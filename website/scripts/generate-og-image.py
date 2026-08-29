#!/usr/bin/env python3
"""Generate website/public/og-image.png (1200x630 Open Graph preview).

Renders locally with Pillow -- no external network calls, no downloaded
fonts/logos. Re-run any time the tagline changes:

    uv run python website/scripts/generate-og-image.py

Pillow is already a declared runtime dependency (PLAN.md §7.1), so no
separate install step is needed.
"""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1200, 630
BG_TOP = (15, 23, 42)       # surface-900  #0f172a
BG_BOTTOM = (136, 19, 55)   # primary-900  #881337
ACCENT = (251, 113, 133)    # primary-400  #fb7185
RIM = (190, 18, 60)         # primary-700  #be123c
TEXT = (248, 250, 252)      # surface-50
SUBTEXT = (251, 113, 133)   # primary-400  #fb7185

FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT_CANDIDATES_REGULAR = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if pathlib.Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _vertical_gradient(width: int, height: int, top: tuple, bottom: tuple) -> Image.Image:
    base = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(base)
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return base


def _draw_document(draw: "ImageDraw.ImageDraw", cx: int, cy: int, r: float) -> None:
    """Frame + folded-corner document, echoing website/src/assets/pdf-toolkit-logo.svg."""
    f = r * 1.58
    draw.rounded_rectangle(
        [cx - f, cy - f, cx + f, cy + f],
        radius=int(r * 0.62), outline=ACCENT, width=max(2, int(r * 0.11)),
    )
    w, h, fold = r * 0.78, r * 1.10, r * 0.34          # page half-width, half-height, fold size
    left, right, top, bot = cx - w, cx + w, cy - h, cy + h
    lw = max(3, int(r * 0.10))
    draw.line(
        [(left, top), (right - fold, top), (right, top + fold), (right, bot),
         (left, bot), (left, top)],
        fill=RIM, width=lw, joint="curve",
    )
    draw.line([(right - fold, top), (right - fold, top + fold), (right, top + fold)],
              fill=RIM, width=lw, joint="curve")
    for k, frac in enumerate((0.55, 0.35)):            # two text rules inside the page
        y = cy + r * (0.10 + 0.30 * k)
        draw.line([(left + r * 0.22, y), (left + r * 0.22 + 2 * w * frac, y)],
                  fill=ACCENT, width=lw)


def main() -> None:
    img = _vertical_gradient(WIDTH, HEIGHT, BG_TOP, BG_BOTTOM)
    draw = ImageDraw.Draw(img)

    draw.rectangle([24, 24, WIDTH - 24, HEIGHT - 24], outline=(120, 30, 60), width=2)
    _draw_document(draw, cx=178, cy=HEIGHT // 2, r=88)

    title_font = _load_font(FONT_CANDIDATES_BOLD, 92)
    tagline_font = _load_font(FONT_CANDIDATES_REGULAR, 38)
    footer_font = _load_font(FONT_CANDIDATES_REGULAR, 24)

    text_x = 350
    draw.text((text_x, 190), "pdf-toolkit", font=title_font, fill=TEXT)
    draw.text((text_x, 310), "Every common PDF chore. One safe CLI.", font=tagline_font, fill=SUBTEXT)
    draw.text((text_x, 358), "No copyleft underneath.", font=tagline_font, fill=SUBTEXT)
    draw.text(
        (text_x, 440),
        "pypdf · pdfium · pikepdf · reportlab — github.com/ArmandoHerra/pdf-toolkit",
        font=footer_font,
        fill=(203, 213, 225),
    )

    out_path = pathlib.Path(__file__).resolve().parent.parent / "public" / "og-image.png"
    img.save(out_path, "PNG")
    print(f"Wrote {out_path} ({WIDTH}x{HEIGHT})")


if __name__ == "__main__":
    main()
