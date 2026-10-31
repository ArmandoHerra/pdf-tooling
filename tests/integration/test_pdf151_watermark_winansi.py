"""PDF-151 -- `watermark --text` warns and draws `?` for characters outside WinAnsi.

THE DEFECT (ledger `d8d5dfa6f0`, carrier B-525). ``watermark base.pdf --text
'A漢😀B' -O w.pdf -o json`` exited 0 with ``warnings: []`` and an empty stderr
while the page drew ``/F2 48 Tf (A) Tj /F3 48 Tf (nn) Tj /F2 48 Tf (B) Tj`` with
``/F3 /ZapfDingbats`` -- a filled square for every character the base-14 font
cannot encode. Control characters (newline, ESC, ...) did the same, because
reportlab's own ``winansi`` codec has no code for U+0000-U+001F and U+007F.

THE FIX under test (operator ruling OR-71): ``ops/overlay.py::watermark_run``
replaces every such character with ``?`` before the text reaches the engine and
carries exactly one run-level warning naming each as ``U+XXXX``; the check
precedes the dry/real fork, so ``--dry-run`` predicts it. Exit codes are
unchanged.

Provenance of every literal below: ``e83c743`` (v1.3.0-1) as measured
2026-10-28 (PDF-151 Evidence E2-E5).

This module imports NO private name the fix adds (``_drawable_text``,
``_WATERMARK_ENCODING``), so copying it onto a tree without the fix collects
cleanly and the defect nodes fail on assertions, not on ``ImportError``.
"""

from __future__ import annotations

import io
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pypdf import PdfReader  # noqa: E402
from pypdf.generic import ByteStringObject, ContentStream, TextStringObject  # noqa: E402

from pdf_tooling.cli.main import app  # noqa: E402,F401  (registers the engines)
from pdf_tooling.ops.overlay import watermark_run  # noqa: E402
from pdf_tooling.safety.policy import SafetyPolicy  # noqa: E402
from registry import run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

U: Final[str] = "A漢😀B"
W: Final[str] = (
    "--text: 2 character(s) outside the font's WinAnsi encoding were replaced with '?': "
    "U+6F22, U+1F600"
)
#: The pre-existing run-level warnings (E3): carriage of an encrypted input, and a blank page.
W_ENC: Final[str] = "enc.pdf: input is encrypted; watermark writes its output unencrypted"
BLANK: Final[str] = (
    "blank page(s) with no content stream: [1] -- overlay and underlay are equivalent there"
)
BAD_FONTS: Final[frozenset[str]] = frozenset({"/ZapfDingbats", "/Symbol"})

_cell_counter = itertools.count()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _arg(raw: bytes) -> str:
    """The argv string whose OS encoding is exactly *raw*."""
    return os.fsdecode(raw)


def _operand_bytes(obj: Any) -> bytes:
    if isinstance(obj, ByteStringObject):
        return bytes(obj)
    if isinstance(obj, TextStringObject):
        return obj.get_original_bytes()
    raise AssertionError(f"unexpected Tj operand type {type(obj)!r}")


def _inspect(reader: PdfReader) -> tuple[list[str], list[tuple[str, bytes]]]:
    """Page 1's `/Resources/Font` BaseFont names, and each `Tj` as (BaseFont, operand bytes).

    Reads the page's merged `/Contents` and its own font resources (E1: the layer is
    merged into the page, it is not an XObject at this version).
    """
    page = reader.pages[0]
    resources = page.get("/Resources")
    fonts_dict = {}
    if resources is not None:
        fonts_dict = resources.get_object().get("/Font", {})
        fonts_dict = fonts_dict.get_object() if hasattr(fonts_dict, "get_object") else fonts_dict
    base_of = {name: str(font.get_object().get("/BaseFont")) for name, font in fonts_dict.items()}
    contents = page.get_contents()
    stream = ContentStream(contents, reader)
    current = ""
    shown: list[tuple[str, bytes]] = []
    for operands, operator in stream.operations:
        if operator == b"Tf":
            current = base_of.get(str(operands[0]), "?unknown")
        elif operator == b"Tj":
            shown.append((current, _operand_bytes(operands[0])))
    return sorted(set(base_of.values())), shown


def _page_of(path: Path) -> tuple[list[str], list[tuple[str, bytes]]]:
    return _inspect(PdfReader(str(path)))


def _watermark_ops(path: Path) -> tuple[list[str], list[tuple[str, bytes]]]:
    """Fonts, and only the watermark's `Tj`s (the source text is drawn in plain Helvetica)."""
    fonts, shown = _page_of(path)
    return fonts, [item for item in shown if item[0] != "/Helvetica"]


def _fonts_clean(fonts: Sequence[str]) -> bool:
    return not (set(fonts) & BAD_FONTS)


def _listing(cell: Path) -> list[str]:
    return sorted(p.name for p in cell.iterdir())


def _keys(value: Any) -> Any:
    """The recursive key skeleton of a JSON document (values dropped, order kept)."""
    if isinstance(value, dict):
        return [(k, _keys(v)) for k, v in value.items()]
    if isinstance(value, list):
        return [_keys(v) for v in value if isinstance(v, (dict, list))]
    return None


def _norm_stdout(text: str) -> str:
    return re.sub(r'"duration_ms": \d+', '"duration_ms": N', text)


@pytest.fixture(scope="module")
def fixtures_dir(tmp_path_factory: pytest.TempPathFactory, corpus: Any) -> Path:
    root = tmp_path_factory.mktemp("pdf151-fixtures")
    (root / "a.txt").write_text("hello\n", encoding="utf-8")
    made = run_cli("create", "a.txt", "-O", "base.pdf", "-o", "json", cwd=root, stdin="")
    assert made.returncode == 0, made.stderr[-500:]
    (root / "pw.txt").write_text("pw\n", encoding="utf-8")
    (root / "bad.txt").write_text("bad\n", encoding="utf-8")
    for name in ("pw.txt", "bad.txt"):
        (root / name).chmod(0o600)
    enc = run_cli(
        "encrypt",
        "base.pdf",
        "--user-password-file",
        "pw.txt",
        "--owner-password-file",
        "pw.txt",
        "-O",
        "enc.pdf",
        "-o",
        "json",
        cwd=root,
        stdin="",
    )
    assert enc.returncode == 0, enc.stderr[-500:]
    (root / "corrupt.pdf").write_bytes((root / "base.pdf").read_bytes()[:200])
    shutil.copy(corpus.path("no_contents_page"), root / "blank.pdf")
    shutil.copy(root / "base.pdf", root / "w.pdf")  # the pre-existing output of rows 8-9
    return root


def _cell(tmp_path: Path, fixtures_dir: Path, *names: str) -> Path:
    cell = tmp_path / f"cell{next(_cell_counter)}"
    cell.mkdir()
    for name in names:
        shutil.copy(fixtures_dir / name, cell / name)
    return cell


def _run(
    cell: Path, *argv: str, dry: bool, fmt: str = "json", stdin: str = ""
) -> subprocess.CompletedProcess[str]:
    head = ["--dry-run"] if dry else []
    tail = ["-o", fmt] if fmt else []
    return run_cli("watermark", *head, *argv, *tail, cwd=cell, stdin=stdin)


def _warn_lines(run: subprocess.CompletedProcess[str]) -> list[str]:
    return [ln for ln in run.stderr.splitlines() if ln.startswith("warning: ")]


def _carries(run: subprocess.CompletedProcess[str], message: str) -> None:
    """'Carries W': the envelope once, the stderr line once, no other `--text:` warning."""
    document = json.loads(run.stdout)
    assert document["warnings"].count(message) == 1, document["warnings"]
    assert _warn_lines(run).count(f"warning: {message}") == 1, run.stderr[-600:]
    others = [ln for ln in _warn_lines(run) if ln.startswith("warning: --text:")]
    assert others == [f"warning: {message}"], others


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


# --------------------------------------------------------------------------- #
# AC1 / AC2 -- the ledger repro, real and dry
# --------------------------------------------------------------------------- #


def test_ac1_ledger_repro_warns_and_draws_question_mark(tmp_path: Path, fixtures_dir: Path) -> None:
    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    run = _run(cell, "base.pdf", "--text", U, "-O", "w.pdf", dry=False)
    assert run.returncode == 0, run.stderr[-500:]
    document = json.loads(run.stdout)
    assert document["schema_version"] == 1
    assert document["warnings"] == [W], document["warnings"]
    _carries(run, W)
    fonts, shown = _watermark_ops(cell / "w.pdf")
    assert _fonts_clean(fonts), f"fonts: {fonts}"
    assert [op for _, op in shown] == [b"A??B"], shown
    assert {font for font, _ in shown} == {"/Helvetica-Bold"}, shown
    text = run_cli("text", "w.pdf", "-o", "json", cwd=cell, stdin="")
    assert text.returncode == 0, text.stderr[-300:]
    assert "A??B" in text.stdout and "■" not in text.stdout, text.stdout[-300:]


def test_ac2_dry_run_predicts_the_warning(tmp_path: Path, fixtures_dir: Path) -> None:
    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    before = (cell / "base.pdf").read_bytes()
    dry = _run(cell, "base.pdf", "--text", U, "-O", "w.pdf", dry=True)
    assert dry.returncode == 0, dry.stderr[-500:]
    _carries(dry, W)
    assert _listing(cell) == ["base.pdf"]
    assert (cell / "base.pdf").read_bytes() == before
    real_cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    real = _run(real_cell, "base.pdf", "--text", U, "-O", "w.pdf", dry=False)
    assert json.loads(dry.stdout)["warnings"] == json.loads(real.stdout)["warnings"]
    assert (dry.returncode, real.returncode) == (0, 0)


# --------------------------------------------------------------------------- #
# AC3 -- the replaced set is what the engine cannot draw
# --------------------------------------------------------------------------- #

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
)


def _engine_layer(text: str) -> tuple[list[str], list[tuple[str, bytes]]] | None:
    """What the product's own adapter draws for *text* in Helvetica-Bold, or None if it refuses."""
    from pdf_tooling.adapters.reportlab_compose import ReportlabComposeAdapter

    buffer = io.BytesIO()
    try:
        ReportlabComposeAdapter().render_text_layer(
            text,
            page_size=(612.0, 792.0),
            font="Helvetica-Bold",
            font_size=48.0,
            color=(0.5, 0.5, 0.5),
            opacity=0.3,
            rotate_deg=45.0,
            out=buffer,
        )
    except Exception:  # noqa: BLE001 - an engine that cannot render it cannot draw it
        return None
    return _inspect(PdfReader(io.BytesIO(buffer.getvalue())))


def test_ac3_replaced_set_is_what_the_engine_cannot_draw(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    drawn_byte: dict[int, bytes] = {}
    non_drawable: set[int] = set()
    for p in SWEEP:
        layer = _engine_layer("A" + chr(p) + "B")
        if layer is None:
            non_drawable.add(p)
            continue
        fonts, shown = layer
        if not _fonts_clean(fonts) or any(font != "/Helvetica-Bold" for font, _ in shown):
            non_drawable.add(p)
            continue
        assert len(shown) == 1, f"U+{p:04X}: {shown}"
        operand = shown[0][1]
        assert len(operand) == 3 and operand[:1] == b"A" and operand[2:] == b"B", (p, operand)
        drawn_byte[p] = operand[1:2]

    low = {p for p in non_drawable if p <= 0xFF}
    assert len(low) == 65, sorted(f"U+{p:04X}" for p in low)
    assert len(non_drawable) == 71, sorted(f"U+{p:04X}" for p in non_drawable)
    for p in (0x09, 0x0A, 0x1B, 0x7F, 0x81, 0x9B):
        assert p in non_drawable, f"U+{p:04X}"
    for p in (0x20, 0xE9, 0x152, 0x2122, 0x20AC, 0x2022):
        assert p not in non_drawable, f"U+{p:04X}"
    assert len(drawn_byte) == len(SWEEP) - 71

    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    base = cell / "base.pdf"
    for p in SWEEP:
        result = watermark_run(
            base,
            text="A" + chr(p) + "B",
            pages_spec=None,
            position="overlay",
            font_size=48.0,
            color=(0.5, 0.5, 0.5),
            opacity=0.3,
            rotate_deg=45.0,
            output=cell / "dry.pdf",
            in_place=False,
            policy=_policy(dry=True),
        )
        warned = bool(result.warnings) and f"U+{p:04X}" in result.warnings[0]
        assert warned == (p in non_drawable), (
            f"U+{p:04X}: warned={warned} engine-non-drawable={p in non_drawable}"
        )
        assert len(result.warnings) == (1 if p in non_drawable else 0), (p, result.warnings)

    everything = "".join(chr(p) for p in SWEEP)
    expected = b"".join(b"?" if p in non_drawable else drawn_byte[p] for p in SWEEP)
    assert len(expected) == 266
    out = cell / "all.pdf"
    watermark_run(
        base,
        text=everything,
        pages_spec=None,
        position="overlay",
        font_size=48.0,
        color=(0.5, 0.5, 0.5),
        opacity=0.3,
        rotate_deg=45.0,
        output=out,
        in_place=False,
        policy=_policy(dry=False),
    )
    fonts, shown = _watermark_ops(out)
    assert _fonts_clean(fonts), f"fonts: {fonts}"
    assert len(shown) == 1 and shown[0][0] == "/Helvetica-Bold", shown
    assert shown[0][1] == expected


# --------------------------------------------------------------------------- #
# AC4 -- the message names characters safely and deterministically
# --------------------------------------------------------------------------- #

PROBES: Final[tuple[tuple[str, str, str], ...]] = (
    ("C1 CSI", "A\u009bB", "U+009B"),
    ("RLO", "A‮B", "U+202E"),
    ("argv byte 0xFF", _arg(b"A\xffB"), "U+DCFF"),
    ("ESC", "A\x1bB", "U+001B"),
)


@pytest.mark.parametrize("dry", [True, False], ids=["dry", "real"])
@pytest.mark.parametrize("fmt", ["json", ""], ids=["json", "default"])
def test_ac4_message_names_code_points_safely(
    tmp_path: Path, fixtures_dir: Path, dry: bool, fmt: str
) -> None:
    def one(text: str) -> subprocess.CompletedProcess[str]:
        cell = _cell(tmp_path, fixtures_dir, "base.pdf")
        return _run(cell, "base.pdf", "--text", text, "-O", "w.pdf", dry=dry, fmt=fmt)

    def entry_of(run: subprocess.CompletedProcess[str]) -> str:
        lines = [ln for ln in run.stderr.split("\n")[:-1] if ln.startswith("warning: --text:")]
        assert len(lines) == 1, run.stderr[-600:]
        assert run.stderr.endswith("\n")
        for line in run.stderr.split("\n")[:-1]:
            assert all(0x20 <= ord(c) <= 0x7E for c in line), repr(line)
        return lines[0].removeprefix("warning: ")

    for label, text, point in PROBES:
        run = one(text)
        assert run.returncode == 0, (label, run.stderr[-300:])
        entry = entry_of(run)
        assert "1 character(s)" in entry and entry.endswith(f": {point}"), (label, entry)
        if fmt == "json":
            warnings = json.loads(run.stdout)["warnings"]
            assert warnings == [entry], (label, warnings)
            assert all(ord(c) < 0x80 for c in warnings[0])

    triple = entry_of(one("漢漢漢"))
    assert "3 character(s)" in triple and triple.endswith(": U+6F22"), triple
    ordered = entry_of(one("😀漢😀"))
    assert "3 character(s)" in ordered and ordered.endswith(": U+1F600, U+6F22"), ordered


# --------------------------------------------------------------------------- #
# AC5 -- drawable text is unchanged
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("dry", [True, False], ids=["dry", "real"])
@pytest.mark.parametrize(
    ("text", "operand"),
    [("AéB", b"A\xe9B"), ("plain", b"plain"), ("A€B", b"A\x80B")],
    ids=["acute", "plain", "euro"],
)
def test_ac5_drawable_text_is_unchanged(
    tmp_path: Path, fixtures_dir: Path, dry: bool, text: str, operand: bytes
) -> None:
    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    run = _run(cell, "base.pdf", "--text", text, "-O", "w.pdf", dry=dry)
    assert run.returncode == 0, run.stderr[-300:]
    assert json.loads(run.stdout)["warnings"] == []
    assert _warn_lines(run) == [], run.stderr[-300:]
    if not dry:
        fonts, shown = _watermark_ops(cell / "w.pdf")
        assert _fonts_clean(fonts), fonts
        assert shown == [("/Helvetica-Bold", operand)], shown


# --------------------------------------------------------------------------- #
# AC6 -- the exit-table matrix (E3, rows 1-19)
# --------------------------------------------------------------------------- #

#: (row, files copied into the cell, argv builder, expected (dry rc, real rc))
Row = tuple[int, tuple[str, ...], Any, tuple[int, int]]


def _t(text: str) -> list[str]:
    return ["--text", text]


ROWS: Final[tuple[Row, ...]] = (
    (1, ("base.pdf",), lambda t: ["base.pdf", *_t(t), "-O", "w.pdf"], (0, 0)),
    (2, (), lambda t: ["missing.pdf", *_t(t), "-O", "w.pdf"], (4, 4)),
    (3, ("base.pdf",), lambda t: ["base.pdf", "-O", "w.pdf"], (2, 2)),
    (4, ("base.pdf",), lambda t: ["base.pdf", *_t(t)], (2, 2)),
    (
        5,
        ("base.pdf",),
        lambda t: ["base.pdf", *_t(t), "--position", "sideways", "-O", "w.pdf"],
        (2, 2),
    ),
    (6, ("base.pdf",), lambda t: ["base.pdf", *_t(t), "--opacity", "2", "-O", "w.pdf"], (2, 2)),
    (7, ("base.pdf",), lambda t: ["base.pdf", *_t(t), "--color", "1,2", "-O", "w.pdf"], (2, 2)),
    (8, ("base.pdf", "w.pdf"), lambda t: ["base.pdf", *_t(t), "-O", "w.pdf"], (5, 5)),
    (9, ("base.pdf", "w.pdf"), lambda t: ["base.pdf", *_t(t), "-O", "w.pdf", "--force"], (0, 0)),
    (10, ("base.pdf",), lambda t: ["base.pdf", *_t(t), "--in-place"], (0, 0)),
    (11, ("base.pdf",), lambda t: ["base.pdf", *_t(t), "--in-place", "-y"], (0, 0)),
    (12, ("base.pdf",), lambda t: ["base.pdf", *_t(t), "--pages", "abc", "-O", "w.pdf"], (2, 2)),
    (13, ("base.pdf",), lambda t: ["base.pdf", *_t(t), "--pages", "9", "-O", "w.pdf"], (2, 2)),
    (14, ("enc.pdf", "pw.txt"), lambda t: ["enc.pdf", *_t(t), "-O", "w.pdf"], (5, 5)),
    (
        15,
        ("enc.pdf", "pw.txt"),
        lambda t: ["enc.pdf", *_t(t), "-O", "w.pdf", "--allow-decrypted-output"],
        (6, 6),
    ),
    (
        16,
        ("enc.pdf", "bad.txt"),
        lambda t: [
            "enc.pdf",
            *_t(t),
            "-O",
            "w.pdf",
            "--allow-decrypted-output",
            "--password-file",
            "bad.txt",
        ],
        (0, 6),
    ),
    (
        17,
        ("enc.pdf", "pw.txt"),
        lambda t: [
            "enc.pdf",
            *_t(t),
            "-O",
            "w.pdf",
            "--allow-decrypted-output",
            "--password-file",
            "pw.txt",
        ],
        (0, 0),
    ),
    (18, ("corrupt.pdf",), lambda t: ["corrupt.pdf", *_t(t), "-O", "w.pdf"], (1, 1)),
    (19, ("blank.pdf",), lambda t: ["blank.pdf", *_t(t), "-O", "w.pdf"], (0, 0)),
)

#: Cells whose stdout is an error envelope, not a result envelope.
ERR_CELLS: Final[Mapping[str, frozenset[int]]] = {
    "dry": frozenset({2, 3, 4, 5, 6, 7, 12, 13, 14, 18}),
    "real": frozenset({2, 3, 4, 5, 6, 7, 8, 12, 13, 14, 15, 16, 18}),
}


def test_ac6_exit_table_pairs(tmp_path: Path, fixtures_dir: Path) -> None:
    problems: list[str] = []
    for row, files, build, expected_rc in ROWS:
        for mode, dry in (("dry", True), ("real", False)):
            cells: dict[str, tuple[subprocess.CompletedProcess[str], list[str]]] = {}
            for column, text in (("plain", "plain"), ("U", U)):
                cell = _cell(tmp_path, fixtures_dir, *files)
                run = _run(cell, *build(text), dry=dry)
                cells[column] = (run, _listing(cell))
            plain, plain_listing = cells["plain"]
            wide, wide_listing = cells["U"]
            label = f"row {row} {mode}"
            want = expected_rc[0 if dry else 1]
            for column, run in (("plain", plain), ("U", wide)):
                if run.returncode != want:
                    problems.append(f"{label} {column}: rc {run.returncode} != {want}")
            if wide_listing != plain_listing:
                problems.append(f"{label}: listing {wide_listing} != {plain_listing}")
            is_err = row in ERR_CELLS[mode]
            plain_doc = json.loads(plain.stdout)
            wide_doc = json.loads(wide.stdout)
            assert ("error" in plain_doc) == is_err, f"{label}: error-envelope expectation"
            assert wide_doc["schema_version"] == 1
            if is_err:
                if (wide.stdout, wide.stderr) != (plain.stdout, plain.stderr):
                    problems.append(f"{label}: ERR cell differs between columns")
                if "--text:" in wide.stderr:
                    problems.append(f"{label}: ERR cell carries a --text: line")
                continue
            if _keys(wide_doc) != _keys(plain_doc):
                problems.append(f"{label}: envelope key skeleton differs")
            try:
                _carries(wide, W)
            except AssertionError as error:
                problems.append(f"{label}: does not carry W: {error}")
                continue
            rest = [w for w in wide_doc["warnings"] if w != W]
            if rest != plain_doc["warnings"]:
                problems.append(
                    f"{label}: warnings minus W {rest} != plain {plain_doc['warnings']}"
                )
            expected_order = {
                (19, "real"): [BLANK, W],
                (16, "dry"): [W, W_ENC],
                (17, "dry"): [W, W_ENC],
                (17, "real"): [W, W_ENC],
            }.get((row, mode))
            if expected_order is not None and wide_doc["warnings"] != expected_order:
                problems.append(f"{label}: order {wide_doc['warnings']} != {expected_order}")
    assert not problems, "\n".join(problems)


def test_ac6_row_20_empty_text_is_unchanged(tmp_path: Path, fixtures_dir: Path) -> None:
    for dry in (True, False):
        cell = _cell(tmp_path, fixtures_dir, "base.pdf")
        run = _run(cell, "base.pdf", "--text", "", "-O", "w.pdf", dry=dry)
        assert run.returncode == 0 and json.loads(run.stdout)["warnings"] == []
        assert _warn_lines(run) == []
        if not dry:
            _, shown = _watermark_ops(cell / "w.pdf")
            assert shown == []


# --------------------------------------------------------------------------- #
# AC7 -- the Python API path
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("dry", [True, False], ids=["dry", "real"])
def test_ac7_python_api_lone_surrogate(tmp_path: Path, fixtures_dir: Path, dry: bool) -> None:
    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    out = cell / "w.pdf"
    result = watermark_run(
        cell / "base.pdf",
        text="A\ud800B",
        pages_spec=None,
        position="overlay",
        font_size=48.0,
        color=(0.5, 0.5, 0.5),
        opacity=0.3,
        rotate_deg=45.0,
        output=out,
        in_place=False,
        policy=_policy(dry=dry),
    )
    assert result.warnings == (
        "--text: 1 character(s) outside the font's WinAnsi encoding were replaced with '?': U+D800",
    )
    if not dry:
        fonts, shown = _watermark_ops(out)
        assert _fonts_clean(fonts), fonts
        assert [op for _, op in shown] == [b"A?B"], shown


# --------------------------------------------------------------------------- #
# AC8 -- the help says what --text can draw
# --------------------------------------------------------------------------- #

HELP_PARAGRAPH: Final[str] = (
    "CHARACTERS. --text is drawn in Helvetica-Bold, a base-14 font that uses the WinAnsi "
    "encoding and embeds nothing. A character outside that encoding -- CJK, emoji, most "
    "non-Latin scripts, and control characters such as a newline or a tab -- is drawn as "
    "'?', and the run warns, naming each one as a U+XXXX code point. --dry-run predicts the "
    "same warning; the exit code is unchanged."
)
HELP_OPTION: Final[str] = (
    "The watermark text. Required. Characters outside WinAnsi are drawn as '?' and named in "
    "a warning."
)


def test_ac8_help_says_what_text_can_draw() -> None:
    env = {**os.environ, "COLUMNS": "100000", "TERM": "dumb", "NO_COLOR": "1"}
    run = run_cli("watermark", "--help", env=env, stdin="")
    assert run.returncode == 0, run.stderr[-300:]
    flat = " ".join(run.stdout.split())
    assert HELP_PARAGRAPH in flat, flat[:1500]
    # The option help may be wrapped inside a table; strip table borders before comparing.
    unboxed = " ".join(re.sub(r"[│┃┆|]", " ", run.stdout).split())
    assert HELP_OPTION in unboxed, unboxed[:2500]
    assert "'overlay' (default)" in flat


# --------------------------------------------------------------------------- #
# AC9 / AC10 -- create and stamp are unchanged
# --------------------------------------------------------------------------- #


def test_ac9_create_is_unchanged(tmp_path: Path) -> None:
    cell = tmp_path / "create"
    cell.mkdir()
    (cell / "u.txt").write_text("A漢😀B\n", encoding="utf-8")
    run = run_cli("create", "u.txt", "-O", "c.pdf", "-o", "json", cwd=cell, stdin="")
    assert run.returncode == 0, run.stderr[-300:]
    # Re-pinned by PDF-161 (OR-88): create names every replaced code point.
    entry = (
        "2 character(s) outside the font's WinAnsi encoding were replaced with '?': "
        "U+6F22, U+1F600 (first on line 1)"
    )
    assert json.loads(run.stdout)["warnings"] == [entry]
    assert _warn_lines(run) == [f"warning: {entry}"], run.stderr[-300:]


def test_ac10_frozen_surface(tmp_path: Path, fixtures_dir: Path) -> None:
    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    plain = _run(cell, "base.pdf", "--text", "plain", "-O", "p.pdf", dry=False)
    wide = _run(cell, "base.pdf", "--text", U, "-O", "w.pdf", dry=False)
    p_doc, w_doc = json.loads(plain.stdout), json.loads(wide.stdout)
    assert p_doc["schema_version"] == w_doc["schema_version"] == 1
    assert _keys(p_doc) == _keys(w_doc)
    assert (plain.returncode, wide.returncode) == (0, 0)
    # stamp keeps an empty dry-run warnings list.
    stamp = run_cli(
        "stamp",
        "--dry-run",
        "base.pdf",
        "--from",
        "base.pdf",
        "-O",
        "s.pdf",
        "-o",
        "json",
        cwd=cell,
        stdin="",
    )
    assert stamp.returncode == 0, stamp.stderr[-300:]
    assert json.loads(stamp.stdout)["warnings"] == []
