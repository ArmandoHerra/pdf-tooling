"""The ``RasterEngine`` port — render pages to images.

One adapter: **pypdfium2**. PDF-05 shipped the probe surface only, deliberately
(``ports/__init__``'s docstring: a stub for an operation nobody implements yet
is worse than its absence). PDF-09 (`rasterize`) is the first consumer of the
render method below, and PDF-15 (`ocr`) is its second — see :class:`RenderedPage`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from pdf_toolkit.models import EngineReport
from pdf_toolkit.ports import KIND_PYTHON_PACKAGE, Adapter, build_report, require

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

    from pdf_toolkit.adapters import AdapterProbe

__all__ = ["RasterEngine", "RenderedPage", "adapters", "probe", "require_raster"]

PORT = "RasterEngine"


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

        Raises:
            FailureError: Exit 1 — pypdfium2 could not render the page. Never
                a fallback to another engine (PLAN §7.2 / Design §D8).
        """
        ...


def adapters() -> tuple[Adapter, ...]:
    from pdf_toolkit.adapters import pdfium_raster

    return (pdfium_raster.ADAPTER,)


def probe() -> EngineReport:
    from pdf_toolkit.adapters import pdfium_raster

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
