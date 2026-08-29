"""The temp namespace: one owner, and the decided "report, never sweep" posture.

``PLAN.md`` §12 R-07 is settled — a stray temp file is *evidence that a process
was killed between create and replace*, and evidence that deletes itself is not
evidence. So the assertion that matters here is not what ``find_stray_temps``
returns; it is that everything it returned is **still on disk afterwards**. A
janitor that quietly tidied up would pass a "returns the right paths" test and
destroy the only artefact a user has when they ask what happened.

The single-owner rule is enforced structurally by a grep in
``test_import_boundaries``-adjacent CI checks rather than here, and asserted from
this side too: the predicate is importable, so ``ops/discovery.py`` has no reason
to hardcode a second copy of the prefix and drift away from the writer.
"""

from __future__ import annotations

from pathlib import Path

from pdf_toolkit.safety import TEMP_PREFIX, find_stray_temps, is_toolkit_temp


def test_the_prefix_is_hidden_and_product_specific() -> None:
    assert TEMP_PREFIX.startswith(".")
    assert "pdftoolkit" in TEMP_PREFIX


def test_the_predicate_recognises_a_toolkit_temp(tmp_path: Path) -> None:
    assert is_toolkit_temp(tmp_path / f"{TEMP_PREFIX}abc123")
    assert is_toolkit_temp(f"{TEMP_PREFIX}abc123")


def test_the_predicate_rejects_everything_else(tmp_path: Path) -> None:
    for name in ("doc.pdf", ".hidden", "pdftoolkit-abc", ".pdftoolkitabc", "sub/doc.pdf"):
        assert not is_toolkit_temp(tmp_path / name), name


def test_find_stray_temps_reports_and_never_sweeps(tmp_path: Path) -> None:
    """PLAN §12 R-07, mechanized: after the call, every stray still exists."""
    planted = [
        tmp_path / f"{TEMP_PREFIX}one",
        tmp_path / "nested" / f"{TEMP_PREFIX}two",
        tmp_path / "nested" / "deeper" / f"{TEMP_PREFIX}three",
    ]
    for stray in planted:
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_bytes(b"residue")
    (tmp_path / "doc.pdf").write_bytes(b"a real output")

    found = find_stray_temps(tmp_path)

    assert set(found) == set(planted)
    assert all(stray.exists() for stray in planted), "find_stray_temps must never delete"
    assert (tmp_path / "doc.pdf").exists()


def test_find_stray_temps_is_sorted_and_deterministic(tmp_path: Path) -> None:
    for name in ("c", "a", "b"):
        (tmp_path / f"{TEMP_PREFIX}{name}").write_bytes(b"")
    found = find_stray_temps(tmp_path)
    assert list(found) == sorted(found)


def test_find_stray_temps_tolerates_a_root_that_is_not_a_directory(tmp_path: Path) -> None:
    assert find_stray_temps(tmp_path / "missing") == ()
    plain = tmp_path / "doc.pdf"
    plain.write_bytes(b"x")
    assert find_stray_temps(plain) == ()


def test_a_directory_named_like_a_temp_is_not_reported(tmp_path: Path) -> None:
    """Residue is a file. A directory with that name is somebody else's problem."""
    (tmp_path / f"{TEMP_PREFIX}dir").mkdir()
    assert find_stray_temps(tmp_path) == ()
