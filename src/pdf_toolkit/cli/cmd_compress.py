"""The ``compress`` verb (PDF-12).

Typer surface only: flag validation, one call into ``ops/optimize.py``, one
result mapped to an exit code. No PDF logic lives here, and **no engine
library is imported at module scope** — `PLAN.md` §12 R-13 keeps
``pdftoolkit --help`` inside its startup budget by lazy-importing every
adapter.

**One verb per file, deliberately** — the same convention every other
``cli/cmd_*.py`` module already follows (``cmd_merge.py``, ``cmd_split.py``,
``cmd_text.py``/``cmd_tables.py`` even though both share ``ops/textract.py``).
`cli/common.py`'s OR-3 declaration (``_CONSUMES_BY_MODULE``) is keyed by the
**module** a command's callback belongs to, and ``tests/registry.py``'s own
docstring states the invariant this depends on: *"each `cli/cmd_*.py` module
declares exactly one command, so this can never collide."* `repair` and
`linearize` are `cmd_repair.py`/`cmd_linearize.py`, siblings of this file —
all three call into the one shared ``ops/optimize.py``, which carries no
such per-module constraint (`ops/` is never subject to OR-3's registry).

The conventional one-call PDF compressor is AGPL-3.0+ and deliberately
excluded by `PLAN.md` §7.2 — `pikepdf`/libqpdf object streams plus an
opt-in Pillow image pass replace it; that is the design, not a workaround
(see ``ops/optimize.py``'s own module docstring).

**OR-3 (`decision.md` §0.5).** `compress` declares all four output flags it
consumes (`--output`, `--out-dir`, `--name`, `--in-place`) on its decorator
line and nowhere else — it legitimately honours every one of them, so its
OR-3 arm can never refuse (D-12.0a). Everything else is refused, exit 2,
once, by the shared option layer in ``cli/common.py``; this module contains
no check for any output flag's *consumption*. What it DOES check is the one
thing OR-3 structurally cannot express: **arity**. `compress a.pdf b.pdf -O
one.pdf` is two inputs sharing one `-O` target, which is an arity mismatch,
not an unconsumed flag — refused here, exit 2, exactly like `split`'s own
mode-count check.

**X-67 / B-054.** The dry-run prediction is inherited: ``ops`` calls the
shared ``safety.atomic.plan_output_set``/``AtomicWriter`` planning path in
both modes through ``plan_filesystem``, so a dry run over an occupied or
unwritable destination predicts what the real run does. No per-verb
prediction logic and no per-verb exit-code logic exists in this file.

**B-079 — the bulk-destructive non-TTY confirmation gate is wired here.**
`compress` is multi-input (``sources: list[Path]``) and was the one verb of
the five-verb blind spot (``compress``/``repair``/``linearize``/``encrypt``/
``decrypt``) actually REACHABLE with a bulk ``--in-place`` run before this
fix — `compress a.pdf b.pdf --in-place` on a non-terminal used to exit 0 and
mutate both inputs, unconfirmed. Mirrors ``cmd_delete.py``/``cmd_rotate.py``'s
own call site exactly: ``require_confirmation`` with the REAL resolved input
count (``len(sources)``), never a literal.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.errors import UsageError
from pdf_toolkit.ops.optimize import (
    DEFAULT_IMAGE_DPI,
    DEFAULT_IMAGE_QUALITY,
    compress_run,
)
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.confirm import require_confirmation
from pdf_toolkit.safety.paths import classify_operand

__all__ = ["ImageMode", "compress_command"]

VERB = "compress"


class ImageMode(StrEnum):
    """`compress --images` (D-12.2). Set-semantics: normalized, sorted,
    deduplicated page selection when combined with `--pages` (`PLAN.md`
    §4.3)."""

    KEEP = "keep"
    DOWNSAMPLE = "downsample"
    RECOMPRESS = "recompress"


_HELP = """Shrink a PDF: object streams and stream recompression (lossless),
plus an optional Pillow image pass (lossy, opt-in, never implied).

Selected through the StructureEngine port, by capability and never by
adapter name -- the 'object-streams' capability for the structural pass,
'image-pass' for --images.

Bare 'compress in.pdf' runs the structural pass ONLY -- no image is ever
transformed unless --images names a lossy mode. --images keep|downsample|
recompress (default keep) controls the pass: downsample and recompress are
LOSSY -- --lossless and a lossy --images together exit 2.

--lossless adds a runtime guarantee that extracted text stays byte-identical:
page count, every image XObject's (/Filter, /Width, /Height, /ColorSpace,
/BitsPerComponent), and every /DCTDecode stream's raw bytes are compared
before and after the structural pass. Any mismatch means nothing is written
and the run exits 1, naming the failed check -- this is enforced, not merely
asserted.

--images downsample resamples (Image.LANCZOS) any in-scope image wider than
--image-dpi x the PAGE's own width in inches -- the page box, never the
image's own placement rectangle, which under-downsamples a small image and
is stated here as the known, conservative limitation. --images recompress
re-encodes every in-scope image as JPEG at --image-quality, pixel dimensions
unchanged. Either way, an image that cannot be re-encoded without losing
information (an alpha channel, bilevel, CCITTFaxDecode or JBIG2Decode) is
skipped and the count is reported -- never silently converted.

--pages scopes the image pass to a SET of pages (PLAN.md §4.3): it has no
meaning without --images and exits 2 without one, same for --image-dpi and
--image-quality.

DESTINATIONS. -O writes one file (multiple inputs sharing one -O is an
arity error, exit 2 -- use --out-dir instead). --out-dir writes one file per
input, named by --name (default '{stem}.{ext}'). --in-place overwrites each
input, with a .bak sidecar first. Exactly one of --output/--out-dir/
--in-place is required.

The measurement, never a claim: every item's bytes_before/bytes_after are
reported, and a run whose output did not shrink still exits 0, with the
percentage rendered as negative or zero and a stderr warning -- hiding a
failed compression is the same dishonesty this tool refuses everywhere else.
"""


def _reject_missing_sources(sources: list[Path]) -> None:
    for source in sources:
        classify_operand(source)


@global_options(consumes=("--output", "--out-dir", "--name", "--in-place"))
def compress_command(
    ctx: typer.Context,
    sources: Annotated[
        list[Path],
        operand_argument(metavar="PDF...", help="One or more PDFs to compress."),
    ],
    lossless: Annotated[
        bool,
        typer.Option("--lossless", help="Enforce byte-identical text and structure (see --help)."),
    ] = False,
    images: Annotated[
        ImageMode,
        typer.Option("--images", help="Image pass: keep (default), downsample, recompress."),
    ] = ImageMode.KEEP,
    image_dpi: Annotated[
        float | None,
        typer.Option(
            "--image-dpi",
            help=f"Downsample threshold (default {DEFAULT_IMAGE_DPI:g}).",
            show_default=False,
        ),
    ] = None,
    image_quality: Annotated[
        int | None,
        typer.Option(
            "--image-quality",
            help=f"JPEG re-encode quality (default {DEFAULT_IMAGE_QUALITY}).",
            show_default=False,
        ),
    ] = None,
    pages: Annotated[
        str | None,
        typer.Option("--pages", help="Scope the image pass to a page set. Requires --images."),
    ] = None,
) -> None:
    """Shrink PDFs via object streams, stream recompression, and an optional
    lossy image pass."""
    config = get_config(ctx)

    # PLAN.md §10's own contract: every verb with a path-taking argument
    # exits 4 on a nonexistent input, unconditionally -- checked first, so it
    # wins over any other usage error, mirroring every other multi-input verb.
    _reject_missing_sources(sources)

    if config.output is not None and len(sources) > 1:
        raise UsageError(
            f"compress of {len(sources)} inputs cannot share one -O/--output target; "
            "pass --out-dir instead"
        )

    active_image_pass = images is not ImageMode.KEEP
    if lossless and active_image_pass:
        raise UsageError(f"--lossless excludes a lossy image pass (--images {images.value})")
    if pages is not None and not active_image_pass:
        raise UsageError("--pages scopes the image pass; it has no meaning without --images")
    if image_dpi is not None and not active_image_pass:
        raise UsageError("--image-dpi has no meaning without --images")
    if image_quality is not None and not active_image_pass:
        raise UsageError("--image-quality has no meaning without --images")

    resolved_dpi = image_dpi if image_dpi is not None else DEFAULT_IMAGE_DPI
    resolved_quality = image_quality if image_quality is not None else DEFAULT_IMAGE_QUALITY

    if not (config.output is not None or config.out_dir is not None or config.in_place):
        raise UsageError("compress requires --output, --out-dir, or --in-place")

    if config.in_place:
        # Local import: `cli.main` imports this module at load time to
        # register the command, so a module-level import here would cycle.
        from pdf_toolkit.cli.main import build_rerun_hint

        require_confirmation(
            config.safety,
            input_count=len(sources),
            in_place=True,
            rerun_hint=build_rerun_hint(),
        )

    result = compress_run(
        sources,
        lossless=lossless,
        images=images.value,
        image_dpi=resolved_dpi,
        image_quality=resolved_quality,
        pages_spec=pages,
        output=config.output,
        out_dir=config.out_dir,
        name_template=config.name,
        in_place=config.in_place,
        policy=config.safety,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


compress_command.__doc__ = _HELP
