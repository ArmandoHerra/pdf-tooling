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

__all__ = ["OfficeConverter", "adapters", "office_binary_present", "probe", "require_office"]

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


def office_binary_present() -> bool:
    """Spawn-free presence check for ``soffice`` -- **PDF-15 / B-096.**

    Delegates to the adapter's own :func:`~pdf_toolkit.adapters.soffice_office.
    binary_present`, which is the same ``shutil.which`` short-circuit its
    ``probe()`` opens with, so a preview and ``doctor`` cannot disagree about
    whether the engine is there.

    This exists because :func:`require_office` is only spawn-free when the
    binary is ABSENT: with it present, resolution runs ``soffice --version``,
    which creates ``$HOME/.config``. A ``--dry-run`` preview must write nothing
    anywhere (``CLAUDE.md`` rule 2), so it asks THIS question -- the only one
    exit 3 turns on -- and demands the engine through :func:`require_office`
    only on the branch where doing so provably cannot spawn.
    """
    from pdf_toolkit.adapters import soffice_office

    return soffice_office.binary_present()


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
