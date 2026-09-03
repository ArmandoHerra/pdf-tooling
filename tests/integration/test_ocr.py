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

from helpers.engine_hiding import hidden_engine_env  # noqa: E402
from helpers.pdfstream import embedded_image_streams  # noqa: E402
from pdf_toolkit.ops.compose import compose_document, parse_page_size  # noqa: E402
from pdf_toolkit.ops.ocr import ocr_run  # noqa: E402
from pdf_toolkit.ops.pages import rotate_run  # noqa: E402
from pdf_toolkit.safety.policy import SafetyPolicy  # noqa: E402
from pdfium_text import page_text  # noqa: E402
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


def _rotate(source: Path, tmp_path: Path, angle: int, *, name: str | None = None) -> Path:
    output = tmp_path / (name or f"rotated-{angle}.pdf")
    result = rotate_run(
        [source],
        pages_spec="1",
        angle=angle,
        absolute=False,
        output=output,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    assert result.exit_code == 0, result
    return output


def _rotate90(source: Path, tmp_path: Path, *, name: str = "rotated.pdf") -> Path:
    return _rotate(source, tmp_path, 90, name=name)


def _collapse_whitespace(text: str) -> str:
    """The comparison AC6 and AC10 already use in this suite.

    It matters on a rotated page and nowhere else: `pdftoolkit text`'s engine
    groups characters into lines in the page's DISPLAYED frame, so a text
    layer that is correct in the page's own unrotated space -- which is the
    only place it can be correct, since that is where the glyphs it was read
    from live -- comes back with the words separated by newlines rather than
    spaces. That is a property of the extractor, not of the layer, and
    `test_b094_the_rotated_layer_is_upright_and_aligned` proves it with a
    control rather than asserting it here.
    """
    return " ".join(text.split())


def _layer_word_boxes(path: Path) -> list[tuple[float, float, float, float]]:
    """Every text rect on page 1, in the page's own unrotated coordinates.

    pypdfium2 directly, for the same reason `tests/pdfium_text.py` exists: this
    reads back geometry the product does not expose through any verb, and it is
    a SECOND engine-level view of the layer -- independent of the `TextEngine`
    the assertions above go through.
    """
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    try:
        page = document.get_page(0)
        try:
            textpage = page.get_textpage()
            try:
                return [textpage.get_rect(index) for index in range(textpage.count_rects())]
            finally:
                textpage.close()
        finally:
            page.close()
    finally:
        document.close()


def _extract_text(path: Path) -> str:
    from pdf_toolkit.ports.text import require_text

    engine = require_text()
    return "".join(engine.extract_text(str(path), [1]))


def _hidden_engine_env(hidden: str, *, tmp_path: Path) -> dict[str, str]:
    """A PATH excluding *hidden*'s real binary, for a SUBPROCESS test.

    The mechanism moved to `tests/helpers/engine_hiding.py` (B-096) once the
    OR-7 `dry == real` mirror -- a CROSS-VERB contract covering both
    system-binary verbs -- needed the same hiding from its own module. This
    thin delegate keeps this module's existing call sites (AC12/AC16) reading
    exactly as before; see that helper's docstring for why hiding must mean
    `shutil.which` -> `None` and never a shadowing shim.
    """
    return hidden_engine_env(hidden, tmp_path=tmp_path)


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
# AC7 -- a genuinely rotated page. UNSKIPPED by B-094.
#
# This test shipped under an unconditional `@pytest.mark.skip` because
# `adapters/pdfium_raster.py` (a PDF-09 file, outside PDF-15's edit scope)
# applied the page's own `/Rotate` a SECOND time on top of pdfium's internal
# one, corrupting the fixture's pixels before OCR ever saw them. B-094 fixed
# that adapter; the skip is gone and the marker is now the ordinary
# `requires("tesseract")` gate every other arm in this module carries, so the
# test RUNS with engines present and skips VISIBLY without them -- which is
# also what puts it back on the right side of `scripts/assert_skips.py` in
# both CI configurations (see that script's `--expect-zero` mode).
#
# The geometry the skip was blocking on is proven separately and with a
# control by `test_b094_the_rotated_layer_is_upright_and_aligned` below. This
# test stays exactly what AC7 says: OCR a `/Rotate 90` page, get the text back
# through the product's own text engine.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("tesseract")
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
    assert EXPECTED_TEXT in _collapse_whitespace(_extract_text(output))


# --------------------------------------------------------------------------- #
# B-094 -- the text layer on a rotated page is UPRIGHT and ALIGNED.
#
# AC7 above proves the letters come back. This proves they came back because
# the geometry is right and not by luck, and it is the assertion that would
# survive a future extractor changing how it groups lines.
#
# The oracle is the layer produced from the SAME page without the rotation:
# `/Rotate` changes nothing about where the glyphs physically sit in the
# page's own coordinate space, so the OCR layer for the rotated page must land
# in the same boxes as the layer for the unrotated one. Anything else is
# misalignment -- and the pre-B-094 render put it 180 degrees out.
#
# The same test carries the control for AC7's whitespace normalisation:
# stamping `/Rotate 90` onto the ALREADY-OCR'd unrotated file changes nothing
# but one dictionary key, and the product's text engine starts separating the
# words with newlines there too. So the separator is the extractor's doing,
# not the layer's, and normalising it is a measurement rather than a
# concession.
# --------------------------------------------------------------------------- #


def test_b094_the_quarter_turn_matrix_is_exact_not_trigonometric() -> None:
    """No engine, no tesseract -- pure matrix arithmetic (B-094).

    The zeros must be EXACTLY 0.0. `pypdf.Transformation.rotate(90)` yields
    `6.123233995736766e-17` there instead, and `pdfplumber` reads that residue
    as "this character is not upright", which changes what `pdftoolkit text`
    returns for a rotated page. This guard is what stops a future edit from
    reverting to `Transformation.rotate()` for the readable-looking reason.
    """
    from pdf_toolkit.adapters.tesseract_ocr import _quarter_turn

    identity = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    assert _quarter_turn(identity, 90) == (0.0, 1.0, -1.0, 0.0, 0.0, 0.0)
    assert _quarter_turn(identity, 180) == (-1.0, -0.0, -0.0, -1.0, -0.0, -0.0)
    assert _quarter_turn(identity, 270) == (0.0, -1.0, 1.0, 0.0, 0.0, 0.0)
    assert _quarter_turn(identity, 0) == identity

    # Same composition order as the function it replaces, so it is a drop-in.
    from pypdf import Transformation

    for degrees in (90, 180, 270):
        reference = Transformation(identity).rotate(degrees).ctm
        exact = _quarter_turn(identity, degrees)
        for want, got in zip(reference, exact, strict=True):
            assert abs(want - got) < 1e-9, (degrees, reference, exact)
        # ... and strictly better: the reference is NOT exact.
        assert any(entry not in (-1.0, 0.0, 1.0) for entry in reference), degrees
        assert all(entry in (-1.0, -0.0, 0.0, 1.0) for entry in exact), degrees


@pytest.mark.requires("tesseract")
def test_b094_the_rotated_layer_is_upright_and_aligned(tmp_path: Path) -> None:
    from pypdf import PdfReader, PdfWriter

    source = _compose_scanned_page(tmp_path)

    upright_out = tmp_path / "upright-ocrd.pdf"
    assert (
        ocr_run(
            [source],
            lang="eng",
            dpi=200,
            psm=3,
            skip_text_pages=False,
            pages_spec=None,
            output=upright_out,
            out_dir=None,
            name_template=None,
            in_place=False,
            policy=_policy(),
        ).exit_code
        == 0
    )

    rotated = _rotate90(source, tmp_path)
    rotated_out = tmp_path / "rotated-ocrd.pdf"
    assert (
        ocr_run(
            [rotated],
            lang="eng",
            dpi=200,
            psm=3,
            skip_text_pages=False,
            pages_spec=None,
            output=rotated_out,
            out_dir=None,
            name_template=None,
            in_place=False,
            policy=_policy(),
        ).exit_code
        == 0
    )

    # (1) ALIGNED -- same words, same boxes, in the page's own space.
    upright_boxes = _layer_word_boxes(upright_out)
    rotated_boxes = _layer_word_boxes(rotated_out)
    assert len(upright_boxes) == len(rotated_boxes) > 0
    for index, (expected, actual) in enumerate(zip(upright_boxes, rotated_boxes, strict=True)):
        for axis, (want, got) in enumerate(zip(expected, actual, strict=True)):
            assert abs(want - got) < 0.5, (index, axis, expected, actual)

    # (2) UPRIGHT -- read back through a second, independent engine view, the
    # rotated page's layer spells the fixture's string with its spaces intact.
    # (The pre-fix render produced upside-down nonsense here, not a spacing
    # difference.)
    assert EXPECTED_TEXT in page_text(rotated_out, 1)

    # (3) The control for AC7's whitespace normalisation: take the KNOWN-GOOD
    # unrotated layer, change nothing but `/Rotate`, and the product's own text
    # engine regroups the words the same way.
    reader = PdfReader(str(upright_out))
    writer = PdfWriter()
    stamped_page = reader.pages[0]
    stamped_page.rotation = 90
    writer.add_page(stamped_page)
    stamped = tmp_path / "upright-ocrd-then-stamped.pdf"
    with open(stamped, "wb") as handle:
        writer.write(handle)

    stamped_text = _extract_text(stamped)
    assert EXPECTED_TEXT not in stamped_text  # the newlines are the extractor's
    assert EXPECTED_TEXT in _collapse_whitespace(stamped_text)


# --------------------------------------------------------------------------- #
# B-094 -- the real-world rotated scan: sideways pixels that `/Rotate` puts
# upright. This is the shape a scanner actually produces, and it is the one
# where a render that ignores (or double-applies) `/Rotate` is unambiguously
# fatal: OCR sees a sideways page and returns nothing usable.
#
# Both 90 and 270 are covered because they are the only two angles the defect
# could distinguish -- and because `_rotate90`'s fixture alone leaves 270
# untested, which is how a half-fixed rotation would slip through.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("tesseract")
@pytest.mark.parametrize("rotation", [90, 270])
def test_b094_a_sideways_scan_that_rotate_makes_upright_is_readable(
    tmp_path: Path, rotation: int
) -> None:
    from PIL import Image
    from pypdf import PdfReader

    # Lay the pixels down sideways so that applying `/Rotate` DISPLAYS them
    # upright: `/Rotate` turns the page clockwise, so the raw content must be
    # pre-turned by the same amount counter-clockwise.
    sideways_png = tmp_path / f"sideways-{rotation}.png"
    with Image.open(SCANNED_RASTER) as scan:
        scan.rotate(rotation, expand=True).save(sideways_png)

    page = tmp_path / f"sideways-{rotation}.pdf"
    composed = compose_document(
        [sideways_png],
        output=page,
        page=parse_page_size("from-image"),
        fit="contain",
        margin_pt=0.0,
        dpi=None,
        policy=_policy(),
    )
    assert composed.exit_code == 0, composed
    rotated = _rotate(page, tmp_path, rotation)
    assert PdfReader(str(rotated)).pages[0].rotation == rotation

    output = tmp_path / f"sideways-{rotation}-ocrd.pdf"
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
    assert _extract_text(rotated) == ""  # the honest before-state: image only
    assert EXPECTED_TEXT in _collapse_whitespace(_extract_text(output))
    # And through the second, independent engine view -- spaces intact, which
    # is the shape a page that genuinely DISPLAYS upright must produce.
    assert EXPECTED_TEXT in page_text(output, 1)


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


# --------------------------------------------------------------------------- #
# PDF-23 AC3 -- `ocr` is the third consumer, and the reason B-092 asked for
# one spec covering all three. `4adc417234`'s own observation, reproduced:
# pre-fix, `ocr --pages 2` on the shared-`/Contents` fixture reported
# `pages_ocrd: [2]` while all THREE pages gained the text layer.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("tesseract")
def test_pdf23_ac3_ocr_scopes_to_selection_on_shared_contents(corpus, tmp_path: Path) -> None:
    import sys as _sys

    tests_dir = Path(__file__).resolve().parents[1]
    if str(tests_dir) not in _sys.path:  # pragma: no cover - import plumbing
        _sys.path.insert(0, str(tests_dir))
    from corpus import changed_pages

    source = corpus.path("shared_contents_pages")
    target = tmp_path / "ocrd.pdf"
    result = ocr_run(
        [source],
        lang="eng",
        dpi=200,
        psm=3,
        skip_text_pages=False,
        pages_spec="2",
        output=target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    assert result.exit_code == 0, result
    item = result.items[0]
    assert item.detail["pages_ocrd"] == [2]

    changed = changed_pages(source, target)
    assert changed == frozenset({2}), (
        f"ocr changed {sorted(changed)}, not exactly {{2}} -- 4adc417234's own defect"
    )


# --------------------------------------------------------------------------- #
# PDF-23 AC12 -- `ocr`'s own `composite_layer` call contributes ZERO pypdf
# deprecation warnings, but the RUN as a whole does not read zero, and this
# test says why rather than silently asserting a wrong number.
#
# MEASURED, not assumed, and it corrects this spec's own Design §D6:
# `adapters/tesseract_ocr.py::_normalize_layer_geometry` calls
# `page.add_transformation(...)` on `reader.pages[0]` -- a page from a FRESH
# `PdfReader`, still UNATTACHED to any writer at that point (the
# `PdfWriter().add_page(page)` call happens AFTER, not before). §D6 claims
# this call site "carries no deprecation... writer-attached by
# construction" -- that claim is wrong, verified by a `-W error` traceback
# that resolves entirely inside `_normalize_layer_geometry`, never inside
# `composite_layer`. This call site is `PDF-15`'s (`ocr`'s geometry
# normalization, D6/Scope > Out) and is NOT touched by this spec.
#
# The bound asserted here is `<= 1 per OCR'd page`, not `== 0`: this proves
# `composite_layer`'s own contribution is zero (a regression there would
# push the count to 2-per-page) without falsely claiming the whole `ocr`
# pipeline is deprecation-free, which it is not and this spec does not
# promise.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("tesseract")
def test_pdf23_ac12_composite_layer_itself_adds_no_deprecation_to_ocr(
    corpus, tmp_path: Path
) -> None:
    import warnings

    source = corpus.path("shared_contents_pages")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = ocr_run(
            [source],
            lang="eng",
            dpi=200,
            psm=3,
            skip_text_pages=False,
            pages_spec="2",
            output=tmp_path / "ocrd-ac12.pdf",
            out_dir=None,
            name_template=None,
            in_place=False,
            policy=_policy(),
        )
    assert result.exit_code == 0, result
    pypdf_deprecations = [
        item
        for item in caught
        if issubclass(item.category, DeprecationWarning) and "pypdf" in (item.filename or "")
    ]
    # One page selected -- at most ONE residual warning (`_normalize_layer_
    # geometry`'s own, out of this spec's scope), never two (which would
    # mean `composite_layer` itself regressed).
    assert len(pypdf_deprecations) <= 1, (
        f"{len(pypdf_deprecations)} pypdf DeprecationWarning(s) for one OCR'd page -- "
        f"composite_layer's own migration may have regressed: "
        f"{[str(item.message) for item in pypdf_deprecations]}"
    )
