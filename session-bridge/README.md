# session-bridge

One Telegram forum topic per tmux Claude session, in the private "Rex & Wall-E"
supergroup, via the dedicated bot @WallFred_bot. Message a session's tab and the
text is pasted into its Claude prompt; the reply comes back to the same tab via a
global Stop hook. Approve/deny permission prompts from the tab while a session is
blocked. Spec: `../docs/superpowers/specs/2026-08-03-session-bridge-design.md`.

## Layout

- `src/main.ts` — daemon: long-poll + topic sync (systemd user service `session-bridge`)
- `hook/stop-hook.ts` — Claude Code Stop hook (registered in `~/.claude/settings.json`)
- `~/.config/session-bridge/` — `config.json` (groupId, allowed user, excludes) + `.env` (bot token, 600)
- `~/.local/state/session-bridge/` — `state.json` (offset, session↔topic map) + `pending/` flags

## Operating notes

- One long-poll consumer per bot token: never run a second copy of the daemon.
- Topics are archived (`✖ name` + closed), never deleted.
- All sends are plain text; 4096-char chunks.
- Pane-state heuristics are a port of `~/.local/bin/agents` — update both together.
- Logs: `journalctl --user -u session-bridge -f`

## Recovery

- Restart: `systemctl --user restart session-bridge`
- Missed replies: check `~/.local/state/session-bridge/pending/` for stale flags (auto-expire after 1 h).
- Rebuild topic map: stop the service, delete `state.json`, start — new topics are created; old ones stay archived.
