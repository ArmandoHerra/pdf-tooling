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

import ast
import contextlib
import re
import signal
import sys
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Final

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
