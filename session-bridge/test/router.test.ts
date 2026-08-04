import { test, expect } from 'bun:test'
import { handleUpdate, type RouterDeps } from '../src/router'
import type { SessionState } from '../src/tmux'

const CFG = {
  groupId: -1004480392983,
  allowedUserId: 7735693897,
  excludePatterns: [],
  pollTimeoutSec: 50,
  topicSyncIntervalSec: 30,
}

function makeDeps(state: SessionState, pane = 'PANE') {
  const calls = { injected: [] as string[], pressed: [] as string[], replies: [] as string[], pending: [] as number[] }
  const deps: RouterDeps = {
    config: CFG,
    topics: () => ({ 'loom-14': { topicId: 7, status: 'open' } }),
    classify: () => state,
    capture: () => pane,
    inject: (_s, text) => { calls.injected.push(text) },
    pressKey: (_s, key) => { calls.pressed.push(key) },
    reply: async (_t, text) => { calls.replies.push(text) },
    setPending: (_s, topicId) => { calls.pending.push(topicId) },
  }
  return { deps, calls }
}

function msg(text: string, over: Record<string, unknown> = {}) {
  return {
    update_id: 1,
    message: {
      message_id: 10,
      text,
      chat: { id: CFG.groupId },
      from: { id: CFG.allowedUserId },
      message_thread_id: 7,
      ...over,
    },
  }
}

test('wrong chat is dropped silently', async () => {
  const { deps, calls } = makeDeps('WAITING')
  await handleUpdate(msg('hi', { chat: { id: 123 } }), deps)
  expect(calls.replies).toEqual([])
  expect(calls.injected).toEqual([])
})

test('wrong user is dropped silently', async () => {
  const { deps, calls } = makeDeps('WAITING')
  await handleUpdate(msg('hi', { from: { id: 999 } }), deps)
  expect(calls.replies).toEqual([])
  expect(calls.injected).toEqual([])
})

test('non-text update (photo, member change) is ignored', async () => {
  const { deps, calls } = makeDeps('WAITING')
  await handleUpdate({ update_id: 1, my_chat_member: {} }, deps)
  expect(calls.replies).toEqual([])
})

test('General topic (no thread id) gets the hint', async () => {
  const { deps, calls } = makeDeps('WAITING')
  await handleUpdate(msg('hi', { message_thread_id: undefined }), deps)
  expect(calls.replies[0]).toContain('General tab is not routed')
})

test('unknown topic id → no live session reply', async () => {
  const { deps, calls } = makeDeps('WAITING')
  await handleUpdate(msg('hi', { message_thread_id: 99 }), deps)
  expect(calls.replies[0]).toBe('no live session for this tab')
})

test('WAITING → inject, flag, delivered', async () => {
  const { deps, calls } = makeDeps('WAITING')
  await handleUpdate(msg('run the tests'), deps)
  expect(calls.injected).toEqual(['run the tests'])
  expect(calls.pending).toEqual([7])
  expect(calls.replies).toEqual(['→ delivered'])
})

test('WORKING → inject, flag, queued warning', async () => {
  const { deps, calls } = makeDeps('WORKING')
  await handleUpdate(msg('also check lint'), deps)
  expect(calls.injected).toEqual(['also check lint'])
  expect(calls.pending).toEqual([7])
  expect(calls.replies[0]).toStartWith('⏳ session is working — queued')
})

test('BLOCKED + ordinary text → excerpt, no inject', async () => {
  const { deps, calls } = makeDeps('BLOCKED', 'Do you want to proceed?\nEsc to cancel')
  await handleUpdate(msg('what is happening'), deps)
  expect(calls.injected).toEqual([])
  expect(calls.replies[0]).toContain('Do you want to proceed?')
  expect(calls.replies[0]).toContain('say approve, deny, or an option number (1-9)')
})

test('BLOCKED + approve → presses 1 and confirms', async () => {
  const { deps, calls } = makeDeps('BLOCKED')
  await handleUpdate(msg('approve'), deps)
  expect(calls.pressed).toEqual(['1'])
  expect(calls.replies[0]).toStartWith('✅ pressed')
})

test('BLOCKED + deny → presses Escape', async () => {
  const { deps, calls } = makeDeps('BLOCKED')
  await handleUpdate(msg('Deny'), deps)
  expect(calls.pressed).toEqual(['Escape'])
})

test('BLOCKED + option number → presses that digit', async () => {
  const { deps, calls } = makeDeps('BLOCKED')
  await handleUpdate(msg('2'), deps)
  expect(calls.pressed).toEqual(['2'])
})

test('GONE → session ended reply, no inject', async () => {
  const { deps, calls } = makeDeps('GONE')
  await handleUpdate(msg('hello?'), deps)
  expect(calls.injected).toEqual([])
  expect(calls.replies[0]).toBe('session ended — tab will be archived')
})
