"""The first tests `scripts/assert_skips.py` has ever had — PDF-28 B-081.

`grep -rl assert_skips tests/` returned nothing before this file: a live CI
gate consumed by two jobs (`engines-present`'s `--expect-zero` arm and
`without-engines`'s visibility arm) had zero coverage. That is a finding in
its own right, closed here.

B-081: `ENGINE_REASON` matches on a `<skipped>` element's REASON TEXT, not on
WHY pytest recorded the skip. pytest serializes an xfail as
`<skipped type="pytest.xfail" message="...">` — the same element shape a real
skip uses — so a deliberate `@pytest.mark.xfail(reason="... engine ...")`
whose reason happens to name an engine was miscounted as an engine-gated skip.
The fix excludes `type="pytest.xfail"` before the regex ever runs. Four arms,
matching AC17/AC18 of `PDF-28`:

  1. the xfail arm            — NOT counted, `--expect-zero` passes
  2. the complement arm       — a REAL `type="pytest.skip"` engine skip IS
                                 still counted (a fix that also stopped
                                 counting real skips would be indistinguishable
                                 from disabling the gate)
  3. the non-vacuity arm      — zero engine-gated skips WITHOUT `--expect-zero`
                                 still exits 1 (PDF-06's guarantee; the xfail
                                 fix must not weaken it as a side effect)
  4. the failure arm          — a `<failure>` exits 1 regardless of skip counts

All fixtures are synthetic JUnit XML built in `tmp_path`. `git ls-files` shows
no committed report containing an xfail — a committed one would redden
`engines-present` for everyone until removed, and `secret-scan` runs with
`fetch-depth: 0`, so a committed fixture is unforgettable (PDF-28 Design §10).

The RED against the code as it stood before this fix is not re-derived here as
a standing test — a standing test can only exercise the code AS IT NOW READS,
so "run this fixture against the unfixed script" cannot live in the suite the
fix ships in. It was observed once, in a scratch worktree against
`git show HEAD:scripts/assert_skips.py`, and is recorded in `PDF-28`'s
Implementation Log: `engine-gated skips: 1`, exit `1`, before the fix;
`engine-gated skips: 0`, exit `0`, after it — same synthetic report both times.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SCRIPT: Final[Path] = REPO_ROOT / "scripts" / "assert_skips.py"

# The literal shape tests/conftest.py::pytest_collection_modifyitems emits for
# a REAL @pytest.mark.requires(engine) skip.
_REAL_ENGINE_SKIP_MESSAGE = (
    "tesseract unavailable (port OcrEngine); install with: apt install tesseract-ocr"
)

_XFAIL_SKIP = (
    '  <testcase classname="tests.test_pagerange" name="test_oracle_agrees" time="0.001">\n'
    '    <skipped type="pytest.xfail" message="StructureEngine port unavailable"/>\n'
    "  </testcase>\n"
)

_REAL_ENGINE_SKIP = (
    '  <testcase classname="tests.test_testdata" name="test_tesseract_recovery" time="0.001">\n'
    f'    <skipped type="pytest.skip" message="{_REAL_ENGINE_SKIP_MESSAGE}"/>\n'
    "  </testcase>\n"
)

_FAILURE_CASE = (
    '  <testcase classname="tests.test_x" name="test_broken" time="0.001">\n'
    '    <failure message="boom">Traceback...</failure>\n'
    "  </testcase>\n"
)


def _junit(*testcases: str, total: int, skipped: int, failures: int = 0) -> str:
    body = "".join(testcases)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<testsuite name="pytest" tests="{total}" errors="0" '
        f'failures="{failures}" skipped="{skipped}">\n{body}</testsuite>\n'
    )


def _run(report: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(report), *extra_args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_an_xfail_skip_is_not_counted_as_engine_gated(tmp_path: Path) -> None:
    """AC17: a synthetic xfail alone yields `engine-gated skips: 0`, exit 0."""
    report = tmp_path / "junit-engines-present.xml"
    report.write_text(_junit(_XFAIL_SKIP, total=1, skipped=1))

    result = _run(report, "--expect-zero")

    assert result.returncode == 0, result.stderr
    assert "engine-gated skips: 0" in result.stdout


def test_the_complement_real_engine_skip_is_still_counted(tmp_path: Path) -> None:
    """AC18: a real `type="pytest.skip"` engine-gated skip is NOT silenced by
    the xfail exclusion. Mixed with an xfail in the SAME report so a fix that
    dropped the `type` check entirely (counting nothing, or counting both)
    cannot pass this arm by accident."""
    report = tmp_path / "junit-mixed.xml"
    report.write_text(_junit(_XFAIL_SKIP, _REAL_ENGINE_SKIP, total=2, skipped=2))

    result = _run(report, "--expect-zero")

    assert result.returncode == 1, result.stdout
    assert "engine-gated skips: 1" in result.stdout
    assert "1 engine-gated skip(s) with engines INSTALLED" in result.stderr


def test_the_complement_alone_is_counted_and_passes_without_expect_zero(tmp_path: Path) -> None:
    """The without-engines job's own shape: a real engine-gated skip, with no
    xfail in sight, is visible and the run exits 0 (no --expect-zero flag)."""
    report = tmp_path / "junit-without-engines.xml"
    report.write_text(_junit(_REAL_ENGINE_SKIP, total=1, skipped=1))

    result = _run(report)

    assert result.returncode == 0, result.stderr
    assert "engine-gated skips: 1" in result.stdout


def test_zero_engine_gated_skips_without_expect_zero_still_fails(tmp_path: Path) -> None:
    """PDF-06's non-vacuity guarantee, asserted so the xfail fix cannot weaken
    it as a side effect: a without-engines run reporting ZERO engine-gated
    skips is itself a regression, xfail or no xfail. Uses the xfail report
    alone (0 counted) with no --expect-zero -- the mirror of the first arm."""
    report = tmp_path / "junit-without-engines-vacuous.xml"
    report.write_text(_junit(_XFAIL_SKIP, total=1, skipped=1))

    result = _run(report)

    assert result.returncode == 1, result.stdout
    assert "0 engine-gated skips in a without-engines run" in result.stderr


def test_a_failure_exits_nonzero_regardless_of_skip_counts(tmp_path: Path) -> None:
    """A <failure> short-circuits before any skip counting, in both modes."""
    report = tmp_path / "junit-broken.xml"
    report.write_text(_junit(_FAILURE_CASE, _XFAIL_SKIP, total=2, skipped=1, failures=1))

    plain = _run(report)
    expect_zero = _run(report, "--expect-zero")

    assert plain.returncode == 1, plain.stdout
    assert expect_zero.returncode == 1, expect_zero.stdout
    assert "1 test(s) FAILED or ERRORED" in plain.stderr
    assert "1 test(s) FAILED or ERRORED" in expect_zero.stderr


def test_no_committed_fixture_contains_an_xfail() -> None:
    """PDF-28 Design §10: a planted xfail must never reach the real suite --
    committed JUnit would redden `engines-present` for everyone, and
    `secret-scan` runs with `fetch-depth: 0`, so it is unforgettable. All
    fixtures in this module are built in `tmp_path`."""
    result = subprocess.run(
        ["git", "ls-files", "*.xml"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_xml = [line for line in result.stdout.splitlines() if line.strip()]
    for path in tracked_xml:
        content = (REPO_ROOT / path).read_text(errors="replace")
        assert "pytest.xfail" not in content, f"{path} carries a committed xfail JUnit fixture"


# --------------------------------------------------------------------------- #
# PDF-47 AC9 — the opt-out skip is a NAMED, COUNTED class.
#
# Appended at this module's own anchor. Nothing above is touched: the four
# PDF-28 arms and the committed-fixture arm keep their fixtures and their
# assertions byte for byte.
#
# TWO DIRECTIONS, BOTH ASSERTED, because a partition is only a partition if
# neither side leaks. `scripts/assert_skips.py`'s census is FIRST-MATCH-WINS
# over an ordered dict, so it is not enough that the new pattern matches its own
# reason -- no earlier class may claim that reason first, and the new class may
# not claim anybody else's. Both are checked here rather than reasoned about.
#
# WHY THAT IS NOT PARANOIA. `ENGINE_REASON` matches on PROSE over the WHOLE skip
# message, and a skip message can carry a path (`tmp_path`) the test never chose
# -- so a class whose pattern is loose enough, or a reason string that happens
# to embed one of its words, is miscounted with a green exit code. The reason
# string below is a CONTRACT between this file and `tests/test_pypi_provenance.py`,
# imported rather than transcribed, so a reword there cannot silently empty the
# class here.
# --------------------------------------------------------------------------- #

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_pypi_provenance import SKIP_REASON as PROVENANCE_SKIP_REASON  # noqa: E402

_PROVENANCE_SKIP = (
    '  <testcase classname="tests.test_pypi_provenance" '
    'name="test_the_live_endpoint_still_agrees_with_the_recorded_matrix" time="0.001">\n'
    f'    <skipped type="pytest.skip" message="{PROVENANCE_SKIP_REASON}"/>\n'
    "  </testcase>\n"
)


def _census_line(stdout: str, name: str) -> int:
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{name}:"):
            return int(stripped.split(":", 1)[1])
    raise AssertionError(f"the census printed no `{name}` line:\n{stdout}")


def test_the_provenance_skip_class_counts_its_own_reason(tmp_path: Path) -> None:
    """AC9. The opt-out skip is visible BY NAME in the census, not swallowed
    into the unclassified remainder."""
    report = tmp_path / "junit-provenance.xml"
    report.write_text(_junit(_PROVENANCE_SKIP, _REAL_ENGINE_SKIP, total=2, skipped=2))

    result = _run(report)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _census_line(result.stdout, "provenance-endpoint-disabled") == 1, result.stdout
    assert _census_line(result.stdout, "unclassified") == 0, result.stdout


def test_the_provenance_class_neither_swallows_nor_is_swallowed(tmp_path: Path) -> None:
    """AC9's real content. First-match-wins means the two failure modes are
    (a) an earlier class claiming this reason and (b) this class claiming an
    earlier one's. Both are driven, in one report that carries both kinds."""
    report = tmp_path / "junit-partition.xml"
    report.write_text(_junit(_PROVENANCE_SKIP, _REAL_ENGINE_SKIP, total=2, skipped=2))

    stdout = _run(report).stdout

    # (a) the engine-gated class did NOT take the provenance skip ...
    assert _census_line(stdout, "engine-gated") == 1, stdout
    assert "engine-gated skips: 1" in stdout, stdout
    # ... and (b) the provenance class did not take the engine skip.
    assert _census_line(stdout, "provenance-endpoint-disabled") == 1, stdout


def test_the_registered_pattern_matches_the_reason_the_suite_actually_emits() -> None:
    """AC9's RED: reword the skip reason without updating the pattern and this
    fails. The pattern is read from the script itself, so the two files cannot
    come to disagree while both look green."""
    spec = importlib.util.spec_from_file_location("assert_skips_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    classes = module.SKIP_CLASSES
    assert "provenance-endpoint-disabled" in classes, sorted(classes)
    assert classes["provenance-endpoint-disabled"].search(PROVENANCE_SKIP_REASON), (
        f"the registered pattern does not match the reason the suite emits: "
        f"{PROVENANCE_SKIP_REASON!r}"
    )

    # The partition, asserted against the live registry rather than against a
    # copy of it: no OTHER class may claim this reason first.
    claimants = [
        name for name, pattern in classes.items() if pattern.search(PROVENANCE_SKIP_REASON)
    ]
    assert claimants == ["provenance-endpoint-disabled"], (
        f"the provenance skip reason is claimed by {claimants}; first-match-wins makes the "
        "earliest claimant the one that counts, so this reason would be filed under the wrong "
        "class with a green exit code"
    )
