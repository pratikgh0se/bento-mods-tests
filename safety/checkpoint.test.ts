import { test, expect } from 'claude-code/testing'
import { world, BANNED, SID, S8, REF, TMP, T0 } from './harness'

const DAY = 86_400_000
const idxFile = (e: Record<string, string>) => e.GIT_INDEX_FILE

async function ready($: any, on: any, o: Parameters<typeof world>[2] = {}) {
  const w = world($, on, o)
  await w.start()
  w.procs.length = 0 // start-up probe/prune calls are not part of the per-turn plumbing
  return w
}

test('C20 plumbing order, GIT_INDEX_FILE, identity env, update-ref target', async ($, on) => {
  const w = await ready($, on)
  await w.cycle()
  const g = w.gitCalls()
  const top = w.procs.findIndex(p => p.argv.join(' ').includes('--show-toplevel'))
  expect(top).toBeGreaterThanOrEqual(0)
  expect(top).toBeLessThan(w.procs.findIndex(p => p.argv[0] === 'cp')) // ref-tip reads (log/cat-file) may come first
  // key steps in order (rev-parse lookups of LASTTREE/PARENT are ambiguous in argv shape and not asserted here)
  const order = w.procs.map(p => (p.argv[0] === 'git' ? w.sub(p.argv) : p.argv[0])).filter(s => ['cp', 'add', 'write-tree', 'commit-tree', 'update-ref', 'rm'].includes(s))
  expect(order).toEqual(['cp', 'add', 'write-tree', 'commit-tree', 'update-ref', 'rm'])
  for (const p of g) {
    const s = w.sub(p.argv)
    if (['add', 'write-tree', 'read-tree'].includes(s)) expect(idxFile(p.env)).toEndWith(`claude-ckpt-${S8}.index`)
  }
  const ct = g.find(p => w.sub(p.argv) === 'commit-tree')!
  expect(ct.env.GIT_AUTHOR_NAME).toBe('claude-checkpoint')
  expect(ct.env.GIT_AUTHOR_EMAIL).toBe('checkpoint@localhost')
  expect(ct.env.GIT_COMMITTER_NAME).toBe('claude-checkpoint')
  expect(ct.env.GIT_COMMITTER_EMAIL).toBe('checkpoint@localhost')
  const ur = g.find(p => w.sub(p.argv) === 'update-ref')!
  expect(ur.argv).toContain(REF)
  const cp = w.procs.find(p => p.argv[0] === 'cp')!
  expect(cp.argv[cp.argv.length - 1]).toBe(TMP)
})

test('C21 no banned git subcommand and no add without GIT_INDEX_FILE', async ($, on) => {
  const w = await ready($, on)
  await w.cycle()
  await w.clock.advance(130_000)
  await w.cycle()
  expect(w.gitCalls().length).toBeGreaterThan(0)
  for (const p of w.gitCalls()) {
    const s = w.sub(p.argv)
    expect(BANNED).not.toContain(s)
    if (s === 'add') expect(typeof p.env.GIT_INDEX_FILE).toBe('string')
  }
})

test('C22 same tree as last checkpoint: no commit-tree/update-ref, count unchanged', async ($, on) => {
  const w = await ready($, on, { ref: 'c0', refTree: 'T1', trees: ['T1'] })
  const before = (await w.state('checkpoint'))?.count ?? 0
  await w.cycle()
  const subs = w.subs()
  expect(subs).toContain('write-tree')
  expect(subs).not.toContain('commit-tree')
  expect(subs).not.toContain('update-ref')
  expect((await w.state('checkpoint'))?.count ?? 0).toBe(before)
})

test('C23 no dirty mark: no process call at turn.complete', async ($, on) => {
  const w = await ready($, on)
  await w.tool({ tool: 'Read', file_path: '/repo/a.ts' })
  await w.turn()
  await w.clock.settle()
  expect(w.procs.length).toBe(0)
})
test('C23 subagent turn.complete never triggers a checkpoint', async ($, on) => {
  const w = await ready($, on)
  await w.write('/repo/a.ts')
  await w.turn('a1')
  await w.clock.settle()
  expect(w.procs.length).toBe(0)
})

test('C24 two dirty turns 30 s apart give one checkpoint; at 130 s a second chained on the first', async ($, on) => {
  const w = await ready($, on)
  await w.cycle()
  await w.clock.advance(30_000)
  await w.cycle()
  expect(w.subs().filter(s => s === 'commit-tree').length).toBe(1)
  await w.clock.advance(100_000)
  await w.cycle()
  expect(w.subs().filter(s => s === 'commit-tree').length).toBe(2)
  expect(w.sim.commitParents[1]).toBe('commit1')
})

test('C25 index.lock present: no cp, no add, no error toast', async ($, on) => {
  const w = await ready($, on, { lockExists: true })
  await w.cycle()
  expect(w.procs.some(p => p.argv[0] === 'cp')).toBe(false)
  expect(w.subs()).not.toContain('add')
  expect(w.toasts.length).toBe(0)
})

test('C26 2500 untracked files: capped, one SKIPPED toast with 2500, no write-tree', async ($, on) => {
  const w = await ready($, on, { untracked: 2500 })
  await w.cycle()
  expect((await w.state('checkpoint'))?.state).toBe('capped')
  const sk = w.toasts.filter(t => t.includes('SKIPPED'))
  expect(sk.length).toBe(1)
  expect(sk[0]).toContain('2500')
  expect(w.subs()).not.toContain('write-tree')
})

test('C27 process.run rejecting on probe: unavailable, status needs host commands, no further calls', async ($, on) => {
  const w = world($, on, { procReject: true })
  await w.start()
  await w.clock.settle()
  expect((await w.state('checkpoint'))?.state).toBe('unavailable')
  expect(w.statuses.filter(Boolean).join(' | ')).toContain('needs host commands')
  const n = w.procs.length
  const r = await w.write('/repo/a.ts')
  expect(w.denied(r)).toBe(false)
  await w.turn()
  await w.clock.settle()
  expect(w.procs.length).toBe(n)
  expect(w.denied(await w.write('/repo/.env'))).toBe(true) // protect still works
})

test('C28 prune on start: only the 20-day-old ref is deleted (keepDays=14)', async ($, on) => {
  const nowSec = Math.floor(T0 / 1000)
  const w = world($, on, {
    forEachRef: `refs/checkpoints/old-sess ${nowSec - 20 * 86400}\nrefs/checkpoints/new-sess ${nowSec - 86400}\n`,
  })
  await w.start()
  await w.clock.settle()
  const del = w.gitCalls().filter(p => w.sub(p.argv) === 'update-ref' && p.argv.includes('-d'))
  expect(del.length).toBe(1)
  expect(del[0].argv).toContain('refs/checkpoints/old-sess')
})

for (const args of ['restore 3', 'restore 3 src/a.ts', 'restore 3 --yes']) {
  test(`C29 /checkpoint ${args} only prints the command`, async ($, on) => {
    const w = await ready($, on)
    await w.cycle()
    const n = w.procs.length
    const t = await w.cmd('checkpoint', args)
    expect(t).toContain('git restore --source=refs/checkpoints/')
    expect(t).toContain(S8)
    if (args.includes('src/a.ts')) expect(t.trim().endsWith('-- src/a.ts')).toBe(true)
    expect(w.procs.length).toBe(n)
  })
}

for (const surface of ['terminal', 'desktop'] as const) {
  test(`C30 /checkpoint status text on ${surface}`, async ($, on) => {
    const w = await ready($, on, { surfaces: [surface] })
    await w.cycle()
    await w.clock.advance(3 * 60_000)
    const t = await w.cmd('checkpoint', '')
    expect(t).toContain('ref refs/checkpoints/')
    expect(t).toMatch(/\b1\b/)
    expect(t).toMatch(/ago|just now|min/)
  })
}

// Skipped (manual list, no test.skip in the kit): M01 behaviour under bypassPermissions (UNVERIFIED); M02 linked worktree on a real repo.
