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

**Why the signal is sent once HALF the pages exist, not the first one.**
An earlier version of this test signalled as soon as a single file
appeared, which is the WORST possible moment: `multiprocessing`'s default
start method is `spawn` on macOS, so every worker cold-imports pypdfium2,
Pillow and this whole package independently, and workers finish that cold
start at staggered times. Signalling at the very first file means most of
the OTHER 7 workers are still statistically likely to be deep inside their
own first, cold, uninterruptible C call (pdfium's render, or Pillow's
max-compression PNG encode) at that exact instant -- and CPython cannot
deliver a signal into a running C call, only at the next bytecode boundary
(the `signal` module's own documented limitation), so a worker caught
there is SIGKILLed with no chance to discard its own temp file. This was
caught live: CI's `macos-14` leg reproduced exactly this, leaving one
`.pdftoolkit-*` stray on the SIGTERM arm. Waiting for half the run's pages
to already exist means most workers have survived their own cold start and
are between pages -- ordinary, interruptible Python bytecode -- when the
signal lands, which is what `ops/procpool.py::TEARDOWN_GRACE_S`'s own
docstring calls a best-effort, not a guaranteed, property.
"""

from __future__ import annotations

import multiprocessing
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
#: signal sent once half the pages exist still lands with genuine work
#: ahead of it, on a CI runner slower or faster than the box this was
#: measured on.
_PAGE_COUNT = 32
_DPI = "400"

#: The `multiprocessing` start method this host will actually use. The product
#: pins none (`ops/procpool.py` constructs a plain `ProcessPoolExecutor`), so the
#: CLI subprocess resolves the same platform default this test process does.
_START_METHOD: str = multiprocessing.get_start_method()

#: Signal once at least this many pages already exist -- not the first one.
#: See the module docstring for why: signalling at the very first file
#: statistically catches the OTHER workers mid cold-start, which is exactly
#: the residue this spec must not introduce.
_SIGNAL_AT_COUNT = _PAGE_COUNT // 2

#: Generous: a `spawn`-started worker's cold import (pypdfium2, Pillow, this
#: whole package) plus its first render can cost real seconds on a loaded CI
#: VM, and this is waiting for HALF the run, not one page.
_PROGRESS_TIMEOUT_S = 60.0
#: `ops/procpool.py::TEARDOWN_GRACE_S` is paid in full on every signalled
#: teardown (see that module's docstring), so this must clear it with room
#: for process spawn/reap overhead on top.
_PARENT_EXIT_TIMEOUT_S = 25.0
_SETTLE_S = 1.0
#: PDF-21/AC11: how long the enumerated-survivor check polls. Under SIGKILL
#: to the parent, the kernel delivers PR_SET_PDEATHSIG's SIGKILL to each
#: worker asynchronously and the subreaper reaps them asynchronously too, so
#: a single sample is a race. This is a bound on a teardown that is expected
#: to complete in milliseconds, not a probability judgment.
_SURVIVOR_TIMEOUT_S = 10.0


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


def _wait_for_progress(out_dir: Path, *, at_least: int, timeout: float) -> int:
    """Block until *out_dir* holds at least *at_least* files, and return the
    count actually observed. See the module docstring for why this waits
    for substantial progress rather than the first file."""
    deadline = time.monotonic() + timeout
    count = 0
    while time.monotonic() < deadline:
        count = len(list(out_dir.iterdir())) if out_dir.is_dir() else 0
        if count >= at_least:
            return count
        time.sleep(0.05)
    pytest.fail(
        f"only {count}/{at_least} files appeared under {out_dir} within {timeout}s "
        f"-- render started too slowly (or not at all) for this test to be decisive"
    )


def _send_signal_and_measure(
    tmp_path: Path, sig: signal.Signals
) -> tuple[subprocess.Popen[bytes], int, int, tuple[Path, ...]]:
    """Launch a real `rasterize` job, signal the PARENT PID ONLY once it has
    made substantial, demonstrable progress, and return
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
        _wait_for_progress(out_dir, at_least=_SIGNAL_AT_COUNT, timeout=_PROGRESS_TIMEOUT_S)

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


#: PDF-21/AC10-AC11. `_group_alive` answers "does ANYTHING exist under this
#: pgid", which is the portable check the SIGTERM/SIGINT arms use. The two arms
#: added by PDF-21 additionally ENUMERATE the survivors by PID, for two reasons
#: the wave-3 `PDF-05` AC10 inversion (`5d5c4d49bd`) makes concrete: a control
#: that reports a boolean cannot say WHAT survived, and `killpg(pgid, 0)`
#: counts an unreaped ZOMBIE as alive -- which under SIGKILL-to-parent is the
#: normal, harmless transient while the kernel's PR_SET_PDEATHSIG kills land and
#: the subreaper reaps them. A zombie holds no memory and writes no output, so
#: it is not a survivor; a live worker is.
def _live_group_members(pgid: int) -> tuple[tuple[int, str], ...]:
    """Every NON-ZOMBIE live pid whose process group is *pgid*, from /proc.

    Enumeration, not a return value: this reads the kernel's own view of which
    processes exist. Returns ``()`` where ``/proc`` is unavailable (macOS), in
    which case the caller falls back to :func:`_group_alive` alone -- which is
    why the SIGKILL arm this backs is `skipif`-gated to Linux in the first
    place.
    """
    procfs = Path("/proc")
    if not procfs.is_dir():  # pragma: no cover - macOS
        return ()
    members: list[tuple[int, str]] = []
    for entry in procfs.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:  # pragma: no cover - the pid exited mid-scan
            continue
        try:
            # `comm` is parenthesised and may itself contain spaces/parens, so
            # the fields after it are found from the LAST ')'.
            fields = stat[stat.rindex(")") + 2 :].split()
            state, pgrp = fields[0], int(fields[2])
        except (ValueError, IndexError):  # pragma: no cover - malformed/raced
            continue
        if pgrp != pgid or state == "Z":
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:  # pragma: no cover - the pid exited mid-scan
            cmdline = ""
        members.append((int(entry.name), cmdline.strip()))
    return tuple(members)


def _wait_for_no_survivors(pgid: int, *, timeout: float) -> tuple[tuple[int, str], ...]:
    """Poll until the group holds no live non-zombie member, and return whatever
    is left when the deadline expires. Bounded polling, not a bare sleep: under
    SIGKILL-to-parent the kernel's PR_SET_PDEATHSIG deliveries and the
    subreaper's reaps are asynchronous, and asserting on the first sample would
    make this arm a race rather than a control."""
    deadline = time.monotonic() + timeout
    survivors = _live_group_members(pgid)
    while survivors and time.monotonic() < deadline:
        time.sleep(0.05)
        survivors = _live_group_members(pgid)
    return survivors


def _assert_enumerated_zero_survivors(proc: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    """Zero survivors, with NO exclusion list.

    An earlier version of this helper excluded processes whose command line named
    `multiprocessing.forkserver` / `multiprocessing.resource_tracker`, on the
    theory that those are infrastructure rather than render workers. **That was
    wrong and it made the control unable to fail**: under the `forkserver` start
    method a render worker is forked FROM the forkserver and inherits its command
    line verbatim, so the exclusion excluded the very processes the arm exists to
    catch. It was caught one assertion later by the "no new output" check, which
    is exactly why this arm asserts both. Recorded rather than quietly reverted.
    """
    survivors = _wait_for_no_survivors(proc.pid, timeout=_SURVIVOR_TIMEOUT_S)
    assert survivors == (), (
        f"after {sig.name} to the parent PID alone, these processes are still alive in "
        f"the launched job's own process group (pgid {proc.pid}): {survivors} -- each one "
        f"is an orphaned render worker holding pdfium/Pillow buffers"
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


# --------------------------------------------------------------------------- #
# PDF-21 D6 -- the two arms the committed suite never had.
#
# E-3, measured: this file contained exactly TWO test functions (SIGTERM and
# SIGINT). `changelog.md` claims "SIGTERM, SIGINT and SIGHUP all route through
# the one teardown routine" and the QA reports record all four signals at zero
# survivors -- but those were probes recorded in a report, not committed
# controls, and the ONE arm `PR_SET_PDEATHSIG` exists to serve, SIGKILL, had
# never had a test on any platform. "Probed once, never re-runnable" is not
# coverage.
# --------------------------------------------------------------------------- #


def test_sighup_to_parent_only_stops_new_output_and_leaves_no_survivors(
    tmp_path: Path,
) -> None:
    """SIGHUP gets the SAME measurement discipline as the SIGTERM and SIGINT
    arms: the PARENT PID ALONE (X-119 -- signalling the group would kill the
    workers directly and manufacture a pass), the positive control (parent
    alive, pool members present, ``count_at_death < _PAGE_COUNT``), zero new
    output after death, and zero survivors -- here ENUMERATED by pid as well as
    probed with ``killpg(pgid, 0)``.
    """
    proc, count_at_death, count_after_settle, strays = _send_signal_and_measure(
        tmp_path, signal.SIGHUP
    )
    _assert_clean_signal_death(proc, signal.SIGHUP, count_at_death, count_after_settle, strays)
    _assert_enumerated_zero_survivors(proc, signal.SIGHUP)


@pytest.mark.xfail(
    _START_METHOD == "forkserver",
    strict=True,
    reason=(
        "PDF-21 finding: PR_SET_PDEATHSIG does not protect a `forkserver` worker. The "
        "kernel sends the death signal when the worker's OWN parent dies, and under "
        "`forkserver` that parent is the forkserver helper, not the CLI process -- so a "
        "SIGKILLed `pdftoolkit` leaves its render workers running AND STILL WRITING PAGES. "
        "Measured on CI's `test (3.14, ubuntu-latest)` leg: output grew from 16 to 24 files "
        "after the parent was reaped. Python 3.14 makes `forkserver` the DEFAULT on Linux, "
        "so this is a live gap on a supported platform, not a hypothetical. Filed, not "
        "fixed -- PDF-21 is a verification spec and `ops/procpool.py` is Scope > Out; "
        "changing the start method or arming the guard in the forkserver is a behaviour "
        "change to a shipped verb and belongs to its own spec. `strict=True` so the day the "
        "mechanism is repaired this marker fails and has to be removed."
    ),
)
@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason=(
        "the SIGKILL-to-parent orphan guard is PR_SET_PDEATHSIG, and prctl is a "
        "Linux syscall (ops/procpool.py:235). There is no macOS equivalent, so on "
        "macos-14 this arm is a VISIBLE SKIP rather than a silent absence -- the "
        "verification gap X-153 rules is filed, not closed (see PDF-21 D7)."
    ),
)
def test_sigkill_to_parent_only_leaves_no_survivors_on_linux(tmp_path: Path) -> None:
    """The one arm ``PR_SET_PDEATHSIG`` exists for, and the one that never had a
    test. SIGKILL cannot be handled by the parent at all: no handler, no
    ``finally``, nothing runs. The only thing the CHILD side can still do is ask
    the kernel to SIGKILL it when its parent dies, which ``ops/procpool.py``
    does at worker start-up, on Linux only.

    **Residue is EXPECTED here and is deliberately not asserted against.** A
    SIGKILLed worker cannot run its own ``AtomicWriter.__exit__`` to discard its
    in-flight temp file; ``PLAN §12 R-07`` accepts that class. What is asserted
    is what the guarantee actually claims: **zero surviving processes and zero
    new output after the parent is gone.**
    """
    proc, count_at_death, count_after_settle, _strays = _send_signal_and_measure(
        tmp_path, signal.SIGKILL
    )
    assert proc.returncode == -signal.SIGKILL, proc.returncode
    # The positive control, part of the assertion and not a preamble: the job
    # was genuinely mid-flight, so "no growth after death" is not vacuously
    # true of a run that had already finished.
    assert count_at_death < _PAGE_COUNT, (
        f"{count_at_death}/{_PAGE_COUNT} files existed at parent death -- the job "
        f"already finished before SIGKILL arrived; tune _DPI/_PAGE_COUNT"
    )
    _assert_enumerated_zero_survivors(proc, signal.SIGKILL)
    # Only NOW is "no new output" decisive: it is asserted after the survivors
    # are gone, so it cannot pass merely because the settle window was short.
    assert len(list((tmp_path / "out").iterdir())) == count_after_settle == count_at_death, (
        "new output appeared after the parent was SIGKILLed -- a worker outlived it"
    )
