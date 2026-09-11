#!/usr/bin/env bash
# Pull the Venice review council's usage artifacts out of GitHub Actions and
# merge them into this machine's ledger.
#
# Why: the merge gate's Venice calls are logged by VeniceClient._log_usage() into
# the RUNNER's ~/.local/state/venice-usage/ledger.db, which dies with the job. The
# workflow now exports those rows to a build artifact (see
# docs/ci-usage-durability-2026-09-11.md); this script is the other half.
#
# Ingest is idempotent (ext_id = gh:<repo>:<run>:<attempt>#<row>), so running this
# every night and re-running it after a failure cannot double-count spend.
#
# Usage:  tools/ci-usage/pull.sh [--days 8] [--repos FILE] [--dest DIR] [--keep]
# Needs:  gh (authenticated, `repo` scope) and the `venice-usage` console script.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DAYS=8
REPOS="$HERE/repos.txt"
DEST=""
KEEP=0
WORKFLOW="venice-review.yml"
PATTERN="venice-usage*"

while [ $# -gt 0 ]; do
  case "$1" in
    --days)   DAYS="$2"; shift 2 ;;
    --repos)  REPOS="$2"; shift 2 ;;
    --dest)   DEST="$2"; shift 2 ;;
    --keep)   KEEP=1; shift ;;
    -h|--help) sed -n '1,20p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v gh >/dev/null || { echo "error: gh is not installed" >&2; exit 2; }
command -v venice-usage >/dev/null || { echo "error: venice-usage is not on PATH" >&2; exit 2; }
[ -f "$REPOS" ] || { echo "error: no repo list at $REPOS" >&2; exit 2; }

if [ -z "$DEST" ]; then
  DEST="$(mktemp -d -t venice-ci-usage-XXXXXX)"
  [ "$KEEP" -eq 1 ] || trap 'rm -rf "$DEST"' EXIT
fi
mkdir -p "$DEST"

SINCE="$(date -u -d "-${DAYS} days" +%Y-%m-%dT%H:%M:%SZ)"
echo "pulling venice-review usage artifacts created since $SINCE into $DEST"

runs_found=0
while IFS= read -r repo; do
  case "$repo" in ''|\#*) continue ;; esac
  ids="$(gh run list --repo "$repo" --workflow "$WORKFLOW" --limit 100 \
           --json databaseId,createdAt \
           --jq "[.[] | select(.createdAt >= \"$SINCE\")] | .[].databaseId" 2>/dev/null || true)"
  [ -n "$ids" ] || { echo "  $repo: no runs in window"; continue; }
  n=0
  for id in $ids; do
    out="$DEST/${repo//\//__}/$id"
    mkdir -p "$out"
    # A run with no matching artifact (older workflow, cancelled job) is normal.
    if gh run download "$id" --repo "$repo" --pattern "$PATTERN" --dir "$out" >/dev/null 2>&1; then
      n=$((n + 1)); runs_found=$((runs_found + 1))
    else
      rmdir "$out" 2>/dev/null || true
    fi
  done
  echo "  $repo: $n run(s) with usage artifacts"
done < "$REPOS"

if [ "$runs_found" -eq 0 ]; then
  echo "nothing to ingest"
  exit 0
fi

echo "ingesting into ${VENICE_USAGE_DB:-$HOME/.local/state/venice-usage/ledger.db}"
venice-usage ingest "$DEST" --json
