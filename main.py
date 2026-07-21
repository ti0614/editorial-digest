#!/usr/bin/env python3
"""新聞各社の社説一覧ページを巡回し、タイトル・リンク・日付をまとめて
Markdown/JSONダイジェストを生成するツール。

著作権・利用規約への配慮として、記事本文は取得・保存しない
（タイトル・リンク・日付のみを収集する）。

使い方:
    python main.py check          # 各ソースの疎通確認（取得件数/エラーを表示するだけ）
    python main.py run            # 全ソースを取得し output/YYYY-MM-DD.{md,json} を生成
    python main.py run --only 朝日新聞 毎日新聞
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.robotparser as robotparser
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

USER_AGENT = "EditorialDigestBot/0.1 (personal research use; contact: set-your-contact-here)"
REQUEST_TIMEOUT = 15
REQUEST_INTERVAL_SEC = 2.0  # 同一実行内でもサイトに負荷をかけすぎないための間隔
DIGEST_WINDOW_DAYS = 7  # 直近何日分の記事のみを対象とするか
SOURCES_FILE = Path(__file__).parent / "sources.yaml"
OUTPUT_DIR = Path(__file__).parent / "output"

# 各紙の published 表記は書式がバラバラ（例: "2026年7月22日 05時00分",
# "2026/7/22 02:02", "7月22日", "7/22 05:10", "22日", "05:00" のみ 等）。
# reference_date を基準に、年月が省略された表記を補完して実日付へ正規化する。
_DATE_PATTERNS = [
    re.compile(r"(?P<y>\d{4})年(?P<m>\d{1,2})月(?P<d>\d{1,2})日"),
    re.compile(r"(?P<y>\d{4})/(?P<m>\d{1,2})/(?P<d>\d{1,2})"),
    re.compile(r"(?P<m>\d{1,2})月(?P<d>\d{1,2})日"),
    re.compile(r"(?P<m>\d{1,2})/(?P<d>\d{1,2})(?:\s|$)"),
]
_DAY_ONLY_PATTERN = re.compile(r"^(?P<d>\d{1,2})日")
_TIME_ONLY_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")
_FUTURE_TOLERANCE_DAYS = 2  # スクレイピング時刻とJSTのずれによる誤差の許容幅


def parse_published_date(published: str | None, reference_date: date) -> date | None:
    """published文字列をreference_date基準で実日付に正規化する。

    年・月が省略されている表記は reference_date から補い、結果が未来日に
    なる場合は前年・前月とみなして補正する（ただしスクレイピング実行時刻と
    各紙サイトのタイムゾーン差により1日程度先の日付は正常にあり得るため、
    _FUTURE_TOLERANCE_DAYS を超えて未来の場合のみ補正する）。時刻のみの
    表記（年月日の手がかりが一切ない）は「直近の記事」とみなし
    reference_date を返す。どうしても解釈できない場合は None を返す
    （フィルタでは除外しない＝取りこぼしを避ける）。
    """
    if not published:
        return None
    future_limit = reference_date + timedelta(days=_FUTURE_TOLERANCE_DAYS)
    for pat in _DATE_PATTERNS:
        m = pat.search(published)
        if not m:
            continue
        g = m.groupdict()
        year = int(g["y"]) if g.get("y") else reference_date.year
        month, day = int(g["m"]), int(g["d"])
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if not g.get("y") and d > future_limit:
            d = date(year - 1, month, day)
        return d
    m = _DAY_ONLY_PATTERN.match(published)
    if m:
        day = int(m.group("d"))
        year, month = reference_date.year, reference_date.month
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d > future_limit:
            prev_month = month - 1 or 12
            prev_year = year if month > 1 else year - 1
            try:
                d = date(prev_year, prev_month, day)
            except ValueError:
                pass
        return d
    if _TIME_ONLY_PATTERN.match(published):
        return reference_date
    return None


def within_digest_window(published: str | None, reference_date: date) -> bool:
    """直近 DIGEST_WINDOW_DAYS 日以内の記事かどうか判定する。

    スクレイピング実行時刻と各紙サイトのタイムゾーン（JST）のずれにより、
    reference_date より1日先の日付が付いた記事が現れることがあるため、
    上限側には1日分の余裕を持たせている。日付を解釈できなかった場合は
    安全側に倒して対象に含める。
    """
    parsed = parse_published_date(published, reference_date)
    if parsed is None:
        return True
    window_start = reference_date - timedelta(days=DIGEST_WINDOW_DAYS - 1)
    window_end = reference_date + timedelta(days=1)
    return window_start <= parsed <= window_end

_robots_cache: dict[str, robotparser.RobotFileParser] = {}


@dataclass
class Item:
    title: str
    link: str
    published: str | None


@dataclass
class SourceResult:
    name: str
    category: str
    index_url: str
    items: list[Item]
    error: str | None = None
    skipped_by_robots: bool = False


def load_sources() -> list[dict]:
    with open(SOURCES_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["sources"]


def robots_allows(url: str) -> bool:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    rp = _robots_cache.get(origin)
    if rp is None:
        rp = robotparser.RobotFileParser()
        rp.set_url(urljoin(origin, "/robots.txt"))
        try:
            rp.read()
        except Exception:
            # robots.txt が読めない場合は安全側に倒して許可しない
            _robots_cache[origin] = rp
            return False
        _robots_cache[origin] = rp
    return rp.can_fetch(USER_AGENT, url)


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text


def extract_items(html: str, base_url: str, source: dict, reference_date: date) -> list[Item]:
    soup = BeautifulSoup(html, "html.parser")
    nodes = soup.select(source["item_selector"])
    items: list[Item] = []
    for node in nodes:
        title_node = node.select_one(source["title_selector"]) if source.get("title_selector") else node
        link_node = node.select_one(source["link_selector"]) if source.get("link_selector") else node
        date_node = node.select_one(source["date_selector"]) if source.get("date_selector") else None

        if title_node is None or link_node is None:
            continue
        if source.get("title_exclude_selector"):
            for bad in title_node.select(source["title_exclude_selector"]):
                bad.decompose()
        title = title_node.get_text(strip=True)
        href = link_node.get("href")
        if not title or not href:
            continue
        link = urljoin(base_url, href)
        published = date_node.get_text(strip=True) if date_node is not None else None
        if not within_digest_window(published, reference_date):
            continue
        items.append(Item(title=title, link=link, published=published))
    return items


def process_source(source: dict, reference_date: date) -> SourceResult:
    name = source["name"]
    index_url = source["index_url"]
    category = source.get("category", "社説")

    if not robots_allows(index_url):
        return SourceResult(
            name=name, category=category, index_url=index_url,
            items=[], skipped_by_robots=True,
        )

    try:
        html = fetch_html(index_url)
        items = extract_items(html, index_url, source, reference_date)
        return SourceResult(name=name, category=category, index_url=index_url, items=items)
    except Exception as exc:  # noqa: BLE001 - 1ソースの失敗で全体を止めない
        return SourceResult(name=name, category=category, index_url=index_url, items=[], error=str(exc))


def run_check(only: list[str] | None) -> int:
    sources = load_sources()
    if only:
        sources = [s for s in sources if s["name"] in only]

    reference_date = date.today()
    had_problem = False
    for i, source in enumerate(sources):
        result = process_source(source, reference_date)
        status = (
            "ROBOTS_DISALLOWED" if result.skipped_by_robots else
            f"ERROR: {result.error}" if result.error else
            f"OK ({len(result.items)} 件)"
        )
        if result.skipped_by_robots or result.error or len(result.items) == 0:
            had_problem = True
        print(f"[{result.name}] {status}  <- {result.index_url}")
        if i < len(sources) - 1:
            time.sleep(REQUEST_INTERVAL_SEC)
    return 1 if had_problem else 0


def run_digest(only: list[str] | None, run_date: date) -> int:
    sources = load_sources()
    if only:
        sources = [s for s in sources if s["name"] in only]

    results: list[SourceResult] = []
    for i, source in enumerate(sources):
        results.append(process_source(source, run_date))
        if i < len(sources) - 1:
            time.sleep(REQUEST_INTERVAL_SEC)

    OUTPUT_DIR.mkdir(exist_ok=True)
    md_path = OUTPUT_DIR / f"{run_date.isoformat()}.md"
    json_path = OUTPUT_DIR / f"{run_date.isoformat()}.json"

    write_markdown(md_path, run_date, results)
    write_json(json_path, run_date, results)

    ok = sum(1 for r in results if not r.error and not r.skipped_by_robots and r.items)
    print(f"{len(results)} 紙中 {ok} 紙を取得しました -> {md_path}")
    return 0


def write_markdown(path: Path, run_date: date, results: list[SourceResult]) -> None:
    lines = [f"# 社説まとめ {run_date.isoformat()}", ""]
    for r in results:
        lines.append(f"## {r.name}（{r.category}）")
        if r.skipped_by_robots:
            lines.append("- robots.txt により取得を見送りました。")
        elif r.error:
            lines.append(f"- 取得エラー: {r.error}")
        elif not r.items:
            lines.append("- 記事が見つかりませんでした（セレクタ要確認）。")
        else:
            for item in r.items:
                date_part = f"（{item.published}）" if item.published else ""
                lines.append(f"- [{item.title}]({item.link}){date_part}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_json(path: Path, run_date: date, results: list[SourceResult]) -> None:
    payload = {
        "date": run_date.isoformat(),
        "sources": [
            {
                "name": r.name,
                "category": r.category,
                "index_url": r.index_url,
                "error": r.error,
                "skipped_by_robots": r.skipped_by_robots,
                "items": [asdict(i) for i in r.items],
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    check_p = sub.add_parser("check", help="各ソースの疎通確認のみ行う（ファイル出力なし）")
    check_p.add_argument("--only", nargs="*", help="対象を新聞社名で絞り込む")

    run_p = sub.add_parser("run", help="全ソースを取得しダイジェストを生成する")
    run_p.add_argument("--only", nargs="*", help="対象を新聞社名で絞り込む")
    run_p.add_argument("--date", type=date.fromisoformat, default=date.today(), help="出力ファイル名に使う日付 (YYYY-MM-DD)")

    args = parser.parse_args()

    if args.command == "check":
        return run_check(args.only)
    if args.command == "run":
        return run_digest(args.only, args.date)
    return 1


if __name__ == "__main__":
    sys.exit(main())
