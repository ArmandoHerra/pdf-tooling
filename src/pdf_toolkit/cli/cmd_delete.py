"""The ``delete`` verb (PDF-08).

Typer surface only: flag validation, one call into ``ops/pages.py``, one result
mapped to an exit code. No PDF logic lives here, and no engine library is
imported at module scope (`PLAN.md` §12 R-13).

**One verb per file** — see ``cmd_extract.py``'s module docstring for the
mechanism (`cli/common.py:768`'s ``_CONSUMES_BY_MODULE`` is keyed by module, so
a second verb here would silently overwrite this one's OR-3 declaration).

**OR-3 (`decision.md` §0.5).** `delete` declares all four output flags it
consumes (``--output``, ``--out-dir``, ``--name``, ``--in-place``) on its
decorator line and nowhere else — it legitimately honours every one of them,
so its OR-3 arm can never refuse. It is byte-for-byte the shape `compress`
declares at ``cmd_compress.py:128``. Everything else is refused, exit 2, once,
by the shared option layer; this module contains no check for any output
flag's *consumption*. What it DOES check is arity (``-O`` with more than one
input) and that a destination was given at all — neither of which OR-3's
one-dimensional verb -> flag-set declaration can express.

**The non-TTY posture is wired here (`PLAN.md` §5.3, §D6).** A bulk
``--in-place`` run — more than one input, mutating them — refuses on a
non-terminal without ``-y``, through ``safety/confirm.py``'s shared gate, with
the exact re-run command. `merge` and `compose` are the landed precedent for
calling it from the cmd layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options
from pdf_toolkit.errors import UsageError
from pdf_toolkit.ops.pages import delete_run, reject_missing_sources
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.confirm import require_confirmation

__all__ = ["delete_command"]

VERB = "delete"

_HELP = """Write everything EXCEPT the selected pages.

SELECTION SEMANTICS. delete is a SET operation: --pages is normalized to a
sorted, deduplicated set before any page is removed, so --pages '1,1,3' and
--pages '1,3' remove exactly the same pages and --pages '5-1' is identical to
--pages '1-5'. Order is meaningless here -- the survivors always come out in
ascending original order. extract and reorder are the ordered verbs.

even and odd are 1-based (--pages even on a ten-page document removes
2,4,6,8,10 and leaves 1,3,5,7,9).

ZERO-PAGE REFUSAL. A selection resolving to the whole document -- --pages all,
or any spec covering every page -- is exit 5. delete does not produce a
zero-page PDF and does not silently succeed; nothing is written, and under
--in-place no .bak is created and the input is left byte-identical. An
empty-but-valid selection (--pages 'all,!all') is the other case and is exit
4: valid invocation, nothing to act on.

DESTINATIONS. -O writes one file (multiple inputs sharing one -O is an arity
error, exit 2 -- use --out-dir instead). --out-dir writes one file per input,
named by --name (default '{stem}.{ext}'). --in-place overwrites each input,
with a .bak sidecar first (--no-backup suppresses the sidecar, explicitly).
Exactly one of --output/--out-dir/--in-place is required.

A bulk --in-place run (more than one input) refuses on a non-terminal without
-y, and prints the exact command to re-run.
"""


@global_options(consumes=("--output", "--out-dir", "--name", "--in-place"))
def delete_command(
    ctx: typer.Context,
    sources: Annotated[
        list[Path],
        typer.Argument(metavar="PDF...", help="One or more PDFs to delete pages from."),
    ],
    pages: Annotated[
        str | None,
        typer.Option("--pages", help="Pages to remove, as a set (see --help)."),
    ] = None,
) -> None:
    """Write everything except the selected pages."""
    config = get_config(ctx)

    # Exits 4 on a nonexistent input, unconditionally and first (`PLAN.md` §10).
    reject_missing_sources(sources)

    if config.output is not None and len(sources) > 1:
        raise UsageError(
            f"{VERB} of {len(sources)} inputs cannot share one -O/--output target; "
            "pass --out-dir instead"
        )
    if pages is None:
        raise UsageError(f"{VERB} requires --pages")
    if not (config.output is not None or config.out_dir is not None or config.in_place):
        raise UsageError(f"{VERB} requires --output, --out-dir, or --in-place")

    if config.in_place:
        # Local import: `cli.main` imports this module at load time to register
        # the command, so a module-level import here would cycle.
        from pdf_toolkit.cli.main import build_rerun_hint

        require_confirmation(
            config.safety,
            input_count=len(sources),
            in_place=True,
            rerun_hint=build_rerun_hint(),
        )

    result = delete_run(
        sources,
        pages_spec=pages,
        output=config.output,
        out_dir=config.out_dir,
        name_template=config.name,
        in_place=config.in_place,
        policy=config.safety,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


delete_command.__doc__ = _HELP
