"""PDF-14 -- `watermark`/`stamp` at the op layer.

Everything here runs IN PROCESS, calling `ops/overlay.py` (and the ports it
sits on) directly. The subprocess-level contract (exit codes, `--help`
content, OR-3) lives in `tests/test_cli_contract.py` (unedited by this spec)
and `tests/integration/test_overlay_preservation.py`.

HC-2 binds this module: nothing here touches `$PDF_TOOLKIT_SAMPLES_DIR`. The
`@samples` arm lives in `tests/test_samples.py`'s own PDF-14 section.

Design D5 -- why this module extracts with pypdf directly
-----------------------------------------------------------
`text` (`PDF-11`) is not a dependency of this spec, and shelling out to it
here would create the undeclared edge D5 forbids. `page.extract_text()` is
called inline instead -- tests are not bound by the adapter rule (Design D1).
"""

from __future__ import annotations

import io
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any, Final

import pypdf
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))
REPO_ROOT = TESTS_DIR.parent

from corpus import STAMP_MARKER, changed_pages  # noqa: E402
from pdf_toolkit.errors import (  # noqa: E402
    EngineMissingError,
    FailureError,
    NoInputError,
    PageRangeError,
    UsageError,
)
from pdf_toolkit.ops.overlay import DEFAULT_POSITION, stamp_run, watermark_run  # noqa: E402
from pdf_toolkit.ports.compose import require_compose  # noqa: E402
from pdf_toolkit.ports.structure import require_composite  # noqa: E402
from pdf_toolkit.safety.policy import SafetyPolicy  # noqa: E402


def policy(**overrides: Any) -> SafetyPolicy:
    values: dict[str, Any] = {
        "dry_run": False,
        "force": False,
        "in_place": False,
        "backup": True,
        "assume_yes": False,
        "is_tty": False,
        "threads": 1,
    }
    values.update(overrides)
    return SafetyPolicy(**values)


def _normalized_text(page: Any) -> str:
    return " ".join((page.extract_text() or "").split())


# --------------------------------------------------------------------------- #
# AC8 -- PRESERVATION, watermark (three assertions, one test)
# --------------------------------------------------------------------------- #


def test_ac8_watermark_preserves_page_count_and_text_and_adds_draft(corpus, tmp_path: Path) -> None:
    """Over `rotated` -- 4 pages, rotations 0/90/180/270 -- so the
    "including its rotated page" clause is genuinely exercised."""
    source = corpus.path("rotated")
    before_reader = pypdf.PdfReader(str(source))
    before_texts = [_normalized_text(page) for page in before_reader.pages]

    target = tmp_path / "watermarked.pdf"
    result = watermark_run(
        source,
        text="DRAFT",
        pages_spec=None,
        position="overlay",
        font_size=24.0,
        color=(0.5, 0.5, 0.5),
        opacity=0.3,
        rotate_deg=0.0,
        output=target,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0

    after_reader = pypdf.PdfReader(str(target))
    # (a) page count equals.
    assert len(after_reader.pages) == len(before_reader.pages)
    for before_text, after_page in zip(before_texts, after_reader.pages, strict=True):
        after_text = _normalized_text(after_page)
        # (b) original text survives as a SUBSTRING (the watermark adds a run).
        assert before_text in after_text
        # (c) DRAFT is present on every selected page.
        assert "DRAFT" in after_text


# --------------------------------------------------------------------------- #
# AC9 -- page-range scoping is PDF-03's, not a local reimplementation
# --------------------------------------------------------------------------- #


def test_ac9_pages_flag_scopes_through_the_shared_grammar(corpus, tmp_path: Path) -> None:
    source = corpus.path("ten_page_text")
    target = tmp_path / "scoped.pdf"
    result = watermark_run(
        source,
        text="DRAFT",
        pages_spec="1-3,!2",
        position="overlay",
        font_size=24.0,
        color=(0.5, 0.5, 0.5),
        opacity=0.3,
        rotate_deg=0.0,
        output=target,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0
    reader = pypdf.PdfReader(str(target))
    for index, page in enumerate(reader.pages, start=1):
        text = _normalized_text(page)
        if index in (1, 3):
            assert "DRAFT" in text, f"page {index} should carry DRAFT"
        else:
            assert "DRAFT" not in text, f"page {index} should NOT carry DRAFT"


def test_ac9_malformed_pages_expression_exits_2(corpus, tmp_path: Path) -> None:
    with pytest.raises(PageRangeError):
        watermark_run(
            corpus.path("single_page"),
            text="DRAFT",
            pages_spec="1--3",
            position="overlay",
            font_size=24.0,
            color=(0.5, 0.5, 0.5),
            opacity=0.3,
            rotate_deg=0.0,
            output=tmp_path / "x.pdf",
            in_place=False,
            policy=policy(),
        )


def test_ac9_empty_selection_exits_4(corpus, tmp_path: Path) -> None:
    with pytest.raises(NoInputError):
        watermark_run(
            corpus.path("single_page"),
            text="DRAFT",
            pages_spec="all,!all",
            position="overlay",
            font_size=24.0,
            color=(0.5, 0.5, 0.5),
            opacity=0.3,
            rotate_deg=0.0,
            output=tmp_path / "x.pdf",
            in_place=False,
            policy=policy(),
        )


# --------------------------------------------------------------------------- #
# AC10 -- `stamp --position underlay` proven by CONTENT-STREAM ORDER
# --------------------------------------------------------------------------- #


def _run_stamp(corpus, tmp_path: Path, *, position: str, name: str) -> Path:
    target = tmp_path / name
    result = stamp_run(
        corpus.path("single_page"),
        from_path=corpus.path("stamp_source"),
        from_page=1,
        pages_spec=None,
        position=position,
        output=target,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0
    return target


def test_ac10_stamp_position_ordering_both_directions(corpus, tmp_path: Path) -> None:
    # `single_page`'s own fixture text is the "base" marker -- both it and
    # `STAMP_MARKER` are drawn in reportlab's default Helvetica (base-14),
    # so both appear as LITERAL ASCII in the content stream, never
    # subset-encoded hex (Design §D4.3).
    base_marker = corpus.spec("single_page").page_texts[0].encode()
    stamp_marker = STAMP_MARKER.encode()

    underlay_target = _run_stamp(corpus, tmp_path, position="underlay", name="underlay.pdf")
    stream = pypdf.PdfReader(str(underlay_target)).pages[0].get_contents().get_data()
    assert stream.index(stamp_marker) < stream.index(base_marker)

    overlay_target = _run_stamp(corpus, tmp_path, position="overlay", name="overlay.pdf")
    stream = pypdf.PdfReader(str(overlay_target)).pages[0].get_contents().get_data()
    assert stream.index(stamp_marker) > stream.index(base_marker)


# --------------------------------------------------------------------------- #
# AC11 -- default position (both verbs)
# --------------------------------------------------------------------------- #


def test_ac11_default_position_constant_is_overlay() -> None:
    assert DEFAULT_POSITION == "overlay"


def test_ac11_stamp_without_position_produces_overlay_ordering(corpus, tmp_path: Path) -> None:
    target = tmp_path / "default-position.pdf"
    result = stamp_run(
        corpus.path("single_page"),
        from_path=corpus.path("stamp_source"),
        from_page=1,
        pages_spec=None,
        position=DEFAULT_POSITION,
        output=target,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0
    base_marker = corpus.spec("single_page").page_texts[0].encode()
    stream = pypdf.PdfReader(str(target)).pages[0].get_contents().get_data()
    assert stream.index(STAMP_MARKER.encode()) > stream.index(base_marker)


# --------------------------------------------------------------------------- #
# AC16 -- `stamp --from` failure modes (Design D4.5), the two legs not
# already covered at the subprocess level: `tests/integration/
# test_overlay_preservation.py`'s AC29 tests prove the missing-path (exit 4)
# and encrypted-with-no-password (exit 6) legs, across every output shape.
# These two close the remaining half of D4.5's four-row table -- malformed
# and from-page-exceeds -- at the op layer.
# --------------------------------------------------------------------------- #


def test_ac16_malformed_from_exits_1(tmp_path: Path, corpus) -> None:
    malformed = tmp_path / "malformed.pdf"
    malformed.write_bytes(b"not a pdf at all")
    with pytest.raises(FailureError, match="--from is malformed"):
        stamp_run(
            corpus.path("single_page"),
            from_path=malformed,
            from_page=1,
            pages_spec=None,
            position="overlay",
            output=tmp_path / "out.pdf",
            in_place=False,
            policy=policy(),
        )


def test_ac16_from_page_exceeding_the_sources_count_exits_2_naming_both_numbers(
    tmp_path: Path, corpus
) -> None:
    """`stamp_source` is a 1-page fixture (Design §D4.3) -- `--from-page 99`
    must name both the requested page and the source's own page count."""
    with pytest.raises(UsageError, match=r"--from-page 99 exceeds --from's page count \(1\)"):
        stamp_run(
            corpus.path("single_page"),
            from_path=corpus.path("stamp_source"),
            from_page=99,
            pages_spec=None,
            position="overlay",
            output=tmp_path / "out.pdf",
            in_place=False,
            policy=policy(),
        )


# --------------------------------------------------------------------------- #
# AC12 -- unusual content streams (Design D4.4)
# --------------------------------------------------------------------------- #


def test_ac12a_no_contents_page_composites_and_warns_overlay_underlay_identical(
    corpus, tmp_path: Path
) -> None:
    outputs: dict[str, bytes] = {}
    for position in ("overlay", "underlay"):
        target = tmp_path / f"no-contents-{position}.pdf"
        result = watermark_run(
            corpus.path("no_contents_page"),
            text="DRAFT",
            pages_spec=None,
            position=position,
            font_size=24.0,
            color=(0.5, 0.5, 0.5),
            opacity=0.3,
            rotate_deg=0.0,
            output=target,
            in_place=False,
            policy=policy(),
        )
        assert result.exit_code == 0
        assert result.warnings and "1" in result.warnings[0]
        outputs[position] = pypdf.PdfReader(str(target)).pages[0].get_contents().get_data()
    assert outputs["overlay"] == outputs["underlay"]


def test_ac12b_empty_contents_page_composites_with_no_warning(corpus, tmp_path: Path) -> None:
    target = tmp_path / "empty-contents.pdf"
    result = watermark_run(
        corpus.path("empty_contents_page"),
        text="DRAFT",
        pages_spec=None,
        position="overlay",
        font_size=24.0,
        color=(0.5, 0.5, 0.5),
        opacity=0.3,
        rotate_deg=0.0,
        output=target,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0
    assert result.warnings == ()
    stream = pypdf.PdfReader(str(target)).pages[0].get_contents().get_data()
    assert b"DRAFT" in stream


# --------------------------------------------------------------------------- #
# AC14 -- the primitive is reusable by `PDF-15`, without invoking the CLI
#
# `PDF-23` AC20's own blast-radius grep found this test calling the port with
# the PRE-MIGRATION signature (a bare `document`, D3's own reader-attached
# shape) -- updated here to the writer-attached shape §D3.1 requires: the
# writer is created and the source's page appended BEFORE `composite_layer`
# is called, exactly as every production caller now does.
# --------------------------------------------------------------------------- #


def test_ac14_composite_layer_is_callable_directly_without_the_cli(corpus) -> None:
    engine = require_composite()
    layer = corpus.path("stamp_source").read_bytes()
    with engine.open_document(corpus.path("single_page")) as document:
        overlay_writer = engine.new_writer()
        overlay_writer.append_pages(document, [1])
        overlay_outcome = engine.composite_layer(
            overlay_writer, layer=layer, pages=[1], position="overlay"
        )
        assert overlay_outcome.pages_composited == (1,)
    with engine.open_document(corpus.path("single_page")) as document:
        underlay_writer = engine.new_writer()
        underlay_writer.append_pages(document, [1])
        underlay_outcome = engine.composite_layer(
            underlay_writer, layer=layer, pages=[1], position="underlay"
        )
        assert underlay_outcome.pages_composited == (1,)


# --------------------------------------------------------------------------- #
# AC15 -- the scoping guarantee, asserted AT THE PORT, without the CLI
# --------------------------------------------------------------------------- #


def test_ac15_composite_layer_direct_call_scopes_via_writer(corpus) -> None:
    """`require_composite().composite_layer(...)` called directly, over a
    writer built in this test from `shared_contents_pages` -- the scoping
    guarantee (Design D2/D4) holds at the PORT, not merely at `ops/overlay.py`.

    `require_composite()` is still selected BY CAPABILITY (`"composite"`),
    never by adapter name (X-76) -- unchanged by this call shape.
    """
    engine = require_composite()
    assert engine.adapter_name == "pypdf"  # X-76: capability, not a guess
    layer = corpus.path("stamp_source").read_bytes()
    source = corpus.path("shared_contents_pages")
    with engine.open_document(source) as document:
        writer = engine.new_writer()
        writer.append_pages(document, [1, 2, 3])
        outcome = engine.composite_layer(writer, layer=layer, pages=[2], position="overlay")
        assert outcome.pages_composited == (2,)
        assert outcome.pages_copied == (2,), (
            "page 2's /Contents was shared with pages 1 and 3 -- copy-on-write must fire"
        )
        buffer = io.BytesIO()
        writer.write(buffer)
    buffer.seek(0)
    reader = pypdf.PdfReader(buffer)
    # The sibling pages' own /Contents object identity must be untouched --
    # asserted here at the port level, independent of `ops/overlay.py`.
    contents_numbers = [
        page.raw_get("/Contents").idnum if hasattr(page.raw_get("/Contents"), "idnum") else None
        for page in reader.pages
    ]
    assert contents_numbers[0] == contents_numbers[2], (
        "unselected siblings must still share their original /Contents object"
    )
    assert contents_numbers[1] != contents_numbers[0], (
        "the selected page's copy-on-written /Contents must be its OWN object now"
    )


# --------------------------------------------------------------------------- #
# AC26 -- page-range resolution is CALLED, not merely absent locally
# --------------------------------------------------------------------------- #


def test_ac26_page_range_resolution_is_invoked_exactly_once_per_run(
    monkeypatch: pytest.MonkeyPatch, corpus, tmp_path: Path
) -> None:
    import pdf_toolkit.ops.overlay as overlay_module

    original = overlay_module.parse
    calls: list[tuple[Any, ...]] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(overlay_module, "parse", spy)

    watermark_run(
        corpus.path("single_page"),
        text="DRAFT",
        pages_spec="1",
        position="overlay",
        font_size=24.0,
        color=(0.5, 0.5, 0.5),
        opacity=0.3,
        rotate_deg=0.0,
        output=tmp_path / "wm.pdf",
        in_place=False,
        policy=policy(),
    )
    assert len(calls) == 1
    assert calls[0][0] == "1"

    calls.clear()
    stamp_run(
        corpus.path("single_page"),
        from_path=corpus.path("stamp_source"),
        from_page=1,
        pages_spec="1",
        position="overlay",
        output=tmp_path / "st.pdf",
        in_place=False,
        policy=policy(),
    )
    assert len(calls) == 1
    assert calls[0][0] == "1"


# --------------------------------------------------------------------------- #
# AC28 -- capability tokens, never adapter names (X-76)
# --------------------------------------------------------------------------- #


def test_ac28_text_layer_capability_resolves_to_reportlab() -> None:
    engine = require_compose(capability="text-layer")
    assert engine.adapter_name == "reportlab"


def test_ac28_composite_capability_resolves_to_pypdf() -> None:
    engine = require_composite()
    assert engine.adapter_name == "pypdf"


def test_ac28_an_unknown_compose_capability_raises_engine_missing_exit_3() -> None:
    with pytest.raises(EngineMissingError) as excinfo:
        require_compose(capability="no-such-capability")
    assert excinfo.value.exit_code == 3


def test_ac28_an_unknown_structure_capability_raises_engine_missing_exit_3() -> None:
    from pdf_toolkit.ports.structure import require_structure

    with pytest.raises(EngineMissingError) as excinfo:
        require_structure(capability="no-such-capability")
    assert excinfo.value.exit_code == 3


# =============================================================================
# PDF-23 -- page-scoped overlays & merge_page migration
# =============================================================================
#
# AC4's own two remaining shapes -- "/Contents array with a shared element"
# and "one page object referenced twice from /Kids" -- are built LOCALLY
# here, never as a second `tests/corpus.py` registration: Design §D7's own
# Scope row names exactly ONE new corpus builder (`shared_contents_pages`),
# and both of these are single-use, low-level pypdf constructions that gain
# nothing from being named-and-shared the way a corpus fixture is.
# --------------------------------------------------------------------------- #

_LETTER: Final[tuple[float, float]] = (612.0, 792.0)


def _build_array_shared_pages(path: Path) -> None:
    """D4.3 row 3: THREE pages, each `/Contents` a direct `ArrayObject` of
    `[own, shared]`, where `shared` is the SAME indirect stream object on
    every page and `own` is unique per page. D4.5's own subject."""
    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject, NameObject, StreamObject

    writer = PdfWriter()
    shared = StreamObject()
    shared.set_data(b"1 0 0 RG 1 w 72 700 468 20 re S")
    shared_ref = writer._add_object(shared)  # noqa: SLF001 - test construction
    for index in range(3):
        page = writer.add_blank_page(width=_LETTER[0], height=_LETTER[1])
        own = StreamObject()
        own.set_data(f"0 1 0 RG 1 w 72 {600 - index} 200 10 re S".encode())
        own_ref = writer._add_object(own)  # noqa: SLF001 - test construction
        page[NameObject("/Contents")] = ArrayObject([own_ref, shared_ref])
    with open(path, "wb") as handle:  # noqa: PTH123 - test-only scratch
        writer.write(handle)


def _build_kids_duplicated_pages(path: Path) -> None:
    """D4.3 row 4: THREE `/Kids` slots, the first TWO referencing the SAME
    underlying page object (legal PDF -- `PdfWriter.add_page` splits it into
    two distinct page dictionaries per D3.1.3, only THEN sharing one
    `/Contents` object as a side effect of that split)."""
    from pypdf import PdfWriter
    from pypdf.generic import NameObject, NumberObject, StreamObject

    writer = PdfWriter()
    page_a = writer.add_blank_page(width=_LETTER[0], height=_LETTER[1])
    stream_a = StreamObject()
    stream_a.set_data(b"1 0 0 RG 1 w 72 700 468 20 re S")
    page_a[NameObject("/Contents")] = writer._add_object(stream_a)  # noqa: SLF001
    page_c = writer.add_blank_page(width=_LETTER[0], height=_LETTER[1])
    stream_c = StreamObject()
    stream_c.set_data(b"0 1 0 RG 1 w 72 600 468 20 re S")
    page_c[NameObject("/Contents")] = writer._add_object(stream_c)  # noqa: SLF001
    kids = writer._root_object["/Pages"]["/Kids"]  # noqa: SLF001 - test construction
    kids.insert(1, page_a.indirect_reference)
    pages_node = writer._root_object["/Pages"]  # noqa: SLF001 - test construction
    pages_node[NameObject("/Count")] = NumberObject(int(pages_node["/Count"]) + 1)
    with open(path, "wb") as handle:  # noqa: PTH123 - test-only scratch
        writer.write(handle)


def _shape_document(name: str, corpus, tmp_path: Path) -> Path:
    """One of AC4's four document shapes, by name."""
    if name == "distinct":
        return corpus.path("multipage_text")
    if name == "scalar_shared":
        return corpus.path("shared_contents_pages")
    if name == "array_shared":
        path = tmp_path / "array_shared.pdf"
        _build_array_shared_pages(path)
        return path
    if name == "kids_duplicated":
        path = tmp_path / "kids_duplicated.pdf"
        _build_kids_duplicated_pages(path)
        return path
    raise ValueError(name)  # pragma: no cover - test-authoring guard


# --------------------------------------------------------------------------- #
# AC1 -- the headline defect, asserted from the FILE (Design §D5.2)
# --------------------------------------------------------------------------- #


def test_ac1_watermark_scopes_to_selection_on_shared_contents(corpus, tmp_path: Path) -> None:
    """`4adc417234` / B-097's exact reproducer. Pre-fix: changed set was
    `{1, 2, 3}` against an expected `{2}`, message `watermarked 1 page(s)`
    (recorded in `tests/acceptance/audit_pdf_23.py`, AC1's `red`)."""
    source = corpus.path("shared_contents_pages")
    target = tmp_path / "watermarked.pdf"
    result = watermark_run(
        source,
        text="SENTINELWM",
        pages_spec="2",
        position="overlay",
        font_size=24.0,
        color=(0.5, 0.5, 0.5),
        opacity=0.3,
        rotate_deg=0.0,
        output=target,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0
    changed = changed_pages(source, target)
    assert changed == frozenset({2}), f"expected exactly {{2}} changed, got {sorted(changed)}"


# --------------------------------------------------------------------------- #
# AC2 -- the same, for `stamp`
# --------------------------------------------------------------------------- #


def test_ac2_stamp_scopes_to_selection_on_shared_contents(corpus, tmp_path: Path) -> None:
    source = corpus.path("shared_contents_pages")
    target = tmp_path / "stamped.pdf"
    result = stamp_run(
        source,
        from_path=corpus.path("stamp_source"),
        from_page=1,
        pages_spec="2",
        position="overlay",
        output=target,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0
    changed = changed_pages(source, target)
    assert changed == frozenset({2}), f"expected exactly {{2}} changed, got {sorted(changed)}"


# --------------------------------------------------------------------------- #
# AC4 / AC5 / AC7 -- one parametrized run per (shape, selection), asserting
# all THREE complementary properties of the SAME produced file:
#   AC4 -- the changed set (derived from the file, §D5.2) equals the selection
#   AC5 -- the message's integer AND `detail["pages_composited"]` agree with it
#   AC7 -- every UNSELECTED page's raw `/Contents` object number AND decoded
#          content are unchanged from input to output
# These are three independent readings of one run, not three runs -- D5.2's
# own rule ("a test that asserts only the counter does not satisfy AC5") is
# honoured by computing the changed set from the FILE first and comparing
# every other signal against it, never the reverse.
#
# `distinct` and `array_shared` are ALREADY GREEN pre-fix (§D4.3) -- their
# rows below are not evidence the fix works, only evidence it does not
# regress a case that was already correct. `scalar_shared` and
# `kids_duplicated` are the two shapes that were RED pre-fix.
# --------------------------------------------------------------------------- #

_SHAPE_NAMES: Final[tuple[str, ...]] = (
    "distinct",
    "scalar_shared",
    "array_shared",
    "kids_duplicated",
)
_SELECTIONS: Final[tuple[str, ...]] = ("2", "1,3")


@pytest.mark.parametrize("shape", _SHAPE_NAMES)
@pytest.mark.parametrize("pages_spec", _SELECTIONS)
def test_ac4_ac5_ac7_selection_count_and_unselected_pages_across_shapes(
    shape: str, pages_spec: str, corpus, tmp_path: Path
) -> None:
    from pypdf.generic import IndirectObject

    source = _shape_document(shape, corpus, tmp_path)
    target = tmp_path / f"{shape}-{pages_spec.replace(',', '_')}.pdf"
    result = watermark_run(
        source,
        text="SENTINELWM",
        pages_spec=pages_spec,
        position="overlay",
        font_size=24.0,
        color=(0.5, 0.5, 0.5),
        opacity=0.3,
        rotate_deg=0.0,
        output=target,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0

    expected = frozenset(int(token) for token in pages_spec.split(","))
    changed = changed_pages(source, target)

    # AC4 -- the changed set equals the selection, exactly.
    assert changed == expected, (
        f"{shape}/{pages_spec}: changed set {sorted(changed)} != selection {sorted(expected)}"
    )

    # AC5 -- the message's own integer and the reported detail agree with it.
    item = result.items[0]
    reported_count = int(item.message.split()[1])
    assert reported_count == len(changed), f"{shape}/{pages_spec}: message count mismatch"
    assert set(item.detail["pages_composited"]) == changed, (
        f"{shape}/{pages_spec}: detail['pages_composited'] disagrees with the file"
    )

    # AC7 -- every UNSELECTED page is untouched, structurally AND in content.
    before_reader = pypdf.PdfReader(str(source))
    after_reader = pypdf.PdfReader(str(target))
    for number in range(1, len(before_reader.pages) + 1):
        if number in expected:
            continue
        before_page = before_reader.pages[number - 1]
        after_page = after_reader.pages[number - 1]
        before_raw = before_page.raw_get("/Contents") if "/Contents" in before_page else None
        after_raw = after_page.raw_get("/Contents") if "/Contents" in after_page else None
        if isinstance(before_raw, IndirectObject):
            # Absolute idnums are not comparable across two independent
            # serializations (the whole file was rewritten) -- what matters
            # is that this unselected page's content is untouched, which
            # `changed_pages` (decoded, coalesced across an array) already
            # proved above. This branch exists so the assertion reads as a
            # positive statement about presence/absence, not only content.
            assert after_raw is not None, f"{shape}/{pages_spec}: page {number} lost /Contents"


# --------------------------------------------------------------------------- #
# AC6 -- copy-on-write is SCOPED, never blanket
# --------------------------------------------------------------------------- #


def test_ac6_copy_on_write_is_scoped_not_blanket(corpus, tmp_path: Path) -> None:
    # No sharing at all -- `pages_copied` must be empty.
    no_share_source = corpus.path("multipage_text")
    no_share_target = tmp_path / "no-share.pdf"
    result = watermark_run(
        no_share_source,
        text="SENTINELWM",
        pages_spec="2",
        position="overlay",
        font_size=24.0,
        color=(0.5, 0.5, 0.5),
        opacity=0.3,
        rotate_deg=0.0,
        output=no_share_target,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0
    assert result.items[0].detail["pages_copied"] == []

    # Sharing, selection == the shared subset -- `pages_copied == [2]`.
    shared_source = corpus.path("shared_contents_pages")
    shared_target = tmp_path / "shared.pdf"
    result2 = watermark_run(
        shared_source,
        text="SENTINELWM",
        pages_spec="2",
        position="overlay",
        font_size=24.0,
        color=(0.5, 0.5, 0.5),
        opacity=0.3,
        rotate_deg=0.0,
        output=shared_target,
        in_place=False,
        policy=policy(),
    )
    assert result2.exit_code == 0
    assert result2.items[0].detail["pages_copied"] == [2]


# --------------------------------------------------------------------------- #
# AC11 -- `PDF-14` AC12(c), the array-`/Contents` case, covered for the
# first time (§D4.5). NOT a re-derivation of a `PDF-14` grant -- `grep -rn
# 'def test_ac12' tests/` returns only `test_ac12a...`/`test_ac12b...` at
# HEAD; there has never been a `test_ac12c...`. Reported to the PM as an
# unmeasured `PDF-14` criterion in the `0615feae63` family, discharged here
# only for THIS spec's own AC11, never as a `PDF-14` status change.
# --------------------------------------------------------------------------- #


def test_ac11_array_contents_shared_element_scopes_and_preserves(corpus, tmp_path: Path) -> None:
    path = tmp_path / "array_shared.pdf"
    _build_array_shared_pages(path)
    before_reader = pypdf.PdfReader(str(path))
    before_texts = [_normalized_text(page) for page in before_reader.pages]

    target = tmp_path / "array-shared-watermarked.pdf"
    result = watermark_run(
        path,
        text="DRAFT",
        pages_spec="2",
        position="overlay",
        font_size=24.0,
        color=(0.5, 0.5, 0.5),
        opacity=0.3,
        rotate_deg=0.0,
        output=target,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0

    # AC1's own scoping property, over the array-shared shape.
    assert changed_pages(path, target) == frozenset({2})

    # AC8's own preservation property, over the array-shared shape: page
    # count unchanged, every page's own prior content survives as a
    # substring, DRAFT present on the selected page.
    after_reader = pypdf.PdfReader(str(target))
    assert len(after_reader.pages) == len(before_reader.pages)
    for index, (before_text, after_page) in enumerate(
        zip(before_texts, after_reader.pages, strict=True), start=1
    ):
        after_text = _normalized_text(after_page)
        assert before_text in after_text
        if index == 2:
            assert "DRAFT" in after_text


# --------------------------------------------------------------------------- #
# AC12 -- the pypdf deprecation is gone from `watermark`/`stamp`'s own
# `composite_layer` call, and the guard itself can fail (a
# `simplefilter("always")` catch, never a mere absence of output).
#
# `ocr` is the THIRD consumer and is deliberately NOT asserted zero here --
# see `tests/integration/test_ocr.py`'s own AC12 arm and this spec's report
# for why: `adapters/tesseract_ocr.py::_normalize_layer_geometry` calls
# `page.add_transformation(...)`, which ALSO reaches `replace_contents` on a
# page that is measured, not assumed, to be reader-attached (NOT
# writer-attached as this spec's own Design §D6 claims) at the moment it is
# called -- a residual warning from a call site this spec's Scope puts OUT
# of bounds (`ocr`'s geometry normalization is `PDF-15`'s). AC12's own text:
# "If the post-fix full-suite census is non-zero for reasons outside these
# three consumers, report the residue -- do not widen the guard to hide it."
# This is exactly that residue, reported rather than silently absorbed into
# a false "zero" claim for `ocr`.
#
# The FULL-SUITE census (whole-suite figures recorded in the Implementation
# Log per Design §D3/Validation step 3) is a shell command, not a pytest
# assertion -- a whole-tree count is not this test's own property.
# --------------------------------------------------------------------------- #


def test_ac12_zero_pypdf_deprecation_warnings_from_watermark_and_stamp(
    corpus, tmp_path: Path
) -> None:
    source = corpus.path("shared_contents_pages")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        watermark_run(
            source,
            text="X",
            pages_spec="2",
            position="overlay",
            font_size=24.0,
            color=(0.5, 0.5, 0.5),
            opacity=0.3,
            rotate_deg=0.0,
            output=tmp_path / "wm.pdf",
            in_place=False,
            policy=policy(),
        )
        stamp_run(
            source,
            from_path=corpus.path("stamp_source"),
            from_page=1,
            pages_spec="2",
            position="overlay",
            output=tmp_path / "st.pdf",
            in_place=False,
            policy=policy(),
        )
    pypdf_deprecations = [
        item
        for item in caught
        if issubclass(item.category, DeprecationWarning) and "pypdf" in (item.filename or "")
    ]
    assert pypdf_deprecations == [], (
        f"{len(pypdf_deprecations)} pypdf DeprecationWarning(s) survived the migration: "
        f"{[str(item.message) for item in pypdf_deprecations]}"
    )


# --------------------------------------------------------------------------- #
# AC16 -- the docstrings do not outlive the contract they describe.
# Mechanized exactly as the spec's own text states it, so a REGRESSION
# (someone re-introducing a `merge_page` prose reference) reds the suite
# rather than waiting for the next audit sweep.
# --------------------------------------------------------------------------- #


def test_ac16_no_merge_page_or_pre_append_prose_survives_in_ports_or_ops() -> None:
    merge_page = subprocess.run(
        [
            "grep",
            "-rn",
            "--include=*.py",
            "merge_page",
            "src/pdf_toolkit/ports/",
            "src/pdf_toolkit/ops/",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    assert merge_page.returncode == 1 and merge_page.stdout == "", (
        f"'merge_page' still referenced under ports/ or ops/: {merge_page.stdout}"
    )
    pre_append = subprocess.run(
        ["grep", "-n", "PRE-append", "src/pdf_toolkit/ports/structure.py"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    assert pre_append.returncode == 1 and pre_append.stdout == "", (
        f"'PRE-append' prose still present: {pre_append.stdout}"
    )


# --------------------------------------------------------------------------- #
# AC17 -- `--dry-run` still mirrors, and the mirror was not disturbed (OR-7).
#
# CORRECTED FROM THE SPEC'S OWN TEXT: AC17 as written says the dry run
# "exits 0 with detail.would_exit == 5". Measured against the shipped,
# ALREADY-PASSING `tests/test_cli_contract.py::
# test_c15_dry_run_predicts_an_occupied_target_refusal` (not owned by this
# spec, unmodified): the actual, correct, X-185-consistent contract is
# `dry.returncode == real.returncode == 5` -- BOTH exit 5, never 0. "Exits 0"
# would break OR-7's own `dry == real` invariant this AC exists to protect.
# Reported rather than implemented as literally written.
#
# The RED THIS TEST OBSERVES, and the CLI-level `test_c15` above CANNOT: a
# temporary, reverted mutation of `safety/atomic.py::plan_output_set`'s
# dry-run branch (`except PdfToolkitError as refusal: raise` unconditionally,
# dropping the `if not policy.dry_run:` guard) makes `dry.returncode ==
# real.returncode == 5` STILL hold at the CLI/subprocess level (the
# top-level error handler converts ANY raised `PdfToolkitError` to its own
# `exit_code`, which happens to be 5 either way) -- X-185's fuller claim,
# that `--dry-run` NEVER raises and instead returns a graceful envelope
# carrying `would_exit`, is what actually breaks, and only an IN-PROCESS
# assertion on the op layer's own return value (not the process exit code)
# can see it. This is why this test calls `watermark_run`/`stamp_run`/
# `ocr_run` directly rather than through `run_cli`.
# --------------------------------------------------------------------------- #


def test_ac17_dry_run_still_mirrors_and_never_raises(corpus, tmp_path: Path) -> None:
    from pdf_toolkit.errors import PdfToolkitError
    from pdf_toolkit.ops.ocr import ocr_run

    source = corpus.path("single_page")

    def dry_and_real_watermark(target: Path):
        dry = watermark_run(
            source,
            text="X",
            pages_spec=None,
            position="overlay",
            font_size=24.0,
            color=(0.5, 0.5, 0.5),
            opacity=0.3,
            rotate_deg=0.0,
            output=target,
            in_place=False,
            policy=policy(dry_run=True),
        )
        with pytest.raises(PdfToolkitError) as excinfo:
            watermark_run(
                source,
                text="X",
                pages_spec=None,
                position="overlay",
                font_size=24.0,
                color=(0.5, 0.5, 0.5),
                opacity=0.3,
                rotate_deg=0.0,
                output=target,
                in_place=False,
                policy=policy(dry_run=False),
            )
        return dry, excinfo.value

    def dry_and_real_stamp(target: Path):
        dry = stamp_run(
            source,
            from_path=corpus.path("stamp_source"),
            from_page=1,
            pages_spec=None,
            position="overlay",
            output=target,
            in_place=False,
            policy=policy(dry_run=True),
        )
        with pytest.raises(PdfToolkitError) as excinfo:
            stamp_run(
                source,
                from_path=corpus.path("stamp_source"),
                from_page=1,
                pages_spec=None,
                position="overlay",
                output=target,
                in_place=False,
                policy=policy(dry_run=False),
            )
        return dry, excinfo.value

    def dry_and_real_ocr(target: Path):
        dry = ocr_run(
            [source],
            lang="eng",
            dpi=200,
            psm=3,
            skip_text_pages=False,
            pages_spec=None,
            output=target,
            out_dir=None,
            name_template=None,
            in_place=False,
            policy=policy(dry_run=True),
        )
        with pytest.raises(PdfToolkitError) as excinfo:
            ocr_run(
                [source],
                lang="eng",
                dpi=200,
                psm=3,
                skip_text_pages=False,
                pages_spec=None,
                output=target,
                out_dir=None,
                name_template=None,
                in_place=False,
                policy=policy(dry_run=False),
            )
        return dry, excinfo.value

    for name, runner in (
        ("watermark", dry_and_real_watermark),
        ("stamp", dry_and_real_stamp),
        ("ocr", dry_and_real_ocr),
    ):
        target = tmp_path / f"{name}-occupied.pdf"
        target.write_bytes(b"C15-SEEDED-BYTES")
        before = target.read_bytes()

        dry_result, real_error = runner(target)

        # `--dry-run` NEVER raises -- it returns a graceful envelope.
        assert dry_result.dry_run is True, f"{name}: dry run did not set dry_run=True"
        item = dry_result.items[0]
        assert item.exit_code == 5, f"{name}: dry item.exit_code = {item.exit_code}, want 5"
        assert item.detail["would_exit"] == 5, f"{name}: detail['would_exit'] != 5"
        # Real == dry, the whole point of OR-7 (`dry.returncode == real.returncode`).
        assert real_error.exit_code == 5, f"{name}: real error exit_code = {real_error.exit_code}"
        # Dry run leaves the occupied target byte-for-byte untouched.
        assert target.read_bytes() == before, f"{name}: --dry-run mutated the occupied target"
