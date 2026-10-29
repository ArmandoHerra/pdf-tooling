"""PDF-156 -- the run-scoped ledger of ``AtomicWriter`` safety warnings.

The rule (``X-1209``): every warning the writer prints to stderr is also
published in the result envelope's ``warnings``. ``AtomicWriter._warn`` records
each message it sends to the DEFAULT stderr sink here; the CLI wrapper opens
this ledger for the duration of one verb run, and the envelope-only publisher
(``ops.carriage.publish_writer_warnings``) appends what was recorded.

This module is separate from ``safety/atomic.py`` on purpose, and imports
nothing from it. The verb registry classifies a verb as mutating when its
static import closure reaches ``safety.atomic``; ``cli/common.py`` and
``ops/carriage.py`` need this ledger, and an edge from either into
``safety.atomic`` would reclassify ``doctor``, ``info`` and ``version`` as
mutating (the registry-classification guard in PDF-108's carriage test module).

No ledger is open outside a CLI verb run (the Python API, the test harness):
recording is then a no-op and behaviour is unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextvars import ContextVar, Token

__all__ = [
    "close_writer_warnings",
    "open_writer_warnings",
    "record_writer_warnings",
    "writer_warnings",
]

_WRITER_WARNINGS: ContextVar[list[str] | None] = ContextVar("pdf156_writer_warnings", default=None)


def open_writer_warnings() -> Token[list[str] | None]:
    """Open a fresh, empty ledger for the current run."""
    return _WRITER_WARNINGS.set([])


def close_writer_warnings(token: Token[list[str] | None]) -> None:
    _WRITER_WARNINGS.reset(token)


def record_writer_warnings(messages: Sequence[str]) -> None:
    """Append *messages*, in order. A no-op when no ledger is open."""
    ledger = _WRITER_WARNINGS.get()
    if ledger is not None:
        ledger.extend(messages)


def writer_warnings() -> tuple[str, ...]:
    """What the open ledger holds, in record order; ``()`` when none is open."""
    ledger = _WRITER_WARNINGS.get()
    return tuple(ledger) if ledger is not None else ()
