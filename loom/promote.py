# loom/promote.py
"""Transactional promote: apply the _staged/.claude mirror to real ~/.claude under
backup, then merge loom-shadow -> master. Any failure rolls applied swaps back from
the manifest. ~/.claude is not git-tracked, so the backup is the only undo for it.
The runner wraps the whole call in flock (shares the absorb lock)."""
from __future__ import annotations

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
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise PromoteError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc


def _staged_files(wiki_root: Path) -> List[Path]:
    base = wiki_root / _STAGE
    return sorted(p for p in base.rglob("*") if p.is_file()) if base.exists() else []


def _shadow_has_stage(wiki_root: Path) -> List[str]:
    out = _git(wiki_root, "ls-tree", "-r", "--name-only", "loom-shadow").stdout.splitlines()
    return [ln for ln in out if ln.startswith(_STAGE + "/")]


def promote(wiki_root: Path, claude_root: Path, backups_dir: Path,
            *, ts: Optional[str] = None, expect_unmodified: bool = False) -> dict:
    wiki_root, claude_root, backups_dir = Path(wiki_root), Path(claude_root), Path(backups_dir)
    ts = ts or time.strftime("%Y%m%dT%H%M%S")

    # 1. PREFLIGHT — merge is clean, working tree is clean, targets unmodified.
    if _git(wiki_root, "status", "--porcelain").stdout.strip():
        raise PromoteError("wiki working tree is dirty; aborting")
    _git(wiki_root, "checkout", "-q", "master")
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
            raise PromoteError(f"refusing: {target} exists/modified out of band")
        plan.append((target, content, target.exists()))

    # 2. BACKUP + manifest
    stamp_dir = backups_dir / ts
    stamp_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, (target, _content, existed) in enumerate(plan):
        backup = stamp_dir / f"{i:04d}.bak"
        if existed:
            shutil.copy2(target, backup)
        manifest.append({"target": str(target), "backup": str(backup) if existed else None,
                         "existed": existed})
    (stamp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    # 3. ATOMIC-SWAP each staged file in
    applied = []
    try:
        for target, content, _existed in plan:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".loomtmp")
            tmp.write_text(content)
            tmp.replace(target)                          # atomic on POSIX
            applied.append(target)
        # 4. drop _staged on shadow, then merge -> master
        _git(wiki_root, "checkout", "-q", "loom-shadow")
        if _shadow_has_stage(wiki_root):
            _git(wiki_root, "rm", "-q", "-r", _STAGE.split("/")[0])  # remove _staged/
            _git(wiki_root, "commit", "-q", "-m", "promote: drop staged .claude mirror")
        _git(wiki_root, "checkout", "-q", "master")
        _git(wiki_root, "merge", "--no-ff", "-q", "loom-shadow", "-m", f"promote {ts}")
    except Exception as e:                               # 5. ROLLBACK
        _rollback_manifest(manifest)
        _git(wiki_root, "merge", "--abort", check=False)
        raise PromoteError(f"promote failed, rolled back: {e}") from e
    return {"applied": len(applied), "ts": ts}


def _rollback_manifest(manifest: List[dict]) -> None:
    for entry in manifest:
        target = Path(entry["target"])
        if entry["existed"] and entry["backup"]:
            shutil.copy2(entry["backup"], target)
        elif not entry["existed"] and target.exists():
            target.unlink()                              # newly created -> remove


def rollback(claude_root: Path, backups_dir: Path, ts: str) -> dict:
    manifest_path = Path(backups_dir) / ts / "manifest.json"
    if not manifest_path.exists():
        raise PromoteError(f"no manifest for ts={ts}")
    manifest = json.loads(manifest_path.read_text())
    _rollback_manifest(manifest)
    return {"restored": len(manifest), "ts": ts}
