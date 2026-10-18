import { test, expect } from 'claude-code/testing'
import { world, REPO } from './_harness'

// ---- C28 ----
test('C28 every observed event reaches the layer beneath (plugin calls next)', async ($, on) => {
  const w = await world($, on)
  const n = (k: string): number => (w.seen[k] ?? []).length
  const before = { m: n('session.measure'), ts: n('turn.start'), tc: n('turn.complete'), ps: n('prompt.submit'), tool: n('tool.call'), step: n('turn.step'), ag: n('agent.spawn'), cmp: n('session.compact'), end: n('session.end'), cmd: n('command.run') }
  await w.measure({ percent: 50 })
  const id = await w.turnStart()
  await w.call('Read', { file_path: `${REPO}/a.ts` }, { readOnly: true })
  await w.step({ answer: 'x' })
  await w.turnComplete(id)
  await w.submit('hi')
  await w.spawnAgent({ model: 'haiku' })
  await w.E.session.compact({ trigger: 'manual', messages: [{ role: 'user', text: 'hi', toolUses: [] }] })
  await w.E.command.run({ command: 'not-ours', args: '', origin: { kind: 'user' }, presentation: 'text' })
  await w.E.session.end({ reason: 'other' })
  await w.clock.settle()
  expect(n('session.measure')).toBe(before.m + 1)
  expect(n('turn.start')).toBe(before.ts + 1)
  expect(n('turn.complete')).toBe(before.tc + 1)
  expect(n('prompt.submit')).toBe(before.ps + 1)
  expect(n('tool.call')).toBe(before.tool + 1)
  expect(n('turn.step')).toBe(before.step + 1)
  expect(n('agent.spawn')).toBe(before.ag + 1)
  expect(n('session.compact')).toBe(before.cmp + 1)
  expect(n('command.run')).toBe(before.cmd + 1)
  expect(n('session.end')).toBe(before.end + 1)
})

test('C28b a failing internal read (spec file unreadable) does not change the tool result', async ($, on) => {
  const w = await world($, on)
  const out = { type: 'create', filePath: `${REPO}/docs/plans/x.md` }
  // file is NOT put in the virtual fs: the plugin's fs.read is refused
  const res = await w.call('Write', { file_path: `${REPO}/docs/plans/x.md`, content: '- [ ] a' }, { result: out })
  expect(res.result).toEqual(out)
})

test('C28c malformed tool input does not change the tool result', async ($, on) => {
  const w = await world($, on)
  const out = { stdout: 'fine', stderr: '', interrupted: false }
  const res = await w.call('Bash', { command: 12345 as unknown as string }, { result: out })
  expect(res.result).toEqual(out)
  const res2 = await w.call('Read', { file_path: null as unknown as string }, { result: { x: 1 } })
  expect(res2.result).toEqual({ x: 1 })
})

test('C28d malformed session.measure payload still reaches the engine and the Bash result is unchanged', async ($, on) => {
  const w = await world($, on)
  await w.E.session.measure({ context: undefined, rateLimits: undefined, changed: [] })
  const out = { stdout: 'ok', stderr: '', interrupted: false }
  const res = await w.bash('ls', { result: out })
  expect(res.result).toEqual(out)
  expect((w.seen['session.measure'] ?? []).length).toBe(1)
})
