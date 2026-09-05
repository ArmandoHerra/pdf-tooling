"""The ``reorder`` verb (PDF-08).

Typer surface only: flag validation, one call into ``ops/pages.py``, one result
mapped to an exit code. No PDF logic lives here, and no engine library is
imported at module scope (`PLAN.md` §12 R-13).

**One verb per file** — see ``cmd_extract.py``'s module docstring for the
mechanism (`cli/common.py:768`'s ``_CONSUMES_BY_MODULE`` is keyed by module).

**OR-3 (`decision.md` §0.5).** `reorder` declares all four output flags
(``--output``, ``--out-dir``, ``--name``, ``--in-place``); every one is
honoured, so its OR-3 arm can never refuse.

**The remainder rule is why this verb honours ``--in-place`` safely (§D3).**
`reorder` is *total*: every input page appears in the output at least once,
because pages the selection does not name are appended rather than dropped.
Under drop semantics, ``reorder book.pdf --pages 'last,1' --in-place`` would
destroy 480 pages of a 482-page document as its **documented** behaviour, in a
product whose only recovery path is the ``.bak`` sidecar (`PLAN.md` §12 R-06).
A verb named "reorder" must not be the largest data-loss footgun in the tool.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.cli.password import ENV_PASSWORD, plan_password
from pdf_toolkit.errors import UsageError
from pdf_toolkit.ops.pages import reject_missing_sources, reorder_run
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.confirm import require_confirmation

__all__ = ["reorder_command"]

VERB = "reorder"

_HELP = """Rewrite page order from an explicit sequence.

SELECTION SEMANTICS. reorder is ORDERED: order and duplicates are preserved,
so the pages you name come first, in the order you named them, and a page
named twice appears twice. delete and rotate are the set verbs, and treat the
same --pages string differently.

REMAINDER RULE. pages you do not name are appended after the named sequence,
in ascending original order. reorder is total -- it never drops a page, so the
output always has at least as many pages as the input. --pages 'last,1' on a
ten-page document yields 10,1,2,3,4,5,6,7,8,9.

An exclusion therefore MOVES A PAGE TO THE BACK rather than deleting it:
--pages 'all,!3' on a five-page document yields 1,2,4,5,3. To remove a page,
run delete --pages 3; to keep only a subset, run extract.

An empty-but-valid selection (--pages 'all,!all') is exit 4: valid invocation,
nothing to act on.

DESTINATIONS. -O writes one file (multiple inputs sharing one -O is an arity
error, exit 2 -- use --out-dir instead). --out-dir writes one file per input,
named by --name (default '{stem}.{ext}'). --in-place overwrites each input,
with a .bak sidecar first (--no-backup suppresses the sidecar, explicitly).
Exactly one of --output/--out-dir/--in-place is required.

A bulk --in-place run (more than one input) refuses on a non-terminal without
-y, and prints the exact command to re-run.
"""


@global_options(consumes=("--output", "--out-dir", "--name", "--in-place"))
def reorder_command(
    ctx: typer.Context,
    sources: Annotated[
        list[Path],
        operand_argument(metavar="PDF...", help="One or more PDFs to reorder."),
    ],
    pages: Annotated[
        str | None,
        typer.Option("--pages", help="The leading page sequence, in order (see --help)."),
    ] = None,
) -> None:
    """Rewrite page order; pages you do not name are appended."""
    config = get_config(ctx)

    # PDF-37: the GLOBAL slot. `plan_password` never reads anything (D3);
    # `ops/document_password.PasswordResolver` reads it at most once, and
    # only if a source turns out to be encrypted.
    password = plan_password(
        slot="password",
        flag="--password-file",
        value=config.password_file,
        env_names=(ENV_PASSWORD,),
        prompt="Password: ",
        allow_empty=True,
    )

    # Exits 4 on a nonexistent input, unconditionally and first (`PLAN.md` §10).
    reject_missing_sources(sources)

    if config.output is not None and len(sources) > 1:
        raise UsageError(
            f"{VERB} of {len(sources)} inputs cannot share one -O/--output target; "
            "pass --out-dir instead"
        )
    if pages is None:
        raise UsageError(f"{VERB} requires --pages")
    if not (config.output is not None or config.out_dir is not None or config.in_place):
        raise UsageError(f"{VERB} requires --output, --out-dir, or --in-place")

    if config.in_place:
        # Local import: `cli.main` imports this module at load time.
        from pdf_toolkit.cli.main import build_rerun_hint

        require_confirmation(
            config.safety,
            input_count=len(sources),
            in_place=True,
            rerun_hint=build_rerun_hint(),
        )

    result = reorder_run(
        sources,
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


reorder_command.__doc__ = _HELP
