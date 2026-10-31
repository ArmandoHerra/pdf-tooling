"""PDF-161 -- `create` warns and draws `?` for control and undrawable characters.

THE DEFECT (ledger `28a5ce263a`, carrier B-537). ``printf 'A\\x1bB\\n' > esc.txt;
pdftooling create esc.txt -O esc.pdf -o json`` exited 0 with ``warnings: []``
while the page drew ``(A)`` in Helvetica, ``(n)`` in ZapfDingbats (a filled
square) and ``(B)``. ``sanitize_text`` asked Python's ``cp1252`` codec, which
accepts U+0000-U+001F and U+007F, while the engine's ``winansi`` codec draws
none of them. The one warning ``create`` did give named only the first
replaced code point.

THE FIX under test (operator ruling OR-88, the OR-71 rule):
``ops/compose.py::sanitize_text`` replaces every control character that is not
layout (newline, carriage return, tab, form feed) and every character the 12
WinAnsi base-14 fonts cannot draw with ``?``, and the run carries exactly one
warning naming every distinct replaced code point as ``U+XXXX``. The check is
pure and precedes the dry/real fork, so ``--dry-run`` predicts it. Exit codes
are unchanged.

Provenance of every literal below: ``e7384d2`` (v1.3.1-5) as measured
2026-10-30 (PDF-161 Evidence E1-E7), re-driven at ``fa2bb8a`` on 2026-10-31.

This module imports NO private name the fix adds (``_LAYOUT_CONTROLS``,
``_encodable``), so copying it onto a tree without the fix collects cleanly and
the defect nodes fail on assertions. Sha256 differentials against the base tree
are a Validation-step instrument, not a literal here: no hash is asserted.
"""

from __future__ import annotations

import io
import itertools
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pypdf import PdfReader  # noqa: E402
from pypdf.generic import ByteStringObject, ContentStream, TextStringObject  # noqa: E402

from pdf_tooling.cli.main import app  # noqa: E402,F401  (registers the engines)
from pdf_tooling.ops import compose  # noqa: E402
from pdf_tooling.safety.policy import SafetyPolicy  # noqa: E402
from registry import run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

APP_ROOT: Final[Path] = TESTS_DIR.parent
BAD_FONTS: Final[frozenset[str]] = frozenset({"/ZapfDingbats", "/Symbol"})
WINANSI_FONTS: Final[tuple[str, ...]] = tuple(
    name for name in compose.BASE14_FONTS if name not in ("Symbol", "ZapfDingbats")
)

#: E4: the sweep S (271 points). T (layout controls) is classified separately.
SWEEP: Final[tuple[int, ...]] = (
    *range(0x100),
    0x0152,
    0x20AC,
    0x2022,
    0x2122,
    0x0301,
    0x202E,
    0x6F22,
    0xDCFF,
    0xFFFD,
    0x1F600,
    0x0391,
    0x03B1,
    0x2665,
    0x2702,
    0x275D,
)
LAYOUT: Final[frozenset[int]] = frozenset({0x09, 0x0A, 0x0C, 0x0D})

_cell_counter = itertools.count()


def _msg(n: int, points: str, line: int) -> str:
    return (
        f"{n} character(s) outside the font's WinAnsi encoding were replaced with '?': "
        f"{points} (first on line {line})"
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _operand_bytes(obj: Any) -> bytes:
    if isinstance(obj, ByteStringObject):
        return bytes(obj)
    if isinstance(obj, TextStringObject):
        return obj.get_original_bytes()
    raise AssertionError(f"unexpected Tj operand type {type(obj)!r}")


def _inspect(reader: PdfReader) -> tuple[list[str], list[list[list[tuple[str, bytes]]]]]:
    """Every page's BaseFont names, and its lines as lists of (BaseFont, operand bytes).

    A line ends at ``T*``. Operands are raw bytes, read from the content stream.
    """
    fonts: set[str] = set()
    pages: list[list[list[tuple[str, bytes]]]] = []
    for page in reader.pages:
        resources = page.get("/Resources")
        fonts_dict: Any = {}
        if resources is not None:
            fonts_dict = resources.get_object().get("/Font", {})
            if hasattr(fonts_dict, "get_object"):
                fonts_dict = fonts_dict.get_object()
        base_of = {
            name: str(font.get_object().get("/BaseFont")) for name, font in fonts_dict.items()
        }
        fonts |= set(base_of.values())
        stream = ContentStream(page.get_contents(), reader)
        current = ""
        lines: list[list[tuple[str, bytes]]] = []
        line: list[tuple[str, bytes]] = []
        for operands, operator in stream.operations:
            if operator == b"Tf":
                current = base_of.get(str(operands[0]), "?unknown")
            elif operator == b"Tj":
                line.append((current, _operand_bytes(operands[0])))
            elif operator == b"T*":
                lines.append(line)
                line = []
        if line:
            lines.append(line)
        pages.append([ln for ln in lines if ln])
    return sorted(fonts), pages


def _page_of(path: Path) -> tuple[list[str], list[list[list[tuple[str, bytes]]]]]:
    return _inspect(PdfReader(str(path)))


def _flat(pages: list[list[list[tuple[str, bytes]]]]) -> list[tuple[str, bytes]]:
    return [item for page in pages for line in page for item in line]


def _joined(pages: list[list[list[tuple[str, bytes]]]]) -> bytes:
    return b"".join(operand for _font, operand in _flat(pages))


def _cell(tmp_path: Path) -> Path:
    cell = tmp_path / f"cell{next(_cell_counter)}"
    cell.mkdir()
    return cell


def _create(
    cell: Path, name: str, data: bytes | None, *argv: str, dry: bool, stdin: str = ""
) -> subprocess.CompletedProcess[str]:
    if data is not None:
        (cell / name).write_bytes(data)
    head = ["--dry-run"] if dry else []
    return run_cli("create", *head, name, *argv, "-o", "json", cwd=cell, stdin=stdin)


def _warn_lines(run: subprocess.CompletedProcess[str]) -> list[str]:
    return [ln for ln in run.stderr.splitlines() if ln.startswith("warning: ")]


def _carries(run: subprocess.CompletedProcess[str], message: str) -> None:
    """'Carries M': the envelope list is exactly [M]; stderr has that one `warning:` line."""
    document = json.loads(run.stdout)
    assert document["warnings"] == [message], document["warnings"]
    assert _warn_lines(run) == [f"warning: {message}"], run.stderr[-600:]


def _carries_nothing(run: subprocess.CompletedProcess[str]) -> None:
    assert json.loads(run.stdout)["warnings"] == [], run.stdout[-400:]
    assert _warn_lines(run) == [], run.stderr[-400:]


def _fonts_clean(fonts: Sequence[str]) -> bool:
    return not (set(fonts) & BAD_FONTS)


def _policy(*, dry: bool) -> SafetyPolicy:
    return SafetyPolicy(
        dry_run=dry,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )


def _keys(value: Any) -> Any:
    """The recursive key skeleton of a JSON document (values dropped, order kept)."""
    if isinstance(value, dict):
        return [(k, _keys(v)) for k, v in value.items()]
    if isinstance(value, list):
        return [_keys(v) for v in value if isinstance(v, (dict, list))]
    return None


def _norm(raw: str) -> str:
    return re.sub(r'"duration_ms": \d+', '"duration_ms": N', raw)


# --------------------------------------------------------------------------- #
# AC1 / AC2 -- the ledger repro, real and dry
# --------------------------------------------------------------------------- #

LEDGER: Final[tuple[tuple[str, bytes, str, str | None], ...]] = (
    ("esc", b"A\x1bB\n", "U+001B", None),
    ("bel", b"A\x07B\n", "U+0007", None),
    ("vt", b"A\x0bB\n", "U+000B", None),
    ("del", b"A\x7fB\n", "U+007F", None),
    ("nul", b"A\x00B\n", "U+0000", None),
    ("stdin-esc", b"A\x1bB\n", "U+001B", "stdin"),
)


def _drive_ledger(
    cell: Path, data: bytes, how: str | None, *, dry: bool
) -> subprocess.CompletedProcess[str]:
    if how == "stdin":
        return run_cli(
            "create", *(["--dry-run"] if dry else []), "-", "-O", "s.pdf", "-o", "json",
            cwd=cell, stdin=data.decode("utf-8"),
        )  # fmt: skip
    return _create(cell, "in.txt", data, "-O", "o.pdf", dry=dry)


@pytest.mark.parametrize(("label", "data", "point", "how"), LEDGER, ids=[c[0] for c in LEDGER])
def test_ac1_ledger_repro_warns_and_draws_question_mark(
    tmp_path: Path, label: str, data: bytes, point: str, how: str | None
) -> None:
    cell = _cell(tmp_path)
    run = _drive_ledger(cell, data, how, dry=False)
    assert run.returncode == 0, run.stderr[-400:]
    assert json.loads(run.stdout)["schema_version"] == 1
    _carries(run, _msg(1, point, 1))
    out = cell / ("s.pdf" if how == "stdin" else "o.pdf")
    fonts, pages = _page_of(out)
    assert _fonts_clean(fonts), fonts
    assert _joined(pages) == b"A?B", _flat(pages)
    assert {font for font, _ in _flat(pages)} == {"/Helvetica"}
    text = run_cli("text", out.name, "-o", "json", cwd=cell, stdin="")
    assert text.returncode == 0, text.stderr[-300:]
    assert "A?B" in text.stdout and "■" not in text.stdout


@pytest.mark.parametrize(("label", "data", "point", "how"), LEDGER, ids=[c[0] for c in LEDGER])
def test_ac2_dry_run_predicts_the_warning(
    tmp_path: Path, label: str, data: bytes, point: str, how: str | None
) -> None:
    real_cell, dry_cell = _cell(tmp_path), _cell(tmp_path)
    real = _drive_ledger(real_cell, data, how, dry=False)
    dry = _drive_ledger(dry_cell, data, how, dry=True)
    assert (real.returncode, dry.returncode) == (0, 0), dry.stderr[-300:]
    _carries(dry, _msg(1, point, 1))
    assert json.loads(dry.stdout)["warnings"] == json.loads(real.stdout)["warnings"]
    expected = [] if how == "stdin" else ["in.txt"]
    assert sorted(p.name for p in dry_cell.iterdir()) == expected


# --------------------------------------------------------------------------- #
# AC3 -- the decisive mixed arm
# --------------------------------------------------------------------------- #

MIXED: Final[bytes] = "A漢\x1bB\x7fé😀漢\n".encode()


@pytest.mark.parametrize("dry", [False, True], ids=["real", "dry"])
def test_ac3_mixed_arm_names_every_point_in_order(tmp_path: Path, dry: bool) -> None:
    cell = _cell(tmp_path)
    run = _create(cell, "mix.txt", MIXED, "-O", "m.pdf", dry=dry)
    assert run.returncode == 0, run.stderr[-300:]
    _carries(run, _msg(5, "U+6F22, U+001B, U+007F, U+1F600", 1))
    if not dry:
        fonts, pages = _page_of(cell / "m.pdf")
        assert _fonts_clean(fonts), fonts
        assert _joined(pages) == b"A??B?\xe9??", _flat(pages)
        assert {font for font, _ in _flat(pages)} == {"/Helvetica"}


# --------------------------------------------------------------------------- #
# AC4 -- the replaced set is what the engine cannot draw, for each WinAnsi font
# --------------------------------------------------------------------------- #


def _engine_render(font: str, point: int) -> tuple[list[str], list[tuple[str, bytes]]] | None:
    """What the product's own adapter draws for ``A<p>B`` in *font*, or None if it refuses."""
    from pdf_tooling.adapters.reportlab_compose import ReportlabComposeAdapter
    from pdf_tooling.ports.compose import TextLayout

    page_size = compose.parse_page_size("a4").size
    assert page_size is not None
    size = compose.DEFAULT_SIZE
    margin = compose.parse_length(compose.DEFAULT_CREATE_MARGIN, flag="--margin")
    layout = TextLayout(
        font=font,
        size=size,
        leading=size * compose.LEADING_RATIO,
        page_size=page_size,
        margin_pt=margin,
        lines_per_page=compose.lines_per_page(page_size, margin, size),
        title=None,
    )
    buffer = io.BytesIO()
    try:
        ReportlabComposeAdapter().render_text("A" + chr(point) + "B", layout=layout, out=buffer)
    except Exception:  # noqa: BLE001 - an engine that cannot render it cannot draw it
        return None
    fonts, pages = _inspect(PdfReader(io.BytesIO(buffer.getvalue())))
    return fonts, _flat(pages)


def _create_in_process(text: str, font: str, output: Path, *, dry: bool) -> Any:
    return compose.create_document(
        text,
        source="in.txt",
        output=output,
        font=font,
        size=compose.DEFAULT_SIZE,
        page=compose.parse_page_size("a4"),
        margin_pt=compose.parse_length(compose.DEFAULT_CREATE_MARGIN, flag="--margin"),
        title=None,
        policy=_policy(dry=dry),
    )


@pytest.mark.parametrize("font", WINANSI_FONTS)
def test_ac4_replaced_set_is_what_the_engine_cannot_draw(tmp_path: Path, font: str) -> None:
    swept = [p for p in SWEEP if p not in LAYOUT]
    assert len(SWEEP) == 271 and len(swept) == 267
    drawn_byte: dict[int, bytes] = {}
    non_drawable: set[int] = set()
    for p in swept:
        rendered = _engine_render(font, p)
        if rendered is None:
            non_drawable.add(p)
            continue
        fonts, shown = rendered
        if not _fonts_clean(fonts) or any(name != f"/{font}" for name, _ in shown):
            non_drawable.add(p)
            continue
        operand = b"".join(op for _name, op in shown)
        assert len(operand) == 3 and operand[:1] == b"A" and operand[2:] == b"B", (p, operand)
        drawn_byte[p] = operand[1:2]

    assert len(non_drawable) == 72, sorted(f"U+{p:04X}" for p in non_drawable)
    assert len(swept) - len(non_drawable) == 195
    for p in (0x00, 0x07, 0x0B, 0x1B, 0x1F, 0x7F, 0x81, 0x9B, 0x301, 0x6F22, 0xDCFF):
        assert p in non_drawable, f"U+{p:04X}"
    for p in (0x20, 0xE9, 0x152, 0x20AC, 0x2022, 0x2122):
        assert p not in non_drawable, f"U+{p:04X}"

    # create_document encodes its text as UTF-8 first, so a lone surrogate raises in both
    # states, outside the sanitiser; the CLI cannot deliver one (asserted below by name).
    with pytest.raises(UnicodeEncodeError):
        _create_in_process("A\udcffB", font, tmp_path / "s.pdf", dry=True)

    dry_out = tmp_path / "dry.pdf"
    named = 0
    for p in swept:
        if p == 0xDCFF:
            continue
        result = _create_in_process("A" + chr(p) + "B", font, dry_out, dry=True)
        listed = f"U+{p:04X}" in " ".join(result.warnings)
        assert listed == (p in non_drawable), f"{font} U+{p:04X}: {result.warnings}"
        named += listed
    assert named == 71
    for p in LAYOUT:
        assert _create_in_process("A" + chr(p) + "B", font, dry_out, dry=True).warnings == ()

    if font == "Helvetica":
        for p in swept:
            if p == 0xDCFF:
                continue
            out = tmp_path / f"h{p:05X}.pdf"
            _create_in_process("A" + chr(p) + "B", font, out, dry=False)
            fonts, pages = _page_of(out)
            assert _fonts_clean(fonts), f"U+{p:04X}: {fonts}"
            expected = b"A?B" if p in non_drawable else b"A" + drawn_byte[p] + b"B"
            assert _joined(pages) == expected, f"U+{p:04X}: {_flat(pages)}"


@pytest.mark.parametrize("dry", [False, True], ids=["real", "dry"])
def test_ac4_lone_surrogate_input_is_refused_before_the_check(tmp_path: Path, dry: bool) -> None:
    cell = _cell(tmp_path)
    run = _create(cell, "s.txt", b"A\xed\xb3\xbfB\n", "-O", "o.pdf", dry=dry)
    assert run.returncode == 1, run.stderr[-300:]
    assert json.loads(run.stdout)["error"]["code"] == 1
    assert _warn_lines(run) == []
    assert not (cell / "o.pdf").exists()


# --------------------------------------------------------------------------- #
# AC5 -- layout controls keep their meaning; VT does not become one
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("dry", [False, True], ids=["real", "dry"])
def test_ac5_layout_controls_keep_their_structure(tmp_path: Path, dry: bool) -> None:
    arms: dict[str, bytes] = {
        "ff": b"a\fb\n",
        "tab": b"a\tb\n",
        "cr": b"a\rb\n",
        "crlf": b"a\r\nb\n",
        "lf": b"a\nb\n",
    }
    for label, data in arms.items():
        cell = _cell(tmp_path)
        run = _create(cell, "in.txt", data, "-O", "o.pdf", dry=dry)
        assert run.returncode == 0, (label, run.stderr[-300:])
        _carries_nothing(run)
        if dry:
            continue
        _fonts, pages = _page_of(cell / "o.pdf")
        if label == "ff":
            assert [[[op for _f, op in line] for line in page] for page in pages] == [
                [[b"a"]],
                [[b"b"]],
            ]
        elif label == "tab":
            assert [[[op for _f, op in line] for line in page] for page in pages] == [[[b"a    b"]]]
        else:
            assert [[[op for _f, op in line] for line in page] for page in pages] == [
                [[b"a"], [b"b"]]
            ], label

    # Decisive: VT is not layout. It is one line, drawn `?` and named.
    cell = _cell(tmp_path)
    run = _create(cell, "in.txt", b"a\x0bb\n", "-O", "o.pdf", dry=dry)
    assert run.returncode == 0, run.stderr[-300:]
    _carries(run, _msg(1, "U+000B", 1))
    if not dry:
        fonts, pages = _page_of(cell / "o.pdf")
        assert _fonts_clean(fonts), fonts
        assert [[[op for _f, op in line] for line in page] for page in pages] == [[[b"a?b"]]]

    # The wrap probe: ESC between 50 and 50 `x ` tokens splits 56 x + `?` / 44 x.
    cell = _cell(tmp_path)
    probe = ("x " * 50 + "\x1b " + "x " * 50 + "\n").encode()
    run = _create(cell, "in.txt", probe, "-O", "o.pdf", dry=dry)
    assert run.returncode == 0, run.stderr[-300:]
    _carries(run, _msg(1, "U+001B", 1))
    if not dry:
        fonts, pages = _page_of(cell / "o.pdf")
        assert _fonts_clean(fonts), fonts
        assert len(pages) == 1 and len(pages[0]) == 2, [len(page) for page in pages]
        first, second = (b"".join(op for _f, op in line) for line in pages[0])
        assert (first.count(b"x"), first.count(b"?")) == (56, 1), first
        assert (second.count(b"x"), second.count(b"?")) == (44, 0), second


# --------------------------------------------------------------------------- #
# AC6 -- drawable text is unchanged (the sha256 differential is a Validation step)
# --------------------------------------------------------------------------- #


def test_ac6_drawable_text_draws_the_same_operands(tmp_path: Path) -> None:
    arms: tuple[tuple[bytes, bytes, str | None], ...] = (
        (b"hello\n", b"hello", None),
        ("AéB\n".encode(), b"A\xe9B", None),
        ("A€B\n".encode(), b"A\x80B", None),
        ("A漢😀B\n".encode(), b"A??B", _msg(2, "U+6F22, U+1F600", 1)),
    )
    for data, operand, message in arms:
        cell = _cell(tmp_path)
        run = _create(cell, "in.txt", data, "-O", "o.pdf", dry=False)
        assert run.returncode == 0, run.stderr[-300:]
        if message is None:
            _carries_nothing(run)
        else:
            _carries(run, message)
        fonts, pages = _page_of(cell / "o.pdf")
        assert _fonts_clean(fonts), fonts
        assert _flat(pages) == [("/Helvetica", operand)]


# --------------------------------------------------------------------------- #
# AC7 -- the line locator and the byte safety of the message
# --------------------------------------------------------------------------- #


def test_ac7_message_lines_and_ascii(tmp_path: Path) -> None:
    probes: tuple[tuple[bytes, str], ...] = (
        ("ok\nok\n€你\x1b好\n".encode(), _msg(3, "U+4F60, U+001B, U+597D", 3)),
        ("ok\rok\r漢\n".encode(), _msg(1, "U+6F22", 3)),
        ("ok\r\nok\r\n漢\n".encode(), _msg(1, "U+6F22", 3)),
        (b"A\xc2\x9bB\n", _msg(1, "U+009B", 1)),
        (b"A\xe2\x80\xaeB\n", _msg(1, "U+202E", 1)),
        (b"A\x65\xcc\x81B\n", _msg(1, "U+0301", 1)),
    )
    for data, message in probes:
        for dry in (False, True):
            cell = _cell(tmp_path)
            run = _create(cell, "in.txt", data, "-O", "o.pdf", dry=dry)
            assert run.returncode == 0, run.stderr[-300:]
            _carries(run, message)
            raw = run.stderr.encode("utf-8")
            for ln in raw.split(b"\n")[:-1]:
                assert all(0x20 <= b <= 0x7E for b in ln), ln
            assert raw.endswith(b"\n") or raw == b""
            assert message.isascii()
            assert run.stdout.isascii()


# --------------------------------------------------------------------------- #
# AC8 -- the exit-table matrix (GR-002), (dry, real) pairs
# --------------------------------------------------------------------------- #

DRAWABLE: Final[bytes] = b"hello\n"
UNDRAWABLE: Final[bytes] = "A\x1bB漢\n".encode()
W8: Final[str] = _msg(2, "U+001B, U+6F22", 1)

#: E6: (row, expected (dry rc, real rc), dry outcome, real outcome); RES = result, ERR = error.
EXIT_TABLE: Final[tuple[tuple[int, tuple[int, int], str, str], ...]] = (
    (1, (0, 0), "RES", "RES"),
    (2, (0, 0), "RES", "RES"),
    (3, (0, 0), "RES", "RES"),
    (4, (5, 5), "RES", "ERR"),
    (5, (1, 1), "RES", "ERR"),
    (6, (4, 4), "ERR", "ERR"),
    (7, (2, 2), "ERR", "ERR"),
    (8, (4, 4), "ERR", "ERR"),
    (9, (2, 2), "ERR", "ERR"),
    (10, (2, 2), "ERR", "ERR"),
    (11, (2, 2), "ERR", "ERR"),
    (12, (2, 2), "ERR", "ERR"),
    (13, (2, 2), "ERR", "ERR"),
    (14, (1, 1), "ERR", "ERR"),
    (15, (2, 2), "ERR", "ERR"),
)


def _drive_row(
    tmp_path: Path, row: int, data: bytes, *, dry: bool
) -> tuple[subprocess.CompletedProcess[str], Path]:
    cell = _cell(tmp_path)
    head = ["--dry-run"] if dry else []
    common = ["-o", "json"]
    stdin = ""
    if row == 1:
        (cell / "in.txt").write_bytes(data)
        argv = ["in.txt", "-O", "o.pdf"]
    elif row == 2:
        argv = ["-", "-O", "o.pdf"]
        stdin = data.decode("utf-8")
    elif row == 3:
        (cell / "in.txt").write_bytes(data)
        (cell / "o.pdf").write_bytes(b"old")
        argv = ["in.txt", "-O", "o.pdf", "--force"]
    elif row == 4:
        (cell / "in.txt").write_bytes(data)
        (cell / "o.pdf").write_bytes(b"old")
        argv = ["in.txt", "-O", "o.pdf"]
    elif row == 5:
        (cell / "in.txt").write_bytes(data)
        (cell / "ro").mkdir()
        argv = ["in.txt", "-O", "ro/o.pdf"]
    elif row == 6:
        argv = ["missing.txt", "-O", "o.pdf"]
    elif row == 7:
        (cell / "dir").mkdir()
        argv = ["dir", "-O", "o.pdf"]
    elif row == 8:
        (cell / "in.txt").write_bytes(b"")
        argv = ["in.txt", "-O", "o.pdf"]
    elif row == 9:
        argv = ["-"]
        stdin = data.decode("utf-8")
    elif row == 10:
        (cell / "in.txt").write_bytes(data)
        (cell / "two.txt").write_bytes(data)
        argv = ["in.txt", "two.txt", "-O", "o.pdf"]
    elif row == 11:
        (cell / "in.txt").write_bytes(data)
        argv = ["in.txt", "-O", "o.pdf", "--font", "Nope"]
    elif row == 12:
        (cell / "in.txt").write_bytes(data)
        argv = ["in.txt", "-O", "o.pdf", "--size", "0"]
    elif row == 13:
        (cell / "in.txt").write_bytes(data)
        argv = ["in.txt", "-O", "o.pdf", "--page-size", "from-image"]
    elif row == 14:
        (cell / "in.txt").write_bytes(b"\xff" + data)
        argv = ["in.txt", "-O", "o.pdf"]
    else:
        (cell / "in.txt").write_bytes(data)
        argv = ["in.txt", "-O", "o.pdf", "--margin", "1000pt"]
    if row == 5:
        (cell / "ro").chmod(0o500)
    try:
        run = run_cli("create", *head, *argv, *common, cwd=cell, stdin=stdin)
    finally:
        if row == 5:
            (cell / "ro").chmod(0o700)
    return run, cell


def _outcome(run: subprocess.CompletedProcess[str]) -> str:
    return "ERR" if "error" in json.loads(run.stdout) else "RES"


def _listing(cell: Path) -> list[str]:
    return sorted(str(p.relative_to(cell)) for p in cell.rglob("*"))


def test_ac8_exit_table_pairs(tmp_path: Path) -> None:
    for row, rcs, dry_kind, real_kind in EXIT_TABLE:
        for dry, rc, kind in ((True, rcs[0], dry_kind), (False, rcs[1], real_kind)):
            good, good_cell = _drive_row(tmp_path, row, DRAWABLE, dry=dry)
            bad, bad_cell = _drive_row(tmp_path, row, UNDRAWABLE, dry=dry)
            where = f"row {row} {'dry' if dry else 'real'}"
            assert (good.returncode, bad.returncode) == (rc, rc), (where, bad.stderr[-300:])
            assert (_outcome(good), _outcome(bad)) == (kind, kind), where
            assert _listing(good_cell) == _listing(bad_cell) or kind == "RES", where
            if kind == "ERR":
                # An error envelope is byte-identical between the two inputs, with no warning.
                assert _norm(bad.stdout) == _norm(good.stdout), where
                assert bad.stderr == good.stderr, where
                assert _warn_lines(bad) == [], where
                continue
            good_doc, bad_doc = json.loads(good.stdout), json.loads(bad.stdout)
            assert good_doc["schema_version"] == bad_doc["schema_version"] == 1
            assert _keys(good_doc) == _keys(bad_doc), where
            assert good_doc["warnings"] == [], where
            assert [w for w in bad_doc["warnings"] if w != W8] == good_doc["warnings"], where
            assert bad_doc["warnings"].count(W8) == 1, (where, bad_doc["warnings"])
            assert _warn_lines(bad) == [f"warning: {W8}"], (where, bad.stderr[-300:])
            assert _warn_lines(good) == [], where
            assert _listing(good_cell) == _listing(bad_cell), where


# --------------------------------------------------------------------------- #
# AC9 -- create and watermark say the same thing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "string", ["A漢😀B", "A\x1bB", "漢漢漢", "😀漢😀", "A\u009bB"], ids=lambda s: ascii(s)
)
def test_ac9_create_and_watermark_say_the_same_thing(tmp_path: Path, string: str) -> None:
    cell = _cell(tmp_path)
    made = _create(cell, "base.txt", b"hello\n", "-O", "base.pdf", dry=False)
    assert made.returncode == 0, made.stderr[-300:]
    created = _create(cell, "u.txt", (string + "\n").encode("utf-8"), "-O", "c.pdf", dry=False)
    marked = run_cli(
        "watermark", "base.pdf", "--text", string, "-O", "w.pdf", "-o", "json", cwd=cell, stdin=""
    )
    assert (created.returncode, marked.returncode) == (0, 0), marked.stderr[-300:]
    c_warnings = json.loads(created.stdout)["warnings"]
    w_warnings = [w for w in json.loads(marked.stdout)["warnings"] if w.startswith("--text: ")]
    assert len(c_warnings) == 1 and len(w_warnings) == 1, (c_warnings, w_warnings)
    assert c_warnings[0] == w_warnings[0].removeprefix("--text: ") + " (first on line 1)"


# --------------------------------------------------------------------------- #
# AC11 -- Symbol and ZapfDingbats keep their bytes
# --------------------------------------------------------------------------- #


def test_ac11_symbol_and_zapfdingbats_are_pinned(tmp_path: Path) -> None:
    cell = _cell(tmp_path)
    sym = _create(cell, "h.txt", b"hello\n", "--font", "Symbol", "-O", "sym.pdf", dry=False)
    zap = _create(cell, "h.txt", None, "--font", "ZapfDingbats", "-O", "zap.pdf", dry=False)
    ab = _create(cell, "ab.txt", b"a b\n", "--font", "ZapfDingbats", "-O", "ab.pdf", dry=False)
    for run in (sym, zap, ab):
        assert run.returncode == 0, run.stderr[-300:]
        _carries_nothing(run)
    for name, expected in (("sym.pdf", b"nnnnn"), ("zap.pdf", b"nnnnn"), ("ab.pdf", b"n n")):
        _fonts, pages = _page_of(cell / name)
        assert {font for font, _ in _flat(pages)} == {"/ZapfDingbats"}, name
        assert _joined(pages) == expected, (name, _flat(pages))


# --------------------------------------------------------------------------- #
# AC12 -- the help and README say what create can draw
# --------------------------------------------------------------------------- #

HELP_PARAGRAPH: Final[str] = (
    "v1 uses the base-14 fonts and embeds none, so some characters cannot be drawn: CJK, "
    "emoji, most non-Latin scripts, and every control character except the newline, carriage "
    "return, tab and form feed described above. Each one renders as '?', and the run raises "
    "one warning that counts them, names every replaced character as a U+XXXX code point and "
    "gives the line of the first -- visible degradation, never a silent drop. --dry-run "
    "predicts the same warning; the exit code is unchanged. The Symbol and ZapfDingbats fonts "
    "draw their own symbol sets, which this check does not cover. Markdown and HTML input are "
    "not part of v1."
)
README_BULLET: Final[str] = (
    "- **`watermark --text` and `create`:** they draw only characters the built-in font's "
    "WinAnsi encoding covers; any other character draws `?` and is named in a warning. "
    "`create` keeps a newline, carriage return, tab and form feed as layout, and does not "
    "check its `Symbol` and `ZapfDingbats` fonts."
)
README_OLD_BULLET: Final[str] = (
    "- **`watermark --text`:** it draws only characters the built-in font's WinAnsi encoding "
    "covers; any other character draws `?` and is named in a warning."
)


def test_ac12_help_and_readme_say_what_create_draws() -> None:
    env = {**os.environ, "COLUMNS": "100000", "TERM": "dumb", "NO_COLOR": "1"}
    shown = run_cli("create", "--help", env=env, stdin="")
    assert shown.returncode == 0, shown.stderr[-300:]
    collapsed = " ".join(shown.stdout.split())
    assert HELP_PARAGRAPH in collapsed
    assert "the first offending codepoint" not in collapsed
    readme_lines = (APP_ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    heading = readme_lines.index("### Known limitations")
    following = readme_lines[heading + 1 :]
    assert README_BULLET in following
    assert README_OLD_BULLET not in readme_lines


# --------------------------------------------------------------------------- #
# AC13 -- the envelope keeps its shape
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("dry", [False, True], ids=["real", "dry"])
def test_ac13_envelope_shape(tmp_path: Path, dry: bool) -> None:
    good = _create(_cell(tmp_path), "in.txt", DRAWABLE, "-O", "o.pdf", dry=dry)
    bad = _create(_cell(tmp_path), "in.txt", UNDRAWABLE, "-O", "o.pdf", dry=dry)
    good_doc, bad_doc = json.loads(good.stdout), json.loads(bad.stdout)
    assert good_doc["schema_version"] == bad_doc["schema_version"] == 1
    assert _keys(good_doc) == _keys(bad_doc)
    assert (good.returncode, bad.returncode) == (0, 0)
    assert bad_doc["warnings"] == [W8]
