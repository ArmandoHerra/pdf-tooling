"""The `AUDIT-CONVENTION(PDF-17)` aggregator gate — PDF-17 Design §9.4.

Six controls over every `tests/acceptance/audit_pdf_*.py` module, discovered by
**glob**: adding an audit module requires zero edits here (AC24).

`PDF-06`'s AC5 and AC11 are why this file exists rather than another markdown
table. Both are mechanized checks written into a spec document; both return the
wrong answer today; **nobody noticed, because nothing runs them** (PDF-17 E8).
An audit convention that is not executed by the test suite reproduces exactly
that failure, so every control below is a real test and
`test_every_covering_node_id_resolves` turns an audit red on the next suite run
when a covering test is renamed or deleted.

Every control is written as a **pure function** taking the audit data as a
parameter rather than reading a module's globals, which is what makes the
"Proof that the gate fires" section at the bottom possible: each control is
proven red against a **synthetic in-memory** `AUDIT` tuple, never by mutating a
real audit module (AC26).
"""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

from acceptance._model import PLACEHOLDER_RED_PHRASES, PLACEHOLDER_REDS, ACAudit, RedKind

ACCEPTANCE_DIR: Final[Path] = Path(__file__).resolve().parent / "acceptance"
MODULE_GLOB: Final[str] = "audit_pdf_*.py"
REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

#: `audit_pdf_06.py` must declare `SPEC_ID = "PDF-06"`.
_MODULE_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^audit_pdf_(\d+)$")


# --------------------------------------------------------------------------- #
# Discovery -- by glob, never a hard-coded module list (AC24)
# --------------------------------------------------------------------------- #


def discover_audit_paths(directory: Path = ACCEPTANCE_DIR) -> tuple[Path, ...]:
    return tuple(sorted(directory.glob(MODULE_GLOB)))


def discover_audit_modules(directory: Path = ACCEPTANCE_DIR) -> tuple[ModuleType, ...]:
    return tuple(
        importlib.import_module(f"acceptance.{path.stem}")
        for path in discover_audit_paths(directory)
    )


def audit_of(module: ModuleType) -> tuple[ACAudit, ...]:
    return tuple(module.AUDIT)


# --------------------------------------------------------------------------- #
# The six controls, as pure functions. Each returns the list of PROBLEMS it
# found; empty means the control passes. Parameterizing on the data rather than
# reading module globals is what lets the red proofs below drive them with a
# synthetic tuple instead of vandalising a real audit module (AC26).
# --------------------------------------------------------------------------- #


def check_roster_is_non_empty(paths: Sequence[Path]) -> list[str]:
    if not paths:
        return [
            f"no {MODULE_GLOB} module was discovered under {ACCEPTANCE_DIR} -- every control "
            "in this file would then iterate an empty roster and pass by doing nothing, "
            "which is the exact defect AUDIT-CONVENTION(PDF-17) exists to end"
        ]
    return []


def check_module_name_matches_spec_id(stem: str, spec_id: str) -> list[str]:
    match = _MODULE_NAME_RE.match(stem)
    if match is None:
        return [f"{stem}: module name does not match {MODULE_GLOB!r}"]
    expected = f"PDF-{match.group(1)}"
    if spec_id != expected:
        return [
            f"{stem}: declares SPEC_ID={spec_id!r} but its filename says {expected!r} -- "
            "a renamed module without its constant, or the reverse"
        ]
    return []


def check_covering_node_ids_resolve(
    spec_id: str, audit: Iterable[ACAudit], live_node_ids: frozenset[str]
) -> list[str]:
    problems = []
    for row in audit:
        for node_id in row.covering:
            if node_id not in live_node_ids:
                problems.append(
                    f"{spec_id} {row.ac}: covering node id {node_id!r} does not resolve in a "
                    "live pytest collection -- the covering test was renamed, deleted or "
                    "re-parameterized, and this audit row now vouches for nothing (this is "
                    "PDF-06 AC11's own rot: `def snapshot_tree` was renamed to `snapshot` and "
                    "its mechanization went on claiming a green)"
                )
    return problems


def check_an_unmeasured_ac_names_a_finding(spec_id: str, audit: Iterable[ACAudit]) -> list[str]:
    problems = []
    for row in audit:
        unmeasured = not row.covering or row.red_kind is RedKind.NOT_OBSERVED
        if unmeasured and not row.finding:
            problems.append(
                f"{spec_id} {row.ac}: covering={row.covering!r} red_kind={row.red_kind.value} "
                "but no `finding` -- an unmeasured acceptance criterion is a FINDING with a "
                "real ledger fingerprint or B-NNN, never a gap filled by a newly written "
                "passing assertion (0615feae63 is the precedent)"
            )
    return problems


def check_the_ac_roster_is_contiguous(
    spec_id: str, ac_count: int, audit: Sequence[ACAudit]
) -> list[str]:
    problems = []
    declared = [row.ac for row in audit]
    if len(declared) != len(set(declared)):
        duplicates = sorted({ac for ac in declared if declared.count(ac) > 1})
        problems.append(f"{spec_id}: duplicate audit rows for {duplicates}")
    expected = [f"AC{n}" for n in range(1, ac_count + 1)]
    missing = [ac for ac in expected if ac not in set(declared)]
    unexpected = [ac for ac in declared if ac not in set(expected)]
    if missing:
        problems.append(
            f"{spec_id}: AC_COUNT={ac_count} but these criteria have no audit row: {missing} -- "
            "every criterion of the audited spec gets a row, including the ones that pass "
            "trivially (Design §9.5 rule 3)"
        )
    if unexpected:
        problems.append(f"{spec_id}: audit rows outside AC1..AC{ac_count}: {unexpected}")
    return problems


def check_red_is_substantive(spec_id: str, audit: Iterable[ACAudit]) -> list[str]:
    problems = []
    for row in audit:
        stripped = row.red.strip()
        lowered = stripped.lower()
        if lowered in PLACEHOLDER_REDS:
            problems.append(f"{spec_id} {row.ac}: `red` is the placeholder {stripped!r}")
            continue
        phrase = next((p for p in PLACEHOLDER_RED_PHRASES if p in lowered), None)
        if phrase is not None:
            problems.append(
                f"{spec_id} {row.ac}: `red` says {phrase!r} -- PDF-17's brief rules this out "
                'in terms: "Would fail if broken" is not a red. Record the mutation you '
                "applied, the failure message you saw, and that you reverted it."
            )
    return problems


# --------------------------------------------------------------------------- #
# Live node-id collection. Scoped to the FILES the audit rows actually name, so
# the gate costs one short collection rather than a whole-suite one -- and it is
# a REAL `--collect-only` run, not an AST guess, because AC30 requires the ids
# to resolve live.
# --------------------------------------------------------------------------- #


def _files_named_by(modules: Iterable[ModuleType]) -> tuple[str, ...]:
    files = {
        node_id.split("::", 1)[0]
        for module in modules
        for row in audit_of(module)
        for node_id in row.covering
    }
    return tuple(sorted(files))


def collect_node_ids(targets: Sequence[str]) -> frozenset[str]:
    """Every node id pytest collects from *targets*, as a real collection."""
    if not targets:
        return frozenset()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            *targets,
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        pytest.fail(
            "pytest --collect-only failed over the files named by the audit rows "
            f"({list(targets)}): {result.stdout}{result.stderr}"
        )
    return frozenset(
        line.strip()
        for line in result.stdout.splitlines()
        if "::" in line and not line.startswith(" ")
    )


@pytest.fixture(scope="module")
def live_node_ids() -> frozenset[str]:
    return collect_node_ids(_files_named_by(discover_audit_modules()))


AUDIT_MODULES: Final[tuple[ModuleType, ...]] = discover_audit_modules()
_IDS: Final[list[str]] = [module.__name__.rsplit(".", 1)[-1] for module in AUDIT_MODULES]


# --------------------------------------------------------------------------- #
# The six controls, run against the REAL discovered audit modules
# --------------------------------------------------------------------------- #


def test_the_audit_roster_is_non_empty() -> None:
    problems = check_roster_is_non_empty(discover_audit_paths())
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("module", AUDIT_MODULES, ids=_IDS)
def test_module_name_matches_declared_spec_id(module: ModuleType) -> None:
    stem = module.__name__.rsplit(".", 1)[-1]
    problems = check_module_name_matches_spec_id(stem, module.SPEC_ID)
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("module", AUDIT_MODULES, ids=_IDS)
def test_every_covering_node_id_resolves(module: ModuleType, live_node_ids: frozenset[str]) -> None:
    problems = check_covering_node_ids_resolve(module.SPEC_ID, audit_of(module), live_node_ids)
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("module", AUDIT_MODULES, ids=_IDS)
def test_an_unmeasured_ac_names_a_finding(module: ModuleType) -> None:
    problems = check_an_unmeasured_ac_names_a_finding(module.SPEC_ID, audit_of(module))
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("module", AUDIT_MODULES, ids=_IDS)
def test_the_ac_roster_is_contiguous(module: ModuleType) -> None:
    problems = check_the_ac_roster_is_contiguous(module.SPEC_ID, module.AC_COUNT, audit_of(module))
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("module", AUDIT_MODULES, ids=_IDS)
def test_red_is_substantive(module: ModuleType) -> None:
    problems = check_red_is_substantive(module.SPEC_ID, audit_of(module))
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("module", AUDIT_MODULES, ids=_IDS)
def test_every_module_exposes_the_three_declared_names(module: ModuleType) -> None:
    """§9.3: exactly `SPEC_ID`, `AC_COUNT` and `AUDIT`. Without this, a module
    missing `AC_COUNT` would `AttributeError` at collection rather than failing
    with a message that tells its author what to add."""
    for name in ("SPEC_ID", "AC_COUNT", "AUDIT"):
        assert hasattr(module, name), (
            f"{module.__name__} does not expose {name!r} -- AUDIT-CONVENTION(PDF-17) §9.3 "
            "requires exactly SPEC_ID, AC_COUNT and AUDIT"
        )
    assert all(isinstance(row, ACAudit) for row in module.AUDIT), (
        f"{module.__name__}: every AUDIT entry must be an acceptance._model.ACAudit"
    )


# --------------------------------------------------------------------------- #
# Proof that the gate fires. Without these, the assertions above are a claim.
#
# Every proof drives a control against a SYNTHETIC in-memory tuple. No proof
# mutates a real audit module (AC26) -- a red proof that vandalises the very
# registry it is proving is the shared-anchor race wearing a lab coat.
# --------------------------------------------------------------------------- #


#: A substantive synthetic `red`, so the placeholder proofs below are the only
#: thing under test in each of them.
_SYNTHETIC_RED: Final[str] = (
    "deleted the INVOCATIONS row at tests/registry.py:900; saw "
    "`verb(s) ['x'] are discovered on the live CLI tree`; restored with git show HEAD:"
)


def _row(
    ac: str = "AC1",
    *,
    covering: tuple[str, ...] = ("tests/test_acceptance_audit.py::test_red_is_substantive",),
    red: str = _SYNTHETIC_RED,
    red_kind: RedKind = RedKind.DELETED_ROW,
    finding: str | None = None,
) -> ACAudit:
    return ACAudit(
        ac=ac, claim="synthetic", covering=covering, red=red, red_kind=red_kind, finding=finding
    )


def test_the_roster_pin_fires_on_an_empty_directory(tmp_path: Path) -> None:
    assert check_roster_is_non_empty(discover_audit_paths(tmp_path)) != []
    assert check_roster_is_non_empty([Path("audit_pdf_06.py")]) == []


def test_the_module_name_pin_fires_on_a_mismatched_spec_id() -> None:
    assert check_module_name_matches_spec_id("audit_pdf_06", "PDF-04") != []
    assert check_module_name_matches_spec_id("audit_pdf_06", "PDF-06") == []


def test_the_node_id_pin_fires_on_a_bogus_id() -> None:
    live = frozenset({"tests/test_x.py::test_real"})
    assert (
        check_covering_node_ids_resolve(
            "PDF-06", (_row(covering=("tests/test_x.py::test_gone",)),), live
        )
        != []
    )
    assert (
        check_covering_node_ids_resolve(
            "PDF-06", (_row(covering=("tests/test_x.py::test_real",)),), live
        )
        == []
    )


def test_the_unmeasured_pin_fires_on_a_row_with_neither() -> None:
    orphan = _row(covering=(), red_kind=RedKind.NOT_OBSERVED, finding=None)
    assert check_an_unmeasured_ac_names_a_finding("PDF-06", (orphan,)) != []
    filed = _row(covering=(), red_kind=RedKind.NOT_OBSERVED, finding="afe6137b")
    assert check_an_unmeasured_ac_names_a_finding("PDF-06", (filed,)) == []


def test_the_contiguity_pin_fires_on_a_deleted_middle_row() -> None:
    full = tuple(_row(f"AC{n}") for n in (1, 2, 3))
    assert check_the_ac_roster_is_contiguous("PDF-06", 3, full) == []
    gapped = tuple(_row(f"AC{n}") for n in (1, 3))
    assert check_the_ac_roster_is_contiguous("PDF-06", 3, gapped) != []
    duplicated = (_row("AC1"), _row("AC1"), _row("AC3"))
    assert check_the_ac_roster_is_contiguous("PDF-06", 3, duplicated) != []


def test_the_red_substance_pin_fires_on_a_placeholder() -> None:
    assert check_red_is_substantive("PDF-06", (_row(red="TODO"),)) != []
    assert check_red_is_substantive("PDF-06", (_row(red="n/a"),)) != []
    assert (
        check_red_is_substantive(
            "PDF-06", (_row(red="this would fail if broken, so it is covered"),)
        )
        != []
    )
    assert check_red_is_substantive("PDF-06", (_row(),)) == []


def test_the_live_collection_helper_actually_collects() -> None:
    """The non-vacuity proof for `collect_node_ids` itself.

    Without this, an empty `live_node_ids` would make
    `test_every_covering_node_id_resolves` fail LOUDLY (good) -- but a helper
    that silently returned every line of pytest's output would make it pass
    vacuously (bad). Both directions are pinned here: a real collection over
    THIS file returns this very test's own node id, and it does not return an
    id that does not exist.
    """
    collected = collect_node_ids(("tests/test_acceptance_audit.py",))
    mine = "tests/test_acceptance_audit.py::test_the_live_collection_helper_actually_collects"
    assert mine in collected, f"live collection did not find this test: {sorted(collected)[:5]}"
    assert "tests/test_acceptance_audit.py::test_definitely_not_a_test" not in collected
