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
    "CliState",
    "GlobalConfig",
    "current_error_format",
    "get_config",
    "global_options",
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
                "--password",
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


def validate_config(config: GlobalConfig) -> None:
    """Reject invalid flag combinations. Every failure here is exit 2.

    ``--no-backup`` without ``--in-place`` is deliberately a usage error and not
    a safety refusal: it is a parse-time invocation mistake, in the same family
    as any other mutually exclusive pair, and nothing has been attempted yet.
    That rule is owned by ``SafetyPolicy.validate()`` and delegated to below;
    everything else here is about flags the policy does not carry.
    """
    if config.output is not None and config.out_dir is not None:
        raise UsageError("--output and --out-dir are mutually exclusive")

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
    """A password is a *path* or ``-``. A literal password is never accepted."""
    if value == "-":
        return
    if not Path(value).is_file():
        raise UsageError(
            "--password-file takes a path to a file holding the password, or '-' for stdin",
            path=value,
        )


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


def _verb_handler(ctx: typer.Context, values: dict[str, Any]) -> None:
    parent_state = getattr(ctx.parent, "obj", None) if ctx.parent is not None else None
    merged: dict[str, Any] = {}
    for spec in GLOBAL_PARAMS:
        explicit = _was_given_explicitly(ctx, spec.name)
        if explicit or not isinstance(parent_state, CliState):
            merged[spec.name] = values[spec.name]
        else:
            merged[spec.name] = parent_state.raw[spec.name]
    config = _apply(ctx, merged)
    validate_config(config)


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


def global_options(func: Callable[..., Any]) -> Callable[..., Any]:
    """Declare the global block on a verb. Every verb is decorated with this."""
    return _attach(func, _verb_handler)


def get_config(ctx: typer.Context) -> GlobalConfig:
    """The resolved global configuration for the running command."""
    state = ctx.obj
    if isinstance(state, CliState):
        return state.config
    raise RuntimeError("global options were not resolved; is the verb decorated?")
