"""`PDF-82`'s 27 acceptance criteria, re-derived -- `AUDIT-CONVENTION(PDF-17)`.

`PDF-82` ("Unblock the engines-absent gate, and retire the excuse that hid it",
landed `52ec164`) reads `Implemented (2026-09-16)` and has never held a
`Verified`. This module is the evidence for that first grant or refusal. The
auditing spec is `PDF-106` (roadmap `R-05`, PM ruling `X-962`, dispatch C); the
audited spec is `PDF-82`.

**Independence (R-05, binding).** The author of this module did not implement
`PDF-82`: it is a fresh dispatch that never held the spec's context. The audited
spec's Implementation Log was not used as evidence; the spec text supplied the
AC wording and nothing else, and every red below was re-driven by this author in
a private scratch worktree at the audit base `119f47e`.

The qa-sentinel grants or refuses; this module does not.

**Taken at the audit base `119f47e`, not at the landing commit.** Covering arms
have moved since `52ec164`: `tests/test_engine_gating_census.py`'s ledger now
holds four records (PDF-82 genesis, PDF-84, PDF-89, PDF-96) and its ceilings
moved with them. Every `covering` id was copy-pasted from a real
`pytest --collect-only -q` at that base.

**Per-class counts: 27 criteria = 10 locally driven + 2 covered-red-NOT-observed
+ 12 command-evidenced + 3 UNREDDENABLE + 0 CI-evidenced.**

* **locally driven** -- AC9, AC13, AC14, AC15, AC16, AC17, AC19, AC21, AC25,
  AC26. Each `red` names the file:line mutated, the failure line seen, the
  revert and the base sha. AC13, AC19, AC21 and AC25 also carry a `finding` for
  the half of the claim the mutation did not red.
* **covered, red NOT observed** -- AC11 and AC18 (`NOT_OBSERVED` + finding). The
  covering arms stayed green when the thing the AC pins was removed or moved.
* **COMMAND:** -- AC2, AC4, AC5, AC6, AC7, AC8, AC10, AC12, AC20, AC22, AC23,
  AC24. Evidence is a re-runnable command. AC6, AC8, AC12 and AC24 carry a
  `COMMAND-RED:` marker (command, scratch plant, failure line); the other eight
  are `NOT_OBSERVED` with a finding.
* **UNREDDENABLE:** -- AC1, AC3 and AC27; reasons below.

**UNREDDENABLE rows (3).**

* **AC1** -- a PRE-EDIT measurement: the nineteen failing arms in three files no
  longer exist at the audit base, because the audited spec's own fix removed
  them. No mutation restores the premise short of reverting `52ec164`. Its
  post-fix successor is AC6.
* **AC3** -- the same: "125 callspec-derived arms with 0 marked" is a pre-fix
  census and is false by construction after the eighteen marks landed. The part
  that still re-derives (`engine_blind_verbs() == ('convert', 'ocr')`) is
  recorded in the row; the surviving structure is graded by AC15 and AC16.
* **AC27** -- "the three filed items of D9 are reported to the project-manager
  by name". It is a hand-up, not an artifact; nothing in the product holds it.

**E7 positions, confirmed or overturned.** Confirmed: AC1, AC3, AC27
(UNREDDENABLE). Overturned: **AC2** (E7 said process; it re-drives at the base
-- E3 and E4 both reproduce -- so it is COMMAND), **AC4** (the four residues and
the read-seam ceiling are re-derivable now and are still 29 / 7 / 6 / 127 and
1), **AC20** (the fallback choice is evidenced by an empty `git show --stat
52ec164 -- scripts/gate_parity.py`), **AC19** (E7 called it host-limited; its
pointer half has a standing arm and a driven red, only the full-suite half is
host-limited), **AC24** (not host-limited: `make docs-gate` hides the engines
itself, so it runs here, and it carries a driven command-level red). AC22 and
AC23 were decided COMMAND rather than UNREDDENABLE because `git show --stat` is
a re-runnable, answerable question; no machine red is possible without
rewriting history.

**Host facts, recorded.** `command -v tesseract soffice` prints only
`/usr/bin/soffice` (tesseract is ABSENT, `command -v` rc 1), so
`make engines-gate` arm 1 refuses on this host. Arm 2 alone was driven on a
20-id subset, not as a full suite run (see AC5). `make verify` runs the covering
ids WITHOUT the engine-hiding shim, so the absence-dependent criteria (AC6, AC10)
cannot be evidenced by the runner's green; they are COMMAND rows for that
reason.

Mutation method: edit one line in the scratch worktree, run the named node ids
with `uv run pytest <ids> -n 0` (or `-n 2`), record the failure line, restore
the file from `git show HEAD:<path>` and prove the restore with
`git diff --exit-code`. Findings are `PENDING-LEDGER:` slugs for the sentinel to
mint; this module writes neither the ledger nor the backlog.
"""

from __future__ import annotations

from typing import Final

from acceptance._model import ACAudit, RedKind

SPEC_ID: Final[str] = "PDF-82"
AC_COUNT: Final[int] = 27

AUDIT: Final[tuple[ACAudit, ...]] = (
    ACAudit(
        ac="AC1",
        claim=(
            "AC1 -- The engineer re-derives the population by E1's subtraction in its "
            "own out-of-tree copy and records both figures: the hidden arm's failure "
            "set, the engines-present control's failure set, `comm -13` returning 0 "
            "(strict subset) and `comm -23` returning 19, in the three files at 15 / 2 "
            "/ 2. A different answer is reported to the project-manager before any "
            "edit, never adjusted for."
        ),
        covering=(),
        red=(
            "UNREDDENABLE: a PRE-EDIT measurement of a population (nineteen failing "
            "arms in three files) that the audited spec's own fix removed by design. At "
            "the audit base 119f47e the premise no longer exists and no mutation can "
            "restore it short of reverting commit 52ec164. Its post-fix successor is "
            "AC6 (the subtraction re-run is empty), audited there. Re-deriving it means "
            "two full-suite runs of about eleven minutes each in a worktree at 3aedef8; "
            "that was NOT run here, because it re-measures history rather than the "
            "product."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-82-ac1-ac3-premise-measurements-have-no-standing-control",
    ),
    ACAudit(
        ac="AC2",
        claim=(
            "AC2 -- The engineer re-drives E3 and E4 against the unmodified console "
            "script and records rc, the presence or absence of an `items` array, and "
            "the four byte-identical envelopes of `convert-output-nonexistent-parent`. "
            "E4 is the one to check hardest."
        ),
        covering=(),
        red=(
            "COMMAND: re-driven at base 119f47e (src/ is untouched by 52ec164, so the "
            "console script is the pre-fix one) with `.venv/bin/pdftooling` from the "
            "scratch worktree. The engine-less environment is a PATH made of a symlink "
            "farm holding every executable on PATH except soffice/tesseract/libreoffice "
            "(`command -v soffice tesseract` under it finds neither). (1) `convert "
            "conv.txt -O out.docx --dry-run -o json` engine-less -> rc 3, "
            '`{"schema_version": 1, "error": {"code": 3, "kind": "engine_missing", ..., '
            '"path": null}}` with NO `items` array; engines present -> rc 0 with an '
            "`items` array. (2) E4: `convert conv.txt -O missingdir/out.pdf`, dry and "
            "real, engines present and engine-less -> rc 1 in all four; the dry pair is "
            "byte-identical (`cmp` clean, 512 bytes each) and so is the real pair (148 "
            'bytes each). E3 and E4 both reproduce, including `"path": null`. No red is '
            "recorded: the byte-identity is asserted by no standing byte compare, since "
            "the nonexistent-parent cell passes in both configurations through derived "
            "oracles only."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-82-ac2-e4-byte-identity-has-no-standing-byte-compare",
    ),
    ACAudit(
        ac="AC3",
        claim=(
            "AC3 -- The E6 collection census is re-run and returns "
            "`engine_blind_verbs() == ('convert', 'ocr')`, a callspec-derived "
            "population of 125 with 0 marked, and neither `tests/test_read_seams.py` "
            "arm among them."
        ),
        covering=(),
        red=(
            "UNREDDENABLE: a PRE-EDIT census. '125 members, 0 marked' is false at the "
            "audit base by construction, because the audited spec marked eighteen arms "
            "(measured: `pytest --collect-only -m requires` over the three files lists "
            "15 + 2 + 1 = 18), and the zip-claim arm in tests/test_read_seams.py is now "
            "an explicit member of the census rather than an exclusion. The part that "
            "still re-derives does: `registry.engine_blind_verbs()` returns ('convert', "
            "'ocr') at 119f47e. The surviving structure (both detectors, the helper "
            "limb) is graded by AC15 and AC16."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-82-ac1-ac3-premise-measurements-have-no-standing-control",
    ),
    ACAudit(
        ac="AC4",
        claim=(
            "AC4 -- The four guarded-document residues are re-derived as 29 / 7 / 6 / "
            "127 with headroom 0, and `tests/test_read_seams.py`'s ceiling for "
            "`pdf_tooling/adapters/soffice_office.py` as 1 with a one-record ledger, "
            "before the first edit."
        ),
        covering=(),
        red=(
            "COMMAND: at base 119f47e in the scratch worktree, a script importing "
            "tests/test_docs_antirot.py and tests/test_read_seams.py printed README.md "
            "residue 29 / ceiling 29, CLAUDE.md 7 / 7, CONTRIBUTING.md 6 / 6, "
            "TESTING.md 127 / 127 (headroom 0 on all four); docs ledger holds 2 records "
            "(PDF-30, PDF-67: the audited spec added none); read-seam RESIDUE_CEILING "
            "for pdf_tooling/adapters/soffice_office.py is 1 with a ONE-record ledger "
            "(PDF-63). All four figures are still the figures AC4 states. No red "
            "recorded: editing the genesis record's value in place "
            "(tests/test_read_seams.py:220, 1 -> 2) left every tests/test_read_seams.py "
            "arm green (see AC11), so the pre-edit figure is guarded only against "
            "growth by a successor record, never against an in-place edit."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-82-ac4-ac11-genesis-record-edit-in-place-is-green",
    ),
    ACAudit(
        ac="AC5",
        claim=(
            "AC5 -- `make engines-gate` exits 0 on both arms on an engine-ful host, and "
            "`make engines-hidden` exits 0 on a host with the engines stripped from "
            "`PATH`. Both are run, and both outputs are recorded."
        ),
        covering=(),
        red=(
            "COMMAND: HOST-LIMITED, driven as far as this host allows. `command -v "
            "tesseract soffice` -> only /usr/bin/soffice (tesseract ABSENT, rc 1). "
            "`make engines-gate` in the scratch worktree -> `make engines-gate: "
            "REFUSING arm 1 (engines present) -- tesseract not on PATH.` and make rc 2 "
            "(make collapses the recipe's 1 to 2); with PATH reduced to the symlink "
            "farm lacking both binaries -> `-- tesseract soffice not on PATH.`, rc 2. "
            "So arm 1 cannot run here. Arm 2 alone (`make engines-hidden`) was NOT run "
            "as a full suite (a whole-suite run, about eleven minutes at -n auto, on a "
            "shared host); its 20-id subset (the eighteen gated arms, the sixteenth "
            "cell and the read-seams AC5 arm) under "
            "PDF_TOOLING_TEST_HIDE_ENGINES=tesseract,soffice gave 1 passed, 19 skipped, "
            "and scripts/assert_skips.py rc 0 (engine-gated skips: 19, 0 failures, 0 "
            "errors). The two-arm exit 0 is therefore NOT evidenced here."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-82-ac5-engines-gate-needs-an-engine-ful-host",
    ),
    ACAudit(
        ac="AC6",
        claim=(
            "AC6 -- Under the shim, the suite's engine-attributable failure count is 0: "
            "E1's subtraction re-run after the fix returns an empty `comm -23`. The "
            "remaining failures, if any, are shown to be present in the engines-present "
            "control too."
        ),
        covering=(),
        red=(
            "COMMAND: COMMAND-RED: PDF_TOOLING_TEST_HIDE_ENGINES=tesseract,soffice uv "
            "run pytest <the 20 ids: sixteen value-shape cells (fifteen gated plus the "
            "sixteenth), two derived-dimension axis arms, the zip-claim arm and "
            "read-seams AC5> -n 2 | plant: tests/registry.py:2965 `return "
            "ENGINE_MARKER_SPELLINGS[port]` -> `return None`, so every per-cell mark "
            "vanishes (scratch worktree, base 119f47e) | saw: `17 failed, 1 passed, 2 "
            "skipped`, e.g. FAILED "
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-out-dir-tilde]"
            " and FAILED "
            "tests/test_derived_dimensions.py::test_the_value_shape_axis_still_changes_the_products_answer[convert-output];"
            " the 17 are E1's 15 + 2. Unplanted, the same command gives `1 passed, 19 "
            "skipped` and assert_skips rc 0. Reverted with `git show "
            "HEAD:tests/registry.py > tests/registry.py`; `git diff --exit-code` "
            "returned 0. NOT evidenced by the runner: `make verify` runs without the "
            "shim, so these arms pass trivially there (soffice is present). The "
            "full-suite `comm -23` was not re-run."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-82-verify-has-no-shim-so-absence-acs-need-engines-hidden",
    ),
    ACAudit(
        ac="AC7",
        claim=(
            "AC7 -- `scripts/assert_skips.py junit-without-engines.xml` exits 0 and "
            "reports an engine-gated skip count greater than E11's measured 90, with "
            "the new skips landing in the `engine-gated` class and the `unclassified` "
            "remainder not growing past 7."
        ),
        covering=(),
        red=(
            "COMMAND: `uv run python scripts/assert_skips.py <junit of the 20-id subset "
            "run under PDF_TOOLING_TEST_HIDE_ENGINES=tesseract,soffice>` -> rc 0, "
            "`engine-gated skips: 19`, `unclassified: 0`, `scanned 20 testcases, 0 "
            "failures, 0 errors`: the new skips land in the `engine-gated` class and "
            "none in the remainder. The AC's figures are FULL-SUITE ones (greater than "
            "90, unclassified at most 7) and were NOT re-derived (they need the whole "
            "suite under the shim). No red recorded."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-82-ac7-full-suite-skip-census-not-re-derived",
    ),
    ACAudit(
        ac="AC8",
        claim=(
            "AC8 -- `scripts/assert_skips.py junit-engines-present.xml --expect-zero` "
            "exits 0 with an engine-gated skip count of 0 -- the half of `:527-530`'s "
            "claim that was true stays true."
        ),
        covering=(),
        red=(
            "COMMAND: COMMAND-RED: uv run pytest <the 20-id subset> -n 2 --junitxml=J; "
            "uv run python scripts/assert_skips.py J --expect-zero, engines present -> "
            "`20 passed`, `engine-gated skips: 0`, rc 0 | plant: the same 20 ids run "
            "under PDF_TOOLING_TEST_HIDE_ENGINES=tesseract,soffice, then "
            "`--expect-zero` applied to that junit (scratch worktree, base 119f47e; no "
            "file edited) | saw: `assert_skips: 19 engine-gated skip(s) with engines "
            "INSTALLED -- a test that should have exercised a real engine silently did "
            "not.` rc 1. The subset stands in for the full-suite figure, which was not "
            "re-run."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
        finding="PENDING-LEDGER: pdf-82-ac8-expect-zero-full-suite-figure-only-subset-run",
    ),
    ACAudit(
        ac="AC9",
        claim=(
            'AC9 -- Exactly eighteen arms gain `@pytest.mark.requires("soffice")`, and '
            "each one's node id is in AC1's measured set. The marks ride the "
            "parametrize for the seventeen cell-level arms and are not a typed list of "
            "node ids."
        ),
        covering=(
            "tests/test_engine_gating_census.py::test_the_ungated_engine_blind_drive_count_does_not_grow_per_module",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-out-dir-absolute]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-out-dir-bare-relative]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-out-dir-dot-relative]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-out-dir-parent-relative]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-out-dir-trailing-slash]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-out-dir-tilde]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-out-dir-symlink]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-out-dir-nonexistent-parent]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-output-absolute]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-output-bare-relative]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-output-dot-relative]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-output-parent-relative]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-output-trailing-slash]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-output-tilde]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-output-symlink]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[convert-output-nonexistent-parent]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[ocr-out-dir-absolute]",
            "tests/integration/test_value_shape.py::test_the_value_shape_cell_holds[ocr-output-absolute]",
            "tests/test_derived_dimensions.py::test_the_value_shape_axis_still_changes_the_products_answer[convert-out-dir]",
            "tests/test_derived_dimensions.py::test_the_value_shape_axis_still_changes_the_products_answer[convert-output]",
            "tests/test_derived_dimensions.py::test_the_value_shape_axis_still_changes_the_products_answer[ocr-out-dir]",
            "tests/test_derived_dimensions.py::test_the_value_shape_axis_still_changes_the_products_answer[ocr-output]",
            "tests/test_read_seams.py::test_convert_zip_claim_branch_and_the_oserror_catch_reachability",
        ),
        red=(
            "Mutated tests/registry.py:2965 (`return ENGINE_MARKER_SPELLINGS[port]` -> "
            "`return None`, so `destination_cell_engine` stops marking any cell) in a "
            "private scratch worktree at base 119f47e. `uv run pytest <the 24 covering "
            "ids> -n 2` -> 1 failed, 23 passed: `AssertionError: ungated engine-blind "
            "drives grew past their frozen ceiling {module: (now, ceiling)}: "
            "{'tests/integration/test_value_shape.py': (18, 17), "
            "'tests/test_derived_dimensions.py': (4, 2)}` from "
            "tests/test_engine_gating_census.py:718, naming both modules and the nodes. "
            "The covering set is chosen so the ratchet has enough ungated members to "
            "cross each ceiling (it only reds on GROWTH, so a smaller selection stays "
            "green). Confirmed by `pytest --collect-only -m requires` over the three "
            "files: exactly 15 + 2 + 1 = 18 marked, and "
            "convert-output-nonexistent-parent is not among them. Reverted with `git "
            "show HEAD:tests/registry.py > tests/registry.py`; `git diff --exit-code` "
            "returned 0. Every mutation in this row was made in a private detached "
            "scratch worktree at base 119f47e, never in the shared worktree."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC10",
        claim=(
            "AC10 -- `convert-output-nonexistent-parent` is NOT marked, and after the "
            "fix it still passes under the shim. This is the criterion that "
            "distinguishes a gated suite from a silenced one."
        ),
        covering=(),
        red=(
            "COMMAND: PDF_TOOLING_TEST_HIDE_ENGINES=tesseract,soffice uv run pytest "
            "<20-id subset> -n 2 -> 1 passed, 19 skipped, and the 1 passed is "
            "`test_the_value_shape_cell_holds[convert-output-nonexistent-parent]`: the "
            "AC is TRUE at base. Over-marking plant (scratch worktree, base 119f47e): "
            'tests/registry.py:2939 `{("convert", "--output", "nonexistent-parent")}` '
            "-> `set()` under the same shim -> `20 skipped`, pytest rc 0. The cell "
            "silently stopped running and NOTHING went red: the census ratchet reds "
            "only on growth, never on shrinkage, and assert_skips merely counts one "
            "more engine-gated skip. D2's own asymmetry table predicts exactly this, "
            "which is why this row has no red. Reverted with `git show "
            "HEAD:tests/registry.py > tests/registry.py`; `git diff --exit-code` "
            "returned 0."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-82-ac10-over-marking-the-sixteenth-cell-reds-nothing",
    ),
    ACAudit(
        ac="AC11",
        claim=(
            "AC11 -- `tests/test_read_seams.py::test_ac5_...ceiling_that_may_not_grow` "
            "carries no `requires` marker, skips visibly under absence with a reason "
            "naming the engine and the undriven cell, and passes normally under engines "
            "present. That module's `RESIDUE_CEILING` entry for the adapter is "
            "unchanged at 1 and its ratification ledger still has one record."
        ),
        covering=(
            "tests/test_read_seams.py::test_ac5_the_undriven_residue_is_counted_against_a_ceiling_that_may_not_grow",
            "tests/test_read_seams.py::test_the_read_seam_ceiling_is_the_newest_ledger_record_not_a_writable_literal",
            "tests/test_read_seams.py::test_x715s_reasoning_survives_the_refactor_onto_the_genesis_record",
            "tests/test_engine_gating_census.py::test_the_helper_limb_reaches_a_gated_arm_the_callspec_walk_cannot_see",
            "tests/test_engine_gating_census.py::test_the_helper_reached_gated_arms_are_in_the_population_when_they_are_collected",
            "tests/test_engine_gating_census.py::test_the_walk_is_not_vacuous",
            "tests/test_engine_gating_census.py::test_the_ungated_engine_blind_drive_count_does_not_grow_per_module",
            "tests/test_read_seams.py::test_convert_zip_claim_branch_and_the_oserror_catch_reachability",
        ),
        red=(
            "THREE halves, one red. (1) SKIP-VISIBLE half: RED OBSERVED, but only under "
            "the shim, which the runner does not apply. SHIM=tesseract,soffice, "
            "tests/test_read_seams.py:807 (`_skip_if_a_cell_never_drove(sweeps)` call "
            "deleted): `AssertionError: undriven read seams grew past their frozen "
            "ceiling {module: (now, ceiling)}: "
            "{'pdf_tooling/adapters/soffice_office.py': (2, 1)}`; unmutated under the "
            "shim the arm SKIPS with `soffice unavailable: the 'convert/office-dry' "
            "cell's un-raced control refused with exit 3 (engine_missing)...`. (2) "
            "NO-MARKER half: tests/test_read_seams.py:782 a "
            '`@pytest.mark.requires("soffice")` added to the arm -> `8 passed`; the '
            "docstring's claim that a marker there would red the census's fitness is "
            "FALSE, the census only reds for arms it can see and this one is in no "
            "population. (3) CEILING half: tests/test_read_seams.py:220 "
            '`"pdf_tooling/adapters/soffice_office.py": 1` -> 2 -> `8 passed`; an '
            "in-place edit of the genesis record reds nothing. Presence half: the "
            "unmutated arm passes with soffice present. Mutations (2) and (3) were "
            "driven against the 8 covering ids. Each reverted with `git show "
            "HEAD:tests/test_read_seams.py > tests/test_read_seams.py`; `git diff "
            "--exit-code` returned 0 (base 119f47e)."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-82-ac11-two-of-three-halves-have-no-standing-red",
    ),
    ACAudit(
        ac="AC12",
        claim=(
            "AC12 -- `tests/integration/test_value_shape.py:527-530`'s engine-gating "
            "paragraph is retracted and replaced with D5's four measured statements. "
            '`grep` for "No cell here is skipped" returns nothing under `tests/`. The '
            "replacement names `--skip-text-pages` and the nonexistent-parent "
            "exception."
        ),
        covering=(),
        red=(
            'COMMAND: COMMAND-RED: git grep -n "No cell here is skipped" -- tests/; '
            "echo rc=$? -> no output, rc 1 at base | plant: appended the line `# No "
            "cell here is skipped` to tests/integration/test_value_shape.py (scratch "
            "worktree, base 119f47e) | saw: "
            "`tests/integration/test_value_shape.py:1055:# No cell here is skipped`, rc "
            "0. The replacement paragraph is at "
            "tests/integration/test_value_shape.py:548-572 and its four numbered "
            "statements name `--skip-text-pages` (item 2) and the `--output` x "
            "nonexistent-parent exception (item 3). No standing test reads the "
            "sentence, so the plant is detected only by the command. Reverted with `git "
            "show HEAD:tests/integration/test_value_shape.py > "
            "tests/integration/test_value_shape.py`; `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-82-ac12-no-standing-test-reads-the-retracted-sentence",
    ),
    ACAudit(
        ac="AC13",
        claim=(
            "AC13 -- The arm exists, reads `request.session.items`, adds no new `make "
            "ci` prerequisite, and rides inside `cover`. Its measured contribution to "
            "the suite's wall clock is recorded and is under one second."
        ),
        covering=(
            "tests/test_engine_gating_census.py::test_the_ungated_engine_blind_drive_count_does_not_grow_per_module",
            "tests/test_engine_gating_census.py::test_the_walk_is_not_vacuous",
            "tests/test_engine_gating_census.py::test_the_helper_limb_reaches_a_gated_arm_the_callspec_walk_cannot_see",
            "tests/test_engine_gating_census.py::test_the_helper_reached_gated_arms_are_in_the_population_when_they_are_collected",
            "tests/test_engine_gating_census.py::test_every_gated_engine_spelling_is_one_the_skip_census_classifies",
            "tests/test_engine_gating_census.py::test_the_lexical_detector_sees_both_shapes_and_cries_no_wolf",
            "tests/test_engine_gating_census.py::test_the_callspec_detector_sees_a_parameter_and_ignores_a_lookalike",
            "tests/test_engine_gating_census.py::test_the_marker_read_distinguishes_a_gated_arm_from_an_ungated_one",
            "tests/test_engine_gating_census.py::test_the_landed_ledger_verifies",
            "tests/test_engine_gating_census.py::test_an_empty_ledger_is_refused",
            "tests/test_engine_gating_census.py::test_a_downward_ratification_is_accepted_with_no_ruling",
            "tests/test_engine_gating_census.py::test_an_unruled_raise_is_refused_naming_the_key_and_both_values",
            "tests/test_read_seams.py::test_convert_zip_claim_branch_and_the_oserror_catch_reachability",
            "tests/test_derived_dimensions.py::test_the_value_shape_axis_still_changes_the_products_answer[convert-out-dir]",
        ),
        red=(
            "Mutated tests/test_engine_gating_census.py:683 (`collected = "
            "arms(request.session.items)` -> `collected = arms(())`, so the census "
            "stops reading the run's own items) in a private scratch worktree at base "
            "119f47e. `uv run pytest <the 14 covering ids> -n 0` -> 1 failed, 13 "
            "passed: `AssertionError: neither detector reached a single one of the 0 "
            "collected item(s), so the population is empty and the ratchet above is "
            "vacuous` (tests/test_engine_gating_census.py:753, "
            "`test_the_walk_is_not_vacuous`). No-new-prerequisite half: see AC25 (a "
            "planted `ci:` prerequisite reds). COST half: `--durations` on the census "
            "file alone showed 1.27 s of setup for a 12-item selection on this host at "
            "load 4, which is NOT a whole-suite measurement, and no test asserts the "
            "under-one-second bound. Reverted with `git show "
            "HEAD:tests/test_engine_gating_census.py > "
            "tests/test_engine_gating_census.py`; `git diff --exit-code` returned 0. "
            "Every mutation in this row was made in a private detached scratch worktree "
            "at base 119f47e, never in the shared worktree."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-82-ac13-census-cost-under-one-second-is-unasserted",
    ),
    ACAudit(
        ac="AC14",
        claim=(
            "AC14 -- Its population is derived by both detectors and its per-module "
            "ungated ceiling is an append-only ratification ledger on the PDF-70 "
            "pattern, whose first record carries the post-fix measured counts and a "
            "reason. No frozen literal appears that is not computed in the same "
            "expression it is compared against."
        ),
        covering=(
            "tests/test_engine_gating_census.py::test_the_ungated_engine_blind_drive_count_does_not_grow_per_module",
            "tests/test_engine_gating_census.py::test_the_walk_is_not_vacuous",
            "tests/test_engine_gating_census.py::test_the_helper_limb_reaches_a_gated_arm_the_callspec_walk_cannot_see",
            "tests/test_engine_gating_census.py::test_the_helper_reached_gated_arms_are_in_the_population_when_they_are_collected",
            "tests/test_engine_gating_census.py::test_every_gated_engine_spelling_is_one_the_skip_census_classifies",
            "tests/test_engine_gating_census.py::test_the_lexical_detector_sees_both_shapes_and_cries_no_wolf",
            "tests/test_engine_gating_census.py::test_the_callspec_detector_sees_a_parameter_and_ignores_a_lookalike",
            "tests/test_engine_gating_census.py::test_the_marker_read_distinguishes_a_gated_arm_from_an_ungated_one",
            "tests/test_engine_gating_census.py::test_the_landed_ledger_verifies",
            "tests/test_engine_gating_census.py::test_an_empty_ledger_is_refused",
            "tests/test_engine_gating_census.py::test_a_downward_ratification_is_accepted_with_no_ruling",
            "tests/test_engine_gating_census.py::test_an_unruled_raise_is_refused_naming_the_key_and_both_values",
            "tests/test_read_seams.py::test_convert_zip_claim_branch_and_the_oserror_catch_reachability",
            "tests/test_derived_dimensions.py::test_the_value_shape_axis_still_changes_the_products_answer[convert-out-dir]",
        ),
        red=(
            "Three mutations, each in the scratch worktree at base 119f47e against the "
            "14 covering ids (`-n 0`). (1) tests/test_engine_gating_census.py:411 "
            "`UNGATED_CEILING: Final[Mapping[str, int]] = "
            "ENGINE_GATING_LEDGER[-1].ceilings` -> a separately constructed "
            "`MappingProxyType(dict(...))` -> 1 failed: `AssertionError: the live "
            "ceiling must BE the newest record's mapping; a separately-writable literal "
            "is a ceiling that can move without a record moving with it` "
            "(test_the_landed_ledger_verifies). (2) :284 the PDF-84 record's "
            '`ruling="X-781"` -> `""` -> 2 failed: `the engine-gating ratification '
            'ledger does not verify: ["[1] PDF-84 (2026-09-17): '
            "tests/integration/test_or7_bulk_destructive.py RAISED 12 -> 13 with NO "
            "ruling.\"]`. (3) :644 the callspec detector's test `if "
            "any(isinstance(value, str) ...` -> `if False:` -> 2 failed: "
            "`AssertionError: {}` in "
            "test_the_callspec_detector_sees_a_parameter_and_ignores_a_lookalike and "
            "`AssertionError: Counter()` in "
            "test_the_marker_read_distinguishes_a_gated_arm_from_an_ungated_one. The "
            "genesis record carries the post-fix census (134 ungated items across 16 "
            "modules of 158). Each reverted with `git show "
            "HEAD:tests/test_engine_gating_census.py > "
            "tests/test_engine_gating_census.py`; `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC15",
        claim=(
            "AC15 -- Non-vacuity, all three: `engine_blind_verbs()` non-empty, "
            "population non-empty, `gated` non-empty -- a walk that matched nothing is "
            "RED."
        ),
        covering=(
            "tests/test_engine_gating_census.py::test_the_ungated_engine_blind_drive_count_does_not_grow_per_module",
            "tests/test_engine_gating_census.py::test_the_walk_is_not_vacuous",
            "tests/test_engine_gating_census.py::test_the_helper_limb_reaches_a_gated_arm_the_callspec_walk_cannot_see",
            "tests/test_engine_gating_census.py::test_the_helper_reached_gated_arms_are_in_the_population_when_they_are_collected",
            "tests/test_engine_gating_census.py::test_every_gated_engine_spelling_is_one_the_skip_census_classifies",
            "tests/test_engine_gating_census.py::test_the_lexical_detector_sees_both_shapes_and_cries_no_wolf",
            "tests/test_engine_gating_census.py::test_the_callspec_detector_sees_a_parameter_and_ignores_a_lookalike",
            "tests/test_engine_gating_census.py::test_the_marker_read_distinguishes_a_gated_arm_from_an_ungated_one",
            "tests/test_engine_gating_census.py::test_the_landed_ledger_verifies",
            "tests/test_engine_gating_census.py::test_an_empty_ledger_is_refused",
            "tests/test_engine_gating_census.py::test_a_downward_ratification_is_accepted_with_no_ruling",
            "tests/test_engine_gating_census.py::test_an_unruled_raise_is_refused_naming_the_key_and_both_values",
            "tests/test_read_seams.py::test_convert_zip_claim_branch_and_the_oserror_catch_reachability",
            "tests/test_derived_dimensions.py::test_the_value_shape_axis_still_changes_the_products_answer[convert-out-dir]",
        ),
        red=(
            "Three mutations against the 14 covering ids in the scratch worktree at "
            "base 119f47e. (1) tests/test_engine_gating_census.py:682 `verbs = "
            "engine_blind_verb_population()` -> `verbs = ()` -> 1 failed: "
            "`registry.engine_blind_verbs() is EMPTY, so this whole census is over "
            "nothing`. (2) :683 `collected = arms(request.session.items)` -> `arms(())` "
            "-> `neither detector reached a single one of the 0 collected item(s)`. (3) "
            ":619 `engine = str(marker.args[0]) if ... else None` -> `engine = None`, "
            "so no arm reads as gated -> 2 failed: `no member of the population carries "
            "an engine marker, so nothing in this suite is declared engine-dependent` "
            "plus the ratchet naming tests/test_read_seams.py. All three go red through "
            "`test_the_walk_is_not_vacuous`. Each reverted with `git show "
            "HEAD:tests/test_engine_gating_census.py > "
            "tests/test_engine_gating_census.py`; `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC16",
        claim=(
            "AC16 -- Fitness: `gated ⊆ population` holds, which is the assertion that "
            "proves H2 reaches the helper-borne verb literal behind the zip-claim arm. "
            "The engineer records the population's size before the marks land and "
            "confirms it contains all eighteen."
        ),
        covering=(
            "tests/test_engine_gating_census.py::test_the_ungated_engine_blind_drive_count_does_not_grow_per_module",
            "tests/test_engine_gating_census.py::test_the_walk_is_not_vacuous",
            "tests/test_engine_gating_census.py::test_the_helper_limb_reaches_a_gated_arm_the_callspec_walk_cannot_see",
            "tests/test_engine_gating_census.py::test_the_helper_reached_gated_arms_are_in_the_population_when_they_are_collected",
            "tests/test_engine_gating_census.py::test_every_gated_engine_spelling_is_one_the_skip_census_classifies",
            "tests/test_engine_gating_census.py::test_the_lexical_detector_sees_both_shapes_and_cries_no_wolf",
            "tests/test_engine_gating_census.py::test_the_callspec_detector_sees_a_parameter_and_ignores_a_lookalike",
            "tests/test_engine_gating_census.py::test_the_marker_read_distinguishes_a_gated_arm_from_an_ungated_one",
            "tests/test_engine_gating_census.py::test_the_landed_ledger_verifies",
            "tests/test_engine_gating_census.py::test_an_empty_ledger_is_refused",
            "tests/test_engine_gating_census.py::test_a_downward_ratification_is_accepted_with_no_ruling",
            "tests/test_engine_gating_census.py::test_an_unruled_raise_is_refused_naming_the_key_and_both_values",
            "tests/test_read_seams.py::test_convert_zip_claim_branch_and_the_oserror_catch_reachability",
            "tests/test_derived_dimensions.py::test_the_value_shape_axis_still_changes_the_products_answer[convert-out-dir]",
        ),
        red=(
            "Mutated tests/test_engine_gating_census.py:117 (`_HELPER_HOPS: Final[int] "
            "= 3` -> 0, so the lexical walk stops following module-level helpers) in a "
            "private scratch worktree at base 119f47e. `uv run pytest <the 14 covering "
            "ids> -n 0` -> 2 failed, 12 passed: `AssertionError: no `requires`-marked "
            "arm anywhere under tests/ is reached THROUGH A MODULE-LEVEL HELPER` "
            "(test_the_helper_limb_reaches_a_gated_arm_the_callspec_walk_cannot_see) "
            "and `AssertionError: the lexical walk did not follow `_argv_helper`` "
            "(test_the_lexical_detector_sees_both_shapes_and_cries_no_wolf). The "
            "'population size before the marks' clause is a pre-edit figure and is not "
            "re-derivable at base. Reverted with `git show "
            "HEAD:tests/test_engine_gating_census.py > "
            "tests/test_engine_gating_census.py`; `git diff --exit-code` returned 0. "
            "Every mutation in this row was made in a private detached scratch worktree "
            "at base 119f47e, never in the shared worktree."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC17",
        claim=(
            "AC17 -- The two-halved control, both halves observed: (i) an ungated "
            "engine-blind drive planted into a copied tree reds the arm, naming module "
            'and node; (ii) the same planted drive carrying `requires("soffice")` does '
            "not red."
        ),
        covering=(
            "tests/test_engine_gating_census.py::test_the_ungated_engine_blind_drive_count_does_not_grow_per_module",
            "tests/test_engine_gating_census.py::test_the_walk_is_not_vacuous",
            "tests/test_engine_gating_census.py::test_the_helper_limb_reaches_a_gated_arm_the_callspec_walk_cannot_see",
            "tests/test_engine_gating_census.py::test_the_helper_reached_gated_arms_are_in_the_population_when_they_are_collected",
            "tests/test_engine_gating_census.py::test_every_gated_engine_spelling_is_one_the_skip_census_classifies",
            "tests/test_engine_gating_census.py::test_the_lexical_detector_sees_both_shapes_and_cries_no_wolf",
            "tests/test_engine_gating_census.py::test_the_callspec_detector_sees_a_parameter_and_ignores_a_lookalike",
            "tests/test_engine_gating_census.py::test_the_marker_read_distinguishes_a_gated_arm_from_an_ungated_one",
            "tests/test_engine_gating_census.py::test_the_landed_ledger_verifies",
            "tests/test_engine_gating_census.py::test_an_empty_ledger_is_refused",
            "tests/test_engine_gating_census.py::test_a_downward_ratification_is_accepted_with_no_ruling",
            "tests/test_engine_gating_census.py::test_an_unruled_raise_is_refused_naming_the_key_and_both_values",
            "tests/test_read_seams.py::test_convert_zip_claim_branch_and_the_oserror_catch_reachability",
            "tests/test_derived_dimensions.py::test_the_value_shape_axis_still_changes_the_products_answer[convert-out-dir]",
        ),
        red=(
            "Both halves re-driven in the scratch worktree at base 119f47e by adding an "
            "untracked module tests/test_zz_plant82.py to the 14 covering ids. HALF 1, "
            'the plant `def test_planted_ungated_engine_blind_drive(): drive("convert", '
            '"x.pdf", "--dry-run")` -> 1 failed, 14 passed: `AssertionError: ungated '
            "engine-blind drives grew past their frozen ceiling {module: (now, "
            "ceiling)}: {'tests/test_zz_plant82.py': (1, 0)}. The nodes in those "
            "modules: "
            "['tests/test_zz_plant82.py::test_planted_ungated_engine_blind_drive']` "
            "(test_the_ungated_engine_blind_drive_count_does_not_grow_per_module). HALF "
            '2, the same plant with `@pytest.mark.requires("soffice")` -> `15 passed`. '
            "The standing arms for the two detectors' own synthetic reds are in the "
            "covering ids. The plant file was removed with `rm`, and `git status "
            "--porcelain` was empty afterwards."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC18",
        claim=(
            "AC18 -- The three `without-engines` entries in `.github/gate-parity.toml` "
            "no longer carry `needs-engine-configuration`; the two `engines-present` "
            "entries still do. `make ci`'s epilogue is captured before and after and "
            "both are recorded."
        ),
        covering=(
            "tests/test_gate_parity.py::test_every_reason_in_the_manifest_is_in_the_closed_vocabulary",
            "tests/test_gate_parity.py::test_manifest_parses_with_tomllib_and_declares_schema_version_1",
        ),
        red=(
            "Mutated .github/gate-parity.toml:124 (re-added `reason = "
            '"needs-engine-configuration"` to the `without-engines` entry `verify '
            "tesseract and soffice are ABSENT`, i.e. the false tag the audited spec "
            "removed) in a private scratch worktree at base 119f47e. `uv run pytest "
            "tests/test_gate_parity.py tests/test_engine_hiding_shim.py -n 2` -> 58 "
            "passed. The restored false claim reds nothing: the closed-vocabulary arm "
            "accepts the value (it is a member of REASON_VOCAB) and no arm asserts the "
            "absence on the three entries or the presence on the two `engines-present` "
            "ones. The before/after epilogue capture is a process act and was not "
            "re-driven. Reverted with `git show HEAD:.github/gate-parity.toml > "
            ".github/gate-parity.toml`; `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-82-ac18-false-reason-tag-can-be-restored-green",
    ),
    ACAudit(
        ac="AC19",
        claim=(
            "AC19 -- Their `local` points at a target that is runnable on every host, "
            "proven by running it with `soffice` and `tesseract` stripped from `PATH` "
            "and recording exit 0. `make engines-gate` still refuses arm 1 on that same "
            "host, with its message unchanged."
        ),
        covering=(
            "tests/test_gate_parity.py::test_every_local_target_is_a_real_makefile_target",
            "tests/test_gate_parity.py::test_gate_parity_check_subcommand_agrees_with_the_independent_scan",
        ),
        red=(
            "Mutated .github/gate-parity.toml:124 (the `without-engines` entry's `local "
            '= "engines-hidden"` -> `"engines-hiddn"`) in a private scratch worktree at '
            "base 119f47e. `uv run pytest tests/test_gate_parity.py "
            "tests/test_engine_hiding_shim.py -n 2` -> 2 failed, 56 passed: "
            "`AssertionError: without-engines/verify tesseract and soffice are ABSENT: "
            "local target 'engines-hiddn' undefined` and `gate_parity check: FAILED`. "
            "Refusal half driven: with PATH reduced to a symlink farm lacking both "
            "binaries, `make engines-gate` -> `make engines-gate: REFUSING arm 1 "
            "(engines present) -- tesseract soffice not on PATH.`, rc 2, message "
            "unchanged. NOT driven: `make engines-hidden` as a full suite with the "
            "binaries stripped (exit 0); only a 20-id subset under the shim was run (rc "
            "0 for assert_skips). Reverted with `git show HEAD:.github/gate-parity.toml "
            "> .github/gate-parity.toml`; `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-82-ac19-engines-hidden-full-run-exit-0-not-re-driven",
    ),
    ACAudit(
        ac="AC20",
        claim=(
            "AC20 -- If `REASON_VOCAB` gained a member, `tests/test_gate_parity.py`'s "
            "closure arm, its invented-reason red and the `RedKind` disjointness arm "
            "are all re-run green and the new spelling is reported to the "
            "project-manager by name. If the fallback was taken instead, that choice is "
            "reported."
        ),
        covering=(),
        red=(
            "COMMAND: `git show --stat --format= 52ec164 -- scripts/gate_parity.py | wc "
            "-l` -> 0: REASON_VOCAB (scripts/gate_parity.py:50) was not touched, so the "
            "FALLBACK was taken (the three `reason` keys were dropped, and "
            ".github/gate-parity.toml:113-120 states the decision in a comment). The "
            "closure, invented-reason and RedKind arms are standing "
            "(tests/test_gate_parity.py) and pass at base. The 'report the choice' act "
            "is not an artifact and no red is recorded."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-82-ac20-fallback-choice-is-only-in-the-diff",
    ),
    ACAudit(
        ac="AC21",
        claim=(
            "AC21 -- The new `Makefile` target is a prerequisite of nothing, proven by "
            "re-running `tests/test_engine_hiding_shim.py`'s recipe census and "
            "`tests/test_gate_parity.py`'s Makefile<->manifest agreement arms."
        ),
        covering=(
            "tests/test_gate_parity.py::test_makefiles_ci_prerequisites_are_exactly_the_in_make_ci_true_locals",
            "tests/test_gate_parity.py::test_gate_parity_check_subcommand_agrees_with_the_independent_scan",
            "tests/test_engine_hiding_shim.py::test_the_prerequisite_check_can_see_a_planted_dependency",
        ),
        red=(
            "Mutated Makefile:433 (`ci: fmt-check lint typecheck cover licenses sast "
            "vulncheck` -> `... vulncheck engines-hidden`) in a private scratch "
            "worktree at base 119f47e. `uv run pytest tests/test_gate_parity.py "
            "tests/test_engine_hiding_shim.py -n 2` -> 3 failed, 55 passed: "
            "`AssertionError: gate_parity check: FAILED` and the frozenset inequality "
            "in test_makefiles_ci_prerequisites_are_exactly_the_in_make_ci_true_locals. "
            "SECOND plant, Makefile:68 (`cover:` -> `cover: engines-hidden`): 58 "
            "passed, so a prerequisite of `cover`, `test` or `docs-gate` is detected by "
            "nothing; the guard reads `ci` only. Each reverted with `git show "
            "HEAD:Makefile > Makefile`; `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-82-ac21-cover-prerequisite-plant-is-green",
    ),
    ACAudit(
        ac="AC22",
        claim=(
            "AC22 -- `src/` is absent from the diff. `git diff --stat` naming any file "
            "under `src/pdf_tooling/` is a BLOCKER."
        ),
        covering=(),
        red=(
            "COMMAND: `git show --stat --format= 52ec164 -- src/ | wc -l` -> 0; the "
            "whole landing commit is 9 files (.github/gate-parity.toml, Makefile, "
            "changelog.md, tests/integration/test_value_shape.py, tests/registry.py, "
            "tests/test_cli_spine.py, tests/test_derived_dimensions.py, "
            "tests/test_engine_gating_census.py, tests/test_read_seams.py). A property "
            "of one landed commit: no mutation can red it without rewriting history, "
            "and no standing arm re-reads it, so no red is recorded."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-82-landed-diff-shape-acs-have-no-standing-control",
    ),
    ACAudit(
        ac="AC23",
        claim=(
            "AC23 -- `README.md`, `CLAUDE.md`, `CONTRIBUTING.md` and `TESTING.md` are "
            "absent from the diff; all four residues stay at 29 / 7 / 6 / 127 and the "
            "guarded-document ratification ledger gains no record."
        ),
        covering=(),
        red=(
            "COMMAND: `git show --stat --format= 52ec164 -- README.md CLAUDE.md "
            "CONTRIBUTING.md TESTING.md | wc -l` -> 0, and the residue script of AC4 "
            "prints 29 / 7 / 6 / 127 with a docs ledger of two records (PDF-30, PDF-67) "
            "at base, so neither the diff nor the ledger moved. Landed-diff shape: no "
            "standing arm re-reads it and no mutation reds it without rewriting "
            "history."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-82-landed-diff-shape-acs-have-no-standing-control",
    ),
    ACAudit(
        ac="AC24",
        claim=(
            "AC24 -- `make docs-gate` exits 0 and its engines-hidden arm still reports "
            "`12 passed, 22 skipped`, matching `TESTING.md:333` unedited."
        ),
        covering=(),
        red=(
            "COMMAND: COMMAND-RED: make docs-gate -> rc 0, `12 passed, 22 skipped in "
            "3.61s`, `docs-gate: TESTING.md's engines-hidden figure agrees with the run "
            "(12 passed, 22 skipped)`, then `272 passed, 9 skipped` (the 9 are "
            "planning-directory arms: PDF_TOOLING_PLANNING_DIR unset) | plant: "
            "TESTING.md `12 passed, 22 skipped` -> `13 passed, 22 skipped` (scratch "
            "worktree, base 119f47e) | saw: `make docs-gate: TESTING.md quotes '13 "
            "passed, 22 skipped' for the engines-hidden run; the documented command "
            "just reported 12 passed, 22 skipped. Re-run it; do not copy it.` make rc "
            "2. Not host-limited: the target hides the engines itself. Reverted with "
            "`git show HEAD:TESTING.md > TESTING.md`; `git diff --exit-code` returned "
            "0."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
        finding="PENDING-LEDGER: pdf-82-ac24-docs-gate-is-not-a-verify-node-and-nine-arms-skip",
    ),
    ACAudit(
        ac="AC25",
        claim=(
            "AC25 -- `make ci`'s prerequisite list is unchanged, coverage stays at or "
            "above the untouched floor of 85, and the suite's xfail total is unchanged."
        ),
        covering=(
            "tests/test_gate_parity.py::test_makefiles_ci_prerequisites_are_exactly_the_in_make_ci_true_locals",
            "tests/test_gate_parity.py::test_the_coverage_floor_is_defined_only_in_the_makefile",
            "tests/test_coverage_policy.py::test_the_floor_has_not_been_weakened_by_any_route",
        ),
        red=(
            "Two mutations in the scratch worktree at base 119f47e. (1) Makefile:433 "
            "`ci:` + `engines-hidden` -> red as in AC21 (frozenset inequality in "
            "test_makefiles_ci_prerequisites_are_exactly_the_in_make_ci_true_locals). "
            "(2) Makefile:107 `--cov-fail-under=85` -> `84`, against these ids plus "
            "`tests/test_coverage_policy.py` -> 2 failed: `AssertionError: Makefile "
            "declares coverage floor(s) ['84'], expected exactly one at 85` "
            "(test_the_floor_has_not_been_weakened_by_any_route) and `assert "
            "'cov-fail-under=85' in ...` "
            "(test_the_coverage_floor_is_defined_only_in_the_makefile). The xfail total "
            "(3 xfailed in the CI logs) is pinned by no test: `git grep -n -i xfail` "
            "over tests/*.py, scripts and the Makefile finds only assert_skips.py's own "
            "exclusion. Each reverted with `git show HEAD:Makefile > Makefile`; `git "
            "diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-82-ac25-xfail-total-has-no-standing-control",
    ),
    ACAudit(
        ac="AC26",
        claim=(
            "AC26 -- `changelog.md` carries one `## [PDF-82] Unblock the engines-absent "
            "gate, and retire the excuse that hid it -- <date>` entry, prepended "
            "directly below the anchor, in the same commit as the code "
            "(`tests/test_changelog_history.py:428`)."
        ),
        covering=(
            "tests/test_changelog_history.py::test_no_other_commit_ever_loses_a_changelog_heading",
            "tests/test_changelog_history.py::test_every_added_heading_is_prepended_below_the_anchor",
            "tests/test_changelog_history.py::test_every_spec_or_remediation_commit_writes_its_own_entry",
        ),
        red=(
            "Mutation is history-shaped: in the scratch worktree at base 119f47e the "
            "`## [PDF-82] Unblock the engines-absent gate...` heading "
            "(changelog.md:202) was deleted in a scratch COMMIT (`git commit -am`), "
            "then `uv run pytest tests/test_changelog_history.py -n 2` -> 1 failed, 13 "
            "passed: `AssertionError: a landed changelog entry was destroyed:` "
            "(test_no_other_commit_ever_loses_a_changelog_heading). The same deletion "
            "left UNCOMMITTED in the working tree gave `14 passed`, so the guard reads "
            "history, not the tree. Returned to base with `git switch --detach 119f47e` "
            "(the scratch commit became unreachable), `git status --porcelain` empty "
            "and HEAD back at 119f47e. The 'same commit as the code' clause is the "
            "audited commit's own shape (`git show --stat 52ec164` lists changelog.md "
            "+8) and is not re-derivable by mutation."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC27",
        claim=(
            "AC27 -- The three filed items of D9 are reported to the project-manager by "
            'name, the `"path": null` finding carrying its own reproduction, so that '
            "none is lost and none is silently absorbed."
        ),
        covering=(),
        red=(
            "UNREDDENABLE: a hand-up to the project-manager, not an artifact. Nothing "
            "in the product records or asserts that three items were reported, so no "
            "mutation exists. The reproduction D9.1 asks for does re-derive (AC2: "
            '`"path": null` on the `engine_missing` envelope at base), which evidences '
            "the finding's premise and not the act of reporting it."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-82-ac27-a-report-to-the-pm-is-not-an-artifact",
    ),
)
