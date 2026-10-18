// Statements 63-78: F36 degraded handoff alert (spec compact.md F36.8, mod `handoffalert`).
// The hook side (writing <sid>-degraded.json) is tested in handoff-hooks/ (Python). Here the file is a mocked $.fs entry.

const DEG_DIR = `${HOME}/.local/state/claude-handoffs`
const degPath = (sid = SID): string => `${DEG_DIR}/${sid.replace(/\//g, '_')}-degraded.json`
const isoZ = (ms: number): string => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z')
const CHIP = 'HANDOFF DEGRADED'
const AB_FF = ['agent_absent', 'fallback_failed']
const AB_FF_TEXT = 'no agent handoff; Haiku fallback failed'
const REASON_TEXT: Record<string, string> = {
  agent_absent: 'no agent handoff',
  agent_stale: 'agent handoff stale',
  fallback_failed: 'Haiku fallback failed',
  fallback_timeout: 'Haiku fallback timed out',
  no_health: 'no health record for this compaction',
  handoff_missing: 'no handoff file for this session',
  handoff_old: 'handoff not refreshed for this compaction',
}

/** Put a degraded file in the mocked fs. ts defaults to 1 s before the clock (whole seconds: the file has no ms). */
function putDeg(w: W, fields: Record<string, unknown> = {}, tsMs: number = w.now() - 1000, sid = SID): number {
  const body = { v: 1, sid: sid.replace(/\//g, '_'), ts: isoZ(tsMs), reasons: AB_FF, trigger: 'auto', detected_by: 'inject', ...fields }
  w.S.files.set(degPath(sid), JSON.stringify(body))
  return Date.parse(String(body.ts))
}
const degToasts = (w: W) => w.S.toasts.filter(x => x.text.startsWith(CHIP))
const touches = (w: W, sid = SID) => w.S.fsLog.filter(x => x.path === degPath(sid) && x.op !== 'fs.write')
const readTimes = (w: W): number[] => [...new Set(touches(w).map(x => x.at))].sort((a, b) => a - b)
const degWrites = (w: W) => w.S.writes.filter(x => x.path === degPath())
const hh = async (w: W): Promise<Any> => w.state('handoffHealth')
const active = async (w: W): Promise<boolean | undefined> => (await hh(w))?.degraded
const handoffLast = (w: W, savedAt: number) => w.S.kv.set(`handoff:last:${SID}`, { v: 1, path: PATH_FOO, savedAt })
const noChip = async (w: W) => {
  for (const s of SURFACES) expect(await w.band(s)).not.toContain(CHIP)
}

// ---- 63 ----
t('C63 degraded file at session.start: one toast, chip first on both surfaces, atom with reasons and since', async ($, on) => {
  const w = await world($, on)
  const ts = putDeg(w, { reasons: AB_FF })
  await w.start()
  await w.drain()
  expect(degToasts(w).length).toBe(1)
  expect(degToasts(w)[0].text).toBe(`HANDOFF DEGRADED · ${AB_FF_TEXT}`)
  for (const s of SURFACES) {
    const b = await w.band(s)
    expect(b.startsWith('HANDOFF DEGRADED · no agent handoff +1')).toBe(true)
  }
  const h = await hh(w)
  expect(h.degraded).toBe(true)
  expect(h.reasons).toEqual(['no agent handoff', 'Haiku fallback failed'])
  expect(h.since).toBe(ts)
  expect(Object.keys(h).sort()).toEqual(['degraded', 'reasons', 'since'])
  expect(JSON.stringify(h)).not.toContain('/')
  expect(JSON.stringify(h)).not.toContain('claude-handoffs')
})

t('C63 a single reason shows no +n on the chip', async ($, on) => {
  const w = await world($, on)
  putDeg(w, { reasons: ['agent_absent'] })
  await w.start()
  await w.drain()
  for (const s of SURFACES) {
    const b = await w.band(s)
    expect(b.startsWith('HANDOFF DEGRADED · no agent handoff')).toBe(true)
    expect(b.slice(0, 60)).not.toMatch(/\+\d/)
  }
  expect(degToasts(w)[0].text).toBe('HANDOFF DEGRADED · no agent handoff')
})

// ---- 64 ----
const BAD: [string, string | null][] = [
  ['missing file', null],
  ['invalid JSON', '{not json'],
  ['array', '[1,2]'],
  ['number', '5'],
  ['null', 'null'],
  ['v:2', JSON.stringify({ v: 2, sid: SID, ts: '2026-10-12T11:59:59Z', reasons: AB_FF, trigger: 'auto', detected_by: 'inject' })],
  ['no ts', JSON.stringify({ v: 1, sid: SID, reasons: AB_FF, trigger: 'auto', detected_by: 'inject' })],
  ['clearedAt set', JSON.stringify({ v: 1, sid: SID, ts: '2026-10-12T11:59:59Z', reasons: AB_FF, trigger: 'auto', detected_by: 'inject', clearedAt: '2026-10-12T11:59:59Z' })],
]
for (const [label, raw] of BAD) {
  t(`C64 ${label}: no toast, no chip, atom degraded false, nothing thrown`, async ($, on) => {
    const w = await world($, on)
    if (raw !== null) w.S.files.set(degPath(), raw)
    await w.start()
    await w.measure()
    await w.drain()
    await w.submit('go')
    expect(degToasts(w).length).toBe(0)
    await noChip(w)
    expect(await active(w)).toBe(false)
  })
}
t('C64 unreadable file (fs.read rejects): logs exactly one more line than the missing case, no toast, no chip', async ($, on) => {
  const w = await world($, on)
  await w.start()
  const base = w.S.logs.length
  const w2 = w
  w2.S.files.set(degPath(), JSON.stringify({ v: 1, sid: SID, ts: isoZ(w.now() - 1000), reasons: AB_FF }))
  w2.S.failOps.add('fs.read')
  await w2.start()
  await w2.drain()
  expect(w2.S.logs.length - base).toBe(1)
  expect(degToasts(w2).length).toBe(0)
  await noChip(w2)
  expect(await active(w2)).toBe(false)
})

// ---- 65 ----
t('C65 once per episode: restart, measures and prompts with the same ts raise no second toast; the key holds ts', async ($, on) => {
  const w = await world($, on)
  const ts = putDeg(w)
  await w.start()
  await w.drain()
  expect(degToasts(w).length).toBe(1)
  await w.start()
  for (let i = 0; i < 4; i++) {
    await w.advance(6000)
    await w.measure()
  }
  await w.submit('p1')
  await w.submit('p2')
  await w.drain()
  expect(degToasts(w).length).toBe(1)
  const shown = w.S.kv.get(`handoff:degradedShown:${SID}`) as Any
  expect(shown.v).toBe(1)
  expect([ts, isoZ(ts)]).toContain(shown.ts)
  expect(Object.keys(shown).sort()).toEqual(['ts', 'v'])
})

t('C65 a newer file after a later compaction raises a second toast', async ($, on) => {
  const w = await world($, on)
  putDeg(w)
  await w.start()
  await w.drain()
  expect(degToasts(w).length).toBe(1)
  await w.advance(10 * MIN)
  await w.compact('auto')
  await w.advance(6000)
  putDeg(w, { reasons: ['agent_stale'] }, w.now() - 1000)
  await w.measure()
  await w.drain()
  expect(degToasts(w).length).toBe(2)
  expect(degToasts(w)[1].text).toBe('HANDOFF DEGRADED · agent handoff stale')
})

t('C65 toast text is at most 140 chars, cut with "..." and matches the prefix pattern', async ($, on) => {
  const w = await world($, on)
  putDeg(w, { reasons: Object.keys(REASON_TEXT).concat(['section_errors']) })
  await w.start()
  await w.drain()
  const x = degToasts(w)
  expect(x.length).toBe(1)
  expect(x[0].text).toMatch(/^HANDOFF DEGRADED · .+/)
  expect(x[0].text.length).toBeLessThanOrEqual(140)
  expect(x[0].text.endsWith('...')).toBe(true)
})

// ---- 66 ----
for (const trig of ['auto', 'manual', 'plugin']) {
  t(`C66 ${trig} compaction: file written 2 s later is found by a measure at least 5 s after the last read`, async ($, on) => {
    const w = await world($, on)
    await w.start()
    await w.drain()
    await w.advance(MIN)
    w.S.fsLog.length = 0
    const tc = w.now()
    await w.compact(trig)
    await w.advance(2000)
    await w.measure() // within 5 s of the last read: no read
    expect(readTimes(w).filter(x => x === tc + 2000)).toEqual([])
    putDeg(w, {}, w.now())
    expect(degToasts(w).length).toBe(0)
    await w.advance(4000) // tc + 6 s
    await w.measure()
    await w.drain()
    expect(degToasts(w).length).toBe(1)
    expect(await active(w)).toBe(true)
    expect(readTimes(w)).toContain(tc + 6000)
  })
}
t('C66 never more than 3 further reads for one compaction', async ($, on) => {
  const w = await world($, on)
  await w.start()
  await w.drain()
  await w.advance(MIN)
  w.S.fsLog.length = 0
  const tc = w.now()
  await w.compact('auto')
  for (let i = 0; i < 8; i++) {
    await w.advance(6000)
    await w.measure()
  }
  const further = readTimes(w).filter(x => x > tc)
  expect(further.length).toBe(3)
})
for (const kind of ['skip', 'precompute', 'agentId'] as const) {
  t(`C66 ${kind} compactions read nothing`, async ($, on) => {
    const w = await world($, on)
    await w.start()
    await w.drain()
    await w.advance(MIN)
    w.S.fsLog.length = 0
    if (kind === 'skip') {
      w.S.compact = 'skip'
      await w.compact('auto')
    } else if (kind === 'precompute') {
      await w.compact('precompute')
    } else {
      await w.compact('auto', { agentId: 'a1' })
    }
    for (let i = 0; i < 4; i++) {
      await w.advance(6000)
      await w.measure()
    }
    expect(touches(w).length).toBe(0)
  })
}
t('C66 no per-measure reads without a compaction, with or without an active alert', async ($, on) => {
  const w = await world($, on)
  await w.start()
  await w.drain()
  w.S.fsLog.length = 0
  for (let i = 0; i < 5; i++) {
    await w.advance(6000)
    await w.measure()
  }
  expect(touches(w).length).toBe(0)
  putDeg(w)
  await w.start()
  await w.drain()
  w.S.fsLog.length = 0
  for (let i = 0; i < 5; i++) {
    await w.advance(6000)
    await w.measure()
  }
  expect(touches(w).length).toBe(0)
})

// ---- 67 ----
t('C67 /handoff saved after ts clears the alert, rewrites the file once with clearedAt, no toast', async ($, on) => {
  const w = await world($, on)
  putDeg(w)
  const original = JSON.parse(w.S.files.get(degPath()) as string)
  await w.start()
  await w.drain()
  expect(await active(w)).toBe(true)
  const toasts = w.S.toasts.length
  handoffLast(w, w.now())
  await w.submit('after handoff')
  await w.drain()
  expect(await active(w)).toBe(false)
  await noChip(w)
  expect(degWrites(w).length).toBe(1)
  const after = JSON.parse(degWrites(w)[0].text)
  expect(typeof after.clearedAt).toBe('string')
  const { clearedAt, ...rest } = after
  expect(rest).toEqual(original)
  expect(w.S.toasts.length).toBe(toasts)
})
t('C67 savedAt not later than ts: still active, no rewrite', async ($, on) => {
  const w = await world($, on)
  const ts = putDeg(w)
  await w.start()
  await w.drain()
  handoffLast(w, ts)
  await w.submit('p')
  await w.measure()
  await w.drain()
  expect(await active(w)).toBe(true)
  expect(degWrites(w).length).toBe(0)
})

// ---- 68 ----
t('C68 agent file rewritten after ts (>= 300 bytes, fresh) clears the alert at the next prompt', async ($, on) => {
  const w = await world($, on)
  putDeg(w)
  await w.start()
  await w.drain()
  expect(await active(w)).toBe(true)
  await w.advance(MIN)
  await writeAgent(w, BIG)
  await w.submit('next')
  await w.drain()
  expect(await active(w)).toBe(false)
  await noChip(w)
  expect(degWrites(w).length).toBe(1)
  expect(typeof JSON.parse(degWrites(w)[0].text).clearedAt).toBe('string')
})
t('C68 an agent write before ts does not clear', async ($, on) => {
  const w = await world($, on)
  await w.start()
  await writeAgent(w, BIG)
  await w.advance(MIN)
  putDeg(w, {}, w.now() - 1000)
  await w.start()
  await w.drain()
  expect(await active(w)).toBe(true)
  await w.submit('next')
  await w.measure()
  await w.drain()
  expect(await active(w)).toBe(true)
})
t('C68 an agent file under 300 bytes does not clear', async ($, on) => {
  const w = await world($, on)
  putDeg(w)
  await w.start()
  await w.drain()
  await w.advance(MIN)
  await writeAgent(w, 'x'.repeat(100))
  await w.submit('next')
  await w.measure()
  await w.drain()
  expect(await active(w)).toBe(true)
})
t('C68 a stale agent file (F35.4 grace failed: older than the last user message by > 10 min) does not clear', async ($, on) => {
  const w = await world($, on)
  putDeg(w)
  await w.start()
  await w.drain()
  await w.advance(MIN)
  const written = w.now()
  await writeAgent(w, BIG)
  w.S.mtimes.set(AGENT, written)
  await w.advance(12 * MIN)
  await w.submit('a much later user message')
  await w.measure()
  await w.drain()
  expect(await active(w)).toBe(true)
})

// ---- 69 ----
t('C69 rewrite of clearedAt failing: cleared in memory, one log line, no throw; (the return at a process restart cannot be simulated in-process)', async ($, on) => {
  const w = await world($, on)
  putDeg(w)
  await w.start()
  await w.drain()
  const toasts = w.S.toasts.length
  const logs = w.S.logs.length
  w.S.failOps.add('fs.write')
  handoffLast(w, w.now())
  await w.submit('after handoff')
  await w.drain()
  expect(await active(w)).toBe(false)
  await noChip(w)
  expect(w.S.logs.length - logs).toBe(1)
  expect(JSON.parse(w.S.files.get(degPath()) as string).clearedAt).toBeUndefined()
})

// ---- 70 ----
t('C70 chip is the first band segment (<= 60 chars) and the rest of the band is unchanged', async ($, on) => {
  const w = await world($, on)
  await w.scene({ tokens: 350_000, cache: 'cold', phase: 'build' })
  const P = { bodyColumns: 400 } // room for the chip: the other segments must not be shortened to make space
  const before = { terminal: await w.band('terminal', P), desktop: await w.band('desktop', P) }
  putDeg(w, { reasons: ['agent_absent'] })
  await w.start()
  await w.drain()
  const chip = 'HANDOFF DEGRADED · no agent handoff'
  for (const s of SURFACES) {
    const b = await w.band(s, P)
    expect(b.startsWith(chip)).toBe(true)
    expect(chip.length).toBeLessThanOrEqual(60)
    expect(b.slice(chip.length)).toContain(before[s])
  }
})
t('C70 no-band fallback: ui.status is prefixed only while surfaces() is empty and cleared once when a surface appears', async ($, on) => {
  const w = await world($, on, { surface: null })
  putDeg(w, { reasons: ['agent_absent'] })
  await w.scene({ tokens: 350_000, cache: 'cold', phase: 'build' })
  await w.measure()
  await w.drain()
  const set = w.S.statuses.filter(x => !!x) as string[]
  expect(set.length).toBeGreaterThan(0)
  expect(set[set.length - 1].startsWith('HANDOFF DEGRADED · no agent handoff · ')).toBe(true)
  expect(set[set.length - 1]).toContain('CTX')
  w.S.surface = 'terminal'
  await w.measure()
  await w.drain()
  expect(w.S.statuses[w.S.statuses.length - 1]).toBeUndefined()
})

// ---- 71 ----
t('C71 Coach state and toasts are identical with the alert active and inactive', async ($, on) => {
  const w = await world($, on)
  await w.scene({ tokens: 350_000, cache: 'cold', phase: 'build' })
  await w.measure()
  await w.complete()
  await w.drain()
  await w.start()
  await w.drain()
  const c1 = await w.state('coach')
  const coachToasts1 = w.S.toasts.filter(x => !x.text.startsWith(CHIP)).map(x => x.text)
  putDeg(w)
  await w.start()
  await w.drain()
  const c2 = await w.state('coach')
  const coachToasts2 = w.S.toasts.filter(x => !x.text.startsWith(CHIP)).map(x => x.text)
  expect(c2).toEqual(c1)
  expect(coachToasts2).toEqual(coachToasts1)
  expect(degToasts(w).length).toBe(1)
})
t('C71 peer gap: dev.toast.lastShownAt = now-10s queues the handoff toast to now+50 s, chip visible at once', async ($, on) => {
  const w = await world($, on)
  await w.start()
  await w.peer('dev', 'toast', { lastShownAt: w.now() - 10_000, shown: 1, held: 0 })
  putDeg(w)
  await w.start()
  expect(await w.band('terminal')).toContain(CHIP)
  expect(degToasts(w).length).toBe(0)
  await w.advance(40_000)
  expect(degToasts(w).length).toBe(0)
  await w.advance(12_000)
  expect(degToasts(w).length).toBe(1)
})
t('C71 focus phase delays the toast, chip visible at once, no Coach lastShownAt written', async ($, on) => {
  const w = await world($, on)
  await w.start()
  await w.peer('awareness', 'focus', { phase: 'focus', count: 1, ofTotal: 4 })
  putDeg(w)
  await w.start()
  await w.advance(3 * MIN)
  expect(degToasts(w).length).toBe(0)
  expect(await w.band('terminal')).toContain(CHIP)
  const c = await w.state('coach')
  expect(c?.lastShownAt).toBeUndefined()
  expect(w.S.kv.has('coach:toast')).toBe(false)
})
t('C71 headsup.mutedUntil in the future delays the toast; it is shown after the mute ends', async ($, on) => {
  const w = await world($, on)
  await w.start()
  await w.peer('awareness', 'headsup', { mutedUntil: w.now() + 10 * MIN, queued: [], shown: 0 })
  putDeg(w)
  await w.start()
  await w.advance(3 * MIN)
  expect(degToasts(w).length).toBe(0)
  expect(await w.band('terminal')).toContain(CHIP)
  await w.advance(10 * MIN)
  await w.measure()
  await w.drain()
  expect(degToasts(w).length).toBe(1)
})
t('C71 the handoff toast ignores the Coach 20-minute rule and does not write coach:toast', async ($, on) => {
  const w = await world($, on)
  await w.scene({ tokens: 350_000, cache: 'cold', phase: 'build' })
  await w.measure()
  await w.complete()
  await w.drain()
  const before = JSON.stringify(w.S.kv.get('coach:toast') ?? null)
  const coachToasts = w.S.toasts.length
  putDeg(w)
  await w.start()
  await w.drain()
  await w.advance(2 * MIN)
  await w.drain()
  expect(degToasts(w).length).toBe(1)
  expect(JSON.stringify(w.S.kv.get('coach:toast') ?? null)).toBe(before)
  expect(w.S.toasts.length).toBeGreaterThanOrEqual(coachToasts + 1)
})

// ---- 72 ----
for (const key of ['mod_handoffalert_enabled', 'mod.handoffalert.enabled']) {
  t(`C72 off switch (${key}=false): no read, no write, no toast, no chip, no atom, no /coach line`, async ($, on) => {
    const w = await world($, on)
    putDeg(w)
    await w.start()
    await w.measure()
    await w.compact('auto')
    await w.submit('p')
    await w.drain()
    expect(w.S.fsLog.filter(x => x.path.endsWith('-degraded.json')).length).toBe(0)
    expect(degWrites(w).length).toBe(0)
    expect(degToasts(w).length).toBe(0)
    await noChip(w)
    expect(await hh(w)).toBeNull()
    expect(await w.cmd('coach')).not.toContain('handoff health')
  }, { options: { [key]: false } })
}
t('C72 on by default: /coach has the handoff health line', async ($, on) => {
  const w = await world($, on)
  await w.start()
  expect(await w.cmd('coach')).toContain('handoff health: ok')
})

// ---- 73 ----
t('C73 never blocks: no submit, compact, notice, model or agent calls; tool results and prompts untouched', async ($, on) => {
  const w = await world($, on)
  putDeg(w)
  const { calls } = await w.trace(async () => {
    await w.start()
    await w.drain()
    await w.measure()
    await w.submit('go')
    await w.tool('Read', { file_path: '/work/repo/a.ts' })
  })
  expect(w.S.submitAttempts).toBe(0)
  expect(w.S.compactAttempts).toBe(0)
  expect(w.S.notices.length).toBe(0)
  expect(calls.filter(c => c.startsWith('model.') || c === 'agent.spawn' || c === 'ui.notice' || c === 'session.compact')).toEqual([])
  const r = await w.tool('Read', { file_path: '/work/repo/a.ts' })
  expect(r).toEqual({ result: 'ok', text: 'ok' })
  const p = await w.submit('another')
  expect(ctxs(p).filter(c => c.includes('HANDOFF') || c.includes('handoff health'))).toEqual([])
})

// ---- 74 ----
for (const op of ['fs.read', 'env.get', 'session.id']) {
  t(`C74 ${op} rejecting: nothing thrown, results unchanged (no toast, no chip)`, async ($, on) => {
    const w = await world($, on)
    putDeg(w)
    w.S.failOps.add(op)
    await w.start()
    await w.measure()
    await w.compact('auto')
    await w.submit('go')
    await w.drain()
    expect(degToasts(w).length).toBe(0)
    await noChip(w)
    expect((await hh(w))?.degraded ?? false).toBe(false)
  })
}

// ---- 75 ----
t('C75 /coach: "handoff health: ok" without an alert, the DEGRADED line with one', async ($, on) => {
  const w = await world($, on)
  await w.start()
  expect(await w.cmd('coach')).toContain('handoff health: ok')
  putDeg(w)
  await w.start()
  await w.drain()
  const txt = await w.cmd('coach')
  expect(txt).toContain(`handoff health: DEGRADED: ${AB_FF_TEXT}`)
  expect(txt).not.toContain('handoff health: ok')
})

// ---- 76 ----
t('C76 a degraded file of another session id never alerts', async ($, on) => {
  const w = await world($, on)
  putDeg(w, {}, w.now() - 1000, 'other-sess')
  await w.start()
  await w.measure()
  await w.drain()
  expect(degToasts(w).length).toBe(0)
  expect(await active(w)).toBe(false)
  await noChip(w)
})
t('C76 a session id with "/" is read as "_"', async ($, on) => {
  const w = await world($, on, { sid: 'a/b' })
  putDeg(w, {}, w.now() - 1000, 'a/b')
  expect(degPath('a/b').endsWith('/a_b-degraded.json')).toBe(true)
  await w.start()
  await w.drain()
  expect(degToasts(w).length).toBe(1)
  expect(await active(w)).toBe(true)
})

// ---- 77 ----
t('C77 headless: atom and /coach line are correct; no toast or chip is drawn', async ($, on) => {
  const w = await world($, on, { surface: null, interactive: false })
  putDeg(w)
  await w.start()
  await w.drain()
  expect(await active(w)).toBe(true)
  expect((await hh(w)).reasons).toEqual(['no agent handoff', 'Haiku fallback failed'])
  expect(degToasts(w).length).toBe(0)
  expect(await w.cmd('coach')).toContain(`handoff health: DEGRADED: ${AB_FF_TEXT}`)
})

// ---- 78 ----
for (const [code, text] of Object.entries(REASON_TEXT)) {
  t(`C78 hook reason code ${code} reads as "${text}"`, async ($, on) => {
    const w = await world($, on)
    putDeg(w, { reasons: [code] })
    await w.start()
    await w.drain()
    expect(degToasts(w).length).toBe(1)
    expect(degToasts(w)[0].text).toBe(`HANDOFF DEGRADED · ${text}`)
  })
}
t('C78 section_errors reads as "sections unavailable"', async ($, on) => {
  const w = await world($, on)
  putDeg(w, { reasons: ['section_errors'] })
  await w.start()
  await w.drain()
  expect(degToasts(w).length).toBe(1)
  expect(degToasts(w)[0].text).toMatch(/^HANDOFF DEGRADED · sections unavailable/)
})
t('C78 a hook-written ok or reduced run leaves no file: no alert, no toast, no chip', async ($, on) => {
  const w = await world($, on)
  await w.start()
  await w.measure()
  await w.compact('auto')
  await w.advance(6000)
  await w.measure()
  await w.drain()
  expect(degToasts(w).length).toBe(0)
  await noChip(w)
  expect(await active(w)).toBe(false)
})
