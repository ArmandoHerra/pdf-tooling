"""The ``create`` verb — plain text into one PDF (Design §6, §11-§12).

Typer surface only: flag validation, reading the one input, one call into
``ops/compose.py``, one result mapped to an exit code. No layout logic lives
here.

Reading standard input is deliberately this layer's job and not the op's: "is
this a terminal?" is a property of the process, and an op that answered it would
be answering it about the wrong process the first time anything embeds this
package.

**OR-3 (Design §11).** ``create`` declares it consumes the single-output flag
and nothing else, so the other three global output flags exit 2 **for free**
from the shared option layer in ``cli/common.py``. This module contains no check
for any of them (AC22), and the refusal prose that has to *name* a flag lives in
``ops/compose.py`` for the same reason.

v1 is plain text only. Markdown and HTML are the ``[html]`` extra and Phase 2 —
no parser, no stub flag, not even a placeholder.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options, operand_argument
from pdf_toolkit.errors import FailureError, PdfToolkitError, UsageError
from pdf_toolkit.ops.compose import (
    BASE14_FONTS,
    DEFAULT_CREATE_MARGIN,
    DEFAULT_FONT,
    DEFAULT_SIZE,
    TAB_WIDTH,
    create_document,
    decode_utf8,
    parse_length,
    parse_page_size,
    resolve_create_output,
)
from pdf_toolkit.output import emit_result
from pdf_toolkit.safety.paths import classify_operand, unreadable_source_error

__all__ = ["STDIN_OPERAND", "create_command"]

VERB = "create"

#: The conventional spelling for "read standard input". Resolved in this
#: module's body rather than by the argument's own type, so the operand stays a
#: PATH for the verb registry -- typing it `str` to accommodate this sentinel
#: would classify `create` as taking no input paths and quietly drop it out of
#: the contract harness's nonexistent-input arm.
STDIN_OPERAND = Path("-")


_HELP = f"""Create a PDF from a plain-text file, or from standard input.

Exactly one input. '-' reads standard input to end-of-file:

    printf 'hello\\n' | pdftoolkit create -

Refusals are decisions, not accidents. Reading from a terminal is refused
outright (exit 2) rather than hanging on a prompt nobody typed. Standard
input with nothing to write it to is exit 2, because there is no input stem
to derive a name from. Empty input -- zero bytes, from a pipe or from a file
-- is exit 4 and writes NO file: a valid invocation with nothing to act on is
not a failure and not an empty PDF. Anything non-empty, however small, is at
least one page. Two or more operands is exit 2; concatenating is 'merge'.
A file input with no explicit destination writes 'notes.pdf' beside
'notes.txt'.

UTF-8 is the only accepted encoding; anything else is exit 1 with the byte
offset. CRLF becomes LF, a tab expands to {TAB_WIDTH} spaces, and a form feed forces a
page break. Lines wider than the content box wrap at word boundaries, falling
back to a character break for a single token longer than one line, so the page
count is a function of (text, font, size, page size, margin) and nothing else.

v1 uses the base-14 fonts and embeds none, so some characters cannot be
represented. Those render as '?' AND raise a warning naming how many and the
first offending codepoint with its line number -- visible degradation, never a
silent drop. Markdown and HTML input are not part of v1.

--font NAME (default {DEFAULT_FONT}). One of: {", ".join(BASE14_FONTS)}.
--size FLOAT (default {DEFAULT_SIZE:g}); leading is 1.2x the size.
--page-size a4|letter|WxH (default a4), WxH with an optional unit
  (pt, mm, cm, in; pt when omitted), e.g. '612x792' or '210x297mm'.
--margin N or N<unit> (default {DEFAULT_CREATE_MARGIN}) -- a document margin,
  deliberately unlike 'compose', which defaults to no margin at all.
--title TEXT sets the document title.

Needs the ComposeEngine, which is a hard install dependency: if it does not
resolve, that is a broken install (exit 3). Run 'pdftoolkit doctor'.
"""


@global_options(consumes=("--output",))
def create_command(
    ctx: typer.Context,
    source: Annotated[
        Path,
        operand_argument(
            metavar="TEXT",
            exists=False,
            help="A UTF-8 text file, or '-' for standard input.",
        ),
    ],
    font: Annotated[
        str,
        typer.Option("--font", help="Base-14 font name."),
    ] = DEFAULT_FONT,
    size: Annotated[
        float,
        typer.Option("--size", help="Type size in points; leading is 1.2x this."),
    ] = DEFAULT_SIZE,
    page_size: Annotated[
        str,
        typer.Option("--page-size", help="a4, letter, or WxH with an optional unit."),
    ] = "a4",
    margin: Annotated[
        str,
        typer.Option("--margin", help="Document margin: N or N<unit> (pt, mm, cm, in)."),
    ] = DEFAULT_CREATE_MARGIN,
    title: Annotated[
        str | None,
        typer.Option("--title", help="Document title.", show_default=False),
    ] = None,
) -> None:
    """Create a PDF from a plain-text file, or from standard input."""
    config = get_config(ctx)
    from_stdin = source == STDIN_OPERAND

    if not from_stdin:
        classify_operand(source, directory_message="expected a text file, not a directory")

    page = parse_page_size(page_size)
    margin_pt = parse_length(margin, flag="--margin")
    output = resolve_create_output(source, config.output, from_stdin=from_stdin)

    raw = _read_input(source, from_stdin=from_stdin)
    text = decode_utf8(raw, source=str(source))

    result = create_document(
        text,
        source=str(source),
        output=output,
        font=font,
        size=size,
        page=page,
        margin_pt=margin_pt,
        title=title,
        policy=config.safety,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


def _input_read_error(source: Path, error: OSError) -> PdfToolkitError:
    """Map a failure raised while READING *source* onto a coded error (PDF-26 §D3).

    The §D3 belt for this verb's one operand read. `compose` and `create` are the
    two verbs that turn NON-PDF input into PDF, and they were the two the belt
    missed together: every seam it reached first reads a PDF, so
    :func:`~pdf_toolkit.safety.paths.read_source_bytes` -- whose own fallback
    says ``could not read PDF`` -- serves none of them. It cannot serve this one
    either. A `.txt` operand is definitionally not a PDF, and answering a failing
    disk with ``could not read PDF`` would swap one wrong sentence for another
    rather than remove it.

    **The accessibility question is asked first, and this verb's own vocabulary
    is the fallback, not the other way round.**
    :func:`~pdf_toolkit.safety.paths.unreadable_source_error` is the same
    predicate :func:`~pdf_toolkit.safety.paths.classify_operand`'s rung 4 uses
    and the same one `ops/compose.py::_image_read_error` asks, so the belt and
    the classifier cannot come to disagree about what "unreadable" means at the
    one verb where both run. Everything else keeps the noun
    `cli/password.py::_read_file` already uses for its own read -- the thing
    actually being read, never the thing being produced.

    Unlike :func:`~pdf_toolkit.safety.paths.source_read_error` this has **no
    ``FileNotFoundError`` rung**, deliberately: that rung answers 4, and this
    seam has only ever answered 1. Refining an unhandled crash into a coded
    failure is this belt's whole job; renumbering a race it was not asked about
    is not. Both arms here are exit 1 -- the class and the message are refined,
    the integer never is.
    """
    unreadable = unreadable_source_error(source)
    if unreadable is not None:
        return unreadable
    return FailureError(f"could not read the input file: {error}", path=str(source))


def _read_input(source: Path, *, from_stdin: bool) -> bytes:
    """The one input, as bytes. Never blocks on an interactive terminal.

    The file read is belted (§D3): :func:`classify_operand` has already run its
    ``os.access`` by the time control reaches here, so an operand that went
    unreadable in between fails at THIS ``read_bytes`` -- the TOCTOU window that
    check cannot close, and the only reason the belt exists.
    """
    if not from_stdin:
        try:
            return source.read_bytes()
        except OSError as error:
            raise _input_read_error(source, error) from error
    try:
        interactive = sys.stdin.isatty()
    except (AttributeError, ValueError):  # pragma: no cover - closed/replaced stream
        interactive = False
    if interactive:
        raise UsageError("refusing to read from a terminal; pipe input in or pass a file path")
    return sys.stdin.buffer.read()


create_command.__doc__ = _HELP
