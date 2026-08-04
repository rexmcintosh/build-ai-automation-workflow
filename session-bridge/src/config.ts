import { readFileSync } from 'node:fs'

export const CONFIG_DIR = `${process.env.HOME}/.config/session-bridge`
export const STATE_DIR = `${process.env.HOME}/.local/state/session-bridge`

export interface Config {
  groupId: number
  allowedUserId: number
  excludePatterns: string[]
  pollTimeoutSec: number
  topicSyncIntervalSec: number
}

export function loadConfig(path = `${CONFIG_DIR}/config.json`): Config {
  let raw: string
  try {
    raw = readFileSync(path, 'utf8')
  } catch {
    throw new Error(`session-bridge config not readable at ${path}`)
  }
  return JSON.parse(raw) as Config
}

export function loadToken(path = `${CONFIG_DIR}/.env`): string {
  const raw = readFileSync(path, 'utf8')
  const m = raw.match(/^TELEGRAM_BOT_TOKEN=(.+)$/m)
  if (!m) throw new Error(`TELEGRAM_BOT_TOKEN not found in ${path}`)
  return m[1].trim()
}
