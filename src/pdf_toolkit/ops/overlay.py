"""`watermark` + `stamp` -- page-range-scoped overlay/underlay compositing,
as pure plan/result functions over `StructureEngine` + `ComposeEngine`
(PDF-14).

Framework-free per L2: no typer/click import, and no engine library import
either (Design D1/D11) -- `tests/test_import_boundaries.py`'s `ENGINE_MODULES`
walk has no `TYPE_CHECKING` exemption, so every pypdf/reportlab byte crosses
the port boundary as a plain `bytes`/dataclass, never a `pypdf.PageObject` or
a reportlab `Canvas`. This module prints nothing and calls no `sys.exit`.

Design D4.1 -- one primitive, reusable by `PDF-15`
------------------------------------------------------
The actual merge happens inside `StructureEngine.composite_layer`, called
against an already-created WRITER whose full page range is already
appended -- never against serialized bytes and never against the reader's
own pages (`PDF-23` migrated this off the reader-attached compositing call
pypdf 6.16.2 deprecates and 7.0.0 removes). This module therefore creates
the writer and calls `append_pages` BEFORE compositing,
the exact reverse of the ordering this module used before `PDF-23` --
`composite_layer` may still be called MULTIPLE times against the same
writer -- once per distinct layer/page-subset -- before that single write,
which is what lets `watermark` composite several page geometries into ONE
output (Design §D3's caching rule).

Design D4.2 -- page-range scoping, consumed not reimplemented
-------------------------------------------------------------
`_resolve_pages` below is the ONE call into `ops.pagerange.parse` both verbs
share (AC26's spy target). Nothing here parses a page-range token itself.

Design D5 -- why this module never shells out to `pdftoolkit text`
--------------------------------------------------------------------
Not applicable to production code (this module extracts nothing), but tests
exercising AC8's preservation property must not create the undeclared
`PDF-14 -> PDF-11` dependency edge -- see `tests/unit/test_overlay.py`.

Nothing here writes. Every byte reaches disk through `safety.AtomicWriter`.
"""

from __future__ import annotations

import io
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from pdf_toolkit.errors import AuthError, FailureError, NoInputError, UsageError
from pdf_toolkit.models import SCHEMA_VERSION as _SCHEMA_VERSION
from pdf_toolkit.models import ItemResult, OperationResult, PageRange
from pdf_toolkit.ops.pagerange import ALL_PAGES_TOKEN, parse
from pdf_toolkit.ports.compose import require_compose
from pdf_toolkit.ports.structure import require_composite, require_structure
from pdf_toolkit.safety.atomic import AtomicWriter, PlannedOutputs, plan_filesystem
from pdf_toolkit.safety.paths import classify_operand
from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = [
    "DEFAULT_COLOR",
    "DEFAULT_FONT_SIZE",
    "DEFAULT_FROM_PAGE",
    "DEFAULT_OPACITY",
    "DEFAULT_POSITION",
    "DEFAULT_ROTATE_DEG",
    "VERB_STAMP",
    "VERB_WATERMARK",
    "WATERMARK_FONT",
    "reject_missing_sources",
    "stamp_run",
    "watermark_run",
]

VERB_WATERMARK: Final[str] = "watermark"
VERB_STAMP: Final[str] = "stamp"

#: Design §D4.3: "both verbs, overlay is the default" -- an invisible
#: watermark is a bug, and a flag defaulting differently on two siblings is
#: exactly the CLI-contract defect `PDF-06`'s harness exists to catch.
DEFAULT_POSITION: Final[str] = "overlay"

#: `watermark`'s own defaults. `PLAN.md` §4.1 gives no `--font` flag (only
#: `--font-size`/`--color`/`--opacity`/`--rotate`), so the font itself is
#: fixed rather than user-selectable -- a base-14 font, per §D4.3's marker
#: technique (a literal ASCII run in the content stream, never subset-encoded
#: hex). Bold, because a hairline watermark is easy to miss.
WATERMARK_FONT: Final[str] = "Helvetica-Bold"
DEFAULT_FONT_SIZE: Final[float] = 48.0
DEFAULT_COLOR: Final[tuple[float, float, float]] = (0.5, 0.5, 0.5)
DEFAULT_OPACITY: Final[float] = 0.3
DEFAULT_ROTATE_DEG: Final[float] = 45.0

#: `--from-page`'s default (Design §D4.5).
DEFAULT_FROM_PAGE: Final[int] = 1


def reject_missing_sources(sources: Sequence[Path]) -> None:
    """`PLAN.md` §10's own contract, shared by every cmd module."""
    for source in sources:
        classify_operand(source)


def _resolve_pages(pages_spec: str | None, page_count: int) -> PageRange:
    """The ONE page-range resolution path both verbs share (Design D4.2,
    AC26). Default when `--pages` is omitted: all pages. Both verbs are
    SET-semantics (`PLAN.md` §4.3): the selection is normalized to a sorted,
    deduplicated set by the caller via `PageRange.as_set()`."""
    spec = pages_spec if pages_spec is not None else ALL_PAGES_TOKEN
    return parse(spec, page_count, ordered=False)


def _blank_warning(blank_pages: tuple[int, ...]) -> tuple[str, ...]:
    """Design D4.4 row 1: a run-level warning naming the affected pages,
    never a refusal -- overlay and underlay are byte-identical there."""
    if not blank_pages:
        return ()
    pages = ", ".join(str(number) for number in sorted(blank_pages))
    return (
        f"blank page(s) with no content stream: [{pages}] -- overlay and "
        "underlay are equivalent there",
    )


# --------------------------------------------------------------------------- #
# The filesystem tier (X-67/B-054), through the ONE shared planner (PDF-18
# Design D1): `watermark` and `stamp` are single-target `("--output",
# "--in-place")` verbs, so `out_dir` is always `None`.
# --------------------------------------------------------------------------- #


def _resolve_target(source: Path, *, output: Path | None, in_place: bool, verb: str) -> Path:
    if in_place:
        return source
    if output is not None:
        return output
    raise UsageError(f"{verb} requires -O/--output or --in-place")


def _dry_run_result(
    verb: str, *, source: Path, target: Path, plan: PlannedOutputs
) -> OperationResult:
    detail = plan.detail()
    item = ItemResult(
        input=str(source),
        output=str(target),
        ok=not plan.refused,
        exit_code=plan.would_exit,
        message=(f"planned: {verb}" if not plan.refused else plan.message),
        bytes_before=source.stat().st_size,
        bytes_after=None,
        duration_ms=0,
        detail=detail,
    )
    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=verb,
        dry_run=True,
        items=(item,),
        warnings=(),
        duration_ms=0,
    )


# --------------------------------------------------------------------------- #
# `watermark`
# --------------------------------------------------------------------------- #


def watermark_run(
    source: Path,
    *,
    text: str,
    pages_spec: str | None,
    position: str,
    font_size: float,
    color: tuple[float, float, float],
    opacity: float,
    rotate_deg: float,
    output: Path | None,
    in_place: bool,
    policy: SafetyPolicy,
) -> OperationResult:
    """Composite a generated text layer onto the selected pages (Design D3).

    One layer is rendered per DISTINCT selected-page geometry (`/MediaBox`
    width/height), cached and reused across every page sharing that size --
    determinism and cost, per §D3. A rotated page (`/Rotate 90`) still
    receives the layer in UNROTATED page space, so the watermark rotates
    with the page's own content when displayed; that is documented,
    intended behaviour, not a defect.
    """
    reject_missing_sources([source])
    target = _resolve_target(source, output=output, in_place=in_place, verb=VERB_WATERMARK)
    plan = plan_filesystem([target], out_dir=None, policy=policy, kind="pdf")
    if policy.dry_run:
        return _dry_run_result(VERB_WATERMARK, source=source, target=target, plan=plan)

    started = time.monotonic()
    bytes_before = source.stat().st_size
    structure_engine = require_composite()  # X-76: "composite" (pypdf only)
    compose_engine = require_compose(capability="text-layer")

    with structure_engine.open_document(source) as document:
        page_count = document.page_count
        selection = _resolve_pages(pages_spec, page_count)
        if selection.is_empty:
            raise NoInputError(
                f"{source}: --pages {(pages_spec or ALL_PAGES_TOKEN)!r} resolved to zero pages; "
                f"nothing to {VERB_WATERMARK}",
                path=str(source),
            )
        selected = sorted(selection.as_set())

        # Per-page geometry comes from the EXISTING `read_document_info(...,
        # pages=True)` path -- `rotate`'s own precedent (`ops/pages.py`):
        # never a new port method for a fact an existing one already reports.
        info = structure_engine.read_document_info(source, pages=True)
        geometry_by_page = {page.number: (page.width_pt, page.height_pt) for page in info.pages}

        pages_by_geometry: dict[tuple[float, float], list[int]] = {}
        for number in selected:
            pages_by_geometry.setdefault(geometry_by_page[number], []).append(number)

        # Design D3.1 -- the writer is created and the FULL page range
        # appended BEFORE any compositing, the reverse of this module's own
        # ordering before `PDF-23`: `composite_layer` now operates on
        # `writer`'s own already-appended pages, never the reader's.
        writer = structure_engine.new_writer()
        writer.append_pages(document, list(range(1, page_count + 1)))

        layer_cache: dict[tuple[float, float], bytes] = {}
        composited: list[int] = []
        copied: list[int] = []
        blank: list[int] = []
        for geometry, numbers in pages_by_geometry.items():
            if geometry not in layer_cache:
                buffer = io.BytesIO()
                compose_engine.render_text_layer(
                    text,
                    page_size=geometry,
                    font=WATERMARK_FONT,
                    font_size=font_size,
                    color=color,
                    opacity=opacity,
                    rotate_deg=rotate_deg,
                    out=buffer,
                )
                layer_cache[geometry] = buffer.getvalue()
            outcome = structure_engine.composite_layer(
                writer, layer=layer_cache[geometry], pages=numbers, position=position
            )
            composited.extend(outcome.pages_composited)
            copied.extend(outcome.pages_copied)
            blank.extend(outcome.blank_pages)

        with AtomicWriter(target, policy=policy, kind="pdf") as atomic:
            writer.write(atomic.stream)

    bytes_after = target.stat().st_size
    duration_ms = int((time.monotonic() - started) * 1000)
    item = ItemResult(
        input=str(source),
        output=str(target),
        ok=True,
        exit_code=0,
        message=f"watermarked {len(composited)} page(s)",
        bytes_before=bytes_before,
        bytes_after=bytes_after,
        duration_ms=duration_ms,
        detail={"pages_composited": sorted(composited), "pages_copied": sorted(copied)},
    )
    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=VERB_WATERMARK,
        dry_run=False,
        items=(item,),
        warnings=_blank_warning(tuple(blank)),
        duration_ms=0,
    )


# --------------------------------------------------------------------------- #
# `stamp`
# --------------------------------------------------------------------------- #


def _validate_from_path(from_path: Path) -> None:
    classify_operand(
        from_path,
        missing_message=f"--from: no such file: {from_path}",
        directory_message=f"--from: expected a PDF file, not a directory: {from_path}",
    )


def _extract_stamp_layer(from_path: Path, from_page: int) -> bytes:
    """Design §D4.5 -- resolve `--from`/`--from-page` into a one-page PDF,
    BEFORE the target document is ever opened, so a bad `--from` refuses
    without touching the target at all. Reuses the EXISTING D10 primitive
    (`open_document` + `new_writer` + `append_pages` + `write`) rather than
    a new adapter method -- extracting one page IS what that primitive
    already does.
    """
    _validate_from_path(from_path)
    engine = require_structure()  # X-76: unqualified -- pypdf is primary
    try:
        with engine.open_document(from_path) as from_document:
            from_page_count = from_document.page_count
            if not (1 <= from_page <= from_page_count):
                raise UsageError(
                    f"--from-page {from_page} exceeds --from's page count "
                    f"({from_page_count}): {from_path}",
                    path=str(from_path),
                )
            writer = engine.new_writer()
            writer.append_pages(from_document, [from_page])
            buffer = io.BytesIO()
            writer.write(buffer)
            return buffer.getvalue()
    except AuthError as error:
        # B-074: names the DOCUMENT, never a secret -- `redacted` unset.
        raise AuthError(
            f"a password is required to open --from ({from_path}); {error.message}",
            path=str(from_path),
        ) from error
    except FailureError as error:
        raise FailureError(
            f"--from is malformed ({from_path}): {error.message}", path=str(from_path)
        ) from error


def stamp_run(
    source: Path,
    *,
    from_path: Path,
    from_page: int,
    pages_spec: str | None,
    position: str,
    output: Path | None,
    in_place: bool,
    policy: SafetyPolicy,
) -> OperationResult:
    """Composite an existing PDF page (`--from`/`--from-page`) onto the
    selected pages of *source* (Design D4.5)."""
    reject_missing_sources([source])
    target = _resolve_target(source, output=output, in_place=in_place, verb=VERB_STAMP)
    plan = plan_filesystem([target], out_dir=None, policy=policy, kind="pdf")
    if policy.dry_run:
        return _dry_run_result(VERB_STAMP, source=source, target=target, plan=plan)

    started = time.monotonic()
    bytes_before = source.stat().st_size

    layer_bytes = _extract_stamp_layer(from_path, from_page)

    structure_engine = require_composite()  # X-76: "composite" (pypdf only)
    with structure_engine.open_document(source) as document:
        page_count = document.page_count
        selection = _resolve_pages(pages_spec, page_count)
        if selection.is_empty:
            raise NoInputError(
                f"{source}: --pages {(pages_spec or ALL_PAGES_TOKEN)!r} resolved to zero pages; "
                f"nothing to {VERB_STAMP}",
                path=str(source),
            )
        selected = sorted(selection.as_set())

        # Design D3.1 -- writer created, full range appended, BEFORE compositing.
        writer = structure_engine.new_writer()
        writer.append_pages(document, list(range(1, page_count + 1)))

        outcome = structure_engine.composite_layer(
            writer, layer=layer_bytes, pages=selected, position=position
        )

        with AtomicWriter(target, policy=policy, kind="pdf") as atomic:
            writer.write(atomic.stream)

    bytes_after = target.stat().st_size
    duration_ms = int((time.monotonic() - started) * 1000)
    item = ItemResult(
        input=str(source),
        output=str(target),
        ok=True,
        exit_code=0,
        message=f"stamped {len(outcome.pages_composited)} page(s)",
        bytes_before=bytes_before,
        bytes_after=bytes_after,
        duration_ms=duration_ms,
        detail={
            "pages_composited": sorted(outcome.pages_composited),
            "pages_copied": sorted(outcome.pages_copied),
        },
    )
    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=VERB_STAMP,
        dry_run=False,
        items=(item,),
        warnings=_blank_warning(outcome.blank_pages),
        duration_ms=0,
    )
