// Contract statements C33-C39 and C48-C52 (PR Radar and the failing-check toast).
// Source: specs/dev.md sections 4 and 13 "PR Radar" / "PR failing-check toast".
import { test, expect } from 'claude-code/testing'
import { SURFACES, TOP, world, crossCheck, prJson, PRS3, WT3, worktrees, rowOf, gaps, base } from './_harness'
import type { Any, World, PrIn } from './_harness'

const isPrList = (a: readonly string[]): boolean => base(a[0]) === 'gh' && a[1] === 'pr' && a[2] === 'list'

function prWorld(on: Any, seq: unknown[][], cfg: Record<string, unknown> = {}): World {
  const w = world(on, { branch: 'feat/auth', ...cfg })
  w.worktreeOut = WT3
  w.prSeq = seq
  return w
}

/** One of the user's own PRs on a branch of the fixture worktrees. */
const mine = (number: number, checks: PrIn['checks'], over: Partial<PrIn> = {}): Record<string, unknown> =>
  prJson({ number, title: `Change ${number}`, branch: number === 418 ? 'fix/login' : number === 419 ? 'feat/export' : 'feat/auth', checks, ...over })

// --------------------------------------------------------------------------------- C33 - C34

for (const surface of SURFACES) {
  test(`C33 three worktrees: rows #412 pass APPROVED, #418 fail CHANGES, #421 running PENDING; header "3 WORKTREES" [${surface}]`, async ($, on) => {
    const w = prWorld(on, [PRS3], { surfaces: [surface] })
    await w.start($, surface)
    expect(await w.untilPr(1, 3 * 60_000)).toBe(true)
    await w.settle()
    const pane = await w.openPane($, surface, 'pr-radar')
    const text = await pane.text()
    expect(text).toContain('3 WORKTREES')
    const r412 = rowOf(text, '#412')
    expect(r412).toContain('pass')
    expect(r412).toContain('APPROVED')
    const r418 = rowOf(text, '#418')
    expect(r418).toContain('fail')
    expect(r418).toContain('CHANGES')
    const r421 = rowOf(text, '#421')
    expect(r421).toContain('running')
    expect(r421).toContain('PENDING')
    const links = (await pane.ui.findAll({ type: 'Link' })) as { props: Record<string, unknown> }[]
    const hrefs = links.map(l => String(l.props.href))
    for (const n of [412, 418, 421]) expect(hrefs.some(h => h.includes(`/pull/${n}`))).toBe(true)
    crossCheck('C33', surface, text)
  })

  test(`C34 a branch with an open and a merged PR shows the open one [${surface}]`, async ($, on) => {
    const w = prWorld(
      on,
      [
        [
          prJson({ number: 400, title: 'Old merged work', branch: 'feat/auth', state: 'MERGED', updatedAt: '2026-10-12T12:00:00Z' }),
          prJson({ number: 412, title: 'Add auth flow', branch: 'feat/auth', state: 'OPEN', updatedAt: '2026-10-01T09:00:00Z' }),
        ],
      ],
      { surfaces: [surface] },
    )
    await w.start($, surface)
    await w.untilPr(1, 3 * 60_000)
    await w.settle()
    const pane = await w.openPane($, surface, 'pr-radar')
    const text = await pane.text()
    expect(text).toContain('#412')
    expect(text).not.toContain('#400')
    crossCheck('C34', surface, text)
  })
}

// --------------------------------------------------------------------------------- C35

test('C35 exactly one gh pr list per cycle, never within 60 s of the previous one, run with cwd=TOP and the documented fields', async ($, on) => {
  const w = prWorld(on, [[mine(421, 'pending')]])
  await w.start($)
  expect(await w.untilPr(1, 3 * 60_000)).toBe(true)
  const first = w.prListCalls()[0]!
  expect(first.cwd).toBe(TOP)
  expect(first.argv).toContain('--json')
  for (const f of ['number', 'title', 'author', 'headRefName', 'url', 'reviewDecision', 'mergeable', 'statusCheckRollup', 'updatedAt']) {
    expect(first.argv.join(' ')).toContain(f)
  }
  await w.advance(55_000)
  expect(w.prListCalls().length).toBe(1)
  expect(await w.untilPr(2, 3 * 60_000)).toBe(true)
  expect(await w.untilPr(3, 3 * 60_000)).toBe(true)
  for (const g of gaps(w.prListCalls())) expect(g).toBeGreaterThanOrEqual(60)
  const worktreeCalls = w.count(c => c.argv.includes('worktree') && c.argv.includes('--porcelain'))
  expect(worktreeCalls).toBeGreaterThanOrEqual(1)
})

test('C35 after a failure the next call is >= 120 s later, then >= 240 s', async ($, on) => {
  const w = prWorld(on, [[mine(421, 'pending')]])
  w.rule(isPrList, { exitCode: 1, stderr: 'HTTP 500: Server Error\n' })
  await w.start($)
  expect(await w.untilPr(1, 3 * 60_000)).toBe(true)
  expect(await w.untilPr(2, 4 * 60_000)).toBe(true)
  expect(await w.untilPr(3, 8 * 60_000)).toBe(true)
  const g = gaps(w.prListCalls())
  expect(g[0]).toBeGreaterThanOrEqual(120)
  expect(g[0]).toBeLessThan(240)
  expect(g[1]).toBeGreaterThanOrEqual(240)
})

for (const stderr of ['gh: API rate limit exceeded for user ID 1234.\n', 'gh: HTTP 429: Too Many Requests (https://api.github.com/graphql)\n', 'gh: HTTP 403: rate limit exceeded\n']) {
  test(`C35 rate limit (stderr ${JSON.stringify(stderr.slice(0, 30))}) -> no call for 15 min`, async ($, on) => {
    const w = prWorld(on, [[mine(421, 'pending')]])
    w.rule(isPrList, { exitCode: 1, stderr })
    await w.start($)
    expect(await w.untilPr(1, 3 * 60_000)).toBe(true)
    await w.advance(14 * 60_000)
    expect(w.prListCalls().length).toBe(1)
    await w.settle()
    const pane = await w.openPane($, 'terminal', 'pr-radar')
    expect(await pane.text()).toMatch(/rate limited until \d\d:\d\d/)
  })
}

test('C35 a Bash result carrying ghRateLimitHint pauses gh calls for 15 min', async ($, on) => {
  const w = prWorld(on, [[mine(421, 'pending')]])
  await w.start($)
  expect(await w.untilPr(1, 3 * 60_000)).toBe(true)
  await w.bash($, 'gh pr view 421', 'error', { ghRateLimitHint: 'GitHub API rate limit reached; wait before retrying.' })
  await w.advance(14 * 60_000)
  expect(w.prListCalls().length).toBe(1)
})

// --------------------------------------------------------------------------------- C36 - C38

test('C36 gh auth status exit 1 -> pane says to run gh auth login, no pr list calls', async ($, on) => {
  const w = prWorld(on, [PRS3])
  w.ghAuthExit = 1
  await w.start($)
  await w.advance(5 * 60_000)
  const pane = await w.openPane($, 'terminal', 'pr-radar')
  const text = await pane.text()
  expect(text).toContain('gh auth login')
  expect(w.prListCalls().length).toBe(0)
  // retried only after 10 minutes
  expect(w.count(c => base(c.argv[0]) === 'gh' && c.argv[1] === 'auth')).toBe(1)
})

test('C37 no user input for 10 min -> interval 180 s', async ($, on) => {
  const w = prWorld(on, [[mine(421, 'pending')]])
  await w.start($)
  await w.advance(21 * 60_000)
  const late = w.prListCalls().filter(c => c.at >= w.calls[0]!.at + 11 * 60_000)
  expect(late.length).toBeGreaterThanOrEqual(3)
  const g = gaps(late)
  for (const gap of g) {
    expect(gap).toBeGreaterThanOrEqual(175)
    expect(gap).toBeLessThanOrEqual(200)
  }
})

test('C38 origin not on github.com -> "no GitHub remote", no calls', async ($, on) => {
  const w = prWorld(on, [PRS3], { remote: 'git@gitlab.com:team/repo.git' })
  await w.start($)
  await w.advance(5 * 60_000)
  const pane = await w.openPane($, 'terminal', 'pr-radar')
  expect(await pane.text()).toContain('no GitHub remote')
  expect(w.prListCalls().length).toBe(0)
})

// --------------------------------------------------------------------------------- C39

for (const surface of SURFACES) {
  test(`C39 band chip shows the CURRENT branch's PR only [${surface}]`, async ($, on) => {
    const w = prWorld(on, [PRS3], { surfaces: [surface] })
    await w.start($, surface)
    await w.untilPr(1, 3 * 60_000)
    await w.settle()
    const text = await w.band($, surface)
    expect(text).toContain('#412')
    expect(text).toContain('checks')
    expect(text).toContain('APPROVED')
    expect(text).not.toContain('#418')
    expect(text).not.toContain('#421')
    crossCheck('C39a', surface, text)
  })

  test(`C39 no chip when the current branch has no PR [${surface}]`, async ($, on) => {
    const w = prWorld(on, [PRS3], { surfaces: [surface], branch: 'scratch' })
    w.worktreeOut = worktrees([
      { path: '/work/repo', branch: 'scratch' },
      { path: '/work/wt/fix-login', branch: 'fix/login' },
      { path: '/work/wt/export', branch: 'feat/export' },
    ])
    await w.start($, surface)
    await w.untilPr(1, 3 * 60_000)
    await w.settle()
    const text = await w.band($, surface)
    expect(text).not.toContain('#41')
    expect(text).not.toContain('#42')
    expect(text).not.toContain('checks')
    crossCheck('C39b', surface, text)
  })

  test(`C39 failing checks and conflicts show in the chip [${surface}]`, async ($, on) => {
    const w = prWorld(on, [[mine(412, 'fail', { review: 'CHANGES_REQUESTED', mergeable: 'CONFLICTING' })]], { surfaces: [surface] })
    await w.start($, surface)
    await w.untilPr(1, 3 * 60_000)
    await w.settle()
    const text = await w.band($, surface)
    expect(text).toContain('#412')
    expect(text).toContain('checks')
    expect(text).toContain('CONFLICT')
    crossCheck('C39c', surface, text)
  })
}

// --------------------------------------------------------------------------------- C48

test('C48 one toast when checks of my PR flip pass -> fail (text, length, timeout, lastShownAt)', async ($, on) => {
  const w = prWorld(on, [[mine(418, 'pass')], [mine(418, 'fail')]])
  await w.start($)
  expect(await w.untilPr(1, 3 * 60_000)).toBe(true)
  await w.settle()
  expect(w.toasts.length).toBe(0)
  expect(await w.untilPr(2, 5 * 60_000)).toBe(true)
  await w.advance(10_000)
  expect(w.toasts.length).toBe(1)
  const t = w.toasts[0]!
  expect(t.text).toContain('PR #418')
  expect(t.text).toContain('CHECKS FAILING')
  expect(t.text).toContain('/prs')
  expect(t.text.length).toBeLessThanOrEqual(140)
  expect(t.timeoutMs).toBe(8000)
  const writes = (w.stateWrites as { plugin: string; key: string; value: { lastShownAt?: number } | undefined }[]).filter(x => x.plugin === 'dev' && x.key === 'toast')
  const last = writes.map(x => x.value?.lastShownAt).filter((v): v is number => typeof v === 'number').pop()
  expect(typeof last).toBe('number')
  expect(Math.abs((last ?? 0) - t.at)).toBeLessThan(10_000)
})

// --------------------------------------------------------------------------------- C49

type NoToast = { name: string; seq: unknown[][]; options?: Record<string, unknown>; toasts: number }
const NO_TOAST: NoToast[] = [
  { name: 'pass -> pending', seq: [[mine(418, 'pass')], [mine(418, 'pending')]], toasts: 0 },
  { name: 'pending -> pass', seq: [[mine(418, 'pending')], [mine(418, 'pass')]], toasts: 0 },
  { name: 'none -> pass', seq: [[mine(418, 'none')], [mine(418, 'pass')]], toasts: 0 },
  { name: 'review becomes APPROVED', seq: [[mine(418, 'pass')], [mine(418, 'pass', { review: 'APPROVED' })]], toasts: 0 },
  { name: 'PR becomes MERGED', seq: [[mine(418, 'pass')], [mine(418, 'fail', { state: 'MERGED' })]], toasts: 0 },
  { name: 'PR becomes CONFLICTING', seq: [[mine(418, 'pass')], [mine(418, 'pass', { mergeable: 'CONFLICTING' })]], toasts: 0 },
  { name: 'baseline observation already failing', seq: [[mine(418, 'fail')], [mine(418, 'fail')]], toasts: 0 },
  { name: 'author someone-else flips to fail', seq: [[mine(418, 'pass', { author: 'someone-else' })], [mine(418, 'fail', { author: 'someone-else' })]], toasts: 0 },
  { name: 'pr.toastOnFail=false', seq: [[mine(418, 'pass')], [mine(418, 'fail')]], options: { 'pr_toastOnFail': false }, toasts: 0 },
  { name: 'still failing on the next cycle does not toast again', seq: [[mine(418, 'pass')], [mine(418, 'fail')], [mine(418, 'fail')]], toasts: 1 },
  { name: 'fail -> pass -> fail toasts again', seq: [[mine(418, 'pass')], [mine(418, 'fail')], [mine(418, 'pass')], [mine(418, 'fail')]], toasts: 2 },
]

for (const c of NO_TOAST) {
  test(`C49 ${c.name} -> ${c.toasts} toast(s)`, { options: (c.options ?? {}) as never }, async ($, on) => {
    const w = prWorld(on, c.seq)
    await w.start($)
    const ran = await w.untilPr(c.seq.length, 25 * 60_000)
    if (c.toasts > 0) expect(ran, 'PR cycles never ran').toBe(true)
    await w.advance(15_000)
    expect(w.toasts.length).toBe(c.toasts)
    if (c.toasts === 2) expect(w.toasts[1]!.at - w.toasts[0]!.at).toBeGreaterThanOrEqual(60_000)
    for (const t of w.toasts) expect(t.text).toContain('PR #418')
  })
}

test('C49 a PR of another author still shows "fail" in the pane', async ($, on) => {
  const w = prWorld(on, [[mine(418, 'pass', { author: 'someone-else' })], [mine(418, 'fail', { author: 'someone-else' })]])
  await w.start($)
  await w.untilPr(2, 10 * 60_000)
  await w.advance(5000)
  expect(w.toasts.length).toBe(0)
  const pane = await w.openPane($, 'terminal', 'pr-radar')
  expect(rowOf(await pane.text(), '#418')).toContain('fail')
})

// --------------------------------------------------------------------------------- C50

test('C50 two PRs flipping in the same cycle -> one toast "PR CHECKS FAILING · 2 PRs"', async ($, on) => {
  const w = prWorld(on, [[mine(418, 'pass'), mine(419, 'pass')], [mine(418, 'fail'), mine(419, 'fail')]])
  await w.start($)
  await w.untilPr(2, 10 * 60_000)
  await w.advance(15_000)
  expect(w.toasts.length).toBe(1)
  expect(w.toasts[0]!.text).toContain('PR CHECKS FAILING · 2 PRs')
  expect(w.toasts[0]!.text).toContain('/prs')
  expect(w.toasts[0]!.text.length).toBeLessThanOrEqual(140)
})

test('C50 a second flip 30 s later is held until 60 s after the first, then shown once', async ($, on) => {
  const w = prWorld(on, [
    [mine(418, 'pass'), mine(419, 'pass')],
    [mine(418, 'fail'), mine(419, 'pass')],
    [mine(418, 'fail'), mine(419, 'fail')],
  ])
  await w.start($)
  await w.untilPr(2, 10 * 60_000)
  await w.advance(2000)
  expect(w.toasts.length).toBe(1)
  const t0 = w.toasts[0]!.at
  await w.advance(Math.max(0, t0 + 30_000 - w.now()))
  await w.cmd($, 'prs', 'refresh')
  await w.settle()
  expect(w.prListCalls().length).toBe(3)
  expect(w.toasts.length).toBe(1)
  await w.advance(Math.max(0, t0 + 55_000 - w.now()))
  expect(w.toasts.length).toBe(1)
  await w.advance(Math.max(0, t0 + 72_000 - w.now()))
  expect(w.toasts.length).toBe(2)
  expect(w.toasts[1]!.text).toContain('PR #419')
  expect(w.toasts[1]!.at - t0).toBeGreaterThanOrEqual(60_000)
  await w.advance(5 * 60_000)
  expect(w.toasts.length).toBe(2)
})

test('C50 awareness.headsup.lastShownAt = now - 20 s defers the toast to now + 40 s', async ($, on) => {
  const w = prWorld(on, [[mine(418, 'pass')], [mine(418, 'fail')]])
  await w.start($)
  await w.untilPr(1, 3 * 60_000)
  await w.advance(20_000)
  const n = w.now()
  w.setPeer('headsup', { lastShownAt: n - 20_000 })
  await w.cmd($, 'prs', 'refresh')
  await w.settle()
  expect(w.prListCalls().length).toBe(2)
  expect(w.toasts.length).toBe(0)
  await w.advance(34_000)
  expect(w.toasts.length).toBe(0)
  await w.advance(14_000)
  expect(w.toasts.length).toBe(1)
  expect(w.toasts[0]!.at).toBeGreaterThanOrEqual(n + 40_000)
})

test('C50 without awareness atoms only the own 60 s limit applies (two flips 3 min apart both toast)', async ($, on) => {
  const w = prWorld(on, [
    [mine(418, 'pass'), mine(419, 'pass')],
    [mine(418, 'fail'), mine(419, 'pass')],
    [mine(418, 'fail'), mine(419, 'fail')],
  ])
  await w.start($)
  await w.untilPr(3, 15 * 60_000)
  await w.advance(15_000)
  expect(w.toasts.length).toBe(2)
})

// --------------------------------------------------------------------------------- C51

test('C51 focus quiet mode: toast held during the block, shown once right after if still failing', async ($, on) => {
  const w = prWorld(on, [[mine(418, 'pass')], [mine(418, 'fail')]])
  await w.start($)
  await w.untilPr(1, 3 * 60_000)
  w.setPeer('focus', { phase: 'focus' })
  await w.untilPr(2, 10 * 60_000)
  await w.advance(5 * 60_000)
  expect(w.toasts.length).toBe(0)
  w.setPeer('focus', { phase: 'idle' })
  await w.advance(15_000)
  expect(w.toasts.length).toBe(1)
  expect(w.toasts[0]!.text).toContain('PR #418')
  await w.advance(5 * 60_000)
  expect(w.toasts.length).toBe(1)
})

test('C51 focus quiet mode: nothing is shown when the PR recovered meanwhile', async ($, on) => {
  const w = prWorld(on, [[mine(418, 'pass')], [mine(418, 'fail')], [mine(418, 'pass')]])
  await w.start($)
  await w.untilPr(1, 3 * 60_000)
  w.setPeer('focus', { phase: 'focus' })
  await w.untilPr(3, 15 * 60_000)
  expect(w.toasts.length).toBe(0)
  w.setPeer('focus', { phase: 'idle' })
  await w.advance(30_000)
  expect(w.toasts.length).toBe(0)
})

test('C51 awareness.headsup.mutedUntil in the future behaves like focus', async ($, on) => {
  const w = prWorld(on, [[mine(418, 'pass')], [mine(418, 'fail')]])
  await w.start($)
  await w.untilPr(1, 3 * 60_000)
  const until = w.now() + 8 * 60_000
  w.setPeer('headsup', { mutedUntil: until })
  await w.untilPr(2, 10 * 60_000)
  await w.advance(60_000)
  expect(w.toasts.length).toBe(0)
  await w.advance(Math.max(0, until - w.now()) + 15_000)
  expect(w.toasts.length).toBe(1)
  expect(w.toasts[0]!.at).toBeGreaterThanOrEqual(until)
})

// --------------------------------------------------------------------------------- C52

const flip = async ($: Any, on: Any, surfaces: string[]): Promise<string> => {
  const w = prWorld(on, [[mine(418, 'pass')], [mine(418, 'fail')]], { surfaces })
  await w.start($)
  await w.untilPr(2, 10 * 60_000)
  await w.advance(15_000)
  expect(w.toasts.length).toBe(1)
  return w.toasts[0]!.text
}

test('C52 surfaces ["desktop"] -> toast text starts with "P" (no glyph)', async ($, on) => {
  const text = await flip($, on, ['desktop'])
  expect(text.startsWith('P')).toBe(true)
  expect(text).toContain('PR #418')
})

test('C52 surfaces ["terminal"] -> toast text starts with the emoji glyph', async ($, on) => {
  const text = await flip($, on, ['terminal'])
  expect(text.startsWith('P')).toBe(false)
  expect(text).toMatch(/^[^\x00-\x7F]/)
  expect(text).toContain('PR #418')
  expect(text.length).toBeLessThanOrEqual(140)
})

test('C52 surfaces ["terminal","desktop"] -> no emoji (a desktop surface is present)', async ($, on) => {
  const text = await flip($, on, ['terminal', 'desktop'])
  expect(text.startsWith('P')).toBe(true)
})
