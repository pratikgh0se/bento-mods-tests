import { test, expect } from 'claude-code/testing'
import { world, SURFACES, REPO, disallowedIn, norm, textOf, PLUGIN } from './_harness'

// f25b: a render hook makes only state.get / clock.now / ui.resolve calls (conventions 3.1a) and reads its state after `next`.

for (const surface of SURFACES) {
  test(`F25 band render of a running turn calls only state.get / clock.now / ui.resolve [${surface}]`, async ($, on) => {
    const w = await world($, on)
    await w.turnStart()
    await w.call('Read', { file_path: `${REPO}/a.ts` }, { readOnly: true })
    await w.call('TodoWrite', { todos: [{ content: 'a', status: 'completed', activeForm: 'a' }, { content: 'b', status: 'in_progress', activeForm: 'Doing b' }] })
    const { text, calls } = await w.renderOnce(surface)
    expect(text).toContain('RESEARCH')
    expect(calls, 'recorder is live').toContain('ui.render')
    expect(disallowedIn(calls), 'a render may only read state, the clock and ui.resolve').toEqual([])
  })

  test(`F25 band render with a focus timer and a pending heads-up still calls only state.get / clock.now / ui.resolve [${surface}]`, async ($, on) => {
    const w = await world($, on)
    await w.cmd('focus', 'start 25')
    await w.hotWeekly()
    await w.turnStart()
    await w.bash('npm test')
    const { calls } = await w.renderOnce(surface)
    expect(disallowedIn(calls)).toEqual([])
    expect(calls.length).toBeLessThanOrEqual(10)
  })

  test(`F25 idle band render (no turn) makes no forbidden call and at most 10 host calls [${surface}]`, async ($, on) => {
    const w = await world($, on)
    const { calls } = await w.renderOnce(surface, { isWorking: false })
    expect(disallowedIn(calls)).toEqual([])
    expect(calls.length).toBeLessThanOrEqual(10)
  })
}

test('F25 convoy: a phase change while a slow hook beneath holds the dispatch shows in the row that settles, and the phase is read after next', async ($, on) => {
  const w = await world($, on, { slowRenderMs: 2000 })
  await w.turnStart()
  await w.call('Read', { file_path: `${REPO}/a.ts` }, { readOnly: true })
  const E = w.E
  w.renderLog.calls = []
  w.renderLog.trace = []
  w.renderLog.on = true
  const pending = E.ui.mount({
    plugin: PLUGIN, surface: 'terminal', component: 'AbovePrompt',
    props: { hasSurvey: false, isWorking: true, maxRows: 6, bodyColumns: 160, scroll: {}, view: {} },
  })
  // the slow hook is mid-flight (1 s of its 2 s): the tool event moves the phase to BUILD
  await w.clock.advance(1000)
  w.renderLog.on = false // reads made by the tool hook are not the render dispatch's
  await w.call('Edit', { file_path: `${REPO}/a.ts`, old_string: 'a', new_string: 'b' })
  w.renderLog.on = true
  await w.clock.advance(1500)
  const ui = await pending
  const text = norm(textOf(await ui.drawn()))
  const trace = [...w.renderLog.trace]
  w.renderLog.on = false
  await ui.unmount()
  expect(text).toContain('▶BUILD')
  expect(text).not.toContain('▶RESEARCH')
  // the plugin read its phase after the slow beneath hook answered
  const end = trace.indexOf('bottom-end')
  expect(end, 'the slow hook answered').toBeGreaterThanOrEqual(0)
  const lastNowRead = trace.reduce((acc, x, i) => (x.startsWith('state.get:awareness.') ? i : acc), -1)
  expect(lastNowRead, 'awareness read some of its state while drawing').toBeGreaterThanOrEqual(0)
  expect(lastNowRead).toBeGreaterThan(end)
})
