"""B-086 — one password hint, at the port, saying something true (PDF-20 AC24).

WHAT THE CRITERION IS. *No verb prints an instruction naming a flag it does not
accept.* Stated as an observable, deliberately, rather than as a fix shape.

WHAT WAS MEASURED, BECAUSE THE FILED PREMISE IS WRONG IN BOTH DIRECTIONS. B-086
says `--password-file` is a flag *"only `decrypt`/`encrypt`/`permissions`
actually declare"*. Derived by execution at implementation HEAD instead of read
off the row:

* **Every one of the 26 verbs DECLARES it.** `cli/common.global_options`
  attaches the whole global block to every verb uniformly, and `--password-file`
  is deliberately ungoverned by OR-3 (`cli/common.py`'s `OUTPUT_FLAGS` note), so
  no verb refuses it. Driving `<verb> --password-file <path>` never produces the
  OR-3 exit-2 refusal.
* **Exactly three verbs HONOUR it** — `decrypt`, `permissions`, `encrypt`,
  which resolve a password through `ops/crypto.py`. On the other twenty-three it
  is parsed, validated (the group/other-readable warning fires) and then
  dropped.
* **Nineteen verbs can print the hint**, derived by running every verb's
  registered invocation against a corpus whose fixtures are all the AES-256
  encrypted document: `compress delete encrypt extract info linearize merge
  meta get meta set ocr rasterize reorder repair rotate split stamp tables text
  watermark`. E4's fifteen was an import-reachability estimate and the brief's
  "roughly ten" was lower still.

So the shipped instruction was **worse** than naming a flag the verb rejects: on
eighteen of the nineteen it named a flag the verb ACCEPTS AND SILENTLY IGNORES.
A user who followed it supplied the correct password and received the identical
exit-6 refusal, with nothing to indicate the flag had done nothing. That
`--password-file` is inert on twenty-three verbs while `PLAN.md` §5.7 states its
resolution order product-wide is a SEPARATE and larger finding, reported to the
PM rather than absorbed here: wiring the resolution chain into eighteen more
verbs is a spec, not an edit.

The surviving clause — *run `pdftoolkit decrypt` first* — is true on all
nineteen, `encrypt` included.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent.parent
SRC: Final[Path] = REPO_ROOT / "src"

#: The hint's canonical name, and the private spellings it replaced. A second
#: definition under ANY of these names is the duplication B-086 filed.
HINT_NAMES: Final[frozenset[str]] = frozenset({"PASSWORD_HINT", "_PASSWORD_HINT"})

#: The trees whose error messages reach a verb population that cannot honour the
#: flag. `cli/` and `ops/crypto.py` are excluded on purpose: those are where the
#: flag IS honoured, so naming it there is true.
MESSAGE_TREES: Final[tuple[str, ...]] = ("adapters", "ports")

#: The flag the hint must not name from those trees.
INERT_FLAG: Final[str] = "--password-file"


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def hint_definition_sites(source: str, module: str) -> list[str]:
    """Module-level assignments binding a hint name to a string."""
    tree = ast.parse(source, filename=module)
    found: list[str] = []
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
        for target in targets:
            if isinstance(target, ast.Name) and target.id in HINT_NAMES:
                found.append(f"{module}:{node.lineno}: {target.id}")
    return found


def string_constants(source: str, module: str) -> list[tuple[int, str]]:
    """Every string CONSTANT in a module — never a comment or a docstring.

    AST rather than `grep` for a stated reason: both files that used to carry a
    copy of the hint now carry a COMMENT explaining the removal, and those
    comments quote the flag. A text scan would report the explanation of the fix
    as the defect, which is how a guard gets weakened by the next author.
    """
    tree = ast.parse(source, filename=module)
    docstrings = {
        id(node.body[0].value)
        for node in [tree, *ast.walk(tree)]
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def flag_naming_message_sites(source: str, module: str, flag: str = INERT_FLAG) -> list[str]:
    return [
        f"{module}:{line}: {text!r}"
        for line, text in string_constants(source, module)
        if flag in text
    ]


# --------------------------------------------------------------------------- #
# The gate, over the real tree.
# --------------------------------------------------------------------------- #


def test_the_password_hint_has_exactly_one_definition_site() -> None:
    """D5.1. Two copies is how two verbs start disagreeing (`PDF-13`'s words)."""
    sites: list[str] = []
    for path in _python_files(SRC):
        sites.extend(hint_definition_sites(path.read_text(), str(path.relative_to(REPO_ROOT))))
    assert len(sites) == 1, (
        f"the password hint is defined in {len(sites)} place(s): {sites} -- it is owned by "
        "pdf_toolkit.ports.structure.PASSWORD_HINT and by nothing else"
    )
    assert sites[0].startswith("src/pdf_toolkit/ports/structure.py"), sites


def test_no_adapter_or_port_message_names_a_flag_the_erroring_verb_cannot_honour() -> None:
    """AC24's observable, asserted where the messages are built.

    Nineteen verbs can surface a message from these two trees and exactly one of
    them (`encrypt`) honours `--password-file`; naming it sends the other
    eighteen's users round a loop that ends where it started.
    """
    offenders: list[str] = []
    for tree in MESSAGE_TREES:
        for path in _python_files(SRC / "pdf_toolkit" / tree):
            offenders.extend(
                flag_naming_message_sites(path.read_text(), str(path.relative_to(REPO_ROOT)))
            )
    assert offenders == [], (
        f"message string(s) naming {INERT_FLAG} from a tree whose readers mostly cannot "
        f"honour it: {offenders}"
    )


def test_the_shipped_hint_names_the_verb_that_actually_resolves_it() -> None:
    """The positive half: removing a false clause must not leave a useless one."""
    from pdf_toolkit.ports.structure import PASSWORD_HINT

    assert "pdftoolkit decrypt" in PASSWORD_HINT
    assert INERT_FLAG not in PASSWORD_HINT
    assert PASSWORD_HINT.strip() == PASSWORD_HINT and PASSWORD_HINT


def test_both_structure_adapters_raise_through_the_one_hint() -> None:
    """In-process, both raise families, so the nineteen verbs are covered by
    their two common ancestors rather than by nineteen CLI spawns.

    `make ci` cost is a `decision.md` §5 R-1 concern, and the end-to-end half is
    already asserted once by `tests/test_info.py`'s re-derived auth-message row.
    """
    from pdf_toolkit.adapters import pikepdf_structure, pypdf_structure
    from pdf_toolkit.ports.structure import PASSWORD_HINT

    sources = [
        Path(pypdf_structure.__file__).read_text(),
        Path(pikepdf_structure.__file__).read_text(),
    ]
    interpolating = sum(source.count("{PASSWORD_HINT}") for source in sources)
    assert interpolating >= 8, (
        f"only {interpolating} message site(s) interpolate the shared hint; the two structure "
        "adapters carried five copies of the same instruction before PDF-20 and every one of "
        "them must now read from the port"
    )
    for source in sources:
        assert "PASSWORD_HINT" in source
    assert PASSWORD_HINT


# --------------------------------------------------------------------------- #
# Proof that both guards fire. Synthetic sources, never a mutated `src/`.
# --------------------------------------------------------------------------- #

_A_SECOND_COPY = '''
"""A module docstring mentioning --password-file, which must NOT count."""
from typing import Final
_PASSWORD_HINT: Final[str] = "supply one with --password-file PATH"
'''

_ONLY_A_COMMENT = """
from typing import Final
# The --password-file clause was removed by PDF-20; see the port.
NOT_THE_HINT: Final[str] = "run 'pdftoolkit decrypt' first"
"""


def test_the_duplicate_definition_check_fires() -> None:
    assert hint_definition_sites(_A_SECOND_COPY, "widget.py") == ["widget.py:4: _PASSWORD_HINT"]
    assert hint_definition_sites(_ONLY_A_COMMENT, "widget.py") == []


def test_the_flag_naming_check_fires_on_a_string_and_not_on_a_comment() -> None:
    """The discriminating half. A `grep` would fail both ways round: it would
    miss nothing, but it would also report the comment that explains the fix."""
    assert flag_naming_message_sites(_A_SECOND_COPY, "widget.py") == [
        "widget.py:4: 'supply one with --password-file PATH'"
    ]
    assert flag_naming_message_sites(_ONLY_A_COMMENT, "widget.py") == []


def test_the_string_scan_sees_a_real_module_at_all() -> None:
    """Non-vacuity: a `string_constants` that returned nothing would make the
    guard above green over an empty set."""
    source = (SRC / "pdf_toolkit" / "ports" / "structure.py").read_text()
    found = string_constants(source, "ports/structure.py")
    assert len(found) > 20, f"the string scan found only {len(found)} constant(s)"
    assert any("AES-256" == text for _, text in found), "the scan missed a known constant"


def test_the_docstring_exclusion_does_not_swallow_real_strings() -> None:
    """The exclusion is narrow: only the FIRST statement of a module, function
    or class body. A string used as a value is still seen."""
    source = 'def f():\n    """doc"""\n    return "--password-file"\n'
    assert flag_naming_message_sites(source, "widget.py") == ["widget.py:3: '--password-file'"]


@pytest.mark.parametrize("name", sorted(HINT_NAMES))
def test_the_hint_name_roster_is_not_empty(name: str) -> None:
    """A `HINT_NAMES` that lost its members would make the duplicate check pass
    over nothing at all."""
    assert name
