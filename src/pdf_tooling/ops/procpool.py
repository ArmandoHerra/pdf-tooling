"""A ``ProcessPoolExecutor`` that does not survive a signal to its parent (B-055).

``rasterize`` (and, per X-104, every future page-rendering verb — ``ocr``
inherits the identical constraint verbatim) MUST run its render workers in a
``ProcessPoolExecutor``, never a ``ThreadPoolExecutor``: real concurrent
pdfium rendering corrupts the process heap even with fully isolated
per-worker documents (see ``ops/raster.py``'s module docstring for the
reproduced ``free(): invalid pointer`` / ``double free`` evidence). That
constraint is exactly what makes the defect this module fixes non-obvious.

THE DEFECT, AND WHY A NAIVE FIX IS A NO-OP
-------------------------------------------
``rasterize_document`` submits one chunk per worker — ``max_workers ==
len(chunks)`` — so every worker is in-flight from the first instant; nothing
is ever queued-but-unstarted. Plain ``ProcessPoolExecutor.__exit__`` calls
``shutdown(wait=True)``, which BLOCKS until every already-running worker
finishes on its own. ``shutdown(wait=False, cancel_futures=True)`` does not
help either: ``cancel_futures`` cancels only *pending* (not yet started) work
items, and there are none. Neither spelling of "shut the pool down" actually
signals a running worker — a handler that only calls ``shutdown()`` in any
combination is not a fix, which is exactly why this module exists: the
teardown below actively signals real worker PIDs.

**Verified against the installed stdlib, not assumed.** ``ProcessPoolExecutor``
spawns each worker inside ``_adjust_process_count()`` -> ``_spawn_process()``,
called synchronously from ``submit()`` on the CALLING thread (this product's
own main thread) — confirmed by reading
``concurrent.futures.process.ProcessPoolExecutor.submit`` in the interpreter
this product runs under. That fact underwrites two separate design choices
below: PR_SET_PDEATHSIG is safe to arm at worker start (see
:func:`_worker_initializer`), and ``executor._processes`` — a private
``{pid: Process}`` mapping with no public equivalent — is genuinely the only
way to reach the worker PIDs at all, which is what :func:`_terminate_pool`
uses.

**A second stdlib fact that shapes the worker-side handler.**
``concurrent.futures.process._process_worker`` wraps every submitted call in
``except BaseException`` and loops back to wait for the next work item — it
does NOT exit the process. Raising an exception from inside a render call
(however it is raised, ``SystemExit`` included) can unwind an in-flight
:class:`~pdf_tooling.safety.atomic.AtomicWriter` cleanly, but the stdlib then
leaves the worker alive. PDF-101 therefore submits every task through
:func:`_run_task` (see :class:`_GuardedExecutor`), which ends the worker with
``os._exit`` the moment its unwind has completed. The raised exception from
:func:`_worker_initializer`'s handler buys the write chokepoint its chance to
discard the temp file, and :func:`_run_task` makes the exit prompt instead of
leaving it to :func:`_terminate_pool`'s SIGKILL at the end of the grace window
(design consideration (e) — trading orphaned processes for orphaned
``.pdftoolkit-*`` temp files would not be a fix either).

THE START METHOD IS A PRODUCT DECISION, NOT AN INTERPRETER DEFAULT
-------------------------------------------------------------------
**PDF-35, ruling X-401, decided 2026-09-04: ``spawn``, pinned; ``forkserver``
excluded.** The pool below is built with an explicit ``mp_context=``; see
:data:`_START_METHOD` for the decision, the measured evidence behind it, and
why ``fork`` was not chosen either.

**The stdlib claim above is re-verified UNDER ``spawn``, not carried over.**
``_adjust_process_count()`` -> ``_spawn_process()`` is a property of
``concurrent.futures.process``, not of the multiprocessing context, so it is
still called synchronously from ``submit()`` on this product's own main
thread under ``spawn`` -- PR_SET_PDEATHSIG's "the thread that created it"
reasoning therefore still holds, and ``executor._processes`` is still the
only route to worker PIDs. Confirmed by reading the installed stdlib, not
assumed.

THE GUARANTEE THIS MODULE ACTUALLY MAKES
-----------------------------------------
**No NEW output after the parent dies.** "No partial output" is not
provable — a worker that was already mid-``os.replace`` when a real SIGKILL
(uncatchable, see below) arrived is not something any code in this process
can prevent, and this module makes no claim about it.

**Residue avoidance is best-effort, not a guarantee — stated plainly rather
than implied.** :data:`TEARDOWN_GRACE_S` exists so a worker's own SIGTERM
handler gets a chance to run and unwind through an open ``AtomicWriter``,
but that chance depends on CPython reaching a bytecode boundary to deliver
it, and a signal cannot interrupt a call already inside pdfium's or
Pillow's C code (the ``signal`` module's own documented limitation). A
worker parked deep in a slow C call for longer than the grace window is
SIGKILLed with no chance to discard its own temp file, exactly as an
un-mitigated hard kill always could. This is the SAME class of accepted
outcome ``safety/tempnames.py``'s own docstring already names for a plain
SIGKILL between temp-create and ``os.replace`` (PLAN §12 R-07: reported by
``doctor --strict``, never swept) — this module lowers how often it
happens, it does not claim to make it impossible.

Every signal is torn down through the ONE routine in
:func:`guarded_process_pool` — SIGTERM, SIGINT and SIGHUP alike. SIGINT gets
the same explicit treatment as the other two rather than being left to
Python's default ``KeyboardInterrupt`` unwind: measured directly against
this exact command (``rasterize --threads 8`` over a 40-page document,
``kill -INT <parent pid only>``, unfixed code), a bare single-process SIGINT
does NOT stop the job — the run completes in full, identically to the
SIGTERM defect this spec was filed against. An interactive terminal Ctrl-C
signals the WHOLE foreground process group, so a group delivery reaches every
worker directly as well as the parent, and each worker unwinds through the
same worker-local handler (PDF-101); ``kill -INT <pid>`` (a supervisor's own
single-process signal, and the discipline the parent-only regression arms
below use) reaches the parent alone. Folding SIGINT into this same teardown
makes both clean by construction, which answers "did you regress SIGINT?"
with a mechanism instead of a hope.

**SIGKILL to the parent cannot be handled. This is stated, not implied.** A
``SIGKILL``ed process gets no code to run at all — no signal handler,
no ``finally``, nothing. The only thing the CHILD side can still do is
PR_SET_PDEATHSIG (Linux only; ``prctl`` is a Linux syscall, so macOS gets no
coverage here — stated rather than silently absent, matching CI's own
matrix, which runs ``ubuntu-latest`` and ``macos-15`` and no Windows job).

**Exit code on signal.** The parent dies BY the signal (``signal.signal(sig,
signal.SIG_DFL)`` then ``os.kill(os.getpid(), sig)``) rather than
``sys.exit(128 + signo)`` — ``WIFSIGNALED`` true, ``$?`` = 128 + signo (143
SIGTERM / 130 SIGINT / 129 SIGHUP), which is what ``timeout``, systemd and
``docker stop`` actually key off. These numbers are a shell convention, not
this product's per-verb exit-code contract: they are deliberately never
added to ``cli/exit_codes.py::ALL_EXIT_CODES``, which tests iterate as the
closed set of codes a VERB can itself decide to exit with.
"""

from __future__ import annotations

import contextlib
import multiprocessing
import os
import signal
import sys
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ProcessPoolExecutor
from contextlib import contextmanager
from typing import Final, ParamSpec, TypeVar

__all__ = ["guarded_process_pool"]

#: The pool's start method is a PRODUCT DECISION (PDF-35, ruling X-401),
#: recorded here rather than inherited from whatever the interpreter happens
#: to default to. Decided 2026-09-04.
#:
#: **Why this constant exists at all.** Before PDF-35 the pool was built with
#: no ``mp_context=``, so the start method was an inherited premise -- `fork`
#: on CPython 3.11-3.13, and `forkserver` from 3.14, which
#: ``pyproject.toml``'s ``requires-python = ">=3.11"`` and the CI matrix both
#: make a SUPPORTED interpreter. A premise nobody chose cannot be defended
#: and changes underneath the product when the interpreter moves; it did.
#:
#: **Why `forkserver` is excluded rather than merely not selected.** It is
#: the defect. Under `forkserver` a worker is forked from the forkserver
#: HELPER, so the worker's own parent is a process that outlives the CLI --
#: and ``PR_SET_PDEATHSIG`` (see :func:`_worker_initializer`) asks the kernel
#: to kill *this process when its parent dies*. Armed against the helper, it
#: never fires for a SIGKILLed CLI. Measured on this product, pre-pin, at the
#: mechanism level with the start method as the only variable: `fork` 0
#: survivors / 0 post-death output growth, `spawn` 0 / 0, **`forkserver` 8
#: survivors and output 21 -> 240 files after the parent was reaped** -- i.e.
#: the job ran to completion with nothing left to have asked for it.
#:
#: **Why `spawn` and not `fork`.** One code path on both supported platforms
#: (macOS has defaulted to `spawn` since 3.8, so every `macos-14` CI run has
#: been exercising this path end to end since the verb shipped -- it is not a
#: new path). No AF_UNIX listener exists at all, which moots `deabf608c2`
#: mechanically rather than mitigating it: `forkserver` binds
#: ``<TMPDIR>/pymp-XXXXXXXX/listener-XXXXXXXX``, 32 bytes past ``$TMPDIR``
#: against a 107-character ``sun_path`` ceiling, and `spawn` binds nothing.
#: And no fork-inheritance of an already-``FPDF_InitLibrary()``'d pdfium
#: global. `fork` was NOT chosen: pinning it would be a commitment against
#: CPython's direction of travel, re-examined every release.
#:
#: **Verified against the installed stdlib, not assumed -- re-checked under
#: `spawn`.** The module docstring's load-bearing claim is that
#: ``_adjust_process_count()`` -> ``_spawn_process()`` is called synchronously
#: from ``submit()`` on the CALLING thread, which is what makes
#: ``PR_SET_PDEATHSIG``'s "the thread that created it" reasoning hold. That
#: is a property of ``concurrent.futures.process``, not of the context, so it
#: is unchanged by the pin -- confirmed by reading the interpreter this
#: product runs under. Separately: PDEATHSIG is cleared across ``execve``,
#: and `spawn` does exec -- but the guard is armed INSIDE
#: :func:`_worker_initializer`, i.e. AFTER the exec, so the question does not
#: arise. Both facts are stated because both are the kind a reader will
#: otherwise re-derive at the next incident.
#:
#: PRIVATE. ``__all__`` does not grow: this is a defect fix, not a new
#: public surface.
_START_METHOD: Final[str] = "spawn"


def _mp_context() -> multiprocessing.context.BaseContext:
    """The explicit ``multiprocessing`` context the render pool is built with.

    An explicit ``mp_context=`` DEFEATS the ambient default, including one an
    embedder set with ``multiprocessing.set_start_method()`` -- which is
    precisely the property PDF-35's end-to-end arm measures, and precisely
    why ``set_start_method()`` was rejected as the mechanism here: it is a
    process-global mutation that would change the default for every library
    the CLI imports rather than for this product's own pool.
    """
    return multiprocessing.get_context(_START_METHOD)


#: How long a SIGTERM'd worker is given to unwind through its own
#: `AtomicWriter.__exit__` (discarding an in-flight temp file) before it is
#: SIGKILLed outright. Independently declared rather than imported from
#: `adapters/subprocess_util.py::TERM_GRACE_S` -- `ops/` does not import
#: `adapters/` anywhere today (verbs reach an engine only through `ports/`),
#: and coupling two unrelated layers for one shared float is not worth
#: introducing that first backward edge. Same value class, same reasoning.
#:
#: Sized for the SLOWEST case this product's own CI matrix exercises, not the
#: fastest: `multiprocessing`'s default start method is `fork` on Linux but
#: `spawn` on macOS (and everywhere from Python 3.14 on) -- a `spawn`ed
#: worker re-imports pypdfium2, Pillow and this whole package from scratch,
#: with no fork-inherited already-loaded state, so its very first page can
#: cost seconds of cold-start C-extension import and JIT-free interpreter
#: warm-up before a single byte is rendered. `guarded_process_pool`'s
#: SIGTERM handler can only take effect at a Python bytecode boundary
#: (CPython cannot interrupt a running C call -- the `signal` module's own
#: documented limitation), so a worker parked inside that cold first-page
#: encode needs a genuinely generous window to reach one, or it is SIGKILLed
#: with no chance to discard its own temp file. Because the worker's own
#: `call_queue.get()` loop never exits on its own even after a clean
#: cooperative unwind (see the module docstring's stdlib-verified fact),
#: this window is effectively always paid in full on a signalled teardown --
#: it is not merely a ceiling; treat raising it as directly, linearly
#: costing wall-clock, and consider it money well spent against residue
#: rather than a knob to shrink casually.
#:
#: 2026-10-04 (PDF-101): CORRECTION to the "paid in full" sentence above. A worker
#: now ends itself once its unwind has completed (`_run_task`), so this window is a
#: CEILING again and not a bill. It is paid in full only by a worker held inside a
#: C call for longer than the grace, which is the quantity the PDF-78 block below
#: measures and still bounds.
#:
#: ------------------------- PDF-78: THE MEASUREMENT -------------------------
#: EVERYTHING ABOVE THIS LINE IS WHY 6.0 WAS PLAUSIBLE. It was never measured
#: against the variable that actually moves this quantity, and the constant's own
#: history is the argument for the block below: `[B-055]` tripled it BY HAND
#: (2s -> 6s, 2026-08-30) to make one red CI leg green; that bought FOUR DAYS,
#: and the same stray-temp assertion has reddened five times since, on both
#: platforms. A second bump would be the same move against the same defect with
#: the same evidence base. So this value is now the OUTPUT OF A RULE applied to a
#: measurement taken under a DECLARED, GENERATED, REPRODUCIBLE load. Nothing
#: about the number was chosen; only the measurement was.
#:
#: WHAT WAS MEASURED -- `T_unwind`, per worker: the interval from the SIGTERM
#: `_terminate_pool` sends to the instant that worker has completed
#: `AtomicWriter.__exit__`'s discard of whatever temp file it held open. NOT the
#: parent's teardown wall-clock (that is `grace_s` by construction) and NOT the
#: time to worker exit (which never happens on its own). Sampled on an
#: INSTRUMENTED SHADOW COPY driven through `PYTHONPATH`, never in this tree, with
#: a deliberately oversized 40 s window so that NOTHING was censored -- a sample
#: truncated at the very window being derived would derive itself.
#:
#: STATISTIC:    pooled per-worker `max`, x 1.25. THE STATISTIC IS PART OF THE
#:               NUMBER, and it is `max` rather than the house's p95 because of
#:               the NUMBER OF DRAWS this window must survive: `--threads 8` x 3
#:               signalled arms = 24 independent draws per suite execution, so a
#:               per-worker coverage p is green p**24 of the time -- 0.95**24 =
#:               0.29, 0.99**24 = 0.79. A percentile borrowed from a
#:               single-measurement budget (`STARTUP_BUDGET_MS`) would be honest,
#:               well-recorded, and red seven runs in ten. THE SHIPPED 6.0 IS
#:               THAT ERROR ALREADY MADE: it covers 77.5 % of the 160 samples
#:               below, and 0.775**24 = 0.0022.
#: DATE:         2026-09-17
#: COMMIT:       48b093d0685327ad649bd693ceab3f7b2c8c7638 -- measured on the
#:               UNMODIFIED tree at that commit; the instrumentation existed only
#:               in the shadow copy and is in no file in this repository.
#: HOST:         Linux-7.0.0-31-generic x86_64, 8 cpus
#: INTERPRETER:  CPython 3.12.13, resolved through this repository's own `.venv`,
#:               never the system `python3`
#: ENGINES:      tesseract AND soffice both present on PATH -- recorded because
#:               the token set demands it, not because either moved the number:
#:               `rasterize` reaches neither.
#: LOAD:         L5 = 5 x cpu_count = 40 stdlib busy-loop SUBPROCESSES, started
#:               before the trial, ramped, held through it, reaped after and the
#:               reap COUNTED. Declared as a MULTIPLE of `cpu_count`, never as an
#:               absolute loadavg, so the declaration transfers to a host with a
#:               different core count. loadavg 34.38 start / 75.15 peak / 47.78
#:               end; per trial 42.67-67.12. **quiet: false, ASSERTED** --
#:               the harness REFUSES to record a load band on a host it measures
#:               as quiet by `perf/README.md`'s own predicate. That is `perf/`'s
#:               rule with its sign flipped, which is why this derivation lives
#:               here and not there.
#: TRIALS:       20 signalled teardowns x 8 workers = 160 pooled per-worker
#:               samples. 1 sample was 0 -- that worker held no open writer
#:               when the signal landed -- and are RETAINED, not dropped:
#:               dropping the zeros measures the conditional distribution and
#:               over-derives the window. 0 censored.
#: DISTRIBUTION: min 0.000 / median 4.929 / p95 11.414 / max 12.407 s,
#:               spread 12.407 s
#:
#: 12.407 x 1.25 = 15.509 -> rounded up to the next 0.5 s = 16.0
#:
#: THE CONTROL, because a measurement with no control is a number and not
#: evidence. The identical protocol at two other declared loads:
#:   L0 (quiet, loadavg 0.13-1.21): min 0.338 / median 0.564 / p95 0.637 /
#:      max 0.705 s over 160 samples, 0 strays
#:   L2 (2 x cpu_count, loadavg 15.64-19.05): min 0.096 / median 2.185 /
#:      p95 2.942 / max 3.275 s over 160 samples, 0 strays
#: The order of magnitude between L0 and L5 is what says this instrument reads
#: CONTENTION rather than a constant.
#:
#: WHAT IT COSTS, STATED RATHER THAN DISCOVERED LATER. 36 of the 160 L5
#: samples exceed the old 6.0; none exceeds 16.0. Restricted to the 34-44 loadavg
#: band the ledger itself recorded (56 samples) the max is 6.207 s and this
#: same rule would have produced 8.0 -- the generated cohort ran HOTTER than
#: that band, because the eight render workers sit on top of it, so this number
#: is CONSERVATIVE and the cheaper one is recorded beside it rather than quietly
#: preferred. And the window is paid IN FULL on every signalled teardown --
#: MEASURED, not inferred: 8 of 8 workers were still alive when the loop reached
#: its deadline in all 60 teardowns across all three loads -- so this is
#: 3 x (16.0 - 6.0) = 30.0 s of added worker-serial teardown per suite run.
#:
#: AND THE CEILING IT MUST FIT INSIDE. The measured p95 parent overhead at L5 is
#: 0.327 s, so 16.0 + 0.327 = 16.327 s against the 25.0 s bound in
#: `tests/integration/test_rasterize_signals.py::_PARENT_EXIT_TIMEOUT_S`, which
#: bounds the parent's whole exit. That bound may NOT be widened to make room for
#: a grace that does not fit -- widening it would be this same forbidden move one
#: file over -- and
#: `tests/unit/test_procpool.py::test_the_grace_fits_inside_the_parent_exit_bound`
#: reddens by name if a later grace stops fitting.
TEARDOWN_GRACE_S: Final[float] = 16.0

#: Poll interval while waiting out `TEARDOWN_GRACE_S`.
_POLL_S: Final[float] = 0.05

#: The budget for the WHOLE reap phase of `_terminate_pool` -- one deadline shared
#: by every `join`, so it does not grow with the worker count.
#:
#: BASIS: ARITHMETIC, NOT MEASURED. The room the reap phase has is
#: `_PARENT_EXIT_TIMEOUT_S` - `TEARDOWN_GRACE_S` - `_PARENT_OVERHEAD_P95_S`, the
#: first and last read from the signalled-arm tests (see
#: `tests/integration/test_rasterize_signals.py::_PARENT_EXIT_TIMEOUT_S`):
#: 25.0 - 16.0 - 0.327 = 8.673 s. 8.0 is the largest whole second inside it, which leaves 0.673 s of
#: margin (about twice the measured p95 overhead). That figure is a WORST-CASE
#: bound: it counts the grace as spent in full, which a worker that unwinds early
#: does not cost.
#:
#: DIRECTION. This replaces a worst case of N x 16.0 s (at least 16.0 s for any
#: N >= 1), so it may only make that smaller. Raising it toward the room is the
#: widening trap under a new name: `TEARDOWN_GRACE_S`, `_PARENT_EXIT_TIMEOUT_S`
#: and `_PARENT_OVERHEAD_P95_S` are not headroom.
#:
#: STOPS HOLDING IF (a) on a supported host a SIGKILLed worker can take longer
#: than 8.0 s to become reapable -- the budget then reports a survivor that a
#: longer join would have collected, and a report with `join-timed-out`,
#: `kernel=zombie` and `join_elapsed_s` close to `join_timeout_s` is how that
#: shows up; or (b) any of the three operands above moves.
#:
#: COST, DISCLOSED. A caller using the default now joins each process for at most
#: 8.0 s, down from 16.0 s: a slow reap has a smaller window in which to succeed.
#: That is the permitted direction. The arithmetic is guarded by the arm named
#: `test_the_grace_and_the_reap_budget_fit_inside_the_parent_exit_bound`, which
#: sits beside the grace's own guard in the unit tests for this module.
_REAP_BUDGET_S: Final[float] = 8.0

#: Every signal torn down through the ONE routine below (design (a)). SIGKILL
#: to the PARENT cannot appear here -- it is uncatchable by definition; see
#: `_worker_initializer` for the one thing the CHILD side can still do about
#: it. `getattr` rather than a bare attribute reference: `SIGHUP` does not
#: exist on Windows, and this module must still be IMPORTABLE there even
#: though the product is POSIX/macOS-only (`pyproject.toml`'s own
#: classifiers) -- an unsupported platform should get "no protection",
#: never an ImportError before a single line of product code runs.
_GUARDED_SIGNAL_NAMES: Final[tuple[str, ...]] = ("SIGTERM", "SIGINT", "SIGHUP")


class _WorkerUnwind(SystemExit):
    """Raised inside a render worker's own signal handler (never elsewhere).

    Not an `Exception`: `_render_one`'s own `except PdfToolingError` (a plain
    `Exception` subclass) must never catch it and turn a teardown into an
    ordinary failed-page result. It is a `SystemExit` rather than a bare
    `BaseException` (PDF-101) for the idle worker: a signal that lands while the
    worker waits in `call_queue.get()` raises OUTSIDE any task, and
    `multiprocessing`'s bootstrap treats a `SystemExit` as a quiet exit where any
    other `BaseException` gets a printed traceback.

    `signum` is the signal that started the unwind. `SystemExit.code` carries
    ``128 + signum`` so an idle worker's exit status matches the one
    :func:`_run_task` gives a worker that was mid-task. Product code reads
    `signum`, never `code` (whose type is ``str | int | None``).

    Inside a task it is caught by :func:`_run_task`, which ends the worker once
    the unwind has finished: its only job is to propagate through whatever
    `with AtomicWriter(...)` block the worker happens to be inside when the signal
    arrives, so that block's `__exit__` discards its temp file.
    """

    def __init__(self, signum: int) -> None:
        super().__init__(128 + signum)
        self.signum = signum


def _absorb_signal(signum: int, _frame: object) -> None:
    """Swallow a signal that arrives AFTER a worker's unwind has begun.

    A Python callable and never `SIG_IGN`: CPython raises ``OSError: Signal N
    ignored due to race condition`` at the next bytecode boundary when a signal
    that was already tripped at the C level has had its disposition changed to
    `SIG_IGN` or `SIG_DFL`, and in an unwinding worker that boundary is inside
    the cleanup code. A callable is simply invoked and returns.
    """
    return None


def _raise_worker_unwind(signum: int, _frame: object) -> None:
    """The one worker-local handler for every guarded signal (PDF-101).

    One-shot: the FIRST signal re-points all three names to :func:`_absorb_signal`
    and then raises. A group Ctrl-C delivers SIGINT and the parent's own
    `_terminate_pool` delivers SIGTERM milliseconds later. Those are different
    signal numbers, so they do not coalesce, and a second raise landing inside
    `AtomicWriter._discard` would lose the unlink (measured: residue in 10 of 10
    trials).
    """
    for name in _GUARDED_SIGNAL_NAMES:
        sig = getattr(signal, name, None)
        if sig is not None:
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sig, _absorb_signal)
    raise _WorkerUnwind(signum)


P = ParamSpec("P")
T = TypeVar("T")


def _run_task(fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
    """Run one task in a worker and end the worker once its unwind is complete.

    Without this the unwound worker is caught by `concurrent.futures.process.
    _process_worker`'s own `except BaseException`, which loops back to
    `call_queue.get()` and leaves the worker alive until the parent's SIGKILL at
    the end of `TEARDOWN_GRACE_S` (measured 16.1-16.3 s on a 0.1 s Ctrl-C).
    """
    try:
        return fn(*args, **kwargs)
    except _WorkerUnwind as unwind:
        # Every `with` block inside `fn` -- the AtomicWriter included -- has exited
        # by now, and `_raise_worker_unwind` has re-pointed all three signals to the
        # absorber, so nothing can interrupt this exit.
        os._exit(128 + unwind.signum)


class _GuardedExecutor(ProcessPoolExecutor):
    """A `ProcessPoolExecutor` whose tasks run under :func:`_run_task`."""

    def submit(self, fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> Future[T]:
        return super().submit(_run_task, fn, *args, **kwargs)


def _worker_initializer() -> None:
    """The pool's ``initializer=`` — runs first, inside every worker, before
    it processes a single work item (design considerations (b), (c), (h)).

    An initializer that raises breaks the WHOLE pool: `_process_worker`
    (stdlib) logs the exception and returns without doing any work at all,
    and the parent later observes a `BrokenProcessPool`. Every step here is
    therefore independently wrapped and degrades rather than propagates.
    """
    # (c) Fork inheritance -- the class of bug PDF-09 already paid for once
    # (commit 26f4c79, "make AC5/AC26 tests spawn-safe, not fork-only").
    # Under the `fork` start method a worker is a byte-for-byte memory copy
    # of the parent at fork time, including whichever callable the parent
    # had installed for SIGTERM/SIGINT/SIGHUP at that moment -- this
    # product's own `_teardown_and_die` (below), closed over the PARENT's
    # `ProcessPoolExecutor`. Left alone, a worker that itself received one
    # of these signals would run teardown logic built for a different
    # process, against a stale copy of the parent's own bookkeeping.
    # `forkserver`/`spawn` re-import this module fresh and never inherit a
    # Python-level handler at all, so resetting unconditionally (rather than
    # branching on start method) is correct under all three and a genuine
    # no-op under the two that do not need it.
    #
    # EVERY guarded signal gets the ONE worker-local handler (PDF-101), not a bare
    # reset to SIG_DFL. A terminal Ctrl-C signals the whole foreground process
    # group, so a worker receives SIGINT (and a hang-up, SIGHUP) directly, and
    # SIG_DFL killed it with no chance for an open `AtomicWriter` to unwind --
    # which is exactly what left `.pdftoolkit-*` residue (design (e)).
    # `Process.terminate()` sends SIGTERM and the parent's teardown follows a group
    # signal milliseconds later, so all three names unwind through the same handler.
    for name in _GUARDED_SIGNAL_NAMES:
        sig = getattr(signal, name, None)
        if sig is None:  # pragma: no cover - POSIX-only names, not on Windows
            continue
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, _raise_worker_unwind)

    # (b) SIGKILL to the PARENT is uncatchable -- nothing in this process
    # can react to it. PR_SET_PDEATHSIG is the one thing the CHILD side can
    # still do: ask the kernel to SIGKILL *this worker* the moment the
    # thread that created it terminates. That thread is, in-process, the
    # parent's own main thread -- `ProcessPoolExecutor.submit()` spawns
    # synchronously on the calling thread (verified against the stdlib
    # source; see the module docstring) -- so this covers both a killed
    # parent and an ordinary parent exit. It does not fire early on the
    # happy path: by the time an ordinary run reaches process exit,
    # `guarded_process_pool`'s own `shutdown(wait=True)` has already reaped
    # every worker while the main thread was still very much alive.
    # Linux-only (`prctl` is a Linux syscall) -- macOS gets no coverage
    # here, stated rather than silently absent.
    if sys.platform.startswith("linux"):
        with contextlib.suppress(Exception):
            _set_pdeathsig_sigkill()


def _set_pdeathsig_sigkill() -> None:
    """``prctl(PR_SET_PDEATHSIG, SIGKILL)`` via ``ctypes`` — stdlib only (Q5:
    no new runtime dependency). Linux-only; the caller guards the platform
    check and wraps every failure, so this never breaks the pool it runs in.
    """
    import ctypes

    pr_set_pdeathsig: Final[int] = 1
    libc = ctypes.CDLL(None, use_errno=True)
    rc = libc.prctl(pr_set_pdeathsig, signal.SIGKILL, 0, 0, 0)
    if rc != 0:
        errno_value = ctypes.get_errno()
        raise OSError(errno_value, os.strerror(errno_value))


_ALIVE: Final[str] = "alive"
_DEAD: Final[str] = "dead"
_UNKNOWN: Final[str] = "unknown"


def _liveness(process: object) -> str:
    """Tri-state: a process that cannot be interrogated is `unknown`, never `dead`."""
    try:
        return _ALIVE if process.is_alive() else _DEAD  # type: ignore[attr-defined]
    except Exception:
        return _UNKNOWN


def _kernel_state(pid: int, proc_root: str = "/proc") -> str:
    """One kernel-side observation of ``pid`` (read-only; survivors only).

    `Process.is_alive()` and `.exitcode` both answer from `waitpid(WNOHANG)`,
    which reports "no exit yet" for a zombie, a still-running process and an
    already-reaped child alike, so only the filesystem can tell them apart.
    Returns `zombie`, `running:<state>` (only while the parent pid is ours),
    `absent`, or `unavailable` (no such filesystem, or it would not parse).
    """
    try:
        with open(f"{proc_root}/{pid}/stat") as handle:
            text = handle.read()
    except FileNotFoundError:
        return "absent" if os.path.isdir(proc_root) else "unavailable"
    except OSError:
        return "unavailable"
    try:
        # `comm` may itself contain spaces and parentheses: split at the LAST one.
        fields = text[text.rindex(")") + 1 :].split()
        state, ppid = fields[0], int(fields[1])
    except (ValueError, IndexError):
        return "unavailable"
    if state == "Z":
        return "zombie"
    return f"running:{state}" if ppid == os.getpid() else "absent"


class _ProcessOutcome:
    """What `_terminate_pool` observed about one process. Plain `__slots__`
    class: this module takes no new import, so no dataclass / NamedTuple."""

    __slots__ = (
        "exitcode_after",
        "join_elapsed_s",
        "join_raised",
        "join_timeout_s",
        "kernel",
        "liveness_after",
        "liveness_at_kill",
        "pid",
        "sigkill",
        "tail",
    )

    def __init__(
        self,
        pid: int,
        liveness_at_kill: str,
        sigkill: str,
        join_timeout_s: float,
        join_elapsed_s: float,
        join_raised: bool,
        exitcode_after: object,
        liveness_after: str,
        kernel: str,
    ) -> None:
        self.pid = pid
        self.liveness_at_kill = liveness_at_kill
        self.sigkill = sigkill
        self.join_timeout_s = join_timeout_s
        self.join_elapsed_s = join_elapsed_s
        self.join_raised = join_raised
        self.exitcode_after = exitcode_after
        self.liveness_after = liveness_after
        self.kernel = kernel
        self.tail = "reaped" if liveness_after == _DEAD else _classify_tail(self)

    def __str__(self) -> str:
        return (
            f"pid={self.pid} tail={self.tail} liveness_at_kill={self.liveness_at_kill} "
            f"sigkill={self.sigkill} join_timeout_s={self.join_timeout_s:.3f} "
            f"join_elapsed_s={self.join_elapsed_s:.3f} join_raised={self.join_raised} "
            f"exitcode_after={self.exitcode_after} liveness_after={self.liveness_after} "
            f"kernel={self.kernel}"
        )


def _classify_tail(outcome: _ProcessOutcome) -> str:
    """Name which teardown tail a survivor is in; the first matching rule wins."""
    if _UNKNOWN in (outcome.liveness_at_kill, outcome.liveness_after):
        return "liveness-unknown"
    if outcome.kernel == "zombie":
        return "join-timed-out"
    if outcome.kernel.startswith("running:") and outcome.sigkill == "sent":
        return "outlived-sigkill"
    if outcome.kernel == "absent":
        return "stale-liveness"
    return "undetermined"


class _TeardownReport:
    """Per-process outcomes of one `_terminate_pool` call, in pool order."""

    __slots__ = ("outcomes",)

    def __init__(self, outcomes: tuple[_ProcessOutcome, ...]) -> None:
        self.outcomes = outcomes

    @property
    def survivors(self) -> tuple[_ProcessOutcome, ...]:
        return tuple(o for o in self.outcomes if o.liveness_after != _DEAD)

    def __str__(self) -> str:
        survivors = self.survivors
        total = len(self.outcomes)
        if not survivors:
            return f"every worker reaped ({total} of {total})"
        names = ", ".join(f"{o.pid}={o.tail}" for o in survivors)
        head = f"a worker survived _terminate_pool: {len(survivors)} of {total} \u2014 {names}"
        return "\n".join([head, *(str(o) for o in survivors)])


def _terminate_pool(
    executor: ProcessPoolExecutor,
    *,
    grace_s: float = TEARDOWN_GRACE_S,
    reap_s: float = _REAP_BUDGET_S,
) -> _TeardownReport:
    """SIGTERM every known worker, wait out the grace window, SIGKILL the rest,
    then reap and REPORT what could not be verified.

    Mirrors ``adapters/subprocess_util.py::_terminate_group``'s grace-then-kill
    shape, but per-PID rather than per-group: this product spawns each worker
    through ``ProcessPoolExecutor`` rather than through the subprocess
    chokepoint, so there is no ``start_new_session``-isolated group to
    address in the first place — signalling *a* group here would either miss
    the workers entirely (no group control was ever requested for them) or
    reach processes this call has no business touching (the whole job's
    launching shell, when the parent was not itself made a session leader).
    ``executor._processes`` (a ``{pid: Process}`` mapping) is the one way to
    reach them: there is no public accessor on ``ProcessPoolExecutor``, and
    none of this codebase's own AST guards (write-chokepoint mutation, engine
    import, subprocess spawn) apply to it or to ``Process.terminate/.kill/
    .join`` — this stays entirely off every forbidden-call list.

    Anything not proven dead is signalled, at most once each; the reap phase
    shares ONE deadline (``reap_s``) whatever the worker count; nothing is
    retried and nothing is raised or emitted. The returned report is a
    hardening of what is observable, not a claim that any worker stops
    surviving.
    """
    processes = list(getattr(executor, "_processes", {}).values())
    if not processes:
        return _TeardownReport(())

    for process in processes:
        if _liveness(process) != _DEAD:
            with contextlib.suppress(OSError, ValueError):
                process.terminate()  # SIGTERM -- lets AtomicWriter unwind

    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline and any(_liveness(p) != _DEAD for p in processes):
        time.sleep(_POLL_S)

    at_kill: list[str] = []
    sigkill: list[str] = []
    for process in processes:
        state = _liveness(process)
        at_kill.append(state)
        if state == _DEAD:
            sigkill.append("not-needed")
            continue
        try:
            process.kill()  # SIGKILL -- whatever the grace window left
            sigkill.append("sent")
        except (OSError, ValueError):
            sigkill.append("raised")

    reap_deadline = time.monotonic() + reap_s
    timeouts: list[float] = []
    elapsed: list[float] = []
    raised: list[bool] = []
    for process in processes:
        timeout = max(0.0, reap_deadline - time.monotonic())
        started = time.monotonic()
        join_raised = False
        try:
            process.join(timeout=timeout)
        except Exception:
            join_raised = True
        timeouts.append(timeout)
        elapsed.append(time.monotonic() - started)
        raised.append(join_raised)

    outcomes: list[_ProcessOutcome] = []
    for index, process in enumerate(processes):
        after = _liveness(process)
        exitcode: object = None
        pid: int = -1
        with contextlib.suppress(Exception):
            exitcode = getattr(process, "exitcode", None)
        with contextlib.suppress(Exception):
            pid = getattr(process, "pid", -1)
        kernel = "not-read" if after == _DEAD else _kernel_state(pid)
        outcomes.append(
            _ProcessOutcome(
                pid,
                at_kill[index],
                sigkill[index],
                timeouts[index],
                elapsed[index],
                raised[index],
                exitcode,
                after,
                kernel,
            )
        )

    with contextlib.suppress(Exception):
        executor.shutdown(wait=False, cancel_futures=True)
    return _TeardownReport(tuple(outcomes))


@contextmanager
def guarded_process_pool(max_workers: int) -> Iterator[ProcessPoolExecutor]:
    """A ``ProcessPoolExecutor`` whose workers do not outlive a signal to the
    parent (B-055). Drop-in replacement for
    ``with ProcessPoolExecutor(max_workers=...) as executor:``.

    On the ordinary, unsignalled path this changes nothing observable: the
    handlers installed below are removed in ``finally`` and
    ``executor.shutdown(wait=True)`` runs exactly as the plain context
    manager's own ``__exit__`` would have — PLAN §12 R-08's byte-identity
    property (``--threads 1`` vs ``--threads 8``) is a property of
    ``_render_chunk``, untouched by this wrapper, and is re-proven after this
    change rather than assumed.

    On SIGTERM/SIGINT/SIGHUP, the handler installed here (a) actively tears
    the pool down (:func:`_terminate_pool`), which a bare ``shutdown()`` in
    any combination cannot do — see the module docstring for why — and then
    (b) lets the parent die BY the signal rather than exiting through
    ``sys.exit``.

    (h) Off the main thread, ``signal.signal()`` raises ``ValueError``.
    ``rasterize_document`` is called directly by unit tests as well as by the
    CLI, so this degrades to "no signal protection, same as before this
    spec" rather than crashing a caller that happens not to be on the main
    thread — installation is all-or-nothing (a partial install, with some
    signals guarded and others not, would be a worse, silently inconsistent
    state than none at all).
    """
    executor = _GuardedExecutor(
        max_workers=max_workers,
        mp_context=_mp_context(),
        initializer=_worker_initializer,
    )
    previous: dict[int, object] = {}
    installed = False

    def _teardown_and_die(signum: int, _frame: object) -> None:
        _terminate_pool(executor)
        # (f) Die BY the signal: WIFSIGNALED true, $? = 128 + signum -- what
        # `timeout`, systemd and `docker stop` actually expect. SIG_DFL, not
        # "whatever `previous` holds": Python's own default SIGINT
        # disposition is `default_int_handler` (raises `KeyboardInterrupt`),
        # which would turn this into an ordinary Python exception instead of
        # a real signal death.
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    try:
        for name in _GUARDED_SIGNAL_NAMES:
            sig = getattr(signal, name, None)
            if sig is None:  # pragma: no cover - SIGHUP does not exist on Windows
                continue
            try:
                previous[sig] = signal.signal(sig, _teardown_and_die)
            except ValueError:
                # Off the main thread (h). Roll back whatever this loop
                # already installed and proceed with none of it -- a run
                # started off the main thread gets exactly today's
                # behaviour, not a partially-protected one.
                for done_sig, handler in previous.items():
                    with contextlib.suppress(ValueError):
                        signal.signal(done_sig, handler)  # type: ignore[arg-type]
                previous.clear()
                break
        else:
            installed = True

        yield executor
    finally:
        if installed:
            for sig, handler in previous.items():
                with contextlib.suppress(ValueError):
                    signal.signal(sig, handler)  # type: ignore[arg-type]
        executor.shutdown(wait=True)
