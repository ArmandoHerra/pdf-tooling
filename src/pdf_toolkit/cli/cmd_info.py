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
Existing but unreadable input                 1
User password required, none supplied         6
Several inputs, at least one failed           1
=========================================  ====

The malformed-PDF **1** is the one the repair work's acceptance signal consumes.
The unreadable-input **1** is PDF-26's, and it is the row that was MISSING: an
operand that exists and cannot be read is an operation that ran and failed, not
a mistyped command line, and it exited 2 on every verb until then. Every row
above is now driven through the CLI by `tests/test_info.py`, parsed out of this
table rather than transcribed from it, so a row cannot claim a code nothing
measures.
The batch row is ``PLAN.md`` §5.4's rule — *a failing input is recorded, the run
continues, and the run exits 1 at the end with a per-input status* — so a
multi-input run reports ``1`` and the per-item codes stay in the payload. A
single-input run reports that item's own code, which is what makes 1/4/6
distinguishable at all.

ENVELOPE
--------
``-o json`` is ``{"schema_version": 1, "verb": "info", "dry_run": …,
"documents": [...], "items": [...], "warnings": [], "duration_ms": 0,
"exit_code": …}``, one entry per input in input order. ``-o ndjson`` streams
one full entry per line with no envelope. ``-o table`` renders a
**projection** — the scalar columns a human reads — because a table cell
containing the whole metadata dictionary and a per-page array teaches nobody
anything; the full record is one ``-o json`` away.

``documents`` IS PRIMARY AND ``items`` IS NOW SUPPLIED TO ``-o json`` TOO —
A DECISION REVERSED ON THE RECORD (PDF-39 D4). This module used to argue that
the ``items`` alias existed for the streaming renderers alone, and kept it out
of ``-o json`` on the ground that the top-level key there was the published
one. ``documents`` remains the published key, verbatim and first, and X-410
forbids renaming it; what is overturned is keeping ``items`` out beside it.
Three spellings of one concept —
``items``, ``documents`` here, ``ports`` on ``doctor`` — under a single
``schema_version: 1`` envelope, documented nowhere a consumer reads, cost more
than one duplicated key ever did. ``documents`` and ``items`` are **the same
list**, asserted by equality so they cannot drift apart. ``-o table``'s
``items`` is still the projection, not the documents: a table is a projection
of the envelope, never the envelope.

``exit_code``/``warnings``/``duration_ms`` arrived with the same spec (D2), so
that all 26 leaves publish the same three envelope-level keys.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.cli.exit_codes import FAILURE, OK
from pdf_toolkit.cli.password import ENV_PASSWORD, plan_password
from pdf_toolkit.ops.document_password import NO_PASSWORD, PasswordSource
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
    password: PasswordSource = NO_PASSWORD,
) -> tuple[dict[str, Any], tuple[InspectionOutcome, ...]]:
    """The canonical payload plus the outcomes the exit code is derived from."""
    validate_operands(paths)
    outcomes = inspect_paths(paths, fonts=fonts, pages=pages_detail, password=password)
    entries = [outcome.to_dict() for outcome in outcomes]
    payload: dict[str, Any] = {
        "verb": VERB,
        "dry_run": dry_run,
        "documents": entries,
        # PDF-39 D4: the universal collection key, the SAME list as
        # `documents`. `documents` stays primary and first.
        "items": entries,
        # PDF-39 D2. `info` produces no warning strings of its own today; the
        # key is published as `[]` rather than omitted so a consumer reads the
        # same three keys off every verb. Never null.
        "warnings": [],
        # PDF-39 D2 -- `0`, chosen and reasoned rather than defaulted. A
        # STANDING byte-identity arm compares two independent `info -o json`
        # runs of the same argv and asserts `quiet.stdout == loud.stdout`:
        # tests/test_usage_envelope.py::test_ac18_quiet_suppresses_engine_chatter
        # A wall-clock reading here would make that arm flake, and D2's rule is
        # that the arm is not the thing that gives way.
        "duration_ms": 0,
        # PDF-39 D2/AC6: the code the process will exit with. DERIVED HERE
        # from the same pure `run_exit_code` the command itself calls, rather
        # than echoed from the number the process was handed -- a payload that
        # copied the process's code could not disagree with it, and the test
        # comparing the two would be a `B-080` tautology.
        "exit_code": run_exit_code(outcomes),
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
    """PDF-39 D4: ``items`` now lives in the payload, so ``-o json`` and
    ``-o ndjson`` read the identical object and the NDJSON branch is gone.
    ``-o table`` still overrides ``items`` with :func:`_table_rows`, because a
    table cell is a projection of a document and not the document."""
    if fmt is OutputFormat.TABLE:
        return render_payload({**payload, "items": _table_rows(payload)}, fmt)
    return render_payload(payload, fmt)


@global_options(consumes=())
def info_command(
    ctx: typer.Context,
    paths: Annotated[
        list[Path],
        operand_argument(metavar="PDF...", help="One or more PDF files."),
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

    # PDF-37: the GLOBAL slot. `plan_password` never reads anything (D3);
    # `ops/document_password.PasswordResolver` reads it at most once, and
    # only for an input that turns out to be encrypted.
    password = plan_password(
        slot="password",
        flag="--password-file",
        value=config.password_file,
        env_names=(ENV_PASSWORD,),
        prompt="Password: ",
        allow_empty=True,
    )

    payload, outcomes = build_payload(
        tuple(paths),
        fonts=fonts,
        pages_detail=pages_detail,
        dry_run=config.dry_run,
        password=password,
    )
    text = _render(payload, config.output_format)
    if text:
        typer.echo(text)
    for outcome in outcomes:
        if outcome.error is not None:
            typer.echo(f"error: {outcome.error.message} ({outcome.path})", err=True)
    raise typer.Exit(run_exit_code(outcomes))
