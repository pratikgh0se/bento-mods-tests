// f25b: a band render makes only state.get / clock.now / ui.resolve calls (conventions 3.1a) and a constant number of them.

for (const surface of SURFACES) {
  t(`F25 chip render (350k, warm cache) calls only state.get / clock.now / ui.resolve [${surface}]`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ tokens: 350_000 })
    const { text, calls } = await w.renderOnce(surface)
    expect(text).toContain('350k')
    expect(calls, 'recorder is live').toContain('ui.render')
    expect(disallowedIn(calls), 'a render may only read state, the clock and ui.resolve').toEqual([])
    expect(calls.length).toBeLessThanOrEqual(10)
  })

  t(`F25 chip render with a handoff in progress and agents running calls only state.get / clock.now / ui.resolve [${surface}]`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ tokens: 80_000, agents: 2, phase: 'build' })
    await w.cmd('handoff', 'foo')
    const { text, calls } = await w.renderOnce(surface)
    expect(text).toContain('HANDOFF writing')
    expect(disallowedIn(calls)).toEqual([])
    expect(calls.length).toBeLessThanOrEqual(10)
  })

  t(`F25 render with no chip (80k) is silent and makes no forbidden call [${surface}]`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ tokens: 80_000 })
    const { text, calls } = await w.renderOnce(surface)
    expect(text).not.toMatch(/CTX|GOOD|NOT NOW/)
    expect(disallowedIn(calls)).toEqual([])
  })

  t(`F25 render call count is unchanged after many measures and 3 more renders [${surface}]`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ tokens: 350_000 })
    const first = await w.renderOnce(surface)
    for (let i = 0; i < 20; i++) await w.setCtx(350_000 + i * 1000)
    await w.advance(60_000)
    const later = await w.renderOnce(surface)
    expect(later.calls.length).toBe(first.calls.length)
    expect(disallowedIn(later.calls)).toEqual([])
  })
}
