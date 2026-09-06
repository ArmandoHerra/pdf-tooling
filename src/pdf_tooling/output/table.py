"""The ``-o table`` renderer — a hand-rolled column formatter.

Deliberately not ``rich``: startup time is a user-facing feature of a CLI meant
to sit in a shell loop, and no module under ``src/`` may import ``rich`` even
though the CLI framework pulls it into the environment.

Everything here consumes the dict produced by ``OperationResult.to_dict()`` (or
``PdfToolkitError.to_dict()``); it never reaches into a dataclass field.
"""

from __future__ import annotations

from typing import Any

#: Item keys that never earn a column of their own in the human table.
_SUPPRESSED_COLUMNS: frozenset[str] = frozenset({"ok"})


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    """Column order: first row's key order, then any key a later row adds.

    A column whose every value is ``None`` is dropped — a table that is mostly
    ``-`` teaches the reader nothing.
    """
    ordered: list[str] = []
    for row in rows:
        for key in row:
            if key not in ordered and key not in _SUPPRESSED_COLUMNS:
                ordered.append(key)
    return [key for key in ordered if any(row.get(key) is not None for row in rows)]


def render_table(payload: dict[str, Any]) -> str:
    """Render an operation payload as an aligned, plain-text table."""
    rows_raw = payload.get("items") or []
    rows: list[dict[str, Any]] = [row for row in rows_raw if isinstance(row, dict)]
    if not rows:
        return f"{payload.get('verb', 'operation')}: no items"

    columns = _columns(rows)
    if not columns:
        return f"{payload.get('verb', 'operation')}: no reportable columns"

    header = [column.replace("_", " ") for column in columns]
    body = [[_cell(row.get(column)) for column in columns] for row in rows]
    widths = [
        max(len(header[index]), *(len(row[index]) for row in body)) for index in range(len(columns))
    ]

    lines = [
        "  ".join(header[index].ljust(widths[index]) for index in range(len(columns))).rstrip(),
        "  ".join("-" * widths[index] for index in range(len(columns))),
    ]
    lines.extend(
        "  ".join(row[index].ljust(widths[index]) for index in range(len(columns))).rstrip()
        for row in body
    )
    return "\n".join(lines)


def render_error_table(error: dict[str, Any]) -> str:
    """Render an error payload as the single line that goes to stderr."""
    message = error.get("message", "")
    path = error.get("path")
    if path:
        return f"error: {message} ({path})"
    return f"error: {message}"
