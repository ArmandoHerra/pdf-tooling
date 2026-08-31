# pdf-toolkit

An Apache-2.0 PDF toolkit CLI in Python. One safe command-line tool (`pdftoolkit`) for the common PDF chores — merge, split, extract, rotate, PDF→images, images→PDF, create, text/tables, compress, encrypt, metadata, watermark, OCR, and Office→PDF — built on a permissively licensed engine stack (pypdf, pypdfium2, reportlab, pikepdf, pdfplumber, Tesseract, LibreOffice) with nothing AGPL or GPL on the call graph.

Safety is first-class: a global `--dry-run`, no-clobber by default, atomic write-to-temp-then-rename, and inputs that are never mutated unless you ask for `--in-place`.

**Current phase:** Phase 1 (v1) complete — per-spec status lives in `ai_plans/pdf-toolkit/specs/SPEC-INDEX.md`; history in `changelog.md`.

- **Website:** https://armandoherra.github.io/pdf-toolkit/ — the public landing page (source in `website/`).

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

The CLI spine, the output contract and the exit-code contract are in place end-to-end, and every verb named at the top of this file — structure, raster, compose, text, optimize, crypto and overlay operations alike — is shipped behind them, not merely specified.

```bash
uv run pdftoolkit --help               # the full verb tree; always the authoritative list
uv run pdftoolkit doctor               # which engines resolved, and how
uv run pdftoolkit merge a.pdf b.pdf -O merged.pdf
uv run pdftoolkit rotate report.pdf --pages 2-4 --angle 90 -O rotated.pdf
uv run pdftoolkit compress report.pdf -O small.pdf
uv run pdftoolkit --version            # tool, Python and engine versions on one line
```

`uv run pdftoolkit --help` is the authoritative list of what is actually available at any moment — if a verb is not printed there, it does not exist yet.

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
| 0 | `OK` | Success — including an empty-but-valid report. A `--dry-run` mirrors the code the real run would return, so it is not always 0. |
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

## Compression ceiling

Structure-level compression plus optional image downsampling is the ceiling of a permissive stack: Ghostscript is AGPL-3.0+ and deliberately excluded, so `compress` builds on `pikepdf`/libqpdf object streams and an opt-in Pillow image pass instead. `--images downsample`'s resample threshold is computed against the page's own width in inches (the page box), never an image's placement rectangle, which under-downsamples a small image on a large page — a stated, conservative limitation.

## Encryption, passwords and permissions

`encrypt` writes AES-256 (revision 6) by default. `--legacy` selects RC4-128, which is cryptographically broken and exists only for readers that predate PDF 1.7 ExtensionLevel 3; it also leaves document metadata unencrypted, because the format cannot encrypt metadata without AES. Every cryptographic operation is libqpdf's, reached through `pikepdf`. This tool implements no cryptography of its own — no key derivation, no cipher, no password comparison.

**A password is never accepted as a command-line value.** There is no `--password`, no `--user-password` and no `--owner-password`: `argv` is world-readable in `/proc` and lands in shell history, so the harm would happen before the tool could refuse. Passing any of those three spellings is a usage error (exit 2) naming the three supported paths, in order of preference:

| Path | Spelling | Notes |
|---|---|---|
| A file | `--password-file PATH`, `--owner-password-file PATH`, `--user-password-file PATH` | The first line only. A single trailing newline is stripped; no other whitespace is, because a password may legitimately end in a space. |
| Standard input | the same flags with `-` | One line. Only one slot may read from stdin per run. |
| The environment | `PDF_TOOLKIT_PASSWORD`, `PDF_TOOLKIT_OWNER_PASSWORD` | Consulted only when no flag was given for that slot. |
| A prompt | none | Only when stdin is a terminal. Never on a pipe, where it would hang. |

With none of those available the run exits **6** and writes nothing.

Run `chmod 600` on any password file. The tool warns when one is readable by group or other, and recommends exactly that — it warns rather than refuses, because refusing to read a 0644 file would break more scripts than it protects.

**The environment channel is weaker than a file, and this document says so rather than implying otherwise.** A process's environment is readable through `/proc/<pid>/environ` by any process running as the same user, and it is inherited by every child the tool spawns. A password file with restrictive permissions is the stronger choice; the environment variable exists because a CI system often has no better option.

No secure erasure is claimed, anywhere. A resolved password is held in a buffer that is zeroed after use, but Python may already have copied it while decoding the file, and swap and core dumps are outside a process's control. The same goes for the `.bak` sidecar and for temporary files: they are deleted, not shredded.

`encrypt --in-place` needs one more word from you, and it is the one place where the safety default and the security default point in opposite directions. The `.bak` sidecar is a copy of the **original**, so an in-place encryption would leave plaintext sitting next to the ciphertext, silently. So it refuses (exit 5) unless you pass `--no-backup` (keep no plaintext copy) or `-y` (keep it, knowingly).

**Permission bits are advisory.** They are a request to the reader, not a lock: only cooperating readers honour them, any reader holding the file may ignore every bit, and a reader that can display a page can extract it. Encryption protects the content; the bits on their own protect nothing. `--allow` takes a comma-separated, repeatable list from `print`, `print-highres`, `copy`, `modify`, `annotate`, `forms`, `assemble`, `accessibility`, plus the exclusive `all` and `none`; omitting it grants nothing. `accessibility` is granted whatever you ask for — PDF 2.0 deprecated that bit and conforming readers always permit it — and `permissions` reports what the document actually grants rather than what was requested.

`decrypt` round-trips the **page tree** byte for byte: the decoded content streams, the page dictionaries and every embedded image's raw bytes come back identical. The whole file does not, and nothing here claims it does — `/ID`, `/Encrypt`, the trailer, the cross-reference table and object numbering all legitimately change on any resave.

## OCR and Office conversion

`ocr` and `convert` are the two verbs that depend on a system binary rather than a Python wheel — the two verbs `pdftoolkit doctor` can legitimately report as unavailable.

`ocr` drives the **tesseract** binary. For every selected page it renders the page, recognises a text-only layer, and overlays that layer on the **original** page object — the page's own image is never re-rendered, and a byte-level check proves the image stream is identical before and after. `--skip-text-pages` leaves a page that already has extractable text untouched (no render, no OCR call). This build ships whatever tessdata language packs the host has installed; `--lang` is validated against exactly that list (`pdftoolkit doctor`), and a pack that is not installed exits 3 with an install hint naming it. No accuracy or confidence claim is made anywhere in this tool — `ocr` is described here by its engine, not by a quality promise.

`convert` drives headless **LibreOffice** (`soffice`) to turn an office document into a PDF. Each invocation gets its own isolated LibreOffice profile directory and converts into a private scratch location first — LibreOffice never writes to the destination directly, and the destination is only touched through this tool's one write chokepoint. An exit 0 from `soffice` having produced no output file is treated as a failure here, not a success, because that is a real and well-known LibreOffice failure mode. `--timeout` bounds one conversion; on expiry the whole process group is killed, so no `soffice.bin` daemon is left running.

## Development

```bash
make test      # run the test suite
make ci        # the full local gate: format, lint, types, tests, licenses, SAST, CVEs
```

`make help` lists every target. The local gate is the CI gate: `make ci` runs exactly the checks CI runs, in the same order, with the same commands. No target degrades to a weaker substitute or exits 0 when its check did not run.

Contributions are accepted under the Developer Certificate of Origin (`git commit -s`). See `CONTRIBUTING.md` for the commit conventions and `TESTING.md` for how to run each suite.

## License

Apache-2.0 — see `LICENSE` and `NOTICE`. `THIRD_PARTY_LICENSES` is generated from the resolved environment and ships in both the sdist and the wheel.
