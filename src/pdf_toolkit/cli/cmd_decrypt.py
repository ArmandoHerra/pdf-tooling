"""The ``decrypt`` verb (PDF-13).

Typer surface only: password planning, one call into ``ops/crypto.py``, one
result mapped to an exit code. No PDF logic and no cryptography live here.

**One verb per file** — see `cmd_encrypt.py`'s module docstring for the
mechanism: `cli/common.py`'s OR-3 declaration is keyed by module, and a
second ``@global_options(consumes=…)`` in one file silently overwrites the
first.

**OR-3.** `decrypt` declares ``--output``/``--in-place`` only — ``--out-dir``
and ``--name`` exit 2, from the shared option layer, with no check for either
here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pdf_toolkit.cli.common import get_config, global_options
from pdf_toolkit.cli.password import ENV_PASSWORD, plan_password
from pdf_toolkit.errors import NoInputError, UsageError
from pdf_toolkit.ops.crypto import decrypt_run
from pdf_toolkit.output import emit_result

__all__ = ["decrypt_command"]

VERB = "decrypt"

_HELP = """Remove encryption from a PDF, given the correct password.

Selected through the StructureEngine port, by capability
('robust-encryption') and never by adapter name. Every cryptographic
operation is libqpdf's; this tool implements none of its own.

PASSWORDS. A password is never accepted as a command-line value: argv is
world-readable in /proc and lands in shell history. --password-file PATH
reads one line from a file, or '-' reads one line from standard input. With
no flag, PDF_TOOLKIT_PASSWORD is consulted, and on a terminal you are
prompted. With none of those, the run exits 6 and writes nothing. A wrong
password also exits 6, once -- there is no retry loop, because retrying is
the caller's recovery and a loop would complicate the exit-code contract
that scripts consume.

DESTINATIONS. -O writes the decrypted document to a new file; --in-place
overwrites the input, keeping a .bak sidecar of the still-encrypted
original. One of the two is required.

A document that is not encrypted exits 4 ("nothing to act on") and writes
nothing: that is not a failure and it is certainly not a wrong password.

The page tree round-trips byte for byte through encrypt then decrypt. The
whole document does not, and this tool does not claim it does: /ID,
/Encrypt, the trailer, the cross-reference table and object numbering all
legitimately change.
"""


def _reject_missing_sources(sources: list[Path]) -> None:
    for source in sources:
        if not source.exists():
            raise NoInputError("no such file", path=str(source))
        if source.is_dir():
            raise UsageError("expected a PDF file, not a directory", path=str(source))


@global_options(consumes=("--output", "--in-place"))
def decrypt_command(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(metavar="PDF", help="The PDF to decrypt.")],
) -> None:
    """Remove encryption from a PDF, given the correct password."""
    config = get_config(ctx)

    password = plan_password(
        slot="password",
        flag="--password-file",
        value=config.password_file,
        env_names=(ENV_PASSWORD,),
        prompt="Password: ",
        allow_empty=True,
    )

    _reject_missing_sources([source])

    result = decrypt_run(
        source,
        password=password,
        output=config.output,
        in_place=config.in_place,
        policy=config.safety,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


decrypt_command.__doc__ = _HELP
