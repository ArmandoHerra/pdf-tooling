"""`PDF-86`'s 16 acceptance criteria, re-derived -- `AUDIT-CONVENTION(PDF-17)`.

`PDF-86` ("Condition the total-startup-cost ceiling on the cells it was measured
in", landed `76437a8`) reads `Implemented (2026-09-18)` and has never held a
`Verified`; the 2026-09-19 sentinel named it one of its three most consequential
omissions (a `G3` tag-blocker evidenced only by CI). This module is the
evidence for that first grant or refusal. The auditing spec is `PDF-106`
(roadmap `R-05`, PM ruling `X-962`, dispatch C); the audited spec is `PDF-86`.

**Independence (R-05, binding).** The author of this module did not implement
`PDF-86`: it is a fresh dispatch that never held the spec's context. The audited
spec's Implementation Log was not used as evidence; the spec text supplied the
AC wording and nothing else, and every red below was re-driven by this author in
a private scratch worktree at the audit base `119f47e`.

The qa-sentinel grants or refuses; this module does not.

**Taken at the audit base `119f47e`, not at the landing commit.** `PDF-86`
landed in `tests/test_import_boundaries.py` and `tests/test_gate_budget.py`;
`tests/unit/test_name_template.py` and the lines the audited spec cites have
since moved (the arm is at `:4358` at the base, not `:3736`). Every `covering` id
was copy-pasted from a real `pytest --collect-only -q` at that base.

**Per-class counts: 16 criteria = 11 locally driven + 0 covered-red-NOT-observed
+ 4 command-evidenced + 1 CI-evidenced + 0 UNREDDENABLE.**

* **locally driven** -- AC1, AC3, AC4, AC5, AC6, AC8, AC9, AC10, AC11, AC12,
  AC16. Each `red` names the file:line mutated, the failure line seen, the
  revert and the base sha. AC4, AC9, AC10 and AC11 also carry a `finding` for
  the half of the claim the mutation did not red.
* **COMMAND:** -- AC2, AC7, AC13, AC14. AC2 and AC7 carry a `COMMAND-RED:`
  marker (command, scratch plant, failure line); AC13 and AC14 are `NOT_OBSERVED`
  with a finding.
* **CI-EVIDENCED:** -- AC15, with a live `gh run view` (see the row).
* **UNREDDENABLE:** -- none in this module. Zero is permitted only where the
  would-be unreddenable rows carry a mechanical red; AC7 and AC9, the two E7
  listed as process, both do (below).

**E7 positions, confirmed or overturned.** Confirmed: AC15 is CI-EVIDENCED.
Overturned: **AC9** (E7 said process; its AST half is drivable -- a `gw0` literal
planted in the observation builder reds the load-sensing walk -- so it is locally
driven, with the `assert_skips` half left recorded-not-re-derived per `X-826`),
**AC6** (E7 listed it under landed-diff shape; the AST walk over the declared
registry is a standing arm with a driven red), **AC8** (locally driven through
its three plants; the diff half is confirmed by `git show 76437a8 --format= --
tests/test_gate_budget.py | grep -cE '^-[^-]'` -> 0, i.e. no deleted line, so
`SANCTIONED_CONDITION` is byte-untouched), and **AC7** (E7 said process; the
ceiling sits under a driven, if incidental, red and one cell is re-measured live,
so it is COMMAND, not unreddenable). AC13 was decided COMMAND rather than
UNREDDENABLE for the reason given on `PDF-82` AC22: `git show --stat` is a
re-runnable answerable question.

**What was NOT re-driven.** The four-interpreter campaign of AC7 (only the
interpreter the scratch venv carries, CPython 3.13.15 = cell `(linux, 3.13)`, was
re-measured), the real-`src/` escaping-class plant of AC4 (the standing control is
synthetic, at the helper level), and the per-gate landing runs of AC14.

Mutation method: edit one line in the scratch worktree, run the named node ids
with `uv run pytest <ids> -n 0` (or `-n 2`), record the failure line, restore
the file from `git show HEAD:<path>` and prove the restore with
`git diff --exit-code`. Findings are `PENDING-LEDGER:` slugs for the sentinel to
mint; this module writes neither the ledger nor the backlog.
"""

from __future__ import annotations

from typing import Final

from acceptance._model import ACAudit, RedKind

SPEC_ID: Final[str] = "PDF-86"
AC_COUNT: Final[int] = 16

AUDIT: Final[tuple[ACAudit, ...]] = (
    ACAudit(
        ac="AC1",
        claim=(
            "AC1 -- the message says which half moved. On a red in a calibrated "
            "condition, the message names the numerator median, the denominator median, "
            "each as a factor of that condition's recorded value, the ratio median, the "
            "ceiling, and a one-clause verdict naming the half that carries the red. "
            "Failing controls, both observed: a numerator-side plant reads 'the "
            "NUMERATOR carries this red (x1.68 against x0.99)'; a denominator collapse "
            "to x0.55 reads 'the DENOMINATOR carries this red (x0.54 against x0.99)'."
        ),
        covering=(
            "tests/test_import_boundaries.py::test_the_observation_names_the_half_that_moved[numerator-side]",
            "tests/test_import_boundaries.py::test_the_observation_names_the_half_that_moved[denominator-collapse]",
            "tests/test_import_boundaries.py::test_the_observation_refuses_a_reference_this_run_does_not_share",
        ),
        red=(
            "Mutated tests/test_import_boundaries.py:3695 (`if factor_numerator >= 1 / "
            "factor_denominator` -> `if factor_numerator < 1 / factor_denominator`, so "
            "the builder names the opposite half) in a private scratch worktree at base "
            "119f47e. `uv run pytest <the 3 covering ids> -n 2` -> 2 failed, 1 passed: "
            "`AssertionError: the message does not name the half that moved:` for BOTH "
            "test_the_observation_names_the_half_that_moved[numerator-side] and "
            "[denominator-collapse], i.e. both directions of the pair went red. "
            "Reverted with `git show HEAD:tests/test_import_boundaries.py > "
            "tests/test_import_boundaries.py`; `git diff --exit-code` returned 0. Every "
            "mutation in this row was made in a private detached scratch worktree at "
            "base 119f47e, never in the shared worktree."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC2",
        claim=(
            "AC2 -- the halves are in the MESSAGE, not only in a repr. The engineer "
            "re-drives E8's lowered-ceiling red and records the shipped message "
            "verbatim, then the new one, and confirms the new figures survive "
            "`--tb=line` and the `-ra` short summary."
        ),
        covering=(
            "tests/test_startup_message_short_summary.py::test_the_startup_cost_halves_survive_a_200_column_terminal",
            "tests/test_startup_message_short_summary.py::test_the_startup_cost_halves_survive_a_ci_log",
        ),
        red=(
            "Closed by PDF-114 D4/D5 (base 9809a7f, private worktree). Before: with "
            "tests/test_import_boundaries.py:3324 `STARTUP_COST_RATIO_CEILING_PER_MILLE` "
            "26_500 -> 5_000 and `env -u CI -u BUILD_NUMBER COLUMNS=200 uv run pytest -n "
            "0 -q --tb=line -ra tests/test_import_boundaries.py -k "
            "total_startup_import_cost`, the `-ra` line read `FAILED "
            "tests/test_import_boundaries.py::"
            "test_total_startup_import_cost_stays_under_its_ceiling "
            "- AssertionError: 5 of 5 readings exceeded the 26.500 total-startup-cost "
            "ratio ceiling in CALIBRATED co...` (no half). After D4 the same plant "
            "reads `... - AssertionError: numerator x0.676 / denominator x0.695 -> the "
            "DENOMINATOR carries this red; 5 of 5 re...`. Control: "
            'tests/test_import_boundaries.py:3790 `return f"{lead}{head} {body} ..."` '
            '-> `return f"{head} {lead}{body} ..."` (the lead behind the header) -> '
            "`pytest -n 0 tests/test_startup_message_short_summary.py` -> 3 failed, 2 "
            "passed: `AssertionError: numerator factor missing from -ra line:` for "
            "the 200-column arm, the CI-log arm still passing; `uv run python "
            "scripts/verify_spec.py PDF-86` printed `AC2 | ... | 1/2 passed (1 failed)` "
            "and `runner exit: 1`. The `-ra` half is graded at a CI log and a "
            "200-column non-CI terminal; below 100 columns pytest prints no message for "
            "this node id at all (recorded by "
            "`test_the_node_id_leaves_no_room_below_100_columns`). Reverted from a saved "
            "copy (the new code is not at HEAD); `git diff --exit-code` against it "
            "returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=None,
    ),
    ACAudit(
        ac="AC3",
        claim=(
            "AC3 -- the condition is ASSERTED, and there are three verdicts. A "
            "registered condition -> CALIBRATED, a declared-unmeasured condition -> "
            "RECORD, anything else -> red. Failing controls: an unregistered platform "
            "reds naming the condition; emptying the declared-unmeasured registry turns "
            "the macOS vector from RECORD into RED."
        ),
        covering=(
            "tests/test_import_boundaries.py::test_the_startup_condition_verdict_roster_is_exhaustive[linux-3.11-CALIBRATED]",
            "tests/test_import_boundaries.py::test_the_startup_condition_verdict_roster_is_exhaustive[linux-3.12-CALIBRATED]",
            "tests/test_import_boundaries.py::test_the_startup_condition_verdict_roster_is_exhaustive[linux-3.13-CALIBRATED]",
            "tests/test_import_boundaries.py::test_the_startup_condition_verdict_roster_is_exhaustive[linux-3.14-CALIBRATED]",
            "tests/test_import_boundaries.py::test_the_startup_condition_verdict_roster_is_exhaustive[darwin-3.11-RECORD]",
            "tests/test_import_boundaries.py::test_the_startup_condition_verdict_roster_is_exhaustive[darwin-3.14-RECORD]",
            "tests/test_import_boundaries.py::test_the_startup_condition_verdict_roster_is_exhaustive[win32-3.12-UNDECLARED]",
            "tests/test_import_boundaries.py::test_the_startup_condition_verdict_roster_is_exhaustive[linux-3.15-UNDECLARED]",
            "tests/test_import_boundaries.py::test_the_startup_condition_verdict_roster_is_exhaustive[darwin-3.15-UNDECLARED]",
            "tests/test_import_boundaries.py::test_the_live_condition_is_one_the_matrix_can_actually_produce",
            "tests/test_import_boundaries.py::test_the_record_verdict_is_reached_through_a_declaration_and_never_as_a_default",
            "tests/test_import_boundaries.py::test_an_undeclared_condition_reds_naming_the_condition_and_both_halves",
        ),
        red=(
            "Mutated tests/test_import_boundaries.py:3564 in "
            "`classify_startup_condition` (`if condition in declared:` -> `if True:`, "
            "so every non-calibrated condition earns RECORD and nothing is ever "
            "UNDECLARED) in a private scratch worktree at base 119f47e. `uv run pytest "
            "<the 12 covering ids> -n 2` -> 5 failed, 7 passed: `AssertionError: assert "
            "'RECORD' == 'UNDECLARED'` on the roster arms [win32-3.12-UNDECLARED], "
            "[linux-3.15-UNDECLARED], [darwin-3.15-UNDECLARED]; the same assertion in "
            "test_the_record_verdict_is_reached_through_a_declaration_and_never_as_a_default; "
            "and `KeyError: StartupCondition(platform='win32', interpreter='3.12')` in "
            "test_an_undeclared_condition_reds_naming_the_condition_and_both_halves. "
            "Reverted with `git show HEAD:tests/test_import_boundaries.py > "
            "tests/test_import_boundaries.py`; `git diff --exit-code` returned 0. Every "
            "mutation in this row was made in a private detached scratch worktree at "
            "base 119f47e, never in the shared worktree."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC4",
        claim=(
            "AC4 -- nothing the product, its lock or its imports can do moves the arm "
            "out of the asserting branch. With PDF-68's escaping-class plant installed "
            "in a scratch rsync copy, the verdict is still CALIBRATED and the arm reds. "
            "Failing control: the same plant with the ceiling untouched must red."
        ),
        covering=(
            "tests/test_import_boundaries.py::test_nothing_the_product_can_do_moves_a_cell_out_of_the_asserting_branch",
        ),
        red=(
            "Mutated tests/test_import_boundaries.py:3771 in "
            "`assert_startup_cost_in_its_domain` (`assert len(over) * 2 <= "
            "len(readings.ratios), observation` -> `assert True, observation`, so a "
            "CALIBRATED cell can never red) in a private scratch worktree at base "
            "119f47e. `uv run pytest "
            "tests/test_import_boundaries.py::test_nothing_the_product_can_do_moves_a_cell_out_of_the_asserting_branch"
            " -n 2` -> 1 failed: `Failed: DID NOT RAISE AssertionError` "
            "(tests/test_import_boundaries.py:4911, the inflated-numerator vector at "
            "the cell's own f_min + 10%). NOT driven: the AC's in-situ half, PDF-68's "
            "real escaping-class plant into a copy of src/ with the full probe; the "
            "standing control is the synthetic helper-level one, which is what this row "
            "evidences. Reverted with `git show HEAD:tests/test_import_boundaries.py > "
            "tests/test_import_boundaries.py`; `git diff --exit-code` returned 0. Every "
            "mutation in this row was made in a private detached scratch worktree at "
            "base 119f47e, never in the shared worktree."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-86-ac4-real-src-plant-not-re-driven",
    ),
    ACAudit(
        ac="AC5",
        claim=(
            "AC5 -- the calibrated registry cannot gain a member without a recorded "
            "distribution. A guard asserts every member carries a block naming its "
            "floor-name count, quiet ratio median, numerator median, denominator "
            "median, headroom, `f_min` and provenance. `PDF42_DERIVATION_TOKENS` is not "
            "extended and no landed block is rewritten."
        ),
        covering=(
            "tests/test_import_boundaries.py::test_every_calibrated_condition_carries_a_recorded_distribution",
            "tests/test_import_boundaries.py::test_a_calibrated_member_missing_a_field_reddens_naming_both[floor_names]",
            "tests/test_import_boundaries.py::test_a_calibrated_member_missing_a_field_reddens_naming_both[ratio_median]",
            "tests/test_import_boundaries.py::test_a_calibrated_member_missing_a_field_reddens_naming_both[numerator_median_us]",
            "tests/test_import_boundaries.py::test_a_calibrated_member_missing_a_field_reddens_naming_both[denominator_median_us]",
            "tests/test_import_boundaries.py::test_a_calibrated_member_missing_a_field_reddens_naming_both[headroom]",
            "tests/test_import_boundaries.py::test_a_calibrated_member_missing_a_field_reddens_naming_both[f_min_pct]",
            "tests/test_import_boundaries.py::test_a_calibrated_member_missing_a_field_reddens_naming_both[provenance]",
        ),
        red=(
            "Mutated tests/test_import_boundaries.py:3467 (the first calibrated "
            "member's `headroom=1.5598,` -> `headroom=0,`) in a private scratch "
            "worktree at base 119f47e. `uv run pytest <the 8 covering ids> -n 2` -> 7 "
            "failed, 1 passed: "
            "test_every_calibrated_condition_carries_a_recorded_distribution fails on "
            "the vacuous field, and every "
            "`test_a_calibrated_member_missing_a_field_reddens_naming_both[...]` case "
            "fails too because each takes the first member as its base: "
            "`AssertionError: stripping 'f_min_pct' from (linux, 3.11) left a record "
            "the guard still accepts: ['(linux, 3.11) carries no headroom', '(linux, "
            "3.11) carries no f_min_pct']`. Landed-diff half (COMMAND, in the row so "
            "the sentinel can re-run it): `git show 76437a8 --format= -- "
            "tests/test_import_boundaries.py | grep -E '^-[^-]'` lists only the arm's "
            "own pre-PDF-86 body and its message; no line of the three landed "
            "derivation blocks is deleted or edited, and `git show 76437a8 --format= -- "
            "tests/test_gate_budget.py | grep -cE '^-[^-]'` -> 0. Reverted with `git "
            "show HEAD:tests/test_import_boundaries.py > "
            "tests/test_import_boundaries.py`; `git diff --exit-code` returned 0. Every "
            "mutation in this row was made in a private detached scratch worktree at "
            "base 119f47e, never in the shared worktree."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC6",
        claim=(
            "AC6 -- the declared-unmeasured entry contains no number about the "
            "condition it declares. Failing control: grep the diff for any numeric "
            "literal inside that registry -> zero."
        ),
        covering=(
            "tests/test_import_boundaries.py::test_the_declared_unmeasured_registry_carries_no_figure_about_what_it_declares",
            "tests/test_import_boundaries.py::test_a_figure_planted_in_the_declared_unmeasured_registry_reddens[a-float-figure]",
            "tests/test_import_boundaries.py::test_a_figure_planted_in_the_declared_unmeasured_registry_reddens[an-integer-figure]",
        ),
        red=(
            'Mutated tests/test_import_boundaries.py:3530 (`StartupCondition("darwin", '
            "condition.interpreter): _NO_HOST_FOR_THIS_PLATFORM` -> `... "
            "_NO_HOST_FOR_THIS_PLATFORM if 3 else None`, a numeric literal inside the "
            "STARTUP_COST_UNCALIBRATED assignment) in a private scratch worktree at "
            "base 119f47e. `uv run pytest <the 3 covering ids> -n 2` -> 1 failed, 2 "
            "passed: `AssertionError: the declared-unmeasured registry carries 1 "
            "numeric literal(s): ['line 3530: 3']` "
            "(test_the_declared_unmeasured_registry_carries_no_figure_about_what_it_declares)."
            " The two planted-figure arms are standing proofs that the walk catches both "
            "a float and an int. Reverted with `git show "
            "HEAD:tests/test_import_boundaries.py > tests/test_import_boundaries.py`; "
            "`git diff --exit-code` returned 0. Every mutation in this row was made in "
            "a private detached scratch worktree at base 119f47e, never in the shared "
            "worktree."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC7",
        claim=(
            "AC7 -- the four Linux cells are re-measured and each is shown to sit under "
            "the UNCHANGED ceiling. The log carries, per interpreter, the floor-name "
            "count, the numerator and denominator medians, the three quorum medians, "
            "the headroom and the derived `f_min`. "
            "`STARTUP_COST_RATIO_CEILING_PER_MILLE` is byte-identical at `26_500`."
        ),
        covering=(),
        red=(
            "COMMAND: COMMAND-RED: uv run pytest tests/test_import_boundaries.py "
            "tests/test_gate_budget.py tests/test_coverage_policy.py "
            "tests/test_docstring_pointers.py tests/test_docs_antirot.py -n 4 | plant: "
            "tests/test_import_boundaries.py:3268 "
            "`STARTUP_COST_RATIO_CEILING_PER_MILLE: Final = 26_500` -> `27_000` "
            "(scratch worktree, base 119f47e) | saw: `3 failed, 525 passed, 9 skipped, "
            "1 xfailed`: "
            "test_nothing_the_product_can_do_moves_a_cell_out_of_the_asserting_branch "
            "(`Regex pattern did not match`) and "
            "test_the_observation_names_the_half_that_moved[numerator-side] / "
            "[denominator-collapse] (`assert 'readings exceeded the 26.500' in '5 of 5 "
            "readings exceeded the 27.000 ...'`). That red is INCIDENTAL: it is a "
            "message-text pin in those arms, not a guard on the constant. Re-measured "
            "live in this interpreter's cell only: `uv run pytest "
            "tests/test_import_boundaries.py -k total_startup_import_cost` -> `1 "
            "passed`, CPython 3.13.15 = (linux, 3.13), readings [10.8541, 11.0148, "
            "10.9896, 12.3819, 11.4342] against the recorded 12.4120 and the ceiling "
            "26.500. The other three interpreters were NOT re-measured (each needs a "
            "fresh `uv sync --python <V>`). Reverted with `git show "
            "HEAD:tests/test_import_boundaries.py > tests/test_import_boundaries.py`; "
            "`git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-86-ac7-ceiling-pin-incidental-three-cells-not-remeasured",
    ),
    ACAudit(
        ac="AC8",
        claim=(
            "AC8 -- NO ABSTENTION IS ADDED, AND THE THREE GUARDS DRAFT 1 WOULD HAVE "
            "MOVED ARE PROVED BYTE-UNTOUCHED. Failing controls, three: plant "
            '`pytest.skip("busy")` in Section 6 -> the companion guard reds naming it; '
            "plant `os.getloadavg()` -> the load-sensing walk reds naming function and "
            "line; plant an xdist skip inside the sanctioned condition -> the trojan "
            "guard reds."
        ),
        covering=(
            "tests/test_gate_budget.py::test_the_load_immune_companion_exists_and_cannot_abstain",
            "tests/test_gate_budget.py::test_the_abstention_walk_is_not_vacuous",
            "tests/test_gate_budget.py::test_the_sanctioned_precondition_cannot_be_used_as_a_trojan",
        ),
        red=(
            "Two plants, each inserted before the arm's "
            "`assert_startup_cost_in_its_domain(` call at "
            "tests/test_import_boundaries.py:4399 in a private scratch worktree at base "
            '119f47e. (1) `pytest.skip("busy")` -> `uv run pytest <the 3 covering ids> '
            "-n 2` -> 2 failed, 1 passed: `AssertionError: a live abstention is not the "
            "sanctioned one: [... "
            "'test_total_startup_import_cost_stays_under_its_ceiling:4399 abstains via "
            "pytest.skip on `<unconditional>`']` and `Section 6 has grown an abstention "
            "that is not the build-absent precondition:`. (2) `os.getloadavg()` -> 1 "
            "failed, 2 passed: `Section 6's code senses host load or worker identity: "
            "['test_total_startup_import_cost_stays_under_its_ceiling:4399 "
            "os.getloadavg']`. The third plant (an xdist skip inside the sanctioned "
            "condition) is the trojan arm's own standing proof and was not re-planted. "
            "Diff half, COMMAND: `git show 76437a8 --format= -- "
            "tests/test_gate_budget.py | grep -cE '^-[^-]'` -> 0 (no deleted line, so "
            "SANCTIONED_CONDITION is byte-untouched). Each reverted with `git show "
            "HEAD:tests/test_import_boundaries.py > tests/test_import_boundaries.py`; "
            "`git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC9",
        claim=(
            "AC9 -- the new text cannot redden an unrelated job, and the one live "
            "constraint is the AST one. The message and the warning class name contain "
            "none of `LOAD_SENSING_LITERAL_PATTERN`'s tokens and none of `engine`, "
            "`tesseract`, `soffice`, `libreoffice`. Failing control: plant a `gw0` "
            "literal into the message -> the companion guard reds naming function and "
            "line."
        ),
        covering=(
            "tests/test_gate_budget.py::test_the_load_immune_companion_exists_and_cannot_abstain",
            "tests/test_gate_budget.py::test_the_environ_passthrough_in_section_six_is_not_flagged",
        ),
        red=(
            "Mutated tests/test_import_boundaries.py:3677 inside "
            '`startup_cost_observation` (the string `"NOT a bound."` -> `"gw0 NOT a '
            'bound."`) in a private scratch worktree at base 119f47e. `uv run pytest '
            "<the 2 covering ids> -n 2` -> 2 failed: `Section 6's code senses host load "
            "or worker identity: [\"startup_cost_observation:3676 ' -- CROSS-CONDITION, "
            "diagnostic only, gw0 NOT a bound.'\"]` "
            "(test_the_load_immune_companion_exists_and_cannot_abstain) and the "
            "post-PDF-42 matcher arm. TWO HALVES THAT STAY GREEN: (a) the same `gw0` "
            "planted in the MODULE-LEVEL constant STARTUP_COST_REMEDIATION (:3608), "
            "which is part of the rendered message, -> `2 passed`, because the string "
            "walk covers only functions Section 6 reaches; (b) `soffice` planted in the "
            "same builder string -> `2 passed`, so the engine-word ban has no standing "
            "control at all. The `assert_skips --expect-zero` half is 'recorded, not "
            "re-derived' per X-826 and was not re-measured. Reverted with `git show "
            "HEAD:tests/test_import_boundaries.py > tests/test_import_boundaries.py`; "
            "`git diff --exit-code` returned 0. Every mutation in this row was made in "
            "a private detached scratch worktree at base 119f47e, never in the shared "
            "worktree."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-86-ac9-module-constant-and-engine-words-unwalked",
    ),
    ACAudit(
        ac="AC10",
        claim=(
            "AC10 -- the register names the case that fired, and the naming is "
            "checkable. Section 6's DECLARED BLIND SPOTS gains the entry described in "
            "D8, including all three declared residuals and the pass/fail-column "
            "legibility note, and a test asserts the new registry's block carries a "
            "CONDITION token and an UNMEASURED token. Failing control: strip either "
            "token in a scratch copy -> the arm reds naming the missing token."
        ),
        covering=(
            "tests/test_gate_budget.py::test_the_startup_condition_registry_carries_its_derivation",
            "tests/test_gate_budget.py::test_the_startup_condition_registry_reddens_when_it_loses_a_token[CONDITION]",
            "tests/test_gate_budget.py::test_the_startup_condition_registry_reddens_when_it_loses_a_token[UNMEASURED]",
        ),
        red=(
            "TOKEN half, RED OBSERVED. Mutated tests/test_import_boundaries.py:3414 "
            "(`#: UNMEASURED: the four `macos-14` legs.` -> `#: the four `macos-14` "
            "legs.`) in a private scratch worktree at base 119f47e. `uv run pytest <the "
            "3 covering ids> -n 2` -> 2 failed: `AssertionError: "
            "STARTUP_COST_CALIBRATED_CONDITIONS's derivation block omits "
            "['UNMEASURED']`; stripping `CONDITION` at :3408 likewise -> `... omits "
            "['CONDITION']`. PROSE half, NO RED: the register entry itself -- :2851 `6. "
            "PDF-86, AND IT IS THE ADJACENT CASE ...` renamed, and separately :2888 "
            "residual `(c) THE INSTRUMENTED CELL.` renamed -- left the 3 covering ids "
            "green and the whole of tests/test_import_boundaries.py + "
            "tests/test_gate_budget.py at `253 passed, 1 xfailed`; no arm reads the "
            "entry, its three residuals or the legibility note. Reverted with `git show "
            "HEAD:tests/test_import_boundaries.py > tests/test_import_boundaries.py`; "
            "`git diff --exit-code` returned 0. Every mutation in this row was made in "
            "a private detached scratch worktree at base 119f47e, never in the shared "
            "worktree."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-86-ac10-register-prose-half-has-no-standing-control",
    ),
    ACAudit(
        ac="AC11",
        claim=(
            "AC11 -- no ceiling, count or bound moves, and the claim is measured. The "
            "four residues are unchanged at 29 / 7 / 6 / 127; `--cov-fail-under=85`, "
            "`PRAGMA_CEILING`, `UNTARGETED_CEILING`, both `RESIDUE_CEILING`s, "
            "`HELP_MODULE_CEILING`, both shipped ratio constants, "
            "`STARTUP_COST_READINGS` and `STARTUP_FLOOR_SANITY_FLOOR_US` "
            "byte-identical. Failing control: lowering the coverage floor by one must "
            "redden the coverage-policy agreement."
        ),
        covering=(
            "tests/test_coverage_policy.py::test_the_floor_has_not_been_weakened_by_any_route",
            "tests/test_gate_parity.py::test_the_coverage_floor_is_defined_only_in_the_makefile",
        ),
        red=(
            "SPEC'S OWN CONTROL, RED OBSERVED: Makefile:107 `--cov-fail-under=85` -> "
            "`84` in a private scratch worktree at base 119f47e -> `uv run pytest "
            "tests/test_coverage_policy.py tests/test_gate_parity.py -n 2` -> 2 failed: "
            "`AssertionError: Makefile declares coverage floor(s) ['84'], expected "
            "exactly one at 85` and `assert 'cov-fail-under=85' in ...`. Residues at "
            "base: 29 / 7 / 6 / 127 (see PDF-82 AC4). THE OTHER EIGHT CONSTANTS, driven "
            "by one-step raises against the five files test_import_boundaries, "
            "test_gate_budget, test_coverage_policy, test_docstring_pointers, "
            "test_docs_antirot (`-n 4`): STARTUP_COST_RATIO_CEILING_PER_MILLE 26_500 -> "
            "27_000 and STARTUP_COST_READINGS 5 -> 6 and STARTUP_FLOOR_SANITY_FLOOR_US "
            "1_700 -> 1_800 each went red, but only through message-text and "
            "probe-count pins; MODULE_SELF_RATIO 470 -> 480, PRODUCT_IMPORT_RATIO 2_600 "
            "-> 2_700, HELP_MODULE_CEILING 320 -> 330, PRAGMA_CEILING 46 -> 47 and "
            "UNTARGETED_CEILING 35 -> 36 each stayed GREEN (`528 passed, 9 skipped, 1 "
            "xfailed`). Byte-identity of those five is guarded by no test: raising them "
            "is the permitted direction of a one-sided ceiling. Each reverted with `git "
            "show HEAD:<path> > <path>`; `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
        finding="PENDING-LEDGER: pdf-86-ac11-five-ceiling-raises-are-green",
    ),
    ACAudit(
        ac="AC12",
        claim=(
            "AC12 -- THE EXECUTION RECEIPT PASSES ON EVERY LEG. "
            "`test_the_section_six_roster_actually_ran_under_the_default_parallelism` "
            "passes unmodified, and its `skipped == []` clause is satisfied by "
            "construction. The counter-control is the whole criterion: plant a "
            "`pytest.skip` on the arm in a scratch copy and confirm the clause reds "
            "naming `['test_total_startup_import_cost_stays_under_its_ceiling']`."
        ),
        covering=(
            "tests/test_gate_budget.py::test_the_section_six_roster_actually_ran_under_the_default_parallelism",
            "tests/test_gate_budget.py::test_the_receipt_reddens_when_a_roster_member_is_taught_to_skip",
            "tests/test_gate_budget.py::test_the_receipt_reddens_on_collection_time_silencing",
        ),
        red=(
            "Counter-control, RED OBSERVED. Mutated "
            'tests/test_import_boundaries.py:4399 (a `pytest.skip("busy")` inserted '
            "before the arm's `assert_startup_cost_in_its_domain(` call) in a private "
            "scratch worktree at base 119f47e. `uv run pytest <the 3 covering ids> -n "
            "2` -> 2 failed, 1 passed: `AssertionError: Section 6 members SKIPPED under "
            "the project's default parallelism: "
            "['test_total_startup_import_cost_stays_under_its_ceiling']` from "
            "tests/test_gate_budget.py:1394, i.e. the receipt names the arm; "
            "test_the_receipt_reddens_on_collection_time_silencing also failed as "
            "collateral. Unmutated, all three pass (6.3 s, the receipt runs a live "
            "pytest subprocess). The macOS-leg half is the CI-observed part (AC15). "
            "Reverted with `git show HEAD:tests/test_import_boundaries.py > "
            "tests/test_import_boundaries.py`; `git diff --exit-code` returned 0. Every "
            "mutation in this row was made in a private detached scratch worktree at "
            "base 119f47e, never in the shared worktree."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC13",
        claim=(
            "AC13 -- `src/`, `.github/`, `pyproject.toml` and the four guarded "
            "documents are untouched. `git show --stat <sha>` lists exactly "
            "`tests/test_import_boundaries.py`, `tests/test_gate_budget.py` and "
            "`changelog.md`. Any fourth file is a BLOCKER."
        ),
        covering=(),
        red=(
            "COMMAND: `git show --stat --format= 76437a8` -> exactly three files, "
            "changelog.md (+8), tests/test_gate_budget.py (+77), "
            "tests/test_import_boundaries.py (1255 lines changed; 1316 insertions, 24 "
            "deletions in all); `git show --stat --format= 76437a8 -- src/ .github/ "
            "pyproject.toml README.md CLAUDE.md CONTRIBUTING.md TESTING.md | wc -l` -> "
            "0 for each pathspec group. A property of one landed commit: no mutation "
            "reds it without rewriting history and no standing arm re-reads it, so no "
            "red is recorded."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-86-ac13-landed-diff-shape-has-no-standing-control",
    ),
    ACAudit(
        ac="AC14",
        claim=(
            "AC14 -- the suite is green in both gates and the cost is reported. One "
            "DCO-signed commit staging explicit paths, subject tagged `[PDF-86]`, one "
            "`## [PDF-86]` entry verified with `git show <sha> -- changelog.md`."
        ),
        covering=(),
        red=(
            "COMMAND: `git show -s --format=%s 76437a8` -> `[PDF-86] test: condition "
            "the total-startup-cost ceiling on the cells it was measured in`; `git show "
            "-s --format=%B 76437a8 | grep -c '^Signed-off-by:'` -> 1 (the trailer sits "
            "in its own paragraph, so `%(trailers)` prints it empty -- read the body, "
            "not the trailers); `git rev-list --count 559183b..76437a8` -> 1; `git show "
            "76437a8 --format= -- changelog.md | grep -cE '^-[^-]'` -> 0, with the `## "
            "[PDF-86]` heading added below the anchor. The AC's gate runs (fmt-check, "
            "lint, typecheck, test, ci, and the zero-subprocess-cost statement) are "
            "landing-time process facts and were not re-run. No red recorded."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-86-ac14-landed-commit-shape-has-no-standing-control",
    ),
    ACAudit(
        ac="AC15",
        claim=(
            "AC15 -- the macOS legs are the last word, and this criterion is an "
            "OBSERVATION, not an assertion. After the change lands and is pushed, the "
            "four `test (3.1x, macos-14)` legs no longer fail on "
            "`tests/test_import_boundaries.py`; the run id, the four job ids and the "
            "four published observations are recorded."
        ),
        covering=(),
        red=(
            "CI-EVIDENCED: queried LIVE at audit time with `gh run view 37230496908 "
            "--json headSha,conclusion,jobs` (ArmandoHerra/pdf-tooling, workflow "
            "ci.yml, main push of 2026-10-04 20:01Z): headSha "
            "119f47e8e2eaf311c6870e4255d77fff215b19e8, conclusion success, 19 jobs. The "
            "four macOS legs: job 111518947001 `test (3.11, macos-14)` success; job "
            "111518947102 `test (3.12, macos-14)` success; job 111518947015 `test "
            "(3.13, macos-14)` success; job 111518947144 `test (3.14, macos-14)` "
            "success. `git merge-base --is-ancestor 76437a8 "
            "119f47e8e2eaf311c6870e4255d77fff215b19e8` -> exit 0, so the run includes "
            "the landing commit. The published observations, read from each job's log "
            "(`gh api repos/ArmandoHerra/pdf-tooling/actions/jobs/<id>/logs`, the "
            "`UncalibratedStartupCondition: STARTUP COST NOT ASSERTED HERE: condition "
            "(darwin, 3.1x) is DECLARED UNMEASURED` warning): 3.11 numerator median "
            "131982 us over 285 rows, denominator 7704 us over 36 rows, ratio median "
            "16.9281; 3.12 162290 / 9961 over 37 / 16.2925; 3.13 136998 / 8455 over 39 "
            "/ 13.9689; 3.14 170628 / 15415 over 47 / 10.6550. Each job summary reads "
            "`5436 passed, 202 skipped, 3 xfailed, 3 warnings` (3.14: `5435 passed, 203 "
            "skipped`), so the execution receipt, which runs inside the suite, passed "
            "on all four. Nothing asserts this AC: it describes one run at one head, "
            "and a later run does not re-evidence it."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-86-ac15-a-ci-run-is-not-a-node-id",
    ),
    ACAudit(
        ac="AC16",
        claim=(
            "AC16 -- the publication channel is proved live, and it is proved to be "
            "able to go dead. Three arms, all in-process: (i) the emission control; "
            "(ii) the not-vacuous control -- the RECORD branch with a hollow census "
            "reds rather than publishing zeros; (iii) the configuration guard reds when "
            "a `filterwarnings` entry that would escalate the warning, or a `-p "
            "no:warnings` in `addopts`, is planted, and passes against the live file."
        ),
        covering=(
            "tests/test_import_boundaries.py::test_the_record_verdict_publishes_through_the_warning_channel",
            "tests/test_import_boundaries.py::test_the_record_verdict_reds_on_a_hollow_census_rather_than_publishing_zeros[short-quorum]",
            "tests/test_import_boundaries.py::test_the_record_verdict_reds_on_a_hollow_census_rather_than_publishing_zeros[collapsed-floor]",
            "tests/test_import_boundaries.py::test_the_record_verdict_reds_on_a_hollow_census_rather_than_publishing_zeros[empty-numerator]",
            "tests/test_import_boundaries.py::test_the_publication_channel_is_not_disabled_by_the_project_configuration",
            "tests/test_import_boundaries.py::test_the_channel_guard_reddens_on_a_silencing_configuration[escalated]",
            "tests/test_import_boundaries.py::test_the_channel_guard_reddens_on_a_silencing_configuration[ignored-by-category]",
            "tests/test_import_boundaries.py::test_the_channel_guard_reddens_on_a_silencing_configuration[plugin-disabled]",
            "tests/test_import_boundaries.py::test_the_channel_guard_reddens_on_a_silencing_configuration[scoped-elsewhere]",
            "tests/test_import_boundaries.py::test_the_channel_guard_reddens_on_a_silencing_configuration[live-shape]",
        ),
        red=(
            "Five mutations, each in a private scratch worktree at base 119f47e against "
            "the 10 covering ids (`-n 2`). (i) tests/test_import_boundaries.py:3807 "
            "`warnings.warn(UncalibratedStartupCondition(observation))` -> `pass` -> 1 "
            "failed: `Failed: DID NOT WARN. No warnings of type (<class "
            "'test_import_boundaries.UncalibratedStartupCondition'>,) were emitted.` "
            "(ii) :3795 `assert min(readings.numerators) > 0` -> `>= 0` -> 1 failed, "
            "`Failed: DID NOT RAISE AssertionError` ([empty-numerator]); :3753 "
            "`len(readings.ratios) == STARTUP_COST_READINGS` -> `>= 1` -> `DID NOT "
            "RAISE` ([short-quorum]). (iii) pyproject.toml:160 `addopts` + ` -p "
            "no:warnings` (the SILENT direction) -> 1 failed: `assert ['addopts car...t "
            "a symptom.'] == []` "
            "(test_the_publication_channel_is_not_disabled_by_the_project_configuration); "
            'and :5243 the guard\'s own shapes tuple minus `"-p no:warnings"` -> 1 '
            "failed: `AssertionError: a silencing configuration went unnoticed: "
            "{'addopts': '--strict-markers -ra -n auto -p no:warnings'}` "
            "([plugin-disabled]). The [collapsed-floor] hollow-census case went red "
            "under the SANITY_FLOOR bump of AC11. Each reverted with `git show "
            "HEAD:<path> > <path>`; `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
)
