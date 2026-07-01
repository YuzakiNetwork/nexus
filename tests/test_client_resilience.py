"""Test untuk NvidiaClient: retry, fallback, klasifikasi error.

Semua test memakai fake `requests.post` agar tidak butuh API key nyata.
"""
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from nexus_cli.agent import ErrorLog, ModelError, NvidiaClient


class FakeResponse:
    def __init__(self, status, success_body=None, headers=None):
        self.status_code = status
        self.text = ""
        self.headers = headers or {}
        self._success_body = success_body

    def raise_for_status(self):
        if self.status_code >= 400:
            e = requests.exceptions.HTTPError(f"{self.status_code}")
            e.response = self
            raise e

    def json(self):
        return self._success_body or {
            "choices": [{"message": {"content": "default"}}]
        }


def make_client(log, **kwargs):
    defaults = dict(
        api_key="k", model="m1", temperature=1.0, top_p=0.95, max_tokens=10,
        error_log=log, fallback_model=None, max_retries=3,
    )
    defaults.update(kwargs)
    return NvidiaClient(**defaults)


def test_429_retries_then_succeeds(tmp_path):
    log = ErrorLog(tmp_path / "e.jsonl")
    client = make_client(log)
    responses = [
        FakeResponse(429, headers={"retry-after": "0.01"}),
        FakeResponse(429, headers={"retry-after": "0.01"}),
        FakeResponse(200, success_body={"choices": [{"message": {"content": "ok"}}]}),
    ]
    with patch.object(requests, "post", side_effect=lambda *a, **k: responses.pop(0)):
        result = client.chat([{"role": "user", "content": "hi"}], stream=False)
    assert result == "ok"
    assert len(log.tail(10)) >= 2  # error 429 tercatat


def test_404_falls_back_without_retry(tmp_path):
    """not_found: langsung fallback, TIDAK retry pada model yang sama."""
    log = ErrorLog(tmp_path / "e.jsonl")
    client = make_client(log, fallback_model="m2")
    responses = [
        FakeResponse(404),
        FakeResponse(200, success_body={"choices": [{"message": {"content": "fb"}}]}),
    ]
    models_used = []
    def fake_post(*a, **k):
        models_used.append(k["json"]["model"])
        return responses.pop(0)
    with patch.object(requests, "post", side_effect=fake_post):
        result = client.chat([{"role": "user", "content": "hi"}], stream=False)
    assert result == "fb"
    assert models_used == ["m1", "m2"]


def test_401_no_retry_no_fallback(tmp_path):
    """auth error (401/403) harus langsung raise, tidak retry, tidak fallback."""
    log = ErrorLog(tmp_path / "e.jsonl")
    client = make_client(log, fallback_model="m2")
    responses = [FakeResponse(401)]
    calls = []
    def fake_post(*a, **k):
        calls.append(k["json"]["model"])
        return responses.pop(0)
    with patch.object(requests, "post", side_effect=fake_post):
        with pytest.raises(ModelError) as exc_info:
            client.chat([{"role": "user", "content": "hi"}], stream=False)
    assert exc_info.value.category == "auth"
    assert exc_info.value.recoverable is False
    assert calls == ["m1"]  # hanya 1 percobaan


def test_network_error_retries(tmp_path):
    log = ErrorLog(tmp_path / "e.jsonl")
    client = make_client(log)
    n = [0]
    def fake_post(*a, **k):
        n[0] += 1
        if n[0] == 1:
            raise requests.exceptions.ConnectionError("down")
        return FakeResponse(200, success_body={"choices": [{"message": {"content": "net"}}]})
    with patch.object(requests, "post", side_effect=fake_post):
        result = client.chat([{"role": "user", "content": "hi"}], stream=False)
    assert result == "net"


def test_5xx_retries_then_fallback(tmp_path):
    """Server 5xx habis retry -> fallback ke model lain."""
    log = ErrorLog(tmp_path / "e.jsonl")
    client = make_client(log, fallback_model="m2")
    responses = [
        FakeResponse(500), FakeResponse(500), FakeResponse(500),
        FakeResponse(200, success_body={"choices": [{"message": {"content": "fb"}}]}),
    ]
    models = []
    def fake_post(*a, **k):
        models.append(k["json"]["model"])
        return responses.pop(0)
    with patch.object(requests, "post", side_effect=fake_post):
        result = client.chat([{"role": "user", "content": "hi"}], stream=False)
    assert result == "fb"
    # m1 dicoba max_retries kali, lalu m2
    assert models[:3] == ["m1", "m1", "m1"]
    assert models[-1] == "m2"


def test_rate_limit_exhausts_then_fallback(tmp_path):
    log = ErrorLog(tmp_path / "e.jsonl")
    client = make_client(log, fallback_model="m2")
    responses = [
        FakeResponse(429, headers={"retry-after": "0.01"}),
        FakeResponse(429, headers={"retry-after": "0.01"}),
        FakeResponse(429, headers={"retry-after": "0.01"}),
        FakeResponse(200, success_body={"choices": [{"message": {"content": "fb"}}]}),
    ]
    with patch.object(requests, "post", side_effect=lambda *a, **k: responses.pop(0)):
        result = client.chat([{"role": "user", "content": "hi"}], stream=False)
    assert result == "fb"


def test_5xx_after_fallback_raises(tmp_path):
    """Kalau fallback juga 5xx sampai habis, harus raise."""
    log = ErrorLog(tmp_path / "e.jsonl")
    client = make_client(log, fallback_model="m2", max_retries=2)
    responses = [
        FakeResponse(500), FakeResponse(500),  # m1 habis
        FakeResponse(503), FakeResponse(503),  # m2 habis
    ]
    with patch.object(requests, "post", side_effect=lambda *a, **k: responses.pop(0)):
        with pytest.raises(ModelError) as exc_info:
            client.chat([{"role": "user", "content": "hi"}], stream=False)
    assert exc_info.value.category == "server"


def test_model_error_attributes():
    """ModelError harus membawa semua metadata yang dipakai ErrorLog."""
    e = ModelError(
        "rate limited",
        category="rate_limit",
        status=429,
        recoverable=True,
        retry_after=2.5,
    )
    assert e.category == "rate_limit"
    assert e.status == 429
    assert e.recoverable is True
    assert e.retry_after == 2.5


def test_log_records_error(tmp_path):
    """Setiap ModelError harus tercatat di ErrorLog."""
    log = ErrorLog(tmp_path / "e.jsonl")
    client = make_client(log)
    responses = [FakeResponse(401)]
    with patch.object(requests, "post", side_effect=lambda *a, **k: responses.pop(0)):
        with pytest.raises(ModelError):
            client.chat([{"role": "user", "content": "hi"}], stream=False)
    entries = log.tail(10)
    assert len(entries) == 1
    assert entries[0]["category"] == "auth"
    assert entries[0]["status"] == 401
