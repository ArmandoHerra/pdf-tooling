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

from PIL import Image
from pypdf import PdfReader, PdfWriter
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
        rotations: Expected ``/Rotate`` per page. Empty when no page is rotated.
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
