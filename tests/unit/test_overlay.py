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

import sys
from pathlib import Path
from typing import Any

import pypdf
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from corpus import STAMP_MARKER  # noqa: E402
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
# --------------------------------------------------------------------------- #


def test_ac14_composite_layer_is_callable_directly_without_the_cli(corpus) -> None:
    engine = require_composite()
    layer = corpus.path("stamp_source").read_bytes()
    with engine.open_document(corpus.path("single_page")) as document:
        overlay_outcome = engine.composite_layer(
            document, layer=layer, pages=[1], position="overlay"
        )
        assert overlay_outcome.pages_composited == (1,)
    with engine.open_document(corpus.path("single_page")) as document:
        underlay_outcome = engine.composite_layer(
            document, layer=layer, pages=[1], position="underlay"
        )
        assert underlay_outcome.pages_composited == (1,)


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
