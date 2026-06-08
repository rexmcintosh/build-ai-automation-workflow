"""Venice review council — GitHub Action shim over the `council` engine.

Splits the PR diff, reviews code changes (gated) and doc changes (advisory) via
council.review.run_pr_review, posts one consolidated comment, and exits 1 when
there are blocking code findings or the code review was unavailable (fail closed).

Required env: VENICE_API_KEY, GITHUB_TOKEN, PR_NUMBER, REPO, DIFF_PATH
"""
from __future__ import annotations
import os, sys
from pathlib import Path

import requests
from council.config import load_panels, get_api_key, truncate
from council.venice import VeniceClient
from council.review import run_pr_review

GITHUB_API = "https://api.github.com"


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
    body, blocking, unavailable = run_pr_review(
        diff, panels, client, chair_model=settings.chair_model)
    post_comment(os.environ["REPO"], os.environ["PR_NUMBER"], body, os.environ["GITHUB_TOKEN"])
    if unavailable:
        print("::error::review council unavailable (code panel/chair failed) — failing closed",
              file=sys.stderr)
        return 1
    if blocking:
        print(f"::error::{blocking} blocking finding(s) from the review council", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
