"""Test untuk SessionStore: persistensi, atomic write, reload."""
from pathlib import Path

import pytest

from nexus_cli.agent import SessionStore


def test_save_and_load(tmp_path):
    p = tmp_path / "session.json"
    s = SessionStore(p)
    msgs = [
        {"role": "user", "content": "halo"},
        {"role": "assistant", "content": "hai"},
    ]
    s.save(msgs)
    s2 = SessionStore(p)
    assert s2.messages == msgs


def test_atomic_write_no_tmp_left(tmp_path):
    """Save harus atomic; tidak boleh ada .tmp tertinggal."""
    p = tmp_path / "session.json"
    s = SessionStore(p)
    s.save([{"role": "user", "content": "x"}])
    assert not (tmp_path / "session.json.tmp").exists()
    assert p.exists()


def test_missing_file_returns_empty(tmp_path):
    """File belum ada -> messages kosong, bukan exception."""
    s = SessionStore(tmp_path / "nonexistent.json")
    assert s.messages == []


def test_overwrite_preserves_only_latest(tmp_path):
    """Save kedua kali menimpa save pertama."""
    p = tmp_path / "session.json"
    s = SessionStore(p)
    s.save([{"role": "user", "content": "first"}])
    s.save([{"role": "user", "content": "second"}])
    s2 = SessionStore(p)
    assert len(s2.messages) == 1
    assert s2.messages[0]["content"] == "second"


def test_save_empty_list_clears(tmp_path):
    p = tmp_path / "session.json"
    s = SessionStore(p)
    s.save([{"role": "user", "content": "x"}])
    s.save([])
    s2 = SessionStore(p)
    assert s2.messages == []
