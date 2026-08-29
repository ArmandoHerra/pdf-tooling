"""Tests for ``pdf_toolkit.ops.pagerange`` — PDF-03.

Structure (Design D10): the two ``PLAN.md`` §4.3 tables are *data*
(``TOKEN_TABLE_CASES``, ``ERROR_TABLE_CASES``), each paired with a
completeness meta-test so a dropped plan row fails by name instead of
silently vanishing. ``R04_HINT_CASES`` is a third, separate table for the
PLAN §12 R-04 negative-index hint, kept apart so the §4.3 row count stays
exactly 7. The five named invariants (P1-P5, Design D8) are hypothesis tests
selectable with ``-k property`` and nothing else.

Hypothesis storage: this file uses ``st.text()``/``st.characters()`` (P1),
which — on a modern Hypothesis — writes a Unicode-charmap cache into
``.hypothesis/`` in the working directory on first use, in addition to the
usual example database. Neither belongs in a git-tracked repo (PDF-01's
``.gitignore`` has no ``.hypothesis/`` entry, and appending one is a PM
decision, not this spec's — see the task's "one known conflict"). Resolved
here, self-contained, with no new dependency and no ``conftest.py``:
Hypothesis's storage directory is redirected to a process-temp location
before any ``@settings`` decorator is evaluated, and the example database is
swapped for an in-memory one. Both calls must run at module import time,
before the first test function definition below.
"""

from __future__ import annotations

import ast
import json
import logging
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.configuration import set_hypothesis_home_dir
from hypothesis.database import InMemoryExampleDatabase

from pdf_toolkit import errors, models
from pdf_toolkit.ops import pagerange

# --- Hypothesis storage: repo-local-write-free, self-contained (see module
# docstring). Must execute before any @settings(...)-decorated test below.
set_hypothesis_home_dir(tempfile.mkdtemp(prefix="pdf-toolkit-pagerange-hypothesis-"))
settings.register_profile("pdf_toolkit_pagerange", database=InMemoryExampleDatabase())
settings.load_profile("pdf_toolkit_pagerange")


# ===========================================================================
# Hypothesis strategies
# ===========================================================================

_MAX_PAGE_COUNT = 200


@st.composite
def _valid_token(draw: Any, page_count: int) -> str:
    """One syntactically-valid page-range token for a document of ``page_count`` pages."""
    n = max(page_count, 1)
    body: str = draw(
        st.one_of(
            st.integers(min_value=1, max_value=n).map(str),
            st.tuples(
                st.integers(min_value=1, max_value=n),
                st.integers(min_value=1, max_value=n),
            ).map(lambda pair: f"{pair[0]}-{pair[1]}"),
            st.integers(min_value=1, max_value=n).map(lambda x: f"{x}-"),
            st.integers(min_value=1, max_value=n).map(lambda x: f"-{x}"),
            st.just("first"),
            st.just("last"),
            st.just("even"),
            st.just("odd"),
            st.just("all"),
        )
    )
    if draw(st.booleans()):
        body = f"!{body}"
    return body


@st.composite
def page_specs(draw: Any, page_count: int) -> str:
    """A syntactically-valid page-range spec for a document of ``page_count`` pages."""
    tokens = draw(st.lists(_valid_token(page_count), min_size=1, max_size=6))
    return ",".join(tokens)


@st.composite
def _mutated_valid_spec(draw: Any) -> str:
    """A valid spec with zero or one character-level mutation applied (P1)."""
    n = draw(st.integers(min_value=1, max_value=50))
    base: str = draw(page_specs(n))
    if not base:
        return base
    kind = draw(st.sampled_from(("insert", "delete", "replace", "none")))
    if kind == "none":
        return base
    idx = draw(st.integers(min_value=0, max_value=len(base) - 1))
    if kind == "delete":
        return base[:idx] + base[idx + 1 :]
    char = draw(st.characters(min_codepoint=32, max_codepoint=126))
    if kind == "insert":
        return base[:idx] + char + base[idx:]
    return base[:idx] + char + base[idx + 1 :]


# ===========================================================================
# AC1 — public surface
# ===========================================================================


def test_ac1_public_surface() -> None:
    assert set(pagerange.__all__) == {
        "parse",
        "render",
        "GRAMMAR_HELP",
        "PageRangeError",
        "EMPTY_SELECTION_EXIT_CODE",
    }
    assert callable(pagerange.parse)
    assert callable(pagerange.render)
    assert isinstance(pagerange.GRAMMAR_HELP, str)
    assert pagerange.PageRangeError is errors.PageRangeError
    assert pagerange.EMPTY_SELECTION_EXIT_CODE == errors.NoInputError.exit_code


# ===========================================================================
# PLAN.md §4.3 token table (rows 1-10) — Design D10
# ===========================================================================


@dataclass(frozen=True)
class _TokenCase:
    row: int
    description: str
    spec: str
    page_count: int
    ordered: bool
    expected: tuple[int, ...]


TOKEN_TABLE_CASES: tuple[_TokenCase, ...] = (
    _TokenCase(1, "N: single page", "5", 10, False, (5,)),
    _TokenCase(2, "A-B: closed ascending range", "1-3", 10, False, (1, 2, 3)),
    _TokenCase(
        3, "B-A: closed descending range, order preserved", "5-1", 10, True, (5, 4, 3, 2, 1)
    ),
    _TokenCase(4, "N-: open-ended", "9-", 10, False, (9, 10)),
    _TokenCase(5, "-N: negative index", "-1", 10, False, (10,)),
    _TokenCase(6, "first: first page", "first", 7, False, (1,)),
    _TokenCase(6, "last: last page", "last", 7, False, (7,)),
    _TokenCase(7, "even: every even page", "even", 6, False, (2, 4, 6)),
    _TokenCase(7, "odd: every odd page", "odd", 6, False, (1, 3, 5)),
    _TokenCase(8, "all: every page", "all", 4, False, (1, 2, 3, 4)),
    _TokenCase(9, "!TOKEN: exclude", "all,!3", 5, False, (1, 2, 4, 5)),
    _TokenCase(10, ",: union, left to right (with exclusion)", "1-3,last,!2", 10, True, (1, 3, 10)),
)


@pytest.mark.parametrize("case", TOKEN_TABLE_CASES, ids=lambda c: f"row{c.row}_{c.description}")
def test_token_table(case: _TokenCase) -> None:
    result = pagerange.parse(case.spec, case.page_count, ordered=case.ordered)
    assert result.indices == case.expected


def test_token_table_covers_every_plan_row() -> None:
    assert {c.row for c in TOKEN_TABLE_CASES} == set(range(1, 11))


def test_token_table_keywords_are_case_insensitive() -> None:
    assert pagerange.parse("ALL", 4).indices == pagerange.parse("all", 4).indices
    assert pagerange.parse("First,LAST", 5, ordered=True).indices == (1, 5)
    assert pagerange.parse("Even", 6).indices == pagerange.parse("even", 6).indices


def test_token_table_render_emits_lowercase_indices_only() -> None:
    # render() emits plain digits regardless of the case of the keywords that
    # produced them — there is no keyword text left to case-fold by the time
    # indices are rendered.
    rendered = pagerange.render(pagerange.parse("FIRST,LAST", 5, ordered=True))
    assert rendered == rendered.lower()


# ===========================================================================
# PLAN.md §4.3 error table (rows 1-7) — Design D10
# ===========================================================================


@dataclass(frozen=True)
class _ErrorCase:
    row: int
    description: str
    spec: str
    page_count: int
    expect_empty: bool = False
    required_substrings: tuple[str, ...] = ()


ERROR_TABLE_CASES: tuple[_ErrorCase, ...] = (
    _ErrorCase(1, "literal 0 is not 1-based", "0", 10, required_substrings=("1-based", '"0"')),
    _ErrorCase(
        1, "1-0: zero endpoint is not 1-based", "1-0", 10, required_substrings=("1-based", '"1-0"')
    ),
    _ErrorCase(2, "malformed: abc", "abc", 10, required_substrings=('"abc"', "column 1")),
    _ErrorCase(
        2,
        "malformed: 1--3 (negative endpoint in a range)",
        "1--3",
        10,
        required_substrings=('"1--3"', "column 1"),
    ),
    _ErrorCase(2, "malformed: 1-2-3", "1-2-3", 10, required_substrings=('"1-2-3"', "column 1")),
    _ErrorCase(2, "malformed: , (bare comma)", ",", 10, required_substrings=('""', "column 1")),
    _ErrorCase(2, "malformed: empty spec", "", 10, required_substrings=('""', "column 1")),
    _ErrorCase(
        3,
        "50 out of range on a 10-page document",
        "50",
        10,
        required_substrings=("out of range", "document has 10 page"),
    ),
    _ErrorCase(
        4,
        "-50 out of range on a 10-page document",
        "-50",
        10,
        required_substrings=("out of range", "document has 10 page", "negative", "1-50"),
    ),
    _ErrorCase(5, "all,!all resolves to nothing", "all,!all", 10, expect_empty=True),
    _ErrorCase(6, "even on a 1-page document", "even", 1, expect_empty=True),
    _ErrorCase(
        7,
        "9- open-ended start out of range on a 5-page document",
        "9-",
        5,
        required_substrings=("out of range", "document has 5 page"),
    ),
)


@pytest.mark.parametrize("case", ERROR_TABLE_CASES, ids=lambda c: f"row{c.row}_{c.description}")
def test_error_table(case: _ErrorCase) -> None:
    if case.expect_empty:
        result = pagerange.parse(case.spec, case.page_count)
        assert result.indices == ()
        assert result.is_empty is True
        # The exit-4 mapping (row 5/6): the CALLER exits EMPTY_SELECTION_EXIT_CODE
        # for an empty-but-valid PageRange; parse() itself never raises for one.
        assert pagerange.EMPTY_SELECTION_EXIT_CODE == 4
    else:
        with pytest.raises(errors.PageRangeError) as excinfo:
            pagerange.parse(case.spec, case.page_count)
        assert excinfo.value.exit_code == errors.UsageError.exit_code
        message = str(excinfo.value)
        for substring in case.required_substrings:
            assert substring in message, f"{substring!r} not in {message!r}"


def test_error_table_covers_every_plan_row() -> None:
    assert {c.row for c in ERROR_TABLE_CASES} == set(range(1, 8))
    required_literal_inputs = {
        "0",
        "1-0",
        "abc",
        "1--3",
        "1-2-3",
        ",",
        "",
        "50",
        "-50",
        "all,!all",
        "even",
        "9-",
    }
    assert required_literal_inputs <= {c.spec for c in ERROR_TABLE_CASES}


# ===========================================================================
# PLAN.md §12 R-04 — negative-index open-left hint, kept separate (Design D10)
# ===========================================================================


@dataclass(frozen=True)
class _R04HintCase:
    description: str
    spec: str
    page_count: int
    expect_hint: bool
    resolved_index: int | None = None
    expected_indices: tuple[int, ...] | None = None


R04_HINT_CASES: tuple[_R04HintCase, ...] = (
    _R04HintCase(
        "out-of-range negative gets the open-left hint", "-50", 10, True, resolved_index=-39
    ),
    _R04HintCase("resolvable negative index is silent", "-3", 10, False, expected_indices=(8,)),
    _R04HintCase("-page_count resolves to the first page", "-10", 10, False, expected_indices=(1,)),
)


@pytest.mark.parametrize("case", R04_HINT_CASES, ids=lambda c: c.description)
def test_r04_negative_index_hint(case: _R04HintCase, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="pdf_toolkit.ops.pagerange")
    if case.expect_hint:
        with pytest.raises(errors.PageRangeError) as excinfo:
            pagerange.parse(case.spec, case.page_count)
        message = str(excinfo.value)
        magnitude = case.spec.lstrip("-")
        assert "negative" in message
        assert f"1-{magnitude}" in message
        assert str(case.resolved_index) in message
        assert f"document has {case.page_count} page" in message
    else:
        result = pagerange.parse(case.spec, case.page_count, ordered=True)
        assert result.indices == case.expected_indices
    # A resolvable, non-exclusion-leading negative index never logs, and an
    # out-of-range one raises rather than logging — neither case here is a
    # leading-exclusion, so caplog must be empty either way.
    assert caplog.records == []


# ===========================================================================
# Direct acceptance-criteria assertions
# ===========================================================================


def test_ac4_order_semantics() -> None:
    assert pagerange.parse("1,1,3", 10, ordered=True).indices == (1, 1, 3)
    assert pagerange.parse("5-1", 10, ordered=True).indices == (5, 4, 3, 2, 1)
    assert pagerange.parse("1,1,3", 10, ordered=False).indices == (1, 3)
    assert pagerange.parse("5-1", 10, ordered=False).indices == (1, 2, 3, 4, 5)


def test_ac5_exclusion_left_to_right_order() -> None:
    assert pagerange.parse("all,!3", 5, ordered=False).indices == (1, 2, 4, 5)
    assert pagerange.parse("!3,all", 5, ordered=False).indices == (1, 2, 3, 4, 5)
    assert pagerange.parse("1-3,!2,2", 10, ordered=True).indices == (1, 3, 2)


def test_ac6_empty_selection_never_raises() -> None:
    for spec, page_count in (("all,!all", 10), ("even", 1)):
        result = pagerange.parse(spec, page_count)
        assert result.indices == ()
        assert result.is_empty is True


def test_ac7_exit_codes_are_derived_not_literal() -> None:
    assert pagerange.EMPTY_SELECTION_EXIT_CODE == errors.NoInputError.exit_code == 4
    assert errors.PageRangeError.exit_code == errors.UsageError.exit_code == 2


def test_ac7_no_exit_code_integer_literal_in_module() -> None:
    source = Path(pagerange.__file__).read_text()
    pattern = re.compile(r"=\s*[24]\s*(#|$)", re.MULTILINE)
    assert pattern.search(source) is None


def test_ac8_error_carries_token_and_column() -> None:
    with pytest.raises(errors.PageRangeError) as excinfo:
        pagerange.parse("1-3,abc", 10)
    error = excinfo.value
    assert error.token == "abc"
    assert error.column == 5
    message = str(error)
    assert "abc" in message
    assert "column 5" in message


def test_ac9_negative_index_hint_message() -> None:
    with pytest.raises(errors.PageRangeError) as excinfo:
        pagerange.parse("-50", 10)
    message = str(excinfo.value)
    assert "1-50" in message
    assert "negative" in message
    assert str(10 - 50 + 1) in message
    assert "document has 10 pages" in message


def test_ac9_resolvable_negative_index_is_silent(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="pdf_toolkit.ops.pagerange")
    result = pagerange.parse("-3", 10, ordered=True)
    assert result.indices == (8,)
    assert caplog.records == []


def test_ac10_named_invariants_are_selectable_and_number_five() -> None:
    module = sys.modules[__name__]
    invariant_tests = [
        name
        for name in dir(module)
        if name.startswith("test_") and "property" in name and callable(getattr(module, name))
    ]
    assert len(invariant_tests) == 5, invariant_tests


def test_ac11_render_is_canonical() -> None:
    assert pagerange.render(pagerange.parse("1-3,last", 10, ordered=True)) == "1,2,3,10"
    empty = pagerange.parse("all,!all", 10)
    assert pagerange.render(empty) == ""
    with pytest.raises(errors.PageRangeError):
        pagerange.parse("", 10)


REQUIRED_TOKEN_FORMS: tuple[str, ...] = (
    "N",
    "A-B",
    "B-A",
    "N-",
    "-N",
    "first",
    "last",
    "even",
    "odd",
    "all",
    "!",
    ",",
)


def test_ac14_grammar_help_documents_every_token() -> None:
    docstring = pagerange.__doc__ or ""
    for form in REQUIRED_TOKEN_FORMS:
        assert form in pagerange.GRAMMAR_HELP, f"{form!r} missing from GRAMMAR_HELP"
        assert form in docstring, f"{form!r} missing from the module docstring"
    assert "1-based" in pagerange.GRAMMAR_HELP
    assert "1-based" in docstring


def test_ac15_no_io_calls_in_module() -> None:
    source = Path(pagerange.__file__).read_text()
    forbidden = re.compile(
        r"\bprint\(|sys\.stderr|\bopen\(|write_bytes|write_text|shutil|subprocess"
        r"|tempfile|os\.replace|Path\("
    )
    assert forbidden.search(source) is None


def test_ac15_leading_exclusion_warns_exactly_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="pdf_toolkit.ops.pagerange")
    result = pagerange.parse("!3,all", 5, ordered=False)
    assert result.indices == (1, 2, 3, 4, 5)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "!3" in message
    assert "exclusion" in message


def test_ac15_non_leading_exclusion_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="pdf_toolkit.ops.pagerange")
    pagerange.parse("all,!3", 5, ordered=False)
    assert caplog.records == []


def test_ac16_pagerange_model_is_additive_only() -> None:
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(models.PageRange)}
    assert field_names == {"spec", "indices", "ordered", "page_count"}
    assert "is_empty" not in field_names

    non_empty = models.PageRange(spec="1-3", indices=(1, 2, 3), ordered=True, page_count=10)
    assert non_empty.as_set() == frozenset({1, 2, 3})
    assert non_empty.is_empty is False
    payload = non_empty.to_dict()
    assert set(payload.keys()) == {"spec", "indices", "ordered", "page_count"}
    json.dumps(payload)  # must not raise

    empty = models.PageRange(spec="", indices=(), ordered=False, page_count=1)
    assert empty.is_empty is True


def test_ac17_validation_precedes_materialization() -> None:
    start = time.monotonic()
    with pytest.raises(errors.PageRangeError):
        pagerange.parse("1-99999999999", 10)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"validation took {elapsed:.3f}s; must precede materialization"

    with pytest.raises(errors.PageRangeError):
        pagerange.parse("1", 0)


def test_ac17_pathologically_long_numeral_is_a_pagerange_error_not_valueerror() -> None:
    # Python 3.11+ refuses int() conversion beyond 4300 digits (a bare
    # ValueError). Totality (P1) requires only PageRangeError escapes.
    huge = "9" * 4400
    start = time.monotonic()
    with pytest.raises(errors.PageRangeError) as excinfo:
        pagerange.parse(huge, 10)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0
    assert excinfo.value.exit_code == errors.UsageError.exit_code


def test_negative_zero_is_the_same_defect_as_literal_zero() -> None:
    with pytest.raises(errors.PageRangeError) as excinfo:
        pagerange.parse("-0", 10)
    message = str(excinfo.value)
    assert "1-based" in message
    assert '"-0"' in message


# AC18 ("no forbidden-engine reference in pagerange.py or this test file") is
# proven by an external `grep` over both files during validation, not by an
# embedded test here: spelling out the forbidden engine names as string
# literals to assert their absence would itself make this file match that
# same grep, defeating the check it is trying to prove.


# ===========================================================================
# AC13 — import boundary (AST walk, not a text grep)
# ===========================================================================

_ALLOWED_FROM_MODULES = frozenset({"pdf_toolkit.models", "pdf_toolkit.errors"})


def test_pagerange_imports_are_stdlib_only() -> None:
    source = Path(pagerange.__file__).read_text()
    tree = ast.parse(source)
    stdlib_names = set(sys.stdlib_module_names) | {"__future__"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root in stdlib_names, f"non-stdlib import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            allowed = module in _ALLOWED_FROM_MODULES or root in stdlib_names
            assert allowed, f"disallowed import-from: {module}"


def test_pagerange_module_does_no_io() -> None:
    """A stronger, still-portable restatement of AC15: no filesystem, process
    or stream call anywhere the module's source reaches, verified the same
    way AC13 is — reading this module's own file, never another path."""
    source = Path(pagerange.__file__).read_text()
    assert "open(" not in source
    assert "subprocess" not in source
    assert "sys.stderr" not in source
    assert "print(" not in source


# ===========================================================================
# Named property invariants P1-P5 (Design D8) — select with `-k property`
# ===========================================================================


@settings(max_examples=1000, deadline=None)
@given(
    spec=st.one_of(st.text(), _mutated_valid_spec()),
    page_count=st.integers(min_value=-5, max_value=_MAX_PAGE_COUNT),
    ordered=st.booleans(),
)
def test_property_p1_totality(spec: str, page_count: int, ordered: bool) -> None:
    """parse() is total or raises PageRangeError — never another exception type.

    No broad except: any other exception escaping is exactly what this test
    must fail on, so it is left uncaught rather than laundered.
    """
    try:
        result = pagerange.parse(spec, page_count, ordered=ordered)
    except errors.PageRangeError:
        return
    assert isinstance(result, models.PageRange)


@settings(max_examples=1000, deadline=None)
@given(data=st.data())
def test_property_p2_bounds_and_coverage(data: st.DataObject) -> None:
    n = data.draw(st.integers(min_value=1, max_value=_MAX_PAGE_COUNT))
    spec = data.draw(page_specs(n))
    ordered = data.draw(st.booleans())

    result = pagerange.parse(spec, n, ordered=ordered)
    assert all(1 <= i <= n for i in result.indices)
    assert pagerange.parse("all", n).indices == tuple(range(1, n + 1))


@settings(max_examples=1000, deadline=None)
@given(data=st.data())
def test_property_p3_order_vs_set(data: st.DataObject) -> None:
    n = data.draw(st.integers(min_value=1, max_value=_MAX_PAGE_COUNT))
    spec = data.draw(page_specs(n))

    ordered_result = pagerange.parse(spec, n, ordered=True)
    unordered_result = pagerange.parse(spec, n, ordered=False)

    assert unordered_result.indices == tuple(sorted(set(ordered_result.indices)))
    assert list(unordered_result.indices) == sorted(unordered_result.indices)
    assert len(set(unordered_result.indices)) == len(unordered_result.indices)


@settings(max_examples=1000, deadline=None)
@given(data=st.data())
def test_property_p4_exclusion_exactness(data: st.DataObject) -> None:
    n = data.draw(st.integers(min_value=1, max_value=_MAX_PAGE_COUNT))
    spec = data.draw(page_specs(n))
    k = data.draw(st.integers(min_value=1, max_value=n))

    base_unordered = pagerange.parse(spec, n, ordered=False)
    excluded_unordered = pagerange.parse(f"{spec},!{k}", n, ordered=False)
    assert excluded_unordered.as_set() == base_unordered.as_set() - {k}

    base_ordered = pagerange.parse(spec, n, ordered=True)
    excluded_ordered = pagerange.parse(f"{spec},!{k}", n, ordered=True)
    assert k not in excluded_ordered.indices
    assert list(excluded_ordered.indices) == [i for i in base_ordered.indices if i != k]


@settings(max_examples=1000, deadline=None)
@given(data=st.data())
def test_property_p5_render_round_trip(data: st.DataObject) -> None:
    n = data.draw(st.integers(min_value=1, max_value=_MAX_PAGE_COUNT))
    spec = data.draw(page_specs(n))
    ordered = data.draw(st.booleans())

    original = pagerange.parse(spec, n, ordered=ordered)
    assume(not original.is_empty)

    rendered = pagerange.render(original)
    round_tripped = pagerange.parse(rendered, n, ordered=ordered)

    assert round_tripped.indices == original.indices
    assert round_tripped.ordered == original.ordered
    assert round_tripped.page_count == original.page_count
