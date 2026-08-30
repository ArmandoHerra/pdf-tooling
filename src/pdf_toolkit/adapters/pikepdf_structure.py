"""``StructureEngine`` secondary adapter — pikepdf (qpdf).

Selected **by capability, never by name** (D-04). ``pikepdf`` declares the
tokens the pypdf primary cannot honestly claim — ``linearized``, ``repair``,
``linearize``, ``object-streams``, ``robust-encryption`` — and a caller that
needs one asks the registry for the capability:

    ports.structure.require_structure(capability="linearized")

That is the whole adapter-selection seam, and it is deliberately the only one:
a verb that hard-coded "use pikepdf" would work, and would also make the choice
unauditable and impossible to redirect when the right backend changes.

``pikepdf`` bundles libqpdf under **MPL-2.0**, which ``PLAN.md`` §12 R-11
records as permitted and which the CI licence gate's ``AGPL|GPL|LGPL`` deny
pattern deliberately does not match. MPL-2.0 is file-level copyleft: obligations
attach to modified MPL files, and this product neither modifies nor vendors it.

``doctor`` still prints **six** rows. This adapter is named inside
``StructureEngine``'s ``detail``, never given a row of its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from pdf_toolkit.adapters import AdapterProbe, package_probe
from pdf_toolkit.output.logging import get_logger

__all__ = ["ADAPTER", "CAPABILITY_SUMMARY", "PikepdfStructureAdapter"]

_NAME: Final[str] = "pikepdf"
_DISTRIBUTION: Final[str] = "pikepdf"
_MODULE: Final[str] = "pikepdf"

_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {"linearized", "repair", "linearize", "object-streams", "robust-encryption"}
)

#: Rendered into ``StructureEngine``'s ``detail`` so ``doctor`` states what the
#: secondary is *for*, not merely that it exists.
CAPABILITY_SUMMARY: Final[str] = "repair, linearize, object-streams, encryption"


class PikepdfStructureAdapter:
    """The pikepdf-backed ``StructureEngine`` secondary."""

    kind: Final[str] = "python-package"

    @property
    def adapter_name(self) -> str:
        return _NAME

    def capabilities(self) -> frozenset[str]:
        return _CAPABILITIES

    def probe(self) -> AdapterProbe:
        return package_probe(_MODULE, _DISTRIBUTION)

    def is_linearized(self, path: Path) -> bool:
        """Whether *path* is linearized ("fast web view").

        A document this adapter cannot open is reported as **not linearized**
        rather than raising: ``info``'s authoritative read is the primary
        adapter's, and a secondary that could veto the whole report by failing
        on one optional field would make an optional field mandatory.
        """
        import pikepdf

        logger = get_logger("adapters.pikepdf")
        try:
            with pikepdf.Pdf.open(str(path)) as pdf:
                return bool(pdf.is_linearized)
        except pikepdf.PasswordError:
            logger.debug("%s: password-protected, reporting linearized=false", path)
            return False
        except (pikepdf.PdfError, OSError, ValueError) as error:
            logger.debug("%s: linearization unreadable (%s)", path, error)
            return False


# There is deliberately NO `read_document_info` here, and no stub raising
# `NotImplementedError`. The port-extension rule is that an adapter declares only
# what it really does: a later spec that needs pikepdf to perform a full read
# adds the working method beside `is_linearized`. A placeholder would type-check,
# satisfy the Protocol, and fail at runtime -- which is the whole failure mode the
# capability tokens exist to prevent.

ADAPTER: Final[PikepdfStructureAdapter] = PikepdfStructureAdapter()
