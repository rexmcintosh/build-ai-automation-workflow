# tests/loom/test_backends.py
import pytest
from loom import backends


def test_claude_backend_maps_roles_and_joins_prompt(monkeypatch):
    seen = {}
    monkeypatch.setattr(backends.llm, "run",
                        lambda prompt, model, **k: seen.update(prompt=prompt, model=model) or "OUT")
    b = backends.get_backend("claude")
    out = b.complete("weave", "SYSTEM", "USER")
    assert out == "OUT"
    assert seen["model"] == "opus"               # weave role → opus on claude backend
    assert "SYSTEM" in seen["prompt"] and "USER" in seen["prompt"]
    assert b.complete("route", "s", "u") or True  # route role exists
    # verify route maps to haiku
    monkeypatch.setattr(backends.llm, "run", lambda prompt, model, **k: model)
    assert backends.get_backend("claude").complete("route", "s", "u") == "haiku"


def test_venice_backend_maps_roles(monkeypatch):
    captured = {}
    class FakeClient:
        def __init__(self, *a, **k): pass
        def complete(self, model, system, user, json_mode=False):
            captured.update(model=model, json_mode=json_mode)
            return "VOUT"
    monkeypatch.setattr(backends, "VeniceClient", FakeClient)
    b = backends.get_backend("venice", api_key="k")
    assert b.complete("weave", "s", "u") == "VOUT"
    assert captured["model"] == "claude-opus-4-8"
    b.complete("route", "s", "u", json_mode=True)
    assert captured["model"] == "gemini-3-5-flash" and captured["json_mode"] is True


def test_unknown_backend_raises():
    with pytest.raises(ValueError):
        backends.get_backend("bogus")
