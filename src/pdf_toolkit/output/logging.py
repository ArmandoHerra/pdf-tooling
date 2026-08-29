"""The stderr logger, and the redaction filter every record passes through.

Stream discipline: this module writes to **stderr only**. stdout carries the
rendered payload and nothing else, so that ``pdftoolkit ... | jq`` works whether
or not the run was verbose.

Redaction is installed here, on the first commit, rather than retrofitted later
around a live credential: a module-level registry holds values that must never
appear in a record, and a ``logging.Filter`` scrubs them at *every* verbosity,
including the most verbose. The spec that resolves passwords registers values
with :func:`register_secret`; the mechanism does not wait for it.

Note that ``import logging`` inside this module resolves to the standard
library: absolute imports are the default, so the module's own name does not
shadow it.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Final

__all__ = [
    "REDACTION_PLACEHOLDER",
    "RedactingFilter",
    "clear_secrets",
    "configure_logging",
    "get_logger",
    "register_secret",
]

LOGGER_NAME: Final[str] = "pdf_toolkit"
REDACTION_PLACEHOLDER: Final[str] = "<redacted>"

_SECRETS: set[str] = set()


def register_secret(value: str) -> None:
    """Register a value that must never appear in a log record.

    Short values are ignored: redacting a one-character string would blank out
    unrelated text and make the log actively misleading.
    """
    if value and len(value) > 1:
        _SECRETS.add(value)


def clear_secrets() -> None:
    """Drop every registered secret. Exists for test isolation."""
    _SECRETS.clear()


def _scrub(text: str) -> str:
    for secret in _SECRETS:
        if secret in text:
            text = text.replace(secret, REDACTION_PLACEHOLDER)
    return text


class RedactingFilter(logging.Filter):
    """Replace every registered secret in a record with a fixed placeholder."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not _SECRETS:
            return True
        if isinstance(record.msg, str):
            record.msg = _scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: (_scrub(value) if isinstance(value, str) else value)
                    for key, value in record.args.items()
                }
            elif isinstance(record.args, tuple):
                scrubbed: tuple[Any, ...] = tuple(
                    _scrub(value) if isinstance(value, str) else value for value in record.args
                )
                record.args = scrubbed
        return True


def resolve_level(*, verbose: int, quiet: bool) -> int:
    """The pinned verbosity map: default WARNING, ``-v`` INFO, ``-vv`` DEBUG, ``-q`` ERROR."""
    if quiet:
        return logging.ERROR
    if verbose >= 2:
        return logging.DEBUG
    if verbose == 1:
        return logging.INFO
    return logging.WARNING


def color_enabled(*, no_color: bool) -> bool:
    """Colour is off when asked, when ``NO_COLOR`` is set, or when stderr is not a TTY."""
    if no_color or os.environ.get("NO_COLOR"):
        return False
    return sys.stderr.isatty()


def configure_logging(*, verbose: int = 0, quiet: bool = False, no_color: bool = False) -> None:
    """Install the single stderr handler for this process. Idempotent."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(resolve_level(verbose=verbose, quiet=quiet))
    logger.propagate = False

    for existing in list(logger.handlers):
        logger.removeHandler(existing)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    # The filter is installed on the logger too, so a record emitted through a
    # handler added elsewhere is still scrubbed.
    logger.addFilter(RedactingFilter())
    del no_color  # Colour styling is applied by renderers, not by the logger.


def get_logger(name: str | None = None) -> logging.Logger:
    """The package logger, or a child of it."""
    if name is None:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
