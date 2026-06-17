"""Watchdog runner: collect signals -> triage -> emit an escalation report.

Invoked by ``run-watchdog.sh``. Prints a human-readable report of fired checks
to stdout and a single machine-readable JSON line (prefixed ``WATCHDOG_JSON:``)
the shell parses to decide whether to escalate to the investigator agent.

Healthy polls print nothing escalation-worthy and cost no tokens — the agent is
only invoked by the shell when ``escalate`` is true.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .triage import (
    CheckStatus,
    LEVELS,
    check_bebop_runs,
    check_cron_log,
    check_disk,
    check_service_active,
    triage,
)

# Default to the MAIN checkout so the installed cron job watches production, not
# a worktree. Override with WATCHDOG_BASE for testing/relocation.
BASE = Path(os.environ.get("WATCHDOG_BASE", "/home/dev/projects/build-ai-automation-workflow"))

# Cron logs to scan for error markers: (label, path).
CRON_LOGS = [
    ("loom", BASE / "loom" / "logs" / "absorb.log"),
    ("meettrack-ingest", Path("/home/dev/projects/splash_poller/logs/ingest_entries.cron.log")),
    ("meettrack-supervise", Path("/home/dev/projects/splash_poller/logs/supervise.cron.log")),
]
SERVICES = ["tailscaled"]


def load_state(path) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}  # missing or corrupt -> start clean; never crash a poll


def save_state(path, state: dict) -> None:
    Path(path).write_text(json.dumps(state, indent=2) + "\n")


def _read(path) -> str | None:
    try:
        return Path(path).read_text(errors="ignore")
    except OSError:
        return None


def _cmd(args) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def collect(now_epoch: int) -> list[CheckStatus]:
    """Gather every signal into normalized statuses. Missing optional signals are
    skipped (not invented as failures)."""
    out: list[CheckStatus] = []

    bebop_log = _read(BASE / "bebop" / "logs" / "runs.log")
    if bebop_log is not None:
        out.append(check_bebop_runs(bebop_log, now_epoch))

    out.append(check_disk(_cmd(["df", "-P", "/"])))

    for unit in SERVICES:
        out.append(check_service_active(unit, _cmd(["systemctl", "is-active", unit])))

    for label, path in CRON_LOGS:
        text = _read(path)
        if text is not None:  # absent log = job may not be installed here; skip
            out.append(check_cron_log(label, text))

    return out


def format_report(fired: list[CheckStatus]) -> str:
    """Render fired checks worst-first into the investigator's briefing text."""
    ordered = sorted(fired, key=lambda s: -LEVELS.get(s.level, 0))
    lines = []
    for s in ordered:
        lines.append(f"[{s.level.upper()}] {s.name}: {s.summary}")
        if s.evidence:
            for ev in s.evidence.splitlines():
                lines.append(f"    | {ev}")
    return "\n".join(lines)


def main(argv=None) -> int:
    state_path = BASE / "watchdog" / "state.json"
    if os.environ.get("WATCHDOG_STATE"):
        state_path = Path(os.environ["WATCHDOG_STATE"])
    now = int(time.time())
    statuses = collect(now)
    prior = load_state(state_path)
    result = triage(statuses, prior, now)
    save_state(state_path, result["state"])

    fired = result["fired"]
    if fired:
        print(format_report(fired))
    else:
        print("all checks ok" if all(s.level == "ok" for s in statuses)
              else "issues present but suppressed (within cooldown)")

    payload = {
        "escalate": result["escalate"],
        "fired": [{"name": s.name, "level": s.level, "summary": s.summary,
                   "evidence": s.evidence} for s in fired],
        "checked": len(statuses),
    }
    print("WATCHDOG_JSON:" + json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
