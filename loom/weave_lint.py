"""Detect the Farza anti-pattern: a weave that only appended to the end of an
article (event-log growth) instead of integrating. Returns True if the change
is a pure trailing append — i.e. the old content is an unchanged prefix of the new."""
from __future__ import annotations

import difflib


def is_trailing_append(before: str, after: str) -> bool:
    before = before.strip()
    after = after.strip()
    if not before:                      # new article — fine
        return False
    if not after.startswith(before):    # existing content was edited/reordered — integrated
        return False
    return len(after) > len(before)     # old kept verbatim + new tacked on the end


DEFAULT_MAX_CHURN = 0.7  # >70% of the original lines discarded = a rewrite, not an integration
# (relaxed from 0.5: legitimate multi-fact integration into an existing article reorganizes a
#  fair amount; the per-target-per-run cap bounds churn, so the lint only needs to catch a
#  genuine wholesale rewrite.)


def is_excessive_rewrite(before: str, after: str, max_churn: float = DEFAULT_MAX_CHURN) -> bool:
    """True if the weave discarded more than max_churn of the original lines — a full-file
    restructure masking a one-fact change. A pure append preserves all originals (churn 0)."""
    before = before.strip()
    after = after.strip()
    if not before:                      # new article — nothing to preserve
        return False
    b = before.splitlines()
    a = after.splitlines()
    sm = difflib.SequenceMatcher(None, b, a)
    preserved = sum(block.size for block in sm.get_matching_blocks())
    churned = len(b) - preserved        # original lines not carried into `after`
    return (churned / max(len(b), 1)) > max_churn
