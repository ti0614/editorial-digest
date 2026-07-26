#!/usr/bin/env python3
"""アーカイブの過去分バックフィル用スクリプト（一回限りの手動実行を想定）。

通常運用（main.py today）は直近1日分しか archive/ に積み上がらないが、
各紙の一覧ページには通常2〜3週間分の記事がまだ残っている。このスクリプトは
広いウィンドウ（BACKFILL_WINDOW_DAYS）で一度だけ全ソースを取得し、記事ごとの
日付で archive/{date}.json 相当のJSONへ振り分けて書き出す。

一覧ページに実際に残っている範囲より過去には遡れない（本文を保存しない
方針上、それ以上の情報源が無いため）。取得できるのは実行時点で各紙サイトが
公開している範囲まで。

時刻補完（enrich_missing_times）は行わない —— 対象記事数が通常運用の
数倍〜十数倍になり、記事個別ページへの追加アクセスが大きく増えてしまうため。
そのため過去日分は時刻無し（日付のみ）でarchive.html上は表示される。

使い方:
    python backfill_archive.py                       # archive/ に書き出す
    python backfill_archive.py --only 朝日新聞 毎日新聞
    python backfill_archive.py --window-days 14
    python backfill_archive.py --force                # 既存の日付ファイルも上書き
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import date
from pathlib import Path

from main import SourceResult, load_sources, process_source
from pubdate import parse_published_date
from robots import RobotsChecker

BACKFILL_WINDOW_DAYS = 21
ARCHIVE_DIR = Path(__file__).parent / "archive"


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
    parser.add_argument("--archive-dir", type=Path, default=ARCHIVE_DIR, help="書き出し先ディレクトリ（既定 archive/）")
    parser.add_argument("--force", action="store_true", help="既に存在する日付ファイルも上書きする")
    args = parser.parse_args()

    sources = load_sources(args.only)
    robots = RobotsChecker()
    reference_date = date.today()

    results: list[SourceResult] = []
    for i, source in enumerate(sources):
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
