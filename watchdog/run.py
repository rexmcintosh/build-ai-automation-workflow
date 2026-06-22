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

import tomllib

from .triage import (
    CheckStatus,
    LEVELS,
    check_bebop_runs,
    check_cron_log,
    check_disk,
    check_service_active,
    triage,
)
from .metrics import sum_counter, count_matches, check_budget, parse_count_header, check_rate

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


def _load_monitors() -> dict:
    """Load watchdog/monitors.toml (the spike-monitor config). Absent/broken -> {} so
    the watchdog still runs its failure checks without it."""
    try:
        with open(BASE / "watchdog" / "monitors.toml", "rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _supabase_count(url: str, key: str, table: str) -> int | None:
    """Read-only row count via PostgREST (Prefer: count=exact). None on any failure —
    a count we can't read must not crash or fake an alert."""
    try:
        import requests
        r = requests.head(f"{url}/rest/v1/{table}?select=*",
                          headers={"apikey": key, "Authorization": f"Bearer {key}",
                                   "Prefer": "count=exact", "Range": "0-0"},
                          timeout=15)
        return parse_count_header(r.headers.get("Content-Range"))
    except Exception:  # noqa: BLE001 — network/parse error -> skip this metric
        return None


def collect_metrics(now_epoch: int, prior_metrics: dict) -> tuple[list[CheckStatus], dict]:
    """Layer 1+2 spike checks. Returns (statuses, new_metrics). new_metrics carries the
    current readings so the next poll can compute Supabase rows/hour deltas."""
    cfg = _load_monitors()
    out: list[CheckStatus] = []
    new_metrics: dict = {}
    window = int(cfg.get("settings", {}).get("window_lines", 6))

    # Layer 1a — windowed log-counter budgets
    for m in cfg.get("log_counters", []):
        text = _read(m["log"])
        if text is None:
            continue  # log absent (job not on this host) -> skip
        value = sum_counter(text, m["key"], lines=window)
        out.append(check_budget(m["name"], value, warn_at=m["warn"], crit_at=m["crit"]))
        new_metrics[m["name"]] = {"value": value, "ts": now_epoch}

    # Layer 1b — live process-count budgets
    procs = cfg.get("processes", [])
    if procs:
        ps = _cmd(["ps", "-eo", "args"])
        for m in procs:
            value = count_matches(ps, m["pattern"])
            out.append(check_budget(m["name"], value, warn_at=m["warn"], crit_at=m["crit"]))
            new_metrics[m["name"]] = {"value": value, "ts": now_epoch}

    # Layer 2 — Supabase row-growth (rows/hour) per hot table
    sb = cfg.get("supabase")
    if sb:
        key = os.environ.get(sb.get("key_env", "SUPABASE_SERVICE_ROLE_KEY"), "")
        if key:
            for table in sb.get("tables", []):
                current = _supabase_count(sb["url"], key, table)
                mkey = f"sb:{table}"
                prev_rec = prior_metrics.get(mkey, {})
                prev, prev_ts = prev_rec.get("value"), prev_rec.get("ts")
                elapsed = now_epoch - prev_ts if prev_ts else 0
                out.append(check_rate(table, current, prev, elapsed,
                                      warn_per_hour=sb["warn_per_hour"],
                                      crit_per_hour=sb["crit_per_hour"]))
                if current is not None:
                    new_metrics[mkey] = {"value": current, "ts": now_epoch}
                else:  # keep the old reading so a transient failure doesn't reset the baseline
                    if prev is not None:
                        new_metrics[mkey] = prev_rec

    return out, new_metrics


def collect(now_epoch: int, prior_metrics: dict | None = None) -> tuple[list[CheckStatus], dict]:
    """Gather every signal into normalized statuses. Returns (statuses, new_metrics).
    Missing optional signals are skipped (not invented as failures)."""
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

    metric_statuses, new_metrics = collect_metrics(now_epoch, prior_metrics or {})
    out.extend(metric_statuses)
    return out, new_metrics


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
    metrics_path = Path(os.environ.get("WATCHDOG_METRICS",
                                       str(BASE / "watchdog" / "metrics-history.json")))
    now = int(time.time())
    prior_metrics = load_state(metrics_path)
    statuses, new_metrics = collect(now, prior_metrics)
    save_state(metrics_path, new_metrics)
    prior = load_state(state_path)
    result = triage(statuses, prior, now)
    save_state(state_path, result["state"])

    fired = result["fired"]
    if fired:
        print(format_report(fired))
    else:
        print("all checks ok" if all(s.level == "ok" for s in statuses)
              else "issues present but suppressed (within cooldown)")

    # Log every metric value on every poll — this is how we bank a baseline to tune
    # the (currently hard-coded) budgets and add statistical thresholds later.
    if new_metrics:
        readings = " ".join(f"{k}={v.get('value')}" for k, v in sorted(new_metrics.items()))
        print("WATCHDOG_METRICS:" + readings)

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
