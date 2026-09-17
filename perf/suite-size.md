# The suite's own size — the one definition

**This is an ANCHORED measurement and never a gate.** The whole-suite size moves
with every spec that adds an arm, so a gate on it would red on every landing and
would be edited to green as a reflex — a gate nobody believes is worse than no
gate. What is guarded instead is that the figure is stated in exactly one place,
that it names its observable, and that the commit it names resolves in this
repository and is an ancestor of `HEAD`. All three are asserted by
`tests/test_docs_antirot.py`; the sentence in `TESTING.md` is rendered from the
record below by that module's derived-figure registry, so the document cannot
drift away from this file.

**The observable is `collected`, not `passed`, and the choice is the point.**
`passed` varies with engine presence, interpreter availability and the odd load
flake — which is exactly how this one suite came to circulate under three
different figures at once (`4486`, `4490`, `4526`), every one of them true, not
one of them saying which quantity at which commit. `collected` is
host-independent: it counts what the collector found, before a single test runs.

**Record shape inherited from `perf/branch-partials.md`** (`PDF-73`): a
provenance table whose rows are a key code span and a value code span, read by
the same ``_PARTIALS_FIELD`` reader in `tests/test_docs_antirot.py`. A second
shape for a second commit-anchored figure is how two artefacts start disagreeing
about what a field means, so no second shape was invented. Rows whose value is
prose carrying more than a single code span (the interpreter, host and engine
rows) are human provenance and are deliberately not machine-read — the same
split `perf/branch-partials.md` already makes.

## Provenance

| Field | Value |
|---|---|
| `commit` | `c76f0db3d83b6adb2e4785512e3030a1b54d13a5` |
| `date` | `2026-09-17` |
| `observable` | `collected` |
| `command` | `uv run pytest --collect-only -q` |
| `collected` | `5348` |
| `dirty` | `false` |
| `interpreter` | `3.12.13` via `uv run python`, prefix `/home/station-01/repos/ClaudeCode_Harness/apps/pdf-tooling/.venv` |
| `host` | `Linux-7.0.0-31-generic-x86_64-with-glibc2.43` (`x86_64`) |
| `engines` | `tesseract`: `/usr/bin/tesseract` · `soffice`: `/usr/bin/soffice` |

## How to refresh it

```bash
git rev-parse HEAD                      # the commit the figure belongs to
uv run pytest --collect-only -q | tail -1
```

Take the measurement on a clean tree, write BOTH the figure and the commit, and
let `make test` re-render `TESTING.md`'s sentence from it. Writing the figure
without moving the commit is the failure this record exists to make impossible:
the anchor arm reds if the sha does not resolve, and skips — never passes — on a
clone too shallow to answer.

**For the size at the commit you are on, run the command.** Do not carry this
figure forward; that is how the three renderings above happened.
