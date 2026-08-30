"""The ``permissions`` verb (PDF-13).

Typer surface only: password planning, one call into ``ops/crypto.py``, one
result mapped to an exit code. No PDF logic and no cryptography live here.

**One verb per file** — see `cmd_encrypt.py`'s module docstring for the
mechanism: `cli/common.py`'s OR-3 declaration is keyed by module, and a
second ``@global_options(consumes=…)`` in one file silently overwrites the
first. That trap is exactly what this verb would have hidden: an empty
``consumes=()`` recorded last would have reported *every* crypto verb as
consuming nothing, while each verb's runtime closure stayed correct.

**OR-3.** `permissions` **reports; it writes nothing**, so it declares
``consumes=()`` and all four of ``-O``, ``--out-dir``, ``--name`` and
``--in-place`` exit 2 from the shared option layer, creating nothing —
exactly as `info`/`doctor`/`version` do. An output flag honoured by a verb
that writes nothing is precisely the half-enforced shape OR-3 exists to end.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options
from pdf_toolkit.cli.password import ENV_PASSWORD, plan_password
from pdf_toolkit.errors import NoInputError, UsageError
from pdf_toolkit.ops.crypto import PasswordSource, permissions_run
from pdf_toolkit.output import emit_result

__all__ = ["permissions_command"]

VERB = "permissions"

_HELP = """Report a PDF's encryption algorithm and permission bits.

Reports only: this verb writes nothing, so -O, --out-dir, --name and
--in-place each exit 2.

PERMISSIONS ARE ADVISORY. The bits are a request to the reader, not a lock:
only cooperating readers honour them, any reader that holds the file may
ignore every bit, and a reader that can display a page can extract it.
Encryption protects the content; the bits on their own protect nothing.
'accessibility' is always granted whatever was requested at encryption time
-- PDF 2.0 deprecated that bit and conforming readers always permit it, so
it appears in the granted set of every encrypted document.

Where the format lets the bits be read without a password they are read and
reported; where it does not, the report says so (permissions_readable:
false) rather than reporting an empty set as if it were a measured deny.

An unencrypted document exits 0 with encrypted: false, a null algorithm and
every permission granted. An encrypted document whose user password was not
supplied exits 6.

PASSWORDS. A password is never accepted as a command-line value.
--password-file PATH reads one line from a file, or '-' reads one line from
standard input; PDF_TOOLKIT_PASSWORD is consulted when no flag is given, and
on a terminal you are prompted.
"""


def _reject_missing_sources(sources: list[Path]) -> None:
    for source in sources:
        if not source.exists():
            raise NoInputError("no such file", path=str(source))
        if source.is_dir():
            raise UsageError("expected a PDF file, not a directory", path=str(source))


@global_options(consumes=())
def permissions_command(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(metavar="PDF", help="The PDF to report on.")],
) -> None:
    """Report a PDF's encryption algorithm and its advisory permission bits."""
    config = get_config(ctx)

    # The password is OPTIONAL here, so the TTY tier is deliberately NOT
    # reached when nothing asked for one: `permissions report.pdf` on a
    # terminal must not stop and prompt for a credential an unencrypted
    # document does not need. When a flag or the environment variable IS
    # present, the full chain applies. A document that turns out to need a
    # credential nobody supplied is exit 6, decided from the document rather
    # than from the invocation.
    if config.password_file is not None or ENV_PASSWORD in os.environ:
        password = plan_password(
            slot="password",
            flag="--password-file",
            value=config.password_file,
            env_names=(ENV_PASSWORD,),
            prompt="Password: ",
            allow_empty=True,
        )
    else:
        password = PasswordSource(slot="password", source=None, read=None)

    _reject_missing_sources([source])

    result = permissions_run(source, password=password, policy=config.safety)
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


permissions_command.__doc__ = _HELP
