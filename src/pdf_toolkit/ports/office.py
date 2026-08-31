"""The ``OfficeConverter`` port — convert office documents to PDF.

The second of the two ports whose engine can legitimately be absent: ``soffice``
is a system package. Absence is a row with ``available:false`` and an OS-aware
hint; a verb that needs it exits **3**.

Conversion itself arrives with the office spec; the Protocol here declares the
probe surface only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

from pdf_toolkit.models import EngineReport
from pdf_toolkit.ports import KIND_SYSTEM_BINARY, Adapter, build_report, require

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

    from pdf_toolkit.adapters import AdapterProbe

__all__ = ["OfficeConverter", "adapters", "probe", "require_office"]

PORT = "OfficeConverter"


class OfficeConverter(Protocol):
    """Convert an office document to PDF."""

    @property
    def adapter_name(self) -> str: ...

    def capabilities(self) -> frozenset[str]: ...

    def probe(self) -> AdapterProbe: ...

    # -- PDF-15 (`convert`), appended at the end of the Protocol body ------- #

    def convert_to_pdf(
        self,
        source: Path,
        *,
        scratch_dir: Path,
        filter_name: str | None,
        timeout: float,
    ) -> Path:
        """Convert *source* to PDF via headless LibreOffice, into a caller-
        owned SCRATCH directory (Design §D6) -- never a product destination.
        The caller (``ops/office.py``) opens *scratch_dir* through
        ``safety.atomic.ScratchDir`` and reads the returned path's bytes
        into ``AtomicWriter`` itself; this method never touches the write
        chokepoint and never chooses a user-visible destination.

        *scratch_dir* holds two isolated subdirectories this call creates
        under it (a fresh ``-env:UserInstallation`` profile per invocation,
        and the conversion ``--outdir``) -- LibreOffice creates both itself
        when they do not exist, so neither is pre-created here.

        Success is **"the expected output PDF exists and is non-empty"**,
        never the return code (D6): LibreOffice frequently exits 0 having
        converted nothing.

        Raises:
            FailureError: Exit 1 -- soffice failed, timed out, or exited 0
                without producing a non-empty PDF.
        """
        ...


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


def require_office(*, capability: str | None = None) -> OfficeConverter:
    """The one way a verb demands the office converter.

    **AMENDED, PDF-15.** Narrowed to :class:`OfficeConverter` (was bare
    :class:`~pdf_toolkit.ports.Adapter`, correct only while this port was
    probe-only) via ``cast``, mirroring ``ports/raster.py::require_raster``'s
    own established shape -- callers now need the operational
    :meth:`OfficeConverter.convert_to_pdf` method this port exists to
    demand.
    """
    return cast("OfficeConverter", require(PORT, capability=capability))
