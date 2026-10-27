"""PDF-146 D4: the pool's teardown record is faithful on both platforms.

Two questions the PDF-131 signal arms cannot answer from their own record:

* **B-508 (the escalated arm without ``/proc``).** The executor's manager thread
  reaps a SIGKILLed worker concurrently, so ``Process.is_alive()`` can read
  ``alive`` for a pid that is already gone. On Linux ``/proc`` names that pid
  ``stale-liveness``. On macOS there is no ``/proc``, so the tail read
  ``undetermined`` and the arm reddened. ``procpool._terminate_pool`` now falls
  back to an ``os.kill(pid, 0)`` presence probe. The forced arm below hides
  ``/proc`` on Linux so the same code path runs on every host.
* **D0 test (a): does the census undercount escalation?** ``sigkill="not-needed"``
  is derived from ``Process.is_alive()``, so it means the worker exited. The exit
  arm asserts that every such worker exited by its OWN unwind (status 143), never
  by a SIGKILL the record cannot see.

PDF-131's helpers are imported, never edited: its file is byte-identical. Each arm
prefixes the launcher program in THIS module only, by patching the imported
module's ``_LAUNCHER`` global, so the prefix wraps ``_terminate_pool`` before
PDF-131's launcher captures it and writes a side record with the fields the
launcher's own record drops. No ``test_*`` name is imported, so nothing is
collected twice; the autouse ``declared_load`` fixture is imported by name so the
declared band applies here too.

The literal temp prefix is never spelled here.
"""

from __future__ import annotations

import json
import signal
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Final

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

import test_rasterize_signals as _signals  # noqa: E402
from test_rasterize_signals import (  # noqa: E402
    _LAUNCHER,
    _assert_signal_death_observed,
    _send_signal_and_measure,
    declared_load,  # noqa: F401  (an autouse fixture: imported so the declared band applies)
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        sys.platform.startswith("win"),
        reason="os.killpg/SIGTERM teardown is POSIX-only (B-055); no Windows job",
    ),
]

#: One template, two baked-in mode literals (the mode cannot travel in the record
#: path, which PDF-131's frozen helper builds itself, nor in argv or the env).
#: ``noproc`` makes ``_kernel_state`` read a missing ``proc_root``: the macOS
#: condition on a Linux host. Either way the wrapper calls the real
#: ``_terminate_pool`` and writes ``<record_path>.pdf146.json`` (0600, fsync).
_PREFIX_TEMPLATE: Final[str] = """
import json, os, sys
from pdf_tooling.ops import procpool

_PDF146_MODE = "__MODE__"
_pdf146_side = sys.argv[1] + ".pdf146.json"
_pdf146_real = procpool._terminate_pool
_pdf146_kernel = procpool._kernel_state

if _PDF146_MODE == "noproc":
    def _pdf146_hidden(pid, proc_root="/pdf146-no-such-proc-root"):
        return _pdf146_kernel(pid, "/pdf146-no-such-proc-root")

    procpool._kernel_state = _pdf146_hidden


def _pdf146_wrapped(executor, **kwargs):
    report = _pdf146_real(executor, **kwargs)
    outcomes = [
        {
            "pid": o.pid,
            "sigkill": o.sigkill,
            "liveness_after": o.liveness_after,
            "tail": o.tail,
            "kernel": o.kernel,
            "exitcode_after": o.exitcode_after,
            "join_timeout_s": o.join_timeout_s,
            "join_elapsed_s": o.join_elapsed_s,
        }
        for o in report.outcomes
    ]
    fd = os.open(_pdf146_side, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps({"outcomes": outcomes}).encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    return report


procpool._terminate_pool = _pdf146_wrapped
"""
_PREFIX_NOPROC: Final[str] = _PREFIX_TEMPLATE.replace("__MODE__", "noproc")
_PREFIX_PROC: Final[str] = _PREFIX_TEMPLATE.replace("__MODE__", "proc")


def _side_outcomes(tmp_path: Path) -> list[dict[str, Any]]:
    """The wrapper's side record, which PDF-131's launcher does not carry."""
    path = tmp_path / "teardown-record.json.pdf146.json"
    assert path.exists(), f"the PDF-146 prefix wrote no side record at {path}"
    loaded = json.loads(path.read_text())
    outcomes = loaded.get("outcomes")
    assert isinstance(outcomes, list) and outcomes, f"the side record lists no workers: {loaded}"
    return outcomes


def test_pdf146_forced_escalation_without_proc_names_every_reaped_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_signals, "_LAUNCHER", _PREFIX_NOPROC + _LAUNCHER)

    measured = _send_signal_and_measure(tmp_path, signal.SIGTERM, force=True)
    _assert_signal_death_observed(measured, signal.SIGTERM, forced=True)

    outcomes = _side_outcomes(tmp_path)
    raced = [o for o in outcomes if o["liveness_after"] == "alive"]
    for outcome in raced:
        assert outcome["kernel"] == "absent" and outcome["tail"] == "stale-liveness", (
            f"a worker the manager thread had already reaped was not named as such "
            f"without /proc: {outcome}"
        )
        print(
            "PDF-146 forced arm race exercised: "
            f"liveness_after={outcome['liveness_after']} kernel={outcome['kernel']} "
            f"tail={outcome['tail']} join_elapsed_s={outcome['join_elapsed_s']:.6f}"
            f"/{outcome['join_timeout_s']:.3f}"
        )
    print(f"PDF-146 forced arm without proc: outcomes={len(outcomes)} raced={len(raced)}")


def test_pdf146_unescalated_workers_exited_by_their_own_unwind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_signals, "_LAUNCHER", _PREFIX_PROC + _LAUNCHER)

    measured = _send_signal_and_measure(tmp_path, signal.SIGTERM)
    _assert_signal_death_observed(measured, signal.SIGTERM)

    outcomes = _side_outcomes(tmp_path)
    unescalated = [o for o in outcomes if o["sigkill"] == "not-needed"]
    expected = 128 + signal.SIGTERM
    for outcome in unescalated:
        assert outcome["exitcode_after"] == expected, (
            f"a worker recorded as not escalated died by {outcome['exitcode_after']}, not by "
            f"its own unwind ({expected}): {outcome}"
        )
    counts = Counter(o["exitcode_after"] for o in unescalated)
    tally = ",".join(f"{code}:{counts[code]}" for code in sorted(counts))
    print(
        f"PDF-146 teardown exits: SIGTERM not-needed={len(unescalated)}/{len(outcomes)} "
        f"exitcodes={tally}"
    )
