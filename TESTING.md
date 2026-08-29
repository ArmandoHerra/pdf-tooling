# Testing

## Running the suites

```bash
uv sync
make test          # everything
make test-e2e      # only the subprocess-level CLI tests
make cover         # the suite under coverage, against the project's floor
```

`make cover` is deliberately **not** part of `make ci`. The coverage floor becomes a gate once the fixture corpus and the per-verb contract harness exist; enforcing it against a spine with one placeholder verb would measure nothing and block everything.

Individual files and selections work as usual:

```bash
uv run pytest tests/test_cli_spine.py -q
uv run pytest -k renderer -q
uv run pytest -m e2e -q
```

## What the current suites cover

- **`tests/test_cli_spine.py`** — the command surface and its exit codes, the exit-code constants themselves, the three renderers and their stream discipline, the structured error shape, global-flag precedence across both declaration levels, the mutually exclusive flag pairs, and the startup budget.
- **`tests/test_docs_antirot.py`** — that the documentation cannot silently rot: one phase line per prime document, no specification identifiers or counts embedded in them, and every `make` target mentioned in the documentation actually existing in the `Makefile`.

## Markers

| Marker | Selects |
|---|---|
| `e2e` | Tests that run the installed console script as a subprocess. Slower, and the only ones that measure real process startup. |

Run `uv run pytest --markers` for the registered list.

## Skips are visible, never silent

Two classes of test cannot always run:

- **Engine-absent tests.** Some engines are system binaries rather than Python wheels, so they can legitimately be missing on a given machine or CI leg.
- **Real-document tests.** The generated fixtures prove the *contract*; they cannot prove the tool survives documents produced by other software. Those arms read an operator-provided corpus that lives outside the repository and is never committed.

In both cases the rule is the same and it is not negotiable: **a test that cannot run reports as a skip, with a reason.** It never passes silently. A green run that proved nothing is worse than a red one, because it is believed.

Deleting or weakening a failing test so the suite turns green is never an acceptable fix. If a test cannot pass for a reason outside the change, say so explicitly in the change's description and leave the test in place.

## Determinism

Every test writes into pytest's own temporary directory and never into the repository tree. Nothing that a test asserts depends on wall-clock timing, on the order tests run in, or on which machine runs them — with one deliberate exception: the startup-budget test measures real elapsed time. It takes the **fastest** of several runs rather than the mean, so scheduler noise cannot turn it red while a genuine regression still will.
