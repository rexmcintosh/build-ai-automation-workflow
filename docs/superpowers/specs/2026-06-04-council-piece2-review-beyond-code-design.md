# Council Piece 2 — Review Beyond Code — Design

- **Status:** Approved design, ready for implementation planning
- **Date:** 2026-06-04
- **Scope:** Piece 2 of the council roadmap — extend the council to review design docs / specs / plans, on-demand and in CI.
- **Builds on:** Piece 1 (`docs/superpowers/specs/2026-06-03-council-engine-design.md`) — the engine, panels, CLI, and the PR-review Action are already shipped (`council` v0.1.0, tag `council-v0.1.0`, live in 17 repos).

---

## 1. Purpose & context

Piece 1 shipped a multi-model council that reviews **code** (the `code-review` panel + a PR Action) and answers free-form questions (`decision`/`brainstorm`/`red-team` panels). On-demand review of a non-code file already works (`council review plan.md` runs *some* panel over it) — but two gaps remain:

1. **No doc-aware lens.** The existing panels are tuned for code, decisions, or adversarial breaking — none reviews a *design doc / spec / plan* for the things that matter there: clarity, completeness, sound assumptions, and whether it can actually be built as written.
2. **CI reviews everything with a code lens.** The PR Action runs the `code-review` panel over the whole diff, so a spec change gets reviewed as if it were code.

Piece 2 closes both: a dedicated `spec-review` panel, path-based routing so CI sends doc changes to it, and a combined PR comment. Doc review is **advisory** — it never blocks a merge.

## 2. Goals & non-goals

**Goals**
- A `spec-review` panel optimized for "will this design survive contact with reality."
- Path-based routing (`classify_path`) + diff splitting (`split_diff_by_type`), reused by CLI and CI.
- The PR Action reviews code changes with `code-review` (gated, unchanged) **and** doc changes with `spec-review` (advisory), in **one combined comment**.
- Move PR-review orchestration into the package (`council/review.py`) so the per-repo CI script becomes a thin shim — future upgrades reach all repos by re-pinning the tag.
- CLI `review` auto-picks the panel by target path; `--panel` always overrides.

**Non-goals (out of scope for Piece 2)**
- **Piece 3** (proactive scheduled proposing — issues/draft PRs).
- Blocking/gating on doc findings (advisory only — see §6).
- Broader non-dev content panels (editorial/business). The `spec-review` panel targets software design docs; a general editorial panel is a possible fast-follow.
- A separate doc-review workflow or a second check status (we use one comment, one check — see §6).
- Auto-detecting *which* doc panel by sub-type (ADR vs plan vs README). One `spec-review` panel covers all prose/design artifacts.

## 3. Architecture

Reuse the Piece 1 engine (`run_panel` → `synthesize` → `render`) **unchanged**. Add:

```
                changed files / a path / a diff
                          │
                 routing.classify_path / split_diff_by_type
                          │
        ┌─────────────────┴─────────────────┐
     code slice                          doc slice
        │                                   │
  code-review panel                   spec-review panel      (engine.run_panel + synthesize, as today)
        │  (gated)                          │ (advisory)
        └─────────────────┬─────────────────┘
                          ▼
              one combined review comment
        (code section may block; doc section never does)
```

| Module | Responsibility | Status |
|---|---|---|
| `council/panels.toml` | add the `spec-review` panel (data) | MODIFY |
| `council/routing.py` | `classify_path`, `split_diff_by_type` | NEW |
| `council/review.py` | `run_pr_review(diff, panels, client, settings) -> (body, blocking, unavailable)` | NEW |
| `council/render.py` | `render_combined(sections)` helper (two titled sections, one body) | MODIFY |
| `council/cli.py` | `review` auto-picks panel by path when `--panel` omitted | MODIFY |
| `setup/templates/venice_review.py` (+ the 17 deployed copies) | reduce to a thin shim over `council.review.run_pr_review` | MODIFY |

## 4. The `spec-review` panel

Lives in `panels.toml` as data. Seats differentiated by **lens**, family-diverse models (chair stays `claude-opus-4-8`). Personas follow the gstack recipe (concrete identity with a number, 3–5 named laws, banned hedges, non-rubber-stamp opening).

| Seat | Lens | Model (family) |
|---|---|---|
| **Editor** | clarity, completeness, structure — is anything missing, vague, or contradictory? | `gemini-3-1-pro-preview` (Google) |
| **Domain Skeptic** | premises & assumptions — is the framing right? what's assumed but unproven? | `grok-4-3` (xAI) |
| **Implementer** | buildability — "can I build this *as written*? what's underspecified / ambiguous?" | `openai-gpt-53-codex` (OpenAI) |
| **Pre-mortem Adversary** | failure modes — "it's a year out and this design failed; how?" | `deepseek-v4-pro` (DeepSeek) |

- `description = "Review a design doc / spec / plan for clarity, soundness, and buildability."`
- `default_rigor = "daily"` (the confidence noise-gate from Piece 1 still applies — show conf ≥ 8, demote 5–7, drop < 5 unless `critical`).
- **Severity semantics for docs:** `critical` = self-contradiction or a fatal flaw the panel agrees on; `high` = a significant gap/ambiguity that will cause rework; lower = polish. Severity drives the gate only for the *code* panel (§6); for docs it is purely presentational.

## 5. Routing (`council/routing.py`)

Pure functions, no I/O, fully unit-testable.

- `classify_path(path: str) -> "doc" | "code"`
  - **doc** if the file extension is one of `.md .markdown .rst .txt .adoc`, **or** any path segment is `docs`, `spec`, `specs`, `plan`, or `plans`.
  - otherwise **code**.
- `split_diff_by_type(diff: str) -> (code_diff: str, doc_diff: str)`
  - Split a unified diff into per-file sections on `diff --git a/<p> b/<p>` boundaries; classify each file by its path; concatenate into the two buckets. Files before the first header (rare preamble) are ignored. Either bucket may be empty.

Chosen over passing a changed-file list from the workflow because it keeps the logic self-contained and needs **no YAML change in the 17 deployed repos** (the workflow already writes the full diff to `DIFF_PATH`).

## 6. CI behavior (`council/review.py` + the shim)

`run_pr_review(diff, panels, client, settings) -> (body, blocking, unavailable)`:

1. `code_diff, doc_diff = split_diff_by_type(diff)`.
2. If `code_diff` non-empty: run the `code-review` panel + chair over it → a **code section**.
3. If `doc_diff` non-empty: run the `spec-review` panel + chair over it → a **doc section**.
4. `body = render_combined([...])` — one comment, a section per non-empty slice, each with the Piece-1 synthesis-on-top + raw panel. A short header notes the doc section is advisory.
5. `blocking` = count of blocking findings **in the code section only** (existing rule: `critical`, or `high` with confidence ≥ 8). The doc section never contributes.
6. `unavailable` (fail-closed) is keyed on the **code** review only — code chair errored, or ≥ half the code panel errored. A doc-side failure is noted in the comment but **never** blocks (advisory).
7. Edge cases: docs-only PR → no code section, `blocking = 0`, check green, advisory doc comment. Code-only PR → exactly today's behavior. Empty diff → "nothing to review", exit 0.

`scripts/venice_review.py` becomes a thin shim: read env (`VENICE_API_KEY`, `GITHUB_TOKEN`, `PR_NUMBER`, `REPO`, `DIFF_PATH`), build the client, call `run_pr_review`, post the comment, and exit (1 if `blocking` or `unavailable`, else 0). The orchestration/testable logic lives in the package.

## 7. CLI changes (`council/cli.py`)

`review` currently defaults `--panel` to `code-review`. New behavior when `--panel` is **omitted**:
- `review <single-file>` → `classify_path` picks `spec-review` for a doc, else `code-review`.
- `review <dir>` / `review --diff` / `review -` (stdin) → default `code-review` (the split-and-run-both flow is a CI concern; a human can pass `--panel spec-review`).
- `--panel` always overrides. `ask` is unchanged.

## 8. Versioning & rollout

Piece 2 changes the package, so it ships as **`council` v0.2.0** with a new immutable tag `council-v0.2.0`.

- Re-pin the Action template (`setup/templates/venice-review.yml`) and the 17 deployed workflows from `@council-v0.1.0` → `@council-v0.2.0` (one line each; scriptable, mirrors the Piece-1 rollout).
- Because the per-repo script becomes a thin shim, re-copy it to the 17 repos **once** as part of this rollout; subsequent council upgrades need only a tag re-pin.
- Until a repo is bumped it stays on v0.1.0 — code-only review, no breakage.

## 9. Error handling

Inherits Piece 1's table. Additions: a doc-panel or doc-chair failure is surfaced in the comment but never affects `blocking`/`unavailable` (advisory). The code path keeps fail-closed semantics. `split_diff_by_type` on a malformed/empty diff returns empty buckets, yielding a clean "nothing to review".

## 10. Testing

All offline against the Piece-1 `FakeClient` (no network):
- `classify_path` — extensions and `docs/specs/plans` path segments, nested paths, ambiguous cases.
- `split_diff_by_type` — code-only, doc-only, mixed, empty/malformed diff.
- `panels.toml` loads with `spec-review` (4 seats, models present, no placeholders).
- `run_pr_review` — combined body has both sections; `blocking` counts code only; a docs-only PR yields `blocking = 0`; a doc-side error doesn't set `unavailable`; a code-side outage does.
- `render_combined` — sections in order, advisory note present.
- CLI `review` auto-pick — doc file → `spec-review`, code file → `code-review`, `--panel` overrides, dir/diff default to code.
- Live smoke (VPS, documented): `council review <a real spec>.md` and a mixed test PR after the v0.2.0 rollout.

## 11. Open questions

Resolved during brainstorming:
- Doc gate → **advisory only** (§6).
- Routing → **by path, one combined comment** (§5, §6).
- Panel seats → **Editor / Domain Skeptic / Implementer / Pre-mortem Adversary** (§4).
- Diff handling → **parse in-package** (no workflow YAML change) (§5).

None open.
