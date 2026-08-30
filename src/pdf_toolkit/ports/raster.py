"""The ``RasterEngine`` port — render pages to images.

One adapter: **pypdfium2**. Rendering itself arrives with the rasterize spec;
the Protocol here declares the probe surface only, because a stub for an
operation nobody implements yet is worse than its absence (see
``ports/__init__``'s docstring).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pdf_toolkit.models import EngineReport
from pdf_toolkit.ports import KIND_PYTHON_PACKAGE, Adapter, build_report, require

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pdf_toolkit.adapters import AdapterProbe

__all__ = ["RasterEngine", "adapters", "probe", "require_raster"]

PORT = "RasterEngine"


class RasterEngine(Protocol):
    """Render pages to raster images."""

    @property
    def adapter_name(self) -> str: ...

    def capabilities(self) -> frozenset[str]: ...

    def probe(self) -> AdapterProbe: ...


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


def require_raster(*, capability: str | None = None) -> Adapter:
    """The one way a verb demands the raster engine."""
    return require(PORT, capability=capability)
