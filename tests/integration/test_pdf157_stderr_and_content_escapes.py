"""PDF-157 -- stderr operand echoes and ``text``/``tables`` table output carry no terminal
control bytes (CWE-150, B-496).

PDF-139 escaped ``-o table`` *cells* only. Two neighbouring routes still wrote raw control
bytes to a terminal: every stderr line that echoes an operand (``error:`` via
``render_error_table`` and ``info``'s own per-outcome line, ``warning:`` lines) and the
destination-less table-mode stdout of the two content verbs (``text``'s body, ``tables``'
embedded grids and their ``# source=`` line). They are escaped at the point of display
only. ``-o json``/``-o ndjson`` bytes, every envelope key, every exit code and every file a
verb writes are frozen (AC9, AC10: sha256 against literals recorded at the rebased base).

All captures are BYTES (``registry.run_cli`` is ``text=True`` and its universal newlines
would hide a bare CR). The hostile PDFs are built here with the stdlib only (no binary in
git): a standard-14 Helvetica with an identity ``/ToUnicode`` CMap, so a content byte
reaches extraction as the Latin-1 code point of the same value.

STEP-0 REACHABILITY (measured at base 7b04b5d, 2026-10-30, CPython 3.14.7, pypdfium2
5.14.0, pdfplumber 0.11.10; code points U+001B U+0007 U+007F U+009B U+0001)::

    engine                       all five code points returned by the engine
    text            (fast)       yes
    text --layout   (layout)     yes
    tables          (lines)      yes  (cell (1,1); shape 2x2, bbox [20,60,390,140])

All three engines pass them, so every AC6/AC7/AC8 arm is counted, none is a guard.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import console_script, run_cli_with_pty  # noqa: E402

CONTENT = "A\x1b[31mRED\x1b[0m B\x1b]0;pwned\x07 C\x9b2J D\x7fE \x01F \xe9"
C0 = "c\x07"
CODE_POINTS = ("\x1b", "\x07", "\x7f", "\x9b", "\x01", "\xe9")

CONTENT_NAME = "hostile_content.pdf"
BENIGN_NAME = "benign_content.pdf"
BLANK_NAME = "blank.pdf"
NOPE = "nope\x1b[31m\x07.pdf"
BAD = "bad\x1b[31m\x07.pdf"
EVIL = "evil\x1b[31m\x07.pdf"
EVILDIR = "dir\x1b[31m\x07.pdf"
EVIL1 = "evil\x1b[31m\x07-1.pdf"
EVIL2 = "evil\x1b[31m\x07-2.pdf"
SHOWN_EVIL = r"evil\x1b[31m\x07.pdf"

#: Recorded at the rebased base 7b04b5d (origin/main, "[PDF-155] fix: report a present XMP
#: packet in meta get / info instead of null"), 2026-10-30, CPython 3.14.7, step 0 (before
#: any src/ edit). Two consecutive base runs of all eight outputs were byte-identical;
#: ``duration_ms`` (a timing field, 0 in both runs) and the engine ``version`` strings
#: (lock-pinned) are normalized so a slow host or a Dependabot bump cannot move a digest.
FIXTURE_SHA256 = "6eb21bdf38f5adb3007fb98950cadf90491b16a6557ab435d16e96cfe4c8b29b"
BENIGN_SHA256 = "c6dc8b9839456db700628fe4bc9cdef363fcd2197eb4078f441cda37c09841e1"
BLANK_SHA256 = "f95c9ead787237ed32dbe0c47602a59c1e2013784ea36d4f5f5f6b0a7aadf292"
BENIGN_TEXT_STDOUT_SHA256 = "247179ad1cfd462143ca0a9d1b9f63bcbdc47080a7fc1549754c17ad06803a35"
TXT_ARTIFACT_DIGEST = "d6d514322de65b83661d178a2f272cc80cabd5841831a2bc469762599affae99"
TABLES_CSV_SHA256 = "fa61fb7de8c0157dc3d572446ec8994c314f4a10290fd4959a0eac280d5875e7"
#: stdout LF count of ``text CONTENT -o table`` at base (4 body lines' breaks incl. the echo's).
TEXT_BODY_LF_COUNT = 4
FROZEN_SHA256 = {
    "text_json": "6b18aee481b6c53ea47d6928c5c9179ae71591676930a63596094b7161f8adc8",
    "text_ndjson": "3229e9b919794790feaf338ab9d95d2a856cd7b9d82847848a2a35f496c9c8c1",
    "text_layout_json": "02cdbe2d3736665fb504944a035d6db6734ab5b8cbe83bdacff5a274ba9b0f9c",
    "tables_json": "e60de672b7b0bb7fcb870cf602f9864a2ac5f97101acd4b0ac05be963b54c85b",
    "tables_ndjson": "8a6c8f924745024882038b6b2efdf4552e1db03c31c8fd765df06faa77ee2787",
    "info_nope_json": "10e49ee212794d17e87d92f0d1a2809195147fad766623c355a96d70ca2780b5",
    "info_nope_ndjson": "10e49ee212794d17e87d92f0d1a2809195147fad766623c355a96d70ca2780b5",
    "rotate_nope_json": "10e49ee212794d17e87d92f0d1a2809195147fad766623c355a96d70ca2780b5",
}
FROZEN_RC = {
    "text_json": 0,
    "text_ndjson": 0,
    "text_layout_json": 0,
    "tables_json": 0,
    "tables_ndjson": 0,
    "info_nope_json": 4,
    "info_nope_ndjson": 4,
    "rotate_nope_json": 4,
}


# --------------------------------------------------------------------------- fixtures


def _hex(text: str) -> str:
    return "<" + text.encode("latin-1").hex().upper() + ">"


def _assemble(bodies: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(bodies, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(bodies) + 1}\n".encode("ascii") + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R "
        "/ID [<00112233445566778899AABBCCDDEEFF> <00112233445566778899AABBCCDDEEFF>] >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


def _stream(data: bytes) -> bytes:
    return f"<< /Length {len(data)} >>\nstream\n".encode("ascii") + data + b"\nendstream"


def _page_pdf(content_stream: bytes) -> bytes:
    cmap = (
        b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        b"/CMapName /Adobe-Identity-UCS def /CMapType 2 def\n"
        b"1 begincodespacerange <00> <FF> endcodespacerange\n"
        b"1 beginbfrange <00> <FF> <0000> endbfrange\n"
        b"endcmap CMapName currentdict /CMap defineresource pop end end\n"
    )
    widths = " ".join(["500"] * 256)
    font = (
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding "
        f"/FirstChar 0 /LastChar 255 /Widths [{widths}] /ToUnicode 6 0 R >>"
    ).encode("ascii")
    return _assemble(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            _stream(content_stream),
            font,
            _stream(cmap),
        ]
    )


def build_hostile_content_pdf(path: Path, *, content: str = CONTENT, c0: str = C0) -> None:
    """One page: CONTENT, ``plain line``, and a ruled 2x2 grid (col 0 narrow, col 1 wide).

    Cell (1,1) holds CONTENT whole (156 pt at 8 pt in a 330 pt column); cell (1,0) holds
    ``C0`` so column 0's width depends on whether widths are computed on escaped text.
    """

    def run(x: int, y: int, text: str) -> str:
        return f"BT /F1 8 Tf {x} {y} Td {_hex(text)} Tj ET\n"

    ops = "0.5 w\n20 100 40 40 re S\n60 100 330 40 re S\n20 60 40 40 re S\n60 60 330 40 re S\n"
    ops += run(24, 180, content) + run(24, 165, "plain line")
    ops += run(24, 115, "a") + run(64, 115, "b") + run(24, 75, c0) + run(64, 75, content)
    path.write_bytes(_page_pdf(ops.encode("ascii")))


def build_blank_pdf(path: Path) -> None:
    """One page, empty content stream: ``text`` and ``tables`` both warn."""
    path.write_bytes(_page_pdf(b""))


# --------------------------------------------------------------------------- helpers


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
    """F (single-line displays): C0 except LF, DEL, and every UTF-8 C1 (c2 80 .. c2 9f)."""
    c0 = sum(1 for byte in data if (byte < 0x20 and byte != 0x0A) or byte == 0x7F)
    return c0 + len(re.findall(rb"\xc2[\x80-\x9f]", data))


def count_f_ml(data: bytes) -> int:
    """F_ml (multiline displays): F minus TAB."""
    c0 = sum(1 for byte in data if (byte < 0x20 and byte not in (0x09, 0x0A)) or byte == 0x7F)
    return c0 + len(re.findall(rb"\xc2[\x80-\x9f]", data))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize(data: bytes) -> bytes:
    """The documented freeze normalization: timing and lock-pinned engine versions only."""
    data = re.sub(rb'"duration_ms": [0-9.]+', b'"duration_ms": 0', data)
    return re.sub(rb'"version": "[^"]*"', b'"version": "X"', data)


def _fixture(tmp_path: Path) -> Path:
    build_hostile_content_pdf(tmp_path / CONTENT_NAME)
    build_hostile_content_pdf(tmp_path / BENIGN_NAME, content="plain", c0="c")
    build_blank_pdf(tmp_path / BLANK_NAME)
    return tmp_path


def _frozen_runs(fixture: Path) -> dict[str, subprocess.CompletedProcess[bytes]]:
    argvs = {
        "text_json": ["text", CONTENT_NAME, "-o", "json"],
        "text_ndjson": ["text", CONTENT_NAME, "-o", "ndjson"],
        "text_layout_json": ["text", "--layout", CONTENT_NAME, "-o", "json"],
        "tables_json": ["tables", CONTENT_NAME, "-o", "json"],
        "tables_ndjson": ["tables", CONTENT_NAME, "-o", "ndjson"],
        "info_nope_json": ["info", NOPE, "-o", "json"],
        "info_nope_ndjson": ["info", NOPE, "-o", "ndjson"],
        "rotate_nope_json": [
            "rotate", NOPE, "--pages", "1", "--angle", "90", "--out-dir", "out", "-o", "json",
        ],
    }  # fmt: skip
    return {name: _run(argv, fixture) for name, argv in argvs.items()}


def test_fixtures_are_deterministic_and_reach_every_engine_unfiltered(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    assert sha((fixture / CONTENT_NAME).read_bytes()) == FIXTURE_SHA256
    assert sha((fixture / BENIGN_NAME).read_bytes()) == BENIGN_SHA256
    assert sha((fixture / BLANK_NAME).read_bytes()) == BLANK_SHA256
    for argv in (["text", CONTENT_NAME], ["text", "--layout", CONTENT_NAME]):
        proc = _run([*argv, "-o", "json"], fixture)
        assert proc.returncode == 0 and proc.stderr == b"", proc.stderr  # no repair warning
        page = json.loads(proc.stdout)["pages"][0]
        text = page["text"] if "text" in page else "\n".join(b["text"] for b in page["blocks"])
        for point in CODE_POINTS:
            assert point in text, (argv, point)
    proc = _run(["tables", CONTENT_NAME, "-o", "json"], fixture)
    assert proc.returncode == 0 and proc.stderr == b""
    table = json.loads(proc.stdout)["tables"][0]
    assert (table["row_count"], table["col_count"]) == (2, 2)
    assert table["rows"] == [["a", "b"], [C0, CONTENT]]


# --------------------------------------------------------------------------- Group A


def test_ac2_info_hostile_operand_stderr_is_escaped(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    (fixture / BAD).write_bytes(b"not a pdf at all")

    # (a) run-scoped refusal of a MISSING operand: render_error_table via print.
    proc = _run(["info", NOPE, "-o", "table"], fixture)
    assert proc.returncode == 4
    assert count_f_ml(proc.stderr) == 0, proc.stderr
    assert rb"nope\x1b[31m\x07.pdf" in proc.stderr

    # (b) the same under a real terminal on stderr.
    result = run_cli_with_pty("info", NOPE, "-o", "table", pty_stream="stderr", cwd=fixture)
    assert result.returncode == 4
    for point in ("\x1b", "\x07", "\x7f", "\x9b"):
        assert point not in result.stderr, (point, result.stderr)

    # (c) guard: json writes nothing on stderr.
    proc = _run(["info", NOPE, "-o", "json"], fixture)
    assert proc.returncode == 4
    assert proc.stderr == b""

    # (d) item-scoped failure: info_command's own typer.echo(err=True) line.
    proc = _run(["info", BAD, "-o", "table"], fixture)
    assert proc.returncode == 1
    error_lines = [line for line in proc.stderr.split(b"\n") if line.startswith(b"error: ")]
    assert len(error_lines) == 1, proc.stderr
    assert error_lines[0].endswith(rb" (bad\x1b[31m\x07.pdf)"), error_lines[0]
    assert count_f_ml(error_lines[0]) == 0, error_lines[0]

    # (e) the same under a real terminal (no strip on a TTY: the CSI is visible here).
    result = run_cli_with_pty("info", BAD, "-o", "table", pty_stream="stderr", cwd=fixture)
    assert result.returncode == 1
    for point in ("\x1b", "\x07", "\x7f", "\x9b"):
        assert point not in result.stderr, (point, result.stderr)


def _strip_dry(data: bytes) -> bytes:
    at = data.rfind(b" --dry-run")
    assert at >= 0
    return data[:at] + data[at + len(b" --dry-run") :]


def test_ac3_rotate_operand_echo_refusals_dry_real_pairs(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    (fixture / EVILDIR).mkdir()
    for name in (EVIL1, EVIL2):
        shutil.copy(fixture / BLANK_NAME, fixture / name)
    before = {name: sha((fixture / name).read_bytes()) for name in (EVIL1, EVIL2)}
    rows = {
        "R1": (["rotate", NOPE, "--pages", "1", "--angle", "90", "--out-dir", "out"], 4),
        "R2": (["rotate", EVILDIR, "--pages", "1", "--angle", "90", "--out-dir", "out"], 2),
        "R3": (["rotate", EVIL1, EVIL2, "--pages", "1", "--angle", "90", "--in-place"], 5),
    }
    runs_with_controls = 0
    unnamed: list[str] = []
    for label, (argv, rc_base) in rows.items():
        dry = _run([*argv, "--dry-run", "-o", "table"], fixture)
        real = _run([*argv, "-o", "table"], fixture)
        assert (dry.returncode, real.returncode) == (rc_base, rc_base), label
        if label in ("R1", "R2"):
            assert dry.stderr == real.stderr, label
        else:
            assert b" --dry-run" not in real.stderr
            assert len(dry.stderr) - len(real.stderr) == 10
            assert _strip_dry(dry.stderr) == real.stderr
        for proc in (dry, real):
            runs_with_controls += count_f_ml(proc.stderr) > 0
        if not re.search(rb"(nope|dir|evil)\\x1b\[31m\\x07", real.stderr):
            unnamed.append(label)
    assert runs_with_controls == 0, f"{runs_with_controls} of 6 runs carry controls"  # base: 6
    assert unnamed == [], f"escaped operand name missing as text: {unnamed}"

    # Decisive arm (R3): the product's own multi-line hint stays three lines.
    real = _run([*rows["R3"][0], "-o", "table"], fixture)
    lines = [line for line in real.stderr.split(b"\n") if line]
    assert len(lines) >= 3, real.stderr
    assert lines[1].startswith(b"hint: ")
    assert rb"evil\x1b[31m\x07-1.pdf" in lines[2]
    assert before == {name: sha((fixture / name).read_bytes()) for name in (EVIL1, EVIL2)}


def test_ac4_content_verb_warning_lines_are_escaped(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    shutil.copy(fixture / BLANK_NAME, fixture / EVIL)
    for verb in ("text", "tables"):
        proc = _run([verb, EVIL, "-o", "table"], fixture)
        assert proc.returncode == 0, (verb, proc.stderr)
        warnings = [line for line in proc.stderr.split(b"\n") if line.startswith(b"warning: ")]
        assert len(warnings) == 1, (verb, proc.stderr)
        assert count_f_ml(proc.stderr) == 0, (verb, proc.stderr)
        assert SHOWN_EVIL.encode("ascii") in warnings[0], (verb, warnings[0])


# --------------------------------------------------------------------------- Group B

TEXT_ARMS = {"fast": ["text"], "layout": ["text", "--layout"]}


@pytest.mark.parametrize("arm", sorted(TEXT_ARMS))
def test_ac6_text_table_body_escapes_content_and_keeps_lines(tmp_path: Path, arm: str) -> None:
    fixture = _fixture(tmp_path)
    argv = TEXT_ARMS[arm]
    proc = _run([*argv, CONTENT_NAME, "-o", "table"], fixture)
    assert proc.returncode == 0
    out = proc.stdout
    assert count_f_ml(out) == 0, out
    assert b"\nplain line\n" in out
    assert out.count(b"\n") == TEXT_BODY_LF_COUNT
    assert rb"\x1b[31mRED" in out
    assert b"\xc3\xa9" in out

    benign = _run([*argv, BENIGN_NAME, "-o", "table"], fixture)
    assert sha(benign.stdout) == BENIGN_TEXT_STDOUT_SHA256

    dry = _run([*argv, CONTENT_NAME, "-o", "table", "--dry-run"], fixture)
    assert dry.returncode == 0
    assert count_f_ml(dry.stdout) == 0, dry.stdout
    assert dry.stdout == out  # the same _emit renders both


def test_ac7_tables_table_grids_escape_cells_and_source(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    shutil.copy(fixture / CONTENT_NAME, fixture / EVIL)
    for name in (CONTENT_NAME, EVIL):
        proc = _run(["tables", name, "-o", "table"], fixture)
        assert proc.returncode == 0
        assert count_f(proc.stdout) == 0, proc.stdout
        lines = proc.stdout.split(b"\n")
        assert lines[0].startswith(
            b"# source="
            + name.replace("\x1b", "\\x1b").replace("\x07", "\\x07").encode("ascii")
            + b" "
        ), lines[0]
        row0, row1 = lines[1], lines[2]
        assert row0 == b"a      b"  # column 1 starts at len(r"c\x07") + 2 == 7
        assert row1[:7] == rb"c\x07" + b"  "
        assert row1[7:].startswith(rb"A\x1b[31mRED\x1b[0m B")
        assert rb"\x07" in row1[7:] and rb"\x7f" in row1[7:]
        assert b"\xc3\xa9" in row1


@pytest.mark.parametrize("arm", ["text", "text-layout", "tables"])
def test_ac8_content_verbs_under_a_pty_carry_no_escape(tmp_path: Path, arm: str) -> None:
    fixture = _fixture(tmp_path)
    argv = {
        "text": ["text"],
        "text-layout": ["text", "--layout"],
        "tables": ["tables"],
    }[arm]
    result = run_cli_with_pty(*argv, CONTENT_NAME, "-o", "table", pty_stream="stdout", cwd=fixture)
    assert result.returncode == 0
    for point in ("\x1b", "\x07", "\x7f", "\x9b"):
        assert point not in result.stdout, (point, result.stdout)


# --------------------------------------------------------------------------- Group C


def test_ac9_json_and_ndjson_are_byte_unchanged(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    runs = _frozen_runs(fixture)
    assert set(runs) == set(FROZEN_SHA256) == set(FROZEN_RC)
    for name, proc in runs.items():
        assert proc.returncode == FROZEN_RC[name], (name, proc.stderr)
        assert proc.stderr == b"", name
        assert sha(normalize(proc.stdout)) == FROZEN_SHA256[name], name

    fast = json.loads(runs["text_json"].stdout)["pages"][0]["text"]
    layout = "\n".join(
        block["text"] for block in json.loads(runs["text_layout_json"].stdout)["pages"][0]["blocks"]
    )
    for text in (fast, layout):
        for point in CODE_POINTS:
            assert point in text
        assert "\x1b[31mRED\x1b[0m" in text
    rows = json.loads(runs["tables_json"].stdout)["tables"][0]["rows"]
    holder = [row for row in rows if any("RED" in cell for cell in row)]
    assert len(holder) == 1
    joined = "".join(holder[0])
    for point in CODE_POINTS:
        assert point in joined
    assert any("\x1b[31mRED\x1b[0m" in cell for cell in holder[0])
    assert json.loads(runs["info_nope_json"].stdout)["error"]["path"] == NOPE


def test_ac10_written_outputs_are_byte_unchanged(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    for name, argv in (
        ("fast", ["text"]),
        ("layout", ["text", "--layout"]),
    ):
        proc = _run([*argv, CONTENT_NAME, "-O", f"{name}.txt", "-o", "table"], fixture)
        assert proc.returncode == 0, proc.stderr
        data = (fixture / f"{name}.txt").read_bytes()
        assert sha(data) == TXT_ARTIFACT_DIGEST, name
        assert b"\x1b" in data
    proc = _run(["tables", CONTENT_NAME, "--out-dir", "o", "-o", "table"], fixture)
    assert proc.returncode == 0, proc.stderr
    files = sorted(os.listdir(fixture / "o"))
    assert len(files) == 1
    csv = (fixture / "o" / files[0]).read_bytes()
    assert sha(csv) == TABLES_CSV_SHA256
    assert b"\x1b[31mRED" in csv


def test_ac12_text_and_tables_help_name_the_escape(tmp_path: Path) -> None:
    text_help = " ".join(_run(["text", "--help"], tmp_path).stdout.decode("utf-8").split())
    assert "yields clean text" in text_help
    assert "control characters other than tab and newline are shown escaped" in text_help
    assert "carry the extracted text exactly" in text_help
    tables_help = " ".join(_run(["tables", "--help"], tmp_path).stdout.decode("utf-8").split())
    assert "control characters in a cell or source name are shown escaped" in tables_help


def test_ac4b_meta_get_warning_loop_is_escaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Operator ruling (H4): ``cmd_meta_get``'s own ``warning:`` loop (PDF-155 D7).

    PDF-155's two warning templates (``XMP packet present but its fields are not
    reported: <fixed reason>``) carry no packet-derived bytes, so no real XMP packet can put a
    control character into that line. The loop is pinned instead by an in-process call that
    feeds a control-bearing warning through it, as the shared ``emit_result`` loop is.
    """
    from typer.testing import CliRunner

    import pdf_tooling
    from pdf_tooling.cli import cmd_meta_get
    from pdf_tooling.cli.main import app

    print("origin:", pdf_tooling.__file__)
    original = cmd_meta_get.build_payload
    raw = "w \x07 \x9b\r \x01 x\x1b]0;t\x07 end"

    def with_warning(*args: object, **kwargs: object) -> dict[str, object]:
        payload = original(*args, **kwargs)  # type: ignore[arg-type]
        return {**payload, "warnings": [*payload.get("warnings", []), raw]}

    monkeypatch.setattr(cmd_meta_get, "build_payload", with_warning)
    build_blank_pdf(tmp_path / BLANK_NAME)
    result = CliRunner().invoke(app, ["meta", "get", str(tmp_path / BLANK_NAME), "-o", "json"])
    assert result.exit_code == 0, result.output
    err = result.stderr_bytes
    assert count_f_ml(err) == 0, err
    assert err == b"warning: w \\x07 \\x9b\\r \\x01 x\\x1b]0;t\\x07 end\n"
    # display-only: the JSON envelope on stdout still carries the raw string
    assert json.loads(result.stdout_bytes)["warnings"][-1] == raw
