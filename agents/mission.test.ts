import { test, expect, mock } from 'claude-code/testing'

// Real host rule: a plugin-registered tool (mcp__<plugin>__<name>) must answer string | array | undefined.
const checkPluginToolResult = (tool: any, res: any): any => {
  if (typeof tool === 'string' && tool.startsWith('mcp__')) {
    const r = res?.result
    if (r !== undefined && typeof r !== 'string' && !Array.isArray(r)) {
      throw new Error(`tool.call step resolved ${tool} with a result that does not match its output shape ... invalid_union (expected string | array | undefined, received ${r === null ? 'null' : typeof r})`)
    }
  }
  return res
}

// ---------------------------------------------------------------------------
// Shared harness (duplicated verbatim in both test files of this folder so each
// file is self-contained). Everything is typed loosely on purpose: the contract
// tester is code-blind, so event payloads are built from the spec and typings
// and cast where the typings are wider than the contract.
// ---------------------------------------------------------------------------
/* eslint-disable @typescript-eslint/no-explicit-any */

const SURFACES = ['terminal', 'desktop'] as const
type Surface = (typeof SURFACES)[number]
const T0 = 1_800_000_000_000
const SENTINEL = 'SENTINEL-INNER-BAND'
const FULLSCREEN = { columns: 200, rows: 50, isFullscreen: true }
const WINDOWED = { columns: 200, rows: 50, isFullscreen: false }

/** Visible text of a tree: strings, Button labels and Svg alt text (never Svg source). */
function textOf(n: any): string {
  if (n === null || n === undefined || n === false || n === true) return ''
  if (typeof n === 'string') return n
  if (typeof n === 'number') return String(n)
  if (Array.isArray(n)) return n.map(textOf).join(' ')
  const p = n.props ?? {}
  const parts: string[] = []
  if (n.type === 'Svg') {
    if (typeof p.alt === 'string') parts.push(p.alt)
  } else {
    if (n.type === 'Button' && typeof p.label === 'string') parts.push(p.label)
    if (n.type === 'Markdown' && typeof p.text === 'string') parts.push(p.text)
    parts.push(textOf(n.children))
  }
  return parts.join(' ')
}
const squash = (s: string) => s.replace(/\s+/g, ' ').trim()
const flat = (n: any) => squash(textOf(n))

/** Every string a tree holds, split on newlines (rows of a terminal pane). */
function rowsOf(n: any): string[] {
  const out: string[] = []
  const walk = (x: any) => {
    if (x === null || x === undefined || typeof x === 'boolean') return
    if (typeof x === 'string') { out.push(...x.split('\n')); return }
    if (typeof x === 'number') { out.push(String(x)); return }
    if (Array.isArray(x)) { x.forEach(walk); return }
    if (x.type === 'Svg') { if (typeof x.props?.alt === 'string') out.push(...x.props.alt.split('\n')); return }
    if (x.type === 'Button' && typeof x.props?.label === 'string') out.push(x.props.label)
    walk(x.children)
  }
  walk(n)
  return out
}
function walkEls(n: any, fn: (el: any) => void) {
  if (n === null || n === undefined || typeof n !== 'object') return
  if (Array.isArray(n)) { n.forEach((c) => walkEls(c, fn)); return }
  fn(n)
  walkEls(n.children, fn)
}
const allEls = (n: any, pred: (el: any) => boolean) => { const r: any[] = []; walkEls(n, (e) => { if (pred(e)) r.push(e) }); return r }
const svgs = (n: any) => allEls(n, (e) => e.type === 'Svg')
const buttons = (n: any) => allEls(n, (e) => e.type === 'Button')
const srcOf = (el: any) => String(el?.props?.source ?? '')
const has = (hay: string, needle: string) => expect(squash(hay)).toContain(squash(needle))
const hasI = (hay: string, needle: string) => expect(squash(hay).toLowerCase()).toContain(needle.toLowerCase())
const lacks = (hay: string, needle: string) => expect(squash(hay)).not.toContain(squash(needle))
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const near = (v: any, a: number, b: number) => typeof v === 'number' && (Math.abs(v - a) < 0.5 || Math.abs(v - b) < 0.005)

/** Skipped statements are listed in CONTRACT-MAP.md; the kit has no test.skip. */
const skip = (_name: string, _why: string) => {}

function each(name: string, topts: { options?: Record<string, any>; plugins?: any[] }, body: ($: any, on: any, s: Surface) => unknown) {
  for (const s of SURFACES) test(`${name} [${s}]`, { timeoutMs: 30_000, ...topts } as any, ($: any, on: any) => body($, on, s))
}

function makeKit($: any, on: any, cfg: { store?: Record<string, unknown>; listed?: string[]; refuse?: string[]; root?: string } = {}) {
  const clock = mock.clock(on, { now: T0 })
  const op = (name: string, fn: (e: any) => any) => on(name, async (_: any, e: any) => { try { return { value: await fn(e) } } catch (err: any) { return { deny: String(err?.message ?? err) } } })
  const w = {
    surface: 'terminal' as string, surfaces: undefined as string[] | undefined, root: cfg.root ?? '/repo',
    taskCreateRaw: undefined as any,
    toasts: [] as string[], opened: [] as string[], closed: [] as string[], open: new Set<string>(),
    statuses: [] as (string | undefined)[], logs: [] as string[],
    tools: [] as any[], commands: [] as any[], agentTypes: [] as any[],
    spawnSeen: [] as any[], toolSeen: [] as any[], results: [] as any[],
    live: new Map<string, any>(), files: new Map<string, string>(),
    fsFail: false, listFail: false, openFail: false,
    ids: [] as string[], nAgent: 0, taskN: 0, resN: 0,
    refuseRewriteOf: undefined as string | undefined,
    bash: (_e: any) => ({ stdout: '', stderr: '', interrupted: false }) as any,
    steps: [] as any[], net: 0, proc: 0, cost: undefined as number | undefined,
    inner: { type: 'Text', children: [SENTINEL] } as any,
    usageFn: undefined as undefined | ((e: any) => any),
    state: {} as Record<string, any>,
    store: { ...(cfg.store ?? {}) } as Record<string, any>,
    listed: [...(cfg.listed ?? ['help', 'compact'])] as string[],
  }
  op('store.set', (e: any) => { w.store[e.key] = e.value })
  op('store.get', (e: any) => w.store[e.key])
  op('store.delete', (e: any) => { delete w.store[e.key] })
  op('store.keys', () => Object.keys(w.store))
  on('state.set', (_: any, e: any, next: any) => { w.state[`${e.plugin}.${e.key}`] = e.value; return next(e) })
  const findFile = (p: string) => { for (const [k, v] of w.files) if (p === k || p.endsWith(k) || k.endsWith(p)) return [k, v] as const; return undefined }

  op('ui.toast', (e: any) => { w.toasts.push(e.text) })
  op('ui.status', (e: any) => { w.statuses.push(e.text) })
  op('ui.log', (e: any) => { w.logs.push(e.text) })
  op('ui.open', (e: any) => { if (w.openFail) throw new Error('open failed'); w.opened.push(e.id); w.open.add(e.id); return { isPlaced: true } })
  op('ui.close', (e: any) => { w.closed.push(e.id); w.open.delete(e.id) })
  op('ui.panes', () => [...w.open].map((id) => ({ id, title: id })))
  const BUILTINS = ['review', 'compact', 'focus', 'help', 'clear', 'config', 'model', 'status', 'usage', 'diff']
  op('command.list', () => w.listed.map((name) => ({ name, description: '', source: 'test' })))
  op('command.register', (e: any) => {
    const hit = BUILTINS.includes(e.name) ? e.name : (cfg.refuse ?? []).includes(e.name) ? e.name : undefined
    if (hit !== undefined) throw new Error(`"/${e.name}" refused: it is the built-in /${hit}`)
    w.commands.push(e); return { command: e.name }
  })
  op('tool.register', (e: any) => { w.tools.push(e); return { tool: `mcp__agents__${e.name}` } })
  op('tool.list', () => [])
  op('agent.register', (e: any) => { w.agentTypes.push(e); return { agent: e.name } })
  op('agent.list', () => { if (w.listFail) throw new Error('list failed'); return [...w.live.values()] })
  op('session.id', () => 'sess-1')
  op('session.cwd', () => w.root)
  op('session.root', () => w.root)
  op('session.model', () => 'claude-opus-5-5')
  op('session.turns', () => 0)
  op('session.surfaces', () => w.surfaces ?? [w.surface])
  op('session.surface', () => (w.surfaces && w.surfaces.length === 0 ? null : w.surface))
  op('session.usage', (e: any) => w.usageFn ? w.usageFn(e) : ({ startedAt: T0, context: { window: 200000 }, rateLimits: [], cost: { usd: w.cost ?? 0 } }))
  op('fs.read', (e: any) => { if (w.fsFail) throw new Error('fs failed'); const f = findFile(e.path); if (!f) throw new Error('ENOENT ' + e.path); return f[1] })
  op('fs.exists', (e: any) => { if (w.fsFail) throw new Error('fs failed'); return !!findFile(e.path) })
  op('fs.stat', (e: any) => { if (w.fsFail) throw new Error('fs failed'); const f = findFile(e.path); if (!f) throw new Error('ENOENT ' + e.path); return { kind: 'file', size: f[1].length, mtimeMs: T0, isLink: false } })
  op('fs.list', () => [])
  op('http.fetch', () => { w.net++; throw new Error('network disabled in tests') })
  op('process.run', () => { w.proc++; throw new Error('process execution disabled in tests') })

  on('agent.spawn', (_: any, e: any) => {
    w.spawnSeen.push(e)
    if (w.refuseRewriteOf !== undefined && e.prompt !== w.refuseRewriteOf) throw new Error('rewrite refused')
    const agentId = w.ids.shift() ?? `a${++w.nAgent}`
    const model = e.model ?? 'claude-opus-5-5'
    w.live.set(agentId, { id: agentId, description: e.description, type: e.subagentType, status: 'running' })
    return { model, agentId }
  })
  on('tool.call', (_: any, e: any) => {
    w.toolSeen.push(e)
    const ref = `ref${++w.resN}`
    let r: any
    switch (e.tool) {
      case 'Bash': { const b = w.bash(e); r = { ref, result: b, text: b.stdout }; break }
      case 'Edit': case 'Write': case 'NotebookEdit': r = { ref, result: { filePath: e.file_path ?? e.notebook_path }, text: 'ok' }; break
      case 'TodoWrite': r = { ref, result: { oldTodos: [], newTodos: e.todos }, text: 'ok' }; break
      case 'TaskCreate': r = { ref, result: w.taskCreateRaw !== undefined ? w.taskCreateRaw : { task: { id: String(++w.taskN), subject: e.subject } }, text: 'ok' }; break
      case 'TaskUpdate': r = { ref, result: { success: true, taskId: e.taskId, updatedFields: ['status'] }, text: 'ok' }; break
      default: r = { ref, result: String(e.tool).startsWith('mcp__') ? 'ok' : { echo: e.tool }, text: 'ok' }
    }
    w.results.push(r)
    return r
  })
  on('turn.step', async function* (_: any, e: any) {
    return w.steps.shift() ?? { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: 'end_turn', usage: null }
  })
  on('turn.complete', (_: any, e: any) => {
    if (e.agentId && w.live.has(e.agentId)) w.live.get(e.agentId).status = e.reason === 'answer' ? 'completed' : 'failed'
    return { text: e.answer, usage: e.usage }
  })
  on('session.measure', (_: any, e: any) => ({ changed: e.changed }))
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  on('prompt.submit', (_: any, e: any) => ({ text: e.text }))
  on('command.run', (_: any, e: any) => ({ text: `(unhandled ${e.command})` }))
  on('ui.render', (_: any, e: any) => (e.component === 'AbovePrompt' ? w.inner : { type: 'Box', children: [] }))

  let tu = 0
  const mountOn = async (surface: Surface, component: string, props: any, requestId?: string, viewport: any = FULLSCREEN) =>
    $.ui.mount({ plugin: 'agents', surface, component, props, requestId, viewport })
  const k = {
    w, clock,
    start: (surface: any = 'terminal', isInteractive = true) => (w.surface = surface ?? 'terminal', $.session.start({ cwd: w.root, surface, isInteractive })),
    spawn: (over: any = {}) => $.agent.spawn({ tool_use_id: `tu${++tu}`, prompt: 'Do the work', description: 'research sweep', subagentType: 'Explore', provider: { plugin: 'engine', tier: 'core' }, parentModel: 'claude-opus-5-5', background: false, fork: false, ...over }),
    complete: (agentId?: string, reason = 'answer', usage?: any) => $.turn.complete({ answer: 'done', durationMs: 1000, isAborted: reason === 'aborted', turnId: 't-' + (agentId ?? 'main'), agentId, reason, usage }),
    async step(o: { agentId?: string; model?: string; usage?: any; index?: number } = {}) {
      w.steps.push({ turnId: 't-' + (o.agentId ?? 'main'), index: o.index ?? 0, answer: '', toolUses: [], stopReason: 'end_turn', usage: o.usage ?? null })
      const s = $.turn.step({ turnId: 't-' + (o.agentId ?? 'main'), index: o.index ?? 0, model: o.model ?? 'claude-opus-5-5', messageCount: 1, agentId: o.agentId })
      for await (const _c of s) { /* drain */ }
      return s.result
    },
    steps: async (agentId: string, n: number, usage?: any, model?: string) => { for (let i = 0; i < n; i++) await k.step({ agentId, index: i, usage, model }) },
    tool: async (over: any) => checkPluginToolResult(over?.tool, await $.tool.call({ tool_use_id: `tu${++tu}`, ...over })),
    cmd: (command: string, args = '') => $.command.run({ command, args, origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 120 } }),
    async st(key: string) { return w.state[`agents.${key}`] },
    mountPane: (surface: Surface, id: string, viewport: any = FULLSCREEN) =>
      mountOn(surface, 'Pane', { title: id, isFocused: false, bodyColumns: 100, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }, id, viewport),
    async paneText(id: string, surface: Surface) { const ui = await k.mountPane(surface, id); const t = flat(await ui.drawn()); await ui.unmount(); return t },
    mountBand: (surface: Surface, over: any = {}, viewport: any = FULLSCREEN) =>
      mountOn(surface, 'AbovePrompt', { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 200, scroll: { offset: 0, bodyRows: 10 }, view: {}, ...over }, undefined, viewport),
    async bandText(surface: Surface, over: any = {}, viewport: any = FULLSCREEN) { const ui = await k.mountBand(surface, over, viewport); const t = flat(await ui.drawn()); await ui.unmount(); return t },
    /** Tell the plugin the surface is fullscreen (conventions 4.6) the way a real render does. */
    async fullscreen(surface: Surface) { const ui = await k.mountBand(surface, {}, FULLSCREEN); await ui.unmount() },
    tu: () => ++tu,
  }
  return k
}
type Kit = ReturnType<typeof makeKit>
// ------------------------------------------------------------------ end kit

// ===========================================================================
// mission-board.md behaviour contract, section 8 (statements 1-34). Prefix: M07.
// Mission Board is a mod of the `agents` plugin (plugin name `agents`, atom
// {plugin:'agents', key:'mission'}).
// ===========================================================================
const title = (i: number) => `ship feature${i}`
const PRICES = JSON.stringify({ asOf: '2026-10-11', sonnet: { input: 2, output: 10, cacheRead: 0.2, write5m: 2.5 }, haiku: { input: 1, output: 5, cacheRead: 0.1, write5m: 1.25 } })
const SONNET = 'claude-sonnet-5-5'
const usageOf = (model: string, i: number, o: number) => ({ model, input_tokens: i, output_tokens: o, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 })

const mv = async (k: Kit) => (await k.st('mission')) ?? { view: { items: [], counts: {}, total: 0, pct: 0, unplanned: 0 }, steps: {}, allDone: false }
const item = (m: any, id: string) => m.view.items.find((x: any) => x.id === id)
async function makePlan(k: Kit, n: number, from = 1) { for (let i = from; i < from + n; i++) await k.tool({ tool: 'TaskCreate', subject: title(i), description: 'd' }) }
const setStatus = (k: Kit, i: number | string, status: string) => k.tool({ tool: 'TaskUpdate', taskId: String(i), status })
async function run(k: Kit, id: string, i: number, over: any = {}) { k.w.ids.push(id); return k.spawn({ description: title(i), model: SONNET, subagentType: 'general-purpose', ...over }) }
const stepCall = (k: Kit, agentId: string | undefined, input: any) => k.tool({ tool: 'mcp__agents__step', agentId, ...input })
const bandOf = (k: Kit, s: Surface) => k.bandText(s)

/** 50 items: 12 done, 5 running (linked), 2 finished-unreviewed, 31 queued. */
async function scenario50(k: Kit) {
  await makePlan(k, 50)
  for (let i = 1; i <= 12; i++) await setStatus(k, i, 'completed')
  for (let i = 13; i <= 17; i++) { await setStatus(k, i, 'in_progress'); await run(k, `R${i}`, i) }
  for (let i = 18; i <= 19; i++) { await run(k, `F${i}`, i); await k.complete(`F${i}`) }
}

// ---- 1 -------------------------------------------------------------------
each('M07 1 no plan => band absent, view.total 0', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  expect(await bandOf(k, s)).toBe(SENTINEL)
  expect((await mv(k)).view.total ?? 0).toBe(0)
})
each('M07 1 five TaskCreate => "0/5 done"', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 5)
  has(await bandOf(k, s), '0/5 done')
  expect((await mv(k)).view.total).toBe(5)
})

// ---- 2 -------------------------------------------------------------------
test('M07 2 band text equals across surfaces except the pets button label (documented exception to conventions 10.2)', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await scenario50(k)
  const strip = (t: string) => squash(t.replace(/(🐾 )?\d+ working/g, '').replace(/\s+plan\s*$/i, ''))
  expect(strip(await k.bandText('desktop'))).toBe(strip(await k.bandText('terminal')))
})
each('M07 2 plan of 50: 12/50 done, 5 running, 2 review, 31 queued, 24%', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await scenario50(k)
  const t = await bandOf(k, s)
  has(t, '12/50 done'); has(t, '5 running'); has(t, '2 review'); has(t, '31 queued'); has(t, '24%')
  if (s === 'terminal') expect(t).toMatch(/█{3}░{9}/)
})

// ---- 3 -------------------------------------------------------------------
each('M07 3 /review done 1 moves one review item to done', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await scenario50(k)
  await k.cmd('agents-review', 'done 1')
  has(await bandOf(k, s), '13/50')
  const m = await mv(k)
  expect(m.view.counts.done).toBe(13); expect(m.view.counts.review).toBe(1)
})
each('M07 3 nothing is marked reviewed by time alone (30 min)', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await scenario50(k)
  await k.clock.advance(30 * 60_000)
  has(await bandOf(k, s), '12/50')
  expect((await mv(k)).view.counts.done).toBe(12)
})

// ---- 4 / 5 / 6 -----------------------------------------------------------
test('M07 4 finished unreviewed run + completed checklist item => review, not done', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 3)
  await run(k, 'A', 1)
  await setStatus(k, 1, 'completed')
  await k.complete('A')
  expect(item(await mv(k), 'T1')?.state).toBe('review')
})
test('M07 5 running linked run beats srcState done', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 3)
  await setStatus(k, 1, 'completed')
  await run(k, 'A', 1)
  expect(item(await mv(k), 'T1')?.state).toBe('running')
})
test('M07 6 failed run => blocked; completed item => done', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 3)
  await run(k, 'A', 1)
  await k.complete('A', 'error')
  expect(item(await mv(k), 'T1')?.state).toBe('blocked')
  await setStatus(k, 1, 'completed')
  expect(item(await mv(k), 'T1')?.state).toBe('done')
})
test('M07 6 failed run marked reviewed with srcState todo stays blocked', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 3)
  await run(k, 'A', 1)
  await k.complete('A', 'error')
  await k.cmd('agents-review', 'done 1')
  expect(item(await mv(k), 'T1')?.state).toBe('blocked')
})

// ---- 7 -------------------------------------------------------------------
each('M07 7 stripePct is running progress / total; band number unchanged', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 10)
  await setStatus(k, 1, 'in_progress')
  await run(k, 'A', 1)
  const before = await mv(k)
  const bandBefore = await bandOf(k, s)
  await stepCall(k, 'A', { done: 5, total: 10 })
  const after = await mv(k)
  // sum of running fractional progress (0.5) / total (10) = 5 % (percent scale) or 0.05 (fraction scale)
  expect(near(after.view.stripePct, 5, 0.05)).toBe(true)
  expect(after.view.pct).toBe(before.view.pct)
  has(await bandOf(k, s), '0%'); has(bandBefore, '0%')
})

// ---- 8 -------------------------------------------------------------------
const SPEC_PATH = '/repo/docs/specs/x.md'
const SPEC_TEXT = [
  '# Spec', '',
  '- [x] Checklist  Alpha one!', '- [x] the checklist beta two', '- [x] checklist gamma three',
  '- [x] spec only item d4', '- [x] spec only item e5', '- [x] spec only item f6', '- [x] spec only item g7',
  '- [ ] spec only item h8', '- [ ] spec only item i9', '- [ ] spec only item j10', '- [ ] spec only item k11', '- [ ] spec only item l12',
].join('\n')
each('M07 8 checklist + spec: total = checklist + 9; matched items keep checklist title/state', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  k.w.files.set(SPEC_PATH, SPEC_TEXT)
  await k.tool({ tool: 'TodoWrite', todos: [
    { content: 'checklist alpha one', status: 'pending', activeForm: 'Alpha' },
    { content: 'checklist beta two', status: 'pending', activeForm: 'Beta' },
    { content: 'checklist gamma three', status: 'pending', activeForm: 'Gamma' },
    { content: 'write release notes', status: 'in_progress', activeForm: 'Notes' },
    { content: 'cut the tag', status: 'pending', activeForm: 'Tag' },
  ] })
  await k.tool({ tool: 'Edit', file_path: SPEC_PATH })
  const m = await mv(k)
  expect(m.view.total).toBe(14)
  const alpha = m.view.items.find((x: any) => x.title === 'checklist alpha one')
  expect(alpha).toBeDefined(); expect(alpha.srcState).toBe('todo'); expect(alpha.state).toBe('queued')
  expect(m.view.items.some((x: any) => x.title.includes('Alpha'))).toBe(false)
  const h8 = m.view.items.find((x: any) => x.title === 'spec only item h8')
  expect(h8).toBeDefined(); expect(h8.state).toBe('queued')
  expect(m.view.items.indexOf(h8)).toBeGreaterThan(4) // appended after the 5 checklist items
})

// ---- 9 -------------------------------------------------------------------
async function mergeCase(k: Kit, todo: string, specLine: string) {
  k.w.files.set(SPEC_PATH, `# s\n- [ ] ${specLine}\n`)
  await k.tool({ tool: 'TodoWrite', todos: [{ content: todo, status: 'pending', activeForm: 'x' }] })
  await k.tool({ tool: 'Edit', file_path: SPEC_PATH })
  return (await mv(k)).view.total
}
test('M07 9 equal after norm merge', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  expect(await mergeCase(k, 'Fix login bug', 'fix  the login bug!')).toBe(1)
})
test('M07 9 Jaccard < 0.8 does not merge', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  expect(await mergeCase(k, 'Fix login', 'Fix logout flow')).toBe(2)
})

// ---- 10 ------------------------------------------------------------------
test('M07 10 deleted checklist item vanishes and the spec line is not resurrected', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  k.w.files.set(SPEC_PATH, '# s\n- [ ] Ship docs page\n- [ ] other spec thing\n')
  await k.tool({ tool: 'TaskCreate', subject: 'Ship docs page', description: 'd' })
  await k.tool({ tool: 'Edit', file_path: SPEC_PATH })
  expect((await mv(k)).view.total).toBe(2)
  await setStatus(k, 1, 'deleted')
  const m = await mv(k)
  expect(m.view.items.some((x: any) => /ship docs page/i.test(x.title))).toBe(false)
  expect(m.view.total).toBe(1)
})

// ---- 11 ------------------------------------------------------------------
const planKey = (k: Kit) => Object.keys(k.w.store).find((x) => x.startsWith('mission:plan:'))!
const PLAN_PATH = '/repo/docs/plans/x.md'
const PLAN_TEXT = '# Plan\n- [ ] first plan step\n- [x] second plan step\n- [ ] third plan step\n- [ ] fourth plan step\n'
test('M07 11 /mission plan <path>: 4 items, basename only, store holds {v:1,path}', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  k.w.files.set(PLAN_PATH, PLAN_TEXT)
  await k.cmd('mission', 'plan docs/plans/x.md')
  const m = await mv(k)
  expect(m.view.total).toBe(4)
  expect(m.view.items[0].src.kind).toBe('plan'); expect(m.view.items[0].src.ref).toBe('x.md')
  const stored = k.w.store[planKey(k)]
  expect(stored).toMatchObject({ v: 1 })
  expect(typeof stored.path).toBe('string')
  expect(JSON.stringify(stored)).not.toContain('plan step')
  await k.cmd('mission', 'plan clear')
  expect((await mv(k)).view.total).toBe(0)
})
test('M07 11 plan clear drops only the plan\'s unmatched items', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  k.w.files.set(PLAN_PATH, PLAN_TEXT)
  await makePlan(k, 1)
  await k.cmd('mission', 'plan docs/plans/x.md')
  expect((await mv(k)).view.total).toBe(5)
  await k.cmd('mission', 'plan clear')
  expect((await mv(k)).view.total).toBe(1)
})

// ---- 12 ------------------------------------------------------------------
const linked = (m: any, id: string) => (item(m, id)?.runIds ?? []).length
test('M07 12 rule 1: explicit [task:T3] links despite a different description', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 3)
  await k.spawn({ description: 'totally different words', model: SONNET, prompt: 'Do it [task:T3]' })
  const m = await mv(k)
  expect(linked(m, 'T3')).toBe(1); expect(linked(m, 'T1')).toBe(0); expect(linked(m, 'T2')).toBe(0)
})
for (const marker of ['(task T3)', 'Task #3']) {
  test(`M07 12 rule 1 marker ${marker}`, async ($: any, on: any) => {
    const k = makeKit($, on); await k.start('terminal')
    await makePlan(k, 3)
    await k.spawn({ description: 'totally different words', model: SONNET, prompt: `Do it ${marker}` })
    expect(linked(await mv(k), 'T3')).toBe(1)
  })
}
test('M07 12 rule 2: description equals title after norm', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await k.tool({ tool: 'TaskCreate', subject: 'Wire pricing table', description: 'd' })
  await k.tool({ tool: 'TaskCreate', subject: 'Unrelated other thing', description: 'd' })
  await k.spawn({ description: 'wire  PRICING table!', model: SONNET })
  expect(linked(await mv(k), 'T1')).toBe(1)
})
test('M07 12 rule 3: Jaccard 0.7 with a unique best links', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await k.tool({ tool: 'TaskCreate', subject: 'alpha bravo charlie delta echo foxtrot golf', description: 'd' })
  await k.tool({ tool: 'TaskCreate', subject: 'zulu yankee xray whiskey', description: 'd' })
  await k.spawn({ description: 'alpha bravo charlie delta echo foxtrot golf hotel india juliet', model: SONNET })
  const m = await mv(k)
  expect(linked(m, 'T1')).toBe(1); expect(linked(m, 'T2')).toBe(0)
})
test('M07 12 rule 3: two items tied at 0.7 stay unlinked', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await k.tool({ tool: 'TaskCreate', subject: 'a1 a2 a3 a4 a5 a6 a7', description: 'd' })
  await k.tool({ tool: 'TaskCreate', subject: 'a4 a5 a6 a7 a8 a9 a10', description: 'd' })
  await k.spawn({ description: 'a1 a2 a3 a4 a5 a6 a7 a8 a9 a10', model: SONNET })
  const m = await mv(k)
  expect(linked(m, 'T1')).toBe(0); expect(linked(m, 'T2')).toBe(0)
  expect(m.view.unplanned).toBe(1)
})

// ---- 13 ------------------------------------------------------------------
each('M07 13 unlinked run: +1 unplanned, total and pct unchanged', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 4)
  await setStatus(k, 1, 'completed')
  const before = await mv(k)
  await k.spawn({ description: 'qqq zzz unrelated', model: SONNET })
  const after = await mv(k)
  expect(after.view.total).toBe(before.view.total); expect(after.view.pct).toBe(before.view.pct)
  const t = await k.paneText('mission', s)
  has(t, '+1 unplanned'); has(t, 'UNPLANNED')
})

// ---- 14 ------------------------------------------------------------------
test('M07 14 /mission link, unlink, bad number', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 6)
  await k.spawn({ description: 'zzz first stray', model: SONNET })
  await k.spawn({ description: 'qqq second stray', model: SONNET })
  const runs = (await k.st('runs')) ?? []
  await k.cmd('mission', 'link 5 2')
  expect(runs.length).toBe(2)
  expect(item(await mv(k), 'T5')?.runIds ?? []).toContain(runs[1]?.id)
  await k.cmd('mission', 'unlink 2')
  expect(linked(await mv(k), 'T5')).toBe(0)
  const before = JSON.stringify((await mv(k)).view.items.map((x: any) => x.runIds))
  const r = await k.cmd('mission', 'link 99 1')
  has(String(r.text), 'No item 99')
  expect(JSON.stringify((await mv(k)).view.items.map((x: any) => x.runIds))).toBe(before)
})

// ---- 14b: unlink outcomes (mission-board.md /mission unlink) -----------------
test('M07 14 unlink of an existing but unlinked run: "Run 2 is not linked.", nothing changes', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 6)
  await k.spawn({ description: 'zzz first stray', model: SONNET })
  await k.spawn({ description: 'qqq second stray', model: SONNET })
  expect(((await k.st('runs')) ?? []).length).toBe(2)
  const before = JSON.stringify((await mv(k)).view.items.map((x: any) => [x.id, x.state, x.runIds]))
  const r = await k.cmd('mission', 'unlink 2')
  has(String(r.text), 'Run 2 is not linked.')
  lacks(String(r.text), 'Unlinked run')
  expect(JSON.stringify((await mv(k)).view.items.map((x: any) => [x.id, x.state, x.runIds]))).toBe(before)
})
test('M07 14 unlink after a link: "Unlinked run 2." and the item drops back to queued', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 6)
  await k.spawn({ description: 'zzz first stray', model: SONNET })
  await k.spawn({ description: 'qqq second stray', model: SONNET })
  await k.cmd('mission', 'link 5 2')
  expect(linked(await mv(k), 'T5')).toBe(1)
  expect(item(await mv(k), 'T5')?.state).toBe('running')
  const r = await k.cmd('mission', 'unlink 2')
  has(String(r.text), 'Unlinked run 2.')
  expect(linked(await mv(k), 'T5')).toBe(0)
  expect(item(await mv(k), 'T5')?.state).toBe('queued')
  const again = await k.cmd('mission', 'unlink 2')
  has(String(again.text), 'Run 2 is not linked.')
})
test('M07 14 unlink of a run number that does not exist: "No run 9", nothing changes', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 6)
  await k.spawn({ description: 'zzz first stray', model: SONNET })
  const before = JSON.stringify((await mv(k)).view.items.map((x: any) => [x.id, x.state, x.runIds]))
  const r = await k.cmd('mission', 'unlink 9')
  has(String(r.text), 'No run 9')
  expect(JSON.stringify((await mv(k)).view.items.map((x: any) => [x.id, x.state, x.runIds]))).toBe(before)
})

// ---- 15 / 16 -------------------------------------------------------------
test('M07 15 step tool registration: name, not eagerly loaded, description, schema', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  const t = k.w.tools.find((x) => x.name === 'step' || x.name === 'mcp__agents__step')
  expect(t).toBeDefined()
  expect(t.isDeferred).not.toBe(false)
  expect(String(t.description).length).toBeLessThanOrEqual(200)
  expect(Object.keys(t.inputSchema?.properties ?? {}).length).toBeLessThanOrEqual(3)
})
each('M07 15 step call returns ok; row shows 70% and step 7/10, no est.', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3)
  await run(k, 'a1', 1)
  const res = await stepCall(k, 'a1', { done: 7, total: 10, note: 'wiring table' })
  expect(res).toMatchObject({ result: 'ok' })
  const t = await k.paneText('mission', s)
  has(t, '70%'); has(t, 'step 7/10')
  // parity backlog: the RUN totals line carries its own "est." label, so "no est." is read from the agent's row only
  expect(rowBlock(await paneTree($, s), 'ship feature1')).not.toMatch(/\best\./)
})
each('M07 16 step call without agentId is ignored', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3)
  const before = JSON.stringify((await mv(k)).steps)
  const res: any = await stepCall(k, undefined, { done: 3, total: 4 })
  expect(String(res.result)).toContain('ignored')
  expect(JSON.stringify((await mv(k)).steps)).toBe(before)
})
each('M07 16 done>total clamps to 100% but state stays running', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3)
  await run(k, 'a1', 1)
  await stepCall(k, 'a1', { done: 12, total: 10 })
  has(await k.paneText('mission', s), '100%')
  expect(item(await mv(k), 'T1')?.state).toBe('running')
})

// ---- 17 / 18 -------------------------------------------------------------
const TYPICAL = { 'mission_typicalTurns': JSON.stringify({ Explore: 20, 'general-purpose': 20, other: 20 }) }
each('M07 17 estimate: 4/20 turns => ~20% est.; capped ~90%; finished => review, 100, no est.', { options: TYPICAL }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3)
  await run(k, 'a1', 1, { subagentType: 'Explore' })
  await k.steps('a1', 4)
  let t = await k.paneText('mission', s)
  has(t, '~20%'); has(t, 'est.')
  await k.steps('a1', 36)
  t = await k.paneText('mission', s)
  has(t, '~90%'); has(t, 'est.')
  await k.complete('a1')
  const it = item(await mv(k), 'T1') ?? {}
  expect(it.state).toBe('review'); expect(near(it.pct, 100, 1)).toBe(true); expect(it.isEst).toBeFalsy()
  expect(rowBlock(await paneTree($, s), 'ship feature1')).not.toMatch(/\best\./) // row only; the RUN totals line says "est."
})
each('M07 18 estimate learning: median of last 3 finished runs (10,12,14) => typical 12', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3)
  for (const [id, n] of [['f1', 10], ['f2', 12], ['f3', 14]] as const) {
    k.w.ids.push(id)
    await k.spawn({ description: `stray ${id} zzz`, model: SONNET, subagentType: 'general-purpose' })
    await k.steps(id, n); await k.complete(id)
  }
  await run(k, 'n1', 1, { subagentType: 'general-purpose' })
  await k.steps('n1', 6)
  has(await k.paneText('mission', s), '~50%') // 6 / 12; with the table default of 20 it would be ~30%
})

// ---- 19 / 20 / 21 --------------------------------------------------------
const lastBeneath = (k: Kit) => k.w.spawnSeen[k.w.spawnSeen.length - 1]
test('M07 19 spawn line: appended once, <= 160 chars, idempotent, [task:] only when mapped', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 3)
  await k.spawn({ description: 'zzz unmapped stray', prompt: 'Do X', model: SONNET, subagentType: 'general-purpose' })
  const p = lastBeneath(k).prompt as string
  expect(p.startsWith('Do X')).toBe(true)
  const lines = p.split('\n'); expect(lines[lines.length - 1]).toContain('mcp__agents__step')
  expect(p.slice('Do X'.length).trim().length).toBeLessThanOrEqual(160)
  expect(p.split('mcp__agents__step').length - 1).toBe(1)
  expect(p).toContain('ToolSearch'); expect(p).toContain('select:mcp__agents__step')
  expect(p).not.toContain('[task:')
  const again = k.w.spawnSeen.length
  await k.spawn({ description: 'zzz unmapped stray two', prompt: p, model: SONNET, subagentType: 'general-purpose' })
  expect(k.w.spawnSeen.length).toBe(again + 1)
  expect(lastBeneath(k).prompt).toBe(p)
  await k.spawn({ description: title(3), prompt: 'Do Y', model: SONNET, subagentType: 'general-purpose' })
  expect(lastBeneath(k).prompt).toContain('[task:T3]')
  expect((lastBeneath(k).prompt as string).split('mcp__agents__step').length - 1).toBe(1)
})
test('M07 19 spawn line with a [task:T12] suffix is still <= 160 chars and names ToolSearch + select:mcp__agents__step once', { timeoutMs: 30_000 } as any, async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 12)
  await k.spawn({ description: title(12), prompt: 'Do W', model: SONNET, subagentType: 'general-purpose' })
  const p = lastBeneath(k).prompt as string
  expect(p.startsWith('Do W')).toBe(true)
  expect(p).toContain('[task:T12]')
  const added = p.slice('Do W'.length).trim()
  expect(added.length).toBeLessThanOrEqual(160)
  expect(p.split('mcp__agents__step').length - 1).toBe(1)
  expect(added).toContain('ToolSearch'); expect(added).toContain('select:mcp__agents__step')
  await k.spawn({ description: title(12) + ' again', prompt: p, model: SONNET, subagentType: 'general-purpose' })
  expect(lastBeneath(k).prompt).toBe(p)
})
test('M07 20 no line for fork, teammate, workflow, stepLine=false', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  for (const over of [{ fork: true, subagentType: 'fork' }, { isTeammate: true, subagentType: 'teammate' }, { workflow: { runId: 'wf_1', agentIndex: 1 } }]) {
    await k.spawn({ description: 'skip ' + JSON.stringify(over).slice(0, 10), prompt: 'Do Z', model: SONNET, ...over })
    expect(lastBeneath(k).prompt).toBe('Do Z')
  }
})
test('M07 20 mission.stepLine=false => prompt untouched', { options: { 'mission_stepLine': false } } as any, async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await k.spawn({ description: 'plain', prompt: 'Do Z', model: SONNET })
  expect(lastBeneath(k).prompt).toBe('Do Z')
})
test('M07 20 Explore scouts get the line (<= 160 chars, once)', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await k.spawn({ description: 'scout job', prompt: 'Map it', model: 'claude-haiku-4-5', subagentType: 'Explore' })
  const p = lastBeneath(k).prompt as string
  expect(p.split('mcp__agents__step').length - 1).toBe(1)
  expect(p.slice('Map it'.length).trim().length).toBeLessThanOrEqual(160)
})
each('M07 20 mission.enabled=false: no tool, no rewrite, no command, no band', { options: { 'mission_enabled': false } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  expect(k.w.tools.some((t) => /step/.test(String(t.name)))).toBe(false)
  expect(k.w.commands.some((c) => /mission/.test(String(c.name)))).toBe(false)
  await makePlan(k, 5)
  await k.spawn({ description: 'plain', prompt: 'Do Z', model: SONNET })
  expect(lastBeneath(k).prompt).toBe('Do Z')
  const bt = await bandOf(k, s)
  expect(bt).not.toContain('Plan'); expect(bt).not.toMatch(/\d+%/); expect(bt).not.toMatch(/\d+\/\d+ done/)
})
test('M07 21 guard-denied spawn: no rewrite reached, no run recorded', { options: { 'delegation_mode': 'deny' } } as any, async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 3)
  const r: any = await k.spawn({ description: title(1), prompt: 'Do X' })
  expect(typeof r.deny).toBe('string')
  expect(k.w.spawnSeen).toHaveLength(0)
  expect((await k.st('runs')) ?? []).toHaveLength(0)
  expect(linked(await mv(k), 'T1')).toBe(0)
})
test('M07 21 refused rewrite: spawn still starts with the original prompt', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  k.w.refuseRewriteOf = 'Do X'
  const r: any = await k.spawn({ description: 'plain', prompt: 'Do X', model: SONNET })
  expect(r.agentId).toBeDefined(); expect(r.deny).toBeUndefined()
  expect(lastBeneath(k).prompt).toBe('Do X')
})

// ---- 22 ------------------------------------------------------------------
test('M07 22 stepVia=bash: echo MISSION_STEP from a subagent stores a report; main loop stores nothing', { options: { 'mission_stepVia': 'bash' } } as any, async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 2)
  await run(k, 'a1', 1)
  const n = k.w.results.length
  const res = await k.tool({ tool: 'Bash', agentId: 'a1', command: 'echo MISSION_STEP 3/5 reading' })
  expect(res).toEqual(k.w.results[n])
  expect((await mv(k)).steps.a1).toMatchObject({ done: 3, total: 5, via: 'bash' })
})
test('M07 22 stepVia=bash: the same command from the main loop stores nothing', { options: { 'mission_stepVia': 'bash' } } as any, async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 2)
  await k.tool({ tool: 'Bash', command: 'echo MISSION_STEP 3/5 reading' })
  expect(Object.keys((await mv(k)).steps)).toHaveLength(0)
})

// ---- 23 ------------------------------------------------------------------
const SAVVY = {
  name: 'savvy-progress',
  register(on: any) {
    on('session.start', async ($: any, e: any, next: any) => {
      try { await $.state.set({ plugin: 'savvy-progress', key: 'agents' }, { a1: { done: 9, total: 10 } }) } catch { /* undeclared slice is fine */ }
      return next(e)
    })
  },
}
for (const withSavvy of [false, true]) {
  each(`M07 23 precedence: own report 50%, else estimate; savvy atom/tool never read (savvy plugin ${withSavvy ? 'present' : 'absent'})`, { plugins: withSavvy ? [SAVVY] : [] }, async ($, on, s) => {
    const k = makeKit($, on); await k.start(s)
    await makePlan(k, 3)
    await run(k, 'a1', 1); await run(k, 'a2', 2)
    await stepCall(k, 'a1', { done: 2, total: 4 })
    let t = await k.paneText('mission', s)
    has(t, '50%'); has(t, '~'); has(t, 'est.')
    const n = k.w.results.length
    const res = await k.tool({ tool: 'mcp__savvy-progress__step', agentId: 'a1', done: 9, total: 10 })
    expect(res).toEqual(k.w.results[n])
    t = await k.paneText('mission', s)
    has(t, '50%'); expect(t).not.toContain('90%')
    const steps = (await mv(k)).steps
    expect(steps.a1).toMatchObject({ done: 2, total: 4 })
    expect(JSON.stringify(steps)).not.toContain('savvy')
  })
}

// ---- 24 ------------------------------------------------------------------
const AWARE = {
  name: 'awareness',
  register(on: any) {
    on('session.start', async ($: any, e: any, next: any) => {
      try { await $.state.set({ plugin: 'awareness', key: 'now' }, { done: 3, total: 5 }) } catch { /* ignore */ }
      return next(e)
    })
  },
}
const FIVE = [1, 2, 3, 4, 5].map((i) => ({ content: `todo ${i} thing`, status: i <= 3 ? 'completed' : 'pending', activeForm: `Doing ${i}` }))
for (const present of [true, false]) {
  each(`M07 24 checklist counts 3/5 (awareness.now ${present ? 'present' : 'absent'})`, { plugins: present ? [AWARE] : [] }, async ($, on, s) => {
    const k = makeKit($, on); await k.start(s)
    await k.tool({ tool: 'TodoWrite', todos: FIVE })
    has(await bandOf(k, s), '3/5')
    const v = (await mv(k)).view
    expect(v.total).toBe(5); expect(v.counts.done).toBe(3)
  })
}

// ---- 25 ------------------------------------------------------------------
const planKeys = (tree: any) => buttons(tree).filter((b) => /^T\d+$/.test(String(b.props.key)))
async function mixedPlan(k: Kit) {
  await makePlan(k, 50)
  await setStatus(k, 1, 'completed')
  await setStatus(k, 2, 'in_progress'); await run(k, 'a2', 2); await stepCall(k, 'a2', { done: 7, total: 10, note: 'wiring table' })
  await run(k, 'a3', 3); await k.complete('a3')
  await run(k, 'a4', 4); await k.complete('a4', 'error')
}
each('M07 25 tile grid: 50 keyed Buttons with state marks; chip filter; detail card', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await mixedPlan(k)
  const ui = await k.mountPane(s, 'mission')
  let tree = await ui.drawn()
  if (s === 'terminal') { // tiles and chip Buttons are desktop-only: text equivalents
    const tt = flat(tree)
    has(tt, 'EVERYTHING LEFT (49)'); has(tt, 'RUNNING NOW (1)'); has(tt, 'step 7/10')
    const GL = '✅▶📥⛔▫'
    const rows = rowsOf(tree).map((r) => Array.from(r.replace(/[\s\uFE0F]/g, ''))).filter((g) => g.length > 0 && g.every((c) => GL.includes(c)))
    expect(rows.map((g) => g.length)).toEqual([25, 25])
    const all = rows.flat().join('')
    for (const c of ['✅', '▶', '📥', '⛔']) expect(all).toContain(c)
    const r = await k.cmd('mission', '2')
    has(String(r.text), '#2 · running'); has(String(r.text), title(2)); has(String(r.text), 'step 7/10')
    return
  }
  expect(planKeys(tree)).toHaveLength(50)
  const mark = (id: string) => textOf(planKeys(tree).find((b) => b.props.key === id))
  expect(mark('T1')).toContain('✓'); expect(mark('T2')).toContain('▶'); expect(mark('T3')).toContain('?'); expect(mark('T4')).toContain('✕')
  const chip = buttons(tree).find((b) => !/^T\d+$/.test(String(b.props.key)) && /\bREVIEW\b/.test(String(b.props.label)))
  expect(chip).toBeDefined()
  await ui.press({ key: chip.props.key })
  tree = await ui.drawn()
  expect(planKeys(tree)).toHaveLength(1); expect(planKeys(tree)[0].props.key).toBe('T3')
  await ui.press({ key: chip.props.key })
  tree = await ui.drawn()
  expect(planKeys(tree)).toHaveLength(50)
  expect(planKeys(tree).some((b) => b.props.key === 'T2')).toBe(true)
  await ui.press({ key: 'T2' })
  const t = flat(await ui.drawn())
  has(t, title(2)); hasI(t, 'running'); has(t, 'checklist #2'); has(t, 'step 7/10')
})
each('M07 25 maxTiles=10 on 50 items => 10 tiles plus "+40 more" Button', { options: { 'mission_maxTiles': 10 } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 50)
  const ui = await k.mountPane(s, 'mission')
  const tree = await ui.drawn()
  if (s === 'terminal') { has(flat(tree), 'EVERYTHING LEFT (50)'); return } // tiles are desktop-only
  expect(planKeys(tree)).toHaveLength(10)
  expect(buttons(tree).some((b) => String(b.props.label).includes('+40 more'))).toBe(true)
})

// ---- 26 ------------------------------------------------------------------
test('M07 26 terminal pane sample formats [terminal]', { options: TYPICAL, timeoutMs: 60_000 } as any, async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 50)
  for (let i = 1; i <= 12; i++) await setStatus(k, i, 'completed')
  for (let i = 13; i <= 17; i++) { await setStatus(k, i, 'in_progress'); await run(k, `R${i}`, i, i === 14 ? { subagentType: 'Explore' } : {}) }
  await stepCall(k, 'R13', { done: 7, total: 10, note: 'wiring table' })
  await stepCall(k, 'R17', { done: 7, total: 10, note: 'wiring table' })
  await k.steps('R14', 4)
  for (let i = 18; i <= 19; i++) { await run(k, `F${i}`, i); await k.complete(`F${i}`) }
  const ui = await k.mountPane('terminal', 'mission')
  const tree = await ui.drawn()
  const t = flat(tree)
  has(t, 'RUNNING NOW (5)'); has(t, 'EVERYTHING LEFT (38)'); has(t, '~20% est.'); has(t, 'step 7/10 · wiring table')
  has(t, '12 done · 5 running · 2 review · 31 queued · 0 blocked')
  const GL = '✅▶📥⛔▫'
  const glyphRows = rowsOf(tree).map((r) => Array.from(r.replace(/[\s\uFE0F]/g, ''))).filter((g) => g.length > 0 && g.every((c) => GL.includes(c)))
  expect(glyphRows.map((g) => g.length)).toEqual([25, 25])
  const r = await k.cmd('mission', '17')
  has(String(r.text), '#17 · running · ship feature17'); has(String(r.text), 'checklist #17')
})

// ---- 27 ------------------------------------------------------------------
each('M07 27 band hidden on survey, agent view, small maxRows; inner preserved', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 5)
  for (const over of [{ hasSurvey: true }, { view: { agentId: 'a1' } }, { maxRows: 3 }]) {
    expect(await k.bandText(s, over)).toBe(SENTINEL)
  }
  has(await bandOf(k, s), SENTINEL); has(await bandOf(k, s), '0/5 done')
})
test('M07 27 status fallback when there is no band', async ($: any, on: any) => {
  const k = makeKit($, on); k.w.surfaces = []; await k.start(null, false)
  await scenario50(k)
  expect(k.w.statuses.some((x) => String(x).includes('plan 12/50 · 5 running'))).toBe(true)
})

// ---- 27b: F30 status-line rule (no-band status fallback decided per write) ----
const sTexts = (k: Kit) => k.w.statuses.filter((x) => typeof x === 'string') as string[]
const sClears = (k: Kit) => k.w.statuses.filter((x) => x === undefined).length
const PLAN_TXT = 'plan 12/50 · 5 running'
test('M07 27b F30 no surface, interactive: status text is written', async ($: any, on: any) => {
  const k = makeKit($, on); k.w.surfaces = []
  await k.start(null, true)
  await scenario50(k)
  expect(sTexts(k).some((x) => x.includes(PLAN_TXT))).toBe(true)
})
test('M07 27b F30 surface appears after text was written: cleared exactly once, nothing written after', async ($: any, on: any) => {
  const k = makeKit($, on); k.w.surfaces = []
  await k.start(null, true)
  await scenario50(k)
  expect(sTexts(k).length).toBeGreaterThan(0)
  k.w.surfaces = ['desktop']; k.w.surface = 'desktop'
  await run(k, 'R20', 20)
  expect(k.w.statuses[k.w.statuses.length - 1]).toBeUndefined()
  expect(sClears(k)).toBe(1)
  const n = k.w.statuses.length
  await run(k, 'R21', 21); await setStatus(k, 22, 'completed')
  await k.complete('R21'); await k.complete('R20')
  expect(k.w.statuses.length).toBe(n)
  expect(sClears(k)).toBe(1)
})
test('M07 27b F30 session.attach event while text stands: cleared exactly once, nothing written after', async ($: any, on: any) => {
  on('session.attach', (_: any, e: any) => ({ clientId: e.clientId }))
  const k = makeKit($, on); k.w.surfaces = []
  await k.start(null, true)
  await scenario50(k)
  expect(sTexts(k).length).toBeGreaterThan(0)
  k.w.surfaces = ['desktop']; k.w.surface = 'desktop'
  await $.session.attach({ surface: 'desktop', clientId: 'desktop:default' } as any)
  await run(k, 'R20', 20)
  expect(sClears(k)).toBe(1)
  expect(k.w.statuses[k.w.statuses.length - 1]).toBeUndefined()
  const n = k.w.statuses.length
  await run(k, 'R21', 21); await k.complete('R21'); await setStatus(k, 22, 'completed')
  expect(k.w.statuses.length).toBe(n)
})
test('M07 27b F30 started with a desktop surface: no status call ever carries text', async ($: any, on: any) => {
  const k = makeKit($, on); k.w.surfaces = ['desktop']
  await k.start('desktop', true)
  await scenario50(k)
  await run(k, 'R20', 20); await k.complete('R20')
  expect(sTexts(k).length).toBe(0)
})
test('M07 27b F30 rendering the band with no state change makes no status calls', async ($: any, on: any) => {
  const k = makeKit($, on); k.w.surfaces = []
  await k.start(null, true)
  await scenario50(k)
  const n = k.w.statuses.length
  for (let i = 0; i < 5; i++) await k.bandText('terminal')
  await k.bandText('desktop')
  expect(k.w.statuses.length).toBe(n)
})
test('M07 27b F30 rendering the band with a surface present makes no status calls', async ($: any, on: any) => {
  const k = makeKit($, on); k.w.surfaces = ['desktop']
  await k.start('desktop', true)
  await scenario50(k)
  const n = k.w.statuses.length
  for (let i = 0; i < 5; i++) await k.bandText('desktop')
  expect(k.w.statuses.length).toBe(n)
})
test('M07 27b F30 non-interactive run with no surface: status text is written', async ($: any, on: any) => {
  const k = makeKit($, on); k.w.surfaces = []
  await k.start(null, false)
  await scenario50(k)
  expect(sTexts(k).some((x) => x.includes(PLAN_TXT))).toBe(true)
})

// ---- 28 ------------------------------------------------------------------
each('M07 28 privacy: prompt text never reaches state, store, toasts or UI', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 5)
  await k.spawn({ description: title(3), prompt: 'SECRET123 [task:T3]', model: SONNET })
  const dump: string[] = [...k.w.toasts]
  for (const key of ['runs', 'spend', 'ui', 'checklist', 'guard', 'clock', 'mission']) dump.push(JSON.stringify(await k.st(key) ?? null))
  for (const key of Object.keys(k.w.store)) dump.push(JSON.stringify(k.w.store[key]))
  dump.push(await k.bandText(s), await k.paneText('mission', s), await k.paneText('pets', s), await k.paneText('delegation', s))
  dump.push(...k.w.statuses.map(String), ...k.w.logs)
  expect(dump.join('\n')).not.toContain('SECRET123')
})

// ---- 29 ------------------------------------------------------------------
test('M07 29 failing dependencies leave results unchanged and next is still called', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  k.w.files.set(SPEC_PATH, SPEC_TEXT)
  k.w.fsFail = true; k.w.listFail = true; k.w.openFail = true
  for (const over of [{ tool: 'Edit', file_path: SPEC_PATH }, { tool: 'TaskCreate', subject: 'x thing', description: 'd' }, { tool: 'TodoWrite', todos: FIVE }, { tool: 'Bash', command: 'echo hi' }]) {
    const n = k.w.results.length
    const res = await k.tool(over)
    expect(res).toEqual(k.w.results[n])
  }
  const r: any = await k.spawn({ description: 'plain', prompt: 'Do X', model: SONNET })
  expect(r.agentId).toBeDefined(); expect(r.deny).toBeUndefined()
  expect(k.w.spawnSeen.length).toBeGreaterThanOrEqual(1)
  await k.cmd('mission', 'status') // must not throw
})

// ---- 30 ------------------------------------------------------------------
// The kit's session.usage bottom derives the breakdown from what the plugin registered (name-only cost for
// deferred tools, name+description for commands). It is an estimate, not the engine's /context.
function installUsage(k: Kit) {
  const cmdTokens = (c: any) => Math.ceil(`${c.name} ${c.description ?? ''}`.length / 4) + 4
  const toolTokens = (t: any) => (t.isDeferred === false ? Math.ceil(JSON.stringify([t.name, t.description, t.inputSchema]).length / 4) + 8 : Math.ceil(`mcp__agents__${t.name}`.length / 4) + 4)
  k.w.usageFn = (e: any) => ({
    startedAt: T0, rateLimits: [], cost: { usd: 0 },
    context: { window: 200000, breakdown: e.breakdown ? {
      categories: [], totalTokens: 0, maxTokens: 200000, rawMaxTokens: 200000, percentage: 0, gridRows: [], model: 'x', memoryFiles: [], agents: [], isAutoCompactEnabled: false, apiUsage: null,
      mcpTools: k.w.tools.map((t) => ({ name: `mcp__agents__${t.name}`, serverName: 'agents', tokens: toolTokens(t) })),
      slashCommands: { totalCommands: k.w.commands.length, includedCommands: k.w.commands.length, tokens: k.w.commands.reduce((a, c) => a + cmdTokens(c), 0) },
    } : undefined },
  })
}
const missionShare = (k: Kit, b: any) => {
  const isM = (n: string) => /(^|__)step$/.test(n)
  const tools = b.mcpTools.filter((t: any) => isM(t.name)).reduce((a: number, t: any) => a + t.tokens, 0)
  const cmdNames = k.w.commands.filter((c) => /mission/.test(String(c.name)))
  const cmds = cmdNames.reduce((a, c) => a + Math.ceil(`${c.name} ${c.description ?? ''}`.length / 4) + 4, 0)
  return tools + cmds
}
test('M07 30 context budget: mod adds <= 40 tokens; no skill, agent type, prompt section', async ($: any, on: any) => {
  const k = makeKit($, on); installUsage(k); await k.start('terminal')
  const u = k.w.usageFn!({ breakdown: 'summary' })
  const share = missionShare(k, u.context.breakdown)
  expect(share).toBeGreaterThan(0); expect(share).toBeLessThanOrEqual(40)
  expect(k.w.agentTypes).toHaveLength(0)
  expect(k.w.tools.filter((t) => t.isDeferred === false)).toHaveLength(0)
  const m = k.w.commands.filter((c) => /mission/.test(String(c.name)))
  expect(m).toHaveLength(1); expect(String(m[0].description).length).toBeLessThanOrEqual(60)
})
test('M07 30 mission.enabled=false adds nothing', { options: { 'mission_enabled': false } } as any, async ($: any, on: any) => {
  const k = makeKit($, on); installUsage(k); await k.start('terminal')
  const u = k.w.usageFn!({ breakdown: 'summary' })
  expect(missionShare(k, u.context.breakdown)).toBe(0)
})

// ---- 31 ------------------------------------------------------------------
const allDone = async (k: Kit) => (await mv(k)).allDone
test('M07 31 allDone: true when everything done, false otherwise', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  expect(await allDone(k)).toBeFalsy() // total 0
  await makePlan(k, 5)
  for (let i = 1; i <= 5; i++) await setStatus(k, i, 'completed')
  expect(await allDone(k)).toBe(true)
  await k.spawn({ description: 'zzz unplanned runner', model: SONNET })
  expect(await allDone(k)).toBe(true) // unplanned running agent does not count
  await setStatus(k, 3, 'pending')
  expect(await allDone(k)).toBe(false)
  await setStatus(k, 3, 'completed')
  expect(await allDone(k)).toBe(true)
  await k.tool({ tool: 'TaskCreate', subject: 'brand new item', description: 'd' })
  expect(await allDone(k)).toBe(false)
})
test('M07 31 allDone: linked run running or unreviewed blocks it until reviewed', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 3)
  for (let i = 1; i <= 3; i++) await setStatus(k, i, 'completed')
  await run(k, 'A', 1)
  expect(await allDone(k)).toBe(false) // running
  await k.complete('A')
  expect(await allDone(k)).toBe(false) // unreviewed
  await k.cmd('agents-review', 'done all')
  expect(await allDone(k)).toBe(true)
})
test('M07 31 allDone resets on /mission plan clear and on a new plan', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  k.w.files.set(PLAN_PATH, '# p\n- [x] one done\n- [x] two done\n')
  k.w.files.set('/repo/docs/plans/y.md', '# p\n- [ ] fresh open step\n')
  await k.cmd('mission', 'plan docs/plans/x.md')
  expect(await allDone(k)).toBe(true)
  await k.cmd('mission', 'plan clear')
  expect(await allDone(k)).toBe(false)
  await k.cmd('mission', 'plan docs/plans/x.md')
  expect(await allDone(k)).toBe(true)
  await k.cmd('mission', 'plan docs/plans/y.md')
  expect(await allDone(k)).toBe(false)
})

// ---- 32 ------------------------------------------------------------------
test('M07 32 savvy independence: savvy tool calls are not read, whole flow works without savvy', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 3)
  await run(k, 'a1', 1)
  const n = k.w.results.length
  const res = await k.tool({ tool: 'mcp__savvy-progress__step', agentId: 'a1', done: 1, total: 2 })
  expect(res).toEqual(k.w.results[n]) // reached the bottom untouched
  expect(Object.keys((await mv(k)).steps)).toHaveLength(0)
  await stepCall(k, 'a1', { done: 1, total: 2 })
  expect((await mv(k)).steps.a1).toMatchObject({ done: 1, total: 2 })
})

// ---- 33 ------------------------------------------------------------------
each('M07 33 parity: per-agent context, tokens, cost, step count; "--" when no source', { options: { pricesJson: PRICES } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3)
  await run(k, 'a1', 1); await run(k, 'a2', 2)
  await k.steps('a1', 4, usageOf(SONNET, 1000, 500), SONNET)
  let t: string
  if (s === 'terminal') { t = squash(String((await k.cmd('mission', '1')).text) + ' ' + String((await k.cmd('mission', '2')).text)) } else {
    const ui = await k.mountPane(s, 'mission')
    expect(planKeys(await ui.drawn()).some((b) => b.props.key === 'T1')).toBe(true)
    await ui.press({ key: 'T1' })
    t = flat(await ui.drawn())
  }
  expect(t).toMatch(/ctx|context/i)
  expect(t).toMatch(/\b6[,.]?0{3}\b|\b6k\b|\b6\.0k\b/i) // 4 x (1000 + 500) tokens
  expect(t).toMatch(/~\$0\.0(28|3)/) // 4 x (1000*2 + 500*10)/1e6; parity backlog: money is always an estimate, `~` prefixed
  // (the old "steps 4" count is gone from the figures line: new format is `ctx 41% · 38k tok · ~$0.42`)
  has(t, '--') // a2 has no usage yet
})

// ---- 34 ------------------------------------------------------------------
async function planStart(k: Kit, s: Surface, viewport: any) {
  const ui = await k.mountBand(s, {}, viewport); await ui.unmount()
  await makePlan(k, 5)
  await run(k, 'a1', 1); await run(k, 'a2', 2)
}
each('M07 34 auto-open once per session at plan start (fullscreen)', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await planStart(k, s, FULLSCREEN)
  expect(k.w.opened.filter((i) => i === 'mission')).toHaveLength(1)
  await k.cmd('mission') // toggle closes the pane
  await k.complete('a1'); await k.complete('a2')
  await run(k, 'a3', 3); await run(k, 'a4', 4)
  await makePlan(k, 3, 6)
  expect(k.w.opened.filter((i) => i === 'mission')).toHaveLength(1)
})
each('M07 34 never auto-opens when not fullscreen', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await planStart(k, s, WINDOWED)
  expect(k.w.opened.filter((i) => i === 'mission')).toHaveLength(0)
})

// ---- terminal pane cap (mission-board.md section 1, pane item 4) ----
const GLYPHS = '✅▶📥⛔▫'
const glyphCount = (tree: any) => rowsOf(tree).map((r) => Array.from(r.replace(/[\s\uFE0F]/g, ''))).filter((g) => g.length > 0 && g.every((c) => GLYPHS.includes(c))).reduce((n, g) => n + g.length, 0)
const listRows = (tree: any) => rowsOf(tree).filter((r) => /#\d+\s+\S+\s+ship feature\d+/.test(r))
test('M07 25t terminal grid caps at 120 glyphs of 150 items with a "+30 more" line', { timeoutMs: 60_000 } as any, async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 150)
  const ui = await k.mountPane('terminal', 'mission')
  const tree = await ui.drawn()
  expect(glyphCount(tree)).toBe(120)
  expect(rowsOf(tree).some((r) => r.includes('+30 more'))).toBe(true)
})
test('M07 25t mission.maxTiles=10 on 50 items => 10 glyphs and "+40 more"', { timeoutMs: 60_000, options: { 'mission_maxTiles': 10 } } as any, async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 50)
  const tree = await (await k.mountPane('terminal', 'mission')).drawn()
  expect(glyphCount(tree)).toBe(10)
  expect(rowsOf(tree).some((r) => r.includes('+40 more'))).toBe(true)
})
test('M07 25t 500 items never exceed maxTiles glyphs', { timeoutMs: 120_000 } as any, async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 500)
  const tree = await (await k.mountPane('terminal', 'mission')).drawn()
  expect(glyphCount(tree)).toBeLessThanOrEqual(120)
  expect(glyphCount(tree)).toBeGreaterThan(0)
})
for (const [label, cmdName, listed] of [['/mission list', 'mission', undefined], ['/agents-mission list (twin)', 'agents-mission', ['help', 'compact', 'mission']]] as const) {
  test(`M07 25t ${label} toggles a text list of all items, a second one returns to the grid`, { timeoutMs: 60_000 } as any, async ($: any, on: any) => {
    const k = makeKit($, on, listed ? { listed: [...listed] } : {}); await k.start('terminal')
    await makePlan(k, 150)
    const ui = await k.mountPane('terminal', 'mission')
    expect(glyphCount(await ui.drawn())).toBe(120)
    await k.cmd(cmdName, 'list')
    let tree = await ui.drawn()
    const rows = listRows(tree)
    expect(rows.length).toBe(150)
    expect(rows.some((r) => /#1\s+\S+\s+ship feature1\b/.test(r))).toBe(true)
    expect(rows.some((r) => /#150\s+\S+\s+ship feature150\b/.test(r))).toBe(true)
    await k.cmd(cmdName, 'list')
    tree = await ui.drawn()
    expect(listRows(tree).length).toBe(0)
    expect(glyphCount(tree)).toBe(120)
  })
}

// ---- skipped / manual ------------------------------------------------------
skip('M07 acceptance (1): 10-item checklist with 3 real subagents show step n/m rows', 'manual list')
skip('M07 acceptance (3): probe Q2 - does a Haiku subagent call the deferred tool unaided', 'manual list, real model')
skip('M07 acceptance (4): /context confirms <= 40 tokens in the real engine', 'manual list; M07 30 covers it with a modelled breakdown')
skip('M07 acceptance (5): 120+ tile click lag probe, light/dark, mascot fallback', 'manual list / UNVERIFIED lag probe')
skip('M07 acceptance (6): parity check against running savvy-progress and uninstall on a yes', 'manual list; destructive step needs the owner')

// ---- agents3 round 3: plan scoped to the project root ----------------------
const PA = '/work/projA', PB = '/work/projB'
const PLAN_A = PA + '/docs/plans/p.md', PLAN_B = PB + '/docs/plans/q.md'
const TXT3 = '# P\n- [ ] alpha step\n- [ ] beta step\n- [ ] gamma step\n'
const TXT2 = '# Q\n- [ ] one step\n- [ ] two step\n'
const swap = async (k: Kit, root: string, surface: any = 'terminal') => { k.w.root = root; await k.start(surface) }
const statusOf = async (k: Kit) => String((await k.cmd('mission', 'status')).text)
const planKeys2 = (k: Kit) => Object.keys(k.w.store).filter((x) => x.startsWith('mission:plan:'))

test('M07 35 plan registered in root A is invisible in root B: no band segment, "No plan" in status and pane', async ($: any, on: any) => {
  const k = makeKit($, on, { root: PA }); await k.start('terminal')
  k.w.files.set(PLAN_A, TXT3)
  await k.cmd('mission', 'plan docs/plans/p.md')
  expect((await mv(k)).view.total).toBe(3)
  hasI(await statusOf(k), 'plan 0/3')
  await swap(k, PB)
  expect(await bandOf(k, 'terminal')).toBe(SENTINEL)
  expect((await mv(k)).view.total ?? 0).toBe(0)
  hasI(await statusOf(k), 'No plan')
  hasI(await k.paneText('mission', 'terminal'), 'no plan')
})
test('M07 35 restarting in root A restores its plan; the store key is namespaced and holds no contents', async ($: any, on: any) => {
  const k = makeKit($, on, { root: PA }); await k.start('terminal')
  k.w.files.set(PLAN_A, TXT3)
  await k.cmd('mission', 'plan docs/plans/p.md')
  await swap(k, PB)
  await swap(k, PA)
  expect((await mv(k)).view.total).toBe(3)
  hasI(await statusOf(k), 'plan 0/3')
  has(await bandOf(k, 'terminal'), '0/3 done')
  const keys = planKeys2(k)
  expect(keys).toHaveLength(1)
  expect(k.w.store[keys[0]]).toMatchObject({ v: 1, root: PA })
  expect(JSON.stringify(k.w.store)).not.toContain('alpha step')
  expect(k.w.store['mission:plan']).toBeUndefined()
})
test('M07 35 root B registering its own plan keeps A and B apart; plan clear in A leaves B', async ($: any, on: any) => {
  const k = makeKit($, on, { root: PA }); await k.start('terminal')
  k.w.files.set(PLAN_A, TXT3); k.w.files.set(PLAN_B, TXT2)
  await k.cmd('mission', 'plan docs/plans/p.md')
  await swap(k, PB)
  await k.cmd('mission', 'plan docs/plans/q.md')
  expect((await mv(k)).view.total).toBe(2)
  expect(planKeys2(k)).toHaveLength(2)
  await swap(k, PA)
  expect((await mv(k)).view.total).toBe(3)
  await k.cmd('mission', 'plan clear')
  expect((await mv(k)).view.total).toBe(0)
  expect(planKeys2(k)).toHaveLength(1)
  await swap(k, PB)
  expect((await mv(k)).view.total).toBe(2)
  hasI(await statusOf(k), 'plan 0/2')
})
test('M07 35 a stored plan whose file is gone is dropped silently at start', async ($: any, on: any) => {
  const k = makeKit($, on, { root: PA }); await k.start('terminal')
  k.w.files.set(PLAN_A, TXT3)
  await k.cmd('mission', 'plan docs/plans/p.md')
  k.w.files.delete(PLAN_A)
  await swap(k, PA)
  expect(await bandOf(k, 'terminal')).toBe(SENTINEL)
  expect((await mv(k)).view.total ?? 0).toBe(0)
})
test('M07 35 a stored plan whose file has no checkboxes is dropped silently at start', async ($: any, on: any) => {
  const k = makeKit($, on, { root: PA }); await k.start('terminal')
  k.w.files.set(PLAN_A, TXT3)
  await k.cmd('mission', 'plan docs/plans/p.md')
  k.w.files.set(PLAN_A, '# P\njust prose, no checkboxes\n')
  await swap(k, PA)
  expect(await bandOf(k, 'terminal')).toBe(SENTINEL)
  expect((await mv(k)).view.total ?? 0).toBe(0)
})
test('M07 35 a legacy value under the old single key appears in no session', async ($: any, on: any) => {
  const k = makeKit($, on, { root: PA, store: { 'mission:plan': { v: 1, path: PLAN_A } } })
  k.w.files.set(PLAN_A, TXT3)
  await k.start('terminal')
  expect(await bandOf(k, 'terminal')).toBe(SENTINEL)
  expect((await mv(k)).view.total ?? 0).toBe(0)
  hasI(await statusOf(k), 'No plan')
})

// ---- terminal band wording and Button -------------------------------------
test('M07 36 [terminal] band says "Plan n/m done" and does not end with a standalone "plan" word', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  k.w.files.set(PLAN_PATH, PLAN_TEXT)
  await k.cmd('mission', 'plan docs/plans/x.md')
  const t = await bandOf(k, 'terminal')
  expect(t).toMatch(/Plan\s+1\/4\s+done/i)
  expect(t).not.toMatch(/\bplan\s*$/i)
})
test('M07 36 [desktop] band keeps a pressable plan Button', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('desktop')
  await makePlan(k, 5)
  const ui = await k.mountBand('desktop'); const tree = await ui.drawn(); await ui.unmount()
  expect(buttons(tree).some((b) => /plan/i.test(textOf(b)))).toBe(true)
})

// ---- checklist source independence ----------------------------------------
test('M07 37 no TodoWrite/TaskCreate at all: a registered plan file still produces the Mission view', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  k.w.files.set(PLAN_PATH, PLAN_TEXT)
  await k.cmd('mission', 'plan docs/plans/x.md')
  expect((await mv(k)).view.total).toBe(4)
  has(await bandOf(k, 'terminal'), '1/4 done')
  expect(k.w.toolSeen.some((e: any) => e.tool === 'TodoWrite' || e.tool === 'TaskCreate')).toBe(false)
})
test('M07 37 no TodoWrite/TaskCreate at all: a spec tracker file still produces the Mission view', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  k.w.files.set(SPEC_PATH, SPEC_TEXT)
  await k.tool({ tool: 'Edit', file_path: SPEC_PATH })
  expect((await mv(k)).view.total).toBe(12)
})
test('M07 37 a TaskCreate result in the host string form "Task #n created successfully: subject" creates the item', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  k.w.taskCreateRaw = 'Task #1 created successfully: t1'
  await k.tool({ tool: 'TaskCreate', subject: 't1', description: 'd' })
  const m = await mv(k)
  expect(m.view.total).toBe(1)
  expect(item(m, 'T1')?.title).toBe('t1')
})
for (const [label, raw] of [['error string', 'error: whatever'], ['number', 42]] as const) {
  test(`M07 37 a TaskCreate result that is a ${label} (not a task object nor the host string form) is ignored without throwing`, async ($: any, on: any) => {
    const k = makeKit($, on); await k.start('terminal')
    k.w.taskCreateRaw = raw
    await k.tool({ tool: 'TaskCreate', subject: 'odd task', description: 'd' })
    expect((await mv(k)).view.total ?? 0).toBe(0)
  })
}

// ===========================================================================
// Parity backlog (mission-board.md "Parity backlog (decided 2026-10-12)"), contract cases 35-49.
// Prefix `M07 PB<n>` (the plain M07 35-37 names are taken by the earlier agents3 rounds).
// ===========================================================================
const usageFull = (model: string, i: number, o: number, cr = 0, cw = 0) => ({ model, input_tokens: i, output_tokens: o, cache_read_input_tokens: cr, cache_creation_input_tokens: cw })
/** windowsJson in the same shape family as pricesJson: asOf plus a family -> window map (tolerant keys). */
const WIN = (n: number) => JSON.stringify({ asOf: '2026-10-12', sonnet: n, 'claude-sonnet-5-5': n, 'claude-sonnet': n })
const PRICES_RUN = JSON.stringify({ asOf: '2026-10-12', sonnet: { input: 400, output: 200 / 3, cacheRead: 0, write5m: 0 }, haiku: { input: 1, output: 5, cacheRead: 0.1, write5m: 1.25 } })

/** Mission pane tree at a given body width (desktop px = bodyColumns*8-16; terminal columns = bodyColumns). */
async function paneTree($: any, s: Surface, cols = 100) {
  const ui = await $.ui.mount({ plugin: 'agents', surface: s, component: 'Pane', requestId: 'mission',
    props: { title: 'mission', isFocused: false, bodyColumns: cols, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} },
    viewport: { columns: Math.max(cols, 20), rows: 50, isFullscreen: true } })
  const tree = await ui.drawn(); await ui.unmount(); return tree
}
const sqRows = (tree: any) => rowsOf(tree).map((r) => squash(r)).filter((r) => r.length > 0)
/** The RUNNING NOW row of the run whose title contains `frag`: its title line (has a model chip) plus the figures line under it. */
function rowBlock(tree: any, frag: string): string {
  const rows = sqRows(tree)
  const i = rows.findIndex((r) => r.includes(frag) && /sonnet|haiku|opus|fable|other/i.test(r))
  if (i < 0) return ''
  const nx = rows[i + 1]
  return nx !== undefined && /^(ctx\b|\d+%|~)/.test(nx) ? rows[i] + ' ' + nx : rows[i]
}
const runLineOf = (tree: any) => sqRows(tree).find((r) => /\bRUN\s*·/.test(r)) ?? ''
const acceptedLineOf = (tree: any) => sqRows(tree).find((r) => /\bACCEPTED\b/.test(r)) ?? ''
const timeIn = (line: string) => line.match(/\b(\d{1,2}:\d{2}(?::\d{2})?)\b/)?.[1] ?? ''
const secs = (t: string) => t.split(':').map(Number).reduce((a, n) => a * 60 + n, 0)
async function cardOf($: any, k: Kit, s: Surface, n = 1): Promise<string> {
  if (s === 'terminal') return squash(String((await k.cmd('mission', String(n))).text))
  const ui = await k.mountPane(s, 'mission')
  await ui.press({ key: `T${n}` })
  const t = flat(await ui.drawn()); await ui.unmount(); return t
}
/** turn.step with extra event fields (effort), like Kit.step. */
async function stepX($: any, k: Kit, o: { agentId?: string; usage?: any; model?: string; effort?: any; index?: number }) {
  const id = o.agentId
  k.w.steps.push({ turnId: 't-' + (id ?? 'main'), index: o.index ?? 0, answer: '', toolUses: [], stopReason: 'end_turn', usage: o.usage ?? null })
  const st = $.turn.step({ turnId: 't-' + (id ?? 'main'), index: o.index ?? 0, model: o.model ?? SONNET, messageCount: 1, agentId: id, effort: o.effort })
  for await (const _c of st) { /* drain */ }
  return st.result
}
const fig = async ($: any, s: Surface, frag = 'ship feature1', cols = 100) => rowBlock(await paneTree($, s, cols), frag)

// ---- PB35 (a): tokens summed, cost tilde ------------------------------------
each('M07 PB35 row shows summed tokens (31.5k, not 10.5k) and a ~$ cost', { options: { pricesJson: PRICES } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3); await run(k, 'a1', 1)
  await k.steps('a1', 3, usageFull(SONNET, 1000, 500, 9000, 0), SONNET)
  const b = await fig($, s)
  expect(b).toContain('tok')
  expect(b).toMatch(/(31\.5k|32k)/)
  expect(b).not.toMatch(/\b10\.5k\s*tok|tok\s*10\.5k/)
  expect(b).toContain('~$')
})

// ---- PB36 cost from the shared price table ----------------------------------
each('M07 PB36 cost uses pricesJson (1M input at $2 => ~$2.00); no $ without ~', { options: { pricesJson: PRICES } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3); await run(k, 'a1', 1)
  await k.steps('a1', 1, usageFull(SONNET, 1_000_000, 0), SONNET)
  expect(await fig($, s)).toContain('~$2.00')
  const all = flat(await paneTree($, s)) + ' ' + (await bandOf(k, s))
  expect(all).not.toMatch(/(?<![~<])\$[\d-]/)
})

// ---- PB37 context percent -----------------------------------------------------
each('M07 PB37 window 200000, last-request input 82000 (incl. cache) => ctx 41%, no warning', { options: { pricesJson: PRICES, windowsJson: WIN(200000) } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3); await run(k, 'a1', 1)
  await k.steps('a1', 1, usageFull(SONNET, 2000, 100, 80000, 0), SONNET)
  const b = await fig($, s)
  expect(b).toMatch(/ctx\s*41%/); expect(b).not.toContain('⚠')
})
each('M07 PB37 window 200000, input 170000 => ctx 85% and ⚠', { options: { pricesJson: PRICES, windowsJson: WIN(200000) } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3); await run(k, 'a1', 1)
  await k.steps('a1', 1, usageFull(SONNET, 170000, 100), SONNET)
  const b = await fig($, s)
  expect(b).toMatch(/ctx\s*85%/); expect(b).toContain('⚠')
})
each('M07 PB37 unknown window (unknown model, no windowsJson entry) => ctx shows a token count, no %', { options: { pricesJson: PRICES } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3); await run(k, 'a1', 1, { model: 'claude-mystery-9' })
  await k.steps('a1', 1, usageFull('claude-mystery-9', 82000, 100), 'claude-mystery-9')
  const b = await fig($, s)
  expect(b).toMatch(/ctx\s*82k(?![\d.]*%)/)
  expect(b).not.toMatch(/ctx\s*\d+%/)
})
each('M07 PB37 a windowsJson override changes the percent (window 100000, input 82000 => ctx 82%)', { options: { pricesJson: PRICES, windowsJson: WIN(100000) } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3); await run(k, 'a1', 1)
  await k.steps('a1', 1, usageFull(SONNET, 82000, 100), SONNET)
  expect(await fig($, s)).toMatch(/ctx\s*82%/)
})

// ---- PB38 null usage keeps figures; no step yet shows -- ----------------------
each('M07 PB38 usage:null leaves figures unchanged; an agent with no step shows ctx -- and ~$--', { options: { pricesJson: PRICES, windowsJson: WIN(200000) } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3); await run(k, 'a1', 1); await run(k, 'a2', 2)
  await k.steps('a1', 2, usageFull(SONNET, 20000, 500), SONNET)
  const core = (b: string) => b.match(/ctx.*?~\$[\d.<-]+/)?.[0] ?? '' // the figures only (the estimate/step count may move on any step)
  const before = core(await fig($, s))
  expect(before).toMatch(/ctx\s*10%/); expect(before).toContain('tok')
  await k.step({ agentId: 'a1', index: 2, model: SONNET, usage: null })
  expect(core(await fig($, s))).toBe(before)
  const b2 = await fig($, s, 'ship feature2')
  expect(b2).toMatch(/ctx\s*--/); expect(b2).toContain('~$--')
})

// ---- PB39 no mixing ------------------------------------------------------------
each('M07 PB39 usage of a2 does not change a1; a main-loop step changes no row', { options: { pricesJson: PRICES, windowsJson: WIN(200000) } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3); await run(k, 'a1', 1); await run(k, 'a2', 2)
  await k.steps('a1', 1, usageFull(SONNET, 20000, 500), SONNET)
  const a1 = await fig($, s)
  await k.steps('a2', 2, usageFull(SONNET, 90000, 500), SONNET)
  expect(await fig($, s)).toBe(a1)
  const a2 = await fig($, s, 'ship feature2')
  expect(a2).toMatch(/ctx\s*45%/)
  await k.step({ model: SONNET, usage: usageFull(SONNET, 150000, 900) }) // main loop: no agentId
  expect(await fig($, s)).toBe(a1); expect(await fig($, s, 'ship feature2')).toBe(a2)
})

// ---- PB40 run totals -------------------------------------------------------------
async function totalsScenario(k: Kit) {
  await makePlan(k, 3)
  await run(k, 'a1', 1); await run(k, 'a2', 2); await run(k, 'a3', 3)
  await k.steps('a1', 1, usageFull(SONNET, 1000, 0), SONNET)  // 0.40, 1000 tok
  await k.steps('a2', 1, usageFull(SONNET, 0, 3000), SONNET)  // 0.20, 3000 tok
  await k.steps('a3', 1, usageFull(SONNET, 200, 300), SONNET) // 0.10, 500 tok
  await k.complete('a1'); await k.complete('a2')
  await k.clock.advance(842_000) // 14:02 after the first run started
}
const RUNRE = /RUN\s*·.*?\bagents?\b/
each('M07 PB40 RUN line: ~$0.70 est., 4.5k tok, 14:02, 3 agents; same line in /mission status; not in the band', { options: { pricesJson: PRICES_RUN } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await totalsScenario(k)
  const line = runLineOf(await paneTree($, s))
  has(line, 'RUN'); has(line, '~$0.70'); has(line, 'est.'); expect(line).toMatch(/(4\.5k|5k)\s*tok/); has(line, '14:02'); has(line, '3 agents')
  const status = squash(String((await k.cmd('mission', 'status')).text))
  expect(status).toMatch(RUNRE)
  expect(squash(status.match(RUNRE)![0])).toBe(squash(line.match(RUNRE)![0]))
  expect(await bandOf(k, s)).not.toMatch(/\bRUN\s*·/)
})
each('M07 PB40 no runs => no RUN line in pane or status', { options: { pricesJson: PRICES_RUN } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3)
  expect(runLineOf(await paneTree($, s))).toBe('')
  expect(squash(String((await k.cmd('mission', 'status')).text))).not.toMatch(/\bRUN\s*·/)
})

// ---- PB41 unknown cost floor, backfilled not counted ----------------------------------
each('M07 PB41 a run with unknown cost makes the total a floor (~$0.40+); a backfilled run is not counted in agents', { options: { pricesJson: PRICES_RUN } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3); await run(k, 'a1', 1); await run(k, 'a2', 2) // a2 never reports usage
  await k.steps('a1', 1, usageFull(SONNET, 1000, 0), SONNET)
  k.w.live.set('ghost', { id: 'ghost', description: 'ghost job', type: 'general-purpose', status: 'running' })
  await k.clock.advance(3100)
  const line = runLineOf(await paneTree($, s))
  expect(line).toMatch(/~\$0\.40\+/); has(line, 'est.'); has(line, '2 agents'); expect(line).not.toContain('3 agents')
})
each('M07 PB41 all costs known => no + on the total', { options: { pricesJson: PRICES_RUN } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3); await run(k, 'a1', 1)
  await k.steps('a1', 1, usageFull(SONNET, 1000, 0), SONNET)
  const line = runLineOf(await paneTree($, s))
  expect(line).toMatch(/~\$0\.40(?!\+|\d)/); expect(line).toMatch(/\b1 agents?\b/)
})

// ---- PB42 elapsed clock ----------------------------------------------------------------
each('M07 PB42 elapsed follows the clock, freezes at allDone, restarts from 00:00 on a new plan', { options: { pricesJson: PRICES_RUN } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 2); await run(k, 'a1', 1); await run(k, 'a2', 2)
  await k.clock.advance(125_000)
  expect(timeIn(runLineOf(await paneTree($, s)))).toBe('02:05')
  await setStatus(k, 1, 'completed'); await setStatus(k, 2, 'completed')
  await k.complete('a1'); await k.complete('a2')
  await k.cmd('agents-review', 'done all')
  expect(await allDone(k)).toBe(true)
  const frozen = timeIn(runLineOf(await paneTree($, s)))
  expect(secs(frozen)).toBeGreaterThanOrEqual(125)
  await k.clock.advance(600_000)
  expect(timeIn(runLineOf(await paneTree($, s)))).toBe(frozen)
  k.w.files.set('/repo/docs/plans/y.md', '# p\n- [ ] ship feature9\n')
  await k.cmd('mission', 'plan docs/plans/y.md')
  await run(k, 'a9', 9)
  expect(secs(timeIn(runLineOf(await paneTree($, s))))).toBeLessThanOrEqual(5)
  await k.clock.advance(30_000)
  const t = secs(timeIn(runLineOf(await paneTree($, s))))
  expect(t).toBeGreaterThanOrEqual(30); expect(t).toBeLessThanOrEqual(40)
})

// ---- PB42b-e elapsed without a plan follows the current burst (F26) --------------------------
const MIN = 60_000
each('M07 PB42b no plan: finished run 12 h ago + running run of 5 min => 05:00, 2 agents, totals sum both', { options: { pricesJson: PRICES_RUN } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await run(k, 'a1', 1); await k.steps('a1', 1, usageFull(SONNET, 1000, 0), SONNET); await k.complete('a1')
  for (let i = 0; i < 6; i++) await k.clock.advance(120 * MIN) // 12 h in chunks (3 days is too slow at a 1 s tick) (the 1 s display tick limits one advance)
  await run(k, 'a2', 2); await k.steps('a2', 1, usageFull(SONNET, 0, 3000), SONNET)
  await k.clock.advance(5 * MIN)
  const line = runLineOf(await paneTree($, s))
  has(line, '05:00'); has(line, '2 agents'); has(line, '~$0.60'); expect(line).toMatch(/4k\s*tok/)
  const status = squash(String((await k.cmd('mission', 'status')).text))
  expect(status).toMatch(RUNRE)
  const sl = status.match(RUNRE)![0]
  has(sl, '05:00'); has(sl, '2 agents')
})
each('M07 PB42c no plan: one run 10:00-10:20 finished; elapsed 20:00 before and after 2 h idle', { options: { pricesJson: PRICES_RUN } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await run(k, 'a1', 1)
  await k.clock.advance(20 * MIN); await k.complete('a1')
  expect(timeIn(runLineOf(await paneTree($, s)))).toBe('20:00')
  await k.clock.advance(120 * MIN)
  expect(timeIn(runLineOf(await paneTree($, s)))).toBe('20:00')
  expect(timeIn(squash(String((await k.cmd('mission', 'status')).text).match(RUNRE)?.[0] ?? ''))).toBe('20:00')
})
each('M07 PB42d no plan: gap under 30 min joins the burst (50:00); gap of 40 min starts a new one (05:00)', { options: { pricesJson: PRICES_RUN } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await run(k, 'a1', 1); await k.clock.advance(20 * MIN); await k.complete('a1')   // 10:00-10:20
  await k.clock.advance(20 * MIN)
  await run(k, 'a2', 2); await k.clock.advance(10 * MIN); await k.complete('a2')   // 10:40-10:50
  expect(timeIn(runLineOf(await paneTree($, s)))).toBe('50:00')
  await k.clock.advance(10 * MIN)                                                   // 11:00, gap 10 min from a2
  expect(timeIn(runLineOf(await paneTree($, s)))).toBe('50:00')
})
each('M07 PB42d no plan: runs 10:00-10:20 and 11:00-11:05 (gap 40 min) => elapsed 05:00', { options: { pricesJson: PRICES_RUN } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await run(k, 'a1', 1); await k.clock.advance(20 * MIN); await k.complete('a1')   // 10:00-10:20
  await k.clock.advance(40 * MIN)
  await run(k, 'a2', 2); await k.clock.advance(5 * MIN); await k.complete('a2')    // 11:00-11:05
  expect(timeIn(runLineOf(await paneTree($, s)))).toBe('05:00')
})
each('M07 PB42e guard: with a plan, elapsed still freezes at allDone and restarts on a new plan', { options: { pricesJson: PRICES_RUN } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 2); await run(k, 'a1', 1); await run(k, 'a2', 2)
  await k.clock.advance(125_000)
  expect(timeIn(runLineOf(await paneTree($, s)))).toBe('02:05')
  await setStatus(k, 1, 'completed'); await setStatus(k, 2, 'completed')
  await k.complete('a1'); await k.complete('a2')
  await k.cmd('agents-review', 'done all')
  expect(await allDone(k)).toBe(true)
  const frozen = timeIn(runLineOf(await paneTree($, s)))
  expect(secs(frozen)).toBeGreaterThanOrEqual(125)
  await k.clock.advance(40 * MIN)   // longer than a burst gap: plan epoch rule still applies
  expect(timeIn(runLineOf(await paneTree($, s)))).toBe(frozen)
  k.w.files.set('/repo/docs/plans/y.md', '# p\n- [ ] ship feature9\n')
  await k.cmd('mission', 'plan docs/plans/y.md')
  await run(k, 'a9', 9)
  expect(secs(timeIn(runLineOf(await paneTree($, s))))).toBeLessThanOrEqual(5)
  await k.clock.advance(30_000)
  const t = secs(timeIn(runLineOf(await paneTree($, s))))
  expect(t).toBeGreaterThanOrEqual(30); expect(t).toBeLessThanOrEqual(40)
})

// ---- PB43 effort ---------------------------------------------------------------------------
async function effortRun(k: Kit, effort?: any) {
  await makePlan(k, 3); await run(k, 'a1', 1)
  if (effort !== undefined) { k.w.live.get('a1').effort = effort; await k.clock.advance(3100) }
}
each('M07 PB43 AgentInfo effort high shows after the model chip; a later turn.step effort low replaces it', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await effortRun(k, 'high')
  expect(await fig($, s)).toMatch(/sonnet\s+high\b/i)
  expect(await cardOf($, k, s)).toMatch(/effort high/)
  await stepX($, k, { agentId: 'a1', effort: 'low' })
  const b = await fig($, s)
  expect(b).toMatch(/sonnet\s+low\b/i); expect(b).not.toMatch(/\bhigh\b/i)
  expect(await cardOf($, k, s)).toMatch(/effort low/)
})
each('M07 PB43 no effort anywhere => no effort word on the row, "effort --" on the card', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await effortRun(k)
  const b = await fig($, s)
  expect(b).not.toMatch(/\b(low|med|medium|high|xhigh|max)\b/i)
  expect(b).not.toMatch(/\bb\d+k\b/)
  expect(await cardOf($, k, s)).toContain('effort --')
})
each('M07 PB43 numeric effort 8000 shows b8k', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await effortRun(k, 8000)
  expect(await fig($, s)).toMatch(/sonnet\s+b8k\b/i)
})
each('M07 PB43 medium is written "med" on the row only', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await effortRun(k, 'medium')
  const b = await fig($, s)
  expect(b).toMatch(/sonnet\s+med\b/i); expect(b).not.toMatch(/medium/i)
  expect(await cardOf($, k, s)).toMatch(/effort medium/)
})

// ---- PB44 step note --------------------------------------------------------------------------
each('M07 PB44 note: row "step 7/10 · wiring table", card "note: wiring table" with age', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3); await run(k, 'a1', 1)
  await stepCall(k, 'a1', { done: 7, total: 10, note: 'wiring table' })
  has(await fig($, s), 'step 7/10 · wiring table')
  await k.clock.advance(12_000)
  const c = await cardOf($, k, s)
  has(c, 'note: wiring table'); expect(c).toMatch(/12 s ago/)
})
each('M07 PB44 a 90-char note is stored as 60; the terminal row clips to 40', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3); await run(k, 'a1', 1)
  const note = Array.from({ length: 90 }, (_, i) => String.fromCharCode(97 + (i % 26))).join('')
  await stepCall(k, 'a1', { done: 7, total: 10, note })
  const stored = String((await mv(k)).steps.a1?.note ?? '')
  expect(stored.length).toBeLessThanOrEqual(60); expect(stored.length).toBeGreaterThanOrEqual(55)
  expect(stored.startsWith(note.slice(0, 55))).toBe(true)
  has(await cardOf($, k, s), note.slice(0, 55))
  if (s === 'terminal') {
    const b = await fig($, s)
    expect(b).toContain(note.slice(0, 30)); expect(b).not.toContain(note.slice(0, 45))
  }
})
each('M07 PB44 a report with no note (or a whitespace note) shows "step 7/10" and no "·" after it', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3); await run(k, 'a1', 1); await run(k, 'a2', 2)
  await stepCall(k, 'a1', { done: 7, total: 10 })
  await stepCall(k, 'a2', { done: 7, total: 10, note: '   ' })
  for (const f of ['ship feature1', 'ship feature2']) {
    const b = await fig($, s, f)
    expect(b).toMatch(/step 7\/10/); expect(b).not.toMatch(/step 7\/10\s*·/)
  }
})

// ---- PB45 accepted vs planned --------------------------------------------------------------------
each('M07 PB45 ACCEPTED 3 of 5 planned, 1 checked off by hand; a 4th reviewed run => ACCEPTED 4 of 5; no plan => no text', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  expect(acceptedLineOf(await paneTree($, s))).toBe('')
  await makePlan(k, 5)
  for (const [id, i] of [['a1', 1], ['a2', 2], ['a3', 3]] as const) { await run(k, id, i); await setStatus(k, i, 'completed'); await k.complete(id) }
  await setStatus(k, 4, 'completed') // checked off by hand, no run
  await k.cmd('agents-review', 'done all')
  let line = acceptedLineOf(await paneTree($, s))
  has(line, 'ACCEPTED 3 of 5 planned'); has(line, '1 checked off by hand')
  await run(k, 'a4', 4); await k.complete('a4')
  line = acceptedLineOf(await paneTree($, s))
  has(line, 'ACCEPTED 3 of 5'); expect(line).toMatch(/1 awaiting review/)
  await k.cmd('agents-review', 'done all')
  has(acceptedLineOf(await paneTree($, s)), 'ACCEPTED 4 of 5')
})

// ---- PB46 width ------------------------------------------------------------------------------------
each('M07 PB46 narrow: desktop ~300 px drops effort then tokens, keeps % and cost; terminal at 70 cols has no second line and ends with the context percent', { options: { pricesJson: PRICES, windowsJson: WIN(200000) } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await effortRun(k, 'high')
  await stepCall(k, 'a1', { done: 7, total: 10, note: 'wiring table' })
  await k.steps('a1', 1, usageFull(SONNET, 82000, 500), SONNET)
  if (s === 'desktop') {
    const b = await fig($, s, 'ship feature1', 39) // 39*8-16 = 296 px
    expect(b).toMatch(/41%/); expect(b).toContain('~$')
    expect(b).not.toMatch(/\bhigh\b/i); expect(b).not.toContain('tok')
  } else {
    const rows = sqRows(await paneTree($, s, 70))
    const line1 = rows.find((r) => r.includes('ship feature1') && /sonnet/i.test(r)) ?? ''
    expect(line1.length).toBeGreaterThan(0)
    expect(line1).toMatch(/41%$/)
    expect(rows.some((r) => /^ctx\b/.test(r))).toBe(false)
    expect(line1).not.toContain('tok')
  }
})

// ---- PB47 terminal text == Svg alt -------------------------------------------------------------------
test('M07 PB47 terminal text equals desktop alt for the figures line, the RUN line and the ACCEPTED line', { options: { pricesJson: PRICES, windowsJson: WIN(200000) } } as any, async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await makePlan(k, 3); await run(k, 'a1', 1); await run(k, 'a2', 2)
  await setStatus(k, 3, 'completed')
  await k.steps('a1', 2, usageFull(SONNET, 40000, 800), SONNET)
  await stepCall(k, 'a1', { done: 7, total: 10, note: 'wiring table' })
  await k.complete('a2')
  await k.clock.advance(65_000)
  const t = await paneTree($, 'terminal'), d = await paneTree($, 'desktop')
  const figLine = (tree: any) => sqRows(tree).find((r) => /^ctx\b/.test(r)) ?? ''
  expect(figLine(t)).not.toBe('')
  expect(figLine(d)).toBe(figLine(t))
  expect(runLineOf(t)).not.toBe(''); expect(runLineOf(d)).toBe(runLineOf(t))
  expect(acceptedLineOf(t)).not.toBe(''); expect(acceptedLineOf(d)).toBe(acceptedLineOf(t))
})

// ---- PB48 privacy and tokens --------------------------------------------------------------------------
each('M07 PB48 no prompt text in figure lines; nothing new registered; budget share stays <= 40', { options: { pricesJson: PRICES } }, async ($, on, s) => {
  const k = makeKit($, on); installUsage(k); await k.start(s)
  await makePlan(k, 3)
  await k.spawn({ description: title(1), prompt: 'SECRET123 [task:T1]', model: SONNET })
  await k.steps('a1', 2, usageFull(SONNET, 5000, 100), SONNET)
  const dump = [await k.paneText('mission', s), String((await k.cmd('mission', 'status')).text), await cardOf($, k, s), await bandOf(k, s), ...k.w.toasts, ...k.w.statuses.map(String), ...k.w.logs].join('\n')
  expect(dump).not.toContain('SECRET123')
  const rewritten = String(k.w.spawnSeen.at(-1)?.prompt ?? '')
  expect(rewritten).not.toMatch(/~\$|\bctx\b|\btok\b|\bRUN\b/)
  expect(k.w.tools.map((t) => t.name)).toEqual(['step'])
  expect(k.w.commands.filter((c) => /cost|ctx|context|effort|accepted|total|elapsed/i.test(String(c.name)))).toHaveLength(0)
  expect(k.w.agentTypes).toHaveLength(0)
  expect(k.w.tools.filter((t) => t.isDeferred === false)).toHaveLength(0)
  const share = missionShare(k, k.w.usageFn!({ breakdown: 'summary' }).context.breakdown)
  expect(share).toBeGreaterThan(0); expect(share).toBeLessThanOrEqual(40)
})

// ---- PB49 throwing usage reader --------------------------------------------------------------------------
const BAD_USAGE: [string, () => any][] = [
  ['getter throws', () => ({ model: SONNET, get input_tokens(): number { throw new Error('boom') }, output_tokens: 1 })],
  ['string', () => 'not-an-object'],
  ['number', () => 42],
  ['wrong field types', () => ({ model: 123, input_tokens: 'x', output_tokens: {}, cache_read_input_tokens: NaN, cache_creation_input_tokens: -5 })],
]
for (const [label, mk] of BAD_USAGE) each(`M07 PB49 malformed usage (${label}) never changes results and next is still called`, { options: { pricesJson: PRICES } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await makePlan(k, 3); await run(k, 'a1', 1)
  await k.step({ agentId: 'a1', index: 3, model: SONNET, usage: mk() }) // must not throw
  expect(k.w.steps).toHaveLength(0) // next was called: the bottom consumed the queued step result
  const n = k.w.results.length
  const t = await k.tool({ tool: 'Bash', command: 'echo hi' })
  expect(t).toEqual(k.w.results[n])
  const sp: any = await k.spawn({ description: 'plain', prompt: 'Do X', model: SONNET })
  expect(sp.agentId).toBeDefined(); expect(sp.deny).toBeUndefined()
  await k.cmd('mission', 'status') // must not throw
  await paneTree($, s) // render still works
})
