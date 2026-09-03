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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Final, get_args, get_type_hints

import typer

from pdf_toolkit.errors import UsageError
from pdf_toolkit.output import OutputFormat, auto_format
from pdf_toolkit.output.logging import configure_logging
from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = [
    "GLOBAL_FLAG_SPELLINGS",
    "GLOBAL_OPTIONS",
    "OUTPUT_FLAGS",
    "PASSWORD_FILE_FLAGS",
    "REFUSED_PASSWORD_FLAGS",
    "SAFETY_FLAGS",
    "UNGOVERNED_FLAGS",
    "CliState",
    "GlobalConfig",
    "consumed_output_flags",
    "current_error_format",
    "format_from_argv",
    "get_config",
    "given_global_flags",
    "global_options",
    "not_a_readable_file",
    "password_flag_refusal",
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

# --------------------------------------------------------------------------- #
# The governance partition of :data:`GLOBAL_OPTIONS` (PDF-24 Design §D2).
#
# Every member of the block lands in EXACTLY ONE of the three classes below,
# and `tests/test_cli_spine.py`'s partition control asserts pairwise
# disjointness plus union == set(GLOBAL_OPTIONS). Adding a sixteenth flag
# without classifying it is a RED TEST, not a silently inert flag.
#
# This replaced a prose comment that named eleven flags in English and could
# not fail. `996f9eb6bc` is what that cost: `--force` and `-y` were advertised,
# accepted and silently ignored at exit 0 on all five verbs that write nothing
# — *inert by omission* rather than *inert by design, disclosed*.
# --------------------------------------------------------------------------- #

#: OR-3 (`decision.md` §0.5, Design §D12) — the global flags whose *consumption*
#: a verb must declare, refused per-verb by :func:`_check_output_flag_consumption`.
#: Unchanged by PDF-24: same four members, same order, same message text — three
#: shipped criteria and the `54500b06e5` regression cells depend on all three.
#: `-O` is `--output`'s short spelling and is governed with it.
OUTPUT_FLAGS: Final[tuple[str, ...]] = ("--output", "--out-dir", "--name", "--in-place")

#: B-115 / `996f9eb6bc` — governed CENTRALLY rather than per-verb: refused on any
#: verb that consumes no output flag at all (``consumes == ()``), because a verb
#: that writes nothing has no output to overwrite and no destructive bulk run to
#: confirm. Derived from a fact the product already publishes — the
#: ``consumes == ()`` branch of :func:`_check_output_flag_consumption` already
#: emits the literal detail *"this verb writes no files"* — so no verb gains a
#: second hand-maintained declaration.
SAFETY_FLAGS: Final[tuple[str, ...]] = ("--force", "--yes")

#: Universal by design, each with its reason recorded AS DATA rather than in a
#: comment: greppable, testable, and quotable. A member with a blank reason
#: fails the partition control — *inert by design, disclosed* is the safe state;
#: *inert by omission* is the one this product's headline defect class is made of.
UNGOVERNED_FLAGS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "--dry-run": (
            "every verb has a plan phase, and OR-7 makes the preview meaningful even on a "
            "verb that writes nothing (dry == real)"
        ),
        "--output-format": "selects the shape of a payload every verb emits",
        "--no-backup": (
            "governed elsewhere, and more strictly: SafetyPolicy.validate() refuses it "
            "without --in-place UNIVERSALLY, so it is never silently inert on any verb"
        ),
        "--password-file": "any verb may meet an encrypted input, including the report-only ones",
        "--quiet": "a property of the stderr stream, which every verb has",
        "--verbose": "a property of the stderr stream, which every verb has",
        "--no-color": "a property of the stderr stream, which every verb has",
        "--threads": "validated universally (< 1 exits 2) and consumed opportunistically",
        "--version": "eager; it exits before a verb body runs at all",
    }
)

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
    :func:`password_flag_refusal` below gives: at the moment of refusal we
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


def password_flag_refusal(flag: str) -> UsageError:
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
            raise password_flag_refusal(flag)

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


# --------------------------------------------------------------------------- #
# The spelling index, DERIVED from :data:`GLOBAL_PARAMS` (PDF-25 Design §D5/§D9).
#
# Every consumer below needs to answer one question -- "is this token the user
# typed a member of the global block, and if so which flag is it?" -- about a
# command line the parser has ALREADY REJECTED, where no bound parameter
# exists to read the answer off. Deriving the index from the same tuple Typer
# renders and binds is what keeps that answer from becoming a second,
# hand-typed roster beside the live one (`e138934a60`'s shape).
# --------------------------------------------------------------------------- #


def _declared_spellings(spec: _ParamSpec) -> tuple[str, ...]:
    """Every command-line spelling one :class:`_ParamSpec` declares, in order.

    ``typer.Option``'s FIRST positional parameter is ``default``, so a
    single-spelling declaration lands its spelling there and leaves
    ``param_decls`` empty (``--dry-run`` reads ``default='--dry-run',
    param_decls=()``; ``-o/--output-format`` reads ``default='-o',
    param_decls=('--output-format',)``). Both shapes are handled.

    Deliberately NOT defensive about the annotation's shape. Every member of
    :data:`GLOBAL_PARAMS` is an ``Annotated[T, typer.Option(...)]`` by
    construction, and if that ever stops being true this raises at IMPORT time
    rather than returning an empty tuple -- which would leave
    :data:`GLOBAL_FLAG_SPELLINGS` empty and silently make every classification
    branch that consumes it unreachable. A build failure is the right answer;
    an inert index is the shape this product's headline defect class is made of.
    """
    info = get_args(spec.annotation)[1]
    spellings: list[str] = []
    default = getattr(info, "default", None)
    if isinstance(default, str) and default.startswith("-"):
        spellings.append(default)
    spellings.extend(getattr(info, "param_decls", ()) or ())
    return tuple(spellings)


def _canonical_spelling(spellings: tuple[str, ...]) -> str:
    """The long form, which every member of the block declares. See above for
    why a missing one raises at import time instead of being skipped."""
    return next(one for one in spellings if one.startswith("--"))


def _build_spelling_index() -> Mapping[str, str]:
    index: dict[str, str] = {}
    for spec in GLOBAL_PARAMS:
        spellings = _declared_spellings(spec)
        canonical = _canonical_spelling(spellings)
        for spelling in spellings:
            index[spelling] = canonical
    return MappingProxyType(index)


#: Every spelling of every global-block flag -- short and long, the OR-4 hidden
#: three included -- mapped to its canonical long spelling. Read on the ERROR
#: path only, to classify a token Click has already refused.
GLOBAL_FLAG_SPELLINGS: Final[Mapping[str, str]] = _build_spelling_index()

#: The canonical long spelling of each global param, keyed by the Python
#: parameter name Click reports through ``get_parameter_source``.
_LONG_BY_PARAM: Final[Mapping[str, str]] = MappingProxyType(
    {spec.name: _canonical_spelling(_declared_spellings(spec)) for spec in GLOBAL_PARAMS}
)

#: ``--output-format``'s spellings, derived rather than typed, so
#: :func:`format_from_argv` below recognises exactly what the block declares.
_OUTPUT_FORMAT_SPELLINGS: Final[tuple[str, ...]] = tuple(
    spelling
    for spelling, canonical in GLOBAL_FLAG_SPELLINGS.items()
    if canonical == "--output-format"
)


def format_from_argv(argv: Sequence[str]) -> OutputFormat | None:
    """The output shape named on a command line that was never parsed.

    Consulted by :func:`current_error_format` below **only** when the flags
    were never resolved -- which is exactly the case Click's parser errors
    create, and the only way the shape can be recovered at GROUP position,
    where ``-o`` does not exist as a parameter at all (Design §D5).

    Five fences, because a reader of raw ``argv`` is precisely the kind of
    thing that becomes a second defect:

    1. It is consulted only when ``_error_format is None``. A successful parse
       is never affected by it.
    2. It **never influences an exit code.** It selects a rendering stream and
       nothing else; the worst case is an error rendered as JSON where a human
       wanted a table.
    3. It returns ``None`` for anything it does not recognise, ``-o bogus``
       included. It never guesses.
    4. It **never echoes a value.** The token is compared against the
       :class:`~pdf_toolkit.output.OutputFormat` members and discarded; it is
       not stored, not logged and not rendered. B-068's never-echo discipline
       is preserved by construction rather than by review.
    5. It honours ``--``.

    Because it reads ``argv`` rather than the parse tree it behaves identically
    at root, group and leaf position, and that single property is what lets a
    group-position failure be rendered in the shape the caller asked for
    without attaching the global block to the group (`a472acde7a`, §D6).

    The LAST occurrence wins, matching Click's own scalar-option semantics.
    """
    args = list(argv)
    token: str | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            break
        for spelling in _OUTPUT_FORMAT_SPELLINGS:
            if arg == spelling:
                if index + 1 < len(args):
                    token = args[index + 1]
                index += 1
                break
            prefix = f"{spelling}="
            if arg.startswith(prefix):
                token = arg[len(prefix) :]
                break
        index += 1
    if token is None:
        return None
    try:
        return OutputFormat(token)
    except ValueError:
        return None


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

    Three tiers, narrowest first (PDF-25 Design §D5):

    1. **The resolved format**, when the flags were parsed. Unchanged, and it
       still wins over everything below it, so no successful invocation's
       behaviour depends on the two tiers that follow.
    2. **The shape named on the raw command line**, when they were not. Click's
       parser errors, and the group position, both terminate before ``_apply``
       ever runs -- so before this tier existed, an explicit ``-o json`` on a
       TTY silently fell through to ``table``, and at group position ``-o`` was
       never parsed at all under any circumstance.
    3. **Stream auto-detection**, so an error is never rendered in a shape the
       caller cannot parse.
    """
    if _error_format is not None:
        return _error_format
    sniffed = format_from_argv(sys.argv[1:])
    if sniffed is not None:
        return sniffed
    return auto_format()


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
    2a. B-115 / `996f9eb6bc` — the :data:`SAFETY_FLAGS` check, in the SAME
        tier as 2 and immediately after it, so an invocation naming both an
        output flag and a safety flag still reports the OUTPUT flag first and
        the `54500b06e5` regression cells keep their verbatim message.
    2b. The B-076 ``--in-place``-vs-output-target conflict check — a
        DIFFERENT dimension from 2 (a conflict BETWEEN two flags a verb
        legitimately declares consuming, not an undeclared flag), so it runs
        only once 2 has already confirmed every given flag is declared.
    3. ``SafetyPolicy.validate()``, the name-template shape check, the
       password-file shape check, ``--threads``, ``--quiet``/``--verbose`` —
       unchanged, just now reached after 1, 2, 2a and 2b.

    All tiers exit 2, so no exit code changes anywhere — only which message
    is emitted.
    """
    if config.output is not None and config.out_dir is not None:
        raise UsageError("--output and --out-dir are mutually exclusive")

    if consumes is not None:
        _check_output_flag_consumption(config, verb=verb or "this command", consumes=consumes)
        _check_safety_flag_consumption(config, verb=verb or "this command", consumes=consumes)
        _check_in_place_output_conflict(config, verb=verb or "this command", consumes=consumes)

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


#: B-115 / `996f9eb6bc`: whether each :data:`SAFETY_FLAGS` member was actually
#: given, read off the resolved config -- the same "differs from the
#: ``GLOBAL_PARAMS`` default" idiom :data:`_OUTPUT_FLAG_GIVEN` above uses, so
#: BOTH spellings of each flag (`-f`/`--force`, `-y`/`--yes`) are caught by
#: value rather than by re-parsing argv for a spelling.
_SAFETY_FLAG_GIVEN: Final[dict[str, Callable[[GlobalConfig], bool]]] = {
    "--force": lambda config: config.force is True,
    "--yes": lambda config: config.assume_yes is True,
}


def _check_safety_flag_consumption(
    config: GlobalConfig, *, verb: str, consumes: tuple[str, ...]
) -> None:
    """B-115 / `996f9eb6bc` — the central refusal for :data:`SAFETY_FLAGS`.

    OR-3's rationale covers these two verbatim: *a global flag a verb cannot
    honour is a usage error, exit 2, never silently ignored.* ``--force``
    means *permit overwriting an existing output*; ``version`` produces no
    output to overwrite. ``-y`` is the flag that lets a **bulk destructive
    run proceed on a non-TTY** (:func:`require_confirmation`'s own gate), and
    a user who learns it is harmless on ``info`` has learned the single most
    expensive thing this CLI can teach.

    **The population is DERIVED, not declared.** The condition is exactly
    ``consumes == ()`` — the same classification
    :func:`_check_output_flag_consumption` already publishes in user-visible
    text as *"this verb writes no files"*. A second required keyword on
    :func:`global_options` would have meant twenty-six edits, twenty-six
    chances to get it wrong, and a second hand-maintained per-verb fact —
    reproducing the shape the partition above exists to remove. A sixth
    ``consumes=()`` verb inherits this refusal with zero author action.

    Exit 2, in the tier :func:`_check_output_flag_consumption` already
    occupies and immediately after it, so an invocation naming both an output
    flag and a safety flag still reports the output flag first (AC11's
    verbatim `54500b06e5` message is unperturbed). Because the tier is reached
    during flag resolution, **before** any plan is built, OR-7's
    ``dry == real == 2`` is structural rather than incidental.
    """
    if consumes:
        return
    offending = tuple(flag for flag in SAFETY_FLAGS if _SAFETY_FLAG_GIVEN[flag](config))
    if not offending:
        return
    flags_text = ", ".join(offending)
    raise UsageError(f"{verb} does not accept {flags_text} (this verb writes no files)")


#: B-076 -- the three of :data:`OUTPUT_FLAGS` that name an actual destination
#: (as opposed to `--in-place`, which names none). A verb declaring BOTH
#: `--in-place` and at least one of these three has a real conflict to
#: adjudicate; a verb declaring only one side never reaches this check at
#: all (see :func:`_check_in_place_output_conflict`'s own docstring).
_DESTINATION_FLAGS: Final[tuple[str, ...]] = ("--output", "--out-dir", "--name")


def _check_in_place_output_conflict(
    config: GlobalConfig, *, verb: str, consumes: tuple[str, ...]
) -> None:
    """B-076 -- ONE central conflict check, never a per-verb one.

    Every one of the eleven verbs that declares `--in-place` alongside
    `--output`/`--out-dir`/`--name` resolves the pair the same
    one-dimensional way at the ``ops/`` layer: ``if in_place: ... elif
    output/out_dir: ...`` (``ops/optimize.py:241,452``,
    ``ops/crypto.py:258``, ``ops/pages.py:286``, ``ops/metadata.py:238``,
    ``ops/overlay.py:167``). Given both flags, `--in-place` silently wins:
    the input is mutated, the named destination is never written, and the
    run exits 0. :func:`_check_output_flag_consumption` above cannot see
    this — its declaration is one-dimensional (verb -> flag SET), and both
    flags sit inside every one of those eleven verbs' declared sets, so the
    matrix reads the pair as honoured. This is a conflict BETWEEN two
    declared flags, a dimension that check has no vocabulary for.

    Fires only when the verb declares BOTH sides of the conflict. A verb
    that does not consume `--in-place` at all, or consumes none of
    `--output`/`--out-dir`/`--name`, cannot reach here with an offending
    flag given -- :func:`_check_output_flag_consumption` above already
    refused the undeclared flag by name, so this never doubles up on that
    message.

    Exit 2 (`PLAN.md` §5.6 lists mutually exclusive flags under USAGE; the
    `--no-backup`-requires-`--in-place` precedent at `SafetyPolicy.validate`
    is exit 2 too), naming every conflicting flag.
    """
    if "--in-place" not in consumes or not config.in_place:
        return
    conflicting = tuple(
        flag for flag in _DESTINATION_FLAGS if flag in consumes and _OUTPUT_FLAG_GIVEN[flag](config)
    )
    if not conflicting:
        return
    flags_text = ", ".join(conflicting)
    raise UsageError(
        f"{verb}: --in-place is mutually exclusive with {flags_text} "
        "(--in-place would mutate the input and the destination would never be written)"
    )


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
    # ONLY an explicitly given `-o` pins the error format (PDF-25 §D5). The
    # root callback runs BEFORE a verb's own arguments are parsed, so pinning
    # the auto-detected fallback here made `_error_format` non-None the moment
    # the root callback ran -- and a verb-level `-o table` that Click then
    # refused to parse (an unknown flag beside it, say) was rendered in the
    # AUTO shape rather than the requested one, silently. Left unset, the
    # fallback is recomputed identically by `current_error_format()`'s third
    # tier, so nothing about a successful run changes.
    if values.get("output_format") is not None:
        _set_error_format(config.output_format)
    configure_logging(verbose=config.verbose, quiet=config.quiet, no_color=config.no_color)
    ctx.obj = CliState(raw=dict(values), config=config)
    return config


def given_global_flags(ctx: typer.Context) -> tuple[str, ...]:
    """The canonical long spelling of every global flag actually TYPED here.

    Derived from :data:`GLOBAL_PARAMS` through Click's own parameter source,
    the same signal :func:`_was_given_explicitly` already uses for
    explicit-wins precedence -- so a sixteenth flag joins this answer with zero
    author action, and a flag left at its default never appears in it.
    """
    return tuple(
        _LONG_BY_PARAM[spec.name] for spec in GLOBAL_PARAMS if _was_given_explicitly(ctx, spec.name)
    )


def _no_command_given(ctx: typer.Context, flags: tuple[str, ...]) -> UsageError:
    """`76ece64648` -- global flags with no command is an INCOMPLETE invocation.

    The rule is stated in terms of **invocation completeness**, never of output
    shape (Design §D7). ``pdftoolkit -o json`` printed 3754 bytes of human help
    to stdout and exited **0**, so a machine consumer reading stdout learned
    neither that it had asked for nothing nor that it had got nothing --
    `README.md`'s own promise, broken at the one position where the promise is
    easiest to reach by accident.

    A shape-dependent exit code (0 for ``-o table``, 2 for ``-o json``) would
    satisfy the row's title too, and is refused: ``-o`` is documented as a
    rendering choice, and an exit code that turns on it is a new surprise.

    ``pdftoolkit`` with NO arguments at all keeps exit 0 and human help --
    the universal convention, and no machine consumer invokes it expecting
    data. That behaviour is preserved and newly pinned.

    The prog name is read off the live context rather than imported from
    ``cli/main.py`` (which imports THIS module).
    """
    program = getattr(ctx, "info_name", None) or "pdftoolkit"
    named = ", ".join(flags)
    return UsageError(
        f"no command given: {named} was passed with no command, which is an incomplete "
        f"invocation. Run '{program} --help' for the list of commands."
    )


def _root_handler(ctx: typer.Context, values: dict[str, Any]) -> None:
    config = _apply(ctx, values)
    # A verb re-validates against the merged values, so validating here as well
    # would reject `--no-backup version --in-place`, which is a legal spelling.
    if ctx.invoked_subcommand is None:
        # COMPLETENESS BEFORE CONSISTENCY, and the ordering is the point. An
        # invocation that named no command cannot be validated *as a
        # configuration for a command*: `pdftoolkit --no-backup` would
        # otherwise be diagnosed as "--no-backup requires --in-place" when the
        # thing actually missing is the verb. Both tiers are exit 2, so no exit
        # code turns on this ordering -- only which message is emitted.
        flags = given_global_flags(ctx)
        if flags:
            raise _no_command_given(ctx, flags)
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
