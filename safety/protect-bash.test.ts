import { test, expect } from 'claude-code/testing'
import { world, assertDeny } from './harness'

const DENY10 = [
  'echo X > .env',
  'echo X >> /repo/.env.local',
  'cat a | tee -a package-lock.json',
  "sed -i 's/a/b/' yarn.lock",
  'cp x.txt Cargo.lock',
  'mv uv.lock /tmp/x',
  'rm poetry.lock',
  'dd if=a of=.env',
]
for (const c of DENY10) {
  test(`C10 bash denied: ${c}`, async ($, on) => {
    const w = world($, on)
    const r = await w.bash(c)
    assertDeny(r, 'Protected file', '/protect allow')
    expect(w.wasCalled()).toBe(0)
  })
}

const DENY10A: [string, string, string][] = [
  ['rm -f .env', '/repo/.env', 'deletes'],
  ['rm -rf yarn.lock', '/repo/yarn.lock', 'deletes'],
  ['unlink Cargo.lock', '/repo/Cargo.lock', 'deletes'],
  ['git rm package-lock.json', '/repo/package-lock.json', 'deletes'],
  ['mv .env /tmp/x', '/repo/.env', 'moves'],
  ['mv /tmp/x .env', '/repo/.env', 'moves'],
  ['mv bun.lock bun.lock.old', '/repo/bun.lock', 'moves'],
]
for (const [c, path, verb] of DENY10A) {
  test(`C10a delete/move denied: ${c}`, async ($, on) => {
    const w = world($, on)
    const r = await w.bash(c)
    assertDeny(r, 'Protected file', path, verb, '/protect allow')
    expect(w.wasCalled()).toBe(0)
  })
}
for (const c of ['rm build/out.js', 'mv a.txt b.txt', 'rm -r node_modules']) {
  test(`C10a allowed: ${c}`, async ($, on) => {
    const w = world($, on)
    expect(w.denied(await w.bash(c))).toBe(false)
    expect(w.wasCalled()).toBe(1)
  })
}
test('C10a /protect allow .env 10m then rm .env is allowed within 10 min', async ($, on) => {
  const w = world($, on)
  await w.cmd('protect', 'allow .env 10m')
  expect(w.denied(await w.bash('rm .env'))).toBe(false)
  expect(w.wasCalled()).toBe(1)
})

const ALLOW11 = [
  'npm install', 'pnpm add left-pad', 'cargo update', 'uv lock', 'cat .env', 'grep KEY .env',
  'git checkout -- package-lock.json', 'echo hi > out.txt', `python -c "open('.env','w')"`,
]
for (const c of ALLOW11) {
  test(`C11 bash allowed: ${c}`, async ($, on) => {
    const w = world($, on)
    const r = await w.bash(c)
    expect(w.denied(r)).toBe(false)
    expect(w.wasCalled()).toBe(1)
    expect(r).toEqual({ result: 'ok', text: 'ok' })
  })
}

test('C12 literal protected basename under $DIR is denied', async ($, on) => {
  const w = world($, on)
  expect(w.denied(await w.bash('echo X > "$DIR/.env"'))).toBe(true)
  expect(w.wasCalled()).toBe(0)
})
test('C12 unresolvable $FILE target is allowed', async ($, on) => {
  const w = world($, on)
  expect(w.denied(await w.bash('echo X > "$FILE"'))).toBe(false)
  expect(w.wasCalled()).toBe(1)
})
