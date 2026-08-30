"""The ``merge`` verb — concatenate PDFs (Design §D1-D3).

Typer surface only: flag validation, one call into ``ops/merge.py``, one
result mapped to an exit code. No PDF logic lives here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options
from pdf_toolkit.errors import UsageError
from pdf_toolkit.ops.merge import merge_documents, resolve_merge_inputs
from pdf_toolkit.ops.pagerange import GRAMMAR_HELP
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.confirm import require_confirmation
from pdf_toolkit.safety.paths import target_exists

__all__ = ["BookmarksMode", "merge_command"]

VERB = "merge"


class BookmarksMode(StrEnum):
    """``--bookmarks`` — the three outline policies (Design §D3)."""

    PER_FILE = "per-file"
    PRESERVE = "preserve"
    NONE = "none"


_HELP = f"""Concatenate PDFs into one file.

Per-input page selection is 'path:range', e.g. 'a.pdf:1-3'. With no ':range'
an input contributes all of its pages, in order. -O/--output is required;
--out-dir is exit 2 (merge produces exactly one file). One or more inputs
are accepted; a listed path may repeat, contributing its pages again.

{GRAMMAR_HELP}

THE COLON PROBLEM
------------------
A path may legitimately contain a colon (a Windows drive prefix, or a POSIX
filename with a colon in it). The separator is the LAST colon in the
argument, and the split is taken only when the text after it is non-empty
and parses as a page-range expression above -- otherwise the whole argument
is read as the path. A file genuinely named 'a:1-3' is addressed as
'a:1-3:all': the last colon is now the real separator, so the escape
degrades gracefully and the path survives intact.

--bookmarks per-file|preserve|none (default: per-file)
  per-file  one top-level outline entry per input argument, titled with that
            input's filename stem, pointing at the first page it contributed.
  preserve  each source's own top-level outline entries, remapped to the
            merged page numbering; an entry whose page was not selected is
            dropped, never retargeted to a neighbouring page.
  none      the output has no outline at all.

Fails closed: every input is opened and every selection resolved before
anything is written, so a failure on any input aborts the run and writes
nothing -- a partially merged document is a wrong document that looks
right. --fail-fast is consequently a no-op for merge.
"""


@global_options(consumes=("--output",))
def merge_command(
    ctx: typer.Context,
    inputs: Annotated[
        list[str],
        typer.Argument(
            metavar="INPUT...",
            help="One or more 'path' or 'path:range' operands, in argv order.",
        ),
    ],
    bookmarks: Annotated[
        BookmarksMode,
        typer.Option("--bookmarks", help="Outline policy applied to the merged output."),
    ] = BookmarksMode.PER_FILE,
) -> None:
    """Concatenate PDFs into one file, with per-input page selection."""
    config = get_config(ctx)
    if config.output is None:
        raise UsageError("merge requires -O/--output")

    merge_inputs = resolve_merge_inputs(tuple(inputs))

    if not config.dry_run and config.force and target_exists(config.output):
        # Local import: `cli.main` imports this module at load time to
        # register the command, so a module-level import here would cycle.
        from pdf_toolkit.cli.main import build_rerun_hint

        require_confirmation(
            config.safety,
            input_count=len(merge_inputs),
            clobbered=(str(config.output),),
            rerun_hint=build_rerun_hint(),
        )

    result = merge_documents(
        merge_inputs,
        output=config.output,
        bookmarks=bookmarks.value,
        policy=config.safety,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


merge_command.__doc__ = _HELP
