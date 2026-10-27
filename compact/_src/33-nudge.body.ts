// Statements 25-40: F33 handoff nudge (spec compact.md F33.8). Statements 41-46 are in 34-resume-agent.
// F41 (statement 86): the default cadence is 25,000 (was 50,000); C27 and C37 assert the 25k steps.
// W = 400,000 is pinned through env CLAUDE_CODE_AUTO_COMPACT_WINDOW unless a test says otherwise.

// ---- 25 ----
t('C25 t=299,999: the next main tool.call returns the inner result with context unchanged', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(299_999)
  const r = await w.tool('Read', { file_path: '/work/repo/a.ts' }, { inner: { result: 'ok', text: 'ok', context: ['keep'] } })
  expect(ctxs(r)).toEqual(['keep'])
  const r2 = await w.tool('Read', { file_path: '/work/repo/a.ts' })
  expect(ctxs(r2).length).toBe(0)
})

t('C25 t=300,000: the next main tool.call gains exactly one entry with the header, the path and the six headings in order', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(300_000)
  const r = await w.tool('Read', { file_path: '/work/repo/a.ts' }, { inner: { result: { a: 1 }, ref: 'R1', text: 'ok' } })
  const c = ctxs(r)
  expect(c.length).toBe(1)
  expect(c[0]).toMatch(/^\[compact\] Context is 75% of the auto-compact window \(300k of 400k\)/)
  expect(c[0]).toContain(AGENT)
  expect(c[0].length).toBeLessThanOrEqual(640) // F35.3 supersedes the F33 bound of 520
  let at = -1
  for (const h of H6) {
    const i = c[0].indexOf(h, at + 1)
    expect(i).toBeGreaterThan(at)
    at = i
  }
  expect(r.result).toEqual({ a: 1 })
  expect(r.ref).toBe('R1')
})

t('C25 existing context entries are kept first, the nudge is appended after them', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(300_000)
  const r = await w.tool('Read', {}, { inner: { result: 'ok', text: 'ok', context: ['keep-1', 'keep-2'] } })
  const c = ctxs(r)
  expect(c.length).toBe(3)
  expect(c.slice(0, 2)).toEqual(['keep-1', 'keep-2'])
  expect(c[2]).toMatch(/^\[compact\] Context is 75%/)
})

// ---- 26 ----
t('C26 env unset, claude-sonnet-5-5 (1,000,000 from windows.ts): none at 700k, nudge at 750k with "750k of 1000k"', async ($, on) => {
  const w = await world($, on, { env: {}, model: SONNET })
  await w.start()
  await w.step()
  expect((await atTool(w, 700_000)).length).toBe(0)
  const c = await atTool(w, 750_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('750k of 1000k')
})

for (const bad of ['abc', '0', '-5']) {
  t(`C26 env CLAUDE_CODE_AUTO_COMPACT_WINDOW=${bad} is ignored and falls through to the model window`, async ($, on) => {
    const w = await world($, on, { env: { CLAUDE_CODE_AUTO_COMPACT_WINDOW: bad }, model: SONNET })
    await w.start()
    await w.step()
    expect((await atTool(w, 700_000)).length).toBe(0)
    const c = await atTool(w, 750_000)
    expect(c.length).toBe(1)
    expect(c[0]).toContain('750k of 1000k')
  })
}

t('C26 a valid env value wins over the model window', async ($, on) => {
  const w = await world($, on, { env: ENV400, model: SONNET })
  await w.start()
  await w.step()
  const c = await atTool(w, 300_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('300k of 400k')
})

t('C26 windowsJson {"sonnet":200000}: thresholds 150k (none at 149,999, nudge at 150,000 "150k of 200k")', async ($, on) => {
  const w = await world($, on, { env: {}, model: SONNET })
  await w.start()
  await w.step()
  expect((await atTool(w, 149_999)).length).toBe(0)
  const c = await atTool(w, 150_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('150k of 200k')
}, { options: { windowsJson: JSON.stringify({ sonnet: 200_000 }) } })

t('C26 no window knowable (unknown model, no breakdown): never nudges, no exception', async ($, on) => {
  const w = await world($, on, { env: {}, model: 'claude-mystery-9' })
  await w.start()
  await w.step()
  for (const n of [300_000, 750_000, 2_000_000]) expect((await atTool(w, n)).length).toBe(0)
  expect((await w.submit('hello')).context ?? []).toEqual([])
})

t('C26 (F33.2 rule 2) no env, unknown model, breakdown rawMaxTokens 500,000: that is the window', async ($, on) => {
  const w = await world($, on, { env: {}, model: 'claude-mystery-9', overhead: 20_000, rawMax: 500_000 })
  await w.start()
  expect((await atTool(w, 374_999)).length).toBe(0)
  const c = await atTool(w, 375_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('375k of 500k')
})

// ---- 27 ----
t('C27 W=400k (F41.1 cadence 25k): after the first delivery 324,999 none; 325,000 one; 350,000 one; each exactly once however many tool calls follow', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 300_000)).length).toBe(1)
  expect(ctxs(await w.tool('Read')).length).toBe(0)
  expect(ctxs(await w.tool('Bash', { command: 'ls' })).length).toBe(0)
  expect((await atTool(w, 324_999)).length).toBe(0)
  expect((await atTool(w, 325_000)).length).toBe(1)
  expect(ctxs(await w.tool('Read')).length).toBe(0)
  expect((await atTool(w, 349_999)).length).toBe(0)
  expect((await atTool(w, 350_000)).length).toBe(1)
  expect(ctxs(await w.tool('Read')).length).toBe(0)
  expect(ctxs(await w.tool('Read')).length).toBe(0)
})

t('C27 a measure jumping 290k -> 410k arms ONE nudge reporting 410k / 102% (highest k=4); nothing more until 425k', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 290_000)).length).toBe(0)
  const c = await atTool(w, 410_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('102%')
  expect(c[0]).toContain('410k of 400k')
  expect(ctxs(await w.tool('Read')).length).toBe(0)
  expect((await atTool(w, 415_000)).length).toBe(0)
  expect((await atTool(w, 424_999)).length).toBe(0)
  expect((await atTool(w, 425_000)).length).toBe(1)
})

// ---- 28 ----
t('C28 pending arm: prompt.submit gets the entry, the following tool.call gets none', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(300_000)
  const r = await w.submit('next prompt')
  expect(nudgesOf(r).length).toBe(1)
  expect(ctxs(await w.tool('Read')).length).toBe(0)
})

t('C28 pending arm: tool.call gets the entry, the following prompt.submit gets none', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(300_000)
  expect(nudgesOf(await w.tool('Read')).length).toBe(1)
  expect(ctxs(await w.submit('next prompt')).length).toBe(0)
})

t('C28 Resume entry pending too: it is kept first and the nudge comes after it', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(100_000)
  await w.toReady()
  await w.compact('manual')
  await w.measureAt(300_000)
  const c = ctxs(await w.submit('first after compaction'))
  expect(c.length).toBe(2)
  expect(c[0]).toContain(PATH_FOO)
  expect(c[0]).toContain('Next steps')
  expect(c[1]).toMatch(/^\[compact\] Context is 75%/)
})

// ---- 29 ----
t('C29 subagent tool calls never receive the entry and never consume the arm', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(300_000)
  const sub = await w.tool('Read', {}, { agentId: 'sub-1', inner: { result: 'ok', text: 'ok', context: ['keep'] } })
  expect(ctxs(sub)).toEqual(['keep'])
  expect(ctxs(await w.tool('Read', {}, { agentId: 'sub-1' })).length).toBe(0)
  expect(nudgesOf(await w.tool('Read')).length).toBe(1) // the arm survived
})

t('C29 a subagent session.measure does not arm', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(100_000)
  await w.measureAt(300_000, { agentId: 'sub-1' })
  expect(ctxs(await w.tool('Read')).length).toBe(0)
  expect(ctxs(await w.submit('hello')).length).toBe(0)
})

// ---- 30 ----
t('C30 a deny from next is returned untouched (no context); the arm survives for the next call', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(300_000)
  const r = await w.tool('Bash', { command: 'rm x' }, { inner: { deny: 'nope' } })
  expect(r.deny).toBe('nope')
  expect(ctxs(r).length).toBe(0)
  expect(nudgesOf(await w.tool('Read')).length).toBe(1)
})

t('C30 an isError result still carries the entry', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(300_000)
  const r = await w.tool('Bash', { command: 'false' }, { inner: { isError: true, result: 'boom', text: 'boom' } })
  expect(r.isError).toBe(true)
  expect(r.result).toBe('boom')
  expect(nudgesOf(r).length).toBe(1)
})

// ---- 31 ----
for (const trigger of ['manual', 'auto', 'plugin'] as const) {
  t(`C31 a ${trigger} session.compact re-arms from k=0: t=300k nudges again`, async ($, on) => {
    const w = await nworld($, on)
    expect((await atTool(w, 300_000)).length).toBe(1)
    await w.compact(trigger)
    expect((await atTool(w, 300_000)).length).toBe(1)
  })
}

t('C31 a compaction answered with {skip} does not reset', async ($, on) => {
  const w = await nworld($, on, { compact: 'skip' })
  expect((await atTool(w, 300_000)).length).toBe(1)
  await w.compact('manual')
  expect((await atTool(w, 300_000)).length).toBe(0)
})

t('C31 trigger precompute does not reset', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 300_000)).length).toBe(1)
  await w.compact('precompute')
  expect((await atTool(w, 300_000)).length).toBe(0)
})

t('C31 a compaction with an agentId does not reset', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 300_000)).length).toBe(1)
  await w.compact('auto', { agentId: 'sub-1' })
  expect((await atTool(w, 300_000)).length).toBe(0)
})

t('C31 session.end resets', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 300_000)).length).toBe(1)
  await $.session.end({ reason: 'clear', sessionId: SID })
  await w.clock.settle()
  expect((await atTool(w, 300_000)).length).toBe(1)
})

t('C31 a measure with t < T(0)/2 (149,999) resets; exactly T(0)/2 (150,000) does not', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 300_000)).length).toBe(1)
  await w.measureAt(149_999)
  expect((await atTool(w, 300_000)).length).toBe(1)
  await w.measureAt(150_000)
  expect((await atTool(w, 300_000)).length).toBe(0)
})

// ---- 32 ----
t('C32 agent file absent: the text says "write <path>" and not "update "', async ($, on) => {
  const w = await nworld($, on)
  const c = await atTool(w, 300_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain(`write ${AGENT}`)
  expect(c[0]).not.toContain('update ')
})

t('C32 agent file present: the text says "update <path>" and not "write "', async ($, on) => {
  const w = await nworld($, on)
  w.S.files.set(AGENT, BIG)
  const c = await atTool(w, 300_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain(`update ${AGENT}`)
  expect(c[0]).not.toContain('write ')
})

// ---- 33 ----
t('C33 nudge_atPercent=50, nudge_everyTokens=100000, W=400k: thresholds 200k, 300k', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 199_999)).length).toBe(0)
  const a = await atTool(w, 200_000)
  expect(a.length).toBe(1)
  expect(a[0]).toContain('50%')
  expect(a[0]).toContain('200k of 400k')
  expect((await atTool(w, 299_999)).length).toBe(0)
  expect((await atTool(w, 300_000)).length).toBe(1)
}, { options: { nudge_atPercent: 50, nudge_everyTokens: 100_000 } })

t('C33 nudge_atPercent=5 clamps to 10% (40k of 400k)', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 39_999)).length).toBe(0)
  const c = await atTool(w, 40_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('10%')
}, { options: { nudge_atPercent: 5 } })

for (const v of [95, 96, 99]) {
  t(`C33 nudge_atPercent=${v} clamps to 95% (380k of 400k)`, async ($, on) => {
    const w = await nworld($, on)
    expect((await atTool(w, 379_999)).length).toBe(0)
    const c = await atTool(w, 380_000)
    expect(c.length).toBe(1)
    expect(c[0]).toContain('95%')
  }, { options: { nudge_atPercent: v, nudge_finalPercent: 0 } })
}

t('C33 nudge_everyTokens=1000 clamps to 10,000 (300k, then 310k)', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 300_000)).length).toBe(1)
  expect((await atTool(w, 309_999)).length).toBe(0)
  expect((await atTool(w, 310_000)).length).toBe(1)
}, { options: { nudge_everyTokens: 1000 } })

for (const key of ['mod_nudge_enabled', 'mod.nudge.enabled']) {
  t(`C33 ${key}=false: results and prompts equal their input at any t, no handoffs-dir write, no atom`, async ($, on) => {
    const w = await nworld($, on)
    for (const n of [300_000, 350_000, 500_000]) {
      await w.measureAt(n)
      const inner = { result: 'ok', text: 'ok', context: ['keep'] }
      const r = await w.tool('Read', {}, { inner })
      expect(r).toEqual(inner)
      const s = await w.submit('hello')
      expect(s.text).toBe('hello')
      expect(ctxs(s).length).toBe(0)
    }
    await w.tool('Write', { file_path: AGENT, content: BIG })
    await w.measureAt(520_000)
    expect(handoffDirWrites(w).length).toBe(0)
    expect(await w.state('nudge')).toBeNull()
  }, { options: { [key]: false } })
}

// ---- 34 ----
t('C34 no handoffs-dir write before the first delivery; at first delivery exactly one meta write with the contracted fields', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(300_000)
  expect(handoffDirWrites(w).length).toBe(0)
  const r = await w.tool('Read')
  expect(nudgesOf(r).length).toBe(1)
  expect(metaWrites(w).length).toBe(1)
  const m = JSON.parse(metaWrites(w)[0].text)
  expect(m.v).toBe(1)
  expect(m.sessionId).toBe(SID)
  expect(m.window).toBe(400_000)
  expect(m.lastNudgeTokens).toBe(300_000)
  expect(m.nudgeCount).toBe(1)
  expect(metaWrites(w)[0].text).not.toContain('[compact]')
  expect(metaWrites(w)[0].text).not.toContain('Compaction will drop')
  expect(handoffDirWrites(w).filter(x => x.path !== META).length).toBe(0)
  expect(w.S.writes.filter(x => x.path.includes('/.claude/handoffs/')).length).toBe(0) // F33.12: old dir never written
})

for (const tool of ['Write', 'Edit', 'MultiEdit']) {
  t(`C34 a main ${tool} of the agent path sets agentWrittenAt / agentWrittenAtTokens in the next meta write`, async ($, on) => {
    const w = await nworld($, on)
    await atTool(w, 300_000)
    await w.advance(1000)
    const at = w.now()
    await w.tool(tool, { file_path: AGENT })
    await w.measureAt(320_000) // moves ctxTokens by >= 10,000: a meta write for sure
    await w.clock.settle()
    const ms = metaWrites(w)
    const m = JSON.parse(ms[ms.length - 1].text)
    expect(m.agentWrittenAt).toBe(at)
    expect(m.agentWrittenAtTokens).toBe(300_000)
  })
}

t('C34 a Write of any other path does not set agentWrittenAt', async ($, on) => {
  const w = await nworld($, on)
  await atTool(w, 300_000)
  await w.tool('Write', { file_path: `${HOME}/.local/state/claude-handoffs/${SID}-other.md`, content: BIG })
  await w.tool('Write', { file_path: '/work/repo/handoff/x.md', content: BIG })
  await w.measureAt(320_000)
  await w.clock.settle()
  const ms = metaWrites(w)
  const m = JSON.parse(ms[ms.length - 1].text)
  expect(m.agentWrittenAt).toBeUndefined()
  expect(m.agentWrittenAtTokens).toBeUndefined()
})

t('C34 a subagent Write of the agent path is not detected', async ($, on) => {
  const w = await nworld($, on)
  await atTool(w, 300_000)
  await w.tool('Write', { file_path: AGENT, content: BIG }, { agentId: 'sub-1' })
  await w.measureAt(320_000)
  await w.clock.settle()
  const ms = metaWrites(w)
  expect(JSON.parse(ms[ms.length - 1].text).agentWrittenAt).toBeUndefined()
})

t('C34 a rejecting $.fs.write does not throw and nudging continues', async ($, on) => {
  const w = await nworld($, on)
  w.S.failOps.add('fs.write')
  const c1 = await atTool(w, 300_000)
  expect(c1.length).toBe(1)
  const c2 = await atTool(w, 350_000)
  expect(c2.length).toBe(1)
  expect(ctxs(await w.submit('still fine')).length).toBe(0)
})

// ---- 35: isFresh is not importable by the contract (module path unspecified), freshness is exercised through Resume in 34-resume-agent.test.ts ----
skip('C35 isFresh(meta, size, now) pure function', 'export path not specified by the spec; freshness is covered through Resume (C35* in 34-resume-agent)')

// ---- 36 ----
t('C36 the mod never submits, compacts, toasts, notices or denies, across a full scenario', async ($, on) => {
  const w = await nworld($, on)
  for (const n of [100_000, 300_000, 350_000, 450_000]) {
    const r = await w.tool('Read', {}, {})
    expect(r.deny).toBeUndefined()
    await w.measureAt(n)
    const r2 = await w.tool('Bash', { command: 'ls' })
    expect(r2.deny).toBeUndefined()
    await w.submit('go')
  }
  await w.tool('Write', { file_path: AGENT, content: BIG })
  await w.compact('manual')
  await w.submit('after compaction')
  await w.clock.settle()
  expect(w.S.submitAttempts).toBe(0)
  expect(w.S.compactAttempts).toBe(0)
  expect(w.S.writes.filter(x => x.path.includes('/.claude/handoffs/')).length).toBe(0)
  expect(w.S.toasts.length).toBe(0)
  expect(w.S.notices.length).toBe(0)
})

const SNAP: Record<string, string> = {}
async function snapshot(w: W): Promise<string> {
  await w.scene({ cache: 'warm', phase: 'build', agents: 1, tokens: 350_000 })
  await w.tool('Read')
  await w.tool('Read')
  const c = await w.state('coach')
  const b = await w.bands()
  return JSON.stringify({ c, b })
}
t('C36 Coach verdict/score/reasons and band text with the mod ON (snapshot for the OFF run)', async ($, on) => {
  const w = await world($, on, { env: ENV400 })
  SNAP.on = await snapshot(w)
  expect(SNAP.on.length).toBeGreaterThan(10)
})
t('C36 Coach verdict/score/reasons and band text are identical with the mod OFF', async ($, on) => {
  const w = await world($, on, { env: ENV400 })
  const off = await snapshot(w)
  expect(SNAP.on).toBeDefined()
  expect(off).toBe(SNAP.on)
}, { options: { mod_nudge_enabled: false } })

// ---- 37 ----
t('C37 atom compact.nudge: armed/lastK/next/fresh, no path or text', async ($, on) => {
  const w = await nworld($, on)
  const a0: Any = await w.state('nudge')
  expect(a0.armed).toBe(false)
  expect(a0.lastK).toBe(-1)
  expect(a0.next).toBe(300_000)
  expect(a0.fresh).toBe('none')
  await w.measureAt(300_000)
  const a1: Any = await w.state('nudge')
  expect(a1.armed).toBe(true)
  await w.tool('Read')
  const a2: Any = await w.state('nudge')
  expect(a2.armed).toBe(false)
  expect(a2.lastK).toBe(0)
  expect(a2.next).toBe(325_000) // F41.1: 25k cadence
  for (const a of [a0, a1, a2]) {
    const j = JSON.stringify(a)
    expect(j).not.toContain('/')
    expect(j).not.toContain('[compact]')
    expect(j).not.toContain('handoffs')
  }
})

t('C37 /coach output contains "handoff nudge: next at 300k" and "agent file none", then "agent file fresh" after a detected write', async ($, on) => {
  const w = await nworld($, on)
  const before = await w.cmd('coach')
  expect(norm(before)).toContain('handoff nudge: next at 300k')
  expect(norm(before)).toContain('agent file none')
  await atTool(w, 300_000)
  await w.advance(1000)
  await writeAgent(w)
  const after = await w.cmd('coach')
  expect(norm(after)).toContain('agent file fresh')
  expect((await w.state('nudge') as Any).fresh).toBe('fresh')
})

// ---- 38 ----
for (const failing of ['env.get', 'session.usage', 'fs.stat']) {
  t(`C38 a rejecting ${failing} throws nothing and leaves results and prompts unchanged`, async ($, on) => {
    const w = await world($, on, { env: ENV400 })
    w.S.failOps.add(failing)
    await w.start()
    await w.measureAt(300_000)
    const inner = { result: 'ok', text: 'ok' }
    const r = await w.tool('Read', {}, { inner })
    expect(r.result).toBe('ok')
    expect(r.deny).toBeUndefined()
    if (failing === 'env.get') expect(ctxs(r).length).toBe(0) // opus window (1M) -> 300k is far below T(0)
    const s = await w.submit('hello')
    expect(s.text).toBe('hello')
    await w.measureAt(350_000)
    await w.tool('Write', { file_path: AGENT, content: BIG })
    await w.measureAt(370_000)
    await w.tool('Read')
  })
}

t('C38 the tool.call path makes no $ call besides clock.after (clock.now tolerated), idle / armed / agent-file Write alike', async ($, on) => {
  const w = await nworld($, on)
  const allowed = new Set(['clock.after', 'clock.now'])
  const bad = (calls: string[]) => calls.filter(c => !allowed.has(c))
  let t1 = await w.trace(() => w.tool('Read', {}, { settle: false }))
  expect(bad(t1.calls)).toEqual([])
  await w.measureAt(300_000)
  t1 = await w.trace(() => w.tool('Read', {}, { settle: false }))
  expect(bad(t1.calls)).toEqual([])
  expect(nudgesOf(t1.out).length).toBe(1)
  t1 = await w.trace(() => w.tool('Write', { file_path: AGENT, content: BIG }, { settle: false }))
  expect(bad(t1.calls)).toEqual([])
  t1 = await w.trace(() => w.tool('Read', {}, { agentId: 'sub-1', settle: false }))
  expect(bad(t1.calls)).toEqual([])
})

// ---- 39 ----
for (const name of ['Read', 'Bash', 'Grep', 'Agent', 'mcp__srv__do_thing', 'SomeFutureTool']) {
  t(`C39 a tool.call of any tool name is handled: ${name} carries the entry`, async ($, on) => {
    const w = await nworld($, on)
    await w.measureAt(300_000)
    expect(nudgesOf(await w.tool(name, {})).length).toBe(1)
  })
}

t('C39 nothing to add: the hook returns the exact object next returned', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(100_000)
  const inner = { result: 'ok', text: 'ok', context: ['keep'] }
  const r = await w.tool('Read', {}, { inner })
  expect(r).toEqual(inner) // identity (toBe) cannot be asserted: the engine may re-box the result between hooks
  const d = { deny: 'no' }
  expect(await w.tool('Bash', {}, { inner: d })).toEqual(d)
})
skip('C39 every added hook ends with .catch(($, e, next) => next(e))', 'source-level property, not observable through the engine')

// ---- 40 ----
t('C40 headless (-p): nudge still delivered via tool.call; /coach card line present', async ($, on) => {
  const w = await world($, on, { env: ENV400, interactive: false, surface: null })
  await w.start()
  const c = await atTool(w, 300_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('300k of 400k')
  expect(norm(await w.cmd('coach'))).toContain('handoff nudge: next at')
})
