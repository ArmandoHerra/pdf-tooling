"""The ``text`` verb — extract text from PDF pages (PDF-11).

Typer surface only: flag validation, one call into ``ops/textract.py``, one
result rendered and mapped to an exit code. No PDF logic lives here, and **no
engine library is imported at module scope** — `PLAN.md` §12 R-13 keeps
``pdftoolkit --help`` inside a 250 ms budget by lazy-importing every adapter,
and a top-level engine import in a CLI module would regress startup for every
verb in the tool.

**OR-3 (`decision.md` §0.5).** This verb declares the output flags it consumes
on the decorator line and **nowhere else**. Everything it does not declare is
refused, exit 2, once, by the shared option layer in ``cli/common.py`` — this
module contains no check for any of them, on purpose. A duplicate check here
would be a second path that could later disagree with the shared one, which is
a defect *even while it agrees*.

**X-67 / B-054.** The dry-run prediction is likewise inherited: ``ops`` calls
the shared ``safety.atomic.plan_output_set`` planner in both modes, so a dry run
over an occupied or unwritable destination predicts what the real run does. No
per-verb prediction logic and no per-verb exit-code logic exists in this file.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.cli.password import ENV_PASSWORD, plan_password
from pdf_toolkit.ops.batch import preflight_operands
from pdf_toolkit.ops.pagerange import GRAMMAR_HELP
from pdf_toolkit.ops.textract import TextOutcome, extract_text_run
from pdf_toolkit.output import OutputFormat, render_payload

__all__ = ["build_payload", "text_command"]

VERB = "text"

_HELP = f"""Extract text from PDF pages.

Two paths, and the output ALWAYS declares which one produced it. The default is
the pypdfium2 fast path (strategy: fast). --layout switches to the pdfplumber
layout-aware path (strategy: layout) and emits one block per text line with its
bounding box. --layout NEVER silently falls back to the fast path: when the
layout adapter does not resolve, the run exits 3 carrying an install hint,
because returning fast-path output labelled 'layout' would be a lie and
returning it labelled 'fast' would be a silent downgrade. Both paths are
selected through the TextEngine port, by capability and never by adapter name.

BLOCK GEOMETRY. x and y are the block's TOP-LEFT corner, in PDF points,
measured from the page's top-left origin, with y increasing downward; width and
height are the box's extent in points. Blocks are sorted by (y, x) ascending
before emission, so y is non-decreasing down every page -- the tool imposes that
order rather than hoping the engine produced it. On a rotated page the
coordinates are reported in the space the layout engine presents for that page;
they are not re-mapped, and no claim is made that they are.

TEXT NORMALIZATION, applied identically on both paths: CRLF and CR become LF,
trailing spaces and tabs are stripped per line, and a run of trailing newlines
collapses to at most one.

--pages selects pages. The selection is a SET (PLAN.md §4.3's set-semantics
verbs): '--pages 3,1,1' normalizes to the sorted, deduplicated pages 1 and 3 --
order and duplicates are not preserved.

{GRAMMAR_HELP}

DESTINATIONS. With -O, one input's text is written to that one file (two inputs
onto one path is an output collision, exit 5). With a destination directory, one
file per input is written as '{{stem}}.txt', or one file per page when the
filename template names '{{page}}'. With no destination at all the text goes to
stdout and the 'strategy: ...' banner goes to stderr, so
'pdftoolkit text a.pdf -o table > a.txt' yields clean text. Note that stdout's
SHAPE still follows -o, which defaults to table on a terminal and json on a
pipe: a bare redirect captures the json report, not bare text.

EMPTY IS A REAL ANSWER. A page that exists and yields no characters returns
empty text, exits 0, and warns on stderr. That is an empty-but-valid report --
never exit 1, never exit 4, and never a fabricated string.

--threads is accepted but has NO effect on this verb: inputs are processed
sequentially, in the order they appear on the command line.
"""


def build_payload(outcome: TextOutcome) -> dict[str, Any]:
    """The canonical ``-o json`` payload for one ``text`` run.

    Assembled from ``to_dict()`` output only, never from a dataclass field, so
    the published schema cannot drift from the methods the golden test pins.
    ``strategy`` and ``engine`` are always present and never null: a result that
    could not say how it was produced is precisely what `PLAN.md` §12 R-03
    forbids.
    """
    base = outcome.result.to_dict()
    return {
        "verb": base["verb"],
        "strategy": outcome.strategy,
        "engine": outcome.engine.to_dict(),
        "dry_run": base["dry_run"],
        "pages": [page.to_dict() for page in outcome.pages],
        "items": base["items"],
        "warnings": base["warnings"],
        "duration_ms": base["duration_ms"],
        "exit_code": base["exit_code"],
    }


def _banner(outcome: TextOutcome) -> str:
    version = outcome.engine.version or "version unknown"
    return f"strategy: {outcome.strategy} ({outcome.engine.adapter} {version})"


def _stdout_text(outcome: TextOutcome) -> str:
    return "\n".join(page.text for page in outcome.pages).rstrip("\n")


def _emit(outcome: TextOutcome, fmt: OutputFormat, *, has_destination: bool) -> None:
    """Render the run, and place the banner on the stream that keeps stdout
    pipe-clean (Design §2): stdout when the payload is a run report, stderr when
    stdout is carrying the extracted text itself."""
    payload = build_payload(outcome)

    if fmt is OutputFormat.JSON:
        typer.echo(render_payload(payload, fmt))
    elif fmt is OutputFormat.NDJSON:
        stream = [
            {**page, "strategy": outcome.strategy, "engine": outcome.engine.to_dict()}
            for page in payload["pages"]
        ]
        text = render_payload({**payload, "items": stream}, fmt)
        if text:
            typer.echo(text)
    elif has_destination:
        typer.echo(_banner(outcome))
        typer.echo(render_payload(payload, fmt))
    else:
        print(_banner(outcome), file=sys.stderr)
        body = _stdout_text(outcome)
        if body:
            typer.echo(body)

    for warning in payload["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)


@global_options(consumes=("--output", "--out-dir", "--name"))
def text_command(
    ctx: typer.Context,
    sources: Annotated[
        list[Path],
        operand_argument(metavar="PDF...", help="One or more PDFs to extract text from."),
    ],
    pages: Annotated[
        str | None,
        typer.Option("--pages", help="Page selection (a set). Default: every page."),
    ] = None,
    layout: Annotated[
        bool,
        typer.Option(
            "--layout", help="Layout-aware extraction: one block per line, with geometry."
        ),
    ] = False,
) -> None:
    """Extract text from PDF pages, fast or layout-aware."""
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

    # PLAN.md §10's own contract (mechanized generically by the CLI-contract
    # harness's C5): every verb with a path-taking argument exits 4 on a
    # nonexistent input, unconditionally -- checked here, first, so it wins over
    # any other usage error. `ops/textract.py` repeats the check for every OTHER
    # call path into it; the duplication is deliberate defense in depth, the
    # same posture `AtomicWriter`'s own no-clobber re-check already takes.
    preflight_operands(sources)

    outcome = extract_text_run(
        sources,
        pages_spec=pages,
        layout=layout,
        output=config.output,
        out_dir=config.out_dir,
        name_template=config.name,
        policy=config.safety,
        password=password,
    )
    _emit(
        outcome,
        config.output_format,
        has_destination=config.output is not None or config.out_dir is not None,
    )
    raise typer.Exit(outcome.result.exit_code)


text_command.__doc__ = _HELP
