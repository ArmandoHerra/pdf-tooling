"""The deterministic reportlab-generated fixture corpus — `PLAN.md` §9.1 `C-06`.

Eight :class:`FixtureSpec` rows, one per fixture the contract harness and every
later verb spec exercises. Each spec carries **both** the build instructions
and the expected values, so a fixture can never silently drift from what a
test asserts against it — the `MHC-12` lesson, applied from PDF-06 onward.

Determinism
-----------
Every fixture except ``encrypted_aes256`` is byte-identical across two
independent builds (AC2): ``reportlab.pdfgen.canvas.Canvas`` is built with
``invariant=1`` (a fixed ``/CreationDate``, ``/ModDate`` and document ID), and
``/Producer``/``/Creator`` are set explicitly rather than left to reportlab's
own version-stamped defaults. The JPEG embedded by ``jpeg_page`` is built by
Pillow from a fixed pixel array at a fixed quality — Pillow writes no
timestamp of its own.

``encrypted_aes256`` is the one honest exemption. AES-256 encryption uses a
random validation salt per the PDF specification (ISO 32000-2 §7.6.4.3.4), so
two builds differ by construction even with ``invariant=1``, and pypdf's own
document-identifier is computed from the encrypted byte stream, not from
plaintext content. Its determinism assertion is therefore **semantic** —
decrypting two independent builds yields the same page count and the same
per-page text — never byte-level. See ``tests/test_corpus.py``.

Nothing here is committed. ``build_corpus()`` is called once per pytest
session by the ``corpus`` fixture in ``tests/conftest.py``, into
``tmp_path_factory``'s own scratch directory.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import pikepdf
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject, TextStringObject
from pypdf.xmp import XmpInformation
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

__all__ = [
    "ENCRYPTED_PASSWORD",
    "FIXTURE_NAMES",
    "TABLE_GRID",
    "Corpus",
    "FixtureSpec",
    "build_corpus",
]

_LETTER: Final[tuple[float, float]] = letter  # (612.0, 792.0) in points

#: The fixed password `encrypted_aes256` is built with. Not a secret — it is a
#: test fixture, and the value is deliberately unremarkable.
ENCRYPTED_PASSWORD: Final[str] = "pdftoolkit-corpus-fixture"

#: The cell grid `tabular` draws, and what `tests/test_corpus.py` asserts against.
TABLE_GRID: Final[tuple[tuple[str, ...], ...]] = (
    ("R1C1", "R1C2", "R1C3"),
    ("R2C1", "R2C2", "R2C3"),
    ("R3C1", "R3C2", "R3C3"),
)


@dataclass(frozen=True)
class FixtureSpec:
    """One fixture's build instructions and its own expected values, together.

    Attributes:
        name: The fixture's registry key and filename stem.
        page_count: Expected page count.
        page_size: Expected MediaBox width/height in points.
        page_texts: Exactly what reportlab wrote, one entry per page, in order.
        rotations: Expected ``/Rotate`` VALUE per page, for pages that carry
            the key. ``()`` means no page carries a NON-ZERO rotation -- which
            is NOT the same as "no page carries a ``/Rotate`` key", and B-084
            is what that ambiguity cost: ``rotate_absent`` below is the only
            fixture whose whole purpose is the second state, and until PDF-17
            nothing in the corpus could tell the two apart.
        rotate_key_absent_on: Zero-based page indices carrying NO ``/Rotate``
            KEY at all. Every OTHER page is asserted to carry one explicitly
            (`tests/test_corpus.py`), so this field is exhaustive in both
            directions rather than a hint.
        embedded_jpeg: Whether this fixture embeds a raster image.
        metadata: The document-information-dictionary fields this fixture sets.
        encrypted: ``"AES-256"`` when the fixture is password-protected, else
            ``None``.
        table: The expected cell grid, row-major. Empty for non-tabular fixtures.
    """

    name: str
    page_count: int
    page_size: tuple[float, float]
    page_texts: tuple[str, ...]
    rotations: tuple[int, ...] = ()
    rotate_key_absent_on: tuple[int, ...] = ()
    embedded_jpeg: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)
    encrypted: str | None = None
    table: tuple[tuple[str, ...], ...] = ()


def _new_canvas(path: Path, page_size: tuple[float, float]) -> canvas.Canvas:
    """A Canvas built for determinism: fixed timestamp/ID, explicit producer."""
    made = canvas.Canvas(str(path), pagesize=page_size, invariant=1)
    made.setProducer("pdf-toolkit test corpus")
    made.setCreator("tests/corpus.py")
    return made


def _build_multipage_text(root: Path) -> tuple[Path, FixtureSpec]:
    texts = tuple(f"multipage_text fixture -- page {n} of 3." for n in range(1, 4))
    path = root / "multipage_text.pdf"
    made = _new_canvas(path, _LETTER)
    for text in texts:
        made.drawString(72, 700, text)
        made.showPage()
    made.save()
    spec = FixtureSpec(name="multipage_text", page_count=3, page_size=_LETTER, page_texts=texts)
    return path, spec


def _build_ten_page_text(root: Path) -> tuple[Path, FixtureSpec]:
    """PDF-08 — ten pages, each carrying its own page number in its text.

    A *parameter*, not a new kind of artefact: the corpus is declarative and
    generated at test time, so "a longer document" is one more row here rather
    than a committed binary (`testdata/` holds only what cannot be generated).

    Ten pages is the shortest length at which PDF-08's assertions are
    meaningful. `multipage_text` (3 pages) cannot express them: `--pages even`
    on it yields 2 pages either way under the correct and the off-by-one
    parity implementation, and `reorder --pages 'last,1'` leaves a remainder
    of one page, which does not distinguish "appended in ascending original
    order" from several wrong orders. It is a NEW fixture rather than a
    lengthened `multipage_text` because `tests/golden/text_layout.json` pins
    that fixture's three pages and their exact "page N of 3" strings.
    """
    texts = tuple(f"ten_page_text fixture -- page {n} of 10." for n in range(1, 11))
    path = root / "ten_page_text.pdf"
    made = _new_canvas(path, _LETTER)
    for text in texts:
        made.drawString(72, 700, text)
        made.showPage()
    made.save()
    spec = FixtureSpec(name="ten_page_text", page_count=10, page_size=_LETTER, page_texts=texts)
    return path, spec


def _build_rotated(root: Path) -> tuple[Path, FixtureSpec]:
    rotations = (0, 90, 180, 270)
    texts = tuple(
        f"rotated fixture -- page {n} of {len(rotations)}." for n in range(1, len(rotations) + 1)
    )
    path = root / "rotated.pdf"
    made = _new_canvas(path, _LETTER)
    for text, angle in zip(texts, rotations, strict=True):
        made.setPageRotation(angle)
        made.drawString(72, 700, text)
        made.showPage()
    made.save()
    spec = FixtureSpec(
        name="rotated",
        page_count=len(rotations),
        page_size=_LETTER,
        page_texts=texts,
        rotations=rotations,
    )
    return path, spec


def _fixed_jpeg_bytes() -> bytes:
    """A tiny, fully deterministic JPEG: a fixed pixel array, fixed quality.

    Pillow writes no timestamp of its own, so this is byte-identical across
    two independent builds on the same Pillow version.
    """
    size = 32
    pixels = bytes((x * 7 + y * 13) % 256 for y in range(size) for x in range(size))
    image = Image.frombytes("L", (size, size), pixels).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85, subsampling=0)
    return buffer.getvalue()


def _build_jpeg_page(root: Path) -> tuple[Path, FixtureSpec]:
    text = "jpeg_page fixture -- one embedded raster image."
    path = root / "jpeg_page.pdf"
    jpeg_bytes = _fixed_jpeg_bytes()
    made = _new_canvas(path, _LETTER)
    made.drawString(72, 720, text)
    made.drawImage(ImageReader(io.BytesIO(jpeg_bytes)), 72, 400, width=200, height=200)
    made.showPage()
    made.save()
    spec = FixtureSpec(
        name="jpeg_page",
        page_count=1,
        page_size=_LETTER,
        page_texts=(text,),
        embedded_jpeg=True,
    )
    return path, spec


_METADATA: Final[dict[str, str]] = {
    "title": "pdf-toolkit corpus: metadata_rich",
    "author": "pdf-toolkit test corpus",
    "subject": "PDF-06 fixture corpus",
    "keywords": "pdf-toolkit,fixture,metadata",
}


def _build_metadata_rich(root: Path) -> tuple[Path, FixtureSpec]:
    text = "metadata_rich fixture."
    path = root / "metadata_rich.pdf"
    made = _new_canvas(path, _LETTER)
    made.setTitle(_METADATA["title"])
    made.setAuthor(_METADATA["author"])
    made.setSubject(_METADATA["subject"])
    made.setKeywords(_METADATA["keywords"])
    made.drawString(72, 700, text)
    made.showPage()
    made.save()
    spec = FixtureSpec(
        name="metadata_rich",
        page_count=1,
        page_size=_LETTER,
        page_texts=(text,),
        metadata=dict(_METADATA),
    )
    return path, spec


def _build_single_page(root: Path) -> tuple[Path, FixtureSpec]:
    text = "single_page fixture -- exactly one page."
    path = root / "single_page.pdf"
    made = _new_canvas(path, _LETTER)
    made.drawString(72, 700, text)
    made.showPage()
    made.save()
    spec = FixtureSpec(name="single_page", page_count=1, page_size=_LETTER, page_texts=(text,))
    return path, spec


def _build_tabular(root: Path) -> tuple[Path, FixtureSpec]:
    path = root / "tabular.pdf"
    made = _new_canvas(path, _LETTER)
    top, left, row_h, col_w = 700, 72, 24, 100
    for row_index, row in enumerate(TABLE_GRID):
        for col_index, cell in enumerate(row):
            made.drawString(left + col_index * col_w, top - row_index * row_h, cell)
    # Grid lines, so a later `--strategy lines` extractor has geometry to key
    # off — this fixture's job is to exist for that spec, not to prove it here.
    grid_bottom = top + 12 - len(TABLE_GRID) * row_h
    grid_right = left + len(TABLE_GRID[0]) * col_w
    for row_index in range(len(TABLE_GRID) + 1):
        y = top + 12 - row_index * row_h
        made.line(left - 4, y, grid_right, y)
    for col_index in range(len(TABLE_GRID[0]) + 1):
        x = left - 4 + col_index * col_w
        made.line(x, top + 12, x, grid_bottom)
    made.showPage()
    made.save()
    # Newline-joined to match pypdf's own extract_text() ordering for stacked
    # drawString() calls -- the individual-cell check below is what matters.
    flat_text = "\n".join(cell for row in TABLE_GRID for cell in row)
    spec = FixtureSpec(
        name="tabular", page_count=1, page_size=_LETTER, page_texts=(flat_text,), table=TABLE_GRID
    )
    return path, spec


def _build_encrypted_aes256(root: Path) -> tuple[Path, FixtureSpec]:
    """Reportlab writes the base document; pypdf encrypts it AES-256.

    The one honest exemption from byte-identity — see the module docstring.
    """
    texts = tuple(f"encrypted_aes256 fixture -- page {n} of 2." for n in range(1, 3))
    plain_path = root / "_encrypted_aes256_plain.pdf"
    made = _new_canvas(plain_path, _LETTER)
    for text in texts:
        made.drawString(72, 700, text)
        made.showPage()
    made.save()

    reader = PdfReader(str(plain_path))
    writer = PdfWriter()
    writer.append(reader)
    writer.encrypt(user_password=ENCRYPTED_PASSWORD, algorithm="AES-256")
    path = root / "encrypted_aes256.pdf"
    with open(path, "wb") as handle:  # noqa: PTH123 - test-only scratch, tests/ is exempt from the write-chokepoint walk
        writer.write(handle)
    plain_path.unlink()

    spec = FixtureSpec(
        name="encrypted_aes256",
        page_count=2,
        page_size=_LETTER,
        page_texts=texts,
        encrypted="AES-256",
    )
    return path, spec


#: PDF-14 -- `meta get`/`meta set`/`watermark`/`stamp`'s own fixture
#: extensions (Scope > Fixtures). Every builder is deterministic across two
#: independent builds, verified the same way PDF-06's own fixtures are
#: (`tests/test_corpus.py::test_every_fixture_matches_its_own_spec` +
#: PDF-14's own `tests/test_corpus.py`-style byte-identity check in
#: `tests/unit/test_metadata.py`): `PdfWriter(clone_from=reader)` over an
#: `invariant=1` reportlab source, never a fresh, unseeded `PdfWriter()` with
#: engine-chosen defaults.


def _build_metadata_typed(root: Path) -> tuple[Path, FixtureSpec]:
    """AC3's own fixture: a `/Trapped` NAME value (never a string) and a
    custom `/Info` key, alongside the ordinary title/author/subject/keywords
    -- the full-dict, type-preserving `meta set` roundtrip has nothing to
    prove against `metadata_rich` alone, which carries neither."""
    text = "metadata_typed fixture."
    path = root / "metadata_typed.pdf"
    plain = root / "_metadata_typed_plain.pdf"
    made = _new_canvas(plain, _LETTER)
    made.setTitle(_METADATA["title"])
    made.setAuthor(_METADATA["author"])
    made.setSubject(_METADATA["subject"])
    made.setKeywords(_METADATA["keywords"])
    made.drawString(72, 700, text)
    made.showPage()
    made.save()

    reader = PdfReader(str(plain))
    writer = PdfWriter(clone_from=reader)
    info = writer._info.get_object()  # noqa: SLF001 - fixture construction, not product code
    info[NameObject("/Trapped")] = NameObject("/False")
    info[NameObject("/CustomField")] = TextStringObject("custom-value")
    with open(path, "wb") as handle:  # noqa: PTH123 - test-only scratch
        writer.write(handle)
    plain.unlink()

    spec = FixtureSpec(
        name="metadata_typed",
        page_count=1,
        page_size=_LETTER,
        page_texts=(text,),
        metadata=dict(_METADATA),
    )
    return path, spec


def _build_xmp_bearing(root: Path) -> tuple[Path, FixtureSpec]:
    """AC4's own fixture: an XMP packet whose `dc:title` AGREES with
    `/Title`, so `meta set --title X` updating both halves has something to
    prove that a no-XMP fixture cannot."""
    text = "xmp_bearing fixture."
    path = root / "xmp_bearing.pdf"
    plain = root / "_xmp_bearing_plain.pdf"
    made = _new_canvas(plain, _LETTER)
    made.setTitle("XMP Bearing Title")
    made.drawString(72, 700, text)
    made.showPage()
    made.save()

    reader = PdfReader(str(plain))
    writer = PdfWriter(clone_from=reader)
    xmp = XmpInformation.create()
    xmp.dc_title = {"x-default": "XMP Bearing Title"}
    writer.xmp_metadata = xmp
    with open(path, "wb") as handle:  # noqa: PTH123 - test-only scratch
        writer.write(handle)
    plain.unlink()

    spec = FixtureSpec(name="xmp_bearing", page_count=1, page_size=_LETTER, page_texts=(text,))
    return path, spec


def _build_xmp_disagreement(root: Path) -> tuple[Path, FixtureSpec]:
    """AC5's own fixture: `/Title` says ``"A"``, `dc:title` says ``"B"`` --
    the one case `meta get`'s `disagreements` array exists to report."""
    text = "xmp_disagreement fixture."
    path = root / "xmp_disagreement.pdf"
    plain = root / "_xmp_disagreement_plain.pdf"
    made = _new_canvas(plain, _LETTER)
    made.setTitle("A")
    made.drawString(72, 700, text)
    made.showPage()
    made.save()

    reader = PdfReader(str(plain))
    writer = PdfWriter(clone_from=reader)
    xmp = XmpInformation.create()
    xmp.dc_title = {"x-default": "B"}
    writer.xmp_metadata = xmp
    with open(path, "wb") as handle:  # noqa: PTH123 - test-only scratch
        writer.write(handle)
    plain.unlink()

    spec = FixtureSpec(name="xmp_disagreement", page_count=1, page_size=_LETTER, page_texts=(text,))
    return path, spec


def _build_residual_surfaces(root: Path) -> tuple[Path, FixtureSpec]:
    """AC7's own fixture: document-level `/Info` + XMP (both clearable by
    `--clear-all`) alongside page-level XMP `/Metadata` and a document-level
    `/PieceInfo` -- neither of which `--clear-all` touches (D2.4), so
    `meta get`'s `residual_surfaces` has something real to report after a
    clear."""
    text = "residual_surfaces fixture."
    path = root / "residual_surfaces.pdf"
    plain = root / "_residual_surfaces_plain.pdf"
    made = _new_canvas(plain, _LETTER)
    made.setTitle("Residual Surfaces Title")
    made.drawString(72, 700, text)
    made.showPage()
    made.save()

    reader = PdfReader(str(plain))
    writer = PdfWriter(clone_from=reader)
    xmp = XmpInformation.create()
    xmp.dc_title = {"x-default": "Residual Surfaces Title"}
    writer.xmp_metadata = xmp

    # Page-level XMP `/Metadata` -- detection is `"/Metadata" in page`
    # (D2.4); the stream need not be a well-formed packet for that check.
    page_xmp_stream = StreamObject()
    page_xmp_stream.set_data(b"<x:xmpmeta xmlns:x='adobe:ns:meta/'></x:xmpmeta>")
    page_xmp_stream[NameObject("/Type")] = NameObject("/Metadata")
    page_xmp_stream[NameObject("/Subtype")] = NameObject("/XML")
    page_xmp_ref = writer._add_object(page_xmp_stream)  # noqa: SLF001 - fixture construction
    writer.pages[0][NameObject("/Metadata")] = page_xmp_ref

    # Document-level `/PieceInfo` -- detection is `"/PieceInfo" in root`.
    piece_info = DictionaryObject()
    piece_info[NameObject("/PDFToolkitTestMarker")] = TextStringObject("present")
    writer._root_object[NameObject("/PieceInfo")] = piece_info  # noqa: SLF001

    with open(path, "wb") as handle:  # noqa: PTH123 - test-only scratch
        writer.write(handle)
    plain.unlink()

    spec = FixtureSpec(
        name="residual_surfaces", page_count=1, page_size=_LETTER, page_texts=(text,)
    )
    return path, spec


def _build_no_contents_page(root: Path) -> tuple[Path, FixtureSpec]:
    """Design D4.4 row 1's own fixture: a page carrying NO `/Contents` key
    at all -- `PdfWriter.add_blank_page` never sets one, which is exactly
    the shape a legitimately blank page has."""
    path = root / "no_contents_page.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=_LETTER[0], height=_LETTER[1])
    with open(path, "wb") as handle:  # noqa: PTH123 - test-only scratch
        writer.write(handle)
    # `PdfWriter.add_blank_page` sets no `/Rotate` either -- measured, and
    # declared here rather than left to `page.get("/Rotate", 0)` to flatten
    # into a `0` indistinguishable from an explicit one (B-084).
    spec = FixtureSpec(
        name="no_contents_page",
        page_count=1,
        page_size=_LETTER,
        page_texts=("",),
        rotate_key_absent_on=(0,),
    )
    return path, spec


def _build_empty_contents_page(root: Path) -> tuple[Path, FixtureSpec]:
    """Design D4.4 row 2's own fixture: a page whose `/Contents` key IS
    present but points at a zero-length stream -- deliberately distinct
    from `no_contents_page` (D4.4 treats the two cases differently: this
    one is ordinary, `no_contents_page` gets a run-level warning)."""
    path = root / "empty_contents_page.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=_LETTER[0], height=_LETTER[1])
    stream = StreamObject()
    stream.set_data(b"")
    page[NameObject("/Contents")] = writer._add_object(stream)  # noqa: SLF001
    with open(path, "wb") as handle:  # noqa: PTH123 - test-only scratch
        writer.write(handle)
    spec = FixtureSpec(
        name="empty_contents_page",
        page_count=1,
        page_size=_LETTER,
        page_texts=("",),
        rotate_key_absent_on=(0,),
    )
    return path, spec


#: The literal ASCII marker `stamp_source` draws, and the marker
#: `tests/unit/test_overlay.py`/`tests/integration/test_overlay_preservation.py`
#: locate with `bytes.index` (never `find`) to prove content-stream order
#: (Design §D4.3). Exported so no test retypes the literal.
STAMP_MARKER: Final[str] = "ZZSTAMPZZ"


def _build_stamp_source(root: Path) -> tuple[Path, FixtureSpec]:
    """Design §D4.3's own fixture: a one-page PDF carrying `STAMP_MARKER` in
    a BASE-14 font (Helvetica), so it appears in the content stream as a
    literal `(ZZSTAMPZZ) Tj` rather than a subset-encoded hex string --
    `stamp`'s `--from` operand for the underlay/overlay ordering proof."""
    path = root / "stamp_source.pdf"
    made = _new_canvas(path, _LETTER)
    made.setFont("Helvetica", 24)
    made.drawString(72, 700, STAMP_MARKER)
    made.showPage()
    made.save()
    spec = FixtureSpec(
        name="stamp_source", page_count=1, page_size=_LETTER, page_texts=(STAMP_MARKER,)
    )
    return path, spec


def _build_rotate_absent(root: Path) -> tuple[Path, FixtureSpec]:
    """B-084 — a page carrying NO ``/Rotate`` key at all.

    THE FILED PREMISE WAS WRONG AND THE MEASUREMENT IS RECORDED HERE. B-084
    reads *"reportlab writes an explicit `/Rotate 0`, so no fixture can express
    absent"*. Measured across all fifteen fixtures at `2d19bcb`, thirteen do
    carry an explicit ``/Rotate`` on every page — but ``no_contents_page`` and
    ``empty_contents_page`` do NOT, because they are built by
    ``pypdf.PdfWriter.add_blank_page`` rather than emitted by reportlab, and
    that writer sets no ``/Rotate``. The absent state was
    therefore already REACHABLE; what did not exist was any way to SAY SO. Both
    of `tests/test_corpus.py`'s rotation branches read
    ``page.get("/Rotate", 0)``, which collapses absent and zero into the same
    ``0``, so a verb that must distinguish them had no fixture that could tell
    it it was wrong.

    This fixture exists anyway, and deliberately: the other two carry the state
    INCIDENTALLY, as a side effect of being built for a different purpose, so a
    future edit to either could restore the key and quietly remove the only
    coverage of the absent case. One fixture whose entire purpose is that state
    cannot lose it by accident.

    Built by deleting the key reportlab emits, via pikepdf — already a runtime
    dependency, so **Q5 holds and no dependency is added**. ``deterministic_id``
    keeps it byte-identical across two independent builds (measured), so it
    joins AC2's determinism assertion rather than needing an exemption.
    """
    text = "rotate_absent fixture -- no /Rotate key on any page."
    staged = root / "_rotate_absent_staged.pdf"
    made = _new_canvas(staged, _LETTER)
    made.drawString(72, 700, text)
    made.showPage()
    made.save()

    path = root / "rotate_absent.pdf"
    with pikepdf.open(str(staged)) as pdf:
        for page in pdf.pages:
            if "/Rotate" in page.obj:
                del page.obj["/Rotate"]
        pdf.save(str(path), deterministic_id=True)
    staged.unlink()

    spec = FixtureSpec(
        name="rotate_absent",
        page_count=1,
        page_size=_LETTER,
        page_texts=(text,),
        rotate_key_absent_on=(0,),
    )
    return path, spec


#: Build order. `FIXTURE_NAMES` mirrors it for iteration by name.
_BUILDERS: Final[tuple[Callable[[Path], tuple[Path, FixtureSpec]], ...]] = (
    _build_multipage_text,
    _build_ten_page_text,
    _build_rotated,
    _build_jpeg_page,
    _build_encrypted_aes256,
    _build_metadata_rich,
    _build_single_page,
    _build_tabular,
    _build_metadata_typed,
    _build_xmp_bearing,
    _build_xmp_disagreement,
    _build_residual_surfaces,
    _build_no_contents_page,
    _build_empty_contents_page,
    _build_stamp_source,
    _build_rotate_absent,
)

FIXTURE_NAMES: Final[tuple[str, ...]] = tuple(
    name
    for name in (
        "multipage_text",
        "ten_page_text",
        "rotated",
        "jpeg_page",
        "encrypted_aes256",
        "metadata_rich",
        "single_page",
        "tabular",
        "metadata_typed",
        "xmp_bearing",
        "xmp_disagreement",
        "residual_surfaces",
        "no_contents_page",
        "empty_contents_page",
        "stamp_source",
        "rotate_absent",
    )
)


class Corpus:
    """One session's built fixture corpus: generated paths plus their own specs.

    Exposed to tests as ``corpus.path(name)`` / ``corpus.spec(name)`` so an
    assertion is always made against the spec that generated the file, never
    against a literal repeated in a test module.
    """

    def __init__(self, paths: Mapping[str, Path], specs: Mapping[str, FixtureSpec]) -> None:
        self._paths = dict(paths)
        self._specs = dict(specs)

    def path(self, name: str) -> Path:
        try:
            return self._paths[name]
        except KeyError:
            raise KeyError(f"unknown corpus fixture {name!r}; have {self.names()}") from None

    def spec(self, name: str) -> FixtureSpec:
        try:
            return self._specs[name]
        except KeyError:
            raise KeyError(f"unknown corpus fixture {name!r}; have {self.names()}") from None

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._paths))


def build_corpus(root: Path) -> Corpus:
    """Build every fixture into *root* and return the handle.

    Each fixture is deterministic on its own (see the module docstring); two
    calls with two different *root* values produce byte-identical files for
    every fixture except ``encrypted_aes256``, proven by ``tests/test_corpus.py``.
    """
    root.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    specs: dict[str, FixtureSpec] = {}
    for builder in _BUILDERS:
        path, spec = builder(root)
        paths[spec.name] = path
        specs[spec.name] = spec
    return Corpus(paths, specs)
