/* eslint-disable @typescript-eslint/no-explicit-any */
import { test, expect } from 'claude-code/testing'
import {
  SURFACES, T0, MIN, HOUR, DAY, SONNET, CACHE_TAX_KEY, CACHE_TAX_SETTINGS, PRICES_SONNET,
  FORK_PLUGIN, rig, usage, formatWhen, localDate, lineWith,
} from './_kit'

const S = (m: number, s = 0) => m * MIN + s * 1000
const HAS_LIMITS = [{ kind: 'five_hour', percentUsed: 10, resetsAt: new Date(T0 + 4 * HOUR).toISOString() }]
const noCountdown = /\d{2}:\d{2}\s+left|\d+h\d{2}m\s+left/

for (const surface of SURFACES) {
  test(`C13 before any request the pane says "No request yet" [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    expect(await r.pane(surface)).toContain('No request yet')
  })

  test(`C13 ttl 1h, 38m12s after a main step: 21:48 and WARM [${surface}]`, { options: { 'cache_ttl': '1h' } }, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.step()
    await r.advance(S(38, 12))
    const p = await r.pane(surface)
    expect(p).toContain('21:48')
    expect(p).toContain('WARM')
  })

  test(`C14 ttl 5m: 00:30 left at 4m30s [${surface}]`, { options: { 'cache_ttl': '5m' } }, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.step()
    await r.advance(S(4, 30))
    expect(await r.pane(surface)).toContain('00:30')
  })

  test(`C14 ttl 5m: COLD and no countdown at 6m [${surface}]`, { options: { 'cache_ttl': '5m' } }, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.step()
    await r.advance(S(6))
    const p = await r.pane(surface)
    expect(p).toContain('COLD')
    expect(p).not.toMatch(noCountdown)
  })

  test(`C15 option ttl 1h: TTL line shows "TTL 1h" [${surface}]`, { options: { 'cache_ttl': '1h' } }, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.step()
    expect(lineWith(await r.pane(surface), 'TTL')).toContain('TTL 1h')
  })

  test(`C15 auto, no cache-tax, subscription limits: ~1h assumed [${surface}]`, async ($, on) => {
    const r = rig($, on, { settings: {}, startRateLimits: HAS_LIMITS as any })
    await r.start()
    await r.measure({ raw: HAS_LIMITS as any })
    await r.step()
    const line = lineWith(await r.pane(surface), 'TTL')
    expect(line).toContain('~1h')
    expect(line).toContain('assumed')
  })

  test(`C15 auto, no cache-tax, rateLimits []: ~5m assumed [${surface}]`, async ($, on) => {
    const r = rig($, on, { settings: {} })
    await r.start()
    await r.measure({ raw: [] })
    await r.step()
    const line = lineWith(await r.pane(surface), 'TTL')
    expect(line).toContain('~5m')
    expect(line).toContain('assumed')
  })

  test(`C15a cache-tax enabled, subscription limits: "TTL 1h (cache-tax)" with no ~ [${surface}]`, async ($, on) => {
    const r = rig($, on, { settings: CACHE_TAX_SETTINGS, startRateLimits: HAS_LIMITS as any })
    await r.start()
    await r.measure({ raw: HAS_LIMITS as any })
    await r.step()
    const line = lineWith(await r.pane(surface), 'TTL')
    expect(line).toMatch(/TTL 1h \(cache-tax\)/)
    expect(line).not.toContain('~')
  })

  test(`C15a cache-tax enabled, rateLimits []: "TTL 1h (cache-tax)" with no ~ [${surface}]`, async ($, on) => {
    const r = rig($, on, { settings: CACHE_TAX_SETTINGS })
    await r.start()
    await r.measure({ raw: [] })
    await r.step()
    const line = lineWith(await r.pane(surface), 'TTL')
    expect(line).toMatch(/TTL 1h \(cache-tax\)/)
    expect(line).not.toContain('~')
  })

  test(`C15a followCacheTax=false falls to the assumed rows [${surface}]`, { options: { 'cache_followCacheTax': false } }, async ($, on) => {
    const r = rig($, on, { settings: CACHE_TAX_SETTINGS })
    await r.start()
    await r.measure({ raw: [] })
    await r.step()
    const line = lineWith(await r.pane(surface), 'TTL')
    expect(line).toContain('~5m')
    expect(line).toContain('assumed')
    expect(line).not.toContain('cache-tax)')
  })

  test(`C15a cache-tax present but disabled behaves as not installed [${surface}]`, async ($, on) => {
    const r = rig($, on, { settings: { enabledPlugins: { [CACHE_TAX_KEY]: false } } })
    await r.start()
    await r.measure({ raw: [] })
    await r.step()
    const line = lineWith(await r.pane(surface), 'TTL')
    expect(line).toContain('~5m')
    expect(line).toContain('assumed')
  })

  test(`C15b pluginConfigs options.ttl "5m" -> "TTL 5m (cache-tax)" [${surface}]`, async ($, on) => {
    const settings = { ...CACHE_TAX_SETTINGS, pluginConfigs: { [CACHE_TAX_KEY]: { options: { ttl: '5m' } } } }
    const r = rig($, on, { settings })
    await r.start()
    await r.step()
    expect(lineWith(await r.pane(surface), 'TTL')).toMatch(/TTL 5m \(cache-tax\)/)
  })

  test(`C15b pluginConfigs options.ttl "90m" is ignored (stays 1h) [${surface}]`, async ($, on) => {
    const settings = { ...CACHE_TAX_SETTINGS, pluginConfigs: { [CACHE_TAX_KEY]: { options: { ttl: '90m' } } } }
    const r = rig($, on, { settings })
    await r.start()
    await r.step()
    expect(lineWith(await r.pane(surface), 'TTL')).toMatch(/TTL 1h \(cache-tax\)/)
  })

  test(`C15c PostModelSwitch cache_ttl 5m beats cache-tax, extra line shown [${surface}]`, async ($, on) => {
    const r = rig($, on, { settings: CACHE_TAX_SETTINGS })
    await r.start()
    await r.step()
    await r.classic('PostModelSwitch', {
      from_model: SONNET, to_model: 'claude-opus-5-5', requested_model: 'opus', source: 'command',
      context_tokens: 100000, prompt_cache_warm: false, cache_ttl: '5m', estimated_cache_write_usd: 0.5, pricing: 'catalog',
    })
    const p = await r.pane(surface)
    const line = lineWith(p, 'TTL')
    expect(line).toContain('TTL 5m')
    expect(line).toContain('event')
    expect(p).toContain('cache-tax assumes 1h')
  })

  test(`C15d model.fork with cache_read 80000: KEEPWARM on, last ping, countdown from the fork [${surface}]`, { plugins: [FORK_PLUGIN] }, async ($, on) => {
    const r = rig($, on, { settings: CACHE_TAX_SETTINGS })
    await r.start()
    await r.fork(usage(80000))
    await r.advance(S(10))
    const p = await r.pane(surface)
    expect(p).toContain('KEEPWARM on')
    expect(p).toContain('last ping')
    expect(p).toContain('50:00') // t + 1h (cache-tax ttl) - 10 min
  })

  test(`C15d no fork and no observed command, cache-tax installed: KEEPWARM unknown [${surface}]`, async ($, on) => {
    const r = rig($, on, { settings: CACHE_TAX_SETTINGS })
    await r.start()
    await r.step()
    expect(await r.pane(surface)).toContain('KEEPWARM unknown')
  })

  test(`C15d observed /keepwarm 2h: KEEPWARM on until t+2h [${surface}]`, async ($, on) => {
    const r = rig($, on, { settings: CACHE_TAX_SETTINGS })
    await r.start()
    await r.step()
    await r.command('keepwarm', '2h')
    const p = await r.pane(surface)
    expect(p).toContain('KEEPWARM on')
    expect(p).toContain(`until ${formatWhen(T0 + 2 * HOUR)}`)
  })

  test(`C15d observed /keepwarm off: KEEPWARM off [${surface}]`, async ($, on) => {
    const r = rig($, on, { settings: CACHE_TAX_SETTINGS })
    await r.start()
    await r.step()
    await r.command('keepwarm', 'off')
    expect(await r.pane(surface)).toContain('KEEPWARM off')
  })

  test(`C15d cache-tax not installed: no KEEPWARM text [${surface}]`, { plugins: [FORK_PLUGIN] }, async ($, on) => {
    const r = rig($, on, { settings: {} })
    await r.start()
    await r.step()
    await r.fork(usage(80000))
    await r.command('keepwarm', '2h')
    expect(await r.pane(surface)).not.toContain('KEEPWARM')
  })
}

test('C15d the keepwarm observer calls next exactly once and returns the beneath result unchanged', async ($, on) => {
  const r = rig($, on, { settings: CACHE_TAX_SETTINGS })
  await r.start()
  const before = r.st.beneathCommandCalls
  const res = await r.command('keepwarm', '90m')
  expect(r.st.beneathCommandCalls - before).toBe(1)
  expect(res.text).toBe('BENEATH-RESULT')
})

for (const surface of SURFACES) {
  test(`C16 a subagent turn.step does not change the countdown [${surface}]`, { options: { 'cache_ttl': '1h' } }, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.step() // main at t0
    await r.advance(S(10))
    await r.step({ agentId: 'agent-1' })
    expect(await r.pane(surface)).toContain('50:00')
  })

  test(`C16 a subagent step alone leaves the clock UNKNOWN [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.step({ agentId: 'agent-1' })
    expect(await r.pane(surface)).toContain('No request yet')
  })

  test(`C17 model.fork with cache_read 80000 at t1 sets lastReq = t1 [${surface}]`, { plugins: [FORK_PLUGIN], options: { 'cache_ttl': '1h' } }, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.step() // t0
    await r.advance(S(20))
    await r.fork(usage(80000)) // t1 = t0 + 20m
    await r.advance(S(5))
    expect(await r.pane(surface)).toContain('55:00')
  })

  test(`C18 session.compact makes the pane COLD; the next main step makes it WARM [${surface}]`, { options: { 'cache_ttl': '1h' } }, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.step()
    await r.compact()
    expect(await r.pane(surface)).toContain('COLD')
    await r.step()
    expect(await r.pane(surface)).toContain('WARM')
  })

  test(`C19 resume with prompt_cache_likely_expired: COLD, 0.42 and est. [${surface}]`, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.classic('SessionStart', {
      source: 'resume', prompt_cache_likely_expired: true, estimated_cache_write_usd: 0.42,
      context_tokens: 100000, seconds_since_last_response: 7200,
    })
    const p = await r.pane(surface)
    expect(p).toContain('COLD')
    expect(p).toContain('0.42')
    expect(p).toContain('est.')
  })

  test(`C20 learning: second step 20 min later re-reads the cache -> learned 1h [${surface}]`, async ($, on) => {
    const r = rig($, on, { settings: {} }) // rateLimits [] would otherwise assume 5m
    await r.start()
    await r.step({ usage: usage(100000, 0) })
    await r.advance(S(20))
    await r.step({ usage: usage(95000, 5000) })
    const line = lineWith(await r.pane(surface), 'TTL')
    expect(line).toContain('~1h')
    expect(line).toContain('learned')
  })

  test(`C20 learning: second step 20 min later re-writes the cache -> learned 5m [${surface}]`, async ($, on) => {
    const r = rig($, on, { settings: {}, startRateLimits: HAS_LIMITS as any }) // subscription would otherwise assume 1h
    await r.start()
    await r.measure({ raw: HAS_LIMITS as any })
    await r.step({ usage: usage(100000, 0) })
    await r.advance(S(20))
    await r.step({ usage: usage(0, 90000) })
    const line = lineWith(await r.pane(surface), 'TTL')
    expect(line).toContain('~5m')
    expect(line).toContain('learned')
  })

  test(`C21 savings = read*(input-cacheRead)/1e6 to 2 decimals [${surface}]`, { options: { pricesJson: PRICES_SONNET, 'cache_ttl': '1h' } }, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.step({ usage: usage(100000, 0), model: SONNET })
    const p = await r.pane(surface)
    expect(p).toContain('Saved by cache today')
    expect(p).toContain('0.27') // 100000 * (3 - 0.3) / 1e6
    expect(p).toContain('estimate (prices as of 2026-10-01, custom)')
  })

  test(`C21 two sessions' keys for the same date are summed [${surface}]`, { options: { pricesJson: PRICES_SONNET, 'cache_ttl': '1h' } }, async ($, on) => {
    const day = localDate(T0)
    const r = rig($, on, { store: { [`cache:day:${day}:other-session`]: { v: 1, saved: 1.5, reads: 1, writes: 0, reqs: 1 } } })
    await r.start()
    await r.step({ usage: usage(100000, 0), model: SONNET })
    const p = await r.pane(surface)
    expect(p).toContain('1.77') // 0.27 + 1.50
  })

  test(`C22 re-cache cost for 200000 context tokens at the 1h write price [${surface}]`, { options: { pricesJson: PRICES_SONNET, 'cache_ttl': '1h' } }, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.measure({ raw: [], context: { tokens: 200000, window: 1_000_000, percent: 20 } })
    await r.step({ usage: usage(0, 0, 200000), model: SONNET })
    await r.advance(2 * HOUR) // cache is cold
    const p = await r.pane(surface)
    expect(p).toContain('COLD')
    expect(p).toContain('~$1.20') // 200000 * 6 / 1e6
  })

  test(`C23 unknown model id: cost is n/a or "(default price)", never throws [${surface}]`, { options: { 'cache_ttl': '1h' } }, async ($, on) => {
    const r = rig($, on)
    await r.start()
    await r.measure({ raw: [], context: { tokens: 200000, window: 1_000_000, percent: 20 } })
    await r.step({ usage: usage(0, 0, 200000), model: 'mystery-model-9' })
    await r.advance(2 * HOUR)
    const p = await r.pane(surface)
    expect(p).toMatch(/n\/a|\(default price\)/)
  })
}

test('C30 mod.cache.enabled=false: no CACHE text and no /cacheclock command', { options: { 'mod_cache_enabled': false } }, async ($, on) => {
  const r = rig($, on)
  await r.start()
  await r.measure({ five: [62, T0 + 2 * HOUR], seven: [71, T0 + 3 * DAY] })
  await r.step()
  for (const surface of SURFACES) {
    const b = await r.band(surface)
    expect(b).toContain('5H') // positive control: band is drawn
    expect(b).not.toContain('CACHE')
  }
  expect(r.st.registered).not.toContain('cacheclock')
  expect(r.st.registered).toContain('burn')
})

test('C30 control: with the cache mod enabled the band shows CACHE and /cacheclock is registered', async ($, on) => {
  const r = rig($, on)
  await r.start()
  await r.step()
  expect(await r.band('terminal')).toContain('CACHE')
  expect(r.st.registered).toContain('cacheclock')
})
