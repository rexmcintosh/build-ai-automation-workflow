#!/usr/bin/env bash
# Loom nightly runner: single-run guard + venv; runs `absorb --live`, then sends a
# scrubbed Telegram run summary (success OR failure). Mirrors the bebop pattern.
set -uo pipefail
REPO="/home/dev/projects/build-ai-automation-workflow"
LOCK="$REPO/loom/.run.lock"
LOG="$REPO/loom/logs/runs.log"
CHAT_ID="7735693897"
mkdir -p "$REPO/loom/logs"

# Load VENICE_API_KEY etc. for any venice-backed path (absorb is claude, but harmless).
[ -f /home/dev/.env ] && set -a && . /home/dev/.env && set +a

exec 9>"$LOCK"
if ! flock -n 9; then echo "[$(date -Iseconds)] another run in progress; skipping" >>"$LOG"; exit 0; fi

TS="$(date -Iseconds)"
OUT="$("$REPO/.venv/bin/python" -m loom.cli absorb --live 2>>"$LOG.err")"; RC=$?
echo "[$TS] rc=$RC $OUT" >>"$LOG"

# Build the Telegram message (scrubbed) from the JSON summary; fall back on failure text.
MSG="$("$REPO/.venv/bin/python" - "$RC" "$OUT" <<'PY' 2>/dev/null
import sys, json
from loom.summary import scrub
rc, out = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""
try:
    c = json.loads(out)
    line = "🧵 Loom run " + " ".join(f"{k}={v}" for k, v in c.items())
except Exception:
    line = f"⚠️ Loom absorb failed (rc={rc}). Check loom/logs/."
print(scrub(line))
PY
)"
[ -z "$MSG" ] && MSG="⚠️ Loom absorb (rc=$RC). Check loom/logs/."

PROMPT="Send a Telegram message to chat_id ${CHAT_ID} with text: ${MSG} Output only SENT or FAILED."
claude -p "$PROMPT" \
  --model haiku --allowedTools mcp__plugin_telegram_telegram__reply \
  --dangerously-skip-permissions --output-format text >/dev/null 2>&1 || true

exit $RC
