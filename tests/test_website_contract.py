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

import importlib.util
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from html import unescape as html_unescape
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
WEBSITE_ROOT: Final[Path] = REPO_ROOT / "website"
WEBSITE_SRC: Final[Path] = WEBSITE_ROOT / "src"
DIST_ROOT: Final[Path] = WEBSITE_ROOT / "dist"
GLOBAL_CSS: Final[Path] = WEBSITE_SRC / "styles" / "global.css"
TAILWIND_CONFIG: Final[Path] = WEBSITE_ROOT / "tailwind.config.mjs"
SECTIONS_TS: Final[Path] = WEBSITE_SRC / "lib" / "sections.ts"
#: PDF-93 AC3. The four independent hard-coded copies of the brand colour
#: (`R6.5`) -- none of which reads the `@theme` block that defines it.
LOGO_SVG: Final[Path] = WEBSITE_SRC / "assets" / "pdf-tooling-logo.svg"
FAVICON_SVG: Final[Path] = WEBSITE_ROOT / "public" / "favicon.svg"
#: PDF-93 AC4. The OG generator's Python module, loaded through the shipped
#: import idiom (`tests/test_brand_surfaces.py`'s `_load_og_generator()`),
#: never by hex grep -- a grep is blind to any operand whose comment omits
#: its hex (Objection 1, `TEXT`'s own trap).
OG_GENERATOR_SCRIPT: Final[Path] = WEBSITE_ROOT / "scripts" / "generate-og-image.py"

#: PDF-92 D7 / AR1. The frozen `id` sequence, declared INDEPENDENTLY of
#: `sections.ts` (D7's own instruction) so drift between the two is a
#: deliberate edit and never a silent one -- `PDF-97` retiring `features` to
#: `safety` reds this tuple by design unless it is edited in the same commit.
FROZEN_SECTION_IDS: Final[tuple[str, ...]] = (
    "features",
    "architecture",
    "verbs",
    "quickstart",
    "contract",
    "licensing",
)

#: `sections.ts`'s own declaration shape (`{ id: 'x', label: 'Y', short: 'Z' }`)
#: -- read as TEXT, never imported/executed: this test tree has no Node
#: runtime (D7 / AR1).
_SECTION_ID_DECL_PATTERN: Final[re.Pattern[str]] = re.compile(r"id:\s*['\"]([a-z0-9-]+)['\"]")
#: A literal `id="..."` attribute anywhere under `website/src` -- AR2's and
#: AR4's subject. Deliberately distinct from `_SECTION_ID_DECL_PATTERN`'s
#: `id: 'x'` shape, so `sections.ts`'s own declarations are never
#: double-counted as targets.
_COMPONENT_ID_ATTR_PATTERN: Final[re.Pattern[str]] = re.compile(r'id="([a-zA-Z0-9_-]+)"')
#: A literal `href="#..."` anywhere under any `.astro` file -- AR3's subject.
#: Deliberately blind to a template-built href (e.g. `href={`#${id}`}`, what
#: the rail and the `sm`+ row both render) -- E12 is the reason: a regex over
#: rendered markup cannot see a data-driven nav, and inferring one is exactly
#: the failure this item's arms replace with a declaration-reading test.
_LITERAL_HASH_HREF_PATTERN: Final[re.Pattern[str]] = re.compile(r'href="#([a-zA-Z0-9_-]+)"')

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
#:
#: PDF-93 re-derivation: `SHAPE_RGBA_LEGACY` (`Hero.astro:7`'s old
#: `rgba(244,63,94,0.10)`) is GONE -- the hero bloom now writes the modern
#: space-separated form the frontend proposal uses throughout `@theme`, and
#: `--shadow-lift`'s colour-bearing blur does too, both held at the shipped
#: 10% (D5) rather than the proposal's unbuilt 16%/28%. `SHAPE_RGB_MODERN`
#: replaces it in the frozen set -- this is the arm PDF-91 built and PDF-93
#: is the first item to actually exercise on a real, non-synthetic value.
LIVE_NOTATION_SHAPES: Final[frozenset[str]] = frozenset(
    {SHAPE_HEX6, SHAPE_RGB_MODERN, SHAPE_UTILITY_MODIFIER, SHAPE_UTILITY_BARE}
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
    """E10 trap 1, pinned against REAL content: the verb-chip line carries TWO
    accent occurrences on one physical line
    (`border-primary-500/10` and `bg-primary-500/10`) -- a line-based
    instrument would report 1 where the true count is 2.

    PDF-93 re-pin: the chip moved from `Verbs.astro:79` to `:87` when the
    section gained its chrome (eyebrow, hairline, `.card` treatment) -- the
    two-occurrence CLAIM is what this test protects, not the specific line,
    so the line is re-measured here rather than left stale."""
    verbs = WEBSITE_SRC / "components" / "Verbs.astro"
    occs_by_line: dict[int, int] = {}
    for occ in locate_accent_occurrences(verbs, verbs.read_text()):
        occs_by_line[occ.line] = occs_by_line.get(occ.line, 0) + 1
    two_hit_lines = [line for line, count in occs_by_line.items() if count == 2]
    assert two_hit_lines == [87], (
        f"expected exactly one two-occurrence line at :87, found {two_hit_lines} "
        f"(full census: {occs_by_line})"
    )


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
# PDF-93 AC3 -- the four hard-coded brand-colour copies agree, as an ARM.
# --------------------------------------------------------------------------- #

#: Per-file occurrence census (occurrences, never lines -- `E2`'s own idiom).
#: `pdf-tooling-logo.svg` carries ZERO copies of the dark plate after `D7`:
#: its plate went to `fill="none"`, permanently removing that copy rather
#: than moving it. `favicon.svg` keeps one copy, MOVED to the new value --
#: a favicon is composited against browser tab chrome this site does not
#: control, so the transparent-plate argument that pays for the logo does
#: not pay for it (D7).
ACCENT_HEX: Final[str] = "#fb7185"
DARK_PLATE_HEX: Final[str] = "#120c10"
EXPECTED_ACCENT_CENSUS: Final[dict[str, int]] = {
    "global.css": 1,
    "tailwind.config.mjs": 1,
    "pdf-tooling-logo.svg": 5,
    "favicon.svg": 2,
}
EXPECTED_DARK_PLATE_CENSUS: Final[dict[str, int]] = {
    "global.css": 1,
    "tailwind.config.mjs": 1,
    "favicon.svg": 1,
    "pdf-tooling-logo.svg": 0,
}


def test_a10_the_four_hardcoded_brand_colour_copies_agree() -> None:
    """AC3. The agreement is an ARM, not an intention (`R6.5`). Per-file
    occurrence census, same shape as `test_brand_surfaces.py`'s display-name
    census -- `.count()`, never a line count, so a minified or single-line
    copy still reports its true occurrence total.

    Control (run manually, never committed): revert exactly one file's copy
    to the old `#0f172a` -- this arm reds naming that one file and nothing
    else moves. Running it once per copy proves four independent reds, not
    one accidental one."""
    css_text = GLOBAL_CSS.read_text()
    tw_text = TAILWIND_CONFIG.read_text()
    logo_text = LOGO_SVG.read_text()
    favicon_text = FAVICON_SVG.read_text()

    accent_census = {
        "global.css": css_text.count(ACCENT_HEX),
        "tailwind.config.mjs": tw_text.count(ACCENT_HEX),
        "pdf-tooling-logo.svg": logo_text.count(ACCENT_HEX),
        "favicon.svg": favicon_text.count(ACCENT_HEX),
    }
    assert accent_census == EXPECTED_ACCENT_CENSUS, (
        f"accent hex census: {accent_census}, expected {EXPECTED_ACCENT_CENSUS}"
    )

    dark_plate_census = {
        "global.css": css_text.count(DARK_PLATE_HEX),
        "tailwind.config.mjs": tw_text.count(DARK_PLATE_HEX),
        "favicon.svg": favicon_text.count(DARK_PLATE_HEX),
        "pdf-tooling-logo.svg": logo_text.count(DARK_PLATE_HEX),
    }
    assert dark_plate_census == EXPECTED_DARK_PLATE_CENSUS, (
        f"dark-plate census: {dark_plate_census}, expected {EXPECTED_DARK_PLATE_CENSUS}"
    )


# --------------------------------------------------------------------------- #
# PDF-93 AC4 -- THE ONE F9 WOULD HAVE MISSED. The OG generator's eight
# operands, asserted BY NAME through the shipped import idiom, never by hex
# grep -- a hex census cannot see an operand whose own comment omits its hex
# (Objection 1: `TEXT`'s trap, reproduced here as the control).
# --------------------------------------------------------------------------- #

#: `PDF-93 D3`'s eight-row table, post-slice. Loaded from the module itself
#: (never re-typed as a second copy of the generator's own literals) would
#: defeat the point of this arm existing -- but the EXPECTED values below
#: are what the design document specifies, so a change to either side is a
#: deliberate edit to this test, never a silent pass.
EXPECTED_OG_OPERANDS: Final[dict[str, tuple[int, int, int]]] = {
    "BG_TOP": (18, 12, 16),  # surface-900  #120c10 -- MOVED
    "BG_BOTTOM": (136, 19, 55),  # primary-900  #881337 -- unmoved
    "ACCENT": (251, 113, 133),  # primary-400  #fb7185 -- frozen byte-for-byte
    "RIM": (190, 18, 60),  # primary-700  #be123c -- unmoved
    "TEXT": (251, 249, 250),  # surface-50  #fbf9fa -- MOVED (F9's own blind spot)
    "SUBTEXT": (251, 113, 133),  # primary-400  #fb7185 -- frozen byte-for-byte
    "RULE": (146, 68, 80),  # promoted from an inline literal -- MOVED
    "FOOTER": (198, 191, 196),  # surface-300  #c6bfc4 -- promoted -- MOVED
}


def _load_og_generator_module():
    """Loaded through the same idiom `tests/test_brand_surfaces.py`'s
    `_load_og_generator()` uses -- a fresh module object, never imported as a
    package, so re-running this in the same interpreter session as that
    module's own tests cannot cross-contaminate either one."""
    spec = importlib.util.spec_from_file_location("_og_generator_ac4", OG_GENERATOR_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a11_the_og_generators_eight_operands_are_asserted_by_name() -> None:
    """AC4. If `PDF-91`'s `P4` already asserted the operands by name this
    would be redundant -- it does not (grepped: no such arm exists anywhere
    under `tests/` before this commit), so this is the one instrument in the
    tree that reads the loaded module's actual tuples rather than grepping
    hex strings.

    Control: revert `TEXT` alone to `(248, 250, 252)` in a scratch copy.
    A hex-grep census stays GREEN (`#f8fafc` never appears in this file as a
    literal -- the operand is a tuple). A contrast check stays green too
    (18.49:1 vs 18.45:1, functionally identical). Only THIS arm reds, naming
    `TEXT`."""
    module = _load_og_generator_module()
    actual = {name: tuple(getattr(module, name)) for name in EXPECTED_OG_OPERANDS}
    assert actual == EXPECTED_OG_OPERANDS, (
        f"OG generator operand census: {actual}, expected {EXPECTED_OG_OPERANDS}"
    )


# --------------------------------------------------------------------------- #
# PDF-92 D7 -- the section register arms. Source-level only, like the rest of
# this tier: no Node, no `dist/`, no build step and therefore no skip path
# (AC7b). Named `AR1`-`AR4` because this module's own `A1`..`A9` series
# already exists and a second `A1` would mean two different things in one
# file (D7b).
# --------------------------------------------------------------------------- #


def declared_section_ids() -> tuple[str, ...]:
    """The `id` sequence `sections.ts` declares, in DOM order, read from its
    source TEXT -- never imported/executed (D7 / AR1)."""
    return tuple(_SECTION_ID_DECL_PATTERN.findall(SECTIONS_TS.read_text()))


#: AR4's one exemption. An id that is a landmark of a SINGLE document --
#: `main`, the skip link's target -- is legitimately declared once per page,
#: and became a cross-file duplicate the moment `PDF-94` added a second
#: route. Held to at-most-once per FILE instead of not-at-all.
PER_DOCUMENT_IDS: Final[frozenset[str]] = frozenset({"main"})


def _component_id_attrs() -> list[tuple[Path, str]]:
    """Every literal `id="..."` attribute under `website/src`, in file
    order -- AR2's and AR4's shared subject. Page-blind by construction: it
    scans `website/src` as one namespace (D7's `PDF-94` hand-off)."""
    hits: list[tuple[Path, str]] = []
    for path in _source_files():
        for m in _COMPONENT_ID_ATTR_PATTERN.finditer(path.read_text()):
            hits.append((path, m.group(1)))
    return hits


def test_ar1_the_section_register_declares_the_frozen_id_sequence() -> None:
    """AR1 (D7). `sections.ts`'s declared id sequence equals the tuple frozen
    above, independently of the shipping code. `PDF-97` retires `features` to
    `safety` by editing BOTH the tuple and the module in the same commit --
    this arm reds on that change by design (D7's third hand-off; isolating
    control C1, E13: remove one entry from `sections.ts`)."""
    declared = declared_section_ids()
    assert declared == FROZEN_SECTION_IDS, (
        f"sections.ts declares {declared}, frozen {FROZEN_SECTION_IDS} -- "
        "an intentional change to the register must edit this tuple in the "
        "same commit"
    )


def test_ar2_every_declared_section_id_has_a_target_under_website_src() -> None:
    """AR2 (D7). Every id `sections.ts` declares exists as a literal
    `id="..."` somewhere under `website/src` (isolating control C2, E13:
    remove `id="contract"` from `ExitCodes.astro`)."""
    all_ids = {i for _, i in _component_id_attrs()}
    missing = [i for i in declared_section_ids() if i not in all_ids]
    assert missing == [], f'declared section id(s) with no id="..." target: {missing}'


def test_ar3_every_literal_hash_href_resolves_to_an_id_in_source() -> None:
    """AR3 (D7). Every literal `href="#..."` under any `.astro` resolves to
    an `id="..."` somewhere under `website/src` -- catches a hand-typed dead
    anchor (isolating control C7, E13: a literal `href="#nope"` in
    `Footer.astro`). Deliberately page-blind and deliberately blind to a
    template-built href (E12) -- the register's own links are covered by
    AR1/AR2/AR4 reading the declaration instead."""
    all_ids = {i for _, i in _component_id_attrs()}
    offenders = []
    for path in _source_files():
        if path.suffix != ".astro":
            continue
        for m in _LITERAL_HASH_HREF_PATTERN.finditer(path.read_text()):
            if m.group(1) not in all_ids:
                offenders.append(f'{path.relative_to(REPO_ROOT)}: href="#{m.group(1)}"')
    assert offenders == [], 'literal anchor href with no id="..." target:\n' + "\n".join(offenders)


def test_ar4_no_id_is_declared_twice_under_website_src() -> None:
    """AR4 (D7). No literal `id="..."` is declared twice under `website/src`
    -- guards `PDF-95` moving `#quickstart` onto the hero block: adding the
    new id without removing the old one reds here (isolating control C8,
    E13: a second `id="licensing"` on another section, nothing removed).

    PER_DOCUMENT_IDS is the one exemption, and it is narrow. `main` is a
    landmark of ONE document: the skip link must resolve within the page it
    is on, so every page carries its own. It became a false positive the
    moment `PDF-94` added a second route, and the arm's original wording
    ("page-blind by construction") was a statement about a one-page site.
    The exempt ids are still held to at-most-once PER FILE, so the guard the
    arm exists for is unweakened -- a second `id="licensing"` anywhere, or a
    second `id="main"` in one document, still reds."""
    seen: dict[str, list[Path]] = {}
    per_file: dict[tuple[Path, str], int] = {}
    for path, i in _component_id_attrs():
        seen.setdefault(i, []).append(path)
        per_file[(path, i)] = per_file.get((path, i), 0) + 1

    dupes = {
        i: [str(p.relative_to(REPO_ROOT)) for p in paths]
        for i, paths in seen.items()
        if len(paths) > 1 and i not in PER_DOCUMENT_IDS
    }
    assert dupes == {}, f"id declared more than once under website/src: {dupes}"

    twice_in_one_file = {
        f"{p.relative_to(REPO_ROOT)}:{i}": n for (p, i), n in per_file.items() if n > 1
    }
    assert twice_in_one_file == {}, (
        f"id declared twice within a single document: {twice_in_one_file}"
    )


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


# --------------------------------------------------------------------------- #
# PDF-95 -- the fold, rebuilt around a real transcript. AC1 drives the actual
# `pdftooling` CLI (this module's one arm that is neither source- nor
# dist-tier in the sense above: it needs no `website/dist`, only the product
# itself, so it always runs); AC6/AC8/AC9/AC20 are source/dist-tier regex
# arms in the same style as the rest of this module. AC2-AC5, AC7 and AC16
# are the browser-measured criteria the spec's own validation ladder keeps
# off this module (`B-376`: no accessibility/browser instrument in this
# repo) -- driven by hand and reported in the implementation log instead.
# --------------------------------------------------------------------------- #

HERO_TRANSCRIPT_TS: Final[Path] = WEBSITE_SRC / "lib" / "hero-transcript.ts"
TERMINAL_ASTRO: Final[Path] = WEBSITE_SRC / "components" / "Terminal.astro"
HERO_ASTRO: Final[Path] = WEBSITE_SRC / "components" / "Hero.astro"
CLOSING_CTA_ASTRO: Final[Path] = WEBSITE_SRC / "components" / "ClosingCta.astro"

#: The two captured command strings and the exact captured `ls` failure --
#: transcribed here ONCE, from the shipped `hero-transcript.ts`, so a future
#: edit to that file's session is what has to change this constant too,
#: rather than two independent hand-typed copies silently drifting apart.
_HERO_MERGE_COMMAND: Final[str] = "pdftooling merge jul.pdf aug.pdf sep.pdf -O q3.pdf --dry-run"
_HERO_LS_COMMAND: Final[str] = "ls q3.pdf"
_HERO_LS_FAILURE: Final[str] = "ls: cannot access 'q3.pdf': No such file or directory"

_SESSION_ENTRY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\{\s*kind:\s*'([a-z]+)',\s*text:\s*(\"[^\"]*\"|'[^']*')\s*\}"
)


def _hero_session_entries() -> list[tuple[str, str]]:
    """`(kind, text)` pairs, in DOM order, read from `hero-transcript.ts`'s
    own source TEXT -- never imported/executed (this test tree has no Node
    runtime, the same constraint `declared_section_ids()` documents)."""
    text = HERO_TRANSCRIPT_TS.read_text()
    m = re.search(r"HERO_TRANSCRIPT_SESSION.*?\] as const;", text, re.DOTALL)
    assert m is not None, "HERO_TRANSCRIPT_SESSION array not found in hero-transcript.ts"
    return [(kind, quoted[1:-1]) for kind, quoted in _SESSION_ENTRY_PATTERN.findall(m.group(0))]


def _hero_merge_table_lines() -> list[str]:
    """The captured `merge --dry-run -o table` stdout ONLY -- the 'output'
    entries between the session's first 'command' and its first 'blank'.
    The session also carries a SECOND 'output' entry after that (the `ls`
    failure line, following the second 'command'), which is a different
    process's stderr and is asserted separately (`_HERO_LS_FAILURE`) --
    conflating the two would make this function's name a lie about what it
    returns."""
    entries = _hero_session_entries()
    lines: list[str] = []
    for kind, text in entries[1:]:  # entries[0] is the merge command itself
        if kind == "blank":
            break
        assert kind == "output", f"unexpected kind before the first blank: {kind}"
        lines.append(text)
    return lines


def _build_merge_dry_run_fixtures(tmp_path: Path, run_cli) -> None:
    """The exact construction method `hero-transcript.ts`'s own provenance
    header records: one one-page PDF via `create`, then `merge` of repeated
    `path:range` operands on that single page to reach the target page
    counts -- never hand-built, never inside a repository (`tmp_path` is
    pytest's own scratch tree)."""
    (tmp_path / "one.txt").write_text("one\n")
    created = run_cli("create", "one.txt", "-O", "one.pdf", "--page-size", "letter", cwd=tmp_path)
    assert created.returncode == 0, created.stderr

    def _merge_n(name: str, n: int) -> None:
        operands = ["one.pdf:1"] * n
        merged = run_cli("merge", *operands, "-O", name, "-f", cwd=tmp_path)
        assert merged.returncode == 0, merged.stderr

    _merge_n("jul.pdf", 12)
    _merge_n("aug.pdf", 9)
    _merge_n("sep.pdf", 11)


def test_pdf95_ac1_the_hero_transcript_table_is_reproducible_from_the_product(
    tmp_path: Path,
) -> None:
    """AC1. Re-run the invocation the panel shows, in a scratch directory
    outside every repository with fixtures built there (`tmp_path`), and
    diff its stdout against the table lines `hero-transcript.ts` ships:
    exit 0, zero differences. This is the one arm in this module that drives
    the real `pdftooling` CLI -- deliberately, because AC1's whole claim is
    that the shipped bytes are reproducible FROM THE PRODUCT, TODAY, by
    whoever is shipping them, not merely transcribed from an earlier drive.

    Reproduced independently at implementation time in a `mktemp -d`
    (outside `tmp_path` too): jul.pdf 9,983 bytes, aug.pdf 7,578 bytes,
    sep.pdf 9,182 bytes -- byte-identical across two independent scratch
    builds, which is what makes shipping these exact numbers (rather than
    the design dossier's `design/2026-09-20_hero-transcript-capture.txt`,
    captured against DIFFERENT fixtures with different byte sizes) the
    correct call: the dossier's own `bytes before` values are fixture-
    dependent and were never going to survive this arm's own re-run diff.

    Control: change one character in one shipped table line (e.g. `12
    pages selected` -> `12 pages`) in a scratch copy of `hero-transcript.ts`
    and re-run this test -- it reds naming the mismatched line. Driven and
    observed red before this note was written.
    """
    tests_dir = str(Path(__file__).resolve().parent)
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    from registry import run_cli  # noqa: E402  (path must be set up first)

    _build_merge_dry_run_fixtures(tmp_path, run_cli)
    result = run_cli(
        "merge",
        "jul.pdf",
        "aug.pdf",
        "sep.pdf",
        "-O",
        "q3.pdf",
        "--dry-run",
        "-o",
        "table",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    actual_lines = result.stdout.splitlines()
    expected_lines = _hero_merge_table_lines()
    assert actual_lines == expected_lines, (
        f"re-run stdout differs from the shipped transcript:\n"
        f"  actual:   {actual_lines}\n"
        f"  expected: {expected_lines}"
    )

    # `ls` is a coreutils binary, not a pdftooling verb -- drive it directly.
    ls_result = subprocess.run(
        ["ls", "q3.pdf"], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert ls_result.returncode != 0
    assert ls_result.stderr.strip() == _HERO_LS_FAILURE, (
        f"ls verdict differs: {ls_result.stderr.strip()!r} != {_HERO_LS_FAILURE!r}"
    )


def test_pdf95_ac6a_the_built_page_carries_both_commands_and_the_exact_ls_failure() -> None:
    """AC6(a). Astro HTML-escapes JSX-interpolated text (the `ls` failure's
    apostrophes become `&#39;` in the raw bytes) -- unescaped once here, the
    same normalisation a browser's own text content would apply, so this
    arm asserts what a visitor actually reads rather than the raw markup."""
    _require_dist()
    html = html_unescape((DIST_ROOT / "index.html").read_text())
    for needle in (_HERO_MERGE_COMMAND, _HERO_LS_COMMAND, _HERO_LS_FAILURE):
        assert needle in html, f"missing from dist/index.html: {needle!r}"


def test_pdf95_ac6b_the_two_commands_share_one_panel_with_no_section_boundary_between() -> None:
    """AC6(b), a regex-scoped proxy for "one common ancestor": between the
    merge invocation and the `ls` invocation in the built page there is no
    `<section` boundary -- both sit inside the one `Terminal` panel rather
    than being split across two page-level sections. Full DOM ancestry
    (`id="quickstart"` is an ancestor of the scroll container at every
    measured viewport) was verified directly with a driven Playwright
    measurement; see this item's report."""
    _require_dist()
    html = html_unescape((DIST_ROOT / "index.html").read_text())
    i1 = html.find(_HERO_MERGE_COMMAND)
    i2 = html.find(_HERO_LS_COMMAND, i1 if i1 != -1 else 0)
    assert i1 != -1 and i2 != -1 and i2 > i1, "both commands must appear, merge before ls"
    between = html[i1:i2]
    assert "<section" not in between, "a <section> boundary sits between the two commands"


def test_pdf95_ac6c_the_caption_carries_its_own_declared_two_fragment_signature() -> None:
    """AC6(c). The caption's text asserts against the signature
    `hero-transcript.ts` DECLARES (`CAPTION_FRAGMENTS`), never against a
    substring chosen at this test site."""
    _require_dist()
    ts_text = HERO_TRANSCRIPT_TS.read_text()
    dry_run_m = re.search(r"dryRun:\s*'([^']*)'", ts_text)
    nothing_m = re.search(r"nothingWritten:\s*'([^']*)'", ts_text)
    assert dry_run_m is not None and nothing_m is not None, (
        "CAPTION_FRAGMENTS not found in hero-transcript.ts"
    )
    html = html_unescape((DIST_ROOT / "index.html").read_text())
    assert dry_run_m.group(1) in html, f"caption fragment missing from dist: {dry_run_m.group(1)!r}"
    assert nothing_m.group(1) in html, f"caption fragment missing from dist: {nothing_m.group(1)!r}"


def test_pdf95_ac6d_the_dry_run_never_claims_what_the_output_does_not_say() -> None:
    """AC6(d). `merge --dry-run` announces nothing about being a dry run in
    its own `-o table` output (ruling R8) -- neither may the page. `would
    create` and `bytes written` occur zero times under `website/src` and in
    every file under `dist`."""
    offenders = []
    for path in _source_files():
        text = path.read_text()
        for needle in ("would create", "bytes written"):
            if needle in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {needle!r}")
    _require_dist()
    for path in sorted(DIST_ROOT.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(errors="ignore")
        for needle in ("would create", "bytes written"):
            if needle in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {needle!r}")
    assert offenders == [], "\n".join(offenders)


#: AC8. Anchor text must never state another section's position.
_DIRECTIONAL_WORDS: Final[tuple[str, ...]] = ("below", "above", "further down", "earlier", "later")
_HASH_ANCHOR_WITH_TEXT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'<a\s+href="#([a-zA-Z0-9_-]+)"[^>]*>(.*?)</a>', re.DOTALL
)


def test_pdf95_ac8_no_anchor_text_states_another_sections_position() -> None:
    """AC8. For every `<a href="#...">` under `website/src`, the link text
    contains none of the directional words, and every such href resolves to
    an id present somewhere under `website/src` (the latter restates AR3;
    kept local so this arm's failure message names the directional word by
    itself). Measured before this item: `QuickStart.astro:55` linked
    `#verbs` with the text "listed below" -- that file is deleted by this
    item, and the directionless replacement lives in `Hero.astro`."""
    all_ids = {i for _, i in _component_id_attrs()}
    offenders = []
    for path in _source_files():
        if path.suffix != ".astro":
            continue
        text = path.read_text()
        for href_id, inner in _HASH_ANCHOR_WITH_TEXT_PATTERN.findall(text):
            plain = re.sub(r"<[^>]+>", "", inner).lower()
            hit = next((w for w in _DIRECTIONAL_WORDS if w in plain), None)
            if hit is not None:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: href=#{href_id} contains {hit!r}")
            if href_id not in all_ids:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: href=#{href_id} has no id target")
    assert offenders == [], "\n".join(offenders)


def test_pdf95_ac9_quickstart_resolves_exactly_once_in_dist() -> None:
    """AC9, the occurrence-count half (the ancestor half is a driven
    Playwright measurement, reported in this item's log -- see AC6(b)'s
    docstring). `grep -o` idiom: occurrences, never lines -- `dist/index.html`
    is minified to a handful of very long lines."""
    _require_dist()
    html = (DIST_ROOT / "index.html").read_text()
    occurrences = len(re.findall(r'id="quickstart"', html))
    assert occurrences == 1, f'id="quickstart" occurs {occurrences} time(s) in dist/index.html'


#: AC20. `v?\d+\.\d+\.\d+` outside the one sanctioned provenance-header
#: comment in `hero-transcript.ts`.
_VERSION_SHAPE_PATTERN: Final[re.Pattern[str]] = re.compile(r"v?\d+\.\d+\.\d+")


def _leading_comment_block_end(text: str) -> int:
    """The character offset where the file's leading run of `//`-comment (and
    blank) lines ends -- the provenance header's own boundary. Everything
    from here on is code, and AC20 must see zero version-shaped matches in
    it."""
    lines = text.splitlines(keepends=True)
    offset = 0
    for line in lines:
        stripped = line.strip()
        if stripped == "" or stripped.startswith("//"):
            offset += len(line)
            continue
        break
    return offset


def test_pdf95_ac20_no_version_number_is_typed_in_the_fold_or_the_closing_band() -> None:
    """AC20. Zero matches for `v?\\d+\\.\\d+\\.\\d+` in `Hero.astro`,
    `ClosingCta.astro`, `Terminal.astro` and `hero-transcript.ts` OUTSIDE the
    provenance header comment (the one sanctioned place a version may be
    written -- it records a drive, never a claim)."""
    offenders = []
    for path in (HERO_ASTRO, CLOSING_CTA_ASTRO, TERMINAL_ASTRO):
        text = path.read_text()
        for m in _VERSION_SHAPE_PATTERN.finditer(text):
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {m.group(0)!r}")
    ts_text = HERO_TRANSCRIPT_TS.read_text()
    header_end = _leading_comment_block_end(ts_text)
    for m in _VERSION_SHAPE_PATTERN.finditer(ts_text[header_end:]):
        offenders.append(
            f"{HERO_TRANSCRIPT_TS.relative_to(REPO_ROOT)}: {m.group(0)!r} (outside header)"
        )
    assert offenders == [], "typed version number found:\n" + "\n".join(offenders)
