"""The ``encrypt`` verb (PDF-13).

Typer surface only: flag validation, the ``--allow`` vocabulary, the
plaintext-``.bak`` gate, one call into ``ops/crypto.py``, one result mapped to
an exit code. No PDF logic and no cryptography live here.

**One verb per file, and here it is load-bearing rather than stylistic.**
``cli/common.py``'s OR-3 declaration is recorded as
``_CONSUMES_BY_MODULE[func.__module__] = consumes`` — keyed by *module* — and
that line's own comment states the invariant it depends on: *"each
`cli/cmd_*.py` module declares exactly one command, so this can never
collide."* Three ``@global_options(consumes=…)`` decorators in one module
silently overwrite that key, last decorator winning, and ``tests/registry.py``
would then report `permissions`' empty tuple for all three verbs while each
verb's runtime closure stayed correct — a latent, invisible OR-3 hole. PDF-12
hit exactly this and split `cmd_optimize.py` into three; those three files are
the precedent. The *ops* layer is shared (``ops/crypto.py``); the cmd module
never is.

**OR-3.** `encrypt` declares ``--output``/``--in-place`` only — ``--out-dir``
and ``--name`` exit 2, from the shared option layer, with no check for either
here. It produces exactly one file per invocation, so the declaration stays
one-dimensional.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Final

import typer

from pdf_toolkit.cli.common import get_config, global_options
from pdf_toolkit.cli.password import (
    ENV_OWNER_PASSWORD,
    ENV_PASSWORD,
    plan_password,
    reject_two_stdin_streams,
)
from pdf_toolkit.errors import NoInputError, PdfToolkitError, RefusedError, UsageError
from pdf_toolkit.ops.crypto import PasswordSource, encrypt_run
from pdf_toolkit.output import emit_result
from pdf_toolkit.output.logging import get_logger
from pdf_toolkit.ports.structure import ALWAYS_GRANTED_TOKENS, PERMISSION_TOKENS

__all__ = ["encrypt_command", "parse_allow", "plaintext_backup_refusal"]

VERB = "encrypt"

#: `--allow`'s two exclusive tokens. Combining either with anything else is
#: exit 2 rather than a silently-resolved intersection.
_ALL: Final[str] = "all"
_NONE: Final[str] = "none"

_HELP = """Encrypt a PDF with AES-256, or RC4-128 behind --legacy.

Selected through the StructureEngine port, by capability
('robust-encryption') and never by adapter name. Every cryptographic
operation is libqpdf's; this tool implements none of its own.

PASSWORDS. A password is never accepted as a command-line value: argv is
world-readable in /proc and lands in shell history. --owner-password-file
PATH reads one line from a file, or '-' reads one line from standard input.
With no flag, PDF_TOOLKIT_OWNER_PASSWORD (owner) and PDF_TOOLKIT_PASSWORD
(user) are consulted, and on a terminal you are prompted. With none of
those, the run exits 6 and writes nothing. The owner password is required;
pass the same path twice if you want one password for both slots. Run
'chmod 600' on any password file: this tool warns when one is readable by
group or other.

DESTINATIONS. -O writes the encrypted document to a new file; --in-place
overwrites the input. One of the two is required. --in-place keeps a .bak
sidecar of the ORIGINAL, which is unencrypted, so it additionally requires
either --no-backup (do not keep it) or -y (keep it, knowingly).

PERMISSIONS ARE ADVISORY. The permission bits are a request to the reader,
not a lock: only cooperating readers honour them, any reader that holds the
file may ignore every bit, and a reader that can display a page can extract
it. Encryption protects the content; the bits on their own protect nothing.
'accessibility' is always granted whatever you ask for -- PDF 2.0 deprecated
that bit and conforming readers always permit it.

--allow takes a comma-separated list, repeatable, from: print,
print-highres, copy, modify, annotate, forms, assemble, accessibility, plus
the exclusive 'all' and 'none'. Omitted means none (deny by default).
"""


def parse_allow(values: list[str] | None) -> frozenset[str]:
    """The eight-token vocabulary plus the two exclusive tokens. Exit 2 on anything else.

    Deny-by-default: an omitted ``--allow`` is the empty set, which is what
    ``none`` spells explicitly. An unknown token is quoted back with the full
    vocabulary — the token is the user's own word and is not a secret.
    """
    if values is None:
        return frozenset()
    tokens = [token.strip() for value in values for token in value.split(",") if token.strip()]
    if not tokens:
        raise UsageError("--allow needs at least one token; the vocabulary is: " + _vocabulary())

    unknown = [t for t in tokens if t not in PERMISSION_TOKENS and t not in (_ALL, _NONE)]
    if unknown:
        raise UsageError(
            f"--allow: unknown token {unknown[0]!r}; the vocabulary is: {_vocabulary()}"
        )

    exclusive = {t for t in tokens if t in (_ALL, _NONE)}
    if exclusive and set(tokens) - exclusive:
        raise UsageError(
            f"--allow: {sorted(exclusive)[0]!r} is exclusive and cannot be combined with "
            "other tokens"
        )
    if exclusive == {_ALL, _NONE}:
        raise UsageError("--allow: 'all' and 'none' are mutually exclusive")
    if exclusive == {_ALL}:
        return frozenset(PERMISSION_TOKENS)
    if exclusive == {_NONE}:
        return frozenset()
    return frozenset(tokens)


def _vocabulary() -> str:
    return ", ".join([*PERMISSION_TOKENS, _ALL, _NONE])


def plaintext_backup_refusal(
    *, in_place: bool, backup: bool, assume_yes: bool
) -> RefusedError | None:
    """AC14 — the one place the safety default and the security default disagree.

    `PLAN.md` §5.3's non-TTY posture says a single-input run never prompts and
    never refuses **on the bulk-destructive ground**. This is a different
    ground: PDF-04's sidecar is a copy of the *original*, so ``encrypt
    --in-place`` leaves plaintext sitting beside the ciphertext, silently,
    forever. So it refuses unless the operator names which outcome they want.

    Returned rather than raised: ``ops/crypto.py`` folds it into the same
    prediction the filesystem tier produces, so ``--dry-run`` predicts this
    refusal instead of promising a write that cannot happen (X-67).
    """
    if in_place and backup and not assume_yes:
        return RefusedError(
            "`encrypt --in-place` would leave an UNENCRYPTED copy at <name>.bak; "
            "pass --no-backup to keep no plaintext copy, or -y to keep it knowingly"
        )
    return None


def _reject_missing_sources(sources: list[Path]) -> None:
    for source in sources:
        if not source.exists():
            raise NoInputError("no such file", path=str(source))
        if source.is_dir():
            raise UsageError("expected a PDF file, not a directory", path=str(source))


@global_options(consumes=("--output", "--in-place"))
def encrypt_command(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(metavar="PDF", help="The PDF to encrypt.")],
    owner_password_file: Annotated[
        str | None,
        typer.Option(
            "--owner-password-file",
            help="Path to a file holding the owner password, or '-' for stdin. Required.",
            show_default=False,
        ),
    ] = None,
    user_password_file: Annotated[
        str | None,
        typer.Option(
            "--user-password-file",
            help="Path to a file holding the user (open) password, or '-' for stdin.",
            show_default=False,
        ),
    ] = None,
    allow: Annotated[
        list[str] | None,
        typer.Option(
            "--allow",
            help="Permission tokens to grant, comma-separated and repeatable. Advisory.",
            show_default=False,
        ),
    ] = None,
    legacy: Annotated[
        bool,
        typer.Option("--legacy", help="Use RC4-128 instead of AES-256. RC4-128 is broken."),
    ] = False,
) -> None:
    """Encrypt a PDF with AES-256 (RC4-128 only behind --legacy)."""
    config = get_config(ctx)
    logger = get_logger("cli.encrypt")

    granted = parse_allow(allow)
    reject_two_stdin_streams([owner_password_file, user_password_file])
    if owner_password_file is None and user_password_file is not None:
        raise UsageError(
            "encrypt requires an owner password: pass --owner-password-file PATH "
            "(the same path as --user-password-file if you want one password for both)"
        )

    owner = plan_password(
        slot="owner",
        flag="--owner-password-file",
        value=owner_password_file,
        env_names=(ENV_OWNER_PASSWORD,),
        prompt="Owner password: ",
        confirm_prompt="Owner password (again): ",
        allow_empty=False,
    )
    # The user slot is OPTIONAL, and the gate below is why it is not just
    # another `plan_password` call. An omitted optional flag with no
    # environment variable means "no user password" -- the document opens
    # without a prompt and carries the permission set -- NOT "prompt me". A
    # slot planned unconditionally would reach `plan_password`'s TTY tier and
    # prompt for a password nobody asked for, and on a non-TTY it would report
    # itself unresolvable and turn every plain `encrypt -O out.pdf` into a
    # predicted exit 6.
    user: PasswordSource | None = None
    if user_password_file is not None or ENV_PASSWORD in os.environ:
        user = plan_password(
            slot="user",
            flag="--user-password-file",
            value=user_password_file,
            env_names=(ENV_PASSWORD,),
            prompt="User password: ",
            allow_empty=True,
        )

    _reject_missing_sources([source])

    if allow is None:
        logger.warning(
            "no permissions granted (deny by default); pass --allow all to grant everything. "
            "Permission bits are advisory: only cooperating readers honour them, and "
            "%s is always granted whatever is requested",
            ", ".join(ALWAYS_GRANTED_TOKENS),
        )

    refusal: PdfToolkitError | None = plaintext_backup_refusal(
        in_place=config.in_place,
        backup=config.safety.backup,
        assume_yes=config.assume_yes,
    )

    result = encrypt_run(
        source,
        owner=owner,
        user=user,
        allow=granted,
        legacy=legacy,
        output=config.output,
        in_place=config.in_place,
        policy=config.safety,
        pre_refusal=refusal,
    )
    emit_result(result, config.output_format)
    raise typer.Exit(result.exit_code)


encrypt_command.__doc__ = _HELP
