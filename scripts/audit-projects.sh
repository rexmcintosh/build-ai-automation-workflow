#!/usr/bin/env bash
# audit-projects.sh — inventory your local projects for the compute mesh.
#
# READ-ONLY. Touches nothing. Scans each immediate subdirectory of the target
# folder (default: ~/Projects) and reports, per project:
#   · is it a git repo?            (NO  = code exists only as loose files)
#   · does it have a remote?       (no  = code lives only on this machine)
#   · is the working tree clean?   (dirty = uncommitted local changes)
#   · how many local branches are NOT on a remote (unpushed = at risk)
#   · last commit (relative time)
#   · on-disk size
#
# Why this exists: the mesh's #1 rule is "code lives in GitHub." This audit
# finds every place that rule is currently broken on this machine — projects
# with no repo, no remote, or unpushed branches are exactly what MIGRATION.md
# and migrate-project.sh need to fix. Run it on the Mac Mini before migrating.
#
# Usage:
#   scripts/audit-projects.sh [DIR]         human-readable table (default ~/Projects)
#   scripts/audit-projects.sh --tsv [DIR]   tab-separated rows, for scripting
#   scripts/audit-projects.sh --no-color [DIR]
#   scripts/audit-projects.sh --help
#
# Exit codes: 0 = ran fine.  1 = target dir missing.  2 = bad arguments.

set -uo pipefail
shopt -s nullglob

# ---- arguments --------------------------------------------------------------
SCAN_DIR=""
TSV=0
COLOR=auto

usage() {
  sed -n '2,28p' "$0" | sed 's/^#\{1,\} \{0,1\}//; s/^#$//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --tsv)      TSV=1 ;;
    --no-color) COLOR=no ;;
    -h|--help)  usage; exit 0 ;;
    --)         shift; break ;;
    -*)         echo "audit-projects: unknown option: $1" >&2; exit 2 ;;
    *)          if [ -n "$SCAN_DIR" ]; then
                  echo "audit-projects: too many arguments" >&2; exit 2
                fi
                SCAN_DIR="$1" ;;
  esac
  shift
done
[ $# -gt 0 ] && SCAN_DIR="${SCAN_DIR:-$1}"

SCAN_DIR="${SCAN_DIR:-$HOME/Projects}"

if [ ! -d "$SCAN_DIR" ]; then
  echo "audit-projects: directory not found: $SCAN_DIR" >&2
  exit 1
fi

# ---- colors (only on a terminal, never in --tsv) ----------------------------
[ "$TSV" -eq 1 ] && COLOR=no
if [ "$COLOR" = auto ]; then
  if [ -t 1 ]; then COLOR=yes; else COLOR=no; fi
fi
if [ "$COLOR" = yes ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; RST=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GRN=""; YLW=""; RST=""
fi

# ---- helpers ----------------------------------------------------------------
trunc() { # trunc <string> <maxlen>  — ASCII-safe so column widths stay aligned
  local s="$1" n="$2"
  if [ "${#s}" -gt "$n" ]; then printf '%s' "${s:0:$((n-2))}.."; else printf '%s' "$s"; fi
}

# Accumulators for the closing summary (bash 3.2 — no associative arrays).
TOTAL=0
LIST_NOGIT=""
LIST_NOREMOTE=""
LIST_UNPUSHED=""
LIST_DIRTY=""

add() { # add <listvar-name> <project-name>
  eval "$1=\"\${$1}\${$1:+, }\$2\""
}

# ---- header -----------------------------------------------------------------
if [ "$TSV" -eq 1 ]; then
  printf '# name\tis_git\thas_remote\tstate\tbranches\tunpushed\tlast_commit\tsize\tremote_url\tpath\n'
else
  printf '%s\n' "${BOLD}Project audit — $SCAN_DIR${RST}"
  printf '%s\n' "${DIM}$(date '+%Y-%m-%d %H:%M %Z') · read-only inventory${RST}"
  printf '\n'
  printf '%s  %-24s %-4s %-7s %-6s %3s %8s %-15s %6s\n' \
    ' ' 'PROJECT' 'GIT' 'REMOTE' 'STATE' 'BR' 'UNPUSHED' 'LAST COMMIT' 'SIZE'
  printf '%s  %-24s %-4s %-7s %-6s %3s %8s %-15s %6s\n' \
    ' ' '------------------------' '----' '-------' '------' '---' '--------' '---------------' '------'
fi

# ---- scan -------------------------------------------------------------------
for d in "$SCAN_DIR"/*/; do
  d="${d%/}"                       # strip trailing slash
  name="$(basename "$d")"
  TOTAL=$((TOTAL + 1))

  # is this directory its own git repo root?
  phys="$(cd "$d" 2>/dev/null && pwd -P || printf '%s' "$d")"
  top="$(git -C "$d" rev-parse --show-toplevel 2>/dev/null || true)"

  is_git="no"; nested_under=""
  if [ -n "$top" ]; then
    if [ "$top" = "$phys" ]; then
      is_git="yes"
    else
      is_git="sub"                 # inside a parent repo, not its own root
      nested_under="$(basename "$top")"
    fi
  fi

  has_remote="-"; remote_url=""; state="-"; branches="-"; unpushed="-"; last="-"

  if [ "$is_git" = "yes" ]; then
    # remote
    remote_url="$(git -C "$d" remote get-url origin 2>/dev/null || true)"
    if [ -n "$remote_url" ]; then
      has_remote="yes"
    elif [ -n "$(git -C "$d" remote 2>/dev/null)" ]; then
      has_remote="other"           # has a remote, but not named 'origin'
      remote_url="$(git -C "$d" remote get-url "$(git -C "$d" remote | head -1)" 2>/dev/null || true)"
    else
      has_remote="no"
    fi

    # clean / dirty
    if [ -n "$(git -C "$d" status --porcelain 2>/dev/null)" ]; then
      state="dirty"
    else
      state="clean"
    fi

    # branch count + unpushed (no upstream, or ahead of upstream)
    branches=0; unpushed=0
    while IFS='|' read -r br up track; do
      [ -z "$br" ] && continue
      branches=$((branches + 1))
      if [ -z "$up" ] || printf '%s' "$track" | grep -q 'ahead'; then
        unpushed=$((unpushed + 1))
      fi
    done <<EOF
$(git -C "$d" for-each-ref --format='%(refname:short)|%(upstream:short)|%(upstream:track)' refs/heads 2>/dev/null)
EOF

    last="$(git -C "$d" log -1 --format='%cr' 2>/dev/null || true)"
    [ -z "$last" ] && last="(no commits)"
  fi

  size="$(du -sh "$d" 2>/dev/null | awk '{print $1}')"
  [ -z "$size" ] && size="?"

  # is this project a migration concern?
  flag=" "; flagged=0
  if [ "$is_git" != "yes" ]; then add LIST_NOGIT "$name"; flagged=1; fi
  if [ "$is_git" = "yes" ] && [ "$has_remote" = "no" ]; then add LIST_NOREMOTE "$name"; flagged=1; fi
  if [ "$is_git" = "yes" ] && [ "$unpushed" != "-" ] && [ "$unpushed" -gt 0 ]; then add LIST_UNPUSHED "$name"; flagged=1; fi
  if [ "$state" = "dirty" ]; then add LIST_DIRTY "$name"; fi
  [ "$flagged" -eq 1 ] && flag="!"

  if [ "$TSV" -eq 1 ]; then
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$name" "$is_git" "$has_remote" "$state" "$branches" "$unpushed" "$last" "$size" "$remote_url" "$d"
    continue
  fi

  # colorize cells (escape codes are zero-width, so columns stay aligned)
  c_flag="$flag"; [ "$flag" = "!" ] && c_flag="${YLW}!${RST}"; [ "$flag" = " " ] && c_flag="${GRN}·${RST}"
  c_git="$is_git"
  case "$is_git" in
    no)  c_git="${RED}no${RST} " ;;
    sub) c_git="${YLW}sub${RST}" ;;
  esac
  c_rem="$has_remote"
  case "$has_remote" in
    no)    c_rem="${RED}no${RST}   " ;;
    other) c_rem="${YLW}other${RST}" ;;
  esac
  c_state="$state"
  [ "$state" = "dirty" ] && c_state="${YLW}dirty${RST}"
  c_unp="$unpushed"
  [ "$unpushed" != "-" ] && [ "$unpushed" != "0" ] && c_unp="${RED}${unpushed}${RST}"

  printf '%s  %-24s %b   %b %b  %3s %8b %-15s %6s\n' \
    "$c_flag" "$(trunc "$name" 24)" "$c_git" "$c_rem" "$c_state" \
    "$branches" "$c_unp" "$(trunc "$last" 15)" "$size"

  if [ "$is_git" = "sub" ] && [ -n "$nested_under" ]; then
    printf '   %s\n' "${DIM}  └ nested inside repo: $nested_under${RST}"
  fi
done

# ---- summary ----------------------------------------------------------------
[ "$TSV" -eq 1 ] && exit 0

printf '\n'
printf '%s\n' "${BOLD}Summary${RST} — $TOTAL project(s) in $SCAN_DIR"

print_bucket() { # print_bucket <emoji-label> <list> <fix-hint>
  local label="$1" list="$2" hint="$3"
  if [ -n "$list" ]; then
    printf '  %s%s%s\n' "$YLW" "$label" "$RST"
    printf '      %s\n' "$list"
    printf '      %s%s%s\n' "$DIM" "$hint" "$RST"
  fi
}

if [ -z "$LIST_NOGIT$LIST_NOREMOTE$LIST_UNPUSHED$LIST_DIRTY" ]; then
  printf '  %sAll projects are git repos with remotes and nothing unpushed. Mesh-ready.%s\n' "$GRN" "$RST"
else
  print_bucket "Not a git repo:"        "$LIST_NOGIT"    "→ migrate-project.sh will 'git init', create a GitHub remote, and push."
  print_bucket "No remote (local only):" "$LIST_NOREMOTE" "→ migrate-project.sh will create the GitHub remote and push all branches."
  print_bucket "Has unpushed branches:"  "$LIST_UNPUSHED" "→ push them; until you do, that work lives only on this machine."
  print_bucket "Dirty (uncommitted):"    "$LIST_DIRTY"    "→ commit or stash before migrating, so nothing is left behind."
  printf '\n'
  printf '  %sNext:%s feed this into migration — %sscripts/audit-projects.sh --tsv | ...%s — see docs/MIGRATION.md\n' \
    "$BOLD" "$RST" "$DIM" "$RST"
fi
