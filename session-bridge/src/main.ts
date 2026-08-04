import { loadConfig, loadToken } from './config'
import { Telegram } from './telegram'
import { loadState, saveState, setPending } from './state'
import { planSync } from './sync'
import { listSessions, capturePane, classify, inject, pressKey } from './tmux'
import { handleUpdate, type RouterDeps } from './router'

const config = loadConfig()
const tg = new Telegram(loadToken())
const state = loadState()

async function runSync(): Promise<void> {
  const actions = planSync(listSessions(), state.topics, config.excludePatterns)
  for (const a of actions) {
    if (a.kind === 'create') {
      const topicId = await tg.createTopic(config.groupId, a.session)
      state.topics[a.session] = { topicId, status: 'open' }
      console.error(`session-bridge: topic created for ${a.session} (${topicId})`)
    } else {
      await tg.renameAndClose(config.groupId, a.topicId!, `✖ ${a.session}`)
      state.topics[a.session].status = 'closed'
      console.error(`session-bridge: topic archived for ${a.session}`)
    }
  }
  if (actions.length > 0) saveState(state)
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
let syncing = false
setInterval(async () => {
  if (syncing) return
  syncing = true
  try {
    await runSync()
  } catch (e) {
    console.error(`session-bridge: sync error: ${e}`)
  } finally {
    syncing = false
  }
}, config.topicSyncIntervalSec * 1000)

console.error('session-bridge: starting')
await runSync().catch(e => console.error(`session-bridge: initial sync error: ${e}`))

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
    }
    if (updates.length > 0) saveState(state)
  } catch (e) {
    console.error(`session-bridge: poll error: ${e}`)
    await Bun.sleep(5000)
  }
}
