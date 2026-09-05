# Scheduled-loop contract index

**Inventory date:** 2026-09-05. **Contract format:** v1.0. These documents record observed configuration and intended operating boundaries. They do not change, validate, or enforce a cron job, timer, or external service.

The inventory came from `crontab -l` and `systemctl --user list-timers --all` on the date above. A lifecycle may have more than one trigger. A successful process exit proves only that the entrypoint exited successfully; the evidence named in its contract is needed for the stated outcome.

Local evidence resolves the scheduler timezone: cron `3.0pl1-184ubuntu2` schedules all user jobs in the daemon timezone, and this host reports `Etc/UTC`. Its local `crontab(5)` says a user-set `TZ` affects only the child process, not scheduling. Therefore every cron time below is UTC; `CRON_TZ` entries are recorded as declared environment only. The same behavior is described in the [Ubuntu manual for the cron 3.0pl1 family](https://manpages.ubuntu.com/manpages/jammy/man5/crontab.5.html); do not substitute a Cronie or systemd-cron manual, which describes a different implementation.

| State | Schedule as installed | Entrypoint(s) | Lifecycle disposition | Contract or reason |
|---|---|---|---|---|
| active | 07:00, 18:00 UTC; declared `CRON_TZ=Europe/Lisbon` not scheduler-effective | `/home/dev/projects/build-ai-automation-workflow/bebop/run-briefing.sh morning`; same with `evening` | Bebop briefing | [bebop-briefings.md](bebop-briefings.md) |
| paused | every 5 min; hourly; every 5 min | `/home/dev/projects/splash_poller/supervise_meets.py`; `/home/dev/projects/splash_poller/discover_meets.py`; `/home/dev/projects/splash_poller/ingest_entries.py` | MeetTrack v2 supply engine | Paused in crontab since 2026-08-15. Remote database state was not checked. No run contract is active. |
| active | every 30 min | `/home/dev/projects/build-ai-automation-workflow/watchdog/run-watchdog.sh` | Automation watchdog | [watchdog.md](watchdog.md) |
| active | Monday 04:00 UTC; declared `CRON_TZ=Europe/Lisbon` not scheduler-effective | `/home/dev/projects/build-ai-automation-workflow/council/scripts/security-sweep.sh` | Council security sweep | [council-security-sweep.md](council-security-sweep.md) |
| active | 08:00, 21:00, 23:00, 23:40 UTC | `/home/dev/.local/bin/diem drain --checkpoint` | DIEM checkpoint drain | [diem-drain.md](diem-drain.md) |
| active | every minute | `/home/dev/.local/bin/agents once` | Agent-attention nudge | [agents-nudge.md](agents-nudge.md) |
| active | 02:00 UTC | `/home/dev/loom-runtime/loom/run-absorb.sh` | Loom session learning | [loom-absorb.md](loom-absorb.md) |
| active | every 10 min snapshot; Monday 08:00 UTC sweep | `/home/dev/.local/bin/session-gc snapshot`; `/home/dev/.local/bin/session-gc sweep` | Session worktree hygiene | [session-gc.md](session-gc.md) |
| active | Monday 07:30 UTC; declared `CRON_TZ=Europe/Lisbon` not scheduler-effective | `/home/dev/projects/build-ai-automation-workflow/setup/superpowers-slim-preamble/reapply.sh` | Superpowers preamble reapply | [superpowers-preamble.md](superpowers-preamble.md) |
| active | Tuesday 07:15 UTC; declared `CRON_TZ=Europe/Lisbon` not scheduler-effective | `/home/dev/projects/ultimate-portugal/scripts/verify-rents.mjs` | Ultimate Portugal rent verification | [ultimate-portugal-rent-verification.md](ultimate-portugal-rent-verification.md) |
| active | weekdays 05:00 UTC; every 15 min 06:00–21:00 UTC | `/home/dev/projects/swimtrack-website/engine/morning-run.sh`; `/home/dev/projects/swimtrack-website/engine/poller-cron.sh` | Swimtrack website writing engine | [swimtrack-writing-engine.md](swimtrack-writing-engine.md) |
| active | weekdays 05:30 UTC; every 15 min 06:00–21:00 UTC; Monday 09:00 UTC | `/home/dev/projects/ultimate-portugal/engine/morning-run.sh`; `/home/dev/projects/ultimate-portugal/engine/poller-cron.sh`; `/home/dev/projects/ultimate-portugal/engine/seo-run.sh` | Ultimate Portugal writing engine | [ultimate-portugal-writing-engine.md](ultimate-portugal-writing-engine.md) |
| active | every 15 min | `cwd=/home/dev/projects/sat-prep`; `npm run --silent feedback:market` | Attain Prep feedback sync | [attainprep-feedback-sync.md](attainprep-feedback-sync.md) |
| active | Monday 13:00 UTC; declared `CRON_TZ=Europe/Lisbon` not scheduler-effective | `cwd=/home/dev/projects/sat-prep`; `npm run --silent digest:market -- --send` | Attain Prep parent digest | [attainprep-parent-digest.md](attainprep-parent-digest.md) |
| active | 03:00 UTC | `/home/dev/.local/bin/backlog-run work` | Backlog runner | [backlog-run.md](backlog-run.md) |
| active | every 10 min | `cwd=/home/dev/projects/sat-prep`; `npm run --silent bento:market` | Attain Prep Bento sync | [attainprep-bento-sync.md](attainprep-bento-sync.md) |
| external | daily after activation and startup + 5 min | `launchpadlib-cache-clean.timer` → `/usr/lib/systemd/user/launchpadlib-cache-clean.service` | OS-owned cache cleanup | It deletes cache files older than 30 days under `~/.launchpadlib`. It is not a project automation loop and has no project owner or contract here. |

## Inventory totals

- 23 active cron entries, grouped into 15 lifecycle contracts.
- 3 commented, explicitly paused MeetTrack entries, grouped into one paused lifecycle.
- 1 active user timer, explicitly external to this project.

## Cross-cutting gaps and retirement candidates

| Finding | Evidence | Disposition |
|---|---|---|
| Cron entries do not point to these contracts. | The active crontab commands invoke entrypoints directly. | Mismatch. Add pointers only in a separately approved scheduler change. |
| `CRON_TZ` comments and legacy documentation conflict with the installed scheduler’s UTC behavior. | Installed `cron 3.0pl1-184ubuntu2`, local `crontab(5)`, and host `Etc/UTC`; Bebop README labels 07:00/18:00 Lisbon while its runner uses Europe/Lisbon for displayed time. | Documentation ambiguity. Classify each schedule as owner-local or UTC-budget before changing any schedule. |
| Several jobs load broad `~/.env` despite narrow needs. | Ultimate Portugal poller; Swimtrack poller; Council security sweep; Loom runner. The Attain Prep digest cron also sources `~/.env` before its package script loads `.env.market`. | Mismatch. Narrow secret custody at each entrypoint before treating the contract secret list as an access control. |
| `agents once` has no durable delivery result. Cron discards stdout/stderr, and its state file records a transition even if Telegram delivery fails. | `/home/dev/.local/bin/agents`; crontab redirection to `/dev/null`. | Repair candidate. It can state a measurable delivery goal, so it is not a loop-retirement candidate on that rule alone. Reconsider retirement only after an overlap audit shows another loop covers the same owner-attention need. |
| Security-sweep delivery is best effort. | `council/scripts/security-sweep.sh` ignores `tg-send` failure. | Mismatch. Its scan result can exist while the owner receives no summary. |
| Content-engine jobs are deploy-capable by their current entrypoints, but their contracts are outside their owning repos. | Swimtrack and Ultimate Portugal engine runners. | Ownership gap. Move each contract to its owning repository, then leave a pointer here; do not create two canonical contracts. |
