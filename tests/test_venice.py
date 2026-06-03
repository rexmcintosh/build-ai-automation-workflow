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
