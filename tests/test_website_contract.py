"""tests/test_website_contract.py -- PDF-91.

Mechanizes AC10 (the accent-text ban and the tint budget), AC11 (zero
JavaScript) and AC12 (the external-host closure, amended) against the real
`website/` tree, replacing the instrument that enforced them before this
commit -- a grep inside a planning document nobody runs
(`PDF-16:671-673`), which is why two live tint violations
(`Hero.astro:7`, `Verbs.astro:79`) shipped with a green suite since launch.

TWO TIERS, and the split is forced by one fact: `website/dist` is gitignored
and is built by neither `make ci` nor the `test` job. An arm that reads
`dist` therefore cannot run in eight matrix legs, and a SKIP IS NOT A PASS --
this repository's own rule (`scripts/assert_skips.py`'s header), and the
exact defect class this module exists to avoid repeating.

  * SOURCE TIER (A1, A2, A2b, A3, A4, A5, A9) -- always runs, never skips,
    reads only `website/src` and `website/tailwind.config.mjs`. No build
    required.
  * DIST TIER (A6, A7, A8) -- runs wherever `website/dist/index.html`
    exists. Outside a built site, the vacuity guard below decides what
    happens, and "it skipped" must never be readable as "it passed":

      - `website/dist/index.html` exists            -> the arms RUN.
      - it does not, and `PDF_TOOLING_WEBSITE_BUILT` -> `pytest.fail(...)`,
        is set                                          never `pytest.skip`.
      - neither of the above                         -> `pytest.skip`, the
                                                          NAMED class below.

`make website` sets `PDF_TOOLING_WEBSITE_BUILT=1` AFTER `npm run build`, so
in the one job whose whole purpose is to check the built site, the dist arms
cannot pass by skipping -- `scripts/assert_skips.py`'s own idiom
transplanted ("Make the unverifiable case FAIL, not SKIP").

Neither tier names `convert` or `ocr` in any node id, so this module joins
no population `tests/test_engine_gating_census.py` is watching (Design D6 /
AC14) -- it costs that census exactly 0.

`X-964` (`C7`, `D4a`): the tint arm (`A2`) is a two-stage CLASSIFIER, not a
regex over violations -- LOCATE every construct that names the accent, then
READ its alpha into exactly one of four states (fill / within-budget /
over-budget / UNREADABLE); there is no fifth state that means "nothing
matched". `A2b` freezes the SET of colour-notation shapes actually in use
under `website/src`, so a notation the classifier has not been taught
arrives as a named red instead of a silent miss -- the exact defect class
the inherited `design/2026-09-20_website-preflight.sh:33` regex embodies
(it reads 3 of the 12 notations this cycle actually writes).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
WEBSITE_ROOT: Final[Path] = REPO_ROOT / "website"
WEBSITE_SRC: Final[Path] = WEBSITE_ROOT / "src"
DIST_ROOT: Final[Path] = WEBSITE_ROOT / "dist"
GLOBAL_CSS: Final[Path] = WEBSITE_SRC / "styles" / "global.css"
TAILWIND_CONFIG: Final[Path] = WEBSITE_ROOT / "tailwind.config.mjs"

#: AC10, `P1`. `global.css`'s own rewritten comment (PDF-91 `R7`): accent
#: TEXT is `primary-400` on every ground; `primary-500` is a fill and never
#: a text colour.
BANNED_ACCENT_TEXT: Final[re.Pattern[str]] = re.compile(r"text-primary-500")

#: AC11 source half, `P6`.
SCRIPT_TAG: Final[re.Pattern[str]] = re.compile(r"<script")

#: A9 / E10 trap 3. The NARROW, hyphenated-or-underscored (or no-separator)
#: legacy needle only. The space-separated common-noun spelling is a
#: REGISTERED spelling (`tests/test_rename_completeness.py`'s
#: `EXPECTED_SPELLINGS`, `Layout.astro:12`) that must keep existing -- the
#: broader `pdf[-_ ]?toolkit` family regex matches it too and reds on a
#: compliant tree (driven, E10). Deliberately built by CONCATENATION rather
#: than spelled as one contiguous literal below: a bare, no-separator
#: spelling of this pattern is itself one of `test_rename_completeness.py`'s
#: watched spellings, and writing it out whole here would self-match that
#: OTHER census -- the identical reason `global.css`'s own comment gives for
#: never spelling a Tailwind class name.
_LEGACY_BARE: Final[str] = "pdf" + "toolkit"
LEGACY_NEEDLE: Final[str] = r"pdf[-_]toolkit|" + _LEGACY_BARE

#: AC12 amended (Design D4). `www.w3.org` is an SVG `xmlns` namespace token
#: Astro inlines into a `data:` URI in `index.html` -- never a fetched
#: resource -- and is exempt WHEREVER it appears, not only inside `.svg`
#: files (E10 trap 2: the original wording predates that inlining).
ALLOWED_HOSTS: Final[frozenset[str]] = frozenset({"armandoherra.github.io", "github.com"})
EXEMPT_HOST: Final[str] = "www.w3.org"
HOST_PATTERN: Final[re.Pattern[str]] = re.compile(r"https?://([a-zA-Z0-9.-]+)")

#: AC4/AC5. The documented base-path foot-gun: the base concatenated
#: directly onto a bare `og-image` reference with no separating slash.
BASE_PATH: Final[str] = "/pdf-tooling/"
MALFORMED_BASE: Final[re.Pattern[str]] = re.compile(r'(?:href|src)="/pdf-tooling[^/"]')
BASE_FOOT_GUN: Final[str] = "/pdf-toolingog-image"

#: The exact reason `scripts/assert_skips.py`'s `website-not-built` class
#: matches (Design D5) -- defined ONCE, here, and read by
#: `tests/test_assert_skips.py` so the two files cannot come to disagree
#: while both look green.
WEBSITE_NOT_BUILT_REASON: Final[str] = "website not built; run `make website`"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )


def _source_files() -> list[Path]:
    """Every `.astro` / `.css` / `.ts` file under `website/src`, sorted for a
    stable report order."""
    return sorted(
        p for p in WEBSITE_SRC.rglob("*") if p.is_file() and p.suffix in {".astro", ".css", ".ts"}
    )


def _dist_html_files() -> list[Path]:
    return sorted(DIST_ROOT.rglob("*.html"))


def _dist_markup_files() -> list[Path]:
    """`.html` AND `.svg` -- AC12 amended scans both (Design D4)."""
    return sorted(p for p in DIST_ROOT.rglob("*") if p.suffix in (".html", ".svg"))


def website_is_built() -> bool:
    return (DIST_ROOT / "index.html").is_file()


def _require_dist() -> None:
    """Call at the START of every DIST-TIER arm (Design D4's vacuity guard).

    Never `pytest.skip` when the unbuilt case is the one this job exists to
    make unverifiable-and-therefore-FAILING -- see the module docstring's
    three-way table.
    """
    if website_is_built():
        return
    if os.environ.get("PDF_TOOLING_WEBSITE_BUILT"):
        pytest.fail(
            "PDF_TOOLING_WEBSITE_BUILT is set but website/dist/index.html does not exist -- "
            "the one job that exists to verify the built site must not be able to pass by "
            "skipping the arms that verify it. Run `npm run build` in website/ first."
        )
    pytest.skip(WEBSITE_NOT_BUILT_REASON)


# --------------------------------------------------------------------------- #
# D4a -- the notation-aware tint classifier (X-964).
#
# A regex over VIOLATIONS is exactly the defect this replaces: the inherited
# preflight sweep (`design/2026-09-20_website-preflight.sh:33`) reads the
# legacy comma `rgba()` spelling and the `primary-500/NN` utility modifier
# and NOTHING ELSE -- 3 of 12 planted violations (C7, E13), because it was
# written against the only two spellings ever live in this tree.
#
# This is a CLASSIFIER instead, in two stages (D4a):
#   1. LOCATE every construct that NAMES the accent -- the `primary-500` /
#      `primary.500` token in any position, the hex `#f43f5e` with or
#      without a trailing alpha pair, or the decimal triple `244 63 94`
#      under any run of commas, spaces or underscores.
#   2. READ the alpha into exactly one of four states: fill (no alpha --
#      legal), within-budget (<=10%), over-budget (>10%, RED), or
#      UNREADABLE (an alpha-shaped token no extractor could read -- RED,
#      never a silent pass; `scripts/assert_skips.py`'s "make the
#      unverifiable case FAIL, not SKIP" applied to colour).
# --------------------------------------------------------------------------- #

#: The seven notations `D4a`'s table derives (rows 1, 2, 4, 5, 6, 7, 8 --
#: 2a/5a are variants of 2/5 and row 3 is a context note, not a new shape),
#: plus two FILL-only shapes the census also tracks even though neither
#: carries an alpha to violate a budget: a bare 6-digit hex, and a bare
#: Tailwind/CSS token with no modifier.
SHAPE_RGBA_LEGACY: Final[str] = "rgba-legacy-comma"  # D4a row 1 -- live, Hero.astro:7
SHAPE_RGB_MODERN: Final[str] = "rgb-modern-space"  # D4a row 2 / 2a -- PDF-93 SS B.2/D.6
SHAPE_RGB_UNDERSCORE: Final[str] = "rgb-modern-underscore"  # D4a row 4 -- Tailwind arbitrary value
SHAPE_COLOR_MIX: Final[str] = "color-mix"  # D4a row 5 / 5a
SHAPE_UTILITY_MODIFIER: Final[str] = "utility-modifier"  # D4a row 6 -- live, Verbs.astro:79
SHAPE_THEME_FUNCTION: Final[str] = "theme-function"  # D4a row 7
SHAPE_HEX8: Final[str] = "hex8"  # D4a row 8 -- what Tailwind v4.3.3 EMITS
SHAPE_HEX6: Final[str] = "hex6"  # fill-only, e.g. the `@theme` declaration itself
SHAPE_UTILITY_BARE: Final[str] = "utility-bare"  # fill-only, e.g. `bg-primary-500`

#: A2b. The LIVE set of notation shapes under `website/src` today --
#: re-derived at implementation HEAD against THIS tree, never transcribed
#: from the spec's own illustrative drive (which was measured against a
#: different tree state; see this item's report). A shape outside this set
#: is a NINTH notation arriving, and it reds naming the file and the line.
LIVE_NOTATION_SHAPES: Final[frozenset[str]] = frozenset(
    {SHAPE_HEX6, SHAPE_RGBA_LEGACY, SHAPE_UTILITY_MODIFIER, SHAPE_UTILITY_BARE}
)

#: R1 (E13, driven). Other CSS Level-4/5 colour-space functions this arm has
#: not been taught to read. `oklch(63.2% 0.23 20.1 / 0.3)` is ~`#f43f5e` at
#: 30% and names NONE of the three things `A2`'s locator can read (the
#: token, the hex, the triple) -- it is INVISIBLE to `A2` by construction, so
#: this denylist is what makes its arrival LOUD instead of silent,
#: regardless of whether the specific occurrence happens to be the accent.
#: `color-mix` and `theme` are excluded on purpose: they are TAUGHT
#: notations (rows 5 and 7), not residue.
UNTAUGHT_COLOR_FUNCTION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(oklch|oklab|lab|lch|hsla?|hwb|color)\(", re.IGNORECASE
)

_HEX: Final[str] = "f43f5e"
_HEX_PATTERN: Final[re.Pattern[str]] = re.compile(r"#" + _HEX + r"([0-9a-f]{2})?\b", re.IGNORECASE)
#: The decimal triple, under ANY run of commas, spaces or underscores
#: between operands (D4a's locator wording, verbatim).
_TRIPLE: Final[str] = r"244[\s,_]+63[\s,_]+94"
_TRIPLE_WRAPPED: Final[re.Pattern[str]] = re.compile(r"\s*" + _TRIPLE + r"\s*")
_RGBA_FUNC: Final[re.Pattern[str]] = re.compile(r"rgba?\(", re.IGNORECASE)
_COLOR_MIX_FUNC: Final[re.Pattern[str]] = re.compile(r"color-mix\(", re.IGNORECASE)
_THEME_FUNC: Final[re.Pattern[str]] = re.compile(r"theme\(", re.IGNORECASE)
_UTILITY_PREFIXES: Final[tuple[str, ...]] = (
    "bg",
    "border",
    "text",
    "ring",
    "shadow",
    "from",
    "via",
    "to",
    "divide",
    "outline",
    "accent",
)
_UTILITY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:" + "|".join(_UTILITY_PREFIXES) + r")-primary-500(?:/(\d+))?\b"
)
#: A number with an optional `%` suffix, anchored at the START of the text it
#: is matched against (`.match`, not `.search`) -- so `calc(...)` and any
#: other non-numeric alpha token fails to match rather than matching some
#: unrelated digit deeper in the string.
_ALPHA_NUMBER: Final[re.Pattern[str]] = re.compile(r"([0-9]*\.?[0-9]+)(%)?")
#: 8-bit alpha is QUANTISED (D4a). Tailwind emits a compliant `/10` as
#: `#f43f5e1a` -- `0x1a = 26 = 10.196%` -- so an exact `> 10.0` percentage
#: test reds a COMPLIANT build. Compare at the representation's own
#: resolution instead: `round(0.10 * 255) == 26` passes; `27` (`10.588%`)
#: reds. This constant is for row 8 (hex8) ONLY -- every other notation's
#: alpha is authored as an exact decimal or percentage and is compared
#: directly against the 10.0 float threshold.
HEX8_BUDGET_MAX: Final[int] = round(0.10 * 255)


def _state_for(alpha_pct: float) -> str:
    return "over-budget" if alpha_pct > 10.0 + 1e-9 else "within-budget"


def _references_accent(text: str) -> bool:
    return bool(
        re.search(r"primary-500|primary\.500|--color-primary-500|#" + _HEX, text, re.IGNORECASE)
        or re.search(_TRIPLE, text)
    )


def _matching_paren(text: str, open_index: int) -> int | None:
    """Index of the `)` matching the `(` at *open_index*, or `None` if the
    construct is unterminated. Handles ARBITRARY nesting depth
    (`calc(var(--a) * 2)` inside `rgb(...)` is two levels) -- a fixed-depth
    regex cannot, and that nested shape is exactly the UNREADABLE plant's."""
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return None


def _classify_rgb_args(args: str) -> tuple[str, str, float | None] | None:
    """*args* is the text between `rgb(`/`rgba(` and its matching `)`.
    Returns `(shape, state, alpha_pct)`, or `None` if the accent triple is
    not present at all (the call names some OTHER colour, e.g.
    `primary-400`'s `251 113 133` -- outside this rule, N4)."""
    m = _TRIPLE_WRAPPED.match(args)
    if m is None:
        return None
    triple_text = args[: m.end()]
    if "_" in triple_text:
        shape = SHAPE_RGB_UNDERSCORE
    elif "," in triple_text:
        shape = SHAPE_RGBA_LEGACY
    else:
        shape = SHAPE_RGB_MODERN

    rest = args[m.end() :].lstrip()
    if not rest or rest[0] == ")":
        return shape, "fill", None

    sep = re.match(r"[\s_]*([,/])[\s_]*", rest)
    if sep is None:
        return shape, "unreadable", None
    after = rest[sep.end() :]
    num = _ALPHA_NUMBER.match(after)
    if num is None:
        return shape, "unreadable", None
    value = float(num.group(1))
    alpha_pct = value if num.group(2) else value * 100.0
    return shape, _state_for(alpha_pct), alpha_pct


def _classify_color_mix_args(args: str) -> tuple[str, str, float | None] | None:
    """`color-mix(in <space>, <c1> <p1>?, <c2> <p2>?)`. Returns `None` if the
    accent is not referenced at all."""
    if not _references_accent(args):
        return None
    direct = re.search(
        r"(?:var\(--color-primary-500\)|--color-primary-500|primary-500|primary\.500|#"
        + _HEX
        + r"(?:[0-9a-f]{2})?|"
        + _TRIPLE
        + r")\s*([0-9.]+)%",
        args,
        re.IGNORECASE,
    )
    if direct:
        alpha_pct = float(direct.group(1))
        return SHAPE_COLOR_MIX, _state_for(alpha_pct), alpha_pct
    # D4a row 5a: the INVERTED spelling -- the accent's own share is implied
    # as the complement of `transparent`'s stated percentage. A reader that
    # took the first percentage it found would read 84, not 16 (E13 plant P9).
    inverted = re.search(r"transparent\s*([0-9.]+)%", args, re.IGNORECASE)
    if inverted:
        alpha_pct = 100.0 - float(inverted.group(1))
        return SHAPE_COLOR_MIX, _state_for(alpha_pct), alpha_pct
    return SHAPE_COLOR_MIX, "unreadable", None


def _classify_theme_args(args: str) -> tuple[str, str, float | None] | None:
    """`theme(colors.primary.500 / 40%)`."""
    m = re.search(r"colors\.primary\.500\s*/\s*([0-9.]+)(%)?", args, re.IGNORECASE)
    if m is None:
        if _references_accent(args):
            return SHAPE_THEME_FUNCTION, "unreadable", None
        return None
    value = float(m.group(1))
    alpha_pct = value  # the row's only live example is percent-form; a bare
    # number here would already BE the percentage under this function's own
    # grammar, so no further scaling is applied.
    return SHAPE_THEME_FUNCTION, _state_for(alpha_pct), alpha_pct


def _classify_utility_match(m: re.Match[str]) -> tuple[str, str, float | None]:
    digits = m.group(1)
    if digits is None:
        return SHAPE_UTILITY_BARE, "fill", None
    alpha_pct = float(digits)
    return SHAPE_UTILITY_MODIFIER, _state_for(alpha_pct), alpha_pct


def _classify_hex_match(m: re.Match[str]) -> tuple[str, str, float | None]:
    pair = m.group(1)
    if pair is None:
        return SHAPE_HEX6, "fill", None
    alpha_int = int(pair, 16)
    state = "within-budget" if alpha_int <= HEX8_BUDGET_MAX else "over-budget"
    return SHAPE_HEX8, state, (alpha_int / 255.0) * 100.0


@dataclass(frozen=True, slots=True)
class AccentOccurrence:
    path: Path
    line: int
    shape: str
    raw: str
    state: str  # "fill" | "within-budget" | "over-budget" | "unreadable"
    alpha_pct: float | None

    def report(self) -> str:
        pct = f"{self.alpha_pct:.3f}%" if self.alpha_pct is not None else "n/a"
        rel = self.path.relative_to(REPO_ROOT)
        return f"{rel}:{self.line} [{self.shape}] {self.raw!r} {self.state} {pct}"


def locate_accent_occurrences(path: Path, text: str) -> list[AccentOccurrence]:
    """The full two-stage classifier (D4a), run over one file's text."""
    occurrences: list[AccentOccurrence] = []
    claimed: list[tuple[int, int]] = []

    def _claim(start: int, end: int) -> bool:
        for s, e in claimed:
            if start < e and s < end:
                return False
        claimed.append((start, end))
        return True

    def _line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    for fm in _RGBA_FUNC.finditer(text):
        open_idx = fm.end() - 1
        close_idx = _matching_paren(text, open_idx)
        if close_idx is None:
            continue
        result = _classify_rgb_args(text[open_idx + 1 : close_idx])
        if result is None or not _claim(fm.start(), close_idx + 1):
            continue
        shape, state, alpha = result
        occurrences.append(
            AccentOccurrence(
                path, _line_of(fm.start()), shape, text[fm.start() : close_idx + 1], state, alpha
            )
        )

    for fm in _COLOR_MIX_FUNC.finditer(text):
        open_idx = fm.end() - 1
        close_idx = _matching_paren(text, open_idx)
        if close_idx is None:
            continue
        result = _classify_color_mix_args(text[open_idx + 1 : close_idx])
        if result is None or not _claim(fm.start(), close_idx + 1):
            continue
        shape, state, alpha = result
        occurrences.append(
            AccentOccurrence(
                path, _line_of(fm.start()), shape, text[fm.start() : close_idx + 1], state, alpha
            )
        )

    for fm in _THEME_FUNC.finditer(text):
        open_idx = fm.end() - 1
        close_idx = _matching_paren(text, open_idx)
        if close_idx is None:
            continue
        result = _classify_theme_args(text[open_idx + 1 : close_idx])
        if result is None or not _claim(fm.start(), close_idx + 1):
            continue
        shape, state, alpha = result
        occurrences.append(
            AccentOccurrence(
                path, _line_of(fm.start()), shape, text[fm.start() : close_idx + 1], state, alpha
            )
        )

    for m in _UTILITY_PATTERN.finditer(text):
        if not _claim(m.start(), m.end()):
            continue
        shape, state, alpha = _classify_utility_match(m)
        occurrences.append(
            AccentOccurrence(path, _line_of(m.start()), shape, m.group(0), state, alpha)
        )

    # Hex is claimed LAST: a hex literal inside an already-claimed rgb()/
    # color-mix()/theme() call (not a shape any live plant produces, but
    # principled to guard) must not be double-counted.
    for m in _HEX_PATTERN.finditer(text):
        if not _claim(m.start(), m.end()):
            continue
        shape, state, alpha = _classify_hex_match(m)
        occurrences.append(
            AccentOccurrence(path, _line_of(m.start()), shape, m.group(0), state, alpha)
        )

    return occurrences


def all_source_occurrences(paths: list[Path] | None = None) -> list[AccentOccurrence]:
    occurrences: list[AccentOccurrence] = []
    for path in paths if paths is not None else _source_files():
        occurrences.extend(locate_accent_occurrences(path, path.read_text()))
    return occurrences


def tint_over_budget_census(paths: list[Path] | None = None) -> dict[str, int]:
    """The per-file OVER-BUDGET-OR-UNREADABLE count, by OCCURRENCE (A4) --
    never a line count (E10 trap 1). `{}` after PDF-91's fix; was
    `{"Hero.astro": 1, "Verbs.astro": 1}` before it (E7/E8, driven)."""
    census: dict[str, int] = {}
    for occ in all_source_occurrences(paths):
        if occ.state in ("over-budget", "unreadable"):
            census[occ.path.name] = census.get(occ.path.name, 0) + 1
    return census


# --------------------------------------------------------------------------- #
# SOURCE TIER -- always runs, never skips, no build required.
# --------------------------------------------------------------------------- #


def test_a1_no_banned_accent_text_anywhere_under_website_src() -> None:
    """AC10, `P1`. `primary-500` is never a text colour."""
    offenders = []
    for path in _source_files():
        count = len(BANNED_ACCENT_TEXT.findall(path.read_text()))
        if count:
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {count} occurrence(s)")
    assert offenders == [], "banned accent-text token `text-primary-500` found:\n" + "\n".join(
        offenders
    )


def test_a2_every_decorative_accent_tint_is_at_most_ten_percent() -> None:
    """AC10, `R5`/`global.css:17`, `X-964`. Notation-aware (D4a): the census
    is empty -- no OVER-BUDGET and no UNREADABLE occurrence -- after this
    item's fix, across every one of the seven notations, not only the two
    the inherited sweep could read."""
    census = tint_over_budget_census()
    assert census == {}, f"tint over the 10% budget (or unreadable): {census}"


def test_a2b_the_notation_census_holds_the_frozen_set() -> None:
    """D4a / `X-964`. The set of colour-notation SHAPES the classifier
    actually produces over `website/src` today must equal the frozen set --
    a shape outside it means a notation arrived that nobody taught the arm,
    and it reds by NAME rather than passing silently."""
    shapes = {occ.shape for occ in all_source_occurrences()}
    assert shapes == LIVE_NOTATION_SHAPES, (
        f"measured {sorted(shapes)}, frozen {sorted(LIVE_NOTATION_SHAPES)} -- "
        f"new: {sorted(shapes - LIVE_NOTATION_SHAPES)}, "
        f"missing: {sorted(LIVE_NOTATION_SHAPES - shapes)}"
    )


def test_a2b_untaught_colour_functions_are_refused_outright() -> None:
    """D4a / R1 (E13, driven). `oklch()` and its siblings name NONE of the
    three things `A2`'s locator can read (the accent token, the hex, the RGB
    triple) and are therefore INVISIBLE to `A2` by construction -- this arm
    is the refusal that makes their arrival loud instead of silent,
    independent of whether the specific occurrence happens to be the accent."""
    offenders = []
    for path in _source_files():
        for m in UNTAUGHT_COLOR_FUNCTION_PATTERN.finditer(path.read_text()):
            offenders.append(f"{path.relative_to(REPO_ROOT)}: new notation: {m.group(1)}")
    assert offenders == [], "\n".join(offenders)


def test_a3_the_accent_hex_values_are_byte_identical_in_both_copies() -> None:
    """`P3`/DECISION decision 5. `#fb7185` and `#f43f5e` must agree between
    `global.css`'s `@theme` and `tailwind.config.mjs`'s mirror -- this item
    touches neither, and this arm is the control that it did not drift."""
    css_text = GLOBAL_CSS.read_text()
    tw_text = TAILWIND_CONFIG.read_text()
    for hexval in ("#fb7185", "#f43f5e"):
        assert hexval in css_text, f"{hexval} missing from global.css's @theme block"
        assert hexval in tw_text, f"{hexval} missing from tailwind.config.mjs's mirror"


def test_a4_the_over_budget_census_counts_occurrences_never_lines() -> None:
    """E10 trap 1, pinned against REAL content: `Verbs.astro:79` carries TWO
    accent occurrences on one physical line
    (`border-primary-500/10` and `bg-primary-500/10`) -- a line-based
    instrument would report 1 where the true count is 2."""
    verbs = WEBSITE_SRC / "components" / "Verbs.astro"
    on_line_79 = [
        occ for occ in locate_accent_occurrences(verbs, verbs.read_text()) if occ.line == 79
    ]
    assert len(on_line_79) == 2, on_line_79


def test_a4_synthetic_two_hits_one_line_count_as_two() -> None:
    """The same lesson, isolated from the tree's own content: two planted
    utility-modifier occurrences on one line must count as 2, not 1."""
    text = "before border-primary-500/40 middle bg-primary-500/99 after"
    occs = locate_accent_occurrences(Path("scratch.astro"), text)
    assert len(occs) == 2, occs


def test_a5_zero_script_tags_under_website_src() -> None:
    """AC11 source half, `P6`."""
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _source_files()
        if SCRIPT_TAG.search(path.read_text())
    ]
    assert offenders == [], f"<script under website/src: {offenders}"


def test_a9_no_hyphenated_or_underscored_legacy_needle_under_website() -> None:
    """E10 trap 3. The NARROW needle only -- the space-separated common-noun
    spelling `LEGACY_NEEDLE` deliberately excludes is a REGISTERED spelling
    (`tests/test_rename_completeness.py`) and must keep matching nothing
    here; that module owns the thirteen-spelling and five-occurrence
    common-noun questions, this arm does not re-derive them (Design D4)."""
    proc = _git("grep", "--untracked", "-Ion", "-E", LEGACY_NEEDLE, "--", "website/")
    assert proc.returncode in (0, 1), f"git grep failed rc={proc.returncode}: {proc.stderr}"
    hits = [line for line in proc.stdout.splitlines() if line]
    assert hits == [], f"legacy needle under website/: {hits}"


# --------------------------------------------------------------------------- #
# DIST TIER -- runs wherever `website/dist/index.html` exists.
# --------------------------------------------------------------------------- #


def test_a6_zero_js_files_and_zero_script_tags_in_dist() -> None:
    """AC11 dist half."""
    _require_dist()
    js_files = [str(p.relative_to(REPO_ROOT)) for p in DIST_ROOT.rglob("*.js")]
    assert js_files == [], f".js file(s) in dist: {js_files}"
    script_pages = [
        str(p.relative_to(REPO_ROOT))
        for p in _dist_html_files()
        if SCRIPT_TAG.search(p.read_text())
    ]
    assert script_pages == [], f"<script> in dist page(s): {script_pages}"


def test_a7_no_page_references_a_host_outside_the_closure() -> None:
    """AC12 amended (Design D4). Every `.html` and `.svg` in `dist`;
    `www.w3.org` exempt WHEREVER it appears."""
    _require_dist()
    offenders: dict[str, list[str]] = {}
    for path in _dist_markup_files():
        hosts = {h for h in HOST_PATTERN.findall(path.read_text()) if h != EXEMPT_HOST}
        unexpected = sorted(hosts - ALLOWED_HOSTS)
        if unexpected:
            offenders[str(path.relative_to(REPO_ROOT))] = unexpected
    assert offenders == {}, f"page(s) referencing an unexpected host: {offenders}"


def test_a8_base_path_integrity() -> None:
    """AC4/AC5. Base path present by OCCURRENCE count (E10 trap 1 -- a
    compliant build reads occurrences in the DOUBLE DIGITS across about six
    minified lines, and a line count would read far fewer and RED ON A
    COMPLIANT BUILD); no malformed concatenation; the documented og-image
    foot-gun absent."""
    _require_dist()
    text = (DIST_ROOT / "index.html").read_text()
    occurrences = len(re.findall(re.escape(BASE_PATH), text))
    assert occurrences >= 3, f"base path {BASE_PATH!r} appears only {occurrences} time(s)"
    assert MALFORMED_BASE.search(text) is None, "malformed base-path concatenation in index.html"
    assert BASE_FOOT_GUN not in text, "the documented base-path foot-gun is live"


# --------------------------------------------------------------------------- #
# The vacuity guard itself, exercised directly (AC11 item 11's "Vacuity"
# control) -- monkeypatched, so this arm runs unconditionally rather than
# depending on the ambient build state of whoever runs the suite.
# --------------------------------------------------------------------------- #


def test_the_vacuity_guard_fails_rather_than_skips_when_the_built_flag_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11 item 11's Vacuity control, first half: `PDF_TOOLING_WEBSITE_BUILT`
    is set but `dist` is absent -- the arm must FAIL, never SKIP. This is
    `scripts/assert_skips.py`'s own idiom transplanted ("Make the
    unverifiable case FAIL, not SKIP"): the one job that exists to check the
    built site must never be able to pass this arm by skipping it."""
    monkeypatch.setattr(sys.modules[__name__], "website_is_built", lambda: False)
    monkeypatch.setenv("PDF_TOOLING_WEBSITE_BUILT", "1")
    with pytest.raises(pytest.fail.Exception):
        _require_dist()


def test_the_vacuity_guard_skips_with_the_named_reason_when_unbuilt_and_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11 item 11's Vacuity control, second half: outside `make website`
    the identical unbuilt condition SKIPS, with the EXACT reason
    `scripts/assert_skips.py`'s `website-not-built` class matches -- reported
    verbatim, per Design D12."""
    monkeypatch.setattr(sys.modules[__name__], "website_is_built", lambda: False)
    monkeypatch.delenv("PDF_TOOLING_WEBSITE_BUILT", raising=False)
    with pytest.raises(pytest.skip.Exception) as excinfo:
        _require_dist()
    assert str(excinfo.value) == WEBSITE_NOT_BUILT_REASON
