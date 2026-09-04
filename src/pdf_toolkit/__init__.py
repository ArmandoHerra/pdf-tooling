"""pdf-tooling — one safe command-line tool for the common PDF chores.

The distribution is ``pdf-tooling``; the import package is ``pdf_toolkit``; the
console scripts are ``pdftoolkit`` and ``pdf-toolkit``. The three names differ
deliberately (see README).

This module deliberately imports nothing at module scope. ``__version__`` is
resolved lazily from *distribution metadata* so that importing the package —
which every CLI invocation does — never pays for a metadata scan it does not
need, and never reaches into an engine library to read a ``__version__``
attribute.
"""

from __future__ import annotations

__all__ = ["__version__"]

_DISTRIBUTION = "pdf-tooling"
_UNKNOWN_VERSION = "0.0.0+unknown"


def __getattr__(name: str) -> str:
    if name == "__version__":
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version(_DISTRIBUTION)
        except PackageNotFoundError:  # pragma: no cover - only when not installed
            return _UNKNOWN_VERSION
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
