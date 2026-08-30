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
"""

from __future__ import annotations

import shlex
import sys
from collections.abc import Sequence

import typer

from pdf_toolkit.cli import cmd_doctor, cmd_info, cmd_version
from pdf_toolkit.cli.common import current_error_format, global_options, root_global_options
from pdf_toolkit.cli.exit_codes import OK
from pdf_toolkit.errors import PdfToolkitError
from pdf_toolkit.output import emit_error

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


def main() -> None:
    """Console-script entry point for ``pdftoolkit``, ``pdf-toolkit`` and ``python -m``."""
    try:
        app(prog_name=PROG_NAME)
    except PdfToolkitError as error:
        emit_error(error, current_error_format())
        raise SystemExit(error.exit_code) from None


__all__ = ["PROG_NAME", "app", "build_rerun_hint", "global_options", "main", "root"]
