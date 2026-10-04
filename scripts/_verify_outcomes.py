"""The pytest plugin behind `scripts/verify_spec.py` (PDF-106 D3).

It is loaded with `-p _verify_outcomes` (the runner puts `scripts/` on the
subprocess's `PYTHONPATH`, because `scripts/` is not a package) and records one
outcome per EXACT node id: `passed | failed | error | skipped`.

WHY A PLUGIN AND NOT `--junitxml`. A JUnit report carries `classname` and
`name`, not a node id, and rebuilding the id from them is lossy for
`tests/unit/...` paths and for class-nested tests. That is the PDF-06 AC11 rot
shape in a new place. `report.nodeid` is the id pytest itself prints, so the
map is keyed on what the audit modules copy-pasted from `--collect-only`.

WHY THE CONTROLLER ONLY. Under the project's `-n auto`, the xdist controller
receives every worker's report and calls `pytest_runtest_logreport` for it. A
worker also calls the hook locally, so registering the recorder in a worker
too would write a second, partial map. `pytest_configure` therefore registers
the recorder only when `config.workerinput` is absent.

Reduction across a test's phases (setup, call, teardown), worst wins:
a setup or teardown failure is `error`; a call failure is `failed`; a skip in
any phase is `skipped`; otherwise `passed`. An id that never produced a report
is simply absent from the map; the runner reads that absence as `not-run`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Final

#: The runner sets this to the path the recorder writes its JSON map to.
OUTCOME_ENV: Final[str] = "PDF_VERIFY_OUTCOMES_FILE"

#: Worst wins when one node id has several phase reports.
_RANK: Final[dict[str, int]] = {"passed": 0, "skipped": 1, "failed": 2, "error": 3}


def phase_outcome(when: str, outcome: str) -> str:
    """Reduce ONE phase report to `passed | failed | error | skipped`."""
    if outcome == "failed":
        return "failed" if when == "call" else "error"
    if outcome == "skipped":
        return "skipped"
    return "passed"


class OutcomeRecorder:
    """Accumulates `{nodeid: outcome}`; callable in-process with any object
    carrying `nodeid`, `when` and `outcome` (a real `TestReport` or a stand-in)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.outcomes: dict[str, str] = {}

    def pytest_runtest_logreport(self, report: Any) -> None:
        new = phase_outcome(report.when, report.outcome)
        old = self.outcomes.get(report.nodeid)
        if old is None or _RANK[new] > _RANK[old]:
            self.outcomes[report.nodeid] = new

    def pytest_sessionfinish(self, session: Any) -> None:
        if self.path is not None:
            self.path.write_text(json.dumps(self.outcomes, sort_keys=True), encoding="utf-8")


def pytest_configure(config: Any) -> None:
    target = os.environ.get(OUTCOME_ENV)
    if not target or hasattr(config, "workerinput"):
        return
    config.pluginmanager.register(OutcomeRecorder(Path(target)), "pdf-verify-outcomes")
