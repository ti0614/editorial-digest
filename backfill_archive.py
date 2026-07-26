#!/usr/bin/env python3
"""アーカイブの過去分バックフィル用スクリプト（一回限りの手動実行を想定）。

通常運用（main.py today）は直近1日分しか archive/ に積み上がらないが、
各紙の一覧ページには通常2〜3週間分の記事がまだ残っている。このスクリプトは
広いウィンドウ（BACKFILL_WINDOW_DAYS）で一度だけ全ソースを取得し、記事ごとの
日付で archive/{date}.json 相当のJSONへ振り分けて書き出す。

一覧ページに実際に残っている範囲より過去には遡れない（本文を保存しない
方針上、それ以上の情報源が無いため）。取得できるのは実行時点で各紙サイトが
公開している範囲まで。ただし`sources.yaml`で`pagination_param`（例: "page"）
を指定した紙については、ウィンドウ分を使い切るまで次ページを自動で追加
取得する（朝日新聞は?id=16&page=Nで151ページ、西日本新聞は?page=Nで157
ページまで一覧ページ自体が持っていることを2026-07-26に確認）。通常の
check/run/todayコマンドは直近1週間程度しか見ないため1ページ目のみで足り、
この機構はbackfill専用（main.process_sourceは変更しない）。

時刻補完（enrich_missing_times）は行わない —— 対象記事数が通常運用の
数倍〜十数倍になり、記事個別ページへの追加アクセスが大きく増えてしまうため。
そのため過去日分は時刻無し（日付のみ）でarchive.html上は表示される。

使い方:
    python backfill_archive.py                       # archive/ に書き出す
    python backfill_archive.py --only 朝日新聞 毎日新聞
    python backfill_archive.py --window-days 14
    python backfill_archive.py --force                # 既存の日付ファイルも上書き
    python backfill_archive.py --only 朝日新聞 --window-days 1000 --max-pages 155
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import date
from pathlib import Path

import requests

from extract import extract_items
from fetch import fetch_html
from main import SourceResult, load_sources, process_source
from pubdate import parse_published_date, today_jst
from robots import RobotsChecker

BACKFILL_WINDOW_DAYS = 21
MAX_PAGINATION_PAGES = 60  # 無限ループ防止の安全上限
ARCHIVE_DIR = Path(__file__).parent / "archive"


def _paginated_url(index_url: str, param: str, page: int) -> str:
    sep = "&" if "?" in index_url else "?"
    return f"{index_url}{sep}{param}={page}"


def _fetch_with_pagination(
    source: dict, reference_date: date, robots: RobotsChecker, window_days: int,
    max_pages: int = MAX_PAGINATION_PAGES,
) -> SourceResult:
    """pagination_paramが指定されたソースについて、ウィンドウを使い切るか
    記事が尽きるまで次ページを追加取得する。extract_itemsが既にwindow_days
    で絞り込むため、あるページで新規記事が0件になった時点でそれより古い
    ページを見ても意味が無い（日付降順に並んでいるため）と判断して止める。
    一覧ページ自体の終端（404等）に達した場合もそこで打ち切る。
    """
    name = source["name"]
    index_url = source["index_url"]
    category = source.get("category", "社説")
    tier = source.get("tier", "regional")
    unavailable_reason = source.get("unavailable_reason")
    param = source["pagination_param"]

    if not robots.allows(index_url):
        return SourceResult(
            name=name, category=category, tier=tier, index_url=index_url,
            skipped_by_robots=True, unavailable_reason=unavailable_reason,
        )

    items = []
    seen_titles: set[str] = set()
    page = 1
    try:
        while page <= max_pages:
            url = index_url if page == 1 else _paginated_url(index_url, param, page)
            if page > 1 and not robots.allows(url):
                break
            try:
                html = fetch_html(url)
            except requests.HTTPError:
                # 一覧ページ自体の終端（404等）に達した。単に「もう次の
                # ページが無い」だけなので、エラー扱いにはせずここまでの
                # 結果で打ち切る（それ以外の通信エラーは外側で処理する）。
                break
            page_items = extract_items(html, url, source, reference_date, window_days=window_days)
            new_items = [it for it in page_items if it.title not in seen_titles]
            if not new_items:
                break
            seen_titles.update(it.title for it in new_items)
            items.extend(new_items)
            page += 1
            if page <= max_pages:
                time.sleep(robots.interval_after(url))
        return SourceResult(
            name=name, category=category, tier=tier, index_url=index_url,
            items=items, unavailable_reason=unavailable_reason,
        )
    except Exception as exc:  # noqa: BLE001 - 1ソースの失敗で全体を止めない
        return SourceResult(
            name=name, category=category, tier=tier, index_url=index_url,
            items=items, error=str(exc), unavailable_reason=unavailable_reason,
        )


def _split_by_date(results: list[SourceResult], reference_date: date) -> dict[date, list[SourceResult]]:
    """各SourceResultのitemsを実際の記事日付で日付ごとに振り分け直す。

    同じ紙・同じメタデータ（error/skipped_by_robots等）を保ちつつ、
    itemsだけをその日付分に絞ったSourceResultを日付ごとに作る。
    """
    buckets_by_source: dict[str, dict[date, list]] = {}
    all_dates: set[date] = set()
    for r in results:
        buckets: dict[date, list] = defaultdict(list)
        for it in r.items:
            d = parse_published_date(it.published, reference_date) or reference_date
            buckets[d].append(it)
            all_dates.add(d)
        buckets_by_source[r.name] = buckets

    by_date: dict[date, list[SourceResult]] = {}
    for d in all_dates:
        by_date[d] = [
            SourceResult(
                name=r.name, category=r.category, tier=r.tier, index_url=r.index_url,
                items=buckets_by_source[r.name].get(d, []),
                error=r.error, skipped_by_robots=r.skipped_by_robots,
                unavailable_reason=r.unavailable_reason,
            )
            for r in results
        ]
    return by_date


def _write_archive_json(path: Path, day: date, results: list[SourceResult]) -> None:
    payload = {
        "date": day.isoformat(),
        "sources": [
            {
                "name": r.name,
                "category": r.category,
                "tier": r.tier,
                "index_url": r.index_url,
                "error": r.error,
                "skipped_by_robots": r.skipped_by_robots,
                "unavailable_reason": r.unavailable_reason,
                "items": [asdict(i) for i in r.items],
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", help="対象を新聞社名で絞り込む")
    parser.add_argument("--window-days", type=int, default=BACKFILL_WINDOW_DAYS, help=f"何日分遡るか（既定 {BACKFILL_WINDOW_DAYS}）")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGINATION_PAGES, help=f"pagination_param指定ソースで最大何ページ追うか（既定 {MAX_PAGINATION_PAGES}）")
    parser.add_argument("--archive-dir", type=Path, default=ARCHIVE_DIR, help="書き出し先ディレクトリ（既定 archive/）")
    parser.add_argument("--force", action="store_true", help="既に存在する日付ファイルも上書きする")
    args = parser.parse_args()

    sources = load_sources(args.only)
    robots = RobotsChecker()
    reference_date = today_jst()

    results: list[SourceResult] = []
    for i, source in enumerate(sources):
        if source.get("pagination_param"):
            result = _fetch_with_pagination(source, reference_date, robots, window_days=args.window_days, max_pages=args.max_pages)
        else:
            result = process_source(source, reference_date, robots, fetch_times=False, window_days=args.window_days)
        status = (
            "ROBOTS_DISALLOWED" if result.skipped_by_robots else
            f"ERROR: {result.error}" if result.error else
            f"OK ({len(result.items)} 件)"
        )
        print(f"[{result.name}] {status}")
        results.append(result)
        if i < len(sources) - 1:
            time.sleep(robots.interval_after(source["index_url"]))

    by_date = _split_by_date(results, reference_date)
    args.archive_dir.mkdir(exist_ok=True)

    written, skipped = 0, 0
    for d in sorted(by_date):
        path = args.archive_dir / f"{d.isoformat()}.json"
        if path.exists() and not args.force:
            skipped += 1
            continue
        _write_archive_json(path, d, by_date[d])
        written += 1
        total_items = sum(len(r.items) for r in by_date[d])
        print(f"{d.isoformat()}: {total_items} 件 -> {path}")

    print(f"{written} 日分を書き出し、{skipped} 日分は既存ファイルのためスキップしました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
