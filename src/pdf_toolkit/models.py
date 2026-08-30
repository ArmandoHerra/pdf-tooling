"""The data model — stdlib frozen dataclasses, and the structured-output schema.

``SCHEMA_VERSION`` and every ``to_dict()`` below are PUBLIC API from v1.0.0.
``to_dict()`` is the *only* thing a renderer consumes, so a field rename cannot
silently change the published schema without touching a method a test pins.

This file is shared by several specs. Each model that a later spec owns has its
own named insertion anchor below; insert at your own anchor and nowhere else,
so two engineers editing this file concurrently cannot race on one line.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = [
    "SCHEMA_VERSION",
    "DocumentInfo",
    "EngineReport",
    "ItemResult",
    "OperationPlan",
    "OperationResult",
    "PageInfo",
    "PageRange",
]

#: Bumped only per the output stability policy: the ``-o json``/``ndjson``
#: shapes are a contract, and breaking one requires a major version bump.
SCHEMA_VERSION: Final[int] = 1


@dataclass(frozen=True, slots=True)
class PageRange:
    """Parsed page selection, resolved against a concrete page count.

    The *parser* for the page-range grammar is not in this file; it imports this
    class and must never redefine it.
    """

    spec: str
    """The original string, e.g. ``"1-3,last,!2"``."""

    indices: tuple[int, ...]
    """1-based, order-preserving; may contain duplicates for ordered verbs."""

    ordered: bool
    """True when order and duplicates are meaningful (extract/reorder)."""

    page_count: int
    """The document page count this selection was resolved against."""

    def as_set(self) -> frozenset[int]:
        """The selection with order and duplicates discarded."""
        return frozenset(self.indices)

    @property
    def is_empty(self) -> bool:
        """True when the selection resolved to zero pages.

        A property, never a field: an empty-but-valid selection is not an
        error (``PLAN.md`` §4.3), and this is how a verb tells the two apart
        without re-deriving it from ``indices`` at every call site.
        """
        return not self.indices

    def to_dict(self) -> dict[str, object]:
        return {
            "spec": self.spec,
            "indices": list(self.indices),
            "ordered": self.ordered,
            "page_count": self.page_count,
        }


# --- ANCHOR: PageInfo ------------------------------------------------------
# Reserved for the per-page report model. Insert the frozen ``PageInfo``
# dataclass directly below this anchor line and leave the anchor in place.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PageInfo:
    """One page, reduced to what a report can state without opening an engine twice.

    ``has_text`` is the field ``ocr --skip-text-pages`` will branch on, so it
    means *this page already carries extractable text*, not *this page looks
    like a scan*. The two differ on a page that is a scan with an OCR layer
    already applied, and the honest answer there is ``True``.
    """

    number: int
    """1-based, matching the page-range grammar rather than Python indexing."""

    width_pt: float
    height_pt: float
    """MediaBox dimensions in points, **before** ``rotation`` is applied — the
    rotation is reported beside them rather than folded into them, so a caller
    can reconstruct either convention and neither is silently assumed."""

    rotation: int
    """0, 90, 180 or 270."""

    has_text: bool
    image_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "width_pt": self.width_pt,
            "height_pt": self.height_pt,
            "rotation": self.rotation,
            "has_text": self.has_text,
            "image_count": self.image_count,
        }


# --- ANCHOR: DocumentInfo --------------------------------------------------
# Reserved for the document-level report model. Insert the frozen
# ``DocumentInfo`` dataclass directly below this anchor line and leave the
# anchor in place.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DocumentInfo:
    """Everything ``info`` reports about one document.

    ``fonts`` and ``pages`` are an **empty tuple** rather than ``None`` when the
    flag that populates them was not passed, so the JSON shape is identical
    across flag combinations and a consumer never has to distinguish "absent"
    from "empty". The cost of that choice is that emptiness alone does not tell
    you whether the flag was given; the payload carries the invocation, so it
    does not have to.
    """

    path: str
    size_bytes: int
    page_count: int

    pdf_version: str
    """The header version, e.g. ``"1.7"`` — the ``%PDF-`` prefix stripped."""

    encrypted: bool
    encryption_algorithm: str | None
    """``"AES-256"`` | ``"AES-128"`` | ``"RC4-128"`` | ``"RC4-40"``, or ``None``
    when the encryption dictionary is unrecognised. Never guessed."""

    permissions: tuple[str, ...]
    """Decoded permission tokens; an empty tuple when unknown or unencrypted."""

    linearized: bool
    has_signature: bool
    """Presence only. This product makes **no** signature-validity claim."""

    has_forms: bool
    metadata: dict[str, str]
    xmp: str | None
    fonts: tuple[str, ...]
    """``--fonts`` only. Names as they appear in ``/BaseFont``; no embedding or
    subset analysis is performed or implied."""

    pages: tuple[PageInfo, ...]
    """``--pages-detail`` only."""

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "page_count": self.page_count,
            "pdf_version": self.pdf_version,
            "encrypted": self.encrypted,
            "encryption_algorithm": self.encryption_algorithm,
            "permissions": list(self.permissions),
            "linearized": self.linearized,
            "has_signature": self.has_signature,
            "has_forms": self.has_forms,
            "metadata": dict(self.metadata),
            "xmp": self.xmp,
            "fonts": list(self.fonts),
            "pages": [page.to_dict() for page in self.pages],
        }


@dataclass(frozen=True, slots=True)
class OperationPlan:
    """Everything the CLI decided, before anything touches the filesystem.

    A verb is ``plan -> result``; ``--dry-run`` renders the plan and stops.
    """

    verb: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    """Fully resolved target paths."""

    page_range: PageRange | None
    options: dict[str, object]
    """Verb-specific and already validated."""

    safety: SafetyPolicy

    def to_dict(self) -> dict[str, object]:
        return {
            "verb": self.verb,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "page_range": self.page_range.to_dict() if self.page_range else None,
            "options": dict(self.options),
            "safety": self.safety.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ItemResult:
    """One unit of work inside a run.

    ``exit_code`` is per-item; the run's code is the highest severity across
    items.
    """

    input: str
    output: str | None
    ok: bool
    exit_code: int
    message: str | None
    bytes_before: int | None
    bytes_after: int | None
    duration_ms: int

    detail: Mapping[str, object] | None = None
    """Verb-specific per-item facts, or ``None``. **Omitted from
    :meth:`to_dict` entirely when ``None``**, so adding this field moved no
    existing verb's JSON by a byte — which is what PDF-06's ``info``/``doctor``
    goldens passing unmodified proves, rather than an inspection claiming it.

    The cycle-wide convention (``decision.md`` §8 X-26): *any verb needing
    per-item facts uses this field; nobody adds a second mechanism.* ``compose``
    reports ``embed``/``stream_bytes_identical``/``source_format``/``dpi_source``/
    ``page`` here; ``text``/``tables`` and ``compress``/``repair``/``linearize``
    are its next consumers.

    Declared **last**, with a default, because no other field on this frozen,
    slotted dataclass carries one — a non-default field after a defaulted one is
    a ``TypeError`` at import. Annotated ``Mapping`` rather than ``dict`` as a
    signpost, not a guarantee: ``frozen=True`` synthesizes ``__hash__``, and a
    mapping value is unhashable, so ``hash(ItemResult(detail={...}))`` raises.
    Nothing in this product hashes an ``ItemResult`` (verified: no ``set()``,
    ``frozenset()`` or ``hash()`` over items anywhere under ``src/``), so the
    constraint is latent rather than live. It is recorded here instead of being
    worked around with ``eq=False``, ``unsafe_hash`` or a custom ``__hash__`` —
    redesigning a shared model to suit one verb is the larger defect.
    """

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "input": self.input,
            "output": self.output,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "message": self.message,
            "bytes_before": self.bytes_before,
            "bytes_after": self.bytes_after,
            "duration_ms": self.duration_ms,
        }
        if self.detail is not None:
            payload["detail"] = dict(self.detail)
        return payload


@dataclass(frozen=True, slots=True)
class OperationResult:
    """The payload every verb returns and every renderer consumes."""

    schema_version: int
    verb: str
    dry_run: bool
    items: tuple[ItemResult, ...]
    warnings: tuple[str, ...]
    duration_ms: int

    @property
    def exit_code(self) -> int:
        """0 when every item is ok, otherwise the highest item code."""
        codes = [item.exit_code for item in self.items if not item.ok]
        return max(codes) if codes else 0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "verb": self.verb,
            "dry_run": self.dry_run,
            "items": [item.to_dict() for item in self.items],
            "warnings": list(self.warnings),
            "duration_ms": self.duration_ms,
            "exit_code": self.exit_code,
        }


# --- ANCHOR: EngineReport --------------------------------------------------
# Reserved for the engine-resolution report model (one row of ``doctor``).
# Insert the frozen ``EngineReport`` dataclass directly below this anchor line
# and leave the anchor in place.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EngineReport:
    """One row of ``doctor``; also what ``ports.require()`` consults.

    A row exists for every port on every run, available or not. A missing engine
    is ``available=False`` with a ``hint`` — never an absent row, because a
    consumer counting rows must get the same number whatever the host looks
    like.
    """

    port: str
    """``"StructureEngine"`` | ``"RasterEngine"`` | … — a **public contract**
    string that appears in ``doctor -o json``."""

    adapter: str | None
    available: bool
    version: str | None

    kind: str
    """``"python-package"`` | ``"system-binary"`` | ``"optional-extra"``."""

    detail: str | None
    """Free text: the secondary adapter and its version, the installed tessdata
    languages, or the raw version line when it did not parse."""

    hint: str | None
    """The OS-aware install command. ``None`` whenever ``available`` is true — a
    hint on a working engine is a defect, not a courtesy."""

    def to_dict(self) -> dict[str, object]:
        return {
            "port": self.port,
            "adapter": self.adapter,
            "available": self.available,
            "version": self.version,
            "kind": self.kind,
            "detail": self.detail,
            "hint": self.hint,
        }
