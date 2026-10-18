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
    cnt: { list: 0, fs: 0, set: 0 },
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
  on('state.set', (_: any, e: any, next: any) => { if (e.plugin === 'agents') w.cnt.set++; w.state[`${e.plugin}.${e.key}`] = e.value; return next(e) })
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
  op('agent.list', () => { w.cnt.list++; if (w.listFail) throw new Error('list failed'); return [...w.live.values()] })
  op('session.id', () => 'sess-1')
  op('session.cwd', () => '/repo')
  op('session.root', () => '/repo')
  op('session.model', () => 'claude-opus-5-5')
  op('session.turns', () => 0)
  op('session.surfaces', () => [w.surface])
  op('session.surface', () => w.surface)
  op('session.usage', (e: any) => w.usageFn ? w.usageFn(e) : ({ startedAt: T0, context: { window: 200000 }, rateLimits: [], cost: { usd: w.cost ?? 0 } }))
  op('fs.read', (e: any) => { w.cnt.fs++; if (w.fsFail) throw new Error('fs failed'); const f = findFile(e.path); if (!f) throw new Error('ENOENT ' + e.path); return f[1] })
  op('fs.exists', (e: any) => { w.cnt.fs++; if (w.fsFail) throw new Error('fs failed'); return !!findFile(e.path) })
  op('fs.stat', (e: any) => { w.cnt.fs++; if (w.fsFail) throw new Error('fs failed'); const f = findFile(e.path); if (!f) throw new Error('ENOENT ' + e.path); return { kind: 'file', size: f[1].length, mtimeMs: T0, isLink: false } })
  op('fs.list', () => { w.cnt.fs++; return [] })
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
      return await s.result
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
// agents.md F34 behaviour contract, statements 33-47. Prefix: A34.
// ===========================================================================
const usage = (model: string, o: Partial<Record<'i' | 'o' | 'r' | 'c', number>> = {}) => ({
  model, input_tokens: o.i ?? 0, output_tokens: o.o ?? 0, cache_read_input_tokens: o.r ?? 0, cache_creation_input_tokens: o.c ?? 0,
})
const OPUS = 'claude-opus-5-5'
const SMALL = usage(OPUS, { i: 10, r: 1000 }) // ctx 1010 => "1k"
/** Terminal toasts may carry one leading glyph; desktop none (toastGlyph). */
const tg = (t: string) => t.replace(/^\S+ (?=AGENT)/, '')
const nestToasts = (k: Kit) => k.w.toasts.filter((t) => t.includes('NESTED SPAWN'))
const runToasts = (k: Kit) => k.w.toasts.filter((t) => t.includes('AGENT RUNAWAY'))
const NEST_DENY = 'Agent call refused: you are a subagent, and subagents must not start subagents. Stop now and do not retry this call. Return to the orchestrator with your result so far and say exactly what you still need (the task, the files or the information); the orchestrator will delegate it. Policy: ~/.claude/CLAUDE.md.'
const nested = (over: any = {}) => ({ parentAgentId: 'A1', model: 'haiku', description: 'deep dig', ...over })
/** Start a running parent run A1 "research sweep". */
async function withParent(k: Kit) { k.w.ids.push('A1'); await k.spawn({ description: 'research sweep', model: 'haiku' }) }
const explicitLine = (t: string) => (squash(t).match(/Explicit model: \d+ of \d+/) ?? [''])[0]

// ---- 33 -------------------------------------------------------------------
each('A34 33 nesting warn (default): passes, one toast, pane rows', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await withParent(k)
  const seen = k.w.spawnSeen.length
  const r: any = await k.spawn(nested())
  expect(r.deny).toBeUndefined()
  expect(k.w.spawnSeen).toHaveLength(seen + 1)
  const ev = k.w.spawnSeen[seen]
  expect(ev.parentAgentId).toBe('A1'); expect(ev.description).toBe('deep dig'); expect(ev.model).toBe('haiku')
  expect(nestToasts(k)).toHaveLength(1)
  const t = tg(nestToasts(k)[0])
  expect(t).toBe('AGENT · NESTED SPAWN: "deep dig" was started by subagent "research sweep". Subagents should return to the orchestrator instead.')
  const p = await k.paneText('delegation', s)
  has(p, 'NESTING GUARD · warn')
  has(p, '⚠ AGENT · NESTED SPAWN · deep dig · by research sweep')
})
each('A34 33 unknown parent id shows "agent abcdef12"', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.spawn(nested({ parentAgentId: 'abcdef1234' }))
  expect(nestToasts(k)).toHaveLength(1)
  has(nestToasts(k)[0], 'agent abcdef12'); lacks(nestToasts(k)[0], 'abcdef1234')
  has(await k.paneText('delegation', s), 'by agent abcdef12')
})

// ---- 34 -------------------------------------------------------------------
each('A34 34 spawn without parentAgentId: no nesting toast, row or count', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  const r: any = await k.spawn({ description: 'main level', model: 'haiku' })
  expect(r.deny).toBeUndefined()
  expect(nestToasts(k)).toHaveLength(0)
  const p = await k.paneText('delegation', s)
  has(p, 'no nested spawns'); lacks(p, 'NESTED SPAWN')
})

// ---- 35 -------------------------------------------------------------------
each('A34 35 limiter: counted without toast within gap, toast after the gap', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.spawn(nested({ description: 'n1' }))
  expect(nestToasts(k)).toHaveLength(1)
  await k.clock.advance(5000)
  await k.spawn(nested({ description: 'n2' }))
  expect(nestToasts(k)).toHaveLength(1)
  has(String((await k.cmd('delegation', 'nesting')).text), 'nested spawns 2')
  await k.clock.advance(30_000)
  await k.spawn(nested({ description: 'n3' }))
  expect(nestToasts(k)).toHaveLength(2)
  has(String((await k.cmd('delegation', 'nesting')).text), 'nested spawns 3')
})
each('A34 35 nesting_toast=false: never a toast, rows still added', { options: { nesting_toast: false } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.spawn(nested({ description: 'n1' }))
  await k.clock.advance(60_000)
  await k.spawn(nested({ description: 'n2' }))
  expect(nestToasts(k)).toHaveLength(0)
  const p = await k.paneText('delegation', s)
  has(p, 'NESTED SPAWN · n1'); has(p, 'NESTED SPAWN · n2')
})

// ---- 36 -------------------------------------------------------------------
each('A34 36 /delegation nesting deny: stored, nested spawn denied, beneath not called', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  const r0 = await k.cmd('delegation', 'nesting deny')
  expect(String(r0.text)).toContain('Nesting guard: mode deny.')
  expect(k.w.store['nesting:mode']).toEqual({ v: 1, mode: 'deny' })
  const r: any = await k.spawn(nested())
  expect(typeof r.deny).toBe('string')
  expect(r.deny).toContain('subagent'); expect(r.deny).toContain('Stop'); expect(r.deny).toContain('orchestrator'); expect(r.deny).not.toContain('Retry')
  expect(r.deny).toBe(NEST_DENY)
  expect(k.w.spawnSeen).toHaveLength(0)
  expect(k.w.toasts).toHaveLength(0)
  has(await k.paneText('delegation', s), '⚠ AGENT · NESTED SPAWN · deep dig · by agent A1')
  const ok: any = await k.spawn({ description: 'main level', model: 'haiku' })
  expect(ok.deny).toBeUndefined()
  expect(k.w.spawnSeen).toHaveLength(1)
})
each('A34 36 nested model-less spawn in deny mode leaves model counts and violations unchanged', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.spawn({ description: 'explicit', model: 'haiku' })
  await k.cmd('delegation', 'nesting deny')
  const before = explicitLine(await k.paneText('delegation', s))
  const vBefore = ((await k.st('spend'))?.violations ?? []).length
  const r: any = await k.spawn({ parentAgentId: 'A1', description: 'no model nested' })
  expect(r.deny).toBe(NEST_DENY)
  expect(explicitLine(await k.paneText('delegation', s))).toBe(before)
  expect(((await k.st('spend'))?.violations ?? []).length).toBe(vBefore)
  expect(k.w.toasts).toHaveLength(0)
})

// ---- 37 -------------------------------------------------------------------
each('A34 37 /delegation nesting off: passes, no toast, no row, no count; bare text', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  const r0 = await k.cmd('delegation', 'nesting off')
  expect(String(r0.text)).toContain('Nesting guard: mode off.')
  const r: any = await k.spawn(nested())
  expect(r.deny).toBeUndefined()
  expect(k.w.spawnSeen).toHaveLength(1)
  expect(k.w.toasts).toHaveLength(0)
  const p = await k.paneText('delegation', s)
  lacks(p, 'NESTED SPAWN'); has(p, 'no nested spawns')
  has(String((await k.cmd('delegation', 'nesting')).text), 'Nesting guard: mode off · nested spawns 0')
})
each('A34 37 /delegation nesting maybe: usage text, mode unchanged', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  const r = await k.cmd('delegation', 'nesting maybe')
  has(String(r.text), 'Usage: /delegation nesting warn|deny|off')
  has(String((await k.cmd('delegation', 'nesting')).text), 'Nesting guard: mode warn · nested spawns 0')
  expect(k.w.store['nesting:mode']).toBeUndefined()
})

// ---- 38 -------------------------------------------------------------------
each('A34 38 independence of the two modes, status text, new session', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.cmd('delegation', 'deny')
  has(String((await k.cmd('delegation', 'nesting')).text), 'mode warn')
  await k.cmd('delegation', 'off')
  const guardStored = JSON.stringify(k.w.store['guard:mode'])
  expect(guardStored).toContain('off')
  await k.cmd('delegation', 'nesting deny')
  expect(JSON.stringify(k.w.store['guard:mode'])).toBe(guardStored)
  const st = String((await k.cmd('delegation', 'status')).text)
  has(st, 'off'); has(st, ' · nesting deny · nested 0')
})
each('A34 38 /delegation status keeps old substrings and appends nesting', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.spawn({ description: 'v1' }); await k.clock.advance(31_000); await k.spawn({ description: 'v2' })
  const st = String((await k.cmd('delegation', 'status')).text)
  has(st, 'warn'); has(st, '2'); has(st, ' · nesting warn · nested 0')
})
test('A34 38 a new session with the store kept starts in the stored nesting mode', async ($: any, on: any) => {
  const k = makeKit($, on, { store: { 'nesting:mode': { v: 1, mode: 'deny' } } })
  await k.start('terminal')
  const r: any = await k.spawn(nested())
  expect(r.deny).toBe(NEST_DENY)
  const ok: any = await k.spawn({ description: 'main', model: 'haiku' })
  expect(ok.deny).toBeUndefined()
})
test('A34 38 stored nesting mode beats the option default', { options: { nesting_mode: 'off' } } as any, async ($: any, on: any) => {
  const k = makeKit($, on, { store: { 'nesting:mode': { v: 1, mode: 'deny' } } })
  await k.start('terminal')
  const r: any = await k.spawn(nested())
  expect(r.deny).toBe(NEST_DENY)
})
test('A34 38 nesting_mode option default deny; invalid stored value falls back to the option', { options: { nesting_mode: 'deny' } } as any, async ($: any, on: any) => {
  const k = makeKit($, on, { store: { 'nesting:mode': { v: 1, mode: 'bogus' } } })
  await k.start('terminal')
  const r: any = await k.spawn(nested())
  expect(r.deny).toBe(NEST_DENY)
})

// ---- 39 -------------------------------------------------------------------
const NOT_EXEMPT: [string, any][] = [
  ['fork', { fork: true, subagentType: 'fork' }],
  ['savvy-light', { subagentType: 'savvy-light' }],
  ['savvy-flow:savvy-heavy', { subagentType: 'savvy-flow:savvy-heavy' }],
]
for (const [label, over] of NOT_EXEMPT) {
  each(`A34 39 ${label} inside a subagent is not exempt (warn -> toast)`, {}, async ($, on, s) => {
    const k = makeKit($, on); await k.start(s)
    const r: any = await k.spawn(nested(over))
    expect(r.deny).toBeUndefined()
    expect(nestToasts(k)).toHaveLength(1)
  })
  each(`A34 39 ${label} inside a subagent is not exempt (deny -> deny)`, { options: { nesting_mode: 'deny' } }, async ($, on, s) => {
    const k = makeKit($, on); await k.start(s)
    const r: any = await k.spawn(nested(over))
    expect(typeof r.deny).toBe('string')
    expect(k.w.spawnSeen).toHaveLength(0)
  })
}
each('A34 39 nesting_allowTypes=Explore: Explore passes silently with no row, other types do not', { options: { nesting_allowTypes: 'Explore' } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  const r: any = await k.spawn(nested({ subagentType: 'Explore' }))
  expect(r.deny).toBeUndefined()
  expect(k.w.toasts).toHaveLength(0)
  const p = await k.paneText('delegation', s)
  has(p, 'no nested spawns')
  has(String((await k.cmd('delegation', 'nesting')).text), 'nested spawns 0')
  await k.spawn(nested({ subagentType: 'Plan' }))
  expect(nestToasts(k)).toHaveLength(1)
})
for (const mode of ['warn', 'deny'] as const) {
  each(`A34 39 workflow spawn with parentAgentId passes silently (${mode})`, { options: { nesting_mode: mode } }, async ($, on, s) => {
    const k = makeKit($, on); await k.start(s)
    const r: any = await k.spawn(nested({ workflow: { runId: 'wf_1', agentIndex: 1 } }))
    expect(r.deny).toBeUndefined()
    expect(k.w.spawnSeen).toHaveLength(1)
    expect(k.w.toasts).toHaveLength(0)
    has(await k.paneText('delegation', s), 'no nested spawns')
  })
}

// ---- 40 -------------------------------------------------------------------
each('A34 40 nesting warn + guard warn + model-less nested: two toasts, separate limiters', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  const r: any = await k.spawn({ parentAgentId: 'A1', description: 'no model nested' })
  expect(r.deny).toBeUndefined()
  expect(k.w.toasts).toHaveLength(2)
  expect(k.w.toasts.filter((t) => t.includes('NESTED SPAWN'))).toHaveLength(1)
  expect(k.w.toasts.filter((t) => t.includes('NO MODEL SET'))).toHaveLength(1)
})
each('A34 40 nesting deny + model-less nested: only the nesting deny text', { options: { nesting_mode: 'deny' } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  const r: any = await k.spawn({ parentAgentId: 'A1', description: 'no model nested' })
  expect(r.deny).toBe(NEST_DENY)
  expect(r.deny).not.toContain('model'); expect(r.deny).not.toContain('haiku')
  expect(k.w.toasts).toHaveLength(0)
})

// ---- 41 -------------------------------------------------------------------
const RUN_A = 'AGENT RUNAWAY · "research sweep" · 100 steps · 1k ctx · consider stopping it'
async function spawnAs(k: Kit, id: string, description = 'research sweep') { k.w.ids.push(id); await k.spawn({ description, model: 'haiku' }) }
each('A34 41 runaway steps: silent at 99, one toast at 100, none after; results unchanged', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await spawnAs(k, 'A')
  const toolsSeen = k.w.toolSeen.length, spawns = k.w.spawnSeen.length
  for (let i = 0; i < 99; i++) {
    const res: any = await k.step({ agentId: 'A', index: i, usage: SMALL })
    expect(res?.deny).toBeUndefined()
  }
  expect(runToasts(k)).toHaveLength(0)
  const r100: any = await k.step({ agentId: 'A', index: 99, usage: SMALL })
  expect(r100?.deny).toBeUndefined()
  expect(runToasts(k)).toHaveLength(1)
  expect(tg(runToasts(k)[0])).toBe(RUN_A)
  for (let i = 100; i < 200; i++) {
    const res: any = await k.step({ agentId: 'A', index: i, usage: SMALL })
    expect(res?.deny).toBeUndefined()
  }
  expect(runToasts(k)).toHaveLength(1)
  expect(k.w.toasts).toHaveLength(1)
  expect(k.w.toolSeen).toHaveLength(toolsSeen); expect(k.w.spawnSeen).toHaveLength(spawns)
  expect(await k.st('runs')).toEqual(expect.arrayContaining([expect.objectContaining({ agentId: 'A', status: 'running' })]))
})

// ---- 42 -------------------------------------------------------------------
each('A34 42 runaway context: 299999 silent, 300000 fires with current step count, no refire, mark stays', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await spawnAs(k, 'A')
  await k.step({ agentId: 'A', index: 0, usage: usage(OPUS, { i: 1000, r: 298999 }) })
  expect(runToasts(k)).toHaveLength(0)
  await k.step({ agentId: 'A', index: 1, usage: usage(OPUS, { i: 1000, r: 299000 }) })
  expect(runToasts(k)).toHaveLength(1)
  has(runToasts(k)[0], '2 steps · 300k ctx'); has(runToasts(k)[0], '"research sweep"')
  await k.step({ agentId: 'A', index: 2, usage: usage(OPUS, { i: 100_000 }) })
  expect(runToasts(k)).toHaveLength(1)
  has(await k.paneText('pets', s), '⚠ RUNAWAY')
})
each('A34 42 output tokens never count toward context', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await spawnAs(k, 'A')
  await k.step({ agentId: 'A', usage: usage(OPUS, { i: 10, o: 500_000 }) })
  expect(runToasts(k)).toHaveLength(0)
  lacks(await k.paneText('pets', s), 'RUNAWAY')
})
each('A34 42 ctx is the latest step, not a sum or peak', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await spawnAs(k, 'A')
  await k.step({ agentId: 'A', index: 0, usage: usage(OPUS, { r: 200_000 }) })
  await k.step({ agentId: 'A', index: 1, usage: usage(OPUS, { r: 200_000 }) })
  await k.step({ agentId: 'A', index: 2, usage: usage(OPUS, { c: 200_000 }) })
  expect(runToasts(k)).toHaveLength(0)
})

// ---- 43 -------------------------------------------------------------------
each('A34 43 agent B: steps then context = exactly two toasts in order; nothing after', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await spawnAs(k, 'B', 'agent b job')
  await k.steps('B', 100, SMALL)
  expect(runToasts(k)).toHaveLength(1)
  has(runToasts(k)[0], '100 steps')
  await k.step({ agentId: 'B', index: 100, usage: usage(OPUS, { r: 340_000 }) })
  expect(runToasts(k)).toHaveLength(2)
  has(runToasts(k)[1], '101 steps · 340k ctx')
  await k.steps('B', 200, usage(OPUS, { r: 340_000 }))
  expect(runToasts(k)).toHaveLength(2)
})
each('A34 43 agent C crossing both on one step: two toasts', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await spawnAs(k, 'C', 'agent c job')
  await k.steps('C', 99, SMALL)
  expect(runToasts(k)).toHaveLength(0)
  await k.step({ agentId: 'C', index: 99, usage: usage(OPUS, { r: 350_000 }) })
  expect(runToasts(k)).toHaveLength(2)
  for (const t of runToasts(k)) { has(t, '100 steps · 350k ctx'); has(t, '"agent c job"') }
})
each('A34 43 steps without agentId (main) never count or toast', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  for (let i = 0; i < 150; i++) await k.step({ index: i, usage: usage(OPUS, { r: 900_000 }) })
  expect(runToasts(k)).toHaveLength(0)
  lacks(await k.paneText('pets', s), 'RUNAWAY')
})

// ---- 44 -------------------------------------------------------------------
const fireSteps = async (k: Kit, id: string) => { await k.steps(id, 100, SMALL) }
each('A34 44 pet row mark: running+fired shows it, quiet or done does not', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await spawnAs(k, 'A'); await spawnAs(k, 'Q', 'quiet job')
  await fireSteps(k, 'A')
  if (s === 'terminal') {
    const ui0 = await k.mountPane('terminal', 'pets')
    const rows = rowsOf(await ui0.drawn()); await ui0.unmount()
    const row = rows.find((r) => r.includes('research sweep') && r.includes('running'))
    expect(row).toBeDefined()
    expect(squash(row!)).toMatch(/running \d\d:\d\d · ⚠ RUNAWAY — research sweep/)
    const quiet = rows.find((r) => r.includes('quiet job'))
    expect(quiet).toBeDefined(); expect(quiet).not.toContain('RUNAWAY')
  } else {
    const ui = await k.mountPane('desktop', 'pets')
    const tree = await ui.drawn()
    const a = svgs(tree).find((e) => String(e.props.alt).includes('research sweep'))
    const q = svgs(tree).find((e) => String(e.props.alt).includes('quiet job'))
    expect(a).toBeDefined(); expect(q).toBeDefined()
    expect(srcOf(a)).toContain('data-runaway="1"')
    expect(srcOf(q)).not.toContain('data-runaway')
    expect(squash(String(a.props.alt))).toMatch(/running \d\d:\d\d · ⚠ RUNAWAY — research sweep/)
    expect(String(q.props.alt)).not.toContain('RUNAWAY')
    await ui.unmount()
  }
  await k.complete('A', 'answer')
  const t = await k.paneText('pets', s)
  lacks(t, 'RUNAWAY')
  if (s === 'desktop') {
    const ui = await k.mountPane('desktop', 'pets')
    for (const e of svgs(await ui.drawn())) expect(srcOf(e)).not.toContain('data-runaway')
    await ui.unmount()
  }
})
test('A34 44 desktop alt equals the terminal row text', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await spawnAs(k, 'A'); await fireSteps(k, 'A')
  const grab = async (s: Surface) => {
    const ui = await k.mountPane(s, 'pets'); const tree = await ui.drawn(); await ui.unmount()
    if (s === 'terminal') return squash(rowsOf(tree).find((r) => r.includes('research sweep') && r.includes('running')) ?? '')
    return squash(String(svgs(tree).find((e) => String(e.props.alt).includes('research sweep'))?.props.alt ?? ''))
  }
  const term = await grab('terminal'); const desk = await grab('desktop')
  expect(term).toContain('⚠ RUNAWAY')
  expect(desk).toBe(term)
})

// ---- 45 -------------------------------------------------------------------
each('A34 45 band segment counts running flagged agents, hides at zero, row appears', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await spawnAs(k, 'A'); await spawnAs(k, 'B', 'second job')
  lacks(await k.bandText(s), 'RUNAWAY')
  await fireSteps(k, 'A')
  has(await k.bandText(s), '⚠ RUNAWAY ×1')
  await fireSteps(k, 'B')
  const t2 = await k.bandText(s)
  has(t2, '⚠ RUNAWAY ×2'); expect(t2).not.toBe(SENTINEL)
  await k.complete('A', 'answer')
  has(await k.bandText(s), '⚠ RUNAWAY ×1')
  await k.complete('B', 'answer')
  lacks(await k.bandText(s), 'RUNAWAY')
})
test('A34 45 terminal and desktop segment text are equal', async ($: any, on: any) => {
  const k = makeKit($, on); await k.start('terminal')
  await spawnAs(k, 'A'); await spawnAs(k, 'B', 'second job'); await fireSteps(k, 'A'); await fireSteps(k, 'B')
  const seg = async (s: Surface) => squash((await k.bandText(s)).match(/⚠ RUNAWAY ×\d+/)?.[0] ?? '')
  const t = await seg('terminal'); const d = await seg('desktop')
  expect(t).toBe('⚠ RUNAWAY ×2'); expect(d).toBe(t)
})

// ---- 46 -------------------------------------------------------------------
each('A34 46 runaway_maxSteps=0: 500 steps never fire the steps threshold', { options: { runaway_maxSteps: 0 } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await spawnAs(k, 'A')
  await k.steps('A', 500, SMALL)
  expect(runToasts(k)).toHaveLength(0)
  lacks(await k.paneText('pets', s), 'RUNAWAY')
})
each('A34 46 runaway_maxContext=50000 fires at 50000 and shows 50k ctx', { options: { runaway_maxContext: 50000 } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await spawnAs(k, 'A')
  await k.step({ agentId: 'A', index: 0, usage: usage(OPUS, { r: 49_999 }) })
  expect(runToasts(k)).toHaveLength(0)
  await k.step({ agentId: 'A', index: 1, usage: usage(OPUS, { r: 50_000 }) })
  expect(runToasts(k)).toHaveLength(1)
  has(runToasts(k)[0], '50k ctx')
})
each('A34 46 runaway_toast=false: no toast, row mark and band segment remain', { options: { runaway_toast: false } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await spawnAs(k, 'A')
  await fireSteps(k, 'A')
  expect(runToasts(k)).toHaveLength(0)
  has(await k.paneText('pets', s), '⚠ RUNAWAY')
  has(await k.bandText(s), '⚠ RUNAWAY ×1')
})
each('A34 46 usage:null steps count as steps, leave context unchanged, throw nothing', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await spawnAs(k, 'A')
  await k.step({ agentId: 'A', index: 0, usage: usage(OPUS, { r: 5000 }) })
  for (let i = 1; i < 99; i++) await k.step({ agentId: 'A', index: i }) // usage null
  expect(runToasts(k)).toHaveLength(0)
  await k.step({ agentId: 'A', index: 99 })
  expect(runToasts(k)).toHaveLength(1)
  has(runToasts(k)[0], '100 steps · 5k ctx')
})
each('A34 46 agentId with no run row: description "agent {first 8 chars}"', { options: { runaway_maxSteps: 3 } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await k.steps('abcdef1234', 3, SMALL)
  expect(runToasts(k)).toHaveLength(1)
  has(runToasts(k)[0], '"agent abcdef12"'); has(runToasts(k)[0], '3 steps')
})
each('A34 46 description in the runaway toast is clipped to 50 characters', { options: { runaway_maxSteps: 1 } }, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  const long = 'abcdefghij'.repeat(6)
  await spawnAs(k, 'A', long)
  await k.step({ agentId: 'A', usage: SMALL })
  expect(runToasts(k)).toHaveLength(1)
  expect(runToasts(k)[0]).not.toContain(long.slice(0, 51))
  expect(runToasts(k)[0]).toContain(long.slice(0, 40))
})

// ---- 47 -------------------------------------------------------------------
each('A34 47 performance: 200 subagent steps make no list/process/http/fs call, <= 4 agents state.set per step', {}, async ($, on, s) => {
  const k = makeKit($, on); await k.start(s)
  await spawnAs(k, 'A')
  const c0 = { ...k.w.cnt }, net = k.w.net, proc = k.w.proc
  let worst = 0
  for (let i = 0; i < 200; i++) {
    const before = k.w.cnt.set
    await k.step({ agentId: 'A', index: i, usage: SMALL })
    worst = Math.max(worst, k.w.cnt.set - before)
  }
  expect(k.w.cnt.list).toBe(c0.list); expect(k.w.cnt.fs).toBe(c0.fs)
  expect(k.w.net).toBe(net); expect(k.w.proc).toBe(proc)
  expect(worst).toBeLessThanOrEqual(4)
  expect(k.w.cnt.set - c0.set).toBeLessThanOrEqual(800)
})
