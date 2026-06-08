# tests/loom/test_venice.py
import pytest
from loom.venice import VeniceClient, VeniceError


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
    def json(self):
        return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _ok(content="HELLO"):
    return {"choices": [{"message": {"content": content}}]}


def test_requires_key():
    with pytest.raises(VeniceError):
        VeniceClient(api_key="")


def test_complete_returns_content_and_sends_key_in_header_only():
    seen = {}
    def fake_post(url, headers=None, json=None, timeout=None):
        seen["headers"] = headers
        seen["body"] = json
        return _Resp(200, _ok("WOVEN"))
    c = VeniceClient(api_key="sk-test-123", post=fake_post)
    out = c.complete("claude-opus-4-8", "sys", "user text", json_mode=False)
    assert out == "WOVEN"
    assert seen["headers"]["Authorization"] == "Bearer sk-test-123"
    import json as _j
    assert "sk-test-123" not in _j.dumps(seen["body"])


def test_4xx_is_not_retried():
    calls = {"n": 0}
    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        return _Resp(400)
    c = VeniceClient(api_key="k", post=fake_post, retries=2, backoff=0)
    with pytest.raises(VeniceError):
        c.complete("m", "s", "u")
    assert calls["n"] == 1


def test_5xx_is_retried_then_fails():
    calls = {"n": 0}
    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        return _Resp(503)
    c = VeniceClient(api_key="k", post=fake_post, retries=2, backoff=0)
    with pytest.raises(VeniceError):
        c.complete("m", "s", "u")
    assert calls["n"] == 3   # 1 + 2 retries
