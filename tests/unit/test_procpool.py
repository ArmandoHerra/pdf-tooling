"""``ops/procpool.py`` — the mechanics unit level, complementing the
black-box, real-signal proof in
``tests/integration/test_rasterize_signals.py``.

That integration file is what actually proves the guarantee end to end
(real CLI subprocess, real signals, real process teardown); this file
proves the PIECES the mechanism is built from, each in isolation:

* the worker `initializer=` installs ONE worker-local handler on all three
  guarded signals (PDF-101) -- observed FROM INSIDE a real
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

import ast
import contextlib
import errno
import inspect
import multiprocessing
import operator
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Final

import pytest

from pdf_tooling.ops import procpool

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


def _pool_kwargs() -> dict[str, Any]:
    """The worker bootstrap the product builds (PDF-111: `_pool_options`), over the
    interpreter's own default start method EXCEPT `forkserver` (the 3.14 default).

    `_worker_initializer` now verifies `getppid()` against the pool's builder, and
    a forkserver worker's parent is the helper, so it would correctly end itself at
    start-up. The product pins `spawn` for that reason; these mechanics tests only
    need workers whose parent is this process.
    """
    context = multiprocessing.get_context()
    if context.get_start_method() == "forkserver":
        context = multiprocessing.get_context("spawn")
    return dict(procpool._pool_options(context))


# --------------------------------------------------------------------------- #
# The worker initializer, observed from inside a real worker.
# --------------------------------------------------------------------------- #


def test_worker_initializer_installs_the_worker_local_handler_on_all_three_signals() -> None:
    """PDF-101 (AC9): this replaces the pin that SIGINT/SIGHUP are ``SIG_DFL``.
    A group Ctrl-C reaches a worker directly, and ``SIG_DFL`` killed it while it
    held an open writer -- so all three guarded signals report the unwinding handler.
    """
    with ProcessPoolExecutor(max_workers=1, **_pool_kwargs()) as executor:
        state = executor.submit(_report_signal_state, 0).result(timeout=30)
    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        assert "_raise_worker_unwind" in state[name], state
        assert state[name] != repr(signal.SIG_DFL), state


def test_worker_initializer_installs_a_worker_local_sigterm_handler() -> None:
    """Not SIG_DFL (design (e) -- a bare default disposition gives an
    in-flight `AtomicWriter` no chance to unwind), and not whatever the
    PARENT (this test process) has installed for itself either -- design
    (c)'s fork-inheritance hazard, proven the other way around: the worker's
    own handler is `_raise_worker_unwind`, a completely different callable
    from anything this test process could have had.
    """
    with ProcessPoolExecutor(max_workers=1, **_pool_kwargs()) as executor:
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
        procpool._worker_initializer(os.getppid())
        for sig in signals:
            assert signal.getsignal(sig) is procpool._raise_worker_unwind
    finally:
        for sig, handler in before.items():
            signal.signal(sig, handler)  # type: ignore[arg-type]
    after = {sig: signal.getsignal(sig) for sig in signals}
    assert after == before


# --------------------------------------------------------------------------- #
# PDF-101: the worker-only code, covered IN-PROCESS (coverage.py does not trace
# into pool workers). Every disposition touched is restored.
# --------------------------------------------------------------------------- #


class _Exited(BaseException):
    """Stands in for ``os._exit`` so a test can observe the status it was given."""

    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


def test_the_first_signal_repoints_all_three_to_a_python_absorber_then_raises() -> None:
    signals = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
    before: dict[signal.Signals, Any] = {sig: signal.getsignal(sig) for sig in signals}
    try:
        with pytest.raises(procpool._WorkerUnwind) as caught:
            procpool._raise_worker_unwind(signal.SIGINT, None)
        assert caught.value.signum == signal.SIGINT
        for sig in signals:
            # A Python callable, never SIG_IGN: CPython raises "Signal N ignored due to
            # race condition" inside cleanup code when a tripped signal goes to SIG_IGN.
            assert signal.getsignal(sig) is procpool._absorb_signal
    finally:
        for sig, handler in before.items():
            signal.signal(sig, handler)
    assert {sig: signal.getsignal(sig) for sig in signals} == before


def test_a_worker_unwind_is_a_quiet_system_exit_that_is_not_an_exception() -> None:
    unwind = procpool._WorkerUnwind(signal.SIGHUP)
    assert isinstance(unwind, SystemExit)
    assert not isinstance(unwind, Exception)
    assert unwind.signum == signal.SIGHUP


def test_run_task_returns_the_value_of_a_task_that_completes() -> None:
    assert procpool._run_task(operator.add, 2, 3) == 5


def test_run_task_lets_every_other_exception_through_unchanged() -> None:
    def boom() -> None:
        raise ValueError("not a teardown")

    with pytest.raises(ValueError, match="not a teardown"):
        procpool._run_task(boom)


def test_run_task_exits_the_worker_with_128_plus_the_signal_once_the_unwind_is_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_exit(status: int) -> None:
        raise _Exited(status)

    def unwinding() -> None:
        raise procpool._WorkerUnwind(signal.SIGINT)

    monkeypatch.setattr(procpool.os, "_exit", fake_exit)
    with pytest.raises(_Exited) as caught:
        procpool._run_task(unwinding)
    assert caught.value.status == 128 + signal.SIGINT == 130


# --------------------------------------------------------------------------- #
# `_terminate_pool` actually ends and reaps a live worker, in isolation from
# the signal-handling machinery around it.
# --------------------------------------------------------------------------- #


def _assert_no_survivor(processes: Sequence[Any], report: Any) -> None:
    """The real arm's assertion, with the teardown's own report in its message.

    The verdict is this test's OWN, independent liveness read -- never the
    function's self-report. The report only ever decorates the message, so a
    failure names which tail occurred on its first line.
    """
    alive = [p.pid for p in processes if p.is_alive()]
    assert alive == [], f"a worker survived _terminate_pool -- {report}"


def test_terminate_pool_ends_and_reaps_a_live_worker() -> None:
    executor = ProcessPoolExecutor(max_workers=1, **_pool_kwargs())
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

        report = procpool._terminate_pool(executor)

        _assert_no_survivor(processes, report)
        with contextlib.suppress(Exception):
            future.cancel()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def test_terminate_pool_is_a_no_op_over_an_empty_pool() -> None:
    """No worker has been spawned yet -- `executor._processes` is empty.
    Must not raise (a `--threads 1` run signalled before its single worker
    is scheduled hits exactly this path)."""
    executor = ProcessPoolExecutor(max_workers=1, **_pool_kwargs())
    try:
        report = procpool._terminate_pool(executor)
    finally:
        executor.shutdown(wait=False)
    assert report.outcomes == ()
    assert report.survivors == ()


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


# --------------------------------------------------------------------------- #
# PDF-78 -- the derivation cannot be bypassed, and the signalled arms may not
# learn to recognise a loaded host.
#
# WHY THESE GUARDS LIVE HERE AND NOT IN `tests/test_gate_budget.py`. That module
# owns the `STARTUP_BUDGET_MS` guard shape these copy, and it is `PDF-72`'s
# write surface in this same wave -- so a write there is a measured collision
# this item declines rather than schedules. The two token tuples are CONSUMED
# from it by import (X-157), never re-typed: a token list that exists twice is a
# token list that will disagree, and `test_the_token_tuples_are_consumed_...`
# below is what makes "consumed" a fact rather than an intention.
#
# WHY THE SIGNALS MODULE IS READ FROM DISK rather than imported. Source-level is
# what makes the PLANTS possible -- every red control below is a scratch module
# handed to the same function the live check uses, so the check is proven to
# bite before it is trusted to pass.
# --------------------------------------------------------------------------- #

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from test_gate_budget import DISTRIBUTION_TOKENS, EVIDENCE_TOKENS  # noqa: E402

REPO_ROOT = TESTS_DIR.parent
PROCPOOL_SOURCE = REPO_ROOT / "src" / "pdf_tooling" / "ops" / "procpool.py"
SIGNALS_SOURCE = TESTS_DIR / "integration" / "test_rasterize_signals.py"

#: The value `TEARDOWN_GRACE_S` carried while it was UNDERIVED, and the floor it
#: may never go below. 6.0 is macOS-`spawn`-calibrated by hand (`[B-055]`,
#: 2026-08-30, `2s -> 6s`) and this product's measurement apparatus is
#: Linux-local, so lowering a two-platform constant on one platform's evidence
#: would silently un-protect the other. The derivation may RAISE it or leave it.
GRACE_SENTINEL: Final[float] = 6.0

#: `EVIDENCE_TOKENS` + `DISTRIBUTION_TOKENS` cannot express a measurement whose
#: VALIDITY DEPENDS ON THE HOST BEING LOUD -- none of the six names the load or
#: the sample size, and `perf/README.md`'s rule (*"a record with `quiet: false`
#: is admissible as an OBSERVATION and inadmissible as a BASELINE"*) runs the
#: other way for this one quantity. Two more, and deliberately no more: an
#: evidence set that grows per spec stops being an instrument.
PDF78_TOKENS: Final = ("LOAD", "TRIALS")

_CONSTANT = re.compile(r"^(\w+)(?::\s*Final\[float\])?\s*=\s*([\d.]+)\s*$")


def constant_with_block(text: str, name: str) -> tuple[float, str]:
    """``(the constant, the comment block immediately above it)``.

    Deliberately the same shape as `tests/test_gate_budget.py::budget_block`,
    generalized over the constant's name so one function serves the live read
    and every plant. The annotation is OPTIONAL in the pattern because a plant
    is a bare `NAME = 12.0` -- which is exactly the shape the guard exists to
    catch, so a pattern that only matched the annotated spelling would pass
    over the thing it is for.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _CONSTANT.match(line)
        if match is None or match.group(1) != name:
            continue
        start = index
        while start > 0 and lines[start - 1].lstrip().startswith("#"):
            start -= 1
        return float(match.group(2)), "\n".join(lines[start:index])
    raise AssertionError(f"{name} is not defined in the source read")


def test_a_moved_teardown_grace_carries_its_measurement() -> None:
    """The bump is not reachable by accident.

    `[B-055]` already made it once, by hand, on this exact constant, to make
    this exact assertion green: `2s -> 6s` on 2026-08-30. It bought FOUR DAYS
    and the assertion has reddened five times since. A value may change here. A
    value may not change without its derivation.
    """
    value, block = constant_with_block(PROCPOOL_SOURCE.read_text(), "TEARDOWN_GRACE_S")
    if value == GRACE_SENTINEL:
        return
    required = EVIDENCE_TOKENS + DISTRIBUTION_TOKENS + PDF78_TOKENS
    missing = [token for token in required if token not in block]
    assert missing == [], (
        f"TEARDOWN_GRACE_S = {value} -- moved off the underived {GRACE_SENTINEL} -- but "
        f"its adjacent comment block omits {missing}. A grace that moves without its "
        f"measurement beside it is a bump wearing a comment, and this constant's own "
        f"history is the argument: raising it to reach green is the move whose "
        f"insufficiency is already on the record in changelog.md's [B-055] entry"
    )


def test_a_raised_constant_with_no_evidence_block_reddens(tmp_path: Path) -> None:
    """THE RED, against a plant, because a guard that has only ever passed has
    not been shown to check anything.

    The plant is the cheapest wrong move in this item, written out: one
    unrelated comment line, then a doubled constant.
    """
    scratch = tmp_path / "planted.py"
    scratch.write_text("# unrelated comment\nTEARDOWN_GRACE_S = 12.0\n")
    value, block = constant_with_block(scratch.read_text(), "TEARDOWN_GRACE_S")
    assert value == 12.0
    required = EVIDENCE_TOKENS + DISTRIBUTION_TOKENS + PDF78_TOKENS
    missing = [token for token in required if token not in block]
    assert missing == list(required), (
        "a bare raised constant was accepted, or was reported as only PARTLY "
        f"undocumented: the guard named {missing} of {list(required)}. It must name "
        "every missing token, because a guard that reports one is a guard a second "
        "token can hide behind"
    )


def test_the_token_tuples_are_consumed_from_the_gate_budget_module_not_retyped() -> None:
    """X-157, made mechanical rather than promised.

    Identity, not equality: two tuples that happen to agree today are two tuples,
    and the day `tests/test_gate_budget.py` grows a seventh evidence token a copy
    here would keep passing while the claim it encodes had moved.
    """
    import test_gate_budget

    assert EVIDENCE_TOKENS is test_gate_budget.EVIDENCE_TOKENS
    assert DISTRIBUTION_TOKENS is test_gate_budget.DISTRIBUTION_TOKENS


def test_teardown_grace_is_never_lowered_below_the_hand_calibrated_floor() -> None:
    """Out of scope in every branch, and it is the quiet failure mode: a
    Linux-local measurement arguing for a SMALLER window would un-protect
    macOS, whose cold `spawn` import is what sized the 6.0 in the first place
    and which no apparatus in this repository can measure."""
    value, _block = constant_with_block(PROCPOOL_SOURCE.read_text(), "TEARDOWN_GRACE_S")
    assert value >= GRACE_SENTINEL, (
        f"TEARDOWN_GRACE_S = {value} is below the {GRACE_SENTINEL} floor. That floor is "
        f"macOS-`spawn`-calibrated ([B-055]) and this repository has no macOS host to "
        f"re-derive it on; a lower value on Linux-only evidence is a silent un-protection "
        f"of the other supported platform. If the measurement argues for less, that is a "
        f"finding to FILE, not a value to land"
    )


# --------------------------------------------------------------------------- #
# PDF-78 AC11 -- the signalled arms may not abstain, by any mechanism.
#
# WHY A SHAPE WALK AND NOT A NAME LIST, and it is `tests/test_gate_budget.py`'s
# own lesson at :446-476 restated one file over. The first version of that
# module's load-immunity guard asserted `"getloadavg" not in body` and was
# defeated in ONE LINE by a mechanism with a different name -- an
# `if os.environ.get("PYTEST_XDIST_WORKER"): pytest.skip(...)` -- after which
# *"the startup claim was then held by two tests that both skip, i.e. by
# nothing, and this file said it was fine."*
#
# So what is matched is the VERB OF ABSTAINING rather than any vendor's spelling
# of it. A library invented tomorrow still has to call something that stops the
# arm without failing it, and the terminal identifier of that call is what this
# walk reads. The scope is deliberately OVER-approximated -- the three arms, the
# two helpers they share, and every module-level function those transitively
# reach -- because a precise call graph is one missed edge away from a false
# negative, and the whole cost of the over-approximation is that nobody may
# write abstention code in this span at all, which IS the rule.
#
# NOT BANNED, and the distinction is the point: `pytest.fail` (`_wait_for_progress`
# uses it) and reading `os.getloadavg()` to RECORD it. Failing is not abstaining,
# and measuring a host is not sensing it. What is banned is stopping without a
# verdict -- "an arm that abstains under load has not survived a loaded host; it
# has learned to recognise one."
# --------------------------------------------------------------------------- #

#: The roots of the span. The three signalled arms plus the two helpers they all
#: share -- `_assert_clean_signal_death` is literally the same code on three
#: paths, which is why a fix proven on `sigterm` alone proves one third of the
#: surface.
_NO_ABSTENTION_ROOTS: Final = (
    "test_sigterm_to_parent_only_stops_new_output_and_leaves_no_survivors",
    "test_sigint_to_parent_only_stops_new_output_and_leaves_no_survivors",
    "test_sighup_to_parent_only_stops_new_output_and_leaves_no_survivors",
    "_send_signal_and_measure",
    "_assert_clean_signal_death",
)

#: The terminal identifier of a call, or of a marker decorator, that stops an arm
#: WITHOUT a verdict. Spelled as verbs, not as `pytest.skip`/`unittest.skipIf`/
#: `flaky`/`pytest-rerunfailures`, so the next mechanism is covered by the rule
#: rather than by an amendment to it.
_ABSTENTION_VERBS: Final = frozenset(
    {
        "skip",
        "skipIf",
        "skipif",
        "skipUnless",
        "xfail",
        "importorskip",
        "exit",
        "_exit",
        "rerun",
        "reruns",
        "retry",
        "flaky",
        "repeat",
    }
)


def _module_functions(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _terminal_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def autouse_fixtures(tree: ast.Module) -> tuple[str, ...]:
    """Every module-level `@pytest.fixture(autouse=True)` in *tree*.

    Folded into the span because an autouse fixture is reached by every arm in
    its module without any arm CALLING it -- so a call-graph walk that started
    only from the named roots would step straight past the one place an
    abstention can be installed for all of them at once. PDF-78's own
    declared-load harness is such a fixture, which makes this the case where the
    guard has to cover the thing the same spec added.
    """
    found: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if _terminal_name(decorator.func) != "fixture":
                continue
            if any(
                keyword.arg == "autouse"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in decorator.keywords
            ):
                found.append(node.name)
    return tuple(found)


def abstention_span(tree: ast.Module, roots: Sequence[str], *, hops: int = 5) -> set[str]:
    """*roots*, plus every autouse fixture, plus everything they transitively call."""
    functions = _module_functions(tree)
    reached = {name for name in (*roots, *autouse_fixtures(tree)) if name in functions}
    for _ in range(hops):
        grew = False
        for name in list(reached):
            for sub in ast.walk(functions[name]):
                if not isinstance(sub, ast.Call):
                    continue
                called = _terminal_name(sub.func)
                if called in functions and called not in reached:
                    reached.add(called)
                    grew = True
        if not grew:
            break
    return reached


def abstentions(tree: ast.Module, roots: Sequence[str], *, where: str) -> list[str]:
    """Every abstention-shaped call or marker inside the span, named by file,
    line and function."""
    functions = _module_functions(tree)
    found: list[str] = []
    for name in sorted(abstention_span(tree, roots)):
        node = functions[name]
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            verb = _terminal_name(target)
            if verb in _ABSTENTION_VERBS:
                found.append(f"{where}:{decorator.lineno} {name}() decorated with `{verb}`")
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            verb = _terminal_name(sub.func)
            if verb in _ABSTENTION_VERBS:
                found.append(f"{where}:{sub.lineno} {name}() calls `{verb}`")
    return found


def test_the_signalled_arms_contain_no_abstention_and_no_load_sensing() -> None:
    """THE PROPERTY THIS ITEM BUYS, stated as a guard: a green here means the
    product is correct, not that the host was quiet.

    An arm that skips on a loaded host has not survived contention; and adding
    one in wave 4 would reinstate the precise shape `PDF-68` removed in wave 3.
    """
    where = SIGNALS_SOURCE.relative_to(REPO_ROOT).as_posix()
    tree = ast.parse(SIGNALS_SOURCE.read_text())
    span = abstention_span(tree, _NO_ABSTENTION_ROOTS)
    assert set(_NO_ABSTENTION_ROOTS) <= span, (
        f"the walk did not even reach {sorted(set(_NO_ABSTENTION_ROOTS) - span)} in "
        f"{where} -- a guard that cannot see its own subject checks nothing. Were the "
        f"arms renamed?"
    )
    assert "declared_load" in span, (
        f"the declared-load harness is not inside the walk's span in {where}. It is an "
        f"autouse fixture every arm in that module runs, so an abstention installed "
        f"there would abstain for all three arms at once and this guard would not see it"
    )
    found = abstentions(tree, _NO_ABSTENTION_ROOTS, where=where)
    assert found == [], (
        f"the signalled arms (or something they call) can now abstain: {found}. "
        f"A skip/xfail/rerun under load does not prove the teardown is correct; it "
        f"proves the arm can recognise a loaded host. If these arms cannot hold on a "
        f"loaded host, the repair is the grace derivation or the teardown's shape -- "
        f"never an abstention, by any mechanism, by any name"
    )


def test_a_planted_abstention_is_named_by_the_walk(tmp_path: Path) -> None:
    """AC11's RED: the exact plant that defeated the first version of
    `tests/test_gate_budget.py`'s guard, handed to this one.

    Planted into the shared HELPER rather than into an arm, because that is the
    harder case: a walk that only read the three test functions' own bodies
    would see three clean arms and three skipped runs.
    """
    planted = tmp_path / "planted.py"
    planted.write_text(
        "import os\n"
        "import pytest\n"
        "\n"
        "\n"
        "def _send_signal_and_measure(tmp_path, sig):\n"
        '    if os.environ.get("PYTEST_XDIST_WORKER"):\n'
        '        pytest.skip("host is loaded")\n'
        "    return 1\n"
        "\n"
        "\n"
        "def test_sigterm_to_parent_only_stops_new_output_and_leaves_no_survivors():\n"
        "    assert _send_signal_and_measure(None, None) == 1\n"
    )
    found = abstentions(ast.parse(planted.read_text()), _NO_ABSTENTION_ROOTS, where="planted.py")
    assert found, "the planted xdist skip was not caught -- the walk is not checking anything"
    assert any("_send_signal_and_measure" in entry and "`skip`" in entry for entry in found), (
        f"the walk fired but did not name the function and the verb: {found}"
    )
    assert any(entry.startswith("planted.py:7") for entry in found), (
        f"the walk named no line number: {found}"
    )


def test_the_grace_fits_inside_the_parent_exit_bound() -> None:
    """D4.1's STRUCTURAL CEILING, mechanized rather than checked once by hand.

    `TEARDOWN_GRACE_S` is paid IN FULL on every signalled teardown, so it is a
    bill and not a ceiling, and the bill is presented to
    `_PARENT_EXIT_TIMEOUT_S`. The bound is a separate, independently-derived
    number ON PURPOSE: a bound defined as `grace + overhead` would accommodate
    any grace by construction and could never red, which is the shape of a
    control that cannot control. A grace raised past the room this bound leaves
    reddens HERE by name, instead of reddening three integration arms with
    *"parent did not exit within 25.0s"* and no explanation.
    """
    grace, _block = constant_with_block(PROCPOOL_SOURCE.read_text(), "TEARDOWN_GRACE_S")
    signals = SIGNALS_SOURCE.read_text()
    bound, _ = constant_with_block(signals, "_PARENT_EXIT_TIMEOUT_S")
    overhead, _ = constant_with_block(signals, "_PARENT_OVERHEAD_P95_S")
    assert grace + overhead < bound, (
        f"TEARDOWN_GRACE_S ({grace}s) plus the measured p95 parent teardown overhead "
        f"({overhead}s) is {grace + overhead}s, which does not fit inside "
        f"_PARENT_EXIT_TIMEOUT_S ({bound}s). Widening that bound to make room is the "
        f"same forbidden move one file over: it is PDF-29-class derived evidence, not "
        f"headroom to spend. Either the grace is too large -- in which case the "
        f"fixed-wall-clock SHAPE is refuted and that is a finding for the "
        f"project-manager -- or the overhead has moved and must be re-measured"
    )


# --------------------------------------------------------------------------- #
# PDF-78 AC12/AC19 -- the two mutants that make every signalled arm green.
#
# Both are cheaper than the bump and both are worse than the flake, so both get
# an arm rather than a paragraph. A guard that goes green because the GUARD
# moved is the same forbidden shape as a constant widened to reach green, and
# the sweep is the quieter of the two: it makes the module green immediately AND
# deletes evidence a user's `doctor --strict` is entitled to see.
# --------------------------------------------------------------------------- #

#: Any comparison that is not `==` would turn the residue claim into a
#: TOLERANCE. `<= 1` is the one that makes the module green today.
_WEAKENING_OPS: Final = (ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn)


def stray_assertions(tree: ast.Module, function: str) -> tuple[list[str], list[str]]:
    """``(equalities against empty, weakened comparisons)`` over `strays`."""
    node = _module_functions(tree).get(function)
    if node is None:
        raise AssertionError(f"{function} is not defined in the source read")
    strict: list[str] = []
    weak: list[str] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Assert) or not isinstance(sub.test, ast.Compare):
            continue
        test = sub.test
        if "strays" not in ast.dump(test):
            continue
        operator = test.ops[0]
        if isinstance(operator, ast.Eq) and isinstance(test.comparators[0], ast.Tuple):
            if not test.comparators[0].elts:
                strict.append(f"line {sub.lineno}")
                continue
        if isinstance(operator, _WEAKENING_OPS) or isinstance(operator, ast.Eq):
            weak.append(f"line {sub.lineno}: {type(operator).__name__}")
    return strict, weak


def test_the_stray_assertion_is_an_equality_against_zero_and_is_not_weakened() -> None:
    """The arm asserts an invariant `ops/procpool.py` itself calls BEST-EFFORT,
    which makes it a flake generator by construction -- and naming that is not a
    licence to soften it. It is the only thing pinning design consideration (e),
    *"the fix must not trade orphaned processes for orphaned temp files"*.

    The repair for a best-effort property that will not hold is to make the
    mechanism hold it, or to change what the product PROMISES (a ruling, not an
    edit). It is never to move the assertion.
    """
    tree = ast.parse(SIGNALS_SOURCE.read_text())
    strict, weak = stray_assertions(tree, "_assert_clean_signal_death")
    assert strict, (
        "_assert_clean_signal_death no longer asserts `strays == ()`. Residue on a "
        "SIGNALLED teardown is the one thing these three arms exist to catch"
    )
    assert weak == [], (
        f"the stray assertion has been weakened into a tolerance: {weak}. `<= 1` makes "
        f"this module green today and it is exactly the forbidden shape applied to a "
        f"test instead of to a constant -- and the ledger's own occurrences left ONE, "
        f"FOUR and SIX files, so a tolerance of one would have hidden neither"
    )


def test_a_weakened_stray_assertion_reddens(tmp_path: Path) -> None:
    """AC12's RED, against the exact mutant that reaches green."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def _assert_clean_signal_death(proc, sig, at_death, after, strays):\n"
        "    assert len(strays) <= 1, strays\n"
    )
    strict, weak = stray_assertions(ast.parse(planted.read_text()), "_assert_clean_signal_death")
    assert strict == [], f"a `<= 1` tolerance was read as a strict equality: {strict}"
    assert weak, "the `<= 1` tolerance was accepted -- this guard is not checking the operator"


#: Disposing of a file, spelled as verbs. `find_stray_temps` is a REPORTER and
#: `PLAN §12 R-07` accepts the residue class explicitly: reported, NEVER swept.
_DISPOSAL_VERBS: Final = frozenset({"unlink", "remove", "rmtree", "removedirs", "rmdir"})


def disposal_calls(tree: ast.Module) -> list[str]:
    return [
        f"line {node.lineno}: {_terminal_name(node.func)}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _terminal_name(node.func) in _DISPOSAL_VERBS
    ]


def test_the_teardown_path_contains_no_residue_sweep() -> None:
    """THE THIRD CHEAPEST WRONG MOVE, and the only one that also destroys a
    user-facing signal.

    Sweeping the residue-prefixed temp files after the SIGKILL sweep makes all
    three signalled arms green instantly. It also contradicts a recorded plan
    decision and deletes exactly the evidence `doctor --strict` exists to
    surface -- so the symptom of taking it would be a suite that got quieter and
    a product that got less honest, which is the hardest pair to notice later.

    (The prefix itself is deliberately NOT spelled here. It is a frozen on-disk
    population with its own byte-unchanged guard in
    `tests/test_rename_completeness.py`, and a guard that had to name it in
    order to forbid sweeping it would grow the population it protects. The check
    below reads the disposal VERB, which is what a sweep cannot avoid using.)
    """
    found = disposal_calls(ast.parse(PROCPOOL_SOURCE.read_text()))
    assert found == [], (
        f"{PROCPOOL_SOURCE.name} now disposes of files: {found}. The teardown path "
        f"SIGNALS workers so they can discard their OWN temp files; it does not clean up "
        f"after them. `PLAN §12 R-07` accepts the residue class as reported and never "
        f"swept, and `find_stray_temps` is a reporter whose whole purpose is to let "
        f"`doctor --strict` surface it"
    )


def test_a_planted_residue_sweep_reddens(tmp_path: Path) -> None:
    """AC19's RED: the sweep that would have closed this flake in one line."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def _terminate_pool(executor, *, grace_s=6.0):\n"
        "    for leftover in out_dir.iterdir():\n"
        "        leftover.unlink()\n"
    )
    found = disposal_calls(ast.parse(planted.read_text()))
    assert found, "a planted post-teardown sweep was not caught -- this guard checks nothing"
    assert any("unlink" in entry for entry in found), found


# --------------------------------------------------------------------------- #
# PDF-87 -- `_terminate_pool` states its own postcondition. Everything below is
# driven with planted objects, a planted `/proc` root or a real local child: no
# arm here depends on how a real pool worker happens to die on this host. It is a
# hardening of what the teardown REPORTS; no arm asserts that any worker stops
# surviving.
# --------------------------------------------------------------------------- #


class _Planted:
    """A stand-in `Process` with spies. Distinct small-int pids: a real
    `/proc/<pid>` read is always monkeypatched away in the arms that use these."""

    def __init__(
        self,
        pid: int,
        *,
        is_alive_raises: bool = False,
        dies_on_kill: bool = False,
        every_method_raises: bool = False,
    ) -> None:
        self.pid = pid
        self._alive = True
        self._exitcode: int | None = None
        self._is_alive_raises = is_alive_raises or every_method_raises
        self._dies_on_kill = dies_on_kill
        self._every_method_raises = every_method_raises
        self.terminate_calls = 0
        self.kill_calls = 0
        self.join_timeouts: list[float] = []
        self.on_join: Any = None

    def is_alive(self) -> bool:
        if self._is_alive_raises:
            raise OSError(errno.ESRCH, "No such process")
        return self._alive

    @property
    def exitcode(self) -> int | None:
        if self._every_method_raises:
            raise OSError(errno.ESRCH, "No such process")
        return self._exitcode

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self._every_method_raises:
            raise OSError(errno.ESRCH, "No such process")

    def kill(self) -> None:
        self.kill_calls += 1
        if self._every_method_raises:
            raise OSError(errno.ESRCH, "No such process")
        if self._dies_on_kill:
            self._alive = False
            self._exitcode = -9

    def join(self, timeout: float | None = None) -> None:
        assert timeout is not None
        self.join_timeouts.append(timeout)
        if self._every_method_raises:
            raise OSError(errno.ESRCH, "No such process")
        if self.on_join is not None:
            self.on_join(timeout)


class _StubExecutor:
    def __init__(self, *planted: _Planted) -> None:
        self._processes = {p.pid: p for p in planted}
        self.shutdown_calls: list[tuple[bool, bool]] = []

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        self.shutdown_calls.append((wait, cancel_futures))


def _plant_kernel(monkeypatch: pytest.MonkeyPatch, answer: str) -> list[int]:
    """Every planted pid reads as `answer`; returns the pids actually asked about."""
    asked: list[int] = []

    def fake(pid: int, proc_root: str = "/proc") -> str:
        asked.append(pid)
        return answer

    monkeypatch.setattr(procpool, "_kernel_state", fake)
    return asked


def _teardown(*planted: _Planted, grace_s: float = 0.0, reap_s: float = 0.0) -> Any:
    return procpool._terminate_pool(_StubExecutor(*planted), grace_s=grace_s, reap_s=reap_s)  # type: ignore[arg-type]


def test_an_uninterrogable_worker_is_signalled_and_reported_as_a_survivor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plant_kernel(monkeypatch, "unavailable")
    opaque = _Planted(11, is_alive_raises=True)

    report = _teardown(opaque)

    assert opaque.terminate_calls == 1
    assert opaque.kill_calls == 1
    assert [o.pid for o in report.survivors] == [11]
    assert report.survivors[0].tail == "liveness-unknown"


def test_a_planted_survivor_is_reported_and_a_reaped_worker_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plant_kernel(monkeypatch, "zombie")
    survivor = _Planted(21)
    reaped = _Planted(22, dies_on_kill=True)

    report = _teardown(survivor, reaped)

    assert len(report.outcomes) == 2
    assert [o.pid for o in report.survivors] == [21]
    assert report.survivors[0].tail == "join-timed-out"
    reaped_outcome = next(o for o in report.outcomes if o.pid == 22)
    assert reaped_outcome.exitcode_after == -9
    assert reaped_outcome.sigkill == "sent"


def test_a_mixed_pool_reports_exactly_the_opaque_and_the_surviving_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plant_kernel(monkeypatch, "zombie")
    opaque = _Planted(31, is_alive_raises=True)
    survivor = _Planted(32)
    reaped = _Planted(33, dies_on_kill=True)

    report = _teardown(opaque, survivor, reaped)

    assert {o.pid for o in report.survivors} == {31, 32}


def test_teardown_signals_each_worker_at_most_once_and_joins_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plant_kernel(monkeypatch, "zombie")
    pool = [_Planted(40 + n) for n in range(8)]

    report = _teardown(*pool)

    assert len(report.survivors) == 8
    for planted in pool:
        assert planted.terminate_calls <= 1
        assert planted.kill_calls <= 1
        assert len(planted.join_timeouts) == 1


def test_a_worker_whose_every_method_raises_yields_a_report_not_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plant_kernel(monkeypatch, "unavailable")
    hostile = _Planted(51, every_method_raises=True)

    report = _teardown(hostile)

    assert [o.pid for o in report.survivors] == [51]
    survivor = report.survivors[0]
    assert survivor.tail == "liveness-unknown"
    assert survivor.join_raised is True
    assert survivor.sigkill == "raised"
    assert survivor.exitcode_after is None


class _FakeClock:
    """Replaces the module-global name `time` inside `procpool` only."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.parametrize("workers", [1, 8, 64])
def test_the_reap_phase_is_bounded_by_one_deadline_whatever_the_worker_count(
    monkeypatch: pytest.MonkeyPatch, workers: int
) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(procpool, "time", clock)
    _plant_kernel(monkeypatch, "zombie")
    reap_started: list[float] = []

    def unreapable_join(timeout: float) -> None:
        if not reap_started:
            reap_started.append(clock.now)
        clock.now += timeout

    pool = [_Planted(100 + n) for n in range(workers)]
    for planted in pool:
        planted.on_join = unreapable_join
    begin = clock.now

    procpool._terminate_pool(_StubExecutor(*pool), grace_s=16.0)  # type: ignore[arg-type]

    assert clock.now - reap_started[0] <= procpool._REAP_BUDGET_S + 1e-9
    assert clock.now - begin <= 16.0 + procpool._POLL_S + procpool._REAP_BUDGET_S + 1e-9
    assert all(t >= 0.0 for planted in pool for t in planted.join_timeouts)
    assert all(len(planted.join_timeouts) == 1 for planted in pool)


def reap_budget_problems(grace: float, reap: float, overhead: float, bound: float) -> list[str]:
    problems: list[str] = []
    if not grace + overhead + reap < bound:
        problems.append(
            f"grace {grace} + overhead {overhead} + reap {reap} = {grace + overhead + reap} "
            f"does not fit inside the parent exit bound {bound}"
        )
    if not reap < grace:
        problems.append(f"reap budget {reap} is not below the grace {grace}")
    return problems


def test_the_grace_and_the_reap_budget_fit_inside_the_parent_exit_bound() -> None:
    source = PROCPOOL_SOURCE.read_text()
    signals = SIGNALS_SOURCE.read_text()
    grace, _ = constant_with_block(source, "TEARDOWN_GRACE_S")
    reap, _ = constant_with_block(source, "_REAP_BUDGET_S")
    bound, _ = constant_with_block(signals, "_PARENT_EXIT_TIMEOUT_S")
    overhead, _ = constant_with_block(signals, "_PARENT_OVERHEAD_P95_S")
    assert reap_budget_problems(grace, reap, overhead, bound) == []


def test_a_reap_budget_that_does_not_fit_reddens(tmp_path: Path) -> None:
    scratch = tmp_path / "planted.py"
    scratch.write_text("# unrelated\n_REAP_BUDGET_S = 9.0\n")
    reap, _ = constant_with_block(scratch.read_text(), "_REAP_BUDGET_S")
    assert reap == 9.0
    problems = reap_budget_problems(16.0, reap, 0.327, 25.0)
    assert len(problems) == 1
    assert "25.327" in problems[0]


_REAP_TOKENS: Final = (
    "BASIS:",
    "ARITHMETIC, NOT MEASURED",
    "STOPS HOLDING IF",
    "TEARDOWN_GRACE_S",
    "_PARENT_EXIT_TIMEOUT_S",
    "_PARENT_OVERHEAD_P95_S",
    "8.673",
)


def test_the_reap_budget_states_its_basis_and_where_it_stops_holding() -> None:
    _, block = constant_with_block(PROCPOOL_SOURCE.read_text(), "_REAP_BUDGET_S")
    assert [token for token in _REAP_TOKENS if token not in block] == []


def test_a_reap_budget_with_no_evidence_block_names_every_missing_token(tmp_path: Path) -> None:
    scratch = tmp_path / "planted.py"
    scratch.write_text("# unrelated\n_REAP_BUDGET_S = 8.0\n")
    _, block = constant_with_block(scratch.read_text(), "_REAP_BUDGET_S")
    assert [token for token in _REAP_TOKENS if token not in block] == list(_REAP_TOKENS)


def _write_stat(root: Path, pid: int, comm: str, state: str, ppid: int) -> None:
    (root / str(pid)).mkdir()
    (root / str(pid) / "stat").write_text(f"{pid} ({comm}) {state} {ppid} 1 1 0 -1 0\n")


@pytest.mark.parametrize(
    ("comm", "state", "ppid_ours", "expected"),
    [
        ("python", "Z", True, "zombie"),
        ("python", "S", True, "running:S"),
        ("python", "D", True, "running:D"),
        ("python", "R", False, "absent"),
        ("a) Z (b", "S", True, "running:S"),
    ],
    ids=["zombie", "sleeping", "disk-wait", "foreign-ppid", "paren-in-comm"],
)
def test_kernel_state_classifies_a_planted_proc_root(
    tmp_path: Path, comm: str, state: str, ppid_ours: bool, expected: str
) -> None:
    _write_stat(tmp_path, 7, comm, state, os.getpid() if ppid_ours else os.getpid() + 1)
    assert procpool._kernel_state(7, str(tmp_path)) == expected


def test_kernel_state_is_absent_when_the_proc_root_has_no_such_pid(tmp_path: Path) -> None:
    assert procpool._kernel_state(7, str(tmp_path)) == "absent"


def test_kernel_state_is_unavailable_for_garbage_and_for_a_missing_proc_root(
    tmp_path: Path,
) -> None:
    (tmp_path / "8").mkdir()
    (tmp_path / "8" / "stat").write_text("garbage with no parenthesis")
    assert procpool._kernel_state(8, str(tmp_path)) == "unavailable"
    (tmp_path / "9").mkdir()
    (tmp_path / "9" / "stat").write_text("9 (x) Z")
    assert procpool._kernel_state(9, str(tmp_path)) == "unavailable"
    assert procpool._kernel_state(7, str(tmp_path / "no-such-root")) == "unavailable"


@pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="no /proc on this host")
def test_kernel_state_tracks_a_real_child_through_zombie_to_absent() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert procpool._kernel_state(child.pid).startswith("running:")
        child.kill()
        deadline = time.monotonic() + 10.0
        while procpool._kernel_state(child.pid) != "zombie":
            assert time.monotonic() < deadline, "the killed child never became a zombie"
            time.sleep(0.01)
        child.wait()
        assert procpool._kernel_state(child.pid) == "absent"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_kernel_state_is_not_read_for_a_reaped_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _plant_kernel(monkeypatch, "zombie")
    pool = [_Planted(60 + n, dies_on_kill=True) for n in range(3)]

    report = _teardown(*pool)

    assert report.survivors == ()
    assert asked == []


_TAIL_CASES: Final = (
    ("join-timed-out", "zombie", {}),
    ("liveness-unknown", "unavailable", {"is_alive_raises": True}),
    ("outlived-sigkill", "running:S", {}),
    ("stale-liveness", "absent", {}),
    ("undetermined", "unavailable", {}),
)


@pytest.mark.parametrize(
    ("label", "kernel", "plant"), _TAIL_CASES, ids=[case[0] for case in _TAIL_CASES]
)
def test_the_report_first_line_names_the_tail(
    monkeypatch: pytest.MonkeyPatch, label: str, kernel: str, plant: dict[str, bool]
) -> None:
    _plant_kernel(monkeypatch, kernel)

    report = _teardown(_Planted(71, **plant))

    lines = str(report).splitlines()
    assert lines[0].startswith("a worker survived _terminate_pool: 1 of 1 — ")
    assert f"71={label}" in lines[0]
    for other, _, _ in _TAIL_CASES:
        if other != label:
            assert f"={other}" not in lines[0]
    for field in (
        "pid=",
        "tail=",
        "liveness_at_kill=",
        "sigkill=",
        "join_timeout_s=",
        "join_elapsed_s=",
        "join_raised=",
        "exitcode_after=",
        "liveness_after=",
        "kernel=",
    ):
        assert field in lines[1]


def test_a_reaped_pool_report_says_so_in_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    _plant_kernel(monkeypatch, "zombie")
    report = _teardown(_Planted(81, dies_on_kill=True), _Planted(82, dies_on_kill=True))
    assert str(report) == "every worker reaped (2 of 2)"


def test_a_survivor_reaching_the_real_arm_assertion_is_named_by_its_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plant_kernel(monkeypatch, "zombie")
    survivor = _Planted(91)
    report = _teardown(survivor)

    with pytest.raises(AssertionError) as caught:
        _assert_no_survivor([survivor], report)

    first = str(caught.value).splitlines()[0]
    assert first.startswith(
        "a worker survived _terminate_pool -- a worker survived _terminate_pool: 1 of 1 — "
    )
    assert "=join-timed-out" in first
    assert ".is_alive()" in inspect.getsource(_assert_no_survivor)


_EMISSION_NAMES: Final = frozenset(
    {
        "print",
        "write",
        "writelines",
        "warn",
        "warning",
        "info",
        "debug",
        "error",
        "exception",
        "critical",
        "log",
    }
)
_TEARDOWN_SYMBOLS: Final = (
    "_terminate_pool",
    "_liveness",
    "_kernel_state",
    "_classify_tail",
    "_ProcessOutcome",
    "_TeardownReport",
)


def teardown_emissions(tree: ast.Module, symbols: Sequence[str]) -> list[str]:
    found: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.ClassDef)) or node.name not in symbols:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and _terminal_name(sub.func) in _EMISSION_NAMES:
                found.append(f"line {sub.lineno}: {node.name}() calls `{_terminal_name(sub.func)}`")
            if isinstance(sub, ast.Attribute) and sub.attr in {"stderr", "stdout"}:
                found.append(f"line {sub.lineno}: {node.name}() reads `{sub.attr}`")
    return found


def test_the_teardown_path_emits_nothing() -> None:
    tree = ast.parse(PROCPOOL_SOURCE.read_text())
    present = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    assert set(_TEARDOWN_SYMBOLS) <= present, sorted(set(_TEARDOWN_SYMBOLS) - present)
    assert teardown_emissions(tree, _TEARDOWN_SYMBOLS) == []


def test_a_planted_emission_on_the_teardown_path_reddens(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text(
        'import sys\n\n\ndef _terminate_pool(executor):\n    sys.stderr.write("x")\n'
    )
    found = teardown_emissions(ast.parse(planted.read_text()), _TEARDOWN_SYMBOLS)
    assert any(entry.startswith("line 5:") and "_terminate_pool" in entry for entry in found), found
