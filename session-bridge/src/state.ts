import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { STATE_DIR } from './config'

export interface TopicInfo {
  topicId: number
  status: 'open' | 'closed'
}

export interface BridgeState {
  offset: number
  topics: Record<string, TopicInfo>
}

export function loadState(dir = STATE_DIR): BridgeState {
  try {
    const raw = readFileSync(join(dir, 'state.json'), 'utf8')
    const s = JSON.parse(raw)
    return { offset: s.offset ?? 0, topics: s.topics ?? {} }
  } catch {
    return { offset: 0, topics: {} }
  }
}

export function saveState(s: BridgeState, dir = STATE_DIR): void {
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, 'state.json'), JSON.stringify(s, null, 2))
}

export function sanitizeSession(name: string): string {
  return name.replace(/[^a-zA-Z0-9._-]/g, '_')
}

export function pendingPath(session: string, dir = STATE_DIR): string {
  return join(dir, 'pending', sanitizeSession(session))
}

export function setPending(session: string, topicId: number, dir = STATE_DIR): void {
  mkdirSync(join(dir, 'pending'), { recursive: true })
  writeFileSync(pendingPath(session, dir), JSON.stringify({ topicId, ts: Date.now() }))
}
