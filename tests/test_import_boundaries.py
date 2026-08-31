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
import subprocess
import sys
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
ADAPTER_PACKAGE: Final = "pdf_toolkit.adapters"

#: The one module permitted to spawn. Spelled as a module path to match
#: `module_name()`; `tests/test_license_policy.py` spells the same file as a
#: path, and both are asserted to point at a file that exists.
SPAWN_CHOKEPOINT: Final = "pdf_toolkit.adapters.subprocess_util"

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
SPAWN_HELPER_QUALIFIED: Final = "pdf_toolkit.adapters.subprocess_util"


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
    `from pdf_toolkit.adapters import subprocess_util`, and a bare `run(...)`
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
            "pdf_toolkit/ops/sneaky.py",
            "import pikepdf\n",
            KIND_ENGINE_IMPORT,
        ),
        (
            "pdf_toolkit/cli/sneaky.py",
            "import subprocess\n",
            KIND_SPAWN_SURFACE,
        ),
        (
            "pdf_toolkit/adapters/sneaky.py",
            "from pdf_toolkit.adapters import subprocess_util\n\n\n"
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
        "pdf_toolkit/ops/sneaky.py",
        "import pikepdf\n\n\ndef go():\n    return pikepdf\n",
    ),
    (
        "plant-pypdf-from-import-in-cli",
        "pdf_toolkit/cli/sneaky.py",
        "from pypdf import PdfReader\n\n\ndef go():\n    return PdfReader\n",
    ),
    (
        "plant-reportlab-import-in-ports",
        "pdf_toolkit/ports/sneaky.py",
        "import reportlab.pdfgen\n\n\ndef go():\n    return reportlab\n",
    ),
    (
        "plant-pdfplumber-import-in-output",
        "pdf_toolkit/output/sneaky.py",
        "import pdfplumber\n\n\ndef go():\n    return pdfplumber\n",
    ),
    (
        "plant-pypdfium2-import-in-safety",
        "pdf_toolkit/safety/sneaky.py",
        "import pypdfium2\n\n\ndef go():\n    return pypdfium2\n",
    ),
    (
        "plant-subprocess-import-in-ops",
        "pdf_toolkit/ops/sneaky.py",
        "import subprocess\n\n\ndef go():\n    return subprocess\n",
    ),
    (
        "plant-os-system-in-cli",
        "pdf_toolkit/cli/sneaky.py",
        "import os\n\n\ndef go():\n    os.system('ls')\n",
    ),
    (
        "plant-pty-spawn-in-adapters",
        "pdf_toolkit/adapters/sneaky.py",
        "import pty\n\n\ndef go():\n    pty.spawn(['ls'])\n",
    ),
    (
        "plant-forbidden-binary-through-the-helper",
        "pdf_toolkit/adapters/sneaky.py",
        "from pdf_toolkit.adapters import subprocess_util\n\n\n"
        "def go():\n    return subprocess_util.run(['gs', '-q'], timeout=1)\n",
    ),
    (
        "plant-computed-argv0-through-the-helper",
        "pdf_toolkit/adapters/sneaky.py",
        "from pdf_toolkit.adapters import subprocess_util\n\n\n"
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
from pdf_toolkit.adapters import subprocess_util

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
    module = "pdf_toolkit.ops.benign"
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
        "pdf_toolkit.ports",
        "pdf_toolkit.ports.structure",
        "pdf_toolkit.ports.raster",
        "pdf_toolkit.ports.compose",
        "pdf_toolkit.ports.text",
        "pdf_toolkit.ports.ocr",
        "pdf_toolkit.ports.office",
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
CLI_PACKAGE: Final = "pdf_toolkit.cli"

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
        "pdf_toolkit/ops/sneaky.py",
        "import typer\n\n\ndef go():\n    return typer\n",
    ),
    (
        "plant-typer-from-import-in-safety",
        "pdf_toolkit/safety/sneaky.py",
        "from typer import Typer\n\n\ndef go():\n    return Typer\n",
    ),
    (
        "plant-click-import-in-ports",
        "pdf_toolkit/ports/sneaky.py",
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
    found = scan_cli_framework_imports(BENIGN_SECTION_3, "pdf_toolkit.ops.benign")
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
        "pdf_toolkit/cli/cmd_sneaky.py",
        "from pdf_toolkit.safety.confirm import require_confirmation\n\n\n"
        "def go(config):\n"
        "    if not config.dry_run and config.in_place:\n"
        "        require_confirmation(config.safety, input_count=2, in_place=True,\n"
        "                             rerun_hint='x')\n",
    ),
    (
        "plant-a-nested-guard",
        "pdf_toolkit/cli/cmd_nested.py",
        "from pdf_toolkit.safety import confirm\n\n\n"
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
        "pdf_toolkit/cli/cmd_shortcircuit.py",
        "from pdf_toolkit.safety.confirm import require_confirmation\n\n\n"
        "def go(cfg):\n"
        "    cfg.dry_run or require_confirmation(cfg.safety, input_count=2,\n"
        "                                        in_place=True, rerun_hint='x')\n",
    ),
    (
        "plant-a-ternary-guard",
        "pdf_toolkit/cli/cmd_ternary.py",
        "from pdf_toolkit.safety.confirm import require_confirmation\n\n\n"
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

from pdf_toolkit.safety.confirm import require_confirmation


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
    found = scan_dry_run_bypass(BENIGN_SECTION_4, "pdf_toolkit.cli.cmd_benign")
    assert found == [], f"false positives: {[str(item) for item in found]}"
