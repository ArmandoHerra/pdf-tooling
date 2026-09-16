"""Import boundaries — the structural rules, enforced by walking the AST of ``src/``.

This file is **shared and append-only**. Each spec that owns a boundary adds its
own section below and reuses the machinery at the top; nobody rewrites an
existing section. PDF-04 created the file and owns Section 1. Section 2 (engine
imports and the subprocess chokepoint) belongs to PDF-05, and Section 3 (no
``typer``/``click`` below L1, ``PLAN.md`` §10 / D-03) belongs to PDF-06 — that
one is roughly ten lines against the machinery already here.

Section 1 — the write chokepoint
================================
``AtomicWriter`` is the single place this product writes. That sentence is only
true if something enforces it, because twenty verbs are written after the spec
that built it and none of their authors will re-read ``PLAN.md`` §5.2. So the
rule is mechanised: every file under ``src/`` is parsed, and any filesystem
mutation outside ``pdf_tooling/safety/atomic.py`` fails the build.

**Two tiers, two allowlists.**

* Tier 1 — ``src/`` outside ``pdf_tooling/safety/``: zero occurrences.
* Tier 2 — inside ``pdf_tooling/safety/``: occurrences are confined to
  ``atomic.py``. The chokepoint is one **file**, not one package.

Both allowlists are empty at landing and a test asserts that they are. An
exception is a ``("module.path", "enclosing_function", "call_name")`` triple with
a mandatory ``# reason:`` comment, and it lives **here, in the test module**,
never as an inline pragma in the source. An inline pragma arrives in the same
diff as the violation it excuses and reads as ordinary code; an allowlist entry
is a diff to the file whose entire purpose is the guarantee, and it shows up in
review as exactly that. Entries are also checked for staleness — an entry that no
longer resolves to a real call site fails the test, because allowlist rot is how
a guard like this dies quietly.

The fourteen call groups
------------------------
Rows 1–9 are the list ``PLAN.md`` §5.2/§10 mandates. Rows 10–14 are named
extensions: the plan's four-call list (``open(...,"w")``, ``write_bytes``,
``shutil.copy``, ``os.replace``) does not close the hole, because a verb that
creates its own ``tempfile`` or its own ``--out-dir`` has bypassed the chokepoint
and broken ``--dry-run`` purity while passing a four-name walk.

 1. ``open(...)`` with a mutating mode (``w``, ``a``, ``x``, ``+``) — or **any
    non-literal mode**, because a computed mode is unauditable and an
    unauditable call is treated as a failing one.
 2. ``.open(...)`` (``Path.open``) — same mode rule.
 3. ``write_bytes``          4. ``write_text``
 5. ``shutil.copy*``         6. ``shutil.move``
 7. ``os.replace``           8. ``os.rename``
 9. ``Path.unlink`` / ``os.remove`` / ``os.unlink``
10. the ``tempfile`` create family (extension)
11. ``os.mkdir`` / ``os.makedirs`` / ``Path.mkdir`` (extension — ``PLAN.md`` §4.2
    makes ``--out-dir`` creation conditional on ``--dry-run``, so directory
    creation is a gated write like any other)
12. ``os.rmdir`` / ``shutil.rmtree`` (extension — symmetry with 9 and 11)
13. ``os.truncate`` / ``Path.touch`` / ``os.utime`` / ``os.chmod`` / ``os.chown``
    (extension — metadata mutation is still mutation, and the purity snapshot
    compares ``st_mode`` and ``st_mtime_ns``)
14. ``os.open`` / ``os.symlink`` / ``os.link`` (extension — ``os.open``'s flags
    are not reliably statically analysable, and no module outside ``safety/``
    has a legitimate use for any of the three)

Honest limitations, stated rather than discovered later
-------------------------------------------------------
* **The walk sees stdlib call names.** It does not see ``writer.write(path)``,
  ``pdf.save(path)``, ``canvas.Canvas(path)`` or ``soffice --outdir <dir>``.
  Engines write too. The compensating structural rule is **destination
  ownership**: *no module outside* ``safety/`` *may choose a destination path*.
  Adapters receive the path they write to; ``AtomicWriter`` is the only thing
  that decides what that path is. The empirical backstop is the ``--dry-run``
  purity snapshot (``tests/fs_snapshot.py``), which catches an engine write no
  AST walk can see.
* **Three names are checked only in qualified form**, because their bare method
  spellings collide with methods that have nothing to do with the filesystem:
  ``remove`` (``list.remove``), ``move`` and ``copy`` (``dict.copy``). ``os.remove``
  and ``shutil.move`` *are* caught, as is ``from os import remove`` followed by a
  bare ``remove(...)``. ``replace`` is caught by arity instead of by name:
  ``Path.replace`` takes exactly one argument and ``str.replace`` takes at least
  two, so a one-argument ``.replace(x)`` is a violation and ``s.replace(a, b)`` is
  not. Widening these would produce false positives, and a guard that cries wolf
  gets an allowlist entry, which is worse than a stated gap.
* ``tests/`` is exempt from the walk **on purpose**. The tests must be able to
  construct violations in order to prove the guard fires, which is what
  ``test_a_planted_violation_fails_the_walk`` does.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final, NamedTuple

import pytest

# --------------------------------------------------------------------------- #
# Shared machinery. PDF-05 and PDF-06 build their sections on this and add to it
# rather than starting a second walk.
# --------------------------------------------------------------------------- #

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
SRC: Final = REPO_ROOT / "src"

#: Non-Python files permitted under src/. Anything else fails the totality
#: check, which is what keeps "walks every file under src/" literally true.
NON_PYTHON_ALLOWED: Final = ("py.typed",)


def iter_python_files(root: Path) -> list[Path]:
    """Every Python source file under *root*, sorted for a stable report."""
    return sorted(
        p
        for p in root.rglob("*")
        if p.suffix in {".py", ".pyi"} and p.is_file() and "__pycache__" not in p.parts
    )


def module_name(path: Path, root: Path) -> str:
    """``src/pdf_tooling/safety/atomic.py`` -> ``pdf_tooling.safety.atomic``."""
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def dotted(func: ast.expr) -> str:
    """Render a call target as a dotted string: ``os.replace``, ``p.open``, ``open``."""
    parts: list[str] = []
    node: ast.expr | None = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def from_import_bindings(tree: ast.Module) -> dict[str, str]:
    """Local names bound by ``from os import replace`` and friends.

    Maps the local name to the qualified name it refers to, so a bare
    ``replace(a, b)`` can be told apart from ``some_object.replace(a, b)``.
    """
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local = alias.asname or alias.name
                bindings[local] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bindings[alias.asname] = alias.name
    return bindings


# --------------------------------------------------------------------------- #
# Section 1 — the write chokepoint (PDF-04)
# --------------------------------------------------------------------------- #

#: The chokepoint is one FILE, not one package.
CHOKEPOINT: Final = "pdf_tooling.safety.atomic"

#: Tier 2's scope.
SAFETY_PACKAGE: Final = "pdf_tooling.safety"

#: Rows 5–14 in their qualified spelling, plus the from-import forms of the
#: same names, which ``from_import_bindings`` resolves back to these.
QUALIFIED_FORBIDDEN: Final = frozenset(
    {
        "shutil.copy",
        "shutil.copy2",
        "shutil.copyfile",
        "shutil.copytree",
        "shutil.move",
        "os.replace",
        "os.rename",
        "os.remove",
        "os.unlink",
        "tempfile.NamedTemporaryFile",
        "tempfile.mkstemp",
        "tempfile.mkdtemp",
        "tempfile.TemporaryDirectory",
        "tempfile.TemporaryFile",
        "os.mkdir",
        "os.makedirs",
        "os.rmdir",
        "shutil.rmtree",
        "os.truncate",
        "os.utime",
        "os.chmod",
        "os.chown",
        "os.open",
        "os.symlink",
        "os.link",
    }
)

#: Method names unambiguous enough to flag on any receiver. ``remove``, ``move``
#: and ``copy`` are deliberately absent — see the module docstring.
METHOD_FORBIDDEN: Final = frozenset(
    {
        "write_bytes",
        "write_text",
        "copy2",
        "copyfile",
        "copytree",
        "rmtree",
        "rename",
        "unlink",
        "mkdir",
        "makedirs",
        "rmdir",
        "touch",
        "chmod",
        "lchmod",
        "utime",
        "truncate",
        "symlink_to",
        "hardlink_to",
        "link_to",
        "mkstemp",
        "mkdtemp",
        "NamedTemporaryFile",
        "TemporaryFile",
        "TemporaryDirectory",
    }
)

#: Characters that turn ``open`` into a write.
MUTATING_MODES: Final = frozenset("wax+")

# --------------------------------------------------------------------------- #
# The allowlists. BOTH EMPTY AT LANDING, and a test asserts it.
#
# Shape: ("module.path", "enclosing_function", "call_name"), each entry carrying
# a mandatory inline `# reason:` comment. An entry that no longer resolves to a
# real call site fails the test — allowlist rot is how a guard dies quietly.
# --------------------------------------------------------------------------- #

# The declaration and the assignment are split, and the empty value is spelled
# `frozenset({})`, so that an auditor can confirm emptiness by READING this file
# rather than by running the suite. PDF-04's Validation block greps these two
# names with `<NAME>\s*=\s*frozenset\(\s*\{(.*?)\}\s*\)`, which an annotated
# assignment (`NAME: Final[...] = ...`) does not match and which Python's missing
# empty-set literal makes awkward to satisfy any other way. `{}` is an empty dict
# and iterating it yields nothing, so both names are the empty frozenset —
# `test_both_allowlists_are_empty` asserts that outright rather than trusting the
# spelling.

#: Tier 1 escape hatch — a write outside `pdf_tooling.safety`.
ALLOWED_WRITE_SITES: Final[frozenset[tuple[str, str, str]]]
ALLOWED_WRITE_SITES = frozenset({})

#: Tier 2 escape hatch — a write inside `pdf_tooling.safety` but outside
#: `atomic.py`.
SAFETY_INNER_ALLOW: Final[frozenset[tuple[str, str, str]]]
SAFETY_INNER_ALLOW = frozenset({})


class WriteCall(NamedTuple):
    """One filesystem-mutating call, located precisely enough to allowlist."""

    module: str
    function: str
    call: str
    line: int
    reason: str

    @property
    def triple(self) -> tuple[str, str, str]:
        return (self.module, self.function, self.call)

    def __str__(self) -> str:
        return f"{self.module}:{self.line}: {self.function}() calls {self.call} ({self.reason})"


class _WriteCallVisitor(ast.NodeVisitor):
    """Collects every filesystem-mutating call, with its enclosing function."""

    def __init__(self, module: str, bindings: dict[str, str]) -> None:
        self.module = module
        self.bindings = bindings
        self.scope: list[str] = ["<module>"]
        self.found: list[WriteCall] = []

    # -- scope tracking -- #

    def _scoped(self, node: ast.AST, name: str) -> None:
        self.scope.append(name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._scoped(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._scoped(node, node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self._scoped(node, node.name)

    # -- the check -- #

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        target = dotted(node.func)
        finding = self._classify(node, target)
        if finding is not None:
            self.found.append(WriteCall(self.module, self.scope[-1], target, node.lineno, finding))
        self.generic_visit(node)

    def _classify(self, node: ast.Call, target: str) -> str | None:
        tail = target.rsplit(".", 1)[-1] if target else ""

        # Rows 1 and 2: open() / Path.open(), by mode.
        if tail == "open" and target != "os.open":
            return self._classify_open(node)

        # Rows 5-14 in qualified form, and the same names reached through a
        # `from x import y` binding.
        if target in QUALIFIED_FORBIDDEN:
            return "qualified filesystem mutation"
        if isinstance(node.func, ast.Name) and self.bindings.get(target) in QUALIFIED_FORBIDDEN:
            return "filesystem mutation via a from-import"
        if isinstance(node.func, ast.Attribute):
            head = target.rsplit(".", 1)[0]
            resolved = self.bindings.get(head.split(".", 1)[0])
            if resolved and f"{resolved}.{tail}" in QUALIFIED_FORBIDDEN:
                return "filesystem mutation via an aliased import"

        # Rows 3, 4 and the unambiguous method spellings of 5 and 9-14.
        if tail in METHOD_FORBIDDEN:
            return "filesystem-mutating method"

        # Row 7/8 by arity: Path.replace takes one argument, str.replace two.
        if tail == "replace" and len(node.args) == 1 and not node.keywords:
            return "one-argument replace (Path.replace)"

        return None

    def _classify_open(self, node: ast.Call) -> str | None:
        mode: ast.expr | None = node.args[1] if len(node.args) > 1 else None
        if mode is None:
            for keyword in node.keywords:
                if keyword.arg == "mode":
                    mode = keyword.value
        if mode is None:
            return None  # defaults to "r"
        if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
            if MUTATING_MODES & set(mode.value):
                return f"open() with mutating mode {mode.value!r}"
            return None
        return "open() with a non-literal mode, which cannot be audited"


def scan_write_calls(source: str, module: str) -> list[WriteCall]:
    """Every filesystem-mutating call in one module's source."""
    tree = ast.parse(source, filename=module)
    visitor = _WriteCallVisitor(module, from_import_bindings(tree))
    visitor.visit(tree)
    return visitor.found


def scan_tree(root: Path) -> list[WriteCall]:
    """Walk every Python file under *root* and collect the mutating calls."""
    found: list[WriteCall] = []
    for path in iter_python_files(root):
        found.extend(scan_write_calls(path.read_text(), module_name(path, root)))
    return found


def tier_violations(
    findings: list[WriteCall],
    *,
    outer_allow: frozenset[tuple[str, str, str]] = ALLOWED_WRITE_SITES,
    inner_allow: frozenset[tuple[str, str, str]] = SAFETY_INNER_ALLOW,
) -> tuple[list[WriteCall], list[WriteCall]]:
    """Split *findings* into (tier 1 violations, tier 2 violations)."""
    outer: list[WriteCall] = []
    inner: list[WriteCall] = []
    for call in findings:
        if call.module == CHOKEPOINT:
            continue
        in_safety = call.module == SAFETY_PACKAGE or call.module.startswith(SAFETY_PACKAGE + ".")
        if in_safety:
            if call.triple not in inner_allow:
                inner.append(call)
        elif call.triple not in outer_allow:
            outer.append(call)
    return outer, inner


def stale_entries(
    allowlist: frozenset[tuple[str, str, str]],
    findings: list[WriteCall],
) -> list[tuple[str, str, str]]:
    """Allowlist entries that no longer resolve to a real call site."""
    live = {call.triple for call in findings}
    return sorted(entry for entry in allowlist if entry not in live)


# --------------------------------------------------------------------------- #
# The gate, over the real tree.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def findings() -> list[WriteCall]:
    return scan_tree(SRC)


def test_the_walk_sees_every_python_file_under_src() -> None:
    """A walk that silently covered nothing would pass every assertion below."""
    files = iter_python_files(SRC)
    assert files, "no Python files found under src/ — the walk is measuring nothing"
    unexpected = sorted(
        str(p.relative_to(SRC))
        for p in SRC.rglob("*")
        if p.is_file()
        and p.suffix not in {".py", ".pyi"}
        and p.name not in NON_PYTHON_ALLOWED
        and "__pycache__" not in p.parts
    )
    assert unexpected == [], f"unscanned non-Python files under src/: {unexpected}"


def test_no_write_call_outside_the_safety_package(findings: list[WriteCall]) -> None:
    outer, _ = tier_violations(findings)
    listed = "\n".join(f"  - {call}" for call in outer)
    assert outer == [], (
        "filesystem mutation outside pdf_tooling.safety — every write goes through "
        f"AtomicWriter:\n{listed}"
    )


def test_write_calls_inside_safety_are_confined_to_the_chokepoint(
    findings: list[WriteCall],
) -> None:
    _, inner = tier_violations(findings)
    listed = "\n".join(f"  - {call}" for call in inner)
    assert inner == [], f"the chokepoint is one FILE ({CHOKEPOINT}), not one package:\n{listed}"


def test_the_chokepoint_actually_contains_the_writes(findings: list[WriteCall]) -> None:
    """Non-vacuity. If nothing writes anywhere, the two tiers prove nothing."""
    at_chokepoint = [call for call in findings if call.module == CHOKEPOINT]
    assert at_chokepoint, (
        f"{CHOKEPOINT} contains no filesystem mutation at all — either the walk is "
        "broken or the writer stopped writing"
    )


@pytest.mark.parametrize(
    ("name", "allowlist"),
    [("ALLOWED_WRITE_SITES", ALLOWED_WRITE_SITES), ("SAFETY_INNER_ALLOW", SAFETY_INNER_ALLOW)],
)
def test_both_allowlists_are_empty(name: str, allowlist: frozenset[tuple[str, str, str]]) -> None:
    """An entry here is a hole in the product's central safety guarantee."""
    assert allowlist == frozenset(), (
        f"{name} has entries: {sorted(allowlist)}. Each needs a '# reason:' comment "
        "and should be read as a deliberate exception, not a formality"
    )


@pytest.mark.parametrize(
    ("name", "allowlist"),
    [("ALLOWED_WRITE_SITES", ALLOWED_WRITE_SITES), ("SAFETY_INNER_ALLOW", SAFETY_INNER_ALLOW)],
)
def test_no_allowlist_entry_is_stale(
    name: str,
    allowlist: frozenset[tuple[str, str, str]],
    findings: list[WriteCall],
) -> None:
    stale = stale_entries(allowlist, findings)
    assert stale == [], f"{name} entries no longer resolve to a call site: {stale}"


# --------------------------------------------------------------------------- #
# Proof that the guard fires. Without these, the assertions above are a claim.
# --------------------------------------------------------------------------- #

PLANTED: Final = (
    (
        "plant-write-bytes-in-ops",
        "pdf_tooling/ops/sneaky.py",
        "from pathlib import Path\n\n\ndef save(p: Path) -> None:\n    p.write_bytes(b'x')\n",
    ),
    (
        "plant-mkstemp-in-ops",
        "pdf_tooling/ops/sneaky.py",
        "import tempfile\n\n\ndef scratch() -> None:\n    tempfile.mkstemp()\n",
    ),
    (
        "plant-mkdir-in-cli",
        "pdf_tooling/cli/sneaky.py",
        "from pathlib import Path\n\n\ndef prepare(p: Path) -> None:\n    p.mkdir(parents=True)\n",
    ),
    (
        "plant-open-write-in-output",
        "pdf_tooling/output/sneaky.py",
        "def dump(p: str) -> None:\n    with open(p, 'w') as fh:\n        fh.write('x')\n",
    ),
    (
        "plant-write-in-safety-but-not-atomic",
        "pdf_tooling/safety/sneaky.py",
        "from pathlib import Path\n\n\ndef save(p: Path) -> None:\n    p.write_text('x')\n",
    ),
    (
        "plant-path-open-write-in-ops",
        "pdf_tooling/ops/sneaky.py",
        "from pathlib import Path\n\n\ndef dump(p: Path) -> None:\n    p.open(mode='w').close()\n",
    ),
    (
        "plant-shutil-copy-in-ops",
        "pdf_tooling/ops/sneaky.py",
        "import shutil\nfrom pathlib import Path\n\n\ndef stash(a: Path, b: Path) -> None:\n"
        "    shutil.copy(a, b)\n",
    ),
    (
        "plant-shutil-move-in-ops",
        "pdf_tooling/ops/sneaky.py",
        "import shutil\nfrom pathlib import Path\n\n\ndef relocate(a: Path, b: Path) -> None:\n"
        "    shutil.move(a, b)\n",
    ),
    (
        "plant-os-replace-in-cli",
        "pdf_tooling/cli/sneaky.py",
        "import os\nfrom pathlib import Path\n\n\ndef commit(a: Path, b: Path) -> None:\n"
        "    os.replace(a, b)\n",
    ),
    (
        "plant-os-rename-via-from-import-in-adapters",
        "pdf_tooling/adapters/sneaky.py",
        "from os import rename\nfrom pathlib import Path\n\n\n"
        "def shuffle(a: Path, b: Path) -> None:\n    rename(a, b)\n",
    ),
    (
        "plant-unlink-in-ops",
        "pdf_tooling/ops/sneaky.py",
        "from pathlib import Path\n\n\ndef discard(p: Path) -> None:\n    p.unlink()\n",
    ),
    (
        "plant-rmtree-in-ports",
        "pdf_tooling/ports/sneaky.py",
        "import shutil\nfrom pathlib import Path\n\n\ndef purge(p: Path) -> None:\n"
        "    shutil.rmtree(p)\n",
    ),
    (
        "plant-chmod-in-output",
        "pdf_tooling/output/sneaky.py",
        "import os\n\n\ndef relax(p: str) -> None:\n    os.chmod(p, 0o644)\n",
    ),
    (
        "plant-os-symlink-in-ops",
        "pdf_tooling/ops/sneaky.py",
        "import os\n\n\ndef alias(a: str, b: str) -> None:\n    os.symlink(a, b)\n",
    ),
)


@pytest.mark.parametrize(
    ("label", "relative", "source"),
    PLANTED,
    ids=[row[0] for row in PLANTED],
)
def test_a_planted_violation_fails_the_walk(
    label: str,
    relative: str,
    source: str,
    tmp_path: Path,
) -> None:
    """Copy src/, plant a violation, and confirm the walk turns red."""
    scratch = tmp_path / "src"
    shutil.copytree(SRC, scratch)
    planted = scratch / relative
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(source)

    outer, inner = tier_violations(scan_tree(scratch))
    assert outer or inner, f"the walk did not notice the planted violation: {label}"


def test_a_stale_allowlist_entry_fails(findings: list[WriteCall]) -> None:
    """Allowlist rot must be loud. An entry outliving its call site is a red."""
    fabricated = frozenset({("pdf_tooling.ops.gone", "vanished", "os.replace")})
    assert stale_entries(fabricated, findings) == [
        ("pdf_tooling.ops.gone", "vanished", "os.replace")
    ]


NON_LITERAL_MODE = "def dump(p: str, mode: str) -> None:\n    open(p, mode).close()\n"


def test_a_non_literal_mode_is_a_violation() -> None:
    found = scan_write_calls(NON_LITERAL_MODE, "pdf_tooling.ops.computed")
    assert [call.call for call in found] == ["open"]
    assert "non-literal" in found[0].reason


BENIGN = """
import shutil
from pathlib import Path


def read_only(p: Path, s: str, items: list[str], d: dict[str, str]) -> object:
    with open(p, "rb") as fh:
        fh.read()
    with p.open() as fh2:
        fh2.read()
    s.replace("a", "b")
    items.remove("a")
    d.copy()
    shutil.which("ls")
    p.stat()
    p.exists()
    return s.replace("a", "b", 1)
"""


def test_benign_calls_are_never_flagged() -> None:
    """The negative self-test. A guard with false positives gets allowlisted away."""
    found = scan_write_calls(BENIGN, "pdf_tooling.ops.benign")
    assert found == [], f"false positives: {[str(call) for call in found]}"


# --------------------------------------------------------------------------- #
# PDF-19 — Section 1 re-derivation (append only; nothing above is rewritten).
#
# `PDF-04` shipped five planted violations covering five of the fourteen §D7
# call groups, and the other nine had never been observed to red. `PDF-19`'s
# audit added one plant per uncovered group (above, inside `PLANTED`) and then
# mechanised the coverage claim itself, because "all fourteen groups are
# planted" is exactly the kind of sentence that is true on the day it is
# written and quietly false two specs later.
#
# The audit also found a real hole while doing it, and it is filed rather than
# patched here: `_classify_open` reads the mode from `node.args[1]`, which is
# the BUILTIN `open`'s positional slot. On a METHOD call the receiver is
# `node.func.value`, so `p.open("w")`'s mode sits at `args[0]` and the check
# never sees it. The keyword spelling `p.open(mode="w")` is caught; the
# idiomatic positional one is not. §D7 row 2 is *mandated*, not an extension,
# so this is a gap in the product's central structural guarantee rather than a
# missing nicety. `src/` contains no such call today (measured 2026-09-02:
# `grep -rnE '\.open\(\s*[\x27"][^\x27"]*[wax+]' src/` returns nothing), so the
# GUARANTEE holds and the GUARD is what is blind.
# --------------------------------------------------------------------------- #

#: The fourteen §D7 call groups, mapped to the `PLANTED` labels that red them.
#: A group with an empty tuple is a group nothing has ever been seen to catch.
D7_GROUP_PLANTS: Final[tuple[tuple[int, str, tuple[str, ...]], ...]] = (
    (1, "open(...) with a mutating or non-literal mode", ("plant-open-write-in-output",)),
    (2, ".open(...) (Path.open), same mode rule", ("plant-path-open-write-in-ops",)),
    (3, "write_bytes", ("plant-write-bytes-in-ops",)),
    (4, "write_text", ("plant-write-in-safety-but-not-atomic",)),
    (5, "shutil.copy*", ("plant-shutil-copy-in-ops",)),
    (6, "shutil.move", ("plant-shutil-move-in-ops",)),
    (7, "os.replace", ("plant-os-replace-in-cli",)),
    (8, "os.rename", ("plant-os-rename-via-from-import-in-adapters",)),
    (9, "Path.unlink / os.remove / os.unlink", ("plant-unlink-in-ops",)),
    (10, "the tempfile create family", ("plant-mkstemp-in-ops",)),
    (11, "os.mkdir / os.makedirs / Path.mkdir", ("plant-mkdir-in-cli",)),
    (12, "os.rmdir / shutil.rmtree", ("plant-rmtree-in-ports",)),
    (13, "os.truncate / Path.touch / os.utime / os.chmod / os.chown", ("plant-chmod-in-output",)),
    (14, "os.open / os.symlink / os.link", ("plant-os-symlink-in-ops",)),
)


def test_every_d7_call_group_has_a_planted_violation() -> None:
    """AC15's own claim, mechanised instead of asserted in a spec document.

    Red: delete a `PLANTED` row, or empty a group's tuple, and this names the
    group that stopped being proven.
    """
    labels = {row[0] for row in PLANTED}
    assert len(D7_GROUP_PLANTS) == 14, "§D7 declares fourteen call groups"
    uncovered = [f"group {n} ({what})" for n, what, plants in D7_GROUP_PLANTS if not plants]
    assert uncovered == [], f"§D7 call groups with no planted violation: {uncovered}"
    dangling = sorted(
        f"group {n}: {plant}"
        for n, _, plants in D7_GROUP_PLANTS
        for plant in plants
        if plant not in labels
    )
    assert dangling == [], f"D7_GROUP_PLANTS names labels PLANTED does not carry: {dangling}"


#: The §D7 row-2 spelling the walk cannot see. `strict=True` so the day the
#: visitor learns to read a method call's mode this turns RED and the marker
#: has to be removed -- a gap that closes itself loudly rather than a comment.
PATH_OPEN_POSITIONAL = (
    "from pathlib import Path\n\n\ndef dump(p: Path) -> None:\n    p.open('w').close()\n"
)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "PDF-19 finding: _classify_open reads the mode from node.args[1], the BUILTIN "
        "open()'s slot. On Path.open the mode is args[0], so the idiomatic positional "
        "spelling p.open('w') evades §D7 row 2 entirely. Filed, not fixed -- PDF-19 "
        "makes no repair to the mechanism it audits."
    ),
)
def test_a_positional_mode_on_path_open_is_a_violation() -> None:
    found = scan_write_calls(PATH_OPEN_POSITIONAL, "pdf_tooling.ops.positional")
    assert [call.call for call in found] == ["p.open"]


# --------------------------------------------------------------------------- #
# `PLAN §12 R-07`: the `.pdftoolkit-` namespace has exactly one owner.
#
# `PDF-04` AC16 mechanised this as a grep for the LITERAL:
#
#     grep -rn "\.pdftoolkit-" src/ | grep -v "^src/pdf_tooling/safety/tempnames.py"
#
# Re-run verbatim at 7522e3e that command returns THREE hits and exits 0 --
# `ops/procpool.py:47`, `ops/procpool.py:207` and `safety/atomic.py:861`, all
# three prose, the last one a doc-comment whose whole point is that
# `_SCRATCH_PREFIX` deliberately does NOT carry the literal. The substance of
# AC16 holds; the command tests a PHRASE where the criterion is about a
# PROPOSITION, so a sentinel re-running the recorded ladder would file a defect
# against a correct tree. `expertise/product.yaml` (2026-08-31) twice:
# *search by proposition, not by phrase*.
#
# This is the proposition: exactly one string-literal DEFINITION of the prefix
# under `src/`. It also discharges `tempnames.py:8-11`'s claim that "an
# import-boundary grep asserts it", which until now was backed by nothing.
# --------------------------------------------------------------------------- #

#: The one module allowed to define the literal.
TEMP_PREFIX_OWNER: Final = "pdf_tooling.safety.tempnames"

#: The value `TEMP_PREFIX` must hold, spelled here so a second definition
#: elsewhere is detectable without importing the product.
TEMP_PREFIX_LITERAL: Final = ".pdftoolkit-"


def literal_prefix_definitions(root: Path) -> list[tuple[str, int]]:
    """Every module-level assignment of the `.pdftoolkit-` literal under *root*."""
    found: list[tuple[str, int]] = []
    for path in iter_python_files(root):
        tree = ast.parse(path.read_text(), filename=str(path))
        module = module_name(path, root)
        for node in ast.walk(tree):
            value = getattr(node, "value", None)
            if not isinstance(node, ast.Assign | ast.AnnAssign):
                continue
            if isinstance(value, ast.Constant) and value.value == TEMP_PREFIX_LITERAL:
                found.append((module, node.lineno))
    return found


def test_the_temp_prefix_literal_has_exactly_one_definition() -> None:
    """`PLAN §12 R-07`, as a proposition rather than as a phrase.

    `ops/discovery.py` cannot hardcode the namespace and must import the
    predicate; that is what makes "report, never sweep" enforceable in one
    place instead of in every consumer.
    """
    definitions = literal_prefix_definitions(SRC)
    assert [module for module, _ in definitions] == [TEMP_PREFIX_OWNER], (
        f"the {TEMP_PREFIX_LITERAL!r} literal is defined at {definitions}; exactly one "
        f"definition is allowed, in {TEMP_PREFIX_OWNER}"
    )


def test_a_second_prefix_literal_is_caught(tmp_path: Path) -> None:
    """The red proof for the check above, planted in a `discovery`-shaped module.

    That shape is deliberate: `PLAN §12 R-07`'s exclusion rule exists precisely
    so a discovery walk cannot grow its own copy of the namespace and drift.
    """
    scratch = tmp_path / "src"
    shutil.copytree(SRC, scratch)
    planted = scratch / "pdf_tooling" / "ops" / "discovery.py"
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text('from typing import Final\n\nSCAN_PREFIX: Final[str] = ".pdftoolkit-"\n')
    definitions = literal_prefix_definitions(scratch)
    assert len(definitions) == 2, definitions
    assert ("pdf_tooling.ops.discovery", 3) in definitions


# --------------------------------------------------------------------------- #
# Section 2 — engine imports and the subprocess chokepoint (PDF-05)
#
# APPENDED, never rewritten: Section 1 above is PDF-04's and this section builds
# on its machinery (`iter_python_files`, `module_name`, `dotted`,
# `from_import_bindings`) rather than starting a second walk. Section 3 belongs
# to the fixture-corpus spec.
#
# WHAT THIS SECTION IS FOR
# ------------------------
# This is the mechanised half of the product's licensing claim. `scripts/
# licenses.py` sees the DEPENDENCY graph; it cannot see the CALL graph. "Is
# anything AGPL/GPL/LGPL reachable?" stays answerable by reading six port files
# only while every engine import and every spawn is confined beneath them, and
# twenty verbs are written after this file by authors who will not re-read
# `PLAN.md` §5.2. A convenience `import pikepdf` in `ops/` would not break a
# feature -- it would void the product's only reason to exist.
#
# THE PILLOW EXCLUSION, RECORDED WITH ITS REASON
# ----------------------------------------------
# `PIL`/Pillow is deliberately NOT in ENGINE_MODULES. `PLAN.md` §7.1 scopes it as
# "image plumbing" rather than a port-backing engine, and the compression work's
# image pass is expected to use it inside `ops/`. Writing the exclusion down HERE,
# with the reason, is what stops a later spec from quietly weakening this test to
# make room for it -- which is how a guard like this actually dies.
# --------------------------------------------------------------------------- #

#: Engine libraries that may be imported only beneath `adapters/`. `pdfminer` is
#: pdfplumber's own dependency and `weasyprint` is the Phase-2 `[html]` extra;
#: both are listed so that reaching for them directly is a red rather than a
#: discovery made later.
ENGINE_MODULES: Final = frozenset(
    {
        "pypdf",
        "pypdfium2",
        "pikepdf",
        "reportlab",
        "pdfplumber",
        "pdfminer",
        "pytesseract",
        "weasyprint",
    }
)

#: The one package permitted to import them.
ADAPTER_PACKAGE: Final = "pdf_tooling.adapters"

#: The one module permitted to spawn. Spelled as a module path to match
#: `module_name()`; `tests/test_license_policy.py` spells the same file as a
#: path, and both are asserted to point at a file that exists.
SPAWN_CHOKEPOINT: Final = "pdf_tooling.adapters.subprocess_util"

#: Spawn surfaces that must not appear outside the chokepoint. `pty` is here and
#: not in the licence walk: it is a second, less obvious way to get a child
#: process, and a `pty.spawn` would evade a check that only knows `subprocess`.
SPAWN_MODULES: Final = frozenset({"subprocess", "pty"})
OS_SPAWN_PREFIXES: Final = ("exec", "spawn")


#: The three Section 2 finding kinds, kept DISJOINT and compared by equality.
#: The first draft used prefix matching over prose kinds, and "spawn module
#: outside the chokepoint" matched the argv[0] test's `startswith("spawn ")` --
#: so an import violation turned two tests red, one of them with a message about
#: something else entirely. A guard that fires for the wrong stated reason is a
#: guard whose next reader mistrusts it.
KIND_ENGINE_IMPORT: Final = "engine-import"
KIND_SPAWN_SURFACE: Final = "spawn-surface"
KIND_HELPER_ARGV0: Final = "helper-argv0"


class Boundary(NamedTuple):
    """One boundary violation, located precisely enough to act on."""

    module: str
    line: int
    what: str
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.module}:{self.line}: {self.detail} '{self.what}'"


def _in_adapters(module: str) -> bool:
    return module == ADAPTER_PACKAGE or module.startswith(ADAPTER_PACKAGE + ".")


def _imported_top_levels(tree: ast.Module) -> list[tuple[str, int]]:
    """Every top-level module name this file imports, with its line number.

    Both `import x.y` and `from x.y import z` reduce to `x`, which is the only
    granularity that matters for "is this library on the call graph".
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name.split(".")[0], node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.module.split(".")[0], node.lineno))
    return found


def scan_engine_imports(source: str, module: str) -> list[Boundary]:
    """Engine libraries imported outside `adapters/`."""
    if _in_adapters(module):
        return []
    tree = ast.parse(source, filename=module)
    return [
        Boundary(module, line, name, KIND_ENGINE_IMPORT, "engine import outside adapters/")
        for name, line in _imported_top_levels(tree)
        if name in ENGINE_MODULES
    ]


def scan_spawn_surface(source: str, module: str) -> list[Boundary]:
    """Spawn surfaces reached outside the one sanctioned module."""
    if module == SPAWN_CHOKEPOINT:
        return []
    tree = ast.parse(source, filename=module)
    found: list[Boundary] = [
        Boundary(module, line, name, KIND_SPAWN_SURFACE, "spawn module outside the chokepoint")
        for name, line in _imported_top_levels(tree)
        if name in SPAWN_MODULES
    ]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = dotted(node.func)
        head, _, tail = target.rpartition(".")
        if head == "os" and (tail == "system" or tail.startswith(OS_SPAWN_PREFIXES)):
            found.append(
                Boundary(
                    module,
                    node.lineno,
                    target,
                    KIND_SPAWN_SURFACE,
                    "os spawn outside the chokepoint",
                )
            )
    return found


# --------------------------------------------------------------------------- #
# The compensating check the chokepoint's own exemption requires.
#
# `tests/test_license_policy.py` refuses a spawn whose `argv[0]` is not
# statically resolvable -- but PDF-05 had to exempt the chokepoint from that
# rule, because a generic wrapper takes argv as a parameter and therefore has a
# non-literal argv[0] BY DEFINITION. That exemption opens a second-order hole:
# once every spawn routes through `subprocess_util.run(...)`, the licence walk's
# `_is_spawn()` (which matches only `subprocess.*`, `sp.*` and `os.*`) no longer
# looks at adapter call sites at all, so a `run(["<forbidden>", ...])` would slip
# past its forbidden-argv[0] shape. `shutil.which("<forbidden>")` is still caught
# there, so the gap is a narrowing rather than a total loss -- and this closes it.
# --------------------------------------------------------------------------- #

SPAWN_HELPER: Final = "subprocess_util"
SPAWN_HELPER_QUALIFIED: Final = "pdf_tooling.adapters.subprocess_util"


def _module_level_literals(tree: ast.Module) -> dict[str, str]:
    """Module-level names bound to a string literal, `Final[str]` included."""
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                out[node.target.id] = node.value.value
        elif isinstance(node, ast.Assign):
            if not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _is_helper_call(target: str, bindings: dict[str, str]) -> bool:
    """Whether a dotted call target names the spawn helper's `run`.

    Both spellings are recognised: `subprocess_util.run(...)` after
    `from pdf_tooling.adapters import subprocess_util`, and a bare `run(...)`
    after `from ...subprocess_util import run`.
    """
    if target == f"{SPAWN_HELPER}.run":
        return True
    return bindings.get(target) == f"{SPAWN_HELPER_QUALIFIED}.run"


def _static_argv0(node: ast.expr, literals: dict[str, str]) -> str | None:
    """argv[0] when it is a literal or a module-level name bound to one."""
    if isinstance(node, ast.List | ast.Tuple):
        if not node.elts:
            return None
        first = node.elts[0]
    else:
        return None
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    if isinstance(first, ast.Name):
        return literals.get(first.id)
    return None


def scan_helper_call_sites(source: str, module: str) -> list[Boundary]:
    """Every `subprocess_util.run(...)` whose argv[0] is unresolvable or forbidden."""
    tree = ast.parse(source, filename=module)
    literals = _module_level_literals(tree)
    bindings = from_import_bindings(tree)
    found: list[Boundary] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if not _is_helper_call(dotted(node.func), bindings):
            continue
        argv0 = _static_argv0(node.args[0], literals)
        if argv0 is None:
            found.append(
                Boundary(
                    module,
                    node.lineno,
                    "argv[0]",
                    KIND_HELPER_ARGV0,
                    "spawn with an unresolvable argv[0]",
                )
            )
            continue
        base = argv0.replace("\\", "/").rsplit("/", 1)[-1]
        if _is_forbidden_binary(base):
            found.append(
                Boundary(
                    module,
                    node.lineno,
                    base,
                    KIND_HELPER_ARGV0,
                    "spawn of a forbidden binary",
                )
            )
    return found


# The forbidden set is IMPORTED from the licence-policy module rather than copied.
# Two lists of the same names in two test files is how one of them silently stops
# covering what the other covers; the tightenings PDF-02 added must apply here too.
from test_license_policy import FORBIDDEN as LICENCE_FORBIDDEN  # noqa: E402
from test_license_policy import normalize as _normalize_binary  # noqa: E402

_NORMALIZED_FORBIDDEN: Final = frozenset(_normalize_binary(n) for n in LICENCE_FORBIDDEN)


def _is_forbidden_binary(name: str) -> bool:
    return _normalize_binary(name) in _NORMALIZED_FORBIDDEN


def scan_boundaries(root: Path) -> list[Boundary]:
    """All three Section 2 walks over every Python file under *root*."""
    found: list[Boundary] = []
    for path in iter_python_files(root):
        module = module_name(path, root)
        source = path.read_text()
        found.extend(scan_engine_imports(source, module))
        found.extend(scan_spawn_surface(source, module))
        found.extend(scan_helper_call_sites(source, module))
    return found


# --------------------------------------------------------------------------- #
# The gate, over the real tree.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def boundaries() -> list[Boundary]:
    return scan_boundaries(SRC)


def test_no_engine_library_is_imported_outside_adapters(boundaries: list[Boundary]) -> None:
    """A red here is a LICENCE-POLICY finding (D-02), not a style finding."""
    offenders = [item for item in boundaries if item.kind == KIND_ENGINE_IMPORT]
    listed = "\n".join(f"  - {item}" for item in offenders)
    assert offenders == [], (
        "engine libraries are importable only beneath adapters/ -- this is what makes "
        f"the licence question answerable by reading six port files:\n{listed}"
    )


def test_nothing_outside_the_chokepoint_can_spawn(boundaries: list[Boundary]) -> None:
    offenders = [item for item in boundaries if item.kind == KIND_SPAWN_SURFACE]
    listed = "\n".join(f"  - {item}" for item in offenders)
    assert offenders == [], f"{SPAWN_CHOKEPOINT} is the only spawn point:\n{listed}"


def test_every_spawn_call_site_names_a_permitted_binary(boundaries: list[Boundary]) -> None:
    """The compensating check for the chokepoint's own argv[0] exemption."""
    offenders = [item for item in boundaries if item.kind == KIND_HELPER_ARGV0]
    listed = "\n".join(f"  - {item}" for item in offenders)
    assert offenders == [], (
        "every subprocess_util.run() call site must pass a statically resolvable "
        f"argv[0] that is not a forbidden binary:\n{listed}"
    )


def test_the_adapters_package_actually_contains_the_engine_imports() -> None:
    """Non-vacuity. If nothing imports an engine anywhere, Section 2 proves nothing."""
    importing: set[str] = set()
    for path in iter_python_files(SRC):
        module = module_name(path, SRC)
        if not _in_adapters(module):
            continue
        tree = ast.parse(path.read_text(), filename=module)
        importing.update(name for name, _ in _imported_top_levels(tree) if name in ENGINE_MODULES)
    assert importing, "no module under adapters/ imports an engine -- the walk is vacuous"


def test_the_chokepoint_actually_spawns() -> None:
    """Non-vacuity for the spawn half: the wrapper really does reach subprocess."""
    path = SRC / SPAWN_CHOKEPOINT.replace(".", "/")
    source = path.with_suffix(".py").read_text()
    tree = ast.parse(source, filename=SPAWN_CHOKEPOINT)
    assert "subprocess" in {name for name, _ in _imported_top_levels(tree)}, (
        f"{SPAWN_CHOKEPOINT} does not import subprocess -- either the walk is broken "
        "or the spawn moved somewhere unguarded"
    )


def test_the_three_finding_kinds_are_disjoint() -> None:
    """Each violation turns exactly ONE assertion red, with the right message.

    Regression guard for a real defect in this section's first draft: the kinds
    were prose and the tests matched them by prefix, so a `import subprocess` in
    `cli/` failed both the spawn-surface assertion AND the argv[0] assertion --
    the latter reporting that a call site had an unresolvable argv[0], which was
    not true and would have sent the next reader looking in the wrong file.
    """
    kinds = (KIND_ENGINE_IMPORT, KIND_SPAWN_SURFACE, KIND_HELPER_ARGV0)
    assert len(set(kinds)) == 3
    for one in kinds:
        for other in kinds:
            if one is not other:
                assert not one.startswith(other) and not other.startswith(one)


@pytest.mark.parametrize(
    ("relative", "source", "expected_kind"),
    [
        (
            "pdf_tooling/ops/sneaky.py",
            "import pikepdf\n",
            KIND_ENGINE_IMPORT,
        ),
        (
            "pdf_tooling/cli/sneaky.py",
            "import subprocess\n",
            KIND_SPAWN_SURFACE,
        ),
        (
            "pdf_tooling/adapters/sneaky.py",
            "from pdf_tooling.adapters import subprocess_util\n\n\n"
            "def go():\n    return subprocess_util.run(['gs'], timeout=1)\n",
            KIND_HELPER_ARGV0,
        ),
    ],
    ids=["engine-import", "spawn-surface", "helper-argv0"],
)
def test_each_violation_class_reports_only_its_own_kind(
    relative: str,
    source: str,
    expected_kind: str,
    tmp_path: Path,
) -> None:
    scratch = tmp_path / "src"
    shutil.copytree(SRC, scratch)
    planted = scratch / relative
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(source)

    kinds = {item.kind for item in scan_boundaries(scratch)}
    assert kinds == {expected_kind}, kinds


def test_pillow_is_deliberately_not_an_engine_module() -> None:
    """The recorded exclusion, asserted so it cannot be widened by accident.

    Pillow is image plumbing (`PLAN.md` §7.1), not a port-backing engine, and the
    compression work's image pass is expected to use it inside `ops/`. This
    assertion exists so that adding it here is a deliberate, reviewed change
    rather than a passing thought.
    """
    assert "PIL" not in ENGINE_MODULES
    assert "pillow" not in ENGINE_MODULES


# --------------------------------------------------------------------------- #
# Proof that Section 2's guards fire. Without these, the assertions are a claim.
# --------------------------------------------------------------------------- #

PLANTED_SECTION_2: Final = (
    (
        "plant-pikepdf-import-in-ops",
        "pdf_tooling/ops/sneaky.py",
        "import pikepdf\n\n\ndef go():\n    return pikepdf\n",
    ),
    (
        "plant-pypdf-from-import-in-cli",
        "pdf_tooling/cli/sneaky.py",
        "from pypdf import PdfReader\n\n\ndef go():\n    return PdfReader\n",
    ),
    (
        "plant-reportlab-import-in-ports",
        "pdf_tooling/ports/sneaky.py",
        "import reportlab.pdfgen\n\n\ndef go():\n    return reportlab\n",
    ),
    (
        "plant-pdfplumber-import-in-output",
        "pdf_tooling/output/sneaky.py",
        "import pdfplumber\n\n\ndef go():\n    return pdfplumber\n",
    ),
    (
        "plant-pypdfium2-import-in-safety",
        "pdf_tooling/safety/sneaky.py",
        "import pypdfium2\n\n\ndef go():\n    return pypdfium2\n",
    ),
    (
        "plant-subprocess-import-in-ops",
        "pdf_tooling/ops/sneaky.py",
        "import subprocess\n\n\ndef go():\n    return subprocess\n",
    ),
    (
        "plant-os-system-in-cli",
        "pdf_tooling/cli/sneaky.py",
        "import os\n\n\ndef go():\n    os.system('ls')\n",
    ),
    (
        "plant-pty-spawn-in-adapters",
        "pdf_tooling/adapters/sneaky.py",
        "import pty\n\n\ndef go():\n    pty.spawn(['ls'])\n",
    ),
    (
        "plant-forbidden-binary-through-the-helper",
        "pdf_tooling/adapters/sneaky.py",
        "from pdf_tooling.adapters import subprocess_util\n\n\n"
        "def go():\n    return subprocess_util.run(['gs', '-q'], timeout=1)\n",
    ),
    (
        "plant-computed-argv0-through-the-helper",
        "pdf_tooling/adapters/sneaky.py",
        "from pdf_tooling.adapters import subprocess_util\n\n\n"
        "def go(name):\n    return subprocess_util.run([name, '-q'], timeout=1)\n",
    ),
)


@pytest.mark.parametrize(
    ("label", "relative", "source"),
    PLANTED_SECTION_2,
    ids=[row[0] for row in PLANTED_SECTION_2],
)
def test_a_planted_section_2_violation_fails_the_walk(
    label: str,
    relative: str,
    source: str,
    tmp_path: Path,
) -> None:
    """Copy src/, plant one violation, and confirm Section 2 turns red."""
    scratch = tmp_path / "src"
    shutil.copytree(SRC, scratch)
    planted = scratch / relative
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(source)

    assert scan_boundaries(scratch), f"Section 2 did not notice the planted violation: {label}"


BENIGN_SECTION_2 = '''
"""A module that mentions every forbidden thing without doing any of them."""
from pdf_tooling.adapters import subprocess_util

TESSERACT_BIN = "tesseract"
subprocess = "not the module"


def go(pikepdf, reportlab):
    """pypdf, pikepdf and pdfplumber appear in this docstring and are not imports."""
    version = subprocess_util.run([TESSERACT_BIN, "--version"], timeout=5)
    listed = subprocess_util.run(["soffice", "--version"], timeout=5)
    return version, listed, pikepdf, reportlab
'''


def test_benign_section_2_calls_are_never_flagged() -> None:
    """The negative self-test. A guard with false positives gets weakened away.

    Engine names in a docstring, in a parameter name and in a local binding are
    not imports; a `Final[str]` argv[0] and a literal argv[0] are both resolvable
    and both permitted. This is the mechanized proof that Section 2 is an AST
    walk and not a text grep -- exactly as its Section 1 counterpart proves for
    the write chokepoint.
    """
    module = "pdf_tooling.ops.benign"
    found = (
        scan_engine_imports(BENIGN_SECTION_2, module)
        + scan_spawn_surface(BENIGN_SECTION_2, module)
        + scan_helper_call_sites(BENIGN_SECTION_2, module)
    )
    assert found == [], f"false positives: {[str(item) for item in found]}"


def test_the_two_forbidden_lists_are_the_same_list() -> None:
    """Section 2 checks argv[0] against the LICENCE walk's set, not a copy of it.

    Two hand-maintained copies of the same names is how one of them silently
    stops covering what the other covers, so the import above is load-bearing
    rather than tidy.
    """
    for name in ("gs", "pdftk", "fitz", "poppler"):
        assert _is_forbidden_binary(name)
    assert not _is_forbidden_binary("tesseract")
    assert not _is_forbidden_binary("soffice")


def test_importing_the_port_layer_loads_no_engine() -> None:
    """`PLAN.md` §12 R-13, at the port seam.

    The CLI spine already asserts that importing `cli.main` leaves `sys.modules`
    clean -- an assertion that only became non-vacuous when the first verbs that
    reach the ports were registered on it. This is the complementary half: even
    importing every port module directly, which is a heavier thing to do than
    starting the CLI, must not pull an engine in. That is what makes the
    "lazy imports only" rule in `ports/__init__` enforced rather than intended.
    """
    ports = [
        "pdf_tooling.ports",
        "pdf_tooling.ports.structure",
        "pdf_tooling.ports.raster",
        "pdf_tooling.ports.compose",
        "pdf_tooling.ports.text",
        "pdf_tooling.ports.ocr",
        "pdf_tooling.ports.office",
    ]
    probe = (
        "import sys;"
        + "".join(f"__import__({name!r});" for name in ports)
        + f"leaked = {set(ENGINE_MODULES)!r} & set(sys.modules);"
        "print(sorted(leaked));"
        "sys.exit(1 if leaked else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"importing the port layer pulled in engines: {result.stdout.strip()}\n{result.stderr}"
    )


# --------------------------------------------------------------------------- #
# PDF-20 -- Section 2 continued: the probe-path environment sandbox is
# PROTECTED BY CONSTRUCTION (AC22). Append only; nothing above is rewritten.
#
# `soffice --version` creates the user's config directory, so `doctor` -- and
# anything else that resolves the office port -- wrote into `$HOME` on every
# run (`ba07fdfb56` / B-100), including under `--dry-run`, against a rule
# `CLAUDE.md` states without conditions. PDF-20 routes the three PROBE-path
# spawns through `subprocess_util.probe_env()`.
#
# WHY THIS IS A GUARD AND NOT A DEFAULT. Putting the sandbox inside `run()`
# would have been the more "central" fix and it is the WRONG one: `run()` is
# shared with the two OPERATIONAL spawns, which depend on the caller's real
# environment (`convert_to_pdf` passes its own isolated profile already; an OCR
# run may legitimately need operator-installed language data reachable from the
# real home). Forcing a redirected home under either is a silent behaviour
# change to a separately-verified verb. The construction guarantee therefore
# lives here, where a FOURTH probe added later inherits it and the operational
# path is untouched.
#
# THE EXCLUSION IS ASSERTED, NOT ASSUMED. `OPERATIONAL_SPAWNS` below is checked
# in BOTH directions: every entry must still resolve to a real call site (an
# exclusion that no longer names anything is how an allowlist rots), and an
# excluded site must NOT pass the probe sandbox. So an operational call cannot
# drift into the probe set, and a probe cannot drift out of it, without a red.
# --------------------------------------------------------------------------- #

#: Section 2's fourth finding kind, DISJOINT from the other three by equality.
KIND_PROBE_SANDBOX: Final = "probe-sandbox"

#: The methods whose spawns are probe-path. `probe()` is the port contract's own
#: name (`ports/__init__`'s Protocol surface) and `languages()` is the one probe
#: helper a probe delegates to.
PROBE_METHODS: Final = frozenset({"probe", "languages"})

#: The sandbox helper, in both spellings a call site may use.
SANDBOX_HELPER: Final = "probe_env"
SANDBOX_HELPER_QUALIFIED: Final = "pdf_tooling.adapters.subprocess_util.probe_env"

#: The OPERATIONAL spawns, excluded BY DESIGN (PDF-20 Scope > Out; they belong
#: to the office/OCR spec). `(module, enclosing function)`.
OPERATIONAL_SPAWNS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("pdf_tooling.adapters.soffice_office", "convert_to_pdf"),
        ("pdf_tooling.adapters.tesseract_ocr", "text_layer"),
    }
)


class SpawnSite(NamedTuple):
    """One `subprocess_util.run(...)` call site, with the function around it."""

    module: str
    function: str
    line: int
    sandboxed: bool

    @property
    def where(self) -> tuple[str, str]:
        return (self.module, self.function)

    def __str__(self) -> str:
        state = "sandboxed" if self.sandboxed else "un-sandboxed"
        return f"{self.module}:{self.line}: {self.function}() spawns {state}"


class _SpawnSiteVisitor(ast.NodeVisitor):
    """Every helper spawn, tagged with its enclosing function and env argument.

    Scope tracking mirrors Section 1's `_WriteCallVisitor` rather than inventing
    a second convention.
    """

    def __init__(self, module: str, bindings: dict[str, str]) -> None:
        self.module = module
        self.bindings = bindings
        self.scope: list[str] = ["<module>"]
        self.found: list[SpawnSite] = []

    def _scoped(self, node: ast.AST, name: str) -> None:
        self.scope.append(name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._scoped(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._scoped(node, node.name)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if _is_helper_call(dotted(node.func), self.bindings):
            self.found.append(
                SpawnSite(self.module, self.scope[-1], node.lineno, self._is_sandboxed(node))
            )
        self.generic_visit(node)

    def _is_sandboxed(self, node: ast.Call) -> bool:
        """Whether this call passes `env=` built by the sandbox helper.

        A CALL is required, not merely a name: `env=some_dict` would satisfy a
        name check while handing the child an arbitrary environment.
        """
        for keyword in node.keywords:
            if keyword.arg != "env" or not isinstance(keyword.value, ast.Call):
                continue
            target = dotted(keyword.value.func)
            if target.rsplit(".", 1)[-1] == SANDBOX_HELPER:
                return True
            if self.bindings.get(target) == SANDBOX_HELPER_QUALIFIED:
                return True
        return False


def scan_spawn_sites(source: str, module: str) -> list[SpawnSite]:
    """Every `subprocess_util.run(...)` site in one module, tagged."""
    tree = ast.parse(source, filename=module)
    visitor = _SpawnSiteVisitor(module, from_import_bindings(tree))
    visitor.visit(tree)
    return visitor.found


def probe_sandbox_violations(
    sites: list[SpawnSite],
    *,
    operational: frozenset[tuple[str, str]] = OPERATIONAL_SPAWNS,
) -> list[Boundary]:
    """Probe-path spawns without the sandbox, and excluded spawns with it."""
    problems: list[Boundary] = []
    for site in sites:
        is_probe = site.function in PROBE_METHODS
        if is_probe and not site.sandboxed:
            problems.append(
                Boundary(
                    site.module,
                    site.line,
                    site.function,
                    KIND_PROBE_SANDBOX,
                    "probe-path spawn without env=subprocess_util.probe_env()",
                )
            )
        elif not is_probe and site.where not in operational:
            problems.append(
                Boundary(
                    site.module,
                    site.line,
                    site.function,
                    KIND_PROBE_SANDBOX,
                    "spawn that is neither a declared probe nor a declared operational site",
                )
            )
        elif not is_probe and site.sandboxed:
            problems.append(
                Boundary(
                    site.module,
                    site.line,
                    site.function,
                    KIND_PROBE_SANDBOX,
                    "operational spawn has joined the probe sandbox by accident",
                )
            )
    return problems


def scan_spawn_sites_tree(root: Path) -> list[SpawnSite]:
    found: list[SpawnSite] = []
    for path in iter_python_files(root):
        found.extend(scan_spawn_sites(path.read_text(), module_name(path, root)))
    return found


@pytest.fixture(scope="module")
def spawn_sites() -> list[SpawnSite]:
    return scan_spawn_sites_tree(SRC)


def test_every_probe_path_spawn_passes_the_sandbox(spawn_sites: list[SpawnSite]) -> None:
    """AC22. B-100 cannot come back through a fourth probe."""
    problems = probe_sandbox_violations(spawn_sites)
    assert problems == [], "\n".join(str(item) for item in problems)


def test_the_operational_exclusion_still_names_real_call_sites(
    spawn_sites: list[SpawnSite],
) -> None:
    """The exclusion list may not outlive the call sites it excuses.

    Without this the two entries could be deleted from `src/` and the guard
    would go on reporting green over a set it no longer describes -- allowlist
    rot, which is how a guard dies quietly (Section 1's own words).
    """
    live = {site.where for site in spawn_sites}
    stale = sorted(OPERATIONAL_SPAWNS - live)
    assert stale == [], f"OPERATIONAL_SPAWNS entries that no longer resolve: {stale}"


def test_the_spawn_walk_sees_the_real_tree(spawn_sites: list[SpawnSite]) -> None:
    """Non-vacuity. A guard over zero call sites is green for the worst reason.

    Pinned against the enumerated population rather than a bare `> 0`: three
    probe-path spawns and two operational ones is the whole spawn surface of
    this product, and a walk that stopped seeing one of them would otherwise be
    indistinguishable from a tree that no longer had it.
    """
    probes = [site for site in spawn_sites if site.function in PROBE_METHODS]
    operational = [site for site in spawn_sites if site.where in OPERATIONAL_SPAWNS]
    assert len(probes) >= 3, f"the walk found only {len(probes)} probe spawn(s): {probes}"
    assert len(operational) >= 2, (
        f"the walk found only {len(operational)} operational: {operational}"
    )
    assert all(site.sandboxed for site in probes)
    assert not any(site.sandboxed for site in operational)


# -- Proof that the AC22 guard fires, in BOTH directions -------------------- #

_FOURTH_PROBE_UNSANDBOXED = """
from pdf_tooling.adapters import subprocess_util
BINARY = "widget"
class Adapter:
    def probe(self):
        return subprocess_util.run([BINARY, "--version"], timeout=1.0, check=False)
"""

_FOURTH_PROBE_SANDBOXED = """
from pdf_tooling.adapters import subprocess_util
BINARY = "widget"
class Adapter:
    def probe(self):
        return subprocess_util.run(
            [BINARY, "--version"], timeout=1.0, check=False, env=subprocess_util.probe_env()
        )
"""

_PROBE_WITH_A_PLAIN_DICT = """
import os
from pdf_tooling.adapters import subprocess_util
BINARY = "widget"
class Adapter:
    def probe(self):
        return subprocess_util.run([BINARY, "-v"], timeout=1.0, check=False, env=dict(os.environ))
"""

_OPERATIONAL_JOINING_THE_SANDBOX = """
from pdf_tooling.adapters import subprocess_util
BINARY = "soffice"
class Adapter:
    def convert_to_pdf(self, source):
        return subprocess_util.run(
            [BINARY, "--convert-to"], timeout=1.0, check=False, env=subprocess_util.probe_env()
        )
"""

_UNDECLARED_SPAWN = """
from pdf_tooling.adapters import subprocess_util
BINARY = "widget"
class Adapter:
    def do_something_new(self):
        return subprocess_util.run([BINARY, "--go"], timeout=1.0, check=False)
"""


def test_the_probe_sandbox_guard_fires_on_a_fourth_unsandboxed_probe() -> None:
    module = "pdf_tooling.adapters.widget"
    found = probe_sandbox_violations(scan_spawn_sites(_FOURTH_PROBE_UNSANDBOXED, module))
    assert found, "a fourth probe spawn without the sandbox was not caught"
    assert found[0].kind == KIND_PROBE_SANDBOX
    assert probe_sandbox_violations(scan_spawn_sites(_FOURTH_PROBE_SANDBOXED, module)) == []


def test_the_probe_sandbox_guard_refuses_an_arbitrary_env() -> None:
    """`env=` alone is not the guarantee -- the sandbox helper is.

    A name check would accept `env=dict(os.environ)`, which is precisely the
    environment whose `$HOME` the probe must not be able to write through.
    """
    found = probe_sandbox_violations(
        scan_spawn_sites(_PROBE_WITH_A_PLAIN_DICT, "pdf_tooling.adapters.widget")
    )
    assert found, "a probe passing an arbitrary env was accepted as sandboxed"


def test_the_exclusion_is_asserted_in_the_other_direction_too() -> None:
    """An operational site may not quietly join the probe sandbox, and a new
    spawn may not appear in neither set."""
    joined = probe_sandbox_violations(
        scan_spawn_sites(_OPERATIONAL_JOINING_THE_SANDBOX, "pdf_tooling.adapters.soffice_office"),
        operational=frozenset({("pdf_tooling.adapters.soffice_office", "convert_to_pdf")}),
    )
    assert joined and "joined the probe sandbox" in joined[0].detail
    undeclared = probe_sandbox_violations(
        scan_spawn_sites(_UNDECLARED_SPAWN, "pdf_tooling.adapters.widget")
    )
    assert undeclared and "neither a declared probe" in undeclared[0].detail


# --------------------------------------------------------------------------- #
# Section 3 -- the typer/click import boundary (PDF-06)
#
# APPENDED, never rewriting Sections 1/2. `PLAN.md` §10 / D-03: no typer or
# click import below L1 (`cli/`) -- `ops/` stays framework-free per L2's own
# contract (`CLAUDE.md`'s layer table), so a page-range parser or a future
# `ops/merge.py` cannot quietly grow a dependency on the CLI layer. PDF-04
# scoped this Out and built the reusable machinery (`iter_python_files`,
# `module_name`, `_imported_top_levels`) that Section 2 also builds on;
# `decision.md` X-6 assigns the assertion itself to PDF-06 and estimates it at
# roughly ten lines against machinery that already exists -- this section is
# that estimate honoured.
# --------------------------------------------------------------------------- #

#: L1 -- the only package permitted to import the CLI framework.
CLI_PACKAGE: Final = "pdf_tooling.cli"

#: `click` is checked even though nothing in this codebase can literally
#: `import click` today -- the installed Typer vendors its own copy
#: (`cli/common.py`'s own docstring: "the CLI framework vendors its Click, so
#: there is no importable top-level click.core to reach into"). Checking for
#: it anyway means a future dependency change that reintroduces a real `click`
#: package is caught immediately rather than silently widening L1.
CLI_FRAMEWORK_MODULES: Final = frozenset({"typer", "click"})

KIND_CLI_FRAMEWORK_IMPORT: Final = "cli-framework-import"


def _below_l1(module: str) -> bool:
    return module != CLI_PACKAGE and not module.startswith(CLI_PACKAGE + ".")


def scan_cli_framework_imports(source: str, module: str) -> list[Boundary]:
    """`typer`/`click` imported outside `cli/` -- `PLAN.md` §10, D-03."""
    if not _below_l1(module):
        return []
    tree = ast.parse(source, filename=module)
    return [
        Boundary(module, line, name, KIND_CLI_FRAMEWORK_IMPORT, "typer/click import below L1")
        for name, line in _imported_top_levels(tree)
        if name in CLI_FRAMEWORK_MODULES
    ]


def scan_cli_framework_boundary(root: Path) -> list[Boundary]:
    found: list[Boundary] = []
    for path in iter_python_files(root):
        module = module_name(path, root)
        found.extend(scan_cli_framework_imports(path.read_text(), module))
    return found


@pytest.fixture(scope="module")
def cli_framework_boundaries() -> list[Boundary]:
    return scan_cli_framework_boundary(SRC)


def test_no_typer_or_click_import_below_l1(cli_framework_boundaries: list[Boundary]) -> None:
    listed = "\n".join(f"  - {item}" for item in cli_framework_boundaries)
    assert cli_framework_boundaries == [], (
        f"typer/click is importable only inside {CLI_PACKAGE} -- PLAN.md §10 / D-03:\n{listed}"
    )


def test_the_cli_package_actually_imports_typer() -> None:
    """Non-vacuity. If cli/ itself never imports typer, the boundary above proves nothing."""
    importing = False
    for path in iter_python_files(SRC):
        module = module_name(path, SRC)
        if _below_l1(module):
            continue
        tree = ast.parse(path.read_text(), filename=module)
        if "typer" in {name for name, _ in _imported_top_levels(tree)}:
            importing = True
            break
    assert importing, "no module under cli/ imports typer -- the walk is vacuous"


PLANTED_SECTION_3: Final = (
    (
        "plant-typer-import-in-ops",
        "pdf_tooling/ops/sneaky.py",
        "import typer\n\n\ndef go():\n    return typer\n",
    ),
    (
        "plant-typer-from-import-in-safety",
        "pdf_tooling/safety/sneaky.py",
        "from typer import Typer\n\n\ndef go():\n    return Typer\n",
    ),
    (
        "plant-click-import-in-ports",
        "pdf_tooling/ports/sneaky.py",
        "import click\n\n\ndef go():\n    return click\n",
    ),
)


@pytest.mark.parametrize(
    ("label", "relative", "source"),
    PLANTED_SECTION_3,
    ids=[row[0] for row in PLANTED_SECTION_3],
)
def test_a_planted_section_3_violation_fails_the_walk(
    label: str,
    relative: str,
    source: str,
    tmp_path: Path,
) -> None:
    """Copy src/, plant one below-L1 typer/click import, confirm Section 3 turns red."""
    scratch = tmp_path / "src"
    shutil.copytree(SRC, scratch)
    planted = scratch / relative
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(source)

    found = scan_cli_framework_boundary(scratch)
    assert found, f"Section 3 did not notice the planted violation: {label}"


BENIGN_SECTION_3 = '''
"""This module talks about typer and click without importing either."""

typer = "not the module"


def go(click):
    """click is a parameter name here, not an import."""
    return typer, click
'''


def test_benign_section_3_mentions_are_never_flagged() -> None:
    """typer/click named in a docstring, a string literal, or a parameter name
    is not an import -- the mechanized proof that Section 3 is an AST walk and
    not a text grep, matching Sections 1 and 2's own negative-control
    discipline."""
    found = scan_cli_framework_imports(BENIGN_SECTION_3, "pdf_tooling.ops.benign")
    assert found == [], f"false positives: {[str(item) for item in found]}"


# --------------------------------------------------------------------------- #
# Section 4 -- the confirmation gate is never bypassed under `--dry-run` (B-093)
#
# APPENDED, never rewritten, per this file's own header rule; it reuses
# `iter_python_files`, `module_name` and `Boundary` rather than starting a
# fourth walk.
#
# THE DEFECT THIS EXISTS FOR. Every one of the fifteen `require_confirmation`
# call sites was written as `if not config.dry_run and <destructive>:`, so a
# bulk-destructive invocation on a non-TTY without `-y` exited 0 under
# `--dry-run` and 5 for real -- a `dry != real` split (operator ruling OR-7,
# PDF-15 §D12.2's "bulk-destructive" row, which is KNOWABLE at plan time).
# Eight of those guards predate the spec that first noticed them.
#
# WHY A STRUCTURAL RULE AND NOT ONLY A BEHAVIOURAL ONE. The behavioural pairs
# (`tests/integration/test_or7_bulk_destructive.py`, C13's dry arm) cover the
# verbs that exist today. This walk covers the ones that do not: the sixteenth
# verb's author copies a neighbouring `cmd_*.py`, and copying the old shape back
# in is exactly how this defect got to fifteen sites. `--dry-run` awareness now
# lives once, inside `safety/confirm.py::require_confirmation`; a caller's job
# is to call it unconditionally on the destructive path, and that is the rule
# below.
#
# AST, not grep, for the reason every other section here is: the words
# "dry_run" and "require_confirmation" appear in the docstrings and comments of
# most of these modules, and a text scan would be red on prose and blind to
# `if cfg.dry_run: ...` spelled with a different receiver name.
# --------------------------------------------------------------------------- #

KIND_DRY_RUN_BYPASS: Final = "dry-run-confirmation-bypass"

#: The shared gate. Matched on the CALL NAME, so both `require_confirmation(...)`
#: and `confirm.require_confirmation(...)` are seen.
CONFIRMATION_CALL: Final = "require_confirmation"

#: The attribute/name whose appearance in a GUARD is the bypass. `--dry-run` is
#: spelled `dry_run` on both `GlobalConfig` and `SafetyPolicy`, and the receiver
#: name varies by call site (`config`, `cfg`, `policy`), so the walk keys on the
#: attribute rather than on any one dotted spelling.
DRY_RUN_NAMES: Final = frozenset({"dry_run"})


def _mentions_dry_run(node: ast.AST) -> bool:
    """Does this expression read a ``dry_run`` flag anywhere inside it?"""
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr in DRY_RUN_NAMES:
            return True
        if isinstance(child, ast.Name) and child.id in DRY_RUN_NAMES:
            return True
    return False


def _parent_map(tree: ast.Module) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _guarding_conditions(node: ast.AST, parents: dict[int, ast.AST]) -> list[ast.AST]:
    """Every condition that must hold for *node* to be evaluated.

    Walks up the parent chain and collects the test of each enclosing ``if``
    (only when *node* really is in a branch of it, never when it is inside the
    test itself), plus ``a if C else b`` and the short-circuit operands of
    ``and``/``or``. Those three are the whole grammar for "this call is
    conditional" in an expression-or-statement position.
    """
    conditions: list[ast.AST] = []
    current: ast.AST | None = node
    while current is not None:
        parent = parents.get(id(current))
        if parent is None:
            break
        if isinstance(parent, ast.If) and current is not parent.test:
            conditions.append(parent.test)
        elif isinstance(parent, ast.IfExp) and current is not parent.test:
            conditions.append(parent.test)
        elif isinstance(parent, ast.BoolOp):
            index = parent.values.index(current) if current in parent.values else 0
            conditions.extend(parent.values[:index])
        current = parent
    return conditions


def scan_dry_run_bypass(source: str, module: str) -> list[Boundary]:
    """Calls to the confirmation gate that a ``dry_run`` condition can skip."""
    tree = ast.parse(source, filename=module)
    parents = _parent_map(tree)
    found: list[Boundary] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if dotted(node.func).split(".")[-1] != CONFIRMATION_CALL:
            continue
        for condition in _guarding_conditions(node, parents):
            if _mentions_dry_run(condition):
                found.append(
                    Boundary(
                        module,
                        node.lineno,
                        CONFIRMATION_CALL,
                        KIND_DRY_RUN_BYPASS,
                        "the confirmation gate is guarded by a dry_run condition "
                        "(OR-7: a dry run must PREDICT the refusal, exit 5)",
                    )
                )
                break
    return found


def scan_confirmation_calls(root: Path) -> list[Boundary]:
    found: list[Boundary] = []
    for path in iter_python_files(root):
        module = module_name(path, root)
        found.extend(scan_dry_run_bypass(path.read_text(), module))
    return found


def _confirmation_call_sites(root: Path) -> list[str]:
    """Every module under *root* that calls the gate at all."""
    sites: list[str] = []
    for path in iter_python_files(root):
        module = module_name(path, root)
        tree = ast.parse(path.read_text(), filename=module)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and dotted(node.func).split(".")[-1] == CONFIRMATION_CALL:
                sites.append(f"{module}:{node.lineno}")
    return sites


def test_no_dry_run_guard_wraps_the_confirmation_gate() -> None:
    found = scan_confirmation_calls(SRC)
    listed = "\n".join(f"  - {item}" for item in found)
    assert found == [], (
        "`--dry-run` awareness belongs to `safety/confirm.py::require_confirmation` "
        "alone (B-093 / OR-7); a caller must reach it on every destructive path:\n"
        f"{listed}"
    )


def test_the_walk_actually_finds_the_confirmation_call_sites() -> None:
    """Non-vacuity. A green Section 4 over zero call sites proves nothing -- the
    same trap `DESTRUCTIVE` sat in from PDF-06 to PDF-14 (B-079)."""
    sites = _confirmation_call_sites(SRC)
    assert len(sites) >= 10, f"Section 4 found only {len(sites)} call site(s): {sites}"


PLANTED_SECTION_4: Final = (
    (
        "plant-the-original-b093-guard",
        "pdf_tooling/cli/cmd_sneaky.py",
        "from pdf_tooling.safety.confirm import require_confirmation\n\n\n"
        "def go(config):\n"
        "    if not config.dry_run and config.in_place:\n"
        "        require_confirmation(config.safety, input_count=2, in_place=True,\n"
        "                             rerun_hint='x')\n",
    ),
    (
        "plant-a-nested-guard",
        "pdf_tooling/cli/cmd_nested.py",
        "from pdf_tooling.safety import confirm\n\n\n"
        "def go(config):\n"
        "    if config.in_place:\n"
        "        if config.dry_run:\n"
        "            return\n"
        "        else:\n"
        "            confirm.require_confirmation(config.safety, input_count=2,\n"
        "                                         in_place=True, rerun_hint='x')\n",
    ),
    (
        "plant-a-short-circuit-guard",
        "pdf_tooling/cli/cmd_shortcircuit.py",
        "from pdf_tooling.safety.confirm import require_confirmation\n\n\n"
        "def go(cfg):\n"
        "    cfg.dry_run or require_confirmation(cfg.safety, input_count=2,\n"
        "                                        in_place=True, rerun_hint='x')\n",
    ),
    (
        "plant-a-ternary-guard",
        "pdf_tooling/cli/cmd_ternary.py",
        "from pdf_tooling.safety.confirm import require_confirmation\n\n\n"
        "def go(policy, cfg):\n"
        "    return None if policy.dry_run else require_confirmation(\n"
        "        policy, input_count=2, in_place=True, rerun_hint='x')\n",
    ),
)


@pytest.mark.parametrize(
    ("label", "relative", "source"),
    PLANTED_SECTION_4,
    ids=[row[0] for row in PLANTED_SECTION_4],
)
def test_a_planted_section_4_violation_fails_the_walk(
    label: str,
    relative: str,
    source: str,
    tmp_path: Path,
) -> None:
    """Copy src/, plant one dry-run-guarded gate call, confirm Section 4 reddens.

    The first row is the ORIGINAL B-093 defect, verbatim -- the cheapest way to
    show this instrument detects a case already known to have happened.
    """
    scratch = tmp_path / "src"
    shutil.copytree(SRC, scratch)
    planted = scratch / relative
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(source)

    found = scan_confirmation_calls(scratch)
    assert found, f"Section 4 did not notice the planted violation: {label}"


BENIGN_SECTION_4 = '''
"""A module that talks about dry_run near the gate without guarding it.

`if not config.dry_run and config.in_place:` in prose is not a guard.
"""

from pdf_tooling.safety.confirm import require_confirmation


def go(config):
    if config.dry_run:
        note = "planning only"
    else:
        note = "writing"
    if config.in_place:
        require_confirmation(config.safety, input_count=2, in_place=True, rerun_hint=note)
'''


def test_benign_section_4_mentions_are_never_flagged() -> None:
    """A sibling `if config.dry_run:` branch, and the defect's own text quoted in
    a docstring, are not bypasses -- the mechanized proof that Section 4 is an
    AST walk and not a text grep, matching Sections 1-3's negative-control
    discipline."""
    found = scan_dry_run_bypass(BENIGN_SECTION_4, "pdf_tooling.cli.cmd_benign")
    assert found == [], f"false positives: {[str(item) for item in found]}"


# --------------------------------------------------------------------------- #
# PDF-19 — Section 4 re-derivation: reachability, not just non-bypass.
#
# The walk above forbids a `dry_run`-guarded call. It CANNOT see an ABSENT one,
# and its non-vacuity floor (`>= 10` sites) is satisfied by fifteen whatever
# happens to the sixteenth verb. Measured at 7522e3e: **15 call sites** across
# fifteen `cli/cmd_*.py` modules, and **12** `cmd_*` modules that call the gate
# zero times. Four of those twelve are `{PDF...}` multi-input producers that
# consume output-directory flags -- `extract`, `rasterize`, `tables`, `text` --
# so `bulk` is reachable for them and `destructive` is the open question.
#
# WHETHER THOSE FOUR SHOULD GATE IS **B-022 ≡ B-045**, deferred by
# `roadmap.md` §5 behind `PDF-18`'s unified planner. This section does not
# decide it. What it does is make the absence an ENTRY A REVIEWER SEES rather
# than a silence nobody counts -- the same idiom `ALLOWED_WRITE_SITES` uses one
# section up, for the same reason.
# --------------------------------------------------------------------------- #

#: Modules that do NOT call the confirmation gate, each with the reason it does
#: not. Shape mirrors `ALLOWED_WRITE_SITES`: an entry is a deliberate exception
#: with a stated reason, checked for staleness, living in the test module rather
#: than as an inline pragma in the source.
GATE_EXEMPT: Final[frozenset[tuple[str, str]]]
GATE_EXEMPT = frozenset(
    {
        # reason: non-producing. `version` writes nothing and takes no input.
        ("pdf_tooling.cli.cmd_version", "non-producing"),
        # reason: non-producing. `doctor` reports engine availability.
        # (Its `--dry-run` IMPURITY is a separate finding -- PDF-19's
        # README.md:74 census -- and is PDF-20's to characterize, B-075/B-100.)
        ("pdf_tooling.cli.cmd_doctor", "non-producing"),
        # reason: non-producing. `info` reads and reports.
        ("pdf_tooling.cli.cmd_info", "non-producing"),
        # reason: grouping parent only; it defines no verb callback of its own.
        ("pdf_tooling.cli.cmd_meta", "grouping parent"),
        # reason: non-producing. `meta get` reads the document information
        # dictionary; the mutating half is `meta set`, which DOES gate.
        ("pdf_tooling.cli.cmd_meta_get", "non-producing"),
        # reason: single-input ({PDF}), so `bulk = input_count > 1` is
        # unreachable and the gate could never fire.
        ("pdf_tooling.cli.cmd_permissions", "single-input"),
        # reason: single-input ({PDF}) producer. Same argument as permissions:
        # `split` fans one document out to many outputs, never many inputs in.
        ("pdf_tooling.cli.cmd_split", "single-input"),
        # reason: creates from {TEXT}, never from existing PDFs; a single
        # `--output` destination, protected by no-clobber rather than by a gate.
        ("pdf_tooling.cli.cmd_create", "non-pdf-input"),
        # reason: B-022 == B-045 -- OPEN. `{PDF...}` multi-input producer
        # consuming output-directory flags, so `bulk` IS reachable. Whether an
        # output-shaped producer is "destructive" is the deferred question.
        ("pdf_tooling.cli.cmd_extract", "B-022 == B-045 (deferred)"),
        # reason: B-022 == B-045 -- OPEN. Same shape as extract.
        ("pdf_tooling.cli.cmd_rasterize", "B-022 == B-045 (deferred)"),
        # reason: B-022 == B-045 -- OPEN. Same shape as extract.
        ("pdf_tooling.cli.cmd_tables", "B-022 == B-045 (deferred)"),
        # reason: B-022 == B-045 -- OPEN. Same shape as extract.
        ("pdf_tooling.cli.cmd_text", "B-022 == B-045 (deferred)"),
    }
)


def _cli_command_modules(root: Path) -> list[str]:
    """Every `cli/cmd_*.py` module under *root*, dotted."""
    cli = root / "pdf_tooling" / "cli"
    return sorted(module_name(path, root) for path in cli.glob("cmd_*.py"))


def gate_reachability(root: Path) -> tuple[list[str], list[str]]:
    """(modules that neither call the gate nor are exempt, stale exemptions)."""
    calling = {site.split(":")[0] for site in _confirmation_call_sites(root)}
    exempt = {module for module, _ in GATE_EXEMPT}
    unaccounted = sorted(m for m in _cli_command_modules(root) if m not in calling | exempt)
    stale = sorted(exempt & calling)
    return unaccounted, stale


def test_every_cli_command_either_gates_or_is_exempt_with_a_reason() -> None:
    """An absent gate becomes visible instead of silent.

    Red (observed, PDF-19): delete the `require_confirmation(...)` call from
    `cli/cmd_delete.py` in a scratch copy of `src/` and this fails naming
    `pdf_tooling.cli.cmd_delete`.
    """
    unaccounted, _ = gate_reachability(SRC)
    assert unaccounted == [], (
        "these cli/cmd_*.py modules neither call require_confirmation nor carry a "
        f"GATE_EXEMPT entry: {unaccounted}. Section 4's walk forbids a dry_run-GUARDED "
        "call and cannot see an ABSENT one -- add the call, or add an exemption with a "
        "'# reason:' naming the filed finding"
    )


def test_no_gate_exemption_is_stale() -> None:
    """Exemption rot, the same failure mode `test_no_allowlist_entry_is_stale`
    exists for: an entry outliving the absence it excused."""
    _, stale = gate_reachability(SRC)
    assert stale == [], (
        f"GATE_EXEMPT entries for modules that DO call the gate now: {stale}; remove the exemption"
    )


def test_every_gate_exemption_carries_a_reason_comment() -> None:
    """The `# reason:` comment is mandatory, exactly as it is for the two write
    allowlists. Counted against the entries so a copied block cannot drift."""
    source = Path(__file__).read_text()
    start = source.index("GATE_EXEMPT = frozenset(")
    end = source.index("def _cli_command_modules", start)
    block = source[start:end]
    assert block.count("# reason:") == len(GATE_EXEMPT), (
        f"GATE_EXEMPT has {len(GATE_EXEMPT)} entries but {block.count('# reason:')} "
        "'# reason:' comments"
    )


def test_the_gate_reachability_helper_actually_finds_the_modules() -> None:
    """Non-vacuity for the helper itself: an empty module list would make both
    assertions above pass by iterating nothing -- Section 4's own `>= 10` floor,
    one level down."""
    modules = _cli_command_modules(SRC)
    assert len(modules) >= 20, f"only {len(modules)} cli/cmd_*.py module(s) found"
    assert "pdf_tooling.cli.cmd_delete" in modules


# --------------------------------------------------------------------------- #
# Section 5 -- no local filesystem-tier refusal construction under `ops/`
# (PDF-18 Design D9)
#
# APPENDED, never rewritten, per this file's own header rule; it reuses
# `iter_python_files`, `module_name` and `Boundary` rather than starting a
# fifth walk.
#
# THE DEFECT THIS EXISTS FOR. Eight `ops/` modules each defined their own
# `_plan_filesystem`/`_FilesystemPlan` before PDF-18 unified them into
# `safety.atomic.plan_filesystem`. `tests/unit/test_metadata.py`'s own
# `test_ac21_meta_set_calls_plan_output_set_not_a_local_refusal` protected
# exactly ONE of those eight files with a string-literal pin -- a real
# invariant ("route through the shared primitive; never hand-roll a local
# refusal") wearing a fragile, single-module form. PDF-18 Design D9
# generalises it: the invariant is now that NO module under `ops/` may even
# NAME `DestinationUnwritableError` or `TargetExistsError` -- the two
# filesystem-tier refusal classes `safety.atomic.plan_filesystem` already
# constructs -- because a verb author who imports one to build a local
# refusal has, by definition, stopped consuming the shared planner's own
# `.refusal`. This is the *protected by construction* form the common brief
# calls for: a string pin on one file protects one file; the AST guard below
# protects the eight that just had their planner taken away, and it is what
# stops copy nine.
#
# AST, not grep, for the reason every other section here is: "raise
# DestinationUnwritableError" could equally be prose in a docstring (as
# several of the eight modules' own module docstrings demonstrate, quoting
# the class name while explaining why they do NOT construct one), and a text
# scan cannot tell the difference.
# --------------------------------------------------------------------------- #

KIND_OPS_LOCAL_REFUSAL: Final = "ops-local-filesystem-refusal-name"

#: The two filesystem-tier refusal classes `safety.atomic.plan_filesystem`
#: already constructs (PDF-18 Design D4/D9). No module under `ops/` may name
#: either one -- importing, isinstance-checking or raising it locally is all
#: the same violation: reaching past the shared planner to build (or inspect
#: the identity of) its own refusal.
#:
#: PDF-38 adds the third. `BackupExistsError` is now constructed in exactly two
#: places -- `safety.paths.ensure_backup_sidecar_free` (the read-only tier
#: `plan_filesystem` calls) and `AtomicWriter._make_backup` (the writer's own
#: raise, kept deliberately: the sidecar can appear between plan and commit, so
#: deleting it would trade defence in depth for a TOCTOU window). Two raise
#: sites for one condition is the intended end state; this token is what stops
#: an `ops/` module becoming the third.
FORBIDDEN_OPS_REFUSAL_NAMES: Final = frozenset(
    {"BackupExistsError", "DestinationUnwritableError", "TargetExistsError"}
)


def scan_local_refusal_names(source: str, module: str) -> list[Boundary]:
    """Every mention of a forbidden refusal class name in *source*'s AST --
    an import, a qualified attribute access, or a bare name -- never a
    prose mention (those live in ``ast.Constant`` string nodes this walk
    never visits)."""
    tree = ast.parse(source, filename=module)
    found: list[Boundary] = []
    for node in ast.walk(tree):
        name: str | None = None
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_OPS_REFUSAL_NAMES:
            name = node.id
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_OPS_REFUSAL_NAMES:
            name = node.attr
        elif isinstance(node, ast.alias) and node.name in FORBIDDEN_OPS_REFUSAL_NAMES:
            name = node.name
        if name is not None:
            found.append(
                Boundary(
                    module,
                    getattr(node, "lineno", 0),
                    name,
                    KIND_OPS_LOCAL_REFUSAL,
                    "the filesystem-tier refusal classes belong to "
                    "safety.atomic.plan_filesystem alone (PDF-18 Design D9); a verb "
                    "module must consume the plan's own `.refusal`, never name "
                    f"{name!r} itself",
                )
            )
    return found


def scan_ops_local_refusal_names(root: Path) -> list[Boundary]:
    """Every Section 5 finding under ``root/pdf_tooling/ops``.

    *root* is the ``src/`` directory to scan -- either :data:`SRC` itself or a
    scratch copy of it, mirroring every other section's ``scan_*(root)``
    shape.
    """
    ops_root = root / "pdf_tooling" / "ops"
    found: list[Boundary] = []
    for path in iter_python_files(ops_root):
        module = module_name(path, root)
        found.extend(scan_local_refusal_names(path.read_text(), module))
    return found


def test_no_ops_module_names_a_filesystem_tier_refusal_class() -> None:
    found = scan_ops_local_refusal_names(SRC)
    listed = "\n".join(f"  - {item}" for item in found)
    assert found == [], (
        "DestinationUnwritableError/TargetExistsError belong to "
        "safety.atomic.plan_filesystem alone; a verb module must consume the "
        f"plan's own `.refusal`, never construct or import the class itself:\n{listed}"
    )


def test_the_ops_package_actually_contains_python_files() -> None:
    """Non-vacuity. A green Section 5 over zero files proves nothing -- the
    same trap every other section's own non-vacuity test exists to catch."""
    files = iter_python_files(SRC / "pdf_tooling" / "ops")
    assert len(files) >= 8, f"Section 5 found only {len(files)} file(s) under ops/"


PLANTED_SECTION_5: Final = (
    (
        "plant-a-raised-destination-unwritable",
        "pdf_tooling/ops/sneaky_refusal.py",
        "from pdf_tooling.errors import DestinationUnwritableError\n\n\n"
        "def go(target):\n"
        "    raise DestinationUnwritableError('nope', path=str(target))\n",
    ),
    (
        "plant-a-bare-target-exists-import",
        "pdf_tooling/ops/sneaky_import.py",
        "from pdf_tooling.errors import TargetExistsError\n\n\n"
        "def check(refusal):\n"
        "    return isinstance(refusal, TargetExistsError)\n",
    ),
    (
        "plant-a-qualified-reference",
        "pdf_tooling/ops/sneaky_qualified.py",
        "from pdf_tooling import errors\n\n\n"
        "def label(refusal):\n"
        "    return type(refusal) is errors.DestinationUnwritableError\n",
    ),
    # PDF-38's own token, proven rather than added on trust. `ops/crypto.py`
    # already MENTIONS `BackupExistsError` in a docstring (explaining why it
    # does not construct one), so this row and
    # `test_benign_section_5_mentions_are_never_flagged` together are what show
    # Section 5 tells a raise from prose for the new name too.
    (
        "plant-a-raised-backup-exists",
        "pdf_tooling/ops/sneaky_sidecar.py",
        "from pdf_tooling.errors import BackupExistsError\n\n\n"
        "def go(sidecar):\n"
        "    raise BackupExistsError('nope', path=str(sidecar))\n",
    ),
)


@pytest.mark.parametrize(
    ("label", "relative", "source"),
    PLANTED_SECTION_5,
    ids=[row[0] for row in PLANTED_SECTION_5],
)
def test_a_planted_section_5_violation_fails_the_walk(
    label: str,
    relative: str,
    source: str,
    tmp_path: Path,
) -> None:
    """Copy src/, plant one refusal-class mention under ops/, confirm Section 5
    turns red."""
    scratch = tmp_path / "src"
    shutil.copytree(SRC, scratch)
    planted = scratch / relative
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(source)

    found = scan_ops_local_refusal_names(scratch)
    assert found, f"Section 5 did not notice the planted violation: {label}"


BENIGN_SECTION_5 = '''
"""A module that talks ABOUT the refusal classes without naming them as code.

DestinationUnwritableError, TargetExistsError and BackupExistsError are
mentioned here only in prose, exactly the way this docstring does it right now
-- that is not what Section 5 forbids, and `ops/crypto.py`'s own docstring
mentions the third one for real.
"""

from pdf_tooling.safety.atomic import plan_filesystem


def go(targets, out_dir, policy):
    plan = plan_filesystem(targets, out_dir=out_dir, policy=policy, kind="pdf")
    if plan.refusal is not None:
        raise plan.refusal
    return plan
'''


def test_benign_section_5_mentions_are_never_flagged() -> None:
    """A docstring quoting both forbidden class names, and ordinary consumption
    of `plan.refusal`, are not violations -- the mechanized proof that Section 5
    is an AST walk and not a text grep, matching Sections 1-4's negative-control
    discipline."""
    found = scan_local_refusal_names(BENIGN_SECTION_5, "pdf_tooling.ops.benign")
    assert found == [], f"false positives: {[str(item) for item in found]}"


# --------------------------------------------------------------------------- #
# Section 6 -- what `pdftooling --help` IMPORTS (PDF-29)
#
# APPENDED, never rewritten; Section 6 is the next free integer at this commit
# (1 PDF-04, 2 PDF-05, 3 PDF-06, 4 B-093, 5 PDF-20), taken by re-reading the
# file rather than from a spec, per the append-only rule this file opens with.
#
# WHY THIS SECTION EXISTS, AND WHAT IT REPLACES.
#
# `PLAN §12 R-13` is a claim about `--help` STARTUP LATENCY, and until PDF-29 it
# was held by exactly one control: a wall-clock assertion in
# tests/test_cli_spine.py. That control has a defect no threshold can fix. Its
# own measured distribution on a host VERIFIED QUIET -- 20 independent
# fastest-of-5 trials -- was min 219.7 / median 235.8 / p95 247.9 / max 248.0 ms
# with a SPREAD OF 28.3 ms, against a 250 ms budget. **A best-of-5 estimator
# whose dispersion is thirteen times its headroom flakes by construction**, on a
# quiet host as much as a loaded one, which is what happened to three different
# agents in one day and to `test (3.12, macos-14)` in run 33721445070.
#
# And under `-n auto` (this project's default since PDF-29) it cannot even
# abstain honestly and still run: eight workers saturate the box by
# construction, so the wall-clock test SKIPS on every worker and therefore
# **does not run in CI at all**. A control that silently stops running is the
# exact class this cycle exists to end, so it is not left implied: THIS SECTION
# IS WHAT RUNS INSTEAD, on every leg of every CI job.
#
# WHY IMPORT SET IS THE RIGHT SUBSTITUTE. Startup latency in a Python CLI is
# dominated by module import, and the import SET is deterministic, load-immune
# and parallel-safe -- none of which wall-clock is. It cannot tell you the
# milliseconds, and it is not trying to; it tells you the thing that MOVES the
# milliseconds, which is the only half of the claim a suite can hold honestly.
#
# WHAT IT CATCHES THAT SECTION 2 AND `ENGINE_MODULES` CANNOT. Section 2's walk
# and `tests/test_cli_spine.py::test_no_engine_library_is_imported_at_module_-
# scope` both check a NAMED list of six-to-eight engine libraries. This section
# names no list of offenders: it pins the set of non-stdlib packages that
# `--help` actually pulls in, so a new eager import of ANY third-party package
# reddens -- `hypothesis`, `requests`, `numpy`, `pkg_resources`, anything. The
# proof of non-duplication is mechanized below: the planted module is
# deliberately NOT in `ENGINE_MODULES`, and the test asserts the engine control
# stays GREEN on the very tree this section turns red.
#
# WHAT THE PIN RECORDS TODAY, and it is not a flattering picture -- the numbers
# below are a MEASUREMENT of the product as it is, not an endorsement of it:
#   * **PIL** is eager, dragging in `defusedxml`. Pillow is deliberately NOT an
#     engine module (`test_pillow_is_deliberately_not_an_engine_module`), so
#     nothing shipped before this section could see it. The single module-scope
#     `PIL` import site under `src/` is **`pdf_tooling/ops/compose.py:90`**,
#     reached from `--help` via `cli.main` -> `cli.cmd_compose` -> `ops.compose`.
#     That site is DERIVED, not transcribed, by
#     `test_pil_has_exactly_one_module_scope_import_site_under_src` below --
#     PDF-42 found this line previously blamed `cli.common`, which contains no
#     `PIL` token at all and never did (`git log -S PIL -- .../cli/common.py` is
#     empty). A comment is one more hand-maintained claim; this one is now a
#     test.
#   * **email** is eager, but NOT via `pdf_tooling.ops.textract` -- that module
#     contains no `email` token at any indentation, and never did. Measured with
#     `python -X importtime`, `email` and `email.message` arrive under
#     `importlib.metadata` (through `importlib.metadata._adapters`), which
#     `pdf_tooling.cli.cmd_version` imports. The cause is named here only
#     because it was measured; the previous attribution was not.
#   * `concurrent.futures` pulls in **multiprocessing**, which pulls in
#     **socket**.
# 280 modules are imported to print a help screen, over and above what a bare
# interpreter loads. Making any of those lazy is a
# `src/` change and is explicitly OUT of PDF-29's scope (Non-goals: not a
# performance-engineering project); it is REPORTED as a finding instead. What
# this section guarantees is that the number cannot quietly get worse.
# --------------------------------------------------------------------------- #


class ModuleImport(NamedTuple):
    """One `-X importtime` row: the module, its OWN import cost, and its subtree's.

    `self_us` is the column this section's latency half is built on. A
    module-scope `time.sleep(0.5)` lands ~500,000 us in the sleeping module's
    SELF column and leaves every other module's alone, which is precisely the
    signature an import-NAME census cannot see: the set does not change.
    """

    name: str
    self_us: int
    cumulative_us: int


class HelpImports(NamedTuple):
    """One `pdftooling --help` run's import census -- the names AND the times."""

    returncode: int
    total: int
    top_level: frozenset[str]
    non_stdlib: frozenset[str]
    #: Attributable module -> its own import cost in microseconds. Same key set
    #: as the count above, computed from the same baseline-subtracted rows, so
    #: the timing half can never disagree with the counting half about which
    #: modules it is describing.
    self_us_by_module: Mapping[str, int]
    #: Sum of the above. The second net, for a regression spread thinly.
    total_self_us: int
    #: PDF-68 D1/E7. The bare-interpreter floor census's NAME set -- the very
    #: set `attributable` is defined by subtracting. It is kept because the
    #: repeated readings below must partition the SAME rows this census did: a
    #: repetition that re-derived its own floor names from its own bare census
    #: could drift, and a numerator and a denominator drawn from two different
    #: partitions are describing two different programs (the failure
    #: `test_the_timing_census_is_not_vacuous` already refuses one level up).
    floor_names: frozenset[str]
    #: PDF-68 D1/E7 -- the DENOMINATOR, and it is the complement of a filter
    #: that already ran. `attributable` keeps the rows whose name is NOT in
    #: `floor_names`; this is the self-time sum of the rows it DISCARDS, from
    #: the SAME `--help` subprocess, the same scheduler window and the same
    #: coverage instrumentation as the numerator. It costs no new subprocess.
    #:
    #: WHY THIS QUANTITY AND NOT THE BARE CENSUS'S OWN SUM. `PDF-55` shipped
    #: `floor_self_us` (the `-c pass` process's self-time sum) for a candidate
    #: its campaign then rejected, and at `7e36649` NO assertion read it --
    #: a measurement moved from being discarded inside a function to being
    #: discarded inside a NamedTuple. It is retired here and replaced by the
    #: quantity measured in the numerator's OWN window, which is what makes
    #: contention cancel rather than merely correlate.
    in_run_floor_self_us: int


#: The console script under test. Deliberately the venv's own, by path: the
#: three-arm fallback in tests/test_cli_spine.py can resolve a globally
#: installed (possibly STALE) `pdftooling`, or the `-m` bootstrap, and an import
#: census taken from a different build is a census of a different program (C-4).
VENV_CONSOLE_SCRIPT: Final = REPO_ROOT / ".venv" / "bin" / "pdftooling"

#: Non-stdlib top-level packages `--help` is permitted to import, asserted as a
#: SUPERSET (a new name reddens; a name that disappears does not). The asymmetry
#: is deliberate: making an import lazy is the improvement this pin exists to
#: encourage, and a pin that reddened on an improvement would be widened or
#: deleted the first time someone made one.
#:
#: `org` appears only under 3.11 (`xml.sax` probing for the Jython runtime), and
#: `sitecustomize` only in environments that install one -- the baseline
#: subtraction cancels `sitecustomize` today, and it is left listed so an
#: environment where it does NOT cancel cannot produce a phantom red. Measured
#: on this host at 3.12.13 AND 3.11.15; the two differ by `org` alone, which is
#: why this is a superset check and not an equality one.
HELP_IMPORT_ALLOWLIST: Final = frozenset(
    {
        "pdf_tooling",
        "typer",
        "annotated_doc",  # typer's own
        "shellingham",  # typer's own
        "PIL",  # FINDING: eager, via pdf_tooling.ops.compose (measured)
        "defusedxml",  # FINDING: eager, dragged in by PIL
        "org",  # 3.11 only: xml.sax probing for Jython
        "sitecustomize",  # venv plumbing, not a product import
    }
)

#: Total modules (not top-level packages) `--help` imports BEYOND what a bare
#: interpreter loads in the same environment. Measured **280 on CPython 3.12.13
#: and 282 on 3.11.15** on this host; pinned at 320, roughly 13% of headroom, so
#: ordinary matrix variation across four Pythons and two operating systems
#: cannot redden it while a new eager subsystem still can -- the planted control
#: below moves it to 428.
#:
#: THIS IS A CEILING AND NEVER A FLOOR, deliberately. The subtraction can only
#: LOWER the attributable count (a module the environment loaded first is
#: credited to the environment), so under `make cover` -- where coverage.py
#: itself is loaded in both censuses and drags stdlib modules the CLI also uses
#: into the floor -- this number reads lower than 280. A lower reading can never
#: produce a false RED, which is the direction that matters for a control that
#: has to be trustworthy across eight matrix legs.
HELP_MODULE_CEILING: Final = 320


# --------------------------------------------------------------------------- #
# PDF-42 -- the TIME half, beside the import-SET half above
#
# The two constants below are CEILINGS on the `-X importtime` self-time columns
# that `_importtime_census` already collects. They are here because the set-half
# above is blind to latency BY CONSTRUCTION, and that blindness was measured
# rather than argued: a module-scope `time.sleep(0.5)` in
# `src/pdf_tooling/cli/common.py` moves `pdftooling --help` from 227.0 ms to
# 728.7 ms (min-of-5, quiet host) while the attributable module count stays at
# **282 -- a delta of exactly 0** -- and every assertion above stays green.
#
# BOTH ARE CEILINGS AND NEITHER IS A FLOOR, for the same reason
# `HELP_MODULE_CEILING` is: the baseline subtraction can only LOWER an
# attributable figure, so a low reading can never produce a false red, and that
# is the direction that matters across eight matrix legs.
#
# A WIDENED CEILING IS NEVER AN ACCEPTABLE RESPONSE TO A RED. If a future eager
# import pushes either statistic up, the admissible responses are to make the
# import lazy or to widen the constant WITH A FRESH MEASURED DISTRIBUTION
# RECORDED BESIDE IT -- the identical rule the allowlist above already imposes,
# for the identical reason: widening a pin without a measurement is how the
# wall-clock budget this section replaced came to be defended by nothing.
# `tests/test_gate_budget.py::test_the_pdf42_ceilings_carry_their_measurement`
# enforces exactly that, and it is not a formality.
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# PDF-55 -- the two absolutes above could not survive contention, so both are
# now RATIOS measured inside the SAME `--help` census.
#
# THE DEFECT, MEASURED RATHER THAN ARGUED. `TOTAL_IMPORT_US_CEILING` reddened on
# a BYTE-IDENTICAL, unmutated tree under ambient contention (loadavg 42-84:
# 2,350,905 / 3,445,048 / 4,431,015 us against its 2,000,000 ceiling) while
# staying GREEN on the very `time.sleep(0.15) x 5` plant PDF-42 shipped it for
# (897,000-928,230 us, quiet). Its dynamic range is INVERTED: the false
# positive is LARGER than the true positive. `MODULE_SELF_US_CEILING` reddened
# the same way in 2 of 3 trials at that same load (`pdf_tooling.models` at
# 309,277 and 401,360 against 250,000) -- BOTH shipped absolutes are
# load-fragile, not one, and neither defect is a tuning error: an absolute
# wall-clock-shaped quantity measured inside a suite that saturates its own
# box cannot separate "the product got slower" from "the box got busier".
#
# THE BASIS THAT SURVIVES IT (D1). Both statistics below are now a
# DIMENSIONLESS RATIO of two self-time sums taken from the SAME subprocess:
# `pdf_tooling.*` self time (the numerator a product-side regression enters)
# over every OTHER attributable module's self time (the denominator it cannot
# enter). Contention multiplies both sides together and cancels; a real
# regression moves the numerator alone. Measured cv under deliberate load
# (N=75, loadavg 22-66, this campaign): the RATIO's cv is 11.26% against the
# retired TOTAL absolute's 41.87% over the identical trials -- see
# `PRODUCT_IMPORT_RATIO_CEILING_PER_MILLE`'s own block below for the full
# distribution.
#
# `TOTAL_IMPORT_US_CEILING` IS RETIRED (D5/AC12), on PROVEN coverage transfer:
# the new ratio arm below reddens on both the thin five-module sleep plant
# (which the retired arm never could -- E3) and a gross-growth plant that
# exceeded the retired arm's own 2,000,000 us ceiling (so no coverage is lost).
# See the Implementation Log for both reds, recorded before this node was
# removed. `MODULE_SELF_US_CEILING` is KEPT AS A NODE -- it is the only arm
# that NAMES the offending module, which a ratio over the whole census cannot
# -- but its basis is RE-BASED to the same normalisation, never widened.
#
# DECLARED BLIND SPOTS (D7), stated so silent invisibility does not happen
# quietly:
#   1. An import-time regression INSIDE a third-party dependency enters the
#      DENOMINATOR, lowering both ratios -- this instrument is blind to it,
#      and it can partially MASK a simultaneous product-side regression.
#      Mitigation: third-party/stdlib growth is still held by
#      `HELP_IMPORT_ALLOWLIST` (names) and `HELP_MODULE_CEILING` (count), and a
#      dependency bump arrives with a `uv.lock` diff the licence/dependency
#      gates already see. A product-side regression arrives silently in an
#      ordinary commit, which is the case this ratio exists for.
#   2. Both statistics see COST, not CAUSE: a sleep, a network call, a large
#      file read and a heavy computation at module scope are indistinguishable
#      to a ratio -- correctly, since all four cost the same thing to a user in
#      a shell loop. `MODULE_SELF_US_CEILING`'s own per-module locator names
#      WHERE; nothing here claims to name WHY.
#   3. `time.sleep` is contention-invariant while its denominator dilates under
#      load, so the separation this basis offers DECAYS as ambient load rises
#      (measured: E9-shaped campaign, this architect, loaded arm N=75 spans
#      loadavg 22-66). It is graded at the project's DEFAULT `-n auto` (the
#      condition X-712 names), not at an artificially escalated loadavg; a
#      CPU-bound regression of the same wall-clock cost behaves in the OPPOSITE
#      direction and its separation GROWS with load, which is why AC1 drives
#      both plant shapes rather than the sleep alone.
#   4. PDF-68, AND IT IS THE ONE THAT ESCAPED. A DIFFUSE PROPORTIONAL SLOWDOWN
#      OF AN UNCHANGED IMPORT SET -- same count, same names, no single
#      dominator, product and non-product inflating TOGETHER -- is invisible to
#      both ratios above BY ALGEBRA rather than by threshold. Under
#      `t_m -> k*t_m` for every attributable module, `product/non-product`
#      reads `kA/kB = A/B` and `peak/non-product` reads `k*peak/kB`: both are
#      EXACTLY invariant, so no value of either ceiling could see it. That is
#      the ordinary shape of a dependency version bump, and it is NOT blind
#      spot 1 above: entry 1 describes growth landing in the denominator alone
#      (the ratio FALLS); this is growth landing on both sides in proportion
#      (the ratio does not move at all). Entry 1's mitigation does not cover it
#      either -- a `uv.lock` diff sees a VERSION change and is silent for a
#      transitive re-resolve, a wheel rebuild, an interpreter minor bump or a
#      platform change.
#      WHICH ARM HOLDS IT NOW: `test_total_startup_import_cost_stays_under_its_-
#      ceiling` below, whose denominator is the IN-RUN FLOOR -- rows the bare
#      interpreter also loads, measured in the numerator's own window, which a
#      product- or dependency-side import regression cannot enter. The class
#      moves the numerator alone, so the statistic moves with `k` exactly.
#      WHAT REMAINS BLIND: a proportional slowdown of the FLOOR ITSELF (an
#      interpreter or libc regression) inflates numerator and denominator
#      together and cancels here as contention does -- correctly, since this
#      instrument's proposition is about what the PRODUCT costs to start, not
#      what the machine costs to boot. And the arm bounds COST, not CAUSE, and
#      only above a MEASURED factor: see the constant's own block for the
#      sensitivity boundary, which is the honest statement of what it cannot
#      see.
#   5. PDF-68, and it is a LIMIT OF THE ARM ABOVE rather than of the basis.
#      Under `make cover`/`make ci`, coverage.py is injected into BOTH censuses
#      (`patch = ["subprocess"]`), so its ~144 modules join the floor name set
#      and its import cost joins the in-run floor DENOMINATOR -- measured at
#      this commit, denominator 8,564 -> 83,887 us and the statistic 16.5 ->
#      1.6062. The dilution is one-sided toward GREEN, so it can never produce
#      a false red, but the arm is roughly TEN TIMES LESS SENSITIVE in the
#      instrumented leg than in `make test`. Stated here because an instrument
#      that quietly stops being able to see is the exact defect this section
#      exists to end, and because the set-half already declares its own version
#      of this ("120, not 280") one screen up.
# --------------------------------------------------------------------------- #

#: PDF-55 D3. Below this, the ratio's denominator is not trusted -- roughly a
#: fifth of the bare-interpreter floor's own typical reading (E6: 8,606-10,214
#: us over three quiet trials on this host) -- so a genuinely broken census (a
#: `--help` that never reached the real path, or a classification bug that
#: swept nearly everything into "product") RAISES rather than dividing.
#: `parse_importtime_row`'s own precedent is the model: do not let the
#: instrument report a plausible-looking answer on data it could not read.
DENOMINATOR_SANITY_FLOOR_US: Final = 2_000


class ImportPartition(NamedTuple):
    """`self_us_by_module`, split into `pdf_tooling.*` (the numerator a
    product-side regression can enter) and everything else (the denominator it
    cannot) -- D1's two halves, partitioning the SAME attributable set the
    count already describes so the ratio can never disagree with the count
    about which modules it means."""

    product_modules: frozenset[str]
    non_product_modules: frozenset[str]
    product_self_us: int
    non_product_self_us: int


def assert_partition_valid(
    product: frozenset[str], non_product: frozenset[str], universe: frozenset[str]
) -> None:
    """D3. *product* and *non_product* must partition *universe* -- no
    overlap, no remainder -- or a classification bug could silently move cost
    from one side to the other without either the count or this ratio ever
    noticing. Called by `partition_by_product` on every real census (defence
    in depth) and directly, with a hand-built bad partition, by this section's
    own red controls -- `partition_by_product`'s own subtraction cannot itself
    produce an overlap, so the only way to prove this assertion fires is to
    hand it two populations computed two different ways, the same shape as
    `test_a_malformed_timing_column_raises_rather_than_reading_as_zero`'s
    direct call into `parse_importtime_row`.
    """
    overlap = product & non_product
    assert overlap == frozenset(), (
        f"module(s) classified as BOTH product and non-product: {sorted(overlap)}. A "
        "classification bug that double-counts (or that lets a module escape both "
        "buckets) would silently move cost between the numerator and the denominator -- "
        "the exact false-positive class this ratio exists to end."
    )
    covered = product | non_product
    assert covered == universe, (
        f"the partition does not cover the attributable set. missing="
        f"{sorted(universe - covered)} extra={sorted(covered - universe)}"
    )


def partition_by_product(self_us_by_module: Mapping[str, int]) -> ImportPartition:
    """Split *self_us_by_module* into `pdf_tooling.*` and everything else."""
    universe = frozenset(self_us_by_module)
    product = frozenset(name for name in universe if name.split(".")[0] == "pdf_tooling")
    non_product = universe - product
    assert_partition_valid(product, non_product, universe)
    return ImportPartition(
        product_modules=product,
        non_product_modules=non_product,
        product_self_us=sum(self_us_by_module[name] for name in product),
        non_product_self_us=sum(self_us_by_module[name] for name in non_product),
    )


def checked_denominator(partition: ImportPartition) -> int:
    """*partition*'s denominator, or a raise naming the reading (D3).

    A ratio whose denominator collapses toward zero manufactures an
    arbitrarily large red -- a false positive produced by the INSTRUMENT
    itself, which is the exact class this statistic exists to end. A bad
    denominator FAILS rather than normalising quietly.
    """
    if not partition.non_product_modules or partition.non_product_self_us <= 0:
        raise AssertionError(
            f"the ratio's denominator (non-product attributable self time) is "
            f"{partition.non_product_self_us} us over "
            f"{len(partition.non_product_modules)} module(s) -- refusing to divide. Either "
            "the probe did not reach the real `--help` path, or the product/non-product "
            "split misclassified the whole census."
        )
    if partition.non_product_self_us < DENOMINATOR_SANITY_FLOOR_US:
        raise AssertionError(
            f"the ratio's denominator read {partition.non_product_self_us} us, under the "
            f"{DENOMINATOR_SANITY_FLOOR_US} us sanity floor -- this is not a live "
            "denominator, so no ratio is computed from it."
        )
    return partition.non_product_self_us


#: No single attributable module's self time, AS A SHARE OF the non-product
#: attributable self time measured in the SAME census, may exceed this.
#: Expressed as an integer x1000 (a per-mille) so `ceiling_block()`'s existing
#: integer-literal parser (`tests/test_gate_budget.py`) needs no change: `470`
#: means the ratio must not exceed `0.470`.
#:
#: RE-BASED FROM `MODULE_SELF_US_CEILING` (an absolute microsecond figure,
#: retired by this block): D5 keeps this test as a NODE -- it is the only arm
#: that NAMES the offending module -- but its basis is now the same
#: normalisation the ratio below uses, because the absolute reddened on a
#: byte-identical tree under load (E4: 2 of 3 trials at loadavg 77-84,
#: `pdf_tooling.models` at 309,277 and 401,360 against 250,000).
#:
#: STATISTIC: max over modules of (per-module self time / non-product
#:   attributable self time), from ONE `pdftooling --help` `-X importtime`
#:   run, baseline-subtracted.
#: DATE: 2026-09-12
#: COMMIT: 46c5ac2 (measured on the working tree at that commit)
#: HOST: station-01, 8 logical CPUs, Linux.
#: INTERPRETER: CPython 3.12.13 (`uv run python -V`)
#: ENGINES: all six present -- pypdf 6.16.2 / pypdfium2 5.13.0 / reportlab
#:   5.0.1 / pdfplumber 0.11.10 / tesseract 5.5.0 / soffice 26.2.5.2
#:
#: Figures are `peak module self / non-product attributable self`, unitless.
#:   serial (bare repeated subprocess, no xdist, N=12, loadavg <1):
#:     min 0.1087  median 0.1113  p95 0.1247  max 0.1352  spread 0.0264  cv 6.58%
#:   `-n auto` (ambient, this project's own workers, N=12, loadavg 13-27):
#:     min 0.0681  median 0.1051  p95 0.1328  max 0.1747  spread 0.1066  cv 25.23%
#:   deliberate ambient load (N=75, loadavg 22-66; N independent CPU-bound
#:   busy-loop processes, 3x-8x nproc, killed by process group afterwards):
#:     min 0.0680  median 0.1227  p95 0.1559  max 0.1679  spread 0.1000  cv 17.16%
#: `-n auto` and serial both named per PDF42_DERIVATION_TOKENS.
#:
#: FACTOR: 3.0x the deliberately-loaded arm's p95 (0.1559), rounded to 0.470.
#: The loaded arm governs (D2 rule 3): a contended box is the condition the
#: assertion actually runs in.
#: SEPARATION: see the Implementation Log for the AC1 plant campaign under the
#: project's DEFAULT `-n auto` (not the deliberately-escalated regime above --
#: E9 Finding 3 measured that a sleep plant's separation DECAYS as load rises,
#: so direction (a) is graded at the shipped condition, per D7 blind spot 3).
MODULE_SELF_RATIO_CEILING_PER_MILLE: Final = 470

#: `pdf_tooling.*` self time, AS A SHARE OF the non-product attributable self
#: time measured in the SAME census. Replaces `TOTAL_IMPORT_US_CEILING`
#: (retired above), which reddened on a byte-identical tree under contention
#: while staying green on the plant it shipped for (D5/AC12; see the retiring
#: block's header for the figures). Expressed as an integer x1000 (a
#: per-mille), for the same reason as the constant above: `2_600` means the
#: ratio must not exceed `2.600`.
#:
#: STATISTIC: sum of `pdf_tooling.*` self time / sum of every OTHER
#:   attributable module's self time, from ONE `pdftooling --help`
#:   `-X importtime` run, baseline-subtracted (D1). Recommended PRIMARY over
#:   `peak/total` (X-557, rejected: denominator contains the regression) and
#:   `total/floor` (rejected: the floor denominator is small and dispersed) --
#:   see the Implementation Log's AC5 campaign for all three, measured.
#: DATE: 2026-09-12
#: COMMIT: 46c5ac2 (measured on the working tree at that commit)
#: HOST: station-01, 8 logical CPUs, Linux.
#: INTERPRETER: CPython 3.12.13 (`uv run python -V`)
#: ENGINES: all six present (as above)
#:
#: Figures are `product self / non-product attributable self`, unitless.
#:   serial (bare repeated subprocess, no xdist, N=12, loadavg <1):
#:     min 0.7192  median 0.8393  p95 0.8991  max 0.9141  spread 0.1949  cv 5.64%
#:   `-n auto` (ambient, this project's own workers, N=12, loadavg 13-27):
#:     min 0.5749  median 0.7304  p95 0.9111  max 0.9354  spread 0.3605  cv 15.57%
#:   deliberate ambient load (N=75, loadavg 22-66; N independent CPU-bound
#:   busy-loop processes, 3x-8x nproc, killed by process group afterwards):
#:     min 0.5456  median 0.8584  p95 1.0406  max 1.1570  spread 0.6115  cv 11.26%
#: `-n auto` and serial both named per PDF42_DERIVATION_TOKENS.
#:
#: FACTOR: 2.5x the deliberately-loaded arm's p95 (1.0406), rounded to 2.600.
#: The loaded arm governs (D2 rule 3), same reasoning as the constant above.
#: SEPARATION: see the Implementation Log's AC1/AC3 evidence. On the SAME
#: deliberately-loaded trials that produced the distribution above, the
#: RETIRED `total_self_us` absolute reddened 4 of 75 times against its
#: 2,000,000 us ceiling (max observed 2,835,898 us) while this ratio's max
#: over the identical trials was 1.1570, under its 2.600 ceiling throughout --
#: the AC3 demonstration this constant's own block exists to carry.
PRODUCT_IMPORT_RATIO_CEILING_PER_MILLE: Final = 2_600


# --------------------------------------------------------------------------- #
# PDF-68 -- the TOTAL half, which BOTH ratios above are blind to by algebra
#
# THE DEFECT, STATED AS ALGEBRA RATHER THAN AS AN OPINION. After PDF-55 retired
# `TOTAL_IMPORT_US_CEILING`, no arm that RUNS BY DEFAULT bounded total startup
# import cost. The four surviving default-running arms hold four propositions
# and none of them is that one: the allowlist holds NAMES, the count ceiling
# holds COUNT, and both ratios above are exactly invariant under a uniform
# proportional inflation of the census (see DECLARED BLIND SPOT 4). The only
# surviving absolute, `STARTUP_BUDGET_MS` in tests/test_cli_spine.py, abstains
# on every xdist worker BY DESIGN and `-n auto` is this project's default -- so
# it never runs here and never runs in CI. That abstention is CORRECT and is
# untouched by this block: the answer to a control that must abstain is a
# control that does not have to.
#
# THE BASIS (D1). The denominator must be measured in the SAME window (so
# contention still cancels) and must be a quantity the regression CANNOT ENTER
# (so the class still moves the numerator). The in-run floor is exactly that
# and it is free: `probe_help_imports` already computes `floor_names` and
# already throws away the rows that match it. Counting the product's total
# import cost in units of a CONTROL WORKLOAD, rather than in microseconds, is
# what makes this arm load-immune without ever asking how busy the box is --
# which it may not do anyway (`tests/test_gate_budget.py::LOAD_SENSING_NAMES`).
#
# WHY NOT A WIDER ABSOLUTE. Re-deriving the retired absolute at a wider ceiling
# is the forbidden move twice over -- it is a guard that goes green because a
# constant moved, and it is the defect PDF-55 measured. It is also INEFFECTIVE,
# and this campaign measured by how much: see the C3 row below.
# --------------------------------------------------------------------------- #

#: PDF-68 D3. Readings per evaluation. The arm reds only on a STRICT MAJORITY
#: of these (3 of 5), which is the same predicate as "the median of K readings
#: exceeds the ceiling" -- the quorum form is used because
#: `"k of K readings exceeded C (readings: ...)"` localises for a reader and a
#: single derived number does not.
#:
#: K WAS MEASURED, NOT CHOSEN. Dispersion of the median-of-K over the 50
#: deliberately-loaded trials below (consecutive windows, so the real
#: autocorrelation of a load window is preserved): K=1 cv 18.15%, K=3 cv 9.69%,
#: K=5 cv 7.71%, K=7 cv 7.38%. K=5 is where it flattens, and the worst reading
#: at K=5 equals the worst at K=3 (21.3947) while the cv is two points better.
#:
#: COST, stated rather than spent silently: a repetition costs ONE subprocess,
#: not two. `floor_names` is taken once (by `help_imports`, which pays for the
#: bare census anyway) and REUSED, so `startup_cost` adds K-1 = 4 `--help`
#: subprocesses per test MODULE and no extra bare censuses. The rejected
#: bare-floor candidate would have cost two per repetition, because its
#: denominator lives in a different process and drifts if it is not re-taken.
STARTUP_COST_READINGS: Final = 5

#: PDF-68 D3/AC9, and DERIVED for THIS denominator rather than copied from
#: `DENOMINATOR_SANITY_FLOOR_US` above (which guards a different, ~9x larger
#: quantity). The in-run floor's own measured readings on this host: quiet
#: median 8,564 us, smallest reading ever observed 8,430 us over 90 trials
#: spanning loadavg 0.19-66. A fifth of the quiet median is ~1,713, so this
#: floor sits 4.96x BELOW the smallest live reading this campaign ever saw --
#: far enough that contention cannot reach it, close enough that a genuinely
#: broken census (a `--help` that never reached the real path, or a subtraction
#: that swept the whole census into one bucket) RAISES rather than dividing.
STARTUP_FLOOR_SANITY_FLOOR_US: Final = 1_700

#: Total attributable import self time, AS A SHARE OF the in-run floor's self
#: time measured in the SAME `--help` subprocess. Expressed as an integer x1000
#: (a per-mille) so `ceiling_block()`'s existing integer parser needs no change:
#: `26_500` means the ratio must not exceed `26.500`.
#:
#: STATISTIC: median of K=5 readings of (sum of attributable self time / sum of
#:   the self time of the rows whose name IS in the bare-census floor name set),
#:   both sums from the SAME `pdftooling --help` `-X importtime` run. One bare
#:   census supplies the floor NAME set for every reading.
#: DATE: 2026-09-16
#: COMMIT: 7e36649 (measured on a byte-identical working tree at that commit,
#:   `git status --porcelain` empty before and after every reading; the harness
#:   lived OUTSIDE the product tree for exactly that reason)
#: HOST: station-01, 8 logical CPUs, Linux.
#: INTERPRETER: CPython 3.12.13 (`uv run python -V`)
#: ENGINES: all six present -- pypdf 6.16.2 / pypdfium2 5.13.0 / reportlab
#:   5.0.1 / pdfplumber 0.11.10 / tesseract 5.5.0 / soffice 26.2.5.2
#:
#: Figures are `attributable self / in-run floor self`, unitless, SINGLE
#: readings (K=1) unless the line says median-of-5:
#:   serial (`-n 0`, N=20, loadavg 0.19-0.25):
#:     min 16.1617  median 16.6154  p95 17.0052  max 17.8239  spread 1.6622  cv 2.07%
#:   `-n auto` (this project's default, ambient, N=20, loadavg 0.25-0.31):
#:     min 15.0132  median 16.5322  p95 17.3232  max 17.4527  spread 2.4395  cv 2.99%
#:   deliberate ambient load (N=50 over TWO regimes, loadavg 23.7-35.2 at 5x
#:   nproc and 57.1-66.0 at 8x nproc; independent CPU-bound busy-loop processes,
#:   killed by process group afterwards and proven dead with `ps`):
#:     min 12.3391  median 18.3084  p95 24.9179  max 32.6462  spread 20.3071  cv 18.15%
#:   the SHIPPED ESTIMATOR, median-of-5 over those same 50 loaded trials:
#:     min 16.2671  median 18.2659  p95 21.1705  max 21.3947  spread 5.1276  cv 7.71%
#:
#: THE LOAD-INVARIANCE THIS BASIS RESTS ON, measured across a 2x load range:
#: doubling the load moved this statistic's median by 0.8% (18.2348 at loadavg
#: 23-35 -> 18.3820 at loadavg 57-66) while the RAW ABSOLUTE over the identical
#: trials moved 87% (1,551,512 -> 2,906,813 us). The level is flat and only the
#: dispersion widens, which is why the median-of-5 estimator is sufficient and
#: why the headroom below is smaller than the shipped N=1 constants needed.
#:
#: REJECTED ALTERNATIVES, measured rather than argued (D2/AC7):
#:   C2, bare-census floor (`total/floor`, PDF-55's rejected candidate,
#:     re-measured here): loaded cv 19.67% at K=1, 7.62% at K=5 -- a virtual
#:     TIE with C1 at K=5, and it would have been ~10 points MORE SENSITIVE
#:     (f_min 50.6% vs 60.3%). It loses on the rule's stated tiebreak (the
#:     loaded-arm cv, 19.67% vs 18.15%), on cost (two subprocesses per
#:     repetition, not one) and structurally: its denominator comes from a
#:     DIFFERENT process, so there is no single row set over which numerator and
#:     denominator partition and AC9's partition assertion is not even
#:     well-posed. That is the inconvenient number, recorded rather than buried.
#:   C3, a majority quorum over the raw absolute: the quorum does kill the
#:     recorded false positive, but the absolute's LEVEL is not load-invariant
#:     (see above), so its ceiling must clear 3,178,150 us against a quiet
#:     median of 141,516 -- f_min 2707%, i.e. it can only catch a 28x slowdown.
#:     Rejected on MEASURED sensitivity, not on argument.
#:
#: FACTOR: 1.25x the deliberately-loaded arm's p95 OF THE SHIPPED ESTIMATOR
#: (21.1705), rounded to 26.500. The loaded arm governs (D2 rule 3): a contended
#: box is the condition the assertion actually runs in. That is 5.73 standard
#: deviations above the loaded mean of the shipped estimator and 1.237x the
#: worst median-of-5 ever observed. False-red rate over the 50 loaded readings:
#: 0 of 46 consecutive windows; 0.013% by bootstrap over 100,000 draws.
#: SEPARATION: the escaping-class plant at f = 2.5 reads a median-of-5 of
#: 56.85 (readings 43.5714 / 56.1641 / 56.8511 / 66.5980 / 57.3577) against
#: this 26.500 ceiling -- 2.15x the ceiling, and 2.66x the worst median-of-5
#: ever observed on a byte-identical tree at loadavg 23-66 (21.3947). Both
#: forms of D2's threshold are cleared. The ORDER is the criterion (X-476): the
#: unmutated loaded distribution above was measured and recorded FIRST, this
#: constant was derived from it SECOND, and the plant was driven against it
#: THIRD -- the value was never chosen with a plant reading in view.
#: SENSITIVITY BOUNDARY, measured on a descending ladder of f rather than
#: claimed (D5.3/AC5): the arm REDS at f >= 0.65 and stays GREEN at f <= 0.60.
#: Derivation predicted f_min = 60.3% from the quiet median-of-5 (16.5322) and
#: the crossing was observed between 0.60 and 0.65 -- the ceiling detects what
#: the measurement says it should, which is the difference between a derived
#: constant and an aimed one. Below f = 0.60 this arm is BLIND, stated plainly:
#: it is a NOISE-FLOOR ceiling ("red when the reading exceeds what contention
#: alone can produce"), never a POLICY ceiling ("red when a user would
#: notice"). Only the first is answerable from measurement; the second is the
#: project-manager's call and is deliberately not taken here.
#:
#: THE COVERAGE LEG IS DILUTED, MEASURED AND DECLARED RATHER THAN DISCOVERED
#: LATER. Every figure above was taken WITHOUT coverage instrumentation, i.e.
#: under `make test`'s condition. Under `make cover`/`make ci`,
#: `[tool.coverage.run] patch = ["subprocess"]` puts coverage.py into BOTH
#: censuses, so its ~144 modules join the floor NAME set and its own import
#: cost joins the DENOMINATOR: measured at this commit, the floor name set goes
#: 39 -> 183, the denominator 8,564 -> 83,887 us, and this statistic reads
#: 1.6062 instead of ~16.5. That direction is SAFE -- it is one-sided toward
#: green and cannot manufacture a false red, which is the direction that
#: matters across eight matrix legs -- but the arm's sensitivity in the
#: coverage leg is roughly a TENTH of its sensitivity in `make test`
#: (f_min ~1546% rather than ~60%). The arm therefore does its real work in the
#: uninstrumented leg, which CI also runs. Narrowing the denominator to the
#: true interpreter floor would recover it and is a DIFFERENT spec: it needs
#: its own three-arm campaign, and inventing it here would mean shipping a
#: constant derived against one condition and asserted under another.
#:
#: CLASS: a diffuse PROPORTIONAL slowdown of an UNCHANGED import set -- same
#: count, same names, no single dominator, both shipped ratios exactly flat
#: (DECLARED BLIND SPOT 4). Under `t_m -> (1+f)*t_m` for every attributable
#: module, this statistic reads `(1+f)x` exactly, because the floor rows are not
#: attributable and do not scale.
#: CONTROL: a `sys.meta_path` shim installed in a scratch rsync copy only, which
#: CPU-SPINS (never `time.sleep` -- a sleep is contention-invariant and is the
#: one shape a ratio basis is structurally weakest against) for `f x` each
#: module's own measured exec time, gated to skip the captured floor-name list
#: so the bare-interpreter floor is unmoved. Proven in the class before it was
#: allowed to grade anything: count delta 0, name set identical, BOTH shipped
#: ratio arms GREEN on the planted tree under the default `-n auto`, floor
#: within its own noise. The SEPARATION and the measured SENSITIVITY BOUNDARY
#: ("reds at f >= X, green at f <= Y") are in this spec's Implementation Log.
STARTUP_COST_RATIO_CEILING_PER_MILLE: Final = 26_500


class StartupPartition(NamedTuple):
    """One `--help` census's rows, split into the two populations this ratio
    divides -- the ATTRIBUTABLE rows (the numerator a product- or
    dependency-side import regression enters) and the IN-RUN FLOOR rows (the
    denominator it cannot), over the SAME row set.

    Deliberately a second partition type beside `ImportPartition` rather than a
    generalisation of it: that one splits the ATTRIBUTABLE set by ownership and
    this one splits the WHOLE census by whether the bare interpreter loaded it.
    They answer different questions over different universes, and a shared type
    would have to lie about one of them in its failure message.
    """

    attributable_modules: frozenset[str]
    floor_modules: frozenset[str]
    attributable_us: int
    floor_us: int


def assert_startup_partition_valid(
    attributable: frozenset[str], floor: frozenset[str], universe: frozenset[str]
) -> None:
    """AC9. *attributable* and *floor* must partition *universe* -- no overlap,
    no remainder -- or cost could move between this ratio's numerator and its
    denominator without either one noticing.

    The overlap half is the dangerous one and it is not hypothetical: a row
    counted on BOTH sides inflates the numerator and the denominator together,
    which is precisely the signature this instrument reads as "nothing
    happened". The remainder half is the `d933b5abdd` shape one level in --
    rows that fall out of both populations are cost the instrument stops
    measuring while still reporting a plausible number.
    """
    overlap = attributable & floor
    assert overlap == frozenset(), (
        f"module(s) counted in BOTH the attributable numerator and the in-run floor "
        f"denominator: {sorted(overlap)}. A row on both sides moves cost into the "
        "numerator and the denominator together, which this statistic reads as no "
        "change at all -- the exact blindness it exists to end."
    )
    covered = attributable | floor
    assert covered == universe, (
        f"the startup partition does not cover the census. missing="
        f"{sorted(universe - covered)} extra={sorted(covered - universe)}"
    )


def checked_startup_denominator(partition: StartupPartition) -> int:
    """*partition*'s in-run floor denominator, or a raise naming the reading.

    Same rule as `checked_denominator` above and for the same reason, with a
    floor DERIVED for this quantity (`STARTUP_FLOOR_SANITY_FLOOR_US`) rather
    than borrowed from a denominator roughly nine times larger: a ratio that
    normalises by a denominator it cannot trust manufactures a false positive
    out of the instrument itself.
    """
    if not partition.floor_modules or partition.floor_us <= 0:
        raise AssertionError(
            f"the startup ratio's denominator (in-run floor self time) is "
            f"{partition.floor_us} us over {len(partition.floor_modules)} module(s) -- "
            "refusing to divide. Either the probe did not reach the real `--help` path, "
            "or the bare-census subtraction claimed every row in the census."
        )
    if partition.floor_us < STARTUP_FLOOR_SANITY_FLOOR_US:
        raise AssertionError(
            f"the startup ratio's denominator read {partition.floor_us} us, under the "
            f"{STARTUP_FLOOR_SANITY_FLOOR_US} us sanity floor -- this is not a live "
            "in-run floor, so no ratio is computed from it."
        )
    return partition.floor_us


def partition_by_floor(rows: list[ModuleImport], floor_names: frozenset[str]) -> StartupPartition:
    """Split one `--help` census's rows into attributable and in-run floor.

    This is the complement of the filter `probe_help_imports` already runs: it
    keeps the rows that one discards. Both sides are summed from the SAME row
    list, so contention that dilates the process dilates both.
    """
    attributable = frozenset(row.name for row in rows if row.name not in floor_names)
    floor = frozenset(row.name for row in rows if row.name in floor_names)
    assert_startup_partition_valid(attributable, floor, frozenset(row.name for row in rows))
    return StartupPartition(
        attributable_modules=attributable,
        floor_modules=floor,
        attributable_us=sum(row.self_us for row in rows if row.name not in floor_names),
        floor_us=sum(row.self_us for row in rows if row.name in floor_names),
    )


#: `-X importtime` writes `import time: self [us] | cumulative | imported package`
#: and then one row per module in the same three columns. Until PDF-42 this
#: parser kept `fields[2]` and threw the two timing columns away -- the
#: measurement was already on the wire, already paid for by a subprocess that
#: runs on every leg of every CI job, and discarded three lines later.
IMPORTTIME_PREFIX: Final = "import time:"
IMPORTTIME_HEADER_NAME: Final = "imported package"


def parse_importtime_row(line: str) -> ModuleImport | None:
    """One `-X importtime` row, or `None` for the header and for shapes that are
    not rows at all.

    A row that reaches the three-column shape and whose timing columns do NOT
    parse as integers **raises, naming the line**. Degrading a malformed field
    to `0` is the tempting alternative and it is forbidden here: a census of
    zeroes passes every ceiling below and still exits 0 -- a silent wrong answer
    wearing a success code, which is the exact failure class Section 6 exists to
    end. If CPython changes this format, this section must go RED and be
    re-read, not quietly start measuring nothing.
    """
    fields = line.split("|")
    if len(fields) != 3:
        return None
    name = fields[2].strip()
    if name == IMPORTTIME_HEADER_NAME:
        return None
    raw_self = fields[0].split(":", 1)[-1].strip()
    raw_cumulative = fields[1].strip()
    try:
        return ModuleImport(name, int(raw_self), int(raw_cumulative))
    except ValueError as exc:  # pragma: no cover - exercised via the red control
        raise AssertionError(
            f"`-X importtime` row has a non-numeric timing column: {line!r}. "
            "The census refuses to read this as 0: a zeroed census passes every ceiling "
            "in this section and still exits 0. If CPython's importtime format changed, "
            "fix this parser -- do not let the instrument report success on data it "
            "could not read."
        ) from exc


def _importtime_census(argv: list[str], env: dict[str, str]) -> tuple[int, list[ModuleImport]]:
    """(exit code, every module `-X importtime` reported for *argv*, WITH both
    of its timing columns)."""
    result = subprocess.run(  # noqa: S603 - this interpreter, a literal argv
        [sys.executable, "-X", "importtime", *argv],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        env=env,
    )
    modules: list[ModuleImport] = []
    for line in result.stderr.splitlines():
        if not line.startswith(IMPORTTIME_PREFIX):
            continue
        row = parse_importtime_row(line)
        if row is not None:
            modules.append(row)
    return result.returncode, modules


def probe_help_imports(entry: Path | None = None) -> HelpImports:
    """Run the real console script under `-X importtime` and census the result,
    MINUS whatever this environment loads into a bare interpreter anyway.

    `-X importtime` reports EVERY module the interpreter imports, so this
    measures the actual `--help` invocation rather than re-deriving it from an
    AST walk -- a lazy import inside a function body is invisible to a walk and
    fully visible here, and it is the runtime set that costs milliseconds.

    WHY THE SUBTRACTION, and it is not tidiness. Under `make cover`,
    `[tool.coverage.run] patch = ["subprocess"]` makes every child process
    measured, so coverage.py and its whole module tree would land in this
    census -- an instrument reporting its own instrumentation, red in CI's
    `engines-present` job and green in every other. The obvious fix is to scrub
    `COVERAGE_PROCESS_*` from the child env, which is what the startup-budget
    test does; that was tried and REJECTED here, because
    `tests/test_coverage_policy.py` pins the number of modules that scrub at
    exactly one and a second one is a real weakening of a real control (observed
    red: `test_exactly_one_test_module_scrubs_the_coverage_environment`, one
    case, during this spec's own `make ci`).

    Subtracting a bare-interpreter census taken in the SAME environment is
    strictly better than scrubbing: coverage.py, `sitecustomize`, and anything
    else the environment injects appear in BOTH censuses and cancel exactly,
    without this file opting out of coverage measurement at all. What is left is
    what the console script itself pulls in -- which is the only thing this
    section is about.
    """
    env = dict(os.environ)
    _, floor = _importtime_census(["-c", "pass"], env)
    returncode, measured = _importtime_census(
        [str(entry if entry is not None else VENV_CONSOLE_SCRIPT), "--help"], env
    )
    floor_names = {row.name for row in floor}
    attributable = [row for row in measured if row.name not in floor_names]
    # PDF-68 D1/E7: the complement of the filter above, from the SAME process.
    in_run_floor_self_us = sum(row.self_us for row in measured if row.name in floor_names)
    top_level = frozenset(row.name.split(".")[0] for row in attributable)
    non_stdlib = frozenset(
        name
        for name in top_level
        if name not in sys.stdlib_module_names and not name.startswith("_")
    )
    # Summed rather than assigned, so a module reported twice cannot silently
    # drop out of the mapping and make the key set disagree with the count.
    self_us_by_module: dict[str, int] = {}
    for row in attributable:
        self_us_by_module[row.name] = self_us_by_module.get(row.name, 0) + row.self_us
    return HelpImports(
        returncode,
        len(attributable),
        top_level,
        non_stdlib,
        self_us_by_module,
        sum(self_us_by_module.values()),
        frozenset(floor_names),
        in_run_floor_self_us,
    )


@pytest.fixture(scope="module")
def help_imports() -> HelpImports:
    if not VENV_CONSOLE_SCRIPT.exists():
        pytest.skip(
            f"no console script at {VENV_CONSOLE_SCRIPT}. This section measures the "
            "project venv's own build and will not silently substitute another one "
            "(PLAN.md 10.1 rule 5: absent precondition, skip with a reason, never pass). "
            "Run `uv sync`."
        )
    return probe_help_imports()


class StartupCostReadings(NamedTuple):
    """K paired (numerator, denominator) readings and the ratios they give.

    Paired is the whole point: each ratio's two halves come from ONE `--help`
    subprocess, so a scheduling excursion that inflates the numerator inflated
    the denominator in the same window and divides out.
    """

    ratios: tuple[float, ...]
    numerators: tuple[int, ...]
    denominators: tuple[int, ...]


def probe_startup_cost(
    floor_names: frozenset[str], repetitions: int, first: tuple[int, int] | None = None
) -> StartupCostReadings:
    """*repetitions* readings of the startup-cost ratio, sharing ONE floor name set.

    `floor_names` is passed in rather than re-derived, for two reasons and both
    are load-bearing. (1) COST: a repetition is then ONE subprocess, not two --
    the bare census is paid for once, by `help_imports`, which needs it anyway.
    (2) CORRECTNESS: every reading partitions its census against the SAME name
    set, so the numerator and the denominator of every ratio are complementary
    over one row set. A repetition that re-derived its own floor names would be
    dividing two quantities drawn from two different partitions.

    *first* is the reading `help_imports` already paid for, reused rather than
    re-taken, so K=5 costs four extra subprocesses and not five.
    """
    ratios: list[float] = []
    numerators: list[int] = []
    denominators: list[int] = []

    def record(numerator: int, denominator: int) -> None:
        numerators.append(numerator)
        denominators.append(denominator)
        ratios.append(numerator / denominator)

    if first is not None:
        record(*first)
    env = dict(os.environ)
    while len(ratios) < repetitions:
        _, measured = _importtime_census([str(VENV_CONSOLE_SCRIPT), "--help"], env)
        partition = partition_by_floor(measured, floor_names)
        record(partition.attributable_us, checked_startup_denominator(partition))
    return StartupCostReadings(tuple(ratios), tuple(numerators), tuple(denominators))


@pytest.fixture(scope="module")
def startup_cost(help_imports: HelpImports) -> StartupCostReadings:
    """K readings of the total-startup-cost ratio, taken once per test module.

    Module-scoped for the same reason `help_imports` is, and it DEPENDS on
    `help_imports` rather than re-censusing: that is what lets the K readings
    reuse one bare census and one floor name set. It adds NO abstention of its
    own -- the only precondition in this section is the build-absent skip
    `help_imports` already carries, and a second one would redden
    `tests/test_gate_budget.py::test_the_abstention_walk_is_not_vacuous`.
    """
    return probe_startup_cost(
        help_imports.floor_names,
        STARTUP_COST_READINGS,
        first=(help_imports.total_self_us, help_imports.in_run_floor_self_us),
    )


def test_the_help_import_census_is_not_vacuous(help_imports: HelpImports) -> None:
    """A green census over an empty or failed run proves nothing.

    This is the same non-vacuity floor Sections 2, 4 and 5 each carry, and it is
    load-bearing here for a specific reason: if the console script exited
    non-zero (a broken build, a missing dependency) the census would be a short
    prefix of the real one and every assertion below would pass by measuring
    almost nothing.
    """
    assert help_imports.returncode == 0, "`pdftooling --help` did not exit 0 under the probe"
    assert help_imports.total >= 120, (
        f"only {help_imports.total} module(s) attributable -- the probe did not reach the "
        "real help path, so nothing below is measuring the product. (120, not 280: the "
        "baseline subtraction legitimately credits modules to the environment under "
        "`make cover`, so the floor has to sit well below the uninstrumented reading.)"
    )
    assert {"pdf_tooling", "typer"} <= help_imports.non_stdlib, (
        f"the census is missing the CLI itself: {sorted(help_imports.non_stdlib)}"
    )


def test_help_imports_no_third_party_package_outside_the_pin(help_imports: HelpImports) -> None:
    """The load-immune half of `PLAN §12 R-13`.

    A wall-clock budget answers "was it fast on this box, this minute". This
    answers "did anything new become eager", which is the question that survives
    being asked on a loaded host, in parallel, on someone else's laptop.
    """
    unexpected = sorted(help_imports.non_stdlib - HELP_IMPORT_ALLOWLIST)
    assert unexpected == [], (
        f"`pdftooling --help` now eagerly imports {unexpected}, which is not in this "
        "section's pin. Startup latency in a Python CLI is dominated by module import, so "
        "this is a startup regression whatever the wall-clock number happens to say on the "
        "host you are reading this on. Either make the import lazy (import it inside the "
        "function that needs it), or add it to HELP_IMPORT_ALLOWLIST **with a measured "
        "`make gate-timing --target help-startup` distribution recorded in "
        "perf/gate-timings.jsonl** -- widening a pin without a measurement is how the "
        "wall-clock budget this section replaced came to be defended by nothing."
    )


def test_help_import_count_stays_under_the_ceiling(help_imports: HelpImports) -> None:
    """The second net, catching an eager STDLIB subsystem the allowlist cannot.

    `asyncio`, `pydoc`, `unittest`, `xmlrpc` and friends are all stdlib, so the
    allowlist above is blind to them by construction -- and each drags in dozens
    of modules. The count is what sees them.
    """
    assert help_imports.total <= HELP_MODULE_CEILING, (
        f"`pdftooling --help` imports {help_imports.total} modules, over the "
        f"{HELP_MODULE_CEILING} ceiling (measured 280 at 3.12.13 / 282 at 3.11.15 when this "
        "was pinned). Find what became eager with "
        f"`python -X importtime {VENV_CONSOLE_SCRIPT} --help`."
    )


# --------------------------------------------------------------------------- #
# Proof that Section 6's guards fire, and that they fire on something the
# ENGINE_MODULES control structurally cannot see. Without these, the three
# assertions above are a claim.
# --------------------------------------------------------------------------- #


#: Planted deliberately: `hypothesis` is a heavy third-party package that is
#: installed in this venv (a dev dependency) and is **NOT** in `ENGINE_MODULES`,
#: nor in `PLAN_FORBIDDEN`/`EXTRA_FORBIDDEN`. That is the whole point -- a red
#: the existing engine control ALSO produces would not satisfy the criterion
#: this control exists for.
PLANTED_EAGER_IMPORT: Final = "hypothesis"


def _entry_with_a_planted_eager_import(tmp_path: Path) -> Path:
    """An entry script that imports a heavy package at module scope, then runs
    the real CLI's `main()`.

    **DELIBERATE DEVIATION, and the reason is a coverage floor.** The obvious
    plant is a full `src/` copy with the import added to `cli/main.py`, reached
    by shadowing `pdf_tooling` on `PYTHONPATH` -- and that is what this control
    did first. It was **observed breaking the gate**: under
    `[tool.coverage.run] patch = ["subprocess"]` the probe's child IS measured,
    coverage matches `source = ["pdf_tooling"]` by module name, and every file
    of the planted copy entered the report as almost entirely unexecuted. The
    total fell from ~94% to **63.24%** and `make ci` went red on
    `--cov-fail-under=85` with 2623 tests passing.

    The three ways out were all worse. An `omit` for the scratch path is
    forbidden outright (`PDF-06:236`: *if the floor is unreachable the answer is
    more tests -- never a lower `fail_under` and never an `omit`*). Redirecting
    `COVERAGE_FILE` in the child does nothing: the serialized
    `COVERAGE_PROCESS_CONFIG` carries the data-file path and wins (measured).
    Scrubbing `COVERAGE_PROCESS_*` here works, but
    `tests/test_coverage_policy.py` pins the number of modules that do so at
    exactly one, and a second one weakens a shipped control to make a test
    convenient.

    Planting at the ENTRY instead costs nothing and proves the same thing,
    because this census is a RUNTIME import census: it sees a non-stdlib
    top-level import wherever in the graph it happens. That the census also sees
    imports made deep INSIDE product modules is not assumed either -- it is
    asserted directly by
    `test_the_census_sees_imports_made_inside_product_modules`, which pins
    `PIL`, imported by `pdf_tooling.cli.common` and by nothing this control
    writes.
    """
    entry = tmp_path / "planted_entry.py"
    entry.write_text(
        f"import {PLANTED_EAGER_IMPORT}  # planted, module scope\n"
        "from pdf_tooling.cli.main import main\n"
        "main()\n"
    )
    return entry


def test_the_census_sees_imports_made_inside_product_modules(
    help_imports: HelpImports,
) -> None:
    """The half the entry-point plant cannot show, asserted directly.

    `PIL` is imported by `pdf_tooling.ops.compose` -- three levels inside the
    product, by nothing any test writes. Its presence in the census is the proof
    that this section sees eager imports made INSIDE product modules and not
    merely ones written at the entry point.

    **The module named above was corrected by PDF-42.** This docstring and the
    failure message below said `pdf_tooling.cli.common`, which has never
    contained a `PIL` token. The assertion was always right; only its
    explanation was wrong, and a wrong explanation costs something precisely
    here: the message tells a future reader which file to look at, and it was
    telling them to look at a file with nothing in it.
    """
    assert "PIL" in help_imports.non_stdlib, (
        "PIL is no longer in the census. If `pdf_tooling/ops/compose.py:90` stopped "
        "importing it eagerly that is GOOD NEWS and this assertion should be re-pointed at "
        "whatever product-internal eager import remains -- but it must be re-pointed, not "
        "deleted, or the planted-entry control below is the only proof this section has "
        "and it proves the weaker half. "
        "(`test_pil_has_exactly_one_module_scope_import_site_under_src` derives the site, "
        "so it will tell you where to point rather than leaving you to grep.)"
    )


def test_a_planted_eager_import_reddens_section_6(tmp_path: Path) -> None:
    """Both nets fire on the same plant, and the engine control does not.

    The last assertion is the load-bearing one: a red that
    `test_no_engine_library_is_imported_at_module_scope` ALSO produces would
    mean this section caught nothing the suite already had.
    """
    if not VENV_CONSOLE_SCRIPT.exists():
        pytest.skip(f"no console script at {VENV_CONSOLE_SCRIPT}; run `uv sync`.")
    planted = probe_help_imports(entry=_entry_with_a_planted_eager_import(tmp_path))

    assert planted.returncode == 0, (
        "the planted entry did not run at all, so this control proved nothing"
    )
    unexpected = sorted(planted.non_stdlib - HELP_IMPORT_ALLOWLIST)
    assert PLANTED_EAGER_IMPORT in unexpected, (
        f"Section 6's allowlist did not notice {PLANTED_EAGER_IMPORT}: {unexpected}"
    )
    assert planted.total > HELP_MODULE_CEILING, (
        f"Section 6's ceiling did not notice the plant: {planted.total} modules against a "
        f"{HELP_MODULE_CEILING} ceiling"
    )
    assert not (ENGINE_MODULES & planted.top_level), (
        "the planted module IS an engine library, so the pre-existing "
        "test_no_engine_library_is_imported_at_module_scope would have caught it too and "
        "this section would have proved nothing new"
    )


def test_the_pin_is_a_superset_check_and_a_missing_import_is_not_a_red(
    help_imports: HelpImports,
) -> None:
    """The asymmetry above, asserted rather than left as a comment.

    Making an import lazy REMOVES a name from the census. If that reddened, the
    first person to improve startup latency would be told they broke a test, and
    the pin would be widened or deleted. So the direction is pinned explicitly:
    a name in the allowlist that no longer appears is fine.
    """
    absent = HELP_IMPORT_ALLOWLIST - help_imports.non_stdlib
    unexpected = help_imports.non_stdlib - HELP_IMPORT_ALLOWLIST
    assert unexpected == frozenset(), f"guarded elsewhere; here only for contrast: {unexpected}"
    # `absent` is deliberately not asserted empty -- this line documents that,
    # and pins that the allowlist is not merely a restatement of the census.
    assert absent <= HELP_IMPORT_ALLOWLIST


# --------------------------------------------------------------------------- #
# PDF-42 -- the assertions the timing columns buy, and the reds that prove them
# --------------------------------------------------------------------------- #


def test_no_single_module_costs_more_than_the_self_time_ceiling(
    help_imports: HelpImports,
) -> None:
    """The assertion the headline plant fails, and the reason it is per-module.

    PDF-55 RE-BASE: this node is KEPT because it is the only arm that NAMES
    the offending module, which a whole-census ratio cannot -- but its basis
    is now the module's share of the non-product attributable self time in
    the SAME census, not an absolute microsecond figure. The absolute
    (`MODULE_SELF_US_CEILING`) reddened on a byte-identical tree under load
    (E4: 2 of 3 trials at loadavg 77-84) precisely because contention inflates
    every module's self time roughly together; the ratio does not, because the
    denominator inflates along with it.
    """
    partition = partition_by_product(help_imports.self_us_by_module)
    denominator = checked_denominator(partition)
    over = sorted(
        (name, cost, round(cost / denominator, 4))
        for name, cost in help_imports.self_us_by_module.items()
        if cost * 1000 > MODULE_SELF_RATIO_CEILING_PER_MILLE * denominator
    )
    assert over == [], (
        f"module(s) over the {MODULE_SELF_RATIO_CEILING_PER_MILLE / 1000:.3f} "
        f"per-module-self/non-product-self ratio ceiling: {over}. Startup latency in a "
        "Python CLI is dominated by module import, and this is a module that got "
        "dramatically more expensive to import -- a sleep, a network call, a heavy "
        "computation or a big eager subsystem at module scope. Find it with "
        f"`python -X importtime {VENV_CONSOLE_SCRIPT} --help`. Either move the cost out of "
        "module scope, or widen MODULE_SELF_RATIO_CEILING_PER_MILLE **with a fresh measured "
        "distribution recorded beside it** -- widening a pin without a measurement is how "
        "the wall-clock budget this section replaced came to be defended by nothing."
    )


def test_the_product_import_ratio_stays_under_its_ceiling(help_imports: HelpImports) -> None:
    """PDF-55's new claim-bearing arm (D1/D2/D4), replacing
    `test_total_import_self_time_stays_under_the_ceiling` (retired, D5/AC12):
    `pdf_tooling.*` self time, as a share of every OTHER attributable module's
    self time in the SAME census. A product-side regression enters the
    numerator and cannot enter the denominator; ordinary contention multiplies
    both and cancels. See `PRODUCT_IMPORT_RATIO_CEILING_PER_MILLE`'s own block
    for the derivation, and the Implementation Log for the AC1-AC3 evidence
    this arm was graded against.
    """
    partition = partition_by_product(help_imports.self_us_by_module)
    denominator = checked_denominator(partition)
    ratio = partition.product_self_us / denominator
    assert (
        partition.product_self_us * 1000 <= PRODUCT_IMPORT_RATIO_CEILING_PER_MILLE * denominator
    ), (
        f"`pdftooling --help` spends {partition.product_self_us} us of PRODUCT "
        f"(`pdf_tooling.*`) import self time against {denominator} us of non-product "
        f"attributable self time in the SAME census -- a ratio of {ratio:.4f}, over the "
        f"{PRODUCT_IMPORT_RATIO_CEILING_PER_MILLE / 1000:.3f} ceiling. Startup latency in a "
        "Python CLI is dominated by module import, and this is the coarse net for a "
        "regression spread thinly across many modules; check the per-module view first "
        f"(`python -X importtime {VENV_CONSOLE_SCRIPT} --help`). Either make an import "
        "lazy, or widen PRODUCT_IMPORT_RATIO_CEILING_PER_MILLE **with a fresh measured "
        "distribution recorded beside it**."
    )


def test_total_startup_import_cost_stays_under_its_ceiling(
    startup_cost: StartupCostReadings,
) -> None:
    """PDF-68's claim-bearing arm: the proposition NO default-running arm held.

    `PLAN §12 R-13` is a claim about `--help` startup latency. The allowlist
    holds the import NAMES, the count ceiling holds the COUNT, and the two
    ratios above hold SHAPE -- which module dominates, and how much of the cost
    is the product's. None of them holds the TOTAL, and the two ratios are
    blind to a uniform proportional inflation of the census BY ALGEBRA rather
    than by threshold (DECLARED BLIND SPOT 4). The only arm that would see it
    abstains on every xdist worker, and `-n auto` is the default -- so it never
    runs here or in CI.

    This one runs, on every leg, because it never asks how busy the box is: it
    counts the product's total import cost in units of the IN-RUN FLOOR -- the
    rows the bare interpreter loads anyway, measured in the same subprocess.
    Contention multiplies both sides and cancels; a product- or dependency-side
    import regression enters the numerator and cannot enter the denominator.

    The QUORUM is the estimator (D3). A strict majority of K readings must
    exceed the ceiling, which is the same predicate as "the median of K exceeds
    it" and localises far better in the message. `min`-of-N is forbidden on the
    denominator: a small denominator's minimum is an outlier draw, and a
    min-based ratio tuned to catch a plant fires on a byte-identical tree.
    """
    readings = startup_cost.ratios
    assert len(readings) == STARTUP_COST_READINGS, (
        f"the startup-cost probe returned {len(readings)} reading(s), not "
        f"{STARTUP_COST_READINGS}. A quorum over the wrong number of readings is not the "
        "estimator this ceiling was derived against."
    )
    ceiling = STARTUP_COST_RATIO_CEILING_PER_MILLE / 1000
    over = [round(value, 4) for value in readings if value > ceiling]
    assert len(over) * 2 <= len(readings), (
        f"{len(over)} of {len(readings)} readings exceeded the {ceiling:.3f} "
        f"total-startup-cost ratio ceiling (readings: "
        f"{[round(value, 4) for value in readings]}; over: {over}). This is TOTAL "
        "attributable import self time measured in units of the in-run interpreter "
        "floor, so a busy box moves both halves together and does NOT produce this "
        "red -- what does is everything getting proportionally more expensive to "
        "import: a dependency bump, a wheel rebuild, a transitive re-resolve. The "
        "import NAMES and the COUNT can all be unchanged and both shipped ratios flat "
        "while this fires; that is the case this arm exists for. Find it with "
        f"`python -X importtime {VENV_CONSOLE_SCRIPT} --help` and compare against the "
        "distribution beside STARTUP_COST_RATIO_CEILING_PER_MILLE. Either make an "
        "import lazy, or widen the ceiling **with a fresh measured distribution "
        "recorded beside it** -- widening a pin without a measurement is how the "
        "wall-clock budget this section replaced came to be defended by nothing."
    )


def test_the_startup_partition_reddens_on_a_row_counted_in_both_populations() -> None:
    """AC9 RED (ii). Hand-built populations, computed two different ways --
    `partition_by_floor`'s own membership test cannot itself produce an overlap,
    so the only way to prove `assert_startup_partition_valid` fires is to hand
    it one."""
    universe = frozenset({"pdf_tooling.models", "_io"})
    with pytest.raises(AssertionError, match="counted in BOTH"):
        assert_startup_partition_valid(
            frozenset({"pdf_tooling.models", "_io"}),  # "_io" wrongly on BOTH sides
            frozenset({"_io"}),
            universe,
        )


def test_the_startup_partition_reddens_on_a_row_left_out_of_both_populations() -> None:
    """AC9 RED (ii)'s sibling: a row in NEITHER population is cost the ratio has
    silently stopped measuring while still reporting a plausible number."""
    universe = frozenset({"pdf_tooling.models", "_io"})
    with pytest.raises(AssertionError, match="does not cover the census"):
        assert_startup_partition_valid(frozenset({"pdf_tooling.models"}), frozenset(), universe)


def test_a_hollow_startup_denominator_raises_rather_than_dividing() -> None:
    """AC9 RED (i). An empty (or zero-summed) in-run floor REFUSES rather than
    manufacturing an enormous ratio out of the instrument itself."""
    hollow = StartupPartition(
        attributable_modules=frozenset({"pdf_tooling.models"}),
        floor_modules=frozenset(),
        attributable_us=140_000,
        floor_us=0,
    )
    with pytest.raises(AssertionError, match="refusing to divide"):
        checked_startup_denominator(hollow)


def test_a_startup_denominator_under_its_sanity_floor_raises_by_name() -> None:
    """AC9 RED (iii). A denominator that is technically positive but far too
    small to be a live in-run floor still refuses, naming the reading. The
    smallest floor reading this campaign ever observed was 8,430 us over 90
    trials spanning loadavg 0.19-66; 1,699 is not a census, it is a bug."""
    thin = StartupPartition(
        attributable_modules=frozenset({"pdf_tooling.models"}),
        floor_modules=frozenset({"_io"}),
        attributable_us=140_000,
        floor_us=STARTUP_FLOOR_SANITY_FLOOR_US - 1,
    )
    with pytest.raises(AssertionError, match="sanity floor"):
        checked_startup_denominator(thin)


def test_the_partition_reddens_on_a_module_placed_in_both_populations() -> None:
    """AC8 RED (ii). Direct call, hand-built input -- the same shape as
    `test_a_malformed_timing_column_raises_rather_than_reading_as_zero`'s proof
    of `parse_importtime_row`. `partition_by_product`'s own subtraction cannot
    itself produce an overlap, so the only way to prove `assert_partition_valid`
    fires is to hand it two populations computed two different ways.
    """
    universe = frozenset({"pdf_tooling.models", "typing"})
    with pytest.raises(AssertionError, match="classified as BOTH"):
        assert_partition_valid(
            frozenset({"pdf_tooling.models", "typing"}),  # "typing" wrongly in BOTH
            frozenset({"typing"}),
            universe,
        )


def test_the_partition_reddens_on_a_module_left_out_of_both_populations() -> None:
    """AC8 RED (ii)'s sibling: a module in NEITHER population is a silent
    remainder rather than a silent overlap, and is caught the same way."""
    universe = frozenset({"pdf_tooling.models", "typing"})
    with pytest.raises(AssertionError, match="does not cover"):
        assert_partition_valid(frozenset({"pdf_tooling.models"}), frozenset(), universe)


def test_a_hollow_denominator_raises_rather_than_dividing() -> None:
    """AC8 RED (i). A denominator population that is empty (or that summed to
    zero) REFUSES rather than manufacturing an infinite -- or merely
    enormous -- ratio from a denominator this section cannot trust."""
    hollow = ImportPartition(
        product_modules=frozenset({"pdf_tooling.models"}),
        non_product_modules=frozenset(),
        product_self_us=9_000,
        non_product_self_us=0,
    )
    with pytest.raises(AssertionError, match="refusing to divide"):
        checked_denominator(hollow)


def test_a_denominator_under_the_sanity_floor_raises_by_name() -> None:
    """D3's stated sanity band, the half AC8 does not name but D3 requires: a
    denominator that is *technically* positive but far too small to be a real
    census (a near-total misclassification) still refuses, naming the
    reading, rather than dividing by something this section cannot trust."""
    thin = ImportPartition(
        product_modules=frozenset({"pdf_tooling.models"}),
        non_product_modules=frozenset({"_io"}),
        product_self_us=900_000,
        non_product_self_us=1,
    )
    with pytest.raises(AssertionError, match="sanity floor"):
        checked_denominator(thin)


def test_the_timing_census_is_not_vacuous(help_imports: HelpImports) -> None:
    """AC5. A ceiling over an empty or zeroed mapping passes forever.

    `expertise/product.yaml`: *a uniform negative across a population expected
    to be split is the signature of a dead instrument.* The two ceilings above
    are one-sided, so a census of zeroes satisfies both while measuring nothing
    -- which is the precise shape of silent wrong answer this section exists to
    prevent, and the reason `parse_importtime_row` raises rather than
    defaulting.
    """
    assert help_imports.self_us_by_module, "the per-module timing mapping is empty"
    assert help_imports.total_self_us > 0, (
        f"total import self time is {help_imports.total_self_us}; the timing columns "
        "parsed to nothing, so both ceilings above are passing over no data at all"
    )
    timed_top_level = {name.split(".")[0] for name in help_imports.self_us_by_module}
    assert timed_top_level == help_imports.top_level, (
        "the timing mapping and the name census describe DIFFERENT module sets; one of them "
        f"is measuring a different program. Timing-only: "
        f"{sorted(timed_top_level - help_imports.top_level)}; "
        f"names-only: {sorted(help_imports.top_level - timed_top_level)}"
    )
    assert sum(help_imports.self_us_by_module.values()) == help_imports.total_self_us

    # PDF-68 D8/AC15. The denominator half of the startup-cost ratio, held to
    # the same non-vacuity floor as the numerator: a zero (or absent) in-run
    # floor would make that arm raise rather than pass, but an unasserted field
    # is how `floor_self_us` came to be declared, populated and read by nothing.
    assert help_imports.floor_names, (
        "the bare-interpreter floor census reported NO module names, so the baseline "
        "subtraction subtracted nothing -- every row in the `--help` census would be "
        "credited to the product and the in-run floor denominator would be empty"
    )
    assert help_imports.in_run_floor_self_us > 0, (
        f"the in-run floor self time is {help_imports.in_run_floor_self_us}; the "
        "denominator of the total-startup-cost ratio parsed to nothing"
    )
    assert not (help_imports.floor_names & set(help_imports.self_us_by_module)), (
        "a module the bare interpreter loads is ALSO in the attributable set: the two "
        "populations of the startup-cost ratio overlap, so cost is being counted in its "
        f"numerator and its denominator at once. Overlap: "
        f"{sorted(help_imports.floor_names & set(help_imports.self_us_by_module))}"
    )

    # `total` counts `-X importtime` ROWS; the mapping is keyed by module NAME, and
    # CPython emits repeat rows. Measured at b175d10: 282 rows over 273 distinct
    # names -- `nt` appears SIX times and `_winapi` twice (Windows-only modules
    # CPython probes for and fails to import, logging each attempt), and
    # `pdf_tooling.safety.policy`, `typer._click.exceptions` and `_elementtree`
    # each appear twice (re-entered while already in `sys.modules`, so the second
    # row is nearly free). So the mapping is expected to be SMALLER, never larger,
    # and the repeated rows are SUMMED into their module's entry rather than
    # overwriting it -- overwriting would silently drop cost on the floor.
    #
    # This also means `HELP_MODULE_CEILING`'s "280 modules" has always been a row
    # count rather than a distinct-module count. PDF-42 records that and changes
    # neither: the ceiling is out of this spec's scope and the row count is a
    # perfectly good proxy for the thing it pins.
    assert len(help_imports.self_us_by_module) <= help_imports.total, (
        f"the timing mapping describes {len(help_imports.self_us_by_module)} modules from "
        f"{help_imports.total} importtime rows. More names than rows is impossible; the "
        "parser or the subtraction is wrong."
    )


def test_a_malformed_timing_column_raises_rather_than_reading_as_zero() -> None:
    """AC4's RED. The parser is fed a row whose self field is not a number.

    A parser that degraded to 0 would produce a census of zeroes that passes
    every ceiling in this section and still exits 0. That is a wrong answer
    wearing a success code, and it is strictly worse than a crash.
    """
    good = parse_importtime_row("import time:       744 |        744 |   _io")
    assert good == ModuleImport("_io", 744, 744)

    with pytest.raises(AssertionError, match="non-numeric timing column"):
        parse_importtime_row("import time:       n/a |        744 |   _io")
    with pytest.raises(AssertionError, match="non-numeric timing column"):
        parse_importtime_row("import time:       744 |        n/a |   _io")

    # The header row and non-rows are None, not errors.
    assert parse_importtime_row("import time: self [us] | cumulative | imported package") is None
    assert parse_importtime_row("import time: nonsense without pipes") is None


def test_the_ceilings_are_one_sided_and_an_improvement_is_never_a_red() -> None:
    """AC6. Making an import lazier reduces both statistics and must redden
    nothing.

    Same asymmetry, and same reason, as
    `test_the_pin_is_a_superset_check_and_a_missing_import_is_not_a_red`: a pin
    that reddened on an improvement would be widened or deleted by the first
    person to improve startup latency.
    """
    # Four non-product modules dilute the denominator so no single one of them
    # is self-referentially close to its own ratio's ceiling (D7 blind spot 1:
    # a non-product module IS part of its own denominator).
    halved = {
        "pdf_tooling.models": 50_000,
        "typing": 50_000,
        "email": 50_000,
        "json": 50_000,
        "os": 50_000,
    }
    partition = partition_by_product(halved)
    denominator = checked_denominator(partition)
    assert max(halved.values()) * 1000 <= MODULE_SELF_RATIO_CEILING_PER_MILLE * denominator
    assert partition.product_self_us * 1000 <= PRODUCT_IMPORT_RATIO_CEILING_PER_MILLE * denominator

    # ...and the same shape with one module raised past the ceiling DOES redden.
    raised = {**halved, "pdf_tooling.cli.common": 550_000}
    raised_partition = partition_by_product(raised)
    raised_denominator = checked_denominator(raised_partition)
    over = [
        name
        for name, cost in raised.items()
        if cost * 1000 > MODULE_SELF_RATIO_CEILING_PER_MILLE * raised_denominator
    ]
    assert over == ["pdf_tooling.cli.common"], (
        "the per-module ratio ceiling did not notice a module raised past it"
    )
    assert (
        raised_partition.product_self_us * 1000
        > PRODUCT_IMPORT_RATIO_CEILING_PER_MILLE * raised_denominator
    ), "the product/non-product ratio ceiling did not notice the same raise"

    # PDF-68 AC8, the same asymmetry for the TOTAL half. Synthesised rows rather
    # than a live census, so the direction is proven by construction rather than
    # by whatever the host happened to do this minute.
    floor_names = frozenset({"_io", "codecs"})
    improved = [
        ModuleImport("pdf_tooling.models", 20_000, 20_000),
        ModuleImport("typing", 20_000, 20_000),
        ModuleImport("_io", 5_000, 5_000),
        ModuleImport("codecs", 5_000, 5_000),
    ]
    improved_partition = partition_by_floor(improved, floor_names)
    improved_ratio = improved_partition.attributable_us / checked_startup_denominator(
        improved_partition
    )
    assert improved_ratio * 1000 <= STARTUP_COST_RATIO_CEILING_PER_MILLE, (
        f"halving every attributable import cost produced a ratio of {improved_ratio:.4f}, "
        "over the ceiling -- the total-startup-cost arm reddens on an IMPROVEMENT, which "
        "is the one direction a pin may never fire in"
    )

    # ...and the same shape with the numerator raised past the ceiling DOES redden,
    # WITHOUT any name, count or per-module share changing beyond the scaling.
    inflated = [
        ModuleImport(
            row.name,
            row.self_us * 30 if row.name not in floor_names else row.self_us,
            row.cumulative_us,
        )
        for row in improved
    ]
    inflated_partition = partition_by_floor(inflated, floor_names)
    inflated_ratio = inflated_partition.attributable_us / checked_startup_denominator(
        inflated_partition
    )
    assert inflated_ratio * 1000 > STARTUP_COST_RATIO_CEILING_PER_MILLE, (
        f"a 30x proportional inflation of the attributable set read {inflated_ratio:.4f}, "
        f"under the {STARTUP_COST_RATIO_CEILING_PER_MILLE / 1000:.3f} ceiling -- the arm "
        "does not notice the class it exists for"
    )


#: The single module-scope `PIL` import site under `src/`, DERIVED below rather
#: than transcribed. PDF-42 found the previous attribution (`cli/common.py`)
#: false, and false in a place that cost something: it was in the failure
#: message that tells a future reader which file to go and look at.
PIL_IMPORT_SITE: Final = "pdf_tooling/ops/compose.py"


def module_scope_pil_import_sites() -> list[str]:
    """Every module-scope `import PIL` / `from PIL import ...` under `src/`.

    Module scope only: an import inside `if TYPE_CHECKING:` or inside a function
    body is not in `tree.body` and costs nothing at runtime, which is exactly
    the distinction that made the old attribution look plausible -- there are
    nine `PIL` references under `src/` and eight of them are free.
    """
    sites: list[str] = []
    for path in iter_python_files(SRC):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - a broken source file is Section 1's problem
            continue
        for node in tree.body:
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            if any(name == "PIL" or name.startswith("PIL.") for name in names):
                sites.append(f"{path.relative_to(SRC).as_posix()}:{node.lineno}")
    return sorted(sites)


def test_pil_has_exactly_one_module_scope_import_site_under_src() -> None:
    """AC16. The corrected attribution is DERIVED, because a comment is one more
    hand-maintained claim.

    `PDF-30`'s closure rule: *a claim about this repository is derived, gated, or
    absent.* The claim "PIL is eager via <module>" was none of those for the
    whole life of Section 6, and it was wrong the entire time -- not rotted,
    wrong when written (`git log -S PIL -- src/pdf_tooling/cli/common.py` is
    empty). Deriving it means the next person to make `PIL` lazy is sent to the
    right file by a test rather than to the wrong one by a comment.
    """
    sites = module_scope_pil_import_sites()
    assert len(sites) == 1, (
        f"expected exactly one module-scope PIL import under src/, found {sites}. If a "
        "second one was added, the census above will already have been unaffected (PIL was "
        "already eager) -- but the attribution in this section's header and in "
        "`test_the_census_sees_imports_made_inside_product_modules`'s failure message now "
        "names only one of them, so update both or make the new one lazy."
    )
    assert sites[0].startswith(PIL_IMPORT_SITE), (
        f"the single module-scope PIL import moved to {sites[0]}; this section's header, "
        "its allowlist comment and the failure message of "
        "`test_the_census_sees_imports_made_inside_product_modules` all name "
        f"{PIL_IMPORT_SITE} and must be re-pointed together."
    )


def test_a_second_module_scope_pil_import_is_detected(tmp_path: Path) -> None:
    """AC16's RED, against a scratch copy -- the working tree is never mutated
    to observe a red (HC-4)."""
    scratch = tmp_path / "planted_module.py"
    scratch.write_text("from PIL import Image\n\n\ndef f() -> None:\n    pass\n")
    tree = ast.parse(scratch.read_text())
    found = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("PIL")
    ]
    assert found, "the derivation's own shape does not see a plain `from PIL import Image`"

    # And the shapes that must NOT count, so the derivation is not merely greedy.
    guarded = ast.parse(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from PIL import Image\n"
        "def g():\n"
        "    from PIL import ImageDraw\n"
    )
    module_scope = [
        node
        for node in guarded.body
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("PIL")
    ]
    assert module_scope == [], (
        "a TYPE_CHECKING-guarded or function-local PIL import counted as module scope; the "
        "derivation would then report sites that cost nothing at runtime"
    )
