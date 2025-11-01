"""
Persistent transfer history logging.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

HISTORY_DIR = Path.home() / ".glitter"
HISTORY_FILE = HISTORY_DIR / "history.jsonl"


@dataclass
class HistoryRecord:
    timestamp: str
    direction: str  # "send" or "receive"
    status: str  # "completed", "failed", etc.
    filename: str
    size: int
    sha256: Optional[str]
    local_device: str
    remote_name: str
    remote_ip: str
    source_path: Optional[str] = None
    target_path: Optional[str] = None
    local_version: Optional[str] = None
    remote_version: Optional[str] = None


def append_record(record: HistoryRecord) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


def load_records(limit: Optional[int] = 50) -> List[HistoryRecord]:
    if not HISTORY_FILE.exists():
        return []
    lines: Iterable[str]
    with HISTORY_FILE.open("r", encoding="utf-8") as handle:
        lines = handle.readlines()
    if limit is not None and limit > 0:
        lines = lines[-limit:]
    records: List[HistoryRecord] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            records.append(HistoryRecord(**payload))
        except (ValueError, TypeError):
            continue
    return records


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_timestamp(timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def clear_history() -> None:
    if HISTORY_FILE.exists():
        try:
            HISTORY_FILE.unlink()
        except OSError:
            pass
