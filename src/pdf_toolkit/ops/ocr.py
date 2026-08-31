"""``ocr`` -- the OCR verb: per-page render -> text-only PDF -> overlay on the
ORIGINAL page (PDF-15).

Framework-free per L2: no ``typer``/``click`` import, and **no engine library
import either** -- ``tests/test_import_boundaries.py``'s ``ENGINE_MODULES``
walk has no ``TYPE_CHECKING`` exemption, so every pypdf/pypdfium2/tesseract
byte crosses a port boundary as a plain ``bytes``/dataclass/``PIL.Image``,
never a ``pypdf.PageObject`` or a ``pypdfium2`` document. This module prints
nothing and calls no ``sys.exit``.

THE HEADLINE PROPERTY, AND WHERE IT LIVES
------------------------------------------
Pixels are never touched: the page's image XObject is never re-rendered.
Step 4 below composites the tesseract-produced text-only layer **onto the
original page object**, via ``StructureEngine.composite_layer`` (PDF-14's own
primitive, D4's docstring names this module by ID) -- the same
``new_writer()`` + ``append_pages()`` + ``write()`` path every other
page-addressing verb already uses. The image XObject is carried through by
``append_pages``'s own clone, exactly as PDF-10's ``/DCTDecode`` passthrough
and PDF-12's ``--lossless`` gate already prove that mechanism preserves.

Design §D4 route (a) -- the geometry gap, closed in the ADAPTER, not here
---------------------------------------------------------------------------
``composite_layer`` takes no transform argument: it is a raw
``page.merge_page``, content-stream concatenation only. So the layer this
module hands it must already be sized and rotated to the ORIGINAL page's own
UNROTATED space before it ever reaches this module -- which is exactly what
``OcrEngine.text_layer`` (``adapters/tesseract_ocr.py``) does, because an
engine import (pypdf, to apply that transform) is legal there and forbidden
here. See that adapter's ``_normalize_layer_geometry`` for the derivation.

THE ENGINE IS DEMANDED LAZILY -- AND THAT IS DELIBERATE, NOT AN OVERSIGHT
---------------------------------------------------------------------------
``--skip-text-pages`` (Design §D2 step 1) copies an already-text page through
UNTOUCHED: "No render, no spawn." Taken to its natural conclusion: an
invocation whose ENTIRE selection is skip-eligible never needs the OCR engine
at all, and demanding it anyway would refuse a run that never actually
needed tesseract. So ``require_ocr()`` (plus the ``--lang`` availability
check, itself the same read-only ``--list-langs`` resolution ``doctor``
already performs) is called **once**, lazily, the first time this run's own
selection is found to contain a page that is not skip-eligible -- computed
identically in BOTH ``--dry-run`` and a real run (Design §D12.1's OR-7 row),
so ``dry == real`` holds by construction rather than by two independently
written predictions kept in sync by hand.

Nothing here writes. Every byte reaches disk through ``safety.AtomicWriter``;
the OCR engine's own scratch files (one input image, one output base, reused
across every page of the run -- Design §D2's sequential model) live inside
``safety.atomic.ScratchDir``, never beside a destination.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pdf_toolkit.errors import EngineMissingError, NoInputError, PdfToolkitError, UsageError
from pdf_toolkit.models import SCHEMA_VERSION as _SCHEMA_VERSION
from pdf_toolkit.models import ItemResult, OperationResult, PageInfo, PageRange
from pdf_toolkit.ops.pagerange import ALL_PAGES_TOKEN, parse
from pdf_toolkit.ports.ocr import OcrEngine, require_ocr
from pdf_toolkit.ports.raster import require_raster
from pdf_toolkit.ports.structure import StructureEngine, require_structure
from pdf_toolkit.safety.atomic import AtomicWriter, ScratchDir, plan_output_set
from pdf_toolkit.safety.naming import render_name
from pdf_toolkit.safety.paths import canonical, check_output_collisions, ensure_destination_writable
from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = [
    "DEFAULT_DPI",
    "DEFAULT_LANG",
    "DEFAULT_OCR_NAME_TEMPLATE",
    "DEFAULT_PSM",
    "DEFAULT_TIMEOUT_S",
    "PSM_RANGE",
    "VERB_OCR",
    "ocr_run",
]

VERB_OCR: Final[str] = "ocr"

#: D5's own defaults.
DEFAULT_LANG: Final[str] = "eng"
DEFAULT_DPI: Final[int] = 300
DEFAULT_PSM: Final[int] = 3

#: PLAN.md §5.4 -- 120 s per page. `ocr` carries no `--timeout` flag (D5's
#: own flag table omits one, unlike `convert`'s), so this is fixed.
DEFAULT_TIMEOUT_S: Final[float] = 120.0

#: D5 -- `--dpi` bounds, `--psm` bounds (0 excluded separately, D5's own
#: refusal: orientation-only, produces no text layer).
DPI_RANGE: Final[tuple[int, int]] = (72, 1200)
PSM_RANGE: Final[tuple[int, int]] = (0, 13)

#: `ocr --out-dir`'s default filename template -- one output per input, same
#: stem, mirroring `compress`'s own `DEFAULT_COMPRESS_NAME_TEMPLATE` shape
#: (the landed precedent D11.1 names for this verb's arity).
DEFAULT_OCR_NAME_TEMPLATE: Final[str] = "{stem}.{ext}"

_NAME_WITHOUT_OUT_DIR: Final[str] = (
    "--name templates a filename inside --out-dir; pass --out-dir, "
    "-O to name one file, or --in-place to overwrite the input"
)


# --------------------------------------------------------------------------- #
# Shared validation and target resolution -- `ops/optimize.py::compress_run`'s
# own donor shape (D11.1: "follow the landed compress precedent exactly").
# --------------------------------------------------------------------------- #


def _validate_sources(sources: Sequence[Path]) -> None:
    for source in sources:
        if not source.exists():
            raise NoInputError("no such file", path=str(source))
        if source.is_dir():
            raise UsageError("expected a PDF file, not a directory", path=str(source))


@dataclass(frozen=True, slots=True)
class _OcrTarget:
    source: Path
    target: Path


def _resolve_ocr_targets(
    sources: Sequence[Path],
    *,
    output: Path | None,
    out_dir: Path | None,
    name_template: str | None,
    in_place: bool,
) -> list[_OcrTarget]:
    """Every source's own destination, computed before anything runs.

    ``ocr a.pdf b.pdf -O one.pdf`` (two inputs, one ``-O`` target) is an
    **arity** error refused by ``cli/cmd_ocr.py`` before this function is
    ever reached -- ``output`` here is only ever paired with exactly one
    source, mirroring ``compress``'s own D-12.0a precedent.
    """
    if in_place:
        return [_OcrTarget(source=source, target=source) for source in sources]
    if output is not None:
        return [_OcrTarget(source=sources[0], target=output)]
    if out_dir is None:  # pragma: no cover - the CLI layer requires a destination first
        raise UsageError("ocr requires --output, --out-dir, or --in-place")
    template = name_template if name_template is not None else DEFAULT_OCR_NAME_TEMPLATE
    return [
        _OcrTarget(
            source=source,
            target=render_name(template, out_dir=out_dir, stem=source.stem, ext="pdf", index=index),
        )
        for index, source in enumerate(sources, start=1)
    ]


@dataclass(frozen=True, slots=True)
class _FilesystemPlan:
    would_exit: int
    would_refuse: dict[str, object] | None
    message: str | None

    @property
    def refused(self) -> bool:
        return self.would_refuse is not None

    def detail(self) -> dict[str, object]:
        payload: dict[str, object] = {"would_exit": self.would_exit}
        if self.would_refuse is not None:
            payload["would_refuse"] = self.would_refuse
        return payload


def _plan_filesystem(
    targets: Sequence[Path], *, out_dir: Path | None, policy: SafetyPolicy
) -> _FilesystemPlan:
    """The filesystem tier, through the SHARED primitives only.

    **Widened beyond ``compress``'s own donor shape for the single-target
    (``-O``, ``out_dir is None``) case**, for the same reason
    ``ops/office.py::_plan_filesystem`` is (see that function's own
    docstring): ``ocr``'s engine can be legitimately ABSENT, so the
    writability check must run in BOTH modes, before ``require_ocr()`` is
    ever reached -- not only under ``--dry-run``, which is where ``compress``
    (a hard, always-present dependency) leaves it.
    """
    plan = plan_output_set(targets, out_dir=out_dir, policy=policy)
    if plan.refusal is not None:
        return _FilesystemPlan(
            would_exit=plan.would_exit,
            would_refuse=plan.would_refuse,
            message=plan.refusal.message,
        )
    if out_dir is None:
        for target in targets:
            try:
                ensure_destination_writable(canonical(target).parent, as_written=target.parent)
            except PdfToolkitError as refusal:
                if not policy.dry_run:
                    raise
                return _FilesystemPlan(
                    would_exit=refusal.exit_code,
                    would_refuse=refusal.to_dict(),
                    message=refusal.message,
                )
    return _FilesystemPlan(would_exit=plan.would_exit, would_refuse=None, message=None)


def _resolve_pages(pages_spec: str | None, page_count: int) -> PageRange:
    """Set semantics (PLAN.md §4.3 names `ocr` in the set-semantics list)."""
    spec = pages_spec if pages_spec is not None else ALL_PAGES_TOKEN
    return parse(spec, page_count, ordered=False)


# --------------------------------------------------------------------------- #
# `--lang` availability -- D5's own amendment: the port, never a re-parse.
# --------------------------------------------------------------------------- #


def _lang_install_hint(missing: Sequence[str]) -> str:
    import sys

    packs = " ".join(f"tesseract-ocr-{code}" for code in missing)
    if sys.platform == "darwin":
        return f"brew install tesseract-lang  # ({', '.join(missing)})"
    return f"apt install {packs}"


def _check_lang_available(adapter: OcrEngine, lang: str) -> None:
    """D5/AC9 -- every ``--lang`` component must be in ``languages()``'s own
    enumeration, or exit 3 (an install situation, not a usage mistake) with
    an install hint naming the pack."""
    available = set(adapter.languages())
    missing = [part for part in lang.split("+") if part not in available]
    if missing:
        raise EngineMissingError(
            f"OcrEngine: tessdata language pack(s) not installed: {', '.join(missing)}. "
            f"Install with: {_lang_install_hint(missing)}. "
            f"Run 'pdftoolkit doctor' to see what is installed."
        )


def _page_needs_engine(page: PageInfo, *, skip_text_pages: bool) -> bool:
    return not (skip_text_pages and page.has_text)


def _selected_pages(
    structure_engine: StructureEngine, source: Path, pages_spec: str | None
) -> tuple[PageInfo, ...]:
    """Every SELECTED page's own :class:`PageInfo`, in ascending page order
    (set semantics -- PLAN.md §4.3)."""
    info = structure_engine.read_document_info(source, pages=True)
    selection = _resolve_pages(pages_spec, info.page_count)
    if selection.is_empty:
        raise NoInputError(
            f"{source}: --pages {(pages_spec or ALL_PAGES_TOKEN)!r} resolved to zero pages; "
            f"nothing to {VERB_OCR}",
            path=str(source),
        )
    selected_numbers = sorted(selection.as_set())
    by_number = {page.number: page for page in info.pages}
    return tuple(by_number[number] for number in selected_numbers)


# --------------------------------------------------------------------------- #
# The verb.
# --------------------------------------------------------------------------- #


def ocr_run(
    sources: Sequence[Path],
    *,
    lang: str,
    dpi: int,
    psm: int,
    skip_text_pages: bool,
    pages_spec: str | None,
    output: Path | None,
    out_dir: Path | None,
    name_template: str | None,
    in_place: bool,
    policy: SafetyPolicy,
) -> OperationResult:
    """OCR every source, one output per input, in input order.

    Under ``--dry-run`` no operational engine call happens (AC16): the
    engine/``--lang`` availability check -- when the selection needs it at
    all -- is the SAME read-only resolution ``doctor`` performs (``--version``
    / ``--list-langs``), never the operational ``textonly_pdf=1`` call.
    """
    _validate_sources(sources)
    if name_template is not None and out_dir is None:
        raise UsageError(_NAME_WITHOUT_OUT_DIR)

    planned = _resolve_ocr_targets(
        sources, output=output, out_dir=out_dir, name_template=name_template, in_place=in_place
    )
    targets = [item.target for item in planned]
    check_output_collisions(targets)

    # The filesystem tier is checked FIRST -- before the engine is ever
    # demanded (`plan_output_set`'s own no-clobber loop, plus the widened
    # writability check above, both raise immediately for a real run) --
    # so a run that is going to be refused on filesystem grounds never
    # spawns tesseract to find that out (the same ordering rationale
    # `ensure_destination_writable`'s own docstring states: "before an
    # engine runs").
    plan = _plan_filesystem(targets, out_dir=out_dir, policy=policy)

    structure_engine = require_structure()
    pages_by_source: dict[Path, tuple[PageInfo, ...]] = {
        item.source: _selected_pages(structure_engine, item.source, pages_spec) for item in planned
    }

    # The lazy engine/`--lang` check (module docstring): computed identically
    # in both modes, so `dry == real` on this row holds by construction.
    needs_engine = any(
        _page_needs_engine(page, skip_text_pages=skip_text_pages)
        for pages in pages_by_source.values()
        for page in pages
    )
    ocr_adapter: OcrEngine | None = None
    if needs_engine and not plan.refused:
        ocr_adapter = require_ocr()
        _check_lang_available(ocr_adapter, lang)

    if policy.dry_run:
        detail = plan.detail()
        items = tuple(
            ItemResult(
                input=str(item.source),
                output=str(item.target),
                ok=not plan.refused,
                exit_code=plan.would_exit,
                message=("planned: ocr" if not plan.refused else plan.message),
                bytes_before=item.source.stat().st_size,
                bytes_after=None,
                duration_ms=0,
                detail=detail,
            )
            for item in planned
        )
        return OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=VERB_OCR,
            dry_run=True,
            items=items,
            warnings=(),
            duration_ms=0,
        )

    raster_engine = require_raster()

    warnings: list[str] = []
    written: list[ItemResult] = []
    scratch = ScratchDir() if needs_engine else None
    scratch_root: Path | None = scratch.__enter__() if scratch is not None else None
    try:
        for item in planned:
            started = time.monotonic()
            bytes_before = item.source.stat().st_size
            pages = pages_by_source[item.source]

            with structure_engine.open_document(item.source) as document:
                page_count = document.page_count
                ocrd: list[int] = []
                skipped: list[int] = []
                for page in pages:
                    if skip_text_pages and page.has_text:
                        skipped.append(page.number)
                        continue
                    # nosec B101 - narrowed by `needs_engine` above (module docstring): any
                    # page reaching this branch already satisfies `_page_needs_engine`.
                    assert ocr_adapter is not None and scratch_root is not None  # nosec B101
                    rendered = raster_engine.render_page(
                        str(item.source),
                        page.number,
                        dpi=float(dpi),
                        width_px=None,
                        grayscale=False,
                    )
                    try:
                        layer_bytes = ocr_adapter.text_layer(
                            rendered.image,
                            lang=lang,
                            psm=psm,
                            dpi=rendered.dpi_effective,
                            page_width_pt=page.width_pt,
                            page_height_pt=page.height_pt,
                            rotation=page.rotation,
                            timeout=DEFAULT_TIMEOUT_S,
                            scratch_dir=scratch_root,
                        )
                    finally:
                        # Design §D2: one page of pixels held at a time.
                        rendered.image.close()
                    outcome = structure_engine.composite_layer(
                        document, layer=layer_bytes, pages=[page.number], position="overlay"
                    )
                    ocrd.extend(outcome.pages_composited)

                writer = structure_engine.new_writer()
                writer.append_pages(document, list(range(1, page_count + 1)))
                with AtomicWriter(item.target, policy=policy, kind="pdf") as atomic:
                    writer.write(atomic.stream)

            bytes_after = item.target.stat().st_size
            duration_ms = int((time.monotonic() - started) * 1000)
            written.append(
                ItemResult(
                    input=str(item.source),
                    output=str(item.target),
                    ok=True,
                    exit_code=0,
                    message=(
                        f"ocr'd {len(ocrd)} page(s), skipped {len(skipped)} already-text page(s)"
                    ),
                    bytes_before=bytes_before,
                    bytes_after=bytes_after,
                    duration_ms=duration_ms,
                    detail={"pages_ocrd": sorted(ocrd), "pages_skipped": sorted(skipped)},
                )
            )
    finally:
        if scratch is not None:
            scratch.__exit__(None, None, None)

    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=VERB_OCR,
        dry_run=False,
        items=tuple(written),
        warnings=tuple(warnings),
        duration_ms=0,
    )
