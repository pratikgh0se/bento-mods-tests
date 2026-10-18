// Statements 13, 14, 15: /handoff go, cancel, failure modes, --no-compact.

for (const surface of SURFACES) {
  t(`C13 /handoff go in ready: one compact with instructions; done; chip COMPACTED 351k -> 41k (${surface})`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ cache: 'warm', phase: 'build', agents: 1 })
    await w.toReady()
    await w.cmd('handoff', 'go')
    expect(w.S.compacts.length).toBe(1)
    const ins: string = w.S.compacts[0].instructions
    expect(ins).toContain(PATH_FOO)
    expect(ins).toContain('source of truth')
    const h = await w.state('handoff')
    expect(h.state).toBe('done')
    expect(await w.band(surface)).toContain('COMPACTED 351k → 41k')
  })
}

t('C13 /handoff go in idle -> "Nothing to compact", no call', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  const txt = await w.cmd('handoff', 'go')
  expect(txt).toContain('Nothing to compact')
  expect(w.S.compacts.length).toBe(0)
})

t('C13 /handoff go after confirmTtlMin (30 min) behaves as idle', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.toReady()
  await w.advance(31 * MIN)
  const txt = await w.cmd('handoff', 'go')
  expect(txt).toContain('Nothing to compact')
  expect(w.S.compacts.length).toBe(0)
})

t('C13 /handoff go just inside the window (29 min) still compacts', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.toReady()
  await w.advance(29 * MIN)
  await w.cmd('handoff', 'go')
  expect(w.S.compacts.length).toBe(1)
})

t('C13 /handoff cancel -> idle, file untouched, go then does nothing', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.toReady()
  const before = w.S.files.get(PATH_FOO)
  const writesBefore = w.S.writes.length
  await w.cmd('handoff', 'cancel')
  expect((await w.state('handoff')).state).toBe('idle')
  expect(w.S.files.get(PATH_FOO)).toBe(before)
  expect(w.S.writes.length).toBe(writesBefore)
  expect(await w.cmd('handoff', 'go')).toContain('Nothing to compact')
  expect(w.S.compacts.length).toBe(0)
})

t('C13 compact instructions name the running agent ids', async ($, on) => {
  const w = await world($, on)
  w.S.agents = [agentInfo('agent-aaa1', 'running', 'Typecheck sweep')]
  await w.scene({ cache: 'warm', phase: 'build', agents: 0 })
  w.S.agents = [agentInfo('agent-aaa1', 'running', 'Typecheck sweep')]
  await w.toReady()
  await w.cmd('handoff', 'go')
  expect(w.S.compacts[0].instructions).toContain('agent-aaa1')
})

// ---- statement 14 (build clarification E): go answers "Compacting now..." at once; the outcome arrives by notice/log after settle ----
t('C14 compact rejects (turn running): outcome "Turn running" by notice/log, state back to ready', async ($, on) => {
  const w = await world($, on, { compact: 'throw' })
  await w.scene()
  await w.toReady()
  const txt = await w.cmd('handoff', 'go')
  expect(txt).toContain('Compacting now')
  const out = [w.S.notices.join('\n'), w.S.logs.join('\n')].join('\n')
  expect(out).toContain('Turn running')
  expect((await w.state('handoff')).state).toBe('ready')
})

t('C14 compact resolves {skip}: notice/log "Compaction skipped: <reason>", state back to ready', async ($, on) => {
  const w = await world($, on, { compact: 'skip', skipReason: 'vetoed-by-hook-xyz' })
  await w.scene()
  await w.toReady()
  const txt = await w.cmd('handoff', 'go')
  expect(txt).toContain('Compacting now')
  const out = [w.S.notices.join('\n'), w.S.logs.join('\n')].join('\n')
  expect(out).toContain('vetoed-by-hook-xyz')
  expect(out).toContain('Compaction skipped')
  expect((await w.state('handoff')).state).toBe('ready')
})

// ---- statement 15 ----
for (const surface of SURFACES) {
  t(`C15 --no-compact ends in saved and never shows go (${surface})`, async ($, on) => {
    const w = await world($, on)
    await w.scene()
    await w.toReady('foo', '--no-compact')
    const h = await w.state('handoff')
    expect(h.state).toBe('saved')
    const everything = [await w.band(surface), w.S.notices.join('\n')].join('\n')
    expect(everything).toContain('saved')
    expect(everything).not.toContain('/handoff go')
    expect(everything).not.toContain('irreversible')
  })
}

t('C15 --no-compact: /handoff go then says Nothing to compact', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.toReady('foo', '--no-compact')
  expect(await w.cmd('handoff', 'go')).toContain('Nothing to compact')
  expect(w.S.compacts.length).toBe(0)
})

t('C15 --no-compact prompt still names the path', async ($, on) => {
  const w = await world($, on)
  await w.start()
  await w.cmd('handoff', '--no-compact bar')
  expect(w.S.submits[0].text).toContain(`${REPO}/handoff/${TODAY}-bar.md`)
})
