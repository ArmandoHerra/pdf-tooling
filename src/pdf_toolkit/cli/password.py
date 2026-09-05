"""Password resolution — `PLAN.md` §5.7's chain, and the never-echo rule.

Lives in **L1** because reading a file, an environment variable and a TTY is
CLI work: ``ops/`` stays a pure function of its arguments (§5.2), so what
crosses the boundary is a
:class:`~pdf_toolkit.ops.document_password.PasswordSource` — a safe-to-log
*source label* plus a thunk — never a value and never an environment.

Resolution order, first hit wins (`PLAN.md` §5.7):

======  ==========================================  =========================
Order   Source                                      Label recorded in the plan
======  ==========================================  =========================
1       ``--*-password-file PATH``                  ``file:<path>``
1       ``--*-password-file -``                     ``stdin``
2       ``PDF_TOOLKIT_PASSWORD`` /                  ``env:<NAME>``
        ``PDF_TOOLKIT_OWNER_PASSWORD``
3       ``getpass`` prompt, written to **stderr**   ``prompt``
4       nothing left                                exit **6**
======  ==========================================  =========================

**A password is NEVER accepted as a command-line value** (`PLAN.md` §4.2,
ruling OR-4). ``argv`` is world-readable in ``/proc`` and lands in shell
history, so the harm happens *before* the tool could refuse — which is why
the inviting spelling was removed rather than merely rejected. See
``cli/common.py``'s refusing options.

The never-echo rule, and why it is not obvious
----------------------------------------------
When a ``--*-password-file`` value does not resolve to a readable file and is
not ``-``, **we cannot tell a typo'd path from a literal password**. The
conventional ``no such file: hunter2`` message would print the password to
stderr and into every CI log that captured it. So the error names the *flag*
and never the value — and deliberately does not populate the error
envelope's ``path=`` field either, because that field is rendered.

A value that *does* resolve to a readable file may be echoed as a path: it is
useful, and a path that exists is not a secret.

**The length is never logged.** It is a real, if small, leak, and a "password
must be at least N characters" style diagnostic is how it gets logged by
accident.

``input(`` appears nowhere in this module — only :func:`getpass.getpass`,
which is what keeps a prompted password off the terminal echo. AC2 asserts
that as a grep.
"""

from __future__ import annotations

import functools
import getpass
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from pdf_toolkit.cli.common import not_a_readable_file
from pdf_toolkit.errors import AuthError, UsageError
from pdf_toolkit.ops.document_password import PasswordSource
from pdf_toolkit.output.logging import get_logger
from pdf_toolkit.secret import Secret

__all__ = [
    "ENV_OWNER_PASSWORD",
    "ENV_PASSWORD",
    "STDIN_SPELLING",
    "plan_password",
    "reject_two_stdin_streams",
]

#: The two environment variables `PLAN.md` §5.7 names. Consulted for
#: *presence* when planning and for *value* only when actually reading, which
#: is what lets ``--dry-run`` predict exit 6 without a secret entering the
#: process.
ENV_PASSWORD: Final[str] = "PDF_TOOLKIT_PASSWORD"
ENV_OWNER_PASSWORD: Final[str] = "PDF_TOOLKIT_OWNER_PASSWORD"

STDIN_SPELLING: Final[str] = "-"

#: Modes granting group or other read. `chmod 600` is recommended, never
#: enforced: refusing to read a 0644 password file would break more scripts
#: than it protects, and the warning is the honest middle.
_LOOSE_MODE_MASK: Final[int] = 0o077

# `not_a_readable_file` -- the never-echo error every password-bearing flag's
# shape refusal builds -- is imported from `cli.common` above, not defined
# here (B-068). It WAS defined in this module until `--password-file`'s own
# refusal (in `cli/common.py`, the shared option layer every verb goes
# through) needed the same constructor: `cli.common` importing THIS module
# would have made `pdf_toolkit.safety.atomic.AtomicWriter` transitively
# reachable (via this module's own `ops.document_password` import) from
# every verb's callback module, silently reclassifying `doctor`/`info`/
# `version` as "mutating" for `tests/registry.py::is_mutating`'s static AST
# reachability scan -- see `cli/common.py`'s own docstring on the function for the full
# account. PDF-37 hit the SAME defect via a DIFFERENT path (this module's
# `PasswordSource` import used to resolve to `ops.crypto`, which legitimately
# reaches `AtomicWriter`) and closed it the same way: the type now lives in
# `ops/document_password.py`, which does not.


def reject_two_stdin_streams(values: Sequence[str | None]) -> None:
    """Exit 2 — one stdin stream cannot supply two passwords."""
    if sum(1 for value in values if value == STDIN_SPELLING) > 1:
        raise UsageError(
            "only one password may be read from stdin: '-' was given for more than one slot"
        )


def _stdin_is_a_tty() -> bool:
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, ValueError):  # pragma: no cover - closed/replaced stream
        return False


def _first_line(raw: bytes) -> bytes:
    """The first line, with a single trailing newline stripped and nothing else.

    A password may legitimately end in a space, so no other whitespace is
    touched. ``\\r\\n`` is stripped as one unit so a file written on Windows
    does not silently carry a ``\\r`` into the key derivation.
    """
    line, _, _ = raw.partition(b"\n")
    if line.endswith(b"\r"):
        line = line[:-1]
    return line


def _warn_on_mode(path: Path, slot: str) -> None:
    logger = get_logger("cli.password")
    try:
        mode = path.stat().st_mode
    except OSError:  # pragma: no cover - it was readable a line ago
        return
    if mode & _LOOSE_MODE_MASK:
        logger.warning(
            "%s: readable by group or other (mode %o); run 'chmod 600 %s'",
            path,
            mode & 0o777,
            path,
        )
    del slot


def _read_file(path_text: str, *, flag: str, slot: str, allow_empty: bool) -> Secret:
    path = Path(path_text)
    logger = get_logger("cli.password")
    try:
        raw = path.read_bytes()
    except OSError as error:
        # It existed when the plan was built; something changed underneath.
        raise AuthError(f"{flag}: could not read the password file ({error.strerror})") from error
    _warn_on_mode(path, slot)
    if b"\n" in raw.rstrip(b"\n"):
        logger.warning("%s: more than one line; using the first", path)
    value = _first_line(raw)
    if not value and not allow_empty:
        raise UsageError(
            f"{flag}: the password file is empty, which would make the encryption meaningless",
            path=path_text,
        )
    return Secret(value, source=f"file:{path_text}")


def _read_stdin(*, flag: str, allow_empty: bool) -> Secret:
    try:
        raw = sys.stdin.buffer.readline()
    except (AttributeError, ValueError, OSError) as error:
        raise AuthError(f"{flag}: '-' was given but stdin could not be read") from error
    value = _first_line(raw)
    if not value and not allow_empty:
        raise UsageError(
            f"{flag}: the password read from stdin is empty, "
            "which would make the encryption meaningless"
        )
    return Secret(value, source="stdin")


def _read_env(name: str, *, allow_empty: bool) -> Secret:
    value = os.environ.get(name, "")
    if not value and not allow_empty:
        raise UsageError(
            f"{name} is set but empty, which would make the encryption meaningless",
        )
    return Secret(value, source=f"env:{name}")


def _read_prompt(*, prompt: str, confirm_prompt: str | None, allow_empty: bool) -> Secret:
    first = getpass.getpass(prompt, stream=sys.stderr)
    if confirm_prompt is not None:
        second = getpass.getpass(confirm_prompt, stream=sys.stderr)
        if first != second:
            raise UsageError("the two passwords did not match")
    if not first and not allow_empty:
        raise UsageError("an empty password would make the encryption meaningless")
    return Secret(first, source="prompt")


def plan_password(
    *,
    slot: str,
    flag: str,
    value: str | None,
    env_names: Sequence[str],
    prompt: str,
    confirm_prompt: str | None = None,
    allow_empty: bool = True,
) -> PasswordSource:
    """Plan one password slot **without reading anything**.

    The whole point of this function is what it does *not* do: it never opens
    the file, never reads the environment variable's value, and never
    prompts. It answers "could a password be produced, and from where" from
    *existence alone* — which is what makes ``--dry-run``'s exit-6
    resolvability prediction possible without a secret entering the process
    (this spec's exit-6 oracle split).

    Args:
        slot: ``"owner"`` | ``"user"`` | ``"password"``.
        flag: The flag spelling to name in an error. Never the value.
        value: What the flag was given, or ``None`` when it was not given.
        env_names: Environment variables to consult, in order, for presence.
        prompt: The ``getpass`` prompt, written to stderr.
        confirm_prompt: When set, the prompt is asked twice and a mismatch is
            exit 2 (`encrypt`'s owner password).
        allow_empty: ``False`` for `encrypt`'s owner slot — an empty owner
            password makes the encryption meaningless, so it is exit 2.

    Raises:
        UsageError: Exit 2 — the value is neither ``-`` nor a readable file.
    """
    if value is not None:
        if value == STDIN_SPELLING:
            return _slot(slot, "stdin", _read_stdin, flag=flag, allow_empty=allow_empty)
        if not Path(value).is_file():
            raise not_a_readable_file(flag)
        return _slot(
            slot,
            f"file:{value}",
            _read_file,
            value,
            flag=flag,
            slot=slot,
            allow_empty=allow_empty,
        )

    for name in env_names:
        # PRESENCE only. `os.environ[name]` is never evaluated here.
        if name in os.environ:
            return _slot(slot, f"env:{name}", _read_env, name, allow_empty=allow_empty)

    if _stdin_is_a_tty():
        return _slot(
            slot,
            "prompt",
            _read_prompt,
            prompt=prompt,
            confirm_prompt=confirm_prompt,
            allow_empty=allow_empty,
        )

    return PasswordSource(slot=slot, source=None, read=None)


def _slot(
    slot_name: str,
    source: str,
    reader: Callable[..., Secret],
    *args: object,
    **kwargs: object,
) -> PasswordSource:
    """One planned slot whose thunk reads, then logs its SOURCE."""
    return PasswordSource(
        slot=slot_name,
        source=source,
        read=functools.partial(_resolved, slot_name, functools.partial(reader, *args, **kwargs)),
    )


def _resolved(slot: str, reader: Callable[[], Secret]) -> Secret:
    """Read, then log the SOURCE at DEBUG. Never the value, never its length.

    The record exists so AC4's grep cannot pass because logging was silently
    off: a `-vv` run must produce a real record on the same code path the
    value travels.
    """
    secret = reader()
    get_logger("cli.password").debug("password resolved from %s (slot: %s)", secret.source, slot)
    return secret
