// Statements 87-93: F43 ceiling, live fill on tool.call, standing-rules line, skip logging (spec compact.md F43.6).
// W = 400,000 via env (ENV400). Harness additions: Cfg.autoCompact (breakdown.autoCompactThreshold), S.usageTokens (what
// session.usage() reports as context.tokens, default = last measured), S.usageCalls (every usage call with its clock time).

const IMM = ' Compaction is imminent.'
const STANDING_F43 =
  "Under ## Decisions and why, list first the user's standing rules and operating mode (e.g. how many agents run in parallel, priorities, who writes tests, how to ask the user), with concrete numbers."
const PARALLEL_F43 = 'Under Parallel work running list every background agent, subagent, builder or long-running job that is running or queued (name, task, branch or id, state), or "none".'
const DBG43 = `${HOME}/.local/state/claude-handoffs/nudge-debug.jsonl`
/** world with a usage() breakdown carrying autoCompactThreshold ac (null: breakdown without the field), session started and idle 11 s (so a 10 s throttle is open) */
async function cworld($: Any, on: Any, ac: number | null = 367_000, over: Partial<Cfg> = {}) {
  const w = await world($, on, { env: ENV400, overhead: 20_000, autoCompact: ac, ...over })
  await w.start()
  await w.advance(11_000)
  return w
}
function dbg43(w: W): Any[] {
  const ws = w.S.writes.filter(x => x.path === DBG43)
  const single = ws.length > 0 && ws.every(x => x.text.trim().split('\n').length === 1)
  const txt = single ? ws.map(x => x.text.replace(/\n$/, '')).join('\n') : (w.S.files.get(DBG43) ?? '')
  return txt.split('\n').filter(l => l.trim() !== '').map(l => JSON.parse(l))
}
/** the usage() calls made since the last reset of the log */
const usageSince = (w: W) => w.S.usageCalls.length

// ---- 87 ----
t('C87 autoCompactThreshold 367,000: nudges at 300k, 325k, 350k, then the final at 355,000 ("Compaction is imminent."); none at 354,999', async ($, on) => {
  const w = await cworld($, on, 367_000)
  expect((await atTool(w, 299_999)).length).toBe(0)
  const a = await atTool(w, 300_000)
  expect(a.length).toBe(1)
  expect(a[0]).toContain('300k of 400k')
  expect(a[0]).not.toContain('imminent')
  const b = await atTool(w, 325_000)
  expect(b.length).toBe(1)
  expect(b[0]).toContain('325k of 400k')
  const c = await atTool(w, 350_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('350k of 400k')
  expect(c[0]).not.toContain('imminent')
  expect((await atTool(w, 354_999)).length).toBe(0)
  const d = await atTool(w, 355_000)
  expect(d.length).toBe(1)
  expect(d[0]).toContain('355k of 400k')
  expect(d[0]).toContain('Compaction is imminent.')
  expect(ctxs(await w.tool('Read')).length).toBe(0)
})

t('C87 none at 360k (no old 360k final) and none at 375k (no k=3 regular nudge), however the measures arrive', async ($, on) => {
  const w = await cworld($, on, 367_000)
  for (const n of [300_000, 325_000, 350_000, 355_000]) expect((await atTool(w, n)).length).toBe(1)
  for (const n of [360_000, 366_000, 370_000, 374_999, 375_000, 390_000, 400_000, 425_000]) expect((await atTool(w, n)).length).toBe(0)
  expect(ctxs(await w.submit('prompt')).length).toBe(0)
})

t('C87 a fresh cycle jumping straight to 375k gets ONE nudge (the final, "imminent") and nothing after', async ($, on) => {
  const w = await cworld($, on, 367_000)
  const c = await atTool(w, 375_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('375k of 400k')
  expect(c[0]).toContain('Compaction is imminent.')
  for (const n of [376_000, 380_000, 400_000]) expect((await atTool(w, n)).length).toBe(0)
})

t('C87 autoCompactThreshold 380,000: final at min(360k, 368k) = 360k, no 375k regular', async ($, on) => {
  const w1 = await cworld($, on, 380_000)
  await atTool(w1, 300_000)
  await atTool(w1, 325_000)
  await atTool(w1, 350_000)
  expect((await atTool(w1, 359_999)).length).toBe(0)
  const f = await atTool(w1, 360_000)
  expect(f.length).toBe(1)
  expect(f[0]).toContain('360k of 400k')
  expect(f[0]).toContain('Compaction is imminent.')
  expect((await atTool(w1, 375_000)).length).toBe(0)
})

t('C87 autoCompactThreshold 460,000: T(k) < C-12k keeps 375k/400k/425k regular nudges alive, the final at 360k fires once', async ($, on) => {
  const w = await cworld($, on, 460_000)
  for (const n of [300_000, 325_000, 350_000]) expect((await atTool(w, n)).length).toBe(1)
  const f = await atTool(w, 360_000)
  expect(f.length).toBe(1)
  expect(f[0]).toContain('Compaction is imminent.')
  for (const n of [375_000, 400_000, 425_000]) {
    const c = await atTool(w, n)
    expect(c.length).toBe(1)
    expect(c[0]).toContain(`${n / 1000}k of 400k`)
  }
})

t('C87 nudge_finalPercent=0 with a 367k ceiling: no final at all, regulars only up to 350k', async ($, on) => {
  const w = await cworld($, on, 367_000)
  for (const n of [300_000, 325_000, 350_000]) expect((await atTool(w, n)).length).toBe(1)
  for (const n of [355_000, 360_000, 375_000, 400_000]) expect((await atTool(w, n)).length).toBe(0)
}, { options: { nudge_finalPercent: 0 } })

// ---- 88 ----
for (const [label, ac, over] of [
  ['breakdown without autoCompactThreshold', null, { overhead: 20_000 }],
  ['no breakdown at all', null, { overhead: null }],
  ['autoCompactThreshold 0', 0, {}],
  ['autoCompactThreshold non-integer 367000.5', 367_000.5, {}],
  ['autoCompactThreshold negative', -5, {}],
] as const) {
  t(`C88 ${label}: C = W - 33k = 367,000, same thresholds as C87 (300k, 325k, 350k, final 355k, nothing at 375k)`, async ($, on) => {
    const w = await world($, on, { env: ENV400, ...over, autoCompact: ac })
    await w.start()
    await w.advance(11_000)
    for (const n of [300_000, 325_000, 350_000]) expect((await atTool(w, n)).length).toBe(1)
    expect((await atTool(w, 354_999)).length).toBe(0)
    const f = await atTool(w, 355_000)
    expect(f.length).toBe(1)
    expect(f[0]).toContain('Compaction is imminent.')
    for (const n of [360_000, 375_000, 400_000]) expect((await atTool(w, n)).length).toBe(0)
  })
}

// ---- 89 ----
t('C89 live fill: cached t 349,116; usage() reports 356,000 on a main-loop tool.call: that call carries ONE nudge reporting 356k (k=2 + final coincident, "imminent")', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await w.measureAt(349_116)
  await w.clock.settle()
  w.S.usageTokens = 356_000
  w.S.usageCalls.length = 0
  const r = await w.tool('Read', { file_path: '/work/repo/a.ts' })
  expect(usageSince(w)).toBeGreaterThanOrEqual(1)
  const n = nudgesOf(r)
  expect(n.length).toBe(1)
  expect(n[0]).toContain('356k of 400k')
  expect(n[0]).toContain('Compaction is imminent.')
  expect(ctxs(await w.tool('Read')).length).toBe(0)
  expect(ctxs(await w.submit('next')).length).toBe(0)
})

t('C89 live fill crossing T(0): cached 290k, usage() 301,000 on the tool.call: the 300k nudge is delivered on that same call', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await w.measureAt(290_000)
  await w.clock.settle()
  expect((await atTool(w, 290_000)).length).toBe(0)
  await w.advance(11_000)
  w.S.usageTokens = 301_000
  const n = nudgesOf(await w.tool('Read'))
  expect(n.length).toBe(1)
  expect(n[0]).toContain('301k of 400k')
  expect(n[0]).not.toContain('imminent')
})

t('C89 the live t sticks: after the live fill a later tool.call with an unchanged usage() gives nothing; the next measure continues from there', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await w.measureAt(300_000)
  await w.tool('Read')
  await w.advance(11_000)
  w.S.usageTokens = 326_000
  const n = nudgesOf(await w.tool('Read'))
  expect(n.length).toBe(1)
  expect(n[0]).toContain('326k of 400k')
  await w.advance(11_000)
  expect(ctxs(await w.tool('Read')).length).toBe(0)
  expect(norm(await w.cmd('coach'))).toContain('handoff nudge: next at 350k')
})

t('C89 a subagent tool.call never calls usage() and never delivers; a later main-loop call does both', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await w.measureAt(349_116)
  await w.clock.settle()
  w.S.usageTokens = 356_000
  w.S.usageCalls.length = 0
  for (let i = 0; i < 5; i++) {
    const r = await w.tool('Read', {}, { agentId: 'sub-1', inner: { result: 'ok', text: 'ok', context: ['keep'] } })
    expect(ctxs(r)).toEqual(['keep'])
  }
  expect(usageSince(w)).toBe(0)
  const m = await w.tool('Read')
  expect(usageSince(w)).toBeGreaterThanOrEqual(1)
  expect(nudgesOf(m).length).toBe(1)
})

t('C89 the live read reaches prompt.submit as well: a nudge armed by the live t on a tool.call is not delivered twice', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await w.measureAt(300_000)
  await w.tool('Read')
  await w.advance(11_000)
  w.S.usageTokens = 351_000
  expect(nudgesOf(await w.tool('Read')).length).toBe(1)
  expect(ctxs(await w.submit('again')).length).toBe(0)
})

// ---- 90 ----
t('C90 throttle: three main-loop tool.calls within 10 s call usage() once; a fourth after 10 s calls it again', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await w.measureAt(200_000)
  await w.clock.settle()
  w.S.usageCalls.length = 0
  await w.tool('Read')
  await w.advance(2_000)
  await w.tool('Read')
  await w.advance(2_000)
  await w.tool('Read')
  expect(usageSince(w)).toBe(1)
  await w.advance(10_001)
  await w.tool('Read')
  expect(usageSince(w)).toBe(2)
  await w.tool('Read')
  expect(usageSince(w)).toBe(2)
})

t('C90 the throttle is per session: after session.end + start the first main-loop call may read usage() again', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await w.measureAt(200_000)
  await w.clock.settle()
  w.S.usageCalls.length = 0
  await w.tool('Read')
  expect(usageSince(w)).toBe(1)
  await $.session.end({ reason: 'clear', sessionId: SID })
  await w.clock.settle()
  await w.start()
  await w.measureAt(200_000)
  await w.clock.settle()
  w.S.usageCalls.length = 0
  await w.advance(1_000)
  await w.tool('Read')
  expect(usageSince(w)).toBeLessThanOrEqual(1) // at most once either way
})

t('C90 usage() rejecting: no exception escapes tool.call, the cached t is used and delivery continues', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await w.measureAt(300_000)
  await w.clock.settle()
  w.S.failOps.add('session.usage')
  const inner = { result: 'ok', text: 'ok', context: ['keep'] }
  const r = await w.tool('Read', {}, { inner })
  expect(r.result).toBe('ok')
  expect(r.deny).toBeUndefined()
  expect(ctxs(r)).toContain('keep')
  const n = nudgesOf(r)
  expect(n.length).toBe(1)
  expect(n[0]).toContain('300k of 400k')
  await w.advance(11_000)
  const r2 = await w.tool('Read')
  expect(r2.deny).toBeUndefined()
  expect(ctxs(await w.submit('hello')).length).toBe(0)
})

t('C90 usage() rejecting does not block a later successful read: after the failure is cleared the next call (after 10 s) uses the live t', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await w.measureAt(200_000)
  await w.clock.settle()
  w.S.failOps.add('session.usage')
  await w.tool('Read')
  w.S.failOps.delete('session.usage')
  await w.advance(11_000)
  w.S.usageTokens = 302_000
  const n = nudgesOf(await w.tool('Read'))
  expect(n.length).toBe(1)
  expect(n[0]).toContain('302k of 400k')
})

t('C90 usage() returning an unusable shape (no context) is swallowed too', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await w.measureAt(300_000)
  await w.clock.settle()
  w.S.usageTokens = Number.NaN
  const r = await w.tool('Read')
  expect(r.deny).toBeUndefined()
  expect(nudgesOf(r).length).toBe(1)
  expect(nudgesOf(r)[0]).toContain('300k of 400k')
})

// ---- 91 ----
t('C91 usage() smaller than cached t: cached t kept (nudge text reports the cached 330k, not 310k)', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await w.measureAt(330_000)
  await w.clock.settle()
  w.S.usageTokens = 310_000
  const n = nudgesOf(await w.tool('Read'))
  expect(n.length).toBe(1)
  expect(n[0]).toContain('330k of 400k')
})

t('C91 usage() far smaller (below T(0)/2) does not reset the cycle: /coach still names the next threshold and nothing is re-delivered', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await atTool(w, 300_000)
  await atTool(w, 325_000)
  expect(norm(await w.cmd('coach'))).toContain('handoff nudge: next at 350k')
  await w.advance(11_000)
  w.S.usageTokens = 100_000
  expect(ctxs(await w.tool('Read')).length).toBe(0)
  expect(norm(await w.cmd('coach'))).toContain('handoff nudge: next at 350k')
  expect((await atTool(w, 350_000)).length).toBe(1)
})

t('C91 usage() equal to cached t changes nothing (no extra nudge, no duplicate)', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await atTool(w, 300_000)
  await w.advance(11_000)
  w.S.usageTokens = 300_000
  expect(ctxs(await w.tool('Read')).length).toBe(0)
})

// ---- 92 ----
t('C92 nudge text contains the standing-rules sentence exactly once, right after the headings list', async ($, on) => {
  const w = await cworld($, on, 367_000)
  const c = await atTool(w, 300_000)
  expect(c.length).toBe(1)
  expect(c[0].split(STANDING_F43).length - 1).toBe(1)
  const iHead = c[0].indexOf('## Exact next step.')
  expect(iHead).toBeGreaterThan(0)
  expect(c[0].indexOf(' ' + STANDING_F43)).toBe(iHead + '## Exact next step.'.length)
  expect(c[0].split(PARALLEL_F43).length - 1).toBe(1) // F43.7
  expect(c[0].toLowerCase().indexOf('rewrite')).toBeGreaterThan(c[0].indexOf(STANDING_F43))
})

t('C92 the final nudge carries the sentence exactly once as well', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await atTool(w, 300_000)
  await atTool(w, 325_000)
  await atTool(w, 350_000)
  const f = await atTool(w, 355_000)
  expect(f.length).toBe(1)
  expect(f[0]).toContain(IMM.trim())
  expect(f[0].split(STANDING_F43).length - 1).toBe(1)
})

t('C92 full text <= 1150 chars with a 120-char agent path (normal and final form)', async ($, on) => {
  const w = await cworld($, on, 367_000)
  const base = `${HOME}/.local/state/claude-handoffs/`
  const sid = 's'.repeat(120 - base.length - '-agent.md'.length)
  w.S.sid = sid
  const c = await atTool(w, 300_000)
  expect(c.length).toBe(1)
  const m = c[0].match(/(\/\S+-agent\.md)/)
  expect(m).not.toBeNull()
  expect(m![1].length).toBe(120) // precondition: the path really is 120 chars (the plugin builds it from session.id)
  expect(c[0].length).toBeLessThanOrEqual(1150)
  await atTool(w, 325_000)
  await atTool(w, 350_000)
  const f = await atTool(w, 355_000)
  expect(f.length).toBe(1)
  expect(f[0].length).toBeLessThanOrEqual(1150)
})

// ---- 93 ----
t('C93 20 subagent tool.calls in one cycle write exactly one skip line with reason agent_subagent', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await w.measureAt(200_000)
  await w.clock.settle()
  for (let i = 0; i < 20; i++) await w.tool('Read', {}, { agentId: 'sub-1', inner: { result: 'ok', text: 'ok' } })
  await w.clock.settle()
  const sk = dbg43(w).filter(x => x.ev === 'skip' && x.reason === 'agent_subagent')
  expect(sk.length).toBe(1)
})

t('C93 after a compaction reset the next subagent call writes one more skip line (two in total), and only one', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await w.measureAt(200_000)
  await w.clock.settle()
  for (let i = 0; i < 20; i++) await w.tool('Read', {}, { agentId: 'sub-1', inner: { result: 'ok', text: 'ok' } })
  await w.compact('manual')
  await w.clock.settle()
  for (let i = 0; i < 20; i++) await w.tool('Read', {}, { agentId: 'sub-1', inner: { result: 'ok', text: 'ok' } })
  await w.clock.settle()
  const sk = dbg43(w).filter(x => x.ev === 'skip' && x.reason === 'agent_subagent')
  expect(sk.length).toBe(2)
})

t('C93 subagent tool.calls write no other debug event (no arm, no deliver) and no skip for main-loop calls', async ($, on) => {
  const w = await cworld($, on, 367_000)
  await w.measureAt(100_000)
  await w.clock.settle()
  for (let i = 0; i < 5; i++) await w.tool('Read', {}, { agentId: 'sub-1' })
  for (let i = 0; i < 5; i++) await w.tool('Read')
  await w.clock.settle()
  const L = dbg43(w)
  expect(L.filter(x => x.ev === 'arm' || x.ev === 'deliver').length).toBe(0)
  expect(L.filter(x => x.ev === 'skip').length).toBe(1)
})
