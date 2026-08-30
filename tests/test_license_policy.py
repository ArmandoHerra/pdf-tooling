"""Forbidden-library AST walk — PLAN.md §7.2 mechanism 2.

This is the half of the G2 guarantee that a dependency scan structurally
CANNOT provide. `scripts/licenses.py` sees the dependency graph; it cannot see
the *call graph*. The realistic violation of PLAN §7.2 is not a PyMuPDF entry
in `pyproject.toml` — it is a three-line convenience shell-out to `gs` or
`pdftoppm` added under deadline, which no license scanner will ever notice.

HOW IT LOOKS — AST ONLY, EXACT EQUALITY, NEVER A TEXT GREP
----------------------------------------------------------
The checker never greps source text. It parses each file with `ast` and
inspects four node shapes, comparing by EXACT EQUALITY on a normalized name:

  1. imports              `import fitz`, `from fitz import x`   (top-level name)
  2. dynamic imports      `importlib.import_module("fitz")`, `__import__(...)`
  3. subprocess argv[0]   `subprocess.run(["gs", ...])`, `os.system("gs ...")`
  4. `shutil.which`       `shutil.which("gs")`

Consequently a local variable `gs`, a function `parse_gs_tokens`, a dict key
`{"gs": 2}` and the word `flags` are NOT module names or argv[0] literals and
are never examined. The negative self-test below is the mechanized proof of
exactly that, and it runs on every CI run forever — not once at implementation
time.

VACUITY, STATED
---------------
The two chokepoint assertions (`test_subprocess_chokepoint*`) passed VACUOUSLY
at PDF-02 time: `src/` contained no `subprocess` anywhere. They are LIVE as of
PDF-05, which introduced `adapters/subprocess_util.py` as the only sanctioned
spawn point. A forward constraint that states its own vacuity is not a silent
no-op.

PDF-02 predicted that PDF-05 would "meet them by construction". It could not:
the non-literal-argv[0] refusal in `scan_chokepoint` applied to the chokepoint
file as well, and a generic spawn wrapper takes argv as a parameter, so that
assertion went red on a correct implementation. PDF-05 moved the refusal inside
the `is_chokepoint` branch and put the compensating call-site check in
`tests/test_import_boundaries.py` Section 2. See the comment at the moved block.
"""

from __future__ import annotations

import ast
import shlex
import sys
import tomllib
from pathlib import Path
from typing import Final, NamedTuple

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
SRC: Final = REPO_ROOT / "src"
CHOKEPOINT: Final = "pdf_toolkit/adapters/subprocess_util.py"

# PLAN.md §7.2 mechanism 2 — the plan's list, verbatim and complete.
PLAN_FORBIDDEN: Final = (
    "fitz",
    "pymupdf",
    "pdf2image",
    "pdftoppm",
    "pdftotext",
    "pdftocairo",
    "pdfinfo",
    "ghostscript",
    "gs",
    "ocrmypdf",
    "img2pdf",
    "pandoc",
    "pdftk",
)
# Deliberate TIGHTENING by PDF-02. Same libraries, same licenses, same leak
# class; names the plan's list predates or abbreviates. Tightening the forbidden
# NAME list is permitted and expected; widening the license DENY PATTERN
# (AGPL|GPL|LGPL) is NOT (PLAN §12 R-11 — MPL-2.0 is permitted).
#   pymupdf4llm : ships as part of the same AGPL-or-commercial PyMuPDF family.
#   poppler     : the python-poppler binding (GPL) — the import-shaped version
#                 of the same leak the four poppler binaries represent.
#   the rest    : the remaining poppler-utils binaries; one apt package, one
#                 license, and exactly as tempting as pdftotext.
EXTRA_FORBIDDEN: Final = (
    "pymupdf4llm",
    "poppler",
    "pdfimages",
    "pdftops",
    "pdfseparate",
    "pdfunite",
    "pdfdetach",
    "pdfattach",
    "pdfsig",
    "pdffonts",
)
FORBIDDEN: Final = frozenset(PLAN_FORBIDDEN + EXTRA_FORBIDDEN)

# Non-Python files permitted under src/. Anything else fails the totality check,
# which keeps "walks every file under src/" literally true without ever running
# a regex over prose.
NON_PYTHON_ALLOWED: Final = ("py.typed",)

SPAWN_FUNCS: Final = frozenset({"run", "Popen", "call", "check_call", "check_output"})
OS_SPAWN_PREFIXES: Final = ("exec", "spawn")


class Finding(NamedTuple):
    name: str
    line: int
    kind: str
    filename: str

    def __str__(self) -> str:
        return f"{self.filename}:{self.line}: forbidden {self.kind} '{self.name}'"


def normalize(name: str) -> str:
    """Lowercase and fold '-'/'_' so PyMuPDF, pymupdf and py_mupdf all collapse."""
    return name.strip().lower().replace("-", "").replace("_", "")


NORMALIZED_FORBIDDEN: Final = frozenset(normalize(n) for n in FORBIDDEN)


def _is_forbidden(name: str) -> bool:
    return normalize(name) in NORMALIZED_FORBIDDEN


def _basename(value: str) -> str:
    """Basename an argv[0] so '/usr/bin/gs' matches 'gs'."""
    return PurePosixPathBasename(value)


def PurePosixPathBasename(value: str) -> str:  # noqa: N802
    cleaned = value.replace("\\", "/").rstrip("/")
    return cleaned.rsplit("/", 1)[-1] if "/" in cleaned else cleaned


def _dotted(func: ast.expr) -> str:
    """Render a call target as a dotted string: subprocess.run, shutil.which, which."""
    parts: list[str] = []
    node: ast.expr | None = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _str_const(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _module_level_literals(tree: ast.Module) -> dict[str, str]:
    """Module-level names bound to a string literal (covers Final[str] = "...")."""
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            value = _str_const(node.value)
            if value is not None:
                out[node.target.id] = value
        elif isinstance(node, ast.Assign):
            value = _str_const(node.value)
            if value is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = value
    return out


def _resolve_str(node: ast.expr, literals: dict[str, str]) -> str | None:
    """A string literal, or a module-level name bound to one (covers Final[str])."""
    literal = _str_const(node)
    if literal is not None:
        return literal
    if isinstance(node, ast.Name):
        return literals.get(node.id)
    return None


def _argv0(node: ast.expr, literals: dict[str, str]) -> str | None:
    """Extract argv[0] from a spawn call's first argument, if it is static.

    PLAN §8 / PDF-02 Design §7.3: argv[0] must be a string literal or a
    module-level Final[str] bound to one. Names are resolved in BOTH positions
    -- `subprocess.run(GS_CMD)` and `subprocess.run([GS_BIN, "-x"])` -- because
    a checker that only resolved the scalar form would miss the list form,
    which is the form real code overwhelmingly uses.
    """
    if isinstance(node, ast.List | ast.Tuple):
        return _resolve_str(node.elts[0], literals) if node.elts else None
    value = _resolve_str(node, literals)
    if value is None:
        return None
    try:
        parts = shlex.split(value)
    except ValueError:
        return None
    return parts[0] if parts else None


def scan_forbidden_names(source: str, filename: str) -> list[Finding]:
    """The four-shape AST walk. Returns every forbidden-name finding."""
    tree = ast.parse(source, filename=filename)
    literals = _module_level_literals(tree)
    findings: list[Finding] = []

    for node in ast.walk(tree):
        # 1. imports — top-level module name only
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if _is_forbidden(top):
                    findings.append(Finding(top, node.lineno, "import", filename))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if _is_forbidden(top):
                    findings.append(Finding(top, node.lineno, "import", filename))
        elif isinstance(node, ast.Call):
            target = _dotted(node.func)
            arg0 = node.args[0] if node.args else None

            # 2. dynamic imports
            if target in {"importlib.import_module", "import_module", "__import__"}:
                value = _str_const(arg0)
                if value and _is_forbidden(value.split(".")[0]):
                    findings.append(
                        Finding(value.split(".")[0], node.lineno, "dynamic import", filename)
                    )

            # 3. subprocess / os spawn argv[0]
            elif arg0 is not None and _is_spawn(target):
                argv0 = _argv0(arg0, literals)
                if argv0 and _is_forbidden(_basename(argv0)):
                    findings.append(
                        Finding(_basename(argv0), node.lineno, "subprocess argv[0]", filename)
                    )

            # 4. shutil.which
            elif target in {"shutil.which", "which"}:
                value = _str_const(arg0)
                if value and _is_forbidden(_basename(value)):
                    findings.append(
                        Finding(_basename(value), node.lineno, "shutil.which", filename)
                    )

    return findings


def _is_spawn(target: str) -> bool:
    head, _, tail = target.rpartition(".")
    if head in {"subprocess", "sp"} and tail in SPAWN_FUNCS:
        return True
    if head == "os":
        return tail == "system" or tail.startswith(OS_SPAWN_PREFIXES)
    return False


def scan_chokepoint(source: str, filename: str, *, is_chokepoint: bool) -> list[Finding]:
    """Assert `subprocess_util.py` is the ONLY spawn point under src/ (PLAN §8)."""
    tree = ast.parse(source, filename=filename)
    literals = _module_level_literals(tree)
    findings: list[Finding] = []

    for node in ast.walk(tree):
        if not is_chokepoint:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "subprocess":
                        findings.append(
                            Finding(
                                "subprocess", node.lineno, "import outside chokepoint", filename
                            )
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] == "subprocess":
                    findings.append(
                        Finding("subprocess", node.lineno, "import outside chokepoint", filename)
                    )
            elif isinstance(node, ast.Call):
                target = _dotted(node.func)
                head, _, tail = target.rpartition(".")
                if head == "os" and (tail == "system" or tail.startswith(OS_SPAWN_PREFIXES)):
                    findings.append(
                        Finding(target, node.lineno, "os spawn outside chokepoint", filename)
                    )
            if isinstance(node, ast.Call) and node.args and _is_spawn(_dotted(node.func)):
                # A spawn whose argv[0] arrives in a non-literal cannot be checked
                # by any static tool, so it is refused outright rather than waved
                # through -- OUTSIDE the chokepoint.
                #
                # AMENDED BY PDF-05, and this is the whole reason the amendment
                # exists. This check used to sit outside the `is_chokepoint`
                # branch, which was correct only while `src/` contained no spawn
                # at all (see the VACUITY note in the module docstring). The
                # chokepoint is a GENERIC wrapper: `subprocess_util.run(argv, ...)`
                # takes argv as a function parameter, so `_argv0` resolves None by
                # construction and this assertion turned red the moment the
                # chokepoint was written as designed. A wrapper with a non-literal
                # argv[0] is not a leak -- it is what a chokepoint IS.
                #
                # The refusal is NOT weakened, it is MOVED to where it can still
                # bite: `tests/test_import_boundaries.py` Section 2 requires every
                # `subprocess_util.run(...)` CALL SITE under `src/` to pass a
                # statically resolvable argv[0] whose basename is not forbidden.
                # Between the two files, every argv[0] in the product is still
                # statically checked; only the pass-through inside the wrapper is
                # exempt.
                if _argv0(node.args[0], literals) is None:
                    findings.append(
                        Finding(_dotted(node.func), node.lineno, "non-literal argv[0]", filename)
                    )

    return findings


def _src_python_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*") if p.suffix in {".py", ".pyi"} and p.is_file())


# --------------------------------------------------------------------------
# The gate itself, over the real tree.
# --------------------------------------------------------------------------


def test_no_forbidden_names_under_src() -> None:
    """No forbidden library or binary name appears anywhere under src/."""
    findings: list[Finding] = []
    for path in _src_python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:  # pragma: no cover - defensive
            raise AssertionError(f"{rel}: not valid UTF-8 ({exc})") from exc
        try:
            findings.extend(scan_forbidden_names(source, rel))
        except SyntaxError as exc:
            # A leak must not be able to hide behind an unparseable module.
            raise AssertionError(f"{rel}: SyntaxError at line {exc.lineno}: {exc.msg}") from exc

    assert not findings, "PLAN §7.2 forbidden names found under src/:\n" + "\n".join(
        str(f) for f in findings
    )


def test_walk_covers_every_file_under_src() -> None:
    """Every file under src/ is either parsed as Python or explicitly allowed."""
    assert SRC.is_dir(), f"{SRC} does not exist"
    parsed = {p.relative_to(REPO_ROOT).as_posix() for p in _src_python_files()}
    assert parsed, "the walk parsed zero files — it is not measuring anything"

    strays = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in sorted(SRC.rglob("*"))
        if p.is_file()
        and p.suffix not in {".py", ".pyi"}
        and p.name not in NON_PYTHON_ALLOWED
        and "__pycache__" not in p.parts
    ]
    assert not strays, (
        "files under src/ that the AST walk cannot read and that are not in "
        f"NON_PYTHON_ALLOWED: {strays}"
    )


def test_subprocess_chokepoint() -> None:
    """Only adapters/subprocess_util.py may spawn. VACUOUS TODAY — see module docstring.

    PDF-05 is the spec that first makes this bite.
    """
    findings: list[Finding] = []
    for path in _src_python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        is_chokepoint = rel.endswith(CHOKEPOINT)
        findings.extend(
            scan_chokepoint(path.read_text(encoding="utf-8"), rel, is_chokepoint=is_chokepoint)
        )
    assert not findings, "spawn-chokepoint violations (PLAN §8):\n" + "\n".join(
        str(f) for f in findings
    )


def test_no_forbidden_dependency_in_pyproject() -> None:
    """Mechanizes the 'never an extra' half of PLAN §7.2's title."""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data.get("project", {})
    declared: list[str] = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        declared.extend(extra)

    offenders = []
    for spec in declared:
        # Strip extras/markers/version pins down to the bare distribution name.
        name = spec.split(";")[0].split("[")[0]
        for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", " "):
            name = name.split(sep)[0]
        if _is_forbidden(name):
            offenders.append(spec)
    assert not offenders, f"forbidden distributions declared in pyproject.toml: {offenders}"


# --------------------------------------------------------------------------
# The checker's OWN self-tests — permanent, not one-off.
#
# Neither synthetic source is ever committed as a file under src/ or testdata/.
# They are built at test time. A sibling cycle's pushed full-history secret scan
# went red on the gate's own committed self-test fixture; a committed file
# containing a real-looking forbidden call is the same trap, and secret-scan
# runs with fetch-depth: 0, so a committed fixture is unforgettable.
# --------------------------------------------------------------------------

POSITIVE_SOURCE: Final = '''\
"""Synthetic violator built at test time — never committed under src/."""
import subprocess
import shutil
import fitz


def render(path):
    subprocess.run(["gs", "-sDEVICE=pdfwrite", path], check=False)
    return shutil.which("pdftotext")
'''

NEGATIVE_SOURCE: Final = '''\
"""Synthetic NON-violator: every 'gs' here is an unrelated identifier."""
from typing import Final

TESSERACT_BIN: Final[str] = "tesseract"

gs = 1
flags = "--dpi=300"
settings = {"gs": 2}


def parse_gs_tokens(text):
    """gs appears in this name and this docstring and is not a forbidden call."""
    return [t for t in text.split() if t != "gs"]


def run_ocr(subprocess):
    return subprocess.run([TESSERACT_BIN, "--version"], check=False)
'''


def test_self_positive_detects_all_three_leaks() -> None:
    """import fitz + gs argv[0] + shutil.which('pdftotext') → exactly three findings."""
    findings = scan_forbidden_names(POSITIVE_SOURCE, "<synthetic-positive>")
    names = sorted(f.name for f in findings)
    kinds = sorted(f.kind for f in findings)
    assert len(findings) == 3, f"expected exactly 3 findings, got {len(findings)}: {findings}"
    assert names == ["fitz", "gs", "pdftotext"], names
    assert kinds == ["import", "shutil.which", "subprocess argv[0]"], kinds
    assert all(f.line > 0 for f in findings)


def test_self_negative_does_not_false_positive_on_gs() -> None:
    """`gs = 1`, `parse_gs_tokens`, `{"gs": 2}`, `flags` → ZERO findings.

    This is the mechanized proof that the walk is an AST walk and not a text
    grep: the string 'gs' occurs seven times in NEGATIVE_SOURCE.
    """
    assert "gs" in NEGATIVE_SOURCE  # the bait is really there
    findings = scan_forbidden_names(NEGATIVE_SOURCE, "<synthetic-negative>")
    assert findings == [], f"false positives on non-call 'gs' occurrences: {findings}"

    # And inside the chokepoint, a Final[str] argv[0] is accepted, not refused.
    choke = scan_chokepoint(NEGATIVE_SOURCE, "<synthetic-negative>", is_chokepoint=True)
    assert choke == [], f"chokepoint false positives: {choke}"


def test_self_negative_source_is_not_committed() -> None:
    """The synthetic sources live in this module, not on disk under src/."""
    for path in _src_python_files():
        text = path.read_text(encoding="utf-8")
        assert "sDEVICE=pdfwrite" not in text, f"synthetic violator committed at {path}"


def test_non_literal_argv0_is_refused_outside_the_chokepoint() -> None:
    """A spawn whose argv[0] is computed cannot be checked statically → refused.

    AMENDED BY PDF-05 together with `scan_chokepoint`: this asserted
    `is_chokepoint=True` while `src/` had no spawn at all, and the chokepoint is
    precisely the one place a non-literal argv[0] is legitimate. The refusal
    itself is unchanged and is asserted here where it still applies; the
    companion assertion below pins the exemption so it cannot silently widen.
    """
    source = "import subprocess\n\n\ndef go(name):\n    subprocess.run([name, '-x'], check=False)\n"
    findings = scan_chokepoint(source, "<synthetic-dynamic>", is_chokepoint=False)
    assert any(f.kind == "non-literal argv[0]" for f in findings), findings


def test_the_chokepoint_may_pass_argv_through() -> None:
    """The generic wrapper is exempt — and ONLY the wrapper.

    `tests/test_import_boundaries.py` Section 2 carries the compensating check
    over the wrapper's call sites, so no argv[0] in the product goes unexamined.
    """
    source = "import subprocess\n\n\ndef go(name):\n    subprocess.run([name, '-x'], check=False)\n"
    assert scan_chokepoint(source, "<synthetic-dynamic>", is_chokepoint=True) == []


def test_forbidden_set_contains_the_plan_list() -> None:
    """The plan's thirteen names are present verbatim; extras only tighten."""
    assert set(PLAN_FORBIDDEN) <= set(FORBIDDEN)
    assert len(PLAN_FORBIDDEN) == 13
    for name in ("fitz", "pymupdf", "gs", "pdftk", "pandoc", "img2pdf", "ocrmypdf"):
        assert _is_forbidden(name)
    # Normalization folds separators and case.
    assert _is_forbidden("PyMuPDF")
    assert _is_forbidden("py_mupdf")
    assert _is_forbidden("/usr/bin/gs".rsplit("/", maxsplit=1)[-1])
    # ...and does not fold unrelated names.
    assert not _is_forbidden("pypdf")
    assert not _is_forbidden("pypdfium2")
    assert not _is_forbidden("pikepdf")
    assert not _is_forbidden("tesseract")


if __name__ == "__main__":  # pragma: no cover
    sys.exit("run via pytest")
