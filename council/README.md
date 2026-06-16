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
    council compare --task "make f handle empties" a.py b.py    # rank candidates, pick a winner
    council sweep path/to/repo                                  # repo-wide security sweep
    council panels                                              # list councils + seats

Flags: `--panel NAME` (skip the router), `--rigor daily|deep` (noise gate),
`--format md|term`, `--file PATH` (repeatable; `-` = stdin), `--panels FILE`.

## compare — waste tokens, save time

`council compare` is the *selection* half of "throw N models at it": you generate N
candidate solutions however you like, then the panel ranks them and the chair picks a
winner + says what to graft from the runners-up. The end-to-end loop for a single
self-contained prompt:

    council/scripts/parallel-attempts.sh "Write a retry decorator with backoff"

generates K candidates across K Venice models in parallel and pipes them to `compare`.
For repo-wide code building, generate candidates with `claude` / parallel git worktrees
instead, then `council compare` the results.

## sweep — autonomous security research

`council sweep <path>` walks a whole tree, fans the `red-team` panel across it chunk
by chunk, **dedups** findings, **gates** by confidence (critical always kept), sorts
worst-first, and has the chair write a phone-glanceable summary. It is deliberately
**bounded** — `--max-chunks` caps coverage and the report states how many files were
dropped, so it never silently claims to have scanned everything. It reports; it opens
nothing. `council/scripts/security-sweep.sh` is the scheduled runner (Telegram summary).

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
