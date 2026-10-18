// Statements 8 and 9: Coach toast, re-arm, peer gap, quiet modes.

const TOAST_RE = /^COMPACT · .{1,120}Run \/handoff\.$/

async function setHot(w: W, hot: boolean): Promise<void> {
  // hot: cold (+3) + no running agents (+2) = 5 (>= strongAt); low: warm + a running agent = 0
  w.S.agents = hot ? [] : [agentInfo('agent-run-1')]
  await w.peer('usage', 'cache', cacheView(hot ? 'cold' : 'warm', w.now()))
}
async function tick(w: W): Promise<void> {
  // two measure/turn.complete rounds so an agent refresh and the offer both happen whichever order the plugin uses
  await w.measure()
  await w.complete()
  await w.measure()
  await w.complete()
}

t('C08 first transition to score >= 5 raises exactly one toast; staying raises none; second episode within 20 min none', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'warm', phase: 'build', agents: 1 }) // score 0
  await tick(w)
  expect(w.S.toasts.length).toBe(0)

  await setHot(w, true) // t = 0
  await tick(w)
  expect(w.S.toasts.length).toBe(1)
  const text = w.S.toasts[0].text
  expect(text).toMatch(TOAST_RE)
  expect(text.length).toBeLessThanOrEqual(140)
  expect(text).toContain('350k')

  await tick(w) // staying >= 5
  await w.advance(61_000)
  await tick(w)
  expect(w.S.toasts.length).toBe(1)

  await w.advance(2 * MIN)
  await setHot(w, false) // re-arm: score falls below 3
  await tick(w)
  await w.advance(5 * MIN)
  await setHot(w, true) // second episode, ~8 min after the first toast
  await tick(w)
  await w.advance(10 * MIN)
  await tick(w)
  expect(w.S.toasts.length).toBe(1)
})

t('C08 a new episode after toastMinGapMin (20 min) raises a second toast', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'warm', phase: 'build', agents: 1 })
  await setHot(w, true)
  await tick(w)
  expect(w.S.toasts.length).toBe(1)
  await setHot(w, false)
  await tick(w)
  await w.advance(22 * MIN)
  await setHot(w, true)
  await tick(w)
  await w.advance(2 * MIN)
  expect(w.S.toasts.length).toBe(2)
  expect(w.S.toasts[1].text).toMatch(TOAST_RE)
})

t('C08 option coach.toast=false raises none', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'warm', phase: 'build', agents: 1 })
  await setHot(w, true)
  await tick(w)
  await w.advance(5 * MIN)
  expect(w.S.toasts.length).toBe(0)
}, { options: { 'coach_toast': false } })

t('C08 no toast while a handoff is in progress', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'warm', phase: 'build', agents: 1 })
  await w.cmd('handoff', 'foo') // state writing
  await setHot(w, true)
  await w.measure()
  await w.advance(5 * MIN)
  expect(w.S.toasts.length).toBe(0)
})

// ---- statement 9 ----
for (const [plugin, key, mk] of [
  ['dev', 'toast', (now: number) => ({ lastShownAt: now - 10_000, shown: 1, held: 0 })],
  ['awareness', 'headsup', (now: number) => ({ lastShownAt: now - 10_000, queued: [], shown: 1 })],
] as const) {
  t(`C09 peer gap: ${plugin}.${key}.lastShownAt = now-10s queues the toast to now+50s`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ cache: 'warm', phase: 'build', agents: 1 })
    await w.peer(plugin, key, mk(w.now()))
    await setHot(w, true)
    await tick(w)
    expect(w.S.toasts.length).toBe(0)
    await w.advance(40_000) // now+40s
    expect(w.S.toasts.length).toBe(0)
    await w.advance(12_000) // now+52s
    expect(w.S.toasts.length).toBe(1)
    expect(w.S.toasts[0].text).toMatch(TOAST_RE)
  })
}

t('C09 awareness.focus.phase = focus: no toast', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'warm', phase: 'build', agents: 1 })
  await w.peer('awareness', 'focus', { phase: 'focus', count: 1, ofTotal: 4 })
  await setHot(w, true)
  await tick(w)
  await w.advance(3 * MIN)
  expect(w.S.toasts.length).toBe(0)
})

t('C09 headsup.mutedUntil in the future: no toast', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'warm', phase: 'build', agents: 1 })
  await w.peer('awareness', 'headsup', { mutedUntil: w.now() + 60 * MIN, queued: [], shown: 0 })
  await setHot(w, true)
  await tick(w)
  await w.advance(3 * MIN)
  expect(w.S.toasts.length).toBe(0)
})

t('C09 compact.coach.lastShownAt is set when a toast is shown', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'warm', phase: 'build', agents: 1 })
  await setHot(w, true)
  await tick(w)
  expect(w.S.toasts.length).toBe(1)
  const c = await w.state('coach')
  expect(typeof c.lastShownAt).toBe('number')
  expect(Math.abs(c.lastShownAt - w.S.toasts[0].at)).toBeLessThan(5_000)
})
