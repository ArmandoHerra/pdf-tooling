"""``merge`` — concatenate PDFs, ordered per-input page selection (Design §D1-D3, D8-D10).

Framework-free per L2: no ``typer``/``click``, no ``sys.exit``, no printing.
Grammar knowledge stays entirely in ``ops/pagerange.py`` (G6, AC7) — this
module imports :func:`~pdf_toolkit.ops.pagerange.is_valid_spec` and
:func:`~pdf_toolkit.ops.pagerange.parse` and never re-implements a token
shape; ``str.split(",")`` for a plain separator is not grammar parsing and is
not covered by that rule.

**Fail-closed on any input (Design §D1).** ``merge``'s output is a single
artifact whose correctness depends on every input, so every input is opened
and every selection resolved — via `contextlib.ExitStack`, which is what lets
"open N documents, one context each" stay a single ``with``-shaped block for
a variable-length input list — **before anything is written**. This
deliberately overrides `PLAN.md` §5.4's default continue-on-failure policy
for this verb alone: a partially merged document is a wrong document that
looks like a right one.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pdf_toolkit.errors import NoInputError, UsageError
from pdf_toolkit.models import SCHEMA_VERSION as _SCHEMA_VERSION
from pdf_toolkit.models import ItemResult, OperationResult
from pdf_toolkit.ops.pagerange import ALL_PAGES_TOKEN, is_valid_spec, parse
from pdf_toolkit.ports.structure import (
    OpenStructureDocument,
    StructureWriter,
    require_structure,
)
from pdf_toolkit.safety.atomic import AtomicWriter
from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = [
    "BOOKMARK_MODES",
    "MergeInput",
    "merge_documents",
    "resolve_merge_inputs",
    "split_input_spec",
]

VERB: Final[str] = "merge"

#: `--bookmarks` values (Design §D3). A plain tuple, not an Enum, because this
#: module is framework-free and the CLI layer is the one that needs an Enum
#: type for Typer's own choice validation; it defines its own and this tuple
#: is what a unit test checks it against.
BOOKMARK_MODES: Final[tuple[str, ...]] = ("per-file", "preserve", "none")


def split_input_spec(raw: str) -> tuple[str, str | None]:
    """Disambiguate one merge ``INPUT`` argument (Design §D2, the colon problem).

    The separator is the **last** colon in *raw*, and the split is taken only
    when the text after it is non-empty and syntactically valid per §4.3
    (:func:`~pdf_toolkit.ops.pagerange.is_valid_spec`). Otherwise the whole
    argument is the path.

    Returns ``(path_text, selection_or_None)`` — TEXT, not a resolved
    :class:`~pathlib.Path` and not a parsed selection. Existence is a caller
    concern (a nonexistent path is exit 4, D2 step 4); resolving the
    selection needs a page count this function does not have.
    """
    last = raw.rfind(":")
    if last == -1:
        return raw, None
    tail = raw[last + 1 :]
    if not tail or not is_valid_spec(tail):
        return raw, None
    return raw[:last], tail


@dataclass(frozen=True, slots=True)
class MergeInput:
    """One resolved merge operand."""

    raw: str
    """The argument exactly as given — selection suffix included, if any."""

    path: Path
    selection: str | None
    """The raw range text, or ``None`` meaning every page is contributed."""


def resolve_merge_inputs(raw_args: tuple[str, ...]) -> tuple[MergeInput, ...]:
    """Disambiguate and existence-check every ``INPUT`` argument (D2, E2).

    One or more inputs are required (E2: the plan's own acceptance signal is
    a *single*-input merge). Every failure here — a missing argument list, a
    nonexistent path, a directory operand — aborts before any document is
    opened.
    """
    if not raw_args:
        raise UsageError("merge needs at least one INPUT")

    resolved: list[MergeInput] = []
    for raw in raw_args:
        path_text, selection = split_input_spec(raw)
        path = Path(path_text)
        if not path.exists():
            read_as = (
                f"read {path_text!r} as the path and {selection!r} as the selection"
                if selection is not None
                else "read the whole argument as the path"
            )
            raise NoInputError(
                f"{raw!r}: no such file ({read_as}); if the file itself is named "
                f"with a colon, append ':{ALL_PAGES_TOKEN}' to force the whole "
                f"text to be read as the path",
                path=path_text,
            )
        if path.is_dir():
            raise UsageError(
                "expected a PDF file, not a directory; globbing is the shell's job",
                path=path_text,
            )
        resolved.append(MergeInput(raw=raw, path=path, selection=selection))
    return tuple(resolved)


def _clean_title(stem: str) -> str:
    """D3: bookmark titles are the input path's stem, NUL bytes stripped."""
    return stem.replace("\x00", "")


def _apply_bookmarks(
    writer: StructureWriter,
    mode: str,
    *,
    inputs: tuple[MergeInput, ...],
    documents: tuple[OpenStructureDocument, ...],
    first_dest_page: tuple[int, ...],
    dest_maps: tuple[dict[int, int], ...],
) -> None:
    """Design §D3 — apply exactly one of the three outline policies."""
    if mode == "none":
        return
    if mode == "per-file":
        for merge_input, dest_page in zip(inputs, first_dest_page, strict=True):
            writer.add_outline_entry(_clean_title(merge_input.path.stem), dest_page)
        return
    if mode == "preserve":
        for document, dest_map in zip(documents, dest_maps, strict=True):
            writer.import_outline(document, page_map=dest_map)
        return
    raise AssertionError(f"unknown --bookmarks mode {mode!r}")  # pragma: no cover - CLI validates


def merge_documents(
    inputs: tuple[MergeInput, ...],
    *,
    output: Path,
    bookmarks: str,
    policy: SafetyPolicy,
) -> OperationResult:
    """Merge *inputs* into *output* (Design §D1, §D8).

    All inputs are opened and all selections resolved before the first byte
    is written (D1). ``items`` carries **one row per input argument**, in
    argv order, ``output`` set to the merged target on every row (D8) — E8's
    resolution for merge's N:1 shape, without touching ``models.py``.
    """
    engine = require_structure()

    with ExitStack() as stack:
        opened: list[OpenStructureDocument] = []
        indices_per_input: list[tuple[int, ...]] = []
        for merge_input in inputs:
            document = stack.enter_context(engine.open_document(merge_input.path))
            page_range = parse(
                merge_input.selection or ALL_PAGES_TOKEN, document.page_count, ordered=True
            )
            if page_range.is_empty:
                raise NoInputError(
                    f"{merge_input.raw}: selection matched no pages",
                    path=str(merge_input.path),
                )
            opened.append(document)
            indices_per_input.append(page_range.indices)

        writer = engine.new_writer()
        first_dest_page: list[int] = []
        dest_maps: list[dict[int, int]] = []
        dest_cursor = 1
        for document, indices in zip(opened, indices_per_input, strict=True):
            first_dest_page.append(dest_cursor)
            writer.append_pages(document, indices)
            local_map: dict[int, int] = {}
            for source_page in indices:
                local_map.setdefault(source_page, dest_cursor)
                dest_cursor += 1
            dest_maps.append(local_map)

        _apply_bookmarks(
            writer,
            bookmarks,
            inputs=inputs,
            documents=tuple(opened),
            first_dest_page=tuple(first_dest_page),
            dest_maps=tuple(dest_maps),
        )

        refusal = None
        with AtomicWriter(output, policy=policy, kind="pdf") as atomic:
            if atomic.is_dry_run:
                refusal = atomic.planned_refusal
            else:
                writer.write(atomic.stream)

        merged_size = output.stat().st_size if output.exists() else None
        items = tuple(
            ItemResult(
                input=merge_input.raw,
                output=str(output),
                ok=refusal is None,
                exit_code=0 if refusal is None else refusal.exit_code,
                message=(f"{len(indices)} pages selected" if refusal is None else refusal.message),
                bytes_before=merge_input.path.stat().st_size,
                bytes_after=merged_size,
                duration_ms=0,
            )
            for merge_input, indices in zip(inputs, indices_per_input, strict=True)
        )
        return OperationResult(
            schema_version=_SCHEMA_VERSION,
            verb=VERB,
            dry_run=policy.dry_run,
            items=items,
            warnings=(),
            duration_ms=0,
        )
