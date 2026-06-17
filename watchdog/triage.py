"""Triage core: pure functions over already-collected signals.

The boundary is deliberate. These functions take *raw text* (a log file's
contents, `df` output, `systemctl is-active` output) and return a normalized
``CheckStatus``. All real I/O — reading files, shelling out — lives in
``run-watchdog.sh``. That keeps the decision logic unit-testable with sample
data and free of the environment.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Ordered so we can compare severities numerically (worsening detection).
LEVELS = {"ok": 0, "warn": 1, "crit": 2}


@dataclass
class CheckStatus:
    name: str
    level: str  # ok | warn | crit
    summary: str
    evidence: str = ""


# --- individual checks ------------------------------------------------------

_BEBOP_LINE = re.compile(r"^\[(?P<ts>[^\]]+)\].*\brc=(?P<rc>-?\d+)\b")


def check_bebop_runs(log_text: str, now_epoch: int, *, max_gap_hours: int = 14) -> CheckStatus:
    """Health of the bebop briefing from its runs.log.

    crit  — the most recent run failed (rc != 0).
    warn  — no run logged, or the last success is older than ``max_gap_hours``
            (a scheduled briefing was missed).
    ok    — the last run succeeded recently.
    """
    last = None
    for line in log_text.splitlines():
        m = _BEBOP_LINE.match(line.strip())
        if m:
            last = m
    if last is None:
        return CheckStatus("bebop", "warn", "no bebop runs logged yet")
    rc = int(last.group("rc"))
    if rc != 0:
        return CheckStatus("bebop", "crit", f"last bebop run failed (rc={rc})",
                           evidence=last.group(0))
    try:
        ts = datetime.fromisoformat(last.group("ts"))
        age_h = (now_epoch - ts.timestamp()) / 3600
    except ValueError:
        return CheckStatus("bebop", "warn", "last bebop run has an unparseable timestamp",
                           evidence=last.group("ts"))
    if age_h > max_gap_hours:
        return CheckStatus("bebop", "warn",
                           f"no bebop run in {age_h:.0f}h (a briefing may have been missed)")
    return CheckStatus("bebop", "ok", f"last bebop run ok, {age_h:.0f}h ago")


_DISK_PCT = re.compile(r"(\d+)%")


def check_disk(df_output: str, *, threshold: int = 85) -> CheckStatus:
    """Root-filesystem usage from `df -P /`. >=95% crit, >=threshold warn."""
    pct = None
    for line in df_output.splitlines():
        m = _DISK_PCT.search(line)
        if m:
            pct = int(m.group(1))  # last data line wins; header has no %
    if pct is None:
        return CheckStatus("disk", "warn", "could not parse df output", evidence=df_output[:200])
    if pct >= 95:
        return CheckStatus("disk", "crit", f"root filesystem {pct}% full")
    if pct >= threshold:
        return CheckStatus("disk", "warn", f"root filesystem {pct}% full")
    return CheckStatus("disk", "ok", f"root filesystem {pct}% full")


def check_service_active(name: str, systemctl_output: str) -> CheckStatus:
    """`systemctl is-active <unit>` — 'active' is ok, anything else is crit."""
    state = systemctl_output.strip()
    if state == "active":
        return CheckStatus(f"svc:{name}", "ok", f"{name} is active")
    return CheckStatus(f"svc:{name}", "crit", f"service {name} is {state or 'unknown'}")


# Match error words, but NOT when they're a key in a key=value metric line
# (e.g. "failed=0", "error=0") — those are counters, not errors. The (?!=)
# lookahead excludes the `=` case while still matching "FAILED rc=1", "error:", etc.
_ERROR_MARKERS = re.compile(
    r"traceback|exception|\b(?:error|failed|critical)\b(?!=)", re.IGNORECASE)


def check_cron_log(name: str, log_text: str, *, tail_lines: int = 50) -> CheckStatus:
    """Scan the tail of a cron log for error markers. Tail-only so an old, since-
    resolved error doesn't fire forever."""
    tail = log_text.splitlines()[-tail_lines:]
    hits = [ln for ln in tail if _ERROR_MARKERS.search(ln)]
    if hits:
        return CheckStatus(f"cron:{name}", "warn",
                           f"{len(hits)} error marker(s) in recent {name} log",
                           evidence="\n".join(hits[-5:]))
    return CheckStatus(f"cron:{name}", "ok", f"{name} log clean")


# --- triage (escalation + flap suppression) ---------------------------------

def triage(statuses, prior_state, now_epoch, *, cooldown_hours: int = 6) -> dict:
    """Decide what to escalate.

    A non-ok status *fires* (escalates) when it is new, when it has worsened
    since the last alert, or when the cooldown window has elapsed since the last
    alert. Repeats at the same level within the window are suppressed (flap
    control). Recovered checks (now ok) are dropped from state.

    Returns ``{"escalate": bool, "fired": [CheckStatus], "state": new_state}``.
    """
    cooldown = cooldown_hours * 3600
    fired = []
    new_state = {}
    for s in statuses:
        if s.level == "ok":
            continue  # recovered or healthy -> not carried in state
        prior = prior_state.get(s.name)
        if prior is None:
            should_fire = True
        elif LEVELS[s.level] > LEVELS.get(prior["level"], 0):
            should_fire = True  # worsened -> fire immediately
        else:
            should_fire = (now_epoch - prior["ts"]) >= cooldown
        if should_fire:
            fired.append(s)
            new_state[s.name] = {"level": s.level, "ts": now_epoch}
        else:
            # suppressed: keep the original alert time so cooldown is measured
            # from when we actually told the human, not from each poll.
            new_state[s.name] = {"level": s.level, "ts": prior["ts"]}
    return {"escalate": bool(fired), "fired": fired, "state": new_state}
