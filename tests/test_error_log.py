"""Test untuk ErrorLog: persistensi, rotasi, tail, clear."""
import json
from pathlib import Path

import pytest

from nexus_cli.agent import ErrorLog


def test_record_creates_file(tmp_path):
    log_path = tmp_path / "errors.jsonl"
    log = ErrorLog(log_path)
    assert not log_path.exists()
    log.record(category="rate_limit", status=429, message="too many", model="m1")
    assert log_path.exists()


def test_tail_returns_most_recent(tmp_path):
    log = ErrorLog(tmp_path / "errors.jsonl")
    for i in range(5):
        log.record(category="test", status=400, message=f"msg-{i}", model="m1")
    tail = log.tail(3)
    assert len(tail) == 3
    assert tail[0]["message"] == "msg-2"
    assert tail[-1]["message"] == "msg-4"


def test_tail_more_than_total(tmp_path):
    log = ErrorLog(tmp_path / "errors.jsonl")
    log.record(category="test", status=400, message="only", model="m1")
    tail = log.tail(100)
    assert len(tail) == 1


def test_tail_empty_returns_empty_list(tmp_path):
    log = ErrorLog(tmp_path / "errors.jsonl")
    assert log.tail(10) == []


def test_clear_empties_log(tmp_path):
    log = ErrorLog(tmp_path / "errors.jsonl")
    log.record(category="test", status=400, message="x", model="m1")
    log.clear()
    assert log.tail(10) == []


def test_record_includes_iso_timestamp(tmp_path):
    log = ErrorLog(tmp_path / "errors.jsonl")
    log.record(category="test", status=400, message="x", model="m1")
    entry = log.tail(1)[0]
    assert "iso" in entry
    assert "T" in entry["iso"]  # ISO format mengandung 'T'


def test_record_extra_field(tmp_path):
    log = ErrorLog(tmp_path / "errors.jsonl")
    log.record(category="rate_limit", status=429, message="x", model="m1",
               extra={"retry_after": 2.5})
    entry = log.tail(1)[0]
    assert entry["extra"]["retry_after"] == 2.5


def test_corrupt_line_is_skipped(tmp_path):
    """Baris rusak di log harus dilewati, bukan exception."""
    p = tmp_path / "errors.jsonl"
    p.write_text("not-a-json-line\n", encoding="utf-8")
    log = ErrorLog(p)
    # Tambahkan entry valid
    log.record(category="test", status=400, message="ok", model="m1")
    tail = log.tail(10)
    # Hanya entry valid yang diambil
    assert len(tail) == 1
    assert tail[0]["message"] == "ok"


def test_rotation_keeps_size_bounded(tmp_path):
    """Kalau ukuran lewat max_bytes, file utama di-rename ke .1."""
    p = tmp_path / "errors.jsonl"
    log = ErrorLog(p, max_bytes=200)
    # Tulis entry besar yang pasti melewati max_bytes
    for i in range(20):
        log.record(category="test", status=400, message="x" * 80, model="m1")
    # Setelah rotasi: arsip .1 ada
    backup = tmp_path / "errors.jsonl.1"
    assert backup.exists()
    # File utama boleh ada atau tidak (tergantung timing rotasi), yang penting
    # ukuran total tidak naik tanpa batas.
    total = 0
    for candidate in (p, backup):
        if candidate.exists():
            total += candidate.stat().st_size
    # Total ada tapi ter-batas — rotasi dipicu minimal sekali
    assert total > 200  # ada data
    # Pastikan file utama (kalau ada) tidak lebih besar dari max_bytes * 1.5
    if p.exists():
        assert p.stat().st_size <= 200 * 1.5
