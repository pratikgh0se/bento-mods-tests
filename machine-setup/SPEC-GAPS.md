# Spec gaps / literal readings (machine-setup contract tests)

- AC 81 says `core.hooksPath githooks`; layout and AC 28 say `setup/githooks`; tests use `setup/githooks`.
- Empty `LABEL_PREFIX=` is treated as invalid (does not match the 11.5 regex).
- Overlay launchd capture file name: AC 61 literal `overlay/launchd/<rendered label>.plist` (11.6 says `<name>.plist`).
- Spec conflict: overlay `config.env` matches the secret-scan forbidden name `*.env`, so export's overlay secret-scan reports FORBIDDEN-FILENAME; tests (AC 61 custom prefix) assert the spec'd exit 0 and fail until resolved.
- AC 42 "duplicates removed": tests expect duplicates inside the template array to be removed too.
- AC 64: only `secret-scan: FAIL` presence is asserted, not that it is the last output line (leak scan may follow).
- AC 51: autosync template env wiring only asserted as the `MACHINE_SETUP_PRIVATE` string plus the overlay path in the plist (env dict or inline form).
- AC 50/4 handoffs dir is `.local/state/claude-handoffs` (spec update 2026-10-16).
- Unspecified formats assumed: `repos.optional` one name per line; plugin list shim output `> id@marketplace`.
- AC 73 "not embedded in longer hex token" tested with a leading hex char.
- Tests that need `launchd/deps.tsv` in the public tree for template jobs write their own fixtures.
- AC 87/88: notification text is matched literally including the parenthesised `commit(s)`; K always uses the literal `@{u}..HEAD` count.
- AC 89: "with no unpushed public commits" is read to also cover `--push` (prints `nothing to publish`, exit 0). Leak findings are only asserted to include the offending path text, on stdout or stderr. Failed-push git error asserted loosely (stderr non-empty).
- AC 89: usage-on-stderr only asserted as non-empty stderr; usage wording unspecified.
- AC 90: "one sentence each" is checked only as the presence of `setup/publish.sh --push` in each README.
- AC 33 + AC 87 in one run (overlay push fails, public change held): both a `(push)` failure notification and the review notification are plausible; test only requires some osascript call contains `(push)`.
