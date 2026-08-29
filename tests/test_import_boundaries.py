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
mutation outside ``pdf_toolkit/safety/atomic.py`` fails the build.

**Two tiers, two allowlists.**

* Tier 1 — ``src/`` outside ``pdf_toolkit/safety/``: zero occurrences.
* Tier 2 — inside ``pdf_toolkit/safety/``: occurrences are confined to
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
import shutil
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
    """``src/pdf_toolkit/safety/atomic.py`` -> ``pdf_toolkit.safety.atomic``."""
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
CHOKEPOINT: Final = "pdf_toolkit.safety.atomic"

#: Tier 2's scope.
SAFETY_PACKAGE: Final = "pdf_toolkit.safety"

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

#: Tier 1 escape hatch — a write outside `pdf_toolkit.safety`.
ALLOWED_WRITE_SITES: Final[frozenset[tuple[str, str, str]]]
ALLOWED_WRITE_SITES = frozenset({})

#: Tier 2 escape hatch — a write inside `pdf_toolkit.safety` but outside
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
        "filesystem mutation outside pdf_toolkit.safety — every write goes through "
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
        "pdf_toolkit/ops/sneaky.py",
        "from pathlib import Path\n\n\ndef save(p: Path) -> None:\n    p.write_bytes(b'x')\n",
    ),
    (
        "plant-mkstemp-in-ops",
        "pdf_toolkit/ops/sneaky.py",
        "import tempfile\n\n\ndef scratch() -> None:\n    tempfile.mkstemp()\n",
    ),
    (
        "plant-mkdir-in-cli",
        "pdf_toolkit/cli/sneaky.py",
        "from pathlib import Path\n\n\ndef prepare(p: Path) -> None:\n    p.mkdir(parents=True)\n",
    ),
    (
        "plant-open-write-in-output",
        "pdf_toolkit/output/sneaky.py",
        "def dump(p: str) -> None:\n    with open(p, 'w') as fh:\n        fh.write('x')\n",
    ),
    (
        "plant-write-in-safety-but-not-atomic",
        "pdf_toolkit/safety/sneaky.py",
        "from pathlib import Path\n\n\ndef save(p: Path) -> None:\n    p.write_text('x')\n",
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
    fabricated = frozenset({("pdf_toolkit.ops.gone", "vanished", "os.replace")})
    assert stale_entries(fabricated, findings) == [
        ("pdf_toolkit.ops.gone", "vanished", "os.replace")
    ]


NON_LITERAL_MODE = "def dump(p: str, mode: str) -> None:\n    open(p, mode).close()\n"


def test_a_non_literal_mode_is_a_violation() -> None:
    found = scan_write_calls(NON_LITERAL_MODE, "pdf_toolkit.ops.computed")
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
    found = scan_write_calls(BENIGN, "pdf_toolkit.ops.benign")
    assert found == [], f"false positives: {[str(call) for call in found]}"
