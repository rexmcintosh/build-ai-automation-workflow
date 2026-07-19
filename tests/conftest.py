import json
import pytest


@pytest.fixture(autouse=True)
def _isolate_venice_usage_ledger(tmp_path, monkeypatch):
    """Belt-and-braces: no test may ever write to the real usage ledger at
    ~/.local/state/venice-usage/. Any test that needs its own ledger path can
    still monkeypatch VENICE_USAGE_DB itself — that simply overrides this."""
    monkeypatch.setenv("VENICE_USAGE_DB", str(tmp_path / "venice-usage-test.db"))


class FakeClient:
    """Stand-in for VeniceClient. Scripted responses keyed by model name,
    or a single default. Records calls for assertions."""

    def __init__(self, by_model=None, default=None, raises_for=None):
        self.by_model = by_model or {}
        self.default = default
        self.raises_for = raises_for or set()
        self.calls = []

    def complete(self, model, system, user, *, json_mode=True, task_type="chat"):
        self.calls.append({"model": model, "system": system, "user": user,
                           "task_type": task_type})
        if model in self.raises_for:
            raise RuntimeError(f"boom:{model}")
        payload = self.by_model.get(model, self.default)
        if payload is None:
            raise AssertionError(f"FakeClient has no scripted reply for {model}")
        return payload if isinstance(payload, str) else json.dumps(payload)


@pytest.fixture
def member_json():
    def make(stance="concerns", headline="ok", findings=(), suggestions=()):
        return {
            "stance": stance,
            "headline": headline,
            "findings": [
                {"point": p, "severity": s, "confidence": c} for (p, s, c) in findings
            ],
            "suggestions": list(suggestions),
        }
    return make
