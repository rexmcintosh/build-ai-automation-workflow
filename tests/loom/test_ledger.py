# tests/loom/test_ledger.py
from loom.ledger import WeaveLedger, LEARNING_STATES


def test_plan_then_advance_persists(tmp_path):
    p = tmp_path / "ledger.json"
    led = WeaveLedger(p)
    led.plan("s1#0", target="people/liam.md", action="update")
    led.mark("s1#0", "woven")
    led.mark("s1#0", "committed", commit_sha="abc123")
    reloaded = WeaveLedger(p)
    assert reloaded.status_of("s1#0") == "committed"
    assert reloaded.entry("s1#0")["commit_sha"] == "abc123"


def test_defer_increments_count(tmp_path):
    led = WeaveLedger(tmp_path / "l.json")
    led.plan("s1#0", "t.md", "create")
    led.defer("s1#0", "backend 5xx")
    led.defer("s1#0", "backend 5xx")
    assert led.status_of("s1#0") == "deferred"
    assert led.entry("s1#0")["deferrals"] == 2


def test_reject_is_terminal_and_surfaced(tmp_path):
    led = WeaveLedger(tmp_path / "l.json")
    led.plan("s1#0", "t.md", "update")
    led.reject("s1#0", "sentinel hit: pipe-to-shell")
    assert led.status_of("s1#0") == "rejected"
    assert led.rejected() == [("s1#0", "sentinel hit: pipe-to-shell")]


def test_pending_ids_excludes_settled(tmp_path):
    led = WeaveLedger(tmp_path / "l.json")
    led.plan("a#0", "t.md", "u"); led.mark("a#0", "committed")
    led.plan("b#0", "t.md", "u"); led.defer("b#0", "cap")
    led.plan("c#0", "t.md", "u"); led.reject("c#0", "lint")
    assert led.pending_ids() == ["b#0"]   # committed + rejected are settled


def test_reconcile_from_git_marks_committed(tmp_path):
    led = WeaveLedger(tmp_path / "l.json")
    led.plan("a#0", "t.md", "u")
    led.reconcile_from_git({"a#0"})
    assert led.status_of("a#0") == "committed"


def test_states_constant():
    assert set(LEARNING_STATES) == {"planned", "woven", "committed", "deferred", "rejected"}
