// Directory tracking in Bash commands (specs/safety.md section 1, "Directory tracking") and exact toast text.
// Session cwd is /work unless stated; /repo, /work, /tmp, /v are real directories for $.fs.stat.
import { test, expect } from 'claude-code/testing'
import { world, assertDeny, ALLOWED_GIT } from './harness'

const W = { cwd: '/work' }

// --- resolved directory shown in deny text and hint -------------------------------------------------
const RESOLVED: [string, string, string?][] = [
  ['cd /repo && echo X >> .env', '/repo/.env'],
  ['cd /repo; echo X > .env', '/repo/.env'],
  ['(cd /repo && echo X > .env)', '/repo/.env'],
  ['cd /repo && cd sub && cd .. && rm .env', '/repo/.env', 'deletes'],
  ['cd /repo && sed -i s/a/b/ yarn.lock', '/repo/yarn.lock'],
  ['cd /repo && mv .env /tmp/x', '/repo/.env', 'moves'],
  ['cd /repo\necho X > .env', '/repo/.env'],
  ['pushd /repo && echo X > .env', '/repo/.env'],
  ['cd /repo && cd && echo X > .env', '/home/u/.env'],
  ['pushd /repo && popd && echo X > .env', '/work/.env'],
  ['git -C /repo rm .env', '/repo/.env', 'deletes'],
]
for (const [cmd, abs, verb] of RESOLVED) {
  test(`CD1 deny names resolved path: ${JSON.stringify(cmd)}`, async ($, on) => {
    const w = world($, on, W)
    const r = await w.bash(cmd)
    assertDeny(r, 'Protected file', abs, `/protect allow ${abs} 10m`)
    if (verb) expect(r.deny).toContain(verb)
    if (abs !== '/work/.env') expect(r.deny).not.toContain('/work/.env')
    expect(r.deny).not.toContain('could not be determined')
    expect(w.wasCalled()).toBe(0)
  })
}

test('CD1 relative cd from the session cwd resolves against it', async ($, on) => {
  const w = world($, on, { cwd: '/repo', dirs: ['/repo/sub'] })
  const r = await w.bash('cd sub && echo X > yarn.lock')
  assertDeny(r, 'Protected file', '/repo/sub/yarn.lock', '/protect allow /repo/sub/yarn.lock 10m')
  expect(w.wasCalled()).toBe(0)
})

// --- scope ----------------------------------------------------------------------------------------------
test('CD2 (cd /repo); echo X > ok.txt is allowed', async ($, on) => {
  const w = world($, on, W)
  expect(w.denied(await w.bash('(cd /repo); echo X > ok.txt'))).toBe(false)
  expect(w.wasCalled()).toBe(1)
})
test('CD2 subshell cd is dropped: (cd /tmp && true); echo X > .env names /work/.env', async ($, on) => {
  const w = world($, on, W)
  const r = await w.bash('(cd /tmp && true); echo X > .env')
  assertDeny(r, 'Protected file', '/work/.env', '/protect allow /work/.env 10m')
  expect(r.deny).not.toContain('/tmp/.env')
  expect(w.wasCalled()).toBe(0)
})
test('CD2 pipeline segment cd is dropped: cd /repo | cat; echo X > .env names /work/.env', async ($, on) => {
  const w = world($, on, W)
  const r = await w.bash('cd /repo | cat; echo X > .env')
  assertDeny(r, 'Protected file', '/work/.env', '/protect allow /work/.env 10m')
  expect(r.deny).not.toContain('/repo/.env')
  expect(w.wasCalled()).toBe(0)
})

// --- allowed --------------------------------------------------------------------------------------------
for (const cmd of ['cd /repo && echo hi > out.txt', 'cd /repo && cat .env', 'cd /repo && echo X > .env.example', 'cd /repo && npm install']) {
  test(`CD3 allowed: ${cmd}`, async ($, on) => {
    const w = world($, on, W)
    const r = await w.bash(cmd)
    expect(w.denied(r)).toBe(false)
    expect(w.wasCalled()).toBe(1)
    expect(r).toEqual({ result: 'ok', text: 'ok' })
  })
}

// --- unknown directory ------------------------------------------------------------------------------------
const UNKNOWN: [string, string][] = [
  ['cd $DIR && echo X > .env', '.env'],
  ['cd - && echo X >> yarn.lock', 'yarn.lock'],
  ['cd `pwd` && echo X > .env', '.env'],
  ['cd /re* && echo X > .env', '.env'],
]
for (const [cmd, file] of UNKNOWN) {
  test(`CD4 unknown directory, target as typed: ${cmd}`, async ($, on) => {
    const w = world($, on, W)
    const r = await w.bash(cmd)
    assertDeny(r, 'Protected file', file, `/protect allow ${file} 10m`, 'directory could not be determined')
    expect(r.deny).not.toContain(`/work/${file}`)
    expect(r.deny).not.toContain(`/repo/${file}`)
    expect(w.wasCalled()).toBe(0)
  })
}
test('CD4 unknown directory, unprotected name is allowed', async ($, on) => {
  const w = world($, on, W)
  expect(w.denied(await w.bash('cd $DIR && echo X > notes.txt'))).toBe(false)
  expect(w.wasCalled()).toBe(1)
})

// --- fail-safe: both directories after ; || newline, new one only after && --------------------------------
test('CD5 cd /nonexistent-looking-dir ; echo X > .env is denied', async ($, on) => {
  const w = world($, on, W)
  expect(w.denied(await w.bash('cd /nonexistent-looking-dir ; echo X > .env'))).toBe(true)
  expect(w.wasCalled()).toBe(0)
})
for (const [sep, denied] of [[';', true], ['||', true], ['\n', true], ['&&', false]] as const) {
  test(`CD5 old dir is checked after ${JSON.stringify(sep)} (cwd rule secrets/**): ${denied ? 'deny' : 'allowed'}`, async ($, on) => {
    const w = world($, on, { ...W, dirs: ['/elsewhere'] })
    await w.cmd('protect', 'add secrets/**')
    const r = await w.bash(`cd /elsewhere${sep === '\n' ? '' : ' '}${sep}${sep === '\n' ? '' : ' '}echo X > secrets/a.txt`)
    expect(w.denied(r)).toBe(denied)
    if (denied) {
      assertDeny(r, 'Protected file', 'secrets/a.txt')
    } else {
      expect(w.wasCalled()).toBe(1)
    }
  })
}
test('CD5 after && an absolute rule on the new directory still denies', async ($, on) => {
  const w = world($, on, { ...W, dirs: ['/elsewhere'] })
  await w.cmd('protect', 'add /elsewhere/secrets/**')
  const r = await w.bash('cd /elsewhere && echo X > secrets/a.txt')
  assertDeny(r, 'Protected file', '/elsewhere/secrets/a.txt')
  expect(w.wasCalled()).toBe(0)
})

// --- vault via cd -----------------------------------------------------------------------------------------
const VAULT: [string, string][] = [
  ['cd /v/Ledger && echo x > 2026.md', '/v/Ledger/2026.md'],
  ['cd ../v/Ledger && echo x > 2026.md', '/v/Ledger/2026.md'],
  ['cd /v && cd Ledger && echo x >> 2026.md', '/v/Ledger/2026.md'],
  ['cd /v/Boards && echo x > Engineering.md', '/v/Boards/Engineering.md'],
  ['cd /v/.obsidian && echo {} > app.json', '/v/.obsidian/app.json'],
  ['(cd /v/Ledger && echo x > 2026.md)', '/v/Ledger/2026.md'],
]
for (const [cmd, abs] of VAULT) {
  test(`CD6 vault via cd denied: ${cmd}`, async ($, on) => {
    const w = world($, on, { ...W, vault: '/v' })
    const r = await w.bash(cmd)
    assertDeny(r, 'Protected file', abs, `/protect allow ${abs} 10m`)
    expect(r.deny).not.toContain('/work/')
    expect(w.wasCalled()).toBe(0)
  })
}
test('CD6 vault note outside protected folders via cd is allowed', async ($, on) => {
  const w = world($, on, { ...W, vault: '/v' })
  expect(w.denied(await w.bash('cd /v/Notes && echo x > a.md'))).toBe(false)
  expect(w.wasCalled()).toBe(1)
})

// --- allowances -------------------------------------------------------------------------------------------
test('CD7 /protect allow /repo/.env 10m allows cd /repo && echo X >> .env, not the cwd .env', async ($, on) => {
  const w = world($, on, W)
  await w.cmd('protect', 'allow /repo/.env 10m')
  expect(w.denied(await w.bash('cd /repo && echo X >> .env'))).toBe(false)
  expect(w.wasCalled()).toBe(1)
  const r = await w.bash('echo X > .env')
  assertDeny(r, 'Protected file', '/work/.env')
  expect(w.wasCalled()).toBe(1)
})
test('CD7 /protect allow .env 10m allows the unknown-dir cd $DIR && echo X > .env', async ($, on) => {
  const w = world($, on, W)
  await w.cmd('protect', 'allow .env 10m')
  expect(w.denied(await w.bash('cd $DIR && echo X > .env'))).toBe(false)
  expect(w.wasCalled()).toBe(1)
})
test('CD7 the allowance hint printed for an unknown dir, once typed, works', async ($, on) => {
  const w = world($, on, W)
  const r = await w.bash('cd - && echo X >> yarn.lock')
  expect(r.deny).toContain('/protect allow yarn.lock 10m')
  await w.cmd('protect', 'allow yarn.lock 10m')
  expect(w.denied(await w.bash('cd - && echo X >> yarn.lock'))).toBe(false)
})

// --- toast text (exact) -----------------------------------------------------------------------------------
const ANY_REASON = /is (a|an) .+\.$|is [A-Z][A-Za-z ]+\.$/

test('T1 Write /repo/.env, cwd /repo, terminal: exact toast', async ($, on) => {
  const w = world($, on, { cwd: '/repo', surfaces: ['terminal'] })
  const r = await w.write('/repo/.env')
  assertDeny(r, '/repo/.env') // model-facing text keeps the absolute path
  expect(w.toasts).toEqual(['⛔ FILE PROTECTED · Edit blocked: .env is a secrets file.'])
  expect(w.toasts[0]).not.toContain('/repo/')
})
test('T1 Write /repo/.env, cwd /repo, desktop: exact toast without emoji', async ($, on) => {
  const w = world($, on, { cwd: '/repo', surfaces: ['desktop'] })
  await w.write('/repo/.env')
  expect(w.toasts).toEqual(['FILE PROTECTED · Edit blocked: .env is a secrets file.'])
})
test('T2 Write /repo/sub/yarn.lock: relative path and lockfile reason', async ($, on) => {
  const w = world($, on, { cwd: '/repo', surfaces: ['desktop'] })
  await w.write('/repo/sub/yarn.lock')
  expect(w.toasts).toEqual(['FILE PROTECTED · Edit blocked: sub/yarn.lock is a managed lockfile.'])
})
test('T3 target outside the cwd shows the absolute path', async ($, on) => {
  const w = world($, on, { cwd: '/repo', surfaces: ['desktop'] })
  await w.write('/other/.env')
  expect(w.toasts).toEqual(['FILE PROTECTED · Edit blocked: /other/.env is a secrets file.'])
})
test('T4 vault groups are relative to the vault root when outside the cwd', async ($, on) => {
  const w = world($, on, { cwd: '/repo', vault: '/v', surfaces: ['desktop'] })
  await w.write('/v/Boards/Engineering.md')
  await w.write('/v/.obsidian/app.json')
  await w.write('/v/Ledger/2026/10.md')
  expect(w.toasts).toEqual([
    'FILE PROTECTED · Edit blocked: Boards/Engineering.md is a generated file.',
    'FILE PROTECTED · Edit blocked: .obsidian/app.json is Obsidian app settings.',
    'FILE PROTECTED · Edit blocked: Ledger/2026/10.md is a protected vault folder.',
  ])
})
test('T5 extra rule toast reads "a protected path"', async ($, on) => {
  const w = world($, on, { cwd: '/repo', surfaces: ['desktop'] })
  await w.cmd('protect', 'add secrets/**')
  await w.write('/repo/secrets/a.txt')
  expect(w.toasts).toEqual(['FILE PROTECTED · Edit blocked: secrets/a.txt is a protected path.'])
})
test('T6 toast from a Bash deny reads like the Write toast', async ($, on) => {
  const w = world($, on, { cwd: '/repo', surfaces: ['desktop'] })
  await w.bash('echo X > .env')
  expect(w.toasts.length).toBe(1)
  expect(w.toasts[0]).toMatch(/^FILE PROTECTED · (Edit|Command) blocked: \.env is a secrets file\.$/)
})
test('T6 toast after cd shows the path relative to the session cwd', async ($, on) => {
  const w = world($, on, { cwd: '/repo', surfaces: ['desktop'], dirs: ['/repo/sub'] })
  await w.bash('cd sub && echo X > yarn.lock')
  expect(w.toasts.length).toBe(1)
  expect(w.toasts[0]).toMatch(/^FILE PROTECTED · (Edit|Command) blocked: sub\/yarn\.lock is a managed lockfile\.$/)
})
test('T7 every deny toast, every group, matches the grammar and never says "is may"', async ($, on) => {
  const w = world($, on, { cwd: '/repo', vault: '/v', surfaces: ['desktop'] })
  await w.cmd('protect', 'add secrets/**')
  const files = ['/repo/.env', '/repo/yarn.lock', '/repo/package-lock.json', '/v/Boards/Engineering.md', '/v/.obsidian/app.json', '/v/Ledger/2026/10.md', '/repo/secrets/a.txt', '/other/.env']
  for (const f of files) await w.write(f)
  expect(w.toasts.length).toBe(files.length)
  for (const t of w.toasts) {
    expect(t).toMatch(ANY_REASON)
    expect(t).not.toContain('is may')
    expect(t).toContain('FILE PROTECTED')
  }
})
