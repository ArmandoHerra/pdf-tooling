"""``page_tree_digest`` — the honest round-trip comparison for PDF-13.

Top level, mirroring `tests/corpus.py`, because three test modules consume it.

**The claim this helper exists to make precise.** ``encrypt`` then ``decrypt``
cannot produce a byte-identical *file*, and this product never claims one:
``/ID``, ``/Encrypt``, the trailer, the cross-reference table, object
numbering and ``/Producer`` all legitimately change. The narrower claim is
true and is what gets asserted: **the page tree round-trips byte for byte.**

Per page, in this order:

1. the **decoded** content-stream bytes, coalesced across a ``/Contents``
   array — decoded, because a re-save may legitimately re-compress a Flate
   stream to different bytes with identical content;
2. the page dictionary rendered as sorted ``(key, value-token)`` pairs,
   **excluding ``/Parent``** (and ``/P``, its annotation-level twin), which
   point at nodes whose object ids legitimately change — and excluding
   ``/Contents``, whose bytes are already hashed by (1) and whose *encoding*
   is not a fact about the page (see below);
3. every image XObject reachable from the page's ``/Resources``, as **raw**
   (undecoded) stream bytes, in resource-name order — raw, because an image's
   compressed bytes are exactly what must not change.

``/Length`` is excluded from every rendered dictionary for the same reason
(1) decodes: it is a property of the encoding, not of the page.

**The ``/Contents`` exclusion is measured, not defensive.** reportlab writes a
content stream filtered ``[/ASCII85Decode, /FlateDecode]``; libqpdf resaves it
as plain ``/FlateDecode``. The DECODED bytes are byte-identical either way
(verified: both sides hash to the same content digest), so including the
content stream's own dictionary in the page token would fail a round trip that
preserved every byte of the page — the false-positive class
``adapters/pikepdf_structure.py::_colorspace_name`` documents one level down.
The content itself is not weakened by this: it is hashed in full by (1).

**This comparison must not be weakened into "page count matches" or
"extracted text matches."** Both pass on a re-encoded document and would
silently retire the only structural guarantee this verb pair offers.
``tests/integration/test_crypto_roundtrip.py`` carries the negative control
that proves this one can fail.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Final

import pikepdf

__all__ = ["page_tree_digest"]

#: Keys whose values point back up the tree. Their object ids legitimately
#: change across a save, so including them would make every round-trip differ.
_SKIP_KEYS: Final[frozenset[str]] = frozenset({"/Parent", "/P"})

#: ``/Length`` is a property of the ENCODING, not of the page.
_SKIP_IN_DICT: Final[frozenset[str]] = frozenset({"/Length"})

#: Keys dropped from the PAGE dictionary only -- never from a nested one,
#: where ``/Contents`` is an annotation's own text string and dropping it
#: would blind the digest to a real change.
_SKIP_PAGE_KEYS: Final[frozenset[str]] = frozenset({"/Parent", "/Contents"})

#: Bounded recursion. An unbounded walk over a graph with back-references does
#: not terminate; six levels reaches a font descriptor's own values, which is
#: past anything a round trip legitimately rewrites.
_MAX_DEPTH: Final[int] = 6


def _token(obj: Any, depth: int = 0) -> str:
    """A stable, comparison-only rendering of one PDF object.

    Deliberately NOT ``str(obj)`` at every level: ``str()`` on a stream
    includes that stream's own ``/Length``, and a legitimate re-compression
    changes it — the same false-positive class
    ``adapters/pikepdf_structure.py::_colorspace_name`` documents for
    ``/ICCBased`` colour spaces.
    """
    if depth >= _MAX_DEPTH:
        return "..."
    if isinstance(obj, pikepdf.Array):
        return "[" + ",".join(_token(item, depth + 1) for item in obj) + "]"
    if isinstance(obj, pikepdf.Dictionary | pikepdf.Stream):
        parts = []
        for key in sorted(obj.keys()):
            if key in _SKIP_KEYS or key in _SKIP_IN_DICT:
                continue
            parts.append(f"{key}={_token(obj[key], depth + 1)}")
        return "{" + ",".join(parts) + "}"
    return str(obj)


def _page_dict_token(page_obj: Any) -> str:
    """The page dictionary, minus the two keys (2) excludes."""
    parts = [
        f"{key}={_token(page_obj[key], 1)}"
        for key in sorted(page_obj.keys())
        if key not in _SKIP_PAGE_KEYS
    ]
    return "{" + ",".join(parts) + "}"


def _content_bytes(page: Any) -> bytes:
    """The page's decoded content, coalesced across a ``/Contents`` array."""
    contents = page.obj.get("/Contents")
    if contents is None:
        return b""
    if isinstance(contents, pikepdf.Array):
        return b"".join(bytes(stream.read_bytes()) for stream in contents)
    return bytes(contents.read_bytes())


def _image_bytes(page: Any) -> list[bytes]:
    """Every reachable image XObject's RAW stream bytes, in resource-name order."""
    found = page.get_images()
    return [bytes(found[name].read_raw_bytes()) for name in sorted(found)]


def page_tree_digest(path: Path | str, password: str | None = None) -> tuple[str, ...]:
    """One SHA-256 per page, in page order. Equality is tuple equality."""
    digests: list[str] = []
    with pikepdf.Pdf.open(str(path), password=password or "") as pdf:
        for page in pdf.pages:
            hasher = hashlib.sha256()
            hasher.update(_content_bytes(page))
            hasher.update(b"\x00")
            hasher.update(_page_dict_token(page.obj).encode("utf-8"))
            for raw in _image_bytes(page):
                hasher.update(b"\x00")
                hasher.update(raw)
            digests.append(hasher.hexdigest())
    return tuple(digests)
