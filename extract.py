"""一覧ページのHTMLから記事情報 (Item) を抽出し、必要に応じて記事個別ページから
時刻を補うモジュール。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from fetch import fetch_html
from pubdate import JST, parse_published_date, parse_published_time, within_digest_window
from robots import RobotsChecker

# <time>タグが無いサイト向けのフォールバック: 本文中の「日付+時刻」表記
# （例: 「2026年7月22日 05時05分」「2026/07/22(水) 03:00」）を拾う。
_DATETIME_TEXT_PATTERN = re.compile(
    r"\d{4}[年/.]\d{1,2}[月/.]\d{1,2}日?[^\d]{0,10}\d{1,2}[:時]\d{2}分?"
)


@dataclass
class Item:
    title: str
    link: str
    published: str | None
    paid: bool = False


def extract_items(html: str, base_url: str, source: dict, reference_date: date) -> list[Item]:
    soup = BeautifulSoup(html, "html.parser")
    nodes = soup.select(source["item_selector"])
    items: list[Item] = []
    seen_titles: set[str] = set()
    title_prefix = source.get("title_prefix")
    title_strip_pattern = source.get("title_strip_pattern")
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
        if title_prefix and not title.startswith(title_prefix):
            # 一覧が専用ページでなく全文検索結果の紙向け: 無関係な記事
            # （例: 岐阜新聞で「社説」を検索すると「会社説明会」等も混ざる）を除外する。
            continue
        if title_strip_pattern:
            title = re.sub(title_strip_pattern, "", title).strip()
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
            dt = datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(JST)
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


def enrich_missing_times(items: list[Item], robots: RobotsChecker, reference_date: date) -> None:
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
        if not robots.allows(item.link):
            continue
        try:
            html = fetch_html(item.link)
        except Exception:
            continue
        finally:
            time.sleep(robots.interval_after(item.link))
        found_time = _find_time_in_article(html, item, reference_date)
        if found_time:
            item.published = f"{item.published} {found_time}" if item.published else found_time
