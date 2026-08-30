"""The ``meta get`` verb (PDF-14).

Typer surface only: flag validation, one call into ``ops/metadata.py``, one
result rendered. No PDF logic lives here.

**One verb per file** — see ``cmd_meta.py``'s module docstring for the
mechanism: ``cli/common.py``'s OR-3 declaration is keyed by module, and
``meta`` (the sub-``Typer`` itself) declares none at all.

**OR-3.** ``meta get`` **reports; it writes nothing**, so it declares
``consumes=()`` and all four of ``-O``, ``--out-dir``, ``--name`` and
``--in-place`` exit 2 from the shared option layer — the same shape
``info``/``permissions`` already have.

**Bespoke top-level JSON shape, not ``OperationResult``.** Design D2.1's own
example shows ``schema_version``/``path``/``info``/``xmp``/``xmp_raw``/
``disagreements``/``residual_surfaces`` at the ABSOLUTE top level of
``-o json`` — no ``verb``/``items``/``warnings``/``exit_code`` envelope.
This mirrors ``cmd_info.py``'s own precedent (the FIRST report verb, built
before the later ``OperationResult`` convention existed): ``ops/metadata.py``
returns a plain :class:`~pdf_toolkit.models.MetadataReport`, and this module
owns turning it into the three rendered shapes, exactly as ``cmd_info.py``
owns ``build_payload``/``_table_rows``/``_render`` for ``info``.
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Annotated, Any

import typer

from pdf_toolkit.cli.common import get_config, global_options
from pdf_toolkit.errors import NoInputError, UsageError
from pdf_toolkit.ops.metadata import meta_get_run
from pdf_toolkit.output import OutputFormat, render_payload

__all__ = ["build_payload", "meta_get_command"]

VERB = "meta get"

_HELP = """Read a document's information dictionary AND its XMP packet,
side by side -- never merged.

Selected through the StructureEngine port, by capability -- never by adapter
name.

BOTH HALVES, ALWAYS. A PDF carries metadata in two places: the /Info
dictionary and an XMP packet. Readers generally PREFER XMP, and the two are
frequently out of sync -- a file edited by two tools ends up with a /Title
from one and a dc:title from the other. This command reports what each half
actually says and states any disagreement explicitly; it never guesses which
one is "right" and never emits a merged, single answer.

--xmp adds the raw XMP packet (verbatim bytes, as text) to the report --
parsing loses custom namespaces, so an operator auditing what they are about
to share may need the packet itself, not just the parsed fields.

REPORTS, NEVER WRITES: -O, --out-dir, --name and --in-place all exit 2.
"""


def build_payload(source: Path, *, xmp: bool, dry_run: bool) -> dict[str, Any]:
    """The canonical `-o json` payload -- the report's own `to_dict()`, plus
    `verb`/`dry_run` alongside it (mirrors `cmd_info.py::build_payload`)."""
    report = meta_get_run(source, xmp=xmp)
    return {"verb": VERB, "dry_run": dry_run, **report.to_dict()}


def _table_block(title: str, lines: list[str]) -> list[str]:
    rendered = [title]
    rendered.extend(f"  {line}" for line in lines) if lines else rendered.append("  (none)")
    return rendered


def _render_table(payload: dict[str, Any]) -> str:
    """Design D2.1's four-block table: Document Info, XMP, Disagreements,
    Not cleared by --clear-all. An empty block prints `(none)` rather than
    omitting the heading, so an empty section is never ambiguous with a
    missing feature."""
    info = payload.get("info") or {}
    xmp = payload.get("xmp")
    disagreements = payload.get("disagreements") or []
    residual = payload.get("residual_surfaces") or {}

    lines: list[str] = [f"path: {payload.get('path')}"]
    lines.extend(_table_block("Document Info", [f"{key}: {value}" for key, value in info.items()]))
    if xmp is None:
        lines.extend(_table_block("XMP", []))
    else:
        lines.extend(_table_block("XMP", [f"{key}: {value}" for key, value in xmp.items()]))
    lines.extend(
        _table_block(
            "Disagreements",
            [
                f"{item['field']}: info={item['info']!r} xmp={item['xmp']!r}"
                for item in disagreements
            ],
        )
    )
    lines.extend(
        _table_block(
            "Not cleared by --clear-all", [f"{key}: {value}" for key, value in residual.items()]
        )
    )
    return "\n".join(lines)


def _render(payload: dict[str, Any], fmt: OutputFormat) -> str:
    if fmt is OutputFormat.JSON:
        return render_payload(payload, fmt)
    if fmt is OutputFormat.NDJSON:
        return _json.dumps(payload, ensure_ascii=False)
    return _render_table(payload)


def _reject_missing_sources(sources: list[Path]) -> None:
    for source in sources:
        if not source.exists():
            raise NoInputError("no such file", path=str(source))
        if source.is_dir():
            raise UsageError("expected a PDF file, not a directory", path=str(source))


@global_options(consumes=())
def meta_get_command(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(metavar="PDF", help="The PDF to report on.")],
    xmp: Annotated[
        bool,
        typer.Option("--xmp", help="Add the raw XMP packet (verbatim) to the report."),
    ] = False,
) -> None:
    """Read a document's information dictionary and its XMP packet, side by side."""
    config = get_config(ctx)
    _reject_missing_sources([source])

    payload = build_payload(source, xmp=xmp, dry_run=config.dry_run)
    text = _render(payload, config.output_format)
    if text:
        typer.echo(text)
    raise typer.Exit(0)


meta_get_command.__doc__ = _HELP
