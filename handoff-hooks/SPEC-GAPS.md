# Spec gaps (ACs / behaviours not covered)

- 75 s Haiku timeout (`timeout after 75s`): cannot be shortened; a test would cost 75 s. Not covered.
- 3.3 degraded file: cannot be provoked from outside. Not covered.
- Unwritable handoffs dir (section 7): not tested (permission semantics fragile as root/macOS); only exit-0 behaviour on garbage stdin covered.
- Excerpt details (last 40 messages, 2500/30000 char caps, `[tool Name: ...]` rendering) are specified in section 4 but no AC pins them; only `USER: <msg>` on stdin (AC 13) is checked.
- Several per-message truncation limits (600/150/200/1500 chars, 4000 Haiku) only partly asserted (AC 12, 15, 24).
- AC 24 "stale-agent file + large sections" with exact trim boundaries: the test asserts a prefix-drop invariant and cap, not exact byte thresholds.
- Haiku-heading position when a failure line exists with fallback enabled and a fresh meta: covered implicitly only.

## F37 (AC 72-80)

- AC 73 k=8: the eight non-user sections are each size-capped (decision lines ~220 chars, 10 max), so their drop cannot be forced from transcript content alone within 20,000 chars. Test inflates the header with a very long nonexistent `cwd`, which removes the `## Git` section; it therefore asserts the first 7 PRESENT names of F37.2 are dropped (all non-user sections) and Last user messages (8 entries) is kept. A literal "first 8 names incl. Git" is untestable black-box. k=1 and k=3 are literal (bisection over task count).
- AC 73 calibration is by bisection on a fixture knob (task count / cwd length); the spec gives no section sizes.
- AC 75: "N = chars not inlined" tested as len(file.strip()) - len(inlined text), i.e. the blank-line separator before the first cut section is counted as not inlined. "(sections: <names>)" tested as heading text without `## `, joined ", ", for every section not inlined. "Greedy" cut (next whole section would not have fit under 9,700) is tested only with a 400-char tolerance because the spec does not say whether the continuation line counts toward 9,700.
- AC 75 (F37.5 amendment, long names): shortened section-name list `, ...` form is not asserted exactly; only total < 10,000 per part and the continuation regex.
- AC 77: position of `inline_cut` among health keys is unspecified; tests require the 13 F36 keys in their order plus `inline_cut` anywhere (AC 49 tests updated accordingly).
- AC 77 `inline_cut` prediction is tested at 12,000 (true) and ~5,000 (false) only; the exact 10,000 boundary and the degraded-warning prefix contribution are not tested.
- AC 78 as written (19,000 chars, two parts) is borderline infeasible with whole-section cuts (two budgets of ~9,430 + ~9,650). Superseded by F37.6: tests deliver 17,500/19,000/20,000-char files and sections up to ~5,500 chars across parts 1-3 and compare line-for-line ignoring blank lines (a section split across parts at a line boundary is allowed for oversized sections).
- Part-3 continuation line (path-only form) and part-2 continuation (`part 3 below and in`) are tested by regex; the exact N semantics for parts 2-3 are not asserted.
- AC 80: the template is located relative to HANDOFF_HOOKS_DIR (`<hooks dir>/../settings.template.json`); command matching is regex `postcompact-inject.py --part[ =]K`. Bootstrap/canary registration (F37.6) is covered only by the canary test's settings assertion (three 10 s hooks plus the 90 s PreCompact).
- AC 75 section names in the continuation line: accepted either as the full heading text or with a trailing parenthetical (e.g. "(last 30)") removed; the spec does not say which.
