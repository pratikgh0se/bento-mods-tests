import { test, expect } from 'claude-code/testing'
import { world, REPO } from './_harness'

type W = Awaited<ReturnType<typeof world>>

const items = (n: number, done: number, prefix = 'task'): string[] =>
  Array.from({ length: n }, (_, i) => `- [${i < done ? 'x' : ' '}] ${prefix} ${i + 1}`)

const plan = (n: number, done: number): string =>
  ['# Plan', '', ...items(n, done), '', '```md', '- [ ] fenced one', '- [x] fenced two', '```', ''].join('\n')

/** Create/overwrite a file in the virtual fs, then raise the main-thread Write/Edit result for it. */
async function write(w: W, rel: string, text: string, tool: 'Write' | 'Edit' = 'Write'): Promise<void> {
  const path = `${REPO}/${rel}`
  w.putFile(path, text)
  if (tool === 'Write') await w.call('Write', { file_path: path, content: text })
  else await w.call('Edit', { file_path: path, old_string: 'x', new_string: 'y' })
  await w.clock.settle()
}
const chip = (w: W): Promise<string> => w.bandBoth({ isWorking: false })

// ---- C26 ----
test('C26 Write docs/plans/x.md (12 boxes, 7 done, fenced ignored) -> SPEC 7/12; Edit -> SPEC 8/12', async ($, on) => {
  const w = await world($, on)
  await write(w, 'docs/plans/x.md', plan(12, 7))
  expect(await chip(w)).toContain('SPEC 7/12')
  await write(w, 'docs/plans/x.md', plan(12, 8), 'Edit')
  expect(await chip(w)).toContain('SPEC 8/12')
})

test('C26b /spec clear -> no chip; plain notes.md Write -> no chip', async ($, on) => {
  const w = await world($, on)
  await write(w, 'docs/plans/x.md', plan(12, 7))
  expect(await chip(w)).toContain('SPEC 7/12')
  await w.cmd('spec', 'clear')
  expect(await chip(w)).not.toContain('SPEC')
  await write(w, 'notes.md', plan(4, 1))
  expect(await chip(w)).not.toContain('SPEC')
})

test('C26c /spec docs/plans/y.md pins y', async ($, on) => {
  const w = await world($, on)
  w.putFile(`${REPO}/docs/plans/y.md`, plan(6, 2))
  await w.cmd('spec', 'docs/plans/y.md')
  expect(await chip(w)).toContain('SPEC 2/6')
  expect(await w.cmd('spec')).toContain('pinned')
})

test('C26d chip shows next: first unchecked item when there is room', async ($, on) => {
  const w = await world($, on)
  await write(w, 'docs/plans/x.md', plan(5, 2))
  expect(await chip(w)).toContain('next: task 3')
})

// ---- C29 ----
test('C29 auto-discovery: latest matching edit wins, Read does not count', async ($, on) => {
  const w = await world($, on)
  await write(w, 'docs/plans/a.md', items(3, 1).join('\n'))
  await write(w, 'docs/specs/b.md', items(5, 2).join('\n'))
  expect(await chip(w)).toContain('SPEC 2/5')
  await w.call('Read', { file_path: `${REPO}/docs/plans/a.md` }, { readOnly: true })
  expect(await chip(w)).toContain('SPEC 2/5')
  expect(await w.cmd('spec')).toContain('auto')
})

test('C29b pin a: later Edit of b changes nothing; /spec says pinned', async ($, on) => {
  const w = await world($, on)
  await write(w, 'docs/plans/a.md', items(3, 1).join('\n'))
  await write(w, 'docs/specs/b.md', items(5, 2).join('\n'))
  await w.cmd('spec', 'docs/plans/a.md')
  expect(await chip(w)).toContain('SPEC 1/3')
  await write(w, 'docs/specs/b.md', items(5, 4).join('\n'), 'Edit')
  expect(await chip(w)).toContain('SPEC 1/3')
  expect(await w.cmd('spec')).toContain('pinned')
})

test('C29c /spec clear -> no chip + "No spec tracked"; next matching Edit tracks again (auto)', async ($, on) => {
  const w = await world($, on)
  await write(w, 'docs/plans/a.md', items(3, 1).join('\n'))
  await write(w, 'docs/specs/b.md', items(5, 2).join('\n'))
  await w.cmd('spec', 'docs/plans/a.md')
  await w.cmd('spec', 'clear')
  expect(await chip(w)).not.toContain('SPEC')
  expect(await w.cmd('spec')).toContain('No spec tracked')
  await write(w, 'docs/specs/b.md', items(5, 3).join('\n'), 'Edit')
  expect(await chip(w)).toContain('SPEC 3/5')
  expect(await w.cmd('spec')).toContain('auto')
})

test('C29d pinning a file without checkboxes says "no checkboxes" and keeps the previous state', async ($, on) => {
  const w = await world($, on)
  await write(w, 'docs/specs/b.md', items(5, 2).join('\n'))
  w.putFile(`${REPO}/docs/plans/empty.md`, '# nothing to check here\n')
  const out = await w.cmd('spec', 'docs/plans/empty.md')
  expect(out).toContain('no checkboxes')
  expect(await chip(w)).toContain('SPEC 2/5')
  expect(await w.cmd('spec')).toContain('auto')
})

test('C29e spec.auto=false: no auto-discovery', { options: { 'spec_auto': false } }, async ($, on) => {
  const w = await world($, on)
  await write(w, 'docs/plans/a.md', items(3, 1).join('\n'))
  expect(await chip(w)).not.toContain('SPEC')
  expect(await w.cmd('spec')).toContain('No spec tracked')
})

test('C29f auto candidate without a checkbox is not accepted', async ($, on) => {
  const w = await world($, on)
  await write(w, 'docs/plans/none.md', '# plan without boxes\n')
  expect(await chip(w)).not.toContain('SPEC')
})
