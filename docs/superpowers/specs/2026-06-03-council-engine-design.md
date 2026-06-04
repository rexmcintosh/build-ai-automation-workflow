# Council Engine + On-Demand CLI — Design (Piece 1)

- **Status:** Approved design, ready for implementation planning
- **Date:** 2026-06-03
- **Scope:** Piece 1 of the "council of agents" roadmap (engine + on-demand CLI).

---

## 1. Purpose & context

The Phase 1 Venice review council (`setup/templates/venice_review.py` + `venice-review.yml`)
is **reactive and PR-only**: a GitHub Action fans a code diff out to a 4-persona
panel and posts one comment. This piece generalizes that into a reusable
**council engine** plus an **on-demand `council` CLI** you can run on the VPS to
consult a multi-model panel about *anything* — a decision, a design doc, a code
file, an idea — not just PR diffs.

It is **Piece 1 of a 3-piece roadmap** (each piece gets its own spec → plan →
build):

1. **Council engine + on-demand CLI** ← *this spec*
2. Review beyond code (design docs / specs / plans), triggered by file/PR change or command
3. Proactive proposing (scheduled agents that surface work as GitHub issues / draft PRs)

Pieces 2 and 3 are thin front-ends on the engine built here.

### Inspiration

Panelist design draws directly on the **gstack** suite's persona-based review
skills (`plan-ceo-review`, `plan-eng-review`, `plan-design-review`,
`plan-devex-review`, `cso`, `office-hours`, `codex`, `autoplan`). Key lessons
adopted: personas are *named characters with laws and banned hedges*; every
finding carries a *confidence score behind a noise gate*; at least one voice is
*genuinely independent*; and the orchestrator treats *disagreement as a typed
signal* (mechanical / taste / user-challenge).

---

## 2. Goals & non-goals

**Goals**
- One reusable engine: fan a prompt out to a configured panel (parallel), then a
  "chair" model synthesizes a consensus.
- A `council` CLI: `ask`, `review`, `panels`.
- Four preset panels (`code-review`, `decision`, `brainstorm`, `red-team`) +
  auto-pick router when none is named.
- Synthesis-on-top output with collapsible per-member detail.
- Confidence noise-gate (`--rigor`).
- Refactor `venice_review.py` to reuse the engine (one engine, two front-ends).
- Installable as a global `council` command on the VPS.

**Non-goals (explicitly out of scope for Piece 1)**
- **Named modes** (ambition axis EXPAND/HOLD/REDUCE; finer rigor postures) —
  documented fast-follow, see §15.
- **Pieces 2 & 3** (auto-review of docs via Action; proactive scheduled proposing).
- **Multi-round debate** — members do NOT see each other's answers; single-round
  fan-out + chair synthesis only. (Independence is a feature, see §6.)
- Web UI; conversation memory / multi-turn sessions.

---

## 3. Architecture

A small installable Python package, **`council/`**, inside
`build-ai-automation-workflow`. Pure Python (`requests` + `concurrent.futures`),
no agent framework — the pattern `venice_review.py` already proves.

```
            council ask "Q" [--panel P] [--file f] [--rigor R]
                                  │
                    assemble context (Q + files, truncated)
                                  │
        ┌──────────── panel select ────────────┐
        │  --panel wins → else router → else default │
        └───────────────────┬───────────────────┘
                            ▼
         engine.run_panel(panel, context)   ── parallel, members blind to each other
            │        │        │        │
          member   member   member   member   → MemberResult{stance, confidence, findings…}
            └────────┴───┬────┴────────┘
                         ▼
        synthesize(context, results)   ── the "chair": consensus + typed disagreements
                         ▼
        render(synthesis, results, rigor)   ── synthesis on top, raw below; noise-gated
                         ▼
              terminal / markdown (+ --save)
```

### Modules (small, single-purpose)

| Module | Responsibility |
|---|---|
| `council/venice.py` | One Venice chat call: timeout, bounded retry, error → structured "errored" result. JSON-mode helper. |
| `council/config.py` | Load defaults + `panels.toml` (+ user override); resolve models, byte caps, `VENICE_API_KEY`. |
| `council/models.py` | Dataclasses: `Member`, `Panel`, `MemberResult`, `Finding`, `Synthesis`. |
| `council/engine.py` | `run_panel(panel, context) -> [MemberResult]` — parallel fan-out + collect. |
| `council/router.py` | `pick_panel(context, panels) -> name` — one cheap model picks a panel; fallback to default. |
| `council/synthesize.py` | `synthesize(context, results) -> Synthesis` — the chair (see §6). |
| `council/render.py` | Synthesis-on-top markdown / terminal; per-member detail; applies the rigor gate. |
| `council/cli.py` | `ask` / `review` / `panels` subcommands (argparse). Console entry point `council`. |
| `council/panels.toml` | Preset panels + persona prompts, as data. |
| `setup/templates/venice_review.py` *(refactor)* | Keeps GitHub I/O (diff, comment, check, exit code); body becomes `engine.run_panel(code_review) + render`. |

Packaging: a `pyproject.toml` exposes `council = "council.cli:main"`; install on
the VPS via `pipx install ~/projects/build-ai-automation-workflow` (or `pip
install -e .`).

---

## 4. Preset panels & personas

Panels live in `council/panels.toml` as data — adding/editing a council is a
config change, not code. Initial set (3–4 seats each, differentiated by **lens**,
not topic):

| Panel | Panelists (lens) — fixed membership |
|---|---|
| **code-review** | Eng Manager (architecture, blast radius, tests) · Security Officer (real vulns, 8/10 gate) · Adversary ("how does this fail in prod — attacker + chaos engineer") |
| **decision** | Founder (premise challenge: "is this the right problem? what if we did nothing?") · Eng Manager (feasibility, "boring by default") · Inversion Adversary ("what would make us fail?") |
| **brainstorm** | YC Partner / builder ("delight is the currency") + forcing questions · Founder / scope-expansion ("the 10× version") · Designer (emotional arc, magical moment) |
| **red-team** | Adversary · Security Officer (comprehensive 2/10 gate, flags `TENTATIVE`) · Eng Manager (edge cases, "what breaks 2am Friday") · Inversion Founder |

Memberships are **fixed per panel** (no auto-detection of input type in Piece 1).
`panels.toml` also ships a library of extra seats (e.g. **DX Advocate**,
**Designer**) that a user can add to any panel by editing config; *automatic*
context-based seat selection is a fast-follow (§15).

### Persona-prompt recipe (the quality bar)

Every panelist's `system` prompt is built with the gstack techniques:

1. **Concrete identity with a number** — *"a developer advocate who has onboarded
   onto 100 dev tools,"* not "a reviewer."
2. **3–5 named, non-negotiable laws** — e.g. "Zero silent failures," "Interest is
   not demand," "Specificity is the only currency."
3. **Cognitive patterns to *internalize, not enumerate*** — Munger inversion,
   Jobs subtraction, Conway's law, "boring by default."
4. **Banned hedges** — a per-persona anti-sycophancy list ("never say 'that's an
   interesting approach' — take a position and state what evidence would change it").
5. **A non-rubber-stamp opening** — each persona starts by disclaiming approval.

### Models

The exact Venice model IDs are an **open implementation question** (§14). The
current template assumes `claude-opus-4-7`, `gpt-5.2-codex`, `deepseek-3.2`,
`qwen-3.6-27b`; these must be verified against Venice's live catalog and made
config-driven. Aim for **model diversity across seats** (different model families
disagree differently — disagreement is the signal). At least one seat (the
Adversary) should ideally be a non-Claude model for genuine cross-model independence.

---

## 5. Member response schema

Each panelist returns JSON (Venice JSON mode), validated/coerced by the engine:

```json
{
  "stance": "approve | concerns | oppose | n/a",
  "headline": "one sentence",
  "findings": [
    { "point": "short, with file:line if code", "severity": "info|low|med|high|critical", "confidence": 1-10 }
  ],
  "suggestions": ["short optional improvements"]
}
```

- `confidence` (1–10) drives the noise gate (§7).
- `severity` lets `render` keep a low-confidence finding if it's `critical`
  (cso rule: a single critical finding is surfaced regardless of confidence).
- The `code-review` panel additionally marks blocking findings (severity ≥ high)
  so the PR-review front-end can gate the merge check (§12).
- A member that errors returns a sentinel result (`stance: "n/a"`, `_error: …`)
  and the panel proceeds.

---

## 6. The chair (synthesis)

`synthesize(context, member_results) -> Synthesis`. A single model call (the
"chair") that receives the original input + **all** member results (it is the only
component that sees everything — members answered in parallel, blind to each
other, so their agreement is meaningful and un-anchored). Modeled on `autoplan`:

```json
{
  "recommendation": "the council's consensus answer / verdict",
  "confidence": 1-10,
  "consensus": ["points ≥2 panelists raised independently (high-confidence signal)"],
  "disagreements": [
    {
      "topic": "...",
      "type": "mechanical | taste | user-challenge",
      "positions": "who held what",
      "resolution": "chair's call (for mechanical/taste)",
      "escalation": { "what_we_might_miss": "...", "if_wrong_cost": "..." }   // user-challenge only
    }
  ],
  "cross_panel_themes": ["concerns appearing across multiple lenses"]
}
```

**Typed disagreement** (the highest-value steal):
- **Mechanical** — one right answer → chair resolves silently in `recommendation`.
- **Taste** — valid differences → chair recommends but surfaces it in `disagreements`.
- **User-challenge** — the panel agrees the user's *stated* direction is wrong →
  never silently resolved; emitted with the escalation framing
  (`what_we_might_miss`, `if_wrong_cost`). The user's direction is the default;
  the panel must make the case to change it.

Chair failure → `render` falls back to showing the raw panel with a "synthesis
unavailable" note.

---

## 7. Confidence noise-gate (`--rigor`)

`render` filters findings by confidence before display:

- `--rigor daily` (default): show findings with **confidence ≥ 8**; demote 5–7 to
  a collapsed "lower-confidence" section; drop < 5 — **unless** severity is
  `critical` (always shown). ("Zero noise > zero misses.")
- `--rigor deep`: show everything with **confidence ≥ 2**, flagging 2–7 as
  `TENTATIVE`.

`red-team` defaults to `deep`; everything else to `daily`. The gate affects
*presentation only* — the chair always sees the full set.

---

## 8. CLI surface

```
council ask "<question>" [--panel NAME] [--file PATH ...] [--rigor daily|deep]
                         [--format md|term] [--save] [--panels FILE]
council review <PATH | -> [--diff] [--panel code-review] [--rigor ...]
council panels                       # list councils + descriptions + seats
```

- `ask` — free-form question, optionally grounded in one or more files.
- `review` — convenience wrapper: reads a file / dir / stdin, or `--diff` (=
  `git diff`), defaults to the `code-review` panel.
- `--panel` omitted → router picks; `--save` writes a timestamped markdown to
  `~/.council/history/`.

Examples:
```bash
council ask "Postgres or SQLite for a single-user finance tracker?"   # → decision (auto)
council ask --panel red-team "Critique this deploy plan" --file plan.md
council review scripts/migrate-project.sh
council review --diff
ssh dev@vps council ask "..."                                         # over the mesh, anywhere
```

---

## 9. Config & secrets

- **`VENICE_API_KEY`** from env / `.env` (per repo convention; documented in
  `.env.example` + `requires_secrets`). Never committed.
- `panels.toml` ships with defaults; override via `~/.config/council/panels.toml`
  or `--panels`.
- Tunables with sane defaults: default panel (`decision`), router model, chair
  model, per-input byte cap (default 200 KB, head+tail truncation like the
  current script), per-call timeout, max parallelism.

---

## 10. Data flow

1. CLI parses subcommand + flags; assembles `context` (question and/or file/diff
   contents, truncated to the byte cap).
2. **Panel selection:** explicit `--panel` → else `router.pick_panel(context)` →
   else default.
3. `engine.run_panel(panel, context)`: submit one Venice call per member to a
   `ThreadPoolExecutor`; collect `MemberResult`s; per-member failure isolated.
4. `synthesize(context, results)`: one chair call → `Synthesis`.
5. `render(synthesis, results, rigor)`: synthesis + typed disagreements on top;
   per-member detail collapsible/below; noise-gated. Print (+ optional `--save`).
6. Exit 0 for `ask`/`review`. (PR-review front-end keeps its own exit-1-on-blocking.)

---

## 11. Error handling

| Failure | Behavior |
|---|---|
| A member errors / times out | Sentinel result; panel proceeds; chair notes reduced panel. |
| Router errors | Fall back to default panel. |
| Chair errors | Render raw panel + "synthesis unavailable". |
| Missing `VENICE_API_KEY` | Friendly fatal error with setup hint. |
| Empty input | Friendly error, exit 2. |
| Malformed member JSON | Best-effort coercion; if impossible, treat as errored seat. |

Bounded retry with backoff lives in `venice.py`; everything above it sees either
a result or a structured error.

---

## 12. `venice_review.py` refactor

The PR reviewer becomes a thin front-end on the engine:
- Keeps: diff fetch (from env), `code-review` panel, posting one PR comment,
  setting the check, **exit 1 when blocking findings exist**.
- Drops: its own `call_venice` / `PANEL` / fan-out / aggregation → calls
  `engine.run_panel(code_review)` + a PR-flavored `render`.
- The `code-review` panel definition moves into `panels.toml` (single source of
  truth). The existing behavior (one comment, pass/fail gate) is preserved — a
  regression test asserts it.
- **Packaging implication:** the refactored `venice_review.py` imports `council`,
  so the GitHub Action (`venice-review.yml`) must *install the package* in CI,
  not just `pip install requests`. How (a `pip install git+https://…build-ai-automation-workflow`,
  a published PyPI package, or vendoring) is an open question — see §14.

---

## 13. Testing

- **Unit tests against a mocked Venice client** (no network), injected into the
  engine:
  - fan-out aggregation & per-member error isolation
  - panel-selection precedence (`--panel` > router > default)
  - router output parsing + fallback
  - synthesize parsing (typed disagreements, consensus)
  - render structure (synthesis-on-top; rigor gate keeps critical, drops low-conf)
  - config loading + `panels.toml` override + truncation
- **Refactor regression:** `venice_review.py` still yields a PR comment body and
  the right exit code via the engine (mocked client).
- **No live calls in CI.** A documented manual smoke test (`council ask "ping"`,
  `council panels`) exercises the real API on the VPS.

---

## 14. Open implementation questions (resolve during planning/build)

1. **Venice model catalog** — verify which model IDs Venice actually serves;
   the four assumed in the current template are placeholders. Pick concrete,
   diverse models per seat, and the router + chair models. (Single source of
   truth in `panels.toml` / config.)
2. **Router cost/latency** — a small/fast Venice model for `pick_panel`; confirm
   one exists and is cheap.
3. **Final persona wording** — write each seat's `system` prompt to the §4 recipe
   (a focused authoring pass, ideally itself reviewed by `council review`).
4. **Action packaging** — how `venice-review.yml` installs the `council` package
   in CI (git-install vs PyPI vs vendor). Affects the §12 refactor; pick the
   simplest that keeps the template self-bootstrapping.

---

## 15. Fast-follows & future pieces

- **Modes (next):** ambition axis (`--mode expand|hold|reduce`) for
  `decision`/`brainstorm`; finer rigor postures; context-dependent defaults
  (greenfield→expand, hotfix→hold). Designed to layer on the fixed personas.
- **Piece 2 — review beyond code:** a GitHub Action (and/or `council review`
  presets) that runs the panel on changed design docs / specs / plans.
- **Piece 3 — proactive proposing:** scheduled `council` runs (cron on the VPS)
  that scan a repo and turn high-confidence proposals into issues / draft PRs;
  needs idea-generation panels, dedup vs existing issues, and noise control —
  and benefits most from Pieces 1–2 being solid first.
