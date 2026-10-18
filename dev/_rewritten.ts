// Helpers for the "rewritten output" contract (specs/dev.md section 5, decided 2026-10-12).
// Separate file so the shared _harness.ts stays untouched.
// The fake host's Bash tool result carries exactly the text supplied by the test; an optional
// leading `Exit code N` line is part of that text (as the real host renders failed commands).
import type { Any } from './_harness'

export type RawBash = { exit?: number; isError?: boolean; agentId?: string }

/** Tool answer whose text is `text`, prefixed by `Exit code N` when `exit` is given. */
export function rawBashAnswer(text: string, x: RawBash = {}): Any {
  const full = x.exit !== undefined ? `Exit code ${x.exit}\n${text}` : text
  const isError = x.isError ?? (x.exit !== undefined && x.exit !== 0)
  if (isError) return { isError: true, result: full, text: full }
  return { result: { stdout: full, stderr: '', interrupted: false }, text: full }
}

/** Run a Bash tool call whose result is `text` (see rawBashAnswer). */
export async function bashRaw($: Any, w: Any, command: string, text: string, x: RawBash = {}): Promise<Any> {
  return w.tool($, { tool: 'Bash', command, ...(x.agentId ? { agentId: x.agentId } : {}) }, rawBashAnswer(text, x))
}

export const RTK_GO_FAIL = [
  'Go test: 0 passed, 1 failed in 1 packages',
  '',
  'acc (0 passed, 1 failed)',
  '  [FAIL] TestX',
  '     x_test.go:3: boom',
  '[full output: rtk recall abc]',
].join('\n')

/** `git diff --numstat -z` fixture. */
export const numstat = (rows: [string, number, number][]): string => rows.map(([p, a, d]) => `${a}\t${d}\t${p}\0`).join('')
/** `git diff --name-status -z` fixture (all modified). */
export const nameStatus = (rows: [string, number, number][]): string => rows.map(([p]) => `M\0${p}\0`).join('')
