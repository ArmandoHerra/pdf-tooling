"""``RasterEngine`` adapter — pypdfium2 (PDFium).

PDFium is Chromium's PDF renderer, BSD-3-Clause, shipped as a wheel with the
binary inside. It is the reason this product can rasterize at all without
reaching for any of the copyleft rasterizers ``PLAN.md`` §7.2 forbids, which is
the single hardest constraint in that section to satisfy. (Those binaries are
not named here: ``tests/test_cli_spine.py`` substring-scans every file under
``src/`` for them, so the authoritative list lives in ``PLAN.md`` §7.2 and in
``FORBIDDEN`` in ``tests/test_license_policy.py``.)

Rendering itself arrives with the rasterize spec. This adapter is probe and
version reporting only, deliberately: the port seam has to exist and be
observable through ``doctor`` before ten verbs are written against it, and every
method added here before its verb exists would be a stub nothing calls.

``pdfium_text`` is a second module over the same engine, backing ``TextEngine``'s
fast path. Two modules, one backend, two ports — which is why the eight adapter
modules cover only seven engines.
"""

from __future__ import annotations

from typing import Final

from pdf_toolkit.adapters import AdapterProbe, package_probe

__all__ = ["ADAPTER", "PdfiumRasterAdapter"]

_NAME: Final[str] = "pypdfium2"
_DISTRIBUTION: Final[str] = "pypdfium2"
_MODULE: Final[str] = "pypdfium2"

_CAPABILITIES: Final[frozenset[str]] = frozenset({"render", "page-size", "raster"})


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


ADAPTER: Final[PdfiumRasterAdapter] = PdfiumRasterAdapter()
