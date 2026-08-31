"""The ``rotate`` verb (PDF-08).

Typer surface only: flag validation, one call into ``ops/pages.py``, one result
mapped to an exit code. No PDF logic lives here — in particular **no rotation
arithmetic**: relative-vs-``--absolute`` and the ``% 360`` normalization live
in ``ops/pages.normalize_rotation``, so they are testable without an engine and
cannot drift between the CLI's help text and what actually gets written.

**One verb per file** — see ``cmd_extract.py``'s module docstring for the
mechanism (`cli/common.py:768`'s ``_CONSUMES_BY_MODULE`` is keyed by module).

**OR-3 (`decision.md` §0.5).** `rotate` declares all four output flags
(``--output``, ``--out-dir``, ``--name``, ``--in-place``); every one is
honoured, so its OR-3 arm can never refuse. Arity and "a destination is
required" are checked here, because OR-3's one-dimensional declaration cannot
express either.

**``--angle`` is validated in the body, not by a Click choice type**, and that
ordering is deliberate: the OR-3 consumption check runs inside
``global_options``' handler, *before* this callback. A ``required=True`` option
would make Click's own missing-parameter error fire at parse time and win over
OR-3's message, so ``tests/test_cli_contract.py``'s C14 refused arm would see
"Missing option '--angle'" instead of a message naming the offending output
flag. Both are exit 2; only one of them tells the user what OR-3 refused.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options
from pdf_toolkit.errors import UsageError
from pdf_toolkit.ops.pages import ROTATION_ANGLES, reject_missing_sources, rotate_run
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.confirm import require_confirmation

__all__ = ["rotate_command"]

VERB = "rotate"

#: Rendered from `ops/pages.ROTATION_ANGLES` rather than typed twice, so the
#: refusal message can never name a set the code does not accept.
_ANGLE_SET = "{" + ", ".join(str(angle) for angle in ROTATION_ANGLES) + "}"

_HELP = f"""Rotate selected pages by a multiple of 90 degrees.

SELECTION SEMANTICS. rotate is a SET operation: --pages is normalized to a
sorted, deduplicated set before anything is rotated, so a page named twice is
rotated ONCE. --pages '1,1' with --angle 90 leaves page 1 at 90, not 180, and
--pages '5-1' is identical to --pages '1-5'. extract and reorder are the
ordered verbs.

ANGLES. --angle accepts exactly {_ANGLE_SET}; anything else is exit 2, before
the document is opened. --angle is required.

RELATIVE BY DEFAULT. --angle 90 ADDS 90 degrees to a page's existing rotation;
--absolute SETS it, ignoring the current value. Either way the written value
is normalized into 0/90/180/270, so a page at 270 rotated by 90 becomes 0
(never 360) and --absolute --angle -90 becomes 270 (never -90).

rotate changes a page's /Rotate entry and nothing else. Page boxes are not
touched: rotation is metadata, not geometry. Pages you do not select are left
exactly as they were, including leaving /Rotate absent where it was absent.

DESTINATIONS. -O writes one file (multiple inputs sharing one -O is an arity
error, exit 2 -- use --out-dir instead). --out-dir writes one file per input,
named by --name (default '{{stem}}.{{ext}}'). --in-place overwrites each input,
with a .bak sidecar first (--no-backup suppresses the sidecar, explicitly).
Exactly one of --output/--out-dir/--in-place is required.

A bulk --in-place run (more than one input) refuses on a non-terminal without
-y, and prints the exact command to re-run.
"""


@global_options(consumes=("--output", "--out-dir", "--name", "--in-place"))
def rotate_command(
    ctx: typer.Context,
    sources: Annotated[
        list[Path],
        typer.Argument(metavar="PDF...", help="One or more PDFs to rotate pages in."),
    ],
    pages: Annotated[
        str | None,
        typer.Option("--pages", help="Pages to rotate, as a set (see --help)."),
    ] = None,
    angle: Annotated[
        int | None,
        typer.Option("--angle", help=f"Rotation in degrees; one of {_ANGLE_SET}."),
    ] = None,
    absolute: Annotated[
        bool,
        typer.Option("--absolute", help="Set the rotation instead of adding to it."),
    ] = False,
) -> None:
    """Rotate selected pages, relative by default."""
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
    if angle is None:
        raise UsageError(f"{VERB} requires --angle; accepted values are {_ANGLE_SET}")
    if angle not in ROTATION_ANGLES:
        raise UsageError(f"--angle {angle} is not one of {_ANGLE_SET}")
    if not (config.output is not None or config.out_dir is not None or config.in_place):
        raise UsageError(f"{VERB} requires --output, --out-dir, or --in-place")

    if config.in_place:
        # Local import: `cli.main` imports this module at load time.
        from pdf_toolkit.cli.main import build_rerun_hint

        require_confirmation(
            config.safety,
            input_count=len(sources),
            in_place=True,
            rerun_hint=build_rerun_hint(),
        )

    result = rotate_run(
        sources,
        pages_spec=pages,
        angle=angle,
        absolute=absolute,
        output=config.output,
        out_dir=config.out_dir,
        name_template=config.name,
        in_place=config.in_place,
        policy=config.safety,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


rotate_command.__doc__ = _HELP
