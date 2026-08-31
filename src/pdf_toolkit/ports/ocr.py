"""The ``OcrEngine`` port — optical character recognition.

One of the two ports whose engine can legitimately be absent: the ``tesseract``
binary is a system package, not a wheel. Absence is a row with
``available:false`` and an OS-aware hint, and a verb that needs it exits **3** —
never a traceback and never a degraded result (``PLAN.md`` §12 R-09).

``detail`` enumerates the tessdata languages actually installed. Multi-language
support is deferred (B-009); what is reported is what is there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

from pdf_toolkit.models import EngineReport
from pdf_toolkit.ports import KIND_SYSTEM_BINARY, Adapter, build_report, require

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

    from PIL.Image import Image

    from pdf_toolkit.adapters import AdapterProbe

__all__ = ["OcrEngine", "adapters", "probe", "require_ocr"]

PORT = "OcrEngine"


class OcrEngine(Protocol):
    """Recognise text in a rasterized page."""

    @property
    def adapter_name(self) -> str: ...

    def capabilities(self) -> frozenset[str]: ...

    def probe(self) -> AdapterProbe: ...

    def languages(self) -> tuple[str, ...]: ...

    # -- PDF-15 (`ocr`), appended at the end of the Protocol body ----------- #

    def text_layer(
        self,
        image: Image,
        *,
        lang: str,
        psm: int,
        dpi: float,
        page_width_pt: float,
        page_height_pt: float,
        rotation: int,
        timeout: float,
        scratch_dir: Path,
    ) -> bytes:
        """A one-page, text-only, invisible-render-mode PDF recognised from
        *image* (Design §D3) -- ``tesseract <input-image> <output-base> -l
        <lang> --psm <psm> --dpi <dpi-int> -c textonly_pdf=1 pdf``, spawned
        through ``subprocess_util.run`` (never ``pytesseract``'s own runner
        -- see the adapter's module docstring for why).

        *scratch_dir* is a caller-owned SCRATCH directory (``ops/ocr.py``
        opens it once per run through ``safety.atomic.ScratchDir`` and reuses
        it across every page -- Design §D2's sequential, one-page-at-a-time
        model) -- never a product destination. tesseract's CLI needs real
        file paths for both the input image and the output base; this is
        where they live, and this method's own file names inside it are
        reused (overwritten) across pages rather than made per-page-unique,
        so disk usage stays bounded regardless of page count.

        The returned page is normalised to *page_width_pt* x
        *page_height_pt* -- the ORIGINAL page's own **unrotated** ``MediaBox``
        dimensions (:attr:`~pdf_toolkit.models.PageInfo.width_pt` /
        ``height_pt``) -- with its content pre-rotated by the geometric
        inverse of *rotation* (Design §D4 route (a)): ``composite_layer``'s
        own ``page.merge_page`` performs a raw content-stream concatenation
        with no transform of its own, so the layer must already be correct
        in the page's own unrotated space before it crosses this port. *dpi*
        is passed to tesseract explicitly (``--dpi``) rather than left to the
        image's own metadata; the exact box tesseract emits is then measured
        back and rescaled (never assumed), so the 0.5 pt tolerance is a
        margin against float rounding only, not against tesseract's own
        rounding behaviour.

        Raises:
            FailureError: Exit 1 -- tesseract failed, produced no readable
                output, or the spawn timed out.
        """
        ...


def adapters() -> tuple[Adapter, ...]:
    from pdf_toolkit.adapters import tesseract_ocr

    return (tesseract_ocr.ADAPTER,)


def probe() -> EngineReport:
    from pdf_toolkit.adapters import tesseract_ocr

    adapter = tesseract_ocr.ADAPTER
    result = adapter.probe()
    binding = adapter.binding_probe()
    extra = None
    if not binding.available:
        extra = "the Python binding is missing, which is a broken installation"
    elif binding.version:
        extra = f"binding: pytesseract {binding.version}"
    return build_report(
        PORT,
        adapter=adapter.adapter_name,
        kind=KIND_SYSTEM_BINARY,
        probe=result,
        extra_detail=extra,
    )


def require_ocr(*, capability: str | None = None) -> OcrEngine:
    """The one way a verb demands the OCR engine.

    **AMENDED, PDF-15.** Narrowed to :class:`OcrEngine` (was bare
    :class:`~pdf_toolkit.ports.Adapter`, correct only while this port was
    probe-only) via ``cast``, mirroring ``ports/raster.py::require_raster``'s
    own established shape -- callers now need the operational
    :meth:`OcrEngine.text_layer` method this port exists to demand.
    """
    return cast("OcrEngine", require(PORT, capability=capability))
