# watchdog — autonomous SRE for the mesh

Watches the automation system's *own* moving parts (bebop, loom, MeetTrack, disk,
key services). When a signal is anomalous, a read-only agent investigates and posts
a **diagnosis + proposed fix** to Telegram. It never fixes production — it puts a fix
on a silver platter and lets Rex decide. (Maps to the "autonomous SRE" idea from
Naval's *AI Industrial Revolution* — minus the auto-remediation, by design.)

## Cheap-first

A pure-Python pre-check (`watchdog/run.py`) collects signals and triages them with
**flap suppression** — no tokens are spent on a healthy poll. Only when something
*fires* does the shell invoke the investigator agent.

## Run

```bash
./watchdog/run-watchdog.sh --dry-run   # collect + triage, print what WOULD escalate
./watchdog/run-watchdog.sh             # …and actually investigate + notify on escalation
```

## What it checks (v1)

| Check | Signal | Fires when |
|---|---|---|
| `bebop` | `bebop/logs/runs.log` | last run failed (crit), or no run in >14h (warn) |
| `disk` | `df -P /` | ≥95% crit, ≥85% warn |
| `svc:tailscaled` | `systemctl is-active` | not `active` (crit) |
| `cron:*` | loom + MeetTrack logs | error markers in the recent tail (warn) |

Error-marker matching ignores `key=value` counters (e.g. `failed=0`) so metric lines
don't read as failures.

## Flap suppression

`triage()` re-alerts a problem only when it's **new**, has **worsened**, or the
**cooldown** (6h) has elapsed since the last alert. Recovered checks drop from state.
Nothing is silently dropped — every poll appends to `logs/runs.log`.

## Boundary

The investigator agent runs with `--allowedTools Read mcp__…telegram…reply` only —
**no Bash/Write/Edit**. It can read logs and send one Telegram message. It cannot
change anything.

## Architecture

- `triage.py` — pure functions over collected text → `CheckStatus`. Unit-tested
  (`tests/test_watchdog_triage.py`).
- `run.py` — collects real signals, loads/saves `state.json`, triages, emits the
  escalation report + a `WATCHDOG_JSON:` line. Plumbing tested in `tests/test_watchdog_run.py`.
- `run-watchdog.sh` — cron entry; parses the pre-check, escalates to the agent.
- `prompts/investigate.md` — the read-only investigator prompt.

## Deploy (human-gated — not auto-installed)

After merge to `main`, add to crontab (every 30 min):

```
*/30 * * * *  /home/dev/projects/build-ai-automation-workflow/watchdog/run-watchdog.sh  >> /home/dev/projects/build-ai-automation-workflow/watchdog/logs/cron.log 2>&1
```

`state.json` and `logs/` are gitignored.
