import { test, expect } from 'claude-code/testing'
import { world, SURFACES, REPO } from './_harness'

const todo = (content: string, status: string, activeForm = content) => ({ content, status, activeForm })

// ---- C20 ----
test('C20 phases: none when idle; Read=RESEARCH; Edit=BUILD; npm test=VERIFY; text-only step=REPORT; prompt.submit resets', async ($, on) => {
  const w = await world($, on)
  for (const surface of SURFACES) {
    const idle = await w.band(surface, { isWorking: false }, false)
    expect(idle).not.toContain('RESEARCH')
  }
  await w.turnStart()
  await w.call('Read', { file_path: `${REPO}/a.ts` }, { readOnly: true })
  expect(await w.bandBoth()).toContain('▶RESEARCH')
  await w.call('Edit', { file_path: `${REPO}/a.ts`, old_string: 'a', new_string: 'b' })
  const b = await w.bandBoth()
  expect(b).toContain('▪RESEARCH')
  expect(b).toContain('▶BUILD')
  await w.bash('npm test')
  expect(await w.bandBoth()).toContain('▶VERIFY')
  await w.step({ answer: 'All done.', toolUses: [] })
  expect(await w.bandBoth()).toContain('▶REPORT')
  await w.submit('next')
  await w.turnStart()
  const r = await w.bandBoth()
  expect(r).not.toContain('▶')
  for (const p of ['RESEARCH', 'PLAN', 'BUILD', 'VERIFY', 'REPORT']) expect(r).toContain(`▫${p}`)
})

// ---- C21 ----
test('C21 subagent tool.call never changes phase or checklist', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  await w.call('Edit', { file_path: `${REPO}/a.ts`, old_string: 'a', new_string: 'b' }, { agentId: 'agent-1' })
  await w.bash('npm test', { agentId: 'agent-1' })
  await w.call('TodoWrite', { todos: [todo('x', 'completed'), todo('y', 'in_progress', 'Doing y')] }, { agentId: 'agent-1' })
  const t = await w.bandBoth()
  expect(t).not.toContain('▶')
  expect(t).not.toContain('%')
  expect(t).not.toContain('Doing y')
})

// ---- C22 ----
test('C22 Read of /a/b/c.ts shows "Reading c.ts", never the directory', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  await w.call('Read', { file_path: '/a/b/c.ts' }, { readOnly: true })
  const t = await w.bandBoth()
  expect(t).toContain('now: Reading c.ts')
  expect(t).not.toContain('/a/b')
})

// ---- C23 ----
test('C23 TodoWrite 5 todos, 3 done, 1 in progress -> 60% and now: Reviewing code', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  await w.call('TodoWrite', {
    todos: [
      todo('one', 'completed'), todo('two', 'completed'), todo('three', 'completed'),
      todo('Review code', 'in_progress', 'Reviewing code'), todo('five', 'pending'),
    ],
  })
  const t = await w.bandBoth()
  expect(t).toContain('60%')
  expect(t).toContain('now: Reviewing code')
})

// ---- C24 ----
test('C24 mcp__awareness__phase overrides phase and now; result is the string ok', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  const res = await w.call('mcp__awareness__phase', { phase: 'verify', note: 'running the suite' })
  expect(typeof res.result).toBe('string')
  expect(res.result).toBe('ok')
  const t = await w.bandBoth()
  expect(t).toContain('▶VERIFY')
  expect(t).toContain('now: running the suite')
})

test('C24c phase tool from a subagent leaves phase/checklist unchanged and returns a string', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  const res = await w.call('mcp__awareness__phase', { phase: 'verify', note: 'sub note' }, { agentId: 'agent-1' })
  expect(typeof res.result).toBe('string')
  const t = await w.bandBoth()
  expect(t).not.toContain('▶')
  expect(t).not.toContain('sub note')
})

test('C24d phase tool with only {phase:build} returns a string and sets BUILD', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  const res = await w.call('mcp__awareness__phase', { phase: 'build' })
  expect(typeof res.result).toBe('string')
  expect(await w.bandBoth()).toContain('▶BUILD')
})

test('C24e phase tool with an invalid phase does not throw and returns a string', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  const res = await w.call('mcp__awareness__phase', { phase: 'bogus' })
  expect(typeof res.result).toBe('string')
})

test('C24f a submitted /nowdoing keeps phase and now; /nowdoing reports them; a normal prompt still resets', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  await w.call('mcp__awareness__phase', { phase: 'build', note: 'wiring the widget' })
  await w.submit('/nowdoing')
  await w.turnStart()
  const t = await w.bandBoth()
  expect(t).toContain('▶BUILD')
  expect(t).toContain('now: wiring the widget')
  const out = await w.cmd('nowdoing')
  expect(out).toContain('BUILD')
  expect(out).toContain('wiring the widget')
  await w.submit('next task')
  await w.turnStart()
  const r = await w.bandBoth()
  expect(r).not.toContain('▶BUILD')
  expect(r).not.toContain('wiring the widget')
})

test('C24b the phase tool is registered by session.start', async ($, on) => {
  const w = await world($, on)
  const names = w.registeredTools.map((t: { name: string }) => t.name)
  expect(names.includes('phase') || names.includes('mcp__awareness__phase')).toBe(true)
})

// ---- C25 ----
test('C25 all todos complete -> "all 5 done" until the next prompt.submit, then the row is gone', async ($, on) => {
  const w = await world($, on)
  await w.call('TodoWrite', { todos: [1, 2, 3, 4, 5].map((n) => todo(`t${n}`, 'completed')) })
  const t = await w.bandBoth({ isWorking: false })
  expect(t).toContain('all 5 done')
  await w.submit('next task')
  for (const surface of SURFACES) {
    const after = await w.band(surface, { isWorking: false }, false)
    expect(after).not.toContain('all 5 done')
    expect(after).not.toContain('RESEARCH')
  }
})

// ---- C27 ----
test('C27 row hidden with hasSurvey, view.agentId, maxRows < 4; shown otherwise; inner tree kept', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  await w.call('Read', { file_path: `${REPO}/a.ts` }, { readOnly: true })
  for (const surface of SURFACES) {
    expect(await w.band(surface)).toContain('RESEARCH')
    expect(await w.band(surface, { hasSurvey: true }, false)).not.toContain('RESEARCH')
    expect(await w.band(surface, { view: { agentId: 'agent-1' } }, false)).not.toContain('RESEARCH')
    expect(await w.band(surface, { maxRows: 3 }, false)).not.toContain('RESEARCH')
  }
})

test('C27b the inner tree beneath is returned stacked above the row', async ($, on) => {
  const w = await world($, on, { inner: { type: 'Text', props: {}, children: ['INNER-BAND'] } })
  await w.turnStart()
  await w.call('Read', { file_path: `${REPO}/a.ts` }, { readOnly: true })
  for (const surface of SURFACES) {
    const t = await w.band(surface)
    expect(t).toContain('INNER-BAND')
    expect(t).toContain('RESEARCH')
    expect(t.indexOf('INNER-BAND')).toBeLessThan(t.indexOf('RESEARCH'))
    const hidden = await w.band(surface, { hasSurvey: true }, false)
    expect(hidden).toContain('INNER-BAND')
    expect(hidden).not.toContain('RESEARCH')
  }
})
