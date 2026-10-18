# CONTRACT-MAP: agents plugin (agents.md 32 statements, mission-board.md 34 statements)

Files: `agents.test.ts` (prefix `A07`), `mission.test.ts` (prefix `M07`). Each file carries its own copy of the harness (`makeKit`, `textOf`, `each`) so it is self-contained. UI tests run through `each(...)`, which registers one test per surface (`[terminal]`, `[desktop]`); tests tagged `[desktop]` or `[terminal]` in the name are surface-specific by spec.

Harness idea: `mock.clock` and `mock.store`; bottom hooks (the "engine") answer `agent.spawn` (returns `agentId`, records the event the plugin passed on), `tool.call`, `turn.step` (generator, usage injected from a queue), `turn.complete`, `session.measure`, `agent.list` (derived from spawns plus injected list-only agents), `ui.toast/open/close/status/log`, `command.register`, `tool.register`, `fs.*` (in-memory files), `http.fetch`/`process.run` (count and throw). Trees come from `$.ui.mount` (`Pane` with `requestId`, `AbovePrompt`). `skip(name, why)` is a no-op because the testing typings export no `test.skip`.

## agents.md (section 9)
| # | Test name(s) | Notes |
|---|---|---|
| 1 | A07 1 spawn shows a working pet | `1 working · 0 done`, `Explore`, `research sweep` literal; `detective`, `haiku` compared case-insensitively |
| 2 | A07 2 costume mapping: <14 cases> | one test per rule incl. first-rule-wins; plain = no costume word |
| 3 | A07 3 pane auto-opens once; /pets toggles | needs fullscreen learnt from a band render (ambiguity 2) |
| 4 | A07 4 turn.complete answer/other | `runs[].status` read from atom `agents.runs` |
| 5 | A07 5 clipped to <= 60 with ellipsis | 80-char description without spaces |
| 6 | A07 6 list-only pet, two missed syncs, model learned | clock advance 3100 ms per sync; 3 misses used (ambiguity 6) |
| 7 | A07 7 empty pane text | |
| 8 | A07 8 showChecklist true / default | read from the band (ambiguity 7) |
| 9 | A07 9 band `2 working` button / row absent | absent = drawn tree equals the sentinel inner band |
| 10 | A07 10 mascot images (on/off) [desktop] | alt equality across on/off is an order-dependent bonus check via a module variable |
| 11 | A07 11 review queue entry | band `1 to review`, pane `REVIEW QUEUE (1)` on both surfaces |
| 12 | A07 12 files/test sums/ordering | state text matched as `tests-failed` or `tests failed` |
| 13 | A07 13 UNTESTED / no edits / FAILED ordering | |
| 13b | A07 13b (6 tests: cat+Write, cat no Write, grep vitest, echo, real pytest, final-answer text) | F31: outcome only from a Bash test-runner call with a runner summary |
| 14 | A07 14 /review done id/all/bare/unknown; REVIEWED button | button found by label /reviewed/i; effect checked through count and `runs[].reviewed` |
| 15 | A07 15 oldest 10 min | band is mounted fresh after the clock advance (ambiguity 8) |
| 16 | A07 16 backfilled not queued / includeBackfilled | |
| 17 | A07 17 results unchanged | Edit, Write, Bash, Read by a subagent compared with what the bottom returned |
| 18 | A07 18 guard warn | toast text is compared with the spec string verbatim; `spend.violations` also checked |
| 19 | A07 19 explicit model, fork, savvy types | |
| 20 | A07 20 deny | exact deny string from spec section 4; beneath spy not called |
| 21 | A07 21 off/status; stored mode | stored value shape `{v:1, mode}` is a guess (ambiguity 9); a separate assertion checks only `{v:1}` and that JSON holds `deny` |
| 22 | A07 22 spend by tier | pricesJson per the statement |
| 23 | A07 23 bar 17 O / 3 S [terminal] | regex `[A-Z]{20}` in brackets |
| 24 | A07 24 unknown model OTHER | |
| 25 | A07 25 footnote differs | 14.00 vs estimate 12.00 differs; 13.00 does not (ambiguity 10) |
| 26 | A07 26 empty spend | |
| 27 | A07 27 hidden on survey/agent view/maxRows<4 | |
| 28 | A07 28 sentinel + plugin band both visible; terminal text == desktop alt (bonus, order dependent) | |
| 29 | A07 29 no auto-review | prompt.submit, Read, 30 min |
| 30 | A07 30 cast (mascots on / off) [desktop] | headers found by Svg alt containing `REVIEW QUEUE` / `delegation|guard` |
| 31 | A07 31 price label (built-in / custom / invalid) | `http.fetch` and `process.run` counters stay 0 |
| 32 | A07 32 namespace agents, /pets registered, legacy keys | commands `pets`, `review`, `delegation` expected from `command.register` |

Skipped (no-op `skip`, listed here): A07 10 Svg data-image scrub probe (UNVERIFIED, needs a real desktop); acceptance manual items (3 real subagents, real deny retry, light/dark and awareness duplicate checklist); legacy agent-pets suite (separate, moved unchanged).

## mission-board.md (section 8)
| # | Test name(s) | Notes |
|---|---|---|
| 1 | M07 1 no plan / five TaskCreate | |
| 2 | M07 2 plan of 50 | scenario50; meter `█{3}░{9}` terminal only; terminal==desktop text is an order-dependent bonus |
| 3 | M07 3 /review done 1; nothing marked in 30 min | |
| 4 | M07 4 | |
| 5 | M07 5 | |
| 6 | M07 6 (two tests) | |
| 7 | M07 7 stripePct | scale accepted as percent (5) or fraction (0.05) |
| 8 | M07 8 checklist + spec | spec found via an Edit result on `docs/specs/x.md` (awareness.md section 3 discovery) |
| 9 | M07 9 (two tests) | |
| 10 | M07 10 | |
| 11 | M07 11 (two tests) | store checked as `{v:1,path}` with no contents |
| 12 | M07 12 rule 1 (3 markers), rule 2, rule 3 unique, rule 3 tie | |
| 13 | M07 13 | |
| 14 | M07 14 | run n = index in `agents.runs` order (ambiguity 12) |
| 15 | M07 15 registration; M07 15 step call | |
| 16 | M07 16 (two tests) | |
| 17 | M07 17 estimate and finish | typical set through `mission.typicalTurns` |
| 18 | M07 18 learning | median of 10,12,14 -> 12, new run 6 steps -> `~50%` |
| 19 | M07 19 spawn line | |
| 20 | M07 20 (5 tests) | workflow field `{runId, agentIndex}` from the typings |
| 21 | M07 21 deny; refused rewrite | refusal simulated by a bottom that throws on any rewritten prompt |
| 22 | M07 22 (two tests) | |
| 23 | M07 23 precedence, savvy present/absent | savvy simulated by an inline plugin and a tool call |
| 24 | M07 24 awareness present/absent | |
| 25 | M07 25 grid/filter/detail; maxTiles | chip found as non-item Button whose label matches `\bREVIEW\b` |
| 26 | M07 26 terminal sample [terminal] | glyph rows parsed from strings split on newlines |
| 27 | M07 27 hidden/inner; status fallback | status fallback uses a non-interactive session start (ambiguity 14) |
| 28 | M07 28 privacy | atoms, store, toasts, status, logs, 3 panes, band |
| 29 | M07 29 failing dependencies | fs/agent.list/ui.open made to throw |
| 30 | M07 30 budget (on, off) | breakdown is modelled by the kit from registrations, not the engine's real /context (ambiguity 15) |
| 31 | M07 31 allDone (three tests) | |
| 32 | M07 32 savvy independence | |
| 33 | M07 33 per-agent figures | formats guessed with tolerant regexes (ambiguity 17) |
| 34 | M07 34 auto-open (fullscreen); never when windowed | |

Skipped: mission acceptance items 1, 3 (Q2 probe, real model), 4 (real /context), 5 (tile lag probe, light/dark), 6 (savvy parity and uninstall); all UNVERIFIED/manual.

## Ambiguities (most literal reading chosen)
1. State shapes: the tests read atoms `agents.runs` (PetRun[]), `spend` (violations), `guard.mode`, `mission` (`view`, `steps`, `allDone`) exactly as named in the type outlines; item fields `id, title, state, srcState, runIds, src{kind,ref}, pct, isEst` from `MissionView`.
2. Auto-open needs `e.viewport.isFullscreen`; how the plugin learns it at spawn time is not specified. Tests first draw the band with `viewport.isFullscreen` true (pets A07 3, mission M07 34).
3. Case: costume and tier words are asserted case-insensitively (terminal lowercase, desktop caps); all literal strings in backticks in the spec are case-sensitive.
4. Pane text from several Text nodes is joined with spaces and whitespace is squashed before matching.
5. Header after a failed pet: only `0 working` and the word failed are asserted (the spec does not say whether failed counts under `done`).
6. "2 missed syncs = done": the test removes the agent from the list and advances three sync intervals.
7. Checklist rows (statement 8) are read from the band, not the pane.
8. `oldest 10 min` is read from a freshly mounted band after the clock moved; no tick runs once nothing is running.
9. Stored `guard:mode` value shape is not specified; the persistence test seeds `{v:1, mode:'deny'}` (a guess) and a second assertion avoids the guess.
10. `differs {pct}%` base is unspecified; the cases use 14 vs 12 (differs on any base) and 13 vs 12 (8% on any base).
11. Statement 24: OTHER must show for an unknown model; the cost for OTHER is left to the plugin (pricesJson has no `other` row), so the test only requires the label OTHER and that "No spend yet" is gone.
12. `/mission link <item n> <run n>`: run n is the 1-based index of `agents.runs`.
13. Grid contents (M26): the sample shows done glyphs inside the EVERYTHING LEFT grid, so 50 glyphs are expected (12 done + 38 left), 25 per row. If builders draw only the 38 left, the total check fails.
14. `hasBand` false is simulated with `session.start{surface:null,isInteractive:false}`.
15. The context budget statement uses a modelled `session.usage` breakdown because the kit has no real engine beneath the plugin; it checks mission's own share (<= 40), description lengths, no eager tool, no agent type.
16. Tile marks (M25): queued tiles carry no mark by spec 1 and a mark by statement 25 ("each carrying a state mark"); the test asserts marks only for done, running, review, blocked tiles.
17. Per-agent figure formats (M33): context, token total (6000), cost ($0.028 or $0.03) and a step count are matched with tolerant regexes; `--` is required somewhere when an agent has no usage.
18. Unmatched checked spec lines (M08): the spec says "appended and queued" but also "checked = done"; only unchecked unmatched lines are asserted queued.
19. `stripePct` scale (percent vs fraction) accepted either way.
20. `textOf` ignores Svg `source`; image/attribute checks read `props.source` directly.

## Stub-run repair log (2026-10-12)
Verified against an empty stub `agents` plugin (`claude plugin test`): before repair 18 pass / 166 fail with many harness TypeErrors; after repair 24 pass / 160 fail, every failure an assertion, no TypeError/HooksError. `tsc --noEmit` (typescript 5.6, claude-code.d.ts) clean.
Root causes: option keys used dots (now `pets_mascots`, `mission_enabled`, ... per conventions s12); the test `$` has no `$.state`, `$.store` or `$.session.usage` (state is now captured by a bottom `state.set` hook, the store by own bottom `store.*` hooks replacing `mock.store`, which cannot be combined with a second `store.set` hook); stub register had to export `register`; reads of absent atoms/items now optional-chained so a silent plugin fails on assertions.
Intent changes: (1) cross-test module variables removed. A07 28 and M07 2 terminal-vs-desktop equality are now single tests mounting both surfaces. A07 10 no longer compares alt between mascots on/off (each run only asserts the alt names the job and `working`). (2) M07 30 reads the modelled breakdown through the kit's usage function instead of `$.session.usage` (not on the test `$`). (3) M07 25 and 33 first assert the tile Button exists before pressing it.
Stub passes (24): absence/silence cases such as mission.enabled=false, stepLine=false, fork/teammate/workflow no line, unchanged tool results, band hidden cases, no auto-open when windowed, empty-plan band, failing-dependency tolerance.

## Referee round (2026-10-12)
- Op-event rule (T1): every hook beneath the plugin for an op event (session.*, ui.toast/status/log/open/close/panes, command/tool/agent list+register, fs.*, store.*, http.fetch, process.run) answers `{ value }`; simulated failures (fsFail, listFail, openFail, disabled http/process) answer `{ deny }`. Events (agent.spawn, tool.call, turn.step, turn.complete, session.start/measure, prompt.submit, command.run, ui.render) answer directly; state.set keeps `next(e)`. `session.surfaces`/`session.surface` answer the surface under test.
- T2: no `ui.close` on the kit `$`; A07 3 and M07 34 close via the `/pets` and `/mission` toggles.
- T3 A07 10: alt must contain `running job` and match `/running/i`, same pattern with mascots on/off.
- T4 A07 18: toast compared after stripping one optional leading glyph; desktop must equal the spec string exactly.
- T5 A07 28 / M07 2: surfaces compared after removing the pets button label (documented exception to conventions 10.2).
- T6 A07 8 run with `mission_enabled:false`; default case also asserts absence of `all 7 done`.
- T7 M07 20 enabled=false: no `Plan`, no `%`, no `N/M done` in band instead of sentinel equality.
- T8 M07 25 (grid, maxTiles) and M07 33 on terminal assert text equivalents (`EVERYTHING LEFT (n)`, glyph rows 25+25, `RUNNING NOW`, `/mission <n>` text); Button/tile presses are desktop-only. T9 glyph rows contain only the five glyphs and spaces, expect [25,25]. T10 `steps? 4` accepted.
- Result: stub 24 pass / 160 assertion fails, zero "skipped" hook lines, tsc clean.

## Spec clarification (agents3, observed host format)
Claude Code 2.1.296 answers TaskCreate with the string `Task #<n> created successfully: <subject>` (structured record `{task:{id,subject}}`). M07 37 requires the string form to create item n titled subject; any other non-object result (e.g. `error: ...`, a number) is ignored without throwing.

## Parity backlog (mission-board.md, contract cases 35-49), tests `M07 PB35` .. `M07 PB49`
PB35-49 map 1:1 to cases 35-49 (PB37, PB40, PB41, PB43, PB44, PB49 have several tests). Guesses: `windowsJson` shape is `{asOf, sonnet:N, 'claude-sonnet-5-5':N, ...}` (spec gives no shape); desktop width is `bodyColumns*8-16` px (39 => 296 px); the agent row is found as the pane row holding the title and a model chip, plus the following `ctx`/`%`/`~` line; RUN and ACCEPTED lines are found by `RUN ·` / `ACCEPTED`; new-plan restart accepts any elapsed <= 5 s right after registering. Changed existing cases: M07 15 and M07 17 (`no est.` now read from the agent row, since the RUN line carries `est.`), M07 33 (cost must be `~$`; the `steps 4` count assertion removed, new format drops it).

PB42b-e (F26, no-plan elapsed follows the current burst): `M07 PB42b` (12 h idle gap in 2 h advances, since the 1 s display tick caps one advance; running 5 min => 05:00, 2 agents, cost/tokens sum both), `PB42c` (frozen 20:00 while idle), `PB42d` (two tests: gap 20 min => 50:00; gap 40 min => 05:00), `PB42e` (guard: with a plan, freeze at allDone and restart on a new plan).

## agents.md F34 (statements 33-47), file `f34.test.ts` (prefix `A34`, own copy of the kit plus `w.cnt` counters for agent.list / fs.* / agents state.set)
| # | Test name(s) | Notes |
|---|---|---|
| 33 | A34 33 nesting warn (default): passes, one toast, pane rows; A34 33 unknown parent id shows "agent abcdef12" | toast compared verbatim after optional leading glyph strip |
| 34 | A34 34 spawn without parentAgentId | pane `no nested spawns` |
| 35 | A34 35 limiter (5 s then +30 s); A34 35 nesting_toast=false | `nested spawns N` from bare `/delegation nesting` |
| 36 | A34 36 /delegation nesting deny; A34 36 nested model-less in deny mode | deny text compared verbatim to F34.2; `Explicit model: a of b` line and `spend.violations` unchanged |
| 37 | A34 37 nesting off; A34 37 nesting maybe | |
| 38 | A34 38 independence; status text; new session with stored mode; stored beats option; invalid stored falls back to option | status suffix ` · nesting {m} · nested {n}` |
| 39 | A34 39 fork / savvy-light / savvy-flow:savvy-heavy (warn and deny); allowTypes=Explore; workflow spawn (warn and deny) | |
| 40 | A34 40 warn+warn two toasts; A34 40 deny model-less only nesting deny | |
| 41 | A34 41 runaway steps 99/100/200 | toast verbatim; step result passthrough only checked as "no deny" (see ambiguity 1) |
| 42 | A34 42 context 299999/300000, output tokens, latest-step-not-sum | |
| 43 | A34 43 agent B two toasts in order; agent C two on one step; main steps ignored | |
| 44 | A34 44 pet row mark (terminal row regex / desktop `data-runaway="1"`, done row clean); A34 44 desktop alt equals terminal row | both surfaces from one kit started on terminal |
| 45 | A34 45 band x2 -> x1 -> absent; A34 45 terminal and desktop segment text equal | press-to-open-pets is not a numbered statement and is not tested |
| 46 | A34 46 maxSteps=0; maxContext=50000; runaway_toast=false; usage:null; no run row `agent abcdef12`; 50-char clip | |
| 47 | A34 47 performance | amended 2026-10-15: at most 4 `agents` state.set per subagent step (default options); counts only `agents` plugin state.set; delta over 200 steps with no clock advance |

Ambiguities (F34): (1) `$.turn.step(...).result` is undefined in this kit, so "step result returned unchanged" is checked only as no `deny`, toolSeen/spawnSeen untouched; (2) 45 "segment alone makes the row appear" is not tested separately because a running agent already shows `N working`; (3) 44 terminal row located by text `research sweep` + `running`, regex `running \d\d:\d\d · ⚠ RUNAWAY — research sweep`; (4) 38 invalid-stored-value and option-default cases derived from F34.2 Settings text; (5) 47 "attributable to F34" = any agent.list/fs/process/http delta over the step loop, and state.set counted for plugin `agents` only; (6) 43/B 101st step toast asserted as `101 steps · 340k ctx`; (7) 41 "no stop/interrupt/message" approximated by no deny, no tool/spawn events, exactly one toast.
