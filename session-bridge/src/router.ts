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
  setPending(session: string, topicId: number): void
}

const APPROVAL_HINT = 'say approve, deny, or an option number (1-9)'

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
    const key = word === 'approve' ? '1' : word === 'deny' ? 'Escape' : /^[1-9]$/.test(word) ? word : null
    if (key === null) {
      const pane = deps.capture(session) ?? ''
      await deps.reply(threadId, `🔴 ${session} is waiting on an approval:\n\n${tailLines(pane, 15)}\n\n${APPROVAL_HINT}`)
      return
    }
    deps.pressKey(session, key)
    await Bun.sleep(500)
    const after = deps.capture(session) ?? ''
    await deps.reply(threadId, `✅ pressed — current screen:\n\n${tailLines(after, 8)}`)
    return
  }

  // WORKING / WAITING / IDLE: deliver the text.
  deps.inject(session, msg.text)
  deps.setPending(session, threadId)
  if (state === 'WORKING') {
    await deps.reply(
      threadId,
      '⏳ session is working — queued. The next answer may belong to its current task; yours follows.',
    )
  } else {
    await deps.reply(threadId, '→ delivered')
  }
}
