#!/usr/bin/env python3
"""archive/配下の月別バンドルから archive/index.json を再生成する。

CIワークフロー（deploy-today.yml）が当日分を該当月のバンドルへマージした直後に
実行し、archive.htmlがfetchする一覧を最新化する。対象ディレクトリは引数で指定
でき、省略時はこのスクリプトと同階層の archive/ を使う（ローカルでの動作確認用）。

出力は月一覧と日付一覧の両方を持つ:

    {"months": ["2026-08", ...], "dates": ["2026-08-01", ...]}

archive.htmlは months をページ送りの単位に、dates を日付入力の上限・下限と
「全◯日分」の表示に使う。months は dates から導出もできるが、ページ送りの
単位をデータ側で明示しておく方が読み手に分かりやすいため両方を書き出す。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from archive_month import iter_months

DEFAULT_ARCHIVE_DIR = Path(__file__).parent / "archive"


def build_index(archive_dir: Path) -> None:
    months: list[str] = []
    dates: list[str] = []
    for path in iter_months(archive_dir):
        payload = json.loads(path.read_text(encoding="utf-8"))
        months.append(path.stem)
        dates.extend(day["date"] for day in payload.get("days") or [])
    index_path = archive_dir / "index.json"
    index_path.write_text(
        json.dumps(
            {"months": sorted(months), "dates": sorted(dates)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ARCHIVE_DIR
    build_index(target)
