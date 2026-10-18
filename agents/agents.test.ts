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

function makeKit($: any, on: any, cfg: { store?: Record<string, unknown>; listed?: string[]; refuse?: string[] } = {}) {
  const clock = mock.clock(on, { now: T0 })
  const op = (name: string, fn: (e: any) => any) => on(name, async (_: any, e: any) => { try { return { value: await fn(e) } } catch (err: any) { return { deny: String(err?.message ?? err) } } })
  const w = {
    surface: 'terminal' as string,
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
  op('session.cwd', () => '/repo')
  op('session.root', () => '/repo')
  op('session.model', () => 'claude-opus-5-5')
  op('session.turns', () => 0)
  op('session.surfaces', () => [w.surface])
  op('session.surface', () => w.surface)
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
      case 'TaskCreate': r = { ref, result: { task: { id: String(++w.taskN), subject: e.subject } }, text: 'ok' }; break
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
    start: (surface: any = 'terminal', isInteractive = true) => (w.surface = surface ?? 'terminal', $.session.start({ cwd: '/repo', surface, isInteractive })),
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
// agents.md behaviour contract, section 9 (statements 1-32). Prefix: A07.
// ===========================================================================
const PRICES = JSON.stringify({
  asOf: '2026-10-11',
  fable: { input: 20, output: 100, cacheRead: 2, write5m: 25 },
  opus: { input: 10, output: 50, cacheRead: 1, write5m: 12.5 },
  sonnet: { input: 2, output: 10, cacheRead: 0.2, write5m: 2.5 },
  haiku: { input: 1, output: 5, cacheRead: 0.1, write5m: 1.25 },
})
const usage = (model: string, o: Partial<Record<'i' | 'o' | 'r' | 'c', number>> = {}) => ({
  model, input_tokens: o.i ?? 0, output_tokens: o.o ?? 0, cache_read_input_tokens: o.r ?? 0, cache_creation_input_tokens: o.c ?? 0,
})
const NO_MODEL_TOAST = (d: string) => `AGENT · NO MODEL SET: "${d}" started without a model. Add model: haiku or sonnet.`
const DENY_TEXT = 'Agent call needs an explicit model. Set model to haiku (search, read, bulk), sonnet (build, tests, docs), opus or fable (hard design only). Policy: ~/.claude/CLAUDE.md. Retry the same call with model set.'

// ---- 1 -------------------------------------------------------------------
each('A07 1 spawn shows a working pet in the pets pane', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.spawn({ description: 'research sweep', subagentType: 'Explore', model: 'claude-haiku-4-5' })
  const t = await k.paneText('pets', s)
  has(t, '1 working · 0 done'); hasI(t, 'detective'); has(t, 'Explore'); hasI(t, 'haiku'); has(t, 'research sweep')
})

// ---- 2 -------------------------------------------------------------------
const COSTUMES: [string, string, string, string | null][] = [
  // [description, subagentType, label, expected costume word (null = plain)]
  ['look around', 'Explore', 'Explore type', 'detective'],
  ['research the api', 'general-purpose', 'research', 'detective'],
  ['find the bug site', 'general-purpose', 'find', 'detective'],
  ['verify the output', 'general-purpose', 'verify', 'scientist'],
  ['debug flaky run', 'general-purpose', 'debug', 'scientist'],
  ['wire something', 'Plan', 'Plan type', 'planner'],
  ['design the layout', 'general-purpose', 'design', 'planner'],
  ['summarize results', 'general-purpose', 'summar', 'scribe'],
  ['write the readme', 'general-purpose', 'readme', 'scribe'],
  ['implement the thing', 'general-purpose', 'implement', 'builder'],
  ['refactor module', 'general-purpose', 'refactor', 'builder'],
  ['research then fix it', 'general-purpose', 'first rule wins: detective over builder', 'detective'],
  ['test the build', 'general-purpose', 'first rule wins: scientist over builder', 'scientist'],
  ['idle chatter', 'general-purpose', 'plain', null],
]
for (const [description, subagentType, label, costume] of COSTUMES) {
  each(`A07 2 costume mapping: ${label} (${description})`, {}, async ($, on, s) => {
    const k = makeKit($, on); await k.start(s)
    await k.spawn({ description, subagentType, model: 'haiku' })
    const t = (await k.paneText('pets', s)).toLowerCase()
    for (const c of ['detective', 'scientist', 'planner', 'scribe', 'builder']) {
      if (c === costume) expect(t).toContain(c); else expect(t).not.toContain(c)
    }
  })
}

// ---- 3 -------------------------------------------------------------------
each('A07 3 pane auto-opens on first spawn only; /pets toggles', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.fullscreen(s)
  const opens = () => k.w.opened.filter((i) => i === 'pets').length
  await k.spawn({ description: 'first job', model: 'haiku' })
  expect(opens()).toBe(1)
  await k.cmd('pets') // toggle: closes
  expect(k.w.open.has('pets')).toBe(false)
  await k.spawn({ description: 'second job', model: 'haiku' })
  expect(opens()).toBe(1)
  await k.cmd('pets') // opens
  expect(opens()).toBe(2)
  await k.cmd('pets') // closes
  expect(k.w.open.has('pets')).toBe(false)
})

// ---- 4 -------------------------------------------------------------------
each('A07 4 turn.complete answer => done, other reasons => failed; header updates', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  k.w.ids.push('A', 'B')
  await k.spawn({ description: 'job a', model: 'haiku' })
  await k.spawn({ description: 'job b', model: 'haiku' })
  has(await k.paneText('pets', s), '2 working · 0 done')
  await k.complete('A', 'answer')
  has(await k.paneText('pets', s), '1 working · 1 done')
  await k.complete('B', 'error')
  const t = await k.paneText('pets', s)
  has(t, '0 working'); hasI(t, 'failed')
  const runs = await k.st('runs')
  expect(runs.find((r: any) => r.agentId === 'A').status).toBe('done')
  expect(runs.find((r: any) => r.agentId === 'B').status).toBe('failed')
})

// ---- 5 -------------------------------------------------------------------
each('A07 5 description is clipped to <= 60 characters with an ellipsis', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  const long = 'abcdefghij'.repeat(8)
  await k.spawn({ description: long, model: 'haiku' })
  const t = await k.paneText('pets', s)
  const m = t.match(/abcdefghij[a-j]*…/)
  expect(m).not.toBeNull()
  expect(m![0].length).toBeLessThanOrEqual(60)
  expect(t).not.toContain(long.slice(0, 61))
})

// ---- 6 -------------------------------------------------------------------
each('A07 6 list-only pet appears after sync, goes done after two missed syncs, model learned from first step', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  k.w.live.set('x1', { id: 'x1', description: 'listed only job', type: 'general-purpose', status: 'running' })
  await k.clock.advance(3100)
  let t = await k.paneText('pets', s)
  has(t, '1 working'); has(t, 'listed only job'); hasI(t, 'other')
  await k.step({ agentId: 'x1', model: 'claude-sonnet-5-5', usage: usage('claude-sonnet-5-5', { i: 10, o: 10 }) })
  hasI(await k.paneText('pets', s), 'sonnet')
  k.w.live.delete('x1')
  await k.clock.advance(3100); await k.clock.advance(3100); await k.clock.advance(3100)
  t = await k.paneText('pets', s)
  has(t, '0 working · 1 done')
})

// ---- 7 -------------------------------------------------------------------
each('A07 7 empty pane text', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  has(await k.paneText('pets', s), 'No agents yet. Pets appear when a subagent starts.')
})

// ---- 8 -------------------------------------------------------------------
const TODOS = (done: number, n = 7) => Array.from({ length: n }, (_, i) => ({ content: `step ${i + 1} content`, status: i < done ? 'completed' : i === done ? 'in_progress' : 'pending', activeForm: `Doing step ${i + 1}` }))
each('A07 8 showChecklist=true shows 3/7, 43% and now:', { options: { showChecklist: true, mission_enabled: false } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.tool({ tool: 'TodoWrite', todos: TODOS(3) })
  let t = await k.bandText(s)
  has(t, '3/7'); has(t, '43%'); has(t, 'now: Doing step 4')
  await k.tool({ tool: 'TodoWrite', todos: TODOS(7).map((x) => ({ ...x, status: 'completed' })) })
  has(await k.bandText(s), 'all 7 done')
})
each('A07 8 showChecklist default (false) shows none of the checklist strings', { options: { mission_enabled: false } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.tool({ tool: 'TodoWrite', todos: TODOS(3) })
  const t = await k.bandText(s)
  lacks(t, '3/7'); lacks(t, '43%'); lacks(t, 'now:'); lacks(t, 'all 7 done')
})

// ---- 9 -------------------------------------------------------------------
each('A07 9 band: "2 working" button while pets run; row absent otherwise', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  let ui = await k.mountBand(s)
  expect(flat(await ui.drawn())).toBe(SENTINEL)
  await ui.unmount()
  k.w.ids.push('A', 'B')
  await k.spawn({ description: 'job a', model: 'haiku' })
  await k.spawn({ description: 'job b', model: 'haiku' })
  ui = await k.mountBand(s)
  const tree = await ui.drawn()
  expect(buttons(tree).some((b) => String(b.props.label).includes('2 working'))).toBe(true)
  await ui.unmount()
  await k.complete('A'); await k.complete('B')
  // finished and never queued for review would still leave a review item; mark them reviewed
  await k.cmd('agents-review', 'done all')
  ui = await k.mountBand(s)
  expect(flat(await ui.drawn())).toBe(SENTINEL)
})

// ---- 10 ------------------------------------------------------------------
for (const mascots of ['on', 'off'] as const) {
  test(`A07 10 mascot images in pet rows (pets.mascots=${mascots}) [desktop]`, { options: { 'pets_mascots': mascots } } as any, async ($: any, on: any) => {
    const k = makeKit($, on); await k.start('desktop')
    k.w.ids.push('R', 'F')
    await k.spawn({ description: 'running job', model: 'claude-haiku-4-5' })
    await k.spawn({ description: 'failing job', model: 'claude-haiku-4-5' })
    await k.complete('F', 'error')
    const ui = await k.mountPane('desktop', 'pets')
    const tree = await ui.drawn()
    const run = svgs(tree).find((e) => String(e.props.alt).includes('running job'))
    const fail = svgs(tree).find((e) => String(e.props.alt).includes('failing job'))
    expect(run).toBeDefined(); expect(fail).toBeDefined()
    expect(srcOf(fail)).not.toContain('<image')
    if (mascots === 'on') expect(srcOf(run)).toContain('<image'); else expect(srcOf(run)).not.toContain('<image')
    expect(String(run.props.alt)).toContain('running job'); expect(String(run.props.alt)).toMatch(/running/i) // same literal pattern with images on or off
  })
}

// ---- 11 ------------------------------------------------------------------
each('A07 11 review: finished agent enters the queue', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  k.w.ids.push('A')
  await k.spawn({ description: 'review me', model: 'haiku' })
  await k.complete('A', 'answer')
  has(await k.bandText(s), '1 to review')
  has(await k.paneText('pets', s), 'REVIEW QUEUE (1)')
})

// ---- 12 ------------------------------------------------------------------
each('A07 12 files touched, test sums, tests-failed listed before tests-passed', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  k.w.ids.push('P', 'Q')
  await k.spawn({ description: 'passing agent', model: 'haiku' })
  await k.spawn({ description: 'failing tests agent', model: 'haiku' })
  // P: one file, passing tests
  await k.tool({ tool: 'Edit', agentId: 'P', file_path: '/repo/p.ts' })
  k.w.bash = () => ({ stdout: '===== 5 passed in 1.00s =====', stderr: '', interrupted: false })
  await k.tool({ tool: 'Bash', agentId: 'P', command: 'pytest' })
  // Q: two distinct files (one edited twice), failing tests
  await k.tool({ tool: 'Edit', agentId: 'Q', file_path: '/repo/a.ts' })
  await k.tool({ tool: 'Edit', agentId: 'Q', file_path: '/repo/b.ts' })
  await k.tool({ tool: 'Edit', agentId: 'Q', file_path: '/repo/a.ts' })
  k.w.bash = () => ({ stdout: '===== 3 failed, 12 passed in 2.31s =====', stderr: '', interrupted: false })
  await k.tool({ tool: 'Bash', agentId: 'Q', command: 'pytest' })
  await k.complete('P'); await k.complete('Q')
  const t = await k.paneText('pets', s)
  has(t, '2 files'); has(t, '12 pass'); has(t, '3 fail')
  expect(t.toLowerCase()).toMatch(/tests[- ]failed/)
  expect(t.indexOf('failing tests agent')).toBeGreaterThan(-1)
  expect(t.indexOf('failing tests agent')).toBeLessThan(t.indexOf('passing agent'))
})

// ---- 13 ------------------------------------------------------------------
each('A07 13 UNTESTED / no edits / FAILED ordering', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  k.w.ids.push('N', 'U', 'C')
  await k.spawn({ description: 'noedit agent', model: 'haiku' })
  await k.spawn({ description: 'untested agent', model: 'haiku' })
  await k.spawn({ description: 'crashed agent', model: 'haiku' })
  await k.tool({ tool: 'Write', agentId: 'U', file_path: '/repo/new.ts' })
  await k.complete('N'); await k.complete('U'); await k.complete('C', 'error')
  const t = await k.paneText('pets', s)
  has(t, 'UNTESTED'); hasI(t, 'no edits'); has(t, 'FAILED')
  const iC = t.indexOf('crashed agent'), iU = t.indexOf('untested agent'), iN = t.indexOf('noedit agent')
  expect(iC).toBeGreaterThan(-1)
  expect(iC).toBeLessThan(iU)
  expect(iU).toBeLessThan(iN)
})

// ---- 13b (F31) test outcome only from a Bash test-runner call with a runner summary ----------
const SUMMARY = '===== 3 failed, 12 passed in 2.31s ====='
async function oneAgent(k: Kit, write: boolean, command?: string) {
  k.w.ids.push('Z')
  await k.spawn({ description: 'solo agent', model: 'haiku' })
  if (write) await k.tool({ tool: 'Write', agentId: 'Z', file_path: '/repo/new.ts' })
  if (command !== undefined) {
    k.w.bash = () => ({ stdout: SUMMARY, stderr: '', interrupted: false })
    await k.tool({ tool: 'Bash', agentId: 'Z', command })
  }
  await k.complete('Z')
}
const noOutcome = (t: string) => { lacks(t, '12 pass'); lacks(t, '3 fail'); lacks(t, 'TESTS FAILED'); lacks(t, 'TESTS PASSED'); expect(t.toLowerCase()).not.toMatch(/tests[- ](failed|passed)/) }
each('A07 13b Write + Bash `cat spec.md` printing a summary => UNTESTED, no counts', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await oneAgent(k, true, 'cat spec.md')
  const t = await k.paneText('pets', s)
  has(t, 'UNTESTED'); noOutcome(t)
})
each('A07 13b no Write + Bash `cat spec.md` printing a summary => NO EDITS', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await oneAgent(k, false, 'cat spec.md')
  const t = await k.paneText('pets', s)
  hasI(t, 'no edits'); noOutcome(t)
})
each('A07 13b `grep -n vitest notes.md` printing a summary is not a test run', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await oneAgent(k, true, 'grep -n vitest notes.md')
  const t = await k.paneText('pets', s)
  has(t, 'UNTESTED'); noOutcome(t)
})
each('A07 13b `echo "3 failed, 12 passed"` is not a test run', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await oneAgent(k, true, 'echo "3 failed, 12 passed"')
  const t = await k.paneText('pets', s)
  has(t, 'UNTESTED'); noOutcome(t)
})
each('A07 13b real `cd app && pytest -q` with a summary => tests-failed, 12 pass, 3 fail', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await oneAgent(k, true, 'cd app && pytest -q')
  const t = await k.paneText('pets', s)
  expect(t.toLowerCase()).toMatch(/tests[- ]failed/); has(t, '12 pass'); has(t, '3 fail')
})
each('A07 13b final answer text "12 passed 3 failed" is never parsed', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  k.w.ids.push('Z')
  await k.spawn({ description: 'solo agent', model: 'haiku' })
  await k.tool({ tool: 'Write', agentId: 'Z', file_path: '/repo/new.ts' })
  await $.turn.complete({ answer: 'All done: 12 passed 3 failed', durationMs: 1000, isAborted: false, turnId: 't-Z', agentId: 'Z', reason: 'answer' })
  const t = await k.paneText('pets', s)
  has(t, 'UNTESTED'); noOutcome(t)
})

// ---- 14 ------------------------------------------------------------------
async function queueThree(k: Kit) {
  k.w.ids.push('A', 'B', 'C')
  for (const [i, d] of ['job one', 'job two', 'job three'].entries()) {
    await k.spawn({ description: d, model: 'haiku' })
    await k.tool({ tool: 'Edit', agentId: ['A', 'B', 'C'][i], file_path: `/repo/f${i}.ts` })
    await k.complete(['A', 'B', 'C'][i])
  }
}
each('A07 14 /review done <id>, all, bare usage, unknown id', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await queueThree(k)
  has(await k.paneText('pets', s), 'REVIEW QUEUE (3)')
  let r = await k.cmd('agents-review', 'done 1')
  has(await k.paneText('pets', s), 'REVIEW QUEUE (2)')
  has(await k.bandText(s), '2 to review')
  r = await k.cmd('agents-review', 'done')
  has(String(r.text), 'Usage')
  has(await k.paneText('pets', s), 'REVIEW QUEUE (2)')
  r = await k.cmd('agents-review', 'done 99')
  has(String(r.text), 'No queue item 99')
  await k.cmd('agents-review', 'done all')
  lacks(await k.bandText(s), 'to review')
  has(await k.paneText('pets', s), '0 working · 3 done')
})
each('A07 14 REVIEWED button has the same effect as /review done <n>', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await queueThree(k)
  const ui = await k.mountPane(s, 'pets')
  const btn = buttons(await ui.drawn()).find((b) => /reviewed/i.test(String(b.props.label)))
  expect(btn).toBeDefined()
  await ui.press({ key: btn.props.key })
  has(flat(await ui.drawn()), 'REVIEW QUEUE (2)')
  expect(((await k.st('runs')) ?? []).filter((r: any) => r.reviewed).length).toBe(1)
})

// ---- 15 ------------------------------------------------------------------
each('A07 15 unreviewed item older than 10 min => "oldest 10 min"', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  k.w.ids.push('A')
  await k.spawn({ description: 'old job', model: 'haiku' })
  await k.complete('A')
  lacks(await k.bandText(s), 'oldest')
  await k.clock.advance(10 * 60_000)
  has(await k.bandText(s), 'oldest 10 min')
})

// ---- 16 ------------------------------------------------------------------
async function backfilledFinished(k: Kit) {
  k.w.live.set('ghost', { id: 'ghost', description: 'ghost job', type: 'general-purpose', status: 'running' })
  await k.clock.advance(3100)
  k.w.live.delete('ghost')
  for (let i = 0; i < 4; i++) await k.clock.advance(3100)
}
each('A07 16 backfilled agents are not queued', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await backfilledFinished(k)
  has(await k.paneText('pets', s), '0 working · 1 done')
  lacks(await k.bandText(s), 'to review')
})
each('A07 16 review.includeBackfilled=true queues them', { options: { 'review_includeBackfilled': true } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await backfilledFinished(k)
  has(await k.bandText(s), '1 to review')
})

// ---- 17 ------------------------------------------------------------------
test('A07 17 subagent tool.call results are returned unchanged', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  k.w.ids.push('A')
  await k.spawn({ description: 'job', model: 'haiku' })
  k.w.bash = () => ({ stdout: '===== 3 failed, 12 passed in 2.31s =====', stderr: '', interrupted: false })
  for (const over of [{ tool: 'Edit', file_path: '/repo/a.ts' }, { tool: 'Write', file_path: '/repo/b.ts' }, { tool: 'Bash', command: 'pytest' }, { tool: 'Read', file_path: '/repo/a.ts' }]) {
    const before = k.w.results.length
    const res = await k.tool({ ...over, agentId: 'A' })
    expect(res).toEqual(k.w.results[before])
  }
})

// ---- 18 ------------------------------------------------------------------
each('A07 18 guard warn: toast once, pane counts, limiter 30 s', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  const r = await k.spawn({ description: 'research sweep' })
  expect((r as any).deny).toBeUndefined()
  expect(k.w.toasts).toHaveLength(1)
  expect(k.w.toasts[0]).toContain('NO MODEL SET'); expect(k.w.toasts[0]).toContain('research sweep')
  expect(k.w.toasts[0]).toMatch(/^(\S+ )?AGENT · NO MODEL SET/)
  expect(k.w.toasts[0].replace(/^\S+ (?=AGENT)/, '')).toBe(NO_MODEL_TOAST('research sweep'))
  if (s === 'desktop') expect(k.w.toasts[0]).toBe(NO_MODEL_TOAST('research sweep'))
  has(await k.paneText('delegation', s), 'Explicit model: 0 of 1')
  await k.clock.advance(5000)
  await k.spawn({ description: 'second sweep' })
  expect(k.w.toasts).toHaveLength(1)
  has(await k.paneText('delegation', s), 'Explicit model: 0 of 2')
  expect((await k.st('spend'))?.violations).toHaveLength(2)
})

// ---- 19 ------------------------------------------------------------------
each('A07 19 explicit model, fork and savvy types pass silently', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.spawn({ description: 'explicit', model: 'haiku' })
  has(await k.paneText('delegation', s), 'Explicit model: 1 of 1')
  expect(k.w.toasts).toHaveLength(0)
  for (const over of [{ fork: true, subagentType: 'fork' }, { subagentType: 'savvy-light' }, { subagentType: 'savvy-flow:savvy-heavy' }]) {
    const r = await k.spawn({ description: 'silent ' + over.subagentType, ...over })
    expect((r as any).deny).toBeUndefined()
  }
  expect(k.w.toasts).toHaveLength(0)
  expect((await k.st('spend'))?.violations).toHaveLength(0)
})

// ---- 20 ------------------------------------------------------------------
each('A07 20 /delegation deny blocks model-less spawns without calling beneath', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.cmd('delegation', 'deny')
  expect((await k.st('guard'))?.mode).toBe('deny')
  const r: any = await k.spawn({ description: 'no model here' })
  expect(typeof r.deny).toBe('string')
  expect(r.deny).toContain('model'); expect(r.deny).toContain('haiku')
  expect(r.deny).toBe(DENY_TEXT)
  expect(k.w.spawnSeen).toHaveLength(0)
  const ok: any = await k.spawn({ description: 'with model', model: 'haiku' })
  expect(ok.deny).toBeUndefined()
  expect(k.w.spawnSeen).toHaveLength(1)
})

// ---- 21 ------------------------------------------------------------------
each('A07 21 /delegation off, status, stored mode survives a new session', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.spawn({ description: 'v1' }); await k.clock.advance(31_000); await k.spawn({ description: 'v2' })
  let r = await k.cmd('delegation', 'status')
  has(String(r.text), 'warn'); has(String(r.text), '2')
  const toasts = k.w.toasts.length
  await k.cmd('delegation', 'off')
  const ok: any = await k.spawn({ description: 'silent now' })
  expect(ok.deny).toBeUndefined()
  expect(k.w.toasts).toHaveLength(toasts)
  r = await k.cmd('delegation', 'status')
  has(String(r.text), 'off')
  await k.cmd('delegation', 'deny')
  const stored = k.w.store['guard:mode']
  expect(stored).toMatchObject({ v: 1 })
  expect(JSON.stringify(stored)).toContain('deny')
})
test('A07 21 a new session with the store kept starts in the stored mode', async ($: any, on: any) => {
  const k = makeKit($, on, { store: { 'guard:mode': { v: 1, mode: 'deny' } } })
  await k.start('terminal')
  const r: any = await k.spawn({ description: 'stored deny' })
  expect(typeof r.deny).toBe('string')
})

// ---- 22 / 23 / 24 / 25 / 26 ---------------------------------------------
async function twoSteps(k: Kit) {
  k.w.ids.push('S1')
  await k.spawn({ description: 'sub job', model: 'claude-sonnet-5-5' })
  await k.step({ usage: usage('claude-opus-5-5', { i: 1_000_000 }) })
  await k.step({ agentId: 'S1', usage: usage('claude-sonnet-5-5', { o: 200_000 }) })
}
each('A07 22 spend by tier from main and subagent steps', { options: { pricesJson: PRICES } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await twoSteps(k)
  const t = await k.paneText('delegation', s)
  has(t, 'OPUS'); has(t, '$10.00'); has(t, 'SONNET'); has(t, '$2.00')
})
test('A07 23 bar proportions: 17 O and 3 S of 20 cells [terminal]', { options: { pricesJson: PRICES } } as any, async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await twoSteps(k)
  const t = await k.paneText('delegation', 'terminal')
  const m = t.match(/\[([A-Z]{20})\]/)
  expect(m).not.toBeNull()
  expect(m![1].split('O').length - 1).toBe(17)
  expect(m![1].split('S').length - 1).toBe(3)
})
each('A07 24 unknown model id is tier OTHER, counted, no exception', { options: { pricesJson: PRICES } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.step({ usage: usage('foo-1', { i: 1_000_000 }) })
  await k.step({ usage: usage('claude-opus-5-5', { i: 100_000 }) })
  const t = await k.paneText('delegation', s)
  has(t, 'OTHER'); has(t, 'OPUS'); lacks(t, 'No spend yet')
})
each('A07 25 footnote: session total and differs when > 15% apart', { options: { pricesJson: PRICES } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.step({ usage: usage('claude-opus-5-5', { i: 1_200_000 }) }) // estimate $12.00
  await $.session.measure({ context: { window: 200000 }, rateLimits: [], cost: { usd: 14 }, changed: ['cost'] })
  let t = await k.paneText('delegation', s)
  has(t, 'session total $14.00'); has(t, 'differs')
  await $.session.measure({ context: { window: 200000 }, rateLimits: [], cost: { usd: 13 }, changed: ['cost'] })
  t = await k.paneText('delegation', s)
  has(t, 'session total $13.00'); lacks(t, 'differs')
})
each('A07 26 empty spend', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  has(await k.paneText('delegation', s), 'No spend yet')
})

// ---- 27 / 28 -------------------------------------------------------------
each('A07 27 band hidden on survey, agent view, small maxRows; inner preserved', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.spawn({ description: 'running job', model: 'haiku' })
  for (const over of [{ hasSurvey: true }, { view: { agentId: 'a1' } }, { maxRows: 3 }]) {
    const ui = await k.mountBand(s, over)
    expect(flat(await ui.drawn())).toBe(SENTINEL)
    await ui.unmount()
  }
})
each('A07 28 plugin band and a sentinel inner band are both visible', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.spawn({ description: 'running job', model: 'haiku' })
  const t = await k.bandText(s)
  has(t, SENTINEL); has(t, '1 working')
})
test('A07 28 band text equals across surfaces except the pets button label (documented exception to conventions 10.2)', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await k.spawn({ description: 'running job', model: 'haiku' })
  const strip = (t: string) => squash(t.replace(/(🐾 )?\d+ working/g, ''))
  expect(strip(await k.bandText('desktop'))).toBe(strip(await k.bandText('terminal')))
})

// ---- 29 ------------------------------------------------------------------
each('A07 29 no auto-review: item survives prompt, read and 30 min', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  k.w.ids.push('A')
  await k.spawn({ description: 'touching job', model: 'haiku' })
  await k.tool({ tool: 'Edit', agentId: 'A', file_path: '/repo/touched.ts' })
  await k.complete('A')
  await $.prompt.submit({ text: 'next thing', origin: { kind: 'composer' } })
  await k.tool({ tool: 'Read', file_path: '/repo/touched.ts' })
  await k.clock.advance(30 * 60_000)
  has(await k.bandText(s), '1 to review')
  has(await k.paneText('pets', s), 'REVIEW QUEUE (1)')
})

// ---- 30 ------------------------------------------------------------------
test('A07 30 cast: Pom on working rows, Carrot on review and delegation headers (mascots=on) [desktop]', { options: { 'pets_mascots': 'on' } } as any, async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('desktop')
  k.w.ids.push('R', 'D')
  await k.spawn({ description: 'running job', model: 'haiku' })
  await k.spawn({ description: 'finished job', model: 'haiku' })
  await k.complete('D')
  let ui = await k.mountPane('desktop', 'pets')
  let tree = await ui.drawn()
  const row = svgs(tree).find((e) => String(e.props.alt).includes('running job'))
  expect(srcOf(row)).toContain('<image'); expect(srcOf(row)).toContain('data-mascot="pom"'); expect(srcOf(row)).not.toContain('data-mascot="carrot"')
  const head = svgs(tree).find((e) => String(e.props.alt).includes('REVIEW QUEUE'))
  expect(head).toBeDefined()
  expect(srcOf(head)).toContain('data-mascot="carrot"'); expect(srcOf(head)).not.toContain('data-mascot="pom"')
  await ui.unmount()
  ui = await k.mountPane('desktop', 'delegation'); tree = await ui.drawn()
  const dh = svgs(tree).find((e) => /delegation|guard/i.test(String(e.props.alt)))
  expect(dh).toBeDefined()
  expect(srcOf(dh)).toContain('data-mascot="carrot"'); expect(srcOf(dh)).not.toContain('data-mascot="pom"')
})
test('A07 30 mascots=off: no data-mascot anywhere, block mark instead [desktop]', { options: { 'pets_mascots': 'off' } } as any, async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('desktop')
  k.w.ids.push('R', 'D')
  await k.spawn({ description: 'running job', model: 'haiku' })
  await k.spawn({ description: 'finished job', model: 'haiku' })
  await k.complete('D')
  for (const id of ['pets', 'delegation']) {
    const ui = await k.mountPane('desktop', id)
    const all = svgs(await ui.drawn()).map(srcOf).join('\n')
    expect(all).not.toContain('data-mascot'); expect(all).not.toContain('<image')
    await ui.unmount()
  }
})

// ---- 31 ------------------------------------------------------------------
each('A07 31 price label: built-in table "estimate (prices as of YYYY-MM-DD"', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.step({ usage: usage('claude-opus-5-5', { i: 1000 }) })
  const t = await k.paneText('delegation', s)
  has(t, 'estimate (prices as of ')
  expect(t).toMatch(/prices as of \d{4}-\d{2}-\d{2}/)
  lacks(t, 'custom'); expect(k.w.net).toBe(0)
})
each('A07 31 price label: pricesJson set => ", custom)"', { options: { pricesJson: PRICES } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.step({ usage: usage('claude-opus-5-5', { i: 1000 }) })
  const t = await k.paneText('delegation', s)
  expect(t).toMatch(/estimate \(prices as of \d{4}-\d{2}-\d{2}, custom\)/)
  expect(k.w.net).toBe(0)
})
each('A07 31 invalid pricesJson => built-in table, no exception, no network', { options: { pricesJson: '{not json' } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.step({ usage: usage('claude-opus-5-5', { i: 1000 }) })
  const t = await k.paneText('delegation', s)
  has(t, 'estimate (prices as of '); lacks(t, 'custom')
  expect(k.w.net).toBe(0); expect(k.w.proc).toBe(0)
})

// ---- 32 ------------------------------------------------------------------
test('A07 32 state namespace is agents, /pets registered, legacy store keys ignored', async ($: any, on: any) => {
  const k = makeKit($, on, { store: { 'agent-pets:legacy': { v: 1, junk: true }, 'pets:old': 'x' } })
  await k.start('terminal')
  await k.spawn({ description: 'ns check', model: 'haiku' })
  const runs = await k.st('runs')
  expect(Array.isArray(runs)).toBe(true); expect(runs).toHaveLength(1)
  const names = k.w.commands.map((c) => c.name)
  expect(names).toContain('pets'); expect(names).toContain('agents-review'); expect(names).toContain('delegation')
})

// ---- 33 (conventions 1.6: command fallback against a host that refuses built-in names) ----
const cmdNames = (k: Kit) => k.w.commands.map((c) => c.name)
test('A07 33a built-in /review refused => agents-review registered, review is not', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  const names = cmdNames(k)
  expect(names).toContain('agents-review'); expect(names).not.toContain('review')
  expect(k.w.listed).not.toContain('review')
})
test('A07 33b agents-review lists the queue and done 1 / done all / bare done behave', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await queueThree(k)
  let r = await $.command.run({ command: 'agents-review', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 120 } })
  for (const d of ['job one', 'job two', 'job three']) has(String(r.text), d)
  r = await $.command.run({ command: 'agents-review', args: 'done', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 120 } })
  has(String(r.text), 'Usage: /agents-review done <id|all>')
  has(await k.paneText('pets', 'terminal'), 'REVIEW QUEUE (3)')
  await $.command.run({ command: 'agents-review', args: 'done 1', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 120 } })
  has(await k.paneText('pets', 'terminal'), 'REVIEW QUEUE (2)')
  await $.command.run({ command: 'agents-review', args: 'done all', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 120 } })
  lacks(await k.bandText('terminal'), 'to review')
})
test('A07 33c free names register bare: pets, mission, delegation', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  const names = cmdNames(k)
  for (const n of ['pets', 'mission', 'delegation']) expect(names).toContain(n)
  for (const n of ['agents-pets', 'agents-mission', 'agents-delegation']) expect(names).not.toContain(n)
})
for (const n of ['pets', 'mission']) {
  test(`A07 33d command.list shows ${n} from another source => agents-${n} registered`, async ($: any, on: any) => {
    const k = makeKit($, on, { listed: ['help', 'compact', n] }); await k.start('terminal')
    const names = cmdNames(k)
    expect(names).toContain(`agents-${n}`); expect(names).not.toContain(n)
    expect(names).toContain('agents-review')
  })
}
test('A07 33e bare and prefixed both refused: start does not throw, other commands still register', async ($: any, on: any) => {
  const k = makeKit($, on, { refuse: ['pets', 'agents-pets'] })
  await k.start('terminal')
  const names = cmdNames(k)
  expect(names).not.toContain('pets'); expect(names).not.toContain('agents-pets')
  expect(names).toContain('agents-review'); expect(names).toContain('delegation'); expect(names).toContain('mission')
})
test('A07 33e review bare and prefixed both refused: other commands still register', async ($: any, on: any) => {
  const k = makeKit($, on, { refuse: ['agents-review'] })
  await k.start('terminal')
  const names = cmdNames(k)
  expect(names).not.toContain('review'); expect(names).not.toContain('agents-review')
  for (const n of ['pets', 'mission', 'delegation']) expect(names).toContain(n)
})

// ---- skipped / manual ------------------------------------------------------
skip('A07 10 probe: Svg scrub keeps data: images (UNVERIFIED, desktop acceptance probe)', 'needs a real desktop surface paint')
skip('A07 acceptance: spawn 3 real subagents (haiku, sonnet, none) and watch pane, bar, toast', 'manual list')
skip('A07 acceptance: /delegation deny blocks a real model-less Agent call and the model retries', 'manual list')
skip('A07 acceptance: light/dark and with awareness installed no duplicate checklist', 'manual list')
skip('A07 acceptance: legacy agent-pets suite passes for retained behaviours', 'separate legacy suite')
