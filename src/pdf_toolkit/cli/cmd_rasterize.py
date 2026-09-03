"""The ``rasterize`` verb — PDF pages to images (Design §D3-D6, D10-D12).

Typer surface only: flag validation, one call into ``ops/raster.py``, one
result mapped to an exit code. No PDF or image logic lives here.

**OR-3 (Design §D10).** ``rasterize`` declares ``consumes=("--out-dir",
"--name")`` and nothing else. ``-O/--output`` and ``--in-place`` therefore
exit 2 **for free**, from the shared option layer in ``cli/common.py`` — this
module contains no check for either flag, on purpose (AC23): a duplicate
check here would be a second path that could later disagree with the shared
one.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.errors import UsageError
from pdf_toolkit.ops.pagerange import GRAMMAR_HELP
from pdf_toolkit.ops.raster import rasterize_document
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.paths import classify_operand

__all__ = ["RasterFormat", "rasterize_command"]

VERB = "rasterize"

#: Design §D3 rule 2 — `--quality` has no effect on a lossless format.
_LOSSLESS_FORMATS: Final[frozenset[str]] = frozenset({"png", "tiff"})

#: Design §D3 — the default DPI when neither `--dpi` nor `--width` is given.
_DEFAULT_DPI: Final[float] = 150.0


class RasterFormat(StrEnum):
    """``--format`` — the four output encodings (Design §D3)."""

    PNG = "png"
    JPEG = "jpeg"
    TIFF = "tiff"
    WEBP = "webp"


_HELP = f"""Render PDF pages to images, one file per page.

Rendering resolves the RasterEngine port; run 'pdftoolkit doctor' to see
which engine satisfied it. pypdfium2 alone -- no other renderer, not even
as a fallback. If a page
cannot be rendered, that page is a failed item and the run exits 1 -- never
a silent fallback to another engine.

--pages defaults to every page. The selection is a SET (PLAN.md §4.3's
set-semantics verbs): '--pages 3,1,1' normalizes to the sorted, deduplicated
pages 1 and 3 -- order and duplicates are not preserved.

{GRAMMAR_HELP}

--dpi FLOAT (default 150) and --width INT are mutually exclusive; --width
implies the page's own aspect ratio for height. --format
{{png,jpeg,tiff,webp}} (default png) is authoritative over any output
extension. --quality INT (1-100, default 85) applies only to jpeg/webp;
passing it with png or tiff exits 2. --grayscale renders single-channel
output for png, tiff and jpeg. --format webp is the one exception: WebP's
bitstream has no single-channel pixel mode, so --grayscale --format webp
writes grey-valued RGB (rendered without colour information, three equal
channels) rather than one channel.

--out-dir is the destination directory (created if absent, unless
--dry-run); defaults to '.' when omitted. --name templates each output
filename with {{stem}}, {{page}}, {{page:04}}, {{index}} and {{ext}}
('{{range}}' is not meaningful for a per-page verb and is refused). Default
template: '{{stem}}-{{page:04}}.{{ext}}'.

--threads N caps per-page render parallelism (default: min(8, CPU count)).
--threads 1 forces deterministic sequential rendering and is the switch to
reproduce a parallel failure -- --threads 1 and --threads 8 render
byte-identical files in the same order (PLAN.md §12 R-08).

Teardown is stated per platform. On any POSIX platform, SIGTERM, SIGINT or
SIGHUP sent to this command alone tears the render pool down through one
routine: no further page is written and no worker outlives it. SIGKILL to
this command cannot be handled by it at all; the workers are still reaped
on Linux under the 'fork' and 'spawn' worker start methods, where each asks
the kernel for PR_SET_PDEATHSIG at start-up. That is a Linux-only facility,
and it does not cover the 'forkserver' start method Python 3.14 makes the
Linux default -- a forkserver worker's own parent is the forkserver, not
this command. So on macOS, and on Python 3.14 for Linux, a SIGKILLed parent
can leave its workers running: send SIGTERM instead.
"""


@global_options(consumes=("--out-dir", "--name"))
def rasterize_command(
    ctx: typer.Context,
    sources: Annotated[
        list[Path],
        operand_argument(metavar="PDF...", help="One or more PDFs to rasterize."),
    ],
    pages: Annotated[
        str | None,
        typer.Option("--pages", help="Page selection (a set). Default: every page."),
    ] = None,
    dpi: Annotated[
        float | None,
        typer.Option("--dpi", help="Render scale in dots per inch.", show_default=False),
    ] = None,
    width: Annotated[
        int | None,
        typer.Option(
            "--width",
            help="Target pixel width; height follows the page's aspect ratio.",
            show_default=False,
        ),
    ] = None,
    image_format: Annotated[
        RasterFormat,
        typer.Option("--format", help="Output encoding."),
    ] = RasterFormat.PNG,
    quality: Annotated[
        int | None,
        typer.Option(
            "--quality",
            help="1-100. Lossy formats only (jpeg, webp).",
            show_default=False,
        ),
    ] = None,
    grayscale: Annotated[
        bool,
        typer.Option("--grayscale", help="Single-channel output."),
    ] = False,
) -> None:
    """Render PDF pages to PNG/JPEG/TIFF/WEBP images, one file per page."""
    config = get_config(ctx)

    # PLAN.md §10's own contract (mechanized generically by the CLI-contract
    # harness's C5): every verb with a path-taking argument exits 4 on a
    # nonexistent input, unconditionally -- checked here, first, so it wins
    # over any other usage error (the same ordering split.py uses).
    # `ops/raster.py::rasterize_document` repeats this check for every OTHER
    # call path into that function; the duplication is deliberate defense in
    # depth, the same posture `AtomicWriter`'s own no-clobber re-check takes.
    for source in sources:
        classify_operand(source)

    if dpi is not None and width is not None:
        raise UsageError("--dpi and --width are mutually exclusive")
    if width is not None and width < 1:
        raise UsageError("--width must be 1 or greater")
    if dpi is not None and dpi <= 0:
        raise UsageError("--dpi must be greater than 0")
    if quality is not None:
        if image_format.value in _LOSSLESS_FORMATS:
            raise UsageError(f"--quality has no effect with --format {image_format.value}")
        if not (1 <= quality <= 100):
            raise UsageError("--quality must be between 1 and 100")

    if width is not None:
        resolved_dpi = None
    elif dpi is not None:
        resolved_dpi = dpi
    else:
        resolved_dpi = _DEFAULT_DPI
    out_dir = config.out_dir if config.out_dir is not None else Path()

    result = rasterize_document(
        sources,
        pages_spec=pages,
        dpi=resolved_dpi,
        width_px=width,
        fmt=image_format.value,
        quality=quality,
        grayscale=grayscale,
        name_template=config.name,
        out_dir=out_dir,
        policy=config.safety,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


rasterize_command.__doc__ = _HELP
