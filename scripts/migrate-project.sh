#!/usr/bin/env bash
# migrate-project.sh — get a local project safely into GitHub (and, later, onto a host).
#
# Phase A (default — runs today, host-independent):
#   1. ensure the directory is a git repo (git init if not)
#   2. ensure a GitHub remote exists (gh repo create --private if missing)
#   3. push ALL branches and tags
# Phase B (optional — once the VPS exists): with --to-host, clone the repo onto a
#   remote host at ~/projects/<name> and start a tmux session.
#
# This is what removes the "code lives only on the Mini" risk the audit found.
#
# Usage:
#   scripts/migrate-project.sh [options] [PROJECT_DIR]      (default PROJECT_DIR = .)
#
# Options:
#   --public           create the GitHub repo public (default: PRIVATE)
#   --to-host U@HOST   also clone onto host (e.g. dev@vps) + tmux session (Phase B)
#   --remote-dir DIR   remote projects dir for --to-host (default: projects -> ~/projects)
#   --yes              don't ask for confirmation (batch use — review first!)
#   --dry-run          print what would happen; change nothing, push nothing
#   -h, --help
#
# Safe by design: private repos by default, refuses to commit likely-secret files
# in --yes mode, never force-pushes, and leaves uncommitted changes untouched.

set -uo pipefail

# ---- options ----------------------------------------------------------------
PUBLIC=0
TO_HOST=""
REMOTE_DIR="projects"
ASSUME_YES=0
DRY=0
PROJECT_DIR=""

usage() { sed -n '2,28p' "$0" | sed 's/^#\{1,\} \{0,1\}//; s/^#$//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --public)     PUBLIC=1 ;;
    --to-host)    TO_HOST="${2:?--to-host needs a host}"; shift ;;
    --remote-dir) REMOTE_DIR="${2:?--remote-dir needs a dir}"; shift ;;
    --yes|-y)     ASSUME_YES=1 ;;
    --dry-run|-n) DRY=1 ;;
    -h|--help)    usage; exit 0 ;;
    --)           shift; break ;;
    -*)           echo "migrate-project: unknown option: $1" >&2; exit 2 ;;
    *)            [ -n "$PROJECT_DIR" ] && { echo "too many arguments" >&2; exit 2; }
                  PROJECT_DIR="$1" ;;
  esac
  shift
done
[ $# -gt 0 ] && PROJECT_DIR="${PROJECT_DIR:-$1}"
PROJECT_DIR="${PROJECT_DIR:-.}"

# ---- pretty output ----------------------------------------------------------
if [ -t 1 ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; RST=$'\033[0m'
else BOLD=""; DIM=""; RED=""; GRN=""; YLW=""; RST=""; fi
step() { printf '%s==>%s %s\n' "$BOLD" "$RST" "$*"; }
ok()   { printf '%s ✓ %s%s\n'  "$GRN" "$*" "$RST"; }
warn() { printf '%s ! %s%s\n'  "$YLW" "$*" "$RST"; }
die()  { printf '%s ✗ %s%s\n'  "$RED" "$*" "$RST" >&2; exit 1; }

run() { # run <cmd...> — execute, or just print in --dry-run
  if [ "$DRY" = 1 ]; then printf '   %swould run:%s %s\n' "$DIM" "$RST" "$*"; else "$@"; fi
}
confirm() { # confirm "question"  — auto-yes in --yes/--dry-run
  { [ "$ASSUME_YES" = 1 ] || [ "$DRY" = 1 ]; } && return 0
  printf '%s %s[y/N]%s ' "$1" "$DIM" "$RST"
  local ans=""; read -r ans </dev/tty 2>/dev/null || ans=""
  case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}
sanitize() { printf '%s' "$1" | tr ' ' '-' | tr -cd '[:alnum:]._-'; }

# ---- preflight --------------------------------------------------------------
[ -d "$PROJECT_DIR" ] || die "not a directory: $PROJECT_DIR"
cd "$PROJECT_DIR" || die "cannot cd into $PROJECT_DIR"
ABS="$(pwd -P)"
RAWNAME="$(basename "$ABS")"
NAME="$(sanitize "$RAWNAME")"
[ -n "$NAME" ] || die "could not derive a repo name from '$RAWNAME'"

command -v git >/dev/null || die "git not found"
command -v gh  >/dev/null || die "gh (GitHub CLI) not found — install it first"
gh auth status >/dev/null 2>&1 || die "not logged in to GitHub — run 'gh auth login' first"
OWNER="$(gh api user -q .login 2>/dev/null || true)"
[ -n "$OWNER" ] || die "could not determine your GitHub username from gh"

printf '%sMigrating%s %s  →  %s/%s  %s(%s)%s\n\n' \
  "$BOLD" "$RST" "$RAWNAME" "$OWNER" "$NAME" "$DIM" \
  "$([ "$DRY" = 1 ] && echo DRY-RUN || echo live)" "$RST"

# ---- step 1: ensure it's a git repo ----------------------------------------
TOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$TOP" ] && [ "$TOP" = "$ABS" ]; then
  ok "Already a git repo"
else
  step "Not a git repo — initializing"
  # bail out early on an empty directory (nothing to migrate)
  if [ -z "$(ls -A . 2>/dev/null)" ]; then
    die "directory is empty — nothing to migrate"
  fi
  run git init -b main
  if [ ! -f .gitignore ]; then
    step "No .gitignore — adding a minimal safety one (.env, node_modules, etc.)"
    if [ "$DRY" = 0 ]; then
      cat > .gitignore <<'GI'
.DS_Store
.env
.env.*
*.log
node_modules/
__pycache__/
.venv/
venv/
dist/
build/
GI
    else printf '   %swould write%s a default .gitignore\n' "$DIM" "$RST"; fi
  fi
  run git add -A
  # secret backstop: warn on staged files that look like keys/secrets
  if [ "$DRY" = 0 ]; then
    HITS="$(git diff --cached --name-only 2>/dev/null \
      | grep -Ei '(^|/)(\.env(\..*)?|.*\.pem|.*\.key|.*\.p12|.*\.pfx|id_rsa|id_ed25519|.*secret.*|.*credential.*)$' || true)"
    if [ -n "$HITS" ]; then
      warn "These staged files look like secrets:"
      printf '%s\n' "$HITS" | sed 's/^/     /'
      [ "$ASSUME_YES" = 1 ] && die "refusing to commit likely secrets in --yes mode; add them to .gitignore"
      confirm "Commit these anyway?" || die "aborted — add them to .gitignore and re-run"
    fi
    git diff --cached --quiet && die "nothing staged to commit"
    COUNT="$(git diff --cached --name-only | wc -l | tr -d ' ')"
    confirm "Create initial commit of $COUNT file(s)?" || die "aborted"
  fi
  run git commit -m "Initial commit (migrated into the compute mesh)"
fi

# ---- step 2: ensure a GitHub remote ----------------------------------------
ORIGIN_URL="$(git remote get-url origin 2>/dev/null || true)"
if [ -n "$ORIGIN_URL" ]; then
  ok "Remote already set: $ORIGIN_URL"
elif gh repo view "$OWNER/$NAME" >/dev/null 2>&1; then
  step "GitHub repo $OWNER/$NAME already exists — adding it as 'origin'"
  run git remote add origin "https://github.com/$OWNER/$NAME.git"
else
  VIS="--private"; LABEL="private"
  [ "$PUBLIC" = 1 ] && { VIS="--public"; LABEL="public"; }
  step "Creating GitHub repo $OWNER/$NAME ($LABEL)"
  confirm "Create $LABEL GitHub repo $OWNER/$NAME?" || die "aborted"
  run gh repo create "$NAME" $VIS --source "." --remote origin
fi

# ---- step 3: push all branches + tags --------------------------------------
step "Pushing all branches and tags"
CUR="$(git symbolic-ref --short HEAD 2>/dev/null || echo main)"
run git push -u origin "$CUR"
run git push origin --all
run git push origin --tags

if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  warn "Working tree has uncommitted changes — NOT pushed (left safely in place)."
  warn "Commit them and re-run to include them."
fi

# ---- phase B (optional): clone onto a host + tmux --------------------------
if [ -n "$TO_HOST" ]; then
  step "Phase B — cloning onto host '$TO_HOST' at ~/$REMOTE_DIR/$NAME"
  case "$TO_HOST" in
    *@*) : ;;
    *) warn "--to-host '$TO_HOST' has no user@ — SSH will use your local username, which likely doesn't exist on the host. Use e.g. dev@$TO_HOST." ;;
  esac
  RURL="$(git remote get-url origin 2>/dev/null || echo "https://github.com/$OWNER/$NAME.git")"
  # Requires: $TO_HOST reachable (Tailscale) and git authed to GitHub there
  # (gh auth login + gh auth setup-git, so HTTPS clones of private repos work).
  # Clone from the real origin URL so a folder name != repo name still works.
  if [ "$DRY" = 1 ]; then
    printf '   %swould clone%s %s -> %s:~/%s/%s and start tmux session %s\n' \
      "$DIM" "$RST" "$RURL" "$TO_HOST" "$REMOTE_DIR" "$NAME" "$NAME"
  elif ssh -n "$TO_HOST" "mkdir -p ~/$REMOTE_DIR && cd ~/$REMOTE_DIR && { [ -d '$NAME/.git' ] || git clone '$RURL' '$NAME'; } && cd '$NAME' && git fetch --all --tags --prune"; then
    ssh -n "$TO_HOST" "tmux has-session -t '$NAME' 2>/dev/null || tmux new-session -d -s '$NAME' -c ~/$REMOTE_DIR/'$NAME'"
    ok "On $TO_HOST: ~/$REMOTE_DIR/$NAME  (tmux session '$NAME')"
    printf '   attach with:  %sssh %s -t "tmux attach -t %s"%s\n' "$DIM" "$TO_HOST" "$NAME" "$RST"
  else
    warn "Phase B failed — could not clone onto '$TO_HOST'. Check it's reachable and that you used user@host (e.g. dev@vps)."
  fi
fi

# ---- done -------------------------------------------------------------------
if [ "$DRY" = 1 ]; then
  printf '\n%sdry-run complete — nothing was changed.%s\n' "$DIM" "$RST"
else
  # report the ACTUAL remote — the GitHub repo name may differ from the folder
  WEB="$(git remote get-url origin 2>/dev/null || echo "https://github.com/$OWNER/$NAME.git")"
  case "$WEB" in git@github.com:*) WEB="https://github.com/${WEB#git@github.com:}" ;; esac
  WEB="${WEB%.git}"
  ok "Done: $WEB"
  printf '   GitHub: %s%s%s\n' "$DIM" "$WEB" "$RST"
fi
