"""``rasterize`` — PDF pages to images, one file per page (Design §D2-D6).

Framework-free per L2: no typer/click import (PDF-06's AST test enforces it).
Everything above the port is naming, planning, parallelism and encoding; the
render itself is one call into ``ports.raster.require_raster()`` (X-76:
selected by capability, never by adapter name).

**Plan-then-write (Design §D4).** Every target path is resolved — through
``safety.naming.render_name``, containment-checked by the shared renderer
itself — and every no-clobber/collision check runs, all **before the first
page is rendered**. A planning failure writes nothing.

**PLAN §12 R-08, the core of this module (Design §D5).** Per-worker document
handles, never shared: a worker receives a path and page numbers, never a
document. ``ops/raster.py`` never opens a pdfium document itself — planning
uses ``StructureEngine`` only, for ``page_count``, opened and closed in this
module before any worker starts; rendering happens entirely inside
:func:`_render_chunk`, a **module-level**, picklable-argument function so the
same code path serves both ``--threads 1`` (the documented reproduction
switch, D5.6) and ``--threads 8``.

**Deviation from Design §D5.5's literal prose, recorded here (Implementation
Log detail):** production uses ``ProcessPoolExecutor``, not
``ThreadPoolExecutor``. D5.5 anticipated threads as the default with a
process pool as an available fallback ("a one-line change"); live-testing
this exact implementation found that concurrent, real multi-threaded pdfium
rendering — even with fully isolated per-worker documents, exactly as D5.3
specifies — reliably corrupts the process heap (``free(): invalid pointer``,
``malloc(): unaligned tcache chunk detected``, ``double free or corruption``,
reproduced with 2 and with 8 concurrent threads on pypdfium2 5.13.0). That is
precisely the failure mode D5 itself names ("threading over a C-extension
boundary can crash the interpreter... no try/except catches that, so the
structure has to make it impossible rather than handled") — a process pool
makes it structurally impossible, since each worker has a wholly separate
address space, while a thread pool did not. :func:`_render_chunk` is
unchanged either way — it is the SAME module-level, picklable-argument
function AC4/AC7 require, so this is exactly the "one-line change" D5.5
described, applied in the direction the evidence pointed rather than the
direction the prose assumed.

``ops/raster.py`` never calls ``open(..., "w")``, ``Path.write_bytes``,
``os.replace`` or creates a directory of its own — every byte reaches disk
through ``safety.AtomicWriter``, and ``--out-dir`` is created only via
``safety.atomic.plan_output_set`` (Design §D12, extended B-054). No ``ops/``
allowlist entry is needed in ``tests/test_import_boundaries.py``.

**The filesystem tier runs in both modes (B-054, extending X-67).**
``plan_output_set`` is called unconditionally, so a ``--dry-run`` over an
occupied target or an unwritable ``--out-dir`` predicts the same exit code a
real run produces, rather than entering cleanly and being contradicted by it.

**The pool does not survive a signal to this process (B-055).** The
``ProcessPoolExecutor`` this module opens is created through
:func:`~pdf_toolkit.ops.procpool.guarded_process_pool`, not the bare class —
see that module's docstring for why a plain ``with ProcessPoolExecutor(...)``
here leaves every render worker running (and writing) after a SIGTERM to the
parent, why that same constraint rules out a thread pool (X-104) as the fix
for this too, and exactly what is and is not guaranteed once a signal
arrives.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import IO, TYPE_CHECKING, Final

from pdf_toolkit.errors import EngineMissingError, NoInputError, PdfToolkitError
from pdf_toolkit.models import SCHEMA_VERSION as _SCHEMA_VERSION
from pdf_toolkit.models import ItemResult, OperationResult
from pdf_toolkit.ops.batch import BatchLedger, preflight_operands
from pdf_toolkit.ops.document_password import NO_PASSWORD, PasswordResolver, PasswordSource
from pdf_toolkit.ops.pagerange import ALL_PAGES_TOKEN, parse
from pdf_toolkit.ops.procpool import guarded_process_pool
from pdf_toolkit.ports import BROKEN_INSTALL_HINT
from pdf_toolkit.ports.raster import require_raster
from pdf_toolkit.ports.structure import require_structure
from pdf_toolkit.safety.atomic import AtomicWriter, plan_output_set
from pdf_toolkit.safety.naming import render_name
from pdf_toolkit.safety.paths import check_output_collisions
from pdf_toolkit.safety.policy import SafetyPolicy
from pdf_toolkit.secret import Secret

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

__all__ = ["DEFAULT_NAME_TEMPLATE", "rasterize_document"]

VERB: Final[str] = "rasterize"

#: Design §D4. Zero-padded to four so lexical order matches page order
#: through 9999 — the plan's largest sample is 482 pages.
DEFAULT_NAME_TEMPLATE: Final[str] = "{stem}-{page:04}.{ext}"

#: Design §D6, D3. Not inherited from Pillow defaults, which move between
#: versions -- explicit and pinned.
_DEFAULT_QUALITY: Final[int] = 85
_PNG_COMPRESS_LEVEL: Final[int] = 9
_JPEG_SUBSAMPLING: Final[int] = 0
_TIFF_COMPRESSION: Final[str] = "tiff_deflate"
_WEBP_METHOD: Final[int] = 6

#: One flat work item, exactly what crosses into a worker: a path (never a
#: document), a page number, a target path, and the render parameters for
#: that one page. Every field is plain, picklable data (AC4/AC7).
#:
#: PDF-37's ``password`` slot is the REVEALED plaintext (``str | None``),
#: never a :class:`~pdf_toolkit.secret.Secret` -- a ``Secret`` refuses to
#: pickle by design (its own ``__reduce__``), and this tuple crosses a real
#: ``ProcessPoolExecutor`` boundary. Revealed exactly once per source, in
#: THIS process, only after `read_encryption` has confirmed the source is
#: actually encrypted (`ops/document_password.PasswordResolver`) -- so a
#: plain document never pays this cost and the plaintext is never bound to a
#: name that outlives the tuple it travels in.
_WorkItem = tuple[int, str, int, str, float | None, int | None, str | None]


def _ensure_format_supported(fmt: str) -> None:
    """Exit 3 with an install hint, never a silent fallback to another
    format (Design §D7)."""
    if fmt != "webp":
        return
    from PIL import features

    if not features.check("webp"):
        raise EngineMissingError(
            "RasterEngine cannot write webp: this Pillow build lacks WEBP support. "
            f"Install it with: {BROKEN_INSTALL_HINT}. "
            "Run 'pdftoolkit doctor' to see which engines resolved."
        )


def _dry_run_message(page_number: int, fmt: str, dpi: float | None, width_px: int | None) -> str:
    if width_px is not None:
        return f"page {page_number}: planned {fmt} @ width {width_px}px"
    return f"page {page_number}: planned {fmt} @ {dpi:g} dpi"


def _plan_pages(
    source: Path, pages_spec: str | None, *, password: Secret | None = None
) -> tuple[int, ...]:
    """The selection for one source: a sorted, deduplicated SET (PLAN §4.3 —
    `rasterize` is a set-semantics verb). ``page_count`` is read from a
    short-lived ``StructureEngine`` handle, closed before this function
    returns and well before any worker starts (Design §D5.3, AC5)."""
    engine = require_structure()
    with engine.open_document(source, password=password) as document:
        page_count = document.page_count

    spec = pages_spec if pages_spec is not None else ALL_PAGES_TOKEN
    selection = parse(spec, page_count, ordered=False)
    if selection.is_empty:
        raise NoInputError(
            f"{source}: --pages {spec!r} resolved to zero pages; nothing to write",
            path=str(source),
        )
    return selection.indices


def _chunk(work: list[_WorkItem], threads: int) -> list[list[_WorkItem]]:
    """At most ``min(threads, len(work))`` contiguous chunks over *work*,
    which is already ordered input-major, page-minor (Design §D5.2) — so a
    contiguous split keeps one input's pages together whenever the input
    isn't itself split across a chunk boundary by an uneven thread count."""
    if not work:
        return []
    n = max(1, min(threads, len(work)))
    size, remainder = divmod(len(work), n)
    chunks: list[list[_WorkItem]] = []
    start = 0
    for index in range(n):
        extra = 1 if index < remainder else 0
        end = start + size + extra
        if start < end:
            chunks.append(work[start:end])
        start = end
    return chunks


def _encode(image: Image, stream: IO[bytes], *, fmt: str, quality: int | None) -> None:
    """Encode *image* into *stream* (an ``AtomicWriter.stream`` — Design §D12:
    never ``writer.path``, never a path string). Encoder parameters are
    explicit and pinned (Design §D6), not inherited from Pillow defaults."""
    if fmt == "png":
        image.save(stream, format="PNG", compress_level=_PNG_COMPRESS_LEVEL)
    elif fmt == "jpeg":
        image.save(
            stream,
            format="JPEG",
            quality=quality if quality is not None else _DEFAULT_QUALITY,
            subsampling=_JPEG_SUBSAMPLING,
            optimize=False,
        )
    elif fmt == "tiff":
        image.save(stream, format="TIFF", compression=_TIFF_COMPRESSION)
    elif fmt == "webp":
        image.save(
            stream,
            format="WEBP",
            quality=quality if quality is not None else _DEFAULT_QUALITY,
            method=_WEBP_METHOD,
            lossless=False,
        )
    else:  # pragma: no cover - cmd_rasterize.py validates the format enum
        raise AssertionError(f"unknown raster format {fmt!r}")


def _render_one(
    source: str,
    page_number: int,
    target: str,
    *,
    dpi: float | None,
    width_px: int | None,
    fmt: str,
    quality: int | None,
    grayscale: bool,
    policy: SafetyPolicy,
    password: str | None = None,
) -> ItemResult:
    """Render, encode and write exactly one page. Everything a worker does
    for one work item, in one call — nothing opened here escapes it
    (Design §D5.3): the adapter opens and closes its own document, and only
    this function's plain ``ItemResult`` return crosses back out.

    Args:
        password: PDF-37 -- the REVEALED plaintext, or ``None``. See
            :data:`_WorkItem`'s own docstring for why this is a plain
            string rather than a :class:`~pdf_toolkit.secret.Secret`.
    """
    started = time.monotonic()
    source_path = Path(source)
    target_path = Path(target)
    bytes_before = source_path.stat().st_size if source_path.exists() else None

    try:
        adapter = require_raster(capability="render")
        rendered = adapter.render_page(
            source, page_number, dpi=dpi, width_px=width_px, grayscale=grayscale, password=password
        )
    except PdfToolkitError as error:
        duration_ms = int((time.monotonic() - started) * 1000)
        return ItemResult(
            input=source,
            output=target,
            ok=False,
            exit_code=error.exit_code,
            message=error.message,
            bytes_before=bytes_before,
            bytes_after=None,
            duration_ms=duration_ms,
        )

    with AtomicWriter(target_path, policy=policy, kind="image") as writer:
        _encode(rendered.image, writer.stream, fmt=fmt, quality=quality)

    duration_ms = int((time.monotonic() - started) * 1000)
    message = (
        f"page {page_number}: {rendered.width_px}x{rendered.height_px} "
        f"{fmt} @ {rendered.dpi_effective:g} dpi"
    )
    return ItemResult(
        input=source,
        output=target,
        ok=True,
        exit_code=0,
        message=message,
        bytes_before=bytes_before,
        bytes_after=target_path.stat().st_size,
        duration_ms=duration_ms,
    )


def _render_chunk(
    items: list[_WorkItem],
    *,
    fmt: str,
    quality: int | None,
    grayscale: bool,
    policy: SafetyPolicy,
) -> list[tuple[int, ItemResult]]:
    """The worker `--threads` dispatches (Design §D5.5). Module-level, and
    every argument and return value is plain, picklable data (AC4/AC7) — a
    process boundary is exactly what production crosses too (module
    docstring: real concurrent pdfium rendering corrupts the heap even with
    per-worker document isolation, so ``ProcessPoolExecutor`` is what
    :func:`rasterize_document` uses, not ``ThreadPoolExecutor``). AC7 proves
    this same function against a single-worker ``ThreadPoolExecutor``
    baseline instead, the one thread-pool shape that cannot race."""
    return [
        (
            slot,
            _render_one(
                source,
                page_number,
                target,
                dpi=dpi,
                width_px=width_px,
                fmt=fmt,
                quality=quality,
                grayscale=grayscale,
                policy=policy,
                password=password,
            ),
        )
        for slot, source, page_number, target, dpi, width_px, password in items
    ]


def rasterize_document(
    sources: list[Path],
    *,
    pages_spec: str | None,
    dpi: float | None,
    width_px: int | None,
    fmt: str,
    quality: int | None,
    grayscale: bool,
    name_template: str | None,
    out_dir: Path,
    policy: SafetyPolicy,
    password: PasswordSource = NO_PASSWORD,
) -> OperationResult:
    """Rasterize every selected page of every source into ``out_dir``.

    ``items`` carries **one row per rendered page** (Design §D9 as corrected):
    ``input`` is the source PDF, ``output`` the image path, ``message`` the
    measured render facts in the pinned shape
    ``"page {page}: {width}x{height} {ext} @ {dpi_effective:g} dpi"``.

    PDF-37: the global ``--password-file`` slot is resolved at most once per
    source (`ops/document_password.PasswordResolver`), during the SAME
    ``_plan_pages`` open every source already pays for page count -- so the
    resolvability tier is predicted for free, in both modes.
    """
    preflight_operands(sources)
    ledger = BatchLedger(sources)

    # Exit 3 up front, before any planning work — Design §D7.
    require_raster(capability="render")
    _ensure_format_supported(fmt)

    template = name_template if name_template is not None else DEFAULT_NAME_TEMPLATE

    resolver = PasswordResolver(password)
    secret_by_source: dict[Path, Secret | None] = {}
    planned: list[tuple[Path, int]] = []

    def _plan_one(source: Path) -> list[int]:
        secret = resolver.for_source(source)
        secret_by_source[source] = secret
        return list(_plan_pages(source, pages_spec, password=secret))

    try:
        for source in sources:
            # `_plan_pages` opens the document: a corrupt or unreadable source
            # fails HERE, before a single page is rendered, and must cost only
            # its own pages.
            page_numbers = ledger.guard(
                source,
                lambda source=source: _plan_one(source),  # type: ignore[misc]
            )
            for page_number in page_numbers or ():
                planned.append((source, page_number))
        return _rasterize_planned(
            sources,
            planned,
            ledger=ledger,
            secret_by_source=secret_by_source,
            fmt=fmt,
            dpi=dpi,
            width_px=width_px,
            quality=quality,
            grayscale=grayscale,
            template=template,
            out_dir=out_dir,
            policy=policy,
        )
    finally:
        resolver.clear()


def _rasterize_planned(
    sources: list[Path],
    planned: list[tuple[Path, int]],
    *,
    ledger: BatchLedger,
    secret_by_source: dict[Path, Secret | None],
    fmt: str,
    dpi: float | None,
    width_px: int | None,
    quality: int | None,
    grayscale: bool,
    template: str,
    out_dir: Path,
    policy: SafetyPolicy,
) -> OperationResult:
    rendered: list[tuple[Path, int, Path]] = []
    for index, (source, page_number) in enumerate(planned, start=1):
        target = render_name(
            template,
            out_dir=out_dir,
            stem=source.stem,
            ext=fmt,
            index=index,
            page=page_number,
        )
        rendered.append((source, page_number, target))

    targets = [target for _source, _page, target in rendered]
    # Data-independent (planned targets against each other) — checked
    # identically under --dry-run (Design §D4, matching split's own AC10).
    check_output_collisions(targets)

    source_sizes = {source: source.stat().st_size for source in sources}

    # B-054: the filesystem tier (--out-dir creation, writability, every
    # target's no-clobber) runs ONCE, unconditionally, in BOTH modes -- a real
    # run raises exactly as before (see the block below); a dry run captures
    # the first refusal instead (X-67, extended to a multi-target --out-dir
    # run).
    plan = plan_output_set(targets, out_dir=out_dir, policy=policy)

    if policy.dry_run:
        # A run-level refusal (an unwritable --out-dir) is not attributable
        # to one page, and this is not a loss of precision: rasterize's own
        # plan-then-write design (D4) means a planning failure writes
        # NOTHING -- not one page -- so applying the same prediction to
        # every item states exactly what the real run would have done,
        # mirroring merge's/compose's own single-target convention of one
        # refusal covering every item in the run.
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
                    _dry_run_message(page_number, fmt, dpi, width_px)
                    if plan.refusal is None
                    else plan.refusal.message
                ),
                bytes_before=source_sizes[source],
                bytes_after=None,
                duration_ms=0,
                detail=detail,
            )
            for source, page_number, target in rendered
        )
        return OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=VERB,
            dry_run=True,
            items=ledger.assemble(list(items)),
            warnings=(),
            duration_ms=0,
        )

    # Real run: plan_output_set already created --out-dir (chokepoint-confined,
    # Design §D12) and pre-flight checked every target for no-clobber/
    # writability -- BEFORE the first page is rendered, so a planning failure
    # writes nothing. It raised already if refused (the
    # `except PdfToolkitError: ... raise` inside plan_output_set, since
    # policy.dry_run is False here), so plan.refusal is always None below.
    # PDF-37: revealed HERE, in the main process, exactly once per source --
    # never inside a worker, and never kept around longer than building this
    # one picklable tuple (see `_WorkItem`'s own docstring for why a `Secret`
    # itself cannot make this trip).
    work: list[_WorkItem] = [
        (
            slot,
            str(source),
            page_number,
            str(target),
            dpi,
            width_px,
            secret.reveal() if (secret := secret_by_source.get(source)) is not None else None,
        )
        for slot, (source, page_number, target) in enumerate(rendered)
    ]
    chunks = _chunk(work, policy.threads)

    # Slot-indexed collection (Design §D5.4): ordering is never derived from
    # completion order, only ever from the slot each item was assigned at
    # planning time.
    collected: dict[int, ItemResult] = {}
    if chunks:
        # B-055: `guarded_process_pool` is `ProcessPoolExecutor` plus a
        # signal teardown -- see `ops/procpool.py`'s module docstring for
        # why a plain `with ProcessPoolExecutor(...) as executor:` here lets
        # every worker outlive a SIGTERM/SIGINT/SIGHUP to this process. The
        # happy path (no signal) is unchanged: same executor, same
        # submit/result loop, same `shutdown(wait=True)` on the way out.
        with guarded_process_pool(len(chunks)) as executor:
            futures = [
                executor.submit(
                    _render_chunk,
                    chunk,
                    fmt=fmt,
                    quality=quality,
                    grayscale=grayscale,
                    policy=policy,
                )
                for chunk in chunks
            ]
            for future in futures:
                for slot, item in future.result():
                    collected[slot] = item

    # Slot order is per-PAGE; `assemble` re-imposes per-SOURCE input order
    # around it and splices in any source that failed planning, so a failed
    # source appears exactly once, in its own command-line position.
    rendered_items = [collected[slot] for slot in range(len(work))]
    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=VERB,
        dry_run=False,
        items=ledger.assemble(rendered_items),
        warnings=(),
        duration_ms=0,
    )
