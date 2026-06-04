# council

A multi-model Venice AI council. Fan a question/artifact out to a panel of
personas — each backed by a *different* model family — then a "chair" model
synthesizes a recommendation with typed disagreements. Members answer in
parallel, blind to each other, so their agreement is meaningful.

## Install

    pipx install .            # from this repo (recommended)
    # or: pip install -e .
    cp .env.example .env      # add your VENICE_API_KEY

`council ask` / `council review` read `VENICE_API_KEY` from the environment
(or a `.env` you've sourced). `council panels` needs no key.

## Use

    council ask "Postgres or SQLite for a single-user app?"     # router auto-picks → decision
    council ask --panel red-team "Critique this plan" --file plan.md
    council review path/to/file.py
    council review --diff                                       # reviews `git diff`
    council panels                                              # list councils + seats

Flags: `--panel NAME` (skip the router), `--rigor daily|deep` (noise gate),
`--format md|term`, `--file PATH` (repeatable; `-` = stdin), `--panels FILE`.

## Panels

`code-review` · `decision` · `brainstorm` · `red-team`. Seats are spread across
model families (OpenAI / DeepSeek / xAI / Google / Claude) — different families
disagree differently, and the Adversary is always a non-Claude model for genuine
independence. Edit `council/panels.toml` (or drop a `~/.config/council/panels.toml`
override) to change personas/models or add seats.

## Rigor (the noise gate)

- `daily` (default): show findings with confidence ≥ 8; demote 5–7 to a
  collapsed section; drop < 5 — **unless** severity is `critical` (always shown).
- `deep` (default for `red-team`): show everything ≥ 2, flagged tentative.

The gate is presentation-only — the chair always sees the full set.

## Secret

`VENICE_API_KEY` from the environment / `.env`. Never commit it.

## Architecture

Pure Python (`requests` + `concurrent.futures`), no agent framework.
`engine.run_panel` fans out → `synthesize` (the chair) → `render`
(synthesis-on-top, raw panel below). The PR reviewer
(`setup/templates/venice_review.py`) is a thin front-end on the same engine.
