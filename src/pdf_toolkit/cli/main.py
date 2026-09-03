"""The Typer root: the global flag block, the verb registry, and the one error handler.

Two structural rules live here.

**No engine library is imported at module scope**, directly or transitively.
``--help`` and ``--version`` must not pay for pdfium, qpdf or reportlab, and a
test asserts that importing this module leaves every engine absent from
``sys.modules``.

**There is exactly one ``except PdfToolkitError``.** Every deliberate error in
the tool is one of those, so the mapping from error to rendered output to exit
code exists in one place. Anything else reaching the top is a bug: it prints a
traceback and exits 1, which is a signal, not a UX.

**``main()`` is the terminal seam** (PDF-25). Five ledger rows were failures a
user could reach that never passed through ``emit_error()`` at all, because
something other than that one handler terminated the process: Click's own
parser (``standalone_mode=True`` printed ``Usage:`` to stderr and exited 2
before anything of ours ran), and this module's root callback (help + exit 0 on
a flags-but-no-verb line). The envelope has to sit where it can see a failure
that happened *before any of this product's code executed*, and ``main()`` is
the only such place. See :func:`main` for the hazard that placement brings
with it.
"""

from __future__ import annotations

import shlex
import sys
from collections.abc import Sequence
from typing import Final, NoReturn

import typer

from pdf_toolkit.cli import (
    cmd_compose,
    cmd_compress,
    cmd_create,
    cmd_decrypt,
    cmd_delete,
    cmd_doctor,
    cmd_encrypt,
    cmd_extract,
    cmd_info,
    cmd_linearize,
    cmd_merge,
    cmd_meta,
    cmd_meta_get,
    cmd_meta_set,
    cmd_ocr,
    cmd_office,
    cmd_permissions,
    cmd_rasterize,
    cmd_reorder,
    cmd_repair,
    cmd_rotate,
    cmd_split,
    cmd_stamp,
    cmd_tables,
    cmd_text,
    cmd_version,
    cmd_watermark,
)
from pdf_toolkit.cli.common import (
    GLOBAL_FLAG_SPELLINGS,
    REFUSED_PASSWORD_FLAGS,
    current_error_format,
    global_options,
    password_flag_refusal,
    root_global_options,
)
from pdf_toolkit.cli.exit_codes import OK, USAGE
from pdf_toolkit.errors import FailureError, PdfToolkitError, UsageError
from pdf_toolkit.output import OutputFormat, emit_error

#: Pinned so that ``pdftoolkit``, ``pdf-toolkit`` and ``python -m pdf_toolkit``
#: print byte-identical help instead of three different usage lines.
PROG_NAME = "pdftoolkit"

HELP = """One safe command-line tool for the common PDF chores.

Inputs are never mutated unless you ask for --in-place, every write is atomic
and non-clobbering, and --dry-run writes nothing anywhere. Structured output
(-o json / -o ndjson) and the exit-code table are a stability contract.
"""

app = typer.Typer(
    name=PROG_NAME,
    help=HELP,
    add_completion=False,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
)


@app.callback(invoke_without_command=True)
@root_global_options
def root(ctx: typer.Context) -> None:
    """Root callback: resolve the global flags, or print help when given no verb."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(OK)


app.command(name="version", help=cmd_version.version_command.__doc__)(cmd_version.version_command)
app.command(name="doctor", help=cmd_doctor.doctor_command.__doc__)(cmd_doctor.doctor_command)
app.command(name="info", help=cmd_info.info_command.__doc__)(cmd_info.info_command)
app.command(name="merge", help=cmd_merge.merge_command.__doc__)(cmd_merge.merge_command)
app.command(name="split", help=cmd_split.split_command.__doc__)(cmd_split.split_command)
app.command(name="rasterize", help=cmd_rasterize.rasterize_command.__doc__)(
    cmd_rasterize.rasterize_command
)
app.command(name="compose", help=cmd_compose.compose_command.__doc__)(cmd_compose.compose_command)
app.command(name="create", help=cmd_create.create_command.__doc__)(cmd_create.create_command)
app.command(name="text", help=cmd_text.text_command.__doc__)(cmd_text.text_command)
app.command(name="tables", help=cmd_tables.tables_command.__doc__)(cmd_tables.tables_command)
app.command(name="compress", help=cmd_compress.compress_command.__doc__)(
    cmd_compress.compress_command
)
app.command(name="repair", help=cmd_repair.repair_command.__doc__)(cmd_repair.repair_command)
app.command(name="linearize", help=cmd_linearize.linearize_command.__doc__)(
    cmd_linearize.linearize_command
)
app.command(name="encrypt", help=cmd_encrypt.encrypt_command.__doc__)(cmd_encrypt.encrypt_command)
app.command(name="decrypt", help=cmd_decrypt.decrypt_command.__doc__)(cmd_decrypt.decrypt_command)
app.command(name="permissions", help=cmd_permissions.permissions_command.__doc__)(
    cmd_permissions.permissions_command
)
# PDF-08 -- the four page-addressed structure verbs. One `cli/cmd_*.py` module
# each, because `cli/common.py`'s OR-3 declaration is keyed by module.
app.command(name="extract", help=cmd_extract.extract_command.__doc__)(cmd_extract.extract_command)
app.command(name="delete", help=cmd_delete.delete_command.__doc__)(cmd_delete.delete_command)
app.command(name="rotate", help=cmd_rotate.rotate_command.__doc__)(cmd_rotate.rotate_command)
app.command(name="reorder", help=cmd_reorder.reorder_command.__doc__)(cmd_reorder.reorder_command)

# PDF-14. `meta` is the CLI's only grouping parent -- `cli/cmd_meta.py` holds
# only the sub-Typer, `get`/`set` each live in their own module (D8.1).
# `watermark`/`stamp` are ordinary top-level verbs.
app.add_typer(cmd_meta.meta_app)
cmd_meta.meta_app.command(name="get", help=cmd_meta_get.meta_get_command.__doc__)(
    cmd_meta_get.meta_get_command
)
cmd_meta.meta_app.command(name="set", help=cmd_meta_set.meta_set_command.__doc__)(
    cmd_meta_set.meta_set_command
)
app.command(name="watermark", help=cmd_watermark.watermark_command.__doc__)(
    cmd_watermark.watermark_command
)
app.command(name="stamp", help=cmd_stamp.stamp_command.__doc__)(cmd_stamp.stamp_command)

# PDF-15 -- the two system-binary verbs.
app.command(name="ocr", help=cmd_ocr.ocr_command.__doc__)(cmd_ocr.ocr_command)
app.command(name="convert", help=cmd_office.convert_command.__doc__)(cmd_office.convert_command)


def build_rerun_hint(argv: Sequence[str] | None = None) -> str:
    """The exact command to re-run, with ``-y`` appended.

    The confirmation gate refuses a bulk destructive run on a non-terminal, and
    the only thing that makes such a refusal *useful* is handing back a line the
    operator can paste. Building it here rather than inside ``safety/`` is the
    layering, not a convenience: reading ``sys.argv`` is a property of being the
    process entry point, and ``safety/`` stays a pure function of its arguments
    so it can be tested and embedded without a command line existing at all.

    ``shlex.join`` rather than ``" ".join`` because a path with a space in it is
    the ordinary case, not the exotic one, and a hint that breaks when pasted is
    worse than no hint.
    """
    return shlex.join(list(sys.argv if argv is None else argv)) + " -y"


# --------------------------------------------------------------------------- #
# PDF-25 -- routing Click's own parser errors through `emit_error()`.
#
# `import click` FAILS in this environment: the CLI framework vendors Click
# privately and there is no top-level distribution to import. Adding one is
# forbidden by the dependency freeze, and reaching into the framework's own
# private vendored copy is a hidden coupling to a vendoring decision that
# `cli/common.py:_COMMANDLINE_SOURCE` already refused once on the record. So the
# classification below is DUCK-TYPED, exactly as that refusal was: a Click
# exception is one carrying
# `ClickException` among the `__name__`s of its MRO, with the two attributes
# this module actually consumes. No import, no dependency, and it survives a
# framework version bump that re-vendors or un-vendors Click.
# --------------------------------------------------------------------------- #

#: The MRO name that identifies a Click-raised, user-facing parser error.
_CLICK_EXCEPTION: Final[str] = "ClickException"

#: The MRO name of Click's own "the user interrupted this" signal. Under
#: ``standalone_mode=True`` Click caught it, printed ``Aborted!`` and exited 1;
#: under ``standalone_mode=False`` it propagates, so this module reproduces
#: that behaviour verbatim rather than letting a Ctrl-D at the confirmation
#: prompt start printing a traceback.
_ABORT: Final[str] = "Abort"

#: What :func:`_argument_placeholder` prints for a value it cannot name.
_VALUE_PLACEHOLDER: Final[str] = "VALUE"


def _mro_names(error: BaseException) -> frozenset[str]:
    return frozenset(cls.__name__ for cls in type(error).__mro__)


def _is_click_exception(error: BaseException) -> bool:
    return (
        _CLICK_EXCEPTION in _mro_names(error)
        and callable(getattr(error, "format_message", None))
        and isinstance(getattr(error, "exit_code", None), int)
    )


def _root_params(context: object) -> tuple[object, ...]:
    """The ROOT command's parameters, reached from the failing context.

    Duck-typed the whole way down, and read off the live tree rather than
    rebuilt: the objects already exist by the time a parser error is raised.
    """
    find_root = getattr(context, "find_root", None)
    root_context = find_root() if callable(find_root) else context
    command = getattr(root_context, "command", None)
    params = getattr(command, "params", ())
    return tuple(params)


def _argument_placeholder(spelling: str, params: tuple[object, ...]) -> str:
    """An example ARGUMENT for *spelling*, or ``""`` when it takes none.

    Derived from the live parameter, never typed. For a choice-typed flag the
    example is the machine-readable member when the flag declares one -- the
    whole point of a group-position refusal is that the caller asked for a
    machine shape at a position that cannot honour it, so an example that hands
    back a HUMAN shape would answer a question nobody asked.
    """
    for param in params:
        if spelling not in tuple(getattr(param, "opts", ()) or ()):
            continue
        if getattr(param, "is_flag", False) or getattr(param, "count", False):
            return ""
        param_type = getattr(param, "type", None)
        choices = tuple(getattr(param_type, "choices", ()) or ())
        if choices:
            machine = OutputFormat.JSON.value
            return f" {machine}" if machine in choices else f" {choices[0]}"
        name = getattr(param_type, "name", "")
        if name == "path":
            return " PATH"
        if name in ("int", "integer"):
            return " N"
        return f" {_VALUE_PLACEHOLDER}"
    return ""


def _group_position_refusal(
    error: BaseException, spelling: str, canonical: str
) -> UsageError | None:
    """`a472acde7a` -- the global block, refused at a GROUPING PARENT.

    All fifteen members of the block exit 2 at ``meta`` with **zero bytes on
    stdout**, which is the whole of the defect: the exit code is correct
    (`PLAN.md` §5.6 rules that a grouping parent is exit 2, and this spec does
    not touch it), the empty stdout is not.

    The fix is deliberately NOT to attach ``@global_options`` to the group.
    That would pollute ``_CONSUMES_BY_MODULE``, enrol a group in an OR-3 matrix
    that classifies leaf verbs, and flip ``meta -o json`` from 2 to 0 --
    overturning both ``cli/cmd_meta.py``'s own ruling and `PLAN.md` §5.6 in a
    single edit. What changes here is the MESSAGE, which now hands back the two
    command lines that do work instead of Click's bare ``No such option: -o``.
    """
    context = getattr(error, "ctx", None)
    command = getattr(context, "command", None)
    subcommands = getattr(command, "commands", None)
    if subcommands is None:
        return None
    command_path = getattr(context, "command_path", None)
    if not isinstance(command_path, str) or not command_path:
        return None
    program, _, group_path = command_path.partition(" ")
    if not group_path:
        return None
    example_subcommand = next(iter(sorted(subcommands)), "<subcommand>")
    argument = _argument_placeholder(spelling, _root_params(context))
    typed = f"{spelling}{argument}"
    return UsageError(
        f"{canonical} is a global flag and '{command_path}' is a command group, which does "
        f"not take the global block: the block is declared at the root and on every verb, "
        f"never on a group. Two positions work -- "
        f"'{program} {typed} {group_path} {example_subcommand} ...' (before the group) or "
        f"'{program} {group_path} {example_subcommand} ... {typed}' (after the subcommand)."
    )


def _envelope_for(error: BaseException) -> tuple[PdfToolkitError, str | None]:
    """One Click parser error, as this product's own error plus a help pointer.

    Precedence, and every tier is load-bearing:

    1. **The OR-4 pointer** for a refused password spelling, because
       ``README.md`` promises a usage error *naming the three supported paths*
       and Click's own ``does not take a value`` names none of them
       (`7fc5a169f6`). Recognition is on the FLAG NAME; the value is never
       read, never bound and never rendered.
    2. **The group-position refusal**, which names the two working positions.
    3. **Click's own ``format_message()``**, carried verbatim. Rewriting Click's
       diagnostics wholesale is a separate, later item; what this spec changes
       is the STREAM and the SHAPE, never the wording of a message that was
       already correct.

    The pointer returned alongside is Click's ``Try '<command> --help' for
    help.``, reproduced because routing through ``emit_error()`` would
    otherwise replace a 120-byte diagnostic with a 38-byte one. It is rendered
    on stderr under ``-o table`` only -- under a structured shape stdout must
    carry the envelope and nothing else.
    """
    context = getattr(error, "ctx", None)
    command_path = getattr(context, "command_path", None)
    pointer = (
        f"Try '{command_path} --help' for help."
        if isinstance(command_path, str) and command_path
        else None
    )

    spelling = getattr(error, "option_name", None)
    canonical = GLOBAL_FLAG_SPELLINGS.get(spelling) if isinstance(spelling, str) else None

    if canonical is not None and canonical in REFUSED_PASSWORD_FLAGS:
        return password_flag_refusal(canonical), pointer

    if canonical is not None and isinstance(spelling, str):
        refusal = _group_position_refusal(error, spelling, canonical)
        if refusal is not None:
            return refusal, pointer

    message = str(error.format_message())  # type: ignore[attr-defined]
    exit_code = getattr(error, "exit_code", USAGE)
    if exit_code == USAGE:
        return UsageError(message), pointer
    return FailureError(message), pointer


def _terminate(error: PdfToolkitError, pointer: str | None) -> NoReturn:
    fmt = current_error_format()
    emit_error(error, fmt)
    if pointer is not None and fmt is OutputFormat.TABLE:
        print(pointer, file=sys.stderr)
    raise SystemExit(error.exit_code) from None


def main() -> None:
    """Console-script entry point for ``pdftoolkit``, ``pdf-toolkit`` and ``python -m``.

    ``standalone_mode=False`` is what makes this function a seam at all: with
    the default, Click catches its own exceptions INSIDE this call and exits
    before anything can reach the handler below.

    ⚠ **The hazard that comes with it, and the reason the last line is what it
    is.** Twenty-eight ``cli/cmd_*.py`` modules signal their exit code with
    ``raise typer.Exit(code)``. Under ``standalone_mode=False`` the framework
    converts that into the RETURN VALUE of ``app(...)``: it does not raise and
    it does not exit. A ``main()`` ending in ``raise SystemExit(OK)`` would
    therefore turn such an exit into **0**, silently -- a wrong answer carrying
    a success exit code, which would make ``cmd --dry-run && cmd``, OR-7, every
    contract row that asserts an exit code and every CI gate pass on failure.
    **The return value IS the exit code.**

    Measured, because the blast radius is worth stating precisely rather than
    generously: this product *raises* most non-zero exits (every
    ``PdfToolkitError`` -- usage, safety, OR-3/OR-4, and every single-input
    verb failure) and *returns* the rest. Today the returned ones are ``info``
    (1/4/6, the batch reporter that accumulates per-item outcomes instead of
    raising) and ``doctor`` (3). `tests/test_usage_envelope.py`'s exit-code
    matrix pins the whole range, and its planted-defect control asserts
    exactly which codes ride the return value -- so a later verb moving onto
    that path is a red rather than a widening.
    """
    try:
        returned = app(prog_name=PROG_NAME, standalone_mode=False)
    except PdfToolkitError as error:
        # FIRST, so the existing handler keeps its precedence unchanged: our
        # own OR-3/OR-4/safety messages must never be replaced by Click's.
        _terminate(error, None)
    except Exception as error:
        if _is_click_exception(error):
            envelope, pointer = _envelope_for(error)
            _terminate(envelope, pointer)
        if _ABORT in _mro_names(error):
            print("Aborted!", file=sys.stderr)
            raise SystemExit(1) from None
        # A genuine bug keeps printing its traceback and exiting 1. Converting
        # one into a tidy usage error is exactly what this module's own header
        # forbids: it is a signal, not a UX.
        raise
    raise SystemExit(returned if isinstance(returned, int) else OK)


__all__ = ["PROG_NAME", "app", "build_rerun_hint", "global_options", "main", "root"]
