"""``StructureEngine`` primary adapter — pypdf.

pypdf is the default structure backend: pure Python, BSD-3-Clause, and the one
that reads a document's shape without pulling a C library into the process.
``pikepdf_structure`` is the capability-selected secondary for the things qpdf
does better (repair, linearization, object streams, robust encryption).

Every pypdf import in this file is **function-local**, so importing this module
costs nothing and ``doctor`` can load all eight adapters inside the startup
budget. That is a rule, not an optimisation: ``PLAN.md`` §12 R-13 is asserted by
a test that fails if importing ``cli.main`` leaves an engine in ``sys.modules``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pdf_toolkit.adapters import AdapterProbe, package_probe
from pdf_toolkit.errors import AuthError, FailureError
from pdf_toolkit.models import DocumentInfo, PageInfo
from pdf_toolkit.output.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from pypdf import PdfReader

__all__ = ["ADAPTER", "PypdfStructureAdapter"]

_NAME: Final[str] = "pypdf"
_DISTRIBUTION: Final[str] = "pypdf"
_MODULE: Final[str] = "pypdf"

#: What this adapter claims it can do. ``ports.require(..., capability=...)``
#: selects on these tokens, so they are a contract between adapters and the
#: registry rather than documentation.
_CAPABILITIES: Final[frozenset[str]] = frozenset({"read", "metadata", "pages"})

#: The ONE encryption-algorithm map, keyed by ``(/V, /CFM, key-length-in-bits)``
#: from the standard security handler's encryption dictionary. PDF-13 extends it
#: **here** and nowhere else; a second copy is how two verbs start disagreeing
#: about what a file is encrypted with.
#:
#: ``/CFM`` is ``""`` for /V 1 and 2, which predate crypt filters. A lookup that
#: misses yields ``None`` plus a stderr warning — never a guess.
_ALGORITHM_MAP: Final[dict[tuple[int, str, int], str]] = {
    (1, "", 40): "RC4-40",
    (2, "", 40): "RC4-40",
    (2, "", 128): "RC4-128",
    (4, "/V2", 40): "RC4-40",
    (4, "/V2", 128): "RC4-128",
    (4, "/AESV2", 128): "AES-128",
    (5, "/AESV3", 256): "AES-256",
}

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
    algorithm = _ALGORITHM_MAP.get((version, method, length))
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
                    "--password-file PATH (or --password -)",
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


#: The module-level singleton the port resolves to. A singleton rather than the
#: module itself so ``mypy --strict`` structurally checks it against the
#: ``StructureEngine`` Protocol at the seam in ``ports/structure.py``.
ADAPTER: Final[PypdfStructureAdapter] = PypdfStructureAdapter()
