"""``TextEngine`` primary adapter — pdfplumber (over pdfminer.six).

pdfplumber is the layout-aware primary: words, lines, and the table heuristics
the ``tables`` verb will expose. ``pdfium_text`` is the fast path beside it.
Both are MIT/BSD.

Extraction itself arrives with the text and tables specs; this is probe and
version reporting only.
"""

from __future__ import annotations

from typing import Final

from pdf_toolkit.adapters import AdapterProbe, package_probe

__all__ = ["ADAPTER", "PdfplumberTextAdapter"]

_NAME: Final[str] = "pdfplumber"
_DISTRIBUTION: Final[str] = "pdfplumber"
_MODULE: Final[str] = "pdfplumber"

_CAPABILITIES: Final[frozenset[str]] = frozenset({"text", "words", "layout", "tables"})


class PdfplumberTextAdapter:
    """The pdfplumber-backed ``TextEngine``."""

    kind: Final[str] = "python-package"

    @property
    def adapter_name(self) -> str:
        return _NAME

    def capabilities(self) -> frozenset[str]:
        return _CAPABILITIES

    def probe(self) -> AdapterProbe:
        return package_probe(_MODULE, _DISTRIBUTION)


ADAPTER: Final[PdfplumberTextAdapter] = PdfplumberTextAdapter()
