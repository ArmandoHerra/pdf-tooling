# Contributing

Thanks for considering a contribution. This document is short on purpose: everything it asks for is mechanically checked, so you can verify you have satisfied it before you push.

## Developer Certificate of Origin

Every commit must be signed off:

```bash
git commit -s -m "feat: add the thing"
```

That adds a `Signed-off-by:` trailer, which is your statement that you have the right to submit the work under this project's licence. There is no CLA. Commits without the trailer are rejected.

## Commit conventions

Conventional commit subjects: `feat|fix|docs|refactor|test|chore`, imperative mood, no trailing period.

Work that implements a planned specification carries that specification's tag as a subject prefix, so the change and its rationale can be found from either direction:

```
[PDF-NN] feat: <what the specification delivers>
```

Write the subject about the *why*, not the *what* — the diff already says what changed.

Each implemented specification appends **its own** entry to `changelog.md`, in the same commit as the code. Entries go directly below the anchor comment, newest first. Never batch entries, never back-fill one later, and never edit an entry that has landed — a correction is a new entry with a new date.

## The local gate

```bash
uv sync
make ci
```

`make ci` is a **subset** of CI, run with the same commands. It does not predict CI — `.github/gate-parity.toml` declares exactly what runs locally and what does not, why, and where a local counterpart exists; `make ci`'s own epilogue prints that gap on every run, and `make help` lists every target it does not run.

Three things about the gate are deliberate and should not be "fixed":

- **No target degrades.** No recipe ends in `|| true`, is prefixed with `-`, or swallows a missing tool. A gate that cannot fail is not a gate; a check that quietly did not run is worse than one that failed loudly.
- **`make secret-scan` needs the `gitleaks` binary** and fails loudly when it is absent, rather than passing. It is not part of `make ci` locally: the local binary, when present, is a different scanner version than the one CI pins (`GITLEAKS_VERSION` in `ci.yml`), so running it inside `make ci` would trade a known gap for an unnoticed one — same command, different check.
- **Some CI checks are not part of `make ci` at all, on purpose.** A few (`make engines-gate`, `make licenses-check`, `make artifacts-check`) are runnable on demand but cost real wall-clock; others need CI's own host, matrix, or a pinned binary and have no local form. `.github/gate-parity.toml` is the record of which is which.

Individual targets, when you want a faster loop:

```bash
make fmt          # format the tree
make lint         # lint
make typecheck    # strict type checking of src/
make test         # the test suite
make test-e2e     # only the subprocess-level CLI tests
```

`make help` lists every target.

## What a change must not do

- **Add anything under AGPL, GPL or LGPL to the call graph** — not as an import, not as an optional extra, not as a `subprocess` fallback. This is a licence-compatibility rule, not a preference, and it is checked in CI.
- **Add a runtime dependency.** The runtime stack is declared up front and deliberately frozen: the licence manifest is generated from the lockfile and diffed in CI, so a mid-stream addition turns that check red on an unrelated commit and the failure looks like something else entirely. If you believe you need one, raise it before writing the code.
- **Change an exit code or a structured output field.** Both are public API. Adding is fine; renumbering and renaming are major-version changes.
- **Import the CLI framework below the CLI layer**, or write to a user-visible path outside the safety layer. Both are enforced by tests, not by review alone.

## Tests

See `TESTING.md` for how each suite is run and what a legitimate skip looks like. The short version: a test that cannot run because an engine or a corpus is missing must **skip visibly, with a reason** — never pass silently, and never be deleted so the suite turns green.
