"""Detect the Farza anti-pattern: a weave that only appended to the end of an
article (event-log growth) instead of integrating. Returns True if the change
is a pure trailing append — i.e. the old content is an unchanged prefix of the new."""
from __future__ import annotations


def is_trailing_append(before: str, after: str) -> bool:
    before = before.strip()
    after = after.strip()
    if not before:                      # new article — fine
        return False
    if not after.startswith(before):    # existing content was edited/reordered — integrated
        return False
    return len(after) > len(before)     # old kept verbatim + new tacked on the end
