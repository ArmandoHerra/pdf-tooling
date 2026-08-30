"""``ops/procpool.py`` — the mechanics unit level, complementing the
black-box, real-signal proof in
``tests/integration/test_rasterize_signals.py``.

That integration file is what actually proves the guarantee end to end
(real CLI subprocess, real signals, real process teardown); this file
proves the PIECES the mechanism is built from, each in isolation:

* the worker `initializer=` resets SIGINT/SIGHUP and installs a
  worker-local SIGTERM handler -- observed FROM INSIDE a real
  `ProcessPoolExecutor` worker (never by calling the initializer in this
  test's own process, which would mutate the test runner's own signal
  state);
* `_terminate_pool` actually ends and reaps a live worker process;
* `guarded_process_pool`'s happy path restores whatever `signal.getsignal`
  reported beforehand, unchanged;
* (h) off the main thread, the whole context manager degrades to "no
  protection", never a crash.
"""

from __future__ import annotations

import contextlib
import signal
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor

import pytest

from pdf_toolkit.ops import procpool

# --------------------------------------------------------------------------- #
# Module-level, picklable-by-reference helpers -- the same discipline
# `ops/raster.py::_render_chunk` already uses (AC4), for the same reason: a
# `ProcessPoolExecutor` worker (under ANY start method) must be able to
# import these fresh.
# --------------------------------------------------------------------------- #


def _report_signal_state(_marker: int) -> dict[str, str]:
    """Runs INSIDE a real worker; reports what ITS OWN dispositions are."""
    return {
        "SIGTERM": repr(signal.getsignal(signal.SIGTERM)),
        "SIGINT": repr(signal.getsignal(signal.SIGINT)),
        "SIGHUP": repr(signal.getsignal(signal.SIGHUP)),
    }


def _sleep_forever_ish(_marker: int) -> None:
    time.sleep(30)


# --------------------------------------------------------------------------- #
# The worker initializer, observed from inside a real worker.
# --------------------------------------------------------------------------- #


def test_worker_initializer_resets_sigint_and_sighup_to_default() -> None:
    with ProcessPoolExecutor(max_workers=1, initializer=procpool._worker_initializer) as executor:
        state = executor.submit(_report_signal_state, 0).result(timeout=30)
    assert state["SIGINT"] == repr(signal.SIG_DFL), state
    assert state["SIGHUP"] == repr(signal.SIG_DFL), state


def test_worker_initializer_installs_a_worker_local_sigterm_handler() -> None:
    """Not SIG_DFL (design (e) -- a bare default disposition gives an
    in-flight `AtomicWriter` no chance to unwind), and not whatever the
    PARENT (this test process) has installed for itself either -- design
    (c)'s fork-inheritance hazard, proven the other way around: the worker's
    own handler is `_raise_worker_unwind`, a completely different callable
    from anything this test process could have had.
    """
    with ProcessPoolExecutor(max_workers=1, initializer=procpool._worker_initializer) as executor:
        state = executor.submit(_report_signal_state, 0).result(timeout=30)
    assert "_raise_worker_unwind" in state["SIGTERM"], state
    assert state["SIGTERM"] != repr(signal.SIG_DFL), state


def test_worker_initializer_called_directly_sets_the_exact_dispositions_described() -> None:
    """The two tests above prove `_worker_initializer` correctly by observing
    a REAL worker from the outside -- the only honest way to test what a
    process's own signal table looks like from its own perspective. This one
    calls it directly, in THIS process, purely so coverage.py -- which
    cannot trace across a `multiprocessing` fork/spawn boundary the way it
    can trace across `subprocess.Popen` (this project's `[tool.coverage.run]
    patch = ["subprocess"]`) -- gets to see the branch it cannot otherwise
    observe running at all. Every disposition this test's own process had
    before the call is saved and restored, so this is the one test in the
    file that is careful to leave no trace of having run.
    """
    signals = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
    before = {sig: signal.getsignal(sig) for sig in signals}
    try:
        procpool._worker_initializer()
        assert signal.getsignal(signal.SIGINT) is signal.SIG_DFL
        assert signal.getsignal(signal.SIGHUP) is signal.SIG_DFL
        assert signal.getsignal(signal.SIGTERM) is procpool._raise_worker_unwind
    finally:
        for sig, handler in before.items():
            signal.signal(sig, handler)  # type: ignore[arg-type]
    after = {sig: signal.getsignal(sig) for sig in signals}
    assert after == before


# --------------------------------------------------------------------------- #
# `_terminate_pool` actually ends and reaps a live worker, in isolation from
# the signal-handling machinery around it.
# --------------------------------------------------------------------------- #


def test_terminate_pool_ends_and_reaps_a_live_worker() -> None:
    executor = ProcessPoolExecutor(max_workers=1, initializer=procpool._worker_initializer)
    try:
        future = executor.submit(_sleep_forever_ish, 0)
        # Give the worker a moment to actually be scheduled and start
        # sleeping, so this proves killing a RUNNING process, not a
        # not-yet-started one `cancel_futures` could have handled anyway
        # (the module docstring's central point about the naive fix).
        time.sleep(0.2)
        processes = list(executor._processes.values())
        assert processes, "no worker process was ever spawned -- test is not measuring anything"
        assert all(p.is_alive() for p in processes)

        procpool._terminate_pool(executor)

        assert all(not p.is_alive() for p in processes), "a worker survived _terminate_pool"
        with contextlib.suppress(Exception):
            future.cancel()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def test_terminate_pool_is_a_no_op_over_an_empty_pool() -> None:
    """No worker has been spawned yet -- `executor._processes` is empty.
    Must not raise (a `--threads 1` run signalled before its single worker
    is scheduled hits exactly this path)."""
    executor = ProcessPoolExecutor(max_workers=1, initializer=procpool._worker_initializer)
    try:
        procpool._terminate_pool(executor)
    finally:
        executor.shutdown(wait=False)


# --------------------------------------------------------------------------- #
# `guarded_process_pool`'s happy path: unchanged behaviour, handlers restored.
# --------------------------------------------------------------------------- #


def _double(value: int) -> int:
    return value * 2


def test_guarded_process_pool_happy_path_runs_work_normally() -> None:
    with procpool.guarded_process_pool(2) as executor:
        results = [executor.submit(_double, n).result(timeout=30) for n in range(4)]
    assert results == [0, 2, 4, 6]


def test_guarded_process_pool_restores_the_previous_handlers_on_normal_exit() -> None:
    before = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    with procpool.guarded_process_pool(1) as executor:
        # Installed while the pool is open -- none of these are what was
        # there a moment ago.
        during = {sig: signal.getsignal(sig) for sig in before}
        assert during != before
        executor.submit(_double, 1).result(timeout=30)
    after = {sig: signal.getsignal(sig) for sig in before}
    assert after == before, "a guarded pool must leave signal dispositions exactly as it found them"


def test_guarded_process_pool_restores_handlers_even_when_the_body_raises() -> None:
    before = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        with procpool.guarded_process_pool(1):
            raise _Boom("ordinary exception unwind, no signal involved")

    after = {sig: signal.getsignal(sig) for sig in before}
    assert after == before


# --------------------------------------------------------------------------- #
# (h) Off the main thread: degrade to "no protection", never crash.
# --------------------------------------------------------------------------- #


def test_guarded_process_pool_off_main_thread_degrades_without_crashing() -> None:
    outcome: dict[str, object] = {}

    def worker() -> None:
        try:
            with procpool.guarded_process_pool(1) as executor:
                outcome["result"] = executor.submit(_double, 5).result(timeout=30)
        except BaseException as error:  # pragma: no cover - failure path only
            outcome["error"] = error

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=30)
    assert not thread.is_alive(), "worker thread did not finish"
    assert "error" not in outcome, outcome.get("error")
    assert outcome["result"] == 10


# --------------------------------------------------------------------------- #
# PR_SET_PDEATHSIG -- Linux-only, best-effort, never breaks the pool.
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="PR_SET_PDEATHSIG is Linux-only")
def test_set_pdeathsig_sigkill_succeeds_on_linux() -> None:
    # Runs in THIS process -- prctl(PR_SET_PDEATHSIG) affects only the
    # calling process's own kernel-side death-signal registration, which is
    # not observable to Python and has no product-visible effect outside a
    # real fork; the only thing worth proving here is that the syscall
    # itself does not raise on the platform this product claims to cover it
    # on.
    procpool._set_pdeathsig_sigkill()


def test_worker_initializer_gates_pdeathsig_on_linux_by_source() -> None:
    """Structural companion to the two platform-specific tests above: the
    call is reached only behind `sys.platform.startswith("linux")`, so
    nothing about it can run at all on a platform that never takes that
    branch (macOS gets no PDEATHSIG coverage -- stated, not silently
    absent, per design consideration (b))."""
    import inspect

    source = inspect.getsource(procpool._worker_initializer)
    assert 'sys.platform.startswith("linux")' in source
