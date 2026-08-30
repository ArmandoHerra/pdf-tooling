"""The canonical global-flag block, and the one place it is defined.

Every verb inherits the global options and none may redefine one with different
semantics. Click does not push group options down into subcommand help, so the
block is declared at *both* levels — root and verb — from this single source of
truth, and the two are reconciled by explicit-wins precedence:

    pdftoolkit --dry-run version   ==   pdftoolkit version --dry-run

A verb-level value is used only when it was actually typed on the command line
(detected through Click's parameter source), otherwise the root value stands.
That is what keeps the two spellings identical instead of merely similar.
"""

from __future__ import annotations

import functools
import inspect
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Final, get_type_hints

import typer

from pdf_toolkit.errors import UsageError
from pdf_toolkit.output import OutputFormat, auto_format
from pdf_toolkit.output.logging import configure_logging
from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = [
    "GLOBAL_OPTIONS",
    "OUTPUT_FLAGS",
    "PASSWORD_FILE_FLAGS",
    "REFUSED_PASSWORD_FLAGS",
    "CliState",
    "GlobalConfig",
    "consumed_output_flags",
    "current_error_format",
    "get_config",
    "global_options",
    "not_a_readable_file",
    "root_global_options",
]

#: The canonical long spellings of the global flag block, in declaration order.
#: Tests iterate this against ``--help`` at root and at every verb.
GLOBAL_OPTIONS: Final[tuple[str, ...]] = (
    "--dry-run",
    "--output-format",
    "--output",
    "--out-dir",
    "--name",
    "--force",
    "--in-place",
    "--no-backup",
    "--yes",
    "--password-file",
    "--quiet",
    "--verbose",
    "--no-color",
    "--threads",
    "--version",
)

#: Default worker cap for multi-file operations.
DEFAULT_THREADS: Final[int] = min(8, os.cpu_count() or 1)

#: OR-3 (`decision.md` §0.5, Design §D12) — the global flags whose *consumption*
#: a verb must declare. NOT the whole :data:`GLOBAL_OPTIONS` block: `--force`,
#: `--no-backup`, `-y`, `--threads`, `--password-file`, `-o/--output-format`,
#: `--dry-run`, `-q`, `-v`, `--no-color` and `--version` are ungoverned by
#: design (PDF-07's spec, Scope > Out) — widening this tuple is a defect, not
#: an improvement. `-O` is `--output`'s short spelling and is governed with it.
OUTPUT_FLAGS: Final[tuple[str, ...]] = ("--output", "--out-dir", "--name", "--in-place")

#: Attribute name the OR-3 declaration is recorded under on a verb module's
#: dict, keyed by that module's own `__name__` -- see :func:`global_options`
#: and :func:`consumed_output_flags`.
_CONSUMES_BY_MODULE: dict[str, tuple[str, ...]] = {}


def _version_callback(value: bool) -> None:
    """Eager ``--version``: print one line and exit, with or without a verb."""
    if not value:
        return
    from pdf_toolkit.cli.cmd_version import version_line

    typer.echo(version_line())
    raise typer.Exit()


@dataclass(frozen=True)
class _ParamSpec:
    """One row of the global block: how it is declared and what it defaults to."""

    name: str
    annotation: Any
    default: Any


#: Ruling **OR-4** (`decision.md` §0.5) + PM ruling **X-114**: no flag in this
#: product takes a password-shaped value. `--password` shipped as an alias of
#: `--password-file`; it is removed, and `--user-password` / `--owner-password`
#: are refused pre-emptively so PDF-13 cannot re-create the same shape on new
#: surface the day it is removed from the old.
#:
#: **Deleting the alias would not have been enough.** With the spelling simply
#: gone, `--password X` falls into Click's unknown-option path, and ledger
#: finding `4772bfd8fc` records that unknown flags on this product bypass the
#: error envelope entirely — so the user would get a generic *"No such
#: option"* carrying none of the three supported paths OR-4 requires the
#: message to name.
#:
#: **Why a hidden BOOLEAN eager option rather than a hidden value-taking one**
#: (verified against Click's own parsing order, not assumed):
#:
#: * A value-taking option given no value fails inside Click's parser with its
#:   own un-enveloped *"requires an argument"* message — the shape OR-4's
#:   message has to cover.
#: * A boolean never binds the value at all, so `--password hunter2` cannot
#:   echo it even by accident: the word is left in the positional stream and
#:   is never looked at. That is the never-echo rule made structural rather
#:   than remembered.
#: * ``is_eager=True`` makes the callback fire during parameter processing,
#:   **before** Click's own "got unexpected extra arguments" check, so the
#:   refusal is identical whether or not the stray word perturbs arity.
#:
#: They are **not** in :data:`GLOBAL_OPTIONS` and ``hidden=True`` keeps them
#: out of every ``--help`` body, so the §4.2 verb-block-vs-root diff test is
#: unperturbed on both sides — that test is the control proving the removal
#: did not deform the shared block.
REFUSED_PASSWORD_FLAGS: Final[tuple[str, ...]] = (
    "--password",
    "--user-password",
    "--owner-password",
)

#: B-068's completeness lever, companion to :data:`REFUSED_PASSWORD_FLAGS`
#: above: every flag in this product that takes a *path to a file holding a
#: password* (never the password itself). Unlike :data:`REFUSED_PASSWORD_
#: FLAGS`, these are real, supported, non-hidden flags that DO appear in
#: rendered ``--help`` — ``--password-file`` is global (declared below,
#: reachable on every verb); ``--owner-password-file`` /
#: ``--user-password-file`` are declared on ``encrypt`` alone
#: (``cmd_encrypt.py``).
#:
#: Every member's shape refusal is proven, by
#: ``tests/test_password_leaks.py``'s B-068 section, to route through
#: :func:`not_a_readable_file` below and never echo the value it was given —
#: that test also asserts this tuple's membership against every verb's
#: *rendered* ``--help`` (the AC18 idiom: an observable-behaviour check, not
#: a source grep) and against its own per-flag coverage map, so a flag
#: landing here without gaining that proof fails the suite rather than
#: shipping quietly.
PASSWORD_FILE_FLAGS: Final[tuple[str, ...]] = (
    "--password-file",
    "--owner-password-file",
    "--user-password-file",
)


def not_a_readable_file(flag: str) -> UsageError:
    """The never-echo error for a flag in :data:`PASSWORD_FILE_FLAGS`.

    ``path=`` is deliberately absent, for the same reason
    :func:`_password_flag_refusal` above gives: at the moment of refusal we
    cannot tell a typo'd path from a literal password, and a rendered
    ``path=`` field would print it either way.

    Defined HERE rather than in ``cli/password.py`` (B-068): that is where
    this exact error was already built for ``--owner-password-file`` /
    ``--user-password-file`` before this fix, and the natural move is to
    have ``--password-file``'s check (below, in THIS module) call it. But
    ``cli/password.py`` imports :mod:`pdf_toolkit.ops.crypto` (for
    ``PasswordSource``), which imports :class:`~pdf_toolkit.safety.atomic.
    AtomicWriter` -- the write chokepoint. ``cli/common.py`` is imported by
    *every* verb's callback module, and ``tests/registry.py``'s
    ``is_mutating`` classification is a **static, transitive** AST-import
    reachability scan for that same name (`ast.walk` sees every import
    statement in a file regardless of nesting, so a deferred/local import
    does not avoid it either) -- so importing ``cli.password`` from
    ``cli.common`` would have made ``AtomicWriter`` reachable from every
    verb, including ``doctor``/``info``/``version``, and reclassified all
    three as mutating (verified against a clean worktree at ``73f6722``: it
    flips exactly those three, and ``doctor``'s own pre-existing
    ``--dry-run`` impurity -- out of B-068's scope -- would have started
    failing ``test_c9`` / ``test_c10`` as a side effect of a password-leak
    fix). ``cli/password.py`` importing THIS module instead carries no such
    risk: ``cli/common.py`` does not import anything that reaches
    ``AtomicWriter``, and the three verbs that already import
    ``cli.password`` (``encrypt``, ``decrypt``, ``permissions``) were
    already classified mutating before this fix.
    """
    return UsageError(
        f"{flag} takes a file path or '-'; the given value is not a readable file. "
        "Refusing to echo it, in case it is the password itself.",
        redacted=True,
    )


def _password_flag_refusal(flag: str) -> UsageError:
    """OR-4's message: name the three supported paths, echo nothing.

    ``path=`` is deliberately absent. At the moment of refusal we cannot know
    whether the value was a literal password or a perfectly valid path, and a
    rendered ``path=`` field would print it either way.
    """
    return UsageError(
        f"{flag} is not a flag: a password is never accepted as a command-line value "
        "(argv is world-readable in /proc and lands in shell history). Use "
        "--password-file PATH (or '-' to read one line from stdin), set "
        "PDF_TOOLKIT_PASSWORD in the environment, or run on a terminal to be prompted.",
        redacted=True,
    )


def _refusing_callback(flag: str) -> Callable[[bool], None]:
    def callback(value: bool) -> None:
        if value:
            raise _password_flag_refusal(flag)

    return callback


def _refused_password_spec(flag: str) -> _ParamSpec:
    return _ParamSpec(
        f"refused{flag.replace('-', '_')}",
        Annotated[
            bool,
            typer.Option(
                flag,
                hidden=True,
                is_eager=True,
                callback=_refusing_callback(flag),
            ),
        ],
        False,
    )


_REFUSED_PASSWORD_PARAMS: Final[tuple[_ParamSpec, ...]] = tuple(
    _refused_password_spec(flag) for flag in REFUSED_PASSWORD_FLAGS
)


GLOBAL_PARAMS: Final[tuple[_ParamSpec, ...]] = (
    _ParamSpec(
        "dry_run",
        Annotated[bool, typer.Option("--dry-run", help="Plan and report; write nothing.")],
        False,
    ),
    _ParamSpec(
        "output_format",
        Annotated[
            OutputFormat | None,
            typer.Option(
                "-o",
                "--output-format",
                help="Output shape. Defaults to table on a TTY and json otherwise.",
                show_default=False,
            ),
        ],
        None,
    ),
    _ParamSpec(
        "output",
        Annotated[
            Path | None,
            typer.Option(
                "-O",
                "--output",
                help="Single output file. Mutually exclusive with --out-dir.",
                show_default=False,
            ),
        ],
        None,
    ),
    _ParamSpec(
        "out_dir",
        Annotated[
            Path | None,
            typer.Option(
                "--out-dir",
                help="Multi-output destination directory.",
                show_default=False,
            ),
        ],
        None,
    ),
    _ParamSpec(
        "name",
        Annotated[
            str | None,
            typer.Option(
                "--name",
                help="Output filename template, e.g. '{stem}-p{page:03}.pdf'.",
                show_default=False,
            ),
        ],
        None,
    ),
    _ParamSpec(
        "force",
        Annotated[
            bool, typer.Option("-f", "--force", help="Permit overwriting an existing output.")
        ],
        False,
    ),
    _ParamSpec(
        "in_place",
        Annotated[
            bool,
            typer.Option("--in-place", help="Mutate the input; writes a .bak sidecar first."),
        ],
        False,
    ),
    _ParamSpec(
        "no_backup",
        Annotated[
            bool,
            typer.Option(
                "--no-backup",
                help="Suppress the --in-place sidecar. Requires --in-place.",
            ),
        ],
        False,
    ),
    _ParamSpec(
        "yes",
        Annotated[
            bool,
            typer.Option(
                "-y",
                "--yes",
                help="Assume yes; required for bulk destructive runs on a non-TTY.",
            ),
        ],
        False,
    ),
    _ParamSpec(
        "password_file",
        Annotated[
            str | None,
            typer.Option(
                "--password-file",
                help="Path to a file holding the password, or '-' to read one line from stdin. "
                "A literal password is never accepted.",
                show_default=False,
            ),
        ],
        None,
    ),
    _ParamSpec(
        "quiet",
        Annotated[bool, typer.Option("-q", "--quiet", help="Report only errors on stderr.")],
        False,
    ),
    _ParamSpec(
        "verbose",
        Annotated[
            int,
            typer.Option(
                "-v",
                "--verbose",
                count=True,
                help="Increase stderr verbosity: -v is INFO, -vv is DEBUG.",
                show_default=False,
            ),
        ],
        0,
    ),
    _ParamSpec(
        "no_color",
        Annotated[
            bool,
            typer.Option("--no-color", help="Disable ANSI styling; NO_COLOR is honoured too."),
        ],
        False,
    ),
    _ParamSpec(
        "threads",
        Annotated[
            int | None,
            typer.Option(
                "--threads",
                help=f"Worker cap for multi-file operations (default {DEFAULT_THREADS}).",
                show_default=False,
            ),
        ],
        None,
    ),
    _ParamSpec(
        "version",
        Annotated[
            bool,
            typer.Option(
                "--version",
                help="Print the tool, Python and engine versions, then exit.",
                is_eager=True,
                callback=_version_callback,
            ),
        ],
        False,
    ),
    *_REFUSED_PASSWORD_PARAMS,
)


@dataclass(frozen=True, slots=True)
class GlobalConfig:
    """The resolved global flags for one invocation."""

    dry_run: bool
    output_format: OutputFormat
    output: Path | None
    out_dir: Path | None
    name: str | None
    force: bool
    in_place: bool
    no_backup: bool
    assume_yes: bool
    password_file: str | None
    quiet: bool
    verbose: int
    no_color: bool
    threads: int
    safety: SafetyPolicy


@dataclass(frozen=True)
class CliState:
    """What the root callback leaves on the context for the verb to build on."""

    raw: dict[str, Any]
    config: GlobalConfig


_error_format: OutputFormat | None = None


def current_error_format() -> OutputFormat:
    """The format an error should be rendered in, resolved as early as possible.

    Falls back to stream auto-detection when a failure happens before the flags
    were resolved, so an error is never rendered in a shape the caller cannot
    parse.
    """
    return _error_format if _error_format is not None else auto_format()


def _set_error_format(fmt: OutputFormat) -> None:
    global _error_format
    _error_format = fmt


def reset_error_format() -> None:
    """Drop the resolved error format. Exists for test isolation."""
    global _error_format
    _error_format = None


def build_config(values: dict[str, Any]) -> GlobalConfig:
    """Turn one raw flag dict into the resolved configuration, defaults applied."""
    raw_format = values["output_format"]
    fmt = OutputFormat(raw_format) if raw_format is not None else auto_format()

    raw_threads = values["threads"]
    threads = DEFAULT_THREADS if raw_threads is None else int(raw_threads)

    no_color = bool(values["no_color"]) or bool(os.environ.get("NO_COLOR"))
    no_backup = bool(values["no_backup"])

    try:
        is_tty = sys.stdin.isatty()
    except (AttributeError, ValueError):  # pragma: no cover - closed/replaced stream
        is_tty = False

    safety = SafetyPolicy(
        dry_run=bool(values["dry_run"]),
        force=bool(values["force"]),
        in_place=bool(values["in_place"]),
        backup=not no_backup,
        assume_yes=bool(values["yes"]),
        is_tty=is_tty,
        threads=threads,
    )
    return GlobalConfig(
        dry_run=safety.dry_run,
        output_format=fmt,
        output=values["output"],
        out_dir=values["out_dir"],
        name=values["name"],
        force=safety.force,
        in_place=safety.in_place,
        no_backup=no_backup,
        assume_yes=safety.assume_yes,
        password_file=values["password_file"],
        quiet=bool(values["quiet"]),
        verbose=int(values["verbose"] or 0),
        no_color=no_color,
        threads=threads,
        safety=safety,
    )


def validate_config(
    config: GlobalConfig,
    *,
    verb: str | None = None,
    consumes: tuple[str, ...] | None = None,
) -> None:
    """Reject invalid flag combinations. Every failure here is exit 2.

    ``--no-backup`` without ``--in-place`` is deliberately a usage error and not
    a safety refusal: it is a parse-time invocation mistake, in the same family
    as any other mutually exclusive pair, and nothing has been attempted yet.
    That rule is owned by ``SafetyPolicy.validate()`` and delegated to below;
    everything else here is about flags the policy does not carry.

    ``verb``/``consumes`` are OR-3's declaration (Design §D12) — ``None`` skips
    the check entirely, which is what the root callback (ungoverned; it is not
    a verb) and direct unit-test construction both want. A real verb always
    passes both, via :func:`global_options`'s ``consumes=`` requirement.

    **Ordering is pinned** (§D12), because two shipped tests depend on it:

    1. ``--output``/``--out-dir`` mutual exclusion — a verb-independent
       contradiction, diagnosed first regardless of what the verb can honour.
    2. The OR-3 consumption check — before every shape check below, so a verb
       that cannot honour ``--name`` at all does not lecture the user about
       template syntax.
    3. ``SafetyPolicy.validate()``, the name-template shape check, the
       password-file shape check, ``--threads``, ``--quiet``/``--verbose`` —
       unchanged, just now reached after 1 and 2.

    All three tiers exit 2, so no exit code changes anywhere — only which
    message is emitted.
    """
    if config.output is not None and config.out_dir is not None:
        raise UsageError("--output and --out-dir are mutually exclusive")

    if consumes is not None:
        _check_output_flag_consumption(config, verb=verb or "this command", consumes=consumes)

    # Delegated, not duplicated: ``SafetyPolicy`` owns this rule, so the CLI and
    # any other construction of a policy cannot drift apart. Still exit 2 —
    # ``BackupWithoutInPlaceError`` is a ``UsageError``.
    config.safety.validate()

    if config.quiet and config.verbose > 0:
        raise UsageError("--quiet and --verbose are mutually exclusive")

    if config.threads < 1:
        raise UsageError("--threads must be 1 or greater")

    if config.name is not None:
        _validate_name_template(config.name)

    if config.password_file is not None:
        _validate_password_file(config.password_file)


#: OR-3: whether each governed flag was actually given, read off the resolved
#: config. A flag "counts as given" when its merged value differs from
#: ``GLOBAL_PARAMS``'s own default -- the same idiom the mutual-exclusion check
#: above already uses for ``--output``/``--out-dir``.
_OUTPUT_FLAG_GIVEN: Final[dict[str, Callable[[GlobalConfig], bool]]] = {
    "--output": lambda config: config.output is not None,
    "--out-dir": lambda config: config.out_dir is not None,
    "--name": lambda config: config.name is not None,
    "--in-place": lambda config: config.in_place is True,
}


def _check_output_flag_consumption(
    config: GlobalConfig, *, verb: str, consumes: tuple[str, ...]
) -> None:
    """OR-3 (`decision.md` §0.5, Design §D12) — the central refusal.

    A global output flag a verb cannot honour is a usage error, exit 2, never
    silently ignored (B-035 / QA fingerprint ``54500b06e5``). One line on
    stderr naming the verb and the long spelling of every offending flag, in
    :data:`OUTPUT_FLAGS` order.
    """
    offending = tuple(
        flag for flag in OUTPUT_FLAGS if flag not in consumes and _OUTPUT_FLAG_GIVEN[flag](config)
    )
    if not offending:
        return
    flags_text = ", ".join(offending)
    if consumes:
        detail = f"{verb} only accepts {', '.join(consumes)} among the output flags"
    else:
        detail = "this verb writes no files"
    raise UsageError(f"{verb} does not accept {flags_text} ({detail})")


def _validate_name_template(template: str) -> None:
    """Shape-validate ``--name``.

    Template *expansion* belongs to the first verb that consumes the template.
    """
    if not template.strip():
        raise UsageError("--name must not be empty")
    separators = {"/", os.sep, os.altsep} - {None, ""}
    if any(separator in template for separator in separators if separator):
        raise UsageError("--name is a filename template and must not contain a path separator")
    if ".." in template:
        raise UsageError("--name must not contain '..'")


def _validate_password_file(value: str) -> None:
    """A password is a *path* or ``-``. A literal password is never accepted.

    Routes through :func:`not_a_readable_file` above (B-068) -- the same
    never-echo constructor ``--owner-password-file`` / ``--user-password-
    file`` already use (via ``cli/password.py``'s own import of it) --
    rather than building its own ``UsageError`` with ``path=value`` here.
    The two were parallel refusal paths for the same class of flag; only one
    of them was hardened, and ``--password-file`` (the shared/global
    spelling, reached from every verb through this shared option layer) was
    the one that leaked.
    """
    if value == "-":
        return
    if not Path(value).is_file():
        raise not_a_readable_file("--password-file")


def _apply(ctx: typer.Context, values: dict[str, Any]) -> GlobalConfig:
    config = build_config(values)
    _set_error_format(config.output_format)
    configure_logging(verbose=config.verbose, quiet=config.quiet, no_color=config.no_color)
    ctx.obj = CliState(raw=dict(values), config=config)
    return config


def _root_handler(ctx: typer.Context, values: dict[str, Any]) -> None:
    config = _apply(ctx, values)
    # A verb re-validates against the merged values, so validating here as well
    # would reject `--no-backup version --in-place`, which is a legal spelling.
    if ctx.invoked_subcommand is None:
        validate_config(config)


#: The Click parameter-source name that means "the user actually typed this".
#: Compared by name rather than by importing the enum: the CLI framework vendors
#: its Click, so there is no importable top-level ``click.core`` to reach into,
#: and a private import would be a hidden coupling to a vendoring decision.
_COMMANDLINE_SOURCE: Final[str] = "COMMANDLINE"


def _was_given_explicitly(ctx: typer.Context, name: str) -> bool:
    source = ctx.get_parameter_source(name)
    return getattr(source, "name", None) == _COMMANDLINE_SOURCE


def _verb_name(ctx: typer.Context) -> str:
    """The invoked verb's own command name, e.g. ``"merge"`` or (PDF-14, the
    first grouping parent) ``"meta set"``.

    Read off the live Click command rather than passed around separately, so
    the OR-3 message always names the verb that was actually typed. Walks
    ``ctx.parent`` up to, but excluding, the ROOT context (whose ``.parent``
    is ``None``) so a subcommand's OWN name is joined with every grouping
    parent above it, in invocation order -- ``meta`` (the group) then
    ``set`` (the leaf) becomes ``"meta set"``. A top-level verb has exactly
    one context between it and the root, so this returns the SAME single
    name it always did (verified: no existing verb's message changes).
    Falls back to a generic label rather than raising -- a message that says
    "this command" is a smaller defect than an unrelated crash inside error
    handling.
    """
    parts: list[str] = []
    # `object`, not `typer.Context`: `.parent`'s own stub type
    # (`typer.models.Context | None`) does not unify with the marker
    # annotation `ctx` itself carries at the call site (the same
    # marker-vs-runtime-Click-Context duck-typing `_attach()`'s own
    # docstring already names above) -- every access below is `getattr`,
    # which needs no narrower type.
    node: object | None = ctx
    while node is not None and getattr(node, "parent", None) is not None:
        command = getattr(node, "command", None)
        name = getattr(command, "name", None)
        if isinstance(name, str):
            parts.append(name)
        node = getattr(node, "parent", None)
    if not parts:
        return "this command"
    return " ".join(reversed(parts))


def _verb_handler(ctx: typer.Context, values: dict[str, Any], *, consumes: tuple[str, ...]) -> None:
    parent_state = getattr(ctx.parent, "obj", None) if ctx.parent is not None else None
    merged: dict[str, Any] = {}
    for spec in GLOBAL_PARAMS:
        explicit = _was_given_explicitly(ctx, spec.name)
        if explicit or not isinstance(parent_state, CliState):
            merged[spec.name] = values[spec.name]
        else:
            merged[spec.name] = parent_state.raw[spec.name]
    config = _apply(ctx, merged)
    validate_config(config, verb=_verb_name(ctx), consumes=consumes)


def _attach(
    func: Callable[..., Any],
    handler: Callable[[typer.Context, dict[str, Any]], None],
) -> Callable[..., Any]:
    """Append the global block to ``func``'s signature and resolve it before the body runs.

    The verb body never sees the global values as parameters; it reads the
    resolved :class:`GlobalConfig` off the context. That keeps a verb's own
    signature about the verb.
    """
    base_signature = inspect.signature(func, eval_str=True)
    hints: dict[str, Any] = dict(get_type_hints(func, include_extras=True))

    added: list[inspect.Parameter] = []
    for spec in GLOBAL_PARAMS:
        if spec.name in base_signature.parameters:
            raise TypeError(
                f"{func.__name__}() declares {spec.name!r}, which the global block already owns"
            )
        added.append(
            inspect.Parameter(
                spec.name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=spec.default,
                annotation=spec.annotation,
            )
        )
        hints[spec.name] = spec.annotation

    new_signature = base_signature.replace(parameters=[*base_signature.parameters.values(), *added])

    @functools.wraps(func)
    def wrapper(**kwargs: Any) -> Any:
        values = {spec.name: kwargs.pop(spec.name, spec.default) for spec in GLOBAL_PARAMS}
        # ``typer.Context`` is an annotation marker: the object the framework
        # actually hands over is its own Click ``Context``, which is a *base*
        # of that marker, not an instance of it. Duck-typing on the one method
        # this layer needs is both correct and independent of that detail.
        ctx = kwargs.get("ctx")
        if ctx is None or not hasattr(ctx, "get_parameter_source"):  # pragma: no cover
            raise TypeError(f"{func.__name__}() must declare a 'ctx: typer.Context' parameter")
        handler(ctx, values)
        return func(**kwargs)

    wrapper.__signature__ = new_signature  # type: ignore[attr-defined]
    wrapper.__annotations__ = hints
    return wrapper


def root_global_options(func: Callable[..., Any]) -> Callable[..., Any]:
    """Declare the global block on the root callback."""
    return _attach(func, _root_handler)


def global_options(
    *, consumes: tuple[str, ...]
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare the global block on a verb, and which output flags it consumes (D12).

    ``consumes`` is **required** and keyword-only. A bare ``@global_options``
    (no call — so the decorated function itself lands where ``consumes`` must
    be) raises ``TypeError`` at import time rather than shipping a verb OR-3
    silently never checks: this function accepts no positional argument at
    all, so Python's own call-binding rejects that shape before a line of this
    module's logic runs (AC26). Every name in ``consumes`` must be one of
    :data:`OUTPUT_FLAGS`; an unknown name raises ``ValueError`` at import
    time too, so a typo is a build failure rather than a silent no-op.
    """
    unknown = [flag for flag in consumes if flag not in OUTPUT_FLAGS]
    if unknown:
        raise ValueError(
            f"global_options(consumes=...) names unknown flag(s) {unknown!r}; "
            f"must be a subset of OUTPUT_FLAGS {OUTPUT_FLAGS!r}"
        )

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        # Keyed by the UNDECORATED function's own module -- exactly the
        # granularity `tests/registry.py::discover_verbs()` already resolves a
        # verb to (`_module_dotted_name`), and each `cli/cmd_*.py` module
        # declares exactly one command, so this can never collide.
        _CONSUMES_BY_MODULE[func.__module__] = consumes

        def handler(ctx: typer.Context, values: dict[str, Any]) -> None:
            _verb_handler(ctx, values, consumes=consumes)

        return _attach(func, handler)

    return decorator


def consumed_output_flags(module: str) -> tuple[str, ...]:
    """The :data:`OUTPUT_FLAGS` the verb defined in *module* declared it consumes.

    Read by ``tests/registry.py`` to build the OR-3 matrix (AC25) and to
    re-parameterize the no-clobber contract check off the real declaration
    instead of a hand-maintained list (AC29). ``()`` for any module that never
    called :func:`global_options` — the same "declares nothing" default a
    verb's own decoration would have recorded, so a caller never has to
    special-case the root callback or an unrelated module.
    """
    return _CONSUMES_BY_MODULE.get(module, ())


def get_config(ctx: typer.Context) -> GlobalConfig:
    """The resolved global configuration for the running command."""
    state = ctx.obj
    if isinstance(state, CliState):
        return state.config
    raise RuntimeError("global options were not resolved; is the verb decorated?")
