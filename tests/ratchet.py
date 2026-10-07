"""PDF-119 -- the ratchet instrument: landed ratification records are immutable.

A HELPER, not a test module (the `tests/seams.py` pattern). It is imported by
`tests/test_ratchet_integrity.py`; it is framework-free and has one CLI,
`remeasure` (see :func:`main`), which is the ONE command that re-derives every
measured figure this spec's records carry.

WHY THIS MODULE EXISTS
----------------------
Every frozen ceiling in this suite was one-sided, and every ratification ledger
verified record N-1 against record N only. So a landed record, or a scalar
ceiling, could be raised **in place** with the suite green (`1a6408b873`,
`B-398`). The file under edit cannot be its own witness: a digest pinned beside a
record moves in the same diff as the record. The one anchor an in-place edit
cannot also rewrite is the LANDED REVISION, so git is the oracle.

What lives here:

* a restricted AST evaluator (:func:`ledger_values`) that reads a ledger constant
  out of a source text at any revision. It is NOT ``exec``/``eval``, and it
  REFUSES (:class:`UnreadableLedger`) rather than guesses;
* the git accessors and the two immutability checks (working tree against
  ``HEAD``; every first-parent commit against its parent);
* the census of scalar ceilings and the generic register verifier
  (:func:`ratification_complaints`);
* the ``remeasure`` report sink (:func:`report`) the exact arms write to.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
TESTS_DIR: Final = REPO_ROOT / "tests"

#: THE ONLY PLACE A GOVERNED LEDGER IS NAMED (PDF-119 D1). A completeness arm
#: derives every ``*_LEDGER`` tuple binding under ``tests/`` and asserts it equals
#: this set, so a fifth ledger cannot be born ungoverned.
GOVERNED_LEDGERS: Final[tuple[tuple[str, str], ...]] = (
    ("tests/test_read_seams.py", "READ_SEAM_RESIDUE_LEDGER"),
    ("tests/test_docs_antirot.py", "DOCS_RESIDUE_LEDGER"),
    ("tests/test_engine_gating_census.py", "ENGINE_GATING_LEDGER"),
    ("tests/ceiling_register.py", "CEILING_LEDGER"),
)

#: The record shape's fields, in the one order records are compared in. A record
#: constructed without `ruling` carries the class default, ``""``.
RECORD_FIELDS: Final = ("date", "spec", "direction", "ceilings", "reason", "ruling")
_RECORD_DEFAULTS: Final[Mapping[str, object]] = {"ruling": ""}

RecordValue = tuple[tuple[str, object], ...]

#: Every ledger/register ceiling is one of these.
CeilingValue = int | tuple[str, ...]


class UnreadableLedger(ValueError):
    """The restricted evaluator met a node it will not evaluate.

    Raised, never swallowed: a revision the evaluator cannot read is a walk-past
    in an immutability audit, and a skipped commit is the defect.
    """


# --------------------------------------------------------------------------- #
# The restricted evaluator
# --------------------------------------------------------------------------- #


class _Record(dict[str, object]):
    """A record-class call's keyword arguments, by field."""


class _Evaluator:
    """Evaluates the node shapes a ratification ledger is written in, and no other."""

    def __init__(self, source: str, *, filename: str) -> None:
        self._filename = filename
        self._tree = ast.parse(source, filename=filename)
        self._bindings: dict[str, ast.expr] = {}
        self._classes: set[str] = set()
        for node in self._tree.body:
            if isinstance(node, ast.ClassDef):
                self._classes.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self._bindings[target.id] = node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                if isinstance(node.target, ast.Name):
                    self._bindings[node.target.id] = node.value
        self._active: list[str] = []

    def has(self, name: str) -> bool:
        return name in self._bindings

    def binding(self, name: str) -> object:
        if name not in self._bindings:
            raise UnreadableLedger(f"{self._filename}: no module-level binding named {name}")
        return self._eval(self._bindings[name])

    def _fail(self, node: ast.AST, why: str) -> UnreadableLedger:
        shown = ast.unparse(node)
        if len(shown) > 80:
            shown = shown[:77] + "..."
        return UnreadableLedger(
            f"{self._filename}:{getattr(node, 'lineno', '?')}: cannot evaluate "
            f"`ast.{type(node).__name__}` ({why}): {shown}"
        )

    def _eval(self, node: ast.expr) -> object:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Tuple):
            return tuple(self._eval(element) for element in node.elts)
        if isinstance(node, ast.Dict):
            out: dict[object, object] = {}
            for key, value in zip(node.keys, node.values, strict=True):
                if key is None:  # `**other`
                    spread = self._eval(value)
                    if not isinstance(spread, Mapping):
                        raise self._fail(value, "`**` operand is not a mapping")
                    out.update(spread)
                else:
                    out[self._eval(key)] = self._eval(value)
            return out
        if isinstance(node, ast.Name):
            if node.id not in self._bindings:
                raise self._fail(node, "name is not a module-level binding in this source")
            if node.id in self._active:
                raise self._fail(node, "circular module-level reference")
            self._active.append(node.id)
            try:
                return self._eval(self._bindings[node.id])
            finally:
                self._active.pop()
        if isinstance(node, ast.Attribute):
            owner = self._eval(node.value)
            if isinstance(owner, Mapping) and node.attr in owner:
                return owner[node.attr]
            raise self._fail(node, f"attribute {node.attr!r} of a non-record")
        if isinstance(node, ast.Subscript):
            owner = self._eval(node.value)
            index = self._eval(node.slice)
            if isinstance(owner, tuple) and isinstance(index, int):
                return owner[index]
            raise self._fail(node, "subscript is not a tuple index")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = self._eval(node.left), self._eval(node.right)
            if isinstance(left, str) and isinstance(right, str):
                return left + right
            if isinstance(left, int) and isinstance(right, int):
                return left + right
            raise self._fail(node, "`+` over operands that are not both str or both int")
        if isinstance(node, ast.Call):
            return self._call(node)
        raise self._fail(node, "node shape is outside the evaluator's grammar")

    def _call(self, node: ast.Call) -> object:
        if not isinstance(node.func, ast.Name):
            raise self._fail(node, "call target is not a plain name")
        name = node.func.id
        if name == "MappingProxyType":
            if len(node.args) != 1 or node.keywords:
                raise self._fail(node, "MappingProxyType takes exactly one positional argument")
            return self._eval(node.args[0])
        if name in self._classes:
            if node.args:
                raise self._fail(node, "record classes are called with keyword arguments only")
            record = _Record()
            for keyword in node.keywords:
                if keyword.arg is None:
                    raise self._fail(node, "`**` in a record call")
                record[keyword.arg] = self._eval(keyword.value)
            return record
        raise self._fail(node, f"call to `{name}` is not evaluable")


def _normalize_ceilings(value: object, *, where: str) -> tuple[tuple[str, object], ...]:
    if not isinstance(value, Mapping):
        raise UnreadableLedger(f"{where}: `ceilings` is not a mapping")
    return tuple(sorted(value.items(), key=lambda item: str(item[0])))


def _normalize_record(value: object, *, where: str) -> RecordValue:
    if not isinstance(value, _Record):
        raise UnreadableLedger(f"{where}: a ledger element is not a record-class call")
    merged = {**_RECORD_DEFAULTS, **value}
    unknown = sorted(set(merged) - set(RECORD_FIELDS))
    if unknown:
        raise UnreadableLedger(f"{where}: unknown record field(s) {unknown}")
    pairs: list[tuple[str, object]] = []
    for field in RECORD_FIELDS:
        if field not in merged:
            raise UnreadableLedger(f"{where}: record has no `{field}`")
        item = merged[field]
        if field == "ceilings":
            item = _normalize_ceilings(item, where=where)
        pairs.append((field, item))
    return tuple(pairs)


def ledger_values(
    source_text: str, name: str, *, filename: str = "<source>"
) -> tuple[RecordValue, ...]:
    """The records of the module-level ledger *name* in *source_text*, as VALUES.

    Compared on evaluated values, never on text: the engine-gating ledger was
    refactored into named constants at byte-identical values, and that refactor
    must read as no change at all. A binding that is absent reads as ``()`` (a
    ledger that does not exist yet is an empty prefix). Every field is part of
    the value -- `reason` and `ruling` included: an edited reason is an edited
    record.
    """
    evaluator = _Evaluator(source_text, filename=filename)
    if not evaluator.has(name):
        return ()
    ledger = evaluator.binding(name)
    if not isinstance(ledger, tuple):
        raise UnreadableLedger(f"{filename}: {name} does not evaluate to a tuple of records")
    return tuple(
        _normalize_record(record, where=f"{filename}:{name}[{index}]")
        for index, record in enumerate(ledger)
    )


# --------------------------------------------------------------------------- #
# Git accessors
# --------------------------------------------------------------------------- #


def isolated_git_env() -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"}
    }
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=isolated_git_env(),
    )


_SHOW_CACHE: dict[tuple[str, str, str], str | None] = {}
_VALUES_CACHE: dict[tuple[str, str, str, str], tuple[RecordValue, ...]] = {}


def resolve_rev(repo: Path, rev: str) -> str | None:
    result = git(repo, "rev-parse", "--verify", "-q", f"{rev}^{{commit}}")
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def file_at(repo: Path, sha: str, path: str) -> str | None:
    """*path* exactly as it stood at the commit *sha*, or None if absent there.

    Cached per ``(repo, sha, path)`` -- a sha names immutable content.
    """
    key = (str(repo), sha, path)
    if key not in _SHOW_CACHE:
        result = git(repo, "show", f"{sha}:{path}")
        _SHOW_CACHE[key] = result.stdout if result.returncode == 0 else None
    return _SHOW_CACHE[key]


def ledger_at(repo: Path, sha: str, path: str, name: str) -> tuple[RecordValue, ...]:
    key = (str(repo), sha, path, name)
    if key not in _VALUES_CACHE:
        text = file_at(repo, sha, path)
        _VALUES_CACHE[key] = (
            () if text is None else ledger_values(text, name, filename=f"{path}@{sha[:10]}")
        )
    return _VALUES_CACHE[key]


# --------------------------------------------------------------------------- #
# Immutability: a prefix check, by value
# --------------------------------------------------------------------------- #

IMMUTABLE_HINT: Final = (
    "a landed record is immutable; append a new record "
    "(direction `up` + ruling, or `down`) instead."
)


def _first_difference(old: RecordValue, new: RecordValue) -> str:
    for (field, before), (_, after) in zip(old, new, strict=True):
        if before == after:
            continue
        if field == "ceilings":
            before_map, after_map = dict(before), dict(after)  # type: ignore[call-overload]
            for key in sorted(set(before_map) | set(after_map), key=str):
                if before_map.get(key) != after_map.get(key):
                    return (
                        f"key {key!r}: {before_map.get(key, 'absent')!r} -> "
                        f"{after_map.get(key, 'absent')!r}"
                    )
        return f"field {field!r}: {before!r} -> {after!r}"
    return "no differing field"


def prefix_complaints(
    label: str,
    old: Sequence[RecordValue],
    new: Sequence[RecordValue],
    *,
    context: str,
) -> list[str]:
    """Complaints unless *old* is a PREFIX of *new*. Empty means append-only."""
    complaints: list[str] = []
    for index, record in enumerate(old):
        spec = dict(record)["spec"]
        if index >= len(new):
            complaints.append(
                f"{label} [{index}] {spec}: the record was REMOVED ({context}). {IMMUTABLE_HINT}"
            )
        elif new[index] != record:
            complaints.append(
                f"{label} [{index}] {spec}: the landed record was EDITED ({context}), "
                f"{_first_difference(record, new[index])}. {IMMUTABLE_HINT}"
            )
    return complaints


def working_tree_complaints(
    repo: Path, governed: Sequence[tuple[str, str]] = GOVERNED_LEDGERS
) -> list[str]:
    """Arm A -- each governed ledger at ``HEAD`` must be a prefix of the working tree.

    A ledger absent at ``HEAD`` counts as an empty prefix (a register that has not
    been committed yet).
    """
    head = resolve_rev(repo, "HEAD")
    if head is None:
        raise RuntimeError("HEAD does not resolve; there is no landed revision to compare with")
    complaints: list[str] = []
    for path, name in governed:
        target = repo / path
        current = (
            ledger_values(target.read_text(encoding="utf-8"), name, filename=path)
            if target.is_file()
            else ()
        )
        complaints += prefix_complaints(
            f"{path}::{name}",
            ledger_at(repo, head, path, name),
            current,
            context=f"working tree against HEAD {head[:10]}",
        )
    return complaints


def first_parent_commits(repo: Path, path: str) -> tuple[str, ...]:
    result = git(repo, "rev-list", "--first-parent", "HEAD", "--", path)
    return tuple(result.stdout.split()) if result.returncode == 0 else ()


def history_complaints(
    repo: Path, governed: Sequence[tuple[str, str]] = GOVERNED_LEDGERS
) -> list[str]:
    """Arm B -- at every first-parent commit touching a ledger, the parent's records
    must be a prefix of the commit's. Root commits have no parent and are skipped.
    """
    complaints: list[str] = []
    for path, name in governed:
        for commit in first_parent_commits(repo, path):
            parent = resolve_rev(repo, f"{commit}^1")
            if parent is None:
                continue
            complaints += prefix_complaints(
                f"{path}::{name}",
                ledger_at(repo, parent, path, name),
                ledger_at(repo, commit, path, name),
                context=f"commit {commit[:10]} against its first parent {parent[:10]}",
            )
    return complaints


# --------------------------------------------------------------------------- #
# The census of scalar ceilings
# --------------------------------------------------------------------------- #

_CEILING_NAME: Final = re.compile(r"[A-Z][A-Z0-9_]*_CEILING(_PER_MILLE)?")


def _target_names(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def _is_ledger_derived(value: ast.expr | None) -> bool:
    """``<...LEDGER>[-1].ceilings`` -- governed by D1 directly, not a scalar."""
    return (
        isinstance(value, ast.Attribute)
        and value.attr == "ceilings"
        and isinstance(value.value, ast.Subscript)
        and isinstance(value.value.value, ast.Name)
        and value.value.value.id.endswith("LEDGER")
    )


def _is_register_lookup(value: ast.expr | None) -> bool:
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "ceiling"
        and len(value.args) == 1
        and not value.keywords
        and isinstance(value.args[0], ast.Constant)
        and isinstance(value.args[0].value, str)
    )


def _is_scalar_ceiling_value(value: ast.expr | None) -> bool:
    """An int literal, a tuple display of str literals, or a register lookup.

    A `_CEILING`-named binding whose value is a plain string (``PDF68_CEILING``
    NAMES a constant, it is not one) is not a ceiling and is outside the census.
    """
    if value is None:
        return False
    if _is_register_lookup(value):
        return True
    if isinstance(value, ast.Constant):
        return isinstance(value.value, int) and not isinstance(value.value, bool)
    if isinstance(value, ast.Tuple):
        return all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in value.elts)
    return False


@dataclass(frozen=True)
class CensusBinding:
    path: str  # tests-relative, posix
    name: str
    line: int
    value: ast.expr | None

    @property
    def key(self) -> str:
        return f"{self.path}::{self.name}"

    @property
    def is_register_lookup(self) -> bool:
        return _is_register_lookup(self.value)

    @property
    def lookup_argument(self) -> str | None:
        if self.value is not None and _is_register_lookup(self.value):
            call = self.value
            assert isinstance(call, ast.Call) and isinstance(call.args[0], ast.Constant)
            return str(call.args[0].value)
        return None


def census(tests_dir: Path = TESTS_DIR) -> tuple[CensusBinding, ...]:
    """Every module-level scalar-ceiling binding under *tests_dir*, DERIVED.

    The rule, stated and never hand-picked: a module-level binding whose name
    ends in ``_CEILING`` or ``_CEILING_PER_MILLE``, whose value is an int literal,
    a tuple display of str literals, or a register lookup, excluding the
    ``<LEDGER>[-1].ceilings`` aliases (governed directly by D1).
    """
    rows: list[CensusBinding] = []
    for path in sorted(tests_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(tests_dir).as_posix()
        for node in tree.body:
            for name in _target_names(node):
                if not _CEILING_NAME.fullmatch(name):
                    continue
                value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
                if _is_ledger_derived(value):
                    continue
                # A name-matching binding with a non-scalar value is still a
                # census row (so a computed ceiling is a RED, not an escape);
                # only a plain string constant is exempt, being a name, not a bound.
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    continue
                rows.append(CensusBinding(relative, name, node.lineno, value))
    return tuple(rows)


def tuple_ledger_bindings(tests_dir: Path = TESTS_DIR) -> tuple[str, ...]:
    """Every module-level ``*_LEDGER`` binding to a tuple display, as ``path::NAME``
    with a repo-relative path -- the completeness rule's population."""
    found: list[str] = []
    for path in sorted(tests_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            if not isinstance(value, ast.Tuple):
                continue
            for name in _target_names(node):
                if name.endswith("_LEDGER"):
                    found.append(f"{path.relative_to(tests_dir.parent).as_posix()}::{name}")
    return tuple(found)


# --------------------------------------------------------------------------- #
# The generic per-key register verifier
# --------------------------------------------------------------------------- #

_DATE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DIRECTIONS: Final = ("genesis", "down", "up")


def _as_set(value: object) -> frozenset[str] | None:
    return frozenset(value) if isinstance(value, tuple) else None


def ratification_complaints(ledger: Sequence[Any]) -> list[str]:
    """Every rule violation in a scalar-ceiling register *ledger*, per key.

    PURE OVER ITS PARAMETER (PDF-70 D4): synthetic ledgers drive it in-process and
    the real one is never mutated to prove a point. It RETURNS complaints rather
    than raising. Rules, per key (the read-seam verifier's):

    * an int increase, a new key, or a name ADDED to a set needs ``direction="up"``,
      a non-empty ``ruling`` and the key named in ``reason``;
    * a decrease or a removal needs ``direction="down"``;
    * ``genesis`` belongs to record 0 only; dates are well-formed and non-decreasing.

    Deliberately NOT shared with the three older verifiers (`B-308`'s decision).
    """
    if not ledger:
        return ["the ceiling register is EMPTY: no ceiling has a record behind it"]
    complaints: list[str] = []
    for index, record in enumerate(ledger):
        where = f"[{index}] {record.spec} ({record.date})"
        if not _DATE.fullmatch(record.date):
            complaints.append(f"{where}: date is not YYYY-MM-DD")
        if not record.spec.strip():
            complaints.append(f"{where}: no allocating spec id")
        if not record.reason.strip():
            complaints.append(f"{where}: no reason; a ratification with no evidence is an edit")
        if record.direction not in _DIRECTIONS:
            complaints.append(
                f"{where}: direction {record.direction!r} is not one of {list(_DIRECTIONS)}"
            )
        if (record.direction == "genesis") != (index == 0):
            complaints.append(f"{where}: direction 'genesis' belongs to record 0 and to no other")
        if index and record.date < ledger[index - 1].date:
            complaints.append(f"{where}: dated before its predecessor {ledger[index - 1].date}")

    for index in range(1, len(ledger)):
        previous, current = ledger[index - 1], ledger[index]
        where = f"[{index}] {current.spec} ({current.date})"
        for key in sorted(set(previous.ceilings) | set(current.ceilings)):
            before, after = previous.ceilings.get(key), current.ceilings.get(key)
            if before == after:
                continue
            raised, lowered = _movement(before, after)
            shown_before = "absent" if before is None else before
            shown_after = "removed" if after is None else after
            if raised:
                if current.direction != "up":
                    complaints.append(
                        f"{where}: {key} RAISED {shown_before} -> {shown_after} in a record "
                        f"declaring direction={current.direction!r}; an upward movement must "
                        f"declare direction='up'"
                    )
                if not current.ruling.strip():
                    complaints.append(
                        f"{where}: {key} RAISED {shown_before} -> {shown_after} with NO ruling; "
                        f"a raise needs a PM ruling id in the diff"
                    )
                if key not in current.reason:
                    complaints.append(
                        f"{where}: {key} RAISED {shown_before} -> {shown_after} but the reason "
                        f"does not name the key"
                    )
            if lowered and current.direction != "down" and not raised:
                complaints.append(
                    f"{where}: {key} LOWERED {shown_before} -> {shown_after} in a record "
                    f"declaring direction={current.direction!r}; a tightening must declare "
                    f"direction='down' so it is recorded rather than furtive"
                )
    return complaints


def _movement(before: object, after: object) -> tuple[bool, bool]:
    """``(raised, lowered)`` for one key's value moving from *before* to *after*."""
    if before is None:
        return True, False
    if after is None:
        return False, True
    before_set, after_set = _as_set(before), _as_set(after)
    if before_set is not None and after_set is not None:
        return bool(after_set - before_set), bool(before_set - after_set)
    if isinstance(before, int) and isinstance(after, int):
        return after > before, after < before
    # A change of KIND (int <-> names) is both: it is neither a fall nor a rise.
    return True, True


# --------------------------------------------------------------------------- #
# `remeasure` -- the one command that re-derives every figure the records carry
# --------------------------------------------------------------------------- #

ENV_REPORT: Final = "PDF_RATCHET_REPORT"


def report(key: str, measured: object) -> None:
    """Append ``{key: measured}`` to the file named by ``PDF_RATCHET_REPORT``, if set.

    The exact arms call this BEFORE asserting, so a slack (or a growth) is still
    reported. Unset, it is a no-op: the suite pays nothing for the sink.
    """
    sink = os.environ.get(ENV_REPORT)
    if not sink:
        return
    with open(sink, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"key": key, "measured": measured}, sort_keys=True) + "\n")


#: The arms that call :func:`report`. Kept in ONE place so ``remeasure`` and the
#: commit body cannot drift apart.
MEASURING_NODES: Final[tuple[str, ...]] = (
    "tests/test_coverage_policy.py",
    "tests/test_docstring_pointers.py",
    "tests/test_read_seams.py",
    "tests/test_secret_leak_sweeps.py",
)


def _read_report(path: Path) -> dict[str, object]:
    out: dict[str, object] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        out[row["key"]] = row["measured"]
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """``uv run python tests/ratchet.py remeasure`` -- measure, then print the diff.

    Runs the measuring arms with ``PDF_RATCHET_REPORT`` set, then prints, per
    census key and per read-seam module, the MEASURED value beside the register's
    newest value and whether they agree. Exit 0 iff every figure agrees. Use it
    after rebasing onto an ``origin/main`` that moved a count (a landed read-seam
    record, a pragma, ...): copy the MEASURED column into the genesis/``down``
    records and amend.
    """
    import tempfile

    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["remeasure"]:
        print("usage: python tests/ratchet.py remeasure", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as scratch:
        sink = Path(scratch) / "report.jsonl"
        sink.write_text("")
        env = {**os.environ, ENV_REPORT: str(sink)}
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-n",
                "0",
                "-q",
                "-p",
                "no:randomly",
                "--no-header",
                "--no-cov",
                *MEASURING_NODES,
            ],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            stdout=subprocess.DEVNULL,
        )
        measured = _read_report(sink)
    if str(TESTS_DIR) not in sys.path:
        sys.path.insert(0, str(TESTS_DIR))
    import ceiling_register  # noqa: PLC0415

    registered: dict[str, object] = dict(ceiling_register.CEILING_LEDGER[-1].ceilings)
    seam_text = (REPO_ROOT / "tests" / "test_read_seams.py").read_text(encoding="utf-8")
    seam_newest = dict(dict(ledger_values(seam_text, "READ_SEAM_RESIDUE_LEDGER")[-1])["ceilings"])  # type: ignore[call-overload]
    disagree = 0
    print("== scalar ceilings (register, newest record) ==")
    for key in sorted(registered):
        got = measured.get(key, "<not measured: one-sided or arm skipped>")
        if isinstance(got, list):
            got = tuple(got)
        exact = key in measured
        mark = "ok " if (not exact or got == registered[key]) else "DIFF"
        disagree += mark == "DIFF"
        print(f"{mark} {key}: measured={got!r} registered={registered[key]!r}")
    print("== read-seam residue per module (READ_SEAM_RESIDUE_LEDGER[-1]) ==")
    residue = measured.get("read_seam_residue")
    if isinstance(residue, dict):
        for module in sorted(set(residue) | set(seam_newest)):
            got, want = residue.get(module, 0), seam_newest.get(module, 0)
            mark = "ok " if got == want else "DIFF"
            disagree += mark == "DIFF"
            print(f"{mark} {module}: measured={got} registered={want}")
    else:
        print("<not measured: the read-seam residue arm skipped (engine/root)>")
    print(f"disagreements: {disagree}")
    return 1 if disagree else 0


if __name__ == "__main__":
    raise SystemExit(main())
