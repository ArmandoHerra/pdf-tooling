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
not exist in this codebase: `pdf_tooling.cli.common.global_options` attaches
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
verb's own callback module and every `pdf_tooling.*` module it imports,
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
  ``pdf_tooling.cli.common`` so a consumer has one import to make. It is the
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
* ``path_spellings()`` — PDF-74's value-shape axis: the SHAPE of the value a
  user types, which no other dimension here describes. Declared (there is no
  spelling enum under ``src/`` to derive from) and therefore carrying both of
  the guards a declaration owes — a live collapse tie and a tree-wide
  no-re-listing scan, both in `tests/test_derived_dimensions.py`.
* ``destination_flag_cases()`` — the ``(verb, flag)`` population that axis is
  crossed against, derived off ``consumes`` alone, and carrying a FITNESS
  statement beside its provenance one. ``out_dir_batch_verbs()`` is NOT it: its
  operand-arity filter is irrelevant to value shape and drops ``split``.
* ``destination_cell_engine()`` — PDF-82's per-CELL engine answer for that same
  population, so the two matrices crossing it gate their cells from one place
  and neither types a verb name or a node id. Per cell and never per verb: the
  measured exception beside it is a cell of an engine-backed verb that refuses
  before the engine resolves, and marking it would cost coverage silently.

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

from pdf_tooling.cli import common as _common
from pdf_tooling.cli.common import OUTPUT_FLAGS
from pdf_tooling.cli.main import PROG_NAME, app
from pdf_tooling.output import OutputFormat

__all__ = [
    "DESTINATION_VALUE_FLAGS",
    "INVOCATIONS",
    "LICENSED_POPULATION_FIELDS",
    "OUTPUT_FLAGS",
    "OUTPUT_FLAG_INVOCATIONS",
    "PATH_SPELLINGS",
    "PDF_08_VERBS",
    "REPO_ROOT",
    "FILTER_MEANINGS",
    "Invocation",
    "PathSpelling",
    "PtyResult",
    "VerbSpec",
    "console_script",
    "derive_password_file_pairs",
    "destination_flag_cases",
    "discover_groups",
    "discover_verbs",
    "engine_blind_verbs",
    "engine_ports",
    "no_input_population",
    "operand_metavar",
    "operand_metavars",
    "out_dir_batch_verbs",
    "expectation",
    "output_formats",
    "output_shape_states",
    "path_spellings",
    "population_fields",
    "reaches_engine_port",
    "run_cli",
    "run_cli_with_pty",
    "spelled_destination",
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

    takes_positional_argument: bool = False
    """PDF-54 D2 -- whether this verb declares a positional ``argument``
    parameter, of ANY type. Broader than ``takes_input_paths`` on purpose:
    that predicate is typed to ``click.Path`` and ``merge``'s own operand is
    ``str``-typed, so it fails it and would silently drop ``merge`` from any
    population built on it (measured, PDF-54 E12 -- the predicate that reads
    like the right one is the biased one). This is the failure-arm
    population's own denominator (`no_input_population()` below); `doctor`
    and `version` decline no positional operand and are correctly excluded
    from both predicates."""

    module: str | None = None
    """PDF-67 -- the dotted name of the module this leaf's callback lives in,
    e.g. ``"pdf_tooling.cli.cmd_office"`` for the verb ``convert``.

    STRUCTURAL, like ``name`` and ``is_group``: it records WHERE the leaf is
    declared, and narrows nothing about the verb's behaviour. ``discover_verbs``
    already resolved it (``is_mutating`` is computed from it), so this exposes a
    value that was being computed and thrown away rather than recomputing it --
    which is what `engine_blind_verbs()` needs in order to walk the import graph
    from a leaf without re-walking the command tree beside `discover_verbs`.

    Defaulted so a ``VerbSpec`` built by hand (a unit test's own throwaway) does
    not have to name it, exactly as ``consumes`` and ``variadic_operands`` are.
    ``None`` for a leaf whose callback cannot be resolved, which is the same
    case ``is_mutating`` already treats as ``False``."""


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
    """A port name from ``pdf_tooling.ports.PORTS`` (e.g. ``"OfficeConverter"``)
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
    ``pdf_tooling.ports.resolve(port).available`` -- never an independent
    ``shutil.which`` and never an env var or hard-coded platform check. When
    unavailable, the consuming test SKIPS with a reason naming the missing
    engine (never passes vacuously); when available, the row runs for real,
    which is what keeps `engines-present`'s own
    ``scripts/assert_skips.py --expect-zero`` green because the rows RAN, not
    because they vanished."""
    no_input_build: Callable[[object, Path], list[str]] | None = None
    """PDF-54 D3's failure-arm population seed, on the identical precedent
    ``destructive_build`` already set: ``build`` cannot be trusted to reach
    ``kind == "no_input"`` on a merely-swapped operand, because several
    verbs need MORE than a nonexistent path before the no-input check ever
    runs -- Click's own required-option enforcement fires first. Measured
    (PDF-54 E13): a bare ``<verb> <missing>`` reaches ``kind: "usage"`` on
    ``merge`` (``-O``/``--output`` is required), ``rasterize`` (accepts
    ``--out-dir``, never ``--output``), ``reorder`` and ``stamp`` (each
    needs its own required flag before the operand is ever inspected). A
    generic "swap the operand" helper would freeze the wrong ``kind`` on
    those leaves while looking green everywhere else -- exactly B-047's
    shape, on this design's own failure arm rather than its bulk one.

    ``None`` is the default. Every leaf the live command tree declares a
    positional ``argument`` for (``no_input_population()`` below, never
    ``VerbSpec.takes_input_paths`` -- see its own docstring) must supply
    one; ``tests/test_envelope_contract.py``'s anti-lapse arm fails the
    suite, naming the leaf, when one does not. Each row points its operand
    at a path that does not exist under the test's OWN ``tmp_path`` and
    never creates it -- HC-2's corpus contract applies here exactly as it
    does to ``destructive_build``: no row ever names a real-document sample
    from the samples fixture, and a row's OTHER required flags may still use
    the generated `corpus` fixture (e.g. `stamp`'s `--from`), because that
    flag is not the operand under test."""


def _dotted_to_path(dotted: str) -> Path | None:
    """``pdf_tooling.cli.cmd_info`` -> its file, or ``None`` if it is not local."""
    parts = dotted.split(".")
    candidate = SRC.joinpath(*parts).with_suffix(".py")
    if candidate.is_file():
        return candidate
    package_init = SRC.joinpath(*parts, "__init__.py")
    if package_init.is_file():
        return package_init
    return None


def _imports_and_references(path: Path) -> tuple[set[str], bool]:
    """One module's own `pdf_tooling.*` imports, and whether it names *AtomicWriter*."""
    tree = ast.parse(path.read_text(), filename=str(path))
    imported: set[str] = set()
    references_writer = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("pdf_tooling")
        ):
            imported.add(node.module)
            if any(alias.name == _ATOMIC_WRITER_NAME for alias in node.names):
                references_writer = True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("pdf_tooling"):
                    imported.add(alias.name)
        elif isinstance(node, ast.Name) and node.id == _ATOMIC_WRITER_NAME:
            references_writer = True
        elif isinstance(node, ast.Attribute) and node.attr == _ATOMIC_WRITER_NAME:
            references_writer = True
    return imported, references_writer


def reaches_atomic_writer(entry_module: str, *, max_hops: int = _MAX_IMPORT_HOPS) -> bool:
    """Whether *entry_module* reaches the write chokepoint via `pdf_tooling.*` imports.

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


# --------------------------------------------------------------------------- #
# PDF-67 -- the ENGINE-BLIND class, derived from the import graph.
#
# The claim `README.md`'s code-`0` row now carries is about a verb whose
# operand is judged by an out-of-process engine the preview may not start. That
# is a property of the import graph, not of a verb name, and it is derived here
# so a third engine verb joins the class with zero author action.
#
# WHY NOT `VerbSpec.requires_engine`/`INVOCATIONS`: that field is hand-set,
# test-harness-side, and set on a single row (`convert`) -- `ocr` declares
# `None` there deliberately, because it has an engine-free path. A population
# read off it would report a class of one and be a verb list wearing a
# derivation's clothes.
#
# WHY NOT `reaches_atomic_writer`'s walker, reused verbatim: MEASURED at
# `20a3dbc`, and the measurement is the reason the two walks differ at all.
# --------------------------------------------------------------------------- #

#: The product's ONE process-spawn point (`adapters/subprocess_util.py`'s own
#: module docstring says so, and `tests/test_license_policy.py::
#: test_subprocess_chokepoint` asserts nothing else under `src/` imports
#: `subprocess`). The derivation below therefore rests on a property the suite
#: already keeps true rather than on a fresh assumption.
_SPAWN_CHOKEPOINT: Final[str] = "pdf_tooling.adapters.subprocess_util"

#: The package modules the walk refuses to traverse THROUGH, and this exclusion
#: is a measurement rather than a preference.
#:
#: Each of the three is an AGGREGATOR: it names every member of a package by
#: construction, so an edge through it means "this module is part of the same
#: product as that one", never "this module depends on that one".
#:
#: * `pdf_tooling.ports.__init__` -- `resolve()` and `probe_all()` each carry a
#:   function-local `from pdf_tooling.ports import compose, ocr, office,
#:   raster, structure, text`, which is `doctor`'s whole job. MEASURED: a walk
#:   that descends into it reports ALL SIX ports as engine ports.
#: * `pdf_tooling.adapters.__init__` -- `doctor`'s probe helper, the same shape.
#: * `pdf_tooling.cli.main` -- the command registry, which imports every
#:   `cli/cmd_*` module in order to register it. MEASURED: dropping THIS entry
#:   alone reports fifteen engine-blind verbs, because every `cmd_*` module
#:   imports `cli.main` and `cli.main` imports `cmd_ocr`; dropping all three
#:   reports twenty-five, `doctor` included -- and every contract cell over the
#:   population stays green throughout, which is why the agreement check in
#:   `tests/test_cli_contract.py::test_c26_the_population_is_derived_from_the_import_graph`
#:   exists rather than being inferred from those cells passing.
#:
#: `reaches_atomic_writer` above does NOT apply this exclusion, and it is not
#: changed here: `is_mutating` is a shipped classifier that C11/C13/C15 depend
#: on, and re-scoping it to suit this population would be a change to three
#: other checks made sideways. The two walks answer different questions and are
#: allowed to differ; what is not allowed is one silently becoming the other.
_IMPORT_GRAPH_AGGREGATORS: Final[frozenset[str]] = frozenset(
    {
        "pdf_tooling.ports",
        "pdf_tooling.adapters",
        "pdf_tooling.cli.main",
    }
)


def _pdf_tooling_module_imports(path: Path) -> set[str]:
    """Every `pdf_tooling.*` MODULE *path*'s own source names, SUBMODULES included.

    The one behavioural difference from :func:`_imports_and_references`, and it
    is required rather than stylistic: `from pdf_tooling.adapters import
    soffice_office` records `pdf_tooling.adapters` there, so the walker that
    feeds `is_mutating` sees the PACKAGE and never the adapter module. Measured
    at `20a3dbc`: `adapters/__init__.py` does not import `subprocess_util`, so a
    walk built on that reading cannot reach the spawn chokepoint from a port at
    all. Each alias is therefore offered as `<module>.<name>` too, and
    :func:`_dotted_to_path` discards the ones that are functions or constants
    rather than modules.

    Same `ast`-over-source convention as every other walk in this module; never
    a real import.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("pdf_tooling")
        ):
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith("pdf_tooling"))
    return {
        dotted
        for dotted in found
        if dotted not in _IMPORT_GRAPH_AGGREGATORS and _dotted_to_path(dotted) is not None
    }


def _reaches_any(entry_module: str, targets: frozenset[str], *, max_hops: int) -> bool:
    """Whether *entry_module* reaches any of *targets*, bounded, aggregators excluded."""
    if entry_module in _IMPORT_GRAPH_AGGREGATORS:
        return False
    seen: set[str] = set()
    frontier = [entry_module]
    for _ in range(max_hops):
        next_frontier: list[str] = []
        for dotted in frontier:
            if dotted in seen or dotted in _IMPORT_GRAPH_AGGREGATORS:
                continue
            seen.add(dotted)
            path = _dotted_to_path(dotted)
            if path is None:
                continue
            imported = _pdf_tooling_module_imports(path)
            if imported & targets:
                return True
            next_frontier.extend(sorted(imported))
        frontier = next_frontier
        if not frontier:
            break
    return False


def engine_ports(*, max_hops: int = _MAX_IMPORT_HOPS) -> frozenset[str]:
    """Every `ports/` module whose adapter reaches the ONE spawn chokepoint.

    Step 1 of PDF-67's two-step derivation. The target is the engine PORTS
    rather than `subprocess` itself, and a RECORDED PREMISE DID NOT HOLD when it
    was re-measured here: the planning artifact predicted that walking straight
    to the spawn chokepoint would balloon the population, because
    `safety/confirm.py` and `ops/procpool.py` also import `subprocess`. Measured
    at `20a3dbc`, it does not -- those two import the STDLIB `subprocess`, not
    `adapters/subprocess_util`, and the direct walk returns the same pair. The
    blow-up this derivation actually has to defend against is the AGGREGATOR
    edge above, not the choice of target. The two-step shape is kept anyway: it
    is what makes the class statable ("the preview did not run the ENGINE over
    this operand") and what lets the agreement check in
    `tests/test_cli_contract.py::test_c26_the_population_is_derived_from_the_import_graph`
    compare this walk against each port's own declared kind.

    Derived at `20a3dbc`: `pdf_tooling.ports.ocr`, `pdf_tooling.ports.office`.
    """
    ports_dir = SRC / "pdf_tooling" / "ports"
    return frozenset(
        dotted
        for dotted in (
            f"pdf_tooling.ports.{path.stem}"
            for path in sorted(ports_dir.glob("*.py"))
            if path.stem != "__init__"
        )
        if _reaches_any(dotted, frozenset({_SPAWN_CHOKEPOINT}), max_hops=max_hops)
    )


def reaches_engine_port(entry_module: str, *, max_hops: int = _MAX_IMPORT_HOPS) -> bool:
    """Whether *entry_module* reaches an engine port -- the sibling of
    :func:`reaches_atomic_writer`, same `ast` walk, same `_dotted_to_path`.

    PROVENANCE: static over the source tree, never a real import, never a
    `--help` census, never a typed verb list.

    FITNESS -- why reaching an ENGINE PORT is the right property for the claim
    this feeds, stated here because provenance alone has already let a wrong
    population ship on this product. PDF-67's disclosure says one thing: *the
    preview did not run the engine over this operand*. A verb can only be blind
    in that way if there IS an out-of-process engine standing between it and a
    verdict on its operand -- which is exactly what reaching a port whose
    adapter reaches the spawn chokepoint means, and what nothing else in the
    registry means. `is_mutating` answers "can this verb write" (a different
    question, and true of twenty-three verbs); `takes_input_paths` answers "does
    it accept an operand"; `requires_engine` is hand-set on one row. None of
    them can tell a verb whose operand LibreOffice judges from a verb whose
    operand pypdf judges in-process, and that distinction is the whole claim.
    """
    return _reaches_any(entry_module, engine_ports(max_hops=max_hops), max_hops=max_hops)


def engine_blind_verbs(root: object | None = None) -> tuple[str, ...]:
    """Every verb whose operand only an out-of-process engine can finally judge.

    Step 2, and keyed on the live command's VERB NAME rather than its module
    basename -- `cli/cmd_office.py` registers `convert`, so a module-keyed
    population is a different population from the one a user types and the
    payload's own `verb` field carries (`out_dir_batch_verbs()` records the same
    trap, and it is the step a re-derivation is most likely to skip).

    Derived at `20a3dbc`: `convert`, `ocr` -- which is independently what
    `README.md` names in the user's own words, *"the two verbs that depend on a
    system binary rather than a Python wheel"*. A derivation that disagrees with
    the product's own documentation is a finding, not a new figure to adopt.
    """
    ports = engine_ports()
    return tuple(
        sorted(
            verb.name
            for verb in discover_verbs(root)
            if not verb.is_group
            and verb.module is not None
            and _reaches_any(verb.module, ports, max_hops=_MAX_IMPORT_HOPS)
        )
    )


def _takes_input_paths(cmd: object) -> bool:
    return any(
        getattr(param, "param_type_name", None) == "argument"
        and getattr(getattr(param, "type", None), "name", None) == "path"
        for param in cmd.params  # type: ignore[attr-defined]
    )


def _takes_positional_argument(cmd: object) -> bool:
    """PDF-54 D2 -- a positional ``argument`` of ANY type, never narrowed to
    ``click.Path`` the way :func:`_takes_input_paths` is. See
    ``VerbSpec.takes_positional_argument``'s own docstring for why the two
    predicates must stay independent rather than one being expressed as a
    special case of the other."""
    return any(
        getattr(param, "param_type_name", None) == "argument"
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
                takes_positional_argument=_takes_positional_argument(cmd),
                module=module,
            )
        )

    _walk(group, ())
    return tuple(found)


def no_input_population(root: object | None = None) -> tuple[str, ...]:
    """PDF-54 D2 -- every leaf with a no-input failure arm to reach, DERIVED
    from `VerbSpec.takes_positional_argument`, never from `takes_input_paths`
    (`click.Path`-typed, silently drops `merge` -- E12) and never from a
    typed list. `doctor` and `version` decline no positional operand and are
    correctly excluded. A verb registered tomorrow joins this population
    with zero author action, mirroring `discover_verbs()`'s own "no skip
    list, ever" contract."""
    return tuple(
        sorted(
            verb.name
            for verb in discover_verbs(root)
            if not verb.is_group and verb.takes_positional_argument
        )
    )


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
    sibling = Path(sys.executable).parent / "pdftooling"
    if sibling.exists():
        return [str(sibling)]
    found = shutil.which("pdftooling")
    if found:
        return [found]
    return [sys.executable, "-m", "pdf_tooling"]


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
# PDF_TOOLING_TEST_HIDE_ENGINES=tesseract,soffice, `ocr`'s own C9-C16 rows
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
# checks VISIBLY, by name, whenever `pdf_tooling.ports.resolve("OfficeConverter")`
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


# --------------------------------------------------------------------------- #
# PDF-54 -- the failure arm's own invocation population, one purpose-built
# `no_input_build` per `no_input_population()` member (D3), on the identical
# precedent `destructive_build` already set for C13's bulk arm.
#
# Every row points its operand at a path that does NOT exist under the
# test's own `tmp_path` and never creates it (HC-2). Everything past the
# operand is copied from that verb's own `build()` counterpart, because
# Click's required-option enforcement runs BEFORE the no-input check ever
# does -- measured (E13): a bare `<verb> <missing>` reaches `kind: "usage"`,
# never `"no_input"`, on `merge` (missing `-O`/`--output`), `rasterize`
# (accepts `--out-dir`, never `--output`), `reorder` and `stamp` (each
# needs its own required flag first). A shared "just swap the operand"
# helper would freeze the wrong `kind` on exactly those four leaves while
# looking green on the other twenty -- this is why the field is purpose-built
# per leaf rather than a fallback onto `build`.
# --------------------------------------------------------------------------- #


def _missing_path(tmp_path: Path, filename: str) -> Path:
    """A path under *tmp_path* a `no_input_build` row points at and never
    creates. One place stating the invariant (HC-2) rather than twenty-four."""
    return tmp_path / filename


def _compose_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-compose.jpg")),
        "-O",
        str(tmp_path / "pdf54-no-input-compose-out.pdf"),
    ]


def _compress_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-compress.pdf")),
        "-O",
        str(tmp_path / "pdf54-no-input-compress-out.pdf"),
    ]


def _convert_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    """Engine-independent, like `_convert_invocation` is not: the no-input
    check fires before engine resolution ever runs (E8, measured with the
    OfficeConverter binary genuinely hidden from `PATH`), so this row needs
    no `soffice`."""
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-convert.txt")),
        "-O",
        str(tmp_path / "pdf54-no-input-convert-out.pdf"),
    ]


def _create_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-create.txt")),
        "-O",
        str(tmp_path / "pdf54-no-input-create-out.pdf"),
    ]


def _decrypt_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    """`--password-file` must resolve as a real file (Click's own option
    validation) or the run would reach `kind: "usage"` before the operand is
    ever inspected -- the file's CONTENT is irrelevant to this arm, only its
    existence, so it is a fresh throwaway, never a corpus original."""
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-decrypt.pdf")),
        "--password-file",
        str(_password_file(tmp_path, "pdf54-no-input-decrypt.pw", "pdf54-probe-pw")),
        "-O",
        str(tmp_path / "pdf54-no-input-decrypt-out.pdf"),
    ]


def _delete_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-delete.pdf")),
        "--pages",
        "1",
        "-O",
        str(tmp_path / "pdf54-no-input-delete-out.pdf"),
    ]


def _encrypt_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    """Same reasoning as `_decrypt_no_input_build`, for `--owner-password-file`."""
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-encrypt.pdf")),
        "--owner-password-file",
        str(_password_file(tmp_path, "pdf54-no-input-encrypt.pw", "pdf54-probe-pw")),
        "-O",
        str(tmp_path / "pdf54-no-input-encrypt-out.pdf"),
    ]


def _extract_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-extract.pdf")),
        "--pages",
        "1,2",
        "-O",
        str(tmp_path / "pdf54-no-input-extract-out.pdf"),
    ]


def _info_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    """PDF-51's own arm: `info` now returns the run-scoped error envelope on
    a nonexistent input, matching its twenty-one path-taking siblings."""
    del corpus
    return [str(_missing_path(tmp_path, "pdf54-no-input-info.pdf"))]


def _linearize_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-linearize.pdf")),
        "-O",
        str(tmp_path / "pdf54-no-input-linearize-out.pdf"),
    ]


def _merge_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    """E13's own first trap: `merge <missing>` alone reaches `kind: "usage"`
    ("merge requires -O/--output"), never the operand check -- `merge`'s
    `-O` is REQUIRED and Click enforces it before the callback body (where
    the no-input check lives) ever runs. `merge`'s operand is `str`-typed
    (E12), not `click.Path`, so a nonexistent string is fine syntactically;
    `merge`'s own code performs the existence check itself."""
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-merge.pdf")),
        "-O",
        str(tmp_path / "pdf54-no-input-merge-out.pdf"),
    ]


def _meta_get_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    del corpus
    return [str(_missing_path(tmp_path, "pdf54-no-input-meta-get.pdf"))]


def _meta_set_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-meta-set.pdf")),
        "--title",
        "pdf54-no-input-probe",
        "-O",
        str(tmp_path / "pdf54-no-input-meta-set-out.pdf"),
    ]


def _ocr_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    """`ocr` requires exactly one of `--output`/`--out-dir`/`--in-place`
    (`cli/cmd_ocr.py`'s own usage message) before the operand is ever
    inspected -- `-O` here, same shape `_ocr_invocation` uses. No
    `--skip-text-pages` needed: the no-input check fires before any engine
    is ever demanded (E8), so this row is engine-independent for free."""
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-ocr.pdf")),
        "-O",
        str(tmp_path / "pdf54-no-input-ocr-out.pdf"),
    ]


def _permissions_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    del corpus
    return [str(_missing_path(tmp_path, "pdf54-no-input-permissions.pdf"))]


def _rasterize_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    """E13's second trap: `rasterize <missing> -O out.pdf` reaches
    `kind: "usage"` ("rasterize does not accept --output") -- `rasterize`
    consumes `--out-dir`/`--name`, never `--output` (Design §D10), and this
    row must not guess `-O` the way a shared swap helper would."""
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-rasterize.pdf")),
        "--out-dir",
        str(tmp_path / "pdf54-no-input-rasterize-out"),
    ]


def _repair_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-repair.pdf")),
        "-O",
        str(tmp_path / "pdf54-no-input-repair-out.pdf"),
    ]


def _reorder_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    """E13's third trap: `reorder <missing> --order 1 -O out.pdf` reaches
    `kind: "usage"` ("No such option: --order") -- `reorder`'s page spec is
    `--pages`, matching `_reorder_invocation`'s own row, never `--order`."""
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-reorder.pdf")),
        "--pages",
        "last,1",
        "-O",
        str(tmp_path / "pdf54-no-input-reorder-out.pdf"),
    ]


def _rotate_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-rotate.pdf")),
        "--pages",
        "1",
        "--angle",
        "90",
        "-O",
        str(tmp_path / "pdf54-no-input-rotate-out.pdf"),
    ]


def _split_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-split.pdf")),
        "--each-page",
        "--out-dir",
        str(tmp_path / "pdf54-no-input-split-out"),
    ]


def _stamp_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    """E13's fourth trap: `stamp <missing> --text hi -O out.pdf` reaches
    `kind: "usage"` ("No such option: --text") -- `stamp` has no `--text`
    flag at all; its required flag is `--from <existing PDF>`, matching
    `_stamp_invocation`'s own row. `--from`'s value is not the operand under
    test, so it is read from the generated `corpus` fixture exactly as
    `_stamp_invocation` already does -- HC-2 governs the OPERAND, not every
    incidental flag value a required option demands."""
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-stamp.pdf")),
        "--from",
        str(corpus.path("single_page")),  # type: ignore[attr-defined]
        "-O",
        str(tmp_path / "pdf54-no-input-stamp-out.pdf"),
    ]


def _tables_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-tables.pdf")),
        "-O",
        str(tmp_path / "pdf54-no-input-tables-out.csv"),
    ]


def _text_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-text.pdf")),
        "-O",
        str(tmp_path / "pdf54-no-input-text-out.txt"),
    ]


def _watermark_no_input_build(corpus: object, tmp_path: Path) -> list[str]:
    del corpus
    return [
        str(_missing_path(tmp_path, "pdf54-no-input-watermark.pdf")),
        "--text",
        "pdf54-no-input-probe",
        "-O",
        str(tmp_path / "pdf54-no-input-watermark-out.pdf"),
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
    "info": Invocation(build=_info_invocation, no_input_build=_info_no_input_build),
    "merge": Invocation(
        build=_merge_invocation, destructive=False, no_input_build=_merge_no_input_build
    ),
    "split": Invocation(
        build=_split_invocation, destructive=False, no_input_build=_split_no_input_build
    ),
    "rasterize": Invocation(
        build=_rasterize_invocation, destructive=False, no_input_build=_rasterize_no_input_build
    ),
    "compose": Invocation(
        build=_compose_invocation, destructive=False, no_input_build=_compose_no_input_build
    ),
    "create": Invocation(
        build=_create_invocation, destructive=False, no_input_build=_create_no_input_build
    ),
    # PDF-11. Both are read verbs toward their INPUT and producing verbs toward
    # their destination, so both are `is_mutating` (they reach the write
    # chokepoint) and both land in C15's PRODUCING population.
    "text": Invocation(
        build=_text_invocation, destructive=False, no_input_build=_text_no_input_build
    ),
    "tables": Invocation(
        build=_tables_invocation, destructive=False, no_input_build=_tables_no_input_build
    ),
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
        no_input_build=_compress_no_input_build,
    ),
    "repair": Invocation(
        build=_repair_invocation, destructive=False, no_input_build=_repair_no_input_build
    ),
    "linearize": Invocation(
        build=_linearize_invocation, destructive=False, no_input_build=_linearize_no_input_build
    ),
    # PDF-13. `encrypt`/`decrypt` are single-target producing verbs;
    # `permissions` is NON-PRODUCING and its row names no destination, which
    # is why it is absent from C11/C15 rather than skipped by them.
    "encrypt": Invocation(
        build=_encrypt_invocation, destructive=False, no_input_build=_encrypt_no_input_build
    ),
    "decrypt": Invocation(
        build=_decrypt_invocation, destructive=False, no_input_build=_decrypt_no_input_build
    ),
    "permissions": Invocation(
        build=_permissions_invocation,
        destructive=False,
        no_input_build=_permissions_no_input_build,
    ),
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
    "extract": Invocation(
        build=_extract_invocation, destructive=False, no_input_build=_extract_no_input_build
    ),
    "delete": Invocation(
        build=_delete_invocation, destructive=False, no_input_build=_delete_no_input_build
    ),
    "rotate": Invocation(
        build=_rotate_invocation, destructive=False, no_input_build=_rotate_no_input_build
    ),
    "reorder": Invocation(
        build=_reorder_invocation, destructive=False, no_input_build=_reorder_no_input_build
    ),
    # PDF-14. `meta get` is NON-PRODUCING, same shape as `permissions`.
    # `meta set`/`watermark`/`stamp` are single-target producing verbs over
    # `StructureEngine` (+ `ComposeEngine` for `watermark`'s text layer);
    # none is destructive, matching every other producing verb's own note
    # above -- a single input writing to `-O` is neither bulk nor
    # destructive, so C13 has nothing to refuse.
    "meta get": Invocation(
        build=_meta_get_invocation, destructive=False, no_input_build=_meta_get_no_input_build
    ),
    "meta set": Invocation(
        build=_meta_set_invocation, destructive=False, no_input_build=_meta_set_no_input_build
    ),
    "watermark": Invocation(
        build=_watermark_invocation, destructive=False, no_input_build=_watermark_no_input_build
    ),
    "stamp": Invocation(
        build=_stamp_invocation, destructive=False, no_input_build=_stamp_no_input_build
    ),
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
        no_input_build=_ocr_no_input_build,
    ),
    "convert": Invocation(
        build=_convert_invocation,
        destructive=False,
        requires_engine="OfficeConverter",
        no_input_build=_convert_no_input_build,
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
    ``src/pdf_tooling/output/__init__.py`` joins every consuming matrix with
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

    from pdf_tooling.cli.common import PASSWORD_FILE_FLAGS

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
    ~~`color_enabled()` on `sys.stderr.isatty()`~~ -- neither stream had ever
    been made a terminal by any test idiom in this repository before this
    function, which is why the sixth shape (a table on stderr, under a
    terminal, with no ``-o`` flag) was unreachable by anything shipped.

    STRUCK 2026-09-15 (`PDF-65`, OR-18): `color_enabled()` no longer exists --
    it was dead code behind an inert `--no-color`, and the flag was REMOVED at
    `v1.0.0` rather than implemented. The clause is struck rather than deleted
    because it is the recorded motivation, not a live claim.

    WHAT JUSTIFIES THE STDERR PTY TODAY, which is a different and still-true
    proposition: `sys.stderr.isatty()` remains an observable difference in
    STREAM POSTURE -- `output/logging.py` builds this process's stderr handler,
    `safety/confirm.py` reads a terminal, and the password-record and
    secret-leak arms assert their guarantees hold IDENTICALLY with stderr as a
    real terminal and as a pipe. No test idiom but this one can put stderr in
    that posture, so the capability stands on its own evidence rather than on a
    function that has been removed.

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


# --------------------------------------------------------------------------- #
# PDF-74 -- the argument VALUE-SHAPE dimension.
#
# Every dimension above answers a question the command tree can be asked: which
# verbs exist, which flags they declare, which enum members exist. NONE of them
# describes THE SHAPE OF THE VALUE A USER TYPES, and this harness has a uniform,
# unexamined convention that pins it to one shape -- `str(tmp_path / ...)`,
# always absolute. `PDF-64` measured what that costs: a `--dry-run` with a
# relative, not-yet-existing `--out-dir` crashed with a raw `ValueError`, exit
# 1, zero bytes on stdout, on all ELEVEN `--out-dir` verbs, while the identical
# argv without `--dry-run` succeeded on all eleven -- and 4,450 tests were green
# over it, including the contract row added three specs earlier to assert that a
# dry run predicts the real run's exit code.
#
# :data:`PATH_SPELLINGS` is a :func:`tty_modes`/:data:`PDF_08_VERBS`-class
# member: DECLARED, never derived, because the shapes a user can type are not
# enumerable from the command tree -- there is no spelling enum under `src/` to
# iterate, and inventing one there to make a test derivable would be a product
# change made to serve a test. A declaration is only admissible with the two
# things those precedents carry, and both live in
# `tests/test_derived_dimensions.py`:
#
#   * a LIVE TIE that fails when the axis collapses -- two distinct spellings of
#     one destination must still produce two distinct rendered payload values at
#     every `(verb, flag)` cell, or something has absolutized at the boundary
#     and this tuple describes nothing;
#   * an AST SCAN that fails when the members are re-listed anywhere under
#     `tests/` outside this declaration site, in the shape `PDF_08_VERBS`'
#     own AC30 scan already has.
#
# The rows are deliberately left in a shape the deferred operand-side property
# (`I-15` / `B-311`) can CONSUME rather than re-declare: a `render(anchor, leaf)`
# that builds a value and an `anchoring` that says what it is are as true of a
# positional operand as of a destination flag.
# --------------------------------------------------------------------------- #

#: The working subdirectory the `parent-relative` row runs from, and the sibling
#: it then descends into. Two names rather than one because the row's whole
#: point is that the value ASCENDS out of the process `cwd` before it descends,
#: which a single directory cannot express.
SPELLING_SUB_DIR: Final[str] = "sub"

#: The `symlink` row's link and its target. `--out-dir` normalizes with
#: `.absolute()` (symlinks NOT followed) and `--output` with `canonical()`
#: (symlinks followed), so this is the spelling at which the two destination
#: flags answer two different identity questions.
SPELLING_LINK_NAME: Final[str] = "link"
SPELLING_REAL_DIR: Final[str] = "real"

#: The `nonexistent-parent` row's intermediate component, which must NOT exist
#: when the cell runs -- the precondition that makes the row cross the existing
#: unwritable-parent tier instead of duplicating the ordinary cell.
SPELLING_ABSENT_DIR: Final[str] = "missing"

#: The two `anchoring` values. The red control derives its predicted red set
#: from this field (a relative `Path` is what `relative_to` raised on), so it is
#: DATA rather than a comment.
ANCHORING_ABSOLUTE: Final[str] = "absolute"
ANCHORING_RELATIVE: Final[str] = "relative"

#: The one row whose value presupposes a redirected `$HOME` rather than a
#: chosen `cwd`. Named once so a consumer asks the declaration instead of
#: matching on a tilde character.
TILDE_SPELLING: Final[str] = "tilde"


def _render_absolute(anchor: Path, leaf: str) -> str:
    return str(anchor / leaf)


def _render_bare_relative(anchor: Path, leaf: str) -> str:
    return leaf


def _render_dot_relative(anchor: Path, leaf: str) -> str:
    return f"./{leaf}"


def _render_parent_relative(anchor: Path, leaf: str) -> str:
    return f"../{anchor.name}/{leaf}"


def _render_trailing_slash(anchor: Path, leaf: str) -> str:
    return f"{leaf}/"


def _render_tilde(anchor: Path, leaf: str) -> str:
    return f"~/{leaf}"


def _render_symlink(anchor: Path, leaf: str) -> str:
    return f"{SPELLING_LINK_NAME}/{leaf}"


def _render_absent_parent(anchor: Path, leaf: str) -> str:
    return f"{SPELLING_ABSENT_DIR}/{leaf}"


def _prepare_nothing(anchor: Path) -> None:
    return None


def _prepare_parent_relative(anchor: Path) -> None:
    """The `cwd` to ascend out of, and the sibling to descend into.

    Both are created here rather than by the cell, because `--output` refuses a
    destination whose parent does not exist -- without the sibling, this row
    would silently become a second copy of `nonexistent-parent`.
    """
    (anchor / SPELLING_SUB_DIR).mkdir(parents=True, exist_ok=True)
    (anchor / anchor.name).mkdir(parents=True, exist_ok=True)


def _prepare_symlink(anchor: Path) -> None:
    real = anchor / SPELLING_REAL_DIR
    real.mkdir(parents=True, exist_ok=True)
    link = anchor / SPELLING_LINK_NAME
    if not os.path.lexists(link):
        os.symlink(real, link)


def _prepare_absent_parent(anchor: Path) -> None:
    """Asserts its own precondition rather than creating anything.

    `os.path.lexists`, never `.exists()`: a dangling link at this name would
    satisfy `.exists()` with `False` and still make `mkdir(parents=True)`
    answer a different question than this row intends to ask.
    """
    absent = anchor / SPELLING_ABSENT_DIR
    if os.path.lexists(absent):
        raise AssertionError(
            f"the nonexistent-parent spelling presupposes {absent} is ABSENT, and it exists "
            "-- the row would then be a second copy of the ordinary relative cell"
        )


def _cwd_anchor(anchor: Path) -> Path:
    return anchor


def _cwd_sub(anchor: Path) -> Path:
    return anchor / SPELLING_SUB_DIR


@dataclass(frozen=True, slots=True)
class PathSpelling:
    """One shape a user can type for a destination path value.

    Attributes:
        id: The stable name of the shape. The ONE place it is written down;
            re-listing it anywhere else under `tests/` fails the AC3 scan.
        anchoring: :data:`ANCHORING_ABSOLUTE` or :data:`ANCHORING_RELATIVE`.
            The red control derives its predicted red set from this field.
        render: ``render(anchor, leaf) -> str`` -- the argv VALUE. *leaf* is
            supplied by the cell rather than by the row, because `--out-dir`
            needs a directory name and `--output` a file name (with the right
            extension, which only the registered invocation knows).
        prepare: ``prepare(anchor) -> None`` -- creates (or asserts absent)
            whatever the spelling presupposes.
        cwd: ``cwd(anchor) -> Path`` -- the process working directory the cell
            MUST run under. A relative value driven from the wrong directory
            measures nothing, which is why the builder asserts this rather than
            documenting it.
        redirect_home: whether the row's value is anchored on ``$HOME`` instead
            of the working directory.
    """

    id: str
    anchoring: str
    render: Callable[[Path, str], str]
    prepare: Callable[[Path], None]
    cwd: Callable[[Path], Path]
    redirect_home: bool


#: The eight shapes, `I-6`'s own list preserved verbatim.
#:
#: TWO MEMBERS OF `AUDIT.md` 5.1's LIST ARE DELIBERATELY ABSENT, with grounds,
#: so a later reader does not read the gap as an oversight. `-` (a stdin
#: sentinel) is not a destination that a directory or an atomic replace can
#: denote, and the product declares no stdin sentinel at either flag. A value
#: that looks like a flag (`--out-dir --force`) is a USAGE-tier property of the
#: CLI framework's parser, one tier above the geometry these rows cover, and
#: mixing a tier-2 oracle into a tier-1 matrix is how `C8` came to assert a
#: third-party library. The flag-lookalike shape is a real member of this
#: dimension and is filed for a carrier of its own rather than smuggled in here.
PATH_SPELLINGS: Final[tuple[PathSpelling, ...]] = (
    PathSpelling(
        "absolute", ANCHORING_ABSOLUTE, _render_absolute, _prepare_nothing, _cwd_anchor, False
    ),
    PathSpelling(
        "bare-relative",
        ANCHORING_RELATIVE,
        _render_bare_relative,
        _prepare_nothing,
        _cwd_anchor,
        False,
    ),
    PathSpelling(
        "dot-relative",
        ANCHORING_RELATIVE,
        _render_dot_relative,
        _prepare_nothing,
        _cwd_anchor,
        False,
    ),
    PathSpelling(
        "parent-relative",
        ANCHORING_RELATIVE,
        _render_parent_relative,
        _prepare_parent_relative,
        _cwd_sub,
        False,
    ),
    PathSpelling(
        "trailing-slash",
        ANCHORING_RELATIVE,
        _render_trailing_slash,
        _prepare_nothing,
        _cwd_anchor,
        False,
    ),
    PathSpelling(
        TILDE_SPELLING, ANCHORING_RELATIVE, _render_tilde, _prepare_nothing, _cwd_anchor, True
    ),
    PathSpelling(
        "symlink", ANCHORING_RELATIVE, _render_symlink, _prepare_symlink, _cwd_anchor, False
    ),
    PathSpelling(
        "nonexistent-parent",
        ANCHORING_RELATIVE,
        _render_absent_parent,
        _prepare_absent_parent,
        _cwd_anchor,
        False,
    ),
)


def path_spellings() -> tuple[PathSpelling, ...]:
    """The value-shape axis, in the shape :func:`output_formats` and
    :func:`tty_modes` already have, so every consumer imports a CALL rather
    than a constant and the deferred operand-side property (`I-15`, `B-311`)
    can consume the same rows without a second declaration."""
    return PATH_SPELLINGS


def spelled_destination(spelling: PathSpelling, anchor: Path, leaf: str, *, home: Path) -> Path:
    """The absolute path *spelling* DENOTES, by the rule a shell would use.

    This is the oracle a mirror comparison and an echo comparison cannot give:
    a run that echoes ``~/out`` and writes ``./~/out`` agrees with itself on the
    exit code AND on the spelling, and is still wrong. The one place the
    expansion rule is written down, so a cell asks it instead of reimplementing
    it per tier.
    """
    value = spelling.render(anchor, leaf)
    if value.startswith("~/"):
        value = f"{home}{value[1:]}"
    return Path(spelling.cwd(anchor)) / value


#: The two destination flags whose VALUE this dimension is scoped to. `--name`
#: is a filename TEMPLATE rather than a path, and `--in-place` takes no value at
#: all, so neither is a member of this axis; the operand side is the deferred
#: `I-15` property and is not driven here. Tied to the product's own
#: `OUTPUT_FLAGS` by `tests/test_derived_dimensions.py`, so a flag renamed under
#: `src/` cannot leave this pair silently stale.
DESTINATION_VALUE_FLAGS: Final[tuple[str, ...]] = ("--out-dir", "--output")


def destination_flag_cases(root: object | None = None) -> tuple[tuple[str, str], ...]:
    """Every ``(verb, flag)`` pair that takes a destination PATH value.

    PROVENANCE. A leaf (``not verb.is_group``) whose own ``consumes``
    declaration contains the flag, for each flag in
    :data:`DESTINATION_VALUE_FLAGS`. ``consumes`` is itself derived --
    ``_common.consumed_output_flags(module)`` -- so this is the live
    declaration, never a grep over docstrings (two module docstrings mention
    ``--out-dir`` beside a literal ``consumes=()``) and never the module
    basename (`cli/cmd_office.py` registers ``convert``; a population keyed on
    the module reports ``convert`` missing while inventing ``office``).

    FITNESS, and this is the statement `X-157` does not ask for. The property
    being tested is *does the SHAPE OF THE VALUE the user typed change the
    answer?*, and the only filter that question licenses is **flag
    declaration**. Every other filter a neighbouring population applies is a
    filter this property does not license -- which is not a hypothetical:
    :func:`out_dir_batch_verbs` was proposed for this job twice, and its step-2
    **operand arity** filter drops ``split``, giving a TEN-verb answer for an
    ELEVEN-verb defect. Arity is a fit property of *can a bad input sit in the
    middle of a batch?* and an irrelevant one here: ``_ensure_out_dir`` has a
    single call site, ``plan_output_set``, and ``ops/split.py`` reaches it
    directly. `tests/integration/test_value_shape.py` MECHANIZES this
    paragraph -- prose alone was satisfied by `PDF-64`'s own brief, which
    carried a provenance statement and still named the wrong population.

    Thirty pairs at `b16fb87`/`aae2822`: eleven at ``--out-dir`` including
    ``split``, nineteen at ``--output``. A verb declaring both flags is TWO
    cells and not one, because the two flags do not share a code path --
    ``--out-dir`` reaches ``_ensure_out_dir``/``_predict_out_dir_creation`` and
    ``--output`` reaches ``AtomicWriter``/``ensure_no_clobber``, and the two do
    not even agree on how they normalize a path.
    """
    leaves = sorted(
        (verb for verb in discover_verbs(root) if not verb.is_group), key=lambda verb: verb.name
    )
    return tuple(
        (verb.name, flag)
        for flag in DESTINATION_VALUE_FLAGS
        for verb in leaves
        if flag in verb.consumes
    )


#: PDF-82 D2 — the ``@pytest.mark.requires(...)`` spelling for each engine port
#: a destination cell can depend on. Hand-written, and it cannot go stale
#: silently in either direction: `tests/conftest.py::_resolve_port` raises
#: ``ValueError`` naming an unknown spelling AT COLLECTION TIME, so a wrong key
#: errors every gated cell in the matrix rather than skipping one quietly, and
#: `tests/test_engine_gating_census.py` asserts the spelling is one
#: `scripts/assert_skips.py` classifies as ``engine-gated``. The FRIENDLY name
#: and not the port name, for that second reason: the port name reaches that
#: classifier only through the platform-dependent install hint, which is the
#: same accidental truth `PDF-82` E5 found underneath ``ocr``'s cells.
ENGINE_MARKER_SPELLINGS: Final[dict[str, str]] = {
    "OcrEngine": "tesseract",
    "OfficeConverter": "soffice",
}

#: PDF-82 E4 — the destination cells whose OUTCOME does not depend on the engine
#: even though their verb does. MEASURED PER CELL, never per verb, and this
#: entry is the disproof of the per-verb shortcut: driven at `3aedef8` with the
#: engines present and again with them hidden, the ``--output`` ×
#: ``nonexistent-parent`` cell's four envelopes (dry and real, both
#: configurations) are BYTE-IDENTICAL — the destination refusal fires at the
#: safety tier BEFORE the engine resolves, so the cell exercises the same code
#: path either way. Gating it would turn a genuinely engine-free cell into a
#: permanent skip, and that loss is invisible to every instrument in this
#: repository (`PDF-82` D2's asymmetry table). Its ``--out-dir`` sibling is
#: deliberately absent: that limb CREATES the directory and proceeds to the
#: engine, which is why it reds under absence and this one does not.
ENGINE_FREE_DESTINATION_CELLS: Final[frozenset[tuple[str, str, str]]] = frozenset(
    {("convert", "--output", "nonexistent-parent")}
)


def destination_cell_engine(verb: str, flag: str, spelling_id: str | None = None) -> str | None:
    """The engine a ``(verb, flag[, spelling])`` destination cell's OUTCOME needs,
    or ``None`` when the cell answers the same question with the engine absent.

    PROVENANCE. :data:`INVOCATIONS`'s own ``requires_engine`` field names the
    port (``convert`` declares ``OfficeConverter``; ``ocr`` declares ``None``
    deliberately, because its cells drive ``--skip-text-pages``, that verb's
    engine-free path), minus the measured per-cell exceptions above. Consumed by
    `tests/integration/test_value_shape.py` and `tests/test_derived_dimensions.py`
    at their PARAMETRIZE, so the mark rides the cell rather than the function and
    neither module has to type a node id.

    A verb with no invocation row answers ``None`` — under-marking, which
    `make engines-gate` arm 2 reds loudly, rather than over-marking, which
    nothing in this repository can see.
    """
    invocation = INVOCATIONS.get(verb)
    port = None if invocation is None else invocation.requires_engine
    if port is None:
        return None
    if spelling_id is not None and (verb, flag, spelling_id) in ENGINE_FREE_DESTINATION_CELLS:
        return None
    return ENGINE_MARKER_SPELLINGS[port]


#: Every ``VerbSpec`` field a population may read WITHOUT narrowing the
#: value-shape property, mapped to what filtering on it would actually mean.
#: `is_group` and `name` are structural (which leaves exist, what they are
#: called) and `consumes` is the flag declaration itself; anything else is a
#: narrowing that has to be argued for, and none has been.
FILTER_MEANINGS: Final[dict[str, str]] = {
    "variadic_operands": "operand arity",
    "takes_input_paths": "operand typing",
    "takes_positional_argument": "operand presence",
    "is_page_addressing": "page addressing",
    "is_mutating": "reachability of the write chokepoint",
}

#: The fields :func:`destination_flag_cases` is licensed to read.
LICENSED_POPULATION_FIELDS: Final[frozenset[str]] = frozenset({"name", "is_group", "consumes"})


def population_fields(population: Callable[..., object]) -> frozenset[str]:
    """Every ``VerbSpec`` attribute *population*'s own source reads.

    Static over the function's source (`ast`, the convention this module and
    `tests/test_derived_dimensions.py` already share) rather than a behavioural
    probe, because the thing under examination is which filters the derivation
    APPLIES -- a property of the code, not of today's answer.
    """
    import inspect

    fields: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(population))):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in ("verb", "v", "leaf"):
                fields.add(node.attr)
    return frozenset(fields)
