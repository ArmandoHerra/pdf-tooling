"""``ops/split.py`` — the four modes, the ``--ranges`` comma, and ``--name``
collision/refusal arms (Design §D4-D6, AC4-AC5, AC9-AC10, AC16, AC18-AC19).

Runs in-process against the framework-free ops layer. AC1's round-trip lives
in ``tests/integration/test_split_merge_roundtrip.py``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from pdf_toolkit import errors
from pdf_toolkit.ops import split as split_ops
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


def _make_source(directory: Path, pages: int, *, name: str = "src.pdf") -> Path:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    made = canvas.Canvas(str(path), pagesize=letter)
    for number in range(1, pages + 1):
        made.drawString(72, 700, f"src page {number}")
        made.showPage()
    made.save()
    return path


# --------------------------------------------------------------------------- #
# AC7 — no grammar re-implementation
# --------------------------------------------------------------------------- #


def test_ops_split_does_not_reimplement_the_grammar() -> None:
    module_path = Path(__file__).resolve().parents[2] / "src" / "pdf_toolkit" / "ops" / "split.py"
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
    assert "parse" in imported


# --------------------------------------------------------------------------- #
# AC4 — --every
# --------------------------------------------------------------------------- #


def test_every_25_pages_at_10_writes_three_chunks_10_10_5(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=25)
    out_dir = tmp_path / "parts"
    result = split_ops.split_document(
        source,
        mode="every",
        every=10,
        ranges=(),
        name_template=None,
        out_dir=out_dir,
        policy=make_policy(),
    )
    assert result.exit_code == 0
    names = sorted(p.name for p in out_dir.iterdir())
    assert len(names) == 3
    from pdf_toolkit.ports.structure import require_structure

    engine = require_structure()
    counts = []
    for name in names:
        with engine.open_document(out_dir / name) as document:
            counts.append(document.page_count)
    assert counts == [10, 10, 5]
    # Per-page text, concatenated in name order, reproduces source order.
    all_texts: list[str] = []
    for name in names:
        target = out_dir / name
        with engine.open_document(target) as document:
            for page in range(1, document.page_count + 1):
                all_texts.append(page_text(target, page))
    assert all_texts == [f"src page {n}" for n in range(1, 26)]


def test_every_zero_is_usage_error() -> None:
    with pytest.raises(errors.UsageError):
        split_ops._parts_every(10, 0)


# --------------------------------------------------------------------------- #
# AC5 — --ranges, the comma is the part separator (D4, E3)
# --------------------------------------------------------------------------- #


def test_ranges_comma_separates_parts_not_a_union(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=45)
    out_dir = tmp_path / "parts"
    result = split_ops.split_document(
        source,
        mode="ranges",
        every=None,
        ranges=("1-12,13-40,41-",),
        name_template=None,
        out_dir=out_dir,
        policy=make_policy(),
    )
    assert result.exit_code == 0
    names = sorted(p.name for p in out_dir.iterdir())
    assert len(names) == 3
    from pdf_toolkit.ports.structure import require_structure

    engine = require_structure()
    counts = []
    for name in names:
        with engine.open_document(out_dir / name) as document:
            counts.append(document.page_count)
    assert counts == [12, 28, 5]
    first_target = out_dir / names[0]
    last_target = out_dir / names[-1]
    assert page_text(first_target, 1) == "src page 1"
    assert page_text(last_target, 5) == "src page 45"


def test_ranges_is_repeatable_and_each_occurrence_is_comma_split(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=10)
    out_dir = tmp_path / "parts"
    result = split_ops.split_document(
        source,
        mode="ranges",
        every=None,
        ranges=("1-2,3-4", "5-6"),
        name_template=None,
        out_dir=out_dir,
        policy=make_policy(),
    )
    assert result.exit_code == 0
    assert len(list(out_dir.iterdir())) == 3


def test_a_malformed_ranges_part_surfaces_pagerange_message_prefixed_with_position(
    tmp_path: Path,
) -> None:
    source = _make_source(tmp_path / "src", pages=10)
    out_dir = tmp_path / "parts"
    with pytest.raises(errors.PageRangeError) as excinfo:
        split_ops.split_document(
            source,
            mode="ranges",
            every=None,
            ranges=("1-3,1--3,5",),
            name_template=None,
            out_dir=out_dir,
            policy=make_policy(),
        )
    message = str(excinfo.value)
    assert "--ranges part 2 of 3" in message
    assert "1--3" in message


def test_a_zero_page_part_is_not_written_and_all_zero_is_exit_4(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=1)
    out_dir = tmp_path / "parts"
    with pytest.raises(errors.NoInputError):
        split_ops.split_document(
            source,
            mode="ranges",
            every=None,
            ranges=("even",),  # a 1-page document has no even pages
            name_template=None,
            out_dir=out_dir,
            policy=make_policy(),
        )


# --------------------------------------------------------------------------- #
# AC16 — --at-bookmarks, no outline at all (E4, D5)
# --------------------------------------------------------------------------- #


def test_at_bookmarks_on_a_document_with_no_outline_is_exit_4_and_writes_nothing(
    tmp_path: Path,
) -> None:
    source = _make_source(tmp_path / "src", pages=5)
    out_dir = tmp_path / "parts"
    with pytest.raises(errors.NoInputError) as excinfo:
        split_ops.split_document(
            source,
            mode="at-bookmarks",
            every=None,
            ranges=(),
            name_template=None,
            out_dir=out_dir,
            policy=make_policy(),
        )
    assert "no top-level outline entries" in str(excinfo.value)
    assert not out_dir.exists()


def test_at_bookmarks_leading_part_and_duplicate_bookmark(tmp_path: Path) -> None:
    from pypdf import PdfReader, PdfWriter

    source = _make_source(tmp_path / "src", pages=10)
    reader = PdfReader(str(source))
    writer = PdfWriter()
    writer.append(reader)
    writer.add_outline_item("first", 2)  # page 3 (0-based 2)
    writer.add_outline_item("dup-a", 4)  # page 5
    writer.add_outline_item("dup-b", 4)  # page 5 again -- must collapse
    with_outline = tmp_path / "with_outline.pdf"
    with open(with_outline, "wb") as handle:
        writer.write(handle)

    out_dir = tmp_path / "parts"
    result = split_ops.split_document(
        with_outline,
        mode="at-bookmarks",
        every=None,
        ranges=(),
        name_template=None,
        out_dir=out_dir,
        policy=make_policy(),
    )
    assert result.exit_code == 0
    names = sorted(p.name for p in out_dir.iterdir())
    # Leading part (pages 1-2) + at page 3 (3-4) + at page 5 (5-10), no
    # zero-page file for the duplicate bookmark.
    assert len(names) == 3
    from pdf_toolkit.ports.structure import require_structure

    engine = require_structure()
    total = 0
    for name in names:
        with engine.open_document(out_dir / name) as document:
            total += document.page_count
    assert total == 10


# --------------------------------------------------------------------------- #
# AC9-10 — --name refusal and collision arms
# --------------------------------------------------------------------------- #


def test_name_collision_is_refused_during_planning_zero_files_written(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=3)
    out_dir = tmp_path / "parts"
    with pytest.raises(errors.OutputCollisionError):
        split_ops.split_document(
            source,
            mode="each-page",
            every=None,
            ranges=(),
            name_template="{stem}.{ext}",
            out_dir=out_dir,
            policy=make_policy(),
        )
    assert not out_dir.exists() or not list(out_dir.iterdir())


def test_name_collision_is_refused_identically_under_dry_run(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=3)
    out_dir = tmp_path / "parts"
    with pytest.raises(errors.OutputCollisionError):
        split_ops.split_document(
            source,
            mode="each-page",
            every=None,
            ranges=(),
            name_template="{stem}.{ext}",
            out_dir=out_dir,
            policy=make_policy(dry_run=True),
        )
    assert not out_dir.exists()


def test_page_token_outside_each_page_is_usage_error(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=3)
    out_dir = tmp_path / "parts"
    with pytest.raises(errors.UsageError):
        split_ops.split_document(
            source,
            mode="every",
            every=2,
            ranges=(),
            name_template="{stem}-{page}.{ext}",
            out_dir=out_dir,
            policy=make_policy(),
        )


# --------------------------------------------------------------------------- #
# AC18 — dry-run purity: --out-dir is never created
# --------------------------------------------------------------------------- #


def test_dry_run_never_creates_out_dir(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=3)
    out_dir = tmp_path / "never"
    result = split_ops.split_document(
        source,
        mode="each-page",
        every=None,
        ranges=(),
        name_template=None,
        out_dir=out_dir,
        policy=make_policy(dry_run=True),
    )
    assert result.dry_run is True
    assert not out_dir.exists()
    assert result.exit_code == 0
    assert len(result.items) == 3


# --------------------------------------------------------------------------- #
# AC19 — --every 0, directory input, nonexistent input
# --------------------------------------------------------------------------- #


def test_nonexistent_source_is_exit_4() -> None:
    with pytest.raises(errors.NoInputError):
        split_ops.split_document(
            Path("/does/not/exist.pdf"),
            mode="each-page",
            every=None,
            ranges=(),
            name_template=None,
            out_dir=Path("/tmp/whatever"),
            policy=make_policy(),
        )


def test_directory_source_is_usage_error(tmp_path: Path) -> None:
    directory = tmp_path / "adir"
    directory.mkdir()
    with pytest.raises(errors.UsageError):
        split_ops.split_document(
            directory,
            mode="each-page",
            every=None,
            ranges=(),
            name_template=None,
            out_dir=tmp_path / "out",
            policy=make_policy(),
        )


def test_default_name_templates_per_mode() -> None:
    assert split_ops.default_name_template("each-page") == "{stem}-{page:03}.{ext}"
    assert split_ops.default_name_template("every") == "{stem}-{index:03}.{ext}"
    assert split_ops.default_name_template("ranges") == "{stem}-{index:03}.{ext}"
    assert split_ops.default_name_template("at-bookmarks") == "{stem}-{index:03}.{ext}"
