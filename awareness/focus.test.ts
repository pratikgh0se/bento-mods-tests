import { test, expect } from 'claude-code/testing'
import { world, T0 } from './_harness'

// ---- C15 ----
test('C15 /focus start: band has FOCUS 25:00 and Focus 1 of 4; after 60 s 24:00 (both surfaces)', async ($, on) => {
  const w = await world($, on)
  await w.cmd('focus', 'start')
  const t1 = await w.bandBoth({ isWorking: false })
  expect(t1).toContain('FOCUS 25:00')
  expect(t1).toContain('Focus 1 of 4')
  await w.elapse(60)
  const t2 = await w.bandBoth({ isWorking: false })
  expect(t2).toContain('24:00')
})

// ---- C16 / C30: digest ----
test('C16 during FOCUS a trigger yields no toast; after the block exactly one digest with 1 notice', { timeoutMs: 120000 }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.cmd('focus', 'start')
  await w.measure({ percent: 85 })
  await w.elapse(10 * 60)
  expect(w.toasts).toHaveLength(0)
  expect(await w.cmd('headsup', 'status')).toContain('context')
  await w.elapse(15 * 60 + 5)
  await w.elapse(3 * 60)
  expect(w.toasts).toHaveLength(1)
  expect(w.toasts[0]!.text).toContain('While you focused')
  expect(w.toasts[0]!.text).toContain('1 notice')
  await w.elapse(10 * 60)
  expect(w.toasts).toHaveLength(1)
})

test('C16b digestAfterFocus=false: no digest', { options: { 'headsup_digestAfterFocus': false } }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.cmd('focus', 'start')
  await w.measure({ percent: 85 })
  await w.elapse(25 * 60 + 5)
  await w.elapse(5 * 60)
  expect(w.toasts).toHaveLength(0)
})

test('C30 context (fired twice) + pace during FOCUS: zero toasts, then one digest "2 notices" with both ids, nothing queued', { timeoutMs: 120000 }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.cmd('focus', 'start')
  const rl = [w.rate('seven_day', 71, 3 * 864e5)]
  await w.measure({ percent: 85, tokens: 20000, rateLimits: rl })
  await w.elapse(5)
  await w.measure({ percent: 65, tokens: 20000, rateLimits: rl })
  await w.elapse(5)
  await w.measure({ percent: 85, tokens: 20000, rateLimits: rl })
  await w.elapse(60)
  expect(w.toasts).toHaveLength(0)
  await w.elapse(25 * 60)
  await w.elapse(3 * 60)
  expect(w.toasts).toHaveLength(1)
  const t = w.toasts[0]!.text
  expect(t).toContain('While you focused: 2 notices')
  expect(t).toContain('context')
  expect(t).toContain('pace')
  await w.elapse(10 * 60)
  expect(w.toasts).toHaveLength(1)
})

test('C30b block end 20 s after a shown toast: digest waits until that toast + 60 s', { timeoutMs: 120000 }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.bigOutput(300000) // toast shown at t0
  expect(w.toasts).toHaveLength(1)
  const shownAt = w.toasts[0]!.at
  await w.elapse(1)
  await w.cmd('focus', 'start')
  await w.measure({ percent: 85 }) // held back during FOCUS
  await w.elapse(19)
  await w.cmd('focus', 'skip') // block ends at shownAt + 20 s
  await w.elapse(30) // shownAt + 50 s
  expect(w.toasts).toHaveLength(1)
  await w.elapse(11) // shownAt + 61 s
  expect(w.toasts).toHaveLength(2)
  expect(w.toasts[1]!.text).toContain('While you focused')
  expect(w.toasts[1]!.at - shownAt).toBeGreaterThanOrEqual(60000)
})

// ---- C17 ----
test('C17 block end: one notify POWER UP, one chime, band BEAN 05:00, count increments', { timeoutMs: 120000 }, async ($, on) => {
  const w = await world($, on)
  await w.cmd('focus', 'start')
  const before = (await w.state('focus'))?.count ?? 0
  await w.elapse(25 * 60)
  expect(w.notifies).toHaveLength(1)
  expect(w.notifies[0]!.text).toContain('POWER UP')
  expect(w.audio).toHaveLength(1)
  expect(JSON.stringify(w.audio[0])).toContain('sounds/done.wav')
  const t = await w.bandBoth({ isWorking: false })
  expect(t).toContain('BEAN 05:00')
  expect((await w.state('focus')).count).toBe(before + 1)
})

test('C17b after the 4th block the break is 15:00', { timeoutMs: 120000 }, async ($, on) => {
  const w = await world($, on)
  for (let i = 1; i <= 4; i++) {
    await w.cmd('focus', 'start')
    await w.elapse(25 * 60)
    if (i < 4) {
      expect(await w.bandBoth({ isWorking: false })).toContain('BEAN 05:00')
      await w.cmd('focus', 'skip') // end the short break
    }
  }
  expect(await w.bandBoth({ isWorking: false })).toContain('BEAN 15:00')
})

// ---- C18 ----
test('C18 pause freezes 10 min, resume continues, stop removes the segment, skip ends the phase', { timeoutMs: 120000 }, async ($, on) => {
  const w = await world($, on)
  await w.cmd('focus', 'start')
  await w.elapse(60)
  await w.cmd('focus', 'pause')
  expect(await w.bandBoth({ isWorking: false })).toContain('24:00')
  await w.elapse(10 * 60)
  const paused = await w.bandBoth({ isWorking: false })
  expect(paused).toContain('PAUSED')
  expect(paused).toContain('24:00')
  await w.cmd('focus', 'resume')
  expect(await w.bandBoth({ isWorking: false })).toContain('24:00')
  await w.elapse(60)
  expect(await w.bandBoth({ isWorking: false })).toContain('23:00')
  await w.cmd('focus', 'stop')
  const stopped = await w.bandBoth({ isWorking: false })
  expect(stopped).not.toContain('FOCUS')
  expect(stopped).not.toContain('PAUSED')
})

test('C18b skip ends the current phase (focus -> break)', async ($, on) => {
  const w = await world($, on)
  await w.cmd('focus', 'start')
  await w.elapse(30)
  await w.cmd('focus', 'skip')
  const t = await w.bandBoth({ isWorking: false })
  expect(t).toContain('BEAN')
  expect(t).not.toContain('FOCUS 2')
})

// ---- C19 ----
test('C19 store focus:state with endsAt in the future -> remaining time shown', async ($, on) => {
  const w = await world($, on, {
    start: false,
    store: { 'focus:state': { v: 1, phase: 'focus', endsAt: T0 + 10 * 60000, startedAt: T0 - 15 * 60000, count: 0, ofTotal: 4 } },
  })
  await w.start()
  const t = await w.bandBoth({ isWorking: false })
  expect(t).toContain('10:00')
  expect(t).toContain('FOCUS')
})

test('C19b store focus:state with endsAt 10 min ago -> idle, block not credited', async ($, on) => {
  const w = await world($, on, {
    start: false,
    store: { 'focus:state': { v: 1, phase: 'focus', endsAt: T0 - 10 * 60000, startedAt: T0 - 35 * 60000, count: 0, ofTotal: 4 } },
  })
  await w.start()
  const t = await w.bandBoth({ isWorking: false }) // may be '' (no segment)
  expect(t).not.toContain('FOCUS')
  expect(t).not.toContain('BEAN')
  const f = await w.state('focus')
  expect(f.phase).toBe('idle')
  expect(f.count).toBe(0)
  expect(w.notifies).toHaveLength(0)
})
