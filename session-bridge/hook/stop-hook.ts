// Claude Code Stop hook: if this tmux session's last input came from Telegram
// (pending flag set by session-bridge), send the final assistant text to that
// forum topic. Must always exit 0 and cost ~nothing when the flag is absent.
import { existsSync, readFileSync, unlinkSync } from 'node:fs'
import { loadConfig, loadToken } from '../src/config'
import { pendingPath } from '../src/state'
import { Telegram } from '../src/telegram'

const STALE_MS = 3_600_000

export function lastAssistantText(jsonl: string): string | null {
  let out: string | null = null
  for (const line of jsonl.split('\n')) {
    if (line.trim() === '') continue
    let entry: any
    try {
      entry = JSON.parse(line)
    } catch {
      continue
    }
    if (entry.type !== 'assistant') continue
    const blocks = entry.message?.content
    if (!Array.isArray(blocks)) continue
    const texts = blocks
      .filter((b: any) => b.type === 'text' && typeof b.text === 'string')
      .map((b: any) => b.text)
    if (texts.length > 0) out = texts.join('\n\n')
  }
  return out
}

if (import.meta.main) {
  try {
    if (!process.env.TMUX) process.exit(0)
    const r = Bun.spawnSync(['tmux', 'display-message', '-p', '#S'])
    const session = r.stdout.toString().trim()
    if (session === '') process.exit(0)

    const flagPath = pendingPath(session)
    if (!existsSync(flagPath)) process.exit(0)
    const flag = JSON.parse(readFileSync(flagPath, 'utf8'))
    if (Date.now() - flag.ts > STALE_MS) {
      unlinkSync(flagPath)
      process.exit(0)
    }

    const input = JSON.parse(await Bun.stdin.text())
    const text = lastAssistantText(readFileSync(input.transcript_path, 'utf8'))
    if (text === null) {
      unlinkSync(flagPath)
      process.exit(0)
    }

    const config = loadConfig()
    await new Telegram(loadToken()).send(config.groupId, flag.topicId, text)
    unlinkSync(flagPath)
  } catch (e) {
    // Leave the flag for a retry on the next Stop; never fail the session.
    console.error(`session-bridge hook: ${e}`)
  }
  process.exit(0)
}
