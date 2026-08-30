"""The ``OfficeConverter`` port — convert office documents to PDF.

The second of the two ports whose engine can legitimately be absent: ``soffice``
is a system package. Absence is a row with ``available:false`` and an OS-aware
hint; a verb that needs it exits **3**.

Conversion itself arrives with the office spec; the Protocol here declares the
probe surface only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pdf_toolkit.models import EngineReport
from pdf_toolkit.ports import KIND_SYSTEM_BINARY, Adapter, build_report, require

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pdf_toolkit.adapters import AdapterProbe

__all__ = ["OfficeConverter", "adapters", "probe", "require_office"]

PORT = "OfficeConverter"


class OfficeConverter(Protocol):
    """Convert an office document to PDF."""

    @property
    def adapter_name(self) -> str: ...

    def capabilities(self) -> frozenset[str]: ...

    def probe(self) -> AdapterProbe: ...


def adapters() -> tuple[Adapter, ...]:
    from pdf_toolkit.adapters import soffice_office

    return (soffice_office.ADAPTER,)


def probe() -> EngineReport:
    from pdf_toolkit.adapters import soffice_office

    return build_report(
        PORT,
        adapter=soffice_office.ADAPTER.adapter_name,
        kind=KIND_SYSTEM_BINARY,
        probe=soffice_office.ADAPTER.probe(),
    )


def require_office(*, capability: str | None = None) -> Adapter:
    """The one way a verb demands the office converter."""
    return require(PORT, capability=capability)
