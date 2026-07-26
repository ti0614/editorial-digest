"""HTTPでHTMLを取得するための薄いラッパー。"""
from __future__ import annotations

import requests
from requests.utils import get_encoding_from_headers

USER_AGENT = "EditorialDigestBot/0.1 (personal research use; contact: set-your-contact-here)"
REQUEST_TIMEOUT = 15


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    if not get_encoding_from_headers(resp.headers):
        # HTTPヘッダーがcharsetを明示していないサイト（Shift-JIS等をヘッダーでは
        # 宣言しないサイト、例: 奈良新聞）向けのフォールバック。ヘッダーが明示
        # している場合はapparent_encoding（chardet系の推定）が誤判定することが
        # あるため（例: 西日本新聞でptcp154と誤検出）、その場合は上書きしない。
        resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text
