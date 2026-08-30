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
## [PDF-04] Ruling X-67 fix-forward: `--dry-run` now runs the plan and predicts the refusal — 2026-08-29
- **The preview lied.** The dry-run gate was the first statement of
  `AtomicWriter.__enter__`, so `_plan()` never ran under `--dry-run` and a dry
  run could not predict any of the three conditions this module owns. Against an
  occupied target a `--dry-run` entered cleanly and reported
  `{"target": ..., "dry_run": true, "written": false}` — while the real run
  refused with `TargetExistsError`, exit **5**. Same for
  `DestinationUnwritableError` (exit **1**) and the cross-filesystem `atomicity
  degraded` warning, which was unreachable under `--dry-run` entirely. Ruling
  X-67 settled this during the cycle and was never carried into the PDF-04 spec,
  so the original implementation was a faithful build of an incomplete spec.
- **The gate moved to immediately above `_open_temp()`** — the first genuinely
  mutating call — so `_plan()` now runs in *both* modes. Under `--dry-run` its
  refusals are **computed and captured** rather than raised: `planned_refusal`
  holds the exception the real run would have thrown, `would_exit` is the status
  it would have exited with, and `plan_item()` renders both as one item whose
  `would_refuse` is the *identical* payload the real run prints under `-o json`.
  Capture stops at the first refusal, exactly where a real run would have
  stopped. The dry run itself still exits **0**; mirroring the predicted status
  into the dry run's own exit code is filed as **B-025**, not implemented here.
- **Real-run behaviour is unchanged** — same classes, codes, messages and
  ordering — and a test asserts a real run raises and captures nothing, so the
  capture path cannot quietly become the raise path. No runtime dependency, no
  `SCHEMA_VERSION` change, and no `ItemResult.detail`: X-26 approved that seam as
  a convention but PDF-10 has not landed and no verb consumes `AtomicWriter`, so
  the writer carries the fact and `tests/atomic_harness.py` is the machine-
  readable surface. (`EngineReport.detail` is PDF-05's unrelated `str` field.)
- **`--dry-run` purity is unchanged and now means something.** `_plan()` calls
  only `ensure_no_clobber`, `ensure_destination_writable` and
  `_warn_if_destination_moved`, which between them use `resolve()`, `.exists()`,
  `os.path.lexists()`, `.is_dir()`, `os.access` and two device stats — reads,
  every one. `assert_pure()` still reports zero differences, and two new arms
  assert it over a dry run that *does* capture a refusal (the pre-existing arm
  used `--in-place`, which suppresses no-clobber by definition and so never
  exercised the capture path at all).
- 16 tests added across `tests/unit/test_atomic_writer.py`,
  `tests/integration/test_purity_primitive.py` and
  `tests/integration/test_cross_filesystem.py`; the regression arms assert the
  prediction against a *second, real* process rather than against a hand-written
  expectation. `test_the_gate_fires_even_when_the_run_would_have_been_refused`
  was rewritten (not deleted): its "a dry run never reaches a filesystem check at
  all" docstring was the superseded contract, while its assertions still hold.


## [PDF-06] Coverage floor fix-forward: subprocess-executed CLI code was unmeasured — 2026-08-29
- `[tool.coverage.run]` gained `patch = ["subprocess"]` and `parallel = true`.
  The suite drives the CLI exclusively through `subprocess.run`
  (`tests/registry.py`, `tests/test_doctor.py`, `tests/test_info.py`,
  `tests/test_cli_spine.py`); without subprocess patching, coverage.py
  measured the parent pytest process only, and the landing commit's reported
  **71.29%** was a measurement artifact, not a real gap. Every subprocess
  call site already inherits the parent's full environment by default
  (`env=None`), so `COVERAGE_PROCESS_CONFIG` (set by the patch) reaches every
  child with no test-helper changes; `tests/unit/test_subprocess_util.py`'s
  deliberately scrubbed `env=` (testing `subprocess_util`'s own env
  handling, not the CLI) is the one exception, left untouched on purpose.
- `Makefile`'s `cover` target pins `COVERAGE_FILE` to an absolute path so a
  subprocess-measured child's parallel data file always lands next to the
  parent's in the repo root, never inside a purity-snapshot root (several
  tests spawn the CLI with `cwd` set to a temp directory). `clean` now also
  removes `.coverage.*`; `.gitignore` gained the same pattern.
- `tests/test_cli_spine.py::test_help_stays_within_the_startup_budget` now
  runs its five `--help` timings with `COVERAGE_PROCESS_START`/
  `COVERAGE_PROCESS_CONFIG` stripped from the child's environment — R-13's
  250 ms budget is a claim about the product's real startup latency, not
  about how the suite happens to be instrumented, and coverage.py's own
  tracer overhead (worse under `branch = true`) pushed the unpatched
  measurement past the budget. `run_cli()` gained an optional `env=`
  parameter (default `None`, so every other call site's inheritance is
  unchanged).
- Re-measured total: **91.29%, engines present — the floor is met**
  (`cli/cmd_doctor.py` 32%→94%, `cli/cmd_info.py` 26%→94%, `ops/inspect.py`
  30%→90%, `output/json.py` 43%→90%, `cli/main.py` 70%→100%, `__main__.py`
  0%→83%). `fail_under` stays 85; no `omit` of anything under
  `src/pdf_toolkit/` was added, then or now.
- `.github/workflows/ci.yml`'s `engines-present` job now also enforces
  `--cov-fail-under=85` (conditionally authorized only because the floor
  genuinely passes there — `decision.md` X-85); `without-engines` is
  deliberately not gated on it, matching Design §6's engines-present-only
  coverage allowance.
- `TESTING.md`'s coverage-floor section rewritten to report the true,
  current state. The original PDF-06 entry below is left untouched per this
  file's own rule 3 — this is a new entry, not a correction of that one.

## [PDF-06] Fixture corpus, CLI contract harness & real-sample guard — 2026-08-29
- Added `tests/corpus.py`: seven deterministic reportlab-generated fixtures
  (`multipage_text`, `rotated`, `jpeg_page`, `encrypted_aes256`,
  `metadata_rich`, `single_page`, `tabular`), built once per session into
  pytest's own scratch directory. Six are byte-identical across two
  independent builds; `encrypted_aes256` is exempt by construction (a fresh
  AES-256 salt every build) and is instead proven semantically —
  `tests/test_corpus.py`.
- Added `testdata/malformed.pdf` (439 B, xref/trailer destroyed, body
  objects intact, `info` exits 1, pikepdf recovers with 5 warnings) and
  `testdata/scanned-page.png` (synthesized, tesseract-recoverable) — the only
  two committed binaries, each earning its place per `testdata/README.md`.
- Added `tests/registry.py`: `discover_verbs()` walks the live Typer tree
  with no skip list, no filter, no hard-coded verb name; the
  `INVOCATIONS` registration contract; and a `reaches_atomic_writer()` scan
  that stands in for the Design-literal `is_mutating` predicate, which is
  unsatisfiable in this codebase because the global flag block attaches
  `-O`/`--out-dir`/`--in-place` to every verb uniformly (see the module's own
  docstring for the full account, and this spec's Implementation Log).
- Added `tests/test_cli_contract.py`: the thirteen-check per-verb matrix
  (`--help`, exit codes, dry-run purity, no-clobber, JSON-on-a-pipe, bulk
  non-TTY posture), parameterized over `discover_verbs()`, plus the AC10
  anti-lapse guard (`test_every_verb_is_registered`, with an automated
  monkeypatch proof that it fires).
- Added `tests/conftest.py`: the session-scoped `corpus` and `golden`
  fixtures, the `requires(engine)` marker resolving through
  `ports.resolve()`, the PATH-shadowing engines-hiding shim
  (`PDF_TOOLKIT_TEST_HIDE_ENGINES`, never touching a system binary), the
  working-tree guard (tracked files only, controller-only under `-n auto`),
  and the `samples` fixture.
- Added `tests/samples_guard.py`: the `PLAN.md` §10.1 rule 3
  originals-integrity guard as an independently-loadable pytest plugin —
  session-start manifest, session-end re-hash, fails the session naming the
  file, controller-only (`if hasattr(config, "workerinput")`). Proven against
  a **synthetic** samples directory, never the operator's real corpus
  (ruling X-25), including a proof that it runs exactly once under `-n 2`
  (`tests/integration/test_samples_guard_fires.py`).
- Added `tests/test_samples.py` (the append-only home for `PDF-07`…`PDF-15`'s
  `@samples` arms) and `tests/golden/` (empty at landing; the primitive is
  self-tested in `tests/unit/test_golden.py` entirely inside a scratch
  directory).
- Appended Section 3 to `tests/test_import_boundaries.py`: no `typer`/`click`
  import below `cli/` (`PLAN.md` §10, D-03), inheriting PDF-04's AST-walk
  machinery per `decision.md` X-6.
- `Makefile`: added `samples-scratch` / `samples-check`; `clean` now removes
  `.scratch/`; `ci` now runs `cover` instead of `test` (X-22) — the coverage
  floor is real on the local gate for the first time. **At this commit,
  coverage measures 71.29%, not the 85% floor** — a genuine, disclosed,
  out-of-scope gap (adapter internals for verbs that do not exist yet);
  `ci.yml`'s `engines-present` job is deliberately **not** wired to enforce
  the floor in this commit, to avoid shipping a red CI run over a gap PDF-06
  cannot close. See `TESTING.md`'s closing section and this spec's
  Implementation Log.
- `pyproject.toml`: `[tool.pytest.ini_options]` gained `addopts =
  "--strict-markers -ra"` and the `samples` / `requires(engine)` markers.
  `[tool.coverage.*]` untouched — already correct.
- `scripts/assert_skips.py`: the `without-engines` count is no longer
  vacuous (at least 7 engine-gated skips now exist) — its docstring and its
  own zero-count branch were updated to treat a future zero as a
  **regression**, not vacuity, per the fleet's own "make the unverifiable
  case FAIL, not SKIP" lesson.
- `tests/test_cli_spine.py`: `MAKEFILE_TARGETS` gained `samples-scratch` /
  `samples-check` (disclosed necessary edit, X-54 class — the Makefile-target
  consistency test would otherwise turn red on PDF-06's own Makefile change).

## [PDF-05] Engine ports, adapters, doctor & info — 2026-08-29
- Added `src/pdf_toolkit/ports/`: six `typing.Protocol` port modules
  (`StructureEngine`, `RasterEngine`, `ComposeEngine`, `TextEngine`, `OcrEngine`,
  `OfficeConverter`) behind a memoized `resolve()`/`resolve_all()`/`reset_cache()`
  registry, plus `require(port, capability=...)` as the **single** exit-3 chokepoint —
  every message carries the OS-aware install hint and names `pdftoolkit doctor`
  (`PLAN.md` §12 R-09). Adapter selection is **by capability, never by name**: `info`
  asks for `linearized` and gets the pikepdf-backed adapter without naming it, and
  `repair`/`linearize`/`object-streams` already resolve through the same seam.
- Added `src/pdf_toolkit/adapters/`: eight engine adapters over seven backends
  (`pypdf`/`pikepdf` structure, `pdfium` raster + text fast path, `pdfplumber` text,
  `reportlab` compose, `tesseract` OCR, `soffice` office) — probe and version
  reporting only, every engine import function-local, wheel presence read via
  `find_spec` + distribution metadata rather than by importing the library.
  `weasyprint_compose.py` is deliberately not created; `doctor` prints six rows, never
  seven, and a secondary is named in its port's `detail`.
- Added `adapters/subprocess_util.py`, **the product's only process-spawn point**:
  `timeout` is a required keyword with no default, `start_new_session=True`, and a
  process-**GROUP** kill (SIGTERM → 2 s grace → SIGKILL) on timeout *and* on every
  other exit path. `tests/unit/test_subprocess_util.py` proves it against a real
  forked grandchild via `os.killpg(pgid, 0)` → `ProcessLookupError`, corroborated by
  a pgid-scoped `pgrep -g`. This is the mediakit MHC-50 lesson (163 orphaned daemons,
  ~6.5 GiB RSS) applied before the first external binary ships.
- Added `doctor` / `doctor --strict` and `info`. `doctor` renders exactly six rows in
  a pinned order whatever the host looks like, exits 0 with engines missing and 3
  under `--strict`, and reports stray `.pdftoolkit-*` residue via PDF-04's
  `find_stray_temps()` — report, never sweep, and never a change to the exit code.
  `info` reports page count, sizes, encryption state and algorithm, permission
  tokens, PDF version, metadata, signature/form presence, linearization, `--fonts`
  and `--pages-detail`; it **writes nothing**, proven by a before/after whole-tree
  filesystem snapshot on both the plain and `--dry-run` paths. Exit codes pinned one
  test per row: 0 / 1 malformed / 2 unknown flag / 2 directory / 4 missing / 6 locked,
  with a batch collapsing to 1 per `PLAN.md` §5.4. `models.py` gained `PageInfo`,
  `DocumentInfo` and `EngineReport` at their reserved anchors; `errors.py` needed no
  change — `EngineMissingError`, `AuthError`, `NoInputError`, `UsageError` and
  `FailureError` already carried every code this spec needs.
- Added Section 2 to `tests/test_import_boundaries.py` (appended beside PDF-04's
  Section 1): no engine library imported outside `adapters/`, no spawn surface
  (`subprocess`, `pty`, `os.exec*`/`spawn*`/`system`) outside `subprocess_util.py`,
  and every `subprocess_util.run()` call site proven to pass a statically resolvable
  `argv[0]` that is not a forbidden binary — fourteen planted violations prove each
  guard fires, and a negative control proves engine names in docstrings and
  parameters are not flagged. **`tests/test_license_policy.py` was amended**: its
  non-literal-`argv[0]` refusal applied to the chokepoint file too, which a generic
  spawn wrapper cannot satisfy by construction, so the refusal moved inside the
  `is_chokepoint` branch and the compensating call-site check landed in Section 2.
  Pillow's exclusion from the engine list is recorded with its reason so a later
  spec cannot quietly weaken the walk to make room for it.

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
