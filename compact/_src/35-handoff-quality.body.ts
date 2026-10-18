// Statements 47-62: F35 handoff quality (spec compact.md F35.6). 58-60 are the PreCompact side and live in
// handoff-hooks/ (Python, ACs 31-48); 62's PreCompact half is there too. W = 400,000 via ENV400 (nworld).


/** Pure-JS SHA-256 (hex): the test module cannot rely on node builtins being importable. */
function sha256hex(str: string): string {
  const bytes: number[] = []
  for (const ch of str) {
    const c = ch.codePointAt(0) ?? 0
    if (c < 0x80) bytes.push(c)
    else if (c < 0x800) bytes.push(0xc0 | (c >> 6), 0x80 | (c & 63))
    else if (c < 0x10000) bytes.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63))
    else bytes.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63))
  }
  const K: number[] = []
  for (let n = 2, found = 0; found < 64; n++) {
    let prime = true
    for (let d = 2; d * d <= n; d++) if (n % d === 0) { prime = false; break }
    if (prime) { K.push(Math.floor((Math.cbrt(n) % 1) * 4294967296) >>> 0); found++ }
  }
  const H: number[] = []
  for (let n = 2, found = 0; found < 8; n++) {
    let prime = true
    for (let d = 2; d * d <= n; d++) if (n % d === 0) { prime = false; break }
    if (prime) { H.push(Math.floor((Math.sqrt(n) % 1) * 4294967296) >>> 0); found++ }
  }
  const bitLen = bytes.length * 8
  bytes.push(0x80)
  while (bytes.length % 64 !== 56) bytes.push(0)
  const hi = Math.floor(bitLen / 4294967296)
  const lo = bitLen >>> 0
  for (const v of [hi, lo]) bytes.push((v >>> 24) & 255, (v >>> 16) & 255, (v >>> 8) & 255, v & 255)
  const rotr = (x: number, n: number) => (x >>> n) | (x << (32 - n))
  for (let o = 0; o < bytes.length; o += 64) {
    const W: number[] = []
    for (let i = 0; i < 16; i++) W[i] = ((bytes[o + 4 * i] << 24) | (bytes[o + 4 * i + 1] << 16) | (bytes[o + 4 * i + 2] << 8) | bytes[o + 4 * i + 3]) >>> 0
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(W[i - 15], 7) ^ rotr(W[i - 15], 18) ^ (W[i - 15] >>> 3)
      const s1 = rotr(W[i - 2], 17) ^ rotr(W[i - 2], 19) ^ (W[i - 2] >>> 10)
      W[i] = (W[i - 16] + s0 + W[i - 7] + s1) >>> 0
    }
    let [a, b, c, d, e, f, g, h] = H.slice()
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
      const ch = (e & f) ^ (~e & g)
      const t1 = (h + S1 + ch + K[i] + W[i]) >>> 0
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
      const mj = (a & b) ^ (a & c) ^ (b & c)
      const t2 = (S0 + mj) >>> 0
      h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0
    }
    ;[a, b, c, d, e, f, g, h].forEach((v, i) => { H[i] = (H[i] + v) >>> 0 })
  }
  return H.map(v => v.toString(16).padStart(8, '0')).join('')
}

const IP = 'In progress'
const NS = 'Exact next step'
const STALE_SENTENCE =
  'Your last handoff is STALE: "In progress" and "Exact next step" are unchanged since the previous nudge; rewrite them from scratch, do not append.'
const DROP = 'Compaction will drop your working memory.'
const NAMES = ['Goal', 'Decisions and why', 'Done', 'In progress', 'Dead ends', 'Exact next step']

/** An agent file with the six exact headings; o overrides a section body, omit leaves headings out. */
function doc(o: Record<string, string> = {}, omit: string[] = []): string {
  const base: Record<string, string> = {
    'Goal': 'Ship the F35 handoff quality work for the compact plugin.',
    'Decisions and why': 'Hash the section bodies so staleness is detectable.',
    'Done': 'Spec approved. Contract tests drafted for the plugin side.',
    'In progress': 'Writing the nudge staleness tests in the compact folder.',
    'Dead ends': 'Comparing file mtimes only: too weak, agents append notes.',
    'Exact next step': 'Run run-contract.sh compact and read the failing names.',
  }
  let out = ''
  for (const n of NAMES) {
    if (omit.includes(n)) continue
    out += `## ${n}\n${o[n] ?? base[n]}\n\n`
  }
  return out
}

/** Reference hash per compact.md F35.1: 12 hex of sha256 over the section body, 'absent' when the heading is missing. */
function h12(text: string, name: string): string {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const i = lines.findIndex(l => l === `## ${name}`)
  if (i < 0) return 'absent'
  let j = i + 1
  while (j < lines.length && !lines[j].startsWith('## ')) j++
  const body = lines.slice(i + 1, j).join('\n').replace(/\s+$/, '')
  return sha256hex(body).slice(0, 12)
}

const F0 = doc()
const lastMeta = (w: W): Any => {
  const ms = metaWrites(w)
  return JSON.parse(ms[ms.length - 1].text)
}
/** Put the file on disk (optional), measure at t, one main tool call: returns the single nudge entry. */
async function deliver(w: W, tokens: number, file?: string): Promise<string> {
  if (file !== undefined) w.S.files.set(AGENT, file)
  const c = await atTool(w, tokens)
  await w.clock.settle()
  expect(c.length).toBe(1)
  return c[0]
}
const turns = async (w: W, n: number, text = 'small follow-up') => {
  for (let i = 0; i < n; i++) await w.submit(text)
}
const calls = async (w: W, n: number, agentId?: string) => {
  for (let i = 0; i < n; i++) await w.tool('Read', { file_path: '/work/repo/a.ts' }, agentId ? { agentId } : {})
}
const STALE_BOTH = [IP, NS]
const PENDING = `compact:pending:${SID}`
const firstPrompt = async (w: W, text = 'first after compaction'): Promise<string[]> => ctxs(await w.submit(text))

// ---- 47 ----
t('C47 hashes are 12 lowercase hex chars and equal the reference sha256 of the section body', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  const m = lastMeta(w)
  expect(Object.keys(m.sections).sort()).toEqual([...NAMES].sort())
  for (const n of NAMES) {
    expect(m.sections[n]).toMatch(/^[0-9a-f]{12}$/)
    expect(m.sections[n]).toBe(h12(F0, n))
  }
})

t('C47 changing only trailing whitespace of "In progress" leaves its stored hash unchanged', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  const before = lastMeta(w).sections
  const ws = F0.replace('## Dead ends', '   \n\n\t\n## Dead ends') // trailing whitespace at the end of the In progress body
  expect(ws).not.toBe(F0)
  await deliver(w, 350_000, ws)
  const after = lastMeta(w).sections
  expect(after[IP]).toBe(before[IP])
  expect(after).toEqual(before)
})

t('C47 CRLF line endings do not change a hash', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  const before = lastMeta(w).sections
  await deliver(w, 350_000, F0.replace(/\n/g, '\r\n'))
  expect(lastMeta(w).sections).toEqual(before)
})

t('C47 changing one byte of the body changes that hash (and only that one)', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  const before = lastMeta(w).sections
  await deliver(w, 350_000, doc({ [IP]: 'Writing the nudge staleness tests in the compact folder!' }))
  const after = lastMeta(w).sections
  expect(after[IP]).not.toBe(before[IP])
  expect(after[IP]).toMatch(/^[0-9a-f]{12}$/)
  for (const n of NAMES.filter(x => x !== IP)) expect(after[n]).toBe(before[n])
})

t('C47 a heading missing from the file stores "absent"', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, doc({}, ['Dead ends']))
  const m = lastMeta(w)
  expect(m.sections['Dead ends']).toBe('absent')
  expect(m.sections[IP]).toBe(h12(F0, IP))
})

// ---- 48 ----
t('C48 first nudge (300k): sections has six keys, no prevSections, stale_sections absent or [], userTurns 0, toolCalls 0', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  const m = lastMeta(w)
  expect(m.v).toBe(1)
  expect(Object.keys(m.sections).length).toBe(6)
  expect(m.prevSections).toBeUndefined()
  expect(m.stale_sections === undefined || (Array.isArray(m.stale_sections) && m.stale_sections.length === 0)).toBe(true)
  expect(m.userTurns).toBe(0)
  expect(m.toolCalls).toBe(0)
})

t('C48 second nudge moves sections into prevSections and resets the counters', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  const first = lastMeta(w).sections
  await turns(w, 1)
  await deliver(w, 350_000)
  const m = lastMeta(w)
  expect(m.prevSections).toEqual(first)
  expect(m.userTurns).toBe(0)
  expect(m.toolCalls).toBe(0)
})

// ---- 49 ----
t('C49 3 user turns between two nudges with both targets byte-identical: stale_sections = ["In progress","Exact next step"]', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  await turns(w, 3)
  await deliver(w, 350_000)
  expect(lastMeta(w).stale_sections).toEqual(STALE_BOTH)
})

t('C49 2 user turns and 39 tool calls: not stale', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  await turns(w, 2)
  await calls(w, 39)
  await deliver(w, 350_000)
  expect(lastMeta(w).stale_sections ?? []).toEqual([])
})

t('C49 empty prompt.submit texts are not user turns', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  await turns(w, 5, '')
  await deliver(w, 350_000)
  expect(lastMeta(w).stale_sections ?? []).toEqual([])
})

// ---- 50 ----
t('C50 40 main-loop tool calls and 0 user turns: stale', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  await calls(w, 40)
  await deliver(w, 350_000)
  expect(lastMeta(w).stale_sections).toEqual(STALE_BOTH)
})

t('C50 39 main-loop tool calls and 0 user turns: not stale', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  await calls(w, 39)
  await deliver(w, 350_000)
  expect(lastMeta(w).stale_sections ?? []).toEqual([])
})

t('C50 subagent (agentId) tool calls add nothing: 100 of them are not stale', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  await calls(w, 100, 'sub-1')
  await deliver(w, 350_000)
  expect(lastMeta(w).stale_sections ?? []).toEqual([])
})

t('C50 subagent tool calls do not top up main-loop ones: 39 main + 10 subagent is not stale', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  await calls(w, 39)
  await calls(w, 10, 'sub-1')
  await deliver(w, 350_000)
  expect(lastMeta(w).stale_sections ?? []).toEqual([])
})

// ---- 51 ----
t('C51 only "Exact next step" unchanged (In progress rewritten), 5 turns and 100 tool calls: not stale', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  await turns(w, 5)
  await calls(w, 100)
  await deliver(w, 350_000, doc({ [IP]: 'Now fixing the harness after the first run.' }))
  expect(lastMeta(w).stale_sections ?? []).toEqual([])
})

t('C51 only "In progress" unchanged (Exact next step rewritten): not stale', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  await turns(w, 5)
  await calls(w, 100)
  await deliver(w, 350_000, doc({ [NS]: 'Commit the tests and report.' }))
  expect(lastMeta(w).stale_sections ?? []).toEqual([])
})

t('C51 both targets rewritten: not stale', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  await turns(w, 5)
  await calls(w, 100)
  await deliver(w, 350_000, doc({ [IP]: 'Reviewing results.', [NS]: 'Report to the orchestrator.' }))
  expect(lastMeta(w).stale_sections ?? []).toEqual([])
})

t('C51 "Done" gaining appended text while both targets are unchanged: still stale', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  await turns(w, 3)
  await deliver(w, 350_000, doc({ Done: 'Spec approved. Contract tests drafted.\nDONE since: wrote 12 tests.\nDONE since: ran them.' }))
  expect(lastMeta(w).stale_sections).toEqual(STALE_BOTH)
})

// ---- 52 ----
function template(pct: string, tk: string, wk: string, verb: string): string {
  return (
    `[compact] Context is ${pct}% of the auto-compact window (${tk}k of ${wk}k). ${DROP} Now, in one Write call, ${verb} ${AGENT} (create the folder if missing) with exactly these headings: ## Goal, ## Decisions and why, ## Done, ## In progress, ## Dead ends, ## Exact next step. REWRITE "In progress" and "Exact next step" in place for the current state; never append "DONE since" notes. Move finished items to "Done". Keep the whole file under 5000 chars. Use real paths, commands and ids; no secrets. Then continue the task.`
  )
}

t('C52 normal nudge text equals the F35.3 template (file present: "update"), <= 640 chars, no STALE', async ($, on) => {
  const w = await nworld($, on)
  const c = await deliver(w, 300_000, F0)
  expect(norm(c)).toBe(norm(template('75', '300', '400', 'update')))
  expect(c.length).toBeLessThanOrEqual(640)
  expect(c).toContain('REWRITE "In progress" and "Exact next step" in place')
  expect(c).toContain('Move finished items to "Done"')
  expect(c).toContain('under 5000 chars')
  expect(c).not.toContain('STALE')
})

t('C52 normal nudge text with the file absent uses "write"', async ($, on) => {
  const w = await nworld($, on)
  const c = await deliver(w, 300_000)
  expect(norm(c)).toBe(norm(template('75', '300', '400', 'write')))
  expect(c).not.toContain('STALE')
})

// ---- 53 ----
t('C53 stale nudge: the STALE sentence follows "Compaction will drop your working memory.", rest equals the normal text, <= 780 chars', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  await turns(w, 3)
  const c = await deliver(w, 350_000)
  expect(c).toContain(STALE_SENTENCE)
  expect(c.indexOf(STALE_SENTENCE)).toBeGreaterThan(c.indexOf(DROP) + DROP.length - 1)
  expect(c.indexOf(STALE_SENTENCE) - (c.indexOf(DROP) + DROP.length)).toBeLessThanOrEqual(2)
  expect(c.length).toBeLessThanOrEqual(780)
  const m = c.match(/Context is (\d+)% of the auto-compact window \((\d+)k of (\d+)k\)/)
  expect(m).not.toBeNull()
  const rest = norm(c.replace(STALE_SENTENCE, ''))
  expect(rest).toBe(norm(template(m![1], m![2], m![3], 'update')))
})

t('C53 the stale nudge is delivered once per k: one entry, none on later calls', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  await turns(w, 3)
  await w.measureAt(350_000)
  const r = await w.tool('Read')
  expect(nudgesOf(r).length).toBe(1)
  expect(ctxs(await w.tool('Read')).length).toBe(0)
  expect(ctxs(await w.submit('again')).length).toBe(0)
})

t('C53 once the sections are rewritten the next nudge is the normal text again', async ($, on) => {
  const w = await nworld($, on)
  await deliver(w, 300_000, F0)
  await turns(w, 3)
  expect(await deliver(w, 350_000)).toContain('STALE')
  await turns(w, 3)
  const c = await deliver(w, 400_000, doc({ [IP]: 'Fresh state.', [NS]: 'Fresh next step.' }))
  expect(c).not.toContain('STALE')
  expect(lastMeta(w).stale_sections ?? []).toEqual([])
})

// ---- 54 ---- (nudge_everyTokens 40k keeps the F33.4 token rule out of the way: nudges at 300k, 340k)
const EVERY40 = { options: { nudge_everyTokens: 40_000 } }
/** Stale scenario: pre-seeded file, nudge 1, the model re-saves the file (only Done grows), 3 turns, nudge 2 at 340k. */
async function staleWorld(w: W): Promise<void> {
  await deliver(w, 300_000, F0)
  await w.advance(1000)
  await writeAgent(w, doc({ Done: 'Spec approved. Contract tests drafted.\nDONE since: wrote tests.' }))
  await turns(w, 3)
  const c = await deliver(w, 340_000)
  expect(c).toContain('STALE')
  expect(lastMeta(w).stale_sections).toEqual(STALE_BOTH)
}

t('C54 a detected write that changes both target hashes clears stale_sections at once', async ($, on) => {
  const w = await nworld($, on)
  await staleWorld(w)
  await w.advance(1000)
  await writeAgent(w, doc({ [IP]: 'Reviewing the results.', [NS]: 'Report to the orchestrator.' }))
  await w.measureAt(355_000)
  await w.clock.settle()
  expect(lastMeta(w).stale_sections ?? []).toEqual([])
}, EVERY40)

t('C54 a detected write that changes only "Done" does not clear stale_sections', async ($, on) => {
  const w = await nworld($, on)
  await staleWorld(w)
  await w.advance(1000)
  await writeAgent(w, doc({ Done: 'Spec approved.\nDONE since: more notes.\nDONE since: even more.' }))
  await w.measureAt(355_000)
  await w.clock.settle()
  expect(lastMeta(w).stale_sections).toEqual(STALE_BOTH)
}, EVERY40)

t('C54 a write changing only one target hash does not clear stale_sections', async ($, on) => {
  const w = await nworld($, on)
  await staleWorld(w)
  await w.advance(1000)
  await writeAgent(w, doc({ [IP]: 'Only this one changed.' }))
  await w.measureAt(355_000)
  await w.clock.settle()
  expect(lastMeta(w).stale_sections).toEqual(STALE_BOTH)
}, EVERY40)

// ---- 55 ----
/** nudge 1 with a pre-seeded file, the model saves the file at T, its mtime is pinned to T. Returns T. */
async function savedAtT(w: W): Promise<number> {
  await deliver(w, 300_000, F0)
  await w.advance(1000)
  await writeAgent(w, doc({ Done: 'Spec approved.\nDONE since: a note.' }))
  const T = w.now()
  w.S.mtimes.set(AGENT, T)
  return T
}

t('C55 lastUserMsgAt = T + 601,000 ms: not fresh: /coach says "agent file stale", no Resume entry, no pending key', async ($, on) => {
  const w = await nworld($, on)
  await savedAtT(w)
  await w.advance(601_000)
  await w.submit('a late user message')
  expect(norm(await w.cmd('coach'))).toContain('agent file stale')
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([])
  expect(w.S.kvSets).not.toContain(PENDING)
})

t('C55 lastUserMsgAt = T + 600,000 ms: fresh: Resume entry present', async ($, on) => {
  const w = await nworld($, on)
  await savedAtT(w)
  await w.advance(600_000)
  await w.submit('a user message exactly at the grace limit')
  expect(norm(await w.cmd('coach'))).toContain('agent file fresh')
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([AGENT_ENTRY])
})

t('C55 no user message at all (lastUserMsgAt absent): only the F33 rule applies, 700 s later it is still fresh', async ($, on) => {
  const w = await nworld($, on)
  await savedAtT(w)
  await w.advance(700_000)
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([AGENT_ENTRY])
})

// ---- 56 ----
t('C56 meta stale_sections non-empty (otherwise fresh): no Resume entry, no pending key', async ($, on) => {
  const w = await nworld($, on)
  await staleWorld(w)
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([])
  expect(w.S.kvSets).not.toContain(PENDING)
}, EVERY40)

t('C56 same file after stale_sections is cleared by a rewrite of both targets: Resume entry appears', async ($, on) => {
  const w = await nworld($, on)
  await staleWorld(w)
  await w.advance(1000)
  await writeAgent(w, doc({ [IP]: 'Reviewing the results.', [NS]: 'Report to the orchestrator.' }))
  await w.compact('manual')
  expect(await firstPrompt(w)).toEqual([AGENT_ENTRY])
}, EVERY40)

// ---- 57 ----
t('C57 a v1 meta (no sections, no counters, no lastUserMsgAt) already on disk is read without error and is not stale', async ($, on) => {
  const w = await nworld($, on)
  w.S.files.set(META, JSON.stringify({ v: 1, sessionId: SID, window: 400_000, lastNudgeTokens: 300_000, nudgeCount: 1, lastNudgeAt: w.now() - 1000 }))
  w.S.files.set(AGENT, BIG)
  const c = await atTool(w, 300_000)
  expect(c.length).toBe(1)
  expect(c[0]).not.toContain('STALE')
  await w.clock.settle()
  expect(lastMeta(w).stale_sections ?? []).toEqual([])
})

// ---- 61 ----
const SNAP61: Record<string, string> = {}
async function snap61(w: W, nCalls: number): Promise<string> {
  w.S.files.set(AGENT, F0)
  await w.scene({ cache: 'warm', phase: 'build', agents: 1, tokens: 300_000 })
  expect(nudgesOf(await w.tool('Read')).length).toBe(1)
  await calls(w, nCalls)
  await w.measureAt(350_000)
  await w.tool('Read')
  return JSON.stringify({ c: await w.state('coach'), b: await w.bands() })
}
t('C61 stale variant (40 calls): no toast, notice, submit or compact; band text and Coach state recorded', async ($, on) => {
  const w = await world($, on, { env: ENV400 })
  SNAP61.stale = await snap61(w, 40)
  expect((await w.state('nudge') as Any)).not.toBeNull()
  expect(w.S.toasts.length).toBe(0)
  expect(w.S.notices.length).toBe(0)
  expect(w.S.submitAttempts).toBe(0)
  expect(w.S.compactAttempts).toBe(0)
  expect(SNAP61.stale).not.toContain('STALE')
  const c: Any = await w.state('coach')
  expect(JSON.stringify(c.reasons ?? [])).not.toMatch(/stale|nudge|handoff/i)
})
t('C61 non-stale variant (39 calls): Coach state and band text are identical to the stale variant', async ($, on) => {
  const w = await world($, on, { env: ENV400 })
  const s = await snap61(w, 39)
  expect(SNAP61.stale).toBeDefined()
  expect(s).toBe(SNAP61.stale)
})

// ---- 62 ----
t('C62 mod_nudge_enabled=false: with a stale-shaped session (file present, 5 turns, 100 tool calls) no meta, no sections, no counters, no atom', async ($, on) => {
  const w = await nworld($, on)
  w.S.files.set(AGENT, F0)
  for (const n of [300_000, 350_000]) {
    await w.measureAt(n)
    await turns(w, 5)
    await calls(w, 50)
  }
  await w.tool('Write', { file_path: AGENT, content: F0 })
  await w.measureAt(380_000)
  await w.clock.settle()
  expect(handoffDirWrites(w).length).toBe(0)
  expect(metaWrites(w).length).toBe(0)
  expect(await w.state('nudge')).toBeNull()
  const r = await w.tool('Read', {}, { inner: { result: 'ok', text: 'ok', context: ['keep'] } })
  expect(ctxs(r)).toEqual(['keep'])
}, { options: { mod_nudge_enabled: false } })
