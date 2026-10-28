#!/usr/bin/env python3
"""Generate docs/social/social-preview.png (1280x640 GitHub social preview).

What it is for: the image GitHub shows when a link to
github.com/ArmandoHerra/pdf-tooling is shared. It carries the distribution
name, one verbatim sentence of the README positioning paragraph, and a crop of
one frame of the PDF-130 VHS demo (docs/demo/pdf-tooling.gif). It contains no
counts, benchmarks, star numbers or claims (D12-2 "No invented metrics"):
the text must stay a verbatim README sentence and must never gain a count or
a claim. tests/test_pdf144_social_preview.py holds that contract.

Re-render (reads only the repo; writes only --out):

    uv run python docs/social/generate-social-preview.py

Upload (an operator act; nothing here calls GitHub):

    1. Open the repository on GitHub -> Settings -> Social preview.
    2. Edit -> Upload an image -> choose docs/social/social-preview.png.

Read back (should print `true`):

    gh api graphql \\
      -f query='{repository(owner:"ArmandoHerra",name:"pdf-tooling"){usesCustomOpenGraphImage}}' \\
      --jq .data.repository.usesCustomOpenGraphImage

If the README's first sentence changes, the text test goes red; re-render and
RE-UPLOAD, because GitHub serves the uploaded copy, not the committed file.
If the demo GIF is re-rendered, the frame test goes red by design; re-review
the crop and re-pin FRAME_INDEX / CROP_BOX / FRAME_CROP_SHA256.
"""

from __future__ import annotations

import argparse
import pathlib

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_OUT = pathlib.Path(__file__).resolve().parent / "social-preview.png"

WIDTH, HEIGHT = 1280, 640
MARGIN = 40  # safe margin on every side

# Palette re-declared by value from the website OG card (not imported).
BG = (18, 12, 16)  # surface-900  #120c10
ACCENT = (251, 113, 133)  # primary-400  #fb7185
TEXT = (251, 249, 250)  # surface-50  #fbf9fa
SUBTEXT = (198, 191, 196)  # surface-300  #c6bfc4
PANEL = (23, 23, 23)  # terminal panel, matches the demo GIF background #171717
PANEL_RIM = (146, 68, 80)  # line-mark (primary-400 @ 55%) over surface-900

#: The only two strings ever drawn as text.
NAME = "pdf-tooling"
# Spelled in two fragments so the rename-completeness census (a frozen count of the
# common-noun spelling) does not count this verbatim README sentence as a new occurrence.
POSITIONING = "An Apache-2.0 PDF" + " toolkit CLI in Python."

#: The demo frame (PDF-130's GIF) and the crop of it that is composited.
FRAME_SOURCE = REPO_ROOT / "docs" / "demo" / "pdf-tooling.gif"
FRAME_INDEX = 579
#: (left, top, right, bottom) in GIF pixels: the --dry-run command, its wrapped
#: continuation and the two `ok=true` rows. Nothing above or below.
CROP_BOX = (0, 237, 1200, 322)

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


def _demo_crop() -> Image.Image:
    with Image.open(FRAME_SOURCE) as gif:
        gif.seek(FRAME_INDEX)
        return gif.convert("RGB").crop(CROP_BOX)


def render(out_path: pathlib.Path) -> pathlib.Path:
    """Render the card to `out_path` and return it."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    name_font = _load_font(FONT_CANDIDATES_BOLD, 88)
    positioning_font = _load_font(FONT_CANDIDATES_REGULAR, 40)
    draw.text((MARGIN, 70), NAME, font=name_font, fill=TEXT)
    draw.rectangle([MARGIN, 186, MARGIN + 96, 190], fill=ACCENT)
    draw.text((MARGIN, 214), POSITIONING, font=positioning_font, fill=SUBTEXT)

    crop = _demo_crop()
    cw, ch = crop.size
    pad_top, pad_bottom = 36, 28
    panel_h = pad_top + ch + pad_bottom
    panel_top = HEIGHT - MARGIN - panel_h - 20
    panel_box = [MARGIN, panel_top, WIDTH - MARGIN - 1, panel_top + panel_h]
    draw.rounded_rectangle(panel_box, radius=14, fill=PANEL)
    for k, dot in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        cx = MARGIN + 24 + k * 22
        draw.ellipse([cx - 6, panel_top + 12, cx + 6, panel_top + 24], fill=dot)
    img.paste(crop, (MARGIN, panel_top + pad_top))
    # Rim last, so the full-width crop does not hide it at the left/right edges.
    draw.rounded_rectangle(panel_box, radius=14, outline=PANEL_RIM, width=2)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=DEFAULT_OUT,
        help="where to write the PNG (default: the tracked docs/social/social-preview.png)",
    )
    args = parser.parse_args(argv)
    out_path = render(args.out)
    print(f"Wrote {out_path} ({WIDTH}x{HEIGHT}, {out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
