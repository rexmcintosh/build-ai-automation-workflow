import { test, expect } from 'bun:test'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { loadConfig, loadToken } from '../src/config'

function tmp(): string { return mkdtempSync(join(tmpdir(), 'sb-')) }

test('loadConfig parses config.json', () => {
  const d = tmp()
  writeFileSync(join(d, 'config.json'), JSON.stringify({
    groupId: -1004480392983, allowedUserId: 7735693897,
    excludePatterns: ['^cai/'], pollTimeoutSec: 50, topicSyncIntervalSec: 30,
  }))
  const c = loadConfig(join(d, 'config.json'))
  expect(c.groupId).toBe(-1004480392983)
  expect(c.excludePatterns).toEqual(['^cai/'])
})

test('loadConfig throws a plain error on missing file', () => {
  expect(() => loadConfig('/nonexistent/config.json')).toThrow(/config/)
})

test('loadToken parses TELEGRAM_BOT_TOKEN= line', () => {
  const d = tmp()
  writeFileSync(join(d, '.env'), 'TELEGRAM_BOT_TOKEN=123:abc\n')
  expect(loadToken(join(d, '.env'))).toBe('123:abc')
})

test('loadToken throws when the variable is absent', () => {
  const d = tmp()
  writeFileSync(join(d, '.env'), 'OTHER=x\n')
  expect(() => loadToken(join(d, '.env'))).toThrow(/TELEGRAM_BOT_TOKEN/)
})
