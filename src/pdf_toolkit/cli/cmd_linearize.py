"""The ``linearize`` verb (PDF-12).

Typer surface only: flag validation, one call into ``ops/optimize.py``, one
result mapped to an exit code. No PDF logic lives here.

**One verb per file** — see `cmd_compress.py`'s module docstring for why:
`cli/common.py`'s OR-3 declaration is keyed by module, and every
``cli/cmd_*.py`` module declares exactly one command.

**OR-3.** `linearize` declares `--output`/`--in-place` only — `--out-dir`
and `--name` exit 2, from the shared option layer, with no check for either
here.

**B-079 — the bulk-destructive non-TTY confirmation gate is wired here.**
`linearize` takes a single ``source: Path`` argument, so a bulk
``--in-place`` run is not reachable today (arity refuses a second operand at
exit 2 before this gate could be consulted) — the gap this closes was
latent, not exposed. Wiring it now (``input_count=1``, the REAL resolved
count for this verb's arity) is a no-op today and correct the day this
verb's arity ever changes, matching ``cmd_meta_set.py``'s own precedent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.ops.optimize import linearize_run
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.confirm import require_confirmation
from pdf_toolkit.safety.paths import classify_operand

__all__ = ["linearize_command"]

VERB = "linearize"

_HELP = """Rewrite a PDF for byte-serving ("fast web view").

Selected through the StructureEngine port, by capability ('linearize') and
never by adapter name.

DESTINATIONS. -O writes the linearized document to a new file; --in-place
overwrites the input, with a .bak sidecar first. One of the two is required.

Verified structurally, never by exit code alone: the candidate is reopened
and checked (is_linearized, and libqpdf's own check_linearization()) before
anything is written. A failed verification means nothing is written and the
run exits 1.
"""


def _reject_missing_sources(sources: list[Path]) -> None:
    for source in sources:
        classify_operand(source)


@global_options(consumes=("--output", "--in-place"))
def linearize_command(
    ctx: typer.Context,
    source: Annotated[Path, operand_argument(metavar="PDF", help="The PDF to linearize.")],
) -> None:
    """Rewrite a PDF for byte-serving ("fast web view"), verified structurally."""
    config = get_config(ctx)
    _reject_missing_sources([source])

    if config.in_place:
        # Local import: `cli.main` imports this module at load time.
        from pdf_toolkit.cli.main import build_rerun_hint

        require_confirmation(
            config.safety,
            input_count=1,
            in_place=True,
            rerun_hint=build_rerun_hint(),
        )

    result = linearize_run(
        source,
        output=config.output,
        in_place=config.in_place,
        policy=config.safety,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


linearize_command.__doc__ = _HELP
