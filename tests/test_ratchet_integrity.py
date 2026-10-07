"""PDF-119 -- the instruments that claim more than they can see, made honest.

Three instruments were one-sided or false:

* **The ratchets.** Every frozen ceiling was `<=`, and every ratification ledger
  checked record N-1 against record N only, so a landed record or a scalar ceiling
  could be raised IN PLACE with the suite green (`1a6408b873`, `B-398`).
* **The read-seam observer** credited every `read_source_bytes` read to the helper,
  never to its caller (`B-401`; the arms for that live in `tests/test_read_seams.py`).
* **The startup condition's rationale** claimed it detects a runner-image roll. It
  cannot (`a8172f6b8a`, `B-414`).

This module holds the immutability arms (D1), the census and register arms (D2),
the register verifier's self-tests (D2) and the rationale guard (D5). The exactness
arms (D3) live beside the counts they pin, in each census module.

Git is the oracle. The file under edit cannot be its own witness: a digest pinned
beside a record moves in the same diff as the record. A landed record is immutable;
the only green path upward is a NEW record, `direction="up"`, with a PM ruling.

RESIDUAL, named honestly: an editor who rewrites a landed record AND the git
history defeats any in-tree check. Force-push to `main` is forbidden by branch
protection, and that is the backstop. A ruled `up` record is green by design: the
ruling is the review.
"""

from __future__ import annotations

import ast
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

import ratchet
from ceiling_register import CEILING_LEDGER, _CeilingRatification

REPO_ROOT: Final = ratchet.REPO_ROOT

#: Mirrors `tests/test_changelog_history.py::MINIMUM_HISTORY_DEPTH` (`7afdb1a`'s
#: reachable-commit count). Below it the clone is shallow and the HISTORY arm SKIPS
#: with a reason naming the depth: *a control that cannot be run must be visible as
#: skipped, never silently absent* (X-153). Mirrored, not imported: one test module
#: does not import another (`B-308`).
MINIMUM_HISTORY_DEPTH: Final = 72


def _history_depth() -> int:
    result = ratchet.git(REPO_ROOT, "rev-list", "--count", "HEAD")
    return int(result.stdout.strip() or 0) if result.returncode == 0 else 0


def _require_full_history() -> None:
    depth = _history_depth()
    if depth < MINIMUM_HISTORY_DEPTH:
        pytest.skip(
            f"shallow clone: git rev-list --count HEAD is {depth}, below the frozen minimum "
            f"of {MINIMUM_HISTORY_DEPTH}. This arm reads old revisions of the governed "
            "ledgers and cannot run here; it is enforced locally and by the qa-sentinel. A "
            "shallow checkout never yields a pass."
        )


# --------------------------------------------------------------------------- #
# D1 -- landed records are immutable, and git is the oracle
# --------------------------------------------------------------------------- #


def test_no_landed_ratification_record_is_edited_in_the_working_tree() -> None:
    """AC1. Each governed ledger at HEAD is a PREFIX of the ledger in the working tree.

    RED (each driven separately, uncommitted): +1 on a key of the newest or the
    genesis read-seam record, the newest docs-residue / engine-gating / register
    record, or one word of a reason. Each names the ledger, the record index and
    the first differing key or field.
    """
    if ratchet.resolve_rev(REPO_ROOT, "HEAD") is None:
        pytest.skip("HEAD does not resolve: there is no landed revision to compare with")
    complaints = ratchet.working_tree_complaints(REPO_ROOT)
    assert complaints == [], "\n".join(complaints)


def test_every_first_parent_commit_only_appends_to_each_governed_ledger() -> None:
    """AC2. At each first-parent commit touching a governed ledger, the parent's
    records are a prefix of the commit's. Born green (zero in-place edits in history),
    and `HEAD` on a pull_request run is GitHub's merge commit, so the PR's own change
    is audited too. RED: commit an in-place edit; the failure names that commit.
    """
    _require_full_history()
    complaints = ratchet.history_complaints(REPO_ROOT)
    assert complaints == [], "\n".join(complaints)


def test_every_tuple_ledger_under_tests_is_governed() -> None:
    """AC3. Every module-level `*_LEDGER` tuple under `tests/` is in the governed set,
    so a fifth ledger cannot be born ungoverned. `_LEDGER_ENV`/`ENV_LEDGER` are not
    tuple displays and fall out by the rule, not by exemption."""
    found = set(ratchet.tuple_ledger_bindings())
    governed = {f"{path}::{name}" for path, name in ratchet.GOVERNED_LEDGERS}
    assert found == governed, (
        f"ledgers bound under tests/ but not governed: {sorted(found - governed)}; "
        f"governed but not found: {sorted(governed - found)}. Add the ledger to "
        f"tests/ratchet.py::GOVERNED_LEDGERS (the one place a ledger is named)."
    )


def test_the_governed_ledgers_are_all_readable_by_the_restricted_evaluator() -> None:
    """The evaluator refuses rather than guesses: every governed ledger reads, now."""
    for path, name in ratchet.GOVERNED_LEDGERS:
        records = ratchet.ledger_values(
            (REPO_ROOT / path).read_text(encoding="utf-8"), name, filename=path
        )
        assert records, f"{path}::{name} read as an empty ledger"
        assert [dict(r)["spec"] for r in records][0], f"{path}::{name}: record 0 has no spec"


# ----- the throwaway-repository self-test, both directions ------------------ #

_LEDGER_PATH: Final = "ledger.py"
_LEDGER_NAME: Final = "X_LEDGER"
_GOVERNED_SCRATCH: Final = ((_LEDGER_PATH, _LEDGER_NAME),)

_HEADER: Final = (
    "from types import MappingProxyType\n"
    "from typing import NamedTuple\n"
    "\n"
    "class Rec(NamedTuple):\n"
    "    date: str\n"
    "    spec: str\n"
    "    direction: str\n"
    "    ceilings: object\n"
    "    reason: str\n"
    "    ruling: str = ''\n"
    "\n"
)


def _record(spec: str, value: int, reason: str = "r") -> str:
    return (
        f"    Rec(date='2026-10-07', spec='{spec}', direction='genesis', "
        f"ceilings=MappingProxyType({{'k': {value}}}), reason='{reason}'),\n"
    )


def _ledger_source(*records: str) -> str:
    return _HEADER + f"{_LEDGER_NAME} = (\n" + "".join(records) + ")\n"


def _commit(repo: Path, message: str) -> None:
    ratchet.git(repo, "add", "-A")
    done = ratchet.git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        message,
    )
    assert done.returncode == 0, done.stderr


@pytest.fixture
def scratch_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert not repo.resolve().is_relative_to(REPO_ROOT.resolve()), (
        "the scratch repository must never live under the shared tree"
    )
    assert ratchet.git(repo, "init", "-q").returncode == 0
    (repo / _LEDGER_PATH).write_text(_ledger_source(_record("A", 1), _record("B", 2)))
    _commit(repo, "two-record ledger")
    return repo


def _audit(repo: Path) -> list[str]:
    return ratchet.history_complaints(repo, _GOVERNED_SCRATCH)


def test_the_history_audit_is_self_tested_in_both_directions(scratch_repo: Path) -> None:
    """AC2. The four D1 cases, run through the SAME functions the live arms call."""
    ledger = scratch_repo / _LEDGER_PATH
    base = ledger.read_text()

    # Appending a record: zero complaints.
    ledger.write_text(base.replace("\n)\n", "\n" + _record("C", 3) + ")\n", 1))
    _commit(scratch_repo, "append")
    assert _audit(scratch_repo) == []
    assert ratchet.working_tree_complaints(scratch_repo, _GOVERNED_SCRATCH) == []

    # Raising a key inside record 1 in place: exactly one complaint, naming it.
    ledger.write_text(ledger.read_text().replace("'k': 2", "'k': 3", 1))
    assert len(ratchet.working_tree_complaints(scratch_repo, _GOVERNED_SCRATCH)) == 1
    _commit(scratch_repo, "in-place raise")
    complaints = _audit(scratch_repo)
    assert len(complaints) == 1, complaints
    assert "[1] B" in complaints[0] and "'k': 2 -> 3" in complaints[0], complaints


def test_an_edited_reason_alone_is_an_edited_record(scratch_repo: Path) -> None:
    ledger = scratch_repo / _LEDGER_PATH
    ledger.write_text(ledger.read_text().replace("reason='r'", "reason='r2'", 1))
    working = ratchet.working_tree_complaints(scratch_repo, _GOVERNED_SCRATCH)
    assert len(working) == 1 and "reason" in working[0], working
    _commit(scratch_repo, "reason edit")
    committed = _audit(scratch_repo)
    assert len(committed) == 1 and "reason" in committed[0], committed


def test_reformatting_a_record_into_named_constants_with_equal_values_is_no_change(
    scratch_repo: Path,
) -> None:
    """The engine-gating refactor shape: source text moves, evaluated values do not."""
    refactored = (
        _HEADER + "_A = Rec(date='2026-10-07', spec='A', direction='genesis', "
        "ceilings=MappingProxyType({'k': 1}), reason='r')\n"
        + f"{_LEDGER_NAME} = (\n    _A,\n"
        + _record("B", 2)
        + ")\n"
    )
    (scratch_repo / _LEDGER_PATH).write_text(refactored)
    assert ratchet.working_tree_complaints(scratch_repo, _GOVERNED_SCRATCH) == []
    _commit(scratch_repo, "named constant")
    assert _audit(scratch_repo) == []


def test_a_removed_landed_record_is_refused(scratch_repo: Path) -> None:
    (scratch_repo / _LEDGER_PATH).write_text(_ledger_source(_record("A", 1)))
    complaints = ratchet.working_tree_complaints(scratch_repo, _GOVERNED_SCRATCH)
    assert len(complaints) == 1 and "[1] B" in complaints[0] and "REMOVED" in complaints[0]


def test_a_ledger_absent_at_head_counts_as_an_empty_prefix(scratch_repo: Path) -> None:
    (scratch_repo / "later.py").write_text(_ledger_source(_record("Z", 9)))
    assert ratchet.working_tree_complaints(scratch_repo, (("later.py", _LEDGER_NAME),)) == []


@pytest.mark.parametrize(
    "shape",
    [
        "X_LEDGER = tuple(sorted(_live()))\n",
        "X_LEDGER = (Rec(date='d', spec='s', direction='up', ceilings=_load(), reason='r'),)\n",
        "X_LEDGER = (Rec(*args),)\n",
    ],
)
def test_the_evaluator_refuses_a_shape_it_cannot_read_rather_than_guessing(shape: str) -> None:
    with pytest.raises(ratchet.UnreadableLedger):
        ratchet.ledger_values(_HEADER + shape, "X_LEDGER")


# --------------------------------------------------------------------------- #
# D2 -- the census is the register, and a literal is a red
# --------------------------------------------------------------------------- #


def test_the_ceiling_census_equals_the_register_keys() -> None:
    """AC4. The derived census (names ending `_CEILING`/`_CEILING_PER_MILLE` bound to a
    scalar, excluding `<LEDGER>[-1].ceilings` aliases) equals the newest record's keys:
    an orphan key, or a census name with no key, reds."""
    census_keys = {row.key for row in ratchet.census()}
    register_keys = set(CEILING_LEDGER[-1].ceilings)
    assert census_keys == register_keys, (
        f"census names with no register key: {sorted(census_keys - register_keys)}; "
        f"register keys with no census binding: {sorted(register_keys - census_keys)}"
    )


def binding_complaints(tests_dir: Path) -> list[str]:
    """Every census binding under *tests_dir* that is not exactly one `ceiling("<own key>")`."""
    complaints: list[str] = []
    seen: dict[str, int] = {}
    for row in ratchet.census(tests_dir):
        seen[row.key] = seen.get(row.key, 0) + 1
        if not row.is_register_lookup:
            shown = "nothing" if row.value is None else ast.unparse(row.value)
            complaints.append(
                f"{row.path}:{row.line} {row.name} is bound to `{shown}`, not to "
                f'`ceiling("{row.key}")`: a ceiling literal is raised by editing it'
            )
        elif row.lookup_argument != row.key:
            complaints.append(
                f"{row.path}:{row.line} {row.name} looks up {row.lookup_argument!r}, "
                f"not its own key {row.key!r}"
            )
    complaints += [f"{key} is bound {count} times" for key, count in seen.items() if count > 1]
    return complaints


def test_every_census_ceiling_is_bound_to_the_register_not_a_literal() -> None:
    """AC4 (PDF-70 AC3's precedent, generalised): each census name is bound exactly
    once, to a register lookup of its own key. RED: re-bind a literal, add a new
    `*_CEILING = 3`."""
    complaints = binding_complaints(ratchet.TESTS_DIR)
    assert complaints == [], "\n".join(complaints)


def _scratch_tests(tmp_path: Path, **modules: str) -> Path:
    root = tmp_path / "tests"
    root.mkdir(parents=True)
    for name, text in modules.items():
        (root / f"{name}.py").write_text(text)
    return root


def test_the_binding_arm_refuses_a_literal_and_a_new_ceiling_and_accepts_a_lookup(
    tmp_path: Path,
) -> None:
    good = _scratch_tests(
        tmp_path / "good", test_a='PRAGMA_CEILING: Final = ceiling("test_a.py::PRAGMA_CEILING")\n'
    )
    assert binding_complaints(good) == []

    literal = _scratch_tests(tmp_path / "lit", test_a="PRAGMA_CEILING: Final[int] = 47\n")
    joined = " ".join(binding_complaints(literal))
    assert "PRAGMA_CEILING" in joined and "47" in joined

    new = _scratch_tests(tmp_path / "new", test_a="NEW_CEILING: Final = 3\n")
    assert "NEW_CEILING" in " ".join(binding_complaints(new))

    wrong_key = _scratch_tests(
        tmp_path / "wrong", test_a='X_CEILING: Final = ceiling("test_b.py::X_CEILING")\n'
    )
    assert "not its own key" in " ".join(binding_complaints(wrong_key))

    computed = _scratch_tests(tmp_path / "computed", test_a="X_CEILING = len(_live())\n")
    assert "X_CEILING" in " ".join(binding_complaints(computed))


def test_the_census_excludes_ledger_aliases_and_string_names(tmp_path: Path) -> None:
    root = _scratch_tests(
        tmp_path,
        test_a=(
            "RESIDUE_CEILING = SOME_LEDGER[-1].ceilings\n"
            'PDF68_CEILING = "STARTUP_COST_RATIO_CEILING_PER_MILLE"\n'
            "TIMEOUT_CEILING = 30\n"
        ),
    )
    assert [row.name for row in ratchet.census(root)] == ["TIMEOUT_CEILING"]


def test_the_register_verifier_accepts_the_landed_register() -> None:
    assert ratchet.ratification_complaints(CEILING_LEDGER) == []


# ----- the register verifier, synthetic, both directions -------------------- #


def _rec(
    direction: str,
    ceilings: dict[str, int | tuple[str, ...]],
    *,
    ruling: str = "",
    reason: str = "synthetic",
    date: str = "2026-10-07",
) -> _CeilingRatification:
    return _CeilingRatification(
        date=date,
        spec="PDF-X",
        direction=direction,
        ceilings=MappingProxyType(dict(ceilings)),
        reason=reason,
        ruling=ruling,
    )


def _genesis(ceilings: dict[str, int | tuple[str, ...]]) -> _CeilingRatification:
    return _rec("genesis", ceilings, reason="synthetic genesis")


def test_an_unruled_raise_is_refused_naming_the_key_and_both_values() -> None:
    complaints = ratchet.ratification_complaints(
        [_genesis({"k": 1}), _rec("up", {"k": 2}, reason="k goes up")]
    )
    assert any("k RAISED 1 -> 2" in c and "NO ruling" in c for c in complaints), complaints


def test_a_ruled_raise_naming_the_key_is_accepted() -> None:
    assert (
        ratchet.ratification_complaints(
            [_genesis({"k": 1}), _rec("up", {"k": 2}, ruling="X-1", reason="k goes up")]
        )
        == []
    )


def test_a_raise_whose_reason_does_not_name_the_key_is_refused() -> None:
    complaints = ratchet.ratification_complaints(
        [_genesis({"k": 1}), _rec("up", {"k": 2}, ruling="X-1", reason="because")]
    )
    assert any("does not name the key" in c for c in complaints), complaints


def test_a_down_record_needs_no_ruling() -> None:
    assert ratchet.ratification_complaints([_genesis({"k": 3}), _rec("down", {"k": 2})]) == []


def test_a_decrease_declared_up_is_refused() -> None:
    complaints = ratchet.ratification_complaints(
        [_genesis({"k": 3}), _rec("up", {"k": 2}, ruling="X-1")]
    )
    assert any("LOWERED 3 -> 2" in c and "direction='down'" in c for c in complaints), complaints


def test_a_name_added_to_a_set_ceiling_without_a_ruling_is_refused() -> None:
    complaints = ratchet.ratification_complaints(
        [_genesis({"s": ("a",)}), _rec("up", {"s": ("a", "b")}, reason="s grows")]
    )
    assert any("s RAISED" in c and "NO ruling" in c for c in complaints), complaints
    assert (
        ratchet.ratification_complaints([_genesis({"s": ("a", "b")}), _rec("down", {"s": ("a",)})])
        == []
    )


def test_a_new_key_is_a_raise_and_a_removed_key_is_a_fall() -> None:
    added = ratchet.ratification_complaints([_genesis({"a": 1}), _rec("up", {"a": 1, "b": 1})])
    assert any("b RAISED absent -> 1" in c for c in added), added
    assert (
        ratchet.ratification_complaints([_genesis({"a": 1, "b": 1}), _rec("down", {"a": 1})]) == []
    )


@pytest.mark.parametrize(
    ("ledger", "expected"),
    [
        ([], "EMPTY"),
        ([_rec("down", {"k": 1})], "genesis' belongs to record 0"),
        (
            [_genesis({"k": 1}), _rec("genesis", {"k": 1})],
            "genesis' belongs to record 0",
        ),
        ([_rec("genesis", {"k": 1}, date="07/10/2026")], "date is not YYYY-MM-DD"),
        (
            [_genesis({"k": 1}), _rec("down", {"k": 1}, date="2026-10-06")],
            "dated before its predecessor",
        ),
    ],
)
def test_a_malformed_register_draws_a_complaint(
    ledger: Sequence[_CeilingRatification], expected: str
) -> None:
    complaints = ratchet.ratification_complaints(ledger)
    assert any(expected in c for c in complaints), complaints


# --------------------------------------------------------------------------- #
# D5 -- the runner-image rationale is true, and a guard keeps it true
# --------------------------------------------------------------------------- #

#: The claim, as a pattern over comment/docstring text with the markers stripped and
#: line breaks folded: a rationale that credits the instrument with detecting an image roll.
_IMAGE_CLAIM: Final = re.compile(r"runner[- ]image\b[^.]{0,120}\barrives as a red", re.IGNORECASE)
_COMMENT_MARKER: Final = re.compile(r"^\s*#:?")


def claim_lines(text: str) -> list[int]:
    """1-based line numbers where the claim BEGINS (the `runner image` words)."""
    cleaned: list[str] = []
    starts: list[int] = []
    offset = 0
    for line in text.splitlines():
        piece = _COMMENT_MARKER.sub("", line).strip()
        starts.append(offset)
        cleaned.append(piece)
        offset += len(piece) + 1
    folded = " ".join(cleaned)
    found: list[int] = []
    for match in _IMAGE_CLAIM.finditer(folded):
        line = max(i for i, start in enumerate(starts) if start <= match.start())
        found.append(line + 1)
    return found


def rationale_claims(repo_root: Path) -> list[str]:
    paths = [*sorted((repo_root / "tests").rglob("*.py")), repo_root / "README.md"]
    out: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        out += [
            f"{path.relative_to(repo_root).as_posix()}:{line}"
            for line in claim_lines(path.read_text(encoding="utf-8"))
        ]
    return out


def _startup_condition_fields() -> tuple[str, ...]:
    """`StartupCondition._fields`, read from the SOURCE by AST (importing the
    section's test module would be cross-test-module coupling)."""
    tree = ast.parse((REPO_ROOT / "tests" / "test_import_boundaries.py").read_text("utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "StartupCondition":
            return tuple(
                item.target.id
                for item in node.body
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            )
    raise AssertionError("StartupCondition is not defined in tests/test_import_boundaries.py")


def test_no_rationale_claims_a_coordinate_the_startup_condition_lacks() -> None:
    """AC11. Reds if any comment, docstring or README sentence claims the instrument
    detects a runner-image roll WHILE no field of `StartupCondition` is an image/runner coordinate.
    Adding such a coordinate later retires the guard with no edit. `changelog.md` is
    excluded: landed entries are immutable. RED: restore the pre-fix sentence; the
    failure names the file and line.
    """
    fields = _startup_condition_fields()
    if any(re.search(r"image|runner", field) for field in fields):
        pytest.skip(f"StartupCondition now carries an image coordinate {fields}: guard retired")
    claims = rationale_claims(REPO_ROOT)
    assert claims == [], (
        f"{claims}: a rationale claims a runner-image roll is detected, but "
        "StartupCondition has only "
        f"{fields}: an image roll that keeps (sys.platform, major.minor) INHERITS the key's "
        "verdict (PDF-109's macos-15 legs passed under `darwin`, a8172f6b8a). Reword it, or "
        "add an image coordinate."
    )


def test_startup_condition_fields_are_unchanged() -> None:
    """AC11: the coordinates did not move (`X-1006`: no runner coordinate this cycle)."""
    assert _startup_condition_fields() == ("platform", "interpreter")


#: The pre-fix sentence, assembled from fragments so THIS file does not itself match
#: the pattern the guard scans for.
_PRE_FIX: Final = (
    "#   UNDECLARED  neither -> RED, naming the condition and both halves. This is\n"
    "#               what closes the CLASS instead of patching one platform: a new\n"
    "#               platform, a new interpreter minor or a new runner "
    "image arrives\n"
    "#               as a red naming its own condition, never as an inherited\n"
    "#               assertion and never as a quiet pass.\n"
)
_REWORDED: Final = (
    "#   UNDECLARED  neither -> RED. A new platform or a new interpreter minor arrives\n"
    "#               as a red naming its own condition. A runner-"
    "image roll that keeps the\n"
    "#               same (platform, major.minor) INHERITS that key's verdict.\n"
)


def test_the_rationale_scanner_reds_on_the_pre_fix_text_and_not_on_the_rewording(
    tmp_path: Path,
) -> None:
    (tmp_path / "tests").mkdir()
    planted = tmp_path / "tests" / "test_planted.py"
    planted.write_text("x = 1\n" + _PRE_FIX)
    assert rationale_claims(tmp_path) == ["tests/test_planted.py:4"]

    planted.write_text("x = 1\n" + _REWORDED)
    assert rationale_claims(tmp_path) == []

    (tmp_path / "README.md").write_text("A new runner-" + "image arrives as a red.\n")
    assert rationale_claims(tmp_path) == ["README.md:1"]


def test_the_git_grep_form_of_the_claim_finds_nothing() -> None:
    """AC11's `git grep -niE "runner[- ]image[^.]*arrives as a red" -- tests README.md`."""
    result = subprocess.run(
        [
            "git",
            "grep",
            "-niE",
            r"runner[- ]image[^.]*arrives as a red",
            "--",
            "tests",
            "README.md",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=ratchet.isolated_git_env(),
    )
    if result.returncode == 128:
        pytest.skip("not a git work tree")
    assert result.returncode == 1, result.stdout
