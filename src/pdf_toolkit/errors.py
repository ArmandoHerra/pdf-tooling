"""The error hierarchy — one class per non-zero exit code.

Every error the tool raises deliberately is a :class:`PdfToolkitError`. The CLI
has exactly one handler for them; anything else reaching the top level is a bug
and prints a traceback.

``kind`` is the machine-readable name that appears in structured error output;
it is part of the same public contract as the exit code itself.
"""

from __future__ import annotations

import re
from typing import ClassVar, Final

from pdf_toolkit.cli.exit_codes import (
    AUTH,
    ENGINE_MISSING,
    FAILURE,
    NO_INPUT,
    REFUSED,
    USAGE,
)
from pdf_toolkit.secret import REDACTED

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
    "SourceUnreadableError",
    "TargetExistsError",
    "UsageError",
    "normalize_object_reprs",
]

#: PDF-36 half two — the CPython default repr, whose address half is
#: per-process noise: ``<_io.BytesIO object at 0x7bb18cbcbe70>``,
#: ``<function f at 0x...>``. Engines interpolate these into their own
#: exception text (libqpdf prefixes every ``Pdf.open`` failure with the stream
#: repr), and ``{error}`` then carries them into a message a user reads.
#:
#: NOT ``adapters.pikepdf_structure._WARNING_PREFIX_RE``, whose idiom this
#: borrows but whose CONSTANT cannot be reused: that one is ``^``-anchored
#: because it strips a whole *leading* prefix from ``Pdf.get_warnings()``
#: output, and by the time a repr reaches this module it is mid-string inside
#: a composed sentence. Anchoring here would silently match nothing.
_OBJECT_REPR_RE: Final = re.compile(r"<([^<>]*?) at 0x[0-9A-Fa-f]+>")


def normalize_object_reprs(message: str) -> str:
    """Collapse ``<X at 0xADDR>`` to ``<X>`` — the address, and only the address.

    `5bd9143f61`: four verbs rendered a live heap address into the message a
    user reads. `adapters/pikepdf_structure.py:61-66` had ALREADY written the
    argument for stripping it — *"the address is per-process noise, never a
    fact about the document"* — and then applied it to warnings only, leaving
    six sibling ``{error}`` interpolations on the error path uncleaned. This is
    the `B-101` → `B-106` shape: a proposition fixed on one carrier and left
    standing on its siblings.

    **Why it is not cosmetic.** `PDF-30`'s closure rule is that a documented
    figure must be *derived*, *gated by a run*, or *absent*. A message carrying
    ``0x70f73b1c7ec0`` can be none of the three: it cannot be quoted in
    `README.md` under that rule and it cannot be diffed between two runs,
    because it changes every process. These are the same message::

        ... stream <_io.BytesIO object at 0x7bb18cbcbe70>: unable to find trailer ...
        ... stream <_io.BytesIO object at 0x70c30c7cbf10>: unable to find trailer ...

    **The engine's own sentence survives byte-identical.** ``unable to find
    trailer dictionary while recovering damaged file`` is libqpdf's useful
    half and this function must never touch it — rewriting engine diagnostic
    wording is an explicit non-goal.

    **Non-suppression is a rule, not an accident.** Input matching no repr
    passes through UNCHANGED. A sanitizer that silently empties a message it
    did not recognise is a wrong answer carrying a success exit code, and it is
    pinned by a test that makes the empty-on-no-match variant fail.
    """
    return _OBJECT_REPR_RE.sub(r"<\1>", message)


class PdfToolkitError(Exception):
    """Base of every deliberate error.

    Args:
        message: Human-readable, already safe to print.
        path: The filesystem path the error is about, when there is one.
        redacted: Set when the message was built from a value that must never
            be echoed verbatim. Honoured at the single :meth:`to_dict`
            chokepoint (B-068) rather than by each renderer or each call
            site, so the password work registers secrets by construction
            instead of retrofitting a redaction path around a live
            credential after the fact.
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
        """The structured error payload. The only thing a renderer consumes.

        ``redacted`` is honoured HERE, not by each call site (B-068): a
        refusal built with ``redacted=True`` and a populated ``path`` renders
        ``path`` as :data:`pdf_toolkit.secret.REDACTED` rather than the value
        itself, so a future password-bearing flag that (mistakenly) passes
        ``path=value`` alongside ``redacted=True`` cannot leak through this
        envelope the way ``--password-file``'s did. Every renderer
        (``render_error_json`` -- which serves ``-o json`` *and* ``-o
        ndjson`` -- and ``render_error_table``) consumes this method's
        output and nothing else, so one change here covers every output
        shape uniformly.

        A caller that passes no ``path`` at all -- the convention every
        never-echo constructor in this codebase already follows -- is
        unaffected: ``path`` stays ``None``, exactly as before.

        **PDF-36 extends this seam rather than inventing one.** ``message`` is
        normalized through :func:`normalize_object_reprs` HERE, for the same
        reason ``redacted`` is honoured here (`B-068`): thirty ``{error}``
        interpolations live under ``src/`` and sanitizing at the call sites is
        a thirty-site pass that a thirty-first reintroduces. This method is the
        only thing every renderer consumes, so one change covers ``-o table``,
        ``-o json`` and ``-o ndjson`` uniformly *and* covers every call site
        that does not exist yet.

        The KEY SET IS UNCHANGED -- ``{code, kind, message, path}``, and
        ``schema_version`` stays 1 (`X-410`'s pre-`v1.0.0` freeze). What
        changed is the CONTENT of one string, never the shape around it.
        """
        path: object = self.path
        if self.redacted and path is not None:
            path = REDACTED
        return {
            "code": self.exit_code,
            "kind": self.kind,
            "message": normalize_object_reprs(self.message),
            "path": path,
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


class SourceUnreadableError(FailureError):
    """Exit 1 — the input exists but its contents cannot be read.

    The exact mirror of :class:`DestinationUnwritableError` above, with one
    noun changed: nothing declined on safety grounds, the filesystem simply
    will not hand over the bytes. An operand that exists but cannot be read is
    **an operation that ran and failed**, not a mistyped command line, so it is
    exit 1 and never exit 2 (PDF-26 §D5).

    Additive by construction, like every class in this block: a subclass of
    :class:`FailureError`, so it introduces no new integer and inherits
    ``kind: "failure"``. ``cli/exit_codes.py`` is unchanged by its arrival.

    The line it draws, and the reason the line is drawn *here* rather than
    remembered: an unreadable ``--password-file`` value stays a
    :class:`UsageError` (exit 2, value never echoed — B-068). That flag takes a
    path to a file *holding a password*, so "not a readable file" is a
    statement about the flag's value rather than about a file the run tried to
    process, and a message naming it could not name the value without printing
    a credential. This class is for operands only.
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
