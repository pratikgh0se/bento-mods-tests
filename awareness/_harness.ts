// Shared helpers for the awareness contract tests. Written from specs/awareness.md
// section 9 and specs/00-conventions.md only (code-blind). Not a test file.
import { mock, expect } from 'claude-code/testing'
import type { Engine, MockClock, TestBody } from 'claude-code/testing'

type On = Parameters<TestBody>[1]
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

export const PLUGIN = 'awareness'
/** Fixed mocked epoch (2026-10-12 09:00:00 UTC). */
export const T0 = Date.UTC(2026, 9, 12, 9, 0, 0)
/** Virtual temp dir: nothing here is ever touched on a real disk (fs.* is answered from memory). */
export const TMP = '/tmp/awareness-test'
export const REPO = `${TMP}/repo`
export const VAULT = `${TMP}/vault`
export const SURFACES = ['terminal', 'desktop'] as const
export type Surface = (typeof SURFACES)[number]

export type ToolOpts = {
  agentId?: string
  /** What the engine (bottom) answers as `result`. */
  result?: unknown
  readOnly?: boolean
  /** Mocked-clock ms the tool "runs" before answering. */
  delayMs?: number
  text?: string
  /** Extra fields merged into the tool call input (e.g. run_in_background). */
  input?: Record<string, unknown>
  /** After `delayMs`, the engine rejects the call with this message (interrupt / abort). */
  reject?: string
  /** The engine never answers this call (the result never arrives). */
  hang?: boolean
}

export type WorldOpts = {
  surfaces?: Surface[]
  store?: Record<string, unknown>
  env?: Record<string, string>
  commands?: string[]
  /** Raise session.start in world() (default true). */
  start?: boolean
  /** Hook answering ui.render beneath the plugin (the "inner" tree). */
  inner?: Any
  /**
   * Stale-frame mode: a `$` call (state / ui ops) made by a hook after its `tool.call` `next(e)` resolved
   * rejects, as the real host does once the dispatch has ended or was abandoned, when that tool call took
   * more than this many mocked seconds. The rejection lasts until the plugin's chain for that call settles.
   */
  staleAfterSec?: number
  /**
   * What the host does with plugin-state writes (`state.set`) made while a `turn.step` stream is being consumed
   * (from streamStep() creation until end(), or for the duration of step()):
   * 'apply' (default) applies them; 'drop' silently discards them (as the real host does for the streaming frame);
   * 'defer' holds them and applies them only when that dispatch ends. Reads (`state.get`) see only applied writes.
   */
  streamWrites?: 'apply' | 'drop' | 'defer'
  /** The engine's own AbovePrompt (beneath every plugin) takes this many mocked ms to answer: a slow hook in the chain. */
  slowRenderMs?: number
}

/** Calls a `ui.render` hook may make (conventions 3.1a). `ui.render` is the bottom the chain ends in. */
export const RENDER_ALLOWED = new Set(['state.get', 'clock.now', 'ui.resolve', 'ui.render'])
export type RenderLog = { on: boolean; calls: string[]; trace: string[] }
/** Wrap `on` so that every bottom hook answering while `log.on` is set is recorded by name (= a `$` call made by the plugin). */
export function tapOn(on: Any, log: RenderLog): Any {
  const wrapped = (...args: Any[]): Any => {
    const i = args.length - 1
    const name = typeof args[0] === 'string' ? args[0] : '?'
    const fn = args[i]
    if (typeof fn === 'function') {
      const kind = fn.constructor?.name
      const w: Any =
        kind === 'AsyncGeneratorFunction'
          ? async function* (this: Any, ...a: Any[]) {
              if (log.on) log.calls.push(name)
              return yield* fn.apply(this, a)
            }
          : function (this: Any, ...a: Any[]) {
              if (log.on) log.calls.push(name)
              return fn.apply(this, a)
            }
      Object.defineProperty(w, 'length', { value: fn.length })
      args[i] = w
    }
    return on(...args)
  }
  return Object.assign(wrapped, on)
}
export const disallowedIn = (calls: string[]): string[] => calls.filter((c) => !RENDER_ALLOWED.has(c))

export const norm = (s: string): string => s.replace(/\s+/g, ' ').trim()

/** Plain text of a drawn tree: strings, Svg `alt`, Button `label`. */
export function textOf(node: Any): string {
  if (node === null || node === undefined || node === false || node === true) return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textOf).filter(Boolean).join(' ')
  if (typeof node === 'object') {
    const props = node.props ?? {}
    if (node.type === 'Svg') return String(props.alt ?? '')
    const parts: string[] = []
    if (typeof props.label === 'string') parts.push(props.label)
    const kids = node.children ?? props.children
    if (kids !== undefined) parts.push(textOf(kids))
    else if (typeof props.text === 'string') parts.push(props.text)
    return parts.filter(Boolean).join(' ')
  }
  return ''
}

export async function drain(stream: Any): Promise<void> {
  if (stream && typeof stream[Symbol.asyncIterator] === 'function') {
    for await (const _chunk of stream) void _chunk
  } else {
    await stream
  }
}

export type World = Awaited<ReturnType<typeof world>>

export async function world($: Engine, on: On, o: WorldOpts = {}) {
  const E = $ as Any
  const renderLog: RenderLog = { on: false, calls: [], trace: [] }
  on = tapOn(on, renderLog)
  const h = (name: string, fn: (...a: Any[]) => Any): void => { (on as Any)(name, fn) }
  const surfaces: Surface[] = o.surfaces ?? ['terminal', 'desktop']
  const clock: MockClock = mock.clock(on, { now: T0 })
  mock.store(on, o.store ?? {})
  mock.env(on, o.env ?? {})

  const toasts: { text: string; timeoutMs?: number; at: number }[] = []
  const notifies: { text: string; title?: string; at: number }[] = []
  const audio: Any[] = []
  const statuses: (string | undefined)[] = []
  const registeredTools: Any[] = []
  const registeredCommands: string[] = []
  const files = new Map<string, { text: string; mtimeMs: number }>()
  const dirs = new Set<string>([TMP, REPO])
  const seen: Record<string, Any[]> = {}
  const rec = (k: string, e: Any): void => { (seen[k] ??= []).push(e) }
  const states = new Map<string, Any>()
  const pending = new Map<string, ToolOpts>()
  let toolSeq = 0
  const w = {
    $, E, on, clock, surfaces, toasts, notifies, audio, statuses, registeredTools, registeredCommands, files, dirs, seen,
    commands: o.commands ?? [] as string[],
    http: { calls: 0, up: true },
    curl: { calls: 0 },
    nextStep: undefined as Any,
    streamer: undefined as Any,
    staleIds: new Set<string>(),
    staleHits: 0,
    inStream: 0,
    deferred: [] as Any[],
    stepIndex: 0,
    turnSeq: 0,
  }
  const abs = (p: string): string => (p.startsWith('/') ? p : `${REPO}/${p}`)

  // ---- bottom (engine) hooks for ops the plugin may call ----
  const stale = (): void => { if (w.staleIds.size > 0) { w.staleHits++; throw new Error('dispatch ended: $ call from an abandoned hook frame') } }
  h('ui.toast', (_$: Any, e: Any) => { stale(); toasts.push({ text: e.text, timeoutMs: e.timeoutMs, at: clock.now() }); return { value: undefined } })
  h('ui.notify', (_$: Any, e: Any) => { stale(); notifies.push({ text: e.text, title: e.title, at: clock.now() }); return { value: { isSent: true } } })
  h('audio.play', (_$: Any, e: Any) => { stale(); audio.push(e); return { value: undefined } })
  h('ui.status', (_$: Any, e: Any) => { stale(); statuses.push(e.text); return { value: undefined } })
  for (const n of ['ui.log', 'ui.invalidate', 'ui.close', 'ui.notice']) h(n, () => { if (n === 'ui.invalidate') stale(); return { value: undefined } })
  h('ui.open', () => ({ value: { isOpen: true } }))
  h('tool.register', (_$: Any, e: Any) => { registeredTools.push(e); return { value: { tool: e.name } } })
  h('command.register', (_$: Any, e: Any) => { registeredCommands.push(e.name); return { value: { command: e.name } } })
  h('command.list', () => ({ value: w.commands.map((name) => ({ name, description: '' })) }))
  h('agent.list', () => ({ value: [] }))
  h('session.surfaces', () => ({ value: surfaces }))
  h('session.cwd', () => ({ value: REPO }))
  h('session.root', () => ({ value: REPO }))
  h('session.id', () => ({ value: 'sess-1' }))
  h('session.model', () => ({ value: 'claude-opus-5-5' }))
  h('session.turns', () => ({ value: 0 }))
  h('fs.read', (_$: Any, e: Any) => { const f = files.get(abs(e.path)); return f ? { value: f.text } : { deny: 'ENOENT' } })
  h('fs.exists', (_$: Any, e: Any) => ({ value: files.has(abs(e.path)) || dirs.has(abs(e.path)) }))
  h('fs.stat', (_$: Any, e: Any) => {
    const p = abs(e.path)
    const f = files.get(p)
    if (f) return { value: { kind: 'file', size: f.text.length, mtimeMs: f.mtimeMs, isLink: false } }
    if (dirs.has(p)) return { value: { kind: 'dir', size: 0, mtimeMs: T0, isLink: false } }
    return { deny: 'ENOENT' }
  })
  h('http.fetch', (_$: Any, _e: Any) => {
    w.http.calls++
    return w.http.up ? { value: { status: 200, ok: true, headers: {}, text: '{"version":"0.0.0"}' } } : { deny: 'ECONNREFUSED' }
  })
  h('process.run', (_$: Any, e: Any) => {
    const argv: string[] = e.argv ?? []
    if (argv[0] === 'curl') {
      w.curl.calls++
      return w.http.up
        ? { value: { exitCode: 0, stdout: '200', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
        : { value: { exitCode: 7, stdout: '000', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    }
    return { value: { exitCode: 0, stdout: 'git version 2.0.0', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })

  // ---- bottom hooks for events the test raises ----
  h('session.start', (_$: Any, e: Any) => { rec('session.start', e); return { cwd: e.cwd } })
  h('session.measure', (_$: Any, e: Any) => { rec('session.measure', e); return { changed: e.changed } })
  h('turn.start', (_$: Any, e: Any) => { rec('turn.start', e); return { turnId: e.turnId } })
  h('turn.complete', (_$: Any, e: Any) => { rec('turn.complete', e); return { text: '' } })
  h('prompt.submit', (_$: Any, e: Any) => { rec('prompt.submit', e); return { text: e.text } })
  h('command.run', (_$: Any, e: Any) => { rec('command.run', e); return {} })
  h('agent.spawn', (_$: Any, e: Any) => { rec('agent.spawn', e); return { model: e.model ?? 'sonnet' } })
  h('session.compact', (_$: Any, e: Any) => { rec('session.compact', e); return { messages: e.messages ?? [] } })
  h('session.end', (_$: Any, e: Any) => { rec('session.end', e); return { sessionId: e.sessionId ?? 'sess-1' } })
  h('tool.call', async (_$: Any, e: Any) => {
    rec('tool.call', e)
    const t: ToolOpts = pending.get(e.tool_use_id) ?? {}
    const started = clock.now()
    if (t.delayMs) await clock.sleep(t.delayMs)
    if (t.hang) await new Promise<void>(() => {})
    if (t.reject !== undefined) throw new Error(t.reject)
    if (o.staleAfterSec !== undefined && clock.now() - started > o.staleAfterSec * 1000) w.staleIds.add(e.tool_use_id)
    const result = t.result ?? (e.tool === 'Bash' ? { stdout: '', stderr: '', interrupted: false } : {})
    return { result, isReadOnly: t.readOnly ? true : undefined, text: t.text }
  })
  h('turn.step', async function* (_$: Any, e: Any) {
    rec('turn.step', e)
    const s = w.streamer
    if (s && s.agentId === e.agentId) {
      w.streamer = undefined
      for (;;) {
        while (s.queue.length === 0) await new Promise<void>((r) => { s.wake = r })
        const it = s.queue.shift()
        if (it.end) return it.result
        yield it.chunk
      }
    }
    return w.nextStep ?? { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: 'tool_use', usage: null }
  })
  h('ui.render', async () => {
    if (renderLog.on) renderLog.trace.push('bottom-start')
    if (o.slowRenderMs) await clock.sleep(o.slowRenderMs)
    if (renderLog.on) renderLog.trace.push('bottom-end')
    return o.inner !== undefined ? o.inner : { type: 'engine', ref: 0 }
  })
  // stale-frame mode: `state.get` is guarded here; ui.toast/notify/audio.play/status/invalidate and state.set call stale() above
  h('state.get', (_$: Any, e: Any, next: Any) => { stale(); if (renderLog.on) renderLog.trace.push(`state.get:${e.plugin}.${e.key}`); return next(e) })
  // record plugin state writes passing through (the kit's bottom keeps the store of state)
  h('state.set', (_$: Any, e: Any, next: Any) => {
    stale()
    if (w.inStream > 0 && o.streamWrites === 'drop') return { value: { isSet: false, version: 0 } }
    if (w.inStream > 0 && o.streamWrites === 'defer') { w.deferred.push({ e, next }); return { value: { isSet: true, version: 0 } } }
    states.set(`${e.plugin}.${e.key}`, e.value)
    return next(e)
  })
  const flushDeferred = async (): Promise<void> => {
    if (w.inStream > 0) return
    const q = w.deferred.splice(0)
    for (const { e, next } of q) { states.set(`${e.plugin}.${e.key}`, e.value); await next(e) }
  }

  // ---- helpers ----
  const api = {
    abs,
    renderLog,
    /** Mount the band, draw it, unmount; returns its text and every bottom call the plugin made while it drew. */
    async renderOnce(surface: Surface, props: Record<string, unknown> = {}): Promise<{ text: string; calls: string[]; trace: string[] }> {
      renderLog.calls = []
      renderLog.trace = []
      renderLog.on = true
      try {
        const ui = await E.ui.mount({
          plugin: PLUGIN, surface, component: 'AbovePrompt',
          props: { hasSurvey: false, isWorking: true, maxRows: 6, bodyColumns: 160, scroll: {}, view: {}, ...props },
        })
        const text = norm(textOf(await ui.drawn()))
        const calls = [...renderLog.calls]
        const trace = [...renderLog.trace]
        renderLog.on = false
        await ui.unmount()
        return { text, calls, trace }
      } finally {
        renderLog.on = false
      }
    },
    /** Put a file in the in-memory fs (path under the virtual temp dir). */
    putFile(path: string, text: string): void {
      const p = abs(path)
      files.set(p, { text, mtimeMs: clock.now() })
      for (let d = p.slice(0, p.lastIndexOf('/')); d.length > 1; d = d.slice(0, d.lastIndexOf('/'))) dirs.add(d)
    },
    async start(): Promise<void> {
      await E.session.start({ cwd: REPO, surface: surfaces[0] ?? 'terminal', isInteractive: true })
      await clock.settle()
    },
    async elapse(sec: number): Promise<void> { await clock.advance(sec * 1000) },
    secs(): number { return (clock.now() - T0) / 1000 },
    toastTexts(): string[] { return toasts.map((t) => t.text) },
    toastsLike(re: RegExp | string): { text: string; at: number }[] {
      return toasts.filter((t) => (typeof re === 'string' ? t.text.includes(re) : re.test(t.text)))
    },
    async state(key: string): Promise<Any> {
      await clock.settle()
      return states.get(`${PLUGIN}.${key}`) ?? {}
    },
    async submit(text = 'hello'): Promise<void> {
      await E.prompt.submit({ text, wait: false, origin: { kind: 'user' } })
      await clock.settle()
    },
    async turnStart(): Promise<string> {
      const turnId = `turn-${++w.turnSeq}`
      await E.turn.start({ text: 'go', turnId })
      await clock.settle()
      return turnId
    },
    async turnComplete(turnId = `turn-${w.turnSeq}`): Promise<void> {
      // all required TurnCompleteFields (answer, durationMs, isAborted) as the real host sends them
      await E.turn.complete({ turnId, reason: 'answer', answer: '', durationMs: 1000, isAborted: false })
      await clock.settle()
    },
    /** A main (or subagent) model request of the turn. */
    async step(o2: { answer?: string; toolUses?: Any[]; usage?: Any; agentId?: string; model?: string } = {}): Promise<Any> {
      w.nextStep = {
        turnId: `turn-${w.turnSeq}`, index: w.stepIndex, answer: o2.answer ?? '', toolUses: o2.toolUses ?? [],
        stopReason: (o2.toolUses?.length ?? 0) > 0 ? 'tool_use' : 'end_turn', usage: o2.usage ?? null,
      }
      const input: Any = { turnId: `turn-${w.turnSeq}`, index: w.stepIndex++, model: o2.model ?? 'claude-opus-5-5', messageCount: 1 }
      if (o2.agentId) input.agentId = o2.agentId
      w.inStream++
      const s = E.turn.step(input)
      try { await drain(s) } finally { w.inStream-- }
      await flushDeferred()
      await clock.settle()
    },
    /**
     * A streamable main (or subagent) model request: chunks are delivered one at a time so the test can read
     * the band between them. Usage: const st = w.streamStep(); await st.text('Hi'); ...; await st.end().
     */
    streamStep(o2: { agentId?: string; model?: string; answer?: string; toolUses?: Any[] } = {}) {
      const turnId = `turn-${w.turnSeq}`
      const index = w.stepIndex++
      const q = { agentId: o2.agentId, queue: [] as Any[], wake: undefined as Any }
      w.streamer = q
      w.inStream++
      let received = 0
      let sent = 0
      const input: Any = { turnId, index, model: o2.model ?? 'claude-opus-5-5', messageCount: 1 }
      if (o2.agentId) input.agentId = o2.agentId
      const done = (async () => {
        const stream = E.turn.step(input)
        for await (const _c of stream) { void _c; received++ }
      })()
      done.catch(() => {})
      const push = (it: Any): void => { q.queue.push(it); const wk = q.wake; q.wake = undefined; if (wk) wk() }
      const st = {
        async chunk(chunk: Any): Promise<void> {
          sent++
          push({ chunk })
          for (let i = 0; i < 200 && received < sent; i++) await clock.settle()
          await clock.settle()
        },
        text(text: string, idx = 0): Promise<void> { return st.chunk({ kind: 'text', index: idx, text }) },
        /** A tool call starting in block `idx` (tool chunk + its arguments as one input chunk). */
        async tool(name: string, input2: Record<string, unknown> = {}, idx = 1): Promise<void> {
          await st.chunk({ kind: 'tool', index: idx, id: `tu-s${idx}-${index}`, name })
          await st.chunk({ kind: 'input', index: idx, json: JSON.stringify(input2) })
        },
        async end(): Promise<void> {
          const toolUses = o2.toolUses ?? []
          sent++
          push({ chunk: { kind: 'stop', stopReason: toolUses.length ? 'tool_use' : 'end_turn', usage: null } })
          push({ end: true, result: { turnId, index, answer: o2.answer ?? '', toolUses, stopReason: toolUses.length ? 'tool_use' : 'end_turn', usage: null } })
          try { await done } finally { w.inStream-- }
          await flushDeferred()
          await clock.settle()
        },
      }
      return st
    },
    async measure(m: { percent?: number; tokens?: number; window?: number; rateLimits?: Any[] } = {}): Promise<void> {
      const context: Any = { window: m.window ?? 200000 }
      if (m.percent !== undefined) context.percent = m.percent
      if (m.tokens !== undefined) context.tokens = m.tokens
      await E.session.measure({ context, rateLimits: m.rateLimits ?? [], changed: ['context', 'rateLimits'] })
      await clock.settle()
    },
    rate(kind: 'seven_day' | 'five_hour', percentUsed: number, resetsInMs: number): Any {
      return { kind, percentUsed, resetsAt: new Date(clock.now() + resetsInMs).toISOString() }
    },
    /** Weekly HOT: seven_day 71% used, resets in 3 days (projected ~124%). */
    async hotWeekly(): Promise<void> {
      await api.measure({ percent: 10, tokens: 20000, rateLimits: [api.rate('seven_day', 71, 3 * 864e5)] })
    },
    /** Raise a tool call as the engine does; resolves with the chain's result. */
    async call(tool: string, input: Record<string, unknown>, t: ToolOpts = {}): Promise<Any> {
      const id = `tu-${++toolSeq}`
      pending.set(id, t)
      const args: Any = { tool, tool_use_id: id, ...input, ...(t.input ?? {}) }
      if (t.agentId) args.agentId = t.agentId
      let res: Any
      try { res = await E.tool.call(args) } finally { w.staleIds.delete(id) }
      // Real host rule: a plugin-registered tool (mcp__<plugin>__<name>) must answer string | array | undefined.
      if (tool.startsWith('mcp__')) {
        const r = res?.result
        if (r !== undefined && typeof r !== 'string' && !Array.isArray(r)) {
          throw new Error(`tool.call step resolved ${tool} with a result that does not match its output shape ... invalid_union (expected string | array | undefined, received ${r === null ? 'null' : typeof r})`)
        }
      }
      return res
    },
    bash(command: string, t: ToolOpts = {}): Promise<Any> { return api.call('Bash', { command }, t) },
    async bigOutput(bytes: number, t: ToolOpts = {}): Promise<Any> {
      return api.bash('cat big.log', { ...t, result: { stdout: '', stderr: '', interrupted: false, persistedOutputSize: bytes } })
    },
    async cmd(command: string, args = ''): Promise<string> {
      const r = await E.command.run({ command, args, origin: { kind: 'user' }, presentation: 'text' })
      await clock.settle()
      return String(r?.text ?? '')
    },
    async spawnAgent(a: { description?: string; subagentType?: string; model?: string } = {}): Promise<void> {
      await E.agent.spawn({
        tool_use_id: `ag-${++toolSeq}`, prompt: 'do it', description: a.description ?? 'Review the diff',
        subagentType: a.subagentType ?? 'general-purpose', provider: { plugin: 'x', tier: 'user' },
        parentModel: 'claude-opus-5-5', ...(a.model ? { model: a.model } : {}),
      })
      await clock.settle()
    },
    /** Mount the AbovePrompt band on one surface and return its normalised text ('' when nothing is drawn). */
    async band(surface: Surface, props: Record<string, unknown> = {}, strict = true): Promise<string> {
      try {
        const ui = await E.ui.mount({
          plugin: PLUGIN, surface, component: 'AbovePrompt',
          props: { hasSurvey: false, isWorking: true, maxRows: 6, bodyColumns: 160, scroll: {}, view: {}, ...props },
        })
        const drawn: Any = await ui.drawn()
        let t = norm(textOf(drawn))
        if (t === '') {
          // fallback: every string reachable under alt/label/text/children (shape-agnostic)
          const parts: string[] = []
          const walk = (n: Any, key = ''): void => {
            if (typeof n === 'string') { if (['alt', 'label', 'text', 'children', ''].includes(key) || /^\d+$/.test(key)) parts.push(n); return }
            if (Array.isArray(n)) { n.forEach((x) => walk(x, key)); return }
            if (n && typeof n === 'object') for (const [k, v] of Object.entries(n)) walk(v, k)
          }
          walk(drawn)
          t = norm(parts.join(' '))
        }
        await ui.unmount()
        return t
      } catch (err) {
        if (strict) throw err
        return ''
      }
    },
    /** Band text on both surfaces; asserts the two are equal (conventions 10.2) and returns it. */
    async bandBoth(props: Record<string, unknown> = {}): Promise<string> {
      const terminal = await api.band('terminal', props)
      const desktop = await api.band('desktop', props)
      expect(desktop, 'desktop text must equal terminal text').toBe(terminal)
      return terminal
    },
  }
  Object.assign(w, api)
  const full = w as typeof w & typeof api
  if (o.start !== false) await full.start()
  return full
}

/** A stand-in `dev` plugin that owns the peer atom `dev.toast`. Run `/devfake <ms-ago>` to publish lastShownAt. */
export const fakeDev = {
  name: 'dev',
  register: ((on: Any) => {
    on('command.run', async ($: Any, e: Any, next: Any) => {
      if (e.command !== 'devfake') return next(e)
      const ago = Number(e.args)
      const now = await $.clock.now()
      await $.state.set({ plugin: 'dev', key: 'toast' }, { lastShownAt: now - ago })
      return { text: 'ok' }
    })
  }) as Any,
}
