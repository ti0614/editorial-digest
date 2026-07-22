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
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.robotparser as robotparser
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

import render
from pubdate import within_digest_window, parse_published_time, parse_published_date

# <time>タグが無いサイト向けのフォールバック: 本文中の「日付+時刻」表記
# （例: 「2026年7月22日 05時05分」「2026/07/22(水) 03:00」）を拾う。
_DATETIME_TEXT_PATTERN = re.compile(
    r"\d{4}[年/.]\d{1,2}[月/.]\d{1,2}日?[^\d]{0,10}\d{1,2}[:時]\d{2}分?"
)
_JST = timezone(timedelta(hours=9))

USER_AGENT = "EditorialDigestBot/0.1 (personal research use; contact: set-your-contact-here)"
REQUEST_TIMEOUT = 15
REQUEST_INTERVAL_SEC = 2.0  # 同一実行内でもサイトに負荷をかけすぎないための間隔
SOURCES_FILE = Path(__file__).parent / "sources.yaml"
OUTPUT_DIR = Path(__file__).parent / "output"

_robots_cache: dict[str, robotparser.RobotFileParser] = {}


@dataclass
class Item:
    title: str
    link: str
    published: str | None
    paid: bool = False


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


def load_sources() -> list[dict]:
    with open(SOURCES_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["sources"]


def _get_robot_parser(url: str) -> robotparser.RobotFileParser:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    rp = _robots_cache.get(origin)
    if rp is None:
        rp = robotparser.RobotFileParser()
        rp.set_url(urljoin(origin, "/robots.txt"))
        try:
            # rp.read() は urllib 経由でUTF-8決め打ちのデコードを行い、
            # Shift-JIS等で配信されているrobots.txt（例: 奈良新聞）で
            # UnicodeDecodeError になることがあるため、fetch_html と同じ
            # requests ベースの文字コード自動判定で自前取得してから渡す。
            resp = requests.get(rp.url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
            resp.encoding = resp.apparent_encoding or resp.encoding
            rp.parse(resp.text.splitlines())
        except Exception:
            pass
        _robots_cache[origin] = rp
    return rp


def robots_allows(url: str) -> bool:
    rp = _get_robot_parser(url)
    if rp.mtime() == 0:
        # robots.txt が読めなかった場合は安全側に倒して許可しない
        return False
    return rp.can_fetch(USER_AGENT, url)


def crawl_delay_sec(url: str) -> float:
    """robots.txt が Crawl-delay を指定している場合はその秒数を返す（無指定なら0）。"""
    rp = _get_robot_parser(url)
    delay = rp.crawl_delay(USER_AGENT)
    return float(delay) if delay else 0.0


def interval_after(source: dict) -> float:
    """このソースを取得した直後に空けるべき待機秒数。

    既定の REQUEST_INTERVAL_SEC を基本としつつ、サイトの robots.txt が
    Crawl-delay を指定している場合はそちらを優先する（例: 茨城新聞は30秒）。
    """
    return max(REQUEST_INTERVAL_SEC, crawl_delay_sec(source["index_url"]))


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text


def extract_items(html: str, base_url: str, source: dict, reference_date: date) -> list[Item]:
    soup = BeautifulSoup(html, "html.parser")
    nodes = soup.select(source["item_selector"])
    items: list[Item] = []
    seen_titles: set[str] = set()
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
        if title in seen_titles:
            # 同じ紙の一覧内に同一見出しが複数URLで重複掲載されることがある
            # （例: 北國新聞は同じ社説が別記事IDで2件並ぶ）。先勝ちで1件に絞る。
            continue
        seen_titles.add(title)
        if source.get("always_paid"):
            paid = True
        else:
            paid = bool(source.get("paid_selector")) and node.select_one(source["paid_selector"]) is not None
        items.append(Item(title=title, link=link, published=published, paid=paid))
    return items


def _time_from_datetime_attr(value: str | None) -> str | None:
    """<time> タグの datetime 属性から時刻(JST, HH:MM)を取り出す。

    末尾が "Z"（UTC）の場合はJSTに変換してから返す。それ以外
    （オフセット付き・オフセットなしのローカル時刻表記）はそのまま
    HH:MM部分を読み取る（日本の新聞サイトなので基本的にJST表記）。
    """
    if not value:
        return None
    v = value.strip()
    if v.endswith("Z"):
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(_JST)
            return f"{dt.hour:02d}:{dt.minute:02d}"
        except ValueError:
            return None
    return parse_published_time(v)


def _find_time_in_article(html: str, item: Item, reference_date: date) -> str | None:
    """記事個別ページのHTMLから、その記事自身の時刻を探す。

    まず <time> タグを試す。タグの表示テキスト（人間が読む表記なので
    基本的にJST）を優先し、テキストから読み取れない場合のみ datetime
    属性にフォールバックする（Nikkei等はdatetime属性がUTC表記のため、
    テキストより先に読むと9時間ずれた誤った時刻を拾ってしまう）。
    <time> タグで見つからなければ、本文中の「日付+時刻」表記
    （例:「2026年7月22日 05時05分」）にフォールバックする。後者は
    サイドバー等の無関係な日時を拾わないよう、一覧ページ側で分かって
    いるこの記事自身の日付と一致する候補だけを採用する。
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("time"):
        found = parse_published_time(tag.get_text(strip=True))
        if not found:
            found = _time_from_datetime_attr(tag.get("datetime"))
        if found:
            return found

    item_date = parse_published_date(item.published, reference_date)
    if item_date is None:
        return None
    text = re.sub(r"\s+", " ", soup.get_text())
    for m in _DATETIME_TEXT_PATTERN.finditer(text):
        candidate = m.group(0)
        if parse_published_date(candidate, reference_date) == item_date:
            found = parse_published_time(candidate)
            if found:
                return found
    return None


def enrich_missing_times(items: list[Item], source: dict, reference_date: date) -> None:
    """一覧ページの日付表記に時刻が含まれない記事について、記事個別ページから
    時刻を補い published に追記する。

    一覧ページは当日分のみ時刻付きで、それより前の日の記事は日付のみの
    表記になっているサイトが多い（例: 京都新聞は一覧で「7月17日」だが、
    記事ページには <time datetime="2026-07-17 16:05"> がある）。この関数は
    そうした記事だけを対象に個別ページを取得するため、時刻が既に取れて
    いる記事については追加のアクセスをしない。
    """
    for item in items:
        if parse_published_time(item.published):
            continue
        if not robots_allows(item.link):
            continue
        try:
            html = fetch_html(item.link)
        except Exception:
            continue
        finally:
            time.sleep(interval_after(source))
        found_time = _find_time_in_article(html, item, reference_date)
        if found_time:
            item.published = f"{item.published} {found_time}" if item.published else found_time


def process_source(source: dict, reference_date: date, fetch_times: bool = False) -> SourceResult:
    name = source["name"]
    index_url = source["index_url"]
    category = source.get("category", "社説")
    tier = source.get("tier", "regional")
    unavailable_reason = source.get("unavailable_reason")

    if not robots_allows(index_url):
        return SourceResult(
            name=name, category=category, tier=tier, index_url=index_url,
            skipped_by_robots=True, unavailable_reason=unavailable_reason,
        )

    try:
        html = fetch_html(index_url)
        items = extract_items(html, index_url, source, reference_date)
        if fetch_times:
            enrich_missing_times(items, source, reference_date)
        return SourceResult(
            name=name, category=category, tier=tier, index_url=index_url,
            items=items, unavailable_reason=unavailable_reason,
        )
    except Exception as exc:  # noqa: BLE001 - 1ソースの失敗で全体を止めない
        return SourceResult(
            name=name, category=category, tier=tier, index_url=index_url,
            error=str(exc), unavailable_reason=unavailable_reason,
        )


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
            time.sleep(interval_after(source))
    return 1 if had_problem else 0


def run_digest(only: list[str] | None, run_date: date) -> int:
    sources = load_sources()
    if only:
        sources = [s for s in sources if s["name"] in only]

    results: list[SourceResult] = []
    for i, source in enumerate(sources):
        results.append(process_source(source, run_date, fetch_times=True))
        if i < len(sources) - 1:
            time.sleep(interval_after(source))

    OUTPUT_DIR.mkdir(exist_ok=True)
    json_path = OUTPUT_DIR / f"{run_date.isoformat()}.json"
    html_path = OUTPUT_DIR / "digest.html"

    write_json(json_path, run_date, results)
    html_path.write_text(render.render_html(results, run_date), encoding="utf-8")

    ok = sum(1 for r in results if not r.error and not r.skipped_by_robots and r.items)
    print(f"{len(results)} 紙中 {ok} 紙を取得しました -> {html_path}")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    check_p = sub.add_parser("check", help="各ソースの疎通確認のみ行う（ファイル出力なし）")
    check_p.add_argument("--only", nargs="*", help="対象を新聞社名で絞り込む")

    run_p = sub.add_parser("run", help="全ソースを取得し output/digest.html を生成する")
    run_p.add_argument("--only", nargs="*", help="対象を新聞社名で絞り込む")
    run_p.add_argument("--date", type=date.fromisoformat, default=date.today(), help="基準日 (YYYY-MM-DD)。省略時は本日")

    args = parser.parse_args()

    if args.command == "check":
        return run_check(args.only)
    if args.command == "run":
        return run_digest(args.only, args.date)
    return 1


if __name__ == "__main__":
    sys.exit(main())
