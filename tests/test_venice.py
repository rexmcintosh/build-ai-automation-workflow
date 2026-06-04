import pytest
from council.venice import VeniceClient, VeniceError


def _resp(content, status=200):
    class R:
        status_code = status
        def json(self): return {"choices": [{"message": {"content": content}}]}
        def raise_for_status(self):
            if status >= 400:
                raise RuntimeError(f"HTTP {status}")
    return R()


def test_complete_returns_content():
    calls = []
    def fake_post(url, **kw):
        calls.append((url, kw))
        return _resp('{"ok": true}')
    c = VeniceClient(api_key="k", post=fake_post)
    out = c.complete("model-x", "sys", "usr")
    assert out == '{"ok": true}'
    assert calls[0][1]["json"]["model"] == "model-x"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer k"


def test_complete_retries_then_raises():
    attempts = {"n": 0}
    def flaky_post(url, **kw):
        attempts["n"] += 1
        raise ConnectionError("nope")
    c = VeniceClient(api_key="k", post=flaky_post, retries=2, backoff=0)
    with pytest.raises(VeniceError):
        c.complete("m", "s", "u")
    assert attempts["n"] == 3  # 1 try + 2 retries


def test_complete_scrubs_api_key_from_prompt():
    sent = {}
    def fake_post(url, **kw):
        sent["messages"] = kw["json"]["messages"]
        return _resp('{"ok": true}')
    c = VeniceClient(api_key="sk-secret-123", post=fake_post)
    c.complete("m", "system has sk-secret-123 in it", "user also sk-secret-123")
    blob = str(sent["messages"])
    assert "sk-secret-123" not in blob
    assert "<redacted>" in blob


def test_complete_does_not_retry_on_4xx():
    # A 401/400 (auth / bad model) fails identically every time — fail fast,
    # don't burn 3x the billing retrying it.
    attempts = {"n": 0}
    def auth_fail_post(url, **kw):
        attempts["n"] += 1
        return _resp("", status=401)
    c = VeniceClient(api_key="k", post=auth_fail_post, retries=2, backoff=0)
    with pytest.raises(VeniceError):
        c.complete("m", "s", "u")
    assert attempts["n"] == 1  # no retries on 4xx


def test_complete_retries_on_5xx():
    attempts = {"n": 0}
    def server_error_post(url, **kw):
        attempts["n"] += 1
        return _resp("", status=503)
    c = VeniceClient(api_key="k", post=server_error_post, retries=2, backoff=0)
    with pytest.raises(VeniceError):
        c.complete("m", "s", "u")
    assert attempts["n"] == 3  # 503 is retryable
