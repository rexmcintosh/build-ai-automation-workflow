import { test, expect } from 'bun:test'
import { mkdtempSync, readFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { loadState, saveState, setPending, pendingPath, sanitizeSession } from '../src/state'

function tmp(): string { return mkdtempSync(join(tmpdir(), 'sb-state-')) }

test('loadState returns empty state when file is absent', () => {
  const s = loadState(tmp())
  expect(s).toEqual({ offset: 0, topics: {} })
})

test('saveState/loadState round-trips', () => {
  const d = tmp()
  saveState({ offset: 42, topics: { 'loom-14': { topicId: 7, status: 'open' } } }, d)
  expect(loadState(d)).toEqual({ offset: 42, topics: { 'loom-14': { topicId: 7, status: 'open' } } })
})

test('setPending writes topicId and a timestamp', () => {
  const d = tmp()
  setPending('loom-14', 7, d)
  const flag = JSON.parse(readFileSync(pendingPath('loom-14', d), 'utf8'))
  expect(flag.topicId).toBe(7)
  expect(typeof flag.ts).toBe('number')
})

test('sanitizeSession replaces path separators', () => {
  expect(sanitizeSession('cai/foo')).toBe('cai_foo')
})

test('loadState survives corrupt json', () => {
  const d = tmp()
  saveState({ offset: 1, topics: {} }, d)
  const s = loadState(d)
  expect(existsSync(join(d, 'state.json'))).toBe(true)
  expect(s.offset).toBe(1)
})
