# Backlog runner

**Contract:** v1.0 · **Date:** 2026-09-05 · **Observed command:** `backlog-run work`

## Purpose and authority

**Default mode:** bounded change-producing preparation. At 03:00 UTC, work at most two eligible open backlog items in isolated `claude/bl-*` worktrees, council-review the result, and leave it `in_review` or `held`. Local cron documentation and host configuration confirm UTC scheduling. Canonical item state is `/home/dev/projects/backlog/backlog.yaml`; completed and dropped records are stored in `archive.yaml`.

It may create local worktrees and branches, run the scoped agent, write runner records, and transition only still-open items to `in_review` or `held`. It must not push, merge, deploy, send externally except its configured summary, or approve its own work. Human approval under the canonical merge protocol remains the merge authority; `backlog-run approve` is an explicit operator command, not a clock action.

**Secrets, names only:** `VENICE_COUNCIL_KEY` or `VENICE_API_KEY`, `TELEGRAM_BOT_TOKEN`; the runner passes a whitelist environment to the worker.

## Success and evidence

Success is a per-item run record, a council review file, and an item transition consistent with the recorded outcome. Inspect `/home/dev/projects/.backlog-run/cron.log`, `runs/<timestamp>-<id>.json`, `reviews/<id>.md`, `report.json`, `report.md`, and the backlog item. The runner’s own test suite covers its state transitions with fake workers.

## Failure, escalation, and gaps

Lock contention exits 75 and is visible in the cron log. Failed or ambiguous work is held or recorded rather than merged. The owner must use the morning report to judge work. The contract is reinforced by the backlog README safety contract but is not a replacement for it.
