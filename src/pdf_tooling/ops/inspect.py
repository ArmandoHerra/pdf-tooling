"""``info`` — assemble a :class:`DocumentInfo` per input. **Writes nothing.**

This is the first real read verb and the first consumer of the port seam. It is
also, deliberately, a **non**-consumer of the write path: nothing in this module
or in ``cli/cmd_info.py`` constructs an ``AtomicWriter`` or performs a
filesystem mutation of any kind, which is why its ``--dry-run`` purity is
trivially provable. PDF-04's write-chokepoint AST walk asserts that globally;
``tests/test_info.py`` pins it directly with a before/after filesystem snapshot
anyway, because *provable* and *proven* are different words.

Framework-free, per L2: no ``typer``, no ``click``, no ``sys.exit``, no
printing. Errors are raised as :class:`~pdf_tooling.errors.PdfToolkitError`
subclasses and the CLI maps them to exit codes.

THE EXIT-CODE CONTRACT ANOTHER SPEC DEPENDS ON
----------------------------------------------
A malformed or unparseable PDF is exit **1**, never 2 and never 4. The repair
work's acceptance signal is *"``repair`` yields a file ``info`` can read (it
exits 1 before the fix)"*, so that code is load-bearing for a spec that has not
been written yet.

WHAT IS DELIBERATELY ABSENT
---------------------------
* ``--pages`` — ``info`` is page-range aware in ``PLAN.md`` §4.1, but the
  page-range grammar's first consumer is the extract work, which depends on it.
  ``--pages-detail`` is a different flag (a boolean) and *is* implemented.
* ``--recursive`` and directory expansion — that needs ``ops/discovery.py``,
  which no roster row claims. A directory operand is exit **2** with a message
  saying a PDF file was expected; it becomes exit 4 when discovery lands.
* Password input — ``PLAN.md`` §5.7's whole resolution chain belongs to the
  crypto work. This module tries the *empty* user password once, which is what
  makes the common owner-password-only document readable, and exits **6** when a
  real user password is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdf_tooling.errors import PdfToolkitError, UsageError
from pdf_tooling.models import DocumentInfo
from pdf_tooling.ops.batch import ITEM_SCOPED_ERRORS, preflight_operands
from pdf_tooling.ops.document_password import NO_PASSWORD, PasswordResolver, PasswordSource
from pdf_tooling.ports.structure import require_linearization, require_structure
from pdf_tooling.safety.paths import classify_operand
from pdf_tooling.secret import Secret

__all__ = ["InspectionOutcome", "inspect_document", "inspect_paths", "validate_operands"]

#: The directory refusal's exact wording (PDF-51 AC7). Named once so
#: `validate_operands`' own whole-batch loop and its `preflight_operands` call
#: below cannot come to disagree about it -- the second occurrence exists only
#: so a directory created between the two passes (TOCTOU) still refuses with
#: the same message rather than `ops/batch.py`'s shorter default.
_DIRECTORY_MESSAGE = (
    "expected a PDF file, not a directory; directory expansion "
    "(--recursive) is not part of this version"
)


@dataclass(frozen=True, slots=True)
class InspectionOutcome:
    """One input's result: the report, or the error that replaced it.

    Modelled as an outcome rather than as "raise on the first failure" because
    ``info`` accepts several inputs and a batch that abandons the remaining
    files at the first bad one is less useful than one that reports on all of
    them and says which failed.
    """

    path: str
    info: DocumentInfo | None
    error: PdfToolkitError | None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def exit_code(self) -> int:
        return 0 if self.error is None else self.error.exit_code

    def to_dict(self) -> dict[str, Any]:
        """The payload entry. Mirrors ``PLAN.md`` §5.6's error shape on failure."""
        if self.info is not None:
            return {**self.info.to_dict(), "ok": True}
        error = self.error
        payload: dict[str, Any] = {"path": self.path, "ok": False}
        if error is not None:
            payload["error"] = {
                "code": error.exit_code,
                "kind": error.kind,
                "message": error.message,
            }
        return payload


def validate_operands(paths: tuple[Path, ...]) -> None:
    """Reject invocations, before any input is opened. Every failure is exit 2
    or exit 4 -- both run-scoped, neither a per-document row.

    Two rungs, deliberately in two passes rather than one interleaved loop.

    **Rung 2 (directory) runs first, over ALL operands, unconditionally** --
    exactly as it always has. It is a property of *how the command was typed*,
    not of what a file turned out to contain, and a pre-flight refusal means a
    twelve-file batch does not process eleven files before rejecting the
    twelfth. Running it to completion before rung 1 is what keeps
    ``info <missing> <directory>`` and ``info <directory> <missing>`` BOTH
    exiting 2 -- the directory rung wins regardless of position, and PDF-51
    does not redesign that (D1.2); the siblings' positional ladder, where
    whichever rung is hit first at a given operand wins, is not adopted here.

    **Rung 1 (existence) is PDF-51's addition.** A nonexistent operand is now
    rejected here, exactly as it is on the other twenty-two ``takes_input_paths``
    verbs, rather than surviving into :func:`inspect_paths`' per-item guard and
    being demoted into a per-document row. Reached through
    :func:`~pdf_tooling.ops.batch.preflight_operands` -- :func:`classify_operand`
    with rung 4 (existing but unreadable) deferred to the per-item path, which is
    PDF-26's survival half and is unchanged -- rather than by restating
    ``Path.exists()`` inline: restating the ladder is how twenty-three per-verb
    copies of it came to exist (``ops/batch.py:42-45``). Because rung 2 already
    ran to completion above, this second pass's own directory check can no
    longer fire on a genuine directory operand; ``directory_message`` is still
    passed so a TOCTOU directory (created between the two passes) refuses with
    this verb's own wording rather than the shorter default.
    """
    if not paths:
        raise UsageError("info needs at least one PDF file")
    for path in paths:
        if path.is_dir():
            raise UsageError(_DIRECTORY_MESSAGE, path=str(path))
    preflight_operands(paths, directory_message=_DIRECTORY_MESSAGE)


def inspect_document(
    path: Path, *, fonts: bool = False, pages: bool = False, password: Secret | None = None
) -> DocumentInfo:
    """Report on one document.

    ``linearized`` comes from whichever adapter declares the ``linearized``
    capability — selected through the registry, never by naming an adapter. If
    no adapter can answer it, that is exit **3** with an install hint rather
    than a ``false`` this product cannot stand behind: ``DocumentInfo``'s field
    is a ``bool``, so "we could not tell" has no honest encoding in it.

    Args:
        password: PDF-37 -- a resolved secret, tried when the empty password
            does not open the document, or ``None``. Resolved by the caller
            (`inspect_paths`) only once ``read_encryption`` has already
            confirmed the input is actually encrypted
            (`ops/document_password.py`).

    Raises:
        NoInputError: Exit 4 — the path does not exist.
        UsageError: Exit 2 — the path is a directory, or not a regular file.
        SourceUnreadableError: Exit 1 — the path exists and cannot be read.
        AuthError: Exit 6 — no password was supplied and one is required, or
            the supplied password did not unlock the document.
        FailureError: Exit 1 — malformed, corrupt or unparseable.
        EngineMissingError: Exit 3 — a required engine is unavailable.

    :func:`~pdf_tooling.safety.paths.classify_operand` is called again HERE,
    on the per-item path inside :func:`inspect_paths`' own guard, as a TOCTOU
    belt rather than as rung 1-3's primary check (PDF-51 D1/D2): those three
    rungs are run-scoped and already rejected by :func:`validate_operands`'
    pre-flight, so reaching them here means an operand changed underneath the
    run between the two calls, and the per-item guard now lets that escape
    rather than swallowing it into a per-document row -- which is what makes
    the boundary hold rather than merely usually hold. **Only rung 4
    (existing-but-unreadable, raised as :class:`SourceUnreadableError`) is
    genuinely per-item here.** That placement is the survival half of PDF-26:
    readability is a property of a file, so one unreadable input must not cost
    the other inputs their reports.
    """
    classify_operand(path)
    if not path.is_file():
        raise UsageError("expected a regular file", path=str(path))

    linearized = require_linearization().is_linearized(path)
    engine = require_structure()
    return engine.read_document_info(
        path, fonts=fonts, pages=pages, linearized=linearized, password=password
    )


def inspect_paths(
    paths: tuple[Path, ...],
    *,
    fonts: bool = False,
    pages: bool = False,
    password: PasswordSource = NO_PASSWORD,
) -> tuple[InspectionOutcome, ...]:
    """Report on every input, in input order, without abandoning the batch.

    Inputs are processed **sequentially**. ``--threads`` exists in the global
    block but parallel execution belongs to the spec that introduces the
    executor; deterministic input order is the contract either way, so doing it
    serially now costs nothing a later change cannot recover.

    **Only `ops.batch.ITEM_SCOPED_ERRORS` is caught here (PDF-51 D2)** --
    imported, never re-declared, so this guard cannot come to disagree with
    `ops/batch.py`'s own AST-asserted one about what is a per-input verdict.
    A `PdfToolkitError` outside that tuple -- a `NoInputError`/`UsageError`
    surviving `validate_operands`' pre-flight only via a TOCTOU race, or an
    `EngineMissingError` from `require_linearization()`/`require_structure()`
    -- is run-scoped and is **not** caught here: it propagates, aborts the
    whole batch, and is handled by `cli/main.py`'s one
    `except PdfToolkitError` -- the run-scoped error envelope, not a demoted
    row. Anything that is not a `PdfToolkitError` at all is a genuine bug and
    is allowed to reach the top level as a traceback, which is a signal rather
    than a UX.

    PDF-37: the global ``--password-file`` slot is resolved at most once
    across the whole batch, and only for an input that turns out to be
    encrypted (`ops/document_password.PasswordResolver`).
    """
    resolver = PasswordResolver(password)
    outcomes: list[InspectionOutcome] = []
    try:
        for path in paths:
            try:
                secret = resolver.for_source(path) if path.is_file() else None
                info = inspect_document(path, fonts=fonts, pages=pages, password=secret)
            except ITEM_SCOPED_ERRORS as error:
                outcomes.append(InspectionOutcome(path=str(path), info=None, error=error))
            else:
                outcomes.append(InspectionOutcome(path=str(path), info=info, error=None))
    finally:
        resolver.clear()
    return tuple(outcomes)
