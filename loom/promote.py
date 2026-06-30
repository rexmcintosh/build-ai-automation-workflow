# loom/promote.py
"""Transactional promote: apply the _staged/.claude mirror to real ~/.claude under
backup, then merge loom-shadow -> master. Any failure rolls applied swaps back from
the manifest. ~/.claude is not git-tracked, so the backup is the only undo for it.
The runner wraps the whole call in flock (shares the absorb lock)."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional

_STAGE = "_staged/.claude"


class PromoteError(RuntimeError):
    pass


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8")
    if check and proc.returncode != 0:
        raise PromoteError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _last_promoted_sha(backups_dir: Path, target: str):
    """The promoted_sha loom last recorded for *target*, scanning manifests newest-first."""
    if not backups_dir.exists():
        return None
    for stamp in sorted((p for p in backups_dir.iterdir() if p.is_dir()), reverse=True):
        mpath = stamp / "manifest.json"
        if not mpath.exists():
            continue
        try:
            entries = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception:
            continue
        for e in entries:
            if e.get("target") == target and e.get("promoted_sha"):
                return e["promoted_sha"]
    return None


def _common_dir(root: Path) -> Path:
    """Resolved .git common dir for *root* — same value for every worktree of a repo."""
    out = _git(root, "rev-parse", "--git-common-dir").stdout.strip()
    p = Path(out)
    return (p if p.is_absolute() else Path(root) / p).resolve()


def _shadow_has_stage(wiki_root: Path) -> List[str]:
    out = _git(wiki_root, "ls-tree", "-r", "--name-only", "loom-shadow").stdout.splitlines()
    return [ln for ln in out if ln.startswith(_STAGE + "/")]


def promote(wiki_root: Path, claude_root: Path, backups_dir: Path,
            *, shadow_root: Optional[Path] = None, ts: Optional[str] = None,
            expect_unmodified: bool = False) -> dict:
    """Promote in the MASTER worktree only. `wiki_root` is the master checkout (~/wiki);
    `shadow_root` is the loom-shadow worktree (~/wiki-loom-shadow). loom-shadow is never
    checked out here (it is already checked out in its own worktree) — the merge reads it
    by ref, the _staged mirror is dropped on master post-merge, and loom-shadow is then
    fast-forwarded to master in its own worktree. If `shadow_root` is None (single-repo,
    e.g. tests), loom-shadow is advanced with `git branch -f`."""
    wiki_root, claude_root, backups_dir = Path(wiki_root), Path(claude_root), Path(backups_dir)
    shadow_root = Path(shadow_root) if shadow_root is not None else None
    ts = ts or time.strftime("%Y%m%dT%H%M%S")

    # 1. PREFLIGHT — merge is clean, working tree is clean, targets unmodified.
    if _git(wiki_root, "status", "--porcelain").stdout.strip():
        raise PromoteError("wiki working tree is dirty; aborting")
    if shadow_root is not None:
        # The shadow worktree must be the genuine loom-shadow worktree of THIS repo, clean,
        # and on loom-shadow — checked up front so the final fast-forward can't fail late
        # (forcing rollback of an otherwise-good promote) or silently advance a foreign repo.
        if _common_dir(shadow_root) != _common_dir(wiki_root):
            raise PromoteError("shadow_root is not a worktree of wiki_root; aborting")
        head = _git(shadow_root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if head != "loom-shadow":
            raise PromoteError(f"shadow_root is on '{head}', expected loom-shadow; aborting")
        if _git(shadow_root, "status", "--porcelain").stdout.strip():
            raise PromoteError("shadow worktree is dirty; aborting")
    _git(wiki_root, "checkout", "-q", "master")
    orig_master = _git(wiki_root, "rev-parse", "HEAD").stdout.strip()
    dry = _git(wiki_root, "merge", "--no-commit", "--no-ff", "loom-shadow", check=False)
    _git(wiki_root, "merge", "--abort", check=False)
    if dry.returncode != 0:
        raise PromoteError("loom-shadow does not merge cleanly into master; aborting")

    # Read staged blobs from the loom-shadow tree (master has no _staged/).
    rels = _shadow_has_stage(wiki_root)
    plan = []   # (real_target, content, existed_before)
    for rel in rels:
        content = _git(wiki_root, "show", f"loom-shadow:{rel}").stdout
        real_rel = rel[len(_STAGE) + 1:]                 # strip "_staged/.claude/"
        target = claude_root / real_rel
        if expect_unmodified and target.exists():
            expected = _last_promoted_sha(backups_dir, str(target))
            actual = _sha(target.read_text(encoding="utf-8"))
            if expected is None or actual != expected:
                raise PromoteError(f"refusing: {target} modified out of band or not loom-managed")
        plan.append((target, content, target.exists()))

    # 2. BACKUP + manifest
    stamp_dir = backups_dir / ts
    stamp_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, (target, content, existed) in enumerate(plan):
        backup = stamp_dir / f"{i:04d}.bak"
        if existed:
            shutil.copy2(target, backup)
        manifest.append({"target": str(target), "backup": str(backup) if existed else None,
                         "existed": existed, "promoted_sha": _sha(content)})
    (stamp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    # 3. ATOMIC-SWAP each staged file in
    applied = []
    try:
        for target, content, _existed in plan:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".loomtmp")
            try:
                tmp.write_text(content, encoding="utf-8")
                tmp.replace(target)                          # atomic on POSIX
            except Exception:
                tmp.unlink(missing_ok=True)
                raise
            applied.append(target)
        # 4. merge loom-shadow -> master (by ref; never check it out), then drop _staged on master
        _git(wiki_root, "merge", "--no-ff", "-q", "loom-shadow", "-m", f"promote {ts}")
        if rels:
            _git(wiki_root, "rm", "-q", "-r", _STAGE.split("/")[0])  # remove _staged/ on master
            _git(wiki_root, "commit", "-q", "-m", "promote: drop staged .claude mirror")
        # 5. fast-forward loom-shadow to master so the next weave starts clean
        if shadow_root is not None:
            _git(shadow_root, "merge", "--ff-only", "-q", "master")
        else:
            _git(wiki_root, "branch", "-f", "loom-shadow", "master")
    except Exception as e:                               # 6. ROLLBACK
        _rollback_manifest(manifest)
        _git(wiki_root, "merge", "--abort", check=False)
        _git(wiki_root, "reset", "-q", "--hard", orig_master, check=False)
        raise PromoteError(f"promote failed, rolled back: {e}") from e
    return {"applied": len(applied), "ts": ts}


def _rollback_manifest(manifest: List[dict]) -> None:
    for entry in manifest:
        target = Path(entry["target"])
        if entry["existed"] and entry["backup"]:
            shutil.copy2(entry["backup"], target)
        elif not entry["existed"] and target.exists():
            target.unlink()                              # newly created -> remove


def rollback(backups_dir: Path, ts: str) -> dict:
    manifest_path = Path(backups_dir) / ts / "manifest.json"
    if not manifest_path.exists():
        raise PromoteError(f"no manifest for ts={ts}")
    manifest = json.loads(manifest_path.read_text())
    _rollback_manifest(manifest)
    return {"restored": len(manifest), "ts": ts}
