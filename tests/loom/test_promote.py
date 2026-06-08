# tests/loom/test_promote.py
import json
import subprocess
from pathlib import Path
import pytest
from loom.promote import promote, rollback, PromoteError


def _git(root, *a):
    subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, text=True)


@pytest.fixture
def env(tmp_path):
    wiki = tmp_path / "wiki"; wiki.mkdir()
    _git(wiki, "init", "-q"); _git(wiki, "config", "user.email", "t@t"); _git(wiki, "config", "user.name", "t")
    (wiki / "people").mkdir(); (wiki / "people" / "liam.md").write_text("# Liam\nv0\n")
    _git(wiki, "add", "-A"); _git(wiki, "commit", "-qm", "seed")
    _git(wiki, "branch", "loom-shadow")
    # on shadow: update an article AND stage a .claude memory file
    _git(wiki, "checkout", "-q", "loom-shadow")
    (wiki / "people" / "liam.md").write_text("# Liam\nv1 woven\n")
    staged = wiki / "_staged" / ".claude" / "memory" / "feedback-x.md"
    staged.parent.mkdir(parents=True); staged.write_text("a new preference\n")
    _git(wiki, "add", "-A"); _git(wiki, "commit", "-qm", "weave + staged")
    _git(wiki, "checkout", "-q", "master")
    claude = tmp_path / "claude"; (claude / "memory").mkdir(parents=True)
    backups = tmp_path / "backups"
    return {"wiki": wiki, "claude": claude, "backups": backups}


def test_promote_applies_claude_and_merges(env):
    promote(wiki_root=env["wiki"], claude_root=env["claude"], backups_dir=env["backups"])
    # .claude memory landed
    assert (env["claude"] / "memory" / "feedback-x.md").read_text() == "a new preference\n"
    # master advanced and carries no _staged/
    head = subprocess.run(["git", "-C", str(env["wiki"]), "log", "master", "--oneline"],
                          capture_output=True, text=True).stdout
    assert "weave" in head
    assert not (env["wiki"] / "_staged").exists()
    assert (env["wiki"] / "people" / "liam.md").read_text() == "# Liam\nv1 woven\n"


def test_dirty_claude_target_aborts_before_touching(env):
    # pre-existing modified target out of band
    tgt = env["claude"] / "memory" / "feedback-x.md"
    tgt.write_text("USER EDIT\n")
    with pytest.raises(PromoteError):
        promote(wiki_root=env["wiki"], claude_root=env["claude"], backups_dir=env["backups"],
                expect_unmodified=True)
    # untouched
    assert tgt.read_text() == "USER EDIT\n"


def test_rollback_restores_from_manifest(env):
    promote(wiki_root=env["wiki"], claude_root=env["claude"], backups_dir=env["backups"])
    tgt = env["claude"] / "memory" / "feedback-x.md"
    tgt.write_text("changed after promote\n")
    ts = sorted(p.name for p in env["backups"].iterdir())[-1]
    rollback(claude_root=env["claude"], backups_dir=env["backups"], ts=ts)
    # the pre-promote state for a NEWLY created file is absence
    assert not tgt.exists()
