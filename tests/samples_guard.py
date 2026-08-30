"""`PLAN.md` §10.1 rule 3 — the originals-integrity guard.

**The highest-consequence code in this spec** (Design §8). `$PDF_TOOLKIT_SAMPLES_DIR`
holds the operator's real, partly irreplaceable documents; `PLAN.md` §12 R-16 is
the risk this module exists to close. At session start it writes a SHA-256 +
size + mtime manifest of every file in the directory; at session end it
re-hashes and **fails the session, naming the file** — never a warning, never
a log line, never a summary count.

Split out of `conftest.py` on purpose. `tests/test_samples_guard.py`'s AC16(b)
arm proves the guard fires by running an **inner** pytest session against a
**synthetic** samples directory (never the operator's real corpus — ruling
X-25) whose one test deliberately writes to a fake "original". That inner run
needs this exact mechanism, not a re-implementation of it, so this module is
independently loadable as a pytest plugin
(``pytest_plugins = ["samples_guard"]``) from a conftest.py that is not this
suite's own — it depends on nothing beyond the standard library and pytest.

THE FAILURE MODE THIS GUARDS AGAINST
-------------------------------------
Under ``pytest -n auto`` every xdist worker AND the controller import this
module and would each run these hooks once, hashing the same directory N+1
times and reporting N+1 times. Worse: a worker's `session.exitstatus` does not
propagate to the controller's exit code the way a controller-level exitstatus
does, so a check that runs *only* on a worker can go completely unseen. The
guard is therefore **controller-only** — `if hasattr(config, "workerinput")`
is true exactly on a worker, so every hook below returns immediately there.
Getting this wrong means the guard silently does not run under the suite's
own default parallelism, which is exactly the "green run that proved
nothing" failure class this spec exists to prevent.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

__all__ = ["ManifestEntry", "build_manifest", "diff_manifest"]

_ENV_VAR = "PDF_TOOLKIT_SAMPLES_DIR"

#: (size, mtime_ns, sha256) — see `diff_manifest`'s docstring for why each field
#: is there.
ManifestEntry = tuple[int, int, str]


def build_manifest(root: Path) -> dict[str, ManifestEntry]:
    """A SHA-256 + size + mtime manifest of every file under *root*.

    Keyed by path relative to *root*, so the manifest is portable across the
    two calls even if the absolute path happens to differ (it never should,
    but a relative key is the honest contract either way).
    """
    manifest: dict[str, ManifestEntry] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        status = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest[str(path.relative_to(root))] = (status.st_size, status.st_mtime_ns, digest)
    return manifest


def diff_manifest(before: dict[str, ManifestEntry], after: dict[str, ManifestEntry]) -> list[str]:
    """Every way *after* differs from *before* — human-readable, FILE-NAMING.

    Content-hash mismatches are reported ahead of size/mtime ones: a changed
    hash is the fact that actually matters, and it implies the other two, so
    leading with it is what makes the terminal report read as a cause rather
    than a pile of symptoms.
    """
    findings: list[str] = []
    for relpath in sorted(set(before) - set(after)):
        findings.append(f"{relpath}: removed")
    for relpath in sorted(set(after) - set(before)):
        findings.append(f"{relpath}: added")
    for relpath in sorted(set(before) & set(after)):
        before_size, before_mtime, before_hash = before[relpath]
        after_size, after_mtime, after_hash = after[relpath]
        if before_hash != after_hash:
            findings.append(f"{relpath}: content changed")
        elif before_size != after_size:
            findings.append(f"{relpath}: size changed")
        elif before_mtime != after_mtime:
            findings.append(f"{relpath}: mtime changed")
    return findings


def _samples_root() -> Path | None:
    raw = os.environ.get(_ENV_VAR)
    if not raw:
        return None
    root = Path(raw)
    return root if root.is_dir() else None


# --------------------------------------------------------------------------- #
# The pytest hooks — controller-only, `pytest_sessionfinish` + `pytest_terminal_summary`
# rather than a fixture finalizer, so a violation is a loud terminal report and
# a forced non-zero session exit, not an easily-missed teardown error.
# --------------------------------------------------------------------------- #


def pytest_configure(config: pytest.Config) -> None:
    if hasattr(config, "workerinput"):
        return
    root = _samples_root()
    config._pdftoolkit_samples_root = root  # type: ignore[attr-defined]
    config._pdftoolkit_samples_before = build_manifest(root) if root is not None else None  # type: ignore[attr-defined]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    if hasattr(config, "workerinput"):
        return
    root: Path | None = getattr(config, "_pdftoolkit_samples_root", None)
    before: dict[str, ManifestEntry] | None = getattr(config, "_pdftoolkit_samples_before", None)
    if root is None or before is None:
        return
    after = build_manifest(root)
    findings = diff_manifest(before, after)
    config._pdftoolkit_samples_findings = findings  # type: ignore[attr-defined]
    if findings:
        session.exitstatus = 1


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    findings = getattr(config, "_pdftoolkit_samples_findings", None)
    if not findings:
        return
    terminalreporter.section("PLAN.md §10.1 rule 3 -- an original changed during this run")
    for line in findings:
        terminalreporter.write_line(f"  - {line}")
    terminalreporter.write_line(
        f"{len(findings)} file(s) under $PDF_TOOLKIT_SAMPLES_DIR changed during this test run. "
        "This is a defect in the tool or the test that touched it -- never the samples "
        "directory itself (PLAN.md §10.1 rule 3, PLAN.md §12 R-16)."
    )
