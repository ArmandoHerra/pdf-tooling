"""PDF-144 -- the committed 1280x640 social preview image and its source.

The image is PIXELS: nothing else in the repo can see it go stale. Arms:
limits (a), regeneration (b), drawn text (c), claims (d), the pinned demo frame
(e) and plain-blob storage (f). Each predicate arm has an arm-can-fail
companion. Renders only into `tmp_path`, never into the tracked artifact.
"""

from __future__ import annotations

import hashlib
import importlib.util
import random
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
GENERATOR = ROOT / "docs" / "social" / "generate-social-preview.py"
ARTIFACT = ROOT / "docs" / "social" / "social-preview.png"
README = ROOT / "README.md"
PYPROJECT = ROOT / "pyproject.toml"

MAX_BYTES = 1_000_000
CLAIM_PATTERN = (
    r"(?i)\b(stars?|downloads?|users?|fastest|faster|best|leading|#1|\d+\s*(%|x\b|k\b|\+))"
)

# Measured on the tracked docs/demo/pdf-tooling.gif (PDF-130 tape, re-rendered by PDF-153),
# zero tolerance.
PRE_DRYRUN_FRAME = 237  # cursor-off frame just before `--dry-run` is typed
PRE_LS_FRAME = 477  # cursor-on frame just before `ls` is typed
PROMPT_CELL = (16, 238, 28, 258)  # the band-3 prompt glyph, persists
FRAME_CROP_SHA256 = "26abb135ea0cc106e1f2ed8b40668ea7b718201bd5e88beecc69efeac745abb0"
PROMPT_CELL_MAX = (12, 21)  # (width, height): one glyph cell (PDF-144 frame criterion)


def _load_generator():
    spec = importlib.util.spec_from_file_location("_social_generator", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _violations(path: Path) -> list[str]:
    out: list[str] = []
    with Image.open(path) as im:
        if im.format != "PNG":
            out.append(f"format {im.format} != PNG")
        if im.size != (1280, 640):
            out.append(f"size {im.size} != (1280, 640)")
        if im.mode != "RGB":
            out.append(f"mode {im.mode} != RGB")
    if path.stat().st_size > MAX_BYTES:
        out.append(f"{path.stat().st_size} bytes > {MAX_BYTES}")
    return out


def test_social_preview_png_is_1280x640_rgb_png_under_the_github_limit() -> None:
    assert ARTIFACT.exists(), f"missing {ARTIFACT}"
    assert _violations(ARTIFACT) == []


def test_social_preview_limit_arm_can_fail(tmp_path: Path) -> None:
    short = tmp_path / "short.png"
    Image.new("RGB", (1280, 630)).save(short)
    assert _violations(short)
    rng = random.Random(144)
    noise = tmp_path / "noise.png"
    Image.frombytes("RGB", (1280, 640), rng.randbytes(1280 * 640 * 3)).save(noise)
    assert noise.stat().st_size > MAX_BYTES
    assert _violations(noise)


def test_social_preview_agrees_with_its_generator(tmp_path: Path) -> None:
    module = _load_generator()
    for group in (module.FONT_CANDIDATES_BOLD, module.FONT_CANDIDATES_REGULAR):
        if not any(Path(c).exists() for c in group):
            pytest.skip(f"social-preview fonts absent: {group}")
    fresh_path = module.render(tmp_path / "sp.png")
    with Image.open(fresh_path) as fresh, Image.open(ARTIFACT) as tracked:
        assert fresh.size == tracked.size
        assert fresh.convert("RGB").tobytes() == tracked.convert("RGB").tobytes(), (
            "the committed social preview no longer matches its generator. Re-run:\n"
            "    uv run python docs/social/generate-social-preview.py\n"
            "commit the result, and re-upload it in repository Settings."
        )


def _is_readme_sentence(s: str) -> bool:
    lines = README.read_text(encoding="utf-8").splitlines()
    idx = lines.index("# pdf-tooling")
    rest = lines[idx + 1 :]
    first = next(i for i, ln in enumerate(rest) if ln.strip())
    para: list[str] = []
    for ln in rest[first:]:
        if not ln.strip():
            break
        para.append(ln.strip())
    sentences = re.split(r"(?<=\.)\s+", " ".join(para))
    return s in sentences


def _record_drawn_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    module = _load_generator()
    recorded: list[str] = []
    original = ImageDraw.ImageDraw.text

    def wrapper(self, *args, **kwargs):
        text = args[1] if len(args) > 1 else kwargs["text"]
        recorded.append(text)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", wrapper)
    module.render(tmp_path / "rec.png")
    return recorded


def test_social_preview_draws_exactly_name_and_readme_positioning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_generator()
    recorded = _record_drawn_text(monkeypatch, tmp_path)
    assert set(recorded) == {module.NAME, module.POSITIONING}
    name = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["name"]
    assert module.NAME == name
    assert _is_readme_sentence(module.POSITIONING), (
        f"POSITIONING {module.POSITIONING!r} is not a verbatim README positioning sentence"
    )


def test_social_preview_positioning_arm_can_fail() -> None:
    assert not _is_readme_sentence("The fastest PDF CLI in Python.")
    assert not _is_readme_sentence("An Apache-2.0 PDF")


def _claim_violations(strings: list[str]) -> list[str]:
    return [s for s in strings if re.search(CLAIM_PATTERN, s)]


def test_social_preview_draws_no_count_or_claim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_generator()
    recorded = _record_drawn_text(monkeypatch, tmp_path)
    digits = [s for s in recorded if s != module.POSITIONING and re.search(r"\d", s)]
    assert digits == [], f"digit in drawn text: {digits}"
    assert _claim_violations(recorded) == [], f"claim in drawn text: {_claim_violations(recorded)}"


def test_social_preview_claim_arm_can_fail() -> None:
    assert _claim_violations(["pdf-tooling", "★ 42 stars"])
    assert _claim_violations(["10x faster"])


def _frame(gif: Image.Image, index: int) -> Image.Image:
    gif.seek(index)
    return gif.convert("RGB")


def _fence_violations(
    crop_box: tuple[int, int, int, int],
    prompt_cell: tuple[int, int, int, int] = PROMPT_CELL,
) -> list[str]:
    """Pixel oracle on the GIF's own frame history (exact equality, no OCR)."""
    module = _load_generator()
    left, top, right, bottom = crop_box
    out: list[str] = []
    with Image.open(module.FRAME_SOURCE) as gif:
        last = _frame(gif, module.FRAME_INDEX)
        width, height = last.size
        bg = last.getpixel((width - 1, height - 1))
        pre_dry = _frame(gif, PRE_DRYRUN_FRAME)
        pre_dry_next = _frame(gif, PRE_DRYRUN_FRAME + 1)
        pre_ls = _frame(gif, PRE_LS_FRAME)
        pre_ls_next = _frame(gif, PRE_LS_FRAME + 1)

    # Upper fence.
    pl, pt, pr, pb = prompt_cell
    cell_w, cell_h = pr - pl, pb - pt
    if cell_w <= 0 or cell_h <= 0:
        out.append(f"upper fence: PROMPT_CELL is {cell_w}x{cell_h} and has no area")
    elif cell_w > PROMPT_CELL_MAX[0] or cell_h > PROMPT_CELL_MAX[1]:
        out.append(f"upper fence: PROMPT_CELL is {cell_w}x{cell_h}, over the 12x21 glyph-cell cap")
    above = (0, 0, width, top)
    if top > 0 and pre_dry.crop(above).tobytes() != last.crop(above).tobytes():
        out.append(
            "upper fence: rows above the crop differ between PRE_DRYRUN_FRAME and FRAME_INDEX"
        )
    if not (left <= pl and top <= pt and pr <= right and pb <= bottom):
        out.append("upper fence: PROMPT_CELL not inside the crop")
    else:
        crop = pre_dry.crop(crop_box)
        stray = 0
        for y in range(crop.height):
            for x in range(crop.width):
                gx, gy = left + x, top + y
                if pl <= gx < pr and pt <= gy < pb:
                    continue
                if crop.getpixel((x, y)) != bg:
                    stray += 1
        if stray:
            out.append(
                f"upper fence: {stray} non-BG crop pixels outside PROMPT_CELL at PRE_DRYRUN_FRAME"
            )
        if pre_dry.crop(prompt_cell).tobytes() != last.crop(prompt_cell).tobytes():
            out.append("upper fence: PROMPT_CELL differs from FRAME_INDEX")
    if pre_dry_next.crop(crop_box).tobytes() == pre_dry.crop(crop_box).tobytes():
        out.append("upper fence: frame PRE_DRYRUN_FRAME+1 does not change the crop")

    # Lower fence.
    if pre_ls.crop(crop_box).tobytes() != last.crop(crop_box).tobytes():
        out.append("lower fence: crop at PRE_LS_FRAME != crop at FRAME_INDEX")
    below = (0, bottom, width, height)
    if bottom < height:
        if pre_ls.crop(below).tobytes() == last.crop(below).tobytes():
            out.append("lower fence: region below the crop is already final at PRE_LS_FRAME")
        if pre_ls_next.crop(below).tobytes() == pre_ls.crop(below).tobytes():
            out.append("lower fence: frame PRE_LS_FRAME+1 does not change the region below")
    return out


def test_social_preview_frame_is_pinned_to_the_pdf130_demo() -> None:
    module = _load_generator()
    assert module.FRAME_SOURCE.resolve() == (ROOT / "docs" / "demo" / "pdf-tooling.gif").resolve()
    with Image.open(module.FRAME_SOURCE) as gif:
        assert 0 <= module.FRAME_INDEX < gif.n_frames
        left, top, right, bottom = module.CROP_BOX
        assert 0 <= left < right <= gif.width and 0 <= top < bottom <= gif.height
        digest = hashlib.sha256(
            _frame(gif, module.FRAME_INDEX).crop(module.CROP_BOX).tobytes()
        ).hexdigest()
    problems = _fence_violations(module.CROP_BOX)
    if digest != FRAME_CROP_SHA256:
        problems.append(
            "SHA pin: the demo frame crop changed (GIF, FRAME_INDEX or CROP_BOX). Redo the "
            "visual review, re-check the fences and re-record the pinned constants."
        )
    assert problems == []


def test_social_preview_frame_fence_arm_can_fail() -> None:
    left, top, right, bottom = _load_generator().CROP_BOX
    upper = _fence_violations((left, top - 21, right, bottom))
    assert any(v.startswith("upper fence") for v in upper), upper
    lower = _fence_violations((left, top, right, bottom + 21))
    assert any(v.startswith("lower fence") for v in lower), lower


def test_social_preview_prompt_cell_cap_arm_can_fail() -> None:
    crop = _load_generator().CROP_BOX
    pl, pt, _, _ = PROMPT_CELL
    wide = (pl, pt, pl + 28, pt + 21)
    tall = (pl, pt, pl + 12, pt + 22)
    edge = (pl, pt, pl + 12, pt + 21)
    for cell in (wide, tall):
        assert any("over the 12x21 glyph-cell cap" in v for v in _fence_violations(crop, cell))
    assert not any("glyph-cell cap" in v for v in _fence_violations(crop, edge))


def test_social_preview_is_a_plain_blob() -> None:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    res = subprocess.run(
        ["git", "check-attr", "filter", "--", "docs/social/social-preview.png"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        pytest.skip("not a git checkout")
    assert "lfs" not in res.stdout, res.stdout
    assert ARTIFACT.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
