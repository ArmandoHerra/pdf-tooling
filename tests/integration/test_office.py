"""`convert` at the subprocess/engine level (PDF-15) -- the generated-corpus
arms: D6's own two properties (isolated per-invocation profile; exit 0 with
no output file is a FAILURE), and AC13's no-orphan guarantee for soffice.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_toolkit.errors import FailureError  # noqa: E402
from pdf_toolkit.ops.office import convert_run  # noqa: E402
from pdf_toolkit.safety.policy import SafetyPolicy  # noqa: E402
from registry import run_cli  # noqa: E402


def _policy(*, dry_run: bool = False, threads: int = 1) -> SafetyPolicy:
    return SafetyPolicy(
        dry_run=dry_run,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=threads,
    )


def _text_fixture(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body)
    return path


def _odt_fixture(tmp_path: Path, name: str, paragraph: str, *, repeat: int = 1) -> Path:
    """A minimal `.odt` built with stdlib `zipfile` only (Design §D7's
    fallback / §D9's large-document fixture) -- no new dependency, nothing
    committed."""
    import zipfile

    path = tmp_path / name
    body = "".join(f"<text:p>{paragraph}</text:p>" for _ in range(repeat))
    content_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2">
  <office:body><office:text>{body}</office:text></office:body>
</office:document-content>"""
    manifest_xml = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">
  <manifest:file-entry manifest:full-path="/"
    manifest:media-type="application/vnd.oasis.opendocument.text"/>
  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
</manifest:manifest>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        archive.writestr("META-INF/manifest.xml", manifest_xml)
        archive.writestr("content.xml", content_xml)
    return path


# --------------------------------------------------------------------------- #
# AC10 -- the generated arm: a hand-built `.docx`/`.odt` round-trips through
# normalisation.
# --------------------------------------------------------------------------- #

_KNOWN_SENTENCE: Final[str] = "The quick brown fox jumps over the lazy pdftoolkit."


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


@pytest.mark.requires("soffice")
def test_ac10_generated_arm_round_trips_the_known_sentence(tmp_path: Path) -> None:
    from pdf_toolkit.ports.text import require_text

    source = _odt_fixture(tmp_path, "known.odt", _KNOWN_SENTENCE)
    output = tmp_path / "known.pdf"
    result = convert_run(
        [source],
        filter_name=None,
        timeout=60.0,
        output=output,
        out_dir=None,
        name_template=None,
        policy=_policy(),
    )
    assert result.exit_code == 0, result
    assert output.is_file() and output.stat().st_size > 0

    engine = require_text()
    extracted = "".join(engine.extract_text(str(output), [1]))
    assert _normalize(extracted) == _normalize(_KNOWN_SENTENCE)


# --------------------------------------------------------------------------- #
# AC11 -- `--filter` maps to `--convert-to pdf:<filter>` and appears in argv;
# a malformed filter exits 2.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("soffice")
def test_ac11_filter_appears_in_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    from pdf_toolkit.adapters import subprocess_util

    real_run = subprocess_util.run

    def _spy(argv, **kwargs):
        calls.append(list(argv))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess_util, "run", _spy)

    source = _text_fixture(tmp_path, "plain.txt", "hello")
    output = tmp_path / "plain.pdf"
    result = convert_run(
        [source],
        filter_name="writer_pdf_Export",
        timeout=60.0,
        output=output,
        out_dir=None,
        name_template=None,
        policy=_policy(),
    )
    assert result.exit_code == 0, result
    assert any("pdf:writer_pdf_Export" in call for call in calls)


def test_ac11_malformed_filter_exits_2(tmp_path: Path) -> None:
    source = _text_fixture(tmp_path, "plain.txt", "hello")
    result = run_cli("convert", str(source), "--filter", "a;b", "-O", str(tmp_path / "plain.pdf"))
    assert result.returncode == 2


# --------------------------------------------------------------------------- #
# AC14 -- every argv carries an isolated `-env:UserInstallation`; two
# CONCURRENT conversions use different profile directories, both exit 0, and
# the directories are gone afterwards.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("soffice")
def test_ac14_isolated_profile_per_invocation_and_concurrent_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import re
    import threading

    from pdf_toolkit.adapters import subprocess_util

    profile_dirs: list[str] = []
    lock = threading.Lock()
    real_run = subprocess_util.run

    def _spy(argv, **kwargs):
        for part in argv:
            match = re.match(r"-env:UserInstallation=file://(.+)$", part)
            if match:
                with lock:
                    profile_dirs.append(match.group(1))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess_util, "run", _spy)

    source_a = _text_fixture(tmp_path, "a.txt", "document A")
    source_b = _text_fixture(tmp_path, "b.txt", "document B")
    out_a, out_b = tmp_path / "a.pdf", tmp_path / "b.pdf"

    results: dict[str, object] = {}

    def _convert(name: str, source: Path, output: Path) -> None:
        results[name] = convert_run(
            [source],
            filter_name=None,
            timeout=60.0,
            output=output,
            out_dir=None,
            name_template=None,
            policy=_policy(),
        )

    t1 = threading.Thread(target=_convert, args=("a", source_a, out_a))
    t2 = threading.Thread(target=_convert, args=("b", source_b, out_b))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results["a"].exit_code == 0, results["a"]  # type: ignore[union-attr]
    assert results["b"].exit_code == 0, results["b"]  # type: ignore[union-attr]
    assert len(profile_dirs) >= 2
    assert len(set(profile_dirs)) == len(profile_dirs), "profile dirs were reused, not isolated"
    for directory in profile_dirs:
        assert not Path(directory).exists(), f"scratch profile dir survived: {directory}"


# --------------------------------------------------------------------------- #
# AC15 -- a corrupt `.docx` yields exit 1, naming the input, even though
# soffice itself may exit 0. Success is "the expected output PDF exists and
# is non-empty", never the return code (D6).
# --------------------------------------------------------------------------- #


@pytest.mark.requires("soffice")
def test_ac15_corrupt_docx_exits_1_even_if_soffice_exits_0(tmp_path: Path) -> None:
    """Driven through the real subprocess (``run_cli``), not ``convert_run``
    in-process: a raised ``FailureError`` propagates out of ``convert_run``
    (mirroring ``compress_run``'s own already-shipped per-item failure
    posture -- no per-item try/except, PLAN §5.4's "record and continue" is
    not this verb's contract either), so only the CLI's own one
    ``except PdfToolkitError`` handler renders the exit code and message an
    in-process call to ``convert_run`` would never see."""
    corrupt = tmp_path / "corrupt.docx"
    corrupt.write_bytes(b"not a real docx file, just random bytes \x00\x01\x02" * 20)
    output = tmp_path / "corrupt.pdf"

    result = run_cli("convert", str(corrupt), "-O", str(output))
    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert str(corrupt) in combined
    assert not output.exists()


# --------------------------------------------------------------------------- #
# AC13 (office arm) -- a timed-out convert leaves no orphaned soffice.bin,
# proven with a synthetic large `.odt` and a short `--timeout`.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("soffice")
def test_ac13_timeout_kills_the_whole_process_group(tmp_path: Path) -> None:
    import subprocess
    import time

    def _soffice_bin_count() -> int:
        try:
            out = subprocess.run(
                ["pgrep", "-fc", "soffice.bin"], capture_output=True, text=True, check=False
            )
        except FileNotFoundError:  # pragma: no cover - pgrep unavailable
            pytest.skip("pgrep is not available on this host")
        return int(out.stdout.strip() or "0")

    before = _soffice_bin_count()

    large = _odt_fixture(tmp_path, "large.odt", "filler paragraph. " * 40, repeat=4000)
    output = tmp_path / "large.pdf"
    with pytest.raises(FailureError, match="timed out"):
        convert_run(
            [large],
            filter_name=None,
            timeout=0.2,
            output=output,
            out_dir=None,
            name_template=None,
            policy=_policy(),
        )

    time.sleep(1.0)
    after = _soffice_bin_count()
    assert after <= before, (
        f"soffice.bin count rose ({before} -> {after}) -- an orphan survived the timeout "
        "(the MHC-50 shape)"
    )
