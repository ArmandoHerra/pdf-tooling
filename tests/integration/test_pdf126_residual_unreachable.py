"""PDF-126 -- ``meta get`` reports unreferenced metadata objects and prior revisions.

Ledger ``c8661d9f85``: ``residual_surfaces`` could not see (a) a metadata object
the file holds but nothing references (the ``--clear-all`` orphan of ``350c89b83c``)
or (b) an earlier revision kept by an incremental save (the ``exiftool -all=``
reversible-strip shape). Two integer sub-keys, ``unreferenced_metadata`` and
``prior_revisions``, now report both. This module drives the CLI as a subprocess
AND ``meta_get_run`` in-process; the two must agree.

Fixtures are built in-process (never added to ``tests/corpus.py``, which would
move every corpus-driven census). Sentinels are HYPHEN-FREE: pypdf serialises
``-`` as ``\\055`` so a hyphenated sentinel misses a literal grep. ``exiftool`` is
never invoked: X-EXIF is a byte-for-byte emulation of its update shape.

Every positive control runs before the count it supports.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Final

import pikepdf
import pypdf
import pytest
from pikepdf import Name
from pypdf.generic import DictionaryObject, NameObject, StreamObject, TextStringObject

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from corpus import ENCRYPTED_PASSWORD, build_corpus  # noqa: E402
from pdf_tooling.cli.password import plan_password  # noqa: E402
from pdf_tooling.ops.document_password import NO_PASSWORD  # noqa: E402
from pdf_tooling.ops.metadata import meta_get_run  # noqa: E402
from registry import run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

OLD_KEYS: Final = (
    "page_xmp_pages",
    "doc_piece_info",
    "page_piece_info_pages",
    "annotation_authors",
    "embedded_files",
    "trailer_id",
)
NEW_KEYS: Final = ("unreferenced_metadata", "prior_revisions")

S_XMP: Final = b"SENTINELXMPORPHAN4R"
S_INFO: Final = b"SENTINELINFOORPHAN7Q"
S_OLD: Final = b"SENTINELOLDREV3M8P"
S_EXIF_INFO: Final = b"SENTINELEXIFAUTH1A"
S_EXIF_XMP: Final = b"SENTINELEXIFXMP2B"
PW: Final = "u"


def _packet(creator: str) -> bytes:
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:creator><rdf:Seq><rdf:li>{creator}</rdf:li></rdf:Seq></dc:creator>"
        '</rdf:Description></rdf:RDF></x:xmpmeta>\n<?xpacket end="w"?>'
    ).encode()


# --------------------------------------------------------------------------- #
# Fixture builders
# --------------------------------------------------------------------------- #


def _pikepdf(
    path: Path, *, pages: int = 1, author: bytes = S_INFO, xmp: bytes | None = S_XMP, **save: Any
) -> None:
    pdf = pikepdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=(612, 792))
    pdf.docinfo["/Author"] = author.decode()
    if xmp is not None:
        stream = pikepdf.Stream(pdf, _packet(xmp.decode()))
        stream.Type = Name.Metadata
        stream.Subtype = Name.XML
        pdf.Root.Metadata = pdf.make_indirect(stream)
    options: dict[str, Any] = {
        "compress_streams": False,
        "object_stream_mode": pikepdf.ObjectStreamMode.disable,
    }
    options.update(save)
    pdf.save(path, **options)


def _orphan_stream(*, flate: bool) -> StreamObject:
    stream = StreamObject()
    stream.set_data(_packet(S_XMP.decode()))
    stream[NameObject("/Type")] = NameObject("/Metadata")
    stream[NameObject("/Subtype")] = NameObject("/XML")
    return stream.flate_encode() if flate else stream


def _pypdf_orphan(path: Path, *, kind: str, encrypt: bool = False) -> None:
    writer = pypdf.PdfWriter()
    writer.add_blank_page(612, 792)
    writer.add_metadata({"/Title": "live title"})
    if kind == "info":
        writer._add_object(  # noqa: SLF001 - the offline m1 shape
            DictionaryObject({NameObject("/Author"): TextStringObject(S_INFO.decode())})
        )
    else:
        writer._add_object(_orphan_stream(flate=kind == "flate"))  # noqa: SLF001
    if encrypt:
        writer.encrypt(PW, algorithm="AES-256")
    with path.open("wb") as handle:
        writer.write(handle)


def _pypdf_incremental(src: Path, dest: Path, author: str = "NEWREVAUTHOR5T1X") -> None:
    writer = pypdf.PdfWriter(str(src), incremental=True)
    writer.add_metadata({"/Author": author})
    with dest.open("wb") as handle:
        writer.write(handle)


def _append_exiftool_update(path: Path) -> None:
    """E5's update, byte for byte in shape: catalogue rewritten without
    /Metadata, the /Info and XMP objects freed at generation 1, a trailer with
    no /Info and /Prev = the old startxref."""
    original = path.read_bytes()
    old_startxref = int(re.findall(rb"startxref\s+(\d+)", original)[-1])
    with pikepdf.open(path) as pdf:
        root = pdf.Root.objgen[0]
        pages = pdf.Root.Pages.objgen[0]
        info = pdf.trailer.Info.objgen[0]
        xmp = pdf.Root.Metadata.objgen[0]
        size = int(pdf.trailer.Size)
        ident = bytes(pdf.trailer.ID[0]).hex()
    body = bytearray(original)
    body += b"\n%BeginExifToolUpdate\n"
    root_at = len(body)
    body += f"{root} 0 obj\n<< /Pages {pages} 0 R /Type /Catalog >>\nendobj\n".encode()
    xref_at = len(body)
    body += b"xref\n"
    body += f"{root} 1\n{root_at:010d} 00000 n \n".encode()
    for freed in (info, xmp):
        body += f"{freed} 1\n0000000000 00001 f \n".encode()
    body += (
        f"trailer\n<< /Root {root} 0 R /Size {size} /ID [<{ident}> <{ident}>] "
        f"/Prev {old_startxref} >>\n"
    ).encode()
    body += f"%EndExifToolUpdate {xref_at - root_at}\nstartxref\n{xref_at}\n%%EOF\n".encode()
    path.write_bytes(bytes(body))


@pytest.fixture(scope="module")
def fx(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("pdf126")
    out: dict[str, Path] = {}

    def at(name: str) -> Path:
        out[name] = d / f"{name}.pdf"
        return out[name]

    _pypdf_orphan(at("X-ORPHAN-RAW"), kind="raw")
    _pypdf_orphan(at("X-ORPHAN-FLATE"), kind="flate")
    _pypdf_orphan(at("X-ORPHAN-INFO"), kind="info")
    _pikepdf(d / "incr_base.pdf", xmp=None, author=S_OLD)
    _pypdf_incremental(d / "incr_base.pdf", at("X-INCR"))
    _pikepdf(at("X-EXIF"), author=S_EXIF_INFO, xmp=S_EXIF_XMP)
    _append_exiftool_update(out["X-EXIF"])
    _pikepdf(at("X-LIN"), pages=4, linearize=True)
    _pikepdf(d / "lin_base.pdf", pages=4, linearize=True)
    _pypdf_incremental(d / "lin_base.pdf", at("X-LIN-INCR"))
    _pikepdf(at("X-OBJSTM"), pages=3, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    _pikepdf(d / "objstm_base.pdf", pages=3, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    _pypdf_incremental(d / "objstm_base.pdf", at("X-OBJSTM-INCR"))
    _pypdf_orphan(at("X-AES"), kind="raw", encrypt=True)
    raw = out["X-INCR"].read_bytes()
    off = len(raw)
    root = re.findall(rb"/Root (\d+ \d+ R)", raw)[-1]
    cycle = (
        b"\nxref\n0 1\n0000000000 65535 f \ntrailer\n<< /Size 1 /Root "
        + root
        + b" /Prev %d >>\nstartxref\n%d\n%%%%EOF\n" % (off + 1, off + 1)
    )
    at("X-CYCLE").write_bytes(raw + cycle)
    pw = d / "pw.txt"
    pw.write_text(PW)
    pw.chmod(0o600)
    out["pw"] = pw
    return out


# --------------------------------------------------------------------------- #
# Readers: CLI JSON and in-process, which must agree
# --------------------------------------------------------------------------- #


def _cli(path: Path, *extra: str, fmt: str = "json") -> dict[str, Any]:
    result = run_cli("meta get", str(path), "-o", fmt, *extra)
    assert result.returncode == 0, result.stderr
    payload: dict[str, Any] = json.loads(result.stdout.splitlines()[0])
    return payload


def _inproc(path: Path, password_file: Path | None = None) -> dict[str, Any]:
    password = NO_PASSWORD
    if password_file is not None:
        password = plan_password(
            slot="password",
            flag="--password-file",
            value=str(password_file),
            env_names=(),
            prompt="x: ",
            allow_empty=True,
        )
    return dict(meta_get_run(path, xmp=False, password=password).residual_surfaces)


def counts(path: Path, password_file: Path | None = None) -> tuple[int, int]:
    extra = ("--password-file", str(password_file)) if password_file else ()
    payload = _cli(path, *extra)
    assert payload["schema_version"] == 1
    cli = payload["residual_surfaces"]
    mem = _inproc(path, password_file)
    assert cli == mem, "CLI JSON and in-process residual_surfaces disagree"
    return cli["unreferenced_metadata"], cli["prior_revisions"]


# --------------------------------------------------------------------------- #
# Positive controls (premises, by byte / object inspection)
# --------------------------------------------------------------------------- #


def _reader_facts(path: Path) -> pypdf.PdfReader:
    return pypdf.PdfReader(str(path))


def test_pc_orphan_fixtures_hold_a_listed_metadata_object_nothing_references(fx) -> None:
    for name in ("X-ORPHAN-RAW", "X-ORPHAN-FLATE"):
        reader = _reader_facts(fx[name])
        meta_objs = [
            n
            for entries in reader.xref.values()
            for n in entries
            if (o := reader.get_object(pypdf.generic.IndirectObject(n, 0, reader))) is not None
            and isinstance(o, StreamObject)
            and o.get("/Type") == "/Metadata"
        ]
        assert len(meta_objs) == 1, name
        assert "/Metadata" not in reader.trailer["/Root"], name
    assert S_XMP in fx["X-ORPHAN-RAW"].read_bytes()
    assert S_XMP not in fx["X-ORPHAN-FLATE"].read_bytes()  # Flate: blind to a grep
    assert S_INFO in fx["X-ORPHAN-INFO"].read_bytes()


def test_pc_exif_fixture_is_the_reversible_strip_shape(fx) -> None:
    raw = fx["X-EXIF"].read_bytes()
    assert S_EXIF_INFO in raw
    assert S_EXIF_XMP in raw
    assert raw.count(b"startxref") == 2
    reader = _reader_facts(fx["X-EXIF"])
    assert "/Metadata" not in reader.trailer["/Root"]
    assert b"/Info" not in raw[raw.rindex(b"trailer") :]


def test_pc_linearized_fixtures_lead_with_the_linearization_dict(fx) -> None:
    head = fx["X-LIN"].read_bytes()[:1024]
    assert b"/Linearized" in head
    assert fx["X-LIN"].read_bytes().count(b"startxref") == 2  # keywords alone cannot tell


def test_pc_objstm_incr_final_section_is_recorded(fx) -> None:
    """AC6's premise: at least one section of X-OBJSTM-INCR is an xref STREAM
    carrying /Prev. Recorded at landing: pypdf's incremental writer itself
    emits the xref stream, so no hand-appended section is needed."""
    raw = fx["X-OBJSTM-INCR"].read_bytes()
    assert raw.count(b"startxref") == 2
    final = int(re.findall(rb"startxref\s+(\d+)", raw)[-1])
    section = raw[final : final + 400]
    assert not section.startswith(b"xref"), "pypdf emitted a classic table: hand-append instead"
    assert b"/XRef" in section
    assert b"/Prev" in section


# --------------------------------------------------------------------------- #
# AC1..AC9
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["X-ORPHAN-RAW", "X-ORPHAN-FLATE"])
def test_ac1_an_unreferenced_xmp_stream_is_counted(fx, name: str) -> None:
    assert counts(fx[name]) == (1, 0)


def test_ac2_an_unreferenced_info_shaped_dict_is_counted_and_the_live_info_is_not(fx) -> None:
    payload = _cli(fx["X-ORPHAN-INFO"])
    assert payload["info"].get("Title") == "live title"
    assert counts(fx["X-ORPHAN-INFO"]) == (1, 0)


def test_ac3_the_exiftool_reversible_strip_shape_is_counted_on_both_keys(fx) -> None:
    assert counts(fx["X-EXIF"]) == (2, 1)


def test_ac4_a_pypdf_incremental_update_is_a_prior_revision(fx) -> None:
    assert S_OLD in fx["X-INCR"].read_bytes()  # premise: the old value is still in the file
    assert counts(fx["X-INCR"]) == (0, 1)


def test_ac5_a_linearized_file_is_one_revision_and_an_update_to_it_is_one_more(fx) -> None:
    assert counts(fx["X-LIN"]) == (0, 0)
    assert counts(fx["X-LIN-INCR"]) == (0, 1)


def test_ac6_xref_stream_sections_are_walked(fx) -> None:
    assert counts(fx["X-OBJSTM"]) == (0, 0)
    assert counts(fx["X-OBJSTM-INCR"]) == (0, 1)


def test_ac7_a_broken_chain_fails_high_and_terminates(fx) -> None:
    result = run_cli("meta get", str(fx["X-CYCLE"]), "-o", "json")
    assert result.returncode == 0
    assert counts(fx["X-CYCLE"]) == (0, 2)


def test_ac8_no_false_positive_on_the_corpus_or_the_controls(
    fx, tmp_path_factory: pytest.TempPathFactory
) -> None:
    built = build_corpus(tmp_path_factory.mktemp("pdf126corpus"))
    names = built.names()
    assert names, "the corpus census must derive its population"
    for name in names:
        path = built.path(name)
        if path.suffix.lower() != ".pdf":
            continue
        if name == "encrypted_aes256":
            pwf = path.parent / "corpus.pw"
            pwf.write_text(ENCRYPTED_PASSWORD)
            pwf.chmod(0o600)
            assert counts(path, pwf) == (0, 0), name
        else:
            assert counts(path) == (0, 0), name
    assert counts(fx["X-LIN"]) == (0, 0)
    assert counts(fx["X-OBJSTM"]) == (0, 0)


def test_ac9_encrypted_input_counts_after_authentication_and_exits_6_without_one(fx) -> None:
    assert counts(fx["X-AES"], fx["pw"]) == (1, 0)
    result = run_cli("meta get", str(fx["X-AES"]), "-o", "json")
    assert result.returncode == 6


# --------------------------------------------------------------------------- #
# AC10 rendering, AC13 help
# --------------------------------------------------------------------------- #


def test_ac10_json_and_ndjson_carry_eight_keys_and_the_new_two_are_ints(fx) -> None:
    for fmt in ("json", "ndjson"):
        payload = _cli(fx["X-EXIF"], fmt=fmt)
        residual = payload["residual_surfaces"]
        assert list(residual) == [*OLD_KEYS, *NEW_KEYS]
        assert all(type(residual[k]) is int for k in NEW_KEYS)
    nd = run_cli("meta get", str(fx["X-EXIF"]), "-o", "ndjson")
    assert len(nd.stdout.strip().splitlines()) == 1


def test_ac10_table_shows_the_held_but_not_reachable_block_apart_from_the_old_one(
    fx, corpus
) -> None:
    out = run_cli("meta get", str(fx["X-EXIF"]), "-o", "table").stdout
    lines = out.splitlines()
    i = lines.index("Held but not reachable")
    assert lines[i + 1 : i + 3] == ["  unreferenced_metadata: 2", "  prior_revisions: 1"]
    old = lines[lines.index("Not cleared by --clear-all") : i]
    assert not any(k in line for line in old for k in NEW_KEYS)
    clean = run_cli("meta get", str(corpus.path("single_page")), "-o", "table").stdout.splitlines()
    j = clean.index("Held but not reachable")
    assert clean[j + 1 : j + 3] == ["  unreferenced_metadata: 0", "  prior_revisions: 0"]


def test_ac13_help_text_states_the_residue_and_the_clear_all_claim() -> None:
    get_help = " ".join(run_cli("meta get", "--help").stdout.split())
    for needle in ("unreferenced_metadata", "prior_revisions", "never removes anything"):
        assert needle in get_help
    set_help = " ".join(run_cli("meta set", "--help").stdout.split())
    assert "Held but not reachable" in set_help
    assert "holds neither" in set_help
    for word in ("--clear-all", "page", "PieceInfo", "annotation"):
        assert word in set_help


# --------------------------------------------------------------------------- #
# AC12 round trip, AC15, AC16
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name",
    ["X-ORPHAN-RAW", "X-ORPHAN-FLATE", "X-ORPHAN-INFO", "X-INCR", "X-EXIF", "X-LIN-INCR"],
)
def test_ac12_meta_set_clear_all_leaves_neither_surface(fx, tmp_path: Path, name: str) -> None:
    assert counts(fx[name]) != (0, 0), "positive control: the input must be non-zero"
    dest = tmp_path / "out.pdf"
    result = run_cli("meta set", str(fx[name]), "--clear-all", "-O", str(dest))
    assert result.returncode == 0, result.stderr
    assert counts(dest) == (0, 0)
    body = dest.read_bytes()
    for sentinel in (S_XMP, S_INFO, S_OLD, S_EXIF_INFO, S_EXIF_XMP):
        assert sentinel not in body


def test_ac15_schema_version_is_1_and_the_six_old_keys_keep_their_order(fx) -> None:
    for name in ("X-EXIF", "X-LIN-INCR", "X-OBJSTM-INCR"):
        payload = _cli(fx[name])
        assert payload["schema_version"] == 1
        assert list(payload["residual_surfaces"])[:6] == list(OLD_KEYS)


def test_ac16_the_c8661d9f85_repro_shapes(fx, tmp_path: Path) -> None:
    assert counts(fx["X-INCR"])[1] == 1  # arm (b)
    assert counts(fx["X-ORPHAN-RAW"])[0] == 1  # arm (a), built offline
    pdf = pikepdf.new()
    for _ in range(2):
        pdf.add_blank_page(page_size=(612, 792))
    page_xmp = pikepdf.Stream(pdf, _packet("PAGETWOXMP"))
    page_xmp.Type = Name.Metadata
    page_xmp.Subtype = Name.XML
    pdf.pages[1].obj.Metadata = pdf.make_indirect(page_xmp)
    control = tmp_path / "control.pdf"
    pdf.save(control, compress_streams=False, object_stream_mode=pikepdf.ObjectStreamMode.disable)
    payload = _cli(control)
    assert payload["residual_surfaces"]["page_xmp_pages"] == [2]
    assert counts(control) == (0, 0)
