from council.router import pick_panel
from council.models import Panel
from tests.conftest import FakeClient


def _panels():
    return {
        "decision": Panel("decision", "weigh a choice", []),
        "code-review": Panel("code-review", "review code", []),
    }


def test_router_returns_named_panel():
    client = FakeClient(default={"panel": "code-review"})
    assert pick_panel("review this diff", _panels(), client,
                      router_model="r", default="decision") == "code-review"


def test_router_falls_back_on_unknown():
    client = FakeClient(default={"panel": "nonsense"})
    assert pick_panel("x", _panels(), client, router_model="r",
                      default="decision") == "decision"


def test_router_falls_back_on_error():
    client = FakeClient(raises_for={"r"})
    assert pick_panel("x", _panels(), client, router_model="r",
                      default="decision") == "decision"
