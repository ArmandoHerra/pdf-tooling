"""The ``version`` verb — the placeholder that proves the spine end to end.

It is deliberately the only verb at this point in the build order: it exercises
the global-flag block, the plan/result model, all three renderers, the stream
discipline and the exit-code path, without opening a single document.

Engine versions come from **distribution metadata**, never from importing an
engine and reading its ``__version__``. That distinction is the difference
between a ``--help`` that answers in well under the startup budget and one that
pays for pdfium and qpdf before printing a line of text.
"""

from __future__ import annotations

import platform
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from typing import Final

import typer

from pdf_toolkit.cli.common import get_config, global_options
from pdf_toolkit.models import SCHEMA_VERSION, ItemResult, OperationResult
from pdf_toolkit.output import emit_result

#: The distributions reported as "engines". Read as metadata, never imported.
ENGINE_DISTRIBUTIONS: Final[tuple[str, ...]] = (
    "pypdf",
    "pypdfium2",
    "reportlab",
    "pikepdf",
    "pdfplumber",
    "pytesseract",
    "pillow",
)

_TOOL_DISTRIBUTION: Final[str] = "pdf-toolkit"
_UNKNOWN: Final[str] = "unknown"


def _distribution_version(name: str) -> str | None:
    try:
        return distribution_version(name)
    except PackageNotFoundError:
        return None


def tool_version() -> str:
    """The installed version of this distribution."""
    return _distribution_version(_TOOL_DISTRIBUTION) or _UNKNOWN


def python_version() -> str:
    """The running interpreter, implementation included."""
    return f"{platform.python_version()} ({platform.python_implementation()})"


def engine_versions() -> tuple[tuple[str, str | None], ...]:
    """One ``(distribution, version-or-None)`` pair per engine, in a stable order."""
    return tuple((name, _distribution_version(name)) for name in ENGINE_DISTRIBUTIONS)


def version_line() -> str:
    """The single line ``--version`` prints: tool, Python, and engine versions."""
    engines = ", ".join(f"{name} {found}" for name, found in engine_versions() if found is not None)
    engine_text = engines or "no engine distributions found"
    return (
        f"pdftoolkit {tool_version()} "
        f"(Python {python_version()} on {sys.platform}); engines: {engine_text}"
    )


def build_result(*, dry_run: bool = False) -> OperationResult:
    """The structured payload behind the ``version`` verb.

    One item per reported component. ``ItemResult.input`` carries the component
    name — this verb reports rather than transforms, so it has no input path to
    put there, and reusing the field keeps the payload on the same shape every
    other verb will emit.
    """
    components: list[tuple[str, str | None]] = [
        (_TOOL_DISTRIBUTION, tool_version()),
        ("python", python_version()),
        *engine_versions(),
    ]
    items = tuple(
        ItemResult(
            input=name,
            output=None,
            ok=found is not None,
            exit_code=0,
            message=found,
            bytes_before=None,
            bytes_after=None,
            duration_ms=0,
        )
        for name, found in components
    )
    warnings = tuple(
        f"{name}: no distribution metadata found" for name, found in components if found is None
    )
    return OperationResult(
        schema_version=SCHEMA_VERSION,
        verb="version",
        dry_run=dry_run,
        items=items,
        warnings=warnings,
        # This verb reads static metadata; there is no timed work to report,
        # and a real wall-clock reading here would make otherwise identical
        # invocations differ byte-for-byte for no informational gain.
        duration_ms=0,
    )


@global_options(consumes=())
def version_command(ctx: typer.Context) -> None:
    """Report the tool, runtime and engine versions.

    REPORTS, NEVER WRITES: this verb writes no files, so -O/--output,
    --out-dir, --name, --in-place, -f/--force and -y/--yes each exit 2.
    """
    config = get_config(ctx)
    result = build_result(dry_run=config.dry_run)
    emit_result(result, config.output_format)
    raise typer.Exit(0)
