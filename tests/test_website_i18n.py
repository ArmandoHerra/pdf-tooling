"""The bilingual contract.

The site ships two locales off ONE set of components (`website/src/lib/
i18n.ts` states why a duplicated `components/es/` tree was rejected). That
design has exactly one failure mode worth a test, and it is silent:

    someone adds an English sentence to a component's `EN` table, does not
    add its Spanish counterpart, and `pick()` -- which merges `Partial<T>`
    over the English base precisely so a missing key still RENDERS -- ships
    an English paragraph in the middle of the Spanish page.

Nothing about that outcome is visibly broken. The page builds, the layout
holds, every link works, and the only reader who finds it is one who does
not read English. So the arms below are structural rather than visual.

TWO TIERS, the same split `tests/test_website_contract.py` uses and for the
same reason: `website/dist` is gitignored and absent in most CI legs.

  * SOURCE TIER -- reads `website/src` only. Always runs. Owns the key-
    parity arm, which is the one that actually catches the failure above.
  * DIST TIER -- guarded by `_require_dist`, the same never-skip-silently
    idiom: it RUNS wherever `website/dist/index.html` exists and FAILS
    (never skips) when the built-site flag is set but `dist` is not there.

What is deliberately NOT asserted here: that any particular sentence is
good Spanish. A test cannot read; that is review's job. What a test can do
is prove no sentence was forgotten, and that the two pages declare
themselves correctly to a machine.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
WEBSITE_ROOT: Final[Path] = REPO_ROOT / "website"
WEBSITE_SRC: Final[Path] = WEBSITE_ROOT / "src"
DIST_ROOT: Final[Path] = WEBSITE_ROOT / "dist"
PAGES_ROOT: Final[Path] = WEBSITE_SRC / "pages"
I18N_TS: Final[Path] = WEBSITE_SRC / "lib" / "i18n.ts"
LAYOUT_ASTRO: Final[Path] = WEBSITE_SRC / "layouts" / "Layout.astro"

#: The locale segment every Spanish route lives under.
ES_SEGMENT: Final[str] = "es"


def _source_files() -> list[Path]:
    """Every `.astro` / `.ts` file under `website/src`, sorted."""
    return sorted(
        p for p in WEBSITE_SRC.rglob("*") if p.is_file() and p.suffix in {".astro", ".ts"}
    )


def _require_dist() -> None:
    """Call at the START of every DIST-TIER arm.

    A skip is not a pass: in the one job whose purpose is to check the
    built site, an absent `dist` must RED, not quietly succeed.
    """
    if (DIST_ROOT / "index.html").is_file():
        return
    if os.environ.get("PDF_TOOLING_WEBSITE_BUILT"):
        pytest.fail(
            "PDF_TOOLING_WEBSITE_BUILT is set but website/dist/index.html does not exist -- "
            "the built-site arms cannot run and must not skip"
        )
    pytest.skip("website/dist is absent; build the site to run the dist-tier i18n arms")


# --------------------------------------------------------------------------- #
# SOURCE TIER
# --------------------------------------------------------------------------- #

#: Matches the opening of a locale copy table. The call shape is fixed by
#: `i18n.ts`'s own signature, so this is a parse of a declared interface,
#: not a guess at a formatting convention.
PICK_OPEN: Final[re.Pattern[str]] = re.compile(r"pick\(\s*Astro\.url\s*,\s*\{")

#: A top-level key inside one of those object literals. Both the bare and
#: the quoted spellings occur (`'meta get'` needs quotes), so both are
#: recognised; the captured group is the key itself either way.
KEY_AT_DEPTH_ONE: Final[re.Pattern[str]] = re.compile(
    r"""(?:^|[\{,])\s*(?:(?P<bare>[A-Za-z_$][\w$]*)|'(?P<quoted>[^']+)')\s*:"""
)


def _match_brace(text: str, open_index: int) -> int:
    """Index just past the `}` that closes the `{` at `open_index`.

    A character scanner rather than a regex: the copy tables contain
    braces inside template literals (`${fam}`) and apostrophes inside
    Spanish prose, and a regex that ignores string state mis-pairs both.
    Quotes, escapes and template literals are tracked, and `//` comments
    are blanked by `_strip_line_comments` before any of this runs -- see
    the note there for the real failure that taught this parser to do so.
    """
    depth = 0
    i = open_index
    quote: str | None = None
    while i < len(text):
        ch = text[i]
        if quote is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise AssertionError(f"unbalanced brace starting at offset {open_index}")


def _strip_line_comments(text: str) -> str:
    """Blank out `//` comments, preserving offsets and newlines.

    Found by this module's own first run, not reasoned about in advance: a
    `//` comment inside `Hero.astro`'s Spanish table quoted this file's
    path in backticks, the scanner read that backtick as the start of a
    template literal, and every key after it vanished -- reporting a
    MISSING translation that was right there. A parser that can be put
    into the wrong state by a comment is a parser that reports fiction,
    so comments stop existing before any brace or quote is counted.
    """
    out = list(text)
    i = 0
    quote: str | None = None
    while i < len(text):
        ch = text[i]
        if quote is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            i += 1
            continue
        if ch == "/" and i + 1 < len(text) and text[i + 1] == "/":
            while i < len(text) and text[i] != "\n":
                out[i] = " "
                i += 1
            continue
        i += 1
    return "".join(out)


def _top_level_keys(literal: str) -> list[str]:
    """The keys declared directly inside one object literal.

    Nested objects are stripped first so a key belonging to a nested
    literal is never counted as a sibling of the keys around it.
    """
    literal = _strip_line_comments(literal)
    out: list[str] = []
    depth = 0
    i = 0
    quote: str | None = None
    flat_chars: list[str] = []
    while i < len(literal):
        ch = literal[i]
        if quote is not None:
            if ch == "\\":
                flat_chars.append(" ")
                i += 2
                continue
            if ch == quote:
                quote = None
            flat_chars.append(ch if depth <= 1 else " ")
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            flat_chars.append(ch if depth <= 1 else " ")
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        flat_chars.append(ch if depth <= 1 else " ")
        i += 1
    flat = "".join(flat_chars)
    for m in KEY_AT_DEPTH_ONE.finditer(flat):
        out.append(m.group("bare") or m.group("quoted"))
    return out


def _pick_tables() -> list[tuple[Path, int, list[str], list[str]]]:
    """Every `pick(Astro.url, {EN}, {ES})` call site in the tree.

    Returns `(path, line, english_keys, spanish_keys)` per call.
    """
    found: list[tuple[Path, int, list[str], list[str]]] = []
    for path in _source_files():
        text = _strip_line_comments(path.read_text())
        for m in PICK_OPEN.finditer(text):
            en_open = text.index("{", m.start())
            en_end = _match_brace(text, en_open)
            rest = text[en_end:]
            comma = rest.index(",")
            es_open = en_end + rest.index("{", comma)
            es_end = _match_brace(text, es_open)
            found.append(
                (
                    path,
                    text.count("\n", 0, m.start()) + 1,
                    _top_level_keys(text[en_open:en_end]),
                    _top_level_keys(text[es_open:es_end]),
                )
            )
    return found


def test_every_pick_call_site_declares_both_locales() -> None:
    """The parser sees real call sites, so the parity arm below cannot pass
    vacuously by finding nothing to check.

    The floor is deliberately a FLOOR, not an equality: adding a component
    should not red this arm, only a refactor that removes the whole
    mechanism should.
    """
    tables = _pick_tables()
    assert len(tables) >= 12, (
        f"only {len(tables)} pick(Astro.url, ...) call site(s) found -- the key-parity arm "
        "would be near-vacuous. Did the locale mechanism change shape?"
    )
    for path, line, en_keys, es_keys in tables:
        assert en_keys, f"{path.relative_to(REPO_ROOT)}:{line}: English copy table is empty"
        assert es_keys, f"{path.relative_to(REPO_ROOT)}:{line}: Spanish copy table is empty"


def test_the_two_copy_tables_agree_key_for_key() -> None:
    """THE ARM. Every English string has a Spanish counterpart.

    `pick()` merges the Spanish slice over the English base, so a missing
    key does not crash, does not warn, and does not look wrong in a
    screenshot -- it renders the English sentence on the Spanish page.
    This is the only place that failure is visible.

    A key that is genuinely identical in both languages (a punctuation
    fragment, a proper name) must still be RESTATED in the Spanish table
    rather than inherited, so "identical on purpose" and "forgotten" stop
    looking the same from here. `Hero.astro`'s `installEnd` carries that
    reasoning at its own declaration.

    DRIVEN RED: delete any one key from any Spanish table -> this names
    the file, the line, and the missing key.
    """
    drift: list[str] = []
    for path, line, en_keys, es_keys in _pick_tables():
        missing = [k for k in en_keys if k not in es_keys]
        extra = [k for k in es_keys if k not in en_keys]
        if missing or extra:
            rel = path.relative_to(REPO_ROOT)
            drift.append(f"{rel}:{line}: missing in ES {missing}, unknown in ES {extra}")
    assert drift == [], (
        "locale copy tables drifted -- an English string with no Spanish counterpart "
        "renders as English on the Spanish page:\n  " + "\n  ".join(drift)
    )


def test_every_english_route_has_a_spanish_counterpart() -> None:
    """A route added to `pages/` without its `pages/es/` twin is reachable
    only in English, and the language switch on it points at a 404.

    Driven red: `git mv website/src/pages/es/licensing.astro /tmp/` ->
    this names `licensing.astro`.
    """
    english = {
        p.relative_to(PAGES_ROOT)
        for p in PAGES_ROOT.rglob("*.astro")
        if ES_SEGMENT not in p.relative_to(PAGES_ROOT).parts
    }
    spanish = {
        p.relative_to(PAGES_ROOT / ES_SEGMENT) for p in (PAGES_ROOT / ES_SEGMENT).rglob("*.astro")
    }
    orphans = sorted(str(p) for p in english - spanish)
    strays = sorted(str(p) for p in spanish - english)
    assert orphans == [], f"English route(s) with no Spanish counterpart: {orphans}"
    assert strays == [], f"Spanish route(s) with no English original: {strays}"


def test_the_document_language_is_derived_never_hard_coded() -> None:
    """`Layout.astro` must not carry a literal `lang="en"`.

    This is the defect a rendered check finds last: Spanish prose inside a
    document that declares itself English is invisible on screen and wrong
    to every screen reader and translation tool that reads the attribute.
    """
    layout = LAYOUT_ASTRO.read_text()
    assert "langOf(Astro.url)" in layout, "Layout.astro no longer derives its locale from the URL"

    # Scoped to the MARKUP half, past the frontmatter fence. Found on this
    # module's first run: the component's own comment explaining why the
    # attribute must not be hard-coded quotes the very thing it forbids,
    # and a whole-file grep read that explanation as the offence.
    _, _, markup = layout.partition("\n---\n")
    assert markup, "Layout.astro has no frontmatter fence -- cannot scope this arm to its markup"
    assert re.search(r'<html[^>]*\blang="(?:en|es)"', markup) is None, (
        "Layout.astro hard-codes a document language in its markup -- it must derive it "
        "from the URL"
    )


def test_the_locale_segment_is_matched_whole_never_as_a_substring() -> None:
    """`langOf` splits the path and compares segments.

    A substring test (`pathname.includes('/es')`) would read a future
    `/estimates/` route as Spanish. The mechanism is pinned, not just its
    current result, because that route does not exist yet and a rendered
    check therefore cannot see the bug.

    `i18n_module_source` is named that way ON PURPOSE and must not be
    renamed back to `text`. `tests/test_secret_leak_sweeps.py`'s B-073
    sweep flags `assert <slash-bearing literal> in <sink-named variable>`
    as an operand pinned inside captured output, and `text` is one of the
    sink names it matches -- so this arm, which greps a TypeScript module
    checked into the repo and touches no process output at all, counted
    against a frozen ceiling it has nothing to do with. The sweep's own
    docstring calls itself "deliberately over-inclusive" with "a few
    false positives a human triages"; this is that triage. Raising the
    ceiling instead would have made it assert there are eighty such
    assertions in this tree when there are seventy-nine and one grep.
    """
    i18n_module_source = I18N_TS.read_text()
    assert "pathname.split('/').includes(" in i18n_module_source, (
        "langOf no longer matches the locale as a whole path segment"
    )


# --------------------------------------------------------------------------- #
# DIST TIER
# --------------------------------------------------------------------------- #

#: Distinctive English prose that lives in a DATA file rather than in a
#: `pick()` table, one sentinel per data source. The key-parity arm cannot
#: see these -- `verbs.ts`, `spine.json` and `contracts.json` are merged by
#: key at render time, not picked -- so they are checked against the
#: rendered Spanish page instead. Each is long enough that an accidental
#: match is not credible.
DATA_FILE_SENTINELS: Final[dict[str, str]] = {
    "verbs.ts": "Concatenate PDFs; per-input page selection",
    "spine.json": "The only layer that may import the CLI framework",
    "contracts.json exit codes": "Success, including an empty-but-valid report",
    "contracts.json atomic write": "Refuses an existing target without",
    "contracts.json output shapes": "An aligned, plain-text table for a person",
    "DependencyTable roles": "pulled in by",
    "examples.ts": "Engines are optional and are found when you run the tool",
}


def test_the_spanish_page_carries_no_untranslated_data_file_prose() -> None:
    """The data files are merged by key, not by `pick()`, so the parity arm
    above is blind to them. One sentinel sentence per source closes that
    gap from the rendered side.

    Driven red: remove any single entry from `copy-es.ts`'s tables (say
    `LAYERS_ES.L1`) -> its sentinel appears in the Spanish HTML and this
    arm names which data file leaked.
    """
    _require_dist()
    es_pages = [
        DIST_ROOT / ES_SEGMENT / "index.html",
        DIST_ROOT / ES_SEGMENT / "licensing" / "index.html",
    ]
    leaks: list[str] = []
    for page in es_pages:
        if not page.is_file():
            continue
        html = page.read_text()
        for source, sentinel in DATA_FILE_SENTINELS.items():
            if sentinel in html:
                leaks.append(f"{page.relative_to(DIST_ROOT)}: untranslated {source} ({sentinel!r})")
    assert leaks == [], "English data-file prose on the Spanish page:\n  " + "\n  ".join(leaks)


def test_both_locales_declare_themselves_correctly() -> None:
    """`lang`, `og:locale`, and the `hreflang` triple, on both pages.

    The `hreflang` pair and the navbar's language switch are built from
    the same `alternatePath` call, so this also proves the switch points
    somewhere real: the alternate it declares is the page it links to.
    """
    _require_dist()
    en = (DIST_ROOT / "index.html").read_text()
    es_path = DIST_ROOT / ES_SEGMENT / "index.html"
    assert es_path.is_file(), "the Spanish route did not build"
    es = es_path.read_text()

    assert '<html lang="en">' in en, "English page does not declare lang=en"
    assert '<html lang="es">' in es, "Spanish page does not declare lang=es"
    assert 'content="en_US"' in en, "English page does not declare og:locale en_US"
    assert 'content="es_MX"' in es, "Spanish page does not declare og:locale es_MX"

    for label, html in (("en", en), ("es", es)):
        for hreflang in ("en", "es", "x-default"):
            assert f'hreflang="{hreflang}"' in html, (
                f"{label} page is missing its {hreflang} alternate"
            )


def test_the_spanish_page_ships_no_javascript_either() -> None:
    """AC11's property, restated for the route that did not exist when it
    was written. The zero-JS arms in `tests/test_website_contract.py` sweep
    all of `dist`, so this is a second reading of the same fact from the
    locale's own side -- cheap, and it fails loudly if a future locale
    mechanism reaches for a client-side language picker.
    """
    _require_dist()
    for page in sorted((DIST_ROOT / ES_SEGMENT).rglob("*.html")):
        html = page.read_text()
        assert "<script" not in html, f"{page.relative_to(DIST_ROOT)} carries a <script> tag"
