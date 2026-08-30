# tests/golden/

Golden files for structured payloads (`info`, `doctor`, `meta get`, `text
--layout`, `tables`, and each verb's `-o json` result), compared as **parsed
dicts, not raw strings** — key order is never a false failure.

## Convention

- One file per case: `<name>.json`, referenced from a test as
  `golden.compare("<name>", payload)`.
- Regenerate with `uv run pytest --update-golden`, then **review the diff**
  before committing — a golden update that nobody looked at is not a review,
  it is a rubber stamp.
- **Goldens are built from the generated corpus only, never from a sample**
  (`PLAN.md` §10.1 rule 4) — nothing from `$PDF_TOOLKIT_SAMPLES_DIR` may ever
  enter a golden file.
- An ordinary `pytest` run never writes here. A missing golden file fails the
  test with a message pointing at `--update-golden`; it is never
  auto-created.

## At PDF-06 landing

This directory is empty on purpose: `version`, `doctor` and `info` do not yet
have a golden test of their own (PDF-06 is a tests-and-tooling spec, Scope
§Non-goals — "not a per-verb test suite"). The primitive itself is
self-tested in `tests/unit/test_golden.py`, entirely inside a scratch
directory, so this directory stays untouched until the first spec that needs
it.
