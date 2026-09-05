"""The ``StructureEngine`` port — read and rewrite a document's structure.

Two adapters sit behind this one port: **pypdf** (the primary, pure Python) and
**pikepdf** (the capability-selected secondary over qpdf). ``doctor`` prints one
row and names the secondary in its ``detail``; it never prints a seventh row.

At this point in the build order the Protocol declares the probe surface plus
one operation — ``read_document_info``, which ``info`` calls. Later specs add
their methods **here**, beside it. See ``ports/__init__``'s docstring for the
rule and for why a stub is worse than an absence.

**PDF-12 (`compress`/`repair`/`linearize`) adds three methods to
``StructureEngine`` — ``compress``, ``repair``, ``linearize`` — plus the
plain-data outcome shapes those signatures need (``StructuralFacts``,
``ImageXObjectFacts``, ``CompressOutcome``, ``RepairOutcome``). Nothing here
crosses back into ``ops/optimize.py`` as an engine object — the shapes are
stdlib dataclasses, exactly like ``ports/text.py``'s ``ExtractedTable`` /
``TextLine`` precedent, so ``ops/`` never needs to import ``pikepdf``.

The Pillow/pypdf **image pass** `compress --images` needs is a *separate*
capability-selected narrowing, ``ImagePassEngine`` — mirroring
``LinearizationProbe``'s own shape exactly — rather than a fourth method on
``StructureEngine`` itself: the pikepdf-backed adapter never performs it (D-04
picks the pikepdf adapter for `compress` by the `"object-streams"`
capability; the image pass is pypdf's own `"image-pass"` capability), and
folding two adapters' work into one Protocol method would blur exactly the
one-operation-one-adapter mapping the licence question depends on.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING, Final, Protocol, cast

from pdf_toolkit.models import DocumentInfo, EngineReport
from pdf_toolkit.ports import KIND_PYTHON_PACKAGE, Adapter, build_report, require
from pdf_toolkit.secret import Secret

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pdf_toolkit.adapters import AdapterProbe

__all__ = [
    "ALWAYS_GRANTED_TOKENS",
    "ENCRYPTION_ALGORITHMS",
    "PASSWORD_HINT",
    "PERMISSION_TOKENS",
    "PERMISSION_TOKEN_MAP",
    "CompositeOutcome",
    "CompressOutcome",
    "EncryptionFacts",
    "ImagePassEngine",
    "ImagePassOutcome",
    "ImageXObjectFacts",
    "LinearizationProbe",
    "MetadataFacts",
    "MetadataWriteOutcome",
    "OpenStructureDocument",
    "RepairOutcome",
    "StructuralFacts",
    "StructureEngine",
    "StructureWriter",
    "adapters",
    "probe",
    "algorithm_name",
    "require_composite",
    "require_encryption",
    "require_image_pass",
    "require_linearization",
    "require_structure",
]

PORT = "StructureEngine"


class OpenStructureDocument(Protocol):
    """One already-open document handle -- the read half of D10 (PDF-07).

    Context-managed so a caller never has to remember to release whatever
    file handle the adapter opened; ``merge`` holds several of these open at
    once (one per input) via `contextlib.ExitStack`, which is exactly the
    shape a plain ``with`` cannot express for a variable-length input list.
    """

    @property
    def page_count(self) -> int: ...

    def top_level_outline(self) -> tuple[tuple[str, int], ...]:
        """``(title, 1-based destination page)`` per top-level entry, in
        outline order. Empty when the document has no outline at all."""
        ...

    def __enter__(self) -> OpenStructureDocument: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...


class StructureWriter(Protocol):
    """Accumulates selected pages, and optionally an outline, for one output.

    The write half of D10. Nothing here chooses a destination path (D7) --
    :meth:`write` is handed the stream ``AtomicWriter`` opened, never a path,
    so pypdf's own path-taking convenience can never bypass the chokepoint
    from inside a call an AST walk cannot see.
    """

    def append_pages(self, document: OpenStructureDocument, page_numbers: Sequence[int]) -> None:
        """Append *document*'s pages at the given 1-based numbers, in order,
        duplicates preserved -- the order-sensitive semantics `merge`'s
        per-input selection and `split`'s parts both need."""
        ...

    def add_outline_entry(self, title: str, page_number: int) -> None:
        """Append one top-level outline entry pointing at the 1-based
        destination page **in this writer's own output**, not the source."""
        ...

    def import_outline(
        self, document: OpenStructureDocument, *, page_map: Mapping[int, int]
    ) -> None:
        """Carry *document*'s own top-level outline across, remapped.

        ``page_map`` is SOURCE 1-based page number -> DESTINATION 1-based page
        number for pages that were selected. An entry whose source page is
        absent from ``page_map`` is dropped -- never retargeted to a
        neighbouring page, which would silently lie about the document
        (Design §D3, `--bookmarks preserve`).
        """
        ...

    def write(self, stream: IO[bytes]) -> None:
        """Serialize everything accumulated so far into *stream*."""
        ...

    # -- PDF-08 (`rotate`), appended at the end of the Protocol body -------- #

    def set_rotation(self, index: int, degrees: int) -> None:
        """Stamp ``/Rotate`` on one already-appended page.

        ``index`` is **0-based within this writer's own appended sequence**,
        not a source page number; ``degrees`` is the final **absolute** value,
        already normalized into ``{0, 90, 180, 270}`` by the CALLER.

        This is deliberately the narrowest possible seam, and all three of its
        properties are consequences of that narrowness:

        * **All arithmetic stays in the framework-free ops layer.**
          Relative-vs-``--absolute``, the ``% 360`` normalization and reading
          the page's current value all happen in ``ops/pages.py``; an adapter
          does exactly one thing — stamp the value it was handed. So `rotate`'s
          rules stay testable at unit level with no engine present.
        * **No new read method is needed.** The current value comes from the
          existing ``read_document_info(path, pages=True)`` ->
          ``PageInfo.rotation``, which the primary adapter already normalizes.
        * **Absent stays absent.** The caller calls this only for the pages the
          selection names, so every unnamed page keeps whatever
          :meth:`append_pages` copied across — including an *absent*
          ``/Rotate`` key. Writing an explicit ``/Rotate 0`` onto untouched
          pages would preserve rendering while failing the "changes only page
          1" guarantee.
        """
        ...


# --------------------------------------------------------------------------- #
# PDF-12 — plain-data shapes crossing the port boundary for `compress`/`repair`.
# Stdlib dataclasses only, mirroring `ports/text.py`'s `ExtractedTable`/
# `TextLine` precedent, so a caller in `ops/optimize.py` never has to hold a
# `pikepdf.Object` to build the D-12.3 lossless-verification message.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ImageXObjectFacts:
    """One image XObject's structural facts — decode-free, cheap to compare.

    ``dct_sha256`` is populated only when ``"/DCTDecode"`` is among
    ``filters``; it is the raw, undecoded stream digest, never a pixel hash
    (`recompress_flate=True` legitimately rewrites Flate streams to different
    bytes with identical pixels, so a digest over every filter would
    false-fail; qpdf never recompresses `/DCTDecode`, so raw-byte identity
    there is exact — D-12.3).
    """

    filters: tuple[str, ...]
    width: int
    height: int
    colorspace: str | None
    bits_per_component: int | None
    dct_sha256: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "filters": list(self.filters),
            "width": self.width,
            "height": self.height,
            "colorspace": self.colorspace,
            "bits_per_component": self.bits_per_component,
            "dct_sha256": self.dct_sha256,
        }


@dataclass(frozen=True, slots=True)
class StructuralFacts:
    """A document's page count plus every image XObject's facts, page order.

    Equality of two ``StructuralFacts`` is exactly D-12.3 Layer 1's three
    checks combined: page count identical, image XObject *count* identical
    (the tuples are the same length), and every image's own tuple identical
    (which folds in the ``/DCTDecode`` raw-byte check via ``dct_sha256``).
    """

    page_count: int
    images: tuple[ImageXObjectFacts, ...]


@dataclass(frozen=True, slots=True)
class CompressOutcome:
    """One `compress` structural pass: the candidate bytes plus the facts of
    both sides of the transformation, so `ops/optimize.py` can run D-12.3's
    Layer 1 gate — enforced there, per the design — without ever holding a
    `pikepdf.Pdf`."""

    output: bytes
    before: StructuralFacts
    after: StructuralFacts


@dataclass(frozen=True, slots=True)
class RepairOutcome:
    """One `repair` run: recovered bytes plus the honest structural delta
    (D-12.4). ``warnings`` are libqpdf's own recovery findings, cleaned of the
    unstable ``stream <object at 0x...>`` prefix `Pdf.get_warnings()` attaches
    — never fabricated, and empty when nothing was wrong."""

    output: bytes
    warnings: tuple[str, ...]
    page_count_before: int
    page_count_after: int
    object_count_before: int
    object_count_after: int
    xref_reconstructed: bool


@dataclass(frozen=True, slots=True)
class ImagePassOutcome:
    """One `compress --images` pre-pass: the transformed bytes, plus counts
    the caller reports honestly rather than silently (D-12.2's skip rule)."""

    output: bytes
    images_transformed: int
    images_skipped: int


# --------------------------------------------------------------------------- #
# PDF-14 -- `meta get`/`meta set`'s plain-data shapes (Design D2), and
# `watermark`/`stamp`'s compositing outcome (Design D4.1). Every one of these
# crosses the port as a stdlib dataclass, mirroring the PDF-12 shapes just
# above: `ops/metadata.py` never holds an `XmpInformation`, and
# `ops/overlay.py` never holds a `pypdf.PageObject`.
#
# **Deviation from the spec's own Scope > Ports row, recorded here rather
# than silently exceeded:** that row names exactly two new port methods
# (`ComposeEngine.render_text_layer` and `StructureEngine.composite_layer`).
# `meta get`/`meta set` need their OWN two new `StructureEngine` methods too
# (`read_metadata`/`write_metadata`, below) -- there is no existing method
# that can report XMP-property-level facts or residual-surface facts without
# either widening the ALREADY-PUBLISHED `DocumentInfo`/`read_document_info`
# shape (a breaking change to a pinned, golden-tested model) or letting
# `ops/metadata.py` hold a pypdf object (forbidden by the import-boundary
# test). The "two new methods" count in the spec's Scope table is therefore
# an undercount by two; see the Implementation Log.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class MetadataFacts:
    """One document's `/Info` + XMP + residual-surface facts (D2), read
    without a write. A plain dataclass like every other shape crossing this
    port -- `ops/metadata.py` never holds an `XmpInformation` or a pypdf
    `DictionaryObject`.
    """

    info: Mapping[str, str]
    """`/Info` entries, `/`-prefix stripped, every value already
    stringified -- D2.1's `info: {...}` JSON shape needs nothing richer. A
    non-string original value (e.g. a `/Trapped` name object) is reported as
    its string form; its ORIGINAL PdfObject type is preserved on the WRITE
    side (D2.3) and never needs to cross back out of a read-only report."""

    xmp: Mapping[str, object] | None
    """Parsed XMP properties, keyed by the D2.1 alignment table's REPORT
    field names (``title``, ``author``, ``subject``, ``keywords``,
    ``creator``, ``producer``, ``creation_date``, ``mod_date``). ``None``
    when the document carries no XMP packet at all."""

    xmp_raw: str | None
    """The XMP packet, verbatim, or ``None``. Always populated when a packet
    exists -- `--xmp`'s additive behaviour (D2.1) is an `ops/`-level decision
    about what to INCLUDE in the rendered report, not a reason to withhold
    the bytes at the port."""

    residual_surfaces: Mapping[str, object]
    """D2.4's five facts, already keyed exactly as the report needs them:
    ``page_xmp_pages``, ``doc_piece_info``, ``page_piece_info_pages``,
    ``annotation_authors``, ``embedded_files``, ``trailer_id``."""


@dataclass(frozen=True, slots=True)
class MetadataWriteOutcome:
    """One `meta set` write (D2.2/D2.3): the candidate bytes, plus which
    halves were actually touched, for the run's own reporting."""

    output: bytes

    wrote_xmp: bool
    """Whether an XMP packet existed and was updated (D2.2's "creates
    neither" rule -- ``False`` on a document with no packet, even when
    ``sets``/``clears``/``clear_all`` were non-empty)."""


@dataclass(frozen=True, slots=True)
class CompositeOutcome:
    """One `watermark`/`stamp`/`ocr` compositing pass (D4.1, migrated by
    `PDF-23` D3/D4): merges *layer* onto each selected page of an
    already-open WRITER, POST-append -- the SAME shape `set_rotation`
    already uses (`ops/pages.py`'s `rotate_run` is the donor), no longer
    the asymmetric pre-append shape this docstring used to describe.
    Producing no bytes itself; the caller still owns `write()`.

    **The scoping guarantee (`PDF-23` D2/D4), and it is the point of this
    method's existence:** the mutation is confined to `pages` and nothing
    else, even when two or more of the writer's pages share one
    `/Contents` object (legal PDF, and the ordinary output of a
    template-driven producer -- `4adc417234` / B-097). A selected page
    whose `/Contents` is shared is copy-on-written (a fresh stream object,
    registered on the writer, before the merge) so the shared object a
    SIBLING page still points at is never touched; an UNSELECTED page's
    `/Contents` object identity and decoded content are therefore always
    unchanged, whether or not it happens to share an object with a
    selected one.
    """

    pages_composited: tuple[int, ...]
    """1-based, in the order composited -- the selection's own order."""

    pages_copied: tuple[int, ...]
    """The subset of `pages_composited` whose `/Contents` was copy-on-written
    because it was shared with another page of the document at merge time
    (D4.1/D5.1). A reporting surface, not a warning -- how a later reader
    explains an output-size increase on an otherwise ordinary-looking
    selection. Empty on a document with no `/Contents` sharing at all."""

    blank_pages: tuple[int, ...]
    """Pages with no `/Contents` key at merge time (D4.4): overlay and
    underlay are byte-identical there. `ops/overlay.py` turns this into an
    `OperationResult.warnings` entry naming the pages; the adapter reports
    only the fact, never the wording."""


# --------------------------------------------------------------------------- #
# PDF-13 — the encryption vocabulary and facts. Port level, not adapter level,
# because every row below is a property of the PDF *format* (ISO 32000) rather
# than of an engine: two adapters read the same encryption dictionary and must
# not be able to disagree about what it says.
# --------------------------------------------------------------------------- #

#: The ONE encryption-algorithm map, keyed by ``(/V, /CFM, key-length-in-bits)``
#: from the standard security handler's encryption dictionary.
#:
#: **Promoted here from ``adapters/pypdf_structure.py`` by PDF-13**, whose own
#: comment named the reason: *"PDF-13 extends it here and nowhere else; a
#: second copy is how two verbs start disagreeing about what a file is
#: encrypted with."* PDF-13 is that second consumer — ``permissions`` answers
#: from the pikepdf adapter while ``info`` answers from the pypdf one — so the
#: map moved to the port both adapters already depend on rather than being
#: copied. The rows themselves are unchanged.
#:
#: ``/CFM`` is ``""`` for /V 1 and 2, which predate crypt filters. A lookup
#: that misses yields ``None`` plus a warning — never a guess.
ENCRYPTION_ALGORITHMS: Final[dict[tuple[int, str, int], str]] = {
    (1, "", 40): "RC4-40",
    (2, "", 40): "RC4-40",
    (2, "", 128): "RC4-128",
    (4, "/V2", 40): "RC4-40",
    (4, "/V2", 128): "RC4-128",
    (4, "/AESV2", 128): "AES-128",
    (5, "/AESV3", 256): "AES-256",
}

#: The `--allow` vocabulary, and the exact tokens `permissions` reports back.
#: Deliberately its own list rather than ``DocumentInfo.permissions``' tokens:
#: those are ``info``'s shipped public JSON (``fill-forms``,
#: ``extract-accessibility``, ``print-high-resolution``, …) and renaming them
#: would break a published contract, while these are `PLAN.md` §5.7's own
#: `--allow` spelling. The overlap is intentional and the divergence is
#: recorded rather than silently reconciled.
PERMISSION_TOKENS: Final[tuple[str, ...]] = (
    "accessibility",
    "annotate",
    "assemble",
    "copy",
    "forms",
    "modify",
    "print",
    "print-highres",
)

#: PDF-39 member 1 (`B-066`) — the crossing between the two PUBLIC permission
#: vocabularies. Keys are :data:`PERMISSION_TOKENS` members (the `--allow` and
#: `permissions` spelling); values are ``DocumentInfo.permissions`` members
#: (the spelling `info` publishes, decoded by
#: ``adapters/pypdf_structure.py``'s ``_PERMISSION_BITS``). Only the three
#: diverging pairs appear here; the five tokens absent from this map are
#: spelled identically on both surfaces.
#:
#: **The disagreement is between two OUTPUT surfaces, not between an input and
#: an output.** `pdftoolkit info -o json` and `pdftoolkit permissions -o json`
#: run against the same encrypted document report the same three ISO 32000-1
#: Table 22 bits (9, 10, 12) under different names, so a consumer diffing one
#: against the other sees three phantom differences on every encrypted file.
#: This map is how a consumer crosses between them, and README's published
#: mapping table is DERIVED from it rather than transcribed beside it.
#:
#: **Neither side may be renamed** (X-410): both are shipped public JSON, and
#: the comment above :data:`PERMISSION_TOKENS` is right that renaming either
#: would break a published contract. PDF-39 ratifies that judgement and adds
#: the step it was missing — a mapping on a surface a consumer reads.
#:
#: **THE `--allow` INPUT ALIAS IS DELIBERATELY NOT IMPLEMENTED, and this is
#: the record of that ruling.** Teaching `--allow` to also accept `fill-forms`,
#: `extract-accessibility` and `print-high-resolution` is X-410-legal and would
#: spare a consumer the translation entirely. It is REFUSED for cycle 3 because
#: an accepted input token is permanent from v1.0.0: it could never be
#: withdrawn without a major bump, so it would spend an irreversible budget to
#: close a gap a documented table closes reversibly. If a consumer ever asks
#: for it, this map is shaped so the alias is a three-line change rather than a
#: redesign. Until then `pdftoolkit encrypt --allow fill-forms` is a usage
#: error (exit 2), and a test asserts that it stays one.
PERMISSION_TOKEN_MAP: Final[dict[str, str]] = {
    "forms": "fill-forms",
    "accessibility": "extract-accessibility",
    "print-highres": "print-high-resolution",
}

#: Tokens the *format* grants whatever was requested. **Measured, not assumed**
#: (pikepdf 10.12.0 / libqpdf 12.3.2, R=4 and R=6 both): saving with every
#: permission denied still yields ``accessibility=True``, because ISO 32000-2
#: deprecated bit 10 and conforming readers always permit extraction for
#: accessibility. Reported honestly rather than echoed back as denied.
ALWAYS_GRANTED_TOKENS: Final[tuple[str, ...]] = ("accessibility",)


# --------------------------------------------------------------------------- #
# PDF-20 (B-086) — the ONE password hint. Port level for the same reason
# `ENCRYPTION_ALGORITHMS` is: two adapters raise the same refusal and must not
# be able to disagree about how a user resolves it.
# --------------------------------------------------------------------------- #

#: What to tell a user whose document needs a password we do not have.
#:
#: **Promoted here from the two adapters by PDF-20.** The text existed as two
#: byte-identical private copies (`adapters/pikepdf_structure.py` and
#: `adapters/pypdf_structure.py`) plus three further inline spellings of the
#: same sentence. `pypdf_structure.py`'s own comment argued the duplication was
#: deliberate -- *"duplicated here rather than imported so this adapter never
#: reaches into its sibling's module for a private symbol"* -- and that
#: objection was RIGHT about the fix it refused and does not apply to this one.
#: A port is not a sibling adapter; it is the shared owner both adapters
#: already import from, exactly as `PDF-13` reasoned when it moved
#: `ENCRYPTION_ALGORITHMS` out of the same file.
#:
#: **The `--password-file` clause was REMOVED, and that half is the half that
#: actually harmed a user** (B-086). Only three verbs declare that flag --
#: `decrypt`, `encrypt` and `permissions` -- and none of them reaches this hint;
#: they resolve a password through `ops/crypto.py`, which has no `open_document`
#: call site. Every verb that CAN reach this message therefore printed an
#: instruction naming a flag it would reject with exit 2. The surviving clause
#: is true on every verb that can print it.
PASSWORD_HINT: Final[str] = "run 'pdftoolkit decrypt' first"


def algorithm_name(version: int, method: str, bits: int) -> str | None:
    """``"AES-256"``/``"RC4-128"``/… for one encryption dictionary, or ``None``.

    ``None`` rather than a plausible-looking guess when the combination is
    unknown: an encryption algorithm reported wrongly is worse than one
    reported as unknown.
    """
    return ENCRYPTION_ALGORITHMS.get((version, method, bits))


@dataclass(frozen=True, slots=True)
class EncryptionFacts:
    """What one document's security handler says, read without a write.

    A plain dataclass like every other shape crossing this port, so
    ``ops/crypto.py`` answers `permissions` without ever holding a
    ``pikepdf.Pdf`` — and, more to the point here, without a ``Secret`` ever
    needing to exist below L2.
    """

    encrypted: bool
    unlocked: bool
    """Whether the supplied credential (or the empty user password) opened it.
    ``False`` with ``encrypted=True`` is exactly `PLAN.md` §5.6's exit-6
    third sub-case."""

    algorithm: str | None
    revision: int | None
    key_bits: int | None
    granted: tuple[str, ...]
    """Granted :data:`PERMISSION_TOKENS`, sorted. Empty when unreadable."""

    permissions_readable: bool
    """``False`` when the format did not let the bits be read at all. The
    output then **says so** rather than reporting an empty set as if it were
    a measured deny-everything (`PLAN.md` §5.7's last sentence)."""

    def to_dict(self) -> dict[str, object]:
        return {
            "encrypted": self.encrypted,
            "algorithm": self.algorithm,
            "revision": self.revision,
            "key_bits": self.key_bits,
            "granted": list(self.granted),
            "permissions_readable": self.permissions_readable,
        }


class StructureEngine(Protocol):
    """Read a document's structure. Implemented in full by the primary adapter."""

    @property
    def adapter_name(self) -> str: ...

    def capabilities(self) -> frozenset[str]: ...

    def probe(self) -> AdapterProbe: ...

    def read_document_info(
        self,
        path: Path,
        *,
        fonts: bool = ...,
        pages: bool = ...,
        linearized: bool = ...,
        password: Secret | None = None,
    ) -> DocumentInfo: ...

    def open_document(self, path: Path, *, password: Secret | None = None) -> OpenStructureDocument:
        """Open *path* for structural reading -- page count and outline.

        Args:
            password: PDF-37 -- a resolved secret to try when the empty
                password does not open the document, or ``None``. Never
                read eagerly by this method's own callers (D3): the ops
                layer resolves it only once ``read_encryption`` has already
                confirmed the document is actually encrypted
                (`ops/document_password.py`), so a plain document never
                costs a password read at all.

        Raises:
            NoInputError: Exit 4 -- the path does not exist.
            FailureError: Exit 1 -- malformed, corrupt or unparseable.
            AuthError: Exit 6 -- no password was supplied and one is
                required, OR the supplied password did not unlock the
                document -- two distinct, byte-different messages (AC6).
        """
        ...

    def new_writer(self) -> StructureWriter:
        """A fresh, empty :class:`StructureWriter` for one output."""
        ...

    def compress(self, data: bytes, *, password: Secret | None = None) -> CompressOutcome:
        """The `"object-streams"` capability (D-12.1/D-12.2): a structural
        recompression pass over an in-memory document — object streams
        generated, streams recompressed — returning the candidate bytes and
        both sides' :class:`StructuralFacts` for D-12.3's Layer 1 gate.

        Args:
            password: PDF-37 -- a resolved secret, or ``None``. Tried only
                after the empty password fails, exactly like
                :meth:`StructureEngine.open_document`.

        Raises:
            AuthError: Exit 6 -- no password was supplied and one is
                required, or the supplied password did not unlock it.
            FailureError: Exit 1 -- the engine could not process it.
        """
        ...

    def repair(self, data: bytes, *, password: Secret | None = None) -> RepairOutcome:
        """The `"repair"` capability (D-12.4): reconstruct a damaged
        cross-reference table via libqpdf's own recovery parser.

        Args:
            password: PDF-37 -- see :meth:`compress`.

        Raises:
            AuthError: Exit 6 -- no password was supplied and one is
                required, or the supplied password did not unlock it.
            FailureError: Exit 1 -- truly unrecoverable.
        """
        ...

    def linearize(self, data: bytes, *, password: Secret | None = None) -> bytes:
        """The `"linearize"` capability (D-12.6): rewrite for byte-serving.

        Verified internally before returning — check 1 of D-12.6's three
        (reopen the candidate, `is_linearized` true and
        `check_linearization()` reports no problems) — so a failed
        verification never reaches `AtomicWriter` at all.

        Args:
            password: PDF-37 -- see :meth:`compress`.

        Raises:
            AuthError: Exit 6 -- no password was supplied and one is
                required, or the supplied password did not unlock it.
            FailureError: Exit 1 -- the engine could not process it, or the
                internal verification failed.
        """
        ...

    def read_encryption(self, data: bytes, password: Secret | None) -> EncryptionFacts:
        """The `"robust-encryption"` capability, read half (PDF-13).

        Never raises on a wrong or absent password: "we could not open it"
        is a *fact about the document* this method reports
        (``unlocked=False``), and turning it into an exception here would
        make `encrypt`'s already-encrypted refusal (exit 5) indistinguishable
        from `decrypt`'s wrong-password refusal (exit 6) at the call site
        that has to tell them apart.

        Raises:
            FailureError: Exit 1 -- malformed, corrupt or unparseable.
        """
        ...

    def encrypt(
        self,
        data: bytes,
        *,
        owner: Secret,
        user: Secret | None,
        allow: frozenset[str],
        legacy: bool,
    ) -> bytes:
        """The `"robust-encryption"` capability, write half (PDF-13).

        ``allow`` holds :data:`PERMISSION_TOKENS`; ``legacy`` selects RC4-128
        (R4) instead of AES-256 (R6). No cryptography is implemented in this
        product — every operation is libqpdf's.

        Raises:
            AuthError: Exit 6 -- the input is itself password-protected.
            FailureError: Exit 1 -- the engine could not process it.
        """
        ...

    def decrypt(self, data: bytes, *, password: Secret) -> bytes:
        """The `"robust-encryption"` capability, removal half (PDF-13).

        Raises:
            AuthError: Exit 6 -- wrong password, or user-level access where
                owner-level is required.
            FailureError: Exit 1 -- the engine could not process it.
        """
        ...

    # -- PDF-14 (`meta get`/`meta set`, `watermark`/`stamp`), appended at the
    # end of the Protocol body -------------------------------------------- #

    def read_metadata(self, path: Path, *, password: Secret | None = None) -> MetadataFacts:
        """The `meta get` read (D2, D2.4). Both halves, side by side, plus
        the D2.4 residual-surface facts -- never merged, never guessed.

        Args:
            password: PDF-37 -- see :meth:`open_document`.

        Raises:
            NoInputError: Exit 4 -- the path does not exist.
            FailureError: Exit 1 -- malformed, corrupt or unparseable.
            AuthError: Exit 6 -- no password was supplied and one is
                required, or the supplied password did not unlock it.
        """
        ...

    def write_metadata(
        self,
        data: bytes,
        *,
        sets: Mapping[str, str],
        clears: Sequence[str],
        clear_all: bool,
        password: Secret | None = None,
    ) -> MetadataWriteOutcome:
        """The `meta set` write (D2.2/D2.3). Applies ``sets``/``clears`` (or
        clears everything, under ``clear_all``) to `/Info`, and -- only when
        the document already carries an XMP packet -- to XMP too, via the
        D2.1 alignment table. Creates no XMP packet where none existed.

        Preserves the original PdfObject type of every `/Info` key not
        named in ``sets``/``clears`` (D2.3): the public
        ``PdfWriter.metadata = value`` setter stringifies every value
        through ``create_string_object(str(value))``, which would silently
        corrupt a field (e.g. a `/Trapped` name object) the caller never
        asked to touch.

        Args:
            password: PDF-37 -- see :meth:`open_document`.

        Raises:
            AuthError: Exit 6 -- no password was supplied and one is
                required, or the supplied password did not unlock it.
            FailureError: Exit 1 -- the engine could not process it.
        """
        ...

    def composite_layer(
        self,
        writer: StructureWriter,
        *,
        layer: bytes,
        pages: Sequence[int],
        position: str,
    ) -> CompositeOutcome:
        """The `watermark`/`stamp`/`ocr` compositing primitive (D4.1,
        migrated to a writer-attached, post-append shape by `PDF-23` D3),
        reusable by `PDF-15`'s `ops/ocr.py` through this SAME port method.

        Merges *layer* -- a one-page PDF, already serialized: the generated
        watermark text layer or the selected `--from`/OCR page -- onto each
        of *pages* (1-based, sorted, deduplicated) of an already-appended
        *writer*'s own pages. The caller creates *writer* and appends the
        SOURCE document's full page range (`new_writer()` + `append_pages()`)
        BEFORE calling this method -- never after -- so that `pages[i]`
        addresses `writer`'s own `i`-th appended page directly; this method
        may then be called MULTIPLE times against the same *writer* (once per
        distinct layer/page-subset) before the caller's own `write()`.

        **Copy-on-write (D4).** Before merging a selected page whose raw,
        unresolved `/Contents` entry names an object number shared by more
        than one of `writer`'s own pages, this method first builds a fresh
        content-stream object carrying that page's current decoded content,
        registers it on `writer`, and repoints the page's `/Contents` at it
        -- so the merge never mutates an object a sibling page still
        depends on. An UNSELECTED page is never visited at all. This is what
        makes the guarantee `CompositeOutcome`'s own docstring states hold
        even on a document whose pages share one `/Contents` object (legal
        PDF; the ordinary output of a template-driven producer).

        Args:
            writer: An already-created `StructureWriter` with the source
                document's pages already appended (`append_pages`).
            layer: A one-page PDF, already serialized.
            pages: 1-based, sorted, deduplicated -- indices into `writer`'s
                own already-appended page sequence.
            position: ``"overlay"`` or ``"underlay"``.

        Raises:
            FailureError: Exit 1 -- *layer* is not a parseable one-page PDF.
        """
        ...


class ImagePassEngine(Protocol):
    """The shape an adapter must have to claim the `"image-pass"` capability
    (D-12.2's Pillow/pypdf `--images downsample|recompress` pre-pass).

    A capability-selected narrowing exactly like :class:`LinearizationProbe`
    below, not a fourth ``StructureEngine`` method: the pikepdf-backed
    adapter never performs this operation, so putting it on the shared
    Protocol would force every adapter to answer for work only one of them
    does.
    """

    def downsample_images(
        self,
        data: bytes,
        *,
        mode: str,
        pages: frozenset[int] | None,
        dpi: float,
        quality: int,
    ) -> ImagePassOutcome:
        """Transform in-scope images per D-12.2's `downsample`/`recompress`
        rules. ``pages`` is ``None`` for "every page"; a set otherwise
        (`PLAN.md` §4.3 set semantics). Never raises for a skip -- skipped
        images are counted in the outcome, not refused."""
        ...


class LinearizationProbe(Protocol):
    """The shape an adapter must have to claim the ``linearized`` capability.

    Not a parallel interface: the port is still ``StructureEngine``. This is what
    a *capability token* means expressed as a type, so the one call site that
    selects on ``linearized`` is checked rather than cast blindly. A capability
    an adapter can declare but whose shape nothing pins is a capability that
    starts drifting on the second adapter that declares it.
    """

    def is_linearized(self, path: Path) -> bool: ...


def adapters() -> tuple[Adapter, ...]:
    """Primary first, then the capability-selected secondary."""
    from pdf_toolkit.adapters import pikepdf_structure, pypdf_structure

    return (pypdf_structure.ADAPTER, pikepdf_structure.ADAPTER)


def probe() -> EngineReport:
    from pdf_toolkit.adapters import pikepdf_structure, pypdf_structure

    primary = pypdf_structure.ADAPTER.probe()
    secondary = pikepdf_structure.ADAPTER.probe()
    if secondary.available:
        detail = (
            f"secondary: {pikepdf_structure.ADAPTER.adapter_name} "
            f"{secondary.version or 'version unknown'} "
            f"({pikepdf_structure.CAPABILITY_SUMMARY})"
        )
    else:
        detail = (
            f"secondary: {pikepdf_structure.ADAPTER.adapter_name} unavailable "
            f"({pikepdf_structure.CAPABILITY_SUMMARY} are therefore unavailable)"
        )
    return build_report(
        PORT,
        adapter=pypdf_structure.ADAPTER.adapter_name,
        kind=KIND_PYTHON_PACKAGE,
        probe=primary,
        extra_detail=detail,
    )


def require_structure(*, capability: str | None = None) -> StructureEngine:
    """The one way a verb demands the structure engine.

    Delegates to ``ports.require`` — the exit-3 chokepoint — and narrows the
    result. The registry is keyed by *string* because the port names are public
    API, so exactly one narrowing lives here, next to the Protocol it narrows
    to, rather than at every call site.
    """
    return cast("StructureEngine", require(PORT, capability=capability))


def require_linearization() -> LinearizationProbe:
    """The adapter that can answer ``linearized``, selected by capability."""
    return cast("LinearizationProbe", require(PORT, capability="linearized"))


def require_encryption() -> StructureEngine:
    """The adapter that can encrypt/decrypt, selected by capability.

    ``"robust-encryption"`` is declared only by the pikepdf adapter, which is
    `PLAN.md` §7.1's named owner of the capability and D-04's "selected by
    capability, not by guesswork" applied to the one operation where guessing
    would be worst.
    """
    return cast("StructureEngine", require(PORT, capability="robust-encryption"))


def require_image_pass() -> ImagePassEngine:
    """The adapter that can perform `compress --images`, selected by
    capability (`"image-pass"`, declared only by the pypdf adapter)."""
    return cast("ImagePassEngine", require(PORT, capability="image-pass"))


def require_composite() -> StructureEngine:
    """The adapter that can perform `watermark`/`stamp` compositing,
    selected by capability (`"composite"`, declared only by the pypdf
    adapter -- it disambiguates against the pikepdf secondary, X-76)."""
    return cast("StructureEngine", require(PORT, capability="composite"))
