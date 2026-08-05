import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
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

// Absent file → fresh state. A file that EXISTS but will not parse must crash the
// daemon: silently starting empty would duplicate every topic and replay from offset 0.
export function loadState(dir = STATE_DIR): BridgeState {
  const path = join(dir, 'state.json')
  if (!existsSync(path)) return { offset: 0, topics: {} }
  let s: any
  try {
    s = JSON.parse(readFileSync(path, 'utf8'))
  } catch (e) {
    throw new Error(`session-bridge state file is corrupt at ${path} — fix or remove it: ${e}`)
  }
  if (s === null || typeof s !== 'object') {
    throw new Error(`session-bridge state file is corrupt at ${path} — not a JSON object`)
  }
  return { offset: s.offset ?? 0, topics: s.topics ?? {} }
}

// Write-then-rename: a crash mid-write leaves the previous good state.json intact.
export function saveState(s: BridgeState, dir = STATE_DIR): void {
  mkdirSync(dir, { recursive: true })
  const tmp = join(dir, 'state.json.tmp')
  writeFileSync(tmp, JSON.stringify(s, null, 2))
  renameSync(tmp, join(dir, 'state.json'))
}

export function sanitizeSession(name: string): string {
  const safe = name.replace(/[^a-zA-Z0-9._-]/g, '_')
  // '.' / '..' / '...' would resolve to the pending dir itself or its parent.
  return /^\.+$/.test(safe) ? '_' : safe
}

export function pendingPath(session: string, dir = STATE_DIR): string {
  return join(dir, 'pending', sanitizeSession(session))
}

// `remaining` is how many Stop events should still forward an answer to this topic.
// A WORKING session owes two: its in-flight turn, then the answer to the new message.
export function setPending(session: string, topicId: number, dir = STATE_DIR, remaining = 1): void {
  mkdirSync(join(dir, 'pending'), { recursive: true })
  writeFileSync(pendingPath(session, dir), JSON.stringify({ topicId, ts: Date.now(), remaining }))
}
