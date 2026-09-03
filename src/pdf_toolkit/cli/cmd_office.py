"""The ``convert`` verb (PDF-15).

Typer surface only: flag validation, one call into ``ops/office.py``, one
result mapped to an exit code. No conversion logic lives here, and no engine
library is imported at module scope (``PLAN.md`` §12 R-13).

**One verb per file, deliberately** -- the same convention every other
``cli/cmd_*.py`` module already follows.

**OR-3 (`decision.md` §0.5, Design §D11.2).** ``convert`` declares
``--output``/``--out-dir``/``--name`` -- the ``text`` set (``cmd_text.py``),
not the ``compress`` set: ``--in-place`` is deliberately EXCLUDED (converting
an office document "in place" into a PDF is meaningless, and OR-3 turns that
from a silent oddity into a clean exit 2 -- the cleanest OR-3 refusal arm in
the cycle).

``convert`` is not page-range aware (PLAN.md §4.1): it declares no ``--pages``
option at all, so ``convert x --pages 1-2`` exits 2 through Click's own
unknown-option path (C3's own generic contract, verified against this file
rather than assumed) -- no second rejection is written here.

**B-079 -- the bulk-destructive confirmation gate is wired here.** ``convert``
carries no ``--in-place`` mode, so its ONLY destructive shape is a bulk
``--force`` run that would clobber existing targets (Design §D11.3):
mirrors ``cmd_merge.py``/``cmd_compose.py``'s own single-target
``clobbered=`` precedent, generalised across every resolved target via
``ops.office.resolve_convert_targets`` -- called ONLY when ``--force`` was
given and at least one resolved target already exists, exactly like
``merge``'s own ``config.force and target_exists(...)`` guard (an occupied
target WITHOUT ``--force`` is already refused at write time, exit 5, before
this gate would ever matter).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.errors import UsageError
from pdf_toolkit.ops.office import (
    DEFAULT_TIMEOUT_S,
    convert_run,
    resolve_convert_targets,
    validate_filter,
)
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.confirm import require_confirmation
from pdf_toolkit.safety.paths import classify_operand

__all__ = ["convert_command"]

VERB = "convert"

_HELP = """Convert one or more office documents to PDF via headless
LibreOffice.

Selected through the OfficeConverter port, by capability and never by
adapter name.

Each invocation gets its own isolated LibreOffice user-profile directory
under a private scratch tree (Design §D6) -- never the shared/default
profile, which serialises conversions and causes intermittent failures
under concurrency -- created and removed automatically. LibreOffice never
writes to the destination directly: it converts into that private scratch
space, and the resulting bytes cross the destination through this
product's one write chokepoint, exactly like every other producing verb.

Success is measured, never assumed: an exit 0 from soffice having produced
no PDF (LibreOffice's own well-known failure mode) is treated as a failure
here too, exit 1, naming the input.

--filter NAME maps to '--convert-to pdf:NAME' (e.g. 'writer_pdf_Export');
letters, digits and underscores only. --timeout SECONDS bounds one
conversion (default 180s); on expiry the WHOLE process group is killed, so
no soffice.bin daemon survives (the mediakit MHC-50 lesson).

Not page-range aware: --pages is not a recognised flag here and exits 2.

DESTINATIONS. -O writes one file (multiple inputs sharing one -O is an
arity error, exit 2). --out-dir writes one file per input, named by --name
(default '{stem}.pdf'). --in-place is not accepted (converting an office
document 'in place' into a PDF is meaningless) and exits 2. Exactly one of
--output/--out-dir is required.
"""


def _reject_missing_sources(sources: list[Path]) -> None:
    for source in sources:
        classify_operand(source, directory_message="expected a file, not a directory")


@global_options(consumes=("--output", "--out-dir", "--name"))
def convert_command(
    ctx: typer.Context,
    sources: Annotated[
        list[Path],
        operand_argument(metavar="FILE...", help="One or more office documents to convert."),
    ],
    filter_name: Annotated[
        str | None,
        typer.Option("--filter", help="LibreOffice export filter, e.g. 'writer_pdf_Export'."),
    ] = None,
    timeout: Annotated[
        float,
        typer.Option(
            "--timeout",
            help=f"Seconds before the conversion is killed (default {DEFAULT_TIMEOUT_S:g}).",
        ),
    ] = DEFAULT_TIMEOUT_S,
) -> None:
    """Convert office documents to PDF via headless LibreOffice."""
    config = get_config(ctx)

    _reject_missing_sources(sources)
    validate_filter(filter_name)
    if timeout <= 0:
        raise UsageError("--timeout must be greater than 0")

    if config.output is not None and len(sources) > 1:
        raise UsageError(
            f"convert of {len(sources)} inputs cannot share one -O/--output target; "
            "pass --out-dir instead"
        )

    if not (config.output is not None or config.out_dir is not None):
        raise UsageError("convert requires --output or --out-dir")

    if config.force:
        planned = resolve_convert_targets(
            sources, output=config.output, out_dir=config.out_dir, name_template=config.name
        )
        existing = tuple(str(item.target) for item in planned if item.target.exists())
        if existing:
            # Local import: `cli.main` imports this module at load time to
            # register the command, so a module-level import here would cycle.
            from pdf_toolkit.cli.main import build_rerun_hint

            require_confirmation(
                config.safety,
                input_count=len(sources),
                clobbered=existing,
                rerun_hint=build_rerun_hint(),
            )

    result = convert_run(
        sources,
        filter_name=filter_name,
        timeout=timeout,
        output=config.output,
        out_dir=config.out_dir,
        name_template=config.name,
        policy=config.safety,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


convert_command.__doc__ = _HELP
