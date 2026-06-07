#!/usr/bin/env bash
# Thin cron/manual entrypoint: single-run guard + venv, delegates all logic to loom.cli.
set -uo pipefail
REPO="/home/dev/projects/build-ai-automation-workflow"
LOCK="$REPO/loom/.run.lock"
LOG="$REPO/loom/logs/runs.log"
mkdir -p "$REPO/loom/logs"
exec 9>"$LOCK"
if ! flock -n 9; then echo "[$(date -Iseconds)] another run in progress; skipping" >>"$LOG"; exit 0; fi
TS="$(date -Iseconds)"
OUT="$("$REPO/.venv/bin/python" -m loom.cli absorb 2>>"$LOG.err")"; RC=$?
echo "[$TS] rc=$RC $OUT" >>"$LOG"
if [ $RC -ne 0 ]; then
  claude -p "Send a Telegram message to chat_id 7735693897: '⚠️ Loom absorb failed (rc=$RC). Check loom/logs/.' Output only SENT or FAILED." \
    --model haiku --allowedTools mcp__plugin_telegram_telegram__reply --dangerously-skip-permissions --output-format text >/dev/null 2>&1 || true
fi
exit $RC
