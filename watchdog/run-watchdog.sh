#!/usr/bin/env bash
# Mesh watchdog — autonomous SRE for the automation system's own moving parts.
#
# Cheap-first by design: a pure-Python pre-check (watchdog/run.py) collects signals
# and triages them with flap suppression. ONLY when something fires does it spend
# tokens on a read-only investigator agent that diagnoses + proposes a fix to
# Telegram. The watchdog never fixes production — it puts a fix on a silver platter.
#
# Usage: run-watchdog.sh [--dry-run]
#   --dry-run : run the pre-check and print what WOULD escalate; never calls the agent.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="$(cd "$DIR/.." && pwd)"
PROMPT_FILE="$DIR/prompts/investigate.md"
LOG_DIR="$DIR/logs"
LOG="$LOG_DIR/runs.log"
CHAT_ID="7735693897"
MODEL="haiku"
CLAUDE_BIN="$(command -v claude || echo /usr/bin/claude)"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

mkdir -p "$LOG_DIR"
TS="$(date -Iseconds)"
NOW_HUMAN="$(TZ=Europe/Lisbon date '+%A %Y-%m-%d %H:%M %Z')"

# --- pre-check: collect + triage (no tokens spent here) ---
OUT="$(WATCHDOG_BASE="$BASE" python3 -m watchdog.run 2>>"$LOG.err")"
JSON_LINE="$(printf '%s\n' "$OUT" | grep '^WATCHDOG_JSON:' | head -1 | sed 's/^WATCHDOG_JSON://')"
REPORT="$(printf '%s\n' "$OUT" | grep -v '^WATCHDOG_JSON:')"
ESCALATE="$(printf '%s' "$JSON_LINE" | python3 -c "import json,sys
try: print('1' if json.load(sys.stdin).get('escalate') else '0')
except Exception: print('0')" 2>/dev/null)"

if [ "$ESCALATE" != "1" ]; then
  echo "[$TS] rc=0 escalate=0 :: $(printf '%s' "$REPORT" | head -1)" >> "$LOG"
  echo "ok (no escalation): $(printf '%s' "$REPORT" | head -1)"
  exit 0
fi

if [ "$DRY_RUN" = "1" ]; then
  echo "[$TS] DRY-RUN escalate=1" >> "$LOG"
  echo "WOULD ESCALATE:"; printf '%s\n' "$REPORT"
  exit 0
fi

# --- escalation: read-only investigator agent -> Telegram ---
PROMPT="$(cat "$PROMPT_FILE")"
PROMPT="${PROMPT//\{\{NOW\}\}/$NOW_HUMAN}"
PROMPT="${PROMPT//\{\{REPORT\}\}/$REPORT}"
PROMPT="${PROMPT//\{\{BASE\}\}/$BASE}"
PROMPT="${PROMPT//\{\{CHAT_ID\}\}/$CHAT_ID}"

# Read-only by construction: Read (logs) + Telegram send. No Bash/Write/Edit.
RESULT=$("$CLAUDE_BIN" -p "$PROMPT" \
  --model "$MODEL" \
  --allowedTools Read mcp__plugin_telegram_telegram__reply \
  --dangerously-skip-permissions \
  --output-format json 2>>"$LOG.err" \
  | python3 -c "import json,sys
try: print(json.load(sys.stdin).get('result','').strip())
except Exception as e: print('PARSE_ERROR:'+str(e))" 2>/dev/null)
RC=$?

echo "[$TS] rc=$RC escalate=1 result=\"${RESULT:0:80}\"" >> "$LOG"
if [ $RC -eq 0 ] && printf '%s' "$RESULT" | grep -q "SENT"; then
  echo "escalated + notified."
  exit 0
fi
echo "FAILED to deliver watchdog alert (rc=$RC): $RESULT" >&2
exit 1
