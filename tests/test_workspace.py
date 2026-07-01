"""Test untuk Workspace: path absolut, state_dir, sandbox."""
import os
from pathlib import Path

import pytest

from nexus_cli.agent import Workspace


def test_state_dir_is_absolute(tmp_path):
    ws = Workspace(tmp_path)
    assert ws.state_dir.is_absolute()


def test_state_dir_created(tmp_path):
    ws = Workspace(tmp_path)
    assert ws.state_dir.exists()
    assert ws.state_dir.is_dir()


def test_resolve_inside_workspace(tmp_path):
    ws = Workspace(tmp_path)
    f = tmp_path / "sub" / "file.txt"
    f.parent.mkdir()
    f.write_text("x", encoding="utf-8")
    resolved = ws.resolve("sub/file.txt")
    assert resolved == f.resolve()


def test_resolve_rejects_outside(tmp_path):
    from nexus_cli.agent import AgentError
    ws = Workspace(tmp_path)
    with pytest.raises(AgentError):
        ws.resolve("../outside.txt")


def test_read_only_uses_global_dir(tmp_path, monkeypatch):
    """Kalau state_dir di workspace tidak bisa dibuat, fallback ke ~/.config."""
    ro_dir = tmp_path / "readonly"
    ro_dir.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    # Patch mkdir HANYA pada path yang mengandung '.nexus'.
    # mkdir untuk root workspace dan folder lain tetap normal.
    real_mkdir = Path.mkdir
    def fake_mkdir(self, *args, **kwargs):
        # Tolak mkdir khusus untuk path '.nexus' di dalam workspace readonly
        if self.name == ".nexus":
            raise OSError("read-only filesystem")
        return real_mkdir(self, *args, **kwargs)
    monkeypatch.setattr(Path, "mkdir", fake_mkdir)

    ws = Workspace(ro_dir)
    # state_dir harus jatuh ke ~/.config/nexus-cli/<hash>
    assert "readonly" not in str(ws.state_dir)
    assert "nexus-cli" in str(ws.state_dir)


def test_root_attribute(tmp_path):
    ws = Workspace(tmp_path)
    assert ws.root == tmp_path
