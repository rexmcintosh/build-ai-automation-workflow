# backlog-run — the 3am backlog runner + morning review

**Date:** 2026-09-03
**Status:** Built (this branch). Spec of record for `backlogrun/`.
**Contract:** `~/projects/backlog/README.md` § "Safety contract for the 3am runner" (C1..C4 below).
**Origin:** backlog item `2026-07-18-3am-backlog-runner`.

## Goal

Work the `open` items in `~/projects/backlog/backlog.yaml` while Rex sleeps, leave every
result as a reviewable branch, and give him a morning report he can answer with
"approve 1 3; drop 2".

## Shape

One console entry point, `backlog-run`, in the `council` pipx package (mirrors
`session-gc`: a self-contained Python CLI, cron-driven, fail-closed, git addressed via
`-C`). State in `~/projects/.backlog-run/`.

```
work     cron 03:00 UTC   open -> in_review | held    (never anything else)
report   morning          numbered list of in_review items + held + open
approve  human            merge --no-ff -> push origin -> delete branch -> archive done
drop     human            delete branch (journaled) -> archive dropped
show / diff / list / hold / reopen
```

## How an item is worked

1. **Plan.** Open items, oldest `created` first. `repo: none` or a missing repo dir, an
   unsafe id, an unresolvable default branch, or an existing `claude/bl-<slug>` branch
   that carries commits → the item is marked `held` with a note (cheap, unbounded). An
   existing branch with **no** commits and no worktree is reclaimed (deleted, journaled)
   and the item worked. Workable items are taken up to `--max-items` (default 2); the
   rest stay `open` for the next night. `--dry-run` prints exactly this plan and changes
   nothing.
2. **Isolate.** `git worktree add -b claude/bl-<slug> <repo>/.claude/worktrees/bl-<slug> <default>`
   — the harness's own worktree home, so `session-gc snapshot` covers it too.
3. **Run.** `claude -p - --output-format json --dangerously-skip-permissions --settings <deny>
   --strict-mcp-config --mcp-config <empty> [--model] [--max-budget-usd]` with cwd = the
   worktree, the prompt on stdin (runner contract + the item's prompt), a per-item timeout
   (default 60 min, process group killed on expiry), and a **whitelist environment**.
4. **Settle.** Leftover uncommitted changes are committed (`backlog-run: leftover …`) so the
   branch holds everything. The final message's `RUNNER-OUTCOME` block decides:

   | outcome | branch has commits | item becomes |
   |---|---|---|
   | done | yes | `in_review` (+ council) |
   | done | no | `held` ("reported done but produced no changes") |
   | held | yes/no | `held` (+ note, branch kept if it has commits) |
   | failed / timeout / non-zero exit | yes | `held`, partial work kept |
   | failed / timeout / non-zero exit | no | `held`, empty branch deleted |
   | no marker | yes | `in_review` (noted) |
   | usage limit | yes | `held`; run stops |
   | usage limit | no | stays `open`; run stops |

5. **Review (C3).** `git diff <default>...<branch>` through the council `code-review` panel
   (in-process, same code path as `council review --diff`). The chair's recommendation +
   confidence go in `council:`; the full markdown in `~/projects/.backlog-run/reviews/<id>.md`.
   A review failure is recorded as the verdict (`REVIEW FAILED: …`), never hidden.
6. **Record (C4).** Under feedback-sync's lock directory, re-read `backlog.yaml`, update the
   one item (`status`, `branch`, `council`, `worked`, `note`, `session`, `cost_usd`),
   atomic write, commit the backlog repo (`backlog: <id> -> <status> (<branch>)`). No push —
   feedback-sync's `pushIfAhead` publishes within 15 min.
7. **Clean.** Worktree removed (branch kept); empty branches deleted and journaled.
8. **Tell.** Telegram summary (main bot, best-effort) + `report.md` rewritten.

## Safety (C1..C4) — what actually enforces each

- **C1 branch-contained.** `work` has no code path that merges or pushes. Only `approve` does,
  and it refuses if the main checkout is dirty or not on the default branch, aborts on
  conflict, and reports a failed push instead of pretending.
- **C2 no outward actions.** Five layers, verified 2026-09-03 on claude 2.1.259:
  1. environment whitelist (HOME/PATH/USER/LANG/TERM/TZ + `BACKLOG_RUN=1`, `CI=1`) — no
     `~/.env` secrets, no Claude-session vars, so a nested session starts clean;
  2. `GIT_CONFIG_*` env sets `url.<dead-path>.pushInsteadOf` for `https://`, `http://`,
     `git@`, `ssh://`, `git://` — a push to any real remote, whatever its name, even one
     added later, is rewritten to a path that does not exist and fails; fetches keep the
     real URL; local-path remotes (test suites' temp repos) still work. Command-line-level
     config, so no config file can undo it; a `git -c remote.X.pushurl=…` could, which the
     deny rules cover. (First cut overrode each remote's `pushurl`; the real run showed it
     also broke 11 loom tests that push to a temp `origin`.)
  3. `--settings` deny rules (push, remote, gh pr/release, wrangler, deploy scripts, netlify,
     vercel, supabase, stripe, curl/wget/ssh/scp/rsync, crontab, systemctl, sudo, docker,
     tg-send, mail, pipx) — enforced even under `--dangerously-skip-permissions`;
  4. `--strict-mcp-config` + empty config — no Gmail/Slack/Notion/Supabase/Playwright tools;
  5. the contract in the prompt with the `held` escape hatch.
  Not a sandbox: a determined session could still script around layer 3. The human review
  before any push is the backstop, which is exactly the contract's design.
- **C3** every `in_review` item has a `council:` line (or a recorded review failure).
- **C4** `_apply()` writes only `in_review`/`held` (or leaves `open`); approve/drop/hold/reopen
  are separate human commands.

Plus: one run at a time (flock on `~/projects/.backlog-run/lock`, contention exits 75);
per-item try/except so one failure never aborts the batch; bounded by `--max-items`,
`--item-timeout`, `--deadline`, `--budget-usd`.

## Consistency under partial failure (council round 1, 2026-09-03)

- A run's result is applied only if the item is **still `open`**; a concurrent human
  hold/reopen wins and the result is kept as a `CONFLICT` note (branch kept).
- Empty leftover `claude/bl-*` branches (no commits, no worktree) are reclaimed and
  journaled on the next run instead of holding the item forever; leftovers with work hold.
- `approve`: merge → push → **record in backlog** → delete branch; idempotent on re-run
  (`merge-base --is-ancestor` short-circuits). `drop`: record → delete.
- Archive moves write `archive.yaml` first; a crash between the two writes duplicates,
  never loses; the duplicate is reconciled (archive wins) on the next locked write.
- Item ids are validated as safe slugs before becoming branch names or paths.
- All mutating commands (`work`, `approve`, `drop`, `hold`, `reopen`) take the run lock.

Council round 2 (approve with changes): held branches that carry work are reviewed too, so
every mergeable branch has a verdict; `approve` is gated to `in_review` (held needs
`--held`); `repo:` is contained to the projects dir; the deny list covers `git -c …
push` / `--git-dir` variants (the pushurl guard stays the primary layer); YAML writes fsync.

## Morning review

`backlog-run report` numbers the `in_review` items; `approve 1 3`, `drop 2`, `show 1`,
`diff 1` take numbers (from the last report) or ids. Merge commits carry
`Backlog-Item:`/`Backlog-Branch:` trailers. Session worktrees left by hand-worked items are
removed when clean; a dirty one keeps its branch and is reported.

## Cron

```
0 3 * * *  /home/dev/.local/bin/backlog-run work >> /home/dev/projects/.backlog-run/cron.log 2>&1
```
03:00 UTC; loom runs 02:00 UTC and the writing engines 05:00/05:30 UTC on the same Max
quota — hence the conservative defaults (2 items, $20 each, 3 h deadline) and the
usage-limit stop.

## Not in scope

Slack/Telegram two-way approval from the phone (tabled 2026-09-03; see the held backlog
item), a keyword pre-screen of prompts (the session + deny rules decide), auto-merge of
anything.
