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
    PASSWORD_HINT,
    CompositeOutcome,
    CompressOutcome,
    ImagePassOutcome,
    MetadataFacts,
    MetadataWriteOutcome,
    RepairOutcome,
    algorithm_name,
)
from pdf_toolkit.safety.paths import source_read_error
from pdf_toolkit.secret import Secret

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
#: `"composite"` (PDF-14) is `watermark`/`stamp`'s own capability -- declared
#: ONLY by this adapter so it disambiguates against the pikepdf secondary
#: (X-76: selected by capability, never by adapter name; `require_composite()`
#: mirrors the landed `require_image_pass()`).
_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {"read", "metadata", "pages", "image-pass", "composite"}
)

#: PDF-12's optimize operations this adapter explicitly refuses. Named once so
#: the three refusal methods below stay identical in shape.
_OPTIMIZE_HINT: Final[str] = (
    f"install pikepdf. Install it with: {BROKEN_INSTALL_HINT}. "
    "Run 'pdftoolkit doctor' to see which engines resolved."
)

#: [B-078 / B-086] The hint now lives at the port
#: (``ports.structure.PASSWORD_HINT``), not here. **Moved by PDF-20**, which
#: also dropped its `--password-file` clause: no verb that can reach this
#: message declares that flag, so the instruction named a flag its own reader
#: would be refused for using. The comment this replaces argued the copy was
#: deliberate -- *"duplicated here rather than imported so this adapter never
#: reaches into its sibling's module for a private symbol"* -- and it was right
#: about the fix it refused. Importing from the PORT is not reaching into a
#: sibling adapter; both adapters already import from it, and `PDF-13` moved
#: `ENCRYPTION_ALGORITHMS` out of this very file for the same reason.

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


# --------------------------------------------------------------------------- #
# PDF-14 -- `meta get`/`meta set`'s D2.1 alignment table, and the read/write
# helpers built on it. ONE table, read by both directions, so a report field
# and its write can never disagree about which `/Info` key or which XMP
# property it means.
# --------------------------------------------------------------------------- #

#: ``(report field, /Info key without the slash, XmpInformation attribute)``.
_ALIGNMENT: Final[tuple[tuple[str, str, str], ...]] = (
    ("title", "Title", "dc_title"),
    ("author", "Author", "dc_creator"),
    ("subject", "Subject", "dc_description"),
    ("keywords", "Keywords", "pdf_keywords"),
    ("creator", "Creator", "xmp_creator_tool"),
    ("producer", "Producer", "pdf_producer"),
    ("creation_date", "CreationDate", "xmp_create_date"),
    ("mod_date", "ModDate", "xmp_modify_date"),
)


def _alignment_row(field: str) -> tuple[str, str, str]:
    for row in _ALIGNMENT:
        if row[0] == field:
            return row
    raise AssertionError(f"unknown metadata field {field!r}")  # pragma: no cover - ops/ validates


def _set_xmp_field(xmp: Any, attr: str, field: str, value: str | None) -> None:
    """Apply one D2.1 alignment row's XMP half. ``field`` selects the SHAPE
    (`dc_title`/`dc_description` are LangAlt dicts comparing `x-default`;
    `dc_creator` is a Seq list; everything else is a plain string) -- the
    XmpInformation setters themselves do not infer a shape from the
    property name, so this dispatch is what keeps D2.1's own table honest.
    ``value=None`` clears the property (every setter below accepts
    ``Optional[...]``, verified against `pypdf` 6.16.2's own source)."""
    if field in ("title", "subject"):
        setattr(xmp, attr, {"x-default": value} if value is not None else None)
    elif field == "author":
        setattr(xmp, attr, [value] if value is not None else None)
    else:
        setattr(xmp, attr, value)


def _info_report_dict(reader: PdfReader) -> dict[str, str]:
    """D2.1's `info` half: `/Info` entries, `/`-prefix stripped, every value
    stringified. Deliberately NOT `_metadata()` above -- that helper feeds
    the already-published, golden-tested `info` verb and stays untouched by
    this spec; this is `meta get`'s own, slash-stripped shape."""
    raw = reader.metadata
    if raw is None:
        return {}
    return {str(key).lstrip("/"): str(value) for key, value in raw.items() if value is not None}


def _xmp_report_fields(reader: PdfReader) -> tuple[dict[str, object] | None, str | None]:
    """D2.1's `xmp` half plus the raw packet text -- `(None, None)` when the
    document carries no XMP packet at all."""
    try:
        xmp = reader.xmp_metadata
    # Malformed XMP is not a malformed document (mirrors `_xmp()` below).
    except Exception:
        return None, None
    if xmp is None:
        return None, None
    raw = _xmp(reader)  # the existing, pinned helper -- reused, not re-derived
    fields: dict[str, object] = {}
    for field, _info_name, xmp_attr in _ALIGNMENT:
        try:
            fields[field] = getattr(xmp, xmp_attr)
        except Exception:
            fields[field] = None
    return fields, raw


def _residual_surfaces(reader: PdfReader) -> dict[str, object]:
    """D2.4: the surfaces `--clear-all` does NOT clear, detected so they are
    REPORTED rather than merely disclaimed. Cheap, pypdf-only detection,
    exactly as D2.4 names it: `"/Metadata" in page`, `"/PieceInfo" in page`,
    `"/PieceInfo" in root`, an `/Annots` entry carrying `/T`,
    `/Names /EmbeddedFiles`, `/ID` in the trailer."""
    root: Any = reader.trailer["/Root"].get_object()
    page_xmp_pages: list[int] = []
    page_piece_info_pages: list[int] = []
    annotation_authors = 0
    for index, page in enumerate(reader.pages, start=1):
        if "/Metadata" in page:
            page_xmp_pages.append(index)
        if "/PieceInfo" in page:
            page_piece_info_pages.append(index)
        annots = page.get("/Annots")
        if annots is not None:
            for annot_ref in annots.get_object():
                annot = annot_ref.get_object()
                if "/T" in annot:
                    annotation_authors += 1
    doc_piece_info = "/PieceInfo" in root
    embedded_files = 0
    names = root.get("/Names")
    if names is not None:
        embedded_files_dict = names.get_object().get("/EmbeddedFiles")
        if embedded_files_dict is not None:
            names_array = embedded_files_dict.get_object().get("/Names")
            if names_array is not None:
                embedded_files = len(names_array.get_object()) // 2
    trailer_id = "/ID" in reader.trailer
    return {
        "page_xmp_pages": page_xmp_pages,
        "doc_piece_info": doc_piece_info,
        "page_piece_info_pages": page_piece_info_pages,
        "annotation_authors": annotation_authors,
        "embedded_files": embedded_files,
        "trailer_id": trailer_id,
    }


def _unlock_with_password(
    reader: PdfReader,
    *,
    password: Secret | None,
    path: str | None,
    message_no_password: str,
    message_wrong_password: str,
) -> None:
    """PDF-37 -- the empty password already failed. Try the supplied secret,
    if any, and raise a message that DIFFERS, byte for byte, between "none
    supplied" and "rejected" (AC6) -- the defect this spec exists to close.
    At `d03bee3` this file's four raise sites emitted the SAME message
    regardless of whether a password was ever given.

    THIS FILE (alongside ``pikepdf_structure.py``) is the only place
    permitted to call :meth:`Secret.reveal` -- widening
    ``tests/test_password_leaks.py::REVEAL_ALLOWLIST`` -- because this
    is the one place pypdf demands a plain ``str``. The value is passed
    straight into ``reader.decrypt(...)`` and never bound to a local that
    outlives the expression, never logged and never returned.

    Never clears *password*: the ops layer that resolved it
    (`ops/document_password.py`) may still need the same secret for a
    second engine call (`rasterize`/`ocr`'s raster pass, `text`/`tables`'
    own extraction engine) and owns its lifecycle end to end.

    Logs the resolution SOURCE (via the caller's already-resolved
    :class:`~pdf_toolkit.secret.Secret`, whose ``source`` is safe-to-log by
    construction) and whether verification succeeded -- the two facts X-403
    licenses and whose absence is the defect (AC14) -- and nothing else.
    """
    logger = get_logger("adapters.pypdf")
    if password is None:
        raise AuthError(message_no_password, path=path)
    unlocked = bool(reader.decrypt(password.reveal()))
    logger.debug("password resolved from %s; password_verified: %s", password.source, unlocked)
    if not unlocked:
        raise AuthError(message_wrong_password, path=path)


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
        password: Secret | None = None,
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
        except OSError as error:
            # PDF-26 §D3: already exit 1, now correctly CLASSIFIED -- an
            # unreadable source is `SourceUnreadableError`, not a generic
            # parse failure. The integer is unchanged.
            raise source_read_error(path, error) from error
        except ValueError as error:
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
                _unlock_with_password(
                    reader,
                    password=password,
                    path=str(path),
                    message_no_password=(
                        f"a user password is required to read this document; {PASSWORD_HINT}"
                    ),
                    message_wrong_password=(
                        f"the supplied password did not unlock this document; {PASSWORD_HINT}"
                    ),
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

    def open_document(self, path: Path, *, password: Secret | None = None) -> PypdfOpenDocument:
        """D10's read half — see :class:`PypdfOpenDocument` for the shape.

        Existence and directory checks are the caller's job (they need to know
        how many operands there were, per `ops/inspect.py`'s own precedent) --
        this method's own contract starts at "the path exists and is a file."
        """
        return PypdfOpenDocument(path, password=password)

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

    # -- PDF-14 (`meta get`/`meta set`), appended at the end of the class --- #

    def read_metadata(self, path: Path, *, password: Secret | None = None) -> MetadataFacts:
        """The `meta get` read (D2, D2.4)."""
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        if not path.exists():
            raise NoInputError("no such file", path=str(path))
        if path.is_dir():
            raise UsageError("expected a PDF file, not a directory", path=str(path))

        try:
            reader = PdfReader(str(path))
        except PdfReadError as error:
            raise FailureError(f"could not read PDF: {error}", path=str(path)) from error
        except OSError as error:
            # PDF-26 §D3: already exit 1, now correctly CLASSIFIED -- an
            # unreadable source is `SourceUnreadableError`, not a generic
            # parse failure. The integer is unchanged.
            raise source_read_error(path, error) from error
        except ValueError as error:
            raise FailureError(f"could not read PDF: {error}", path=str(path)) from error

        if reader.is_encrypted:
            # The empty user password, tried once -- same convention as
            # `read_document_info` above.
            try:
                unlocked = bool(reader.decrypt(""))
            except Exception as error:
                logger = get_logger("adapters.pypdf")
                logger.debug("%s: decrypt('') raised %s", path, error)
                unlocked = False
            if not unlocked:
                _unlock_with_password(
                    reader,
                    password=password,
                    path=str(path),
                    message_no_password=(
                        "a user password is required to read this document's metadata; "
                        f"{PASSWORD_HINT}"
                    ),
                    message_wrong_password=(
                        "the supplied password did not unlock this document's metadata; "
                        f"{PASSWORD_HINT}"
                    ),
                )

        try:
            info = _info_report_dict(reader)
            xmp_fields, xmp_raw = _xmp_report_fields(reader)
            residual = _residual_surfaces(reader)
        except PdfReadError as error:
            raise FailureError(f"could not read PDF: {error}", path=str(path)) from error
        except (KeyError, TypeError, ValueError, OSError) as error:
            raise FailureError(f"could not read PDF: {error}", path=str(path)) from error

        return MetadataFacts(info=info, xmp=xmp_fields, xmp_raw=xmp_raw, residual_surfaces=residual)

    def write_metadata(
        self,
        data: bytes,
        *,
        sets: Mapping[str, str],
        clears: Sequence[str],
        clear_all: bool,
        password: Secret | None = None,
    ) -> MetadataWriteOutcome:
        """The `meta set` write (D2.2/D2.3)."""
        from pypdf import PdfReader, PdfWriter
        from pypdf.errors import PdfReadError
        from pypdf.generic import NameObject, TextStringObject

        try:
            reader = PdfReader(io.BytesIO(data))
        except PdfReadError as error:
            raise FailureError(f"could not read PDF: {error}") from error
        except (OSError, ValueError) as error:
            raise FailureError(f"could not read PDF: {error}") from error

        if reader.is_encrypted:
            try:
                unlocked = bool(reader.decrypt(""))
            except Exception:
                unlocked = False
            if not unlocked:
                _unlock_with_password(
                    reader,
                    password=password,
                    path=None,
                    message_no_password=(
                        "a user password is required to write this document's metadata; "
                        f"{PASSWORD_HINT}"
                    ),
                    message_wrong_password=(
                        "the supplied password did not unlock this document's metadata; "
                        f"{PASSWORD_HINT}"
                    ),
                )

        # `clone_from=reader` -- not `writer.append(reader)` -- is what makes
        # D2.3's guarantee cheap: it clones EVERY `/Info` key with its
        # ORIGINAL PdfObject type intact (verified: a `/Trapped` NameObject
        # round-trips as a NameObject, not the string `"/False"` the public
        # `PdfWriter.metadata = value` setter would produce via
        # `create_string_object(str(value))`) and carries the XMP packet
        # across verbatim. Every key this method does not name in
        # `sets`/`clears` is therefore untouched BY CONSTRUCTION -- there is
        # no copy-then-compare step that could miss one.
        try:
            writer = PdfWriter(clone_from=reader)
        except PdfReadError as error:
            raise FailureError(f"could not read PDF: {error}") from error

        xmp = writer.xmp_metadata
        had_xmp = xmp is not None

        if clear_all:
            # D2.3's documented, commented deviation: the public setter
            # cannot preserve non-string types AND cannot remove a key, so
            # the writer's own `/Info` dictionary is cleared directly.
            # `.clear()` leaves an EMPTY dictionary object rather than
            # removing `/Info` from the trailer entirely -- AC7 accepts
            # either ("empty/absent"), and an empty dictionary is the
            # behaviour `PdfWriter.metadata = None` itself already produces
            # elsewhere in this codebase's own conventions.
            writer_info: Any = writer._info  # noqa: SLF001 -- see above; `Any` sidesteps
            # the stub's `DictionaryObject | None` -- `PdfWriter(clone_from=...)`
            # always populates `_info` (verified against pypdf 6.16.2's own
            # `clone_from` path), so the `None` arm is unreachable here.
            writer_info.get_object().clear()
            writer.xmp_metadata = None
            wrote_xmp = had_xmp
        else:
            writer_info = writer._info  # noqa: SLF001 -- see above
            info: Any = writer_info.get_object()
            for field, value in sets.items():
                _, info_name, xmp_attr = _alignment_row(field)
                info[NameObject("/" + info_name)] = TextStringObject(value)
                if xmp is not None:
                    _set_xmp_field(xmp, xmp_attr, field, value)
            for field in clears:
                _, info_name, xmp_attr = _alignment_row(field)
                key = NameObject("/" + info_name)
                if key in info:
                    del info[key]
                if xmp is not None:
                    _set_xmp_field(xmp, xmp_attr, field, None)
            if xmp is not None:
                writer.xmp_metadata = xmp
            wrote_xmp = xmp is not None and bool(sets or clears)

        out_buffer = io.BytesIO()
        writer.write(out_buffer)
        return MetadataWriteOutcome(output=out_buffer.getvalue(), wrote_xmp=wrote_xmp)

    # -- PDF-14 (`watermark`/`stamp`), appended at the end of the class ---- #

    def composite_layer(
        self,
        writer: PypdfStructureWriter,
        *,
        layer: bytes,
        pages: Sequence[int],
        position: str,
    ) -> CompositeOutcome:
        """The `watermark`/`stamp`/`ocr` compositing primitive (D3/D4).

        `PDF-23` migration: *writer* is already-appended (the caller's own
        `new_writer()` + `append_pages()`, done BEFORE this is ever called),
        so every merge below lands on a page already attached to a
        `PdfWriter` -- `replace_contents`'s WRITER branch, which emits no
        `DeprecationWarning` (AC12), unlike the READER-attached shape this
        method used before B-092/B-097.
        """
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
        from pypdf.generic import DecodedStreamObject, IndirectObject, NameObject

        try:
            layer_reader = PdfReader(io.BytesIO(layer))
            layer_page = layer_reader.pages[0]
        except (PdfReadError, IndexError, OSError, ValueError) as error:
            raise FailureError(f"could not read the composite layer: {error}") from error

        pdf_writer = writer._writer  # noqa: SLF001 -- same adapter's own
        # internal pair, mirroring `PypdfStructureWriter.append_pages` above.
        over = position == "overlay"

        # Design D4.1 -- the sharing predicate, a SNAPSHOT taken once before
        # any mutation below: the set of `/Contents` object numbers
        # referenced by MORE THAN ONE of the writer's own pages, from the
        # RAW (unresolved) entry -- `raw_get` never dereferences, which is
        # what makes the object's IDENTITY, not its content, the thing
        # compared. A direct `/Contents` ARRAY has no object number of its
        # own and is therefore never a member of this map (D4.5: that shape
        # already scopes correctly on its own and is deliberately left
        # alone -- `replace_contents`'s array branch re-registers fresh
        # element objects rather than substituting one shared object).
        contents_refcount: dict[int, int] = {}
        for wpage in pdf_writer.pages:
            raw = wpage.raw_get("/Contents") if "/Contents" in wpage else None
            if isinstance(raw, IndirectObject):
                contents_refcount[raw.idnum] = contents_refcount.get(raw.idnum, 0) + 1
        shared_object_numbers = frozenset(
            number for number, count in contents_refcount.items() if count > 1
        )

        composited: list[int] = []
        blank: list[int] = []
        copied: list[int] = []
        for number in pages:
            page = pdf_writer.pages[number - 1]
            current_contents = page.get_contents()
            if current_contents is None:
                blank.append(number)
            else:
                raw = page.raw_get("/Contents") if "/Contents" in page else None
                if isinstance(raw, IndirectObject) and raw.idnum in shared_object_numbers:
                    # Design D4.2 -- copy-on-write: a FRESH stream object
                    # carrying this SELECTED page's own current decoded
                    # content, registered on the writer, and pointed at
                    # BEFORE the merge -- so the merge below never mutates
                    # the object number a SIBLING page still depends on.
                    # An unselected page is never visited at all.
                    fresh = DecodedStreamObject()
                    fresh.set_data(current_contents.get_data())
                    page[NameObject("/Contents")] = pdf_writer._add_object(fresh)  # noqa: SLF001
                    copied.append(number)
            # `get_contents()` re-derives a FRESH `ContentStream` from the
            # underlying object on every call (verified against pypdf
            # 6.16.2's own source) rather than caching a mutated one, which
            # is what makes reusing the SAME `layer_page` across every
            # selected page safe: `merge_page` never mutates its `page2`
            # argument, only `self`.
            page.merge_page(layer_page, over=over)
            composited.append(number)
        return CompositeOutcome(
            pages_composited=tuple(composited),
            pages_copied=tuple(copied),
            blank_pages=tuple(blank),
        )


class PypdfOpenDocument:
    """D10 — one already-open document: page count, top-level outline.

    Opens its own file handle (never lets pypdf open the path itself) so the
    handle this class owns is closeable deterministically on ``__exit__``
    rather than left to pypdf's own lifecycle, which does not expose one.
    """

    def __init__(self, path: Path, *, password: Secret | None = None) -> None:
        self._path = path
        self._password = password
        self._handle: BinaryIO | None = None
        self._reader: PdfReader | None = None

    def __enter__(self) -> PypdfOpenDocument:
        from pypdf import PdfReader
        from pypdf.errors import FileNotDecryptedError, PdfReadError

        if not self._path.exists():
            raise NoInputError("no such file", path=str(self._path))
        if self._path.is_dir():
            raise UsageError("expected a PDF file, not a directory", path=str(self._path))

        try:
            # PDF-26 §D3. This `open` sat OUTSIDE the try below -- three lines
            # above a clause that already caught `OSError` -- so a
            # `PermissionError` here walked out of the product as a raw
            # traceback and exited 1 as an UNHANDLED CRASH. That was `merge
            # <unreadable.pdf> <good.pdf>`'s "correct" exit code, and it is why
            # B-057's "merge already classifies this" was wrong.
            handle = open(self._path, "rb")  # closed in __exit__, kept for lazy page reads
        except OSError as error:
            raise source_read_error(self._path, error) from error
        try:
            reader = PdfReader(handle)
            # [B-078] pypdf raises FileNotDecryptedError LAZILY -- not at the
            # PdfReader() construction above, but on the first `.pages` access,
            # which every caller of this class reaches only through `page_count`
            # or `top_level_outline`, both outside the try this method used to
            # have. Forcing that first access HERE, inside the one guard this
            # class already has, is what makes AuthError fire in exactly ONE
            # place for every consumer (`merge`, `split`, `extract`, `delete`,
            # `rotate`, `reorder`, `rasterize`, `text`, `tables`, `compress
            # --pages`) instead of leaking an unhandled traceback past whichever
            # property happened to touch `.pages` first.
            len(reader.pages)
        except FileNotDecryptedError as error:
            try:
                _unlock_with_password(
                    reader,
                    password=self._password,
                    path=str(self._path),
                    message_no_password=(
                        f"a password is required to open this document; {PASSWORD_HINT}"
                    ),
                    message_wrong_password=(
                        f"the supplied password did not unlock this document; {PASSWORD_HINT}"
                    ),
                )
            except AuthError as unlock_error:
                handle.close()
                raise unlock_error from error
        except PdfReadError as error:
            handle.close()
            raise FailureError(f"could not read PDF: {error}", path=str(self._path)) from error
        except (OSError, ValueError) as error:
            handle.close()
            raise FailureError(f"could not read PDF: {error}", path=str(self._path)) from error
        self._reader = reader
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
