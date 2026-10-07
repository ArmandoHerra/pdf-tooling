"""The ``RasterEngine`` port — render pages to images.

One adapter: **pypdfium2**. PDF-05 shipped the probe surface only, deliberately
(``ports/__init__``'s docstring: a stub for an operation nobody implements yet
is worse than its absence). PDF-09 (`rasterize`) is the first consumer of the
render method below, and PDF-15 (`ocr`) is its second — see :class:`RenderedPage`.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, cast

from pdf_tooling.errors import FailureError, RenderBudgetError
from pdf_tooling.models import EngineReport
from pdf_tooling.ports import KIND_PYTHON_PACKAGE, Adapter, build_report, require

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

    from pdf_tooling.adapters import AdapterProbe

__all__ = [
    "DPI_CEILING",
    "PIXEL_BUDGET",
    "WIDTH_CEILING",
    "PagePixels",
    "RasterEngine",
    "RenderedPage",
    "adapters",
    "enforce_render_budget",
    "page_pixels",
    "probe",
    "require_raster",
]

PORT = "RasterEngine"

#: PDF-112 / X-1002 -- the most pixels one rendered page may allocate. It is
#: twice Pillow's default ``Image.MAX_IMAGE_PIXELS`` (89,478,485) as of the
#: ruling, written as a literal on purpose: a Pillow bump must never move a
#: published number. No env var, flag or config key reads it.
PIXEL_BUDGET: Final[int] = 178_956_970

#: ``rasterize --dpi`` ceiling; larger (or non-finite) values exit 2.
DPI_CEILING: Final[float] = 2400.0

#: ``rasterize --width`` ceiling; larger values exit 2.
WIDTH_CEILING: Final[int] = 32768

_POINTS_PER_INCH: Final[float] = 72.0


@dataclass(frozen=True, slots=True)
class RenderedPage:
    """One rendered page's in-memory pixels (Design §D2).

    The carrier :meth:`RasterEngine.render_page` returns: encoding, naming and
    the write itself stay outside the port (D2) — a caller that wants pixels
    without a file (``ocr``, PDF-15) gets exactly this and nothing more. It
    never crosses a process boundary: PDF-09's per-worker render+encode+write
    happens inside one call, so only plain, picklable ``ItemResult`` data
    crosses back out of a worker (PLAN §12 R-08, Design §D5).
    """

    image: Image
    """The decoded pixels. ``mode`` is ``"RGB"`` or ``"L"``; never carries an
    alpha channel (Design §D6 — a page is paper, rendered onto opaque white)."""

    width_px: int
    height_px: int
    mode: str

    dpi_effective: float
    """The DPI the produced pixels actually represent. Equal to the requested
    ``--dpi`` under DPI mode; derived from the produced width under
    ``--width`` mode (Design §D6 — measured, never guessed)."""


@dataclass(frozen=True)
class PagePixels:
    """One page's bitmap geometry, from exactly the box pdfium allocates from."""

    displayed_width_pt: float
    displayed_height_pt: float
    target_width: int
    """``round()``-based output size (the product's promised pixel size)."""
    target_height: int
    alloc_width: int
    """``ceil()``-based size -- what pypdfium2's ``render()`` allocates."""
    alloc_height: int
    scale: float
    dpi_effective: float

    @property
    def alloc_pixels(self) -> int:
        return self.alloc_width * self.alloc_height


def page_pixels(
    displayed_width_pt: float,
    displayed_height_pt: float,
    *,
    dpi: float | None,
    width_px: int | None,
) -> PagePixels:
    """The ONE pure function that sizes a page's bitmap (PDF-112 / X-1002).

    No I/O and no pdfium. The ``target_*`` arithmetic is the former
    ``_target_dimensions`` byte-for-byte; ``alloc_*`` is pypdfium2's own
    ``ceil(points * scale)`` sizing, which is what the budget compares.
    """
    if not (displayed_width_pt > 0 and displayed_height_pt > 0):
        raise FailureError(
            f"page box {displayed_width_pt:g} x {displayed_height_pt:g} pt has no positive area"
        )
    if width_px is not None:
        target_width = width_px
        target_height = max(1, round(width_px * displayed_height_pt / displayed_width_pt))
        dpi_effective = width_px / displayed_width_pt * _POINTS_PER_INCH
    else:
        if dpi is None:  # pragma: no cover - caller guarantees exactly one of dpi/width_px is set
            raise ValueError("page_pixels requires exactly one of dpi or width_px")
        target_width = max(1, round(displayed_width_pt * dpi / _POINTS_PER_INCH))
        target_height = max(1, round(displayed_height_pt * dpi / _POINTS_PER_INCH))
        dpi_effective = dpi
    scale = dpi_effective / _POINTS_PER_INCH
    return PagePixels(
        displayed_width_pt=displayed_width_pt,
        displayed_height_pt=displayed_height_pt,
        target_width=target_width,
        target_height=target_height,
        alloc_width=math.ceil(displayed_width_pt * scale),
        alloc_height=math.ceil(displayed_height_pt * scale),
        scale=scale,
        dpi_effective=dpi_effective,
    )


def _largest_whole(low: int, high: int, fits: Callable[[int], bool]) -> int | None:
    """Largest whole ``n`` in ``[low, high]`` with ``fits(n)`` true, by binary
    search (``fits`` is monotone: larger n only allocates more)."""
    if low > high or not fits(low):
        return None
    lo, hi = low, high
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def enforce_render_budget(
    pixels: PagePixels,
    *,
    page_number: int,
    path: str,
    dpi: float | None,
    width_px: int | None,
    dpi_floor: float = 1.0,
) -> None:
    """Raise :class:`RenderBudgetError` iff the page would allocate more than
    :data:`PIXEL_BUDGET` pixels. Equality is legal. Advice is found by search
    through :func:`page_pixels`, never by closed form."""
    if pixels.alloc_pixels <= PIXEL_BUDGET:
        return
    w, h = pixels.displayed_width_pt, pixels.displayed_height_pt
    best_dpi = _largest_whole(
        math.ceil(dpi_floor),
        int(DPI_CEILING),
        lambda d: page_pixels(w, h, dpi=float(d), width_px=None).alloc_pixels <= PIXEL_BUDGET,
    )
    message = (
        f"{path}: page {page_number} would render at "
        f"{pixels.alloc_width:,}x{pixels.alloc_height:,} px ({pixels.alloc_pixels:,} px), "
        f"over the per-page budget of {PIXEL_BUDGET:,} px; "
    )
    if best_dpi is None:
        message += "no --dpi this command accepts fits this page"
    else:
        message += f"the largest --dpi that fits this page is {best_dpi:,}"
    if width_px is not None:
        best_width = _largest_whole(
            1,
            WIDTH_CEILING,
            lambda v: page_pixels(w, h, dpi=None, width_px=v).alloc_pixels <= PIXEL_BUDGET,
        )
        if best_width is None:
            message += "; no --width this command accepts fits this page"
        else:
            message += f"; the largest --width that fits is {best_width:,}"
    raise RenderBudgetError(message, path=path)


class RasterEngine(Protocol):
    """Render pages to raster images."""

    @property
    def adapter_name(self) -> str: ...

    def capabilities(self) -> frozenset[str]: ...

    def probe(self) -> AdapterProbe: ...

    def render_page(
        self,
        path: str,
        page_number: int,
        *,
        dpi: float | None,
        width_px: int | None,
        grayscale: bool,
        password: str | None = None,
    ) -> RenderedPage:
        """Render one page to in-memory pixels.

        Args:
            path: The source PDF's path, as plain text — not a document
                handle (Design §D2/§D5): the caller may run this from a
                worker that must open, render and close its own document.
            page_number: 1-based.
            dpi: Render scale in dots per inch. Mutually exclusive with
                ``width_px`` at the call site — exactly one is non-``None``.
            width_px: Target pixel width; height follows the page's own
                (post-rotation) aspect ratio.
            grayscale: Single-channel (``"L"``) output.
            password: PDF-37 -- the REVEALED plaintext, or ``None``. A plain
                ``str`` rather than a
                :class:`~pdf_tooling.secret.Secret`, for the SAME reason
                ``path`` above is plain text: this call may cross a
                ``ProcessPoolExecutor`` worker boundary, and a ``Secret``
                refuses to pickle by design.

        Raises:
            AuthError: Exit 6 — no password was supplied and one is
                required, or the supplied password did not unlock it.
            FailureError: Exit 1 — pypdfium2 could not render the page. Never
                a fallback to another engine (PLAN §7.2 / Design §D8).
        """
        ...

    def measure_pages(
        self,
        path: str,
        page_numbers: list[int] | tuple[int, ...],
        *,
        dpi: float | None,
        width_px: int | None,
        password: str | None = None,
    ) -> tuple[PagePixels, ...]:
        """Size each page's bitmap WITHOUT loading or rendering it (PDF-112).

        Planning-only: reads each page's displayed box by index and never
        crosses a process boundary. Raises like :meth:`render_page` on an
        unopenable or locked document.
        """
        ...


def adapters() -> tuple[Adapter, ...]:
    from pdf_tooling.adapters import pdfium_raster

    return (pdfium_raster.ADAPTER,)


def probe() -> EngineReport:
    from pdf_tooling.adapters import pdfium_raster

    return build_report(
        PORT,
        adapter=pdfium_raster.ADAPTER.adapter_name,
        kind=KIND_PYTHON_PACKAGE,
        probe=pdfium_raster.ADAPTER.probe(),
    )


def require_raster(*, capability: str | None = None) -> RasterEngine:
    """The one way a verb demands the raster engine (X-76: selected by
    capability, never by adapter name)."""
    return cast("RasterEngine", require(PORT, capability=capability))
