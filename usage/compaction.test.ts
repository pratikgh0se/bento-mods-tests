/* eslint-disable @typescript-eslint/no-explicit-any */
import { test, expect } from 'claude-code/testing'
import { SURFACES, T0, HOUR, DAY, rig } from './_kit'

const WINDOW = 1_000_000
const on_ = { autoCompactThreshold: 900_000, isAutoCompactEnabled: true }

for (const surface of SURFACES) {
  test(`C24 context 50%: no CTX text [${surface}]`, async ($, on) => {
    const r = rig($, on, { breakdown: on_ })
    await r.start()
    await r.measureContext(500_000, WINDOW)
    await r.measure({ five: [62, T0 + 2 * HOUR], seven: [71, T0 + 3 * DAY] })
    const b = await r.band(surface)
    expect(b).toContain('5H') // positive control: band is drawn
    expect(b).not.toContain('CTX')
  })

  test(`C24 context 78% with 12% to compact: CTX, 78%, "12% to compact" [${surface}]`, async ($, on) => {
    const r = rig($, on, { breakdown: on_ }) // toCompact = (900000-780000)/1e6*100 = 12
    await r.start()
    await r.measureContext(780_000, WINDOW)
    const b = await r.band(surface)
    expect(b).toContain('CTX')
    expect(b).toContain('78%')
    expect(b).toContain('12% to compact')
  })

  test(`C24 context 85% starts its chip with the warning sign [${surface}]`, async ($, on) => {
    const r = rig($, on, { breakdown: { autoCompactThreshold: 950_000, isAutoCompactEnabled: true } }) // toCompact 10
    await r.start()
    await r.measureContext(850_000, WINDOW)
    expect(await r.band(surface)).toContain('⚠ CTX')
  })

  test(`C24 context 93% starts its chip with the stop sign [${surface}]`, async ($, on) => {
    const r = rig($, on, { breakdown: { autoCompactThreshold: 950_000, isAutoCompactEnabled: true } }) // toCompact 2
    await r.start()
    await r.measureContext(930_000, WINDOW)
    expect(await r.band(surface)).toContain('⛔ CTX')
  })

  test(`C25 auto-compact off: no "to compact", says "auto-compact off" [${surface}]`, async ($, on) => {
    const r = rig($, on, { breakdown: { autoCompactThreshold: 900_000, isAutoCompactEnabled: false } })
    await r.start()
    await r.measureContext(780_000, WINDOW)
    const b = await r.band(surface)
    expect(b).not.toContain('to compact')
    expect(b).toContain('auto-compact off')
  })

  test(`C26 after session.compact 91 -> 23: COMPACTED chip for 60 s, then gone; x1 counter appears [${surface}]`, async ($, on) => {
    const r = rig($, on, { breakdown: on_ })
    await r.start()
    await r.measureContext(910_000, WINDOW)
    await r.compact(910_000, 230_000)
    await r.measureContext(230_000, WINDOW)
    expect(await r.band(surface)).toContain('COMPACTED 91% → 23%')
    await r.advance(61_000)
    expect(await r.band(surface)).not.toContain('COMPACTED')
    await r.measureContext(700_000, WINDOW) // back above showFrom (60)
    const b = await r.band(surface)
    expect(b).toContain('CTX')
    expect(b).toContain('×1')
  })
}
