# bento-mods-tests

Behaviour-contract tests for [machine-setup](https://github.com/pratikgh0se/machine-setup), written without ever looking at its code. Each test is derived from a numbered statement in a spec, and a separate agent builds the implementation from the same spec. The two sides only exchange pass/fail results.

![The code-blind loop: a spec feeds a tester lane and a builder lane that are separated by a wall; only pass/fail counts and failing test names flow back to the orchestrator, and a referee handles disagreements](docs/img/code-blind-loop.svg)

## Why code-blind

- **The spec is the oracle.** A test asserts what the spec says, not what the code happens to do.
- **Tests cannot be bent to fit the code.** The tester has never seen the implementation, so there is nothing to fit. Assertions are not weakened to make a failing implementation pass.
- **Disagreements surface spec gaps.** Where the spec is silent or ambiguous, the test takes the most literal reading and the gap is logged for the referee to resolve in the spec: [machine-setup](machine-setup/SPEC-GAPS.md), [handoff-hooks](handoff-hooks/SPEC-GAPS.md), [token-budget](token-budget/SPEC-GAPS.md), [compact (F33)](compact/F33-SPEC-GAPS.md). The TypeScript suites record the same kind of notes in their `CONTRACT-MAP.md` files.

The process is described in `docs/code-blind-tdd.md` in the machine-setup repository.

## What's covered

| Suite | What it tests | Tests |
|---|---|---|
| `agents` | The agents plugin and the mission board: spawned-agent display, costume mapping, pane behaviour | 378 |
| `compact` | The compact plugin: context-cost chip, payback floor, handoff detection and prompt, resume, nudges, toasts | 348 |
| `token-budget` | Token-budget probe, analyze, apply, schedule and run report, using synthetic `/context` dumps | 321 |
| `dev` | The dev plugin: git chip, worktrees, diff, PR, ports, coverage, type-check and change tracking | 214 |
| `handoff-hooks` | The precompact and postcompact handoff hooks: content, I/O, freshness, size bounds | 208 |
| `machine-setup` | Bootstrap, settings merge, overlay, export, autosync, scrub, secret scan, leak scan, publish gate | 199 |
| `usage` | The usage plugin: burn rate, plan-limit bands, cache, compaction display | 156 |
| `safety` | The safety plugin: write, bash and directory protection, UI, checkpoints and resume | 143 |
| `awareness` | The awareness plugin: heads-up toasts, focus, now-doing line, robustness | 122 |

Counts are as of 2026-10-18, 2,089 tests in total.

![Bar chart of test counts per suite, sorted descending, as of 2026-10-18](docs/img/suites.svg)

## Run the tests

Prerequisites:

- Python 3 (the Python suites use only `unittest`).
- Node and `tsc` for the TypeScript suites, which run through the `claude plugin test` runner.
- A checkout of `machine-setup` next to this repo. The default location is `~/CodeBase/machine-setup`; set `MACHINE_SETUP_REPO` if it lives elsewhere.

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

## Repo layout

```
machine-setup/    Python, one test_*.py per area; README.md maps files to acceptance criteria
handoff-hooks/    Python; helpers.py is shared
token-budget/     Python; fixtures/context/ holds synthetic /context dumps
compact/          TypeScript; *.test.ts are generated from _src/ by python3 compact/_src/build.py
agents/ awareness/ dev/ safety/ usage/   TypeScript; harness files start with _ or are named harness.ts
docs/img/         The two diagrams used in this README
```

Each TypeScript suite has a `CONTRACT-MAP.md` that maps spec statements to test names and lists the ambiguities found. For `compact`, edit `_src/` and regenerate; do not edit the generated test files.

## Contributing

- Write tests from the spec only. The spec is the files under `specs/` and the `docs/*-spec.md` files in machine-setup.
- Never read the implementation, and do not paste implementation code or output into a test or issue. Pass/fail results and failing test names are fine.
- Do not weaken an assertion to make an implementation pass. If a test and the code disagree, the spec decides.
- Log every ambiguity in the suite's `SPEC-GAPS.md` (or `CONTRACT-MAP.md` for TypeScript suites) with the reading you took.

## License

MIT, see `LICENSE`.
