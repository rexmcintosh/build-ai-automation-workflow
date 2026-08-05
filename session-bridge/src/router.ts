import type { Config } from './config'
import type { SessionState } from './tmux'
import type { TopicInfo } from './state'
import { tailLines } from './tmux'

export interface RouterDeps {
  config: Config
  topics(): Record<string, TopicInfo>
  classify(session: string): SessionState
  capture(session: string): string | null
  inject(session: string, text: string): void
  pressKey(session: string, key: string): void
  reply(threadId: number | undefined, text: string): Promise<void>
  setPending(session: string, topicId: number, dir?: string, remaining?: number): void
}

const APPROVAL_HINT = 'say approve, deny, or an option number (1-9)'

// One message format for "this session is blocked", shared by the router's
// reactive path and main's proactive blocked-watcher.
export function blockedPrompt(session: string, pane: string): string {
  return `🔴 ${session} is waiting on an approval:\n\n${tailLines(pane, 15)}\n\n${APPROVAL_HINT}`
}

// Main's blocked-watcher arms a topic when it proactively posts the prompt,
// so the user's next reply can press a key without another round trip.
export function armTopic(threadId: number): void {
  armed.set(threadId, Date.now())
}
const ARM_WINDOW_MS = 10 * 60 * 1000

// A topic is "armed" once we have shown its pending prompt. Keys are only honored
// while armed, so a message typed before seeing the prompt can never press a button.
const armed = new Map<number, number>()

export function resetArmedForTests(): void {
  armed.clear()
}

function isArmed(threadId: number, now: number): boolean {
  const at = armed.get(threadId)
  if (at === undefined) return false
  if (now - at > ARM_WINDOW_MS) {
    armed.delete(threadId)
    return false
  }
  return true
}

export async function handleUpdate(update: any, deps: RouterDeps): Promise<void> {
  const msg = update.message
  if (!msg || typeof msg.text !== 'string') return
  if (msg.chat?.id !== deps.config.groupId) return
  if (msg.from?.id !== deps.config.allowedUserId) return

  const threadId: number | undefined = msg.message_thread_id
  if (threadId === undefined) {
    await deps.reply(undefined, 'talk to a session in its own tab — this General tab is not routed')
    return
  }

  const entry = Object.entries(deps.topics()).find(
    ([, t]) => t.topicId === threadId && t.status === 'open',
  )
  if (!entry) {
    await deps.reply(threadId, 'no live session for this tab')
    return
  }
  const [session] = entry
  const state = deps.classify(session)

  if (state === 'GONE') {
    await deps.reply(threadId, 'session ended — tab will be archived')
    return
  }

  if (state === 'BLOCKED') {
    const word = msg.text.trim().toLowerCase()
    const wanted =
      word === 'approve' ? '1' : word === 'deny' ? 'Escape' : /^[1-9]$/.test(word) ? word : null
    // Unarmed topics always get the prompt first, even for "approve" — you never
    // approve something you have not been shown.
    const key = wanted !== null && isArmed(threadId, Date.now()) ? wanted : null
    if (key === null) {
      const pane = deps.capture(session) ?? ''
      armed.set(threadId, Date.now())
      await deps.reply(threadId, blockedPrompt(session, pane))
      return
    }
    armed.delete(threadId)
    // Flag first: the answer that follows the approval belongs in this tab.
    deps.setPending(session, threadId, undefined, 1)
    deps.pressKey(session, key)
    await Bun.sleep(500)
    const after = deps.capture(session) ?? ''
    await deps.reply(threadId, `✅ pressed — current screen:\n\n${tailLines(after, 8)}`)
    return
  }

  // WORKING / WAITING / IDLE: deliver the text.
  // Strip ESC so pasted content cannot terminate bracketed paste early.
  // The preamble stops the session from "helpfully" replying via its own
  // telegram plugin tools — the bridge's Stop hook relays the answer instead.
  const text =
    '[message from Rex via this session\'s Telegram tab — answer normally in this chat; ' +
    'the bridge relays your reply back to the tab. Never send Telegram messages yourself.]\n' +
    msg.text.replace(/\x1b/g, '')
  try {
    deps.inject(session, text)
  } catch (e) {
    console.error(`session-bridge: inject failed for ${session}: ${e}`)
    await deps.reply(
      threadId,
      `⚠ delivery failed — could not type into ${session}; check journalctl --user -u session-bridge`,
    )
    return
  }
  // A WORKING session owes two answers: its in-flight turn, then yours.
  deps.setPending(session, threadId, undefined, state === 'WORKING' ? 2 : 1)
  if (state === 'WORKING') {
    await deps.reply(
      threadId,
      '⏳ session is working — queued. The next answer may belong to its current task; yours follows.',
    )
  } else {
    await deps.reply(threadId, '→ delivered')
  }
}
