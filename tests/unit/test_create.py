"""PDF-10 `create` — plain text to PDF.

Page counts here are **arithmetically predicted** from (text, font, size, page
size, margin) and then compared against the produced file, rather than read back
out of the code that produced them.

v1 is plain text only. There is no Markdown test because there is no Markdown
path: it is the `[html]` extra and Phase 2, and a stubbed flag would be worse
than its absence.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_toolkit.errors import FailureError, NoInputError, UsageError  # noqa: E402
from pdf_toolkit.ops.compose import (  # noqa: E402
    BASE14_FONTS,
    DEFAULT_CREATE_MARGIN,
    DEFAULT_FONT,
    DEFAULT_SIZE,
    LEADING_RATIO,
    TAB_WIDTH,
    create_document,
    decode_utf8,
    lines_per_page,
    normalize_text,
    parse_length,
    parse_page_size,
    resolve_create_output,
    sanitize_text,
)
from pdf_toolkit.safety.policy import SafetyPolicy  # noqa: E402

LETTER = (612.0, 792.0)
MARGIN = 54.0


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


def _create(
    text: str,
    output: Path,
    *,
    font: str = DEFAULT_FONT,
    size: float = DEFAULT_SIZE,
    page_size: str = "letter",
    margin: str = DEFAULT_CREATE_MARGIN,
    title: str | None = None,
    policy: SafetyPolicy | None = None,
):
    return create_document(
        text,
        source="fixture.txt",
        output=output,
        font=font,
        size=size,
        page=parse_page_size(page_size),
        margin_pt=parse_length(margin, flag="--margin"),
        title=title,
        policy=policy if policy is not None else _policy(),
    )


def _pages(path: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(path)).pages)


def _text(path: Path, page_index: int = 0) -> str:
    from pypdf import PdfReader

    return PdfReader(str(path)).pages[page_index].extract_text()


# --------------------------------------------------------------------------- #
# The engine-free constant that must not drift from the engine.
# --------------------------------------------------------------------------- #


def test_the_base14_list_matches_the_engines_own() -> None:
    """`ops/compose.py` is engine-free, so it hard-codes the base-14 names. This
    is the tripwire that keeps that copy honest -- a test module MAY import the
    engine; the op may not."""
    from reportlab.pdfbase._fontdata import standardFonts

    assert set(BASE14_FONTS) == set(standardFonts)
    assert len(BASE14_FONTS) == 14


# --------------------------------------------------------------------------- #
# AC14 -- the smallest possible input is still a valid document.
# --------------------------------------------------------------------------- #


def test_ac14_one_byte_of_content_is_a_valid_one_page_pdf(tmp_path: Path) -> None:
    out = tmp_path / "hello.pdf"
    result = _create("x", out)
    assert result.exit_code == 0
    assert _pages(out) == 1
    assert "x" in _text(out)


# --------------------------------------------------------------------------- #
# AC15 -- empty input is a decision, not an accident.
# --------------------------------------------------------------------------- #


def test_ac15_empty_input_is_exit_4_and_writes_no_file(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    with pytest.raises(NoInputError) as caught:
        _create("", out)
    assert caught.value.exit_code == 4
    assert not out.exists()


def test_ac15_standard_input_with_no_destination_is_exit_2(tmp_path: Path) -> None:
    with pytest.raises(UsageError) as caught:
        resolve_create_output(Path("-"), None, from_stdin=True)
    assert caught.value.exit_code == 2


def test_a_file_operand_with_no_destination_writes_beside_the_input(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    assert resolve_create_output(source, None, from_stdin=False) == tmp_path / "notes.pdf"


def test_an_explicit_destination_always_wins(tmp_path: Path) -> None:
    chosen = tmp_path / "chosen.pdf"
    assert resolve_create_output(Path("-"), chosen, from_stdin=True) == chosen


def test_invalid_utf8_is_exit_1_and_names_the_byte_offset() -> None:
    raw = b"ok then \xff\xfe more"
    expected_offset = raw.index(b"\xff")  # computed, not counted by hand
    with pytest.raises(FailureError) as caught:
        decode_utf8(raw, source="notes.txt")
    assert caught.value.exit_code == 1
    assert f"byte offset {expected_offset}" in caught.value.message
    assert caught.value.path == "notes.txt"


def test_valid_utf8_decodes_unchanged() -> None:
    assert decode_utf8("héllo\n".encode(), source="notes.txt") == "héllo\n"


# --------------------------------------------------------------------------- #
# AC16/AC29 -- layout arithmetic, predicted then measured.
# --------------------------------------------------------------------------- #


def _expected_lines_per_page(size: float = DEFAULT_SIZE) -> int:
    """Computed here from the page geometry, independently of the op."""
    content_height = LETTER[1] - 2 * MARGIN
    return int(content_height // (size * LEADING_RATIO))


def test_the_line_budget_is_pure_geometry() -> None:
    assert _expected_lines_per_page() == 51
    assert lines_per_page(LETTER, MARGIN, DEFAULT_SIZE) == 51


@pytest.mark.parametrize("line_count", [1, 2, 51, 52, 102, 103, 120])
def test_ac16_the_page_count_is_the_arithmetically_predicted_one(
    tmp_path: Path, line_count: int
) -> None:
    per_page = _expected_lines_per_page()
    body = "\n".join(f"line {index:04}" for index in range(line_count))
    out = tmp_path / f"{line_count}.pdf"
    _create(body, out)
    assert _pages(out) == math.ceil(line_count / per_page)


def test_ac16_a_form_feed_forces_a_page_break(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    _create("first\fsecond\fthird", out)
    assert _pages(out) == 3
    assert "first" in _text(out, 0)
    assert "second" in _text(out, 1)
    assert "third" in _text(out, 2)


def test_ac16_a_tab_expands_to_four_spaces() -> None:
    assert TAB_WIDTH == 4
    assert normalize_text("a\tb") == "a" + " " * 4 + "b"


def test_ac16_an_unknown_font_is_exit_2_and_lists_the_accepted_names(tmp_path: Path) -> None:
    with pytest.raises(UsageError) as caught:
        _create("x", tmp_path / "out.pdf", font="Bogus")
    assert caught.value.exit_code == 2
    for name in BASE14_FONTS:
        assert name in caught.value.message


def test_ac16_the_title_reaches_the_document_information_dictionary(tmp_path: Path) -> None:
    from pypdf import PdfReader

    out = tmp_path / "out.pdf"
    _create("x", out, title="T")
    metadata = PdfReader(str(out)).metadata
    assert metadata is not None
    assert metadata.title == "T"


def test_ac16_unrepresentable_characters_render_as_question_marks_and_warn(
    tmp_path: Path,
) -> None:
    out = tmp_path / "out.pdf"
    result = _create("plain\nnihao 你好 ok", out)
    assert result.exit_code == 0
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert "2 character(s)" in warning
    assert "U+4F60" in warning
    assert "line 2" in warning
    assert "?" in _text(out)


def test_representable_text_produces_no_warning(tmp_path: Path) -> None:
    result = _create("plain ascii and a café", tmp_path / "out.pdf")
    assert result.warnings == ()


def test_a_size_of_zero_or_less_is_exit_2(tmp_path: Path) -> None:
    with pytest.raises(UsageError) as caught:
        _create("x", tmp_path / "out.pdf", size=0.0)
    assert caught.value.exit_code == 2


def test_from_image_is_refused_for_a_verb_that_has_no_image(tmp_path: Path) -> None:
    with pytest.raises(UsageError) as caught:
        _create("x", tmp_path / "out.pdf", page_size="from-image")
    assert caught.value.exit_code == 2


def test_a_margin_that_leaves_no_content_area_is_exit_2(tmp_path: Path) -> None:
    with pytest.raises(UsageError) as caught:
        _create("x", tmp_path / "out.pdf", margin="500pt")
    assert caught.value.exit_code == 2


# --------------------------------------------------------------------------- #
# Normalisation and encodability, on their own.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a\r\nb", "a\nb"),
        ("a\rb", "a\nb"),
        ("a\n", "a"),
        ("a\n\n", "a\n"),
        ("a", "a"),
        ("", ""),
    ],
)
def test_normalisation_is_exactly_the_documented_rules(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_sanitisation_counts_every_replacement_but_names_only_the_first() -> None:
    sanitized, warning = sanitize_text("a你b好c")
    assert sanitized == "a?b?c"
    assert warning is not None
    assert "2 character(s)" in warning
    assert "U+4F60" in warning


def test_sanitisation_of_clean_text_is_a_no_op() -> None:
    assert sanitize_text("plain") == ("plain", None)


def test_sanitisation_counts_lines_from_one() -> None:
    _sanitized, warning = sanitize_text("ok\nok\n€你")
    assert warning is not None
    assert "line 3" in warning


# --------------------------------------------------------------------------- #
# Wrapping -- the one thing the engine decides.
# --------------------------------------------------------------------------- #


def test_a_long_line_wraps_at_word_boundaries(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    body = " ".join(["word"] * 400)
    _create(body, out)
    assert _pages(out) >= 1
    # Every wrapped line still fits: the produced text carries no line longer
    # than the content box, measured with the same metrics the engine used.
    from reportlab.pdfbase.pdfmetrics import stringWidth

    content_width = LETTER[0] - 2 * MARGIN
    for line in _text(out).splitlines():
        assert stringWidth(line, DEFAULT_FONT, DEFAULT_SIZE) <= content_width + 1e-6


def test_a_single_token_longer_than_a_line_breaks_by_character(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    _create("M" * 400, out)
    extracted = _text(out).replace("\n", "")
    assert extracted.count("M") == 400


def test_a_content_box_narrower_than_one_glyph_terminates(tmp_path: Path) -> None:
    """The character break always consumes at least one character, so a
    pathologically narrow page finishes instead of looping forever."""
    out = tmp_path / "out.pdf"
    result = _create("MMMM", out, page_size="20x400", margin="8pt")
    assert result.exit_code == 0
    assert _pages(out) >= 1


# --------------------------------------------------------------------------- #
# Safety -- the same chokepoint every other verb uses.
# --------------------------------------------------------------------------- #


def test_a_dry_run_writes_nothing_but_still_reports_a_real_page_count(
    tmp_path: Path,
) -> None:
    out = tmp_path / "out.pdf"
    body = "\n".join(f"line {index}" for index in range(120))
    result = _create(body, out, policy=_policy(dry_run=True))
    assert result.exit_code == 0
    assert not out.exists()
    detail = result.items[0].to_dict()["detail"]
    assert isinstance(detail, dict)
    assert detail["page_count"] == math.ceil(120 / _expected_lines_per_page())
    assert detail["would_exit"] == 0


def test_a_dry_run_over_an_occupied_target_predicts_exit_5(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    out.write_bytes(b"%PDF-1.4\n%%EOF\n")
    occupied = out.read_bytes()
    result = _create("x", out, policy=_policy(dry_run=True))
    detail = result.items[0].to_dict()["detail"]
    assert isinstance(detail, dict)
    assert detail["would_exit"] == 5
    assert out.read_bytes() == occupied


def test_an_existing_target_without_force_is_exit_5(tmp_path: Path) -> None:
    from pdf_toolkit.errors import TargetExistsError

    out = tmp_path / "out.pdf"
    out.write_bytes(b"%PDF-1.4\n%%EOF\n")
    with pytest.raises(TargetExistsError) as caught:
        _create("x", out)
    assert caught.value.exit_code == 5
