#!/usr/bin/env python3
"""新聞各社の社説一覧ページを巡回し、当日分のタイトル・リンク・日付を
まとめたWebページ（output/today.html）を生成するツール。

著作権・利用規約への配慮として、記事本文は取得・保存しない
（タイトル・リンク・日付のみを収集する）。生成したHTMLはそのままブラウザで
開くか、任意の静的ホスティング（Claude Artifacts、GitHub Pages 等）に
公開して閲覧する想定。

使い方:
    python main.py check          # 各ソースの疎通確認（取得件数/エラーを表示するだけ）
    python main.py today          # 全ソースを取得し当日分のみの output/today.html を生成
    python main.py today --only 朝日新聞 毎日新聞
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import yaml

import render
from extract import Item, enrich_missing_times, extract_items
from fetch import fetch_html
from pubdate import DEFAULT_WINDOW_DAYS, is_same_day, today_jst
from robots import RobotsChecker

SOURCES_FILE = Path(__file__).parent / "sources.yaml"
OUTPUT_DIR = Path(__file__).parent / "output"


@dataclass
class SourceResult:
    name: str
    category: str
    tier: str
    index_url: str
    items: list[Item] = field(default_factory=list)
    error: str | None = None
    skipped_by_robots: bool = False
    unavailable_reason: str | None = None


def load_sources(only: list[str] | None = None) -> list[dict]:
    with open(SOURCES_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    sources = data["sources"]
    if only:
        sources = [s for s in sources if s["name"] in only]
    return sources


def process_source(
    source: dict, reference_date: date, robots: RobotsChecker, fetch_times: bool = False,
    same_day_only: bool = False, window_days: int = DEFAULT_WINDOW_DAYS,
) -> SourceResult:
    name = source["name"]
    index_url = source["index_url"]
    category = source.get("category", "社説")
    tier = source.get("tier", "regional")
    unavailable_reason = source.get("unavailable_reason")

    if not robots.allows(index_url):
        return SourceResult(
            name=name, category=category, tier=tier, index_url=index_url,
            skipped_by_robots=True, unavailable_reason=unavailable_reason,
        )

    try:
        html = fetch_html(index_url)
        items = extract_items(html, index_url, source, reference_date, window_days=window_days)
        if same_day_only:
            # 当日版では対象外の記事のために個別ページへ追加アクセスしない
            # よう、時刻補完(enrich_missing_times)の前に当日分へ絞り込む。
            items = [it for it in items if is_same_day(it.published, reference_date)]
        if fetch_times:
            enrich_missing_times(items, robots, reference_date)
        return SourceResult(
            name=name, category=category, tier=tier, index_url=index_url,
            items=items, unavailable_reason=unavailable_reason,
        )
    except Exception as exc:  # noqa: BLE001 - 1ソースの失敗で全体を止めない
        return SourceResult(
            name=name, category=category, tier=tier, index_url=index_url,
            error=str(exc), unavailable_reason=unavailable_reason,
        )


def _iter_results(
    sources: list[dict], reference_date: date, robots: RobotsChecker, fetch_times: bool,
    same_day_only: bool = False, window_days: int = DEFAULT_WINDOW_DAYS,
) -> Iterator[SourceResult]:
    """全ソースを順に取得し、結果を1件ずつ返す。

    次のソースを取得する前に robots.txt の Crawl-delay（既定は
    RobotsChecker の待機秒数）だけ待機し、サイトへの負荷を抑える。
    """
    for i, source in enumerate(sources):
        yield process_source(
            source, reference_date, robots, fetch_times=fetch_times,
            same_day_only=same_day_only, window_days=window_days,
        )
        if i < len(sources) - 1:
            time.sleep(robots.interval_after(source["index_url"]))


def run_check(only: list[str] | None) -> int:
    sources = load_sources(only)
    robots = RobotsChecker()
    reference_date = today_jst()

    had_problem = False
    for result in _iter_results(sources, reference_date, robots, fetch_times=False):
        status = (
            "ROBOTS_DISALLOWED" if result.skipped_by_robots else
            f"ERROR: {result.error}" if result.error else
            f"OK ({len(result.items)} 件)"
        )
        if result.skipped_by_robots or result.error or not result.items:
            had_problem = True
        print(f"[{result.name}] {status}  <- {result.index_url}")
    return 1 if had_problem else 0


def run_today(only: list[str] | None, run_date: date) -> int:
    sources = load_sources(only)
    robots = RobotsChecker()
    results = list(_iter_results(sources, run_date, robots, fetch_times=True, same_day_only=True))

    OUTPUT_DIR.mkdir(exist_ok=True)
    json_path = OUTPUT_DIR / f"{run_date.isoformat()}-today.json"
    html_path = OUTPUT_DIR / "today.html"

    write_json(json_path, run_date, results)
    html_path.write_text(render.render_today_html(results, run_date), encoding="utf-8")

    total_items = sum(len(r.items) for r in results)
    ok = sum(1 for r in results if not r.error and not r.skipped_by_robots)
    print(f"{len(results)} 紙中 {ok} 紙を取得（本日分 {total_items} 件）-> {html_path}")
    return 0


def run_archive_page() -> int:
    """output/archive.html（アーカイブ検索ページの骨格）を生成する。

    このページ自体はスクレイピング結果を埋め込まず、archive/配下のJSON
    スナップショットをブラウザ側でfetchして検索・表示する（render.render_archive_html
    のdocstring参照）ため、ソース取得は行わない。
    """
    OUTPUT_DIR.mkdir(exist_ok=True)
    html_path = OUTPUT_DIR / "archive.html"
    html_path.write_text(render.render_archive_html(), encoding="utf-8")
    print(f"アーカイブ検索ページを生成しました -> {html_path}")
    return 0


def write_json(path: Path, run_date: date, results: list[SourceResult]) -> None:
    payload = {
        "date": run_date.isoformat(),
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


def _add_only_argument(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--only", nargs="*", help="対象を新聞社名で絞り込む")


def _add_date_argument(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--date", type=date.fromisoformat, default=today_jst(), help="基準日 (YYYY-MM-DD)。省略時は本日（JST基準）")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    check_p = sub.add_parser("check", help="各ソースの疎通確認のみ行う（ファイル出力なし）")
    _add_only_argument(check_p)

    today_p = sub.add_parser("today", help="全ソースを取得し当日分のみの output/today.html を生成する")
    _add_only_argument(today_p)
    _add_date_argument(today_p)

    sub.add_parser("archive-page", help="output/archive.html（アーカイブ検索ページの骨格）を生成する（ソース取得なし）")

    args = parser.parse_args()

    if args.command == "check":
        return run_check(args.only)
    if args.command == "today":
        return run_today(args.only, args.date)
    if args.command == "archive-page":
        return run_archive_page()
    return 1


if __name__ == "__main__":
    sys.exit(main())
