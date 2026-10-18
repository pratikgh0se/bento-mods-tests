// Statement 12: detection of a finished handoff write.

const CONFIRM = ['irreversible', '/handoff go', '/handoff cancel']

for (const surface of SURFACES) {
  t(`C12 answer turn with a valid file -> ready; chip and notice carry the confirm text (${surface})`, async ($, on) => {
    const w = await world($, on)
    await w.scene({ cache: 'warm', phase: 'build', agents: 1 })
    await w.cmd('handoff', 'foo')
    w.writeHandoff()
    await w.complete({ reason: 'answer' })
    const h = await w.state('handoff')
    expect(h.state).toBe('ready')
    const band = await w.band(surface)
    const notice = w.S.notices.join('\n')
    for (const needle of CONFIRM) {
      expect(band).toContain(needle)
      expect(notice).toContain(needle)
    }
  })
}

t('C12 aborted turn changes nothing', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.cmd('handoff', 'foo')
  w.writeHandoff()
  await w.complete({ reason: 'aborted', isAborted: true })
  expect((await w.state('handoff')).state).toBe('writing')
})

t('C12 a subagent turn (agentId set) changes nothing', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.cmd('handoff', 'foo')
  w.writeHandoff()
  await w.complete({ reason: 'answer', agentId: 'sub-1' })
  expect((await w.state('handoff')).state).toBe('writing')
})

for (const surface of SURFACES) {
  t(`C12 missing "## 7" heading -> failed; text says missing + the heading; no compaction offered (${surface})`, async ($, on) => {
    const w = await world($, on)
    await w.scene()
    await w.cmd('handoff', 'foo')
    w.writeHandoff(PATH_FOO, handoffText({ omit: [7] }))
    await w.complete({ reason: 'answer' })
    const h = await w.state('handoff')
    expect(h.state).toBe('failed')
    expect(JSON.stringify(h.missing)).toMatch(/Next steps|7/)
    const everything = [await w.band(surface), w.S.notices.join('\n'), w.S.toasts.map(x => x.text).join('\n')].join('\n')
    expect(everything).toContain('missing')
    expect(everything).toMatch(/Next steps/)
    expect(everything).not.toContain('/handoff go')
    expect(everything).not.toContain('irreversible')
  })
}

t('C12 file absent -> failed, no compaction offered', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.cmd('handoff', 'foo')
  await w.complete({ reason: 'answer' })
  const h = await w.state('handoff')
  expect(h.state).toBe('failed')
  expect(w.S.notices.join('\n')).not.toContain('/handoff go')
})

t('C12 file under 800 bytes (all headings present) -> failed', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.cmd('handoff', 'foo')
  const tiny = handoffText({ tiny: true })
  expect(utf8len(tiny)).toBeLessThan(800)
  w.writeHandoff(PATH_FOO, tiny)
  await w.complete({ reason: 'answer' })
  expect((await w.state('handoff')).state).toBe('failed')
})

t('C12 only the first main answer turn after the submit is judged', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.cmd('handoff', 'foo')
  await w.complete({ reason: 'answer', agentId: 'sub-1' }) // ignored
  w.writeHandoff()
  await w.complete({ reason: 'answer' })
  expect((await w.state('handoff')).state).toBe('ready')
})
