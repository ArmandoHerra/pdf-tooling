"""``extract`` + ``delete`` + ``rotate`` + ``reorder`` — the four page-addressed
structure verbs, as pure plan/result functions over ``StructureEngine`` (PDF-08).

Framework-free per L2: no typer/click import (PDF-06's AST test enforces it),
and **no engine library import either** — every page crosses the port boundary
through ``ports/structure.py``'s ``OpenStructureDocument`` / ``StructureWriter``
Protocols, never a ``pypdf`` object.

Design §D1 — set vs ordered, the one thing four verbs can drift on
------------------------------------------------------------------
Four verbs addressing pages are four chances to disagree about whether a page
selection is a *set* or an *ordered sequence*. The distinction is resolved
**once**, at the verb boundary, by the ``ordered=`` keyword each verb threads
into the ONE shared parser (``ops/pagerange.py::parse``), and then consumed by
one pure function per verb below:

===========  ==========  ===================  =========================
Verb         Semantics   ``PageRange``        Page plan
===========  ==========  ===================  =========================
``extract``  ORDERED     ``ordered=True``     :func:`plan_extract`
``reorder``  ORDERED     ``ordered=True``     :func:`plan_reorder`
``delete``   SET         ``ordered=False``    :func:`plan_delete`
``rotate``   SET         ``ordered=False``    :func:`plan_rotate`
===========  ==========  ===================  =========================

The two consequences that are exactly where a naive implementation diverges:
a `delete` that removed by index in emission order would corrupt its own
indices on a duplicate, and a `rotate` that did the same would rotate a
duplicated page **twice** — observable, because rotation is relative by
default. Both are prevented by construction here: the set verbs consume
``PageRange.as_set()`` and the ordered verbs consume ``PageRange.indices``.

Design §D3 — `reorder` appends what the selection does not name
---------------------------------------------------------------
`reorder` is **total**: every input page appears in the output at least once,
so ``output_page_count >= input_page_count``. That is what distinguishes it
from `extract` (which subsets) and what stops
``reorder book.pdf --pages 'last,1' --in-place`` from being the cycle's
largest data-loss footgun in a product whose stated recovery path is the
``.bak`` sidecar and nothing else (`PLAN.md` §12 R-06). An exclusion in
`reorder` means "move to the back", never "delete" — dropping pages is
`extract`'s job, and removing them is `delete`'s.

Design §D5 — `delete` never produces a zero-page document
---------------------------------------------------------
A selection resolving to the whole document is exit **5**, not 2 and not 4:
§5.6 makes 2 a *bad invocation* (decidable without the document — this needs
the page count) and 4 *nothing to act on* (here there is a full document to
act on). This is a safety gate declining, which is 5's definition. The two
"empty" cases therefore carry different codes and are kept distinct by
construction: an empty *selection* is 4, a *full* selection under `delete` is
5.

Design §D4/§D16 — rotation arithmetic lives HERE, never in the adapter
----------------------------------------------------------------------
:func:`normalize_rotation` owns relative-vs-``--absolute`` and the ``% 360``
normalization; the port's ``StructureWriter.set_rotation`` is handed a final,
already-normalized absolute value and does nothing but stamp it. So
``/Rotate 270`` plus ``--angle 90`` is **0**, never 360, and
``--absolute --angle -90`` is **270**, never -90 — and all of it is testable
without an engine.

**Absent stays absent.** :func:`plan_rotate` returns a stamp map covering only
the pages the selection names, so every unnamed page keeps whatever
``append_pages`` copied across — including an *absent* ``/Rotate`` key.
Writing an explicit ``/Rotate 0`` onto untouched pages would preserve
rendering while failing the "changes only page 1" guarantee, so it is not a
defensive branch that could be removed by mistake: it is a property of which
pages get a call at all.

**The filesystem tier runs in both modes (X-67, B-054), through the ONE
shared planner (PDF-18).**
:func:`~pdf_toolkit.safety.atomic.plan_filesystem` is called at the tier-2
step below. The *selection* tier is planned the same way (see
:func:`_run`'s tier 1), so ``delete --pages all --dry-run`` predicts §D5's
zero-page refusal rather than discovering it only on the real run.

**Nothing here writes.** Every byte reaches disk through
``safety.AtomicWriter``; ``--out-dir`` is created only via
``safety.atomic.plan_output_set`` (which ``plan_filesystem`` wraps); every
rendered destination comes from ``safety.naming.render_name`` (X-70 — a
hand-built path is the only way to bypass containment, so the rule is about
which function builds the path).
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pdf_toolkit.errors import NoInputError, PdfToolkitError, RefusedError, UsageError
from pdf_toolkit.models import SCHEMA_VERSION as _SCHEMA_VERSION
from pdf_toolkit.models import ItemResult, OperationResult, PageRange
from pdf_toolkit.ops.pagerange import parse
from pdf_toolkit.ports.structure import OpenStructureDocument, require_structure
from pdf_toolkit.safety.atomic import AtomicWriter, plan_filesystem
from pdf_toolkit.safety.naming import render_name
from pdf_toolkit.safety.paths import check_output_collisions, classify_operand
from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = [
    "DEFAULT_PAGES_NAME_TEMPLATE",
    "ROTATION_ANGLES",
    "VERB_DELETE",
    "VERB_EXTRACT",
    "VERB_REORDER",
    "VERB_ROTATE",
    "delete_run",
    "extract_run",
    "normalize_rotation",
    "plan_delete",
    "plan_extract",
    "plan_reorder",
    "plan_rotate",
    "reject_missing_sources",
    "reorder_run",
    "rotate_run",
]

VERB_EXTRACT: Final[str] = "extract"
VERB_DELETE: Final[str] = "delete"
VERB_ROTATE: Final[str] = "rotate"
VERB_REORDER: Final[str] = "reorder"

#: `PLAN.md` §4.1's accepted `--angle` set, exactly. Anything else is refused
#: by the CLI layer (exit 2) before a document is opened; this tuple is the
#: single source both the enum and its error message are built from, so the
#: message can never name a set the code does not accept.
ROTATION_ANGLES: Final[tuple[int, ...]] = (90, 180, 270, -90)

#: `--out-dir`'s default filename template — one output per input, same stem,
#: mirroring `compress`'s own `DEFAULT_COMPRESS_NAME_TEMPLATE` shape.
DEFAULT_PAGES_NAME_TEMPLATE: Final[str] = "{stem}.{ext}"

_NAME_WITHOUT_OUT_DIR: Final[str] = (
    "--name templates a filename inside --out-dir; pass --out-dir, "
    "-O to name one file, or --in-place to overwrite the input"
)


# --------------------------------------------------------------------------- #
# Shared validation
# --------------------------------------------------------------------------- #


def reject_missing_sources(sources: Sequence[Path]) -> None:
    """`PLAN.md` §10's own contract, shared by all four cmd modules.

    Exported (rather than copied into four `cli/cmd_*.py` files) because it is
    the ordering guarantee C5 depends on: every verb with a path-taking
    argument exits **4** on a nonexistent input, unconditionally, and that
    wins over any other usage error. The four cmd modules call this first,
    before their own destination and `--pages` checks.
    """
    for source in sources:
        classify_operand(source)


# --------------------------------------------------------------------------- #
# §D1/§D3/§D4/§D5 — the page plans. Pure functions of a resolved `PageRange`:
# no engine, no filesystem, no document. This is where the set-vs-ordered
# table is CODE rather than prose, and it is unit-tested as such.
# --------------------------------------------------------------------------- #


def _all_pages(page_count: int) -> tuple[int, ...]:
    return tuple(range(1, page_count + 1))


def plan_extract(selection: PageRange) -> tuple[int, ...]:
    """`extract` — ORDERED. The selection, verbatim: order is the caller's and
    duplicates are meaningful (one output page per occurrence).

    Sorting this "for tidiness" is precisely how `extract --pages '1,1,3'`
    silently becomes a set filter.
    """
    return selection.indices


def plan_delete(selection: PageRange) -> tuple[int, ...]:
    """`delete` — SET. Everything the selection does not name, in ascending
    original order. Duplicates are idempotent, because the selection is
    consumed as a set."""
    removed = selection.as_set()
    return tuple(number for number in _all_pages(selection.page_count) if number not in removed)


def plan_reorder(selection: PageRange) -> tuple[int, ...]:
    """`reorder` — ORDERED, and **total** (§D3).

    The named sequence first, in the order given and with duplicates
    preserved; then every page the selection did not name, in ascending
    original order. `reorder` never drops a page — an exclusion moves a page
    to the back rather than deleting it.
    """
    named = selection.as_set()
    remainder = tuple(number for number in _all_pages(selection.page_count) if number not in named)
    return selection.indices + remainder


def normalize_rotation(current: int, angle: int, *, absolute: bool) -> int:
    """The written ``/Rotate`` value, always inside ``{0, 90, 180, 270}``.

    Relative by default (`PLAN.md` §4.1 lists ``--absolute``, and a flag named
    ``--absolute`` can only mean the default is relative). Modular either way,
    so ``270 + 90`` is **0** rather than 360 and ``--absolute --angle -90`` is
    **270** rather than -90: readers vary in how they treat out-of-band
    values, and every deterministic assertion downstream depends on this.
    """
    return (angle % 360) if absolute else ((current + angle) % 360)


def plan_rotate(
    selection: PageRange,
    current_rotations: Mapping[int, int],
    *,
    angle: int,
    absolute: bool,
) -> tuple[tuple[int, ...], dict[int, int]]:
    """`rotate` — SET. Every page is emitted; only the named ones are stamped.

    Returns ``(page_numbers, stamps)`` where ``stamps`` maps a **0-based index
    into the emitted sequence** to the final absolute ``/Rotate`` value.

    Two properties, both by construction rather than by a guard:

    * a page named twice is rotated **once** (the selection is consumed as a
      set), which is observable precisely because rotation is relative by
      default;
    * a page the selection does not name gets **no call at all**, so an absent
      ``/Rotate`` key stays absent.

    ``current_rotations`` is 1-based page number -> current ``/Rotate``; a page
    missing from it is treated as 0, which is what an absent key means for the
    arithmetic.
    """
    pages = _all_pages(selection.page_count)
    stamps = {
        number - 1: normalize_rotation(current_rotations.get(number, 0), angle, absolute=absolute)
        for number in sorted(selection.as_set())
    }
    return pages, stamps


# --------------------------------------------------------------------------- #
# Destination resolution — every `--out-dir` path through `render_name` (X-70)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Target:
    source: Path
    target: Path


def _resolve_targets(
    sources: Sequence[Path],
    *,
    verb: str,
    output: Path | None,
    out_dir: Path | None,
    name_template: str | None,
    in_place: bool,
) -> list[_Target]:
    """Every source's own destination, computed before anything runs.

    ``-O`` with more than one input is an **arity** error, not an
    output-flag-consumption error (§D12 rule 1) — the CLI layer refuses it
    before this function is reached, so ``output`` here is only ever paired
    with exactly one source.

    ``--in-place`` wins over ``output`` in the same one-dimensional way
    ``ops/optimize.py:241`` and ``ops/crypto.py:258`` already resolve it. That
    precedence is the landed behaviour of every verb consuming both flags
    (backlog **B-076**); PDF-08 follows it rather than improvising a fifth
    per-verb refusal that ``cli/common.py`` should own centrally, and adds no
    acceptance criterion pinning it (**B-073** — a test encoding today's
    behaviour turns red the day the central fix lands and reads as a
    regression).
    """
    if in_place:
        return [_Target(source=source, target=source) for source in sources]
    if output is not None:
        return [_Target(source=sources[0], target=output)]
    if out_dir is None:  # pragma: no cover - the CLI layer requires a destination first
        raise UsageError(f"{verb} requires --output, --out-dir, or --in-place")
    template = name_template if name_template is not None else DEFAULT_PAGES_NAME_TEMPLATE
    return [
        _Target(
            source=source,
            # X-70: containment is `render_name`'s own last step
            # (`safety/naming.py:166` calls `ensure_within`), so a destination
            # is protected BY CONSTRUCTION here -- never `out_dir / f"..."`,
            # never `os.path.join`, never string concatenation.
            target=render_name(template, out_dir=out_dir, stem=source.stem, ext="pdf", index=index),
        )
        for index, source in enumerate(sources, start=1)
    ]


# --------------------------------------------------------------------------- #
# The two prediction tiers (X-67). Both run in BOTH modes; a real run raises
# exactly as before, a dry run captures the FIRST refusal and stops where the
# real run would have stopped.
#
# NOTE ON THE DRY RUN'S OWN EXIT CODE, measured rather than assumed. This
# spec's AC34/AC35 state that a dry run over a predicted refusal "exits 0".
# The landed product does the opposite and is PINNED doing it:
# `tests/test_cli_contract.py::test_c15_dry_run_predicts_an_occupied_target_
# refusal` asserts `dry.returncode == real.returncode == 5` for every
# PRODUCING verb, and `compress --dry-run -O <occupied>` exits 5 today. The
# prediction rides in `detail.would_exit`/`would_refuse` either way; only the
# process code differs. These four verbs follow the landed convention, so no
# verb disagrees with another about an exit code. Recorded in the spec's
# Implementation Log rather than silently reconciled.
# --------------------------------------------------------------------------- #


#: The filesystem tier for this run, through the ONE shared planner (PDF-18
#: Design D1). :func:`~pdf_toolkit.safety.atomic.plan_filesystem` owns both
#: destination shapes in one call, in both modes: the `--out-dir` tier and
#: the per-destination tier a single `-O`/`--in-place` target has instead of
#: a shared directory. `d55b302668` -- a `--out-dir` that does not exist and
#: whose *parent* is unwritable used to predict `would_exit 0` against a real
#: unhandled `PermissionError` -- is now predicted correctly, for these four
#: verbs along with every other producing verb, because the fix lives inside
#: the shared planner itself (`safety/atomic.py::_ensure_out_dir`) rather
#: than in a per-module copy.


@dataclass(frozen=True, slots=True)
class _PagePlan:
    """One input's resolved page work, before anything is written."""

    page_numbers: tuple[int, ...]
    stamps: Mapping[int, int]
    page_count_before: int


def _selection_refusal(source: Path, verb: str, pages_spec: str, kind: str) -> PdfToolkitError:
    """The two selection-tier refusals, built in one place so §D5's pair can
    never converge: an empty *selection* is exit 4, a *full* selection under
    `delete` is exit 5."""
    if kind == "empty":
        return NoInputError(
            f"{source}: --pages {pages_spec!r} resolved to zero pages; nothing to {verb}",
            path=str(source),
        )
    return RefusedError(
        f"{source}: --pages {pages_spec!r} selects every page; "
        f"{verb} refuses to produce a zero-page document (select fewer pages, "
        f"or remove the file instead)",
        path=str(source),
    )


def _resolve_selection(
    document: OpenStructureDocument,
    source: Path,
    *,
    verb: str,
    pages_spec: str,
    ordered: bool,
) -> PageRange:
    """The ONE selection path (§D2), consumed and never forked.

    ``ops/pagerange.py::parse`` is called **directly**, once per input, with
    the raw ``--pages`` string exactly as given and the ``ordered=`` value
    §D1's table assigns. There is no wrapper, no helper and no second
    signature: ``parse`` already carries ``ordered``, already raises
    ``PageRangeError`` (exit 2) for every §4.3 error row, and already leaves
    the empty-but-valid selection to the caller. The page count comes from the
    opened document, which is why this runs after the document is open.
    """
    del verb  # named for the call site's readability; the message is built above
    return parse(pages_spec, document.page_count, ordered=ordered)


def _plan_pages(
    document: OpenStructureDocument,
    source: Path,
    *,
    verb: str,
    pages_spec: str,
    ordered: bool,
    angle: int | None,
    absolute: bool,
) -> _PagePlan:
    """One input's page plan. Raises the §D5/§4.3 refusals; never writes."""
    selection = _resolve_selection(
        document, source, verb=verb, pages_spec=pages_spec, ordered=ordered
    )
    if selection.is_empty:
        raise _selection_refusal(source, verb, pages_spec, "empty")

    if verb == VERB_EXTRACT:
        return _PagePlan(plan_extract(selection), {}, selection.page_count)
    if verb == VERB_REORDER:
        return _PagePlan(plan_reorder(selection), {}, selection.page_count)
    if verb == VERB_DELETE:
        survivors = plan_delete(selection)
        if not survivors:
            raise _selection_refusal(source, verb, pages_spec, "full")
        return _PagePlan(survivors, {}, selection.page_count)

    # `rotate`. The CURRENT value is read through the EXISTING path -- never a
    # new port method: `read_document_info(path, pages=True)` -> `PageInfo.
    # rotation`, which the adapter already normalizes `% 360`. Only relative
    # rotation needs it, so `--absolute` never pays for the read.
    assert angle is not None  # nosec B101 - the CLI layer requires --angle for rotate
    current: dict[int, int] = {}
    if not absolute:
        info = require_structure().read_document_info(source, pages=True)
        current = {page.number: page.rotation for page in info.pages}
    pages, stamps = plan_rotate(selection, current, angle=angle, absolute=absolute)
    return _PagePlan(pages, stamps, selection.page_count)


# --------------------------------------------------------------------------- #
# The one execution path all four verbs share
# --------------------------------------------------------------------------- #


def _item_detail(plan: _PagePlan) -> dict[str, object]:
    """X-107 — what a real run reports about what it actually did.

    Asserted against the RE-READ documents by this spec's AC39, never against
    the emitting code: a `detail` that disagrees with the document is the
    defect, which is the transferable lesson of PDF-10's `stream_bytes_
    identical` reporting `true` for two pages reportlab had de-duplicated.
    """
    detail: dict[str, object] = {
        "pages_before": plan.page_count_before,
        "pages_after": len(plan.page_numbers),
    }
    if plan.stamps:
        detail["pages_rotated"] = len(plan.stamps)
    return detail


def _run(
    sources: Sequence[Path],
    *,
    verb: str,
    pages_spec: str,
    ordered: bool,
    angle: int | None = None,
    absolute: bool = False,
    output: Path | None,
    out_dir: Path | None,
    name_template: str | None,
    in_place: bool,
    policy: SafetyPolicy,
) -> OperationResult:
    """Plan and (unless ``--dry-run``) perform one run, in input order.

    Fails closed: every input's selection is resolved before the first byte is
    written, so a refusal on any input aborts the run and writes nothing. A
    partially-rewritten set of documents is a wrong result that looks right.
    """
    reject_missing_sources(sources)
    if name_template is not None and out_dir is None:
        raise UsageError(_NAME_WITHOUT_OUT_DIR)

    planned = _resolve_targets(
        sources,
        verb=verb,
        output=output,
        out_dir=out_dir,
        name_template=name_template,
        in_place=in_place,
    )
    targets = [item.target for item in planned]
    # Data-independent (planned targets against each other) -- checked
    # identically in both modes, mirroring `split`'s own convention.
    check_output_collisions(targets)

    engine = require_structure()  # X-76: by capability, never by adapter name

    # Tier 1 -- the selection. Runs in both modes; a real run raises, a dry run
    # captures the first refusal (X-67), so `delete --pages all --dry-run`
    # PREDICTS §D5's zero-page refusal instead of discovering it later.
    page_plans: list[_PagePlan] = []
    selection_refusal: PdfToolkitError | None = None
    try:
        for item in planned:
            with engine.open_document(item.source) as document:
                page_plans.append(
                    _plan_pages(
                        document,
                        item.source,
                        verb=verb,
                        pages_spec=pages_spec,
                        ordered=ordered,
                        angle=angle,
                        absolute=absolute,
                    )
                )
    except (NoInputError, RefusedError) as refusal:
        if not policy.dry_run:
            raise
        selection_refusal = refusal

    if selection_refusal is not None:
        detail: dict[str, object] = {
            "would_exit": selection_refusal.exit_code,
            "would_refuse": selection_refusal.to_dict(),
        }
        return OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=verb,
            dry_run=True,
            items=tuple(
                ItemResult(
                    input=str(item.source),
                    output=str(item.target),
                    ok=False,
                    exit_code=selection_refusal.exit_code,
                    message=selection_refusal.message,
                    bytes_before=item.source.stat().st_size,
                    bytes_after=None,
                    duration_ms=0,
                    detail=detail,
                )
                for item in planned
            ),
            warnings=(),
            duration_ms=0,
        )

    # Tier 2 -- the filesystem.
    plan = plan_filesystem(targets, out_dir=out_dir, policy=policy, kind="pdf")

    if policy.dry_run:
        fs_detail = plan.detail()
        return OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=verb,
            dry_run=True,
            items=tuple(
                ItemResult(
                    input=str(item.source),
                    output=str(item.target),
                    ok=not plan.refused,
                    exit_code=plan.would_exit,
                    message=(
                        f"planned: {verb} -> {len(page_plan.page_numbers)} page(s)"
                        if not plan.refused
                        else plan.message
                    ),
                    bytes_before=item.source.stat().st_size,
                    bytes_after=None,
                    duration_ms=0,
                    detail={**fs_detail, **_item_detail(page_plan)},
                )
                for item, page_plan in zip(planned, page_plans, strict=True)
            ),
            warnings=(),
            duration_ms=0,
        )

    written: list[ItemResult] = []
    for item, page_plan in zip(planned, page_plans, strict=True):
        started = time.monotonic()
        bytes_before = item.source.stat().st_size
        # The document stays open across the write: `append_pages` hands the
        # adapter its own reader, and `AtomicWriter` writes a temp then
        # `os.replace`s onto the target -- so `--in-place` never reads through
        # a handle whose bytes have already been swapped underneath it.
        with engine.open_document(item.source) as document:
            writer = engine.new_writer()
            writer.append_pages(document, page_plan.page_numbers)
            for index, degrees in page_plan.stamps.items():
                writer.set_rotation(index, degrees)
            with AtomicWriter(item.target, policy=policy, kind="pdf") as atomic:
                writer.write(atomic.stream)
        written.append(
            ItemResult(
                input=str(item.source),
                output=str(item.target),
                ok=True,
                exit_code=0,
                message=(f"{page_plan.page_count_before} -> {len(page_plan.page_numbers)} page(s)"),
                bytes_before=bytes_before,
                bytes_after=item.target.stat().st_size,
                duration_ms=int((time.monotonic() - started) * 1000),
                detail=_item_detail(page_plan),
            )
        )

    return OperationResult(
        schema_version=_SCHEMA_VERSION,
        verb=verb,
        dry_run=False,
        items=tuple(written),
        warnings=(),
        duration_ms=0,
    )


# --------------------------------------------------------------------------- #
# The four public entry points. Each threads exactly ONE thing its siblings do
# not: the `ordered=` value §D1's table assigns it.
# --------------------------------------------------------------------------- #


def extract_run(
    sources: Sequence[Path],
    *,
    pages_spec: str,
    output: Path | None,
    out_dir: Path | None,
    name_template: str | None,
    policy: SafetyPolicy,
) -> OperationResult:
    """`extract` — ORDERED (§D1). Writes the selected pages to a NEW document,
    in the order given, duplicates preserved.

    Declares no ``--in-place``: `extract` derives a different page set from
    its input, so "mutate the input" has no meaning here that is not simply
    `reorder` or `delete`. That refusal is produced centrally by OR-3's
    declaration in ``cli/cmd_extract.py`` — there is no in-place branch here
    or there.
    """
    return _run(
        sources,
        verb=VERB_EXTRACT,
        pages_spec=pages_spec,
        ordered=True,
        output=output,
        out_dir=out_dir,
        name_template=name_template,
        in_place=False,
        policy=policy,
    )


def delete_run(
    sources: Sequence[Path],
    *,
    pages_spec: str,
    output: Path | None,
    out_dir: Path | None,
    name_template: str | None,
    in_place: bool,
    policy: SafetyPolicy,
) -> OperationResult:
    """`delete` — SET (§D1). Writes everything *except* the selected pages;
    refuses (exit 5) to produce a zero-page document (§D5)."""
    return _run(
        sources,
        verb=VERB_DELETE,
        pages_spec=pages_spec,
        ordered=False,
        output=output,
        out_dir=out_dir,
        name_template=name_template,
        in_place=in_place,
        policy=policy,
    )


def rotate_run(
    sources: Sequence[Path],
    *,
    pages_spec: str,
    angle: int,
    absolute: bool,
    output: Path | None,
    out_dir: Path | None,
    name_template: str | None,
    in_place: bool,
    policy: SafetyPolicy,
) -> OperationResult:
    """`rotate` — SET (§D1). Rotates the selected pages by a multiple of 90°,
    relative by default and absolute under ``--absolute`` (§D4).

    Changes ``/Rotate`` and nothing else: no cropping, no scaling, no page-size
    manipulation, and ``MediaBox``/``CropBox`` are untouched — rotation is
    metadata, not geometry.
    """
    return _run(
        sources,
        verb=VERB_ROTATE,
        pages_spec=pages_spec,
        ordered=False,
        angle=angle,
        absolute=absolute,
        output=output,
        out_dir=out_dir,
        name_template=name_template,
        in_place=in_place,
        policy=policy,
    )


def reorder_run(
    sources: Sequence[Path],
    *,
    pages_spec: str,
    output: Path | None,
    out_dir: Path | None,
    name_template: str | None,
    in_place: bool,
    policy: SafetyPolicy,
) -> OperationResult:
    """`reorder` — ORDERED and total (§D1/§D3). Rewrites page order from an
    explicit sequence; pages the selection does not name are **appended** in
    ascending original order, never dropped."""
    return _run(
        sources,
        verb=VERB_REORDER,
        pages_spec=pages_spec,
        ordered=True,
        output=output,
        out_dir=out_dir,
        name_template=name_template,
        in_place=in_place,
        policy=policy,
    )
