import { test, expect } from 'claude-code/testing'
import { world, MIN } from './harness'

test('C13 warn mode: .env write passes, next called, one toast with FILE PROTECTED', { options: { 'protect_mode': 'warn' } }, async ($, on) => {
  const w = world($, on)
  const r = await w.write('/repo/.env')
  expect(w.denied(r)).toBe(false)
  expect(w.wasCalled()).toBe(1)
  expect(w.toasts.length).toBe(1)
  expect(w.toasts[0]).toContain('FILE PROTECTED')
})
test('C13 off mode: no toast, no deny', { options: { 'protect_mode': 'off' } }, async ($, on) => {
  const w = world($, on)
  const r = await w.write('/repo/.env')
  expect(w.denied(r)).toBe(false)
  expect(w.wasCalled()).toBe(1)
  expect(w.toasts.length).toBe(0)
})

for (const surface of ['terminal', 'desktop'] as const) {
  test(`C14 deny toast text and rate limit on ${surface}`, async ($, on) => {
    const w = world($, on, { surfaces: [surface] })
    await w.write('/repo/.env')
    expect(w.toasts.length).toBe(1)
    const t = w.toasts[0]
    expect(t).toContain('FILE PROTECTED')
    expect(t).toContain('.env')
    if (surface === 'desktop') expect(t.startsWith('F')).toBe(true)
    else expect(t.startsWith('F')).toBe(false)
    if (surface === 'terminal') expect(t.startsWith('⛔')).toBe(true)
    await w.write('/repo/.env')
    expect(w.toasts.length).toBe(1) // same path within 30 s
    await w.write('/repo/yarn.lock')
    expect(w.toasts.length).toBe(2) // different path
    expect(w.toasts[1]).toContain('yarn.lock')
  })
}
test('C14 same path again after 30 s toasts again', async ($, on) => {
  const w = world($, on)
  await w.write('/repo/.env')
  await w.clock.advance(31_000)
  await w.write('/repo/.env')
  expect(w.toasts.length).toBe(2)
})

test('C15 allow .env 10m: allowed at +9 min, denied at +11 min', async ($, on) => {
  const w = world($, on)
  await w.cmd('protect', 'allow .env 10m')
  await w.clock.advance(9 * MIN)
  expect(w.denied(await w.write('/repo/.env'))).toBe(false)
  await w.clock.advance(2 * MIN)
  expect(w.denied(await w.write('/repo/.env'))).toBe(true)
})
test('C15 allow with 120m is clamped to 60', async ($, on) => {
  const w = world($, on)
  await w.cmd('protect', 'allow .env 120m')
  await w.clock.advance(59 * MIN)
  expect(w.denied(await w.write('/repo/.env'))).toBe(false)
  await w.clock.advance(2 * MIN)
  expect(w.denied(await w.write('/repo/.env'))).toBe(true)
})
test('C15 /protect list shows allowance and minutes left', async ($, on) => {
  const w = world($, on)
  await w.cmd('protect', 'allow .env 10m')
  await w.clock.advance(3 * MIN)
  const t = await w.cmd('protect', 'list')
  expect(t).toContain('.env')
  expect(t).toMatch(/7\s*(m|min)/)
})
test('C15 allowance gone after a new session.start', async ($, on) => {
  const w = world($, on)
  await w.cmd('protect', 'allow .env 10m')
  await w.start()
  expect(w.denied(await w.write('/repo/.env'))).toBe(true)
})

test('C16 /protect add secrets/** then Write is denied; remove allows it again', async ($, on) => {
  const w = world($, on)
  await w.cmd('protect', 'add secrets/**')
  expect(w.denied(await w.write('/repo/secrets/a.txt'))).toBe(true)
  await w.cmd('protect', 'remove secrets/**')
  expect(w.denied(await w.write('/repo/secrets/a.txt'))).toBe(false)
})
test('C16 removing a default group entry is refused with text "default"', async ($, on) => {
  const w = world($, on)
  const t = await w.cmd('protect', 'remove yarn.lock')
  expect(t).toContain('default')
  expect(w.denied(await w.write('/repo/yarn.lock'))).toBe(true)
})

// Statement 14/spec section 3: /protect status wireframe (extra coverage, same terminal/desktop equality rule)
for (const surface of ['terminal', 'desktop'] as const) {
  test(`C14b /protect status text on ${surface}`, async ($, on) => {
    const w = world($, on, { surfaces: [surface] })
    await w.write('/repo/yarn.lock')
    const t = await w.cmd('protect', 'status')
    expect(t).toContain('PROTECTED FILES')
    expect(t).toContain('deny')
    expect(t).toContain('yarn.lock')
  })
}
