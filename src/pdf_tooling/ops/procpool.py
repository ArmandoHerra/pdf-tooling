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
does NOT exit the process. This means raising an exception from inside a
render call (however it is raised, ``SystemExit`` included) can unwind an
in-flight :class:`~pdf_tooling.safety.atomic.AtomicWriter` cleanly, but
cannot by itself end the worker. :func:`_terminate_pool`'s own SIGKILL, sent
once the grace window elapses, is what actually ends it. The raised exception
in :func:`_worker_initializer` therefore exists ONLY to buy the write
chokepoint a chance to discard its temp file before that SIGKILL lands
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
SIGTERM defect this spec was filed against. "SIGINT is already clean" is
true only for an interactive terminal Ctrl-C, which signals the WHOLE
foreground process group and kills workers directly, independent of
anything this process does; ``kill -INT <pid>`` (a supervisor's own
single-process signal, and the exact discipline the automated regression
test below uses) receives no such help by accident. Folding SIGINT into
this same teardown makes it clean by construction instead, which is a
strict improvement over relying on process-group luck and answers "did you
regress SIGINT?" with a mechanism instead of a hope.

**SIGKILL to the parent cannot be handled. This is stated, not implied.** A
``SIGKILL``ed process gets no code to run at all — no signal handler,
no ``finally``, nothing. The only thing the CHILD side can still do is
PR_SET_PDEATHSIG (Linux only; ``prctl`` is a Linux syscall, so macOS gets no
coverage here — stated rather than silently absent, matching CI's own
matrix, which runs ``ubuntu-latest`` and ``macos-14`` and no Windows job).

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
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from typing import Final

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

#: Every signal torn down through the ONE routine below (design (a)). SIGKILL
#: to the PARENT cannot appear here -- it is uncatchable by definition; see
#: `_worker_initializer` for the one thing the CHILD side can still do about
#: it. `getattr` rather than a bare attribute reference: `SIGHUP` does not
#: exist on Windows, and this module must still be IMPORTABLE there even
#: though the product is POSIX/macOS-only (`pyproject.toml`'s own
#: classifiers) -- an unsupported platform should get "no protection",
#: never an ImportError before a single line of product code runs.
_GUARDED_SIGNAL_NAMES: Final[tuple[str, ...]] = ("SIGTERM", "SIGINT", "SIGHUP")


class _WorkerUnwind(BaseException):
    """Raised inside a render worker's own SIGTERM handler (never elsewhere).

    Deliberately a `BaseException`, not an `Exception`: `_render_one`'s own
    `except PdfToolingError` (a plain `Exception` subclass) must never catch
    it and turn a teardown into an ordinary failed-page result.

    Never escapes the worker PROCESS on its own -- see this module's
    docstring for the verified stdlib fact that makes that true. Its only
    job is to propagate through whatever `with AtomicWriter(...)` block the
    worker happens to be inside when the signal arrives, so that block's
    `__exit__` discards its temp file before `_terminate_pool`'s SIGKILL
    lands.
    """


def _raise_worker_unwind(signum: int, _frame: object) -> None:
    raise _WorkerUnwind(signum)


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
    # SIGTERM gets a WORKER-LOCAL handler instead of a bare reset to
    # SIG_DFL: `Process.terminate()` -- the only way this module ever
    # signals a worker directly -- always sends SIGTERM, and SIG_DFL kills
    # the process with no chance for an open `AtomicWriter` to unwind, which
    # is precisely what would leave `.pdftoolkit-*` residue (design (e)).
    # SIGINT/SIGHUP reset to plain SIG_DFL: nothing in this product ever
    # signals a worker with either directly (they would only reach a worker
    # via a real, whole-process-group delivery this teardown never controls
    # in the first place), and inheriting the parent's pool-shaped handler
    # for them under `fork` would be the identical hazard SIGTERM has.
    for name in ("SIGINT", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is None:  # pragma: no cover - POSIX-only names, not on Windows
            continue
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, signal.SIG_DFL)
    term = getattr(signal, "SIGTERM", None)
    if term is not None:  # pragma: no branch - SIGTERM exists on every CI platform
        with contextlib.suppress(ValueError, OSError):
            signal.signal(term, _raise_worker_unwind)

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


def _is_alive(process: object) -> bool:
    try:
        return bool(process.is_alive())  # type: ignore[attr-defined]
    except Exception:
        return False


def _terminate_pool(executor: ProcessPoolExecutor, *, grace_s: float = TEARDOWN_GRACE_S) -> None:
    """SIGTERM every known worker, wait out the grace window, SIGKILL the rest.

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
    """
    processes = list(getattr(executor, "_processes", {}).values())
    if not processes:
        return

    for process in processes:
        if _is_alive(process):
            with contextlib.suppress(OSError, ValueError):
                process.terminate()  # SIGTERM -- lets AtomicWriter unwind

    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline and any(_is_alive(p) for p in processes):
        time.sleep(_POLL_S)

    for process in processes:
        if _is_alive(process):
            with contextlib.suppress(OSError, ValueError):
                process.kill()  # SIGKILL -- whatever the grace window left

    for process in processes:
        with contextlib.suppress(Exception):
            process.join(timeout=grace_s)

    with contextlib.suppress(Exception):
        executor.shutdown(wait=False, cancel_futures=True)


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
    executor = ProcessPoolExecutor(
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
