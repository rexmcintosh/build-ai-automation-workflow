import { existsSync } from 'node:fs'
import { loadConfig, loadToken } from './config'
import { Telegram } from './telegram'
import { loadState, saveState, setPending, pendingPath } from './state'
import { planSync, debounceCloses } from './sync'
import { listSessions, capturePane, classify, inject, pressKey } from './tmux'
import { handleUpdate, blockedPrompt, armTopic, type RouterDeps } from './router'

const config = loadConfig()
const tg = new Telegram(loadToken())
const state = loadState()

// Sessions whose topics were open but missing from the previous sync's session list.
// A close only fires on the second consecutive miss, so one failed `tmux ls` (which
// returns an empty list) cannot archive every tab.
let prevMissing = new Set<string>()

async function runSync(): Promise<void> {
  const actions = planSync(listSessions(), state.topics, config.excludeRegexps)
  const { execute, nextMissing } = debounceCloses(actions, prevMissing)
  prevMissing = nextMissing
  // Persist after every single action: a Telegram failure mid-loop must not lose the
  // topics already created, or the next sync would create duplicates.
  for (const a of execute) {
    if (a.kind === 'create') {
      const topicId = await tg.createTopic(config.groupId, a.session)
      state.topics[a.session] = { topicId, status: 'open' }
      saveState(state)
      console.error(`session-bridge: topic created for ${a.session} (${topicId})`)
    } else {
      await tg.renameAndClose(config.groupId, a.topicId!, `✖ ${a.session}`)
      state.topics[a.session].status = 'closed'
      saveState(state)
      console.error(`session-bridge: topic archived for ${a.session}`)
    }
  }
}

// One guard for both callers (timer and post-update), so they never overlap.
let syncing = false
async function syncNow(label: string): Promise<void> {
  if (syncing) return
  syncing = true
  try {
    await runSync()
  } catch (e) {
    console.error(`session-bridge: ${label} error: ${e}`)
  } finally {
    syncing = false
  }
}

const deps: RouterDeps = {
  config,
  topics: () => state.topics,
  classify: s => classify(capturePane(s)),
  capture: capturePane,
  inject,
  pressKey,
  reply: (threadId, text) => tg.send(config.groupId, threadId, text),
  setPending,
}

// Sync on a timer; the event loop interleaves this with the long poll below.
setInterval(() => {
  void syncNow('sync')
}, config.topicSyncIntervalSec * 1000)

// Blocked-watcher: a session the user is mid-conversation with (pending flag
// set) that freezes on a permission/question modal can't announce itself — no
// Stop fires while it waits. Watch flagged sessions and proactively post the
// armed prompt to their tab, once per blocked episode (edge-triggered).
const blockedNotified = new Set<string>()
let watching = false
setInterval(() => {
  if (watching) return
  watching = true
  void (async () => {
    try {
      for (const [session, t] of Object.entries(state.topics)) {
        if (t.status !== 'open' || !existsSync(pendingPath(session))) continue
        const pane = capturePane(session)
        if (classify(pane) !== 'BLOCKED') {
          blockedNotified.delete(session)
          continue
        }
        if (blockedNotified.has(session)) continue
        blockedNotified.add(session)
        armTopic(t.topicId)
        await tg.send(config.groupId, t.topicId, blockedPrompt(session, pane ?? ''))
        console.error(`session-bridge: posted blocked prompt for ${session}`)
      }
    } catch (e) {
      console.error(`session-bridge: blocked-watch error: ${e}`)
    } finally {
      watching = false
    }
  })()
}, 5000)

console.error('session-bridge: starting')
await syncNow('initial sync')

while (true) {
  try {
    const updates = await tg.getUpdates(state.offset, config.pollTimeoutSec)
    for (const u of updates) {
      state.offset = Math.max(state.offset, u.update_id + 1)
      try {
        await handleUpdate(u, deps)
      } catch (e) {
        console.error(`session-bridge: handler error: ${e}`)
      }
      // Persist per update, not per batch, to shrink the crash replay window.
      saveState(state)
    }
    // Sync on every update batch: picks up new tabs and archives GONE ones promptly.
    if (updates.length > 0) await syncNow('post-update sync')
  } catch (e) {
    console.error(`session-bridge: poll error: ${e}`)
    await Bun.sleep(5000)
  }
}
