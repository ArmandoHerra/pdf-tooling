"""``compose`` and ``create`` — the two verbs that turn non-PDF input into PDF.

Framework-free per L2: no ``typer``/``click``, no ``sys.exit``, no printing.
``PLAN.md`` §8 lists one module for both verbs, and they genuinely share one:
the page-size grammar, the margin grammar, the atomic-write shape and the
per-item reporting are identical, and only the source material differs.

THE ONE GUARANTEE, AND THE THREE WAYS TO LOSE IT
------------------------------------------------
A JPEG file already *is* a DCT-compressed bitstream and PDF's ``/DCTDecode``
filter stores exactly that, so embedding one correctly is a **byte copy**: the
page carries the original scan, bit for bit. An implementation that decodes and
re-encodes is silently lossy, produces a bigger file, and looks identical on
screen — which is why this module's acceptance signal is byte-level and not
visual.

Three ways to fall off it, all guarded here rather than downstream:

1. **Handing the renderer pixels instead of a path.** The passthrough is offered
   only while the original file bytes are still to hand. So
   :class:`~pdf_toolkit.ports.compose.ImagePlacement` carries ``raster=None`` for
   every input that may pass through, and Pillow is used **for inspection only**
   on that path — ``Image.open()`` for ``.size``/``.format``/``.mode``/``.info``,
   never ``.load()``, never a conversion.
2. **Transforming pixels to satisfy layout.** Scaling, centring and
   ``--fit cover``'s crop are **graphics-state** operations — a scale in the CTM
   and a PDF clip path — never Pillow operations. Geometry here is placement;
   it is never resampling.
3. **Deciding eligibility by extension.** The renderer sniffs *nothing*: handed
   anything whose magic reads as JPEG it stores the bytes unconditionally,
   progressive included. So :func:`inspect_image` reads the frame header itself.

Eligibility, as it binds (each row measured against the renderer, not assumed):

============================  =========================  =========================
Input                         Path                       Why
============================  =========================  =========================
JPEG SOF0/SOF1, 1 component   ``/DCTDecode`` passthrough ``/DeviceGray``
JPEG SOF0/SOF1, 3 components  ``/DCTDecode`` passthrough ``/DeviceRGB``
JPEG SOF0/SOF1, 4 components  ``/DCTDecode`` passthrough ``/DeviceCMYK`` **plus**
                                                         the Adobe inversion
                                                         array, so the page is
                                                         right and the bytes
                                                         survive. Reported as
                                                         ``colorspace: cmyk``;
                                                         **no** warning — a
                                                         warning on a path that
                                                         works is noise.
JPEG SOF2 (progressive)       ``/FlateDecode`` + warning ``/DCTDecode`` is
                                                         specified against the
                                                         baseline profile and
                                                         progressive support in
                                                         real viewers is
                                                         inconsistent. Where a
                                                         correct page and
                                                         byte-identity conflict,
                                                         the page wins — and the
                                                         user is told, which is
                                                         the whole difference
                                                         between a trade-off and
                                                         a silent one.
PNG, TIFF, WebP, BMP, GIF     ``/FlateDecode``           Not DCT data;
                                                         passthrough is
                                                         impossible by
                                                         construction. Normal,
                                                         so no warning.
============================  =========================  =========================

``compose`` never JPEG-encodes anything. Shrinking a PDF is a different verb.

WRITING
-------
Both verbs produce exactly **one** file and both write through
:class:`~pdf_toolkit.safety.atomic.AtomicWriter`, handing the engine
``atomic.stream`` — never ``atomic.path``, never a filename. This module calls
no ``open(..., "w")``, no ``write_bytes``, no ``mkdir``; no ``ops/`` allowlist
entry is needed in ``tests/test_import_boundaries.py``.
"""

from __future__ import annotations

import io
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from PIL import Image, UnidentifiedImageError

from pdf_toolkit.errors import FailureError, NoInputError, UsageError
from pdf_toolkit.models import SCHEMA_VERSION as _SCHEMA_VERSION
from pdf_toolkit.models import ItemResult, OperationResult
from pdf_toolkit.ports.compose import ImagePlacement, TextLayout, require_compose
from pdf_toolkit.safety.atomic import AtomicWriter
from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = [
    "BASE14_FONTS",
    "COMPOSE_VERB",
    "CREATE_VERB",
    "DEFAULT_COMPOSE_MARGIN",
    "DEFAULT_CREATE_MARGIN",
    "DEFAULT_FIT",
    "DEFAULT_FONT",
    "DEFAULT_SIZE",
    "FIT_MODES",
    "FROM_IMAGE",
    "NAMED_PAGE_SIZES",
    "ImageFacts",
    "PageSize",
    "compose_document",
    "create_document",
    "decode_utf8",
    "inspect_image",
    "lines_per_page",
    "normalize_text",
    "parse_length",
    "parse_page_size",
    "plan_placements",
    "resolve_create_output",
    "resolve_single_output",
    "sanitize_text",
]

COMPOSE_VERB: Final[str] = "compose"
CREATE_VERB: Final[str] = "create"

#: PostScript points per inch. The only conversion constant in this module that
#: is not derived from another one.
POINTS_PER_INCH: Final[float] = 72.0

#: ``--page-size`` names. A4's dimensions are the ISO 216 millimetre sizes
#: converted at 72 pt/in, so ``a4`` and ``210x297mm`` agree by construction.
NAMED_PAGE_SIZES: Final[dict[str, tuple[float, float]]] = {
    "a4": (595.276, 841.890),
    "letter": (612.0, 792.0),
}

#: ``--page-size from-image``: each page is sized to its OWN image. A compose of
#: differently-sized scans yields differently-sized pages — never normalised to
#: the first, to the largest, or to a bounding box. It is the only mode that
#: returns the source geometry, which is why the round-trip uses it.
FROM_IMAGE: Final[str] = "from-image"

FIT_MODES: Final[tuple[str, ...]] = ("contain", "cover", "stretch")
DEFAULT_FIT: Final[str] = "contain"

#: The base-14 fonts, which is the whole of v1's font support (no embedding, no
#: TTF/OTF loading). Hard-coded rather than read from the engine because this
#: module is engine-free; ``tests/unit/test_create.py`` pins this tuple against
#: the engine's own list, so a drift is a loud failure rather than a surprise.
BASE14_FONTS: Final[tuple[str, ...]] = (
    "Courier",
    "Courier-Bold",
    "Courier-Oblique",
    "Courier-BoldOblique",
    "Helvetica",
    "Helvetica-Bold",
    "Helvetica-Oblique",
    "Helvetica-BoldOblique",
    "Times-Roman",
    "Times-Bold",
    "Times-Italic",
    "Times-BoldItalic",
    "Symbol",
    "ZapfDingbats",
)

DEFAULT_FONT: Final[str] = "Helvetica"
DEFAULT_SIZE: Final[float] = 11.0

#: Leading as a multiple of the type size.
LEADING_RATIO: Final[float] = 1.2

#: A tab is four spaces. Fixed, not configurable: the page count has to be
#: derivable from (text, font, size, page size, margin) and nothing else.
TAB_WIDTH: Final[int] = 4

#: The two margin defaults differ deliberately. ``compose`` places an image and
#: any margin is a decision the user makes; ``create`` sets a document and a
#: text block flush to the page edge is never what anyone wanted.
DEFAULT_COMPOSE_MARGIN: Final[str] = "0"
DEFAULT_CREATE_MARGIN: Final[str] = "54pt"

#: The text encoding the base-14 fonts carry. Characters outside it are replaced
#: with ``?`` **and warned about** — never silently dropped.
_TEXT_ENCODING: Final[str] = "cp1252"

_UNITS: Final[dict[str, float]] = {
    "pt": 1.0,
    "mm": POINTS_PER_INCH / 25.4,
    "cm": POINTS_PER_INCH / 2.54,
    "in": POINTS_PER_INCH,
}

_NUMBER = r"\d+(?:\.\d+)?"
_UNIT = "|".join(_UNITS)
_LENGTH_RE: Final[re.Pattern[str]] = re.compile(rf"^({_NUMBER})({_UNIT})?$", re.IGNORECASE)
_PAGE_SIZE_RE: Final[re.Pattern[str]] = re.compile(
    rf"^({_NUMBER})x({_NUMBER})({_UNIT})?$", re.IGNORECASE
)

_PDF_MAGIC: Final[bytes] = b"%PDF-"

#: JPEG frame markers. ``0xC4``/``0xC8``/``0xCC`` share the ``0xCn`` range but
#: are not frame headers (Huffman table, reserved, arithmetic-coding table).
_SOF_BASELINE: Final[frozenset[int]] = frozenset({0xC0, 0xC1})
_SOF_PROGRESSIVE: Final[int] = 0xC2
_NOT_A_FRAME: Final[frozenset[int]] = frozenset({0xC4, 0xC8, 0xCC})

EMBED_PASSTHROUGH: Final[str] = "dctdecode-passthrough"
EMBED_REENCODE: Final[str] = "flate-reencode"

DPI_FLAG: Final[str] = "flag"
DPI_IMAGE: Final[str] = "image"
DPI_DEFAULT: Final[str] = "default"


# --------------------------------------------------------------------------- #
# Grammars — the two the CLI hands straight through, both exit 2 on a
# malformed value with the offending string quoted.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PageSize:
    """A resolved ``--page-size``: either a fixed size, or per-image."""

    from_image: bool
    size: tuple[float, float] | None
    """``None`` exactly when :attr:`from_image` is true."""


def parse_length(raw: str, *, flag: str) -> float:
    """``"54"`` / ``"54pt"`` / ``"20mm"`` -> points. Malformed is exit 2."""
    match = _LENGTH_RE.match(raw.strip())
    if match is None:
        raise UsageError(
            f"{flag} {raw!r} is not a length; expected N or N<unit> "
            f"with unit one of {', '.join(_UNITS)}"
        )
    return float(match.group(1)) * _UNITS[(match.group(2) or "pt").lower()]


def parse_page_size(raw: str) -> PageSize:
    """``a4`` | ``letter`` | ``from-image`` | ``WxH[unit]``. Malformed is exit 2."""
    value = raw.strip()
    lowered = value.lower()
    if lowered == FROM_IMAGE:
        return PageSize(from_image=True, size=None)
    named = NAMED_PAGE_SIZES.get(lowered)
    if named is not None:
        return PageSize(from_image=False, size=named)
    match = _PAGE_SIZE_RE.match(value)
    if match is None:
        raise UsageError(
            f"--page-size {raw!r} is not a page size; expected "
            f"{', '.join(NAMED_PAGE_SIZES)}, {FROM_IMAGE}, or WxH with an "
            f"optional unit ({', '.join(_UNITS)}), e.g. '612x792' or '210x297mm'"
        )
    factor = _UNITS[(match.group(3) or "pt").lower()]
    width = float(match.group(1)) * factor
    height = float(match.group(2)) * factor
    if width <= 0 or height <= 0:
        raise UsageError(f"--page-size {raw!r} must have a positive width and height")
    return PageSize(from_image=False, size=(width, height))


# --------------------------------------------------------------------------- #
# Inspection — what an input is, decided from its own bytes.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ImageFacts:
    """One input image, as sniffed. Never as inferred from its extension."""

    path: Path
    source_format: str
    """``JPEG``, ``PNG``, ``TIFF``, ``WEBP``, … as the decoder reports it."""

    width_px: int
    height_px: int
    mode: str
    colorspace: str
    """``rgb`` | ``gray`` | ``cmyk``."""

    passthrough: bool
    """True exactly when the stored stream will be this file's own bytes."""

    diverted: str | None
    """Why passthrough was declined **unexpectedly**, or ``None``. A PNG taking
    the re-encode path is normal and sets this to ``None``; a JPEG taking it is
    not, and this is what turns into the user-visible warning."""

    dpi: float
    dpi_source: str
    size_bytes: int

    @property
    def natural_size_pt(self) -> tuple[float, float]:
        """The image at its own density, in points."""
        return (
            self.width_px * POINTS_PER_INCH / self.dpi,
            self.height_px * POINTS_PER_INCH / self.dpi,
        )


def jpeg_frame(data: bytes) -> tuple[int, int] | None:
    """``(marker, component_count)`` of a JPEG's frame header, or ``None``.

    Walks the marker segments rather than trusting a library's summary, because
    the decision this feeds — pass the bytes through or re-encode them — is the
    product's central guarantee and must not depend on a decoder's convenience
    attribute.
    """
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    index = 2
    end = len(data)
    while index + 3 < end:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0x00, 0xFF, 0x01) or 0xD0 <= marker <= 0xD8:
            index += 2 if marker != 0xFF else 1
            continue
        if marker in (0xD9, 0xDA):  # end of image, or start of scan
            return None
        length = int.from_bytes(data[index + 2 : index + 4], "big")
        if length < 2:
            return None
        if 0xC0 <= marker <= 0xCF and marker not in _NOT_A_FRAME:
            payload = data[index + 4 : index + 2 + length]
            if len(payload) < 6:
                return None
            return marker, payload[5]
        index += 2 + length
    return None


def _density(info: dict[str, object]) -> float | None:
    """The image's own embedded density in dpi, or ``None`` when absent/zero."""
    raw = info.get("dpi")
    if not isinstance(raw, tuple | list) or not raw:
        return None
    try:
        value = float(raw[0])
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if value <= 0 or value != value or value == float("inf"):
        return None
    return value


def _colorspace(mode: str, components: int | None) -> str:
    if components == 4 or mode == "CMYK":
        return "cmyk"
    if components == 1 or mode in ("1", "L", "LA", "I;16"):
        return "gray"
    return "rgb"


def inspect_image(path: Path, *, dpi_flag: float | None) -> ImageFacts:
    """Sniff one operand. Every refusal here happens before anything is written.

    Exit 2 for a directory or a PDF (both are invocation mistakes with an
    obvious fix), exit 4 for a missing file, exit 1 for a real file the decoder
    cannot read as a raster.
    """
    if not path.exists():
        raise NoInputError("no such file", path=str(path))
    if path.is_dir():
        raise UsageError(
            "expected an image file, not a directory; globbing is the shell's "
            "job, so pass the files themselves (e.g. './scans/*.jpg')",
            path=str(path),
        )

    head = _read_head(path)
    if head.startswith(_PDF_MAGIC):
        raise UsageError(
            "this is a PDF, not an image; combining PDFs is what 'merge' does",
            path=str(path),
        )

    try:
        with Image.open(path) as probe:
            source_format = str(probe.format or "UNKNOWN")
            width_px, height_px = probe.size
            mode = str(probe.mode)
            info = {str(key): value for key, value in probe.info.items()}
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise FailureError(
            f"could not read as an image: {error}",
            path=str(path),
        ) from error

    components: int | None = None
    passthrough = False
    diverted: str | None = None
    if source_format == "JPEG":
        frame = jpeg_frame(path.read_bytes())
        if frame is None:
            diverted = "JPEG with no readable frame header"
        else:
            marker, components = frame
            if marker in _SOF_BASELINE:
                passthrough = True
            elif marker == _SOF_PROGRESSIVE:
                diverted = "progressive JPEG (SOF2)"
            else:
                diverted = f"non-baseline JPEG frame (SOF marker 0x{marker:02X})"

    if dpi_flag is not None:
        dpi, dpi_source = dpi_flag, DPI_FLAG
    else:
        embedded = _density(info)
        dpi, dpi_source = (
            (embedded, DPI_IMAGE) if embedded is not None else (POINTS_PER_INCH, DPI_DEFAULT)
        )

    return ImageFacts(
        path=path,
        source_format=source_format,
        width_px=width_px,
        height_px=height_px,
        mode=mode,
        colorspace=_colorspace(mode, components),
        passthrough=passthrough,
        diverted=diverted,
        dpi=dpi,
        dpi_source=dpi_source,
        size_bytes=path.stat().st_size,
    )


def _read_head(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read(len(_PDF_MAGIC))


# --------------------------------------------------------------------------- #
# Geometry — placement, never resampling.
# --------------------------------------------------------------------------- #


def plan_placements(
    facts: Sequence[ImageFacts],
    *,
    page: PageSize,
    fit: str,
    margin_pt: float,
) -> tuple[ImagePlacement, ...]:
    """Resolve every page's size, draw box and clip box. Pure: no decode, no IO.

    ``--fit`` applies only to a fixed page size; under ``from-image`` the image
    fills its own page by construction and the flag is inert (the caller warns
    rather than silently ignoring it).
    """
    if fit not in FIT_MODES:  # pragma: no cover - the CLI validates the enum
        raise UsageError(f"--fit {fit!r} is not one of {', '.join(FIT_MODES)}")
    return tuple(_place(fact, page=page, fit=fit, margin_pt=margin_pt) for fact in facts)


def _place(fact: ImageFacts, *, page: PageSize, fit: str, margin_pt: float) -> ImagePlacement:
    natural_w, natural_h = fact.natural_size_pt
    if page.from_image:
        page_size = (natural_w + 2 * margin_pt, natural_h + 2 * margin_pt)
        return ImagePlacement(
            source=fact.path,
            raster=None,
            page_size=page_size,
            draw_box=(margin_pt, margin_pt, natural_w, natural_h),
            clip_box=None,
        )

    if page.size is None:  # pragma: no cover - `from_image` returned above
        raise AssertionError("a fixed page size resolved to None")
    page_width, page_height = page.size
    content_w = page_width - 2 * margin_pt
    content_h = page_height - 2 * margin_pt
    if content_w <= 0 or content_h <= 0:
        raise UsageError(
            f"--margin {margin_pt:g}pt leaves no content area on a "
            f"{page_width:g}x{page_height:g} pt page"
        )

    if fit == "stretch":
        drawn_w, drawn_h = content_w, content_h
    else:
        ratios = (content_w / natural_w, content_h / natural_h)
        scale = min(ratios) if fit == "contain" else max(ratios)
        drawn_w, drawn_h = natural_w * scale, natural_h * scale

    x = margin_pt + (content_w - drawn_w) / 2
    y = margin_pt + (content_h - drawn_h) / 2
    return ImagePlacement(
        source=fact.path,
        raster=None,
        page_size=(page_width, page_height),
        draw_box=(x, y, drawn_w, drawn_h),
        clip_box=(margin_pt, margin_pt, content_w, content_h) if fit == "cover" else None,
    )


def _decode_for_reencode(path: Path, mode: str) -> Image.Image:
    """Decode an input that cannot be passed through.

    Reached only for inputs :func:`inspect_image` already ruled ineligible, so
    it can never touch the passthrough path. Alpha is dropped rather than
    composited: a page is paper, and v1 does not model transparency.
    """
    target = "L" if mode in ("1", "L", "LA", "I;16") else "CMYK" if mode == "CMYK" else "RGB"
    with Image.open(path) as opened:
        return opened.convert(target)


def _attach_rasters(
    facts: Sequence[ImageFacts], placements: Sequence[ImagePlacement]
) -> tuple[ImagePlacement, ...]:
    """Decode exactly the inputs that must be re-encoded, and nothing else."""
    return tuple(
        placement
        if fact.passthrough
        else replace(placement, raster=_decode_for_reencode(fact.path, fact.mode))
        for fact, placement in zip(facts, placements, strict=True)
    )


# --------------------------------------------------------------------------- #
# Output naming — the `-O`-omitted case (Design §11)
# --------------------------------------------------------------------------- #


def resolve_single_output(sources: Sequence[Path], output: Path | None, *, verb: str) -> Path:
    """The one output path, or exit 2 when there is no unambiguous stem.

    One operand and no ``-O`` derives ``photo.pdf`` beside ``photo.jpg``. Two or
    more and no ``-O`` is exit 2: silently picking the first operand's stem is
    the kind of guess that surprises someone at a hundred files.
    """
    if output is not None:
        return output
    if len(sources) == 1:
        return sources[0].with_suffix(".pdf")
    raise UsageError(
        f"{verb} of {len(sources)} inputs writes one PDF and has no unambiguous "
        f"name to derive; pass -O/--output"
    )


def resolve_create_output(source: Path, output: Path | None, *, from_stdin: bool) -> Path:
    """``create``'s output path, or exit 2 when standard input leaves no stem.

    The refusal message lives here rather than in the CLI module on purpose:
    ``cli/cmd_create.py`` carries no output-flag literal at all (OR-3 — there is
    exactly one refusal path in the product and it is the shared one), so the
    only place allowed to *name* the flag in prose is this layer.
    """
    if output is not None:
        return output
    if from_stdin:
        raise UsageError(
            "create from standard input has no input stem to derive an output "
            "name from; pass -O/--output"
        )
    return source.with_suffix(".pdf")


def decode_utf8(raw: bytes, *, source: str) -> str:
    """Decode input text, naming the byte offset when it is not UTF-8.

    Exit 1, not 2: the invocation was fine and the operation ran; the *input*
    is what failed. UTF-8 is the only encoding v1 accepts (there is no
    ``--encoding`` flag), and an offset is what makes that answerable.
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FailureError(
            f"not valid UTF-8 at byte offset {error.start} ({error.reason}); "
            f"UTF-8 is the only encoding this verb accepts",
            path=source,
        ) from error


# --------------------------------------------------------------------------- #
# Text — normalisation, encodability and the pure half of pagination.
# --------------------------------------------------------------------------- #


def normalize_text(text: str) -> str:
    """CRLF/CR to LF, tabs to spaces, one trailing newline dropped.

    Dropping exactly one trailing newline is the plain-text-file convention: a
    file ending ``"x\\n"`` is one line, not one line and an empty one, and the
    page-count arithmetic has to agree with what a user counted.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\t", " " * TAB_WIDTH)
    if normalized.endswith("\n"):
        normalized = normalized[:-1]
    return normalized


def sanitize_text(text: str) -> tuple[str, str | None]:
    """Replace unrepresentable characters with ``?``; return the text and a warning.

    The base-14 fonts cannot represent CJK, emoji and much else. Left alone the
    engine draws a placeholder glyph and says nothing, which is exactly the
    silent degradation this product refuses. So the substitution is explicit and
    it is counted, and the caller surfaces the count, the first offending
    codepoint and its line number.
    """
    out: list[str] = []
    replaced = 0
    first: tuple[int, int] | None = None
    line_number = 1
    for character in text:
        try:
            character.encode(_TEXT_ENCODING)
        except UnicodeEncodeError:
            replaced += 1
            if first is None:
                first = (ord(character), line_number)
            out.append("?")
            continue
        if character == "\n":
            line_number += 1
        out.append(character)
    if first is None:
        return "".join(out), None
    codepoint, line = first
    return "".join(out), (
        f"{replaced} character(s) outside the font's WinAnsi encoding were "
        f"replaced with '?' (first: U+{codepoint:04X} on line {line})"
    )


def lines_per_page(page_size: tuple[float, float], margin_pt: float, size: float) -> int:
    """How many lines of *size* fit between the margins. Pure geometry.

    Deliberately not behind the engine: the page count has to be predictable
    from the invocation alone, so the only thing the engine decides is where a
    line *wraps*, never how many fit.
    """
    content_h = page_size[1] - 2 * margin_pt
    if content_h <= 0:
        raise UsageError(
            f"--margin {margin_pt:g}pt leaves no content area on a "
            f"{page_size[0]:g}x{page_size[1]:g} pt page"
        )
    return max(1, int(content_h // (size * LEADING_RATIO)))


# --------------------------------------------------------------------------- #
# The verbs.
# --------------------------------------------------------------------------- #


def _item(
    *,
    source: str,
    output: Path,
    refusal_code: int,
    message: str,
    bytes_before: int | None,
    bytes_after: int | None,
    detail: dict[str, object],
    duration_ms: int = 0,
) -> ItemResult:
    return ItemResult(
        input=source,
        output=str(output),
        ok=refusal_code == 0,
        exit_code=refusal_code,
        message=message,
        bytes_before=bytes_before,
        bytes_after=bytes_after,
        duration_ms=duration_ms,
        detail=detail,
    )


def compose_document(
    sources: Sequence[Path],
    *,
    output: Path,
    page: PageSize,
    fit: str,
    margin_pt: float,
    dpi: float | None,
    policy: SafetyPolicy,
) -> OperationResult:
    """Compose *sources* into one PDF, one page per operand, in argv order.

    Ordering is argv order and nothing else: duplicates are permitted and
    produce duplicate pages, there is no sorting and no de-duplication.
    ``items`` carries one row per input, in the same order, each with its 1-based
    page in ``detail`` — so the ordering is machine-verifiable rather than merely
    visual.
    """
    started = time.monotonic()
    if not sources:
        raise UsageError("compose needs at least one image")
    engine = require_compose(capability="compose")

    facts = tuple(inspect_image(path, dpi_flag=dpi) for path in sources)
    placements = plan_placements(facts, page=page, fit=fit, margin_pt=margin_pt)

    warnings: list[str] = []
    if page.from_image and fit != DEFAULT_FIT:
        warnings.append(
            f"--fit {fit} is inert with --page-size {FROM_IMAGE}: each page is "
            f"sized to its own image, so there is nothing to fit it to"
        )
    warnings.extend(
        f"{fact.path}: {fact.diverted}; stored as a re-encoded Flate stream "
        f"rather than the original compressed bytes"
        for fact in facts
        if fact.diverted is not None
    )

    refusal = None
    would_exit = 0
    with AtomicWriter(output, policy=policy, kind="pdf") as atomic:
        if atomic.is_dry_run:
            refusal = atomic.planned_refusal
            would_exit = atomic.would_exit
        else:
            engine.compose_images(_attach_rasters(facts, placements), out=atomic.stream)

    written = output.stat().st_size if output.exists() else None
    duration_ms = int((time.monotonic() - started) * 1000)
    items = tuple(
        _item(
            source=str(fact.path),
            output=output,
            refusal_code=0 if refusal is None else refusal.exit_code,
            message=(
                _compose_message(fact, placement, index) if refusal is None else refusal.message
            ),
            bytes_before=fact.size_bytes,
            bytes_after=written,
            detail=_compose_detail(
                fact, placement, index, dry_run=policy.dry_run, would_exit=would_exit
            ),
            duration_ms=duration_ms,
        )
        for index, (fact, placement) in enumerate(zip(facts, placements, strict=True), start=1)
    )
    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=COMPOSE_VERB,
        dry_run=policy.dry_run,
        items=items,
        warnings=tuple(warnings),
        duration_ms=duration_ms,
    )


def _embed(fact: ImageFacts) -> str:
    return EMBED_PASSTHROUGH if fact.passthrough else EMBED_REENCODE


def _compose_message(fact: ImageFacts, placement: ImagePlacement, page_number: int) -> str:
    width, height = placement.page_size
    return (
        f"page {page_number}: {fact.width_px}x{fact.height_px} px "
        f"{fact.source_format} @ {fact.dpi:g} dpi on a {width:g}x{height:g} pt "
        f"page ({_embed(fact)})"
    )


def _compose_detail(
    fact: ImageFacts,
    placement: ImagePlacement,
    page_number: int,
    *,
    dry_run: bool,
    would_exit: int,
) -> dict[str, object]:
    detail: dict[str, object] = {
        "page": page_number,
        "embed": _embed(fact),
        "stream_bytes_identical": fact.passthrough,
        "source_format": fact.source_format,
        "colorspace": fact.colorspace,
        "dpi": fact.dpi,
        "dpi_source": fact.dpi_source,
        "image_width_px": fact.width_px,
        "image_height_px": fact.height_px,
        "page_width_pt": placement.page_size[0],
        "page_height_pt": placement.page_size[1],
    }
    if dry_run:
        detail["would_exit"] = would_exit
    return detail


def create_document(
    text: str,
    *,
    source: str,
    output: Path,
    font: str,
    size: float,
    page: PageSize,
    margin_pt: float,
    title: str | None,
    policy: SafetyPolicy,
) -> OperationResult:
    """Render one plain-text input into one PDF.

    v1 is plain text only — no Markdown, no HTML, no font embedding. *source* is
    the label the item row reports (a path, or ``-`` for standard input); the
    reading itself belongs to the CLI, because "is this a terminal?" is not a
    question this layer can answer honestly.
    """
    started = time.monotonic()
    if font not in BASE14_FONTS:
        raise UsageError(
            f"--font {font!r} is not one of the base-14 fonts; v1 embeds no "
            f"fonts. Accepted: {', '.join(BASE14_FONTS)}"
        )
    if size <= 0:
        raise UsageError("--size must be greater than 0")
    if page.from_image:
        raise UsageError(
            f"--page-size {FROM_IMAGE} sizes a page to an image; create has no "
            f"image. Use {', '.join(NAMED_PAGE_SIZES)} or WxH"
        )
    if not text:
        raise NoInputError("no text to render; nothing was written", path=source)

    if page.size is None:  # pragma: no cover - `from_image` was refused above
        raise AssertionError("a fixed page size resolved to None")
    engine = require_compose(capability="text-layout")

    sanitized, warning = sanitize_text(text)
    body = normalize_text(sanitized)
    layout = TextLayout(
        font=font,
        size=size,
        leading=size * LEADING_RATIO,
        page_size=page.size,
        margin_pt=margin_pt,
        lines_per_page=lines_per_page(page.size, margin_pt, size),
        title=title,
    )

    refusal = None
    would_exit = 0
    with AtomicWriter(output, policy=policy, kind="pdf") as atomic:
        if atomic.is_dry_run:
            refusal = atomic.planned_refusal
            would_exit = atomic.would_exit
            # A dry run still renders -- into a buffer it throws away -- so the
            # page count it reports is measured rather than guessed. Nothing
            # here touches the filesystem.
            page_count = engine.render_text(body, layout=layout, out=io.BytesIO()).page_count
        else:
            page_count = engine.render_text(body, layout=layout, out=atomic.stream).page_count

    written = output.stat().st_size if output.exists() else None
    duration_ms = int((time.monotonic() - started) * 1000)
    detail: dict[str, object] = {
        "page": 1,
        "page_count": page_count,
        "font": font,
        "size_pt": size,
        "leading_pt": layout.leading,
        "lines_per_page": layout.lines_per_page,
        "page_width_pt": layout.page_size[0],
        "page_height_pt": layout.page_size[1],
    }
    if policy.dry_run:
        detail["would_exit"] = would_exit
    item = _item(
        source=source,
        output=output,
        refusal_code=0 if refusal is None else refusal.exit_code,
        message=(
            f"{page_count} page(s) of {font} {size:g}pt" if refusal is None else refusal.message
        ),
        bytes_before=len(text.encode("utf-8")),
        bytes_after=written,
        detail=detail,
        duration_ms=duration_ms,
    )
    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=CREATE_VERB,
        dry_run=policy.dry_run,
        items=(item,),
        warnings=(warning,) if warning is not None else (),
        duration_ms=duration_ms,
    )
