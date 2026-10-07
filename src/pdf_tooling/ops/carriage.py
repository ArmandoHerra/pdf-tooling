"""PDF-108 -- say what a write drops: encryption and document metadata.

A PDF-writing verb that rebuilds or rewrites its operand does not always
carry everything the operand held. Thirteen verbs write a **plaintext**
output from an encrypted input. Since PDF-116 the nine page-rebuild verbs carry
the document's ``/Info`` and XMP packet (``merge``: the first input's only), so
what is still dropped is encryption and ``merge``'s later inputs' metadata. This
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
from pathlib import Path

from pdf_tooling.errors import DecryptedOutputRefusedError, PdfToolingError
from pdf_tooling.models import OperationResult
from pdf_tooling.ops.carriage_decl import (
    _UNDECLARED,
    CARRIAGE,
    Carriage,
    Drop,
    requires_decrypted_output_opt_in,
    undeclared,
)
from pdf_tooling.ops.pagerange import is_valid_spec
from pdf_tooling.ports.structure import CarriageFacts, require_encryption
from pdf_tooling.safety.paths import canonical, classify_operand, read_source_bytes

__all__ = [
    "CARRIAGE",
    "Carriage",
    "Drop",
    "amend",
    "carriage_warnings",
    "close_ledger",
    "dropped_info",
    "open_ledger",
    "record",
    "refuse_decrypted_output",
    "split_operand",
    "undeclared",
]

_LOG = logging.getLogger(__name__)

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
    """Whether a source holds any ``/Info`` content a dropping write would lose."""
    return bool(facts.info_keys)


def _drops(dimension: Drop, first: bool) -> bool:
    """``DROPS``, or ``FIRST`` for a source that is not the run's first (PDF-116 D6)."""
    return dimension is Drop.DROPS or (dimension is Drop.FIRST and not first)


def carriage_warnings(
    verb: str,
    label: str,
    facts: CarriageFacts,
    *,
    in_place: bool = False,
    first: bool = True,
) -> tuple[str, ...]:
    """The warnings for one source of one *verb*, in D2's exact (tense-neutral) text.

    *label* is the operand exactly as the item publishes it. W-ENC comes
    before W-META; at most one of each. A ``FIRST`` dimension counts as carried
    when *first* and as dropped otherwise.
    """
    declared = CARRIAGE.get(verb, _UNDECLARED)
    out: list[str] = []
    if declared.encryption is Drop.DROPS and facts.encrypted:
        text = f"{label}: input is encrypted; {verb} writes its output unencrypted"
        if in_place:
            text += " (--in-place: the encrypted input is replaced)"
        out.append(text)

    info_dropping = _drops(declared.info, first)
    xmp_dropping = _drops(declared.xmp, first)
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
    # `merge` publishes one item per argv input, in order (all ok or none), so
    # the first item's source is the donor whose metadata was carried.
    first_key = _source_key(ledger, result.items[0].input) if result.items else None
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
                result.verb,
                item.input,
                ledger.facts[key],
                in_place=output == item.input,
                first=key == first_key,
            )
        )
    if not extra:
        return result
    return dataclasses.replace(result, warnings=(*result.warnings, *extra))


# --------------------------------------------------------------------------- #
# Refusal: PDF-115's normative half (OR-26 / X-1001).
# --------------------------------------------------------------------------- #


def refuse_decrypted_output(verb: str, operands: Iterable[str]) -> None:
    """Refuse a decrypted output from an encrypted input, before anything is written.

    Called ONCE per run by the CLI wrapper, before the verb body. Credential-free
    (it never touches a password), and it adds no read of its own: the only read
    is :func:`record`'s, first-read-wins, which the verb's own seam then hits.
    Every operand is pre-checked with the existing :func:`classify_operand`
    ladder and a rejected one is skipped -- the verb's own ladder answers for it
    exactly as before -- so a FIFO or device is never opened here (PDF-107's lesson).

    Raises:
        DecryptedOutputRefusedError: Exit 5, naming EVERY encrypted operand as typed.
    """
    if not requires_decrypted_output_opt_in(verb):
        return
    ledger = _LEDGER.get()
    refused: list[str] = []
    first_path: str | None = None
    for text in operands:
        path_text, _ = split_operand(text)
        try:
            classify_operand(path_text)
        except PdfToolingError:
            continue
        source = Path(path_text)
        record(source)
        # By recorded SPELLING, so this adds no filesystem call of its own.
        key = None if ledger is None else ledger.spelled.get(str(source))
        facts = None if ledger is None or key is None else ledger.facts.get(key)
        if facts is not None and facts.encrypted:
            refused.append(text)
            if first_path is None:
                first_path = path_text
    if not refused:
        return
    count = len(refused)
    noun = "input is" if count == 1 else "inputs are"
    raise DecryptedOutputRefusedError(
        f"{verb} writes its output unencrypted, and {count} {noun} encrypted: "
        f"{', '.join(refused)}. Nothing was written. "
        "Pass --allow-decrypted-output to write a decrypted output anyway.",
        path=first_path,
    )
