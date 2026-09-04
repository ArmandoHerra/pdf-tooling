# CLAUDE.md

> Prime prompt for Claude Code and compatible agents working in this repository.

## What this repository is

`pdf-tooling` is an Apache-2.0 command-line tool for the common PDF chores. It **orchestrates** permissively licensed PDF engines; it does not implement PDF parsing, rendering or codecs, and it never will — that is a multi-year project and the classic memory-safety attack surface.

**Current phase:** Phase 1 (v1) complete — per-spec status lives in `ai_plans/pdf-tooling/specs/SPEC-INDEX.md`; history in `changelog.md`.

Do not restate status here. This file carries exactly one phase line, and that line is a pointer, not a status: it is written so that landing work requires editing it zero times. A status chain in a prime prompt rots within a week and then actively misleads.

## The three rules that are not negotiable

1. **Licensing is a call-graph rule, not a dependency rule.** Nothing under AGPL, GPL or LGPL may be reachable — not as an import, not as an optional extra, not as a vendored file, and **not as a `subprocess` fallback**. Specifically forbidden: PyMuPDF/`fitz`, the poppler command-line tools and `pdf2image`, Ghostscript, `ocrmypdf`, `img2pdf`, `pandoc`, `pdftk`. The realistic leak is a convenience shell-out, which a package-level licence scan structurally cannot see.
2. **Inputs are immutable by default.** `--dry-run` is *pure* — it writes nothing, anywhere. Outputs never clobber without `-f`. Every write is atomic. `--in-place` is opt-in and leaves a `.bak` sidecar.
3. **The structured output shapes and the exit-code table are public API.** Breaking either is a major version bump, not a patch. Add a code; never renumber one. Add a field; never rename one without touching the `to_dict()` a test pins.

## Layout

```
src/pdf_toolkit/
├── cli/       L1  the ONLY layer that may import the CLI framework
├── ops/       L2  framework-free verbs, pure over ports
├── safety/    L3  the single write chokepoint
├── ports/     L4  typing.Protocol definitions only
├── adapters/  L5  the ONLY modules that import an engine or spawn a process
└── output/    L6  stdout is the payload; stderr is everything else
```

`website/` at the repo root is a separate Astro 7 + Tailwind v4 landing page (GitHub Pages); see `website/README.md`.

Each package's `__init__.py` states its own contract in its docstring. Read it before editing anything in that package — the rule you are about to break is written at the top of the file.

`models.py` holds the data model and the schema version. It is shared, so each model a later change owns has a named insertion anchor; insert at your own anchor and nowhere else.

## Conventions

- Python `>=3.11`; this repo's own development environment is managed exclusively by `uv` (no hand-rolled virtualenv). End users install the published package however they prefer — `uv tool install pdf-tooling` and `pip install pdf-tooling` are both documented.
- Frozen `dataclasses` with explicit `to_dict()`. Not pydantic: startup time is a user-facing feature of a tool meant to sit in a shell loop.
- A hand-rolled table formatter. `rich` must not be imported anywhere under `src/`, even though the CLI framework pulls it into the environment.
- Engine versions come from distribution metadata, never from importing the engine and reading `__version__`.
- Conventional commit subjects, DCO sign-off (`git commit -s`). Details in `CONTRIBUTING.md`.

## Working here

```bash
uv sync        # runtime stack plus development tooling
make help      # every available target
make test      # the test suite
make ci        # the full local gate -- a SUBSET of CI, run with the same commands
```

`make ci` does not predict CI — see `.github/gate-parity.toml` and the epilogue `make ci` prints on every run for exactly what CI additionally gates. No target in it degrades to a weaker substitute or exits 0 when its check did not run.

`uv run pdftoolkit --help` is the authoritative list of what exists. If a verb is not printed there, it has not been built yet — do not write documentation, tests or website copy that claims otherwise.
