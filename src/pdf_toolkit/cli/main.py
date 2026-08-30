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
