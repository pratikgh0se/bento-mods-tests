# bento-mods-tests

Code-blind behaviour-contract tests for [github.com/pratikgh0se/machine-setup](https://github.com/pratikgh0se/machine-setup).

## The code-blind rule

These tests are written **only from the behaviour contracts** (the specs shipped in `machine-setup`: `specs/*.md`, `docs/*-spec.md`). The author of a test never reads the implementation, and the builders of the implementation never read these tests. Only pass/fail results cross the boundary. Where a spec is silent or ambiguous, the test takes the most literal reading and the gap is recorded in a `SPEC-GAPS.md` or `CONTRACT-MAP.md` file next to the tests. Keep it that way when contributing: do not weaken an assertion to make an implementation pass.

## Layout

| Suite | Language | What it covers | Notes |
|---|---|---|---|
| `machine-setup/` | Python (unittest) | bootstrap, settings merge, overlay, export, autosync, scrub, secret scan, leak scan, publish gate | `README.md` maps files to acceptance criteria; `SPEC-GAPS.md` |
| `handoff-hooks/` | Python (unittest) | precompact / postcompact handoff hooks | `SPEC-GAPS.md` |
| `token-budget/` | Python (unittest) | token-budget probe, analyze, apply, schedule, run report | `fixtures/context/` holds synthetic `/context` dumps; `SPEC-GAPS.md` |
| `compact/` | TypeScript | compact plugin | `CONTRACT-MAP.md`; `*.test.ts` are generated from `_src/` by `python3 compact/_src/build.py` (edit `_src/`, not the generated files) |
| `agents/` | TypeScript | agents plugin and mission board | `CONTRACT-MAP.md` |
| `awareness/` | TypeScript | awareness plugin | `CONTRACT-MAP.md` |
| `dev/` | TypeScript | dev plugin | `CONTRACT-MAP.md` |
| `safety/` | TypeScript | safety plugin | `CONTRACT-MAP.md` |
| `usage/` | TypeScript | usage plugin | `CONTRACT-MAP.md` |

## Running

Check out `machine-setup` next to this repo (default `~/CodeBase/machine-setup`). Python 3 and Node are required; the TypeScript suites run through the `claude plugin test` runner.

Python suites, from the root of this repo:

```sh
export MACHINE_SETUP_REPO=~/CodeBase/machine-setup   # default if unset
python3 -m unittest discover -s machine-setup
python3 -m unittest discover -s handoff-hooks         # HANDOFF_HOOKS_DIR overrides the hooks dir; HANDOFF_SLOW=1 enables the 75 s timeout test
python3 -m unittest discover -s token-budget          # TOKEN_BUDGET_REPO overrides the repo for this suite
```

`machine-setup/test_leakscan.py` also checks that the public tree carries no personal launchd prefix; it uses `com.<login name>` unless `PERSONAL_LAUNCHD_PREFIX` is set.

TypeScript suites, using the runner in the `machine-setup` checkout:

```sh
export BENTO_TESTS_DIR=~/CodeBase/bento-mods-tests    # path of this repo (this is the default)
~/CodeBase/machine-setup/scripts/run-contract.sh compact
~/CodeBase/machine-setup/scripts/run-contract.sh agents
~/CodeBase/machine-setup/scripts/run-contract.sh awareness
~/CodeBase/machine-setup/scripts/run-contract.sh dev
~/CodeBase/machine-setup/scripts/run-contract.sh safety
~/CodeBase/machine-setup/scripts/run-contract.sh usage
```

The runner copies the plugin and the matching suite folder into a temp directory and prints pass/fail counts and any failing test names.

## License

MIT, see `LICENSE`.
