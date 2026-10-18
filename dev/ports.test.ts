// Contract statements C40-C43 and C55 (Port Watch). Source: specs/dev.md sections 8 and 13 "Port Watch".
import { test, expect } from 'claude-code/testing'
import { SURFACES, TOP, world, crossCheck, base } from './_harness'
import type { Any, Listener, Surface, World } from './_harness'

const OURS: Listener = { pid: 4242, cmd: 'node', addrs: ['*:3000', '*:3000'], cwd: `${TOP}/app` }
const OURS2: Listener = { pid: 4343, cmd: 'node', addrs: ['*:5173'], cwd: TOP }
const PG: Listener = { pid: 5151, cmd: 'postgres', addrs: ['127.0.0.1:5432'], cwd: '/var/lib/postgresql/data' }
const REDIS: Listener = { pid: 6161, cmd: 'redis-server', addrs: ['[::1]:6379'], cwd: '/var/lib/redis' }

/** Session start with `baseline` listening, then `later` is what listens when the next scan runs. */
async function boot($: Any, w: World, baseline: Listener[], later: Listener[], surface: Surface = 'terminal'): Promise<void> {
  w.listeners = baseline.map(l => ({ ...l }))
  await w.start($, surface)
  w.listeners = later.map(l => ({ ...l }))
  await w.turnComplete($)
  await w.advance(5000)
}

const stopKey = async (ui: Any): Promise<string> => {
  const found = await ui.findAll({ type: 'Button', text: /STOP/ })
  expect(found.length, 'no STOP button drawn for an OURS listener').toBeGreaterThan(0)
  return found[0].key as string
}

const buttons = async (ui: Any, label: RegExp): Promise<{ key?: string; text: string }[]> => ui.findAll({ type: 'Button', text: label })

for (const surface of SURFACES) {
  test(`C40 one agent-started listener -> chip "1 port (3000)"; pane OURS row and "1 other listener" [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await boot($, w, [PG], [OURS, PG], surface)
    const band = await w.band($, surface)
    expect(band).toContain('1 port (3000)')
    crossCheck('C40-band', surface, band)
    const pane = await w.openPane($, surface, 'ports')
    const text = await pane.text()
    expect(text).toContain('OURS')
    expect(text).toContain(':3000 node pid 4242')
    expect(text).toContain('1 other listener')
    expect(text).not.toContain('1 other listeners')
    expect(text).not.toContain('pid 5151') // others are collapsed
    crossCheck('C40-pane', surface, text)
  })

  test(`C40 two ours -> chip "2 ports (3000, 5173)" and several others -> "2 other listeners" [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await boot($, w, [PG, REDIS], [OURS, OURS2, PG, REDIS], surface)
    const band = await w.band($, surface)
    expect(band).toContain('2 ports (3000, 5173)')
    const pane = await w.openPane($, surface, 'ports')
    expect(await pane.text()).toContain('2 other listeners')
    crossCheck('C40-two', surface, band)
  })

  test(`C41 STOP is two-step: first press arms CONFIRM (no kill), second runs "kill -TERM 4242" once; never offered for 5151 [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await boot($, w, [PG], [OURS, PG], surface)
    const pane = await w.openPane($, surface, 'ports')
    const stops = await buttons(pane.ui, /STOP/)
    expect(stops.length).toBe(1)
    expect((await pane.text()).split('STOP').length - 1).toBe(1)
    const key = stops[0]!.key!
    expect(key).toBeDefined()

    await pane.ui.press({ key })
    await w.settle()
    expect((await buttons(pane.ui, /CONFIRM/)).length).toBe(1)
    expect((await buttons(pane.ui, /STOP/)).length).toBe(0)
    expect(w.killCalls().length).toBe(0)

    await pane.ui.press({ key })
    await w.settle()
    expect(w.killCalls().length).toBe(1)
    expect(w.killCalls()[0]!.argv.slice(1)).toEqual(['-TERM', '4242'])
    crossCheck('C41', surface, await pane.text())
  })

  test(`C41 the armed state expires after 5 s [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await boot($, w, [PG], [OURS, PG], surface)
    const pane = await w.openPane($, surface, 'ports')
    const key = await stopKey(pane.ui)
    await pane.ui.press({ key })
    await w.settle()
    expect((await buttons(pane.ui, /CONFIRM/)).length).toBe(1)
    await w.advance(5100)
    expect((await buttons(pane.ui, /CONFIRM/)).length).toBe(0)
    expect((await buttons(pane.ui, /STOP/)).length).toBe(1)
    expect(w.killCalls().length).toBe(0)
  })

  test(`C41 3 s after the kill the pane reports "stopped" [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await boot($, w, [PG], [OURS, PG], surface)
    const pane = await w.openPane($, surface, 'ports')
    const key = await stopKey(pane.ui)
    await pane.ui.press({ key })
    await pane.ui.press({ key })
    await w.advance(3500)
    expect(await pane.text()).toContain('stopped')
  })

  test(`C41 3 s after the kill the pane reports "still running" when the process stays [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    w.killRemoves = false
    await boot($, w, [PG], [OURS, PG], surface)
    const pane = await w.openPane($, surface, 'ports')
    const key = await stopKey(pane.ui)
    await pane.ui.press({ key })
    await pane.ui.press({ key })
    await w.advance(3500)
    expect(await pane.text()).toContain('still running')
  })

  test(`C42 pid whose cwd changed before confirm -> no kill [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await boot($, w, [PG], [OURS, PG], surface)
    const pane = await w.openPane($, surface, 'ports')
    const key = await stopKey(pane.ui)
    await pane.ui.press({ key })
    await w.settle()
    w.listeners = w.listeners.map(l => (l.pid === 4242 ? { ...l, cwd: '/somewhere/else' } : l))
    await w.advance(1000)
    const confirm = await buttons(pane.ui, /CONFIRM/)
    const target = confirm[0]?.key ?? key
    await pane.ui.press({ key: target }).catch(() => undefined)
    await w.settle()
    expect(w.killCalls().length).toBe(0)
  })

  test(`C42 pid that now listens on another port -> no kill [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await boot($, w, [PG], [OURS, PG], surface)
    const pane = await w.openPane($, surface, 'ports')
    const key = await stopKey(pane.ui)
    await pane.ui.press({ key })
    await w.settle()
    w.listeners = w.listeners.map(l => (l.pid === 4242 ? { ...l, addrs: ['*:4000'] } : l))
    await w.advance(1000)
    const confirm = await buttons(pane.ui, /CONFIRM/)
    await pane.ui.press({ key: confirm[0]?.key ?? key }).catch(() => undefined)
    await w.settle()
    expect(w.killCalls().length).toBe(0)
  })

  test(`C55 a second press after the 5 s window re-arms from the start (needs two fresh presses) [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await boot($, w, [PG], [OURS, PG], surface)
    const pane = await w.openPane($, surface, 'ports')
    const key = await stopKey(pane.ui)
    await pane.ui.press({ key })
    await w.advance(6000)
    await pane.ui.press({ key }) // expired: this is a fresh first press
    await w.settle()
    expect(w.killCalls().length).toBe(0)
    expect((await buttons(pane.ui, /CONFIRM/)).length).toBe(1)
    await pane.ui.press({ key })
    await w.settle()
    expect(w.killCalls().length).toBe(1)
  })

  test(`C55 a listener that existed at session start is not OURS: no STOP element, no kill [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    const pre: Listener = { pid: 7000, cmd: 'node', addrs: ['*:8080'], cwd: TOP }
    await boot($, w, [pre, PG], [pre, PG], surface)
    const pane = await w.openPane($, surface, 'ports')
    expect((await buttons(pane.ui, /STOP|CONFIRM/)).length).toBe(0)
    expect(await pane.text()).not.toContain('STOP')
    expect(w.killCalls().length).toBe(0)
  })

  test(`C55 a new listener whose cwd is outside the repo is not OURS: no STOP element [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    await boot($, w, [], [PG], surface)
    const pane = await w.openPane($, surface, 'ports')
    expect((await buttons(pane.ui, /STOP|CONFIRM/)).length).toBe(0)
    const text = await pane.text()
    expect(text).not.toContain('STOP')
    expect(text).toContain('1 other listener')
    const band = await w.band($, surface)
    expect(band).not.toContain('port (')
    expect(band).not.toContain('ports (')
  })

  test(`C55 a new listener under a linked worktree of the repo is OURS [${surface}]`, async ($, on) => {
    const w = world(on, { surfaces: [surface] })
    const wt: Listener = { pid: 4545, cmd: 'node', addrs: ['*:3100'], cwd: '/work/wt/fix-login/app' }
    await boot($, w, [PG], [wt, PG], surface)
    const band = await w.band($, surface)
    expect(band).toContain('1 port (3100)')
  })
}

test('C43 no ps call is ever made; only lsof (two fixed shapes) and "kill -TERM <pid>" run for ports', async ($, on) => {
  const w = world(on)
  await boot($, w, [PG], [OURS, PG])
  const pane = await w.openPane($, 'terminal', 'ports')
  const key = await stopKey(pane.ui)
  await pane.ui.press({ key })
  await pane.ui.press({ key })
  await w.advance(20_000)

  expect(w.calls.some(c => base(c.argv[0]) === 'ps')).toBe(false)
  expect(w.calls.some(c => c.argv.some(a => a === 'ps'))).toBe(false)
  const lsof = w.lsofCalls()
  expect(lsof.length).toBeGreaterThanOrEqual(2)
  for (const c of lsof) {
    const rest = c.argv.slice(1)
    const isList = JSON.stringify(rest) === JSON.stringify(['-nP', '-iTCP', '-sTCP:LISTEN', '-Fpcn'])
    const isCwd = rest.length === 6 && rest[0] === '-a' && rest[1] === '-p' && /^\d+(,\d+)*$/.test(rest[2]!) && rest[3] === '-d' && rest[4] === 'cwd' && rest[5] === '-Fpn'
    expect(isList || isCwd, `unexpected lsof argv: ${c.argv.join(' ')}`).toBe(true)
  }
  const kills = w.killCalls()
  expect(kills.length).toBe(1)
  expect(kills[0]!.argv.slice(1)).toEqual(['-TERM', '4242'])
  for (const c of w.calls) {
    expect(c.argv.join(' ')).not.toMatch(/(^| )-(9|KILL|SIGKILL)( |$)/)
  }
})
