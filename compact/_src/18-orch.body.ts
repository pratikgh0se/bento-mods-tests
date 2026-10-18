// Statements 18, 19, 20: Orchestrator mode, budget.

function orchSections(sections: Any[]): Any[] {
  return sections.filter(s => s.id === 'compact:orchestrator')
}
const ENGINE_IDS = ENGINE_SECTIONS.map(s => s.id)

t('C18 ON by default (no store key): exactly one compact:orchestrator section, session scope, <= 280 chars', async ($, on) => {
  const w = await world($, on)
  await w.start()
  const r = await w.compose()
  const mine = orchSections(r.sections)
  expect(mine.length).toBe(1)
  expect(mine[0].scope).toBe('session')
  expect(mine[0].text.length).toBeLessThanOrEqual(280)
  expect(mine[0].text).toContain('ALWAYS set model')
  expect(mine[0].text).toContain('Sonnet')
  expect(mine[0].text).toContain('Haiku')
  // budget: <= 120 tokens at 4 chars/token, and it is the ONLY thing the plugin adds
  expect(Math.ceil(mine[0].text.length / 4)).toBeLessThanOrEqual(120)
  expect(r.sections.length).toBe(ENGINE_SECTIONS.length + 1)
})

t('C18 engine sections are unchanged and in order', async ($, on) => {
  const w = await world($, on)
  await w.start()
  const r = await w.compose()
  expect(r.sections.slice(0, ENGINE_SECTIONS.length)).toEqual(ENGINE_SECTIONS)
  expect(r.sections.slice(0, ENGINE_IDS.length).map((s: Any) => s.id)).toEqual(ENGINE_IDS)
})

t('C18 stays on across session.start', async ($, on) => {
  const w = await world($, on)
  await w.start()
  await w.start()
  expect(orchSections((await w.compose()).sections).length).toBe(1)
})

t('C18 /orch off without --yes: prints "cold turn" and a dollar figure, stays on', async ($, on) => {
  const w = await world($, on)
  await w.scene({ tokens: 350_000 })
  const txt = await w.cmd('orch', 'off')
  expect(txt).toContain('cold turn')
  expect(txt).toMatch(/\$\d/)
  expect(orchSections((await w.compose()).sections).length).toBe(1)
})

t('C18 /orch off --yes: zero sections added, result equals engine input; persisted across session.start; /orch on --yes restores', async ($, on) => {
  const w = await world($, on)
  await w.scene({ tokens: 350_000 })
  await w.cmd('orch', 'off --yes')
  let r = await w.compose()
  expect(r.sections).toEqual(ENGINE_SECTIONS)
  expect(JSON.stringify(r)).toBe(JSON.stringify({ sections: ENGINE_SECTIONS }))
  await w.start()
  r = await w.compose()
  expect(r.sections).toEqual(ENGINE_SECTIONS)
  await w.cmd('orch', 'on --yes')
  r = await w.compose()
  expect(orchSections(r.sections).length).toBe(1)
})

t('C18 /orch on without --yes (while off) prints the estimate and does nothing', async ($, on) => {
  const w = await world($, on, { store: { 'orch:on': { v: 1, on: false } } })
  await w.scene({ tokens: 350_000 })
  const txt = await w.cmd('orch', 'on')
  expect(txt).toContain('cold turn')
  expect(orchSections((await w.compose()).sections).length).toBe(0)
})

t('C18 store key wins over option: store off beats orch.enabled=true', async ($, on) => {
  const w = await world($, on, { store: { 'orch:on': { v: 1, on: false } } })
  await w.start()
  expect(orchSections((await w.compose()).sections).length).toBe(0)
})

t('C18 store key wins over option: store on beats orch.enabled=false', async ($, on) => {
  const w = await world($, on, { store: { 'orch:on': { v: 1, on: true } } })
  await w.start()
  expect(orchSections((await w.compose()).sections).length).toBe(1)
}, { options: { 'orch_enabled': false } })

t('C18 option orch.enabled=false is the first-run default when no store key exists', async ($, on) => {
  const w = await world($, on)
  await w.start()
  expect(orchSections((await w.compose()).sections).length).toBe(0)
}, { options: { 'orch_enabled': false } })

t('C18 state atom compact.orch.on follows the switch', async ($, on) => {
  const w = await world($, on)
  await w.scene({ tokens: 350_000 })
  expect((await w.state('orch')).on).toBe(true)
  await w.cmd('orch', 'off --yes')
  expect((await w.state('orch')).on).toBe(false)
})

// ---- statement 19 ----
t('C19 the section is identical on two successive composes and after a session.compact event', async ($, on) => {
  const w = await world($, on)
  await w.start()
  const a = JSON.stringify(await w.compose())
  const b = JSON.stringify(await w.compose())
  expect(b).toBe(a)
  await w.compact('manual')
  const c = JSON.stringify(await w.compose())
  expect(c).toBe(a)
  expect(orchSections(JSON.parse(c).sections).length).toBe(1)
})

// ---- statement 20 ----
t('C20 /orch status mentions CLAUDE_CODE_SUBAGENT_MODEL_FORCE as not recommended; plugin never writes settings or env', async ($, on) => {
  const w = await world($, on, { settingsEnv: { CLAUDE_CODE_SUBAGENT_MODEL: 'sonnet' } })
  await w.scene({ tokens: 350_000 })
  const txt = await w.cmd('orch', 'status')
  expect(txt).toContain('CLAUDE_CODE_SUBAGENT_MODEL_FORCE')
  expect(txt).toContain('not recommended')
  await w.cmd('orch', 'off --yes')
  await w.cmd('orch', 'on --yes')
  expect(w.S.envSets.length).toBe(0)
  expect(w.S.configSets.length).toBe(0)
})

t('C20 /orch status works when the env var is not set', async ($, on) => {
  const w = await world($, on, { settingsEnv: {} })
  await w.scene({ tokens: 350_000 })
  const txt = await w.cmd('orch', 'status')
  expect(txt).toContain('CLAUDE_CODE_SUBAGENT_MODEL_FORCE')
  expect(txt).toContain('not recommended')
})
