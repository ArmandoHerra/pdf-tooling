"""PDF-86 AC2, closed by PDF-114 D4/D5 -- the startup-cost halves reach the `-ra` line.

`test_total_startup_import_cost_stays_under_its_ceiling` used to carry both
numerator and denominator FACTORS only from column ~363 of its first line, so on
the `-ra` `FAILED` line of a non-CI terminal (where pytest keeps ONLY the first
line of a message and trims it to the terminal width) neither half ever appeared.
`startup_cost_lead` moves them to the head of that line.

WHAT IS MEASURED, AND HOW
-------------------------
A REAL inner pytest session, in a subprocess over a throwaway project under
`tmp_path` (the `tests/integration/test_samples_guard_fires.py::_run_inner_pytest`
precedent), runs ONE test whose file name, function name and therefore node id
are byte-identical to the real arm's (the `FAILED <node id>` prefix is 94
characters). That test raises
`AssertionError(<the message the product's own renderer produced>)`. The line is
located by its `FAILED ` prefix and every figure is matched on THAT LINE ONLY:
matching the whole output would also see the `--tb=line` `E` line, which always
carried both halves, and would go green for the wrong reason -- the original
finding's trap.

THE ENVIRONMENT IS EXPLICIT. `CI` and `BUILD_NUMBER` are removed unless the arm
sets them: pytest's `running_on_ci()` untruncates the `-ra` line under either, so
an inherited `CI=true` would make the 200-column arm pass for the wrong reason.
`-q` and `-vv` net out to verbose 1, so nothing here relies on `-vv`, and
`--force-short-summary` is never passed.

ARM (iii) RECORDS A FACT RATHER THAN A WISH: below 100 columns pytest prints NO
message for a node id whose `FAILED ` line prefix is 94 characters
(`_format_trimmed` returns `None` when fewer than six columns remain), so "the halves
at 80 columns" cannot be reached by any message on this arm. If a pytest upgrade
changes that rule this arm reds and says so.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

_tests_dir = str(Path(__file__).resolve().parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)
from test_import_boundaries import (  # noqa: E402  (path must be set up first)
    STARTUP_CALIBRATED,
    STARTUP_COST_CALIBRATION,
    StartupCondition,
    startup_cost_observation,
    synthetic_readings,
)

ARM_FILE: Final[str] = "tests/test_import_boundaries.py"
ARM_NAME: Final[str] = "test_total_startup_import_cost_stays_under_its_ceiling"
ARM_NODE_ID: Final[str] = f"{ARM_FILE}::{ARM_NAME}"
_CONDITION: Final[StartupCondition] = StartupCondition("linux", "3.12")

#: AC1's two vectors: (numerator factor, denominator factor, carrier word).
_VECTORS: Final = (
    pytest.param(1.68, 0.99, "NUMERATOR", id="numerator-side"),
    pytest.param(0.99, 0.55, "DENOMINATOR", id="denominator-collapse"),
)


#: The vector the three inner-session arms render: AC1's denominator-collapse one.
_DENOMINATOR_COLLAPSE: Final = (0.99, 0.55)
_DENOMINATOR_COLLAPSE_CARRIER: Final = "DENOMINATOR"


class _Rendered:
    """The product's own message, and the exact lead text it must carry."""

    def __init__(self, numerator_factor: float, denominator_factor: float) -> None:
        recorded = STARTUP_COST_CALIBRATION[_CONDITION]
        numerator = int(recorded.numerator_median_us * numerator_factor)
        denominator = int(recorded.denominator_median_us * denominator_factor)
        self.message = startup_cost_observation(
            STARTUP_CALIBRATED,
            _CONDITION,
            synthetic_readings(numerator, denominator),
            floor_names=recorded.floor_names,
            attributable=273,
        )
        # Factors as the renderer divides them: the integer-truncated medians.
        self.numerator_text = f"numerator x{numerator / recorded.numerator_median_us:.3f}"
        self.denominator_text = f"denominator x{denominator / recorded.denominator_median_us:.3f}"


def _inner_failed_line(message: str, *, columns: int, ci: bool, tmp_path: Path) -> str:
    """Run the arm's twin in a real inner pytest and return its `FAILED` line."""
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "pytest.ini").write_text("[pytest]\n")
    (project / ARM_FILE).write_text(f"def {ARM_NAME}():\n    raise AssertionError({message!r})\n")
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"CI", "BUILD_NUMBER", "COLUMNS", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"}
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["COLUMNS"] = str(columns)
    if ci:
        env["CI"] = "true"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            ARM_FILE,
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "-p",
            "no:xdist",
            "-q",
            "--tb=line",
            "-ra",
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 1, (
        f"the inner session was expected to fail its one test:\n{result.stdout}\n{result.stderr}"
    )
    failed = [line for line in result.stdout.splitlines() if line.startswith("FAILED ")]
    assert len(failed) == 1, f"expected exactly one FAILED line, got {failed!r}:\n{result.stdout}"
    assert failed[0].startswith(f"FAILED {ARM_NODE_ID}"), failed[0]
    return failed[0]


def test_the_startup_cost_halves_survive_a_200_column_terminal(tmp_path: Path) -> None:
    """PDF-86 AC2, `-ra` half, non-CI terminal: both factors and the verdict on the line.

    RED: put the lead behind the readings header (or strip the factors from it)
    -> the line is cut before the first factor -> red naming the missing text.
    """
    rendered = _Rendered(*_DENOMINATOR_COLLAPSE)

    line = _inner_failed_line(rendered.message, columns=200, ci=False, tmp_path=tmp_path)

    assert rendered.numerator_text in line, f"numerator factor missing from -ra line:\n{line}"
    assert rendered.denominator_text in line, f"denominator factor missing from -ra line:\n{line}"
    assert f"the {_DENOMINATOR_COLLAPSE_CARRIER} carries this red" in line, (
        f"verdict missing from -ra line:\n{line}"
    )


def test_the_startup_cost_halves_survive_a_ci_log(tmp_path: Path) -> None:
    """The same three facts under `CI=true` at 80 columns.

    A REGRESSION PIN, not a change: `running_on_ci()` makes pytest keep the whole
    first line, so this held before PDF-114 and must keep holding in every CI log.
    """
    rendered = _Rendered(*_DENOMINATOR_COLLAPSE)

    line = _inner_failed_line(rendered.message, columns=80, ci=True, tmp_path=tmp_path)

    assert rendered.numerator_text in line, f"numerator factor missing from CI line:\n{line}"
    assert rendered.denominator_text in line, f"denominator factor missing from CI line:\n{line}"
    assert f"the {_DENOMINATOR_COLLAPSE_CARRIER} carries this red" in line, (
        f"verdict missing from CI line:\n{line}"
    )


def test_the_node_id_leaves_no_room_below_100_columns(tmp_path: Path) -> None:
    """E6 consequence 2, recorded as a measured fact: no message fits at 80 columns.

    The 94-character `FAILED <node id>` prefix is pinned by the roster guard, so no message design
    can put a figure on this line below 100 columns. If a pytest upgrade changes
    the rule this reds, and the reader learns it from here rather than re-chasing
    the ledger slug's "at 80 columns".
    """
    rendered = _Rendered(*_DENOMINATOR_COLLAPSE)

    line = _inner_failed_line(rendered.message, columns=80, ci=False, tmp_path=tmp_path)

    assert len(f"FAILED {ARM_NODE_ID}") == 94, "the FAILED prefix + node id is not 94 characters"
    assert " - " not in line, (
        f"pytest now prints a message on the -ra line at 80 columns; the impossibility "
        f"this arm records no longer holds:\n{line}"
    )


@pytest.mark.parametrize(("numerator_factor", "denominator_factor", "carrier"), _VECTORS)
def test_the_lead_clause_opens_the_first_line_and_names_the_body_carrier(
    numerator_factor: float, denominator_factor: float, carrier: str
) -> None:
    """PDF-114 AC4: the lead is within the first 100 characters, and agrees with the body."""
    message = _Rendered(numerator_factor, denominator_factor).message

    first_line = message.split("\n", 1)[0]
    head = first_line[:100]
    assert first_line.startswith("numerator x"), first_line[:120]
    assert "/ denominator x" in head and "carries this red" in head, head
    lead_carrier = re.match(r".*-> the (\w+) carries this red; ", first_line)
    body_carrier = re.search(r"-- the (\w+) carries this red \(x", first_line)
    assert lead_carrier is not None and body_carrier is not None, first_line
    assert lead_carrier.group(1) == body_carrier.group(1) == carrier
