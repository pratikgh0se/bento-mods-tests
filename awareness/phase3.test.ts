// Round 3 contract: /nowdoing last-turn record, live /nowdoing, REPORT timing under streaming-write modes.
// Written from specs/awareness.md (incl. the 2026-10-12 /nowdoing and REPORT clarifications) and public events only.
import { test, expect } from 'claude-code/testing'
import { world, SURFACES, REPO } from './_harness'
import type { World } from './_harness'

const todo = (content: string, status: string, activeForm = content) => ({ content, status, activeForm })
const hhmm = (ms: number): string => {
  const d = new Date(ms)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
const lastLine = (out: string): string => out.split('\n').map((l) => l.trim()).find((l) => l.startsWith('last turn: ')) ?? ''

/** Read, Edit, Bash pytest, then a text-only step; completes the turn; returns the mocked ended time. */
async function pytestTurn(w: World): Promise<number> {
  const id = await w.turnStart()
  await w.call('Read', { file_path: `${REPO}/a.py` }, { readOnly: true })
  await w.call('Edit', { file_path: `${REPO}/a.py`, old_string: 'a', new_string: 'b' })
  await w.bash('pytest -q')
  await w.step({ answer: 'All done.', toolUses: [] })
  await w.elapse(7)
  const ended = w.clock.now()
  await w.turnComplete(id)
  return ended
}

test('N01 idle /nowdoing after Read, Edit, pytest, text-only step: "last turn: " with final phase, now: and ended HH:MM', async ($, on) => {
  const w = await world($, on)
  const ended = await pytestTurn(w)
  const out = await w.cmd('nowdoing')
  const line = lastLine(out)
  expect(line, out).not.toBe('')
  expect(line).toContain('REPORT')
  expect(line).toContain('now: ')
  const m = /ended (\d{2}:\d{2})/.exec(line)
  expect(m, line).not.toBeNull()
  expect(m![1]).toBe(hhmm(ended))
  expect(out).not.toContain('no phase yet')
})

test('N02 phase tool alone: exactly "last turn: BUILD · now: testing · ended HH:MM"', async ($, on) => {
  const w = await world($, on)
  const id = await w.turnStart()
  await w.call('mcp__awareness__phase', { phase: 'build', note: 'testing' })
  await w.elapse(3)
  const ended = w.clock.now()
  await w.turnComplete(id)
  const out = await w.cmd('nowdoing')
  expect(lastLine(out), out).toBe(`last turn: BUILD · now: testing · ended ${hhmm(ended)}`)
})

test('N03 a session with no turn yet prints "no phase yet"', async ($, on) => {
  const w = await world($, on)
  const out = await w.cmd('nowdoing')
  expect(out).toContain('no phase yet')
  expect(out).not.toContain('last turn')
})

test('N04 /nowdoing reset clears the last-turn record: next /nowdoing prints "no phase yet"', async ($, on) => {
  const w = await world($, on)
  await pytestTurn(w)
  expect(lastLine(await w.cmd('nowdoing'))).not.toBe('')
  await w.cmd('nowdoing', 'reset')
  const out = await w.cmd('nowdoing')
  expect(out).toContain('no phase yet')
  expect(out).not.toContain('last turn')
})

test('N05 a second turn replaces the previous last-turn line', async ($, on) => {
  const w = await world($, on)
  const id1 = await w.turnStart()
  await w.call('mcp__awareness__phase', { phase: 'build', note: 'testing' })
  await w.turnComplete(id1)
  expect(lastLine(await w.cmd('nowdoing'))).toContain('testing')
  await w.elapse(120)
  await w.submit('next task')
  const id2 = await w.turnStart()
  await w.call('mcp__awareness__phase', { phase: 'verify', note: 'checking results' })
  const ended = w.clock.now()
  await w.turnComplete(id2)
  const out = await w.cmd('nowdoing')
  expect(out.split('\n').filter((l) => l.includes('last turn: '))).toHaveLength(1)
  expect(lastLine(out)).toBe(`last turn: VERIFY · now: checking results · ended ${hhmm(ended)}`)
  expect(out).not.toContain('testing')
})

test('N06 with a TodoWrite checklist 3 of 5 complete the last-turn line contains "3/5 done"', async ($, on) => {
  const w = await world($, on)
  const id = await w.turnStart()
  await w.call('TodoWrite', {
    todos: [
      todo('one', 'completed'), todo('two', 'completed'), todo('three', 'completed'),
      todo('Review code', 'in_progress', 'Reviewing code'), todo('five', 'pending'),
    ],
  })
  await w.turnComplete(id)
  const line = lastLine(await w.cmd('nowdoing'))
  expect(line).toContain('last turn: ')
  expect(line).toContain('3/5 done')
})

test('N07 the last-turn record is never drawn in the band, and the phase row still clears at turn end', async ($, on) => {
  const w = await world($, on)
  await pytestTurn(w)
  for (const surface of SURFACES) {
    for (const isWorking of [false, true]) {
      const t = await w.band(surface, { isWorking }, false)
      expect(t).not.toContain('last turn')
      expect(t).not.toContain('▶')
      expect(t).not.toContain('now:')
    }
  }
})

test('N08 live /nowdoing during a turn prints "phase BUILD · now: Editing calc.py", not the last-turn line', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  await w.call('Edit', { file_path: `${REPO}/calc.py`, old_string: 'a', new_string: 'b' })
  const out = await w.cmd('nowdoing')
  expect(out).toContain('phase BUILD · now: Editing calc.py')
  expect(out).not.toContain('last turn')
  expect(out).not.toContain('no phase yet')
})

test('N09 live /nowdoing during a second turn shows the current phase, not the previous turn', async ($, on) => {
  const w = await world($, on)
  const id = await w.turnStart()
  await w.call('mcp__awareness__phase', { phase: 'verify', note: 'old note' })
  await w.turnComplete(id)
  await w.submit('again')
  await w.turnStart()
  await w.call('Edit', { file_path: `${REPO}/calc.py`, old_string: 'a', new_string: 'b' })
  const out = await w.cmd('nowdoing')
  expect(out).toContain('phase BUILD · now: Editing calc.py')
  expect(out).not.toContain('last turn')
  expect(out).not.toContain('old note')
})

// ---- REPORT timing, in every streaming-write mode ----
for (const mode of ['apply', 'drop', 'defer'] as const) {
  test(`T01[${mode}] first non-empty main text chunk: band shows ▶REPORT and "now: Writing the report" within 1 s, before the step ends`, async ($, on) => {
    const w = await world($, on, { streamWrites: mode })
    await w.turnStart()
    await w.call('Read', { file_path: `${REPO}/a.py` }, { readOnly: true })
    await w.call('Edit', { file_path: `${REPO}/a.py`, old_string: 'a', new_string: 'b' })
    await w.bash('pytest -q')
    const st = w.streamStep({ answer: 'All done.' })
    expect(await w.bandBoth()).not.toContain('▶REPORT')
    await st.text('All')
    await w.elapse(1)
    const mid = await w.bandBoth()
    expect(mid).toContain('▶REPORT')
    expect(mid).toContain('now: Writing the report')
    expect(mid).toContain('▪VERIFY')
    await st.text(' done.')
    expect(await w.bandBoth()).toContain('▶REPORT')
    await st.end()
    expect(await w.bandBoth()).toContain('▶REPORT')
  })

  test(`T02[${mode}] REPORT is visible immediately after the chunk (no elapse) on both surfaces`, async ($, on) => {
    const w = await world($, on, { streamWrites: mode })
    await w.turnStart()
    await w.call('Read', { file_path: `${REPO}/a.py` }, { readOnly: true })
    const st = w.streamStep()
    await st.text('Report begins')
    for (const surface of SURFACES) {
      const t = await w.band(surface)
      expect(t).toContain('▶REPORT')
      expect(t).toContain('now: Writing the report')
    }
    await st.end()
  })

  test(`T03[${mode}] a tool chunk later in the same step restores the earlier phase`, async ($, on) => {
    const w = await world($, on, { streamWrites: mode })
    await w.turnStart()
    await w.call('Read', { file_path: `${REPO}/a.py` }, { readOnly: true })
    await w.call('Edit', { file_path: `${REPO}/a.py`, old_string: 'a', new_string: 'b' })
    const st = w.streamStep({ toolUses: [{ name: 'Read', input: { file_path: `${REPO}/b.py` } }] })
    await st.text('Let me check.')
    expect(await w.bandBoth()).toContain('▶REPORT')
    await st.tool('Read', { file_path: `${REPO}/b.py` })
    const t = await w.bandBoth()
    expect(t).not.toContain('▶REPORT')
    expect(t).not.toContain('now: Writing the report')
    expect(t).toContain('▶BUILD')
    await st.end()
    const t2 = await w.bandBoth()
    expect(t2).not.toContain('▶REPORT')
    expect(t2).toContain('▶BUILD')
  })

  test(`T04[${mode}] thinking-only chunks and a subagent text step change nothing`, async ($, on) => {
    const w = await world($, on, { streamWrites: mode })
    await w.turnStart()
    await w.call('Read', { file_path: `${REPO}/a.py` }, { readOnly: true })
    const st = w.streamStep()
    await st.chunk({ kind: 'thinking', index: 0, text: 'Hmm, considering options' })
    await w.elapse(1)
    const t = await w.bandBoth()
    expect(t).toContain('▶RESEARCH')
    expect(t).not.toContain('▶REPORT')
    expect(t).not.toContain('Writing the report')
    await st.end()
    const sub = w.streamStep({ agentId: 'agent-1' })
    await sub.text('Subagent writing a lot of text')
    await w.elapse(1)
    const t2 = await w.bandBoth()
    expect(t2).toContain('▶RESEARCH')
    expect(t2).not.toContain('▶REPORT')
    await sub.end()
  })

  test(`T05[${mode}] after turn.complete the REPORT row is gone`, async ($, on) => {
    const w = await world($, on, { streamWrites: mode })
    const id = await w.turnStart()
    await w.call('Read', { file_path: `${REPO}/a.py` }, { readOnly: true })
    const st = w.streamStep({ answer: 'Done.' })
    await st.text('Done.')
    expect(await w.bandBoth()).toContain('▶REPORT')
    await st.end()
    await w.turnComplete(id)
    for (const surface of SURFACES) {
      for (const isWorking of [false, true]) {
        const t = await w.band(surface, { isWorking }, false)
        for (const bad of ['▶', 'REPORT', 'now:']) expect(t).not.toContain(bad)
      }
    }
  })
}

test('K01 plugin tool results are strings and the phase tool still sets the phase mid-turn', async ($, on) => {
  const w = await world($, on, { streamWrites: 'drop' })
  await w.turnStart()
  const res = await w.call('mcp__awareness__phase', { phase: 'verify', note: 'running the suite' })
  expect(typeof res.result).toBe('string')
  const t = await w.bandBoth()
  expect(t).toContain('▶VERIFY')
  expect(t).toContain('now: running the suite')
})
