// Statements 5 and 7: moment score, verdicts, signals, idle return.

for (const surface of SURFACES) {
  t(`C05 cold + phase report + no agents = 7 -> GOOD MOMENT (${surface})`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ cache: 'cold', phase: 'report', agents: 0 })
    const c = await w.state('coach')
    expect(c.score).toBe(7)
    expect(c.verdict).toBe('good')
    const txt = await w.band(surface)
    expect(txt).toContain('GOOD MOMENT')
    expect(txt).toContain('no agents')
  })

  t(`C05 warm + phase build + 1 running agent -> NOT NOW (${surface})`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ cache: 'warm', phase: 'build', agents: 1 })
    const c = await w.state('coach')
    expect(c.score).toBe(0)
    expect(c.verdict).toBe('notnow')
    expect(JSON.stringify(c.reasons)).toContain('agents running')
    expect(await w.band(surface)).toContain('NOT NOW')
  })

  t(`C05 score 4 -> OK (${surface})`, async ($, on) => {
    // warm 0 + phase report 2 + no agents 2
    const w = await world($, on)
    await w.scene({ cache: 'warm', phase: 'report', agents: 0 })
    const c = await w.state('coach')
    expect(c.score).toBe(4)
    expect(c.verdict).toBe('ok')
    const txt = await w.band(surface)
    expect(txt).toMatch(/\bOK\b/)
    expect(txt).not.toContain('GOOD')
    expect(txt).not.toContain('NOT NOW')
  })

  t(`C05 absent usage atom adds 0 points and shows "cache ?" (${surface})`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ cache: null, phase: null, agents: 0 })
    const c = await w.state('coach')
    expect(c.score).toBe(2) // only "no running agents"
    expect(await w.band(surface)).toContain('cache ?')
  })
}

t('C05 cache expiring counts +3 like cold', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'expiring', phase: 'build', agents: 1 })
  expect((await w.state('coach')).score).toBe(3)
})

t('C05 cache unknown counts 0', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'unknown', phase: 'build', agents: 1 })
  expect((await w.state('coach')).score).toBe(0)
})

// phase-finished signals: each is worth +2; run with one running agent so "no agents" is not in play
const PHASE_SIGNALS: [string, Parameters<W['scene']>[0], number][] = [
  ['awareness.now.phase = report', { cache: 'warm', phase: 'report', agents: 1 }, 2],
  ['awareness.now.isComplete', { cache: 'warm', phase: 'build', nowExtra: { isComplete: true }, agents: 1 }, 2],
  ['specTotal > 0 and specDone === specTotal', { cache: 'warm', phase: 'build', nowExtra: { specTotal: 3, specDone: 3 }, agents: 1 }, 2],
  ['specDone < specTotal', { cache: 'warm', phase: 'build', nowExtra: { specTotal: 3, specDone: 2 }, agents: 1 }, 0],
  ['agents.mission.allDone true', { cache: 'warm', phase: 'build', allDone: true, agents: 1 }, 2],
  ['agents.mission.allDone false', { cache: 'warm', phase: 'build', allDone: false, agents: 1 }, 0],
]
for (const [label, opts, expected] of PHASE_SIGNALS) {
  t(`C05 phase signal: ${label} -> +${expected}`, async ($, on) => {
    const w = await world($, on)
    await w.scene(opts)
    expect((await w.state('coach')).score).toBe(expected)
  })
}

// agent statuses: pending, running and waiting count as running; completed does not
for (const status of ['pending', 'running', 'waiting']) {
  t(`C05 agent status ${status} removes the +2`, async ($, on) => {
    const w = await world($, on)
    w.S.agents = [agentInfo('a1', status)]
    await w.scene({ cache: 'warm', phase: 'build', agents: 0 })
    w.S.agents = [agentInfo('a1', status)]
    await w.complete() // agents are refreshed on turn.complete
    await w.measure()
    expect((await w.state('coach')).score).toBe(0)
  })
}
t('C05 a completed agent does not count as running (+2)', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'warm', phase: 'build', agents: 0 })
  w.S.agents = [agentInfo('a1', 'completed')]
  await w.complete()
  await w.measure()
  expect((await w.state('coach')).score).toBe(2)
})

// ---- statement 7: idle return ----
async function scoreAfterGap(w: W, gapMs: number): Promise<number> {
  await w.scene({ cache: 'warm', phase: 'build', agents: 1 }) // baseline score 0
  await w.submit('first')
  await w.complete()
  await w.advance(gapMs)
  w.S.agents = [agentInfo('agent-run-1')]
  await w.submit('second') // a turn starts after the gap
  await w.measure()
  return (await w.state('coach')).score
}
t('C07 a turn starting 11 min after the previous gives +1', async ($, on) => {
  expect(await scoreAfterGap(await world($, on), 11 * MIN)).toBe(1)
})
t('C07 a turn starting 9 min after the previous gives 0', async ($, on) => {
  expect(await scoreAfterGap(await world($, on), 9 * MIN)).toBe(0)
})
t('C07 a gap of exactly coach.idleReturnMin (10 min) gives +1', async ($, on) => {
  expect(await scoreAfterGap(await world($, on), 10 * MIN)).toBe(1)
})
t('C07 option coach.idleReturnMin=20: an 11 min gap gives 0', async ($, on) => {
  expect(await scoreAfterGap(await world($, on), 11 * MIN)).toBe(0)
}, { options: { 'coach_idleReturnMin': 20 } })
