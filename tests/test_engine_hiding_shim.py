"""PDF-46 — the engine-hiding shim reclaims its own directory, and can be seen to.

`0b672c634e`: `tests/conftest.py::_apply_engine_hiding_shim` called `mkdtemp()`
and registered no teardown of any kind, then replaced `PATH` with the result.
`pytest_configure` calls it ABOVE the `workerinput` early-return, so the leak
ran in the controller AND in every xdist worker: `1 + N` directories per
invocation, `N` being whatever the project default `-n auto` resolves to. That
multiplier is the whole reason this row outranks its three `x1` siblings.

WHY THIS IS A NEW MODULE
------------------------
`tests/test_gate_budget.py` is the natural-looking home and it is another
spec's surface this cycle. A new file costs nothing and collides with nobody.

THE THING THIS FILE IS MOST AT RISK OF DOING WRONG
---------------------------------------------------
Every delta arm below asserts a ZERO, and a zero is a claim requiring proof
rather than a result. A child session that never applied the shim leaves zero
directories; a host with the keep-switch already exported leaves zero
"differences". Both would render a green that measured nothing.

So no arm here asserts a zero alone. Each runs the SAME command TWICE, one
environment variable apart, asserts BOTH readings, and asserts that they
DIFFER. If the fixed arm and the keep arm agree, the instrument is broken and
the test says so in those words -- it does not report a clean run.

THE SELF-MATCH CLASS, AND THE THREE NEEDLES THIS FILE NEVER SPELLS
-------------------------------------------------------------------
Three guards below census the tree for a string. A guard whose own source is
inside its own search space reads itself and passes for the wrong reason. All
three needles are therefore assembled at runtime from fragments and never
appear as literals here:

* the family glob (`SHIM_GLOB`)          -- AC12
* the recursive-force shell delete       -- AC11
* nothing else; the keep-switch name IS spelled, deliberately, because its
  census (AC7) covers the `Makefile`, the workflows, `addopts` and the
  gate-parity declaration -- surfaces this file is not part of.

HOW THE "DRIVEN ONCE" REDS BECAME SHIPPED REDS
-----------------------------------------------
The spec allows three controls (AC1, AC2, AC6) to be driven by hand against a
byte-restored copy at landing. They are stronger as standing arms, so each is
shipped instead: the mutation is applied to a COPY OF THE SOURCE TEXT held in
memory and the checker is re-run against it. The working tree is never
modified, nothing is stashed, and nothing has to be remembered a wave later.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFTEST = REPO_ROOT / "tests" / "conftest.py"
MAKEFILE = REPO_ROOT / "Makefile"
PYPROJECT = REPO_ROOT / "pyproject.toml"
GATE_PARITY = REPO_ROOT / ".github" / "gate-parity.toml"
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
REAPER = REPO_ROOT / "scripts" / "reap_shims.py"

KEEP_ENV = "PDF_TOOLKIT_TEST_KEEP_SHIM"
HIDE_ENV = "PDF_TOOLKIT_TEST_HIDE_ENGINES"

#: The directory-name prefix, and the glob an incautious "cleanup" would reach
#: for. Assembled, never spelled -- see the module docstring.
SHIM_PREFIX = "pdftoolkit" + "-hide-engines-"
SHIM_GLOB = SHIM_PREFIX + "*"

#: The child session the delta arms run. Small, engine-free, and it exercises
#: a real session rather than `--collect-only`: measured at this spec's
#: landing, `--collect-only` does NOT start xdist workers, so a collect-only
#: parallel arm would report `1` where a real one reports `N + 1` and the
#: multiplier -- the entire point of AC4 -- would go unobserved.
CHILD_TARGET = "tests/test_assert_skips.py"


def _load_reaper() -> Any:
    spec = importlib.util.spec_from_file_location("reap_shims_under_test", REAPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reaper = _load_reaper()


# --------------------------------------------------------------------------- #
# AST helpers over `tests/conftest.py` — AC1 and AC6
# --------------------------------------------------------------------------- #


def _function_named(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"tests/conftest.py declares no top-level `{name}`")


def _is_call_to(node: ast.AST, dotted: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}" == dotted
    if isinstance(func, ast.Name):
        return func.id == dotted
    return False


def _is_path_assignment(node: ast.AST) -> bool:
    """`os.environ["PATH"] = ...` and nothing else."""
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        return False
    target = node.targets[0]
    if not isinstance(target, ast.Subscript):
        return False
    value = target.value
    if not (isinstance(value, ast.Attribute) and value.attr == "environ"):
        return False
    key = target.slice
    return isinstance(key, ast.Constant) and key.value == "PATH"


def shim_statement_order(source: str) -> dict[str, int]:
    """Line numbers of the three statements AC1 constrains, in *source*.

    Returned as a mapping rather than asserted here so the same function can be
    run against a deliberately mutated copy and shown to change its answer.
    """
    fn = _function_named(ast.parse(source), "_apply_engine_hiding_shim")
    order: dict[str, int] = {}
    for node in ast.walk(fn):
        if "register" not in order and _is_call_to(node, "atexit.register"):
            order["register"] = node.lineno
        if "walk" not in order and isinstance(node, ast.For):
            order["walk"] = node.lineno
        if "path_assignment" not in order and _is_path_assignment(node):
            order["path_assignment"] = node.lineno
    return order


def hooks_that_reclaim(source: str) -> list[str]:
    """Pytest hooks in *source* that perform the reclaim. Must be empty (AC6)."""
    tree = ast.parse(source)
    offenders: list[str] = []
    for hook in ("pytest_sessionfinish", "pytest_unconfigure"):
        try:
            fn = _function_named(tree, hook)
        except AssertionError:
            continue
        for node in ast.walk(fn):
            if _is_call_to(node, "shutil.rmtree") or _is_call_to(
                node, "_reclaim_engine_hiding_shim"
            ):
                offenders.append(f"{hook}:{node.lineno}")
    return offenders


def test_the_reclaim_is_registered_before_the_walk_and_before_the_path_swap() -> None:
    """AC1. `mkdtemp` has already created the directory by the time the walk
    starts, so a registration placed after the walk leaks whenever the walk or
    the `PATH` assignment raises."""
    order = shim_statement_order(CONFTEST.read_text())
    assert set(order) == {"register", "walk", "path_assignment"}, (
        f"could not locate all three statements; found {sorted(order)}. The shim "
        "must register an `atexit` reclaim, walk PATH, and reassign PATH"
    )
    assert order["register"] < order["walk"] < order["path_assignment"], (
        "the atexit registration must come FIRST: it is registered at line "
        f"{order['register']}, the symlink walk at {order['walk']}, the PATH "
        f"assignment at {order['path_assignment']}. Registered after either of "
        "them, a directory mkdtemp already created is leaked whenever the walk "
        "or the assignment raises"
    )


def test_the_registration_order_check_can_see_a_reordered_registration() -> None:
    """AC1's RED, shipped rather than driven once.

    The mutation is applied to a COPY OF THE SOURCE TEXT. The working tree is
    not touched, nothing is stashed and nothing is checked out.
    """
    source = CONFTEST.read_text()
    lines = source.splitlines(keepends=True)
    body = next(i for i, line in enumerate(lines) if "atexit.register(_reclaim" in line)
    # The registration is GUARDED, so the guard travels with it -- moving the
    # call alone would leave an `if` with no body and the mutated copy would
    # fail to parse, which is a broken control rather than a red one.
    block = lines[body - 1 : body + 1]
    assert block[0].strip().startswith("if not os.environ.get("), (
        f"expected the keep-switch guard above the registration; saw {block[0]!r}"
    )
    remaining = lines[: body - 1] + lines[body + 1 :]
    moved: list[str] = []
    for line in remaining:
        moved.append(line)
        if line.strip() == 'os.environ["PATH"] = str(shim_dir)':
            moved.extend(block)
    mutated = "".join(moved)
    assert mutated != source, "the mutation did not apply; this control proves nothing"
    order = shim_statement_order(mutated)
    assert not (order["register"] < order["walk"] < order["path_assignment"]), (
        "the ordering check is blind: the registration was moved BELOW the PATH "
        "assignment and the check still reported the correct order"
    )


def test_no_pytest_hook_performs_the_reclaim() -> None:
    """AC6, and the reason is in the same file rather than in this docstring.

    `pytest_sessionfinish` calls `_tracked_files_manifest()`, which shells out
    to `git ls-files` THROUGH the shimmed PATH and returns `None` on `OSError`,
    on which the hook returns early. A teardown placed in a pytest hook can
    therefore remove the directory before `git` is resolved through it: the
    working-tree guard would not fail, it would stop guarding, silently. That
    is this product's own headline failure mode -- a silent wrong answer with a
    success exit code -- manufactured by a resource-leak fix.
    """
    offenders = hooks_that_reclaim(CONFTEST.read_text())
    assert offenders == [], (
        f"a pytest hook performs the shim reclaim at {offenders}. `atexit` "
        "callbacks run LIFO and this registration happens in pytest_configure, "
        "so the reclaim already runs strictly AFTER pytest_sessionfinish. A hook "
        "races the working-tree guard's `git ls-files` for no benefit at all"
    )


def test_the_hook_placement_check_can_see_a_planted_reclaim() -> None:
    """AC6's RED, shipped. Planted in a copy of the source, never on disk."""
    source = CONFTEST.read_text()
    anchor = "def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:\n"
    assert anchor in source, "the sessionfinish signature moved; re-derive this anchor"
    planted = source.replace(anchor, anchor + '    shutil.rmtree("/nonexistent")\n')
    assert planted != source, "the mutation did not apply; this control proves nothing"
    offenders = hooks_that_reclaim(planted)
    assert any(entry.startswith("pytest_sessionfinish") for entry in offenders), (
        "the hook-placement guard is blind: a `shutil.rmtree` was planted inside "
        f"pytest_sessionfinish and the guard reported {offenders}"
    )


# --------------------------------------------------------------------------- #
# AC2 — PATH is restored BEFORE the directory is removed
# --------------------------------------------------------------------------- #


def test_the_reclaim_restores_path_before_it_removes_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2.

    The end state alone cannot distinguish the two orderings -- swap the
    statements and `PATH` is still restored and the directory is still gone.
    So `shutil.rmtree` is intercepted and `PATH` is read AT CALL TIME. A
    control that cannot tell the two orderings apart is a control for neither.
    """
    import conftest

    # `import shutil` here would bind the SAME module object conftest holds, so
    # monkeypatching `conftest.shutil.rmtree` would also replace the function
    # this shim calls to do the real removal -- infinite recursion, not a
    # measurement. The original is captured by reference BEFORE the patch.
    original_rmtree = conftest.shutil.rmtree

    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    (shim_dir / "git").symlink_to(sys.executable)

    original_path = "/usr/bin:/bin"
    monkeypatch.setenv("PATH", str(shim_dir))

    observed: list[str] = []

    def recording_rmtree(target: Any, **kwargs: Any) -> None:
        observed.append(os.environ["PATH"])
        original_rmtree(target, **kwargs)

    monkeypatch.setattr(conftest.shutil, "rmtree", recording_rmtree)
    conftest._reclaim_engine_hiding_shim(str(shim_dir), original_path)

    assert observed == [original_path], (
        "at the moment the tree was removed, PATH was "
        f"{observed!r} rather than the captured original. PATH must be restored "
        "FIRST, so no window exists in which PATH names a directory that is gone"
    )
    assert not shim_dir.exists(), "the reclaim left its own directory behind"
    assert os.environ["PATH"] == original_path


def test_the_ordering_control_would_fail_on_the_swapped_implementation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2's RED, shipped: the swapped order is executed and shown to be caught.

    Without this, the arm above is a control whose discriminating power has
    never been demonstrated -- which is the exact defect class this repository
    files against its own instruments.
    """
    import shutil as real_shutil

    shim_dir = tmp_path / "swapped"  # not patched here; the real rmtree is wanted
    shim_dir.mkdir()
    original_path = "/usr/bin:/bin"
    monkeypatch.setenv("PATH", str(shim_dir))
    observed: list[str] = []

    def swapped_reclaim(target: str, restore: str) -> None:
        observed.append(os.environ["PATH"])  # what a recording rmtree would see
        real_shutil.rmtree(target, ignore_errors=True)
        os.environ["PATH"] = restore

    swapped_reclaim(str(shim_dir), original_path)

    assert observed == [str(shim_dir)], (
        "the swapped implementation was expected to be observed removing the "
        f"tree while PATH still named it; observed {observed!r}"
    )
    assert observed != [original_path], (
        "the swapped and correct orderings are indistinguishable to this "
        "instrument, so the arm above proves nothing"
    )


# --------------------------------------------------------------------------- #
# AC3, AC4, AC8 — the delta arms, in a private TMPDIR, both readings asserted
# --------------------------------------------------------------------------- #


def _count_shims(root: Path) -> int:
    return len([entry for entry in root.iterdir() if entry.name.startswith(SHIM_PREFIX)])


def _run_child_session(scratch: Path, *, keep: bool, workers: str) -> tuple[int, int]:
    """Run one child pytest session in a private TMPDIR; return (count, rc).

    D4: the measurement is ISOLATED rather than attributed. On a shared host the
    count over `/tmp` is contaminated from three directions -- a sibling agent
    session, another product's sweep, and `systemd-tmpfiles-clean.timer`
    reclaiming old entries daily -- so a shared reading can go NEGATIVE for a
    reason that has nothing to do with the gate. Nothing else on the host knows
    this path, so the "before" is zero by construction and the "after" is
    attributable by construction.

    The private directory is removed here because this function created it
    (OR-13). Leaving it would make a leak fix that leaks: the keep arm's
    directory holds a couple of thousand symlinks.
    """
    private = scratch / f"tmpdir-{'keep' if keep else 'fixed'}-n{workers}"
    private.mkdir()
    env = dict(os.environ)
    env["TMPDIR"] = str(private)
    env[HIDE_ENV] = "soffice"
    # Cleared EXPLICITLY, never merely left unset: a developer with the switch
    # exported would otherwise turn the fixed arm green in the wrong direction.
    env.pop(KEEP_ENV, None)
    if keep:
        env[KEEP_ENV] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            CHILD_TARGET,
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "-n",
            workers,
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    count = _count_shims(private)
    reaper.shutil.rmtree(private, ignore_errors=True)
    return count, completed.returncode


def _assert_paired(fixed: int, kept: int, *, expected_kept: int, arm: str) -> None:
    """AC8. Both readings, and they must DIFFER."""
    assert fixed != kept, (
        f"{arm}: the fixed arm and the keep arm both read {fixed}. This is NOT a "
        f"clean run -- it means the child never applied the shim, or {KEEP_ENV} "
        "was already exported into it, so the zero below was never measuring the "
        "teardown. An instrument that cannot see the defect cannot clear it"
    )
    assert kept == expected_kept, (
        f"{arm}: with {KEEP_ENV} set the child left {kept} shim director(ies), "
        f"expected {expected_kept}. The multiplier is being OBSERVED here, not "
        "described; a different number means the session shape changed"
    )
    assert fixed == 0, (
        f"{arm}: the child left {fixed} shim director(ies) behind with the "
        "teardown active. `0b672c634e` is back"
    )


def test_a_serial_child_session_leaves_no_shim_directory(tmp_path: Path) -> None:
    """AC3 + AC8 at `-n 0`, the easy half, with its shipped RED beside it."""
    fixed, fixed_rc = _run_child_session(tmp_path, keep=False, workers="0")
    kept, kept_rc = _run_child_session(tmp_path, keep=True, workers="0")
    assert fixed_rc == 0 and kept_rc == 0, (
        f"the child sessions did not pass (rc {fixed_rc} / {kept_rc}); a failed "
        "child can leave a count for a reason unrelated to the teardown"
    )
    _assert_paired(fixed, kept, expected_kept=1, arm="-n 0")


def test_a_parallel_child_session_leaves_no_shim_directory(tmp_path: Path) -> None:
    """AC4 + AC8 at `-n 2` — the arm that matters, and the one a spec proving
    only `-n 0` has skipped.

    `-n auto` is the project default, declared once in `pyproject.toml`'s
    `addopts`, and the leak's cost lives entirely in that multiplier: the shim
    is applied in `pytest_configure`, ABOVE the `workerinput` early-return, so
    the controller and every worker each built one. `-n 2` is used rather than
    `auto` because `auto` resolves to the host's core count and an assertion
    hard-coding one host's answer fails on the next box; `2` is deterministic
    everywhere, and `2 + 1` still observes the multiplier rather than
    describing it.
    """
    fixed, fixed_rc = _run_child_session(tmp_path, keep=False, workers="2")
    kept, kept_rc = _run_child_session(tmp_path, keep=True, workers="2")
    assert fixed_rc == 0 and kept_rc == 0, (
        f"the child sessions did not pass (rc {fixed_rc} / {kept_rc})"
    )
    _assert_paired(fixed, kept, expected_kept=3, arm="-n 2")


# --------------------------------------------------------------------------- #
# AC7 — the keep-switch has exactly one source, and no gate sets it
# --------------------------------------------------------------------------- #


def _addopts(text: str) -> str:
    match = re.search(r"^addopts\s*=\s*\"([^\"]*)\"", text, re.MULTILINE)
    return match.group(1) if match else ""


def keep_switch_sites(
    makefile: str, workflows: dict[str, str], addopts: str, parity: str
) -> list[str]:
    """Every gate-side surface that names the keep switch. Must be empty."""
    offenders: list[str] = []
    for number, line in enumerate(makefile.splitlines(), start=1):
        if KEEP_ENV in line:
            offenders.append(f"Makefile:{number}")
    for name, text in sorted(workflows.items()):
        for number, line in enumerate(text.splitlines(), start=1):
            if KEEP_ENV in line:
                offenders.append(f"{name}:{number}")
    if KEEP_ENV in addopts:
        offenders.append("pyproject.toml:addopts")
    for number, line in enumerate(parity.splitlines(), start=1):
        if KEEP_ENV in line:
            offenders.append(f"gate-parity.toml:{number}")
    return offenders


def test_no_gate_surface_sets_the_keep_switch() -> None:
    """AC7. The switch reinstates the leak by design, which is exactly why a
    gate must never set it: a `Makefile` recipe or a workflow step carrying it
    would turn every arm above green while the defect ran."""
    offenders = keep_switch_sites(
        MAKEFILE.read_text(),
        {path.name: path.read_text() for path in WORKFLOWS},
        _addopts(PYPROJECT.read_text()),
        GATE_PARITY.read_text(),
    )
    assert offenders == [], (
        f"{KEEP_ENV} is set by a gate surface at {offenders}. It is a debug and "
        "control switch only; its sole sources are tests/conftest.py (which "
        "READS it), this module, and TESTING.md (which documents it)"
    )


def test_the_keep_switch_census_can_see_a_planted_setting() -> None:
    """AC7's RED, planted on a copy of the Makefile text rather than on disk."""
    planted = MAKEFILE.read_text().replace(
        "test: ## Run the test suite\n",
        f"test: ## Run the test suite\n\t@{KEEP_ENV}=1 true\n",
    )
    offenders = keep_switch_sites(planted, {}, "", "")
    assert any(entry.startswith("Makefile:") for entry in offenders), (
        "the census is blind: the switch was planted on the `test` recipe and "
        f"the census returned {offenders}"
    )


def test_the_keep_switch_is_read_in_exactly_one_place() -> None:
    """The complement of the census above: the switch has ONE reader, so its
    semantics cannot diverge between two call sites."""
    lines = CONFTEST.read_text().splitlines()
    definitions = [
        f"tests/conftest.py:{number}"
        for number, line in enumerate(lines, start=1)
        if KEEP_ENV in line and "Final[str]" in line
    ]
    readers = [
        f"tests/conftest.py:{number}"
        for number, line in enumerate(lines, start=1)
        if "_KEEP_ENV" in line and "Final[str]" not in line and not line.lstrip().startswith("#")
    ]
    assert len(definitions) == 1, (
        f"the literal {KEEP_ENV} must be spelled exactly once, at its constant "
        f"definition; found {definitions}"
    )
    assert len(readers) == 1, (
        f"expected exactly one read of the keep-switch constant; found {readers}. "
        "Two readers is two places its semantics can diverge"
    )


# --------------------------------------------------------------------------- #
# AC9 — `make shim-reap` exists, is documented, is phony, gates nothing
# --------------------------------------------------------------------------- #

GATE_TARGETS = ("clean", "test", "cover", "ci", "engines-gate", "docs-gate")


def makefile_prerequisites(text: str) -> dict[str, list[str]]:
    rules: dict[str, list[str]] = {}
    for match in re.finditer(r"^([a-zA-Z0-9_.-]+):([^=\n]*)$", text, re.MULTILINE):
        name, rest = match.group(1), match.group(2)
        rules[name] = rest.split("##")[0].split()
    return rules


def test_the_reaper_target_is_declared_documented_and_phony() -> None:
    """AC9's first half."""
    text = MAKEFILE.read_text()
    assert re.search(r"^shim-reap:.*?## ", text, re.MULTILINE), (
        "`shim-reap` has no `## ` doc comment, so `make help` will not list it "
        "and test_makefile_documents_exactly_the_expected_targets will fail"
    )
    phony = re.search(r"^\.PHONY:((?:.*\\\n)*.*)$", text, re.MULTILINE)
    assert phony is not None and "shim-reap" in phony.group(1), (
        "`shim-reap` is missing from .PHONY; it produces no file of that name"
    )


def test_the_reaper_is_a_prerequisite_of_nothing() -> None:
    """AC9's second half, and the one worth having.

    Parsed, not read. A reaper that had quietly become part of `clean` or `ci`
    would delete a CONCURRENT session's live shim directory, and the symptom
    would present as a flake in an unrelated test -- the hardest possible way
    to find this out.
    """
    rules = makefile_prerequisites(MAKEFILE.read_text())
    offenders = [name for name in GATE_TARGETS if "shim-reap" in rules.get(name, [])]
    assert offenders == [], (
        f"`shim-reap` is a prerequisite of {offenders}. It is opt-in, operator-"
        "driven and a prerequisite of nothing; a gate that reaps would race any "
        "concurrent session on the same host"
    )


def test_the_prerequisite_check_can_see_a_planted_dependency() -> None:
    """AC9's RED, on a copy of the Makefile text."""
    planted = MAKEFILE.read_text().replace(
        "ci: fmt-check lint typecheck cover licenses sast vulncheck ## ",
        "ci: fmt-check lint typecheck cover licenses sast vulncheck shim-reap ## ",
    )
    rules = makefile_prerequisites(planted)
    assert "shim-reap" in rules.get("ci", []), (
        "the prerequisite parser is blind: `shim-reap` was planted on `ci`'s "
        f"prerequisite list and the parser returned {rules.get('ci')}"
    )


# --------------------------------------------------------------------------- #
# AC10, AC11 — the reaper's predicates, one planted survivor class at a time
# --------------------------------------------------------------------------- #


def _plant(root: Path, name: str, *, age_days: float) -> Path:
    directory = root / name
    directory.mkdir()
    (directory / "git").symlink_to(sys.executable)
    stamp = time.time() - age_days * reaper.SECONDS_PER_DAY
    os.utime(directory, (stamp, stamp))
    return directory


def _synthetic_root(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    planted = {
        "old": _plant(root, SHIM_PREFIX + "old00000", age_days=5),
        "young": _plant(root, SHIM_PREFIX + "young000", age_days=0.1),
        "near_miss": _plant(root, SHIM_PREFIX.rstrip("-") + "Xtra0000", age_days=5),
        "outside": _plant(outside, SHIM_PREFIX + "outside0", age_days=5),
    }
    link = root / (SHIM_PREFIX + "symlink0")
    link.symlink_to(planted["outside"])
    planted["symlink"] = link
    return planted


def test_the_default_invocation_removes_nothing(tmp_path: Path, capsys: Any) -> None:
    """AC10. The default is the safe one; the destructive path needs a word
    typed. Every planted directory survives, and each is NAMED in the listing
    with its age and its non-dereferenced byte size."""
    planted = _synthetic_root(tmp_path)
    rc = reaper.main(["--root", str(tmp_path / "root")])
    out = capsys.readouterr().out

    assert rc == 0
    for label, path in planted.items():
        assert path.exists(), f"the default invocation removed the {label} directory"
    assert planted["old"].name in out, "the listing did not name the reapable directory"
    assert "REAPABLE" in out and "too young" in out, (
        f"the listing must distinguish what WOULD be reaped from what would not; it printed:\n{out}"
    )
    assert "nothing was removed" in out


def test_confirm_removes_exactly_the_qualifying_set(tmp_path: Path) -> None:
    """AC11. Each survivor class is asserted INDIVIDUALLY, so a loosened
    predicate reddens by name rather than by a single aggregate count."""
    planted = _synthetic_root(tmp_path)
    rc = reaper.main(["--root", str(tmp_path / "root"), "--confirm", "--min-age-days", "1"])

    assert rc == 0
    assert not planted["old"].exists(), "the old, exact-prefix, real directory was not removed"
    assert planted["young"].exists(), (
        "a directory below the age floor was removed. A young one may belong to "
        "a LIVE session on this host, which the reaper has no way to tell"
    )
    assert planted["near_miss"].exists(), (
        f"a near-miss name ({planted['near_miss'].name}) was removed; the prefix "
        "match must be exact"
    )
    assert planted["symlink"].is_symlink(), "a symlink wearing the prefix was removed"
    assert planted["outside"].exists(), (
        "a directory OUTSIDE the given root was removed -- the symlink wearing "
        "the prefix pointed at it, so the reaper followed a link out of its root"
    )


def test_the_reaper_never_shells_out_to_a_recursive_force_delete() -> None:
    """AC11 / E7.

    The needle is assembled at runtime. Spelled as a literal, this guard would
    find itself in its own subject and pass for the wrong reason -- and the
    `Makefile` recipe is inside that subject too.
    """
    needle = "rm" + " -rf"
    subjects = {"scripts/reap_shims.py": REAPER.read_text()}
    recipe = re.search(r"^shim-reap:.*\n((?:\t.*\n)*)", MAKEFILE.read_text(), re.MULTILINE)
    assert recipe is not None, "the `shim-reap` recipe could not be located"
    subjects["Makefile:shim-reap recipe"] = recipe.group(1)

    offenders = [name for name, text in subjects.items() if needle in text]
    assert offenders == [], (
        f"{offenders} use a recursive-force shell delete. The agent layer's "
        "git_safety_guard.py REFUSES that form, so the target would be usable "
        "by a human and inert for the sentinel that most needs it. `shutil."
        "rmtree` is the mechanism"
    )
    assert "rmtree" in subjects["scripts/reap_shims.py"], (
        "the reaper does not call shutil.rmtree at all, so the assertion above "
        "passed for the wrong reason"
    )


# --------------------------------------------------------------------------- #
# AC12 — nothing else globs the family prefix
# --------------------------------------------------------------------------- #

#: The only files allowed to name the family glob. OR-13: an interpreter
#: reclaims its OWN directory and nothing else, and a glob-and-delete anywhere
#: else is how a resource-leak fix turns into someone else's data loss.
GLOB_ALLOWED = frozenset({"scripts/reap_shims.py", "tests/test_engine_hiding_shim.py"})


def tracked_files() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.split()


def glob_sites(paths: list[str], extra: dict[str, str] | None = None) -> list[str]:
    offenders: list[str] = []
    sources: dict[str, str] = {}
    for relpath in paths:
        if relpath in GLOB_ALLOWED:
            continue
        absolute = REPO_ROOT / relpath
        try:
            sources[relpath] = absolute.read_text()
        except (OSError, UnicodeDecodeError):
            continue
    sources.update(extra or {})
    for relpath, text in sources.items():
        for number, line in enumerate(text.splitlines(), start=1):
            if SHIM_GLOB in line:
                offenders.append(f"{relpath}:{number}")
    return sorted(offenders)


def test_nothing_outside_the_reaper_globs_the_family_prefix() -> None:
    """AC12. `tests/test_pagerange.py` already writes the rule down at the
    sibling call site that shipped first: a glob reaches directories this
    process never created, and those belong to whoever ran the suite before."""
    offenders = glob_sites(tracked_files())
    assert offenders == [], (
        f"{offenders} glob the shim family prefix. Only the operator-invoked "
        "reaper may, and only under --confirm, above an age floor, on exact "
        "prefix matches, directly under a root it was given"
    )


def test_the_glob_census_can_see_a_planted_glob() -> None:
    """AC12's RED. Without it the arm above is a negative assertion that has
    never been shown able to fire."""
    offenders = glob_sites([], extra={"tests/conftest.py": f'shutil.rmtree("/tmp/{SHIM_GLOB}")\n'})
    assert offenders == ["tests/conftest.py:1"], (
        f"the glob census is blind: a planted glob returned {offenders}"
    )
