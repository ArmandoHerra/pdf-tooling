"""PDF-157 -- stderr operand echoes carry no terminal control bytes (CWE-150, B-496).

PDF-139 escaped table *cells*. The stderr lines that echo an operand or a document
string (``render_error_table``, the ``warning:`` loop, the ``AtomicWriter`` sink) now go
through :func:`escape_controls_multiline`, the same 65-code-point ``Cc`` rule minus TAB and
LF, so the product's own multi-line messages survive. Escaping is display-only: the
payload and the ``-o json`` bytes still carry the raw string (AC5 b).

``escape_controls_multiline`` is NEW in this change, so it is resolved lazily (never at
module scope): this module collects at base and the counted arms fail on assertions.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from pdf_tooling.output.table import render_error_table

#: Unicode category Cc: the 65 code points.
CONTROLS = [*range(0x00, 0x20), *range(0x7F, 0xA0)]
#: PDF-139 AC1's identity set: everything outside Cc that must pass through unchanged.
IDENT = [
    *range(0x20, 0x7F),
    *range(0xA0, 0x100),
    0x4E2D,
    0x6587,
    0x1F600,
    0x202E,
    0x2028,
]
#: The full (one-line) rule, LF -> \n.
EXPECTED = {c: {0x09: "\\t", 0x0A: "\\n", 0x0D: "\\r"}.get(c, f"\\x{c:02x}") for c in CONTROLS}
#: The multiline rule: TAB and LF stay real characters.
EXPECTED_ML = {c: (chr(c) if c in (0x09, 0x0A) else EXPECTED[c]) for c in CONTROLS}


def _multiline() -> Callable[[str], str]:
    """Resolve the NEW helper at call time; absent => an assertion, not a collection fault."""
    from pdf_tooling.output import table

    helper = getattr(table, "escape_controls_multiline", None)
    assert helper is not None, "output/table.py has no escape_controls_multiline (PDF-157 D1)"
    return helper  # type: ignore[no-any-return]


def test_ac1_render_error_table_escapes_message_and_path() -> None:
    assert len(CONTROLS) == 65
    assert len(IDENT) == 196
    assert len(EXPECTED_ML) == 65

    bad_msg = [
        c
        for c in CONTROLS
        if render_error_table({"message": "m" + chr(c)}) != "error: m" + EXPECTED_ML[c]
    ]
    assert len(bad_msg) == 0, f"{len(bad_msg)} message code points mis-rendered: {bad_msg}"

    bad_path = [
        c
        for c in CONTROLS
        if render_error_table({"message": "m", "path": "p" + chr(c)})
        != "error: m (p" + EXPECTED[c] + ")"
    ]
    assert bad_path == [], f"{len(bad_path)} path code points mis-rendered: {bad_path}"

    moved = [
        c
        for c in IDENT
        if render_error_table({"message": chr(c), "path": chr(c)}) != f"error: {chr(c)} ({chr(c)})"
    ]
    assert moved == [], f"identity set moved: {moved}"

    helper = _multiline()
    tie = [c for c in CONTROLS if helper(chr(c)) != EXPECTED_ML[c]]
    assert tie == []
    assert [c for c in IDENT if helper(chr(c)) != chr(c)] == []
    # The product's own multi-line hint survives; a hostile ESC inside it does not.
    hint = "refusing (stdin is not a terminal)\nhint: re-run with -y:\n  cmd 'a\x1b[31m\x07'"
    assert (
        helper(hint)
        == "refusing (stdin is not a terminal)\nhint: re-run with -y:\n  cmd 'a\\x1b[31m\\x07'"
    )


def _result(warning: str) -> object:
    from pdf_tooling.models import OperationResult

    return OperationResult(
        schema_version=1,
        verb="rotate",
        dry_run=False,
        items=(),
        warnings=(warning,),
        duration_ms=0,
    )


def test_ac5_warning_sinks_write_no_control_bytes(
    capsysbinary: pytest.CaptureFixture[bytes], tmp_path: Path
) -> None:
    from pdf_tooling.output import OutputFormat, emit_result, render_payload
    from pdf_tooling.safety.atomic import AtomicWriter, _default_warn
    from pdf_tooling.safety.policy import SafetyPolicy

    def forbidden(data: bytes) -> int:
        # F_ml: C0 except TAB/LF, DEL, and every UTF-8 C1 (c2 80 .. c2 9f).
        c0 = sum(1 for b in data if (b < 0x20 and b not in (0x09, 0x0A)) or b == 0x7F)
        c1 = sum(1 for i in range(len(data) - 1) if data[i] == 0xC2 and 0x80 <= data[i + 1] <= 0x9F)
        return c0 + c1

    raw = "w \x1b[31m\x07 \x9b\r end"
    shown = b"warning: w \\x1b[31m\\x07 \\x9b\\r end\n"

    # (a) the shared envelope loop, table format.
    emit_result(_result(raw), OutputFormat.TABLE)  # type: ignore[arg-type]
    err = capsysbinary.readouterr().err
    assert forbidden(err) == 0, err
    assert err == shown

    # (b) json format: identical stderr line; stdout is the raw payload, display-only escaping.
    result = _result(raw)
    emit_result(result, OutputFormat.JSON)  # type: ignore[arg-type]
    captured = capsysbinary.readouterr()
    assert captured.err == shown
    payload = result.to_dict()  # type: ignore[attr-defined]
    assert captured.out.decode("utf-8") == render_payload(payload, OutputFormat.JSON) + "\n"
    assert b"\\u001b" in captured.out
    assert json.loads(captured.out)["warnings"] == [raw]

    # (c) D4: the AtomicWriter stderr sink survives PDF-156, so it is escaped here.
    _default_warn("x \x1b]0;t\x07 y")
    err = capsysbinary.readouterr().err
    assert forbidden(err) == 0, err
    assert err == b"warning: x \\x1b]0;t\\x07 y\n"

    policy = SafetyPolicy(
        dry_run=False,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )
    writer = AtomicWriter(tmp_path / "out.pdf", policy=policy)
    writer._warn("atomicity degraded: a\x1b[31m\x07.pdf")
    err = capsysbinary.readouterr().err
    assert forbidden(err) == 0, err
    assert writer.warnings == ["atomicity degraded: a\x1b[31m\x07.pdf"]  # the list stays raw
