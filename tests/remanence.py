"""PDF-121 -- the remanence instrument: fixtures, encoded sentinel forms, and a scan.

This is a DATA/HELPER module (the ``tests/seams.py`` pattern), not a test module,
so importing it from a test is not ``B-308`` coupling. PDF-126 (R-02) reuses both
the fixtures and the scan.

WHY IT IS INDEPENDENT OF THE FIX
--------------------------------
It imports nothing from ``pdf_tooling``. The oracle for "nothing the clear removed
is still in the file" must not share code with the thing that does the removing
(the PDF-107 lesson: a verifier that reuses the writer's own parser agrees with
the writer's bug). The tests drive the CLI as a subprocess and read the result
with pikepdf and pypdf here, and with raw bytes.

THE FOUR CHANNELS
-----------------
:func:`scan` looks at one file four independent ways:

* ``raw_hits`` -- the sentinel appears in the file bytes under ANY of
  :func:`encoded_forms`. This sees a revision the trailer no longer reaches.
  It is blind to a Flate stream (the bytes are compressed).
* ``decoded_hits`` -- per sentinel, the objgens whose DECODED content carries it,
  each tagged reachable or not. Every object the xref lists is scanned. This sees
  a Flate packet. It is blind to anything the xref does not list.
* ``unreachable`` -- objgens the xref lists that the trailer does not reach.
  Computed TWICE, by an iterative pikepdf walk and independently by pypdf; the two
  must agree or :func:`scan` raises, so one engine's blind spot cannot hide one.
* ``revisions`` -- ``startxref`` count, ``%%EOF`` count, and whether the PARSED
  trailer carries ``/Prev``. Never a raw ``/Prev`` grep: a ``merge`` output holds
  ``/Prev`` once as an outline sibling key (PDF-121 E6).

THE ENCODINGS THE RAW SEARCH MUST COVER (measured at ``e2a980e``)
-----------------------------------------------------------------
pypdf octal-escapes ``-``: ``SENT-INFO`` serialises as ``(SENT\\055INFO)``, so a
plain grep for a hyphenated sentinel in a pypdf-written file finds nothing even
when it is there. pypdf writes ``Ü``/``Ñ`` as ``\\334\\321`` and a non-PDFDoc
string as UTF-16BE in octal. pikepdf writes PDFDoc text as a literal with raw
high bytes and other text as lowercase hex UTF-16BE with a BOM. Sentinels stay
hyphenated on purpose: the ``\\055`` form is what the AC2 red control removes.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any, Final

import pikepdf
import pypdf
from pikepdf import Dictionary, Encryption, Name
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    StreamObject,
    TextStringObject,
)

__all__ = [
    "ENCRYPTED_SHAPES",
    "INFO_KEYS",
    "KEPT_LOCATIONS",
    "SENTINELS",
    "ScanResult",
    "build_fixtures",
    "encoded_forms",
    "metadata_streams_outside_pages",
    "scan",
    "unreferenced_info_count",
]

#: The keys that make a dictionary "an /Info dictionary" for the R-04 census.
INFO_KEYS: Final[frozenset[str]] = frozenset(
    {
        "/Author",
        "/Title",
        "/Subject",
        "/Keywords",
        "/Creator",
        "/Producer",
        "/CreationDate",
        "/ModDate",
        "/Trapped",
    }
)

#: Locations a clear must NOT remove (false-removal controls).
KEPT_LOCATIONS: Final[frozenset[str]] = frozenset({"page_xmp", "content"})

#: ``fixture -> {location: sentinel}``. Every sentinel is distinct per location.
SENTINELS: Final[dict[str, dict[str, str]]] = {
    "A": {"info": "SENT-INFO", "xmp": "SENT-XMP-RAW", "content": "SENT-CONTENT"},
    "A2": {"info": "SENT-INFO", "xmp": "SENT-XMP-FLATE"},
    "E": {"info": "SENT-INFO", "xmp": "SENT-XMP-RAW"},
    "D": {
        "info": "SENT-INFO",
        "xmp": "SENT-XMP-RAW",
        "page_xmp": "SENT-PAGEXMP",
        "content": "SENT-CONTENT",
    },
    "U": {"info": "SENT-ÜÑ-OCT", "content": "SENT-CONTENT"},
    "U_pypdf": {"info": "SENT-ÜÑ-OCT"},
    "U16": {"info": "SENT-ΩΞ-U16", "content": "SENT-CONTENT"},
    "U16_pypdf": {"info": "SENT-ΩΞ-U16"},
    "B": {
        "old_info": "SENT-OLDREV",
        "info": "SENT-NEWREV",
        "old_xmp": "SENT-OLDXMP",
        "xmp": "SENT-NEWXMP",
        "content": "SENT-CONTENT",
    },
    "B2": {"old_info": "SENT-OLDOBJ", "info": "SENT-NEWREV", "content": "SENT-CONTENT"},
    "C": {
        "info": "SENT-INFO",
        "xmp": "SENT-XMP-RAW",
        "chain": "SENT-CHAIN",
        "content": "SENT-CONTENT",
    },
    "C2": {"info": "SENT-CHAIN-INFO", "xmp": "SENT-XMP-RAW", "content": "SENT-CONTENT"},
    "O": {
        "info": "SENT-INFO",
        "xmp": "SENT-XMP-RAW",
        "preorphan": "SENT-PREORPHAN",
        "content": "SENT-CONTENT",
    },
}

#: The five encryption shapes, each over A's content. pikepdf builds RC4 (R3)
#: only with ``/EncryptMetadata false``, so the RC4 cell is necessarily a
#: no-metadata-encryption shape.
ENCRYPTED_SHAPES: Final[tuple[str, ...]] = (
    "A-RC4-UO",
    "A-AES128-UO",
    "A-AES256-UO",
    "A-AES256-O",
    "A-AES256-NOMETA-UO",
)
for _shape in ENCRYPTED_SHAPES:
    SENTINELS[_shape] = dict(SENTINELS["A"])

_UNCOMPRESSED: Final[dict[str, Any]] = {
    "compress_streams": False,
    "object_stream_mode": pikepdf.ObjectStreamMode.disable,
}
_XMP: Final[str] = (
    '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
    ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
    '  <rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
    "   <dc:creator><rdf:Seq><rdf:li>{c}</rdf:li></rdf:Seq></dc:creator>\n"
    '  </rdf:Description>\n </rdf:RDF>\n</x:xmpmeta>\n<?xpacket end="w"?>'
)


def _packet(creator: str) -> bytes:
    return _XMP.format(c=creator).encode("utf-8")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _base(
    author: str | None = "SENT-INFO", xmp: str | None = "SENT-XMP-RAW", pages: int = 1
) -> pikepdf.Pdf:
    pdf = pikepdf.new()
    font = pdf.make_indirect(
        Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica)
    )
    for i in range(pages):
        pdf.add_blank_page(page_size=(612, 792))
        page = pdf.pages[-1]
        page.obj.Contents = pdf.make_indirect(
            pikepdf.Stream(pdf, f"BT /F1 24 Tf 72 700 Td (SENT-CONTENT p{i + 1}) Tj ET".encode())
        )
        page.obj.Resources = Dictionary(Font=Dictionary(F1=font))
    if author is not None:
        pdf.docinfo["/Author"] = author
    if xmp:
        stream = pikepdf.Stream(pdf, _packet(xmp))
        stream.Type = Name.Metadata
        stream.Subtype = Name.XML
        pdf.Root.Metadata = pdf.make_indirect(stream)
    return pdf


def _pypdf_with_info(path: Path, author: str) -> None:
    writer = pypdf.PdfWriter()
    writer.add_blank_page(612, 792)
    writer.add_metadata({"/Author": author})
    with path.open("wb") as handle:
        writer.write(handle)


def build_fixtures(directory: Path) -> dict[str, Path]:
    """Write E4's fixture set into ``directory``; return ``name -> path``.

    Also writes ``u.pw`` / ``o.pw`` (the user / owner passwords for the
    ``*-UO`` / ``*-O`` encryption shapes) and returns them under those keys.
    Pikepdf-built fixtures randomise ``/ID[1]``: never compare their bytes
    against frozen literals.
    """
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    def at(name: str) -> Path:
        paths[name] = directory / f"{name}.pdf"
        return paths[name]

    _base().save(at("A"), **_UNCOMPRESSED)

    # A2: a Flate-compressed packet written by pypdf (raw ABSENT, decoded PRESENT).
    writer = pypdf.PdfWriter()
    writer.add_blank_page(612, 792)
    writer.add_metadata({"/Author": "SENT-INFO"})
    flate = StreamObject()
    flate.set_data(_packet("SENT-XMP-FLATE"))
    flate[NameObject("/Type")] = NameObject("/Metadata")
    flate[NameObject("/Subtype")] = NameObject("/XML")
    writer.root_object[NameObject("/Metadata")] = writer._add_object(flate.flate_encode())  # noqa: SLF001
    with at("A2").open("wb") as handle:
        writer.write(handle)

    # E: pikepdf open_metadata() plus a default save (object streams, compression).
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
        meta["dc:creator"] = ["SENT-XMP-RAW"]
    pdf.docinfo["/Author"] = "SENT-INFO"
    pdf.save(at("E"))

    # D: three pages, a page-2 packet AND the doc packet.
    pdf = _base(pages=3)
    page_packet = pikepdf.Stream(pdf, _packet("SENT-PAGEXMP"))
    page_packet.Type = Name.Metadata
    page_packet.Subtype = Name.XML
    pdf.pages[1].obj.Metadata = pdf.make_indirect(page_packet)
    pdf.save(at("D"), **_UNCOMPRESSED)

    # U / U16: non-ASCII /Info. "U" is PDFDoc-representable, "U16" is not; the
    # pypdf-written siblings are where the octal-escaped forms live.
    _base(author="SENT-ÜÑ-OCT", xmp=None).save(at("U"), **_UNCOMPRESSED)
    _pypdf_with_info(at("U_pypdf"), "SENT-ÜÑ-OCT")
    _base(author="SENT-ΩΞ-U16", xmp=None).save(at("U16"), **_UNCOMPRESSED)
    _pypdf_with_info(at("U16_pypdf"), "SENT-ΩΞ-U16")

    # B: a pypdf incremental update. Rev 1 holds SENT-OLDREV / SENT-OLDXMP; rev 2
    # replaces the XMP with a new object number.
    rev1 = directory / "B_rev1.pdf"
    _base(author="SENT-OLDREV", xmp="SENT-OLDXMP").save(rev1, **_UNCOMPRESSED)
    incremental = pypdf.PdfWriter(str(rev1), incremental=True)
    incremental.add_metadata({"/Author": "SENT-NEWREV"})
    new_packet = DecodedStreamObject()
    new_packet.set_data(_packet("SENT-NEWXMP"))
    new_packet[NameObject("/Type")] = NameObject("/Metadata")
    new_packet[NameObject("/Subtype")] = NameObject("/XML")
    incremental._root_object[NameObject("/Metadata")] = incremental._add_object(new_packet)  # noqa: SLF001
    with at("B").open("wb") as handle:
        incremental.write(handle)
    rev1.unlink()

    # B2: a hand-written classic update. Rev 1's old /Info (SENT-OLDOBJ) is left
    # unreferenced but still listed in the cumulative xref.
    rev1 = directory / "B2_rev1.pdf"
    _base(author="SENT-OLDOBJ", xmp=None).save(rev1, **_UNCOMPRESSED)
    raw = rev1.read_bytes()
    prev = int(re.findall(rb"startxref\s+(\d+)", raw)[-1])
    size = int(re.findall(rb"/Size (\d+)", raw)[-1])
    root = re.findall(rb"/Root (\d+ \d+ R)", raw)[-1]
    body = bytearray(raw)
    if not raw.endswith(b"\n"):
        body += b"\n"
    offset = len(body)
    body += b"%d 0 obj\n<< /Author (SENT-NEWREV) >>\nendobj\n" % size
    xref_at = len(body)
    body += b"xref\n0 1\n0000000000 65535 f \n%d 1\n%010d 00000 n \n" % (size, offset)
    body += b"trailer\n<< /Size %d /Root %s /Info %d 0 R /Prev %d >>\nstartxref\n%d\n%%%%EOF\n" % (
        size + 1,
        root,
        size,
        prev,
        xref_at,
    )
    at("B2").write_bytes(bytes(body))
    rev1.unlink()

    # C: the doc /Metadata stream references an indirect dict holding SENT-CHAIN
    # (an orphan CHAIN once the stream is unlinked).
    chained = pypdf.PdfWriter(clone_from=str(paths["A"]))
    chain = chained._add_object(  # noqa: SLF001
        DictionaryObject({NameObject("/Note"): TextStringObject("SENT-CHAIN")})
    )
    chained._root_object["/Metadata"].get_object()[NameObject("/PieceRef")] = chain  # noqa: SLF001
    with at("C").open("wb") as handle:
        chained.write(handle)

    # C2: /Info /Author as an indirect string.
    pdf = _base(author=None)
    pdf.docinfo["/Author"] = pdf.make_indirect(pikepdf.String("SENT-CHAIN-INFO"))
    pdf.save(at("C2"), **_UNCOMPRESSED)

    # O: a pre-existing unreferenced stream in the input.
    orphaned = pypdf.PdfWriter(clone_from=str(paths["A"]))
    orphan = DecodedStreamObject()
    orphan.set_data(b"SENT-PREORPHAN")
    orphaned._add_object(orphan)  # noqa: SLF001
    with at("O").open("wb") as handle:
        orphaned.write(handle)

    # N: two pages, no /Info and no XMP.
    _base(author=None, xmp=None, pages=2).save(at("N"), **_UNCOMPRESSED)

    shapes: dict[str, dict[str, Any]] = {
        "A-RC4-UO": {"user": "u-pw", "owner": "o-pw", "R": 3, "aes": False, "metadata": False},
        "A-AES128-UO": {"user": "u-pw", "owner": "o-pw", "R": 4, "aes": True},
        "A-AES256-UO": {"user": "u-pw", "owner": "o-pw", "R": 6},
        "A-AES256-O": {"user": "", "owner": "o-pw", "R": 6},
        "A-AES256-NOMETA-UO": {"user": "u-pw", "owner": "o-pw", "R": 6, "metadata": False},
    }
    for name, options in shapes.items():
        with pikepdf.open(paths["A"]) as source:
            source.save(at(name), encryption=Encryption(**options), compress_streams=False)
    (directory / "u.pw").write_text("u-pw\n")
    (directory / "o.pw").write_text("o-pw\n")
    (directory / "u.pw").chmod(0o600)
    (directory / "o.pw").chmod(0o600)
    paths["u.pw"] = directory / "u.pw"
    paths["o.pw"] = directory / "o.pw"
    return paths


# --------------------------------------------------------------------------- #
# Encoded forms
# --------------------------------------------------------------------------- #


def _mixed_escape(raw: bytes) -> re.Pattern[bytes]:
    """A pattern for ``raw`` where each byte may be literal OR a ``\\ddd`` octal escape."""
    parts: list[bytes] = []
    for byte in raw:
        octal = b"%o" % byte
        padded = octal.rjust(3, b"0")
        parts.append(
            b"(?:" + re.escape(bytes([byte])) + b"|\\\\" + padded + b"|\\\\" + octal + b")"
        )
    return re.compile(b"".join(parts), re.DOTALL)


def encoded_forms(sentinel: str) -> list[bytes | re.Pattern[bytes]]:
    """Every byte-level spelling of ``sentinel`` a PDF writer is known to emit.

    * plain bytes (ASCII, latin-1 when representable, UTF-8);
    * a pattern accepting ANY mix of literal and ``\\ddd`` octal-escaped bytes,
      over latin-1, UTF-8, UTF-16BE without a BOM and UTF-16BE with a BOM. This is
      what catches pypdf's ``\\055`` for ``-``;
    * UTF-16BE with and without a BOM, raw;
    * hex ``<...>`` in lower and upper case, for latin-1 and UTF-16BE with a BOM.
    """
    forms: list[bytes | re.Pattern[bytes]] = []
    utf8 = sentinel.encode("utf-8")
    utf16 = sentinel.encode("utf-16-be")
    utf16_bom = b"\xfe\xff" + utf16
    latin1: bytes | None
    try:
        latin1 = sentinel.encode("latin-1")
    except UnicodeEncodeError:
        latin1 = None
    plain = [utf8, utf16, utf16_bom]
    if latin1 is not None:
        plain.append(latin1)
    forms.extend(plain)
    for raw in plain:
        forms.append(_mixed_escape(raw))
    for raw in (latin1, utf16_bom):
        if raw is not None:
            forms.extend([raw.hex().encode(), raw.hex().upper().encode()])
    return forms


def _matches(data: bytes, form: bytes | re.Pattern[bytes]) -> bool:
    if isinstance(form, bytes):
        return form in data
    return form.search(data) is not None


# --------------------------------------------------------------------------- #
# The scan
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class ScanResult:
    """One file, four channels. See the module docstring."""

    raw_hits: frozenset[str]
    decoded_hits: dict[str, tuple[tuple[tuple[int, int], bool], ...]]
    unreachable: tuple[tuple[int, int], ...]
    revisions: tuple[int, int, bool]
    size: int

    def decoded_sentinels(self) -> frozenset[str]:
        return frozenset(self.decoded_hits)

    def decoded_in_unreachable(self) -> frozenset[str]:
        return frozenset(
            sentinel
            for sentinel, hits in self.decoded_hits.items()
            if any(not reachable for _, reachable in hits)
        )


def _is_structural(obj: Any) -> bool:
    """qpdf-owned structure rather than content: ObjStm, XRef, linearization."""
    if isinstance(obj, pikepdf.Stream):
        kind = obj.get("/Type")
        if kind in ("/XRef", "/ObjStm"):
            return True
        keys = [str(k) for k in obj.stream_dict.keys()]
        if kind is None and "/S" in keys and "/Length" in keys and len(keys) <= 3:
            return True
    return isinstance(obj, pikepdf.Dictionary) and "/Linearized" in obj


def _pikepdf_reachable(pdf: pikepdf.Pdf) -> set[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    stack: list[tuple[Any, bool]] = [(pdf.trailer, True)]
    while stack:
        node, is_root = stack.pop()
        if node is None:
            continue
        if not is_root and getattr(node, "is_indirect", False):
            if node.objgen in seen:
                continue
            seen.add(node.objgen)
        if isinstance(node, (pikepdf.Stream, pikepdf.Dictionary)):
            stack.extend((node.get(k), False) for k in list(node.keys()))
        elif isinstance(node, pikepdf.Array):
            stack.extend((item, False) for item in node)
    return seen


def _pypdf_unreachable(path: Path, password: str) -> set[tuple[int, int]]:
    reader = pypdf.PdfReader(str(path))
    if reader.is_encrypted:
        reader.decrypt(password)
    listed: set[tuple[int, int]] = set()
    for generation, numbers in reader.xref.items():
        listed.update((number, generation) for number in numbers)
    listed.update((number, 0) for number in getattr(reader, "xref_objStm", {}))
    seen: set[tuple[int, int]] = set()
    stack: list[Any] = [reader.trailer]
    while stack:
        node = stack.pop()
        if isinstance(node, IndirectObject):
            key = (node.idnum, node.generation)
            if key in seen:
                continue
            seen.add(key)
            node = node.get_object()
        if isinstance(node, DictionaryObject):
            stack.extend(node.values())
        elif isinstance(node, ArrayObject):
            stack.extend(node)
    out: set[tuple[int, int]] = set()
    for key in listed - seen:
        obj = reader.get_object(IndirectObject(key[0], key[1], reader))
        if obj is None:
            continue
        if isinstance(obj, DictionaryObject) and (
            obj.get("/Type") in ("/XRef", "/ObjStm") or "/Linearized" in obj
        ):
            continue
        if (
            isinstance(obj, StreamObject)
            and obj.get("/Type") is None
            and "/S" in obj
            and len(obj) <= 3
        ):
            continue
        out.add(key)
    return out


def _strings(obj: Any, acc: list[bytes], depth: int = 0) -> None:
    if depth and getattr(obj, "is_indirect", False):
        return
    if isinstance(obj, pikepdf.String):
        acc.append(str(obj).encode("utf-8"))
        acc.append(bytes(obj))
    elif isinstance(obj, (pikepdf.Stream, pikepdf.Dictionary)):
        for key in list(obj.keys()):
            _strings(obj.get(key), acc, depth + 1)
    elif isinstance(obj, pikepdf.Array):
        for item in obj:
            _strings(item, acc, depth + 1)


def _needles(sentinel: str) -> tuple[bytes, ...]:
    utf16 = sentinel.encode("utf-16-be")
    return (sentinel.encode("utf-8"), utf16, b"\xfe\xff" + utf16)


def scan(
    path: Path,
    sentinels: list[str] | tuple[str, ...] | None = None,
    password: str = "",
) -> ScanResult:
    """Scan ``path`` on all four channels. Raises if the two reachability walks disagree."""
    if sentinels is None:
        sentinels = sorted({s for group in SENTINELS.values() for s in group.values()})
    data = Path(path).read_bytes()
    raw_hits = frozenset(
        sentinel
        for sentinel in sentinels
        if any(_matches(data, form) for form in encoded_forms(sentinel))
    )
    decoded: dict[str, list[tuple[tuple[int, int], bool]]] = {}
    with pikepdf.open(path, password=password) as pdf:
        reachable = _pikepdf_reachable(pdf)
        listed = [obj for obj in pdf.objects if obj is not None]
        pikepdf_unreachable = {
            obj.objgen for obj in listed if obj.objgen not in reachable and not _is_structural(obj)
        }
        for obj in listed:
            blobs: list[bytes] = []
            if isinstance(obj, pikepdf.Stream):
                blobs.append(obj.read_bytes())
                blobs.append(obj.stream_dict.unparse())
            else:
                blobs.append(obj.unparse())
            _strings(obj, blobs)
            for sentinel in sentinels:
                if any(needle in blob for blob in blobs for needle in _needles(sentinel)):
                    decoded.setdefault(sentinel, []).append((obj.objgen, obj.objgen in reachable))
    pypdf_unreachable = _pypdf_unreachable(Path(path), password)
    if pikepdf_unreachable != pypdf_unreachable:
        raise AssertionError(
            f"the two reachability walks disagree on {path}: "
            f"pikepdf-only={sorted(pikepdf_unreachable - pypdf_unreachable)} "
            f"pypdf-only={sorted(pypdf_unreachable - pikepdf_unreachable)}"
        )
    with pikepdf.open(path, password=password) as pdf:
        has_prev = "/Prev" in pdf.trailer
    return ScanResult(
        raw_hits=raw_hits,
        decoded_hits={k: tuple(sorted(v)) for k, v in decoded.items()},
        unreachable=tuple(sorted(pikepdf_unreachable)),
        revisions=(data.count(b"startxref"), data.count(b"%%EOF"), has_prev),
        size=len(data),
    )


def unreferenced_info_count(path: Path, password: str = "") -> int:
    """Unreachable dictionaries that carry any ``/Info`` key (R-04's duplicate /Info)."""
    unreachable = set(scan(path, [], password).unreachable)
    count = 0
    with pikepdf.open(path, password=password) as pdf:
        for obj in pdf.objects:
            if obj is None or obj.objgen not in unreachable:
                continue
            if isinstance(obj, pikepdf.Dictionary) and INFO_KEYS & {str(k) for k in obj.keys()}:
                count += 1
    return count


def metadata_streams_outside_pages(path: Path, password: str = "") -> list[tuple[int, int]]:
    """``/Type /Metadata`` streams the xref lists that no page dictionary references."""
    with pikepdf.open(path, password=password) as pdf:
        on_pages = {page.obj["/Metadata"].objgen for page in pdf.pages if "/Metadata" in page.obj}
        return sorted(
            obj.objgen
            for obj in pdf.objects
            if isinstance(obj, pikepdf.Stream)
            and obj.get("/Type") == "/Metadata"
            and obj.objgen not in on_pages
        )


def passwords_for(fixture: str, directory: Path) -> tuple[str, list[str]]:
    """``(scan password, CLI args)`` to open ``fixture`` as an INPUT (``*-O``: empty user pw)."""
    if fixture.endswith("-UO"):
        return "u-pw", ["--password-file", str(directory / "u.pw")]
    return "", []
