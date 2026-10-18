// Contract statements for rewritten tool output (RTK) and the exit-code fallback.
// Source: specs/dev.md section 5 "Rewritten output (decided 2026-10-12)".
import { test, expect } from 'claude-code/testing'
import { SURFACES, world, crossCheck, PYTEST_3F_12P_1S, VITEST_OUT, JEST_OUT, BUN_OUT, GO_OUT, CARGO_OUT } from './_harness'
import { bashRaw, RTK_GO_FAIL } from './_rewritten'

for (const surface of SURFACES) {
  for (const command of ['go test ./...', 'go test -v ./...']) {
    test(`R01 RTK go failure (Exit code 1) via "${command}" -> chip "0 pass 1 fail", /pulse "0 pass 1 fail · go" and TestX [${surface}]`, async ($, on) => {
      const w = world(on, { surfaces: [surface] })
      await w.start($, surface)
      await bashRaw($, w, command, RTK_GO_FAIL, { exit: 1 })
      const chip = await w.band($, surface)
      expect(chip).toContain('0 pass 1 fail')
      expect(chip).not.toContain('no summary')
      expect(chip).not.toContain('failed (exit')
      const pulse = await w.cmd($, 'pulse')
      expect(pulse).toContain('0 pass 1 fail · go')
      expect(pulse).toContain('TestX')
      crossCheck('R01', surface, chip)
    })
  }

  test(`R02 RTK go success "Go test: 12 passed, 0 failed in 3 packages" -> "12 pass" [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    await bashRaw($, w, 'go test ./...', 'Go test: 12 passed, 0 failed in 3 packages')
    const chip = await w.band($, surface)
    expect(chip).toContain('12 pass')
    expect(chip).not.toContain('fail')
    expect(chip).not.toContain('no summary')
  })

  test(`R03 RTK "Go test: No tests found" -> a summary with 0 tests, not "no summary" [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    await bashRaw($, w, 'go test ./...', 'Go test: No tests found')
    const chip = await w.band($, surface)
    expect(chip).not.toContain('no summary')
    expect(chip).toMatch(/\b0 pass\b/)
    expect(chip).toContain('go')
  })

  for (const command of ['pytest -q', 'python3 -m pytest']) {
    test(`R04 RTK pytest "Pytest: 3 passed, 1 failed" via "${command}" -> "3 pass 1 fail" [${surface}]`, async ($, on) => {
      const w = world(on, { surfaces: [surface] })
      await w.start($, surface)
      await bashRaw($, w, command, 'Pytest: 3 passed, 1 failed', { exit: 1 })
      const chip = await w.band($, surface)
      expect(chip).toContain('3 pass 1 fail')
      expect(chip).not.toContain('no summary')
      expect(chip).toContain('pytest')
    })
  }

  test(`R05 RTK "Pytest: No tests collected" -> 0 tests with a summary [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    await bashRaw($, w, 'pytest -q', 'Pytest: No tests collected')
    const chip = await w.band($, surface)
    expect(chip).not.toContain('no summary')
    expect(chip).toMatch(/\b0 pass\b/)
    expect(chip).toContain('pytest')
  })

  for (const [command, out, chip] of [
    ['pytest -q', PYTEST_3F_12P_1S, '12 pass 3 fail 1 skip · 2.3s · pytest'],
    ['npx vitest run', VITEST_OUT, '10 pass 2 fail · 1.5s · vitest'],
    ['npx jest', JEST_OUT, '9 pass 1 fail · 2.1s · jest'],
    ['bun test', BUN_OUT, '10 pass 1 fail · 120ms · bun'],
    ['go test ./...', GO_OUT, '1 pkg pass 1 pkg fail'],
    ['cargo test', CARGO_OUT, '8 pass 2 fail 1 skip'],
  ] as [string, string, string][]) {
    test(`R06 regression: raw "${command}" fixture keeps chip "${chip}" [${surface}]`, async ($, on) => {
      const w = world(on, { surfaces: [surface] })
      await w.start($, surface)
      await bashRaw($, w, command, out)
      expect(await w.band($, surface)).toContain(chip)
    })
  }

  test(`R07 exit-code fallback: runner, unrecognisable text, "Exit code 2" -> "ran, failed (exit 2)" in chip and /pulse [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    await bashRaw($, w, 'go test ./...', '# a\n./a.go:3:1: syntax error: unexpected }\n', { exit: 2 })
    const chip = await w.band($, surface)
    expect(chip).toContain('ran, failed (exit 2)')
    expect(await w.cmd($, 'pulse')).toContain('ran, failed (exit 2)')
    crossCheck('R07', surface, chip)
  })

  test(`R08 exit-code fallback: a leading "Exit code 2" decides even without the error flag [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    await bashRaw($, w, 'pytest -q', 'something odd happened\n', { exit: 2, isError: false })
    expect(await w.band($, surface)).toContain('ran, failed (exit 2)')
  })

  test(`R09 exit-code fallback: no exit prefix and no error flag -> "ran, ok" in chip and /pulse [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    await bashRaw($, w, 'cargo test', 'compiled quietly\n')
    const chip = await w.band($, surface)
    expect(chip).toContain('ran, ok')
    expect(chip).not.toContain('no summary')
    expect(await w.cmd($, 'pulse')).toContain('ran, ok')
  })

  test(`R10 unknown status: error flag set but no "Exit code" line -> "ran, no summary" [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    await bashRaw($, w, 'go test ./...', 'killed by something\n', { isError: true })
    const chip = await w.band($, surface)
    expect(chip).toContain('ran, no summary')
    expect(chip).not.toContain('ran, ok')
    expect(chip).not.toContain('failed (exit')
  })

  test(`R11 a non-test Bash with an Exit code is still ignored [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    const empty = await w.band($, surface)
    await bashRaw($, w, 'ls /nope', 'ls: /nope: No such file or directory', { exit: 2 })
    await bashRaw($, w, 'echo hi', 'hi\n')
    const after = await w.band($, surface)
    expect(after).toBe(empty)
    expect(after).not.toContain('ran,')
  })
}
