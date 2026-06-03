# Migration — getting projects off the Mini and into the mesh

> **Where this fits:** The audit ([`../scripts/audit-projects.sh`](../scripts/audit-projects.sh))
> found projects whose code **lives only on the Mini** — not a git repo, no
> remote, or branches never pushed. That's exactly the risk
> [ARCHITECTURE.md](ARCHITECTURE.md)'s "code in GitHub, always" rule exists to
> remove. Migration fixes it, one project at a time.

[`../scripts/migrate-project.sh`](../scripts/migrate-project.sh) does the work in
two phases:

- **Phase A (today, host-independent):** ensure the project is a git repo →
  ensure a GitHub remote exists (`gh repo create --private` if missing) → push
  **all** branches and tags. This alone removes the data-loss risk.
- **Phase B (after the VPS exists):** clone the repo onto the host at
  `~/projects/<name>` and start a `tmux` session. The VPS gets its copy **by
  cloning from GitHub** — which is *why* Phase A comes first.

---

## Prerequisites

- **GitHub CLI authenticated on the Mini:** `gh auth status` should show you
  logged in. If not: `gh auth login`.
- For **Phase B** later: the host (VPS) must be reachable over Tailscale **and**
  authenticated to GitHub itself (`gh auth login` on the VPS, or an SSH deploy
  key) so it can clone your private repos.

---

## Migrate one project

Always preview first with `--dry-run` (it changes nothing):

```bash
scripts/migrate-project.sh --dry-run ~/Projects/some-project
```

Then do it for real:

```bash
scripts/migrate-project.sh ~/Projects/some-project
```

What happens:
1. If it isn't a git repo, the script `git init`s it, adds a minimal safety
   `.gitignore` (so `.env`, `node_modules`, etc. aren't committed), and makes an
   initial commit (after showing you the file count and asking).
2. If there's no GitHub remote, it creates a **private** repo named after the
   folder and wires it as `origin` (after asking).
3. It pushes every branch and every tag.

Run from inside a project with no path argument and it migrates the current
directory.

---

## Safety features

- **Private by default.** Repos are created private; pass `--public` to override.
- **Secret backstop.** When initializing a new repo, it scans staged files for
  things that look like keys/secrets (`.env`, `*.pem`, `*.key`, `id_rsa`, …) and
  won't commit them silently. In `--yes` mode it *refuses* rather than risk it.
- **Uncommitted changes are never touched.** A dirty working tree is left exactly
  as-is; only committed branches are pushed. The script tells you if it skipped
  uncommitted work.
- **No force-push, ever.** It only adds; it never rewrites remote history.
- **Idempotent.** Re-running a migrated project just re-pushes (a no-op if
  nothing changed).

---

## Migrate the at-risk projects in a batch

The audit's `--tsv` output feeds straight into migration. This selects every
project that is **not a git repo**, **has no remote**, or **has unpushed
branches**, and migrates each:

```bash
scripts/audit-projects.sh --tsv \
| awk -F'\t' 'NR>1 && ($2!="yes" || $3=="no" || ($6 ~ /^[0-9]+$/ && $6+0>0)) {print $10}' \
| while read -r dir; do
    scripts/migrate-project.sh --dry-run "$dir"    # drop --dry-run once you trust it
  done
```

Recommended approach:
1. Run the loop **with `--dry-run`** first and read what it plans to do.
2. Run a couple of projects **interactively** (no `--yes`) so you see the
   confirmations.
3. Only then consider `--yes` for the long tail — and never `--yes` on a project
   you haven't reviewed for stray secrets.

> TSV columns (tab-separated): `1 name · 2 is_git · 3 has_remote · 4 state ·
> 5 branches · 6 unpushed · 7 last_commit · 8 size · 9 remote_url · 10 path`.

---

## Phase B — clone onto the VPS (after provisioning)

Once the VPS is up, on the mesh, and authenticated to GitHub, add `--to-host`:

```bash
scripts/migrate-project.sh --to-host vps ~/Projects/some-project
```

This runs Phase A as usual, then on the VPS:
- clones the repo to `~/projects/<name>` (via `gh repo clone`, falling back to
  `git clone`),
- starts a detached `tmux` session named `<name>`.

Attach from any device:
```bash
ssh vps -t "tmux attach -t <name>"
```

Use `--remote-dir <dir>` to change the remote projects directory (default
`projects` → `~/projects`).

> **Why Phase B is separate and later:** the VPS doesn't exist yet, and it can
> only clone what's already on GitHub. Do Phase A for everything now; come back
> and run `--to-host vps` per project once the server is provisioned
> (`../setup/PLAYBOOK.md` Phases 1–3).

---

## Verify

```bash
# the repo now exists on GitHub:
gh repo view <your-username>/<name> --web

# all local branches are on the remote (no "ahead" / missing branches):
scripts/audit-projects.sh ~/Projects | grep <name>
```

A migrated project should show `git=yes`, `remote=yes`, `unpushed=0` in a
fresh audit.

---

## Glossary (additions)

- **origin** — the conventional name of a repo's primary remote (here, GitHub).
- **`gh repo create`** — GitHub CLI command that makes a new repo and (with
  `--source . --remote origin`) wires your local folder to it.
- **detached tmux session** — a `tmux` session started in the background
  (`new-session -d`) that keeps running on the host until you attach to it.
