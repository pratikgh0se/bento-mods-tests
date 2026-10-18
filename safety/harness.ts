// Shared harness for the safety contract tests (not a test file).
// Everything is built from specs/safety.md section 7; no plugin code is read.
import { mock, expect } from 'claude-code/testing'

type Fn = (...a: any[]) => any
export const T0 = 1_800_000_000_000
export const SID = 'abcd1234-ef56-7890-aaaa-bbbbbbbbbbbb'
export const S8 = 'abcd1234'
export const TMP = `/repo/.git/claude-ckpt-${S8}.index`
export const LOCK = '/repo/.git/index.lock'
export const REF = `refs/checkpoints/${SID}`
export const MIN = 60_000

export type Proc = { argv: string[]; env: Record<string, string>; cwd?: string }

export type WorldOpts = {
  vault?: string | null // null = OBSIDIAN_VAULT_PATH unset
  home?: string
  cwd?: string
  surfaces?: ('terminal' | 'desktop')[]
  missing?: string[] // paths $.fs.stat reports as non-existent
  links?: Record<string, string> // path -> realPath
  lockExists?: boolean
  untracked?: number
  forEachRef?: string
  trees?: string[] // successive write-tree results
  ref?: string // existing checkpoint commit
  refTree?: string
  procReject?: boolean
  statThrows?: boolean
  /** directories $.fs.stat reports with kind 'dir' (always: /repo /work /tmp /v and the cwd) */
  dirs?: string[]
  /** a checkpoint ref that already exists for this session when the world starts (a resumed session) */
  tip?: { n: number; agoMs: number; tree: string }
}

export const ALLOWED_GIT = ['rev-parse', 'ls-files', 'add', 'write-tree', 'read-tree', 'commit-tree', 'update-ref', 'for-each-ref', 'diff', 'log', 'cat-file']
export const TIP_TREE = '9f3c2a1b8d4e6f70123456789abcdef012345678'
export const isoOf = (ms: number) => new Date(ms).toISOString()

export type World = ReturnType<typeof world>

export function world($: any, on: any, o: WorldOpts = {}) {
  const hook = on as (p: string, f: Fn) => void
  const clock = mock.clock(on, { now: T0 })
  const vault = o.vault === undefined ? '/v' : o.vault
  const env: Record<string, string> = { HOME: o.home ?? '/home/u' }
  if (vault !== null) env.OBSIDIAN_VAULT_PATH = vault
  mock.env(on, env)
  mock.store(on, {})
  const toasts: string[] = []
  const statuses: (string | undefined)[] = []
  const spy: any[] = []
  const procs: Proc[] = []
  const sim = {
    ref: o.ref as string | undefined,
    refTree: o.refTree as string | undefined,
    lastTree: '',
    n: 0,
    commitParents: [] as (string | undefined)[],
    trees: [...(o.trees ?? [])],
    untracked: o.untracked ?? 0,
    forEachRef: o.forEachRef ?? '',
    headTree: 'headtree000',
    tip: undefined as undefined | { sha: string; msg: string; ct: number; tree: string },
    msgs: [] as string[],
    violations: [] as string[],
  }
  if (o.tip) {
    const ct = Math.floor((T0 - o.tip.agoMs) / 1000)
    sim.tip = { sha: 'tipcommit0', msg: `checkpoint ${S8} #${o.tip.n} ${isoOf(ct * 1000)}`, ct, tree: o.tip.tree }
    sim.ref = 'tipcommit0'
    sim.refTree = o.tip.tree
  }
  const dirs = new Set(['/repo', '/work', '/tmp', '/v', o.cwd ?? '/repo', ...(o.dirs ?? [])])
  const missing = new Set(o.missing ?? [])
  const links = o.links ?? {}
  const surfaces = o.surfaces ?? ['terminal']

  hook('session.cwd', async () => ({ value: o.cwd ?? '/repo' }))
  hook('session.id', async () => ({ value: SID }))
  hook('session.surfaces', async () => ({ value: surfaces }))
  hook('command.list', async () => ({ value: [] }))
  hook('command.register', async () => ({ value: undefined }))
  hook('ui.toast', async (_$: any, e: any) => { toasts.push(e.text); return { value: undefined } })
  hook('ui.status', async (_$: any, e: any) => { statuses.push(e.text); return { value: undefined } })
  hook('fs.exists', async (_$: any, e: any) => ({ value: e.path === LOCK ? !!o.lockExists : !missing.has(e.path) }))
  hook('fs.stat', async (_$: any, e: any) => {
    if (o.statThrows) throw new TypeError('boom')
    if (missing.has(e.path)) throw new Error('ENOENT')
    const real = links[e.path]
    return { value: { kind: dirs.has(e.path) ? 'dir' : 'file', size: 1, mtimeMs: 0, isLink: !!real, realPath: e.resolve ? (real ?? e.path) : undefined } }
  })
  hook('session.start', async () => ({ cwd: o.cwd ?? '/repo' }))
  hook('command.run', async () => ({}))
  hook('turn.complete', async () => ({ text: '' }))
  hook('session.end', async () => ({}))
  const states: Record<string, any> = {}
  hook('state.set', async (_$: any, e: any, next: Fn) => { states[e.key ?? e.ref?.key] = e.value; return next(e) })
  // bottom of tool.call: the spy "next". Records every call that reaches it.
  hook('tool.call', async (_$: any, e: any) => {
    spy.push(e)
    return { result: 'ok', text: 'ok' }
  })

  const sub = (argv: string[]) => {
    if (argv[0] !== 'git') return argv[0]
    return argv.slice(1).find(a => !a.startsWith('-') && a !== TMP) ?? ''
  }
  hook('process.run', async (_$: any, e: any) => {
    const argv: string[] = [...e.argv]
    const init = e.init ?? {}
    procs.push({ argv, env: { ...(init.env ?? {}) }, cwd: init.cwd })
    if (o.procReject) throw new Error('spawn unavailable')
    const ok = (stdout = '', exitCode = 0) => ({ value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
    const s = sub(argv)
    if (argv[0] === 'cp' || argv[0] === 'rm') return ok()
    if (argv[0] === 'git' && !ALLOWED_GIT.includes(s) && !(s === '' && argv.includes('--version'))) {
      sim.violations.push(argv.join(' '))
      return ok('', 129)
    }
    const tip = sim.tip
    const expand = (f: string) => {
      if (!tip) return ''
      const iso = isoOf(tip.ct * 1000)
      const sp = iso.replace('T', ' ').replace('Z', ' +0000')
      const map: Record<string, string> = {
        '%H': tip.sha, '%h': tip.sha.slice(0, 7), '%T': tip.tree, '%t': tip.tree.slice(0, 7), '%s': tip.msg, '%B': tip.msg + '\n', '%b': '',
        '%ct': String(tip.ct), '%at': String(tip.ct), '%cI': iso, '%aI': iso, '%ci': sp, '%ai': sp,
        '%cn': 'claude-checkpoint', '%an': 'claude-checkpoint', '%ce': 'checkpoint@localhost', '%ae': 'checkpoint@localhost', '%n': '\n',
        '%(refname)': REF, '%(refname:short)': REF.replace('refs/', ''), '%(objectname)': tip.sha, '%(tree)': tip.tree, '%(subject)': tip.msg,
        '%(contents:subject)': tip.msg, '%(contents)': tip.msg + '\n', '%(committerdate:unix)': String(tip.ct), '%(authordate:unix)': String(tip.ct),
        '%(creatordate:unix)': String(tip.ct), '%(committerdate:iso-strict)': iso, '%(committerdate:iso8601-strict)': iso, '%(committerdate:iso)': sp, '%(committerdate)': iso,
      }
      return f.replace(/%\([^)]*\)|%x[0-9a-fA-F]{2}|%[a-zA-Z]{1,2}/g, m => (m.startsWith('%x') ? String.fromCharCode(parseInt(m.slice(2), 16)) : m in map ? map[m] : m))
    }
    const fmtArg = argv
      .map((a, i) => (a.startsWith('--format=') ? a.slice(9) : a.startsWith('--pretty=format:') ? a.slice(16) : a.startsWith('--pretty=') ? a.slice(9) : a === '--format' || a === '--pretty' ? argv[i + 1] : undefined))
      .find(x => x !== undefined)
    switch (s) {
      case 'rev-parse': {
        if (argv.includes('--show-toplevel')) return ok(`/repo\n/repo/.git/index\n${TMP}\n${LOCK}\n`)
        const tree = argv.find(a => a.includes('^{tree}'))
        if (tree && tree.includes('refs/checkpoints/')) return sim.refTree ? ok(sim.refTree + '\n') : ok('', 1)
        if (tree) return ok(sim.headTree + '\n')
        if (argv.some(a => a.includes('refs/checkpoints/'))) return sim.ref ? ok(sim.ref + '\n') : ok('', 1)
        return ok('headsha0000\n')
      }
      case 'ls-files': return ok(Array.from({ length: sim.untracked }, (_, i) => `u${i}.txt`).join('\n'))
      case 'write-tree': {
        sim.lastTree = sim.trees.length ? sim.trees.shift()! : `tree${++sim.n}`
        return ok(sim.lastTree + '\n')
      }
      case 'commit-tree': {
        const i = argv.indexOf('-p')
        sim.commitParents.push(i >= 0 ? argv[i + 1] : undefined)
        const mi = argv.indexOf('-m')
        sim.msgs.push(mi >= 0 ? argv[mi + 1] : String(init.stdin ?? ''))
        return ok(`commit${sim.commitParents.length}\n`)
      }
      case 'update-ref': {
        if (argv.includes('-d')) return ok()
        const nc = argv.find(a => a.startsWith('commit'))
        sim.ref = nc ?? sim.ref
        sim.refTree = sim.lastTree
        if (nc) sim.tip = { sha: nc, msg: (sim.msgs[sim.msgs.length - 1] ?? '').trim().split('\n')[0], ct: Math.floor(clock.now() / 1000), tree: sim.lastTree }
        return ok()
      }
      case 'for-each-ref': {
        if (sim.forEachRef) return ok(sim.forEachRef)
        return ok(tip ? expand(fmtArg ?? '%(refname) %(objectname)') + '\n' : '')
      }
      case 'log': {
        if (!tip) return ok('', 128)
        if (fmtArg !== undefined) return ok(expand(fmtArg) + '\n')
        return ok(`commit ${tip.sha}\nAuthor: claude-checkpoint <checkpoint@localhost>\nDate:   ${isoOf(tip.ct * 1000)}\n\n    ${tip.msg}\n`)
      }
      case 'cat-file': {
        if (!tip) return ok('', 128)
        if (argv.includes('-t')) return ok('commit\n')
        return ok(`tree ${tip.tree}\nauthor claude-checkpoint <checkpoint@localhost> ${tip.ct} +0000\ncommitter claude-checkpoint <checkpoint@localhost> ${tip.ct} +0000\n\n${tip.msg}\n`)
      }
      default: return ok()
    }
  })

  const w = {
    clock, toasts, statuses, spy, procs, sim,
    /** raise a tool.call through the plugin */
    tool: async (input: Record<string, unknown>): Promise<any> => {
      const res = await $.tool.call(input)
      const t = input.tool
      if (typeof t === 'string' && t.startsWith('mcp__') && res?.result !== undefined && typeof res.result !== 'string' && !Array.isArray(res.result)) {
        throw new Error(`tool.call step resolved ${t} with a result that does not match its output shape ... invalid_union (expected string | array | undefined, received ${res.result === null ? 'null' : typeof res.result})`)
      }
      return res
    },
    write: (file_path: string, extra: Record<string, unknown> = {}) => $.tool.call({ tool: 'Write', file_path, content: 'x', ...extra }),
    edit: (file_path: string, extra: Record<string, unknown> = {}) => $.tool.call({ tool: 'Edit', file_path, old_string: 'a', new_string: 'b', ...extra }),
    bash: (command: string, extra: Record<string, unknown> = {}) => $.tool.call({ tool: 'Bash', command, ...extra }),
    cmd: async (command: string, args = ''): Promise<string> => {
      const r = await $.command.run({ command, args })
      return String(r?.text ?? '')
    },
    start: () => $.session.start({ cwd: o.cwd ?? '/repo', surface: 'terminal', isInteractive: true }),
    turn: (agentId?: string) =>
      $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId: 't' + Math.random(), reason: 'answer', ...(agentId ? { agentId } : {}) }),
    state: async (key: 'protect' | 'checkpoint') => states[key] as any,
    /** a checkpoint cycle: one successful Write (dirty) then a main turn.complete */
    cycle: async () => {
      await w.write('/repo/a.ts')
      await w.turn()
      await clock.settle()
    },
    gitCalls: () => procs.filter(p => p.argv[0] === 'git'),
    subs: () => procs.map(p => sub(p.argv)),
    sub,
    denied: (r: any) => typeof r?.deny === 'string',
    wasCalled: () => spy.length,
  }
  return w
}

export const BANNED = ['stash', 'commit', 'reset', 'checkout', 'restore', 'clean', 'rm', 'gc', 'push', 'fetch']
export function assertDeny(r: any, ...parts: string[]) {
  expect(typeof r.deny).toBe('string')
  for (const p of parts) expect(r.deny).toContain(p)
}
