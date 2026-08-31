"""The ``compose`` verb — images into one PDF (Design §1-§5, §11-§12).

Typer surface only: flag validation, one call into ``ops/compose.py``, one
result mapped to an exit code. No image or PDF logic lives here.

**OR-3 (Design §11).** ``compose`` declares it consumes the single-output flag
and nothing else, so the other three global output flags exit 2 **for free**
from the shared option layer in ``cli/common.py``. This module contains no check
for any of them, on purpose (AC22): a duplicate check here would be a second
refusal path that could later disagree with the shared one — and a second path
is a defect even while it happens to agree. For the same reason, the prose that
names a flag in a refusal lives in ``ops/compose.py``, not here.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options
from pdf_toolkit.errors import NoInputError, UsageError
from pdf_toolkit.ops.compose import (
    DEFAULT_COMPOSE_MARGIN,
    compose_document,
    parse_length,
    parse_page_size,
    resolve_single_output,
)
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.confirm import require_confirmation
from pdf_toolkit.safety.paths import target_exists

__all__ = ["FitMode", "compose_command"]

VERB = "compose"


class FitMode(StrEnum):
    """``--fit`` — how an image meets a fixed page size (Design §4)."""

    CONTAIN = "contain"
    COVER = "cover"
    STRETCH = "stretch"


_HELP = """Build a PDF from image files, one page per image.

A JPEG is embedded byte-for-byte: a JPEG file already IS a DCT-compressed
stream and PDF stores exactly that, so the page carries the original scan
with no decode and no re-encode. The stored stream is the input file's own
bytes, and 'compose' never JPEG-encodes anything.

Baseline JPEG -- greyscale, RGB and CMYK alike -- takes that path; CMYK
carries the Adobe inversion array, so the colours are right and the bytes
survive. A PROGRESSIVE JPEG is re-encoded as a Flate stream instead, because
the passthrough filter is specified against the baseline profile and
progressive support in real viewers is inconsistent -- and you are told, per
file, on stderr and in -o json. PNG, TIFF, WebP, BMP and GIF are decoded and
stored as Flate samples; that is normal and not warned about. Every item
reports which path it took, so nothing is ever silently degraded.

Pages come out in the order the operands appear on the command line, one page
per operand. Duplicates are allowed and produce duplicate pages. There is no
sorting and no globbing -- globbing is the shell's job, so 'compose
./scans/*.jpg' is the spelling; a directory operand is refused.

--page-size a4|letter|from-image|WxH (default a4). WxH is literal with an
optional unit (pt, mm, cm, in; pt when omitted): '612x792', '210x297mm'.
'from-image' sizes EVERY page to its OWN image, so a run of differently-sized
scans yields differently-sized pages -- never normalised to the first, the
largest, or a bounding box. It is the mode that returns the source geometry.

--fit contain|cover|stretch (default contain) applies only to a fixed page
size. contain scales to fit inside the content box and centres; cover scales
to fill it, centres, and removes the overflow with a PDF clip path -- pixels
are never cropped, so the byte-for-byte guarantee survives; stretch fills the
content box exactly and does not preserve the aspect ratio. Under
--page-size from-image the flag is inert and saying so is a warning, not
silence.

--margin N or N<unit> (default 0 for compose; 'create' defaults to 54pt,
because a document margin and an image margin are different decisions).

--dpi FLOAT overrides the density used to convert pixels to points. Without
it the image's own embedded density is used when it has one, and 72 dpi
otherwise; every item reports which of the three rules fired.

Needs the ComposeEngine, which is a hard install dependency: if it does not
resolve, that is a broken install (exit 3). Run 'pdftoolkit doctor'.
"""


@global_options(consumes=("--output",))
def compose_command(
    ctx: typer.Context,
    sources: Annotated[
        list[Path],
        typer.Argument(metavar="IMAGE...", help="One or more images, in page order."),
    ],
    page_size: Annotated[
        str,
        typer.Option("--page-size", help="a4, letter, from-image, or WxH with an optional unit."),
    ] = "a4",
    fit: Annotated[
        FitMode,
        typer.Option("--fit", help="How an image meets a fixed page size."),
    ] = FitMode.CONTAIN,
    margin: Annotated[
        str,
        typer.Option("--margin", help="Page margin: N or N<unit> (pt, mm, cm, in)."),
    ] = DEFAULT_COMPOSE_MARGIN,
    dpi: Annotated[
        float | None,
        typer.Option(
            "--dpi",
            help="Pixels-to-points density. Default: the image's own, else 72.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Build a PDF from image files, one page per image."""
    config = get_config(ctx)

    # PLAN.md §10's own contract (mechanized generically by the CLI-contract
    # harness's C5): every verb with a path-taking argument exits 4 on a
    # nonexistent input, unconditionally -- checked here, first, so it wins
    # over any other usage error. `ops/compose.py::inspect_image` repeats the
    # check for every OTHER call path into that function; the duplication is
    # deliberate defense in depth, the same posture `AtomicWriter`'s own
    # no-clobber re-check takes.
    for source in sources:
        if not source.exists():
            raise NoInputError("no such file", path=str(source))
        if source.is_dir():
            raise UsageError(
                "expected an image file, not a directory; globbing is the "
                "shell's job, so pass the files themselves (e.g. './scans/*.jpg')",
                path=str(source),
            )

    if dpi is not None and dpi <= 0:
        raise UsageError("--dpi must be greater than 0")

    page = parse_page_size(page_size)
    margin_pt = parse_length(margin, flag="--margin")
    output = resolve_single_output(sources, config.output, verb=VERB)

    if config.force and target_exists(output):
        # Local import: `cli.main` imports this module at load time to
        # register the command, so a module-level import here would cycle.
        from pdf_toolkit.cli.main import build_rerun_hint

        require_confirmation(
            config.safety,
            input_count=len(sources),
            clobbered=(str(output),),
            rerun_hint=build_rerun_hint(),
        )

    result = compose_document(
        sources,
        output=output,
        page=page,
        fit=fit.value,
        margin_pt=margin_pt,
        dpi=dpi,
        policy=config.safety,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


compose_command.__doc__ = _HELP
