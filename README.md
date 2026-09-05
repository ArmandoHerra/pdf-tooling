# pdf-tooling

An Apache-2.0 PDF toolkit CLI in Python. One safe command-line tool (`pdftoolkit`) for the common PDF chores — `merge`, `split`, `extract`, `delete`, `rotate`, `reorder`, `rasterize`, `compose`, `create`, `text`, `tables`, `compress`, `repair`, `linearize`, `encrypt`, `decrypt`, `permissions`, `meta`, `watermark`, `stamp`, `ocr` and `convert`, plus `doctor`, `info` and `version` — built on a permissively licensed engine stack (pypdf, pypdfium2, reportlab, pikepdf, pdfplumber, Tesseract, LibreOffice) with nothing AGPL or GPL on the call graph.

Safety is first-class: a global `--dry-run`, no-clobber by default, atomic write-to-temp-then-rename, and inputs that are never mutated unless you ask for `--in-place`.

**Current phase:** Phase 1 (v1) complete — per-spec status lives in `ai_plans/pdf-tooling/specs/SPEC-INDEX.md`; history in `changelog.md`.

- **Website:** https://armandoherra.github.io/pdf-tooling/ — the public landing page (source in `website/`).

## This is not `pdftk`

`pdf-tooling` shares no code with `pdftk`, is not a fork of it, and is not a drop-in replacement for it. `pdftk` is GPL-licensed; this project is **Apache-2.0**, and its engine policy forbids anything under AGPL, GPL or LGPL from appearing as an import, an optional extra, or a `subprocess` fallback. The console script is named `pdftoolkit` precisely so the two cannot be confused on your `PATH`.

The PyPI **distribution** to install is **`pdf-tooling`**. The distribution named `pdftoolkit` on PyPI is an unrelated GPL-3.0 project and is not this software. The names this project owns, and which of them moved, are the contract in [Naming](#naming).

## Naming

The names below are this project's contract. They differ deliberately, and a reader
citing any of them should cite the table rather than the prose around it.

| Kind | Name |
|---|---|
| PyPI distribution | `pdf-tooling` |
| Repository | `github.com/ArmandoHerra/pdf-tooling` |
| Import package | `pdf_toolkit` |
| Console scripts | `pdftoolkit` (canonical), `pdf-toolkit` (alias) |

**Why the distribution is not `pdf-toolkit`.** That name sits too close to names already
on PyPI, and the distribution called `pdftoolkit` there is an unrelated GPL-3.0 project
that is not this software. The repository followed the distribution; the import package
and both console scripts did not, because they are published surfaces and moving them
would break an install that already works.

**Both console scripts are supported.** `pdftoolkit` is canonical and `pdf-toolkit` is a
documented alias; they resolve to the same entry point, and the alias is not deprecated
by this rename.

**Release history, so the install lines above can be read against it.** `v0.1.0` was
git-install-only and was never published to PyPI under either name; `v0.1.1` is the
first published release, as `pdf-tooling`; `v0.2.0` is the first published under the
renamed repository.

## Getting Started

```bash
uv tool install pdf-tooling
# or: pip install pdf-tooling
pdftoolkit --help
```

### From source

```bash
# Prerequisites: Python >= 3.11 and uv (https://docs.astral.sh/uv/)
git clone https://github.com/ArmandoHerra/pdf-tooling.git
cd pdf-tooling
uv sync
uv run pdftoolkit --help
```

`uv sync` installs the runtime stack *and* the development tooling, so there is no separate bootstrap step.

## What exists today

The CLI spine, the output contract and the exit-code contract are in place end-to-end, and every verb named at the top of this file — structure, raster, compose, text, optimize, crypto and overlay operations alike — is shipped behind them, not merely specified.

The complete top-level roster, by family:

| Family | Commands |
|---|---|
| Structure | `merge`, `split`, `extract`, `delete`, `rotate`, `reorder` |
| Raster & compose | `rasterize`, `compose`, `create` |
| Text | `text`, `tables` |
| Optimize | `compress`, `repair`, `linearize` |
| Crypto | `encrypt`, `decrypt`, `permissions` |
| Metadata & overlay | `meta` (`get` / `set`), `watermark`, `stamp` |
| Engine-backed | `ocr`, `convert` |
| Diagnostics | `doctor`, `info`, `version` |

That table is asserted against the live command tree by set-inclusion, so a verb
shipped tomorrow turns the check red with no author action — but
`uv run pdftoolkit --help` remains the authoritative list.

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

Errors are the one deliberate asymmetry: with `-o table` an error is a one-line `error: …` on stderr, but with `-o json`/`-o ndjson` it is an object on **stdout**, so a machine consumer reading stdout never has to also read stderr to learn that the run failed. That holds for **every** failure you can reach, an unknown flag and a missing argument included: those are usage errors (exit 2) carrying the same envelope, not a human `Usage:` block.

**A command group does not take the global block.** `meta` groups `meta get` and `meta set`, and the global flags are declared at the root and on every verb, never on a group — so `pdftoolkit meta -o json` is a usage error (exit 2) rather than a run. It names the two positions that do work: `pdftoolkit -o json meta get FILE` (before the group) and `pdftoolkit meta get FILE -o json` (after the subcommand).

**Global flags with no command at all** — `pdftoolkit -o json` — are an incomplete invocation and exit 2 as well, pointing at `--help`. `pdftoolkit` on its own, with no arguments, still prints help and exits 0.

### The collection key

Every `-o json` envelope that carries a collection of rows carries them under `items`. `doctor` and `info` additionally publish that same list under a name of their own, and both names are frozen: `doctor`'s `ports` is pinned by the plan's own `pdftoolkit doctor -o json | jq '.ports[] | select(.available == false)'` example, and `info`'s `documents` is its shipped shape. Neither is being renamed. The alias was added beside them so that a single `jq` expression works against every verb.

| Verb | Primary key | Universal alias | Relationship |
|---|---|---|---|
| every verb that returns an operation result | `items` | `items` | the same list |
| `info` | `documents` | `items` | the same list |
| `doctor` | `ports` | `items` | the same list |

`meta get` publishes a single document's report rather than a collection, so it has no row collection and names none.

Every `-o json` envelope also carries `exit_code`, `warnings` and `duration_ms`, on every verb. `warnings` is a list and is `[]` when empty — never `null`, never absent. `exit_code` is the code the process exits with for the run the envelope describes, and `duration_ms` is `0` on the verbs whose output must be reproducible byte-for-byte.

### A batch reports every input, and never denies a file it wrote

A multi-input run writing into `--out-dir` records **every input by name, in command-line order**, in the payload's collection — the inputs that succeeded and the input that failed alike. A failing input is recorded, the run continues, and the run exits `1` at the end; each row carries its own `ok`, `exit_code` and `message`. A row that succeeded names its artifact in `output`, and that path is on disk.

**This is a behaviour change on a failure path, inside the pre-`1.0.0` window.** A multi-input `--out-dir` failure used to emit the error envelope — `{"schema_version": 1, "error": {…, "path": null}}`, with no collection at all — in place of the operation envelope, so the input that succeeded went unreported and the input that failed went unnamed even while its sibling's artifact sat on disk. A script that parsed such a failure by reading `payload["error"]` now finds `payload["items"]` instead. **`schema_version` stays `1`**: no key is renamed, removed, retyped or repurposed, and the error envelope itself is unchanged.

Failures that are properties of the invocation rather than of an input stay run-scoped and keep the error envelope: a usage error, a directory where a file was expected, a nonexistent input, a missing engine, and the refusals the safety gate raises. A missing engine fails identically for every input, so it stays a single accurate diagnosis carrying its own exit code rather than becoming a row per input that also changes what the process exits with. A single-input run likewise reports that item's own code, which is what keeps the per-input codes distinguishable at all.

### `schema_version` is `1`, and this is what would move it

`schema_version` is `1` and stays `1` for as long as the envelope changes only by **addition**. Adding a key never moves it; nor does adding a verb, an item field, or an output format. It increments on the first change a consumer that reads keys by name cannot survive, which is exactly this list:

- a published key is **renamed**;
- a published key is **removed**;
- a published key's **type** changes — including `[]` becoming `null`, or a scalar becoming an object;
- a published key's **meaning** changes while its name and type stay the same.

An increment is **coupled to a major version bump**; they move together or not at all.

The structured shapes and the exit-code table below are **public API from v1.0.0**. Breaking either requires a major version bump and a `schema_version` increment. Pre-1.0 releases are explicitly still moving.

## Exit codes

Uniform across every verb.

| Code | Name | Meaning |
|---|---|---|
| 0 | `OK` | Success — including an empty-but-valid report. A `--dry-run` mirrors the code the real run would return, so it is not always 0. |
| 1 | `FAILURE` | The operation ran and failed — corrupt input, engine error, unwritable destination. |
| 2 | `USAGE` | Bad invocation — unknown flag, mutually exclusive flags, malformed page range, unknown subcommand, a global flag at a command group, or global flags with no command. |
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

**A password is never accepted as a command-line value.** There is no `--password`, no `--user-password` and no `--owner-password`: `argv` is world-readable in `/proc` and lands in shell history, so the harm would happen before the tool could refuse. Passing any of those three spellings is a usage error (exit 2) naming the three supported paths, in order of preference — in the separated form (`--password hunter2`) and in the joined one (`--password=hunter2`) alike, and the value is never echoed back in either:

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

### The permission vocabularies

`pdftoolkit info -o json` and `pdftoolkit permissions -o json` are **both public output**, and they spell some of their permission tokens differently. That is a documented divergence, not a defect to be tidied: both spellings shipped, both are `schema_version: 1` public API, and renaming either would break a published contract. So the crossing is published here instead. **`--allow` accepts the left column only** — the right column is `info`'s output spelling and is not an input token.

| `--allow` / `permissions` | `info` | `ISO 32000-1 Table 22` bit |
|---|---|---|
| `print` | `print` | `3` |
| `modify` | `modify` | `4` |
| `copy` | `copy` | `5` |
| `annotate` | `annotate` | `6` |
| `forms` | `fill-forms` | `9` |
| `accessibility` | `extract-accessibility` | `10` |
| `assemble` | `assemble` | `11` |
| `print-highres` | `print-high-resolution` | `12` |

The tokens spelled identically on both surfaces need no translation; the ones that diverge are the same bit under a different name. Without this table, a consumer that runs both verbs against the same encrypted document sees phantom differences on every file. The table is derived from the source constants by a test, so it cannot rot away from what the tool actually emits.

**Permission bits are advisory.** They are a request to the reader, not a lock: only cooperating readers honour them, any reader holding the file may ignore every bit, and a reader that can display a page can extract it. Encryption protects the content; the bits on their own protect nothing. `--allow` takes a comma-separated, repeatable list from `print`, `print-highres`, `copy`, `modify`, `annotate`, `forms`, `assemble`, `accessibility`, plus the exclusive `all` and `none`; omitting it grants nothing. `accessibility` is granted whatever you ask for — PDF 2.0 deprecated that bit and conforming readers always permit it — and `permissions` reports what the document actually grants rather than what was requested. **`print-highres` also grants `print`**: a reader permitted to print at full resolution may obviously print at low resolution, and the format has no spelling for “high but not low”, so asking for the one token grants two. That is the format's behaviour rather than this tool's choice, and it is disclosed at the flag that causes it instead of being left for `permissions` to reveal afterwards.

### `--password-file` is global: honoured or refused, never silently ignored

`--password-file` (and its resolution siblings — the `PDF_TOOLKIT_PASSWORD` environment variable and the interactive prompt) is declared on **every** verb, because any of them may meet a password-protected input — including the report-only ones. A verb that can open an encrypted document uses the resolved password there, on the SAME first-hit-wins chain `encrypt`/`decrypt` already document above; a verb that structurally cannot use one (it takes no document operand, or it already declares its own dedicated password flag) refuses it up front, at exit **2**, naming the flag rather than accepting it and doing nothing — the same "declared but silently inert" shape this tool refuses for every other global flag (see the safety contract above). There is no hand-maintained list of which verbs fall into which group here: run the verb's own `--help` to see the flag declared, or try it — a verb that cannot honour it says so immediately, before any document is opened.

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

`make help` lists every target. `make ci` is a **subset** of CI, run with the same commands — it does not predict CI. What runs locally, what does not, and why is declared in `.github/gate-parity.toml` and printed by `make ci`'s own epilogue on every run. No target degrades to a weaker substitute or exits 0 when its check did not run.

Contributions are accepted under the Developer Certificate of Origin (`git commit -s`). See `CONTRIBUTING.md` for the commit conventions and `TESTING.md` for how to run each suite.

## Known issues

Open defects and planned work are recorded, per finding, in the maintainer's planning tree:

- `ai_plans/pdf-tooling/BACKLOG.md` — the groomed intake list.
- `ai_plans/pdf-tooling/qa/FINDINGS-LEDGER.md` — every finding a QA sweep has raised, with its state and its evidence.

**Those artifacts live in the maintainer's planning repository and are not part of this distribution.** They are not shipped in the sdist or the wheel and are not present in a clone of this repository; the paths above are where they live for anyone reading this source tree beside it.

The most recent sweep carrying a readable verdict is `2026-09-03_113318`, taken at commit `7afdb1a`. This section names a sweep and a commit and never a tally — a count is wrong the day after it is written, and the ledger's own header could not hold one still for two days. Read the ledger for what is open right now.

If a sweep ever records nothing open, this section still stands and reads *no open findings are recorded as of sweep `<id>` (`<sha>`)*. It is not deleted: a momentarily vacuous pointer is still the affordance, and deleting it silently removes the only place a user is told where the defects are.

## License

Apache-2.0 — see `LICENSE` and `NOTICE`. `THIRD_PARTY_LICENSES` is generated from the resolved environment and ships in both the sdist and the wheel.
