// Statements 16 and 17: Resume loader.

async function ctxOf(w: W, text = 'continue'): Promise<string[]> {
  const r = await w.submit(text)
  return [...((r && r.context) || [])]
}
function expectEntry(entries: string[]): void {
  expect(entries.length).toBe(1)
  expect(entries[0].length).toBeLessThanOrEqual(240)
  expect(entries[0]).toContain(PATH_FOO)
  expect(entries[0]).toContain('Next steps')
}

for (const trigger of ['manual', 'auto', 'plugin'] as const) {
  t(`C16 after a ${trigger} compaction following a saved handoff: next prompt carries exactly one entry, the one after none`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ cache: 'warm', phase: 'build', agents: 1 })
    await w.toReady()
    await w.compact(trigger)
    expectEntry(await ctxOf(w, 'first after compaction'))
    expect((await ctxOf(w, 'second')).length).toBe(0)
  })
}

t('C16 --no-compact saved handoff also feeds the resume entry', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.toReady('foo', '--no-compact')
  await w.compact('manual')
  expectEntry(await ctxOf(w))
})

t('C16 /handoff go path: exactly one entry (idempotent with the compaction event)', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.toReady()
  await w.cmd('handoff', 'go')
  expectEntry(await ctxOf(w))
  expect((await ctxOf(w, 'again')).length).toBe(0)
})

t('C16 compaction result {skip}: no entry ever', async ($, on) => {
  const w = await world($, on, { compact: 'skip' })
  await w.scene()
  await w.toReady()
  await w.compact('manual')
  expect((await ctxOf(w)).length).toBe(0)
  expect((await ctxOf(w, 'again')).length).toBe(0)
})

t('C16 trigger precompute: no entry', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.toReady()
  await w.compact('precompute')
  expect((await ctxOf(w)).length).toBe(0)
})

t('C16 compaction with an agentId (a subagent): no entry', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.toReady()
  await w.compact('auto', { agentId: 'sub-1' })
  expect((await ctxOf(w)).length).toBe(0)
})

t('C16 no saved handoff in this session: no entry', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.compact('manual')
  expect((await ctxOf(w)).length).toBe(0)
})

t('C16 handoff saved more than resumeMaxAgeMin (240 min) before the compaction: no entry', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.toReady()
  await w.advance(241 * MIN)
  await w.compact('manual')
  expect((await ctxOf(w)).length).toBe(0)
})

t('C16 handoff saved 200 min before the compaction: entry', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.toReady()
  await w.advance(200 * MIN)
  await w.compact('manual')
  expectEntry(await ctxOf(w))
})

t('C16 handoff file gone at injection time: nothing injected, exactly one log line', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.toReady()
  await w.compact('manual')
  w.S.files.delete(PATH_FOO)
  const logsBefore = w.S.logs.length
  const entries = await ctxOf(w)
  expect(entries.length).toBe(0)
  expect(w.S.logs.length - logsBefore).toBe(1)
})

// ---- statement 17 ----
t('C17 the system prompt does not change for the resume (compose identical before, while pending, after)', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.toReady()
  const before = JSON.stringify(await w.compose())
  await w.compact('manual') // pending now
  const pending = JSON.stringify(await w.compose())
  expectEntry(await ctxOf(w))
  const after = JSON.stringify(await w.compose())
  expect(pending).toBe(before)
  expect(after).toBe(before)
})
