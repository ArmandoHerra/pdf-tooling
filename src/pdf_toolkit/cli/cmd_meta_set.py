"""The ``meta set`` verb (PDF-14).

Typer surface only: flag validation, one call into ``ops/metadata.py``, one
result mapped to an exit code. No PDF logic lives here.

**One verb per file** — see ``cmd_meta.py``'s module docstring for the
mechanism.

**OR-3.** ``meta set`` declares ``--output``/``--in-place`` only — no
``--out-dir``/``--name``: there is one input and one output document, no
directory shape and no name template, so both exit 2 (same shape as
``cmd_repair.py``/``cmd_linearize.py``/``cmd_encrypt.py``/``cmd_decrypt.py``).

**R6/B-079 — the bulk-destructive confirmation gate.** Mirrors
``cmd_rotate.py:119-127`` exactly: every ``--in-place`` path calls
``require_confirmation`` with the REAL resolved input count, so this verb
cannot join the five-verb blind spot (``compress``/``repair``/``linearize``/
``encrypt``/``decrypt``) where the gate is never wired at all. A single-input
run is never bulk, so the call is a no-op today — it is correct whichever way
this verb's arity ends up, which is the point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.cli.password import ENV_PASSWORD, plan_password
from pdf_toolkit.ops.metadata import meta_set_run
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.confirm import require_confirmation
from pdf_toolkit.safety.paths import classify_operand

__all__ = ["meta_set_command"]

VERB = "meta set"

_HELP = """Write or clear document information fields, and sync XMP where a
packet already exists.

Selected through the StructureEngine port, by capability -- never by adapter
name.

BOTH HALVES, ONE RULE. If the document HAS an XMP packet, every set and every
clear is applied to BOTH /Info and XMP. If it has NO packet, sets and clears
apply to /Info only -- no XMP packet is ever CREATED by this command; that
would change the document's shape and could invalidate a PDF/A conformance
claim the operator never asked to touch.

--clear-producer and --clear-all REMOVE keys; they never set a field to the
empty string.

--clear-all's SCOPE (read this before trusting it for privacy). --clear-all
empties the DOCUMENT-LEVEL /Info dictionary and deletes the DOCUMENT-LEVEL
XMP packet. It does NOT touch page-level XMP /Metadata, /PieceInfo
(document- or page-level application-private data), annotation author (/T)
fields, embedded-file metadata, or the trailer /ID -- 'meta get' REPORTS
these residual surfaces under "Not cleared by --clear-all" / the JSON
payload's residual_surfaces, so what --clear-all cannot remove is visible
rather than merely disclaimed.

With no field flag and no clear flag, this command exits 2 -- there is
nothing to set.

DESTINATIONS. -O writes the tagged document to a new file; --in-place
overwrites the input, with a .bak sidecar first. One of the two is required.
"""


def _reject_missing_sources(sources: list[Path]) -> None:
    for source in sources:
        classify_operand(source)


@global_options(consumes=("--output", "--in-place"))
def meta_set_command(
    ctx: typer.Context,
    source: Annotated[Path, operand_argument(metavar="PDF", help="The PDF to tag.")],
    title: Annotated[
        str | None, typer.Option("--title", help="Set /Title (and dc:title, if XMP exists).")
    ] = None,
    author: Annotated[
        str | None, typer.Option("--author", help="Set /Author (and dc:creator, if XMP exists).")
    ] = None,
    subject: Annotated[
        str | None,
        typer.Option("--subject", help="Set /Subject (and dc:description, if XMP exists)."),
    ] = None,
    keywords: Annotated[
        str | None,
        typer.Option("--keywords", help="Set /Keywords (and pdf:Keywords, if XMP exists)."),
    ] = None,
    creator: Annotated[
        str | None,
        typer.Option("--creator", help="Set /Creator (and xmp:CreatorTool, if XMP exists)."),
    ] = None,
    clear_producer: Annotated[
        bool,
        typer.Option(
            "--clear-producer", help="Remove /Producer (and pdf:Producer, if XMP exists)."
        ),
    ] = False,
    clear_all: Annotated[
        bool,
        typer.Option(
            "--clear-all",
            help=(
                "Empty document-level /Info and delete document-level XMP. "
                "Does NOT clear page-level metadata, PieceInfo, annotation "
                "author fields, embedded files or the trailer ID -- 'meta "
                "get' reports what is left."
            ),
        ),
    ] = False,
) -> None:
    """Write or clear document information fields, and sync XMP where present."""
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

    sets: dict[str, str] = {}
    if title is not None:
        sets["title"] = title
    if author is not None:
        sets["author"] = author
    if subject is not None:
        sets["subject"] = subject
    if keywords is not None:
        sets["keywords"] = keywords
    if creator is not None:
        sets["creator"] = creator

    if config.in_place:
        # Local import: `cli.main` imports this module at load time.
        from pdf_toolkit.cli.main import build_rerun_hint

        require_confirmation(
            config.safety,
            input_count=1,
            in_place=True,
            rerun_hint=build_rerun_hint(),
        )

    result = meta_set_run(
        source,
        sets=sets,
        clear_producer=clear_producer,
        clear_all=clear_all,
        output=config.output,
        in_place=config.in_place,
        policy=config.safety,
        password=password,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


meta_set_command.__doc__ = _HELP
