#!/usr/bin/env python3
"""Print one spec's per-AC AUDIT-CONVENTION evidence table (PDF-106).

    make verify SPEC=PDF-85
    uv run python scripts/verify_spec.py PDF-85; echo $?

It imports `tests/acceptance/audit_pdf_NN.py`, runs that module's covering node
ids plus its aggregator controls in ONE pytest subprocess, and prints a table:
which ids ran, how each came out, which ACs are evidenced only by a CI run or a
command, and which have no red at all.

THIS RUNNER GRANTS NOTHING. It produces evidence. The qa-sentinel signs it and
the project-manager moves the status; the last line of every table says so, and
the runner never prints a single overall PASS.

Exit codes (D5): 0 every id passed; 1 any failed/error/not-run, a failed
aggregator control, or a collection problem; 2 usage error or no module for the
spec; 3 no failures but at least one skipped id (a skip is not evidence).
`make` collapses any non-zero recipe status to 2, so the code is also printed as
`runner exit: N (...)`.

THE OUTPUT CONTRACT AND THE WORD IT MUST NOT CONTAIN (read before editing)
--------------------------------------------------------------------------
The output of this runner must never contain the status word the PM alone
assigns, in any case (AC8). Real claims, findings and node ids that the runner
ECHOES can contain that word, so `_echo` rewrites every echoed string. The word
itself is deliberately assembled from two joined fragments below, so that a
grep of this file's SOURCE for it returns zero. That grep pins the output
contract (nothing in this file speaks that word on the runner's own behalf); it
is not a way of hiding a use. The in-process arms in `tests/test_verify_spec.py`
assert the OUTPUT, including a row whose own text carries the word.

The runner never reads or writes under the planning tree: the audit modules
quote the spec into `claim`, so there is nothing to read there.
"""

from __future__ import annotations

import datetime
import importlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SCRIPTS_DIR: Final[Path] = REPO_ROOT / "scripts"
TESTS_DIR: Final[Path] = REPO_ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from acceptance._model import ACAudit, RedKind  # noqa: E402

PLUGIN: Final[str] = "_verify_outcomes"
OUTCOME_ENV: Final[str] = "PDF_VERIFY_OUTCOMES_FILE"
AGGREGATOR_FILE: Final[str] = "tests/test_acceptance_audit.py"

#: The six PARAMETRIZED arms of the frozen aggregator (one node id per module).
AGGREGATOR_ARMS: Final[tuple[str, ...]] = (
    "test_module_name_matches_declared_spec_id",
    "test_every_covering_node_id_resolves",
    "test_an_unmeasured_ac_names_a_finding",
    "test_the_ac_roster_is_contiguous",
    "test_red_is_substantive",
    "test_every_module_exposes_the_three_declared_names",
)
#: The one GLOBAL (unparametrized) aggregator arm.
ROSTER_ARM: Final[str] = "test_the_audit_roster_is_non_empty"

FOOTER: Final[str] = (
    "This runner grants nothing: qa-sentinel signs the evidence; "
    "project-manager transitions the status."
)

_SPEC_RE: Final[re.Pattern[str]] = re.compile(r"PDF-([0-9]{2,})", re.ASCII)

# See the module docstring: assembled from two literals on purpose.
_FORBIDDEN_WORD: Final[re.Pattern[str]] = re.compile("".join(("ver", "ified")), re.IGNORECASE)
_REPLACEMENT: Final[str] = "[term withheld]"

CLASS_LOCAL: Final[str] = "locally driven"
CLASS_NO_RED: Final[str] = "covered, red NOT observed"
CLASS_CI: Final[str] = "CI-evidenced, not locally driven"
CLASS_COMMAND: Final[str] = "command-evidenced, not driven by this runner"
CLASS_UNREDDENABLE: Final[str] = "UNREDDENABLE: no mutation can red this AC"
CLASS_UNMEASURED: Final[str] = "unmeasured (unclassified)"
CLASSES: Final[tuple[str, ...]] = (
    CLASS_LOCAL,
    CLASS_NO_RED,
    CLASS_CI,
    CLASS_COMMAND,
    CLASS_UNREDDENABLE,
    CLASS_UNMEASURED,
)

TOKEN_CLASSES: Final[tuple[tuple[str, str], ...]] = (
    ("CI-EVIDENCED:", CLASS_CI),
    ("COMMAND:", CLASS_COMMAND),
    ("UNREDDENABLE:", CLASS_UNREDDENABLE),
)

EXIT_MEANING: Final[dict[int, str]] = {
    0: "every requested id and every aggregator control passed",
    1: "a failed, errored or not-run id, a failed aggregator control, or a collection problem",
    2: "usage error or no audit module for this spec",
    3: "no failures, but skipped ids are present; a skip is not evidence",
}


def _echo(text: str) -> str:
    """Make an echoed string safe to print: one line, no forbidden word."""
    return _FORBIDDEN_WORD.sub(_REPLACEMENT, " ".join(text.split()))


# --------------------------------------------------------------------------- #
# Pure functions
# --------------------------------------------------------------------------- #


def parse_spec(arg: str) -> str | None:
    """`PDF-85` -> `85`; anything off-grammar (`PDF-5`, `85`, `PDF-NOPE`) -> None."""
    match = _SPEC_RE.fullmatch(arg)
    return match.group(1) if match else None


def module_path_for(digits: str) -> Path:
    return TESTS_DIR / "acceptance" / f"audit_pdf_{digits}.py"


def stem_of(module: ModuleType) -> str:
    return module.__name__.rsplit(".", 1)[-1]


def _ids_from_rows(stem: str, audit: Sequence[ACAudit]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for row in audit:
        for node_id in row.covering:
            seen.setdefault(node_id, None)
    return (*seen, *aggregator_ids_for(stem))


def node_ids_for(module: ModuleType) -> tuple[str, ...]:
    """Covering ids (de-duplicated, first-seen order), the six aggregator ids for
    this module, then the global roster arm."""
    return _ids_from_rows(stem_of(module), module.AUDIT)


def aggregator_ids_for(module_stem: str) -> tuple[str, ...]:
    return (
        *(f"{AGGREGATOR_FILE}::{arm}[{module_stem}]" for arm in AGGREGATOR_ARMS),
        f"{AGGREGATOR_FILE}::{ROSTER_ARM}",
    )


def classify(row: ACAudit) -> str:
    """The evidence class (D4). A `red` token wins over the covering rules."""
    for token, label in TOKEN_CLASSES:
        if row.red.startswith(token):
            return label
    if row.covering:
        return CLASS_NO_RED if row.red_kind is RedKind.NOT_OBSERVED else CLASS_LOCAL
    return CLASS_UNMEASURED


def exit_code(outcomes: Mapping[str, str], requested: Sequence[str], pytest_rc: int = 0) -> int:
    """0 / 1 / 3 per D5 (2 is decided before any run). Token classes never enter."""
    states = [outcomes.get(node_id, "not-run") for node_id in requested]
    if pytest_rc != 0 or any(s in ("failed", "error", "not-run") for s in states):
        return 1
    if any(s == "skipped" for s in states):
        return 3
    return 0


def _covering_cell(row: ACAudit, outcomes: Mapping[str, str]) -> str:
    if not row.covering:
        return "-"
    states = Counter(outcomes.get(node_id, "not-run") for node_id in row.covering)
    cell = f"{states['passed']}/{len(row.covering)} passed"
    extras = [f"{states[s]} {s}" for s in ("skipped", "failed", "error", "not-run") if states[s]]
    return f"{cell} ({', '.join(extras)})" if extras else cell


def _ac_order(row: ACAudit) -> int:
    digits = re.sub(r"\D", "", row.ac)
    return int(digits) if digits else 0


@dataclass(frozen=True, slots=True)
class Header:
    spec_id: str
    module_path: str
    head: str
    python: str
    utc: str


def render(
    header: Header,
    module_stem: str,
    audit: Sequence[ACAudit],
    outcomes: Mapping[str, str],
    pytest_rc: int = 0,
) -> str:
    """The whole table as a string. Pure: every input is a parameter."""
    requested = _ids_from_rows(module_stem, audit)
    code = exit_code(outcomes, requested, pytest_rc)
    lines = [
        f"spec:    {_echo(header.spec_id)}",
        f"module:  {_echo(header.module_path)}",
        f"head:    {_echo(header.head)}",
        f"python:  {_echo(header.python)}",
        f"utc:     {_echo(header.utc)}",
        "",
        "AC | class | covering | red_kind | finding | claim",
    ]
    counts: Counter[str] = Counter()
    for row in sorted(audit, key=_ac_order):
        label = classify(row)
        counts[label] += 1
        lines.append(
            " | ".join(
                (
                    _echo(row.ac),
                    label,
                    _covering_cell(row, outcomes),
                    row.red_kind.value,
                    _echo(row.finding or "-"),
                    _echo(row.claim)[:60],
                )
            )
        )
    lines += ["", "aggregator controls:"]
    lines += [
        f"  {_echo(node_id)}: {outcomes.get(node_id, 'not-run')}"
        for node_id in aggregator_ids_for(module_stem)
    ]
    lines += ["", "classes:"]
    lines += [f"  {label}: {counts[label]}" for label in CLASSES]
    unsettled = [
        (node_id, outcomes.get(node_id, "not-run"))
        for node_id in requested
        if outcomes.get(node_id, "not-run") != "passed"
    ]
    if unsettled:
        lines += ["", "ids not passed (a skip is not evidence):"]
        lines += [f"  {state}: {_echo(node_id)}" for node_id, state in unsettled]
    if pytest_rc != 0:
        lines += ["", f"pytest exit code: {pytest_rc}"]
    lines += ["", f"runner exit: {code} ({EXIT_MEANING[code]})", FOOTER]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Side-effecting shell
# --------------------------------------------------------------------------- #

USAGE: Final[str] = (
    "usage: make verify SPEC=PDF-NN   (or: python scripts/verify_spec.py PDF-NN)\n"
    "  PDF-NN is `PDF-` plus two or more digits, e.g. PDF-85"
)


def run_pytest(node_ids: Sequence[str]) -> tuple[int, dict[str, str], str]:
    """ONE pytest subprocess; returns (exit code, {nodeid: outcome}, output tail)."""
    workdir = Path(tempfile.mkdtemp(prefix="pdf-verify-"))
    try:
        target = workdir / "outcomes.json"
        env = dict(os.environ)
        env[OUTCOME_ENV] = str(target)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(SCRIPTS_DIR), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
        )
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", PLUGIN, "-p", "no:cacheprovider", *node_ids],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        outcomes: dict[str, str] = {}
        if target.exists():
            outcomes = json.loads(target.read_text(encoding="utf-8"))
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-15:])
        return proc.returncode, outcomes, tail
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _git_head() -> str:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    return done.stdout.strip() or "unknown"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    digits = parse_spec(args[0]) if len(args) == 1 else None
    if digits is None:
        shown = _echo(" ".join(args)) if args else "<none>"
        print(f"{USAGE}\n  got: {shown}", file=sys.stderr)
        return 2
    path = module_path_for(digits)
    relative = path.relative_to(REPO_ROOT).as_posix()
    if not path.is_file():
        print(
            f"PDF-{digits} is unaudited: there is no {relative}\n"
            "  (unaudited is not the same as failing; no evidence has been written for it)",
            file=sys.stderr,
        )
        return 2
    stem = path.stem
    module = importlib.import_module(f"acceptance.{stem}")
    audit: tuple[ACAudit, ...] = tuple(module.AUDIT)
    ids = node_ids_for(module)
    rc, outcomes, tail = run_pytest(ids)
    header = Header(
        spec_id=f"PDF-{digits}",
        module_path=relative,
        head=_git_head(),
        python=platform.python_version(),
        utc=datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    print(render(header, stem, audit, outcomes, rc))
    if rc not in (0, 1):
        print(f"\npytest output tail:\n{_echo_block(tail)}", file=sys.stderr)
    return exit_code(outcomes, ids, rc)


def _echo_block(text: str) -> str:
    return "\n".join(_FORBIDDEN_WORD.sub(_REPLACEMENT, line) for line in text.splitlines())


if __name__ == "__main__":
    sys.exit(main())
