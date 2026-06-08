# tests/loom/test_gitio.py
import subprocess
from pathlib import Path
import pytest
from loom.gitio import ShadowRepo
from loom.fingerprint import trailer_line


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "wiki"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "seed.md").write_text("seed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")          # this is 'master'
    _git(root, "checkout", "-qb", "loom-shadow")
    return ShadowRepo(root, base="master")


def test_read_missing_returns_none(repo):
    assert repo.read("people/none.md") is None


def test_commit_file_persists_and_returns_sha(repo):
    sha = repo.commit_file("people/liam.md", "# Liam\n", ["s1#0"], "weave: liam")
    assert sha and len(sha) >= 7
    assert repo.read("people/liam.md") == "# Liam\n"


def test_commit_file_no_change_returns_none(repo):
    repo.commit_file("a.md", "X\n", ["s1#0"], "first")
    assert repo.commit_file("a.md", "X\n", ["s1#0"], "again") is None  # identical content


def test_committed_ids_reads_trailers(repo):
    repo.commit_file("a.md", "A\n", ["s1#0"], "one")
    repo.commit_file("b.md", "B\n", ["s2#1", "s2#2"], "two")
    assert repo.committed_ids() == {"s1#0", "s2#1", "s2#2"}


def test_commits_since_counts_only_shadow(repo):
    assert repo.commits_since() == 0
    repo.commit_file("a.md", "A\n", ["s1#0"], "one")
    assert repo.commits_since() == 1
