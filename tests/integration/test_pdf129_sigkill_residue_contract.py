"""PDF-129: say what a SIGKILLed run leaves behind, and prove a live run's temp is never swept.

A hard kill cannot be handled by any process, so it can leave a hidden temp
beside the destination. ``PLAN.md`` §12 R-07 ("report, never sweep") is decided
and the temp name carries no liveness signal, so PDF-129 takes the documented
fallback: no reaper. This module pins the two halves of that decision.

* **Behaviour.** A SIGKILLed writer's temp survives the next successful write
  into its directory (arm 1), and a LIVE writer's temp survives a concurrent
  write into its directory (arm 2). Arm 2 is the liveness control: every
  non-liveness predicate a reaper could use (same uid, the exact name grammar,
  zero bytes, mtime older than the second run's start) holds for it, so only a
  liveness check could separate it from a dead writer's temp.
* **Documents.** The README safety contract, the website's atomic-write failure
  sentence (EN and ES) and ``doctor --strict``'s help say what the behaviour is.

The literal temp prefix is never spelled here: every pattern is built from
``TEMP_PREFIX`` (a guard that had to name it to forbid sweeping it would grow
the population it protects).
"""

from __future__ import annotations

import json
import os
import re
import signal
import stat
import sys
import time
from pathlib import Path
from typing import Any, Final

import pytest

from pdf_tooling.safety import TEMP_PREFIX, find_stray_temps

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from test_atomic_crash import park_at  # noqa: E402

from atomic_harness import REPO_ROOT, run_harness  # noqa: E402

POINT: Final[str] = "after_temp_create"
TEMP_NAME: Final[re.Pattern[str]] = re.compile(re.escape(TEMP_PREFIX) + r"[a-z0-9_]{8}")
README: Final[Path] = REPO_ROOT / "README.md"
CONTRACTS_JSON: Final[Path] = REPO_ROOT / "website" / "src" / "data" / "contracts.json"
COPY_ES: Final[Path] = REPO_ROOT / "website" / "src" / "lib" / "copy-es.ts"


def _only_temp(directory: Path) -> Path:
    temps = find_stray_temps(directory)
    assert len(temps) == 1, f"expected exactly the parked writer's temp, found {temps}"
    return temps[0]


def _write(target: Path) -> None:
    done = run_harness(["write", "--target", str(target), "--content", "second writer"])
    assert done.returncode == 0, done.stderr
    assert target.read_bytes() == b"second writer"


def test_a_sigkilled_writers_temp_survives_the_next_write_into_its_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()

    with park_at(POINT, ["write", "--target", str(work / "a.pdf")]) as parked:
        t1 = _only_temp(work)
        assert parked.kill() == -signal.SIGKILL

    _write(work / "b.pdf")

    assert t1.exists(), "a later successful write swept a SIGKILLed run's temp"
    info = t1.stat()
    assert info.st_size == 0
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert t1 in find_stray_temps(work)
    assert TEMP_NAME.fullmatch(t1.name), f"the temp name grammar moved: {t1.name!r}"
    assert not (work / "a.pdf").exists()

    from pdf_tooling.cli import cmd_doctor

    payload = cmd_doctor.build_payload(strict=True, dry_run=False, root=work)
    assert str(t1) in payload["stray_temp_files"]

    class _Available:
        def to_dict(self) -> dict[str, Any]:
            return {"port": "fake", "available": True}

    monkeypatch.setattr(cmd_doctor, "resolve_all", lambda: [_Available()])
    clean_host = cmd_doctor.build_payload(strict=True, dry_run=False, root=work)
    assert str(t1) in clean_host["stray_temp_files"]
    assert clean_host["exit_code"] == 0, "a stray temp must never change doctor's exit code"


def test_a_live_writers_temp_survives_a_concurrent_write_into_its_directory(
    tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    work.mkdir()

    with park_at(POINT, ["write", "--target", str(work / "a.pdf")]) as parked:
        try:
            t1 = _only_temp(work)
            t_start = time.time()
            # Non-vacuity: the age predicate a reaper would use genuinely holds.
            assert t1.stat().st_mtime <= t_start
            assert t1.stat().st_uid == os.getuid()
            assert t1.stat().st_size == 0
            assert TEMP_NAME.fullmatch(t1.name)

            _write(work / "b.pdf")

            assert t1.exists(), "a concurrent write swept a LIVE writer's temp"
            assert parked.release() == 0
            assert (work / "a.pdf").exists()
            assert not t1.exists()
        finally:
            if parked.process.poll() is None:  # pragma: no cover - only on a failed arm
                parked.kill()


def _readme_section(heading: str) -> str:
    text = README.read_text(encoding="utf-8")
    start = text.index(f"\n{heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def test_the_readme_safety_contract_discloses_sigkill_residue() -> None:
    section = _readme_section("## Safety contract")
    for needle in (TEMP_PREFIX, "doctor --strict", "SIGKILL", "never deletes"):
        assert needle in section, f"README Safety contract no longer says {needle!r}"


def test_the_website_failure_sentence_no_longer_promises_deletion_on_a_kill() -> None:
    english = json.loads(CONTRACTS_JSON.read_text(encoding="utf-8"))["atomicWrite"]["failure"]
    assert "SIGKILL" in english

    source = COPY_ES.read_text(encoding="utf-8")
    block = source[source.index("export const ATOMIC_ES") :]
    spanish = block[: block.index("} as const")]
    assert "SIGKILL" in spanish


def test_doctor_strict_help_names_its_search_root() -> None:
    from typer.testing import CliRunner

    from pdf_tooling.cli.main import app

    result = CliRunner().invoke(app, ["doctor", "--help"], env={"COLUMNS": "400"})
    assert result.exit_code == 0, result.output
    assert "under the current directory" in " ".join(result.output.split())
