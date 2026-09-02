"""The product's ONLY process-spawn point: bounded timeout, process-GROUP kill.

Everything that leaves this interpreter as a child process leaves through
:func:`run`. Two rules make that worth having, and both are structural rather
than remembered.

**1. No unbounded spawn can be written by accident.** ``timeout`` is a required
keyword argument with no default and no ``None`` sentinel, so a call site that
forgets a bound does not run slowly — it raises ``TypeError``.

**2. The kill is a GROUP kill, never a PID kill.** ``start_new_session=True``
puts the child in its own session and therefore its own process group; a
timeout signals that whole group. Killing ``proc.pid`` alone is the exact
mistake that leaked **163 orphaned engine daemons (~6.5 GiB RSS) on this host**
in a sibling product: a child that has itself forked leaves the grandchild
running, holding memory, invisible to the parent. ``PLAN.md`` §5.4 applies that
lesson pre-emptively, and ``tests/unit/test_subprocess_util.py`` proves it
mechanically with a child that forks before it sleeps.

WHAT MAY NEVER BE HANDED TO THIS FUNCTION
-----------------------------------------
``PLAN.md`` §7.2's forbidden list is absolute — never an import, never an extra,
and **never a subprocess fallback**. This module is precisely where such a
convenience shell-out would physically be written, so the prohibition is
restated here, in the file where the temptation lives.

The forbidden binaries are **not spelled out in this docstring**, deliberately.
``tests/test_cli_spine.py::test_no_forbidden_engine_name_appears_in_packaging_source_or_build``
is a lowercase **substring** scan over every file under ``src/``, so writing the
names here as prose would turn a landed license gate red for a comment. The
authoritative, machine-checked list is:

* ``PLAN.md`` §7.2 — the plan's own list; and
* ``FORBIDDEN`` in ``tests/test_license_policy.py`` — that list plus PDF-02's
  tightenings, enforced by an AST walk over ``src/`` that inspects imports,
  dynamic imports, spawn ``argv[0]`` and ``shutil.which`` arguments.

Read either before adding a call site. A binary in that set is refused whatever
the deadline: the product's licensing claim is the reason it exists.

Two AST guards watch this file from opposite directions:

* ``tests/test_license_policy.py::test_subprocess_chokepoint`` asserts nothing
  else under ``src/`` imports ``subprocess`` or reaches an ``os`` spawn; and
* ``tests/test_import_boundaries.py`` Section 2 asserts that every ``run(...)``
  call site in the tree passes a statically resolvable ``argv[0]`` that is not a
  forbidden binary — the check that a generic wrapper necessarily moves off the
  spawn itself and onto its callers.
"""

from __future__ import annotations

import contextlib
import os
import signal

# The one sanctioned spawn import in the product; see the module docstring for
# the two AST guards that hold the boundary. The marker below carries no prose:
# bandit parses everything after it as test ids and warns on each word.
import subprocess  # nosec B404
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pdf_toolkit.errors import FailureError
from pdf_toolkit.output.logging import get_logger

__all__ = [
    "PROBE_HOME_VARIABLES",
    "PROBE_SANDBOX_ROOT",
    "TERM_GRACE_S",
    "ProcRun",
    "probe_env",
    "run",
]

#: How long a signalled group is given to exit on its own before it is killed
#: outright. Long enough for a well-behaved child to flush and close, short
#: enough that a timeout stays a timeout.
TERM_GRACE_S: Final[float] = 2.0

#: Poll interval while waiting out :data:`TERM_GRACE_S`.
_POLL_S: Final[float] = 0.05


# --------------------------------------------------------------------------- #
# The probe environment sandbox (PDF-20, D2).
#
# WHY THIS EXISTS. `soffice --version` -- the OfficeConverter probe's version
# query -- creates the user's config directory as a side effect (measured
# against LibreOffice 26.2.5.2 on this host: a pristine redirected HOME gains
# exactly `$HOME/.config`, and its own mtime moves). `doctor` therefore wrote
# into the operator's home on every run, and `doctor --dry-run` wrote there too,
# against a purity rule `CLAUDE.md` states without conditions. The write is a
# *probe* side effect, so it is fixed at the probe, not at the verb.
#
# WHAT IS OVERRIDDEN, AND WHAT IS NOT. Exactly the five home-rooted variables
# below. EVERYTHING ELSE IN THE CALLER'S ENVIRONMENT IS INHERITED UNCHANGED --
# `PATH` above all, and `TESSDATA_PREFIX` with it. `run()`'s `env` REPLACES the
# child environment wholesale, so a helper that built a *minimal* environment
# instead of copying `os.environ` would strip `PATH`; the probes would then stop
# resolving and `doctor` would report engines missing on a host that has them.
# That is a purity fix converted into a silent wrong answer with a success exit
# code, and it is the failure mode this function is written to make impossible:
# `probe_env` starts from a full copy and overrides five keys.
#
# WHY THE TARGET IS UNWRITABLE RATHER THAN A SCRATCH DIRECTORY WE REMOVE.
# "Zero net filesystem effect" and "create a scratch tree and delete it" are not
# the same requirement. A directory that is created and removed still moves its
# PARENT's mtime, which a recursive snapshot records -- so a scratch-and-sweep
# sandbox trades one impurity (`$HOME/.config` appears) for another (`$TMPDIR`'s
# mtime moves) and the contract rows that measure `--dry-run` purity would still
# be red. Pointing the five variables at a path UNDER `os.devnull` removes the
# question instead of answering it: `/dev/null` is a character device, so
# creating anything beneath it fails with ENOTDIR for every user including root,
# on every POSIX host, and there is no cleanup path that can fail, leak or race.
#
# MEASURED, NOT ASSUMED (this host, 2026-09-02): with the five variables pointed
# at `/dev/null/pdftoolkit-probe`, `soffice --version` still prints
# `LibreOffice 26.2.5.2 620(Build:2)`, `tesseract --version` still prints
# `tesseract 5.5.0`, and `tesseract --list-langs` still reports the same two
# languages it reports with a real home -- while nothing is created anywhere.
# `tests/test_doctor.py` pins the "did not blind the probe" half so a future
# engine that genuinely needs a writable home cannot degrade silently.
# --------------------------------------------------------------------------- #

#: The home-rooted variables a probe must not be able to write through. Every
#: OTHER variable is inherited unchanged -- see the note above on `PATH`.
PROBE_HOME_VARIABLES: Final[tuple[str, ...]] = (
    "HOME",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
)

#: Where those five are pointed: a path beneath the null device, which cannot be
#: created. Not a directory this process makes, and therefore not one it has to
#: remember to remove.
PROBE_SANDBOX_ROOT: Final[str] = os.path.join(os.devnull, "pdftoolkit-probe")


def probe_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment a *probe* spawn runs under: inherited, minus a home.

    Args:
        base: The environment to start from. Defaults to ``os.environ``; a test
            passes an explicit mapping so the override can be asserted against a
            known starting point rather than against whatever the host has.

    Returns:
        A copy of *base* with :data:`PROBE_HOME_VARIABLES` pointed at
        :data:`PROBE_SANDBOX_ROOT` and every other variable left alone.

    This is deliberately **opt-in at the three probe call sites** rather than a
    default inside :func:`run`. ``run`` is shared with the two OPERATIONAL
    spawns -- the conversion and the OCR call -- which depend on the caller's
    real environment (the converter passes its own isolated profile directory
    already, and an OCR run may legitimately need operator-installed language
    data reachable from the real home). Forcing a redirected home under either
    would be a silent behaviour change to a separately-verified verb.
    ``tests/test_import_boundaries.py`` Section 2 asserts the split by
    construction: every spawn reached from a ``probe()`` or ``languages()``
    method passes this environment, and the two operational sites are excluded
    by an assertion rather than by anyone remembering.
    """
    prepared = dict(os.environ if base is None else base)
    for name in PROBE_HOME_VARIABLES:
        prepared[name] = PROBE_SANDBOX_ROOT
    return prepared


@dataclass(frozen=True, slots=True)
class ProcRun:
    """The complete, already-decoded outcome of one spawn.

    ``pgid`` is carried deliberately: the process-group guarantee above is only
    a guarantee if a test can address the group afterwards and observe that it
    is gone. A field that exists so the promise can be *checked* is cheaper than
    a promise that can only be reviewed.
    """

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    pgid: int

    @property
    def ok(self) -> bool:
        """True when the process ran to completion and reported success."""
        return self.returncode == 0 and not self.timed_out

    def first_line(self, stream: str = "stdout") -> str:
        """The first non-empty line of a captured stream, or ``""``.

        Version probing wants exactly this and nothing more, and every probe
        wanting it in the same place is what keeps "never report a version we
        did not parse" a single rule instead of six.
        """
        text = self.stdout if stream == "stdout" else self.stderr
        for line in text.splitlines():
            if line.strip():
                return line.strip()
        return ""


def _group_alive(pgid: int) -> bool:
    """Whether any process remains in *pgid*.

    Signal 0 performs the permission and existence checks without delivering
    anything. ``PermissionError`` means the group exists but is not ours, which
    is still "alive" for the purpose of deciding whether to escalate.
    """
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - not reachable for our own child
        return True
    return True


def _signal_group(pgid: int, sig: int) -> None:
    """Signal a whole process group, tolerating a group that already vanished."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, sig)


def _terminate_group(proc: subprocess.Popen[str], pgid: int) -> None:
    """SIGTERM the group, wait out the grace window, then SIGKILL what is left.

    Returns immediately and signals nothing when the group is already empty, so
    the belt-and-braces call on the success path costs one ``killpg(pgid, 0)``
    rather than :data:`TERM_GRACE_S`.
    """
    if not _group_alive(pgid):
        return

    _signal_group(pgid, signal.SIGTERM)

    # Reap the direct child first: until it is waited for it stays a zombie
    # *inside the group*, which would make the liveness probe below report
    # "still alive" for every child, well-behaved or not, and turn the grace
    # window into dead time on every timeout.
    with contextlib.suppress(subprocess.TimeoutExpired, ValueError, OSError):
        proc.wait(timeout=TERM_GRACE_S)

    deadline = time.monotonic() + TERM_GRACE_S
    while _group_alive(pgid) and time.monotonic() < deadline:
        time.sleep(_POLL_S)

    if _group_alive(pgid):
        _signal_group(pgid, signal.SIGKILL)


def run(
    argv: Sequence[str],
    *,
    timeout: float,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = False,
) -> ProcRun:
    """Spawn *argv*, capture both streams, and never leave a process behind.

    Args:
        argv: The command as a **list**, never a string. ``shell`` is pinned
            False below and is not a parameter of this function, so a shell is
            never interposed and metacharacters in an argument stay data. (The
            enabled spelling of that keyword is deliberately not written
            anywhere under ``src/``: ``tests/unit/test_subprocess_util.py``
            greps the tree for it, and a guard that its own subject can satisfy
            in a comment is not a guard.)
        timeout: Required. Seconds before the process group is signalled.
        cwd: Working directory for the child.
        env: Complete environment for the child; inherited when ``None``.
        check: When true, a non-zero exit (or a timeout) raises
            :class:`~pdf_toolkit.errors.FailureError` (exit code 1) carrying the
            tail of stderr. Probes pass ``False`` on purpose — a non-zero
            ``--version`` means *unavailable*, which is a report, not a crash.

    Returns:
        A :class:`ProcRun`. ``timed_out`` is a field rather than an exception so
        that a probe can treat a hung binary as "unavailable" without wrapping
        every call in a handler.

    Note:
        Both streams are captured, and a **grandchild inherits those pipes**. The
        read therefore completes when the last holder of the pipe closes it, not
        when the direct child exits, so a command that daemonises while holding
        its output will hit ``timeout`` even though its immediate process
        returned at once. That is bounded and it is honest for a capturing
        runner — the alternative is discarding output an engine may have
        produced — and the group is swept either way.
        ``tests/unit/test_subprocess_util.py`` pins both halves of it.
    """
    command = tuple(str(part) for part in argv)
    if not command:
        raise ValueError("argv must not be empty")

    logger = get_logger("subprocess")
    # argv is logged at DEBUG (-vv) only. PLAN.md §5.7 forbids passwords in argv
    # product-wide and no engine driven through here takes one; this module must
    # not become the exception that makes -vv unsafe to paste into an issue.
    logger.debug("spawn %r (timeout %.1fs)", command, timeout)

    started = time.perf_counter()
    # Waiver rationale for B603 (the marker itself is on the call below, because
    # a bare marker on its own line makes bandit parse this prose as test ids):
    # argv is always a list and `shell` is pinned False below, so no element is
    # ever re-parsed by a shell; and argv[0] is asserted to be a statically
    # resolvable, permitted binary at every call site by
    # tests/test_import_boundaries.py Section 2. Bandit cannot see either fact,
    # and pyproject.toml is off-limits to this spec, so the waiver is inline and
    # states the two guarantees it stands on.
    proc = subprocess.Popen(  # nosec B603
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=None if cwd is None else str(cwd),
        env=None if env is None else dict(env),
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
        shell=False,
    )
    # `start_new_session=True` makes the child a session leader, so its process
    # group id IS its pid, by definition and without a race. Reading it here
    # rather than via os.getpgid() later means the group stays addressable even
    # after the direct child has been reaped -- which is exactly when a leaked
    # grandchild would otherwise become unreachable.
    pgid = proc.pid

    timed_out = False
    stdout = ""
    stderr = ""
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_group(proc, pgid)
            stdout, stderr = proc.communicate()
    finally:
        # Every exit path, including KeyboardInterrupt and an unexpected OSError
        # out of communicate(). A successful run whose child forked and returned
        # is swept here too: the group is the unit of cleanup, not the pid.
        _terminate_group(proc, pgid)
        with contextlib.suppress(OSError, ValueError):
            proc.wait()

    duration_ms = int((time.perf_counter() - started) * 1000)
    result = ProcRun(
        argv=command,
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout or "",
        stderr=stderr or "",
        duration_ms=duration_ms,
        timed_out=timed_out,
        pgid=pgid,
    )

    if check and not result.ok:
        tail = "\n".join(result.stderr.strip().splitlines()[-5:])
        what = "timed out" if result.timed_out else f"exited {result.returncode}"
        detail = f": {tail}" if tail else ""
        raise FailureError(f"{command[0]} {what} after {duration_ms} ms{detail}")

    return result
