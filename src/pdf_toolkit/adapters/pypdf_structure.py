"""``StructureEngine`` primary adapter — pypdf.

pypdf is the default structure backend: pure Python, BSD-3-Clause, and the one
that reads a document's shape without pulling a C library into the process.
``pikepdf_structure`` is the capability-selected secondary for the things qpdf
does better (repair, linearization, object streams, robust encryption).

Every pypdf import in this file is **function-local**, so importing this module
costs nothing and ``doctor`` can load all eight adapters inside the startup
budget. That is a rule, not an optimisation: ``PLAN.md`` §12 R-13 is asserted by
a test that fails if importing ``cli.main`` leaves an engine in ``sys.modules``.

**PDF-12.** This adapter never performs `compress`/`repair`/`linearize` --
those are pikepdf's `"object-streams"`/`"repair"`/`"linearize"` capabilities
-- so the three methods below are **explicit refusals** (exit 3, naming
pikepdf), never a silent fallback (`PLAN.md` §5.5). What this adapter DOES
own is the `--images downsample|recompress` pre-pass, over its own
`"image-pass"` capability: Pillow resamples in-scope images and
`page.images[i].replace(...)` re-embeds them, exactly the §7.1 mechanism the
plan names for `compress`.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, BinaryIO, Final

from pdf_toolkit.adapters import AdapterProbe, package_probe
from pdf_toolkit.errors import AuthError, EngineMissingError, FailureError, NoInputError, UsageError
from pdf_toolkit.models import DocumentInfo, PageInfo
from pdf_toolkit.output.logging import get_logger
from pdf_toolkit.ports import BROKEN_INSTALL_HINT
from pdf_toolkit.ports.structure import (
    CompressOutcome,
    ImagePassOutcome,
    RepairOutcome,
    algorithm_name,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from pypdf import PdfReader
    from pypdf._page import ImageFile

__all__ = ["ADAPTER", "PypdfOpenDocument", "PypdfStructureAdapter", "PypdfStructureWriter"]

_NAME: Final[str] = "pypdf"
_DISTRIBUTION: Final[str] = "pypdf"
_MODULE: Final[str] = "pypdf"

#: What this adapter claims it can do. ``ports.require(..., capability=...)``
#: selects on these tokens, so they are a contract between adapters and the
#: registry rather than documentation.
#: `"image-pass"` (PDF-12) is `compress --images downsample|recompress`'s own
#: capability -- pypdf/Pillow work, never pikepdf's.
_CAPABILITIES: Final[frozenset[str]] = frozenset({"read", "metadata", "pages", "image-pass"})

#: PDF-12's optimize operations this adapter explicitly refuses. Named once so
#: the three refusal methods below stay identical in shape.
_OPTIMIZE_HINT: Final[str] = (
    f"install pikepdf. Install it with: {BROKEN_INSTALL_HINT}. "
    "Run 'pdftoolkit doctor' to see which engines resolved."
)

#: Filters that mean "converting this to JPEG would lose information" --
#: skipped, counted, and the count is reported (D-12.2's skip rule).
_UNENCODABLE_FILTERS: Final[frozenset[str]] = frozenset({"/CCITTFaxDecode", "/JBIG2Decode"})

#: The ONE encryption-algorithm map now lives at the port
#: (``ports.structure.ENCRYPTION_ALGORITHMS``), not here. **Moved by PDF-13**
#: for the reason this comment already gave when the map was local: *"a second
#: copy is how two verbs start disagreeing about what a file is encrypted
#: with."* PDF-13's `permissions` answers from the pikepdf adapter while
#: ``info`` answers from this one, so the map had to become shared or become
#: duplicated. The rows are unchanged; only their home moved.

#: Permission bits, ISO 32000-1 Table 22, 1-based bit numbers. Spelled as raw
#: bit positions rather than as an engine enum so the decoding is a property of
#: the *format* and survives an engine swap. Reserved bits (7, 8, 13-32) are
#: deliberately absent: they are set to 1 in every conforming file and reporting
#: them would bury the four tokens a user came for in twenty-six that mean
#: nothing.
_PERMISSION_BITS: Final[tuple[tuple[str, int], ...]] = (
    ("print", 3),
    ("modify", 4),
    ("copy", 5),
    ("annotate", 6),
    ("fill-forms", 9),
    ("extract-accessibility", 10),
    ("assemble", 11),
    ("print-high-resolution", 12),
)


def _decode_permissions(bits: int | None) -> tuple[str, ...]:
    """Decode the ``/P`` bitmask into stable tokens. Empty tuple when unknown."""
    if bits is None:
        return ()
    return tuple(name for name, bit in _PERMISSION_BITS if bits & (1 << (bit - 1)))


def _algorithm(encryption: Any) -> tuple[str | None, str | None]:
    """``(algorithm, warning)`` from an encryption dictionary.

    Returns ``(None, warning)`` rather than a plausible-looking guess when the
    dictionary does not match a known combination, because an encryption
    algorithm reported wrongly is worse than one reported as unknown.
    """
    if encryption is None:
        return None, None
    version = int(encryption.get("/V", 0) or 0)
    length = int(encryption.get("/Length", 40) or 40)
    method = ""
    crypt_filters = encryption.get("/CF")
    if crypt_filters is not None:
        default = encryption.get("/StmF", "/StdCF")
        entry = crypt_filters.get_object().get(str(default))
        if entry is not None:
            method = str(entry.get_object().get("/CFM", "") or "")
    algorithm = algorithm_name(version, method, length)
    if algorithm is not None:
        return algorithm, None
    return None, (
        f"unrecognised encryption dictionary (/V {version}, /CFM {method or 'none'}, "
        f"/Length {length}); reporting the algorithm as null rather than guessing"
    )


def _pdf_version(header: str) -> str:
    """``"%PDF-1.7"`` -> ``"1.7"``. Anything unexpected is passed through as-is."""
    text = header.strip()
    prefix = "%PDF-"
    return text[len(prefix) :] if text.startswith(prefix) else text


def _page_info(number: int, page: Any) -> PageInfo:
    box = page.mediabox
    resources = page.get("/Resources")
    images = 0
    if resources is not None:
        xobjects = resources.get_object().get("/XObject")
        if xobjects is not None:
            images = sum(
                1
                for entry in xobjects.get_object().values()
                if str(entry.get_object().get("/Subtype", "")) == "/Image"
            )
    try:
        text = page.extract_text() or ""
    # A page that will not yield text is not a malformed document.
    except Exception:
        text = ""
    rotation = int(page.get("/Rotate", 0) or 0) % 360
    return PageInfo(
        number=number,
        width_pt=float(box.width),
        height_pt=float(box.height),
        rotation=rotation,
        has_text=bool(text.strip()),
        image_count=images,
    )


def _fonts(reader: PdfReader) -> tuple[str, ...]:
    """``/BaseFont`` names across every page, deduped and sorted.

    Names only. No embedding, subsetting or substitutability analysis is
    performed, and none is implied by the field's presence.
    """
    names: set[str] = set()
    for page in reader.pages:
        resources = page.get("/Resources")
        if resources is None:
            continue
        fonts = resources.get_object().get("/Font")
        if fonts is None:
            continue
        for entry in fonts.get_object().values():
            base = entry.get_object().get("/BaseFont")
            if base is not None:
                names.add(str(base).lstrip("/"))
    return tuple(sorted(names))


def _metadata(reader: PdfReader) -> dict[str, str]:
    raw = reader.metadata
    if raw is None:
        return {}
    return {str(key): str(value) for key, value in raw.items() if value is not None}


class PypdfStructureAdapter:
    """The pypdf-backed ``StructureEngine``."""

    kind: Final[str] = "python-package"

    @property
    def adapter_name(self) -> str:
        return _NAME

    def capabilities(self) -> frozenset[str]:
        return _CAPABILITIES

    def probe(self) -> AdapterProbe:
        return package_probe(_MODULE, _DISTRIBUTION)

    def read_document_info(
        self,
        path: Path,
        *,
        fonts: bool = False,
        pages: bool = False,
        linearized: bool = False,
    ) -> DocumentInfo:
        """Assemble a :class:`DocumentInfo` for one document.

        Args:
            path: An existing regular file. Validation of the operand — missing
                path (exit 4), directory (exit 2) — belongs to the caller, which
                is the only place that knows how many operands there were.
            fonts: Populate ``fonts``. Off by default because it walks every
                page's resource dictionary.
            pages: Populate ``pages`` with a :class:`PageInfo` each. Off by
                default because ``has_text`` costs a text extraction per page.
            linearized: The already-resolved answer from the port that owns the
                ``linearized`` capability. Passed in rather than computed here
                on purpose: pypdf cannot answer it, and an adapter that guessed
                would be exactly the silent degradation this product refuses.

        Raises:
            AuthError: Exit 6 — a user password is required and none was
                supplied. This adapter never asks for one; ``PLAN.md`` §5.7's
                resolution chain belongs to PDF-13.
            FailureError: Exit 1 — the document is malformed or unreadable.
                ``PDF-12``'s ``repair`` acceptance depends on this being 1.
        """
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        logger = get_logger("adapters.pypdf")
        size_bytes = path.stat().st_size

        try:
            reader = PdfReader(str(path))
        except PdfReadError as error:
            raise FailureError(f"could not read PDF: {error}", path=str(path)) from error
        except (OSError, ValueError) as error:
            raise FailureError(f"could not read PDF: {error}", path=str(path)) from error

        encrypted = bool(reader.is_encrypted)
        algorithm: str | None = None
        if encrypted:
            encryption_dict = reader.trailer.get("/Encrypt")
            algorithm, warning = _algorithm(
                encryption_dict.get_object() if encryption_dict is not None else None
            )
            if warning:
                logger.warning("%s: %s", path, warning)
            # The empty user password is tried once, unconditionally. That is
            # what makes `info` work on the common "owner password only,
            # permissions-restricted" document without a credential -- PLAN.md
            # §5.7's "report the permission bits without needing the owner
            # password where the format allows". A user-password-protected file
            # returns NOT_DECRYPTED here and becomes exit 6.
            try:
                unlocked = bool(reader.decrypt(""))
            # Any failure at all means "still locked"; the reason is a debug detail.
            except Exception as error:
                logger.debug("%s: decrypt('') raised %s", path, error)
                unlocked = False
            if not unlocked:
                raise AuthError(
                    "a user password is required to read this document; supply one with "
                    "--password-file PATH (or --password-file - to read one line from stdin)",
                    path=str(path),
                )

        try:
            page_count = len(reader.pages)
            version = _pdf_version(reader.pdf_header)
            # `user_access_permissions` is Optional even on an encrypted file:
            # a non-standard security handler need not carry /P at all. That is
            # exactly the "empty tuple when unknown" case, not a crash.
            raw_permissions = reader.user_access_permissions if encrypted else None
            permissions = _decode_permissions(
                int(raw_permissions) if raw_permissions is not None else None
            )
            root = reader.root_object
            acroform = root.get("/AcroForm")
            acroform_obj = acroform.get_object() if acroform is not None else None
            fields = acroform_obj.get("/Fields") if acroform_obj is not None else None
            has_forms = bool(fields is not None and len(fields.get_object()) > 0)
            has_signature = _has_signature(acroform_obj, fields)
            xmp = _xmp(reader)
            font_names = _fonts(reader) if fonts else ()
            page_details = (
                tuple(_page_info(index, page) for index, page in enumerate(reader.pages, start=1))
                if pages
                else ()
            )
            document_metadata = _metadata(reader)
        except PdfReadError as error:
            raise FailureError(f"could not read PDF: {error}", path=str(path)) from error
        except (KeyError, TypeError, ValueError, OSError) as error:
            raise FailureError(f"could not read PDF: {error}", path=str(path)) from error

        return DocumentInfo(
            path=str(path),
            size_bytes=size_bytes,
            page_count=page_count,
            pdf_version=version,
            encrypted=encrypted,
            encryption_algorithm=algorithm,
            permissions=permissions,
            linearized=linearized,
            has_signature=has_signature,
            has_forms=has_forms,
            metadata=document_metadata,
            xmp=xmp,
            fonts=font_names,
            pages=page_details,
        )

    def open_document(self, path: Path) -> PypdfOpenDocument:
        """D10's read half — see :class:`PypdfOpenDocument` for the shape.

        Existence and directory checks are the caller's job (they need to know
        how many operands there were, per `ops/inspect.py`'s own precedent) --
        this method's own contract starts at "the path exists and is a file."
        """
        return PypdfOpenDocument(path)

    def new_writer(self) -> PypdfStructureWriter:
        """D10's write half — see :class:`PypdfStructureWriter`."""
        return PypdfStructureWriter()

    def compress(self, data: bytes) -> CompressOutcome:
        """PDF-12 explicit refusal (D-12.1) — this adapter never performs the
        `"object-streams"` structural pass; pikepdf does. Silent fallback to a
        different engine is forbidden by `PLAN.md` §5.5."""
        raise EngineMissingError(
            f"compress needs pikepdf's object-streams capability; {_OPTIMIZE_HINT}"
        )

    def repair(self, data: bytes) -> RepairOutcome:
        """PDF-12 explicit refusal (D-12.1) — pypdf has no recovery parser."""
        raise EngineMissingError(f"repair needs pikepdf's recovery parser; {_OPTIMIZE_HINT}")

    def linearize(self, data: bytes) -> bytes:
        """PDF-12 explicit refusal (D-12.1) — pypdf cannot linearize."""
        raise EngineMissingError(
            f"linearize needs pikepdf's linearization support; {_OPTIMIZE_HINT}"
        )

    def downsample_images(
        self,
        data: bytes,
        *,
        mode: str,
        pages: frozenset[int] | None,
        dpi: float,
        quality: int,
    ) -> ImagePassOutcome:
        """The `"image-pass"` capability (D-12.2) — `compress --images
        downsample|recompress`'s own pre-pass, over `page.images[i].replace(...)`.

        ``downsample``: for each in-scope image whose pixel width exceeds
        ``dpi x page_width_inches`` (the PAGE box, never the placement rect
        -- D-12.2's stated, conservative limitation), resample with
        `Image.LANCZOS` to that width, preserving aspect ratio, and
        re-embed. An image at or under the threshold is left untouched.

        ``recompress``: every in-scope image is re-embedded at ``quality``,
        pixel dimensions unchanged.

        Images that cannot be re-encoded as JPEG without losing information
        -- an alpha channel, bilevel, `CCITTFaxDecode` or `JBIG2Decode` --
        are skipped, counted, and never touched.
        """
        from PIL import Image
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(data))
        writer = PdfWriter()
        writer.append(reader)

        transformed = 0
        skipped = 0
        for page_number, page in enumerate(writer.pages, start=1):
            if pages is not None and page_number not in pages:
                continue
            page_width_in = float(page.mediabox.width) / 72.0
            threshold_px = dpi * page_width_in
            for image_file in list(page.images):
                if _should_skip_image(image_file):
                    skipped += 1
                    continue
                pil_image = image_file.image
                if (
                    pil_image is None
                ):  # pragma: no cover - `_should_skip_image` already refused this
                    continue
                if mode == "recompress":
                    image_file.replace(pil_image, quality=quality)
                    transformed += 1
                    continue
                # mode == "downsample"
                width, height = pil_image.size
                if width <= threshold_px:
                    continue
                new_width = max(1, int(threshold_px))
                new_height = max(1, round(height * new_width / width))
                resized = pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                image_file.replace(resized, quality=quality)
                transformed += 1

        out_buffer = io.BytesIO()
        writer.write(out_buffer)
        return ImagePassOutcome(
            output=out_buffer.getvalue(), images_transformed=transformed, images_skipped=skipped
        )


class PypdfOpenDocument:
    """D10 — one already-open document: page count, top-level outline.

    Opens its own file handle (never lets pypdf open the path itself) so the
    handle this class owns is closeable deterministically on ``__exit__``
    rather than left to pypdf's own lifecycle, which does not expose one.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: BinaryIO | None = None
        self._reader: PdfReader | None = None

    def __enter__(self) -> PypdfOpenDocument:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        if not self._path.exists():
            raise NoInputError("no such file", path=str(self._path))
        if self._path.is_dir():
            raise UsageError("expected a PDF file, not a directory", path=str(self._path))

        handle = open(self._path, "rb")  # closed in __exit__, kept open for lazy page reads
        try:
            self._reader = PdfReader(handle)
        except PdfReadError as error:
            handle.close()
            raise FailureError(f"could not read PDF: {error}", path=str(self._path)) from error
        except (OSError, ValueError) as error:
            handle.close()
            raise FailureError(f"could not read PDF: {error}", path=str(self._path)) from error
        self._handle = handle
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._reader = None
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    @property
    def _open_reader(self) -> PdfReader:
        if self._reader is None:
            raise RuntimeError("PypdfOpenDocument is only valid inside its own with-block")
        return self._reader

    @property
    def page_count(self) -> int:
        return len(self._open_reader.pages)

    def top_level_outline(self) -> tuple[tuple[str, int], ...]:
        """1-based ``(title, destination page)`` pairs, top-level only.

        pypdf represents a nested (non-top-level) entry as a Python ``list``
        interleaved with the top-level entries in ``reader.outline`` — those
        are skipped here rather than descended into, which is what makes this
        "top-level only" rather than "every entry flattened." A document with
        no outline at all reports ``reader.outline == []``, which this
        iterates over trivially into an empty tuple — no special-casing.
        """
        reader = self._open_reader
        entries: list[tuple[str, int]] = []
        for item in reader.outline:
            if isinstance(item, list):
                continue
            resolved = self._resolved_outline_entry(reader, item)
            if resolved is not None:
                entries.append(resolved)
        return tuple(entries)

    @staticmethod
    def _resolved_outline_entry(reader: PdfReader, item: Any) -> tuple[str, int] | None:
        """One outline entry as ``(title, 1-based page)``, or ``None`` when it
        cannot be resolved -- a malformed single entry, not a bad document."""
        title = str(getattr(item, "title", "") or "")
        try:
            zero_based = reader.get_destination_page_number(item)
        except Exception:
            return None
        if zero_based is None:
            return None
        return title, zero_based + 1


class PypdfStructureWriter:
    """D10 — the write half: accumulate pages (and an outline), then serialize.

    Never chooses a destination path (D7) — :meth:`write` takes the stream
    ``AtomicWriter`` already opened.
    """

    def __init__(self) -> None:
        from pypdf import PdfWriter

        self._writer = PdfWriter()

    def append_pages(self, document: PypdfOpenDocument, page_numbers: Sequence[int]) -> None:
        reader = document._open_reader  # same adapter's own internal pair
        for number in page_numbers:
            self._writer.add_page(reader.pages[number - 1])

    def add_outline_entry(self, title: str, page_number: int) -> None:
        self._writer.add_outline_item(title, page_number - 1)

    def import_outline(self, document: PypdfOpenDocument, *, page_map: Mapping[int, int]) -> None:
        for title, source_page in document.top_level_outline():
            destination = page_map.get(source_page)
            if destination is None:
                continue  # dropped: not selected (Design §D3, `--bookmarks preserve`)
            self._writer.add_outline_item(title, destination - 1)

    def write(self, stream: IO[bytes]) -> None:
        self._writer.write(stream)

    # -- PDF-08 (`rotate`), appended at the end of the class body ----------- #

    def set_rotation(self, index: int, degrees: int) -> None:
        """The port's rotation seam — stamp one already-appended page.

        The whole method: no arithmetic, no normalization, no reading of the
        current value. ``degrees`` arrives from ``ops/pages.py`` already
        absolute and already inside ``{0, 90, 180, 270}``, which is what keeps
        `rotate`'s rules unit-testable without an engine.

        ``add_page`` clones each page into this writer's own object store
        (verified: stamping ``self._writer.pages[i]`` leaves the source
        reader's page untouched), so this cannot reach back into the document
        being read — which is what makes ``--in-place`` safe here.

        The pypdf import stays function-local like every other one in this
        file: importing this module must cost nothing (`PLAN.md` §12 R-13).
        """
        from pypdf.generic import NameObject, NumberObject

        self._writer.pages[index][NameObject("/Rotate")] = NumberObject(degrees)


def _has_signature(acroform: Any, fields: Any) -> bool:
    """Presence only — ``/SigFlags`` or a field of type ``/Sig``.

    This product makes **no** claim about whether a signature is valid, whose it
    is, or what it covers (``PLAN.md`` §2 non-goals). Reporting presence is
    useful; reporting validity without a trust store would be a lie.
    """
    if acroform is None:
        return False
    if acroform.get("/SigFlags") is not None:
        return True
    if fields is None:
        return False
    for field in fields.get_object():
        if str(field.get_object().get("/FT", "")) == "/Sig":
            return True
    return False


def _xmp(reader: PdfReader) -> str | None:
    try:
        stream = reader.xmp_metadata
    # Malformed XMP is not a malformed document.
    except Exception:
        return None
    if stream is None:
        return None
    raw = getattr(stream, "stream", None)
    if raw is None:
        return None
    data = raw.get_data()
    return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)


def _should_skip_image(image_file: ImageFile) -> bool:
    """D-12.2's skip rule: an alpha channel, bilevel, or a filter chain that
    is not decode-safe to re-encode as JPEG without losing information.

    Checked from the image's own XObject filters, never guessed from the
    file extension or the container -- the same "sniff the object, not the
    name" discipline `compose`'s own eligibility table already applies.
    """
    pil_image = image_file.image
    if pil_image is None:
        return True
    if pil_image.mode in ("RGBA", "LA", "PA") or "transparency" in pil_image.info:
        return True
    if pil_image.mode == "1":
        return True
    reference = image_file.indirect_reference
    if reference is None:  # pragma: no cover - never inline on a PdfWriter's own page
        return True
    xobject = reference.get_object()
    return any(name in _UNENCODABLE_FILTERS for name in _filter_names(xobject))


def _filter_names(xobject: Any) -> tuple[str, ...]:
    """`/Filter` normalized to a tuple of names -- a single `Name` or an
    `ArrayObject` of them (pypdf's own generic types, not pikepdf's)."""
    filt = xobject.get("/Filter")
    if filt is None:
        return ()
    if isinstance(filt, list):
        return tuple(str(entry) for entry in filt)
    return (str(filt),)


#: The module-level singleton the port resolves to. A singleton rather than the
#: module itself so ``mypy --strict`` structurally checks it against the
#: ``StructureEngine`` Protocol at the seam in ``ports/structure.py``.
ADAPTER: Final[PypdfStructureAdapter] = PypdfStructureAdapter()
