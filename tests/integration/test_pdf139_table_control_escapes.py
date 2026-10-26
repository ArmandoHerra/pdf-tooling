"""PDF-139 -- ``-o table`` cells render control characters as visible escapes (CWE-150, B-426).

A hostile PDF can put terminal control sequences in ``/Title``; a hostile operand can
carry them in its filename. Table output used to write them raw. Every ``Cc`` code point
now renders as ``\\t``/``\\n``/``\\r``/``\\xNN`` text. ``-o json``/``-o ndjson`` are a frozen
contract and stay byte-unchanged (asserted by sha256 below).

The hostile fixture is built here with the stdlib only (``pikepdf.String(str)`` silently
drops ESC and BEL, so it cannot carry the claim). Output is captured as BYTES: ``run_cli``
is ``text=True`` and its universal newlines would hide a bare CR.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import console_script, run_cli_with_pty  # noqa: E402

TITLE = "A\x1b[31mRED\x1b[0m B\x1b]0;pwned\x07 C\x9b2J D\rE\x07F\x7fG é 中文 H\tI\nJ"
ESCAPED_TITLE = r"A\x1b[31mRED\x1b[0m B\x1b]0;pwned\x07 C\x9b2J D\rE\x07F\x7fG é 中文 H\tI\nJ"
FIXTURE_NAME = "hostile_title.pdf"
EVIL_NAME = "evil\x1b[31m\x07.pdf"

# Recorded at base 68447f3 (origin/main), 2026-10-26, CPython 3.14 (step 0, before any edit).
FIXTURE_SHA256 = "b705a8723ce6c86045d0776bcf3b96d548fa964322cc53c1928395dc2aa7cb87"
FROZEN_SHA256 = {
    "meta_json": "eeb567b63b465d12327e784acf3ebbf45997b84518f4c9787fb49ab625fffe52",
    "meta_ndjson": "8b27220ab9c79f907f31649c24c8e0df488212c45c95ef4980c0a1f570062cc8",
    "info_json": "6525eab4983bd6361a7a63fc9eaff4ae06a8e11e8f726a124b87c4f72516ad74",
    "info_ndjson": "a960858d53562054daffed8937807952df9cfae7e4a24c2bd2de22fcf40bb78c",
}


def build_hostile_title_pdf(path: Path) -> None:
    """Write a minimal one-page PDF whose /Info /Title is TITLE as a UTF-16BE hex string."""
    title_hex = (b"\xfe\xff" + TITLE.encode("utf-16-be")).hex().upper()
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>",
        f"<< /Title <{title_hex}> >>".encode("ascii"),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(bodies, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(bodies) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R /Info 4 0 R "
        "/ID [<00112233445566778899AABBCCDDEEFF> <00112233445566778899AABBCCDDEEFF>] >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode("ascii")
    path.write_bytes(bytes(out))


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - argv is the product's own console script
        [*console_script(), *argv],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        cwd=cwd,
        check=False,
        timeout=120,
    )


def count_f(data: bytes) -> int:
    """Forbidden bytes in table stdout: C0 except LF, DEL, and every UTF-8 C1 (c2 80..c2 9f)."""
    c0 = sum(1 for byte in data if (byte < 0x20 and byte != 0x0A) or byte == 0x7F)
    return c0 + len(re.findall(rb"\xc2[\x80-\x9f]", data))


def _fixture(tmp_path: Path) -> Path:
    build_hostile_title_pdf(tmp_path / FIXTURE_NAME)
    return tmp_path


def _evil(tmp_path: Path) -> Path:
    fixture = _fixture(tmp_path)
    (fixture / EVIL_NAME).write_bytes((fixture / FIXTURE_NAME).read_bytes())
    return fixture


def test_fixture_is_deterministic_and_carries_the_title_verbatim(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    assert hashlib.sha256((fixture / FIXTURE_NAME).read_bytes()).hexdigest() == FIXTURE_SHA256
    proc = _run(["meta", "get", FIXTURE_NAME, "-o", "json"], fixture)
    assert proc.returncode == 0
    assert proc.stderr == b""
    assert json.loads(proc.stdout)["info"]["Title"] == TITLE


def test_ac3_meta_get_table_escapes_the_hostile_title(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    proc = _run(["meta", "get", FIXTURE_NAME, "-o", "table"], fixture)
    assert proc.returncode == 0
    assert proc.stderr == b""
    assert count_f(proc.stdout) == 0
    title_lines = [line for line in proc.stdout.split(b"\n") if line.startswith(b"  Title: ")]
    assert len(title_lines) == 1
    assert title_lines[0] == ("  Title: " + ESCAPED_TITLE).encode("utf-8")
    assert b"\xc3\xa9" in title_lines[0]
    assert b"\xe4\xb8\xad\xe6\x96\x87" in title_lines[0]


def test_ac4_meta_get_table_under_a_pty_carries_no_escape(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    result = run_cli_with_pty(
        "meta", "get", FIXTURE_NAME, "-o", "table", pty_stream="stdout", cwd=fixture
    )
    assert result.returncode == 0
    data = result.stdout.encode("utf-8")
    for needle in (b"\x1b", b"\x07", b"\x7f", b"\xc2\x9b"):
        assert needle not in data, needle
    assert ESCAPED_TITLE in result.stdout  # the escaped text, not the raw bytes


def test_ac5_cell_verbs_escape_a_hostile_operand_name(tmp_path: Path) -> None:
    fixture = _evil(tmp_path)
    shown = EVIL_NAME.replace("\x1b", "\\x1b").replace("\x07", "\\x07").encode("utf-8")

    rotate = _run(
        ["rotate", EVIL_NAME, "--pages", "1", "--angle", "90", "--out-dir", "out", "-o", "table"],
        fixture,
    )
    assert rotate.returncode == 0, rotate.stderr
    assert count_f(rotate.stdout) == 0
    assert shown in rotate.stdout
    assert os.listdir(fixture / "out") == [EVIL_NAME]  # display-only: the real name is kept

    info = _run(["info", EVIL_NAME, "-o", "table"], fixture)
    assert info.returncode == 0, info.stderr
    assert count_f(info.stdout) == 0
    assert shown in info.stdout


def test_ac6_json_and_ndjson_are_byte_unchanged_on_the_hostile_inputs(tmp_path: Path) -> None:
    fixture = _evil(tmp_path)
    runs = {
        "meta_json": _run(["meta", "get", FIXTURE_NAME, "-o", "json"], fixture),
        "meta_ndjson": _run(["meta", "get", FIXTURE_NAME, "-o", "ndjson"], fixture),
        "info_json": _run(["info", EVIL_NAME, "-o", "json"], fixture),
        "info_ndjson": _run(["info", EVIL_NAME, "-o", "ndjson"], fixture),
    }
    for name, proc in runs.items():
        assert proc.returncode == 0, (name, proc.stderr)
        assert hashlib.sha256(proc.stdout).hexdigest() == FROZEN_SHA256[name], name
    for name in ("meta_json", "meta_ndjson"):
        out = runs[name].stdout
        assert b"\\u001b]0;pwned\\u0007" in out
        assert b"\xc2\x9b" in out
        assert json.loads(out)["info"]["Title"] == TITLE
