"""The ``tables`` verb — extract tables from PDF pages (PDF-11).

Typer surface only: flag validation, one call into ``ops/textract.py``, one
result rendered and mapped to an exit code. No PDF logic lives here, and **no
engine library is imported at module scope** (`PLAN.md` §12 R-13).

**OR-3 (`decision.md` §0.5).** This verb declares the output flags it consumes
on the decorator line and **nowhere else**; everything it does not declare is
refused, exit 2, once, by the shared option layer in ``cli/common.py``. There is
deliberately no check for any of them in this file.

**The collision path stays distinct from the OR-3 path, and that is a design
choice, not an accident.** ``tables`` *does* declare ``-O``, so pointing it at a
selection that yielded two or more tables is an output **collision — exit 5**,
raised by ``safety.paths.check_output_collisions`` in the op layer. It is not an
OR-3 usage refusal. Two paths, two codes, and a test proves they stay apart.

**X-67 / B-054.** The dry-run prediction is inherited from the shared
``safety.atomic.plan_output_set`` planner. No per-verb prediction logic and no
per-verb exit-code logic exists here.
"""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.ops.pagerange import GRAMMAR_HELP
from pdf_toolkit.ops.textract import TableOutcome, extract_tables_run
from pdf_toolkit.output import OutputFormat, render_payload
from pdf_toolkit.safety.paths import classify_operand

__all__ = ["TableFormat", "TableStrategy", "build_payload", "tables_command"]

VERB = "tables"


class TableStrategy(StrEnum):
    """``--strategy`` — the two heuristics, and deliberately no third.

    There is no ``auto``. A strategy that runs both and ranks them is Phase 2
    (`PLAN.md` §12 R-03); accepting the token now and silently picking one is
    exactly the failure that rule exists to prevent, so an unknown value is
    rejected by this type rather than ignored.
    """

    LINES = "lines"
    TEXT = "text"


class TableFormat(StrEnum):
    """``--format`` — the two file shapes. Markdown, XLSX and HTML are out of
    scope for v1, not merely unimplemented."""

    CSV = "csv"
    JSON = "json"


_HELP = f"""Extract tables from PDF pages.

TABLE EXTRACTION IS A HEURISTIC. The engine infers a grid from page geometry and
this verb reports what it found, as it found it: no header row is detected, no
merged cell is reconstructed, no cell value is type-coerced, and nothing in the
output states how sure the engine was -- a fabricated number would be worse than
none, so none is invented.

--strategy lines|text (default lines) selects the heuristic, and the output
ALWAYS declares which one produced it. 'lines' keys off ruling lines actually
drawn in the content stream -- evidence present in the document itself --
whereas 'text' infers structure from whitespace alignment, which is why the
default is the one whose evidence the document supplies. The tool never switches
on its own. NOTE: '--strategy text' is pdfplumber's whitespace-alignment table
strategy; it is UNRELATED to the 'text' verb, which extracts prose. There is no
'--strategy auto': an unknown value exits 2 rather than being quietly ignored.

--format csv|json (default csv) governs FILES; -o governs stdout. Passing
--format with nowhere to write earns a warning on stderr and exits 0.

CSV DIALECT, pinned exactly: ',' delimiter, '"' quote character, minimal
quoting, doubled quotes, no escape character, LF line terminators (not RFC
4180's CRLF -- deliberate, for pipeline friendliness on the target platforms),
UTF-8 with no BOM, and NO header row. A newline inside a cell is preserved
inside the quoted field rather than flattened to a space. A cell the engine
found no text in is written as the empty string; the JSON shape keeps the
empty-versus-absent distinction and CSV cannot represent it, which is a real,
one-directional loss stated here rather than left to be discovered by diffing.

A CSV file cannot carry provenance without corrupting the grid, so it does not
try: the strategy behind every written artifact is declared in the run report on
stdout, and in every -o json / -o ndjson object.

--pages selects pages. The selection is a SET (PLAN.md §4.3's set-semantics
verbs): '--pages 3,1,1' normalizes to the sorted, deduplicated pages 1 and 3 --
order and duplicates are not preserved.

{GRAMMAR_HELP}

DESTINATIONS. With a destination directory, one artifact per detected table is
written as '{{stem}}-p{{page:03}}-t{{index}}.{{ext}}' by default. -O accepts
exactly one table; a selection yielding two or more onto one path is an output
collision and exits 5. With no destination nothing is written and the grids are
embedded in the run report on stdout.

ZERO TABLES IS A LEGITIMATE ANSWER: the run exits 0, reports an empty list, and
warns on stderr naming the strategy it used.

--threads is accepted but has NO effect on this verb: inputs are processed
sequentially, in the order they appear on the command line.

Extraction is selected through the TextEngine port, by capability and never by
adapter name.
"""


def build_payload(outcome: TableOutcome) -> dict[str, Any]:
    """The canonical ``-o json`` payload for one ``tables`` run.

    Assembled from ``to_dict()`` output only. ``strategy`` and ``engine`` are
    always present and never null.
    """
    base = outcome.result.to_dict()
    return {
        "verb": base["verb"],
        "strategy": outcome.strategy,
        "engine": outcome.engine.to_dict(),
        "dry_run": base["dry_run"],
        "tables": [grid.to_dict() for grid in outcome.tables],
        "items": base["items"],
        "warnings": base["warnings"],
        "duration_ms": base["duration_ms"],
        "exit_code": base["exit_code"],
    }


def _banner(outcome: TableOutcome) -> str:
    version = outcome.engine.version or "version unknown"
    return f"strategy: {outcome.strategy} ({outcome.engine.adapter} {version})"


def _render_grid(rows: list[list[str]]) -> str:
    """One grid as aligned plain text. A ``None`` cell renders as an empty
    column, exactly as the CSV shape writes it."""
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [[*row, *([""] * (width - len(row)))] for row in rows]
    widths = [max(len(row[column]) for row in padded) for column in range(width)]
    return "\n".join(
        "  ".join(row[column].ljust(widths[column]) for column in range(width)).rstrip()
        for row in padded
    )


def _embedded_grids(outcome: TableOutcome) -> str:
    """The human rendering of a destination-less run: each grid preceded by one
    comment line carrying its provenance, so a pasted grid is never anonymous."""
    chunks: list[str] = []
    for grid in outcome.tables:
        header = (
            f"# source={grid.source} page={grid.page} table={grid.index} "
            f"strategy={outcome.strategy} rows={grid.row_count} cols={grid.col_count}"
        )
        body = _render_grid([["" if cell is None else cell for cell in row] for row in grid.rows])
        chunks.append(f"{header}\n{body}" if body else header)
    return "\n\n".join(chunks)


def _emit(outcome: TableOutcome, fmt: OutputFormat, *, has_destination: bool) -> None:
    payload = build_payload(outcome)

    if fmt is OutputFormat.JSON:
        typer.echo(render_payload(payload, fmt))
    elif fmt is OutputFormat.NDJSON:
        stream = [
            {**grid, "strategy": outcome.strategy, "engine": outcome.engine.to_dict()}
            for grid in payload["tables"]
        ]
        text = render_payload({**payload, "items": stream}, fmt)
        if text:
            typer.echo(text)
    elif has_destination:
        typer.echo(_banner(outcome))
        typer.echo(render_payload(payload, fmt))
    else:
        print(_banner(outcome), file=sys.stderr)
        body = _embedded_grids(outcome)
        if body:
            typer.echo(body)

    for warning in payload["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)


@global_options(consumes=("--output", "--out-dir", "--name"))
def tables_command(
    ctx: typer.Context,
    sources: Annotated[
        list[Path],
        operand_argument(metavar="PDF...", help="One or more PDFs to extract tables from."),
    ],
    pages: Annotated[
        str | None,
        typer.Option("--pages", help="Page selection (a set). Default: every page."),
    ] = None,
    strategy: Annotated[
        TableStrategy,
        typer.Option("--strategy", help="Which table heuristic to use."),
    ] = TableStrategy.LINES,
    table_format: Annotated[
        TableFormat | None,
        typer.Option(
            "--format",
            help="File shape for written artifacts (default csv). Does not affect stdout.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Extract tables from PDF pages -- a documented heuristic, never a claim."""
    config = get_config(ctx)

    # See `cmd_text.py` for why this check is duplicated here and in the op
    # layer: PLAN.md §10's exit-4 contract must win over every other usage
    # error, and every other call path into the op needs it too.
    for source in sources:
        classify_operand(source)

    outcome = extract_tables_run(
        sources,
        pages_spec=pages,
        strategy=strategy.value,
        fmt=table_format.value if table_format is not None else None,
        output=config.output,
        out_dir=config.out_dir,
        name_template=config.name,
        policy=config.safety,
    )
    _emit(
        outcome,
        config.output_format,
        has_destination=config.output is not None or config.out_dir is not None,
    )
    raise typer.Exit(outcome.result.exit_code)


tables_command.__doc__ = _HELP
