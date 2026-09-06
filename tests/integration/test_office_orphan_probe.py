"""The orphan probe's asymmetry, proven by DISAGREEMENT — PDF-44 Half B.

WHY THIS MODULE EXISTS, AND WHY IT HAS NO ENGINE IN IT
------------------------------------------------------
`face1c63a0` is filed as a **bug**, not as a flake row, and the distinguishing
sentence is this: *"the instrument is **symmetric** — if a sibling's
``soffice.bin`` EXITS between the two samples while this test DOES leak exactly
one orphan, ``after == before`` and the assertion **PASSES**. It cannot detect
the defect it was written for even when it is green."*

`test_office.py` sampled ``pgrep -fc soffice.bin`` **machine-wide**, before and
after a timeout, inside a suite whose ``addopts`` pins ``-n auto``. Written as a
table over two independent events — **O** = this invocation leaked an orphan,
**S** = a sibling's count changed between the samples — the old predicate
``after <= before`` behaved like this:

===================  ==========================  ===========================
                     sibling EXITS between        sibling STARTS between
===================  ==========================  ===========================
**orphan leaked**    ``after == before`` -> PASS  FAIL (right verdict,
                     **FALSE GREEN**              wrong cause)
**no orphan**        PASS                         **FAIL -- FALSE RED**
===================  ==========================  ===========================

The false red is the cheap symptom, and it is what got noticed (6/6, *"count
rose (3 -> 7)"* -- by **four**, the number of concurrent siblings, not by one
orphan). **The top-left cell is the defect.** A wider tolerance, a retry or a
serial-only marker fixes the column that is merely noisy and leaves the cell
that is dishonest.

So the deliverable is asymmetry, not scoping, and a paragraph asserting it
would be worth nothing. **This module is the assertion.** It builds the
top-left cell synthetically and runs BOTH predicates over that one scenario:
the retained old one must say PASS and the new one must say FAIL. That
disagreement, in that direction, is the reader-confirmable proof.

WHY IT IS ENGINE-FREE, WHICH IS A CORRECTNESS PROPERTY AND NOT A CONVENIENCE
---------------------------------------------------------------------------
`@pytest.mark.requires("soffice")` skips the real arm on every leg without the
engine. If the asymmetry claim lived only there, this spec's central claim
would be **unproven almost everywhere it runs**. Nothing below needs an engine,
a corpus, a quiet host or `pgrep`: ``sh``, ``sleep`` and ``os.killpg`` are the
entire toolkit (`test_ocr.py:815` is the standing precedent for the first two
inside ``tests/``). **This module skips nowhere.**

WHY THE PROBE IS RESTATED LOCALLY RATHER THAN IMPORTED
------------------------------------------------------
``_group_alive`` is `adapters/subprocess_util.py:212` restated here, exactly as
`test_rasterize_signals.py:157` and `tests/unit/test_subprocess_util.py:46`
already restate it, and for the reason those files give: importing the
product's own liveness helper into the test that judges the product's own
cleanup means **one broken helper turns both green together**. `PDF-30`'s AC25
is the general form -- *the assertion is made by a different consumer than the
one that computes it* -- and this is that rule applied to a syscall wrapper.

``os.killpg(pgid, 0)`` is also the reason there is no ``ps`` and no ``pgrep``
here. It answers *"does anything, including an unreaped zombie, still exist
under this pgid at all"* with the same syscall on both platforms in this
project's matrix, where BSD and GNU ``ps`` do not agree on a stable
``sid``/``pgid`` column spelling.

THE RESIDUAL, NAMED RATHER THAN HIDDEN
--------------------------------------
One false **red** survives the replacement: PID/PGID recycling inside the
observation window could hand our group id to an unrelated process. It is not
eliminated and it does not need to be. **An instrument that can only err toward
red is honest; the defect being repaired is one that errs toward green.**
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

#: How long a synthetic survivor is asked to live. Long enough that it is still
#: there at the second sample under any plausible scheduling delay, short enough
#: that a leaked one on a developer's machine ages out within a minute rather
#: than becoming one of the week-old orphans this instrument exists to notice.
SURVIVOR_LIFETIME_S: Final = 45

#: Bound on how long a killed group may take to vanish. A deadline that keeps
#: the scenario deterministic, NOT a tolerance that may be widened to turn a
#: red green.
GROUP_REAP_DEADLINE_S: Final = 10.0


def _group_alive(pgid: int) -> bool:
    """Whether any process remains in *pgid*.

    `adapters/subprocess_util.py:212` restated locally, deliberately -- see the
    module docstring. Signal 0 performs the permission and existence checks
    without delivering anything. ``PermissionError`` means the group exists but
    is not ours, which is still "alive" for this question.
    """
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - not reachable for our own child
        return True
    return True


def _wait_group_gone(pgid: int, deadline_s: float = GROUP_REAP_DEADLINE_S) -> float | None:
    """Seconds taken for *pgid* to vanish, or ``None`` if it never did."""
    started = time.monotonic()
    while time.monotonic() - started < deadline_s:
        if not _group_alive(pgid):
            return time.monotonic() - started
        time.sleep(0.02)
    return None


class _Scenario:
    """Every process this test created, and nothing it did not.

    Teardown is unconditional and group-scoped: it signals only pgids recorded
    here. Nothing on this host that this scenario did not spawn is ever
    addressed -- which is the same discipline the probe under test is being
    given.
    """

    def __init__(self) -> None:
        self.spawned: list[subprocess.Popen[bytes]] = []

    def spawn_group(self, script: str) -> subprocess.Popen[bytes]:
        """A child in its OWN process group, so ``pgid == pid`` by definition."""
        proc = subprocess.Popen(  # noqa: S602 - fixed argv, no shell string interpolation
            ["sh", "-c", script],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.spawned.append(proc)
        return proc

    def adopt(self, proc: subprocess.Popen[bytes]) -> None:
        """Put a process spawned elsewhere under this scenario's teardown."""
        self.spawned.append(proc)

    def kill_group(self, proc: subprocess.Popen[bytes]) -> float | None:
        """SIGKILL the whole group AND REAP THE DIRECT CHILD.

        The reap is not tidiness, it is correctness. ``_group_alive`` answers
        *"does anything, including an unreaped zombie, still exist under this
        pgid"* -- so a killed-but-unwaited direct child stays a zombie in its
        own group and the group NEVER goes away. The first draft of this module
        omitted the ``wait()`` and every scenario blocked for the full reap
        deadline, which is the probe correctly reporting a process that really
        was still there.
        """
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=GROUP_REAP_DEADLINE_S)
        return _wait_group_gone(proc.pid)

    def leak_a_survivor_into_its_own_group(self) -> int:
        """One orphan in a group of our own: the leader exits, a child lives on.

        This is the ``MHC-50`` shape reduced to its observable -- exactly what a
        timed-out ``convert`` leaves behind when only the direct child is
        killed. The leader is reaped, so a PID-scoped check would see nothing.
        """
        proc = self.spawn_group(f"sleep {SURVIVOR_LIFETIME_S} & exit 0")
        proc.wait(timeout=GROUP_REAP_DEADLINE_S)
        assert _group_alive(proc.pid), (
            "the scenario failed to construct a survivor; the backgrounded child "
            "did not outlive its leader, so nothing below would be testing the "
            "case it claims to test"
        )
        return proc.pid

    def alive_count(self, pgids: list[int]) -> int:
        """How many of *pgids* still exist.

        This is the OLD predicate's population: it spans groups **this
        invocation did not create**, which is the entire property that made the
        machine-wide ``pgrep -fc soffice.bin`` symmetric. It is enumerated
        rather than scanned so the scenario is deterministic on every host --
        the marker processes are all ours or the scenario's, so an enumeration
        and a scan over the same marker see the same set.
        """
        return sum(1 for pgid in pgids if _group_alive(pgid))

    def close(self) -> None:
        for proc in self.spawned:
            self.kill_group(proc)


@pytest.fixture
def scenario() -> Iterator[_Scenario]:
    built = _Scenario()
    try:
        yield built
    finally:
        built.close()


def _old_predicate(before: int, after: int) -> bool:
    """`test_office.py:269` as it read before this spec: ``after <= before``.

    Retained here **purely as the control**. It is a local function rather than
    an import precisely because nothing should ever call it again.
    """
    return after <= before


def _new_predicate(our_pgid: int) -> bool:
    """Does the group THIS invocation created still hold anything?

    The verdict is ``True`` for "clean". No sibling can enter this answer:
    ``start_new_session=True`` puts every spawn in its own group, so a
    sibling's processes are in a different group **by construction**.
    """
    return not _group_alive(our_pgid)


# --------------------------------------------------------------------------- #
# AC8 -- the DISAGREEMENT. This is the criterion that discharges the item.
# --------------------------------------------------------------------------- #


def test_the_old_predicate_passes_the_exact_case_the_new_one_catches(scenario) -> None:
    """AC8: over ONE scenario, old says PASS and new says FAIL.

    The scenario is E3's top-left cell, built rather than waited for:

      1. a sibling is alive at the first sample;
      2. between the samples this invocation leaks **one** orphan into its own
         group, and the sibling **exits**;
      3. the second sample is taken.

    ``after == before`` -- so the machine-wide count is satisfied while an
    orphan is sitting there. That is *"it cannot detect the defect it was
    written for even when it is green"*, made mechanical.
    """
    sibling = scenario.spawn_group(f"sleep {SURVIVOR_LIFETIME_S}")
    sibling_pgid = sibling.pid
    assert _group_alive(sibling_pgid), "the sibling was not alive at the first sample"

    # SAMPLE 1 -- the population is the sibling; our orphan does not exist yet.
    before = scenario.alive_count([sibling_pgid])

    # Between the samples: we leak exactly one orphan, and the sibling exits.
    our_pgid = scenario.leak_a_survivor_into_its_own_group()
    assert scenario.kill_group(sibling) is not None, (
        "the sibling did not exit between the samples, so this is not the "
        "top-left cell and the disagreement below would prove nothing"
    )

    # SAMPLE 2 -- our orphan is alive, the sibling is gone.
    after = scenario.alive_count([sibling_pgid, our_pgid])

    assert (before, after) == (1, 1), (
        f"the scenario did not reproduce `after == before` (before={before}, "
        f"after={after}); without that equality the old predicate is not being "
        "shown its blind spot"
    )

    old_verdict = _old_predicate(before, after)
    new_verdict = _new_predicate(our_pgid)

    assert old_verdict is True, (
        "the OLD predicate was supposed to pass this case -- that is the whole "
        f"defect (before={before}, after={after})"
    )
    assert new_verdict is False, (
        f"the NEW predicate missed an orphan in our own group {our_pgid}; the "
        "replacement is symmetric too, and the item is not discharged"
    )
    assert old_verdict != new_verdict, (
        "the two predicates AGREE, so the asymmetry this spec exists to deliver is not present"
    )


def test_the_two_predicates_agree_when_there_is_nothing_to_disagree_about(
    scenario,
) -> None:
    """The disagreement above must be caused by the orphan, not by the two
    predicates simply always differing.

    Same shape, minus the leak: no orphan in our group, sibling still exits
    between the samples. Both predicates must now say PASS. A control whose
    'disagreement' fired on every input would prove nothing at all.
    """
    sibling = scenario.spawn_group(f"sleep {SURVIVOR_LIFETIME_S}")
    sibling_pgid = sibling.pid
    before = scenario.alive_count([sibling_pgid])

    clean = scenario.spawn_group("exit 0")
    our_pgid = clean.pid
    clean.wait(timeout=GROUP_REAP_DEADLINE_S)
    assert _wait_group_gone(our_pgid) is not None, "our own group did not go away"

    assert scenario.kill_group(sibling) is not None

    after = scenario.alive_count([sibling_pgid, our_pgid])

    assert _old_predicate(before, after) is True
    assert _new_predicate(our_pgid) is True


# --------------------------------------------------------------------------- #
# AC9 -- INVARIANCE under sibling noise, asserted directly.
# --------------------------------------------------------------------------- #


def _machine_wide_flavoured_predicate(our_pgid: int, population: list[int]) -> bool:
    """A predicate with a machine-wide term put back in, kept ONLY so AC9's
    invariance arm can be shown to be discriminating.

    If the invariance arm passed for both this and the real predicate, it would
    be asserting nothing. It does not: this one's verdict moves with a
    sibling, and that is demonstrated rather than claimed.
    """
    return not _group_alive(our_pgid) and sum(1 for pgid in population if _group_alive(pgid)) == 0


@pytest.mark.parametrize("leak", [True, False])
def test_the_new_predicates_verdict_does_not_move_with_sibling_noise(scenario, leak: bool) -> None:
    """AC9: with a sibling starting AND exiting between the samples, the new
    predicate's verdict is unchanged -- in BOTH the survivor and the
    no-survivor scenario.

    This is the property whose absence produced `face1c63a0`'s 6/6, asserted
    directly rather than inferred from a run that happened to be green.
    """
    if leak:
        our_pgid = scenario.leak_a_survivor_into_its_own_group()
    else:
        clean = scenario.spawn_group("exit 0")
        our_pgid = clean.pid
        clean.wait(timeout=GROUP_REAP_DEADLINE_S)
        assert _wait_group_gone(our_pgid) is not None

    quiet_verdict = _new_predicate(our_pgid)

    # Sibling noise: one starts and one exits between the observations.
    starting = scenario.spawn_group(f"sleep {SURVIVOR_LIFETIME_S}")
    exiting = scenario.spawn_group(f"sleep {SURVIVOR_LIFETIME_S}")
    assert scenario.kill_group(exiting) is not None

    noisy_verdict = _new_predicate(our_pgid)

    assert noisy_verdict == quiet_verdict, (
        f"the new predicate's verdict moved from {quiet_verdict} to "
        f"{noisy_verdict} because a SIBLING changed. A machine-wide term is "
        "back in the predicate, and the instrument is symmetric again"
    )
    assert quiet_verdict is not leak, (
        "the verdict does not reflect our own group's actual state, so its "
        "invariance above is vacuous"
    )

    # And the invariance is discriminating: a predicate WITH a machine-wide
    # term does move, over the very same processes.
    population = [starting.pid, exiting.pid]
    assert _machine_wide_flavoured_predicate(our_pgid, population) is False, (
        "the machine-wide-flavoured control did not move with the sibling, so "
        "the invariance assertion above proves nothing"
    )


# --------------------------------------------------------------------------- #
# AC10 -- the `pgid == pid` premise, PROVEN once against a child we own.
# --------------------------------------------------------------------------- #


def test_start_new_session_really_does_make_the_child_its_own_group_leader(
    scenario,
) -> None:
    """AC10: ``os.getpgid(pid) == pid`` for a ``start_new_session=True`` spawn.

    The premise is **observed**, not quoted from `subprocess_util.py:333-337`'s
    source comment. The child is held alive by its own ``sleep`` for the
    duration of the check, so there is no race between the spawn and the
    question -- which is precisely why this lives here and not in the office
    test, where the fast ``--version`` probe's exit would race it.
    """
    proc = scenario.spawn_group(f"sleep {SURVIVOR_LIFETIME_S}")

    assert os.getpgid(proc.pid) == proc.pid, (
        "start_new_session=True did not yield pgid == pid; the premise the "
        "whole probe rests on is gone"
    )


def test_without_start_new_session_the_premise_does_not_hold(scenario) -> None:
    """The complement, so AC10's arm is shown to be discriminating.

    A child spawned WITHOUT ``start_new_session`` inherits this interpreter's
    process group, so ``pgid == pid`` is false and ``pgid`` is ours. If this
    ever passed, the arm above would be satisfied by any spawn at all.
    """
    proc = subprocess.Popen(  # noqa: S603 - fixed argv
        ["sh", "-c", f"sleep {SURVIVOR_LIFETIME_S}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert os.getpgid(proc.pid) != proc.pid, (
            "a child spawned WITHOUT start_new_session became its own group "
            "leader; the two arms cannot tell the premise apart"
        )
        assert os.getpgid(proc.pid) == os.getpgid(0), (
            "the child is not in this interpreter's group either, so the "
            "complement is not the case it claims to be"
        )
    finally:
        proc.kill()
        proc.wait(timeout=GROUP_REAP_DEADLINE_S)


# --------------------------------------------------------------------------- #
# AC7 -- the recorder's PRECONDITION can actually fire.
# --------------------------------------------------------------------------- #


class _SpawnRecorder:
    """`test_office.py`'s recorder, restated here so its guard has a control.

    Restated rather than imported for the same reason ``_group_alive`` is (see
    the module docstring), and because importing one ``test_*`` module from
    another gives pytest two module objects for one file.
    """

    def __init__(self, real: object, sink: list[int]) -> None:
        self._real = real
        self._sink = sink

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)

    def Popen(self, *args: object, **kwargs: object) -> object:  # noqa: N802
        assert kwargs.get("start_new_session") is True, (
            "subprocess_util.run no longer starts a new session; the "
            "pgid == pid premise this probe rests on is gone"
        )
        proc = self._real.Popen(*args, **kwargs)
        self._sink.append(proc.pid)
        return proc


def test_the_recorder_refuses_a_spawn_that_lost_the_session_premise() -> None:
    """AC7's guard, driven: a spawn without ``start_new_session=True`` fails
    LOUDLY, naming the lost premise, instead of the probe silently measuring
    the wrong process group.

    This is the difference between an instrument that breaks and one that lies.
    """
    sink: list[int] = []
    recorder = _SpawnRecorder(subprocess, sink)

    with pytest.raises(AssertionError, match="no longer starts a new session"):
        recorder.Popen(["sh", "-c", "exit 0"])

    assert sink == [], "a refused spawn must not be recorded"


def test_the_recorder_passes_through_and_records_a_conforming_spawn(scenario) -> None:
    """The complement: a conforming spawn is delegated untouched and its pid --
    which IS its pgid, by the premise above -- is recorded."""
    sink: list[int] = []
    recorder = _SpawnRecorder(subprocess, sink)

    proc = recorder.Popen(
        ["sh", "-c", f"sleep {SURVIVOR_LIFETIME_S}"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    scenario.adopt(proc)

    assert sink == [proc.pid]
    assert os.getpgid(proc.pid) == proc.pid
    assert recorder.DEVNULL is subprocess.DEVNULL, "delegation through __getattr__ broke"


# --------------------------------------------------------------------------- #
# AC11 -- the settle window is a BOUNDED POLL, and its failure names the time.
# --------------------------------------------------------------------------- #


def _wait_for_groups_to_settle(pgids: list[int], deadline_s: float) -> tuple[list[int], float, int]:
    """`test_office.py`'s settle window, restated for its own control.

    Returns ``(survivors, elapsed, polls)``. It returns AS SOON AS the groups
    are empty, so on a quiet host it is faster than the fixed
    ``time.sleep(1.0)`` it replaces; under contention it stops failing merely
    because 1.0 s was not enough.

    ``polls`` is returned so the "as soon as" half can be asserted by COUNTING
    rather than by a wall-clock budget. A budget would be a threshold with no
    stated host precondition sampled once -- which is `B-146`'s exact shape, on
    the same contended hosts, in the suite this docket is about. Writing one
    here to prove a de-flaking change would be self-defeating.
    """
    started = time.monotonic()
    polls = 0
    while True:
        survivors = [pgid for pgid in pgids if _group_alive(pgid)]
        polls += 1
        elapsed = time.monotonic() - started
        if not survivors or elapsed >= deadline_s:
            return survivors, elapsed, polls
        time.sleep(0.02)


def test_the_settle_poll_returns_as_soon_as_the_group_is_empty(scenario) -> None:
    """AC11: the poll is not a sleep. An already-empty group returns promptly
    rather than costing the full deadline."""
    proc = scenario.spawn_group("exit 0")
    proc.wait(timeout=GROUP_REAP_DEADLINE_S)
    assert _wait_group_gone(proc.pid) is not None

    survivors, elapsed, polls = _wait_for_groups_to_settle([proc.pid], deadline_s=5.0)

    assert survivors == []
    assert polls == 1, (
        f"an empty group cost {polls} polls; the probe is sleeping before it "
        "looks, which is the fixed-sleep behaviour this replaced"
    )
    # `elapsed` is REPORTED, never asserted against a budget -- see the helper.
    assert elapsed < 5.0, f"the poll ran to its own deadline on an empty group ({elapsed:.3f}s)"


def test_the_settle_poll_fails_at_the_deadline_naming_the_elapsed_time(
    scenario,
) -> None:
    """AC11's RED, as a standing arm: a process held alive in the probed group
    past the deadline is reported, with the elapsed time and the surviving
    group in the message.

    The deadline is small HERE because this arm exists to observe the timeout
    path. It is not the office arm's deadline and may not be read as a budget.
    """
    our_pgid = scenario.leak_a_survivor_into_its_own_group()

    survivors, elapsed, _polls = _wait_for_groups_to_settle([our_pgid], deadline_s=0.5)

    assert survivors == [our_pgid], (
        "a survivor held alive past the deadline was not reported; the poll "
        "returns clean on a group that still holds a process"
    )
    assert elapsed >= 0.5, f"the poll gave up after {elapsed:.3f}s, before its own deadline"


def test_the_scenario_leaves_nothing_behind(scenario) -> None:
    """The instrument must not become the thing it detects.

    Every group this module creates is recorded and killed in teardown. This
    arm proves the teardown works on a group that is still live at the moment
    it runs, so a failing arm above cannot leak a 45-second sleeper per run.
    """
    local = _Scenario()
    pgid = local.leak_a_survivor_into_its_own_group()
    assert _group_alive(pgid)

    local.close()

    assert not _group_alive(pgid), (
        f"group {pgid} survived the scenario's own teardown; this module leaks"
    )


# --------------------------------------------------------------------------- #
# AC6 -- the machine-wide count cannot creep back in, under any spelling.
# --------------------------------------------------------------------------- #

#: Every way this suite could reach for a machine-wide process census again.
#: `pgrep` is the one that was actually there; the rest are named so the guard
#: is about the CLASS rather than about one binary, because "fixed by switching
#: to `ps`" would be the same defect with a different argv.
PROCESS_SCANNERS: Final = ("pgrep", "pkill", "pidof", "ps -e", '"ps"', "'ps'")

OFFICE_TEST = Path(__file__).with_name("test_office.py")


def test_the_office_arm_names_no_process_scanning_binary() -> None:
    """AC6: `test_office.py` no longer reads a machine-wide process count.

    A source-level guard, deliberately. The behavioural arms above prove the
    NEW predicate is asymmetric; this one proves the OLD one did not survive
    somewhere in the same file, which no behavioural arm can see. It fails the
    moment a machine-wide count is reintroduced -- including in a comment,
    because the previous instrument was defended by its comment for as long as
    it existed.
    """
    source = OFFICE_TEST.read_text(encoding="utf-8")

    found = sorted({scanner for scanner in PROCESS_SCANNERS if scanner in source})

    assert not found, (
        f"{OFFICE_TEST.name} names {found}; the machine-wide process count that "
        "made this instrument symmetric (`face1c63a0`) is back. The question it "
        "must ask is 'does anything remain in the group THIS invocation "
        "created', which no process scan can answer"
    )


def test_that_guard_can_actually_fire() -> None:
    """A control that cannot fail is not a control, and this spec exists
    because one of those shipped. The predicate is re-run over a string that
    DOES contain a scanner, and must find it."""
    poisoned = 'out = subprocess.run(["pgrep", "-fc", "soffice.bin"])'

    found = sorted({scanner for scanner in PROCESS_SCANNERS if scanner in poisoned})

    assert found == ["pgrep"], f"the AC6 predicate is blind to the exact retired call: {found}"
