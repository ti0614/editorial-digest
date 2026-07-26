#!/usr/bin/env python3
"""新聞各社の社説一覧ページを巡回し、直近1週間分のタイトル・リンク・日付を
まとめたWebページ（output/digest.html）を生成するツール。

著作権・利用規約への配慮として、記事本文は取得・保存しない
（タイトル・リンク・日付のみを収集する）。生成したHTMLはそのままブラウザで
開くか、任意の静的ホスティング（Claude Artifacts、GitHub Pages 等）に
公開して閲覧する想定。

使い方:
    python main.py check          # 各ソースの疎通確認（取得件数/エラーを表示するだけ）
    python main.py run            # 全ソースを取得し output/digest.html と digest.json を生成
    python main.py run --only 朝日新聞 毎日新聞
    python main.py today          # 全ソースを取得し当日分のみの output/today.html を生成
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

import render
from extract import Item, enrich_missing_times, extract_items
from fetch import fetch_html
from pubdate import JST, is_same_day
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
    same_day_only: bool = False,
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
        items = extract_items(html, index_url, source, reference_date)
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
    same_day_only: bool = False,
) -> Iterator[SourceResult]:
    """全ソースを順に取得し、結果を1件ずつ返す。

    次のソースを取得する前に robots.txt の Crawl-delay（既定は
    RobotsChecker の待機秒数）だけ待機し、サイトへの負荷を抑える。
    """
    for i, source in enumerate(sources):
        yield process_source(source, reference_date, robots, fetch_times=fetch_times, same_day_only=same_day_only)
        if i < len(sources) - 1:
            time.sleep(robots.interval_after(source["index_url"]))


def run_check(only: list[str] | None) -> int:
    sources = load_sources(only)
    robots = RobotsChecker()
    reference_date = date.today()

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


def _fetch_and_write(
    only: list[str] | None, run_date: date, *, same_day_only: bool,
    json_suffix: str, html_filename: str, render_fn,
) -> tuple[list[SourceResult], Path]:
    """ソースを取得し、JSONスナップショットとHTMLを書き出す（run_digest/run_todayの共通処理）。"""
    sources = load_sources(only)
    robots = RobotsChecker()
    results = list(_iter_results(sources, run_date, robots, fetch_times=True, same_day_only=same_day_only))

    OUTPUT_DIR.mkdir(exist_ok=True)
    json_path = OUTPUT_DIR / f"{run_date.isoformat()}{json_suffix}.json"
    html_path = OUTPUT_DIR / html_filename

    write_json(json_path, run_date, results)
    generated_at = datetime.now(JST)
    html_path.write_text(render_fn(results, run_date, generated_at), encoding="utf-8")
    return results, html_path


def run_digest(only: list[str] | None, run_date: date) -> int:
    results, html_path = _fetch_and_write(
        only, run_date, same_day_only=False,
        json_suffix="", html_filename="digest.html", render_fn=render.render_html,
    )
    ok = sum(1 for r in results if not r.error and not r.skipped_by_robots and r.items)
    print(f"{len(results)} 紙中 {ok} 紙を取得しました -> {html_path}")
    return 0


def run_today(only: list[str] | None, run_date: date) -> int:
    results, html_path = _fetch_and_write(
        only, run_date, same_day_only=True,
        json_suffix="-today", html_filename="today.html", render_fn=render.render_today_html,
    )
    total_items = sum(len(r.items) for r in results)
    ok = sum(1 for r in results if not r.error and not r.skipped_by_robots)
    print(f"{len(results)} 紙中 {ok} 紙を取得（本日分 {total_items} 件）-> {html_path}")
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
    subparser.add_argument("--date", type=date.fromisoformat, default=date.today(), help="基準日 (YYYY-MM-DD)。省略時は本日")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    check_p = sub.add_parser("check", help="各ソースの疎通確認のみ行う（ファイル出力なし）")
    _add_only_argument(check_p)

    run_p = sub.add_parser("run", help="全ソースを取得し output/digest.html を生成する")
    _add_only_argument(run_p)
    _add_date_argument(run_p)

    today_p = sub.add_parser("today", help="全ソースを取得し当日分のみの output/today.html を生成する")
    _add_only_argument(today_p)
    _add_date_argument(today_p)

    args = parser.parse_args()

    if args.command == "check":
        return run_check(args.only)
    if args.command == "run":
        return run_digest(args.only, args.date)
    if args.command == "today":
        return run_today(args.only, args.date)
    return 1


if __name__ == "__main__":
    sys.exit(main())
