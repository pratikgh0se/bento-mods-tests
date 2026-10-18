/* eslint-disable @typescript-eslint/no-explicit-any */
// f25b: render does constant work (conventions 3.1a) and the savings total is published, not computed in render.
import { test, expect } from 'claude-code/testing'
import { SURFACES, T0, DAY, rig, usage, localDate, disallowedIn, lineWith } from './_kit'
import type { Surface } from './_kit'

const TODAY = localDate(T0)
const YESTERDAY = localDate(T0 - DAY)
const OLD = localDate(T0 - 7 * DAY)
const row = (saved: number) => ({ v: 1, saved, reads: 1, writes: 0, reqs: 1 })

/** 500 other-session day keys for today (0.01 each = 5.00), 50 stale ones (100 each, must not count), 200 burn sample lists. */
function seedStore(): Record<string, unknown> {
  const s: Record<string, unknown> = {}
  for (let i = 0; i < 500; i++) s[`cache:day:${TODAY}:other-${i}`] = row(0.01)
  for (let i = 0; i < 50; i++) s[`cache:day:${YESTERDAY}:old-${i}`] = row(100)
  for (let i = 0; i < 200; i++) s[`burn:samples:other-${i}`] = { v: 1, samples: [{ t: T0 - i * 1000, p: 10 }] }
  return s
}
const SEEDED_SUM = 5.0

const money = (text: string): number => {
  const m = /(-?)\$(-?)([\d,]+(?:\.\d+)?)/.exec(text)
  if (!m) return NaN
  return (m[1] || m[2] ? -1 : 1) * Number(m[3].replace(/,/g, ''))
}
const bandSeg = (t: string) => /saves[^]*?today/.exec(t)?.[0] ?? ''

async function warmRig($: any, on: any, seeded: boolean) {
  const r = rig($, on, { store: seeded ? seedStore() : {} })
  await r.start()
  await r.step({ usage: usage(1_000_000, 0, 1000, 100) })
  await r.advance(60_000)
  return r
}

for (const surface of SURFACES) {
  for (const kind of ['band', 'pane'] as const) {
    test(`F25 ${kind} render calls only state.get / clock.now / ui.resolve with 700 seeded keys [${surface}]`, async ($, on) => {
      const r = await warmRig($, on, true)
      const { text, calls } = await r.renderOnce(kind, surface as Surface)
      expect(text.length, 'something is drawn').toBeGreaterThan(0)
      // recorder self-check: the band's chain ends in the kit's own ui.render bottom, which must have been seen
      if (kind === 'band') expect(calls, 'recorder is live').toContain('ui.render')
      expect(calls.filter(c => c === 'store.keys' || c === 'store.get' || c === 'settings.read'), 'no store scan or settings read while drawing').toEqual([])
      expect(disallowedIn(calls), 'only state.get, clock.now, ui.resolve may be called by a render').toEqual([])
    })

    test(`F25 ${kind} render host-call count is at most 10 and unchanged when the store holds 0 keys instead of 700 [${surface}]`, async ($, on) => {
      const r = await warmRig($, on, true)
      expect(r.storeSize()).toBeGreaterThan(700)
      const seeded = await r.renderOnce(kind, surface as Surface)
      r.wipeStore()
      expect(r.storeSize()).toBe(0)
      const empty = await r.renderOnce(kind, surface as Surface)
      expect(seeded.calls.length).toBeLessThanOrEqual(10)
      expect(empty.calls.length).toBeLessThanOrEqual(10)
      expect(seeded.calls.length).toBe(empty.calls.length)
      // the figure comes from published state, so wiping the store changes nothing on screen
      expect(empty.text).toBe(seeded.text)
    })

    test(`F25 ${kind} savings total = seeded 5.00 + own savings, stale days excluded, after a step and 60 s [${surface}]`, async ($, on) => {
      const r = await warmRig($, on, true)
      const own: any = await r.store(`cache:day:${TODAY}:sid-usage-test`)
      expect(own, 'own day key written by the step').toBeTruthy()
      const t = (await r.renderOnce(kind, surface as Surface)).text
      const seg = kind === 'pane' ? lineWith(t, 'Saved by cache today') : bandSeg(t)
      expect(seg, 'a savings figure is drawn').not.toBe('')
      expect(Math.abs(money(seg) - (SEEDED_SUM + own.saved))).toBeLessThanOrEqual(0.011)
    })
  }

  test(`F25 band and pane show the same savings figure [${surface}]`, async ($, on) => {
    const r = await warmRig($, on, true)
    const pane = money(lineWith((await r.renderOnce('pane', surface as Surface)).text, 'Saved by cache today'))
    const band = money(bandSeg((await r.renderOnce('band', surface as Surface)).text))
    expect(Number.isFinite(pane)).toBe(true)
    expect(Math.abs(band - pane)).toBeLessThanOrEqual(0.011)
  })
}

test("F25 session.start deletes cache:day keys older than today and keeps today's", async ($, on) => {
  const store: Record<string, unknown> = {
    [`cache:day:${YESTERDAY}:a`]: row(1),
    [`cache:day:${YESTERDAY}:sid-usage-test`]: row(2),
    [`cache:day:${OLD}:b`]: row(3),
    [`cache:day:${TODAY}:other`]: row(4),
    'burn:samples:other': { v: 1, samples: [] },
  }
  const r = rig($, on, { store })
  await r.start()
  await r.advance(60_000)
  expect(await r.store(`cache:day:${YESTERDAY}:a`)).toBeUndefined()
  expect(await r.store(`cache:day:${YESTERDAY}:sid-usage-test`)).toBeUndefined()
  expect(await r.store(`cache:day:${OLD}:b`)).toBeUndefined()
  expect(await r.store(`cache:day:${TODAY}:other`)).toBeTruthy()
})

// Recorder self-check: a render hook that scans the store must be seen by the fake host.
const SCANNER = {
  name: 'zzscan',
  register(on: any) {
    on('ui.render', { component: 'AbovePrompt' }, async ($: any, e: any, next: any) => {
      await $.store.keys()
      return next(e)
    })
  },
}
test('F25 recorder: a render hook calling $.store.keys is recorded and flagged', { plugins: [SCANNER] } as any, async ($, on) => {
  const r = rig($, on, { store: seedStore() })
  await r.start()
  const { calls } = await r.renderOnce('band', 'terminal')
  expect(disallowedIn(calls)).toContain('store.keys')
})
