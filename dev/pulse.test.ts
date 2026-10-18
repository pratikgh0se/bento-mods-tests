// Contract statements C08-C19 (Test Pulse). Source: specs/dev.md sections 5 and 13 "Test Pulse".
import { test, expect } from 'claude-code/testing'
import {
  SURFACES,
  TOP,
  world,
  crossCheck,
  ANSI,
  PYTEST_3F_12P_1S,
  VITEST_OUT,
  JEST_OUT,
  BUN_OUT,
  GO_OUT,
  CARGO_OUT,
  pytestRun,
} from './_harness'

type Case = { id: string; label: string; command: string; stdout: string; chip: string; stderr?: string }

const CASES: Case[] = [
  { id: 'C08', label: 'pytest', command: 'pytest -q', stdout: PYTEST_3F_12P_1S, chip: '12 pass 3 fail 1 skip · 2.3s · pytest' },
  { id: 'C09', label: 'vitest', command: 'npx vitest run', stdout: VITEST_OUT, chip: '10 pass 2 fail · 1.5s · vitest' },
  { id: 'C10', label: 'jest', command: 'npx jest', stdout: JEST_OUT, chip: '9 pass 1 fail · 2.1s · jest' },
  { id: 'C11', label: 'bun', command: 'bun test', stdout: BUN_OUT, chip: '10 pass 1 fail · 120ms · bun' },
  { id: 'C12', label: 'go', command: 'go test ./...', stdout: GO_OUT, chip: '1 pkg pass 1 pkg fail' },
  { id: 'C13', label: 'cargo', command: 'cargo test', stdout: CARGO_OUT, chip: '8 pass 2 fail 1 skip' },
]

for (const surface of SURFACES) {
  for (const c of CASES) {
    test(`${c.id} ${c.label} output -> chip "${c.chip}" [${surface}]`, async ($, on) => {
      const w = world(on, { surfaces: [surface] })
      await w.start($, surface)
      await w.bash($, c.command, c.stdout)
      const text = await w.band($, surface)
      expect(text).toContain(c.chip)
      crossCheck(c.id, surface, text)
    })
  }

  test(`C13 cargo summary goes to stderr stream is also parsed (cargo prints results on stdout; stderr may carry them) [${surface}]`, async ($, on) => {
    // cargo writes "test result:" lines to stdout, but `cargo test` run through some wrappers merges to stderr.
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    await w.bash($, 'cargo test', '', { stderr: CARGO_OUT })
    const text = await w.band($, surface)
    expect(text).toContain('8 pass 2 fail 1 skip')
  })

  test(`C14 ANSI-coloured pytest output parses the same [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    const coloured = PYTEST_3F_12P_1S.replace('3 failed', ANSI.red('3 failed'))
      .replace('12 passed', ANSI.green('12 passed'))
      .replace('FAILED tests/test_a.py::test_x', `${ANSI.red('FAILED')} tests/test_a.py::test_x`)
      .replace('1 skipped in 2.31s', `1 skipped${'\u001b[0m'} in ${ANSI.bold('2.31s')}`)
    expect(coloured).toContain('\u001b[')
    await w.bash($, 'pytest -q', coloured)
    const text = await w.band($, surface)
    expect(text).toContain('12 pass 3 fail 1 skip · 2.3s · pytest')
    crossCheck('C14', surface, text)
  })

  test(`C15 "npm test" with jest-shaped output -> runner jest [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    await w.bash($, 'npm test', JEST_OUT)
    const text = await w.band($, surface)
    expect(text).toContain('9 pass 1 fail')
    expect(text).toContain('· jest')
    crossCheck('C15', surface, text)
  })

  test(`C16 a non-test Bash leaves the chip unchanged; go test without summary -> "ran, no summary" [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    const empty = await w.band($, surface)
    await w.bash($, 'ls', 'README.md\nsrc\n', { readOnly: true })
    expect(await w.band($, surface)).toBe(empty)
    expect(empty).not.toContain('pass')

    await w.bash($, 'pytest -q', PYTEST_3F_12P_1S)
    const afterRun = await w.band($, surface)
    expect(afterRun).toContain('12 pass 3 fail')
    await w.bash($, 'ls -la', 'total 0\n', { readOnly: true })
    expect(await w.band($, surface)).toBe(afterRun)

    await w.bash($, 'go test ./...', '# a\n./a.go:3:1: syntax error: unexpected }\n', { isError: true }) // error flag without an exit line = unknown status
    const noSummary = await w.band($, surface)
    expect(noSummary).toContain('ran, no summary')
    crossCheck('C16', surface, noSummary)
  })

  test(`C17 stale marker counts successful edits and a new run clears it [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    await w.bash($, 'pytest -q', PYTEST_3F_12P_1S)
    expect(await w.band($, surface)).not.toContain('stale')
    await w.edit($, `${TOP}/src/a.py`)
    const one = await w.band($, surface)
    expect(one).toContain('stale (1 edit)')
    expect(one).not.toContain('stale (1 edits)')
    await w.edit($, `${TOP}/src/b.py`)
    const two = await w.band($, surface)
    expect(two).toContain('stale (2 edits)')
    await w.bash($, 'pytest -q', PYTEST_3F_12P_1S)
    const cleared = await w.band($, surface)
    expect(cleared).not.toContain('stale')
    crossCheck('C17', surface, two)
  })

  test(`C18 flaky: two flips with no edits between runs -> "⚠ 1 flaky" only after run 4 [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    const fail = pytestRun(['a::test_x'], 4)
    const pass = pytestRun([], 5)
    await w.bash($, 'pytest -q', fail)
    await w.advance(1000)
    await w.bash($, 'pytest -q', pass)
    expect(await w.band($, surface)).not.toContain('flaky')
    await w.advance(1000)
    await w.bash($, 'pytest -q', fail)
    expect(await w.band($, surface)).not.toContain('flaky')
    await w.advance(1000)
    await w.bash($, 'pytest -q', pass)
    const text = await w.band($, surface)
    expect(text).toContain('⚠ 1 flaky')
    crossCheck('C18', surface, text)
  })

  test(`C18 an edit between runs 1 and 2 means that pair is not counted [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    const fail = pytestRun(['a::test_x'], 4)
    const pass = pytestRun([], 5)
    await w.bash($, 'pytest -q', fail)
    await w.edit($, `${TOP}/src/a.py`)
    await w.bash($, 'pytest -q', pass) // would be flip 1 without the edit
    await w.bash($, 'pytest -q', fail)
    await w.bash($, 'pytest -q', pass) // flip 2 of a plain count, but only the 2nd pair counts
    expect(await w.band($, surface)).not.toContain('flaky')
  })

  test(`C19 subagent test runs are ignored by default [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    await w.bash($, 'pytest -q', PYTEST_3F_12P_1S, { agentId: 'sub-agent-1' })
    const text = await w.band($, surface)
    expect(text).not.toContain('12 pass')
    expect(text).not.toContain('pytest')
    crossCheck('C19', surface, text)
  })

  test(`C19 with pulse.includeSubagents=true a subagent run is shown [${surface}]`, { options: { 'pulse_includeSubagents': true } as never }, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    await w.bash($, 'pytest -q', PYTEST_3F_12P_1S, { agentId: 'sub-agent-1' })
    expect(await w.band($, surface)).toContain('12 pass 3 fail 1 skip')
  })
}

test('C08 /pulse lists the last runs (command text mentions the runner and counts)', async ($, on) => {
  const w = world(on)
  await w.start($)
  await w.bash($, 'pytest -q', PYTEST_3F_12P_1S)
  const text = await w.cmd($, 'pulse')
  expect(text).toContain('pytest')
  expect(text).toContain('12')
})
