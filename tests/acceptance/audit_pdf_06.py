"""`PDF-06`'s 25 acceptance criteria, re-derived — `AUDIT-CONVENTION(PDF-17)`.

The worked example the six sibling specs (`PDF-19`, `PDF-20`, `PDF-21`,
`PDF-24`, `PDF-27`, `PDF-28`) copy. Read Design §9.5 of
`ai_plans/pdf-toolkit/specs/PDF-17_*.md` for the seven rules; this file is what
following them produces.

`PDF-06`'s header reads **Status: Implemented (2026-08-29)**, its criteria are
at `PDF-06:340-376`, and **two of them were filed as BLOCKERs by its own
implementing engineer at landing** (`PDF-06:505-509`) with nobody re-deriving
either since. Both are discharged below, on measurement.

Every `red` names what was changed, what failed, and that it was reverted.
"Would fail if broken" is not a red and `test_red_is_substantive` rejects it.
"""

from __future__ import annotations

from typing import Final

from acceptance._model import ACAudit, RedKind

SPEC_ID: Final[str] = "PDF-06"
AC_COUNT: Final[int] = 25

AUDIT: Final[tuple[ACAudit, ...]] = (
    ACAudit(
        ac="AC1",
        claim=(
            "tests/corpus.py defines the FixtureSpecs named in PLAN.md §9.1 C-06 and "
            "tests/test_corpus.py re-reads each built file with pypdf/pikepdf, asserting it "
            "matches its OWN FixtureSpec -- page count, page size, per-page text, /Rotate "
            "values, metadata dict, encryption algorithm and cell grid."
        ),
        covering=(
            "tests/test_corpus.py::test_every_fixture_matches_its_own_spec[rotated]",
            "tests/test_corpus.py::test_every_fixture_matches_its_own_spec[rotate_absent]",
            "tests/test_corpus.py::test_every_fixture_matches_its_own_spec[encrypted_aes256]",
            "tests/test_corpus.py::test_every_fixture_matches_its_own_spec[tabular]",
            "tests/test_corpus.py::test_the_absent_rotate_state_is_expressible_at_all",
        ),
        red=(
            "The /Rotate clause was VACUOUS and PDF-17 closed it. Both branches of the "
            'rotation assertion read `page.get("/Rotate", 0)`, which answers 0 for an '
            "absent key AND for an explicit /Rotate 0, so 'matches its spec on /Rotate "
            "values' could not distinguish the two states (B-084). RED, measured: with the "
            "new key-presence assertion in place, declaring rotate_key_absent_on=() on the "
            "rotate_absent fixture in tests/corpus.py failed with `rotate_absent: page 0 "
            "carries NO /Rotate key, but its spec does not list page 0 in "
            "rotate_key_absent_on`; the declaration was restored. The corpus grew from 15 "
            "fixtures to 16 and both pikepdf-free `add_blank_page` fixtures were measured "
            "and declared truthfully."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC2",
        claim=(
            "Building the corpus twice into two different temp directories produces "
            "byte-identical files for all unencrypted fixtures; encrypted_aes256 is exempt "
            "by construction and is asserted SEMANTICALLY instead. One test proves both."
        ),
        covering=(
            "tests/test_corpus.py::test_six_unencrypted_fixtures_are_byte_identical_across_two_builds",
            "tests/test_corpus.py::test_the_encrypted_fixture_is_semantically_identical_across_two_builds",
        ),
        red=(
            "The exemption half already carries its own red IN the assertion: "
            "`test_the_encrypted_fixture_is_semantically_identical_across_two_builds` asserts "
            "the two builds DIFFER, so an exemption that stopped being real fails. Measured "
            "for PDF-17's new fixture before adding it: two independent pikepdf saves with "
            "deterministic_id=True hash 862b124025f04c99 both times (1204 bytes), so "
            "rotate_absent joins the byte-identity set rather than needing an exemption. "
            "The test's NAME still says 'six' against 15 unencrypted fixtures; the set "
            "itself is derived from FIXTURE_NAMES and is correct -- filed, not renamed, "
            "because PDF-17 must not move a node id six sibling specs may cite."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: corpus-byte-identity-test-name-says-six",
    ),
    ACAudit(
        ac="AC3",
        claim=(
            "testdata/ contains exactly two binary artifacts plus README.md; "
            "testdata/malformed.pdf is < 8 KB; a strict pypdf read errors while "
            "pikepdf.open() succeeds WITH recovery."
        ),
        covering=(
            "tests/test_testdata.py::test_testdata_holds_exactly_two_artifacts_plus_readme",
            "tests/test_testdata.py::test_malformed_pdf_is_under_the_size_cap",
            "tests/test_testdata.py::test_a_strict_pypdf_read_of_malformed_pdf_errors",
            "tests/test_testdata.py::test_property_4_pikepdf_recovers_with_at_least_one_warning",
        ),
        red=(
            "NOT re-observed red by PDF-17. Re-run literally at implementation HEAD and "
            "PASSING: testdata/ holds exactly malformed.pdf, scanned-page.png and README.md, "
            "and malformed.pdf is 439 bytes (< 8192). The mechanization is wired into the "
            "suite, so its rot would be caught, but no mutation was applied here -- "
            "PDF-17's scope is the contract harness and the coverage floor, and mutating "
            "testdata/ is out of it."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-06-ac3-covered-but-red-not-observed",
    ),
    ACAudit(
        ac="AC4",
        claim=(
            "testdata/README.md names both artifacts, each one's provenance, "
            "malformed.pdf's exact defect and the spec that consumes it. Mechanized: "
            "grep -c 'malformed.pdf\\|scanned-page.png' testdata/README.md returns >= 2."
        ),
        covering=("tests/test_testdata.py::test_readme_documents_both_artifacts",),
        red=(
            "NOT re-observed red by PDF-17. Its own mechanization was re-run at "
            "implementation HEAD and returns 5 (>= 2), and unlike AC5/AC11 it is ALSO "
            "wired into the suite as a real test, which is why it has not rotted. No "
            "mutation applied: editing testdata/README.md is outside PDF-17's scope."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-06-ac4-covered-but-red-not-observed",
    ),
    ACAudit(
        ac="AC5",
        claim=(
            "discover_verbs() walks the live Typer/click tree recursively and contains NO "
            "skip list, no filter and no hard-coded verb name. Mechanized: "
            "grep -nE 'SKIP|EXCLUDE|IGNORE' tests/registry.py returns nothing."
        ),
        covering=(
            "tests/test_derived_dimensions.py::test_pdf_06_ac5_the_registry_carries_no_skip_list",
            "tests/test_derived_dimensions.py::test_the_skip_list_scan_reads_bindings_and_not_prose",
            "tests/test_derived_dimensions.py::test_no_typed_verb_list_survives_anywhere_under_tests",
        ),
        red=(
            "AC5'S OWN MECHANIZATION IS BROKEN AND THAT IS THIS ROW'S RED. Re-run verbatim "
            "at implementation HEAD, `grep -nE 'SKIP|EXCLUDE|IGNORE' tests/registry.py` "
            "returns TWO hits (:183, :790 post-PDF-17) against a required nothing. Both are "
            "PROSE in docstrings describing skip BEHAVIOUR; there is no skip list and the "
            "property HOLDS. The CHECK fails while the CLAIM is true -- a naive uppercase "
            "substring scan, the same family as B-026's naive lowercase forbidden-name scan. "
            "Repaired by scanning BINDINGS instead of characters, and the repair's own red "
            "is pinned: `skip_list_bindings(\"SKIP_VERBS = ('info',)\")` returns "
            "['SKIP_VERBS'] while the same scan over the two real docstring lines returns []."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC6",
        claim=(
            "pytest tests/test_cli_contract.py --collect-only shows at least one contract "
            "test node per verb, and pytest -m e2e --collect-only collects a NON-ZERO "
            "number of items -- so make test-e2e is not a target that passes by doing "
            "nothing."
        ),
        covering=(
            "tests/test_cli_contract.py::test_every_population_is_non_empty[VERBS]",
            "tests/test_cli_contract.py::test_every_population_is_non_empty[GROUPS]",
            "tests/test_cli_contract.py::test_every_population_is_non_empty[MUTATING]",
            "tests/test_cli_contract.py::test_every_population_is_non_empty[DESTRUCTIVE]",
            "tests/test_cli_contract.py::test_every_population_is_rostered",
            "tests/test_cli_contract.py::test_a_population_pin_fires",
        ),
        red=(
            "AC6 IS ITSELF A CONTROL THAT CANNOT FAIL FOR THE THING IT APPEARS TO PROTECT, "
            "and PDF-17's Objective names it as the failure mode the whole spec exists to "
            "prevent. `pytest -m e2e --collect-only` returns 947 items at implementation "
            "HEAD and returned non-zero at PDF-06 landing too -- AT THE VERY COMMIT WHERE "
            "C4, C9, C10, C11 AND C13 EACH COLLECTED ZERO CASES. An aggregate non-emptiness "
            "pin is structurally blind to a per-population zero, which is exactly how "
            "DESTRUCTIVE sat empty from PDF-06 through PDF-14 while the bulk confirmation "
            "gate went unwired on five verbs. What discharges AC6's INTENT is the "
            "per-population roster PDF-17 added: RED, observed, `test_a_population_pin_fires` "
            "emptying each of the 16 rostered populations in turn and requiring the failure "
            "to name the population AND the checks it feeds. The aggregate check is retained "
            "as covering only because it is true, not because it is sufficient."
        ),
        red_kind=RedKind.DELETED_ROW,
    ),
    ACAudit(
        ac="AC7",
        claim=(
            "For every verb, <verb> --help exits 0 with non-empty stdout containing the "
            "verb's own name, and its PLAN.md §4.2 global-flag block matches root's "
            "(checks C1, C2)."
        ),
        covering=(
            "tests/test_cli_contract.py::test_c1_help_exits_0_and_names_itself[info]",
            "tests/test_cli_contract.py::test_c2_global_flag_block_matches_root[info]",
            "tests/test_cli_contract.py::test_every_population_is_non_empty[VERBS]",
            "tests/test_cli_contract.py::test_every_population_is_non_empty[GLOBAL_OPTIONS]",
        ),
        red=(
            "C2 CARRIED AN UNGUARDED SECOND VACUITY AXIS AND PDF-17 CLOSED IT. Its "
            "assertions live inside `for option in GLOBAL_OPTIONS`, and GLOBAL_OPTIONS is "
            "the PRODUCT's tuple imported from pdf_toolkit.cli.common -- an empty one makes "
            "C2 report 26 green cases having asserted nothing, with VERBS non-empty "
            "throughout. RED, observed: `test_a_population_pin_fires` empties GLOBAL_OPTIONS "
            "and the pin fails with `GLOBAL_OPTIONS has 0 member(s), below its floor of 1 -- "
            "the check(s) it feeds (C2, test_root_help_exits_0_and_lists_every_global_flag) "
            "would then collect zero parametrized cases`. GLOBAL_OPTIONS is one of the two "
            "IMPORTED populations PDF-17 rostered."
        ),
        red_kind=RedKind.DELETED_ROW,
    ),
    ACAudit(
        ac="AC8",
        claim=(
            "For every verb an unknown flag exits 2; every grouping parent exits 2 on a "
            "bogus subcommand; every takes_input_paths verb exits 4 on a nonexistent path; "
            "every is_page_addressing verb exits 2 on --pages 1--3; --no-backup without "
            "--in-place exits 2; no verb emits an ANSI escape through a pipe (C3-C8)."
        ),
        covering=(
            "tests/test_cli_contract.py::test_c3_unknown_flag_exits_2[info]",
            "tests/test_cli_contract.py::test_c4_bogus_subcommand_on_a_group_exits_2[meta]",
            "tests/test_cli_contract.py::test_c5_nonexistent_input_exits_4[info]",
            "tests/test_cli_contract.py::test_c6_malformed_page_range_exits_2[extract]",
            "tests/test_cli_contract.py::test_c7_no_backup_alone_exits_2[info]",
            "tests/test_cli_contract.py::test_c8_no_ansi_on_a_pipe[info]",
            "tests/test_cli_contract.py::test_every_population_is_non_empty[PAGE_ADDRESSING]",
            "tests/test_cli_contract.py::test_every_population_is_non_empty[TAKES_INPUT_PATHS]",
            "tests/test_cli_contract.py::test_every_population_is_non_empty[GROUPS]",
        ),
        red=(
            "THREE OF AC8's SIX CHECKS RAN OVER UNPINNED POPULATIONS UNTIL PDF-17. C4's "
            "GROUPS collected ZERO cases at PDF-06 landing (no grouping parent existed "
            "below root until PDF-14's `meta`) and nothing said so; C5's TAKES_INPUT_PATHS "
            "and C6's PAGE_ADDRESSING were never pinned at all -- and B-032 filed the "
            "opposite, claiming PAGE_ADDRESSING WAS pinned. Measured at 2d19bcb: "
            "`grep -n 'assert len(' tests/test_cli_contract.py` returned exactly TWO lines "
            "(:364 DESTRUCTIVE, :718 IN_PLACE_OUTPUT_CONFLICT_VERBS) against 15 populations. "
            "RED, observed for each: `test_a_population_pin_fires` empties GROUPS, "
            "TAKES_INPUT_PATHS and PAGE_ADDRESSING in turn and the pin names each one and "
            "the check it feeds. GROUPS additionally carries a roster note that its single "
            "member makes the pin necessary and NOT sufficient."
        ),
        red_kind=RedKind.DELETED_ROW,
    ),
    ACAudit(
        ac="AC9",
        claim=(
            "For every is_mutating verb a --dry-run leaves the tree byte-identical whatever "
            "its exit code (C9); every registered invocation's dry run is pure (C10); "
            "no-clobber exits 5 (C11); stdout on a pipe with no -o parses as JSON carrying "
            "schema_version (C12); bulk destructive non-TTY without -y exits 5 while the "
            "same run with -y succeeds (C13)."
        ),
        covering=(
            "tests/test_cli_contract.py::test_c9_unconditional_dry_run_purity[compress]",
            "tests/test_cli_contract.py::test_c10_registered_invocation_dry_run_purity[compress]",
            "tests/test_cli_contract.py::test_c11_no_clobber_exits_5[merge]",
            "tests/test_cli_contract.py::test_c12_json_on_a_pipe_by_default[info]",
            "tests/test_cli_contract.py::test_c13_bulk_destructive_requires_y_on_a_non_tty[compress]",
            "tests/test_cli_contract.py::test_a_destructive_row_supplies_its_own_bulk_argv[compress]",
            "tests/test_cli_contract.py::test_the_destructive_argv_guard_fires_on_a_missing_row",
        ),
        red=(
            "C13's HALF OF AC9 WAS REINSTATABLE AND PDF-17 CLOSED THE DOOR. B-047: one argv "
            "tail was shared by C10 (must exit 0), C12 (must exit 0) and C13 (must exit 5), "
            "and one invocation cannot satisfy both C12 and C13. B-079 added "
            "Invocation.destructive_build -- but the DOCUMENTED FALLBACK "
            "(`destructive_build or build`) meant the next destructive=True row written "
            "without one would silently re-share C12's single-input -O tail, C13 would stop "
            "discriminating, and no test would fail. RED, observed by hand: setting "
            "INVOCATIONS['compress'].destructive_build to None in tests/registry.py made "
            "`test_a_destructive_row_supplies_its_own_bulk_argv[compress]` fail with "
            "`tests/registry.py::INVOCATIONS['compress'] is destructive=True with "
            "destructive_build=None`; the file was restored with `git show HEAD:` (never "
            "git stash, HC-4). The fallback is now DELETED rather than pragma-ed."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC10",
        claim=(
            "The harness fails when a verb is registered in the CLI but absent from the "
            "contract collection. test_every_verb_is_registered names the missing verb and "
            "the file to edit. Coverage cannot silently lapse."
        ),
        covering=(
            "tests/test_cli_contract.py::test_every_verb_is_registered",
            "tests/test_cli_contract.py::test_the_anti_lapse_guard_fires_when_a_verb_is_unregistered",
        ),
        red=(
            "ALREADY RECORDED, AND IT IS THIS CONVENTION'S HOUSE PRECEDENT. PDF-06:513 "
            "records the manual cycle its own engineer ran: one INVOCATIONS row deleted, "
            "the named failure observed, the file restored, the suite re-run green. PDF-17 "
            "re-derived the automated half at implementation HEAD -- "
            "`test_the_anti_lapse_guard_fires_when_a_verb_is_unregistered` monkeypatches a "
            "live-discovered verb out of INVOCATIONS and asserts the same set difference "
            "reports it -- and it passes over 26 registered verbs. This is the row every "
            "other row in this file is modelled on: a mutation, a named failure, a restore."
        ),
        red_kind=RedKind.DELETED_ROW,
    ),
    ACAudit(
        ac="AC11",
        claim=(
            "Exactly ONE tree-snapshot/purity helper exists in the repository. Mechanized: "
            "grep -rn 'def snapshot_tree' tests/ src/ | wc -l returns 1."
        ),
        covering=(
            "tests/test_derived_dimensions.py::test_pdf_06_ac11_exactly_one_tree_snapshot_helper_exists",
            "tests/test_derived_dimensions.py::test_the_snapshot_helper_scan_can_find_a_second_one",
        ),
        red=(
            "AC11'S OWN MECHANIZATION RETURNS THE WRONG ANSWER AND HAS DONE SILENTLY. "
            "Re-run verbatim at implementation HEAD, `grep -rn 'def snapshot_tree' "
            "tests/ src/ | wc -l` returns 0 against a required 1: the helper was renamed to "
            "snapshot() at tests/fs_snapshot.py:170 and the AC's grep names a function that "
            "does not exist. It rotted invisibly because NOTHING RUNS IT -- it is a prose "
            "recipe in a markdown file. That is the structural finding behind this whole "
            "convention. Repaired as a TEST asserting AC11's PROPERTY (exactly one helper) "
            "rather than one spelling of a name, and the repair's own RED is pinned: a "
            "planted `def snapshot_tree(root)` under tmp_path is reported, and a function "
            "that merely MENTIONS snapshots is not."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC12",
        claim=(
            "pdftoolkit --help completes in under 250 ms (best of five), asserted by a "
            "test -- PLAN.md §12 R-13. Omitted only if PDF-01 already shipped an equivalent, "
            "in which case the Implementation Log names that test."
        ),
        covering=("tests/test_cli_spine.py::test_help_stays_within_the_startup_budget",),
        red=(
            "Discharged by PDF-01's own test, which PDF-06 correctly names in place of "
            "shipping a second one (tests/test_cli_contract.py's own closing comment). "
            "PDF-17 touched it from a different angle and that is this row's red: the "
            "budget test is THE ONE test in the suite that scrubs COVERAGE_PROCESS_START/"
            "COVERAGE_PROCESS_CONFIG from a child environment, and nothing pinned it at one. "
            "RED, observed: planting a second scrubbing module under a synthetic tests/ tree "
            "makes `coverage_scrub_sites` return it, and the real pin "
            "`test_exactly_one_test_module_scrubs_the_coverage_environment` compares against "
            "the singleton ['tests/test_cli_spine.py']."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC13",
        claim=(
            "uv run pytest is green with all engines present, and green again under "
            "PDF_TOOLKIT_TEST_HIDE_ENGINES=tesseract,soffice, where the second run reports a "
            "NON-ZERO count of visible skips, asserted mechanically from --junitxml. Engines "
            "are hidden by a PATH-shadowing symlink directory; no system binary is renamed, "
            "moved or chmod-ed."
        ),
        covering=(
            "tests/integration/test_or7_engine_absent.py::test_or7_absent_engine_dry_run_mirrors_the_real_exit_code[convert-soffice-absent]",
            "tests/integration/test_or7_engine_absent.py::test_or7_absent_engine_dry_run_mirrors_the_real_exit_code[ocr-tesseract-absent]",
            "tests/integration/test_ocr.py::test_ac12_engine_hidden_exits_3_names_doctor_no_traceback",
        ),
        red=(
            "NOT re-observed red by PDF-17. The engine-hiding shim was exercised at "
            "implementation HEAD -- both engines resolve on this host "
            "(/usr/bin/soffice, /usr/bin/tesseract), so C12/C14's convert rows RAN rather "
            "than skipping, which is what makes PDF-17's C14 rebuild measurable over all 53 "
            "declared cells. The engines-ABSENT arm and its non-zero visible-skip count are "
            "a `make ci`-external, two-run junitxml comparison that PDF-17 did not execute, "
            "and asserting a skip count is not something a single suite run can do."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-06-ac13-engines-absent-arm-not-re-run",
    ),
    ACAudit(
        ac="AC14",
        claim=(
            "Coverage on src/pdf_toolkit is >= 85% under --cov-fail-under=85, with NO omit "
            "of anything under src/pdf_toolkit/ and fail_under unchanged from 85; make ci "
            "runs cover, not test. If 85% proves unreachable the engineer reports a BLOCKER "
            "rather than adjusting either knob."
        ),
        covering=(
            "tests/test_coverage_policy.py::test_the_floor_has_not_been_weakened_by_any_route",
            "tests/test_coverage_policy.py::test_the_pragma_total_has_not_been_raised",
            "tests/test_coverage_policy.py::test_every_pragma_carries_a_reason",
            "tests/test_coverage_policy.py::test_the_floor_interpreter_still_needs_the_branch_deviation",
            "tests/test_coverage_policy.py::test_the_branch_support_boundary_is_where_it_was_measured",
        ),
        red=(
            "FILED AS A BLOCKER BY PDF-06's OWN ENGINEER AT LANDING (PDF-06:507, measured "
            "71.29% against a required 85) AND DISCHARGED HERE ON MEASUREMENT: 94.00% line "
            "coverage over 6049 statements at implementation HEAD, floor reached, no `omit` "
            "key anywhere, `--cov-fail-under=85` present in exactly two places (Makefile:78, "
            ".github/workflows/ci.yml:136) and unchanged -- and there is no `fail_under` KEY "
            "in pyproject.toml at all, contrary to how the AC is usually read. WHAT WEAKENED "
            "IS THE PROPERTY, NOT THE NUMBER: branch = false, so 85 now enforces LINE "
            "coverage. Measured fresh, both arms, same band (tests/test_doctor.py + "
            "tests/test_info.py, 55 tests, quiet host): branch=false/core=sysmon 24.93 s at "
            "46%, branch=true 486.56 s at 39% -- a 19.5x factor, with coverage 7.16.0 "
            "emitting `Can't use core=sysmon: sys.monitoring can't measure branches in this "
            "version`. branch = false STAYS and the key was not touched -- AND the expiry alarm "
            "PDF-17 added FIRED FOR REAL on its first pushed run: CPython 3.14 already "
            "supports branch measurement under sys.monitoring (measured on 8 CI "
            "interpreters, run 33588614762), so the deviation has expired on 3.14 while "
            "still holding on the 3.13 the floor is enforced on. RED, observed: "
            "adding an unreasoned `# pragma: no cover` is reported by "
            "`unreasoned_pragmas`, and the 46-pragma ceiling fires when exceeded -- closing "
            "the third gaming lever AC14's anti-gaming rule left open."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
    ),
    ACAudit(
        ac="AC15",
        claim=(
            "The samples fixture exposes exactly available, names(), copy(name) and "
            "copy_tree(name), and NO member returning a path under "
            "$PDF_TOOLKIT_SAMPLES_DIR. copy()/copy_tree() return user-writable paths inside "
            "tmp_path; an unknown name calls pytest.fail (never skip)."
        ),
        covering=(
            "tests/test_samples.py::test_ac15_fixture_exposes_exactly_four_public_members",
            "tests/test_samples.py::test_ac15_available_and_names_never_leak_a_path",
            "tests/test_samples.py::test_an_unknown_name_fails_rather_than_skips",
            "tests/test_samples.py::test_copy_never_hands_back_a_path_under_the_originals_root",
        ),
        red=(
            "NOT re-observed red by PDF-17. All four covering tests run WITHOUT the corpus "
            "(they are not @samples arms -- they interrogate the fixture object, not real "
            "documents) and pass at implementation HEAD. No mutation was applied: the "
            "samples apparatus is outside PDF-17's scope, which is the contract harness and "
            "the coverage floor."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-06-ac15-covered-but-red-not-observed",
    ),
    ACAudit(
        ac="AC16",
        claim=(
            "The originals guard FAILS THE SESSION, naming the file, when an original "
            "changes -- it does not warn, log or merely count. Proven two ways: "
            "diff_manifest unit tests over a synthetic tmp directory, and an inner pytest "
            "session against a SYNTHETIC samples directory. The operator's real corpus is "
            "never used to prove the guard. Guarded controller-only so it still runs under "
            "-n auto."
        ),
        covering=(
            "tests/integration/test_samples_guard_fires.py::test_the_guard_fails_the_inner_session_and_names_the_mutated_file",
            "tests/integration/test_samples_guard_fires.py::test_the_guard_never_fires_when_nothing_is_mutated",
            "tests/integration/test_samples_guard_fires.py::test_the_guard_runs_exactly_once_under_dash_n_2",
            "tests/unit/test_samples_guard.py::test_content_change_is_reported_by_name",
        ),
        red=(
            "AC16 IS THE ONE PDF-06 CRITERION THAT ALREADY CARRIES ITS OWN RED BY "
            "CONSTRUCTION, and PDF-17 confirmed it runs corpus-free: "
            "test_the_guard_fails_the_inner_session_and_names_the_mutated_file spawns an "
            "inner pytest session over a SYNTHETIC samples directory whose test mutates an "
            "'original', and asserts the outer guard exits non-zero naming that file. It is "
            "green at implementation HEAD with PDF_TOOLKIT_SAMPLES_DIR unset, so unlike the "
            "@samples arms it is not skipped and not vacuous. No further mutation applied."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC17",
        claim=(
            "No file under testdata/ shares a SHA-256 with any file in "
            "$PDF_TOOLKIT_SAMPLES_DIR (rule 4). Asserted by a test that skips visibly when "
            "the corpus is absent."
        ),
        covering=(
            "tests/test_testdata.py::test_no_testdata_file_shares_a_hash_with_a_real_sample",
        ),
        red=(
            "NOT re-observed red, and it CANNOT be without the corpus. The covering test is "
            "a @samples arm and SKIPPED at implementation HEAD with the reason "
            "'PDF_TOOLKIT_SAMPLES_DIR not set -- real-document arm skipped (PLAN.md §10.1 "
            "rule 5)'. HC-2 rules that a skipped control is recorded NOT_OBSERVED with a "
            "finding and never as a pass, and PDF-17's own local gate deliberately ran "
            "corpus-free so the committed evidence is reproducible on CI, which is forbidden "
            "from ever setting that variable (B-R01)."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-06-ac17-samples-arm-skipped-at-verification",
    ),
    ACAudit(
        ac="AC18",
        claim=(
            "With the corpus absent, EVERY @samples test reports as SKIPPED, never as "
            "PASSED, and the visible skip count is non-zero. Proven by comparing two "
            "--junitxml runs: every node id collected under -m samples with the variable set "
            "appears as <skipped> in the run with it unset."
        ),
        covering=(),
        red=(
            "NOT OBSERVED AND NOT COVERED BY ANY TEST. AC18's mechanism is `make "
            "samples-gate`, a Makefile target that runs two pytest sessions and compares "
            "their junitxml -- a LOCAL AND SENTINEL gate, never a CI job, and never part of "
            "`make ci` (Makefile:167-176 states the reason: it needs the real corpus and "
            "copies every original). It is therefore not reachable from the suite, and "
            "PDF-17 ran corpus-free, so neither arm of the comparison exists in this run. "
            "The unset arm's assertion is real and well-argued in the Makefile "
            "(SAMPLES_UNSET_ASSERT fails on any pass AND on zero collected tests), but "
            "nothing in the test suite exercises it and nothing would notice if it rotted -- "
            "which is `PDF-06` AC5/AC11's exact failure mode in a third instrument."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-06-ac18-samples-gate-unreachable-from-the-suite",
    ),
    ACAudit(
        ac="AC19",
        claim=(
            "With PDF_TOOLKIT_SAMPLES_DIR set, pytest -m samples passes AND the originals' "
            "SHA-256 manifest is byte-identical before and after, verified by an EXTERNAL "
            "sha256sum -c witness taken outside the suite -- so the guard cannot vouch for "
            "itself."
        ),
        covering=(),
        red=(
            "NOT OBSERVED AND NOT COVERED BY ANY TEST, BY DESIGN. AC19's witness is "
            "deliberately EXTERNAL to pytest (`make samples-scratch` then `make "
            "samples-check`, which shells out to sha256sum -c), precisely so the guard "
            "cannot vouch for itself -- so no node id can cover it and none is claimed. "
            "PDF-17 ran corpus-free, so the witness was not taken."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-06-ac19-external-witness-not-taken",
    ),
    ACAudit(
        ac="AC20",
        claim=(
            "make samples-scratch && make samples-check exits 0; afterwards git status "
            "--porcelain produces no output and git check-ignore -q .scratch succeeds. "
            "samples-scratch exits non-zero with a clear message when the variable is unset; "
            "samples-check exits non-zero when the manifest is missing or an original "
            "changed, naming the file; make clean removes .scratch/."
        ),
        covering=(
            "tests/test_cli_spine.py::test_gitignore_covers_scratch_but_not_the_generated_license_manifest",
        ),
        red=(
            "PARTIALLY covered and NOT re-observed red. The untracked-ness half is a real "
            "test and passes at implementation HEAD. The Makefile-behaviour half (three exit "
            "codes and their messages) is covered by nothing in the suite: it lives in "
            "Makefile recipes, PDF-28 owns local-gate/CI-gate equivalence, and PDF-17 is "
            "forbidden from editing the Makefile at all. PDF-17 ran corpus-free so "
            "samples-scratch could not be exercised."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-06-ac20-makefile-samples-targets-uncovered",
    ),
    ACAudit(
        ac="AC21",
        claim=(
            "Privacy (rule 4) holds across every committed artifact, including the "
            "Implementation Log. Nothing beyond filename, page count, size and hash about "
            "any sample appears in changelog.md, TESTING.md, testdata/README.md or the "
            "Implementation Log. Mechanized: git grep -n 'Downloads/Sample_Documents' "
            "returns nothing."
        ),
        covering=(),
        red=(
            "AC21 IS COVERED BY NO TEST AT ALL, and this row is how PDF-17 found that out: "
            "the covering node id was written from the AC's own description, and "
            "`test_every_covering_node_id_resolves` refused it -- which is the aggregator "
            "doing precisely the job `PDF-06` AC11's unrun grep could not. Re-run verbatim "
            "at implementation HEAD, `git grep -n 'Downloads/Sample_Documents'` inside "
            "apps/pdf-toolkit returns NOTHING, and it stayed nothing across PDF-17's own "
            "commit -- which matters, because PDF-17's brief supplies the operator's "
            "absolute corpus path and this spec's Implementation Log records a corpus-free "
            "gate. But the check is a grep in a markdown file that nothing executes: "
            "AC5/AC11's failure mode in a THIRD instance, in the criterion that protects "
            "the operator's privacy. NOT filled with a newly written passing assertion "
            "(PDF-17 AC30 forbids it); filed. Nor is a red plantable: the mutation this row "
            "would need is writing the operator's absolute directory into a committed "
            "artifact, which is itself the HC-2 violation."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-06-ac21-privacy-grep-is-covered-by-no-test",
    ),
    ACAudit(
        ac="AC22",
        claim=(
            "Exactly one commit, DCO-signed, subject-tagged [PDF-06], staged by explicit "
            "paths, with a changelog.md entry. git show --stat <sha> does not list uv.lock, "
            "and the pyproject.toml diff touches only [tool.pytest.ini_options] and "
            "[tool.coverage.*] -- never [project]."
        ),
        covering=(
            "tests/test_cli_spine.py::test_changelog_prepends_every_spec_entry_below_the_anchor",
        ),
        red=(
            "A LANDING-STATE criterion about PDF-06's own commit, so the only durable part "
            "is the changelog invariant, which IS covered and IS an instrument: "
            "test_changelog_prepends_every_spec_entry_below_the_anchor has been generalized "
            "three times (PDF-02, PDF-04/X-67, PDF-08) rather than weakened, and asserts "
            "prepend-at-the-anchor plus non-increasing dates plus per-spec remediation "
            "ordering. PDF-17 exercised it: this spec's own changelog entry had to satisfy "
            "it before `make ci` went green. NOT re-observed red -- PDF-06's commit is "
            "immutable history and `git show --stat` over it is a one-shot check, not a "
            "control."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-06-ac22-landing-state-not-a-control",
    ),
    ACAudit(
        ac="AC23",
        claim=(
            "Any src/ change is a bounded conformance fix of <= 20 changed lines total, "
            "each justified in the Implementation Log. More than that was reported as a "
            "BLOCKER instead of committed."
        ),
        covering=(),
        red=(
            "A LANDING-STATE criterion about PDF-06's own diff, covered by no test and "
            "coverable by none -- `git show --stat <sha> -- src/` over a landed commit is a "
            "one-shot audit. PDF-17 did not inherit the allowance: its own src/ budget is "
            "ZERO lines and `git show --stat` over PDF-17's commit lists no file under "
            "src/pdf_toolkit/, which is a stronger statement about this commit but says "
            "nothing about PDF-06's."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-06-ac23-landing-state-not-a-control",
    ),
    ACAudit(
        ac="AC24",
        claim=(
            "TESTING.md documents corpus generation, every marker, how to run each suite, "
            "the samples setup, and the expected skip counts for the engines-present and "
            "engines-absent configurations. Mechanized: grep -c "
            "'PDF_TOOLKIT_SAMPLES_DIR\\|PDF_TOOLKIT_TEST_HIDE_ENGINES\\|samples-scratch' "
            "TESTING.md returns >= 3."
        ),
        covering=(
            "tests/test_docs_antirot.py::test_every_documented_make_target_exists[TESTING.md]",
        ),
        red=(
            "Its own mechanization was re-run at implementation HEAD and returns 10 (>= 3). "
            "NOT re-observed red, and the gap is real: what IS covered by a test is that "
            "every make target TESTING.md names exists; the CONTENT clauses (markers, skip "
            "counts) are covered by the grep only, and the grep lives in a markdown file "
            "nothing executes -- AC5/AC11's failure mode again. TESTING.md's doc claims are "
            "PDF-30's subject and PDF-17 is forbidden from editing it. B-099 already "
            "corrected one quoted skip count in TESTING.md that was low by one, which is "
            "the same class arriving in the same file."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-06-ac24-testing-md-content-clauses-uncovered",
    ),
    ACAudit(
        ac="AC25",
        claim=(
            "make ci passes locally AND the pushed ci.yml run is green (decision.md §4 wave "
            "gate: gate on a pushed green CI run, not on a local make ci)."
        ),
        covering=(),
        red=(
            "FILED AS A BLOCKER BY PDF-06's OWN ENGINEER AT LANDING (PDF-06:509 -- local "
            "make ci did not pass at that commit, blocked by AC14's 71.29%) AND DISCHARGED "
            "HERE ON MEASUREMENT. Local: `make ci` green at implementation HEAD 2d19bcb, "
            "tree clean, quiet host (nproc 8, loadavg 1.03 -> 1.80), 572.575 s, 1857 passed "
            "/ 30 skipped, coverage 94.00%. Pushed: GitHub Actions run 33374363503 at "
            "2d19bcb, conclusion success, TALLIED BY HAND with `gh` rather than read off a "
            "summary line -- TEN JOBS, SEVENTEEN CHECKS (lint, typecheck, engines-present, "
            "without-engines, sast, vulncheck, secret-scan, license-gate, build, plus `test` "
            "as a 4-Python x 2-OS matrix = 8 legs). PDF-06:489's own log says 'all 17 jobs "
            "green', which X-160 corrected: 17 is the CHECK count, not the job count. "
            "Covered by no test, and coverable by none -- a CI run is not a node id."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-06-ac25-ci-run-is-not-a-node-id",
    ),
)
