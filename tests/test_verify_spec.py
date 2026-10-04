"""The arms for `scripts/verify_spec.py` and its outcome plugin -- PDF-106 D6.

`make verify SPEC=PDF-NN` runs one spec's `AUDIT-CONVENTION(PDF-17)` evidence and
prints a per-AC table. Every arm here is IN-PROCESS over SYNTHETIC `ACAudit` rows
and injected outcome maps; no arm mutates a real audit module (the house idiom,
`tests/test_acceptance_audit.py`'s "Proof that the gate fires"). The one
subprocess arm drives the usage and unaudited exits of the real script.

The cohort arm at the bottom is the one that touches real modules: it applies the
D4 token rule to `audit_pdf_{82,85,86,88}`, one node id per module, and a
module that does not exist FAILS (import error) rather than skipping.
"""

from __future__ import annotations

import re
import subprocess
import sys
import types
import typing
from pathlib import Path
from typing import Final

import pytest
from _pytest.reports import TestReport

from acceptance._model import ACAudit, RedKind

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SCRIPT: Final[Path] = REPO_ROOT / "scripts" / "verify_spec.py"
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import _verify_outcomes as outcomes_plugin  # noqa: E402
import verify_spec as vs  # noqa: E402

FOOTER_LITERAL: Final[str] = (
    "This runner grants nothing: qa-sentinel signs the evidence; "
    "project-manager transitions the status."
)
STATUS_WORD: Final[re.Pattern[str]] = re.compile("verified", re.IGNORECASE)

_RED: Final[str] = (
    "mutated src/x.py:10 in a scratch worktree; saw `AssertionError: boom`; "
    "reverted by git show HEAD:src/x.py and git diff --exit-code; base 119f47e"
)
_ID_A: Final[str] = "tests/test_a.py::test_a"
_ID_B: Final[str] = "tests/unit/test_b.py::test_b[x-1]"


def _row(
    ac: str = "AC1",
    *,
    claim: str = "a synthetic claim",
    covering: tuple[str, ...] = (_ID_A,),
    red: str = _RED,
    red_kind: RedKind = RedKind.PLANTED_DEFECT,
    finding: str | None = None,
) -> ACAudit:
    return ACAudit(
        ac=ac, claim=claim, covering=covering, red=red, red_kind=red_kind, finding=finding
    )


def _module(name: str, rows: tuple[ACAudit, ...]) -> types.ModuleType:
    module = types.ModuleType(f"acceptance.{name}")
    module.AUDIT = rows  # type: ignore[attr-defined]
    return module


def _header() -> vs.Header:
    return vs.Header(
        spec_id="PDF-99",
        module_path="tests/acceptance/audit_pdf_99.py",
        head="0" * 40,
        python="3.13.0",
        utc="2026-10-04T00:00:00Z",
    )


def _all_pass(ids: tuple[str, ...]) -> dict[str, str]:
    return dict.fromkeys(ids, "passed")


# --------------------------------------------------------------------------- #
# AC3 -- usage and unaudited specs exit 2 (the one subprocess arm)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("args", "needles"),
    [
        ([], ["make verify SPEC=PDF-NN"]),
        (["PDF-NOPE"], ["make verify SPEC=PDF-NN"]),
        (["PDF-5"], ["make verify SPEC=PDF-NN"]),
        (["85"], ["make verify SPEC=PDF-NN"]),
        (["PDF-55"], ["tests/acceptance/audit_pdf_55.py", "unaudited"]),
    ],
    ids=["no-arg", "nope", "one-digit", "bare-digits", "no-module"],
)
def test_ac3_usage_and_unaudited_specs_exit_2(args: list[str], needles: list[str]) -> None:
    done = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2, (done.returncode, done.stderr)
    for needle in needles:
        assert needle in done.stderr, (needle, done.stderr)
    assert done.stdout == "", "a usage error must not print a table"


# --------------------------------------------------------------------------- #
# AC4 -- node-id selection is exact
# --------------------------------------------------------------------------- #


def test_ac4_node_ids_are_deduplicated_ordered_then_aggregator_then_roster() -> None:
    module = _module(
        "audit_pdf_99",
        (
            _row("AC1", covering=(_ID_A, _ID_B)),
            _row("AC2", covering=(_ID_A,)),  # shares one covering id with AC1
            _row("AC3", covering=("tests/test_c.py::TestC::test_m",)),
        ),
    )
    agg = "tests/test_acceptance_audit.py"
    assert vs.node_ids_for(module) == (
        _ID_A,
        _ID_B,
        "tests/test_c.py::TestC::test_m",
        f"{agg}::test_module_name_matches_declared_spec_id[audit_pdf_99]",
        f"{agg}::test_every_covering_node_id_resolves[audit_pdf_99]",
        f"{agg}::test_an_unmeasured_ac_names_a_finding[audit_pdf_99]",
        f"{agg}::test_the_ac_roster_is_contiguous[audit_pdf_99]",
        f"{agg}::test_red_is_substantive[audit_pdf_99]",
        f"{agg}::test_every_module_exposes_the_three_declared_names[audit_pdf_99]",
        f"{agg}::test_the_audit_roster_is_non_empty",
    )


def test_ac4_every_aggregator_arm_is_requested_by_name() -> None:
    module = _module("audit_pdf_99", (_row(),))
    requested = set(vs.node_ids_for(module))
    wanted = {f"tests/test_acceptance_audit.py::{arm}[audit_pdf_99]" for arm in vs.AGGREGATOR_ARMS}
    missing = sorted(wanted - requested)
    assert missing == [], f"the run set omits aggregator controls: {missing}"


def test_ac4_the_six_arms_are_the_aggregators_real_parametrized_arms() -> None:
    """Pin the runner's arm list to the frozen aggregator's own source, so a
    renamed arm reds here rather than as `not-run` on a real verify pass."""
    source = (REPO_ROOT / "tests" / "test_acceptance_audit.py").read_text(encoding="utf-8")
    parametrized = re.findall(
        r"@pytest\.mark\.parametrize\(\"module\"[^\n]*\)\ndef (test_\w+)", source
    )
    assert tuple(parametrized) == tuple(sorted(parametrized, key=parametrized.index))
    assert set(parametrized) == set(vs.AGGREGATOR_ARMS)
    assert f"def {vs.ROSTER_ARM}(" in source


# --------------------------------------------------------------------------- #
# AC5 -- outcomes are keyed by exact node id
# --------------------------------------------------------------------------- #


def _report(nodeid: str, when: str, outcome: str) -> TestReport:
    return TestReport(
        nodeid=nodeid,
        location=("f.py", 0, "t"),
        keywords={},
        outcome=outcome,  # type: ignore[arg-type]
        longrepr=None,
        when=when,  # type: ignore[arg-type]
    )


def test_ac5_the_plugin_records_every_id_shape_verbatim_and_reduces_phases() -> None:
    parametrized = "tests/test_p.py::test_p[a-1]"
    nested = "tests/x.py::TestC::test_m"
    unit = "tests/unit/test_u.py::test_u"
    skipped = "tests/test_s.py::test_s"
    errored = "tests/test_e.py::test_e"
    recorder = outcomes_plugin.OutcomeRecorder()
    for node_id in (parametrized, nested, unit):
        for when in ("setup", "call", "teardown"):
            recorder.pytest_runtest_logreport(_report(node_id, when, "passed"))
    recorder.pytest_runtest_logreport(_report(skipped, "setup", "passed"))
    recorder.pytest_runtest_logreport(_report(skipped, "call", "skipped"))
    recorder.pytest_runtest_logreport(_report(skipped, "teardown", "passed"))
    recorder.pytest_runtest_logreport(_report(errored, "setup", "failed"))
    recorder.pytest_runtest_logreport(_report(errored, "teardown", "passed"))

    assert recorder.outcomes == {
        parametrized: "passed",
        nested: "passed",
        unit: "passed",
        skipped: "skipped",
        errored: "error",
    }


@pytest.mark.parametrize(
    ("phases", "expected"),
    [
        ([("call", "failed")], "failed"),
        ([("setup", "failed")], "error"),
        ([("call", "passed"), ("teardown", "failed")], "error"),
        ([("setup", "skipped")], "skipped"),
        ([("call", "failed"), ("teardown", "failed")], "error"),
    ],
    ids=["call-fail", "setup-fail", "teardown-fail", "setup-skip", "fail-then-teardown-fail"],
)
def test_ac5_phase_reduction_worst_wins(phases: list[tuple[str, str]], expected: str) -> None:
    recorder = outcomes_plugin.OutcomeRecorder()
    for when, outcome in phases:
        recorder.pytest_runtest_logreport(_report("tests/x.py::t", when, outcome))
    assert recorder.outcomes == {"tests/x.py::t": expected}


def test_ac5_an_id_with_no_report_reads_as_not_run() -> None:
    module = _module("audit_pdf_99", (_row(covering=(_ID_A,)),))
    ids = vs.node_ids_for(module)
    seen = {_ID_A: "passed"}  # every aggregator id is absent
    text = vs.render(_header(), "audit_pdf_99", module.AUDIT, seen)  # type: ignore[attr-defined]
    assert text.count(": not-run") == 7
    assert vs.exit_code(seen, ids) == 1


def test_ac5_the_runner_never_goes_through_a_junit_report() -> None:
    assert "junit" + "xml" not in SCRIPT.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# AC6 -- classification follows D4's table, token first
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (_row(), "locally driven"),
        (
            _row(red_kind=RedKind.NOT_OBSERVED, finding="PENDING-LEDGER: s", red="no red"),
            "covered, red NOT observed",
        ),
        (
            _row(
                covering=(),
                red="CI-EVIDENCED: run 1",
                red_kind=RedKind.NOT_OBSERVED,
                finding="B-123",
            ),
            "CI-evidenced, not locally driven",
        ),
        (
            _row(
                covering=(),
                red="COMMAND: make x",
                red_kind=RedKind.NOT_OBSERVED,
                finding="B-123",
            ),
            "command-evidenced, not driven by this runner",
        ),
        (
            _row(
                covering=(),
                red="UNREDDENABLE: a person reads it",
                red_kind=RedKind.NOT_OBSERVED,
                finding="B-123",
            ),
            "UNREDDENABLE: no mutation can red this AC",
        ),
        (
            _row(covering=(), red="no red", red_kind=RedKind.NOT_OBSERVED, finding="B-123"),
            "unmeasured (unclassified)",
        ),
    ],
    ids=["local", "no-red", "ci", "command", "unreddenable", "unmeasured"],
)
def test_ac6_each_class_gets_its_exact_printed_text(row: ACAudit, expected: str) -> None:
    assert vs.classify(row) == expected


def test_ac6_a_token_beats_the_covering_and_red_kind_rules() -> None:
    covered_ci = _row(red="CI-EVIDENCED: run 1", red_kind=RedKind.PLANTED_DEFECT)
    assert vs.classify(covered_ci) == "CI-evidenced, not locally driven"


# --------------------------------------------------------------------------- #
# AC7 -- exit codes (0 / 1 x3 / 3), each over injected outcomes
# --------------------------------------------------------------------------- #

_IDS7: Final[tuple[str, ...]] = vs.node_ids_for(_module("audit_pdf_99", (_row(),)))


def test_ac7_exit_0_when_every_id_passes() -> None:
    assert vs.exit_code(_all_pass(_IDS7), _IDS7) == 0


def test_ac7_exit_1_when_a_covering_id_fails() -> None:
    assert vs.exit_code({**_all_pass(_IDS7), _ID_A: "failed"}, _IDS7) == 1


def test_ac7_exit_1_when_a_covering_id_did_not_run() -> None:
    absent = {k: v for k, v in _all_pass(_IDS7).items() if k != _ID_A}
    assert vs.exit_code(absent, _IDS7) == 1


def test_ac7_exit_1_when_only_an_aggregator_arm_fails() -> None:
    arm = next(i for i in _IDS7 if "test_red_is_substantive" in i)
    assert vs.exit_code({**_all_pass(_IDS7), arm: "failed"}, _IDS7) == 1


def test_ac7_exit_1_when_pytest_reports_a_collection_or_usage_problem() -> None:
    assert vs.exit_code(_all_pass(_IDS7), _IDS7, pytest_rc=4) == 1


def test_ac7_exit_3_when_the_only_blemish_is_a_skip() -> None:
    assert vs.exit_code({**_all_pass(_IDS7), _ID_A: "skipped"}, _IDS7) == 3


def test_ac7_a_failure_outranks_a_skip() -> None:
    mixed = {**_all_pass(_IDS7), _ID_A: "skipped", _IDS7[1]: "failed"}
    assert vs.exit_code(mixed, _IDS7) == 1


def test_ac7_token_classes_never_change_the_exit_code() -> None:
    rows = (
        _row("AC1"),
        _row(
            "AC2",
            covering=(),
            red="CI-EVIDENCED: run 1",
            red_kind=RedKind.NOT_OBSERVED,
            finding="B-123",
        ),
        _row(
            "AC3",
            covering=(),
            red="UNREDDENABLE: judgement",
            red_kind=RedKind.NOT_OBSERVED,
            finding="B-124",
        ),
    )
    ids = vs.node_ids_for(_module("audit_pdf_99", rows))
    text = vs.render(_header(), "audit_pdf_99", rows, _all_pass(ids))
    assert "runner exit: 0 (" in text


# --------------------------------------------------------------------------- #
# AC8 -- the runner grants nothing
# --------------------------------------------------------------------------- #


def _scenarios() -> list[tuple[str, tuple[ACAudit, ...], dict[str, str]]]:
    rows = (
        _row("AC1"),
        _row("AC2", claim="the Verified claim", covering=("tests/Verified.py::test_VERIFIED",)),
        _row(
            "AC3",
            covering=(),
            red="UNREDDENABLE: a reader decides",
            red_kind=RedKind.NOT_OBSERVED,
            finding="PENDING-LEDGER: not-Verified-yet",
        ),
    )
    ids = vs.node_ids_for(_module("audit_pdf_99", rows))
    return [
        ("all-pass", rows, _all_pass(ids)),
        ("failed", rows, {**_all_pass(ids), _ID_A: "failed"}),
        ("skipped", rows, {**_all_pass(ids), _ID_A: "skipped"}),
        ("empty", rows, {}),
    ]


@pytest.mark.parametrize(
    ("rows", "seen"), [(r, s) for _, r, s in _scenarios()], ids=[n for n, _, _ in _scenarios()]
)
def test_ac8_the_output_never_says_the_status_word_and_ends_with_the_footer(
    rows: tuple[ACAudit, ...], seen: dict[str, str]
) -> None:
    text = vs.render(_header(), "audit_pdf_99", rows, seen)
    assert STATUS_WORD.search(text) is None, STATUS_WORD.search(text)
    assert text.splitlines()[-1] == FOOTER_LITERAL
    assert text.endswith(FOOTER_LITERAL)


def test_ac8_echoed_text_is_rewritten_not_dropped() -> None:
    rows = (_row("AC1", claim="a Verified claim"),)
    text = vs.render(_header(), "audit_pdf_99", rows, {})
    assert "a [term withheld] claim" in text


def test_ac8_a_usage_error_echoing_the_word_does_not_print_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert vs.main(["PDF-VERIFIED"]) == 2
    assert STATUS_WORD.search(capsys.readouterr().err) is None


def test_ac8_the_runner_source_never_names_the_planning_tree_or_the_status_word() -> None:
    for name in ("verify_spec.py", "_verify_outcomes.py"):
        text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert STATUS_WORD.search(text) is None, name
        assert "ai_" + "plans" not in text, name


def _fake_pytest(
    seen_dirs: list[Path], *, rc: int, fail: bool = False
) -> typing.Callable[..., subprocess.CompletedProcess[str]]:
    def fake(cmd: list[str], **kwargs: typing.Any) -> subprocess.CompletedProcess[str]:
        target = Path(kwargs["env"]["PDF_VERIFY_OUTCOMES_FILE"])
        seen_dirs.append(target.parent)
        assert target.parent.is_dir(), "the work dir must exist while pytest runs"
        assert "-p" in cmd and "_verify_outcomes" in cmd and "no:cacheprovider" in cmd
        assert not any(arg.startswith("-n") for arg in cmd), "addopts is the one -n source"
        if fail:
            raise RuntimeError("pytest could not be started")
        target.write_text('{"tests/t.py::t": "passed"}', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, rc, stdout="out", stderr="")

    return fake


@pytest.mark.parametrize("fail", [False, True], ids=["pytest-ran", "pytest-raised"])
def test_ac8_the_temp_dir_is_removed_on_every_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail: bool
) -> None:
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    seen_dirs: list[Path] = []
    monkeypatch.setattr(vs.subprocess, "run", _fake_pytest(seen_dirs, rc=0, fail=fail))
    if fail:
        with pytest.raises(RuntimeError):
            vs.run_pytest(["tests/t.py::t"])
    else:
        assert vs.run_pytest(["tests/t.py::t"])[:2] == (0, {"tests/t.py::t": "passed"})
    assert len(seen_dirs) == 1
    assert not seen_dirs[0].exists()
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------- #
# AC9 -- the cohort token rule (D4)
# --------------------------------------------------------------------------- #

_FINDING_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{10}|B-\d{3,}|PENDING-LEDGER: \S+")
#: `COMMAND-RED: <command run> | plant: <scratch plant> | saw: <failure line>`
_COMMAND_RED_RE: Final[re.Pattern[str]] = re.compile(
    r"COMMAND-RED: .+ \| plant: .+ \| saw: .+", re.DOTALL
)
_TOKENS: Final[tuple[str, ...]] = tuple(token for token, _ in vs.TOKEN_CLASSES)


def cohort_violations(rows: tuple[ACAudit, ...]) -> list[str]:
    """The D4 cohort rules for `audit_pdf_{82,85,86,88}`; `[]` means compliant.

    1. Every row with `covering == ()` has a `red` that starts with exactly one of
       `CI-EVIDENCED:`, `COMMAND:`, `UNREDDENABLE:`.
    2. `CI-EVIDENCED:` and `UNREDDENABLE:` rows have `red_kind == NOT_OBSERVED`
       and a non-empty `finding`.
    3. A `COMMAND:` row may carry `PLANTED_DEFECT` or `MUTATED_CONFIG` only if its
       `red` contains the marker ``COMMAND-RED: <command> | plant: <scratch plant>
       | saw: <failure line>`` (matched by ``COMMAND-RED: .+ \\| plant: .+ \\|
       saw: .+``, so `|` is the field separator and no field may be empty).
    4. Every `finding` that is present is a ledger fingerprint
       (`^[0-9a-f]{10}$`), a `B-NNN`, or `PENDING-LEDGER: <slug>`.

    Each message begins with the AC id, so a failure names the criterion.
    """
    problems: list[str] = []
    for row in rows:
        started = [token for token in _TOKENS if row.red.startswith(token)]
        if not row.covering and len(started) != 1:
            problems.append(
                f"{row.ac}: covering is () but red starts with none of {list(_TOKENS)} "
                "(an unmeasured row is illegal in this cohort)"
            )
        if started and started[0] in ("CI-EVIDENCED:", "UNREDDENABLE:"):
            if row.red_kind is not RedKind.NOT_OBSERVED:
                problems.append(
                    f"{row.ac}: a {started[0]} row must be NOT_OBSERVED, not {row.red_kind.name}"
                )
            if not row.finding:
                problems.append(f"{row.ac}: a {started[0]} row needs a non-empty finding")
        if (
            started == ["COMMAND:"]
            and row.red_kind in (RedKind.PLANTED_DEFECT, RedKind.MUTATED_CONFIG)
            and not _COMMAND_RED_RE.search(row.red)
        ):
            problems.append(
                f"{row.ac}: a COMMAND: row claims {row.red_kind.name} without the "
                "'COMMAND-RED: ... | plant: ... | saw: ...' marker"
            )
        if row.finding is not None and not _FINDING_RE.fullmatch(row.finding):
            problems.append(
                f"{row.ac}: finding {row.finding!r} is not a fingerprint, a B-NNN, "
                "or 'PENDING-LEDGER: <slug>'"
            )
    return problems


COHORT: Final[tuple[str, ...]] = ("audit_pdf_82", "audit_pdf_85", "audit_pdf_86", "audit_pdf_88")


@pytest.mark.parametrize("module_name", COHORT)
def test_the_pdf106_cohort_classifies_every_uncovered_row(module_name: str) -> None:
    import importlib

    module = importlib.import_module(f"acceptance.{module_name}")  # missing -> FAIL, never skip
    problems = cohort_violations(tuple(module.AUDIT))
    assert problems == [], "\n".join(problems)


# --- proof that the cohort gate fires: synthetic rows only ------------------ #


def test_the_cohort_rule_accepts_a_compliant_synthetic_set() -> None:
    rows = (
        _row("AC1"),
        _row(
            "AC2",
            covering=(),
            red="CI-EVIDENCED: run 1",
            red_kind=RedKind.NOT_OBSERVED,
            finding="PENDING-LEDGER: slug",
        ),
        _row(
            "AC3",
            covering=(),
            red="COMMAND: make x COMMAND-RED: make x | plant: .scratch/p | saw: exit 1",
            red_kind=RedKind.PLANTED_DEFECT,
            finding="0123456789",
        ),
        _row(
            "AC4",
            covering=(),
            red="UNREDDENABLE: r",
            red_kind=RedKind.NOT_OBSERVED,
            finding="B-100",
        ),
    )
    assert cohort_violations(rows) == []


def test_the_cohort_rule_fires_on_an_uncovered_row_with_no_token() -> None:
    rows = (_row("AC7", covering=(), red="no red", red_kind=RedKind.NOT_OBSERVED, finding="B-100"),)
    problems = cohort_violations(rows)
    assert len(problems) == 1
    assert problems[0].startswith("AC7:")


def test_the_cohort_rule_fires_on_a_ci_evidenced_row_with_an_observed_red_kind() -> None:
    rows = (
        _row(
            "AC14",
            covering=(),
            red="CI-EVIDENCED: run 1",
            red_kind=RedKind.PLANTED_DEFECT,
            finding="B-100",
        ),
    )
    problems = cohort_violations(rows)
    assert problems and problems[0].startswith("AC14:")
    assert "NOT_OBSERVED" in problems[0]


def test_the_cohort_rule_fires_on_an_unreddenable_row_without_a_finding() -> None:
    rows = (_row("AC10", covering=(), red="UNREDDENABLE: r", red_kind=RedKind.NOT_OBSERVED),)
    problems = cohort_violations(rows)
    assert problems and problems[0].startswith("AC10:")
    assert "finding" in problems[0]


def test_the_cohort_rule_fires_on_free_text_posing_as_a_finding() -> None:
    rows = (_row("AC3", red_kind=RedKind.NOT_OBSERVED, finding="Not a defect"),)
    problems = cohort_violations(rows)
    assert len(problems) == 1
    assert problems[0].startswith("AC3:")


def test_the_cohort_rule_fires_on_a_command_row_claiming_a_red_it_never_drove() -> None:
    rows = (
        _row(
            "AC5",
            covering=(),
            red="COMMAND: make x",
            red_kind=RedKind.MUTATED_CONFIG,
            finding="B-100",
        ),
    )
    problems = cohort_violations(rows)
    assert problems and problems[0].startswith("AC5:")
    assert "COMMAND-RED" in problems[0]


# --------------------------------------------------------------------------- #
# Proof that the AC3/AC8 gates fire on the REAL script's source and helpers
# --------------------------------------------------------------------------- #


def test_proof_the_status_word_probe_fires_on_a_footer_that_carries_it() -> None:
    planted = "This runner grants nothing: qa-sentinel signs it VERIFIED."
    assert STATUS_WORD.search(planted) is not None
    assert planted != FOOTER_LITERAL


def test_proof_the_grammar_rejects_what_the_spec_forbids() -> None:
    assert [vs.parse_spec(a) for a in ("PDF-85", "PDF-100", "PDF-06")] == ["85", "100", "06"]
    for bad in ("PDF-5", "85", "PDF-NOPE", "pdf-85", "PDF-85 ", "PDF-8٥"):
        assert vs.parse_spec(bad) is None, bad
