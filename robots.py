"""robots.txt の許可判定と Crawl-delay を、オリジンごとにキャッシュしながら扱うモジュール。"""
from __future__ import annotations

import urllib.robotparser as robotparser
from urllib.parse import urljoin, urlparse

from fetch import USER_AGENT, fetch_html

DEFAULT_REQUEST_INTERVAL_SEC = 2.0  # 同一実行内でもサイトに負荷をかけすぎないための間隔


class RobotsChecker:
    """robots.txt の取得結果をオリジン単位でキャッシュし、許可判定・待機時間を提供する。"""

    def __init__(self, default_interval_sec: float = DEFAULT_REQUEST_INTERVAL_SEC) -> None:
        self._default_interval_sec = default_interval_sec
        self._cache: dict[str, robotparser.RobotFileParser] = {}

    def _get_parser(self, url: str) -> robotparser.RobotFileParser:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._cache.get(origin)
        if rp is None:
            rp = robotparser.RobotFileParser()
            rp.set_url(urljoin(origin, "/robots.txt"))
            try:
                # rp.read() は urllib 経由でUTF-8決め打ちのデコードを行い、
                # Shift-JIS等で配信されているrobots.txt（例: 奈良新聞）で
                # UnicodeDecodeError になることがあるため、fetch_html を使って
                # 自前取得してから渡す。
                rp.parse(fetch_html(rp.url).splitlines())
            except Exception:
                pass
            self._cache[origin] = rp
        return rp

    def allows(self, url: str) -> bool:
        rp = self._get_parser(url)
        if rp.mtime() == 0:
            # robots.txt が読めなかった場合は安全側に倒して許可しない
            return False
        return rp.can_fetch(USER_AGENT, url)

    def crawl_delay_sec(self, url: str) -> float:
        """このURLのオリジンの robots.txt が Crawl-delay を指定していればその秒数を返す（無指定なら0）。"""
        rp = self._get_parser(url)
        delay = rp.crawl_delay(USER_AGENT)
        return float(delay) if delay else 0.0

    def interval_after(self, url: str) -> float:
        """このURLを取得した直後に空けるべき待機秒数。

        既定の待機秒数を基本としつつ、アクセス先の robots.txt が
        Crawl-delay を指定している場合はそちらを優先する（例: 茨城新聞は30秒）。
        """
        return max(self._default_interval_sec, self.crawl_delay_sec(url))
