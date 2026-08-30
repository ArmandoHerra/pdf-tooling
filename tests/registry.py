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
"""

from __future__ import annotations

import ast
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import typer

from pdf_toolkit.cli import common as _common
from pdf_toolkit.cli.main import PROG_NAME, app

__all__ = [
    "INVOCATIONS",
    "OUTPUT_FLAG_INVOCATIONS",
    "REPO_ROOT",
    "Invocation",
    "VerbSpec",
    "console_script",
    "discover_groups",
    "discover_verbs",
    "run_cli",
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
            )
        )

    _walk(group, ())
    return tuple(found)


def discover_groups(root: object | None = None) -> tuple[tuple[str, ...], ...]:
    """Every **non-root** grouping parent's path, e.g. ``("meta",)``.

    Separate from :func:`discover_verbs` on purpose: C4 ("every grouping
    parent" exits 2 on a bogus subcommand) is a plain structural check, not
    one of the ``(reg)`` checks, so it has no business participating in the
    :data:`INVOCATIONS` anti-lapse contract (AC10) that leaf verbs do. No
    grouping parent exists below root at PDF-06 landing time (``meta``
    arrives with ``PDF-14``); this returns ``()`` today and picks the future
    group up automatically the moment it exists.
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
    stdin/stdout posture are observable at all."""
    return subprocess.run(
        [*console_script(), *args],
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
}
