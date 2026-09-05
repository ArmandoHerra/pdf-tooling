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

Why nothing here applies ``/Rotate`` (B-094)
--------------------------------------------
pdfium applies the page's own ``/Rotate`` **internally, twice over**, and both
halves are load-bearing here:

* ``PdfPage.get_size()`` is ``FPDF_GetPage{Width,Height}F``, which reports the
  **displayed** box — already swapped relative to the ``MediaBox`` for a 90/270
  page. Measured on pypdfium2 5.13.0 against a page whose ``MediaBox`` is
  ``[0 0 792 612]`` with ``/Rotate 90``: ``get_mediabox() == (0, 0, 792, 612)``
  while ``get_size() == (612.0, 792.0)``.
* ``PdfPage.render()`` honours ``/Rotate`` with no argument at all; its
  ``rotation=`` parameter is documented by pypdfium2 as *"**Additional**
  rotation in degrees"* and is applied **on top of** ``/Rotate``.

Until B-094 this module applied the rotation a second time in **both** places —
it re-swapped ``get_size()``'s already-displayed dimensions and passed
``rotation=page.get_rotation()`` into ``render()``. The two second applications
agreed with each other on the *dimensions*, which is why the crop below never
fired and why every size-and-aspect assertion in the suite stayed green while
the pixels were wrong.

The error was an **additional clockwise turn of ``/Rotate`` degrees**, so it was
90° at ``/Rotate 90``, **180° at ``/Rotate 180`` — it did not cancel** — and
270° at ``/Rotate 270``; only ``/Rotate 0`` was ever right. (The earlier reading
of "180° out at 90/270, cancels at 180" came from comparing image *sizes*, which
the second swap had already put back.) Measured on a 200×600 portrait page with
a black band on its top fifth: correct renders put the band top/right/bottom/left
at 0/90/180/270, and this module put it top/bottom/top/bottom. Downstream,
``ocr`` on a ``/Rotate 90`` page exited 0 and wrote an unreadable text layer.

The fix is not a compensating counter-rotation: it is to stop applying
``/Rotate`` here at all and let pdfium's single, internal application stand.
``tests/unit/test_raster.py`` asserts the band's edge as well as the size, at
all four angles, because either half alone is blind to some of this.

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
target — a real value's ``round()`` is provably never greater than its
``ceil()``, so this crop only ever removes at most one row/column of slack
that ceiling introduced and never truncates real content.

That proof holds for every rotation only because :func:`_displayed_size` and
pdfium's own bitmap sizing now read the *same* ``get_size()`` floats: target is
``round(displayed * scale)``, bitmap is ``ceil(displayed * scale)``. Before
B-094 the two were derived from different boxes and merely happened to agree.
The crop is therefore still a crop and never a pad — and :func:`_render`
now *asserts* that rather than trusting it, because a silent
:meth:`PIL.Image.Image.crop` past the edge pads with black, which is precisely
the shape of defect B-094 was: a wrong answer carrying a success exit code.

``pdfium_text`` is a second module over the same engine, backing ``TextEngine``'s
fast path. Two modules, one backend, two ports — which is why the eight adapter
modules cover only seven engines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from pdf_toolkit.adapters import AdapterProbe, package_probe
from pdf_toolkit.errors import AuthError, FailureError
from pdf_toolkit.ports.raster import RenderedPage
from pdf_toolkit.ports.structure import PASSWORD_HINT

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

#: How much slack pdfium's ``math.ceil()`` bitmap sizing may leave over this
#: module's own ``round()``-based target before the difference stops being a
#: rounding artefact and starts being a geometry defect. ``ceil(x) - round(x)``
#: is at most 1 for every real ``x``, so anything past this is the B-094 shape
#: — a mismatch the crop would paper over — and is refused rather than cropped.
_MAX_CEIL_SLACK_PX: Final[int] = 1


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
        password: str | None = None,
    ) -> RenderedPage:
        """Render one page. See the Protocol docstring in ``ports/raster.py``.

        The engine import is function-local (``adapters/__init__``'s rule 1):
        probing must never pay pdfium's import cost, and this method is the
        first thing in the product that actually does.

        Args:
            password: PDF-37 -- the REVEALED plaintext, or ``None``. Plain
                ``str``, not :class:`~pdf_toolkit.secret.Secret`: a
                ``Secret`` refuses to pickle (`secret.py`'s own
                ``__reduce__``) and `path` above is already documented as
                "plain text ... the caller may run this from a worker" for
                the identical reason (`rasterize`'s ``ProcessPoolExecutor``,
                Design §D5.3/§D5.5). The caller
                (`ops/document_password.py`) reveals it exactly once, only
                after confirming the document is actually encrypted, and
                only when the SAME secret already unlocked the primary
                `StructureEngine` read -- this method never resolves a
                password of its own.
        """
        import pypdfium2 as pdfium  # type: ignore[import-untyped]

        try:
            document = pdfium.PdfDocument(path, password=password)
        except pdfium.PdfiumError as error:
            if "password" not in str(error).lower():
                raise FailureError(f"{path}: could not be opened: {error}", path=path) from error
            if password is None:
                raise AuthError(
                    f"a password is required to rasterize this document; {PASSWORD_HINT}",
                    path=path,
                ) from error
            raise AuthError(
                f"the supplied password did not unlock this document; {PASSWORD_HINT}",
                path=path,
            ) from error
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


def _displayed_size(page: Any) -> tuple[float, float]:
    """The page's own ``(width_pt, height_pt)`` as it will be DISPLAYED — i.e.
    already swapped relative to the ``MediaBox`` when ``/Rotate`` is 90 or 270
    (Design §D6, AC8).

    That contract is unchanged by B-094; what changed is that this function no
    longer performs the swap **itself**. pdfium's ``get_size()`` is the
    displayed box already (module docstring, "Why nothing here applies
    ``/Rotate``"), so swapping it again produced the raw ``MediaBox`` back —
    the opposite of this function's own name. It deliberately does **not**
    match :class:`~pdf_toolkit.models.PageInfo`'s convention: ``PageInfo``
    reports the raw ``MediaBox`` with ``rotation`` beside it, and
    ``tesseract_ocr._normalize_layer_geometry`` reconstructs this displayed
    view from that pair — the two conventions are complementary, not equal,
    and the earlier docstring's claim that they agreed was the defect stated
    in prose."""
    width, height = page.get_size()
    return float(width), float(height)


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
    displayed_width, displayed_height = _displayed_size(page)
    target_width, target_height, dpi_effective = _target_dimensions(
        displayed_width, displayed_height, dpi=dpi, width_px=width_px
    )
    # The scale fed to pdfium: for DPI mode this is dpi/72 exactly (matching
    # what the module docstring's example measures); for width mode it is
    # sized so pdfium's own ceil() lands at or above target_width, which the
    # crop below then trims to exactly target_width.
    scale = dpi_effective / _POINTS_PER_INCH

    # NO `rotation=` argument. pdfium has already applied the page's own
    # `/Rotate`; passing it again is B-094. See the module docstring.
    bitmap = page.render(
        scale=scale,
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
        # the module docstring's "ceiling-vs-round correction". PIL's crop()
        # will happily extend past the edge and pad with black instead of
        # saying so, so the invariant is checked rather than assumed: a bitmap
        # that disagrees with the target by more than ceil()'s one pixel of
        # slack means the two are no longer derived from the same box, and
        # that is a geometry defect to surface, not slack to trim.
        slack_width = image.width - target_width
        slack_height = image.height - target_height
        if not (0 <= slack_width <= _MAX_CEIL_SLACK_PX and 0 <= slack_height <= _MAX_CEIL_SLACK_PX):
            raise FailureError(
                f"rendered bitmap {image.size} cannot be cropped to the "
                f"expected {(target_width, target_height)}: the renderer's page "
                "geometry disagrees with this adapter's"
            )
        image = image.crop((0, 0, target_width, target_height))
    return image, dpi_effective


ADAPTER: Final[PdfiumRasterAdapter] = PdfiumRasterAdapter()
