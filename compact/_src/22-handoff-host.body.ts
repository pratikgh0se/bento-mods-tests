// Host hold rule for /handoff (spec 2.x "Host hold rule", headless clarification, 2.3 headings).
// The fake host refuses prompt.submit / session.compact while the originating command.run dispatch is in flight
// (S.inCmd, with every fs call yielding so delay-0 timers can fire inside that window). A refusal reaches the plugin
// as a rejected call. Timers that fire after the command returned are accepted.

const FAILED = 'HANDOFF failed'

async function waitingRepo(gitignore: string | null, fsYields = 1) {
  return async ($: Any, on: Any) => {
    const w = await world($, on)
    w.S.fsYields = fsYields
    if (gitignore !== null) w.S.files.set(`${REPO}/.gitignore`, gitignore)
    await w.start()
    return w
  }
}

const GITIGNORES: [string, string | null][] = [
  ['no .gitignore', null],
  ['.gitignore with handoff/', 'node_modules/\nhandoff/\n'],
  ['.gitignore without handoff/', 'node_modules/\ndist/\n'],
]

for (const [label, gi] of GITIGNORES) {
  for (const yields of [1, 4]) {
    t(`H01 /handoff foo (${label}, fs takes ${yields} macrotask(s)): prompt submitted once, writing, no failure text`, async ($, on) => {
      const w = await (await waitingRepo(gi, yields))($, on)
      const txt = await w.cmd('handoff', 'foo')
      await w.drain()
      expect(w.S.holdRefusals).toBe(0)
      expect(w.S.submits.length).toBe(1)
      expect(w.S.submitAttempts).toBe(1)
      expect((await w.state('handoff')).state).toBe('writing')
      expect(w.allText(txt)).not.toContain(FAILED)
      for (const surface of SURFACES) expect(await w.band(surface)).not.toContain(FAILED)
    })
  }
}

t('H02 /handoff --no-compact foo behind a slow .gitignore read: submitted once, writing, no failure text', async ($, on) => {
  const w = await (await waitingRepo('handoff/\n', 3))($, on)
  const txt = await w.cmd('handoff', '--no-compact foo')
  await w.drain()
  expect(w.S.holdRefusals).toBe(0)
  expect(w.S.submits.length).toBe(1)
  expect((await w.state('handoff')).state).toBe('writing')
  expect(w.allText(txt)).not.toContain(FAILED)
})

t('H03 /handoff retry from failed behind a slow .gitignore read: submitted again once, writing, no new failure text', async ($, on) => {
  const w = await (await waitingRepo('handoff/\n', 3))($, on)
  await w.cmd('handoff', 'foo')
  await w.complete() // the model wrote nothing -> failed
  expect((await w.state('handoff')).state).toBe('failed')
  const before = w.S.submits.length
  const noticesBefore = w.S.notices.length
  const logsBefore = w.S.logs.length
  const txt = await w.cmd('handoff', 'retry')
  await w.drain()
  expect(w.S.holdRefusals).toBe(0)
  expect(w.S.submits.length).toBe(before + 1)
  expect((await w.state('handoff')).state).toBe('writing')
  const fresh = [txt, ...w.S.notices.slice(noticesBefore), ...w.S.logs.slice(logsBefore)].join('\n')
  expect(fresh).not.toContain(FAILED)
  for (const surface of SURFACES) expect(await w.band(surface)).not.toContain(FAILED)
})

t('H06 /handoff go in ready: compact called once, from a timer after the command returned', async ($, on) => {
  const w = await (await waitingRepo('handoff/\n'))($, on)
  await w.toReady()
  const txt = await w.cmd('handoff', 'go')
  await w.drain()
  expect(w.S.holdRefusals).toBe(0)
  expect(w.S.compactAttempts).toBe(1)
  expect(w.S.compacts.length).toBe(1)
  expect((await w.state('handoff')).state).toBe('done')
  expect(w.allText(txt)).not.toContain('Turn running')
})

t('H09 prompt: the eight heading lines appear as whole lines, in order, and no other "## " line is in it', async ($, on) => {
  const w = await (await waitingRepo(null))($, on)
  await w.cmd('handoff', 'foo')
  await w.drain()
  expect(w.S.submits.length).toBe(1)
  const lines: string[] = (w.S.submits[0].text as string).split('\n').map((l: string) => l.replace(/\r$/, ''))
  for (const h of HEADINGS) expect(lines).toContain(h)
  const hashed = lines.filter(l => l.startsWith('## '))
  expect(hashed).toEqual(HEADINGS)
})

t('H10 prompt: tells the model to write the headings exactly and not to copy the guide text', async ($, on) => {
  const w = await (await waitingRepo(null))($, on)
  await w.cmd('handoff', 'foo')
  await w.drain()
  const text: string = w.S.submits[0].text
  expect(text).toMatch(/exact/i)
  expect(text).toMatch(/(not|n't|never)[^.\n]{0,40}cop(y|ied)|cop(y|ied)[^.\n]{0,40}\b(not|never)\b/i)
})

// ---- not expressible with this kit (verified 2026-10-12): the plugin's call can only be rejected with the kit's OWN
// error text. A test hook that throws is skipped and the caller sees the engine default error ("no implementation for
// prompt.submit" / "next() passed an argument with messages that are not a list"); `{deny}` is not a valid answer for
// these two events. So a hold text ("called from a command.run hook ...") or the headless text cannot be injected.
// The harness keeps the knobs (S.rejectSubmit / S.rejectCompact / S.compact = 'headless') for a kit that can.
skip('H04 first two submit attempts refused with the hold text: retried, one prompt enters, no user-visible failure', 'kit cannot surface a hook error text to the caller')
skip('H05 every submit attempt refused with the hold text: failed, "prompt not sent" + "/handoff retry"; 3rd failure "Write the file by hand"', 'kit cannot surface a hook error text to the caller')
skip('H07 /handoff go: first compact attempt refused with the hold text: retried, succeeds once', 'kit cannot surface a hook error text to the caller')
skip('H08 /handoff go headless: stays ready; text has "headless" and "interactive", not "Turn running"', 'kit cannot surface a hook error text to the caller')
