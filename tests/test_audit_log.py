"""
Tests for CSV audit logging.
"""

import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest

import audit_log


@pytest.fixture
def audit_file(tmp_path, monkeypatch):
    path = tmp_path / "audit.csv"
    monkeypatch.setenv("AUDIT_LOG_FILE", str(path))
    audit_log._header_written.clear()
    return path


def test_creates_file_with_header(audit_file: Path):
    audit_log.append_audit_entry("user@example.com", "getHoldings")
    assert audit_file.exists()
    with audit_file.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["timestamp", "email", "tool_name"]
    assert rows[1][1:] == ["user@example.com", "getHoldings"]


def test_appends_multiple_rows(audit_file: Path):
    audit_log.append_audit_entry("a@example.com", "validateToken")
    audit_log.append_audit_entry("b@example.com", "getPortfolios")
    with audit_file.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert len(rows) == 3
    assert rows[1][1:] == ["a@example.com", "validateToken"]
    assert rows[2][1:] == ["b@example.com", "getPortfolios"]


def test_uses_provided_timestamp(audit_file: Path):
    ts = datetime(2026, 7, 18, 12, 30, 0, tzinfo=timezone.utc)
    audit_log.append_audit_entry("user@example.com", "getFundDetails", timestamp=ts)
    with audit_file.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[1][0] == "2026-07-18T12:30:00Z"


def test_escapes_csv_special_characters(audit_file: Path):
    audit_log.append_audit_entry('user,"test"@example.com', "getHoldings")
    with audit_file.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[1][1] == 'user,"test"@example.com'


def test_skips_empty_email_or_tool_name(audit_file: Path):
    audit_log.append_audit_entry("", "getHoldings")
    audit_log.append_audit_entry("user@example.com", "")
    assert not audit_file.exists()
