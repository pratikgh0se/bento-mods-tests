/* eslint-disable @typescript-eslint/no-explicit-any */
import { test, expect } from 'claude-code/testing'
import { SURFACES, T0, HOUR, DAY, rig, textOf } from './_kit'

test('C27 tool.call for Bash returns the engine result unchanged', async ($, on) => {
  const answer = { result: 'engine-said-ok' }
  ;(on as any)('tool.call', () => answer)
  const r = rig($, on)
  await r.start()
  const res = await ($ as any).tool.call({ tool: 'Bash', input: { command: 'echo hi' }, tool_use_id: 'tu-1' })
  expect((res as any).result).toBe(answer.result)
})

for (const surface of SURFACES) {
  test(`C27 ui.render AbovePrompt with hasSurvey:true returns exactly the inner tree [${surface}]`, async ($, on) => {
    const r = rig($, on, { beneathInner: 'SENTINEL-INNER' })
    await r.start()
    await r.measure({ five: [62, T0 + 2 * HOUR], seven: [71, T0 + 3 * DAY] })
    const tree = await r.bandTree(surface, { hasSurvey: true })
    expect(textOf(tree)).toBe('SENTINEL-INNER')
    expect(tree).toMatchObject({ type: 'Text' })
  })

  test(`C28 the band keeps the inner (beneath) tree and adds the usage row [${surface}]`, async ($, on) => {
    const r = rig($, on, { beneathInner: 'SENTINEL-INNER' })
    await r.start()
    await r.measure({ five: [62, T0 + 2 * HOUR], seven: [71, T0 + 3 * DAY] })
    const b = await r.band(surface)
    expect(b).toContain('SENTINEL-INNER')
    expect(b).toContain('5H')
    expect(b).toContain('71%')
  })

  test(`C29 maxRows 2 (below minBandRows): the usage row is absent [${surface}]`, async ($, on) => {
    const r = rig($, on, { beneathInner: 'SENTINEL-INNER' })
    await r.start()
    await r.measure({ five: [62, T0 + 2 * HOUR], seven: [71, T0 + 3 * DAY] })
    const b = await r.band(surface, { maxRows: 2 })
    expect(b).not.toContain('5H')
    expect(b).not.toContain('7D')
    expect(b).toContain('SENTINEL-INNER')
    // positive control: with enough rows the same state shows the usage row
    expect(await r.band(surface, { maxRows: 6 })).toContain('5H')
  })
}
