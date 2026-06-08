# loom/gitio.py
"""Git operations on the wiki's loom-shadow worktree. All writes go through
commit_file, which stamps a Loom-Woven trailer and a no-op-skip (empty diff ->
no commit). committed_ids() reconstructs the set of woven learnings from trailers
so a lost ledger rebuilds from git."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional, Set

from .fingerprint import ids_from_trailers, trailer_line


class GitError(RuntimeError):
    pass


class ShadowRepo:
    def __init__(self, root: Path, base: str = "master") -> None:
        self.root = Path(root)
        self.base = base

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(["git", "-C", str(self.root), *args],
                              capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()}")
        return proc

    def read(self, rel: str) -> Optional[str]:
        p = self.root / rel
        return p.read_text(encoding="utf-8") if p.exists() else None

    def commit_file(self, rel: str, content: str, trailer_ids: List[str], message: str) -> Optional[str]:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        self._git("add", "--", rel)
        # nothing staged (identical content) -> skip, signal no-op
        if self._git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return None
        msg = f"{message}\n\n{trailer_line(trailer_ids)}\n"
        self._git("commit", "-q", "-m", msg)
        return self._git("rev-parse", "HEAD").stdout.strip()

    def commit_paths(self, paths: List[str], message: str) -> Optional[str]:
        """Stage the given paths and commit if anything changed; returns sha or None (no-op)."""
        for p in paths:
            self._git("add", "--", p, check=False)
        if self._git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return None
        self._git("commit", "-q", "-m", message)
        return self._git("rev-parse", "HEAD").stdout.strip()

    def committed_ids(self) -> Set[str]:
        blob = self._git("log", f"{self.base}..HEAD", "--format=%B%x00").stdout
        return ids_from_trailers(blob)

    def commits_since(self) -> int:
        return int(self._git("rev-list", "--count", f"{self.base}..HEAD").stdout.strip() or "0")

    def oldest_unpromoted_epoch(self) -> Optional[int]:
        out = self._git("log", f"{self.base}..HEAD", "--format=%ct", "--reverse").stdout.split()
        return int(out[0]) if out else None
