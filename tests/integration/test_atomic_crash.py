"""A real ``SIGKILL``, delivered to a process provably parked mid-write.

This is the arm that decides whether "every write is atomic" is a claim or a
fact, so it is built to remove every way of being accidentally right:

* **the signal is real.** ``signal.SIGKILL`` cannot be caught, blocked or
  handled. There is no unwind, no ``finally``, no ``__exit__`` and no cleanup —
  which is the entire scenario. A mocked failure would test the mock; a caught
  exception would test the exception handler, which is a different guarantee
  that the writer also has and that other tests already cover.
* **the timing is not timing.** The child announces its arrival at the named
  point over an inherited pipe and then blocks. When the parent reads that byte
  the child is *provably* parked there. No ``sleep``, no polling, no
  "usually fast enough".
* **the assertion is bytes.** SHA-256 and size of the original, before and
  after. Not "the file still exists".

Both shapes are covered, because they are the same code path and it is worth
proving that: a fresh output, where the destination must simply never appear,
and ``--in-place``, where the destination is the input and must come through
byte-identical. Residue is expected and allowed — ``PLAN.md`` §12 R-07 decided to
report stray temps rather than sweep them — so the check is "nothing changed
except a toolkit temp appearing", not "nothing changed".
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import select
import signal
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from pdf_toolkit.safety import TEMP_PREFIX, is_toolkit_temp
from pdf_toolkit.safety._faults import ENV_POINT, ENV_RENDEZVOUS, FAULT_POINTS

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from atomic_harness import REPO_ROOT  # noqa: E402
from fs_snapshot import Snapshot, diff, snapshot  # noqa: E402

RENDEZVOUS_TIMEOUT = 30.0
ORIGINAL = b"the original bytes, which must survive a kill -9\n"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class Parked:
    """A child process stopped at a named point inside the write."""

    detail: str
    process: subprocess.Popen[str]
    release_fd: int

    def kill(self) -> int:
        os.kill(self.process.pid, signal.SIGKILL)
        return self.process.wait(timeout=20)

    def release(self) -> int:
        os.write(self.release_fd, b"\x01")
        return self.process.wait(timeout=20)


def _read_announcement(fd: int, process: subprocess.Popen[str]) -> str:
    buffer = b""
    while b"\n" not in buffer:
        ready, _, _ = select.select([fd], [], [], RENDEZVOUS_TIMEOUT)
        if not ready:
            process.kill()
            raise AssertionError("the child never reached the fault point within the deadline")
        chunk = os.read(fd, 4096)
        if not chunk:
            code = process.poll()
            _, stderr = process.communicate(timeout=10)
            raise AssertionError(
                f"the child exited (code {code}) before reaching the fault point:\n{stderr}"
            )
        buffer += chunk
    return buffer.split(b"\n", 1)[0].decode()


@contextlib.contextmanager
def park_at(point: str, args: Sequence[str]) -> Iterator[Parked]:
    """Run the harness and stop it, provably, at *point*."""
    ready_read, ready_write = os.pipe()
    release_read, release_write = os.pipe()
    environment = dict(os.environ)
    environment[ENV_POINT] = point
    environment[ENV_RENDEZVOUS] = f"{ready_write}:{release_read}"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", "tests.atomic_harness", *args],
        cwd=str(REPO_ROOT),
        env=environment,
        pass_fds=(ready_write, release_read),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # The parent's copies must go, or a dead child would never produce an EOF
    # on the ready pipe and the read below would block for the full deadline.
    os.close(ready_write)
    os.close(release_read)
    try:
        yield Parked(_read_announcement(ready_read, process), process, release_write)
    finally:
        os.close(ready_read)
        os.close(release_write)  # closing releases a child that is still parked
        if process.poll() is None:  # pragma: no cover - only on an arm that failed
            process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=20)


def assert_only_temp_residue(before: Snapshot, after: Snapshot) -> None:
    """A hard kill may leave a toolkit temp. It may leave nothing else.

    A directory's own ``mtime`` — and, on APFS, its ``st_size`` — move as a
    direct consequence of the temp entry that was just tolerated. They are the
    same fact reported a second time, not a change to anything a user owns, so
    they are tolerated *on directories only*. This is a crash-arm helper and
    deliberately not part of the purity comparator, which still reports both.
    """
    for item in diff(before, after):
        if item.kind == "added" and is_toolkit_temp(item.path):
            continue
        if item.kind in {"mtime", "size"} and Path(item.path).is_dir():
            continue
        raise AssertionError(f"a kill changed more than the temp namespace: {item}")


# --------------------------------------------------------------------------- #
# AC7 — where the temp actually is, read while the writer holds it
# --------------------------------------------------------------------------- #


def test_the_live_temp_sits_beside_the_destination(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    with park_at("after_temp_create", ["write", "--target", str(target)]) as parked:
        temp = Path(parked.detail)
        assert temp.exists()
        assert temp.parent == target.parent.resolve()
        assert temp.parent != Path(tempfile.gettempdir()).resolve()
        assert temp.name.startswith(TEMP_PREFIX)
        assert parked.release() == 0
    assert target.exists()


def test_every_declared_fault_point_is_reachable(tmp_path: Path) -> None:
    """A point the writer never calls would make its arm silently vacuous."""
    for index, point in enumerate(FAULT_POINTS):
        target = tmp_path / f"doc{index}.pdf"
        target.write_bytes(ORIGINAL)
        args = ["--in-place", "write", "--target", str(target), "--content", "rewritten"]
        with park_at(point, args) as parked:
            assert parked.detail
            assert parked.release() == 0


# --------------------------------------------------------------------------- #
# AC8 — the plan's acceptance signal (b)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("point", FAULT_POINTS)
def test_a_kill_never_creates_a_fresh_target(point: str, tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    witness = work / "input.pdf"
    witness.write_bytes(ORIGINAL)
    witness_before = sha256(witness)
    target = work / "doc.pdf"

    before = snapshot(work)
    with park_at(point, ["write", "--target", str(target), "--content", "new bytes"]) as parked:
        assert parked.kill() == -signal.SIGKILL
    after = snapshot(work)

    assert not target.exists(), "the destination appeared despite the kill"
    assert sha256(witness) == witness_before
    assert_only_temp_residue(before, after)


@pytest.mark.parametrize("point", FAULT_POINTS)
def test_a_kill_leaves_an_in_place_target_byte_identical(point: str, tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    target = work / "doc.pdf"
    target.write_bytes(ORIGINAL)
    before_digest = sha256(target)
    before_size = target.stat().st_size

    before = snapshot(work)
    args = ["--in-place", "write", "--target", str(target), "--content", "rewritten bytes"]
    with park_at(point, args) as parked:
        assert parked.kill() == -signal.SIGKILL
    after = snapshot(work)

    assert sha256(target) == before_digest
    assert target.stat().st_size == before_size

    sidecar = work / "doc.pdf.bak"
    if point == "after_backup":
        assert sidecar.exists(), "step 5 completed, so the sidecar must be there"
        assert sha256(sidecar) == before_digest
    else:
        assert not sidecar.exists()
        assert_only_temp_residue(before, after)


@pytest.mark.parametrize("point", FAULT_POINTS)
def test_residue_is_reported_rather_than_swept(point: str, tmp_path: Path) -> None:
    """PLAN §12 R-07 in its natural habitat: what a kill actually leaves behind."""
    from pdf_toolkit.safety import find_stray_temps

    work = tmp_path / "work"
    work.mkdir()
    target = work / "doc.pdf"
    with park_at(point, ["write", "--target", str(target)]) as parked:
        temp = Path(parked.detail)
        assert parked.kill() == -signal.SIGKILL

    strays = find_stray_temps(work)
    assert temp in strays
    assert all(stray.exists() for stray in strays)


# --------------------------------------------------------------------------- #
# PDF-19 — the crash arms, re-derived (Design §D4).
#
# The rendezvous is real: `os.pipe()` x2 handed down by `pass_fds`, the child
# announcing on the ready descriptor and blocking on the release one, the parent
# selecting with a 30 s timeout and delivering `os.kill(pid, SIGKILL)`. Signal 9
# cannot be caught, so there is no unwind path to get wrong.
#
# The vacuity risk is not the kill -- it is WHERE the child was when it arrived.
# An arm that passes because the writer never reached the commit is
# indistinguishable from one that passes because the commit is atomic. Two
# mutations settled it, both observed in a scratch worktree on 2026-09-02:
#
#   (1) `os.replace` hoisted ABOVE the `after_fsync` checkpoint in `_commit`:
#       four arms red, and `test_a_kill_leaves_an_in_place_target_byte_identical`
#       red with the ORIGINAL's SHA-256 CHANGED
#       (b5b6b8f3...09a239 -> 26d85e40...33690ca1). The arms observe the
#       destination, not merely the absence of a fresh file.
#   (2) `checkpoint()` made a no-op: three arms red in ~1 s with
#       "the child exited (code 0) before reaching the fault point" -- NOT the
#       30 s rendezvous timeout §D4 predicted, and better than predicted: the
#       harness detects a child that ran to completion instead of waiting for
#       one that never parks. The arms are not green on a race.
#
# What was missing, and is added below: `test_every_declared_fault_point_is_
# reachable` proves DECLARED -> CALLED. Nothing proved CALLED -> DECLARED, so a
# `checkpoint("after_something_new")` added to `atomic.py` without a
# `FAULT_POINTS` entry would be a live injection point no arm ever parks at.
# --------------------------------------------------------------------------- #

import ast  # noqa: E402

CHOKEPOINT_SOURCE = REPO_ROOT / "src" / "pdf_toolkit" / "safety" / "atomic.py"


def checkpoint_call_site_names(path: Path = CHOKEPOINT_SOURCE) -> tuple[str, ...]:
    """Every literal name passed to `checkpoint(...)` in the chokepoint.

    AST rather than grep: the words appear in prose throughout this module and a
    text scan would be red on the docstrings and blind to a computed argument.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "checkpoint" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            names.append(first.value)
        else:
            names.append("<computed>")
    return tuple(names)


def test_every_checkpoint_call_site_is_a_declared_fault_point() -> None:
    """The converse of `test_every_declared_fault_point_is_reachable`.

    Red (observed, PDF-19): adding a fourth name to `FAULT_POINTS` that no
    writer calls reds the reachability arm above; adding a `checkpoint("x")`
    call that `FAULT_POINTS` does not declare reds THIS one. Both directions
    are needed -- an orphan in either set is an injection point nobody parks at.
    """
    called = checkpoint_call_site_names()
    assert called, f"no checkpoint() call site found in {CHOKEPOINT_SOURCE}"
    assert "<computed>" not in called, (
        f"a checkpoint() call site takes a non-literal name: {called}; it cannot be "
        "matched against FAULT_POINTS and cannot be parked at deterministically"
    )
    undeclared = sorted(set(called) - set(FAULT_POINTS))
    assert undeclared == [], (
        f"{CHOKEPOINT_SOURCE.name} calls checkpoint() at {undeclared}, which "
        f"safety/_faults.FAULT_POINTS does not declare: {list(FAULT_POINTS)}"
    )


def test_the_declared_points_and_the_call_sites_are_the_same_set() -> None:
    """§D4's set equality, stated once so neither direction can drift alone."""
    assert set(checkpoint_call_site_names()) == set(FAULT_POINTS)
    assert len(FAULT_POINTS) == len(set(FAULT_POINTS)), "FAULT_POINTS carries a duplicate"


def test_every_fault_point_precedes_the_replace() -> None:
    """§D1 step 7's guarantee, as a structural fact rather than a sentence.

    "There is no *during* `os.replace`" is what makes the six crash arms a
    complete enumeration rather than a sample. If a checkpoint ever landed after
    the commit, an arm would be parking at a point where the destination has
    already changed and "byte-identical" would stop being the right assertion.
    """
    source = CHOKEPOINT_SOURCE.read_text()
    tree = ast.parse(source, filename=str(CHOKEPOINT_SOURCE))
    commit = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_commit"
    )
    checkpoints = [
        node.lineno
        for node in ast.walk(commit)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", "")) == "checkpoint"
    ]
    replaces = [
        node.lineno
        for node in ast.walk(commit)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") in {"_replace", "_replace_across_devices"}
    ]
    assert checkpoints and replaces, (checkpoints, replaces)
    assert max(checkpoints) < min(replaces), (
        f"a checkpoint at line {max(checkpoints)} sits at or after the commit at "
        f"line {min(replaces)}: the crash arms would be parking after the destination "
        "has already changed"
    )
