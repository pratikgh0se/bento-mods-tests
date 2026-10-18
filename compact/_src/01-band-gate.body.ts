// Statements 1 and 6: when the chip shows, and the saving gate.

for (const surface of SURFACES) {
  t(`C01 ctx 80k draws no chip (${surface})`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ tokens: 80_000 })
    const txt = await w.band(surface)
    expect(txt).not.toContain('80k')
    expect(txt).not.toMatch(/CTX|GOOD|NOT NOW/)
  })

  t(`C01 ctx 350k chip shows size, warm and cold cost, saving (${surface})`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ tokens: 350_000 })
    const txt = await w.band(surface)
    expect(txt).toContain('350k')
    expect(txt).toContain('$0.07')
    expect(txt).toContain('$2.80')
    expect(txt).toContain('save $0.06')
  })

  t(`C01 a handoff in progress draws the chip even below 100k (${surface})`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ tokens: 80_000 })
    await w.cmd('handoff', 'foo')
    const txt = await w.band(surface)
    expect(txt).toContain('HANDOFF writing')
  })
}

t('C01 gate: ctx below showFromTokens forces NOT NOW even with a perfect score', async ($, on) => {
  const w = await world($, on)
  await w.scene({ tokens: 80_000, cache: 'cold', phase: 'report', agents: 0 })
  const c = await w.state('coach')
  expect(c.verdict).toBe('notnow')
})

t('C01 option coach.showFromTokens moves the threshold', async ($, on) => {
  const w = await world($, on)
  await w.scene({ tokens: 150_000 })
  expect(await w.band('terminal')).toContain('150k')
}, { options: { 'coach_showFromTokens': 120000 } })

t('C01 option coach.showFromTokens 200000 hides a 150k chip', async ($, on) => {
  const w = await world($, on)
  await w.scene({ tokens: 150_000 })
  expect(await w.band('terminal')).not.toContain('150k')
}, { options: { 'coach_showFromTokens': 200000 } })

// ---- statement 6 ----
for (const surface of SURFACES) {
  t(`C06 saving per warm turn below minSavingUsd forces NOT NOW (${surface})`, async ($, on) => {
    // ctx 100k, target 98k: saving = 2,000 * 0.20 / 1e6 = $0.0004 < 0.02, although cold + report + no agents = 7
    const w = await world($, on)
    await w.scene({ tokens: 100_000, cache: 'cold', phase: 'report', agents: 0 })
    const c = await w.state('coach')
    expect(c.verdict).toBe('notnow')
    expect(await w.band(surface)).toContain('NOT NOW')
  }, { options: { 'coach_targetTokens': 98000 } })
}

// ---- F24: a gated NOT NOW shows why (reasons[0] and chip text right after NOT NOW) ----
for (const surface of SURFACES) {
  t(`F24 min-saving gate: reasons[0] "saving < $0.02 min", chip shows it after NOT NOW (${surface})`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ tokens: 100_000, cache: 'cold', phase: 'report', agents: 0 })
    const c = await w.state('coach')
    expect(c.verdict).toBe('notnow')
    expect(c.reasons[0]).toBe('saving < $0.02 min')
    expect(await w.band(surface)).toMatch(/NOT NOW\W+saving < \$0\.02 min/)
  }, { options: { 'coach_targetTokens': 98000 } })

  t(`F24 min-saving gate follows coach.minSavingUsd 0.05 (${surface})`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ tokens: 100_000, cache: 'cold', phase: 'report', agents: 0 })
    const c = await w.state('coach')
    expect(c.verdict).toBe('notnow')
    expect(c.reasons[0]).toBe('saving < $0.05 min')
    expect(await w.band(surface)).toMatch(/NOT NOW\W+saving < \$0\.05 min/)
  }, { options: { 'coach_targetTokens': 98000, 'coach_minSavingUsd': 0.05 } })

  t(`F24 handoff compacting: reasons[0] "compacting", chip shows it (${surface})`, async ($, on) => {
    const w = await world($, on, { compact: 'hang' })
    await w.scene()
    await w.toReady()
    await w.cmd('handoff', 'go')
    expect((await w.state('handoff')).state).toBe('compacting')
    const c = await w.state('coach')
    expect(c.verdict).toBe('notnow')
    expect(c.reasons[0]).toBe('compacting')
    expect(await w.band(surface)).toContain('compacting')
  })

  t(`F24 ungated NOT NOW (score < 3, saving above min) adds no gate text (${surface})`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ cache: 'warm', phase: 'build', agents: 1 })
    const c = await w.state('coach')
    expect(c.verdict).toBe('notnow')
    expect(JSON.stringify(c.reasons)).not.toMatch(/saving <|compacting|below/)
    const txt = await w.band(surface)
    expect(txt).toContain('NOT NOW')
    expect(txt).not.toMatch(/saving <|compacting|below/)
  })
}
