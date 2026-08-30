"""``TextEngine`` secondary adapter — pypdfium2's text extraction fast path.

The same engine as ``pdfium_raster``, a different port. PDFium extracts text
several times faster than the pdfplumber primary and knows nothing about layout,
words or tables, so it is the right answer for "give me the characters" and the
wrong one for "give me the columns". Which is exactly why both exist behind one
port, selected by capability rather than by a guess at call time.

PDF-05 shipped probe and version reporting only. **PDF-11 fills in
:meth:`PdfiumTextAdapter.extract_text` — the `text` verb's default path.**
PDFium *is* the fast path: `PLAN.md` §7.2 forbids every shell-out alternative
outright, not as a fallback and not "just for a comparison", so there is one
implementation here and no second route to the same answer.

One document handle per call, opened and closed inside the method (the same
posture ``pdfium_raster`` takes, and for the same reason): no pdfium object
crosses this method's return, only plain strings.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pdf_toolkit.adapters import AdapterProbe, package_probe
from pdf_toolkit.errors import FailureError

__all__ = ["ADAPTER", "CAPABILITY_SUMMARY", "PdfiumTextAdapter"]

_NAME: Final[str] = "pypdfium2"
_DISTRIBUTION: Final[str] = "pypdfium2"
_MODULE: Final[str] = "pypdfium2"

_CAPABILITIES: Final[frozenset[str]] = frozenset({"text", "fast-text"})

#: Rendered into ``TextEngine``'s ``detail``.
CAPABILITY_SUMMARY: Final[str] = "fast text extraction, no layout analysis"


class PdfiumTextAdapter:
    """The PDFium-backed ``TextEngine`` fast path."""

    kind: Final[str] = "python-package"

    @property
    def adapter_name(self) -> str:
        return _NAME

    def capabilities(self) -> frozenset[str]:
        return _CAPABILITIES

    def probe(self) -> AdapterProbe:
        return package_probe(_MODULE, _DISTRIBUTION)

    def extract_text(self, path: str, page_numbers: Sequence[int]) -> tuple[str, ...]:
        """See the Protocol docstring in ``ports/text.py``.

        The engine import is function-local (``adapters/__init__``'s rule 1):
        probing must never pay pdfium's import cost.

        A page that exists and yields no characters comes back as the empty
        string. That is the honest answer for an image-only scan, and it is
        deliberately not turned into a placeholder, a space, or an OCR attempt —
        the later `ocr` verb's own acceptance signal is that this result becomes
        non-empty, so fabricating anything here would destroy another verb's
        proof.
        """
        import pypdfium2 as pdfium  # type: ignore[import-untyped]

        document = pdfium.PdfDocument(path)
        try:
            texts: list[str] = []
            for page_number in page_numbers:
                try:
                    page = document.get_page(page_number - 1)
                except pdfium.PdfiumError as error:
                    raise FailureError(
                        f"{path}: page {page_number} could not be opened: {error}", path=path
                    ) from error
                try:
                    textpage = page.get_textpage()
                    try:
                        texts.append(textpage.get_text_range())
                    finally:
                        textpage.close()
                except pdfium.PdfiumError as error:
                    raise FailureError(
                        f"{path}: page {page_number} text could not be extracted: {error}",
                        path=path,
                    ) from error
                finally:
                    page.close()
            return tuple(texts)
        finally:
            document.close()


ADAPTER: Final[PdfiumTextAdapter] = PdfiumTextAdapter()
