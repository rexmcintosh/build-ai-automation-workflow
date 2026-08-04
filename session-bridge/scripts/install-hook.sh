#!/usr/bin/env bash
# Adds the session-bridge Stop hook to ~/.claude/settings.json (idempotent).
# Run by the USER via a ! one-liner — agent writes to ~/.claude are auto-mode-gated.
set -euo pipefail

SETTINGS="$HOME/.claude/settings.json"
CMD="/usr/local/bin/bun /home/dev/projects/build-ai-automation-workflow/session-bridge/hook/stop-hook.ts"

if jq -e --arg cmd "$CMD" '[.hooks.Stop[]?.hooks[]?.command] | index($cmd)' "$SETTINGS" >/dev/null 2>&1; then
  echo "already installed"
  exit 0
fi

tmp="$(mktemp)"
jq --arg cmd "$CMD" \
  '.hooks.Stop = ((.hooks.Stop // []) + [{"hooks": [{"type": "command", "command": $cmd, "timeout": 30}]}])' \
  "$SETTINGS" > "$tmp"
mv "$tmp" "$SETTINGS"
echo "installed — new sessions pick it up; running sessions need a restart"
