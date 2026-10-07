#!/usr/bin/env python3
"""Load harness for the start-method survivor arm (PDF-111, ledger 7b6f1aac03).

THE PROTOCOL
------------
The arm ``tests/integration/test_render_pool_start_method.py::
test_ac3_survivors_and_post_death_growth_by_start_method`` is load-sensitive: it
SIGKILLs a render driver and then asserts that no worker survives and no late page
was written. A lucky CI streak proves nothing about it, so this harness reproduces
the shape of the runner that reddened it (4 CPUs, ``make cover``'s coverage
instrument, a CPU-saturated box -- X-841) and counts trials.

One TRIAL is one fresh ``pytest -n 0 <node>`` with ``PDF111_ARM_RECORD`` set, so the
arm appends its record (survivors with ppid/state, late files with size and writer
pid, seconds to quiescence) as one JSON line. Every trial and the busy-loops are
pinned to ``--cpus`` with ``os.sched_setaffinity`` (no ``taskset`` dependency), so
the pressure never leaks onto the rest of a shared host.

THE TEETH RULE (spec AC13). A green run counts for nothing until the SAME
parameters have reddened the PRE-FIX tree. Copy this file (untracked) into a
detached worktree at ``9809a7f`` and run it there::

    scripts/stress_start_method_arm.py --params spawn-False --trials 60

At least one trial must red with the SURVIVOR shape. If 0/60, escalate at most two
rungs -- rung 1 ``--load-per-cpu 10``, rung 2 ``--cpus`` = 2 CPUs -- and if the last
rung is still 0/60 the harness has no teeth: STOP and report BLOCKED with every
JSONL. The parameters that first show teeth are THE declared parameters for the
post-fix run (AC14)::

    scripts/stress_start_method_arm.py --params fork-False,spawn-False --trials 60

which must be 120/120 green, with zero late files carrying payload and a maximum
``seconds_to_quiescence`` of at most 2.5 s (``_SURVIVOR_TIMEOUT_S / 4`` against an
unchanged bound -- never widen it). ``--params forkserver-True`` is opt-in and
ADVISORY: it is reported but never gates the exit code.

HYGIENE. The load runs in its own process group and is killed in ``finally`` by
that group id. Nothing is ever killed by name. Every trial carries an environment
token, and on exit a census lists any process still carrying it (those are this
harness's own descendants); each is reported, then killed by pid. ``COVERAGE_FILE``
points into a scratch directory, never the repo root (B-090). Not wired into CI or
``make ci``: an acceptance instrument, not a gate.

Exit status is 0 iff every GATED trial is green.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

_NODE = (
    "tests/integration/test_render_pool_start_method.py"
    "::test_ac3_survivors_and_post_death_growth_by_start_method[{param}]"
)
_GATED = {"fork-False", "spawn-False"}
_WORKERS = 6  # the arm's `_WORKERS`: one empty in-flight name per worker is the benign class
_TRIAL_TIMEOUT_S = 600.0
_QUIESCENCE_LIMIT_S = 2.5


def _parse_cpus(text: str) -> list[int]:
    cpus: list[int] = []
    for part in text.split(","):
        if "-" in part:
            low, high = part.split("-", 1)
            cpus.extend(range(int(low), int(high) + 1))
        elif part:
            cpus.append(int(part))
    return sorted(set(cpus))


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    return done.stdout.strip()


def _start_load(cpus: list[int], per_cpu: int, loads: list[subprocess.Popen[bytes]]) -> None:
    """``per_cpu * len(cpus)`` busy-loops in ONE new process group, all pinned.

    Appends to *loads* as it goes, so a failure half-way still leaves the caller's
    ``finally`` able to kill every busy-loop already started.
    """
    pgid = 0
    for _ in range(per_cpu * len(cpus)):
        proc = subprocess.Popen(
            [sys.executable, "-c", "while True: pass"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # First busy-loop leads a NEW group (0); the rest join it.
            process_group=pgid,
        )
        if pgid == 0:
            pgid = proc.pid
        loads.append(proc)


def _stop_load(loads: list[subprocess.Popen[bytes]]) -> None:
    if not loads:
        return
    try:
        os.killpg(loads[0].pid, signal.SIGKILL)
    except OSError:
        pass
    for proc in loads:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _census(token: str) -> list[int]:
    """Live non-zombie pids whose environment carries *token* -- our descendants."""
    found: list[int] = []
    me = os.getpid()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        try:
            environ = (entry / "environ").read_bytes()
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        if token.encode() not in environ:
            continue
        if stat[stat.rindex(")") + 2 :].split()[0] == "Z":
            continue
        found.append(int(entry.name))
    return found


def _classify(rc: int, record: dict[str, object] | None, text: str) -> str:
    if rc == 0:
        return "GREEN"
    if record is not None:
        if record.get("survivors"):
            return "SURVIVORS"
        late = record.get("late") or []
        if any(item[1] > 0 for item in late) or len(late) > _WORKERS:  # type: ignore[index, arg-type]
            return "LATE"
    if "still alive in the job's own process group" in text:
        return "SURVIVORS"
    if "output grew from" in text or "output appeared after" in text:
        return "LATE"
    return "OTHER"


def _run_trial(
    repo: Path,
    param: str,
    *,
    coverage: bool,
    scratch: Path,
    token: str,
    meta: dict[str, object],
) -> dict[str, object]:
    sink = scratch / f"record-{uuid.uuid4().hex}.jsonl"
    env = dict(os.environ)
    env["PDF111_ARM_RECORD"] = str(sink)
    env["PDF111_HARNESS_TOKEN"] = token
    env.pop("PDF111_PLANT", None)
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-n",
        "0",
        "-q",
        "-p",
        "no:cacheprovider",
        _NODE.format(param=param),
    ]
    if coverage:
        env["COVERAGE_FILE"] = str(scratch / ".coverage")
        cmd += ["--cov=pdf_tooling", "--cov-report="]
    load_start = os.getloadavg()[0]
    started = time.monotonic()
    try:
        done = subprocess.run(
            cmd,
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            timeout=_TRIAL_TIMEOUT_S,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        rc, text = done.returncode, done.stdout + done.stderr
    except subprocess.TimeoutExpired as exc:
        rc, text = 124, f"trial timed out after {_TRIAL_TIMEOUT_S}s: {exc}"
    seconds = time.monotonic() - started
    record: dict[str, object] | None = None
    if sink.exists() and sink.read_text().strip():
        record = json.loads(sink.read_text().strip().splitlines()[-1])
    for stale in scratch.glob(".coverage.*"):
        stale.unlink(missing_ok=True)
    sink.unlink(missing_ok=True)
    half = _classify(rc, record, text)
    late = (record or {}).get("late") or []
    return {
        **meta,
        "param": param,
        "rc": rc,
        "half": half,
        "seconds": round(seconds, 2),
        "loadavg_start": round(load_start, 2),
        "loadavg_end": round(os.getloadavg()[0], 2),
        "seconds_to_quiescence": (record or {}).get("seconds_to_quiescence"),
        "survivors": (record or {}).get("survivors"),
        "late": late,
        "late_sizes": [item[1] for item in late],  # type: ignore[index, union-attr]
        "has_record": record is not None,
        "tail": "" if half == "GREEN" else text[-1500:],
    }


def main(argv: list[str] | None = None) -> int:
    affinity = sorted(os.sched_getaffinity(0))
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--cpus",
        default=",".join(map(str, affinity[:4])),
        help="CPUs to pin the load and every trial to, e.g. 4-7 or 2,9 "
        "(default: the first 4 of this process's affinity)",
    )
    parser.add_argument(
        "--load-per-cpu",
        type=int,
        default=5,
        help="busy-loops per pinned CPU (default 5; X-841 used 40 on 8)",
    )
    parser.add_argument(
        "--coverage",
        choices=("on", "off"),
        default="on",
        help="run each trial under make cover's coverage instrument (default on)",
    )
    parser.add_argument("--trials", type=int, default=60, help="trials per param (default 60)")
    parser.add_argument(
        "--params",
        default="fork-False,spawn-False",
        help="comma list of the arm's parametrize ids; forkserver-True is "
        "opt-in and advisory (default fork-False,spawn-False)",
    )
    parser.add_argument("--out", type=Path, required=True, help="JSONL, one line per trial")
    parser.add_argument(
        "--stop-on-red", action="store_true", help="stop at the first non-green GATED trial"
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="the tree under test (default: this script's repo)",
    )
    args = parser.parse_args(argv)

    cpus = _parse_cpus(args.cpus)
    params = [p for p in args.params.split(",") if p]
    repo: Path = args.repo
    token = f"pdf111-{uuid.uuid4().hex}"
    scratch = Path(tempfile.mkdtemp(prefix="pdf111-stress-"))
    os.sched_setaffinity(0, set(cpus))  # trials and loads inherit the pin
    meta: dict[str, object] = {
        "sha": _git(repo, "rev-parse", "--short", "HEAD"),
        "dirty": bool(_git(repo, "status", "--porcelain", "--untracked-files=no")),
        "python": sys.version.split()[0],
        "cpus": cpus,
        "load_per_cpu": args.load_per_cpu,
        "coverage": args.coverage,
    }
    print(f"harness {meta} params={params} trials={args.trials} token={token}", flush=True)

    def _die(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, _die)
    signal.signal(signal.SIGINT, _die)

    loads: list[subprocess.Popen[bytes]] = []
    results: list[dict[str, object]] = []
    leftover: list[int] = []
    try:
        _start_load(cpus, args.load_per_cpu, loads)
        meta["load_pids"] = len(loads)
        with args.out.open("a") as out:
            stop = False
            for n in range(args.trials):
                for param in params:
                    row = _run_trial(
                        repo,
                        param,
                        coverage=args.coverage == "on",
                        scratch=scratch,
                        token=token,
                        meta={**meta, "trial": n + 1},
                    )
                    results.append(row)
                    out.write(json.dumps(row) + "\n")
                    out.flush()
                    print(
                        f"trial {n + 1:>3} {param:<15} {row['half']:<9} rc={row['rc']} "
                        f"{row['seconds']}s load={row['loadavg_start']}->{row['loadavg_end']} "
                        f"q={row['seconds_to_quiescence']}",
                        flush=True,
                    )
                    if args.stop_on_red and param in _GATED and row["half"] != "GREEN":
                        stop = True
                        break
                if stop:
                    break
    finally:
        _stop_load(loads)
        leftover = _census(token)
        for pid in leftover:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        shutil.rmtree(scratch, ignore_errors=True)

    print("\n== SUMMARY ==")
    gated_green = True
    for param in params:
        rows = [r for r in results if r["param"] == param]
        halves: dict[str, int] = {}
        for r in rows:
            halves[str(r["half"])] = halves.get(str(r["half"]), 0) + 1
        quiescence = [
            float(r["seconds_to_quiescence"])
            for r in rows  # type: ignore[arg-type]
            if r["seconds_to_quiescence"] is not None
        ]
        payload = sum(1 for r in rows if any(s > 0 for s in r["late_sizes"]))  # type: ignore[union-attr]
        empty = sum(1 for r in rows if r["late"] and not any(s > 0 for s in r["late_sizes"]))  # type: ignore[union-attr]
        green = halves.get("GREEN", 0)
        gate = "GATED" if param in _GATED else "ADVISORY"
        reds = {k: v for k, v in halves.items() if k != "GREEN"}
        print(
            f"{param} [{gate}]: {green}/{len(rows)} green; reds={reds}; "
            f"max seconds_to_quiescence={max(quiescence) if quiescence else None} "
            f"(limit {_QUIESCENCE_LIMIT_S}); trials with payload-bearing late files={payload}; "
            f"trials observing >=1 EMPTY late file={empty}"
        )
        if param in _GATED and green != len(rows):
            gated_green = False
    print(
        f"census: {len(leftover)} surviving pid(s) carrying this run's token "
        f"before cleanup: {leftover}"
    )
    print(f"census after cleanup: {len(_census(token))} surviving pid(s)")
    print(f"load processes started: {len(loads)}; killed by group id")
    return 0 if gated_green else 1


if __name__ == "__main__":
    raise SystemExit(main())
