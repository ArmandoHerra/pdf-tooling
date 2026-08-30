"""The ``OcrEngine`` port — optical character recognition.

One of the two ports whose engine can legitimately be absent: the ``tesseract``
binary is a system package, not a wheel. Absence is a row with
``available:false`` and an OS-aware hint, and a verb that needs it exits **3** —
never a traceback and never a degraded result (``PLAN.md`` §12 R-09).

``detail`` enumerates the tessdata languages actually installed. Multi-language
support is deferred (B-009); what is reported is what is there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pdf_toolkit.models import EngineReport
from pdf_toolkit.ports import KIND_SYSTEM_BINARY, Adapter, build_report, require

if TYPE_CHECKING:  # pragma: no cover - typing only
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


def require_ocr(*, capability: str | None = None) -> Adapter:
    """The one way a verb demands the OCR engine."""
    return require(PORT, capability=capability)
