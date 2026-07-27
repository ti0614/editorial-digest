"""HTTPでHTMLを取得するための薄いラッパー。"""
from __future__ import annotations

import requests
from requests.utils import get_encoding_from_headers

USER_AGENT = "EditorialDigestBot/0.1 (personal research use; contact: t.iizuka188@gmail.com)"
REQUEST_TIMEOUT = 15


def fetch_html(url: str, extra_headers: dict[str, str] | None = None) -> str:
    """extra_headersは、一部サイトのページ送りがXHRリクエストかどうかで
    応答内容を変える場合（例: 毎日新聞、X-Requested-With: XMLHttpRequestが
    必要）に使う追加ヘッダー。"""
    headers = {"User-Agent": USER_AGENT, **(extra_headers or {})}
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    if not get_encoding_from_headers(resp.headers):
        # HTTPヘッダーがcharsetを明示していないサイト（Shift-JIS等をヘッダーでは
        # 宣言しないサイト、例: 奈良新聞）向けのフォールバック。ヘッダーが明示
        # している場合はapparent_encoding（chardet系の推定）が誤判定することが
        # あるため（例: 西日本新聞でptcp154と誤検出）、その場合は上書きしない。
        resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text
