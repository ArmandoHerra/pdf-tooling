"""``text`` and ``tables`` — extraction, planning and serialization (PDF-11).

Framework-free per L2: no typer/click import (PDF-06's AST test enforces it),
and **no engine library import either** — every character and every grid comes
back through ``ports/text.py``, which is what keeps the licence question
answerable by reading six port files.

The engineering content of this module is not "call the layout engine". It is
honesty under ambiguity, in four rules `PLAN.md` §12 R-03 already decided:

1. **The strategy is declared in the output.** ``fast``/``layout`` for `text`,
   ``lines``/``text`` for `tables`, together with the adapter and version that
   produced it. It is a fact about the code path taken, never an inference.
2. **Table extraction is a heuristic**, said out loud in ``tables --help``.
3. **No number claiming how sure the engine was is invented** — not on a
   table, not on a cell, not on a block, not now and not behind a flag. A
   fabricated number is worse than no number. The six identifier names this
   rule forbids are listed in ``tests/unit/test_textract.py``, which greps this
   module and its four siblings for them rather than trusting this paragraph;
   they are deliberately not repeated here, so the grep has nothing to find.
4. **A silent fallback is a bug.** ``--layout`` with the layout adapter
   unresolved is exit 3 from ``ports/text.py``; it never quietly returns
   fast-path output.

**Empty is a real answer.** A page that exists and yields no characters returns
an empty string, exits 0, and warns. It is not exit 1, not exit 4, and never a
fabricated string. That contract is load-bearing outside this spec: the later
`ocr` verb's acceptance signal is *"`text` returns non-empty text where it
returned empty before"*, so changing the empty-page contract silently
invalidates another spec's proof.

**Nothing here writes.** Every byte reaches disk through
``safety.AtomicWriter``, and a destination directory is created only via
``safety.atomic.plan_output_set``. CSV and text are serialized **into memory**
(``io.StringIO`` + ``csv.writer``, then ``encode("utf-8")``) and the bytes are
handed to the writer — which is both what PDF-04's import-boundary walk
requires and how ``--dry-run`` purity, no-clobber and the ``-y`` posture come
for free instead of being re-implemented twice.

**The filesystem tier runs in both modes (B-054, extending X-67).**
``plan_output_set`` is called unconditionally, so a ``--dry-run`` over an
occupied target or an unwritable destination predicts the same refusal a real
run produces, through the *shared* planning path rather than a per-verb copy of
it. This module adds no per-verb exit-code logic on top of that path.

**Inputs are processed sequentially, in input order.** ``--threads`` is
accepted (it is a global flag) and has no effect on either verb; both
``--help`` texts say so, and a test pins the declared no-op so it cannot
silently become a lie. Extraction here is I/O- and parse-bound rather than
render-bound, and the product's one measured argument against worker threads
over the page engines (`decision.md` §8 X-104) is a reason not to reach for
them casually.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pdf_toolkit.errors import NoInputError, UsageError
from pdf_toolkit.models import SCHEMA_VERSION as _SCHEMA_VERSION
from pdf_toolkit.models import ItemResult, OperationResult, PageText, TableGrid, TextBlock
from pdf_toolkit.ops.pagerange import ALL_PAGES_TOKEN, parse
from pdf_toolkit.ports.structure import require_structure
from pdf_toolkit.ports.text import (
    TABLE_STRATEGIES,
    ExtractedTable,
    TextLine,
    require_fast_text,
    require_layout_text,
    require_tables,
)
from pdf_toolkit.safety.atomic import AtomicWriter, plan_output_set
from pdf_toolkit.safety.naming import render_name, used_fields
from pdf_toolkit.safety.paths import check_output_collisions
from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = [
    "DEFAULT_TABLE_NAME_TEMPLATE",
    "DEFAULT_TEXT_NAME_TEMPLATE",
    "TABLE_FORMATS",
    "TABLE_STRATEGIES",
    "TEXT_STRATEGIES",
    "EngineDeclaration",
    "TableOutcome",
    "TextOutcome",
    "extract_tables_run",
    "extract_text_run",
    "normalize_page_text",
    "rows_to_csv_bytes",
    "table_artifact_bytes",
]

VERB_TEXT: Final[str] = "text"
VERB_TABLES: Final[str] = "tables"

#: `text`'s two strategies, named by the code path taken.
TEXT_STRATEGIES: Final[tuple[str, ...]] = ("fast", "layout")

#: `tables --format`. `csv|json` and nothing else -- Markdown, XLSX and HTML
#: are out of scope, not merely unimplemented.
TABLE_FORMATS: Final[tuple[str, ...]] = ("csv", "json")

DEFAULT_TEXT_NAME_TEMPLATE: Final[str] = "{stem}.{ext}"
DEFAULT_TABLE_NAME_TEMPLATE: Final[str] = "{stem}-p{page:03}-t{index}.{ext}"

#: The extension a `text` artifact takes. Not derived from the input, and not
#: templated by default: the artifact is plain text whatever the source was.
TEXT_EXT: Final[str] = "txt"

#: The stderr warning a destination-less `--format` earns (AC12). A warning and
#: not a refusal: the run is still exactly what the user asked for, it simply
#: had no files to apply the file format to.
FORMAT_WITHOUT_DESTINATION_WARNING: Final[str] = (
    "--format only affects files written with --out-dir/-O; stdout follows -o"
)

#: The one place the "a template needs somewhere to put the file" refusal is
#: worded. Exit 2 -- a parse-time invocation mistake, nothing attempted yet.
_NAME_WITHOUT_OUT_DIR: Final[str] = (
    "--name templates a filename inside --out-dir; pass --out-dir, or -O to name one file"
)


# --------------------------------------------------------------------------- #
# The declaration that rides every payload (PLAN §12 R-03)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class EngineDeclaration:
    """Which adapter, at which version, produced a result.

    Read off the adapter the port handed back, never hard-coded and never
    inferred: if selection ever returns a different adapter, this reports the
    one that actually ran.
    """

    adapter: str
    version: str | None

    def to_dict(self) -> dict[str, object]:
        return {"adapter": self.adapter, "version": self.version}


@dataclass(frozen=True, slots=True)
class TextOutcome:
    """Everything one `text` run produced: the run result and its payload."""

    result: OperationResult
    strategy: str
    engine: EngineDeclaration
    pages: tuple[PageText, ...]


@dataclass(frozen=True, slots=True)
class TableOutcome:
    """Everything one `tables` run produced: the run result and its payload."""

    result: OperationResult
    strategy: str
    engine: EngineDeclaration
    tables: tuple[TableGrid, ...]


# --------------------------------------------------------------------------- #
# Normalization and serialization -- pure functions, unit-tested directly
# --------------------------------------------------------------------------- #


def normalize_page_text(raw: str) -> str:
    """One page's extracted text, normalized identically on both paths.

    ``\\r\\n`` and ``\\r`` become ``\\n``; trailing spaces and tabs are stripped
    per line; a run of trailing newlines collapses to at most one, and a page
    that ended without a newline still does.

    This is a **product behaviour**, documented in ``text --help``, not a test
    fudge: it is what makes "the extracted text equals exactly what the
    generator wrote" a meaningful assertion rather than a brittle one, and it
    makes the two extraction paths comparable byte for byte.
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip(" \t") for line in text.split("\n")]
    text = "\n".join(lines)
    stripped = text.rstrip("\n")
    return stripped + "\n" if len(stripped) != len(text) else stripped


def rows_to_csv_bytes(rows: Sequence[Sequence[str | None]]) -> bytes:
    """Serialize a grid to CSV bytes, in the dialect this product pins.

    ``,`` delimiter, ``"`` quote char, ``QUOTE_MINIMAL``, doubled quotes, no
    escape character, **LF** terminators (not RFC 4180's CRLF -- deliberate,
    for pipeline friendliness on the target platforms, and stated in
    ``tables --help``), UTF-8 with no BOM, and **no header row** -- the grid is
    emitted as found, because nothing in this product knows which row is a
    header and labelling one would be a heuristic dressed as a fact.

    A cell the engine found no text in (``None``) is written as the empty
    string. That is a real, one-directional loss against the JSON shape, which
    keeps the distinction; ``tables --help`` says so rather than leaving a user
    to discover it by diffing the two.

    Serializes into memory and returns **bytes**: this module never opens a
    file, so the result goes to ``AtomicWriter`` and gets the whole safety
    posture for free.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(
        buffer,
        delimiter=",",
        quotechar='"',
        quoting=csv.QUOTE_MINIMAL,
        doublequote=True,
        escapechar=None,
        lineterminator="\n",
    )
    for row in rows:
        writer.writerow(["" if cell is None else cell for cell in row])
    return buffer.getvalue().encode("utf-8")


def table_artifact_bytes(grid: TableGrid, fmt: str) -> bytes:
    """One table's on-disk bytes in *fmt*.

    The JSON artifact deliberately omits ``path``: the file already knows its
    own name, and echoing it back would be the only field in the artifact that
    is a fact about this run rather than about the document.
    """
    if fmt == "csv":
        return rows_to_csv_bytes(grid.rows)
    payload = {key: value for key, value in grid.to_dict().items() if key != "path"}
    return (
        json.dumps({"schema_version": _SCHEMA_VERSION, **payload}, indent=2, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def text_artifact_bytes(texts: Sequence[str]) -> bytes:
    """The bytes of a ``text`` artifact covering *texts*, in page order.

    Pages are joined with a single newline and the file is newline-terminated
    when it has any content at all. A document whose every page is empty
    therefore produces an **empty file**, not a file of blank lines -- the same
    "empty is a real answer" rule the payload follows.
    """
    body = "\n".join(texts).rstrip("\n")
    return (body + "\n").encode("utf-8") if body else b""


# --------------------------------------------------------------------------- #
# Shared planning helpers
# --------------------------------------------------------------------------- #


def _validate_sources(sources: Sequence[Path]) -> None:
    for source in sources:
        if not source.exists():
            raise NoInputError("no such file", path=str(source))
        if source.is_dir():
            raise UsageError("expected a PDF file, not a directory", path=str(source))


def _select_pages(source: Path, pages_spec: str | None) -> tuple[int, ...]:
    """The selection for one source: a sorted, deduplicated **set**.

    `PLAN.md` §4.3 names `text` and `tables` among the set-semantics verbs, so
    ``--pages '3,1,1'`` resolves to pages 1 and 3, once each, in page order.

    A selection that resolves to **zero pages** is exit 4 (`PLAN.md` §5.6): the
    caller addressed nothing. That is a different thing from a page that exists
    and yields nothing, which is exit 0 with an empty result, and keeping the
    two apart is the whole point of this verb's exit-code map.
    """
    engine = require_structure()
    with engine.open_document(source) as document:
        page_count = document.page_count

    spec = pages_spec if pages_spec is not None else ALL_PAGES_TOKEN
    selection = parse(spec, page_count, ordered=False)
    if selection.is_empty:
        raise NoInputError(
            f"{source}: --pages {spec!r} resolved to zero pages; nothing to extract",
            path=str(source),
        )
    return selection.indices


def _require_out_dir_for_template(name_template: str | None, out_dir: Path | None) -> None:
    if name_template is not None and out_dir is None:
        raise UsageError(_NAME_WITHOUT_OUT_DIR)


@dataclass(frozen=True, slots=True)
class _FilesystemPlan:
    """What a real run of this invocation would do at the filesystem tier.

    Mirrors :class:`~pdf_toolkit.safety.atomic.PlannedOutputs`' own X-67
    vocabulary exactly, because that is what makes a prediction and an outcome
    comparable like with like rather than two hand-rolled shapes that agree by
    luck.
    """

    would_exit: int
    would_refuse: dict[str, object] | None
    message: str | None

    @property
    def refused(self) -> bool:
        return self.would_refuse is not None

    def detail(self) -> dict[str, object]:
        """The per-item ``detail`` payload a ``--dry-run`` item carries."""
        payload: dict[str, object] = {"would_exit": self.would_exit}
        if self.would_refuse is not None:
            payload["would_refuse"] = self.would_refuse
        return payload


def _plan_filesystem(
    targets: Sequence[Path], *, out_dir: Path | None, policy: SafetyPolicy, kind: str
) -> _FilesystemPlan:
    """The filesystem tier for this run, through the SHARED primitives only.

    These two verbs are the first in the product to carry **both** destination
    shapes, and the two shapes have two different shared owners. Neither is
    re-implemented here:

    * :func:`~pdf_toolkit.safety.atomic.plan_output_set` owns the ``--out-dir``
      tier — creating the directory, checking it is writable, and checking every
      target for no-clobber. It is called unconditionally, in both modes, so a
      dry run over an occupied target or an unwritable directory predicts what
      the real run does (B-054, extending X-67).
    * :class:`~pdf_toolkit.safety.atomic.AtomicWriter`'s own ``_plan`` owns the
      per-destination tier that a single ``-O`` target has *instead of* a shared
      directory. ``plan_output_set`` deliberately does not check writability
      when ``out_dir`` is ``None`` (its own docstring says it routes only the
      per-target no-clobber check in that shape), because for a single target
      that check belongs to the writer — which is exactly why ``merge``,
      ``compose`` and ``create`` predict through the writer and not through the
      planner.

    A real run walks both tiers because it *calls* both. A dry run must
    therefore consult both, or it predicts half of what the real run checks —
    which is B-054's own defect class one destination shape further out, and it
    is a real, measured gap: found here by contract row ``C15``'s unwritable arm
    reporting dry 0 against real 1, not by reading the code.

    **The one thing to read before touching this function.** The writer tier is
    consulted **only when ``out_dir`` is ``None``**. Under ``--dry-run`` a
    not-yet-existing ``--out-dir`` legitimately stays non-existent (its creation
    is the real run's first mutation), and ``ensure_destination_writable``
    refuses a directory that does not exist — so entering a writer against a
    target inside it would turn every ordinary
    ``text --dry-run --out-dir new/`` into a false exit-1 refusal. That is
    ``plan_output_set``'s own documented Trap 1, reached from the other side.
    """
    plan = plan_output_set(targets, out_dir=out_dir, policy=policy)
    if plan.refusal is not None:
        return _FilesystemPlan(
            would_exit=plan.would_exit,
            would_refuse=plan.would_refuse,
            message=plan.refusal.message,
        )
    if policy.dry_run and out_dir is None:
        for target in targets:
            with AtomicWriter(target, policy=policy, kind=kind) as atomic:
                refusal = atomic.planned_refusal
            if refusal is not None:
                return _FilesystemPlan(
                    would_exit=refusal.exit_code,
                    would_refuse=refusal.to_dict(),
                    message=refusal.message,
                )
    return _FilesystemPlan(would_exit=plan.would_exit, would_refuse=None, message=None)


# --------------------------------------------------------------------------- #
# `text`
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _TextTarget:
    source: Path
    page_numbers: tuple[int, ...]
    target: Path


def _blocks_from(lines: Sequence[TextLine]) -> tuple[TextBlock, ...]:
    """Sorted, indexed blocks -- the ordering invariant, **imposed** here.

    Blocks are sorted by ``(round(y, 2), round(x, 2))`` ascending with a stable
    sort, so ``y`` is non-decreasing down the page on **every** page, rotated
    ones included, because the tool imposes the order rather than hoping the
    engine produced it. Two blocks may legitimately share a ``top`` in a
    multi-column layout, which is why the guarantee is non-decreasing and not
    strictly increasing -- asserting strict increase would be asserting
    something the data cannot support.
    """
    ordered = sorted(lines, key=lambda line: (round(line.top, 2), round(line.x0, 2)))
    return tuple(
        TextBlock(
            index=index,
            text=normalize_page_text(line.text),
            x=line.x0,
            y=line.top,
            width=line.x1 - line.x0,
            height=line.bottom - line.top,
        )
        for index, line in enumerate(ordered)
    )


def _extract_pages(
    sources: Sequence[Path],
    selections: dict[Path, tuple[int, ...]],
    *,
    layout: bool,
) -> tuple[tuple[PageText, ...], EngineDeclaration]:
    pages: list[PageText] = []
    if layout:
        layout_engine = require_layout_text()
        declaration = EngineDeclaration(
            adapter=layout_engine.adapter_name, version=layout_engine.probe().version
        )
        for source in sources:
            numbers = selections[source]
            per_page_lines = layout_engine.extract_lines(str(source), numbers)
            for page_number, lines in zip(numbers, per_page_lines, strict=True):
                blocks = _blocks_from(lines)
                text = "\n".join(block.text for block in blocks)
                pages.append(
                    PageText(
                        source=str(source),
                        page=page_number,
                        char_count=len(text),
                        text=text,
                        blocks=blocks,
                    )
                )
        return tuple(pages), declaration

    fast_engine = require_fast_text()
    declaration = EngineDeclaration(
        adapter=fast_engine.adapter_name, version=fast_engine.probe().version
    )
    for source in sources:
        numbers = selections[source]
        for page_number, raw in zip(
            numbers, fast_engine.extract_text(str(source), numbers), strict=True
        ):
            text = normalize_page_text(raw)
            pages.append(
                PageText(
                    source=str(source),
                    page=page_number,
                    char_count=len(text),
                    text=text,
                    blocks=None,
                )
            )
    return tuple(pages), declaration


def _plan_text_targets(
    sources: Sequence[Path],
    selections: dict[Path, tuple[int, ...]],
    *,
    output: Path | None,
    out_dir: Path | None,
    name_template: str | None,
) -> list[_TextTarget]:
    if output is not None:
        return [
            _TextTarget(source=source, page_numbers=selections[source], target=output)
            for source in sources
        ]
    if out_dir is None:
        return []

    template = name_template if name_template is not None else DEFAULT_TEXT_NAME_TEMPLATE
    per_page = "page" in used_fields(template)
    planned: list[_TextTarget] = []
    for index, source in enumerate(sources, start=1):
        numbers = selections[source]
        if per_page:
            planned.extend(
                _TextTarget(
                    source=source,
                    page_numbers=(page_number,),
                    target=render_name(
                        template,
                        out_dir=out_dir,
                        stem=source.stem,
                        ext=TEXT_EXT,
                        index=index,
                        page=page_number,
                    ),
                )
                for page_number in numbers
            )
        else:
            planned.append(
                _TextTarget(
                    source=source,
                    page_numbers=numbers,
                    target=render_name(
                        template,
                        out_dir=out_dir,
                        stem=source.stem,
                        ext=TEXT_EXT,
                        index=index,
                    ),
                )
            )
    return planned


def _empty_page_warning(page: PageText) -> str:
    return (
        f"no extractable text on page {page.page} of {page.source} "
        "— the page may be a scan; see 'pdftoolkit ocr'"
    )


def extract_text_run(
    sources: Sequence[Path],
    *,
    pages_spec: str | None,
    layout: bool,
    output: Path | None,
    out_dir: Path | None,
    name_template: str | None,
    policy: SafetyPolicy,
) -> TextOutcome:
    """Extract text from every selected page of every source, in input order.

    ``items`` carries one row per planned artifact when a destination was
    given, and one row per input when the text is going to stdout.
    """
    _validate_sources(sources)
    _require_out_dir_for_template(name_template, out_dir)

    selections = {source: _select_pages(source, pages_spec) for source in sources}
    pages, declaration = _extract_pages(sources, selections, layout=layout)
    strategy = "layout" if layout else "fast"

    warnings = tuple(_empty_page_warning(page) for page in pages if page.char_count == 0)
    by_source_page = {(page.source, page.page): page for page in pages}

    planned = _plan_text_targets(
        sources, selections, output=output, out_dir=out_dir, name_template=name_template
    )
    targets = [item.target for item in planned]
    # Data-independent (planned targets against each other), so it is checked
    # identically in both modes -- the same rule `split` follows.
    check_output_collisions(targets)

    plan = _plan_filesystem(targets, out_dir=out_dir, policy=policy, kind="text")

    if not planned:
        items = tuple(
            ItemResult(
                input=str(source),
                output=None,
                ok=True,
                exit_code=0,
                message=f"{len(selections[source])} page(s)",
                bytes_before=source.stat().st_size,
                bytes_after=None,
                duration_ms=0,
                detail=plan.detail() if policy.dry_run else None,
            )
            for source in sources
        )
        return TextOutcome(
            result=OperationResult(
                schema_version=_SCHEMA_VERSION,
                verb=VERB_TEXT,
                dry_run=policy.dry_run,
                items=items,
                warnings=warnings,
                duration_ms=0,
            ),
            strategy=strategy,
            engine=declaration,
            pages=pages,
        )

    if policy.dry_run:
        # A run-level refusal (an unwritable destination) is not attributable to
        # one artifact, and this is not a loss of precision: a planning failure
        # writes nothing at all, so applying the same prediction to every item
        # states exactly what the real run would have done. This is the shared
        # path `split` and `rasterize` already take -- no per-verb prediction
        # logic and no per-verb exit-code logic is added on top of it.
        detail = plan.detail()
        items = tuple(
            ItemResult(
                input=str(item.source),
                output=str(item.target),
                ok=not plan.refused,
                exit_code=plan.would_exit,
                message=(f"{len(item.page_numbers)} page(s)" if not plan.refused else plan.message),
                bytes_before=item.source.stat().st_size,
                bytes_after=None,
                duration_ms=0,
                detail=detail,
            )
            for item in planned
        )
        return TextOutcome(
            result=OperationResult(
                schema_version=_SCHEMA_VERSION,
                verb=VERB_TEXT,
                dry_run=True,
                items=items,
                warnings=warnings,
                duration_ms=0,
            ),
            strategy=strategy,
            engine=declaration,
            pages=pages,
        )

    written: list[ItemResult] = []
    for item in planned:
        payload = text_artifact_bytes(
            [by_source_page[(str(item.source), number)].text for number in item.page_numbers]
        )
        with AtomicWriter(item.target, policy=policy, kind="text") as atomic:
            atomic.stream.write(payload)
        written.append(
            ItemResult(
                input=str(item.source),
                output=str(item.target),
                ok=True,
                exit_code=0,
                message=f"{len(item.page_numbers)} page(s), {len(payload)} bytes",
                bytes_before=item.source.stat().st_size,
                bytes_after=item.target.stat().st_size,
                duration_ms=0,
            )
        )
    return TextOutcome(
        result=OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=VERB_TEXT,
            dry_run=False,
            items=tuple(written),
            warnings=warnings,
            duration_ms=0,
        ),
        strategy=strategy,
        engine=declaration,
        pages=pages,
    )


# --------------------------------------------------------------------------- #
# `tables`
# --------------------------------------------------------------------------- #


def _no_tables_warning(source: Path, page_number: int, strategy: str) -> str:
    other = next(name for name in TABLE_STRATEGIES if name != strategy)
    return (
        f"no tables detected on page {page_number} of {source} with strategy "
        f"'{strategy}' — table extraction is a heuristic; try --strategy {other}"
    )


def _detect_tables(
    sources: Sequence[Path],
    selections: dict[Path, tuple[int, ...]],
    *,
    strategy: str,
) -> tuple[list[tuple[Path, int, int, ExtractedTable]], EngineDeclaration, tuple[str, ...]]:
    engine = require_tables()
    declaration = EngineDeclaration(adapter=engine.adapter_name, version=engine.probe().version)

    found: list[tuple[Path, int, int, ExtractedTable]] = []
    warnings: list[str] = []
    for source in sources:
        numbers = selections[source]
        per_page = engine.extract_tables(str(source), numbers, strategy=strategy)
        for page_number, detected in zip(numbers, per_page, strict=True):
            if not detected:
                warnings.append(_no_tables_warning(source, page_number, strategy))
                continue
            found.extend(
                (source, page_number, index, table) for index, table in enumerate(detected)
            )
    return found, declaration, tuple(warnings)


def extract_tables_run(
    sources: Sequence[Path],
    *,
    pages_spec: str | None,
    strategy: str,
    fmt: str | None,
    output: Path | None,
    out_dir: Path | None,
    name_template: str | None,
    policy: SafetyPolicy,
) -> TableOutcome:
    """Detect tables on every selected page of every source, in input order.

    ``fmt`` is ``None`` when ``--format`` was not given, which is how a
    destination-less ``--format`` earns its warning (AC12) without the CLI
    having to reach into the framework for a parameter source.
    """
    if strategy not in TABLE_STRATEGIES:  # pragma: no cover - the CLI's choice type refuses first
        raise UsageError(
            f"--strategy must be one of {', '.join(TABLE_STRATEGIES)} (got {strategy!r})"
        )
    _validate_sources(sources)
    _require_out_dir_for_template(name_template, out_dir)

    has_destination = output is not None or out_dir is not None
    resolved_fmt = fmt if fmt is not None else TABLE_FORMATS[0]

    selections = {source: _select_pages(source, pages_spec) for source in sources}
    found, declaration, warnings_list = _detect_tables(sources, selections, strategy=strategy)

    warnings = list(warnings_list)
    if fmt is not None and not has_destination:
        warnings.append(FORMAT_WITHOUT_DESTINATION_WARNING)

    template = name_template if name_template is not None else DEFAULT_TABLE_NAME_TEMPLATE
    grids: list[TableGrid] = []
    targets: list[Path] = []
    for source, page_number, index, table in found:
        target: Path | None = None
        if output is not None:
            target = output
        elif out_dir is not None:
            target = render_name(
                template,
                out_dir=out_dir,
                stem=source.stem,
                ext=resolved_fmt,
                index=index,
                page=page_number,
            )
        if target is not None:
            targets.append(target)
        grids.append(
            TableGrid(
                source=str(source),
                page=page_number,
                index=index,
                bbox=table.bbox,
                rows=table.rows,
                path=str(target) if target is not None else None,
            )
        )

    # `-O` onto a selection that yielded two or more tables is an output
    # COLLISION (exit 5), not an OR-3 refusal: `tables` does declare `--output`.
    # The two paths stay distinct, and a test proves they stay distinct.
    check_output_collisions(targets)

    plan = _plan_filesystem(targets, out_dir=out_dir, policy=policy, kind="table")

    if not targets:
        items = tuple(
            ItemResult(
                input=str(source),
                output=None,
                ok=True,
                exit_code=0,
                message=(
                    f"{sum(1 for entry in found if entry[0] == source)} table(s) on "
                    f"{len(selections[source])} page(s)"
                ),
                bytes_before=source.stat().st_size,
                bytes_after=None,
                duration_ms=0,
                detail=plan.detail() if policy.dry_run else None,
            )
            for source in sources
        )
        return TableOutcome(
            result=OperationResult(
                schema_version=_SCHEMA_VERSION,
                verb=VERB_TABLES,
                dry_run=policy.dry_run,
                items=items,
                warnings=tuple(warnings),
                duration_ms=0,
            ),
            strategy=strategy,
            engine=declaration,
            tables=tuple(grids),
        )

    if policy.dry_run:
        detail = plan.detail()
        items = tuple(
            ItemResult(
                input=grid.source,
                output=grid.path,
                ok=not plan.refused,
                exit_code=plan.would_exit,
                message=(
                    f"page {grid.page} table {grid.index}: {grid.row_count}x{grid.col_count}"
                    if not plan.refused
                    else plan.message
                ),
                bytes_before=Path(grid.source).stat().st_size,
                bytes_after=None,
                duration_ms=0,
                detail=detail,
            )
            for grid in grids
        )
        return TableOutcome(
            result=OperationResult(
                schema_version=_SCHEMA_VERSION,
                verb=VERB_TABLES,
                dry_run=True,
                items=items,
                warnings=tuple(warnings),
                duration_ms=0,
            ),
            strategy=strategy,
            engine=declaration,
            tables=tuple(grids),
        )

    written: list[ItemResult] = []
    for grid in grids:
        if grid.path is None:  # pragma: no cover - unreachable: targets is non-empty here
            continue
        target = Path(grid.path)
        payload = table_artifact_bytes(grid, resolved_fmt)
        with AtomicWriter(target, policy=policy, kind="table") as atomic:
            atomic.stream.write(payload)
        written.append(
            ItemResult(
                input=grid.source,
                output=grid.path,
                ok=True,
                exit_code=0,
                message=f"page {grid.page} table {grid.index}: {grid.row_count}x{grid.col_count}",
                bytes_before=Path(grid.source).stat().st_size,
                bytes_after=target.stat().st_size,
                duration_ms=0,
            )
        )
    return TableOutcome(
        result=OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=VERB_TABLES,
            dry_run=False,
            items=tuple(written),
            warnings=tuple(warnings),
            duration_ms=0,
        ),
        strategy=strategy,
        engine=declaration,
        tables=tuple(grids),
    )
