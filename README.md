# build-ai-automation-workflow

Home of the VPS + Venice AI multi-agent PR review setup, plus the automation workflow built on top of it.

The dev infrastructure model: **Claude Code runs on a Hetzner VPS → opens PRs → a Venice AI council critiques every PR → you merge → CI deploys to the same VPS.** See `setup/PLAYBOOK.md` for the full architecture, provisioning steps, and day-to-day loop.

## Layout

- `setup/PLAYBOOK.md` — implementation playbook (start here)
- `setup/bootstrap-vps.sh` — one-shot Ubuntu 24.04 VPS provisioning
- `setup/templates/` — files to drop into this repo (and any future project):
  - `CLAUDE.md` — agent conventions (branch/commit/PR discipline)
  - `settings.json` — Claude Code permission allowlist
  - `venice-review.yml` — GitHub Action that runs the review council
  - `venice_review.py` — the council itself (4 specialist personas, fan-out + aggregate)
  - `deploy.yml` — GitHub Action that ships merged PRs to the VPS
  - `upload-shortcut.md` — iPhone screenshot-paste workaround
