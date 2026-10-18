# dev plugin: contract map

Source: `specs/dev.md` section 13 (55 statements) plus `specs/00-conventions.md` sections 2, 3, 7, 8, 10. Written code-blind.
Test names start with the statement number (`C07 ...`). UI tests are looped over `terminal` and `desktop`; the suffix `[terminal]` / `[desktop]` is in the name.

Harness: `_harness.ts` (not a test file). It registers the engine-bottom hooks (`process.run`, `fs.*`, `session.*`, `ui.toast/status/open`, `command.register`, `tool.call`, peer `state.get`), mocks the clock and store through the kit, records calls, and builds git / gh / lsof / test-runner fixtures. Process output is never real.

| Statement | File | Test(s) | Notes |
|---|---|---|---|
| C01 | git.test.ts | C01 chip shows branch*, ahead, staged...; C01 no upstream line -> no arrows | `↓0` is not asserted (see Ambiguity 1) |
| C02 | git.test.ts | C02 detached head | |
| C03 | git.test.ts | C03 linked worktree; C03 main worktree has no `wt ` | |
| C04 | git.test.ts | C04 commit triggers refresh; C04 two triggers one call | counts `git status --porcelain=v2` calls |
| C05 | diff.test.ts | C05 tree-to-tree diff | numstat/name-status `-z` fixtures; `write-tree` mocked as `tree1`, `tree2` |
| C06 | diff.test.ts | C06 Edit result listed before next snapshot | |
| C07 | diff.test.ts | C07 no process: `+2 −1`, `(tools only)` | uses `procDown` (all `process.run` reject) |
| C08-C13 | pulse.test.ts | `C08`..`C13` generated from a table (pytest, vitest, jest, bun, go, cargo) | go: realistic tab-separated `ok  \ta\t0.123s` |
| C13 | pulse.test.ts | extra: cargo summary on stderr | not in contract, see Ambiguity 9 |
| C14 | pulse.test.ts | C14 ANSI pytest | |
| C15 | pulse.test.ts | C15 npm test -> jest | |
| C16 | pulse.test.ts | C16 non-test Bash, `ran, no summary` | |
| C17 | pulse.test.ts | C17 stale (1 edit)/(2 edits)/cleared | |
| C18 | pulse.test.ts | C18 two flips; C18 edit between runs | runs advance the mocked clock 1 s apart |
| C19 | pulse.test.ts | C19 subagent ignored; C19 includeSubagents=true shown | second is an extra (option documented in section 5) |
| C20 | coverage.test.ts | C20 fresh mtime; C20 older than run; C20 `/coverage` message | file facts via mocked `fs.exists/stat/read` |
| C21 | coverage.test.ts | C21 `(+0.4)`; C21 `(-1.6)` with `⚠` | two scenarios, see Ambiguity 4 |
| C22 | coverage.test.ts | C22 lcov 85.0% | |
| C23 | coverage.test.ts | C23 cobertura 85.1% | |
| C24 | coverage.test.ts | C24 coverage.py json 91.0% | |
| C25 | typecheck.test.ts | C25 context + chip `TSC 1 error` | result deep-equals the engine answer |
| C26 | typecheck.test.ts | C26 same errors not repeated; C26 changed errors resent | |
| C27 | typecheck.test.ts | C27 clean after errors; C27 clean without earlier errors adds nothing | second is an extra from the Behaviour text |
| C28 | typecheck.test.ts | C28 ruff F401 | `ruff --version` probe answered |
| C29 | typecheck.test.ts | C29 25 s tsc | mocked clock: advance 20.1 s, then 6 s |
| C30 | typecheck.test.ts | C30 band mode; C30 off mode | `off` is an extra |
| C31 | typecheck.test.ts | C31 missing tsconfig/binary; C31 npx cannot resolve | where `tsc: n/a` shows is not fixed, see Ambiguity 5 |
| C32 | typecheck.test.ts | C32 throwing tsc; C32 throwing ruff | |
| C33 | pr.test.ts | C33 three worktrees | rows, header `3 WORKTREES`, Link hrefs |
| C34 | pr.test.ts | C34 open beats merged | |
| C35 | pr.test.ts | spacing; failure backoff 120 s then 240 s; rate limit (3 stderr variants); ghRateLimitHint | |
| C36 | pr.test.ts | C36 gh auth failure | also asserts a single `gh auth` call in 5 min |
| C37 | pr.test.ts | C37 idle x3 -> 180 s | pending fixture (60 s base) |
| C38 | pr.test.ts | C38 no GitHub remote | |
| C39 | pr.test.ts | current-branch chip; no chip without PR; fail + CONFLICT chip | |
| C40 | ports.test.ts | one ours; two ours; plural others | |
| C41 | ports.test.ts | two-step; expiry after 5 s; `stopped`; `still running` | buttons found by label regex, key read from the found element |
| C42 | ports.test.ts | cwd changed; port changed | |
| C43 | ports.test.ts | no `ps`; lsof argv shapes; kill argv | |
| C44 | common.test.ts | C44 unchanged results; C44 only context added | |
| C45 | common.test.ts | C45 probe rejects | asserts exactly one process call (the probe) |
| C46 | common.test.ts | C46 hidden conditions + inner preserved; C46 nothing to show | inner tree injected by a bottom `ui.render` hook |
| C47 | common.test.ts | all enabled; one test per mod id | each disabled mod: chip, command, call effects |
| C48 | pr.test.ts | C48 | `$.state.get({plugin:'dev',key:'toast'})` read for `lastShownAt` |
| C49 | pr.test.ts | table of 11 cases + pane `fail` row for another author | |
| C50 | pr.test.ts | two in one cycle; held 30 s flip; headsup lastShownAt; no peers | `/prs refresh` used to place a flip 30 s / 20 s after another event |
| C51 | pr.test.ts | focus shown after; focus recovered; mutedUntil | |
| C52 | pr.test.ts | desktop `P`; terminal emoji; both surfaces no emoji | |
| C53 | typecheck.test.ts | C53 two runs, `timeoutMs` 20000 | |
| C54 | coverage.test.ts | session-first default (+2.0, no `git status --porcelain`); last-clean | |
| C55 | ports.test.ts | re-arm; baseline listener not ours; outside-cwd not ours; linked worktree ours | |

## Skipped / not testable here
- The testing typings (`claude-code/testing`) have no `test.skip`; skipped items are therefore listed here only, not as code.
- Manual acceptance list (a) to (h) in spec section 14, including "(c) a TS type error appears in the agent's next message" (UNVERIFIED that a hook-added `context` reaches the model; the tests only prove the plugin adds it).
- UNVERIFIED: `isError` on non-zero exit (pulse treats it as a hint; tests never set it for runs, except the C44 failed Bash result).
- UNVERIFIED: `bashEditDiff.changedFiles` (bonus only; not exercised).
- Real `git`, `gh`, `lsof`, `tsc`, `ruff` behaviour: mocked only.
- Not covered (no numbered statement): cadence of ports scans (15 s / 60 s), hold of a toast for at most 60 min, `idleMinutes` pause, store keys (`pulse:flaky:<repoHash>`, `cov:base:<repoHash>`; the hash format is not specified), `/changes open <n>`, `/prs` command text, terminal pane line format `wt/auth-flow  #412  pass  APPROVED`.

## Ambiguities (most literal reading chosen)
1. C01: the contract says "no `↓` when behind 0 and no upstream line -> no arrows", the Strings section shows `↑2 ↓0`. Chose: the fixture with upstream and `+2 -0` must contain `↑2` (nothing asserted about `↓`); the fixture with no upstream lines must contain neither arrow.
2. Band text on desktop = Svg `alt`, on terminal = Text children; equality of the two is checked through `crossCheck` (module-level map, relies on terminal tests running before desktop ones). Conventions 10.2 says alt == terminal text, while section 6 says desktop never uses emoji; tests assume the alt carries the same glyphs as the terminal text and only assert glyph-free substrings (`main*`, `2 files`, `TSC 1 error`...) individually.
3. Text assertions are whitespace-normalised (runs of whitespace collapse to one space), because the spec writes rows with double spaces and the contract with single spaces.
4. C21: `82.0 -> (-1.6)` only works against 83.6 (83.6 - 82.0 = 1.6), not against the first reading 83.2. Tested as two scenarios: 83.2 then 83.6 gives `(+0.4)`; 83.6 then 82.0 gives `(-1.6)` and `⚠`.
5. C31: "status `tsc: n/a`" does not say where. The test accepts it in any of: `$.ui.status` texts, the band text, or the `/typecheck` command text.
6. C35: "no call before 60 s" is read as "no second call within 60 s of the previous call"; the time of the first call after `session.start` is not fixed (the test waits for it in 5 s steps). A pending-check fixture is used so the base interval is 60 s. The rate-limit test checks only the 15 min silence (14 min wait), not when calls resume.
7. C37: "no input for 10 min -> interval 180 s" is tested with a pending fixture (base 60 s x 3) by measuring gaps between calls after minute 11. No user prompt is ever simulated; the session start is the last input.
8. C50: flips "30 s later" and "now - 20 s" fall below the 60 s minimum between normal cycles, so the test places them with `/prs refresh` (spec: refresh bypasses the interval, floor 15 s). The headsup peer atom is supplied through a test `state.get` hook for plugin `awareness`, because a plugin cannot write another plugin's state; this relies on the kit's `$.state` sitting beneath a test-registered `state.get` hook that forwards other plugins to `next`.
9. C13 extra (cargo summary on stderr) and C19/C27/C30 extras go beyond the numbered contract; they come from the Behaviour sections. Remove them first if a builder disputes them.
10. C41/C55: the STOP/CONFIRM control is found as a `Button` whose shown text matches `STOP` / `CONFIRM`; its `key` is whatever the plugin gives it. If the plugin renders it as another element type, these tests fail by design.
11. C40: lsof fixtures use the shapes from the spec (`p`, `c`, `f`, `n` lines for listing; `p`, `n` lines for the cwd call). `n*:3000` appears twice (two fds) to test de-duplication. Pane text is matched as `:3000 node pid 4242`.
12. C45: "status contains `needs host commands`" is read from `$.ui.status`; "does nothing else" is tested as exactly one process call (the probe `git --version`, last argv `--version`).
13. C47: the baseline test requires all seven chips at once in one scripted session; if a chip depends on timing the builders chose, adjust `full()` in `common.test.ts`.
14. C18: run timestamps are 1 s apart on the mocked clock; flips are identified only by the chip text (`⚠ 1 flaky`); the `$.store` flaky key is not asserted.
15. C29: the budget is exercised by advancing the mocked clock 20.1 s; the process mock ignores `timeoutMs` and finishes at 25 s, so the background run can complete.
16. Tests import `./_harness`; the runner script must copy the whole `dev/` folder (not only `*.test.ts`). If the engine refuses sibling imports, concatenate `_harness.ts` into each file.
17. `SessionRepo` in the typings has `remote`, the spec says `originUrl`; the mock `session.repo` answers both fields.

## Repair log (stub run)
- Root causes of the first 0/166: the harness lacked bottom hooks for `session.start`, `session.end` and `turn.complete` (the engine throws "no implementation for ..."), and the bottom `ui.render` returned `{type:'engine'}` which the kit refuses ("engine node without a ref"); it now returns an empty Box. Also `$.state` is not in the `Engine` typings (cast), and `World` was `any` (implicit-any errors under strict); it is now an interface.
- Option keys in `test(name,{options})` use underscores (`tc_mode`, `mod_git_enabled`, ...).
- Intent change 1: order-dependent `crossCheck` removed. Equality of terminal and desktop BAND text is now asserted inside `w.band()` (it mounts both surfaces in the same test). Pane text equality across surfaces is no longer asserted.
- Intent change 2: C49 no-toast cases no longer require the PR cycles to have run (so absence tests pass on a stub); cases expecting a toast still do.
- Stub run: 0/166 before, 28 pass / 138 fail after (all remaining failures are assertion failures).

## Referee round (dev)
- Engine-op hooks now answer `{ value }` / `{ deny }` (procDown, rejecting checkers and missing files are `{ deny }`); peers via `state.get` answer `{ value: { value, version } }`.
- C44 compares results without `isReadOnly` (context still asserted absent). C46 no-repo = all git commands except `--version` exit 128 plus `session.repo()` null. C47 mounts the band at 260 columns. C48 reads `dev.toast.lastShownAt` from a pass-through `state.set` recorder. C30 off passes `tc_mode: 'off'`. C04 and C12 unchanged.
