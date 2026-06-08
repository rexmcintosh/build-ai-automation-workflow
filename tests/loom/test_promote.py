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
    rollback(backups_dir=env["backups"], ts=ts)
    # the pre-promote state for a NEWLY created file is absence
    assert not tgt.exists()


def test_rollback_restores_preexisting_file(env):
    # a file that already exists in ~/.claude before promote (will be backed up)
    tgt = env["claude"] / "memory" / "feedback-x.md"
    tgt.write_text("ORIGINAL\n")
    promote(wiki_root=env["wiki"], claude_root=env["claude"], backups_dir=env["backups"])
    assert tgt.read_text() == "a new preference\n"          # promote overwrote it
    ts = sorted(p.name for p in env["backups"].iterdir())[-1]
    rollback(backups_dir=env["backups"], ts=ts)
    assert tgt.read_text() == "ORIGINAL\n"                  # restored from backup


def test_promote_update_of_loom_managed_file_succeeds(env):
    # first promote creates the .claude file and records its promoted_sha
    promote(wiki_root=env["wiki"], claude_root=env["claude"], backups_dir=env["backups"], expect_unmodified=True)
    tgt = env["claude"] / "memory" / "feedback-x.md"
    assert tgt.read_text() == "a new preference\n"
    # re-stage an UPDATED version on loom-shadow
    _git(env["wiki"], "checkout", "-q", "loom-shadow")
    staged = env["wiki"] / "_staged" / ".claude" / "memory" / "feedback-x.md"
    staged.parent.mkdir(parents=True, exist_ok=True); staged.write_text("an updated preference\n")
    _git(env["wiki"], "add", "-A"); _git(env["wiki"], "commit", "-qm", "restage update")
    _git(env["wiki"], "checkout", "-q", "master")
    # second promote with the guard ON must SUCCEED (on-disk still matches last promoted)
    promote(wiki_root=env["wiki"], claude_root=env["claude"], backups_dir=env["backups"], expect_unmodified=True)
    assert tgt.read_text() == "an updated preference\n"


def test_promote_refuses_out_of_band_edit(env):
    promote(wiki_root=env["wiki"], claude_root=env["claude"], backups_dir=env["backups"], expect_unmodified=True)
    tgt = env["claude"] / "memory" / "feedback-x.md"
    tgt.write_text("USER EDITED THIS\n")                 # out-of-band change after promote
    _git(env["wiki"], "checkout", "-q", "loom-shadow")
    staged = env["wiki"] / "_staged" / ".claude" / "memory" / "feedback-x.md"
    staged.parent.mkdir(parents=True, exist_ok=True); staged.write_text("loom update\n")
    _git(env["wiki"], "add", "-A"); _git(env["wiki"], "commit", "-qm", "restage")
    _git(env["wiki"], "checkout", "-q", "master")
    with pytest.raises(PromoteError):
        promote(wiki_root=env["wiki"], claude_root=env["claude"], backups_dir=env["backups"], expect_unmodified=True)
    assert tgt.read_text() == "USER EDITED THIS\n"        # untouched
