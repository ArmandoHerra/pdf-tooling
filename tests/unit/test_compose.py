"""PDF-10 `compose` — the byte-identity guarantee, and everything arranged so
it cannot break.

Every dimensional assertion here reads its number back out of the **produced
file** (`mediabox`, the XObject's `/Width`/`/Height`) and compares it against an
independently computed expectation. None reads a value back out of the code that
produced it: PDF-09 found a one-pixel defect that way, by running rather than by
reading, and this suite is written to be capable of the same.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from PIL import Image

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from helpers.pdfstream import embedded_image_streams, page_media_box  # noqa: E402
from pdf_toolkit.errors import FailureError, NoInputError, UsageError  # noqa: E402
from pdf_toolkit.ops.compose import (  # noqa: E402
    DEFAULT_FIT,
    EMBED_PASSTHROUGH,
    EMBED_REENCODE,
    ImageFacts,
    compose_document,
    inspect_image,
    jpeg_frame,
    parse_length,
    parse_page_size,
    plan_placements,
    resolve_single_output,
)
from pdf_toolkit.ports.compose import ImagePlacement, require_compose  # noqa: E402
from pdf_toolkit.safety.policy import SafetyPolicy  # noqa: E402

REPO_ROOT = TESTS_DIR.parent
SRC = REPO_ROOT / "src"

A4 = (595.276, 841.890)
LETTER = (612.0, 792.0)


# --------------------------------------------------------------------------- #
# Fixtures -- generated, never committed (PDF-06's posture).
# --------------------------------------------------------------------------- #


def _jpeg(
    path: Path,
    *,
    size: tuple[int, int] = (320, 240),
    color: tuple[int, ...] = (200, 30, 30),
    mode: str = "RGB",
    dpi: tuple[int, int] | None = None,
    progressive: bool = False,
) -> Path:
    options: dict[str, object] = {"quality": 85}
    if dpi is not None:
        options["dpi"] = dpi
    if progressive:
        options["progressive"] = True
    Image.new(mode, size, color).save(path, format="JPEG", **options)  # type: ignore[arg-type]
    return path


def _png(path: Path, *, size: tuple[int, int] = (320, 240)) -> Path:
    Image.new("RGB", size, (5, 5, 250)).save(path, format="PNG")
    return path


def _policy(*, dry_run: bool = False, force: bool = False) -> SafetyPolicy:
    return SafetyPolicy(
        dry_run=dry_run,
        force=force,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )


def _compose(
    sources: list[Path],
    output: Path,
    *,
    page_size: str = "a4",
    fit: str = DEFAULT_FIT,
    margin: str = "0",
    dpi: float | None = None,
    policy: SafetyPolicy | None = None,
):
    return compose_document(
        sources,
        output=output,
        page=parse_page_size(page_size),
        fit=fit,
        margin_pt=parse_length(margin, flag="--margin"),
        dpi=dpi,
        policy=policy if policy is not None else _policy(),
    )


def _assert_stream_is_the_input_file(pdf: Path, page_index: int, source: Path) -> None:
    """AC2, as one named assertion so AC5 can prove it is capable of failing."""
    streams = embedded_image_streams(pdf, page_index)
    assert len(streams) == 1, streams
    stream = streams[0]
    assert stream.filters[-1] == "/DCTDecode", stream.filters
    assert stream.dct_payload == source.read_bytes()


# --------------------------------------------------------------------------- #
# AC2/AC3/AC4 -- the guarantee, the pinned chain, and the canary.
# --------------------------------------------------------------------------- #


def test_ac2_a_baseline_jpeg_is_stored_byte_for_byte(tmp_path: Path) -> None:
    source = _jpeg(tmp_path / "photo.jpg")
    out = tmp_path / "out.pdf"
    result = _compose([source], out)
    assert result.exit_code == 0
    assert len(embedded_image_streams(out, 0)) == 1
    _assert_stream_is_the_input_file(out, 0, source)


def test_ac3_the_filter_chain_is_exactly_dctdecode(tmp_path: Path) -> None:
    """No A85 transport layer. The default is 1 and would ship the pair chain,
    so disabling it is a deliberate act, not a tidy-up."""
    source = _jpeg(tmp_path / "photo.jpg")
    out = tmp_path / "out.pdf"
    _compose([source], out)
    assert embedded_image_streams(out, 0)[0].filters == ("/DCTDecode",)


def test_ac3_the_stored_stream_and_the_payload_are_the_same_bytes(tmp_path: Path) -> None:
    """On a single-filter chain there is no transport layer to undo, so the
    stored bytes ARE the payload -- which is the whole point of pinning it."""
    source = _jpeg(tmp_path / "photo.jpg")
    out = tmp_path / "out.pdf"
    _compose([source], out)
    stream = embedded_image_streams(out, 0)[0]
    assert stream.raw == stream.dct_payload == source.read_bytes()


def test_ac4_canary_the_payload_is_a_jpeg_not_decoded_samples(tmp_path: Path) -> None:
    source = _jpeg(tmp_path / "photo.jpg")
    out = tmp_path / "out.pdf"
    _compose([source], out)
    payload = embedded_image_streams(out, 0)[0].dct_payload
    assert payload is not None
    assert payload[:3] == b"\xff\xd8\xff"
    assert payload[-2:] == b"\xff\xd9"


# --------------------------------------------------------------------------- #
# AC5 -- the negative control. The harness must be able to tell the two apart.
# --------------------------------------------------------------------------- #


def test_ac5_a_png_takes_the_flate_path_and_reports_it(tmp_path: Path) -> None:
    source = _png(tmp_path / "flat.png")
    out = tmp_path / "out.pdf"
    result = _compose([source], out)
    stream = embedded_image_streams(out, 0)[0]
    assert "/FlateDecode" in stream.filters
    assert "/DCTDecode" not in stream.filters
    assert stream.dct_payload is None
    detail = result.items[0].to_dict()["detail"]
    assert isinstance(detail, dict)
    assert detail["embed"] == EMBED_REENCODE
    assert detail["stream_bytes_identical"] is False


def test_ac5_the_byte_identity_assertion_is_capable_of_failing(tmp_path: Path) -> None:
    """The control that makes AC2 mean something: run AC2's OWN assertion
    against a page that was re-encoded and require it to go red. A green check
    that has never been seen red is worth nothing."""
    source = _png(tmp_path / "flat.png")
    out = tmp_path / "out.pdf"
    _compose([source], out)
    with pytest.raises(AssertionError):
        _assert_stream_is_the_input_file(out, 0, source)


# --------------------------------------------------------------------------- #
# AC6/AC27 -- path in, not pixels in; and the process-global toggle.
# --------------------------------------------------------------------------- #


def _drawn_handles(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Record what the renderer's own `drawImage` is handed, per page.

    This is the real seam: what the OP hands the renderer is what decides
    whether the original compressed bytes survive, and (see the adapter's
    mechanic 2) whether the XObject cache is keyed on the filename or on the
    decoded pixels.
    """
    from reportlab.pdfgen import canvas

    seen: list[object] = []
    original = canvas.Canvas.drawImage

    def spy(self: object, image: object, *args: object, **kwargs: object) -> object:
        seen.append(image)
        return original(self, image, *args, **kwargs)

    monkeypatch.setattr(canvas.Canvas, "drawImage", spy)
    return seen


def test_ac6_a_passthrough_jpeg_reaches_the_renderer_as_a_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _drawn_handles(monkeypatch)
    source = _jpeg(tmp_path / "photo.jpg")
    _compose([source], tmp_path / "out.pdf")
    assert seen == [str(source)]
    assert not isinstance(seen[0], Image.Image)


def test_ac6_a_reencoded_input_reaches_the_renderer_as_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of AC6: the distinction is real, not an accident of the
    one input type the passthrough test happens to use."""
    from reportlab.lib.utils import ImageReader

    seen = _drawn_handles(monkeypatch)
    _compose([_png(tmp_path / "flat.png")], tmp_path / "out.pdf")
    assert len(seen) == 1
    assert isinstance(seen[0], ImageReader)


def _pixel_identical_variant(source: Path, target: Path) -> Path:
    """A file with the SAME decoded pixels and DIFFERENT compressed bytes.

    Built by inserting a JPEG comment segment after the start-of-image marker,
    which every decoder skips. Realistic (metadata differs between two scans of
    one page) and, crucially, exactly the shape that made the renderer's
    pixel-keyed XObject cache collide on the real corpus.
    """
    raw = source.read_bytes()
    payload = b"pdf-toolkit variant"
    comment = b"\xff\xfe" + (2 + len(payload)).to_bytes(2, "big") + payload
    target.write_bytes(raw[:2] + comment + raw[2:])
    return target


def test_two_inputs_with_identical_pixels_keep_their_own_bytes(tmp_path: Path) -> None:
    """REGRESSION (found on the 108-scan corpus, reproduced here without it).

    The renderer de-duplicates image XObjects by a digest computed from the
    DECODED PIXELS when it is handed an `ImageReader`. Two files whose pixels
    match but whose compressed bytes do not therefore collapse onto one XObject,
    and the second page silently renders the first file's bytes -- with the
    filter chain still reading `/DCTDecode` and the item still claiming a
    passthrough. Keying on the filename, by handing over the path itself, is the
    fix; this test is what stops it regressing.
    """
    first = _jpeg(tmp_path / "first.jpg", size=(160, 120), color=(90, 140, 200))
    second = _pixel_identical_variant(first, tmp_path / "second.jpg")

    with Image.open(first) as a, Image.open(second) as b:
        assert a.convert("RGB").tobytes() == b.convert("RGB").tobytes(), (
            "fixture is not pixel-identical"
        )
    assert first.read_bytes() != second.read_bytes(), "fixture bytes are not different"

    out = tmp_path / "out.pdf"
    _compose([first, second], out)
    _assert_stream_is_the_input_file(out, 0, first)
    _assert_stream_is_the_input_file(out, 1, second)
    assert embedded_image_streams(out, 0)[0].name != embedded_image_streams(out, 1)[0].name


def test_ac6_the_adapter_contains_no_image_transform_or_save_call() -> None:
    adapter = (SRC / "pdf_toolkit" / "adapters" / "reportlab_compose.py").read_text()
    pattern = re.compile(r"Image\.(convert|resize|rotate|thumbnail)|\.save\(")
    assert pattern.findall(adapter) == []


def test_ac27_the_a85_toggle_is_restored_after_a_successful_compose(tmp_path: Path) -> None:
    from reportlab import rl_config

    before = rl_config.useA85
    _compose([_jpeg(tmp_path / "photo.jpg")], tmp_path / "out.pdf")
    assert rl_config.useA85 == before


def test_ac27_the_a85_toggle_is_restored_when_the_render_raises(tmp_path: Path) -> None:
    """Process-global mutable state left set is a defect even while the tests
    pass. Proven with a forced exception, not by reading the `finally`."""
    from reportlab import rl_config

    engine = require_compose(capability="compose")
    before = rl_config.useA85
    broken = ImagePlacement(
        source=tmp_path / "does-not-exist.jpg",
        raster=None,
        page_size=A4,
        draw_box=(0.0, 0.0, 10.0, 10.0),
        clip_box=None,
    )
    with pytest.raises(Exception):  # noqa: B017 - the renderer's own error type
        engine.compose_images([broken], out=(tmp_path / "sink.pdf").open("wb"))
    assert rl_config.useA85 == before


def test_ac27_the_toggle_is_set_and_restored_inside_one_context_manager() -> None:
    adapter = (SRC / "pdf_toolkit" / "adapters" / "reportlab_compose.py").read_text()
    body = adapter.split("def _single_filter_chain")[1].split("\ndef ")[0]
    assert "rl_config.useA85 = 0" in body
    assert "finally:" in body
    assert "rl_config.useA85 = previous" in body
    # The scope encloses the draw loop, not merely the canvas construction.
    render = adapter.split("def compose_images")[1].split("\n    def ")[0]
    manager = render.index("with _single_filter_chain():")
    assert manager < render.index("drawImage")


# --------------------------------------------------------------------------- #
# AC7 -- geometry is graphics state, not pixels.
# --------------------------------------------------------------------------- #


def _page_content(pdf: Path, page_index: int) -> str:
    from pypdf import PdfReader

    return PdfReader(str(pdf)).pages[page_index].get_contents().get_data().decode("latin-1")


def test_ac7_fit_cover_clips_and_the_bytes_still_survive(tmp_path: Path) -> None:
    source = _jpeg(tmp_path / "wide.jpg", size=(800, 200))
    out = tmp_path / "out.pdf"
    _compose([source], out, page_size="a4", fit="cover")
    _assert_stream_is_the_input_file(out, 0, source)
    # The renderer emits the even-odd form `W* n`; an assertion pinned to the
    # literal `W n` would fail a CORRECT implementation.
    assert re.search(r"\bW\*?\s+n\b", _page_content(out, 0)) is not None


# --------------------------------------------------------------------------- #
# AC8/AC29 -- the page-size grammar, measured from the artefact.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("a4", A4),
        ("A4", A4),
        ("letter", LETTER),
        ("612x792", LETTER),
        ("210x297mm", A4),
        ("8.5x11in", LETTER),
        ("21x29.7cm", A4),
    ],
)
def test_ac8_page_sizes_parse_and_land_in_the_produced_file(
    tmp_path: Path, spec: str, expected: tuple[float, float]
) -> None:
    out = tmp_path / f"{spec.replace('.', '_')}.pdf"
    _compose([_jpeg(tmp_path / "photo.jpg")], out, page_size=spec)
    assert page_media_box(out, 0) == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize("spec", ["8.5x11xyz", "a5", "612", "x792", "-1x2", "0x0"])
def test_ac8_a_malformed_page_size_is_exit_2_and_quotes_the_offender(spec: str) -> None:
    with pytest.raises(UsageError) as caught:
        parse_page_size(spec)
    assert caught.value.exit_code == 2
    assert repr(spec) in caught.value.message


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0", 0.0), ("54", 54.0), ("54pt", 54.0), ("25.4mm", 72.0), ("2.54cm", 72.0), ("1in", 72.0)],
)
def test_margins_parse_in_every_unit(raw: str, expected: float) -> None:
    assert parse_length(raw, flag="--margin") == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize("raw", ["", "abc", "10px", "1.2.3"])
def test_a_malformed_margin_is_exit_2_and_quotes_the_offender(raw: str) -> None:
    with pytest.raises(UsageError) as caught:
        parse_length(raw, flag="--margin")
    assert caught.value.exit_code == 2
    assert repr(raw) in caught.value.message


# --------------------------------------------------------------------------- #
# AC9/AC29 -- from-image, per page, including a NON-exact float conversion.
# --------------------------------------------------------------------------- #


def test_ac9_from_image_sizes_every_page_to_its_own_image(tmp_path: Path) -> None:
    """Three differently-sized images, three differently-sized pages -- not
    normalised to the first, the largest, or a bounding box. The 1240 px @ 150
    dpi case is deliberately a NON-exact float: 1240 * 72 / 150 is 595.2, and
    956 * 72 / 300 is 229.44, so the float path is exercised rather than assumed
    (AC29)."""
    cases = [
        (tmp_path / "a.jpg", (2550, 3300), 300.0, (612.0, 792.0)),
        (tmp_path / "b.jpg", (1240, 1754), 150.0, (595.2, 841.92)),
        (tmp_path / "c.jpg", (956, 1435), 300.0, (229.44, 344.4)),
    ]
    out = tmp_path / "out.pdf"
    for path, size, _dpi, _expected in cases:
        _jpeg(path, size=size)

    for path, _size, dpi, expected in cases:
        single = tmp_path / f"{path.stem}.pdf"
        _compose([path], single, page_size="from-image", dpi=dpi)
        assert page_media_box(single, 0) == pytest.approx(expected, abs=0.01), path.name

    # All three in one document, each page still its own size.
    result = _compose([case[0] for case in cases], out, page_size="from-image", dpi=300.0)
    assert result.exit_code == 0
    assert [page_media_box(out, index) for index in range(3)] == [
        pytest.approx((612.0, 792.0), abs=0.01),
        pytest.approx((297.6, 420.96), abs=0.01),
        pytest.approx((229.44, 344.4), abs=0.01),
    ]


def test_ac9_from_image_adds_the_margin_on_all_four_sides(tmp_path: Path) -> None:
    source = _jpeg(tmp_path / "a.jpg", size=(720, 360))
    out = tmp_path / "out.pdf"
    _compose([source], out, page_size="from-image", dpi=72.0, margin="18pt")
    assert page_media_box(out, 0) == pytest.approx((720 + 36, 360 + 36), abs=0.01)


def test_ac9_a_non_default_fit_under_from_image_warns_rather_than_being_ignored(
    tmp_path: Path,
) -> None:
    result = _compose(
        [_jpeg(tmp_path / "a.jpg")],
        tmp_path / "out.pdf",
        page_size="from-image",
        fit="cover",
    )
    assert any("--fit cover" in warning for warning in result.warnings)


def test_ac9_the_default_fit_under_from_image_is_silent(tmp_path: Path) -> None:
    result = _compose([_jpeg(tmp_path / "a.jpg")], tmp_path / "out.pdf", page_size="from-image")
    assert result.warnings == ()


# --------------------------------------------------------------------------- #
# AC10 -- the three fit modes, from the placement geometry the op returns.
# --------------------------------------------------------------------------- #


def _facts(tmp_path: Path, size: tuple[int, int], dpi: float = 72.0) -> ImageFacts:
    return inspect_image(_jpeg(tmp_path / f"{size[0]}x{size[1]}.jpg", size=size), dpi_flag=dpi)


def test_ac10_contain_fits_inside_the_content_box_and_centres(tmp_path: Path) -> None:
    fact = _facts(tmp_path, (800, 200))
    (placement,) = plan_placements(
        [fact], page=parse_page_size("letter"), fit="contain", margin_pt=0.0
    )
    _x, _y, width, height = placement.draw_box
    assert width <= LETTER[0] + 1e-9 and height <= LETTER[1] + 1e-9
    assert (width == pytest.approx(LETTER[0])) ^ (height == pytest.approx(LETTER[1]))
    assert placement.draw_box[0] == pytest.approx((LETTER[0] - width) / 2)
    assert placement.draw_box[1] == pytest.approx((LETTER[1] - height) / 2)
    assert placement.clip_box is None


def test_ac10_cover_fills_the_content_box_and_clips(tmp_path: Path) -> None:
    fact = _facts(tmp_path, (800, 200))
    (placement,) = plan_placements(
        [fact], page=parse_page_size("letter"), fit="cover", margin_pt=0.0
    )
    _x, _y, width, height = placement.draw_box
    assert width >= LETTER[0] - 1e-9 and height >= LETTER[1] - 1e-9
    assert (width == pytest.approx(LETTER[0])) ^ (height == pytest.approx(LETTER[1]))
    assert placement.clip_box == (0.0, 0.0, LETTER[0], LETTER[1])


def test_ac10_stretch_matches_the_content_box_exactly(tmp_path: Path) -> None:
    fact = _facts(tmp_path, (800, 200))
    (placement,) = plan_placements(
        [fact], page=parse_page_size("letter"), fit="stretch", margin_pt=36.0
    )
    assert placement.draw_box == pytest.approx((36.0, 36.0, LETTER[0] - 72.0, LETTER[1] - 72.0))


def test_contain_scales_up_as_well_as_down(tmp_path: Path) -> None:
    fact = _facts(tmp_path, (100, 100))
    (placement,) = plan_placements(
        [fact], page=parse_page_size("letter"), fit="contain", margin_pt=0.0
    )
    assert placement.draw_box[2] > 100.0


def test_a_margin_that_leaves_no_content_area_is_exit_2(tmp_path: Path) -> None:
    fact = _facts(tmp_path, (100, 100))
    with pytest.raises(UsageError) as caught:
        plan_placements([fact], page=parse_page_size("letter"), fit="contain", margin_pt=400.0)
    assert caught.value.exit_code == 2


# --------------------------------------------------------------------------- #
# AC11 -- argv order, and nothing else.
# --------------------------------------------------------------------------- #


def test_ac11_pages_come_out_in_argv_order_duplicates_included(tmp_path: Path) -> None:
    a = _jpeg(tmp_path / "a.jpg", color=(10, 200, 40))
    b = _jpeg(tmp_path / "b.jpg", color=(200, 30, 30))
    out = tmp_path / "out.pdf"
    result = _compose([b, a, b], out)

    from pypdf import PdfReader

    assert len(PdfReader(str(out)).pages) == 3
    for index, source in enumerate([b, a, b]):
        _assert_stream_is_the_input_file(out, index, source)
    assert [item.input for item in result.items] == [str(b), str(a), str(b)]
    assert [item.to_dict()["detail"]["page"] for item in result.items] == [1, 2, 3]  # type: ignore[index]


def test_the_renderer_deduplicates_identical_images_but_pages_still_differ(
    tmp_path: Path,
) -> None:
    """Recorded because it is the trap a global XObject count would fall into:
    composing one file twice yields ONE XObject referenced from two pages."""
    b = _jpeg(tmp_path / "b.jpg")
    out = tmp_path / "out.pdf"
    _compose([b, b], out)
    assert embedded_image_streams(out, 0)[0].name == embedded_image_streams(out, 1)[0].name


def test_a_directory_operand_is_exit_2_and_names_the_shell_glob(tmp_path: Path) -> None:
    with pytest.raises(UsageError) as caught:
        inspect_image(tmp_path, dpi_flag=None)
    assert caught.value.exit_code == 2
    assert "shell" in caught.value.message


def test_a_pdf_operand_is_exit_2_and_points_at_merge(tmp_path: Path) -> None:
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF-1.7\n%%EOF\n")
    with pytest.raises(UsageError) as caught:
        inspect_image(source, dpi_flag=None)
    assert caught.value.exit_code == 2
    assert "merge" in caught.value.message


def test_a_nonexistent_operand_is_exit_4(tmp_path: Path) -> None:
    with pytest.raises(NoInputError) as caught:
        inspect_image(tmp_path / "nope.jpg", dpi_flag=None)
    assert caught.value.exit_code == 4


def test_a_file_that_is_not_a_raster_is_exit_1_and_names_the_path(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("this is not an image at all")
    with pytest.raises(FailureError) as caught:
        inspect_image(source, dpi_flag=None)
    assert caught.value.exit_code == 1
    assert caught.value.path == str(source)


def test_zero_operands_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        _compose([], tmp_path / "out.pdf")


# --------------------------------------------------------------------------- #
# AC12/AC31 -- honest per-input reporting, and the two JPEG special cases.
# --------------------------------------------------------------------------- #


def _detail(result, index: int = 0) -> dict:
    detail = result.items[index].to_dict()["detail"]
    assert isinstance(detail, dict)
    return detail


def test_ac12_every_item_reports_which_path_it_took(tmp_path: Path) -> None:
    jpeg = _jpeg(tmp_path / "a.jpg")
    png = _png(tmp_path / "b.png")
    result = _compose([jpeg, png], tmp_path / "out.pdf")
    first, second = _detail(result, 0), _detail(result, 1)
    assert first["embed"] == EMBED_PASSTHROUGH
    assert first["stream_bytes_identical"] is True
    assert first["source_format"] == "JPEG"
    assert first["page"] == 1
    assert second["embed"] == EMBED_REENCODE
    assert second["stream_bytes_identical"] is False
    assert second["source_format"] == "PNG"
    assert second["page"] == 2
    # A PNG on the Flate path is normal and is NOT warned about.
    assert result.warnings == ()


@pytest.mark.parametrize(
    ("flag", "written_dpi", "expected", "source"),
    [
        (300.0, None, 300.0, "flag"),
        (None, (150, 150), 150.0, "image"),
        (None, None, 72.0, "default"),
    ],
)
def test_ac12_dpi_source_reports_which_of_the_three_rules_fired(
    tmp_path: Path,
    flag: float | None,
    written_dpi: tuple[int, int] | None,
    expected: float,
    source: str,
) -> None:
    image = _jpeg(tmp_path / "a.jpg", dpi=written_dpi)
    result = _compose([image], tmp_path / "out.pdf", dpi=flag)
    detail = _detail(result)
    assert detail["dpi"] == pytest.approx(expected)
    assert detail["dpi_source"] == source


def test_ac12_a_progressive_jpeg_is_diverted_and_warned_about(tmp_path: Path) -> None:
    """The renderer sniffs nothing and would pass this through byte-identically;
    the diversion is the OP's decision, and the user is told about it."""
    source = _jpeg(tmp_path / "prog.jpg", progressive=True)
    out = tmp_path / "out.pdf"
    result = _compose([source], out)
    detail = _detail(result)
    assert detail["embed"] == EMBED_REENCODE
    assert detail["stream_bytes_identical"] is False
    assert any("prog.jpg" in w and "progressive" in w for w in result.warnings)
    stream = embedded_image_streams(out, 0)[0]
    assert stream.filters == ("/FlateDecode",)
    assert stream.dct_payload is None


def test_ac31_a_cmyk_jpeg_passes_through_with_its_inversion_array(tmp_path: Path) -> None:
    """Diverting CMYK would trade byte-identity away for ZERO correctness gain:
    the renderer already emits /DeviceCMYK and the Adobe /Decode array, so the
    page is right AND the bytes survive. No warning -- a warning on a path that
    works is noise."""
    source = _jpeg(tmp_path / "cmyk.jpg", mode="CMYK", color=(10, 200, 40, 5))
    out = tmp_path / "out.pdf"
    result = _compose([source], out)
    stream = embedded_image_streams(out, 0)[0]
    assert stream.filters == ("/DCTDecode",)
    assert stream.dct_payload == source.read_bytes()
    assert stream.colorspace == "/DeviceCMYK"
    assert stream.decode == (1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0)
    detail = _detail(result)
    assert detail["embed"] == EMBED_PASSTHROUGH
    assert detail["stream_bytes_identical"] is True
    assert detail["colorspace"] == "cmyk"
    assert result.warnings == ()


def test_a_greyscale_jpeg_passes_through_as_devicegray(tmp_path: Path) -> None:
    source = _jpeg(tmp_path / "gray.jpg", mode="L", color=(128,))
    out = tmp_path / "out.pdf"
    result = _compose([source], out)
    stream = embedded_image_streams(out, 0)[0]
    assert stream.filters == ("/DCTDecode",)
    assert stream.colorspace == "/DeviceGray"
    assert stream.dct_payload == source.read_bytes()
    assert _detail(result)["colorspace"] == "gray"


def test_ac29_the_xobject_carries_the_source_pixel_dimensions(tmp_path: Path) -> None:
    source = _jpeg(tmp_path / "a.jpg", size=(1240, 1754))
    out = tmp_path / "out.pdf"
    _compose([source], out, page_size="from-image", dpi=150.0)
    stream = embedded_image_streams(out, 0)[0]
    assert (stream.width, stream.height) == (1240, 1754)


# --------------------------------------------------------------------------- #
# The frame sniffer itself -- the decision the renderer refuses to make.
# --------------------------------------------------------------------------- #


def test_jpeg_frame_reads_the_marker_and_component_count(tmp_path: Path) -> None:
    baseline = _jpeg(tmp_path / "rgb.jpg").read_bytes()
    grey = _jpeg(tmp_path / "grey.jpg", mode="L", color=(128,)).read_bytes()
    cmyk = _jpeg(tmp_path / "cmyk.jpg", mode="CMYK", color=(1, 2, 3, 4)).read_bytes()
    progressive = _jpeg(tmp_path / "prog.jpg", progressive=True).read_bytes()
    assert jpeg_frame(baseline) == (0xC0, 3)
    assert jpeg_frame(grey) == (0xC0, 1)
    assert jpeg_frame(cmyk) == (0xC0, 4)
    assert jpeg_frame(progressive) == (0xC2, 3)


@pytest.mark.parametrize(
    "data",
    [b"", b"\xff\xd8", b"not a jpeg at all", b"\xff\xd8\xff\xd9", b"\xff\xd8\xff\xc0\x00\x01"],
)
def test_jpeg_frame_returns_none_rather_than_guessing(data: bytes) -> None:
    assert jpeg_frame(data) is None


# --------------------------------------------------------------------------- #
# AC13/AC21 -- the `detail` seam is additive, and provably so.
# --------------------------------------------------------------------------- #


def _item_kwargs() -> dict[str, object]:
    return {
        "input": "in",
        "output": "out",
        "ok": True,
        "exit_code": 0,
        "message": None,
        "bytes_before": None,
        "bytes_after": None,
        "duration_ms": 0,
    }


def test_ac21_to_dict_without_detail_has_exactly_the_eight_original_keys() -> None:
    from pdf_toolkit.models import ItemResult

    payload = ItemResult(**_item_kwargs()).to_dict()  # type: ignore[arg-type]
    assert list(payload) == [
        "input",
        "output",
        "ok",
        "exit_code",
        "message",
        "bytes_before",
        "bytes_after",
        "duration_ms",
    ]


def test_ac21_to_dict_with_detail_has_nine_keys_and_detail_is_last() -> None:
    from pdf_toolkit.models import ItemResult

    payload = ItemResult(**_item_kwargs(), detail={"page": 1}).to_dict()  # type: ignore[arg-type]
    assert len(payload) == 9
    assert list(payload)[-1] == "detail"
    assert payload["detail"] == {"page": 1}


def test_ac21_detail_defaults_to_none_so_no_existing_construction_site_changes() -> None:
    from pdf_toolkit.models import ItemResult

    assert ItemResult(**_item_kwargs()).detail is None  # type: ignore[arg-type]


def test_ac13_schema_version_is_unchanged() -> None:
    from pdf_toolkit.models import SCHEMA_VERSION

    assert SCHEMA_VERSION == 1


# --------------------------------------------------------------------------- #
# AC19/AC23 -- the write chokepoint, and an honest dry run.
# --------------------------------------------------------------------------- #


def test_ac23_the_engine_refuses_anything_that_is_not_a_binary_stream(tmp_path: Path) -> None:
    engine = require_compose(capability="compose")
    placement = ImagePlacement(
        source=_jpeg(tmp_path / "a.jpg"),
        raster=None,
        page_size=A4,
        draw_box=(0.0, 0.0, 10.0, 10.0),
        clip_box=None,
    )
    with pytest.raises(TypeError):
        engine.compose_images([placement], out=str(tmp_path / "out.pdf"))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        engine.render_text("x", layout=_layout(), out=str(tmp_path / "out.pdf"))  # type: ignore[arg-type]


def _layout():
    from pdf_toolkit.ports.compose import TextLayout

    return TextLayout(
        font="Helvetica",
        size=11.0,
        leading=13.2,
        page_size=LETTER,
        margin_pt=54.0,
        lines_per_page=51,
        title=None,
    )


def test_ac23_the_engine_refuses_an_empty_placement_list(tmp_path: Path) -> None:
    engine = require_compose(capability="compose")
    with pytest.raises(ValueError):
        engine.compose_images([], out=(tmp_path / "out.pdf").open("wb"))


def test_ac19_a_dry_run_writes_nothing_and_leaves_no_temp_file(tmp_path: Path) -> None:
    source = _jpeg(tmp_path / "a.jpg")
    out = tmp_path / "out.pdf"
    before = sorted(p.name for p in tmp_path.iterdir())
    result = _compose([source], out, policy=_policy(dry_run=True))
    assert result.exit_code == 0
    assert result.dry_run is True
    assert not out.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert list(tmp_path.glob(".pdftoolkit-*")) == []


def test_ac23_a_dry_run_over_an_occupied_target_predicts_exit_5(tmp_path: Path) -> None:
    """`_plan()` runs in BOTH modes, so the preview predicts the refusal instead
    of returning early -- a preview that lies is worse than no preview."""
    source = _jpeg(tmp_path / "a.jpg")
    out = tmp_path / "out.pdf"
    out.write_bytes(b"%PDF-1.4\n%%EOF\n")
    occupied = out.read_bytes()
    result = _compose([source], out, policy=_policy(dry_run=True))
    assert _detail(result)["would_exit"] == 5
    assert result.items[0].exit_code == 5
    assert out.read_bytes() == occupied


def test_ac19_an_existing_target_without_force_is_exit_5(tmp_path: Path) -> None:
    from pdf_toolkit.errors import TargetExistsError

    source = _jpeg(tmp_path / "a.jpg")
    out = tmp_path / "out.pdf"
    out.write_bytes(b"%PDF-1.4\n%%EOF\n")
    with pytest.raises(TargetExistsError) as caught:
        _compose([source], out)
    assert caught.value.exit_code == 5


def test_ac19_force_overwrites_and_the_result_is_a_real_pdf(tmp_path: Path) -> None:
    from pypdf import PdfReader

    source = _jpeg(tmp_path / "a.jpg")
    out = tmp_path / "out.pdf"
    out.write_bytes(b"%PDF-1.4\n%%EOF\n")
    _compose([source], out, policy=_policy(force=True))
    assert len(PdfReader(str(out)).pages) == 1


def test_ac23_the_op_module_opens_nothing_for_writing() -> None:
    """Walked as an AST, not grepped as text: that module's own docstring quotes
    the very call names it must not make, and a text grep flags the prohibition
    as if it were the violation."""
    import ast

    tree = ast.parse((SRC / "pdf_toolkit" / "ops" / "compose.py").read_text())
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name == "Canvas":
            offenders.append(ast.unparse(node))
        if name == "open":
            for argument in node.args:
                if (
                    isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                    and set(argument.value) & set("wax+")
                ):
                    offenders.append(ast.unparse(node))
    assert offenders == []


# --------------------------------------------------------------------------- #
# AC22 -- OR-3 is consumed, not re-implemented.
# --------------------------------------------------------------------------- #


def test_ac22_both_verbs_declare_exactly_the_single_output_flag() -> None:
    import pdf_toolkit.cli.cmd_compose  # noqa: F401
    import pdf_toolkit.cli.cmd_create  # noqa: F401
    from pdf_toolkit.cli.common import consumed_output_flags

    assert consumed_output_flags("pdf_toolkit.cli.cmd_compose") == ("--output",)
    assert consumed_output_flags("pdf_toolkit.cli.cmd_create") == ("--output",)


@pytest.mark.parametrize("module", ["cmd_compose", "cmd_create"])
def test_ac22_neither_command_module_re_implements_the_refusal(module: str) -> None:
    """There must be exactly ONE refusal path in the product -- the shared check
    in `cli/common.py`. A duplicate here would be a defect even while it agreed,
    because it is the second path that can later disagree.

    The three flags these verbs DECLINE appear nowhere in either module, and
    neither does the short spelling of the one they consume. `--output` itself
    appears exactly once and only inside the mandatory `consumes=` declaration:
    the declaration is what makes the refusal happen, so a grep that forbade it
    outright could not be satisfied by any verb at all -- the shipped
    `cmd_rasterize.py` does not satisfy that form either (five matches at
    `26f4c79`). Reported as a spec defect; asserted here in the strongest form
    that is actually satisfiable.
    """
    text = (SRC / "pdf_toolkit" / "cli" / f"{module}.py").read_text()
    for flag in ("--out-dir", "--name", "--in-place", '"-O"', "'-O'"):
        assert flag not in text, f"{module} names {flag}"
    assert text.count("--output") == 1
    assert 'global_options(consumes=("--output",))' in text
    for attribute in ("config.out_dir", "config.name", "config.in_place"):
        assert attribute not in text, f"{module} reads {attribute}"


def test_ac22_the_shared_option_layer_is_not_edited() -> None:
    """A widened OUTPUT_FLAGS or a second refusal path would show up here."""
    from pdf_toolkit.cli.common import OUTPUT_FLAGS

    assert OUTPUT_FLAGS == ("--output", "--out-dir", "--name", "--in-place")


# --------------------------------------------------------------------------- #
# AC26 -- the live registry classification, at the EXISTING hop bound.
# --------------------------------------------------------------------------- #


def test_ac26_both_verbs_classify_as_mutating_at_the_existing_hop_bound() -> None:
    import registry

    assert registry._MAX_IMPORT_HOPS == 4
    verbs = {verb.name: verb for verb in registry.discover_verbs()}
    for name in ("compose", "create"):
        assert verbs[name].is_mutating is True
        assert verbs[name].is_page_addressing is False
        assert verbs[name].consumes == ("--output",)
    assert registry.reaches_atomic_writer("pdf_toolkit.cli.cmd_compose", max_hops=2) is True
    assert registry.reaches_atomic_writer("pdf_toolkit.cli.cmd_create", max_hops=2) is True


# --------------------------------------------------------------------------- #
# AC30 -- no forbidden tool is named anywhere under src/.
# --------------------------------------------------------------------------- #


def test_ac30_no_forbidden_engine_name_appears_in_this_specs_own_files() -> None:
    """The prohibition and the advertisement look identical to a grep, and this
    spec's headline feature is reproducing a forbidden tool's differentiator --
    so the capability is described and the tool is never named."""
    from test_cli_spine import FORBIDDEN_NAMES

    owned = [
        SRC / "pdf_toolkit" / "ops" / "compose.py",
        SRC / "pdf_toolkit" / "cli" / "cmd_compose.py",
        SRC / "pdf_toolkit" / "cli" / "cmd_create.py",
        SRC / "pdf_toolkit" / "adapters" / "reportlab_compose.py",
        SRC / "pdf_toolkit" / "ports" / "compose.py",
    ]
    offenders = [
        f"{path.name}: {name}"
        for path in owned
        for name in FORBIDDEN_NAMES
        if name in path.read_text().lower()
    ]
    assert offenders == []


# --------------------------------------------------------------------------- #
# The `-O`-omitted case (Design §11).
# --------------------------------------------------------------------------- #


def test_one_operand_without_an_explicit_target_writes_beside_the_input(tmp_path: Path) -> None:
    source = _jpeg(tmp_path / "photo.jpg")
    assert resolve_single_output([source], None, verb="compose") == tmp_path / "photo.pdf"


def test_two_operands_without_an_explicit_target_is_exit_2(tmp_path: Path) -> None:
    with pytest.raises(UsageError) as caught:
        resolve_single_output([tmp_path / "a.jpg", tmp_path / "b.jpg"], None, verb="compose")
    assert caught.value.exit_code == 2


def test_an_explicit_target_always_wins(tmp_path: Path) -> None:
    chosen = tmp_path / "chosen.pdf"
    assert resolve_single_output([tmp_path / "a.jpg"], chosen, verb="compose") == chosen
