# SPEC-GAPS (token-budget contract tests)

Written code-blind from `docs/token-budget-spec.md`. Where the spec is silent or ambiguous the tests use the most literal reading and the gap is listed here.

Run: `python3 -m unittest discover -s ~/CodeBase/bento-mods-tests/token-budget -v`
Repo under test: env `TOKEN_BUDGET_REPO` (default `~/CodeBase/machine-setup`). All runs use a temp HOME, `TZ=UTC`, and shimmed `osascript`/`launchctl`/`claude`/`ccusage` first on PATH.

## Ambiguities / gaps

1. **ccusage output format and CLI args are undefined** (4.1 step 4). The fake prints plausible JSON for any args. Tests assert only: missing/failing binary -> `spend.*` null + warning `ccusage`; with a working binary the keys exist and are null or numbers. The `$61.80` headline form (AC27) cannot be driven through a real run; only `spend n/a` is tested. Not tested: `daily_usd`/`weekly_usd` values.
2. **`cli_version` source** is not stated (a third `claude --version` call would violate "exactly 2 invocations"). Only key presence in the ledger is asserted.
3. **Proposals file content** (4.2): read literally as "same content as stdout", i.e. the full analysis object with a `proposals` array. Apply tests build files in that shape. A bare array would fail these tests.
4. **`--out-json FILE`** meaning is undefined; not tested.
5. **Manifest has no per-MCP-tool list** (4.1.2), but R4 (AC20) needs "a non-deferred tool not in the previous manifest". Test uses `tool_count` growth on a non-deferred server and asserts only the id prefix `mcp-new-<server>-` and `flag`. The deferred case asserts no `mcp-new-*`. The real tool-level fixture format is unknown.
6. **R2 ids for all-plugin duplicates** (AC18): which `skill-dup-<name>-<source>` ids are emitted is unspecified; test asserts at least one `skill-dup-<name>-*` and all are `flag` with saving 0. Three-way duplicates (project+user+plugin) not tested. Shell `argv` path form (`~` expanded or not) is unspecified; test checks `argv[0]=="rm"` and the path suffix only. Plugin-skill name form in `/context` ("superpowers:brainstorming") vs manifest `name` is unspecified; test uses `endswith`.
7. **R7 "enabled plugin"**: manifest `plugins[]` is treated as the enabled set. Mapping of MCP servers to plugins for the saving estimate is not specified, so only skill tokens are used in the estimate test. The `Skill` input form for plugin skills (`plugin:name`) is covered both prefixed and plain.
8. **R5/R6/R7 `risk` values** are unspecified (only R1 = medium); not asserted. `title`/`evidence` wording not asserted except presence.
9. **`command` field**: spec example `apply.sh <id>`, text says "exact human-runnable invocation" (might include a path); tests assert `endswith("apply.sh <id>")`.
10. **`protect.json`** shape is contradictory (`"protected": true` tag vs `{"skills":[],"mcp":[]}`); not tested.
11. **Transcript format**: tests use Claude Code's real shape (`type`, `timestamp`, `message.content[]` tool_use blocks; user `message.content` as a plain string for `/name`). List-form user content is not tested. `stats.transcripts_scanned` is asserted as the count of `*.jsonl` files; `malformed_lines` as count of bad lines.
12. **`generated_at`** is asserted equal to `--now` (required for byte-identical output).
13. **R1/R6/R7 history rule boundary**: "oldest transcript within 14 days". Tests use 10 days (insufficient), none at all (treated insufficient), and 60 days (sufficient). Exactly-14 not tested.
14. **Report `(as of ...)`**, the `Breakdown` table layout, and the `Applied since last report` row format are not asserted beyond headings/ordering. Frontmatter `date` assumed = run date (2026-10-19).
15. **AC31**: a newly created untracked report necessarily changes `git status`. Test compares `.git` file hashes and `git log --all` before/after, and expects only `?? Reports/` in status.
16. **AC40**: the "older than most recent Monday 09:00" and "current ISO week" clauses conflict for a `last-run` earlier on the same Monday before 09:00, and "most recent Monday 09:00 not yet passed" is unclear when `last-run.json` is absent. Tests avoid those edges: last-run in current week = no-op; previous week / failed / absent = runs (using a Wednesday `now`). Log text `catch-up: not needed` is searched in stdout, stderr and `logs/run.log`.
17. **AC39/42 CLI shape**: `install.sh --render-only <path>` (separate argument) and `uninstall.sh --render-only` (spec says "`--render-only`/dry mode"; only `--render-only` is used). Spec has one plist but both `run.sh` and `run.sh --catch-up` invocations; `ProgramArguments` is only checked for `/bin/bash -lc '...run.sh...'`. `next fire time` print and state-dir mode 700 for install are not tested (non-render path would call launchctl).
18. **`--json` and `--force`/`--yes` position** on `apply.sh` is unspecified; tests put them after the id (or after `--revert <id>`).
19. **Patch with missing parent** (`add /env/X` when `/env` is absent): RFC 6902 says error, spec does not say; tests always keep the parent present. Whether a no-op `add` writes a backup/log is read literally as "counts as already applied" = nothing written.
20. **`shell` proposal with `--yes`**: whether it writes backups or `applied.jsonl` is unspecified; only exit 0 and the argv effect are tested.
21. **Backup/log failure exit code** (AC37) is unspecified; tests assert non-zero and unchanged settings.
22. **State perms** (dir 700 / files 600), lock handling (`mkdir lock`, stale PID reclaim), `logs/context-raw.<ts>.txt` on exit 3, and exit 12 (report failure) are specified but have no AC and unknown formats; not tested (raw log is only checked for redaction when present).
23. **Context window notation**: `1m` in the `before` capture is read as 1,000,000.
24. **Unknown `/context` rows**: `other` key naming (as-is vs snake_case) unspecified; test matches case-insensitively on a substring; whether `other` counts toward `category_sum_check` is unspecified (not asserted).
25. **Plugin info for the manifest probe** (`installed_plugins.json` shape) is "or equivalent" and not tested.

## AC coverage map

| AC | Test(s) |
|---|---|
| 1 | test_probe.TestProbeInvocation.test_ac01 |
| 2 | test_ac02 |
| 3 | TestLedgerLine.test_ac03_* (2) |
| 4 | TestContextParsing.test_ac04_* (3), TestRealCaptures |
| 5 | test_ac05_* (5) |
| 6 | test_ac06_* (3) (value assertions limited, gap 1) |
| 7 | test_ac07_* (2), TestRealCaptures.after2 |
| 8 | test_ac08_* (3) |
| 9 | TestManifest.test_ac09_* (12) |
| 10 | TestSecrets (2) |
| 11 | test_ac11 |
| 12 | test_analyze.TestDeterminismAndShape.test_ac12_* (2) |
| 13 | TestRegressions.test_ac13_* (4) |
| 14 | test_ac14_* (4) |
| 15 | test_ac15, baseline_still_produces_proposals |
| 16 | TestRulesR1.test_ac16_* (9) |
| 17 | test_ac17_* (4) |
| 18 | TestRulesR2 (5) |
| 19 | test_ac19_* (2) |
| 20 | test_ac20_* (2) (partial, gap 5) |
| 21 | test_ac21_* (3) |
| 22 | test_ac22_* (5) |
| 23 | TestProposalContract.test_ac23_* (5) |
| 24 | test_ac24_* (4) |
| 25 | test_ac25 (static ast check) |
| 26 | test_run_report.TestReport.test_ac26_* (2) |
| 27 | test_ac27_* (3) ($ spend form untestable, gap 1) |
| 28 | test_ac28_* (2) |
| 29 | test_ac29_* (2) |
| 30 | test_ac30_* (3) + notify_one |
| 31 | test_ac31 |
| 32 | test_apply.TestApplyBasics.test_ac32_* (3) |
| 33 | test_ac33_* (2) |
| 34 | TestRevert.test_ac34_* (4) |
| 35 | test_ac35_* (2) |
| 36 | TestExitCodes.test_ac36_* (7) |
| 37 | test_ac37_* (2) |
| 38 | TestRunOrchestration.test_ac38 |
| 39 | test_schedule.TestInstall.test_ac39_* (5) |
| 40 | test_ac40_* (4) |
| 41 | test_ac41_* (3) |
| 42 | TestUninstall.test_ac42_* (3) |
| 43 | TestRulesR3toR7.test_ac43_* (3) |
| 44 | TestRealCaptures.test_ac44_* (4) |

All 44 ACs have at least one test; none are omitted as untestable (AC20, AC27 and AC6 are partially covered, see gaps).

## Amendments 10c330e (R1 long-description, R7 surfaces, spend breakdown, AC 45-51)

Rewritten: all R1 tests (now `skill-desc-long-<name>` flag, tokens > 150, saving tokens-60, usage-independent, never a skillOverrides patch); AC17 (R1/R8/R9 unaffected by the history guard); R7 tests (now surfaces-aware; MCP usage no longer relevant); report heading order (adds `Spend breakdown` after `Breakdown`). Old skill-usage matching is now only exercised through R7 (plugin skills, incl. `subagents/` files). `apply.sh` mechanics tests still use synthetic `skill-off-*` ids purely as arbitrary json_patch proposals.

New gaps:
26. **Plugin discovery for `surfaces`**: tests write `plugins/installed_plugins.json` as `{"version":2,"plugins":{"<name>@<mkt>":[{"installPath":...,"version":...}]}}` plus `enabledPlugins` in settings; the spec only says "or equivalent". `plugin.json` location is unspecified, so the fixture writes it both at the plugin root and in `.claude-plugin/`. Plugin name is expected as the part before `@`. A mods status-line module marker (4.1.2) is not tested (unspecified file layout); mods `hooks/register.*` is tested with `register.ts`.
27. **`messages_counted`** is asserted as the count after dedupe (the spec example does not define it).
28. **`TOKEN_BUDGET_PRICES`** is assumed to be a path to a JSON file in the prices.json shape; the override replaces the whole table.
29. **R8/R9 evidence format** is unspecified; tests accept `0.71`/`71` style numbers. R8/R9 on a ledger line with no `spend_breakdown` are assumed not evaluated.
30. **`est_usd`/shares** are compared with tolerance (3-4 dp); exact serialisation of fractions beyond 4 dp is unspecified. A missing `requestId`+`message.id` pair uses whichever id exists (tested with message.id only).
31. **Report `## Spend breakdown` table layout** is only checked via content (family names, label `estimate (prices as of 2026-10-11)`, ratio as 0.625 or 62.5, shares words, top-session rows, `ccusage n/a`, a 7-day window mention). Frontmatter `spend_est_usd_7d` is asserted equal to total est USD.
32. R1 `command`/`evidence` wording for flags is unchecked beyond presence; `command` need not end with `apply.sh <id>` for flags (only json_patch/shell proposals are checked).

AC map additions: 16 -> TestRulesR1 (9); 17 -> test_ac17_* (5); 26 -> heading order (updated); 45 -> TestRulesR3toR7.test_ac45_* (4) + test_spend.TestSurfaces (2); 46 -> TestDedupe (5); 47 -> TestSpendMath.test_ac47_* (8); 48 -> test_ac48_* (3); 49 -> TestShares (3); 50 -> TestSpendRules (9); 51 -> TestSpendReport (3).
