#!/usr/bin/env python3
"""日次スナップショットを該当月のアーカイブバンドルへマージする。

CIワークフロー（deploy-today.yml）が `main.py today` の出力
（output/{date}-today.json）を `data`ブランチのチェックアウトへ取り込む際に使う。
アーカイブが日別ファイルだった頃はコピー1回で済んでいたが、月別バンドルでは
既存の当月ファイルを読んで当日分を差し替える必要があるため、シェルではなく
このスクリプトで行う。

    python append_archive_day.py <archive_dir> <output/{date}-today.json>

同じ日付が既に入っている場合は置き換える（1日3回実行され、後の回ほど記事が
揃っているため、常に最新の取得結果を正とする）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from archive_month import upsert_day


def main(archive_dir: Path, snapshot: Path) -> int:
    day = json.loads(snapshot.read_text(encoding="utf-8"))
    if not day.get("date"):
        print(f"ERROR: {snapshot} に date フィールドがありません")
        return 1
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = upsert_day(archive_dir, day)
    items = sum(len(s.get("items") or []) for s in day.get("sources") or [])
    print(f"{day['date']}（記事{items}件）を {path.name} へ取り込みました")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
