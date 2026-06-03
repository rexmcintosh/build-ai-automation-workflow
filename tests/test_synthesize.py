from council.synthesize import synthesize
from council.models import MemberResult
from tests.conftest import FakeClient


def _results():
    return [
        MemberResult("Founder", "m1", "approve", "go"),
        MemberResult("Eng", "m2", "concerns", "risky"),
    ]


def test_synthesize_parses_chair_json():
    client = FakeClient(default={
        "recommendation": "do X with guardrails",
        "confidence": 8,
        "consensus": ["X is the right direction"],
        "disagreements": [{"topic": "rollout", "type": "taste",
                           "positions": "founder fast, eng slow", "resolution": "stage it"}],
        "cross_panel_themes": ["timeline risk"],
    })
    s = synthesize("ship X?", _results(), client, chair_model="c")
    assert s.recommendation.startswith("do X")
    assert s.disagreements[0].type == "taste"
    assert s.cross_panel_themes == ["timeline risk"]
    assert s.error is None


def test_synthesize_falls_back_on_error():
    client = FakeClient(raises_for={"c"})
    s = synthesize("x", _results(), client, chair_model="c")
    assert s.error is not None
    assert "unavailable" in s.recommendation.lower()
