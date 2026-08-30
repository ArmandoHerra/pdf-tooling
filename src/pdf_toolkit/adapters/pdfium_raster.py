"""``RasterEngine`` adapter — pypdfium2 (PDFium).

PDFium is Chromium's PDF renderer, BSD-3-Clause, shipped as a wheel with the
binary inside. It is the reason this product can rasterize at all without
reaching for any of the copyleft rasterizers ``PLAN.md`` §7.2 forbids, which is
the single hardest constraint in that section to satisfy. (Those binaries are
not named here: ``tests/test_cli_spine.py`` substring-scans every file under
``src/`` for them, so the authoritative list lives in ``PLAN.md`` §7.2 and in
``FORBIDDEN`` in ``tests/test_license_policy.py``.)

PDF-05 shipped probe and version reporting only. PDF-09 (`rasterize`) fills in
the render path below — the only place in the product `page.render()` is
called, and the only file that ever holds a pdfium document or page handle.

Per-worker document handles, never shared (PLAN §12 R-08). :meth:`render_page`
opens its own document from a path, renders exactly one page, and closes the
document in a ``finally`` before returning — no pdfium object crosses this
method's return; only :class:`~pdf_toolkit.ports.raster.RenderedPage`'s plain
data does.

The ceiling-vs-round correction (why this file crops)
-------------------------------------------------------
pypdfium2's own ``PdfPage.render()`` computes its bitmap's pixel dimensions as
``math.ceil(page_points * scale)``. For a scale that is not exactly
representable as an IEEE-754 double — ``300/72`` is one; ``792 * (300/72)``
evaluates to ``3300.0000000000005``, not ``3300.0`` — that ceiling can produce
one pixel more than the mathematically exact ``page_pt/72*dpi`` this product
promises (Design §D3), independently of anything this file does. AC1 requires
**exactly** 2550×3300 for a US-Letter page at 300 dpi, so :func:`_render`
always crops the bitmap down to the independently-computed, round()-based
target — a real() value's ``round()`` is provably never greater than its
``ceil()``, so this crop only ever removes at most one row/column of slack
that ceiling introduced and never truncates real content.

``pdfium_text`` is a second module over the same engine, backing ``TextEngine``'s
fast path. Two modules, one backend, two ports — which is why the eight adapter
modules cover only seven engines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from pdf_toolkit.adapters import AdapterProbe, package_probe
from pdf_toolkit.errors import FailureError
from pdf_toolkit.ports.raster import RenderedPage

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

__all__ = ["ADAPTER", "PdfiumRasterAdapter"]

_NAME: Final[str] = "pypdfium2"
_DISTRIBUTION: Final[str] = "pypdfium2"
_MODULE: Final[str] = "pypdfium2"

_CAPABILITIES: Final[frozenset[str]] = frozenset({"render", "page-size", "raster"})

_POINTS_PER_INCH: Final[float] = 72.0

#: Opaque white, no transparency — Design §D6: a page is paper, and no format
#: this verb writes carries an alpha channel.
_FILL_WHITE: Final[tuple[int, int, int, int]] = (255, 255, 255, 255)

#: Page rotations pdfium's own ``PdfPage.render(rotation=...)`` accepts.
_ROTATIONS_SWAPPING_AXES: Final[frozenset[int]] = frozenset({90, 270})


class PdfiumRasterAdapter:
    """The PDFium-backed ``RasterEngine``."""

    kind: Final[str] = "python-package"

    @property
    def adapter_name(self) -> str:
        return _NAME

    def capabilities(self) -> frozenset[str]:
        return _CAPABILITIES

    def probe(self) -> AdapterProbe:
        return package_probe(_MODULE, _DISTRIBUTION)

    def render_page(
        self,
        path: str,
        page_number: int,
        *,
        dpi: float | None,
        width_px: int | None,
        grayscale: bool,
    ) -> RenderedPage:
        """Render one page. See the Protocol docstring in ``ports/raster.py``.

        The engine import is function-local (``adapters/__init__``'s rule 1):
        probing must never pay pdfium's import cost, and this method is the
        first thing in the product that actually does.
        """
        import pypdfium2 as pdfium  # type: ignore[import-untyped]

        document = pdfium.PdfDocument(path)
        try:
            try:
                page = document.get_page(page_number - 1)
            except pdfium.PdfiumError as error:
                raise FailureError(
                    f"{path}: page {page_number} could not be opened: {error}", path=path
                ) from error
            try:
                image, dpi_effective = _render(
                    page, dpi=dpi, width_px=width_px, grayscale=grayscale
                )
            except pdfium.PdfiumError as error:
                raise FailureError(
                    f"{path}: page {page_number} failed to render: {error}", path=path
                ) from error
            finally:
                page.close()
        finally:
            document.close()

        return RenderedPage(
            image=image,
            width_px=image.width,
            height_px=image.height,
            mode=image.mode,
            dpi_effective=dpi_effective,
        )


def _displayed_size(page: Any) -> tuple[float, float, int]:
    """The page's own ``(width_pt, height_pt)`` as it will be DISPLAYED, plus
    its declared rotation — i.e. swapped when ``/Rotate`` is 90 or 270
    (Design §D6, AC8). pdfium's ``get_size()`` always reports the raw,
    pre-rotation MediaBox, matching :class:`~pdf_toolkit.models.PageInfo`'s
    own convention."""
    raw_width, raw_height = page.get_size()
    rotation = page.get_rotation()
    if rotation in _ROTATIONS_SWAPPING_AXES:
        return raw_height, raw_width, rotation
    return raw_width, raw_height, rotation


def _target_dimensions(
    displayed_width: float,
    displayed_height: float,
    *,
    dpi: float | None,
    width_px: int | None,
) -> tuple[int, int, float]:
    """``(target_width_px, target_height_px, dpi_effective)`` — the exact,
    round()-based pixel size Design §D3 promises, computed independently of
    whatever pdfium's own ceil()-based bitmap size turns out to be."""
    if width_px is not None:
        target_width = width_px
        target_height = max(1, round(width_px * displayed_height / displayed_width))
        dpi_effective = width_px / displayed_width * _POINTS_PER_INCH
        return target_width, target_height, dpi_effective

    if dpi is None:  # pragma: no cover - caller guarantees exactly one of dpi/width_px is set
        raise ValueError("render_page requires exactly one of dpi or width_px")
    target_width = max(1, round(displayed_width * dpi / _POINTS_PER_INCH))
    target_height = max(1, round(displayed_height * dpi / _POINTS_PER_INCH))
    return target_width, target_height, dpi


def _render(
    page: Any, *, dpi: float | None, width_px: int | None, grayscale: bool
) -> tuple[Image, float]:
    displayed_width, displayed_height, rotation = _displayed_size(page)
    target_width, target_height, dpi_effective = _target_dimensions(
        displayed_width, displayed_height, dpi=dpi, width_px=width_px
    )
    # The scale fed to pdfium: for DPI mode this is dpi/72 exactly (matching
    # what the module docstring's example measures); for width mode it is
    # sized so pdfium's own ceil() lands at or above target_width, which the
    # crop below then trims to exactly target_width.
    scale = dpi_effective / _POINTS_PER_INCH

    bitmap = page.render(
        scale=scale,
        rotation=rotation,
        grayscale=grayscale,
        rev_byteorder=True,
        fill_color=_FILL_WHITE,
    )
    try:
        image = bitmap.to_pil()
    finally:
        bitmap.close()

    if image.size != (target_width, target_height):
        # Always a crop, never a pad: round(x) <= ceil(x) for every real x, so
        # pdfium's ceil()-based bitmap is never smaller than our target — see
        # the module docstring's "ceiling-vs-round correction".
        image = image.crop((0, 0, target_width, target_height))
    return image, dpi_effective


ADAPTER: Final[PdfiumRasterAdapter] = PdfiumRasterAdapter()
