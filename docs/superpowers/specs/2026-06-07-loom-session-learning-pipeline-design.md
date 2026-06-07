# Loom — Session-Learning Pipeline — Design

- **Status:** Approved design (brainstormed 2026-06-07), ready for implementation planning.
- **Date:** 2026-06-07
- **Scope:** A standalone pipeline that absorbs working-session transcripts into the memory stack.
  All four routes built in v1. *("Loom" is a working name — it weaves sessions into memory. Renameable.)*

> **Thesis:** Loom distills each working session into discrete, sanitized learnings, then weaves each
> into the right layer of the memory stack — turning ephemeral 90-day transcripts into compounding,
> personal knowledge. Opus writes; cheaper models read.

---

## 1. Invariants

| Invariant | Means |
|---|---|
| **Delta-only** | Process only transcripts not yet absorbed (`absorb-log.json`). |
| **Sanitize-at-distill** | Secrets / keys / OAuth / PII are stripped in Stage 1; nothing downstream sees them. |
| **Opus writes, cheap reads** | Every write into a permanent store is Opus. Reading, classifying, stripping is Haiku/Sonnet. |
| **Everything reviewable** | The wiki is a local git repo (every absorb = a revertible commit); non-git writes are audited by the `learnings/` artifact + run log. |
| **Route, don't dump** | Each learning goes to exactly one home (MECE), or is deliberately dropped. |
| **Re-read before weave** | Never blind-append to a wiki article — read it whole, integrate (Farza anti-cram / anti-thin). |
| **Advance only on success** | `absorb-log` moves forward only after a clean run — no lost or double-absorbed sessions. |
| **Local-only** | The wiki repo has no remote. Personal knowledge never leaves the box. |

---

## 2. Purpose & context

Working sessions generate raw transcripts (`~/.claude/projects/<cwd>/*.jsonl`, retained 90 days)
that then age out. Today, capturing anything durable from them is **ad hoc** — a memory or spec gets
written only when someone remembers to. That is the leak Loom closes.

It is **standalone**, not part of Bebop. Bebop (the briefing assistant) routes *incoming life-data*
(email, calendar) for you; Loom absorbs *our working sessions* — a self-improvement loop. They share
the wiki/memory as a **destination**, nothing else. (Decided in brainstorming: source, trigger, and
purpose differ enough that welding them together would be a category error.)

The memory stack Loom feeds:

| Layer | Holds | Lifetime | Loaded |
|---|---|---|---|
| Session transcripts | raw firehose | 90 days | on resume |
| `memory/` md | curated facts + preferences | indefinite | every session |
| CLAUDE.md | standing instructions | indefinite | every session |
| RexBrain wiki (`~/wiki/`) | semantic "map of a mind" | indefinite | on-demand |
| Repo specs/docs | published decisions | indefinite (git) | on-demand |
| Skills (`~/.claude/skills/`) | reusable procedures | indefinite | on trigger |

---

## 3. Goals & non-goals

| Goals | Non-goals (v1) |
|---|---|
| Nightly (+ manual) absorb of session transcripts into the stack | Absorbing Bebop's email/calendar data (that's Bebop's job) |
| Capture 4 learning types, each routed to its correct layer | A search UI / FTS index (transcripts stay greppable as-is) |
| Autonomous but reviewable (git diff / revert) | Multi-machine sync; pushing the wiki to any remote |
| Opus quality on everything written to permanent stores | Real-time / per-turn capture (nightly batch only) |
| Cheap + bounded cost (cheap models read; Opus sees only small inputs) | Auto-editing CLAUDE.md unattended (proposed, not auto-applied) |

---

## 4. Architecture — two stages, per-step model

```
nightly cron (~02:00 Lisbon)  |  manual: run-absorb.sh now
  └─ Stage 1 · DISTILL  (per new transcript)
       Sonnet : read .jsonl (skip giant tool-output blobs) → extract discrete learnings
       Haiku  : classify each by type · sanitize (regex denylist + check)
       └─ write loom/learnings/YYYY-MM-DD_<session>.md   ← sanitized, classified middle layer
  └─ Stage 2 · WEAVE  (per session's learnings)
       Haiku  : confirm routing per learning
       Opus   : write each learning into its home (re-read target first)   [all writes]
       └─ git-commit the wiki repo
  └─ (script) rebuild wiki _index.md / _backlinks.json · advance absorb-log · log cost
  └─ fail-loud Telegram ping on error
```

---

## 5. Model plan

| Operation | R/W | Model | Why |
|---|---|---|---|
| Read transcript, git, logging, index rebuild, absorb-log | mechanical | **none** | scripted |
| Distill: extract learnings from transcript | read → intermediate | **Sonnet** | big input, faithfulness matters, but throwaway middle layer |
| Classify type · confirm route · sanitize-check | judgment | **Haiku** | classification / pattern work |
| Weave into wiki article | **write** | **Opus** | permanent knowledge |
| Create / patch a skill | **write** | **Opus** | permanent procedure |
| Write / update a memory file | **write** | **Opus** | permanent fact/preference |
| Append a decision entry | **write** | **Opus** | permanent record |

**Why Opus stays cheap here:** Opus never reads the 1 MB transcript — only the *distilled learnings*
(KBs) plus the *one target article* it edits. Cost scales with new-learning volume (a handful/day),
not session length.

---

## 6. Routing (the MECE core)

| Learning type | Home | Mechanism | Store |
|---|---|---|---|
| Fact about you / world / projects | `~/wiki/<dir>/` article | match index → create/update → re-read first | wiki (git) |
| Decision + rationale | `~/wiki/decisions/` | append dated entry | wiki (git) |
| Working-style preference | `~/.claude/.../memory/` (feedback) | add/update memory file | `.claude` |
| Reusable procedure / gotcha | `~/.claude/skills/<name>/SKILL.md` | create or patch | `.claude` |

- A learning that fits none, or is too thin to be worth a write, is **dropped** (logged, not written).
- CLAUDE.md changes are **proposed in the run summary**, never auto-applied (highest blast radius).
- The `learnings/` artifact records *what was written and where* — the audit trail for the non-git
  (`.claude`) destinations.

---

## 7. Components (`build-ai-automation-workflow/loom/`, sibling to `bebop/`)

| File | Responsibility |
|---|---|
| `loom/distill.md` | Stage-1 prompt: extract + classify + sanitize → learnings file. |
| `loom/weave.md` | Stage-2 prompt: routing rules + Farza wiki-writing discipline. |
| `loom/run-absorb.sh` | Runner: delta from absorb-log, per-step model calls, git commit, cost log, fail-loud ping. |
| `loom/absorb-log.json` | Absorbed transcripts (delta + idempotency). Gitignored. |
| `loom/learnings/` | Sanitized, classified middle artifacts. Gitignored (PII-adjacent, kept local). |
| `loom/logs/runs.log` | Per-run: stage, model, cost, counts. Gitignored. |
| `loom/README.md` | Operational doc. |
| crontab entry | `CRON_TZ=Europe/Lisbon`, ~02:00, → `cron.log`. |
| `~/wiki/` → git repo | `git init`, **no remote**, `.gitignore` for `_absorb*`/internals. |

---

## 8. Data flow

1. Cron (or `run-absorb.sh now`) lists transcripts newer than `absorb-log` across all project dirs.
2. **Distill** each (Sonnet): extract learnings → Haiku classify + sanitize → `learnings/<…>.md`.
3. **Weave** (per session): Haiku confirms each learning's route; Opus reads the target and writes
   the integration; one commit to the wiki repo.
4. Script rebuilds `_index.md` / `_backlinks.json`; runner logs cost and counts.
5. **On clean run** → advance `absorb-log`. **On failure** → Telegram ping; `absorb-log` unchanged.

---

## 9. Sanitization & safety

- **Stage 1 strips**, before anything is written: API keys, bot tokens, OAuth codes, `ntn_*`,
  bearer tokens, raw credentials, and email *contents* beyond the gist. Deterministic denylist/regex
  first; Haiku as a second-pass check.
- **Local-only wiki repo** — no remote, ever. A pre-commit secret-scan hook on the repo is the
  belt-and-suspenders against a future slip.
- `learnings/` and `logs/` are gitignored and stay on the (mesh-locked, `700`) box.

---

## 10. Cost model

| Driver | Tier | Scales with |
|---|---|---|
| Distill | Sonnet | total transcript volume/day (the variable cost) — capped by skipping tool-output blobs |
| Classify / sanitize | Haiku | learning count (cheap) |
| Weave (all writes) | Opus | new-learning count + target-article size (small) |

Measured on run #1, like Bebop. Expectation: dollars/month, not tens — Opus only authors KBs.

---

## 11. Error handling

| Failure | Behavior | Invariant |
|---|---|---|
| A transcript fails to distill | Skip it, log, continue others; its `absorb-log` entry not advanced | Advance-on-success · Delta-only |
| A weave write fails | That learning logged as failed; commit only what succeeded; ping | Everything-reviewable |
| Sanitizer uncertain | Err toward redaction (drop the snippet), flag in run summary | Sanitize-at-distill |
| `claude`/model error or non-zero exit | Telegram fail-loud ping; absorb-log unchanged | Advance-on-success |
| Wiki git conflict / dirty tree | Abort run, ping; never force | Local-only · Everything-reviewable |

---

## 12. What good looks like

**A good distilled learning** (sanitized, classified, routable — not raw transcript):
```
- type: fact
  subject: Liam (Rex's son)
  learning: Swims competitively for the Bullsharks club in Portugal; mobility training tracked.
  route: wiki/people/liam
- type: procedure
  subject: headless Claude Code + MCP
  learning: --allowedTools alone doesn't authorize MCP calls headlessly; needs --dangerously-skip-permissions.
  route: skills/claude-code-headless
```

**Good weave** — integrated into the existing `people/liam` article under a themed section, the
article re-read first, reads as a coherent whole.

**Bad weave** (the failure mode to design against) — a dated bullet blind-appended to the bottom:
`## 2026-06-07\n- swims for Bullsharks` — turning the article into an event log. The
**Re-read-before-weave** invariant exists to prevent exactly this.

---

## 13. Verification plan

- **Dry-run distill** on the last two days' transcripts → inspect `learnings/` for faithfulness +
  that no secrets survived (grep the artifact for known token patterns → must be zero).
- **One full absorb** → review the wiki `git diff`; confirm articles integrated (not appended),
  memory/skills writes correct, cost logged.
- **Idempotency** — re-run immediately → zero new writes (absorb-log holds).
- **Fail-loud** — force a model error → confirm Telegram ping + absorb-log unchanged.

---

## 14. Open questions (resolve in planning/build)

1. **Transcript parsing** — which `.jsonl` record types feed the distill (user/assistant text yes;
   cap or drop large tool_result blobs) and how aggressively to truncate for cost.
2. **Decision sub-routing** — v1 sends all decisions to `~/wiki/decisions/`; revisit whether
   repo-specific technical decisions should land as ADRs in their own repo later.
3. **`~/.claude` git-tracking** — v1 audits memory/skill writes via the `learnings/` artifact; decide
   later whether to also `git init ~/.claude` for diff/revert on those stores.
4. **Cadence vs. cost** — confirm nightly is right once run #1 cost is known.

---

## 15. Roadmap / future

- **CLAUDE.md auto-apply** — once trust is established, promote proposed instruction-changes from
  "in the run summary" to applied-with-commit.
- **Cross-source absorb** — let Bebop's email/calendar findings flow through the same weave engine
  (the engine is source-agnostic; only the distill front-end differs).
- **Recall metric** — track reduction in re-explanation as the signal that the stack is compounding.
