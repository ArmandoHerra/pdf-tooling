"""``compress`` + ``repair`` + ``linearize`` — pure plan/result functions over
``StructureEngine`` (PDF-12).

Framework-free per L2: no typer/click import (PDF-06's AST test enforces it),
and **no engine library import either** — every byte crosses the port
boundary through ``ports/structure.py``'s plain dataclasses
(``CompressOutcome``/``RepairOutcome``/``ImagePassOutcome``), never a
``pikepdf`` or ``pypdf`` object. That is what keeps the licence question
answerable by reading six port files, and it is the one discipline this
module is most tempted to break: **the conventional one-call PDF compressor
is AGPL-3.0+ and excluded by `PLAN.md` §7.2 (see §12 R-01/R-02)** —
`pikepdf`/libqpdf object streams plus an opt-in Pillow image pass is the
replacement, not a workaround.

Three verbs, four rules `PLAN.md` §12 R-02 already decided:

1. **`compress` reports a measurement, not a claim.** ``bytes_before`` /
   ``bytes_after`` are populated for every item (both already exist on
   ``ItemResult`` — no model change, no ``SCHEMA_VERSION`` bump); the ratio
   is derived in the *message*, never stored as a new field, so it is a
   rendering concern rather than a schema one. A run whose output did not
   shrink still exits **0**, with the negative-or-zero percentage printed as
   such and a stderr warning — hiding a failed compression is the same
   dishonesty class as claiming a saving that did not occur.
2. **`--lossless` is a guarantee, not a promise.** D-12.3's Layer 1 runtime
   gate lives HERE, before ``AtomicWriter`` ever opens: two
   :class:`~pdf_toolkit.ports.structure.StructuralFacts` (plain data the
   adapter computed) are compared, and a mismatch means nothing is written
   and the run fails honestly, exit 1, naming the failed check.
3. **The image pass is opt-in, never implied.** ``--images`` defaults to
   ``keep``; combining it with ``--lossless`` is a usage error (exit 2), not
   a silently-honoured "lossless but also lossy" invocation.
4. **`repair` and `linearize` are verified, never merely claimed.** `repair`
   reports exactly what libqpdf's recovery pass found, including reporting
   *nothing* when nothing was wrong; `linearize`'s runtime check happens
   inside the adapter (D-12.6 check 1) before this module ever reaches
   ``AtomicWriter``.

**The filesystem tier runs in both modes (B-054, extending X-67), through
the ONE shared planner (PDF-18).**
:func:`~pdf_toolkit.safety.atomic.plan_filesystem` is the ONE call all three
verbs share. `compress` carries both destination shapes (``-O``,
``--out-dir``, ``--name``, ``--in-place``); `repair`/`linearize` carry only
the single-target shape (``out_dir`` is always ``None`` for them), which the
shared planner's own guard already handles without a second code path.

**Nothing here writes.** Every byte reaches disk through
``safety.AtomicWriter``; `compress --out-dir` creates its directory only via
``safety.atomic.plan_output_set`` (which ``plan_filesystem`` wraps).
Structural work (the image pass, the pikepdf pass, the recovery/linearize
pass) is skipped entirely under ``--dry-run`` — the same posture
`rasterize`/`compose`/`create` already take — so a dry run never opens
`pikepdf` or `pypdf` at all.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pdf_toolkit.errors import FailureError, NoInputError, UsageError
from pdf_toolkit.models import SCHEMA_VERSION as _SCHEMA_VERSION
from pdf_toolkit.models import ItemResult, OperationResult
from pdf_toolkit.ops.pagerange import parse
from pdf_toolkit.ports.structure import (
    StructuralFacts,
    require_image_pass,
    require_structure,
)
from pdf_toolkit.safety.atomic import AtomicWriter, plan_filesystem
from pdf_toolkit.safety.naming import render_name
from pdf_toolkit.safety.paths import check_output_collisions
from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = [
    "DEFAULT_COMPRESS_NAME_TEMPLATE",
    "DEFAULT_IMAGE_DPI",
    "DEFAULT_IMAGE_QUALITY",
    "IMAGE_MODES",
    "VERB_COMPRESS",
    "VERB_LINEARIZE",
    "VERB_REPAIR",
    "compress_run",
    "linearize_run",
    "repair_run",
]

VERB_COMPRESS: Final[str] = "compress"
VERB_REPAIR: Final[str] = "repair"
VERB_LINEARIZE: Final[str] = "linearize"

#: `compress --images` (D-12.2). ``keep`` is the default and does nothing.
IMAGE_MODES: Final[tuple[str, ...]] = ("keep", "downsample", "recompress")

DEFAULT_IMAGE_DPI: Final[float] = 150.0
DEFAULT_IMAGE_QUALITY: Final[int] = 80

#: `compress --out-dir`'s default filename template -- one output per input,
#: same stem, mirroring `text`'s own `DEFAULT_TEXT_NAME_TEMPLATE` shape.
DEFAULT_COMPRESS_NAME_TEMPLATE: Final[str] = "{stem}.{ext}"

_NAME_WITHOUT_OUT_DIR: Final[str] = (
    "--name templates a filename inside --out-dir; pass --out-dir, "
    "-O to name one file, or --in-place to overwrite the input"
)


# --------------------------------------------------------------------------- #
# Shared validation
# --------------------------------------------------------------------------- #


def _validate_sources(sources: Sequence[Path]) -> None:
    for source in sources:
        if not source.exists():
            raise NoInputError("no such file", path=str(source))
        if source.is_dir():
            raise UsageError("expected a PDF file, not a directory", path=str(source))


# --------------------------------------------------------------------------- #
# Shared filesystem-tier planning — PDF-18 Design D1's ONE planner. `compress`
# is the first of these three verbs to carry **both** destination shapes:
# :func:`~pdf_toolkit.safety.atomic.plan_filesystem` owns the `--out-dir` tier
# and the per-destination (`-O`/`--in-place`) tier a single target has
# instead, in the same call, in both modes. For `repair`/`linearize`,
# `out_dir` is always `None`, so the same call routes them through the writer
# tier on every call — the same code path `compress -O`/`--in-place` takes.
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# `compress`
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _CompressTarget:
    source: Path
    target: Path


def _resolve_compress_targets(
    sources: Sequence[Path],
    *,
    output: Path | None,
    out_dir: Path | None,
    name_template: str | None,
    in_place: bool,
) -> list[_CompressTarget]:
    """Every source's own destination, computed before anything runs.

    ``compress a.pdf b.pdf -O one.pdf`` (two inputs, one ``-O`` target) is an
    **arity** error, not an output-flag-consumption error (D-12.0a) — the
    CLI layer refuses it before this function is ever reached, so ``output``
    here is only ever paired with exactly one source.
    """
    if in_place:
        return [_CompressTarget(source=source, target=source) for source in sources]
    if output is not None:
        return [_CompressTarget(source=sources[0], target=output)]
    if out_dir is None:  # pragma: no cover - the CLI layer requires a destination first
        raise UsageError("compress requires --output, --out-dir, or --in-place")
    template = name_template if name_template is not None else DEFAULT_COMPRESS_NAME_TEMPLATE
    return [
        _CompressTarget(
            source=source,
            target=render_name(template, out_dir=out_dir, stem=source.stem, ext="pdf", index=index),
        )
        for index, source in enumerate(sources, start=1)
    ]


def _select_pages_set(source: Path, pages_spec: str | None) -> frozenset[int] | None:
    """The scope for the image pass: ``None`` means "every page" (`PLAN.md`
    §4.3's set semantics), a set otherwise. Computed only when an image pass
    is active — the page count read is the one cost `--images keep` never
    pays."""
    if pages_spec is None:
        return None
    engine = require_structure()
    with engine.open_document(source) as document:
        page_count = document.page_count
    selection = parse(pages_spec, page_count, ordered=False)
    if selection.is_empty:
        raise NoInputError(
            f"{source}: --pages {pages_spec!r} resolved to zero pages; nothing to compress",
            path=str(source),
        )
    return frozenset(selection.indices)


def _lossless_failure(before: StructuralFacts, after: StructuralFacts) -> str | None:
    """D-12.3 Layer 1 — the runtime gate, over plain facts only.

    Three checks, cheap and decode-free: page count, image XObject count,
    and every image's own tuple (which folds in the ``/DCTDecode`` raw-byte
    identity check via ``dct_sha256``). Returns the name of the first failed
    check, or ``None`` when the guarantee holds. This is a runtime
    invariant, not a proof of text identity — the test-level proof (D-12.3
    Layer 2) extracts text with ``pypdfium2`` directly, outside this module.
    """
    if before.page_count != after.page_count:
        return f"page count changed ({before.page_count} -> {after.page_count})"
    if len(before.images) != len(after.images):
        return f"image XObject count changed ({len(before.images)} -> {len(after.images)})"
    for index, (earlier, later) in enumerate(zip(before.images, after.images, strict=True)):
        if earlier != later:
            return f"image {index} changed structurally (filter/dimensions/colour or DCT bytes)"
    return None


def _compress_one(
    source: Path,
    *,
    lossless: bool,
    images: str,
    image_dpi: float,
    image_quality: int,
    pages_spec: str | None,
) -> tuple[bytes, dict[str, object]]:
    """One input's full pipeline (D-12.2): optional image pre-pass, then the
    pikepdf structural pass, then (only under ``--lossless``) D-12.3's Layer
    1 gate. Raises before returning on any failure — the caller never opens
    ``AtomicWriter`` for a failed item, so nothing is written (D-12.3)."""
    data = source.read_bytes()
    detail: dict[str, object] = {}

    if images != "keep":
        pages = _select_pages_set(source, pages_spec)
        pass_engine = require_image_pass()
        pass_outcome = pass_engine.downsample_images(
            data, mode=images, pages=pages, dpi=image_dpi, quality=image_quality
        )
        data = pass_outcome.output
        detail["images_transformed"] = pass_outcome.images_transformed
        detail["images_skipped"] = pass_outcome.images_skipped

    engine = require_structure(capability="object-streams")
    outcome = engine.compress(data)

    if lossless:
        failure = _lossless_failure(outcome.before, outcome.after)
        if failure is not None:
            raise FailureError(
                f"--lossless guarantee violated: {failure}; nothing written", path=str(source)
            )

    return outcome.output, detail


def compress_run(
    sources: Sequence[Path],
    *,
    lossless: bool,
    images: str,
    image_dpi: float,
    image_quality: int,
    pages_spec: str | None,
    output: Path | None,
    out_dir: Path | None,
    name_template: str | None,
    in_place: bool,
    policy: SafetyPolicy,
) -> OperationResult:
    """Compress every source, one output per input, in input order.

    Under ``--dry-run`` no engine runs at all (mirroring `rasterize`/
    `compose`/`create`): the filesystem tier alone is predicted, through
    :func:`~pdf_toolkit.safety.atomic.plan_filesystem`.
    """
    _validate_sources(sources)
    if name_template is not None and out_dir is None:
        raise UsageError(_NAME_WITHOUT_OUT_DIR)

    planned = _resolve_compress_targets(
        sources, output=output, out_dir=out_dir, name_template=name_template, in_place=in_place
    )
    targets = [item.target for item in planned]
    # Data-independent (planned targets against each other) -- checked
    # identically in both modes, mirroring `split`'s own AC10 convention.
    check_output_collisions(targets)

    plan = plan_filesystem(targets, out_dir=out_dir, policy=policy, kind="pdf")

    if policy.dry_run:
        detail = plan.detail()
        items = tuple(
            ItemResult(
                input=str(item.source),
                output=str(item.target),
                ok=not plan.refused,
                exit_code=plan.would_exit,
                message=("planned: compress" if not plan.refused else plan.message),
                bytes_before=item.source.stat().st_size,
                bytes_after=None,
                duration_ms=0,
                detail=detail,
            )
            for item in planned
        )
        return OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=VERB_COMPRESS,
            dry_run=True,
            items=items,
            warnings=(),
            duration_ms=0,
        )

    warnings: list[str] = []
    written: list[ItemResult] = []
    for item in planned:
        started = time.monotonic()
        bytes_before = item.source.stat().st_size
        output_bytes, item_detail = _compress_one(
            item.source,
            lossless=lossless,
            images=images,
            image_dpi=image_dpi,
            image_quality=image_quality,
            pages_spec=pages_spec,
        )
        with AtomicWriter(item.target, policy=policy, kind="pdf") as writer:
            writer.stream.write(output_bytes)
        bytes_after = item.target.stat().st_size

        if bytes_after >= bytes_before:
            warnings.append(
                f"{item.source}: did not shrink ({bytes_before} -> {bytes_after} bytes)"
            )
        skipped = item_detail.get("images_skipped")
        if isinstance(skipped, int) and skipped > 0:
            warnings.append(f"{item.source}: {skipped} image(s) skipped (not safely re-encodable)")

        ratio = ((bytes_before - bytes_after) / bytes_before * 100) if bytes_before else 0.0
        duration_ms = int((time.monotonic() - started) * 1000)
        written.append(
            ItemResult(
                input=str(item.source),
                output=str(item.target),
                ok=True,
                exit_code=0,
                message=f"{bytes_before} -> {bytes_after} bytes ({ratio:+.1f}%)",
                bytes_before=bytes_before,
                bytes_after=bytes_after,
                duration_ms=duration_ms,
                detail=item_detail or None,
            )
        )

    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=VERB_COMPRESS,
        dry_run=False,
        items=tuple(written),
        warnings=tuple(warnings),
        duration_ms=0,
    )


# --------------------------------------------------------------------------- #
# Single-target resolution — shared by `repair` and `linearize`, neither of
# which carries `--out-dir`/`--name` (D-12.0a).
# --------------------------------------------------------------------------- #


def _resolve_single_target(source: Path, *, output: Path | None, in_place: bool, verb: str) -> Path:
    if in_place:
        return source
    if output is not None:
        return output
    raise UsageError(f"{verb} requires -O/--output or --in-place")


# --------------------------------------------------------------------------- #
# `repair`
# --------------------------------------------------------------------------- #


def _repair_message(warnings: tuple[str, ...]) -> str:
    if not warnings:
        return "no damage detected"
    return f"recovered from {len(warnings)} finding(s)"


def repair_run(
    source: Path,
    *,
    output: Path | None,
    in_place: bool,
    report: bool,
    policy: SafetyPolicy,
) -> OperationResult:
    """Recover *source* via libqpdf's own recovery parser (D-12.4).

    ``--report`` widens ``ItemResult.detail`` with the structural delta
    (object/page counts, whether an xref reconstruction occurred);
    ``OperationResult.warnings`` and the one-line message are populated
    either way, because *whether nothing was wrong* is the honest baseline
    this verb reports, not an opt-in extra.
    """
    _validate_sources([source])
    target = _resolve_single_target(source, output=output, in_place=in_place, verb=VERB_REPAIR)

    plan = plan_filesystem([target], out_dir=None, policy=policy, kind="pdf")

    if policy.dry_run:
        detail = plan.detail()
        item = ItemResult(
            input=str(source),
            output=str(target),
            ok=not plan.refused,
            exit_code=plan.would_exit,
            message=("planned: repair" if not plan.refused else plan.message),
            bytes_before=source.stat().st_size,
            bytes_after=None,
            duration_ms=0,
            detail=detail,
        )
        return OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=VERB_REPAIR,
            dry_run=True,
            items=(item,),
            warnings=(),
            duration_ms=0,
        )

    started = time.monotonic()
    bytes_before = source.stat().st_size
    engine = require_structure(capability="repair")
    outcome = engine.repair(source.read_bytes())

    with AtomicWriter(target, policy=policy, kind="pdf") as writer:
        writer.stream.write(outcome.output)
    bytes_after = target.stat().st_size
    duration_ms = int((time.monotonic() - started) * 1000)

    report_detail: dict[str, object] | None = None
    if report:
        report_detail = {
            "page_count_before": outcome.page_count_before,
            "page_count_after": outcome.page_count_after,
            "object_count_before": outcome.object_count_before,
            "object_count_after": outcome.object_count_after,
            "xref_reconstructed": outcome.xref_reconstructed,
        }

    item = ItemResult(
        input=str(source),
        output=str(target),
        ok=True,
        exit_code=0,
        message=_repair_message(outcome.warnings),
        bytes_before=bytes_before,
        bytes_after=bytes_after,
        duration_ms=duration_ms,
        detail=report_detail,
    )
    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=VERB_REPAIR,
        dry_run=False,
        items=(item,),
        warnings=outcome.warnings,
        duration_ms=0,
    )


# --------------------------------------------------------------------------- #
# `linearize`
# --------------------------------------------------------------------------- #


def linearize_run(
    source: Path,
    *,
    output: Path | None,
    in_place: bool,
    policy: SafetyPolicy,
) -> OperationResult:
    """Rewrite *source* for byte-serving (D-12.6).

    Verified structurally inside the adapter before this function ever sees
    the candidate bytes -- a failed verification raises there, so nothing
    reaches ``AtomicWriter`` and the target stays untouched.
    """
    _validate_sources([source])
    target = _resolve_single_target(source, output=output, in_place=in_place, verb=VERB_LINEARIZE)

    plan = plan_filesystem([target], out_dir=None, policy=policy, kind="pdf")

    if policy.dry_run:
        detail = plan.detail()
        item = ItemResult(
            input=str(source),
            output=str(target),
            ok=not plan.refused,
            exit_code=plan.would_exit,
            message=("planned: linearize" if not plan.refused else plan.message),
            bytes_before=source.stat().st_size,
            bytes_after=None,
            duration_ms=0,
            detail=detail,
        )
        return OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=VERB_LINEARIZE,
            dry_run=True,
            items=(item,),
            warnings=(),
            duration_ms=0,
        )

    started = time.monotonic()
    bytes_before = source.stat().st_size
    engine = require_structure(capability="linearize")
    output_bytes = engine.linearize(source.read_bytes())

    with AtomicWriter(target, policy=policy, kind="pdf") as writer:
        writer.stream.write(output_bytes)
    bytes_after = target.stat().st_size
    duration_ms = int((time.monotonic() - started) * 1000)

    item = ItemResult(
        input=str(source),
        output=str(target),
        ok=True,
        exit_code=0,
        message="linearized",
        bytes_before=bytes_before,
        bytes_after=bytes_after,
        duration_ms=duration_ms,
    )
    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=VERB_LINEARIZE,
        dry_run=False,
        items=(item,),
        warnings=(),
        duration_ms=0,
    )
