#!/usr/bin/env python3
"""Gate-timing measurement harness — PDF-29.

**Why this is a script and not a stopwatch.** Ruling `X-109` records that every
one of `B-061`'s six `make ci` datapoints was self-measured by the agent that
produced it: six agents, six protocols, one trend, and a suite that grew 25.6%
across the same interval. A trend built from incommensurable samples cannot tell
scope growth from a regression, so none of those six numbers could justify a
decision. **A protocol that is not executable is not a protocol.**

Every field in `RECORD_FIELDS` is required because each one is a way two
timings stop being comparable:

* `cache_state` — 331.25 s (warm) and 492.20 s (after `make clean`) were never
  the same measurement and were compared as though they were.
* `engines` — the same suite measured 860 s with engines present and 529 s with
  them hidden.
* `interpreter` — on this project's dev host `python3 -V` reports 3.14.4 while
  `uv run python -V` reports 3.12.13. The system Python is **never** recorded.
* `binary` / `binary_arm` — `tests/test_cli_spine.py::console_script()` has a
  three-arm fallback, and `make install` can leave a *stale* `pdftoolkit` on
  PATH. An unrecorded arm means the number may be from a different bootstrap
  than the one under test.
* `quiet` / `foreign_processes` — captured **while the foreign processes are
  alive**, because once they exit the contention becomes unprovable and an
  anomalous timing reads as a product regression (`B-098`).
* `distribution` — a single derived headroom figure is how the findings ledger
  came to contradict itself (`C-3`: "shrunk from 25 ms to 4.7 ms" against a
  median that implies 6.8 ms).

**The one rule that makes the file usable:** a record with ``quiet: false`` is
admissible as an OBSERVATION and inadmissible as a BASELINE. ``--baseline``
therefore refuses (non-zero exit, nothing written) on a host it cannot verify
quiet, rather than recording a number nobody can use. That is `PLAN.md` §10.1
rule 5 — absent precondition, skip with a reason, never pass — applied to
timing.

**Licence posture (HC-1).** This harness shells out to `make`, `git`, `ps`, `uv`
and the project's own console script and to nothing else. It must never gain a
convenience shell-out to a PDF tool: a licence violation taken for a benchmark
would be the worst possible trade.

**Privacy posture (HC-2).** The foreign-process census records pid, ppid,
%CPU and the executable *basename* only — never a command line and never a
working directory, either of which could carry a path under the operator's
real-document corpus into a tracked file.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TREND_PATH = REPO_ROOT / "perf" / "gate-timings.jsonl"

#: The record schema. Every field is required; a record missing one is invalid.
#: Ordered as Design §3's table so the file and the spec read the same way.
RECORD_FIELDS: tuple[str, ...] = (
    "timestamp",
    "commit",
    "dirty",
    "target",
    "variant",
    "interpreter",
    "binary",
    "binary_arm",
    "cache_state",
    "engines",
    "tests_collected",
    "coverage_pct",
    "cpu_count",
    "loadavg_start",
    "loadavg_peak",
    "loadavg_end",
    "foreign_processes",
    "quiet",
    "wall_clock_s",
    "distribution",
)

TARGETS: tuple[str, ...] = ("ci", "cover", "test", "help-startup")

#: A foreign process at or above this %CPU makes the host non-quiet.
FOREIGN_CPU_THRESHOLD = 25.0

#: ...but only once it has been alive this long. **This guard is not a
#: convenience, it is an arithmetic requirement**, and it was added after the
#: detector was OBSERVED returning `quiet: false` on a demonstrably idle host.
#: `ps -o pcpu` reports CPU time divided by ELAPSED time -- a lifetime average.
#: On a process that has lived for a few milliseconds that ratio is meaningless:
#: the transient `ps` invocations another tool on this box makes were measured
#: at **200% and 400%**, figures that are not even valid CPU fractions for the
#: single-threaded snapshot they describe. A process alive for under ten seconds
#: also cannot meaningfully contend with a run measured in minutes. Since the
#: census is re-taken every few seconds for the whole run, anything that
#: persists is still caught by a later sample; only sub-ten-second transients
#: are missed, and those are exactly what should be missed.
FOREIGN_MIN_LIFETIME_S = 10.0

#: `loadavg_start <= QUIET_LOAD_FRACTION * cpu_count`. Design §3.
QUIET_LOAD_FRACTION = 0.25

_COVERAGE_TOTAL = re.compile(r"^TOTAL\s+.*?(\d+(?:\.\d+)?)%\s*$", re.MULTILINE)
_COVERAGE_REACHED = re.compile(r"Total coverage:\s*(\d+(?:\.\d+)?)%")
_COLLECTED = re.compile(r"collected (\d+) items?")
_SUMMARY_COUNT = re.compile(r"(\d+) (passed|failed|skipped|xfailed|xpassed|error|errors)\b")


class MeasurementRefused(RuntimeError):
    """Raised when a precondition fails and refusing beats recording."""


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #


def _run(argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv), capture_output=True, text=True, check=False, cwd=REPO_ROOT, **kwargs
    )


def git_commit() -> str:
    return _run(["git", "rev-parse", "HEAD"]).stdout.strip() or "unknown"


def git_dirty() -> tuple[bool, list[str]]:
    """(is dirty, the paths that make it dirty).

    The path list is what makes a dirty-tree timing *attributable* rather than
    merely disqualified: a run measured with this spec's own deliverables in the
    tree is a different thing from one measured against an unknown diff.
    """
    # NOT `.stdout.strip()`. Porcelain lines are `XY<space>PATH`, and for a
    # worktree-modified file X is a SPACE -- so stripping the whole output ate
    # the first line's leading status char and `line[3:]` then cut one character
    # too many. Observed live: `.github/workflows/ci.yml` was recorded as
    # `github/workflows/ci.yml`. A provenance field that is subtly wrong is
    # worse than one that is absent, because nothing about it looks wrong.
    out = _run(["git", "status", "--porcelain"]).stdout
    paths: list[str] = []
    for line in out.splitlines():
        if len(line) <= 3:
            continue
        path = line[3:]
        if " -> " in path:  # a rename: record the destination
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip().strip('"'))
    if not paths:
        return False, []
    return True, sorted(paths)


def resolve_interpreter() -> dict[str, str]:
    """The project venv's interpreter, resolved through `uv run` and nothing else.

    Never records the system Python. Refuses if `uv run python` does not land
    inside a virtual environment under this repository (AC3): a figure taken on
    a different interpreter than the gate uses is not a figure about the gate.
    """
    probe = (
        "import sys;print(sys.version.split()[0]);print(sys.executable);"
        "print(sys.prefix);print(sys.base_prefix)"
    )
    result = _run(["uv", "run", "python", "-c", probe])
    if result.returncode != 0:
        raise MeasurementRefused(f"`uv run python` failed: {result.stderr.strip()[:400]}")
    lines = result.stdout.strip().splitlines()
    if len(lines) != 4:
        raise MeasurementRefused(f"unexpected interpreter probe output: {lines!r}")
    version, executable, prefix, base_prefix = lines
    if prefix == base_prefix:
        raise MeasurementRefused(
            f"`uv run python` resolved {executable} which is NOT a virtual environment "
            f"(sys.prefix == sys.base_prefix == {prefix}). Refusing rather than recording "
            "a system-Python figure -- this host reports a different version for "
            "`python3 -V` than for `uv run python -V`."
        )
    if REPO_ROOT not in Path(prefix).resolve().parents and Path(prefix).resolve() != REPO_ROOT:
        raise MeasurementRefused(
            f"`uv run python` resolved a venv outside this repository ({prefix}). "
            "The local gate runs the project venv; recording another one would make "
            "this record incomparable with every other record for the same target."
        )
    return {
        "version": version,
        "executable": executable,
        "prefix": prefix,
        "resolved_by": "uv run python",
    }


def resolve_console_script(*, strict: bool) -> tuple[str, str]:
    """(binary, arm) for `pdftoolkit`, mirroring tests/test_cli_spine.py's arms.

    C-4: that helper falls back through `venv-sibling` -> `PATH` -> `-m`, and
    nothing asserted which arm ran. `make install` puts a `pdftoolkit` on PATH
    that may be a stale build, and the `-m` arm has a measurably different
    bootstrap, so an unrecorded arm means the startup number may not be about
    the binary under test at all. Under ``strict`` (which is what ``--baseline``
    passes) anything but the project venv's own console script is refused.
    """
    venv_bin = REPO_ROOT / ".venv" / "bin" / "pdftoolkit"
    if venv_bin.exists():
        return str(venv_bin), "venv-sibling"
    sibling = Path(sys.executable).parent / "pdftoolkit"
    if sibling.exists():
        return str(sibling), "interpreter-sibling"
    found = shutil.which("pdftoolkit")
    if found:
        if strict:
            raise MeasurementRefused(
                f"resolved `pdftoolkit` from PATH ({found}), not from the project venv. "
                "`make install` leaves a globally installed build on PATH that may be "
                "STALE, so a --baseline recorded from this arm would be a number about "
                "a different build. Run `uv sync` and re-measure."
            )
        return found, "path"
    if strict:
        raise MeasurementRefused(
            "no `pdftoolkit` console script resolved; the remaining arm is "
            "`python -m pdf_toolkit`, whose bootstrap differs measurably from the "
            "console script's. Refusing to --baseline a different bootstrap."
        )
    return f"{sys.executable} -m pdf_toolkit", "dash-m"


def engine_presence() -> dict[str, str | None]:
    return {"tesseract": shutil.which("tesseract"), "soffice": shutil.which("soffice")}


# --------------------------------------------------------------------------- #
# Host quietness
# --------------------------------------------------------------------------- #


def _process_snapshot() -> list[tuple[int, int, float, float, str]]:
    """One `ps` snapshot, shared by the tree walk and the census.

    Deliberately ONE call: deriving the ownership tree from a *different* `ps`
    invocation than the census means the census's own `ps` child is absent from
    the tree and gets reported as a foreign process at 100% cpu -- a detector
    that always says "not quiet" is exactly as dead as one that always says
    "quiet" (`expertise/product.yaml`: a uniform answer across a population
    expected to be split is the signature of a dead instrument).
    """
    result = _run(["ps", "-eo", "pid=,ppid=,pcpu=,etimes=,comm="])
    rows: list[tuple[int, int, float, float, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) != 5:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
            pcpu, etimes = float(parts[2]), float(parts[3])
        except ValueError:
            continue
        rows.append((pid, ppid, pcpu, etimes, parts[4].strip()))
    return rows


def _own_process_tree(rows: Sequence[tuple[int, int, float, float, str]]) -> set[int]:
    """This process, every descendant of it, and its launching ancestry.

    Our own `make`/`pytest`/`ps` children are not contention -- they are the
    measurement. The ancestry (the shell or agent that started the harness) is
    added too, but only the chain itself, never the chain's other subtrees.
    """
    children: dict[int, list[int]] = {}
    parents: dict[int, int] = {}
    for pid, ppid, _pcpu, _etimes, _comm in rows:
        children.setdefault(ppid, []).append(pid)
        parents[pid] = ppid
    tree: set[int] = set()
    stack = [os.getpid()]
    while stack:
        pid = stack.pop()
        if pid in tree:
            continue
        tree.add(pid)
        stack.extend(children.get(pid, []))
    pid = os.getppid()
    for _ in range(12):
        if pid <= 1:
            break
        tree.add(pid)
        pid = parents.get(pid, 0)
    return tree


def census_foreign_processes(threshold: float = FOREIGN_CPU_THRESHOLD) -> list[dict[str, Any]]:
    """Non-descendant processes at or above *threshold* %CPU, captured live.

    Records pid, ppid, %CPU and the executable BASENAME only -- never a command
    line and never a cwd, either of which could carry a path under the
    operator's real-document corpus into a tracked file (HC-2).
    """
    rows = _process_snapshot()
    own = _own_process_tree(rows)
    found: list[dict[str, Any]] = []
    for pid, ppid, pcpu, etimes, comm in rows:
        if pid in own or comm.startswith("["):
            continue
        if pcpu >= threshold and etimes >= FOREIGN_MIN_LIFETIME_S:
            found.append(
                {
                    "pid": pid,
                    "ppid": ppid,
                    "pcpu": pcpu,
                    "etimes": etimes,
                    "comm": Path(comm).name,
                }
            )
    return sorted(found, key=lambda item: -float(item["pcpu"]))


def load_is_quiet(loadavg_start: float, cpu_count: int) -> bool:
    return loadavg_start <= QUIET_LOAD_FRACTION * cpu_count


class LoadSampler:
    """Samples loadavg and the foreign-process census for the run's duration."""

    def __init__(self, threshold: float = FOREIGN_CPU_THRESHOLD) -> None:
        self.threshold = threshold
        self.peak = 0.0
        self.foreign: dict[int, dict[str, Any]] = {}

    def sample(self) -> None:
        self.peak = max(self.peak, os.getloadavg()[0])
        for proc in census_foreign_processes(self.threshold):
            pid = int(proc["pid"])
            previous = self.foreign.get(pid)
            if previous is None or float(proc["pcpu"]) > float(previous["pcpu"]):
                self.foreign[pid] = proc

    def records(self) -> list[dict[str, Any]]:
        return sorted(self.foreign.values(), key=lambda item: -float(item["pcpu"]))


# --------------------------------------------------------------------------- #
# The runs
# --------------------------------------------------------------------------- #


def parse_tests_collected(output: str) -> int | None:
    matches = _COLLECTED.findall(output)
    if matches:
        return max(int(m) for m in matches)
    counts = {kind: int(n) for n, kind in _SUMMARY_COUNT.findall(output)}
    total = sum(
        counts.get(kind, 0) for kind in ("passed", "failed", "skipped", "xfailed", "xpassed")
    )
    return total or None


def parse_coverage_pct(output: str) -> float | None:
    match = _COVERAGE_REACHED.search(output)
    if match:
        return float(match.group(1))
    totals = _COVERAGE_TOTAL.findall(output)
    if totals:
        return float(totals[-1])
    return None


def run_make_target(target: str, sampler: LoadSampler) -> tuple[float, str]:
    """Run `make <target>`, sampling load throughout, and return (seconds, output)."""
    started = time.perf_counter()
    process = subprocess.Popen(  # noqa: S603 - a literal argv, no shell
        ["make", target],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    chunks: list[str] = []
    assert process.stdout is not None
    last_sample = 0.0
    for line in process.stdout:
        chunks.append(line)
        sys.stderr.write(line)
        now = time.perf_counter()
        if now - last_sample >= 5.0:
            sampler.sample()
            last_sample = now
    process.wait()
    elapsed = time.perf_counter() - started
    sampler.sample()
    output = "".join(chunks)
    if process.returncode != 0:
        raise MeasurementRefused(
            f"`make {target}` exited {process.returncode}. A timing taken from a RED gate "
            "measures a different amount of work than a green one, so nothing is recorded."
        )
    return elapsed, output


def run_help_startup(
    binary: str, trials: int, per_trial: int, sampler: LoadSampler
) -> tuple[list[float], list[float]]:
    """`--help` latency: *trials* independent fastest-of-*per_trial* samples.

    Returns (the fastest-of-N per trial, every individual sample). Coverage's
    subprocess auto-start hooks are scrubbed from the child environment for the
    same reason `tests/test_cli_spine.py` scrubs them: R-13 is a claim about the
    product's startup path, not about how this suite is instrumented.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("COVERAGE_PROCESS_START", "COVERAGE_PROCESS_CONFIG")
    }
    argv = binary.split() if " " in binary else [binary]
    fastest: list[float] = []
    every: list[float] = []
    for index in range(trials):
        samples: list[float] = []
        for _ in range(per_trial):
            started = time.perf_counter()
            result = subprocess.run(  # noqa: S603 - a literal argv, no shell
                [*argv, "--help"],
                capture_output=True,
                text=True,
                check=False,
                cwd=REPO_ROOT,
                env=env,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            if result.returncode != 0:
                raise MeasurementRefused(
                    f"`pdftoolkit --help` exited {result.returncode}; a latency figure from a "
                    "failing invocation measures an error path, not startup."
                )
            samples.append(elapsed_ms)
        every.extend(samples)
        fastest.append(min(samples))
        sampler.sample()
        sys.stderr.write(
            f"  trial {index + 1}/{trials}: fastest-of-{per_trial} = {min(samples):.1f} ms\n"
        )
    return fastest, every


def summarize(values: Iterable[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {}
    index = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return {
        "n": float(len(ordered)),
        "min": round(ordered[0], 3),
        "median": round(statistics.median(ordered), 3),
        "p95": round(ordered[index], 3),
        "max": round(ordered[-1], 3),
        "spread": round(ordered[-1] - ordered[0], 3),
    }


# --------------------------------------------------------------------------- #
# The record
# --------------------------------------------------------------------------- #


def validate_record(record: dict[str, Any]) -> list[str]:
    """Problems with *record*, empty when it is a valid trend line.

    Exported deliberately: `tests/test_gate_budget.py` feeds this one record
    with each required field removed in turn, which is how AC1's red is
    OBSERVED rather than asserted.
    """
    problems = [
        f"missing required field: {field}" for field in RECORD_FIELDS if field not in record
    ]
    if problems:
        return problems
    if record["target"] not in TARGETS:
        problems.append(f"unknown target: {record['target']!r}")
    if record["cache_state"] not in ("clean", "warm", "n/a"):
        problems.append(f"unknown cache_state: {record['cache_state']!r}")
    if not isinstance(record["quiet"], bool):
        problems.append("quiet must be a bool")
    if not isinstance(record["dirty"], bool):
        problems.append("dirty must be a bool")
    if not isinstance(record["interpreter"], dict) or "version" not in record["interpreter"]:
        problems.append("interpreter must carry a resolved version")
    if record["binary_arm"] not in ("venv-sibling", "interpreter-sibling", "path", "dash-m"):
        problems.append(f"unknown binary_arm: {record['binary_arm']!r}")
    if not isinstance(record["cpu_count"], int) or record["cpu_count"] < 1:
        problems.append("cpu_count must be a positive int")
    return problems


def append_record(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def build_record(args: argparse.Namespace) -> dict[str, Any]:
    cpu_count = os.cpu_count() or 1
    loadavg_start = os.getloadavg()[0]
    foreign_at_start = census_foreign_processes()
    quiet = load_is_quiet(loadavg_start, cpu_count) and not foreign_at_start

    if args.baseline and not quiet:
        raise MeasurementRefused(
            "REFUSING to record a BASELINE on a host this harness cannot verify quiet.\n"
            f"  loadavg(1m) at start: {loadavg_start:.2f} against the "
            f"{QUIET_LOAD_FRACTION * cpu_count:.2f} ceiling ({cpu_count} cpus)\n"
            f"  foreign processes at or above {FOREIGN_CPU_THRESHOLD}% cpu and alive at "
            f"least {FOREIGN_MIN_LIFETIME_S:.0f}s: "
            f"{foreign_at_start or 'none'}\n"
            "  A `quiet: false` record is admissible as an OBSERVATION and inadmissible as a\n"
            "  BASELINE (perf/README.md). Re-run WITHOUT --baseline to record the observation,\n"
            "  or wait for the host. Recording an unusable number is worse than recording none."
        )

    interpreter = resolve_interpreter()
    binary, binary_arm = resolve_console_script(strict=args.baseline)

    sampler = LoadSampler()
    sampler.peak = loadavg_start
    for proc in foreign_at_start:
        sampler.foreign[int(proc["pid"])] = proc

    tests_collected: int | None = None
    coverage_pct: float | None = None
    distribution: dict[str, Any] | None = None

    if args.target == "help-startup":
        fastest, every = run_help_startup(binary, args.trials, args.per_trial, sampler)
        distribution = {
            "statistic": f"fastest-of-{args.per_trial}, {args.trials} independent trials",
            "unit": "ms",
            "trials": [round(value, 3) for value in fastest],
            **summarize(fastest),
            "all_samples": summarize(every),
        }
        wall_clock_s = round(sum(every) / 1000.0, 3)
    else:
        wall_clock_s, output = run_make_target(args.target, sampler)
        wall_clock_s = round(wall_clock_s, 3)
        tests_collected = parse_tests_collected(output)
        coverage_pct = parse_coverage_pct(output)

    loadavg_end = os.getloadavg()[0]
    foreign = sampler.records()
    quiet = quiet and not foreign

    dirty, dirty_paths = git_dirty()
    record: dict[str, Any] = {
        "schema_version": 1,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "commit": git_commit(),
        "dirty": dirty,
        "dirty_paths": dirty_paths,
        "target": args.target,
        "variant": args.variant,
        "interpreter": interpreter,
        "binary": binary,
        "binary_arm": binary_arm,
        "cache_state": args.cache_state,
        "engines": engine_presence(),
        "tests_collected": tests_collected,
        "coverage_pct": coverage_pct,
        "cpu_count": cpu_count,
        "loadavg_start": round(loadavg_start, 2),
        "loadavg_peak": round(sampler.peak, 2),
        "loadavg_end": round(loadavg_end, 2),
        "foreign_processes": foreign,
        "quiet": quiet,
        "wall_clock_s": wall_clock_s,
        "distribution": distribution,
        "baseline_requested": bool(args.baseline),
        "host": {"platform": platform.platform(), "machine": platform.machine()},
        "note": args.note,
    }
    return record


def render_summary(record: dict[str, Any]) -> str:
    lines = [
        "",
        "=" * 72,
        f"  target        {record['target']}  (variant: {record['variant']})",
        f"  wall_clock_s  {record['wall_clock_s']}",
        f"  quiet         {record['quiet']}"
        + ("" if record["quiet"] else "   <-- OBSERVATION ONLY, NOT A BASELINE"),
        f"  loadavg       start {record['loadavg_start']} / peak {record['loadavg_peak']} "
        f"/ end {record['loadavg_end']}  ({record['cpu_count']} cpus)",
        f"  foreign       {record['foreign_processes'] or 'none above threshold'}",
        f"  cache_state   {record['cache_state']}",
        f"  engines       {record['engines']}",
        f"  interpreter   {record['interpreter']['version']} "
        f"({record['interpreter']['executable']})",
        f"  binary        {record['binary']}  [arm: {record['binary_arm']}]",
        f"  commit        {record['commit'][:12]}  dirty={record['dirty']} "
        f"({len(record['dirty_paths'])} path(s))",
        f"  tests         {record['tests_collected']}   coverage {record['coverage_pct']}",
    ]
    if record["distribution"]:
        dist = record["distribution"]
        lines.append(
            f"  distribution  {dist['statistic']}: min {dist['min']} / median {dist['median']} "
            f"/ p95 {dist['p95']} / max {dist['max']} / spread {dist['spread']} {dist['unit']}"
        )
    lines.append("=" * 72)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="measure_gate.py",
        description="Measure a gate target and append one provenance-complete JSON line.",
    )
    parser.add_argument("--target", required=True, choices=TARGETS)
    parser.add_argument(
        "--cache-state",
        default="warm",
        choices=("clean", "warm", "n/a"),
        help="`clean` means `make clean` ran immediately before this invocation.",
    )
    parser.add_argument("--variant", default="default")
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Refuse (non-zero, nothing written) unless the host verifies quiet.",
    )
    parser.add_argument("--trials", type=int, default=20, help="help-startup: independent trials")
    parser.add_argument("--per-trial", type=int, default=5, help="help-startup: samples per trial")
    parser.add_argument("--out", type=Path, default=DEFAULT_TREND_PATH)
    parser.add_argument("--no-append", action="store_true", help="Print the record, write nothing.")
    parser.add_argument("--note", default="", help="Free-text provenance note.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        record = build_record(args)
    except MeasurementRefused as exc:
        sys.stderr.write(f"\nmeasure_gate: {exc}\n\n")
        return 2
    problems = validate_record(record)
    if problems:
        sys.stderr.write("measure_gate: refusing to append an invalid record:\n")
        for problem in problems:
            sys.stderr.write(f"  - {problem}\n")
        return 3
    if not args.no_append:
        append_record(record, args.out)
    sys.stderr.write(render_summary(record) + "\n")
    if args.no_append:
        print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
