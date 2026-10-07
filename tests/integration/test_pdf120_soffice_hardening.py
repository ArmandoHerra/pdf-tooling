"""PDF-120 -- the LibreOffice adapter's hardening: no linked-resource loads and
an absolute operand.

``convert`` hands an UNTRUSTED office document to headless ``soffice``. On
LibreOffice 24.2.7 (measured) a document whose image is a *link* made the child
connect to the URL the document names, and a ``file://`` link rendered a local
file's content into the output PDF. The throwaway profile is now pre-seeded
(``user/registrymodifications.xcu``, written by ``ScratchDir`` -- the write
chokepoint -- from bytes the adapter supplies), the adapter refuses to spawn
without that seed, and the operand is passed absolute (never ``--``: 24.2.7
has no end-of-options marker).

Fixtures are built at test time with ``zipfile``. Every listener binds
``127.0.0.1`` on port 0; no fixture names any external host. Canary and control
tokens are fresh ``uuid4().hex`` values.
"""

from __future__ import annotations

import socket
import sys
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Final

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registry import run_cli  # noqa: E402

_ODT_NS: Final[str] = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"'
)
_ODT_MANIFEST: Final[str] = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest
 xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
<manifest:file-entry manifest:full-path="/"
 manifest:media-type="application/vnd.oasis.opendocument.text"/>
<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
{extra}</manifest:manifest>"""

_DOCX_CT: Final[str] = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" '
    'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_DOCX_RELS: Final[str] = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/></Relationships>'
)
_DOCX_PIC: Final[str] = (
    '<w:p><w:r><w:drawing><wp:inline><wp:extent cx="720000" cy="720000"/>'
    '<wp:docPr id="1" name="p"/><a:graphic>'
    '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
    '<pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="p"/><pic:cNvPicPr/></pic:nvPicPr>'
    '<pic:blipFill><a:blip r:link="{rid}"/></pic:blipFill>'
    '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="720000" cy="720000"/></a:xfrm>'
    '<a:prstGeom prst="rect"/></pic:spPr></pic:pic></a:graphicData></a:graphic>'
    "</wp:inline></w:drawing></w:r></w:p>"
)


def _svg(text: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="100">'
        f'<text x="10" y="50" font-size="24">{text}</text></svg>'
    )


def _write_odt(path: Path, body: str, *, embedded: dict[str, str] | None = None) -> None:
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<office:document-content {_ODT_NS} office:version="1.2">'
        f"<office:body><office:text><text:p>BODY-MARKER</text:p>{body}"
        "</office:text></office:body></office:document-content>"
    )
    extra = "".join(
        f'<manifest:file-entry manifest:full-path="{name}" manifest:media-type="image/svg+xml"/>\n'
        for name in (embedded or {})
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.text")
        archive.writestr("META-INF/manifest.xml", _ODT_MANIFEST.format(extra=extra))
        archive.writestr("content.xml", content)
        for name, data in (embedded or {}).items():
            archive.writestr(name, data)


def _odt_image(href: str, width: str = "8cm") -> str:
    return (
        f'<text:p><draw:frame svg:width="{width}" svg:height="2cm"><draw:image xlink:href="{href}" '
        'xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/></draw:frame></text:p>'
    )


def _write_docx(path: Path, targets: list[str]) -> None:
    body = "".join(_DOCX_PIC.format(rid=f"rId{9 + i}") for i in range(len(targets)))
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f"<w:body><w:p><w:r><w:t>BODY-MARKER</w:t></w:r></w:p>{body}</w:body></w:document>"
    )
    rels = "".join(
        f'<Relationship Id="rId{9 + i}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        f'Target="{target}" TargetMode="External"/>'
        for i, target in enumerate(targets)
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", _DOCX_CT)
        archive.writestr("_rels/.rels", _DOCX_RELS)
        archive.writestr("word/document.xml", document)
        archive.writestr(
            "word/_rels/document.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{rels}</Relationships>",
        )


class _Listener:
    """A loopback-only recorder. Port 0, daemon thread, bounded accept timeout."""

    def __init__(self) -> None:
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self._sock.settimeout(0.25)
        self.port: int = self._sock.getsockname()[1]
        self.lines: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            conn.settimeout(2)
            try:
                data = conn.recv(4096)
            except OSError:
                data = b""
            self.lines.append(data.split(b"\r\n")[0].decode("latin-1"))
            try:
                conn.sendall(b"HTTP/1.0 404 Not Found\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            conn.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._sock.close()


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


@pytest.mark.requires("soffice")
@pytest.mark.parametrize("fmt", ["odt", "docx"])
def test_pdf120_no_fetch_no_embed(tmp_path: Path, fmt: str) -> None:
    token = uuid.uuid4().hex
    control = uuid.uuid4().hex
    canary_svg = tmp_path / "canary.svg"
    canary_svg.write_text(_svg(f"CANARY-{token}"), encoding="utf-8")
    listener = _Listener()
    try:
        probe = socket.create_connection(("127.0.0.1", listener.port), timeout=2)
        probe.sendall(f"GET /self-probe-{token} HTTP/1.0\r\n\r\n".encode())
        probe.settimeout(2)
        probe.recv(256)
        probe.close()
        for _ in range(40):
            if listener.lines:
                break
            threading.Event().wait(0.05)
        assert listener.lines == [f"GET /self-probe-{token} HTTP/1.0"], "listener is vacuous"
        listener.lines.clear()

        remote = f"http://127.0.0.1:{listener.port}/{token}.png"
        local = f"file://{canary_svg}"
        doc = tmp_path / f"linked.{fmt}"
        if fmt == "odt":
            _write_odt(
                doc,
                _odt_image(remote, "2cm") + _odt_image(local) + _odt_image("Pictures/control.svg"),
                embedded={"Pictures/control.svg": _svg(f"CONTROL-{control}")},
            )
        else:
            _write_docx(doc, [remote, local])
        out = tmp_path / "out.pdf"
        result = run_cli("convert", str(doc), "-O", str(out))
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert out.read_bytes().startswith(b"%PDF-")
        recorded = list(listener.lines)
        # pypdf inserts spaces inside rendered SVG text ("CANARY -<hex>"), so
        # compare on the whitespace-free text and on the unique hex alone.
        text = "".join(_pdf_text(out).split())
    finally:
        listener.close()
    # One assertion over every finding, so a red names EVERY failed guard at once
    # (the listener AND the canary), not just the first.
    problems: list[str] = []
    if recorded:
        problems.append(f"soffice contacted the listener: {recorded}")
    if token in text:
        problems.append("a file:// linked image was rendered into the PDF (canary present)")
    if "BODY-MARKER" not in text:
        problems.append("BODY-MARKER missing from the extracted text")
    if fmt == "odt" and control not in text:
        problems.append("extraction/render non-vacuity: the embedded control image is missing")
    assert not problems, problems


@pytest.mark.requires("soffice")
def test_pdf120_leading_dash_converts(tmp_path: Path) -> None:
    _write_odt(tmp_path / "-dash.odt", "")
    out = tmp_path / "dash.pdf"
    result = run_cli("convert", "./-dash.odt", "-O", str(out), cwd=tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert out.read_bytes().startswith(b"%PDF-")


# --------------------------------------------------------------------------- #
# Engine-free arms (run in every leg). None of them spells a verb name.
# --------------------------------------------------------------------------- #

_EXPECTED_KEYS: Final[frozenset[tuple[str, str, str]]] = frozenset(
    {
        ("/org.openoffice.Office.Common/Security/Scripting", "BlockUntrustedRefererLinks", "true"),
        ("/org.openoffice.Office.Writer/Content/Update", "Link", "0"),
        ("/org.openoffice.Office.Calc/Content/Update", "Link", "1"),
        ("/org.openoffice.Office.Common/Security/Scripting", "DisableActiveContent", "true"),
        ("/org.openoffice.Office.Common/Security/Scripting", "DisableMacrosExecution", "true"),
    }
)
_OOR: Final[str] = "{http://openoffice.org/2001/registry}"


def test_pdf120_seed_content() -> None:
    from xml.etree import ElementTree

    from pdf_tooling.adapters import soffice_office

    root = ElementTree.fromstring(soffice_office._PROFILE_SEED_XCU)
    triples: set[tuple[str, str, str]] = set()
    for item in root.findall("item"):
        for prop in item.findall("prop"):
            assert prop.get(f"{_OOR}op") == "fuse"
            value = prop.findtext("value")
            assert value is not None
            triples.add((item.get(f"{_OOR}path") or "", prop.get(f"{_OOR}name") or "", value))
    assert triples == set(soffice_office.PROFILE_SEED_KEYS)
    assert triples == _EXPECTED_KEYS
    assert len(soffice_office.PROFILE_SEED_KEYS) == len(_EXPECTED_KEYS)
    assert dict(soffice_office.ADAPTER.scratch_seed()) == {
        soffice_office._PROFILE_SEED_RELPATH: soffice_office._PROFILE_SEED_XCU
    }


def _scratch_leftovers(tmp: Path) -> list[str]:
    return sorted(p.name for p in tmp.glob("*-scratch-*"))


def test_pdf120_scratchdir_seeds_and_cleans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import stat
    import tempfile

    from pdf_tooling.safety.atomic import ScratchDir

    tmp = tmp_path / "tmp"
    tmp.mkdir()
    monkeypatch.setenv("TMPDIR", str(tmp))
    monkeypatch.setattr(tempfile, "tempdir", None)

    with ScratchDir(seed={"a/b/c.xcu": b"x"}) as root:
        assert (root / "a/b/c.xcu").read_bytes() == b"x"
        for parent in (root / "a", root / "a/b"):
            assert stat.S_IMODE(parent.stat().st_mode) == 0o700
    assert _scratch_leftovers(tmp) == []

    for bad in ("../x", "/abs", "", "a/../../x", "a\\b"):
        with pytest.raises(ValueError), ScratchDir(seed={bad: b"x"}):
            raise AssertionError("entered with an invalid seed path")
        assert _scratch_leftovers(tmp) == [], bad
    assert not (tmp / "x").exists()

    # A write failure AFTER the root exists (a file where a directory must go).
    with pytest.raises(OSError), ScratchDir(seed={"a": b"x", "a/b": b"y"}):
        raise AssertionError("entered with an unwritable seed")
    assert _scratch_leftovers(tmp) == []


class _RecordingRun:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **_kwargs: object) -> object:
        from types import SimpleNamespace

        self.calls.append(list(argv))
        return SimpleNamespace(timed_out=False, returncode=0, stdout="", stderr="")


def test_pdf120_argv_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    from pdf_tooling.adapters import soffice_office, subprocess_util
    from pdf_tooling.errors import FailureError
    from pdf_tooling.safety.atomic import ScratchDir

    recorder = _RecordingRun()
    monkeypatch.setattr(subprocess_util, "run", recorder)
    monkeypatch.chdir(tmp_path)
    with ScratchDir(seed=soffice_office.ADAPTER.scratch_seed()) as scratch:
        with pytest.raises(FailureError):
            soffice_office.ADAPTER.convert_to_pdf(
                Path("-dash.odt"), scratch_dir=scratch, filter_name=None, timeout=5.0
            )
    assert len(recorder.calls) == 1
    argv = recorder.calls[0]
    assert argv[-1] == os.path.abspath("-dash.odt")
    assert argv[-1].startswith("/")
    assert "--" not in argv


def test_pdf120_fail_closed_without_the_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pdf_tooling.adapters import soffice_office, subprocess_util
    from pdf_tooling.errors import FailureError
    from pdf_tooling.safety.atomic import ScratchDir

    recorder = _RecordingRun()
    monkeypatch.setattr(subprocess_util, "run", recorder)
    monkeypatch.chdir(tmp_path)
    with ScratchDir() as scratch:
        with pytest.raises(FailureError, match="hardened profile"):
            soffice_office.ADAPTER.convert_to_pdf(
                Path("x.odt"), scratch_dir=scratch, filter_name=None, timeout=5.0
            )
    assert recorder.calls == []


# --------------------------------------------------------------------------- #
# Engine arm: the seeded keys exist in the installed engine's own schema.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("soffice")
def test_pdf120_schema_presence() -> None:
    import shutil
    import subprocess
    from xml.etree import ElementTree

    from pdf_tooling.adapters import soffice_office

    located = shutil.which(soffice_office.BINARY)
    assert located, "soffice resolved by the gate but not by which()"
    binary = Path(located).resolve()
    candidates = [
        binary.parent.parent / "share" / "registry" / "main.xcd",
        binary.parent.parent / "Resources" / "registry" / "main.xcd",
    ]
    schema = next((c for c in candidates if c.is_file()), None)
    assert schema is not None, f"no LibreOffice schema at either of: {[str(c) for c in candidates]}"
    version = subprocess.run(  # noqa: S603 - fixed argv, host binary, version query
        [str(binary), "--version"], capture_output=True, text=True, check=False, timeout=60
    ).stdout.strip()

    oor = "{http://openoffice.org/2001/registry}"
    types: dict[tuple[str, str], str] = {}

    def walk(node: ElementTree.Element, path: str) -> None:
        for child in node:
            name = child.get(f"{oor}name")
            if name is None:
                continue
            if child.tag == "prop":
                types[(path, name)] = child.get(f"{oor}type") or ""
            elif child.tag in {"node", "group", "set"}:
                walk(child, f"{path}/{name}")

    root = ElementTree.parse(schema).getroot()
    for component in root:
        pkg = component.get(f"{oor}package")
        name = component.get(f"{oor}name")
        if pkg and name and component.tag == f"{oor}component-schema":
            for body in component.findall("component"):
                walk(body, f"/{pkg}.{name}")

    for path, key, value in soffice_office.PROFILE_SEED_KEYS:
        assert (path, key) in types, f"{path} {key} not in the schema ({version})"
        kind = types[(path, key)]
        if value in {"true", "false"}:
            assert kind == "xs:boolean", (path, key, kind, version)
        else:
            assert kind == "xs:int" and value.isdigit(), (path, key, kind, version)
