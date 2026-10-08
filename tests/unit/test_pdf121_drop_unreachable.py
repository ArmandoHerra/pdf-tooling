"""PDF-121 -- ``_drop_unreachable``: the one sweep at both pypdf write seams.

In-process arms over pypdf writers. The subprocess matrix that proves the
CLI outputs hold nothing the clear removed is
``tests/integration/test_pdf121_clear_all_remanence.py``.

* U1 -- an injected orphan chain (a stream that references a dict) is nulled, a
  reader-owned reference is left alone, and a dangling or cyclic reference is safe.
* U2 -- each root kind survives: ``/Info``, ``/ID`` (an INDIRECT one, the only
  shape where the root matters) and ``/Encrypt`` (the output opens with its password).
* U3 -- byte identity: for orphan-free inputs the output with the sweep equals the
  output with the sweep monkeypatched to a no-op. The in-process form of E5's 21/21.
  No sha literals: pikepdf-built fixtures randomise ``/ID[1]``.
* U4 -- the fail-closed canary: a renamed pypdf private raises, never passes.
"""

from __future__ import annotations

import io
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pikepdf
import pypdf
import pytest
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    StreamObject,
    TextStringObject,
)

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

import remanence as R  # noqa: E402
from pdf_tooling.adapters import pypdf_structure  # noqa: E402
from pdf_tooling.adapters.pypdf_structure import (  # noqa: E402
    PypdfStructureAdapter,
    _drop_unreachable,
)


def blank_writer() -> pypdf.PdfWriter:
    writer = pypdf.PdfWriter()
    writer.add_blank_page(612, 792)
    return writer


def orphan_chain(writer: pypdf.PdfWriter) -> tuple[IndirectObject, IndirectObject]:
    """An unreferenced stream that references an unreferenced dict."""
    inner = writer._add_object(  # noqa: SLF001
        DictionaryObject({NameObject("/Note"): TextStringObject("SENT-CHAIN")})
    )
    stream = StreamObject()
    stream.set_data(b"SENT-PREORPHAN")
    stream[NameObject("/PieceRef")] = inner
    return writer._add_object(stream), inner  # noqa: SLF001


def slot(writer: pypdf.PdfWriter, ref: IndirectObject) -> Any:
    return writer._objects[ref.idnum - 1]  # noqa: SLF001


def pdf_with_indirect_id() -> bytes:
    """A hand-written PDF whose trailer ``/ID`` is an INDIRECT array (object 4)."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>",
        b"[<00112233445566778899aabbccddeeff> <00112233445566778899aabbccddeeff>]",
    ]
    out = bytearray(b"%PDF-1.7\n")
    offsets: list[int] = []
    for number, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref_at = len(out)
    out += b"xref\n0 5\n0000000000 65535 f \n"
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size 5 /Root 1 0 R /ID 4 0 R >>\nstartxref\n%d\n%%%%EOF\n" % xref_at
    return bytes(out)


# --------------------------------------------------------------------------- #
# U1
# --------------------------------------------------------------------------- #


def test_u1_orphan_chain_is_nulled_and_every_root_survives() -> None:
    writer = blank_writer()
    writer.add_metadata({"/Author": "kept"})
    stream_ref, inner_ref = orphan_chain(writer)
    root_ref = writer._root_object.indirect_reference  # noqa: SLF001
    info_ref = writer._info_obj  # noqa: SLF001
    page_ref = writer.pages[0].indirect_reference

    _drop_unreachable(writer)

    assert slot(writer, stream_ref) is None, "the unreferenced stream must be nulled"
    assert slot(writer, inner_ref) is None, "the dict only the orphan stream reached must be nulled"
    for kept in (root_ref, info_ref, page_ref):
        assert slot(writer, kept) is not None
    buffer = io.BytesIO()
    writer.write(buffer)
    assert b"SENT-CHAIN" not in buffer.getvalue()
    assert b"SENT-PREORPHAN" not in buffer.getvalue()


def test_u1_walk_leaves_foreign_dangling_and_cyclic_references_safe() -> None:
    writer = blank_writer()
    reader = pypdf.PdfReader(io.BytesIO(pdf_with_indirect_id()))
    count = len(writer._objects)  # noqa: SLF001
    loop_a = writer._add_object(DictionaryObject())  # noqa: SLF001
    loop_b = writer._add_object(DictionaryObject({NameObject("/Next"): loop_a}))  # noqa: SLF001
    loop_a.get_object()[NameObject("/Next")] = loop_b
    root = writer._root_object  # noqa: SLF001
    root[NameObject("/Foreign")] = IndirectObject(1, 0, reader)  # a READER reference
    root[NameObject("/Dangling")] = IndirectObject(count + 500, 0, writer)
    root[NameObject("/Zero")] = IndirectObject(0, 0, writer)
    root[NameObject("/Loop")] = ArrayObject([loop_a])

    _drop_unreachable(writer)

    assert slot(writer, loop_a) is not None and slot(writer, loop_b) is not None
    assert root.raw_get("/Foreign").pdf is reader, "a reader reference is left exactly as it was"


# --------------------------------------------------------------------------- #
# U2
# --------------------------------------------------------------------------- #


def test_u2_info_root_is_kept() -> None:
    writer = blank_writer()
    writer.add_metadata({"/Author": "SENT-INFO"})
    info_ref = writer._info_obj  # noqa: SLF001
    _drop_unreachable(writer)
    assert slot(writer, info_ref) is not None, "the /Info root was dropped"
    buffer = io.BytesIO()
    writer.write(buffer)
    with pikepdf.open(io.BytesIO(buffer.getvalue())) as pdf:
        assert str(pdf.docinfo["/Author"]) == "SENT-INFO"


def test_u2_id_root_is_kept_when_the_trailer_id_is_an_indirect_object() -> None:
    reader = pypdf.PdfReader(io.BytesIO(pdf_with_indirect_id()))
    writer = pypdf.PdfWriter(clone_from=reader)
    id_index = next(i for i, o in enumerate(writer._objects) if o is writer._ID)  # noqa: SLF001
    _drop_unreachable(writer)
    assert writer._objects[id_index] is writer._ID, "the /ID root was dropped"  # noqa: SLF001
    buffer = io.BytesIO()
    writer.write(buffer)
    with pikepdf.open(io.BytesIO(buffer.getvalue())) as pdf:
        assert len(pdf.trailer["/ID"]) == 2


def test_u2_encrypt_root_is_kept_and_the_output_opens_with_its_password() -> None:
    writer = blank_writer()
    writer.add_blank_page(612, 792)
    writer.encrypt("u-secret", "o-secret")
    entry = writer._encrypt_entry  # noqa: SLF001
    _drop_unreachable(writer)
    assert entry in writer._objects, "the /Encrypt root was dropped"  # noqa: SLF001
    buffer = io.BytesIO()
    writer.write(buffer)
    with pikepdf.open(io.BytesIO(buffer.getvalue()), password="u-secret") as pdf:
        assert len(pdf.pages) == 2


# --------------------------------------------------------------------------- #
# U3
# --------------------------------------------------------------------------- #


def _meta_author(path: Path) -> bytes:
    outcome = PypdfStructureAdapter().write_metadata(
        path.read_bytes(), sets={"author": "X"}, clears=[], clear_all=False
    )
    return outcome.output


def _page_write(path: Path) -> bytes:
    adapter = PypdfStructureAdapter()
    writer = adapter.new_writer()
    with adapter.open_document(path) as document:
        writer.append_pages(document, [1, 2])
        buffer = io.BytesIO()
        writer.write(buffer)
    return buffer.getvalue()


U3_CASES: dict[str, tuple[str, Callable[[Path], bytes]]] = {
    "meta-set-author-N": ("N", _meta_author),
    "meta-set-author-U": ("U", _meta_author),
    "meta-set-author-A": ("A", _meta_author),
    "page-write-N": ("N", _page_write),
}


@pytest.mark.parametrize("case", sorted(U3_CASES))
def test_orphan_free_output_is_byte_identical(
    case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, produce = U3_CASES[case]
    source = R.build_fixtures(tmp_path)[fixture]
    with_sweep = produce(source)
    monkeypatch.setattr(pypdf_structure, "_drop_unreachable", lambda writer: None)
    without_sweep = produce(source)
    assert with_sweep == without_sweep, f"{case}: the sweep changed an orphan-free output"


# --------------------------------------------------------------------------- #
# U4
# --------------------------------------------------------------------------- #


def test_u4_canary_clean_on_the_installed_pypdf() -> None:
    writer = blank_writer()
    stream_ref, _ = orphan_chain(writer)
    _drop_unreachable(writer)
    assert slot(writer, stream_ref) is None, (
        f"the sweep no longer works on pypdf {pypdf.__version__}"
    )


PRIVATES = ("_objects", "_root_object", "_info_obj", "_ID", "_encrypt_entry")


@pytest.mark.parametrize("missing", PRIVATES)
def test_u4_a_renamed_pypdf_private_raises_instead_of_passing_silently(missing: str) -> None:
    real = blank_writer()
    double = types.SimpleNamespace(**{name: getattr(real, name) for name in PRIVATES})
    delattr(double, missing)
    with pytest.raises(AttributeError):
        _drop_unreachable(double)


def test_u4_a_writer_double_without_objects_raises() -> None:
    with pytest.raises(AttributeError):
        _drop_unreachable(types.SimpleNamespace())
