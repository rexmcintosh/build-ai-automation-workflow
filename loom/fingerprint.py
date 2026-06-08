# loom/fingerprint.py
"""Structural idempotency primitives. A learning is identified by `<session_id>#<index>`.
The SCRIPT (never the model) records that id in two script-controlled places:
  - an HTML-comment marker block at the end of each woven file (per-target manifest), and
  - a `Loom-Woven:` git trailer on each loom-shadow commit (for ledger reconciliation).
Both are committed to loom-shadow, so git is the source of truth and a lost ledger rebuilds."""
from __future__ import annotations

import re
from typing import Iterable, Set

_MARKER_RE = re.compile(r"<!--\s*loom-woven:(.*?)-->", re.S)
_TRAILER_RE = re.compile(r"^Loom-Woven:\s*(.+)$", re.M)


def learning_id(session_id: str, index: int) -> str:
    return f"{session_id}#{index}"


def _split_ids(blob: str) -> Set[str]:
    return {tok.strip() for tok in blob.replace(",", " ").split() if tok.strip()}


def markers_in(text: str) -> Set[str]:
    m = _MARKER_RE.search(text or "")
    return _split_ids(m.group(1)) if m else set()


def strip_markers(text: str) -> str:
    """Remove any loom-woven marker block from *text* (used before re-stamping so the
    script — never the model — decides which ids a file carries)."""
    return _MARKER_RE.sub("", text or "").rstrip()


def with_markers(text: str, ids: Iterable[str]) -> str:
    """Return *text* with a single marker block carrying the union of existing + new ids."""
    merged = sorted(markers_in(text) | {str(i) for i in ids})
    body = _MARKER_RE.sub("", text or "").rstrip()
    return f"{body}\n\n<!-- loom-woven: {' '.join(merged)} -->\n"


def trailer_line(ids: Iterable[str]) -> str:
    return "Loom-Woven: " + " ".join(sorted({str(i) for i in ids}))


def ids_from_trailers(git_log_blob: str) -> Set[str]:
    out: Set[str] = set()
    for m in _TRAILER_RE.finditer(git_log_blob or ""):
        out |= _split_ids(m.group(1))
    return out
