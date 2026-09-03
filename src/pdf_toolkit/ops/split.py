"""``split`` — one PDF into many (Design §D4-D6, D8-D10).

Framework-free per L2. Grammar knowledge stays entirely in
``ops/pagerange.py`` (G6, AC7): every ``--ranges`` part is handed *verbatim*
to :func:`~pdf_toolkit.ops.pagerange.parse`; ``str.split(",")`` for the part
separator is not grammar parsing and is explicitly permitted by AC7.

**Plan-then-write (Design §D4).** All parts are resolved, all target paths
rendered — through :mod:`pdf_toolkit.safety.naming`, containment-checked —
and all no-clobber/collision checks run **before the first byte is
written**; a planning failure writes nothing. ``--out-dir`` is created once,
as its own plan step, before the write loop, via
:func:`~pdf_toolkit.safety.atomic.plan_output_set` (never inside
:class:`~pdf_toolkit.safety.atomic.AtomicWriter`'s own per-target gate,
which would create it once per part instead of once per run).

**The filesystem tier runs in both modes (B-054, extending X-67).**
``plan_output_set`` is called unconditionally, so a ``--dry-run`` over an
occupied target or an unwritable ``--out-dir`` predicts the same exit code a
real run produces, rather than entering cleanly and being contradicted by it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pdf_toolkit.errors import NoInputError, UsageError
from pdf_toolkit.models import SCHEMA_VERSION as _SCHEMA_VERSION
from pdf_toolkit.models import ItemResult, OperationResult
from pdf_toolkit.ops.pagerange import PageRangeError, parse
from pdf_toolkit.ports.structure import OpenStructureDocument, require_structure
from pdf_toolkit.safety.atomic import AtomicWriter, plan_output_set
from pdf_toolkit.safety.naming import render_name, used_fields
from pdf_toolkit.safety.paths import check_output_collisions, classify_operand
from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = ["MODES", "default_name_template", "split_document"]

VERB: Final[str] = "split"

#: The four mode flags (Design §D4). A plain tuple for the same reason
#: `ops/merge.py::BOOKMARK_MODES` is — this module is framework-free and the
#: CLI layer owns its own choice-shaped surface.
MODES: Final[tuple[str, ...]] = ("every", "ranges", "each-page", "at-bookmarks")

_EACH_PAGE_TEMPLATE: Final[str] = "{stem}-{page:03}.{ext}"
_INDEXED_TEMPLATE: Final[str] = "{stem}-{index:03}.{ext}"


def default_name_template(mode: str) -> str:
    """The per-mode default ``--name`` template (Design §D6)."""
    if mode == "each-page":
        return _EACH_PAGE_TEMPLATE
    return _INDEXED_TEMPLATE


@dataclass(frozen=True, slots=True)
class _Part:
    page_numbers: tuple[int, ...]
    index: int
    """1-based part number, in the order parts were produced."""


def _extent_text(page_numbers: tuple[int, ...]) -> str:
    """The part's resolved extent as ``NNN-NNN``, or ``NNN`` for one page (D6)."""
    if not page_numbers:
        return ""
    if len(page_numbers) == 1:
        return f"{page_numbers[0]}"
    return f"{min(page_numbers)}-{max(page_numbers)}"


def _parts_every(page_count: int, every: int) -> list[_Part]:
    if every < 1:
        raise UsageError("--every must be 1 or greater")
    parts: list[_Part] = []
    start = 1
    index = 1
    while start <= page_count:
        end = min(start + every - 1, page_count)
        parts.append(_Part(page_numbers=tuple(range(start, end + 1)), index=index))
        start = end + 1
        index += 1
    return parts


def _parts_each_page(page_count: int) -> list[_Part]:
    return [_Part(page_numbers=(page,), index=page) for page in range(1, page_count + 1)]


def _parts_ranges(ranges: tuple[str, ...], page_count: int) -> list[_Part]:
    """D4: ``--ranges`` is repeatable; every occurrence is comma-split at the
    top level, in order, and each resulting part is handed verbatim to
    PDF-03. A malformed part surfaces PDF-03's message unmodified, prefixed
    only with the part's position."""
    flat: list[str] = []
    for occurrence in ranges:
        flat.extend(occurrence.split(","))
    total = len(flat)
    parts: list[_Part] = []
    for position, raw_part in enumerate(flat, start=1):
        part_spec = raw_part.strip()
        try:
            page_range = parse(part_spec, page_count, ordered=True)
        except PageRangeError as error:
            raise PageRangeError(
                f"--ranges part {position} of {total}: {error.message}",
                spec=error.spec,
                token=error.token,
                column=error.column,
                reason=error.reason,
                path=error.path,
            ) from error
        parts.append(_Part(page_numbers=page_range.indices, index=position))
    return parts


def _parts_at_bookmarks(document: OpenStructureDocument, source: Path) -> list[_Part]:
    """Design §D5, including the no-outline case (E4, AC16)."""
    outline = document.top_level_outline()
    if not outline:
        raise NoInputError(
            f"--at-bookmarks: {source} has no top-level outline entries; nothing to split at",
            path=str(source),
        )
    page_count: int = document.page_count
    breakpoints = sorted({page for _title, page in outline})
    starts = [1, *breakpoints] if breakpoints[0] != 1 else breakpoints
    ends = [*(start - 1 for start in starts[1:]), page_count]
    parts: list[_Part] = []
    for index, (start, end) in enumerate(zip(starts, ends, strict=True), start=1):
        parts.append(_Part(page_numbers=tuple(range(start, end + 1)), index=index))
    return parts


def _resolve_parts(
    mode: str,
    document: OpenStructureDocument,
    source: Path,
    *,
    page_count: int,
    every: int | None,
    ranges: tuple[str, ...],
) -> list[_Part]:
    if mode == "every":
        return _parts_every(page_count, every if every is not None else 0)
    if mode == "ranges":
        return _parts_ranges(ranges, page_count)
    if mode == "each-page":
        return _parts_each_page(page_count)
    if mode == "at-bookmarks":
        return _parts_at_bookmarks(document, source)
    raise AssertionError(f"unknown split mode {mode!r}")  # pragma: no cover - CLI validates


def split_document(
    source: Path,
    *,
    mode: str,
    every: int | None,
    ranges: tuple[str, ...],
    name_template: str | None,
    out_dir: Path,
    policy: SafetyPolicy,
) -> OperationResult:
    """Split *source* into ``out_dir``, by *mode* (Design §D4, §D8).

    ``items`` carries **one row per output part** (D8): ``input`` is
    *source* on every row, ``output`` the part path, ``message`` the
    resolved extent ("pages 1-10").
    """
    classify_operand(source)

    template = name_template if name_template is not None else default_name_template(mode)
    fields = used_fields(template)
    if "page" in fields and mode != "each-page":
        raise UsageError("'{page}' is only available with --each-page")

    engine = require_structure()
    with engine.open_document(source) as document:
        page_count = document.page_count
        parts = _resolve_parts(
            mode, document, source, page_count=page_count, every=every, ranges=ranges
        )

        nonzero = [part for part in parts if part.page_numbers]
        if not nonzero:
            raise NoInputError(
                f"{source}: every part resolved to zero pages; nothing to write",
                path=str(source),
            )

        stem = source.stem
        ext = source.suffix.lstrip(".") or "pdf"
        rendered: list[tuple[_Part, Path]] = []
        for part in nonzero:
            target = render_name(
                template,
                out_dir=out_dir,
                stem=stem,
                ext=ext,
                index=part.index,
                page=part.page_numbers[0] if "page" in fields else None,
                range_text=_extent_text(part.page_numbers),
            )
            rendered.append((part, target))

        targets = [target for _part, target in rendered]
        # D4: collision is checked identically in both real and dry-run modes
        # -- it is data-independent (planned targets against each other), and
        # AC10 explicitly requires the same refusal under --dry-run.
        check_output_collisions(targets)

        source_size = source.stat().st_size

        # B-054: the filesystem tier (--out-dir creation, writability, every
        # target's no-clobber) runs ONCE, unconditionally, in BOTH modes -- a
        # real run raises exactly as before (see the block below); a dry run
        # captures the first refusal instead (X-67, extended to a
        # multi-target --out-dir run).
        plan = plan_output_set(targets, out_dir=out_dir, policy=policy)

        if policy.dry_run:
            # A run-level refusal (an unwritable --out-dir) is not
            # attributable to one part, and this is not a loss of precision:
            # split's own plan-then-write design (D4) means a planning
            # failure writes NOTHING -- not one part -- so applying the same
            # prediction to every item states exactly what the real run would
            # have done, mirroring merge's/compose's own single-target
            # convention of one refusal covering every item in the run.
            detail: dict[str, object] = {"would_exit": plan.would_exit}
            if plan.refusal is not None:
                detail["would_refuse"] = plan.would_refuse
            items = tuple(
                ItemResult(
                    input=str(source),
                    output=str(target),
                    ok=plan.refusal is None,
                    exit_code=plan.would_exit,
                    message=(
                        f"pages {_extent_text(part.page_numbers)}"
                        if plan.refusal is None
                        else plan.refusal.message
                    ),
                    bytes_before=source_size,
                    bytes_after=None,
                    duration_ms=0,
                    detail=detail,
                )
                for part, target in rendered
            )
            return OperationResult(
                schema_version=_SCHEMA_VERSION,
                verb=VERB,
                dry_run=True,
                items=items,
                warnings=(),
                duration_ms=0,
            )

        # Real run: plan_output_set already created --out-dir
        # (chokepoint-confined) and pre-flight checked every target for
        # no-clobber/writability -- BEFORE the first AtomicWriter opens, so a
        # planning failure writes nothing. It raised already if refused (the
        # `except PdfToolkitError: ... raise` inside plan_output_set, since
        # policy.dry_run is False here), so plan.refusal is always None below.
        written_items: list[ItemResult] = []
        for part, target in rendered:
            writer = engine.new_writer()
            writer.append_pages(document, part.page_numbers)
            with AtomicWriter(target, policy=policy, kind="pdf") as atomic:
                writer.write(atomic.stream)
            written_items.append(
                ItemResult(
                    input=str(source),
                    output=str(target),
                    ok=True,
                    exit_code=0,
                    message=f"pages {_extent_text(part.page_numbers)}",
                    bytes_before=source_size,
                    bytes_after=target.stat().st_size,
                    duration_ms=0,
                )
            )
        return OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=VERB,
            dry_run=False,
            items=tuple(written_items),
            warnings=(),
            duration_ms=0,
        )
