#!/usr/bin/env python3
"""Run the `--help` wall-clock budget serially and never trust a skip -- PDF-117.

`tests/test_cli_spine.py::test_help_stays_within_the_startup_budget` is the only
control that sees `--help` LATENCY, and it abstains on every xdist worker, so it
never runs under the default `-n auto`. The advisory `startup-latency` CI job
(`make startup-gate`) runs that one node, alone, serially. This script is the
wrapper that makes "alone, serially" mean something.

**Why a wrapper and not a bare `pytest -n 0`.** The test has a SECOND abstention
branch (the host is not quiet). When it fires, bare `pytest -n 0` exits 0 with
`1 skipped`, so a step that trusts the exit code is green on a regression: the
`PDF-26`/`B-203` class, a guard blind in the direction it guards. So this script
reads the JUnit receipt and classifies it. Every class ends in exactly one
outcome:

* measured, within budget            -> exit 0
* failed (the budget was exceeded)   -> exit 1, **never retried**: a failure is
  a verdict and is final
* skipped for the LOAD reason        -> wait and re-run, bounded (7 attempts,
  20 s apart); still skipped on the last attempt -> exit 1 `ABSTAINED -- not
  measured`. A skip carries no verdict, so waiting for one is not a
  re-run-until-green
* skipped for ANY other reason       -> exit 1 `ABSTAINED -- misconfigured`, once
* no matching testcase at all        -> exit 1 `NOT COLLECTED`, once

The script never computes load itself, holds no copy of the quiet fraction and
imports nothing from `tests/`: the test's own abstention is the definition of
"not admissible". The one coupling is `LOAD_ABSTENTION_PREFIX`, pinned by an arm
in `tests/test_gate_budget.py` against the reason's wording.

Stdlib only. The JUnit file lives in a temp directory, never the repo root.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

NODE = "tests/test_cli_spine.py::test_help_stays_within_the_startup_budget"
TESTCASE_NAME = "test_help_stays_within_the_startup_budget"

#: Contract with `startup_gate_abstention_reason()`: the load branch's reason
#: opens with exactly this. Pinned by tests/test_gate_budget.py.
LOAD_ABSTENTION_PREFIX = "host not quiet:"
MAX_ATTEMPTS = 7
SETTLE_SECONDS = 20.0

Runner = Callable[[], str | None]
Sleeper = Callable[[float], None]


def classify(junit_xml: str | None) -> tuple[str, str, str]:
    """Return `(kind, detail, reading)` for one JUnit receipt.

    `kind` is one of `measured`, `failed`, `load-skip`, `other-skip`,
    `not-collected`. `reading` is the `STARTUP-READING` line, or "".
    """
    if not junit_xml:
        return "not-collected", "no JUnit receipt was written", ""
    try:
        root = ET.fromstring(junit_xml)
    except ET.ParseError as exc:
        return "not-collected", f"unparseable JUnit receipt: {exc}", ""
    cases = [case for case in root.iter("testcase") if case.get("name") == TESTCASE_NAME]
    if len(cases) != 1:
        return "not-collected", f"{len(cases)} matching testcases (expected exactly 1)", ""
    case = cases[0]
    reading = ""
    for out in case.iter("system-out"):
        for line in (out.text or "").splitlines():
            if line.startswith("STARTUP-READING"):
                reading = line.strip()
    for tag in ("failure", "error"):
        node = case.find(tag)
        if node is not None:
            text = node.get("message") or (node.text or "").strip()
            return "failed", " ".join(text.split()), reading
    skipped = case.find("skipped")
    if skipped is not None:
        message = skipped.get("message") or (skipped.text or "").strip()
        if message.startswith(LOAD_ABSTENTION_PREFIX):
            return "load-skip", message, reading
        return "other-skip", message, reading
    return "measured", "", reading


def run_node() -> str | None:
    """Run the node once, serially (`-n 0`, never `-p no:xdist`); return the JUnit text."""
    with tempfile.TemporaryDirectory(prefix="startup-gate-") as tmp:
        junit = Path(tmp) / "junit.xml"
        command = [
            sys.executable, "-m", "pytest", "-n", "0", "-p", "no:cacheprovider",
            "-o", "junit_logging=system-out", "--junitxml", str(junit), NODE,
        ]  # fmt: skip
        subprocess.run(command, cwd=REPO_ROOT, check=False)
        return junit.read_text(encoding="utf-8") if junit.exists() else None


def _summary(lines: list[str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def gate(
    run: Runner = run_node,
    sleep: Sleeper = time.sleep,
    emit: Callable[[str], None] = print,
    loadavg: Callable[[], float] = lambda: os.getloadavg()[0],
) -> int:
    """Drive the bounded settle-on-abstention rule; return the process exit code."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        kind, detail, reading = classify(run())
        if kind == "measured":
            first = "startup-latency: MEASURED"
            emit(first)
            emit(reading)
            _summary([first, reading])
            return 0
        if kind == "failed":
            first = f"startup-latency: BUDGET EXCEEDED -- {detail}"
        elif kind == "other-skip":
            first = f"startup-latency: ABSTAINED -- misconfigured: {detail}"
        elif kind == "not-collected":
            first = f"startup-latency: NOT COLLECTED -- {detail}"
        elif attempt == MAX_ATTEMPTS:
            first = f"startup-latency: ABSTAINED -- not measured: {detail}"
        else:
            emit(
                f"startup-latency: waiting for a quiet host (attempt {attempt}/{MAX_ATTEMPTS}, "
                f"loadavg {loadavg():.2f}): {detail}"
            )
            sleep(SETTLE_SECONDS)
            continue
        emit(first)
        if reading:
            emit(reading)
        _summary([first, reading] if reading else [first])
        return 1
    raise AssertionError("unreachable: the last attempt always returns")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(gate())
