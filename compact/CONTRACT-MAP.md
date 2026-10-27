# compact: contract map

Source: `specs/compact.md` section 10 (24 statements) plus section 8 budget and section 12 decisions. Written code-blind.
Test files are GENERATED: `_src/harness.ts` + `_src/NN-name.body.ts` -> `NN-name.test.ts` via `python3 _src/build.py` (each test file is self-contained, so run-contract.sh only has to copy `*.test.ts`). Edit `_src/`, rerun the script.
UI tests loop `['terminal','desktop']` and compare text (desktop = Svg `alt`); `bodyColumns: 160` so the full variant is drawn.

| # | Statement | Test names (prefix) | File | Notes |
|---|---|---|---|---|
| 1 | 80k no chip; 350k chip has 350k, $0.07, $2.80, save $0.06 | `C01 ctx 80k ...`, `C01 ctx 350k ...`, `C01 a handoff in progress ...`, `C01 gate: ctx below showFromTokens ...`, showFromTokens option x2 | 01 | model primed through `turn.step` (OPUS) |
| 2 | estimate label, `, custom)`, invalid JSON | `C02 ...` x3 | 02 | override schema from agents.md s4 + write1h; asserts `$0.35`/`$7.00` for cacheRead 1 / write1h 20 |
| 3 | payback line warm and cold | `C03 warm payback...`, `C03 warm chip...`, `C03 cold payback...`, `C03 passAssumesCacheHit=false...` | 03 | warm asserted on `/coach` and on both surfaces' chip; cold on `/coach` (chip has no `at once` in the spec strings) |
| 4 | floor 54k+4k -> `→58k`, save $0.06 | `C04 ...` x2 loops + view test | 03 | breakdown includes free/buffer rows (see ambiguity 3) |
| 5 | score, verdicts, absent atom | `C05 ...` (7, NOT NOW, 4/OK, absent usage) per surface, expiring, unknown, six phase signals, agent statuses | 05 | state atom `compact.coach` `{score, verdict, reasons}` read via a test-side reader |
| 6 | saving gate | `C06 ...` per surface | 01 | `coach.targetTokens` 98000 |
| 7 | idle return 11 min +1, 9 min 0 | `C07 ...` x4 | 05 | also exactly 10 min (>=) and option change |
| 8 | toast: one per episode, regex, 140 chars, re-arm, 20-min gap | `C08 ...` x4 | 08 | clock mocked; episode = cold + no agents (5) |
| 9 | peer gap, focus, mute, lastShownAt | `C09 ...` x5 | 08 | queue release asserted between +40 s (none) and +52 s (one) |
| 10 | /handoff prompt, path, headings, agent ids, -2 | `C10 ...` x7 | 10 | |
| 11 | compact never called except by `go` | `C11 ...` x3 | 10 | |
| 12 | detection -> ready / failed / ignored | `C12 ...` (per surface ready, missing heading) + aborted, subagent, absent, <800 bytes, first-turn-only | 12 | |
| 13 | `/handoff go`, idle, ttl, cancel | `C13 ...` x6 (+1 per surface) | 13 | |
| 14 | compact rejects / skip | `C14 ...` x2 | 13 | reject simulated by a bottom hook that throws (see ambiguity 7) |
| 15 | --no-compact | `C15 ...` x3 | 13 | |
| 16 | Resume entry | `C16 ...` x11 (3 triggers + variants) | 16 | entry <= 240 chars (60-token budget) |
| 17 | system prompt unchanged by resume | `C17 ...` | 16 | compose JSON identical before / pending / after |
| 18 | Orchestrator ON/OFF, store wins | `C18 ...` x10 | 18 | section <= 480 chars and <= 120 tokens (budget row 129/150) |
| 19 | section identical, survives compaction | `C19 ...` | 18 | |
| 20 | /orch status text, no settings writes | `C20 ...` x2 | 18 | spies on `env.set` and `config.set` |
| 21 | <= 3 commands, no tool/agent, collision prefix | `C21 ...` x4 | 21 | |
| 22 | `-p` fallback status | `C22 ...` x2 | 21 | `session.start{surface:null,isInteractive:false}` |
| 23 | missing peers never throw | `C23 ...` x2 | 21 | with and without the peer stub plugins |
| 24 | terminal == desktop | `C24 ...` x7 | 21 | chip states, handoff states, narrow widths, silent cases |

Budget rows: OFF = 0 (`C18 /orch off --yes`: compose result deep-equals engine input); ON <= 129 (`C18 ON by default`: exactly one added section, <= 480 chars, <= 120 tokens); Resume entry <= 60 tokens (`expectEntry`); 3 commands with descriptions <= 40 chars (`C21`).

## Skipped / not written
- `C21 no tool.call hook`: registered through `skip()` (kit has no `test.skip` in its typings; the helper uses it if it exists at runtime, else nothing is registered). The kit cannot list hooks. Covered by `claude plugin validate` / review.
- Acceptance probes of spec 11e (`classic.SessionStart` source `compact`, task-notification `prompt.submit`, compaction cache reuse, commands in the model listing): manual list, first acceptance run.
- 30 s `$.clock.every` refresh and "3 failures stop" for `/handoff retry`: spec does not give a testable contract (see ambiguities 9, 10). Not tested.
- Desktop pixel/variant widths (720/520/300/130 px) not asserted: only text equality and silence conditions.

## Harness assumptions (read before the first run)
- Peer atoms are written by stub plugins named `usage`, `awareness`, `agents`, `dev` (owner-only writes), driven by a hidden command `__peer-<name>`. Compact's state is read through a hidden `__read` command in the bottom hook. If the kit puts the plugin under test in `plugins` explicitly, add it to `PEERS`.
- Ops (`fs.*`, `process.run`, `session.*`, `agent.list`, `command.list/register`, `ui.toast/notice/status/log`, `env.*`, `settings.read`) are answered by hooks on the test's `on`. `mock.clock`, `mock.store`, `mock.env` supply time, store, env.
- The model writes the handoff file in the test by filling the in-memory fs between `/handoff` and `turn.complete`.
- User prompts are raised with `$.prompt.submit({text, asUser:true})` followed by `$.turn.start`.

## Ambiguities (most literal reading chosen)
1. State atom field names: tests read `compact.coach` as `CoachView` (`score`, `verdict` `good|ok|notnow`, `reasons`, `floorWon`, `targetTokens`, `lastShownAt`) and `compact.handoff` as `HandoffView` (`state`, `missing`), `compact.orch.on`, exactly as the section 7 contract outline.
2. Peer atom shapes follow usage.md / awareness.md / mission-board.md type blocks; `agents.mission.allDone` is a field of the `mission` atom value; `dev.toast.lastShownAt` and `awareness.headsup.lastShownAt` are top-level fields.
3. Floor: "sum of non-Messages categories" is taken as the `kind:'used'` non-Messages rows; the fixture also has `free` and `buffer` rows, which a literal sum of every non-Messages row would wrongly add (that implementation would fail C04, by design).
4. Where the cold payback line appears: asserted on `/coach` only; warm `8 turns` on `/coach` and on the chip (spec string "pays back ~8 turns").
5. Toast offers happen on `turn.complete` (hook list in s9); the toast helper therefore does `measure, complete, measure, complete` so the agent refresh order does not matter. "Staying >= 5" is two such ticks; re-arm is score < 3.
6. "Idle return +1": gap measured between the last turn activity and the next `prompt.submit` (+ `turn.start`); equality (exactly 10 min) counted as +1 (spec `>=`).
7. "Compact rejects (turn running)": simulated by the bottom `session.compact` hook throwing `Error('Turn running...')`. The kit may treat a throwing hook as skipped; if so, C14 reject needs a different injection.
8. "Missing `## 7` heading -> text `missing` + the heading": asserted as `missing` and `Next steps` (the heading name) across chip, notices and toasts; `HandoffView.missing` matches `/Next steps|7/`.
9. 30 s refresh timer is not driven by a test (the spec gives no observable beyond "agent list refreshed"); tests refresh via `turn.complete` as the spec lists.
10. "3 failures stop" for `/handoff retry`: wording of the stop state is unspecified; not tested.
11. Slug when no argument: `session` fallback only asserted as a valid kebab slug (session title field is UNVERIFIED in the spec).
12. The prompt-length check (`< 2400` chars) is a loose reading of "~300 tokens".
13. `/orch off` estimate asserts `cold turn` and `/\$\d/` only, not the exact `$2.80`.
14. Test-only date: clock fixed at 2026-10-12 12:00 UTC so local-date and UTC-date agree in any timezone.

## Stub run (2026-10-12): harness repair log
Run against an empty stub plugin (`claude plugin test`): before 7 pass / 123 fail, all failing at harness level (no test reached an assertion). After: 21 pass (silence/absence tests) / 109 fail, every failure an assertion or a null read of the plugin's absent state; `tsc --noEmit` (TS 5.6 against claude-code.d.ts) clean. A probe stub that writes `compact` state and draws an AbovePrompt confirmed that mount, `textOf` and the state reader work.
Root causes fixed: (1) `mock.env` already registers `env.get`, my second one made the test module fail to load (removed). (2) Peer plugin modules are serialised and statically scanned: no closures, no `$` passed to helpers, literal state refs -> four hand-inlined peer plugins. (3) The test module may not call `$.state.get` (host rule) -> state is read through a fifth stub plugin `reader` (`__read`). (4) The engine's `ui.render` and `command.run` need a bottom answer (added). (5) `session.compact` rejects empty `messages` -> a kept message is passed and returned. (6) `$.prompt.compose()` needs an argument object (`{}`).
Intent changes: option keys now use underscores (`coach_toast`, `coach_targetTokens`, `orch_enabled`, ...) per conventions s12. C24 narrow-width test now also asserts the chip is non-empty (was vacuous). No other assertion changed.
Note: `PEERS` now includes `reader`; with `peers:false` only `reader` is installed.

## Referee fixes (2026-10-12)
A: op-style hooks answer `{value}` (helper `op`); B: `cmd/complete/compact` call `clock.settle()` (plugin defers submit/compact via `$.clock.after(0)`); C: full `PromptComposeInput`; D: C24 failed/saved split into two tests. Spec clarifications applied: E (C14 now asserts `Compacting now` at once, then `Turn running` / `Compaction skipped: <reason>` in notices+logs, state back to `ready`; supersedes ambiguity 7), F (C03 matches `N (warm )?turns`). No weakening of statements 5 or 24.

## Host hold rule (added 2026-10-12, file 22)
Harness: while a `w.cmd` command.run dispatch is in flight (`S.inCmd`) every fs call yields macrotasks and settles the clock, so delay-0 timers armed before the hook returns fire inside the window; `prompt.submit` / `session.compact` made by the plugin in that window are refused (`S.holdRefusals`). Cases: `H01`-`H03` (submit once, writing, no `HANDOFF failed`), `H06` (go: one compact, none refused), `H09`/`H10` (heading lines whole, nothing appended, "exactly"/"do not copy"), `C18` bound now 280 chars.
Not expressible (registered via `skip()`): `H04`, `H05`, `H07`, `H08` - the kit cannot show a hook's error text to the caller (thrown hook = skipped; caller sees the engine default error). Knobs kept in the harness: `rejectSubmit`, `rejectCompact`, `compact: 'headless'`.

## F41 (statements 79-86, file 41-nudge-cadence; spec compact.md F41.6)
Statements 79-85 are `C79`..`C85` (32 tests in `_src/41-nudge-cadence.body.ts`; 79 x2, 80 x3, 81 x2, 82 x4, 83 x4, 84 x4, 85 x12, 86 x2). Statement 86 also amends `C27` (both tests: 25k steps, 324,999/325,000/350,000, jump to 410k then 425k) and `C37` (`next` 325,000) in 33. Harness additions: `fs.write` honours an `append` flag, `process.run mv` renames, `fs.exists` can be rejected via `failOps`, `handoffDirWrites` ignores `nudge-debug*`. Gaps: `SPEC-GAPS.md`.
