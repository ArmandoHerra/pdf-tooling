"""The ``StructureEngine`` port — read and rewrite a document's structure.

Two adapters sit behind this one port: **pypdf** (the primary, pure Python) and
**pikepdf** (the capability-selected secondary over qpdf). ``doctor`` prints one
row and names the secondary in its ``detail``; it never prints a seventh row.

At this point in the build order the Protocol declares the probe surface plus
exactly one operation — ``read_document_info``, which ``info`` calls. Later
specs add their methods **here**, beside it. See ``ports/__init__``'s docstring
for the rule and for why a stub is worse than an absence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, TYPE_CHECKING, Protocol, cast

from pdf_toolkit.models import DocumentInfo, EngineReport
from pdf_toolkit.ports import KIND_PYTHON_PACKAGE, Adapter, build_report, require

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pdf_toolkit.adapters import AdapterProbe

__all__ = [
    "LinearizationProbe",
    "OpenStructureDocument",
    "StructureEngine",
    "StructureWriter",
    "adapters",
    "probe",
    "require_linearization",
    "require_structure",
]

PORT = "StructureEngine"


class OpenStructureDocument(Protocol):
    """One already-open document handle -- the read half of D10 (PDF-07).

    Context-managed so a caller never has to remember to release whatever
    file handle the adapter opened; ``merge`` holds several of these open at
    once (one per input) via `contextlib.ExitStack`, which is exactly the
    shape a plain ``with`` cannot express for a variable-length input list.
    """

    @property
    def page_count(self) -> int: ...

    def top_level_outline(self) -> tuple[tuple[str, int], ...]:
        """``(title, 1-based destination page)`` per top-level entry, in
        outline order. Empty when the document has no outline at all."""
        ...

    def __enter__(self) -> OpenStructureDocument: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...


class StructureWriter(Protocol):
    """Accumulates selected pages, and optionally an outline, for one output.

    The write half of D10. Nothing here chooses a destination path (D7) --
    :meth:`write` is handed the stream ``AtomicWriter`` opened, never a path,
    so pypdf's own path-taking convenience can never bypass the chokepoint
    from inside a call an AST walk cannot see.
    """

    def append_pages(self, document: OpenStructureDocument, page_numbers: Sequence[int]) -> None:
        """Append *document*'s pages at the given 1-based numbers, in order,
        duplicates preserved -- the order-sensitive semantics `merge`'s
        per-input selection and `split`'s parts both need."""
        ...

    def add_outline_entry(self, title: str, page_number: int) -> None:
        """Append one top-level outline entry pointing at the 1-based
        destination page **in this writer's own output**, not the source."""
        ...

    def import_outline(
        self, document: OpenStructureDocument, *, page_map: Mapping[int, int]
    ) -> None:
        """Carry *document*'s own top-level outline across, remapped.

        ``page_map`` is SOURCE 1-based page number -> DESTINATION 1-based page
        number for pages that were selected. An entry whose source page is
        absent from ``page_map`` is dropped -- never retargeted to a
        neighbouring page, which would silently lie about the document
        (Design §D3, `--bookmarks preserve`).
        """
        ...

    def write(self, stream: IO[bytes]) -> None:
        """Serialize everything accumulated so far into *stream*."""
        ...


class StructureEngine(Protocol):
    """Read a document's structure. Implemented in full by the primary adapter."""

    @property
    def adapter_name(self) -> str: ...

    def capabilities(self) -> frozenset[str]: ...

    def probe(self) -> AdapterProbe: ...

    def read_document_info(
        self,
        path: Path,
        *,
        fonts: bool = ...,
        pages: bool = ...,
        linearized: bool = ...,
    ) -> DocumentInfo: ...

    def open_document(self, path: Path) -> OpenStructureDocument:
        """Open *path* for structural reading -- page count and outline.

        Raises:
            NoInputError: Exit 4 -- the path does not exist.
            FailureError: Exit 1 -- malformed, corrupt or unparseable.
            AuthError: Exit 6 -- a user password is required and none was
                supplied.
        """
        ...

    def new_writer(self) -> StructureWriter:
        """A fresh, empty :class:`StructureWriter` for one output."""
        ...


class LinearizationProbe(Protocol):
    """The shape an adapter must have to claim the ``linearized`` capability.

    Not a parallel interface: the port is still ``StructureEngine``. This is what
    a *capability token* means expressed as a type, so the one call site that
    selects on ``linearized`` is checked rather than cast blindly. A capability
    an adapter can declare but whose shape nothing pins is a capability that
    starts drifting on the second adapter that declares it.
    """

    def is_linearized(self, path: Path) -> bool: ...


def adapters() -> tuple[Adapter, ...]:
    """Primary first, then the capability-selected secondary."""
    from pdf_toolkit.adapters import pikepdf_structure, pypdf_structure

    return (pypdf_structure.ADAPTER, pikepdf_structure.ADAPTER)


def probe() -> EngineReport:
    from pdf_toolkit.adapters import pikepdf_structure, pypdf_structure

    primary = pypdf_structure.ADAPTER.probe()
    secondary = pikepdf_structure.ADAPTER.probe()
    if secondary.available:
        detail = (
            f"secondary: {pikepdf_structure.ADAPTER.adapter_name} "
            f"{secondary.version or 'version unknown'} "
            f"({pikepdf_structure.CAPABILITY_SUMMARY})"
        )
    else:
        detail = (
            f"secondary: {pikepdf_structure.ADAPTER.adapter_name} unavailable "
            f"({pikepdf_structure.CAPABILITY_SUMMARY} are therefore unavailable)"
        )
    return build_report(
        PORT,
        adapter=pypdf_structure.ADAPTER.adapter_name,
        kind=KIND_PYTHON_PACKAGE,
        probe=primary,
        extra_detail=detail,
    )


def require_structure(*, capability: str | None = None) -> StructureEngine:
    """The one way a verb demands the structure engine.

    Delegates to ``ports.require`` — the exit-3 chokepoint — and narrows the
    result. The registry is keyed by *string* because the port names are public
    API, so exactly one narrowing lives here, next to the Protocol it narrows
    to, rather than at every call site.
    """
    return cast("StructureEngine", require(PORT, capability=capability))


def require_linearization() -> LinearizationProbe:
    """The adapter that can answer ``linearized``, selected by capability."""
    return cast("LinearizationProbe", require(PORT, capability="linearized"))
