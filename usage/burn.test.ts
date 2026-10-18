/* eslint-disable @typescript-eslint/no-explicit-any */
import { test, expect } from 'claude-code/testing'
import { SURFACES, T0, MIN, HOUR, DAY, rig, formatWhen, whenWithin1Min, norm, cellWidth, countOf, samplesLen } from './_kit'

const meters = (band: string) => {
  const five = /5H\s+([█░]{12})\s+62%/.exec(band)
  const seven = /7D\s+([█░]{12})\s+71%/.exec(band)
  return { five: five?.[1] ?? '', seven: seven?.[1] ?? '' }
}

for (const surface of SURFACES) {
  test(`C01a no session.measure yet: band has no 5H [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    expect(await r.band(surface)).not.toContain('5H')
    // positive control: the same rig does show the burn row once a reading arrives
    await r.measure({ five: [62, T0 + 2 * HOUR], seven: [71, T0 + 3 * DAY] })
    expect(await r.band(surface)).toContain('5H')
  })

  test(`C01b rateLimits [] shows "No plan limits reported" [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.measure({ raw: [] })
    expect(await r.band(surface)).toContain('No plan limits reported')
  })

  test(`C02 five 62% / seven 71%: labels and percents [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.measure({ five: [62, T0 + 2 * HOUR], seven: [71, T0 + 3 * DAY] })
    const b = await r.band(surface)
    for (const t of ['5H', '62%', '7D', '71%']) expect(b).toContain(t)
  })
}

test('C02 meters: 5H has 7 filled + 5 empty, 7D has 9 filled + 3 empty (terminal)', async ($, on) => {
  const r = rig($, on)
  await r.start()
  await r.measure({ five: [62, T0 + 2 * HOUR], seven: [71, T0 + 3 * DAY] })
  const m = meters(await r.band('terminal'))
  expect(countOf(m.five, '█')).toBe(7)
  expect(countOf(m.five, '░')).toBe(5)
  expect(countOf(m.seven, '█')).toBe(9)
  expect(countOf(m.seven, '░')).toBe(3)
})

for (const surface of SURFACES) {
  test(`C03 seven_day 71% with 4 days elapsed: HOT, weekly limit, hit time within 1 min [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    const resets = T0 + 3 * DAY
    await r.measure({ seven: [71, resets] })
    const b = await r.band(surface)
    expect(b).toContain('HOT')
    expect(b).toContain('weekly limit')
    const hitAt = T0 + (29 / (71 / 4)) * DAY // 1 d 15 h 13 m
    expect(whenWithin1Min(hitAt).some(w => b.includes(w))).toBe(true)
    expect(b).toContain(formatWhen(resets))
  })

  test(`C03a projected exactly 100.0 is HOT [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    // 50% used with exactly half of 7 days elapsed: projected = 100.0
    await r.measure({ seven: [50, T0 + 3.5 * DAY] })
    const b = await r.band(surface)
    expect(b).toContain('HOT')
    expect(b).toContain('weekly limit')
  })

  test(`C03a projected 99.9 with plentyBelow 60 is ON PACE [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    const elapsed = Math.round((50 * 7 * DAY) / 99.9) // projected = 50 * 7d / elapsed = 99.9
    await r.measure({ seven: [50, T0 + 7 * DAY - elapsed] })
    const b = await r.band(surface)
    expect(b).toContain('ON PACE')
    expect(b).not.toContain('HOT')
  })

  test(`C03a burn.hotAt=120 turns the 100.0 case into ON PACE [${surface}]`, { options: { 'burn_hotAt': 120 } }, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.measure({ seven: [50, T0 + 3.5 * DAY] })
    const b = await r.band(surface)
    expect(b).toContain('ON PACE')
    expect(b).not.toContain('HOT')
  })

  test(`C04 five_hour 10% with 1 h elapsed: PLENTY ~50% [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.measure({ five: [10, T0 + 4 * HOUR] })
    const b = await r.band(surface)
    expect(b).toContain('PLENTY')
    expect(b).toContain('~50%')
  })

  test(`C05 five_hour 30% with 1 h elapsed: HOT, 5-hour limit [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.measure({ five: [30, T0 + 4 * HOUR] })
    const b = await r.band(surface)
    expect(b).toContain('HOT')
    expect(b).toContain('5-hour limit')
  })

  test(`C06 five_hour 5% with 5 min elapsed: LEARNING / Gathering pace [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.measure({ five: [5, T0 + 4 * HOUR + 55 * MIN] })
    const b = await r.band(surface)
    expect(b).toContain('LEARNING')
    expect(b).toContain('Gathering pace')
  })

  test(`C07 window at 100%: "reached" and the reset time [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    const resets = T0 + 2 * HOUR
    await r.measure({ five: [100, resets], seven: [40, T0 + 3 * DAY] })
    const b = await r.band(surface)
    expect(b).toContain('reached')
    expect(b).toContain(formatWhen(resets))
  })

  test(`C08 chip shows the worse window: five PLENTY + seven HOT -> HOT and weekly forecast [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.measure({ five: [10, T0 + 4 * HOUR], seven: [71, T0 + 3 * DAY] })
    const b = await r.band(surface)
    expect(b).toContain('HOT')
    expect(b).toContain('weekly limit')
    expect(b).not.toContain('Plenty left')
  })

  test(`C09 width 40 columns still shows 71%; width 24 shows carrot and a percent [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.measure({ five: [62, T0 + 2 * HOUR], seven: [71, T0 + 3 * DAY] })
    const b40 = await r.band(surface, { bodyColumns: 40 })
    expect(b40).toContain('71%')
    const b24 = await r.band(surface, { bodyColumns: 24 })
    expect(b24).toContain('🥕')
    expect(b24).toMatch(/\d+%/)
  })
}

test('C09 width 40 columns: no terminal line longer than 40 cells', async ($, on) => {
  const r = rig($, on)
  await r.start()
  await r.measure({ five: [62, T0 + 2 * HOUR], seven: [71, T0 + 3 * DAY] })
  const b = await r.band('terminal', { bodyColumns: 40 })
  for (const line of b.split('\n')) expect(cellWidth(line)).toBeLessThanOrEqual(40)
})

test('C10 a second measure with an unchanged reading adds no sample', async ($, on) => {
  const r = rig($, on)
  await r.start()
  const five = T0 + 2 * HOUR
  const seven = T0 + 3 * DAY
  await r.measure({ five: [62, five], seven: [71, seven] })
  await r.advance(5_000)
  await r.measure({ five: [62, five], seven: [71, seven] }) // identical reading
  await r.advance(5_000)
  await r.measure({ five: [62, five], seven: [71, seven] }) // identical again
  await r.advance(2 * MIN)
  await r.flush()
  const stored = await r.store('burn:samples:sid-usage-test')
  expect(stored).toBeDefined()
  expect(stored.v).toBe(1)
  // one changed reading in total -> exactly one sample
  expect(samplesLen(stored)).toBe(1)
})

for (const surface of SURFACES) {
  test(`C11 seven_day drops 71 -> 40 with the same resetsAt: LEARNING [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    const resets = T0 + 3 * DAY
    await r.measure({ seven: [71, resets] })
    await r.advance(MIN)
    await r.measure({ seven: [40, resets] })
    expect(await r.band(surface)).toContain('LEARNING')
  })
}

test('C12 /burn card has both percents, "resets" and "samples"', async ($, on) => {
  const r = rig($, on)
  await r.start()
  await r.measure({ five: [62, T0 + 2 * HOUR], seven: [71, T0 + 3 * DAY] })
  const res = await r.command('burn')
  const text = norm(res.text ?? '')
  expect(text).toContain('62')
  expect(text).toContain('71')
  expect(text).toContain('resets')
  expect(text).toContain('samples')
})

test('CX desktop alt equals terminal text (chip words normalised)', async ($, on) => {
  const r = rig($, on)
  await r.start()
  await r.measure({ five: [62, T0 + 2 * HOUR], seven: [71, T0 + 3 * DAY] })
  const chip = (s: string) => s.replace(/🔥 HOT|RUNNING HOT/g, '<chip>').replace(/\s+/g, ' ').trim()
  const term = await r.band('terminal')
  expect(term).toContain('5H')
  expect(chip(await r.band('desktop'))).toBe(chip(term))
})
