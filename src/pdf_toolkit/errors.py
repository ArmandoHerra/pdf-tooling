"""The error hierarchy — one class per non-zero exit code.

Every error the tool raises deliberately is a :class:`PdfToolkitError`. The CLI
has exactly one handler for them; anything else reaching the top level is a bug
and prints a traceback.

``kind`` is the machine-readable name that appears in structured error output;
it is part of the same public contract as the exit code itself.
"""

from __future__ import annotations

from typing import ClassVar

from pdf_toolkit.cli.exit_codes import (
    AUTH,
    ENGINE_MISSING,
    FAILURE,
    NO_INPUT,
    REFUSED,
    USAGE,
)

__all__ = [
    "AuthError",
    "BackupExistsError",
    "BackupWithoutInPlaceError",
    "ConfirmationDeclinedError",
    "ConfirmationRequiredError",
    "DestinationUnwritableError",
    "EngineMissingError",
    "FailureError",
    "NoInputError",
    "OutputCollisionError",
    "OutputEscapesDirError",
    "PageRangeError",
    "PdfToolkitError",
    "RefusedError",
    "TargetExistsError",
    "UsageError",
]


class PdfToolkitError(Exception):
    """Base of every deliberate error.

    Args:
        message: Human-readable, already safe to print.
        path: The filesystem path the error is about, when there is one.
        redacted: Set when the message was built from a value that must never
            be echoed verbatim. Renderers honour it from the first commit so
            that the password work can register secrets rather than retrofit a
            redaction path around a live credential.
    """

    exit_code: ClassVar[int] = FAILURE
    kind: ClassVar[str] = "failure"

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        redacted: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.path = path
        self.redacted = redacted

    def to_dict(self) -> dict[str, object]:
        """The structured error payload. The only thing a renderer consumes."""
        return {
            "code": self.exit_code,
            "kind": self.kind,
            "message": self.message,
            "path": self.path,
        }


class FailureError(PdfToolkitError):
    """Exit 1 — the operation ran and failed."""

    exit_code: ClassVar[int] = FAILURE
    kind: ClassVar[str] = "failure"


class UsageError(PdfToolkitError):
    """Exit 2 — bad invocation.

    Deliberately *our* class and never Click's: ``UsageError`` must be
    unambiguous at every call site inside this package.
    """

    exit_code: ClassVar[int] = USAGE
    kind: ClassVar[str] = "usage"


class PageRangeError(UsageError):
    """Exit 2 — a page-range spec is malformed, out of range, or otherwise
    cannot be resolved against a page count.

    Raised only by ``pdf_toolkit.ops.pagerange.parse``. Carries the offending
    ``token`` and its 1-based ``column`` in the original ``spec`` string, plus
    a short machine-readable ``reason``, so a caller can build a precise
    diagnostic without re-parsing the message. An empty-but-valid selection is
    *not* this error (``PLAN.md`` §4.3) — it is a normal ``PageRange`` whose
    ``is_empty`` is ``True``.
    """

    def __init__(
        self,
        message: str,
        *,
        spec: str,
        token: str,
        column: int,
        reason: str,
        path: str | None = None,
    ) -> None:
        super().__init__(message, path=path)
        self.spec = spec
        self.token = token
        self.column = column
        self.reason = reason


class EngineMissingError(PdfToolkitError):
    """Exit 3 — a required engine or binary is unavailable.

    The message must always carry the install hint.
    """

    exit_code: ClassVar[int] = ENGINE_MISSING
    kind: ClassVar[str] = "engine_missing"


class NoInputError(PdfToolkitError):
    """Exit 4 — valid invocation, nothing to act on."""

    exit_code: ClassVar[int] = NO_INPUT
    kind: ClassVar[str] = "no_input"


class RefusedError(PdfToolkitError):
    """Exit 5 — a safety gate declined."""

    exit_code: ClassVar[int] = REFUSED
    kind: ClassVar[str] = "refused"


class AuthError(PdfToolkitError):
    """Exit 6 — password required, incorrect, or of the wrong kind."""

    exit_code: ClassVar[int] = AUTH
    kind: ClassVar[str] = "auth"


# --- The safety spine's own codes (PLAN.md §5.6, PDF-04 Design §D8) ---------
# Additive by construction: every class below is a subclass of one that already
# existed, so it inherits an exit code that is already public API rather than
# introducing a new integer. The *family* (``kind``) is inherited too — a
# machine consumer keys off ``code``/``kind``, and the specific class is for
# call sites and tests.


class BackupWithoutInPlaceError(UsageError):
    """Exit 2 — ``--no-backup`` was passed without ``--in-place``.

    A usage error and not a safety refusal: the pair is mutually exclusive at
    parse time, in the same family as ``--quiet``/``--verbose``, and nothing has
    been attempted yet. Raised by ``SafetyPolicy.validate()``, which is the one
    owner of the rule.
    """


class DestinationUnwritableError(FailureError):
    """Exit 1 — the destination directory is missing or not writable.

    Deliberately *not* a refusal: nothing declined on safety grounds, the
    filesystem simply cannot accept the write. Raised at plan time so it lands
    before an engine runs rather than after one produced bytes with nowhere to
    put them.
    """


class TargetExistsError(RefusedError):
    """Exit 5 — the output exists and ``--force`` was not given."""


class OutputCollisionError(RefusedError):
    """Exit 5 — two planned outputs resolve to one destination.

    Detected across the whole planned output set before the first write, so a
    200-file batch refuses at item 0 rather than at item 137.
    """


class BackupExistsError(RefusedError):
    """Exit 5 — the ``.bak`` sidecar exists and ``--force`` was not given."""


class OutputEscapesDirError(RefusedError):
    """Exit 5 — a resolved destination lands outside its ``--out-dir``.

    The split is deliberate and it is the one thing to read before adding a
    template-expansion path: a *statically malformed* ``--name`` (a path
    separator, or ``..`` in the template itself) is a bad invocation and stays
    exit 2, raised by the CLI layer. A destination that only escapes **after**
    substitution — a ``{stem}`` carrying ``../``, say — is discovered at plan
    time from *data*, not from the invocation, so it is a safety gate declining
    over a resolved path and is exit 5, in the same family as no-clobber and
    collision.
    """


class ConfirmationRequiredError(RefusedError):
    """Exit 5 — a bulk destructive run on a non-TTY without ``-y``.

    Never a prompt and never a block on stdin: on a non-terminal the answer is
    a refusal, immediately.
    """


class ConfirmationDeclinedError(RefusedError):
    """Exit 5 — the interactive confirmation prompt was answered no."""
