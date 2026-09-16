"""`convert` at the subprocess/engine level (PDF-15) -- the generated-corpus
arms: D6's own two properties (isolated per-invocation profile; exit 0 with
no output file is a FAILURE), and AC13's no-orphan guarantee for soffice.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Final

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_tooling.adapters import subprocess_util  # noqa: E402
from pdf_tooling.errors import FailureError  # noqa: E402
from pdf_tooling.ops.office import convert_run  # noqa: E402
from pdf_tooling.safety.policy import SafetyPolicy  # noqa: E402
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

_KNOWN_SENTENCE: Final[str] = "The quick brown fox jumps over the lazy pdftooling."


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


@pytest.mark.requires("soffice")
def test_ac10_generated_arm_round_trips_the_known_sentence(tmp_path: Path) -> None:
    from pdf_tooling.ports.text import require_text

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
    from pdf_tooling.adapters import subprocess_util

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

    from pdf_tooling.adapters import subprocess_util

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
    ``except PdfToolingError`` handler renders the exit code and message an
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


#: Bound on how long the groups this invocation spawned may take to disappear
#: after `convert_run` returns. `subprocess_util._terminate_group` already
#: SIGTERMs, waits its grace window, SIGKILLs stragglers and reaps the direct
#: child BEFORE `run()` returns, so the groups are normally gone at the first
#: probe. This is a DEADLINE that keeps the assertion deterministic, never a
#: tolerance: a survivor past it is a real orphan (the `MHC-50` shape) and is
#: FILED, never accommodated by widening this number.
GROUP_SETTLE_DEADLINE_S: Final = 10.0


def _group_alive(pgid: int) -> bool:
    """Whether any process remains in *pgid*.

    ``adapters/subprocess_util.py:212`` restated locally rather than imported,
    exactly as ``tests/integration/test_rasterize_signals.py:157`` and
    ``tests/unit/test_subprocess_util.py:46`` already restate it. Importing the
    product's own liveness helper into the test that judges the product's own
    cleanup would mean one broken helper turns both green together.

    ``os.killpg(pgid, 0)`` is also why nothing here scans the process table:
    it is the same syscall on both platforms in this project's matrix, where
    BSD and GNU ``ps`` do not agree on a stable ``sid``/``pgid`` column
    spelling. (This file names no process-scanning binary at all -- an arm in
    the control module asserts that, so the machine-wide count cannot creep
    back in under a different spelling.)
    """
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - not reachable for our own child
        return True
    return True


@pytest.mark.requires("soffice")
def test_ac13_timeout_kills_the_whole_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timed-out ``convert`` leaves nothing in the process groups IT created.

    THIS TEST USED TO COUNT THE MACHINE, AND THAT WAS THE DEFECT (`face1c63a0`)
    ---------------------------------------------------------------------------
    It counted ``soffice.bin`` processes **machine-wide**, before and after,
    inside a suite whose ``addopts`` pins ``-n auto``. The cheap symptom was a
    false red: reproduced 6/6, *"count rose (3 -> 7)"* -- by **four**, the
    number of concurrent xdist siblings, not by one orphan. The full history,
    including the exact command that did the counting, is in the control
    module's own docstring, which is where the retired predicate now lives.

    **The expensive half was a false GREEN.** If a sibling's ``soffice.bin``
    exited between the two samples while this test DID leak exactly one orphan,
    ``after == before`` and the assertion PASSED. The instrument could not
    detect the defect it was written for even when it was green.

    The replacement is asymmetric by construction rather than by tolerance.
    ``start_new_session=True`` puts every spawn in its own process group
    (``subprocess_util.py:330``), so a sibling's processes are in a DIFFERENT
    GROUP by definition and cannot enter this answer at all. The question is
    no longer *"how many soffice.bin exist on this host"* but *"does anything
    remain in the groups THIS invocation created"*.

    That asymmetry is proven by a standing DISAGREEMENT between the old and new
    predicates over one synthetic scenario, in
    ``tests/integration/test_office_orphan_probe.py`` -- which is engine-free
    and therefore runs on every leg, including the many where the marker above
    skips this one. A green run of this test is not the evidence; that
    disagreement is.
    """
    spawned: list[int] = []

    class _SpawnRecorder:
        """Records the pid of every child ``subprocess_util`` spawns.

        Scoped to ``subprocess_util``'s own namespace, so it sees every spawn
        made THROUGH THAT MODULE WHILE IT IS INSTALLED, and nothing else on
        this host.

        Measured rather than assumed: this records **1** spawn on this host,
        not two. The ``soffice --version`` engine-resolution probe runs when
        ``@pytest.mark.requires("soffice")`` is evaluated, which is before the
        monkeypatch exists, so it is NOT among them. That is why the
        non-vacuity assertion below checks the recorder saw a spawn at all --
        a probe over an empty list would pass while observing nothing.

        The pid IS the pgid, by ``start_new_session=True``, and that premise is
        asserted at EVERY spawn rather than assumed. Taking the id from the
        spawn (rather than from ``result.pgid``) keeps the observer and the
        thing observed from sharing one computation: a wrong pgid would
        otherwise blind the probe and the cleanup in the same direction, which
        is this cycle's defining defect class.
        """

        def __init__(self, real: Any) -> None:
            self._real = real

        def __getattr__(self, name: str) -> Any:
            return getattr(self._real, name)

        def Popen(self, *args: Any, **kwargs: Any) -> Any:  # noqa: N802
            assert kwargs.get("start_new_session") is True, (
                "subprocess_util.run no longer starts a new session; the "
                "pgid == pid premise this probe rests on is gone"
            )
            proc = self._real.Popen(*args, **kwargs)
            spawned.append(proc.pid)
            return proc

    monkeypatch.setattr(subprocess_util, "subprocess", _SpawnRecorder(subprocess_util.subprocess))

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

    assert spawned, (
        "the recorder saw no spawn at all, so the probe below would pass "
        "vacuously; the seam over subprocess_util's namespace has moved"
    )

    # A BOUNDED POLL, not a fixed sleep. It returns as soon as the groups are
    # empty -- faster than the `time.sleep(1.0)` it replaces on a quiet host --
    # and under contention it stops failing merely because 1.0 s was not enough.
    started = time.monotonic()
    while True:
        survivors = [pgid for pgid in spawned if _group_alive(pgid)]
        elapsed = time.monotonic() - started
        if not survivors or elapsed >= GROUP_SETTLE_DEADLINE_S:
            break
        time.sleep(0.02)

    assert not survivors, (
        f"process group(s) {survivors} still exist {elapsed:.3f}s after the timeout "
        f"(deadline {GROUP_SETTLE_DEADLINE_S}s, loadavg {os.getloadavg()}) -- an orphan "
        "survived, which is the MHC-50 shape. This deadline may NOT be widened to make "
        "this green: a survivor past it is a real defect and is FILED."
    )


# --------------------------------------------------------------------------- #
# PDF-67 -- ARM C: the class stimulus, and the TWO-WAY anti-rot arm.
#
# `README.md`'s code-`0` row now carries a named exception: an operand whose
# acceptability an out-of-process engine decides at load time. This arm is what
# keeps that sentence from rotting in EITHER direction, and the second direction
# is the one that separates an anti-rot arm from a test that freezes a defect.
#
# THE STIMULUS is `_odt_fixture`'s own output with ONE member changed -- its
# `META-INF/manifest.xml` emptied of file-entries (E10's V1 -> V3). Everything
# else is byte-for-byte the shipped helper's, so the fixture tracks the helper
# rather than forking from it, and the mutation is visible in one line.
#
# WHY THAT MUTATION AND NOT A SIMPLER ONE. Measured at `20a3dbc` against
# LibreOffice 26.2.5.2: a package with NO `content.xml` at all converts, while
# a complete package that under-declares its manifest does not. The engine
# trusts the manifest's declaration and does not require the declared member to
# exist -- so this is engine POLICY, not structural validity, and a spawn-free
# predicate that refused it would be encoding one LibreOffice version's policy
# as this product's contract. That measurement is why OR-19 carved the case out
# instead of chasing it, and it is also why this arm is written to red when the
# engine's behaviour changes rather than to assume it will not.
#
# THE THREE BRANCHES (Design D5):
#   dry 0 / real 1 / disclosure present  -> GREEN, the documented state
#   dry 0 / real 1 / disclosure absent   -> RED, the payload stopped saying
#                                           what `README.md` says it says
#   dry and real AGREE                   -> RED, naming the measured soffice
#                                           version: the README now carves out
#                                           an exception the product no longer
#                                           needs, so NARROW THE CLAIM. A wider
#                                           SPAWN-FREE triage that legitimately
#                                           predicts this operand is welcome;
#                                           improvement is not punished, it is
#                                           required to move the documentation
#                                           with it.
#
# The verdict function is PURE OVER ITS PARAMETERS, following
# `docs_ratification_complaints`'s rule, so the third branch can be DRIVEN
# against a convertible operand rather than asserted to exist -- an arm that
# cannot tell "the claim is still needed" from "the claim is stale" is an arm
# that will one day certify a false carve-out.
#
# It SKIPS WITH A REASON when `soffice` is absent. A vacuous pass here would be
# worse than no arm at all.
# --------------------------------------------------------------------------- #


def _odt_with_empty_manifest(tmp_path: Path, name: str) -> Path:
    """E10's V3: the shipped `_odt_fixture` with its manifest file-entries gone."""
    import zipfile

    source = _odt_fixture(tmp_path, f"_{name}", "engine residual")
    target = tmp_path / name
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w") as mutated:
        for entry in original.namelist():
            payload = original.read(entry)
            if entry == "META-INF/manifest.xml":
                payload = (
                    b'<?xml version="1.0" encoding="UTF-8"?>\n'
                    b"<manifest:manifest xmlns:manifest="
                    b'"urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>'
                )
            mutated.writestr(entry, payload)
    source.unlink()
    return target


def _soffice_version() -> str:
    """The measured engine version, so an engine-behaviour change is diagnosable."""
    from pdf_tooling.ports.office import probe

    report = probe()
    return f"{report.adapter} {report.version or '<unparsed>'}"


def engine_residual_complaints(
    *,
    dry_code: int,
    dry_rows: list[dict[str, Any]],
    real_code: int,
    soffice_version: str,
) -> list[str]:
    """Every violation of `README.md`'s code-`0` carve-out. Empty means ACCEPTED.

    Pure over its parameters so BOTH directions can be driven: the documented
    state from a real pair of runs, and the stale-claim branch from a
    convertible operand, without mutating the product to prove a point.
    """
    from pdf_tooling.ops.engine_disclosure import ENGINE_VERIFIED_KEY

    complaints: list[str] = []
    if dry_code == real_code:
        complaints.append(
            f"the engine residual has CLOSED against {soffice_version}: the preview and "
            f"the real run now agree (both exited {dry_code}). README.md's code-`0` row "
            f"carves out an exception this product no longer needs -- NARROW THE CLAIM. "
            f"Do not widen, bump or delete this arm: it is doing its job."
        )
        return complaints
    if real_code != 1:
        complaints.append(
            f"the real run exited {real_code}, not 1, against {soffice_version}: the "
            f"stimulus no longer reproduces the class the carve-out is about"
        )
    if dry_code != 0:
        complaints.append(
            f"the preview exited {dry_code}, not 0: the divergence the carve-out "
            f"discloses is not the one being measured"
        )
    for row in dry_rows:
        detail = row.get("detail")
        if not isinstance(detail, dict) or detail.get(ENGINE_VERIFIED_KEY) is not False:
            complaints.append(
                f"dry item {row.get('input')!r} does not state {ENGINE_VERIFIED_KEY}=False: "
                f"the payload no longer says what README.md says it says ({detail!r})"
            )
    return complaints


def _convert_dry_and_real(operand: Path, tmp_path: Path) -> tuple[int, list[dict[str, Any]], int]:
    """Drive *operand* through `convert` in both modes, `--out-dir` in each."""
    import json

    dry = run_cli(
        "convert", str(operand), "--out-dir", str(tmp_path / "dry"), "--dry-run", "-o", "json"
    )
    real = run_cli("convert", str(operand), "--out-dir", str(tmp_path / "real"), "-o", "json")
    dry_payload = json.loads(dry.stdout)
    return dry.returncode, list(dry_payload.get("items", [])), real.returncode


@pytest.mark.requires("soffice")
def test_pdf67_arm_c_the_engine_residual_is_the_documented_state(tmp_path: Path) -> None:
    """PDF-67 AC17, branch 1 -- the GREEN case, driven end to end.

    RED, branch 2 (observed): remove the disclosure from `ops/office.py`'s dry
    branch and this arm fails naming the item that stopped stating it.
    RED, branch 3: `test_pdf67_arm_c_reds_when_the_residual_closes` below.
    """
    operand = _odt_with_empty_manifest(tmp_path, "engine-residual.odt")
    dry_code, dry_rows, real_code = _convert_dry_and_real(operand, tmp_path)
    assert dry_rows, "the preview produced no item rows; this arm asserted nothing"
    assert (
        engine_residual_complaints(
            dry_code=dry_code,
            dry_rows=dry_rows,
            real_code=real_code,
            soffice_version=_soffice_version(),
        )
        == []
    ), f"dry={dry_code} real={real_code} rows={dry_rows}"


@pytest.mark.requires("soffice")
def test_pdf67_arm_c_reds_when_the_residual_closes(tmp_path: Path) -> None:
    """AC17's SECOND red, driven rather than asserted: point the arm's own
    verdict path at E10's V1 -- the CONVERTIBLE shape the shipped `_odt_fixture`
    builds -- and it must refuse, naming the measured engine version.

    This is the branch that keeps the arm from being a test that freezes a
    defect. If a future engine, or a wider spawn-free triage, makes the residual
    operand predictable, the arm demands that `README.md` be narrowed instead of
    staying silently green.
    """
    operand = _odt_fixture(tmp_path, "convertible.odt", "the control")
    dry_code, dry_rows, real_code = _convert_dry_and_real(operand, tmp_path)
    assert (dry_code, real_code) == (0, 0), (
        f"the CONTROL operand did not convert (dry={dry_code} real={real_code}); a "
        f"carve-out justified by a fixture everything fails is not a carve-out"
    )
    version = _soffice_version()
    complaints = engine_residual_complaints(
        dry_code=dry_code, dry_rows=dry_rows, real_code=real_code, soffice_version=version
    )
    assert complaints, "the arm accepted a CONVERGENT pair; branch 3 cannot fire"
    assert version in complaints[0], complaints
    assert "NARROW THE CLAIM" in complaints[0], complaints


def test_pdf67_arm_c_reds_when_the_disclosure_goes_missing() -> None:
    """AC17's FIRST red, as a standing arm: the divergence still there, the
    payload no longer saying so. Synthetic rows, because a red proof that
    vandalises the product it proves is not a proof."""
    from pdf_tooling.ops.engine_disclosure import ENGINE_VERIFIED_KEY

    honest = [{"input": "x.odt", "detail": {"would_exit": 0, ENGINE_VERIFIED_KEY: False}}]
    assert (
        engine_residual_complaints(
            dry_code=0, dry_rows=honest, real_code=1, soffice_version="<synthetic>"
        )
        == []
    )
    for rows in (
        [{"input": "x.odt", "detail": {"would_exit": 0}}],
        [{"input": "x.odt", "detail": None}],
        [{"input": "x.odt", "detail": {"would_exit": 0, "engine_checked": False}}],
        [{"input": "x.odt", "detail": {"would_exit": 0, ENGINE_VERIFIED_KEY: True}}],
    ):
        complaints = engine_residual_complaints(
            dry_code=0, dry_rows=rows, real_code=1, soffice_version="<synthetic>"
        )
        assert complaints, f"the arm accepted a payload with no honest disclosure: {rows}"
        assert ENGINE_VERIFIED_KEY in complaints[0], complaints
