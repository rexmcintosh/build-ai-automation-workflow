# diem/discover.py
"""Checkpoint-time discovery: hygiene (unreviewed commits / dirty trees) and
publishing feedstock (standing-order stock shortfalls). Discovery only ADDS
queue items; QueueDir.add's dedupe makes it idempotent within a night."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

from .queue import Item, QueueDir, new_item
from .state import Reviewed


def _git(repo: Path, *args, run) -> str | None:
    try:
        p = run(["git", "-C", str(repo), *args],
                capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001 — a broken repo must never kill the drain
        return None
    if p.returncode != 0:
        return None
    return p.stdout.strip()


def discover(cfg, queue: QueueDir, reviewed: Reviewed, now_iso: str,
             *, day_start_iso: str | None = None,
             run=subprocess.run) -> list[Item]:
    added: list[Item] = []
    done_tonight = (queue.archived_keys_since(day_start_iso)
                    if day_start_iso else set())

    def _add(item: Item):
        if item.dedupe_key() in done_tonight:
            return  # already ran (or failed out) tonight — once per night
        if queue.add(item):
            added.append(item)

    for repo in cfg.repos:
        repo = Path(repo)
        head = _git(repo, "rev-parse", "HEAD", run=run)
        if head:
            old = reviewed.get(str(repo))
            if old is None:
                reviewed.set(str(repo), head)  # baseline, nothing to review yet
            elif old != head:
                _add(new_item("review", {"repo": str(repo),
                                         "range": f"{old}..{head}",
                                         "head": head}, created=now_iso))
            status = _git(repo, "status", "--porcelain", run=run)
            if status:
                _add(new_item("review", {"repo": str(repo), "diff": True},
                              created=now_iso))

        so_path = repo / ".diem" / "standing-order.json"
        if so_path.exists():
            try:
                so = json.loads(so_path.read_text())
                target = int(so["target"])
                cand = repo / so["candidates_dir"]
                command = list(so["command"])
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue  # malformed standing order: skip, never invent
            stock = sum(1 for f in cand.glob("*") if f.is_file()) if cand.is_dir() else 0
            if stock < target:
                _add(new_item("images", {"repo": str(repo),
                                         "count": target - stock,
                                         "command": command}, created=now_iso))
    return added
