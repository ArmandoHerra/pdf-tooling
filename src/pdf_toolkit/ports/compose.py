"""The ``ComposeEngine`` port — build a PDF from images or text.

One adapter in v1: **reportlab**, which needs no system libraries so a bare
install can compose. WeasyPrint would be the second, behind the ``[html]``
extra, and is Phase 2 (D-05) — which is why ``doctor`` prints six rows and
``EngineReport.kind``'s ``"optional-extra"`` value has no v1 row.

PDF-05 left this file probe-and-version only. PDF-10 adds the port's first two
real operations, and one rule binds both of them:

**Every method renders into a caller-supplied binary stream, never a path.**
``PLAN.md`` §5.2 makes ``safety/`` the single write chokepoint and PDF-04 ships
an import-boundary test that fails on any write call outside it. A renderer
handed a *filename* opens it itself — a second, untracked descriptor, from
inside third-party code where a source-level AST walk cannot see it — which
bypasses the atomic-write, no-clobber and dry-run guarantees while passing
every static check. So the adapter renders into a buffer and the op hands the
bytes to :class:`~pdf_toolkit.safety.atomic.AtomicWriter`.

:meth:`ComposeEngine.render_text` exists now, in the shape the watermark/stamp
work needs, so that spec extends this port rather than redesigning it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING, Protocol, cast

from pdf_toolkit.models import EngineReport
from pdf_toolkit.ports import KIND_PYTHON_PACKAGE, Adapter, build_report, require

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from PIL.Image import Image

    from pdf_toolkit.adapters import AdapterProbe

__all__ = [
    "ComposeEngine",
    "ComposeReport",
    "ImagePlacement",
    "TextLayout",
    "adapters",
    "probe",
    "require_compose",
]

PORT = "ComposeEngine"


@dataclass(frozen=True, slots=True)
class ImagePlacement:
    """One image, one page: where it goes and how it must get there.

    Geometry is expressed entirely in **PDF points**, as placement — a page
    size, a destination box, and an optional clip. It is never expressed as a
    pixel operation, because resampling an image to fit a page would destroy
    the one guarantee this port exists to keep.
    """

    source: Path
    """The file on disk. On the passthrough path this is what the adapter hands
    the renderer, so the renderer still has the original compressed bytes."""

    raster: Image | None
    """Decoded pixels for the **re-encode** path, or ``None`` to signal
    passthrough. The decision belongs to the op (it sniffs the frame header);
    the renderer sniffs nothing and would otherwise pass everything through."""

    page_size: tuple[float, float]
    """``(width, height)`` of this image's own page, in points. Per page: a
    ``from-image`` compose of differently-sized scans yields differently-sized
    pages, never a normalised bounding box."""

    draw_box: tuple[float, float, float, float]
    """``(x, y, width, height)`` in points — where the image is drawn."""

    clip_box: tuple[float, float, float, float] | None
    """``(x, y, width, height)`` to clip to, or ``None``. Set only under
    ``--fit cover``, where the overflow is removed by a PDF clip path rather
    than by cropping pixels."""


@dataclass(frozen=True, slots=True)
class TextLayout:
    """Everything ``create`` decided before a glyph was measured.

    Line *wrapping* is deliberately not here: it needs font metrics, which live
    behind the engine. Everything that is pure geometry — the page, the margin,
    the leading, how many lines fit — is resolved by the op and passed in, so
    the page-count arithmetic is testable without an engine.
    """

    font: str
    size: float
    leading: float
    page_size: tuple[float, float]
    margin_pt: float
    lines_per_page: int
    title: str | None


@dataclass(frozen=True, slots=True)
class ComposeReport:
    """What a render actually produced, measured rather than predicted."""

    page_count: int


class ComposeEngine(Protocol):
    """Compose a PDF from non-PDF source material."""

    @property
    def adapter_name(self) -> str: ...

    def capabilities(self) -> frozenset[str]: ...

    def probe(self) -> AdapterProbe: ...

    def compose_images(self, items: Sequence[ImagePlacement], *, out: IO[bytes]) -> ComposeReport:
        """Render one page per placement into *out*.

        Args:
            items: The placements, in page order. An item whose ``raster`` is
                ``None`` must reach the renderer as its **path**, so the
                already-compressed bytes are stored verbatim.
            out: An open binary stream — an ``AtomicWriter.stream`` in
                production, a buffer in tests. Never a path: see the module
                docstring.

        Raises:
            TypeError: *out* is not a writable binary stream.
        """
        ...

    def render_text(self, text: str, *, layout: TextLayout, out: IO[bytes]) -> ComposeReport:
        """Render *text* into *out*, wrapped and paginated per *layout*.

        Args:
            text: Already normalised and already encodable in the font's
                encoding — the op owns both, so this method never silently
                drops a character.
            layout: The resolved page geometry and font selection.
            out: An open binary stream. Never a path.

        Raises:
            TypeError: *out* is not a writable binary stream.
        """
        ...


def adapters() -> tuple[Adapter, ...]:
    from pdf_toolkit.adapters import reportlab_compose

    return (reportlab_compose.ADAPTER,)


def probe() -> EngineReport:
    from pdf_toolkit.adapters import reportlab_compose

    return build_report(
        PORT,
        adapter=reportlab_compose.ADAPTER.adapter_name,
        kind=KIND_PYTHON_PACKAGE,
        probe=reportlab_compose.ADAPTER.probe(),
        extra_detail="HTML/Markdown composition is the [html] extra and is not part of v1",
    )


def require_compose(*, capability: str | None = None) -> ComposeEngine:
    """The one way a verb demands the compose engine (X-76: selected by
    capability, never by adapter name)."""
    return cast("ComposeEngine", require(PORT, capability=capability))
