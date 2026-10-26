"""PDF-140 D7 -- the independent render-memory measurement harness.

Stdlib only, Linux ``/proc`` only. It NEVER imports ``pdf_tooling`` (AC5's AST
arm enforces that) and reads nothing the product computes: the product grades
itself by the warning it prints, this harness grades it by the operating
system's own account of the processes it actually spawned.

``probe`` launches *argv* in a new session, samples every ``interval`` seconds
the process group it leads, sums ``VmRSS`` over the group and counts the
spawned render workers (``multiprocessing`` ``spawn_main`` children, excluding
the ``resource_tracker``). On teardown it ``killpg``s ONLY its own leader's
group, if anything is still alive -- never a global kill.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = ["FULL_SCALE_SKIP_REASON", "PROC_SKIP_REASON", "Probe", "have_proc", "probe"]

#: The opt-in full-scale arm's skip reason. `scripts/assert_skips.py` counts it
#: under `full-scale-render-memory` (regex `full-scale render memory`).
FULL_SCALE_SKIP_REASON = "full-scale render memory arm disabled; set PDF_TOOLING_FULL_SCALE_RSS=1"

PROC_SKIP_REASON = "/proc process-group sampling is Linux-only"

_PROC = Path("/proc")


def have_proc() -> bool:
    return sys.platform.startswith("linux") and (_PROC / "self" / "stat").exists()


@dataclass(frozen=True)
class Probe:
    rc: int
    peak_rss_mib: float
    max_workers: int
    max_procs: int
    stdout: str
    stderr: str


def _pgid_of(pid: int) -> int | None:
    """The process-group id from ``/proc/<pid>/stat`` (field 5), robust to a
    ``comm`` containing spaces or parentheses."""
    try:
        raw = (_PROC / str(pid) / "stat").read_text()
    except OSError:
        return None
    tail = raw.rsplit(")", 1)[-1].split()
    try:
        return int(tail[2])
    except (IndexError, ValueError):
        return None


def _rss_kib(pid: int) -> int:
    try:
        for line in (_PROC / str(pid) / "status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _is_worker(pid: int) -> bool:
    try:
        cmdline = (_PROC / str(pid) / "cmdline").read_bytes()
    except OSError:
        return False
    return b"spawn_main" in cmdline and b"resource_tracker" not in cmdline


def _sample(leader: int) -> tuple[int, int, int]:
    """(summed RSS KiB, process count, worker count) over the leader's group."""
    total = procs = workers = 0
    for entry in os.listdir(_PROC):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if _pgid_of(pid) != leader:
            continue
        total += _rss_kib(pid)
        procs += 1
        if _is_worker(pid):
            workers += 1
    return total, procs, workers


def probe(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
    interval: float = 0.05,
    timeout: float = 300.0,
) -> Probe:
    """Run *argv* in its own session and report what the OS saw."""
    proc = subprocess.Popen(  # noqa: S603 - argv is test-built
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=dict(env) if env is not None else None,
        cwd=cwd,
        start_new_session=True,
    )
    leader = proc.pid
    peak_kib = max_procs = max_workers = 0
    deadline = time.monotonic() + timeout
    try:
        # Drain pipes on threads-free polling: communicate() would block the
        # sampler, so read after exit; output here is small (a JSON envelope).
        while proc.poll() is None and time.monotonic() < deadline:
            total, procs, workers = _sample(leader)
            peak_kib = max(peak_kib, total)
            max_procs = max(max_procs, procs)
            max_workers = max(max_workers, workers)
            time.sleep(interval)
        out, err = proc.communicate(timeout=max(1.0, deadline - time.monotonic()))
    finally:
        # Only our own session's group; ESRCH (already empty) is the normal case.
        _kill_own_group(leader)
        proc.wait()
    return Probe(
        rc=proc.returncode,
        peak_rss_mib=peak_kib / 1024,
        max_workers=max_workers,
        max_procs=max_procs,
        stdout=out,
        stderr=err,
    )


def _kill_own_group(leader: int) -> None:
    try:
        os.killpg(leader, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
