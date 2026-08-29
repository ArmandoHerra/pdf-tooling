# pdf-toolkit

An Apache-2.0 PDF toolkit CLI in Python. One safe command-line tool (`pdftoolkit`) for the common PDF chores — merge, split, extract, rotate, PDF→images, images→PDF, create, text/tables, compress, encrypt, metadata, watermark, OCR, and Office→PDF — built on a permissively licensed engine stack (pypdf, pypdfium2, reportlab, pikepdf, pdfplumber, Tesseract, LibreOffice) with nothing AGPL or GPL on the call graph.

Safety is first-class: a global `--dry-run`, no-clobber by default, atomic write-to-temp-then-rename, and inputs that are never mutated unless you ask for `--in-place`.

**Current phase:** Phase 1 (v1) — per-spec status lives in `ai_plans/pdf-toolkit/specs/SPEC-INDEX.md`; history in `changelog.md`.

## This is not `pdftk`

`pdf-toolkit` shares no code with `pdftk`, is not a fork of it, and is not a drop-in replacement for it. `pdftk` is GPL-licensed; this project is **Apache-2.0**, and its engine policy forbids anything under AGPL, GPL or LGPL from appearing as an import, an optional extra, or a `subprocess` fallback. The console script is named `pdftoolkit` precisely so the two cannot be confused on your `PATH`.

The PyPI **distribution** to install is **`pdf-toolkit`** — with the hyphen. The distribution named `pdftoolkit` on PyPI is an unrelated GPL-3.0 project and is not this software. The import package is `pdf_toolkit`, and the installed console scripts are `pdftoolkit` and `pdf-toolkit`; the three names differ deliberately.

## Getting Started

```bash
# Prerequisites: Python >= 3.11 and uv (https://docs.astral.sh/uv/)
git clone https://github.com/ArmandoHerra/pdf-toolkit.git
cd pdf-toolkit
uv sync
uv run pdftoolkit --help
```

`uv sync` installs the runtime stack *and* the development tooling, so there is no separate bootstrap step.

## What exists today

The CLI spine is in place and end-to-end: the global flag block, the output contract, the exit-code contract, and one verb that exercises all of them.

```bash
uv run pdftoolkit --version            # tool, Python and engine versions on one line
uv run pdftoolkit version              # the same, as a rendered payload
uv run pdftoolkit version -o json      # structured, one object
uv run pdftoolkit version -o ndjson    # structured, one object per line
```

The document verbs listed at the top of this file are planned, not shipped. `uv run pdftoolkit --help` is the authoritative list of what is actually available at any moment — if a verb is not printed there, it does not exist yet.

## Output contract

Rendered payloads go to **stdout**; diagnostics, warnings and progress go to **stderr**. `-o` selects the shape and defaults to `table` when stdout is a terminal and `json` when it is not, so piping into `jq` needs no flag.

| Shape | Behaviour |
|---|---|
| `-o table` | An aligned, plain-text table. No colour when `--no-color` is passed, when `NO_COLOR` is set, or when the stream is not a terminal. |
| `-o json` | One object, carrying `schema_version`. |
| `-o ndjson` | One object per item, one per line, **each line carrying its own `schema_version`** so a single streamed line is self-describing. |

Errors are the one deliberate asymmetry: with `-o table` an error is a one-line `error: …` on stderr, but with `-o json`/`-o ndjson` it is an object on **stdout**, so a machine consumer reading stdout never has to also read stderr to learn that the run failed.

The structured shapes and the exit-code table below are **public API from v1.0.0**. Breaking either requires a major version bump and a `schema_version` increment. Pre-1.0 releases are explicitly still moving.

## Exit codes

Uniform across every verb.

| Code | Name | Meaning |
|---|---|---|
| 0 | `OK` | Success. Also a completed `--dry-run`, and an empty-but-valid report. |
| 1 | `FAILURE` | The operation ran and failed — corrupt input, engine error, unwritable destination. |
| 2 | `USAGE` | Bad invocation — unknown flag, mutually exclusive flags, malformed page range, unknown subcommand. |
| 3 | `ENGINE_MISSING` | A required engine or binary is unavailable. The message always carries an install hint. |
| 4 | `NO_INPUT` | Valid invocation, nothing to act on. |
| 5 | `REFUSED` | A safety gate declined. |
| 6 | `AUTH` | Password required, incorrect, or of the wrong kind. |

## Safety contract

- `--dry-run` plans and reports; it writes nothing, anywhere.
- Outputs never clobber. An existing target needs `-f/--force`.
- Every write is write-to-temp-on-the-target-filesystem, `fsync`, then an atomic rename.
- Inputs are never mutated unless you pass `--in-place`, which writes a `.bak` sidecar first. `--no-backup` suppresses the sidecar and requires `--in-place` — on its own it is a usage error.
- A password is never accepted as a command-line value. `--password-file` takes a path or `-`, because `argv` is world-readable in `/proc` and lands in shell history.

## Development

```bash
make test      # run the test suite
make ci        # the full local gate: format, lint, types, tests, licenses, SAST, CVEs
```

`make help` lists every target. The local gate is the CI gate: `make ci` runs exactly the checks CI runs, in the same order, with the same commands. No target degrades to a weaker substitute or exits 0 when its check did not run.

Contributions are accepted under the Developer Certificate of Origin (`git commit -s`). See `CONTRIBUTING.md` for the commit conventions and `TESTING.md` for how to run each suite.

## License

Apache-2.0 — see `LICENSE` and `NOTICE`. `THIRD_PARTY_LICENSES` is generated from the resolved environment and ships in both the sdist and the wheel.
