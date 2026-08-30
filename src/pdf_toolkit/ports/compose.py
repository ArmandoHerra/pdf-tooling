"""The ``ComposeEngine`` port — build a PDF from text or markup.

One adapter in v1: **reportlab**, which needs no system libraries so a bare
install can compose. WeasyPrint would be the second, behind the ``[html]``
extra, and is Phase 2 (D-05) — which is why ``doctor`` prints six rows and
``EngineReport.kind``'s ``"optional-extra"`` value has no v1 row.

Composition itself arrives with the create spec; the Protocol here declares the
probe surface only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pdf_toolkit.models import EngineReport
from pdf_toolkit.ports import KIND_PYTHON_PACKAGE, Adapter, build_report, require

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pdf_toolkit.adapters import AdapterProbe

__all__ = ["ComposeEngine", "adapters", "probe", "require_compose"]

PORT = "ComposeEngine"


class ComposeEngine(Protocol):
    """Compose a PDF from non-PDF source material."""

    @property
    def adapter_name(self) -> str: ...

    def capabilities(self) -> frozenset[str]: ...

    def probe(self) -> AdapterProbe: ...


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


def require_compose(*, capability: str | None = None) -> Adapter:
    """The one way a verb demands the compose engine."""
    return require(PORT, capability=capability)
