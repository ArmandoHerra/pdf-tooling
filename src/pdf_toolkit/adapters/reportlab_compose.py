"""``ComposeEngine`` adapter — reportlab.

reportlab is the only ``ComposeEngine`` backend in v1 and needs no system
libraries, so ``pdftoolkit compose`` and ``pdftoolkit create`` work on a bare
install. The WeasyPrint adapter that would sit beside it is Phase 2 behind the
``[html]`` extra, and is deliberately **not** created here — which is why
``doctor`` prints six rows and not seven, and why ``EngineReport.kind``'s third
value ``"optional-extra"`` is declared but unused by any v1 row.

PDF-05 shipped probe and version reporting only. PDF-10 fills in both render
paths. Four mechanics in this file are load-bearing, and every one of them was
measured against reportlab 5.0.1 rather than assumed.

1. The single-filter chain (``rl_config.useA85``)
-------------------------------------------------
A JPEG file *is* a DCT bitstream, and PDF's ``/DCTDecode`` filter stores exactly
that, so embedding a JPEG correctly is a byte copy: the page carries the
original scan, bit for bit, with no decode and no re-encode. A naive
implementation re-encodes, which is silently lossy, produces a larger file, and
looks identical on screen.

``rl_config.useA85`` **defaults to 1**, which wraps that stream in an ASCII85
transport layer and yields ``/Filter [/ASCII85Decode /DCTDecode]``. Undoing A85
recovers the JPEG exactly, so it is not a re-encode — but it means the *stored*
bytes are not the file's bytes, and the guarantee this product actually makes is
about the stored bytes. Measured on a 5430-byte source: ``useA85 = 1`` stores
6786 bytes; ``useA85 = 0`` stores 5430, byte for byte. So the chain is pinned to
exactly ``("/DCTDecode",)``.

**The value is read at ``drawImage()`` time** — not at ``Canvas()`` construction
and not at finalisation. Probed all three: setting it before the constructor
works, before the draw works, and before finalisation does **not**. So
:func:`_single_filter_chain` must span the draw loop, not merely the canvas
construction; a manager wrapping construction alone happens to work today and
would break the moment the loop moves out of it.

It is process-global mutable state, so the prior value is restored in a
``finally`` — including when the render raises. Nothing here sets it at import
time and nothing leaves it set: this product dispatches work across processes
elsewhere, and a global toggled for the life of a process is a defect even while
the tests pass.

2. Path in, not pixels in — and a *path string*, not a reader
--------------------------------------------------------------
The renderer offers the passthrough only when it still has the original file
bytes to hand. Built from an in-memory image it has only samples, so it
re-encodes. Hence: ``ImagePlacement.raster is None`` means *hand it the path*;
anything else means the op decided this input cannot be passed through and
already decoded it. **This module never converts, resizes, rotates or re-encodes
an image** — those are the op's decisions, taken before a placement exists.

**The passthrough must be handed the path as a plain string, never wrapped in
an ``ImageReader``, and that is a correctness requirement rather than a
preference.** ``drawImage`` de-duplicates image XObjects by a digest, and it
computes that digest from two different things depending on what it was handed:
from the *filename* for a path, but from ``ImageReader.getRGBData()`` — the
**decoded pixels** — for a reader. Two files whose pixels are identical but
whose compressed bytes are not therefore collide onto one XObject, and the
second page silently renders the first file's bytes.

That is not hypothetical. It was found on the operator's 108-page scan corpus,
where two scans of the same size but different SHA-256 dedupe into one XObject
and the byte-identity guarantee quietly fails for exactly one page — with the
filter chain still reading ``/DCTDecode`` and the item still reporting a
passthrough, which is the tool lying about its own path. Keying on the filename
keeps distinct operands distinct; a repeated operand still, correctly, shares
one XObject.

3. The renderer sniffs nothing
-------------------------------
Handed any file whose magic reads as JPEG, it stores the compressed bytes
unconditionally — baseline, progressive and CMYK alike (all three measured
byte-identical). Eligibility is therefore entirely the op's job. CMYK is passed
through on purpose: the renderer emits ``/DeviceCMYK`` *and* the Adobe
``/Decode [1 0 1 0 1 0 1 0]`` inversion array, so the page renders correctly and
the bytes survive.

4. One write, on this side of the boundary
-------------------------------------------
Both methods take a caller-supplied stream and finalise with
``getpdfdata()`` + a single ``out.write(...)``, rather than letting the renderer
flush the canvas itself. Two reasons, both structural: the write stays on this
side of the third-party boundary where it is visible, and this module then
contains no image-save call at all, so the audit grep for one over this file
returns nothing rather than returning a false positive on a canvas method.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import IO, Any, Final

from pdf_toolkit.adapters import AdapterProbe, package_probe
from pdf_toolkit.ports.compose import ComposeReport, ImagePlacement, TextLayout

__all__ = ["ADAPTER", "ReportlabComposeAdapter"]

_NAME: Final[str] = "reportlab"
_DISTRIBUTION: Final[str] = "reportlab"
_MODULE: Final[str] = "reportlab"

#: `"text-layer"` (PDF-14) is `watermark`'s own capability -- a single-page,
#: rotated, alpha-blended text render, distinct from `"text-layout"`'s
#: paginated-document shape (`render_text`/`_paginate`).
_CAPABILITIES: Final[frozenset[str]] = frozenset({"compose", "text-layout", "vector", "text-layer"})

#: The one form-feed-free page break in a text render, and the split token for
#: source lines. Spelled here so the two render paths cannot drift.
_LINE_BREAK: Final[str] = "\n"
_PAGE_BREAK: Final[str] = "\f"


@contextmanager
def _single_filter_chain() -> Iterator[None]:
    """Pin the stored-stream filter chain to exactly ``("/DCTDecode",)``.

    Process-global state, saved and restored — including on the exception path.
    The scope must enclose **every** ``drawImage`` call: the toggle is read
    there, not at canvas construction and not at finalisation.
    """
    from reportlab import rl_config  # type: ignore[import-untyped]

    previous = rl_config.useA85
    rl_config.useA85 = 0
    try:
        yield
    finally:
        rl_config.useA85 = previous


def _require_stream(out: object) -> IO[bytes]:
    """Refuse anything that is not a writable binary stream.

    A path handed to a renderer opens a second, untracked descriptor from inside
    third-party code — invisible to the source-level walk that holds the write
    chokepoint. Refusing it here is the half of that guarantee a static check
    cannot make.
    """
    if not callable(getattr(out, "write", None)):
        raise TypeError(
            f"compose renders into an open binary stream, never a path: got {type(out).__name__}"
        )
    return out  # type: ignore[return-value]


class ReportlabComposeAdapter:
    """The reportlab-backed ``ComposeEngine``."""

    kind: Final[str] = "python-package"

    @property
    def adapter_name(self) -> str:
        return _NAME

    def capabilities(self) -> frozenset[str]:
        return _CAPABILITIES

    def probe(self) -> AdapterProbe:
        return package_probe(_MODULE, _DISTRIBUTION)

    def compose_images(self, items: Sequence[ImagePlacement], *, out: IO[bytes]) -> ComposeReport:
        """Render one page per placement into *out*. See the module docstring."""
        stream = _require_stream(out)
        if not items:
            raise ValueError("compose_images needs at least one placement")

        from reportlab.lib.utils import ImageReader  # type: ignore[import-untyped]
        from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

        made = canvas.Canvas(stream, pagesize=items[0].page_size)
        with _single_filter_chain():
            for item in items:
                made.setPageSize(item.page_size)
                made.saveState()
                if item.clip_box is not None:
                    outline = made.beginPath()
                    outline.rect(*item.clip_box)
                    made.clipPath(outline, stroke=0, fill=0)
                # THE PASSTHROUGH IS THE *PATH*, NOT A READER -- see mechanic 2.
                handle = str(item.source) if item.raster is None else ImageReader(item.raster)
                x, y, width, height = item.draw_box
                made.drawImage(handle, x, y, width=width, height=height)
                made.restoreState()
                made.showPage()
            payload = made.getpdfdata()
        stream.write(payload)
        return ComposeReport(page_count=len(items))

    def render_text(self, text: str, *, layout: TextLayout, out: IO[bytes]) -> ComposeReport:
        """Render *text* into *out*, wrapped and paginated per *layout*."""
        stream = _require_stream(out)

        from reportlab.pdfgen import canvas

        pages = _paginate(text, layout)
        made = canvas.Canvas(stream, pagesize=layout.page_size)
        if layout.title is not None:
            made.setTitle(layout.title)
        top = layout.page_size[1] - layout.margin_pt - layout.size
        for page_lines in pages:
            made.setFont(layout.font, layout.size)
            for index, line in enumerate(page_lines):
                if line:
                    made.drawString(layout.margin_pt, top - index * layout.leading, line)
            made.showPage()
        payload = made.getpdfdata()
        stream.write(payload)
        return ComposeReport(page_count=len(pages))

    def render_text_layer(
        self,
        text: str,
        *,
        page_size: tuple[float, float],
        font: str,
        font_size: float,
        color: tuple[float, float, float],
        opacity: float,
        rotate_deg: float,
        out: IO[bytes],
    ) -> ComposeReport:
        """Render ONE page, *page_size* points, containing only *text*,
        centred and rotated about the page centre. See the port docstring.

        Order matters: ``translate`` to the page centre, THEN ``rotate`` (so
        the rotation pivots on the centre rather than the origin), THEN
        ``drawCentredString(0, 0, text)`` in that now-rotated, now-recentred
        local frame -- the standard reportlab "rotate about a point" idiom.
        """
        stream = _require_stream(out)

        from reportlab.pdfgen import canvas

        width, height = page_size
        made = canvas.Canvas(stream, pagesize=page_size)
        made.saveState()
        made.translate(width / 2.0, height / 2.0)
        made.rotate(rotate_deg)
        made.setFont(font, font_size)
        made.setFillColorRGB(*color)
        made.setFillAlpha(opacity)
        made.drawCentredString(0, 0, text)
        made.restoreState()
        made.showPage()
        payload = made.getpdfdata()
        stream.write(payload)
        return ComposeReport(page_count=1)


def _content_width(layout: TextLayout) -> float:
    return layout.page_size[0] - 2 * layout.margin_pt


def _paginate(text: str, layout: TextLayout) -> list[list[str]]:
    """Wrap *text* to the content width and cut it into pages.

    A form feed starts a new page, so each form-feed-delimited block is
    paginated on its own. Wrapping needs font metrics, which is the only reason
    this lives behind the engine at all; everything above it — the page size,
    the margin, the leading, how many lines fit — was resolved by the op.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth  # type: ignore[import-untyped]

    width = _content_width(layout)
    per_page = max(1, layout.lines_per_page)
    pages: list[list[str]] = []
    for block in text.split(_PAGE_BREAK):
        lines: list[str] = []
        for source_line in block.split(_LINE_BREAK):
            lines.extend(_wrap(source_line, layout, width, stringWidth))
        for start in range(0, len(lines), per_page):
            pages.append(lines[start : start + per_page])
        if not lines:  # pragma: no cover - a block is never empty after normalisation
            pages.append([])
    return pages


def _wrap(
    line: str,
    layout: TextLayout,
    width: float,
    measure: Any,
) -> list[str]:
    """Greedy word wrap, falling back to a character break for one long token.

    The character break always consumes at least one character, so a content box
    narrower than a single glyph terminates instead of looping forever.
    """
    if not line or measure(line, layout.font, layout.size) <= width:
        return [line]

    out: list[str] = []
    current = ""
    for word in line.split(" "):
        candidate = word if not current else f"{current} {word}"
        if measure(candidate, layout.font, layout.size) <= width:
            current = candidate
            continue
        if current:
            out.append(current)
            current = ""
        while measure(word, layout.font, layout.size) > width:
            cut = _longest_prefix(word, layout, width, measure)
            out.append(word[:cut])
            word = word[cut:]
        current = word
    out.append(current)
    return out


def _longest_prefix(word: str, layout: TextLayout, width: float, measure: Any) -> int:
    """The longest prefix of *word* that fits, never fewer than one character."""
    cut = 1
    while cut < len(word) and measure(word[: cut + 1], layout.font, layout.size) <= width:
        cut += 1
    return cut


ADAPTER: Final[ReportlabComposeAdapter] = ReportlabComposeAdapter()
