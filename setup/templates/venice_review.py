"""Venice review council — GitHub Action front-end on the `council` engine.

Runs the `code-review` panel over a PR diff, posts one consolidated comment,
and exits 1 when there are blocking findings (severity >= high).

Required env: VENICE_API_KEY, GITHUB_TOKEN, PR_NUMBER, REPO, DIFF_PATH
"""
from __future__ import annotations
import os, sys
from pathlib import Path

import requests
from council.config import load_panels, get_api_key, truncate
from council.venice import VeniceClient
from council.engine import run_panel
from council.synthesize import synthesize
from council.render import render_markdown

GITHUB_API = "https://api.github.com"


def _is_blocking(finding) -> bool:
    """A finding blocks merge only if it would also be SHOWN in the posted
    comment (daily rigor): any `critical`, or a `high` the panelist is confident
    in (>=8). This keeps a low-confidence `high` from failing CI invisibly."""
    return finding.severity == "critical" or (
        finding.severity == "high" and finding.confidence >= 8)


def build_review(diff: str, panel, client, *, chair_model: str):
    results = run_panel(panel, f"Review this pull request diff:\n\n```diff\n{diff}\n```", client)
    syn = synthesize("PR diff review", results, client, chair_model=chair_model)
    body = render_markdown("Pull request review", syn, results, rigor=panel.default_rigor)
    blocking = sum(1 for r in results for f in r.findings if _is_blocking(f))
    # Fail CLOSED: if the chair errored or half-or-more of the panel failed, the
    # review didn't really happen — a Venice outage / bad model id must NOT pass
    # the merge gate with 0 findings.
    errored = sum(1 for r in results if r.error)
    unavailable = (syn.error is not None
                   or not results               # empty/misconfigured panel — zero reviewers
                   or errored * 2 >= len(results))  # half or more of the panel failed
    return body, blocking, unavailable


def post_comment(repo, pr, body, token):
    requests.post(f"{GITHUB_API}/repos/{repo}/issues/{pr}/comments",
                  headers={"Authorization": f"Bearer {token}",
                           "Accept": "application/vnd.github+json"},
                  json={"body": body}, timeout=30).raise_for_status()


def main() -> int:
    settings, panels = load_panels()
    diff = truncate(Path(os.environ["DIFF_PATH"]).read_text(), settings.byte_cap)
    if not diff.strip():
        print("Empty diff, nothing to review.")
        return 0
    client = VeniceClient(get_api_key(), timeout=settings.timeout)
    body, blocking, unavailable = build_review(diff, panels["code-review"], client,
                                               chair_model=settings.chair_model)
    post_comment(os.environ["REPO"], os.environ["PR_NUMBER"], body, os.environ["GITHUB_TOKEN"])
    if unavailable:
        print("::error::review council unavailable (chair or panel failed) — failing closed",
              file=sys.stderr)
        return 1
    if blocking:
        print(f"::error::{blocking} blocking finding(s) from the review council", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
