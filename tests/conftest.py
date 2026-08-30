"""The fixture wiring: the generated corpus, the golden primitive, engine
markers, the engines-hiding PATH shim, the working-tree guard, and the
`samples` fixture (`PLAN.md` §10 / §10.1). `tests/fs_snapshot.py` says this
file does not exist yet on purpose — the fixture wiring is PDF-06's.

The `PLAN.md` §10.1 originals-integrity guard (rule 3) lives in its own module,
`tests/samples_guard.py`, and is registered here as a plugin
(`pytest_plugins`) rather than defined inline — see that module's docstring
for why.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import pytest

from corpus import Corpus, build_corpus

pytest_plugins = ["samples_guard"]

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
GOLDEN_DIR: Final[Path] = REPO_ROOT / "tests" / "golden"

__all__: list[str] = []

# --------------------------------------------------------------------------- #
# pytest options
# --------------------------------------------------------------------------- #


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Regenerate tests/golden/ files instead of comparing against them.",
    )


# --------------------------------------------------------------------------- #
# The generated corpus (Machine A) — session-scoped, built once, into
# pytest's own tmp_path_factory scratch. Never into the repo tree.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Corpus:
    return build_corpus(tmp_path_factory.mktemp("corpus"))


# --------------------------------------------------------------------------- #
# The golden primitive — thin, parsed-dict comparison, `--update-golden`.
# Approved beyond the two-machine framing (X-23): six wave-5 specs dispatch
# immediately after this one and would otherwise each invent a convention.
#
# `Golden.compare` NEVER writes on an ordinary run, missing or not — only
# `--update-golden` writes. Anything else would make a plain `pytest` able to
# create a file under `tests/golden/`, which is exactly the "a test writes
# into the repo tree" violation the working-tree guard below exists to catch.
# --------------------------------------------------------------------------- #


def _display(path: Path) -> str:
    """A message-friendly path: relative to the repo when possible, absolute
    otherwise -- `Golden` is also exercised directly against a `tmp_path`
    directory by its own unit tests, which are never under `REPO_ROOT`."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


class Golden:
    """Compare a payload against `tests/golden/<name>.json`, as parsed dicts."""

    def __init__(self, directory: Path, *, update: bool) -> None:
        self._directory = directory
        self._update = update

    def compare(self, name: str, payload: Mapping[str, Any]) -> None:
        path = self._directory / f"{name}.json"
        if self._update:
            self._directory.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            return
        if not path.is_file():
            pytest.fail(
                f"no golden file at {_display(path)} -- re-run with "
                "--update-golden to create it, then review the diff before committing"
            )
        expected = json.loads(path.read_text())
        assert payload == expected, (
            f"golden mismatch for {name!r} against {_display(path)} "
            "(re-run with --update-golden to regenerate, then review the diff)"
        )


@pytest.fixture
def golden(request: pytest.FixtureRequest) -> Golden:
    return Golden(GOLDEN_DIR, update=bool(request.config.getoption("--update-golden")))


# --------------------------------------------------------------------------- #
# Engine markers that skip VISIBLY, resolved through the same ports.resolve()
# the CLI uses (`PLAN.md` §5.5) — never an independent shutil.which.
# --------------------------------------------------------------------------- #

#: The friendly names a spec writes in `@pytest.mark.requires("tesseract")`,
#: mapped to the port they gate. A bare port name (`"OcrEngine"`) also works.
_ENGINE_ALIASES: Final[dict[str, str]] = {
    "tesseract": "OcrEngine",
    "soffice": "OfficeConverter",
    "libreoffice": "OfficeConverter",
}


def _resolve_port(engine: str) -> str:
    from pdf_toolkit.ports import PORTS

    if engine in PORTS:
        return engine
    try:
        return _ENGINE_ALIASES[engine]
    except KeyError:
        known = ", ".join(sorted({*PORTS, *_ENGINE_ALIASES}))
        raise ValueError(
            f"requires({engine!r}): not a known engine or port; known: {known}"
        ) from None


# --------------------------------------------------------------------------- #
# The engines-hiding PATH shim — `PDF_TOOLKIT_TEST_HIDE_ENGINES=tesseract,soffice`.
#
# Reproducible, and it NEVER touches the host: every executable reachable on
# the current PATH is symlinked into a fresh scratch directory under $TMPDIR
# except the named ones, and PATH is repointed at that directory. No system
# binary is ever renamed, moved, or chmod-ed (AC13). Applied in
# `pytest_configure` -- BEFORE collection -- rather than as a fixture, because
# the `requires(engine)` skip decision below is made at collection time and
# must see the hidden PATH, not the host's real one.
# --------------------------------------------------------------------------- #

_HIDE_ENV: Final[str] = "PDF_TOOLKIT_TEST_HIDE_ENGINES"


def _apply_engine_hiding_shim() -> None:
    hide_raw = os.environ.get(_HIDE_ENV)
    if not hide_raw:
        return
    hidden = {name.strip() for name in hide_raw.split(",") if name.strip()}
    shim_dir = Path(tempfile.mkdtemp(prefix="pdftoolkit-hide-engines-"))
    original_path = os.environ.get("PATH", "")
    for entry in original_path.split(os.pathsep):
        entry_path = Path(entry)
        if not entry_path.is_dir():
            continue
        try:
            candidates = list(entry_path.iterdir())
        except OSError:
            continue
        for exe in candidates:
            if exe.name in hidden:
                continue
            link = shim_dir / exe.name
            if link.exists():
                continue
            try:
                link.symlink_to(exe)
            except OSError:
                continue
    os.environ["PATH"] = str(shim_dir)
    # The registry memoizes per process; a PATH change after the first probe
    # must be seen, exactly like `doctor` resetting it before it probes.
    from pdf_toolkit.ports import reset_cache

    reset_cache()


# --------------------------------------------------------------------------- #
# The working-tree guard — `PLAN.md` §10's parallelism bullet: no test writes
# into the repo tree. Tracked files only (`git ls-files`); `.pytest_cache/`,
# coverage data and `.scratch/` legitimately change and would otherwise be
# constant false positives. Controller-only, same reasoning as the originals
# guard in `samples_guard.py`.
# --------------------------------------------------------------------------- #


def _tracked_files_manifest() -> dict[str, str] | None:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    manifest: dict[str, str] = {}
    for relpath in result.stdout.splitlines():
        path = REPO_ROOT / relpath
        if path.is_file():
            manifest[relpath] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def pytest_configure(config: pytest.Config) -> None:
    _apply_engine_hiding_shim()
    if hasattr(config, "workerinput"):
        return
    config._pdftoolkit_worktree_before = _tracked_files_manifest()  # type: ignore[attr-defined]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    if hasattr(config, "workerinput"):
        return
    before: dict[str, str] | None = getattr(config, "_pdftoolkit_worktree_before", None)
    if before is None:
        return
    after = _tracked_files_manifest()
    if after is None:
        return
    findings: list[str] = []
    for relpath in sorted(set(before) - set(after)):
        findings.append(f"{relpath}: removed")
    for relpath in sorted(set(after) - set(before)):
        findings.append(f"{relpath}: added")
    for relpath in sorted(set(before) & set(after)):
        if before[relpath] != after[relpath]:
            findings.append(f"{relpath}: content changed")
    config._pdftoolkit_worktree_findings = findings  # type: ignore[attr-defined]
    if findings:
        session.exitstatus = 1


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    findings = getattr(config, "_pdftoolkit_worktree_findings", None)
    if not findings:
        return
    terminalreporter.section("PLAN.md §10 -- a tracked file changed during this run")
    for line in findings:
        terminalreporter.write_line(f"  - {line}")
    terminalreporter.write_line(
        f"{len(findings)} tracked file(s) changed on disk during this test run -- no test may "
        "write into the repository tree (PLAN.md §10)."
    )


# --------------------------------------------------------------------------- #
# `samples` — the PLAN.md §10.1 real-samples apparatus (Machine B).
# --------------------------------------------------------------------------- #

#: Rule 5's visible-skip reason, named exactly once and reused by every skip
#: site so the wording can never drift between the marker and the fixture.
SAMPLES_SKIP_REASON: Final[str] = (
    "PDF_TOOLKIT_SAMPLES_DIR not set — real-document arm skipped (PLAN.md §10.1 rule 5)"
)

_SAMPLES_ENV: Final[str] = "PDF_TOOLKIT_SAMPLES_DIR"


def samples_root() -> Path | None:
    """The originals directory, or `None` when unset/missing. Test-visible on
    purpose, so `tests/test_samples.py` can assert on availability without
    going through the fixture -- this function itself never returns a path
    that a *fixture consumer* can reach; see `Samples` below for that rule."""
    raw = os.environ.get(_SAMPLES_ENV)
    if not raw:
        return None
    root = Path(raw)
    return root if root.is_dir() else None


class Samples:
    """Copy-on-use over `$PDF_TOOLKIT_SAMPLES_DIR` — `PLAN.md` §10.1 rules 1-2.

    Exposes exactly four PUBLIC members: `available`, `names()`, `copy()`,
    `copy_tree()`. **No public member returns a path under the originals
    root** (AC15) -- the two private attributes below carry the only such
    paths, and nothing this class exposes hands one back. A test cannot pass
    an original to a verb because this fixture will not hand it one.
    """

    def __init__(self, root: Path | None, tmp_path: Path) -> None:
        self._root = root
        self._tmp_path = tmp_path

    @property
    def available(self) -> bool:
        """Corpus present and readable. Checking this never skips."""
        return self._root is not None

    def names(self) -> tuple[str, ...]:
        """Top-level entry NAMES only -- never paths. Empty when unavailable."""
        if self._root is None:
            return ()
        return tuple(sorted(entry.name for entry in self._root.iterdir()))

    def copy(self, name: str) -> Path:
        """A writable copy of one top-level FILE, inside this test's `tmp_path`.

        Skips visibly (rule 5) when the corpus is unavailable -- an unmarked
        test that reaches this still skips instead of erroring. An unknown
        *name* is `pytest.fail`, never `pytest.skip`: "sample present but
        misspelled" is a test bug and must not masquerade as "corpus absent".
        """
        source = self._resolve(name)
        if not source.is_file():
            pytest.fail(f"samples.copy({name!r}) is not a file -- use copy_tree() for a directory")
        destination = self._tmp_path / name
        import shutil

        shutil.copy2(source, destination)
        _make_writable(destination)
        return destination

    def copy_tree(self, name: str) -> Path:
        """A writable copy of one top-level DIRECTORY, inside this test's `tmp_path`."""
        source = self._resolve(name)
        if not source.is_dir():
            pytest.fail(f"samples.copy_tree({name!r}) is not a directory -- use copy() for a file")
        destination = self._tmp_path / name
        import shutil

        shutil.copytree(source, destination)
        for path in destination.rglob("*"):
            if path.is_file():
                _make_writable(path)
        return destination

    def _resolve(self, name: str) -> Path:
        if self._root is None:
            pytest.skip(SAMPLES_SKIP_REASON)
        names = self.names()
        if name not in names:
            pytest.fail(f"no such sample {name!r}; available top-level entries: {names}")
        return self._root / name


def _make_writable(path: Path) -> None:
    """chmod a copy user-writable. A read-only original must not yield a
    read-only copy -- `--in-place` verbs would fail for a confusing reason."""
    mode = path.stat().st_mode
    path.chmod(mode | 0o200)


@pytest.fixture
def samples(tmp_path: Path) -> Samples:
    return Samples(samples_root(), tmp_path)


# --------------------------------------------------------------------------- #
# Marker-driven skips, resolved once at collection time.
# --------------------------------------------------------------------------- #


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    samples_available = samples_root() is not None
    for item in items:
        requires_marker = item.get_closest_marker("requires")
        if requires_marker is not None and requires_marker.args:
            engine = requires_marker.args[0]
            port = _resolve_port(engine)
            from pdf_toolkit.ports import resolve

            report = resolve(port)
            if not report.available:
                reason = f"{engine} unavailable (port {port}); install with: {report.hint}"
                item.add_marker(pytest.mark.skip(reason=reason))

        if not samples_available and item.get_closest_marker("samples") is not None:
            item.add_marker(pytest.mark.skip(reason=SAMPLES_SKIP_REASON))
