"""The ``-o json`` and ``-o ndjson`` renderers.

Both shapes are PUBLIC API from v1.0.0, versioned by ``schema_version``.

Two rules this module exists to make structural rather than remembered:

1. Everything rendered comes from ``to_dict()`` — never from a dataclass field
   read directly — so the published schema cannot drift from the method a test
   pins.
2. Every NDJSON line carries its own ``schema_version``, so a consumer that
   reads a single streamed line, and never sees the first one, can still
   describe what it is holding.

Note that ``import json`` inside this module resolves to the standard library:
absolute imports are the default, so the module's own name does not shadow it.
"""

from __future__ import annotations

import json
from typing import Any

from pdf_toolkit.models import SCHEMA_VERSION


def render_json(payload: dict[str, Any]) -> str:
    """One object: ``schema_version`` at the top level, the rest of the payload."""
    return json.dumps({"schema_version": SCHEMA_VERSION, **payload}, ensure_ascii=False)


def render_ndjson(payload: dict[str, Any]) -> str:
    """One object per item, one per line, each line self-describing."""
    items_raw = payload.get("items") or []
    lines: list[str] = []
    for item in items_raw:
        if not isinstance(item, dict):
            continue
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "verb": payload.get("verb"),
            "dry_run": payload.get("dry_run"),
            **item,
        }
        lines.append(json.dumps(record, ensure_ascii=False))
    return "\n".join(lines)


def render_error_json(error: dict[str, Any]) -> str:
    """The structured error shape. Goes to stdout, not stderr — deliberately."""
    return json.dumps({"schema_version": SCHEMA_VERSION, "error": error}, ensure_ascii=False)
