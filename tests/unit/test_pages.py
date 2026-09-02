"""PDF-08 — `extract` / `delete` / `rotate` / `reorder`: semantics, ordering,
normalization, the remainder rule and rotation arithmetic.

**Assertion discipline (§D10).** Every functional claim here is proven by
opening the output document and reading it back — per-page text via
``pypdfium2`` (``tests/pdfium_text.py``) for identity, ``/Rotate`` off the
output's own page objects via ``pypdf`` for rotation. ``exit_code == 0`` alone
is never an acceptance criterion for a functional claim, and every "X changed"
assertion has its matching "everything else did not" half over the WHOLE
document.

``info --pages-detail`` is deliberately **not** the rotation oracle:
``PageInfo.rotation`` reports ``0`` both for an absent ``/Rotate`` and for an
explicit ``/Rotate 0``, which is exactly the distinction AC14's negative half
exists to catch.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_toolkit.errors import NoInputError, PageRangeError, RefusedError  # noqa: E402
from pdf_toolkit.models import PageRange  # noqa: E402
from pdf_toolkit.ops.pages import (  # noqa: E402
    ROTATION_ANGLES,
    delete_run,
    extract_run,
    normalize_rotation,
    plan_delete,
    plan_extract,
    plan_reorder,
    plan_rotate,
    reorder_run,
    rotate_run,
)
from pdf_toolkit.safety.policy import SafetyPolicy  # noqa: E402
from pdfium_text import page_texts  # noqa: E402
from registry import PDF_08_VERBS  # noqa: E402

FIXTURE = "ten_page_text"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _policy(**overrides: object) -> SafetyPolicy:
    base: dict[str, object] = {
        "dry_run": False,
        "force": False,
        "in_place": False,
        "backup": True,
        "assume_yes": False,
        "is_tty": False,
        "threads": 1,
    }
    base.update(overrides)
    return SafetyPolicy(**base)  # type: ignore[arg-type]


def _page_numbers(path: Path) -> list[int]:
    """The 1-based ORIGINAL page number each output page carries, read back
    from the page's own text.

    The generated corpus writes its own page number into every page (the §10
    "fixture as contract" property), so this reads what the document actually
    says rather than trusting the order the tool claims to have written.
    """
    numbers: list[int] = []
    for text in page_texts(path):
        match = re.search(r"page (\d+) of 10", text)
        assert match is not None, f"unexpected page text: {text!r}"
        numbers.append(int(match.group(1)))
    return numbers


def _rotations(path: Path) -> list[int | None]:
    """Every page's ``/Rotate``, with ``None`` for an ABSENT key.

    ``None`` rather than ``0`` is the whole point: an absent key and an
    explicit ``/Rotate 0`` render identically and are a different fact about
    the document (§D4), and only one of them is what an untouched page must
    keep.
    """
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return [(page.get("/Rotate") if "/Rotate" in page else None) for page in reader.pages]


def _media_boxes(path: Path) -> list[tuple[float, float, float, float]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return [
        (
            float(page.mediabox.left),
            float(page.mediabox.bottom),
            float(page.mediabox.right),
            float(page.mediabox.top),
        )
        for page in reader.pages
    ]


def _strip_rotate(source: Path, destination: Path) -> Path:
    """A copy of *source* with every ``/Rotate`` key REMOVED.

    Needed because reportlab writes an explicit ``/Rotate 0`` onto every page
    it produces (measured, not assumed — see this spec's Implementation Log),
    so no generated fixture has a genuinely absent key. Without this, AC14's
    negative half — "remaining absent where the key was absent" — could not be
    observed at all, and a test that cannot observe its own property is the
    vacuous-pass shape X-89 warns about.
    """
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject

    reader = PdfReader(str(source))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    for page in writer.pages:
        if "/Rotate" in page:
            del page[NameObject("/Rotate")]
    with open(destination, "wb") as handle:  # noqa: PTH123 - tests/ is exempt from the write-chokepoint walk
        writer.write(handle)
    return destination


def _selection(spec: str, indices: tuple[int, ...], *, ordered: bool, page_count: int = 10):
    return PageRange(spec=spec, indices=indices, ordered=ordered, page_count=page_count)


# --------------------------------------------------------------------------- #
# §D1 — the set-vs-ordered table, as PURE functions. No engine, no filesystem.
# This is the layer at which the table is code rather than prose.
# --------------------------------------------------------------------------- #


def test_plan_extract_preserves_order_and_duplicates() -> None:
    assert plan_extract(_selection("1,1,3", (1, 1, 3), ordered=True)) == (1, 1, 3)


def test_plan_extract_preserves_a_descending_range() -> None:
    assert plan_extract(_selection("5-1", (5, 4, 3, 2, 1), ordered=True)) == (5, 4, 3, 2, 1)


def test_plan_delete_is_idempotent_over_duplicates() -> None:
    """A `delete` that iterated `indices` and removed by index in emission
    order would corrupt its own indices on a duplicate. Consuming the
    selection as a SET makes that impossible rather than merely unlikely."""
    with_duplicate = plan_delete(_selection("1,1,3", (1, 3), ordered=False, page_count=5))
    without = plan_delete(_selection("1,3", (1, 3), ordered=False, page_count=5))
    assert with_duplicate == without == (2, 4, 5)


def test_plan_delete_returns_survivors_in_ascending_original_order() -> None:
    assert plan_delete(_selection("even", (2, 4, 6, 8, 10), ordered=False)) == (1, 3, 5, 7, 9)


def test_plan_reorder_appends_the_pages_the_selection_did_not_name() -> None:
    assert plan_reorder(_selection("last,1", (10, 1), ordered=True)) == (
        10,
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
    )


def test_plan_reorder_composes_duplicates_with_the_remainder() -> None:
    assert plan_reorder(_selection("1,1", (1, 1), ordered=True, page_count=3)) == (1, 1, 2, 3)


def test_plan_reorder_is_total_over_every_selection_shape() -> None:
    """§D3's invariant, stated as a property: every input page appears at least
    once, so `reorder` can never be the verb that loses a document."""
    for indices in [(10, 1), (1,), (5, 5, 5), tuple(range(1, 11))]:
        planned = plan_reorder(_selection("x", indices, ordered=True))
        assert set(planned) == set(range(1, 11))
        assert len(planned) >= 10


def test_plan_reorder_moves_an_excluded_page_to_the_back_never_deletes_it() -> None:
    """`all,!3` on five pages resolves to (1,2,4,5); page 3 is simply not
    named, so the remainder rule appends it. Surprising enough to be its own
    criterion: a user who wants page 3 gone runs `delete`."""
    assert plan_reorder(_selection("all,!3", (1, 2, 4, 5), ordered=True, page_count=5)) == (
        1,
        2,
        4,
        5,
        3,
    )


def test_plan_rotate_stamps_a_duplicated_page_exactly_once() -> None:
    """AC4 at the pure layer: a duplicate in a SET selection rotates a page
    ONCE, which is observable precisely because rotation is relative."""
    pages, stamps = plan_rotate(
        _selection("1,1", (1,), ordered=False), {1: 0}, angle=90, absolute=False
    )
    assert pages == tuple(range(1, 11))
    assert stamps == {0: 90}


def test_plan_rotate_stamps_only_the_pages_the_selection_names() -> None:
    """The "absent stays absent" property, at the layer where it is decided:
    an unnamed page gets no entry in the stamp map, so it gets no call, so it
    keeps whatever `append_pages` copied -- including an absent key."""
    _pages, stamps = plan_rotate(
        _selection("1", (1,), ordered=False), {}, angle=180, absolute=False
    )
    assert set(stamps) == {0}


@pytest.mark.parametrize(
    ("current", "angle", "absolute", "expected"),
    [
        (270, 90, False, 0),  # never 360
        (0, -90, False, 270),  # never -90
        (90, 180, False, 270),
        (180, 180, False, 0),
        (270, -90, True, 270),  # absolute ignores the current value
        (270, 180, True, 180),
        (90, 90, True, 90),
    ],
)
def test_normalize_rotation_is_modular_into_the_four_legal_values(
    current: int, angle: int, absolute: bool, expected: int
) -> None:
    assert normalize_rotation(current, angle, absolute=absolute) == expected


def test_normalize_rotation_never_leaves_the_legal_set() -> None:
    for current in (0, 90, 180, 270):
        for angle in ROTATION_ANGLES:
            for absolute in (True, False):
                assert normalize_rotation(current, angle, absolute=absolute) in (0, 90, 180, 270)


# --------------------------------------------------------------------------- #
# AC1/AC2/AC3/AC5 — the same table, proven end to end by re-reading the output
# --------------------------------------------------------------------------- #


def test_ac1_extract_duplicates_are_preserved_in_the_order_given(corpus, tmp_path: Path) -> None:
    target = tmp_path / "ac1.pdf"
    result = extract_run(
        [corpus.path(FIXTURE)],
        pages_spec="1,1,3",
        output=target,
        out_dir=None,
        name_template=None,
        policy=_policy(),
    )
    assert result.exit_code == 0
    assert _page_numbers(target) == [1, 1, 3]


def test_ac2_extract_preserves_a_descending_range(corpus, tmp_path: Path) -> None:
    target = tmp_path / "ac2.pdf"
    extract_run(
        [corpus.path(FIXTURE)],
        pages_spec="5-1",
        output=target,
        out_dir=None,
        name_template=None,
        policy=_policy(),
    )
    assert _page_numbers(target) == [5, 4, 3, 2, 1]


def test_ac3_delete_duplicates_are_idempotent(corpus, tmp_path: Path) -> None:
    """Both spellings must produce the same page count AND the same per-page
    text sequence -- the count alone would pass for several wrong answers."""
    outputs = []
    for index, spec in enumerate(("1,1,3", "1,3")):
        target = tmp_path / f"ac3-{index}.pdf"
        delete_run(
            [corpus.path(FIXTURE)],
            pages_spec=spec,
            output=target,
            out_dir=None,
            name_template=None,
            in_place=False,
            policy=_policy(),
        )
        outputs.append(_page_numbers(target))
    assert outputs[0] == outputs[1] == [2, 4, 5, 6, 7, 8, 9, 10]


def test_ac5_reorder_puts_the_original_last_page_first(corpus, tmp_path: Path) -> None:
    target = tmp_path / "ac5.pdf"
    reorder_run(
        [corpus.path(FIXTURE)],
        pages_spec="last,1",
        output=target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    read_back = _page_numbers(target)
    assert read_back[0] == 10
    assert read_back[1] == 1


def test_ac6_each_verb_threads_the_ordered_value_its_semantics_require(
    corpus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC6 (replacement), half (i): the D1 table proven behaviourally, by
    recording the `ordered=` keyword each verb hands the ONE shared parser.

    Half (ii) -- the observable page sequences -- is AC1/AC2/AC3/AC4 above,
    and is the authority if the two ever disagree.
    """
    import pdf_toolkit.ops.pagerange as pagerange_module
    import pdf_toolkit.ops.pages as pages_module

    seen: list[tuple[str, bool]] = []
    real_parse = pagerange_module.parse

    def spy(spec: str, page_count: int, *, ordered: bool = False):
        seen.append((spec, ordered))
        return real_parse(spec, page_count, ordered=ordered)

    monkeypatch.setattr(pages_module, "parse", spy)

    source = corpus.path(FIXTURE)
    common = {"out_dir": None, "name_template": None, "policy": _policy()}
    extract_run([source], pages_spec="1,3", output=tmp_path / "e.pdf", **common)  # type: ignore[arg-type]
    reorder_run([source], pages_spec="1,3", output=tmp_path / "o.pdf", in_place=False, **common)  # type: ignore[arg-type]
    delete_run([source], pages_spec="1,3", output=tmp_path / "d.pdf", in_place=False, **common)  # type: ignore[arg-type]
    rotate_run(
        [source],
        pages_spec="1,3",
        angle=90,
        absolute=False,
        output=tmp_path / "r.pdf",
        in_place=False,
        **common,  # type: ignore[arg-type]
    )

    assert [ordered for _spec, ordered in seen] == [True, True, False, False]
    # AC24: the RAW `--pages` string, unmodified, once per input.
    assert {spec for spec, _ordered in seen} == {"1,3"}
    assert len(seen) == 4


def test_ac24_parse_is_called_exactly_once_per_input(
    corpus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pdf_toolkit.ops.pagerange as pagerange_module
    import pdf_toolkit.ops.pages as pages_module

    calls: list[str] = []
    real_parse = pagerange_module.parse

    def spy(spec: str, page_count: int, *, ordered: bool = False):
        calls.append(spec)
        return real_parse(spec, page_count, ordered=ordered)

    monkeypatch.setattr(pages_module, "parse", spy)

    source = corpus.path(FIXTURE)
    extract_run(
        [source, source, source],
        pages_spec="1,3",
        output=None,
        out_dir=tmp_path / "out",
        name_template="{index}.{ext}",
        policy=_policy(),
    )
    assert len(calls) == 3


@pytest.mark.parametrize("verb", PDF_08_VERBS)
def test_ac24_no_verb_carries_a_second_grammar_implementation(
    verb: str, corpus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC24 (replacement), the behavioural half: with the SHARED parser
    patched to raise, every verb fails and writes nothing.

    A verb carrying its own parser would survive this patch. Asserted this way
    rather than by grepping the source for the ABSENCE of a string, which
    asserts intent and can be satisfied by renaming a variable (X-113).
    """
    import pdf_toolkit.ops.pages as pages_module

    def refuse(spec: str, page_count: int, *, ordered: bool = False):
        raise PageRangeError(
            "patched",
            spec=spec,
            token="",  # nosec B106 -- the grammar's offending-token field
            column=1,
            reason="patched",
        )

    monkeypatch.setattr(pages_module, "parse", refuse)
    target = tmp_path / f"{verb}.pdf"
    runners = {
        "extract": lambda: extract_run(
            [corpus.path(FIXTURE)],
            pages_spec="1",
            output=target,
            out_dir=None,
            name_template=None,
            policy=_policy(),
        ),
        "delete": lambda: delete_run(
            [corpus.path(FIXTURE)],
            pages_spec="1",
            output=target,
            out_dir=None,
            name_template=None,
            in_place=False,
            policy=_policy(),
        ),
        "rotate": lambda: rotate_run(
            [corpus.path(FIXTURE)],
            pages_spec="1",
            angle=90,
            absolute=False,
            output=target,
            out_dir=None,
            name_template=None,
            in_place=False,
            policy=_policy(),
        ),
        "reorder": lambda: reorder_run(
            [corpus.path(FIXTURE)],
            pages_spec="1",
            output=target,
            out_dir=None,
            name_template=None,
            in_place=False,
            policy=_policy(),
        ),
    }
    with pytest.raises(PageRangeError) as caught:
        runners[verb]()
    assert caught.value.exit_code == 2
    assert not target.exists()


# --------------------------------------------------------------------------- #
# AC7/AC8/AC9 — `reorder`'s remainder rule, end to end
# --------------------------------------------------------------------------- #


def test_ac7_reorder_appends_the_remainder_in_ascending_original_order(
    corpus, tmp_path: Path
) -> None:
    target = tmp_path / "ac7.pdf"
    reorder_run(
        [corpus.path(FIXTURE)],
        pages_spec="last,1",
        output=target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    assert _page_numbers(target) == [10, 1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_ac9_an_exclusion_moves_a_page_to_the_back(corpus, tmp_path: Path) -> None:
    """`all,!3` over the ten-page fixture: page 3 is unnamed, so it is
    appended -- 1,2,4..10 then 3. It is NOT deleted."""
    target = tmp_path / "ac9.pdf"
    reorder_run(
        [corpus.path(FIXTURE)],
        pages_spec="all,!3",
        output=target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    assert _page_numbers(target) == [1, 2, 4, 5, 6, 7, 8, 9, 10, 3]


# --------------------------------------------------------------------------- #
# AC11/AC12/AC13 — `delete`, and the two "empty" cases that must not converge
# --------------------------------------------------------------------------- #


def test_ac11_delete_even_removes_the_1_based_even_pages(corpus, tmp_path: Path) -> None:
    """Asserted by IDENTITY, not by count: the count (5) is identical under the
    exactly-wrong parity implementation, so only the surviving page numbers
    catch the off-by-one."""
    target = tmp_path / "ac11.pdf"
    delete_run(
        [corpus.path(FIXTURE)],
        pages_spec="even",
        output=target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    assert _page_numbers(target) == [1, 3, 5, 7, 9]


def test_ac12_delete_refuses_to_produce_a_zero_page_document(corpus, tmp_path: Path) -> None:
    target = tmp_path / "ac12.pdf"
    with pytest.raises(RefusedError) as caught:
        delete_run(
            [corpus.path(FIXTURE)],
            pages_spec="all",
            output=target,
            out_dir=None,
            name_template=None,
            in_place=False,
            policy=_policy(),
        )
    assert caught.value.exit_code == 5
    assert "zero-page" in caught.value.message
    assert not target.exists()


def test_ac13_the_two_empty_cases_carry_different_exit_codes(corpus, tmp_path: Path) -> None:
    """An empty SELECTION is 4 ("nothing to act on"); a FULL selection under
    `delete` is 5 (a safety gate declining). §D5 exists so these can never
    converge, and this is what pins them apart."""
    source = corpus.path(FIXTURE)
    with pytest.raises(NoInputError) as empty:
        delete_run(
            [source],
            pages_spec="all,!all",
            output=tmp_path / "a.pdf",
            out_dir=None,
            name_template=None,
            in_place=False,
            policy=_policy(),
        )
    assert empty.value.exit_code == 4

    with pytest.raises(RefusedError) as full:
        delete_run(
            [source],
            pages_spec="1-10",
            output=tmp_path / "b.pdf",
            out_dir=None,
            name_template=None,
            in_place=False,
            policy=_policy(),
        )
    assert full.value.exit_code == 5


def test_ac13_an_empty_extract_selection_is_exit_4(corpus, tmp_path: Path) -> None:
    with pytest.raises(NoInputError) as caught:
        extract_run(
            [corpus.path("single_page")],
            pages_spec="even",
            output=tmp_path / "c.pdf",
            out_dir=None,
            name_template=None,
            policy=_policy(),
        )
    assert caught.value.exit_code == 4


# --------------------------------------------------------------------------- #
# AC14/AC15 — `rotate`, BOTH halves of every assertion (§D10)
# --------------------------------------------------------------------------- #


def test_ac14_rotate_changes_only_the_named_page(corpus, tmp_path: Path) -> None:
    """The positive half AND the negative half, over the whole document."""
    source = corpus.path(FIXTURE)
    target = tmp_path / "ac14.pdf"
    rotate_run(
        [source],
        pages_spec="1",
        angle=90,
        absolute=False,
        output=target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    before = _rotations(source)
    after = _rotations(target)
    assert after[0] == 90, "page 1 was not rotated"
    assert after[1:] == before[1:], "a page the selection did not name changed"
    assert _media_boxes(target) == _media_boxes(source), "rotation is metadata, not geometry"
    assert _page_numbers(target) == list(range(1, 11)), "rotate must not reorder or drop pages"


def test_ac14_an_absent_rotate_key_stays_absent(corpus, tmp_path: Path) -> None:
    """The negative half's sharpest edge, and the reason this test builds its
    own operand: reportlab writes an explicit `/Rotate 0` onto every page, so
    on a generated fixture "absent" is never observable and this property
    would pass vacuously (X-89's shape).

    Writing an explicit `/Rotate 0` onto untouched pages would preserve
    rendering while failing the "changes only page 1" guarantee -- which is
    precisely why the oracle here is key PRESENCE, not `PageInfo.rotation`
    (which reports 0 for both).
    """
    source = _strip_rotate(corpus.path(FIXTURE), tmp_path / "no-rotate.pdf")
    assert _rotations(source) == [None] * 10, "the stripped operand is not what this test needs"

    target = tmp_path / "ac14-absent.pdf"
    rotate_run(
        [source],
        pages_spec="1",
        angle=90,
        absolute=False,
        output=target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    after = _rotations(target)
    assert after[0] == 90
    assert after[1:] == [None] * 9, "an untouched page was stamped with an explicit /Rotate"


def test_ac4_a_duplicated_page_is_rotated_once(corpus, tmp_path: Path) -> None:
    """End-to-end AC4: `--pages '1,1' --angle 90` (relative) leaves page 1 at
    90, not 180."""
    target = tmp_path / "ac4.pdf"
    rotate_run(
        [corpus.path(FIXTURE)],
        pages_spec="1,1",
        angle=90,
        absolute=False,
        output=target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    assert _rotations(target)[0] == 90


@pytest.mark.parametrize(
    ("angle", "absolute", "expected"),
    [(90, False, 0), (-90, True, 270), (180, True, 180)],
)
def test_ac15_modular_normalization_against_a_pre_rotated_page(
    angle: int, absolute: bool, expected: int, corpus, tmp_path: Path
) -> None:
    """The `rotated` fixture's page 4 carries `/Rotate 270` (declared by its
    own FixtureSpec, so the operand and the expectation cannot drift)."""
    source = corpus.path("rotated")
    assert corpus.spec("rotated").rotations[3] == 270

    target = tmp_path / f"ac15-{angle}-{absolute}.pdf"
    rotate_run(
        [source],
        pages_spec="4",
        angle=angle,
        absolute=absolute,
        output=target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    after = _rotations(target)
    assert after[3] == expected
    assert after[:3] == _rotations(source)[:3], "an unnamed page changed"


# --------------------------------------------------------------------------- #
# AC22/AC39 — structural sanity and the `detail` seam
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", PDF_08_VERBS)
def test_ac39_the_reported_page_count_transition_matches_the_documents(
    verb: str, corpus, tmp_path: Path
) -> None:
    """X-107: `detail` is asserted against the RE-READ documents, never against
    the emitting code. A `detail` that disagrees with the document is the
    defect."""
    source = corpus.path(FIXTURE)
    target = tmp_path / f"{verb}.pdf"
    common = {
        "output": target,
        "out_dir": None,
        "name_template": None,
        "policy": _policy(),
    }
    if verb == "extract":
        result = extract_run([source], pages_spec="1,3", **common)  # type: ignore[arg-type]
    elif verb == "delete":
        result = delete_run([source], pages_spec="1", in_place=False, **common)  # type: ignore[arg-type]
    elif verb == "rotate":
        result = rotate_run(
            [source], pages_spec="1", angle=90, absolute=False, in_place=False, **common
        )  # type: ignore[arg-type]
    else:
        result = reorder_run([source], pages_spec="last,1", in_place=False, **common)  # type: ignore[arg-type]

    assert result.exit_code == 0
    detail = result.items[0].detail
    assert detail is not None
    assert detail["pages_before"] == len(_page_numbers(source)) == 10
    assert detail["pages_after"] == len(_page_numbers(target))


def test_ac39_rotate_reports_how_many_pages_it_actually_stamped(corpus, tmp_path: Path) -> None:
    target = tmp_path / "rot-detail.pdf"
    result = rotate_run(
        [corpus.path(FIXTURE)],
        pages_spec="1,1,3",
        angle=90,
        absolute=False,
        output=target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=_policy(),
    )
    detail = result.items[0].detail
    assert detail is not None
    changed = [
        index
        for index, (before, after) in enumerate(
            zip(_rotations(corpus.path(FIXTURE)), _rotations(target), strict=True)
        )
        if before != after
    ]
    assert detail["pages_rotated"] == len(changed) == 2


# --------------------------------------------------------------------------- #
# AC38 — X-76: the engine comes from `require_structure()`, by capability
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", PDF_08_VERBS)
def test_ac38_every_verb_acquires_its_engine_through_the_one_registry_seam(
    verb: str, corpus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asserted behaviourally: with `require_structure` patched to raise
    `EngineMissingError`, every verb surfaces exit 3. A second, by-name
    acquisition path would bypass the patch and is caught by it."""
    import pdf_toolkit.ops.pages as pages_module
    from pdf_toolkit.errors import EngineMissingError

    def refuse(*args: object, **kwargs: object):
        raise EngineMissingError("patched: no structure engine")

    monkeypatch.setattr(pages_module, "require_structure", refuse)
    target = tmp_path / f"{verb}.pdf"
    common = {
        "output": target,
        "out_dir": None,
        "name_template": None,
        "policy": _policy(),
    }
    with pytest.raises(EngineMissingError) as caught:
        if verb == "extract":
            extract_run([corpus.path(FIXTURE)], pages_spec="1", **common)  # type: ignore[arg-type]
        elif verb == "delete":
            delete_run([corpus.path(FIXTURE)], pages_spec="1", in_place=False, **common)  # type: ignore[arg-type]
        elif verb == "rotate":
            rotate_run(
                [corpus.path(FIXTURE)],
                pages_spec="1",
                angle=90,
                absolute=False,
                in_place=False,
                **common,  # type: ignore[arg-type]
            )
        else:
            reorder_run([corpus.path(FIXTURE)], pages_spec="1", in_place=False, **common)  # type: ignore[arg-type]
    assert caught.value.exit_code == 3
    assert not target.exists()


def test_ac38_ops_pages_never_names_an_adapter(corpus) -> None:
    """The companion negative control: `require_structure` is called with NO
    capability argument at all (`ops/pages.py` needs plain page-tree work, and
    a capability token here would be the second selection mechanism X-21 was
    written to prevent)."""
    del corpus
    import inspect

    import pdf_toolkit.ops.pages as pages_module

    source = inspect.getsource(pages_module)
    assert "require_structure()" in source
    assert "capability=" not in source
