"""AC16(b) — the originals-integrity guard actually fires, proven with a
SYNTHETIC samples directory. The operator's real corpus is never involved in
proving the guard works (ruling X-25) — the mechanism that protects
irreplaceable personal documents must never itself be tested by risking them.

An INNER pytest session, run as a real subprocess against a throwaway project
under `tmp_path`, loads the exact same `tests/samples_guard.py` module as a
plugin and runs one test that deliberately writes to a fake "original". The
outer assertions are: the inner session exits non-zero, and the mutated
file's name appears in its output.

The second half proves the controller-only guard (`if hasattr(config,
"workerinput")`) actually holds under the suite's own default parallelism:
run the SAME synthetic project under `-n 2` and confirm the violation is
reported exactly once, not once per worker.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REAL_TESTS_DIR = Path(__file__).resolve().parents[1]

_INNER_CONFTEST = 'pytest_plugins = ["samples_guard"]\n'

_INNER_MALICIOUS_TEST = """
import os
from pathlib import Path

def test_writes_to_an_original():
    root = Path(os.environ["PDF_TOOLKIT_SAMPLES_DIR"])
    (root / "original.txt").write_text("mutated by a planted violation")
"""

_INNER_BENIGN_TEST = """
def test_does_nothing_interesting():
    assert 1 + 1 == 2
"""


def _build_synthetic_project(project_dir: Path, originals_dir: Path) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    originals_dir.mkdir(parents=True, exist_ok=True)
    (originals_dir / "original.txt").write_text("do not touch")
    (project_dir / "conftest.py").write_text(_INNER_CONFTEST)
    (project_dir / "test_malicious.py").write_text(_INNER_MALICIOUS_TEST)


def _run_inner_pytest(
    project_dir: Path, originals_dir: Path, *extra_args: str
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PDF_TOOLKIT_SAMPLES_DIR"] = str(originals_dir)
    env["PYTHONPATH"] = str(REAL_TESTS_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(project_dir),
            "-q",
            "-p",
            "no:cacheprovider",
            *extra_args,
        ],
        cwd=project_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_the_guard_fails_the_inner_session_and_names_the_mutated_file(tmp_path: Path) -> None:
    project_dir = tmp_path / "synthetic-project"
    originals_dir = tmp_path / "synthetic-originals"
    _build_synthetic_project(project_dir, originals_dir)

    result = _run_inner_pytest(project_dir, originals_dir)

    assert result.returncode != 0, (
        f"the inner session did not fail after a planted original-mutation:\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "original.txt" in combined, (
        f"the mutated file's name did not appear in the inner session's output:\n{combined}"
    )
    assert "content changed" in combined, combined


def test_the_guard_never_fires_when_nothing_is_mutated(tmp_path: Path) -> None:
    """The negative control: an inner session that touches nothing stays green."""
    project_dir = tmp_path / "synthetic-project-benign"
    originals_dir = tmp_path / "synthetic-originals-benign"
    project_dir.mkdir(parents=True)
    originals_dir.mkdir(parents=True)
    (originals_dir / "original.txt").write_text("do not touch")
    (project_dir / "conftest.py").write_text(_INNER_CONFTEST)
    (project_dir / "test_benign.py").write_text(_INNER_BENIGN_TEST)

    result = _run_inner_pytest(project_dir, originals_dir)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


def test_the_guard_runs_exactly_once_under_dash_n_2(tmp_path: Path) -> None:
    """AC16 -- the controller-only guard, proven under the suite's own -n auto style parallelism.

    Several inner test files so xdist actually distributes work across two
    workers, one of which plants the violation. If the `workerinput` guard in
    `samples_guard.py` were missing, both workers AND the controller would
    each hash the originals and each report a finding -- three reports, not
    one.
    """
    project_dir = tmp_path / "synthetic-project-n2"
    originals_dir = tmp_path / "synthetic-originals-n2"
    project_dir.mkdir(parents=True)
    originals_dir.mkdir(parents=True)
    (originals_dir / "original.txt").write_text("do not touch")
    (project_dir / "conftest.py").write_text(_INNER_CONFTEST)
    (project_dir / "test_malicious.py").write_text(_INNER_MALICIOUS_TEST)
    for index in range(4):
        (project_dir / f"test_filler_{index}.py").write_text(_INNER_BENIGN_TEST)

    result = _run_inner_pytest(project_dir, originals_dir, "-n", "2")

    combined = result.stdout + result.stderr
    occurrences = combined.count("original.txt: content changed")
    assert occurrences == 1, (
        f"the guard reported the violation {occurrences} time(s) under -n 2, expected exactly 1 "
        f"(controller-only guard is not holding):\n{combined}"
    )
    assert result.returncode != 0
