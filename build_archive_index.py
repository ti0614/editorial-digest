#!/usr/bin/env python3
"""archive/配下のスナップショット一覧から archive/index.json を再生成する。

CIワークフロー（deploy-today.yml）が当日分のJSONを archive/{date}.json として
`data`ブランチのチェックアウトにコピーした直後に実行し、archive.htmlがfetch
する日付一覧を最新化する。対象ディレクトリは引数で指定でき、省略時はこの
スクリプトと同階層の archive/ を使う（ローカルでの動作確認用）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_ARCHIVE_DIR = Path(__file__).parent / "archive"


def build_index(archive_dir: Path) -> None:
    dates = sorted(p.stem for p in archive_dir.glob("*.json") if p.stem != "index")
    index_path = archive_dir / "index.json"
    index_path.write_text(
        json.dumps({"dates": dates}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ARCHIVE_DIR
    build_index(target)
