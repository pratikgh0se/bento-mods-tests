import { test, expect } from 'claude-code/testing'
import { world, fakeDev, T0, VAULT } from './_harness'

// ---- C01 .. C02: context trigger ----
test('C01 context 82% yields one CONTEXT toast <= 140 chars', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.measure({ percent: 82 })
  expect(w.toasts).toHaveLength(1)
  const t = w.toasts[0]!
  expect(t.text).toContain('CONTEXT')
  expect(t.text).toContain('82%')
  expect(t.text.length).toBeLessThanOrEqual(140)
})

test('C01b toast timeoutMs is 6000 (edge cases)', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.measure({ percent: 82 })
  expect(w.toasts[0]?.timeoutMs).toBe(6000)
})

test('C02 context: 83% after 82% shows nothing; 65 then 85 re-arms and toasts again', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.measure({ percent: 82 })
  await w.elapse(1)
  await w.measure({ percent: 83 })
  await w.elapse(61)
  expect(w.toastsLike('CONTEXT')).toHaveLength(1)
  await w.measure({ percent: 65 })
  await w.elapse(1)
  await w.measure({ percent: 85 })
  await w.elapse(61)
  expect(w.toastsLike('CONTEXT')).toHaveLength(2)
})

// ---- C03 .. C05: limiter ----
test('C03 two triggers at t0: context first, bigOutput at t0+60s, only one toast at t0+59s', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.measure({ percent: 85 })
  await w.bigOutput(300000)
  expect(w.toasts).toHaveLength(1)
  expect(w.toasts[0]!.text).toContain('CONTEXT')
  await w.elapse(59)
  expect(w.toasts).toHaveLength(1)
  await w.elapse(2)
  expect(w.toasts).toHaveLength(2)
  expect(w.toasts[1]!.text).toContain('OUTPUT')
  expect(w.toasts[1]!.at - T0).toBeGreaterThanOrEqual(60000)
  expect(w.toasts[1]!.at - w.toasts[0]!.at).toBeGreaterThanOrEqual(60000)
})

test('C03b queued toasts are released by priority (pace p4 before bigOutput p5) regardless of arrival order', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.measure({ percent: 85 }) // shown now (context)
  await w.bigOutput(300000) // queued first
  await w.hotWeekly() // queued second, better priority (context stays armed, no new context toast)
  await w.elapse(61)
  expect(w.toasts).toHaveLength(2)
  expect(w.toasts[1]!.text).toContain('WEEKLY PACE')
  await w.elapse(60)
  expect(w.toasts).toHaveLength(3)
  expect(w.toasts[2]!.text).toContain('OUTPUT')
})

test('C04 several triggers at t0: never two toasts within 60 s, at most 5 in 4 minutes', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.measure({ percent: 85, tokens: 20000, rateLimits: [w.rate('seven_day', 71, 3 * 864e5)] })
  await w.bigOutput(300000)
  await w.spawnAgent({ description: 'x' }) // noModel is off by default: no toast
  await w.elapse(240)
  expect(w.toasts.length).toBeGreaterThanOrEqual(3)
  expect(w.toasts.length).toBeLessThanOrEqual(5)
  for (let i = 1; i < w.toasts.length; i++) {
    expect(w.toasts[i]!.at - w.toasts[i - 1]!.at).toBeGreaterThanOrEqual(60000)
  }
})

test('C04b with noModel on: four triggers at t0, still never two within 60 s', { options: { 'headsup_trigger_noModel': true } }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.measure({ percent: 85, tokens: 20000, rateLimits: [w.rate('seven_day', 71, 3 * 864e5)] })
  await w.bigOutput(300000)
  await w.spawnAgent({ description: 'Review the diff' })
  await w.elapse(240)
  expect(w.toasts.length).toBe(4)
  for (let i = 1; i < w.toasts.length; i++) {
    expect(w.toasts[i]!.at - w.toasts[i - 1]!.at).toBeGreaterThanOrEqual(60000)
  }
})

test('C05 a queued trigger whose condition cleared is not shown', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.bigOutput(300000) // shown now
  await w.measure({ percent: 85 }) // queued (gap)
  expect(w.toasts).toHaveLength(1)
  await w.elapse(10)
  await w.measure({ percent: 60 }) // condition cleared
  await w.elapse(120)
  expect(w.toastsLike('CONTEXT')).toHaveLength(0)
  expect(w.toasts).toHaveLength(1)
})

// ---- C06: pace ----
test('C06 weekly HOT toasts WEEKLY PACE + HOT', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.hotWeekly()
  const t = w.toastsLike('WEEKLY PACE')
  expect(t).toHaveLength(1)
  expect(t[0]!.text).toContain('HOT')
})

test('C06b weekly ON PACE shows nothing', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  // p=40, 4 of 7 days elapsed -> projected ~70% (between plentyBelow 60 and hotAt 100)
  await w.measure({ percent: 10, tokens: 20000, rateLimits: [w.rate('seven_day', 40, 3 * 864e5)] })
  await w.elapse(120)
  expect(w.toasts).toHaveLength(0)
})

test('C06c five_hour HOT only shows nothing by default (pace.five off)', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  // five_hour p=30 resets in 4h -> HOT; seven_day tiny
  await w.measure({ percent: 10, tokens: 20000, rateLimits: [w.rate('five_hour', 30, 4 * 3600e3), w.rate('seven_day', 5, 3 * 864e5)] })
  await w.elapse(120)
  expect(w.toasts).toHaveLength(0)
})

// ---- C07: cache ----
const cacheStart = async (w: Awaited<ReturnType<typeof world>>, ctxTokens: number, running: boolean): Promise<void> => {
  await w.measure({ percent: 12, tokens: ctxTokens, window: 1_000_000 })
  await w.turnStart()
  await w.step({ answer: '', toolUses: [] })
  if (!running) await w.turnComplete()
}

test('C07 cache: toast CACHE + 60 S near expiry, none at +3500 s, fired once', { options: { 'cache_ttl': '1h' }, timeoutMs: 120000 }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await cacheStart(w, 120000, false)
  await w.elapse(3500)
  expect(w.toasts).toHaveLength(0)
  await w.elapse(45) // t0+3545 s (5 s slack for timer alignment, see ambiguities)
  const c = w.toastsLike('CACHE')
  expect(c).toHaveLength(1)
  expect(c[0]!.text).toContain('60 S')
  expect(c[0]!.text.length).toBeLessThanOrEqual(140)
  await w.elapse(120)
  expect(w.toastsLike('CACHE')).toHaveLength(1)
})

test('C07b cache: no toast while a turn is running', { options: { 'cache_ttl': '1h' }, timeoutMs: 120000 }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await cacheStart(w, 120000, true)
  await w.elapse(3560)
  expect(w.toastsLike('CACHE')).toHaveLength(0)
})

test('C07c cache: no toast with context 30000 tokens (< 50000)', { options: { 'cache_ttl': '1h' }, timeoutMs: 120000 }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await cacheStart(w, 30000, false)
  await w.elapse(3560)
  expect(w.toastsLike('CACHE')).toHaveLength(0)
})

// ---- C08: bigOutput ----
test('C08 main-thread Bash persistedOutputSize 300000 -> OUTPUT 300 KB toast', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.bigOutput(300000)
  const t = w.toastsLike('OUTPUT')
  expect(t).toHaveLength(1)
  expect(t[0]!.text).toContain('300 KB')
})

test('C08b same result from a subagent (agentId set) -> no toast', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.bigOutput(300000, { agentId: 'agent-1' })
  await w.elapse(120)
  expect(w.toasts).toHaveLength(0)
})

// ---- C09 / C10: long command ----
test('C09 npm test --token=SECRET123 for 130 s: toast at 120 s with COMMAND + npm, never the arguments; result unchanged', { timeoutMs: 120000 }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  const out = { stdout: 'ok', stderr: '', interrupted: false }
  const p = w.bash('npm test --token=SECRET123', { delayMs: 130000, result: out })
  await w.clock.settle()
  await w.elapse(119)
  expect(w.toasts).toHaveLength(0)
  await w.elapse(2)
  const t = w.toastsLike('COMMAND')
  expect(t).toHaveLength(1)
  expect(t[0]!.text).toContain('npm')
  await w.elapse(15)
  const res = await p
  expect(res.result).toEqual(out)
  await w.elapse(300)
  for (const x of w.toastTexts()) {
    expect(x).not.toContain('SECRET123')
    expect(x).not.toContain('--token')
  }
})

test('C09b finished long command raises COMMAND DONE with mm:ss (spec section 1.2)', { timeoutMs: 120000 }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  const p = w.bash('npm test --token=SECRET123', { delayMs: 130000 })
  await w.clock.settle()
  await w.elapse(131)
  await p
  await w.elapse(120)
  const done = w.toasts.find((t) => t.text.includes('DONE'))
  expect(done).toBeDefined()
  expect(done!.text).toContain('npm')
  expect(done!.text).toContain('02:10')
})

test('C09c a 30 s command raises no toast', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  const p = w.bash('npm test', { delayMs: 30000 })
  await w.clock.settle()
  await w.elapse(31)
  await p
  await w.elapse(300)
  expect(w.toasts).toHaveLength(0)
})

test('C10 Bash run_in_background:true gives no toast', { timeoutMs: 120000 }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  const p = w.bash('npm run dev', { input: { run_in_background: true }, delayMs: 130000 })
  await w.clock.settle()
  await w.elapse(200)
  await p
  expect(w.toasts).toHaveLength(0)
})

test('C10b Bash result with backgroundTaskId gives no toast', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.bash('npm run dev', { result: { stdout: '', stderr: '', interrupted: false, backgroundTaskId: 'bg1' } })
  await w.elapse(200)
  expect(w.toasts).toHaveLength(0)
})

// ---- C11: ollama ----
test('C11 no OBSIDIAN_VAULT_PATH: zero http.fetch calls', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.elapse(20 * 60)
  expect(w.http.calls).toBe(0)
  expect(w.toasts).toHaveLength(0)
})

test('C11b vault set, fetch failing twice 5 min apart -> KEYWORD ONLY; up then down again -> second toast', { timeoutMs: 120000 }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'], env: { OBSIDIAN_VAULT_PATH: VAULT }, start: false })
  w.dirs.add(VAULT)
  w.http.up = false
  await w.start()
  await w.elapse(11 * 60)
  expect(w.http.calls + w.curl.calls).toBeGreaterThanOrEqual(2)
  expect(w.toastsLike('KEYWORD ONLY')).toHaveLength(1)
  w.http.up = true
  await w.elapse(6 * 60)
  w.http.up = false
  await w.elapse(11 * 60)
  expect(w.toastsLike('KEYWORD ONLY')).toHaveLength(2)
})

// ---- C12: noModel ----
test('C12 agent without model: default options -> no toast', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.spawnAgent({ description: 'Review the diff' })
  await w.elapse(120)
  expect(w.toasts).toHaveLength(0)
})

test('C12b noModel on: toast with NO MODEL SET and description', { options: { 'headsup_trigger_noModel': true } }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.spawnAgent({ description: 'Review the diff' })
  const t = w.toastsLike('NO MODEL SET')
  expect(t).toHaveLength(1)
  expect(t[0]!.text).toContain('Review the diff')
})

test('C12c noModel on: model haiku, fork type, or savvy-* type -> none', { options: { 'headsup_trigger_noModel': true } }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.spawnAgent({ description: 'a', model: 'haiku' })
  await w.spawnAgent({ description: 'b', subagentType: 'fork' })
  await w.spawnAgent({ description: 'c', subagentType: 'savvy-light' })
  await w.spawnAgent({ description: 'd', subagentType: 'savvy-flow:savvy-light' })
  await w.elapse(120)
  expect(w.toasts).toHaveLength(0)
})

// ---- C13: glyph policy ----
const startsWithEmoji = /^\p{Extended_Pictographic}/u
test('C13 surfaces [terminal]: toast starts with an emoji', async ($, on) => {
  const w = await world($, on, { surfaces: ['terminal'] })
  await w.measure({ percent: 82 })
  expect(w.toasts).toHaveLength(1)
  expect(w.toasts[0]!.text).toMatch(startsWithEmoji)
})
test('C13b surfaces [desktop]: toast starts with A-Z', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.measure({ percent: 82 })
  expect(w.toasts).toHaveLength(1)
  expect(w.toasts[0]!.text).toMatch(/^[A-Z]/)
})
test('C13c surfaces [terminal, desktop]: toast starts with A-Z', async ($, on) => {
  const w = await world($, on, { surfaces: ['terminal', 'desktop'] })
  await w.measure({ percent: 82 })
  expect(w.toasts).toHaveLength(1)
  expect(w.toasts[0]!.text).toMatch(/^[A-Z]/)
})

// ---- C14: mute ----
test('C14 /headsup mute 30m silences triggers; status contains muted', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.cmd('headsup', 'mute 30m')
  await w.measure({ percent: 85 })
  await w.bigOutput(300000)
  await w.elapse(20 * 60)
  expect(w.toasts).toHaveLength(0)
  expect((await w.cmd('headsup', 'status')).toLowerCase()).toContain('muted')
})

test('C14b unmute restores toasts', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.cmd('headsup', 'mute 30m')
  await w.cmd('headsup', 'unmute')
  await w.measure({ percent: 85 })
  expect(w.toastsLike('CONTEXT')).toHaveLength(1)
})

// ---- C31: peer gap ----
test('C31 dev.toast.lastShownAt = now-10s: Heads-Up waits until now+50s', { plugins: [fakeDev] }, async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.cmd('devfake', '10000')
  await w.measure({ percent: 85 })
  expect(w.toasts).toHaveLength(0)
  await w.elapse(49)
  expect(w.toasts).toHaveLength(0)
  await w.elapse(2)
  expect(w.toastsLike('CONTEXT')).toHaveLength(1)
})

test('C31b absent dev atom changes nothing; headsup.lastShownAt updated on every shown toast', async ($, on) => {
  const w = await world($, on, { surfaces: ['desktop'] })
  await w.measure({ percent: 85 })
  expect(w.toasts).toHaveLength(1)
  const first = w.toasts[0]!.at
  expect((await w.state('headsup')).lastShownAt).toBe(first)
  await w.bigOutput(300000)
  await w.elapse(61)
  expect(w.toasts).toHaveLength(2)
  expect((await w.state('headsup')).lastShownAt).toBe(w.toasts[1]!.at)
})
