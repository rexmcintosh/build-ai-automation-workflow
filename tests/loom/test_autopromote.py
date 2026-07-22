# tests/loom/test_autopromote.py
"""The unattended-promote gate. Auto-promote is only safe because these refuse."""
import subprocess
from pathlib import Path
import pytest
from loom.autopromote import auto_promote_check, set_hold, clear_hold, is_held


def _git(root, *a):
    subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, text=True)


@pytest.fixture
def wiki(tmp_path):
    """master seeded; loom-shadow one weave ahead; no _staged/."""
    w = tmp_path / "wiki"; w.mkdir()
    _git(w, "init", "-q"); _git(w, "config", "user.email", "t@t"); _git(w, "config", "user.name", "t")
    (w / "people").mkdir(); (w / "people" / "liam.md").write_text("# Liam\nv0\n")
    _git(w, "add", "-A"); _git(w, "commit", "-qm", "seed")
    _git(w, "branch", "loom-shadow")
    _git(w, "checkout", "-q", "loom-shadow")
    (w / "people" / "liam.md").write_text("# Liam\nv1 woven\n")
    _git(w, "add", "-A"); _git(w, "commit", "-qm", "weave: people/liam.md")
    _git(w, "checkout", "-q", "master")
    return w


def _stage_claude_swap(w):
    _git(w, "checkout", "-q", "loom-shadow")
    p = w / "_staged" / ".claude" / "memory" / "new-pref.md"
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text("a preference\n")
    _git(w, "add", "-A"); _git(w, "commit", "-qm", "stage claude swap")
    _git(w, "checkout", "-q", "master")


def test_clean_shadow_promotes_unattended(wiki, tmp_path):
    r = auto_promote_check(wiki_root=wiki, loom_dir=tmp_path / "loom", today="2026-07-21")
    assert r["go"] is True


def test_staged_claude_swap_blocks_unattended_promote(wiki, tmp_path):
    """Wiki prose can land unreviewed; changes to Rex's live memories/skills cannot.
    That path has never run and its blast radius is the agent's own behaviour."""
    _stage_claude_swap(wiki)
    r = auto_promote_check(wiki_root=wiki, loom_dir=tmp_path / "loom", today="2026-07-21")
    assert r["go"] is False
    assert r["reason"] == "staged-claude"


def test_hold_stops_tonight_only(wiki, tmp_path):
    loom = tmp_path / "loom"
    set_hold(loom, "2026-07-21")
    assert auto_promote_check(wiki_root=wiki, loom_dir=loom, today="2026-07-21")["reason"] == "hold"
    # self-expiring: a hold is for ONE night, never a silent permanent stop
    assert auto_promote_check(wiki_root=wiki, loom_dir=loom, today="2026-07-22")["go"] is True


def test_clear_hold_resumes_same_night(wiki, tmp_path):
    loom = tmp_path / "loom"
    set_hold(loom, "2026-07-21")
    clear_hold(loom)
    assert is_held(loom, "2026-07-21") is False
    assert auto_promote_check(wiki_root=wiki, loom_dir=loom, today="2026-07-21")["go"] is True


def test_nothing_to_promote_is_not_an_error(wiki, tmp_path):
    _git(wiki, "merge", "-q", "--no-ff", "-m", "promote", "loom-shadow")
    r = auto_promote_check(wiki_root=wiki, loom_dir=tmp_path / "loom", today="2026-07-21")
    assert r["go"] is False and r["reason"] == "nothing-pending"


def test_check_reports_how_much_would_land(wiki, tmp_path):
    r = auto_promote_check(wiki_root=wiki, loom_dir=tmp_path / "loom", today="2026-07-21")
    assert r["commits"] == 1
    assert r["articles"] == ["people/liam.md"]


def test_dirty_wiki_stands_down_instead_of_crashing(wiki, tmp_path):
    """Rex edits this wiki in Obsidian, so uncommitted changes are NORMAL, not an
    error. promote() rightly refuses a dirty tree — the gate must catch that first
    and stand down quietly, or the nightly run fails (and pings) every time he
    leaves a note half-written."""
    (wiki / "people" / "liam.md").write_text("# Liam\nedited in Obsidian, uncommitted\n")
    r = auto_promote_check(wiki_root=wiki, loom_dir=tmp_path / "loom", today="2026-07-21")
    assert r["go"] is False
    assert r["reason"] == "wiki-dirty"


def test_untracked_junk_also_stands_down(wiki, tmp_path):
    """An untracked stray file is enough to make promote's preflight abort."""
    (wiki / "scratch.txt").write_text("stray\n")
    r = auto_promote_check(wiki_root=wiki, loom_dir=tmp_path / "loom", today="2026-07-21")
    assert r["go"] is False and r["reason"] == "wiki-dirty"
