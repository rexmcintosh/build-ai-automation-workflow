# loom/sentinel.py
"""Deterministic dangerous-pattern scan run on EVERY weave output (and the Telegram
summary). The two shape lints are scoped to wiki/memory; the sentinel is the
content guard for the otherwise-unlinted routes (decisions/SKILL.md/MEMORY.md) —
a model-authored backdoor or policy-override must not reach loom-shadow unflagged.
This is a coarse net before human review, not a security boundary on its own."""
from __future__ import annotations

import re
from typing import List

# Each: (label, compiled regex). Case-insensitive. Keep tight to limit false positives;
# everything still gets human review on loom-shadow — this just refuses the obvious.
_PATTERNS = [
    ("skip-permissions", re.compile(r"--dangerously-skip-permissions|--dangerously", re.I)),
    ("pipe-to-shell", re.compile(r"curl[^\n|]*\|\s*(ba)?sh|wget[^\n|]*\|\s*(ba)?sh", re.I)),
    ("rm-rf", re.compile(r"\brm\s+-rf\b", re.I)),
    ("chmod-777", re.compile(r"\bchmod\s+777\b", re.I)),
    ("disable-auth", re.compile(r"\b(disable|bypass|skip)\s+(auth|authentication|the\s+gate|security)\b", re.I)),
    ("override-policy", re.compile(r"\bignore\s+(all\s+)?(previous|prior)\s+(instructions|rules)\b", re.I)),
    ("priv-write", re.compile(r"\b(sudo|/etc/sudoers|authorized_keys)\b", re.I)),
]


def find_hits(text: str) -> List[str]:
    if not text:
        return []
    return [label for label, rx in _PATTERNS if rx.search(text)]


def is_clean(text: str) -> bool:
    return not find_hits(text)
