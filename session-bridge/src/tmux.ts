export type SessionState = 'BLOCKED' | 'WORKING' | 'WAITING' | 'IDLE' | 'GONE'

// Ported from ~/.local/bin/agents classify() — keep the two in sync.
const BLOCKED_RE = /Esc to cancel|Enter to select|Do you want to (proceed|create|make|run|apply)/
const WORKING_RE = /esc to interrupt/
const WAITING_RE =
  /^[^A-Za-z]*[A-Z][a-z]+ for \d+m \d+s$|^[^A-Za-z]*[A-Z][a-z]+ for \d+s$|How is Claude doing this session|new task\? \/clear|say "do it"/m

export function tailLines(pane: string, n = 15): string {
  return pane
    .split('\n')
    .map(l => l.replace(/\s+$/, ''))
    .filter(l => l !== '')
    .slice(-n)
    .join('\n')
}

export function classify(pane: string | null): SessionState {
  if (pane === null) return 'GONE'
  const tail = tailLines(pane, 15)
  if (BLOCKED_RE.test(tail)) return 'BLOCKED'
  if (WORKING_RE.test(tail)) return 'WORKING'
  if (WAITING_RE.test(tail)) return 'WAITING'
  return 'IDLE'
}

function run(cmd: string[]): { code: number; out: string; err: string } {
  const r = Bun.spawnSync(cmd, { stdout: 'pipe', stderr: 'pipe' })
  return { code: r.exitCode, out: r.stdout.toString(), err: r.stderr.toString() }
}

// tmux -t targets are prefix matches by default; '=' forces an exact-name match so
// 'loom-1' can never resolve to 'loom-14'. Pane-taking commands (capture-pane,
// paste-buffer, send-keys) only honor '=' in the session part of a target-pane,
// so the trailing ':' is required — bare '=name' fails with "can't find pane".
function target(session: string): string {
  return `=${session}:`
}

function detail(err: string): string {
  const first = err.trim().slice(0, 200)
  return first === '' ? '' : `: ${first}`
}

export function listSessions(): string[] {
  const r = run(['tmux', 'ls', '-F', '#{session_name}'])
  if (r.code !== 0) return []
  return r.out.split('\n').filter(s => s !== '')
}

export function capturePane(session: string): string | null {
  // -J joins soft-wrapped lines: narrow panes split phrases like 'Esc to cancel'
  // across rows, which broke BLOCKED detection.
  const r = run(['tmux', 'capture-pane', '-t', target(session), '-p', '-J'])
  return r.code === 0 ? r.out : null
}

// Bracketed paste so multi-line text doesn't submit early; Enter submits once.
export function inject(session: string, text: string): void {
  const buf = `sb-${session.replace(/[^a-zA-Z0-9]/g, '_')}`
  for (const step of [
    ['tmux', 'set-buffer', '-b', buf, '--', text],
    ['tmux', 'paste-buffer', '-p', '-d', '-b', buf, '-t', target(session)],
    ['tmux', 'send-keys', '-t', target(session), 'Enter'],
  ]) {
    const r = run(step)
    if (r.code !== 0) throw new Error(`tmux ${step[1]} failed for ${session}${detail(r.err)}`)
  }
}

export function pressKey(session: string, key: string): void {
  const r = run(['tmux', 'send-keys', '-t', target(session), key])
  if (r.code !== 0) throw new Error(`tmux send-keys failed for ${session}${detail(r.err)}`)
}
