# awareness contract map

Source: `specs/awareness.md` section 9 (statements 1-31) + conventions 2, 3, 7, 10. Helpers: `_harness.ts` (mocked clock/store/env, in-memory fs under `/tmp/awareness-test`, captured `ui.toast`/`ui.notify`/`audio.play`). Files: `headsup.test.ts`, `focus.test.ts`, `nowdoing.test.ts`, `spec.test.ts`, `robustness.test.ts`.

| Stmt | Test names | Notes |
|---|---|---|
| 1 | C01, C01b | C01b asserts `timeoutMs` 6000 (section 1 edge cases) |
| 2 | C02 | 82, 83 (none), 65, 85 (second toast, 61 s gap) |
| 3 | C03, C03b | C03b extra: queued pace (p4) is released before bigOutput (p5) |
| 4 | C04, C04b | only 3-4 distinct triggers possible (see ambiguities) |
| 5 | C05 | bigOutput shown, context queued, context cleared to 60 |
| 6 | C06, C06b, C06c | HOT = 71%/3 d; ON PACE = 40%/3 d; five_hour 30%/4 h only |
| 7 | C07, C07b, C07c | option `cache.ttl='1h'`; running turn; 30000 tokens |
| 8 | C08, C08b | |
| 9 | C09, C09b, C09c | C09b/C09c cover DONE toast and 30 s command (section 1.2) |
| 10 | C10, C10b | flag and `backgroundTaskId` |
| 11 | C11, C11b | vault dir is virtual; http/curl answered by mock |
| 12 | C12, C12b, C12c | C12c also covers default `savvy-*` allowTypes |
| 13 | C13, C13b, C13c | |
| 14 | C14, C14b | |
| 15 | C15 | both surfaces, texts must be equal |
| 16 | C16, C16b | C16 also checks `/headsup status` lists `context` while held |
| 17 | C17, C17b | 4th block break 15:00 |
| 18 | C18, C18b | |
| 19 | C19, C19b | |
| 20 | C20 | |
| 21 | C21 | |
| 22 | C22 | |
| 23 | C23 | |
| 24 | C24, C24b | C24b: tool registered at session.start |
| 25 | C25 | |
| 26 | C26, C26b, C26c, C26d | |
| 27 | C27, C27b | C27b depends on the shape of an inner tree (see ambiguities) |
| 28 | C28, C28b, C28c, C28d | |
| 29 | C29, C29b-C29f | |
| 30 | C30, C30b | C30b uses `/focus skip` to end the block 20 s after a toast |
| 31 | C31, C31b | C31 uses a fake `dev` plugin (`fakeDev`) owning `dev.toast` |

Skipped (UNVERIFIED / manual): none skipped as `test.skip`; all 31 statements are mocked-testable. Manual list from section 10 (real 2:00 toast, real chime, launchctl Ollama toggle, real spec edit, row coexistence, mascot probe) is not automated.

## Ambiguities (most literal reading chosen)
1. Cache option name: statement 7 says "ttl option 1h"; awareness has no named option, so `cache.ttl` (same as usage.md) is used.
2. Cache timing: asserted at t0+3545 s (5 s slack) because the check timer alignment is unspecified; "none at +3500 s" is exact.
3. Statement 4 says "five triggers"; only context, pace, bigOutput (+ noModel when enabled) can be raised at one instant without moving the clock. C04 uses 3, C04b uses 4; the "<= 5 in 4 min, gap >= 60 s" assertions are kept.
4. Statement 3 order is made deterministic by raising context before bigOutput (no clock move between).
5. Subagent events: the harness passes `agentId` as an extra field of `$.tool.call` / `$.turn.step` input; the typings do not show it on `$.tool.call`'s args.
6. Surfaces for toast tests are set through the mocked `session.surfaces` op ([desktop] by default, avoiding emoji); UI tests mount both surfaces regardless.
7. Equal text on both surfaces (conventions 10.2) is asserted whole (`bandBoth`): desktop Svg `alt` must equal terminal text.
8. Focus count: "count increments" is read as `$.state` `focus.count` rising by 1 after the first block end; statement 17 "after the 4th block": test loops start / 25 min / `skip` of the short break x4. Whether `skip` of a break returns to idle is assumed.
9. `/focus skip` is assumed to count as a block end for the digest (C30b) because no other way exists to end a block 20 s after a toast.
10. Store shape for `focus:state` (C19) is assumed to equal the FocusView fields plus `v:1`.
11. Unvisited phase glyph is assumed to be `▫` (only REPORT shows it in the spec string); current `▶`, visited `▪`.
12. Digest text: `1 notice` is asserted by substring (`1 notices` also passes); ids are the lowercase trigger ids `context`, `pace`.
13. The `ui.render` bottom tree for C27b is a guessed element description `{type:'Text', props:{}, children:[...]}`; the kit may need another shape.
14. C31 needs the kit to let a fake `dev` plugin set an undeclared state atom; if the engine requires a declared atom the fake plugin must declare it.
15. Command names are assumed unprefixed (`command.list` mock returns none, so no collision).

## Harness repair log (stub run)
- Stub plugin run: 18 pass / 49 fail (all fail on assertions; the passes are silence tests). tsc clean against claude-code.d.ts.
- Fixes: default `ui.render` bottom answering `{type:'engine',ref:0}`; plugin state read via recorded `state.set` (Engine has no `state` noun; missing atom reads as `{}`); `session.compact` / `session.end` bottoms return their required shapes; option keys use underscores (`headsup_trigger_noModel`, `cache_ttl`, `spec_auto`, `headsup_digestAfterFocus`); band reader falls back to a shape-agnostic string walk and was verified against a probe plugin drawing both a terminal Text and a desktop Svg alt; `timeoutMs: 120000` on long-advance tests; guards so assertions (not TypeErrors) fail on an inert plugin.
- Assertion intent changes: none.

- Referee fixes: C17/C17b advance exactly 25 min (band read at block end); C24b accepts registered name `phase` or `mcp__awareness__phase`.

## Round 2 (awareness2): `lifecycle.test.ts`
Source: spec clarification "REPORT (decided 2026-10-12)" + section 1.2 / 2. Harness additions: `streamStep()` (chunk-by-chunk `turn.step`, band reads between chunks), `staleAfterSec` world option (state/ui `$` calls rejected for a tool.call frame that ran longer than N mocked s, until the chain settles; `staleHits` counts rejections), ToolOpts `reject` / `hang`, `turnComplete` sends the full required fields (answer, durationMs, isAborted).
| Cases | Behaviour |
|---|---|
| R01, R01b, R02, R03, R04, R04b | REPORT current from first non-empty text chunk; tool in same step returns earlier phase; subagent never; row gone after turn.complete |
| R10, R10b | 130 s Bash: chip at 10 s counting up, one COMMAND toast at 120 s, chip gone within 2 s of return, DONE offered |
| R11, R11b, R11c | turn.complete clears phase row and chip (hang / reject / still running) |
| R12, R12b | prompt.submit / turn.start remove the chip |
| R13, R13b, R14, R15 | overlapping / consecutive Bash never show earlier chip; background none; no BUILD/now: row after turn end |
| R20, R20b | stale-frame `$` rejection: result unchanged, recovers at turn.complete and next turn |

## Round 3 (awareness3): `phase3.test.ts`
Source: spec clarifications "/nowdoing (decided 2026-10-12)" and amended REPORT rule. Harness addition: world option `streamWrites: 'apply' | 'drop' | 'defer'` (plugin `state.set` made while a `turn.step` stream is consumed, i.e. streamStep() creation to end() or during step(): applied / discarded / applied only when that dispatch ends).
| Cases | Behaviour |
|---|---|
| N01-N07 | idle `/nowdoing`: `last turn: <PHASE> · now: <text> · ended HH:MM` (local time of mocked clock), `no phase yet` (fresh / after reset), replaced by next turn, `3/5 done`, never drawn in band |
| N08, N09 | live `/nowdoing` mid-turn: `phase BUILD · now: Editing calc.py`, no `last turn` |
| T01-T05 x [apply, drop, defer] | REPORT within 1 s of first non-empty main text; tool chunk restores phase; thinking-only / subagent change nothing; row gone after turn.complete |
| K01 | plugin tool result is a string; phase tool still sets the band phase |
