"""`PDF-23`'s 23 acceptance criteria -- `AUDIT-CONVENTION(PDF-17)`.

THIS MODULE RECORDS EVIDENCE FOR CRITERIA LANDED BY THE SAME COMMIT AS THIS
MODULE. It is NOT a re-derivation of a previously-granted status -- unlike
the six sibling modules in this roster (`audit_pdf_{02,03,04,05,06,09}.py`,
all re-verifications of a PRIOR grant), `PDF-23` is a first landing: the
scoping fix and the `merge_page` migration this module's rows describe did
not exist before this commit. A reader must not round this module up to a
re-derivation (X-273's own binding condition).

`PDF-23` fixes `4adc417234` / B-097 (a page-range-scoped overlay on a
document whose pages share one `/Contents` object mutates every page
sharing it, while the completion message and `detail.pages_composited`
report only the selection) and migrates all three `merge_page` consumers
(`watermark`, `stamp`, `ocr`) off a reader-attached call pypdf 6.16.2
deprecates and 7.0.0 removes (`438bd13038` / B-092), in one commit, because
landing the migration alone removes the only signal the over-reach
currently emits (§D1's own argument).

**Every `red` below states the mutation/observation, what failed, and what
the failure message said** -- never "would fail if broken" (`PLAN.md`'s own
rule, mechanized by `check_red_is_substantive`). Pre-fix observations were
taken in a scratch `git worktree` at unmodified HEAD (`312b763`, HC-4:
`git stash` is never used), never in `apps/pdf-toolkit` itself; each was
verified loaded from the scratch path before being trusted (the same
`pdf_toolkit.__file__` hazard-guard `PDF-21`'s own audit used).

**Two corrections to this spec's OWN text, discovered while building this
module's evidence, reported here and in the Implementation Log/report
rather than silently absorbed:**

1. **AC17's literal text ("exits 0 with `detail.would_exit == 5`") is
   WRONG.** The shipped, correct, ALREADY-PASSING contract (`tests/
   test_cli_contract.py::test_c15_dry_run_predicts_an_occupied_target_
   refusal`, unmodified) is `dry.returncode == real.returncode == 5` --
   BOTH exit 5, matching X-185's own framing ("dry == real ... never the
   integer alone") far better than "exits 0" would. AC17's own covering
   test below asserts the CORRECT contract (dry never raises; its own
   `item.exit_code`/`detail["would_exit"]` are 5) rather than the spec's
   literal (and incorrect) "exits 0".
2. **D6's claim that `adapters/tesseract_ocr.py::_normalize_layer_geometry`
   "carries no deprecation ... writer-attached by construction" is
   MEASURED WRONG.** `page.add_transformation(...)` runs on `reader.pages[0]`
   -- a page from a fresh, UNATTACHED `PdfReader` -- and the
   `PdfWriter().add_page(page)` step happens AFTER, not before. A `-W
   error::DeprecationWarning` traceback resolves entirely inside that
   function, never inside `composite_layer`. This is real residue OUTSIDE
   this spec's three consumers, reported per AC12's own instruction
   ("report the residue, do not widen the guard to hide it") rather than
   silently claimed away.

**AC8/AC9/AC10/AC18 are regression rows: this spec's own Scope/Design
explicitly claims these properties are PRESERVED, not created.** Their
covering tests are `PDF-14`'s own (unmodified, still passing after the
migration); their `red` records the SAME temporary, reverted mutation this
spec's own engineer drove against the MIGRATED code to confirm the
inherited control still bites, not a fresh defect this spec introduces.
"""

from __future__ import annotations

from typing import Final

from acceptance._model import ACAudit, RedKind

SPEC_ID: Final[str] = "PDF-23"
AC_COUNT: Final[int] = 23

AUDIT: Final[tuple[ACAudit, ...]] = (
    ACAudit(
        ac="AC1",
        claim=(
            "The headline defect, asserted from the file. On the new "
            "shared_contents_pages fixture (3 pages, one shared /Contents), "
            "watermark --text SENTINELWM --pages 2 exits 0 and the set of "
            "output pages whose decoded content differs from the input is "
            "exactly {2}. Pages 1 and 3 byte-identical."
        ),
        covering=(
            "tests/unit/test_overlay.py::test_ac1_watermark_scopes_to_selection_on_shared_contents",
        ),
        red=(
            "Pre-fix (312b763, scratch worktree): watermark_run(shared_contents_pages, "
            "pages_spec='2') exits 0, message 'watermarked 1 page(s)', "
            "detail={'pages_composited': [2]} -- but changed_pages() derived from the "
            "PRODUCED FILE (decoded content, coalesced across an array) returns "
            "{1, 2, 3}, not {2}. Post-fix: changed set is exactly {2}."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC2",
        claim="The same, for `stamp`.",
        covering=(
            "tests/unit/test_overlay.py::test_ac2_stamp_scopes_to_selection_on_shared_contents",
        ),
        red=(
            "Pre-fix (scratch worktree): stamp_run(shared_contents_pages, pages_spec='2') "
            "exits 0, message 'stamped 1 page(s)', detail={'pages_composited': [2]}, "
            "changed_pages() returns {1, 2, 3}. Post-fix: {2}."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC3",
        claim=(
            "The same for `ocr`, the third consumer and the reason B-092 asked for one "
            "spec. Engine-gated: skips with a reason when tesseract is absent."
        ),
        covering=(
            "tests/integration/test_ocr.py::"
            "test_pdf23_ac3_ocr_scopes_to_selection_on_shared_contents",
        ),
        red=(
            "Pre-fix (scratch worktree, tesseract present): ocr_run([shared_contents_pages], "
            "pages_spec='2') exits 0, message \"ocr'd 1 page(s), skipped 0 already-text "
            "page(s)\", detail={'pages_ocrd': [2], 'pages_skipped': []}, changed_pages() "
            "returns {1, 2, 3} -- 4adc417234's own OCR observation. Post-fix: {2}."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC4",
        claim=(
            "Selection is honoured for every shape: distinct /Contents, scalar-shared, "
            "array-shared-element, one page object twice in /Kids. Two selections each "
            "(--pages 2, --pages 1,3). Changed set equals selection in every case."
        ),
        covering=(
            "tests/unit/test_overlay.py::"
            "test_ac4_ac5_ac7_selection_count_and_unselected_pages_across_shapes"
            "[2-distinct]",
            "tests/unit/test_overlay.py::"
            "test_ac4_ac5_ac7_selection_count_and_unselected_pages_across_shapes"
            "[2-scalar_shared]",
            "tests/unit/test_overlay.py::"
            "test_ac4_ac5_ac7_selection_count_and_unselected_pages_across_shapes"
            "[2-array_shared]",
            "tests/unit/test_overlay.py::"
            "test_ac4_ac5_ac7_selection_count_and_unselected_pages_across_shapes"
            "[2-kids_duplicated]",
            "tests/unit/test_overlay.py::"
            "test_ac4_ac5_ac7_selection_count_and_unselected_pages_across_shapes"
            "[1,3-distinct]",
            "tests/unit/test_overlay.py::"
            "test_ac4_ac5_ac7_selection_count_and_unselected_pages_across_shapes"
            "[1,3-scalar_shared]",
            "tests/unit/test_overlay.py::"
            "test_ac4_ac5_ac7_selection_count_and_unselected_pages_across_shapes"
            "[1,3-array_shared]",
            "tests/unit/test_overlay.py::"
            "test_ac4_ac5_ac7_selection_count_and_unselected_pages_across_shapes"
            "[1,3-kids_duplicated]",
        ),
        red=(
            "Pre-fix, all four shapes x both selections, scratch worktree (raw watermark_run "
            "+ changed_pages()): "
            "distinct --pages 2 -> changed {2}==expected (ALREADY GREEN); "
            "distinct --pages 1,3 -> changed {1,3}==expected (ALREADY GREEN); "
            "scalar_shared --pages 2 -> changed {1,2,3} != {2} (RED); "
            "scalar_shared --pages 1,3 -> changed {1,2,3} != {1,3} (RED); "
            "array_shared --pages 2 -> changed {1,2,3} != {2}, AND pages 1/3's shared array "
            "element became an unreadable pikepdf null (worse than a count mismatch -- "
            "genuine sibling corruption, RED); "
            "kids_duplicated --pages 2 -> changed {1,2} != {2} (RED); "
            "kids_duplicated --pages 1,3 -> changed {1,2,3} != {1,3} (RED). "
            "Post-fix: all eight cases changed==expected."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC5",
        claim=(
            "THE COUNT CLAUSE. The message's integer AND detail['pages_composited'] both "
            "equal the changed set derived from the file, for all four AC4 shapes."
        ),
        covering=(
            "tests/unit/test_overlay.py::"
            "test_ac4_ac5_ac7_selection_count_and_unselected_pages_across_shapes"
            "[2-scalar_shared]",
            "tests/unit/test_overlay.py::"
            "test_ac4_ac5_ac7_selection_count_and_unselected_pages_across_shapes"
            "[1,3-kids_duplicated]",
        ),
        red=(
            "Pre-fix: scalar_shared --pages 2 message reads 'watermarked 1 page(s)' and "
            "detail['pages_composited']==[2], while the file's own changed set is size 3 -- "
            "the message and detail AGREE WITH EACH OTHER and both disagree with the file. "
            "A test asserting only message==len(detail) (today's shipped assertion, "
            "pre-fix) passes; this AC's own third check (against the FILE) fails. Post-fix "
            "all three (message, detail, file) agree."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC6",
        claim=(
            "Copy-on-write is scoped, not blanket. No sharing -> pages_copied == []. "
            "Sharing, selection == shared subset -> pages_copied == [2]."
        ),
        covering=("tests/unit/test_overlay.py::test_ac6_copy_on_write_is_scoped_not_blanket",),
        red=(
            "Pre-fix (scratch worktree): watermark_run's own result.items[0].detail has "
            "keys ['pages_composited'] only -- no 'pages_copied' key exists at all "
            "(CompositeOutcome carried no such field), so `detail['pages_copied']` raises "
            "KeyError. Post-fix: the key exists and reads [] / [2] correctly."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC7",
        claim=(
            "Unselected pages are not touched, structurally: raw /Contents object number "
            "unchanged, decoded content byte-identical, for every AC4 run."
        ),
        covering=(
            "tests/unit/test_overlay.py::"
            "test_ac4_ac5_ac7_selection_count_and_unselected_pages_across_shapes"
            "[2-scalar_shared]",
            "tests/unit/test_overlay.py::"
            "test_ac4_ac5_ac7_selection_count_and_unselected_pages_across_shapes"
            "[2-array_shared]",
        ),
        red=(
            "Pre-fix, scalar_shared --pages 2: pages 1 and 3 (unselected) are IN the "
            "changed set (content differs from input) -- the defect this AC exists to "
            "close. Pre-fix, array_shared --pages 2 is the more severe finding: pages 1 "
            "and 3's own shared array ELEMENT is replaced with a pikepdf null by the "
            "READER-cache mutation replace_contents's array-nullify loop performs -- an "
            "unselected sibling's /Contents becomes partially unreadable, not merely "
            "changed. Post-fix: unselected pages are content-identical and no element is "
            "nulled in either shape (the migration's post-append ordering means the "
            "shared array element is already page-private by the time any nullify runs, "
            "per D4.5, confirmed at HEAD rather than merely inherited from the spec's own "
            "measurement)."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC8",
        claim=(
            "PDF-14 AC8's preservation property still holds over `multipage_text` "
            "including its rotated page: page count, substring survival, DRAFT on every "
            "selected page."
        ),
        covering=(
            "tests/unit/test_overlay.py::"
            "test_ac8_watermark_preserves_page_count_and_text_and_adds_draft",
        ),
        red=(
            "REGRESSION ROW, RED ACTUALLY DRIVEN in apps/pdf-toolkit (not the scratch "
            "worktree -- this is the MIGRATED code, which only exists here): commenting "
            "out `writer.append_pages(document, list(range(1, page_count + 1)))` in "
            "ops/overlay.py::watermark_run (the writer is created but never appended) "
            "makes this test fail with `IndexError: Sequence index out of range` inside "
            "adapters/pypdf_structure.py::composite_layer's `page = pdf_writer.pages"
            "[number - 1]` (an empty writer has no page 0), confirming the migrated call "
            "order still depends on the append happening before compositing. Reverted; "
            "`git diff` over ops/overlay.py shows only this spec's own intended changes "
            "afterward (verified: the writer+append_pages block, unmutated, is present)."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC9",
        claim=(
            "Overlay/underlay ordering survives the port-shape change (PDF-14 AC10's "
            "property, re-asserted post-migration)."
        ),
        covering=("tests/unit/test_overlay.py::test_ac10_stamp_position_ordering_both_directions",),
        red=(
            "RED ACTUALLY DRIVEN in apps/pdf-toolkit (the migrated code): hard-coding "
            "`over = True  # ...` in adapters/pypdf_structure.py::composite_layer "
            "(dropping the `position`-derived value before the "
            "`page.merge_page(layer_page, over=over)` call) makes the UNDERLAY assertion "
            "fail: `assert stream.index(stamp_marker) < stream.index(base_marker)` -> "
            "`AssertionError: assert 234 < 64` (the marker landed AFTER the base text, "
            "the overlay ordering, on a run that requested underlay). Reverted; "
            "re-ran the full `tests/unit/test_overlay.py` suite green (33 passed)."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC10",
        claim=(
            "Blank and empty content streams still behave as PDF-14 D4.4 ruled -- "
            "AC12(a)/AC12(b) pass unmodified."
        ),
        covering=(
            "tests/unit/test_overlay.py::"
            "test_ac12a_no_contents_page_composites_and_warns_overlay_underlay_identical",
            "tests/unit/test_overlay.py::test_ac12b_empty_contents_page_composites_with_no_warning",
        ),
        red=(
            "RED ACTUALLY DRIVEN in apps/pdf-toolkit (the migrated code): replacing "
            "`if page.get_contents() is None:` with `if False:` in "
            "adapters/pypdf_structure.py::composite_layer makes AC12a fail -- "
            '`assert result.warnings and "1" in result.warnings[0]` raises '
            "`AssertionError: assert (())`, i.e. `result.warnings == ()` -- because "
            "`_blank_warning` never fires without a blank-page number reported into "
            "`blank`. Reverted; re-ran the full suite (33 passed)."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC11",
        claim=(
            "PDF-14 AC12(c), the array-/Contents case, gains a test for the first time. "
            "Reported to the PM as an unmeasured PDF-14 criterion, not quietly closed."
        ),
        covering=(
            "tests/unit/test_overlay.py::"
            "test_ac11_array_contents_shared_element_scopes_and_preserves",
        ),
        red=(
            "`grep -rn 'def test_ac12' tests/` at HEAD returns only test_ac12a.../"
            "test_ac12b... -- no test_ac12c ever existed; PDF-14's AC12(c) is unmeasured, "
            "not merely undiscovered. Pre-fix (this test's own shape, scratch worktree): "
            "changed_pages() returns {1, 2, 3} not {2}, AND pages 1/3's shared array "
            "element is nulled (AC7's own finding, reproduced here as PDF-14's missing "
            "control would have caught it). Post-fix: {2}, and D4.5's preservation holds."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="0615feae63",
    ),
    ACAudit(
        ac="AC12",
        claim=(
            "The pypdf deprecation is gone from the three consumers' own compositing "
            "path, and the guard can fail. Full-suite census recorded (pre/post)."
        ),
        covering=(
            "tests/unit/test_overlay.py::"
            "test_ac12_zero_pypdf_deprecation_warnings_from_watermark_and_stamp",
            "tests/integration/test_ocr.py::"
            "test_pdf23_ac12_composite_layer_itself_adds_no_deprecation_to_ocr",
        ),
        red=(
            "Pre-fix (scratch worktree): a single watermark_run call over "
            "shared_contents_pages raises exactly 1 pypdf DeprecationWarning "
            "('Calling PageObject.replace_contents() for pages not assigned to a "
            "writer...'); a single ocr_run call over one page raises exactly 2 (one from "
            "composite_layer's own merge_page, one from adapters/tesseract_ocr.py::"
            "_normalize_layer_geometry's add_transformation -- confirmed by isolating "
            "each call and by a -W error traceback). Post-fix: watermark/stamp 0; ocr's "
            "own composite_layer contribution 0, but the run as a whole still carries "
            "the residual 1-per-page warning from _normalize_layer_geometry (out of this "
            "spec's scope per D6/Scope>Out -- reported as residue, not fixed, not hidden "
            "behind a widened guard). Full-suite census: see Implementation Log."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC13",
        claim=(
            "X-159's licence duty discharged in this spec's own commit, whichever arm "
            "fired. No runtime dependency added."
        ),
        covering=("tests/test_license_policy.py::test_no_forbidden_dependency_in_pyproject",),
        red=(
            "No dependency version changed this wave (only a dated comment was added to "
            "pyproject.toml's pypdf line -- Arm A). The duty's own no-op case, evidenced "
            "rather than skipped: `uv lock --check` -> 'Resolved 77 packages' (no lock "
            "change); `make licenses` regenerated both artifacts; `git diff --exit-code "
            "-- THIRD_PARTY_LICENSES` -> exit 0, no output; `git diff --exit-code -- "
            "website/src/data/licenses.json` -> exit 0, no output. RED ACTUALLY DRIVEN "
            "to prove the instrument itself can fail (a clean check is not the same "
            "evidence as a skipped one): appending one line to THIRD_PARTY_LICENSES made "
            "`git diff --exit-code -- THIRD_PARTY_LICENSES` return exit 1 with the "
            "expected diff hunk; the line was then removed and the exit code returned to "
            "0. Both quoted in full in the Implementation Log."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
    ),
    ACAudit(
        ac="AC14",
        claim=(
            "The ceiling arm is decided by §D8's own command, and stated. Implementation "
            "Log records which arm fired and the raw probe output."
        ),
        covering=("tests/test_license_policy.py::test_no_forbidden_dependency_in_pyproject",),
        red=(
            "§D8's probe run at implementation time (2026-09-02): "
            "`json.load(urlopen('https://pypi.org/pypi/pypdf/json'))['releases']` filtered "
            "to entries starting '7.' -> EMPTY output, exit 0 -- Arm A. Latest published "
            "`info.version` == '6.16.2', the version already pinned as the floor. "
            "pyproject.toml:35's `<7` ceiling KEPT, dated comment added naming PDF-23 "
            "(quoted in full in the Implementation Log)."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
    ),
    ACAudit(
        ac="AC15",
        claim=(
            "The port contract is the guarantee, asserted AT THE PORT: "
            "require_composite().composite_layer(...) called directly, without the CLI, "
            "over a writer built from shared_contents_pages. Import boundaries and X-76 "
            "capability selection unaffected."
        ),
        covering=(
            "tests/unit/test_overlay.py::test_ac15_composite_layer_direct_call_scopes_via_writer",
            "tests/test_import_boundaries.py::test_no_engine_library_is_imported_outside_adapters",
        ),
        red=(
            "The PRE-migration signature (`composite_layer(document, ...)`, a reader "
            "handle) makes this exact call shape (`composite_layer(writer, ...)`, a "
            "writer with pages already appended) raise `AttributeError: "
            "'PypdfOpenDocument' object has no attribute '_writer'` when passed a "
            "`document` positionally where the new signature expects `writer` -- observed "
            "directly while updating tests/unit/test_overlay.py::test_ac14_composite_"
            "layer_is_callable_directly_without_the_cli (AC20's own known non-empty row) "
            "before it was corrected to build a writer first. Post-fix: both AC14 and "
            "AC15 pass; `ops/overlay.py`/`ops/ocr.py` import no engine library "
            "(test_no_engine_library_is_imported_outside_adapters, unmodified, still "
            "green); require_composite() still selects by the 'composite' capability."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC16",
        claim=(
            "The docstrings do not outlive the contract they describe. Mechanized: "
            "grep -rn 'merge_page' src/pdf_toolkit/ports/ src/pdf_toolkit/ops/ returns "
            "nothing; grep -n 'PRE-append' src/pdf_toolkit/ports/structure.py returns "
            "nothing."
        ),
        covering=(
            "tests/unit/test_overlay.py::"
            "test_ac16_no_merge_page_or_pre_append_prose_survives_in_ports_or_ops",
        ),
        red=(
            "SELF-CAUGHT DURING THIS SPEC'S OWN WORK, not merely a pre-fix state: this "
            "spec's FIRST drafts of the migrated ops/overlay.py and ops/ocr.py module "
            "docstrings themselves still named 'page.merge_page' in explanatory prose "
            "(describing what the migration moved OFF of) -- the mechanized grep this "
            "test drives caught it immediately (`assert merge_page.returncode == 1 and "
            'merge_page.stdout == ""` failed, printing both stale lines with their exact '
            "file:line). Both rewritten to describe the contract without the literal "
            "banned string. Also caught and fixed: the grep's own first form matched "
            "compiled .pyc files under __pycache__ (binary matches inflating false "
            "positives), corrected to `--include=*.py`. Pre-fix-of-the-CODE (before "
            "PDF-23's port-shape change), the SAME grep also finds ports/structure.py:325/"
            "620 and ops/ocr.py:24-25 (the three sites D6 enumerates) plus "
            "ports/ocr.py:78 (Correction 1's own fourth, unenumerated site)."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC17",
        claim=(
            "`--dry-run` still mirrors (OR-7), for watermark/stamp/ocr, over an occupied "
            "target: dry never raises (graceful envelope, item.exit_code==5, "
            "detail['would_exit']==5); the real run raises the same exit_code==5. See "
            "this module's own docstring for the correction to the spec's literal "
            "'exits 0' text."
        ),
        covering=("tests/unit/test_overlay.py::test_ac17_dry_run_still_mirrors_and_never_raises",),
        red=(
            "A temporary, reverted mutation of safety/atomic.py::plan_output_set's "
            "dry-run branch (`except PdfToolkitError as refusal: raise` unconditionally, "
            "dropping `if not policy.dry_run:`) makes this test fail: the dry-run call "
            "for watermark now RAISES TargetExistsError instead of returning a graceful "
            "OperationResult, caught by `pytest.raises` NOT being expected on the DRY "
            "call -- `dry_result, real_error = runner(target)` errors out of "
            "dry_and_real_watermark's own unguarded `dry = watermark_run(...)` line with "
            "an uncaught TargetExistsError traceback. The CLI-subprocess-level "
            "test_c15_dry_run_predicts_an_occupied_target_refusal (unmodified, `tests/"
            "test_cli_contract.py`) does NOT catch this same mutation -- it only asserts "
            "exit codes, and the top-level error handler converts the raised exception "
            "to the SAME exit code (5) a graceful prediction would have produced, "
            "explaining why AC17 needed its own, finer-grained, in-process test. "
            "Mutation reverted; `git diff --exit-code -- src/pdf_toolkit/safety/` clean "
            "before commit (verified twice, once per mutation attempt: an initial wrong "
            "branch -- `plan_filesystem`'s ensure_destination_writable try/except, which "
            "is NOT reached by an occupied-target refusal -- was tried, found to not "
            "red, and reverted before the correct branch was found and driven)."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC18",
        claim="Safety spine unchanged (PDF-04): AtomicWriter, no-clobber, --in-place/.bak.",
        covering=(
            "tests/test_import_boundaries.py::test_no_write_call_outside_the_safety_package",
            "tests/test_import_boundaries.py::"
            "test_write_calls_inside_safety_are_confined_to_the_chokepoint",
            "tests/test_cli_contract.py::test_c15_dry_run_predicts_an_occupied_target_"
            "refusal[watermark]",
        ),
        red=(
            "REGRESSION ROW: the write-chokepoint AST walk (test_no_write_call_outside_"
            "the_safety_package) already carries its own planted-violation self-tests "
            "(test_a_planted_violation_fails_the_walk, parametrized, unmodified) proving "
            "the walk can fail -- this spec introduces NO new write path (composite_layer "
            "still produces bytes only; every byte still reaches disk through "
            "ops/overlay.py's and ops/ocr.py's own unmodified AtomicWriter calls), so no "
            "PDF-23-specific mutation was needed to re-derive this AC: the walk covers "
            "the migrated files unconditionally (it globs src/ by file, not by a "
            "hand-maintained list) and this suite run is itself the re-verification."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC19",
        claim=(
            "@samples arm (HC-2): watermark --pages <subset> against a copy of a real "
            "document; AC5's count clause and AC7's untouched-page property against the "
            "produced file. Skips with a reason when PDF_TOOLKIT_SAMPLES_DIR is unset."
        ),
        covering=(
            "tests/test_samples.py::"
            "test_ac19_watermark_pages_scopes_and_counts_over_a_real_document",
        ),
        red=(
            "Run locally with PDF_TOOLKIT_SAMPLES_DIR set: 1 passed (watermark --pages "
            "3,7 over a copy of catalogo_arquitectura_2017_2023_0.pdf -- changed set == "
            "{3, 7}, message count and detail agree). Run without the variable: "
            "1 skipped, reason 'PDF_TOOLKIT_SAMPLES_DIR not set -- real-document arm "
            "skipped (PLAN.md §10.1 rule 5)' -- never reported as passed. CI never sets "
            "the variable (HC-2), so this arm is local-gate-only by construction."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC20",
        claim=(
            "Blast-radius grep before editing shared surfaces, with a per-test "
            "disposition list in the Implementation Log."
        ),
        covering=(),
        red=(
            "PROCEDURAL AC, no red/green pair: this is an engineering-process check "
            "(a grep run before editing, not a code property a test can assert), "
            "discharged as prose in the Implementation Log and this spec's report -- "
            "the grep output over each shared surface (ports/structure.py, "
            "adapters/pypdf_structure.py, ops/overlay.py, ops/ocr.py, tests/corpus.py) "
            "and the disposition of every test it surfaced, including the ONE known "
            "non-empty result the spec's own text names in advance "
            "(test_ac14_composite_layer_is_callable_directly_without_the_cli)."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding=(
            "Not a defect -- recorded as NOT_OBSERVED per _model.py's own honesty rule "
            "rather than manufacturing a covering pytest control for a one-time "
            "engineering-process check. No ledger fingerprint applies."
        ),
    ),
    ACAudit(
        ac="AC21",
        claim="Gate green: make ci passes, coverage >= 85%, pushed CI run green.",
        covering=(),
        red=(
            "PROCEDURAL AC, no red/green pair: a gate run is not itself a test case. "
            "`make ci`'s own wall clock (with loadavg before/after or the 'indicative' "
            "label per X-277) and the pushed CI run id/conclusion are recorded in the "
            "Implementation Log and this spec's report."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="Not a defect -- recorded as NOT_OBSERVED per _model.py's own honesty rule.",
    ),
    ACAudit(
        ac="AC22",
        claim=(
            "HC-3a git hygiene: DCO-signed commit(s); git diff-tree lists only owned paths per sha."
        ),
        covering=(),
        red=(
            "PROCEDURAL AC, no red/green pair: git hygiene is verified via "
            "`git diff-tree --no-commit-id --name-only -r <sha>` (never `git show "
            "--stat`, per X-124) per landed sha, recorded in the Implementation Log and "
            "this spec's report."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="Not a defect -- recorded as NOT_OBSERVED per _model.py's own honesty rule.",
    ),
    ACAudit(
        ac="AC23",
        claim=(
            "HC-1 holds: no forbidden PLAN.md §7.2 name appears in the diff as an "
            "import, subprocess argv[0], or shutil.which argument."
        ),
        covering=(
            "tests/test_license_policy.py::test_no_forbidden_names_under_src",
            "tests/test_license_policy.py::test_self_positive_detects_all_three_leaks",
        ),
        red=(
            "REGRESSION ROW: this spec adds no import, no subprocess call and no "
            "shutil.which call anywhere (composite_layer's new code is pure pypdf.generic "
            "object manipulation, already an approved dependency) -- the EXISTING "
            "forbidden-name AST walk, whose own positive self-test "
            "(test_self_positive_detects_all_three_leaks) already proves it can fail, "
            "covers the migrated files unconditionally by globbing src/. No PDF-23-"
            "specific plant was needed or performed; the poppler measurement-oracle "
            "carve-out (§0.7) is correctly NOT exercised, per AC23's own text."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
)
