"""The ``stamp`` verb (PDF-14).

Typer surface only: flag validation, one call into ``ops/overlay.py``, one
result mapped to an exit code. No PDF logic lives here.

**One verb per file** — see ``cli/cmd_meta.py``'s module docstring for the
mechanism.

**OR-3.** ``stamp`` declares ``--output``/``--in-place`` only — one input,
one output document; no ``--out-dir``/``--name`` (same shape as ``meta
set``/``watermark``).

**R6/B-079.** Mirrors ``cmd_rotate.py:119-127`` exactly on every
``--in-place`` path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.cli.password import ENV_PASSWORD, plan_password
from pdf_toolkit.errors import UsageError
from pdf_toolkit.ops.overlay import DEFAULT_FROM_PAGE, DEFAULT_POSITION, stamp_run
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.confirm import require_confirmation
from pdf_toolkit.safety.paths import classify_operand

__all__ = ["stamp_command"]

VERB = "stamp"

_POSITIONS = ("overlay", "underlay")

_HELP = """Overlay or underlay an EXISTING PDF page across the selected
pages.

Selected through the StructureEngine port, by capability -- never by adapter
name.

SELECTION SEMANTICS. stamp is a SET operation: --pages is normalized to a
sorted, deduplicated set before anything is composited. Default when
--pages is omitted: every page.

--from PATH names the source document; --from-page N (default 1) selects
which of its pages becomes the stamp layer. A multi-page --from with no
--from-page uses page 1, without a warning -- a warning there would be noise
in bulk runs.

--position overlay (the default) draws the stamp ON TOP of the page's own
content; --position underlay draws it BENEATH -- proven by CONTENT-STREAM
ORDER, never by a rendered pixel. The default is the same on `watermark`; an
invisible stamp would be a defect.

--from's own failure modes: a missing path is exit 4; an encrypted --from
that cannot be opened is exit 6 and the message names --from, not the
positional input; a malformed --from is exit 1; a --from-page beyond the
source's own page count is exit 2, naming both numbers.

DESTINATIONS. -O writes one file; --in-place overwrites the input, with a
.bak sidecar first. One of the two is required.
"""


def _reject_missing_sources(sources: list[Path]) -> None:
    for source in sources:
        classify_operand(source)


@global_options(consumes=("--output", "--in-place"))
def stamp_command(
    ctx: typer.Context,
    source: Annotated[Path, operand_argument(metavar="PDF", help="The PDF to stamp.")],
    from_: Annotated[
        Path | None,
        typer.Option(
            "--from",
            help="The PDF whose page becomes the stamp layer. Required.",
            # PDF-26 §D2/E6: `--from` is an INPUT that happens to be spelled as
            # an option, so it drops the framework's readability veto with the
            # twenty-four positional operands rather than with the two write
            # destinations. `ops/overlay.py::_validate_from_path` is the ladder
            # that answers it, and it now carries the unreadable rung.
            readable=False,
        ),
    ] = None,
    from_page: Annotated[
        int,
        typer.Option(
            "--from-page", help=f"1-based page of --from to use. Default {DEFAULT_FROM_PAGE}."
        ),
    ] = DEFAULT_FROM_PAGE,
    pages: Annotated[
        str | None,
        typer.Option("--pages", help="Pages to stamp, as a set (see --help). Default: all."),
    ] = None,
    position: Annotated[
        str,
        typer.Option("--position", help="'overlay' (default) or 'underlay'."),
    ] = DEFAULT_POSITION,
) -> None:
    """Overlay or underlay an existing PDF page across the selected pages."""
    config = get_config(ctx)

    # PDF-37: the GLOBAL slot. `plan_password` never reads anything (D3);
    # `ops/document_password.PasswordResolver` reads it at most once, and
    # only if the source turns out to be encrypted.
    password = plan_password(
        slot="password",
        flag="--password-file",
        value=config.password_file,
        env_names=(ENV_PASSWORD,),
        prompt="Password: ",
        allow_empty=True,
    )

    _reject_missing_sources([source])

    if from_ is None:
        raise UsageError(f"{VERB} requires --from")
    if position not in _POSITIONS:
        raise UsageError(f"--position must be one of {_POSITIONS}: {position!r}")
    if from_page < 1:
        raise UsageError(f"--from-page must be 1 or greater: {from_page!r}")
    if not (config.output is not None or config.in_place):
        raise UsageError(f"{VERB} requires --output or --in-place")

    if config.in_place:
        # Local import: `cli.main` imports this module at load time.
        from pdf_toolkit.cli.main import build_rerun_hint

        require_confirmation(
            config.safety,
            input_count=1,
            in_place=True,
            rerun_hint=build_rerun_hint(),
        )

    result = stamp_run(
        source,
        from_path=from_,
        from_page=from_page,
        pages_spec=pages,
        position=position,
        output=config.output,
        in_place=config.in_place,
        policy=config.safety,
        password=password,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


stamp_command.__doc__ = _HELP
