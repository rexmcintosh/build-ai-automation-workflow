# Bebop Personal Assistant — Design (Slice 1: twice-daily briefing)

- **Status:** Built & deployed (cron live). Spec written retroactively to the as-built system.
- **Date:** 2026-06-06
- **Scope:** Slice 1 of a 4-slice personal-assistant roadmap (the twice-daily briefing "spine").

> **Thesis:** Bebop is a cheap, legible, fail-loud cron loop that turns Gmail + Calendar **deltas**
> into a glanceable twice-daily briefing on Telegram. Everything below serves that one sentence.

---

## 1. Invariants

The load-bearing rules. If a change violates one of these, it's wrong — fix the change, not the rule.

| Invariant | Means | Where it lives |
|---|---|---|
| **Delta-only** | Never re-read what's already been seen; scan email *since the last successful run*. | `state.json` → `SINCE_EPOCH` |
| **Fail loud** | Silence never hides a break. A failed run pings Telegram with the reason. | runner failure path |
| **Advance only on success** | `state.json` moves forward *only* after `SENT`. A failed run re-scans the same window — it never skips email. | runner gate |
| **Cheap by default** | Haiku + minimal context + 5-tool whitelist. Escalate only when a task demands it. | `run-briefing.sh` flags |
| **Send-only (for now)** | Slice 1 is outbound. Two-way chat needs a persistent listener, not a cron job — it's a Slice 4 prerequisite. | scope |
| **Reversible cutover** | Hermes is stopped, not deleted. `~/.hermes/` stays as a fallback for a few days. | ops |

---

## 2. Purpose & context

Rex ran his assistant "Bebop" on **Hermes** (Nous Research's self-improving agent) on `mesh-vps`.
It worked, but it metered tokens at a **~$1,000/month-equivalent pace** — a day of setup-level use
burned the daily Venice DIEM budget before the assistant felt "up and running."

The honest assessment that triggered the switch:

| | Hermes | Claude Code |
|---|---|---|
| Differentiated as… | a thin always-on Telegram + memory shell | the engine that does the work |
| The actual work | already delegated to Claude Code (it built the RexBrain wiki via Opus 4.8) | native |
| Primitives (MCP, memory, skills, Telegram) | wraps them | ships them |
| Interactive cost | metered per token (Venice) | flat (Max subscription) |

So this rebuilds Bebop on Claude Code, retires Hermes, and proves the cheapest useful loop. It is
**Slice 1 of 4**; each later slice reuses this machinery (**~70% of the engineering is Slice 1**):

1. **Twice-daily briefing** ← *this spec*
2. **Proactive alerts** — same scan, event-triggered pings
3. **Tends the knowledge base** — route worth-keeping items into `~/wiki/` + memory
4. **Takes actions** — draft replies / schedule / update Notion, gated by approve-via-Telegram

---

## 3. Goals & non-goals

| Goals | Non-goals (Slice 1) |
|---|---|
| Scheduled Gmail + Calendar briefing → Telegram, twice daily | Two-way / interactive chat (needs a persistent listener) |
| Structurally cheap (target ≤ low-$10s/month) | Slices 2–4 |
| Robust unattended (fail loud, never skip email) | Notion / Drive / repo scanning (Gmail + Calendar only — best signal/cost) |
| Owned & legible (a handful of files Rex controls) | Deleting `~/.hermes/` |
| Clean, reversible cutover from Hermes | Per-run MCP scoping via `--mcp-config` (deferred cost lever) |

---

## 4. Architecture

No agent framework. A bash runner invokes **headless Claude Code** (`claude -p`) on the always-on
VPS, driven by **cron**. State is one JSON file; delivery is the Claude Code **Telegram plugin**.
Lives in `build-ai-automation-workflow/bebop/`.

```
cron (07:00 + 18:00 Europe/Lisbon, CRON_TZ)
  └─ run-briefing.sh <morning|evening>
       ├─ read state.json  →  SINCE_EPOCH (last successful run; default now-24h)   [Delta-only]
       ├─ substitute {{NOW}} {{SINCE}} {{SINCE_EPOCH}} {{CHAT_ID}} into the prompt
       ├─ claude -p <prompt> --model haiku --allowedTools <5 tools>               [Cheap by default]
       │                     --dangerously-skip-permissions --output-format json
       │     ├─ Gmail   search_threads  (important only, after:SINCE_EPOCH)
       │     ├─ Gmail   get_thread       (only if a subject is ambiguous)
       │     ├─ Calendar list_events     (today | tomorrow)
       │     └─ Telegram reply           → digest to Rex (chat 7735693897)
       ├─ append cost/tokens/result → logs/runs.log
       └─ if SENT: advance state.json   else: ping Telegram + exit 1   [Advance-on-success / Fail-loud]
```

### Components (small, single-purpose)

| File | Responsibility |
|---|---|
| `bebop/prompts/briefing-morning.md` | Morning: today's schedule + important new email. Template vars `{{NOW}} {{SINCE}} {{SINCE_EPOCH}} {{CHAT_ID}}`. The thing Rex tunes. |
| `bebop/prompts/briefing-evening.md` | Evening wrap + **tomorrow** preview; biases email toward "still needs a reply today." |
| `bebop/run-briefing.sh` | Orchestrator: delta window, substitution, headless invoke, cost logging, success-gated state, failure ping. |
| `bebop/state.json` | `{last_run_epoch, last_run_iso, last_mode}`. The delta mechanism. Gitignored. |
| `bebop/logs/runs.log` | One line/run: mode, rc, result, cost_usd, tokens. The cost watch. Gitignored. |
| `bebop/README.md` | Operational doc (run, schedule, gotchas). |
| crontab (user) | `CRON_TZ=Europe/Lisbon`, pinned `PATH`/`HOME`, two entries → `cron.log`. |

---

## 5. Data flow

1. Cron fires the runner with `morning` or `evening`.
2. Runner reads `state.json` → `SINCE_EPOCH` (default `now-24h`), computes Lisbon `NOW`/`SINCE`,
   substitutes them into the chosen prompt.
3. `claude -p` runs on **haiku** with a 5-tool whitelist: `Gmail.search_threads`,
   `Gmail.get_thread`, `Calendar.list_events`, `Calendar.list_calendars`, `telegram.reply`.
4. Agent searches email since `SINCE_EPOCH` (promos/social/forums excluded), keeps only genuinely
   important items (top 5), reads today's/tomorrow's calendar, composes a ≤6-line digest, sends it.
5. Agent prints `SENT` (or `FAILED:<reason>`); `--output-format json` carries `result` + `usage`.
6. Runner logs cost. **`SENT`** → advance `state.json`. **Else** → Telegram failure ping + exit 1.

---

## 6. Delivery & access (the Telegram cutover)

Decision: **keep the `@Bebopmac_bot` identity** Rex already uses, drop Hermes (vs. Claude Code's
pre-existing `@JaneVal_bot`, vs. cloud `/schedule`, vs. a Hermes-stays hybrid).

- Token repointed `@JaneVal_bot` → `@Bebopmac_bot` in `~/.claude/channels/telegram/.env`.
- Allowlist `~/.claude/channels/telegram/access.json`: `dmPolicy: allowlist`,
  `allowFrom: ["7735693897"]`. Server re-reads on every inbound message.
- `hermes-gateway.service` **stopped + disabled** (one poller per token).
- `~/.hermes/` left intact [Reversible cutover].

---

## 7. Cost model

The decisive reason for the rebuild.

| | Value |
|---|---|
| Measured run | **~$0.07** (haiku) |
| Twice daily | **~$4–5/month** |
| vs. Hermes | ~$1,000/month-equivalent pace → **1–2 orders of magnitude cheaper** |
| Dominant cost | MCP tool schemas loaded into context, *not* output |
| Next lever if it drifts | scope to the 3 needed servers via `--mcp-config` + `--strict-mcp-config` (deferred) |

Controls baked in: cheap model, delta-only reads, 5-tool whitelist, ≤6-line output cap, no vision.
`logs/runs.log` records `cost_usd` per run so drift is visible.

---

## 8. Error handling

Each row is an instance of an invariant, not an ad-hoc patch.

| Failure | Behavior | Invariant |
|---|---|---|
| Agent can't complete (MCP/auth/API) | Prints `FAILED:…`; runner pings Telegram; state NOT advanced | Fail loud · Advance-on-success |
| `claude` non-zero exit | Same failure path | Fail loud |
| Telegram send fails | Surfaces as `FAILED`; failure ping best-effort (`|| true`); still logged | Fail loud |
| `state.json` missing/corrupt | Default window `now-24h`; run proceeds | Delta-only (degrades safe) |
| Cron env (PATH/HOME) | Crontab pins `PATH` (nvm bin) + `HOME`; runner falls back to `/usr/bin/claude` | — |

---

## 9. What good looks like

The briefing is judged on **signal**, not coverage. The bar: a glance on a phone tells Rex what
needs him. Show, don't dump.

**Good** — judgment applied, one line each, action surfaced:
```
☀️ Morning, Rex — Saturday, June 6
📅 Clear today; 17:00 Liam swim (Bullsharks)
📧 United crew scheduling — June bid opens Mon, action needed
📧 João (OIS) — wants a call re: meet calendar, reply
```

**Bad** — a count and a content dump, no judgment (this is the failure mode to design against):
```
📬 You have 14 new emails!
1. United Airlines — "Your June Newsletter is here ☀️"
2. LinkedIn — "You appeared in 7 searches"
3. ...
```

The difference is the **Cheap-by-default → important-only** filter doing real work: newsletters,
promos, receipts, and automated noise never reach the message.

---

## 10. Verification (as performed)

- **Headless MCP probe** — Calendar reads + Telegram send work via `claude -p`.
- **Permission finding** — `--allowedTools` alone does NOT authorize MCP calls headlessly (agent
  silently blocked, hallucinated an "auth issue"); `--dangerously-skip-permissions` required.
- **End-to-end run** — `./run-briefing.sh morning` → real briefing delivered, `state.json`
  advanced, cost logged (~$0.07).
- **Cron-env check** — `claude` resolves under the exact pinned cron `PATH`/`HOME`.
- No test suite (1-file bash + prompts); `logs/runs.log` is the ongoing health signal, watched
  over week 1.

---

## 11. Open questions (resolve via week-1 observation)

1. **Max billing for headless/scheduled `claude -p`** — subscription-covered vs. metered
   separately, unresolved at build time. Watch `logs/runs.log` + the Max usage dashboard.
2. **Signal tuning** — the "important email" heuristic needs a few real days to calibrate (false
   newsletters vs. missed real mail). The §9 bar is the target.
3. **Output size** — a run emitted ~3.4k output tokens for a 6-line digest; trim prompt verbosity
   if cost matters.

---

## 12. Roadmap (the other 3 slices)

| Slice | What | Reuses | New piece |
|---|---|---|---|
| 2 — Proactive alerts | event-triggered pings | the scan | trigger logic |
| 3 — Tends knowledge base | route keepers into `~/wiki/` + memory | the scan | a write step |
| 4 — Takes actions | draft/schedule/update, approve-via-Telegram | the scan + delivery | a persistent **listener** for true two-way (the one Hermes capability Slice 1's send-only cron does not replace) |
