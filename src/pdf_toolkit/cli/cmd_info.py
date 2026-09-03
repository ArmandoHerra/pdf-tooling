"""The ``info`` verb — the first real read verb. **It writes nothing.**

``info`` reports page count, page sizes, encryption state and algorithm,
permission bits, PDF version, metadata, signature and form presence, and
linearization; ``--fonts`` and ``--pages-detail`` add the two expensive fields.
Without those flags the corresponding fields are an **empty tuple**, never
``None`` and never omitted, so the JSON shape is identical across flag
combinations.

EXIT CODES, PINNED
------------------
=========================================  ====
Success (including ``--dry-run``)             0
Malformed / corrupt / unparseable PDF         1
Nonexistent input path                        4
Unknown flag                                  2
Directory operand                             2
User password required, none supplied         6
Several inputs, at least one failed           1
=========================================  ====

The malformed-PDF **1** is the one the repair work's acceptance signal consumes.
The batch row is ``PLAN.md`` §5.4's rule — *a failing input is recorded, the run
continues, and the run exits 1 at the end with a per-input status* — so a
multi-input run reports ``1`` and the per-item codes stay in the payload. A
single-input run reports that item's own code, which is what makes 1/4/6
distinguishable at all.

ENVELOPE
--------
``-o json`` is ``{"schema_version": 1, "verb": "info", "documents": [...]}``,
one entry per input in input order. ``-o ndjson`` streams one full entry per
line with no envelope. ``-o table`` renders a **projection** — the scalar
columns a human reads — because a table cell containing the whole metadata
dictionary and a per-page array teaches nobody anything; the full record is one
``-o json`` away.

The ``items`` alias exists for the same reason as in ``doctor``: PDF-01 owns the
NDJSON and table renderers and they stream from ``payload["items"]``, so the
alias is supplied to those two and withheld from ``-o json``, whose top-level
key is the published one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from pdf_toolkit.cli.common import get_config, global_options
from pdf_toolkit.cli.exit_codes import FAILURE, OK
from pdf_toolkit.ops.inspect import InspectionOutcome, inspect_paths, validate_operands
from pdf_toolkit.output import OutputFormat, render_payload

__all__ = ["build_payload", "info_command", "run_exit_code"]

VERB = "info"

#: The scalar columns ``-o table`` shows, in reading order.
_TABLE_COLUMNS = (
    "path",
    "page_count",
    "pdf_version",
    "encrypted",
    "encryption_algorithm",
    "linearized",
    "has_forms",
    "has_signature",
    "size_bytes",
)


def run_exit_code(outcomes: tuple[InspectionOutcome, ...]) -> int:
    """The run's exit code from the per-item codes.

    One input reports its own code, so ``1`` (malformed), ``4`` (missing) and
    ``6`` (locked) stay distinguishable — a downstream verb keys off exactly
    that. More than one input collapses any failure to ``1``, which is
    ``PLAN.md`` §5.4's batch contract: the aggregate is "something in this run
    failed", and *which* thing is in the per-item payload rather than smuggled
    into a single integer.
    """
    failed = [outcome.exit_code for outcome in outcomes if not outcome.ok]
    if not failed:
        return OK
    if len(outcomes) == 1:
        return failed[0]
    return FAILURE


def build_payload(
    paths: tuple[Path, ...],
    *,
    fonts: bool,
    pages_detail: bool,
    dry_run: bool,
) -> tuple[dict[str, Any], tuple[InspectionOutcome, ...]]:
    """The canonical payload plus the outcomes the exit code is derived from."""
    validate_operands(paths)
    outcomes = inspect_paths(paths, fonts=fonts, pages=pages_detail)
    payload: dict[str, Any] = {
        "verb": VERB,
        "dry_run": dry_run,
        "documents": [outcome.to_dict() for outcome in outcomes],
    }
    return payload, outcomes


def _table_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in payload["documents"]:
        if entry.get("ok"):
            rows.append({column: entry.get(column) for column in _TABLE_COLUMNS})
        else:
            error = entry.get("error", {})
            rows.append(
                {
                    "path": entry.get("path"),
                    "page_count": None,
                    "pdf_version": None,
                    "error": error.get("message"),
                    "exit_code": error.get("code"),
                }
            )
    return rows


def _render(payload: dict[str, Any], fmt: OutputFormat) -> str:
    if fmt is OutputFormat.JSON:
        return render_payload(payload, fmt)
    if fmt is OutputFormat.NDJSON:
        return render_payload({**payload, "items": payload["documents"]}, fmt)
    return render_payload({**payload, "items": _table_rows(payload)}, fmt)


@global_options(consumes=())
def info_command(
    ctx: typer.Context,
    paths: Annotated[
        list[Path],
        typer.Argument(metavar="PDF...", help="One or more PDF files."),
    ],
    fonts: Annotated[
        bool,
        typer.Option("--fonts", help="Include the font names used by the document."),
    ] = False,
    pages_detail: Annotated[
        bool,
        typer.Option("--pages-detail", help="Include a per-page size/rotation/text report."),
    ] = False,
) -> None:
    """Report page count, encryption, version, metadata and structure.

    REPORTS, NEVER WRITES: this verb writes no files, so -O/--output,
    --out-dir, --name, --in-place, -f/--force and -y/--yes each exit 2.
    """
    config = get_config(ctx)
    payload, outcomes = build_payload(
        tuple(paths),
        fonts=fonts,
        pages_detail=pages_detail,
        dry_run=config.dry_run,
    )
    text = _render(payload, config.output_format)
    if text:
        typer.echo(text)
    for outcome in outcomes:
        if outcome.error is not None:
            typer.echo(f"error: {outcome.error.message} ({outcome.path})", err=True)
    raise typer.Exit(run_exit_code(outcomes))
