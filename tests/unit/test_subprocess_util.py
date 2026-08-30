"""The spawn chokepoint's contract, asserted mechanically rather than by review.

The central assertion here is the process-**group** kill. It is not "we call
``killpg`` somewhere" — that would be a test about the code. It spawns a shell
that forks a grandchild, times the call out, and then asks the operating system
whether the group still exists. A sibling product leaked **163 orphaned engine
daemons (~6.5 GiB RSS) on this host** by killing the direct child only, and the
OCR work will drive a binary whose Python binding makes exactly that mistake, so
this is the one test in the file that must be impossible to satisfy by accident.

MEASUREMENT DISCIPLINE
----------------------
Process-hygiene assertions here are **scoped to the process group under test**,
never to an absolute count of processes on the machine. ``pgrep -g <pgid>`` is
group-scoped and safe; a ``pgrep -f 'sleep 300'`` would go red the moment
anything else on this host happened to run a ``sleep 300``, which is a false
alarm masquerading as a finding.

Two assertions, deliberately paired: ``os.killpg(pgid, 0)`` raising
``ProcessLookupError`` is the **primary** check and never skips, because it needs
nothing but the standard library. ``pgrep`` **corroborates** it from outside the
interpreter and skips with a visible reason when the binary is absent.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from pdf_toolkit.adapters import subprocess_util
from pdf_toolkit.errors import FailureError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Bound on how long the group may take to disappear after `run()` returns. The
#: grandchild is reparented when its shell dies, so reaping is prompt; this is a
#: deadline to keep the assertion deterministic rather than a tolerance.
GROUP_REAP_DEADLINE_S = 5.0


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_group_gone(pgid: int, deadline_s: float = GROUP_REAP_DEADLINE_S) -> float | None:
    """Seconds taken for the group to vanish, or ``None`` if it never did."""
    started = time.monotonic()
    while time.monotonic() - started < deadline_s:
        if not _group_alive(pgid):
            return time.monotonic() - started
        time.sleep(0.02)
    return None


# --------------------------------------------------------------------------- #
# The process-group guarantee.
# --------------------------------------------------------------------------- #


def test_timeout_kills_the_whole_group_including_a_forked_grandchild() -> None:
    """A timed-out spawn leaves NO descendant, not merely no direct child.

    ``sh -c 'sleep 300 & sleep 300'`` is the shape that catches a PID kill: the
    backgrounded sleep is a grandchild, so killing ``proc.pid`` alone would reap
    the shell and leave a 300-second sleeper running with nobody watching it.
    """
    result = subprocess_util.run(["sh", "-c", "sleep 300 & sleep 300"], timeout=1)

    assert result.timed_out is True
    assert result.ok is False
    assert result.duration_ms >= 1000, "the call returned before its own timeout elapsed"

    elapsed = _wait_group_gone(result.pgid)
    assert elapsed is not None, (
        f"process group {result.pgid} still exists {GROUP_REAP_DEADLINE_S}s after the "
        "timeout — a descendant survived the kill, which is the orphaned-daemon "
        "failure mode this module exists to prevent"
    )

    # Primary check: the group is gone, asserted through the kernel.
    with pytest.raises(ProcessLookupError):
        os.killpg(result.pgid, 0)


def test_pgrep_corroborates_that_the_group_is_empty() -> None:
    """The same guarantee, observed from outside this interpreter.

    Scoped to the group with ``-g``. An absolute ``pgrep -f 'sleep 300'`` would
    report anything else on this host that happens to be sleeping, which is a
    false positive dressed as a resource-hygiene finding.
    """
    if shutil.which("pgrep") is None:
        pytest.skip("pgrep is not installed; the killpg assertion above still ran")

    result = subprocess_util.run(["sh", "-c", "sleep 300 & sleep 300"], timeout=1)
    assert result.timed_out is True
    assert _wait_group_gone(result.pgid) is not None

    found = subprocess.run(
        ["pgrep", "-g", str(result.pgid)], capture_output=True, text=True, check=False
    )
    assert found.returncode != 0, (
        f"pgrep still lists processes in group {result.pgid}: {found.stdout.strip()!r}"
    )


def test_a_normal_run_leaves_no_group_behind_either() -> None:
    """The sweep is unconditional, so a fast child that forked is covered too.

    The grandchild's streams are redirected away from the inherited pipes, which
    is what lets this run finish *normally* instead of waiting out the timeout —
    see ``test_a_grandchild_holding_the_pipes_is_a_timeout`` for the other half
    of that behaviour. The point here is that the group sweep runs on the
    SUCCESS path too, not only after a timeout.
    """
    result = subprocess_util.run(["sh", "-c", "sleep 30 >/dev/null 2>&1 & echo done"], timeout=10)
    assert result.timed_out is False
    assert result.stdout.strip() == "done"
    assert _wait_group_gone(result.pgid) is not None, (
        "a backgrounded grandchild survived a SUCCESSFUL run — the group, not the "
        "pid, is the unit of cleanup"
    )


def test_a_grandchild_holding_the_pipes_is_a_timeout_and_still_reaped() -> None:
    """A stated property, pinned rather than discovered later in production.

    A grandchild inherits the capture pipes, so the read does not finish when the
    direct child exits — it finishes when the last holder of the pipe closes it.
    A daemon-spawning engine therefore hits the timeout even though its immediate
    process returned promptly. That is honest behaviour for a *capturing* runner
    and it is bounded, but it is surprising enough to be worth a test that names
    it, and the group sweep still leaves nothing behind.
    """
    result = subprocess_util.run(["sh", "-c", "sleep 300 & echo done"], timeout=1)
    assert result.timed_out is True
    assert result.stdout.strip() == "done", "output produced before the timeout is still returned"
    assert _wait_group_gone(result.pgid) is not None


# --------------------------------------------------------------------------- #
# The bound that cannot be forgotten.
# --------------------------------------------------------------------------- #


def test_timeout_is_required_and_has_no_default() -> None:
    """An unbounded spawn is not slow, it is a ``TypeError``.

    A default of ``None`` would make the omission compile and hang; a required
    keyword makes it impossible to write by accident, which is the only version
    of this rule that survives twenty verbs.
    """
    with pytest.raises(TypeError):
        subprocess_util.run(["true"])  # type: ignore[call-arg]


def test_no_module_under_src_enables_a_shell() -> None:
    """The enabled spelling of the shell keyword appears nowhere under ``src/``.

    A literal grep on purpose, and the only one in this spec: this asserts the
    absence of a *string*, so an AST walk would be the wrong tool and a comment
    that merely quoted the spelling would defeat it. Which is exactly why the
    module docstring refuses to quote it.
    """
    needle = "shell" + "=True"
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in sorted((REPO_ROOT / "src").rglob("*.py"))
        if needle in path.read_text()
    ]
    assert offenders == [], f"a shell was enabled somewhere: {offenders}"


def test_argv_is_a_list_and_an_empty_one_is_refused() -> None:
    with pytest.raises(ValueError, match="argv must not be empty"):
        subprocess_util.run([], timeout=1)


# --------------------------------------------------------------------------- #
# Capture, decoding and the check= contract.
# --------------------------------------------------------------------------- #


def test_streams_are_captured_and_returned_not_inherited(
    capfd: pytest.CaptureFixture[str],
) -> None:
    result = subprocess_util.run(
        ["sh", "-c", "echo out; echo err >&2; exit 0"],
        timeout=10,
    )
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"
    assert result.returncode == 0
    assert result.ok is True
    captured = capfd.readouterr()
    assert "out" not in captured.out, "the child's stdout leaked to this process's terminal"


def test_undecodable_bytes_are_replaced_rather_than_raising() -> None:
    """A version banner in the wrong encoding must not crash ``doctor``."""
    result = subprocess_util.run(
        ["sh", "-c", "printf '\\xff\\xfeabc'"],
        timeout=10,
    )
    assert result.returncode == 0
    assert "abc" in result.stdout


def test_check_false_returns_the_failure_for_the_caller_to_judge() -> None:
    """A probe treats a non-zero ``--version`` as *unavailable*, not as a crash."""
    result = subprocess_util.run(["sh", "-c", "exit 3"], timeout=10, check=False)
    assert result.returncode == 3
    assert result.ok is False


def test_check_true_raises_exit_one_carrying_the_stderr_tail() -> None:
    with pytest.raises(FailureError) as caught:
        subprocess_util.run(["sh", "-c", "echo boom >&2; exit 3"], timeout=10, check=True)
    assert caught.value.exit_code == 1
    assert "boom" in caught.value.message


def test_check_true_also_raises_on_a_timeout() -> None:
    with pytest.raises(FailureError) as caught:
        subprocess_util.run(["sh", "-c", "sleep 300"], timeout=1, check=True)
    assert caught.value.exit_code == 1
    assert "timed out" in caught.value.message


def test_cwd_and_env_are_honoured(tmp_path: Path) -> None:
    result = subprocess_util.run(
        ["sh", "-c", "pwd; echo $PDF_TOOLKIT_TEST_MARKER"],
        timeout=10,
        cwd=tmp_path,
        env={"PATH": os.environ.get("PATH", ""), "PDF_TOOLKIT_TEST_MARKER": "marker"},
    )
    lines = result.stdout.split()
    assert str(tmp_path) in lines[0]
    assert "marker" in result.stdout


def test_first_line_skips_blank_lines_and_falls_back_to_stderr() -> None:
    result = subprocess_util.run(["sh", "-c", "echo; echo '  banner  '"], timeout=10)
    assert result.first_line() == "banner"
    empty = subprocess_util.run(["sh", "-c", "echo oops >&2"], timeout=10)
    assert empty.first_line() == ""
    assert empty.first_line("stderr") == "oops"


def test_arguments_are_never_reparsed_by_a_shell() -> None:
    """Metacharacters in an argument are data, because no shell is interposed."""
    payload = "a; echo pwned > /dev/null; b"
    result = subprocess_util.run(["printf", "%s", payload], timeout=10)
    assert result.stdout == payload
