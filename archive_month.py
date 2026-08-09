"""アーカイブの月別バンドル（archive/{YYYY-MM}.json）を読み書きする共通処理。

アーカイブは以前 archive/{date}.json と1日1ファイルで持っていたが、日数分だけ
リクエストが増える構造だった（1010日で1010リクエスト・gzip 2.22MB）。gzipは
圧縮窓が広いほど繰り返しを潰せるため、月ごとに束ねるだけで各紙のメタ情報の
重複がほぼ消え、34リクエスト・gzip 0.93MB になる。

月別ファイルの形式は、日次スナップショット（main.py の write_json が書き出す
{"date": ..., "sources": [...]}）をそのまま日付順に並べたもの:

    {"month": "2026-08", "days": [{"date": "2026-08-01", "sources": [...]}, ...]}

日次スナップショットの中身には手を加えない。表示に使われていないフィールド
（index_url・category・error等）も、その日その紙が取得に失敗したかの記録として
価値があるため落としていない。
"""
from __future__ import annotations

import json
from pathlib import Path

DATE_LEN = len("YYYY-MM-DD")
MONTH_LEN = len("YYYY-MM")


def month_of(date_str: str) -> str:
    return date_str[:MONTH_LEN]


def month_path(archive_dir: Path, month: str) -> Path:
    return archive_dir / f"{month}.json"


def is_month_name(stem: str) -> bool:
    return len(stem) == MONTH_LEN and stem[:4].isdigit() and stem[5:].isdigit()


def load_month(path: Path) -> dict:
    if not path.exists():
        return {"month": path.stem, "days": []}
    return json.loads(path.read_text(encoding="utf-8"))


def dump_month(path: Path, payload: dict) -> None:
    payload["days"] = sorted(payload["days"], key=lambda d: d["date"])
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def upsert_day(archive_dir: Path, day: dict) -> Path:
    """日次スナップショット1件を該当月のバンドルへ入れる（同じ日付は置き換え）。"""
    month = month_of(day["date"])
    path = month_path(archive_dir, month)
    payload = load_month(path)
    payload["month"] = month
    payload["days"] = [d for d in payload["days"] if d["date"] != day["date"]]
    payload["days"].append(day)
    dump_month(path, payload)
    return path


def iter_months(archive_dir: Path):
    for path in sorted(archive_dir.glob("*.json")):
        if is_month_name(path.stem):
            yield path
