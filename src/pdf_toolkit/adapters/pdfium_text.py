"""``TextEngine`` secondary adapter — pypdfium2's text extraction fast path.

The same engine as ``pdfium_raster``, a different port. PDFium extracts text
several times faster than the pdfplumber primary and knows nothing about layout,
words or tables, so it is the right answer for "give me the characters" and the
wrong one for "give me the columns". Which is exactly why both exist behind one
port, selected by capability rather than by a guess at call time.

Extraction itself arrives with the text spec; this is probe and version
reporting only.
"""

from __future__ import annotations

from typing import Final

from pdf_toolkit.adapters import AdapterProbe, package_probe

__all__ = ["ADAPTER", "CAPABILITY_SUMMARY", "PdfiumTextAdapter"]

_NAME: Final[str] = "pypdfium2"
_DISTRIBUTION: Final[str] = "pypdfium2"
_MODULE: Final[str] = "pypdfium2"

_CAPABILITIES: Final[frozenset[str]] = frozenset({"text", "fast-text"})

#: Rendered into ``TextEngine``'s ``detail``.
CAPABILITY_SUMMARY: Final[str] = "fast text extraction, no layout analysis"


class PdfiumTextAdapter:
    """The PDFium-backed ``TextEngine`` fast path."""

    kind: Final[str] = "python-package"

    @property
    def adapter_name(self) -> str:
        return _NAME

    def capabilities(self) -> frozenset[str]:
        return _CAPABILITIES

    def probe(self) -> AdapterProbe:
        return package_probe(_MODULE, _DISTRIBUTION)


ADAPTER: Final[PdfiumTextAdapter] = PdfiumTextAdapter()
