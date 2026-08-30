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
    "MetadataReport",
    "OperationPlan",
    "OperationResult",
    "PageInfo",
    "PageRange",
    "PageText",
    "TableGrid",
    "TextBlock",
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


# --- ANCHOR: PDF-11 text and table models ----------------------------------
# Appended by PDF-11 (`text` + `tables`), never inserted: `models.py` is shared
# with five sibling wave-5 specs, and an append can never move a line another
# engineer's diff is anchored on. The three models below are the payload shapes
# `ops/textract.py` produces and `cli/cmd_text.py` / `cli/cmd_tables.py`
# render. Each carries an explicit ``to_dict()`` (D-11) — the renderers consume
# nothing else.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TextBlock:
    """One text line of a ``text --layout`` page, with its bounding box.

    **Coordinate convention, stated on the model because "increasing ``y``" is
    meaningless without it:** ``x``/``y`` are the box's **top-left corner**, in
    PDF points, measured from the **page's top-left origin**, with ``y``
    increasing **downward** (pdfplumber's ``x0``/``top``). ``width``/``height``
    are the box's extent in points. The convention is chosen precisely so that
    *down the page* equals *increasing ``y``*.

    On a rotated page the coordinates are reported in the space the layout
    engine presents for that page. The tool does not re-map them and makes no
    claim to; the block **ordering** invariant is unaffected, because the
    ordering is imposed by a sort in ``ops/textract.py`` rather than inherited
    from the engine.

    There is deliberately **no** confidence, score or quality field here, or
    anywhere else in this spec's payloads (`PLAN.md` §12 R-03): a fabricated
    number is worse than no number, and a test greps for one.
    """

    index: int
    """0-based position in the page's emitted, sorted block list."""

    text: str
    x: float
    y: float
    width: float
    height: float

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "text": self.text,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class PageText:
    """One page of a ``text`` run, on either extraction path.

    ``blocks`` is ``None`` on the fast path and a tuple on the layout path, and
    :meth:`to_dict` emits ``text`` **xor** ``blocks`` accordingly — the shape
    `PLAN.md` §3's own documented ``jq '.pages[0].blocks | length'`` expression
    resolves against. ``text`` is carried on both paths regardless, because the
    file a destination-bearing run writes is the same text either way; it is the
    *payload* that differs, not what the tool extracted.

    ``char_count`` is present on both paths and is the length of the page's
    normalized text (on the layout path, the newline-joined block texts). A page
    that exists and yields nothing is ``char_count == 0`` with an empty
    ``text``/``blocks`` — an empty-but-valid result, never a fabricated string.
    """

    source: str
    page: int
    """1-based, matching the page-range grammar."""

    char_count: int
    text: str
    blocks: tuple[TextBlock, ...] | None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "source": self.source,
            "page": self.page,
            "char_count": self.char_count,
        }
        if self.blocks is None:
            payload["text"] = self.text
        else:
            payload["blocks"] = [block.to_dict() for block in self.blocks]
        return payload


@dataclass(frozen=True, slots=True)
class TableGrid:
    """One detected table, as found — no header row, no merged-cell repair.

    ``rows`` preserves the engine's own ``None`` for a cell it found no text in.
    JSON keeps that distinction; CSV cannot represent it and writes the empty
    string, which is a documented, one-directional loss rather than a hidden
    one.

    ``bbox`` is ``[x0, top, x1, bottom]`` in the same top-left-origin convention
    as :class:`TextBlock`. ``path`` is the artifact this grid was written to, or
    ``None`` when the run wrote no files.
    """

    source: str
    page: int
    index: int
    """0-based position among the tables detected on that page."""

    bbox: tuple[float, float, float, float]
    rows: tuple[tuple[str | None, ...], ...]
    path: str | None

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def col_count(self) -> int:
        """The widest row's width. Never inferred from a header, because this
        product does not claim to know which row is a header."""
        return max((len(row) for row in self.rows), default=0)

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "page": self.page,
            "index": self.index,
            "bbox": list(self.bbox),
            "row_count": self.row_count,
            "col_count": self.col_count,
            "rows": [list(row) for row in self.rows],
            "path": self.path,
        }


# --- ANCHOR: PDF-14 `meta get` model ---------------------------------------
# Appended by PDF-14 (`meta get`/`meta set`/`watermark`/`stamp`), never
# inserted at another spec's anchor -- same convention PDF-11 already used
# above: `models.py` is shared across the wave, and an append can never move
# a line another engineer's diff is anchored on. Scope's own Models row asks
# for exactly ONE new frozen dataclass here; every nested shape below
# (`disagreements`, `residual_surfaces`) stays a plain mapping assembled by
# `to_dict()` rather than a second dataclass -- mirroring `PageRange.to_dict()`'s
# own convention of never nesting a second dataclass inside a report model.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MetadataReport:
    """`meta get`'s payload -- both metadata halves, side by side, never
    merged (Design D2.1). `info` and `xmp` are reported independently and a
    disagreement between them is stated, never resolved.

    ``xmp``/``xmp_raw`` are ``None`` when the document carries no XMP packet
    at all -- not an empty dict/string, which would claim a packet with no
    fields. ``xmp_raw`` is populated only when the CLI's ``--xmp`` flag was
    given (D2.1's additive rule); the op decides that, not this model.
    """

    schema_version: int
    path: str

    info: Mapping[str, str]
    """Verbatim `/Info` keys, `/`-prefix stripped (e.g. ``"Title"``), every
    value already stringified -- the JSON report's own shape. Non-string
    `/Info` values (e.g. a `/Trapped` name object) are reported as their
    string form here; the WRITE side (`meta set`) preserves the original
    PdfObject type internally, which this read-only report has no need to
    carry back out."""

    xmp: Mapping[str, object] | None
    """Parsed XMP properties, keyed by the Design D2.1 alignment table's
    REPORT field names (``title``, ``author``, ``subject``, ``keywords``,
    ``creator``, ``producer``, ``creation_date``, ``mod_date``) -- lowercase,
    matching ``disagreements``' own ``"field"`` spelling, so the two never
    disagree about what to call the same property."""

    xmp_raw: str | None
    """The XMP packet, verbatim, only with ``--xmp``."""

    disagreements: tuple[Mapping[str, object], ...]
    """``{"field": ..., "info": ... | None, "xmp": ... | None}`` per
    disagreeing field (D2.1) -- a field present on one side only is a
    disagreement with ``None`` on the missing side."""

    residual_surfaces: Mapping[str, object]
    """D2.4's five facts, already keyed exactly as the report needs them:
    ``page_xmp_pages``, ``doc_piece_info``, ``page_piece_info_pages``,
    ``annotation_authors``, ``embedded_files``, ``trailer_id``."""

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "path": self.path,
            "info": dict(self.info),
            "xmp": dict(self.xmp) if self.xmp is not None else None,
            "xmp_raw": self.xmp_raw,
            "disagreements": [dict(item) for item in self.disagreements],
            "residual_surfaces": dict(self.residual_surfaces),
        }
