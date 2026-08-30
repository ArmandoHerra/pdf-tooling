"""``TextEngine`` primary adapter — pdfplumber (over pdfminer.six).

pdfplumber is the layout-aware primary: words, lines, and the table heuristics
the ``tables`` verb exposes. ``pdfium_text`` is the fast path beside it. Both
are MIT/BSD.

PDF-05 shipped probe and version reporting only. **PDF-11 fills in the three
extraction methods** — plain text, layout lines, and tables.

Object-level extraction only
----------------------------
Nothing here touches pdfplumber's *rendering* path: no ``to_image()``, no visual
debugging. That matters for `PLAN.md` §7.2 rather than for performance — the
render path is where a page-image toolchain question could arise at all, and
this adapter's call graph never reaches it.

Line extraction, and why there is exactly one route to it
---------------------------------------------------------
``Page.extract_text_lines()`` is pdfplumber's own line-level API and is present
across the entire version range `pyproject.toml` pins (``>=0.11.10,<0.12``). The
spec allowed a documented fallback — grouping ``extract_words()`` by a ``top``
tolerance — for an installation that did not expose it; that fallback is
deliberately **not** carried here as unreachable code. Instead the absence is
detected and reported as a coded, exit-3 engine failure, because an
``AttributeError`` traceback in front of a user is the failure mode this
product's port layer exists to prevent. Which route ran is recorded in
``changelog.md``.

Memory
------
Every page is ``close()``d as soon as its results are taken. pdfplumber caches
per-page object lists aggressively, and a 400-page document walked without
closing is the difference between a few megabytes and a few hundred.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from pdf_toolkit.adapters import AdapterProbe, package_probe
from pdf_toolkit.errors import EngineMissingError, FailureError
from pdf_toolkit.ports import BROKEN_INSTALL_HINT
from pdf_toolkit.ports.text import ExtractedTable, TextLine

__all__ = ["ADAPTER", "PdfplumberTextAdapter"]

_NAME: Final[str] = "pdfplumber"
_DISTRIBUTION: Final[str] = "pdfplumber"
_MODULE: Final[str] = "pdfplumber"

_CAPABILITIES: Final[frozenset[str]] = frozenset({"text", "words", "layout", "tables"})

#: The line-level API this adapter uses, named once so the absence check and
#: its message cannot drift apart.
_LINES_API: Final[str] = "extract_text_lines"

#: `--strategy` -> pdfplumber's own table-settings pair. The two axes are set
#: together on purpose: mixing a line-based vertical axis with a text-based
#: horizontal one produces a grid whose provenance cannot be stated in one
#: word, and this product's whole table contract is that the output declares
#: which strategy produced it.
_TABLE_SETTINGS: Final[dict[str, dict[str, str]]] = {
    "lines": {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
    "text": {"vertical_strategy": "text", "horizontal_strategy": "text"},
}


class PdfplumberTextAdapter:
    """The pdfplumber-backed ``TextEngine``."""

    kind: Final[str] = "python-package"

    @property
    def adapter_name(self) -> str:
        return _NAME

    def capabilities(self) -> frozenset[str]:
        return _CAPABILITIES

    def probe(self) -> AdapterProbe:
        return package_probe(_MODULE, _DISTRIBUTION)

    def extract_text(self, path: str, page_numbers: Sequence[int]) -> tuple[str, ...]:
        """See the Protocol docstring in ``ports/text.py``."""
        texts: list[str] = []
        for page in _pages(path, page_numbers):
            try:
                texts.append(page.extract_text() or "")
            finally:
                page.close()
        return tuple(texts)

    def extract_lines(
        self, path: str, page_numbers: Sequence[int]
    ) -> tuple[tuple[TextLine, ...], ...]:
        """See the Protocol docstring in ``ports/text.py``."""
        out: list[tuple[TextLine, ...]] = []
        for page in _pages(path, page_numbers):
            try:
                extract = getattr(page, _LINES_API, None)
                if extract is None:  # pragma: no cover - impossible in the pinned range
                    raise EngineMissingError(
                        f"the installed {_NAME} has no {_LINES_API}(), so layout-aware "
                        f"line extraction is unavailable. Install it with: "
                        f"{BROKEN_INSTALL_HINT}. "
                        f"Run 'pdftoolkit doctor' to see which engines resolved."
                    )
                out.append(
                    tuple(
                        TextLine(
                            text=str(line["text"]),
                            x0=float(line["x0"]),
                            top=float(line["top"]),
                            x1=float(line["x1"]),
                            bottom=float(line["bottom"]),
                        )
                        for line in extract(strip=True, return_chars=False)
                    )
                )
            finally:
                page.close()
        return tuple(out)

    def extract_tables(
        self, path: str, page_numbers: Sequence[int], *, strategy: str
    ) -> tuple[tuple[ExtractedTable, ...], ...]:
        """See the Protocol docstring in ``ports/text.py``."""
        settings = _TABLE_SETTINGS[strategy]
        out: list[tuple[ExtractedTable, ...]] = []
        for page in _pages(path, page_numbers):
            try:
                found = []
                for table in page.find_tables(settings):
                    x0, top, x1, bottom = (float(value) for value in table.bbox)
                    rows = tuple(tuple(row) for row in table.extract())
                    found.append(ExtractedTable(bbox=(x0, top, x1, bottom), rows=rows))
                out.append(tuple(found))
            finally:
                page.close()
        return tuple(out)


def _pages(path: str, page_numbers: Sequence[int]) -> Any:
    """Yield the requested 1-based pages, opening the document exactly once.

    A generator rather than a list so a caller that closes each page as it goes
    never holds two pages' object caches at the same time. The document itself
    is closed when the generator is exhausted or garbage-collected, which is
    guaranteed here because every caller in this module iterates it to
    completion.
    """
    import pdfplumber

    try:
        document = pdfplumber.open(path)
    except Exception as error:  # noqa: BLE001 - pdfminer raises a wide, unstable family
        raise FailureError(f"{path}: could not be read: {error}", path=path) from error
    try:
        for page_number in page_numbers:
            try:
                yield document.pages[page_number - 1]
            except IndexError as error:  # pragma: no cover - callers validate the selection
                raise FailureError(
                    f"{path}: page {page_number} is out of range", path=path
                ) from error
    finally:
        document.close()


ADAPTER: Final[PdfplumberTextAdapter] = PdfplumberTextAdapter()
