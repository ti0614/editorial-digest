#!/usr/bin/env python3
"""アーカイブの過去分バックフィル用スクリプト（一回限りの手動実行を想定）。

通常運用（main.py today）は直近1日分しか archive/ に積み上がらないが、
各紙の一覧ページには通常2〜3週間分の記事がまだ残っている。このスクリプトは
広いウィンドウ（BACKFILL_WINDOW_DAYS）で一度だけ全ソースを取得し、記事ごとの
日付で archive/{date}.json 相当のJSONへ振り分けて書き出す。

一覧ページに実際に残っている範囲より過去には遡れない（本文を保存しない
方針上、それ以上の情報源が無いため）。取得できるのは実行時点で各紙サイトが
公開している範囲まで。ただし`sources.yaml`でページ送り設定を持つ紙に
ついては、ウィンドウ分を使い切るまで次ページを自動で追加取得する。ページ送り
方式は4通り対応している —— クエリパラメータ方式（`pagination_param`、例:
"page"、朝日新聞は?id=16&page=Nで151ページ、西日本新聞は?page=Nで157ページ
まで一覧ページ自体が持っていることを2026-07-26に確認）、パス方式
（`pagination_path_template`、例: "/editorial/{page}"、毎日新聞・宮崎日日
新聞・琉球新報等）、パス方式＋JSON包装（`pagination_response_json_field`、
読売新聞のAJAX「さらに読み込む」がHTML断片ではなく{"contents": "...html..."}
形式のJSONで返る）、JSON配列そのもの（`pagination_json_url_template`、
産経新聞のFusion CMS content-apiのようにHTMLですらなく構造化JSON配列で
返る）。各方式の詳細は`_paginated_url`/`_fetch_with_pagination`/
`_fetch_json_items_with_pagination`のdocstring参照。パス方式のうち毎日新聞は
ページ送りがXHRリクエストで、`pagination_headers`（例: X-Requested-With:
XMLHttpRequest）が無いと通常のHTMLが返り、かつXHR応答は一覧の外側コンテナ
（<ul class="articlelist">）を含まない断片HTMLなので
`pagination_wrap_fragment: true`でitem_selectorの先頭トークンから外側
コンテナを組み立てて包み直している。通常の`check`/`today`コマンドは
直近7日分（`check`の既定）または当日分（`today`）しか見ないため1ページ目
のみで足り、この機構はbackfill専用（main.process_sourceは変更しない）。

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
import re
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests

from extract import Item, extract_items
from fetch import fetch_html
from main import SourceResult, load_sources, process_source, source_status_label, write_json
from pubdate import JST, parse_published_date, today_jst, within_window
from robots import RobotsChecker

BACKFILL_WINDOW_DAYS = 21
MAX_PAGINATION_PAGES = 60  # 無限ループ防止の安全上限
RATE_LIMIT_RETRY_DELAYS_SEC = (15, 30, 60)  # 403時のリトライ待機秒数（段階的に伸ばす）
ARCHIVE_DIR = Path(__file__).parent / "archive"


def _paginated_url(source: dict, page: int) -> str:
    """ページ送り先のURLを組み立てる。

    大半のサイトはクエリパラメータ方式（pagination_param、例: ?page=2）だが、
    毎日新聞や宮崎日日新聞等はパス方式（pagination_path_template、例:
    /editorial/{page}）。両対応にしている。読売新聞のようにAJAXのページ番号が
    「一覧ページ本体の続き」から0/1始まりで振られているサイトは、
    pagination_page_offset（例: -1）で調整できるようにしている
    （backfillのpage=2が本体の直後の1ページ目に相当する場合、offset=-1で
    ajax上のページ番号1に変換する）。
    """
    if "pagination_path_template" in source:
        effective_page = page + source.get("pagination_page_offset", 0)
        return urljoin(source["index_url"], source["pagination_path_template"].format(page=effective_page))
    param = source["pagination_param"]
    index_url = source["index_url"]
    sep = "&" if "?" in index_url else "?"
    return f"{index_url}{sep}{param}={page}"


def _wrap_fragment_html(html: str, item_selector: str) -> str:
    """XHRページ送りが外側コンテナ抜きの断片HTMLを返すサイト向け（例: 毎日新聞、
    通常は<ul class="articlelist">の中身の<li>群だが、ページ2以降のXHR応答には
    <ul class="articlelist">自体が含まれない）。item_selectorの先頭トークン
    （例: "ul.articlelist"）から外側コンテナを組み立てて断片を包み直し、
    通常のextract_itemsがそのまま使えるようにする。
    """
    container = item_selector.split()[0]
    m = re.match(r"([a-zA-Z0-9]+)((?:\.[\w-]+)*)", container)
    tag = m.group(1)
    classes = m.group(2).lstrip(".").replace(".", " ")
    class_attr = f' class="{classes}"' if classes else ""
    return f"<{tag}{class_attr}>{html}</{tag}>"


def _fetch_html_with_retry(url: str, extra_headers: dict[str, str] | None = None) -> str:
    """403（レート制限の疑い）は間隔を空けてリトライする。

    朝日新聞のページ送りバックフィル中、25ページ目付近で403を受け取ったが
    15秒待って再取得すると成功した実績があり、一時的なレート制限と判断できる。
    リトライを尽くしても403のままの場合や、403以外のHTTPError（404等）は
    そのまま呼び出し側に伝播させる。
    """
    for delay in (0, *RATE_LIMIT_RETRY_DELAYS_SEC):
        if delay:
            time.sleep(delay)
        try:
            return fetch_html(url, extra_headers=extra_headers)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status != 403:
                raise
            last_exc = exc
    raise last_exc


def _fetch_with_pagination(
    source: dict, reference_date: date, robots: RobotsChecker, window_days: int,
    max_pages: int = MAX_PAGINATION_PAGES,
) -> SourceResult:
    """pagination_paramが指定されたソースについて、ウィンドウを使い切るか
    記事が尽きるまで次ページを追加取得する。extract_itemsが既にwindow_days
    で絞り込むため、あるページで新規記事が0件になった時点でそれより古い
    ページを見ても意味が無い（日付降順に並んでいるため）と判断して止める。
    一覧ページ自体の終端（404）に達した場合もそこで打ち切る。403はレート
    制限とみなしリトライし（_fetch_html_with_retry）、それでも解消しなければ
    ここまでの結果を保ったままエラーとして記録する（404と違い、まだ続きが
    ある可能性が高いため静かに「完了」扱いにはしない）。
    """
    name = source["name"]
    index_url = source["index_url"]
    category = source.get("category", "社説")
    tier = source.get("tier", "regional")
    unavailable_reason = source.get("unavailable_reason")
    extra_headers = source.get("pagination_headers")

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
            url = index_url if page == 1 else _paginated_url(source, page)
            if page > 1 and not robots.allows(url):
                break
            try:
                html = _fetch_html_with_retry(url, extra_headers=extra_headers if page > 1 else None)
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    # 一覧ページ自体の終端に達した。単に「もう次のページが
                    # 無い」だけなので、エラー扱いにはせずここまでの結果で
                    # 打ち切る。
                    break
                raise  # 403のリトライも尽きた場合等はエラーとして記録する
            if page > 1 and source.get("pagination_response_json_field"):
                # 読売新聞のように、ページ送り応答がHTML断片そのものではなく
                # {"contents": "...html...", "has_next_data": true} 形式のJSONで
                # 返るサイト向け。指定フィールドの値をHTML断片として扱う。
                html = json.loads(html)[source["pagination_response_json_field"]]
            if page > 1 and source.get("pagination_wrap_fragment"):
                html = _wrap_fragment_html(html, source["item_selector"])
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


def _get_nested(d: dict, dotted_path: str):
    """"a.b.c"形式のパスでネストした辞書から値を取り出す。"""
    for key in dotted_path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def _fetch_json_items_with_pagination(
    source: dict, reference_date: date, robots: RobotsChecker, window_days: int,
    max_pages: int = MAX_PAGINATION_PAGES,
) -> SourceResult:
    """産経新聞（Fusion CMS）のように、ページ送り応答がHTMLですらなく構造化
    JSON配列で返るサイト向け。extract_items（CSSセレクタでHTMLをパースする
    前提）は使わず、JSON配列から直接Itemを組み立てる。1ページ目（index_url）
    だけは通常通りHTMLとしてextract_itemsで取得し、2ページ目以降だけこの
    方式に切り替える（1ページ目は別ウィジェット由来のため取得方法が異なる）。

    pagination_offset_base/pagination_offset_stepでoffsetを組み立てる
    （offset = base + (page-2)*step）。産経新聞は一覧ページ本体が既に
    pagination_offset_base件（先頭のウィジェット分）を表示済みで、JSON API
    はその直後から返す設計になっている（サイト自身の埋め込み設定
    feedOffset値と一致することを確認済み）。
    """
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

    items = []
    seen_titles: set[str] = set()
    page = 1
    try:
        while page <= max_pages:
            if page == 1:
                html = _fetch_html_with_retry(index_url)
                page_items = extract_items(html, index_url, source, reference_date, window_days=window_days)
            else:
                offset = source.get("pagination_offset_base", 0) + (page - 2) * source.get("pagination_offset_step", 0)
                url = source["pagination_json_url_template"].format(offset=offset)
                if not robots.allows(url):
                    break
                try:
                    raw = _fetch_html_with_retry(url)
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 404:
                        break
                    raise
                data = json.loads(raw)
                elements = _get_nested(data, source["pagination_json_items_path"]) or []
                page_items = []
                for el in elements:
                    title = _get_nested(el, source["pagination_json_title_field"])
                    link = _get_nested(el, source["pagination_json_link_field"])
                    published = _get_nested(el, source["pagination_json_date_field"])
                    if not title or not link:
                        continue
                    link = urljoin(index_url, link)
                    if published:
                        # UTC ISO8601 -> JST変換（<time>のdatetime属性のUTC対応と同じ扱い）
                        try:
                            dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                            if dt.tzinfo is not None:
                                dt = dt.astimezone(JST)
                            published = f"{dt.year}/{dt.month}/{dt.day} {dt.hour}:{dt.minute:02d}"
                        except ValueError:
                            pass
                    if not within_window(published, reference_date, window_days=window_days):
                        continue
                    page_items.append(Item(title=title, link=link, published=published, paid=False))
                if not elements:
                    break
            new_items = [it for it in page_items if it.title not in seen_titles]
            if not new_items:
                break
            seen_titles.update(it.title for it in new_items)
            items.extend(new_items)
            page += 1
            if page <= max_pages:
                time.sleep(robots.interval_after(index_url))
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
        if source.get("pagination_json_url_template"):
            result = _fetch_json_items_with_pagination(source, reference_date, robots, window_days=args.window_days, max_pages=args.max_pages)
        elif source.get("pagination_param") or source.get("pagination_path_template"):
            result = _fetch_with_pagination(source, reference_date, robots, window_days=args.window_days, max_pages=args.max_pages)
        else:
            result = process_source(source, reference_date, robots, fetch_times=False, window_days=args.window_days)
        print(f"[{result.name}] {source_status_label(result)}")
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
        write_json(path, d, by_date[d])
        written += 1
        total_items = sum(len(r.items) for r in by_date[d])
        print(f"{d.isoformat()}: {total_items} 件 -> {path}")

    print(f"{written} 日分を書き出し、{skipped} 日分は既存ファイルのためスキップしました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
