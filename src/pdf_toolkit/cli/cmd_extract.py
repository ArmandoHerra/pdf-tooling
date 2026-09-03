"""The ``extract`` verb (PDF-08).

Typer surface only: flag validation, one call into ``ops/pages.py``, one result
mapped to an exit code. No PDF logic lives here, and **no engine library is
imported at module scope** — `PLAN.md` §12 R-13 keeps ``pdftoolkit --help``
inside its startup budget by lazy-importing every adapter.

**One verb per file, and this one is not style.** `cli/common.py`'s OR-3
declaration is recorded as ``_CONSUMES_BY_MODULE[func.__module__] = consumes``
(`cli/common.py:768`) — keyed by the **module** a command's callback belongs
to — and that line's own comment states the invariant it rests on: *"each
`cli/cmd_*.py` module declares exactly one command, so this can never
collide."* Four ``@global_options(consumes=…)`` decorators in one module would
silently overwrite that key, last decorator winning, so ``tests/registry.py``
would report the **wrong** tuple for three of the four verbs while each verb's
runtime closure stayed correct — a latent, invisible OR-3 hole. `delete`,
`rotate` and `reorder` are ``cmd_delete.py``/``cmd_rotate.py``/
``cmd_reorder.py``, siblings of this file; all four call into the one shared
``ops/pages.py``, which carries no such per-module constraint.

**OR-3 (`decision.md` §0.5).** `extract` declares the three output flags it
consumes (``--output``, ``--out-dir``, ``--name``) on its decorator line and
nowhere else. It deliberately does **not** declare ``--in-place``: `extract`
derives a different page set from its input, so "mutate the input" has no
meaning here that is not simply `reorder` or `delete`.

**That refusal is produced BY THE DECLARATION**, which is the whole point.
``_check_output_flag_consumption`` (`cli/common.py:578`) emits, unaided:

    extract does not accept --in-place (extract only accepts --output,
    --out-dir, --name among the output flags)

naming the verb, the offending flag, and what the verb does accept. **There is
no check for the in-place policy anywhere in this file** — writing one would
re-create per-verb what OR-3 exists to make unnecessary, and would be the
first of four copies to drift.

Two rules that are NOT OR-3 and are deliberately not folded into it, because
the declaration stays one-dimensional (verb -> flag set):

1. **Arity.** ``-O`` with more than one input is an *arity* error, not a
   consumption error — refused here, exit 2, naming ``--out-dir`` as the
   alternative, exactly as ``cmd_compress.py:173-177`` does.
2. **A destination is required.** ``extract`` needs ``--output`` or
   ``--out-dir``; neither given is exit 2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.errors import UsageError
from pdf_toolkit.ops.pages import extract_run, reject_missing_sources
from pdf_toolkit.output import emit_result

__all__ = ["extract_command"]

VERB = "extract"

_HELP = """Write selected pages to a NEW document.

SELECTION SEMANTICS. extract is ORDERED: order and duplicates are preserved,
so the pages come out in the order you named them and a page named twice
appears twice. --pages '1,1,3' yields THREE pages (1, 1, 3); --pages '5-1'
yields pages 5,4,3,2,1 in that order. This is what separates extract from a
set filter, and it is the opposite of what delete and rotate do with the same
--pages string.

extract SUBSETS a document. To permute one without losing pages, use reorder
(pages you do not name are appended there, never dropped); to remove pages,
use delete.

DESTINATIONS. -O writes one file (multiple inputs sharing one -O is an arity
error, exit 2 -- use --out-dir instead). --out-dir writes one file per input,
named by --name (default '{stem}.{ext}'). One of --output/--out-dir is
required. extract does not accept --in-place: it derives a different page set
from its input, so there is nothing to mutate in place -- that invocation is
exit 2, from the shared option layer.

An empty-but-valid selection (--pages 'all,!all', or --pages even on a
one-page document) is exit 4: a valid invocation with nothing to act on.
"""


@global_options(consumes=("--output", "--out-dir", "--name"))
def extract_command(
    ctx: typer.Context,
    sources: Annotated[
        list[Path],
        operand_argument(metavar="PDF...", help="One or more PDFs to extract pages from."),
    ],
    pages: Annotated[
        str | None,
        typer.Option("--pages", help="Pages to extract, in the order given (see --help)."),
    ] = None,
) -> None:
    """Write selected pages to a new PDF, in the order given."""
    config = get_config(ctx)

    # `PLAN.md` §10's own contract: every verb with a path-taking argument
    # exits 4 on a nonexistent input, unconditionally -- checked FIRST, so it
    # wins over any other usage error, mirroring every other multi-input verb.
    reject_missing_sources(sources)

    if config.output is not None and len(sources) > 1:
        raise UsageError(
            f"{VERB} of {len(sources)} inputs cannot share one -O/--output target; "
            "pass --out-dir instead"
        )
    if pages is None:
        raise UsageError(f"{VERB} requires --pages")
    if config.output is None and config.out_dir is None:
        raise UsageError(f"{VERB} requires --output or --out-dir")

    result = extract_run(
        sources,
        pages_spec=pages,
        output=config.output,
        out_dir=config.out_dir,
        name_template=config.name,
        policy=config.safety,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


extract_command.__doc__ = _HELP
