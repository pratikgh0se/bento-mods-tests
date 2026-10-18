// Contract statements C44-C47 (common behaviour). Source: specs/dev.md section 13 "Common".
import { test, expect } from 'claude-code/testing'
import { SURFACES, TOP, world, crossCheck, porcelain, WT3, PRS3, VITEST_OUT, PYTEST_3F_12P_1S, base } from './_harness'
import type { Any, Listener, Surface, World } from './_harness'

const TS_ERR = "src/a.ts(10,5): error TS2322: Type 'string' is not assignable to type 'number'."
const A_TS = `${TOP}/src/a.ts`
const isTsc = (a: readonly string[]): boolean => a.some(x => x === 'tsc' || x.endsWith('/tsc')) && !a.includes('rev-parse')
const SUMMARY = `${TOP}/coverage/coverage-summary.json`
const summaryJson = (pct: number): string => JSON.stringify({ total: { lines: { total: 100, covered: pct, skipped: 0, pct } } })

// --------------------------------------------------------------------------------- C44

test('C44 every tool result other than the typecheck context is returned unchanged', async ($, on) => {
  const w = world(on)
  await w.start($)
  const answers: [Record<string, unknown>, Any][] = [
    [{ tool: 'Bash', command: 'git commit -m x' }, w.bashAnswer('[main abc1234] x\n', { gitOperation: { commit: { sha: 'abc1234', kind: 'committed', branch: 'main' } } })],
    [{ tool: 'Bash', command: 'pytest -q' }, w.bashAnswer(PYTEST_3F_12P_1S)],
    [{ tool: 'Bash', command: 'ls' }, w.bashAnswer('README.md\n', { readOnly: true })],
    [{ tool: 'Bash', command: 'false' }, { isError: true, result: 'Exit code 1', text: 'Exit code 1' }],
    [{ tool: 'Edit', file_path: `${TOP}/README.md`, old_string: 'a', new_string: 'b' }, w.editAnswer(`${TOP}/README.md`, ['-a', '+b'])],
    [{ tool: 'Write', file_path: `${TOP}/notes.md`, content: 'x' }, { result: { type: 'create', filePath: `${TOP}/notes.md`, content: 'x', structuredPatch: [], originalFile: null }, text: 'created' }],
    [{ tool: 'Read', file_path: `${TOP}/README.md` }, { result: { type: 'text', file: { filePath: `${TOP}/README.md`, content: 'hi' } }, text: 'hi', isReadOnly: true }],
    [{ tool: 'Grep', pattern: 'x' }, { result: { mode: 'content', numFiles: 0, filenames: [], content: '' }, text: 'none', isReadOnly: true }],
  ]
  for (const [input, answer] of answers) {
    const ran = await w.tool($, input, answer)
    const { isReadOnly: _ro, ...gotRest } = ran
    const { isReadOnly: _ro2, ...wantRest } = answer
    expect(gotRest, `${String(input.tool)} result was altered`).toEqual(wantRest)
    expect(ran.context).toBeUndefined()
  }
})

test('C44 the tool result is unchanged even when Typecheck adds context (only context is added)', async ($, on) => {
  const w = world(on)
  w.setFile(`${TOP}/tsconfig.json`, '{}')
  w.setFile(`${TOP}/node_modules/.bin/tsc`, 'x')
  w.rule(isTsc, { exitCode: 2, stdout: `${TS_ERR}\n` })
  await w.start($)
  const answer = w.editAnswer(A_TS, ['+x'])
  const ran = await w.tool($, { tool: 'Edit', file_path: A_TS, old_string: 'a', new_string: 'b' }, answer)
  const { context, ...rest } = ran
  expect(rest).toEqual(answer)
  expect(((context ?? []) as string[]).join('\n')).toContain('TYPECHECK')
})

// --------------------------------------------------------------------------------- C45

for (const surface of SURFACES) {
  test(`C45 process probe rejects -> status "needs host commands"; Test Pulse and Coverage keep working [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface], procDown: true })
    await w.start($, surface)
    w.setFile(SUMMARY, summaryJson(83.2))
    await w.bash($, 'npx vitest run --coverage', VITEST_OUT)
    await w.write($, A_TS)
    await w.turnComplete($)
    await w.advance(10_000)

    const statuses = w.statuses.filter((s): s is string => typeof s === 'string')
    expect(statuses.some(s => s.includes('needs host commands'))).toBe(true)

    const text = await w.band($, surface)
    expect(text).toContain('10 pass 2 fail')
    expect(text).toContain('83.2%')
    crossCheck('C45', surface, text)

    // the process-based mods do nothing else: only the probe was attempted
    expect(w.calls.length).toBe(1)
    expect(w.calls[0]!.argv.slice(-1)[0]).toBe('--version')
  })
}

// --------------------------------------------------------------------------------- C46

const INNER = { type: 'Text', props: {}, children: ['INNER-MARK'] }

for (const surface of SURFACES) {
  test(`C46 row hidden for hasSurvey, view.agentId, maxRows < 4; inner tree preserved otherwise [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    w.inner = INNER
    await w.start($, surface)
    await w.bash($, 'pytest -q', PYTEST_3F_12P_1S)

    const shown = await w.band($, surface)
    expect(shown).toContain('INNER-MARK')
    expect(shown).toContain('12 pass 3 fail 1 skip')

    const survey = await w.band($, surface, { hasSurvey: true })
    expect(survey).toContain('INNER-MARK')
    expect(survey).not.toContain('12 pass')

    const agent = await w.band($, surface, { view: { agentId: 'agent-7' } })
    expect(agent).toContain('INNER-MARK')
    expect(agent).not.toContain('12 pass')

    const small = await w.band($, surface, { maxRows: 3 })
    expect(small).toContain('INNER-MARK')
    expect(small).not.toContain('12 pass')

    const ok = await w.band($, surface, { maxRows: 4 })
    expect(ok).toContain('12 pass')
    crossCheck('C46', surface, shown)
  })

  test(`C46 nothing to show -> the inner tree alone [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface], noRepo: true })
    w.inner = INNER
    await w.start($, surface)
    expect(await w.band($, surface)).toBe('INNER-MARK')
  })
}

// --------------------------------------------------------------------------------- C47

const PG: Listener = { pid: 5151, cmd: 'postgres', addrs: ['127.0.0.1:5432'], cwd: '/var/lib/postgresql/data' }
const OURS: Listener = { pid: 4242, cmd: 'node', addrs: ['*:3000'], cwd: `${TOP}/app` }

type Mod = 'git' | 'diff' | 'pulse' | 'coverage' | 'typecheck' | 'pr' | 'ports'
const MODS: { id: Mod; marker: string; command?: string }[] = [
  { id: 'git', marker: 'feat/auth*' },
  { id: 'diff', marker: '+10', command: 'changes' },
  { id: 'pulse', marker: '10 pass 2 fail', command: 'pulse' },
  { id: 'coverage', marker: '83.2%', command: 'coverage' },
  { id: 'typecheck', marker: 'TSC 1 error', command: 'typecheck' },
  { id: 'pr', marker: '#412', command: 'prs' },
  { id: 'ports', marker: '1 port (3000)', command: 'ports' },
]

/** Drives every mod once and returns what a test needs to judge them. */
async function full($: Any, w: World, surface: Surface): Promise<{ band: string; write: Any }> {
  w.setFile(`${TOP}/tsconfig.json`, '{}')
  w.setFile(`${TOP}/node_modules/.bin/tsc`, 'x')
  w.rule(isTsc, { exitCode: 2, stdout: `${TS_ERR}\n` })
  w.rule(['diff', '--numstat'], { stdout: '10\t2\ta.ts\0' })
  w.rule(['diff', '--name-status'], { stdout: 'M\0a.ts\0' })
  w.gitStatusOut = porcelain({ head: 'feat/auth', unstaged: 2 })
  w.worktreeOut = WT3
  w.prSeq = [PRS3]
  w.listeners = [{ ...PG }]
  await w.start($, surface)
  w.listeners = [{ ...OURS }, { ...PG }]
  w.setFile(SUMMARY, summaryJson(83.2))
  await w.bash($, 'npx vitest run --coverage', VITEST_OUT)
  const write = await w.write($, A_TS)
  await w.advance(6000)
  await w.turnComplete($)
  await w.untilPr(1, 3 * 60_000)
  await w.advance(10_000)
  return { band: await w.band($, surface, { bodyColumns: 260 }), write }
}

test('C47 with every mod enabled all seven chips and six commands exist', async ($, on) => {
  const w = world(on, { branch: 'feat/auth' })
  const { band, write } = await full($, w, 'terminal')
  for (const m of MODS) expect(band, `${m.id} chip missing`).toContain(m.marker)
  expect(((write.context ?? []) as string[]).join('\n')).toContain('TYPECHECK')
  for (const m of MODS) if (m.command) expect(w.commands.some(c => c === m.command || c.endsWith(`-${m.command}`))).toBe(true)
})

for (const m of MODS) {
  test(`C47 mod.${m.id}.enabled=false removes its chip, command and hook effects`, { options: { [`mod_${m.id}_enabled`]: false } as never }, async ($, on) => {
    const w = world(on, { branch: 'feat/auth' })
    const { band, write } = await full($, w, 'terminal')
    expect(band, `${m.id} chip still shown`).not.toContain(m.marker)
    for (const other of MODS) if (other.id !== m.id) expect(band, `${other.id} chip vanished`).toContain(other.marker)
    if (m.command) expect(w.commands.some(c => c === m.command || c.endsWith(`-${m.command}`))).toBe(false)
    switch (m.id) {
      case 'git':
        expect(w.gitStatusCalls().length).toBe(0)
        break
      case 'diff':
        expect(w.count(c => c.argv.includes('write-tree'))).toBe(0)
        break
      case 'typecheck':
        expect(w.tscCalls().length).toBe(0)
        expect(((write.context ?? []) as string[]).join('')).toBe('')
        break
      case 'pr':
        expect(w.prListCalls().length).toBe(0)
        break
      case 'ports':
        expect(w.lsofCalls().length).toBe(0)
        break
      default:
        break
    }
    expect(w.calls.some(c => base(c.argv[0]) === 'ps')).toBe(false)
  })
}
