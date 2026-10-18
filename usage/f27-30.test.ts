/* eslint-disable @typescript-eslint/no-explicit-any */
// Cases 25-39 (fix round F27-F30), written from specs/usage.md (s2 F27/F28/F29, s4 F30) and 00-conventions s4 only.
// Numbering follows the brief files: 25-27 pane, 28-32 band, 33-36 update points, 37-39 status.
import { test, expect } from 'claude-code/testing'
import {
  T0, MIN, HOUR, CACHE_TAX_SETTINGS, PRICES_SONNET,
  rig, usage, textOf, norm, cellWidth, textNodes, walk,
} from './_kit'

const S = (m: number, s = 0) => m * MIN + s * 1000
const countdown = /(\d{2}:\d{2}|\d+h\d{2}m)\s+left/

// ---------------------------------------------------------------- F27 pane never truncates (25-27)
async function warmWithHitRatio(r: ReturnType<typeof rig>) {
  await r.start()
  await r.measure({ five: [10, T0 + 4 * HOUR] })
  await r.step({ usage: usage(50000, 1000, 100, 100) })
  await r.advance(S(1))
  await r.step({ usage: usage(60000, 1000, 100, 100) })
  await r.advance(S(1))
}
const paneOpts = { settings: CACHE_TAX_SETTINGS }

for (const cols of [30, 40, 58, 80]) {
  test(`C25 pane at ${cols} columns keeps every fact in full and has no ellipsis`, { options: { pricesJson: PRICES_SONNET } }, async ($, on) => {
    const r = rig($, on, paneOpts)
    await warmWithHitRatio(r)
    const { tree } = await r.mountAt('pane', 'terminal', cols)
    const joined = textNodes(tree).map(textOf).join('\n')
    expect(joined).toContain('hit ratio')
    expect(joined).toContain('(last 20)')
    expect(joined).toContain('estimate (prices as of')
    expect(joined).toContain('(cache-tax)')
    expect(joined).not.toContain('…')
    expect(joined).not.toContain('...')
  })
}

test('C26 no Text node in the pane is set to truncate', { options: { pricesJson: PRICES_SONNET } }, async ($, on) => {
  const r = rig($, on, paneOpts)
  await warmWithHitRatio(r)
  for (const cols of [30, 58, 120]) {
    const { tree } = await r.mountAt('pane', 'terminal', cols)
    const texts = textNodes(tree)
    expect(texts.length).toBeGreaterThan(3) // positive control: the pane drew Text
    for (const t of texts) {
      const w = t.props?.wrap
      expect(w === 'truncate-end' || w === 'truncate').toBe(false)
    }
  }
})

/** Chain of nodes from the root to the first Text whose text contains `needle`. */
function pathTo(node: any, needle: string, acc: any[] = []): any[] | null {
  if (node === null || node === undefined || typeof node !== 'object') return null
  if (Array.isArray(node)) {
    for (const n of node) {
      const p = pathTo(n, needle, acc)
      if (p) return p
    }
    return null
  }
  const here = [...acc, node]
  if (node.type === 'Text' && textOf(node).includes(needle)) return here
  const raw = node.children ?? node.props?.children
  const kids = Array.isArray(raw) ? raw : raw === undefined || raw === null ? [] : [raw]
  for (const k of kids) {
    const p = pathTo(k, needle, here)
    if (p) return p
  }
  return null
}
/** True when the two parts are laid out so that they can sit on different lines: different Text nodes whose
 *  nearest common container stacks (column) or wraps, or one Text holding a line break between them. */
function canWrapApart(tree: any, left: string, right: string): boolean {
  const a = pathTo(tree, left)
  const b = pathTo(tree, right)
  if (!a || !b) return false
  const ta = a[a.length - 1]
  const tb = b[b.length - 1]
  if (ta === tb) {
    const s = textOf(ta)
    return s.indexOf('\n', s.indexOf(left)) !== -1 && s.indexOf('\n', s.indexOf(left)) < s.indexOf(right)
  }
  let i = 0
  while (i < a.length && i < b.length && a[i] === b[i]) i++
  const lca = a[i - 1]
  const dir = lca?.props?.flexDirection
  const wrap = lca?.props?.flexWrap
  return dir === 'column' || dir === 'column-reverse' || wrap === 'wrap' || wrap === 'wrap-reverse'
}

const PAIRS: [string, string][] = [
  ['CACHE CLOCK', 'TTL'],
  ['Saved by cache today', 'hit ratio'],
  ['Cold writes this session', 'estimate (prices as of'],
]
test('C27 at 30 columns the right parts wrap away from the left parts; at 120 both parts are present', { options: { pricesJson: PRICES_SONNET } }, async ($, on) => {
  const r = rig($, on, paneOpts)
  await warmWithHitRatio(r)
  const narrow = (await r.mountAt('pane', 'terminal', 30)).tree
  for (const [l, rt] of PAIRS) {
    expect(pathTo(narrow, l), `left part "${l}" present`).not.toBeNull()
    expect(pathTo(narrow, rt), `right part "${rt}" present`).not.toBeNull()
    expect(canWrapApart(narrow, l, rt), `"${rt}" can leave the row of "${l}" at 30 columns`).toBe(true)
  }
  const wide = (await r.mountAt('pane', 'terminal', 120)).tree
  for (const [l, rt] of PAIRS) {
    expect(pathTo(wide, l)).not.toBeNull()
    expect(pathTo(wide, rt)).not.toBeNull()
  }
})

// ---------------------------------------------------------------- F28 band bottom row (28-32)
async function warmBand(r: ReturnType<typeof rig>) {
  await r.start()
  await r.measure({ five: [2], seven: [68] })
  await r.step()
}

test('C28 120 columns, warm cache: the band shows 5H, 7D and CACHE', { options: { cache_ttl: '1h' } }, async ($, on) => {
  const r = rig($, on)
  await warmBand(r)
  const t = (await r.mountAt('band', 'terminal', 120)).text
  expect(t).toContain('5H')
  expect(t).toContain('7D')
  expect(t).toContain('CACHE')
})

test('C29 120 columns on desktop: Svg alt equals the terminal text', { options: { cache_ttl: '1h' } }, async ($, on) => {
  const r = rig($, on)
  await warmBand(r)
  const term = (await r.mountAt('band', 'terminal', 120)).text
  const desk = (await r.mountAt('band', 'desktop', 120)).text
  const chip = (s: string) => s.replace(/🔥 HOT|RUNNING HOT|🧊 PLENTY|PLENTY LEFT/g, '<chip>').replace(/\s+/g, ' ').trim()
  expect(term).toContain('CACHE')
  expect(chip(desk)).toBe(chip(term))
})

/** Segment groups of a desktop band Svg, split by their `translate(X,0)` offset. A slot runs from its X to the
 *  next group's X minus the 12 px gap (the last: to the Svg width). */
type Group = { x: number; end: number; body: string; texts: { x: number; s: string }[]; images: { x: number; w: number }[] }
function svgGroups(source: string, width: number): Group[] {
  const marks = [...source.matchAll(/translate\(\s*(-?[\d.]+)\s*[, ]\s*0(?:\.0+)?\s*\)/g)].map(m => ({ x: Number(m[1]), at: m.index ?? 0 }))
  return marks.map((m, i) => {
    const body = source.slice(m.at, i + 1 < marks.length ? marks[i + 1].at : source.length)
    const texts: Group['texts'] = []
    for (const t of body.matchAll(/<text\b([^>]*)>([\s\S]*?)<\/text>/g)) {
      const x = /\bx="(-?[\d.]+)"/.exec(t[1])
      const s = t[2].replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim()
      if (s) texts.push({ x: x ? Number(x[1]) : 0, s })
    }
    const images: Group['images'] = []
    for (const im of body.matchAll(/<image\b([^>]*)>/g)) {
      const x = /\bx="(-?[\d.]+)"/.exec(im[1])
      const w = /\bwidth="([\d.]+)"/.exec(im[1])
      images.push({ x: x ? Number(x[1]) : 0, w: w ? Number(w[1]) : 0 })
    }
    return { x: m.x, end: i + 1 < marks.length ? marks[i + 1].x - 12 : width, body, texts, images }
  })
}
function svgWidth(s: any): number {
  const source = String(s.props?.source ?? '')
  return Number(s.props?.width ?? /<svg\b[^>]*\bwidth="([\d.]+)"/.exec(source)?.[1] ?? NaN)
}
/** Problems found in one band Svg: every text and image must end inside its own slot. */
function clipProblems(s: any): { problems: string[]; groups: Group[] } {
  const w = svgWidth(s)
  const groups = svgGroups(String(s.props?.source ?? ''), w)
  const problems: string[] = []
  for (const g of groups) {
    for (const t of g.texts) {
      const right = g.x + t.x + 6 * [...t.s].length
      if (right > g.end) problems.push(`"${t.s}" ends at ${right}, slot ends at ${g.end}`)
    }
    for (const im of g.images) {
      if (g.x + im.x + im.w > g.end) problems.push(`mascot ends at ${g.x + im.x + im.w}, slot ends at ${g.end}`)
    }
  }
  return { problems, groups }
}

test('C30 warm 59:18 left, columns 20..160: no text or mascot leaves its own slot; the tiny last chip is exercised', { options: { cache_ttl: '1h' } }, async ($, on) => {
  const r = rig($, on)
  await warmBand(r)
  await r.advance(S(0, 42)) // 59:18 left
  let exercised = 0 // widths where a group shows 59:18
  let tinyLast = 0 // ... as the LAST group and tiny (countdown without the word CACHE)
  const bad: string[] = []
  for (let cols = 20; cols <= 160; cols += 2) {
    const { tree } = await r.mountAt('band', 'desktop', cols)
    for (const s of walk(tree).filter(n => n.type === 'Svg')) {
      const { problems, groups } = clipProblems(s)
      for (const p of problems) bad.push(`${cols} columns: ${p}`)
      const gi = groups.findIndex(g => g.texts.some(t => t.s.includes('59:18')))
      if (gi >= 0) {
        exercised++
        if (gi === groups.length - 1 && !groups[gi].texts.some(t => t.s.includes('CACHE'))) tinyLast++
      }
    }
  }
  expect(bad).toEqual([])
  expect(exercised).toBeGreaterThan(5)
  expect(tinyLast).toBeGreaterThan(0)
})

test('C30 cold, columns 20..160: `Z z` and the word cold sit inside the chip slot', { options: { cache_ttl: '1h' } }, async ($, on) => {
  const r = rig($, on)
  await warmBand(r)
  await r.compact()
  await r.advance(S(1, 5)) // the COMPACTED chip (60 s) is gone; the cache chip is the cold one
  let exercised = 0
  const bad: string[] = []
  for (let cols = 20; cols <= 160; cols += 2) {
    const { tree } = await r.mountAt('band', 'desktop', cols)
    for (const s of walk(tree).filter(n => n.type === 'Svg')) {
      const { problems, groups } = clipProblems(s)
      for (const p of problems) bad.push(`${cols} columns: ${p}`)
      if (groups.some(g => g.texts.some(t => t.s.includes('cold')))) exercised++
    }
  }
  expect(bad).toEqual([])
  expect(exercised).toBeGreaterThan(5)
})

test('C31 60 columns, cold: the band says cold', { options: { cache_ttl: '1h' } }, async ($, on) => {
  const r = rig($, on)
  await warmBand(r)
  await r.compact()
  const term = (await r.mountAt('band', 'terminal', 60)).text
  expect(term).toContain('cold')
  expect((await r.mountAt('band', 'desktop', 60)).text).toContain('cold')
})

for (const state of ['warm', 'cold'] as const) {
  test(`C32 composeRow invariant via the band: terminal text never exceeds the columns, 20..160 [${state}]`, { options: { cache_ttl: '1h' } }, async ($, on) => {
    const r = rig($, on)
    await warmBand(r)
    if (state === 'cold') await r.compact()
    expect(norm((await r.mountAt('band', 'terminal', 120)).text)).toContain('5H') // positive control
    for (let cols = 20; cols <= 160; cols += 2) {
      const { text } = await r.mountAt('band', 'terminal', cols)
      for (const line of text.split('\n')) expect(cellWidth(line), `${cols} columns: "${line}"`).toBeLessThanOrEqual(cols)
    }
  })
}

// ---------------------------------------------------------------- F29 update points (33-36), retained mounts
// Harness: `r.retained('pane'|'band', surface, columns)` mounts ONCE and never re-mounts. The host re-draws it
// only when a plugin invalidates it (an atom write or a tick); `.text()` flushes pending work and returns the
// LAST draw, so a missing invalidation leaves a stale draw. `r.atom()` is the last published `cache` atom of
// usage, `r.atomMarker()/r.atomsSince()` count atom writes after a marker. `.draws` counts Pane draws.
const stateOf = (a: any) => String(a?.state ?? a?.cache?.state ?? '')

test('C33 retained: cold after compact, then a main step held open: WARM, countdown, atom warm and changed, with no tick', { options: { cache_ttl: '1h' } }, async ($, on) => {
  const r = rig($, on)
  await warmBand(r)
  const pane = await r.retained('pane', 'terminal', 100)
  const band = await r.retained('band', 'terminal', 120)
  expect(await pane.text()).toContain('WARM') // control: the mount drew the warm state
  await r.compact()
  expect(await pane.text()).toContain('COLD')
  expect(stateOf(r.atom())).toBe('cold')
  const marker = r.atomMarker()
  const t = r.now()
  const release = r.holdSteps()
  const n0 = r.st.stepLog.length
  const run = r.startStep()
  await r.advance(0) // no tick, no clock movement
  expect(r.st.stepLog.length).toBe(n0 + 1) // the step is in flight
  expect(r.now()).toBe(t)
  const p = await pane.text()
  expect(p).toContain('WARM')
  expect(p).not.toContain('COLD')
  expect(p).toMatch(countdown)
  const b = await band.text()
  expect(b).toMatch(/\d{2}:\d{2}|\d+h\d{2}m/)
  expect(b.toLowerCase()).not.toContain('cold')
  expect(stateOf(r.atom())).toBe('warm')
  expect(r.atomsSince(marker).length).toBeGreaterThan(0)
  release()
  await run.done
  await r.clock.settle()
  expect(await pane.text()).toContain('WARM')
})

test('C34 retained: cold, then a subagent step held open: the pane stays COLD and no atom it reads changes', { options: { cache_ttl: '1h' } }, async ($, on) => {
  const r = rig($, on)
  await warmBand(r)
  await r.compact()
  const pane = await r.retained('pane', 'terminal', 100)
  expect(await pane.text()).toContain('COLD')
  const marker = r.atomMarker()
  const release = r.holdSteps()
  const n0 = r.st.stepLog.length
  const run = r.startStep({ agentId: 'agent-1' })
  await r.advance(0)
  expect(r.st.stepLog.length).toBe(n0 + 1) // in flight
  const mid = await pane.text()
  expect(mid).toContain('COLD')
  expect(mid).not.toContain('WARM')
  expect(stateOf(r.atom())).toBe('cold')
  expect(r.atomsSince(marker).filter(a => a.key === 'cache')).toEqual([])
  release()
  await run.done
  await r.clock.settle()
  expect(await pane.text()).toContain('COLD')
})

test('C35 retained: cold write turn is WARM from the step start, and after turn.complete: one cold write, ~$ above 0', { options: { cache_ttl: '1h', pricesJson: PRICES_SONNET } }, async ($, on) => {
  const r = rig($, on)
  await warmBand(r)
  await r.compact()
  const pane = await r.retained('pane', 'terminal', 100)
  expect(await pane.text()).toContain('COLD')
  const u = usage(0, 316000, 100, 100)
  const release = r.holdSteps()
  const run = r.startStep({ usage: u })
  await r.advance(0)
  const mid = await pane.text()
  expect(mid).toContain('WARM') // already warm before the step ends
  expect(mid).not.toContain('COLD')
  expect(stateOf(r.atom())).toBe('warm') // the published atom agrees before the step ends
  release()
  await run.done
  await r.clock.settle()
  await r.complete({ usage: u })
  const p = await pane.text()
  expect(p).toContain('WARM')
  expect(p).not.toContain('COLD')
  const m = /Cold writes this session\s+1\s+~\$(\d+(?:\.\d+)?)/.exec(p)
  expect(m, `cold-write line in: ${p}`).not.toBeNull()
  expect(Number(m![1])).toBeGreaterThan(0)
})

test('C36 retained: compact mid-step forces COLD (30000 tokens re-cache cost), stays COLD after the step, a new step warms; skip and precompute change nothing', { options: { cache_ttl: '1h', pricesJson: PRICES_SONNET } }, async ($, on) => {
  const r = rig($, on)
  await warmBand(r)
  await r.complete()
  const pane = await r.retained('pane', 'terminal', 100)
  expect(await pane.text()).toContain('WARM')
  const release = r.holdSteps()
  const run = r.startStep()
  await r.advance(0)
  await r.compact(200000, 30000)
  const cold = async (when: string) => {
    const p = await pane.text()
    expect(p, when).toContain('COLD')
    expect(p, when).not.toContain('WARM')
    expect(p, when).not.toMatch(countdown)
    expect(p, when).not.toContain('n/a')
    expect(p, when).toMatch(/return costs ~\$0\.18\b/i) // 30000 tokens * 6 $/MTok (1h write)
  }
  await cold('compact mid-step')
  release()
  await run.done
  await r.clock.settle()
  await r.complete()
  await cold('after the step returned and turn.complete fired')
  await r.step() // a new main step starts
  expect(await pane.text()).toContain('WARM')
  // a compact after the step ended
  await r.compact(200000, 30000)
  expect(await pane.text()).toContain('COLD')
  // skip result and precompute trigger leave the state unchanged
  await r.step()
  expect(await pane.text()).toContain('WARM')
  await r.compactRaw('manual', { skip: 'nothing to compact' })
  expect(await pane.text()).toContain('WARM')
  await r.compactRaw('precompute', { messages: [{ role: 'user', text: 'summary', toolUses: [] }], tokensBefore: 200000, tokensAfter: 30000 })
  const after = await pane.text()
  expect(after).toContain('WARM')
  expect(after).not.toContain('COLD')
})

// ---------------------------------------------------------------- F28 maximality / grow-back (40)
const BAND_OPTS = { cache_ttl: '1h' }
const isCacheTiny = (t: string) => !t.includes('CACHE') && /🍅\s*(\d{2}:\d{2}|\d+h\d{2}m)/.test(t)
const cacheRank = (t: string) => (t.includes('CACHE') ? (t.includes('warm') ? 3 : 2) : isCacheTiny(t) ? 1 : 0)
const burnRank = (t: string) => (t.includes('Gathering pace') ? 3 : t.includes('LEARNING') ? 2 : t.includes('5H') ? 1 : 0)

async function sweepFirst(r: ReturnType<typeof rig>, from: number, to: number, pred: (t: string) => boolean): Promise<number> {
  for (let n = from; n <= to; n++) if (pred((await r.mountAt('band', 'terminal', n)).text)) return n
  return -1
}
test('C40a variant thresholds learned alone: burn without forecast, cache short and full', { options: { ...BAND_OPTS, mod_cache_enabled: false } }, async ($, on) => {
  const r = rig($, on)
  await warmBand(r)
  expect(await sweepFirst(r, 8, 200, t => t.includes('LEARNING'))).toBe(62) // B_nf
  expect(await sweepFirst(r, 8, 200, t => t.includes('Gathering pace'))).toBe(110)
})
test('C40a variant thresholds learned alone: cache short and full', { options: { ...BAND_OPTS, mod_burn_enabled: false } }, async ($, on) => {
  const r = rig($, on)
  await warmBand(r)
  expect(await sweepFirst(r, 8, 200, t => cacheRank(t) >= 1)).toBeLessThanOrEqual(10) // tiny
  expect(await sweepFirst(r, 8, 200, t => cacheRank(t) >= 2)).toBe(26) // C_short
  expect(await sweepFirst(r, 8, 200, t => cacheRank(t) >= 3)).toBe(56) // C_full
})

test('C40 grow-back: burn without forecast leaves room, so the cache is short at 90 columns and full (warm, meter) at 120', { options: BAND_OPTS }, async ($, on) => {
  const r = rig($, on)
  await warmBand(r)
  const B_NF = 62, C_SHORT = 26, C_FULL = 56
  const short = (await r.mountAt('band', 'terminal', B_NF + 2 + C_SHORT)).text
  expect(short).toContain('LEARNING')
  expect(short).toContain('CACHE')
  expect(short).toMatch(/CACHE\s+(\d{2}:\d{2}|\d+h\d{2}m)/)
  const full = (await r.mountAt('band', 'terminal', B_NF + 2 + C_FULL)).text
  expect(full).toContain('LEARNING')
  expect(full).toContain('CACHE')
  expect(full).toContain('warm')
  expect(full).toMatch(/[█░]{12}\s+(\d{2}:\d{2}|\d+h\d{2}m)\s+warm/)
  // never a bare tiny countdown with room to spare
  for (let n = B_NF + 2 + C_SHORT; n < B_NF + 2 + C_FULL; n++) {
    const t = (await r.mountAt('band', 'terminal', n)).text
    expect(cacheRank(t), `${n} columns: ${t}`).toBeGreaterThanOrEqual(2)
  }
})

test('C40 no regression: with the burn variant unchanged, a wider band never shows a narrower cache variant; desktop alt equals terminal', { options: BAND_OPTS }, async ($, on) => {
  const r = rig($, on)
  await warmBand(r)
  const last = new Map<number, number>() // burn rank -> last cache rank
  for (let n = 20; n <= 200; n++) {
    const t = (await r.mountAt('band', 'terminal', n)).text
    const b = burnRank(t)
    const c = cacheRank(t)
    const before = last.get(b)
    if (before !== undefined) expect(c, `${n} columns (burn rank ${b}): ${t}`).toBeGreaterThanOrEqual(before)
    last.set(b, c)
    if (n >= 30 && (n % 5 === 0 || n === 90 || n === 120)) {
      const d = (await r.mountAt('band', 'desktop', n)).text
      expect(d.replace(/\s+/g, ' ').trim(), `${n} columns desktop`).toBe(t.replace(/\s+/g, ' ').trim())
    }
  }
})

// ---------------------------------------------------------------- F30 status line fallback (37-39)
const lastStatus = (r: ReturnType<typeof rig>) => r.st.statusCalls[r.st.statusCalls.length - 1]

test('C37 surfaces []: the status carries 5H/7D, follows each measure and does not wait for the clock', { options: { cache_ttl: '1h' } }, async ($, on) => {
  const r = rig($, on, { surfaces: [] })
  await r.start()
  await r.measure({ five: [2], seven: [68] })
  expect(String(lastStatus(r))).toContain('5H 2%')
  expect(String(lastStatus(r))).toContain('7D 68%')
  const t = r.now()
  await r.measure({ five: [3], seven: [68] })
  expect(r.now()).toBe(t)
  expect(String(lastStatus(r))).toContain('5H 3%')
})

test('C38 surfaces [] then [desktop]: one clearing status(undefined), then silence', { options: { cache_ttl: '1h' } }, async ($, on) => {
  const r = rig($, on, { surfaces: [] })
  await r.start()
  await r.measure({ five: [2], seven: [68] })
  expect(String(lastStatus(r))).toContain('5H 2%') // control: it was written while no surface existed
  const before = r.st.statusCalls.length
  r.st.surfaces = ['desktop']
  await r.measure({ five: [3], seven: [68] })
  const added = r.st.statusCalls.slice(before)
  expect(added).toEqual([undefined])
  const n = r.st.statusCalls.length
  await r.measure({ five: [4], seven: [69] })
  await r.step()
  await r.advance(S(2))
  await r.measure({ five: [5], seven: [69] })
  await r.advance(S(2))
  expect(r.st.statusCalls.length).toBe(n)
})

test('C39 surfaces [] and a main step started: the status shows cache with a countdown, not cache cold', { options: { cache_ttl: '1h' } }, async ($, on) => {
  const r = rig($, on, { surfaces: [] })
  await r.start()
  await r.measure({ five: [2], seven: [68] })
  const release = r.holdSteps()
  const n0 = r.st.stepLog.length
  const run = r.startStep()
  await r.clock.settle()
  expect(r.st.stepLog.length).toBe(n0 + 1) // the step is in flight
  const mid = String(lastStatus(r))
  expect(mid).toMatch(/cache\s+(\d{1,2}:\d{2}|\d+h\d{2}m)/)
  expect(mid).not.toContain('cache cold')
  release()
  await run.done
  await r.clock.settle()
  await r.complete()
  const end = String(lastStatus(r))
  expect(end).toMatch(/cache\s+(\d{1,2}:\d{2}|\d+h\d{2}m)/)
  expect(end).not.toContain('cache cold')
})

// ---------------------------------------------------------------- F32 COMPACTED chip slot fit
test('C40 within 60 s of a compaction, columns 20..160: the COMPACTED chip text stays inside its own slot on both surfaces', { options: { cache_ttl: '1h' } }, async ($, on) => {
  const r = rig($, on)
  await warmBand(r)
  await r.compact(91000, 23000)
  await r.advance(S(0, 10)) // well inside the 60 s window
  let seenDesktop = 0
  let seenTerminal = 0
  const bad: string[] = []
  for (let cols = 20; cols <= 160; cols += 2) {
    const desk = await r.mountAt('band', 'desktop', cols)
    for (const s of walk(desk.tree).filter(n => n.type === 'Svg')) {
      const { problems, groups } = clipProblems(s)
      for (const p of problems) bad.push(`desktop ${cols} columns: ${p}`)
      if (groups.some(g => g.texts.some(t => t.s.includes('COMPACTED')))) seenDesktop++
    }
    const term = await r.mountAt('band', 'terminal', cols)
    for (const line of term.text.split('\n')) {
      if (cellWidth(line) > cols) bad.push(`terminal ${cols} columns: "${line}" is ${cellWidth(line)} cells`)
    }
    if (term.text.includes('COMPACTED')) seenTerminal++
  }
  expect(bad).toEqual([])
  expect(seenDesktop).toBeGreaterThan(5) // positive control: the chip was drawn
  expect(seenTerminal).toBeGreaterThan(5)
})
