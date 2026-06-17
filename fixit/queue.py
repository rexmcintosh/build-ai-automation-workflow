"""File-based issue queue for the fix->PR loop.

Each issue is a JSON file under ``<qdir>/pending``. Claiming atomically moves the
oldest file to ``<qdir>/processing`` (an os.rename, so two concurrent runners can
never claim the same issue). Completion moves it to ``done`` or ``failed`` with a
status stamped on. No timestamps are required for ordering — ids sort lexically and
are assigned oldest-first.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_SUBDIRS = ("pending", "processing", "done", "failed")


def _ensure(qdir: Path) -> Path:
    qdir = Path(qdir)
    for sub in _SUBDIRS:
        (qdir / sub).mkdir(parents=True, exist_ok=True)
    return qdir


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:48] or "issue"


def add_issue(qdir, title: str, body: str, *, issue_id: str | None = None) -> str:
    """Add a pending issue; returns its id. Duplicate slugs get a numeric suffix so
    ids are always unique."""
    qdir = _ensure(qdir)
    base = issue_id or _slug(title)
    iid, n = base, 1
    while (qdir / "pending" / f"{iid}.json").exists() or \
            (qdir / "processing" / f"{iid}.json").exists():
        n += 1
        iid = f"{base}-{n}"
    issue = {"id": iid, "title": title, "body": body, "status": "pending"}
    (qdir / "pending" / f"{iid}.json").write_text(json.dumps(issue, indent=2) + "\n")
    return iid


def list_pending(qdir) -> list[dict]:
    qdir = _ensure(qdir)
    out = []
    for p in sorted((qdir / "pending").glob("*.json")):
        out.append(json.loads(p.read_text()))
    return out


def claim_next(qdir) -> dict | None:
    """Atomically claim the oldest pending issue (pending -> processing). Returns the
    issue dict, or None if the queue is empty."""
    qdir = _ensure(qdir)
    pending = sorted((qdir / "pending").glob("*.json"))
    for src in pending:
        dst = qdir / "processing" / src.name
        try:
            os.rename(src, dst)  # atomic; loses the race -> try the next file
        except OSError:
            continue
        issue = json.loads(dst.read_text())
        issue["status"] = "processing"
        dst.write_text(json.dumps(issue, indent=2) + "\n")
        return issue
    return None


def _finish(qdir: Path, issue_id: str, status: str, **extra) -> None:
    qdir = _ensure(qdir)
    src = qdir / "processing" / f"{issue_id}.json"
    issue = json.loads(src.read_text()) if src.exists() else {"id": issue_id}
    issue["status"] = status
    issue.update(extra)
    (qdir / status / f"{issue_id}.json").write_text(json.dumps(issue, indent=2) + "\n")
    if src.exists():
        src.unlink()


def mark_done(qdir, issue_id: str, *, result: str = "") -> None:
    _finish(Path(qdir), issue_id, "done", result=result)


def mark_failed(qdir, issue_id: str, *, error: str = "") -> None:
    _finish(Path(qdir), issue_id, "failed", error=error)
