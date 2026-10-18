// Contract statements for /changes freshness (specs/dev.md section 3 + 7.7 clarification, 2026-10-12):
// /changes forces a fresh snapshot ignoring changes.minRefreshSec and lists up to 5 files as `path +a −d`.
import { test, expect } from 'claude-code/testing'
import { SURFACES, world } from './_harness'
import { numstat, nameStatus } from './_rewritten'

type Rows = [string, number, number][]
const A: Rows = [['a.ts', 3, 1]]
const B: Rows = [['a.ts', 10, 2], ['b.ts', 5, 0]]

/** World whose `git diff` fixtures follow the mutable `cur.rows`. */
function diffWorld(on: never, surface: (typeof SURFACES)[number], cur: { rows: Rows }) {
  const w = world(on, { surfaces: [surface] })
  w.rule(['diff', '--numstat'], () => ({ stdout: numstat(cur.rows) }))
  w.rule(['diff', '--name-status'], () => ({ stdout: nameStatus(cur.rows) }))
  return w
}
const numstatCalls = (w: any): number => w.count((c: any) => c.argv.includes('diff') && c.argv.includes('--numstat'))

for (const surface of SURFACES) {
  test(`D01 /changes right after a Bash edit (inside the 5 s window) reports the new file count and totals [${surface}]`, async ($, on) => {
    const cur = { rows: A }
    const w = diffWorld(on as never, surface, cur)
    await w.start($, surface)
    await w.advance(6000)
    await w.turnComplete($)
    await w.advance(6000)
    cur.rows = B
    await w.bash($, "sed -i '' 's/x/y/' a.ts && touch b.ts", '') // non-read-only Bash that changes tracked files
    const t = await w.cmd($, 'changes')
    expect(t).toContain('2 files')
    expect(t).toContain('+15')
    expect(t).toContain('−2')
  })

  test(`D02 /changes twice in a row with no changes is stable [${surface}]`, async ($, on) => {
    const cur = { rows: B }
    const w = diffWorld(on as never, surface, cur)
    await w.start($, surface)
    await w.advance(6000)
    await w.turnComplete($)
    await w.advance(6000)
    const first = await w.cmd($, 'changes')
    const second = await w.cmd($, 'changes')
    expect(first).toContain('2 files')
    expect(second).toBe(first)
  })

  test(`D03 /changes answers from cached state when the snapshot call fails [${surface}]`, async ($, on) => {
    const cur = { rows: B }
    const w = diffWorld(on as never, surface, cur)
    await w.start($, surface)
    await w.advance(6000)
    await w.turnComplete($)
    await w.advance(6000)
    w.rule(['write-tree'], { exitCode: 128, stderr: 'fatal: snapshot failed\n' })
    await w.bash($, 'make build', '')
    const t = await w.cmd($, 'changes')
    expect(t).toContain('2 files')
    expect(t).toContain('a.ts')
  })

  test(`D04 /changes names changed files with +a −d, at most 5 [${surface}]`, async ($, on) => {
    const rows: Rows = [['a.ts', 10, 2], ['b.ts', 9, 1], ['c.ts', 8, 1], ['d.ts', 7, 0], ['e.ts', 6, 0], ['f.ts', 2, 0], ['g.ts', 1, 0]]
    const w = diffWorld(on as never, surface, { rows })
    await w.start($, surface)
    await w.advance(6000)
    await w.turnComplete($)
    await w.advance(6000)
    const t = await w.cmd($, 'changes')
    expect(t).toContain('7 files')
    expect(t).toMatch(/a\.ts\s*\+10\s*−2/)
    const listed = ['a', 'b', 'c', 'd', 'e', 'f', 'g'].filter(n => t.includes(`${n}.ts`))
    expect(listed.length).toBe(5)
  })

  test(`D05 the Session diff pane shows a Bash edit made inside the 5 s window [${surface}]`, async ($, on) => {
    const cur = { rows: A }
    const w = diffWorld(on as never, surface, cur)
    await w.start($, surface)
    await w.advance(6000)
    await w.turnComplete($)
    await w.advance(6000)
    cur.rows = B
    await w.bash($, 'touch b.ts', '')
    const pane = await w.openPane($, surface, 'changes')
    const text = await pane.text()
    expect(text).toContain('2 files')
    expect(text).toContain('b.ts')
  })

  test(`D06 fake-host strictness: an automatic refresh requested inside the 5 s window is not executed until time advances [${surface}]`, async ($, on) => {
    const cur = { rows: A }
    const w = diffWorld(on as never, surface, cur)
    await w.start($, surface)
    await w.advance(6000)
    await w.turnComplete($)
    await w.advance(100)
    const before = numstatCalls(w)
    expect(before, 'a snapshot diff should have run after the turn').toBeGreaterThan(0)
    await w.bash($, 'touch b.ts', '')
    await w.bash($, 'touch c.ts', '')
    expect(numstatCalls(w), 'automatic refresh ran inside changes.minRefreshSec').toBe(before)
  })
}
