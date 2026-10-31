"""PDF-166 -- log records on stderr carry no terminal control bytes (CWE-150, B-538).

PDF-157 escaped the product's own ``error:`` / ``warning:`` lines. The logging handler was
left out on purpose, and ``output/logging.py`` wrote every record raw. The fix is one seam:
the handler's formatter shows every ``Cc`` code point except TAB and LF escaped, after
``RedactingFilter`` has already run (the stdlib's ``handle`` -> ``emit`` -> ``format``
order), and without touching the ``LogRecord`` itself.

Unit arms only (the seam, the order, record immutability, and the unknown-``/Encrypt``
record built from the real ``_algorithm`` output). The end-to-end matrix is in
``tests/integration/test_pdf166_log_record_escapes.py``.

Every capture is BYTES (``capsysbinary``): a bare CR would be hidden by a text capture.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from pdf_tooling.output import logging as pdf_logging
from pdf_tooling.output.table import escape_controls_multiline

H = "pw\x1b[31m\x07\u009b.txt"
SHOWN_H = "pw\\x1b[31m\\x07\\x9b.txt"
EVIL_PDF_NAME = "unk\x1b[31m\x07\u009b.pdf"
SHOWN_CFM = "/CFM /X\\x1b[31m\\x07"
SECRET_WITH_CONTROLS = "s3\x1bcr\x07t"
SHOWN_SECRET = "s3\\x1bcr\\x07t"

#: Unicode category Cc, restated from PDF-139's table test.
CONTROLS = [*range(0x00, 0x20), *range(0x7F, 0xA0)]
EXPECTED_ML = {
    code: {0x09: "\t", 0x0A: "\n", 0x0D: "\\r"}.get(code, f"\\x{code:02x}") for code in CONTROLS
}
#: PDF-139 AC1's identity set, restated verbatim: none of these is a Cc code point.
IDENT = [
    *range(0x20, 0x7F),
    *range(0xA0, 0x100),
    0x4E2D,
    0x6587,
    0x1F600,
    0x202E,
    0x2028,
]


def count_f_ml(data: bytes) -> int:
    """F_ml: every byte 0x00-0x1F except TAB and LF, DEL, and each UTF-8 C1 pair."""
    c0 = sum(1 for byte in data if (byte < 0x20 and byte not in (0x09, 0x0A)) or byte == 0x7F)
    return c0 + len(re.findall(rb"\xc2[\x80-\x9f]", data))


def _shows(line: bytes, shown: str) -> bool:
    """True when *line* carries *shown* as ASCII text (never an operand pin, B-073)."""
    return shown.encode("ascii") in line


@pytest.fixture
def restored_logging():
    """Snapshot and restore both loggers (``configure_logging`` owns root)."""
    root = logging.getLogger()
    ours = logging.getLogger(pdf_logging.LOGGER_NAME)
    saved = (
        list(root.handlers),
        root.level,
        list(ours.handlers),
        list(ours.filters),
        ours.level,
        ours.propagate,
    )
    try:
        yield
    finally:
        pdf_logging.clear_secrets()
        root.handlers[:] = saved[0]
        root.setLevel(saved[1])
        ours.handlers[:] = saved[2]
        ours.filters[:] = saved[3]
        ours.setLevel(saved[4])
        ours.propagate = saved[5]


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


# --------------------------------------------------------------------------- Group A


def test_ac1_every_cc_code_point_in_a_record_is_escaped_except_tab_and_lf(
    restored_logging, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    assert len(CONTROLS) == 65
    assert len(IDENT) == 196
    pdf_logging.configure_logging(verbose=0, quiet=False)
    logger = pdf_logging.get_logger("pdf166")

    bad = []
    for code in CONTROLS:
        logger.warning("m%s", "p" + chr(code))
        line = capsysbinary.readouterr().err
        if line != b"WARNING: mp" + EXPECTED_ML[code].encode("utf-8") + b"\n":
            bad.append(code)
    assert bad == []  # base: 63 (TAB and LF are already their own escape)

    moved = []
    for code in IDENT:
        logger.warning("m%s", "p" + chr(code))
        line = capsysbinary.readouterr().err
        if line != b"WARNING: mp" + chr(code).encode("utf-8") + b"\n":
            moved.append(code)
    assert moved == []  # the identity guard: green at base and after

    # Idempotence: escaping the already-escaped text changes nothing (backslash is untouched).
    hostile = "a\x1b[31m\x07\u009b\r\tb\nc"
    logger.warning("%s", hostile)
    once = capsysbinary.readouterr().err
    logger.warning("%s", escape_controls_multiline(hostile))
    twice = capsysbinary.readouterr().err
    assert once == twice

    # The new symbol is checked by assertion, never by an import that could fail at base.
    formatter_class = getattr(pdf_logging, "EscapingFormatter", None)
    assert isinstance(formatter_class, type)
    assert issubclass(formatter_class, logging.Formatter)
    assert "EscapingFormatter" in pdf_logging.__all__


SHAPES = ("s1-path-arg", "s2-str-arg", "s3-exception-arg", "s4-raised-then-caught")
FAMILIES = ("pdf_tooling", "root")


def _emit_shape(logger: logging.Logger, shape: str) -> None:
    if shape == "s1-path-arg":
        logger.warning(
            "%s: readable by group or other (mode %o); run 'chmod 600 %s'",
            Path(H),
            0o644,
            Path(H),
        )
    elif shape == "s2-str-arg":
        logger.warning("password resolved from %s (slot: %s)", "file:" + H, "password")
    elif shape == "s3-exception-arg":
        logger.warning(
            "%s: linearization unreadable (%s)", Path(H), OSError(H + ": unable to find trailer")
        )
    else:
        try:
            raise ValueError("v\x1b]0;t\x07")
        except ValueError as exc:
            logger.warning("boom", exc_info=exc)


def test_ac2_paths_exceptions_and_tracebacks_are_escaped_on_both_handlers(
    restored_logging, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    pdf_logging.configure_logging(verbose=0, quiet=False)
    loggers = {
        "pdf_tooling": pdf_logging.get_logger("cli.password"),
        "root": logging.getLogger("pypdf._reader"),
    }
    captures: dict[tuple[str, str], bytes] = {}
    for family in FAMILIES:
        for shape in SHAPES:
            _emit_shape(loggers[family], shape)
            captures[(family, shape)] = capsysbinary.readouterr().err
    assert len(captures) == 8
    assert sum(count_f_ml(data) > 0 for data in captures.values()) == 0  # base: 8
    for (family, shape), captured in captures.items():
        assert captured.startswith(b"WARNING: "), (family, shape)
        if shape != "s4-raised-then-caught":
            assert _shows(captured, SHOWN_H), (family, shape)
        else:
            assert captured.count(b"\n") >= 3, (family, shape, captured)
            assert _shows(captured, "ValueError: v\\x1b]0;t\\x07"), (family, shape)


def test_ac3_redaction_runs_before_the_escape_and_records_are_not_mutated(
    restored_logging, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    from pdf_tooling.secret import Secret

    pdf_logging.register_secret(SECRET_WITH_CONTROLS)
    pdf_logging.configure_logging(verbose=0, quiet=False)
    logger = pdf_logging.get_logger("x")

    # (a) a registered secret that itself holds control bytes is redacted BEFORE the escape.
    logger.warning("pw=%s", SECRET_WITH_CONTROLS)
    logger.warning("pw=" + SECRET_WITH_CONTROLS)
    both = capsysbinary.readouterr().err
    assert both == b"WARNING: pw=<redacted>\nWARNING: pw=<redacted>\n"
    assert not _shows(both, SHOWN_SECRET)
    assert SECRET_WITH_CONTROLS.encode("utf-8") not in both
    assert count_f_ml(both) == 0

    # (b) a Secret passed as an argument renders as the placeholder.
    logger.warning("pw=%s", Secret(SECRET_WITH_CONTROLS, source="file:x"))
    assert capsysbinary.readouterr().err == b"WARNING: pw=<redacted>\n"

    # (c) display only: the record every other handler sees keeps its raw text and its Path.
    observed = _ListHandler()
    logging.getLogger().addHandler(observed)
    pdf_logging.get_logger().addHandler(observed)
    try:
        _emit_shape(pdf_logging.get_logger("cli.password"), "s1-path-arg")
    finally:
        pdf_logging.get_logger().removeHandler(observed)
        logging.getLogger().removeHandler(observed)
    shown = capsysbinary.readouterr().err
    assert len(observed.records) == 1
    record = observed.records[0]
    assert isinstance(record.args, tuple)
    assert isinstance(record.args[0], Path)
    assert record.args[0] == Path(H)
    assert "\x1b[31m\x07\u009b" in record.getMessage()
    assert count_f_ml(shown) == 0  # base: red, the stream is raw
    assert _shows(shown, SHOWN_H)


# --------------------------------------------------------------------------- Group B


def test_ac7a_unknown_encrypt_warning_is_escaped(
    restored_logging, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    from pypdf.generic import DictionaryObject, NameObject, NumberObject

    from pdf_tooling.adapters.pypdf_structure import _algorithm

    cfm = "/X\x1b[31m\x07"
    standard = DictionaryObject({NameObject("/CFM"): NameObject(cfm)})
    crypt_filters = DictionaryObject({NameObject("/StdCF"): standard})
    encryption = DictionaryObject(
        {
            NameObject("/V"): NumberObject(4),
            NameObject("/Length"): NumberObject(128),
            NameObject("/StmF"): NameObject("/StdCF"),
            NameObject("/CF"): crypt_filters,
        }
    )
    algorithm, warning = _algorithm(encryption)
    # Reachability guard, green at base and after: document-derived controls reach the string.
    assert algorithm is None
    assert warning is not None
    assert "\x1b[31m\x07" in warning

    pdf_logging.configure_logging(verbose=0, quiet=False)
    # Exactly the call the adapter makes for an unrecognised /Encrypt dictionary.
    pdf_logging.get_logger("adapters.pypdf").warning("%s: %s", Path(EVIL_PDF_NAME), warning)
    captured = capsysbinary.readouterr().err
    assert captured.startswith(b"WARNING: ")
    assert count_f_ml(captured) == 0  # base: >= 1
    assert _shows(captured, SHOWN_CFM)
    assert _shows(captured, "unk\\x1b[31m\\x07\\x9b.pdf")
