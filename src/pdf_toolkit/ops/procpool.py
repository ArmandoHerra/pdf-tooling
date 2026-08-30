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
in-flight :class:`~pdf_toolkit.safety.atomic.AtomicWriter` cleanly, but
cannot by itself end the worker. :func:`_terminate_pool`'s own SIGKILL, sent
once the grace window elapses, is what actually ends it. The raised exception
in :func:`_worker_initializer` therefore exists ONLY to buy the write
chokepoint a chance to discard its temp file before that SIGKILL lands
(design consideration (e) — trading orphaned processes for orphaned
``.pdftoolkit-*`` temp files would not be a fix either).

THE GUARANTEE THIS MODULE ACTUALLY MAKES
-----------------------------------------
**No NEW output after the parent dies.** "No partial output" is not
provable — a worker that was already mid-``os.replace`` when a real SIGKILL
(uncatchable, see below) arrived is not something any code in this process
can prevent, and this module makes no claim about it.

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
import os
import signal
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from typing import Final

__all__ = ["guarded_process_pool"]

#: How long a SIGTERM'd worker is given to unwind through its own
#: `AtomicWriter.__exit__` (discarding an in-flight temp file) before it is
#: SIGKILLed outright. Independently declared rather than imported from
#: `adapters/subprocess_util.py::TERM_GRACE_S` -- `ops/` does not import
#: `adapters/` anywhere today (verbs reach an engine only through `ports/`),
#: and coupling two unrelated layers for one shared float is not worth
#: introducing that first backward edge. Same value class, same reasoning.
TEARDOWN_GRACE_S: Final[float] = 2.0

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
    `except PdfToolkitError` (a plain `Exception` subclass) must never catch
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
    executor = ProcessPoolExecutor(max_workers=max_workers, initializer=_worker_initializer)
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
