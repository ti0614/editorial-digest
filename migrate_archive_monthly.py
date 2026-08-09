#!/usr/bin/env python3
"""archive/{date}.json を archive/{YYYY-MM}.json へまとめる一回限りの移行CLI。

`data`ブランチのチェックアウトを対象に一度だけ実行する想定（backfill_archive.py
と同じ、通常運用には乗らない使い切りスクリプトの位置づけ）。既定では変換結果の
検証のみ行い、--apply を付けたときだけ日別ファイルを削除して置き換える。

    python migrate_archive_monthly.py /path/to/data-branch/archive          # 検証のみ
    python migrate_archive_monthly.py /path/to/data-branch/archive --apply  # 置き換え
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from archive_month import dump_month, is_month_name, month_of, month_path


def _is_day_name(stem: str) -> bool:
    return len(stem) == len("YYYY-MM-DD") and stem.count("-") == 2 and stem != "index"


def _count_items(sources: list[dict]) -> int:
    return sum(len(s.get("items") or []) for s in sources)


def migrate(archive_dir: Path, apply: bool) -> int:
    day_files = sorted(p for p in archive_dir.glob("*.json") if _is_day_name(p.stem))
    if not day_files:
        print("日別ファイルが見つかりません（移行済みの可能性があります）")
        return 1

    by_month: dict[str, list[dict]] = defaultdict(list)
    before_items = 0
    for path in day_files:
        day = json.loads(path.read_text(encoding="utf-8"))
        if day.get("date") != path.stem:
            # ファイル名と中身のdateがずれていると、移行後にどちらを正とするか
            # 判断できなくなるため、黙って続けず落とす。
            print(f"ERROR: {path.name} の date フィールドが {day.get('date')!r} でファイル名と一致しません")
            return 1
        before_items += _count_items(day.get("sources") or [])
        by_month[month_of(day["date"])].append(day)

    print(f"移行前: 日別 {len(day_files)}ファイル / {len(by_month)}ヶ月 / 記事 {before_items}件")

    after_days = after_items = 0
    for month, days in sorted(by_month.items()):
        payload = {"month": month, "days": days}
        if apply:
            dump_month(month_path(archive_dir, month), payload)
        after_days += len(days)
        after_items += sum(_count_items(d.get("sources") or []) for d in days)

    print(f"移行後: 月別 {len(by_month)}ファイル / {after_days}日分 / 記事 {after_items}件")
    if after_days != len(day_files) or after_items != before_items:
        print("ERROR: 日数または記事件数が一致しません。中止します。")
        return 1

    if not apply:
        print("（検証のみ。書き出すには --apply を付けてください）")
        return 0

    for path in day_files:
        path.unlink()
    written = sorted(p.name for p in archive_dir.glob("*.json") if is_month_name(p.stem))
    print(f"日別 {len(day_files)}ファイルを削除し、月別 {len(written)}ファイルへ置き換えました")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_dir", type=Path, help="archive/ ディレクトリ")
    parser.add_argument("--apply", action="store_true", help="実際に書き換える")
    args = parser.parse_args()
    sys.exit(migrate(args.archive_dir, args.apply))
