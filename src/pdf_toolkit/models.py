"""The data model — stdlib frozen dataclasses, and the structured-output schema.

``SCHEMA_VERSION`` and every ``to_dict()`` below are PUBLIC API from v1.0.0.
``to_dict()`` is the *only* thing a renderer consumes, so a field rename cannot
silently change the published schema without touching a method a test pins.

This file is shared by several specs. Each model that a later spec owns has its
own named insertion anchor below; insert at your own anchor and nowhere else,
so two engineers editing this file concurrently cannot race on one line.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = [
    "SCHEMA_VERSION",
    "ItemResult",
    "OperationPlan",
    "OperationResult",
    "PageRange",
]

#: Bumped only per the output stability policy: the ``-o json``/``ndjson``
#: shapes are a contract, and breaking one requires a major version bump.
SCHEMA_VERSION: Final[int] = 1


@dataclass(frozen=True, slots=True)
class PageRange:
    """Parsed page selection, resolved against a concrete page count.

    The *parser* for the page-range grammar is not in this file; it imports this
    class and must never redefine it.
    """

    spec: str
    """The original string, e.g. ``"1-3,last,!2"``."""

    indices: tuple[int, ...]
    """1-based, order-preserving; may contain duplicates for ordered verbs."""

    ordered: bool
    """True when order and duplicates are meaningful (extract/reorder)."""

    page_count: int
    """The document page count this selection was resolved against."""

    def as_set(self) -> frozenset[int]:
        """The selection with order and duplicates discarded."""
        return frozenset(self.indices)

    def to_dict(self) -> dict[str, object]:
        return {
            "spec": self.spec,
            "indices": list(self.indices),
            "ordered": self.ordered,
            "page_count": self.page_count,
        }


# --- ANCHOR: PageInfo ------------------------------------------------------
# Reserved for the per-page report model. Insert the frozen ``PageInfo``
# dataclass directly below this anchor line and leave the anchor in place.
# ---------------------------------------------------------------------------


# --- ANCHOR: DocumentInfo --------------------------------------------------
# Reserved for the document-level report model. Insert the frozen
# ``DocumentInfo`` dataclass directly below this anchor line and leave the
# anchor in place.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OperationPlan:
    """Everything the CLI decided, before anything touches the filesystem.

    A verb is ``plan -> result``; ``--dry-run`` renders the plan and stops.
    """

    verb: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    """Fully resolved target paths."""

    page_range: PageRange | None
    options: dict[str, object]
    """Verb-specific and already validated."""

    safety: SafetyPolicy

    def to_dict(self) -> dict[str, object]:
        return {
            "verb": self.verb,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "page_range": self.page_range.to_dict() if self.page_range else None,
            "options": dict(self.options),
            "safety": self.safety.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ItemResult:
    """One unit of work inside a run.

    ``exit_code`` is per-item; the run's code is the highest severity across
    items.
    """

    input: str
    output: str | None
    ok: bool
    exit_code: int
    message: str | None
    bytes_before: int | None
    bytes_after: int | None
    duration_ms: int

    def to_dict(self) -> dict[str, object]:
        return {
            "input": self.input,
            "output": self.output,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "message": self.message,
            "bytes_before": self.bytes_before,
            "bytes_after": self.bytes_after,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True, slots=True)
class OperationResult:
    """The payload every verb returns and every renderer consumes."""

    schema_version: int
    verb: str
    dry_run: bool
    items: tuple[ItemResult, ...]
    warnings: tuple[str, ...]
    duration_ms: int

    @property
    def exit_code(self) -> int:
        """0 when every item is ok, otherwise the highest item code."""
        codes = [item.exit_code for item in self.items if not item.ok]
        return max(codes) if codes else 0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "verb": self.verb,
            "dry_run": self.dry_run,
            "items": [item.to_dict() for item in self.items],
            "warnings": list(self.warnings),
            "duration_ms": self.duration_ms,
            "exit_code": self.exit_code,
        }


# --- ANCHOR: EngineReport --------------------------------------------------
# Reserved for the engine-resolution report model (one row of ``doctor``).
# Insert the frozen ``EngineReport`` dataclass directly below this anchor line
# and leave the anchor in place.
# ---------------------------------------------------------------------------
