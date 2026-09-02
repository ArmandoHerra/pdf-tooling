"""The page-range grammar: one parser, one renderer, unwired by design.

``PLAN.md`` §4.3 fixes this grammar once so that every page-addressing verb
(eight of the 24 v1 verbs) consumes the same tokens instead of learning them
eight separate ways (G6). This module owns the grammar end to end: parsing,
validation, ordering, exclusion, and the canonical ``render()`` that inverts
it. It resolves against an integer ``page_count`` only — never a path, never
a real document — and it is framework-free, I/O-free, and importable as a
plain library (``PLAN.md`` §5.2, L2).

Grammar (1-based, inclusive throughout — matching every printed page number
and every other PDF tool a user has met):

    N        a single page, e.g. "5"
    A-B      a closed range, ascending, e.g. "1-3" -> 1,2,3
    B-A      a closed range, descending, order preserved, e.g. "5-1" -> 5,4,3,2,1
    N-       open-ended, N through the last page, e.g. "9-"
    -N       negative index, counted from the end; "-1" is the last page,
             "-2" the second-to-last. There is no "-N" meaning "1 through N";
             write "1-N" for that (PLAN.md §12 R-04, decided and closed).
    first    the first page
    last     the last page
    even     pages whose 1-based number is even
    odd      pages whose 1-based number is odd
    all      every page
    !TOKEN   exclude TOKEN from the union of everything named so far, e.g.
             "all,!3". Exclusions apply left to right: "all,!3" and "!3,all"
             differ, since the second has nothing to its left to subtract
             from. A spec whose first token is an exclusion logs one warning.
    ,        union, evaluated strictly left to right, e.g. "1-3,last,!2"

Keyword tokens (first/last/even/odd/all) are case-insensitive; ``render()``
always emits lowercase. Outer whitespace around a token is stripped; internal
whitespace ("1 - 3") is malformed, same as any other unrecognized shape.

An **empty-but-valid** selection ("all,!all", or "even" on a 1-page document)
is not an error: ``parse()`` returns a ``PageRange`` with ``indices == ()``
and ``is_empty`` true. The caller maps that to ``EMPTY_SELECTION_EXIT_CODE``
(derived from ``errors.NoInputError``, exit 4) — raising here would abort an
entire batch over one input that legitimately matched nothing.

See ``GRAMMAR_HELP`` for the one-paragraph user-facing rendering of this same
grammar, which PDF-07/PDF-08 generate their ``--pages``/``--ranges`` help
text from instead of hand-writing eight copies.
"""

from __future__ import annotations

import logging
import re
from typing import Final

from pdf_toolkit.errors import NoInputError, PageRangeError
from pdf_toolkit.models import PageRange

#: `tests/test_pagerange.py::test_ac1_public_surface` pins this list EXACTLY
#: (PDF-03's own public-surface contract, AC6: that file is unedited and
#: passes unchanged). `is_valid_spec` and `ALL_PAGES_TOKEN` below are PDF-07
#: additions that stay OUT of `__all__` for exactly that reason — still
#: directly importable (`__all__` only governs `from module import *`), just
#: not part of the pinned surface. Recorded in this spec's Implementation Log.
__all__ = [
    "EMPTY_SELECTION_EXIT_CODE",
    "GRAMMAR_HELP",
    "PageRangeError",
    "parse",
    "render",
]

#: The §4.3 keyword meaning "every page", exported (though not via `__all__`
#: — see above) so a caller needing "no selection given, so select
#: everything" (`merge`'s per-input default) never has to spell the token
#: itself — AC7 forbids the literal string "all" outside this file.
ALL_PAGES_TOKEN: Final[str] = "all"

_LOG = logging.getLogger(__name__)

#: Derived, never a literal — AC7 greps this module for bare exit-code
#: integers. The empty-but-valid selection maps to the same exit code as any
#: other "valid invocation, nothing to act on" outcome.
EMPTY_SELECTION_EXIT_CODE: Final[int] = NoInputError.exit_code

#: The single user-facing grammar blurb. PDF-07/PDF-08 build their `--pages`
#: help text from this one string instead of eight hand-written copies — the
#: mechanism that makes G6 ("one grammar, learned once") real.
GRAMMAR_HELP: Final[str] = (
    "Page ranges are 1-based and inclusive, and reuse the same ten token "
    "forms everywhere pages are selected:\n"
    "  N        a single page, e.g. 5\n"
    "  A-B      a closed range, ascending, e.g. 1-3\n"
    "  B-A      a closed range, descending, order preserved, e.g. 5-1\n"
    "  N-       open-ended, N through the last page, e.g. 9-\n"
    "  -N       negative index, counted from the end, e.g. -1 is the last page\n"
    "  first    the first page\n"
    "  last     the last page\n"
    "  even     every even-numbered page\n"
    "  odd      every odd-numbered page\n"
    "  all      every page\n"
    "  !TOKEN   exclude TOKEN from everything named so far, e.g. all,!3\n"
    "  ,        union, evaluated left to right, e.g. 1-3,last,!2\n"
    "Keywords are case-insensitive. An exclusion as the first token has "
    "nothing to its left to subtract from, and is warned about."
)

_KEYWORDS: Final[frozenset[str]] = frozenset({"first", "last", "even", "odd", "all"})

# ASCII-only: a Unicode "digit" that ``int()`` cannot parse the same way
# ``\d`` matched it would otherwise turn an unrestricted-text fuzz input into
# an escaping exception rather than a clean ``PageRangeError`` (see P1).
_SINGLE_RE: Final[re.Pattern[str]] = re.compile(r"^\d+$", re.ASCII)
_RANGE_RE: Final[re.Pattern[str]] = re.compile(r"^(\d+)-(\d+)$", re.ASCII)
_OPEN_END_RE: Final[re.Pattern[str]] = re.compile(r"^(\d+)-$", re.ASCII)
_NEGATIVE_RE: Final[re.Pattern[str]] = re.compile(r"^-(\d+)$", re.ASCII)


def _split_tokens(spec: str) -> list[tuple[str, int]]:
    """Split ``spec`` on top-level commas into ``(token, column)`` pairs.

    ``column`` is the 1-based position, in the *original* ``spec``, of the
    token's first character after outer whitespace is stripped (or of where
    that content would start, for an all-whitespace segment). Internal
    whitespace inside a token is preserved, so it later fails token
    validation as malformed rather than being silently accepted.
    """
    tokens: list[tuple[str, int]] = []
    pos = 0
    for part in spec.split(","):
        leading = len(part) - len(part.lstrip())
        tokens.append((part.strip(), pos + leading + 1))
        pos += len(part) + 1
    return tokens


def _safe_int(digits: str, *, spec: str, token: str, column: int) -> int:
    """``int(digits)``, converting a pathological-length failure into our own error.

    Python 3.11+ refuses to convert an int/str of more than 4300 digits
    (CVE-2020-10735 mitigation) and raises a bare ``ValueError``. Totality
    (P1) requires that only ``PageRangeError`` ever escapes ``parse()``.
    """
    try:
        return int(digits)
    except ValueError:
        raise PageRangeError(
            f'malformed page-range token "{token}" in "{spec}" (column {column}): '
            "numeral is too long to be a page number",
            spec=spec,
            token=token,
            column=column,
            reason="malformed",
        ) from None


def _malformed(spec: str, token: str, column: int) -> PageRangeError:
    return PageRangeError(
        f'malformed page-range token "{token}" in "{spec}" (column {column})',
        spec=spec,
        token=token,
        column=column,
        reason="malformed",
    )


def _not_one_based(spec: str, token: str, column: int) -> PageRangeError:
    return PageRangeError(
        f'pages are 1-based; "{token}" in "{spec}" (column {column}) is not a page',
        spec=spec,
        token=token,
        column=column,
        reason="not_1_based",
    )


def _out_of_range(
    resolved: int, page_count: int, *, spec: str, token: str, column: int
) -> PageRangeError:
    plural = "" if page_count == 1 else "s"
    return PageRangeError(
        f"page {resolved} out of range (document has {page_count} page{plural}) "
        f'(token "{token}" in "{spec}", column {column})',
        spec=spec,
        token=token,
        column=column,
        reason="out_of_range",
    )


def _validate_endpoint(n: int, page_count: int, *, spec: str, token: str, column: int) -> None:
    """Bounds-check one numeric endpoint before any range is materialized (D3)."""
    if n == 0:
        raise _not_one_based(spec, token, column)
    if n > page_count:
        raise _out_of_range(n, page_count, spec=spec, token=token, column=column)


def _resolve_negative(
    magnitude: int, page_count: int, *, spec: str, token: str, column: int
) -> int:
    """Resolve a ``-N`` token: ``-1`` is the last page, per PLAN §12 R-04.

    A zero magnitude ("-0") is the same defect as a literal "0": there is no
    "1-based" page to name. Any other magnitude that resolves outside
    ``1..page_count`` is the one case where "negative index" is provably not
    what the user meant, and the message names the open-left fix explicitly.
    """
    if magnitude == 0:
        raise _not_one_based(spec, token, column)

    resolved = page_count - magnitude + 1
    if resolved < 1:
        plural = "" if page_count == 1 else "s"
        magnitude_plural = "" if magnitude == 1 else "s"
        raise PageRangeError(
            f"page {resolved} out of range (document has {page_count} page{plural}); "
            f'"{token}" is a negative index counting {magnitude} page{magnitude_plural} '
            f'from the end — did you mean the open-left range "1-{magnitude}"? '
            f'(in "{spec}", column {column})',
            spec=spec,
            token=token,
            column=column,
            reason="negative_out_of_range",
        )
    return resolved


def _resolve_body(body: str, page_count: int, *, spec: str, token: str, column: int) -> list[int]:
    """Resolve one token's body (the part after a leading ``!``, if any).

    Order: keywords first (cheap, unambiguous), then the four numeric shapes
    in an order chosen so their anchored patterns cannot overlap. Anything
    left over is malformed — this is the sole fallthrough, which is what
    makes totality (P1) provable by inspection rather than by exhaustive case
    analysis.
    """
    lowered = body.lower()
    if lowered in _KEYWORDS:
        if lowered == "all":
            return list(range(1, page_count + 1))
        if lowered == "first":
            return [1]
        if lowered == "last":
            return [page_count]
        if lowered == "even":
            return [i for i in range(1, page_count + 1) if i % 2 == 0]
        return [i for i in range(1, page_count + 1) if i % 2 == 1]  # "odd"

    match = _NEGATIVE_RE.match(body)
    if match:
        magnitude = _safe_int(match.group(1), spec=spec, token=token, column=column)
        resolved = _resolve_negative(magnitude, page_count, spec=spec, token=token, column=column)
        return [resolved]

    match = _OPEN_END_RE.match(body)
    if match:
        start = _safe_int(match.group(1), spec=spec, token=token, column=column)
        _validate_endpoint(start, page_count, spec=spec, token=token, column=column)
        return list(range(start, page_count + 1))

    match = _RANGE_RE.match(body)
    if match:
        first = _safe_int(match.group(1), spec=spec, token=token, column=column)
        second = _safe_int(match.group(2), spec=spec, token=token, column=column)
        _validate_endpoint(first, page_count, spec=spec, token=token, column=column)
        _validate_endpoint(second, page_count, spec=spec, token=token, column=column)
        step = 1 if second >= first else -1
        return list(range(first, second + step, step))

    match = _SINGLE_RE.match(body)
    if match:
        n = _safe_int(match.group(0), spec=spec, token=token, column=column)
        _validate_endpoint(n, page_count, spec=spec, token=token, column=column)
        return [n]

    raise _malformed(spec, token, column)


def parse(spec: str, page_count: int, *, ordered: bool = False) -> PageRange:
    """Parse ``spec`` against a document of ``page_count`` pages.

    One left-to-right evaluator over a running ``list[int]``, then one
    normalization switch at the end (D2): ``ordered=True`` keeps the running
    list exactly as built (order and duplicates meaningful — extract,
    reorder, merge-per-input); ``ordered=False`` collapses it to a sorted,
    duplicate-free tuple (delete, rotate, text, tables, rasterize, watermark,
    stamp, ocr, compress --images). Both semantics come from the same
    evaluator, which is what makes "the unordered result is the sorted,
    deduplicated ordered result" true by construction rather than by two
    parallel code paths.

    Total or raises :class:`PageRangeError` — never another exception type,
    and never blocks: every numeric endpoint is bounds-checked before any
    range is expanded, so a spec like "1-99999999999" fails immediately
    rather than building an 11-digit list first.

    An empty-but-valid selection ("all,!all", or "even" on a 1-page
    document) is returned, not raised — see the module docstring.

    Raises:
        PageRangeError: ``page_count < 1``, or the spec is malformed or
            resolves a token outside ``1..page_count``.
    """
    if page_count < 1:
        raise PageRangeError(
            f"invalid page_count {page_count}: a document has at least 1 page",
            spec=spec,
            token="",  # nosec B106 -- the grammar's offending-token field, not a credential
            column=1,
            reason="invalid_page_count",
        )

    running: list[int] = []
    for position, (raw_token, column) in enumerate(_split_tokens(spec)):
        is_exclusion = raw_token.startswith("!")
        body = raw_token[1:] if is_exclusion else raw_token

        if is_exclusion and position == 0:
            _LOG.warning(
                "page-range spec %r begins with exclusion token %r; "
                "there is nothing to its left to exclude from",
                spec,
                raw_token,
            )

        resolved = _resolve_body(body, page_count, spec=spec, token=raw_token, column=column)

        if is_exclusion:
            excluded = set(resolved)
            running = [i for i in running if i not in excluded]
        else:
            running.extend(resolved)

    indices: tuple[int, ...] = tuple(running) if ordered else tuple(sorted(set(running)))
    return PageRange(spec=spec, indices=indices, ordered=ordered, page_count=page_count)


def _is_valid_body_shape(body: str) -> bool:
    """Whether *body* matches one of §4.3's five token shapes -- no bounds check.

    Mirrors :func:`_resolve_body`'s dispatch exactly, reusing the SAME
    keyword set, the SAME compiled regexes and the SAME numeral-conversion
    ceiling, so a grammar change can never leave this answer out of step with
    ``parse()``'s -- a property that is now asserted rather than asserted
    about, by ``test_syntax_oracle_agrees_with_parse``. Deliberately does
    **not** call ``_resolve_body`` itself: that function materializes a range
    (``list(range(first, second + step, step))``), and a syntax-only check
    must never do that -- an unbounded shape check that materialized would
    let a spec like ``"1-99999999999"`` try to build a 100-billion-element
    list before any page count is even known.
    """
    lowered = body.lower()
    if lowered in _KEYWORDS:
        return True
    match = (
        _NEGATIVE_RE.match(body)
        or _OPEN_END_RE.match(body)
        or _RANGE_RE.match(body)
        or _SINGLE_RE.match(body)
    )
    if match is None:
        return False
    try:
        for numeral in match.groups() or (match.group(0),):
            int(numeral)
    except ValueError:
        # Past CPython's 4300-digit int() ceiling. `parse()` converts the same
        # failure into a "malformed" PageRangeError through `_safe_int`, so
        # answering True here would leave the two dispatches out of step on
        # the one input where they can be: `merge`'s path:range
        # disambiguation would read a 4400-digit numeral as a page range and
        # then fail to parse it, instead of reading it as part of a filename.
        return False
    return True


def is_valid_spec(spec: str) -> bool:
    """Whether *spec* is syntactically well-formed per §4.3 -- bounds ignored.

    The syntax-only wrapper Design §D2 asks for: `merge`'s ``path:range``
    disambiguation must answer "is the text after the last colon a
    page-range expression" **before** a document, and therefore a page
    count, is even known. Grammar knowledge stays in this one file (G6) --
    the caller (``ops/merge.py``) never inspects a token shape itself.

    Bounds (page 0, an out-of-range endpoint, a negative index past the
    start) are deliberately **not** checked here: whether ``"500"`` is a
    valid page depends on a document this function never sees, and §D2 is
    explicit that an out-of-range value is a resolution-time concern, not a
    step-2 concern. A token that is bounds-doomed on every conceivable
    document (``"0"``) is still reported as syntactically valid here for the
    same reason — it is *shaped* like a page number, and only `parse()`,
    resolved against a real page count, is positioned to say it never
    survives.

    An empty or blank spec is not valid (nothing to split at); a spec is
    valid only when **every** comma-separated token is one of the five
    shapes.
    """
    if not spec.strip():
        return False
    tokens = _split_tokens(spec)
    if not tokens:
        return False
    for raw_token, _column in tokens:
        body = raw_token[1:] if raw_token.startswith("!") else raw_token
        if not _is_valid_body_shape(body):
            return False
    return True


def render(selection: PageRange) -> str:
    """The canonical, comma-joined rendering of ``selection.indices``.

    Not a compressor (D6): duplicates and order are preserved exactly, so
    round-tripping through :func:`parse` at the same ``page_count`` is true
    by construction rather than by a compressor that has to be right about
    duplicates adjacent to descending runs. The empty selection renders as
    the empty string; ``parse("")`` raises, so that asymmetry is deliberate.
    """
    return ",".join(str(index) for index in selection.indices)
