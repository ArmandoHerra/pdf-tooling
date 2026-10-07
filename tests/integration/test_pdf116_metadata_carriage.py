"""PDF-116 -- the page-rebuild verbs carry the input's /Info and XMP.

The nine page-rebuild verbs used to write ``/Info == {/Producer: pypdf}`` and no
XMP packet whatever the input held (ledger ``f4d02eab86``). The seam is one: the
adapter's ``PypdfStructureWriter`` carries its donor's (the first document whose
pages it appends) /Info and XMP at ``write()``. This module is the carriage
matrix and the driven red controls.

Oracle (D10): source truth is read with pikepdf and the password. ``/Info`` is
compared key by key on ``unparse()`` (type-sensitive: the name ``/False`` is not
the string ``(/False)``), including the absence of the trailer entry; XMP is
compared as ``Root.Metadata.read_bytes()``, or both absent. Encrypted shapes run
under ``--allow-decrypted-output`` (PDF-115); without it they are refused at 5,
which is PDF-115's arm.
"""

from __future__ import annotations

import dataclasses
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final, NamedTuple

import pikepdf
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_tooling.ops import carriage, carriage_decl  # noqa: E402
from pdf_tooling.ops.carriage import CARRIAGE, Drop  # noqa: E402
from pdf_tooling.ports.structure import CarriageFacts  # noqa: E402
from registry import INVOCATIONS, run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: D1's REBUILD population, written literally with its provenance: the verbs
#: whose CARRIAGE row had /Info and XMP `Drop.DROPS` at `9809a7f` (PDF-108's set).
REBUILD_AT_9809A7F: Final[frozenset[str]] = frozenset(
    {"rotate", "extract", "delete", "reorder", "merge", "split", "watermark", "stamp", "ocr"}
)
NON_MERGE: Final[tuple[str, ...]] = (
    "rotate",
    "extract",
    "delete",
    "reorder",
    "split",
    "watermark",
    "stamp",
    "ocr",
)
ALL_VERBS: Final[tuple[str, ...]] = (*NON_MERGE, "merge")

SHAPES: Final[tuple[str, ...]] = (
    "plain",
    "aes",
    "emf-rc4",
    "emf-aes",
    "owner-only",
    "no-info",
    "info-only",
    "none",
)
ENCRYPTED: Final[frozenset[str]] = frozenset({"aes", "emf-rc4", "emf-aes", "owner-only"})
NEEDS_PASSWORD: Final[frozenset[str]] = frozenset({"aes", "emf-rc4", "emf-aes"})
USER_PASSWORD: Final[str] = "user-secret"
OWNER_PASSWORD: Final[str] = "owner-secret"
FLAG: Final[str] = "--allow-decrypted-output"

W_ENC_MARK: Final[str] = "input is encrypted"
W_META_MARK: Final[str] = "does not carry"
W_UNCHECKED_MARK: Final[str] = "not checked"


def w_enc(label: str, verb: str) -> str:
    return f"{label}: input is encrypted; {verb} writes its output unencrypted"


def w_meta(label: str, verb: str, parts: str) -> str:
    return f"{label}: {verb} does not carry the input's {parts} to its output"


def w_unchecked(label: str, verb: str) -> str:
    return (
        f"{label}: {verb} carries no document /Info or XMP metadata packet to its output; "
        "the input needs a password to read, so whether it has either was not checked"
    )


# --------------------------------------------------------------------------- #
# Inputs, built once per session
# --------------------------------------------------------------------------- #

_INFO: Final[dict[str, str]] = {
    "/Author": "An Author",
    "/Subject": "A Subject",
    "/Keywords": "k1, k2",
    "/Creator": "A Creator",
    "/Producer": "A Source Producer",
    "/CreationDate": "D:20200101120000Z",
    "/ModDate": "D:20210202130000Z",
}


class Inputs(NamedTuple):
    files: dict[str, Path]
    user_pw: Path
    owner_pw: Path
    root: Path
    corpus: Any

    def password_args(self, shape: str) -> list[str]:
        return ["--password-file", str(self.user_pw)] if shape in NEEDS_PASSWORD else []

    def password(self, shape: str) -> str:
        return USER_PASSWORD if shape in NEEDS_PASSWORD else ""


def _build(base: Path, dest: Path, *, info: bool, xmp: bool) -> None:
    with pikepdf.Pdf.open(base) as pdf:
        if "/Info" in pdf.trailer:
            del pdf.trailer["/Info"]
        if info:
            pdf.docinfo["/Title"] = "Résumé ✓"
            for key, value in _INFO.items():
                pdf.docinfo[key] = value
            pdf.docinfo["/Trapped"] = pikepdf.Name("/False")
        if xmp:
            packet = (
                '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
                '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf='
                '"http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description '
                'rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                '<dc:title><rdf:Alt><rdf:li xml:lang="x-default">Résumé</rdf:li></rdf:Alt>'
                '</dc:title></rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
            ).encode()
            pdf.Root.Metadata = pdf.make_stream(packet)
            pdf.Root.Metadata.Type = pikepdf.Name.Metadata
            pdf.Root.Metadata.Subtype = pikepdf.Name.XML
        pdf.save(dest)


@pytest.fixture(scope="session")
def inputs(corpus: Any, tmp_path_factory: pytest.TempPathFactory) -> Inputs:
    root = tmp_path_factory.mktemp("pdf116")
    base = corpus.path("multipage_text")
    files: dict[str, Path] = {}
    for name, info, xmp in (
        ("plain", True, True),
        ("no-info", False, True),
        ("info-only", True, False),
        ("none", False, False),
    ):
        files[name] = root / f"{name}.pdf"
        _build(base, files[name], info=info, xmp=xmp)
    user_pw = root / "user.pw"
    owner_pw = root / "owner.pw"
    user_pw.write_text(USER_PASSWORD + "\n")
    owner_pw.write_text(OWNER_PASSWORD + "\n")
    user_pw.chmod(0o600)
    owner_pw.chmod(0o600)

    def encrypt(dest: str, *extra: str) -> Path:
        out = root / dest
        proc = run_cli("encrypt", str(files["plain"]), "-O", str(out), *extra)
        assert proc.returncode == 0, proc.stderr
        return out

    both = ("--user-password-file", str(user_pw), "--owner-password-file", str(owner_pw))
    files["aes"] = encrypt("aes.pdf", *both)
    files["emf-rc4"] = encrypt("emf-rc4.pdf", *both, "--legacy")
    files["owner-only"] = encrypt("owner-only.pdf", "--owner-password-file", str(owner_pw))
    emf_aes = root / "emf-aes.pdf"
    with pikepdf.Pdf.open(files["plain"]) as pdf:
        pdf.save(
            emf_aes,
            encryption=pikepdf.Encryption(
                user=USER_PASSWORD, owner=OWNER_PASSWORD, R=6, aes=True, metadata=False
            ),
        )
    files["emf-aes"] = emf_aes
    return Inputs(files, user_pw, owner_pw, root, corpus)


# --------------------------------------------------------------------------- #
# The oracle
# --------------------------------------------------------------------------- #


def info_of(path: Path, password: str = "") -> dict[str, str] | None:
    """The trailer /Info as ``{key: unparse()}``, or ``None`` when there is none."""
    with pikepdf.Pdf.open(path, password=password) as pdf:
        if "/Info" not in pdf.trailer:
            return None
        return {str(k): v.unparse().decode() for k, v in pdf.trailer["/Info"].items()}


def xmp_of(path: Path, password: str = "") -> bytes | None:
    with pikepdf.Pdf.open(path, password=password) as pdf:
        stream = pdf.Root.get("/Metadata")
        return None if stream is None else bytes(stream.read_bytes())


def truth(inputs: Inputs, shape: str) -> tuple[dict[str, str] | None, bytes | None]:
    path = inputs.files[shape]
    pw = inputs.password(shape)
    return info_of(path, pw), xmp_of(path, pw)


def assert_equal_to_source(path: Path, inputs: Inputs, shape: str) -> None:
    want_info, want_xmp = truth(inputs, shape)
    assert info_of(path) == want_info, (path, shape)
    assert xmp_of(path) == want_xmp, (path, shape)


# --------------------------------------------------------------------------- #
# The cell runner
# --------------------------------------------------------------------------- #


class Run(NamedTuple):
    rc: int
    env: dict[str, Any]
    stderr: str

    @property
    def warnings(self) -> list[str]:
        return list(self.env.get("warnings", []))


def parse(proc: subprocess.CompletedProcess[str]) -> Run:
    text = proc.stdout.strip()
    env: dict[str, Any] = json.loads(text) if text.startswith("{") else {}
    return Run(proc.returncode, env, proc.stderr)


def _template(verb: str, inputs: Inputs) -> list[str]:
    """The verb's registered flags, minus operand and destination (PDF-108's technique)."""
    scratch = inputs.root / "tmpl" / verb
    scratch.mkdir(parents=True, exist_ok=True)
    argv = INVOCATIONS[verb].build(inputs.corpus, scratch)
    kept: list[str] = []
    skip = False
    for token in argv[1:]:
        if skip:
            skip = False
            continue
        if token in ("-O", "--output", "--out-dir"):
            skip = True
            continue
        kept.append(token)
    return kept


def argv_for(verb: str, shape: str, inputs: Inputs, dest: Path) -> list[str]:
    src = str(inputs.files[shape])
    if verb == "merge":
        args = [src, "-O", str(dest / "out.pdf")]
    elif verb == "split":
        args = [src, *_template(verb, inputs), "--out-dir", str(dest / "parts")]
    else:
        args = [src, *_template(verb, inputs), "-O", str(dest / "out.pdf")]
    if shape in ENCRYPTED:
        args.append(FLAG)
    return [*args, *inputs.password_args(shape)]


class Cell(NamedTuple):
    dry: Run
    real: Run
    dest: Path
    dry_wrote: list[str]

    def outputs(self) -> list[Path]:
        return sorted(self.dest.rglob("*.pdf"))


class Matrix:
    def __init__(self, inputs: Inputs) -> None:
        self.inputs = inputs
        self._cells: dict[tuple[str, str], Cell] = {}

    def cell(self, verb: str, shape: str) -> Cell:
        key = (verb, shape)
        if key not in self._cells:
            dest = self.inputs.root / "cells" / verb / shape
            dest.mkdir(parents=True)
            args = argv_for(verb, shape, self.inputs, dest)
            dry = parse(run_cli(verb, "--dry-run", *args, "-o", "json"))
            wrote = sorted(str(p) for p in dest.rglob("*.pdf"))
            real = parse(run_cli(verb, *args, "-o", "json"))
            self._cells[key] = Cell(dry, real, dest, wrote)
        return self._cells[key]


@pytest.fixture(scope="session")
def matrix(inputs: Inputs) -> Matrix:
    return Matrix(inputs)


def _ids(items: tuple[str, ...]) -> list[str]:
    return list(items)


def _in_process(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    from pdf_tooling.cli.common import reset_error_format
    from pdf_tooling.cli.main import main

    monkeypatch.setattr(sys, "argv", ["pdftooling", *argv])
    reset_error_format()
    with pytest.raises(SystemExit) as excinfo:
        main()
    code = excinfo.value.code
    return int(code) if code is not None else 0


# --------------------------------------------------------------------------- #
# AC1 -- every rebuild output carries the source's /Info and XMP
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vi", range(len(NON_MERGE)), ids=_ids(NON_MERGE))
def test_ac1_every_rebuild_output_carries_the_sources_info_and_xmp(vi: int, matrix: Matrix) -> None:
    verb = NON_MERGE[vi]
    for shape in SHAPES:
        cell = matrix.cell(verb, shape)
        assert cell.real.rc == 0, f"{verb} {shape}: {cell.real.stderr[-400:]}"
        outputs = cell.outputs()
        assert outputs, (verb, shape)
        for path in outputs:  # every split part included
            assert_equal_to_source(path, matrix.inputs, shape)


# --------------------------------------------------------------------------- #
# AC2 -- merge carries the first input's
# --------------------------------------------------------------------------- #


def _merge(
    inputs: Inputs, name: str, operands: list[str], extra: list[str]
) -> tuple[Run, Run, Path]:
    dest = inputs.root / "merge-arms" / name
    dest.mkdir(parents=True)
    args = [*operands, "-O", str(dest / "out.pdf"), *extra]
    dry = parse(run_cli("merge", "--dry-run", *args, "-o", "json"))
    assert not list(dest.glob("*.pdf")), "a dry run writes nothing"
    real = parse(run_cli("merge", *args, "-o", "json"))
    return dry, real, dest / "out.pdf"


def test_ac2_merge_plain_then_none_is_equal_to_plain_and_silent(inputs: Inputs) -> None:
    files = inputs.files
    dry, real, out = _merge(inputs, "a", [str(files["plain"]), str(files["none"])], [])
    assert real.rc == 0 and dry.rc == 0
    assert_equal_to_source(out, inputs, "plain")
    assert real.warnings == [] and dry.warnings == []


def test_ac2_merge_none_then_plain_has_no_metadata_and_names_the_loser(inputs: Inputs) -> None:
    files = inputs.files
    dry, real, out = _merge(inputs, "b", [str(files["none"]), str(files["plain"])], [])
    assert real.rc == 0
    assert info_of(out) is None and xmp_of(out) is None
    expected = [w_meta(str(files["plain"]), "merge", "document /Info and XMP metadata packet")]
    assert real.warnings == expected
    assert dry.warnings == expected


def test_ac2_merge_with_a_range_and_a_repeat_names_only_the_other_source(inputs: Inputs) -> None:
    files = inputs.files
    operands = [f"{files['plain']}:1", str(files["info-only"]), f"{files['plain']}:2"]
    dry, real, out = _merge(inputs, "c", operands, [])
    assert real.rc == 0
    assert_equal_to_source(out, inputs, "plain")
    expected = [w_meta(str(files["info-only"]), "merge", "document /Info")]
    assert real.warnings == expected
    assert dry.warnings == expected


def test_ac2_merge_none_then_an_encrypted_operand_reports_it_unchecked(inputs: Inputs) -> None:
    files = inputs.files
    dry, real, _ = _merge(
        inputs,
        "d",
        [str(files["none"]), str(files["aes"])],
        [FLAG, "--password-file", str(inputs.user_pw)],
    )
    label = str(files["aes"])
    expected = [w_enc(label, "merge"), w_unchecked(label, "merge")]
    assert real.rc == 0
    assert real.warnings == expected
    assert dry.warnings == expected


# --------------------------------------------------------------------------- #
# AC3 -- /Trapped keeps its type
# --------------------------------------------------------------------------- #


def test_ac3_trapped_stays_a_name(matrix: Matrix) -> None:
    cell = matrix.cell("rotate", "plain")
    assert cell.real.rc == 0
    with pikepdf.Pdf.open(cell.outputs()[0]) as pdf:
        trapped = pdf.trailer["/Info"]["/Trapped"]
        assert isinstance(trapped, pikepdf.Name)
        assert str(trapped) == "/False"


# --------------------------------------------------------------------------- #
# AC4 -- /EncryptMetadata false is read with pikepdf
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vi", range(len(ALL_VERBS)), ids=_ids(ALL_VERBS))
def test_ac4_encrypt_metadata_false_xmp_is_the_true_packet(vi: int, matrix: Matrix) -> None:
    verb = ALL_VERBS[vi]
    bad: list[tuple[str, str]] = []
    for shape in ("emf-rc4", "emf-aes"):
        cell = matrix.cell(verb, shape)
        assert cell.real.rc == 0, f"{verb} {shape}: {cell.real.stderr[-400:]}"
        with pikepdf.Pdf.open(matrix.inputs.files[shape], password=USER_PASSWORD) as source:
            packet = bytes(source.Root.Metadata.read_bytes())
        assert packet.startswith(b"<?xpacket"), "control: the true packet is the XMP text"
        bad.extend((verb, shape) for path in cell.outputs() if xmp_of(path) != packet)
    assert bad == [], f"XMP is not the true packet in cells {bad}"


# --------------------------------------------------------------------------- #
# AC5 -- W-META stops where carriage succeeds
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vi", range(len(NON_MERGE)), ids=_ids(NON_MERGE))
def test_ac5_no_metadata_warning_where_carriage_succeeds(vi: int, matrix: Matrix) -> None:
    verb = NON_MERGE[vi]
    for shape in SHAPES:
        cell = matrix.cell(verb, shape)
        for tier, run in (("dry", cell.dry), ("real", cell.real)):
            assert run.rc == 0, (verb, shape, tier, run.stderr[-300:])
            assert all(W_META_MARK not in w and W_UNCHECKED_MARK not in w for w in run.warnings), (
                verb,
                shape,
                tier,
                run.warnings,
            )
            enc = [w for w in run.warnings if W_ENC_MARK in w]
            assert len(enc) == (1 if shape in ENCRYPTED else 0), (verb, shape, tier, run.warnings)


# --------------------------------------------------------------------------- #
# AC6 -- dry == real
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vi", range(len(ALL_VERBS)), ids=_ids(ALL_VERBS))
def test_ac6_dry_warnings_equal_real_warnings_and_dry_writes_nothing(
    vi: int, matrix: Matrix
) -> None:
    verb = ALL_VERBS[vi]
    for shape in SHAPES:
        cell = matrix.cell(verb, shape)
        assert cell.dry.rc == cell.real.rc, (verb, shape)
        assert cell.dry.warnings == cell.real.warnings, (verb, shape)
        assert cell.dry_wrote == [], (verb, shape)


# --------------------------------------------------------------------------- #
# AC7 -- the stamp layer never donates
# --------------------------------------------------------------------------- #


def test_ac7_the_stamp_layer_never_donates_nor_reads_its_xmp(
    inputs: Inputs, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import pdf_tooling.adapters.pypdf_structure as adapter

    def boom(data: bytes, password: Any) -> bytes:
        raise AssertionError("the layer buffer must not read a true packet")

    monkeypatch.setattr(adapter, "_true_metadata_packet", boom)
    out = inputs.root / "ac7-stamp.pdf"
    argv = [
        "stamp",
        str(inputs.files["plain"]),
        "--from",
        str(inputs.files["emf-rc4"]),
        "--password-file",
        str(inputs.user_pw),
        FLAG,
        "-O",
        str(out),
        "-o",
        "json",
    ]
    capsys.readouterr()
    assert _in_process(argv, monkeypatch) == 0, capsys.readouterr().out[-500:]
    assert_equal_to_source(out, inputs, "plain")


# --------------------------------------------------------------------------- #
# AC8 / AC9 -- the true packet: once per document through the held handle; fail closed
# --------------------------------------------------------------------------- #


def test_ac8_the_true_packet_is_read_once_per_document_through_the_held_handle(
    inputs: Inputs, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pdf_tooling.adapters.pypdf_structure as adapter

    calls: list[int] = []
    original = adapter._true_metadata_packet

    def counting(data: bytes, password: Any) -> bytes:
        calls.append(1)
        return original(data, password)

    monkeypatch.setattr(adapter, "_true_metadata_packet", counting)

    source = str(inputs.files["emf-rc4"])
    in_write: list[bool] = []
    opens: list[str] = []
    original_write = adapter.PypdfStructureWriter.write

    def spying_write(self: Any, stream: Any) -> None:
        in_write.append(True)
        try:
            original_write(self, stream)
        finally:
            in_write.pop()

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if event == "open" and in_write and str(args[0]) == source:
            opens.append(str(args[0]))

    monkeypatch.setattr(adapter.PypdfStructureWriter, "write", spying_write)
    sys.addaudithook(hook)
    out_dir = inputs.root / "ac8-parts"
    argv = [
        "split",
        source,
        "--each-page",
        "--out-dir",
        str(out_dir),
        FLAG,
        "--password-file",
        str(inputs.user_pw),
        "-o",
        "json",
    ]
    assert _in_process(argv, monkeypatch) == 0
    parts = sorted(out_dir.glob("*.pdf"))
    assert len(parts) == 3
    assert len(calls) == 1, "the packet is read once for three parts"
    assert opens == [], "the donor is read through the handle it already holds"


def test_ac9_a_failed_true_packet_read_fails_closed_with_nothing_written(
    inputs: Inputs, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import pdf_tooling.adapters.pypdf_structure as adapter
    from pdf_tooling.errors import FailureError

    fixed = (
        "could not read this document's XMP packet (it is encrypted with "
        "/EncryptMetadata false); nothing was written"
    )

    def refuse(data: bytes, password: Any) -> bytes:
        raise FailureError(fixed)

    monkeypatch.setattr(adapter, "_true_metadata_packet", refuse)
    work = inputs.root / "ac9"
    work.mkdir()
    out = work / "r.pdf"
    argv = [
        "rotate",
        str(inputs.files["emf-rc4"]),
        "--pages",
        "1",
        "--angle",
        "90",
        "-O",
        str(out),
        FLAG,
        "--password-file",
        str(inputs.user_pw),
        "-o",
        "json",
    ]
    capsys.readouterr()
    assert _in_process(argv, monkeypatch) == 1
    text = capsys.readouterr().out
    envelope = json.loads(text[text.index("{") :])
    messages = [envelope.get("error", {}).get("message")] + [
        item.get("message") for item in envelope.get("items", [])
    ]
    assert fixed in messages, envelope
    assert not out.exists()
    assert [p.name for p in work.iterdir()] == []


# --------------------------------------------------------------------------- #
# AC10 -- no new secret consumer
# --------------------------------------------------------------------------- #

#: Measured at `a38a58d` (the rebased base: PDF-115), by running this very test body there.
PASSWORD_FILE_READS_AT_A38A58D: Final[int] = 1
REVEAL_SITES_AT_A38A58D: Final[int] = 2


def test_ac10_the_carriage_adds_no_secret_consumer(
    inputs: Inputs, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pdf_tooling.cli.password as password_module

    reads: list[int] = []
    original = password_module._read_file

    def counting(*args: Any, **kwargs: Any) -> Any:
        reads.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(password_module, "_read_file", counting)
    out = inputs.root / "ac10.pdf"
    argv = [
        "rotate",
        str(inputs.files["aes"]),
        "--pages",
        "1",
        "--angle",
        "90",
        "-O",
        str(out),
        FLAG,
        "--password-file",
        str(inputs.user_pw),
        "-o",
        "json",
    ]
    assert _in_process(argv, monkeypatch) == 0
    assert len(reads) == PASSWORD_FILE_READS_AT_A38A58D
    source = (REPO_ROOT / "src/pdf_tooling/adapters/pypdf_structure.py").read_text()
    assert source.count("reveal()") == REVEAL_SITES_AT_A38A58D


# --------------------------------------------------------------------------- #
# AC11 -- the declaration and the warnings agree with carriage
# --------------------------------------------------------------------------- #


def _facts(*, info: set[str], xmp: bool) -> CarriageFacts:
    return CarriageFacts(
        readable=True,
        encrypted=False,
        info_keys=frozenset(info),
        producer=None,
        has_xmp=xmp,
    )


def test_ac11_the_declaration_and_the_warnings_agree() -> None:
    assert CARRIAGE["merge"] is carriage_decl._MERGE
    for verb in REBUILD_AT_9809A7F - {"merge"}:
        row = CARRIAGE[verb]
        assert dataclasses.replace(row, sources=()) == carriage_decl._REBUILD, verb
        assert (row.info, row.xmp) == (Drop.CARRIES, Drop.CARRIES), verb
    facts = _facts(info={"/Title"}, xmp=True)
    assert carriage.carriage_warnings("merge", "x", facts, first=False) != ()
    assert carriage.carriage_warnings("merge", "x", facts, first=True) == ()
    undeclared = carriage.carriage_warnings(
        "no-such-verb", "x", dataclasses.replace(facts, encrypted=True)
    )
    assert (
        len(undeclared) == 2 and "encrypted" in undeclared[0] and "does not carry" in undeclared[1]
    )


# --------------------------------------------------------------------------- #
# AC12 -- the population is derived, and the seam reaches all of it
# --------------------------------------------------------------------------- #


def _derived_rebuild() -> set[str]:
    rebuild, merge = carriage_decl._REBUILD, carriage_decl._MERGE
    return {
        verb
        for verb, row in CARRIAGE.items()
        if dataclasses.replace(row, sources=()) in (rebuild, merge)
    }


def test_ac12_the_derived_population_is_the_one_the_writer_serialises(
    inputs: Inputs, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pdf_tooling.adapters.pypdf_structure as adapter

    assert _derived_rebuild() == set(REBUILD_AT_9809A7F)
    fired: list[str] = []
    current: list[str] = []
    original = adapter.PypdfStructureWriter.write

    def spy(self: Any, stream: Any) -> None:
        if current:
            fired.append(current[0])
        original(self, stream)

    monkeypatch.setattr(adapter.PypdfStructureWriter, "write", spy)
    for verb in ALL_VERBS:
        dest = inputs.root / "ac12" / verb
        dest.mkdir(parents=True)
        current[:] = [verb]
        argv = [verb, *argv_for(verb, "plain", inputs, dest), "-o", "json"]
        assert _in_process(argv, monkeypatch) == 0, verb
    assert set(fired) == _derived_rebuild()


# --------------------------------------------------------------------------- #
# AC14 -- help tells the truth
# --------------------------------------------------------------------------- #


def _help(verb: str) -> str:
    proc = run_cli(verb, "--help")
    assert proc.returncode == 0, proc.stderr
    return re.sub(r"\s+", " ", proc.stdout)


def test_ac14_help_tells_the_truth() -> None:
    rotate = _help("rotate")
    assert "not carried" not in rotate
    assert "carried to the output unchanged" in rotate
    assert "first input's /Info and XMP" in _help("merge")
    assert "Every part carries" in _help("split")
    for verb in sorted(REBUILD_AT_9809A7F):
        assert "not carried" not in _help(verb), verb


# --------------------------------------------------------------------------- #
# AC15 / AC16 -- README
# --------------------------------------------------------------------------- #

UPGRADING_1_1: Final[str] = "## Upgrading to 1.1"


def test_ac15_the_readme_no_longer_claims_the_old_behaviour() -> None:
    readme = (REPO_ROOT / "README.md").read_text()
    for pattern in (
        r"Rebuilt without the input's .Info or XMP packet",
        r"holds only the engine's producer entry",
        r"Whether any of this should change is an open decision",
    ):
        assert re.search(pattern, readme) is None, pattern


def test_ac16_the_upgrading_row_names_the_nine_verbs_and_the_clear_all_recipe() -> None:
    text = (REPO_ROOT / "README.md").read_text()
    assert UPGRADING_1_1 in text, "README has no '## Upgrading to 1.1' section to carry the row"
    section = text.split(UPGRADING_1_1, 1)[1].split("\n## ", 1)[0]
    rows = [
        line
        for line in section.splitlines()
        if line.startswith("|") and "meta set --clear-all" in line
    ]
    assert len(rows) == 1
    named = set(re.findall(r"`([a-z]+)`", rows[0]))
    assert named >= _derived_rebuild()


# --------------------------------------------------------------------------- #
# AC17 -- the read-seam record is exact
# --------------------------------------------------------------------------- #


def test_ac17_the_read_seam_record_is_exact() -> None:
    from test_read_seams import READ_SEAM_RESIDUE_LEDGER

    last, previous = READ_SEAM_RESIDUE_LEDGER[-1], READ_SEAM_RESIDUE_LEDGER[-2]
    assert (last.spec, last.direction) == ("PDF-116", "up")
    assert last.ruling.strip()
    key = "pdf_tooling/adapters/pypdf_structure.py"
    differing = {
        k
        for k in {*last.ceilings, *previous.ceilings}
        if last.ceilings.get(k) != previous.ceilings.get(k)
    }
    assert differing == {key}
    assert (previous.ceilings[key], last.ceilings[key]) == (9, 10)
