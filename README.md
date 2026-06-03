# build-ai-automation-workflow

Home of the VPS + Venice AI multi-agent PR review setup, plus the automation workflow built on top of it.

The dev infrastructure model: **Claude Code runs on a Hetzner VPS → opens PRs → a Venice AI council critiques every PR → you merge → CI deploys to the same VPS.** See `setup/PLAYBOOK.md` for the full architecture, provisioning steps, and day-to-day loop.

## Two phases

- **Phase 1 — VPS + Venice review** (`setup/`): stand up a Hetzner VPS where Claude Code writes, opens PRs, and a Venice AI council reviews each one before you merge + deploy. Start at [`setup/PLAYBOOK.md`](setup/PLAYBOOK.md).
- **Phase 2 — Personal compute mesh** (`docs/`): wrap that VPS in a four-node mesh (VPS + Mac Mini + MacBook + iPhone) so work is reachable from any device, even with the Mini off. Start at [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## docs/ — Phase 2 (the mesh)

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — design of record: the rule, the ASCII diagram, where each kind of work lives
- [`docs/TAILSCALE.md`](docs/TAILSCALE.md) — private mesh: install on all four nodes, SSH ACL/grants, verify
- [`docs/MAC-MINI-SETUP.md`](docs/MAC-MINI-SETUP.md) — never-sleep, Remote Login, Time Machine + Backblaze, Tailscale-at-boot
- [`docs/MIGRATION.md`](docs/MIGRATION.md) — get local projects into GitHub, then clone onto the host
- [`docs/DAILY-LOOP.md`](docs/DAILY-LOOP.md) — the operating manual (start / suspend / push / resume anywhere)
- `scripts/` — [`audit-projects.sh`](scripts/audit-projects.sh) (inventory) · [`migrate-project.sh`](scripts/migrate-project.sh) (migrate)

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
