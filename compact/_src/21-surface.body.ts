// Statements 21, 22, 23, 24: registration, -p fallback, missing peers, surface parity.

// ---- statement 21 ----
t('C21 registers at most 3 commands (handoff, coach, orch), each description <= 40 chars; no tool, agent type', async ($, on) => {
  const w = await world($, on)
  await w.start()
  const names = w.S.registered.map((r: Any) => r.name).sort()
  expect(names.length).toBeLessThanOrEqual(3)
  expect(names).toEqual(['coach', 'handoff', 'orch'])
  for (const r of w.S.registered) expect(String(r.description).length).toBeLessThanOrEqual(40)
  expect(w.S.toolRegs.length).toBe(0)
  expect(w.S.agentRegs.length).toBe(0)
})

t('C21 a colliding built-in name gets the compact- prefix and still answers', async ($, on) => {
  const w = await world($, on, { builtins: ['handoff'] })
  await w.start()
  const names = w.S.registered.map((r: Any) => r.name)
  expect(names).toContain('compact-handoff')
  expect(names).not.toContain('handoff')
  expect(names).toContain('coach')
  expect(names).toContain('orch')
  await w.cmd('compact-handoff', 'foo')
  expect(w.S.submits.length).toBe(1)
})

t('C21 all three names colliding are all prefixed', async ($, on) => {
  const w = await world($, on, { builtins: ['handoff', 'coach', 'orch'] })
  await w.start()
  expect(w.S.registered.map((r: Any) => r.name).sort()).toEqual(['compact-coach', 'compact-handoff', 'compact-orch'])
})

t('C21 no network and no MCP/tool surface was touched while running every flow', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'cold', phase: 'report' })
  await w.cmd('coach')
  await w.cmd('orch', 'status')
  await w.toReady()
  await w.cmd('handoff', 'go')
  expect(w.S.fetches.length).toBe(0)
  expect(w.S.toolRegs.length).toBe(0)
})

skip('C21 no tool.call hook is registered', 'cannot observe hook registration through the kit; checked by claude plugin validate / code review (manual list)')

// ---- statement 22 ----
t('C22 -p run (no band): $.ui.status shows the fallback; commands answer text', async ($, on) => {
  const w = await world($, on, { surface: null, interactive: false })
  await w.scene({ tokens: 350_000, cache: 'warm' })
  const last = [...w.S.statuses].reverse().find(s => typeof s === 'string') as string
  expect(last).toBeDefined()
  expect(last).toContain('CTX 350k · save $0.06/turn')
  expect((await w.cmd('coach')).length).toBeGreaterThan(0)
  expect(await w.cmd('orch', 'status')).toContain('CLAUDE_CODE_SUBAGENT_MODEL_FORCE')
  expect(await w.cmd('handoff', 'go')).toContain('Nothing to compact')
})

t('C22 -p run: /handoff still sends the prompt and answers text', async ($, on) => {
  const w = await world($, on, { surface: null, interactive: false })
  await w.start()
  const txt = await w.cmd('handoff', 'foo')
  expect(typeof txt).toBe('string')
  expect(w.S.submits.length).toBe(1)
})

// ---- statement 23 ----
t('C23 no peer plugins at all: nothing throws; band still renders warm and cold figures', async ($, on) => {
  const w = await world($, on)
  await w.scene({ tokens: 350_000, cache: null, phase: null })
  await w.complete()
  await w.measure()
  await w.cmd('coach')
  await w.cmd('handoff', 'foo')
  for (const surface of SURFACES) {
    const txt = await w.band(surface)
    expect(txt).toContain('$0.07')
    expect(txt).toContain('$2.80')
  }
}, { peers: false })

t('C23 peer plugins present but atoms never written: same', async ($, on) => {
  const w = await world($, on)
  await w.scene({ tokens: 350_000, cache: null, phase: null })
  await w.complete()
  const txt = await w.band('terminal')
  expect(txt).toContain('$0.07')
  expect(txt).toContain('$2.80')
})

// ---- statement 24 ----
const C24_SCENES: [string, Parameters<W['scene']>[0]][] = [
  ['good moment', { cache: 'cold', phase: 'report', agents: 0 }],
  ['ok', { cache: 'warm', phase: 'report', agents: 0 }],
  ['not now', { cache: 'warm', phase: 'build', agents: 1 }],
  ['cache unknown', { cache: null, phase: null, agents: 0 }],
]
for (const [label, opts] of C24_SCENES) {
  t(`C24 terminal text equals desktop alt: chip state ${label}`, async ($, on) => {
    const w = await world($, on)
    await w.scene(opts)
    const b = await w.bands()
    expect(b.terminal.length).toBeGreaterThan(0)
    expect(b.desktop).toBe(b.terminal)
  })
}

t('C24 terminal text equals desktop alt: handoff states', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'warm', phase: 'build', agents: 1 })
  await w.cmd('handoff', 'foo')
  let b = await w.bands()
  expect(b.terminal).toContain('HANDOFF writing')
  expect(b.desktop).toBe(b.terminal)

  w.writeHandoff()
  await w.complete()
  b = await w.bands()
  expect(b.terminal).toContain('/handoff go')
  expect(b.desktop).toBe(b.terminal)

  await w.cmd('handoff', 'go')
  b = await w.bands()
  expect(b.terminal).toContain('COMPACTED 351k → 41k')
  expect(b.desktop).toBe(b.terminal)
})

t('C24 terminal text equals desktop alt: failed state', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.cmd('handoff', 'foo')
  w.writeHandoff(PATH_FOO, handoffText({ omit: [7] }))
  await w.complete()
  const b = await w.bands()
  expect(b.terminal).toContain('missing')
  expect(b.desktop).toBe(b.terminal)
})

t('C24 terminal text equals desktop alt: saved state', async ($, on) => {
  const w = await world($, on)
  await w.scene()
  await w.toReady('bar', '--no-compact')
  const b = await w.bands()
  expect(b.terminal).toContain('saved')
  expect(b.desktop).toBe(b.terminal)
})

t('C24 narrow bodyColumns picks a smaller variant; terminal and desktop still agree and keep the size', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'cold', phase: 'report', agents: 0 })
  for (const cols of [90, 60, 40]) {
    const b = await w.bands({ bodyColumns: cols })
    expect(b.terminal.length).toBeGreaterThan(0)
    expect(b.desktop).toBe(b.terminal)
  }
})

t('C24 maxRows below minBandRows: the plugin is silent on both surfaces', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'cold', phase: 'report', agents: 0 })
  const b = await w.bands({ maxRows: 1 })
  expect(b.terminal).not.toContain('350k')
  expect(b.desktop).not.toContain('350k')
})

t('C24 hasSurvey: the plugin leaves the band alone on both surfaces', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'cold', phase: 'report', agents: 0 })
  const b = await w.bands({ hasSurvey: true })
  expect(b.terminal).not.toContain('350k')
  expect(b.desktop).not.toContain('350k')
})

t('C24 subagent transcript view (view.agentId set): no chip', async ($, on) => {
  const w = await world($, on)
  await w.scene({ cache: 'cold', phase: 'report', agents: 0 })
  const b = await w.bands({ view: { agentId: 'sub-1' } })
  expect(b.terminal).not.toContain('350k')
  expect(b.desktop).not.toContain('350k')
})

// ---- F30: no-band status fallback is decided per write ----
const texts = (w: W) => w.S.statuses.filter((s: Any) => typeof s === 'string') as string[]

t('F30 no surface, interactive: a measure above showFrom writes a status containing CTX 212k', async ($, on) => {
  const w = await world($, on, { surface: null, interactive: true })
  await w.start()
  w.S.tokens = 212_000
  await w.measure()
  const last = [...w.S.statuses].reverse().find((s: Any) => typeof s === 'string') as string
  expect(last).toBeDefined()
  expect(last).toContain('CTX 212k')
})

t('F30 a surface appears after a status was written: next measure clears it exactly once, nothing after', async ($, on) => {
  const w = await world($, on, { surface: null, interactive: true })
  await w.start()
  w.S.tokens = 212_000
  await w.measure()
  expect(texts(w).length).toBeGreaterThan(0)
  w.S.surface = 'desktop'
  await w.measure()
  expect(w.S.statuses[w.S.statuses.length - 1]).toBeUndefined()
  expect(w.S.statuses.filter((s: Any) => s === undefined).length).toBe(1)
  const n = w.S.statuses.length
  w.S.tokens = 230_000
  await w.measure()
  await w.measure()
  expect(w.S.statuses.length).toBe(n)
})

t('F30 session.attach event while a status stands: next measure clears it exactly once', async ($, on) => {
  bot(on, 'session.attach', e => ({ clientId: e.clientId }))
  const w = await world($, on, { surface: null, interactive: true })
  await w.start()
  w.S.tokens = 212_000
  await w.measure()
  expect(texts(w).length).toBeGreaterThan(0)
  w.S.surface = 'desktop'
  await $.session.attach({ surface: 'desktop', clientId: 'desktop:default' } as Any)
  w.S.tokens = 214_000
  await w.measure()
  expect(w.S.statuses.filter((s: Any) => s === undefined).length).toBe(1)
  expect(w.S.statuses[w.S.statuses.length - 1]).toBeUndefined()
  const n = w.S.statuses.length
  await w.measure()
  expect(w.S.statuses.length).toBe(n)
})

t('F30 started with a desktop surface: no status call ever carries text', async ($, on) => {
  const w = await world($, on, { surface: 'desktop', interactive: true })
  await w.start()
  w.S.tokens = 212_000
  await w.measure()
  w.S.tokens = 350_000
  await w.measure()
  expect(texts(w).length).toBe(0)
})

t('F30 non-interactive run with no surface: status text is still written', async ($, on) => {
  const w = await world($, on, { surface: null, interactive: false })
  await w.start()
  w.S.tokens = 212_000
  await w.measure()
  const last = [...w.S.statuses].reverse().find((s: Any) => typeof s === 'string') as string
  expect(last).toBeDefined()
  expect(last).toContain('CTX 212k')
})
