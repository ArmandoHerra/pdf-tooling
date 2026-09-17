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

import contextlib
import multiprocessing
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_tooling.safety.tempnames import find_stray_temps  # noqa: E402
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

#: The `multiprocessing` start method THIS TEST PROCESS's host defaults to.
#:
#: **It describes the host and nothing else.** PDF-35 pinned the product's own
#: pool to `spawn` (`ops/procpool.py::_START_METHOD`, ruling X-401), so the CLI
#: subprocess no longer resolves this platform default -- an explicit
#: `mp_context=` defeats it, which is the whole point of the pin. Before
#: PDF-35 this constant said "the product pins none", derived the suite's
#: expectations FROM the ambient default, and was accurate; the pin falsified
#: it, and correcting it is PDF-35 AC6.
#:
#: **No expectation about the CLI may be derived from this value.** A claim
#: about the product's start method belongs to
#: `tests/integration/test_render_pool_start_method.py`, which asserts the
#: product's own declaration and then proves it against the kernel. Left here
#: only because the module docstring's start-method-agnostic reasoning still
#: wants to be able to name what the host would have done.
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
#: The p95 of the PARENT's own teardown overhead -- everything
#: `_terminate_pool` pays ON TOP of its grace window: the SIGKILL sweep, the
#: joins, `shutdown(wait=False)` and interpreter exit.
#:
#: PDF-78, MEASURED rather than assumed, on the same instrumented shadow copy
#: and the same 20-teardown protocol that derived `TEARDOWN_GRACE_S`, at the
#: heaviest declared load (`L5` = 5 x cpu_count, loadavg 42.67-67.12):
#: p95 0.327 s, max 0.521 s. At L2 it is 0.199 s and at L0 0.087 s -- i.e. it
#: is an order of magnitude smaller than the grace and it barely moves with
#: load, which is what makes the bound below mostly a statement about the
#: grace.
_PARENT_OVERHEAD_P95_S = 0.327
#: `ops/procpool.py::TEARDOWN_GRACE_S` is paid in full on every signalled
#: teardown -- MEASURED, not inferred: 8 of 8 workers were still alive when
#: that module's grace loop reached its deadline in all 60 teardowns PDF-78
#: sampled across three declared loads. So this must clear it with room for
#: process spawn/reap overhead on top, and it is now DERIVED FROM IT rather
#: than picked: `TEARDOWN_GRACE_S` (16.0) + `_PARENT_OVERHEAD_P95_S` (0.327)
#: = 16.327 s, and
#: `tests/unit/test_procpool.py::test_the_grace_fits_inside_the_parent_exit_bound`
#: reddens by name the day a raised grace stops fitting.
#:
#: THE VALUE IS HELD AT 25.0 AND NOT NARROWED TO 17, and that is a decision
#: rather than an omission. This is a BOUND, not a budget: it is paid only on
#: pathology, so its size costs no wall-clock on any run that works, while
#: shrinking it to hug the measurement would convert the next load spike into
#: a NEW flake -- which is the exact defect this spec exists to remove. It may
#: not be WIDENED to make room for a grace that does not fit (that would be
#: the forbidden move one file over); it is simply not required to shrink.
_PARENT_EXIT_TIMEOUT_S = 25.0
_SETTLE_S = 1.0
#: PDF-21/AC11: how long the enumerated-survivor check polls. Under SIGKILL
#: to the parent, the kernel delivers PR_SET_PDEATHSIG's SIGKILL to each
#: worker asynchronously and the subreaper reaps them asynchronously too, so
#: a single sample is a race. This is a bound on a teardown that is expected
#: to complete in milliseconds, not a probability judgment.
_SURVIVOR_TIMEOUT_S = 10.0


# --------------------------------------------------------------------------- #
# PDF-78 D2 -- THE DECLARED LOAD.
#
# AMBIENT LOAD IS NOT A TEST CONDITION. Every recorded occurrence of the stray
# flake this harness exists for happened under load nobody created on purpose --
# three overlapping agent pytest runs on an 8-cpu box, a foreign `make ci` from
# another checkout. A `qa-sentinel` cannot re-drive that, and a number derived
# under it is evidence about one afternoon. So the contention is GENERATED here,
# sized as a multiple of `cpu_count` rather than as an absolute loadavg (the core
# count is part of every figure, so a declaration of "2" transfers to a host with
# a different one), and the harness REFUSES a load band on a host it measures as
# quiet -- `perf/README.md`'s own `quiet` predicate with its sign flipped, which
# is exactly why this inverted rule cannot live in `perf/` beside a rule that
# says a `quiet: false` record is inadmissible as a baseline.
#
# OPT-IN, AND NOT A STANDING GATE ARM (D7.5). Unset -- the default, and what
# every CI leg does -- this fixture starts nothing, samples nothing and costs
# nothing; the four arms below run byte-identically to before this spec. Set, it
# is the REPRODUCIBLE form of the stimulus the ledger row recorded:
#
#     PDF_TOOLING_DECLARED_LOAD=2 uv run pytest \
#         tests/integration/test_rasterize_signals.py -q -p no:randomly -n0
#
# `-n0` is part of the recipe and not an aside: under `-n auto` each xdist worker
# would start a cohort of its own and the real load would be a multiple of the
# declared one. The loadavg actually observed is printed at start, peak and end,
# so an over-loaded run is visible in the record rather than silent.
#
# BANDS, both derived from what the ledger recorded rather than chosen:
#   L2  2 x cpu_count -- the REPRODUCTION band (2026-09-15, loadavg ~12-17 on 8
#                        cpus). A repair validated only against a heavier load
#                        has not addressed the failure that actually last happened.
#   L5  5 x cpu_count -- the DERIVATION band (2026-09-05, loadavg 34-44).
#   L0  0             -- the DISCRIMINATION control. Without it a green run is a
#                        number, not evidence: alternated pairs in a quiet window
#                        gave 0/5 on both arms BEFORE any change.
#
# IT NEVER ABSTAINS, and that is the whole point. A band it cannot establish is a
# FAILURE, never a skip. An arm that abstains under load has not survived a
# loaded host; it has learned to recognise one.
#
# THE GENERATOR IS STDLIB AND HONEST ABOUT WHAT IT DOES NOT MODEL. Busy loops
# create CPU contention; the recorded occurrences also carried memory pressure,
# page-cache churn and competing I/O from concurrent pytest runs. The declared
# load is therefore a LOWER BOUND on the hostility of the real band, and any
# value derived under it inherits that conservatism in the unhelpful direction.
# --------------------------------------------------------------------------- #

#: The operator's declaration: `L`, a multiple of `cpu_count`. Absent or empty
#: means "generate nothing", which is the default and is what CI runs.
_DECLARED_LOAD_ENV = "PDF_TOOLING_DECLARED_LOAD"

#: How long to let the 1-minute loadavg rise into the declared band before the
#: arms start. The kernel's figure is an exponential moving average with a
#: 60-second time constant, so a cohort started and measured immediately reports
#: the load of the minute BEFORE it existed -- which is how a declared-load
#: harness comes to record a band it never actually applied. A CEILING, not a
#: cost: the ramp ends the moment the band floor below is reached.
_LOAD_RAMP_S = 300.0

#: The fraction of the cohort's own asymptote that counts as "the band was
#: applied". `L x cpu_count` busy loops drive the 1-minute average toward
#: `L x cpu_count`, so this floor is 12 at `L2` and 30 at `L5` on an 8-cpu host
#: -- which is where the ledger's two recorded failure bands (12-17 and 34-44)
#: actually sit.
#:
#: THIS EXISTS BECAUSE THE FIRST VERSION OF THIS FIXTURE WAS WRONG, and the
#: error is worth keeping visible: it ramped only until the host stopped being
#: QUIET, and `quiet` is `loadavg <= 0.25 x cpu_count`, i.e. 2.0 here. So it
#: declared `L2`, ramped for four seconds, recorded `quiet: false` at loadavg
#: 2.26 and ran the arms at a twentieth of the declared band -- a harness that
#: reports the load it was ASKED for rather than the load it APPLIED, which is
#: the exact failure mode `perf/README.md`'s `quiet` field exists to prevent.
#: Caught by driving it and reading its own printed loadavg.
_BAND_FLOOR_FRACTION = 0.75

#: Long enough that the cohort outlives any drive; the fixture reaps it in a
#: `finally` regardless, and asserts the reap.
_LOAD_HOLD_S = 3600.0

#: One stdlib busy loop, as a program rather than as a picklable callable: a
#: `subprocess` cohort needs no start method, pickles nothing, and cannot fail to
#: import this module inside a child -- and it leaves nothing for
#: `multiprocessing`'s resource tracker to inherit into the render pool's own
#: process group, which this file spends its docstring keeping clean.
_BURN_PROGRAM = (
    "import sys, time\n"
    "deadline = time.monotonic() + float(sys.argv[1])\n"
    "value = 0\n"
    "while time.monotonic() < deadline:\n"
    "    for _ in range(200000):\n"
    "        value = (value * 1103515245 + 12345) & 0x7FFFFFFF\n"
)


def _host_is_quiet() -> bool:
    """``perf/README.md``'s own predicate, in its loadavg half.

    That document derives `quiet` as ``loadavg_start <= 0.25 * cpu_count`` AND
    no foreign non-descendant process at or above 25 % cpu. Only the first half
    is computable from here without a process table walk, and it is the half
    that decides this measurement: a cohort of `L x cpu_count` busy loops moves
    loadavg by construction, so a host that still reports quiet after the ramp
    is a host where the cohort did not start.
    """
    return os.getloadavg()[0] <= 0.25 * (os.cpu_count() or 1)


@pytest.fixture(scope="module", autouse=True)
def declared_load() -> Iterator[None]:
    """Generate, hold and reap the declared load; refuse a band it cannot apply.

    Yields immediately and starts nothing when `$PDF_TOOLING_DECLARED_LOAD` is
    unset, which is the default posture and the one CI runs.
    """
    raw = os.environ.get(_DECLARED_LOAD_ENV, "").strip()
    if not raw:
        yield
        return

    multiple = float(raw)
    cpus = os.cpu_count() or 1
    cohort_size = int(round(multiple * cpus))
    cohort: list[subprocess.Popen[bytes]] = []
    observed: list[float] = []
    try:
        for _ in range(cohort_size):
            cohort.append(
                subprocess.Popen(
                    [sys.executable, "-c", _BURN_PROGRAM, str(_LOAD_HOLD_S)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        band_floor = _BAND_FLOOR_FRACTION * multiple * cpus
        ramp_until = time.monotonic() + (_LOAD_RAMP_S if cohort_size else 0.0)
        while time.monotonic() < ramp_until and os.getloadavg()[0] < band_floor:
            observed.append(os.getloadavg()[0])
            time.sleep(2.0)

        at_start = os.getloadavg()[0]
        observed.append(at_start)
        quiet = _host_is_quiet()
        if cohort_size and quiet:
            pytest.fail(
                f"declared load L={multiple} started {cohort_size} busy process(es) and "
                f"the host still measures QUIET after {_LOAD_RAMP_S}s "
                f"(loadavg {at_start:.2f} <= 0.25 x {cpus}). Refusing to record a loaded "
                f"band on a quiet host -- a measurement taken here would be reported as "
                f"contention and would be nothing of the kind"
            )
        if cohort_size and at_start < band_floor:
            pytest.fail(
                f"declared load L={multiple} started {cohort_size} busy process(es) but "
                f"the 1-minute loadavg only reached {at_start:.2f} in {_LOAD_RAMP_S}s, "
                f"short of the {band_floor:.1f} floor this declaration means. The band "
                f"was NOT applied, so nothing measured here is a measurement of it -- "
                f"and reporting it as one is how a harness comes to certify a load it "
                f"never generated"
            )
        if not cohort_size and not quiet:
            pytest.fail(
                f"declared load L=0 is the QUIET control and the host measures LOUD "
                f"(loadavg {at_start:.2f} > 0.25 x {cpus}). The discrimination control "
                f"has to run on a quiet host or it discriminates nothing"
            )
        print(
            f"PDF-78 declared load: L={multiple} cohort={cohort_size} cpu_count={cpus} "
            f"loadavg_start={at_start:.2f} quiet={quiet}"
        )
        yield
        at_end = os.getloadavg()[0]
        observed.append(at_end)
        print(
            f"PDF-78 declared load: L={multiple} loadavg_peak={max(observed):.2f} "
            f"loadavg_end={at_end:.2f}"
        )
    finally:
        for burner in cohort:
            if burner.poll() is None:
                burner.terminate()
        for burner in cohort:
            with contextlib.suppress(subprocess.TimeoutExpired):
                burner.wait(timeout=10)
        survivors = [burner.pid for burner in cohort if burner.poll() is None]
        for burner in cohort:
            if burner.poll() is None:  # pragma: no cover - SIGTERM is enough here
                burner.kill()
                burner.wait(timeout=10)
        # Counted, not hoped for. An orphaned busy-loop cohort would poison every
        # subsequent measurement taken on this box, and the symptom would look
        # like somebody else's flake.
        assert survivors == [], (
            f"the declared-load cohort did not reap: {survivors} still alive after "
            f"SIGTERM. They have been SIGKILLed, but any measurement taken on this "
            f"host in the meantime is contaminated"
        )


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
    #
    # PDF-78 D7.2: the COUNT is recorded on every drive, red or green, because
    # one stray and six strays are different observations and the shipped
    # assertion rendered both as a tuple nobody counted. The ledger row records
    # an occurrence leaving FOUR at once; this spec's own pre-fix control at a
    # declared `L2` left SIX. A single file at the margin reads as a knife-edge
    # race; a whole cohort missing the window together is what a load spike
    # does, and it is what actually happens here.
    #
    # The ASSERTION is untouched -- still an equality against zero, after the
    # same settle discipline, still naming the paths. This is a reporting
    # change; `len(strays) <= 1` would be the forbidden shape.
    print(
        f"PDF-78 stray census: {sig.name} strays={len(strays)} "
        f"paths={tuple(str(path) for path in strays)}"
    )
    assert strays == (), (
        f"{len(strays)} stray .pdftoolkit-* temp file(s) left behind after {sig.name}: {strays}"
    )

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


# PDF-21 hung an `xfail(_START_METHOD == "forkserver", strict=True)` marker here,
# recording that PR_SET_PDEATHSIG does not protect a `forkserver` worker and
# saying, in its own reason string, *"`strict=True` so the day the mechanism is
# repaired this marker fails and has to be removed."* PDF-35 repaired the
# mechanism by pinning the pool to `spawn` (`ops/procpool.py::_START_METHOD`).
#
# **The removal was EARNED, not assumed** (PDF-35 AC5). Post-pin, on genuine
# CPython 3.14.4 -- where the ambient default IS `forkserver`, i.e. the posture
# the marker was written for -- this arm was observed producing
# `[XPASS(strict)] ... 1 failed in 6.01s`. The marker failed because the test
# passed; only then was it deleted. Re-adding it would redden the suite on any
# such host, which is the free red control this deletion leaves behind.
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
