"""The ``watermark`` verb (PDF-14).

Typer surface only: flag validation, one call into ``ops/overlay.py``, one
result mapped to an exit code. No PDF logic lives here.

**One verb per file** — see ``cli/cmd_meta.py``'s module docstring for the
mechanism.

**OR-3.** ``watermark`` declares ``--output``/``--in-place`` only — one
input, one output document; no ``--out-dir``/``--name`` (same shape as
``meta set``/``stamp``).

**R6/B-079.** Mirrors ``cmd_rotate.py:119-127`` exactly on every
``--in-place`` path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.errors import UsageError
from pdf_toolkit.ops.overlay import (
    DEFAULT_COLOR,
    DEFAULT_FONT_SIZE,
    DEFAULT_OPACITY,
    DEFAULT_POSITION,
    DEFAULT_ROTATE_DEG,
    watermark_run,
)
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.confirm import require_confirmation
from pdf_toolkit.safety.paths import classify_operand

__all__ = ["parse_color", "watermark_command"]

VERB = "watermark"

_POSITIONS = ("overlay", "underlay")
_DEFAULT_COLOR_TEXT = ",".join(f"{c:g}" for c in DEFAULT_COLOR)

_HELP = f"""Overlay or underlay a generated text layer across the selected
pages.

Selected through the ComposeEngine port (the text layer) AND the
StructureEngine port (the compositing), by capability -- never by adapter
name.

SELECTION SEMANTICS. watermark is a SET operation: --pages is normalized to
a sorted, deduplicated set before anything is composited. Default when
--pages is omitted: every page.

--position overlay (the default) draws the layer ON TOP of the page's own
content; --position underlay draws it BENEATH. The default is the same on
`stamp`; an invisible watermark would be a defect, so `overlay` wins.

--opacity is 0.0-1.0 (default {DEFAULT_OPACITY:g}); --rotate is degrees about
the page centre (default {DEFAULT_ROTATE_DEG:g}); --font-size is points
(default {DEFAULT_FONT_SIZE:g}); --color is "r,g,b", each 0.0-1.0 (default
"{_DEFAULT_COLOR_TEXT}").

ROTATED PAGES. A page with its own /Rotate entry receives the layer in
UNROTATED page space, so the watermark rotates together with the page's
content when displayed -- correct, documented behaviour, not a defect.

PRESERVATION. The original page count and every page's original extractable
text survive; the watermark's own text is ADDED, never a replacement.

DESTINATIONS. -O writes one file; --in-place overwrites the input, with a
.bak sidecar first. One of the two is required.
"""


def parse_color(value: str) -> tuple[float, float, float]:
    """``"r,g,b"``, each ``0.0``-``1.0``. Exit 2 on anything else."""
    parts = value.split(",")
    if len(parts) != 3:
        raise UsageError(f'--color must be "r,g,b" (three comma-separated floats): {value!r}')
    try:
        red, green, blue = (float(part) for part in parts)
    except ValueError as error:
        raise UsageError(f"--color must be three floats: {value!r}") from error
    for channel, name in ((red, "r"), (green, "g"), (blue, "b")):
        if not (0.0 <= channel <= 1.0):
            raise UsageError(f"--color's {name!r} channel must be within 0.0-1.0: {value!r}")
    return (red, green, blue)


def _reject_missing_sources(sources: list[Path]) -> None:
    for source in sources:
        classify_operand(source)


@global_options(consumes=("--output", "--in-place"))
def watermark_command(
    ctx: typer.Context,
    source: Annotated[Path, operand_argument(metavar="PDF", help="The PDF to watermark.")],
    text: Annotated[
        str | None, typer.Option("--text", help="The watermark text. Required.")
    ] = None,
    pages: Annotated[
        str | None,
        typer.Option("--pages", help="Pages to watermark, as a set (see --help). Default: all."),
    ] = None,
    position: Annotated[
        str,
        typer.Option("--position", help="'overlay' (default) or 'underlay'."),
    ] = DEFAULT_POSITION,
    opacity: Annotated[
        float, typer.Option("--opacity", help=f"0.0-1.0. Default {DEFAULT_OPACITY:g}.")
    ] = DEFAULT_OPACITY,
    rotate: Annotated[
        float,
        typer.Option(
            "--rotate", help=f"Degrees about the page centre. Default {DEFAULT_ROTATE_DEG:g}."
        ),
    ] = DEFAULT_ROTATE_DEG,
    font_size: Annotated[
        float, typer.Option("--font-size", help=f"Points. Default {DEFAULT_FONT_SIZE:g}.")
    ] = DEFAULT_FONT_SIZE,
    color: Annotated[
        str,
        typer.Option("--color", help=f'"r,g,b", each 0.0-1.0. Default "{_DEFAULT_COLOR_TEXT}".'),
    ] = _DEFAULT_COLOR_TEXT,
) -> None:
    """Overlay or underlay a generated text layer across the selected pages."""
    config = get_config(ctx)
    _reject_missing_sources([source])

    if text is None:
        raise UsageError(f"{VERB} requires --text")
    if position not in _POSITIONS:
        raise UsageError(f"--position must be one of {_POSITIONS}: {position!r}")
    if not (0.0 <= opacity <= 1.0):
        raise UsageError(f"--opacity must be within 0.0-1.0: {opacity!r}")
    if not (config.output is not None or config.in_place):
        raise UsageError(f"{VERB} requires --output or --in-place")

    parsed_color = parse_color(color)

    if config.in_place:
        # Local import: `cli.main` imports this module at load time.
        from pdf_toolkit.cli.main import build_rerun_hint

        require_confirmation(
            config.safety,
            input_count=1,
            in_place=True,
            rerun_hint=build_rerun_hint(),
        )

    result = watermark_run(
        source,
        text=text,
        pages_spec=pages,
        position=position,
        font_size=font_size,
        color=parsed_color,
        opacity=opacity,
        rotate_deg=rotate,
        output=config.output,
        in_place=config.in_place,
        policy=config.safety,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


watermark_command.__doc__ = _HELP
