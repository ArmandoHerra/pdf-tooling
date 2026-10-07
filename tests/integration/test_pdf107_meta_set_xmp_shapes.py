"""PDF-107 -- `meta set` never writes an XMP packet that does not parse.

THE DEFECT. pypdf's XMP setters assume the canonical prefix (``dc``, ``pdf``,
``xmp``) is already bound on the first ``rdf:Description`` or above it. pypdf's
own template satisfies that and every older corpus fixture is pypdf-authored, so
the suite never saw ``meta set`` rewrite a pikepdf-authored packet into
``unbound prefix`` XML behind a reported ``ok`` (ledger ``652385c7bf``). The same
cause breaks three further realistic shapes, and leaves ``--clear-producer``
that did not clear, and a raw traceback when the input packet was already
unparseable.

THE AXIS. The *document shape* is a declared axis (PDF-74 never varies the input
document). Nine shapes are crossed with the XMP-touching verbs. The test-local
shapes are byte-exact packets saved through pikepdf with
``fix_metadata_version=False`` so pikepdf does not re-serialize them, and every
builder asserts what it claims to be.

THE ORACLES (named, because the wrong oracle makes the whole matrix vacuous):

* parse: ``PdfReader(out).xmp_metadata`` (pypdf, expat/minidom -- the parser
  ``meta get`` uses) AND ``xml.etree.ElementTree.fromstring`` over the raw
  ``/Metadata`` bytes (stdlib expat, namespace-aware). pikepdf's
  ``open_metadata()`` is NOT an oracle: it silently RECOVERS undeclared prefixes.
* round-trip: ``meta get <out>`` reports the value that was set.
* survival: a property inventory (namespace URI, local name, normalized text)
  over every Description equals the input's, except the edited property.

Every cell is a subprocess (``registry.run_cli``), ``-o json``, non-TTY, on a
per-cell copy under ``tmp_path``.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pikepdf
import pytest
from pypdf import PdfReader

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from dryreal import dry_and_real, prediction  # noqa: E402
from registry import run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

NEW: Final[str] = "PDF107 New Value"

RDF: Final[str] = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DC: Final[str] = "http://purl.org/dc/elements/1.1/"
XMP: Final[str] = "http://ns.adobe.com/xap/1.0/"
PDF: Final[str] = "http://ns.adobe.com/pdf/1.3/"
PDFAID: Final[str] = "http://www.aiim.org/pdfa/ns/id/"

REASON_NOT_WELL_FORMED: Final[str] = "the XMP packet is not well-formed XML"
REASON_NON_EMPTY_ABOUT: Final[str] = "the XMP packet describes a non-empty rdf:about"
REASON_UNVERIFIED: Final[str] = "rewriting the XMP packet did not verify"


def _preserved_message(reason: str) -> str:
    return f"ok (XMP packet left unchanged: {reason}; /Info only)"


#: `field` -> (CLI flag, (namespace URI, local name), /Info key)
FIELDS: Final[Mapping[str, tuple[str, tuple[str, str], str]]] = {
    "title": ("--title", (DC, "title"), "/Title"),
    "author": ("--author", (DC, "creator"), "/Author"),
    "subject": ("--subject", (DC, "description"), "/Subject"),
    "keywords": ("--keywords", (PDF, "Keywords"), "/Keywords"),
    "creator": ("--creator", (XMP, "CreatorTool"), "/Creator"),
}
PRODUCER: Final[tuple[str, str]] = (PDF, "Producer")

SET_CELLS: Final[tuple[str, ...]] = tuple(FIELDS)
ALL_CELLS: Final[tuple[str, ...]] = (*SET_CELLS, "clear_producer", "clear_all")

#: `rdf:Description`-level packets share this prolog/epilog.
_PROLOG: Final[str] = (
    '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"{xmpmeta_extra}>\n'
    '<rdf:RDF xmlns:rdf="' + RDF + '"{rdf_extra}>\n'
)
_EPILOG: Final[str] = '</rdf:RDF>\n</x:xmpmeta>\n<?xpacket end="w"?>'

_DECL_DC: Final[str] = f'xmlns:dc="{DC}"'
_DECL_XMP: Final[str] = f'xmlns:xmp="{XMP}"'
_DECL_PDF: Final[str] = f'xmlns:pdf="{PDF}"'
_DECL_PDFAID: Final[str] = f'xmlns:pdfaid="{PDFAID}"'

_TITLE: Final[str] = (
    '<dc:title><rdf:Alt><rdf:li xml:lang="x-default">Shape Title</rdf:li></rdf:Alt></dc:title>'
)
_CREATOR: Final[str] = "<dc:creator><rdf:Seq><rdf:li>Shape Author</rdf:li></rdf:Seq></dc:creator>"
_KEYWORDS: Final[str] = "<pdf:Keywords>shape, keywords</pdf:Keywords>"
_TOOL: Final[str] = "<xmp:CreatorTool>Shape Tool</xmp:CreatorTool>"
_PRODUCER: Final[str] = "<pdf:Producer>Shape Producer</pdf:Producer>"
_PDFAID: Final[str] = "<pdfaid:part>2</pdfaid:part><pdfaid:conformance>B</pdfaid:conformance>"


def _packet(body: str, *, xmpmeta_extra: str = "", rdf_extra: str = "") -> bytes:
    prolog = _PROLOG.format(xmpmeta_extra=xmpmeta_extra, rdf_extra=rdf_extra)
    return (prolog + body + _EPILOG).encode("utf-8")


def _description(declarations: str, content: str, *, about: str = "") -> str:
    return f'<rdf:Description rdf:about="{about}" {declarations}>{content}</rdf:Description>\n'


ALL_DECLS: Final[str] = f"{_DECL_DC} {_DECL_XMP} {_DECL_PDF} {_DECL_PDFAID}"
ALL_PROPS: Final[str] = _TITLE + _CREATOR + _KEYWORDS + _TOOL + _PRODUCER + _PDFAID


def _packet_on_description() -> bytes:
    return _packet(_description(ALL_DECLS, ALL_PROPS))


def _packet_multi_description() -> bytes:
    body = (
        _description(_DECL_XMP, _TOOL)
        + _description(_DECL_DC, _TITLE + _CREATOR)
        + _description(_DECL_PDF, _KEYWORDS + _PRODUCER)
        + _description(_DECL_PDFAID, _PDFAID)
    )
    return _packet(body)


def _packet_root_declared() -> bytes:
    body = _description("", ALL_PROPS)
    return _packet(
        body, xmpmeta_extra=f" {_DECL_DC} {_DECL_PDF}", rdf_extra=f" {_DECL_XMP} {_DECL_PDFAID}"
    )


def _packet_nonstandard_prefix() -> bytes:
    purl_title = _TITLE.replace("dc:", "purl:")
    purl_creator = _CREATOR.replace("dc:", "purl:")
    declarations = f'xmlns:purl="{DC}" {_DECL_XMP} {_DECL_PDF} {_DECL_PDFAID}'
    content = purl_title + purl_creator + _KEYWORDS + _TOOL + _PRODUCER + _PDFAID
    return _packet(_description(declarations, content))


def _packet_attribute_form() -> bytes:
    attributes = (
        f'{_DECL_DC} {_DECL_XMP} {_DECL_PDF} {_DECL_PDFAID} pdf:Keywords="shape, keywords" '
        'xmp:CreatorTool="Shape Tool" pdf:Producer="Shape Producer"'
    )
    return _packet(_description(attributes, _TITLE + _CREATOR + _PDFAID))


def _packet_about_uuid() -> bytes:
    return _packet(
        _description(ALL_DECLS, ALL_PROPS, about="uuid:5b7e2c1e-0000-4000-8000-000000000107")
    )


# --------------------------------------------------------------------------- #
# The inventory oracle.
# --------------------------------------------------------------------------- #


def _tree(raw: bytes) -> ET.Element:
    """Parse *raw* with the stdlib's namespace-aware expat (an oracle)."""
    return ET.fromstring(raw)  # noqa: S314 - a test oracle over a locally built packet


def _inventory(raw: bytes) -> Counter[tuple[str, str, str]]:
    """Multiset of ``(namespace URI, local name, normalized text)`` over every
    child element and every non-``rdf`` attribute of every ``rdf:Description``."""
    found: Counter[tuple[str, str, str]] = Counter()
    for description in _tree(raw).iter(f"{{{RDF}}}Description"):
        for key, value in description.attrib.items():
            namespace, _, local = key[1:].partition("}")
            if namespace == RDF or not local:
                continue
            found[(namespace, local, value.strip())] += 1
        for child in description:
            namespace, _, local = child.tag[1:].partition("}")
            text = "|".join(part.strip() for part in child.itertext() if part.strip())
            found[(namespace, local, text)] += 1
    return found


def _expected_inventory(
    before: Counter[tuple[str, str, str]], prop: tuple[str, str], value: str | None
) -> Counter[tuple[str, str, str]]:
    expected = Counter({k: n for k, n in before.items() if (k[0], k[1]) != prop})
    if value is not None:
        expected[(prop[0], prop[1], value)] += 1
    return expected


def _metadata_bytes(path: Path) -> bytes | None:
    with pikepdf.open(str(path)) as pdf:
        stream = pdf.Root.get("/Metadata")
        return None if stream is None else bytes(stream.read_bytes())


# --------------------------------------------------------------------------- #
# The nine shapes, each asserting what it claims to be.
# --------------------------------------------------------------------------- #

#: Ledger `17add7b3e9`: inputs whose `/Encrypt` says `/EncryptMetadata false`, so the
#: `/Metadata` stream is stored in PLAINTEXT and pypdf's cipher turns it into garbage.
#: `rc4_owner` is the product's own `encrypt --legacy` (always writes the flag);
#: the AES-256 R=6 pair is Acrobat's "encrypt all contents except metadata". All are
#: owner-password-only (the empty user password opens them), which is the form that
#: reaches `meta set` without a password flag. The malformed twin makes the P1
#: "left unchanged" arm reachable on an encrypted input, so the byte-equality
#: assertion there is against the TRUE packet and cannot pass on garbage.
ENCRYPTED_SHAPES: Final[tuple[str, ...]] = ("rc4_owner", "aes256_nometa", "aes256_nometa_malformed")

SHAPES: Final[tuple[str, ...]] = (
    "xmp_bearing",
    "xmp_pikepdf",
    "on_description",
    "multi_description",
    "root_declared",
    "nonstandard_prefix",
    "attribute_form",
    "about_uuid",
    "malformed",
    *ENCRYPTED_SHAPES,
)

#: shape -> None (parseable, rewritten) or the preserve reason it must trigger.
PRESERVED: Final[Mapping[str, str]] = {
    "about_uuid": REASON_NON_EMPTY_ABOUT,
    "malformed": REASON_NOT_WELL_FORMED,
    "aes256_nometa_malformed": REASON_NOT_WELL_FORMED,
}
PARSEABLE: Final[tuple[str, ...]] = tuple(s for s in SHAPES if s not in PRESERVED)

#: The shapes whose packet carries a `pdf:Producer` the clear cell can remove.
PRODUCER_BEARING: Final[tuple[str, ...]] = tuple(s for s in PARSEABLE if s not in ("xmp_bearing",))

_PACKETS: Final[Mapping[str, Any]] = {
    "on_description": _packet_on_description,
    "multi_description": _packet_multi_description,
    "root_declared": _packet_root_declared,
    "nonstandard_prefix": _packet_nonstandard_prefix,
    "attribute_form": _packet_attribute_form,
    "about_uuid": _packet_about_uuid,
}


def _opening_tags(raw: bytes, name: str) -> list[str]:
    return re.findall(rf"<{name}\b[^>]*>", raw.decode("utf-8"))


def _assert_shape_precondition(shape: str, raw: bytes) -> None:
    """Each builder proves where its declarations live and what parses."""
    text = raw.decode("utf-8")
    if shape == "malformed":
        with pytest.raises(ET.ParseError, match="unbound prefix"):
            _tree(raw)
        return
    _tree(raw)  # every other shape is well-formed XML
    descriptions = _opening_tags(raw, "rdf:Description")
    if shape == "xmp_pikepdf":
        assert all("xmlns:" not in tag for tag in descriptions)
        assert text.count("xmlns:dc=") >= 2
    elif shape == "on_description":
        assert len(descriptions) == 1
        assert all(prefix in descriptions[0] for prefix in ("xmlns:dc", "xmlns:xmp", "xmlns:pdf"))
    elif shape == "multi_description":
        assert len(descriptions) == 4
        assert [re.findall(r"xmlns:(\w+)=", tag) for tag in descriptions] == [
            ["xmp"],
            ["dc"],
            ["pdf"],
            ["pdfaid"],
        ]
    elif shape == "root_declared":
        assert all("xmlns:" not in tag for tag in descriptions)
        assert "xmlns:dc" in _opening_tags(raw, "x:xmpmeta")[0]
        assert "xmlns:xmp" in _opening_tags(raw, "rdf:RDF")[0]
    elif shape == "nonstandard_prefix":
        assert f'xmlns:purl="{DC}"' in text
        assert "xmlns:dc=" not in text
        assert "<dc:" not in text
    elif shape == "attribute_form":
        assert 'pdf:Keywords="' in descriptions[0]
        assert "<pdf:Keywords" not in text
    elif shape == "about_uuid":
        assert 'rdf:about="uuid:' in text
        assert 'rdf:about=""' not in text
    if shape != "about_uuid":
        assert 'rdf:about=""' in text


def _malformed_packet(corpus: Any) -> bytes:
    """`xmp_pikepdf`'s packet with ONE element-local `xmlns:dc` removed: the
    exact bytes the defect produces."""
    raw = _metadata_bytes(corpus.path("xmp_pikepdf"))
    assert raw is not None
    declaration = f' xmlns:dc="{DC}"'
    assert raw.decode("utf-8").count(declaration) == 2
    return raw.replace(declaration.encode(), b"", 1)


def _plain_source_with_packet(corpus: Any, tmp_path: Path, packet: bytes) -> Path:
    source = tmp_path / "plain_source.pdf"
    with pikepdf.open(str(corpus.path("single_page"))) as pdf:
        stream = pdf.make_stream(packet)
        stream["/Type"] = pikepdf.Name.Metadata
        stream["/Subtype"] = pikepdf.Name.XML
        pdf.Root.Metadata = stream
        pdf.save(str(source), fix_metadata_version=False, deterministic_id=True)
    return source


def _build_encrypted_shape(shape: str, corpus: Any, tmp_path: Path) -> tuple[Path, bytes]:
    """An `/EncryptMetadata false` input and its TRUE packet (read through pikepdf)."""
    if shape == "aes256_nometa_malformed":
        packet = _malformed_packet(corpus)
    else:
        packet = _packet(_description(ALL_DECLS, _TITLE + _PRODUCER + _PDFAID))
    plain = _plain_source_with_packet(corpus, tmp_path, packet)
    target = tmp_path / f"{shape}.pdf"
    if shape == "rc4_owner":
        password_file = tmp_path / "owner.pw"
        password_file.write_text("ownerpw\n")
        password_file.chmod(0o600)
        made = run_cli(
            "encrypt", str(plain), "--legacy", "--owner-password-file", str(password_file),
            "-O", str(target), "-o", "json",
        )  # fmt: skip
        assert made.returncode == 0, made.stderr[-500:]
    else:
        with pikepdf.open(str(plain)) as pdf:
            pdf.save(
                str(target),
                fix_metadata_version=False,
                encryption=pikepdf.Encryption(owner="ownerpw", user="", R=6, metadata=False),
            )
    with pikepdf.open(str(target)) as pdf:
        assert pdf.is_encrypted
        assert pdf.trailer.Encrypt.get("/EncryptMetadata") is False, shape
    raw = _metadata_bytes(target)
    assert raw is not None and raw.startswith(b"<?xpacket"), f"{shape}: not the stored packet"
    # Non-vacuity: this shape really is the one on which pypdf's view is wrong, so a
    # test that compared against pypdf's bytes would be comparing against garbage.
    reader = PdfReader(str(target))
    assert reader.decrypt("") != 0
    pypdf_view = reader.trailer["/Root"]["/Metadata"].get_object().get_data()
    assert pypdf_view != raw, f"{shape}: pypdf already reads the true packet (no defect shape)"
    return target, raw


def build_shape(shape: str, corpus: Any, tmp_path: Path) -> tuple[Path, bytes]:
    """Return ``(path, input packet bytes)`` for a fresh copy of *shape*."""
    if shape in ENCRYPTED_SHAPES:
        return _build_encrypted_shape(shape, corpus, tmp_path)
    target = tmp_path / f"{shape}.pdf"
    if shape in ("xmp_bearing", "xmp_pikepdf"):
        target.write_bytes(corpus.path(shape).read_bytes())
    else:
        packet = _malformed_packet(corpus) if shape == "malformed" else _PACKETS[shape]()
        with pikepdf.open(str(corpus.path("single_page"))) as pdf:
            stream = pdf.make_stream(packet)
            stream["/Type"] = pikepdf.Name.Metadata
            stream["/Subtype"] = pikepdf.Name.XML
            pdf.Root.Metadata = stream
            pdf.save(str(target), fix_metadata_version=False, deterministic_id=True)
    raw = _metadata_bytes(target)
    assert raw is not None, f"{shape}: the packet was not written"
    _assert_shape_precondition(shape, raw)
    if shape == "malformed":
        with pytest.raises(Exception, match="unbound prefix"):
            _ = PdfReader(str(target)).xmp_metadata
    else:
        assert PdfReader(str(target)).xmp_metadata is not None
    return target, raw


# --------------------------------------------------------------------------- #
# One cell = one subprocess on a per-cell copy.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Cell:
    shape: str
    cell: str
    source: Path
    before: bytes
    out: Path
    returncode: int
    payload: dict[str, Any]
    stderr: str

    @property
    def item(self) -> dict[str, Any]:
        return dict(self.payload["items"][0])


#: PDF-115 D10: every cell here asks what an ALLOWED `meta set` does to a shape,
#: encrypted ones included, so each carries the opt-in (accepted and inert on a
#: plain shape). Nothing else about the cells moves.
_OPT_IN: Final[str] = "--allow-decrypted-output"


def _args(cell: str, out: Path) -> list[str]:
    if cell in FIELDS:
        return [FIELDS[cell][0], NEW, "-O", str(out), _OPT_IN]
    if cell == "clear_producer":
        return ["--clear-producer", "-O", str(out), _OPT_IN]
    if cell == "clear_all":
        return ["--clear-all", "-O", str(out), _OPT_IN]
    assert cell == "in_place", cell
    return ["--title", NEW, "--in-place", _OPT_IN]


def _envelope(result: Any) -> dict[str, Any]:
    assert "Traceback" not in result.stderr, result.stderr[-800:]
    try:
        return dict(json.loads(result.stdout))
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"stdout was not JSON ({error}); rc={result.returncode} stdout={result.stdout[:300]!r} "
            f"stderr={result.stderr[-500:]!r}"
        ) from None


def run_cell(shape: str, cell: str, corpus: Any, tmp_path: Path) -> Cell:
    source, before = build_shape(shape, corpus, tmp_path)
    out = source if cell == "in_place" else tmp_path / "out.pdf"
    result = run_cli("meta set", str(source), *_args(cell, tmp_path / "out.pdf"), "-o", "json")
    payload = _envelope(result)
    return Cell(shape, cell, source, before, out, result.returncode, payload, result.stderr)


def _meta_get(path: Path) -> dict[str, Any]:
    result = run_cli("meta", "get", str(path), "-o", "json")
    assert result.returncode == 0, result.stderr[-500:]
    return _envelope(result)


def _expected_xmp_value(cell: str) -> Any:
    if cell in ("title", "subject", "in_place"):
        return {"x-default": NEW}
    if cell == "author":
        return [NEW]
    return NEW


def _assert_parses_under_both(out: Path) -> bytes:
    raw = _metadata_bytes(out)
    assert raw is not None, "the output carries no /Metadata"
    _tree(raw)  # ElementTree (stdlib expat): raises ParseError on `unbound prefix`
    assert PdfReader(str(out)).xmp_metadata is not None  # pypdf: the parser `meta get` uses
    return raw


def _assert_round_trip(out: Path, cell: str) -> None:
    report = _meta_get(out)
    assert report["xmp"] is not None, "meta get reports xmp: null for the written packet"
    assert report["warnings"] == []
    field = "title" if cell == "in_place" else ("producer" if cell == "clear_producer" else cell)
    if cell == "clear_producer":
        assert report["xmp"]["producer"] is None
    else:
        assert report["xmp"][field] == _expected_xmp_value(cell)
    assert field not in [d["field"] for d in report["disagreements"]], report["disagreements"]


def _packet_warnings(run: Cell) -> list[str]:
    """The run's warnings minus PDF-108's carriage line. An encrypted input writes
    an unencrypted output, and PDF-108 says so exactly once; this arm's oracle is
    about the XMP packet, so that line is asserted present and then set aside."""
    carriage = [w for w in run.payload["warnings"] if "input is encrypted;" in w]
    assert len(carriage) == (1 if run.shape in ENCRYPTED_SHAPES else 0), run.payload["warnings"]
    return [w for w in run.payload["warnings"] if w not in carriage]


def _assert_rewritten(run: Cell) -> None:
    """AC3/AC4/AC5's oracles for one cell that must have been rewritten."""
    assert run.returncode == 0, f"rc {run.returncode}; stderr={run.stderr[-400:]!r}"
    item = run.item
    assert item["message"] == "ok", item
    assert item["detail"] == {"wrote_xmp": True}
    assert _packet_warnings(run) == []
    raw = _assert_parses_under_both(run.out)
    _assert_round_trip(run.out, run.cell)

    if run.cell == "clear_producer":
        prop, value = PRODUCER, None
    else:
        field = "title" if run.cell == "in_place" else run.cell
        prop, value = FIELDS[field][1], NEW
    assert _inventory(raw) == _expected_inventory(_inventory(run.before), prop, value), (
        "an XMP property was lost, duplicated or left behind"
    )
    if run.shape != "xmp_bearing":
        assert any(k[0] == PDFAID and k[1] == "part" for k in _inventory(raw)), "pdfaid:part lost"
        assert any(k[0] == PDFAID and k[1] == "conformance" for k in _inventory(raw))


# --------------------------------------------------------------------------- #
# AC3 / AC4 -- every set field, on every parseable shape.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("cell", SET_CELLS)
@pytest.mark.parametrize("shape", PARSEABLE)
def test_meta_set_field_round_trips_on_every_parseable_shape(
    corpus: Any, tmp_path: Path, shape: str, cell: str
) -> None:
    _assert_rewritten(run_cell(shape, cell, corpus, tmp_path))


def test_meta_set_in_place_round_trips_on_the_pikepdf_shape(corpus: Any, tmp_path: Path) -> None:
    run = run_cell("xmp_pikepdf", "in_place", corpus, tmp_path)
    _assert_rewritten(run)
    assert Path(str(run.source) + ".bak").is_file(), "--in-place must write its .bak sidecar"


# --------------------------------------------------------------------------- #
# AC5 -- `--clear-producer` clears everywhere it can.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("shape", PRODUCER_BEARING)
def test_clear_producer_clears_the_xmp_property_on_every_parseable_shape(
    corpus: Any, tmp_path: Path, shape: str
) -> None:
    run = run_cell(shape, "clear_producer", corpus, tmp_path)
    assert any(k[:2] == PRODUCER for k in _inventory(run.before)), "the shape carries no producer"
    _assert_rewritten(run)
    assert not any(k[:2] == PRODUCER for k in _inventory(_assert_parses_under_both(run.out)))
    assert "producer" not in [d["field"] for d in _meta_get(run.out)["disagreements"]]


# --------------------------------------------------------------------------- #
# AC6 / AC7 -- a packet the tool cannot safely rewrite is preserved, announced.
# --------------------------------------------------------------------------- #

PRESERVE_CELLS: Final[tuple[str, ...]] = (*SET_CELLS, "clear_producer")


@pytest.mark.parametrize("cell", PRESERVE_CELLS)
@pytest.mark.parametrize("shape", tuple(PRESERVED))
def test_an_unrewritable_packet_is_preserved_byte_for_byte_and_announced(
    corpus: Any, tmp_path: Path, shape: str, cell: str
) -> None:
    reason = PRESERVED[shape]
    run = run_cell(shape, cell, corpus, tmp_path)

    assert run.returncode == 0, f"rc {run.returncode}; stderr={run.stderr[-400:]!r}"
    item = run.item
    assert item["ok"] is True
    assert item["message"] == _preserved_message(reason)
    assert item["detail"] == {"wrote_xmp": False}
    packet = _packet_warnings(run)
    assert len(packet) == 1
    assert reason in packet[0]
    assert _metadata_bytes(run.out) == run.before, "the packet was not preserved byte-for-byte"

    info = PdfReader(str(run.out)).metadata
    assert info is not None
    if cell == "clear_producer":
        assert "/Producer" not in info
    else:
        assert info[FIELDS[cell][2]] == NEW


# --------------------------------------------------------------------------- #
# AC10 -- `--clear-all` never parses.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("shape", SHAPES)
def test_clear_all_removes_the_packet_on_every_shape_without_parsing_it(
    corpus: Any, tmp_path: Path, shape: str
) -> None:
    run = run_cell(shape, "clear_all", corpus, tmp_path)
    assert run.returncode == 0, f"rc {run.returncode}; stderr={run.stderr[-400:]!r}"
    assert run.item["message"] == "ok"
    assert "/Metadata" not in PdfReader(str(run.out)).trailer["/Root"]


# --------------------------------------------------------------------------- #
# AC9 -- pypdf-authored packets are byte-stable: no declaration is added.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("cell", ("title", "clear_producer"))
@pytest.mark.parametrize("shape", ("xmp_bearing", "on_description"))
def test_a_pypdf_authored_packet_gains_no_namespace_declaration(
    corpus: Any, tmp_path: Path, shape: str, cell: str
) -> None:
    run = run_cell(shape, cell, corpus, tmp_path)
    raw = _assert_parses_under_both(run.out)
    assert raw.count(b"xmlns:") == run.before.count(b"xmlns:"), (
        "the binding step added a declaration to a packet that already bound its prefixes"
    )


# --------------------------------------------------------------------------- #
# AC11 -- the dry run agrees with the real run, on the absolute value 0.
# --------------------------------------------------------------------------- #

DRY_CELLS: Final[tuple[tuple[str, str], ...]] = tuple(
    [(shape, cell) for shape in SHAPES for cell in ALL_CELLS] + [("xmp_pikepdf", "in_place")]
)


@pytest.mark.parametrize(("shape", "cell"), DRY_CELLS)
def test_dry_run_and_real_run_agree_on_zero(
    corpus: Any, tmp_path: Path, shape: str, cell: str
) -> None:
    source, _ = build_shape(shape, corpus, tmp_path)
    dry, real = dry_and_real("meta set", [str(source), *_args(cell, tmp_path / "out.pdf")])

    assert dry.returncode == 0
    assert _envelope(dry)["exit_code"] == 0
    assert prediction(dry)["would_exit"] == 0
    assert real.returncode == 0, f"real rc {real.returncode}; stderr={real.stderr[-400:]!r}"
    assert _envelope(real)["items"][0]["ok"] is True


# --------------------------------------------------------------------------- #
# AC12 -- the invariant: never a bare `ok` over a lost packet.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("shape", "cell"), DRY_CELLS)
def test_a_bare_ok_always_leaves_a_parseable_packet_that_reads_back(
    corpus: Any, tmp_path: Path, shape: str, cell: str
) -> None:
    run = run_cell(shape, cell, corpus, tmp_path)
    message = run.item["message"]
    if cell == "clear_all":
        assert message == "ok"
        assert _metadata_bytes(run.out) is None
    elif message == "ok":
        _assert_parses_under_both(run.out)
        _assert_round_trip(run.out, cell)
    else:
        assert message.startswith("ok (XMP packet left unchanged:"), message
        # BYTE-equality with the input's TRUE on-disk packet (`run.before` is read
        # through pikepdf, never through pypdf's view of an encrypted stream).
        assert _metadata_bytes(run.out) == run.before


def test_the_invariant_arm_covers_encrypted_inputs_and_is_not_vacuous() -> None:
    """The AC12 arm above must have seen encrypted cells, and the qualified
    ("left unchanged") branch must be reachable on one -- otherwise the byte-equality
    assertion against the true packet would be a loop over nothing."""
    encrypted = [(s, c) for s, c in DRY_CELLS if s in ENCRYPTED_SHAPES]
    assert len(encrypted) == len(ENCRYPTED_SHAPES) * len(ALL_CELLS) > 0
    qualified = [(s, c) for s, c in encrypted if s in PRESERVED and c != "clear_all"]
    assert qualified, "no encrypted cell can ever reach the 'left unchanged' branch"


@pytest.mark.parametrize("cell", PRESERVE_CELLS)
def test_an_encrypted_unparseable_packet_is_preserved_as_the_true_bytes(
    corpus: Any, tmp_path: Path, cell: str
) -> None:
    """Ledger `17add7b3e9` at its sharpest: the qualifier fires on a packet that is
    really malformed, and the output carries the stored bytes -- not pypdf's
    mis-decrypted ones."""
    run = run_cell("aes256_nometa_malformed", cell, corpus, tmp_path)
    assert run.returncode == 0, run.stderr[-400:]
    assert run.item["message"] == _preserved_message(REASON_NOT_WELL_FORMED)
    assert _metadata_bytes(run.out) == run.before


# --------------------------------------------------------------------------- #
# AC8 -- the verification is load-bearing (an in-process fault injection).
# --------------------------------------------------------------------------- #


def _adapter_write(corpus: Any, **sets: str) -> tuple[Any, bytes]:
    from pdf_tooling.adapters import pypdf_structure

    data = corpus.path("xmp_pikepdf").read_bytes()
    outcome = pypdf_structure.ADAPTER.write_metadata(data, sets=sets, clears=[], clear_all=False)
    return outcome, data


def _output_packet(outcome: Any) -> bytes:
    import io

    with pikepdf.open(io.BytesIO(outcome.output)) as pdf:
        return bytes(pdf.Root.Metadata.read_bytes())


def test_a_candidate_that_fails_verification_is_not_written(
    corpus: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pdf_tooling.adapters import pypdf_structure

    real = pypdf_structure._serialize_xmp

    def drop_one_declaration(xmp: Any) -> bytes:
        return real(xmp).replace(f' xmlns:dc="{DC}"'.encode(), b"", 1)

    monkeypatch.setattr(pypdf_structure, "_serialize_xmp", drop_one_declaration)
    outcome, data = _adapter_write(corpus, title=NEW)

    assert outcome.xmp_left_unchanged == REASON_UNVERIFIED
    assert outcome.wrote_xmp is False
    assert _output_packet(outcome) == _metadata_bytes_of(data)


def test_a_candidate_with_the_wrong_value_is_not_written(
    corpus: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Well-formed XML that does not say what was asked: only the READ-BACK check
    catches it, because it parses."""
    from pdf_tooling.adapters import pypdf_structure

    real = pypdf_structure._serialize_xmp
    monkeypatch.setattr(
        pypdf_structure, "_serialize_xmp", lambda xmp: real(xmp).replace(NEW.encode(), b"Other")
    )
    outcome, data = _adapter_write(corpus, title=NEW)

    assert outcome.xmp_left_unchanged == REASON_UNVERIFIED
    assert _output_packet(outcome) == _metadata_bytes_of(data)


def test_an_edit_that_raises_is_preserved_not_a_traceback(
    corpus: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pdf_tooling.adapters import pypdf_structure

    def boom(xmp: Any) -> bytes:
        raise RuntimeError("serializer failed")

    monkeypatch.setattr(pypdf_structure, "_serialize_xmp", boom)
    outcome, data = _adapter_write(corpus, keywords=NEW)

    assert outcome.xmp_left_unchanged == REASON_UNVERIFIED
    assert _output_packet(outcome) == _metadata_bytes_of(data)


def _metadata_bytes_of(data: bytes) -> bytes:
    import io

    with pikepdf.open(io.BytesIO(data)) as pdf:
        return bytes(pdf.Root.Metadata.read_bytes())


def test_an_unreadable_packet_date_does_not_block_a_rewrite(corpus: Any, tmp_path: Path) -> None:
    """A date getter that raises on both sides of the edit is not a change the
    rewrite caused: it must not turn every set into a preserve."""
    packet = _packet(
        _description(
            ALL_DECLS, _TITLE + "<xmp:CreateDate>garbage</xmp:CreateDate>" + _PRODUCER + _PDFAID
        )
    )
    source = tmp_path / "bad_date.pdf"
    with pikepdf.open(str(corpus.path("single_page"))) as pdf:
        stream = pdf.make_stream(packet)
        stream["/Type"] = pikepdf.Name.Metadata
        stream["/Subtype"] = pikepdf.Name.XML
        pdf.Root.Metadata = stream
        pdf.save(str(source), fix_metadata_version=False, deterministic_id=True)

    out = tmp_path / "out.pdf"
    result = run_cli("meta set", str(source), "--title", NEW, "-O", str(out), "-o", "json")
    payload = _envelope(result)

    assert result.returncode == 0
    assert payload["items"][0]["message"] == "ok"
    assert PdfReader(str(out)).xmp_metadata.dc_title == {"x-default": NEW}  # type: ignore[union-attr]


def test_an_encrypted_input_whose_true_packet_cannot_be_read_fails_closed(
    corpus: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback for ledger `17add7b3e9`: never write pypdf's mis-decrypted bytes
    when the true ones cannot be obtained -- a typed error, nothing returned."""
    from pdf_tooling.adapters import pypdf_structure
    from pdf_tooling.errors import FailureError

    source, _ = build_shape("aes256_nometa", corpus, tmp_path)
    data = source.read_bytes()

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise pikepdf.PdfError("injected")

    monkeypatch.setattr(pikepdf, "open", refuse)
    with pytest.raises(FailureError, match="could not read this document's XMP packet"):
        pypdf_structure.ADAPTER.write_metadata(
            data, sets={"title": NEW}, clears=[], clear_all=False
        )
