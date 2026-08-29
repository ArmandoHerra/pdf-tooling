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
    "EngineMissingError",
    "FailureError",
    "NoInputError",
    "PdfToolkitError",
    "RefusedError",
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
