"""``rasterize`` does not survive a signal to its parent (B-055).

Black-box, subprocess-level, and **start-method agnostic by construction**:
this file never touches ``multiprocessing`` internals, patches nothing in
the TEST process (PDF-131: in the CLI SUBPROCESS only, ``_LAUNCHER`` wraps one
function, ``ops/procpool.py::_terminate_pool``, with a call-through observer
that records the pool's own teardown report and alters nothing), and never asks
"was this worker forked or spawned?" --
it only observes three things any start method produces identically: files
landing on disk, the LAUNCHED PROCESS's own exit status, and whether its OS
process GROUP still has any member at all. Commit ``26f4c79`` ("make
AC5/AC26 tests spawn-safe, not fork-only") is exactly the failure mode this
shape avoids by not depending on it in the first place.

Every signal here is sent to the **parent PID only, never its process
group**. A group delivery reaches every render worker directly, and each one
now unwinds itself (PDF-101, proved by
``tests/integration/test_procpool_group_signals.py``), so it would not isolate
the thing these arms measure: the PARENT's own teardown. That is the defect
this spec fixes: a bare, single-process ``kill <pid>`` (what ``timeout``,
``kill``, systemd, ``docker stop`` and CI job cancellation all send) must be
enough on its own.

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
in this project's matrix, ``ubuntu-latest`` and ``macos-15``).

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
import json
import multiprocessing
import os
import signal
import stat
import subprocess
import sys
import time
import types
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_tooling.safety.tempnames import TEMP_PREFIX, find_stray_temps  # noqa: E402
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
#: 2026-10-04 (PDF-101): "paid in full" is now true only of a worker held inside a C
#: call longer than the grace; a worker that unwinds exits at once (`_run_task`).
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


#: PDF-131 D1. The CLI is launched through this program so the test can read the
#: pool's OWN teardown record (``_TeardownReport``, which ``_teardown_and_die``
#: discards) instead of inferring from timing whether the pool SIGKILL-escalated.
#: It wraps ``_terminate_pool`` with a call-through observer: the unforced
#: teardown is byte-for-byte the product's. ``force`` is the one stimulus it
#: adds -- SIGSTOP every worker first, which stands in for "a worker held in a C
#: call past TEARDOWN_GRACE_S" (SIGTERM stays pending, the grace expires, the
#: pool SIGKILLs). Argv: record path, force flag ("1"/"0"), then the CLI args.
_LAUNCHER = """
import importlib.metadata, json, os, signal, sys
from pdf_tooling.ops import procpool

record_path, force, *rest = sys.argv[1:]
real = procpool._terminate_pool


def recording(executor, **kwargs):
    if force == "1":
        for pid in list(getattr(executor, "_processes", {})):
            try:
                os.kill(pid, signal.SIGSTOP)
            except OSError:
                pass
    report = real(executor, **kwargs)
    outcomes = [
        {
            "pid": o.pid,
            "liveness_at_kill": o.liveness_at_kill,
            "sigkill": o.sigkill,
            "liveness_after": o.liveness_after,
            "tail": o.tail,
        }
        for o in report.outcomes
    ]
    fd = os.open(record_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps({"outcomes": outcomes}).encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    return report


procpool._terminate_pool = recording
(entry,) = importlib.metadata.entry_points(group="console_scripts", name="pdftooling")
sys.argv = ["pdftooling", *rest]
sys.exit(entry.load()())
"""

#: Tails that mean "this worker is gone". ``stale-liveness`` is a worker the
#: executor's manager thread had already reaped when the pool re-probed it (the
#: kernel had forgotten the pid), so judging on ``liveness_after`` would red
#: for a worker that no longer exists. ``_group_alive`` still catches a real one.
_REAPED_TAILS = frozenset({"reaped", "stale-liveness"})


@dataclass(frozen=True)
class _Measured:
    proc: Any
    count_at_death: int
    count_after_settle: int
    strays: tuple[Path, ...]
    record: dict[str, Any] | None
    out_dir: Path
    parent_exit_s: float


def _read_record(path: Path) -> dict[str, Any] | None:
    """The launcher's teardown record, or ``None`` when absent or unparsable.
    Absence is never read as "no escalation" -- the oracle reds on it."""
    try:
        loaded = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _send_signal_and_measure(
    tmp_path: Path, sig: signal.Signals, *, force: bool = False
) -> _Measured:
    """Launch a real `rasterize` job, signal the PARENT PID ONLY once it has
    made substantial, demonstrable progress, and return what was measured,
    including the pool's own teardown record (PDF-131 D1).
    """
    source = _make_source(tmp_path / "src")
    out_dir = tmp_path / "out"
    record_path = tmp_path / "teardown-record.json"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _LAUNCHER,
            str(record_path),
            "1" if force else "0",
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

        # THE PID ONLY -- never the group. A group delivery reaches the workers
        # directly, where each one unwinds itself, so it would not isolate the
        # parent's own teardown that this arm measures (see module docstring).
        sent_at = time.monotonic()
        os.kill(proc.pid, sig)

        try:
            proc.wait(timeout=_PARENT_EXIT_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            record = _read_record(record_path)
            proc.kill()
            proc.wait(timeout=5)
            pytest.fail(
                f"parent did not exit within {_PARENT_EXIT_TIMEOUT_S}s of "
                f"{sig.name} -- teardown hung instead of tearing down. "
                f"Teardown record at the time: {record}"
            )
        parent_exit_s = time.monotonic() - sent_at

        count_at_death = len(list(out_dir.iterdir()))
        # Decisive by construction, not by luck -- see module docstring.
        time.sleep(_SETTLE_S)
        count_after_settle = len(list(out_dir.iterdir()))

        strays = find_stray_temps(out_dir)
        record = _read_record(record_path)
    finally:
        if proc.poll() is None:  # pragma: no cover - defensive, only if the above raised
            proc.kill()
            proc.wait(timeout=5)

    return _Measured(
        proc=proc,
        count_at_death=count_at_death,
        count_after_settle=count_after_settle,
        strays=strays,
        record=record,
        out_dir=out_dir,
        parent_exit_s=parent_exit_s,
    )


def _assert_death_without_growth(
    proc: Any, sig: signal.Signals, count_at_death: int, count_after_settle: int
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


def _assert_no_group_member(proc: Any) -> None:
    # T4: zero surviving workers, by the same portable check
    # `adapters/subprocess_util.py` already uses for its own group teardown.
    assert not _group_alive(proc.pid), (
        f"a process is still alive in the launched job's own process group "
        f"(pgid {proc.pid}) after the parent exited -- a worker outlived it"
    )


def _assert_clean_signal_death(
    proc: Any,
    sig: signal.Signals,
    count_at_death: int,
    count_after_settle: int,
    strays: tuple[Path, ...],
) -> None:
    _assert_death_without_growth(proc, sig, count_at_death, count_after_settle)

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

    _assert_no_group_member(proc)


def _assert_record_clean(record: dict[str, Any] | None, sig: signal.Signals) -> tuple[int, int]:
    """The pool's own record must exist and name no unreaped worker. Returns
    ``(escalated, total)`` where *escalated* counts workers the pool SIGKILLed."""
    assert record is not None, (
        f"no teardown record after {sig.name} -- the launcher's observer never saw "
        f"`_terminate_pool` return, so escalation cannot be judged (this is never "
        f"read as 'no escalation')"
    )
    outcomes = record.get("outcomes")
    assert isinstance(outcomes, list) and outcomes, (
        f"the teardown record after {sig.name} lists no workers: {record}"
    )
    unreaped = [o for o in outcomes if o.get("tail") not in _REAPED_TAILS]
    assert not unreaped, (
        f"_terminate_pool reported workers it could not reap after {sig.name}: {unreaped}"
    )
    return sum(1 for o in outcomes if o.get("sigkill") == "sent"), len(outcomes)


def _assert_escalated_residue(strays: tuple[Path, ...], out_dir: Path, escalated: int) -> None:
    """Admit only the documented hard-kill residue (PLAN §12 R-07 / PDF-129): a
    regular toolkit temp, mode 0600, directly in *out_dir*, and no more of them
    than the pool SIGKILLed workers (a sequential worker holds at most one)."""
    assert len(strays) <= escalated, (
        f"{len(strays)} stray temp file(s) but the pool SIGKILLed only {escalated} "
        f"worker(s) -- residue not explained by a hard kill: {strays}"
    )
    for stray in strays:
        mode = os.lstat(stray).st_mode
        assert stat.S_ISREG(mode), f"stray {stray} is not a regular file"
        assert stray.parent == out_dir, f"stray {stray} is not directly beside the destination"
        assert stray.name.startswith(TEMP_PREFIX), f"stray {stray} is not a toolkit temp"
        assert stat.S_IMODE(mode) == 0o600, (
            f"stray {stray} has mode {stat.S_IMODE(mode):o}, not the 0600 of a hard-killed temp"
        )


def _assert_signal_death_observed(
    measured: _Measured, sig: signal.Signals, *, forced: bool = False
) -> None:
    escalated, total = _assert_record_clean(measured.record, sig)
    print(
        f"PDF-131 escalation census: {sig.name} escalated={escalated}/{total} "
        f"strays={len(measured.strays)}"
    )
    if forced:
        assert escalated == total >= 1, (
            f"escalation was not exercised: the pool SIGKILLed {escalated}/{total} workers"
        )
        assert measured.parent_exit_s < _PARENT_EXIT_TIMEOUT_S, (
            f"parent took {measured.parent_exit_s:.2f}s to exit, bound {_PARENT_EXIT_TIMEOUT_S}s"
        )
    if escalated == 0:
        _assert_clean_signal_death(
            measured.proc,
            sig,
            measured.count_at_death,
            measured.count_after_settle,
            measured.strays,
        )
        return
    _assert_death_without_growth(
        measured.proc, sig, measured.count_at_death, measured.count_after_settle
    )
    _assert_escalated_residue(measured.strays, measured.out_dir, escalated)
    _assert_no_group_member(measured.proc)


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


def _final_pages(out_dir: Path) -> int:
    """Finished outputs only: toolkit temps are in-flight residue, not progress."""
    if not out_dir.is_dir():
        return 0
    return sum(1 for entry in out_dir.iterdir() if not entry.name.startswith(TEMP_PREFIX))


def _wait_for_final_pages(out_dir: Path, *, at_least: int, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    count = 0
    while time.monotonic() < deadline:
        count = _final_pages(out_dir)
        if count >= at_least:
            return count
        time.sleep(0.05)
    pytest.fail(
        f"only {count}/{at_least} final pages appeared under {out_dir} within {timeout}s "
        f"-- render started too slowly (or not at all) for this test to be decisive"
    )


def _group_states(pgid: int) -> dict[int, str]:
    """``{pid: state}`` for every non-zombie member of *pgid*, from /proc."""
    states: dict[int, str] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat_text = (entry / "stat").read_text()
            fields = stat_text[stat_text.rindex(")") + 2 :].split()
            state, pgrp = fields[0], int(fields[2])
        except (OSError, ValueError, IndexError):  # pragma: no cover - raced exit
            continue
        if pgrp == pgid and state != "Z":
            states[int(entry.name)] = state
    return states


def _wait_until_group_stopped(pgid: int, *, timeout: float) -> None:
    """Bounded 0.01 s poll until every non-zombie member is in a stopped state."""
    deadline = time.monotonic() + timeout
    states = _group_states(pgid)
    while time.monotonic() < deadline:
        states = _group_states(pgid)
        if states and all(state in ("T", "t") for state in states.values()):
            return
        time.sleep(0.01)
    pytest.fail(f"the process group {pgid} did not stop within {timeout}s: {states}")


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
    measured = _send_signal_and_measure(tmp_path, signal.SIGTERM)
    _assert_signal_death_observed(measured, signal.SIGTERM)


def test_sigint_to_parent_only_stops_new_output_and_leaves_no_survivors(
    tmp_path: Path,
) -> None:
    """T6 -- SIGINT gets the SAME measurement discipline as T3's SIGTERM arm.

    Measured directly against the unfixed code (module docstring / spec
    report): a bare ``kill -INT <parent pid only>`` does NOT stop the job --
    it runs to completion, identically to the SIGTERM defect. An interactive
    Ctrl-C signals the whole foreground process group, so each worker also
    receives it directly and unwinds itself (PDF-101), independent of
    anything this process does. This arm proves SIGINT is clean under the
    harder, accident-free discipline too, because
    `guarded_process_pool` now handles it through the identical routine.
    """
    measured = _send_signal_and_measure(tmp_path, signal.SIGINT)
    _assert_signal_death_observed(measured, signal.SIGINT)


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
    arms: the PARENT PID ALONE (X-119 -- a group delivery reaches the workers
    directly and would not isolate the parent's own teardown), the positive
    control (parent
    alive, pool members present, ``count_at_death < _PAGE_COUNT``), zero new
    output after death, and zero survivors -- here ENUMERATED by pid as well as
    probed with ``killpg(pgid, 0)``.
    """
    measured = _send_signal_and_measure(tmp_path, signal.SIGHUP)
    _assert_signal_death_observed(measured, signal.SIGHUP)
    _assert_enumerated_zero_survivors(measured.proc, signal.SIGHUP)


def test_sigterm_with_all_workers_held_past_the_grace_is_sigkilled_with_only_documented_residue(
    tmp_path: Path,
) -> None:
    """PDF-131 D2c -- the escalated path, driven on every POSIX CI leg.

    The launcher SIGSTOPs every worker before the pool's real teardown. That is a
    STAND-IN for "a worker held in a C call past ``TEARDOWN_GRACE_S``": SIGTERM
    stays pending, the grace expires and the pool SIGKILLs. The arm asserts the
    pool really escalated (a positive control), that it named no unreaped
    worker, that only the documented hard-kill residue remains, that the group
    is empty and that no output grows. Costs about one grace window of wall time.
    """
    measured = _send_signal_and_measure(tmp_path, signal.SIGTERM, force=True)
    _assert_signal_death_observed(measured, signal.SIGTERM, forced=True)


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
        "macOS this arm is a VISIBLE SKIP rather than a silent absence -- the "
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
    pgid = proc.pid
    try:
        _wait_for_final_pages(out_dir, at_least=_SIGNAL_AT_COUNT, timeout=_PROGRESS_TIMEOUT_S)

        # PDF-131 D3: judge the precondition on a group that cannot move.
        os.killpg(pgid, signal.SIGSTOP)
        _wait_until_group_stopped(pgid, timeout=_SURVIVOR_TIMEOUT_S)
        final_at_freeze = _final_pages(out_dir)
        members_at_freeze = _live_group_members(pgid)

        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=_PARENT_EXIT_TIMEOUT_S)
        entries_at_death = len(list(out_dir.iterdir()))
        # The thaw is mandatory: without it a broken PDEATHSIG would leave stopped,
        # harmless-looking workers and the no-growth check below could never fail.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGCONT)

        assert proc.returncode == -signal.SIGKILL, proc.returncode
        # The positive control, part of the assertion and not a preamble: the job
        # was genuinely mid-flight, so "no growth after death" is not vacuously
        # true of a run that had already finished. FINAL pages, not temps.
        assert final_at_freeze < _PAGE_COUNT, (
            f"{final_at_freeze}/{_PAGE_COUNT} final pages existed at the freeze -- the job "
            f"already finished before SIGKILL arrived; tune _DPI/_PAGE_COUNT"
        )
        assert [m for m in members_at_freeze if m[0] != proc.pid], (
            f"no worker was alive in the frozen group besides the parent: {members_at_freeze}"
        )
        _assert_enumerated_zero_survivors(proc, signal.SIGKILL)
        # Only NOW is "no new output" decisive: it is asserted after the survivors
        # are gone, so it cannot pass merely because the settle window was short.
        time.sleep(_SETTLE_S)
        assert len(list(out_dir.iterdir())) == entries_at_death, (
            "new output appeared after the parent was SIGKILLed -- a worker outlived it"
        )
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGCONT)
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGKILL)
        proc.wait(timeout=5)


# --------------------------------------------------------------------------- #
# PDF-131 D4 -- oracle tests over planted files and synthetic records. No
# process is spawned by any of these.
# --------------------------------------------------------------------------- #


def _reaped_pid() -> int:
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    return done.pid


def _plant_temp(directory: Path, suffix: str, *, mode: int = 0o600) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    planted = directory / (TEMP_PREFIX + suffix)
    planted.write_bytes(b"x")
    planted.chmod(mode)
    return planted


def _record(*, sigkill: str, tail: str = "reaped", count: int = 8) -> dict[str, Any]:
    return {
        "outcomes": [
            {
                "pid": 1000 + index,
                "liveness_at_kill": "alive",
                "sigkill": sigkill,
                "liveness_after": "dead",
                "tail": tail,
            }
            for index in range(count)
        ]
    }


def test_a_stray_without_escalation_reds_on_the_strict_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `capsys` keeps this planted oracle's census line out of a `-s` run, so the
    # census count in the real arms' output stays exactly one per real arm.
    out_dir = tmp_path / "out"
    stray = _plant_temp(out_dir, "aaaa")
    measured = _Measured(
        proc=types.SimpleNamespace(returncode=-signal.SIGTERM, pid=_reaped_pid()),
        count_at_death=3,
        count_after_settle=3,
        strays=(stray,),
        record=_record(sigkill="not-needed"),
        out_dir=out_dir,
        parent_exit_s=0.1,
    )

    with pytest.raises(AssertionError, match=r"1 stray.*after SIGTERM"):
        _assert_signal_death_observed(measured, signal.SIGTERM)
    assert "escalated=0/8" in capsys.readouterr().out


def test_escalated_residue_oracle_accepts_documented_crash_residue(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    strays = (_plant_temp(out_dir, "aaaa"), _plant_temp(out_dir, "bbbb"))

    _assert_escalated_residue(strays, out_dir, 2)


@pytest.mark.parametrize("case", ["mode-0644", "no-prefix", "nested-dir"])
def test_escalated_residue_oracle_rejects_what_the_contract_does_not_describe(
    tmp_path: Path, case: str
) -> None:
    out_dir = tmp_path / "out"
    if case == "mode-0644":
        stray = _plant_temp(out_dir, "aaaa", mode=0o644)
    elif case == "no-prefix":
        out_dir.mkdir()
        stray = out_dir / "page-0001.png.part"
        stray.write_bytes(b"x")
        stray.chmod(0o600)
    else:
        stray = _plant_temp(out_dir / "nested", "aaaa")

    with pytest.raises(AssertionError):
        _assert_escalated_residue((stray,), out_dir, 8)


def test_escalated_residue_oracle_rejects_a_symlink_stray(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    target = tmp_path / "target"
    target.write_bytes(b"x")
    target.chmod(0o600)
    link = out_dir / (TEMP_PREFIX + "link")
    link.symlink_to(target)

    with pytest.raises(AssertionError):
        _assert_escalated_residue((link,), out_dir, 8)


def test_escalated_residue_oracle_rejects_more_strays_than_sigkills(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    strays = (_plant_temp(out_dir, "aaaa"), _plant_temp(out_dir, "bbbb"))

    with pytest.raises(AssertionError):
        _assert_escalated_residue(strays, out_dir, 1)


def test_record_oracle_fails_on_a_missing_record_and_on_an_unreaped_worker() -> None:
    with pytest.raises(AssertionError, match="no teardown record after SIGTERM"):
        _assert_record_clean(None, signal.SIGTERM)

    with pytest.raises(AssertionError, match="could not reap after SIGTERM"):
        _assert_record_clean(
            _record(sigkill="sent", tail="outlived-sigkill", count=1), signal.SIGTERM
        )

    # `stale-liveness` is a worker the executor had already reaped: not a survivor.
    assert _assert_record_clean(
        _record(sigkill="sent", tail="stale-liveness", count=1), signal.SIGTERM
    ) == (1, 1)


def test_final_pages_exclude_toolkit_temps(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    for number in range(28):
        (out_dir / f"page-{number:04d}.png").write_bytes(b"x")
    for index in range(4):
        _plant_temp(out_dir, f"t{index}")

    assert _final_pages(out_dir) == 28
