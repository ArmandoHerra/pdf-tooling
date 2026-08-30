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
