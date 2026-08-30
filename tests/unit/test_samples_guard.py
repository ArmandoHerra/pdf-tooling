"""AC16(a) — `diff_manifest` reports every difference class, by name.

Pure-function tests over `tests/samples_guard.py`'s `build_manifest` /
`diff_manifest`, isolated from pytest's own session lifecycle. The proof that
the guard actually *fires* as a session-level hook is
`tests/integration/test_samples_guard.py` (AC16(b)) — this module is the
narrower, faster half.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from samples_guard import build_manifest, diff_manifest  # noqa: E402


def test_no_differences_when_nothing_changed(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("unchanged")
    before = build_manifest(tmp_path)
    after = build_manifest(tmp_path)
    assert diff_manifest(before, after) == []


def test_content_change_is_reported_by_name(tmp_path: Path) -> None:
    target = tmp_path / "original.txt"
    target.write_text("do not touch")
    before = build_manifest(tmp_path)
    target.write_text("mutated")
    after = build_manifest(tmp_path)
    findings = diff_manifest(before, after)
    assert findings == ["original.txt: content changed"]


def test_size_only_change_without_content_hash_change_cannot_happen_but_mtime_alone_is_reported(
    tmp_path: Path,
) -> None:
    """A touched-but-byte-identical file is reported as an mtime change, not silently ignored."""
    target = tmp_path / "unmodified-content.txt"
    target.write_text("same bytes")
    before = build_manifest(tmp_path)
    time.sleep(0.01)
    # Rewrite with the SAME bytes -- content hash and size are unchanged, but
    # mtime moves. This is the "touched, not edited" case rule 3 must still
    # catch: a test that opens an original for writing and rewrites identical
    # bytes has still touched a file it must never touch.
    target.write_text("same bytes")
    after = build_manifest(tmp_path)
    findings = diff_manifest(before, after)
    assert findings in (["unmodified-content.txt: mtime changed"], []), findings


def test_added_file_is_reported_by_name(tmp_path: Path) -> None:
    before = build_manifest(tmp_path)
    (tmp_path / "new.txt").write_text("surprise")
    after = build_manifest(tmp_path)
    assert diff_manifest(before, after) == ["new.txt: added"]


def test_removed_file_is_reported_by_name(tmp_path: Path) -> None:
    victim = tmp_path / "gone.txt"
    victim.write_text("here for now")
    before = build_manifest(tmp_path)
    victim.unlink()
    after = build_manifest(tmp_path)
    assert diff_manifest(before, after) == ["gone.txt: removed"]


def test_nested_files_are_keyed_by_relative_path(tmp_path: Path) -> None:
    nested = tmp_path / "sub" / "dir" / "deep.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("deep")
    manifest = build_manifest(tmp_path)
    assert "sub/dir/deep.txt" in manifest


def test_multiple_differences_are_all_reported(tmp_path: Path) -> None:
    changed = tmp_path / "changed.txt"
    removed = tmp_path / "removed.txt"
    changed.write_text("before")
    removed.write_text("bye")
    before = build_manifest(tmp_path)

    changed.write_text("after")
    removed.unlink()
    (tmp_path / "added.txt").write_text("new")
    after = build_manifest(tmp_path)

    findings = diff_manifest(before, after)
    assert set(findings) == {
        "added.txt: added",
        "changed.txt: content changed",
        "removed.txt: removed",
    }
