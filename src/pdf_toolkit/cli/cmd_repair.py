"""The ``repair`` verb (PDF-12).

Typer surface only: flag validation, one call into ``ops/optimize.py``, one
result mapped to an exit code. No PDF logic lives here.

**One verb per file** — see `cmd_compress.py`'s module docstring for why:
`cli/common.py`'s OR-3 declaration is keyed by module, and every
``cli/cmd_*.py`` module declares exactly one command.

**OR-3.** `repair` declares `--output`/`--in-place` only — `--out-dir` and
`--name` exit 2, from the shared option layer, with no check for either
here.

**B-079 — the bulk-destructive non-TTY confirmation gate is wired here.**
`repair` takes a single ``source: Path`` argument, so a bulk ``--in-place``
run is not reachable today (two operands is an arity error, exit 2, before
this gate could ever be consulted) — the gap this closes was latent, not
exposed. Wiring it now (``input_count=1``, the REAL resolved count for this
verb's arity) is a no-op today and correct the day this verb's arity ever
changes, matching ``cmd_meta_set.py``'s own precedent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.cli.password import ENV_PASSWORD, plan_password
from pdf_toolkit.ops.optimize import repair_run
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.confirm import require_confirmation
from pdf_toolkit.safety.paths import classify_operand

__all__ = ["repair_command"]

VERB = "repair"

_HELP = """Structurally recover a damaged PDF via libqpdf's own recovery
parser.

Selected through the StructureEngine port, by capability ('repair') and
never by adapter name.

DESTINATIONS. -O writes the recovered document to a new file; --in-place
overwrites the input, with a .bak sidecar first. One of the two is required.

--report widens the report with the structural delta (object/page counts,
whether an xref reconstruction occurred). Recovery findings and the one-line
summary are always reported: 'no damage detected' when nothing was wrong --
this verb never dresses an ordinary resave up as a recovery -- or a count of
what was found otherwise. A truly unrecoverable input exits 1 and writes
nothing.
"""


def _reject_missing_sources(sources: list[Path]) -> None:
    for source in sources:
        classify_operand(source)


@global_options(consumes=("--output", "--in-place"))
def repair_command(
    ctx: typer.Context,
    source: Annotated[Path, operand_argument(metavar="PDF", help="The PDF to repair.")],
    report: Annotated[
        bool,
        typer.Option("--report", help="Widen the report with the structural delta."),
    ] = False,
) -> None:
    """Structurally recover a damaged PDF via libqpdf's own recovery parser."""
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

    if config.in_place:
        # Local import: `cli.main` imports this module at load time.
        from pdf_toolkit.cli.main import build_rerun_hint

        require_confirmation(
            config.safety,
            input_count=1,
            in_place=True,
            rerun_hint=build_rerun_hint(),
        )

    result = repair_run(
        source,
        output=config.output,
        in_place=config.in_place,
        report=report,
        policy=config.safety,
        password=password,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


repair_command.__doc__ = _HELP
