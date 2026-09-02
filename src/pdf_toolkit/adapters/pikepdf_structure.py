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

**PDF-12 real implementations (`compress`/`repair`/`linearize`).** The
conventional one-call PDF compressor is AGPL-3.0+ and excluded by
``PLAN.md`` §7.2 — object streams plus stream recompression via this
adapter's own ``compress()``, over libqpdf, is the replacement, not a
workaround. Every operation here works entirely over ``io.BytesIO``: input
bytes in, candidate bytes out, and the one filesystem write stays
``safety.AtomicWriter``'s alone (this module never opens a file itself).
Recovery warnings for ``repair`` come from ``pikepdf.Pdf.get_warnings()`` —
never a ``qpdf`` CLI shell-out, which HC-1 forbids even for a convenience.
"""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import TYPE_CHECKING, Final

from pdf_toolkit.adapters import AdapterProbe, package_probe
from pdf_toolkit.errors import AuthError, FailureError
from pdf_toolkit.output.logging import get_logger
from pdf_toolkit.ports.structure import (
    PASSWORD_HINT,
    PERMISSION_TOKENS,
    CompressOutcome,
    EncryptionFacts,
    ImageXObjectFacts,
    RepairOutcome,
    StructuralFacts,
    algorithm_name,
)
from pdf_toolkit.secret import Secret

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    import pikepdf

__all__ = ["ADAPTER", "CAPABILITY_SUMMARY", "PikepdfStructureAdapter"]

#: `Pdf.get_warnings()` messages are prefixed with the stream repr, e.g.
#: ``"stream <_io.BytesIO object at 0x...>: file is damaged"`` or
#: ``"stream <_io.BytesIO object at 0x...> (object 5 0, offset 439): EOF..."``.
#: The address is per-process noise, never a fact about the document, so it is
#: stripped before a warning reaches `OperationResult.warnings` — otherwise
#: every repair report would carry a non-deterministic memory address.
_WARNING_PREFIX_RE: Final = re.compile(r"^\S+ <[^>]+>(?:\s*\([^)]*\))?:\s*(.*)$")

_NAME: Final[str] = "pikepdf"
_DISTRIBUTION: Final[str] = "pikepdf"
_MODULE: Final[str] = "pikepdf"

_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {"linearized", "repair", "linearize", "object-streams", "robust-encryption"}
)

#: Rendered into ``StructureEngine``'s ``detail`` so ``doctor`` states what the
#: secondary is *for*, not merely that it exists.
CAPABILITY_SUMMARY: Final[str] = "repair, linearize, object-streams, encryption"

#: PDF-13 -- `PLAN.md` §5.7's `--allow` vocabulary mapped to libqpdf's own
#: permission fields. Verified against `pikepdf.Permissions()._fields` at
#: pikepdf 10.12.0 / libqpdf 12.3.2 before it was written, not recalled from a
#: document. `print-highres` also implies `print` (`print_lowres`): a reader
#: that may print at full resolution may obviously print at low resolution,
#: and the format has no spelling for "high but not low".
_PERMISSION_FIELDS: Final[dict[str, str]] = {
    "accessibility": "accessibility",
    "annotate": "modify_annotation",
    "assemble": "modify_assembly",
    "copy": "extract",
    "forms": "modify_form",
    "modify": "modify_other",
    "print": "print_lowres",
    "print-highres": "print_highres",
}

#: ``EncryptionInfo.stream_method`` -> the ``/CFM`` spelling
#: :data:`~pdf_toolkit.ports.structure.ENCRYPTION_ALGORITHMS` is keyed by.
#: ``none`` is /V 1 and 2, which predate crypt filters; ``unknown`` is absent
#: on purpose, so an unrecognised handler yields ``None`` and a warning rather
#: than a guess.
_CFM_BY_STREAM_METHOD: Final[dict[str, str]] = {
    "none": "",
    "rc4": "/V2",
    "aes": "/AESV2",
    "aesv3": "/AESV3",
}


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

    def compress(self, data: bytes) -> CompressOutcome:
        """The `"object-streams"` capability (D-12.1/D-12.2).

        Always runs the same structural pass -- ``compress``'s bare form and
        its `--lossless` form differ only in whether `ops/optimize.py` acts
        on the returned :class:`StructuralFacts`, never in what this method
        does. ``before``/``after`` are computed unconditionally: both are
        decode-free (D-12.3), so the cost is paid whether or not the caller
        enforces the guarantee.
        """
        import pikepdf

        try:
            with pikepdf.Pdf.open(io.BytesIO(data)) as pdf:
                before = _structural_facts(pdf)
                out_buffer = io.BytesIO()
                pdf.save(
                    out_buffer,
                    object_stream_mode=pikepdf.ObjectStreamMode.generate,
                    compress_streams=True,
                    recompress_flate=True,
                    normalize_content=False,
                )
        except pikepdf.PasswordError as error:
            raise AuthError(
                f"a password is required to compress this document; {PASSWORD_HINT}"
            ) from error
        except pikepdf.PdfError as error:
            raise FailureError(f"could not open PDF for compression: {error}") from error

        output = out_buffer.getvalue()
        with pikepdf.Pdf.open(io.BytesIO(output)) as candidate:
            after = _structural_facts(candidate)
        return CompressOutcome(output=output, before=before, after=after)

    def repair(self, data: bytes) -> RepairOutcome:
        """The `"repair"` capability (D-12.4): libqpdf's own recovery parser,
        via `pikepdf.Pdf.open(..., attempt_recovery=True)`.

        Recovery warnings come from `Pdf.get_warnings()` -- the library, never
        a `qpdf` CLI shell-out (HC-1, `decision.md` X-84). "Before" is the
        structure pikepdf's recovery pass already reconstructed (the damaged
        file's *own* pre-recovery counts are unknowable without a successful
        parse -- if they were knowable the file would not need recovery);
        "after" is the resaved output, so the delta this method reports is
        honest about what the SAVE step changed, never a fabricated
        before-the-damage number.
        """
        import pikepdf

        try:
            pdf = pikepdf.Pdf.open(io.BytesIO(data), attempt_recovery=True)
        except pikepdf.PasswordError as error:
            raise AuthError(
                f"a password is required to repair this document; {PASSWORD_HINT}"
            ) from error
        except pikepdf.PdfError as error:
            raise FailureError(f"could not recover this document: {error}") from error

        try:
            page_count_before = len(pdf.pages)
            object_count_before = len(pdf.objects)
            warnings = tuple(_clean_warning(raw) for raw in pdf.get_warnings())
            xref_reconstructed = any("reconstruct" in warning.lower() for warning in warnings)
            out_buffer = io.BytesIO()
            pdf.save(out_buffer)
        finally:
            pdf.close()

        output = out_buffer.getvalue()
        with pikepdf.Pdf.open(io.BytesIO(output)) as saved:
            page_count_after = len(saved.pages)
            object_count_after = len(saved.objects)

        return RepairOutcome(
            output=output,
            warnings=warnings,
            page_count_before=page_count_before,
            page_count_after=page_count_after,
            object_count_before=object_count_before,
            object_count_after=object_count_after,
            xref_reconstructed=xref_reconstructed,
        )

    def linearize(self, data: bytes) -> bytes:
        """The `"linearize"` capability (D-12.6).

        Verifies internally -- reopen the candidate, `is_linearized` true and
        `check_linearization()` reports no problems -- BEFORE returning, so a
        failed verification never reaches `AtomicWriter`: nothing is written
        and the caller sees exit 1 (D-12.6 check 1, run at runtime).
        """
        import pikepdf

        try:
            with pikepdf.Pdf.open(io.BytesIO(data)) as pdf:
                out_buffer = io.BytesIO()
                pdf.save(out_buffer, linearize=True)
        except pikepdf.PasswordError as error:
            raise AuthError(
                f"a password is required to linearize this document; {PASSWORD_HINT}"
            ) from error
        except pikepdf.PdfError as error:
            raise FailureError(f"could not open PDF for linearization: {error}") from error

        output = out_buffer.getvalue()
        verified = False
        with pikepdf.Pdf.open(io.BytesIO(output)) as candidate:
            if candidate.is_linearized:
                try:
                    verified = bool(candidate.check_linearization(io.StringIO()))
                except RuntimeError:
                    verified = False
        if not verified:
            raise FailureError("linearization did not verify: the saved output is not linearized")
        return output

    # -- PDF-13: the `"robust-encryption"` capability ---------------------- #
    #
    # THIS IS THE ONLY FILE PERMITTED TO CALL `Secret.reveal()`
    # (`PLAN.md` §5.7; enforced by an allowlist walk in
    # `tests/test_password_leaks.py`). Every `reveal()` below sits at the
    # exact point where libqpdf demands a `str`, is passed straight into the
    # engine call, and is never bound to a local that outlives the
    # expression, never logged, never formatted and never returned.
    #
    # No cryptography is implemented here or anywhere in this product: key
    # derivation, ciphers and password comparison are libqpdf's, reached
    # through pikepdf. A hand-rolled anything in this path is an automatic
    # rejection (`PLAN.md` §5.7, this spec's Non-goals).

    def read_encryption(self, data: bytes, password: Secret | None) -> EncryptionFacts:
        """The read half: what this document's security handler says.

        **Never raises on a wrong or absent password.** "The credential did
        not open it" is a fact about the document, reported as
        ``unlocked=False`` -- because the one caller that has to tell
        `encrypt`'s already-encrypted refusal (exit 5) apart from `decrypt`'s
        wrong-password refusal (exit 6) cannot do so from a single exception
        type.
        """
        import pikepdf

        logger = get_logger("adapters.pikepdf")
        try:
            pdf = pikepdf.Pdf.open(io.BytesIO(data), password=password.reveal() if password else "")
        except pikepdf.PasswordError:
            # Encrypted, and this credential is not the one. Nothing about the
            # attempt is logged: not the password, not its length, not its
            # source -- the caller owns the (safe) source label.
            return EncryptionFacts(
                encrypted=True,
                unlocked=False,
                algorithm=None,
                revision=None,
                key_bits=None,
                granted=(),
                permissions_readable=False,
            )
        except pikepdf.PdfError as error:
            raise FailureError(f"could not read this document's encryption: {error}") from error

        with pdf:
            if not pdf.is_encrypted:
                return EncryptionFacts(
                    encrypted=False,
                    unlocked=True,
                    algorithm=None,
                    revision=None,
                    key_bits=None,
                    granted=tuple(PERMISSION_TOKENS),
                    permissions_readable=True,
                )
            info = pdf.encryption
            method = _CFM_BY_STREAM_METHOD.get(info.stream_method.name)
            algorithm = (
                algorithm_name(int(info.V), method, int(info.bits)) if method is not None else None
            )
            if algorithm is None:
                logger.warning(
                    "unrecognised encryption dictionary (/V %s, method %s, %s-bit); "
                    "reporting the algorithm as null rather than guessing",
                    info.V,
                    info.stream_method.name,
                    info.bits,
                )
            allow = pdf.allow
            granted = tuple(
                sorted(
                    token for token, field in _PERMISSION_FIELDS.items() if getattr(allow, field)
                )
            )
            return EncryptionFacts(
                encrypted=True,
                unlocked=True,
                algorithm=algorithm,
                revision=int(info.R),
                key_bits=int(info.bits),
                granted=granted,
                permissions_readable=True,
            )

    def encrypt(
        self,
        data: bytes,
        *,
        owner: Secret,
        user: Secret | None,
        allow: frozenset[str],
        legacy: bool,
    ) -> bytes:
        """The write half: AES-256 (R6) by default, RC4-128 (R4) under ``legacy``.

        ``metadata=`` is forced off in the legacy shape because libqpdf
        refuses to encrypt metadata without AES (``ValueError: Cannot encrypt
        metadata unless AES encryption is enabled``) -- measured, not assumed.
        The caller's `--legacy` warning states that consequence rather than
        letting it be a surprise.
        """
        import pikepdf

        permissions = pikepdf.Permissions(
            **{field: (token in allow) for token, field in _PERMISSION_FIELDS.items()}
        )
        try:
            with pikepdf.Pdf.open(io.BytesIO(data)) as pdf:
                out_buffer = io.BytesIO()
                pdf.save(
                    out_buffer,
                    encryption=pikepdf.Encryption(
                        owner=owner.reveal(),
                        user=user.reveal() if user is not None else "",
                        R=4 if legacy else 6,
                        allow=permissions,
                        aes=not legacy,
                        metadata=not legacy,
                    ),
                )
        except pikepdf.PasswordError as error:
            raise AuthError(
                f"a password is required to open this document; {PASSWORD_HINT}"
            ) from error
        except pikepdf.PdfError as error:
            raise FailureError(f"could not encrypt this document: {error}") from error
        return out_buffer.getvalue()

    def decrypt(self, data: bytes, *, password: Secret) -> bytes:
        """The removal half: saving without ``encryption=`` writes plaintext.

        `PLAN.md` §5.6's third exit-6 sub-case (opened with the user password
        where owner-level access is required) is **not simulated here**:
        libqpdf grants full access to any credential that opens the document
        and does not itself enforce the permission bits, so a check invented
        at this layer would be a claim the format does not support -- the
        same security-theatre standard §9.2 applies to redaction. If a future
        engine reports it, it maps to :class:`AuthError` beside the wrong
        password below.
        """
        import pikepdf

        try:
            with pikepdf.Pdf.open(io.BytesIO(data), password=password.reveal()) as pdf:
                out_buffer = io.BytesIO()
                pdf.save(out_buffer)
        except pikepdf.PasswordError as error:
            raise AuthError(
                "the supplied password did not open this document",
                redacted=True,
            ) from error
        except pikepdf.PdfError as error:
            raise FailureError(f"could not decrypt this document: {error}") from error
        return out_buffer.getvalue()


def _filter_tuple(obj: pikepdf.Object) -> tuple[str, ...]:
    """`/Filter` normalized to a tuple -- a single `Name` or an `Array` of them."""
    import pikepdf

    filt = obj.get("/Filter")
    if filt is None:
        return ()
    if isinstance(filt, pikepdf.Array):
        return tuple(str(entry) for entry in filt)
    return (str(filt),)


def _colorspace_name(colorspace: object) -> str | None:
    """A stable string for `/ColorSpace` -- a `Name`, an `Array` (e.g.
    `[/ICCBased 5 0 R]`, `[/Indexed ...]`), or absent.

    **Verified false-positive trap, found against a real 482-page sample
    (`decision.md`-style finding, PDF-12's own D-12.3 warning made concrete):
    `str()` on an `/ICCBased` colour space includes the embedded ICC profile
    STREAM's own representation, which carries its compressed `/Length`.**
    `recompress_flate=True` legitimately re-encodes that Flate stream to a
    different byte length with byte-identical decompressed content --
    exactly the class of false-positive D-12.3's own docstring warns
    against for image data, recurring one level down in the colour-space
    dictionary. So this function reduces an `/ICCBased` array to its family
    name plus `/N` (component count) and `/Alternate`, never the stream's
    own bytes or length -- comparison-only, and it is what D-12.3's
    equality check actually needs: *is this the same kind of colour space*,
    not *is this stream's compression identical*.
    """
    import pikepdf

    if colorspace is None:
        return None
    if not isinstance(colorspace, pikepdf.Array):
        return str(colorspace)
    if len(colorspace) == 0:
        return "[]"
    family = str(colorspace[0])
    if family == "/ICCBased" and len(colorspace) > 1:
        profile = colorspace[1]
        components = profile.get("/N") if hasattr(profile, "get") else None
        alternate = profile.get("/Alternate") if hasattr(profile, "get") else None
        return f"{family}(N={components},Alternate={alternate})"
    return family


def _image_facts(obj: pikepdf.Object) -> ImageXObjectFacts:
    filters = _filter_tuple(obj)
    width = int(obj.get("/Width", 0) or 0)
    height = int(obj.get("/Height", 0) or 0)
    colorspace = _colorspace_name(obj.get("/ColorSpace"))
    bpc_raw = obj.get("/BitsPerComponent")
    bits_per_component = int(bpc_raw) if bpc_raw is not None else None
    dct_sha256 = (
        hashlib.sha256(obj.read_raw_bytes()).hexdigest() if "/DCTDecode" in filters else None
    )
    return ImageXObjectFacts(
        filters=filters,
        width=width,
        height=height,
        colorspace=colorspace,
        bits_per_component=bits_per_component,
        dct_sha256=dct_sha256,
    )


def _structural_facts(pdf: pikepdf.Pdf) -> StructuralFacts:
    """Page count plus every image XObject's facts, in page then name order --
    a stable, deterministic ordering so two structurally-equal documents
    compare equal regardless of internal object numbering."""
    images: list[ImageXObjectFacts] = []
    for page in pdf.pages:
        found = page.get_images()
        for name in sorted(found):
            images.append(_image_facts(found[name]))
    return StructuralFacts(page_count=len(pdf.pages), images=tuple(images))


def _clean_warning(raw: str) -> str:
    """Strip `Pdf.get_warnings()`'s `stream <object at 0x...>: ` prefix.

    The address is per-process noise, not a fact about the document -- left
    in, every repair report would carry a non-deterministic memory address.
    """
    match = _WARNING_PREFIX_RE.match(raw)
    return match.group(1) if match else raw


# There is deliberately NO `read_document_info` here, and no stub raising
# `NotImplementedError`. The port-extension rule is that an adapter declares only
# what it really does: a later spec that needs pikepdf to perform a full read
# adds the working method beside `is_linearized`. A placeholder would type-check,
# satisfy the Protocol, and fail at runtime -- which is the whole failure mode the
# capability tokens exist to prevent.

ADAPTER: Final[PikepdfStructureAdapter] = PikepdfStructureAdapter()
