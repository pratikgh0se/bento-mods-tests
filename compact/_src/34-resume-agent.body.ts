// Statements 41-46 (+ the freshness rule of 35, exercised through Resume): F33.11 Resume uses the agent file.

const PENDING = `compact:pending:${SID}`

/** nudge delivered at 300k, then (optionally) the model writes the agent file one second later */
async function nudged(w: W, o: { write?: boolean | string } = {}): Promise<void> {
  expect((await atTool(w, 300_000)).length).toBe(1)
  await w.advance(1000)
  if (o.write !== false) await writeAgent(w, typeof o.write === 'string' ? o.write : BIG)
}
async function firstPrompt(w: W, text = 'first after compaction'): Promise<string[]> {
  return ctxs(await w.submit(text))
}

// ---- 41 ----
for (const trigger of ['manual', 'auto', 'plugin'] as const) {
  t(`C41 fresh agent file, no /handoff, ${trigger} compaction: next prompt carries exactly the agent entry, the one after none`, async ($, on) => {
    const w = await nworld($, on)
    await nudged(w)
    await w.compact(trigger)
    const c = await firstPrompt(w)
    expect(c).toEqual([AGENT_ENTRY])
    expect(c[0].length).toBeLessThanOrEqual(240)
    expect(await firstPrompt(w, 'second')).toEqual([])
  })
}

t('C41 the pending key is {v:1, path, at, savedAt: agentWrittenAt, kind:"agent"} and is deleted once injected', async ($, on) => {
  const w = await nworld($, on)
  await nudged(w)
  const writtenAt = w.now()
  await w.compact('manual')
  const v = w.S.kv.get(PENDING) as Any
  expect(v).toBeDefined()
  expect(v.v).toBe(1)
  expect(v.path).toBe(AGENT)
  expect(v.kind).toBe('agent')
  expect(typeof v.at).toBe('number')
  expect(v.savedAt).toBe(writtenAt)
  expect(await firstPrompt(w)).toEqual([AGENT_ENTRY])
  expect(w.S.kv.has(PENDING)).toBe(false)
})

// ---- 42 / 35 (freshness through Resume) ----
t('C42 written before the latest nudge, ctxTokens - agentWrittenAtTokens = 50,001: stale, no entry, key never written', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(249_999)
  await writeAgent(w)
  await w.advance(1000)
  expect((await atTool(w, 300_000)).length).toBe(1)
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([])
  expect(w.S.kvSets).not.toContain(PENDING)
})

t('C35 written before the latest nudge, ctxTokens - agentWrittenAtTokens = 49,999: fresh', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(250_001)
  await writeAgent(w)
  await w.advance(1000)
  expect((await atTool(w, 300_000)).length).toBe(1)
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([AGENT_ENTRY])
})

t('C35 written after lastNudgeAt: fresh however far the context has grown since is not required (written at the nudge token count)', async ($, on) => {
  const w = await nworld($, on)
  await nudged(w)
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([AGENT_ENTRY])
})

t('C42 size 299 bytes: stale, no entry, key never written', async ($, on) => {
  const w = await nworld($, on)
  await nudged(w, { write: 'x'.repeat(299) })
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([])
  expect(w.S.kvSets).not.toContain(PENDING)
})

t('C35 size exactly 300 bytes: fresh', async ($, on) => {
  const w = await nworld($, on)
  await nudged(w, { write: 'x'.repeat(300) })
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([AGENT_ENTRY])
})

t('C42 no write detected (file on disk, no Write tool call, no later measure): stale, no entry, key never written', async ($, on) => {
  const w = await nworld($, on)
  await nudged(w, { write: false })
  w.S.files.set(AGENT, BIG)
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([])
  expect(w.S.kvSets).not.toContain(PENDING)
})

t('C42 file missing at inject time: no entry and exactly one log line', async ($, on) => {
  const w = await nworld($, on)
  await nudged(w)
  await w.compact('manual')
  w.S.files.delete(AGENT)
  const before = w.S.logs.length
  expect(await firstPrompt(w)).toEqual([])
  expect(w.S.logs.length - before).toBe(1)
})

t('C42 no agent file at all and no /handoff: behaves exactly like s3 with no handoff (no entry, no key)', async ($, on) => {
  const w = await nworld($, on)
  await atTool(w, 300_000)
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([])
  expect(w.S.kvSets).not.toContain(PENDING)
})

t('C35 no meta file (nudge off): agent file with mtime 29 min old is fresh', async ($, on) => {
  const w = await nworld($, on)
  w.S.files.set(AGENT, BIG)
  w.S.mtimes.set(AGENT, w.now() - 29 * MIN)
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([AGENT_ENTRY])
}, { options: { mod_nudge_enabled: false } })

t('C35 no meta file (nudge off): agent file with mtime 31 min old is stale', async ($, on) => {
  const w = await nworld($, on)
  w.S.files.set(AGENT, BIG)
  w.S.mtimes.set(AGENT, w.now() - 31 * MIN)
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([])
}, { options: { mod_nudge_enabled: false } })

// ---- 43 ----
t('C43 /handoff saved within 240 min AND a fresh agent file: the entry is the s3 text and the pending key has no kind', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(100_000)
  await w.toReady()
  await nudged(w)
  await w.compact('manual')
  const v = w.S.kv.get(PENDING) as Any
  expect(v).toBeDefined()
  expect(v.kind).toBeUndefined()
  const c = await firstPrompt(w)
  expect(c.length).toBe(1)
  expect(c[0]).toContain(PATH_FOO)
  expect(c[0]).toContain('Next steps')
  expect(c[0]).not.toContain('Exact next step')
})

t('C43 a --no-compact /handoff that saved a file still wins over a fresh agent file', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(100_000)
  await w.toReady('foo', '--no-compact')
  await nudged(w)
  await w.compact('manual')
  const c = await firstPrompt(w)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('Next steps')
  expect(c[0]).not.toContain('Exact next step')
})

t('C43 a /handoff older than resumeMaxAgeMin (241 min) and a fresh agent file: the agent entry', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(100_000)
  await w.toReady()
  await w.advance(241 * MIN)
  await nudged(w)
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([AGENT_ENTRY])
})

t('C43 a /handoff 200 min old and a fresh agent file: still the /handoff entry', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(100_000)
  await w.toReady()
  await w.advance(200 * MIN)
  await nudged(w)
  await w.compact('manual')
  const c = await firstPrompt(w)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('Next steps')
})

// ---- 44 ----
t('C44 compaction answered with {skip}: no key, no entry, even with a fresh agent file', async ($, on) => {
  const w = await nworld($, on, { compact: 'skip' })
  await nudged(w)
  await w.compact('manual')
  expect(w.S.kvSets).not.toContain(PENDING)
  expect(await firstPrompt(w)).toEqual([])
  expect(await firstPrompt(w, 'again')).toEqual([])
})

t('C44 trigger precompute: no key, no entry, even with a fresh agent file', async ($, on) => {
  const w = await nworld($, on)
  await nudged(w)
  await w.compact('precompute')
  expect(w.S.kvSets).not.toContain(PENDING)
  expect(await firstPrompt(w)).toEqual([])
})

t('C44 a compaction with an agentId: no key, no entry, even with a fresh agent file', async ($, on) => {
  const w = await nworld($, on)
  await nudged(w)
  await w.compact('auto', { agentId: 'sub-1' })
  expect(w.S.kvSets).not.toContain(PENDING)
  expect(await firstPrompt(w)).toEqual([])
})

t('C44 after an injected entry the key is deleted: a second prompt gets none', async ($, on) => {
  const w = await nworld($, on)
  await nudged(w)
  await w.compact('manual')
  expect((await firstPrompt(w)).length).toBe(1)
  expect(w.S.kv.has(PENDING)).toBe(false)
  expect(await firstPrompt(w, 'second')).toEqual([])
  expect(await firstPrompt(w, 'third')).toEqual([])
})

// ---- 45 ----
t('C45 Resume still picks the file when it is fresh only because agentWrittenAt >= lastNudgeAt (reset runs after the pick)', async ($, on) => {
  const w = await nworld($, on)
  await nudged(w)
  await w.compact('manual')
  expect(w.S.kv.has(PENDING)).toBe(true)
  expect(((await w.state('nudge')) as Any).lastK).toBe(-1)
  expect(await firstPrompt(w)).toEqual([AGENT_ENTRY])
})

t('C45 after that compaction lastK is -1 and the next nudge fires again at 300k', async ($, on) => {
  const w = await nworld($, on)
  await nudged(w)
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([AGENT_ENTRY])
  const c = await atTool(w, 300_000)
  expect(c.length).toBe(1)
  expect(c[0]).toMatch(/^\[compact\] Context is 75%/)
})

t('C45 the first prompt after compaction carries at most the Resume entry (the nudge arm was cleared)', async ($, on) => {
  const w = await nworld($, on)
  await atTool(w, 300_000)
  await w.measureAt(350_000) // armed again (k=1) but not delivered yet
  await w.advance(1000)
  await writeAgent(w)
  await w.compact('manual')
  const c = await firstPrompt(w)
  expect(nudgesOf({ context: c }).length).toBe(0)
  expect(c.length).toBeLessThanOrEqual(1)
})

// ---- 46 ----
t('C46 the system prompt is unchanged while the agent-file entry is pending (compose identical before, while pending, after)', async ($, on) => {
  const w = await nworld($, on)
  await nudged(w)
  const before = JSON.stringify(await w.compose())
  await w.compact('manual')
  const pending = JSON.stringify(await w.compose())
  expect(await firstPrompt(w)).toEqual([AGENT_ENTRY])
  const after = JSON.stringify(await w.compose())
  expect(pending).toBe(before)
  expect(after).toBe(before)
})

t('C46 mod_resume_enabled=false: no entry after compaction (even with a fresh agent file) while the nudge still delivers', async ($, on) => {
  const w = await nworld($, on)
  await nudged(w)
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([])
  expect(w.S.kvSets).not.toContain(PENDING)
  const c = await atTool(w, 300_000)
  expect(c.length).toBe(1)
  expect(c[0]).toMatch(/^\[compact\] Context is 75%/)
}, { options: { mod_resume_enabled: false } })

t('C46 mod_nudge_enabled=false does not disable Resume: a fresh file from an earlier run is still used', async ($, on) => {
  const w = await nworld($, on)
  w.S.files.set(AGENT, BIG)
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([AGENT_ENTRY])
}, { options: { mod_nudge_enabled: false } })
