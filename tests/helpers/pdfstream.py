"""Extract an image XObject's **stored** stream out of a PDF — PDF-10's
acceptance signal, and the one place any test is allowed to ask for it.

Why this module exists at all
-----------------------------
``compose``'s guarantee is byte-level, not visual: a JPEG already *is* a
DCT-compressed bitstream and PDF's ``/DCTDecode`` filter stores exactly that, so
a correct implementation copies the compressed bytes in untouched. A naive one
decodes and re-encodes, which is silently lossy and produces a page that looks
identical. "The output looks the same" is therefore explicitly **not** the
check, and the only way to tell the two apart is to read the stored bytes back
out and compare them with the input file.

That is easy to get subtly wrong in the direction that hides a defect, so this
module pins the accessors rather than leaving each test to pick one:

* **The bytes come from the XObject, not from a convenience accessor.**
  ``page.images[i]`` exists to hand you a *loadable image*, not the bytes on
  disk, and it is free to normalise. It may be used to corroborate (e.g. that a
  page has exactly one image); it is never the evidence.
* ``raw`` is the stream **exactly as stored**, transport filters intact.
* ``dct_payload`` is ``raw`` with every non-DCT filter undone — so it is the
  JPEG bitstream on both a bare ``/DCTDecode`` chain and an
  ``("/ASCII85Decode", "/DCTDecode")`` one, and ``None`` when the object is not
  DCT at all. A test comparing ``dct_payload`` against the input file therefore
  detects a re-encode without being fooled by a transport layer, and without
  being weakened into accepting one.

Pinned to pypdf 6.16.2
-----------------------
Measured on that version, and the version is named here so an upgrade that
moves these accessors is a loud failure rather than a quiet weakening:

* ``obj.get_data()`` leaves ``/DCTDecode`` **undecoded** and returns the JPEG
  bytes verbatim; on the A85 pair it undoes only the ASCII85 layer and returns
  those same bytes. It already has exactly ``dct_payload``'s semantics.
* the **stored** bytes (A85 layer intact) have no public accessor, so ``raw``
  comes from the private ``obj._data``. That is the single private access in
  this spec, it is confined to this test helper, and the pinned version above is
  what makes it safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

__all__ = ["EmbeddedStream", "PYPDF_PINNED_VERSION", "embedded_image_streams", "page_media_box"]

#: The version every accessor below was measured against.
PYPDF_PINNED_VERSION = "6.16.2"

_DCT = "/DCTDecode"


@dataclass(frozen=True)
class EmbeddedStream:
    """One image XObject, reduced to what an acceptance test may assert on."""

    name: str
    """The resource key, e.g. ``/FormXob.<digest>``. Renderers de-duplicate
    identical images by digest, so composing one file twice yields ONE XObject
    referenced from two pages — which is why every assertion in this spec is
    **per page** and never a global XObject count."""

    filters: tuple[str, ...]
    """``("/DCTDecode",)`` or ``("/ASCII85Decode", "/DCTDecode")``, in stream
    order. A single name normalises to a one-tuple."""

    raw: bytes
    """The stream EXACTLY as stored, before any filter is undone."""

    dct_payload: bytes | None
    """``raw`` with every non-DCT filter undone; ``None`` when ``/DCTDecode`` is
    absent. This is what a byte-identity assertion compares against."""

    width: int
    height: int
    colorspace: str | None
    decode: tuple[float, ...] | None
    """The ``/Decode`` array, e.g. the Adobe CMYK inversion
    ``(1, 0, 1, 0, 1, 0, 1, 0)``, or ``None`` when the object carries none."""


def _filters(obj: object) -> tuple[str, ...]:
    raw = obj.get("/Filter")  # type: ignore[attr-defined]
    if raw is None:
        return ()
    if isinstance(raw, list):
        return tuple(str(entry) for entry in raw)
    return (str(raw),)


def _decode(obj: object) -> tuple[float, ...] | None:
    raw = obj.get("/Decode")  # type: ignore[attr-defined]
    if raw is None:
        return None
    return tuple(float(entry) for entry in raw)


def embedded_image_streams(pdf_path: Path, page_index: int) -> list[EmbeddedStream]:
    """Every image XObject on ``pages[page_index]``, in resource-key order."""
    page = PdfReader(str(pdf_path)).pages[page_index]
    resources = page.get("/Resources")
    if resources is None:
        return []
    xobjects = resources.get_object().get("/XObject")
    if xobjects is None:
        return []
    container = xobjects.get_object()

    found: list[EmbeddedStream] = []
    for key in container:
        obj = container[key].get_object()
        if str(obj.get("/Subtype")) != "/Image":
            continue
        filters = _filters(obj)
        colorspace = obj.get("/ColorSpace")
        found.append(
            EmbeddedStream(
                name=str(key),
                filters=filters,
                raw=bytes(obj._data),  # noqa: SLF001 - see the module docstring
                dct_payload=bytes(obj.get_data()) if _DCT in filters else None,
                width=int(obj["/Width"]),
                height=int(obj["/Height"]),
                colorspace=str(colorspace) if colorspace is not None else None,
                decode=_decode(obj),
            )
        )
    return found


def page_media_box(pdf_path: Path, page_index: int) -> tuple[float, float]:
    """``(width, height)`` in points, read back out of the produced file.

    Every dimensional assertion in this spec measures the artefact rather than
    re-reading a number out of the code that produced it — the trap PDF-09 found
    live, where an intent-based assertion missed a one-pixel defect.
    """
    box = PdfReader(str(pdf_path)).pages[page_index].mediabox
    return float(box.width), float(box.height)
