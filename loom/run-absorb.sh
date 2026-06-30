#!/usr/bin/env bash
# Loom nightly runner: single-run guard + venv; runs `absorb --live`, then sends a
# scrubbed Telegram run summary (success OR failure). Mirrors the bebop pattern.
#
# Runs loom CODE from a DEDICATED clone pinned to `main` (RUNTIME, provisioned by
# setup-runtime.sh), NOT the shared dev checkout — interactive sessions flip the shared
# repo's working tree between branches, and a flip mid-run once deleted a loom prompt out
# from under a live run. RUNTIME is never flipped. Loom DATA + logs stay in the shared
# repo (DATA_REPO): cli.py hardcodes that loom/ dir and those files are gitignored, so
# branch flips never disturb them. Install this script's path from RUNTIME in cron.
set -uo pipefail

# RUNTIME = this script's clone (pinned to main). DATA_REPO = shared repo (state/ledger/logs).
RUNTIME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_REPO="/home/dev/projects/build-ai-automation-workflow"
PY="$RUNTIME/.venv/bin/python"
# loom is not a declared package (the editable install maps only `council`), so bind
# `import loom`/`import council` to the runtime clone explicitly — never via CWD, which
# under cron is /home/dev. Data paths stay in DATA_REPO via cli.py's hardcoded constants.
export PYTHONPATH="$RUNTIME"
LOCK="$DATA_REPO/loom/.run.lock"
LOG="$DATA_REPO/loom/logs/runs.log"
CHAT_ID="7735693897"
mkdir -p "$DATA_REPO/loom/logs"

# Load VENICE_API_KEY etc. for any venice-backed path (absorb is claude, but harmless).
[ -f /home/dev/.env ] && set -a && . /home/dev/.env && set +a

exec 9>"$LOCK"
if ! flock -n 9; then echo "[$(date -Iseconds)] another run in progress; skipping" >>"$LOG"; exit 0; fi

# Under the lock (so no concurrent run resets mid-flight), pin RUNTIME to the latest merged
# main. Failure to sync is non-fatal — run the existing pinned (safe, never-flipped) checkout
# rather than skip the nightly. NOTE: this refreshes CODE only, not the venv — re-run
# setup-runtime.sh after any dependency change (loom's deps are just requests + PyYAML).
if ! { git -C "$RUNTIME" fetch --quiet origin main && git -C "$RUNTIME" reset --hard --quiet origin/main; }; then
  echo "[$(date -Iseconds)] WARN: could not sync $RUNTIME to origin/main; running existing checkout" >>"$LOG"
fi

TS="$(date -Iseconds)"
OUT="$("$PY" -m loom.cli absorb --live 2>>"$LOG.err")"; RC=$?
echo "[$TS] rc=$RC $OUT" >>"$LOG"

# Build the Telegram message (scrubbed) from the JSON summary; fall back on failure text.
MSG="$("$PY" - "$RC" "$OUT" <<'PY' 2>/dev/null
import sys, json
from loom.summary import format_run_summary, scrub
rc, out = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""
try:
    print(format_run_summary(json.loads(out)))
except Exception:
    print(scrub(f"⚠️ Loom absorb failed (rc={rc}). Check loom/logs/."))
PY
)"
[ -z "$MSG" ] && MSG="⚠️ Loom absorb (rc=$RC). Check loom/logs/."

PROMPT="Send a Telegram message to chat_id ${CHAT_ID} with text: ${MSG} Output only SENT or FAILED."
claude -p "$PROMPT" \
  --model haiku --allowedTools mcp__plugin_telegram_telegram__reply \
  --dangerously-skip-permissions --output-format text >/dev/null 2>&1 || true

exit $RC
