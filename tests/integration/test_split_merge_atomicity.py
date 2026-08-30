"""AC17 (the chokepoint actually holds) and AC20 (failure atomicity and exit
codes) — ``merge``/``split`` (Design §D1, §D7, §D9).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pdf_toolkit import errors
from pdf_toolkit.ops.merge import merge_documents, resolve_merge_inputs
from pdf_toolkit.ops.split import split_document
from pdf_toolkit.safety import atomic as atomic_module
from pdf_toolkit.safety.policy import SafetyPolicy

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import run_cli  # noqa: E402


def make_policy(**overrides: object) -> SafetyPolicy:
    values: dict[str, object] = {
        "dry_run": False,
        "force": False,
        "in_place": False,
        "backup": True,
        "assume_yes": False,
        "is_tty": False,
        "threads": 1,
    }
    values.update(overrides)
    return SafetyPolicy(**values)  # type: ignore[arg-type]


def _make_source(directory: Path, pages: int, *, name: str = "src.pdf") -> Path:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    made = canvas.Canvas(str(path), pagesize=letter)
    for number in range(1, pages + 1):
        made.drawString(72, 700, f"src page {number}")
        made.showPage()
    made.save()
    return path


# --------------------------------------------------------------------------- #
# AC17 -- with AtomicWriter.__enter__ patched to raise, zero files appear.
# --------------------------------------------------------------------------- #


def test_merge_produces_zero_files_when_the_chokepoint_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_source(tmp_path / "src", pages=2)
    output = tmp_path / "out.pdf"

    def _boom(self: object) -> None:
        raise RuntimeError("planted chokepoint failure")

    monkeypatch.setattr(atomic_module.AtomicWriter, "__enter__", _boom)
    inputs = resolve_merge_inputs((str(source),))
    with pytest.raises(RuntimeError):
        merge_documents(inputs, output=output, bookmarks="none", policy=make_policy())
    assert not output.exists()
    assert list(tmp_path.rglob(".pdftoolkit-*")) == []


def test_split_produces_zero_files_when_the_chokepoint_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_source(tmp_path / "src", pages=3)
    out_dir = tmp_path / "parts"

    def _boom(self: object) -> None:
        raise RuntimeError("planted chokepoint failure")

    monkeypatch.setattr(atomic_module.AtomicWriter, "__enter__", _boom)
    with pytest.raises(RuntimeError):
        split_document(
            source,
            mode="each-page",
            every=None,
            ranges=(),
            name_template=None,
            out_dir=out_dir,
            policy=make_policy(),
        )
    written = [p for p in out_dir.rglob("*") if p.is_file()] if out_dir.exists() else []
    assert written == []
    assert list(tmp_path.rglob(".pdftoolkit-*")) == []


# --------------------------------------------------------------------------- #
# AC20 -- exit codes and atomicity, driven as real subprocesses (a traceback
# is only observable there).
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
def test_nonexistent_merge_input_is_exit_4_no_traceback(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pdf"
    result = run_cli("merge", str(missing), "-O", str(tmp_path / "out.pdf"), cwd=tmp_path)
    assert result.returncode == 4
    assert "Traceback" not in result.stderr


@pytest.mark.e2e
def test_corrupt_merge_input_is_exit_1_no_traceback(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not a pdf at all")
    result = run_cli("merge", str(corrupt), "-O", str(tmp_path / "out.pdf"), cwd=tmp_path)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_merge_second_input_failure_writes_zero_bytes_to_target(tmp_path: Path) -> None:
    """D1's fail-closed contract: the second input fails INSIDE
    `merge_documents`'s own document-opening loop (a corrupt file, not a
    missing one -- a missing path is already caught by
    `resolve_merge_inputs` before this function is ever called, which is a
    stronger, earlier form of the same guarantee)."""
    good = _make_source(tmp_path / "good", pages=2)
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not a pdf at all")
    output = tmp_path / "out.pdf"
    inputs = resolve_merge_inputs((str(good), str(corrupt)))
    with pytest.raises(errors.FailureError):
        merge_documents(inputs, output=output, bookmarks="none", policy=make_policy())
    assert not output.exists()


@pytest.mark.e2e
def test_split_planning_failure_writes_nothing(tmp_path: Path) -> None:
    """A malformed --ranges part is a planning failure (PDF-03's own message
    surfaces unmodified); zero files are written and no traceback appears."""
    source = _make_source(tmp_path / "src", pages=5)
    out_dir = tmp_path / "parts"
    result = run_cli(
        "split", str(source), "--ranges", "1-2,1--3", "--out-dir", str(out_dir), cwd=tmp_path
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert not out_dir.exists() or list(out_dir.iterdir()) == []
