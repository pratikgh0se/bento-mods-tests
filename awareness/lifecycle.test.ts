// Round 2 contract: REPORT while streaming, Long Command Timer chip lifecycle, clear paths.
// Written from specs/awareness.md (incl. the 2026-10-12 REPORT clarification) and public events only.
import { test, expect } from 'claude-code/testing'
import { world, SURFACES, REPO } from './_harness'
import type { World } from './_harness'

const CLEAR = ['▶', 'RESEARCH', 'BUILD', 'VERIFY', 'REPORT', 'now:', '⏱']

/** Parses the chip `⏱ <exe> mm:ss` out of band text; undefined when no chip. */
function chip(t: string): { exe: string; secs: number } | undefined {
  const m = /⏱\s*(\S+)\s+(\d{2,}):(\d{2})/.exec(t)
  return m ? { exe: m[1]!, secs: Number(m[2]) * 60 + Number(m[3]) } : undefined
}

async function rowGone(w: World): Promise<void> {
  for (const surface of SURFACES) {
    for (const isWorking of [false, true]) {
      const t = await w.band(surface, { isWorking }, false)
      for (const bad of CLEAR) expect(t, `${surface} isWorking=${isWorking}`).not.toContain(bad)
    }
  }
}

/** A main thread that already used Read, Edit and Bash pytest. */
async function earlierSteps(w: World): Promise<void> {
  await w.call('Read', { file_path: `${REPO}/a.py` }, { readOnly: true })
  await w.call('Edit', { file_path: `${REPO}/a.py`, old_string: 'a', new_string: 'b' })
  await w.bash('pytest -q')
}

// ---- REPORT while streaming ----
test('R01 text-only step: REPORT and "now: Writing the report" as soon as the first non-empty text chunk is delivered; earlier chips stay visited', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  await earlierSteps(w)
  const before = await w.bandBoth()
  expect(before).toContain('▶VERIFY')
  expect(before).not.toContain('▶REPORT')
  const st = w.streamStep({ answer: 'All done.' })
  const mid0 = await w.bandBoth()
  expect(mid0).not.toContain('▶REPORT')
  await st.text('All')
  const mid = await w.bandBoth()
  expect(mid).toContain('▶REPORT')
  expect(mid).toContain('now: Writing the report')
  expect(mid).toContain('▪RESEARCH')
  expect(mid).toContain('▪BUILD')
  expect(mid).toContain('▪VERIFY')
  await st.text(' done.')
  expect(await w.bandBoth()).toContain('▶REPORT')
  await st.end()
  const after = await w.bandBoth()
  expect(after).toContain('▶REPORT')
  expect(after).toContain('▪VERIFY')
})

test('R01b an empty text chunk does not make REPORT current', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  await earlierSteps(w)
  const st = w.streamStep()
  await st.text('')
  const t = await w.bandBoth()
  expect(t).toContain('▶VERIFY')
  expect(t).not.toContain('▶REPORT')
  await st.end()
})

test('R02 a step that streams text then a tool call ends with the earlier phase current, not REPORT', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  await earlierSteps(w)
  const st = w.streamStep({ toolUses: [{ name: 'Read', input: { file_path: `${REPO}/b.py` } }] })
  await st.text('Let me check the file.')
  expect(await w.bandBoth()).toContain('▶REPORT')
  await st.tool('Read', { file_path: `${REPO}/b.py` })
  await st.end()
  const t = await w.bandBoth()
  expect(t).not.toContain('▶REPORT')
  expect(t).toContain('▶VERIFY')
  expect(t).not.toContain('now: Writing the report')
})

test('R03 a subagent step that streams text never changes the phase', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  await w.call('Read', { file_path: `${REPO}/a.py` }, { readOnly: true })
  const st = w.streamStep({ agentId: 'agent-1' })
  await st.text('Subagent report text.')
  const t = await w.bandBoth()
  expect(t).toContain('▶RESEARCH')
  expect(t).not.toContain('▶REPORT')
  expect(t).not.toContain('Writing the report')
  await st.end()
  const t2 = await w.bandBoth()
  expect(t2).toContain('▶RESEARCH')
  expect(t2).not.toContain('▶REPORT')
})

test('R04 after turn.complete the phase row is gone, even when REPORT was current', async ($, on) => {
  const w = await world($, on)
  const id = await w.turnStart()
  await earlierSteps(w)
  const st = w.streamStep({ answer: 'Done.' })
  await st.text('Done.')
  await st.end()
  expect(await w.bandBoth()).toContain('▶REPORT')
  await w.turnComplete(id)
  await rowGone(w)
})

test('R04b turn.complete in the middle of a streaming text step clears the row', async ($, on) => {
  const w = await world($, on)
  const id = await w.turnStart()
  await earlierSteps(w)
  const st = w.streamStep({ answer: 'Partial' })
  await st.text('Partial')
  expect(await w.bandBoth()).toContain('▶REPORT')
  await w.turnComplete(id)
  await rowGone(w)
  await st.end()
  await rowGone(w)
})

// ---- Long command lifecycle ----
test('R10 130 s Bash: chip at 10 s counting up, one COMMAND toast at 120 s, chip gone within 2 s of the return, DONE toast offered', { timeoutMs: 180000 }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.turnStart()
  const out = { stdout: 'ok', stderr: '', interrupted: false }
  const p = w.bash('npm test --token=SECRET123', { delayMs: 130000, result: out })
  await w.clock.settle()
  await w.elapse(5)
  expect(chip(await w.band('desktop'))).toBeUndefined()
  await w.elapse(6) // t = 11 s
  const c1 = chip(await w.band('desktop'))
  expect(c1).toBeDefined()
  expect(c1!.exe).toBe('npm')
  expect(c1!.secs).toBeGreaterThanOrEqual(10)
  expect(c1!.secs).toBeLessThanOrEqual(12)
  await w.elapse(60) // t = 71 s
  const c2 = chip(await w.band('desktop'))
  expect(c2).toBeDefined()
  expect(c2!.secs).toBeGreaterThanOrEqual(70)
  expect(c2!.secs).toBeLessThanOrEqual(72)
  expect(w.toastsLike('COMMAND')).toHaveLength(0)
  await w.elapse(49) // t = 120 s: toast edge
  await w.elapse(1.5)
  expect(w.toastsLike('COMMAND')).toHaveLength(1)
  await w.elapse(8) // t = 129.5 s, still running
  expect(chip(await w.band('desktop'))).toBeDefined()
  expect(w.toastsLike('COMMAND')).toHaveLength(1)
  await w.elapse(2) // t = 131.5 s: returned at 130 s
  const res = await p
  expect(res.result).toEqual(out)
  expect(chip(await w.band('desktop', {}, false))).toBeUndefined()
  expect(await w.band('desktop', {}, false)).not.toContain('⏱')
  await w.elapse(70)
  const done = w.toasts.find((t) => t.text.includes('DONE'))
  expect(done).toBeDefined()
  expect(done!.text).toContain('npm')
  expect(done!.text).not.toContain('SECRET123')
  expect(w.toastsLike('COMMAND · 2')).toHaveLength(1)
})

test('R10b the chip shows the same text on terminal and desktop and never the arguments', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  const p = w.bash('pytest -q --token=SECRET123', { delayMs: 60000 })
  await w.clock.settle()
  await w.elapse(20)
  const t = await w.bandBoth()
  expect(chip(t)?.exe).toBe('pytest')
  expect(t).not.toContain('SECRET123')
  expect(t).not.toContain('--token')
  await w.elapse(45)
  await p
})

test('R11 turn.complete with the Bash result never arriving (call hangs): phase row and chip are gone', async ($, on) => {
  const w = await world($, on)
  const id = await w.turnStart()
  await w.call('Edit', { file_path: `${REPO}/a.py`, old_string: 'a', new_string: 'b' })
  w.bash('make dist', { hang: true }).catch(() => {})
  await w.clock.settle()
  await w.elapse(30)
  expect(chip(await w.bandBoth())).toBeDefined()
  await w.turnComplete(id)
  await rowGone(w)
  await w.elapse(200)
  await rowGone(w)
})

test('R11b interrupt: the Bash call rejects (aborted), then turn.complete: phase row and chip are gone', async ($, on) => {
  const w = await world($, on)
  const id = await w.turnStart()
  await w.call('Edit', { file_path: `${REPO}/a.py`, old_string: 'a', new_string: 'b' })
  const p = w.bash('make dist', { delayMs: 40000, reject: 'aborted' })
  p.catch(() => {})
  await w.clock.settle()
  await w.elapse(25)
  expect(chip(await w.bandBoth())).toBeDefined()
  await w.elapse(20)
  await expect(p).rejects.toThrow()
  await w.turnComplete(id)
  await rowGone(w)
})

test('R11c turn.complete while the command is still running (call finishes later): row gone and the chip does not come back', async ($, on) => {
  const w = await world($, on)
  const id = await w.turnStart()
  const p = w.bash('make dist', { delayMs: 90000 })
  await w.clock.settle()
  await w.elapse(30)
  expect(chip(await w.bandBoth())).toBeDefined()
  await w.turnComplete(id)
  await rowGone(w)
  await w.elapse(70)
  await p
  await rowGone(w)
})

test('R12 prompt.submit while a command chip shows removes the chip', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  w.bash('make dist', { hang: true }).catch(() => {})
  await w.clock.settle()
  await w.elapse(30)
  expect(chip(await w.bandBoth())).toBeDefined()
  await w.submit('next task')
  expect(await w.band('terminal', {}, false)).not.toContain('⏱')
  expect(await w.band('desktop', {}, false)).not.toContain('⏱')
})

test('R12b turn.start while a command chip shows removes the chip', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  w.bash('make dist', { hang: true }).catch(() => {})
  await w.clock.settle()
  await w.elapse(30)
  expect(chip(await w.bandBoth())).toBeDefined()
  await w.turnStart()
  expect(await w.band('terminal', {}, false)).not.toContain('⏱')
  expect(await w.band('desktop', {}, false)).not.toContain('⏱')
})

test('R13 overlapping Bash calls never show the earlier one\'s chip', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  const a = w.bash('npm test', { delayMs: 80000 })
  await w.clock.settle()
  await w.elapse(20)
  const b = w.bash('make dist', { delayMs: 30000 })
  await w.clock.settle()
  await w.elapse(5) // A at 25 s, B at 5 s
  const t1 = await w.bandBoth()
  expect(t1).not.toContain('⏱ npm')
  await w.elapse(20) // B at 25 s
  const t2 = await w.bandBoth()
  expect(t2).not.toContain('⏱ npm')
  expect(chip(t2)?.exe).toBe('make')
  await w.elapse(10) // B returned at 30 s after its start; A still running
  await b
  await w.elapse(1.5)
  expect(await w.bandBoth()).not.toContain('⏱ make')
  await w.elapse(40)
  await a
})

test('R13b consecutive Bash calls: the finished one\'s chip is gone, the new one shows its own', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  const a = w.bash('npm test', { delayMs: 30000 })
  await w.clock.settle()
  await w.elapse(31)
  await a
  const b = w.bash('make dist', { delayMs: 60000 })
  await w.clock.settle()
  await w.elapse(5)
  expect(await w.bandBoth()).not.toContain('⏱ npm')
  await w.elapse(20)
  const t = await w.bandBoth()
  expect(t).not.toContain('⏱ npm')
  expect(chip(t)?.exe).toBe('make')
  expect(chip(t)!.secs).toBeLessThanOrEqual(27)
  await w.elapse(40)
  await b
  await w.elapse(1.5)
  expect(await w.bandBoth()).not.toContain('⏱')
})

test('R14 Bash with run_in_background shows no chip', async ($, on) => {
  const w = await world($, on)
  await w.turnStart()
  const p = w.bash('npm run dev', { input: { run_in_background: true }, delayMs: 60000 })
  await w.clock.settle()
  await w.elapse(30)
  expect(await w.bandBoth()).not.toContain('⏱')
  await w.elapse(40)
  await p
})

test('R15 a turn that ends right after a long foreground command leaves no BUILD or now: row', async ($, on) => {
  const w = await world($, on)
  const id = await w.turnStart()
  const p = w.bash('sleep 130', { delayMs: 130000 })
  await w.clock.settle()
  await w.elapse(131)
  await p
  await w.turnComplete(id)
  await rowGone(w)
  await w.elapse(5)
  await rowGone(w)
})

// ---- Failure in the clear paths ($ rejects for an abandoned hook frame) ----
test('R20 stale frame: $ calls after a 130 s Bash returns reject; the result is unchanged and turn.complete still clears row and chip', { timeoutMs: 180000 }, async ($, on) => {
  const w = await world($, on, { staleAfterSec: 60 })
  const id = await w.turnStart()
  const out = { stdout: 'ok', stderr: '', interrupted: false }
  const p = w.bash('make dist', { delayMs: 130000, result: out })
  await w.clock.settle()
  await w.elapse(131)
  const res = await p
  expect(res.result).toEqual(out)
  await w.turnComplete(id)
  await rowGone(w)
  await w.elapse(10)
  await rowGone(w)
})

test('R20b stale frame: the plugin recovers on the next turn (new phase and a short command behave normally)', { timeoutMs: 180000 }, async ($, on) => {
  const w = await world($, on, { staleAfterSec: 60 })
  const id = await w.turnStart()
  const p = w.bash('make dist', { delayMs: 130000 })
  await w.clock.settle()
  await w.elapse(131)
  await p
  await w.turnComplete(id)
  await w.submit('again')
  await w.turnStart()
  await w.call('Read', { file_path: `${REPO}/a.py` }, { readOnly: true })
  const t = await w.bandBoth()
  expect(t).toContain('▶RESEARCH')
  expect(t).not.toContain('⏱')
  const q = w.bash('npm test', { delayMs: 30000 })
  await w.clock.settle()
  await w.elapse(20)
  expect(chip(await w.bandBoth())?.exe).toBe('npm')
  await w.elapse(11)
  await q
  await w.elapse(1.5)
  expect(await w.bandBoth()).not.toContain('⏱')
})
