import { test, expect } from 'bun:test'
import { lastAssistantText } from '../hook/stop-hook'

const L = (o: unknown) => JSON.stringify(o)

test('extracts text of the last assistant message with text blocks', () => {
  const jsonl = [
    L({ type: 'user', message: { content: [{ type: 'text', text: 'hi' }] } }),
    L({ type: 'assistant', message: { content: [{ type: 'text', text: 'first' }] } }),
    L({ type: 'assistant', message: { content: [{ type: 'tool_use', name: 'Bash' }] } }),
    L({ type: 'assistant', message: { content: [{ type: 'text', text: 'final answer' }] } }),
  ].join('\n')
  expect(lastAssistantText(jsonl)).toBe('final answer')
})

test('joins multiple text blocks with blank lines', () => {
  const jsonl = L({
    type: 'assistant',
    message: { content: [{ type: 'text', text: 'part 1' }, { type: 'text', text: 'part 2' }] },
  })
  expect(lastAssistantText(jsonl)).toBe('part 1\n\npart 2')
})

test('returns null when no assistant text exists', () => {
  const jsonl = L({ type: 'user', message: { content: [] } })
  expect(lastAssistantText(jsonl)).toBeNull()
})

test('skips malformed lines without throwing', () => {
  const jsonl = ['not json{{{', L({ type: 'assistant', message: { content: [{ type: 'text', text: 'ok' }] } })].join('\n')
  expect(lastAssistantText(jsonl)).toBe('ok')
})
