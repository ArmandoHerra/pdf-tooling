"""The stderr logger, and the redaction filter every record passes through.

Stream discipline: this module writes to **stderr only**. stdout carries the
rendered payload and nothing else, so that ``pdftoolkit ... | jq`` works whether
or not the run was verbose.

Redaction is installed here, on the first commit, rather than retrofitted later
around a live credential: a module-level registry holds values that must never
appear in a record, and a ``logging.Filter`` scrubs them at *every* verbosity,
including the most verbose.

**The password work deliberately does NOT use that registry** (PDF-13). A
process-global set of live plaintext passwords is a new leak surface built to
defend against leaks, and it cannot catch a value that was sliced, partially
formatted or escape-encoded on its way out. Prevention by construction beats
scrubbing. What PDF-13 added instead is one behaviour below: a
:class:`~pdf_toolkit.secret.Secret` in ``record.msg`` or ``record.args``
renders through its own redacting ``__str__``. The filter does **not** scan
strings for secrets. :func:`register_secret` stays available for a caller that
genuinely has a plaintext string to suppress; nothing in this product does.

Note that ``import logging`` inside this module resolves to the standard
library: absolute imports are the default, so the module's own name does not
shadow it.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Final

from pdf_toolkit.secret import Secret

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


def _render(value: Any) -> Any:
    """One log argument, rendered safely (PDF-13).

    A :class:`~pdf_toolkit.secret.Secret` is converted to ``str`` **here**,
    which is where its redacting ``__str__`` produces ``"<redacted>"``. That
    is a type-driven guarantee rather than a search: it holds for a value
    this filter has never seen, at every verbosity, and it cannot be defeated
    by slicing or escape-encoding the way a plaintext-registry scrub can.
    Strings are scrubbed against the registry as before; nothing else is
    touched.
    """
    if isinstance(value, Secret):
        return str(value)
    if isinstance(value, str):
        return _scrub(value)
    return value


class RedactingFilter(logging.Filter):
    """Replace every registered secret in a record with a fixed placeholder."""

    def filter(self, record: logging.LogRecord) -> bool:
        # NOT gated on `_SECRETS` any more: the `Secret` rendering below is a
        # type guarantee that must hold whether or not anything was ever
        # registered, and gating it on a registry nothing populates would
        # make it dead code (`_SECRETS` is empty in this product by design).
        if isinstance(record.msg, Secret):
            record.msg = str(record.msg)
        elif isinstance(record.msg, str) and _SECRETS:
            record.msg = _scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {key: _render(value) for key, value in record.args.items()}
            elif isinstance(record.args, tuple):
                scrubbed: tuple[Any, ...] = tuple(_render(value) for value in record.args)
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
