// Statements 3 and 4: payback line and the floor rule.

t('C03 warm payback line: pass $0.47, 8 turns (/coach)', async ($, on) => {
  const w = await world($, on)
  await w.scene({ tokens: 350_000, cache: 'warm' })
  const txt = await w.cmd('coach')
  expect(txt).toContain('$0.47')
  expect(txt).toMatch(/\b8 (warm )?turns/)
})

for (const surface of SURFACES) {
  t(`C03 warm chip says pays back ~8 turns (${surface})`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ tokens: 350_000, cache: 'warm' })
    expect(await w.band(surface)).toMatch(/\b8 (warm )?turns/)
  })
}

t('C03 cold payback line: pass $2.15 < next turn $2.80, pays back at once (/coach)', async ($, on) => {
  const w = await world($, on)
  await w.scene({ tokens: 350_000, cache: 'cold' })
  const txt = await w.cmd('coach')
  expect(txt).toContain('$2.15')
  expect(txt).toContain('$2.80')
  expect(txt).toContain('at once')
})

t('C03 passAssumesCacheHit=false prices the warm pass as C*W5: $2.15, 35 turns', async ($, on) => {
  // P = 1.75 + 0.08 + 0.32 = 2.15 ; n = ceil((2.15 - 0.008) / 0.062) = 35
  const w = await world($, on)
  await w.scene({ tokens: 350_000, cache: 'warm' })
  const txt = await w.cmd('coach')
  expect(txt).toContain('$2.15')
  expect(txt).toMatch(/\b35 (warm )?turns/)
}, { options: { 'coach_passAssumesCacheHit': false } })

// ---- statement 4: floor ----
for (const surface of SURFACES) {
  t(`C04 floor 54k + summary 4k beats target 40k: chip shows ->58k, saving on 58k (${surface})`, async ($, on) => {
    const w = await world($, on, { overhead: 54_000 })
    await w.scene({ tokens: 350_000, cache: 'warm' })
    const txt = await w.band(surface)
    expect(txt).toContain('→58k')
    expect(txt).toContain('save $0.06')
  })

  t(`C04 small overhead: target 40k wins and the chip shows ->40k (${surface})`, async ($, on) => {
    const w = await world($, on, { overhead: 20_000 })
    await w.scene({ tokens: 350_000, cache: 'warm' })
    const txt = await w.band(surface)
    expect(txt).toContain('→40k')
    expect(txt).not.toContain('→58k')
  })
}

t('C04 view records floorWon', async ($, on) => {
  const w = await world($, on, { overhead: 54_000 })
  await w.scene({ tokens: 350_000, cache: 'warm' })
  const c = await w.state('coach')
  expect(c.floorWon).toBe(true)
  expect(c.targetTokens).toBe(58_000)
})
