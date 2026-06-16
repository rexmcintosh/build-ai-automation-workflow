# Industrial-revolution features — design of record

> **Source idea:** Naval's *The AI Industrial Revolution* podcast (2026-06-01).
> See the assessment that produced this list in the session that created this doc.
> **Approval:** Rex delegated approval ("build and deploy all these — make decisions
> for me") for an unattended overnight build (2026-06-16). Decisions below are mine,
> recorded so they can be audited on review. Where I chose a tighter scope than the
> idea's maximal form, the rationale is stated.

## The boundary that governs all four

The project's core guardrail is **"the AIs argue; the human adjudicates; nothing ships
without a human go."** Every feature here preserves it:

- **A (watchdog)** diagnoses and *proposes*; it never fixes prod. (Article's "silver platter".)
- **B (compare)** *selects* among candidates; the human still merges the winner.
- **C (sweep)** *reports* security findings; it opens nothing.
- **D (fix→PR)** opens a **PR** into the existing council CI gate; the human merges.

Two operations are explicitly **out of scope for the unattended run** and left as
human-gated steps with everything prepared: **merging to `main`** (standing rule) and
**editing the live crontab** (it runs real jobs; touching it unattended is reckless).
Each feature ships a ready-to-run install/trigger step instead.

---

## Feature A — Mesh watchdog (autonomous SRE)  → maps to article idea #5

**Purpose.** Watch the automated system's own moving parts; when a signal is anomalous,
a cheap agent investigates and posts a diagnosis + proposed fix to Telegram. Human applies.

**Cost discipline (the bebop lesson).** No tokens are spent unless a cheap, AI-free
*collector* first detects something worth investigating. Healthy polls cost $0.

**Architecture (mirrors bebop).**
- `watchdog/triage.py` — **pure functions** over already-collected raw data (log text,
  `df` output, `systemctl` output). The whole point of the boundary: logic is unit-tested
  with sample data; the shell does the real I/O. Returns `CheckStatus(name, level, summary, evidence)`
  where `level ∈ {ok, warn, crit}`.
- Checks v1 (YAGNI): `check_bebop_runs` (last run failed / a scheduled briefing missed),
  `check_cron_log` (recent error markers in a log — reused for loom + MeetTrack logs),
  `check_disk` (root fs % over threshold), `check_service_active` (e.g. tailscaled).
- `triage(statuses, prior_state, now)` — decides whether to escalate, with **flap
  suppression**: don't re-alert the same `(check, level)` within a cooldown window unless
  it worsens. Always logs; only escalates on change. ("No silent drops.")
- `watchdog/run-watchdog.sh` — cron entry: collects raw signals → pipes to triage →
  if escalation fires, builds an investigation prompt with the evidence and calls headless
  `claude -p --model haiku` to produce *diagnosis + proposed fix* → Telegram reply →
  logs to `watchdog/logs/runs.log` + advances `watchdog/state.json`.

**Schedule (prepared, not installed):** `*/30 * * * *`.

**Why tighter than the article:** Vercel auto-remediates; we stop at "propose" to keep
the human-go guardrail. Deliberate.

---

## Feature B — `council compare` (waste tokens, save time)  → idea #2

**Purpose.** Today the council only *reviews* one artifact. Add the **selection** half of
"throw N models at it": given N candidate solutions to the same task, the panel ranks them
and the chair picks the winner + grafts the best ideas from runners-up.

**Scope decision.** The council owns *selection* (deterministic, testable). *Generation*
of candidates (running Codex/Claude/Gemini on a task) is the heavy, non-deterministic half:
- For self-contained prompts, `council/scripts/parallel-attempts.sh` generates K answers
  across K Venice models and pipes them to `compare` — a real end-to-end "waste tokens" loop.
- For repo-wide code building, generation is `claude` / parallel git worktrees (the existing
  Workflow primitive). Left as the documented heavy path; not re-implemented tonight.

**Architecture (additive to council).**
- `council/compare.py`:
  - `run_compare(task, candidates, panel, client, *, chair_model)` — each panelist sees the
    task + **all** candidates (blind to each other) and returns a ranking + pick + rationale.
  - chair `synthesize_comparison` → `ComparisonResult(winner, ranking, rationale, grafts)`.
- New models: `CandidateVote`, `ComparisonResult` in `models.py`.
- New prompts: `COMPARE_OUTPUT`, `COMPARE_SYNTH` in `prompts.py`.
- Render: `render_comparison`.
- CLI: `council compare --task "..." FILE [FILE ...] [--panel code-review]`.

---

## Feature C — `council sweep` (autonomous security research)  → idea #6

**Purpose.** A repo-wide, multi-agent security pass (the `deepsec` shape) rather than the
diff-only review. Fan the **red-team** panel across the whole tree, aggregate + dedup findings,
gate by severity, and produce one consolidated report. Ours is "fan N chunks across the panel,
bounded by a cap," not "10,000 agents" — explicitly bounded, and it **logs what it drops**.

**Architecture (additive to council).**
- `council/sweep.py`:
  - `chunk_repo(path, cap, max_chunks)` — reuse the file-walking from `_read_for_review`
    (skips dotfiles/binaries/symlinks, byte-bounded). Returns labeled chunks; logs anything
    dropped past `max_chunks`.
  - `run_sweep(chunks, panel, client, *, chair_model)` — run the security panel per chunk,
    collect findings, **dedup** by normalized (severity, point), gate, chair-synthesize top risks.
  - `SweepReport(findings, dropped, by_severity)`.
- CLI: `council sweep <path> [--max-chunks N]`.
- `council/scripts/security-sweep.sh` — scheduled runner (Telegram summary). Prepared cron:
  weekly `0 4 * * 1`. Not installed.

**Verify pattern:** high-severity findings are re-checked by the chair (adversarial pass)
before they make the report, to suppress plausible-but-wrong findings.

---

## Feature D — fix→PR loop (feedback → fix → ship)  → idea #7

**Purpose.** Inbound issue → headless Claude reproduces, writes a minimal fix on a fresh
branch, commits, pushes, opens a PR → the **existing** GitHub Actions council review runs on
the PR → human merges. Reuses bebop's runner shape + the existing PR gate.

**Architecture.**
- `fixit/queue.py` — **testable** queue logic: claim the next pending issue from a JSON/dir
  queue, mark it done/failed, dedup. (The one deterministic piece — gets unit tests.)
- `fixit/prompts/fix.md` — constrained agent prompt: reproduce → *minimal* fix → run tests →
  commit → push → `gh pr create`. Never touches `main`; one branch per issue.
- `fixit/run-fixit.sh` — runner. `--dry-run` (default) stops before `gh pr create`;
  `--demo` opens one real demonstration PR to prove the pipeline end-to-end.

**Safety / scope.** No cron, no auto-trigger on real inbound issues tonight — it writes code.
Trigger is manual for now; the article's auto-loop (TestFlight-style ingest) is a later wiring
(Telegram listener / CI-failure webhook). Tonight: build it, unit-test the queue, and run **one
demo PR** as evidence the loop works.

---

## Cross-cutting

- `council` version bump `0.2.0 → 0.3.0` (two new subcommands).
- READMEs updated per component; this repo's top-level docs get a pointer.
- TDD throughout for the deterministic cores (triage, compare, sweep aggregation, queue).
  The agentic shells are verified by dry-run/demo, not unit tests.
- Each feature is committed + pushed to the branch as it lands. No merge to `main`.
