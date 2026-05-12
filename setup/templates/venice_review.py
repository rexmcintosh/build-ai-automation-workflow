"""Venice AI multi-agent PR reviewer.

Fans out the PR diff to a panel of specialist personas, each backed by a
different Venice model, then aggregates verdicts into one consolidated PR
comment and a check status.

Required env:
  VENICE_API_KEY   Venice API key (repo secret)
  GITHUB_TOKEN     Provided by Actions
  PR_NUMBER, REPO, DIFF_PATH

Tune the panel below.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import requests

VENICE_API = "https://api.venice.ai/api/v1/chat/completions"
GITHUB_API = "https://api.github.com"

MAX_DIFF_BYTES = 200_000  # cap per-reviewer; larger PRs get head+tail


@dataclass
class Reviewer:
    name: str
    model: str
    lens: str  # short label shown in the PR comment
    system: str  # persona prompt


PANEL: list[Reviewer] = [
    Reviewer(
        name="Architect",
        model="claude-opus-4-7",
        lens="design & coherence",
        system=(
            "You are a staff engineer reviewing a pull request. Your lens is "
            "DESIGN COHERENCE. You ask: does this change belong in this layer? "
            "Are the abstractions earned by the actual requirements, or "
            "speculative? Is there an obvious simpler shape? Be terse and "
            "concrete; point at lines."
        ),
    ),
    Reviewer(
        name="BugHunter",
        model="gpt-5.2-codex",
        lens="correctness & edge cases",
        system=(
            "You are an adversarial code reviewer. Your lens is CORRECTNESS. "
            "Hunt for off-by-ones, null/undefined paths, race conditions, "
            "missing error handling, incorrect type assumptions, and edge "
            "cases the author probably didn't test. Only flag real bugs, not "
            "style."
        ),
    ),
    Reviewer(
        name="Security",
        model="deepseek-3.2",
        lens="security",
        system=(
            "You are a security-focused reviewer. Look for: injection (SQL, "
            "shell, prompt), authn/authz bypass, secrets in code or logs, "
            "unsafe deserialization, SSRF, open redirects, insecure crypto, "
            "missing input validation at trust boundaries. Ignore "
            "nice-to-haves; flag only real risk."
        ),
    ),
    Reviewer(
        name="Simplifier",
        model="qwen-3.6-27b",
        lens="simplicity",
        system=(
            "You are a reviewer obsessed with SIMPLICITY. Flag: over-"
            "engineering, premature abstraction, dead code, unused params, "
            "speculative generality, comments that restate the code, and "
            "anything that could be three lines instead of thirty."
        ),
    ),
]

OUTPUT_INSTRUCTIONS = textwrap.dedent("""\
    Respond with ONLY a JSON object (no markdown, no prose around it):
    {
      "verdict": "approve" | "comment" | "request_changes",
      "summary": "one sentence",
      "blocking": ["each item: short, with file:line if possible"],
      "suggestions": ["each item: short, with file:line if possible"]
    }
    Use "blocking" only for issues that should block merge. Use "suggestions"
    for nits and optional improvements. Keep each list <= 5 items.
""")


def truncate_diff(diff: str) -> str:
    b = diff.encode("utf-8", errors="ignore")
    if len(b) <= MAX_DIFF_BYTES:
        return diff
    head = b[: MAX_DIFF_BYTES // 2].decode("utf-8", errors="ignore")
    tail = b[-MAX_DIFF_BYTES // 2 :].decode("utf-8", errors="ignore")
    return f"{head}\n\n... [diff truncated, {len(b)} bytes total] ...\n\n{tail}"


def call_venice(reviewer: Reviewer, diff: str, api_key: str) -> dict:
    payload = {
        "model": reviewer.model,
        "messages": [
            {"role": "system", "content": reviewer.system + "\n\n" + OUTPUT_INSTRUCTIONS},
            {"role": "user", "content": f"Review this pull request diff:\n\n```diff\n{diff}\n```"},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        r = requests.post(VENICE_API, headers=headers, json=payload, timeout=180)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        return {
            "verdict": "comment",
            "summary": f"(reviewer errored: {type(e).__name__})",
            "blocking": [],
            "suggestions": [],
            "_error": str(e),
        }


def render_comment(results: list[tuple[Reviewer, dict]]) -> str:
    verdicts = {r.name: res.get("verdict", "comment") for r, res in results}
    total_blocking = sum(len(res.get("blocking", [])) for _, res in results)

    if total_blocking == 0 and all(v == "approve" for v in verdicts.values()):
        headline = "All reviewers approve. Safe to merge."
    elif total_blocking == 0:
        headline = "No blocking issues. See suggestions below."
    else:
        headline = f"{total_blocking} blocking issue(s) raised. See details below."

    parts = [
        "## Venice Review Council",
        "",
        f"**{headline}**",
        "",
        "| Reviewer | Lens | Verdict | Blocking | Suggestions |",
        "|---|---|---|---:|---:|",
    ]
    for r, res in results:
        parts.append(
            f"| {r.name} | {r.lens} | `{res.get('verdict', '?')}` | "
            f"{len(res.get('blocking', []))} | {len(res.get('suggestions', []))} |"
        )

    for r, res in results:
        parts += ["", f"<details><summary><b>{r.name}</b> · {r.model} · {r.lens}</summary>", ""]
        if summary := res.get("summary"):
            parts += [f"_{summary}_", ""]
        if blocking := res.get("blocking"):
            parts += ["**Blocking:**"] + [f"- {b}" for b in blocking] + [""]
        if suggestions := res.get("suggestions"):
            parts += ["**Suggestions:**"] + [f"- {s}" for s in suggestions] + [""]
        if err := res.get("_error"):
            parts += [f"_error: {err}_", ""]
        parts.append("</details>")

    return "\n".join(parts)


def post_pr_comment(repo: str, pr_number: str, body: str, token: str) -> None:
    url = f"{GITHUB_API}/repos/{repo}/issues/{pr_number}/comments"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={"body": body},
        timeout=30,
    )
    r.raise_for_status()


def main() -> int:
    api_key = os.environ["VENICE_API_KEY"]
    gh_token = os.environ["GITHUB_TOKEN"]
    pr_number = os.environ["PR_NUMBER"]
    repo = os.environ["REPO"]
    diff = truncate_diff(Path(os.environ["DIFF_PATH"]).read_text())

    if not diff.strip():
        print("Empty diff, nothing to review.")
        return 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(PANEL)) as pool:
        futures = {pool.submit(call_venice, r, diff, api_key): r for r in PANEL}
        results = [(futures[f], f.result()) for f in concurrent.futures.as_completed(futures)]

    results.sort(key=lambda x: [r.name for r in PANEL].index(x[0].name))

    body = render_comment(results)
    post_pr_comment(repo, pr_number, body, gh_token)

    total_blocking = sum(len(res.get("blocking", [])) for _, res in results)
    if total_blocking > 0:
        print(f"::error::{total_blocking} blocking issue(s) raised by review council", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
