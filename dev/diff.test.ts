// Contract statements C05-C07 (Session Diff). Source: specs/dev.md section 13 "Diff".
import { test, expect } from 'claude-code/testing'
import { SURFACES, TOP, world, crossCheck } from './_harness'

const NUMSTAT = '10\t2\ta.ts\0-\t-\tlogo.png\0'
const NAME_STATUS = 'M\0a.ts\0A\0logo.png\0'

for (const surface of SURFACES) {
  test(`C05 tree-to-tree diff: chip "2 files +10 −2", pane row for logo.png shows bin [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    w.rule(['diff', '--numstat'], { stdout: NUMSTAT })
    w.rule(['diff', '--name-status'], { stdout: NAME_STATUS })
    await w.start($, surface)
    await w.advance(6000)
    await w.turnComplete($)
    await w.advance(6000)

    const numstat = w.calls.find(c => c.argv.includes('diff') && c.argv.includes('--numstat'))
    expect(numstat, 'git diff --numstat BASE CUR was never run').toBeDefined()
    const trees = numstat!.argv.filter(a => /^tree\d+$/.test(a))
    expect(trees.length).toBe(2)
    expect(trees[0]).not.toBe(trees[1])

    const band = await w.band($, surface)
    expect(band).toContain('2 files')
    expect(band).toContain('+10')
    expect(band).toContain('−2')
    crossCheck('C05-band', surface, band)

    const pane = await w.openPane($, surface, 'changes')
    const text = await pane.text()
    expect(text).toContain('SESSION DIFF')
    expect(text).toContain('2 files')
    expect(text).toContain('a.ts')
    expect(text).toMatch(/logo\.png[^]*?\bbin\b/)
    crossCheck('C05-pane', surface, text)
  })

  test(`C06 an Edit result for src/x.ts is listed in the pane before the next snapshot [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await w.start($, surface)
    await w.edit($, `${TOP}/src/x.ts`, ['+a'])
    await w.advance(1000)
    const pane = await w.openPane($, surface, 'changes')
    const text = await pane.text()
    expect(text).toContain('src/x.ts')
    crossCheck('C06', surface, text)
  })

  test(`C07 no process available: structuredPatch +a +b -c gives chip "+2 −1" and pane header "(tools only)" [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface], procDown: true })
    await w.start($, surface)
    await w.edit($, `${TOP}/src/x.ts`, ['+a', '+b', '-c'])
    await w.advance(1000)
    const band = await w.band($, surface)
    expect(band).toContain('+2 −1')
    crossCheck('C07-band', surface, band)
    const pane = await w.openPane($, surface, 'changes')
    const text = await pane.text()
    expect(text).toContain('(tools only)')
    crossCheck('C07-pane', surface, text)
  })
}
