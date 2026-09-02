#!/usr/bin/env python3
"""Read `.github/gate-parity.toml`, re-derive `ci.yml`, and print the gap.

PDF-28. `make ci` is a subset of CI, run with the same commands -- it does
not, and cannot, predict CI (see the spec's Design Sec 2 for why widening it
to try is unreachable by construction, not merely expensive). This script is
the engine behind two things:

  check      exits 0 iff the manifest and ci.yml agree in BOTH directions --
             every CI gating step is declared, and every declaration resolves
             to a real gating step. Prints the three derived figures (job
             count, check-leg count, gating-step count), none hard-coded.
  epilogue   what `make ci`'s own recipe calls. Runs the same agreement check
             (so a filtered `-k` run still catches drift) and, on success,
             prints exactly what CI additionally gates and how to run it
             locally where a local counterpart exists.

`tests/test_gate_parity.py` re-derives the CI side AGAIN, independently, with
a from-scratch text scan that does not import `derive_from_ci` below -- see
that module's own docstring and PDF-28 Design Sec 6 for why (a shared parser
bug would make the two sides agree WRONGLY, which is worse than disagreeing).

WHAT COUNTS AS A "GATING STEP" is stated once, at the top of
`.github/gate-parity.toml`, and applied identically (in separately-written
code) by both parsers.
"""

from __future__ import annotations

import argparse
import platform
import re
import sys
import tomllib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
MANIFEST_PATH: Final[Path] = REPO_ROOT / ".github" / "gate-parity.toml"
CI_WORKFLOW_PATH: Final[Path] = REPO_ROOT / ".github" / "workflows" / "ci.yml"
MAKEFILE_PATH: Final[Path] = REPO_ROOT / "Makefile"

#: CLOSED. A `reason` value outside this set is an escape hatch that turns
#: into "reason = because" within two waves -- PDF-28 Design Sec 3.
REASON_VOCAB: Final[frozenset[str]] = frozenset(
    {
        "needs-ci-host",
        "needs-pinned-external-binary",
        "needs-engine-configuration",
        "needs-clean-tree",
        "needs-built-artifact",
        "setup",
        "informational",
    }
)

#: Step `name:` values recognized as pure environment provisioning, not a
#: check -- the same category as `uv sync --locked` below, just spelled with a
#: `name:` instead of being self-evident from the command.
SETUP_STEP_NAMES: Final[frozenset[str]] = frozenset({"Install engines", "Install pinned gitleaks"})

#: Exact `run:` command bodies (after stripping) recognized as setup.
SETUP_RUN_COMMANDS: Final[frozenset[str]] = frozenset({"uv sync --locked"})


@dataclass(frozen=True, slots=True)
class GatingStep:
    job: str
    name: str
    run: str


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _is_self_neutralizing(run_text: str) -> bool:
    """A command ending in `|| true` cannot fail regardless of its own exit
    code -- an artifact-generation report step, never a gate."""
    return run_text.strip().endswith("|| true")


def _matrix_leg_count(job: dict[str, Any]) -> int:
    strategy = job.get("strategy") or {}
    matrix = strategy.get("matrix") or {}
    legs = 1
    for axis, values in matrix.items():
        if axis in ("include", "exclude"):
            continue
        if isinstance(values, list):
            legs *= len(values)
    return legs


def derive_from_ci(
    path: Path = CI_WORKFLOW_PATH,
) -> tuple[tuple[str, ...], tuple[GatingStep, ...], int]:
    """Returns (job names in file order, gating steps, total check-leg count)."""
    with path.open() as fh:
        doc = yaml.safe_load(fh)
    jobs: dict[str, Any] = doc["jobs"]
    job_names = tuple(jobs.keys())
    gating_steps: list[GatingStep] = []
    leg_count = 0
    for job_name, job in jobs.items():
        leg_count += _matrix_leg_count(job)
        for step in job.get("steps", []):
            run = step.get("run")
            if run is None:
                continue
            if step.get("continue-on-error") is True:
                continue
            if _is_self_neutralizing(run):
                continue
            name = step.get("name", "") or ""
            if name in SETUP_STEP_NAMES:
                continue
            if run.strip() in SETUP_RUN_COMMANDS:
                continue
            first_line = run.strip().splitlines()[0].strip() if run.strip() else ""
            gating_steps.append(GatingStep(job=job_name, name=name or first_line, run=run.strip()))
    return job_names, tuple(gating_steps), leg_count


def _parse_makefile_ci_prereqs(text: str) -> tuple[str, ...]:
    for line in text.splitlines():
        if line.startswith("ci:"):
            rest = line[len("ci:") :].split("##", 1)[0]
            return tuple(rest.split())
    raise ValueError("Makefile has no 'ci:' target line")


def _makefile_target_names(text: str) -> frozenset[str]:
    names: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):", line)
        if m:
            names.add(m.group(1))
    return frozenset(names)


def validate(
    job_names: Iterable[str],
    gating_steps: Iterable[GatingStep],
    manifest: dict[str, Any],
    makefile_text: str,
) -> list[str]:
    """Pure: returns the list of PROBLEMS. Empty means agreement holds."""
    problems: list[str] = []
    job_names = tuple(job_names)
    job_name_set = frozenset(job_names)
    gating_steps = tuple(gating_steps)
    checks: list[dict[str, Any]] = manifest.get("check", [])

    # Reason vocabulary is closed (AC6).
    for c in checks:
        reason = c.get("reason")
        if reason is not None and reason not in REASON_VOCAB:
            problems.append(
                f"[[check]] job={c.get('job')!r} step={c.get('step')!r}: reason {reason!r} "
                f"is outside the closed vocabulary {sorted(REASON_VOCAB)}"
            )
        if not c.get("local") and not reason:
            problems.append(
                f"[[check]] job={c.get('job')!r} step={c.get('step')!r}: neither `local` nor "
                "`reason` is set -- a check must declare a local counterpart, a reason it has "
                "none, or both"
            )

    # Rule 1: every derived CI job has at least one manifest entry (AC4).
    manifest_jobs = {c.get("job") for c in checks}
    for jn in job_names:
        if jn not in manifest_jobs:
            problems.append(
                f"CI job {jn!r} has no [[check]] entry in {MANIFEST_PATH.name} -- a CI check "
                "cannot be added without declaring whether a contributor can run it locally"
            )

    # Rule 2: every manifest entry's job still exists in ci.yml (AC5, the
    # anti-weakening direction -- deleting the CI side must not "fix" this).
    for c in checks:
        if c.get("job") not in job_name_set:
            problems.append(
                f"[[check]] job={c.get('job')!r} step={c.get('step')!r} does not resolve -- "
                "no such job in ci.yml. Deleting a CI job does not make the manifest agree; "
                "the manifest entry must be removed too, in the same commit that explains why."
            )

    # Per-job step-count equality -- a finer net than job-level presence,
    # catching drift WITHIN an existing job (e.g. an undeclared new step).
    derived_counts = Counter(s.job for s in gating_steps)
    manifest_counts = Counter(c.get("job") for c in checks if c.get("job") in job_name_set)
    for jn in job_names:
        d, m = derived_counts.get(jn, 0), manifest_counts.get(jn, 0)
        if d != m:
            problems.append(
                f"job {jn!r}: ci.yml has {d} gating step(s), the manifest declares {m} -- "
                "they must match one-to-one"
            )

    # Every `local` target must be a real Makefile target (AC16).
    target_names = _makefile_target_names(makefile_text)
    for c in checks:
        local = c.get("local")
        if local and local not in target_names:
            problems.append(
                f"[[check]] job={c.get('job')!r} step={c.get('step')!r}: local target "
                f"{local!r} is not defined in {MAKEFILE_PATH.name}"
            )

    # Makefile's `ci:` prerequisites <-> manifest `in_make_ci = true` (AC8).
    try:
        prereqs = frozenset(_parse_makefile_ci_prereqs(makefile_text))
    except ValueError as exc:
        problems.append(str(exc))
        prereqs = frozenset()
    declared_true = frozenset(
        c["local"] for c in checks if c.get("in_make_ci") is True and c.get("local")
    )
    for missing in sorted(prereqs - declared_true):
        problems.append(
            f"Makefile 'ci:' runs {missing!r} but no [[check]] declares it in_make_ci = true"
        )
    for extra in sorted(declared_true - prereqs):
        problems.append(
            f"[[check]] entries claim {extra!r} is in_make_ci = true, but Makefile's 'ci:' "
            "target no longer runs it -- the local gate has silently narrowed"
        )

    return problems


def check(argv: list[str] | None = None) -> int:
    del argv
    job_names, gating_steps, leg_count = derive_from_ci()
    manifest = load_manifest()
    makefile_text = MAKEFILE_PATH.read_text()
    problems = validate(job_names, gating_steps, manifest, makefile_text)
    if problems:
        print("gate_parity check: FAILED", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"jobs: {len(job_names)}")
    print(f"check legs: {leg_count}")
    print(f"gating steps: {len(gating_steps)}")
    print("gate_parity check: OK -- manifest and ci.yml agree in both directions")
    return 0


def _not_run_here(
    job_names: tuple[str, ...],
    manifest: dict[str, Any],
) -> list[tuple[str, str | None, str | None, str | None]]:
    """One (job, reason, local, partial) row per job that `make ci` does NOT
    fully cover -- either because some of its checks are `in_make_ci = false`,
    or because a check carries a `partial` note even while `in_make_ci = true`
    (the `test` job's one-leg-of-eight case)."""
    checks: list[dict[str, Any]] = manifest.get("check", [])
    by_job: dict[str, list[dict[str, Any]]] = {}
    for c in checks:
        by_job.setdefault(c.get("job"), []).append(c)

    rows: list[tuple[str, str | None, str | None, str | None]] = []
    for jn in job_names:
        rows_for_job = by_job.get(jn, [])
        not_fully_local = [
            c for c in rows_for_job if c.get("in_make_ci") is not True or c.get("partial")
        ]
        if not not_fully_local:
            continue
        representative = not_fully_local[0]
        reason = representative.get("reason")
        local = representative.get("local")
        partial = representative.get("partial")
        rows.append((jn, reason, local, partial))
    return rows


def epilogue(argv: list[str] | None = None) -> int:
    del argv
    job_names, gating_steps, _leg_count = derive_from_ci()
    manifest = load_manifest()
    makefile_text = MAKEFILE_PATH.read_text()
    problems = validate(job_names, gating_steps, manifest, makefile_text)
    if problems:
        print(
            "make ci: gate_parity epilogue FAILED -- manifest and ci.yml disagree", file=sys.stderr
        )
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    prereqs = _parse_makefile_ci_prereqs(makefile_text)
    interpreter = platform.python_version()
    system = platform.system().lower()
    print(f"make ci: {len(prereqs)} local checks passed, on CPython {interpreter} ({system}).")
    print()
    print("NOT RUN HERE -- CI additionally gates:")
    for jn, reason, local, partial in _not_run_here(job_names, manifest):
        tag = f"[{reason}]" if reason else ""
        suffix = f" ({partial})" if partial else ""
        print(f"  {jn}{suffix}  {tag}")
        if local:
            print(f"                    -> runnable locally: make {local}")
    print()
    print("A green `make ci` means those checks passed. It does not predict CI.")
    manifest_rel = MANIFEST_PATH.relative_to(REPO_ROOT)
    print(f"Manifest: {manifest_rel}   Reproduce one CI leg: make test PYTHON=3.11")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="verify manifest <-> ci.yml agreement, print derived figures")
    sub.add_parser("epilogue", help="what `make ci` prints on success")
    args, rest = parser.parse_known_args(argv)
    if args.command == "check":
        return check(rest)
    return epilogue(rest)


if __name__ == "__main__":
    raise SystemExit(main())
