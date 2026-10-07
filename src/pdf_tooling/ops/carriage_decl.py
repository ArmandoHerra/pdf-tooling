"""PDF-108/PDF-115 -- the carriage declaration DATA, stdlib-only.

What each verb carries, as data keyed by the verb name the envelope spells.
It lives apart from :mod:`pdf_tooling.ops.carriage` so the CLI can derive the
``--allow-decrypted-output`` flag from it at ``--help`` time without loading the
facts reader (PDF-108 AC17: ``--help`` never loads ``ops.carriage``). This module
imports nothing first-party; :mod:`pdf_tooling.ops.carriage` re-exports every
name so existing importers are unchanged.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "CARRIAGE",
    "Carriage",
    "Drop",
    "requires_decrypted_output_opt_in",
    "undeclared",
]


class Drop(StrEnum):
    """What one verb does with one dimension of its operand."""

    DROPS = "drops"
    CARRIES = "carries"
    PURPOSE = "purpose"
    """Changing it is the verb's whole job (``encrypt``/``decrypt``)."""
    NA = "n/a"


@dataclass(frozen=True, slots=True)
class Carriage:
    """One verb's declaration, with the reason it is not the default."""

    encryption: Drop
    info: Drop
    xmp: Drop
    reason: str
    sources: tuple[str, ...] = ()
    """Option PARAMETERS (not flag spellings) that name a secondary input document
    whose pages reach the output (``stamp``'s ``--from``, parameter ``from_``).
    PDF-115 X-1014(a): such a source is gated exactly like a positional operand."""


_REBUILD: Final[Carriage] = Carriage(
    Drop.DROPS,
    Drop.DROPS,
    Drop.DROPS,
    "rebuilds the document page by page through the page-rebuild engine",
)
_REWRITE: Final[Carriage] = Carriage(
    Drop.DROPS,
    Drop.CARRIES,
    Drop.CARRIES,
    "rewrites the document in place of structure; /Info and XMP survive, encryption does not",
)
_CRYPTO: Final[Carriage] = Carriage(
    Drop.PURPOSE,
    Drop.CARRIES,
    Drop.CARRIES,
    "changes encryption by design; /Info and XMP survive",
)


def _na(reason: str) -> Carriage:
    return Carriage(Drop.NA, Drop.NA, Drop.NA, reason)


_NO_PDF_OPERAND: Final[str] = "no PDF operand"
_NO_PDF_OUTPUT: Final[str] = "no PDF output"

#: The declaration table, keyed by the verb name the envelope's ``verb``
#: field spells (``"meta set"``, not ``meta_set``). Every leaf verb appears:
#: ``tests/integration/test_pdf108_carriage_warnings.py::test_ac12a_keys_equal_the_tree``
#: proves the key set equals the live command tree, and its
#: ``test_derived_writers_agree`` that the verbs writing a PDF from a PDF are
#: exactly the non-N/A rows.
CARRIAGE: Final[dict[str, Carriage]] = {
    # REBUILD: encryption, /Info and XMP all dropped.
    "rotate": _REBUILD,
    "extract": _REBUILD,
    "delete": _REBUILD,
    "reorder": _REBUILD,
    "merge": _REBUILD,
    "split": _REBUILD,
    "watermark": _REBUILD,
    "stamp": dataclasses.replace(_REBUILD, sources=("from_",)),
    "ocr": _REBUILD,
    # REWRITE: encryption dropped, /Info and XMP carried.
    "compress": _REWRITE,
    "repair": _REWRITE,
    "linearize": _REWRITE,
    "meta set": _REWRITE,
    # CRYPTO: excluded by purpose.
    "encrypt": _CRYPTO,
    "decrypt": _CRYPTO,
    # N/A: nothing to carry.
    "compose": _na(_NO_PDF_OPERAND),
    "create": _na(_NO_PDF_OPERAND),
    "convert": _na(_NO_PDF_OPERAND),
    "info": _na(_NO_PDF_OUTPUT),
    "text": _na(_NO_PDF_OUTPUT),
    "tables": _na(_NO_PDF_OUTPUT),
    "rasterize": _na(_NO_PDF_OUTPUT),
    "meta get": _na(_NO_PDF_OUTPUT),
    "permissions": _na(_NO_PDF_OUTPUT),
    "doctor": _na(_NO_PDF_OUTPUT),
    "version": _na(_NO_PDF_OUTPUT),
}

#: A verb the table does not know drops everything. Silence is the failure
#: this seam exists to prevent, so the default is the loud one.
_UNDECLARED: Final[Carriage] = Carriage(
    Drop.DROPS, Drop.DROPS, Drop.DROPS, "undeclared verb: assumed to drop everything"
)


def requires_decrypted_output_opt_in(verb: str) -> bool:
    """Whether *verb* needs ``--allow-decrypted-output`` (PDF-115 D1).

    Derived, fail-closed: true exactly when the verb's declared encryption is
    ``DROPS``, and an undeclared verb is treated as dropping everything.
    """
    return CARRIAGE.get(verb, _UNDECLARED).encryption is Drop.DROPS


def undeclared(verbs: Iterable[str]) -> set[str]:
    """The verbs in *verbs* the declaration table has no row for."""
    return {verb for verb in verbs if verb not in CARRIAGE}
