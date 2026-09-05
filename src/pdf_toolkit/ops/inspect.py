"""``info`` — assemble a :class:`DocumentInfo` per input. **Writes nothing.**

This is the first real read verb and the first consumer of the port seam. It is
also, deliberately, a **non**-consumer of the write path: nothing in this module
or in ``cli/cmd_info.py`` constructs an ``AtomicWriter`` or performs a
filesystem mutation of any kind, which is why its ``--dry-run`` purity is
trivially provable. PDF-04's write-chokepoint AST walk asserts that globally;
``tests/test_info.py`` pins it directly with a before/after filesystem snapshot
anyway, because *provable* and *proven* are different words.

Framework-free, per L2: no ``typer``, no ``click``, no ``sys.exit``, no
printing. Errors are raised as :class:`~pdf_toolkit.errors.PdfToolkitError`
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

from pdf_toolkit.errors import PdfToolkitError, UsageError
from pdf_toolkit.models import DocumentInfo
from pdf_toolkit.ops.document_password import NO_PASSWORD, PasswordResolver, PasswordSource
from pdf_toolkit.ports.structure import require_linearization, require_structure
from pdf_toolkit.safety.paths import classify_operand
from pdf_toolkit.secret import Secret

__all__ = ["InspectionOutcome", "inspect_document", "inspect_paths", "validate_operands"]


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
    """Reject invocations, before any input is opened. Every failure is exit 2.

    A directory is checked here rather than per item on purpose: it is a
    property of *how the command was typed*, not of what the file turned out to
    contain, and a pre-flight refusal means a twelve-file batch does not process
    eleven files before rejecting the twelfth.
    """
    if not paths:
        raise UsageError("info needs at least one PDF file")
    for path in paths:
        if path.is_dir():
            raise UsageError(
                "expected a PDF file, not a directory; directory expansion "
                "(--recursive) is not part of this version",
                path=str(path),
            )


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

    The first four are :func:`~pdf_toolkit.safety.paths.classify_operand`'s
    ladder, in its fixed precedence order, called HERE — on the per-item path
    inside :func:`inspect_paths`' own ``except PdfToolkitError`` — rather than
    in :func:`validate_operands`, which aborts the whole batch pre-flight.
    That placement is the survival half of PDF-26: readability is a property of
    a file, so one unreadable input must not cost the other inputs their
    reports.
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

    Only :class:`PdfToolkitError` is caught. Anything else is a bug and is
    allowed to reach the top level as a traceback, which is a signal rather
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
            except PdfToolkitError as error:
                outcomes.append(InspectionOutcome(path=str(path), info=None, error=error))
            else:
                outcomes.append(InspectionOutcome(path=str(path), info=info, error=None))
    finally:
        resolver.clear()
    return tuple(outcomes)
