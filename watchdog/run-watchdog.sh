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

# Cron's PATH has no ~/.local/bin, where the claude CLI lives since the 2026-07-25
# installer migration. Without this every escalation dies rc=127 (2026-08-08: the
# alert about bebop's own outage failed to send). Same fix as loom's runner.
export PATH="$HOME/.local/bin:$PATH"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="$(cd "$DIR/.." && pwd)"
PROMPT_FILE="$DIR/prompts/investigate.md"
LOG_DIR="$DIR/logs"
LOG="$LOG_DIR/runs.log"
CHAT_ID="7735693897"
MODEL="haiku"
CLAUDE_BIN="$(command -v claude || echo /usr/bin/claude)"
# Where the read-only Supabase key lives (for Layer-2 row-count checks). Sourced ONLY
# for the pre-check subshell below, so the investigator agent never inherits it.
ENV_FILE="${WATCHDOG_ENV_FILE:-/home/dev/projects/splash_poller/.env}"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

mkdir -p "$LOG_DIR"
TS="$(date -Iseconds)"
NOW_HUMAN="$(TZ=Europe/Lisbon date '+%A %Y-%m-%d %H:%M %Z')"

# --- pre-check: collect + triage (no tokens spent here) ---
# PYTHONPATH="$BASE" so `python3 -m watchdog.run` resolves the package no matter the
# cwd (cron runs from $HOME). Secrets sourced in a subshell so they stay out of the
# agent's environment further down.
OUT="$( set -a; [ -f "$ENV_FILE" ] && . "$ENV_FILE"; set +a
        WATCHDOG_BASE="$BASE" PYTHONPATH="$BASE" python3 -m watchdog.run 2>>"$LOG.err" )"
JSON_LINE="$(printf '%s\n' "$OUT" | grep '^WATCHDOG_JSON:' | head -1 | sed 's/^WATCHDOG_JSON://')"
METRICS_LINE="$(printf '%s\n' "$OUT" | grep '^WATCHDOG_METRICS:' | head -1 | sed 's/^WATCHDOG_METRICS://')"
# Report excludes the machine lines (JSON + metrics) — the investigator sees only findings.
REPORT="$(printf '%s\n' "$OUT" | grep -vE '^WATCHDOG_(JSON|METRICS):')"
[ -n "$METRICS_LINE" ] && echo "[$TS] metrics:$METRICS_LINE" >> "$LOG"

# Fail CLOSED: if the pre-check produced no JSON line it crashed (import error, bad
# signal). A silent watchdog is worse than a noisy one — escalate a meta-alert so the
# break itself becomes visible, rather than masquerading as "all ok".
if [ -z "$JSON_LINE" ]; then
  REPORT="[CRIT] watchdog: pre-check failed to run (no result emitted). See $LOG.err."
  ESCALATE="1"
else
  ESCALATE="$(printf '%s' "$JSON_LINE" | python3 -c "import json,sys
try: print('1' if json.load(sys.stdin).get('escalate') else '0')
except Exception: print('0')" 2>/dev/null)"
fi

if [ "$ESCALATE" != "1" ]; then
  echo "[$TS] rc=0 escalate=0 :: $(printf '%s' "$REPORT" | head -1)" >> "$LOG"
  echo "ok (no escalation): $(printf '%s' "$REPORT" | head -1)"
  exit 0
fi

# --- build the investigator briefing (shown in full by --dry-run) ---
# File-freshness table: the investigator is read-only with no shell, so it can't
# ask how old a file is. Collect mtimes for every authorized log root here and
# inject them, so stale evidence is visible AS stale (2026-08-16: a runs.log.err
# untouched for 2 weeks got blamed as the live cause of a disk alert).
# Newest-first, capped: splash_poller/logs alone holds dozens of dead poller-*.log
# files, and the investigator runs on a small model — old tail stays out.
ALL_FILES="$(find "$BASE/bebop/logs" "$BASE/loom/logs" "$BASE/watchdog/logs" \
                  /home/dev/projects/splash_poller/logs \
                  -maxdepth 1 -type f \
                  -printf '%T@ %TY-%Tm-%Td %TH:%TM  %9s  %p\n' 2>/dev/null | sort -rn)"
FILES="$(printf '%s\n' "$ALL_FILES" | head -40 | cut -d' ' -f2-)"
N_FILES="$(printf '%s\n' "$ALL_FILES" | grep -c .)"
[ "$N_FILES" -gt 40 ] && FILES="$FILES
(+ $((N_FILES - 40)) older files omitted)"
PROMPT="$(cat "$PROMPT_FILE")"
PROMPT="${PROMPT//\{\{NOW\}\}/$NOW_HUMAN}"
PROMPT="${PROMPT//\{\{REPORT\}\}/$REPORT}"
PROMPT="${PROMPT//\{\{FILES\}\}/$FILES}"
PROMPT="${PROMPT//\{\{BASE\}\}/$BASE}"
PROMPT="${PROMPT//\{\{CHAT_ID\}\}/$CHAT_ID}"

if [ "$DRY_RUN" = "1" ]; then
  echo "[$TS] DRY-RUN escalate=1" >> "$LOG"
  echo "WOULD ESCALATE — investigator briefing:"; printf '%s\n' "$PROMPT"
  exit 0
fi

# --- escalation: read-only investigator agent -> Telegram ---

# Read-only by construction: Read (logs) only. No Bash/Write/Edit, no send tools —
# the investigator COMPOSES the alert; delivery happens below via raw Bot API
# (bin/tg-send), so the telegram plugin/MCP is not needed.
RESULT=$("$CLAUDE_BIN" -p "$PROMPT" \
  --model "$MODEL" \
  --allowedTools Read \
  --dangerously-skip-permissions \
  --output-format json 2>>"$LOG.err" \
  | python3 -c "import json,sys
try: print(json.load(sys.stdin).get('result','').strip())
except Exception as e: print('PARSE_ERROR:'+str(e))" 2>/dev/null)
RC=$?

TG_SEND="$BASE/bin/tg-send"
# runs.log entries must stay ONE line; RESULT is multiline alert text — flatten.
RESULT_1LINE="$(printf '%s' "$RESULT" | tr '\n' ' ')"
if [ $RC -eq 0 ] && [ -n "$RESULT" ] && ! printf '%s' "$RESULT" | grep -q '^FAILED'; then
  if printf '%s' "$RESULT" | "$TG_SEND" "$CHAT_ID" -; then
    echo "[$TS] rc=0 escalate=1 result=\"SENT ${RESULT_1LINE:0:70}\"" >> "$LOG"
    echo "escalated + notified."
    exit 0
  fi
  RESULT_1LINE="tg-send failed: ${RESULT_1LINE:0:60}"
  RC=1
fi
[ $RC -eq 0 ] && RC=1
echo "[$TS] rc=$RC escalate=1 result=\"${RESULT_1LINE:0:80}\"" >> "$LOG"
echo "FAILED to deliver watchdog alert (rc=$RC): $RESULT" >&2
exit 1
