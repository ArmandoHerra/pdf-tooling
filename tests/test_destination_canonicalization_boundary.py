"""PDF-80 — the destination-canonicalization boundary, as a statically decidable rule.

**The defect this module exists to make impossible.** ``safety/paths.py``'s
``canonical()`` is the product's one expansion vocabulary, and it is correct:
the no-clobber gate, the planned-output collision key, containment, writability
and ``os.replace`` itself all answer for its result. What was broken is that a
destination path reached the filesystem **around** it in twenty-three places —
two in ``safety/atomic.py`` and **twenty-one in ``ops/``**, where every
producing verb ``stat()``-ed the spelling the user typed instead of the
destination the ``AtomicWriter`` standing one line above it had already
resolved. At a ``~`` spelling those are two different paths, so sixteen verbs
answered a *successful* write with a raw ``FileNotFoundError`` traceback and
zero bytes of stdout, and three more answered with a published
``bytes_after: null`` for a file that exists and is non-empty.

**The rule, and it is a rule rather than a census.**

    Inside ``src/pdf_tooling/ops/``, a name passed as the first positional
    argument to ``AtomicWriter(...)`` must not be the receiver of a filesystem
    call anywhere in the same function.

It fired on exactly the twenty-one sites at ``6488f18`` — which is how its
first half was proven against the real tree rather than only against a plant —
and on zero after the fix. A twenty-second site is a matter of time unless
something reds, and prose in a docstring is not something that reds.

**Why this is NOT a fifteenth ``D7_GROUP_PLANTS`` row** (``PDF-80`` D8).
That register in ``tests/test_import_boundaries.py`` is a claim about ``§D7``'s
taxonomy of **mutating** call groups, and
``test_every_d7_call_group_has_a_planted_violation`` asserts
``len(D7_GROUP_PLANTS) == 14``. A canonicalization rule is not a mutating call
group: every one of the twenty-one sites was a *read*. Adding a row would mean
editing a frozen count to reach green — forbidden in writing — and would
quietly widen a register that claims to describe ``§D7`` alone. So this is a
separately-named instrument in its own module, carrying its own planted
negatives in ``test_import_boundaries.py``'s own ``PLANTED`` idiom (copy a
tree, plant a violation, confirm the walk turns red) rather than borrowing that
module's register.

**The control has two halves and both are driven below.** Half 1: a planted
``target.stat()`` beside an ``AtomicWriter(target, …)`` reds, naming module and
line. Half 2: ``item.source.stat()`` in the same function does **not** red —
an operand readback is legitimate and present at many of these very sites.
Without half 2 the rule degenerates into *"no ``.stat()`` in ``ops/``"*, which
is not the rule, would be red on arrival, and would be "fixed" by an allowlist
that hollows it out.
"""

from __future__ import annotations

import ast
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
SRC: Final[Path] = REPO_ROOT / "src" / "pdf_tooling"
OPS: Final[Path] = SRC / "ops"

#: The writer whose first positional argument IS the destination. Named as a
#: string because this is a source-level walk: the rule has to hold for a
#: module this test never imports.
WRITER: Final[str] = "AtomicWriter"

#: Attribute calls that ask the FILESYSTEM about their receiver. Deliberately
#: wider than the twenty-one shapes actually found, because the rule is about
#: the question being asked and not about the four spellings that happened to
#: ask it: ``.stat()``, ``.exists()``, ``.is_file()`` and ``.is_dir()`` were the
#: census's hits, and a twenty-second site is as likely to arrive as
#: ``.read_bytes()`` or ``.lstat()``.
FILESYSTEM_CALLS: Final[frozenset[str]] = frozenset(
    {
        "exists",
        "glob",
        "is_dir",
        "is_file",
        "is_symlink",
        "iterdir",
        "lstat",
        "mkdir",
        "open",
        "read_bytes",
        "read_text",
        "rename",
        "replace",
        "resolve",
        "rglob",
        "samefile",
        "stat",
        "touch",
        "unlink",
        "write_bytes",
        "write_text",
    }
)


@dataclass(frozen=True, slots=True)
class Readback:
    """One destination readback: where it is, and what it asked about."""

    module: str
    lineno: int
    function: str
    receiver: str
    call: str

    def __str__(self) -> str:
        return f"{self.module}:{self.lineno} {self.function}(): {self.receiver}.{self.call}()"


def _dotted(node: ast.expr) -> str | None:
    """*node* as a dotted name, or ``None`` if it is not one.

    ``target`` and ``item.target`` are both destinations a verb hands the
    writer; ``Path(grid.path)`` is not a NAME and is deliberately not one
    either -- a call result cannot be compared for identity across two
    statements, so a site that constructs its destination inline is out of this
    rule's reach and is left to the census. Depth is capped at one attribute
    for the same reason ``path_prefixes`` caps its walk: past that the
    comparison stops discriminating.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


def _own_body(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """Every node inside *function* that a NESTED function does not own.

    Scoping matters in both directions here. Several verbs bind their writer in
    an inner helper (``pages.py``'s ``_write_one``, ``optimize.py``'s
    ``_compress_item``) and read back in that same helper, so a module-wide
    walk would be right by luck; but a module-wide walk would ALSO pair an
    outer function's destination name with an unrelated inner function's
    identically-named local, which is a false positive that gets a rule
    deleted rather than fixed.
    """
    owned: list[ast.AST] = []
    stack: list[ast.AST] = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        owned.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return owned


def destination_readbacks(source: str, module: str) -> list[Readback]:
    """Every violation of the rule in *source*, as ``module:line``-bearing rows."""
    found: list[Readback] = []
    tree = ast.parse(source)
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = _own_body(function)
        destinations: set[str] = set()
        for node in body:
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == WRITER
                and node.args
            ):
                name = _dotted(node.args[0])
                if name is not None:
                    destinations.add(name)
        if not destinations:
            continue
        for node in body:
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in FILESYSTEM_CALLS:
                continue
            receiver = _dotted(node.func.value)
            if receiver in destinations:
                found.append(
                    Readback(
                        module=module,
                        lineno=node.lineno,
                        function=function.name,
                        receiver=str(receiver),
                        call=node.func.attr,
                    )
                )
    return sorted(found, key=lambda row: (row.module, row.lineno))


def scan_ops(root: Path) -> list[Readback]:
    """The rule, applied to every module under an ``ops/`` tree."""
    found: list[Readback] = []
    for path in sorted(root.rglob("*.py")):
        found.extend(
            destination_readbacks(path.read_text(encoding="utf-8"), path.name),
        )
    return found


# --------------------------------------------------------------------------- #
# The rule itself.
# --------------------------------------------------------------------------- #


def test_no_ops_module_reads_a_destination_back_off_the_spelling() -> None:
    """``ops/`` performs ZERO filesystem calls on a destination.

    Consume :attr:`~pdf_tooling.safety.atomic.AtomicWriter.bytes_written`
    instead: it is measured in ``_commit`` off the canonical path ``os.replace``
    actually wrote to, so a verb cannot disagree with the writer standing one
    line above it. ``canonical(target).stat()`` is NOT the repair -- it would
    create a new expansion site per call, and this defect is made of
    expansions that were computed and then discarded.
    """
    offenders = scan_ops(OPS)
    assert offenders == [], (
        "ops/ module(s) ask the filesystem about a destination the adjacent "
        "AtomicWriter already resolved:\n  "
        + "\n  ".join(str(row) for row in offenders)
        + "\nRead the size back through `writer.bytes_written`. At a `~` "
        "spelling the name handed to the writer and the path the bytes landed "
        "at are DIFFERENT paths, which is how a successful write reached the "
        "user as a FileNotFoundError traceback on sixteen verbs (PDF-80)."
    )


def test_the_rule_is_not_vacuous_on_the_shipped_tree() -> None:
    """The guard for the guard: a scan that sees no writers proves nothing.

    Without this, deleting ``AtomicWriter`` from the detector -- or renaming the
    class under ``src/`` -- leaves the assertion above green while measuring an
    empty set, which is the shape every count pin in this suite exists to
    refuse.
    """
    writers = [
        path.name
        for path in sorted(OPS.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == WRITER
    ]
    assert len(writers) >= 15, (
        f"the boundary scan found only {len(writers)} {WRITER} construction(s) under ops/ "
        f"({sorted(set(writers))}) -- the rule above is then green over a tree it has "
        "stopped seeing. Twenty-one readbacks across twelve modules were measured at "
        "PDF-80's entry gate"
    )
    assert len(set(writers)) >= 10, sorted(set(writers))


# --------------------------------------------------------------------------- #
# The control, in `test_import_boundaries.py`'s own PLANTED idiom: copy the
# tree, plant the violation, confirm the walk turns red. Both halves, because a
# one-sided control is what this cycle keeps catching.
# --------------------------------------------------------------------------- #

#: Half 1 -- each of these MUST be reported, naming module and line.
PLANTED_VIOLATIONS: Final[tuple[tuple[str, str], ...]] = (
    (
        "bare-name-stat",
        "from pdf_tooling.safety.atomic import AtomicWriter\n\n\n"
        "def write(target, policy, payload):\n"
        "    with AtomicWriter(target, policy=policy, kind='pdf') as writer:\n"
        "        writer.stream.write(payload)\n"
        "    return target.stat().st_size\n",
    ),
    (
        "attribute-name-stat",
        "from pdf_tooling.safety.atomic import AtomicWriter\n\n\n"
        "def write(item, policy, payload):\n"
        "    with AtomicWriter(item.target, policy=policy, kind='pdf') as writer:\n"
        "        writer.stream.write(payload)\n"
        "    return item.target.stat().st_size\n",
    ),
    (
        "guarded-exists-then-stat",
        "from pdf_tooling.safety.atomic import AtomicWriter\n\n\n"
        "def write(output, policy, payload):\n"
        "    with AtomicWriter(output, policy=policy, kind='pdf') as atomic:\n"
        "        atomic.stream.write(payload)\n"
        "    return output.stat().st_size if output.exists() else None\n",
    ),
    (
        "readback-in-a-nested-helper",
        "from pdf_tooling.safety.atomic import AtomicWriter\n\n\n"
        "def run(items, policy, payload):\n"
        "    def one(item):\n"
        "        with AtomicWriter(item.target, policy=policy, kind='pdf') as atomic:\n"
        "            atomic.stream.write(payload)\n"
        "        return item.target.stat().st_size\n"
        "    return [one(item) for item in items]\n",
    ),
)

#: Half 2 -- each of these must stay QUIET. Every one is a shape that really
#: appears beside a writer under `ops/` today.
PLANTED_INNOCENTS: Final[tuple[tuple[str, str], ...]] = (
    (
        "operand-readback-in-the-same-function",
        "from pdf_tooling.safety.atomic import AtomicWriter\n\n\n"
        "def write(item, policy, payload):\n"
        "    before = item.source.stat().st_size\n"
        "    with AtomicWriter(item.target, policy=policy, kind='pdf') as writer:\n"
        "        writer.stream.write(payload)\n"
        "    return before, writer.bytes_written\n",
    ),
    (
        "the-repaired-shape",
        "from pdf_tooling.safety.atomic import AtomicWriter\n\n\n"
        "def write(target, policy, payload):\n"
        "    with AtomicWriter(target, policy=policy, kind='pdf') as writer:\n"
        "        writer.stream.write(payload)\n"
        "    return writer.bytes_written\n",
    ),
    (
        "same-name-in-an-unrelated-sibling-function",
        "from pdf_tooling.safety.atomic import AtomicWriter\n\n\n"
        "def write(target, policy, payload):\n"
        "    with AtomicWriter(target, policy=policy, kind='pdf') as writer:\n"
        "        writer.stream.write(payload)\n"
        "    return writer.bytes_written\n\n\n"
        "def probe(target):\n"
        "    return target.stat().st_size\n",
    ),
    (
        "a-source-read-with-no-writer-in-the-function",
        "def probe(target):\n    return target.stat().st_size\n",
    ),
)


@pytest.mark.parametrize(
    ("label", "source"),
    PLANTED_VIOLATIONS,
    ids=[row[0] for row in PLANTED_VIOLATIONS],
)
def test_a_planted_destination_readback_is_reported(
    label: str, source: str, tmp_path: Path
) -> None:
    """Half 1, driven against a COPY of the shipped tree rather than a snippet.

    Copying ``ops/`` first is what makes this the same proof
    ``test_a_planted_violation_fails_the_walk`` gives: the scan runs over a
    real tree with a real violation in it, so a detector that only ever looks
    at the one file it was handed cannot pass this.
    """
    scratch = tmp_path / "ops"
    shutil.copytree(OPS, scratch)
    planted = scratch / "sneaky.py"
    planted.write_text(source, encoding="utf-8")

    offenders = scan_ops(scratch)
    assert offenders != [], f"the walk did not notice the planted readback: {label}"
    reported = [row for row in offenders if row.module == "sneaky.py"]
    assert reported, f"{label}: the walk reported {offenders}, none of them the plant"
    assert all(row.lineno > 0 for row in reported), reported
    # The failure has to NAME the site. A boolean would send a reader grepping.
    rendered = str(reported[0])
    assert "sneaky.py:" in rendered and f".{reported[0].call}()" in rendered, rendered


@pytest.mark.parametrize(
    ("label", "source"),
    PLANTED_INNOCENTS,
    ids=[row[0] for row in PLANTED_INNOCENTS],
)
def test_the_rule_does_not_fire_on_a_legitimate_readback(
    label: str, source: str, tmp_path: Path
) -> None:
    """Half 2, and it is the half that keeps the rule a rule.

    ``item.source.stat()`` beside a writer is an OPERAND readback and is
    correct; so is a same-named local in a sibling function that binds no
    writer. A detector that flagged either would be red on arrival over the
    shipped tree and would be "fixed" with an allowlist, at which point it
    stops being an absolute rule -- which is the entire reason ``X-737``
    mandated ``bytes_written`` over the ``writer.destination`` floor.
    """
    scratch = tmp_path / "ops"
    scratch.mkdir()
    (scratch / "innocent.py").write_text(source, encoding="utf-8")
    assert scan_ops(scratch) == [], label
