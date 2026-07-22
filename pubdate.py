"""各紙の published 表記（書式がバラバラ）を実日付に正規化するユーティリティ。

main.py（取得・直近7日間フィルタ）と render.py（Webページの日付見出し
グルーピング）の両方から共通で使う。
"""
from __future__ import annotations

import re
from datetime import date, timedelta

DIGEST_WINDOW_DAYS = 7  # 直近何日分の記事を対象とするか

# 観測された表記例:
#   "2026年7月22日 05時00分" / "2026/7/22 02:02" / "2026.07.21" / "7月22日"
#   "7月21日 07時41分" / "7/22 05:10" / "22日" / "05:00"（時刻のみ＝日付情報なし）
_DATE_PATTERNS = [
    re.compile(r"(?P<y>\d{4})年(?P<m>\d{1,2})月(?P<d>\d{1,2})日"),
    re.compile(r"(?P<y>\d{4})/(?P<m>\d{1,2})/(?P<d>\d{1,2})"),
    re.compile(r"(?P<y>\d{4})\.(?P<m>\d{1,2})\.(?P<d>\d{1,2})"),
    re.compile(r"(?P<m>\d{1,2})月(?P<d>\d{1,2})日"),
    re.compile(r"(?P<m>\d{1,2})/(?P<d>\d{1,2})(?:\s|$)"),
]
_DAY_ONLY_PATTERN = re.compile(r"^(?P<d>\d{1,2})日")
_TIME_ONLY_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")
_FUTURE_TOLERANCE_DAYS = 2  # スクレイピング時刻とJSTのずれによる誤差の許容幅

_HOUR_MIN_KANJI = re.compile(r"(?P<h>\d{1,2})時(?P<mi>\d{1,2})分")
_HOUR_MIN_COLON = re.compile(r"(?P<h>\d{1,2}):(?P<mi>\d{2})(?!\d)")


def parse_published_time(published: str | None) -> str | None:
    """published文字列から "HH:MM" 形式の時刻部分だけを取り出す（無ければNone）。"""
    if not published:
        return None
    m = _HOUR_MIN_KANJI.search(published)
    if m:
        return f"{int(m.group('h')):02d}:{int(m.group('mi')):02d}"
    m = _HOUR_MIN_COLON.search(published)
    if m:
        return f"{int(m.group('h')):02d}:{m.group('mi')}"
    return None


def parse_published_date(published: str | None, reference_date: date) -> date | None:
    """published文字列をreference_date基準で実日付に正規化する。

    年・月が省略されている表記は reference_date から補い、結果が未来日に
    なる場合は前年・前月とみなして補正する（ただし _FUTURE_TOLERANCE_DAYS
    を超えて未来の場合のみ補正し、1〜2日程度先の日付はタイムゾーン差として
    許容する）。時刻のみの表記（年月日の手がかりが一切ない）は「直近の
    記事」とみなし reference_date を返す。どうしても解釈できない場合は
    None を返す（呼び出し側は取りこぼしを避けるため対象に含めるのが基本）。
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

    上限側には _FUTURE_TOLERANCE_DAYS 分の余裕を持たせている（スクレイピング
    実行時刻と各紙サイトのタイムゾーンのずれを吸収するため）。日付を解釈
    できなかった場合は安全側に倒して対象に含める。
    """
    parsed = parse_published_date(published, reference_date)
    if parsed is None:
        return True
    window_start = reference_date - timedelta(days=DIGEST_WINDOW_DAYS - 1)
    window_end = reference_date + timedelta(days=_FUTURE_TOLERANCE_DAYS)
    return window_start <= parsed <= window_end
