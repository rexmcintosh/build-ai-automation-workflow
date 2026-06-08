from council.review import run_pr_review
from council.models import Panel, Member
from tests.conftest import FakeClient

CODE = ("diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n"
        "@@ -1 +1 @@\n-old\n+new\n")
DOC = ("diff --git a/docs/design.md b/docs/design.md\n--- a/docs/design.md\n+++ b/docs/design.md\n"
       "@@ -1 +1 @@\n-old\n+new\n")


def _panels():
    return {
        "code-review": Panel("code-review", "review code", [Member("Eng", "code1", "be an eng")]),
        "spec-review": Panel("spec-review", "review docs", [Member("Editor", "doc1", "be an editor")]),
    }


def _chair(rec="ok"):
    return {"recommendation": rec, "confidence": 8, "consensus": [],
            "disagreements": [], "cross_panel_themes": []}


def test_mixed_pr_runs_both_blocking_counts_code_only(member_json):
    client = FakeClient(by_model={
        "code1": member_json(stance="oppose", headline="bug",
                             findings=[("nil deref at app.py:1", "high", 9)]),
        "doc1": member_json(stance="concerns", headline="vague",
                            findings=[("undefined term", "high", 9)]),
        "c": _chair("address both"),
    })
    body, blocking, unavailable = run_pr_review(CODE + DOC, _panels(), client, chair_model="c")
    assert "Code review (gate)" in body and "Docs review (advisory)" in body
    assert blocking == 1          # only the code finding counts
    assert unavailable is False


def test_docs_only_pr_never_blocks(member_json):
    client = FakeClient(by_model={
        "doc1": member_json(stance="oppose", headline="bad",
                            findings=[("fatal gap", "critical", 9)]),
        "c": _chair("clarify"),
    })
    body, blocking, unavailable = run_pr_review(DOC, _panels(), client, chair_model="c")
    assert "Docs review (advisory)" in body
    assert "Code review (gate)" not in body
    assert blocking == 0          # docs never block, even a critical
    assert unavailable is False


def test_code_panel_outage_fails_closed(member_json):
    client = FakeClient(by_model={"c": _chair()}, raises_for={"code1"})
    _, blocking, unavailable = run_pr_review(CODE, _panels(), client, chair_model="c")
    assert unavailable is True     # whole (1-member) code panel errored


def test_doc_panel_outage_does_not_block(member_json):
    client = FakeClient(by_model={
        "code1": member_json(stance="approve", headline="lgtm"),
        "c": _chair()},
        raises_for={"doc1"})
    _, blocking, unavailable = run_pr_review(CODE + DOC, _panels(), client, chair_model="c")
    assert unavailable is False    # doc-side failure must not fail the gate


def test_empty_diff_is_noop():
    body, blocking, unavailable = run_pr_review("", _panels(), FakeClient(), chair_model="c")
    assert blocking == 0 and unavailable is False
