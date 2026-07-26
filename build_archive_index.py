#!/usr/bin/env python3
"""archive/配下のスナップショット一覧から archive/index.json を再生成する。

CIワークフロー（deploy-today.yml）が当日分のJSONを archive/{date}.json として
コミットした直後に実行し、archive.htmlがfetchする日付一覧を最新化する。
"""
from __future__ import annotations

import json
from pathlib import Path

ARCHIVE_DIR = Path(__file__).parent / "archive"


def build_index() -> None:
    dates = sorted(p.stem for p in ARCHIVE_DIR.glob("*.json") if p.stem != "index")
    index_path = ARCHIVE_DIR / "index.json"
    index_path.write_text(
        json.dumps({"dates": dates}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    build_index()
