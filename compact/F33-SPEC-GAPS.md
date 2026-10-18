# F33 spec gaps and reading choices (contract tester)

1. Rounding of pct (stmt 27): spec says 410k of 400k reports "102%" (410/400 = 102.5). Tested literally (`102%`). An implementation that rounds half up prints 103% and fails C27. Spec should say floor or round.
2. Dotted option spelling (stmt 33): `mod.nudge.enabled`=false is tested literally. `mod_resume_enabled` only the underscore spelling is tested (spec names only that one).
3. `isFresh(meta, size, now)` (stmt 35): the spec says "exported for the contract" but gives no module path or signature home, so it cannot be imported from a code-blind test. Freshness rules are tested through Resume instead (49,999/50,001, 299/300 bytes, 29/31 min, no agentWrittenAt, written after lastNudgeAt). The direct-call test is registered as skipped.
4. Statement 35 "ctxTokens": taken as the context at the moment of the compaction (last measure). Tests make the last measure before compaction coincide with the last meta write, so the 10k meta-write lag does not matter.
5. Write detection before the first nudge: spec does not say whether an agent-file Write before any nudge is recorded. Tested as recorded (C35 49,999 / C42 50,001 write at 250,001 / 249,999 then nudge at 300k).
6. "No write detected" (stmt 42): modelled as the file existing on disk with no Write tool call and no measure after the first delivery (a later measure would adopt its mtime per F33.4).
7. Stmt 38 "unchanged": for `session.usage` / `fs.stat` rejecting, only "no throw, result/text/deny unchanged" is asserted (the nudge may legitimately still be delivered because env gives W). For `env.get` rejecting the context is asserted unchanged (Opus window 1M, t=300k).
8. Stmt 38 latency: "no `$` call besides `$.clock.after`" is asserted with `clock.now` also tolerated (the hook needs the time for agentWrittenAt; the spec's "pure-memory read" is unspecified).
9. Stmt 39: "returns the exact `next` object" is asserted with deep equality, not identity (engine may re-box). The `.catch(($, e, next) => next(e))` property and "no tool.call hook registered" when the mod is off (stmt 33) are not observable through the engine; the latter is covered by "results equal input".
10. Stmt 43: a cancelled `/handoff` that did save a file is not tested (cancel semantics are not defined in F33; `--no-compact` is).
11. Stmt 29 "subagent turn does not arm": only subagent `session.measure` is tested (a turn does not arm anything in the spec).
12. Stmt 36 "Coach verdict identical on/off": compared as the compact `coach` state JSON plus both band texts, snapshot taken in two consecutive tests (ON then OFF) via a module variable.
13. Stmt 28 Resume + nudge: the Resume entry is made pending with a `/handoff` before compaction; the nudge is armed after the compaction by a fresh measure at 300k.
