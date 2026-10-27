// Statements 79-86: F41 nudge cadence, final nudge, delivery-time safety net, debug log (spec compact.md F41.6).
// W = 400,000 via env (nworld). Statement 86 amendments live in 33-nudge (C27, C37).

const IMMINENT = ' Compaction is imminent.'
const FINAL_RE = /^\[compact\] Context is 90% of the auto-compact window \(360k of 400k\)\. Compaction is imminent\./
const DBG = `${HOME}/.local/state/claude-handoffs/nudge-debug.jsonl`
const DBG1 = `${HOME}/.local/state/claude-handoffs/nudge-debug.1.jsonl`

/** Parsed lines of the debug log. fs.write is mocked as replace-or-append: if every write was a single line, the writes are the lines. */
function dbg(w: W): Any[] {
  const ws = w.S.writes.filter(x => x.path === DBG)
  const single = ws.length > 0 && ws.every(x => x.text.trim().split('\n').length === 1)
  const txt = single ? ws.map(x => x.text.replace(/\n$/, '')).join('\n') : (w.S.files.get(DBG) ?? '')
  return txt.split('\n').filter(l => l.trim() !== '').map(l => JSON.parse(l))
}
const touchedDbg = (w: W) => w.S.fsLog.filter(x => x.path.includes('/nudge-debug')).length + w.S.writes.filter(x => x.path.includes('/nudge-debug')).length

// ---- 79 ----
t('C79 defaults: nudges at 300,000, 325,000 and 350,000, one each; 324,999 after the first gives none', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 299_999)).length).toBe(0)
  const a = await atTool(w, 300_000)
  expect(a.length).toBe(1)
  expect(a[0]).toContain('300k of 400k')
  expect(ctxs(await w.tool('Read')).length).toBe(0)
  expect((await atTool(w, 324_999)).length).toBe(0)
  const b = await atTool(w, 325_000)
  expect(b.length).toBe(1)
  expect(b[0]).toContain('325k of 400k')
  expect(ctxs(await w.tool('Read')).length).toBe(0)
  const c = await atTool(w, 350_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('350k of 400k')
  expect(ctxs(await w.tool('Read')).length).toBe(0)
  expect(ctxs(await w.submit('again')).length).toBe(0)
})

t('C79 the /coach card names the next threshold at the 25k cadence: next at 325k after the first delivery', async ($, on) => {
  const w = await nworld($, on)
  await atTool(w, 300_000)
  expect(norm(await w.cmd('coach'))).toContain('handoff nudge: next at 325k')
})

// ---- 80 ----
t('C80 after 350k: 359,999 none; 360,000 exactly one final nudge (regex, path, six headings in order)', async ($, on) => {
  const w = await nworld($, on)
  await atTool(w, 300_000)
  await atTool(w, 325_000)
  expect((await atTool(w, 350_000)).length).toBe(1)
  expect((await atTool(w, 359_999)).length).toBe(0)
  const c = await atTool(w, 360_000)
  expect(c.length).toBe(1)
  expect(c[0]).toMatch(FINAL_RE)
  expect(c[0]).toContain(AGENT)
  let at = -1
  for (const h of H6) {
    const i = c[0].indexOf(h, at + 1)
    expect(i).toBeGreaterThan(at)
    at = i
  }
  expect(c[0].length).toBeLessThanOrEqual(662) // F41.2 says <= 560 but F35.3's own text is already ~600 (see SPEC-GAPS F41 #1)
  expect(ctxs(await w.tool('Read')).length).toBe(0)
})

t('C80 t=362k..374,999 give none more; t=375,000 gives the k=3 regular nudge (no "imminent")', async ($, on) => {
  const w = await nworld($, on)
  await atTool(w, 300_000)
  await atTool(w, 325_000)
  await atTool(w, 350_000)
  expect((await atTool(w, 360_000)).length).toBe(1)
  for (const n of [362_000, 368_000, 374_999]) expect((await atTool(w, n)).length).toBe(0)
  const c = await atTool(w, 375_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('375k of 400k')
  expect(c[0]).not.toContain(IMMINENT.trim())
  expect(c[0]).not.toMatch(FINAL_RE)
})

t('C80 the final nudge is delivered through prompt.submit too (whichever channel comes first), once', async ($, on) => {
  const w = await nworld($, on)
  await atTool(w, 300_000)
  await atTool(w, 325_000)
  await atTool(w, 350_000)
  await w.measureAt(360_000)
  const s = await w.submit('next prompt')
  expect(ctxs(s).length).toBe(1)
  expect(ctxs(s)[0]).toMatch(FINAL_RE)
  expect(ctxs(await w.tool('Read')).length).toBe(0)
})

// ---- 81 ----
t('C81 a measure jumping 290k -> 365k delivers ONE nudge (k=2 text with " Compaction is imminent."); nothing until 375k', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 290_000)).length).toBe(0)
  const c = await atTool(w, 365_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('365k of 400k')
  expect(c[0]).toContain('91%')
  expect(c[0]).toContain(IMMINENT)
  expect(c[0]).toMatch(/^\[compact\] Context is 91% of the auto-compact window \(365k of 400k\)\. Compaction is imminent\./)
  expect(ctxs(await w.tool('Read')).length).toBe(0)
  expect(ctxs(await w.submit('p')).length).toBe(0)
  for (const n of [366_000, 370_000, 374_999]) expect((await atTool(w, n)).length).toBe(0)
  const d = await atTool(w, 375_000)
  expect(d.length).toBe(1)
  expect(d[0]).toContain('375k of 400k')
})

t('C81 coincidence at the moment the final is armed with a pending regular arm: still one entry on the same tool.call', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(300_000) // regular k=0 armed, not delivered
  await w.measureAt(360_000) // final due as well, nothing delivered in between
  const r = await w.tool('Read')
  expect(ctxs(r).length).toBe(1)
  expect(ctxs(r)[0]).toContain(IMMINENT)
  expect(ctxs(await w.tool('Read')).length).toBe(0)
})

// ---- 82 ----
t('C82 nudge_finalPercent=0: no final nudge at 360k (nor "imminent" anywhere); regular nudges continue', async ($, on) => {
  const w = await nworld($, on)
  await atTool(w, 300_000)
  await atTool(w, 325_000)
  expect((await atTool(w, 350_000)).length).toBe(1)
  expect((await atTool(w, 360_000)).length).toBe(0)
  expect((await atTool(w, 374_999)).length).toBe(0)
  const c = await atTool(w, 375_000)
  expect(c.length).toBe(1)
  expect(c[0]).not.toContain('imminent')
  const d = await atTool(w, 399_999)
  expect(d.length).toBe(0)
  const e = await atTool(w, 400_000)
  expect(e.length).toBe(1)
  expect(e[0]).not.toContain('imminent')
}, { options: { nudge_finalPercent: 0 } })

t('C82 nudge_finalPercent=120 clamps to 99: final at 396,000, none at 395,999 (regular steps 100k: 300k, 400k)', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 300_000)).length).toBe(1)
  expect((await atTool(w, 360_000)).length).toBe(0)
  expect((await atTool(w, 395_999)).length).toBe(0)
  const c = await atTool(w, 396_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('396k of 400k')
  expect(c[0]).toContain('99%')
  expect(c[0]).toContain(IMMINENT)
}, { options: { nudge_finalPercent: 120, nudge_everyTokens: 100_000 } })

t('C82 nudge_finalPercent=10 clamps to 50: final at 200,000 (none at 199,999)', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 199_999)).length).toBe(0)
  const c = await atTool(w, 200_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain('200k of 400k')
  expect(c[0]).toContain('50%')
  expect(c[0]).toContain(IMMINENT)
}, { options: { nudge_finalPercent: 10 } })

t('C82 nudge_finalPercent=75 with default 75% start: the coinciding k=0 and final deliver ONE entry at 300k', async ($, on) => {
  const w = await nworld($, on)
  const c = await atTool(w, 300_000)
  expect(c.length).toBe(1)
  expect(c[0]).toContain(IMMINENT)
  expect(ctxs(await w.tool('Read')).length).toBe(0)
}, { options: { nudge_finalPercent: 75 } })

// ---- 83 ----
t('C83 after a session.compact reset the final fires again in the next cycle at 360k', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 360_000)).length).toBe(1)
  expect((await atTool(w, 365_000)).length).toBe(0)
  await w.compact('manual')
  const r = await atTool(w, 359_999) // regular k=2 only
  expect(r.length).toBe(1)
  expect(r[0]).not.toContain('imminent')
  const c = await atTool(w, 360_000)
  expect(c.length).toBe(1)
  expect(c[0]).toMatch(FINAL_RE)
  expect(ctxs(await w.tool('Read')).length).toBe(0)
})

t('C83 session.end resets the final too', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 360_000)).length).toBe(1)
  await $.session.end({ reason: 'clear', sessionId: SID })
  await w.clock.settle()
  const c = await atTool(w, 360_000)
  expect(c.length).toBe(1)
  expect(c[0]).toMatch(FINAL_RE)
})

t('C83 a measure with t < T(0)/2 resets the final too', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 360_000)).length).toBe(1)
  await w.measureAt(149_999)
  const c = await atTool(w, 360_000)
  expect(c.length).toBe(1)
  expect(c[0]).toMatch(FINAL_RE)
})

t('C83 a skip / precompute / agentId compaction does not reset the final', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 360_000)).length).toBe(1)
  await w.compact('precompute')
  await w.compact('auto', { agentId: 'sub-1' })
  expect((await atTool(w, 361_000)).length).toBe(0)
})

// ---- 84 ----
t('C84 safety net: t cached at 352,000 without a measure-time arm; the next main tool.call delivers the k=2 nudge, a subagent call does not', async ($, on) => {
  const w = await nworld($, on)
  // The arm text needs $.fs.exists at measure time; with it down the measure-time arm cannot complete,
  // but the measured t is still cached. (See SPEC-GAPS F41 #2 on how "lost arm" is simulated.)
  w.S.failOps.add('fs.exists')
  await w.measureAt(352_000)
  w.S.failOps.delete('fs.exists')
  const sub = await w.tool('Read', {}, { agentId: 'sub-1', inner: { result: 'ok', text: 'ok', context: ['keep'] } })
  expect(ctxs(sub)).toEqual(['keep'])
  const r = await w.tool('Read')
  const n = nudgesOf(r)
  expect(n.length).toBe(1)
  expect(n[0]).toContain('352k of 400k')
  expect(n[0]).not.toContain('imminent') // 352k < final 360k
  expect(ctxs(await w.tool('Read')).length).toBe(0)
})

t('C84 safety net on prompt.submit: same lost arm is recovered by the next prompt', async ($, on) => {
  const w = await nworld($, on)
  w.S.failOps.add('fs.exists')
  await w.measureAt(352_000)
  w.S.failOps.delete('fs.exists')
  const s = await w.submit('hello')
  expect(nudgesOf(s).length).toBe(1)
  expect(ctxs(await w.tool('Read')).length).toBe(0)
})

t('C84 safety net, final due: a lost final at 361,000 is delivered by the next main tool.call with " Compaction is imminent."', async ($, on) => {
  const w = await nworld($, on)
  w.S.failOps.add('fs.exists')
  await w.measureAt(361_000)
  w.S.failOps.delete('fs.exists')
  const n = nudgesOf(await w.tool('Read'))
  expect(n.length).toBe(1)
  expect(n[0]).toContain(IMMINENT)
})

t('C84 the safety net makes no $ call from tool.call besides clock.after / clock.now', async ($, on) => {
  const w = await nworld($, on)
  w.S.failOps.add('fs.exists')
  await w.measureAt(352_000)
  w.S.failOps.delete('fs.exists')
  const t1 = await w.trace(() => w.tool('Read', {}, { settle: false }))
  expect(t1.calls.filter(c => c !== 'clock.after' && c !== 'clock.now')).toEqual([])
})

// ---- 85 ----
t('C85 debug log: arm(300k) -> deliver(tool.call) -> compact reset writes 3 lines in order with the contracted fields', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(300_000)
  await w.tool('Read')
  await w.compact('manual')
  await w.clock.settle()
  const L = dbg(w)
  expect(L.map(x => x.ev)).toEqual(['arm', 'deliver', 'reset'])
  for (const x of L) {
    expect(x.sid).toBe(SID)
    expect(x.w).toBe(400_000)
    expect(new Date(x.ts).toISOString()).toBe(x.ts)
  }
  expect(L[0].t).toBe(300_000)
  expect(L[0].k).toBe(0)
  expect(L[1].k).toBe(0)
  expect(L[1].channel).toBe('tool.call')
  expect(L[1].final).toBe(false)
  expect(L[2].reason).toBe('compact')
})

t('C85 deliver through prompt.submit logs channel "prompt.submit"', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(300_000)
  await w.submit('go')
  await w.clock.settle()
  const d = dbg(w).filter(x => x.ev === 'deliver')
  expect(d.length).toBe(1)
  expect(d[0].channel).toBe('prompt.submit')
})

t('C85 the final nudge logs final=true on arm and deliver', async ($, on) => {
  const w = await nworld($, on)
  await atTool(w, 360_000)
  await w.clock.settle()
  const L = dbg(w)
  expect(L.filter(x => x.ev === 'arm').every(x => x.final === true)).toBe(true)
  expect(L.filter(x => x.ev === 'deliver').every(x => x.final === true)).toBe(true)
  expect(L.filter(x => x.ev === 'deliver').length).toBe(1)
})

t('C85 skip is logged at most once per distinct reason per cycle (subagent measures repeated)', async ($, on) => {
  const w = await nworld($, on)
  await w.measureAt(300_000, { agentId: 'sub-1' })
  await w.measureAt(310_000, { agentId: 'sub-1' })
  await w.measureAt(320_000, { agentId: 'sub-1' })
  await w.clock.settle()
  const sk = dbg(w).filter(x => x.ev === 'skip' && x.reason === 'agent_subagent')
  expect(sk.length).toBe(1)
})

t('C85 skip no_window is logged once per cycle when no window is knowable', async ($, on) => {
  const w = await world($, on, { env: {}, model: 'claude-mystery-9' })
  await w.start()
  await w.step()
  for (const n of [300_000, 310_000, 320_000]) await w.measureAt(n)
  await w.clock.settle()
  const sk = dbg(w).filter(x => x.ev === 'skip' && x.reason === 'no_window')
  expect(sk.length).toBe(1)
})

t('C85 nudge_debugLog=false: the file is never created, read, stat-ed or written', async ($, on) => {
  const w = await nworld($, on)
  await atTool(w, 300_000)
  await atTool(w, 360_000)
  await w.compact('manual')
  await w.clock.settle()
  expect(touchedDbg(w)).toBe(0)
  expect(w.S.files.has(DBG)).toBe(false)
}, { options: { nudge_debugLog: false } })

t('C85 mod_nudge_enabled=false: no debug file touched either', async ($, on) => {
  const w = await nworld($, on)
  await atTool(w, 300_000)
  await w.compact('manual')
  await w.clock.settle()
  expect(touchedDbg(w)).toBe(0)
}, { options: { mod_nudge_enabled: false } })

t('C85 a pre-existing 1,000,001-byte file is rotated to nudge-debug.1.jsonl (replacing an old one); the new file holds one line', async ($, on) => {
  const w = await nworld($, on)
  const big = 'x'.repeat(1_000_001)
  w.S.files.set(DBG, big)
  w.S.files.set(DBG1, 'old rotated content')
  await w.measureAt(300_000) // exactly one event: arm
  await w.clock.settle()
  expect(w.S.files.get(DBG1)).toBe(big)
  const txt = w.S.files.get(DBG) ?? ''
  const lines = txt.split('\n').filter(l => l.trim() !== '')
  expect(lines.length).toBe(1)
  expect(JSON.parse(lines[0]).ev).toBe('arm')
})

t('C85 a file at exactly 1,000,000 bytes is not rotated', async ($, on) => {
  const w = await nworld($, on)
  w.S.files.set(DBG, ('x'.repeat(999_999) + '\n'))
  await w.measureAt(300_000)
  await w.clock.settle()
  expect(w.S.files.has(DBG1)).toBe(false)
})

t('C85 debug-log write failures are swallowed: nothing throws, nudging continues', async ($, on) => {
  const w = await nworld($, on)
  w.S.failOps.add('fs.write')
  expect((await atTool(w, 300_000)).length).toBe(1)
  expect((await atTool(w, 325_000)).length).toBe(1)
  expect((await atTool(w, 360_000)).length).toBe(1)
  expect(ctxs(await w.submit('still fine')).length).toBe(0)
})

t('C85 the debug log adds no atom content and no UI: no toast, no notice, band unchanged by the mod', async ($, on) => {
  const w = await nworld($, on)
  await atTool(w, 300_000)
  await atTool(w, 360_000)
  await w.clock.settle()
  expect(w.S.toasts.length).toBe(0)
  expect(w.S.notices.length).toBe(0)
  expect(JSON.stringify(await w.state('nudge'))).not.toContain('nudge-debug')
})

// ---- 86 ----
// The amended C27 / C37 live in 33-nudge.body.ts. Here: the default itself, observed through every F33 option path.
t('C86 nudge_everyTokens explicit 25000 equals the default; clamp stays >= 10,000 (1000 -> steps of 10k)', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 300_000)).length).toBe(1)
  expect((await atTool(w, 309_999)).length).toBe(0)
  expect((await atTool(w, 310_000)).length).toBe(1)
  expect((await atTool(w, 320_000)).length).toBe(1)
}, { options: { nudge_everyTokens: 1000, nudge_finalPercent: 0 } })

t('C86 explicit nudge_everyTokens=50000 still gives the old steps (300k, 350k; none at 325k)', async ($, on) => {
  const w = await nworld($, on)
  expect((await atTool(w, 300_000)).length).toBe(1)
  expect((await atTool(w, 325_000)).length).toBe(0)
  expect((await atTool(w, 350_000)).length).toBe(1)
}, { options: { nudge_everyTokens: 50_000 } })
