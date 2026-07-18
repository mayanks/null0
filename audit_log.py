"""
Append-only CSV audit log for MCP tool invocations.

Each row records: timestamp (UTC), user email, tool name.
"""

from __future__ import annotations

import csv
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

_lock = threading.Lock()
_header_written: set[str] = set()

CSV_COLUMNS = ("timestamp", "email", "tool_name")


def audit_log_path() -> Path:
    return Path(os.environ.get("AUDIT_LOG_FILE", "logs/audit.csv"))


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_header(path: Path) -> None:
    key = str(path.resolve())
    if key in _header_written or path.exists() and path.stat().st_size > 0:
        _header_written.add(key)
        return
    with path.open("a", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerow(CSV_COLUMNS)
    _header_written.add(key)


def append_audit_entry(email: str, tool_name: str, *, timestamp: datetime | None = None) -> None:
    """Append one audit row. Thread-safe; never raises to callers."""
    if not email or not tool_name:
        return

    ts = timestamp or datetime.now(timezone.utc)
    ts_str = ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = audit_log_path()

    try:
        with _lock:
            _ensure_parent(path)
            _write_header(path)
            with path.open("a", encoding="utf-8", newline="") as fh:
                csv.writer(fh).writerow([ts_str, email, tool_name])
    except OSError as exc:
        logger.warning("Failed to write audit log entry: {}", exc)
