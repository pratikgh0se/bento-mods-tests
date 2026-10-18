/* eslint-disable @typescript-eslint/no-explicit-any */
// Shared helpers for the `usage` contract tests. Written from specs/usage.md section 8 only.
import { mock } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

declare const console: { error: (...a: unknown[]) => void }
export const SURFACES = ['terminal', 'desktop'] as const
export type Surface = (typeof SURFACES)[number]

export const MIN = 60_000
export const HOUR = 3_600_000
export const DAY = 86_400_000
// Local noon, so "today" vs "Ddd" formatting is stable in any timezone.
export const T0 = new Date(2026, 9, 12, 12, 0, 0).getTime()
export const SID = 'sid-usage-test'
export const SONNET = 'claude-sonnet-5-5'
export const CACHE_TAX_KEY = 'cache-tax@claude-code-mods'
export const CACHE_TAX_SETTINGS = { enabledPlugins: { [CACHE_TAX_KEY]: true } }

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const p2 = (n: number) => String(n).padStart(2, '0')

/** `{when}`: local HH:MM when the same local date as `nowMs`, else `Ddd HH:MM`. */
export function formatWhen(ms: number, nowMs: number = T0): string {
  const d = new Date(ms)
  const n = new Date(nowMs)
  const hhmm = `${p2(d.getHours())}:${p2(d.getMinutes())}`
  const same = d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate()
  return same ? hhmm : `${DAYS[d.getDay()]} ${hhmm}`
}
/** Candidates one minute either side (the contract allows 1 minute of slack). */
export function whenWithin1Min(ms: number, nowMs: number = T0): string[] {
  return [-MIN, 0, MIN].map(o => formatWhen(ms + o, nowMs))
}
export function localDate(ms: number): string {
  const d = new Date(ms)
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`
}

/** Plain text of a drawn tree. Svg contributes its `alt`, Button its label. */
export function textOf(node: unknown): string {
  if (node === null || node === undefined || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textOf).join('')
  const n = node as { type?: string; props?: Record<string, any>; children?: unknown }
  if (n.type === 'Svg') return String(n.props?.alt ?? '')
  if (n.type === 'Button') return String(n.props?.label ?? '')
  const raw = n.children ?? n.props?.children
  const kids = Array.isArray(raw) ? raw : raw === undefined || raw === null ? [] : [raw]
  const parts = kids.map(textOf)
  if (n.type === 'Text') return parts.join('')
  const col = n.props?.flexDirection === 'column' || n.props?.flexDirection === 'column-reverse'
  return parts.filter(p => p !== '').join(col ? '\n' : ' ')
}
export const norm = (s: string) => s.replace(/[ \t]+/g, ' ')
/** Terminal cell width, approximate: emoji and symbols above U+1F000 and a few dingbats count 2. */
export function cellWidth(line: string): number {
  let w = 0
  for (const ch of line) {
    const c = ch.codePointAt(0) ?? 0
    w += c >= 0x1f000 || c === 0x26d4 || c === 0x26a0 ? 2 : 1
  }
  return w
}

export type RL = { kind: string; percentUsed: number; resetsAt?: string }
export const rl = (kind: string, percentUsed: number, resetsAtMs?: number): RL => ({
  kind,
  percentUsed,
  ...(resetsAtMs === undefined ? {} : { resetsAt: new Date(resetsAtMs).toISOString() }),
})

export type Usage = { input_tokens: number; output_tokens: number; cache_read_input_tokens: number; cache_creation_input_tokens: number }
export const usage = (read = 0, creation = 0, input = 0, output = 0): Usage => ({
  input_tokens: input,
  output_tokens: output,
  cache_read_input_tokens: read,
  cache_creation_input_tokens: creation,
})

export type RigConfig = {
  settings?: Record<string, unknown>
  store?: Record<string, unknown>
  breakdown?: { autoCompactThreshold: number; isAutoCompactEnabled: boolean }
  startRateLimits?: RL[]
  surfaces?: string[] // `session.surfaces()` answer (default ['terminal'])
  beneathInner?: string // text of a sentinel tree drawn by a hook beneath the plugin on AbovePrompt
}

const SUMMARY = { role: 'user', text: 'summary', toolUses: [] }

/** Inline plugin: lets a test raise `model.fork` (an op, only callable from a plugin's `$`) via /zzfork. */
export const FORK_PLUGIN = {
  name: 'zzfork',
  register(on: any) {
    on('command.run', { command: 'zzfork' }, async ($: any) => {
      await $.model.fork({ prompt: 'keepwarm ping' })
      return { text: 'forked' }
    })
  },
}

/** Calls a `ui.render` hook may make (conventions 3.1a). `ui.render` itself is the bottom the chain ends in. */
export const RENDER_ALLOWED = new Set(['state.get', 'clock.now', 'ui.resolve', 'ui.render'])
export type RenderLog = { on: boolean; calls: string[] }
/** Wrap `on` so every bottom hook that answers while `log.on` is set is recorded by name (a `$` call made by the plugin). */
export function tapOn(on: any, log: RenderLog): any {
  const wrapped = (...args: any[]) => {
    const i = args.length - 1
    const name = typeof args[0] === 'string' ? args[0] : '?'
    const fn = args[i]
    if (typeof fn === 'function') {
      const kind = fn.constructor?.name
      const w: any =
        kind === 'AsyncGeneratorFunction'
          ? async function* (this: any, ...a: any[]) {
              if (log.on) log.calls.push(name)
              return yield* fn.apply(this, a)
            }
          : function (this: any, ...a: any[]) {
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
export const disallowedIn = (calls: string[]) => calls.filter(c => !RENDER_ALLOWED.has(c))

export function rig($: Engine, on0: On, cfg: RigConfig = {}) {
  const E = $ as any
  const renderLog: RenderLog = { on: false, calls: [] }
  const on = tapOn(on0, renderLog) as On
  const o = on as unknown as (...a: any[]) => void
  const clock = mock.clock(on, { now: T0 })
  const kv = new Map<string, unknown>(Object.entries(cfg.store ?? {}))

  const st = {
    rateLimits: (cfg.startRateLimits ?? []) as RL[],
    context: { window: 1_000_000 } as Record<string, unknown>,
    cost: undefined as undefined | { usd: number },
    settings: cfg.settings ?? {},
    breakdown: cfg.breakdown,
    stepUsage: usage(0, 0, 1000, 100) as Usage,
    stepModel: SONNET,
    forkUsage: usage(80000) as Usage,
    compact: { messages: [SUMMARY] } as Record<string, unknown>,
    beneathCommandCalls: 0,
    stepLog: [] as { at: number; agentId?: string }[],
    registered: [] as string[],
    toasts: [] as string[],
    turnIndex: 0,
    surfaces: (cfg.surfaces ?? ['terminal']) as string[],
    statusCalls: [] as (string | undefined)[],
    gate: undefined as undefined | Promise<void>,
    atomLog: [] as { plugin: string; key: string; value: unknown }[],
    renders: { pane: 0, band: 0 },
  }

  // Observe every atom write (state.set) without answering it, and every Pane draw.
  o('state.set', async (_$: unknown, e: any, next: any) => {
    st.atomLog.push({ plugin: e.plugin, key: e.key, value: e.value })
    return next(e)
  })
  o('ui.render', { component: 'Pane' }, async (_$: unknown, e: any, next: any) => {
    st.renders.pane += 1
    return next(e)
  })

  o('store.get', (_$: unknown, e: any) => ({ value: kv.get(e.key) }))
  o('store.set', (_$: unknown, e: any) => {
    kv.set(e.key, JSON.parse(JSON.stringify(e.value)))
    return { value: undefined }
  })
  o('store.delete', (_$: unknown, e: any) => {
    kv.delete(e.key)
    return { value: undefined }
  })
  o('store.keys', () => ({ value: [...kv.keys()] }))
  o('session.id', () => ({ value: SID }))
  o('session.model', () => ({ value: SONNET }))
  o('session.cwd', () => ({ value: '/tmp/usage-test' }))
  o('session.surface', () => ({ value: 'terminal' }))
  o('session.surfaces', () => ({ value: [...st.surfaces] }))
  o('session.turns', () => ({ value: 0 }))
  o('session.usage', (_$: unknown, e: any) => {
    const context: Record<string, unknown> = { ...st.context }
    if (e?.breakdown && st.breakdown) context.breakdown = { ...st.breakdown }
    return { value: { startedAt: T0, context, rateLimits: [...st.rateLimits], ...(st.cost ? { cost: st.cost } : {}) } }
  })
  o('settings.read', () => ({ value: st.settings }))
  o('session.start', (_$: unknown, e: any) => ({ cwd: e.cwd }))
  o('session.measure', (_$: unknown, e: any) => ({ changed: e.changed }))
  o('session.end', (_$: unknown, e: any) => ({ sessionId: e.sessionId }))
  o('session.compact', () => st.compact)
  o('turn.step', async function* (_$: unknown, e: any) {
    st.stepLog.push({ at: clock.now(), agentId: e.agentId })
    if (st.gate) await st.gate
    return {
      turnId: e.turnId,
      index: e.index,
      answer: '',
      toolUses: [],
      stopReason: 'end_turn',
      usage: { ...st.stepUsage, model: st.stepModel },
    }
  })
  o('model.fork', () => ({ value: { isAnswered: true, text: 'pong', usage: { ...st.forkUsage } } }))
  o('command.register', (_$: unknown, e: any) => {
    st.registered.push(e.name)
    return { value: undefined }
  })
  o('command.list', () => ({ value: [] }))
  o('command.run', () => {
    st.beneathCommandCalls += 1
    return { text: 'BENEATH-RESULT' }
  })
  o('ui.open', () => ({ value: { isPlaced: true } }))
  o('ui.close', () => ({ value: undefined }))
  o('ui.toast', (_$: unknown, e: any) => {
    st.toasts.push(e.text)
    return { value: undefined }
  })
  o('ui.status', (_$: unknown, e: any) => {
    st.statusCalls.push(e?.text)
    return { value: undefined }
  })
  o('turn.complete', (_$: unknown, e: any) => ({ text: String(e?.answer ?? '') }))
  o('ui.log', () => ({ value: undefined }))
  o('ui.panes', () => ({ value: [] }))
  o('classic.SessionStart', () => ({}))
  o('classic.PreModelSwitch', () => ({}))
  o('classic.PostModelSwitch', () => ({}))
  {
    // Bottom for AbovePrompt: nothing sits beneath the plugin in the kit, so always answer.
    const text = cfg.beneathInner ?? ''
    o('ui.render', { component: 'AbovePrompt' }, () => ({ type: 'Text', props: {}, children: [text] }))
  }

  const bandProps = (over: Record<string, unknown> = {}) => ({
    hasSurvey: false,
    isWorking: false,
    maxRows: 6,
    bodyColumns: 120,
    scroll: { offset: 0, bodyRows: 6 },
    view: {},
    ...over,
  })

  const api = {
    st,
    clock,
    renderLog,
    /** Mount a component, draw it, unmount; returns the tree text and every bottom call made while it drew. */
    async renderOnce(kind: 'band' | 'pane', surface: Surface): Promise<{ text: string; calls: string[] }> {
      renderLog.calls = []
      renderLog.on = true
      let text = ''
      let calls: string[] = []
      try {
        const ui =
          kind === 'band'
            ? await E.ui.mount({ plugin: 'usage', surface, component: 'AbovePrompt', props: bandProps(), viewport: { columns: 120, rows: 40 } })
            : await E.ui.mount({
                plugin: 'usage',
                surface,
                component: 'Pane',
                requestId: 'cache-clock',
                props: { title: 'Cache Clock', isFocused: true, bodyColumns: 100, placement: 'inline', scroll: { offset: 0, bodyRows: 30 }, view: {} },
                viewport: { columns: 110, rows: 40 },
              })
        text = norm(textOf(await ui.drawn()))
        calls = [...renderLog.calls]
        renderLog.on = false
        await ui.unmount()
      } finally {
        renderLog.on = false
      }
      return { text, calls }
    },
    advance: (ms: number) => clock.advance(ms),
    now: () => clock.now(),

    async start() {
      await E.session.start({ cwd: '/tmp/usage-test', surface: 'terminal', isInteractive: true })
      await clock.settle()
    },

    /** A `session.measure` with rate limits (and optionally context). */
    async measure(opts: { five?: [number, number?]; seven?: [number, number?]; spend?: [number, number?]; raw?: RL[]; context?: Record<string, unknown>; changed?: string[]; cost?: number }) {
      const list: RL[] = opts.raw ?? []
      if (opts.five) list.push(rl('five_hour', opts.five[0], opts.five[1]))
      if (opts.seven) list.push(rl('seven_day', opts.seven[0], opts.seven[1]))
      if (opts.spend) list.push(rl('spend_limit', opts.spend[0], opts.spend[1]))
      st.rateLimits = list
      if (opts.context) st.context = opts.context
      if (opts.cost !== undefined) st.cost = { usd: opts.cost }
      await E.session.measure({
        context: { ...st.context },
        rateLimits: [...list],
        ...(st.cost ? { cost: st.cost } : {}),
        changed: opts.changed ?? (opts.context ? ['context'] : ['rateLimits']),
      })
      await clock.settle()
    },

    async measureContext(tokens: number, window = 1_000_000) {
      st.context = { tokens, window, percent: Math.round((tokens / window) * 100) }
      await E.session.measure({
        context: { ...st.context },
        rateLimits: [...st.rateLimits],
        changed: ['context'],
      })
      await clock.settle()
    },

    /** A main-thread (or subagent when agentId given) turn.step at the current mocked time. */
    async step(opts: { usage?: Usage; model?: string; agentId?: string } = {}) {
      if (opts.usage) st.stepUsage = opts.usage
      if (opts.model) st.stepModel = opts.model
      const s = E.turn.step({
        turnId: 'turn-1',
        index: st.turnIndex++,
        model: st.stepModel,
        messageCount: 1,
        ...(opts.agentId ? { agentId: opts.agentId } : {}),
      })
      for await (const _chunk of s) {
        // drain
      }
      const r = await s.result
      await clock.settle()
      return r
    },

    /** Hold every turn.step open (before it returns) until the returned `release()` is called. */
    holdSteps(): () => void {
      let go!: () => void
      st.gate = new Promise<void>(res => {
        go = res
      })
      return () => {
        st.gate = undefined
        go()
      }
    },

    /** Start a turn.step without waiting for it; `done` resolves when it has finished. */
    startStep(opts: { agentId?: string; usage?: Usage } = {}): { done: Promise<unknown> } {
      if (opts.usage) st.stepUsage = opts.usage
      const s = E.turn.step({
        turnId: 'turn-1',
        index: st.turnIndex++,
        model: st.stepModel,
        messageCount: 1,
        ...(opts.agentId ? { agentId: opts.agentId } : {}),
      })
      const done = (async () => {
        for await (const _chunk of s) {
          // drain
        }
        return await s.result
      })()
      done.catch(() => undefined)
      return { done }
    },

    /** The end of a main-thread (or subagent) turn. */
    async complete(opts: { agentId?: string; usage?: Usage } = {}) {
      const r = await E.turn.complete({
        turnId: 'turn-1',
        answer: 'done',
        durationMs: 1000,
        isAborted: false,
        reason: 'answer',
        ...(opts.agentId ? { agentId: opts.agentId } : {}),
        ...(opts.usage ? { usage: { ...opts.usage, model: st.stepModel } } : {}),
      })
      await clock.settle()
      return r
    },

    /** Mount at a given width: bodyColumns and viewport columns are both `columns`. Returns the raw tree and its text. */
    async mountAt(kind: 'band' | 'pane', surface: Surface, columns: number): Promise<{ tree: any; text: string }> {
      const ui =
        kind === 'band'
          ? await E.ui.mount({ plugin: 'usage', surface, component: 'AbovePrompt', props: bandProps({ bodyColumns: columns }), viewport: { columns, rows: 40 } })
          : await E.ui.mount({
              plugin: 'usage',
              surface,
              component: 'Pane',
              requestId: 'cache-clock',
              props: { title: 'Cache Clock', isFocused: true, bodyColumns: columns, placement: 'inline', scroll: { offset: 0, bodyRows: 30 }, view: {} },
              viewport: { columns, rows: 40 },
            })
      try {
        const tree = await ui.drawn()
        return { tree, text: norm(textOf(tree)) }
      } finally {
        await ui.unmount()
      }
    },

    async fork(u?: Usage) {
      if (u) st.forkUsage = u
      const r = await E.command.run({ command: 'zzfork' })
      await clock.settle()
      return r
    },

    /** Atom writes so far (marker), and the writes since a marker. */
    atomMarker: () => st.atomLog.length,
    atomsSince: (marker: number, plugin = 'usage') => st.atomLog.slice(marker).filter(a => a.plugin === plugin),
    /** The last published value of the `usage` plugin's atom `key` (default `cache`). */
    atom: (key = 'cache', plugin = 'usage'): any => [...st.atomLog].reverse().find(a => a.plugin === plugin && a.key === key)?.value,

    /**
     * A RETAINED mount (usage round 2): mounted once and never re-mounted. The host re-draws it only when a
     * plugin invalidates (state write / tick); `text()` flushes pending work and reads the last draw, so
     * a stale draw stays stale. `draws` counts Pane draws seen by the host (0 where the harness cannot count).
     */
    async retained(kind: 'band' | 'pane', surface: Surface, columns: number) {
      const ui =
        kind === 'band'
          ? await E.ui.mount({ plugin: 'usage', surface, component: 'AbovePrompt', props: bandProps({ bodyColumns: columns }), viewport: { columns, rows: 40 } })
          : await E.ui.mount({
              plugin: 'usage',
              surface,
              component: 'Pane',
              requestId: 'cache-clock',
              props: { title: 'Cache Clock', isFocused: true, bodyColumns: columns, placement: 'inline', scroll: { offset: 0, bodyRows: 30 }, view: {} },
              viewport: { columns, rows: 40 },
            })
      return {
        async tree(): Promise<any> {
          await clock.settle()
          return ui.drawn()
        },
        async text(): Promise<string> {
          await clock.settle()
          return norm(textOf(await ui.drawn()))
        },
        get draws() {
          return kind === 'pane' ? st.renders.pane : st.renders.band
        },
        unmount: () => ui.unmount(),
      }
    },

    /** Raw session.compact with any trigger and any bottom answer (e.g. `{ skip: 'x' }`). */
    async compactRaw(trigger: string, result: Record<string, unknown>) {
      st.compact = result
      const r = await E.session.compact({ trigger, messages: [SUMMARY] })
      await clock.settle()
      return r
    },

    async compact(before?: number, after?: number) {
      st.compact = { messages: [SUMMARY], ...(before === undefined ? {} : { tokensBefore: before }), ...(after === undefined ? {} : { tokensAfter: after }) }
      const r = await E.session.compact({ trigger: 'manual', messages: [SUMMARY] })
      await clock.settle()
      return r
    },

    async command(command: string, args = '') {
      const r = await E.command.run({ command, args })
      await clock.settle()
      return r as { text?: string }
    },

    async classic(name: string, fields: Record<string, unknown>) {
      const r = await E.classic[name](fields)
      await clock.settle()
      return r
    },

    async flush() {
      await E.session.end({ reason: 'other', sessionId: SID, resume: {} })
      await clock.settle()
    },

    /** Empty the engine's backing Map, as if the store held nothing. */
    wipeStore() {
      for (const k of [...kv.keys()]) kv.delete(k)
    },
    storeSize: () => kv.size,

    async store(key: string): Promise<any> {
      return kv.get(key)
    },

    /** Text of the AbovePrompt band as drawn on a surface. */
    async band(surface: Surface, over: Record<string, unknown> = {}): Promise<string> {
      // When the plugin draws nothing and nothing sits beneath, the engine may draw an
      // empty/engine element: treat a failed read as empty text.
      try {
        const ui = await E.ui.mount({
          plugin: 'usage',
          surface,
          component: 'AbovePrompt',
          props: bandProps(over),
          viewport: { columns: 120, rows: 40 },
        })
        const text = norm(textOf(await ui.drawn()))
        await ui.unmount()
        return text
      } catch (err) {
        console.error('band() mount failed:', err)
        return ''
      }
    },

    async bandTree(surface: Surface, over: Record<string, unknown> = {}): Promise<unknown> {
      const ui = await E.ui.mount({
        plugin: 'usage',
        surface,
        component: 'AbovePrompt',
        props: bandProps(over),
        viewport: { columns: 120, rows: 40 },
      })
      const tree = await ui.drawn()
      await ui.unmount()
      return tree
    },

    /** Text of the `cache-clock` pane on a surface. */
    async pane(surface: Surface): Promise<string> {
      try {
      const ui = await E.ui.mount({
        plugin: 'usage',
        surface,
        component: 'Pane',
        requestId: 'cache-clock',
        props: {
          title: 'Cache Clock',
          isFocused: true,
          bodyColumns: 100,
          placement: 'inline',
          scroll: { offset: 0, bodyRows: 30 },
          view: {},
        },
        viewport: { columns: 110, rows: 40 },
      })
      const text = norm(textOf(await ui.drawn()))
      await ui.unmount()
      return text
      } catch (err) {
        console.error('pane() mount failed:', err)
        return ''
      }
    },
  }
  return api
}

export const lineWith = (text: string, needle: string): string => text.split('\n').find(l => l.includes(needle)) ?? ''
export const countOf = (s: string, ch: string): number => [...s].filter(c => c === ch).length

/** Length of the sample list inside a stored `{v:1,...}` value (array, or its first array property). */
export function samplesLen(v: unknown): number {
  if (Array.isArray(v)) return v.length
  if (v && typeof v === 'object') {
    for (const x of Object.values(v as Record<string, unknown>)) if (Array.isArray(x)) return x.length
  }
  return -1
}

/** pricesJson override: one row per family, tuple [family,input,output,cacheRead,write5m,write1h,asOf?]. */
export const PRICES_SONNET = JSON.stringify([['sonnet', 3, 15, 0.3, 3.75, 6, '2026-10-01']])

/** Every node of a drawn tree, depth first. */
export function walk(node: any, out: any[] = []): any[] {
  if (node === null || node === undefined || typeof node !== 'object') return out
  if (Array.isArray(node)) {
    for (const n of node) walk(n, out)
    return out
  }
  out.push(node)
  const raw = node.children ?? node.props?.children
  const kids = Array.isArray(raw) ? raw : raw === undefined || raw === null ? [] : [raw]
  for (const k of kids) walk(k, out)
  return out
}
export const textNodes = (tree: unknown): any[] => walk(tree).filter(n => n.type === 'Text')
