# backlog-run

The 3am backlog runner and the morning-review tool for `~/projects/backlog`.
Spec: `../docs/superpowers/specs/2026-09-03-backlog-runner-design.md`.
Contract it obeys: `~/projects/backlog/README.md` § "Safety contract for the 3am runner".

Each `open` item is worked by a cold, headless Claude Code session inside its own git
worktree on a fresh `claude/bl-<slug>` branch of the item's repo, council-reviewed, and left
as `in_review` (or `held`) for you. Nothing is ever pushed or merged by the clock.

## Commands

    backlog-run work --dry-run           # what tonight would do; changes nothing
    backlog-run work                     # the nightly run (cron); open -> in_review | held
    backlog-run work --only <id>         # one specific item (also --repo NAME, --max-items N)
    backlog-run report                   # morning report, numbered
    backlog-run show 1  |  diff 1        # details / full diff (number from the report, or an id)
    backlog-run approve 1 3              # merge --no-ff into main, push, delete branch, archive done
    backlog-run drop 2                   # delete branch (journaled), archive dropped
    backlog-run hold <id> "why"          # park an item;  backlog-run reopen <id> returns it
    backlog-run list

`work` flags: `--max-items` (2) · `--item-timeout` seconds (3600) · `--deadline` seconds
(10800) · `--budget-usd` per session (20; 0 = none) · `--model` · `--no-council` ·
`--no-notify` · `--keep-worktree`.

## What the session gets

- cwd = the worktree; prompt = runner contract + the item's `prompt`; the repo's own
  CLAUDE.md applies.
- A whitelist environment (no `~/.env`, no Claude-session vars), `git push` disabled via
  `GIT_CONFIG_*` pushurl override, deny rules for push/deploy/send/spend commands (held in
  `~/projects/.backlog-run/claude-settings.json`), no MCP servers.
- It must end with a `RUNNER-OUTCOME: done|held|failed` block; `held` is its escape hatch
  for anything that needs a human or an outward action.

## Guarantees under failure

- An item is only transitioned if it is **still `open`** when the run finishes. If you
  held/reopened it meanwhile, your state wins and the run's result becomes a
  `runner: CONFLICT …` note (the branch is kept).
- An empty leftover `claude/bl-*` branch (no commits, no worktree) is reclaimed on the next
  run, journaled; a leftover branch **with** work holds the item instead.
- A council failure is recorded as the verdict (`REVIEW FAILED: …`); the item still goes to
  `in_review` — the morning report shows it, you review by hand.
- `approve` records the merge in the backlog **before** deleting the branch and is safe to
  re-run (an already-merged branch is not merged twice). `drop` records before deleting.
- An archive move writes `archive.yaml` first; an id found in both files is reconciled in
  favour of the archive on the next write.
- Lock contention exits 75 (`EX_TEMPFAIL`), so a skipped nightly run shows up in `cron.log`.

## Item fields the runner writes

`status`, `branch`, `worked`, `council`, `note`, `session` (claude session id), `cost_usd`.
`approve` adds `merged`, `merge_commit`; `drop` adds `dropped`. Both move the item to
`archive.yaml`.

## State

`~/projects/.backlog-run/`: `report.md` + `report.json` (number → id), `reviews/<id>.md`
(full council output), `runs/<ts>-<id>.json` (raw session result), `journal.log`
(branch deletions: ts, repo, branch, sha, action — restore with `git branch <name> <sha>`),
`lock`, `cron.log`.

Environment overrides: `BACKLOG_PATH`, `BACKLOG_RUN_STATE`, `BACKLOG_RUN_PROJECTS`,
`BACKLOG_RUN_CLAUDE` (binary), `BACKLOG_RUN_GIT=0` (no backlog commits),
`BACKLOG_RUN_TG=0` (no Telegram), `BACKLOG_RUN_TG_CHAT`, `BACKLOG_RUN_TG_SEND`,
`BACKLOG_RUN_ENV_FILE` (where the Venice key is read from for the council step).

## Cron

    0 3 * * *  /home/dev/.local/bin/backlog-run work >> /home/dev/projects/.backlog-run/cron.log 2>&1

## Install / update

    pipx install --force ~/projects/build-ai-automation-workflow

## Tests

    python3 -m pytest tests/test_backlogrun.py -q

They run the whole `work`/`approve`/`drop` flow against temp git repos with a fake `claude`
binary (no network, no real sessions) and assert the scrubbed environment, the pushurl
guard, the state transitions, the YAML round trip and the lock.
