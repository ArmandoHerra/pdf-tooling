"""PDF-99 -- `meta set` returns the envelope, not a traceback, on a PDF with no `/Info`.

THE DEFECT. `pdftooling meta set noinfo.pdf --title X -O out.pdf -o json` exited
1 with 0 bytes on stdout and a raw ``AttributeError: 'NoneType' object has no
attribute 'get_object'`` traceback, while ``--dry-run`` predicted 0. The cause
is ``PdfWriter(clone_from=reader)._info`` being ``None`` whenever the source
carries no usable ``/Info``. Three document shapes reach that arm and all three
are driven here, because a class closed on one trigger is not closed (X-732):

* ``no_info`` -- the corpus fixture: no ``/Info`` entry in the trailer.
* ``dangling_info`` -- ``/Info`` is an indirect reference to an object that does
  not exist (``PdfReader.metadata`` is ``None``).
* ``xmp_no_info`` -- an XMP packet but no ``/Info``; the fix has to keep syncing
  the packet while ``/Info`` is absent.

The shapes are a DECLARED axis (the PDF-74 stance: they are not enumerable from
the command tree). They are crossed with the metadata-touching verbs only, and
``test_every_metadata_access_site_is_declared`` keeps that population honest: a
new ``reader.``/``writer.`` metadata access anywhere in ``src/`` reds the arm
until its author states the site's ``None`` arm and adds a cell here.

Every cell is a subprocess (``registry.run_cli``), ``-o json``, non-TTY. Write
cells run on a per-cell copy under ``tmp_path``, never on the session corpus.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import shutil
import sys
import tokenize
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import pikepdf
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import TextStringObject

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from dryreal import dry_and_real, prediction  # noqa: E402
from registry import run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

SRC_ROOT: Final[Path] = Path(__file__).resolve().parents[2] / "src" / "pdf_tooling"

SHAPES: Final[tuple[str, ...]] = ("no_info", "dangling_info", "xmp_no_info")
PRODUCER: Final[str] = "PDF99-Producer"
OK_INFO_ONLY: Final[str] = "ok (no XMP packet; /Info only)"

#: The four write invocations. `{out}` is filled per cell.
WRITE_CELLS: Final[Mapping[str, tuple[str, ...]]] = {
    "title": ("--title", "X", "-O", "{out}"),
    "clear_producer": ("--clear-producer", "-O", "{out}"),
    "clear_all": ("--clear-all", "-O", "{out}"),
    "in_place": ("--title", "X", "--in-place"),
}


# --------------------------------------------------------------------------- #
# The three document shapes, each with its own precondition assertions.
# --------------------------------------------------------------------------- #


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_shape(shape: str, corpus: Any, tmp_path: Path) -> Path:
    """Return a fresh copy of *shape* under *tmp_path*, preconditions asserted."""
    target = tmp_path / f"{shape}.pdf"
    if shape == "no_info":
        shutil.copy(corpus.path("no_info"), target)
        reader = PdfReader(str(target))
        assert "/Info" not in reader.trailer
        assert reader.metadata is None
    elif shape == "dangling_info":
        # Byte-patch a pikepdf-saved file: the trailer dictionary follows the
        # xref table, so inserting a key into it moves no xref offset.
        raw = corpus.path("no_info").read_bytes()
        marker = b"trailer <<"
        assert raw.count(marker) == 1, "unexpected trailer layout; rebuild the patch"
        target.write_bytes(raw.replace(marker, marker + b" /Info 99 0 R", 1))
        reader = PdfReader(str(target))
        assert reader.metadata is None, "a dangling /Info must resolve to nothing"
    elif shape == "xmp_no_info":
        # `xmp_bearing`'s packet carries `pdf_producer = None`, so without this
        # step the `--clear-producer` cell would pass vacuously.
        writer = PdfWriter(clone_from=PdfReader(str(corpus.path("xmp_bearing"))))
        xmp = writer.xmp_metadata
        assert xmp is not None
        xmp.pdf_producer = PRODUCER
        writer.xmp_metadata = xmp
        buffer = io.BytesIO()
        writer.write(buffer)
        buffer.seek(0)
        with pikepdf.open(buffer) as pdf:
            if "/Info" in pdf.trailer:
                del pdf.trailer["/Info"]
            pdf.save(str(target))
        reader = PdfReader(str(target))
        assert "/Info" not in reader.trailer
        assert reader.metadata is None
        packet = reader.xmp_metadata
        assert packet is not None, "the packet must be present"
        assert packet.pdf_producer == PRODUCER
    else:  # pragma: no cover - the axis is declared above
        raise AssertionError(shape)
    return target


def _envelope(result: Any) -> dict[str, Any]:
    assert "Traceback" not in result.stderr, result.stderr[-800:]
    try:
        return dict(json.loads(result.stdout))
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"stdout was not JSON ({error}); stdout={result.stdout[:300]!r} "
            f"stderr={result.stderr[-500:]!r}"
        ) from None


def _args(cell: str, out: Path) -> list[str]:
    return [part.replace("{out}", str(out)) for part in WRITE_CELLS[cell]]


# --------------------------------------------------------------------------- #
# AC3-AC7 -- every write cell, on every shape.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("cell", tuple(WRITE_CELLS))
@pytest.mark.parametrize("shape", SHAPES)
def test_meta_set_on_a_pdf_without_info_returns_the_envelope(
    corpus: Any, tmp_path: Path, shape: str, cell: str
) -> None:
    source = _build_shape(shape, corpus, tmp_path)
    before = _sha256(source)
    out = tmp_path / "out.pdf"

    result = run_cli("meta set", str(source), *_args(cell, out), "-o", "json")

    payload = _envelope(result)
    assert result.returncode == 0, f"rc {result.returncode}; stderr={result.stderr[-500:]!r}"
    assert payload["exit_code"] == 0
    item = payload["items"][0]
    assert item["ok"] is True, item

    written = source if cell == "in_place" else out
    reader = PdfReader(str(written))
    root_has_xmp = "/Metadata" in reader.trailer["/Root"]

    if cell == "in_place":
        backup = Path(str(source) + ".bak")
        assert backup.is_file(), "--in-place must write its .bak sidecar"
        assert _sha256(backup) == before, ".bak must hold the pre-run bytes"
    else:
        assert _sha256(source) == before, "the source must be untouched"

    if shape in ("no_info", "dangling_info"):
        assert not root_has_xmp, "no XMP packet may be created"
        if cell in ("title", "in_place"):
            assert item["message"] == OK_INFO_ONLY
            title = reader.metadata["/Title"]
            assert title == "X"
            assert isinstance(title, TextStringObject)
        elif cell == "clear_all":
            assert item["message"] == "ok"
            assert "/Info" not in reader.trailer, "a clear-only run must leave /Info absent"
        else:  # clear_producer
            assert item["message"] == OK_INFO_ONLY
            assert "/Info" not in reader.trailer, "a clear-only run must create nothing"
    else:  # xmp_no_info
        packet = reader.xmp_metadata
        if cell in ("title", "in_place"):
            assert item["message"] == "ok"
            assert reader.metadata["/Title"] == "X"
            assert packet is not None
            assert packet.dc_title == {"x-default": "X"}
        elif cell == "clear_producer":
            assert "/Info" not in reader.trailer
            assert packet is not None, "the packet must survive a clear of one field"
            assert packet.pdf_producer is None, "the XMP half must still run"
        else:  # clear_all
            assert "/Info" not in reader.trailer
            assert not root_has_xmp, "--clear-all must still remove the packet"


# --------------------------------------------------------------------------- #
# AC8 -- dry == real, on the absolute value 0.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("cell", tuple(WRITE_CELLS))
@pytest.mark.parametrize("shape", SHAPES)
def test_meta_set_dry_run_and_real_run_agree_on_zero(
    corpus: Any, tmp_path: Path, shape: str, cell: str
) -> None:
    source = _build_shape(shape, corpus, tmp_path)
    out = tmp_path / "out.pdf"

    dry, real = dry_and_real("meta set", [str(source), *_args(cell, out)])

    assert dry.returncode == 0
    assert _envelope(dry)["exit_code"] == 0
    assert prediction(dry)["would_exit"] == 0
    assert real.returncode == 0, f"real rc {real.returncode}; stderr={real.stderr[-500:]!r}"
    assert _envelope(real)["items"][0]["ok"] is True


# --------------------------------------------------------------------------- #
# AC9 -- the read side, pinned on inputs that truly lack /Info.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("shape", SHAPES)
def test_info_on_a_pdf_without_info_reports_empty_metadata(
    corpus: Any, tmp_path: Path, shape: str
) -> None:
    source = _build_shape(shape, corpus, tmp_path)
    result = run_cli("info", str(source), "-o", "json")
    payload = _envelope(result)
    assert result.returncode == 0
    assert payload["documents"][0]["metadata"] == {}


@pytest.mark.parametrize("shape", SHAPES)
def test_meta_get_on_a_pdf_without_info_reports_empty_info(
    corpus: Any, tmp_path: Path, shape: str
) -> None:
    source = _build_shape(shape, corpus, tmp_path)
    result = run_cli("meta get", str(source), "-o", "json")
    payload = _envelope(result)
    assert result.returncode == 0
    assert payload["info"] == {}
    if shape == "xmp_no_info":
        assert payload["xmp"] is not None
    else:
        assert payload["xmp"] is None


# --------------------------------------------------------------------------- #
# AC10 -- the census arm: a new metadata access site anywhere in src/ reds.
# --------------------------------------------------------------------------- #

#: Receivers and attributes the census looks for (D7). `docinfo`/`open_metadata`
#: have zero accesses in `src/`; `importlib.metadata` and `self.metadata` are not
#: document access and are excluded by the receiver filter.
_RECEIVERS: Final[frozenset[str]] = frozenset({"reader", "writer"})
_ATTRS: Final[frozenset[str]] = frozenset({"metadata", "_info", "xmp_metadata", "add_metadata"})

#: `(module, enclosing function, receiver.attr)` -> `(occurrences, disposition)`.
#: A new entry means: state the site's `None` arm and add a document-shape cell.
METADATA_ACCESS_CENSUS: Final[Mapping[tuple[str, str, str], tuple[int, str]]] = {
    ("adapters/pypdf_structure.py", "_metadata", "reader.metadata"): (
        1,
        "`info`: guarded by `if raw is None: return {}`",
    ),
    ("adapters/pypdf_structure.py", "_info_report_dict", "reader.metadata"): (
        1,
        "`meta get`: guarded by `if raw is None`",
    ),
    ("adapters/pypdf_structure.py", "_xmp_report_fields", "reader.xmp_metadata"): (
        1,
        "`meta get`: try/except plus `if xmp is None`",
    ),
    ("adapters/pypdf_structure.py", "write_metadata", "writer.xmp_metadata"): (
        3,
        "`meta set`: `had_xmp` / `if xmp is not None`; two setters",
    ),
    ("adapters/pypdf_structure.py", "write_metadata", "writer.metadata"): (
        1,
        "`meta set`: the public getter IS the absence test (None on no-/Info and dangling)",
    ),
    ("adapters/pypdf_structure.py", "write_metadata", "writer.add_metadata"): (
        1,
        "`meta set`: creates /Info via the public path, only when a set needs it",
    ),
    ("adapters/pypdf_structure.py", "write_metadata", "writer._info"): (
        2,
        "`meta set`: the live-dict edit, reached only when /Info exists or was just created",
    ),
    ("adapters/pypdf_structure.py", "_xmp", "reader.xmp_metadata"): (
        1,
        "`info`: try/except plus a `None` check",
    ),
}


def _enclosing_functions(tree: ast.AST) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            spans.append((node.lineno, node.end_lineno or node.lineno, node.name))
    return spans


def _innermost(spans: list[tuple[int, int, str]], line: int) -> str:
    inside = [s for s in spans if s[0] <= line <= s[1]]
    if not inside:
        return "<module>"
    return min(inside, key=lambda s: s[1] - s[0])[2]


def _measure_metadata_accesses() -> Counter[tuple[str, str, str]]:
    found: Counter[tuple[str, str, str]] = Counter()
    for path in sorted(SRC_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        spans = _enclosing_functions(ast.parse(source))
        with path.open("rb") as handle:
            tokens = [
                t
                for t in tokenize.tokenize(handle.readline)
                if t.type in (tokenize.NAME, tokenize.OP)
            ]
        module = path.relative_to(SRC_ROOT).as_posix()
        for first, dot, last in zip(tokens, tokens[1:], tokens[2:], strict=False):
            if (
                first.type == tokenize.NAME
                and dot.string == "."
                and last.type == tokenize.NAME
                and first.string in _RECEIVERS
                and last.string in _ATTRS
            ):
                function = _innermost(spans, first.start[0])
                found[(module, function, f"{first.string}.{last.string}")] += 1
    return found


def test_every_metadata_access_site_is_declared() -> None:
    declared = Counter({key: count for key, (count, _) in METADATA_ACCESS_CENSUS.items()})
    measured = _measure_metadata_accesses()
    undeclared = measured - declared
    stale = declared - measured
    assert not undeclared and not stale, (
        "the document-metadata access census moved. For each NEW site state its `None` arm "
        "(PdfWriter(clone_from=...)._info and PdfReader.metadata are both None on a PDF "
        "with no /Info) and add a document-shape cell to this module, then declare it in "
        f"METADATA_ACCESS_CENSUS. undeclared={dict(undeclared)} stale={dict(stale)}"
    )


def test_every_declared_census_entry_states_its_disposition() -> None:
    assert all(disposition.strip() for _, disposition in METADATA_ACCESS_CENSUS.values())
