"""The ``ocr`` verb (PDF-15).

Typer surface only: flag validation, one call into ``ops/ocr.py``, one result
mapped to an exit code. No PDF logic lives here, and no engine library is
imported at module scope (``PLAN.md`` §12 R-13).

**One verb per file, deliberately** -- the same convention every other
``cli/cmd_*.py`` module already follows.

**OR-3 (`decision.md` §0.5, Design §D11.2).** ``ocr`` declares all four
output flags it consumes (``--output``, ``--out-dir``, ``--name``,
``--in-place``) on its decorator line and nowhere else -- the ``compress``
set (D11.1: "follow the landed `compress` precedent exactly"), the only
landed set that fits multi-input **and** ``--in-place``. Everything else is
refused, exit 2, once, by the shared option layer in ``cli/common.py``; this
module carries no check for any output flag's *consumption*. What it DOES
check is the one thing OR-3 structurally cannot express: **arity**. ``ocr
a.pdf b.pdf -O one.pdf`` is two inputs sharing one ``-O`` target -- refused
here, exit 2, exactly like ``compress``'s own precedent.

**B-076.** The ``--in-place`` + ``-O``/``--out-dir``/``--name`` conflict is
refused by the LANDED central check (``cli/common.py``'s
``_check_in_place_output_conflict``, called from ``validate_config``) --
this module contains no second copy of it.

**B-079 -- the bulk-destructive confirmation gate is wired here.** ``ocr`` is
multi-input and, per Design §D11.3, is now REACHABLE with a bulk
``--in-place`` run: ``require_confirmation`` fires with the REAL resolved
input count, mirroring ``cmd_compress.py``'s own call site exactly.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Final

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.cli.password import ENV_PASSWORD, plan_password
from pdf_toolkit.errors import UsageError
from pdf_toolkit.ops.ocr import (
    DEFAULT_DPI,
    DEFAULT_LANG,
    DEFAULT_PSM,
    DPI_RANGE,
    PSM_RANGE,
    ocr_run,
)
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.confirm import require_confirmation
from pdf_toolkit.safety.paths import classify_operand

__all__ = ["ocr_command"]

VERB = "ocr"

#: D5's own shape: one or more `[a-z]{3}` codes joined by `+`.
_LANG_SHAPE_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z]{3}(\+[a-z]{3})*$")

_LANG_SHAPE_ERROR = (
    "--lang must be one or more lowercase 3-letter codes joined by '+' (e.g. 'eng' or 'eng+osd')"
)


def _validate_lang_shape(lang: str) -> None:
    if not _LANG_SHAPE_RE.match(lang):
        raise UsageError(_LANG_SHAPE_ERROR)


def _validate_dpi(dpi: int) -> None:
    low, high = DPI_RANGE
    if not (low <= dpi <= high):
        raise UsageError(f"--dpi {dpi} is out of range ({low}..{high})")


def _validate_psm(psm: int) -> None:
    low, high = PSM_RANGE
    if not (low <= psm <= high):
        raise UsageError(f"--psm {psm} is out of range ({low}..{high})")
    if psm == 0:
        raise UsageError(
            "--psm 0 is orientation/script-detection only and produces no text layer; pick 1-13"
        )


def _reject_missing_sources(sources: list[Path]) -> None:
    for source in sources:
        classify_operand(source)


_HELP = """Add an invisible text layer to scanned pages. Pixels are never
touched -- for every OCR'd page a text-only PDF is generated (tesseract,
'-c textonly_pdf=1') and overlaid on the ORIGINAL page object; the page's
image XObject is byte-identical before and after.

Selected through the OcrEngine port, by capability and never by adapter
name.

--lang eng (default) -- one or more 'eng'-shaped codes joined by '+', each
validated against what this host's tesseract actually has installed
(`pdftoolkit doctor`); an unavailable pack exits 3 with an install hint
naming it. --dpi 300 (default) controls the render resolution the text is
recognised from (72-1200). --psm 3 (default) is tesseract's page
segmentation mode (0-13); --psm 0 is orientation-detection only and
produces no text layer, so it is refused.

--skip-text-pages leaves an already-extractable page untouched (no render,
no OCR spawn) -- proven selective, not a no-op, by AC5's own byte-identity
check on the untouched page alongside the OCR'd one.

SELECTION SEMANTICS. ocr is a SET operation: --pages is normalized to a
sorted, deduplicated set (PLAN.md §4.3) before anything runs. Default when
--pages is omitted: every page. Unselected pages are carried through
unmodified.

DESTINATIONS. -O writes one file (multiple inputs sharing one -O is an
arity error, exit 2 -- use --out-dir instead). --out-dir writes one file
per input, named by --name (default '{stem}.{ext}'). --in-place overwrites
each input, with a .bak sidecar first. Exactly one of --output/--out-dir/
--in-place is required.
"""


@global_options(consumes=("--output", "--out-dir", "--name", "--in-place"))
def ocr_command(
    ctx: typer.Context,
    sources: Annotated[
        list[Path],
        operand_argument(metavar="PDF...", help="One or more PDFs to OCR."),
    ],
    lang: Annotated[
        str,
        typer.Option("--lang", help=f"Tesseract language code(s) (default {DEFAULT_LANG})."),
    ] = DEFAULT_LANG,
    dpi: Annotated[
        int,
        typer.Option("--dpi", help=f"Render resolution for recognition (default {DEFAULT_DPI})."),
    ] = DEFAULT_DPI,
    psm: Annotated[
        int,
        typer.Option("--psm", help=f"Tesseract page segmentation mode (default {DEFAULT_PSM})."),
    ] = DEFAULT_PSM,
    skip_text_pages: Annotated[
        bool,
        typer.Option("--skip-text-pages", help="Leave an already-extractable page untouched."),
    ] = False,
    pages: Annotated[
        str | None,
        typer.Option("--pages", help="Scope the run to a page set (default: all)."),
    ] = None,
) -> None:
    """Add an invisible OCR text layer to the selected pages."""
    config = get_config(ctx)

    # PDF-37: the GLOBAL slot. `plan_password` never reads anything (D3);
    # `ops/document_password.PasswordResolver` reads it at most once per
    # source, and only if that source turns out to be encrypted.
    password = plan_password(
        slot="password",
        flag="--password-file",
        value=config.password_file,
        env_names=(ENV_PASSWORD,),
        prompt="Password: ",
        allow_empty=True,
    )

    _reject_missing_sources(sources)
    _validate_lang_shape(lang)
    _validate_dpi(dpi)
    _validate_psm(psm)

    if config.output is not None and len(sources) > 1:
        raise UsageError(
            f"ocr of {len(sources)} inputs cannot share one -O/--output target; "
            "pass --out-dir instead"
        )

    if not (config.output is not None or config.out_dir is not None or config.in_place):
        raise UsageError("ocr requires --output, --out-dir, or --in-place")

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

    result = ocr_run(
        sources,
        lang=lang,
        dpi=dpi,
        psm=psm,
        skip_text_pages=skip_text_pages,
        pages_spec=pages,
        output=config.output,
        out_dir=config.out_dir,
        name_template=config.name,
        in_place=config.in_place,
        policy=config.safety,
        password=password,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


ocr_command.__doc__ = _HELP
