# usage contract map (from specs/usage.md section 8, code-blind)

Helpers: `_kit.ts` (rig with bottom hooks for engine ops, `textOf`, time formatting). Surfaces looped: `terminal`, `desktop` (band text = tree text; desktop reads Svg `alt`).

| Statement | Tests | Notes |
|---|---|---|
| 1 | burn: C01a, C01b | before measure no `5H`; `rateLimits: []` -> `No plan limits reported` |
| 2 | burn: C02 (labels, both surfaces), C02 meters | meter glyph counts asserted on terminal only |
| 3 | burn: C03 | hit time compared to now+1d15h13m within +-1 min, local `Ddd HH:MM` |
| 3a | burn: C03a x3 | 100.0 HOT; 99.9 ON PACE; `burn.hotAt=120` ON PACE |
| 4-8 | burn: C04 ... C08 | |
| 9 | burn: C09 (both surfaces), C09 line width (terminal) | width via `bodyColumns` 40 / 24; cell width approximated (emoji = 2) |
| 10 | burn: C10 | measure x3 same reading, flush by `session.end`, stored `burn:samples:<sid>` has exactly 1 sample |
| 11, 12 | burn: C11, C12 | |
| (conventions 10.2) | burn: CX | desktop alt == terminal text, chip words normalised |
| 13, 14 | cache: C13 x3, C14 x2 | via `cache.ttl` option |
| 15, 15a, 15b, 15c, 15d | cache: C15*, observer test | `settings.read` mocked; keepwarm observer via `$.command.run` with counted bottom |
| 16-19 | cache: C16 x2, C17, C18, C19 | |
| 20-23 | cache: C20 x2, C21 x2, C22, C23 | prices via `pricesJson` override |
| 24-26 | compaction: C24 x4, C25, C26 | threshold via `session.usage({breakdown})` mock |
| 27-29 | band: C27 x2, C28, C29 | sentinel inner tree from a hook beneath |
| 30 | cache: C30 x2 | `mod.cache.enabled=false` + control |

Skipped (`test.skip`): none. Manual-list items (real percents vs /usage, 5-minute countdown, /compact chip, mascot probe, theme screenshots, cache-tax coexistence) are out of scope.

## Ambiguities (most literal reading chosen)
1. Option keys are used literally as written in the spec (`cache_ttl`, `burn_hotAt`, `cache_followCacheTax`, `mod_cache_enabled`, `pricesJson` (underscore form, conventions s12)), passed through `test(..., { options })`.
2. `pricesJson` shape is not given; read as an array of row tuples `[family,input,output,cacheRead,write5m,write1h,asOf?]` ("same row shape plus optional asOf"). Used with family `sonnet` and model id `claude-sonnet-5-5` (family matched by name).
3. Chip words differ per surface (`🔥 HOT` vs `RUNNING HOT`) while the spec also says alt == terminal text; assertions use the shared substring (`HOT`, `PLENTY`, `LIMIT`); CX compares after normalising the chip.
4. TTL line wording: `TTL <ttl> (<source>)` taken from the wireframe for cache-tax; for `assumed`/`learned`/`event` only the presence of `~` + ttl and the source word on the line containing `TTL` is asserted (except cache-tax, asserted as `TTL 1h (cache-tax)` and `TTL 5m (cache-tax)`).
5. 78% with toCompact 12 is also WARN (toCompact <= 15); only `CTX`, `78%`, `12% to compact` asserted. "Starts with ⚠/⛔" is asserted as the substring `⚠ CTX` / `⛔ CTX` because the band row also holds the burn segment first. The 85% case uses a threshold giving toCompact 10 (WARN, not DANGER); 93% gives toCompact 2.
6. Shape of the stored samples value is unknown beyond `{v:1,...}`: the test finds the sample list as an array (or the first array property) and expects length 1.
7. Store flush is forced by raising `session.end` (reason `other`) after advancing 2 minutes, since writes are throttled to once a minute.
8. Pane/band are read by mounting `Pane` (requestId `cache-clock`) and `AbovePrompt` through the kit's `ui.mount`; Pane/band props (bodyColumns 100/120, maxRows 6) are test-chosen. Tree text joins row Boxes with a space, column Boxes with a newline.
9. `KEEPWARM on · until HH:MM` asserted as `KEEPWARM on` + `until ` + local `HH:MM` (same-day) or `Ddd HH:MM`; a fork-based `on` asserts `last ping` and the countdown (`50:00` after a fork at t and 10 min).
10. Statement 22 produces the cold state by letting a 1h TTL lapse (2 h) with context tokens 200000 from `session.measure`; cost asserted as `~$1.20` with write1h = 6 $/MTok.
11. Statement 23 accepts `n/a` or `(default price)`.
12. Statement 20 case 1 uses `rateLimits []` (would assume 5m), case 2 a subscription (would assume 1h) so learning is the only way to get the expected TTL; the `learned` word is asserted on the TTL line.

## Harness repair log (stub run, 2026-10-12)
- Stub plugin (no hooks): 11 pass / 104 fail before, 13 pass / 102 fail after; every failure is now an assertion. Passing on stub: absence/silence tests (C01a, C24 50%, C27, C29, C09 width, C15d no-KEEPWARM, observer pass-through).
- Root causes: ops (`model.fork`, `store.*`) are not on the test `$` (fixed: `model.fork` is raised by an inline plugin `zzfork` via `/zzfork`, tests pass `plugins: [FORK_PLUGIN]`; the store is a Map answered by the rig's own `store.*` hooks instead of `mock.store`); `session.compact` needs non-empty messages; `tool.call` bottom must return `{result}`; Pane mount throws when nothing is drawn (now read as empty text); option keys now underscore.
- Intent changes: C27 tool.call now asserts `result` equals the engine's answer (not text); CX now also requires `5H` present (otherwise vacuous on an empty plugin).
- Referee fixes: AbovePrompt bottom always registered; band()/pane() log mount errors; positive controls added to C01a, C24 50%, C29, C30; C21 asserts the custom-prices footer; command.register -> {value: undefined}, command.list -> {value: []}.
