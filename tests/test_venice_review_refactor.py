import importlib.util, pathlib
from council.models import Panel, Member
from tests.conftest import FakeClient

# load the template module by path
_spec = importlib.util.spec_from_file_location(
    "venice_review", pathlib.Path("setup/templates/venice_review.py"))
vr = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(vr)


def test_build_review_blocks_on_high_severity(member_json):
    panel = Panel("code-review", "review", [Member("Eng", "m1", "eng")])
    client = FakeClient(by_model={
        "m1": member_json(stance="oppose", headline="bug",
                          findings=[("nil deref at api.py:10", "high", 9)]),
        "c": {"recommendation": "fix the nil deref", "confidence": 9,
              "consensus": [], "disagreements": [], "cross_panel_themes": []}})
    body, blocking, _ = vr.build_review("diff text", panel, client, chair_model="c")
    assert "## Council" in body
    assert blocking >= 1  # severity>=high counts as blocking → exit 1


def test_build_review_clean_diff_no_block(member_json):
    panel = Panel("code-review", "review", [Member("Eng", "m1", "eng")])
    client = FakeClient(by_model={
        "m1": member_json(stance="approve", headline="lgtm"),
        "c": {"recommendation": "ship it", "confidence": 8,
              "consensus": [], "disagreements": [], "cross_panel_themes": []}})
    body, blocking, _ = vr.build_review("diff", panel, client, chair_model="c")
    assert blocking == 0


def test_build_review_low_confidence_high_does_not_block(member_json):
    # A low-confidence `high` is dropped from the daily-rigor comment, so it must
    # not fail CI invisibly — only confident highs / any critical block.
    panel = Panel("code-review", "review", [Member("Eng", "m1", "eng")])
    client = FakeClient(by_model={
        "m1": member_json(stance="concerns", headline="maybe",
                          findings=[("speculative high at x.py:1", "high", 3)]),
        "c": {"recommendation": "ok", "confidence": 7,
              "consensus": [], "disagreements": [], "cross_panel_themes": []}})
    _, blocking, _ = vr.build_review("diff", panel, client, chair_model="c")
    assert blocking == 0


def test_build_review_low_confidence_critical_still_blocks(member_json):
    # A single critical always blocks (and is always shown), even at low confidence.
    panel = Panel("code-review", "review", [Member("Eng", "m1", "eng")])
    client = FakeClient(by_model={
        "m1": member_json(stance="oppose", headline="rce",
                          findings=[("possible RCE at x.py:9", "critical", 2)]),
        "c": {"recommendation": "fix", "confidence": 6,
              "consensus": [], "disagreements": [], "cross_panel_themes": []}})
    _, blocking, _ = vr.build_review("diff", panel, client, chair_model="c")
    assert blocking == 1


def test_build_review_fails_closed_when_panel_errors(member_json):
    # Total Venice failure: the member call raises. blocking is 0 (no findings),
    # but `unavailable` must be True so CI fails closed instead of merging unreviewed.
    panel = Panel("code-review", "review", [Member("Eng", "m1", "eng")])
    client = FakeClient(by_model={
        "c": {"recommendation": "x", "confidence": 5,
              "consensus": [], "disagreements": [], "cross_panel_themes": []}},
        raises_for={"m1"})
    _, blocking, unavailable = vr.build_review("diff", panel, client, chair_model="c")
    assert blocking == 0
    assert unavailable is True


def test_build_review_fails_closed_when_chair_errors(member_json):
    panel = Panel("code-review", "review", [Member("Eng", "m1", "eng")])
    client = FakeClient(
        by_model={"m1": member_json(stance="approve", headline="ok")},
        raises_for={"c"})
    _, _, unavailable = vr.build_review("diff", panel, client, chair_model="c")
    assert unavailable is True


def test_build_review_available_on_healthy_run(member_json):
    panel = Panel("code-review", "review", [Member("Eng", "m1", "eng")])
    client = FakeClient(by_model={
        "m1": member_json(stance="approve", headline="ok"),
        "c": {"recommendation": "ship", "confidence": 8,
              "consensus": [], "disagreements": [], "cross_panel_themes": []}})
    _, _, unavailable = vr.build_review("diff", panel, client, chair_model="c")
    assert unavailable is False
