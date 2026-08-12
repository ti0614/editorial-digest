#!/usr/bin/env python3
"""dataブランチの過去アーカイブから、全国紙5紙以外のエントリを削除する
一回限りのCLI（migrate_archive_monthly.pyと同じ、通常運用には乗らない
使い切りスクリプトの位置づけ）。

対象を全国紙5紙のみに恒久固定したことに伴い、以前収録していたブロック紙・
地方紙分の過去データもdataブランチのarchive/{YYYY-MM}.jsonから削除する
（今後増やさないだけでなく、過去分も除去する）。各月バンドルの各日の
sourcesを、name が --keep で指定した紙のものだけに絞り込む。絞り込んだ結果
sourcesが空になった日はその日のエントリごと削除し、全ての日が消えた月
ファイルは削除する（archive/index.jsonに空の月が残らないようにするため）。

    python purge_national_only_archive.py /path/to/data-branch/archive          # 検証のみ
    python purge_national_only_archive.py /path/to/data-branch/archive --apply  # 置き換え

実行後は build_archive_index.py で archive/index.json を再生成すること。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from archive_month import dump_month, iter_months, load_month

DEFAULT_KEEP = ["朝日新聞", "毎日新聞", "読売新聞", "日本経済新聞", "産経新聞"]


def _count_items(sources: list[dict]) -> int:
    return sum(len(s.get("items") or []) for s in sources)


def purge(archive_dir: Path, keep: list[str], apply: bool) -> int:
    keep_set = set(keep)
    month_paths = list(iter_months(archive_dir))
    if not month_paths:
        print("月別ファイルが見つかりません")
        return 1

    before_files = len(month_paths)
    before_days = before_items = 0
    after_days = after_items = 0
    files_to_delete: list[Path] = []
    updates: list[tuple[Path, dict]] = []

    for path in month_paths:
        payload = load_month(path)
        days = payload.get("days") or []
        before_days += len(days)
        before_items += sum(_count_items(d.get("sources") or []) for d in days)

        kept_days = []
        for day in days:
            kept_sources = [s for s in (day.get("sources") or []) if s["name"] in keep_set]
            if kept_sources:
                kept_days.append({**day, "sources": kept_sources})
        after_days += len(kept_days)
        after_items += sum(_count_items(d["sources"]) for d in kept_days)

        if kept_days:
            updates.append((path, {"month": payload["month"], "days": kept_days}))
        else:
            files_to_delete.append(path)

    print(f"購入前: 月別 {before_files}ファイル / {before_days}日分 / 記事 {before_items}件")
    print(f"購入後: 月別 {len(updates)}ファイル / {after_days}日分 / 記事 {after_items}件"
          f"（削除される月ファイル {len(files_to_delete)}件）")

    if after_days > before_days or after_items > before_items:
        print("ERROR: 購入後の日数または記事件数が購入前を上回っています。中止します。")
        return 1

    if not apply:
        print("（検証のみ。書き出すには --apply を付けてください）")
        return 0

    for path, payload in updates:
        dump_month(path, payload)
    for path in files_to_delete:
        path.unlink()

    print(f"{len(updates)}ファイルを更新し、{len(files_to_delete)}ファイルを削除しました")
    print("続けて build_archive_index.py でarchive/index.jsonを再生成してください")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("archive_dir", type=Path, help="archive/ ディレクトリ（dataブランチのチェックアウト）")
    parser.add_argument("--keep", nargs="*", default=DEFAULT_KEEP, help="残す新聞社名（既定: 全国紙5紙）")
    parser.add_argument("--apply", action="store_true", help="実際に書き換える")
    args = parser.parse_args()
    sys.exit(purge(args.archive_dir, args.keep, args.apply))
