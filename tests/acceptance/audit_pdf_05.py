"""`PDF-05`'s 18 acceptance criteria, re-derived — `AUDIT-CONVENTION(PDF-17)`.

`PDF-05` is the engine seam: six `Protocol` ports behind a `resolve()` registry,
eight probe-and-version adapters, the product's single process-spawn point, and
the two verbs that make the seam observable — `doctor` and `info`. Its roster row
reads `Implemented (2026-08-29)` and its 18 criteria were granted in one pass by
the method the `qa-sentinel` later withdrew on its own motion. This module is the
evidence for that first re-grant or refusal, produced by `PDF-20`. The
`qa-sentinel` grants or refuses; this module does not.

**Verdict counts — 15 `holds` · 1 `inverted` · 1 `not-met` · 1 `no-live-control`
= 18.**

`ACAudit` has no `verdict` field and `_model.py` is frozen, so `PDF-27`'s
vocabulary is mapped onto the landed fields — the declared deviation
`audit_pdf_04.py` established, reused rather than reinvented (Design §9.2 / R2):

* **`holds`** — MET at the audited HEAD **and** grounded in a control this audit
  drove RED, with the mutation, the failure text and the revert recorded in
  `red`. AC1, AC2, AC3, AC4, AC5, AC6, AC7, AC8, AC9, AC11, AC12, AC13, AC14,
  AC15, AC18 — fifteen.
* **`inverted`** — a covering test exists and **cannot fail for one of the two
  halves it claims**. AC10: `start_new_session=False` — the exact mutation
  `PDF-05` AC10 names as its red — leaves
  `test_timeout_kills_the_whole_group_including_a_forked_grandchild` GREEN (in
  300.25 s) and leaves `test_a_normal_run_leaves_no_group_behind_either` GREEN
  in 0.25 s **while a `sleep 30` grandchild survives the run**. The group-vs-PID
  half IS live and was driven red. Filed, not repaired — `audit_pdf_04.py` AC11
  is the precedent: an audit makes no repair to the mechanism it audits.
* **`not-met`** — AC16. `tests/corpus.py` exists, the marker still sits at
  `tests/test_info.py:38`, and `tests/test_info.py` still builds its three
  fixtures inline. The handoff AC16 mechanised was never carried out, so the
  grep it specifies is green for the opposite of its intended meaning.
* **`no-live-control`** — AC17, a one-shot assertion about a commit that has
  already happened. Re-checked and true; it cannot go red for future work, so it
  is recorded as carrying no live control **by construction** and is not counted
  as one. `PDF-20`'s own commit meets the same standard, and that half is
  checkable going forward.

**Every `red` below was applied inside a scratch `git worktree` under `$TMPDIR`
whose `src/` and `tests/` are a copy of the working tree, never in
`apps/pdf-toolkit` (HC-4 — `git stash` is never used).** X-210's hazard was
defended twice on every arm: each run carried `PYTHONPATH=<scratch>/src`
(verified once by asserting `pdf_toolkit.__file__` starts with the scratch path),
and each mutation was proven present in the scratch file before its arm ran.
Restoration was verified by a sha256 manifest over all thirteen mutated files
against the real tree — thirteen matches, zero mismatches. **The copied
`__pycache__` trees were removed from the scratch first**: `cp -a` preserves
mtimes, so a stale `.pyc` satisfies Python's freshness check and renders
tracebacks against the ORIGINAL source path — a second, quieter shape of the
same hazard, caught by reading a traceback that named the real repository.

**Findings are reported to the `project-manager`, not filed here.** The wave-3
brief makes `qa/FINDINGS-LEDGER.md` read-only to this spec, so each `finding`
below carries a `PENDING-LEDGER:` slug in the convention `audit_pdf_03.py`,
`audit_pdf_04.py` and `audit_pdf_06.py` established. Rows citing an EXISTING
fingerprint (`ba07fdfb56`, `d4ae996c52`) name it directly.

**Four `PDF-20` spec pointers were measured wrong and are recorded here rather
than transcribed** — the pointers are corrected in `PDF-20`'s dispatch report:
`Makefile`'s `ci:` target is at `:274`, not `:221`; `PDF-05` AC8's covering test
drives the TESSERACT adapter, so mutating `soffice_office._parse_version` (the
line `PDF-20` names) produces no red; `PDF-05` AC14's per-item directory refusal
(`ops/inspect.py:124`) is unreachable from the CLI, shadowed by the pre-flight at
`:98`; and AC20's prescribed red cannot fire on this host at all (see AC20's
note in `PDF-20`'s report — `os.get_exec_path` falls back to `os.defpath`).
"""

from __future__ import annotations

from typing import Final

from acceptance._model import ACAudit, RedKind

SPEC_ID: Final[str] = "PDF-05"
AC_COUNT: Final[int] = 18

AUDIT: Final[tuple[ACAudit, ...]] = (
    ACAudit(
        ac="AC1",
        claim=(
            "`doctor -o json | jq '.ports | length'` prints 6. Every element carries a non-null "
            "`port`, `available` and `kind`, and a `version` key is present (possibly null) -- "
            "asserted as a count and a key check, never by eyeballing output."
        ),
        covering=(
            "tests/test_doctor.py::test_doctor_reports_exactly_six_ports",
            "tests/test_doctor.py::test_every_row_carries_the_keys_a_consumer_reads",
            "tests/unit/test_ports_registry.py::test_there_are_exactly_six_ports_in_a_pinned_order",
            "tests/unit/test_ports_registry.py::test_resolve_all_returns_one_row_per_port_in_order",
        ),
        red=(
            'TWO mutations, one per half. (a) Deleted the `"OcrEngine"` entry from `PORTS` '
            "(ports/__init__.py:96-103): `test_doctor_reports_exactly_six_ports` failed with "
            '`AssertionError: assert 5 == 6`. (b) Deleted `"version": self.version` from '
            "`EngineReport.to_dict()` (models.py:348): "
            "`test_every_row_carries_the_keys_a_consumer_reads` failed with `AssertionError: the "
            "key must exist even when the value is null / assert 'version' in {...}` "
            "(test_doctor.py:108). Each reverted from the real tree; sha256 match.\\n"
            "MEASURED, not transcribed: `uv run pdftoolkit doctor -o json | jq '.ports | length'` "
            "returns 6 at implementation HEAD on an engines-present host."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC2",
        claim=(
            "`.ports[].port` equals exactly [StructureEngine, RasterEngine, ComposeEngine, "
            "TextEngine, OcrEngine, OfficeConverter] in that order, and `jq -r '.ports[].kind' | "
            "sort -u` yields only python-package and system-binary. No seventh row for WeasyPrint."
        ),
        covering=(
            "tests/test_doctor.py::test_the_six_are_the_right_six_in_the_right_order",
            "tests/test_doctor.py::test_no_seventh_row_exists_for_the_phase_two_html_engine",
            "tests/unit/test_ports_registry.py::test_the_office_port_is_not_called_office_engine",
        ),
        red=(
            'TWO mutations. (a) Swapped `"RasterEngine"` and `"ComposeEngine"` in `PORTS`: '
            "`test_the_six_are_the_right_six_in_the_right_order` failed with `At index 1 diff: "
            "'ComposeEngine' != 'RasterEngine'` (test_doctor.py:91). (b) Renamed the sixth entry "
            'to `"OfficeEngine"` -- the name ports/__init__.py:95 warns about in a comment: '
            "`test_the_office_port_is_not_called_office_engine` failed with `assert "
            "'OfficeConverter' in ('StructureEngine', ..., 'OfficeEngine')` "
            "(test_ports_registry.py:58). Both reverted; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC3",
        claim=("With all engines present, `doctor` exits 0 and `doctor --strict` exits 0."),
        covering=(
            "tests/test_doctor.py::test_plain_doctor_exits_zero_whatever_is_installed",
            "tests/test_doctor.py::test_strict_exits_zero_when_every_engine_is_present",
            "tests/test_doctor.py::"
            "test_strict_exits_three_when_an_engine_is_hidden_and_plain_still_exits_zero",
        ),
        red=(
            "THE PRESCRIBED MUTATION DOES NOT REDDEN, AND THAT IS RECORDED RATHER THAN WORKED "
            "AROUND. `PDF-20` AC3 names 'force `build_report` to return available=False for one "
            'port\'. Applied as `available=probe.available and port != "OcrEngine"`: '
            "`test_strict_exits_zero_when_every_engine_is_present` SKIPPED "
            "(`engine-gated: this host is missing OcrEngine`) because the row self-gates on "
            "`all_engines_present(report)`. A skip is correct behaviour there -- the mutation "
            "removes the criterion's own precondition -- but it means the prescribed red produces "
            "a green suite, which is the failure shape this cycle exists to catch.\\n"
            "TWO CORRECTED MUTATIONS, both at the logic the criterion is actually about, both "
            "observed red. (a) `cmd_doctor.py:112` `if strict and unavailable:` -> `if strict:`: "
            "`test_strict_exits_zero_when_every_engine_is_present` failed with `assert 3 == 0` "
            "(test_doctor.py:157). (b) The same line -> `if unavailable:`: "
            "`test_strict_exits_three_when_an_engine_is_hidden_and_plain_still_exits_zero` failed "
            "with `assert 3 == 0` on the PLAIN arm (test_doctor.py:237), which is what proves the "
            "two arms are independently asserted rather than sharing one oracle. Both reverted; "
            "sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=(
            "PENDING-LEDGER: pdf-05-ac3-strict-row-skips-rather-than-fails-"
            "when-a-port-is-forced-unavailable"
        ),
    ),
    ACAudit(
        ac="AC4",
        claim=(
            "The StructureEngine row's `detail` names the secondary adapter and its version "
            "(pikepdf); the TextEngine row's `detail` names the pypdfium2 fast path; the row "
            "count stays 6."
        ),
        covering=(
            "tests/test_doctor.py::test_the_structure_row_names_its_secondary",
            "tests/test_doctor.py::test_the_text_row_names_its_fast_path",
        ),
        red=(
            "Deleted `extra_detail=detail,` from the structure port's `build_report` call "
            "(ports/structure.py:730-735). `test_the_structure_row_names_its_secondary` failed "
            "with `assert None is not None` (test_doctor.py:124) -- and "
            "`test_doctor_reports_exactly_six_ports`, run in the same invocation, stayed GREEN, "
            "which is what proves AC4 is not AC1 restated. Reverted; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC5",
        claim=(
            "Every available:true row has hint == null; every available:false row has a non-null, "
            "non-empty hint. Asserted over all six rows in both the all-present and the "
            "tesseract-hidden configurations."
        ),
        covering=(
            "tests/test_doctor.py::test_hints_appear_exactly_when_a_row_is_unavailable",
            "tests/test_doctor.py::test_hints_are_still_exactly_right_with_an_engine_hidden",
            "tests/unit/test_ports_registry.py::"
            "test_a_hint_on_an_available_engine_is_impossible_by_construction",
        ),
        red=(
            "The mutation is AT THE CONSTRUCTION SITE the docstring's 'true by construction' "
            "claim rests on, not at the values: `ports/__init__.py:192` `hint: str | None = None` "
            "-> `hint: str | None = install_hint(port, kind)`. "
            "`test_hints_appear_exactly_when_a_row_is_unavailable` failed with `AssertionError: "
            "StructureEngine is available but carries a hint / assert 'uv tool install --force "
            "pdf-toolkit' is None` (test_doctor.py:139). Reverted; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC6",
        claim=(
            "The acceptance signal, as a count. With PATH set to a temp dir containing only a "
            "soffice symlink, `doctor -o json` shows exactly one available:false row, its port is "
            "OcrEngine, its hint is non-empty; `doctor --strict` exits 3 in that environment while "
            "plain `doctor` still exits 0. Skips with a reason if soffice is absent."
        ),
        covering=(
            "tests/test_doctor.py::test_hiding_tesseract_flips_exactly_one_row",
            "tests/test_doctor.py::test_hiding_both_binaries_flips_exactly_two_rows",
            "tests/test_doctor.py::"
            "test_strict_exits_three_when_an_engine_is_hidden_and_plain_still_exits_zero",
        ),
        red=(
            "THE DISCRIMINATING ARM DID NOT EXIST AT HEAD AND WAS ADDED. Only "
            "`test_hiding_tesseract_flips_exactly_one_row` shipped, and a row that only ever "
            "observes the value 1 cannot tell 'exactly one' from 'at least one' -- the "
            "silent-wrong-answer reading of the product's own countable signal. "
            "`test_hiding_both_binaries_flips_exactly_two_rows` drives the same instrument to a "
            "DIFFERENT number (empty PATH -> exactly [OcrEngine, OfficeConverter], strict 3, "
            "plain 0).\\n"
            "RED, with both arms live: `cmd_doctor.py:68` `[report.to_dict() for report in "
            "reports]` -> `[... if report.available]`, i.e. an absent engine becomes an absent "
            "row rather than an available:false one. `test_hiding_both_binaries_flips_exactly_"
            "two_rows` failed with `AssertionError: the row count must not depend on what is "
            "installed / assert 4 == 6` (test_doctor.py:219). Reverted; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC7",
        claim=(
            "The OcrEngine hint is literally `apt install tesseract-ocr` when sys.platform == "
            "'linux' and literally `brew install tesseract` when sys.platform == 'darwin' "
            "(monkeypatched), both asserted as exact substrings."
        ),
        covering=(
            "tests/unit/test_ports_registry.py::test_ocr_hint_is_platform_aware",
            "tests/unit/test_ports_registry.py::test_office_hint_is_platform_aware",
            "tests/unit/test_ports_registry.py::test_an_unmapped_platform_falls_back_and_says_so",
        ),
        red=(
            "Set `_BINARY_HINTS['OcrEngine']['darwin']` to the linux string "
            "(ports/__init__.py:122-131). `test_ocr_hint_is_platform_aware` failed with "
            "`AssertionError: assert 'apt install tesseract-ocr' == 'brew install tesseract'` "
            "(test_ports_registry.py:91) -- and it failed on the DARWIN line while the LINUX "
            "assertion two lines above still passed, which is what proves both arms are live on "
            "this one host. Reverted; sha256 match.\\n"
            "PLATFORM, stated per-platform (X-153): no macOS host is available to this cycle, so "
            "the darwin arm is verified by monkeypatching `sys.platform`, never by observation on "
            "a Mac. The criterion is about the TABLE, and the table is what is asserted."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC8",
        claim=(
            "`doctor` never reports a version it did not parse: forcing an unparseable --version "
            "output yields available:true, version:null with the raw line in detail, and raises "
            "no exception."
        ),
        covering=(
            "tests/unit/test_ports_registry.py::"
            "test_an_unparseable_version_yields_null_and_the_raw_line",
            "tests/unit/test_ports_registry.py::test_a_parseable_version_is_reported_exactly",
            "tests/unit/test_ports_registry.py::test_an_absent_binary_is_a_row_not_an_exception",
        ),
        red=(
            "THE MUTATION `PDF-20` NAMES PRODUCES NO RED, MEASURED. `PDF-20` AC8 names "
            "`soffice_office.py:55-57` (`_parse_version`). Applied there -- `return match.group(1) "
            "if match else None` -> `raise ValueError(line)` on no match -- the covering test "
            "PASSED in 0.24 s, because it drives the TESSERACT adapter "
            "(`tesseract_ocr.ADAPTER.probe()` with `subprocess_util.run` monkeypatched, "
            "test_ports_registry.py:172-182). The soffice half of AC8 has no covering test.\\n"
            "RED at the site the covering test actually exercises: the identical mutation in "
            "`tesseract_ocr.py:79-81` failed with `ValueError: Tesseract Open Source OCR` raised "
            "through `probe()` (tesseract_ocr.py:82), i.e. the no-exception assertion. Reverted; "
            "sha256 match. The criterion HOLDS for the adapter it is measured on; the second "
            "system-binary adapter is filed."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=(
            "PENDING-LEDGER: pdf-05-ac8-version-parse-honesty-covers-tesseract-and-not-soffice"
        ),
    ),
    ACAudit(
        ac="AC9",
        claim=(
            "On this host the OcrEngine row's detail enumerates the installed tessdata languages "
            "and contains both eng and osd and does not contain spa. Honest degradation, asserted "
            "negatively as well as positively."
        ),
        covering=(
            "tests/test_doctor.py::"
            "test_the_ocr_row_enumerates_the_languages_that_are_actually_installed",
            "tests/test_doctor.py::test_the_ocr_row_claims_no_language_that_is_not_installed",
            "tests/unit/test_ports_registry.py::test_language_enumeration_drops_the_header_and_sorts",
        ),
        red=(
            "Made `_parse_languages` fabricate codes (tesseract_ocr.py:91-92, "
            "`tuple(sorted(set(body)))` -> `tuple(sorted({*body, 'spa', 'deu'}))`). "
            "`test_the_ocr_row_claims_no_language_that_is_not_installed` failed with "
            "`AssertionError: detail advertises spa, which is not installed / assert 'spa' not in "
            "' deu, eng, osd, spa'` (test_doctor.py:288). Reverted; sha256 match.\\n"
            "RE-DERIVED AS CORRECTED (`PDF-20` E7), and the correction was already SHIPPED: the "
            "criterion's literal `spa` is a fact about this laptop and fails a CORRECT "
            "implementation on a host with the Spanish pack installed. The covering tests do NOT "
            "hard-code it -- `_installed_languages()` (test_doctor.py:219) asks the binary, and "
            "the negative arm derives `absent` from the difference, with "
            "`assert absent, 'every probe language happens to be installed; nothing to assert "
            "negatively'` guarding the vacuous case. The defect is in `PDF-05` AC9's PROSE, not "
            "in its mechanization, and is recorded rather than silently replaced."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC10",
        claim=(
            "Process-group kill, asserted mechanically, not by inspection. "
            "`subprocess_util.run(['sh','-c','sleep 300 & sleep 300'], timeout=1)` reports "
            "timed_out=True and no descendant survives: `pgrep -g <pgid>` exits non-zero AND "
            "`os.killpg(pgid, 0)` raises ProcessLookupError, both in the same test."
        ),
        covering=(
            "tests/unit/test_subprocess_util.py::"
            "test_timeout_kills_the_whole_group_including_a_forked_grandchild",
            "tests/unit/test_subprocess_util.py::test_pgrep_corroborates_that_the_group_is_empty",
            "tests/unit/test_subprocess_util.py::test_a_normal_run_leaves_no_group_behind_either",
            "tests/unit/test_subprocess_util.py::"
            "test_a_grandchild_holding_the_pipes_is_a_timeout_and_still_reaped",
        ),
        red=(
            "INVERTED for one of its two halves, DEMONSTRATED TWICE, and the second demonstration "
            "leaked a live process.\\n"
            "(a) `start_new_session=True` -> `False` (subprocess_util.py:236) -- the exact "
            "mutation `PDF-05`/`PDF-20` AC10 names. "
            "`test_timeout_kills_the_whole_group_including_a_forked_grandchild` PASSED, in "
            "**300.25 s**. Mechanism: the grandchild inherits the capture pipes, so the "
            "post-timeout `communicate()` blocks until it exits of natural causes; by the time the "
            "'no descendant survives' assertion runs, the `sleep 300` has finished. The assertion "
            "is true on ANY implementation that captures streams, group kill or not.\\n"
            "(b) The same mutation against `test_a_normal_run_leaves_no_group_behind_either`, "
            "where the grandchild redirects its streams away and so cannot hold the pipes: PASSED "
            "in **0.25 s**, and `pgrep -x sleep` immediately afterwards listed a surviving "
            "`sleep 30` (pid 3897873). Mechanism: `ProcRun.pgid` is set to `proc.pid` "
            "UNCONDITIONALLY (subprocess_util.py:244), so without a new session it names a "
            "process group that does not exist; `killpg(pgid, 0)` raises ProcessLookupError at "
            "once and `_wait_group_gone` reports the group 'already gone'. The instrument cannot "
            "distinguish a group that was killed from a group that never existed -- and that is "
            "the mediakit failure mode (163 orphaned daemons) reproduced with the guard green.\\n"
            "(c) THE OTHER HALF IS LIVE. Replaced both group signals with PID-scoped ones "
            "(`_signal_group(pgid, SIGTERM)` -> `proc.terminate()`, `_signal_group(pgid, SIGKILL)` "
            "-> `proc.kill()`, subprocess_util.py:150/164). "
            "`test_a_normal_run_leaves_no_group_behind_either` failed with `AssertionError: a "
            "backgrounded grandchild survived a SUCCESSFUL run -- the group, not the pid, is the "
            "unit of cleanup / assert None is not None ... _wait_group_gone(3898440)` "
            "(test_subprocess_util.py:128). All three reverted; sha256 match. No orphan survived "
            "this audit (`pgrep -x sleep` empty at close).\\n"
            "FILED, NOT REPAIRED: `audit_pdf_04.py` AC11 is the precedent -- an audit makes no "
            "repair to the mechanism it audits, and repairing a `PDF-05` control mid-re-derivation "
            "is what turns a measurement into a claim about the measurer."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=(
            "PENDING-LEDGER: pdf-05-ac10-process-group-control-cannot-fail-for-start-new-session"
        ),
    ),
    ACAudit(
        ac="AC11",
        claim=(
            "`subprocess_util.run` has no default timeout: calling it without the keyword raises "
            "TypeError, asserted. `grep -rn 'shell=True' src/` returns nothing."
        ),
        covering=(
            "tests/unit/test_subprocess_util.py::test_timeout_is_required_and_has_no_default",
            "tests/unit/test_subprocess_util.py::test_no_module_under_src_enables_a_shell",
            "tests/unit/test_subprocess_util.py::test_arguments_are_never_reparsed_by_a_shell",
            "tests/unit/test_subprocess_util.py::test_argv_is_a_list_and_an_empty_one_is_refused",
        ),
        red=(
            "TWO mutations, one per half. (a) `timeout: float,` -> `timeout: float = 30.0,` "
            "(subprocess_util.py:170): `test_timeout_is_required_and_has_no_default` failed with "
            "`Failed: DID NOT RAISE TypeError` (test_subprocess_util.py:162). (b) Flipped the "
            "pinned `shell` keyword to its enabled spelling (subprocess_util.py:237): "
            "`test_no_module_under_src_enables_a_shell` failed with `AssertionError: a shell was "
            "enabled somewhere: ['src/pdf_toolkit/adapters/subprocess_util.py']` "
            "(test_subprocess_util.py:180). Both reverted; sha256 match.\\n"
            "DEVIATION FROM `PDF-20` AC11, ARGUED IN SHIPPED SOURCE. `PDF-20` requires the shell "
            "half to be 'an AST assertion, not a grep (X-113)'. It is a grep, deliberately, and "
            "the reason is written at test_subprocess_util.py:169-172: the assertion is about the "
            "ABSENCE OF A STRING, so the module docstring refuses to quote the spelling and an "
            "AST walk is the wrong tool for it. X-113's hazard -- a grep for an absence failing a "
            "correct implementation, e.g. on a docstring -- is real and is defused at the source "
            "rather than by changing the instrument. The control is live, which is the property "
            "that matters here."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC12",
        claim=(
            "`info` writes nothing. A recursive snapshot (path + size + mtime + sha256) of a "
            "scratch tree taken before and after `info x.pdf`, and again around `info x.pdf "
            "--dry-run`, is byte-identical in both cases, and no .pdftoolkit-* file appears in the "
            "tree or in $TMPDIR. Both invocations exit 0."
        ),
        covering=(
            "tests/test_info.py::test_info_changes_nothing_on_the_filesystem[plain]",
            "tests/test_info.py::test_info_changes_nothing_on_the_filesystem[dry-run]",
            "tests/test_info.py::test_info_leaves_no_toolkit_temp_file_anywhere",
            "tests/test_info.py::test_neither_info_module_constructs_a_writer",
        ),
        red=(
            "THE OPEN QUESTION `PDF-20` AC12 RAISES IS ANSWERED: the shipped roots DO cover a "
            "redirected `$HOME`. `test_info_changes_nothing_on_the_filesystem` builds its roots "
            "from `redirected_environment(tmp_path / 'env')` (test_info.py:371-372), which "
            "redirects both `$HOME` and `$TMPDIR` under the scratch and returns both as roots. "
            "No finding about AC12's roots is owed.\\n"
            "RED: added a write under the redirected home to `ops/inspect.py`'s validation path, "
            "guarded to fire only when `$HOME` is under `/tmp/` so the operator's real home could "
            "not be touched by the probe for a $HOME write. "
            "`test_info_changes_nothing_on_the_filesystem[plain]` failed with `AssertionError: 2 "
            "filesystem difference(s) across 3 root(s); a pure run makes none: "
            "<env>/home/.pdf20-probe: added; <env>/home: mtime ... -> ...` (fs_snapshot.py:228). "
            "Reverted; sha256 match; no file was created under the real `$HOME` (checked)."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC13",
        claim=(
            "`info -o json` reports the true page_count, encrypted, encryption_algorithm and "
            "pdf_version, asserted against the values the fixture generator wrote: a 3-page "
            "document reports 3; an AES-256-encrypted copy reports encrypted:true and 'AES-256'; "
            "pdf_version matches the header the generator produced."
        ),
        covering=(
            "tests/test_info.py::test_info_reports_the_true_page_count_and_version",
            "tests/test_info.py::test_info_reports_the_true_encryption_algorithm",
            "tests/test_info.py::test_pages_detail_reports_one_entry_per_page",
        ),
        red=(
            "`page_count = len(reader.pages)` -> `len(reader.pages) + 1` "
            "(pypdf_structure.py:415). `test_info_reports_the_true_page_count_and_version` failed "
            "with `assert 4 == 3` (test_info.py:134). Reverted; sha256 match.\\n"
            "CORROBORATED BY A DIFFERENT CONSUMER THAN THE ONE THAT COMPUTES IT (D7.2), using the "
            "HC-1 cycle-2 carve-out: an OUT-OF-TREE poppler `pdfinfo` oracle, run outside the "
            "product, nothing imported, nothing shipped, no dependency added. On the generated "
            "3-page fixture and on its owner-password-only AES-256 copy, THREE independent "
            "consumers agree: pdftoolkit `pages=3 version=1.3`, poppler `Pages: 3 / PDF version: "
            "1.3`, and the generator's own recorded `FIXTURE_PAGES = 3`. Under the mutation the "
            "product says 4 and the oracle still says 3 -- the disagreement a single-consumer "
            "assertion cannot produce."
        ),
        red_kind=RedKind.EXTERNAL_ORACLE,
    ),
    ACAudit(
        ac="AC14",
        claim=(
            "`info`'s exit codes match D6.4 exactly, one test per row: malformed PDF -> 1; "
            "nonexistent path -> 4; unknown flag -> 2; directory operand -> 2; "
            "owner-password-only encrypted document -> 0 with encrypted:true; "
            "user-password-required document with no password -> 6."
        ),
        covering=(
            "tests/test_info.py::test_a_malformed_pdf_is_exit_one",
            "tests/test_info.py::test_a_nonexistent_path_is_exit_four",
            "tests/test_info.py::test_an_unknown_flag_is_exit_two",
            "tests/test_info.py::test_a_directory_operand_is_exit_two",
            "tests/test_info.py::test_an_owner_password_only_document_is_exit_zero",
            "tests/test_info.py::test_a_user_password_document_is_exit_six",
            "tests/test_info.py::test_a_malformed_pdf_reports_a_structured_error",
        ),
        red=(
            "SIX mutations, one per row, all six reds observed, all six reverted; sha256 match "
            "after each.\\n"
            "(1) nonexistent -> 4: `NoInputError` -> `UsageError` (ops/inspect.py:122): "
            "`assert 2 == 4` (test_info.py:252). "
            "(2) directory -> 2: the PRE-FLIGHT `UsageError` -> `NoInputError` "
            "(ops/inspect.py:98): "
            "`assert 4 == 2` (test_info.py:262). "
            "(3) malformed -> 1: all eight `FailureError(f'could not read PDF: ...')` raises -> "
            "`UsageError` (pypdf_structure.py): `assert 2 == 1` (test_info.py:239). "
            "(4) unknown flag -> 2: DECLARED `--not-a-flag` as a real option on `info_command` "
            "(cmd_info.py) -- the framework, not a raise, is what enforces this row: "
            "`assert 0 == 2` (test_info.py:256). "
            "(5) owner-only -> 0: `unlocked = bool(reader.decrypt(''))` -> `unlocked = False` "
            "(pypdf_structure.py:403): `assert 6 == 0` (test_info.py:278). "
            "(6) user-password -> 6: `AuthError` -> `FailureError` (pypdf_structure.py:409): "
            "`assert 1 == 6` (test_info.py:285).\\n"
            "A CORRECTION TO `PDF-20`'s POINTER, MEASURED. The per-item directory refusal at "
            "`ops/inspect.py:123-124` is UNREACHABLE from the CLI -- mutating it produces no red, "
            "because `validate_inputs`' pre-flight refusal at `:97-102` answers first. The same "
            "holds for `:95`'s no-operand `UsageError`, which Typer's required argument answers "
            "before it. Both are live only for a direct `inspect_document` caller.\\n"
            "The malformed -> 1 row is the one `PDF-12`'s `repair` consumes and is called out so "
            "a later engineer sees the coupling."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=(
            "PENDING-LEDGER: pdf-05-ac14-per-item-directory-and-no-operand-"
            "refusals-are-unreachable-from-the-cli"
        ),
    ),
    ACAudit(
        ac="AC15",
        claim=(
            "License and startup boundaries. tests/test_import_boundaries.py fails when (a) an "
            "import of pypdf/pypdfium2/pikepdf/reportlab/pdfplumber is added to any module under "
            "src/pdf_toolkit/ outside adapters/, and (b) a subprocess reference is added outside "
            "adapters/subprocess_util.py. Additionally, after importing cli.main, sys.modules "
            "contains none of the engines, and `--help` completes within the 250 ms budget "
            "expressed as a single named constant."
        ),
        covering=(
            "tests/test_import_boundaries.py::test_no_engine_library_is_imported_outside_adapters",
            "tests/test_import_boundaries.py::test_nothing_outside_the_chokepoint_can_spawn",
            "tests/test_license_policy.py::test_subprocess_chokepoint",
            "tests/test_cli_spine.py::test_no_engine_library_is_imported_at_module_scope",
            "tests/test_cli_spine.py::test_help_stays_within_the_startup_budget",
        ),
        red=(
            "TWO mutations, on the REAL tree copy, one per clause. (a) `import pikepdf` added to "
            "`ops/inspect.py`: `test_no_engine_library_is_imported_outside_adapters` failed with "
            "`engine libraries are importable only beneath adapters/ ... - "
            "pdf_toolkit.ops.inspect:42: engine import outside adapters/ 'pikepdf'` "
            "(test_import_boundaries.py:1064). (b) `import subprocess` added to "
            "`cli/cmd_doctor.py`: `test_nothing_outside_the_chokepoint_can_spawn` failed with "
            "`pdf_toolkit.adapters.subprocess_util is the only spawn point: - "
            "pdf_toolkit.cli.cmd_doctor:38: spawn module outside the chokepoint 'subprocess'` "
            "(test_import_boundaries.py:1073). Both reverted; sha256 match.\\n"
            "`PDF-20` calls a failure here a license-policy finding that outranks everything else "
            "in the sweep. There is none: the boundary suite is green at implementation HEAD, "
            "including over `PDF-20`'s own new `probe_env()` call sites, and `make licenses` "
            "produces no diff -- Q5 held, no runtime dependency was added."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC16",
        claim=(
            "`grep -rn 'PROVISIONAL — superseded by PDF-06' tests/` returns the fixture helper. "
            "Mechanized handoff, so PDF-06 migrates rather than duplicates."
        ),
        covering=(),
        red=(
            "NOT MET, and its greenness now means the opposite of what it was written to mean "
            "(`PDF-20` E8, confirmed by measurement at implementation HEAD).\\n"
            "MEASURED: `tests/corpus.py` EXISTS (25,609 bytes, 16 fixtures in `_BUILDERS` and "
            "`FIXTURE_NAMES`). The marker still sits at `tests/test_info.py:38`. "
            "`tests/test_info.py` does NOT import `tests/corpus.py`; it still calls its three "
            "inline builders (`build_plain_pdf`, `build_encrypted_pdf`, `build_malformed_pdf`, "
            "test_info.py:55-86) from 34 tests, e.g. at `:118`. The marker's own instruction -- "
            "'When the corpus lands, MIGRATE these three builders into it rather than duplicating "
            "them' -- was not carried out, so the marker is no longer a pending handoff signal but "
            "evidence of the duplication AC16 existed to prevent.\\n"
            "NO COVERING TEST EXISTS AT ALL: `grep -rn PROVISIONAL tests/` returns exactly one "
            "line, the marker itself. AC16's mechanization is a grep written into a spec document "
            "that nothing in the suite executes -- `PDF-17` E8's family, second instance.\\n"
            "FILED RATHER THAN MIGRATED, and `PDF-20` AC16 authorizes exactly this choice. The "
            "migration needs at least TWO fixtures `tests/corpus.py` does not have -- an "
            "owner-password-only document (empty user password; `encrypted_aes256` uses a "
            "non-empty one, corpus.py:295) and a malformed-bytes document -- on a roster whose "
            "`_BUILDERS`/`FIXTURE_NAMES` counts are pinned and owned by `PDF-06`/`PDF-17`, plus "
            "re-pointing 34 tests. That is a scope widening discovered at implementation time, "
            "which goes back to the PM rather than being absorbed."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding=(
            "PENDING-LEDGER: pdf-05-ac16-pdf-06-corpus-handoff-was-never-"
            "executed-and-is-unmechanised"
        ),
    ),
    ACAudit(
        ac="AC17",
        claim=(
            "`git show <sha> --stat` for this spec's single commit lists no README.md, no "
            "CLAUDE.md, no pyproject.toml, no uv.lock, and no file under .github/ or website/; it "
            "does list changelog.md with exactly one new [PDF-05 ...] entry. Exactly one commit, "
            "DCO-signed."
        ),
        covering=(),
        red=(
            "RE-CHECKED AND TRUE, AND IT CARRIES NO RED CONTROL BY CONSTRUCTION. This criterion "
            "asserts a property of a commit that has already happened; it can be re-checked "
            "forever and can never go red for future work, so it is recorded here as NOT a live "
            "control and is not counted as one (`PDF-20` AC17 requires exactly this statement).\\n"
            "MEASURED at `38ca2ab117f7eedccb9df05393ef2a9145ff6d64` ('[PDF-05] feat: engine "
            "ports, adapters, the only spawn point, doctor & info'): `git show --stat` lists NONE "
            "of README.md, CLAUDE.md, pyproject.toml, uv.lock, .github/ or website/; "
            "`git show <sha> -- changelog.md | grep -c '^+## \\\\[PDF-05'` returns 1; "
            "`git log -1 --format=%B <sha> | grep -c 'Signed-off-by:'` returns 1.\\n"
            "ONE CORRECTION TO `PDF-05`'s OWN LOG, recorded because a count nobody re-ran is this "
            "loop's most-repeated anti-pattern: the stat reads `30 files changed, 4557 "
            "insertions(+), 25 deletions(-)`. `PDF-05`'s Implementation Log says '30 files' in its "
            "header and '31 files:' four lines later. Thirty is the measured number.\\n"
            "`PDF-20`'s own commit meets the same standard and THAT half is checkable going "
            "forward; it is asserted in `PDF-20`'s AC27 and in this engineer's report."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding=("PENDING-LEDGER: pdf-05-ac17-one-shot-historical-assertion-with-no-live-control"),
    ),
    ACAudit(
        ac="AC18",
        claim=(
            "`make ci` passes locally (fmt-check lint typecheck test licenses sast vulncheck), "
            "mypy --strict is clean over the new modules, and the wave gate is a pushed green CI "
            "run, not a local `make ci`."
        ),
        covering=(
            "tests/test_gate_parity.py::"
            "test_makefiles_ci_prerequisites_are_exactly_the_in_make_ci_true_locals",
            "tests/test_gate_parity.py::test_every_local_target_is_a_real_makefile_target",
            "tests/test_gate_parity.py::test_ac8_proof_a_narrowed_makefile_ci_line_reddens",
            "tests/test_gate_parity.py::test_the_coverage_floor_is_defined_only_in_the_makefile",
        ),
        red=(
            "RE-DERIVED AS CORRECTED (`PDF-20` E6), and the prerequisite list is read FROM the "
            "Makefile rather than from any literal -- `test_makefiles_ci_prerequisites_are_"
            "exactly_the_in_make_ci_true_locals` parses `^ci: ([^\\n#]+)` at "
            "test_gate_parity.py:274 and compares it against the gate-parity manifest.\\n"
            "MEASURED: `grep -n '^ci:' Makefile` returns line **274** (not `:221`, which is what "
            "both `PDF-20` E6 and its Validation step 10 say -- the pointer moved and is corrected "
            "here). The list is `fmt-check lint typecheck cover licenses sast vulncheck`: "
            "**cover, not test**, which is what `PDF-05` AC18 says. Re-deriving AC18 verbatim "
            "would have asserted a target list the Makefile does not have.\\n"
            "RED: narrowed the Makefile's `ci:` line by removing `cover` in the scratch worktree. "
            "`test_makefiles_ci_prerequisites_are_exactly_the_in_make_ci_true_locals` failed with "
            "`AssertionError: (frozenset({'fmt-check','licenses','lint','sast','typecheck',"
            "'vulncheck'}), frozenset({'cover','fmt-check',...}))  Extra items in the right set: "
            "'cover'` (test_gate_parity.py:281). Reverted; sha256 match.\\n"
            "WORTH RECORDING ON ITS OWN: the spec whose whole lesson is 'never transcribe a "
            "literal' itself hard-coded a Makefile line number, and that number moved within two "
            "commits. `mypy --strict` clean over all seven touched source modules; the pushed CI "
            "run is tallied by hand in `PDF-20`'s report."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
    ),
)
