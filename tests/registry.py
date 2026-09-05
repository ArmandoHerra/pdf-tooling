"""The verb registry and the registration contract — `PLAN.md` §10.

`discover_verbs()` walks the **live** Typer/click command tree with **no skip
list, no filter and no hard-coded verb name** (AC5) — a new verb registered
on `app` is automatically covered the next time the suite runs. `INVOCATIONS`
closes the one gap a generic walk cannot: a harness cannot know that a future
`rotate` needs `--angle`, so each verb that needs a valid, verb-specific argv
tail registers one here. `test_every_verb_is_registered` (AC10) fails the
suite the moment a verb is discovered but not registered.

A NAMED DEVIATION FROM THE LITERAL DESIGN — `is_mutating`
-----------------------------------------------------------
Design intended `is_mutating` to be derived from whether a verb's own click
command declares `-O/--output`, `--out-dir` or `--in-place`. That signal does
not exist in this codebase: `pdf_toolkit.cli.common.global_options` attaches
the **entire** global flag block — including all three of those — to *every*
verb uniformly (`PLAN.md` §4.2), and a verb is structurally forbidden from
redeclaring any of those names on its own signature (`_attach()` raises
`TypeError` if it tries). Checking for their presence on `cmd.params` is
therefore true for `version`/`doctor`/`info` today even though none of them
writes anything, and parameterizing the no-clobber (C11) and bulk-destructive
(C13) checks over a universally-true predicate would assert a refusal from
verbs that structurally cannot refuse — a real, verified failure, not a
hypothetical one (see this spec's Implementation Log).

The working predicate is still fully structural and still classifies a new
verb automatically, without a hand-maintained per-verb list: it walks the
verb's own callback module and every `pdf_toolkit.*` module it imports,
transitively and bounded, for a reference to `AtomicWriter` — the one write
chokepoint (`PLAN.md` §5.2, `PDF-04`). A verb that never reaches the
chokepoint cannot mutate anything the safety spine protects, which is what
`is_mutating` is actually meant to signal.

THE DIMENSION SURFACE — X-157, and `PDF-22` CONSUMES IT RATHER THAN REBUILDING IT
---------------------------------------------------------------------------------
Every matrix dimension in this suite comes from here, derived from the live
registry or a live enum, never typed beside it:

* ``discover_verbs()`` — the verb dimension, walked off the live Typer tree.
* ``OUTPUT_FLAGS`` — the destination-flag dimension, RE-EXPORTED from
  ``pdf_toolkit.cli.common`` so a consumer has one import to make. It is the
  product's own tuple, not a copy: there is nothing here that can drift from it.
* ``output_formats()`` — every member of the live ``OutputFormat`` StrEnum.
  Derived from the enum; a renderer added there joins every consuming matrix
  with zero author action, and `tests/test_derived_dimensions.py` asserts the
  renderer's own dispatch was wired to match.
* ``tty_modes()`` — the ``isatty()`` branch as an explicit two-member axis
  rather than an implicit one.
* ``PDF_08_VERBS`` — the ONE place PDF-08's four page verbs are named, with a
  live membership tie (`test_the_governed_verb_set_is_live`). AC30 forbids a
  typed verb list in PDF-08's tests; this is the declaration that let eleven of
  them be deleted, and it is mechanically enforced tree-wide.
* ``expectation()`` — the safe shape for per-verb DATA: a mapping keyed by a
  derived verb, with a lookup that fails BY NAME when a new verb has no
  expectation declared, instead of skipping it silently.

`PDF-17` exports and pins these. It does not cross them, cap them, or write a
single secret-leak case: the cardinality budget is `PDF-22`'s own deliverable.
"""

from __future__ import annotations

import ast
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import typer

from pdf_toolkit.cli import common as _common
from pdf_toolkit.cli.common import OUTPUT_FLAGS
from pdf_toolkit.cli.main import PROG_NAME, app
from pdf_toolkit.output import OutputFormat

__all__ = [
    "INVOCATIONS",
    "OUTPUT_FLAGS",
    "OUTPUT_FLAG_INVOCATIONS",
    "PDF_08_VERBS",
    "REPO_ROOT",
    "Invocation",
    "PtyResult",
    "VerbSpec",
    "console_script",
    "derive_password_file_pairs",
    "discover_groups",
    "discover_verbs",
    "operand_metavar",
    "operand_metavars",
    "out_dir_batch_verbs",
    "expectation",
    "output_formats",
    "output_shape_states",
    "run_cli",
    "run_cli_with_pty",
    "tty_modes",
]

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SRC: Final[Path] = REPO_ROOT / "src"

#: The name the write chokepoint is imported/referenced as. A verb "mutates"
#: exactly when this name is reachable from its callback module.
_ATOMIC_WRITER_NAME: Final[str] = "AtomicWriter"

#: Bounded transitive-import depth for the `is_mutating` scan. The current
#: L1(cli)->L2(ops)->L3(safety) call graph is at most two hops; four is
#: generous headroom without letting the scan wander into the whole tree.
_MAX_IMPORT_HOPS: Final[int] = 4


@dataclass(frozen=True, slots=True)
class VerbSpec:
    """One discovered command, with its structural predicates already resolved."""

    name: str
    """Space-joined path, e.g. ``"info"`` or (once a group exists) ``"meta get"``."""

    path: tuple[str, ...]
    is_group: bool
    takes_input_paths: bool
    is_page_addressing: bool
    is_mutating: bool
    consumes: tuple[str, ...] = ()
    """OR-3 (Design §D12, PDF-07): the ``OUTPUT_FLAGS`` this verb declared it
    consumes, read off the live command's own callback module via
    ``cli.common.consumed_output_flags``. Defaulted so a `VerbSpec` built by
    hand (a unit test's own throwaway) does not have to name it."""

    variadic_operands: bool = False
    """Whether this verb's path-taking operand accepts MORE THAN ONE input.

    Read off the live command object's own ``nargs`` (``-1`` variadic, ``1``
    single), never off the source text. The annotation beside
    ``operand_argument()`` is the authoring surface (``Annotated[list[Path],
    ...]`` vs ``Annotated[Path, ...]``); ``nargs`` is what the framework
    resolved it to, and it is the thing a batch's behaviour actually turns on.

    This is what excludes ``split`` from the ``--out-dir`` batch population
    BY DERIVATION rather than by a literal: a future ``split`` that grew a
    variadic operand would enter the population with zero author action."""


@dataclass(frozen=True, slots=True)
class Invocation:
    """A valid argv tail for one verb, built against the generated corpus.

    ``build`` receives the session ``corpus`` fixture and the test's own
    ``tmp_path``, and returns the argv that follows the verb name on the
    command line.
    """

    build: Callable[[object, Path], list[str]]
    destructive: bool = False
    """Participates in the bulk/`-y` non-TTY arm (C13)."""
    destructive_build: Callable[[object, Path], list[str]] | None = None
    """B-079's C13 population seed. ``build`` is SHARED by C1/C9/C10/C11/C12/
    C15 -- most of those need a single-input, ``-O``-terminated shape (C11
    in particular relies on appending its OWN ``-O <existing target>`` and
    Click's last-scalar-wins landing on that override, per
    ``_compress_invocation``'s own docstring), which is neither bulk nor
    ``--in-place`` and therefore cannot exercise C13's bulk-destructive
    ground at all. Rather than mutate ``build`` itself and risk every OTHER
    check silently degrading (C11's override would turn into a B-076
    ``--in-place``/``--output`` conflict, C12's plain run would newly hit
    the very confirmation gate C13 exists to test), a verb whose
    ``destructive=True`` supplies its OWN bulk, ``--in-place`` argv here.

    ``None`` is the default and is correct for every ``destructive=False`` row.
    It is NOT a fallback: PDF-17 deleted the ``destructive_build or build``
    fallback both C13 rows used to take, and
    ``test_a_destructive_row_supplies_its_own_bulk_argv`` now fails the suite
    when a ``destructive=True`` row omits one. That fallback was B-047's
    reinstatement path -- the next author to write ``destructive=True`` without
    a ``destructive_build`` would have silently re-shared C12's single-input
    ``-O`` tail, C13 would have stopped discriminating, and no test would have
    failed. Two rows set it today (``compress``, B-079; ``ocr``, PDF-15), not
    one."""
    requires_engine: str | None = None
    """A port name from ``pdf_toolkit.ports.PORTS`` (e.g. ``"OfficeConverter"``)
    that this verb's registered invocation genuinely needs to REACH exit 0,
    or ``None`` (the default, and every entry but ``convert`` today).

    This is a property of the VERB, not of any one flag row: `convert`'s
    whole job is the conversion (unlike `ocr`, which has an engine-free path
    via `--skip-text-pages` -- see this file's own PDF-15 section note), so
    every registered invocation and every declared-``OUTPUT_FLAG_INVOCATIONS``
    row for `convert` needs the same engine. `tests/test_cli_contract.py`
    reads this single declaration for both C12 (which calls `build` directly)
    and C14's honoured side (which calls a per-flag `OUTPUT_FLAG_INVOCATIONS`
    lambda instead) -- one declaration, both consumers, per this fix's own
    instruction not to duplicate it onto a second registry.

    Resolved the same way `doctor` and `tests/conftest.py`'s own
    ``@pytest.mark.requires`` marker resolve an engine --
    ``pdf_toolkit.ports.resolve(port).available`` -- never an independent
    ``shutil.which`` and never an env var or hard-coded platform check. When
    unavailable, the consuming test SKIPS with a reason naming the missing
    engine (never passes vacuously); when available, the row runs for real,
    which is what keeps `engines-present`'s own
    ``scripts/assert_skips.py --expect-zero`` green because the rows RAN, not
    because they vanished."""


def _dotted_to_path(dotted: str) -> Path | None:
    """``pdf_toolkit.cli.cmd_info`` -> its file, or ``None`` if it is not local."""
    parts = dotted.split(".")
    candidate = SRC.joinpath(*parts).with_suffix(".py")
    if candidate.is_file():
        return candidate
    package_init = SRC.joinpath(*parts, "__init__.py")
    if package_init.is_file():
        return package_init
    return None


def _imports_and_references(path: Path) -> tuple[set[str], bool]:
    """One module's own `pdf_toolkit.*` imports, and whether it names *AtomicWriter*."""
    tree = ast.parse(path.read_text(), filename=str(path))
    imported: set[str] = set()
    references_writer = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("pdf_toolkit")
        ):
            imported.add(node.module)
            if any(alias.name == _ATOMIC_WRITER_NAME for alias in node.names):
                references_writer = True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("pdf_toolkit"):
                    imported.add(alias.name)
        elif isinstance(node, ast.Name) and node.id == _ATOMIC_WRITER_NAME:
            references_writer = True
        elif isinstance(node, ast.Attribute) and node.attr == _ATOMIC_WRITER_NAME:
            references_writer = True
    return imported, references_writer


def reaches_atomic_writer(entry_module: str, *, max_hops: int = _MAX_IMPORT_HOPS) -> bool:
    """Whether *entry_module* reaches the write chokepoint via `pdf_toolkit.*` imports.

    Pure static analysis (`ast`, never a real import) over the source tree —
    the same style `tests/test_import_boundaries.py` already uses, so this
    stays consistent with the codebase's one AST-walking convention rather
    than inventing a second one.
    """
    seen: set[str] = set()
    frontier = [entry_module]
    for _ in range(max_hops):
        next_frontier: list[str] = []
        for dotted in frontier:
            if dotted in seen:
                continue
            seen.add(dotted)
            path = _dotted_to_path(dotted)
            if path is None:
                continue
            imported, references_writer = _imports_and_references(path)
            if references_writer:
                return True
            next_frontier.extend(sorted(imported))
        frontier = next_frontier
        if not frontier:
            break
    return False


def _takes_input_paths(cmd: object) -> bool:
    return any(
        getattr(param, "param_type_name", None) == "argument"
        and getattr(getattr(param, "type", None), "name", None) == "path"
        for param in cmd.params  # type: ignore[attr-defined]
    )


def operand_metavar(cmd: object) -> str | None:
    """The ``metavar`` the live command declares for its path operand.

    ``convert`` declares ``FILE...`` where every other batch verb declares
    ``PDF...``, because — as `tests/registry.py::_convert_invocation` already
    records — *its own operand is never a PDF*. Reading the live declaration is
    what lets a caller build the right KIND of operand for a verb without a
    hand-maintained exception list, and without discovering the difference only
    on a host whose LibreOffice lacks the PDF import filter.
    """
    for param in cmd.params:  # type: ignore[attr-defined]
        if (
            getattr(param, "param_type_name", None) == "argument"
            and getattr(getattr(param, "type", None), "name", None) == "path"
        ):
            return getattr(param, "metavar", None)
    return None


def operand_metavars(root: object | None = None) -> dict[str, str | None]:
    """Every leaf verb's declared operand ``metavar``, keyed by VERB name."""
    group = root if root is not None else typer.main.get_command(app)
    found: dict[str, str | None] = {}

    def _walk(cmd: object, path: tuple[str, ...]) -> None:
        commands = getattr(cmd, "commands", None)
        if commands is not None:
            for name in sorted(commands):
                _walk(commands[name], (*path, name))
            return
        found[" ".join(path)] = operand_metavar(cmd)

    _walk(group, ())
    return found


def _has_variadic_operand(cmd: object) -> bool:
    """``nargs == -1`` on a path-typed argument — i.e. a batch can be built.

    Same duck-typed shape as :func:`_takes_input_paths`, one field further in.
    """
    return any(
        getattr(param, "param_type_name", None) == "argument"
        and getattr(getattr(param, "type", None), "name", None) == "path"
        and getattr(param, "nargs", 1) == -1
        for param in cmd.params  # type: ignore[attr-defined]
    )


def _is_page_addressing(cmd: object) -> bool:
    return any(
        getattr(param, "param_type_name", None) == "option"
        and "--pages" in getattr(param, "opts", ())
        for param in cmd.params  # type: ignore[attr-defined]
    )


def _module_dotted_name(cmd: object) -> str | None:
    callback = getattr(cmd, "callback", None)
    if callback is None:
        return None
    original = getattr(callback, "__wrapped__", callback)
    module = getattr(original, "__module__", None)
    return module


def discover_verbs(root: object | None = None) -> tuple[VerbSpec, ...]:
    """Every command on the live tree, walked recursively. No skip list, ever.

    Descends into any command exposing a ``.commands`` mapping (duck-typed —
    the CLI framework vendors its own click, so there is no importable
    top-level ``click.core.Group`` to `isinstance`-check against, the same
    reasoning `cli/common.py` already applies to parameter sources).
    """
    group = root if root is not None else typer.main.get_command(app)
    found: list[VerbSpec] = []

    def _walk(cmd: object, path: tuple[str, ...]) -> None:
        commands = getattr(cmd, "commands", None)
        if commands is not None:
            for name in sorted(commands):
                _walk(commands[name], (*path, name))
            return
        module = _module_dotted_name(cmd)
        mutating = reaches_atomic_writer(module) if module else False
        consumes = _common.consumed_output_flags(module) if module else ()
        found.append(
            VerbSpec(
                name=" ".join(path),
                path=path,
                is_group=False,
                takes_input_paths=_takes_input_paths(cmd),
                is_page_addressing=_is_page_addressing(cmd),
                is_mutating=mutating,
                consumes=consumes,
                variadic_operands=_has_variadic_operand(cmd),
            )
        )

    _walk(group, ())
    return tuple(found)


def out_dir_batch_verbs(root: object | None = None) -> tuple[str, ...]:
    """Every verb whose ``--out-dir`` run can carry a bad input IN THE MIDDLE.

    Derived, in the three mechanical steps a transcribed list cannot reproduce:

    1. the ``--out-dir`` consumer set, off each command's own ``consumes``
       declaration (never a grep — two module docstrings mention ``--out-dir``
       beside a literal ``consumes=()`` and would join a text census);
    2. operand arity, off the live command's ``nargs``, which is what excludes
       the single-operand consumer;
    3. **the VERB name, off the live command tree** — never the module
       basename. ``cli/cmd_office.py`` registers ``convert``, so a population
       keyed on the module is a different population from the one a user
       types and the payload's own ``verb`` field carries.

    Step 3 is the one a re-derivation is most likely to skip, and skipping it
    reports ``convert`` missing while inventing ``office``.
    """
    return tuple(
        sorted(
            verb.name
            for verb in discover_verbs(root)
            if not verb.is_group and "--out-dir" in verb.consumes and verb.variadic_operands
        )
    )


def discover_groups(root: object | None = None) -> tuple[tuple[str, ...], ...]:
    """Every **non-root** grouping parent's path, e.g. ``("meta",)``.

    Separate from :func:`discover_verbs` on purpose: C4 ("every grouping
    parent" exits 2 on a bogus subcommand) is a plain structural check, not
    one of the ``(reg)`` checks, so it has no business participating in the
    :data:`INVOCATIONS` anti-lapse contract (AC10) that leaf verbs do.

    No grouping parent existed below root at PDF-06 landing time, which is why
    C4 collected zero cases there. ``meta`` arrived with ``PDF-14``, so this
    returns ``(("meta",),)`` -- ONE path-tuple, not the bare ``("meta",)`` an
    earlier version of this docstring claimed -- and picks a future group up
    automatically the moment it exists. A single-element population still
    passes an emptiness pin while being one refactor from vacuity, which is
    stated in `test_cli_contract.py`'s own ``POPULATIONS`` roster rather than
    left to be rediscovered.
    """
    top = root if root is not None else typer.main.get_command(app)
    found: list[tuple[str, ...]] = []

    def _walk(cmd: object, path: tuple[str, ...]) -> None:
        commands = getattr(cmd, "commands", None)
        if commands is None:
            return
        if path:  # never the synthetic root itself -- root's own bogus-subcommand
            found.append(path)  # check is one of the three non-parameterized root tests.
        for name in sorted(commands):
            _walk(commands[name], (*path, name))

    _walk(top, ())
    return tuple(found)


def console_script() -> list[str]:
    """The argv prefix that runs the installed CLI as a real process."""
    sibling = Path(sys.executable).parent / "pdftoolkit"
    if sibling.exists():
        return [str(sibling)]
    found = shutil.which("pdftoolkit")
    if found:
        return [found]
    return [sys.executable, "-m", "pdf_toolkit"]


def run_cli(
    *args: str,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the CLI as a subprocess — the only place exit codes and real TTY-less
    stdin/stdout posture are observable at all.

    **PDF-14 — the FIRST argument is tokenized on whitespace before it
    reaches ``subprocess.run``.** ``meta`` is the CLI's first grouping
    parent, and every caller in this test suite passes the verb as ONE
    argument — ``run_cli(verb.name, *args, ...)`` (``test_cli_contract.py``'s
    own convention, unedited by this spec) — where ``VerbSpec.name`` is the
    space-joined display string ``discover_verbs()`` already builds (e.g.
    ``"meta set"``). A real shell tokenizes on whitespace before ``exec``
    ever sees an argv, which is exactly what this reproduces for the ONE
    argument that is ever a verb/group name. Every OTHER argument is passed
    through UNSPLIT: a ``--title`` value, a path, or any other flag argument
    may legitimately contain a space, and no argument but the verb name has
    ever needed splitting before this spec (`tests/registry.py`'s own
    module docstring already names the mechanism this completes: "a
    grouping parent... returns `()` today and picks the future group up
    automatically the moment it exists").
    """
    head = tuple(args[0].split()) if args and " " in args[0] else args[:1]
    resolved = (*head, *args[1:])
    return subprocess.run(
        [*console_script(), *resolved],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd is not None else REPO_ROOT,
        env=env,
    )


def rerun_hint(args: list[str]) -> str:
    """A human-pasteable repro line, used by test failure messages only."""
    return shlex.join([PROG_NAME, *args])


def _info_invocation(corpus: object, tmp_path: Path) -> list[str]:
    return [str(corpus.path("single_page"))]  # type: ignore[attr-defined]


def _merge_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`merge` requires `-O`; a fresh target makes C10/C12 valid on their own.

    C11 appends its OWN ``-O <already-existing target>`` after this build's
    result — Click takes the LAST occurrence of a scalar option, so that
    still exercises no-clobber against the test's target, not this one.
    """
    return [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "-O",
        str(tmp_path / "registered-invocation-merge.pdf"),
    ]


def _split_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`split` consumes `--out-dir`/`--name`, never `--output` -- E13/AC29:
    C11 is re-parameterized off the OR-3 declaration precisely so it never
    drives `-O` at this verb (that would be exit 2, not 5)."""
    return [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--each-page",
        "--out-dir",
        str(tmp_path / "split-invocation-parts"),
    ]


def _rasterize_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`rasterize` (PDF-09) consumes `--out-dir`/`--name`, never `--output`
    (Design §D10) -- no mode flag is required, unlike `split`: the default
    selection is every page, so a bare `--out-dir` is already a valid,
    honoured invocation."""
    return [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--out-dir",
        str(tmp_path / "rasterize-invocation-out"),
    ]


def _fixture_jpeg(tmp_path: Path, name: str) -> Path:
    """A tiny baseline JPEG, generated rather than committed.

    `compose` is the product's first verb whose operand is not a PDF, so the
    generated PDF corpus cannot supply one. Pillow builds it here for the same
    reason `tests/corpus.py` builds the PDFs: PDF-06's generate-don't-commit
    posture, and no binary fixture in the tree.
    """
    from PIL import Image

    path = tmp_path / name
    Image.new("RGB", (64, 48), (200, 30, 30)).save(path, format="JPEG", quality=85)
    return path


def _fixture_text(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_text("registered invocation for the create verb\n")
    return path


def _compose_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`compose` (PDF-10) consumes `--output` and produces exactly one PDF, so
    its row mirrors `merge`'s shape: a fresh `-O` target keeps C10/C12 valid on
    their own, and C11's own trailing `-O` still wins (Click takes the LAST
    occurrence of a scalar option)."""
    return [
        str(_fixture_jpeg(tmp_path, "registered-invocation-compose.jpg")),
        "-O",
        str(tmp_path / "registered-invocation-compose.pdf"),
    ]


def _create_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`create` (PDF-10) takes ONE operand, and this row deliberately uses a
    real `.txt` file rather than the `-` stdin sentinel: a harness case that
    passed `-` would block reading standard input that no test writes."""
    return [
        str(_fixture_text(tmp_path, "registered-invocation-create.txt")),
        "-O",
        str(tmp_path / "registered-invocation-create.pdf"),
    ]


def _text_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`text` (PDF-11) consumes `--output`, `--out-dir` and `--name`, and this
    row deliberately names `-O` rather than `--out-dir`.

    Two live checks constrain it from opposite directions and `-O` is the only
    shape that satisfies both. C15's `_discover_target` `pytest.fail`s unless
    the registered invocation's own `--dry-run` plan carries a discoverable
    `items[0].output`, so a stdout-only row is refused by name -- the row must
    name SOME destination. C11 then appends its own `-O <existing target>` to
    whatever this returns; had the row named `--out-dir`, that appended `-O`
    would hit the `--output`/`--out-dir` mutual-exclusion check and C11 would
    measure exit 2 instead of the no-clobber 5 it exists to prove. With `-O`
    here, Click takes the LAST occurrence of a scalar option and C11's target
    wins -- exactly the mechanism `_merge_invocation` above already documents.
    """
    return [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "-O",
        str(tmp_path / "registered-invocation-text.txt"),
    ]


def _tables_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`tables` (PDF-11) -- same `-O` reasoning as `_text_invocation`, plus one
    constraint of its own: the operand must be a selection yielding EXACTLY ONE
    table. `tables` declares `--output`, so two or more planned tables onto one
    path is an output collision (exit 5), and a row built on a multi-table
    selection would fail C10/C12 for the right reason at the wrong time. The
    `tabular` fixture draws one ruled grid on one page."""
    return [
        str(corpus.path("tabular")),  # type: ignore[attr-defined]
        "-O",
        str(tmp_path / "registered-invocation-tables.csv"),
    ]


def _copy_corpus_fixture(corpus: object, tmp_path: Path, name: str, filename: str) -> Path:
    """A `tmp_path`-local COPY of a corpus fixture -- never the fixture path
    itself (PDF-12 HAZARD: an `--in-place` row that named `corpus.path(...)`
    directly would mutate the shared session-scoped corpus, silently
    corrupting every downstream test that reuses it)."""
    import shutil

    destination = tmp_path / filename
    shutil.copy(corpus.path(name), destination)  # type: ignore[attr-defined]
    return destination


def _compress_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`compress` (PDF-12) consumes `--output`, `--out-dir`, `--name` and
    `--in-place`, and this row names `-O` -- same reasoning as
    `_text_invocation`: C11 appends its own `-O <existing target>`, and only
    `-O` in this row keeps Click's last-scalar-wins behaviour landing on
    C11's target rather than tripping the `--output`/`--out-dir` mutual
    exclusion."""
    return [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "-O",
        str(tmp_path / "registered-invocation-compress.pdf"),
    ]


def _compress_destructive_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """B-079's C13 population seed (`Invocation.destructive_build`) --
    TWO ``tmp_path``-local COPIES of a corpus fixture (never the fixture
    path itself, per `_copy_corpus_fixture`'s own docstring: `--in-place`
    would otherwise mutate the shared, session-scoped corpus) plus
    ``--in-place``. That is BULK (`input_count=2`) and DESTRUCTIVE
    (`in_place=True`) simultaneously -- exactly the shape
    `safety/confirm.py::require_confirmation` exists to refuse without
    ``-y`` on a non-TTY, and to permit with it. `compress` needs no other
    required flag, so this is the whole invocation; C13 reuses the same two
    paths for both its refused and its confirmed call, which is safe
    because a refused run mutates neither."""
    first = _copy_corpus_fixture(corpus, tmp_path, "single_page", "c13-compress-a.pdf")
    second = _copy_corpus_fixture(corpus, tmp_path, "single_page", "c13-compress-b.pdf")
    return [str(first), str(second), "--in-place"]


def _repair_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`repair` (PDF-12) -- one input, `-O` (same C11 reasoning). `single_page`
    is a fine operand: a healthy document exits 0 through `repair` exactly as
    it does through every other verb (D-12.4 -- "nothing was wrong" is a
    success, not a refusal)."""
    return [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "-O",
        str(tmp_path / "registered-invocation-repair.pdf"),
    ]


def _linearize_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`linearize` (PDF-12) -- one input, `-O` (same C11 reasoning)."""
    return [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "-O",
        str(tmp_path / "registered-invocation-linearize.pdf"),
    ]


def _password_file(tmp_path: Path, filename: str, password: str) -> Path:
    """A 0600 password file inside `tmp_path` -- never a literal on the command
    line (`PLAN.md` §5.7, ruling OR-4: argv is world-readable in /proc).

    PDF-13 HAZARD, and it reads like a defect until you check it: **every**
    `encrypt` row must supply `--owner-password-file`, or the invocation exits
    2 or 6 for a reason that has nothing to do with the flag under test and the
    cell proves nothing. The file is created by the row itself so no row
    depends on another having run first."""
    destination = tmp_path / filename
    destination.write_text(password)
    destination.chmod(0o600)
    return destination


def _encrypt_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`encrypt` (PDF-13) -- one input, `-O` (same C11 reasoning as
    `_text_invocation`: C11 appends its own `-O <existing target>`, and only
    `-O` here keeps Click's last-scalar-wins landing on C11's target instead
    of tripping the `--output`/`--out-dir` mutual exclusion)."""
    return [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--owner-password-file",
        str(_password_file(tmp_path, "registered-invocation-encrypt.pw", "registry-owner-pw")),
        "-O",
        str(tmp_path / "registered-invocation-encrypt.pdf"),
    ]


def _decrypt_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`decrypt` (PDF-13) -- the operand MUST be an encrypted document, because
    `decrypt` on an unencrypted one is exit 4 by design ("valid invocation,
    nothing to act on") and C12/C15 both require this row to reach exit 0. The
    `encrypted_aes256` fixture carries a user password the corpus publishes as
    `corpus.ENCRYPTED_PASSWORD`."""
    from corpus import ENCRYPTED_PASSWORD

    return [
        str(corpus.path("encrypted_aes256")),  # type: ignore[attr-defined]
        "--password-file",
        str(_password_file(tmp_path, "registered-invocation-decrypt.pw", ENCRYPTED_PASSWORD)),
        "-O",
        str(tmp_path / "registered-invocation-decrypt.pdf"),
    ]


def _permissions_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`permissions` (PDF-13) is NON-PRODUCING: it reports and writes nothing,
    so its row names no destination at all -- the same shape `info`'s row has.
    It declares `consumes=()` under OR-3, so it never enters C11's or C15's
    populations and never needs a discoverable target."""
    del tmp_path
    return [str(corpus.path("single_page"))]  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# PDF-08 -- the four page-addressed structure verbs.
#
# Every row names `-O` rather than `--out-dir`, for the reason
# `_text_invocation` documents at length: C11 appends its own
# `-O <existing target>`, and only `-O` here keeps Click's last-scalar-wins
# behaviour landing on C11's target instead of tripping the
# `--output`/`--out-dir` mutual exclusion (which would measure exit 2 where
# C11 exists to prove the no-clobber 5).
#
# Every row operates on `ten_page_text`, never `single_page`, and that is not
# cosmetic: `delete --pages 1` on a ONE-page document selects every page, which
# is the spec's §D5 zero-page refusal (exit 5) -- the row would then fail C10,
# C12 and C15 for the right reason at the wrong time. `rotate` additionally
# needs `--angle`, which is exactly the gap this table's own module docstring
# names as the thing a generic walk cannot know.
# --------------------------------------------------------------------------- #


def _extract_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`extract` (PDF-08) -- ORDERED selection, one input, `-O`.

    PDF-37: ``--pages`` was ``"1,3"`` -- valid against the normal ten-page
    fixture, but a pre-existing, previously-LATENT defect against
    `tests/test_password_leaks.py`'s `_EncryptedOperandProxy`, which
    substitutes the two-page `encrypted_aes256` fixture wherever a verb's
    own registered invocation would have used a plaintext one. The defect
    was masked before this spec landed: `extract` raised `AuthError`
    (password required) before page-range validation ever ran, on EITHER
    arm of the witness's own no-password/correct-password probe, so
    "page 3 does not exist on a 2-page document" was never reached. Once
    the seam this spec adds lets the CORRECT-password arm actually open the
    document, it reaches page-range validation and reds on the pre-existing
    mismatch (`PageRangeError`, exit 2) -- a witness-methodology defect this
    fix surfaced, not one it introduced. ``"1,2"`` is valid on BOTH the
    normal ten-page fixture (unchanged for every other consumer of this
    invocation) and the two-page encrypted one.
    """
    return [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "1,2",
        "-O",
        str(tmp_path / "registered-invocation-extract.pdf"),
    ]


def _delete_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`delete` (PDF-08) -- SET selection over a TEN-page operand, so the
    survivors are non-empty and §D5's zero-page refusal is not reached."""
    return [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "1",
        "-O",
        str(tmp_path / "registered-invocation-delete.pdf"),
    ]


def _rotate_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`rotate` (PDF-08) -- the verb `tests/registry.py`'s own module docstring
    names as the reason this table exists: a generic walk cannot know it needs
    `--angle`, and without one the invocation is exit 2."""
    return [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "1",
        "--angle",
        "90",
        "-O",
        str(tmp_path / "registered-invocation-rotate.pdf"),
    ]


def _reorder_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`reorder` (PDF-08) -- ORDERED, and total: the unnamed pages are appended,
    so this yields ten pages from a ten-page operand."""
    return [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "last,1",
        "-O",
        str(tmp_path / "registered-invocation-reorder.pdf"),
    ]


# --------------------------------------------------------------------------- #
# PDF-14 -- `meta get`/`meta set`/`watermark`/`stamp`. Every producing row
# names `-O` rather than `--out-dir`, for the reason `_text_invocation`
# documents at length: C11 appends its own `-O <existing target>`, and only
# `-O` here keeps Click's last-scalar-wins behaviour landing on C11's target
# instead of tripping the `--output`/`--out-dir` mutual exclusion.
# --------------------------------------------------------------------------- #


def _meta_get_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`meta get` (PDF-14) is NON-PRODUCING: it reports and writes nothing,
    so its row names no destination -- same shape `permissions`'s own row
    has. It declares `consumes=()` under OR-3."""
    del tmp_path
    return [str(corpus.path("single_page"))]  # type: ignore[attr-defined]


def _meta_set_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`meta set` (PDF-14) -- one input, `-O`, one field flag (D2.2: no
    field/clear flag is exit 2, so a bare invocation would fail C10/C12/C15
    for the wrong reason)."""
    return [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--title",
        "registered-invocation-title",
        "-O",
        str(tmp_path / "registered-invocation-meta-set.pdf"),
    ]


def _watermark_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`watermark` (PDF-14) -- one input, `-O`, `--text` (required)."""
    return [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--text",
        "REGISTERED-INVOCATION",
        "-O",
        str(tmp_path / "registered-invocation-watermark.pdf"),
    ]


def _stamp_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`stamp` (PDF-14) -- one input, `-O`, `--from` (required). The
    generated corpus itself is a fine `--from` operand: `single_page`'s own
    page 1 becomes the stamp layer."""
    return [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--from",
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "-O",
        str(tmp_path / "registered-invocation-stamp.pdf"),
    ]


# --------------------------------------------------------------------------- #
# PDF-15 -- `ocr` + `convert`, the two system-binary verbs. Both rows below
# are deliberately ENGINE-INDEPENDENT (work identically whether tesseract/
# soffice are present or absent), which is what lets them join the generic
# C1-C16 population unconditionally, exactly like every other row here.
#
# `ocr` -- `--skip-text-pages` over `single_page` (a TEXT page, has_text=True)
# makes every selected page skip-eligible, so `ops/ocr.py`'s own lazy engine
# demand (its module docstring: "the engine is demanded lazily") is NEVER
# reached -- the run succeeds via the ordinary append-through path with zero
# spawns, regardless of whether tesseract is installed. Verified: with
# PDF_TOOLKIT_TEST_HIDE_ENGINES=tesseract,soffice, `ocr`'s own C9-C16 rows
# are unaffected by the hide.
#
# `convert` has no equivalent trick -- its whole job IS the conversion, so its
# registered row genuinely NEEDS soffice for the "declared flag honoured"
# (C14) and "json on a pipe" (C12) arms. FIX-FORWARD (`[PDF-15] fix:`,
# post-`5bf6e65`): the eight `test (3.x, ubuntu|macos)` legs and
# `without-engines` have no soffice, and C12/C14 asserted exit 0 unconditionally
# -- exit 3 (`ENGINE_MISSING`) is the CORRECT behaviour there, not a defect,
# but the generic contract rows had no way to say so. `INVOCATIONS["convert"]`
# now declares `requires_engine="OfficeConverter"` (`Invocation`'s own
# docstring), and `tests/test_cli_contract.py` reads it to SKIP those two
# checks VISIBLY, by name, whenever `pdf_toolkit.ports.resolve("OfficeConverter")`
# is unavailable -- never a silent pass. The CI `engines-present` job is where
# those two arms are still meaningfully PROVEN for `convert`
# (`scripts/assert_skips.py --expect-zero` on that job asserts no engine-gated
# skip silently substituted for real coverage -- i.e. the declaration must
# still let the rows RUN there, not vanish); the `without-engines` job's own
# `--pages`-style OR-3 refusal arms (C14's UNDECLARED side, C3, C5, C7, C9,
# C11, C15's refusal rows, C16) all stay engine-independent (verified below)
# since every one of those refuses BEFORE `require_office()` is ever reached.
# --------------------------------------------------------------------------- #


def _ocr_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`ocr` (PDF-15) consumes `--output`/`--out-dir`/`--name`/`--in-place`
    (the `compress` set, D11.1/D11.2) -- this row names `-O` (same C11
    reasoning as `_text_invocation`) AND `--skip-text-pages` over the
    text-only `single_page` fixture, so the run needs no OCR engine at all
    (see this section's own module-level note)."""
    return [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--skip-text-pages",
        "-O",
        str(tmp_path / "registered-invocation-ocr.pdf"),
    ]


def _ocr_destructive_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """B-079's C13 arm for `ocr` (spec Amendment 1: `ocr --in-place` over two
    inputs JOINS the C13 population `compress` already seeded, and the arm
    is shown to fire for `ocr` specifically). TWO `tmp_path`-local COPIES of
    `single_page` (never the shared corpus fixture directly -- see
    `_copy_corpus_fixture`'s own docstring) plus `--skip-text-pages` (engine
    -independent, same reasoning as `_ocr_invocation`) and `--in-place`.
    Bulk (`input_count=2`) and destructive (`in_place=True`) simultaneously,
    exactly what `safety/confirm.py::require_confirmation` refuses without
    `-y` on a non-TTY and permits with it -- and even though every page is
    skip-eligible, the confirmed write still goes through `new_writer()` +
    `append_pages()` + `write()`, which is NOT byte-identical to the
    original (measured: a pypdf round-trip changes serialized bytes even for
    a pure pass-through, e.g. numeric formatting), so the mutation the C13
    contract requires is real, not vacuous."""
    first = _copy_corpus_fixture(corpus, tmp_path, "single_page", "c13-ocr-a.pdf")
    second = _copy_corpus_fixture(corpus, tmp_path, "single_page", "c13-ocr-b.pdf")
    return [str(first), str(second), "--skip-text-pages", "--in-place"]


def _convert_invocation(corpus: object, tmp_path: Path) -> list[str]:
    """`convert` (PDF-15) consumes `--output`/`--out-dir`/`--name` (the
    `text` set, D11.2 -- `--in-place` is deliberately excluded). Its own
    operand is never a PDF, so this row reuses `_fixture_text` (a plain
    `.txt` file -- LibreOffice converts arbitrary text input, verified
    against this host's LibreOffice 26.2.5.2) rather than the generated PDF
    corpus. Requires `OfficeConverter` (`INVOCATIONS["convert"].requires_engine`,
    see this section's own fix-forward note) -- unlike every other row here,
    this one cannot reach exit 0 on a soffice-less host."""
    return [
        str(_fixture_text(tmp_path, "registered-invocation-convert.txt")),
        "-O",
        str(tmp_path / "registered-invocation-convert.pdf"),
    ]


#: Every verb `discover_verbs()` can find on the live tree. `version` and
#: `doctor` take no positional arguments; `info`/`merge` need one existing
#: PDF; `split` needs one PDF plus a mode flag; `rasterize` needs one PDF (no
#: mode flag -- the default page selection is every page). `merge`/`split`/
#: `rasterize` are all `destructive=False` (PDF-07's spec, Scope > Out: a
#: second destructive invocation shape for C13 is a separate backlog
#: candidate, not built here) -- C13 keeps collecting zero cases, a stated
#: fact rather than a silent one.
#: `test_every_verb_is_registered` (AC10) is what forces new-verb registration
#: to happen rather than lapse.
INVOCATIONS: Final[dict[str, Invocation]] = {
    "version": Invocation(build=lambda corpus, tmp_path: []),
    "doctor": Invocation(build=lambda corpus, tmp_path: []),
    "info": Invocation(build=_info_invocation),
    "merge": Invocation(build=_merge_invocation, destructive=False),
    "split": Invocation(build=_split_invocation, destructive=False),
    "rasterize": Invocation(build=_rasterize_invocation, destructive=False),
    "compose": Invocation(build=_compose_invocation, destructive=False),
    "create": Invocation(build=_create_invocation, destructive=False),
    # PDF-11. Both are read verbs toward their INPUT and producing verbs toward
    # their destination, so both are `is_mutating` (they reach the write
    # chokepoint) and both land in C15's PRODUCING population.
    "text": Invocation(build=_text_invocation, destructive=False),
    "tables": Invocation(build=_tables_invocation, destructive=False),
    # PDF-12. `compress`/`repair`/`linearize` are all producing, single- or
    # multi-target verbs over `StructureEngine`. B-079/B-076: `compress` is
    # the one PDF-12 verb whose confirmation gate is now wired AND whose
    # arity makes a bulk `--in-place` run reachable, so it is
    # `destructive=True` with its own `destructive_build` seeding C13's
    # previously-empty population (PDF-15's spec claimed it would be first
    # to do this; amended -- see B-079's ledger row). `repair`/`linearize`
    # take a single `{PDF}` argument each, so their gate is latent, not
    # exposed (bulk is structurally unreachable), and they stay
    # `destructive=False` like every other single-input verb.
    "compress": Invocation(
        build=_compress_invocation,
        destructive=True,
        destructive_build=_compress_destructive_invocation,
    ),
    "repair": Invocation(build=_repair_invocation, destructive=False),
    "linearize": Invocation(build=_linearize_invocation, destructive=False),
    # PDF-13. `encrypt`/`decrypt` are single-target producing verbs;
    # `permissions` is NON-PRODUCING and its row names no destination, which
    # is why it is absent from C11/C15 rather than skipped by them.
    "encrypt": Invocation(build=_encrypt_invocation, destructive=False),
    "decrypt": Invocation(build=_decrypt_invocation, destructive=False),
    "permissions": Invocation(build=_permissions_invocation, destructive=False),
    # PDF-08. All four are producing, multi-input-capable verbs over
    # `StructureEngine`. `destructive=False` like every other producing verb:
    # the registered invocation is a single input writing to `-O`, which is
    # neither bulk nor destructive, so C13 would have nothing to refuse. The
    # bulk `--in-place` non-TTY posture these three DO honour is asserted
    # directly by
    # `tests/integration/test_pages_cli.py::test_ac21_a_bulk_in_place_run_fails_closed_on_a_non_tty`
    # instead of by giving C13 a row it would pass vacuously.
    #
    # PDF-17/AC9 -- THAT SENTENCE IS NOW TIED TO THE TEST IT NAMES. It used to
    # credit a whole module and nothing checked the credit, so the routing
    # decision could outlive the test that justified it.
    # `test_the_pdf_08_destructive_routing_claim_names_a_test_that_exists`
    # parses the node id out of this very comment and fails when it stops
    # resolving.
    "extract": Invocation(build=_extract_invocation, destructive=False),
    "delete": Invocation(build=_delete_invocation, destructive=False),
    "rotate": Invocation(build=_rotate_invocation, destructive=False),
    "reorder": Invocation(build=_reorder_invocation, destructive=False),
    # PDF-14. `meta get` is NON-PRODUCING, same shape as `permissions`.
    # `meta set`/`watermark`/`stamp` are single-target producing verbs over
    # `StructureEngine` (+ `ComposeEngine` for `watermark`'s text layer);
    # none is destructive, matching every other producing verb's own note
    # above -- a single input writing to `-O` is neither bulk nor
    # destructive, so C13 has nothing to refuse.
    "meta get": Invocation(build=_meta_get_invocation, destructive=False),
    "meta set": Invocation(build=_meta_set_invocation, destructive=False),
    "watermark": Invocation(build=_watermark_invocation, destructive=False),
    "stamp": Invocation(build=_stamp_invocation, destructive=False),
    # PDF-15. `ocr` is multi-input, page-addressing, and `--in-place`-capable
    # (the `compress` shape, D11.1) -- `destructive=True`, joining C13's
    # population `compress` already seeded (Amendment 1: the arm is shown to
    # fire for `ocr` specifically, via its own `destructive_build`). `convert`
    # is multi-input but never `--in-place` (D11.2) -- `destructive=False`,
    # matching every other producing verb's own note above (a single input
    # writing to `-O` is neither bulk nor destructive). `convert` is also the
    # first (and, at PDF-15 fix-forward, only) row to set `requires_engine`:
    # unlike `ocr`, it has no engine-free path (this section's own PDF-15
    # module note).
    "ocr": Invocation(
        build=_ocr_invocation,
        destructive=True,
        destructive_build=_ocr_destructive_invocation,
    ),
    "convert": Invocation(
        build=_convert_invocation,
        destructive=False,
        requires_engine="OfficeConverter",
    ),
}

#: AC25 — the OR-3 matrix arm's own per-(verb, flag) invocation table, for
#: every **declared** pair only. A declared pair with no row here fails
#: `test_c14_output_flag_matrix` by name (AC25's own anti-lapse guard,
#: mirroring `test_every_verb_is_registered`'s shape) -- a future verb that
#: declares a flag is forced to show it honoured.
OUTPUT_FLAG_INVOCATIONS: Final[dict[tuple[str, str], Callable[[object, Path], list[str]]]] = {
    ("merge", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "-O",
        str(tmp_path / "or3-merge-output.pdf"),
    ],
    ("split", "--out-dir"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--each-page",
        "--out-dir",
        str(tmp_path / "or3-split-out-dir"),
    ],
    ("split", "--name"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--each-page",
        "--out-dir",
        str(tmp_path / "or3-split-name"),
        "--name",
        "or3-custom-{page}.{ext}",
    ],
    ("rasterize", "--out-dir"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--out-dir",
        str(tmp_path / "or3-rasterize-out-dir"),
    ],
    ("rasterize", "--name"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--out-dir",
        str(tmp_path / "or3-rasterize-name"),
        "--name",
        "or3-custom-{page}.{ext}",
    ],
    ("compose", "--output"): lambda corpus, tmp_path: [
        str(_fixture_jpeg(tmp_path, "or3-compose.jpg")),
        "-O",
        str(tmp_path / "or3-compose-output.pdf"),
    ],
    ("create", "--output"): lambda corpus, tmp_path: [
        str(_fixture_text(tmp_path, "or3-create.txt")),
        "-O",
        str(tmp_path / "or3-create-output.pdf"),
    ],
    # PDF-11 -- six rows, one per (verb, flag) pair `text`/`tables` declare.
    # C14's honoured side asserts a file APPEARS, so every row below must be a
    # complete, succeeding invocation; the `("tables", "--output")` row in
    # particular uses the single-table `tabular` fixture, because a multi-table
    # selection onto one `-O` path is an output collision (exit 5) and the row
    # would then fail for the right reason at the wrong time.
    ("text", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "-O",
        str(tmp_path / "or3-text-output.txt"),
    ],
    ("text", "--out-dir"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--out-dir",
        str(tmp_path / "or3-text-out-dir"),
    ],
    ("text", "--name"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--out-dir",
        str(tmp_path / "or3-text-name"),
        "--name",
        "or3-custom-{stem}.{ext}",
    ],
    ("tables", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("tabular")),  # type: ignore[attr-defined]
        "-O",
        str(tmp_path / "or3-tables-output.csv"),
    ],
    ("tables", "--out-dir"): lambda corpus, tmp_path: [
        str(corpus.path("tabular")),  # type: ignore[attr-defined]
        "--out-dir",
        str(tmp_path / "or3-tables-out-dir"),
    ],
    ("tables", "--name"): lambda corpus, tmp_path: [
        str(corpus.path("tabular")),  # type: ignore[attr-defined]
        "--out-dir",
        str(tmp_path / "or3-tables-name"),
        "--name",
        "or3-custom-p{page:03}-t{index}.{ext}",
    ],
    # PDF-12 -- eight rows: compress x {--output, --out-dir, --name,
    # --in-place}, repair/linearize x {--output, --in-place}. Every
    # `--in-place` row copies its fixture into `tmp_path` FIRST via
    # `_copy_corpus_fixture` and operates on the COPY -- these are the
    # product's first `--in-place` C14 cells, and a row naming
    # `corpus.path(...)` directly would mutate the shared, session-scoped
    # corpus (see that helper's own docstring).
    ("compress", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "-O",
        str(tmp_path / "or3-compress-output.pdf"),
    ],
    ("compress", "--out-dir"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--out-dir",
        str(tmp_path / "or3-compress-out-dir"),
    ],
    ("compress", "--name"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--out-dir",
        str(tmp_path / "or3-compress-name"),
        "--name",
        "or3-custom-{stem}.{ext}",
    ],
    ("compress", "--in-place"): lambda corpus, tmp_path: [
        str(_copy_corpus_fixture(corpus, tmp_path, "single_page", "or3-compress-in-place.pdf")),
        "--in-place",
    ],
    ("repair", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "-O",
        str(tmp_path / "or3-repair-output.pdf"),
    ],
    ("repair", "--in-place"): lambda corpus, tmp_path: [
        str(_copy_corpus_fixture(corpus, tmp_path, "single_page", "or3-repair-in-place.pdf")),
        "--in-place",
    ],
    ("linearize", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "-O",
        str(tmp_path / "or3-linearize-output.pdf"),
    ],
    ("linearize", "--in-place"): lambda corpus, tmp_path: [
        str(_copy_corpus_fixture(corpus, tmp_path, "single_page", "or3-linearize-in-place.pdf")),
        "--in-place",
    ],
    # PDF-13 -- four rows: encrypt/decrypt x {--output, --in-place}. Three
    # constraints, each of which would otherwise produce a green-but-meaningless
    # cell:
    #   1. Every row names `-O`, never `--out-dir` -- C11 appends its own
    #      `-O <existing target>` (X-121).
    #   2. Every `encrypt` row supplies `--owner-password-file`, or it exits 2
    #      or 6 for an unrelated reason (see `_password_file`).
    #   3. The `("encrypt", "--in-place")` row supplies `--no-backup`, because a
    #      bare `encrypt --in-place` exits 5 BY DESIGN -- the plaintext-`.bak`
    #      gate -- and could never be "honoured" without it. `--no-backup`
    #      rather than `-y` so the row leaves no plaintext copy behind either.
    ("encrypt", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--owner-password-file",
        str(_password_file(tmp_path, "or3-encrypt-output.pw", "or3-owner-pw")),
        "-O",
        str(tmp_path / "or3-encrypt-output.pdf"),
    ],
    ("encrypt", "--in-place"): lambda corpus, tmp_path: [
        str(_copy_corpus_fixture(corpus, tmp_path, "single_page", "or3-encrypt-in-place.pdf")),
        "--owner-password-file",
        str(_password_file(tmp_path, "or3-encrypt-in-place.pw", "or3-owner-pw")),
        "--in-place",
        "--no-backup",
    ],
    ("decrypt", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("encrypted_aes256")),  # type: ignore[attr-defined]
        "--password-file",
        str(_password_file(tmp_path, "or3-decrypt-output.pw", _encrypted_password())),
        "-O",
        str(tmp_path / "or3-decrypt-output.pdf"),
    ],
    ("decrypt", "--in-place"): lambda corpus, tmp_path: [
        str(_copy_corpus_fixture(corpus, tmp_path, "encrypted_aes256", "or3-decrypt-in-place.pdf")),
        "--password-file",
        str(_password_file(tmp_path, "or3-decrypt-in-place.pw", _encrypted_password())),
        "--in-place",
    ],
    # PDF-08 -- FIFTEEN rows, not sixteen: extract x {--output, --out-dir,
    # --name} plus delete/rotate/reorder x {--output, --out-dir, --name,
    # --in-place}. `extract` declares no `--in-place`, so its cell for that
    # flag is on C14's REFUSED side and needs no row here -- which is exactly
    # AC33's proof that the refusal comes from the OR-3 declaration alone.
    #
    # Constraints every row below satisfies, each of which would otherwise
    # produce a green-but-meaningless cell:
    #   1. The operand is `ten_page_text`, never `single_page`: `delete
    #      --pages 1` on a one-page document is §D5's zero-page refusal
    #      (exit 5), and C14's honoured side requires exit 0.
    #   2. Every row carries `--pages` (all four verbs require it) and every
    #      `rotate` row carries `--angle` as well.
    #   3. Every `--in-place` row copies its fixture into `tmp_path` FIRST via
    #      `_copy_corpus_fixture` and operates on the COPY -- naming
    #      `corpus.path(...)` directly would mutate the shared, session-scoped
    #      corpus (see that helper's own docstring).
    #
    # KNOWN, INHERITED AND NOT FIXED HERE (ledger `afe2e6137b` / backlog
    # B-065): C14's honoured side snapshots `tmp_path` at `:300` but the row's
    # own `build` lambda runs at `:310`, so any row materialising its fixture
    # inside `tmp_path` passes with the verb never having written anything.
    # The three `--in-place` rows below are therefore vacuous BY CONSTRUCTION,
    # as PDF-12's and PDF-13's already are -- repairing C14 would change a
    # shared control every verb depends on. The compensation is stated rather
    # than assumed: `tests/integration/test_pages_cli.py`'s AC17 arm is what
    # proves these three verbs actually wrote something, by hashing the input
    # before and after and requiring `.bak` to carry the pre-run hash.
    ("extract", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "1,3",
        "-O",
        str(tmp_path / "or3-extract-output.pdf"),
    ],
    ("extract", "--out-dir"): lambda corpus, tmp_path: [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "1,3",
        "--out-dir",
        str(tmp_path / "or3-extract-out-dir"),
    ],
    ("extract", "--name"): lambda corpus, tmp_path: [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "1,3",
        "--out-dir",
        str(tmp_path / "or3-extract-name"),
        "--name",
        "or3-custom-{stem}.{ext}",
    ],
    ("delete", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "1",
        "-O",
        str(tmp_path / "or3-delete-output.pdf"),
    ],
    ("delete", "--out-dir"): lambda corpus, tmp_path: [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "1",
        "--out-dir",
        str(tmp_path / "or3-delete-out-dir"),
    ],
    ("delete", "--name"): lambda corpus, tmp_path: [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "1",
        "--out-dir",
        str(tmp_path / "or3-delete-name"),
        "--name",
        "or3-custom-{stem}.{ext}",
    ],
    ("delete", "--in-place"): lambda corpus, tmp_path: [
        str(_copy_corpus_fixture(corpus, tmp_path, "ten_page_text", "or3-delete-in-place.pdf")),
        "--pages",
        "1",
        "--in-place",
    ],
    ("rotate", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "1",
        "--angle",
        "90",
        "-O",
        str(tmp_path / "or3-rotate-output.pdf"),
    ],
    ("rotate", "--out-dir"): lambda corpus, tmp_path: [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "1",
        "--angle",
        "90",
        "--out-dir",
        str(tmp_path / "or3-rotate-out-dir"),
    ],
    ("rotate", "--name"): lambda corpus, tmp_path: [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "1",
        "--angle",
        "90",
        "--out-dir",
        str(tmp_path / "or3-rotate-name"),
        "--name",
        "or3-custom-{stem}.{ext}",
    ],
    ("rotate", "--in-place"): lambda corpus, tmp_path: [
        str(_copy_corpus_fixture(corpus, tmp_path, "ten_page_text", "or3-rotate-in-place.pdf")),
        "--pages",
        "1",
        "--angle",
        "90",
        "--in-place",
    ],
    ("reorder", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "last,1",
        "-O",
        str(tmp_path / "or3-reorder-output.pdf"),
    ],
    ("reorder", "--out-dir"): lambda corpus, tmp_path: [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "last,1",
        "--out-dir",
        str(tmp_path / "or3-reorder-out-dir"),
    ],
    ("reorder", "--name"): lambda corpus, tmp_path: [
        str(corpus.path("ten_page_text")),  # type: ignore[attr-defined]
        "--pages",
        "last,1",
        "--out-dir",
        str(tmp_path / "or3-reorder-name"),
        "--name",
        "or3-custom-{stem}.{ext}",
    ],
    ("reorder", "--in-place"): lambda corpus, tmp_path: [
        str(_copy_corpus_fixture(corpus, tmp_path, "ten_page_text", "or3-reorder-in-place.pdf")),
        "--pages",
        "last,1",
        "--in-place",
    ],
    # PDF-14 -- six rows: `meta set`/`watermark`/`stamp` x {--output,
    # --in-place}. Every `--in-place` row copies its fixture into `tmp_path`
    # FIRST via `_copy_corpus_fixture` and operates on the COPY, for the same
    # reason every earlier `--in-place` row does (see that helper's own
    # docstring): naming `corpus.path(...)` directly would mutate the
    # shared, session-scoped corpus.
    ("meta set", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--title",
        "or3-title",
        "-O",
        str(tmp_path / "or3-meta-set-output.pdf"),
    ],
    ("meta set", "--in-place"): lambda corpus, tmp_path: [
        str(_copy_corpus_fixture(corpus, tmp_path, "single_page", "or3-meta-set-in-place.pdf")),
        "--title",
        "or3-title",
        "--in-place",
    ],
    ("watermark", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--text",
        "OR3-WATERMARK",
        "-O",
        str(tmp_path / "or3-watermark-output.pdf"),
    ],
    ("watermark", "--in-place"): lambda corpus, tmp_path: [
        str(_copy_corpus_fixture(corpus, tmp_path, "single_page", "or3-watermark-in-place.pdf")),
        "--text",
        "OR3-WATERMARK",
        "--in-place",
    ],
    ("stamp", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--from",
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "-O",
        str(tmp_path / "or3-stamp-output.pdf"),
    ],
    ("stamp", "--in-place"): lambda corpus, tmp_path: [
        str(_copy_corpus_fixture(corpus, tmp_path, "single_page", "or3-stamp-in-place.pdf")),
        "--from",
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--in-place",
    ],
    # PDF-15 -- seven rows: `ocr` x {--output, --out-dir, --name, --in-place},
    # `convert` x {--output, --out-dir, --name}. Every `ocr` row carries
    # `--skip-text-pages` over the text-only `single_page` fixture, engine
    # -independent for the same reason `_ocr_invocation` is (this file's own
    # PDF-15 section note); every `convert` row uses `_fixture_text` (plain
    # `.txt`, LibreOffice converts it) since `convert`'s operand is never a
    # PDF. Every `--in-place` row copies its fixture into `tmp_path` FIRST,
    # same reason every earlier `--in-place` row does.
    ("ocr", "--output"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--skip-text-pages",
        "-O",
        str(tmp_path / "or3-ocr-output.pdf"),
    ],
    ("ocr", "--out-dir"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--skip-text-pages",
        "--out-dir",
        str(tmp_path / "or3-ocr-out-dir"),
    ],
    ("ocr", "--name"): lambda corpus, tmp_path: [
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "--skip-text-pages",
        "--out-dir",
        str(tmp_path / "or3-ocr-name"),
        "--name",
        "or3-custom-{stem}.{ext}",
    ],
    ("ocr", "--in-place"): lambda corpus, tmp_path: [
        str(_copy_corpus_fixture(corpus, tmp_path, "single_page", "or3-ocr-in-place.pdf")),
        "--skip-text-pages",
        "--in-place",
    ],
    ("convert", "--output"): lambda corpus, tmp_path: [
        str(_fixture_text(tmp_path, "or3-convert-output.txt")),
        "-O",
        str(tmp_path / "or3-convert-output.pdf"),
    ],
    ("convert", "--out-dir"): lambda corpus, tmp_path: [
        str(_fixture_text(tmp_path, "or3-convert-out-dir.txt")),
        "--out-dir",
        str(tmp_path / "or3-convert-out-dir"),
    ],
    ("convert", "--name"): lambda corpus, tmp_path: [
        str(_fixture_text(tmp_path, "or3-convert-name.txt")),
        "--out-dir",
        str(tmp_path / "or3-convert-name"),
        "--name",
        "or3-custom-{stem}.{ext}",
    ],
}


def _encrypted_password() -> str:
    """The `encrypted_aes256` fixture's own password, read from the corpus
    module rather than repeated as a literal (the `MHC-12` rule: a fixture and
    what a test asserts against it must not be able to drift)."""
    from corpus import ENCRYPTED_PASSWORD

    return ENCRYPTED_PASSWORD


# --------------------------------------------------------------------------- #
# PDF-17 -- the derived dimension surface (X-157). See this module's docstring.
# --------------------------------------------------------------------------- #

#: PDF-08's four page-addressed structure verbs — the ONE place they are named.
#:
#: AC30 forbids a typed verb list *"anywhere in PDF-08's tests"*, and eleven of
#: them existed. They are gone; this declaration replaced them, and it is not
#: the same thing they were, for one reason: it carries a LIVE TIE
#: (`tests/test_derived_dimensions.py::test_the_governed_verb_set_is_live`)
#: that fails by name the moment one of these stops being a discovered verb.
#: The eleven tuples had no tie, which is why a rename would have left them
#: stale AND passing.
#:
#: It is a declaration rather than a derivation because no structural predicate
#: over the live registry isolates these four: `is_page_addressing` returns
#: ELEVEN verbs (`compress`, `ocr`, `rasterize`, `stamp`, `tables`, `text`,
#: `watermark` all declare `--pages` too). Measured, not assumed.
PDF_08_VERBS: Final[tuple[str, ...]] = ("extract", "delete", "rotate", "reorder")


def output_formats() -> tuple[OutputFormat, ...]:
    """Every member of the live ``OutputFormat`` StrEnum, in declaration order.

    DERIVED, never listed: a renderer added to
    ``src/pdf_toolkit/output/__init__.py`` joins every consuming matrix with
    zero action from its author. `PDF-22` consumes this rather than building a
    second one (X-157).
    """
    return tuple(OutputFormat)


def tty_modes() -> tuple[bool, ...]:
    """The ``isatty()`` branch as an explicit two-member dimension.

    A first-class axis rather than an implicit one, so a matrix that must cross
    it says so. `tests/test_derived_dimensions.py` ties it to the product:
    ``auto_format()`` must still answer differently on the two modes, or the
    axis has collapsed and this tuple describes nothing.
    """
    return (True, False)


def expectation(mapping: dict[str, object], key: str, *, label: str) -> object:
    """*mapping*[*key*], failing BY NAME when no expectation is declared.

    The blessed shape for per-verb DATA under AC30 (`PDF-17` §5). A dimension
    is DERIVED (`discover_verbs()`, :data:`PDF_08_VERBS`); the per-verb values a
    test compares against are a mapping keyed by that dimension, and this
    lookup is what stops a new verb from being silently skipped: it fails with
    "no expectation declared" instead. `undeclared_expectations` closes the
    other direction.
    """
    if key not in mapping:
        raise AssertionError(
            f"{label}: no expectation declared for {key!r}. A verb joined the derived "
            f"dimension without a value here -- declare one (or state why it is exempt). "
            f"Declared: {sorted(mapping)}"
        )
    return mapping[key]


def undeclared_expectations(
    mapping: dict[str, object], dimension: tuple[str, ...]
) -> tuple[list[str], list[str]]:
    """``(missing, stale)`` — dimension members with no expectation, and
    expectations naming something no longer in the dimension."""
    return sorted(set(dimension) - set(mapping)), sorted(set(mapping) - set(dimension))


# --------------------------------------------------------------------------- #
# PDF-22 -- the code-derived secret-leak regression matrix (X-157, X-243).
#
# Two capabilities `PDF-17` did not need and `PDF-22` does: the derived
# `(flag, verb)` population behind the B-068 guard (D2), and a REAL pty on
# `stdout`/`stderr` (Correction 3 -- both pre-existing pty tests in this suite
# attach the pty to `stdin` only, which cannot reach the sixth shape). Both
# live here rather than in `tests/test_password_leaks.py` because they are
# harness machinery, not matrix content -- the same split `discover_verbs()`
# and `run_cli()` already draw.
# --------------------------------------------------------------------------- #

#: Click hard-wraps `--help` text, including inside a hyphenated flag name
#: (`--password-\n  file`). De-wrapping before a substring grep is what keeps
#: the D2 probe from silently shrinking the population on a wrapped line --
#: `tests/test_password_leaks.py`'s own AC18 grep already carries this same
#: normalization (its `:883`); reused here, not re-derived, so the population
#: and the proof that built it cannot drift apart.
_HELP_LINE_WRAP: Final[re.Pattern[str]] = re.compile(r"-[ \t]*\n[ \t]*")


def derive_password_file_pairs() -> tuple[tuple[str, str], ...]:
    """D2 -- the `(flag, verb)` population, built rather than typed.

    A pair is IN the population **iff the live rendered `<verb> --help`
    names `flag`** -- `PDF-13` AC18's own idiom (B-052's lesson: grep
    rendered ``--help``, never source) applied to BUILD a population rather
    than to police one. No skip list, no hard-coded verb or flag name: a verb
    that stops accepting a flag, or a new password-file flag, moves this
    return value the next time the suite runs.

    At `2d19bcb` this yields 28 pairs over 26 verbs; that number appears
    nowhere as a literal in this function or in its callers.

    The 26 `--help` subprocess spawns are dispatched across a small thread
    pool (AC8's `<= 30s` budget: this is I/O-bound subprocess wait, not CPU
    work, so the GIL is released for the duration of each spawn and threads
    give a real wall-clock win with zero correctness risk -- each verb's
    probe is independent and touches nothing but its own `--help` output).
    """
    from concurrent.futures import ThreadPoolExecutor

    from pdf_toolkit.cli.common import PASSWORD_FILE_FLAGS

    def _probe(verb_name: str) -> list[tuple[str, str]]:
        rendered = run_cli(verb_name, "--help").stdout
        normalized = _HELP_LINE_WRAP.sub("-", rendered)
        return [(flag, verb_name) for flag in PASSWORD_FILE_FLAGS if flag in normalized]

    verb_names = [verb.name for verb in discover_verbs()]
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(verb_names)))) as pool:
        per_verb = list(pool.map(_probe, verb_names))
    return tuple(pair for pairs in per_verb for pair in pairs)


def output_shape_states() -> tuple[OutputFormat | None, ...]:
    """The shape dimension: every `output_formats()` member PLUS the
    absent-``-o`` state (``None``), which resolves through `auto_format()`'s
    own `isatty()` branch rather than being a fourth enum member.

    Reuses `output_formats()` rather than a second enumeration (X-157): a
    member added to `OutputFormat` joins this tuple, and every derived
    dimension a consumer builds from it, with zero action here.
    """
    return (*output_formats(), None)


@dataclass(frozen=True, slots=True)
class PtyResult:
    """One `run_cli_with_pty` observation. Mirrors
    `subprocess.CompletedProcess[str]`'s three fields a consumer actually
    reads, decoded ``errors="replace"`` since a pty is a byte stream, not
    guaranteed valid UTF-8 at every partial read boundary."""

    returncode: int
    stdout: str
    stderr: str


def _drain_pty(controller_fd: int, sink: bytearray) -> None:
    """Read *controller_fd* until the kernel reports the far end gone.

    A pty's read-side raises ``OSError`` (``EIO``) once the slave has no more
    writers, rather than returning ``b""`` the way a pipe's read side would --
    the one behavioural difference from a plain `subprocess.PIPE` that makes
    this its own function instead of a `communicate()` call.
    """
    while True:
        try:
            chunk = os.read(controller_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        sink.extend(chunk)


def pty_hang_timeout() -> float:
    """The pty helper's HANG bound -- scaled by the xdist worker count.

    PDF-29, and this is the SAME defect the startup budget has, found by
    measurement rather than by reading: **a wall-clock number used as a
    correctness bound is not portable across host load.** Under `-n auto`
    (`pyproject.toml`'s `addopts`) eight workers share the box, so a pty-driven
    `decrypt` that finishes in a couple of seconds alone can legitimately take
    tens of seconds; the flat 30.0 s this defaulted to killed the child with
    SIGKILL mid-prompt and reported
    `test_tier_b_the_stdin_tty_axis_never_echoes_a_wrong_password_at_the_prompt`
    as a leak failure. Reproduced deliberately: eight busy-loop children,
    loadavg 14.12 on 8 cpus -> `TimeoutExpired ... timed out after 30.0
    seconds`, returncode -9, with `Password: ` already on stderr.

    This bound exists to stop a HUNG pty read from holding the suite open
    forever. It is NOT a latency assertion and must never be read as one -- the
    latency claim lives in exactly one place (`STARTUP_BUDGET_MS`), and even
    there it abstains rather than flakes. Scaling by the worker count keeps it a
    hang bound under every configuration: 30 s serial, 240 s at `-n auto` on
    this 8-cpu host -- still an order of magnitude inside `ci.yml`'s
    `timeout-minutes`, so a genuine hang is still caught by something.
    """
    try:
        workers = int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", "1") or "1")
    except ValueError:  # pragma: no cover - defensive
        workers = 1
    return 30.0 * max(1, workers)


def _wait_until_the_child_is_reading(
    controller: int, process: subprocess.Popen[str], bound: float
) -> None:
    """Block until the child has posted its `getpass` read, or *bound* elapses.

    PDF-29, and this is a REAL DEFECT that `-n auto` exposed rather than a
    tuning problem. This function replaces a flat ``time.sleep(0.5)`` whose own
    comment conceded it was "giving it real wall-clock time rather than assuming
    the same timing holds" -- i.e. an unstated wall-clock assumption used as a
    correctness mechanism, which is the same defect the startup budget has and
    the third instance of it this spec met.

    WHY THE SLEEP WAS NOT MERELY SLOW, IT WAS WRONG. `getpass` disables echo
    with ``termios.tcsetattr(fd, TCSAFLUSH, ...)``, and **TCSAFLUSH DISCARDS
    PENDING INPUT**. If the 0.5 s elapses before the child reaches that call --
    which is exactly what happens when eight xdist workers share the box -- the
    password we already wrote is flushed away and the child then waits for input
    that will never arrive. It is a HANG, not a slow test: widening the bound
    from 30 s to 240 s reproduced the identical failure at 240 s, with
    ``Password: `` already on the child's stderr. Reproduced deliberately with
    eight busy-loop children at loadavg 14.12 on 8 cpus.

    THE FIX IS AN OBSERVED EVENT, NOT A LONGER GUESS. The pty's line discipline
    is shared between controller and follower, so ``tcgetattr(controller)``
    shows ECHO cleared the instant the child's ``tcsetattr`` lands. Waiting for
    that bit is waiting for the exact happens-before this write needs, at any
    host load. The bound remains only so a child that never disables echo (no
    caller does today -- `pty_stream="stdin"` with `stdin_data` has exactly one
    call site, the `getpass` arm) degrades to the old behaviour instead of
    hanging here.
    """
    import termios
    import time

    deadline = time.monotonic() + max(1.0, bound * 0.5)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return
        try:
            if not termios.tcgetattr(controller)[3] & termios.ECHO:
                return
        except termios.error:  # pragma: no cover - controller closed under us
            return
        time.sleep(0.01)


def run_cli_with_pty(
    *args: str,
    pty_stream: str,
    stdin_data: bytes | None = None,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    timeout: float | None = None,
) -> PtyResult:
    """Run the CLI with exactly ONE of ``stdout`` / ``stderr`` / ``stdin``
    attached to a REAL pty (`pty_stream`), the other two ordinary pipes.

    THE NEW CAPABILITY (Correction 3, `PDF-22` Design D1) -- every pty test
    that already existed in this suite (`tests/unit/test_confirm.py:251`,
    `tests/integration/test_compose_roundtrip.py:166`) attaches the pty to
    `stdin` only. `auto_format()` branches on `sys.stdout.isatty()` and
    `color_enabled()` on `sys.stderr.isatty()` -- neither stream had ever
    been made a terminal by any test idiom in this repository before this
    function, which is why the sixth shape (a table on stderr, under a
    terminal, with no ``-o`` flag) was unreachable by anything shipped.

    ``start_new_session=True`` (verified against this host, `PDF-22`
    Implementation Log): without it the child inherits the calling process's
    session and `getpass`'s `/dev/tty` open may resolve to a DIFFERENT
    terminal than the pty this function built; with it the child is a fresh
    session leader and falls back to reading its own `stdin` (still our pty)
    the same way `getpass.getpass` always has when `/dev/tty` is unavailable.
    """
    if timeout is None:
        timeout = pty_hang_timeout()
    if pty_stream not in ("stdout", "stderr", "stdin"):
        raise ValueError(f"pty_stream must be one of stdout/stderr/stdin, got {pty_stream!r}")

    import pty  # POSIX-only; local per this repo's own pty-test convention.

    controller, follower = pty.openpty()
    stdin_kw: object = subprocess.DEVNULL
    stdout_kw: object = subprocess.PIPE
    stderr_kw: object = subprocess.PIPE
    if pty_stream == "stdin":
        stdin_kw = follower
    elif pty_stream == "stdout":
        stdout_kw = follower
    else:
        stderr_kw = follower

    process = subprocess.Popen(  # noqa: S603 - argv built by this module, never shell
        [*console_script(), *args],
        stdin=stdin_kw,
        stdout=stdout_kw,
        stderr=stderr_kw,
        cwd=str(cwd) if cwd is not None else REPO_ROOT,
        env=env,
        text=True,
        start_new_session=True,
    )
    os.close(follower)

    captured = bytearray()
    drain_thread: threading.Thread | None = None
    if pty_stream in ("stdout", "stderr"):
        drain_thread = threading.Thread(target=_drain_pty, args=(controller, captured), daemon=True)
        drain_thread.start()
    elif stdin_data is not None:
        _wait_until_the_child_is_reading(controller, process, timeout)
        os.write(controller, stdin_data)

    try:
        piped_stdout, piped_stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        piped_stdout, piped_stderr = process.communicate()
        raise
    finally:
        if drain_thread is not None:
            drain_thread.join(timeout=5.0)
        os.close(controller)

    pty_text = captured.decode("utf-8", errors="replace")
    if pty_stream == "stdout":
        return PtyResult(process.returncode, pty_text, piped_stderr or "")
    if pty_stream == "stderr":
        return PtyResult(process.returncode, piped_stdout or "", pty_text)
    return PtyResult(process.returncode, piped_stdout or "", piped_stderr or "")
