"""The `samples` fixture's own self-tests, and the home for every later
spec's `@samples` arm — `PLAN.md` §10.1, Design §10.

**This file is append-only across nine specs** (`PDF-07`…`PDF-15`). Each adds
exactly ONE section below this module's own PDF-06 section, in a delimited
block naming its own spec ID, and never edits another spec's section.
`decision.md` §2's execution rule (one engineer at a time in
`apps/pdf-toolkit`) is what makes an append-only shared file safe; the cycle
close audits it with `git log -p -- tests/test_samples.py`, never a grep at
HEAD (append-only shared files are not contention-free —
`expertise/product.yaml`, 2026-08-22).

Rules for every `@samples` arm, restated from Design §10 so a later engineer
does not have to re-derive them:

- Uses `samples.copy()` / `samples.copy_tree()` and nothing else. Never a
  path constructed from `$PDF_TOOLKIT_SAMPLES_DIR` directly.
- Asserts **structural** facts only — page counts, sizes, hashes,
  dimensions. **Never a content string extracted from a sample** (rule 4).
- Produces no golden file. Goldens are built from the generated corpus only.
- Privacy (rule 4) binds this file exactly as it binds `changelog.md`,
  `TESTING.md` and every Implementation Log: filename, page count, size and
  hash only — nothing else about any document's content.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# PDF-06 -- the fixture's own contract (AC15, AC18-adjacent)
# --------------------------------------------------------------------------- #


def test_ac15_fixture_exposes_exactly_four_public_members(samples) -> None:
    public = {name for name in dir(samples) if not name.startswith("_")}
    assert public == {"available", "names", "copy", "copy_tree"}


def test_ac15_available_and_names_never_leak_a_path(samples) -> None:
    """The zero-argument surface can never resolve under the originals root:
    `available` is a bool, `names()` is bare filenames with no separator."""
    assert isinstance(samples.available, bool)
    for name in samples.names():
        assert os.sep not in name
        assert "/" not in name
        assert not name.startswith((str(Path.home()), "/"))


def test_ac15_copy_and_copy_tree_are_argument_taking_methods() -> None:
    """Neither is a zero-argument property that could hand back a path
    directly -- both require a `name` and route through `_resolve()`, which
    is the fixture's one and only originals-root read site."""
    import inspect

    import conftest

    signature_copy = inspect.signature(conftest.Samples.copy)
    signature_copy_tree = inspect.signature(conftest.Samples.copy_tree)
    assert "name" in signature_copy.parameters
    assert "name" in signature_copy_tree.parameters


@pytest.mark.samples
def test_an_unknown_name_fails_rather_than_skips(samples) -> None:
    """ "Sample present but misspelled" is a test bug, not corpus absence."""
    with pytest.raises(pytest.fail.Exception):
        samples.copy("this-name-does-not-exist-anywhere-in-the-corpus.pdf")


@pytest.mark.samples
def test_copy_or_copy_tree_returns_a_writable_path_inside_tmp_path(samples, tmp_path: Path) -> None:
    """Generic on purpose: picks whichever entry the operator's corpus
    happens to have first, rather than hardcoding one operator's filenames
    into PDF-06's own self-test (later specs' `@samples` arms are the place
    for a specific, named file -- Design §10's suggested-sample table)."""
    names = samples.names()
    assert names, "samples.available is True but names() is empty"

    result: Path | None = None
    for name in names:
        try:
            result = samples.copy(name)
        except pytest.fail.Exception:
            try:
                result = samples.copy_tree(name)
            except pytest.fail.Exception:
                continue
        break
    assert result is not None, f"neither copy() nor copy_tree() worked for any of {names}"
    assert result.exists()
    assert result.parent == tmp_path or tmp_path in result.parents
    assert os.access(result, os.W_OK), "the copy is not user-writable"


@pytest.mark.samples
def test_copy_never_hands_back_a_path_under_the_originals_root(samples, tmp_path: Path) -> None:
    root = os.environ.get("PDF_TOOLKIT_SAMPLES_DIR", "")
    name = samples.names()[0]
    try:
        result = samples.copy(name)
    except pytest.fail.Exception:
        result = samples.copy_tree(name)
    assert not str(result).startswith(root), "copy() returned a path under the originals root"
    assert tmp_path in result.parents or result.parent == tmp_path


# --------------------------------------------------------------------------- #
# Later specs append ONE section each below this line, in wave order. Do not
# edit another spec's section. Re-read this file at HEAD immediately before
# adding yours (Design §10; `decision.md` §2 execution rule).
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# PDF-07 -- AC22, the cycle's first @samples arm. Over a COPY of
# PrendiniLoria2020.pdf (originals are never an operand, HC-2 rule 1):
#   (a) the copy reports 482 pages
#   (b) split --ranges '1-100,101-200,201-482' writes three parts of
#       100/100/282, summing to 482
#   (c) merge 'copy.pdf:1-50,!25,400-,last' -O long.pdf yields 133 pages
#       (hand-derived: 50 - 1 + 83 + 1 under §4.3's left-to-right
#       union/exclusion semantics, duplicates preserved -- see AC22's own
#       text). If this count differs, that is a PDF-03 defect to report,
#       never a number to adjust.
# Nothing beyond filename, page count, size and hash is quoted anywhere in
# this section (HC-2 rule 4) -- no page text, no title, no metadata.
# --------------------------------------------------------------------------- #

_SAMPLE_NAME = "PrendiniLoria2020.pdf"
_SAMPLE_EXPECTED_PAGES = 482


@pytest.mark.samples
def test_ac22_sample_copy_reports_the_expected_page_count(samples) -> None:
    from pdf_toolkit.ports.structure import require_structure

    copy_path = samples.copy(_SAMPLE_NAME)
    engine = require_structure()
    with engine.open_document(copy_path) as document:
        assert document.page_count == _SAMPLE_EXPECTED_PAGES


@pytest.mark.samples
def test_ac22_split_ranges_over_a_482_page_sample(samples, tmp_path: Path) -> None:
    from pdf_toolkit.ops.split import split_document
    from pdf_toolkit.ports.structure import require_structure
    from pdf_toolkit.safety.policy import SafetyPolicy

    copy_path = samples.copy(_SAMPLE_NAME)
    out_dir = tmp_path / "parts"
    policy = SafetyPolicy(
        dry_run=False,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )
    result = split_document(
        copy_path,
        mode="ranges",
        every=None,
        ranges=("1-100,101-200,201-482",),
        name_template=None,
        out_dir=out_dir,
        policy=policy,
    )
    assert result.exit_code == 0
    names = sorted(p.name for p in out_dir.iterdir())
    assert len(names) == 3

    engine = require_structure()
    counts = []
    for name in names:
        with engine.open_document(out_dir / name) as document:
            counts.append(document.page_count)
    assert counts == [100, 100, 282]
    assert sum(counts) == _SAMPLE_EXPECTED_PAGES


@pytest.mark.samples
def test_ac22_merge_union_exclusion_over_a_482_page_sample(samples, tmp_path: Path) -> None:
    from pdf_toolkit.ops.merge import merge_documents, resolve_merge_inputs
    from pdf_toolkit.ports.structure import require_structure
    from pdf_toolkit.safety.policy import SafetyPolicy

    copy_path = samples.copy(_SAMPLE_NAME)
    output = tmp_path / "long.pdf"
    policy = SafetyPolicy(
        dry_run=False,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )
    inputs = resolve_merge_inputs((f"{copy_path}:1-50,!25,400-,last",))
    result = merge_documents(inputs, output=output, bookmarks="none", policy=policy)
    assert result.exit_code == 0

    engine = require_structure()
    with engine.open_document(output) as document:
        # Hand-derived per AC22: 50 - 1 + 83 + 1 == 133.
        assert document.page_count == 133


# --------------------------------------------------------------------------- #
# PDF-09 -- AC20. Over a COPY of 1888-10.pdf (originals are never an operand,
# HC-2 rule 1):
#   (a) page 1 at --dpi 72 renders 956x1435 px -- the page is 956x1435 pt
#       (E-5), and at 72 dpi one point is one pixel: no rounding ambiguity;
#   (b) AC3's identity check re-run at scale on real scans: --pages 1-12
#       --dpi 72 at --threads 1 and --threads 8, comparing per-file SHA-256
#       and the filename list.
# Nothing beyond filename, page count, size and hash is quoted anywhere in
# this section (HC-2 rule 4) -- no page text, no title, no metadata.
# --------------------------------------------------------------------------- #

_RASTER_SAMPLE_NAME = "1888-10.pdf"
_RASTER_SAMPLE_PAGE_1_DPI_72_SIZE = (956, 1435)


@pytest.mark.samples
def test_ac20_sample_page_1_at_72_dpi_renders_the_exact_point_pixel_size(
    samples, tmp_path: Path
) -> None:
    from PIL import Image

    from pdf_toolkit.ops.raster import rasterize_document
    from pdf_toolkit.safety.policy import SafetyPolicy

    copy_path = samples.copy(_RASTER_SAMPLE_NAME)
    out_dir = tmp_path / "page1"
    policy = SafetyPolicy(
        dry_run=False,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )
    result = rasterize_document(
        [copy_path],
        pages_spec="1",
        dpi=72.0,
        width_px=None,
        fmt="png",
        quality=None,
        grayscale=False,
        name_template=None,
        out_dir=out_dir,
        policy=policy,
    )
    assert result.exit_code == 0
    files = list(out_dir.iterdir())
    assert len(files) == 1
    with Image.open(files[0]) as img:
        assert img.size == _RASTER_SAMPLE_PAGE_1_DPI_72_SIZE


@pytest.mark.samples
def test_ac20_threads_1_and_threads_8_are_byte_identical_over_a_real_scan(
    samples, tmp_path: Path
) -> None:
    from pdf_toolkit.ops.raster import rasterize_document
    from pdf_toolkit.safety.policy import SafetyPolicy

    copy_path = samples.copy(_RASTER_SAMPLE_NAME)
    out1 = tmp_path / "t1"
    out8 = tmp_path / "t8"

    def _policy(threads: int) -> SafetyPolicy:
        return SafetyPolicy(
            dry_run=False,
            force=False,
            in_place=False,
            backup=True,
            assume_yes=False,
            is_tty=False,
            threads=threads,
        )

    result1 = rasterize_document(
        [copy_path],
        pages_spec="1-12",
        dpi=72.0,
        width_px=None,
        fmt="png",
        quality=None,
        grayscale=False,
        name_template=None,
        out_dir=out1,
        policy=_policy(1),
    )
    result8 = rasterize_document(
        [copy_path],
        pages_spec="1-12",
        dpi=72.0,
        width_px=None,
        fmt="png",
        quality=None,
        grayscale=False,
        name_template=None,
        out_dir=out8,
        policy=_policy(8),
    )
    assert result1.exit_code == 0
    assert result8.exit_code == 0

    names1 = sorted(p.name for p in out1.iterdir())
    names8 = sorted(p.name for p in out8.iterdir())
    assert names1 == names8
    assert len(names1) == 12
    for name in names1:
        assert (out1 / name).read_bytes() == (out8 / name).read_bytes(), name


# --------------------------------------------------------------------------- #
# PDF-10 -- AC18/AC28, the lossless proof against real scans. Over a COPY of
# the `1888-10/` directory (originals are never an operand, HC-2 rule 1):
#   (a) the copy holds 108 .jpg entries and nothing else;
#   (b) composing all 108 in sorted() filename order yields 108 pages;
#   (c) for EVERY page i, the stored stream is byte-identical to copied input
#       i, and every page's filter chain is exactly ('/DCTDecode',);
#   (d) corroborating only: the output is at least the sum of the input sizes.
# Nothing beyond filename, page count, size and hash is quoted anywhere in
# this section (HC-2 rule 4) -- no page content of any kind.
# --------------------------------------------------------------------------- #

_COMPOSE_SAMPLE_TREE = "1888-10"
_COMPOSE_SAMPLE_PAGES = 108


@pytest.mark.samples
def test_ac18_the_sample_tree_holds_exactly_the_expected_jpeg_count(samples) -> None:
    copied = samples.copy_tree(_COMPOSE_SAMPLE_TREE)
    entries = sorted(copied.iterdir())
    jpegs = [entry for entry in entries if entry.suffix.lower() == ".jpg"]
    assert len(jpegs) == _COMPOSE_SAMPLE_PAGES
    assert len(entries) == _COMPOSE_SAMPLE_PAGES, "the tree holds something other than the scans"


@pytest.mark.samples
def test_ac18_every_one_of_108_real_scans_is_stored_byte_for_byte(samples, tmp_path) -> None:
    import sys

    tests_dir = Path(__file__).resolve().parent
    if str(tests_dir) not in sys.path:  # pragma: no cover - import plumbing
        sys.path.insert(0, str(tests_dir))
    from helpers.pdfstream import embedded_image_streams
    from pdf_toolkit.ops.compose import compose_document, parse_page_size
    from pdf_toolkit.safety.policy import SafetyPolicy

    copied = samples.copy_tree(_COMPOSE_SAMPLE_TREE)
    # sorted() over fixed-width names is a total, deterministic order; the test
    # never relies on a shell glob or on filesystem order.
    scans = sorted(entry for entry in copied.iterdir() if entry.suffix.lower() == ".jpg")
    assert len(scans) == _COMPOSE_SAMPLE_PAGES

    output = tmp_path / "1888-10-recomposed.pdf"
    result = compose_document(
        scans,
        output=output,
        page=parse_page_size("from-image"),
        fit="contain",
        margin_pt=0.0,
        dpi=None,
        policy=SafetyPolicy(
            dry_run=False,
            force=False,
            in_place=False,
            backup=True,
            assume_yes=False,
            is_tty=False,
            threads=1,
        ),
    )
    assert result.exit_code == 0
    assert result.warnings == (), result.warnings

    from pypdf import PdfReader

    assert len(PdfReader(str(output)).pages) == _COMPOSE_SAMPLE_PAGES

    for index, scan in enumerate(scans):
        streams = embedded_image_streams(output, index)
        assert len(streams) == 1, f"page {index + 1} carries {len(streams)} images"
        assert streams[0].filters == ("/DCTDecode",), f"page {index + 1}: {streams[0].filters}"
        assert streams[0].dct_payload == scan.read_bytes(), (
            f"page {index + 1} ({scan.name}) is NOT the source bytes -- the tool re-encoded a scan"
        )

    # Corroborating, never the evidence: a document holding 108 originals
    # verbatim cannot be smaller than the originals.
    assert output.stat().st_size >= sum(scan.stat().st_size for scan in scans)


# --------------------------------------------------------------------------- #
# PDF-11 -- AC14/AC15, the honest-empty case. Over a COPY of 1888-10.pdf
# (originals are never an operand, HC-2 rule 1):
#   (a) `text` exits 0 and every one of the 108 page objects reports
#       char_count == 0 with empty text, on BOTH extraction paths;
#   (b) one `no extractable text` warning is emitted per empty page -- 108 of
#       them, not one summary line;
#   (c) `tables` on the same copy exits 0 with an empty table list and its own
#       per-page warning naming the strategy it used;
#   (d) AC15: `info --pages-detail` reports has_text false for every page while
#       `text` returns empty for every page -- the two surfaces AGREE. A
#       disagreement here is a finding reported to the PM, never a fix made to
#       `info` (PDF-05's surface) from inside this spec.
#
# This is the BEFORE state of another spec's proof: the later `ocr` verb's
# acceptance signal is "`text` returns non-empty text where it returned empty
# before". Anything that made this arm non-empty would silently invalidate it.
#
# Nothing beyond filename, page count, size and hash is quoted anywhere in this
# section (HC-2 rule 4) -- and asserting that a page's extracted text is EMPTY
# is a structural fact about the document, not a content string taken from it.
# --------------------------------------------------------------------------- #

_EMPTY_SAMPLE_NAME = "1888-10.pdf"
_EMPTY_SAMPLE_PAGES = 108


def _read_only_policy():
    from pdf_toolkit.safety.policy import SafetyPolicy

    return SafetyPolicy(
        dry_run=False,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )


@pytest.mark.samples
@pytest.mark.parametrize("layout", [False, True], ids=["fast", "layout"])
def test_ac14_every_page_of_an_image_only_scan_is_empty_and_exits_0(samples, layout: bool) -> None:
    from pdf_toolkit.ops.textract import extract_text_run

    copy_path = samples.copy(_EMPTY_SAMPLE_NAME)
    outcome = extract_text_run(
        [copy_path],
        pages_spec=None,
        layout=layout,
        output=None,
        out_dir=None,
        name_template=None,
        policy=_read_only_policy(),
    )

    assert outcome.result.exit_code == 0, "an empty-but-valid extraction is exit 0, never 1 or 4"
    assert outcome.strategy == ("layout" if layout else "fast")
    assert len(outcome.pages) == _EMPTY_SAMPLE_PAGES

    assert [page.char_count for page in outcome.pages] == [0] * _EMPTY_SAMPLE_PAGES
    assert {page.text for page in outcome.pages} == {""}
    if layout:
        assert {page.blocks for page in outcome.pages} == {()}
    else:
        assert {page.blocks for page in outcome.pages} == {None}

    # One warning per empty page, not one summary line for the document.
    warnings = outcome.result.warnings
    assert len(warnings) == _EMPTY_SAMPLE_PAGES
    assert all("no extractable text" in warning for warning in warnings)


@pytest.mark.samples
def test_ac14_tables_finds_nothing_on_an_image_only_scan_and_exits_0(samples) -> None:
    from pdf_toolkit.ops.textract import extract_tables_run

    copy_path = samples.copy(_EMPTY_SAMPLE_NAME)
    outcome = extract_tables_run(
        [copy_path],
        pages_spec=None,
        strategy="lines",
        fmt=None,
        output=None,
        out_dir=None,
        name_template=None,
        policy=_read_only_policy(),
    )

    assert outcome.result.exit_code == 0, "zero tables is a legitimate answer, not an error"
    assert outcome.tables == ()
    warnings = outcome.result.warnings
    assert len(warnings) == _EMPTY_SAMPLE_PAGES
    assert all("no tables detected" in warning for warning in warnings)
    assert all("heuristic" in warning for warning in warnings)
    assert all("'lines'" in warning for warning in warnings)


@pytest.mark.samples
def test_ac15_info_has_text_and_text_emptiness_agree_on_the_same_copy(samples) -> None:
    """AC15. `info --pages-detail` says has_text false for every page; `text`
    returns empty for every page. If these ever disagree it is a FINDING for the
    PM about PDF-05's surface, not something this spec fixes."""
    from pdf_toolkit.cli.cmd_info import build_payload
    from pdf_toolkit.ops.textract import extract_text_run

    copy_path = samples.copy(_EMPTY_SAMPLE_NAME)

    payload, _outcomes = build_payload((copy_path,), fonts=False, pages_detail=True, dry_run=False)
    pages_detail = payload["documents"][0]["pages"]
    assert len(pages_detail) == _EMPTY_SAMPLE_PAGES
    info_has_text = {page["number"]: bool(page["has_text"]) for page in pages_detail}

    outcome = extract_text_run(
        [copy_path],
        pages_spec=None,
        layout=False,
        output=None,
        out_dir=None,
        name_template=None,
        policy=_read_only_policy(),
    )
    text_has_text = {page.page: page.char_count > 0 for page in outcome.pages}

    assert info_has_text == text_has_text, (
        "info --pages-detail's has_text and text's emptiness disagree -- report this to "
        "the PM as a finding about PDF-05's surface; do not adjust either side here"
    )
    assert set(info_has_text.values()) == {False}


# --------------------------------------------------------------------------- #
# PDF-12 -- AC16. Over COPIES of PrendiniLoria2020.pdf (482 pages) and
# catalogo_arquitectura_2017_2023_0.pdf (14 pages) -- originals are never an
# operand, HC-2 rule 1:
#   (a) on PrendiniLoria2020.pdf -- `compress --lossless` reduces size, page
#       count unchanged, per-page extracted text byte-identical;
#   (b) on catalogo_arquitectura_2017_2023_0.pdf -- `--images downsample
#       --image-dpi 150` does not produce an output LARGER than the
#       lossless-only output of the same input, page count and text
#       unchanged (this real document's own embedded images happen to sit at
#       or under the page-box DPI-150 threshold already -- D-12.2's own
#       stated, conservative limitation -- so `images_transformed` is
#       legitimately 0 here; the stronger, deterministic proof that
#       downsampling itself shrinks a wide image lives in
#       `tests/unit/test_optimize.py::test_ac5_downsample_is_strictly_smaller_than_lossless_only`
#       against a local, engineered fixture built specifically to cross that
#       threshold);
#   (c) on PrendiniLoria2020.pdf -- `linearize` yields `is_linearized is True`.
# Nothing beyond filename, page count, size and hash is quoted anywhere in
# this section (HC-2 rule 4) -- no page text, no title, no metadata.
# --------------------------------------------------------------------------- #

_OPTIMIZE_SAMPLE_NAME = "PrendiniLoria2020.pdf"
_OPTIMIZE_SAMPLE_PAGES = 482
_IMAGE_SAMPLE_NAME = "catalogo_arquitectura_2017_2023_0.pdf"
_IMAGE_SAMPLE_PAGES = 14


@pytest.mark.samples
def test_ac16_lossless_shrinks_and_preserves_text_over_a_482_page_sample(
    samples, tmp_path: Path
) -> None:
    import sys

    tests_dir = Path(__file__).resolve().parent
    if str(tests_dir) not in sys.path:  # pragma: no cover - import plumbing
        sys.path.insert(0, str(tests_dir))
    from pdf_toolkit.ops.optimize import compress_run
    from pdfium_text import page_texts

    copy_path = samples.copy(_OPTIMIZE_SAMPLE_NAME)
    target = tmp_path / "lossless.pdf"
    result = compress_run(
        [copy_path],
        lossless=True,
        images="keep",
        image_dpi=150.0,
        image_quality=80,
        pages_spec=None,
        output=target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_read_only_policy(),
    )
    assert result.exit_code == 0
    item = result.items[0]
    assert item.bytes_before is not None and item.bytes_after is not None
    assert item.bytes_after < item.bytes_before

    before_texts = page_texts(copy_path)
    after_texts = page_texts(target)
    assert len(before_texts) == len(after_texts) == _OPTIMIZE_SAMPLE_PAGES
    assert before_texts == after_texts


@pytest.mark.samples
def test_ac16_downsample_does_not_exceed_lossless_only_over_a_real_scan(
    samples, tmp_path: Path
) -> None:
    import sys

    tests_dir = Path(__file__).resolve().parent
    if str(tests_dir) not in sys.path:  # pragma: no cover - import plumbing
        sys.path.insert(0, str(tests_dir))
    from pdf_toolkit.ops.optimize import compress_run
    from pdfium_text import page_texts

    copy_path = samples.copy(_IMAGE_SAMPLE_NAME)

    lossless_target = tmp_path / "lossless.pdf"
    lossless_result = compress_run(
        [copy_path],
        lossless=True,
        images="keep",
        image_dpi=150.0,
        image_quality=80,
        pages_spec=None,
        output=lossless_target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_read_only_policy(),
    )
    assert lossless_result.exit_code == 0

    downsample_target = tmp_path / "downsampled.pdf"
    downsample_result = compress_run(
        [copy_path],
        lossless=False,
        images="downsample",
        image_dpi=150.0,
        image_quality=80,
        pages_spec=None,
        output=downsample_target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_read_only_policy(),
    )
    assert downsample_result.exit_code == 0
    assert downsample_target.stat().st_size <= lossless_target.stat().st_size

    before_texts = page_texts(copy_path)
    after_texts = page_texts(downsample_target)
    assert len(before_texts) == len(after_texts) == _IMAGE_SAMPLE_PAGES
    assert before_texts == after_texts


@pytest.mark.samples
def test_ac16_linearize_over_a_482_page_sample(samples, tmp_path: Path) -> None:
    import pikepdf

    from pdf_toolkit.ops.optimize import linearize_run

    copy_path = samples.copy(_OPTIMIZE_SAMPLE_NAME)
    target = tmp_path / "linearized.pdf"
    result = linearize_run(copy_path, output=target, in_place=False, policy=_read_only_policy())
    assert result.exit_code == 0

    with pikepdf.Pdf.open(target) as reopened:
        assert reopened.is_linearized is True


# --------------------------------------------------------------------------- #
# PDF-13 -- AC16. Over a COPY of a real CV: encrypt -> `info` reports AES-256
# -> decrypt -> the page tree comes back byte for byte.
#
# HC-2 / `PLAN.md` §10.1 binds this section harder than any other in this file,
# because the operand is a PERSONAL DOCUMENT. Originals are never an operand
# (`samples.copy()` only), nothing about it is asserted or reported beyond
# STRUCTURE -- page count, sizes and hashes -- and nothing password-bearing is
# captured, printed or written anywhere. `inspect_document` is called in
# process rather than `info -o json` through a subprocess deliberately: it is
# the same code path `info` runs, and it never renders this document's
# metadata into a captured stream that a failure report could carry.
# --------------------------------------------------------------------------- #

_CRYPTO_SAMPLE_NAME = "ArmandoHerra_Cloud_Architect_2026_CV.pdf"
_CRYPTO_SAMPLE_PASSWORD = "samples-arm-owner-password"


def _crypto_slot(path: Path, slot: str):
    from pdf_toolkit.cli.password import plan_password

    return plan_password(
        slot=slot,
        flag=f"--{slot}-password-file" if slot != "password" else "--password-file",
        value=str(path),
        env_names=(),
        prompt="x: ",
        allow_empty=slot != "owner",
    )


@pytest.mark.samples
def test_ac16_encrypt_info_decrypt_round_trips_a_real_document(samples, tmp_path: Path) -> None:
    import sys

    tests_dir = Path(__file__).resolve().parent
    if str(tests_dir) not in sys.path:  # pragma: no cover - import plumbing
        sys.path.insert(0, str(tests_dir))
    from pagetree import page_tree_digest
    from pdf_toolkit.ops.crypto import decrypt_run, encrypt_run
    from pdf_toolkit.ops.inspect import inspect_document

    copy_path = samples.copy(_CRYPTO_SAMPLE_NAME)
    password_file = tmp_path / "owner.pw"
    password_file.write_text(_CRYPTO_SAMPLE_PASSWORD)
    password_file.chmod(0o600)

    before = page_tree_digest(copy_path)
    assert before, "the sample yielded no pages"

    encrypted = tmp_path / "sample-encrypted.pdf"
    encrypt_result = encrypt_run(
        copy_path,
        owner=_crypto_slot(password_file, "owner"),
        user=None,
        allow=frozenset({"print"}),
        legacy=False,
        output=encrypted,
        in_place=False,
        policy=_read_only_policy(),
    )
    assert encrypt_result.exit_code == 0

    report = inspect_document(encrypted)
    assert report.encrypted is True
    assert report.encryption_algorithm == "AES-256"

    decrypted = tmp_path / "sample-decrypted.pdf"
    decrypt_result = decrypt_run(
        encrypted,
        password=_crypto_slot(password_file, "password"),
        output=decrypted,
        in_place=False,
        policy=_read_only_policy(),
    )
    assert decrypt_result.exit_code == 0

    assert page_tree_digest(decrypted) == before


@pytest.mark.samples
def test_ac16_the_original_is_never_an_operand(samples, tmp_path: Path) -> None:
    """HC-2 restated as a test rather than as a promise: the only path this
    arm can obtain is a copy under `tmp_path`, and it is writable."""
    copy_path = samples.copy(_CRYPTO_SAMPLE_NAME)
    assert copy_path.parent == tmp_path
    assert os.access(copy_path, os.W_OK)


# --------------------------------------------------------------------------- #
# PDF-08 -- AC27. Over a COPY of a real 482-page document: `extract` with a
# long page-range expression, and `reorder --in-place` exercising the `.bak`
# sidecar at a scale the generated corpus cannot reach.
#
# HC-2 / `PLAN.md` §10.1 binds this section as it binds every other: originals
# are NEVER an operand (`samples.copy()` only), and nothing about the document
# is asserted or reported beyond STRUCTURE -- page counts, sizes and hashes.
# No extracted text and no metadata value appears here, in a test name, in
# `changelog.md`, or in the Implementation Log.
#
# The ordering assertion below is what the generated corpus genuinely cannot
# make: `200-190` is an eleven-page DESCENDING range, and a document long
# enough to carry it is the only place where "order preserved" is
# distinguishable from several plausible wrong answers.
# --------------------------------------------------------------------------- #

_PAGES_SAMPLE_NAME = "PrendiniLoria2020.pdf"

#: 1-5 (5) + 100 (1) + 200-190 (11) + last (1). Derived from the spec rather
#: than measured from the tool's own output, so this cannot rubber-stamp
#: whatever the verb happened to produce.
_PAGES_EXTRACT_EXPECTED = 5 + 1 + 11 + 1


def _page_content_digests(path: Path) -> tuple[str, ...]:
    """One SHA-256 per page over the DECODED content-stream bytes, in page
    order -- the structural identity of a page's marks.

    Deliberately narrower than `tests/pagetree.py::page_tree_digest`, and the
    difference is measured rather than assumed. That helper additionally hashes
    the page dictionary, which makes it exact for PDF-13's pikepdf->pikepdf
    encrypt/decrypt round trip (its stated purpose) but unusable ACROSS a pypdf
    rewrite: pypdf re-serializes numeric literals, so a `/MediaBox` of
    `[0.0, 0.0, 495.0, 720.0]` comes back as `[0.0, 0.0, 495, 720]` and every
    page's token differs while the page itself is untouched. Verified on this
    section's own operand: with `extract --pages '1-3'`, the page-dictionary
    tokens differ on exactly that formatting while all three content streams
    are byte-identical.

    It reuses `pagetree._content_bytes` rather than re-deriving the
    `/Contents`-array coalescing, so the two helpers cannot drift on the one
    thing they share.

    Structural only, per HC-2 / `PLAN.md` §10.1 rule 4: a digest, never the
    bytes, and nothing this document says is read, asserted or reported.
    """
    import hashlib
    import sys

    import pikepdf

    tests_dir = Path(__file__).resolve().parent
    if str(tests_dir) not in sys.path:  # pragma: no cover - import plumbing
        sys.path.insert(0, str(tests_dir))
    from pagetree import _content_bytes

    digests: list[str] = []
    with pikepdf.Pdf.open(str(path)) as pdf:
        for page in pdf.pages:
            digests.append(hashlib.sha256(_content_bytes(page)).hexdigest())
    return tuple(digests)


@pytest.mark.samples
def test_ac27_extract_preserves_order_across_a_long_range_expression(
    samples, tmp_path: Path
) -> None:
    from pdf_toolkit.ops.pages import extract_run

    copy_path = samples.copy(_PAGES_SAMPLE_NAME)
    target = tmp_path / "extracted.pdf"
    result = extract_run(
        [copy_path],
        pages_spec="1-5,100,200-190,last",
        output=target,
        out_dir=None,
        name_template=None,
        policy=_read_only_policy(),
    )
    assert result.exit_code == 0

    from pypdf import PdfReader

    assert len(PdfReader(str(target)).pages) == _PAGES_EXTRACT_EXPECTED

    # Order preserved, asserted structurally: each output page must carry the
    # SAME content stream as the input page it claims to be -- never anything
    # the page says.
    source_pages = _page_content_digests(copy_path)
    output_pages = _page_content_digests(target)
    assert len(output_pages) == _PAGES_EXTRACT_EXPECTED
    assert output_pages[0] == source_pages[0], "the first output page is not the input's page 1"
    assert output_pages[4] == source_pages[4], "the fifth output page is not the input's page 5"
    # The descending block: output pages 7..17 are input pages 200..190.
    assert output_pages[6] == source_pages[199]
    assert output_pages[7] == source_pages[198]
    assert output_pages[16] == source_pages[189]
    assert output_pages[-1] == source_pages[-1], "the last output page is not the input's last"


@pytest.mark.samples
def test_ac27_reorder_in_place_keeps_the_document_whole_and_backs_it_up(
    samples, tmp_path: Path
) -> None:
    """§D3's totality invariant on a real document, plus §5.3 step 5's `.bak`.

    The `.bak` must hash to the SHA-256 taken of the copy BEFORE the run --
    which is the only thing that makes the sidecar a recovery path rather than
    a claim (`PLAN.md` §12 R-06: there is no undo journal).
    """
    import hashlib

    from pdf_toolkit.ops.pages import reorder_run
    from pdf_toolkit.safety.policy import SafetyPolicy

    copy_path = samples.copy(_PAGES_SAMPLE_NAME)
    before_hash = hashlib.sha256(copy_path.read_bytes()).hexdigest()

    from pypdf import PdfReader

    before_pages = len(PdfReader(str(copy_path)).pages)
    assert before_pages > 1, "this arm needs a multi-page operand"

    before_digests = _page_content_digests(copy_path)

    result = reorder_run(
        [copy_path],
        pages_spec="last,1",
        output=None,
        out_dir=None,
        name_template=None,
        in_place=True,
        policy=SafetyPolicy(
            dry_run=False,
            force=False,
            in_place=True,
            backup=True,
            assume_yes=False,
            is_tty=False,
            threads=1,
        ),
    )
    assert result.exit_code == 0

    backup = copy_path.with_name(copy_path.name + ".bak")
    assert backup.is_file(), "no .bak sidecar was written"
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == before_hash, (
        ".bak does not carry the pre-run bytes"
    )

    after_digests = _page_content_digests(copy_path)
    assert len(after_digests) == before_pages, "reorder changed the page count"
    assert after_digests[0] == before_digests[-1], "the original last page is not first"
    assert after_digests[1] == before_digests[0], "the original first page is not second"
    assert sorted(after_digests) == sorted(before_digests), "reorder lost or duplicated a page"


@pytest.mark.samples
def test_ac27_the_original_is_never_an_operand_for_the_pages_verbs(samples, tmp_path: Path) -> None:
    """HC-2 restated as a test rather than as a promise, for this section's own
    operand: the only path this arm can obtain is a copy under `tmp_path`."""
    copy_path = samples.copy(_PAGES_SAMPLE_NAME)
    assert copy_path.parent == tmp_path
    assert os.access(copy_path, os.W_OK)


# --------------------------------------------------------------------------- #
# PDF-14 -- AC17's three arms, over `catalogo_arquitectura_2017_2023_0.pdf`
# (14 pages, A4, MS Publisher, text + images -- PLAN.md §10.1, named for
# exactly "watermark/stamp on mixed pages, meta get/set"). Originals are
# NEVER an operand (`samples.copy()` only, HC-2 rule 1).
#
# ARM A carries this section's own, STRICTER privacy discipline (Design D12,
# AC25): no `/Info`/XMP VALUE from the real document is ever compared for
# equality directly -- a failing `assert a == b` would have pytest's own
# assertion rewriting interpolate BOTH sides into the failure message, which
# is exactly the leak AC25 exists to prevent. Preservation is proven with a
# SHA-256 FINGERPRINT of each value instead: a fingerprint mismatch still
# fails loudly, but a failure message can only ever show a hex digest, never
# the value it was computed from. Every assertion besides the fingerprint
# comparison is on `sorted(keys())`, `type(...).__name__` or `len(str(...))`
# -- a field name, a boolean, a count or a length, never a value (AC25's own
# affordance). `capsys` proves NOTHING was printed at all: Arm A calls
# `ops/metadata.py` directly, never the CLI, so there is no stdout to leak
# through in the first place -- proven rather than assumed.
#
# ARMS B/C follow this file's EXISTING, already-landed convention for
# structural/content preservation checks (PDF-12's own lossless sample test,
# above: `assert before_texts == after_texts`) -- HC-2 rule 4 forbids
# asserting or reporting a content string, not comparing two extractions for
# equality; a mismatch there is exactly the same class of risk every earlier
# @samples content-preservation arm already accepts. Arm C's own marker
# (`corpus.STAMP_MARKER`) is one THIS SUITE wrote (Design §D7 rule 4): the
# `stamp_source` fixture, never sample content.
#
# Nothing beyond filename, page count, size and hash is quoted anywhere in
# this section (HC-2 rule 4) -- no page text, no title, no metadata VALUE.
# --------------------------------------------------------------------------- #

_META_SAMPLE_NAME = "catalogo_arquitectura_2017_2023_0.pdf"
_META_SAMPLE_PAGES = 14


def _fingerprint(value: object) -> str:
    """A one-way digest of one metadata value -- proves equality without a
    failure message ever being able to show the value itself (AC25)."""
    import hashlib

    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()


@pytest.mark.samples
def test_pdf14_arm_a_meta_get_reports_a_non_empty_producer(
    samples, capsys: pytest.CaptureFixture[str]
) -> None:
    from pdf_toolkit.ops.metadata import meta_get_run

    copy_path = samples.copy(_META_SAMPLE_NAME)
    report = meta_get_run(copy_path, xmp=False)

    # Existence and LENGTH only (AC25) -- never the value.
    assert "Producer" in report.info
    assert isinstance(report.info["Producer"], str)
    assert len(report.info["Producer"]) > 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.samples
def test_pdf14_arm_a_meta_set_title_preserves_every_other_info_field(
    samples, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from pdf_toolkit.ops.metadata import meta_get_run, meta_set_run

    copy_path = samples.copy(_META_SAMPLE_NAME)
    before = meta_get_run(copy_path, xmp=False)
    before_keys = sorted(before.info)
    before_types = {key: type(value).__name__ for key, value in before.info.items()}
    before_fingerprints = {key: _fingerprint(value) for key, value in before.info.items()}

    target = tmp_path / "tagged.pdf"
    literal_title = "pdftoolkit-samples-arm-a-title"  # OUR OWN literal, never sample content
    result = meta_set_run(
        copy_path,
        sets={"title": literal_title},
        clear_producer=False,
        clear_all=False,
        output=target,
        in_place=False,
        policy=_read_only_policy(),
    )
    assert result.exit_code == 0

    after = meta_get_run(target, xmp=False)
    # `Title` may be a NEW key on a real document that never carried one --
    # `meta set --title` both ADDS an absent key and UPDATES a present one
    # (D2.2), and this sample happens to exercise the "absent" case, which
    # the generated corpus's own `metadata_typed` fixture (always title-
    # bearing) cannot. Every OTHER key's PRESENCE is unaffected either way.
    #
    # PDF-17/AC14 (`0355564e04`): the sentence above USED TO BE THE WHOLE
    # ARGUMENT. The set-union below distinguishes "added a key" from
    # "overwrote a key" only while the sample carries no `/Title`; the moment
    # one does, `{*before_keys, "Title"} == set(before_keys)` and the assertion
    # silently stops discriminating. Prose is now an assertion.
    assert_title_absent(before_keys, _META_SAMPLE_NAME)
    expected_keys = sorted({*before_keys, "Title"})
    assert sorted(after.info) == expected_keys, "meta set changed which keys are present"
    for key in before_keys:
        assert type(after.info[key]).__name__ == before_types[key], f"{key}: type changed"
        if key == "Title":
            continue
        assert _fingerprint(after.info[key]) == before_fingerprints[key], f"{key}: value changed"
    assert after.info["Title"] == literal_title

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.samples
def test_pdf14_arm_b_watermark_preserves_text_and_adds_draft_over_mixed_pages(
    samples, tmp_path: Path
) -> None:
    import sys

    tests_dir = Path(__file__).resolve().parent
    if str(tests_dir) not in sys.path:  # pragma: no cover - import plumbing
        sys.path.insert(0, str(tests_dir))
    from pdf_toolkit.ops.overlay import watermark_run
    from pdfium_text import page_texts

    copy_path = samples.copy(_META_SAMPLE_NAME)
    target = tmp_path / "watermarked.pdf"
    result = watermark_run(
        copy_path,
        text="DRAFT",
        pages_spec=None,
        position="overlay",
        font_size=36.0,
        color=(0.5, 0.5, 0.5),
        opacity=0.3,
        rotate_deg=30.0,
        output=target,
        in_place=False,
        policy=_read_only_policy(),
    )
    assert result.exit_code == 0

    before_texts = page_texts(copy_path)
    after_texts = page_texts(target)
    assert len(before_texts) == len(after_texts) == _META_SAMPLE_PAGES
    for before_text, after_text in zip(before_texts, after_texts, strict=True):
        assert before_text in after_text
        assert "DRAFT" in after_text


@pytest.mark.samples
def test_pdf14_arm_c_stamp_underlay_sits_beneath_a_real_page(
    samples, tmp_path: Path, corpus
) -> None:
    import pypdf

    from corpus import STAMP_MARKER
    from pdf_toolkit.ops.overlay import stamp_run

    copy_path = samples.copy(_META_SAMPLE_NAME)
    stamp_source = corpus.path("stamp_source")  # OUR OWN marker, never sample content

    over_target = tmp_path / "over.pdf"
    over_result = stamp_run(
        copy_path,
        from_path=stamp_source,
        from_page=1,
        pages_spec="1",
        position="overlay",
        output=over_target,
        in_place=False,
        policy=_read_only_policy(),
    )
    assert over_result.exit_code == 0
    over_stream = pypdf.PdfReader(str(over_target)).pages[0].get_contents().get_data()
    over_index = over_stream.index(STAMP_MARKER.encode())

    under_target = tmp_path / "under.pdf"
    under_result = stamp_run(
        copy_path,
        from_path=stamp_source,
        from_page=1,
        pages_spec="1",
        position="underlay",
        output=under_target,
        in_place=False,
        policy=_read_only_policy(),
    )
    assert under_result.exit_code == 0
    under_stream = pypdf.PdfReader(str(under_target)).pages[0].get_contents().get_data()
    under_index = under_stream.index(STAMP_MARKER.encode())

    # Structural proof, never a quoted content string (HC-2 rule 4): the
    # SAME marker, over the SAME real page, sits at a smaller byte offset
    # under `underlay` than under `overlay` -- exactly what "beneath" means
    # in content-stream order (Design §D4.3), without ever locating or
    # quoting the sample's own text.
    assert under_index < over_index


@pytest.mark.samples
def test_pdf14_the_original_is_never_an_operand(samples, tmp_path: Path) -> None:
    """HC-2 restated as a test rather than as a promise, for this section's
    own operand: the only path this arm can obtain is a copy under
    `tmp_path`, and it is writable."""
    copy_path = samples.copy(_META_SAMPLE_NAME)
    assert copy_path.parent == tmp_path
    assert os.access(copy_path, os.W_OK)


# --------------------------------------------------------------------------- #
# PDF-15 -- AC19/AC20. Over COPIES of `1888-10.pdf` and the
# `ArmandoHerra_Cloud_Architect_2026_CV.docx`/`.pdf` pair (originals are
# never an operand, HC-2 rule 1):
#   (a) `ocr --pages 1-2` on the 108-page real scan: 0 words before, non-empty
#       text on pages 1-2 after, page 1's image XObject byte-identical
#       (AC3 on a real scan, D13's instrument), page count still 108;
#   (b) `convert` of the CV `.docx` against the Google-Docs-produced `.pdf`
#       of the SAME document: 3 pages, normalised-token `SequenceMatcher`
#       ratio >= 0.90.
# HC-2 rule 4 is load-bearing in the failure path, not just the success path
# (D7): the assertion message carries ONLY the filename and the ratio --
# `f"{name}: token overlap {ratio:.2f}"` -- never the extracted text, on any
# path, pass or fail. Nothing beyond filename, page count, size and hash is
# quoted anywhere in this section.
# --------------------------------------------------------------------------- #

_OCR_SAMPLE_NAME = "1888-10.pdf"
_OCR_SAMPLE_PAGES = 108
_OCR_SAMPLE_DPI = 150

_CONVERT_SAMPLE_DOCX = "ArmandoHerra_Cloud_Architect_2026_CV.docx"
_CONVERT_SAMPLE_PDF = "ArmandoHerra_Cloud_Architect_2026_CV.pdf"
_CONVERT_SAMPLE_PAGES = 3
_CONVERT_SAMPLE_MIN_RATIO = 0.90


@pytest.mark.samples
@pytest.mark.requires("tesseract")
def test_ac19_ocr_pages_1_2_of_a_real_scan_preserves_the_image_and_recovers_text(
    samples, tmp_path: Path
) -> None:
    import sys

    tests_dir = Path(__file__).resolve().parent
    if str(tests_dir) not in sys.path:  # pragma: no cover - import plumbing
        sys.path.insert(0, str(tests_dir))
    from helpers.pdfstream import embedded_image_streams
    from pdf_toolkit.ops.ocr import ocr_run
    from pdf_toolkit.ports.structure import require_structure
    from pdf_toolkit.ports.text import require_text
    from pdf_toolkit.safety.policy import SafetyPolicy

    policy = SafetyPolicy(
        dry_run=False,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )

    copy_path = samples.copy(_OCR_SAMPLE_NAME)
    engine = require_structure()
    with engine.open_document(copy_path) as document:
        assert document.page_count == _OCR_SAMPLE_PAGES

    text_engine = require_text()
    before_page1 = "".join(text_engine.extract_text(str(copy_path), [1]))
    before_page2 = "".join(text_engine.extract_text(str(copy_path), [2]))
    assert before_page1 == ""
    assert before_page2 == ""

    before_page1_image = embedded_image_streams(copy_path, 0)
    assert len(before_page1_image) == 1

    output = tmp_path / "1888-10-ocrd.pdf"
    result = ocr_run(
        [copy_path],
        lang="eng",
        dpi=_OCR_SAMPLE_DPI,
        psm=3,
        skip_text_pages=False,
        pages_spec="1-2",
        output=output,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=policy,
    )
    assert result.exit_code == 0, result.items[0].message

    with engine.open_document(output) as document:
        assert document.page_count == _OCR_SAMPLE_PAGES

    after_page1 = "".join(text_engine.extract_text(str(output), [1]))
    after_page2 = "".join(text_engine.extract_text(str(output), [2]))
    assert after_page1 != ""
    assert after_page2 != ""

    after_page1_image = embedded_image_streams(output, 0)
    assert len(after_page1_image) == 1
    assert after_page1_image[0].raw == before_page1_image[0].raw


@pytest.mark.samples
@pytest.mark.requires("soffice")
def test_ac20_convert_docx_matches_the_google_docs_pdf_of_the_same_document(
    samples, tmp_path: Path
) -> None:
    import difflib

    from pdf_toolkit.ops.office import convert_run
    from pdf_toolkit.ports.structure import require_structure
    from pdf_toolkit.ports.text import require_text
    from pdf_toolkit.safety.policy import SafetyPolicy

    policy = SafetyPolicy(
        dry_run=False,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )

    docx_copy = samples.copy(_CONVERT_SAMPLE_DOCX)
    reference_pdf_copy = samples.copy(_CONVERT_SAMPLE_PDF)

    structure_engine = require_structure()
    with structure_engine.open_document(reference_pdf_copy) as document:
        assert document.page_count == _CONVERT_SAMPLE_PAGES

    output = tmp_path / "cv-converted.pdf"
    result = convert_run(
        [docx_copy],
        filter_name=None,
        timeout=120.0,
        output=output,
        out_dir=None,
        name_template=None,
        policy=policy,
    )
    assert result.exit_code == 0, result.items[0].message

    with structure_engine.open_document(output) as document:
        assert document.page_count == _CONVERT_SAMPLE_PAGES

    text_engine = require_text()
    converted_pages = text_engine.extract_text(
        str(output), list(range(1, _CONVERT_SAMPLE_PAGES + 1))
    )
    reference_pages = text_engine.extract_text(
        str(reference_pdf_copy), list(range(1, _CONVERT_SAMPLE_PAGES + 1))
    )
    converted_tokens = " ".join(converted_pages).lower().split()
    reference_tokens = " ".join(reference_pages).lower().split()

    ratio = difflib.SequenceMatcher(a=converted_tokens, b=reference_tokens).ratio()
    # HC-2 rule 4: the message carries ONLY the filename and the ratio --
    # never the extracted text, on any path, pass or fail.
    assert ratio >= _CONVERT_SAMPLE_MIN_RATIO, f"{_CONVERT_SAMPLE_DOCX}: token overlap {ratio:.2f}"


# --------------------------------------------------------------------------- #
# PDF-17 -- AC14: the precondition pin, and the general rule it introduces.
#
# WHERE A CONTROL IS SOUND ONLY BECAUSE OF A PROPERTY OF ITS INPUT, THAT
# PROPERTY IS ASSERTED, NOT ASSUMED. `0355564e04` is the first instance:
# `test_pdf14_arm_a_meta_set_title_preserves_every_other_info_field` is
# discriminating only while its sample carries no `/Title`, and its own comment
# conceded the point in prose.
#
# The red for this pin is deliberately taken INSIDE THE GENERATED CORPUS --
# `metadata_rich` does carry a `/Title` -- and never against the operator's
# originals. That keeps HC-2 satisfied with no skip: the proof below runs on
# every host, corpus or no corpus, which matters because the pinned arm itself
# is an `@samples` test and would otherwise carry two vacuity axes at once
# (a skipped control AND an assumed precondition).
# --------------------------------------------------------------------------- #


def assert_title_absent(before_keys, sample_name: str) -> None:
    """Fail when *sample_name* already carries a `/Title`.

    HC-2 binds the message: the sample is named by FILENAME ONLY -- no content,
    no metadata values, no path.
    """
    if "Title" in before_keys:
        raise AssertionError(
            f"{sample_name} carries a /Title before the run, which makes this arm's "
            "set-union assertion NON-DISCRIMINATING: `{*before_keys, 'Title'}` collapses "
            "to `before_keys`, so an added key and an overwritten key become "
            "indistinguishable. Point Arm A at a sample with no /Title, or split the "
            "arm in two -- do not relax the assertion."
        )


def test_the_arm_a_title_precondition_pin_fires(corpus) -> None:
    """AC14's red, taken against the GENERATED corpus so it needs no samples
    directory and touches no original: `metadata_rich` sets a title, so the
    precondition must fire on it."""
    from pdf_toolkit.ops.metadata import meta_get_run

    titled = meta_get_run(corpus.path("metadata_rich"), xmp=False)
    before_keys = sorted(titled.info)
    assert "Title" in before_keys, (
        "the metadata_rich fixture no longer carries a /Title -- this red proof has lost "
        "its subject and would pass by having nothing to detect"
    )
    with pytest.raises(AssertionError) as caught:
        assert_title_absent(before_keys, "metadata_rich.pdf")
    assert "NON-DISCRIMINATING" in str(caught.value)


def test_the_arm_a_title_precondition_pin_is_quiet_when_the_precondition_holds() -> None:
    """The positive half: a pin that raised unconditionally would fail Arm A
    for the wrong reason on every host with a corpus."""
    assert_title_absent(["Author", "Producer"], "some-sample.pdf")
