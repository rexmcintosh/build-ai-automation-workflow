# RESUME HERE — Council build handoff

> **Purpose:** orient a fresh Claude Code session (or a human) that has **none of
> the original chat context**. Read this, then the spec, then the plan, and you
> can pick up the build cleanly. Last updated 2026-06-03.

## You are here

We are building a **"council of agents"** — a multi-model Venice AI panel that
reviews/advises — on top of the Phase 1 Venice PR-review council
(`setup/templates/venice_review.py`). The work is split into a 3-piece roadmap;
**only Piece 1 is designed and planned so far.**

| Piece | What | Status |
|---|---|---|
| **1. Engine + on-demand CLI** | reusable council engine + a `council` command (`ask`/`review`/`panels`) | **Designed + planned — ready to BUILD** |
| 2. Review beyond code | run the panel on design docs / specs / plans | not started |
| 3. Proactive proposing | scheduled agents that file issues / draft PRs | not started |

**Branch:** `feat/council` (pushed to GitHub; the VPS clone is on it too).

**The two documents that ARE the context:**
1. **Design spec** — `docs/superpowers/specs/2026-06-03-council-engine-design.md`
   (the *what* and *why*: architecture, the 4 panels, persona recipe, the chair,
   the confidence gate, open questions).
2. **Implementation plan** — `docs/superpowers/plans/2026-06-03-council-engine.md`
   (the *how*: 12 TDD tasks, each with real test + implementation code, exact
   paths and commands).

## How to pick up the build (on the VPS)

```bash
ssh dev@vps
cd ~/projects/build-ai-automation-workflow
git checkout feat/council && git pull          # get the latest
export VENICE_API_KEY=...                       # required for Tasks 4 & 12
# start Claude Code here, then:
#   "Read docs/superpowers/plans/2026-06-03-council-engine.md and implement it
#    using the superpowers:subagent-driven-development skill, task by task."
```

Execute the plan **in order**. Tasks 0–3, 5–11 are pure unit tests (no network —
runnable anywhere). **Task 4** (choose real Venice model IDs by querying
`/models`) and **Task 12** (install + live smoke test) need `VENICE_API_KEY` and
network — that's why the build lives on the VPS.

## Decisions already made (so you don't re-litigate them)

- **Hand-rolled** (requests + concurrent.futures), **no agent framework** —
  deliberate; the spec explains why. Don't add CrewAI/LangGraph.
- **Packaged inside this repo** as an installable `council` command (not a
  separate repo). `venice_review.py` is **refactored to reuse the engine**.
- **4 fixed panels:** `code-review`, `decision`, `brainstorm`, `red-team`. Auto-
  pick router when no `--panel` given. Personas follow the **gstack recipe**
  (named identity, 3–5 laws, banned hedges, non-rubber-stamp opening) — see spec §4.
- **Output:** synthesis-on-top; a "chair" classifies disagreement as
  **mechanical / taste / user-challenge** (from gstack's `autoplan`).
- **Confidence noise-gate** (`--rigor daily|deep`): show high-confidence, demote/
  drop low — *"zero noise > zero misses."*
- **Out of scope for Piece 1 (do NOT build yet):** named modes (EXPAND/HOLD/
  REDUCE), Pieces 2 & 3, multi-round debate, web UI.

## The one thing to resolve early

**Venice's real model catalog.** The spec's model IDs
(`claude-opus-4-7`, etc.) are *assumptions*. Task 4 Step 1 queries
`https://api.venice.ai/api/v1/models` and you fill `council/panels.toml` with
verified, **diverse** IDs (different families disagree differently; ideally one
non-Claude model for the Adversary). Leave **no `REPLACE-` placeholders**.

## Working rules (the mesh discipline)

- This build now lives on the **VPS** (the canonical, always-on session). Reach
  it from any device via `ssh dev@vps` + tmux.
- **Push every commit.** Don't also edit the council on the Mini — one place at a
  time, or you create divergence. (GitHub is canonical; pull before you start.)
- When the council works, the satisfying finale: open a **draft PR** so the
  (now self-hosted) Venice council **reviews its own code**. 🪞

## Unrelated FYI (not part of this work)

A one-off backup left 11 personal repos on `wip/mini-snapshot-2026-06-03`
branches on GitHub (uncommitted Mini work, parked safely). Ignore them for the
council build; they're just sitting there if you ever want to integrate that WIP.
