// /checkpoint status derived from the ref tip in a new or resumed session (specs/safety.md section 2).
import { test, expect } from 'claude-code/testing'
import { world, ALLOWED_GIT, TIP_TREE, MIN } from './harness'

async function ready($: any, on: any, o: Parameters<typeof world>[2] = {}) {
  const w = world($, on, o)
  await w.start()
  return w
}

test('R1 resumed session: status shows count, age and tree from the ref tip with no edits', async ($, on) => {
  const w = await ready($, on, { tip: { n: 7, agoMs: 3 * MIN, tree: TIP_TREE } })
  await w.clock.settle()
  const t = await w.cmd('checkpoint', '')
  expect(t).toContain('ref refs/checkpoints/')
  expect(t).toContain('7 saved')
  expect(t).toContain('last 3 min ago')
  expect(t).toContain('tree 9f3c2a1')
  expect(t).not.toContain('9f3c2a1b') // 7 characters only
  expect(t).not.toContain('none yet')
  expect(w.sim.violations).toEqual([])
})
test('R1 the age moves with the clock', async ($, on) => {
  const w = await ready($, on, { tip: { n: 7, agoMs: 3 * MIN, tree: TIP_TREE } })
  await w.clock.advance(2 * MIN)
  const t = await w.cmd('checkpoint', '')
  expect(t).toContain('7 saved')
  expect(t).toContain('last 5 min ago')
})
test('R2 no ref: "none yet" form and no tree', async ($, on) => {
  const w = await ready($, on)
  await w.clock.settle()
  const t = await w.cmd('checkpoint', '')
  expect(t).toContain('none yet')
  expect(t).toContain('ref refs/checkpoints/')
  expect(t).not.toMatch(/tree/i)
  expect(w.sim.violations).toEqual([])
})
test('R3 same session after one checkpoint: "1 saved · last 0s ago · tree <7 hex>"', async ($, on) => {
  const w = await ready($, on, { trees: ['abc1234def5678'] })
  await w.cycle()
  const t = await w.cmd('checkpoint', '')
  expect(t).toContain('1 saved · last 0s ago · tree abc1234')
  expect(t).toMatch(/1 saved · last 0s ago · tree [0-9a-f]{7}(?![0-9a-f])/)
})
test('R4 resumed session: the next checkpoint is numbered #8', async ($, on) => {
  const w = await ready($, on, { tip: { n: 7, agoMs: 3 * MIN, tree: TIP_TREE } })
  await w.cycle()
  expect(w.subs()).toContain('commit-tree')
  const msg = w.sim.msgs[w.sim.msgs.length - 1] ?? ''
  expect(msg).toContain('checkpoint abcd1234 #8 ')
  expect(msg).not.toContain('#1 ')
  const t = await w.cmd('checkpoint', '')
  expect(t).toContain('8 saved')
  expect(t).toContain('last 0s ago')
  expect(w.sim.violations).toEqual([])
})
test('R5 status in a resumed session makes no process call outside the allowed git list', async ($, on) => {
  const w = await ready($, on, { tip: { n: 7, agoMs: 3 * MIN, tree: TIP_TREE } })
  await w.clock.settle()
  w.procs.length = 0
  await w.cmd('checkpoint', '')
  for (const p of w.procs) {
    expect(p.argv[0]).toBe('git')
    expect(ALLOWED_GIT).toContain(w.sub(p.argv))
  }
  expect(w.sim.violations).toEqual([])
})
test('R5 start-up and a full cycle never leave the allowed git list', async ($, on) => {
  const w = await ready($, on, { tip: { n: 7, agoMs: 3 * MIN, tree: TIP_TREE } })
  await w.cycle()
  await w.cmd('checkpoint', 'list')
  await w.cmd('checkpoint', 'status')
  expect(w.sim.violations).toEqual([])
})
test('R6 a fresh tip within retention is not pruned at start', async ($, on) => {
  const w = await ready($, on, { tip: { n: 7, agoMs: 3 * MIN, tree: TIP_TREE } })
  await w.clock.settle()
  const del = w.gitCalls().filter(p => w.sub(p.argv) === 'update-ref' && p.argv.includes('-d'))
  expect(del.length).toBe(0)
})
