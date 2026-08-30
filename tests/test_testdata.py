"""AC3 / AC4 / AC17 — the two committed `testdata/` binaries.

`testdata/` holds exactly two artifacts that cannot be generated at test time
(`tests/corpus.py`'s module docstring; `testdata/README.md`). This module pins
the contract `PDF-12` (`repair`) and `PDF-15` (`ocr`) consume, and the privacy
boundary that keeps `$PDF_TOOLKIT_SAMPLES_DIR` out of anything committed.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pikepdf
import pypdf
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTDATA = REPO_ROOT / "testdata"
MALFORMED = TESTDATA / "malformed.pdf"
SCANNED_PAGE = TESTDATA / "scanned-page.png"

MAX_MALFORMED_BYTES = 8 * 1024


def console_script() -> list[str]:
    """The argv prefix that runs the installed CLI as a real process.

    Mirrors `tests/test_cli_spine.py::console_script` — duplicated rather than
    imported so this module has no dependency on a sibling test module's
    internals surviving a refactor.
    """
    import shutil

    sibling = Path(sys.executable).parent / "pdftoolkit"
    if sibling.exists():
        return [str(sibling)]
    found = shutil.which("pdftoolkit")
    if found:
        return [found]
    return [sys.executable, "-m", "pdf_toolkit"]


# --------------------------------------------------------------------------- #
# AC3 -- testdata/ contains exactly two artifacts plus README.md
# --------------------------------------------------------------------------- #


def test_testdata_holds_exactly_two_artifacts_plus_readme() -> None:
    entries = sorted(p.name for p in TESTDATA.iterdir() if p.is_file())
    assert entries == ["README.md", "malformed.pdf", "scanned-page.png"], (
        "testdata/ has drifted from the two-artifact contract -- see testdata/README.md"
    )


# --------------------------------------------------------------------------- #
# AC3 -- malformed.pdf: size, the four X-20 properties
# --------------------------------------------------------------------------- #


def test_malformed_pdf_is_under_the_size_cap() -> None:
    size = MALFORMED.stat().st_size
    assert size < MAX_MALFORMED_BYTES, (
        f"malformed.pdf is {size} bytes, must be < {MAX_MALFORMED_BYTES}"
    )


def test_property_1_xref_and_trailer_are_destroyed() -> None:
    text = MALFORMED.read_bytes()
    for marker in (b"\nxref", b"\ntrailer", b"\nstartxref"):
        assert marker not in text, (
            f"malformed.pdf still carries {marker!r} -- xref/trailer not destroyed"
        )


def test_property_2_body_objects_are_intact() -> None:
    """Recovery finds all five objects and a coherent one-page document."""
    with pikepdf.open(str(MALFORMED), attempt_recovery=True) as pdf:
        assert len(pdf.pages) == 1
        assert pdf.Root.get("/Type") == pikepdf.Name("/Catalog")


def test_property_3_info_exits_1_on_the_malformed_fixture() -> None:
    result = subprocess.run(
        [*console_script(), "info", str(MALFORMED)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 1, (
        f"pdftoolkit info exited {result.returncode}, not 1, on the malformed fixture\n"
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_property_4_pikepdf_recovers_with_at_least_one_warning() -> None:
    """libqpdf recovery, via pikepdf -- never a `qpdf` CLI shell-out (HC-1)."""
    with pikepdf.open(str(MALFORMED), attempt_recovery=True) as pdf:
        warnings = pdf.get_warnings()
    assert len(warnings) >= 1, (
        "pikepdf recovered malformed.pdf with zero warnings -- not a repair signal"
    )


def test_a_strict_pypdf_read_of_malformed_pdf_errors() -> None:
    """The complementary half of AC3's own wording: a strict reader must fail."""
    with pytest.raises(Exception):  # noqa: B017 - pypdf raises its own PdfReadError subclasses
        reader = pypdf.PdfReader(str(MALFORMED), strict=True)
        list(reader.pages)  # force parsing, not just header sniffing


# --------------------------------------------------------------------------- #
# AC4 -- testdata/README.md names both artifacts, provenance and defect
# --------------------------------------------------------------------------- #


def test_readme_documents_both_artifacts() -> None:
    text = (TESTDATA / "README.md").read_text()
    mentions = text.count("malformed.pdf") + text.count("scanned-page.png")
    assert mentions >= 2, "testdata/README.md must name both artifacts"
    assert "PDF-12" in text, "testdata/README.md must name the spec that consumes malformed.pdf"
    assert "PDF-15" in text, "testdata/README.md must name the spec that consumes scanned-page.png"


# --------------------------------------------------------------------------- #
# scanned-page.png: OCR recoverability, and AC17's privacy boundary
# --------------------------------------------------------------------------- #


def test_scanned_page_is_a_small_committed_raster() -> None:
    assert SCANNED_PAGE.is_file()
    assert SCANNED_PAGE.stat().st_size < 50 * 1024


@pytest.mark.requires("tesseract")
def test_tesseract_recovers_text_from_scanned_page() -> None:
    result = subprocess.run(
        ["tesseract", str(SCANNED_PAGE), "stdout"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "tesseract recovered no text from testdata/scanned-page.png"


def test_no_testdata_file_shares_a_hash_with_a_real_sample(pytestconfig: pytest.Config) -> None:
    """AC17 -- rule 4's realistic violation, mechanized as a standing check.

    Skips visibly when the operator's corpus is not configured -- this check
    can only run against real content, and it must never silently pass by
    having nothing to compare against.
    """
    samples_dir = os.environ.get("PDF_TOOLKIT_SAMPLES_DIR")
    if not samples_dir or not Path(samples_dir).is_dir():
        pytest.skip(
            "PDF_TOOLKIT_SAMPLES_DIR not set -- real-document arm skipped (PLAN.md §10.1 rule 5)"
        )
    testdata_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in TESTDATA.iterdir()
        if path.is_file() and path.name != "README.md"
    }
    root = Path(samples_dir)
    for sample_path in root.rglob("*"):
        if not sample_path.is_file():
            continue
        sample_hash = hashlib.sha256(sample_path.read_bytes()).hexdigest()
        for testdata_name, testdata_hash in testdata_hashes.items():
            assert sample_hash != testdata_hash, (
                f"testdata/{testdata_name} shares a SHA-256 with a file in the operator's "
                "real-document corpus -- rule 4 requires testdata/ never contain sample content"
            )
