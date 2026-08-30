"""Per-page text extraction via ``pypdfium2`` directly — for AC1/AC4/AC5/AC15 only.

The `text` verb is PDF-11 and does not exist yet; these round-trip tests
still need to read back what a page actually says, so they go straight to
the rendering engine rather than through a verb that isn't built. PDF-06's
generated corpus (`tests/corpus.py`) declares the exact strings reportlab
wrote, so any assertion built on this helper is cross-checked against a
known value, never against the tool's own earlier output.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["page_text", "page_texts"]


def page_text(path: Path, page_number: int) -> str:
    """The extracted text of *path*'s 1-based *page_number*."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        page = pdf[page_number - 1]
        try:
            textpage = page.get_textpage()
            try:
                return textpage.get_text_range()
            finally:
                textpage.close()
        finally:
            page.close()
    finally:
        pdf.close()


def page_texts(path: Path) -> tuple[str, ...]:
    """Every page's extracted text, in page order."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        texts: list[str] = []
        for page in pdf:
            try:
                textpage = page.get_textpage()
                try:
                    texts.append(textpage.get_text_range())
                finally:
                    textpage.close()
            finally:
                page.close()
        return tuple(texts)
    finally:
        pdf.close()
