// Shared test harness for the `dev` plugin contract tests.
// Code-blind: written from specs/dev.md section 13 and specs/00-conventions.md only.
//
// What it does:
//  * registers the "engine bottom" hooks (process.run, fs.*, session.*, ui.*, command.*,
//    tool.call, state.get for peers) that every test needs, with permissive defaults;
//  * records every process call, toast, status line, pane open and command registration;
//  * offers builders for realistic git / gh / lsof / test-runner output.
//
// Everything is typed loosely on purpose (`Any`): the plugin under test does not exist yet and
// the testing typings are generic over events; the assertions are what matter.

import { expect, mock } from 'claude-code/testing'
import type { MockClock } from 'claude-code/testing'
import type { On } from 'claude-code'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Any = any

export const SURFACES = ['terminal', 'desktop'] as const
export type Surface = (typeof SURFACES)[number]

/** 2026-10-12 14:00:00 UTC. */
export const T0 = Date.UTC(2026, 9, 12, 14, 0, 0)
export const TOP = '/work/repo'
export const SESSION_ID = 'abcd1234-ef56-7890-abcd-ef1234567890'

// ---------------------------------------------------------------- text helpers

/** Plain text of a described tree: strings, Svg alt, Button label, Link label/href. */
export function textOf(node: unknown): string {
  if (node === null || node === undefined || node === false || node === true) return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textOf).join(' ')
  const n = node as { type?: string; props?: Record<string, unknown>; children?: unknown[] }
  const p = n.props ?? {}
  const kids = (n.children ?? (p.children as unknown[] | undefined) ?? []) as unknown[]
  const kidsArr = Array.isArray(kids) ? kids : [kids]
  switch (n.type) {
    case 'Svg':
      return String(p.alt ?? '')
    case 'Button':
      return `${String(p.label ?? '')}${kidsArr.map(textOf).join('')}`
    case 'Link': {
      const inner = kidsArr.map(textOf).join('')
      return inner !== '' ? inner : String(p.label ?? p.href ?? '')
    }
    case 'Input':
      return String(p.value ?? '')
    case 'Markdown':
      return String(p.text ?? p.source ?? kidsArr.map(textOf).join(''))
    case 'Code':
      return String(p.source ?? p.text ?? kidsArr.map(textOf).join(''))
    case 'Box':
      return kidsArr.map(textOf).filter(s => s !== '').join(' ')
    default:
      return kidsArr.map(textOf).join('')
  }
}

/** Collapse whitespace so `a  b` and `a b` compare equal. */
export const norm = (s: string): string => s.replace(/\s+/g, ' ').trim()

/** Kept for call sites; equality of terminal and desktop band text is now asserted inside `band()` itself. */
export function crossCheck(_key: string, _surface: Surface, _text: string): void {}

export const base = (s: string | undefined): string => (s ?? '').split('/').pop() ?? ''

// ---------------------------------------------------------------- fixture builders

const H = '1111111111111111111111111111111111111111'

/** `git status --porcelain=v2 --branch -z --untracked-files=normal` output (NUL separated). */
export function porcelain(o: {
  head?: string
  detached?: boolean
  oid?: string
  upstream?: string
  ab?: [number, number]
  staged?: number
  unstaged?: number
  untracked?: number
  conflicts?: number
} = {}): string {
  const out: string[] = []
  out.push(`# branch.oid ${o.oid ?? 'abc1234def5678abc1234def5678abc1234def56'}`)
  out.push(`# branch.head ${o.detached ? '(detached)' : (o.head ?? 'main')}`)
  if (o.upstream !== undefined) out.push(`# branch.upstream ${o.upstream}`)
  if (o.ab !== undefined) out.push(`# branch.ab +${o.ab[0]} -${o.ab[1]}`)
  for (let i = 0; i < (o.staged ?? 0); i++) out.push(`1 M. N... 100644 100644 100644 ${H} ${H} src/staged${i}.ts`)
  for (let i = 0; i < (o.unstaged ?? 0); i++) out.push(`1 .M N... 100644 100644 100644 ${H} ${H} src/unstaged${i}.ts`)
  for (let i = 0; i < (o.conflicts ?? 0); i++) out.push(`u UU N... 100644 100644 100644 100644 ${H} ${H} ${H} src/conflict${i}.ts`)
  for (let i = 0; i < (o.untracked ?? 0); i++) out.push(`? notes${i}.txt`)
  return out.join('\0') + '\0'
}

/** `git worktree list --porcelain` output. */
export function worktrees(list: { path: string; branch?: string; head?: string }[]): string {
  return (
    list
      .map(w =>
        [`worktree ${w.path}`, `HEAD ${w.head ?? H}`, w.branch !== undefined ? `branch refs/heads/${w.branch}` : 'detached'].join('\n'),
      )
      .join('\n\n') + '\n\n'
  )
}

export type PrIn = {
  number: number
  title?: string
  author?: string
  branch: string
  state?: 'OPEN' | 'MERGED' | 'CLOSED'
  checks?: 'pass' | 'fail' | 'pending' | 'none'
  review?: 'APPROVED' | 'CHANGES_REQUESTED' | 'REVIEW_REQUIRED' | null
  mergeable?: 'MERGEABLE' | 'CONFLICTING' | 'UNKNOWN'
  updatedAt?: string
  draft?: boolean
}

export function prJson(p: PrIn): Record<string, unknown> {
  const checks = p.checks ?? 'pass'
  const rollup =
    checks === 'none'
      ? []
      : checks === 'pass'
        ? [{ __typename: 'CheckRun', name: 'ci', status: 'COMPLETED', conclusion: 'SUCCESS' }]
        : checks === 'fail'
          ? [
              { __typename: 'CheckRun', name: 'lint', status: 'COMPLETED', conclusion: 'SUCCESS' },
              { __typename: 'CheckRun', name: 'ci', status: 'COMPLETED', conclusion: 'FAILURE' },
            ]
          : [{ __typename: 'CheckRun', name: 'ci', status: 'IN_PROGRESS', conclusion: '' }]
  return {
    number: p.number,
    title: p.title ?? `Change number ${p.number}`,
    author: { login: p.author ?? 'alice' },
    headRefName: p.branch,
    url: `https://github.com/alice/repo/pull/${p.number}`,
    isDraft: p.draft ?? false,
    state: p.state ?? 'OPEN',
    reviewDecision: p.review === undefined ? null : p.review,
    mergeable: p.mergeable ?? 'MERGEABLE',
    mergeStateStatus: p.mergeable === 'CONFLICTING' ? 'DIRTY' : 'CLEAN',
    statusCheckRollup: rollup,
    updatedAt: p.updatedAt ?? '2026-10-12T10:00:00Z',
  }
}

export const WT3 = worktrees([
  { path: '/work/repo', branch: 'feat/auth' },
  { path: '/work/wt/fix-login', branch: 'fix/login' },
  { path: '/work/wt/export', branch: 'feat/export' },
])

export const PRS3 = [
  prJson({ number: 412, title: 'Add auth flow', branch: 'feat/auth', checks: 'pass', review: 'APPROVED' }),
  prJson({ number: 418, title: 'Fix login redirect', branch: 'fix/login', checks: 'fail', review: 'CHANGES_REQUESTED' }),
  prJson({ number: 421, title: 'Export to csv', branch: 'feat/export', checks: 'pending', review: 'REVIEW_REQUIRED' }),
]

// ---------------------------------------------------------------- test-runner output samples

export const ANSI = {
  green: (s: string) => `\u001b[32m${s}\u001b[39m`,
  red: (s: string) => `\u001b[31m${s}\u001b[39m`,
  bold: (s: string) => `\u001b[1m${s}\u001b[22m`,
}

export const PYTEST_3F_12P_1S = [
  '============================= test session starts ==============================',
  'platform darwin -- Python 3.12.4, pytest-8.2.0',
  'collected 16 items',
  '',
  'tests/test_a.py ....F..                                                  [ 43%]',
  'tests/test_b.py .....FF.s                                                [100%]',
  '',
  '=========================== short test summary info ============================',
  'FAILED tests/test_a.py::test_x - AssertionError: assert 1 == 2',
  'FAILED tests/test_b.py::test_y - ValueError: bad',
  'FAILED tests/test_b.py::test_z - KeyError: z',
  '3 failed, 12 passed, 1 skipped in 2.31s',
].join('\n')

export const pytestRun = (failed: string[], passed: number, secs = '0.50s'): string =>
  [
    '============================= test session starts ==============================',
    'collected ' + (failed.length + passed) + ' items',
    '',
    ...(failed.length > 0
      ? [
          '=========================== short test summary info ============================',
          ...failed.map(f => `FAILED ${f} - AssertionError`),
          `${failed.length} failed, ${passed} passed in ${secs}`,
        ]
      : [`============================== ${passed} passed in ${secs} ===============================`]),
  ].join('\n')

export const VITEST_OUT = [
  ' RUN  v1.6.0 /work/repo',
  '',
  ' ❯ src/a.test.ts  (6 tests | 2 failed) 12ms',
  '   × adds numbers',
  '   × subtracts numbers',
  '',
  ' FAIL  src/a.test.ts > math > adds numbers',
  'AssertionError: expected 2 to be 3',
  '',
  ' Test Files  1 failed | 1 passed (2)',
  '      Tests  2 failed | 10 passed (12)',
  '   Start at  14:02:11',
  '   Duration  1.52s (transform 20ms, setup 0ms, collect 51ms, tests 33ms)',
].join('\n')

export const JEST_OUT = [
  'FAIL src/math.test.js',
  '  ● math › adds numbers',
  '',
  '    expect(received).toBe(expected)',
  '',
  'Test Suites: 1 failed, 1 passed, 2 total',
  'Tests:       1 failed, 9 passed, 10 total',
  'Snapshots:   0 total',
  'Time:        2.1 s',
  'Ran all test suites.',
].join('\n')

export const BUN_OUT = [
  'bun test v1.1.8 (89b4dd35)',
  '',
  'src/a.test.ts:',
  '(pass) adds [0.12ms]',
  '(fail) subtracts [0.34ms]',
  '',
  ' 10 pass',
  ' 1 fail',
  ' 12 expect() calls',
  'Ran 11 tests across 2 files. [120.00ms]',
].join('\n')

export const GO_OUT = [
  'ok  \ta\t0.123s',
  '--- FAIL: TestX (0.00s)',
  '    x_test.go:12: boom',
  'FAIL',
  'FAIL\tb\t0.500s',
  'FAIL',
].join('\n')

export const CARGO_OUT = [
  'running 6 tests',
  'test a::one ... ok',
  'test a::two ... ignored',
  '',
  'test result: ok. 5 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out; finished in 0.01s',
  '',
  'running 5 tests',
  'test b::three ... ok',
  'test b::four ... FAILED',
  'test b::five ... FAILED',
  '',
  'failures:',
  '    b::four',
  '    b::five',
  '',
  'test result: FAILED. 3 passed; 2 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.02s',
].join('\n')

// ---------------------------------------------------------------- the world

export type Resp = { exitCode?: number; stdout?: string; stderr?: string; delayMs?: number; reject?: string }
export type Call = { argv: string[]; cwd?: string; timeoutMs?: number; env?: Record<string, string>; at: number }
export type Toast = { text: string; timeoutMs?: number; at: number }
export type Listener = { pid: number; cmd: string; addrs: string[]; cwd: string }
type RuleTest = ((argv: readonly string[]) => boolean) | readonly string[]
type Rule = { test: RuleTest; resp: Resp | ((argv: readonly string[], n: number) => Resp); n: number }

export type WorldCfg = {
  now?: number
  top?: string
  noRepo?: boolean
  branch?: string
  remote?: string | null
  me?: string
  surfaces?: string[]
  store?: Record<string, unknown>
  /** Every process.run rejects (host without process-exec). */
  procDown?: boolean
  linkedWorktree?: boolean
}

const matches = (t: RuleTest, argv: readonly string[]): boolean => {
  if (typeof t === 'function') return t(argv)
  const shown = argv.map((a, i) => (i === 0 ? base(a) : a))
  return t.every(tok => shown.includes(tok))
}

export function world(on: On, cfg: WorldCfg = {}) {
  const o = on as unknown as (...a: Any[]) => unknown
  const clock: MockClock = mock.clock(on, { now: cfg.now ?? T0 })
  mock.store(on, cfg.store ?? {})

  const top = cfg.top ?? TOP
  const w: Any = {
    clock,
    top,
    noRepo: cfg.noRepo ?? false,
    branch: cfg.branch ?? 'main',
    procDown: cfg.procDown ?? false,
    linkedWorktree: cfg.linkedWorktree ?? false,
    remote: cfg.remote === undefined ? 'git@github.com:alice/repo.git' : cfg.remote,
    me: cfg.me ?? 'alice',
    surfaces: cfg.surfaces ?? ['terminal'],
    gitStatusOut: undefined as string | undefined,
    worktreeOut: WT3 as string,
    prSeq: [] as unknown[][],
    ghAuthExit: 0,
    listeners: [] as Listener[],
    killRemoves: true,
    calls: [] as Call[],
    toasts: [] as Toast[],
    statuses: [] as (string | undefined)[],
    opened: [] as string[],
    commands: [] as string[],
    files: new Map<string, { text: string; mtimeMs: number }>(),
    peers: {} as Record<string, unknown>,
    rules: [] as Rule[],
    results: new Map<string, Any>(),
    inner: undefined as Any,
    nextId: 0,
    treeN: 0,
    prN: 0,
  }

  // ----- process.run -------------------------------------------------------------------------
  const defaultProc = (argv: readonly string[]): Resp => {
    const a0 = base(argv[0])
    const sub = argv[1]
    if (a0 === 'git') {
      if (argv.includes('--version')) return { stdout: 'git version 2.50.1\n' }
      if (w.noRepo) return { exitCode: 128, stderr: 'fatal: not a git repository (or any of the parent directories): .git\n' }
      if (sub === 'rev-parse' || argv.includes('rev-parse')) {
        if (argv.includes('-q') && argv.includes('--verify')) return { exitCode: 1 }
        const gitDir = w.linkedWorktree ? `${top.replace(/\/[^/]+$/, '')}/main/.git/worktrees/${base(top)}` : `${top}/.git`
        const common = w.linkedWorktree ? `${top.replace(/\/[^/]+$/, '')}/main/.git` : `${top}/.git`
        const lines: string[] = []
        argv.forEach((a, i) => {
          if (a === '--show-toplevel') lines.push(top)
          else if (a === '--git-dir') lines.push(gitDir)
          else if (a === '--git-common-dir') lines.push(common)
          else if (a === '--git-path') lines.push(`${gitDir}/${argv[i + 1]}`)
          else if (a.startsWith('HEAD')) lines.push('treeHEAD')
        })
        return { stdout: lines.join('\n') + (lines.length > 0 ? '\n' : '') }
      }
      if (argv.includes('status')) {
        if (argv.some((a: string) => a.startsWith('--porcelain=v2'))) return { stdout: w.gitStatusOut ?? porcelain({ head: w.branch }) }
        return { stdout: '' }
      }
      if (argv.includes('write-tree')) return { stdout: `tree${++w.treeN}\n` }
      if (argv.includes('worktree')) return { stdout: w.worktreeOut }
      return { stdout: '' }
    }
    if (a0 === 'gh') {
      if (argv[1] === 'auth') return { exitCode: w.ghAuthExit, stderr: w.ghAuthExit === 0 ? '' : 'You are not logged into any GitHub hosts.\n' }
      if (argv[1] === 'api') return { stdout: `${w.me}\n` }
      if (argv[1] === 'pr' && argv[2] === 'list') {
        const i = Math.min(w.prN, Math.max(0, w.prSeq.length - 1))
        w.prN += 1
        return { stdout: JSON.stringify(w.prSeq[i] ?? []) }
      }
      return { stdout: '' }
    }
    if (a0 === 'lsof') {
      if (argv.includes('-d') && argv.includes('cwd')) {
        const pids = (argv[argv.indexOf('-p') + 1] ?? '').split(',').map(Number)
        return {
          stdout: (w.listeners as Listener[])
            .filter(l => pids.includes(l.pid))
            .map(l => `p${l.pid}\nn${l.cwd}\n`)
            .join(''),
        }
      }
      return {
        stdout: (w.listeners as Listener[])
          .map(l => `p${l.pid}\nc${l.cmd}\n${l.addrs.map((a, i) => `f${11 + i}\nn${a}\n`).join('')}`)
          .join(''),
      }
    }
    if (a0 === 'kill') {
      const pid = Number(argv[argv.length - 1])
      if (w.killRemoves) w.listeners = (w.listeners as Listener[]).filter(l => l.pid !== pid)
      return {}
    }
    return {}
  }

  o('process.run', async (_$: Any, e: Any) => {
    const argv = [...(e.argv as string[])]
    const init = (e.init ?? {}) as { cwd?: string; timeoutMs?: number; env?: Record<string, string> }
    w.calls.push({ argv, cwd: init.cwd, timeoutMs: init.timeoutMs, env: init.env, at: clock.now() })
    if (w.procDown) return { deny: 'process.run is unavailable on this host' }
    let resp: Resp | undefined
    for (const r of w.rules) {
      if (matches(r.test, argv)) {
        resp = typeof r.resp === 'function' ? r.resp(argv, r.n) : r.resp
        r.n += 1
        break
      }
    }
    resp ??= defaultProc(argv)
    if (resp.reject !== undefined) return { deny: resp.reject }
    if (resp.delayMs !== undefined && resp.delayMs > 0) await clock.sleep(resp.delayMs)
    return {
      value: {
        exitCode: resp.exitCode ?? 0,
        stdout: resp.stdout ?? '',
        stderr: resp.stderr ?? '',
        isStdoutTruncated: false,
        isStderrTruncated: false,
      },
    }
  })

  // ----- session -----------------------------------------------------------------------------
  o('session.start', async (_$: Any, e: Any) => ({ cwd: e.cwd }))
  o('session.end', async () => ({}))
  o('turn.complete', async () => ({ text: '' }))
  o('session.cwd', async () => ({ value: top }))
  o('session.root', async () => ({ value: top }))
  o('session.id', async () => ({ value: SESSION_ID }))
  o('session.surfaces', async () => ({ value: w.surfaces }))
  o('session.surface', async () => ({ value: w.surfaces[0] ?? null }))
  o('session.repo', async () => ({
    value: w.noRepo ? null : { root: top, remote: w.remote, originUrl: w.remote, internal: false, name: null },
  }))

  // ----- commands, ui ------------------------------------------------------------------------
  o('command.list', async () => ({ value: [] }))
  o('command.register', async (_$: Any, e: Any) => {
    w.commands.push(String(e.name))
    return { value: { command: String(e.name) } }
  })
  o('command.run', async () => ({}))
  o('ui.toast', async (_$: Any, e: Any) => {
    w.toasts.push({ text: String(e.text), timeoutMs: e.timeoutMs, at: clock.now() })
    return { value: undefined }
  })
  o('ui.status', async (_$: Any, e: Any) => {
    w.statuses.push(e.text)
    return { value: undefined }
  })
  o('ui.open', async (_$: Any, e: Any) => {
    w.opened.push(String(e.id))
    return { value: { isPlaced: true } }
  })
  o('ui.close', async () => ({ value: undefined }))
  o('ui.log', async () => ({ value: undefined }))
  o('ui.notice', async () => ({ value: undefined }))
  o('ui.render', async (_$: Any, e: Any) => (e.component === 'AbovePrompt' && w.inner ? w.inner : { type: 'Box', props: {}, children: [] }))

  // ----- fs ----------------------------------------------------------------------------------
  o('fs.exists', async (_$: Any, e: Any) => ({ value: w.files.has(String(e.path)) }))
  o('fs.stat', async (_$: Any, e: Any) => {
    const f = w.files.get(String(e.path))
    if (f === undefined) return { deny: `ENOENT: ${String(e.path)}` }
    return { value: { kind: 'file', size: f.text.length, mtimeMs: f.mtimeMs, isLink: false } }
  })
  o('fs.read', async (_$: Any, e: Any) => {
    const f = w.files.get(String(e.path))
    if (f === undefined) return { deny: `ENOENT: ${String(e.path)}` }
    return { value: f.text }
  })
  o('fs.list', async () => ({ value: [] }))
  o('fs.ancestors', async () => ({ value: [] }))

  // ----- tool.call (engine side) -------------------------------------------------------------
  o('tool.call', async (_$: Any, e: Any) => w.results.get(String(e.tool_use_id)) ?? { result: {}, text: '' })

  // ----- peers' state (awareness atoms are read-only slices; absent = no information) --------
  o('state.get', async ($: Any, e: Any, next: Any) => {
    if (e.plugin === 'awareness') {
      const v = w.peers[String(e.key)]
      return { value: { value: v, version: v === undefined ? 0 : 1 } }
    }
    return next(e)
  })
  w.stateWrites = [] as { plugin: string; key: string; value: unknown; at: number }[]
  o('state.set', async ($: Any, e: Any, next: Any) => {
    w.stateWrites.push({ plugin: String(e.plugin), key: String(e.key), value: e.value, at: clock.now() })
    return next(e)
  })

  // ----- api ---------------------------------------------------------------------------------
  const api: Any = Object.assign(w, {
    /** Add a process rule (checked before the defaults; newest first). */
    rule(test: RuleTest, resp: Resp | ((argv: readonly string[], n: number) => Resp)): void {
      w.rules.unshift({ test, resp, n: 0 })
    },
    setFile(path: string, text: string, age = 0): void {
      w.files.set(path, { text, mtimeMs: clock.now() - age })
    },
    count(pred: (c: Call) => boolean): number {
      return (w.calls as Call[]).filter(pred).length
    },
    gitStatusCalls: (): Call[] => (w.calls as Call[]).filter(c => base(c.argv[0]) === 'git' && c.argv.includes('status') && c.argv.some((a: string) => a.startsWith('--porcelain=v2'))),
    prListCalls: (): Call[] => (w.calls as Call[]).filter(c => base(c.argv[0]) === 'gh' && c.argv[1] === 'pr' && c.argv[2] === 'list'),
    tscCalls: (): Call[] => (w.calls as Call[]).filter(c => c.argv.some(a => a === 'tsc' || a.endsWith('/tsc')) && !c.argv.includes('rev-parse')),
    killCalls: (): Call[] => (w.calls as Call[]).filter(c => base(c.argv[0]) === 'kill'),
    lsofCalls: (): Call[] => (w.calls as Call[]).filter(c => base(c.argv[0]) === 'lsof'),
    /** Peer atoms of awareness. */
    setPeer(key: 'headsup' | 'focus', value: unknown): void {
      w.peers[key] = value
    },
    now: (): number => clock.now(),
    async settle(): Promise<void> {
      await clock.settle()
    },
    async advance(ms: number): Promise<void> {
      await clock.advance(ms)
    },
    /** Advance in 5 s steps until `done()` or `maxMs` elapsed. Returns whether done. */
    async until(done: () => boolean, maxMs = 20 * 60_000, step = 5000): Promise<boolean> {
      const end = clock.now() + maxMs
      while (!done() && clock.now() < end) await clock.advance(step)
      return done()
    },
    async untilPr(n: number, maxMs = 20 * 60_000): Promise<boolean> {
      return api.until(() => w.prN >= n || api.prListCalls().length >= n, maxMs)
    },

    // ----- events --------------------------------------------------------------------------
    async start($: Any, surface: Surface = 'terminal'): Promise<void> {
      await $.session.start({ cwd: top, surface, isInteractive: true })
      await clock.settle()
    },
    async turnComplete($: Any, agentId?: string): Promise<void> {
      await $.turn.complete({ answer: '', durationMs: 1000, isAborted: false, turnId: 'turn1', reason: 'answer', ...(agentId ? { agentId } : {}) })
      await clock.settle()
    },
    async sessionEnd($: Any, reason = 'clear'): Promise<void> {
      await $.session.end({ reason, sessionId: SESSION_ID })
      await clock.settle()
    },

    // ----- tool calls ----------------------------------------------------------------------
    /** Starts a tool call without awaiting it (for budget tests). */
    toolPromise($: Any, input: Record<string, unknown>, answer: Any): Promise<Any> {
      const id = `tu${++w.nextId}`
      w.results.set(id, answer)
      return Promise.resolve($.tool.call({ ...input, tool_use_id: id })).then((res: Any) => {
        const t = input.tool
        if (typeof t === 'string' && t.startsWith('mcp__') && res?.result !== undefined && typeof res.result !== 'string' && !Array.isArray(res.result)) {
          throw new Error(`tool.call step resolved ${t} with a result that does not match its output shape ... invalid_union (expected string | array | undefined, received ${res.result === null ? 'null' : typeof res.result})`)
        }
        return res
      })
    },
    async tool($: Any, input: Record<string, unknown>, answer: Any): Promise<Any> {
      const out = await api.toolPromise($, input, answer)
      await clock.settle()
      return out
    },
    bashAnswer(
      stdout: string,
      x: { stderr?: string; isError?: boolean; readOnly?: boolean; gitOperation?: Any; ghRateLimitHint?: string } = {},
    ): Any {
      const result = {
        stdout,
        stderr: x.stderr ?? '',
        interrupted: false,
        ...(x.gitOperation ? { gitOperation: x.gitOperation } : {}),
        ...(x.ghRateLimitHint ? { ghRateLimitHint: x.ghRateLimitHint } : {}),
      }
      if (x.isError) return { isError: true, result: stdout, text: stdout }
      return { result, text: stdout, ...(x.readOnly ? { isReadOnly: true } : {}) }
    },
    async bash(
      $: Any,
      command: string,
      stdout = '',
      x: { stderr?: string; isError?: boolean; readOnly?: boolean; gitOperation?: Any; agentId?: string; background?: boolean; ghRateLimitHint?: string } = {},
    ): Promise<Any> {
      return api.tool(
        $,
        { tool: 'Bash', command, ...(x.agentId ? { agentId: x.agentId } : {}), ...(x.background ? { run_in_background: true } : {}) },
        api.bashAnswer(stdout, x),
      )
    },
    editAnswer(file: string, lines: string[]): Any {
      return {
        result: {
          filePath: file,
          oldString: 'a',
          newString: 'b',
          originalFile: 'a',
          structuredPatch: [{ oldStart: 1, oldLines: 1, newStart: 1, newLines: 1, lines }],
          userModified: false,
          replaceAll: false,
        },
        text: `The file ${file} has been updated.`,
      }
    },
    async edit($: Any, file: string, lines: string[] = ['-a', '+b'], agentId?: string): Promise<Any> {
      return api.tool(
        $,
        { tool: 'Edit', file_path: file, old_string: 'a', new_string: 'b', ...(agentId ? { agentId } : {}) },
        api.editAnswer(file, lines),
      )
    },
    async write($: Any, file: string, content = 'export const a = 1\n', lines: string[] = ['+export const a = 1'], agentId?: string): Promise<Any> {
      return api.tool(
        $,
        { tool: 'Write', file_path: file, content, ...(agentId ? { agentId } : {}) },
        {
          result: { type: 'update', filePath: file, content, structuredPatch: [{ oldStart: 1, oldLines: 0, newStart: 1, newLines: lines.length, lines }], originalFile: '' },
          text: `The file ${file} has been updated.`,
        },
      )
    },

    // ----- commands and UI -----------------------------------------------------------------
    async cmd($: Any, name: string, args = ''): Promise<string> {
      const r = await $.command.run({ command: name, args, origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 100 } })
      await clock.settle()
      return norm(String(r?.text ?? ''))
    },
    async band($: Any, surface: Surface, over: Record<string, unknown> = {}): Promise<string> {
      const read = async (sf: Surface): Promise<string> => {
        const ui = await $.ui.mount({
          plugin: 'dev',
          surface: sf,
          component: 'AbovePrompt',
          props: { hasSurvey: false, isWorking: false, maxRows: 6, bodyColumns: 160, scroll: { offset: 0, bodyRows: 6 }, view: {}, ...over },
          viewport: { columns: (over.bodyColumns as number | undefined) ?? 160, rows: 50, isFullscreen: false },
        })
        const text = norm(textOf(await ui.drawn()))
        await ui.unmount()
        return text
      }
      const mine = await read(surface)
      const other = await read(surface === 'terminal' ? 'desktop' : 'terminal')
      expect(surface === 'terminal' ? other : mine, 'desktop band text differs from terminal band text').toBe(surface === 'terminal' ? mine : other)
      return mine
    },
    async openPane($: Any, surface: Surface, id: 'pr-radar' | 'changes' | 'ports', title = id): Promise<{ ui: Any; text: () => Promise<string> }> {
      const ui = await $.ui.mount({
        plugin: 'dev',
        surface,
        component: 'Pane',
        requestId: id,
        props: { title, isFocused: true, bodyColumns: 100, scroll: { offset: 0, bodyRows: 30 } },
        viewport: { columns: 120, rows: 40, isFullscreen: true },
      })
      return { ui, text: async () => norm(textOf(await ui.drawn())) }
    },
  })
  return api as World
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export interface World {
  [k: string]: Any
  calls: Call[]
  toasts: Toast[]
  statuses: (string | undefined)[]
  commands: string[]
  listeners: Listener[]
  count(pred: (c: Call) => boolean): number
  gitStatusCalls(): Call[]
  prListCalls(): Call[]
  tscCalls(): Call[]
  killCalls(): Call[]
  lsofCalls(): Call[]
}

/** Slice of `text` belonging to the row that starts with `marker` (up to the next `#NNN`). */
export function rowOf(text: string, marker: string): string {
  const i = text.indexOf(marker)
  if (i < 0) return ''
  const rest = text.slice(i + marker.length)
  const j = rest.search(/#\d{3}/)
  return text.slice(i, j < 0 ? undefined : i + marker.length + j)
}

/** Extract the interval gaps (seconds) between consecutive call times. */
export const gaps = (calls: Call[]): number[] => calls.slice(1).map((c, i) => Math.round((c.at - calls[i]!.at) / 1000))

export { expect }
