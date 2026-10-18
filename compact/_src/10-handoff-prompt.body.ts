// Statements 10 and 11: /handoff builds the prompt and never compacts by itself.

const AGENTS = [agentInfo('agent-aaa1', 'running', 'Typecheck sweep'), agentInfo('agent-bbb2', 'waiting', 'Docs pass')]

t('C10 /handoff foo submits once: path, eight headings, running agent ids', async ($, on) => {
  const w = await world($, on)
  w.S.agents = AGENTS
  await w.start()
  await w.cmd('handoff', 'foo')
  expect(w.S.submits.length).toBe(1)
  const text: string = w.S.submits[0].text
  expect(text).toContain(`${REPO}/handoff/${TODAY}-foo.md`)
  for (const h of HEADINGS) expect(text).toContain(h)
  expect(text).toContain('agent-aaa1')
  expect(text).toContain('agent-bbb2')
  expect(text).toContain('Do nothing else this turn')
  // one-shot prompt is ~300 tokens; allow generous slack for path + agents
  expect(text.length).toBeLessThan(2400)
  // the plugin never writes the handoff body itself
  expect(w.S.writes.filter(x => x.path.endsWith('.md')).length).toBe(0)
})

t('C10 outside a repo the path starts with the home .local/state/claude-handoffs/', async ($, on) => {
  const w = await world($, on, { inRepo: false })
  await w.start()
  await w.cmd('handoff', 'foo')
  expect(w.S.submits.length).toBe(1)
  expect(w.S.submits[0].text).toContain(`${HOME}/.local/state/claude-handoffs/${TODAY}-foo.md`)
})

t('C10 second call the same day gets -foo-2.md, third -foo-3.md', async ($, on) => {
  const w = await world($, on)
  await w.start()
  w.writeHandoff(PATH_FOO)
  await w.cmd('handoff', 'foo')
  expect(w.S.submits[0].text).toContain(`${REPO}/handoff/${TODAY}-foo-2.md`)
  await w.cmd('handoff', 'cancel') // one handoff at a time: leave writing first
  w.writeHandoff(`${REPO}/handoff/${TODAY}-foo-2.md`)
  await w.cmd('handoff', 'foo')
  const last = w.S.submits[w.S.submits.length - 1].text
  expect(last).toContain(`${REPO}/handoff/${TODAY}-foo-3.md`)
})

t('C10 slug is kebab-case of the argument, at most 40 chars', async ($, on) => {
  const w = await world($, on)
  await w.start()
  await w.cmd('handoff', 'Fix The Auth Flow')
  expect(w.S.submits[0].text).toContain(`${REPO}/handoff/${TODAY}-fix-the-auth-flow.md`)
})

t('C10 long slug is cut to 40 chars', async ($, on) => {
  const w = await world($, on)
  await w.start()
  await w.cmd('handoff', 'a very long handoff name that keeps going and going well past forty characters')
  const m = (w.S.submits[0].text as string).match(new RegExp(`${REPO}/handoff/${TODAY}-([a-z0-9-]+)\\.md`))
  expect(m).toBeTruthy()
  expect((m as RegExpMatchArray)[1].length).toBeLessThanOrEqual(40)
})

t('C10 no argument falls back to a slug (session)', async ($, on) => {
  const w = await world($, on)
  await w.start()
  await w.cmd('handoff', '')
  expect(w.S.submits.length).toBe(1)
  expect(w.S.submits[0].text).toMatch(new RegExp(`${REPO}/handoff/${TODAY}-[a-z0-9-]+\\.md`))
})

t('C10 state is writing after /handoff', async ($, on) => {
  const w = await world($, on)
  await w.start()
  await w.cmd('handoff', 'foo')
  expect((await w.state('handoff')).state).toBe('writing')
})

// ---- statement 11 ----
t('C11 compact is never called by /handoff, turn.complete, timers, toasts or hooks (go excluded)', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'cold', phase: 'report', agents: 0 }) // a strong moment: toast offered
  await w.cmd('handoff', 'foo')
  expect(w.S.compacts.length).toBe(0)
  await w.complete({ reason: 'aborted', isAborted: true })
  await w.complete({ agentId: 'sub-1' })
  expect(w.S.compacts.length).toBe(0)
  w.writeHandoff()
  await w.complete() // writing -> ready
  expect((await w.state('handoff')).state).toBe('ready')
  expect(w.S.compacts.length).toBe(0)
  await w.complete()
  await w.measure()
  await w.submit('another prompt')
  await w.advance(29 * MIN) // inside the confirm window: timers run, nothing compacts
  await w.complete()
  await w.advance(40 * MIN) // past expiry
  await w.complete()
  await w.measure()
  expect(w.S.compacts.length).toBe(0)
  expect(w.S.toasts.length).toBeLessThanOrEqual(1) // a toast may exist; it never compacts
})

t('C11 --no-compact never compacts in any state', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'cold', phase: 'report', agents: 0 })
  await w.toReady('foo', '--no-compact')
  await w.advance(40 * MIN)
  await w.complete()
  expect(w.S.compacts.length).toBe(0)
})

t('C11 /handoff go is the only caller: exactly one compact', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'warm', phase: 'build', agents: 1 })
  await w.toReady()
  await w.cmd('handoff', 'go')
  expect(w.S.compacts.length).toBe(1)
})

t('C10 second /handoff while writing: in-progress answer, nothing submitted, first keeps its options', async ($, on) => {
  const w = await world($, on)
  await w.start()
  await w.cmd('handoff', '--no-compact foo')
  expect(w.S.submits.length).toBe(1)
  const txt = await w.cmd('handoff', 'bar')
  expect(txt).toContain('Handoff in progress')
  expect(txt).toContain('/handoff cancel first')
  expect(w.S.submits.length).toBe(1)
  expect((await w.state('handoff')).state).toBe('writing')
  w.writeHandoff(PATH_FOO)
  await w.complete()
  expect((await w.state('handoff')).state).toBe('saved') // still --no-compact, not overwritten by the second call
})
