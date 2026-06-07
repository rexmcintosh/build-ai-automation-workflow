# Loom — session-learning pipeline (v0: shadow mode)

Distills Claude Code session transcripts into sanitized, classified learnings behind
deterministic secret gates. v0 stops at the reviewable `learnings/` artifacts; v1 adds the
live Opus weave into the wiki/memory/skills and the nightly cron.

## Run
    .venv/bin/python -m loom.cli absorb     # shadow: gate → spool → distill → learnings/
    ./loom/run-absorb.sh                     # same, with flock guard (used by cron in v1)

## Layout
- `state.json` — per-session state (pending→distilled→weaved→committed). Gitignored.
- `learnings/` — distilled, sanitized middle artifacts. Gitignored, local.
- `spool/` — immutable transcript copies (anti 90-day data loss). Gitignored.
- `quarantine/` — items a secret gate flagged. Gitignored.
- `logs/runs.log` — durable per-run log.
- `prompts/` — distill + weave prompts (learnings treated as data, not instructions).

## Secret gate
Deterministic `detect-secrets` gate at Stage 0 (raw transcript) and Stage 2.0 (learnings
artifact), fail-closed. The Base64/Hex high-entropy plugins are disabled (they false-positive on
benign IDs — Gmail/Drive IDs, hashes); credential-specific + keyword detectors stay active, and the
LLM sanitize pass is the entropy backstop. The wiki repo carries the same hook.

## Invariants
Secrets gated deterministically · learnings are data not instructions · idempotent reruns ·
single-run (flock) · re-read before weave (lint) · local-only wiki repo. See the spec:
`docs/superpowers/specs/2026-06-07-loom-session-learning-pipeline-design.md`.

## v1 (next plan)
Live weave (Haiku route → Opus write → wiki commit on `loom-shadow`→promote), `.claude`
memory/skill writes, weave-shape lint enforcement, nightly cron, Telegram run summary.
