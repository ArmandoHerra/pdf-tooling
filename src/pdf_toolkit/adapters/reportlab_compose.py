"""``ComposeEngine`` adapter — reportlab.

reportlab is the only ``ComposeEngine`` backend in v1 and needs no system
libraries, so ``pdftoolkit create`` works on a bare install. The WeasyPrint
adapter that would sit beside it is Phase 2 behind the ``[html]`` extra, and is
deliberately **not** created here — which is why ``doctor`` prints six rows and
not seven, and why ``EngineReport.kind``'s third value ``"optional-extra"`` is
declared but unused by any v1 row.

Composition itself arrives with the create spec; this is probe and version
reporting only.
"""

from __future__ import annotations

from typing import Final

from pdf_toolkit.adapters import AdapterProbe, package_probe

__all__ = ["ADAPTER", "ReportlabComposeAdapter"]

_NAME: Final[str] = "reportlab"
_DISTRIBUTION: Final[str] = "reportlab"
_MODULE: Final[str] = "reportlab"

_CAPABILITIES: Final[frozenset[str]] = frozenset({"compose", "text-layout", "vector"})


class ReportlabComposeAdapter:
    """The reportlab-backed ``ComposeEngine``."""

    kind: Final[str] = "python-package"

    @property
    def adapter_name(self) -> str:
        return _NAME

    def capabilities(self) -> frozenset[str]:
        return _CAPABILITIES

    def probe(self) -> AdapterProbe:
        return package_probe(_MODULE, _DISTRIBUTION)


ADAPTER: Final[ReportlabComposeAdapter] = ReportlabComposeAdapter()
