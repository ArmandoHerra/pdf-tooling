"""L6. Output — stdout is the payload; stderr is everything else.

Nothing but the rendered payload is ever written to stdout, at any verbosity.
Diagnostics, warnings and progress go to stderr. That asymmetry is what lets a
caller pipe the tool into ``jq`` without a flag.

The one deliberate exception is a structured **error**: with ``-o table`` an
error is a one-line ``error: ...`` on stderr, but with ``-o json``/``ndjson`` it
is an object on **stdout**, because a machine consumer that is reading stdout
must not have to also read stderr to learn that the run failed.
"""

from __future__ import annotations

import sys
from enum import StrEnum
from typing import Any

from pdf_toolkit.errors import PdfToolkitError
from pdf_toolkit.models import OperationResult
from pdf_toolkit.output.json import render_error_json, render_json, render_ndjson
from pdf_toolkit.output.table import render_error_table, render_table

__all__ = [
    "OutputFormat",
    "auto_format",
    "emit_error",
    "emit_result",
    "render_payload",
]


class OutputFormat(StrEnum):
    """The three shapes ``-o`` selects between."""

    TABLE = "table"
    JSON = "json"
    NDJSON = "ndjson"


def auto_format() -> OutputFormat:
    """``table`` when stdout is a terminal, ``json`` when it is not."""
    try:
        interactive = sys.stdout.isatty()
    except (AttributeError, ValueError):  # pragma: no cover - closed/replaced stream
        interactive = False
    return OutputFormat.TABLE if interactive else OutputFormat.JSON


def render_payload(payload: dict[str, Any], fmt: OutputFormat) -> str:
    """Render an already-``to_dict()``-ed operation payload in the chosen shape."""
    if fmt is OutputFormat.JSON:
        return render_json(payload)
    if fmt is OutputFormat.NDJSON:
        return render_ndjson(payload)
    return render_table(payload)


def emit_result(result: OperationResult, fmt: OutputFormat) -> None:
    """Write the payload to stdout and any warnings to stderr."""
    payload = result.to_dict()
    text = render_payload(payload, fmt)
    if text:
        print(text, file=sys.stdout)
    warnings = payload.get("warnings") or []
    if isinstance(warnings, list):
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)


def emit_error(error: PdfToolkitError, fmt: OutputFormat) -> None:
    """Write a structured error to whichever stream the format contract names."""
    payload = error.to_dict()
    if fmt is OutputFormat.TABLE:
        print(render_error_table(payload), file=sys.stderr)
    else:
        print(render_error_json(payload), file=sys.stdout)
