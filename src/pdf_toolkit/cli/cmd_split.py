"""The ``split`` verb — one PDF into many (Design §D4-D6).

Typer surface only: flag validation, one call into ``ops/split.py``, one
result mapped to an exit code. No PDF logic lives here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.cli.password import ENV_PASSWORD, plan_password
from pdf_toolkit.errors import UsageError
from pdf_toolkit.ops.pagerange import GRAMMAR_HELP
from pdf_toolkit.ops.split import split_document
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.paths import classify_operand

__all__ = ["split_command"]

VERB = "split"

_HELP = f"""Split one PDF into many.

Exactly one mode flag is required: --every, --ranges, --each-page or
--at-bookmarks. --out-dir is required (created if absent, unless --dry-run);
-O/--output is exit 2 (split produces more than one file). --name templates
each output filename with {{stem}}, {{page}}, {{page:03}}, {{index}},
{{range}} and {{ext}} -- '{{page}}' requires --each-page. Default template:
'{{stem}}-{{page:03}}.{{ext}}' for --each-page, '{{stem}}-{{index:03}}.{{ext}}'
for the other three modes.

--every N          consecutive N-page chunks; the final chunk may be shorter.
--ranges SPEC       repeatable; the comma separates parts, not a union --
                    'split book.pdf --ranges 1-12,13-40,41-' writes three
                    files. A part is therefore always comma-free; a
                    non-contiguous union inside one part is out of scope --
                    see `extract` (a later verb) for that case.
--each-page         one file per page, in page order.
--at-bookmarks       split points are the document's top-level outline
                    entries. Pages before the first bookmark form a leading
                    part; two bookmarks at the same page produce one part,
                    never an empty file. A document with NO top-level
                    outline entries at all is exit 4 -- documented, tested,
                    and never a silent single-file passthrough.

{GRAMMAR_HELP}

Plan-then-write: every part is resolved and every target path rendered
before the first byte is written; a planning failure writes nothing.
"""


@global_options(consumes=("--out-dir", "--name"))
def split_command(
    ctx: typer.Context,
    source: Annotated[Path, operand_argument(metavar="PDF", help="The PDF to split.")],
    every: Annotated[
        int | None,
        typer.Option("--every", help="Split into consecutive N-page chunks."),
    ] = None,
    ranges: Annotated[
        list[str] | None,
        typer.Option(
            "--ranges",
            help="Comma-separated parts, e.g. '1-12,13-40,41-'. Repeatable.",
        ),
    ] = None,
    each_page: Annotated[
        bool,
        typer.Option("--each-page", help="One file per page."),
    ] = False,
    at_bookmarks: Annotated[
        bool,
        typer.Option("--at-bookmarks", help="Split at the document's top-level outline entries."),
    ] = False,
) -> None:
    """Split one PDF into many, by chunk size, explicit ranges, page or bookmark."""
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

    # PLAN.md §10's own contract (mechanized generically by the CLI-contract
    # harness's C5): every verb with a path-taking argument exits 4 on a
    # nonexistent input, unconditionally -- checked here, first, so it wins
    # over the mode-flag-count usage error below in the case both are true
    # (no mode flag given at all, against a path that also does not exist).
    # `ops/split.py::split_document` repeats this check for every OTHER call
    # path into that function; the duplication is deliberate defense in depth,
    # the same posture `AtomicWriter`'s own no-clobber re-check already takes.
    classify_operand(source)

    modes_given = [
        name
        for name, given in (
            ("--every", every is not None),
            ("--ranges", bool(ranges)),
            ("--each-page", each_page),
            ("--at-bookmarks", at_bookmarks),
        )
        if given
    ]
    if len(modes_given) != 1:
        raise UsageError(
            "split needs exactly one of --every, --ranges, --each-page, "
            f"--at-bookmarks (got {len(modes_given)}: {', '.join(modes_given) or 'none'})"
        )
    mode = modes_given[0].lstrip("-")

    if config.out_dir is None:
        raise UsageError("split requires --out-dir")

    result = split_document(
        source,
        mode=mode,
        every=every,
        ranges=tuple(ranges or ()),
        name_template=config.name,
        out_dir=config.out_dir,
        policy=config.safety,
        password=password,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


split_command.__doc__ = _HELP
