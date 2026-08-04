import { test, expect } from 'bun:test'
import { planSync } from '../src/sync'

test('new live session → create', () => {
  expect(planSync(['loom-14'], {}, [])).toEqual([{ kind: 'create', session: 'loom-14' }])
})

test('excluded sessions are never created', () => {
  expect(planSync(['cai/x', 'codex-bank-20', 'loom-14'], {}, ['^cai/', '^codex-'])).toEqual([
    { kind: 'create', session: 'loom-14' },
  ])
})

test('open topic with dead session → close', () => {
  expect(planSync([], { 'loom-14': { topicId: 7, status: 'open' } }, [])).toEqual([
    { kind: 'close', session: 'loom-14', topicId: 7 },
  ])
})

test('open topic with live session → no action', () => {
  expect(planSync(['loom-14'], { 'loom-14': { topicId: 7, status: 'open' } }, [])).toEqual([])
})

test('closed topic whose name is live again → fresh create', () => {
  expect(planSync(['loom-14'], { 'loom-14': { topicId: 7, status: 'closed' } }, [])).toEqual([
    { kind: 'create', session: 'loom-14' },
  ])
})

test('closed topic with dead session stays untouched', () => {
  expect(planSync([], { 'loom-14': { topicId: 7, status: 'closed' } }, [])).toEqual([])
})
