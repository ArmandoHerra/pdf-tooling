"""PDF-139 -- the table renderer escapes control characters (CWE-150, B-426)."""

from __future__ import annotations

import ast
from pathlib import Path

from pdf_tooling.output.table import _cell

TITLE = "A\x1b[31mRED\x1b[0m B\x1b]0;pwned\x07 C\x9b2J D\rE\x07F\x7fG é 中文 H\tI\nJ"
ESCAPED_TITLE = r"A\x1b[31mRED\x1b[0m B\x1b]0;pwned\x07 C\x9b2J D\rE\x07F\x7fG é 中文 H\tI\nJ"

#: Unicode category Cc. EXPECTED restates table.py's rule rather than being independent
#: of it; ESCAPED_TITLE above is the hand-written literal oracle.
CONTROLS = [*range(0x00, 0x20), *range(0x7F, 0xA0)]
EXPECTED = {c: {0x09: "\\t", 0x0A: "\\n", 0x0D: "\\r"}.get(c, f"\\x{c:02x}") for c in CONTROLS}
IDENT = [
    *range(0x20, 0x7F),
    *range(0xA0, 0x100),
    0x4E2D,
    0x6587,
    0x1F600,
    0x202E,
    0x2028,
]

SRC = Path(__file__).resolve().parents[2] / "src" / "pdf_tooling"


def test_ac1_escape_controls_maps_every_cc_code_point_and_nothing_else() -> None:
    assert len(CONTROLS) == 65
    assert len(IDENT) == 196
    bad = [c for c in CONTROLS if _cell(chr(c)) != EXPECTED[c]]
    assert bad == []
    moved = [c for c in IDENT if _cell(chr(c)) != chr(c)]
    assert moved == []
    assert _cell(TITLE) == ESCAPED_TITLE

    from pdf_tooling.output.table import escape_controls

    for c in (*CONTROLS, *IDENT):
        assert escape_controls(chr(c)) == _cell(chr(c))
    assert escape_controls(TITLE) == ESCAPED_TITLE


def test_ac2_cell_escapes_strings_and_keeps_none_bool_and_repr_cells() -> None:
    assert _cell("a\x1bb") == "a\\x1bb"
    assert _cell(None) == "-"
    assert _cell(True) == "yes"
    assert _cell(False) == "no"
    assert _cell(3) == "3"
    assert _cell({"wrote_xmp": True}) == str({"wrote_xmp": True})
    assert _cell("é 中文") == "é 中文"


def _module_level_imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_ac8_table_module_import_set_is_unchanged() -> None:
    assert _module_level_imports(SRC / "output" / "table.py") == {"__future__", "typing"}
    tree = ast.parse((SRC / "cli" / "cmd_meta_get.py").read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "pdf_tooling.output.table"
        for alias in node.names
    }
    assert "escape_controls" in imported
