import { test, expect } from 'claude-code/testing'
import { world, assertDeny } from './harness'

test('C01 Write of /repo/.env is denied, next not called', async ($, on) => {
  const w = world($, on)
  const r = await w.write('/repo/.env')
  assertDeny(r, 'Protected file', '/repo/.env', '/protect allow')
  expect(w.wasCalled()).toBe(0)
})

test('C02 .env.local and .env.production are denied', async ($, on) => {
  const w = world($, on)
  for (const p of ['/repo/apps/web/.env.local', '/repo/apps/web/.env.production']) {
    expect(w.denied(await w.edit(p))).toBe(true)
  }
  expect(w.wasCalled()).toBe(0)
})

test('C02 example/sample/template env files are allowed', async ($, on) => {
  const w = world($, on)
  const names = ['.env.example', '.env.sample', '.env.template', '.env.staging.example']
  for (const n of names) expect(w.denied(await w.write('/repo/' + n))).toBe(false)
  expect(w.wasCalled()).toBe(names.length)
})

const LOCKS = ['package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'bun.lock', 'bun.lockb', 'Cargo.lock', 'poetry.lock', 'uv.lock']
for (const name of LOCKS) {
  test(`C03 lockfile ${name} denied in any directory`, async ($, on) => {
    const w = world($, on)
    expect(w.denied(await w.write('/repo/' + name))).toBe(true)
    expect(w.denied(await w.write('/repo/deep/er/' + name))).toBe(true)
    expect(w.wasCalled()).toBe(0)
  })
}
test('C03 near-miss names are allowed', async ($, on) => {
  const w = world($, on)
  expect(w.denied(await w.write('/repo/package-lock.json.bak'))).toBe(false)
  expect(w.denied(await w.write('/repo/my-yarn.lock.md'))).toBe(false)
  expect(w.wasCalled()).toBe(2)
})

test('C04 vault protected paths denied with OBSIDIAN_VAULT_PATH=/v', async ($, on) => {
  const w = world($, on, { vault: '/v' })
  for (const p of ['/v/Boards/Engineering.md', '/v/.obsidian/app.json', '/v/Ledger/2026/10.md']) {
    expect(w.denied(await w.write(p))).toBe(true)
  }
  for (const p of ['/v/Boards/Other.md', '/v/Notes/a.md']) expect(w.denied(await w.write(p))).toBe(false)
  expect(w.wasCalled()).toBe(2)
})

test('C04 vault falls back to ~/second-brain when env unset (HOME mocked)', async ($, on) => {
  const w = world($, on, { vault: null, home: '/home/u' })
  const v = '/home/u/second-brain'
  for (const p of [`${v}/Boards/Engineering.md`, `${v}/.obsidian/app.json`, `${v}/Ledger/2026/10.md`]) {
    expect(w.denied(await w.write(p))).toBe(true)
  }
  for (const p of [`${v}/Boards/Other.md`, `${v}/Notes/a.md`]) expect(w.denied(await w.write(p))).toBe(false)
})

test('C05 NotebookEdit with notebook_path on .env is denied', async ($, on) => {
  const w = world($, on)
  const r = await w.tool({ tool: 'NotebookEdit', notebook_path: '/repo/.env', new_source: 'x', cell_id: 'c' })
  expect(w.denied(r)).toBe(true)
  expect(w.wasCalled()).toBe(0)
})

test('C05 a tool named MultiEdit with file_path yarn.lock is denied', async ($, on) => {
  const w = world($, on)
  const r = await w.tool({ tool: 'MultiEdit', file_path: '/repo/yarn.lock', edits: [] })
  expect(w.denied(r)).toBe(true)
  expect(w.wasCalled()).toBe(0)
})

test('C06 relative .env resolves against cwd /repo in deny text', async ($, on) => {
  const w = world($, on, { cwd: '/repo' })
  assertDeny(await w.write('.env'), '/repo/.env')
})
test('C06 ./sub/../.env is denied', async ($, on) => {
  const w = world($, on, { cwd: '/repo' })
  expect(w.denied(await w.write('./sub/../.env'))).toBe(true)
})

test('C07 symlink whose realPath is .env is denied', async ($, on) => {
  const w = world($, on, { links: { '/repo/notes.txt': '/repo/.env' } })
  expect(w.denied(await w.write('/repo/notes.txt'))).toBe(true)
  expect(w.wasCalled()).toBe(0)
})
test('C07 non-existent /repo/new/.env (parent exists) is denied', async ($, on) => {
  const w = world($, on, { missing: ['/repo/new/.env'] })
  expect(w.denied(await w.write('/repo/new/.env'))).toBe(true)
})

test('C08 /repo/.ENV denied when caseInsensitive true (default)', async ($, on) => {
  const w = world($, on)
  expect(w.denied(await w.write('/repo/.ENV'))).toBe(true)
})
test('C08 /repo/.ENV allowed when caseInsensitive false', { options: { 'protect_caseInsensitive': false } }, async ($, on) => {
  const w = world($, on)
  expect(w.denied(await w.write('/repo/.ENV'))).toBe(false)
  expect(w.wasCalled()).toBe(1)
})

test('C09 subagent call (agentId a1) on .env is denied', async ($, on) => {
  const w = world($, on)
  expect(w.denied(await w.write('/repo/.env', { agentId: 'a1' }))).toBe(true)
  expect(w.wasCalled()).toBe(0)
})

test('C17 group lockfiles=false allows lockfile writes, .env still denied', { options: { 'protect_group_lockfiles': false } }, async ($, on) => {
  const w = world($, on)
  expect(w.denied(await w.write('/repo/yarn.lock'))).toBe(false)
  expect(w.denied(await w.write('/repo/.env'))).toBe(true)
  expect(w.wasCalled()).toBe(1)
})

test('C18 gate error path: literal .env still denied, unrelated edit passes to next', async ($, on) => {
  // Force an internal error in the gate by making $.fs.stat blow up in a way the plugin did not expect.
  const w = world($, on, { statThrows: true })
  expect(w.denied(await w.write('/repo/.env'))).toBe(true)
  const r = await w.write('/repo/a.ts')
  expect(w.denied(r)).toBe(false)
  expect(w.wasCalled()).toBe(1)
})

test('C19 allowed calls return the beneath hook result unaltered', async ($, on) => {
  const w = world($, on)
  const r = await w.write('/repo/src/ok.ts')
  expect(r).toEqual({ result: 'ok', text: 'ok' })
  const r2 = await w.bash('echo hi > out.txt')
  expect(r2).toEqual({ result: 'ok', text: 'ok' })
  expect(w.spy.length).toBe(2)
})

test('C29a MCP write tool is not inspected with default options', async ($, on) => {
  const w = world($, on)
  const r = await w.tool({ tool: 'mcp__desktop-commander__write_file', path: '/repo/.env', content: 'x' })
  expect(w.denied(r)).toBe(false)
  expect(w.wasCalled()).toBe(1)
})
test('C29a MCP write tool denied with protect.mcpRules opt-in', { options: { 'protect_mcpRules': '[{"tool":"mcp__desktop-commander__write_file","arg":"path"}]' } }, async ($, on) => {
  const w = world($, on)
  const r = await w.tool({ tool: 'mcp__desktop-commander__write_file', path: '/repo/.env', content: 'x' })
  expect(w.denied(r)).toBe(true)
  expect(w.wasCalled()).toBe(0)
})
