from council.engine import run_panel
from council.models import Panel, Member
from tests.conftest import FakeClient


def _panel():
    return Panel(name="decision", description="d", members=[
        Member("Founder", "m1", "be a founder"),
        Member("Eng", "m2", "be an eng"),
    ])


def test_run_panel_parallel_collects_results(member_json):
    client = FakeClient(by_model={
        "m1": member_json(stance="approve", headline="go",
                          findings=[("ship it", "info", 9)]),
        "m2": member_json(stance="concerns", headline="careful"),
    })
    results = run_panel(_panel(), "ship X?", client)
    by = {r.member: r for r in results}
    assert by["Founder"].stance == "approve"
    assert by["Founder"].findings[0].confidence == 9
    assert by["Eng"].stance == "concerns"


def test_run_panel_isolates_member_errors(member_json):
    client = FakeClient(by_model={"m2": member_json()}, raises_for={"m1"})
    results = run_panel(_panel(), "x", client)
    by = {r.member: r for r in results}
    assert by["Founder"].error is not None
    assert by["Founder"].stance == "na"
    assert by["Eng"].error is None  # one failure doesn't kill the panel


def test_run_panel_coerces_bad_json():
    client = FakeClient(default="not json at all")
    results = run_panel(_panel(), "x", client)
    assert all(r.error is not None for r in results)
