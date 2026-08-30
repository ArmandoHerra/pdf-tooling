"""The ``TextEngine`` port — extract text and tables.

Two adapters, one row: **pdfplumber** is the layout-aware primary and
**pypdfium2** is the fast path, named in ``detail``. Which one a verb gets is a
capability question, never a name; the text and tables specs select on the
tokens each declares.

Extraction itself arrives with those specs; the Protocol here declares the probe
surface only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pdf_toolkit.models import EngineReport
from pdf_toolkit.ports import KIND_PYTHON_PACKAGE, Adapter, build_report, require

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pdf_toolkit.adapters import AdapterProbe

__all__ = ["TextEngine", "adapters", "probe", "require_text"]

PORT = "TextEngine"


class TextEngine(Protocol):
    """Extract text, words and tables from a document."""

    @property
    def adapter_name(self) -> str: ...

    def capabilities(self) -> frozenset[str]: ...

    def probe(self) -> AdapterProbe: ...


def adapters() -> tuple[Adapter, ...]:
    from pdf_toolkit.adapters import pdfium_text, pdfplumber_text

    return (pdfplumber_text.ADAPTER, pdfium_text.ADAPTER)


def probe() -> EngineReport:
    from pdf_toolkit.adapters import pdfium_text, pdfplumber_text

    primary = pdfplumber_text.ADAPTER.probe()
    secondary = pdfium_text.ADAPTER.probe()
    if secondary.available:
        detail = (
            f"secondary: {pdfium_text.ADAPTER.adapter_name} "
            f"{secondary.version or 'version unknown'} "
            f"({pdfium_text.CAPABILITY_SUMMARY})"
        )
    else:
        detail = (
            f"secondary: {pdfium_text.ADAPTER.adapter_name} unavailable "
            f"({pdfium_text.CAPABILITY_SUMMARY} is therefore unavailable)"
        )
    return build_report(
        PORT,
        adapter=pdfplumber_text.ADAPTER.adapter_name,
        kind=KIND_PYTHON_PACKAGE,
        probe=primary,
        extra_detail=detail,
    )


def require_text(*, capability: str | None = None) -> Adapter:
    """The one way a verb demands the text engine."""
    return require(PORT, capability=capability)
