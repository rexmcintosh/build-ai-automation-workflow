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

## Spike monitoring (rate/volume, not just failures)

The failure checks above answer *"did something error?"*. The spike monitor answers
*"is something doing far more than normal?"* — the gap that let a weekend splash_poller
restart-storm burn through Supabase writes while every poll still read "all ok".
Config lives in [`monitors.toml`](monitors.toml) (data, not code; no secrets):

| Layer | Watches | Fires when |
|---|---|---|
| **1 — log counters** | `relaunched`/`launched` (supervise), `ingested` (ingest), summed over the recent window | value ≥ budget |
| **1 — processes** | live `poller.py` count (`ps`) | count ≥ budget |
| **2 — Supabase** | row counts of hot tables (`results`,`splits`,`swimmers`) via read-only PostgREST | rows/hour ≥ budget |

Detection uses **hard budgets** (no cold-start, no tuning). Every metric value is logged
on **every poll** (`metrics:` lines in `logs/runs.log`) so you can calibrate the budgets
and add statistical thresholds later. Supabase needs `SUPABASE_SERVICE_ROLE_KEY` in the
environment — the runner sources it from `WATCHDOG_ENV_FILE` (default
`/home/dev/projects/splash_poller/.env`) **inside a subshell**, so the investigator agent
never inherits the secret.

### Layer 3 — Supabase spend cap (manual, do once)

The watchdog is the in-system tripwire; the provider-side cap is the seatbelt that stops
spend even if the VPS is down. In the Supabase dashboard for project
**`moaagxigxjyuuqygoqfg`**: *Organization → Billing → Cost Control* — set a **spend cap**,
and *Project → Settings → Billing* — add a **usage alert** email. This isn't code; it's a
two-minute config that backstops everything above.

## Flap suppression

`triage()` re-alerts a problem only when it's **new**, has **worsened**, or the
**cooldown** (6h) has elapsed since the last alert. Recovered checks drop from state.
Nothing is silently dropped — every poll appends to `logs/runs.log`.

## Boundary

The investigator agent runs with `--allowedTools Read mcp__…telegram…reply` only —
**no Bash/Write/Edit**. It can read logs and send one Telegram message. It cannot
change anything.

## Architecture

- `triage.py` — failure checks: pure functions over collected text → `CheckStatus`.
  Unit-tested (`tests/test_watchdog_triage.py`).
- `metrics.py` — spike checks: pure rate/budget functions → `CheckStatus`. Unit-tested
  (`tests/test_watchdog_metrics.py`).
- `monitors.toml` — spike-monitor config (log counters, processes, Supabase tables + budgets).
- `run.py` — collects real signals, loads/saves `state.json` + `metrics-history.json`,
  triages, emits the report + `WATCHDOG_JSON:`/`WATCHDOG_METRICS:` lines. Plumbing tested
  in `tests/test_watchdog_run.py`.
- `run-watchdog.sh` — cron entry; parses the pre-check, escalates to the agent.
- `prompts/investigate.md` — the read-only investigator prompt.

## Deploy (human-gated — not auto-installed)

After merge to `main`, add to crontab (every 30 min):

```
*/30 * * * *  /home/dev/projects/build-ai-automation-workflow/watchdog/run-watchdog.sh  >> /home/dev/projects/build-ai-automation-workflow/watchdog/logs/cron.log 2>&1
```

`state.json` and `logs/` are gitignored.
