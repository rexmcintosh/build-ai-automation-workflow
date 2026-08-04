import { test, expect } from 'bun:test'
import { chunkText } from '../src/chunk'

test('short text is a single chunk', () => {
  expect(chunkText('hello', 4096)).toEqual(['hello'])
})

test('splits at paragraph boundary under the limit', () => {
  const a = 'a'.repeat(60)
  const b = 'b'.repeat(60)
  const chunks = chunkText(`${a}\n\n${b}`, 100)
  expect(chunks).toEqual([a, b])
})

test('hard-cuts a single oversized paragraph', () => {
  const chunks = chunkText('x'.repeat(250), 100)
  expect(chunks.length).toBe(3)
  expect(chunks.every(c => c.length <= 100)).toBe(true)
  expect(chunks.join('')).toBe('x'.repeat(250))
})

test('empty text yields no chunks', () => {
  expect(chunkText('', 100)).toEqual([])
})
