# loom/summary.py
"""Build and scrub the Telegram run summary. Scrub runs the same coarse secret
patterns as the gate's intent — Telegram is an external surface, so a learning or
proposed diff must not leak a token. Output is plain text (one message)."""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

STALE_DAYS = 7

_SECRET_RE = re.compile(
    r"AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|xox[baprs]-[A-Za-z0-9-]+|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|ntn_[A-Za-z0-9]+|[0-9]{8,10}:AA[A-Za-z0-9_-]{33}"
)


def scrub(text: str) -> str:
    return _SECRET_RE.sub("<redacted>", text or "")


def build_summary(counts: Dict[str, int], shadow_commits: int, oldest_age_days: int,
                  rejected: List[Tuple[str, str]], proposed: List[str]) -> str:
    parts = ["🧵 Loom run"]
    parts.append(" ".join(f"{k}={v}" for k, v in counts.items()))
    stale = "  ⚠️ STALE" if oldest_age_days >= STALE_DAYS else ""
    parts.append(f"loom-shadow: {shadow_commits} commits to review; oldest {oldest_age_days}d{stale}")
    if rejected:
        parts.append("rejected (needs requeue):")
        parts += [f"  • {lid} — {reason}" for lid, reason in rejected]
    if proposed:
        parts.append("proposed (not applied):")
        parts += [f"  • {p}" for p in proposed]
    return scrub("\n".join(parts))


_COUNT_KEYS = ("distilled", "quarantined", "failed", "committed", "deferred",
               "rejected", "deadline_hit")


def format_run_summary(d: dict) -> str:
    """Build the scrubbed Telegram message from an `absorb` return dict."""
    counts = {k: d[k] for k in _COUNT_KEYS if k in d}
    rejected = [tuple(x) for x in d.get("rejected_items", [])]
    return build_summary(counts=counts,
                         shadow_commits=int(d.get("shadow_commits", 0)),
                         oldest_age_days=int(d.get("oldest_age_days", 0)),
                         rejected=rejected,
                         proposed=d.get("proposed", []))
