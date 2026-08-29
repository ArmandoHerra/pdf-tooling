# Changelog

All notable changes to pdf-toolkit, newest first. **One entry per implemented spec,
written by that spec's own commit** — never batched, never back-filled, never edited
afterwards (a correction is a new entry).

Entry format: `## [PDF-NN] <Spec title> — <YYYY-MM-DD>`, then 1–5 bullets.
New entries are inserted **directly below the anchor line**, above the previous newest entry.

Three rules bind every entry:

1. **Append at the top, at the anchor.** Never at the bottom, and never inside another
   entry.
2. **Each spec's own commit writes its own entry**, so `git show <sha> -- changelog.md`
   proves the entry and the code landed together.
3. **Never edit a landed entry.** A correction is a new entry with a new date.

Audit this file per commit with `git show <sha> -- changelog.md`, never with a heading
grep at `HEAD` — a grep at `HEAD` is exactly what hides a lost prepend.

<!-- CHANGELOG-ANCHOR: insert new entries directly below this line, newest first -->

## [PDF-04] Safety spine (atomic writes, no-clobber, --in-place, -y gate) — 2026-08-29
- Added the write chokepoint under `src/pdf_toolkit/safety/`: `atomic.py`
  (`AtomicWriter` — dry-run gate as the first statement of `__enter__`, temp beside the
  resolved destination, `flush`/`fsync`, the `.bak` sidecar via `os.link` with a
  `shutil.copy2` fallback, `os.replace`, and an `EXDEV` path that copies, fsyncs,
  replaces and then verifies size **and** SHA-256), plus `paths.py` (alias-safe identity,
  no-clobber, planned-output collision, `ensure_within`, destination writability),
  `tempnames.py` (`TEMP_PREFIX`, `find_stray_temps` — reports, never sweeps, per
  `PLAN.md` §12 R-07), `confirm.py` (the bulk-destructive `-y` gate, which fails closed
  and immediately on a non-terminal) and `_faults.py` (an inherited-pipe crash
  rendezvous, inert unless a test asks for it). `SafetyPolicy.validate()` now owns
  `--no-backup` without `--in-place` (exit **2**) and `cli/common.py` delegates to it;
  `cli/main.py` gained `build_rerun_hint()`. Eight error classes added to `errors.py`,
  all subclasses of existing ones, so no new exit-code integer entered the public table.
- Added `tests/test_import_boundaries.py`: an AST walk over every file under `src/` that
  fails on any of fourteen filesystem-mutating call groups outside
  `safety/atomic.py`. Two tiers, two allowlists, **both empty and asserted empty**,
  stale-entry detection, five planted violations proving the walk bites, and a negative
  self-test proving `str.replace`, `list.remove`, `dict.copy` and `open(p, "rb")` are
  not flagged. Shared and append-only — PDF-05 and PDF-06 add their sections to it.
- Added `tests/fs_snapshot.py`, the `--dry-run` purity primitive (inode, mode, size,
  mtime, content hash, symlink target; `atime` excluded, directory mtime included;
  `$TMPDIR`/`$HOME` redirected into the test's own tree and both snapshot roots), with
  six planted mutations as negative controls and a non-dry-run control that produces a
  non-empty diff so "zero differences" cannot mean "nothing ran".
- Added `tests/atomic_harness.py` (a subprocess driver, deliberately not a verb, routing
  errors through the product's own `emit_error` and `exit_code`) and seven test arms:
  a **real** `SIGKILL` delivered to a child provably parked at `after_temp_create`,
  `after_fsync` and `after_backup` leaves the original byte-identical for both a fresh
  target and `--in-place`; a real second filesystem (`/dev/shm`) proves the degradation
  warning and a genuine kernel `EXDEV`; the `-y` gate is exercised over a never-written
  stdin pipe under a hard timeout and over a real `pty`.
- `TESTING.md` gained a "Safety-spine test arms" section documenting
  `PDF_TOOLKIT_FAULT_POINT`, `PDF_TOOLKIT_FAULT_RENDEZVOUS`,
  `PDF_TOOLKIT_TEST_XDEV_DIR`, the second-filesystem ladder (which **fails** rather than
  skips on Linux) and the expected visible-skip count per configuration. No runtime
  dependency was added and no engine is touched — every arm writes plain bytes.

## [PDF-03] Page-range grammar & selection engine — 2026-08-29
- Added `src/pdf_toolkit/ops/pagerange.py`: the one module that owns the full `PLAN.md`
  §4.3 grammar (`N`, `A-B`, `B-A`, `N-`, `-N`, `first`/`last`, `even`/`odd`, `all`,
  `!TOKEN`, `,`) via a single left-to-right evaluator over a running list, one
  normalization switch at the end (ordered vs. sorted-deduplicated). `parse()`/`render()`
  are public and framework-free (stdlib + `pdf_toolkit.models`/`errors` only, no engine,
  no I/O); `GRAMMAR_HELP` is the one string PDF-07/PDF-08 will build their `--pages` help
  text from (G6). PLAN §12 R-04 closed: `-N` is negative indexing, with a dedicated
  `1-N` open-left hint on an unresolvable negative index.
- Added `PageRangeError(UsageError)` to `src/pdf_toolkit/errors.py` (`spec`/`token`/
  `column`/`reason`) and the `is_empty` property (never a field) to `PageRange` in
  `src/pdf_toolkit/models.py` — both edits additive-only, no other line touched.
- Added `tests/test_pagerange.py`: the §4.3 token table (10/10 rows) and error table
  (7/7 rows) as data with completeness meta-tests, the five named property invariants
  P1–P5 at 1000 hypothesis examples each (`-k property` selects exactly those five), the
  PLAN §12 R-04 hint cases, and the module's own import-boundary/no-I/O tests. 100%
  statement+branch coverage on the module.
- The grammar is deliberately **unwired**: no verb, no flag, no `cli/` file created or
  edited — `pdftoolkit --help` still lists only `version`. Wiring is PDF-07/PDF-08.

## [Task: PDF-16 — Project website (GitHub Pages), Phase A] - 2026-08-29
- Added `website/` (27 files — 24 hand-authored, plus generated `package-lock.json`,
  `public/og-image.png`, `src/data/licenses.json`): a zero-client-JS Astro 7 +
  Tailwind v4 landing page at `https://armandoherra.github.io/pdf-toolkit/`, rose accent,
  ten sections (Navbar, Hero, Features, Architecture, Verbs, QuickStart, ExitCodes,
  Licensing, TechStack, Footer), data-driven Verbs/Licensing/TechStack sections rendered
  from `src/data/licenses.json` (generated by `make licenses`, PDF-02 — no second
  generator script was written).
- Added `.github/workflows/deploy-website.yml`, byte-identical to the `apps/mediakit`
  donor, SHA-pinned Pages build+deploy on push to `website/**`.
- Appended the `npm:/website` ecosystem block to `.github/dependabot.yml` (created by
  PDF-02; `uv` + `github-actions` blocks left byte-identical).
- Appended two steps to `ci.yml`'s `license-gate` job: regenerate and diff
  `website/src/data/licenses.json` for drift (PLAN §12 R-15).
- One added line each in `README.md` (website link) and `CLAUDE.md` (website layout
  note); `Current phase:` untouched in both (Phase B's job).
- Phase B (re-deriving Verbs/ExitCodes content once more verbs ship, wave 8) remains
  open by design — this item is `In progress (Phase A landed)`, not `Implemented`.

## [PDF-02] CI, license gate & release skeleton — 2026-08-29
- Added `.github/workflows/ci.yml`: ten parallel jobs (`lint`, `typecheck`, `test` on
  {3.11,3.12,3.13,3.14}x{ubuntu-latest,macos-14}, `engines-present`, `without-engines`,
  `sast`, `vulncheck`, `secret-scan`, `license-gate`, `build`), every action SHA-pinned,
  workflow-level `contents: read` and no job above it.
- Added `scripts/licenses.py`: generates `THIRD_PARTY_LICENSES` from a dedicated
  `--no-dev --all-extras` Python 3.11 environment (never the ambient venv) and gates the
  distributed closure on `AGPL|GPL|LGPL`. MPL-2.0 passes by design (`pikepdf` bundles
  libqpdf, PLAN §12 R-11); `UNKNOWN` fails; the allowlist is present, commented and empty.
- Added `tests/test_license_policy.py`: an AST walk (never a text grep) over every file
  under `src/` for forbidden imports, `subprocess` argv[0] and `shutil.which` arguments,
  with permanent positive and negative self-tests proving `gs` inside an identifier does
  not false-positive, plus the `subprocess_util.py` spawn-chokepoint assertion.
- Added `.github/workflows/release.yml` (tag-gated, PyPI Trusted Publishing, **configured
  and never fired**), `.github/dependabot.yml` (`uv` + `github-actions`), and
  `scripts/assert_skips.py` / `scripts/assert_artifacts.py`.
- Rewired the `licenses` and `secret-scan` Makefile targets; `secret-scan` now hard-fails
  with an install hint instead of exiting 0 when `gitleaks` is absent.

## [PDF-01] Project scaffold & CLI spine — 2026-08-29
- Added `pyproject.toml` with the full PLAN §7.1 runtime dependency set and committed `uv.lock`.
- Added the `src/pdf_toolkit/` six-layer skeleton, the Typer root with all §4.2 global flags,
  `errors.py`/`exit_codes.py`, the table/JSON/NDJSON renderers, the redacting stderr logger,
  and `SafetyPolicy`.
- Added the placeholder `version` verb, the 18-target `Makefile`, six documentation skeletons,
  `changelog.md`, and `.scratch/` to `.gitignore`.
