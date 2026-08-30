"""``OfficeConverter`` adapter — the ``soffice`` (LibreOffice) binary.

The second of the two ports that can legitimately be absent. LibreOffice is
MPL-2.0, which ``PLAN.md`` §12 R-11 records as permitted: MPL is file-level
copyleft, this product neither modifies nor vendors it, and the licence gate's
deny pattern is ``AGPL|GPL|LGPL`` only.

Conversion itself arrives with the office spec. What matters here is that the
spawn goes through ``subprocess_util.run``: ``soffice`` starts a background
process of its own and is the second binary this product will drive, so the
process-**group** kill is the reason a converted-document timeout does not leave
an office daemon resident.
"""

from __future__ import annotations

import re
import shutil
from typing import Final

from pdf_toolkit.adapters import AdapterProbe, subprocess_util

__all__ = ["ADAPTER", "BINARY", "PROBE_TIMEOUT_S", "SofficeOfficeAdapter"]

_NAME: Final[str] = "soffice"

#: A module-level string literal on purpose -- see the note on the same constant
#: in ``tesseract_ocr``: this is the shape the licence walk can resolve.
BINARY: Final[str] = "soffice"

#: LibreOffice's first start can be slow, but a *version* query is not a
#: conversion. Kept short so `doctor` stays fast, and generous enough that a cold
#: profile directory does not read as an absent engine.
PROBE_TIMEOUT_S: Final[float] = 20.0

_CAPABILITIES: Final[frozenset[str]] = frozenset({"office-convert", "to-pdf"})

#: ``LibreOffice 26.2.5.2 620(Build:2)`` -> ``26.2.5.2``.
_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"([0-9]+(?:\.[0-9]+)+)")


def _parse_version(line: str) -> str | None:
    match = _VERSION_RE.search(line.strip())
    return match.group(1) if match else None


class SofficeOfficeAdapter:
    """The ``soffice``-binary-backed ``OfficeConverter``."""

    kind: Final[str] = "system-binary"

    @property
    def adapter_name(self) -> str:
        return _NAME

    def capabilities(self) -> frozenset[str]:
        return _CAPABILITIES

    def probe(self) -> AdapterProbe:
        if shutil.which(BINARY) is None:
            return AdapterProbe(available=False, version=None, detail=None)

        # argv[0] is the module-level constant, not the located path -- see the
        # note on the same line in `tesseract_ocr`.
        run = subprocess_util.run([BINARY, "--version"], timeout=PROBE_TIMEOUT_S, check=False)
        first = run.first_line() or run.first_line("stderr")
        version = _parse_version(first)
        if version is None:
            detail = f"version line not recognised: {first!r}" if first else "no version line"
            return AdapterProbe(available=True, version=None, detail=detail)
        return AdapterProbe(available=True, version=version, detail=first or None)


ADAPTER: Final[SofficeOfficeAdapter] = SofficeOfficeAdapter()
