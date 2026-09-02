"""`PDF-09`'s 28 acceptance criteria — `AUDIT-CONVENTION(PDF-17)`, produced by `PDF-21`.

`PDF-09` is `rasterize`: the product's only multi-process verb, its only image
encoder, and the one whose `Verified` the `qa-sentinel` **withdrew on its own
motion** — because `AC8`'s single covering test passed *because of* the defect it
existed to catch (`Canvas.setPageRotation(90)` pre-swaps the MediaBox, so
`width > height` was evidence FOR the bug). The withdrawal's stated reason is the
premise of this module: *"every other criterion was granted in that same pass by
that same method."* This is the evidence for the re-grant or the refusal. The
`qa-sentinel` decides; this module does not.

**28 ROWS, 27 CRITERIA RE-DERIVED. Both numbers are correct and they do not
conflict.** `PDF-09` has 28 criteria and `test_the_ac_roster_is_contiguous`
requires a row for every one of them, *"including the ones that pass trivially"*.
`AC8` is therefore present as the 28th row — but as an explicitly labelled
**REGRESSION-ONLY** row: it was already independently re-verified at `971d0e5`
with its own control measured red, and this audit did **not** re-drive it. The
27 criteria this audit re-derived are `AC1-AC7` and `AC9-AC28`.

**FOUR-BUCKET CLASSIFICATION (X-242) — 19 `ADVANCES` · 1 `MADE-TRUE-HERE` ·
6 `SUPERSEDED` · 1 `FINDING` = 27.**

`ACAudit` has no `verdict` field and `_model.py` is frozen, so the vocabulary is
carried in the module docstring and in each row's `red` prose — the declared
deviation `audit_pdf_04.py` established and `audit_pdf_05.py` reused, rather than
a new field (Design §9.2 / R2). Every `red` below opens with its bucket in caps.

* **`ADVANCES`** — MET at the audited HEAD (`b20a651`) **and** newly grounded in a
  control this audit drove RED, with the mutation, the observed failure text and
  the revert recorded. `AC1`, `AC2`, `AC3`, `AC4`, `AC5`, `AC10`, `AC11`, `AC12`,
  `AC13`, `AC14`, `AC15`, `AC16`, `AC17`, `AC19`, `AC20`, `AC23`, `AC25`, `AC26`,
  `AC28` — nineteen.
* **`MADE-TRUE-HERE`** — not met at `b20a651`; true only because of this spec's own
  `src/` edits, so X-215(ii) fires and it cannot ground a re-grant. `AC18` — one.
* **`SUPERSEDED`** — the criterion's words are not re-derivable and a successor
  property is stated (X-215(iv)); permitted only on `PDF-21` §D3.2's closed list.
  `AC7`, `AC9`, `AC21`, `AC22`, `AC24`, `AC27` — six.
* **`FINDING`** — a clause of the criterion is measured by nothing, and this audit
  did not build the missing control. `AC6` — one.

**Bucket precedence.** `PDF-21`'s dispatch brief ruled a deterministic order
(SUPERSEDED, then MADE-TRUE-HERE, then FINDING, then ADVANCES) because several
criteria genuinely qualify for two. It is applied here and reported upward for
ratification. **Filing a finding is orthogonal to the bucket and is mandatory
whenever a control could not fail**, so nothing is laundered by the ordering; and
because every non-`ADVANCES` bucket refuses the re-grant on its own, no ordering
choice changes the outcome.

**Every mutation ran in a scratch `git worktree` under `$TMPDIR`
(`.../pdf21-mut`), never in `apps/pdf-toolkit` (HC-4 — `git stash` is never
used).** Restoration is structural: each mutated file is copied back from an
immutable GOLD tree snapshotted before the first mutation and then verified by
sha256. X-210's hazard was defended on **every** arm: (1) `pdf_toolkit.__file__`
was asserted to start with the scratch path before any red was trusted; (2) the
mutation was proven present in the scratch file before its arm ran, and an absent
mutation ABORTS the arm rather than reporting a green as a red; (3)
`PYTHONDONTWRITEBYTECODE=1`, so no stale `.pyc` can render a traceback against the
original source; (4) restoration is sha256-verified per arm. **34 mutation arms,
34 restorations, 0 mismatches at the end.** The harness's own gold-reference gap
was caught by that sha256 check mid-run (`safety/paths.py` was outside the first
gold set), and the whole affected batch was re-run from a verified-clean scratch
rather than accepted.

**Three criteria are defended IN DEPTH, and single-point mutations could not red
them** — recorded because it is a property of the product worth knowing, not a
harness failure: `AC12`'s no-clobber row needed BOTH `safety/paths.py`'s
pre-flight and `AtomicWriter._recheck_no_clobber`; `AC12`'s `-O`+`--out-dir` row
needed BOTH the verb's `consumes=` declaration and `cli/common.py`'s mutual
exclusion; `AC13`'s escape needed all THREE containment tiers (the exit-2 template
guard, the exit-5 component check, and `ensure_within`).

**Findings are reported to the `project-manager`, not filed here** — the wave-4
brief makes `qa/FINDINGS-LEDGER.md` read-only to `PDF-21`, so new findings carry a
`PENDING-LEDGER:` slug in the convention `audit_pdf_03/04/05/06.py` established.
Rows citing an EXISTING fingerprint (`0615feae63`, `66f43b3123`, `cb948ad85b`)
name it directly.

**Spec pointers re-measured rather than transcribed** (corrected in `PDF-21`'s
report, not in any owned file): `PDF-21` E-5's *"104 C14 cases"* re-measured and
CONFIRMED at `b20a651` (26 verbs x 4 flags); `make samples-gate` is at
`Makefile:219`, not `:201-219`; HEAD is **39** commits past `PDF-09`'s last
commit, not the 29 `PDF-21` E-6 states; and `PDF-09` AC13's *"(exit 5 per D4)"*
parenthetical is wrong at CLI level — the measured refusal is **exit 2**.
"""

from __future__ import annotations

from typing import Final

from acceptance._model import ACAudit, RedKind

SPEC_ID: Final[str] = "PDF-09"
AC_COUNT: Final[int] = 28

AUDIT: Final[tuple[ACAudit, ...]] = (
    ACAudit(
        ac="AC1",
        claim=(
            "`rasterize <letter.pdf> --dpi 300 --out-dir <tmp>` on a US-Letter page (612x792 pt) "
            "produces a PNG whose pixel dimensions are exactly 2550x3300, asserted by opening "
            "the file with Pillow. Asserting the file exists is not sufficient."
        ),
        covering=(
            "tests/unit/test_raster.py::test_ac1_dpi_300_on_us_letter_produces_exactly_2550x3300",
        ),
        red=(
            "ADVANCES. MET at b20a651 and grounded on an observed red.\n"
            "MUTATION: removed the round()-computed crop in "
            "`adapters/pdfium_raster.py::_render` (`image = image.crop((0, 0, target_width, "
            "target_height))` replaced by a no-op), which restores the live ceiling defect the "
            "crop exists to correct.\n"
            "OBSERVED: `assert (2550, 3301) == (2550, 3300)` / `At index 1 diff: 3301 != 3300` "
            "-- exactly the pdfium ceil()-vs-round() pixel `PDF-09`'s own engineer found by "
            "running. `test_ac17_render_page_is_directly_reusable_without_the_cli` fired too "
            "(`1651 != 1650`), which is a second, independent consumer of the same geometry.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC2",
        claim=(
            "`rasterize <multipage.pdf> --pages 2 --out-dir <tmp>` writes exactly one file, "
            "asserted by `len(list(tmp.iterdir())) == 1` -- the count of entries in the output "
            "directory, not merely the presence of the expected name."
        ),
        covering=(
            "tests/integration/test_rasterize_cli.py::test_ac2_pages_2_writes_exactly_one_file",
        ),
        red=(
            "ADVANCES. MET at b20a651 and grounded on an observed red.\n"
            "MUTATION: `ops/raster.py`'s planning loop made to ignore the resolved selection "
            "(`_plan_pages(source, pages_spec)` -> `_plan_pages(source, None)`), so every page "
            "is emitted.\n"
            "OBSERVED: `assert 3 == 1` -- three files under the output directory where the "
            "criterion requires one. The directory-entry COUNT is what caught it; a "
            "name-presence check would have stayed green.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC3",
        claim=(
            "Byte identity across thread counts, both halves, over a >=8-page fixture: "
            "(a) the SHA-256 of every produced file is equal pairwise between a `--threads 1` "
            "and a `--threads 8` run; (b) the sorted filename lists are equal AND the `items` "
            "order in `-o json` is identical between the runs and equals the resolved selection "
            "order. A test that checks only hashes does not satisfy AC3."
        ),
        covering=(
            "tests/unit/test_raster.py::test_ac3_threads_1_and_threads_8_are_byte_identical",
            "tests/integration/test_rasterize_cli.py::"
            "test_ac3_threads_1_and_threads_8_are_byte_identical_over_the_cli",
        ),
        red=(
            "ADVANCES, with BOTH halves driven red separately -- which is the point of the "
            "criterion.\n"
            "MUTATION (a): an encoder parameter derived from the worker count -- `_render_one` "
            "made to pass `compress_level=max(0, 9 - policy.threads)` for PNG.\n"
            "OBSERVED (a): `AssertionError: eight-0001.png` / `assert b'\\x89PNG...' == "
            "b'\\x89PNG...'` / `At index 35 diff: b'\\x1b' != b'A'` -- both the ops-layer and the "
            "real-subprocess CLI arms fired.\n"
            "MUTATION (b): results ordered by completion instead of by slot "
            "(`collected[slot] for slot in range(len(work))` -> `sorted(collected, "
            "reverse=True)`).\n"
            "OBSERVED (b): `At index 0 diff: 'multi-0008.png' != 'multi-0001.png'` -- the HASH "
            "arm stayed green and only the ORDER arm fired, which is precisely why AC3 asserts "
            "both.\n"
            "FINDING FILED, not repaired: the order half is still only exercised over a "
            "selection that is every page, so *equals the resolved selection order* is not yet "
            "distinguished from *sorted*. `PDF-21` D3 offered strengthening or filing; this "
            "audit filed.\n"
            "REVERTED from the gold tree; sha256 match on both arms."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=("PENDING-LEDGER: pdf-09-ac3b-order-clause-never-uses-a-non-contiguous-selection"),
    ),
    ACAudit(
        ac="AC4",
        claim=(
            "A unit test asserts the worker function's signature and call convention: it is a "
            "module-level function, and every argument it receives and every value it returns "
            "is picklable (`pickle.dumps` round-trips them). No pdfium object appears in either."
        ),
        covering=(
            "tests/unit/test_raster.py::test_ac4_render_chunk_is_module_level_and_picklable",
            "tests/unit/test_raster.py::"
            "test_ac4_worker_arguments_and_return_value_round_trip_through_pickle",
        ),
        red=(
            "ADVANCES. MET at b20a651 and grounded on an observed red.\n"
            "MUTATION: an OPEN pdfium document crosses back out of the worker -- `_render_chunk` "
            "wrapped so each `ItemResult` carries `detail={'handle': "
            "pdfium.PdfDocument(item.input)}`. This is the criterion's own named prohibition "
            "(*no pdfium object appears in either*), applied to the return side.\n"
            "OBSERVED: `ValueError: ctypes objects containing pointers cannot be pickled` at "
            "`assert pickle.loads(pickle.dumps(result)) == result`.\n"
            "RECORDED HONESTLY: a first attempt at this arm produced a `SyntaxError` rather "
            "than a criterion failure. A broken module is NOT a red -- the arm was rewritten "
            "and re-run rather than counted.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC5",
        claim=(
            "A test asserts the parent never holds an open render handle while workers run: the "
            "planning handle is closed before the executor is created (assert via an "
            "instrumented adapter counter, or by asserting `render_page` is only ever entered "
            "from a non-main thread when `--threads > 1`)."
        ),
        covering=(
            "tests/unit/test_raster.py::"
            "test_ac5_the_planning_handle_is_closed_before_the_executor_is_created",
            "tests/unit/test_raster.py::test_ac5_a_process_pool_dispatch_runs_in_a_different_process",
            "tests/unit/test_raster.py::test_ac5_rasterize_document_never_calls_render_directly",
        ),
        red=(
            "ADVANCES, re-derived AS WRITTEN via the FIRST of the two mechanizations the "
            "criterion itself offers. NOT superseded: the criterion is a disjunction and the "
            "instrumented-counter disjunct is live. Its SECOND disjunct is falsified by X-104 "
            "and is recorded as such -- rendering happens in child PROCESSES, on their own main "
            "threads, so *`render_page` only ever entered from a non-main thread* can never "
            "hold.\n"
            "THE SHIPPED CONTROL WAS VACUOUS AND IS REPLACED, NOT SUPPLEMENTED: "
            "`test_ac5_a_process_pool_dispatch_runs_in_a_different_pid` referenced NO "
            "`pdf_toolkit` symbol at all -- it submitted a local function to a "
            "`ProcessPoolExecutor` and asserted the PID differed. It tested that CPython forks, "
            "and it passed with the entire rasterize feature deleted. Filed as a finding.\n"
            "MUTATION: the planning handle held open across the executor -- `_plan_pages` made "
            "to `__enter__()` the structure document into a module-level list and never close "
            "it.\n"
            "OBSERVED: `AssertionError: 1 planning handle(s) were still open when the executor "
            "was created; AC5 requires the parent to hold none` / `assert [1] == [0]`.\n"
            "The replacement's own non-vacuity is asserted in the test: the sample list must be "
            "non-empty, i.e. the pool was really created.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=("PENDING-LEDGER: pdf-09-ac5-shipped-pid-test-references-no-product-symbol"),
    ),
    ACAudit(
        ac="AC6",
        claim=(
            "`--threads 0`, `--threads -1` exit 2. `--threads 1` and `--threads 8` both exit 0 "
            "on the fixture and take the same code path (one executor call site, asserted by "
            "coverage of the single parallel function in both runs)."
        ),
        covering=(
            "tests/integration/test_rasterize_cli.py::test_ac6_threads_out_of_range_exits_2[0]",
            "tests/integration/test_rasterize_cli.py::test_ac6_threads_out_of_range_exits_2[-1]",
            "tests/integration/test_rasterize_cli.py::test_ac6_threads_1_and_8_both_exit_0[1]",
            "tests/integration/test_rasterize_cli.py::test_ac6_threads_1_and_8_both_exit_0[8]",
        ),
        red=(
            "FINDING. The exit-code halves are met and were driven red; the criterion's THIRD "
            "clause is measured by nothing, and this audit did not build the missing control, "
            "so the criterion is not fully re-derived and cannot ground a re-grant.\n"
            "MUTATION (the halves that do have controls): `cli/common.py`'s `if config.threads "
            "< 1` weakened to `< -99999`, so 0 and -1 are accepted.\n"
            "OBSERVED: `assert 0 == 2` on BOTH `[0]` and `[-1]` -- the runs completed and wrote "
            "files instead of refusing.\n"
            "THREE MEASURED WEAKNESSES, all recorded rather than papered over. (i) *the same "
            "code path, asserted by coverage of the single parallel function in both runs* has "
            "NO coverage assertion of any kind, anywhere -- the clause is prose. (ii) the exit-2 "
            "half is enforced in the SHARED option layer (`cli/common.py:560-561`), so it is not "
            "a `rasterize` control at all: the identical red fires for every verb. (iii) the "
            "`--threads 8` arm runs a 2-page source, so `min(8, len(work)) == 2` chunks and "
            "eight workers are never exercised by the arm that names eight.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=(
            "PENDING-LEDGER: "
            "pdf-09-ac6-coverage-clause-has-no-assertion-and-the-8-thread-arm-uses-2-pages"
        ),
    ),
    ACAudit(
        ac="AC7",
        claim=(
            "Executor-agnosticism is mechanized: a test drives the *same* module-level worker "
            "through a `ProcessPoolExecutor` and asserts the produced files are byte-identical "
            "to the `ThreadPoolExecutor` run. This is the standing proof of PLAN §12 R-08's "
            "reversibility clause."
        ),
        covering=(
            "tests/unit/test_raster.py::"
            "test_ac7_process_pool_and_thread_pool_produce_byte_identical_output",
        ),
        red=(
            "SUPERSEDED (PDF-21 §D3.2's closed list; mechanism falsified by X-104), and driven "
            "red on the successor property.\n"
            "ORIGINAL TEXT, verbatim, is the `claim` field above. The criterion says *the "
            "`ThreadPoolExecutor` run* without qualification. X-104 falsifies the unqualified "
            "reading: real concurrent pdfium rendering across OS threads corrupts the process "
            "heap even with per-worker document isolation, reproduced live during `PDF-09`'s "
            "own implementation. SUCCESSOR PROPERTY, which is what the shipped test asserts and "
            "what was driven red: the same module-level worker through a `ProcessPoolExecutor` "
            "and through a SINGLE-WORKER `ThreadPoolExecutor` -- the one thread-pool shape with "
            "no concurrent access at all -- produces byte-identical files.\n"
            "MUTATION: per-worker state the process arm cannot see -- `_render_one` made to pick "
            "its PNG compress level from `threading.current_thread() is "
            "threading.main_thread()`, which differs between a pool worker's own main thread "
            "and a thread-pool worker thread.\n"
            "OBSERVED: `assert b'\\x89PNG...' == b'\\x89PNG...'` / `At index 35 diff: b'B' != "
            "b'\\x17'`.\n"
            "ONE ITEM NOT DONE, reported rather than silently skipped: `PDF-21` D3 also asked "
            "for the dead `work` / `del work` pair to be removed from this test while in the "
            "file. It was not; it is filed.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-09-ac7-dead-work-del-work-pair-still-present",
    ),
    ACAudit(
        ac="AC8",
        claim=(
            "A page carrying `/Rotate 90` in PDF-06's generated corpus rasterizes landscape: "
            "`img.size[0] > img.size[1]` where the unrotated page is portrait, and the reported "
            "`width_px`/`height_px` match the file."
        ),
        covering=(
            "tests/unit/test_raster.py::test_ac8_rotated_page_rasterizes_landscape",
            "tests/unit/test_raster.py::test_b094_rotate_is_applied_exactly_once_at_every_angle[0]",
            "tests/unit/test_raster.py::test_b094_rotate_is_applied_exactly_once_at_every_angle[90]",
            "tests/unit/test_raster.py::test_b094_rotate_is_applied_exactly_once_at_every_angle[180]",
            "tests/unit/test_raster.py::test_b094_rotate_is_applied_exactly_once_at_every_angle[270]",
            "tests/unit/test_raster.py::test_b094_displayed_size_agrees_with_pdfiums_own_unrotated_render",
            "tests/unit/test_raster.py::test_b094_the_ceiling_correction_is_still_a_crop_and_never_a_pad[0]",
            "tests/unit/test_raster.py::test_b094_the_ceiling_correction_is_still_a_crop_and_never_a_pad[90]",
            "tests/unit/test_raster.py::test_b094_the_ceiling_correction_is_still_a_crop_and_never_a_pad[180]",
            "tests/unit/test_raster.py::test_b094_the_ceiling_correction_is_still_a_crop_and_never_a_pad[270]",
        ),
        red=(
            "REGRESSION-ONLY. **THIS ROW IS OUTSIDE THE FOUR-BUCKET CLASSIFICATION AND THIS "
            "AUDIT DID NOT RE-DERIVE IT.** It is the 28th row because the contiguity pin "
            "requires a row for every criterion of the audited spec, including ones that pass "
            "trivially; the 27 criteria this audit re-derived are AC1-AC7 and AC9-AC28.\n"
            "PROVENANCE OF THE RED, stated so no reader mistakes it for one this audit drove: "
            "AC8 was independently re-verified at `971d0e5` (`B-094`), where the inverted "
            "fixture was replaced -- `Canvas.setPageRotation(90)` pre-swaps the MediaBox, so the "
            "old `width > height` assertion passed BECAUSE of the defect -- and the corrected "
            "control was measured going red there, by that spec's engineer. **`PDF-21` did not "
            "re-drive it and claims no red of its own on this row.**\n"
            "WHAT THIS AUDIT DID DO, measured at the landed commit: ran "
            "`uv run pytest tests/unit/test_raster.py -k 'ac8 or b094'` -> **10 passed, 38 "
            "deselected**, and confirmed `git diff --stat HEAD -- "
            "src/pdf_toolkit/adapters/pdfium_raster.py` is EMPTY, so `B-094`'s `/Rotate` fix "
            "stands exactly as landed and this spec changed no rendering behaviour."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="B-094",
    ),
    ACAudit(
        ac="AC9",
        claim=(
            '`--grayscale` produces an image whose Pillow `mode == "L"` (single channel) for '
            "each of `png`, `tiff`, `webp`, and a grayscale JPEG for `jpeg`; without the flag "
            "the mode is `RGB`."
        ),
        covering=(
            "tests/unit/test_raster.py::test_ac9_grayscale_produces_mode_l[png]",
            "tests/unit/test_raster.py::test_ac9_grayscale_produces_mode_l[tiff]",
            "tests/unit/test_raster.py::test_ac9_grayscale_produces_mode_l[jpeg]",
            "tests/unit/test_raster.py::test_ac9_grayscale_webp_is_perceptually_grayscale_but_reads_back_rgb",
            "tests/unit/test_raster.py::test_ac9_the_webp_grayscale_arm_can_fail_without_the_flag",
            "tests/unit/test_raster.py::test_ac9_without_grayscale_the_mode_is_rgb",
            "tests/unit/test_verb_help_content.py::"
            "test_ac9_rasterize_help_qualifies_the_single_channel_claim_for_webp",
        ),
        red=(
            'SUPERSEDED on its `"L" for webp` clause (PDF-21 §D3.2\'s closed list; physically '
            "unsatisfiable), and the covering control REBUILT because it was inverted.\n"
            "ORIGINAL TEXT is the `claim` field above. WebP's bitstream has no single-channel "
            "pixel mode at all; Pillow's WebP encoder converts any non-RGB(A/X) source to RGB "
            "before handing it to libwebp. SUCCESSOR PROPERTY: `L` for png/tiff/jpeg, and for "
            "webp an `RGB` file that is GENUINELY a grayscale conversion -- plus a `--help` "
            "statement that says so, since the shipped help claimed single-channel output "
            "without qualification (`66f43b3123`).\n"
            "THE SHIPPED WEBP ARM WAS A SECOND INVERTED CONTROL, IN THE SAME FILE AS AC8'S, AND "
            "IT WAS MEASURED BEFORE BEING REPAIRED. Its fixture `_make_letter` draws BLACK TEXT "
            "ON WHITE, so R == G == B before any conversion. Measured at b20a651 on that "
            "fixture: `grayscale=True -> mode=RGB max_delta=1` and `grayscale=False -> mode=RGB "
            "max_delta=1` -- **both shipped assertions passed identically with the feature "
            "switched off.** Rebuilt on a six-band saturated colour fixture: `grayscale=True -> "
            "max_delta=0`, `grayscale=False -> max_delta=255`.\n"
            "MUTATION: `grayscale=grayscale` dropped from the adapter call in `ops/raster.py`.\n"
            "OBSERVED: the three `mode == 'L'` arms fired AND the rebuilt webp arm fired with "
            "`AssertionError: assert 255 <= 8` -- which the shipped arm could not have done on "
            "any input.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="66f43b3123",
    ),
    ACAudit(
        ac="AC10",
        claim=(
            "`--width 1200` on the US-Letter fixture produces an image exactly 1200 px wide "
            "with height equal to `round(1200 * 792/612)` +/-1, and the JSON's reported "
            "dimensions equal the file's actual dimensions (measured, not predicted)."
        ),
        covering=(
            "tests/unit/test_raster.py::test_ac10_width_mode_produces_exact_width_and_measured_height",
            "tests/unit/test_raster.py::test_ac27_message_matches_the_produced_file_for_dpi_and_width_modes",
        ),
        red=(
            "ADVANCES. MET at b20a651 and grounded on an observed red.\n"
            "MUTATION: the adapter made to report PREDICTED rather than MEASURED dimensions -- "
            "`RenderedPage.width_px/height_px` sourced from pdfium's own pre-crop, ceil()-based "
            "bitmap size instead of the produced image, which is exactly the number the crop "
            "exists to correct.\n"
            "OBSERVED: `assert (2550, 3301) == (2550, 3300)` -- the reported dimensions no "
            "longer equal what Pillow reads back from the file.\n"
            "NARROWNESS RECORDED, not overstated: at HEAD both the message and the assertion's "
            "expected value trace to the same produced `Image` object, so the cross-check "
            "proves agreement with the object rather than with an independent decode. It is "
            "still a real control -- the mutation above separates the two and reds it -- but "
            "the independence is weaker than the criterion's *measured, not predicted* phrasing "
            "suggests. Filed.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=(
            "PENDING-LEDGER: pdf-09-ac10-message-and-expectation-share-the-produced-image-object"
        ),
    ),
    ACAudit(
        ac="AC11",
        claim=(
            "Run-to-run determinism: two consecutive identical `--threads 8` runs into fresh "
            "directories produce byte-identical files (proves no timestamp/metadata is "
            "embedded), and a produced PNG contains no `tIME` chunk (byte-level check)."
        ),
        covering=(
            "tests/unit/test_raster.py::test_ac11_two_runs_are_byte_identical_and_carry_no_time_chunk",
        ),
        red=(
            "ADVANCES. MET at b20a651 and grounded on an observed red.\n"
            "MUTATION: a `tIME` chunk written through `PngInfo` in `ops/raster.py::_encode`, "
            "seeded from `time.time()` so it also breaks run-to-run byte identity.\n"
            "OBSERVED: `AssertionError: assert b'tIME' not in b'\\x89PNG\\r\\n\\x1a\\n...\\x07tIME"
            "\\x07...'` -- the byte-level chunk scan fired on the produced file.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC12",
        claim=(
            "Every ruling in D3 has a test: `--dpi 300 --width 1200` -> 2; `--quality 82 "
            "--format png` -> 2; `--quality 0`/`101` -> 2; `-O a.png --out-dir d` -> 2; `-O "
            "a.png` with a 3-page selection -> 2; `-O a.jpg --format png` -> 2; `--name "
            "'{range}.png'` -> 2; `--pages 1--3` -> 2; `--pages even` on a 1-page document -> 4; "
            "existing target without `--force` -> 5; two inputs with the same stem into one "
            "`--out-dir` -> 5 with no file written; `RasterEngine` monkeypatched unavailable -> "
            "3 with the hint in the message."
        ),
        covering=(
            "tests/integration/test_rasterize_cli.py::test_ac12_dpi_and_width_together_exits_2",
            "tests/integration/test_rasterize_cli.py::test_ac12_quality_with_png_exits_2",
            "tests/integration/test_rasterize_cli.py::test_ac12_quality_out_of_range_exits_2[0]",
            "tests/integration/test_rasterize_cli.py::test_ac12_quality_out_of_range_exits_2[101]",
            "tests/integration/test_rasterize_cli.py::test_ac12_output_with_out_dir_exits_2",
            "tests/integration/test_rasterize_cli.py::test_ac12_output_alone_exits_2_with_a_three_page_selection",
            "tests/integration/test_rasterize_cli.py::test_ac12_name_range_exits_5",
            "tests/integration/test_rasterize_cli.py::test_ac12_pages_malformed_exits_2",
            "tests/integration/test_rasterize_cli.py::test_ac12_pages_even_on_a_one_page_document_exits_4",
            "tests/integration/test_rasterize_cli.py::test_ac12_existing_target_without_force_exits_5",
            "tests/integration/test_rasterize_cli.py::test_ac12_two_inputs_same_stem_collide_exit_5_nothing_written",
            "tests/unit/test_raster.py::test_raster_engine_unavailable_exits_3_with_a_hint",
        ),
        red=(
            "ADVANCES -- ELEVEN SUB-RULES, ELEVEN SEPARATE MUTATIONS, ELEVEN OBSERVED REDS. The "
            "twelfth (`-O a.jpg --format png`) was struck by `PDF-07` correction C-1 and "
            "correctly has no test; that is recorded rather than restored.\n"
            "(1) dpi+width: guard inverted -> `assert 0 == 2`. (2) quality-with-png: the "
            "lossless set emptied -> `assert 0 == 2`. (3) quality range: `1 <= q <= 100` "
            "widened to `0 <= q <= 101` -> `assert 0 == 2` on BOTH `[0]` and `[101]`. "
            "(4) `-O`+`--out-dir`: BOTH tiers disabled (the verb's `consumes=` declaration made "
            "to accept `--output`, AND `cli/common.py`'s mutual exclusion removed) -> `assert 0 "
            "== 2`. (5) `-O` alone: the `consumes=` declaration made to accept `--output` -> "
            "`assert 5 == 2`. (7) `--name '{range}'`: the token silently rewritten in "
            "`ops/raster.py` -> `assert 0 == 5` and `DID NOT RAISE OutputEscapesDirError`. "
            "(8) `--pages 1--3`: `pagerange.parse` made to truncate at the malformed separator "
            "-> `assert 0 == 2`. (9) `--pages even` on 1 page: the empty-selection refusal "
            "disabled -> `assert 0 == 4` and `DID NOT RAISE NoInputError`. (10) existing target: "
            "BOTH no-clobber tiers disabled (`safety/paths.py`'s pre-flight AND "
            "`AtomicWriter._recheck_no_clobber`) -> `assert 0 == 5`. (11) same-stem collision: "
            "`check_output_collisions` removed -> `assert 0 == 5`. (12) engine unavailable: the "
            "up-front `require_raster` call removed -> `DID NOT RAISE EngineMissingError`.\n"
            "TWO SUB-RULES ARE DEFENDED IN DEPTH and a single-point mutation left them green -- "
            "measured, not assumed: (4) and (10) each needed BOTH of their tiers disabled. "
            "Recorded because it is a genuine property of the product.\n"
            "FINDING FILED: the shipped `test_ac12_existing_target_without_force_exits_5` seeded "
            '`b"already here"` and never re-read it, so the NO-CLOBBER half -- the half a user '
            "cares about -- was unasserted; a run that exited 5 after overwriting the file "
            "passed. The read-back is added here.\n"
            "ALL ELEVEN REVERTED from the gold tree; sha256 match on every arm."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=("PENDING-LEDGER: pdf-09-ac12-no-clobber-half-was-seeded-but-never-re-read"),
    ),
    ACAudit(
        ac="AC13",
        claim=(
            "Containment is consumed, not re-derived. `--name '../{stem}.png'` is refused (exit "
            "5 per D4; assert whatever the shared safety path enforces) and nothing is written "
            "outside `--out-dir`. Mechanized companion: `grep -nE '\\.\\.|normpath|realpath|"
            "resolve\\(\\)' src/pdf_toolkit/ops/raster.py` returns no path-sanitization logic."
        ),
        covering=(
            "tests/unit/test_raster.py::test_ac13_ops_raster_calls_no_path_sanitization_function",
            "tests/unit/test_raster.py::test_ac13_name_escaping_the_out_dir_is_refused_and_nothing_escapes",
            "tests/integration/test_rasterize_cli.py::"
            "test_ac13_name_escaping_the_out_dir_is_refused_at_the_cli_and_nothing_escapes",
        ),
        red=(
            "ADVANCES, on both halves, with the criterion's own literal grep recorded as "
            "BROKEN.\n"
            "MUTATION (a): a local sanitizer added to `ops/raster.py` (`Path(target).resolve()`)."
            "\nOBSERVED (a): `assert <re.Match object; span=(9529, 9538), match='resolve()'> is "
            "None`.\n"
            "MUTATION (b): ALL THREE containment tiers disabled -- `cli/common.py`'s exit-2 "
            "filename-template guard, `safety/naming.py`'s exit-5 path-separator component "
            "check, and the `ensure_within` call.\n"
            "OBSERVED (b): `assert 0 == 2`, and the envelope shows the escape actually "
            'happened: `"output": ".../out/../src.png", "ok": true` -- a file written '
            "outside `--out-dir`. Both the ops-layer and the CLI-layer arms fired. Two tiers "
            "were NOT enough: measured, the product refuses this at three independent points.\n"
            "TWO CORRECTIONS TO THE CRITERION'S OWN TEXT, measured at b20a651 and filed rather "
            "than edited into it. (i) Its literal grep alternative `\\.\\.` matches `...` in "
            "prose and type hints -- SIX false positives in `ops/raster.py` on clean source -- "
            "so the shipped test correctly substitutes a call-shaped regex. A grep that has "
            "never been shown to match is not a control. (ii) Its parenthetical *(exit 5 per "
            'D4)* is wrong at CLI level: the measured refusal is **exit 2** with *"--name is a '
            'filename template and must not contain a path separator"*, from a guard that fires '
            "BEFORE `render_name`. Exit 5 is what the ops layer produces when called directly. "
            "The criterion's own hedge (*assert whatever the shared safety path enforces*) is "
            "what makes it re-derivable as written.\n"
            "REVERTED from the gold tree; sha256 match on both arms."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=(
            "PENDING-LEDGER: "
            "pdf-09-ac13-literal-grep-has-six-false-positives-and-names-the-wrong-exit-code"
        ),
    ),
    ACAudit(
        ac="AC14",
        claim=(
            "Mechanized help-text criterion: `rasterize --help | grep -q -- '--threads 1'` "
            "succeeds and the surrounding line states that `--threads 1` forces deterministic "
            "sequential rendering and is the switch to reproduce a parallel failure. A test "
            "asserts the grep, so this cannot rot into an instruction nobody notices."
        ),
        covering=(
            "tests/integration/test_rasterize_cli.py::"
            "test_ac14_help_documents_threads_1_as_the_reproduction_switch",
        ),
        red=(
            "ADVANCES. The claim sentence EXISTS in the shipped `_HELP` at b20a651, so the "
            "property is MET there; the strengthening below is a TEST-ONLY change, green at "
            "b20a651 with only the new assertion added, so X-215(ii) does not fire.\n"
            "MUTATION: the claim sentence -- and ONLY that sentence -- deleted from `_HELP`, "
            "leaving the byte-identity sentence intact.\n"
            "OBSERVED, BOTH STATES MEASURED, WHICH IS THE WHOLE POINT OF THIS ROW: against the "
            "SHIPPED assertion (`'--threads 1' in result.stdout`) the mutated help stayed "
            "**GREEN** -- `--threads 1` still occurs once, in the surviving sentence. That is "
            "the finding. Against the strengthened assertion it fired: `AssertionError: "
            "'--threads 1' is named but the claim AC14 requires the surrounding line to make is "
            "absent; the flag token alone is not the criterion`.\n"
            "THE FIX: the claim is now pinned as a collapsed-whitespace SENTENCE, not as the "
            "flag token, so deleting the sentence reds the test while the second `--threads 1` "
            "occurrence remains.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=(
            "PENDING-LEDGER: pdf-09-ac14-shipped-help-control-pinned-the-flag-token-not-the-claim"
        ),
    ),
    ACAudit(
        ac="AC15",
        claim=(
            "`--dry-run` writes nothing: tree snapshot (path + size + mtime + hash) before and "
            "after is identical, the `--out-dir` is not created, and no `.pdftoolkit-*` temp "
            "file appears anywhere. It still prints the full list of planned output paths and "
            "exits 0."
        ),
        covering=(
            "tests/integration/test_rasterize_cli.py::"
            "test_ac15_dry_run_writes_nothing_and_does_not_create_out_dir",
        ),
        red=(
            "ADVANCES, on the PURITY half, which is the whole of the criterion as written.\n"
            "MUTATION: `--out-dir` created before the dry-run gate (`out_dir.mkdir(parents=True, "
            "exist_ok=True)` inserted ahead of `plan_output_set`).\n"
            "OBSERVED: `AssertionError: assert not True` / `where True = "
            "PosixPath('.../does-not-exist-yet').exists()` -- the not-created assertion fired.\n"
            "ONE ORPHANED CLAUSE CLOSED: *it still prints the FULL LIST of planned output "
            "paths* was unasserted -- the covering row read only `items[0].output`, so a dry run "
            "that predicted ONE page of a two-page selection passed. The full list is now "
            "asserted against the resolved selection. Filed as a finding, then closed.\n"
            "OUT OF SCOPE AND DELIBERATELY NOT PRE-EMPTED: `b43bb70cc3` / `B-058` -- the "
            "`--dry-run` filesystem-tier PREDICTION defect (dry `would_exit 0` vs real `1` under "
            "an unwritable parent) -- is specced to `PDF-18`, which owns the unified "
            "`_plan_filesystem`. Nothing here touches it.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-09-ac15-planned-path-list-clause-was-unasserted",
    ),
    ACAudit(
        ac="AC16",
        claim=(
            "The forbidden-name grep over `ops/raster.py`, `ports/raster.py` and "
            "`adapters/pdfium_raster.py` returns nothing, and `tests/test_license_policy.py` "
            "stays green. The rasterize call path spawns no process and names no forbidden tool "
            "-- including as a fallback when `pypdfium2` raises. A render failure is a failed "
            "`ItemResult` and exit 1, never a fallback."
        ),
        covering=(
            "tests/unit/test_raster.py::test_ac16_no_forbidden_name_or_process_spawn[ops/raster.py]",
            "tests/unit/test_raster.py::test_ac16_no_forbidden_name_or_process_spawn[ports/raster.py]",
            "tests/unit/test_raster.py::"
            "test_ac16_no_forbidden_name_or_process_spawn[adapters/pdfium_raster.py]",
            "tests/unit/test_raster.py::test_ac16_a_render_failure_is_a_failed_item_and_exit_1_never_a_fallback",
            "tests/integration/test_rasterize_cli.py::test_hc1_no_forbidden_name_in_cmd_rasterize",
            "tests/test_license_policy.py::test_self_positive_detects_all_three_leaks",
        ),
        red=(
            "ADVANCES, on both clauses -- and the second clause had NO TEST IN THE REPOSITORY "
            "before this audit.\n"
            "MUTATION (a): `import subprocess` planted at the top of `ops/raster.py`.\n"
            "OBSERVED (a): `AssertionError: ops/raster.py` / `assert <re.Match object; "
            "span=(3689, 3699), match='subprocess'> is None`.\n"
            "MUTATION (b): the render failure swallowed -- `_render_one`'s `except "
            "PdfToolkitError` arm made to return `ok=True, exit_code=0`.\n"
            "OBSERVED (b): `assert [True, True, True] == [True, False, True]` / `At index 1 "
            "diff: True != False`.\n"
            "THE GAP THIS CLOSES: nothing in the suite had ever produced `ok=False` out of "
            "`_render_one`, so *a render failure is a failed `ItemResult` and exit 1, never a "
            "fallback* -- the clause that carries HC-1's whole point -- was prose. The new "
            "control fails page 2 of 3 through the adapter, asserts the other two pages are "
            "still written, and asserts the run-level code is 1. Filed as a finding, then "
            "closed.\n"
            "REVERTED from the gold tree; sha256 match on both arms."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=("PENDING-LEDGER: pdf-09-ac16-render-failure-path-had-no-test-at-all"),
    ),
    ACAudit(
        ac="AC17",
        claim=(
            "The render is re-usable by another verb. A test imports the `RasterEngine` port and "
            "its resolved adapter directly -- no Typer, no CLI, no `--out-dir`, no file written "
            "-- calls `render_page(path, 1, dpi=150, width_px=None, grayscale=True)`, and "
            "asserts it returns an in-memory carrier with correct `width_px`/`height_px`/`mode`."
        ),
        covering=(
            "tests/unit/test_raster.py::test_ac17_render_page_is_directly_reusable_without_the_cli",
        ),
        red=(
            "ADVANCES. MET at b20a651 and grounded on an observed red.\n"
            "MUTATION: the port made to write a file -- an empty `<path>.sidecar` created inside "
            "`render_page` before it returns.\n"
            "OBSERVED: `AssertionError: assert [PosixPath('.../letter.pdf.sidecar'), ...] == "
            "[PosixPath('.../letter.pdf')]` / `Left contains one more item` -- the *no file "
            "written* half fired, which is the half `PDF-23`'s overlay path depends on.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC18",
        claim=(
            "`rasterize` is in the verb registry, so `pytest --collect-only` shows PDF-06's "
            "contract tests instantiated for it: `--help` exits 0 and names its port; an unknown "
            "flag exits 2; a nonexistent input path exits 4; `--pages 1--3` exits 2; `--dry-run` "
            "purity passes."
        ),
        covering=(
            "tests/unit/test_verb_help_content.py::test_ac1_these_verbs_name_the_port_they_depend_on[rasterize]",
            "tests/unit/test_registry.py::test_every_discovered_verb_is_registered_in_invocations",
            "tests/unit/test_registry.py::test_discover_verbs_finds_exactly_the_twenty_six_landed_verbs",
        ),
        red=(
            "MADE-TRUE-HERE. **This criterion was NOT MET at the audited HEAD, and it is true "
            "only because of this spec's own `src/` edit, so X-215(ii) fires and it cannot "
            "ground the re-grant.** Recorded as a disqualifier, not as a success.\n"
            "MEASURED AT b20a651, BEFORE ANY EDIT: `rasterize --help` contains `RasterEngine` "
            '**ZERO** times, while `ports/raster.py:24` reads `PORT = "RasterEngine"`. The '
            "port half of AC18 was `0615feae63`'s subject -- filed as UNMEASURED -- and is here "
            "measured to have been UNMET as well.\n"
            "RED, WITH NO MUTATION AT ALL, AGAINST UNMODIFIED SOURCE (the cheapest and "
            "strongest evidence in this audit): the new assertion, added to the scratch with "
            "the product still at b20a651, failed with `AssertionError: rasterize --help does "
            "not name 'RasterEngine', the port it resolves. A user who cannot see which engine "
            "a verb depends on cannot act on `doctor` output.` It went green only after the "
            "`_HELP` edit.\n"
            "THE PORT NAME IS READ FROM THE CODE, NEVER TYPED: the assertion imports "
            "`pdf_toolkit.ports.raster.PORT`, so `grep -n '\"RasterEngine\"' "
            "tests/unit/test_verb_help_content.py` returns nothing and a port rename reds the "
            "test instead of leaving a stale literal passing.\n"
            "REGISTRY HALF, separately grounded: the `rasterize` row deleted from "
            "`tests/registry.py::INVOCATIONS` -> `AssertionError: assert {'rasterize'} == "
            "set()`. Restored from the gold tree; sha256 match.\n"
            "`0615feae63` is reported ready to move to `fixed`."
        ),
        red_kind=RedKind.DELETED_ROW,
        finding="0615feae63",
    ),
    ACAudit(
        ac="AC19",
        claim=(
            "`make ci` is green locally (`fmt-check lint typecheck test licenses sast "
            "vulncheck`), coverage stays >= 85%, and `mypy --strict src/` passes on the three "
            "new/extended modules."
        ),
        covering=(
            "tests/test_gate_parity.py::test_makefiles_ci_prerequisites_are_exactly_the_in_make_ci_true_locals",
            "tests/test_gate_parity.py::test_the_coverage_floor_is_defined_only_in_the_makefile",
        ),
        red=(
            "ADVANCES, as a GATE with a real config control rather than as prose.\n"
            "MEASURED, not repeated from `PDF-09`'s claimed 94%: `make ci` exits **0** with "
            "**2229 passed, 31 skipped, 1 xfailed** and `Required test coverage of 85% reached. "
            "Total coverage: **93.99%**` (baseline before this spec's edits, same command: 2200 "
            "passed, 93.94%). `mypy --strict src/` -> `Success: no issues found in 82 source "
            "files`.\n"
            "MUTATION: `cover` removed from the Makefile's `ci:` prerequisite list in the "
            "scratch.\n"
            "OBSERVED: `AssertionError: gate_parity check: FAILED` / `[[check]] entries claim "
            "'cover' is in_make_ci = true, but Makefile's 'ci:' target no longer runs it -- the "
            "local gate has silently narrowed`, and `test_makefiles_ci_prerequisites_...` fired "
            "with `Extra items in the right set: 'cover'`.\n"
            "FLOOR PROVENANCE, re-measured with the brief's own spelling `grep -n "
            "'cov-fail-under' Makefile pyproject.toml`: exactly ONE live enforcement site, "
            "`Makefile:96`; `pyproject.toml:146` is prose; `.github/workflows/ci.yml` has no "
            "site and reaches the floor through `make cover` at `ci.yml:138`. The floor is "
            "**line, not branch**, since `B-034`, so AC19 enforces a weaker property today than "
            "when it was written -- restoring branch coverage is `PDF-17`'s decision, not this "
            "spec's. Unchanged here; no `omit` added.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
    ),
    ACAudit(
        ac="AC20",
        claim=(
            "`tests/test_samples.py` gains a `@pytest.mark.samples` arm that obtains its operand "
            "only through the copy-on-use fixture, asserts page 1 at `--dpi 72` renders exactly "
            "956x1435 px, re-runs AC3's identity check at scale, skips visibly when "
            "`PDF_TOOLKIT_SAMPLES_DIR` is unset or missing, quotes nothing about the corpus "
            "beyond filename/page count/size/hash, and leaves the originals manifest identical."
        ),
        covering=(
            "tests/test_samples.py::test_ac20_sample_page_1_at_72_dpi_renders_the_exact_point_pixel_size",
            "tests/test_samples.py::test_ac20_threads_1_and_threads_8_are_byte_identical_over_a_real_scan",
        ),
        red=(
            "ADVANCES. MET at b20a651 and grounded on an observed red, run against the real "
            "corpus under HC-2.\n"
            "MUTATION: the arm's scale changed from `dpi=72.0` to `dpi=96.0`, so the exact-pixel "
            "assertion is asked about a different render.\n"
            "OBSERVED: `assert (1275, 1914) == (956, 1435)` / `At index 0 diff: 1275 != 956`. "
            "The assertion is exact and has no rounding slack, which is what makes it decisive.\n"
            "HC-2 THROUGHOUT: the operand is a copy-on-use copy; the originals directory was "
            "read and never written, renamed, chmod-ed or deleted; and nothing about its content "
            "is quoted here beyond a filename. `make samples-gate` exits **0**, which subsumes "
            "the stale-manifest pre-check, `samples-scratch` first, the present arm running, the "
            "unset arm skipping with zero passes, and `samples-check` last.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC21",
        claim=(
            "`git log -1 --format='%s%n%b'` shows exactly ONE commit for this spec, subject "
            "tagged `[PDF-09]`, DCO-signed. `git show --stat HEAD` lists only the paths this "
            "spec owns plus `changelog.md`, and contains no `README.md` and no `CLAUDE.md`. "
            "Staging is by explicit path -- never `git add -A`."
        ),
        covering=(),
        red=(
            "SUPERSEDED (PDF-21 §D3.2's closed list, X-105/HC-3a) AND CARRYING NO LIVE CONTROL. "
            "A commit graph is not mutable without a rewrite, which OR-6 forbids, so no "
            "mutation for this criterion exists and none is claimed.\n"
            "ORIGINAL TEXT is the `claim` field above. It is FALSE as written and was already "
            "false when granted: `git log --oneline --grep='\\[PDF-09\\]'` returns **TWO** "
            "commits -- `702f5b8` (`feat: rasterize -- PDF pages to images`) and `26f4c79` "
            "(`fix: make AC5/AC26 tests spawn-safe, not fork-only`). SUCCESSOR: **HC-3a** as "
            "X-105 ruled it -- one commit for the initial landing, a post-push CI red repaired "
            "fix-forward, each fix-forward commit carrying its own `changelog.md` entry.\n"
            "MEASURED AGAINST HC-3a, per commit, with `git show <sha> -- changelog.md` and never "
            "a heading grep at HEAD: `702f5b8` added 1 `[PDF-09]` heading and deleted 0; "
            "`26f4c79` added **0** and deleted 0; both carry `Signed-off-by:`. **`26f4c79` is "
            "the HC-3a breach** -- a code-bearing commit with no changelog entry -- already on "
            "the record as `B-042`/X-106 and re-confirmed here.\n"
            "X-98 TWO-LEG AUDIT RUN IN FULL over the whole history. Leg 2 as above. Leg 1 found "
            "exactly one commit that deleted a changelog heading: `33bf481` (`[B-068]`) replaced "
            "`## [PDF-13] fix: wait for /proc...` with its own heading -- 20 headings before, 20 "
            "after, the `[PDF-13]` fix heading count going 1 -> 0. **A heading grep at HEAD "
            "hides this**, because `cd33ced` (`[B-088] fix: restore the changelog entry silently "
            "overwritten at 33bf481`) later restored it. Already caught and repaired on the "
            "record; re-confirmed here as live proof that the per-commit audit fires and the "
            "HEAD grep does not.\n"
            "ONE POINTER CORRECTED: `PDF-21` E-6 says HEAD is 29 commits past `PDF-09`. "
            "`git rev-list --count 26f4c79..HEAD` measures **39**."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="B-042",
    ),
    ACAudit(
        ac="AC22",
        claim=(
            "The OR-3 matrix moves 20 -> 24 on its own: `pytest tests/test_cli_contract.py -k "
            "c14 --collect-only -q` reports 24 cases (6 verbs x 4 flags) and all 24 pass. Two of "
            "`rasterize`'s four are honoured, each with a row in "
            "`tests/registry.py::OUTPUT_FLAG_INVOCATIONS`, each exiting 0 with at least one file "
            "that did not exist before; the other two exit 2 with the envelope naming both the "
            "verb and the flag, asserted against `stdout + stderr` combined."
        ),
        covering=(
            "tests/test_cli_contract.py::test_c14_output_flag_matrix[rasterize:--out-dir]",
            "tests/test_cli_contract.py::test_c14_output_flag_matrix[rasterize:--name]",
            "tests/test_cli_contract.py::test_c14_output_flag_matrix[rasterize:--output]",
            "tests/test_cli_contract.py::test_c14_output_flag_matrix[rasterize:--in-place]",
            "tests/test_cli_contract.py::test_the_honoured_population_matches_the_declared_registry",
        ),
        red=(
            "SUPERSEDED (PDF-21 §D3.2's closed list: the count is stale AND was never asserted "
            "by anything), and driven red on the successor property.\n"
            "ORIGINAL TEXT is the `claim` field above. RE-MEASURED at b20a651 with the "
            "criterion's own command: C14 collects **104** cases (**26 verbs x 4 flags**), not "
            "24 -- and `PDF-21` E-5's figure of 104 is CONFIRMED rather than transcribed. X-121 "
            "already records the matrix moving 32 -> 40 at `PDF-11`. **The count itself is prose "
            "in the criterion and is asserted by no test**, so re-deriving it literally would "
            "mean editing an expected number, which `PDF-21` D11 forbids in terms.\n"
            "SUCCESSOR PROPERTY, re-measured: `rasterize` contributes exactly **4** cells, "
            "reached from the live registry with no edit -- 2 honoured (`--out-dir`, `--name`) "
            "and 2 refused (`--output`, `--in-place`).\n"
            'MUTATION: the `("rasterize", "--out-dir")` row deleted from '
            "`tests/registry.py::OUTPUT_FLAG_INVOCATIONS`.\n"
            "OBSERVED: `Failed: rasterize declares '--out-dir' consumed but has no "
            "tests/registry.py::OUTPUT_FLAG_INVOCATIONS[('rasterize', '--out-dir')] row -- add "
            "one so this pair's honoured side is actually proven`, and "
            "`test_the_honoured_population_matches_the_declared_registry` fired with `Extra "
            "items in the left set: ('rasterize', '--out-dir')`. **No expected total was "
            "hand-edited.**\n"
            "RESTORED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.DELETED_ROW,
        finding="PENDING-LEDGER: pdf-09-ac22-cell-count-is-prose-asserted-by-no-test",
    ),
    ACAudit(
        ac="AC23",
        claim=(
            "The `-O`/`--in-place` refusals come from the declaration and from nowhere else. "
            "(a) `-O out.png` -> exit 2 naming `rasterize` and `--output`, no file created; "
            '`--in-place` -> exit 2. (b) `grep -nE \'"--output"|"-O"|"--in-place"\' '
            "src/pdf_toolkit/cli/cmd_rasterize.py` returns nothing. (c) `-O a.png --out-dir d` "
            "emits the mutual-exclusion message while `-O a.png` emits the OR-3 message. (d) The "
            'declaration is exactly `@global_options(consumes=("--out-dir", "--name"))`.'
        ),
        covering=(
            "tests/integration/test_rasterize_cli.py::test_ac23_output_flag_refused_and_nothing_written",
            "tests/integration/test_rasterize_cli.py::test_ac23_in_place_refused",
            "tests/integration/test_rasterize_cli.py::test_ac23b_the_refusal_exists_only_in_the_shared_option_layer",
            "tests/integration/test_rasterize_cli.py::test_ac23_ordering_mutual_exclusion_before_or3",
            "tests/integration/test_rasterize_cli.py::test_ac23_declaration_is_exactly_out_dir_and_name",
        ),
        red=(
            "ADVANCES, with clause (b) given its FIRST test -- it was a mechanized grep in the "
            "criterion that nothing ran.\n"
            "MUTATION (a/b): a second `--output` refusal path added inside `cmd_rasterize.py`.\n"
            "OBSERVED (b): `AssertionError: cmd_rasterize.py names ['\"--output\"'] itself -- "
            "the OR-3 refusal must come from the declaration in cli/common.py and from nowhere "
            "else`.\n"
            "MUTATION (c/d): the `consumes=` declaration widened to accept `--output` and "
            "`--in-place`.\n"
            "OBSERVED (c/d): `assert ('--out-dir', '--name', '--output', '--in-place') == "
            "('--out-dir', '--name')`; `assert 5 == 2` on the `-O`-alone row; and the ordering "
            "row fired on the MESSAGE -- `assert 'mutually exclusive' in '{... \"message\": "
            '"rasterize does not accept --output ..."}\'` -- while both paths still exited 2, '
            "which is exactly why the criterion asserts messages rather than codes.\n"
            "FINDING FILED: clause (b)'s grep had no covering test at all before this audit.\n"
            "REVERTED from the gold tree; sha256 match on both arms."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-09-ac23b-single-path-grep-had-no-covering-test",
    ),
    ACAudit(
        ac="AC24",
        claim=(
            "Every fired pin is updated, never deleted, and the B-031 outcome is recorded either "
            "way. The engineer runs the full suite immediately after registering the verb and "
            "reports the enumerated list of failing pins before fixing any of them. Then the "
            "verb-count, mutating and page-addressing pins are updated to explicit named sets so "
            "they keep failing loudly on the next unclassified verb."
        ),
        covering=(
            "tests/unit/test_registry.py::test_discover_verbs_finds_exactly_the_twenty_six_landed_verbs",
            "tests/unit/test_registry.py::test_the_expected_verbs_are_classified_page_addressing_or_not",
            "tests/unit/test_registry.py::test_the_expected_verbs_are_classified_mutating_or_not",
            "tests/unit/test_registry.py::test_every_discovered_verb_is_registered_in_invocations",
        ),
        red=(
            "SUPERSEDED on its PROCESS half (PDF-21 §D3.2's closed list): *the engineer runs the "
            "full suite and reports the enumerated list of failing pins* describes a past event "
            "and is not re-runnable by anyone, ever. SUCCESSOR PROPERTY, which is the durable "
            "half and was driven red: the pins are explicit named sets that fail LOUDLY on the "
            "next unclassified verb rather than absorbing it silently.\n"
            "MUTATION: a fake verb `zzfake` registered on the live command tree in "
            "`cli/main.py`.\n"
            "OBSERVED: all FOUR pins fired, including both `else: raise AssertionError(...update "
            "this pin)` branches -- `AssertionError: zzfake is not in either expected set -- "
            "update this pin` (page-addressing AND mutating), `assert {'zzfake'} == set()` "
            "(verb count), and the INVOCATIONS registration pin. **No pin absorbed the new verb "
            "silently**, which is the property this criterion exists to protect.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC25",
        claim=(
            "`safety/naming.py` is consumed, not copied or extended. `git show --stat` lists "
            "neither `safety/naming.py` nor `safety/paths.py`. `grep -n 'ensure_within' "
            "src/pdf_toolkit/ops/raster.py` returns nothing. `--name '{range}.png'` -> exit 5 "
            "from the shared renderer, and `--name '../{stem}.png'` -> the code the shared path "
            "enforces, with nothing written outside `--out-dir`. `FIELDS` is not extended."
        ),
        covering=(
            "tests/unit/test_raster.py::test_ac25_ops_raster_never_calls_ensure_within_directly",
            "tests/unit/test_raster.py::test_ac25_range_in_name_template_is_refused_by_the_shared_renderer",
            "tests/unit/test_raster.py::test_ac25_fields_is_not_extended",
        ),
        red=(
            "ADVANCES, on both mechanized halves.\n"
            "MUTATION (a): a sixth token (`dpi`) appended to `safety/naming.FIELDS`.\n"
            "OBSERVED (a): `AssertionError: assert frozenset({'dpi', ...}) == frozenset({...})` / "
            "`Extra items in the left set: 'dpi'`.\n"
            "MUTATION (b): `ensure_within` imported into `ops/raster.py`, i.e. containment "
            "re-derived locally instead of consumed.\n"
            "OBSERVED (b): `assert 'ensure_within' not in '\"\"\"``raster...'` with the offending "
            "import quoted back.\n"
            "CONFIRMED AT THE LANDED COMMIT: `git show --stat` lists neither "
            "`src/pdf_toolkit/safety/naming.py` nor `src/pdf_toolkit/safety/paths.py`; both are "
            "consumed unchanged, and `FIELDS` is not extended.\n"
            "REVERTED from the gold tree; sha256 match on both arms."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC26",
        claim=(
            "Image bytes reach disk only through the chokepoint. Pillow is handed `writer.stream`"
            ", never `writer.path` and never a path string; `--out-dir` is created only via "
            "`safety.atomic.ensure_out_dir`, so `grep -n 'mkdir' src/pdf_toolkit/ops/raster.py` "
            "returns nothing. With `AtomicWriter.__enter__` patched to raise, `rasterize` "
            "produces zero files and leaves no `.pdftoolkit-*` residue. "
            "`tests/test_import_boundaries.py` is absent from `git show --stat` and green "
            "unmodified."
        ),
        covering=(
            "tests/unit/test_raster.py::test_ac26_pillow_is_handed_a_stream_never_a_path",
            "tests/unit/test_raster.py::test_ac26_no_mkdir_in_ops_raster",
            "tests/unit/test_raster.py::test_ac26_atomic_writer_refusing_produces_zero_files",
        ),
        red=(
            "ADVANCES, with the shipped control's PROVEN HOLE closed and BOTH bypasses "
            "demonstrated red -- two mutations for that clause, not one.\n"
            "THE HOLE, MEASURED AT b20a651 BEFORE THE REPAIR. The shipped assertion was "
            "`re.match(r'\\s*(str|Path|[a-z_]*path)\\s*[,)]', call)` over "
            "`re.findall(r'\\.save\\(([^)]*)')`. Because `[^)]*` stops at the FIRST `)`, "
            "`image.save(str(target), ...)` captures `'str(target'` and `str` is then followed "
            "by `(`, not by `[,)]`, so the guard does not fire. Run directly against the four "
            "shapes: `stream` PASSES (correct), `str(target)` **PASSES** (the hole), "
            "`Path(target)` **PASSES** (the hole), `writer.path` FAILS (the only one it "
            "caught).\n"
            "THE REPAIR: the denylist regex is replaced by an AST parse with an ALLOWLIST -- "
            "every `.save(` call's first positional argument must be, verbatim, `stream`. "
            "Parsing removes the class of hole rather than one instance of it.\n"
            "MUTATION (a): `image.save(str(target), ...)`. OBSERVED: `AssertionError: "
            "ops/raster.py:171: image bytes are handed 'str(target)', not an AtomicWriter stream "
            "-- the chokepoint is bypassed (allowed: ['stream'])`.\n"
            "MUTATION (b): `image.save(Path(target), ...)`. OBSERVED: the same assertion naming "
            "`'Path(target)'`.\n"
            "MUTATION (c): `image.save(writer.path, ...)`. OBSERVED: the same assertion naming "
            "`'writer.path'` -- the one shape the old regex caught still fires.\n"
            "MUTATION (d): `out_dir.mkdir(...)` inserted into `ops/raster.py`. OBSERVED: `assert "
            "'mkdir' not in ...` with the offending line quoted back.\n"
            "ONE CORRECTION TO THE CRITERION'S OWN GREP: its literal `\\.save\\(\\s*(str|Path|"
            "[a-z_]*path)` matches the first three characters of **`stream`** -- three false "
            "positives on clean source -- which is why the shipped test substituted a narrower "
            "one and then inherited a hole. Recorded, not edited into the spec.\n"
            "CONFIRMED AT THE LANDED COMMIT: `tests/test_import_boundaries.py` is absent from "
            "`git show --stat` and green unmodified; no `ops/` allowlist entry was added.\n"
            "ALL FOUR REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=("PENDING-LEDGER: pdf-09-ac26-shipped-save-regex-passes-the-str-and-path-bypasses"),
    ),
    ACAudit(
        ac="AC27",
        claim=(
            "`models.py` is untouched and the measured dimensions are observable. `git show "
            "--stat` does not list `src/pdf_toolkit/models.py`. Each item's `message` matches "
            "`^page \\d+: \\d+x\\d+ [a-z]+ @ [\\d.]+ dpi$`, and the width/height parsed out of it "
            "equal the dimensions Pillow reads back from the produced file -- for a `--dpi` run "
            "and for a `--width` run."
        ),
        covering=(
            "tests/unit/test_raster.py::test_ac27_models_py_has_no_rasterize_specific_field",
            "tests/unit/test_raster.py::test_ac27_message_matches_the_produced_file_for_dpi_and_width_modes",
        ),
        red=(
            "SUPERSEDED on its *`models.py` untouched* clause (PDF-21 §D3.2's closed list; the "
            "divergence is X-26), and driven red on both successor properties.\n"
            "ORIGINAL TEXT is the `claim` field above. `models.py` is no longer untouched: "
            "`PDF-10` landed the cycle-wide `ItemResult.detail` field that `decision.md` §8 X-26 "
            "ruled. SUCCESSOR PROPERTY, which the shipped test already substitutes: **no "
            "verb-shaped field exists on the shared model** -- the set of `ItemResult` fields is "
            "exact and none of them is named after a verb.\n"
            "MUTATION (a): a verb-shaped `raster_dpi: float | None` field bolted onto "
            "`models.ItemResult`.\n"
            "OBSERVED (a): `AssertionError: assert {...} == {...}` / `Extra items in the left "
            "set: 'raster_dpi'`.\n"
            "MUTATION (b): the adapter made to report PREDICTED rather than MEASURED dimensions "
            "(pdfium's pre-crop ceil size).\n"
            "OBSERVED (b): `assert (2550, 3301) == (2550, 3300)` -- the regex still MATCHED and "
            "only the COMPARISON fired, which proves the criterion measures agreement with the "
            "file rather than message format.\n"
            "CONFIRMED AT THE LANDED COMMIT: `git show --stat` lists no "
            "`src/pdf_toolkit/models.py`.\n"
            "REVERTED from the gold tree; sha256 match on both arms."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC28",
        claim=(
            "The corpus-integrity control actually controls. The `@samples` arm is run with "
            "`make samples-scratch` executed FIRST, before any verb touches anything, and `make "
            'samples-check` AFTER. Running `samples-check` with no manifest exits 1 with "no '
            'manifest" and is neither a pass nor a fail -- reporting that as a pass is the '
            "defect this criterion exists to prevent."
        ),
        covering=(
            "tests/test_samples.py::test_ac20_sample_page_1_at_72_dpi_renders_the_exact_point_pixel_size",
            "tests/test_samples.py::test_ac20_threads_1_and_threads_8_are_byte_identical_over_a_real_scan",
        ),
        red=(
            "ADVANCES, driven red by an EXTERNAL, out-of-suite control: the Makefile chain "
            "itself, run against a THROWAWAY corpus copy.\n"
            "RUN BY ITS OWN GATE, not hand-rolled: `make samples-gate` exits **0**, which "
            "subsumes the stale-manifest pre-check X-108 added, `samples-scratch` first, the "
            "present arm running, the unset arm skipping with zero passes, and `samples-check` "
            "last.\n"
            "THE FOUR-STEP CONTROL, on a `$TMPDIR` copy -- **nothing under "
            "PDF_TOOLKIT_SAMPLES_DIR was written, renamed, chmod-ed or deleted** (HC-2; X-121's "
            "precedent). (0) `samples-check` with NO manifest -> non-zero with `make "
            "samples-check: no manifest at .scratch/samples.MANIFEST.sha256 -- run 'make "
            "samples-scratch' first.` -- recorded as NEITHER a pass NOR a fail, per correction "
            "C-4. (1) `samples-scratch` -> manifest written. (2) `samples-check` on the "
            "untouched copy -> exit **0**, `originals unchanged`. (3) one byte appended to one "
            "file IN THE THROWAWAY COPY. (4) `samples-check` -> **RED**: "
            "`./catalogo_arquitectura_2017_2023_0.pdf: FAILED` / `sha256sum: WARNING: 1 computed "
            "checksum did NOT match` / `Error 1`.\n"
            "Steps (2) and (4) are the two outcomes that must differ, and they do -- which is "
            "what distinguishes this from `B-046`'s shape, where all-skipped and all-passed both "
            "exited 0."
        ),
        red_kind=RedKind.EXTERNAL_ORACLE,
    ),
)
