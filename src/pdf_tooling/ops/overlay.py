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
PDF-162: the real run AND the dry run reach it through `_select_pages` (and
`stamp`'s `--from-page` bound through `_check_from_page`), the dry run with the
page counts PDF-159's credential-free probe already read, so a preview raises
exactly the page-selection refusal the real run raises.

Design D5 -- why this module never shells out to `pdftooling text`
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

from pdf_tooling.errors import AuthError, FailureError, NoInputError, PdfToolingError, UsageError
from pdf_tooling.models import SCHEMA_VERSION as _SCHEMA_VERSION
from pdf_tooling.models import ItemResult, OperationResult, PageRange
from pdf_tooling.ops.document_password import (
    NO_PASSWORD,
    DryOpenProbe,
    EngineProbe,
    PasswordResolver,
    PasswordSource,
    password_detail,
    predict_password_refusal,
)
from pdf_tooling.ops.pagerange import ALL_PAGES_TOKEN, parse
from pdf_tooling.ports.compose import require_compose
from pdf_tooling.ports.structure import require_composite, require_structure
from pdf_tooling.safety.atomic import AtomicWriter, PlannedOutputs, plan_filesystem
from pdf_tooling.safety.paths import classify_operand
from pdf_tooling.safety.policy import SafetyPolicy
from pdf_tooling.secret import Secret

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

#: PDF-151 D1: mirrors `ops/compose.py`'s `_TEXT_ENCODING`, minus the C0/DEL
#: codes reportlab's `winansi` codec lacks (handled in `_drawable_text`);
#: `create`'s constant is private and `create` is frozen, so it is not imported.
_WATERMARK_ENCODING: Final[str] = "cp1252"


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


def _select_pages(source: Path, pages_spec: str | None, page_count: int, *, verb: str) -> list[int]:
    """The ONE page-selection step (D4.2): resolve --pages against the document's
    own page count, and refuse an empty selection. Called by the real run AND,
    with the count from PDF-159's dry probe, by the dry run (PDF-162), so a
    preview raises exactly what the real run raises."""
    selection = _resolve_pages(pages_spec, page_count)
    if selection.is_empty:
        raise NoInputError(
            f"{source}: --pages {(pages_spec or ALL_PAGES_TOKEN)!r} resolved to zero "
            f"pages; nothing to {verb}",
            path=str(source),
        )
    return sorted(selection.as_set())


def _check_from_page(from_page: int, from_page_count: int, from_path: Path) -> None:
    """The `--from-page` bound, shared by the real run and the dry run (PDF-162)."""
    if not (1 <= from_page <= from_page_count):
        raise UsageError(
            f"--from-page {from_page} exceeds --from's page count ({from_page_count}): {from_path}",
            path=str(from_path),
        )


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


def _encodable(character: str) -> bool:
    try:
        character.encode(_WATERMARK_ENCODING)
    except UnicodeEncodeError:
        return False
    return True


def _drawable_text(text: str) -> tuple[str, str | None]:
    """PDF-151 (OR-71): replace every character the watermark font cannot draw with '?'.

    Returns the text to draw and, when anything was replaced, one warning that
    names each distinct replaced character as a U+XXXX code point, in order of
    first occurrence. Pure: no OS, document or engine call, so the dry run and
    the real run give the same answer.
    """
    drawn: list[str] = []
    replaced: list[int] = []
    for character in text:
        point = ord(character)
        if point < 0x20 or point == 0x7F or not _encodable(character):
            drawn.append("?")
            replaced.append(point)
        else:
            drawn.append(character)
    if not replaced:
        return text, None
    points = ", ".join(f"U+{point:04X}" for point in dict.fromkeys(replaced))
    return "".join(drawn), (
        f"--text: {len(replaced)} character(s) outside the font's WinAnsi encoding "
        f"were replaced with '?': {points}"
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
    verb: str,
    *,
    source: Path,
    target: Path,
    plan: PlannedOutputs,
    password: PasswordSource = NO_PASSWORD,
    warnings: tuple[str, ...] = (),
    engine_probe: EngineProbe | None = None,
    from_probe: tuple[Path, EngineProbe] | None = None,
    pages_spec: str | None = None,
    from_page: int | None = None,
) -> OperationResult:
    """PDF-37: neither `watermark` nor `stamp` otherwise opens the document
    under ``--dry-run``, so the global ``--password-file`` resolvability
    tier is predicted here explicitly, in the SAME tier as the filesystem
    refusal (never the correctness tier, X-89).

    PDF-162: after the probes, the page selection the real run resolves is
    resolved here too, from the page counts those probes already read (no second
    open, no secret), and its refusal is RAISED -- the real run's own exception.
    An input locked behind a supplied password yields no count and is skipped."""
    refusal: PdfToolingError | None = plan.refusal
    if refusal is None and from_probe is not None:
        # PDF-159: the real run reads `--from` first (`_extract_stamp_layer`).
        from_path, from_engine_probe = from_probe
        try:
            from_refusal = predict_password_refusal(
                from_path, password=password, verb=verb, engine_probe=from_engine_probe
            )
        except (AuthError, FailureError) as error:
            raise _from_operand_error(error, from_path) from error
        if from_refusal is not None:
            refusal = _from_operand_error(from_refusal, from_path)
        elif from_page is not None:
            from_count = getattr(from_engine_probe, "page_count", None)
            if from_count is not None:
                _check_from_page(from_page, from_count, from_path)
    if refusal is None:
        refusal = predict_password_refusal(
            source, password=password, verb=verb, engine_probe=engine_probe
        )
        source_count = getattr(engine_probe, "page_count", None)
        if refusal is None and source_count is not None:
            _select_pages(source, pages_spec, source_count, verb=verb)
    detail = plan.detail()
    if refusal is not None and plan.refusal is None:
        detail = {**detail, "would_exit": refusal.exit_code, "planned_refusal": "AuthError"}
    # PDF-52 (`d01c9d52fb`): the pair rides along on every arm of this dry
    # tier -- including the refusal arm just above (D2's boundary arm ii).
    # A dry run never reads the secret, so `verified` is unconditionally
    # `False` here. Shared by `watermark` and `stamp` (this is their one
    # dry-run helper).
    detail = {**detail, **password_detail([password], verified=False)}
    item = ItemResult(
        input=str(source),
        output=str(target),
        ok=refusal is None,
        exit_code=(refusal.exit_code if refusal is not None else plan.would_exit),
        message=(f"planned: {verb}" if refusal is None else refusal.message),
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
        warnings=warnings,
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
    password: PasswordSource = NO_PASSWORD,
) -> OperationResult:
    """Composite a generated text layer onto the selected pages (Design D3).

    One layer is rendered per DISTINCT selected-page geometry (`/MediaBox`
    width/height), cached and reused across every page sharing that size --
    determinism and cost, per §D3. A rotated page (`/Rotate 90`) still
    receives the layer in UNROTATED page space, so the watermark rotates
    with the page's own content when displayed; that is documented,
    intended behaviour, not a defect.

    PDF-151 (`OR-71`): every character of `text` the base-14 font cannot draw
    (outside its WinAnsi encoding, including C0 controls and U+007F) is drawn
    as `?`, and one run-level warning names each as U+XXXX. The check is pure
    and precedes the dry/real fork, so `--dry-run` predicts the same warning.
    """
    reject_missing_sources([source])
    text, text_warning = _drawable_text(text)
    text_warnings = (text_warning,) if text_warning else ()
    target = _resolve_target(source, output=output, in_place=in_place, verb=VERB_WATERMARK)
    plan = plan_filesystem([target], out_dir=None, policy=policy, kind="pdf", sources=[source])
    if policy.dry_run:
        return _dry_run_result(
            VERB_WATERMARK,
            source=source,
            target=target,
            plan=plan,
            password=password,
            warnings=text_warnings,
            engine_probe=DryOpenProbe(composite=True),
            pages_spec=pages_spec,
        )

    started = time.monotonic()
    bytes_before = source.stat().st_size
    structure_engine = require_composite()  # X-76: "composite" (pypdf only)
    compose_engine = require_compose(capability="text-layer")
    resolver = PasswordResolver(password)

    try:
        secret = resolver.for_source(source)
        with structure_engine.open_document(source, password=secret) as document:
            page_count = document.page_count
            selected = _select_pages(source, pages_spec, page_count, verb=VERB_WATERMARK)

            # Per-page geometry comes from the EXISTING `read_document_info(...,
            # pages=True)` path -- `rotate`'s own precedent (`ops/pages.py`):
            # never a new port method for a fact an existing one already reports.
            info = structure_engine.read_document_info(source, pages=True, password=secret)
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

        bytes_after = atomic.bytes_written
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
            warnings=_blank_warning(tuple(blank)) + text_warnings,
            duration_ms=0,
        )
    finally:
        resolver.clear()


# --------------------------------------------------------------------------- #
# `stamp`
# --------------------------------------------------------------------------- #


def _validate_from_path(from_path: Path) -> None:
    classify_operand(
        from_path,
        missing_message=f"--from: no such file: {from_path}",
        directory_message=f"--from: expected a PDF file, not a directory: {from_path}",
    )


def _from_operand_error(error: PdfToolingError, from_path: Path) -> PdfToolingError:
    """The `--from` operand's wrapped refusal, shared by the real path and the dry probe."""
    if isinstance(error, AuthError):
        # B-074: names the DOCUMENT, never a secret -- `redacted` unset.
        return AuthError(
            f"a password is required to open --from ({from_path}); {error.message}",
            path=str(from_path),
        )
    return FailureError(f"--from is malformed ({from_path}): {error.message}", path=str(from_path))


def _extract_stamp_layer(
    from_path: Path, from_page: int, *, password: Secret | None = None
) -> bytes:
    """Design §D4.5 -- resolve `--from`/`--from-page` into a one-page PDF,
    BEFORE the target document is ever opened, so a bad `--from` refuses
    without touching the target at all. Reuses the EXISTING D10 primitive
    (`open_document` + `new_writer` + `append_pages` + `write`) rather than
    a new adapter method -- extracting one page IS what that primitive
    already does.

    PDF-37: ``--from`` is checked against the SAME global secret as
    ``source`` -- one shared ``--password-file`` flag, reused wherever it is
    needed within one invocation.
    """
    _validate_from_path(from_path)
    engine = require_structure()  # X-76: unqualified -- pypdf is primary
    try:
        with engine.open_document(from_path, password=password) as from_document:
            from_page_count = from_document.page_count
            _check_from_page(from_page, from_page_count, from_path)
            # PDF-116 D2: a layer buffer, never an output; it must not donate or read XMP.
            writer = engine.new_writer(carry_metadata=False)
            writer.append_pages(from_document, [from_page])
            buffer = io.BytesIO()
            writer.write(buffer)
            return buffer.getvalue()
    except (AuthError, FailureError) as error:
        raise _from_operand_error(error, from_path) from error


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
    password: PasswordSource = NO_PASSWORD,
) -> OperationResult:
    """Composite an existing PDF page (`--from`/`--from-page`) onto the
    selected pages of *source* (Design D4.5)."""
    reject_missing_sources([source])
    target = _resolve_target(source, output=output, in_place=in_place, verb=VERB_STAMP)
    plan = plan_filesystem([target], out_dir=None, policy=policy, kind="pdf", sources=[source])
    if policy.dry_run:
        return _dry_run_result(
            VERB_STAMP,
            source=source,
            target=target,
            plan=plan,
            password=password,
            engine_probe=DryOpenProbe(composite=True),
            from_probe=(from_path, DryOpenProbe(composite=False)),
            pages_spec=pages_spec,
            from_page=from_page,
        )

    started = time.monotonic()
    bytes_before = source.stat().st_size
    resolver = PasswordResolver(password)

    try:
        layer_bytes = _extract_stamp_layer(
            from_path, from_page, password=resolver.for_source(from_path)
        )

        structure_engine = require_composite()  # X-76: "composite" (pypdf only)
        secret = resolver.for_source(source)
        with structure_engine.open_document(source, password=secret) as document:
            page_count = document.page_count
            selected = _select_pages(source, pages_spec, page_count, verb=VERB_STAMP)

            # Design D3.1 -- writer created, full range appended, BEFORE compositing.
            writer = structure_engine.new_writer()
            writer.append_pages(document, list(range(1, page_count + 1)))

            outcome = structure_engine.composite_layer(
                writer, layer=layer_bytes, pages=selected, position=position
            )

            with AtomicWriter(target, policy=policy, kind="pdf") as atomic:
                writer.write(atomic.stream)

        bytes_after = atomic.bytes_written
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
    finally:
        resolver.clear()
