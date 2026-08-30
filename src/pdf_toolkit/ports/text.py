"""The ``TextEngine`` port — extract text and tables.

Two adapters, one row: **pdfplumber** is the layout-aware primary and
**pypdfium2** is the fast path, named in ``detail``. Which one a verb gets is a
capability question, never a name; the text and tables specs select on the
tokens each declares.

PDF-05 shipped the probe surface only. **PDF-11 (`text` + `tables`) fills in the
extraction methods here, beside the probe surface** — ``ports/__init__``'s own
rule: a later spec adds its method to the same port file and never forks a
seventh port (`PLAN.md` D-04, the six-port seam is what keeps the licence claim
answerable by reading six files).

Why there are two Protocols and not one
---------------------------------------
The two adapters behind this port are deliberately unequal. pypdfium2 extracts
characters several times faster and knows nothing about layout, words or
tables; pdfplumber knows all three. A single Protocol demanding every method
would force one of them to ship a stub — which type-checks, satisfies the
Protocol, and then fails at runtime in front of a user, exactly the failure mode
``ports/__init__``'s rule forbids. So the operations split along the capability
line that already exists: :class:`TextEngine` is what *both* adapters do, and
:class:`LayoutTextEngine` is the strictly larger surface only the layout adapter
claims. This mirrors ``ports/structure.py``, which already carries several
Protocols in one file for the same reason.

Selection stays by capability, never by name (X-76): :func:`require_fast_text`
asks for ``fast-text``, :func:`require_layout_text` for ``layout``, and
:func:`require_tables` for ``tables``. Nothing above this file names an adapter.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from pdf_toolkit.models import EngineReport
from pdf_toolkit.ports import KIND_PYTHON_PACKAGE, Adapter, build_report, require

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pdf_toolkit.adapters import AdapterProbe

__all__ = [
    "ExtractedTable",
    "LayoutTextEngine",
    "TextEngine",
    "TextLine",
    "adapters",
    "probe",
    "require_fast_text",
    "require_layout_text",
    "require_tables",
    "require_text",
]

PORT = "TextEngine"

#: The capability tokens this port's consumers select on. Declared here rather
#: than spelled at each call site so a typo is one edit away from a red, not a
#: silent fall-through to the wrong adapter.
CAPABILITY_FAST: str = "fast-text"
CAPABILITY_LAYOUT: str = "layout"
CAPABILITY_TABLES: str = "tables"

#: The two table strategies `tables --strategy` selects between. ``lines`` keys
#: off ruling lines actually drawn in the content stream — evidence present in
#: the document — while ``text`` infers structure from whitespace alignment.
#: There is deliberately no ``auto``: a strategy that scores two heuristics
#: against each other is Phase 2 (`PLAN.md` §12 R-03), and an unknown value is
#: rejected rather than ignored.
TABLE_STRATEGIES: tuple[str, ...] = ("lines", "text")


@dataclass(frozen=True, slots=True)
class TextLine:
    """One extracted line of text with its bounding box, engine-side.

    Deliberately *not* :class:`~pdf_toolkit.models.TextBlock`: this is what an
    adapter can say about a line it found, in the engine's own coordinates and
    the engine's own order. Assigning the emitted index, imposing the ordering
    invariant and normalizing the text all happen above the port, in
    ``ops/textract.py``, so those guarantees hold whatever the engine did.

    ``x0``/``top``/``x1``/``bottom`` are PDF points from the page's **top-left**
    origin, ``top`` increasing downward.
    """

    text: str
    x0: float
    top: float
    x1: float
    bottom: float


@dataclass(frozen=True, slots=True)
class ExtractedTable:
    """One table an engine detected on one page, exactly as found.

    ``rows`` may contain ``None`` for a cell the engine found no text in. That
    is preserved rather than coerced: the distinction between "empty" and "the
    engine saw nothing here" is real, and flattening it at the port would make
    it unrecoverable for every consumer.
    """

    bbox: tuple[float, float, float, float]
    """``(x0, top, x1, bottom)``, top-left origin, in points."""

    rows: tuple[tuple[str | None, ...], ...]


class TextEngine(Protocol):
    """Extract text from a document. What **both** adapters do."""

    @property
    def adapter_name(self) -> str: ...

    def capabilities(self) -> frozenset[str]: ...

    def probe(self) -> AdapterProbe: ...

    def extract_text(self, path: str, page_numbers: Sequence[int]) -> tuple[str, ...]:
        """Every extractable character of each requested page.

        Args:
            path: The source PDF's path, as plain text — the adapter opens and
                closes its own document handle, exactly once for the whole
                request, and no engine object crosses this method's return.
            page_numbers: 1-based page numbers, in the order the caller wants
                results back.

        Returns:
            One string per requested page, in the requested order. A page that
            exists and yields nothing is the **empty string** — never ``None``,
            never a placeholder, never a fabricated line.

        Raises:
            FailureError: Exit 1 — the document could not be read. Never a
                fallback to another engine (`PLAN.md` §7.2).
        """
        ...


class LayoutTextEngine(TextEngine, Protocol):
    """The strictly larger surface the layout-aware adapter claims.

    Everything :class:`TextEngine` has, plus the two operations that need real
    layout analysis. An adapter that cannot do these does not implement this
    Protocol and is never selected for them, because selection goes through
    :func:`require_layout_text` / :func:`require_tables` and those ask for a
    capability token rather than a name.
    """

    def extract_lines(
        self, path: str, page_numbers: Sequence[int]
    ) -> tuple[tuple[TextLine, ...], ...]:
        """The text lines of each requested page, in the engine's own order.

        Returns:
            One tuple of :class:`TextLine` per requested page, in the requested
            order. A page with no extractable text is an **empty tuple**.
        """
        ...

    def extract_tables(
        self, path: str, page_numbers: Sequence[int], *, strategy: str
    ) -> tuple[tuple[ExtractedTable, ...], ...]:
        """The tables detected on each requested page under *strategy*.

        Table extraction is a **heuristic**, and this Protocol says so where a
        caller reads it: the engine reports what its geometry analysis found,
        and neither the engine nor this product attaches a confidence to that
        answer. Zero tables is a legitimate answer, not an error.

        Args:
            strategy: One of :data:`TABLE_STRATEGIES`. Validated by the caller;
                an adapter may assume it is one of those two.

        Returns:
            One tuple of :class:`ExtractedTable` per requested page, in the
            requested order.
        """
        ...


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


def require_text(*, capability: str | None = None) -> TextEngine:
    """The one way a verb demands the text engine.

    Exit 3 with the install hint when the port does not resolve, or when it
    resolves but no adapter behind it claims *capability* — never an
    ``ImportError`` traceback and never a silent downgrade to an adapter that
    would answer a different question.
    """
    return cast("TextEngine", require(PORT, capability=capability))


def require_fast_text() -> TextEngine:
    """The fast extraction path, selected by capability (X-76)."""
    return require_text(capability=CAPABILITY_FAST)


def require_layout_text() -> LayoutTextEngine:
    """The layout-aware path. **Never falls back to the fast path.**

    A fallback here would return fast-path output either mislabelled ``layout``
    (a lie) or correctly labelled ``fast`` while the user asked for ``layout``
    (a silent downgrade). Both are `PLAN.md` §12 R-03 violations, so this raises
    exit 3 instead.
    """
    return cast("LayoutTextEngine", require(PORT, capability=CAPABILITY_LAYOUT))


def require_tables() -> LayoutTextEngine:
    """The table-extraction path, selected by capability (X-76)."""
    return cast("LayoutTextEngine", require(PORT, capability=CAPABILITY_TABLES))
