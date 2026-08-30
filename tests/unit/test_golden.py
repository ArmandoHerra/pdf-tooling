"""Self-test of the `golden` primitive (`tests/conftest.py::Golden`).

Deliberately instantiates `Golden` directly against a `tmp_path` directory
rather than going through the real `tests/golden/` fixture — this is a test
of the MECHANISM, not a golden test of any verb's payload (that is each later
spec's own job; see `tests/golden/README.md`). Running these tests must never
write into the real, tracked `tests/golden/` directory, which is exactly what
the working-tree guard in `tests/conftest.py` would flag.
"""

from __future__ import annotations

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

import pytest  # noqa: E402

from conftest import Golden  # noqa: E402


def test_compare_passes_when_the_golden_file_matches(tmp_path: Path) -> None:
    directory = tmp_path / "golden"
    golden = Golden(directory, update=True)
    golden.compare("sample", {"b": 2, "a": 1})

    reader = Golden(directory, update=False)
    reader.compare("sample", {"a": 1, "b": 2})  # key order must not matter


def test_compare_fails_on_a_mismatch(tmp_path: Path) -> None:
    directory = tmp_path / "golden"
    Golden(directory, update=True).compare("sample", {"a": 1})

    reader = Golden(directory, update=False)
    with pytest.raises(AssertionError):
        reader.compare("sample", {"a": 2})


def test_compare_fails_loudly_when_the_file_is_missing_and_not_updating(tmp_path: Path) -> None:
    directory = tmp_path / "golden"
    reader = Golden(directory, update=False)
    with pytest.raises(pytest.fail.Exception):
        reader.compare("never-created", {"a": 1})


def test_a_missing_golden_file_is_never_auto_created_without_update_golden(tmp_path: Path) -> None:
    """The rule that keeps `tests/golden/` out of the working-tree guard's way:
    an ordinary run must never write a golden file into existence."""
    directory = tmp_path / "golden"
    reader = Golden(directory, update=False)
    with pytest.raises(pytest.fail.Exception):
        reader.compare("never-created", {"a": 1})
    assert not (directory / "never-created.json").exists()


def test_update_golden_regenerates_the_file(tmp_path: Path) -> None:
    directory = tmp_path / "golden"
    writer = Golden(directory, update=True)
    writer.compare("sample", {"a": 1})
    writer.compare("sample", {"a": 2})  # a second --update-golden run overwrites
    reader = Golden(directory, update=False)
    reader.compare("sample", {"a": 2})


def test_the_golden_file_on_disk_is_readable_json(tmp_path: Path) -> None:
    import json

    directory = tmp_path / "golden"
    Golden(directory, update=True).compare("sample", {"a": [1, 2, 3], "b": None})
    on_disk = json.loads((directory / "sample.json").read_text())
    assert on_disk == {"a": [1, 2, 3], "b": None}
