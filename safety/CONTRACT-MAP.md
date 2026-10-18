# Contract map: safety (spec section 7)

Files: `harness.ts` (shared, not a test; run-contract.sh must copy the whole `safety/` folder), `protect-write.test.ts`, `protect-bash.test.ts`, `protect-ui.test.ts`, `checkpoint.test.ts`.
Harness: test-bottom hooks mock `session.cwd/id/surfaces`, `ui.toast`, `ui.status`, `fs.stat`, `fs.exists`, `process.run` (a small stateful git simulator), `tool.call` (the spy "next"; `wasCalled()` counts calls that reached it), plus `mock.clock/env/store`.

| # | Test names (prefix) | Notes |
|---|---|---|
| 1 | C01 | |
| 2 | C02 (x2) | |
| 3 | C03 per lockfile (8) + near-miss | |
| 4 | C04 (x2) | vault set / unset (HOME mocked) |
| 5 | C05 (x2) | MultiEdit sent as `tool:'MultiEdit'` |
| 6 | C06 (x2) | |
| 7 | C07 (x2) | symlink via mocked realPath; missing file via fs.stat throw |
| 8 | C08 (x2) | option `protect.caseInsensitive` |
| 9 | C09 | |
| 10 | C10 per command (8) | |
| 10a | C10a deny (7), allowed (3), allow-then-rm | |
| 11 | C11 per command (9) | result must equal bottom result |
| 12 | C12 (x2) | |
| 13 | C13 (x2) | options `protect.mode` |
| 14 | C14 terminal/desktop, C14 30 s expiry, C14b status wireframe | surface via mocked `session.surfaces`; C14b is extra (spec section 3) |
| 15 | C15 (x4) | |
| 16 | C16 (x2) | |
| 17 | C17 | |
| 18 | C18 | error induced by making `fs.stat` throw TypeError |
| 19 | C19 | |
| 20 | C20 | |
| 21 | C21 | |
| 22 | C22 | |
| 23 | C23 (x2) | |
| 24 | C24 | |
| 25 | C25 | |
| 26 | C26 | |
| 27 | C27 | |
| 28 | C28 | |
| 29 | C29 (x3) | |
| 29a | C29a (x2) | |
| 30 | C30 terminal/desktop | |

Skipped: M01 (bypassPermissions, UNVERIFIED), M02 (linked worktree, manual list), `verify-checkpoint.sh` (real git, acceptance script).

## Ambiguities
1. Option key spelling (`protect.mode`, `protect.group.lockfiles`, `protect.mcpRules`, `protect.caseInsensitive`) is taken literally from the spec as `userConfig` keys.
2. C18: the spec does not say how to make the gate throw; the test makes `$.fs.stat` throw. A plugin that guards stat itself may never reach `.catch`; test still asserts the outcomes (deny `.env`, pass-through `a.ts`).
3. C20: the exact argv of the LASTTREE/PARENT `rev-parse` lookups is unspecified; only the order of cp, add, write-tree, commit-tree, update-ref, rm and the first `--show-toplevel` call are asserted.
4. C14: "starts with F" (desktop) / emoji (terminal) is driven by `$.session.surfaces()`; the plugin may use another surface probe.
5. C15 `/protect list` minutes left is matched by `/7\s*(m|min)/` after 3 of 10 minutes.
6. C16 refusal of removing a default entry: tested with `/protect remove yarn.lock`; text must contain `default`.
7. C24/C20 assume the first checkpoint is allowed immediately (lastAt unset). Commit identity read from `process.run` `init.env`.
8. C25: lock presence is read through `$.fs.exists` on the 4th rev-parse line.
9. C27: probe failure is induced by `process.run` rejecting; `start()` is the assumed probe moment.
10. C29/C30: the checkpoint ref spelling is tested via the 8-char session prefix and full-ref prefix; `restore 3` assumes at least that checkpoint number is printable even if fewer exist.
11. C05 MultiEdit and C29a MCP calls are raised through `$.tool.call` with the stated tool names; the typings may reject unknown tools at compile time (loose input).
12. Commands raised via `$.command.run({command,args})`; the `origin` field is left to the engine default.

## Stub run (2026-10-12)
Against an empty stub plugin: before repair 0 pass / file load error; after repair 23 pass / 63 fail, all failures plain assertions; tsc clean.
Repairs: no `test.skip` in the kit (M01/M02 now a comment); harness now answers bottom hooks `session.start`, `command.run`, `turn.complete` (`{text:''}`), `session.end`; `$.state` is not on the test `$`, so state is read from recorded `state.set` writes (keys `protect`, `checkpoint`, matched by `e.key`); option keys use underscores (`protect_mode` etc.).
Intent unchanged. Passing on a stub (silence/absence tests): C02 examples, C03 near-miss, C08 case-sensitive, C10a allowed x3 + allow-then-rm, C11 x9, C12 $FILE, C13 off, C19, C23 x2, C25, C29a default.
New ambiguity: C27/C26/C22 read `state.set` writes with `key` `checkpoint` and `.state/.count` fields (the ProtectView/CheckpointView shapes).

## Harness convention (kit)
Bottom hooks standing in for noun calls answer `{ value: <result> }` (session.cwd/id/surfaces, command.list, command.register, ui.toast/status, fs.exists/stat, process.run); a bare return is skipped by the kit ("no implementation"). Lifecycle events (session.start, command.run, turn.complete, session.end) answer their result directly. state.set passes through; tool.call is the spy.
