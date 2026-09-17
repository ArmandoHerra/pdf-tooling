"""The fixture wiring: the generated corpus, the golden primitive, engine
markers, the engines-hiding PATH shim, the working-tree guard, the hypothesis
profile, and the `samples` fixture (`PLAN.md` §10 / §10.1).
`tests/fs_snapshot.py` says this file does not exist yet on purpose — the
fixture wiring is PDF-06's.

The `PLAN.md` §10.1 originals-integrity guard (rule 3) lives in its own module,
`tests/samples_guard.py`, and is registered here as a plugin
(`pytest_plugins`) rather than defined inline — see that module's docstring
for why.

The hypothesis block below is PDF-77's and belongs HERE rather than in a test
module: it is in force for every property in the suite whatever is selected
and whatever order collection lands in, which is the property the arrangement
it replaced did not have.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import pytest
from hypothesis import settings
from hypothesis.configuration import set_hypothesis_home_dir
from hypothesis.database import DirectoryBasedExampleDatabase

from corpus import Corpus, build_corpus

pytest_plugins = ["samples_guard"]

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
GOLDEN_DIR: Final[Path] = REPO_ROOT / "tests" / "golden"

__all__: list[str] = []

# --------------------------------------------------------------------------- #
# Hypothesis: the storage redirect, the profile, and the example database.
#
# THIS BLOCK BELONGS TO THE SUITE, NOT TO A MODULE, AND THE PLACEMENT IS THE
# FIX. `conftest.py` is imported before any test module is collected, so a
# profile loaded here is in force for every `@settings(...)` decorator in the
# suite regardless of which modules are selected or what order they sort in.
# The same block lived at the head of `tests/test_pagerange.py` until PDF-77,
# where it reached `tests/unit/test_name_template.py` only because that module
# sorts LATER: `pytest tests/unit/test_name_template.py` on its own wrote
# hypothesis's cache into the repository root, which `PLAN.md` §10 forbids in
# terms (`B-147`). A fix in a second module would have rebuilt the same
# alphabetical accident one file over.
#
# `d8233d4cc9`: the mkdtemp() below used to run with no teardown at all. The
# atexit hook removes THIS interpreter's directory and nothing else --
# deliberately not a glob over `pdf-toolkit-pagerange-hypothesis-*`, which
# would reach directories this process never created. Those belong to whoever
# ran the suite before (OR-13), and a glob-and-delete is how a resource-leak
# fix turns into someone else's data loss. The prefix keeps its original
# spelling byte-for-byte on the move: it is part of a frozen population
# (`tests/test_brand_surfaces.py`'s class H), so re-spelling it here would move
# a count this spec has no business moving.
# --------------------------------------------------------------------------- #

HYPOTHESIS_HOME_DIR: str = tempfile.mkdtemp(prefix="pdf-toolkit-pagerange-hypothesis-")
set_hypothesis_home_dir(HYPOTHESIS_HOME_DIR)
atexit.register(shutil.rmtree, HYPOTHESIS_HOME_DIR, ignore_errors=True)

#: An explicit location for the example database, in the house `PDF_TOOLING_*`
#: spelling that `PDF_TOOLING_TEST_HIDE_ENGINES` and `PDF_TOOLING_TEST_KEEP_SHIM`
#: already use.
HYPOTHESIS_DB_ENV: Final[str] = "PDF_TOOLING_HYPOTHESIS_DB"

#: Selects a registered profile by name. The default is the only one any gate
#: surface loads; the derandomized sibling exists for bisecting a suspected
#: flake by hand and is never a default, because freezing every property into
#: one permanent set of inputs trades away the search that found this project's
#: only property-discovered defect (PDF-77 D5).
HYPOTHESIS_PROFILE_ENV: Final[str] = "PDF_TOOLING_HYPOTHESIS_PROFILE"

DEFAULT_HYPOTHESIS_PROFILE: Final[str] = "pdf_tooling"


def hypothesis_database_dir() -> Path:
    """Where shrunk counterexamples persist -- outside the repository, always.

    The home directory above holds rebuildable caches (the Unicode charmap,
    the constants cache) and is reclaimed at interpreter exit. The example
    database holds the counterexamples that make a property failure
    RECOVERABLE, so it must survive the process; conflating the two is why
    reclaiming the home directory used to destroy the database with it. They
    are resolved independently here.

    A database inside the checkout would re-open `B-147` wearing a different
    name, so a path that lands there is refused at import time, loudly, rather
    than silently relocated to somewhere safe.
    """
    raw = os.environ.get(HYPOTHESIS_DB_ENV)
    if raw:
        resolved = Path(raw).expanduser().resolve()
    else:
        cache_home = os.environ.get("XDG_CACHE_HOME")
        base = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
        resolved = (base / "pdf-tooling" / "hypothesis-examples").resolve()
    if resolved.is_relative_to(REPO_ROOT):
        raise RuntimeError(
            f"the hypothesis example database resolves to {resolved}, which is INSIDE "
            f"the repository tree at {REPO_ROOT}. No test may write into the checkout "
            f"(PLAN.md §10). Point {HYPOTHESIS_DB_ENV} somewhere outside the "
            "repository, or unset it to use $XDG_CACHE_HOME/pdf-tooling/."
        )
    # Created here rather than left to hypothesis's first write, so the path
    # the run header names is a path that exists: a developer told where the
    # replay came from should not have to work out whether the directory is
    # missing or merely empty. Strictly AFTER the containment check above, so
    # a hostile override never gets as far as creating anything.
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


HYPOTHESIS_DATABASE_DIR: Final[Path] = hypothesis_database_dir()

# The profile carries ONLY what the decorators do not set. `max_examples`,
# `deadline` and `phases` are deliberately absent: the property decorators own
# the first two and `tests/test_pagerange.py`'s named-invariant control reads
# them back off each of P1-P5, and the default phase list is what makes an
# `@example` guaranteed (`Phase.explicit`) and a persisted database worth
# having (`Phase.reuse`). A profile that narrowed `phases` would silently
# disarm both.
settings.register_profile(
    DEFAULT_HYPOTHESIS_PROFILE,
    database=DirectoryBasedExampleDatabase(str(HYPOTHESIS_DATABASE_DIR)),
    print_blob=True,
)
# No `database=` on this one, and that is hypothesis's rule rather than a
# choice: `derandomize=True` implies `database=None`, and passing both is an
# InvalidArgument at registration. Measured, not assumed -- the first draft of
# this block passed both and failed at collection.
settings.register_profile(
    "pdf_tooling_derandomized",
    print_blob=True,
    derandomize=True,
)

ACTIVE_HYPOTHESIS_PROFILE: Final[str] = (
    os.environ.get(HYPOTHESIS_PROFILE_ENV) or DEFAULT_HYPOTHESIS_PROFILE
)
settings.load_profile(ACTIVE_HYPOTHESIS_PROFILE)


def pytest_report_header(config: pytest.Config) -> str:
    """Name the example database in the run's own output.

    A persisted database means a developer can inherit a red from an EARLIER
    run's counterexample while CI is green. That is the feature working as
    designed, and it is only diagnosable if the reader can see where the
    replay came from and how to clear it without opening this file.
    """
    return (
        f"hypothesis: profile {ACTIVE_HYPOTHESIS_PROFILE}, example database at "
        f"{HYPOTHESIS_DATABASE_DIR} -- a property that reds here may be replaying a "
        "counterexample recorded by an earlier run; remove that directory to clear "
        f"it, or set {HYPOTHESIS_DB_ENV} to relocate it"
    )


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
    from pdf_tooling.ports import PORTS

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
# The engines-hiding PATH shim — `PDF_TOOLING_TEST_HIDE_ENGINES=tesseract,soffice`.
#
# Reproducible, and it NEVER touches the host: every executable reachable on
# the current PATH is symlinked into a fresh scratch directory under $TMPDIR
# except the named ones, and PATH is repointed at that directory. No system
# binary is ever renamed, moved, or chmod-ed (AC13). Applied in
# `pytest_configure` -- BEFORE collection -- rather than as a fixture, because
# the `requires(engine)` skip decision below is made at collection time and
# must see the hidden PATH, not the host's real one.
# --------------------------------------------------------------------------- #

_HIDE_ENV: Final[str] = "PDF_TOOLING_TEST_HIDE_ENGINES"

#: PDF-46 D6. Set to a non-empty value, the reclaim below is NOT registered and
#: the shim directory survives the interpreter -- i.e. the pre-PDF-46 behaviour,
#: on purpose. It exists so the delta-0 arms can be shown RED on every suite run
#: instead of once, by hand, at landing: a child session that never applied the
#: shim leaves 0 directories too, so `0` alone proves nothing. It is a foot-gun
#: and it is censused (`tests/test_engine_hiding_shim.py`): no Makefile recipe,
#: no workflow, no `addopts` and no gate-parity entry may set it.
_KEEP_ENV: Final[str] = "PDF_TOOLING_TEST_KEEP_SHIM"


def _reclaim_engine_hiding_shim(shim_dir: str, original_path: str) -> None:
    """Restore `PATH`, THEN remove this interpreter's own shim directory.

    `0b672c634e`: `_apply_engine_hiding_shim()` below used to `mkdtemp()` with no
    teardown at all -- no `TemporaryDirectory`, no `atexit`, no fixture -- and
    `pytest_configure` calls it ABOVE the `workerinput` early-return, so under
    the project's default `-n auto` every run leaked one directory per xdist
    worker PLUS one for the controller.

    Two properties, both of which have a control that can see them go wrong:

    * **The order.** `PATH` is restored BEFORE the tree is removed, so no window
      exists in which `PATH` names a directory that is already gone. Swapping
      the two statements leaves the same end state, so the control monkeypatches
      `shutil.rmtree` and reads `PATH` at call time rather than afterwards.
    * **Own directory only.** This removes the path it was handed and never
      globs the family prefix -- the literal glob form is deliberately not
      spelled here, because `tests/test_engine_hiding_shim.py` censuses the
      tree for it and a comment saying "no glob" would be read as one. OR-13,
      and `tests/test_pagerange.py` already writes down why: a glob reaches
      directories this process never created, and a glob-and-delete is how a
      resource-leak fix turns into someone else's data loss. On this host
      `/tmp` also holds another product's sentinel sandboxes.

    `reset_cache()` is deliberately NOT called here. The registry memoization
    exists to serve resolution DURING the session; at interpreter exit there is
    no consumer left to serve, and importing `pdf_tooling.ports` during teardown
    would buy a new failure mode for no benefit.
    """
    os.environ["PATH"] = original_path
    shutil.rmtree(shim_dir, ignore_errors=True)


def _apply_engine_hiding_shim() -> None:
    hide_raw = os.environ.get(_HIDE_ENV)
    if not hide_raw:
        return
    hidden = {name.strip() for name in hide_raw.split(",") if name.strip()}
    shim_dir = Path(tempfile.mkdtemp(prefix="pdftoolkit-hide-engines-"))
    original_path = os.environ.get("PATH", "")
    # PDF-46 D1/D3. Registered HERE -- before the walk and before the PATH
    # assignment -- so a directory `mkdtemp` already created is reclaimed even
    # if the walk or the assignment raises. `atexit` and not a pytest hook:
    # callbacks run LIFO, this registration happens in `pytest_configure`, so
    # the reclaim runs strictly AFTER `pytest_sessionfinish` -- which resolves
    # `git` through this very PATH (`_tracked_files_manifest()`) and returns
    # None on OSError, i.e. a teardown that beat it there would silently blind
    # the working-tree guard instead of failing. `_KEEP_ENV` skips the
    # registration on purpose; it is this fix's shipped red control.
    if not os.environ.get(_KEEP_ENV):
        atexit.register(_reclaim_engine_hiding_shim, str(shim_dir), original_path)
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
    from pdf_tooling.ports import reset_cache

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
    config._pdftooling_worktree_before = _tracked_files_manifest()  # type: ignore[attr-defined]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    if hasattr(config, "workerinput"):
        return
    before: dict[str, str] | None = getattr(config, "_pdftooling_worktree_before", None)
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
    config._pdftooling_worktree_findings = findings  # type: ignore[attr-defined]
    if findings:
        session.exitstatus = 1


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    findings = getattr(config, "_pdftooling_worktree_findings", None)
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
    "PDF_TOOLING_SAMPLES_DIR not set — real-document arm skipped (PLAN.md §10.1 rule 5)"
)

_SAMPLES_ENV: Final[str] = "PDF_TOOLING_SAMPLES_DIR"


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
    """Copy-on-use over `$PDF_TOOLING_SAMPLES_DIR` — `PLAN.md` §10.1 rules 1-2.

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
            from pdf_tooling.ports import resolve

            report = resolve(port)
            if not report.available:
                reason = f"{engine} unavailable (port {port}); install with: {report.hint}"
                item.add_marker(pytest.mark.skip(reason=reason))

        if not samples_available and item.get_closest_marker("samples") is not None:
            item.add_marker(pytest.mark.skip(reason=SAMPLES_SKIP_REASON))
