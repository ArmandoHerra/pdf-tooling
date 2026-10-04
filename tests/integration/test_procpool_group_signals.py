"""A signal delivered to the WHOLE process group unwinds every render worker's open
writer (PDF-101, ledger ``88fae0dff3``, carrier ``B-379``).

**The defect.** A terminal Ctrl-C signals the whole foreground process group, so a
``rasterize`` render worker receives SIGINT directly. Before PDF-101 the worker's
SIGINT and SIGHUP were reset to ``SIG_DFL``, so a worker holding an open
``AtomicWriter`` died on the spot and its temp file stayed beside the outputs.

**Why this file is the suite's instrument and a real-CLI arm is not.** A real
``rasterize`` worker can be inside pdfium or Pillow when the signal lands, and then
the outcome is governed by ``TEARDOWN_GRACE_S``: that is the best-effort class
``ops/procpool.py`` names. Here every worker is parked in PURE PYTHON
(``time.sleep(0.01)`` in a loop), so CPython delivers the signal at the next
bytecode boundary and the result does not depend on load. The real CLI is proved by
a driven pre/post measurement recorded with the spec, not by a standing arm.

**How it is deterministic rather than lucky.**

- The test signals ONLY after every worker has written its ready marker, and each
  marker is written after ``AtomicWriter.__enter__`` created the temp, so "every
  worker holds an open writer" is observed, not hoped for.
- No ``sleep`` decides when to signal. Marker polling is bounded and a timeout is a
  ``pytest.fail``, never a skip.
- ``os.killpg`` targets the driver's OWN session (``start_new_session=True``), so a
  group signal never reaches pytest or a sibling xdist worker.
- The residue is read through ``find_stray_temps``, never a spelled-out prefix: a
  guard that names the prefix to forbid it is how a frozen population grows.

``N`` repeats a deterministic property; it does not sample a distribution.

**Marker.** None. ``pyproject.toml``'s marker list is closed (``--strict-markers``),
and ``e2e`` is defined as "runs the installed console script as a subprocess" -- this
module runs ``sys.executable`` on an embedded driver, which is the precedent
``test_render_pool_start_method.py`` set and documents.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from pdf_tooling.safety.tempnames import find_stray_temps

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="os.killpg and SIGHUP are POSIX-only; this product ships no Windows job",
)

_K = 4  # workers per trial
_READY_TIMEOUT_S = 60.0
#: A worker that has unwound must be GONE well inside this. It is less than a third of
#: `TEARDOWN_GRACE_S`, so a worker held to the grace reds the arm.
_EXIT_WITHIN_S = 5.0
_DRIVER_EXIT_TIMEOUT_S = 60.0
_GROUP_POLL_S = 5.0

_DRIVER = """\
import faulthandler, json, os, signal, sys, time
faulthandler.dump_traceback_later(40, exit=True)
from pathlib import Path

from pdf_tooling.ops import procpool
from pdf_tooling.safety import AtomicWriter, SafetyPolicy

SCRATCH = Path(sys.argv[1])
OUT = SCRATCH / "out"
MARKS = SCRATCH / "marks"
K = int(sys.argv[2])
MODE = sys.argv[3]


def _policy():
    return SafetyPolicy(
        dry_run=False, force=False, in_place=False, backup=True,
        assume_yes=False, is_tty=False, threads=1,
    )


def _mark(name, payload):
    # Written whole under a temp name and renamed in, so a reader that sees the marker
    # sees its content. O_EXCL: a marker is only ever created once.
    tmp = MARKS / (name + ".tmp")
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(payload).encode())
    finally:
        os.close(fd)
    os.rename(str(tmp), str(MARKS / name))


def park(i):
    with AtomicWriter(OUT / ("out-%d.bin" % i), policy=_policy(), kind="image") as w:
        w.stream.write(b"partial bytes")
        _mark("ready-%d" % i, os.getpid())
        while True:
            time.sleep(0.01)


def rendezvous(i):
    _mark("idle-%d" % i, os.getpid())
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if all((MARKS / ("idle-%d" % j)).exists() for j in range(K)):
            return os.getpid()
        time.sleep(0.01)
    raise RuntimeError("rendezvous timed out")


def _wait_workers_gone(procs):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if all(not p.is_alive() for p in procs):
            return
        time.sleep(0.005)


def main():
    OUT.mkdir(exist_ok=True)
    MARKS.mkdir(exist_ok=True)
    if MODE == "full-stack":
        with procpool.guarded_process_pool(K) as ex:
            futs = [ex.submit(park, i) for i in range(K)]
            for f in futs:
                f.result(timeout=120)
        return
    # The driver records the three signals with a Python handler. Never SIG_IGN:
    # that would survive exec into a worker.
    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        signal.signal(getattr(signal, name), lambda s, f: None)
    ex = procpool._GuardedExecutor(
        max_workers=K, mp_context=procpool._mp_context(),
        initializer=procpool._worker_initializer,
    )
    if MODE == "guarded-executor":
        futs = [ex.submit(park, i) for i in range(K)]
        procs = list(ex._processes.values())
    else:
        futs = [ex.submit(rendezvous, i) for i in range(K)]
        for f in futs:
            f.result(timeout=60)
        procs = list(ex._processes.values())
        _mark("idle", "1")
    _wait_workers_gone(procs)
    (SCRATCH / "exitcodes.json").write_text(json.dumps([p.exitcode for p in procs]))
    ex.shutdown(wait=False, cancel_futures=True)
    os._exit(0)


if __name__ == "__main__":
    main()
"""


def _ps_group_members(pgid: int) -> tuple[int, ...]:
    """Non-zombie members of *pgid* from ``ps -A -o pid=,pgid=,stat=`` (the portable census)."""
    out = subprocess.run(
        ["ps", "-A", "-o", "pid=,pgid=,stat="], capture_output=True, text=True, check=True
    ).stdout
    members: list[int] = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            pid, grp = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if grp == pgid and not parts[2].startswith("Z"):
            members.append(pid)
    return tuple(members)


def _live_group_members_killpg(pgid: int) -> tuple[int, ...]:
    """Non-/proc path. macOS answers EPERM to ``killpg(pgid, 0)`` when the group holds only
    zombies or other non-signalable members, so EPERM is NOT "no survivors": fall back to an
    independent ``ps`` census of the non-zombie members, which preserves the survivor check."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return ()
    except PermissionError:
        return _ps_group_members(pgid)
    return (pgid,)


def _live_group_members(pgid: int) -> tuple[int, ...]:
    """Non-zombie members of process group *pgid*; ``/proc`` on Linux, ``killpg`` elsewhere."""
    procfs = Path("/proc")
    if not procfs.is_dir():  # pragma: no cover - macOS: no /proc, so killpg(pgid, 0)
        return _live_group_members_killpg(pgid)
    members: list[int] = []
    for entry in procfs.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            fields = stat[stat.rindex(")") + 2 :].split()
            state, pgrp = fields[0], int(fields[2])
        except (OSError, ValueError, IndexError):  # pragma: no cover - raced an exit
            continue
        if pgrp == pgid and state != "Z":
            members.append(int(entry.name))
    return tuple(members)


def _wait_until_blocked(pids: list[int]) -> None:
    """Wait until every worker is parked in a blocking kernel call (Linux ``wchan``).

    The driver writes its idle marker the moment the last RESULT arrives, but a worker is
    still running the stdlib's post-task bookkeeping for a few microseconds after it has
    sent that result. `concurrent.futures.process` wraps that bookkeeping in
    ``except BaseException``, so a signal landing in that window has its unwind swallowed
    and the worker idles on with the signals absorbed (about 1 trial in 600 under a
    saturated host). "Idle" must be observed, not assumed: a worker that is parked in
    ``call_queue.get()`` is blocked in the kernel (a pipe read or a futex wait). Where
    ``/proc/<pid>/wchan`` does not exist (macOS) this returns at once.
    """
    deadline = time.monotonic() + _READY_TIMEOUT_S
    for pid in pids:
        wchan = Path(f"/proc/{pid}/wchan")
        while time.monotonic() < deadline:
            try:
                state = wchan.read_text().strip()
            except OSError:  # pragma: no cover - no /proc (macOS) or the pid is gone
                break
            if state not in ("", "0"):
                break
            time.sleep(0.005)


def _pid_gone(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return True
    except OSError:  # pragma: no cover - /proc unreadable, fall through to kill(0)
        pass
    else:
        return stat[stat.rindex(")") + 2 :].split()[0] == "Z"
    try:  # pragma: no cover - macOS: no /proc
        os.kill(pid, 0)
    except ProcessLookupError:  # pragma: no cover
        return True
    return False  # pragma: no cover


def _untraced_env() -> dict[str, str]:
    """The environment for the driver, with coverage's subprocess hook removed.

    `make cover` turns on ``patch = ["subprocess"]``, which would trace the driver and
    every spawned worker. A signal handler that raises can land INSIDE coverage's own
    tracer callback while it holds its non-reentrant lock, and the next callback on that
    thread then deadlocks (measured: about 40% of the double-signal trials hung under
    `make cover`, with the parked worker's stack inside ``coverage.collector.lock_data``,
    and none without it). The product has no tracer, and coverage cannot see into these
    workers usefully anyway, so the instrument runs untraced.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("COVERAGE_")}


@dataclass
class Trial:
    mode: str
    signame: str
    returncode: int | None = None
    strays: tuple[Path, ...] = ()
    committed: int = 0
    pids: list[int] = field(default_factory=list)
    alive_after_window: list[int] = field(default_factory=list)
    exit_seconds: float = 0.0
    tracebacks: int = 0
    group_survivors: tuple[int, ...] = ()
    exitcodes: list[int | None] = field(default_factory=list)

    def describe(self) -> str:
        return (
            f"{self.mode}/{self.signame}: rc={self.returncode} strays={len(self.strays)} "
            f"committed={self.committed} workers={len(self.pids)} "
            f"exitcodes={self.exitcodes} alive@{_EXIT_WITHIN_S}s={self.alive_after_window} "
            f"tracebacks={self.tracebacks} "
            f"group_survivors={self.group_survivors} exit_s={self.exit_seconds:.2f}"
        )


def _wait_for(paths: list[Path], proc: subprocess.Popen[bytes], what: str) -> None:
    deadline = time.monotonic() + _READY_TIMEOUT_S
    while time.monotonic() < deadline:
        if all(p.exists() for p in paths):
            return
        if proc.poll() is not None:
            pytest.fail(f"driver exited rc={proc.returncode} before {what}")
        time.sleep(0.02)
    pytest.fail(f"timed out after {_READY_TIMEOUT_S}s waiting for {what}")


def _run_trial(
    tmp_path: Path, index: int, mode: str, sig: signal.Signals, *, then_term: bool = False
) -> Trial:
    scratch = tmp_path / f"trial-{index}"
    scratch.mkdir()
    driver = scratch / "driver.py"
    driver.write_text(_DRIVER)
    errfile = scratch / "driver.err"
    trial = Trial(mode=mode, signame=sig.name)
    with errfile.open("wb") as err:
        proc = subprocess.Popen(
            [sys.executable, str(driver), str(scratch), str(_K), mode],
            stdout=subprocess.DEVNULL,
            stderr=err,
            start_new_session=True,
            env=_untraced_env(),
        )
    pgid = proc.pid
    try:
        marks = scratch / "marks"
        if mode == "idle":
            _wait_for([marks / "idle"], proc, "the idle marker")
            pid_files = [marks / f"idle-{i}" for i in range(_K)]
        else:
            pid_files = [marks / f"ready-{i}" for i in range(_K)]
            _wait_for(pid_files, proc, "every worker's ready marker")
        trial.pids = [int(p.read_text()) for p in pid_files]
        if mode == "idle":
            _wait_until_blocked(trial.pids)
        signalled_at = time.monotonic()
        os.killpg(pgid, sig)
        if then_term:
            for pid in trial.pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        if mode != "full-stack":
            deadline = signalled_at + _EXIT_WITHIN_S
            pending = list(trial.pids)
            while pending and time.monotonic() < deadline:
                pending = [pid for pid in pending if not _pid_gone(pid)]
                if pending:
                    time.sleep(0.01)
            trial.exit_seconds = time.monotonic() - signalled_at
            trial.alive_after_window = pending
        try:
            trial.returncode = proc.wait(timeout=_DRIVER_EXIT_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            pytest.fail(
                "the driver did not exit after the signal:\n" + errfile.read_text(errors="replace")
            )
        if mode == "full-stack":
            trial.exit_seconds = time.monotonic() - signalled_at
        deadline = time.monotonic() + _GROUP_POLL_S
        survivors = _live_group_members(pgid)
        while survivors and time.monotonic() < deadline:
            time.sleep(0.05)
            survivors = _live_group_members(pgid)
        trial.group_survivors = survivors
    finally:
        try:
            os.killpg(pgid, signal.SIGKILL)  # only ever our own session
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()
    out = scratch / "out"
    codes = scratch / "exitcodes.json"
    if codes.exists():
        trial.exitcodes = json.loads(codes.read_text())
    trial.strays = find_stray_temps(out)
    trial.committed = len(list(out.glob("out-*.bin")))
    trial.tracebacks = sum(
        1
        for line in errfile.read_text(errors="replace").splitlines()
        if line.startswith("Traceback")
    )
    return trial


def _run_arm(
    tmp_path: Path, n: int, mode: str, sig: signal.Signals, *, then_term: bool = False
) -> list[Trial]:
    return [_run_trial(tmp_path, i, mode, sig, then_term=then_term) for i in range(n)]


def _assert_unwound(trials: list[Trial], sig: signal.Signals) -> None:
    table = "\n".join(t.describe() for t in trials)
    for t in trials:
        assert t.strays == (), f"residue left behind:\n{table}"
        assert t.committed == 0, f"a parked writer committed:\n{table}"
        assert len(t.pids) == _K, table
        assert t.alive_after_window == [], f"a worker outlived {_EXIT_WITHIN_S}s:\n{table}"
        # The worker ends itself with the shell convention for the signal that started
        # its unwind (not `-N`, which is what a worker killed by the signal reports). A
        # worker the group signal has not reached yet can instead be reached first by the
        # SIGTERM the driver's executor sends when it sees the first worker leave, so 143
        # is the one other honest status.
        assert set(t.exitcodes) <= {128 + sig, 128 + signal.SIGTERM}, (
            f"a worker did not exit by its own unwind:\n{table}"
        )
        assert len(t.exitcodes) == _K, table


def test_ac1_group_sigint_unwinds_every_open_writer(tmp_path: Path) -> None:
    _assert_unwound(_run_arm(tmp_path, 5, "guarded-executor", signal.SIGINT), signal.SIGINT)


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="no SIGHUP on this platform")
def test_ac2_group_sighup_unwinds_every_open_writer(tmp_path: Path) -> None:
    # Driver stderr is deliberately not asserted: the multiprocessing resource tracker
    # does not ignore SIGHUP and prints its own noise (handed up, not this item's).
    _assert_unwound(_run_arm(tmp_path, 3, "guarded-executor", signal.SIGHUP), signal.SIGHUP)


def test_ac3_group_sigterm_is_the_harness_validity_control(tmp_path: Path) -> None:
    _assert_unwound(_run_arm(tmp_path, 2, "guarded-executor", signal.SIGTERM), signal.SIGTERM)


def test_ac4_a_following_sigterm_cannot_break_the_unwind(tmp_path: Path) -> None:
    trials = _run_arm(tmp_path, 5, "guarded-executor", signal.SIGINT, then_term=True)
    table = "\n".join(t.describe() for t in trials)
    for t in trials:
        assert t.strays == (), f"the parent's follow-up SIGTERM broke an unwind:\n{table}"
        assert t.alive_after_window == [], table


def test_ac7_an_idle_worker_exits_quietly_on_a_group_sigint(tmp_path: Path) -> None:
    trials = _run_arm(tmp_path, 2, "idle", signal.SIGINT)
    table = "\n".join(t.describe() for t in trials)
    for t in trials:
        assert len(t.pids) == _K, table
        assert t.alive_after_window == [], f"an idle worker outlived {_EXIT_WITHIN_S}s:\n{table}"
        assert t.tracebacks == 0, f"an idle worker printed a traceback:\n{table}"
        # An idle worker unwinds outside any task, as a quiet SystemExit whose status
        # matches the task path (where a worker killed by the signal reports -2). The
        # first worker to exit makes the driver's executor SIGTERM the rest, and a
        # worker already finalizing its interpreter has had its handlers reset to the
        # default by then, so -15 is the one other honest status for a worker that
        # holds no writer. At least one worker must have exited by its own unwind.
        assert set(t.exitcodes) <= {128 + signal.SIGINT, -signal.SIGTERM}, (
            f"idle exit status:\n{table}"
        )
        assert 128 + signal.SIGINT in t.exitcodes, f"no idle worker unwound by itself:\n{table}"


def test_ac8_full_stack_the_parent_dies_by_sigint_with_no_residue(tmp_path: Path) -> None:
    (trial,) = _run_arm(tmp_path, 1, "full-stack", signal.SIGINT)
    assert trial.returncode == -signal.SIGINT, trial.describe()
    assert trial.strays == (), trial.describe()
    assert trial.group_survivors == (), trial.describe()


def test_killpg_eperm_fallback_still_reports_a_live_member(monkeypatch):
    """Red control for the macOS EPERM branch: a live group member must survive the fallback.

    Fails against a naive ``except PermissionError: return ()`` (the live pid would vanish).
    """

    def eperm(*_a):
        raise PermissionError(1, "Operation not permitted")

    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True
    )
    try:
        pgid = os.getpgid(child.pid)
        monkeypatch.setattr(os, "killpg", eperm)
        assert _live_group_members_killpg(pgid) == (child.pid,)
    finally:
        monkeypatch.undo()
        child.kill()
        child.wait()
    # Group now holds only a reaped/dead child: the census is empty.
    monkeypatch.setattr(os, "killpg", eperm)
    assert _live_group_members_killpg(pgid) == ()
