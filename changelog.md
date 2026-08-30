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
## [PDF-11] text + tables — 2026-08-30
- Added `text` (pypdfium2 fast path; `--layout` via pdfplumber, one block per
  line with top-left-origin geometry) and `tables` (`--strategy lines|text`,
  `--format csv|json`), over one `TextEngine` port extended in place —
  `LayoutTextEngine` is a second Protocol in the same file, not a seventh port,
  so the licence claim still reads as six files. New frozen models `TextBlock`,
  `PageText`, `TableGrid`; new op layer `ops/textract.py`.
- Every result DECLARES the strategy and the engine that produced it, in
  `-o json`, on every `-o ndjson` line, and as a one-line banner in `-o table`
  (stdout when a destination was given, stderr when stdout is carrying the
  payload). `--layout` with the layout adapter unresolved exits **3** and never
  falls back. Table extraction is documented as a heuristic in `--help`, and no
  number claiming how sure the engine was is invented anywhere — enforced by a
  grep over the five source files and both goldens, not by review. A page that
  exists and yields nothing returns empty, exits **0** and warns; that is the
  before-state the later `ocr` verb's acceptance signal depends on.
- Block extraction uses pdfplumber's own `Page.extract_text_lines()` — present
  across the whole pinned `>=0.11.10,<0.12` range, so the spec's documented
  word-grouping fallback is deliberately NOT carried as unreachable code; its
  absence is reported as a coded exit-3 engine failure instead of an
  `AttributeError` traceback. Block ORDER is imposed by a stable sort on
  `(y, x)`, so `y` is non-decreasing on every page including rotated ones — a
  guarantee the tool makes rather than a property it hopes the engine has.
- Contract row `C15` found a real gap while this landed: `plan_output_set`
  deliberately skips the writability tier when there is no shared `--out-dir`,
  so a `-O` dry run predicted 0 where the real run exited 1. Closed by
  consulting BOTH shared primitives — the planner for the `--out-dir` tier and
  `AtomicWriter`'s own plan for the single-destination tier that `merge`,
  `compose` and `create` already predict through. No per-verb prediction logic
  and no per-verb exit-code logic was added; `--in-place` is refused by the OR-3
  declaration alone, and neither command module mentions it.
- Makefile: `make samples-gate` now encodes the `@samples` ordering ONCE
  (`decision.md` §8 X-115) — assert-no-stale-manifest, `samples-scratch`,
  the arm with the corpus present, the arm with it absent, `samples-check` —
  so no spec has to re-type the four steps that let B-046 propagate. Its
  unset arm asserts on junit COUNTS, failing on any pass and on zero collected
  tests, because an exit code cannot tell "all skipped" from "all passed".
  `make samples-scratch` now REFUSES over an existing manifest naming
  `make clean`, instead of silently overwriting the snapshot that
  `samples-check` compares against (X-108). `samples-gate` is deliberately not
  part of `make ci`: it needs the real-document corpus, which CI has not got.

## [B-055] widen the SIGTERM/SIGINT/SIGHUP teardown grace window and make its own test spawn-safe — 2026-08-30
- CI's `macos-14` leg (`test (3.13, macos-14)`) caught a real gap on the
  first push of the landed `[B-055]` entry below: stray `.pdftoolkit-*`
  temp files survived the run. `multiprocessing` defaults to `spawn` on
  macOS (and every platform from Python 3.14 on), so every worker
  cold-imports pypdfium2/Pillow/this package from scratch on start —
  `guarded_process_pool()`'s grace window widens from 2s to 6s in
  `ops/procpool.py` to give that cold start room to finish an in-flight
  `AtomicWriter` unwind before the SIGKILL deadline, instead of racing it.
- `tests/integration/test_rasterize_signals.py` sent its signal at the
  worst possible moment — the very first output file — which statistically
  catches other workers mid cold-import, uninterruptible C call included.
  Fixed by signalling once half the run's pages already exist instead, so
  the test's own timing no longer manufactures the race it was written to
  detect.
- The `guarded_process_pool()` docstring now states residue avoidance as
  best-effort under PLAN §12 R-07's own accepted class, not as a guarantee
  — the fix narrows the race, it does not eliminate the theoretical window
  inherent to signalling a cold-starting worker.

## [B-055] `rasterize`'s worker pool no longer survives SIGTERM/SIGINT/SIGHUP to the parent — 2026-08-30
- Fixed: `rasterize --threads N>1` left every render worker running (and
  writing) after a signal to the parent — `ProcessPoolExecutor.__exit__`'s
  `shutdown(wait=True)` blocks until already-running workers finish rather
  than signalling them, so a bare `shutdown()` in any combination was never
  a fix. Added `ops/procpool.py::guarded_process_pool()`, a drop-in
  `ProcessPoolExecutor` wrapper that actively SIGTERMs every known worker
  PID (via `executor._processes`, the only reachable handle), waits out a
  2s grace window for an in-flight `AtomicWriter` to unwind and discard its
  own temp file, then SIGKILLs stragglers and reaps them — before letting
  the parent die BY the signal (`SIG_DFL` + self-`kill`, `$?` = 128+signo,
  not `sys.exit`). `ProcessPoolExecutor` stays mandatory (X-104: real
  concurrent pdfium rendering corrupts the heap even with per-worker
  document isolation) — this is not a switch to threads.
- SIGTERM, SIGINT and SIGHUP all route through the one teardown routine.
  Measured directly: a bare `kill -INT <parent pid only>` on the unfixed
  code does NOT stop the job — "SIGINT is already clean" held only for an
  interactive Ctrl-C, which signals the whole foreground process group and
  kills workers by accident, not for a supervisor's single-process signal.
  SIGKILL to the parent remains uncatchable by definition; the one thing
  the child side can do about it, `PR_SET_PDEATHSIG(SIGKILL)` via `ctypes`
  in the worker initializer, is Linux-only and stated as such (no macOS
  coverage).
- The worker initializer also resets SIGINT/SIGHUP to `SIG_DFL` and
  installs a worker-local SIGTERM handler, closing the `fork`-inheritance
  hazard commit `26f4c79` already paid for once: a forked worker must never
  run the PARENT's own pool-shaped teardown handler.
- Added `tests/integration/test_rasterize_signals.py` — black-box, real
  `subprocess.Popen`/`os.kill` (parent PID only, never the group), proven
  start-method agnostic by construction (never touches multiprocessing
  internals) and seen RED on the unfixed code before being made GREEN.
  Added `tests/unit/test_procpool.py` for the underlying mechanics. R-08
  byte-identity (`--threads 1` vs `--threads 8`, sha256) re-verified after
  the change.

## [B-054] `--dry-run` predicts the filesystem-tier refusal for `--out-dir` verbs — 2026-08-30
- Fixed `split`/`rasterize`: `--dry-run` over an occupied `--out-dir` target,
  or over an unwritable `--out-dir`, now predicts the same exit code the real
  run produces (5 / 1) with a character-identical `would_refuse` payload,
  instead of entering cleanly and exiting 0 (QA `b43bb70cc3`).
- Added `safety/atomic.py::plan_output_set()` — the X-67 filesystem-tier
  planner, extended from one destination to a multi-target `--out-dir` run,
  run once, unconditionally, in both modes. `ensure_out_dir` is now private
  (`_ensure_out_dir`) and `plan_output_set` is its only caller, so a future
  `--out-dir` verb cannot reach the write chokepoint without also getting the
  prediction. `split`/`rasterize` each call it once, at the position their
  own real-run filesystem checks used to occupy.
- Added contract-harness arm `C15` (`tests/test_cli_contract.py`), driven off
  a widened structural "producing" derivation (`--output` OR `--out-dir`)
  that C11's own set is now read off, and generic target discovery via each
  verb's own `--dry-run -o json` plan rather than a per-verb table — so a
  future producing verb is covered the day it registers, with zero action
  from its author.
- Added focused unit coverage for `plan_output_set` (clean plan, occupied
  target, unwritable directory, and the non-existent-`--out-dir` case) in
  `tests/unit/test_atomic_writer.py`.

## [PDF-10] compose + create — 2026-08-30
- Added `src/pdf_toolkit/ops/compose.py` (framework-free ops for BOTH verbs) +
  `cli/cmd_compose.py` and `cli/cmd_create.py`. `compose` builds a PDF from
  images, one page per operand in argv order (duplicates allowed, no sorting,
  no globbing — a directory operand is exit 2 naming the shell as the fix);
  `create` renders one plain-text input, including `-` for standard input.
  Both declare `consumes=("--output",)` (OR-3), so `--out-dir`, `--name` and
  `--in-place` exit 2 **for free** from the shared option layer — neither
  command module contains a check for any of them, and neither names them.
  One operand with no explicit destination writes beside the input; two or
  more is exit 2 rather than a guess.
- **The lossless guarantee, asserted byte-for-byte rather than visually.** A
  baseline JPEG is stored as its own compressed bytes under a `/DCTDecode`
  filter with no decode and no re-encode; the chain is pinned to exactly
  `("/DCTDecode",)` by disabling reportlab's ASCII85 transport layer inside a
  save/restore context manager that spans every `drawImage` call (the toggle
  is read there, not at canvas construction) and restores on the exception
  path. Greyscale, RGB **and** CMYK pass through — reportlab emits the Adobe
  `/Decode [1 0 1 0 1 0 1 0]` inversion array, so the page renders correctly
  AND the bytes survive. A **progressive** JPEG is diverted to Flate with a
  per-file warning; the op sniffs the SOF marker itself, because the renderer
  sniffs nothing and would otherwise pass everything through silently.
- **Defect found on the 108-scan real-document corpus and fixed here:**
  `drawImage` de-duplicates image XObjects by a digest computed from the
  DECODED PIXELS when handed an `ImageReader`, so two inputs with identical
  pixels but different compressed bytes collapsed onto one XObject and the
  second page silently rendered the first file's bytes — with the filter chain
  still reading `/DCTDecode` and the item still claiming a passthrough.
  Handing the path itself to `drawImage` keys the cache on the filename;
  a repeated operand still, correctly, shares one XObject. Regression test
  reproduces it without the corpus and was proven to go red without the fix.
- `src/pdf_toolkit/ports/compose.py` gains `ComposeEngine.compose_images()` and
  `.render_text()` plus the `ImagePlacement`/`TextLayout`/`ComposeReport`
  carriers; both render into a **caller-supplied binary stream**, never a path,
  so every byte still reaches disk through `safety.AtomicWriter` and
  `tests/test_import_boundaries.py` stays green unedited. Geometry is placement
  — a CTM scale and a PDF clip path — never a pixel operation, so byte
  identity survives `--fit cover`.
- `src/pdf_toolkit/models.py` gains **one** optional field, `ItemResult.detail`
  (last, defaulted `None`, omitted from `to_dict()` when `None`) — the
  cycle-wide per-item-facts seam. `SCHEMA_VERSION` is unchanged and PDF-06's
  `info`/`doctor` goldens pass byte-identical, which is the proof the change is
  additive rather than a claim that it is. `compose` reports `embed`,
  `stream_bytes_identical`, `source_format`, `dpi_source` and `page` through it.

## [PDF-09] rasterize — PDF pages to images — 2026-08-30
- Added `src/pdf_toolkit/ops/raster.py` + `cli/cmd_rasterize.py`: `rasterize`
  renders every selected page of one or more PDFs to PNG/JPEG/TIFF/WEBP,
  `--dpi`/`--width` (mutually exclusive), `--quality` (lossy formats only),
  `--grayscale`, `--pages` (a **set** — PLAN §4.3, the product's first
  `--pages` verb). `consumes=("--out-dir", "--name")` (Design §D10) —
  `-O/--output` and `--in-place` exit 2 **for free** from the shared option
  layer; `cmd_rasterize.py` contains no check for either flag (AC23).
  Default `--name` template `{stem}-{page:04}.{ext}`.
- `src/pdf_toolkit/ports/raster.py` gains `RasterEngine.render_page()` and
  the `RenderedPage` carrier (in-memory pixels only — encoding/naming/write
  stay outside the port, D2), the interface PDF-15's `ocr` will reuse.
  `src/pdf_toolkit/adapters/pdfium_raster.py` fills in the render path PDF-05
  left probe-and-version-only: per-page open/render/close, rotation honoured
  via the page's own declared `/Rotate`, and a round()-vs-pdfium's-own-ceil()
  pixel-dimension correction (pypdfium2's `math.ceil(page_pt * scale)` can
  overshoot by one pixel on a scale like `300/72` that isn't exactly
  representable as an IEEE double — confirmed live, corrected by cropping
  down to the independently-computed exact target, never padding).
- **PLAN §12 R-08's per-worker-document-handle requirement, live-tested and
  the executor swapped as a result.** `_render_chunk` is a module-level,
  picklable-argument worker (proven by driving it through both a
  `ThreadPoolExecutor` and a `ProcessPoolExecutor` in the test suite).
  Live-testing found that real concurrent multi-threaded pdfium rendering —
  even with each thread opening and closing its own separate document,
  exactly as designed — reliably corrupts the process heap (`free(): invalid
  pointer`, `malloc(): unaligned tcache chunk detected`, `double free or
  corruption`, reproduced with 2 and with 8 concurrent threads on pypdfium2
  5.13.0). Production therefore dispatches `_render_chunk` through a
  `ProcessPoolExecutor`, not a `ThreadPoolExecutor` — a deviation from the
  spec's literal prose, in the direction the evidence pointed. `--threads 1`
  and `--threads 8` are proven byte-identical, same file order, over both a
  local 8-page fixture and a real 108-page scanned sample.
- Registered the sixth verb: the CLI-contract `C14` matrix moves 20→24
  automatically; `tests/unit/test_registry.py`'s three pins fire as designed
  (six-verb set, `rasterize` added to the mutating set — classified through
  the **existing** `_MAX_IMPORT_HOPS = 4`, never raised — and a new explicit
  page-addressing set) and are updated, never deleted.
- Added `tests/unit/test_raster.py` (ops/ports/adapter, in-process) and
  `tests/integration/test_rasterize_cli.py` (subprocess, flag contract,
  OR-3). Appended one `@pytest.mark.samples` section to `tests/test_samples.py`
  over a copy of `1888-10.pdf` (AC20): page 1 at `--dpi 72` renders the exact
  956×1435 px the sample's own point geometry predicts, and the thread-count
  identity proof re-run at `--pages 1-12` over the real scan.
- **Reported to the PM, not reconciled here (the spec is the carrier, not
  this commit):** AC9's "`--grayscale` reads back mode `L` for webp too" is
  physically unsatisfiable — WebP's own bitstream format has no
  single-channel pixel mode at all (Pillow 12.3.0's WebP encoder
  unconditionally converts any non-RGB(A/X) source to RGB before handing it
  to libwebp); the produced file is still perceptually grayscale (R≈G≈B
  throughout), which is what the test asserts instead. My own help text
  mentioning "Ghostscript" (prose, matching the spec's own D8 wording)
  tripped `tests/test_cli_spine.py`'s literal, case-insensitive,
  whole-source-tree forbidden-name scan — reworded to name no forbidden tool
  at all, even in prose.

## [PDF-07] merge + split — the OR-3 output-flag consumption mechanism — 2026-08-30
- **OR-3 (`decision.md` §0.5, Design §D12), built here before either verb
  existed.** `cli/common.py` gains `OUTPUT_FLAGS` (`--output`, `--out-dir`,
  `--name`, `--in-place`) and turns `global_options` into a decorator
  **factory** taking a required `consumes=` keyword; a bare `@global_options`
  now raises `TypeError` at import time, and an unknown flag name raises
  `ValueError` — both at import time, never at runtime. The central check
  (`_check_output_flag_consumption`) runs once, inside `validate_config()`, in
  a pinned order: `--output`/`--out-dir` mutual exclusion, then OR-3, then the
  existing shape checks. `version`/`doctor`/`info` are retrofitted to declare
  `consumes=()` — the proof the mechanism actually refuses. Closes **B-035**
  (QA fingerprint `54500b06e5`).
- Added `src/pdf_toolkit/ops/merge.py` and `cli/cmd_merge.py`: `merge`
  concatenates PDFs with per-input `path:range` selection (last-colon
  disambiguation, `:all` escape), `--bookmarks per-file|preserve|none`,
  fail-closed on any input (all inputs opened and resolved before the first
  byte is written), `consumes=("--output",)`.
- Added `src/pdf_toolkit/ops/split.py` and `cli/cmd_split.py`: `split` splits
  one PDF into many by `--every`, `--ranges` (comma is the part separator,
  not a union), `--each-page` or `--at-bookmarks` (including the documented
  no-outline-at-all case, exit 4), `--name` templating into `--out-dir`,
  plan-then-write (all parts resolved and no-clobber/collision-checked before
  the first write), `consumes=("--out-dir", "--name")`.
- Added `src/pdf_toolkit/safety/naming.py`: the `--name` template renderer
  (X-70 resolves Design §D6's branch — PDF-04 shipped only
  `ensure_within()`, no renderer, so this module is new, not consumed).
  Token substitution plus the binding containment invariant; calls
  `ensure_within()` on every rendered path before it ever reaches
  `AtomicWriter`. Owns only the substituted-value/255-byte exit-5 tier;
  `cli/common.py::_validate_name_template`'s exit-2 tier is untouched.
- `src/pdf_toolkit/safety/atomic.py`: added `AtomicWriter.stream` (the open
  file handle, never a path — D7's fix for `pypdf.PdfWriter.write(path)`
  opening its own handle and bypassing the tracked one) and `ensure_out_dir()`
  (the one confined `Path.mkdir` call site for `--out-dir`, gated on
  `--dry-run`, chokepoint-confined per the existing AST-walk boundary).
- `src/pdf_toolkit/safety/paths.py`: added `target_exists()`, a boolean
  existence predicate (dangling-symlink-aware) for the bulk-destructive
  confirmation gate to consult before deciding whether a run is destructive.
- `src/pdf_toolkit/ports/structure.py` + `adapters/pypdf_structure.py`: D10's
  minimal method set — `open_document()`/`OpenStructureDocument`
  (context-managed, page count, top-level outline as 1-based
  `(title, page)` pairs) and `new_writer()`/`StructureWriter`
  (`append_pages`, `add_outline_entry`, `import_outline`, `write`). No new
  adapter, no second engine.
- `src/pdf_toolkit/ops/pagerange.py`: added `is_valid_spec()` (syntax-only,
  no bounds check, no materialization — reuses the existing regex/keyword
  constants) and `ALL_PAGES_TOKEN`. **Neither is added to `__all__`** —
  `tests/test_pagerange.py::test_ac1_public_surface` pins that list exactly
  and that file is unedited (AC6/HC-3); both stay directly importable.
- `tests/registry.py` (PDF-06's, edited under the ruling's own
  authorization): `VerbSpec` gained `consumes`; `merge`/`split` rows added to
  `INVOCATIONS`; added `OUTPUT_FLAG_INVOCATIONS` for the three OR-3-honoured
  pairs.
- `tests/test_cli_contract.py` (PDF-06's): added `C14`, the OR-3 matrix arm —
  `discover_verbs()` × `OUTPUT_FLAGS`, no skip list — 5×4=20 cases at
  landing, 3 honoured / 17 exit-2. `C11` re-parameterized off the live
  `consumes` declaration instead of a hard-coded `-O` (`OUTPUT_CONSUMING_
  MUTATING`), so it no longer drives `-O` at `split`.
- `tests/unit/test_registry.py`: the two pins the tripwire hit (B-031, E12)
  updated to the explicit expected set, never deleted —
  `test_discover_verbs_finds_exactly_the_five_landed_verbs` and
  `test_the_expected_verbs_are_classified_mutating_or_not`
  (`merge`/`split` classify `is_mutating=True` through the **existing**
  `_MAX_IMPORT_HOPS = 4` scan; the bound was never raised).
- `tests/test_cli_spine.py`: the two E13-vacuous cases repaired, not
  deleted — the `-O`/`--out-dir` row now has a dedicated message assertion
  proving the mutual-exclusion ordering rule; the `--name` row is re-pointed
  at `split` (which declares `--name`) with a dedicated template-shape
  message assertion.
- Added `tests/unit/test_merge.py`, `tests/unit/test_split.py`,
  `tests/unit/test_name_template.py` (hypothesis, 1000 examples),
  `tests/unit/test_output_flags.py` (AC26), `tests/unit/test_verb_help_
  content.py` (AC23), `tests/integration/test_split_merge_roundtrip.py`
  (AC1, in-process and subprocess), `tests/integration/test_split_merge_
  atomicity.py` (AC17/AC20), `tests/integration/test_split_merge_cli.py`
  (AC9/AC18/AC19/AC21/AC30), `tests/pdfium_text.py` (the pypdfium2 per-page
  text helper AC1/AC4/AC5/AC15 share). Appended PDF-07's `@samples` section
  to `tests/test_samples.py` (AC22, over a copy of `PrendiniLoria2020.pdf`).

## [B-034] `make ci` was locally unrunnable under coverage instrumentation — 2026-08-30
- **Measurement (identical band both arms, `tests/test_info.py` +
  `tests/test_doctor.py` + `tests/test_cli_contract.py`, 84 tests):**
  14.49s uninstrumented vs **544.59s** instrumented under the pre-existing
  `[tool.coverage.run]` config (`branch = true`, default core) — a 37.6x
  penalty, consistent with the qa-sentinel's earlier 57x control on
  `tests/test_info.py` alone. A single isolated `info` subprocess call
  (real PDF parse) measured 0.245s uninstrumented vs **15.8s** instrumented
  (~65x) — `version`/`doctor` calls, which never reach the parser, stayed
  near baseline (~2.6x for 10 calls). CI is unaffected: the same suite ran
  in ~86s on Python 3.13 in the `engines-present` job (run `33287428715`).
- **Diagnosis, attributed by direct measurement, not assumed:** the cost is
  coverage.py's classic ctrace tracer applied to `adapters/pypdf_structure.py`
  — the primary `StructureEngine`, a pure-Python PDF parser reached by every
  `info` call. `branch = true` blocks `sys.monitoring` (`COVERAGE_CORE=sysmon`)
  from engaging at all (`Can't use core=sysmon: sys.monitoring can't measure
  branches in this version`), forcing ctrace, and ctrace on pure-Python
  parsing code is what is catastrophically slow — not a fixed per-subprocess
  startup tax (ruled out: `version`/`doctor` pay the same startup and stay
  fast) and not the `.coverage.*` combine step (ruled out: the single-call
  isolation reproduces the full multiplier with zero combine involved).
  Turning off branch tracking alone did **not** help (15.8s, unchanged) —
  the fix is specifically `core = "sysmon"` becoming reachable once branch
  tracking is off: same single call measured 0.34s (~46x faster), same
  84-test band measured 21.51s end-to-end (~25x faster).
- **Fix, config-only:** `[tool.coverage.run]` in `pyproject.toml` — `branch =
  true` → `branch = false` + `core = "sysmon"`. No Makefile or CI workflow
  changes needed: pytest-cov's parent-process measurement and the
  `patch = ["subprocess"]` child measurement both read the same
  `pyproject.toml` section, so local and CI apply the identical config with
  zero divergence. `--cov-fail-under=85` is unchanged; `patch`/`parallel`
  (subprocess measurement) are untouched — the floor for subprocess-executed
  code stays exactly as honest as `d777dd8` left it.
- **What the floor now means:** this is line coverage, not branch coverage —
  a weaker property (a line inside a branch counts as covered the moment
  either arm executes once) that reads higher for the same code. The
  84-test band alone moved from 66.24% (branch) to 71.49% (line) under
  identical tests. Re-enabling branch coverage is a legitimate follow-up
  once coverage.py/CPython ship a version combination where `sys.monitoring`
  supports branch measurement.
- **End-to-end result:** `make cover` (full 490-test suite, instrumented):
  93.79% line coverage (>= the unchanged 85% floor) in **76.67s**, down from
  a PM-observed baseline of ~571s. `make ci` (fmt-check, lint, typecheck,
  cover, licenses, sast, vulncheck): green, **80s** total wall clock, well
  under the ~5 minute target from OR-5. Only `pyproject.toml` changed —
  `make licenses`'s regenerate step is a no-op diff since no dependency
  moved.

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
