"""HTTPでHTMLを取得するための薄いラッパー。"""
from __future__ import annotations

import requests

USER_AGENT = "EditorialDigestBot/0.1 (personal research use; contact: set-your-contact-here)"
REQUEST_TIMEOUT = 15


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text
