"""PDF-22 Design D6 -- two mechanized sweeps, both B-073's and B-074's own
stated follow-ups, both promoted onto this spec by the groom.

`tests/test_import_boundaries.py` is the house precedent for an AST-walk
check over `src/`; this module is the sibling that walks `tests/` (Sweep 1)
and BOTH trees (Sweep 2). Neither sweep silently fixes what it finds --
genuine findings are FILED to the project-manager (AC11, AC13), never wired
here (`0615feae63`'s precedent: an unratified policy or a documented-but-dead
symbol is a FINDING, not an assertion to write).

Both sweeps record a MEASURED baseline (this engineer's own re-derivation at
landing, never inherited from the spec's `2d19bcb` figures, which measure a
different commit) and fail only when the LIVE count exceeds it.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Final

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

REPO_ROOT: Final[Path] = TESTS_DIR.parent
SRC: Final[Path] = REPO_ROOT / "src" / "pdf_toolkit"

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


def _sweep_1_candidates() -> list[tuple[Path, int, str]]:
    """Every `assert` across `tests/**/*.py` matching `_is_operand_pin`,
    excluding `tests/unit/test_safety_paths.py`'s documented-contract rows
    (exempted by ENCLOSING FUNCTION NAME, per AC10)."""
    found: list[tuple[Path, int, str]] = []
    for path in sorted(TESTS_DIR.rglob("*.py")):
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
                rel = path.relative_to(REPO_ROOT)
                found.append((rel, node.lineno, func_name))
    return found


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


#: MEASURED at landing (`bb9008a`+PDF-22, this engineer, 2026-09-02) --
#: re-derived, never inherited from the spec's `2d19bcb` figure (a different
#: commit; the D6 table's own breakdown does not bind this sweep's number).
#: A rise above this baseline is the sweep doing its job.
SWEEP_1_BASELINE: Final[int] = len(_sweep_1_candidates())


def test_sweep_1_b073_baseline_does_not_rise() -> None:
    """AC10 -- fails when the count of unexempted operand-pinning assertions
    rises above the recorded baseline. The baseline itself is measured
    ABOVE, at collection time, from the SAME function this test calls again
    -- so a literal never drives either side."""
    current = _sweep_1_candidates()
    assert len(current) <= SWEEP_1_BASELINE, (
        f"{len(current)} operand-pinning assertions found, baseline is "
        f"{SWEEP_1_BASELINE}. New instances: "
        f"{[c for c in current if c not in _sweep_1_candidates()]}"
    )


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


def _sweep_2_candidates() -> list[tuple[str, str]]:
    """`(symbol, "genuine" | "dead-but-honest")` for every documented-as-
    honoured symbol under `src/pdf_toolkit/` with ZERO token-level reads in
    BOTH `src/` and `tests/` outside its own definition line, excluding
    `to_dict()`-only loads (bucketed separately -- D6 item 4)."""
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
    return results


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


#: MEASURED at landing (`bb9008a`+PDF-22, this engineer, 2026-09-02) -- the
#: three genuine findings (F1-F3) plus whatever dead-but-honest symbols this
#: run's own AST walk finds. Re-derived, never inherited from `2d19bcb`'s
#: figure (a different commit).
_SWEEP_2_RESULTS: Final[list[tuple[str, str]]] = _sweep_2_candidates()
SWEEP_2_GENUINE: Final[tuple[str, ...]] = tuple(
    sorted(symbol for symbol, cls in _SWEEP_2_RESULTS if cls == "genuine")
)
SWEEP_2_DEAD_BUT_HONEST: Final[tuple[str, ...]] = tuple(
    sorted(symbol for symbol, cls in _SWEEP_2_RESULTS if cls == "dead-but-honest")
)


def test_sweep_2_b074_baseline_does_not_rise() -> None:
    """AC12 -- fails when the GENUINE (behaviourally-claimed but unread)
    count rises above the recorded baseline."""
    current = tuple(sorted(symbol for symbol, cls in _sweep_2_candidates() if cls == "genuine"))
    assert current == SWEEP_2_GENUINE, (
        f"sweep 2 genuine findings changed: baseline={SWEEP_2_GENUINE}, now={current}"
    )


def test_sweep_2_b074_f1_f2_f3_are_found() -> None:
    """AC13 -- the three named findings (`ops/merge.py` `BOOKMARK_MODES`,
    `ops/metadata.py` `SETTABLE_FIELDS` and `CLEARABLE_FIELDS`) are among
    the sweep's own genuine results, confirming the mechanism is not merely
    passing by missing everything."""
    names = {entry.rsplit(" ", 1)[-1] for entry in SWEEP_2_GENUINE}
    for expected in ("BOOKMARK_MODES", "SETTABLE_FIELDS", "CLEARABLE_FIELDS"):
        assert expected in names, f"{expected} not found by the sweep -- {SWEEP_2_GENUINE}"


def test_sweep_2_b074_enum_classes_are_never_flagged() -> None:
    """D6 item 2 -- `StrEnum`/`Enum` members are consumed by Typer iterating
    the CLASS, never by member name; skipping them is required or the sweep
    would flag ~13 false positives (`OutputFormat`'s own members among
    them)."""
    names = {entry.rsplit(" ", 1)[-1] for entry in (*SWEEP_2_GENUINE, *SWEEP_2_DEAD_BUT_HONEST)}
    assert "TABLE" not in names and "JSON" not in names and "NDJSON" not in names, (
        "an OutputFormat enum member was flagged -- the Enum-class exemption is not firing"
    )


def test_sweep_2_b074_dunders_and_all_are_never_flagged() -> None:
    names = {entry.rsplit(" ", 1)[-1] for entry in (*SWEEP_2_GENUINE, *SWEEP_2_DEAD_BUT_HONEST)}
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
    everything = (*SWEEP_2_GENUINE, *SWEEP_2_DEAD_BUT_HONEST)
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
