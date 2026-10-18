// Contract statements C20-C24 and C54 (Coverage Delta). Source: specs/dev.md sections 6 and 13.
import { test, expect } from 'claude-code/testing'
import { SURFACES, TOP, world, crossCheck, VITEST_OUT, base } from './_harness'
import type { Any, World } from './_harness'

const SUMMARY = `${TOP}/coverage/coverage-summary.json`
const summaryJson = (pct: number): string => JSON.stringify({ total: { lines: { total: 100, covered: pct, skipped: 0, pct }, statements: { total: 100, covered: pct, skipped: 0, pct } } })

/** A recognised test run (vitest) after the coverage file has been (re)written. */
const run = ($: Any, w: World): Promise<Any> => w.bash($, 'npx vitest run --coverage', VITEST_OUT)

const lcov = (blocks: { lf: number; lh: number }[]): string =>
  blocks.map((b, i) => `TN:\nSF:src/f${i}.ts\nFNF:2\nFNH:1\nDA:1,1\nLF:${b.lf}\nLH:${b.lh}\nBRF:4\nBRH:2\nend_of_record\n`).join('')

for (const surface of SURFACES) {
  test(`C20 coverage-summary.json lines.pct 83.2 with fresh mtime -> chip "83.2%" [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    w.setFile(SUMMARY, summaryJson(83.2))
    await run($, w)
    const text = await w.band($, surface)
    expect(text).toContain('83.2%')
    crossCheck('C20', surface, text)
  })

  test(`C20 coverage file older than the run -> no coverage chip [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    w.setFile(SUMMARY, summaryJson(83.2), 60_000)
    await run($, w)
    const text = await w.band($, surface)
    expect(text).not.toContain('83.2%')
    expect(text).not.toContain('📈')
    crossCheck('C20b', surface, text)
  })

  test(`C21 second reading 83.6 after 83.2 -> "(+0.4)" [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    w.setFile(SUMMARY, summaryJson(83.2))
    await run($, w)
    await w.advance(60_000)
    w.setFile(SUMMARY, summaryJson(83.6))
    await run($, w)
    const text = await w.band($, surface)
    expect(text).toContain('83.6%')
    expect(text).toContain('(+0.4)')
    expect(text).not.toContain('⚠')
    crossCheck('C21a', surface, text)
  })

  test(`C21 drop from 83.6 to 82.0 -> "(-1.6)" with the warning marker [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    w.setFile(SUMMARY, summaryJson(83.6))
    await run($, w)
    await w.advance(60_000)
    w.setFile(SUMMARY, summaryJson(82.0))
    await run($, w)
    const text = await w.band($, surface)
    expect(text).toContain('82.0%')
    expect(text).toContain('(-1.6)')
    expect(text).toContain('⚠')
    crossCheck('C21b', surface, text)
  })

  test(`C22 lcov LF:100 LH:80 and LF:100 LH:90 -> "85.0%" [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    w.setFile(`${TOP}/coverage/lcov.info`, lcov([{ lf: 100, lh: 80 }, { lf: 100, lh: 90 }]))
    await run($, w)
    const text = await w.band($, surface)
    expect(text).toContain('85.0%')
    crossCheck('C22', surface, text)
  })

  test(`C23 cobertura line-rate="0.8512" -> "85.1%" [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    w.setFile(
      `${TOP}/coverage.xml`,
      '<?xml version="1.0" ?>\n<coverage version="7.4.0" timestamp="1760000000000" lines-valid="1000" lines-covered="851" line-rate="0.8512" branches-covered="0" branches-valid="0" branch-rate="0" complexity="0">\n  <packages/>\n</coverage>\n',
    )
    await w.bash($, 'pytest --cov -q', '=== 5 passed in 0.50s ===')
    const text = await w.band($, surface)
    expect(text).toContain('85.1%')
    crossCheck('C23', surface, text)
  })

  test(`C24 coverage.py json totals.percent_covered 91.04 -> "91.0%" [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    w.setFile(
      `${TOP}/coverage.json`,
      JSON.stringify({ meta: { version: '7.4.0' }, files: {}, totals: { covered_lines: 91, num_statements: 100, percent_covered: 91.04, percent_covered_display: '91' } }),
    )
    await w.bash($, 'pytest --cov -q', '=== 5 passed in 0.50s ===')
    const text = await w.band($, surface)
    expect(text).toContain('91.0%')
    crossCheck('C24', surface, text)
  })

  test(`C54 default baseline is session-first: 80.0 then 82.0 -> "(+2.0)" and no git status [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    w.setFile(SUMMARY, summaryJson(80.0))
    await run($, w)
    await w.advance(60_000)
    w.setFile(SUMMARY, summaryJson(82.0))
    await run($, w)
    const text = await w.band($, surface)
    expect(text).toContain('82.0%')
    expect(text).toContain('(+2.0)')
    // `git status --porcelain` (v1, exact flag) is only run for coverage.baseline=last-clean.
    const plain = w.count(c => base(c.argv[0]) === 'git' && c.argv.includes('status') && c.argv.includes('--porcelain'))
    expect(plain).toBe(0)
    crossCheck('C54a', surface, text)
  })

  test(
    `C54 coverage.baseline=last-clean uses the reading taken at the last clean git status [${surface}]`,
    { options: { 'coverage_baseline': 'last-clean' } as never },
    async ($, on) => {
      const w = world(on, { surfaces: [surface] })
      // run 1: dirty, run 2: clean, run 3: dirty
      w.rule((a: readonly string[]) => base(a[0]) === 'git' && a.includes('status') && a.includes('--porcelain'), (_a: readonly string[], n: number) => ({
        stdout: [' M src/a.ts\n', '', ' M src/a.ts\n'][Math.min(n, 2)] ?? '',
      }))
      await w.start($, surface)
      w.setFile(SUMMARY, summaryJson(80.0))
      await run($, w)
      await w.advance(60_000)
      w.setFile(SUMMARY, summaryJson(82.0))
      await run($, w)
      await w.advance(60_000)
      w.setFile(SUMMARY, summaryJson(85.0))
      await run($, w)
      const text = await w.band($, surface)
      expect(text).toContain('85.0%')
      expect(text).toContain('(+3.0)') // against 82.0, the clean reading; session-first would say +5.0
      const plain = w.count(c => base(c.argv[0]) === 'git' && c.argv.includes('status') && c.argv.includes('--porcelain'))
      expect(plain).toBeGreaterThanOrEqual(1)
      crossCheck('C54b', surface, text)
    },
  )
}

test('C20 /coverage without any coverage file says how to produce one', async ($, on) => {
  const w = world(on)
  await w.start($)
  await w.bash($, 'npx vitest run', VITEST_OUT)
  const band = await w.band($, 'terminal')
  expect(band).not.toContain('📈')
  const text = await w.cmd($, 'coverage')
  expect(text).toContain('No coverage file found. Run the tests with coverage (vitest --coverage, pytest --cov).')
})
