"""PDF-22 Design D6 -- two mechanized sweeps, both B-073's and B-074's own
stated follow-ups, both promoted onto this spec by the groom.

`tests/test_import_boundaries.py` is the house precedent for an AST-walk
check over `src/`; this module is the sibling that walks `tests/` (Sweep 1)
and BOTH trees (Sweep 2). Neither sweep silently fixes what it finds --
genuine findings are FILED to the project-manager (AC11, AC13), never wired
here (`0615feae63`'s precedent: an unratified policy or a documented-but-dead
symbol is a FINDING, not an assertion to write).

PDF-69 -- both baselines are COMMITTED LITERALS (`SWEEP_1_CEILING`,
`SWEEP_2_GENUINE_CEILING`, `SWEEP_2_DEAD_BUT_HONEST_CEILING`), stamped with the
commit they were measured at (`BASELINES_MEASURED_AT`), and each sweep fails
when the LIVE measurement exceeds its literal. Until PDF-69 each baseline was
`len(<that same sweep>())` evaluated at import, so both assertions compared one
call of a pure function against another call of the same function, in the same
process, over the same tree: neither could fail, and sweep 1's "New instances"
list was unconditionally empty. Re-derived rather than argued about: the sweep-1
count was 65 when PDF-22 landed this module at `312b763`, 78 at `b16fb87` and 79
at `91c2aae` -- FOURTEEN rises across fifteen days, by an instrument written to
report a rise, none of them reported. A frozen literal may be LOWERED freely by
anyone who removes a finding; RAISING one is a recorded decision, never a bump
to green. `test_no_baseline_in_this_module_is_computed_from_the_tree` forbids
the import-time re-derivation returning under ANY name: the defect was a SHAPE,
and correcting the instance without forbidding the shape leaves the next
contributor free to re-introduce it with nothing able to say so.
"""

from __future__ import annotations

import ast
import functools
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import pytest

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

REPO_ROOT: Final[Path] = TESTS_DIR.parent
SRC: Final[Path] = REPO_ROOT / "src" / "pdf_tooling"

#: PDF-69 D4 -- the commit every frozen baseline in this module was MEASURED at,
#: in the shape `tests/golden/envelope_keys.json`'s `_meta.generated_at_commit`
#: already ships and `tests/test_envelope_contract.py:1255-1265` already grades:
#: forty lowercase hex characters that RESOLVE in this repository. Never an
#: abbreviation (the arm asserts forty), never the landing commit's own future
#: sha (it does not exist when the literal is written, so a stamp naming it names
#: nothing), never a placeholder. A provenance stamp naming a commit nobody can
#: resolve is not provenance; it is decoration with a serial number.
BASELINES_MEASURED_AT: Final[str] = "91c2aaeaddd3addf7f804645c52e818211eeb9fa"

# --------------------------------------------------------------------------- #
# Sweep 1 (B-073) -- assertions pinning a caller-supplied operand PRESENT in
# captured output.
# --------------------------------------------------------------------------- #

#: B-073's own contract: three tests literally named this way
#: (`tests/unit/test_safety_paths.py`), docstring at `:96-97` -- "The
#: canonical form is a key; it is never what the user reads back." Exempted
#: by this NAMING CONVENTION, never by line number (AC10).
_ECHOES_AS_WRITTEN: Final[re.Pattern[str]] = re.compile(r"echoes.*as_written")

#: An "output sink" variable name -- the compared-against side of a caller-
#: supplied-operand assertion. Heuristic, not exhaustive by design: this is
#: a SWEEP, and its own red control (below) is what proves it still fires.
_OUTPUT_SINK_NAME: Final[re.Pattern[str]] = re.compile(
    r"(combined|stdout|stderr|caplog\.text|payload|output|result\.output|text)", re.IGNORECASE
)

#: An "operand-shaped" right-hand identifier -- a caller-supplied value that
#: could be a path, a flag argument, or similar. Excludes bare booleans/None.
_OPERAND_SHAPED_NAME: Final[re.Pattern[str]] = re.compile(
    r"(path|argv|value|flag|source|target|file|dest)", re.IGNORECASE
)


def _is_operand_pin(node: ast.Assert) -> bool:
    """True when *node* is an `assert` whose comparison pins a caller-
    supplied-operand-SHAPED value present in / equal to an output-SINK-
    shaped expression. Heuristic and deliberately over-inclusive (a sweep
    that misses instances is worse than one with a few false positives a
    human triages), token-level rather than substring (`_OUTPUT_SINK_NAME`
    / `_OPERAND_SHAPED_NAME` both compile as regexes, not `in` checks)."""
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    op = test.ops[0]
    if not isinstance(op, (ast.In, ast.Eq)):
        return False
    left_src = ast.dump(test.left)
    right_src = ast.dump(test.comparators[0])
    sink_side = f"{left_src} {right_src}"
    if not _OUTPUT_SINK_NAME.search(sink_side):
        return False
    # The operand side: a Name/Attribute/f-string referencing a
    # path/argv/value-shaped identifier, or a literal that looks like a
    # filesystem path (contains a path separator).
    operand_nodes = [test.left, *test.comparators]
    for candidate in operand_nodes:
        for sub in ast.walk(candidate):
            if isinstance(sub, ast.Name) and _OPERAND_SHAPED_NAME.search(sub.id):
                return True
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                if "/" in sub.value or "\\" in sub.value:
                    return True
    return False


def _relative_to_repo(path: Path) -> str:
    """*path* as a repo-relative POSIX string when it lies under `REPO_ROOT`, and
    as an absolute POSIX string when it does not.

    PDF-69 D6 -- a scratch tree has no repo-relative spelling, and inventing one
    would put a falsehood into the failure message at exactly the moment the red
    control is the thing that fired."""
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


@functools.cache
def _sweep_1_candidates(root: Path = TESTS_DIR) -> tuple[tuple[str, int, str], ...]:
    """Every `assert` under *root* matching `_is_operand_pin`, excluding
    `tests/unit/test_safety_paths.py`'s documented-contract rows (exempted by
    ENCLOSING FUNCTION NAME, per AC10).

    PDF-69 D6 -- *root* is a PARAMETER defaulting to the real tree, the shape
    `test_coverage_policy.py`'s `pragma_sites(root)` already ships. It is what
    lets this sweep's red control run against a SCRATCH tree while the frozen
    ceiling below stays a statement about `tests/`; every existing caller is
    unchanged by the default. Cached because the function is pure over the tree
    within a process, and returning a TUPLE because a cached mutable return is a
    shared-state defect waiting for its first mutator (D7).

    UNBOUNDED rather than `maxsize=1`: D7's own stated reason for keying the
    cache on the root argument is that the scratch-tree arms and the real-tree
    count must "coexist in one process", and at `maxsize=1` they evict each
    other on every alternation instead. (`functools.cache` rather than
    `lru_cache(maxsize=None)` because `ruff`'s `UP033` requires it.)"""
    found: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*.py")):
        if path.name == "test_secret_leak_sweeps.py":
            continue  # this file's own red-control fixtures, below
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        enclosing = _enclosing_function_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert) and _is_operand_pin(node):
                func_name = enclosing.get(node, "")
                if _ECHOES_AS_WRITTEN.search(func_name):
                    continue
                found.append((_relative_to_repo(path), node.lineno, func_name))
    return tuple(sorted(found))


def _enclosing_function_names(tree: ast.AST) -> dict[ast.AST, str]:
    result: dict[ast.AST, str] = {}

    def _walk(node: ast.AST, current: str) -> None:
        name = current
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
        result[node] = name
        for child in ast.iter_child_nodes(node):
            _walk(child, name)

    _walk(tree, "")
    return result


#: MEASURED at `BASELINES_MEASURED_AT` by re-deriving `len(_sweep_1_candidates())`
#: on the unmodified tree before any of PDF-69's edits: **79**. (PDF-69's own spec
#: measured 78 at `b16fb87`; the +1 arrived with the two commits in between, and
#: the difference is information about those commits rather than an error in
#: either figure. 65 at `312b763`, PDF-22's landing, re-derived from a `git
#: archive` extraction rather than transcribed.)
#:
#: This ceiling may be LOWERED freely by anyone who removes an operand-pinning
#: assertion. RAISING it is a decision, not a diff: state in the commit body why
#: the new assertion must pin a caller-supplied operand PRESENT in captured
#: output, which is the thing B-073 exists to worry about. (A test cannot read a
#: commit body -- the mechanism is the ceiling; the process rule is this comment,
#: and both are copied line for line from `test_coverage_policy.py:62-70`'s
#: `PRAGMA_CEILING`, which is cited here and modified nowhere.)
#:
#: Renamed from `SWEEP_1_BASELINE` by PDF-69, and the rename is not cosmetic: the
#: old name claimed "MEASURED at landing" beside a value recomputed on every
#: import, and a constant whose NAME asserts a provenance it does not have is how
#: this defect stayed invisible for fifteen days and fourteen rises.
SWEEP_1_CEILING: Final[int] = 79


def _sweep_1_failure_message(candidates: tuple[tuple[str, int, str], ...], ceiling: int) -> str:
    """PDF-69 D2 -- the live count, the ceiling, the provenance commit, the two
    sanctioned responses, and EVERY live candidate rendered
    `path:lineno:function`, sorted, with no truncation and no `[:N]` slice.

    Built here rather than inline so the red control below grades the SAME text
    a contributor meeting this red would read. The pre-PDF-69 message computed
    its "New instances" as `[c for c in current if c not in _sweep_1_candidates()]`,
    which is unconditionally `[]` by construction: the naming half of this
    instrument was not weak, it was absent.
    """
    inventory = "\n  ".join(
        f"{path}:{lineno}:{function or '<module>'}" for path, lineno, function in sorted(candidates)
    )
    return (
        f"{len(candidates)} unexempted operand-pinning assertions in the swept tree, above "
        f"the frozen ceiling of {ceiling} measured at {BASELINES_MEASURED_AT}.\n"
        "Two responses are sanctioned and no third is. If you REMOVED a pin, lower the "
        "ceiling -- that is free and needs no ceremony. If you ADDED one, that is a "
        "recorded decision: say in the commit body why this assertion must pin a "
        "caller-supplied operand present in captured output (B-073), and raise the ceiling "
        "in the same commit. Raising it to reach green, with no reason beside it, is "
        "precisely the act this ceiling exists to prevent.\n"
        f"Every live candidate, sorted and untruncated ({len(candidates)}):\n  {inventory}"
    )


def test_sweep_1_b073_the_live_count_does_not_exceed_the_frozen_ceiling() -> None:
    """AC10, repaired by PDF-69 -- fails when the count of unexempted operand-
    pinning assertions under `tests/` rises above the COMMITTED ceiling.

    Before PDF-69 both sides of this comparison were the same call:
    `SWEEP_1_BASELINE` was `len(_sweep_1_candidates())` evaluated at import and
    this arm called `_sweep_1_candidates()` again, in the same process over the
    same tree. The ceiling is now a literal a human wrote down at a named
    commit, which is the only thing a live measurement can actually be graded
    against.
    """
    current = _sweep_1_candidates()
    assert len(current) <= SWEEP_1_CEILING, _sweep_1_failure_message(current, SWEEP_1_CEILING)


def test_sweep_1_b073_the_safety_paths_contract_is_exempted_by_convention(tmp_path: Path) -> None:
    """Non-vacuity: `tests/unit/test_safety_paths.py`'s own `..._echoes_the_
    path_as_written`-named tests exist and WOULD match `_is_operand_pin` if
    not exempted -- confirmed by AST-walking a copy of one such function
    body in isolation, without the enclosing-name exemption applied."""
    sample = (
        "def test_a_collision_message_echoes_the_path_as_written():\n"
        "    combined = 'refused: /tmp/real/path'\n"
        "    assert str(real_path) in combined\n"
    )
    tree = ast.parse(sample)
    asserts = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    assert asserts, "the sample has no assert to test against"
    assert _is_operand_pin(asserts[0]), (
        "the sample assertion did not match the operand-pin shape at all -- "
        "the exemption test below would then prove nothing"
    )


def test_sweep_1_b073_red_control_a_planted_pin_is_caught(tmp_path: Path) -> None:
    """AC10's own red control: plant one new assertion pinning a
    `--password-file`-shaped argument present in captured output, in a
    SCRATCH file under `tmp_path` (never the working tree -- HC-4), and
    confirm `_is_operand_pin` fires on it."""
    planted = tmp_path / "planted_leak_test.py"
    planted.write_text(
        "def test_a_planted_pin():\n"
        "    combined = 'error: --password-file (secret-value-path)'\n"
        "    assert password_file_value in combined\n"
    )
    tree = ast.parse(planted.read_text(), filename=str(planted))
    asserts = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    assert any(_is_operand_pin(node) for node in asserts), (
        "a planted assertion pinning a password-file-shaped argument present "
        "was NOT caught -- the sweep cannot fire and is decoration"
    )


#: The pin the two arms below plant. One assertion, matching `_is_operand_pin`
#: on both sides (`combined` is output-sink-shaped, `password_file_value` is
#: operand-shaped), on line 3 of the file it is written into.
_PLANTED_PIN_SOURCE: Final[str] = (
    "def test_a_planted_pin():\n"
    "    combined = 'error: --password-file (secret-value-path)'\n"
    "    assert password_file_value in combined\n"
)
_PLANTED_PIN_LINENO: Final[int] = 3


def test_sweep_1_b073_planted_pins_raise_the_count_and_every_ONE_is_named(
    tmp_path: Path,
) -> None:
    """PDF-69 AC2 (the rising direction) and AC4 (the naming half), SHIPPED.

    Driven against a SCRATCH root, never the working tree (HC-4), which is what
    `_sweep_1_candidates`' `root` parameter exists for (D6). The real-tree
    end-to-end observation -- plant into a scanned `tests/` file before pytest
    starts, then grep the captured failure text for the planted `path:lineno` --
    was driven by hand at landing and recorded in PDF-69's Implementation Log;
    this arm is the half that stays in the suite.

    The message is graded by GREPPING it for each planted location, never by
    reading the format string: a format string that looks right and renders
    nothing is the exact failure mode this instrument shipped with for fifteen
    days.

    FOUR pins across THREE files, not one, and the inventory's row count is
    asserted -- which is not fastidiousness. A single-pin fixture was driven
    first, and a `sorted(candidates)[:1]` slice planted into
    `_sweep_1_failure_message` left it GREEN: at one candidate a truncating
    message is byte-identical to a complete one. D2 forbids a `[:N]` slice
    precisely because truncation is how the naming half breaks a second time,
    and an arm that cannot see the slice does not hold that clause.
    """
    quiet = tmp_path / "quiet"
    quiet.mkdir()
    (quiet / "test_quiet.py").write_text("def test_nothing():\n    assert True\n")
    assert _sweep_1_candidates(quiet) == (), (
        "the scratch baseline is not empty, so a rise below would prove nothing"
    )

    planted_root = tmp_path / "planted"
    planted_root.mkdir()
    (planted_root / "test_quiet.py").write_text("def test_nothing():\n    assert True\n")
    expected: list[str] = []
    for name in ("test_planted_leak_a.py", "test_planted_leak_b.py"):
        planted = planted_root / name
        planted.write_text(_PLANTED_PIN_SOURCE)
        expected.append(f"{planted.as_posix()}:{_PLANTED_PIN_LINENO}")
    twice = planted_root / "test_planted_leak_twice.py"
    twice.write_text(_PLANTED_PIN_SOURCE + "\n\n" + _PLANTED_PIN_SOURCE)
    expected.append(f"{twice.as_posix()}:{_PLANTED_PIN_LINENO}")
    expected.append(f"{twice.as_posix()}:{_PLANTED_PIN_LINENO + 5}")

    after = _sweep_1_candidates(planted_root)
    assert len(after) == len(expected), f"the planted pins did not move the count: {after}"

    message = _sweep_1_failure_message(after, len(_sweep_1_candidates(quiet)))
    missing = [location for location in expected if location not in message]
    assert missing == [], (
        f"the failure message does not name {len(missing)} of the {len(expected)} planted "
        "assertions. A red that names nothing -- or names only some -- is the pre-PDF-69 "
        f"behaviour wearing a new message:\n{message}"
    )
    rows = [row for row in message.splitlines() if planted_root.as_posix() in row]
    assert len(rows) == len(after), (
        f"the inventory rendered {len(rows)} of {len(after)} candidates: it is TRUNCATED, "
        f"which D2 forbids outright:\n{message}"
    )


def test_sweep_1_b073_removing_a_pin_is_never_punished(tmp_path: Path) -> None:
    """PDF-69 AC2's second direction, SHIPPED. One direction alone proves
    nothing: the arm above shows the ratchet fires, this one shows improvement
    is not punished. A ratchet that reds when debt is PAID DOWN is not a fix, it
    is the defect PDF-70 spent a whole item removing from two sibling
    instruments, newly installed here.

    Driven through the same `<=` comparison the live arm makes, against a
    ceiling frozen at the larger tree's count.
    """
    two = tmp_path / "two"
    two.mkdir()
    (two / "test_pin_a.py").write_text(_PLANTED_PIN_SOURCE)
    (two / "test_pin_b.py").write_text(_PLANTED_PIN_SOURCE)
    one = tmp_path / "one"
    one.mkdir()
    (one / "test_pin_a.py").write_text(_PLANTED_PIN_SOURCE)

    ceiling = len(_sweep_1_candidates(two))
    assert ceiling == 2, f"the fixture is only meaningful at two pins: {_sweep_1_candidates(two)}"
    assert len(_sweep_1_candidates(one)) <= ceiling


# --------------------------------------------------------------------------- #
# Sweep 2 (B-074) -- attributes documented as behaviour-changing that no
# branch reads. Scans BOTH `src/` and `tests/` (AC12: a `src/`-only walk is
# WRONG -- at least six symbols in this codebase are read only from `tests/`).
# --------------------------------------------------------------------------- #

#: Behavioural-claim vocabulary (D6's own list), matched against the `#:`
#: comment block immediately preceding a module-level assignment -- this
#: codebase's own attribute-docstring convention (`registry.py`'s
#: `PDF_08_VERBS`, `cli/common.py`'s `PASSWORD_FILE_FLAGS`, etc. all use it).
_BEHAVIOURAL_CLAIM: Final[re.Pattern[str]] = re.compile(
    r"\b(honour|honor|branch on|gate|enforce|consult|read by|allowlist|"
    r"narrower than|member of this set|test (checks|asserts|iterates|pins)|"
    r"validated against)\b",
    re.IGNORECASE,
)

#: D6's own documented-deliberate-no-op marker. A symbol whose comment
#: block carries this is skipped entirely -- the inverse of B-074, and it
#: needs an explicit convention or the sweep would flag it forever.
_INTENTIONALLY_UNREAD: Final[str] = "intentionally unread"


def _preceding_comment_block(source_lines: list[str], lineno: int) -> str:
    """The contiguous `#`-prefixed comment lines immediately above *lineno*
    (1-based), THIS codebase's attribute-docstring convention."""
    collected: list[str] = []
    index = lineno - 2  # 0-based line just above the assignment
    while index >= 0:
        stripped = source_lines[index].strip()
        if stripped.startswith("#"):
            collected.append(stripped)
            index -= 1
            continue
        if stripped == "":
            index -= 1
            continue
        break
    return "\n".join(reversed(collected))


def _module_level_candidates(path: Path) -> list[tuple[str, str, int]]:
    """`(name, comment_block, lineno)` for every module-level `Name = ...`
    or `Name: Ann = ...` assignment outside an `Enum`/`StrEnum` class body,
    whose preceding comment matches the behavioural-claim vocabulary and is
    not marked intentionally-unread."""
    source = path.read_text()
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    out: list[tuple[str, str, int]] = []
    for node in tree.body:  # module level only
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.target is not None:
            targets = [node.target]
        else:
            continue
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            name = target.id
            if name == "__all__" or name.startswith("__"):
                continue
            comment = _preceding_comment_block(lines, node.lineno)
            if _INTENTIONALLY_UNREAD in comment.lower():
                continue
            if _BEHAVIOURAL_CLAIM.search(comment):
                out.append((name, comment, node.lineno))
    return out


def _token_reference_count(name: str, text: str) -> int:
    """Token-level (``\\b...\\b``), not substring -- D6's own recorded
    false-positive: a naive ``name in text`` scan collided ``MODES`` with
    ``IMAGE_MODES``. Quoted occurrences are excluded on BOTH conventions
    this codebase uses to refer to a symbol WITHOUT reading it: Python
    string literals (single/double quotes, e.g. inside ``__all__``) AND
    backtick-wrapped prose mentions in comments/docstrings (this codebase's
    own convention -- ``ops/split.py:44``'s "`ops/merge.py::BOOKMARK_MODES`
    is..." is a cross-reference IN PROSE, not a read; an earlier version of
    this sweep counted it as one and is corrected here)."""
    pattern = re.compile(rf"""(?<!['"`])\b{re.escape(name)}\b(?!['"`])""")
    return len(pattern.findall(text))


def _is_enum_class_body(tree: ast.Module, node: ast.Assign | ast.AnnAssign) -> bool:
    for candidate in ast.walk(tree):
        _enum_names = ("Enum", "StrEnum", "IntEnum", "Flag")
        if isinstance(candidate, ast.ClassDef) and any(
            (isinstance(base, ast.Name) and base.id in _enum_names)
            or (isinstance(base, ast.Attribute) and base.attr in _enum_names)
            for base in candidate.bases
        ):
            if node in ast.walk(candidate):
                return True
    return False


@functools.lru_cache(maxsize=1)
def _sweep_2_candidates() -> tuple[tuple[str, str], ...]:
    """`(symbol, "genuine" | "dead-but-honest")` for every documented-as-
    honoured symbol under `src/pdf_tooling/` with ZERO token-level reads in
    BOTH `src/` and `tests/` outside its own definition line, excluding
    `to_dict()`-only loads (bucketed separately -- D6 item 4).

    PDF-69 D7 -- cached and returning a TUPLE. Five arms below call it where
    they used to read a module constant computed once at import, and paying the
    sweep's full cost five times per process would be a regression dressed as a
    repair. A cached MUTABLE return would be a shared-state defect waiting for
    its first mutator."""
    src_files = sorted(SRC.rglob("*.py"))
    test_files = sorted(TESTS_DIR.rglob("*.py"))
    all_files = [*src_files, *test_files]
    corpus_text = {path: path.read_text() for path in all_files}

    results: list[tuple[str, str]] = []
    for path in src_files:
        source = corpus_text[path]
        tree = ast.parse(source, filename=str(path))
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            if isinstance(node, ast.AnnAssign) and node.target is None:
                continue
            if _is_enum_class_body(tree, node):
                continue
            for candidate in _module_level_candidates(path):
                name, comment, lineno = candidate
                if node.lineno != lineno:
                    continue
                total_reads = 0
                to_dict_only_reads = 0
                for other_path in all_files:
                    text = corpus_text[other_path]
                    count = _token_reference_count(name, text)
                    if other_path == path:
                        # subtract the definition's own occurrence(s) on this line
                        own_lines = text.splitlines()
                        def_line = own_lines[lineno - 1] if lineno - 1 < len(own_lines) else ""
                        count -= _token_reference_count(name, def_line)
                    total_reads += count
                    if count and _only_inside_to_dict(other_path, name, corpus_text[other_path]):
                        to_dict_only_reads += count
                location = f"{path.relative_to(REPO_ROOT)}:{lineno} {name}"
                if total_reads == 0:
                    results.append((location, "genuine"))
                elif total_reads == to_dict_only_reads:
                    results.append((location, "dead-but-honest"))
    return tuple(results)


def _only_inside_to_dict(path: Path, name: str, text: str) -> bool:
    """Whether EVERY token-level reference to *name* in *path* falls inside
    a method literally named `to_dict` -- D6 item 4: `to_dict()`-only loads
    are legitimate (serialized, therefore honoured), bucketed separately."""
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:  # pragma: no cover - not expected on this tree
        return False
    pattern = re.compile(rf"""(?<!['"`])\b{re.escape(name)}\b(?!['"`])""")
    all_lines = {match.start() for match in pattern.finditer(text)}
    if not all_lines:
        return False
    inside_to_dict_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "to_dict":
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            lines = text.splitlines(keepends=True)
            offset = sum(len(line) for line in lines[: start - 1])
            body_text = "".join(lines[start - 1 : end])
            for match in pattern.finditer(body_text):
                inside_to_dict_lines.add(offset + match.start())
    return all_lines <= inside_to_dict_lines


def _identity_key(location: str) -> str:
    """`src/.../merge.py:55 BOOKMARK_MODES` -> `src/.../merge.py::BOOKMARK_MODES`.

    PDF-69 D3 -- the frozen key carries NO line number, and that is the one
    place PDF-69 departs from its own improvement report's literal wording.
    Between `312b763` and `b16fb87` every one of this sweep's three keys
    changed, for two reasons and neither of them a defect: PDF-48 renamed the
    package, and ordinary edits above the symbols moved `:53` -> `:55`,
    `:78` -> `:86` and `:84` -> `:92`. A ceiling frozen on `path:lineno symbol`
    strings would therefore red on any insertion above three unrelated symbols.
    The live line number belongs in the DIAGNOSIS, and is printed there; it
    never belongs in the frozen key."""
    located, _, name = location.rpartition(" ")
    return f"{located.rpartition(':')[0]}::{name}"


#: MEASURED at `BASELINES_MEASURED_AT` -- the three genuine findings (F1-F3)
#: PDF-22 FILED and deliberately did not fix (AC13), frozen as SYMBOL IDENTITIES
#: rather than as coordinates.
#:
#: Compared under SUBSET, never equality, and the three properties that buys are
#: each separately asserted below: a NEW genuine finding reds (the ratchet);
#: WIRING one of the three stays green; and an edit that merely moves a symbol's
#: line changes nothing. An equality here would red on IMPROVEMENT -- the exact
#: class PDF-70 spent a whole item removing from two sibling instruments -- and
#: installing a fresh instance of a just-removed defect, one arm away from this
#: spec's own subject, would be indefensible.
#:
#: LOWERING this ceiling (deleting a key because the symbol is now read) is free
#: and needs no ceremony. ADDING one is a recorded decision, and B-074's answer
#: is to WIRE the symbol or FILE it, never to widen the ceiling to accommodate
#: it. `_sweep_2_candidates` is byte-unchanged in what it detects; only what its
#: result is compared against has moved.
SWEEP_2_GENUINE_CEILING: Final[tuple[str, ...]] = (
    "src/pdf_tooling/ops/merge.py::BOOKMARK_MODES",
    "src/pdf_tooling/ops/metadata.py::CLEARABLE_FIELDS",
    "src/pdf_tooling/ops/metadata.py::SETTABLE_FIELDS",
)

#: The `to_dict()`-only bucket (D6 item 4), frozen the same way and EMPTY at
#: `BASELINES_MEASURED_AT`. An empty ceiling under subset is the sharpest form
#: this instrument takes: any arrival at all reds, and naming it costs nothing.
SWEEP_2_DEAD_BUT_HONEST_CEILING: Final[tuple[str, ...]] = ()


def _sweep_2_live(bucket: str) -> tuple[str, ...]:
    """The live locations in *bucket*, sorted.

    PDF-69 D7 -- the four arms that used to read the `SWEEP_2_GENUINE` /
    `SWEEP_2_DEAD_BUT_HONEST` module constants read this instead. Each of them
    asserts exactly what it asserted before; only the reference moved, from a
    constant computed at import to a call."""
    return tuple(sorted(location for location, kind in _sweep_2_candidates() if kind == bucket))


def sweep_2_arrivals(
    live: Sequence[tuple[str, str]], bucket: str, ceiling: Sequence[str]
) -> list[str]:
    """Live locations in *bucket* whose IDENTITY is absent from *ceiling*, sorted.
    Empty means the subset ratchet holds.

    PURE OVER ITS PARAMETERS, the shape `read_seam_ratification_complaints`
    already ships in `tests/test_read_seams.py`: synthetic populations drive it
    in-process on every run, so both directions of D3's ratchet are asserted
    without a scratch checkout of `src/` and the real ceiling is never edited to
    prove a point. It RETURNS arrivals rather than raising, so the accepting
    direction is as ordinary to assert as the refusing one."""
    frozen = set(ceiling)
    return sorted(
        location
        for location, kind in live
        if kind == bucket and _identity_key(location) not in frozen
    )


def test_sweep_2_b074_no_documented_but_unread_symbol_has_arrived() -> None:
    """AC12, repaired by PDF-69 -- fails when a symbol documented as
    behaviour-changing that nothing reads arrives in either bucket.

    Before PDF-69 this was `current == SWEEP_2_GENUINE` where `SWEEP_2_GENUINE`
    was derived from `_sweep_2_candidates()` at import and `current` called it
    again: a tautology, and an EQUALITY besides, so had it been able to fire it
    would have fired on the three findings being FIXED.
    """
    live = _sweep_2_candidates()
    for bucket, ceiling in (
        ("genuine", SWEEP_2_GENUINE_CEILING),
        ("dead-but-honest", SWEEP_2_DEAD_BUT_HONEST_CEILING),
    ):
        arrivals = sweep_2_arrivals(live, bucket, ceiling)
        assert arrivals == [], (
            f"{len(arrivals)} '{bucket}' symbol(s) documented as behaviour-changing that "
            f"nothing reads have arrived since {BASELINES_MEASURED_AT}, each shown with its "
            "LIVE line number:\n  " + "\n  ".join(arrivals) + "\n"
            f"Frozen identities in this bucket ({len(ceiling)}): {list(ceiling)}.\n"
            "B-074's answer is to WIRE the symbol or FILE it to the project-manager; "
            "widening this ceiling to reach green is the act it exists to prevent. "
            "Removing a key because the symbol is now read is free."
        )


def test_sweep_2_b074_f1_f2_f3_are_found() -> None:
    """AC13 -- the three named findings (`ops/merge.py` `BOOKMARK_MODES`,
    `ops/metadata.py` `SETTABLE_FIELDS` and `CLEARABLE_FIELDS`) are among
    the sweep's own genuine results, confirming the mechanism is not merely
    passing by missing everything."""
    genuine = _sweep_2_live("genuine")
    names = {entry.rsplit(" ", 1)[-1] for entry in genuine}
    for expected in ("BOOKMARK_MODES", "SETTABLE_FIELDS", "CLEARABLE_FIELDS"):
        assert expected in names, f"{expected} not found by the sweep -- {genuine}"


def test_sweep_2_b074_enum_classes_are_never_flagged() -> None:
    """D6 item 2 -- `StrEnum`/`Enum` members are consumed by Typer iterating
    the CLASS, never by member name; skipping them is required or the sweep
    would flag ~13 false positives (`OutputFormat`'s own members among
    them)."""
    names = {
        entry.rsplit(" ", 1)[-1]
        for entry in (*_sweep_2_live("genuine"), *_sweep_2_live("dead-but-honest"))
    }
    assert "TABLE" not in names and "JSON" not in names and "NDJSON" not in names, (
        "an OutputFormat enum member was flagged -- the Enum-class exemption is not firing"
    )


def test_sweep_2_b074_dunders_and_all_are_never_flagged() -> None:
    names = {
        entry.rsplit(" ", 1)[-1]
        for entry in (*_sweep_2_live("genuine"), *_sweep_2_live("dead-but-honest"))
    }
    assert not any(name.startswith("__") for name in names)
    assert "__all__" not in names


def test_sweep_2_b074_token_level_matching_does_not_collide_modes_and_fields() -> None:
    """D6 item 5's own recorded false-positive: a naive `name in text` scan
    collides `MODES` with `IMAGE_MODES`/`BOOKMARK_MODES`, and `FIELDS` with
    `SETTABLE_FIELDS`. Confirmed directly against `_token_reference_count`."""
    haystack = "IMAGE_MODES = (...)\nBOOKMARK_MODES = (...)\nSETTABLE_FIELDS = (...)\n"
    assert _token_reference_count("MODES", haystack) == 0
    assert _token_reference_count("FIELDS", haystack) == 0
    assert _token_reference_count("IMAGE_MODES", haystack) == 1
    assert _token_reference_count("BOOKMARK_MODES", haystack) == 1
    assert _token_reference_count("SETTABLE_FIELDS", haystack) == 1


def test_sweep_2_b074_intentionally_unread_marker_suppresses_the_two_documented_no_ops() -> None:
    """D6 item 9 -- `ports/__init__.py`'s `KIND_OPTIONAL_EXTRA` and
    `output/logging.py`'s `_SECRETS` are unread ON PURPOSE and say so; they
    must NOT appear among either bucket, or the check would flag them
    forever and train reviewers to ignore its output."""
    everything = (*_sweep_2_live("genuine"), *_sweep_2_live("dead-but-honest"))
    all_flagged = {entry.rsplit(" ", 1)[-1] for entry in everything}
    assert "KIND_OPTIONAL_EXTRA" not in all_flagged
    assert "_SECRETS" not in all_flagged


def test_sweep_2_b074_red_control_the_pre_fix_redacted_symbol_is_caught(tmp_path: Path) -> None:
    """AC12's own red control: re-plant the pre-fix shape -- a module-level
    symbol documented as "honoured" that nothing reads -- in an isolated
    scratch tree (never the working tree, HC-4) and confirm the SAME
    mechanism `_module_level_candidates` + a zero-read count fires on it."""
    scratch_src = tmp_path / "planted_module.py"
    scratch_src.write_text(
        "#: honoured from the first commit -- a test checks this value.\n"
        "REDACTED_FLAG_PLANTED = True\n"
    )
    candidates = _module_level_candidates(scratch_src)
    assert candidates, "the planted symbol was not even recognized as a candidate"
    name, _comment, _lineno = candidates[0]
    assert name == "REDACTED_FLAG_PLANTED"
    other_text = "print('nothing here reads it')\n"
    assert _token_reference_count(name, other_text) == 0, (
        "the planted symbol's own red control did not read as zero elsewhere -- "
        "the mutation is not isolated"
    )


def test_sweep_2_b074_a_new_genuine_finding_is_refused_and_named_with_its_live_line() -> None:
    """PDF-69 AC3, the rising direction, driven over a synthetic population.

    `sweep_2_arrivals` is pure over its parameters, so the ratchet's refusing
    behaviour is asserted without editing the real ceiling or staging a scratch
    `src/` checkout. The arrival carries its LIVE line number, which is what
    makes the diagnosis actionable while the frozen key stays coordinate-free.
    """
    live = (
        ("src/pdf_tooling/ops/merge.py:55 BOOKMARK_MODES", "genuine"),
        ("src/pdf_tooling/ops/newly.py:12 NEWLY_DOCUMENTED_FLAG", "genuine"),
    )
    arrivals = sweep_2_arrivals(live, "genuine", ("src/pdf_tooling/ops/merge.py::BOOKMARK_MODES",))
    assert arrivals == ["src/pdf_tooling/ops/newly.py:12 NEWLY_DOCUMENTED_FLAG"], arrivals


def test_sweep_2_b074_wiring_a_known_finding_is_never_punished() -> None:
    """PDF-69 AC3's second direction, and the reason `==` is forbidden here.

    One of the three frozen findings gains a read and therefore leaves the live
    set. Under the pre-PDF-69 equality that is a FAILURE -- an instrument that
    reds when a documented-but-dead symbol is finally wired, which is R-06's
    defect being installed rather than removed. Under subset it is silence, and
    the stale key may be dropped whenever someone notices, for free.
    """
    live = (("src/pdf_tooling/ops/metadata.py:86 SETTABLE_FIELDS", "genuine"),)
    ceiling = (
        "src/pdf_tooling/ops/merge.py::BOOKMARK_MODES",
        "src/pdf_tooling/ops/metadata.py::SETTABLE_FIELDS",
    )
    live_keys = tuple(sorted(_identity_key(location) for location, _ in live))
    assert live_keys != tuple(sorted(ceiling)), (
        "the fixture is only meaningful while the wired finding actually left the live "
        "set -- an EQUALITY over these two would have red, which is the comparison "
        "PDF-69 replaced"
    )
    assert sweep_2_arrivals(live, "genuine", ceiling) == []


def test_sweep_2_b074_a_symbol_moving_line_is_not_a_finding() -> None:
    """PDF-69 D3/E4 -- the coordinate-rot class, designed out rather than lived
    with. Between `312b763` and `b16fb87` all three keys moved line for reasons
    unrelated to this instrument; a ceiling frozen on coordinates would have red
    on each one."""
    live = (("src/pdf_tooling/ops/merge.py:9999 BOOKMARK_MODES", "genuine"),)
    ceiling = ("src/pdf_tooling/ops/merge.py::BOOKMARK_MODES",)
    assert sweep_2_arrivals(live, "genuine", ceiling) == []


def test_sweep_2_b074_the_ratchet_is_wired_to_the_real_sweep_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PDF-69 AC3, end to end. The three arms above drive `sweep_2_arrivals`
    over a synthetic population, which proves the COMPARISON; this one drives
    the real `_sweep_2_candidates` over a scratch tree, which proves the
    comparison is wired to the sweep that feeds it. Neither half establishes the
    other: a pure comparison nothing calls is dead code, and a live sweep whose
    result is compared against itself is what PDF-69 exists to repair.

    The module globals are repointed for the duration and the cache is cleared
    on both sides -- a cached function whose purity is over MODULE STATE is only
    pure while that state holds still.
    """
    scratch_src = tmp_path / "src" / "pkg"
    scratch_src.mkdir(parents=True)
    (scratch_src / "mod.py").write_text(
        "#: honoured on every run -- a test asserts this value.\nSCRATCH_DOCUMENTED_FLAG = True\n"
    )
    scratch_tests = tmp_path / "tests"
    scratch_tests.mkdir()
    (scratch_tests / "test_quiet.py").write_text("def test_nothing():\n    assert True\n")

    monkeypatch.setitem(globals(), "SRC", scratch_src)
    monkeypatch.setitem(globals(), "TESTS_DIR", scratch_tests)
    monkeypatch.setitem(globals(), "REPO_ROOT", tmp_path)
    _sweep_2_candidates.cache_clear()
    try:
        live = _sweep_2_candidates()
        arrivals = sweep_2_arrivals(live, "genuine", SWEEP_2_GENUINE_CEILING)
        assert [entry.rsplit(" ", 1)[-1] for entry in arrivals] == ["SCRATCH_DOCUMENTED_FLAG"], (
            f"the scratch symbol did not reach the ratchet through the real sweep: {live}"
        )
        assert sweep_2_arrivals(live, "genuine", ("src/pkg/mod.py::SCRATCH_DOCUMENTED_FLAG",)) == []
    finally:
        _sweep_2_candidates.cache_clear()


# --------------------------------------------------------------------------- #
# PDF-69 D5 -- the SHAPE forbidden, not merely the instance corrected.
#
# The fix above repairs two assertions. This arm forbids the defect CLASS, and
# it is the deliverable here with the longest half-life: a future contributor
# who re-derives a baseline at import time must get a RED, not a green, under
# any name they choose for it.
# --------------------------------------------------------------------------- #

#: The names PDF-69 froze. Each must bind a LITERAL at module scope -- an
#: `ast.Call`, an `ast.Name`, a comprehension or a `BinOp` is a red.
_FROZEN_BASELINE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "BASELINES_MEASURED_AT",
        "SWEEP_1_CEILING",
        "SWEEP_2_DEAD_BUT_HONEST_CEILING",
        "SWEEP_2_GENUINE_CEILING",
    }
)

#: The two sweeps. Neither may be CALLED by a module-level statement in this
#: file, under any binding name or under none. Condition 1 is a per-NAME check
#: that a contributor evades simply by computing under a fresh name; condition 2
#: forbids the shape regardless of naming, and it is the clause that matters.
_SWEEP_FUNCTION_NAMES: Final[frozenset[str]] = frozenset(
    {"_sweep_1_candidates", "_sweep_2_candidates"}
)


def _is_literal_display(node: ast.expr | None) -> bool:
    """Whether *node* is a literal, or a tuple/list/set/dict display whose every
    element is one. Deliberately NOT `ast.literal_eval`: that accepts a `BinOp`
    over constants, and a baseline spelled `65 + 14` is a derivation wearing a
    literal's clothes."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_literal_display(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        return all(_is_literal_display(key) for key in node.keys) and all(
            _is_literal_display(value) for value in node.values
        )
    return False


def _called_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def computed_baseline_complaints(
    source: str, *, required: frozenset[str] = _FROZEN_BASELINE_NAMES
) -> list[str]:
    """Every way *source* COMPUTES a frozen baseline rather than writing one
    down. Empty means the shape holds.

    Two conditions, and the second is the one with teeth:

    1. every name in *required* is bound at module scope, exactly to a literal;
    2. no module-level statement calls either sweep, under any binding name.

    PURE OVER ITS PARAMETER, so its own non-vacuity is asserted against planted
    sources in-process rather than by mutating the shipped module -- the same
    reason `read_seam_ratification_complaints` takes its ledger as an argument.
    It RETURNS complaints rather than raising, so the accepting direction is as
    ordinary to assert as the refusing one.
    """
    tree = ast.parse(source, filename="<checked-module>")
    complaints: list[str] = []
    bound: set[str] = set()

    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.target is not None:
            targets = [node.target]
        else:
            continue
        for target in targets:
            if not isinstance(target, ast.Name) or target.id not in required:
                continue
            bound.add(target.id)
            if not _is_literal_display(node.value):
                shape = type(node.value).__name__ if node.value is not None else "nothing"
                complaints.append(
                    f"line {node.lineno}: {target.id} is bound to an `ast.{shape}`, not to a "
                    f"literal. A frozen baseline must be WRITTEN DOWN at a named commit; one "
                    f"computed at import compares the tree against itself and cannot fail"
                )

    for name in sorted(required - bound):
        complaints.append(
            f"{name} is not bound at module scope. A frozen baseline that is not there is "
            f"not a lowered ceiling, it is an absent instrument"
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and _called_name(sub.func) in _SWEEP_FUNCTION_NAMES:
                complaints.append(
                    f"line {sub.lineno}: module-level call to {_called_name(sub.func)}(). "
                    f"Re-deriving a baseline at import is the PDF-69 defect whatever the "
                    f"result is bound to -- the tautology was the SHAPE, not the two names "
                    f"it happened to wear"
                )
    return complaints


def test_no_baseline_in_this_module_is_computed_from_the_tree() -> None:
    """PDF-69 AC1/AC6, on this module's own source.

    Applied to the pre-PDF-69 file this arm fails on BOTH conditions:
    `SWEEP_1_BASELINE` and `_SWEEP_2_RESULTS` were each bound to an `ast.Call`,
    and both sweeps were called at module scope.

    Reading this file is free of consequence for the read-seam `RESIDUE_CEILING`
    (`tests/test_read_seams.py:66`): that census is scoped to `SRC_ROOT`, so a
    `read_text()` added inside `tests/` is outside it entirely.
    """
    complaints = computed_baseline_complaints(Path(__file__).read_text(encoding="utf-8"))
    assert complaints == [], (
        "a baseline in this module is computed rather than committed:\n  "
        + "\n  ".join(complaints)
        + "\nThis is PDF-69's own defect returning. A baseline measured at import from the "
        "same function the assertion calls again compares the tree against itself: it "
        "cannot fail, and for fifteen days it did not."
    )


def _shape_fixture(extra: str = "") -> str:
    """A synthetic module binding all four frozen names to literals, plus an
    optional extra statement. The positive control below asserts the checker
    accepts it, so every red case here differs from an accepted module by
    exactly the mutation it plants."""
    zeros = "0" * 40
    return (
        "from typing import Final\n"
        f'BASELINES_MEASURED_AT: Final[str] = "{zeros}"\n'
        "SWEEP_1_CEILING: Final[int] = 5\n"
        'SWEEP_2_GENUINE_CEILING: Final[tuple[str, ...]] = ("a/b.py::C",)\n'
        "SWEEP_2_DEAD_BUT_HONEST_CEILING: Final[tuple[str, ...]] = ()\n"
    ) + extra


def test_the_shape_checker_accepts_a_module_that_writes_its_baselines_down() -> None:
    """The positive half, and it is not optional. A checker that flagged
    everything would pass every red case below and be deleted rather than fixed
    the first time it fired on honest code."""
    assert computed_baseline_complaints(_shape_fixture()) == []


def test_the_shape_checker_catches_the_pdf69_defect_under_its_own_name() -> None:
    """Condition 1: the exact shape this module shipped with at `91c2aae`."""
    mutation = "SWEEP_1_CEILING: Final[int] = len(_sweep_1_candidates())"
    source = _shape_fixture().replace("SWEEP_1_CEILING: Final[int] = 5", mutation)
    joined = " ".join(computed_baseline_complaints(source))
    assert "SWEEP_1_CEILING" in joined, joined
    assert "_sweep_1_candidates" in joined, joined


def test_the_shape_checker_catches_a_re_derivation_under_any_new_name() -> None:
    """PDF-69 AC6, THE criterion the roadmap singles out and the reason
    condition 2 exists.

    Condition 1 is a per-name check, and a contributor who wants a live figure
    at import evades it in one keystroke by choosing a name the frozen set does
    not contain. Condition 2 forbids the shape itself: any module-level call to
    either sweep is a red, and the complaint names the offending line.
    """
    mutation = "_LIVE: Final[int] = len(_sweep_1_candidates())"
    source = _shape_fixture(mutation + "\n")
    lineno = source.splitlines().index(mutation) + 1
    joined = " ".join(computed_baseline_complaints(source))
    assert "_sweep_1_candidates" in joined, joined
    assert f"line {lineno}" in joined, joined


def test_the_shape_checker_catches_sweep_2_re_derived_at_import() -> None:
    """The other half of condition 2. `_SWEEP_2_RESULTS = _sweep_2_candidates()`
    is what stood at `:356` before PDF-69."""
    source = _shape_fixture("_SWEEP_2_RESULTS = _sweep_2_candidates()\n")
    assert "_sweep_2_candidates" in " ".join(computed_baseline_complaints(source))


def test_the_shape_checker_catches_a_ceiling_aliased_instead_of_written_down() -> None:
    """A frozen name bound to another NAME is not a committed literal: it moves
    whenever the thing it points at moves, which is the property a ceiling must
    not have."""
    source = _shape_fixture().replace(
        "SWEEP_1_CEILING: Final[int] = 5", "SWEEP_1_CEILING: Final[int] = _MEASURED_ELSEWHERE"
    )
    joined = " ".join(computed_baseline_complaints(source))
    assert "SWEEP_1_CEILING" in joined and "ast.Name" in joined, joined


def test_the_shape_checker_catches_a_ceiling_tuple_built_by_a_comprehension() -> None:
    """The sweep-2 shape of the same evasion: a tuple of identities is a literal
    display or it is a derivation, and a comprehension is the latter however
    constant its output looks today."""
    source = _shape_fixture().replace(
        'SWEEP_2_GENUINE_CEILING: Final[tuple[str, ...]] = ("a/b.py::C",)',
        "SWEEP_2_GENUINE_CEILING: Final[tuple[str, ...]] = tuple(sorted(_live_keys()))",
    )
    joined = " ".join(computed_baseline_complaints(source))
    assert "SWEEP_2_GENUINE_CEILING" in joined and "ast.Call" in joined, joined


def test_the_shape_checker_catches_a_baseline_spelled_as_arithmetic() -> None:
    """`65 + 14` is a derivation wearing a literal's clothes, and it is exactly
    how a contributor absorbs drift without writing a number down. This is why
    the check is a structural walk and not `ast.literal_eval`, which accepts
    it."""
    source = _shape_fixture().replace(
        "SWEEP_1_CEILING: Final[int] = 5", "SWEEP_1_CEILING: Final[int] = 65 + 14"
    )
    joined = " ".join(computed_baseline_complaints(source))
    assert "SWEEP_1_CEILING" in joined and "ast.BinOp" in joined, joined


def test_the_shape_checker_catches_a_frozen_name_that_has_gone_missing() -> None:
    """Deleting a ceiling is not the same as lowering one. A frozen baseline
    that is simply absent leaves the assertion beside it comparing against
    nothing, and the module still collects green."""
    source = _shape_fixture().replace("SWEEP_1_CEILING: Final[int] = 5\n", "")
    assert "SWEEP_1_CEILING" in " ".join(computed_baseline_complaints(source))


# --------------------------------------------------------------------------- #
# PDF-69 D4 -- the provenance stamp, in the shape the envelope register ships.
# --------------------------------------------------------------------------- #


def test_the_baseline_provenance_commit_resolves_in_this_repository() -> None:
    """PDF-69 AC7, mirroring `test_envelope_contract.py:1255-1265`.

    Written UNCONDITIONALLY, which was measured rather than hoped: `ci.yml:178`
    sets `fetch-depth: 0` on the `test` job, so the object resolves in the job
    that runs this module. No shallow-clone disjunct is added, because a
    disjunct true for every input is a second unfailable arm -- PDF-69's own
    defect re-introduced beside its repair.

    A stamp naming a commit nobody can resolve is a FINDING even where the
    assertion passes, because it means the arm has never been exercised on this
    checkout.
    """
    assert len(BASELINES_MEASURED_AT) == 40 and all(
        character in "0123456789abcdef" for character in BASELINES_MEASURED_AT
    ), f"BASELINES_MEASURED_AT {BASELINES_MEASURED_AT!r} is not 40 lowercase hex characters"

    resolved = subprocess.run(
        ["git", "cat-file", "-e", BASELINES_MEASURED_AT], cwd=REPO_ROOT, capture_output=True
    )
    assert resolved.returncode == 0, (
        f"BASELINES_MEASURED_AT {BASELINES_MEASURED_AT!r} does not resolve in this "
        "repository. Every frozen ceiling in this module claims to have been measured at "
        "that commit; an unresolvable stamp is decoration with a serial number, and the "
        "ceilings beside it then assert a provenance nothing can check"
    )
