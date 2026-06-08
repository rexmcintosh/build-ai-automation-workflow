from __future__ import annotations

from .routing import split_diff_by_type
from .engine import run_panel
from .synthesize import synthesize
from .render import render_combined


def _is_blocking(finding) -> bool:
    """Code-side gate: any `critical`, or a `high` with confidence >= 8."""
    return finding.severity == "critical" or (
        finding.severity == "high" and finding.confidence >= 8)


def run_pr_review(diff: str, panels: dict, client, *, chair_model: str):
    """Split a PR diff, review the code slice (gated) and the doc slice (advisory).

    Returns (body, blocking, unavailable):
      - body: one combined comment (a section per non-empty slice)
      - blocking: count of blocking findings in the CODE section only
      - unavailable: fail-closed flag keyed on the CODE review only (chair errored,
        or >= half the code panel errored). Doc-side failures never set it.
    """
    code_diff, doc_diff = split_diff_by_type(diff)
    sections = []
    blocking = 0
    unavailable = False

    if code_diff.strip():
        results = run_panel(
            panels["code-review"],
            f"Review this code diff:\n\n```diff\n{code_diff}\n```", client)
        syn = synthesize("Code review", results, client, chair_model=chair_model)
        sections.append(("Code review (gate)", "", "Code changes", syn, results))
        blocking = sum(1 for r in results for f in r.findings if _is_blocking(f))
        errored = sum(1 for r in results if r.error)
        unavailable = syn.error is not None or not results or errored * 2 >= len(results)

    if doc_diff.strip():
        results = run_panel(
            panels["spec-review"],
            f"Review this design doc / spec / plan diff:\n\n```diff\n{doc_diff}\n```", client)
        syn = synthesize("Doc review", results, client, chair_model=chair_model)
        sections.append(("Docs review (advisory)",
                         "Advisory only — does not affect the merge check.",
                         "Doc changes", syn, results))

    if not sections:
        return "Nothing to review.", 0, False
    return render_combined(sections), blocking, unavailable
