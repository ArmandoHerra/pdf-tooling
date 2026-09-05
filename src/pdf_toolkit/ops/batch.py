"""The ONE per-item continuation guard for the ``--out-dir`` batch class.

``PLAN.md`` §5.4's Failure policy — *by default a failing input is recorded and
the run continues (exit 1 at the end, with a per-input status in the structured
output)* — is quoted verbatim in shipped source at ``cli/cmd_info.py``, and
before this module it was true of exactly one verb. ``ops/inspect.py`` continues
past a bad input because its operand classification happens **per item, inside
the loop's own guard**; every ``--out-dir`` batch verb classified **per batch,
outside** any guard, so one bad input cost every other input its result — and,
on the verbs that write before they fail, produced a payload that denied an
artifact already on disk.

**Written once, deliberately.** The precedent is in this repository and is
explicit about why: ``cli/common.py``'s ``operand_argument()`` records that the
same decision *"was wrong twenty-three times in a row and the mechanism that
made it wrong was a default"*. Six ops modules times two failure kinds is that
same arithmetic, so the guard, the failure item's shape and the run/item
boundary all live here rather than being re-decided per module.

The run/item boundary
---------------------

:func:`~pdf_toolkit.safety.paths.classify_operand`'s ladder owns four rungs, and
they do **not** all belong to the same scope::

    1. does not exist        -> NoInputError           4   RUN-scoped
    2. is a directory        -> UsageError             2   RUN-scoped
    3. is not a regular file -> UsageError             2   RUN-scoped
    4. exists, unreadable    -> SourceUnreadableError  1   ITEM-scoped

Rungs 1-3 are properties of **how the command line was typed**, not of what a
file turned out to contain, and both carry precedence guarantees that predate
this module: ``ops/pages.py``'s exit-4 contract *"wins over any other usage
error"*, and ``ops/inspect.py`` states the directory rule's reason — a refusal
there means *"a twelve-file batch does not process eleven files before rejecting
the twelfth."* So they stay pre-flight, in :func:`preflight_operands`.

Rung 4 is a property of **one file**, so it is deferred to the per-item guard,
which is the whole of the unreadable half of this fix: an unreadable input in
position 2 must cost position 2 its result and nothing else.

:func:`defer_unreadable` gets that split by **calling the one classifier and
dropping only rung 4**, rather than restating rungs 1-3 inline. Restating them
is how twenty-three per-verb ladders came to exist; the classifier stays the
single source of truth for what each rung means.

Ordering
--------

``PLAN.md`` §5.4 bullet 3 — *"Output ordering is deterministic regardless of
``--threads``. Results are collected into a slot-indexed list and rendered in
input order."* — is a property of the **collection**, not of the guard, so
:class:`BatchLedger` owns it and :meth:`BatchLedger.assemble` is where input
order is re-imposed. A guard that appended failures as they occurred would break
that contract on the pooled verbs; this module never appends.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Final, TypeVar

from pdf_toolkit.errors import AuthError, FailureError, PdfToolkitError, SourceUnreadableError
from pdf_toolkit.models import ItemResult
from pdf_toolkit.safety.paths import (
    DEFAULT_DIRECTORY_MESSAGE,
    MISSING_MESSAGE,
    classify_operand,
)

__all__ = [
    "ITEM_SCOPED_ERRORS",
    "BatchLedger",
    "defer_unreadable",
    "failure_item",
    "preflight_operands",
]

T = TypeVar("T")

#: The classes a per-input failure is made of, and nothing else.
#:
#: ``FailureError`` (exit 1, including ``SourceUnreadableError`` and
#: ``DestinationUnwritableError``) is *"the operation ran and failed"* — a
#: verdict about **one input**. ``AuthError`` (exit 6) is a password
#: requirement, which is a property of **one document**.
#:
#: Everything else is re-raised untouched and still aborts the run:
#: ``UsageError``/``PageRangeError`` (2), ``EngineMissingError`` (3),
#: ``NoInputError`` (4) and the whole ``RefusedError`` family (5). An absent
#: ``tesseract`` fails identically for every input, so rendering it as ten items
#: each ``code: 3`` would replace one accurate diagnosis with ten copies of it
#: **and change ``ocr``'s exit code from 3 to 1** — a public exit-table change
#: wearing a bug fix's clothes.
#:
#: **``except Exception`` is forbidden in this module.** A broad catch would
#: swallow the bare ``OSError``/``PdfError`` escapes that are a separate,
#: still-open read-seam item's entire evidence base — destroying that evidence
#: while appearing to improve this one. The boundary is mechanical: a
#: ``PdfToolkitError`` subclass reaching this guard is this module's; a bare
#: ``OSError``/``PdfError`` escaping to a traceback is not, and must keep
#: escaping so it stays measurable.
ITEM_SCOPED_ERRORS: Final[tuple[type[PdfToolkitError], ...]] = (FailureError, AuthError)


def defer_unreadable(
    path: Path | str,
    *,
    as_written: Path | str | None = None,
    missing_message: str = MISSING_MESSAGE,
    directory_message: str = DEFAULT_DIRECTORY_MESSAGE,
) -> None:
    """:func:`classify_operand`'s RUN-scoped rungs only; rung 4 is deferred.

    Delegates to the one classifier and drops **only** its unreadable verdict,
    so rungs 1-3 cannot come to disagree with the classifier about what a
    missing input or a directory operand means. The deferred rung is re-run on
    the per-item path by :meth:`BatchLedger.guard`, where it becomes one item's
    failure instead of the batch's.

    Raises:
        NoInputError: Exit 4 — the path does not exist.
        UsageError: Exit 2 — a directory, or not a regular file.
    """
    try:
        classify_operand(
            path,
            as_written=as_written,
            missing_message=missing_message,
            directory_message=directory_message,
        )
    except SourceUnreadableError:
        # Rung 4, and only rung 4. Deferred to the per-item guard on purpose:
        # readability is a property of a file, so one unreadable input must not
        # cost the other inputs their results.
        return


def preflight_operands(
    sources: Iterable[Path],
    *,
    missing_message: str = MISSING_MESSAGE,
    directory_message: str = DEFAULT_DIRECTORY_MESSAGE,
) -> None:
    """The batch pre-flight every ``--out-dir`` verb runs before planning.

    Keeps the two precedences that predate this module — a nonexistent input
    still exits 4 unconditionally and still wins over any other usage error, and
    a directory operand still exits 2 before any earlier input is processed —
    while letting an unreadable input through to the per-item guard.
    """
    for source in sources:
        defer_unreadable(
            source, missing_message=missing_message, directory_message=directory_message
        )


def failure_item(
    source: Path | str,
    error: PdfToolkitError,
    *,
    duration_ms: int = 0,
) -> ItemResult:
    """The per-input failure row: named input, no output, non-zero code.

    ``output`` is ``None`` rather than the target that was never written, so the
    payload cannot name a path that is not on disk — the second direction of the
    filesystem-versus-payload agreement this module exists to restore.

    ``message`` is taken from the error's own ``to_dict()`` rather than from
    ``error.message`` directly, because that method is the single chokepoint
    where a message is normalized (a raw ``repr`` carrying a heap address is
    scrubbed there, once, for every renderer). Reading the raw attribute here
    would reintroduce the very leak that chokepoint was built to close.
    """
    return ItemResult(
        input=str(source),
        output=None,
        ok=False,
        exit_code=error.exit_code,
        message=str(error.to_dict()["message"]),
        bytes_before=None,
        bytes_after=None,
        duration_ms=duration_ms,
    )


class BatchLedger:
    """Per-source failure ledger, and the input-order assembly around it.

    Two responsibilities, deliberately together: the guard has to know which
    source it is guarding in order to record a failure against it, and the
    assembly has to know the input order in order to re-impose it. Splitting
    them would put the ordering contract somewhere a caller could forget it.

    A plain ``__slots__`` class rather than a dataclass: it is mutable by
    design (the ledger accumulates), and every other model in this product is
    ``frozen=True`` — borrowing that decorator here would make a mutable
    accumulator look like one of them.
    """

    __slots__ = ("_failures", "sources")

    def __init__(self, sources: Sequence[Path]) -> None:
        self.sources = tuple(sources)
        self._failures: dict[str, ItemResult] = {}

    def guard(
        self,
        source: Path,
        work: Callable[[], T],
        *,
        classify: bool = True,
        directory_message: str = DEFAULT_DIRECTORY_MESSAGE,
        missing_message: str = MISSING_MESSAGE,
    ) -> T | None:
        """Run *work* for *source*; record and swallow an item-scoped failure.

        Returns *work*'s value, or ``None`` when the source failed — the caller
        skips it and carries on, which is the continuation half of §5.4. A
        source that has already failed an earlier phase is never re-run, so a
        verb whose planning and writing are separate passes records exactly one
        failure row for it rather than two.

        *classify* runs the deferred rung 4 immediately before the work, so the
        unreadable kind and the corrupt kind arrive at the same place by the
        same route. It is the caller's own ``classify_operand`` call, re-sited
        from a pre-flight loop to here.

        **A SINGLE-operand run re-raises instead of recording** (see
        :attr:`is_batch`), so its envelope and its exit code are exactly what
        they were before this module existed.
        """
        key = str(source)
        if key in self._failures:
            return None
        try:
            if classify:
                classify_operand(
                    source,
                    missing_message=missing_message,
                    directory_message=directory_message,
                )
            return work()
        except ITEM_SCOPED_ERRORS as error:
            if not self.is_batch:
                raise
            self._failures[key] = failure_item(source, error)
            return None

    @property
    def is_batch(self) -> bool:
        """Whether this run has more than one operand to keep going *for*.

        **The continuation only applies to a BATCH, and this is the whole of
        why.** A single-operand run has no other input that a per-item failure
        could cost, so recording that failure as a row rather than raising would
        buy nothing and would spend something: the run's exit code would
        collapse to the batch's aggregate and its envelope would change shape.
        A single-input run reports that item's OWN code, which is what makes the
        per-input codes distinguishable from each other at all — the exit-`1`
        failure, the exit-`4` missing input and the exit-`6` password
        requirement would otherwise be indistinguishable from outside.

        So the error envelope survives here EXACTLY as it was: unchanged for
        every single-input run, and unchanged for every run-scoped class on a
        batch. The behaviour change is confined to the case that was actually
        wrong — a multi-input run whose payload denied what the filesystem
        showed.
        """
        return len(self.sources) > 1

    def failed(self, source: Path) -> bool:
        """Whether *source* has already been recorded as failed."""
        return str(source) in self._failures

    @property
    def any_failed(self) -> bool:
        return bool(self._failures)

    def assemble(self, produced: Sequence[ItemResult]) -> tuple[ItemResult, ...]:
        """Merge produced rows with recorded failures, in **input order**.

        Ordering is derived from :attr:`sources` — the command line — never from
        completion order, which is what keeps ``PLAN.md`` §5.4 bullet 3 true on
        the pooled verbs. A source may contribute more than one produced row
        (``rasterize`` emits one row per rendered page); those keep their own
        relative order within the source's slot.
        """
        by_source: dict[str, list[ItemResult]] = {}
        for item in produced:
            by_source.setdefault(item.input, []).append(item)

        ordered: list[ItemResult] = []
        seen: set[str] = set()
        for source in self.sources:
            key = str(source)
            if key in seen:
                continue
            seen.add(key)
            failure = self._failures.get(key)
            if failure is not None:
                ordered.append(failure)
                continue
            ordered.extend(by_source.get(key, ()))

        # A produced row whose input is not one of the declared sources would be
        # silently dropped by the loop above, which would be a payload that
        # denies an artifact -- exactly the defect this module exists to close.
        # Append rather than discard, so it is visible instead of invisible.
        for item in produced:
            if item.input not in seen:
                ordered.append(item)
        return tuple(ordered)
