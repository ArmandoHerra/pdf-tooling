"""``rasterize`` does not survive a signal to its parent (B-055).

Black-box, subprocess-level, and **start-method agnostic by construction**:
this file never touches ``multiprocessing`` internals, never patches
anything in-process, and never asks "was this worker forked or spawned?" —
it only observes three things any start method produces identically: files
landing on disk, the LAUNCHED PROCESS's own exit status, and whether its OS
process GROUP still has any member at all. Commit ``26f4c79`` ("make
AC5/AC26 tests spawn-safe, not fork-only") is exactly the failure mode this
shape avoids by not depending on it in the first place.

Every signal here is sent to the **parent PID only, never its process
group**. Signalling the whole group would kill the render workers directly
and prove nothing — that is precisely the defect this spec fixes: a bare,
single-process ``kill <pid>`` (what ``timeout``, ``kill``, systemd,
``docker stop`` and CI job cancellation all send) must be enough on its own.

Every launched process uses ``start_new_session=True``, which makes it a new
session AND process-group leader in the same syscall (POSIX ``setsid()``);
every worker it forks/spawns afterwards inherits that same process-group id
without ever calling ``setpgid`` itself. ``_group_alive()`` below is exactly
``adapters/subprocess_util.py::_group_alive`` restated locally rather than
imported: signal 0 to the group answers "does anything (including an
unreaped zombie) still exist under this pgid at all", which is the T4
"zero surviving worker processes" check the spec calls for, without parsing
platform-specific ``ps`` output (BSD ``ps`` on macOS and GNU ``ps`` on Linux
do not agree on a stable ``sid``/``pgid`` column spelling; killpg's signal-0
probe has no such disagreement — it is the same syscall on both CI platforms
in this project's matrix, ``ubuntu-latest`` and ``macos-14``).

**Why the observation window here is shorter than the >=5s used in the
manual repro, and still decisive.** ``guarded_process_pool``'s own signal
handler (``ops/procpool.py``) SIGTERMs every worker, waits out its grace
window, SIGKILLs stragglers, and ``.join()``s all of them -- synchronously,
before it lets the parent die by the signal. By the time this test's
``proc.wait()`` unblocks, every worker the parent ever owned has therefore
already been reaped; there is no code path in which one could still be
running, so the length of the settle window used to double-check the file
count is not a probability judgment the way the PM's manual repro's ``>=5s``
necessarily was against unpatched code -- it exists only as a margin against
filesystem/OS scheduling noise, not against a race this test is hoping to
win.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_toolkit.safety.tempnames import find_stray_temps  # noqa: E402
from registry import console_script  # noqa: E402

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        sys.platform.startswith("win"),
        reason="os.killpg/SIGTERM/SIGHUP process teardown is POSIX-only (B-055); "
        "this product ships no Windows job (pyproject.toml classifiers, CI matrix)",
    ),
]

#: 32 pages at a DPI high enough to keep 8 workers busy for several seconds
#: (measured locally: ~3.7s unsignalled, 8 threads) -- long enough that a
#: signal sent once the first file appears lands with several seconds of
#: genuine work still ahead of it, on a CI runner slower or faster than the
#: box this was measured on.
_PAGE_COUNT = 32
_DPI = "400"

_FIRST_OUTPUT_TIMEOUT_S = 20.0
_PARENT_EXIT_TIMEOUT_S = 10.0
_SETTLE_S = 1.0


def _make_source(directory: Path, *, pages: int = _PAGE_COUNT) -> Path:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "signals-source.pdf"
    made = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    made.setProducer("pdf-toolkit test corpus")
    made.setCreator("tests/integration/test_rasterize_signals.py")
    for number in range(1, pages + 1):
        made.drawString(72, 700, f"src page {number}")
        made.showPage()
    made.save()
    return path


def _group_alive(pgid: int) -> bool:
    """Mirrors ``adapters/subprocess_util.py::_group_alive`` -- see the
    module docstring for why this is restated locally rather than imported.
    """
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - not reachable for our own child
        return True
    return True


def _wait_for_first_output(out_dir: Path, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if out_dir.is_dir() and any(out_dir.iterdir()):
            return
        time.sleep(0.05)
    pytest.fail(f"no output appeared under {out_dir} within {timeout}s -- render never started")


def _send_signal_and_measure(
    tmp_path: Path, sig: signal.Signals
) -> tuple[subprocess.Popen[bytes], int, int, tuple[Path, ...]]:
    """Launch a real `rasterize` job, signal the PARENT PID ONLY once it has
    demonstrably started writing, and return
    ``(process, count_at_death, count_after_settle, stray_temps)``.
    """
    source = _make_source(tmp_path / "src")
    out_dir = tmp_path / "out"

    proc = subprocess.Popen(
        [
            *console_script(),
            "rasterize",
            str(source),
            "--dpi",
            _DPI,
            "--out-dir",
            str(out_dir),
            "--threads",
            "8",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        _wait_for_first_output(out_dir, timeout=_FIRST_OUTPUT_TIMEOUT_S)

        # THE PID ONLY -- never the group. Signalling the group would kill
        # the workers directly and prove nothing about the parent's own
        # teardown (see module docstring).
        os.kill(proc.pid, sig)

        try:
            proc.wait(timeout=_PARENT_EXIT_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            pytest.fail(
                f"parent did not exit within {_PARENT_EXIT_TIMEOUT_S}s of "
                f"{sig.name} -- teardown hung instead of tearing down"
            )

        count_at_death = len(list(out_dir.iterdir()))
        # Decisive by construction, not by luck -- see module docstring.
        time.sleep(_SETTLE_S)
        count_after_settle = len(list(out_dir.iterdir()))

        strays = find_stray_temps(out_dir)
    finally:
        if proc.poll() is None:  # pragma: no cover - defensive, only if the above raised
            proc.kill()
            proc.wait(timeout=5)

    return proc, count_at_death, count_after_settle, strays


def _assert_clean_signal_death(
    proc: subprocess.Popen[bytes],
    sig: signal.Signals,
    count_at_death: int,
    count_after_settle: int,
    strays: tuple[Path, ...],
) -> None:
    # (f) Died BY the signal -- WIFSIGNALED true -- not via sys.exit(). A
    # negative returncode is `subprocess`'s own encoding of that fact.
    assert proc.returncode == -sig, (
        f"expected the process to die by {sig.name} (returncode {-sig}), "
        f"got {proc.returncode} -- this is the mechanized proof that death "
        f"came from the signal itself, not from sys.exit(128 + signo)"
    )

    # Genuinely mid-flight: the job did NOT already finish before the signal
    # landed. Without this, "no growth after death" would be vacuously true
    # of a job that had already completed on its own -- the exact "a
    # single post-hoc count proves nothing" trap this spec's brief names.
    assert count_at_death < _PAGE_COUNT, (
        f"{count_at_death}/{_PAGE_COUNT} files existed at parent death -- the "
        f"job already finished before the signal arrived; tune _DPI/_PAGE_COUNT"
    )

    # T3/T6's own core claim: the count does not move after the parent dies.
    assert count_after_settle == count_at_death, (
        f"file count grew from {count_at_death} to {count_after_settle} after "
        f"the parent died -- new output was written after the process that "
        f"produced it no longer exists"
    )

    # (e) The fix must not trade orphaned processes for orphaned temp files.
    assert strays == (), f"stray .pdftoolkit-* temp file(s) left behind: {strays}"

    # T4: zero surviving workers, by the same portable check
    # `adapters/subprocess_util.py` already uses for its own group teardown.
    assert not _group_alive(proc.pid), (
        f"a process is still alive in the launched job's own process group "
        f"(pgid {proc.pid}) after the parent exited -- a worker outlived it"
    )


def test_sigterm_to_parent_only_stops_new_output_and_leaves_no_survivors(
    tmp_path: Path,
) -> None:
    proc, count_at_death, count_after_settle, strays = _send_signal_and_measure(
        tmp_path, signal.SIGTERM
    )
    _assert_clean_signal_death(proc, signal.SIGTERM, count_at_death, count_after_settle, strays)


def test_sigint_to_parent_only_stops_new_output_and_leaves_no_survivors(
    tmp_path: Path,
) -> None:
    """T6 -- SIGINT gets the SAME measurement discipline as T3's SIGTERM arm.

    Measured directly against the unfixed code (module docstring / spec
    report): a bare ``kill -INT <parent pid only>`` does NOT stop the job --
    it runs to completion, identically to the SIGTERM defect. "SIGINT is
    already clean" was true only for an interactive Ctrl-C, which signals
    the whole foreground process group and kills workers directly,
    independent of anything this process does. This arm proves SIGINT is
    clean under the harder, accident-free discipline too, because
    `guarded_process_pool` now handles it through the identical routine.
    """
    proc, count_at_death, count_after_settle, strays = _send_signal_and_measure(
        tmp_path, signal.SIGINT
    )
    _assert_clean_signal_death(proc, signal.SIGINT, count_at_death, count_after_settle, strays)
