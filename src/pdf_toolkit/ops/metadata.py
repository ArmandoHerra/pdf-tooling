"""`meta get` + `meta set` -- pure plan/result functions over `StructureEngine`
(PDF-14).

Framework-free per L2: no typer/click import (`tests/test_import_boundaries.py`
enforces it), and **no engine library import either** -- every value crosses
the port boundary through `ports/structure.py`'s plain `MetadataFacts` /
`MetadataWriteOutcome` dataclasses, never a pypdf `XmpInformation` or
`DictionaryObject` (the same `ENGINE_MODULES` walk that binds `ops/overlay.py`
binds this module too -- Design D1/D11, no `TYPE_CHECKING` exemption).

Design D2.1 -- both halves, always, never merged
--------------------------------------------------
`meta get` reports `/Info` and XMP side by side and STATES a disagreement
rather than resolving it. The comparison basis is the alignment table
`adapters/pypdf_structure.py::_ALIGNMENT` already owns on the write side; this
module keeps its OWN plain-string mirror of the same field/`/Info`-key pairing
(`_INFO_KEY_BY_FIELD` below) because `ops/` may not import `adapters/`
directly -- the port is the boundary. It is a duplication of field NAMES,
never of engine behaviour.

Design D2.2/D2.3 -- `meta set` writes both halves, creates neither
----------------------------------------------------------------------
The write itself -- including the D2.3 type-preservation mechanics and the
"no packet, no sync" rule -- lives entirely in the adapter
(`write_metadata`). This module's job is arity/usage validation (`meta set`
with no field flag and no clear flag is exit 2), the filesystem tier
(X-67/B-054, mirroring `ops/optimize.py::repair_run`'s own `_FilesystemPlan`
donor shape), and handing the write to `safety.AtomicWriter`.

Nothing here writes. Every byte reaches disk through `safety.AtomicWriter`.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from pdf_toolkit.errors import NoInputError, UsageError
from pdf_toolkit.models import SCHEMA_VERSION as _SCHEMA_VERSION
from pdf_toolkit.models import ItemResult, MetadataReport, OperationResult
from pdf_toolkit.ports.structure import MetadataFacts, require_structure
from pdf_toolkit.safety.atomic import AtomicWriter, plan_filesystem
from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = [
    "CLEARABLE_FIELDS",
    "SETTABLE_FIELDS",
    "VERB_META_GET",
    "VERB_META_SET",
    "meta_get_run",
    "meta_set_run",
    "reject_missing_sources",
]

VERB_META_GET: Final[str] = "meta get"
VERB_META_SET: Final[str] = "meta set"

#: Report field -> `/Info` key, `/`-stripped -- matching `MetadataFacts.info`'s
#: own keys. A plain-string mirror of `adapters/pypdf_structure.py::_ALIGNMENT`'s
#: first two columns, duplicated deliberately (see the module docstring).
_INFO_KEY_BY_FIELD: Final[dict[str, str]] = {
    "title": "Title",
    "author": "Author",
    "subject": "Subject",
    "keywords": "Keywords",
    "creator": "Creator",
    "producer": "Producer",
    "creation_date": "CreationDate",
    "mod_date": "ModDate",
}

#: `meta set --title/--author/--subject/--keywords/--creator` (PLAN.md §4.1).
#: Deliberately narrower than `_INFO_KEY_BY_FIELD`: `creation_date`/`mod_date`
#: are report-only, and `producer` is CLEAR-only (`--clear-producer`, never a
#: `--producer` setter).
SETTABLE_FIELDS: Final[frozenset[str]] = frozenset(
    {"title", "author", "subject", "keywords", "creator"}
)

#: `meta set --clear-producer`. `--clear-all` is a separate, orthogonal flag
#: (D2.4) -- not a member of this set.
CLEARABLE_FIELDS: Final[frozenset[str]] = frozenset({"producer"})


def reject_missing_sources(sources: Sequence[Path]) -> None:
    """`PLAN.md` §10's own contract, shared by every cmd module."""
    for source in sources:
        if not source.exists():
            raise NoInputError("no such file", path=str(source))
        if source.is_dir():
            raise UsageError("expected a PDF file, not a directory", path=str(source))


# --------------------------------------------------------------------------- #
# D2.1 -- disagreement computation, over already-extracted plain values only.
# `MetadataFacts.xmp` carries each XMP property in whatever native shape
# `XmpInformation`'s own getter returns (measured against pypdf 6.16.2): a
# LangAlt as a `{"x-default": ...}` dict (empty `{}` when unset), a Seq as a
# `list[str]` (empty `[]` when unset), a scalar as `str | None`, and the two
# date fields as `datetime.datetime | None`.
# --------------------------------------------------------------------------- #


def _xmp_scalar(field: str, value: object) -> str | None:
    """One XMP property, reduced to the string D2.1's comparison rule
    compares -- LangAlt compares `x-default`; `dc_creator` compares
    `", ".join(...)`. `{}`/`[]`/`None` -- pypdf's own "unset" shapes --
    normalize to `None` here: "absent", not "empty"."""
    if not value:
        return None
    if field in ("title", "subject"):
        return value.get("x-default") if isinstance(value, Mapping) else None
    if field == "author":
        return ", ".join(value) if isinstance(value, (list, tuple)) else None
    if field in ("creation_date", "mod_date"):
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
    return str(value)


def _normalize(value: str | None) -> str | None:
    """D2.1's comparison rule: strip surrounding whitespace. `None` stays
    `None` -- the missing-side sentinel, never an empty string."""
    return value.strip() if isinstance(value, str) else value


def _compute_disagreements(facts: MetadataFacts) -> tuple[dict[str, object], ...]:
    if facts.xmp is None:
        return ()
    disagreements: list[dict[str, object]] = []
    for field, info_key in _INFO_KEY_BY_FIELD.items():
        info_value = _normalize(facts.info.get(info_key))
        xmp_value = _normalize(_xmp_scalar(field, facts.xmp.get(field)))
        if info_value != xmp_value:
            disagreements.append({"field": field, "info": info_value, "xmp": xmp_value})
    return tuple(disagreements)


def _json_safe_xmp(xmp: Mapping[str, object] | None) -> dict[str, object] | None:
    """`MetadataFacts.xmp`'s native pypdf-return shapes, reduced to what
    `json.dumps` can render -- `datetime` -> ISO 8601 string, everything else
    passed through unchanged (dict/list/str/None already serialize)."""
    if xmp is None:
        return None
    safe: dict[str, object] = {}
    for field, value in xmp.items():
        safe[field] = value.isoformat() if hasattr(value, "isoformat") else value
    return safe


def _build_report(source: Path, facts: MetadataFacts, *, include_xmp_raw: bool) -> MetadataReport:
    return MetadataReport(
        schema_version=_SCHEMA_VERSION,
        path=str(source),
        info=facts.info,
        xmp=_json_safe_xmp(facts.xmp),
        xmp_raw=facts.xmp_raw if include_xmp_raw else None,
        disagreements=_compute_disagreements(facts),
        residual_surfaces=facts.residual_surfaces,
    )


def meta_get_run(source: Path, *, xmp: bool) -> MetadataReport:
    """`meta get` -- read both halves, side by side, plus D2.4's residual
    surfaces. Writes nothing; unaffected by `--dry-run` (D9) -- there is
    nothing to predict."""
    reject_missing_sources([source])
    engine = require_structure()  # X-76: by capability, never by adapter name
    facts = engine.read_metadata(source)
    return _build_report(source, facts, include_xmp_raw=xmp)


# --------------------------------------------------------------------------- #
# `meta set` -- the filesystem tier (X-67/B-054), through the ONE shared
# planner (PDF-18 Design D1/D9): `meta set` is a single-target `("--output",
# "--in-place")` verb, so `out_dir` is always `None`.
# --------------------------------------------------------------------------- #


def meta_set_run(
    source: Path,
    *,
    sets: Mapping[str, str],
    clear_producer: bool,
    clear_all: bool,
    output: Path | None,
    in_place: bool,
    policy: SafetyPolicy,
) -> OperationResult:
    """`meta set` -- write both halves (D2.2), creating neither, preserving
    the original PdfObject type of every untouched `/Info` key (D2.3, inside
    the adapter). `--in-place`'s confirmation gate (R6/B-079) is the CLI
    layer's job (`cmd_meta_set.py`), mirroring `cmd_rotate.py`'s own call
    site -- this function is called only once the gate has already cleared.
    """
    reject_missing_sources([source])
    if not sets and not clear_producer and not clear_all:
        raise UsageError(f"{VERB_META_SET} requires at least one field flag or a clear flag")

    target = source if in_place else output
    if target is None:
        raise UsageError(f"{VERB_META_SET} requires -O/--output or --in-place")

    plan = plan_filesystem([target], out_dir=None, policy=policy, kind="pdf")

    if policy.dry_run:
        detail = plan.detail()
        item = ItemResult(
            input=str(source),
            output=str(target),
            ok=not plan.refused,
            exit_code=plan.would_exit,
            message=(f"planned: {VERB_META_SET}" if not plan.refused else plan.message),
            bytes_before=source.stat().st_size,
            bytes_after=None,
            duration_ms=0,
            detail=detail,
        )
        return OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=VERB_META_SET,
            dry_run=True,
            items=(item,),
            warnings=(),
            duration_ms=0,
        )

    started = time.monotonic()
    bytes_before = source.stat().st_size
    engine = require_structure()  # X-76: by capability, never by adapter name
    clears = ["producer"] if clear_producer else []

    outcome = engine.write_metadata(
        source.read_bytes(), sets=sets, clears=clears, clear_all=clear_all
    )

    with AtomicWriter(target, policy=policy, kind="pdf") as writer:
        writer.stream.write(outcome.output)

    bytes_after = target.stat().st_size
    duration_ms = int((time.monotonic() - started) * 1000)
    message = "ok" if outcome.wrote_xmp or clear_all else "ok (no XMP packet; /Info only)"
    item = ItemResult(
        input=str(source),
        output=str(target),
        ok=True,
        exit_code=0,
        message=message,
        bytes_before=bytes_before,
        bytes_after=bytes_after,
        duration_ms=duration_ms,
        detail={"wrote_xmp": outcome.wrote_xmp},
    )
    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=VERB_META_SET,
        dry_run=False,
        items=(item,),
        warnings=(),
        duration_ms=0,
    )
