"""``ops/merge.py`` — the path:range disambiguation, per-input selection, and
the three ``--bookmarks`` modes (Design §D1-D3, AC2-AC3, AC6, AC11-AC14).

Runs in-process against the framework-free ops layer, so a table-driven
assertion never has to shell out per case. AC1's own round-trip lives in
``tests/integration/test_split_merge_roundtrip.py``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from pdf_toolkit import errors
from pdf_toolkit.ops import merge as merge_ops
from pdf_toolkit.safety.policy import SafetyPolicy

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdfium_text import page_text  # noqa: E402


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


# --------------------------------------------------------------------------- #
# AC7 — no grammar re-implementation
# --------------------------------------------------------------------------- #


def test_ops_merge_does_not_reimplement_the_grammar() -> None:
    module_path = Path(__file__).resolve().parents[2] / "src" / "pdf_toolkit" / "ops" / "merge.py"
    text = module_path.read_text()
    assert "re.compile" not in text
    for literal in ("even", "odd", "first", "last", "all"):
        assert f'"{literal}"' not in text
        assert f"'{literal}'" not in text
    tree = ast.parse(text)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "pdf_toolkit.ops.pagerange"
        for alias in node.names
    }
    assert {"is_valid_spec", "parse"} <= imported


# --------------------------------------------------------------------------- #
# D2 — path:range disambiguation, at the pure-text level (AC11)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected_path", "expected_selection"),
    [
        ("notes:draft.pdf", "notes:draft.pdf", None),
        ("a.pdf:1-3", "a.pdf", "1-3"),
        (r"C:\docs\a.pdf:1-3", r"C:\docs\a.pdf", "1-3"),
        ("a:1-3:all", "a:1-3", "all"),
        ("plain.pdf", "plain.pdf", None),
        ("a.pdf:even", "a.pdf", "even"),
        ("a.pdf:", "a.pdf:", None),  # empty tail -- not a valid spec
    ],
)
def test_split_input_spec_disambiguates_on_the_last_valid_colon(
    raw: str, expected_path: str, expected_selection: str | None
) -> None:
    path_text, selection = merge_ops.split_input_spec(raw)
    assert path_text == expected_path
    assert selection == expected_selection


def test_split_input_spec_nonexistent_left_half_is_reported_via_resolve(
    tmp_path: Path,
) -> None:
    with pytest.raises(errors.NoInputError) as excinfo:
        merge_ops.resolve_merge_inputs((str(tmp_path / "missing.pdf:1-3"),))
    message = str(excinfo.value)
    assert str(tmp_path / "missing.pdf") in message
    assert ":all" in message


# --------------------------------------------------------------------------- #
# AC3 / AC6 — page selection through merge, table-driven
# --------------------------------------------------------------------------- #


def _make_source(directory: Path, pages: int = 10) -> Path:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "src.pdf"
    made = canvas.Canvas(str(path), pagesize=letter)
    for number in range(1, pages + 1):
        made.drawString(72, 700, f"src page {number}")
        made.showPage()
    made.save()
    return path


@pytest.mark.parametrize(
    ("token", "expected_pages"),
    [
        ("5", [5]),
        ("1-3", [1, 2, 3]),
        ("5-1", [5, 4, 3, 2, 1]),
        ("9-", [9, 10]),
        ("-1", [10]),
        ("first", [1]),
        ("last", [10]),
        ("even", [2, 4, 6, 8, 10]),
        ("odd", [1, 3, 5, 7, 9]),
        ("all", list(range(1, 11))),
        ("all,!5", [i for i in range(1, 11) if i != 5]),
        ("1,1,3", [1, 1, 3]),
    ],
)
def test_merge_single_input_selection_matches_pagerange_resolution(
    tmp_path: Path, token: str, expected_pages: list[int]
) -> None:
    source = _make_source(tmp_path)
    output = tmp_path / "out.pdf"
    inputs = merge_ops.resolve_merge_inputs((f"{source}:{token}",))
    result = merge_ops.merge_documents(
        inputs, output=output, bookmarks="none", policy=make_policy()
    )
    assert result.exit_code == 0
    texts = [page_text(output, i) for i in range(1, len(expected_pages) + 1)]
    expected_texts = [f"src page {n}" for n in expected_pages]
    assert texts == expected_texts


def test_merge_single_input_no_selection_is_all_pages_in_order(tmp_path: Path) -> None:
    """E2: the plan's own acceptance signal is a *single*-input merge."""
    source = _make_source(tmp_path, pages=3)
    output = tmp_path / "out.pdf"
    inputs = merge_ops.resolve_merge_inputs((str(source),))
    assert len(inputs) == 1
    result = merge_ops.merge_documents(
        inputs, output=output, bookmarks="none", policy=make_policy()
    )
    assert result.exit_code == 0
    assert [page_text(output, i) for i in (1, 2, 3)] == [f"src page {n}" for n in (1, 2, 3)]


# --------------------------------------------------------------------------- #
# AC6 continued — the §4.3 error table surfaces through merge unmodified
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("token", ["0", "1-0"])
def test_merge_error_tokens_surface_pagerange_exit_2(tmp_path: Path, token: str) -> None:
    """§4.3's error table, through merge -- PDF-03's message unmodified,
    PDF-03's own reason/token/column fields intact (`errors.PageRangeError`,
    never a bare `UsageError` that lost the detail).

    Only the well-SHAPED-but-semantically-invalid rows (0, 1-0) reach
    `parse()` this way. The malformed-SHAPE rows (abc, 1--3, 1-2-3, a bare
    comma, an empty tail) are D2's own routing decision, not PDF-03's: none
    is syntactically valid per `is_valid_spec`, so D2 step 2 reads the WHOLE
    argument as the path instead of splitting -- a real file cannot be
    addressed as `path:abc` any more than as `path:` itself, by design (the
    escape for a colon-named file is `:all`, never a malformed shape).
    Verified by `test_split_input_spec_disambiguates_on_the_last_valid_colon`;
    the malformed-shape side of this same table IS reachable through `split
    --ranges`, which hands parts verbatim with no disambiguation filter --
    see `test_a_malformed_ranges_part_surfaces_pagerange_message_prefixed_
    with_position` in tests/unit/test_split.py."""
    source = _make_source(tmp_path, pages=10)
    output = tmp_path / "out.pdf"
    inputs = merge_ops.resolve_merge_inputs((f"{source}:{token}",))
    with pytest.raises(errors.PageRangeError):
        merge_ops.merge_documents(inputs, output=output, bookmarks="none", policy=make_policy())


def test_merge_out_of_range_token_surfaces_pagerange_exit_2(tmp_path: Path) -> None:
    source = _make_source(tmp_path, pages=10)
    output = tmp_path / "out.pdf"
    inputs = merge_ops.resolve_merge_inputs((f"{source}:50",))
    with pytest.raises(errors.PageRangeError) as excinfo:
        merge_ops.merge_documents(inputs, output=output, bookmarks="none", policy=make_policy())
    assert "out of range" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# AC2 — two inputs, page-count sum, first/last text
# --------------------------------------------------------------------------- #


def test_merge_two_inputs_sums_page_counts_and_orders_text(tmp_path: Path) -> None:
    from pdf_toolkit.ports.structure import require_structure

    first = _make_source(tmp_path / "a", pages=3)
    second_dir = tmp_path / "b"
    second_dir.mkdir(exist_ok=True)
    second = second_dir / "src.pdf"
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    made = canvas.Canvas(str(second), pagesize=letter)
    for number in range(1, 3):
        made.drawString(72, 700, f"second page {number}")
        made.showPage()
    made.save()

    output = tmp_path / "merged.pdf"
    inputs = merge_ops.resolve_merge_inputs((str(first), str(second)))
    result = merge_ops.merge_documents(
        inputs, output=output, bookmarks="none", policy=make_policy()
    )
    assert result.exit_code == 0
    engine = require_structure()
    with engine.open_document(output) as document:
        assert document.page_count == 3 + 2
    assert page_text(output, 1) == "src page 1"
    assert page_text(output, 5) == "second page 2"


# --------------------------------------------------------------------------- #
# AC11 continued — a real colon-named file resolves whole
# --------------------------------------------------------------------------- #


def test_a_file_literally_named_with_a_colon_resolves_whole(tmp_path: Path) -> None:
    weird = tmp_path / "notes:draft.pdf"
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    made = canvas.Canvas(str(weird), pagesize=letter)
    made.drawString(72, 700, "weird page 1")
    made.showPage()
    made.save()

    inputs = merge_ops.resolve_merge_inputs((str(weird),))
    assert len(inputs) == 1
    assert inputs[0].path == weird
    assert inputs[0].selection is None


def test_the_all_escape_addresses_a_file_that_itself_ends_in_a_range_shape(
    tmp_path: Path,
) -> None:
    weird = tmp_path / "a:1-3.pdf"
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    made = canvas.Canvas(str(weird), pagesize=letter)
    for number in range(1, 4):
        made.drawString(72, 700, f"weird page {number}")
        made.showPage()
    made.save()

    inputs = merge_ops.resolve_merge_inputs((f"{weird}:all",))
    assert len(inputs) == 1
    assert inputs[0].path == weird
    assert inputs[0].selection == "all"


# --------------------------------------------------------------------------- #
# AC12-AC14 — the three --bookmarks modes
# --------------------------------------------------------------------------- #


def _outline(path: Path) -> list[tuple[str, int]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    entries: list[tuple[str, int]] = []
    for item in reader.outline:
        if isinstance(item, list):
            continue
        entries.append((str(item.title), reader.get_destination_page_number(item)))
    return entries


def test_bookmarks_per_file_one_entry_per_input(tmp_path: Path) -> None:
    a = _make_source(tmp_path / "a", pages=2)
    b_dir = tmp_path / "b"
    b_dir.mkdir(exist_ok=True)
    b = b_dir / "src.pdf"
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    made = canvas.Canvas(str(b), pagesize=letter)
    made.drawString(72, 700, "b page 1")
    made.showPage()
    made.save()

    output = tmp_path / "out.pdf"
    inputs = merge_ops.resolve_merge_inputs((str(a), str(b)))
    result = merge_ops.merge_documents(
        inputs, output=output, bookmarks="per-file", policy=make_policy()
    )
    assert result.exit_code == 0
    entries = _outline(output)
    assert len(entries) == 2
    assert entries[0] == (a.stem, 0)
    assert entries[1] == (b.stem, 2)


def test_bookmarks_per_file_duplicate_input_yields_two_entries(tmp_path: Path) -> None:
    a = _make_source(tmp_path, pages=2)
    output = tmp_path / "out.pdf"
    inputs = merge_ops.resolve_merge_inputs((str(a), str(a)))
    result = merge_ops.merge_documents(
        inputs, output=output, bookmarks="per-file", policy=make_policy()
    )
    assert result.exit_code == 0
    entries = _outline(output)
    assert len(entries) == 2
    assert entries[0][1] == 0
    assert entries[1][1] == 2


def test_bookmarks_none_has_no_outline_at_all(tmp_path: Path) -> None:
    a = _make_source(tmp_path, pages=2)
    output = tmp_path / "out.pdf"
    inputs = merge_ops.resolve_merge_inputs((str(a),))
    result = merge_ops.merge_documents(
        inputs, output=output, bookmarks="none", policy=make_policy()
    )
    assert result.exit_code == 0
    assert _outline(output) == []


def test_bookmarks_preserve_remaps_and_drops_unselected(tmp_path: Path) -> None:
    from pypdf import PdfReader, PdfWriter

    source = _make_source(tmp_path, pages=10)
    reader = PdfReader(str(source))
    writer = PdfWriter()
    writer.append(reader)
    writer.add_outline_item("at-1", 0)
    writer.add_outline_item("at-5", 4)
    writer.add_outline_item("at-9", 8)
    with_outline = tmp_path / "with_outline.pdf"
    with open(with_outline, "wb") as handle:
        writer.write(handle)

    output = tmp_path / "out.pdf"
    inputs = merge_ops.resolve_merge_inputs((f"{with_outline}:1-4",))
    result = merge_ops.merge_documents(
        inputs, output=output, bookmarks="preserve", policy=make_policy()
    )
    assert result.exit_code == 0
    entries = _outline(output)
    assert entries == [("at-1", 0)]
    with_output_reader = PdfReader(str(output))
    for _title, page_index in entries:
        assert 0 <= page_index < len(with_output_reader.pages)
