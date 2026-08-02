"""Tests for the packaged CI shim (`council-ci-review` -> council.ci_review).

One shim in the package instead of 17 repo copies: these tests pin the
behaviors the fleet relied on (grounding, determinism, rolling comment,
advisory mode, fail-closed) plus the two hardening guards from aris PR #5
(path containment on diff-derived paths, COUNCIL_FILE_CAP parse fallback).
"""
from types import SimpleNamespace

import pytest

from council import ci_review as cr


def _diff_for(*paths):
    return "".join(
        f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-a\n+b\n"
        for p in paths)


# ---------- entry point wiring ----------

def test_entry_point_declared_in_pyproject():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    text = (root / "pyproject.toml").read_text()
    assert 'council-ci-review = "council.ci_review:main"' in text


def test_shim_delegates_to_engine_and_wires_audit_behaviors():
    import inspect
    src = inspect.getsource(cr)
    assert "from council.review import run_pr_review" in src
    assert "file_context=" in src            # S1 grounding reaches the engine
    assert "temperature=0" in src            # E3 deterministic gate path
    assert cr.MARKER in src                  # S2 rolling single comment
    assert "build_review" not in src         # no resurrected per-script logic


# ---------- gather_file_context ----------

def test_gather_reads_changed_files_and_anchors(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "x.mjs").write_text("const ROOT = '/repo';\n")
    (tmp_path / "package.json").write_text('{"engines": {"node": ">=22.12.0"}}')
    ctx = cr.gather_file_context(_diff_for("tools/x.mjs"), tmp_path)
    assert "const ROOT" in ctx               # full file, not just the hunk
    assert "tools/x.mjs" in ctx
    assert ">=22.12.0" in ctx                # anchor pulled in even if not in diff


def test_gather_skips_missing_files_without_raising(tmp_path):
    ctx = cr.gather_file_context(_diff_for("missing.py"), tmp_path)
    assert "missing.py" not in ctx


def test_gather_caps_large_files(tmp_path):
    (tmp_path / "big.js").write_text("x" * 5000)
    ctx = cr.gather_file_context(_diff_for("big.js"), tmp_path, per_file_cap=1000)
    assert "truncated" in ctx                # truncate() marker, not the whole file
    assert "x" * 5000 not in ctx


def test_gather_respects_total_cap(tmp_path):
    for name in ("a.js", "b.js"):
        (tmp_path / name).write_text("y" * 900)
    ctx = cr.gather_file_context(_diff_for("a.js", "b.js"), tmp_path,
                                 total_cap=1000)
    assert "=== a.js ===" in ctx
    assert "=== b.js ===" not in ctx         # second block would blow the budget


def test_hostile_diff_cannot_escape_checkout_root(tmp_path):
    """The aris PR #5 guard: diff-derived paths are attacker-controlled, so
    traversal and absolute paths must be refused — a crafted diff must never
    read files outside the checkout into the review payload."""
    root = tmp_path / "checkout"
    root.mkdir()
    secret = tmp_path / "secret.txt"         # sits OUTSIDE the checkout
    secret.write_text("TOP-SECRET-CONTENT")
    (root / "package.json").write_text('{"name": "anchor-ok"}')
    hostile = _diff_for("../secret.txt", "/etc/passwd",
                        "a/../../secret.txt")
    ctx = cr.gather_file_context(hostile, root)
    assert "TOP-SECRET-CONTENT" not in ctx
    assert "root:" not in ctx                # no /etc/passwd contents
    assert "anchor-ok" in ctx                # anchors still gathered normally


def test_hostile_diff_leaves_normal_gathering_unchanged(tmp_path):
    root = tmp_path / "checkout"
    (root / "src").mkdir(parents=True)
    (root / "src" / "ok.py").write_text("SAFE = True\n")
    mixed = _diff_for("../evil.txt", "src/ok.py")
    ctx = cr.gather_file_context(mixed, root)
    assert "SAFE = True" in ctx
    assert "evil" not in ctx


# ---------- comment upsert ----------

class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload if payload is not None else []
    def raise_for_status(self):
        return None
    def json(self):
        return self.payload


def test_upsert_updates_existing_comment_in_place(monkeypatch):
    calls = []
    def fake_request(method, url, **kw):
        calls.append((method, url, kw.get("json")))
        if method == "GET":
            return FakeResponse([{"id": 7, "body": f"old {cr.MARKER}"}])
        return FakeResponse()
    monkeypatch.setattr(cr.requests, "request", fake_request)
    cr.upsert_comment("o/r", "5", "new verdict", "tok")
    methods = [c[0] for c in calls]
    assert methods == ["GET", "PATCH"]       # updated, never a second comment
    assert "issues/comments/7" in calls[1][1]
    assert cr.MARKER in calls[1][2]["body"]


def test_upsert_creates_comment_when_none_exists(monkeypatch):
    calls = []
    def fake_request(method, url, **kw):
        calls.append((method, url, kw.get("json")))
        if method == "GET":
            return FakeResponse([{"id": 1, "body": "unrelated"}])
        return FakeResponse()
    monkeypatch.setattr(cr.requests, "request", fake_request)
    cr.upsert_comment("o/r", "5", "verdict", "tok")
    assert [c[0] for c in calls] == ["GET", "POST"]


# ---------- main(): gate semantics ----------

@pytest.fixture
def wired(monkeypatch, tmp_path):
    """main() with the engine, client, and GitHub wire all faked out."""
    state = SimpleNamespace(review_kwargs=None, client_kwargs=None,
                            posted=None, result=("body", 0, False))
    diff_file = tmp_path / "pr.diff"
    diff_file.write_text(_diff_for("src/app.py"))
    monkeypatch.setenv("DIFF_PATH", str(diff_file))
    monkeypatch.setenv("REPO", "o/r")
    monkeypatch.setenv("PR_NUMBER", "5")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("COUNCIL_ENFORCE", raising=False)
    monkeypatch.delenv("COUNCIL_FILE_CAP", raising=False)
    monkeypatch.setattr(cr, "load_panels", lambda: (
        SimpleNamespace(byte_cap=100_000, timeout=60, chair_model="chair"), {}))
    monkeypatch.setattr(cr, "get_api_key", lambda: "key")
    def fake_client(key, **kw):
        state.client_kwargs = {"key": key, **kw}
        return "CLIENT"
    monkeypatch.setattr(cr, "VeniceClient", fake_client)
    def fake_review(diff, panels, client, **kw):
        state.review_kwargs = kw
        return state.result
    monkeypatch.setattr(cr, "run_pr_review", fake_review)
    monkeypatch.setattr(cr, "upsert_comment",
                        lambda repo, pr, body, tok: setattr(state, "posted", body))
    return state


def test_main_clean_review_passes_and_posts(wired):
    assert cr.main() == 0
    assert wired.posted == "body"
    assert wired.client_kwargs["temperature"] == 0
    assert "file_context" in wired.review_kwargs


def test_main_blocking_findings_fail_closed(wired):
    wired.result = ("body", 2, False)
    assert cr.main() == 1
    assert wired.posted == "body"            # comment still posted before failing


def test_main_advisory_mode_never_fails_on_findings(wired, monkeypatch):
    wired.result = ("body", 2, False)
    monkeypatch.setenv("COUNCIL_ENFORCE", "0")
    assert cr.main() == 0


def test_main_unavailable_engine_fails_closed_even_in_advisory(wired, monkeypatch):
    wired.result = ("body", 0, True)
    monkeypatch.setenv("COUNCIL_ENFORCE", "0")
    assert cr.main() == 1                    # infra failure is never advisory


def test_main_empty_diff_short_circuits(wired, monkeypatch, tmp_path):
    empty = tmp_path / "empty.diff"
    empty.write_text("   \n")
    monkeypatch.setenv("DIFF_PATH", str(empty))
    assert cr.main() == 0
    assert wired.posted is None              # no API calls at all


def test_main_bad_file_cap_falls_back(wired, monkeypatch):
    monkeypatch.setenv("COUNCIL_FILE_CAP", "not-a-number")
    assert cr.main() == 0                    # ValueError guard: no crash


def test_read_capped_matches_reference_truncate_output(tmp_path):
    """The bounded read must produce byte-identical output to the reference
    shim's read-everything-then-truncate() for ordinary (valid UTF-8) files."""
    from council.config import truncate
    body = "line-" * 2000                    # 10_000 bytes, ASCII
    f = tmp_path / "big.txt"
    f.write_text(body)
    assert cr._read_capped(f, 1000) == truncate(body, 1000)
    assert cr._read_capped(f, 20_000) == body   # under cap: whole file, no marker


def test_main_negative_file_cap_clamped_to_default(wired, monkeypatch):
    monkeypatch.setenv("COUNCIL_FILE_CAP", "-5")
    assert cr.main() == 0                    # clamped, no crash / no empty context
