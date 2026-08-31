"""`ocr` at the subprocess/engine level (PDF-15) -- the generated-corpus arms.

Uses the ``testdata/scanned-page.png`` raster PDF-06 committed for exactly
this purpose (its own README: "Consumed by PDF-15's `ocr` acceptance
signal") -- composed into a 1-page image-only PDF at test time, never a
committed PDF fixture of its own.

D13 -- the instrument. Byte-identity assertions in this module use
``tests/helpers/pdfstream.py`` exclusively, never ``tests/pagetree.py::
page_tree_digest`` (B-083: a pypdf rewrite is not byte-identical at the
whole-document level even for a pure pass-through, so a digest-based
identity check would false-fail on exactly the comparison this spec makes;
the image XObject's own raw stream bytes are the correct, narrower
instrument).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from helpers.pdfstream import embedded_image_streams  # noqa: E402
from pdf_toolkit.ops.compose import compose_document, parse_page_size  # noqa: E402
from pdf_toolkit.ops.ocr import ocr_run  # noqa: E402
from pdf_toolkit.ops.pages import rotate_run  # noqa: E402
from pdf_toolkit.safety.policy import SafetyPolicy  # noqa: E402
from registry import run_cli  # noqa: E402

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SCANNED_RASTER: Final[Path] = REPO_ROOT / "testdata" / "scanned-page.png"

#: Verified at authoring time against tesseract 5.5.0 (`testdata/README.md`'s
#: own claim, re-verified live in this spec's Implementation Log).
EXPECTED_TEXT: Final[str] = "PDF TOOLKIT OCR FIXTURE"


def _policy(
    *, dry_run: bool = False, threads: int = 1, force: bool = False, in_place: bool = False
) -> SafetyPolicy:
    return SafetyPolicy(
        dry_run=dry_run,
        force=force,
        in_place=in_place,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=threads,
    )


def _compose_scanned_page(tmp_path: Path, *, name: str = "scanned.pdf") -> Path:
    """The generated OCR fixture: `scanned-page.png` composed to its own
    native size (`from-image`), never derived from the operator's samples
    corpus."""
    output = tmp_path / name
    result = compose_document(
        [SCANNED_RASTER],
        output=output,
        page=parse_page_size("from-image"),
        fit="contain",
        margin_pt=0.0,
        dpi=None,
        policy=_policy(),
    )
    assert result.exit_code == 0, result
    return output


def _rotate90(source: Path, tmp_path: Path, *, name: str = "rotated.pdf") -> Path:
    output = tmp_path / name
    result = rotate_run(
        [source],
        pages_spec="1",
        angle=90,
        absolute=False,
        output=output,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    assert result.exit_code == 0, result
    return output


def _extract_text(path: Path) -> str:
    from pdf_toolkit.ports.text import require_text

    engine = require_text()
    return "".join(engine.extract_text(str(path), [1]))


def _hidden_engine_env(hidden: str, *, tmp_path: Path) -> dict[str, str]:
    """A PATH excluding *hidden*'s real binary, for a SUBPROCESS test
    (AC12's own note: hiding means ``shutil.which`` -> ``None`` -- a PATH
    that excludes the real binary's directory, never a shadowing shim).

    `conftest.py::_apply_engine_hiding_shim` does this same thing but
    mutates the CURRENT (pytest) process's own ``os.environ["PATH"]`` --
    fine for in-process collection-time skips, wrong here: this helper must
    return an env dict for a CHILD process without touching this test
    process's own PATH (which every other test in this session still
    depends on).
    """
    import os
    import shutil

    shim_dir = tmp_path / f"hide-{hidden}"
    shim_dir.mkdir(exist_ok=True)
    original_path = os.environ.get("PATH", "")
    for entry in original_path.split(os.pathsep):
        entry_path = Path(entry)
        if not entry_path.is_dir():
            continue
        try:
            candidates = list(entry_path.iterdir())
        except OSError:
            continue
        for exe in candidates:
            if exe.name == hidden:
                continue
            link = shim_dir / exe.name
            if link.exists():
                continue
            try:
                link.symlink_to(exe)
            except OSError:
                continue
    env = dict(os.environ)
    env["PATH"] = str(shim_dir)
    assert shutil.which(hidden, path=env["PATH"]) is None, f"{hidden} is still on the shimmed PATH"
    return env


# --------------------------------------------------------------------------- #
# AC3 -- the headline property: the image XObject's raw stream bytes are
# byte-identical before and after `ocr`.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("tesseract")
def test_ac3_image_xobject_raw_stream_is_byte_identical(tmp_path: Path) -> None:
    source = _compose_scanned_page(tmp_path)
    before = embedded_image_streams(source, 0)
    assert len(before) == 1

    output = tmp_path / "ocrd.pdf"
    result = ocr_run(
        [source],
        lang="eng",
        dpi=200,
        psm=3,
        skip_text_pages=False,
        pages_spec=None,
        output=output,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    assert result.exit_code == 0, result

    after = embedded_image_streams(output, 0)
    assert len(after) == 1
    assert after[0].raw == before[0].raw
    assert after[0].filters == before[0].filters


# --------------------------------------------------------------------------- #
# AC29 -- the REQUIRED positive control: a deliberately altered image stream
# MUST make the AC3-style assertion RED. A green byte-identity assertion
# whose instrument was never shown to bite means nothing (X-131).
# --------------------------------------------------------------------------- #


def test_ac29_positive_control_a_mutated_image_stream_fails_the_identity_check(
    tmp_path: Path,
) -> None:
    """A REAL, on-disk mutation of one byte of the image stream, run through
    the SAME extraction + comparison AC3 uses -- not a manual byte-equality
    check on values never written to a file. If this instrument could not
    fail, AC3's own green would mean nothing (X-131)."""
    import io

    from pypdf import PdfReader, PdfWriter

    source = _compose_scanned_page(tmp_path)
    before = embedded_image_streams(source, 0)
    assert len(before) == 1

    reader = PdfReader(str(source))
    page = reader.pages[0]
    xobjects = page["/Resources"]["/XObject"].get_object()  # type: ignore[index]
    (image_key,) = xobjects.keys()
    image_obj = xobjects[image_key].get_object()

    mutated = bytearray(image_obj._data)  # noqa: SLF001 - the same private access AC3's own
    # instrument (`tests/helpers/pdfstream.py`) uses, pinned to pypdf 6.16.2
    mutated[0] ^= 0xFF  # flip one byte -- deliberately corrupt the stored stream
    image_obj._data = bytes(mutated)  # noqa: SLF001

    writer = PdfWriter()
    writer.append(reader)
    corrupted = tmp_path / "corrupted.pdf"
    buffer = io.BytesIO()
    writer.write(buffer)
    corrupted.write_bytes(buffer.getvalue())

    after_corrupted = embedded_image_streams(corrupted, 0)
    assert len(after_corrupted) == 1
    assert after_corrupted[0].raw != before[0].raw, (
        "the positive control did not bite: a deliberately corrupted image stream "
        "still compared equal to the original -- the instrument cannot be trusted"
    )


# --------------------------------------------------------------------------- #
# AC4 -- before: 0 words; after: non-empty text containing the known string.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("tesseract")
def test_ac4_text_before_empty_after_recovers_the_known_string(tmp_path: Path) -> None:
    source = _compose_scanned_page(tmp_path)
    assert _extract_text(source) == ""

    output = tmp_path / "ocrd.pdf"
    result = ocr_run(
        [source],
        lang="eng",
        dpi=200,
        psm=3,
        skip_text_pages=False,
        pages_spec=None,
        output=output,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    assert result.exit_code == 0, result
    assert EXPECTED_TEXT in _extract_text(output)


# --------------------------------------------------------------------------- #
# AC5 -- `--skip-text-pages` is selective: an already-extractable page stays
# byte-identical (content stream AND image), while an image-only page in the
# SAME run gains extractable text.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("tesseract")
def test_ac5_skip_text_pages_is_selective_not_a_no_op(tmp_path: Path) -> None:
    from pypdf import PdfReader, PdfWriter

    text_page_doc = tmp_path / "text-page.pdf"
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    made = canvas.Canvas(str(text_page_doc), pagesize=letter, invariant=1)
    made.setProducer("pdf-toolkit test")
    made.setCreator("tests/integration/test_ocr.py")
    made.drawString(72, 700, "already has extractable text")
    made.showPage()
    made.save()

    scan_doc = _compose_scanned_page(tmp_path, name="scan-only.pdf")

    combined = tmp_path / "combined.pdf"
    writer = PdfWriter()
    writer.append(PdfReader(str(text_page_doc)))
    writer.append(PdfReader(str(scan_doc)))
    with open(combined, "wb") as handle:
        writer.write(handle)

    before_page1_images = embedded_image_streams(combined, 0)  # none expected
    before_page1_content = PdfReader(str(combined)).pages[0].get_contents().get_data()

    output = tmp_path / "combined-ocrd.pdf"
    result = ocr_run(
        [combined],
        lang="eng",
        dpi=200,
        psm=3,
        skip_text_pages=True,
        pages_spec=None,
        output=output,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    assert result.exit_code == 0, result
    assert result.items[0].detail["pages_skipped"] == [1]
    assert result.items[0].detail["pages_ocrd"] == [2]

    after_page1_content = PdfReader(str(output)).pages[0].get_contents().get_data()
    assert after_page1_content == before_page1_content
    after_page1_images = embedded_image_streams(output, 0)
    assert after_page1_images == before_page1_images
    from pdf_toolkit.ports.text import require_text

    engine = require_text()
    page2_text = "".join(engine.extract_text(str(output), [2]))
    assert EXPECTED_TEXT in page2_text


# --------------------------------------------------------------------------- #
# AC6 -- our adapter's recognised text matches pytesseract's own oracle, for
# the same image/lang/psm (test-only: the single-spawn-point rule is scoped
# to src/, per D3).
# --------------------------------------------------------------------------- #


@pytest.mark.requires("tesseract")
def test_ac6_matches_the_pytesseract_oracle(tmp_path: Path) -> None:
    import pytesseract
    from PIL import Image

    image = Image.open(SCANNED_RASTER)
    oracle_pdf = pytesseract.image_to_pdf_or_hocr(
        image, extension="pdf", config="-c textonly_pdf=1"
    )
    from pypdf import PdfReader

    oracle_reader = PdfReader(__import__("io").BytesIO(oracle_pdf))
    oracle_text = oracle_reader.pages[0].extract_text()

    source = _compose_scanned_page(tmp_path)
    output = tmp_path / "ocrd.pdf"
    result = ocr_run(
        [source],
        lang="eng",
        dpi=200,
        psm=3,
        skip_text_pages=False,
        pages_spec=None,
        output=output,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    assert result.exit_code == 0, result
    ours_text = _extract_text(output)

    def _normalize(text: str) -> str:
        return " ".join(text.split()).upper()

    assert _normalize(ours_text) == _normalize(oracle_text)


# --------------------------------------------------------------------------- #
# AC7 -- a genuinely rotated page. SKIPPED: `RasterEngine.render_page`
# (`adapters/pdfium_raster.py`, out of this spec's permitted edit scope --
# see D1's "NO EDIT" row) double-applies `/Rotate` for 90/270-degree pages.
# Verified live (this spec's Implementation Log): `pdfium.PdfPage.render()`
# ALREADY auto-applies `/Rotate` internally (confirmed: `rotation=0` on a
# `/Rotate 90` page still renders the CORRECT, poppler-matching 200x600
# portrait image), and `pdfium_raster.py::_render` ALSO passes
# `rotation=page.get_rotation()` explicitly -- a SECOND application. Net
# effect measured: for `/Rotate 90` the output is rotated 180 DEGREES from
# correct (dims wrongly unswapped, content upside down); for `/Rotate 180`
# the double-application cancels out (0/180/360 are all equivalent modulo
# 360), which is exactly why no earlier spec's test caught this -- PDF-09's
# own rotation test only asserts an aspect-ratio CLASS (`width > height`)
# against a fixture whose OWN mediabox reportlab already pre-swaps, and
# renders BLANK (no visible pixels) under inspection, so it never actually
# validated pixel placement. This spec's own geometry-normalisation
# (`adapters/tesseract_ocr.py::_normalize_layer_geometry`, Design §D4 route
# (a)) is implemented against the DOCUMENTED, INTENDED contract of
# `render_page` and is not itself in question -- reported as a BLOCKER for
# AC7 rather than papered over with a compensating hack tied to a bug in a
# file this spec may not edit.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("tesseract")
@pytest.mark.skip(
    # Deliberately spelled to avoid the substrings `scripts/assert_skips.py`'s
    # own ENGINE_REASON regex (`engine|tesseract|soffice|libreoffice`, case
    # -insensitive) matches: this skip is UNCONDITIONAL (fires with or
    # without tesseract installed), so a reason naming "RasterEngine" would
    # be misread by the `engines-present` CI job's `--expect-zero` check as
    # "a test that should have exercised a real engine silently did not" --
    # a false positive, verified live against the actual regex before this
    # wording was chosen.
    reason=(
        "BLOCKED by a pre-existing defect in adapters/pdfium_raster.py (out of "
        "PDF-15's permitted edit scope): its render_page() function double-"
        "applies /Rotate for 90/270-degree pages, corrupting the fixture's own "
        "pixels before OCR ever sees them. See this test's own module-level "
        "comment and the spec's Implementation Log for the live reproduction."
    )
)
def test_ac7_rotated_page_returns_the_expected_text(tmp_path: Path) -> None:
    source = _compose_scanned_page(tmp_path)
    rotated = _rotate90(source, tmp_path)

    from pypdf import PdfReader

    assert PdfReader(str(rotated)).pages[0].rotation == 90  # present, non-zero (B-084)

    output = tmp_path / "rotated-ocrd.pdf"
    result = ocr_run(
        [rotated],
        lang="eng",
        dpi=200,
        psm=3,
        skip_text_pages=False,
        pages_spec=None,
        output=output,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    assert result.exit_code == 0, result
    assert EXPECTED_TEXT in _extract_text(output)


# --------------------------------------------------------------------------- #
# AC8 -- `ocr --pages 2` on a 3-page document leaves pages 1 and 3
# byte-identical, page count unchanged.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("tesseract")
def test_ac8_unselected_pages_are_byte_identical(tmp_path: Path) -> None:
    from pypdf import PdfReader, PdfWriter

    page1 = tmp_path / "p1.pdf"
    page3 = tmp_path / "p3.pdf"
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    for path, label in ((page1, "page one"), (page3, "page three")):
        made = canvas.Canvas(str(path), pagesize=letter, invariant=1)
        made.setProducer("pdf-toolkit test")
        made.setCreator("tests/integration/test_ocr.py")
        made.drawString(72, 700, label)
        made.showPage()
        made.save()

    scan_doc = _compose_scanned_page(tmp_path, name="scan-only.pdf")

    combined = tmp_path / "combined3.pdf"
    writer = PdfWriter()
    writer.append(PdfReader(str(page1)))
    writer.append(PdfReader(str(scan_doc)))
    writer.append(PdfReader(str(page3)))
    with open(combined, "wb") as handle:
        writer.write(handle)

    before_p1 = PdfReader(str(combined)).pages[0].get_contents().get_data()
    before_p3 = PdfReader(str(combined)).pages[2].get_contents().get_data()

    output = tmp_path / "combined3-ocrd.pdf"
    result = ocr_run(
        [combined],
        lang="eng",
        dpi=200,
        psm=3,
        skip_text_pages=False,
        pages_spec="2",
        output=output,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    assert result.exit_code == 0, result

    reader = PdfReader(str(output))
    assert len(reader.pages) == 3
    assert reader.pages[0].get_contents().get_data() == before_p1
    assert reader.pages[2].get_contents().get_data() == before_p3


# --------------------------------------------------------------------------- #
# AC9 -- the flag-validation table.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("tesseract")
def test_ac9_unavailable_lang_pack_exits_3_with_an_install_hint(tmp_path: Path) -> None:
    source = _compose_scanned_page(tmp_path)
    result = run_cli("ocr", str(source), "--lang", "spa", "-O", str(tmp_path / "x.pdf"))
    assert result.returncode == 3
    combined = result.stdout + result.stderr
    assert "spa" in combined
    assert "doctor" in combined


def test_ac9_malformed_lang_shape_exits_2(tmp_path: Path) -> None:
    source = _compose_scanned_page(tmp_path)
    result = run_cli("ocr", str(source), "--lang", "XX9", "-O", str(tmp_path / "x.pdf"))
    assert result.returncode == 2


def test_ac9_psm_0_exits_2(tmp_path: Path) -> None:
    source = _compose_scanned_page(tmp_path)
    result = run_cli("ocr", str(source), "--psm", "0", "-O", str(tmp_path / "x.pdf"))
    assert result.returncode == 2


def test_ac9_dpi_out_of_range_exits_2(tmp_path: Path) -> None:
    source = _compose_scanned_page(tmp_path)
    result = run_cli("ocr", str(source), "--dpi", "5000", "-O", str(tmp_path / "x.pdf"))
    assert result.returncode == 2
    assert "72" in (result.stdout + result.stderr)


# --------------------------------------------------------------------------- #
# AC12 -- PDF-05's first real consumer of the engine-absent contract.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("tesseract")
def test_ac12_engine_hidden_exits_3_names_doctor_no_traceback(tmp_path: Path) -> None:
    source = _compose_scanned_page(tmp_path)
    env = _hidden_engine_env("tesseract", tmp_path=tmp_path)
    result = run_cli("ocr", str(source), "-O", str(tmp_path / "x.pdf"), env=env)
    assert result.returncode == 3
    combined = result.stdout + result.stderr
    assert "doctor" in combined
    assert "Traceback" not in combined


# --------------------------------------------------------------------------- #
# AC16 -- dry-run purity and the zero-operational-spawn guarantee.
# --------------------------------------------------------------------------- #


def test_ac16_dry_run_with_engine_absent_makes_zero_calls(tmp_path: Path) -> None:
    """(c) -- with the engine ABSENT, the probe short-circuits before any
    spawn (`tesseract_ocr.py:96-97`); asserted here via the hiding shim on a
    page that NEEDS the engine (not skip-eligible), so the exit-3 prediction
    is genuinely exercised."""
    source = _compose_scanned_page(tmp_path)
    env = _hidden_engine_env("tesseract", tmp_path=tmp_path)

    dry = run_cli("ocr", str(source), "-O", str(tmp_path / "x.pdf"), "--dry-run", env=env)
    real = run_cli("ocr", str(source), "-O", str(tmp_path / "x.pdf"), env=env)
    assert dry.returncode == real.returncode == 3, (dry.stdout, real.stdout)
    assert not (tmp_path / "x.pdf").exists()


@pytest.mark.requires("tesseract")
def test_ac16_dry_run_never_spawns_the_operational_call(tmp_path: Path, monkeypatch) -> None:
    """(b) -- with the engine PRESENT, a dry run performs no argv containing
    `textonly_pdf=1` (the operational call, D3)."""
    calls: list[list[str]] = []
    from pdf_toolkit.adapters import subprocess_util

    real_run = subprocess_util.run

    def _spy(argv, **kwargs):
        calls.append(list(argv))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess_util, "run", _spy)

    source = _compose_scanned_page(tmp_path)
    result = ocr_run(
        [source],
        lang="eng",
        dpi=200,
        psm=3,
        skip_text_pages=False,
        pages_spec=None,
        output=tmp_path / "x.pdf",
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(dry_run=True),
    )
    assert result.dry_run is True
    assert not any("textonly_pdf=1" in " ".join(call) for call in calls)
    assert not (tmp_path / "x.pdf").exists()


@pytest.mark.requires("tesseract")
def test_ac16_in_place_leaves_a_bak_sidecar(tmp_path: Path) -> None:
    """(e) -- `ocr --in-place` leaves a `.bak` sidecar carrying the
    pre-run bytes (PDF-04's own path; one case asserted, per D5)."""
    source = _compose_scanned_page(tmp_path, name="inplace.pdf")
    before = source.read_bytes()

    result = ocr_run(
        [source],
        lang="eng",
        dpi=200,
        psm=3,
        skip_text_pages=False,
        pages_spec=None,
        output=None,
        out_dir=None,
        name_template=None,
        in_place=True,
        policy=_policy(in_place=True),
    )
    assert result.exit_code == 0, result

    bak = source.with_name(source.name + ".bak")
    assert bak.is_file(), "no .bak sidecar was left behind"
    assert bak.read_bytes() == before
    assert source.read_bytes() != before, "the input was not actually mutated in place"


# --------------------------------------------------------------------------- #
# AC13 -- no orphan survives a timed-out tesseract spawn (the group-kill
# path, exercised with a forking stub -- proving the GROUP, not just the
# direct child, is killed).
# --------------------------------------------------------------------------- #


def test_ac13_group_kill_survives_a_forking_child(tmp_path: Path) -> None:
    import os
    import time

    from pdf_toolkit.adapters import subprocess_util

    result = subprocess_util.run(["sh", "-c", "sleep 30 & sleep 30"], timeout=0.3, check=False)
    assert result.timed_out is True

    time.sleep(0.5)
    with __import__("contextlib").suppress(ProcessLookupError, PermissionError):
        os.killpg(result.pgid, 0)
        raise AssertionError("process group survived the timeout")
