"""PDF-108 -- say what a write drops: encryption and document metadata.

A PDF-writing verb that rebuilds or rewrites its operand does not always
carry everything the operand held. Thirteen verbs write a **plaintext**
output from an encrypted input; nine of them also replace the document's
``/Info`` with the engine's own producer entry and drop its XMP packet. This
module is the DESCRIPTIVE half only: every such write says what it dropped,
in the existing ``warnings`` array and on stderr, and ``--dry-run`` says the
same thing word for word. Whether the product should carry or refuse is a
separate, normative decision this module does not make.

One central seam, three parts -- never one edit per verb (PDF-37's lesson):

* **Facts** (:func:`record`). A credential-free read of each source, taken at
  the PDF-37 per-source password seam *before* its early returns, first read
  wins -- which is what pins the pre-image under ``--in-place``. The read
  method takes no password at all, so this seam can never become a second
  consumer of the secret.
* **Declarations** (:data:`CARRIAGE`). What each verb carries, as data keyed
  by the verb name the envelope spells. A verb absent from the table is
  treated as dropping everything: a warning seam that fails toward silence is
  the defect this closes.
* **Application** (:func:`amend`). One function, installed by the CLI wrapper
  as the result hook ``output.emit_result`` applies, composing the warnings.

Import discipline (the verb registry walks imports statically): this
module must not reach ``safety.atomic`` (every verb would become mutating) or
``ports.ocr``/``ports.office`` (the engine-blind set would move).
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Iterable
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

from pdf_tooling.models import OperationResult
from pdf_tooling.ops.pagerange import is_valid_spec
from pdf_tooling.ports.structure import CarriageFacts, require_encryption
from pdf_tooling.safety.paths import canonical, read_source_bytes

__all__ = [
    "CARRIAGE",
    "REBUILD_PRODUCER",
    "Carriage",
    "Drop",
    "amend",
    "carriage_warnings",
    "close_ledger",
    "dropped_info",
    "open_ledger",
    "record",
    "split_operand",
    "undeclared",
]

_LOG = logging.getLogger(__name__)

#: The ``/Producer`` the page-rebuild engine writes into every output's
#: ``/Info`` (pypdf's ``PdfWriter`` default). A source whose ``/Info`` is only
#: this pair comes out identical, so it is not a drop. Pinned by a test that
#: asserts every REBUILD output's ``/Info`` is exactly this, so it cannot
#: drift silently.
REBUILD_PRODUCER: Final[str] = "pypdf"


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
    "stamp": _REBUILD,
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


def undeclared(verbs: Iterable[str]) -> set[str]:
    """The verbs in *verbs* the declaration table has no row for."""
    return {verb for verb in verbs if verb not in CARRIAGE}


# --------------------------------------------------------------------------- #
# Facts: the run-scoped ledger.
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class _Ledger:
    """One run's facts, keyed by canonical path, plus how each source was SPELLED.

    The spelling map exists so :func:`amend` (which runs after the write) can
    match an item's published ``input`` to its source by string, without a
    single further filesystem call: canonicalising at emit time would add
    metadata operations AFTER the work is done, which the read-seam sweep reads
    as a race window that no longer matters.
    """

    facts: dict[Path, CarriageFacts] = field(default_factory=dict)
    spelled: dict[str, Path] = field(default_factory=dict)


#: ``None`` outside a CLI invocation, so a direct ``ops`` call records nothing
#: and its result is unchanged.
_LEDGER: ContextVar[_Ledger | None] = ContextVar("pdf108_ledger", default=None)


def open_ledger() -> Token[_Ledger | None]:
    """Begin a run: an empty ledger. Pair with :func:`close_ledger`."""
    return _LEDGER.set(_Ledger())


def close_ledger(token: Token[_Ledger | None]) -> None:
    _LEDGER.reset(token)


def record(source: Path) -> None:
    """Record *source*'s carriage facts once, credential-free, first read wins.

    Called as the FIRST statement of the two PDF-37 per-source seams, so it
    runs before either returns early and before any write: the fact captured
    is the pre-image even under ``--in-place``. It never resolves or reads a
    password, and it never raises -- a non-PDF or damaged operand records
    nothing and the verb's own error path owns it.
    """
    ledger = _LEDGER.get()
    if ledger is None:
        return
    try:
        # The key derivation is INSIDE the try: `canonical` can raise on a source
        # it cannot key (an unknown `~user`, an embedded NUL), and a seam that
        # claims to never raise must hold that on every path, not on the read alone.
        key = canonical(source)
        if key in ledger.facts:
            ledger.spelled.setdefault(str(source), key)
            return
        ledger.facts[key] = require_encryption().read_carriage_facts(read_source_bytes(source))
        ledger.spelled.setdefault(str(source), key)
    except Exception as error:  # noqa: BLE001 - this seam must never raise
        _LOG.debug("carriage: no fact recorded for a source: %s", type(error).__name__)


# --------------------------------------------------------------------------- #
# Composition: declarations + facts -> warnings.
# --------------------------------------------------------------------------- #


def dropped_info(facts: CarriageFacts) -> bool:
    """Whether a rebuild would lose real ``/Info`` content from *facts*.

    The engine's own ``/Producer`` is discounted: a source whose ``/Info`` is
    exactly the pair the rebuild writes back is not losing anything.
    """
    if facts.info_keys is None:
        return False
    keys = set(facts.info_keys)
    if facts.producer == REBUILD_PRODUCER:
        keys.discard("/Producer")
    return bool(keys)


def carriage_warnings(
    verb: str, label: str, facts: CarriageFacts, *, in_place: bool = False
) -> tuple[str, ...]:
    """The warnings for one source of one *verb*, in D2's exact (tense-neutral) text.

    *label* is the operand exactly as the item publishes it. W-ENC comes
    before W-META; at most one of each.
    """
    declared = CARRIAGE.get(verb, _UNDECLARED)
    out: list[str] = []
    if declared.encryption is Drop.DROPS and facts.encrypted:
        text = f"{label}: input is encrypted; {verb} writes its output unencrypted"
        if in_place:
            text += " (--in-place: the encrypted input is replaced)"
        out.append(text)

    info_dropping = declared.info is Drop.DROPS
    xmp_dropping = declared.xmp is Drop.DROPS
    if not (info_dropping or xmp_dropping):
        return tuple(out)
    if not facts.readable:
        out.append(
            f"{label}: {verb} carries no document /Info or XMP metadata packet to its "
            "output; the input needs a password to read, so whether it has either "
            "was not checked"
        )
        return tuple(out)
    parts: list[str] = []
    if info_dropping and dropped_info(facts):
        parts.append("document /Info")
    if xmp_dropping and facts.has_xmp:
        parts.append("XMP metadata packet")
    if parts:
        out.append(
            f"{label}: {verb} does not carry the input's {' and '.join(parts)} to its output"
        )
    return tuple(out)


def _source_key(ledger: _Ledger, raw: str) -> Path | None:
    """The ledger key for an item's published ``input``, or ``None``.

    By recorded spelling first (no filesystem call), then by canonical path as
    a defence for a verb that publishes a different spelling of its operand.
    The one declared grammar lives here: ``merge``'s ``path:range`` operand
    spelling. ``ops.merge.split_input_spec`` cannot be imported (``merge``
    reaches the write chokepoint, which would make every verb mutating), so
    this applies the same last-colon rule over the page-range module's own
    ``is_valid_spec``; a test pins the two splitters to agree.
    """
    candidates = [raw]
    path_text, selection = split_operand(raw)
    if selection is not None:
        candidates.append(path_text)
    for text in candidates:
        key = ledger.spelled.get(text)
        if key is not None:
            return key
    for text in candidates:
        key = canonical(text)
        if key in ledger.facts:
            return key
    return None


def split_operand(raw: str) -> tuple[str, str | None]:
    """``merge``'s ``path:range`` split: the LAST colon, taken only when the
    text after it is a syntactically valid page-range spec."""
    last = raw.rfind(":")
    if last == -1:
        return raw, None
    tail = raw[last + 1 :]
    if not tail or not is_valid_spec(tail):
        return raw, None
    return raw[:last], tail


def amend(result: OperationResult) -> OperationResult:
    """Append this run's carriage warnings to *result* (the ``emit_result`` hook).

    Only items that wrote, or in a dry run would write, count (``ok`` with an
    output); a refused or failed item contributes nothing. One warning per
    source however many outputs it fed.
    """
    ledger = _LEDGER.get()
    if ledger is None or not ledger.facts:
        return result
    seen: set[Path] = set()
    extra: list[str] = []
    for item in result.items:
        output = item.output
        if item.ok is not True or output is None:
            continue
        key = _source_key(ledger, item.input)
        if key is None or key in seen:
            continue
        seen.add(key)
        extra.extend(
            carriage_warnings(
                result.verb, item.input, ledger.facts[key], in_place=output == item.input
            )
        )
    if not extra:
        return result
    return dataclasses.replace(result, warnings=(*result.warnings, *extra))
