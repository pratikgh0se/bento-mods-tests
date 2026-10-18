// Contract statements C01-C04 (Git chip). Source: specs/dev.md section 13 "Git".
import { test, expect } from 'claude-code/testing'
import { SURFACES, world, porcelain, crossCheck } from './_harness'

for (const surface of SURFACES) {
  test(`C01 git chip shows branch*, ahead, staged, unstaged, untracked [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    w.gitStatusOut = porcelain({ head: 'main', upstream: 'origin/main', ab: [2, 0], staged: 3, unstaged: 5, untracked: 1 })
    await w.start($, surface)
    const text = await w.band($, surface)
    expect(text).toContain('main*')
    expect(text).toContain('↑2')
    expect(text).toContain('+3')
    expect(text).toContain('~5')
    expect(text).toContain('?1')
    crossCheck('C01', surface, text)
  })

  test(`C01 no upstream line -> no ahead/behind arrows [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    w.gitStatusOut = porcelain({ head: 'main', staged: 3, unstaged: 5, untracked: 1 })
    await w.start($, surface)
    const text = await w.band($, surface)
    expect(text).toContain('main*')
    expect(text).not.toContain('↑')
    expect(text).not.toContain('↓')
    crossCheck('C01b', surface, text)
  })

  test(`C02 detached head shows HEAD@abc1234 [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    w.gitStatusOut = porcelain({ detached: true, oid: 'abc1234def5678abc1234def5678abc1234def56', unstaged: 1 })
    await w.start($, surface)
    const text = await w.band($, surface)
    expect(text).toContain('HEAD@abc1234')
    crossCheck('C02', surface, text)
  })

  test(`C03 linked worktree (git-dir != git-common-dir) shows "wt auth-flow" [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface], top: '/work/wt/auth-flow', branch: 'auth-flow', linkedWorktree: true })
    w.gitStatusOut = porcelain({ head: 'auth-flow', unstaged: 1 })
    await w.start($, surface)
    const text = await w.band($, surface)
    expect(text).toContain('wt auth-flow')
    crossCheck('C03', surface, text)
  })
}

test('C03 main worktree (git-dir == git-common-dir) shows no "wt " marker', async ($, on) => {
  const w = world(on, { surfaces: ['terminal'] })
  w.gitStatusOut = porcelain({ head: 'main', unstaged: 1 })
  await w.start($, 'terminal')
  const text = await w.band($, 'terminal')
  expect(text).toContain('main*')
  expect(text).not.toContain('wt ')
})

test('C04 a Bash result with gitOperation.commit triggers a refresh within 5 s', async ($, on) => {
  const w = world(on)
  w.gitStatusOut = porcelain({ head: 'main', unstaged: 1 })
  await w.start($)
  await w.advance(30_000) // clear any min-refresh window after start
  const before = w.gitStatusCalls().length
  await w.bash($, 'git commit -m "x"', '[main abc1234] x\n', { gitOperation: { commit: { sha: 'abc1234', kind: 'committed', branch: 'main' } } })
  await w.advance(5000)
  expect(w.gitStatusCalls().length).toBe(before + 1)
})

test('C04 two triggers within 5 s cause exactly one git status call', async ($, on) => {
  const w = world(on)
  w.gitStatusOut = porcelain({ head: 'main', unstaged: 1 })
  await w.start($)
  await w.advance(30_000)
  const before = w.gitStatusCalls().length
  const op = { commit: { sha: 'abc1234', kind: 'committed', branch: 'main' } }
  await w.bash($, 'git commit -m "one"', '[main abc1234] one\n', { gitOperation: op })
  await w.advance(1000)
  await w.bash($, 'git commit -m "two"', '[main abc1235] two\n', { gitOperation: op })
  await w.advance(10_000)
  expect(w.gitStatusCalls().length).toBe(before + 1)
})
