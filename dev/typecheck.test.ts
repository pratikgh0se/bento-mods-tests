// Contract statements C25-C32 and C53 (Typecheck Feedback). Source: specs/dev.md sections 7 and 13.
import { test, expect } from 'claude-code/testing'
import { SURFACES, TOP, world, crossCheck, base } from './_harness'
import type { Any, World } from './_harness'

const TS_ERR = "src/a.ts(10,5): error TS2322: Type 'string' is not assignable to type 'number'."
const TS_MSG = "Type 'string' is not assignable to type 'number'."
const A_TS = `${TOP}/src/a.ts`
const isTsc = (a: readonly string[]): boolean => a.some(x => x === 'tsc' || x.endsWith('/tsc')) && !a.includes('rev-parse')
const isRuff = (a: readonly string[]): boolean => a.some(x => x === 'ruff' || base(x) === 'ruff')

const withTs = (w: World): void => {
  w.setFile(`${TOP}/tsconfig.json`, '{}')
  w.setFile(`${TOP}/node_modules/.bin/tsc`, '#!/usr/bin/env node')
}
const ctxOf = (ran: Any): string => ((ran?.context ?? []) as string[]).join('\n')

for (const surface of SURFACES) {
  test(`C25 tsc error is appended as context to the Write result; result unchanged; chip "TSC 1 error" [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    withTs(w)
    w.rule(isTsc, { exitCode: 2, stdout: `${TS_ERR}\n` })
    await w.start($, surface)
    const answer = {
      result: { type: 'update', filePath: A_TS, content: 'const a: number = "x"\n', structuredPatch: [], originalFile: '' },
      text: `The file ${A_TS} has been updated.`,
    }
    const ran = await w.tool($, { tool: 'Write', file_path: A_TS, content: 'const a: number = "x"\n' }, answer)
    expect(ran.result).toEqual(answer.result)
    expect(ran.deny).toBeUndefined()
    const ctx = ctxOf(ran)
    expect(ctx).toContain('TYPECHECK: 1 error in files you touched (tsc):')
    expect(ctx).toContain(TS_MSG)
    expect(ctx).toContain('src/a.ts(10,5)')
    expect(ctx).toContain('TS2322')
    const text = await w.band($, surface)
    expect(text).toContain('TSC 1 error')
    crossCheck('C25', surface, text)
  })
}

test('C26 the same errors after another edit are not fed back twice', async ($, on) => {
  const w = world(on)
  withTs(w)
  w.rule(isTsc, { exitCode: 2, stdout: `${TS_ERR}\n` })
  await w.start($)
  const first = await w.write($, A_TS)
  expect(ctxOf(first)).toContain('TYPECHECK: 1 error')
  const second = await w.edit($, A_TS)
  expect(ctxOf(second)).not.toContain('TYPECHECK')
  expect(second.context === undefined || second.context.length === 0).toBe(true)
})

test('C26 errors that change are sent again', async ($, on) => {
  const w = world(on)
  withTs(w)
  w.rule(isTsc, (_a: readonly string[], n: number) => ({
    exitCode: 2,
    stdout: n === 0 ? `${TS_ERR}\n` : `src/a.ts(11,1): error TS2304: Cannot find name 'foo'.\n`,
  }))
  await w.start($)
  await w.write($, A_TS)
  const second = await w.edit($, A_TS)
  expect(ctxOf(second)).toContain("Cannot find name 'foo'.")
})

test('C27 errors gone -> context "TYPECHECK: clean (tsc)"', async ($, on) => {
  const w = world(on)
  withTs(w)
  w.rule(isTsc, (_a: readonly string[], n: number) => (n === 0 ? { exitCode: 2, stdout: `${TS_ERR}\n` } : { exitCode: 0, stdout: '' }))
  await w.start($)
  await w.write($, A_TS)
  const second = await w.edit($, A_TS)
  expect(ctxOf(second)).toContain('TYPECHECK: clean (tsc)')
})

test('C27 a clean run with no earlier errors adds no context', async ($, on) => {
  const w = world(on)
  withTs(w)
  w.rule(isTsc, { exitCode: 0, stdout: '' })
  await w.start($)
  const ran = await w.write($, A_TS)
  expect(ctxOf(ran)).toBe('')
})

test('C28 ruff concise output for a .py edit -> context mentions F401', async ($, on) => {
  const w = world(on)
  w.rule(isRuff, (a: readonly string[]) =>
    a.includes('--version') ? { stdout: 'ruff 0.5.0\n' } : { exitCode: 1, stdout: 'a.py:3:1: F401 os imported but unused\n' },
  )
  await w.start($)
  const ran = await w.edit($, `${TOP}/a.py`)
  const ctx = ctxOf(ran)
  expect(ctx).toContain('F401')
  expect(ctx).toContain('os imported but unused')
  expect(ctx).toContain('(ruff)')
})

test('C29 tsc taking 25 s: result returned within the 20 s budget without context; next edit carries the finished run', async ($, on) => {
  const w = world(on)
  withTs(w)
  w.rule(isTsc, (_a: readonly string[], n: number) => (n === 0 ? { exitCode: 2, stdout: `${TS_ERR}\n`, delayMs: 25_000 } : { exitCode: 2, stdout: `${TS_ERR}\n` }))
  await w.start($)
  const answer = w.editAnswer(A_TS, ['+x'])
  const pending = w.toolPromise($, { tool: 'Edit', file_path: A_TS, old_string: 'a', new_string: 'b' }, answer)
  await w.advance(20_100) // budget (20 s) exceeded, tsc (25 s) still running
  const ran = await pending
  expect(ran.result).toEqual(answer.result)
  expect(ctxOf(ran)).toBe('')
  await w.advance(6_000) // the run finishes in the background
  const next = await w.edit($, A_TS)
  expect(ctxOf(next)).toContain(TS_MSG)
})

for (const surface of SURFACES) {
  test(`C30 tc.mode=band: chip only, no context [${surface}]`, { options: { 'tc_mode': 'band' } as never }, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    withTs(w)
    w.rule(isTsc, { exitCode: 2, stdout: `${TS_ERR}\n` })
    await w.start($, surface)
    const ran = await w.write($, A_TS)
    expect(ran.context === undefined || ran.context.length === 0).toBe(true)
    const text = await w.band($, surface)
    expect(text).toContain('TSC 1 error')
    crossCheck('C30', surface, text)
  })
}

test('C30 tc.mode=off: no tsc run, no context, no chip', { options: { tc_mode: 'off' } as never }, async ($, on) => {
  const w = world(on)
  withTs(w)
  w.rule(isTsc, { exitCode: 2, stdout: `${TS_ERR}\n` })
  await w.start($)
  const ran = await w.write($, A_TS)
  expect(ctxOf(ran)).toBe('')
  expect(w.tscCalls().length).toBe(0)
  expect(await w.band($, 'terminal')).not.toContain('TSC')
})

test('C31 missing tsconfig and binary: result untouched, no error for the agent, status "tsc: n/a"', async ($, on) => {
  const w = world(on)
  await w.start($)
  const answer = w.editAnswer(A_TS, ['+x'])
  const ran = await w.tool($, { tool: 'Edit', file_path: A_TS, old_string: 'a', new_string: 'b' }, answer)
  expect(ran.result).toEqual(answer.result)
  expect(ran.deny).toBeUndefined()
  expect(ran.isError).toBeUndefined()
  expect(ctxOf(ran)).toBe('')
  const seen = [...w.statuses.filter(s => s !== undefined), await w.band($, 'terminal'), await w.cmd($, 'typecheck')].join(' | ')
  expect(seen).toContain('tsc: n/a')
})

test('C31 tsconfig present but no binary and npx cannot resolve tsc: nothing reaches the agent', async ($, on) => {
  const w = world(on)
  w.setFile(`${TOP}/tsconfig.json`, '{}')
  w.rule(isTsc, { exitCode: 1, stdout: '', stderr: 'npm error npx canceled due to missing packages and no YES option: ["typescript"]\n' })
  await w.start($)
  const answer = w.editAnswer(A_TS, ['+x'])
  const ran = await w.tool($, { tool: 'Edit', file_path: A_TS, old_string: 'a', new_string: 'b' }, answer)
  expect(ran.result).toEqual(answer.result)
  expect(ctxOf(ran)).toBe('')
})

for (const kind of ['tsc', 'ruff'] as const) {
  test(`C32 a throwing ${kind} never alters the tool result`, async ($, on) => {
    const w = world(on)
    withTs(w)
    w.rule(kind === 'tsc' ? isTsc : isRuff, { reject: 'spawn ENOENT' })
    await w.start($)
    const file = kind === 'tsc' ? A_TS : `${TOP}/a.py`
    const answer = w.editAnswer(file, ['+x'])
    const ran = await w.tool($, { tool: 'Edit', file_path: file, old_string: 'a', new_string: 'b' }, answer)
    expect(ran.result).toEqual(answer.result)
    expect(ran.deny).toBeUndefined()
    expect(ran.isError).toBeUndefined()
    expect(ctxOf(ran)).toBe('')
  })
}

test('C53 tsc runs after each edit (two edits 10 s apart -> two runs, timeoutMs 20000 each)', async ($, on) => {
  const w = world(on)
  withTs(w)
  w.rule(isTsc, { exitCode: 2, stdout: `${TS_ERR}\n` })
  await w.start($)
  await w.edit($, A_TS)
  await w.advance(10_000)
  await w.edit($, A_TS)
  await w.advance(1000)
  const runs = w.tscCalls()
  expect(runs.length).toBe(2)
  for (const r of runs) expect(r.timeoutMs).toBe(20_000)
})
