"""Fixture bersama untuk semua test."""
import os
import sys
from pathlib import Path

import pytest

# Pastikan project root masuk ke PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def tmp_nexus_dir(tmp_path, monkeypatch):
    """Arahkan NEXUS_CLI_HOME ke folder kosong per test."""
    nexus_dir = tmp_path / ".nexus"
    nexus_dir.mkdir()
    monkeypatch.setenv("NEXUS_CLI_HOME", str(tmp_path))
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-fixture")
    return nexus_dir


@pytest.fixture
def workspace(tmp_nexus_dir):
    from nexus_cli.agent import Workspace
    return Workspace(tmp_nexus_dir.parent, read_only=False)
