import type { TopicInfo } from './state'

export interface SyncAction {
  kind: 'create' | 'close'
  session: string
  topicId?: number
}

export function planSync(
  live: string[],
  topics: Record<string, TopicInfo>,
  excludePatterns: string[],
): SyncAction[] {
  const excludes = excludePatterns.map(p => new RegExp(p))
  const watched = live.filter(s => !excludes.some(r => r.test(s)))
  const actions: SyncAction[] = []
  for (const session of watched) {
    const t = topics[session]
    if (!t || t.status === 'closed') actions.push({ kind: 'create', session })
  }
  for (const [session, t] of Object.entries(topics)) {
    if (t.status === 'open' && !watched.includes(session)) {
      actions.push({ kind: 'close', session, topicId: t.topicId })
    }
  }
  return actions
}
