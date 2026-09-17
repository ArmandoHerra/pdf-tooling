"""``safety/naming.py`` — the ``--name`` template renderer (Design §D6, AC8/AC9).

The binding invariant (§D6, verbatim): for every template and every set of
substituted values, rendering either **raises** a classified error, or
returns a path whose final component ``c`` is not one of ``""``, ``"."``,
``".."``; contains no ``/``, no ``os.sep``/``os.altsep``, and no NUL byte; is
not absolute; and whose parent, once both sides are resolved, is ``out_dir``
itself. AC8 asks for at least 1000 examples over templates and values drawn
from at least: ``../``, ``..\\``, ``/``, ``\\x00``, a leading ``/``, ``~``,
``.``, ``..``, the empty string, a >255-byte name, and ordinary names.

**PDF-77 — what changed, and why the search now reaches further.** The
generator used to draw stems from an alphabet that blacklisted the NUL byte,
``/`` and ``\\`` and capped at forty characters, so four of the renderer's
five refusal branches were unreachable from it and the property only ever
exercised the ones ordinary text can reach. Three things now hold instead:

* the seed roster is **guaranteed**, not sampled. Every value in
  ``_SEED_VALUES`` runs under every template in ``_TEMPLATES`` on every run,
  as explicit examples built from the two rosters rather than transcribed
  (``Phase.explicit`` is in the default phase list, which is what makes an
  ``@example`` guaranteed). A seed added without a matching example fails by
  name in the meta-arm below instead of quietly never running;
* ``_hostile_text`` sits beside ``_ordinary_text`` rather than replacing it,
  and admits path separators, leading separators and components long enough
  that no filesystem will take them. It deliberately does **not** admit the
  NUL byte: that branch has exactly the one trigger condition and no
  interaction with template shape, so sampling it would buy nothing and would
  cost the suite its one deterministic red control;
* the property records whether each example was refused or returned
  (``--hypothesis-show-statistics``), because widening a generator raises the
  share of examples that take the early ``return`` where nothing is asserted,
  and a property whose interesting branch has quietly become rare is a
  vacuous control with excellent branding.

The profile that makes a failure here recoverable — ``print_blob`` and a
persisted example database outside the repository tree — lives in
``tests/conftest.py`` and reaches this module because pytest imports that file
before any test module. It used to reach here only because
``tests/test_pagerange.py`` sorts earlier during collection (``B-147``).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

import pytest  # noqa: E402
from hypothesis import HealthCheck, Phase, event, example, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402
from hypothesis.database import DirectoryBasedExampleDatabase  # noqa: E402

import conftest  # noqa: E402
from pdf_tooling.errors import OutputEscapesDirError  # noqa: E402
from pdf_tooling.safety.naming import render_name, used_fields  # noqa: E402

#: AC8's own named seed values, always included alongside hypothesis-generated
#: ordinary text — the property must hold on the adversarial values named in
#: the spec, not merely on whatever hypothesis happens to draw.
_SEED_VALUES = (
    "../",
    "..\\",
    "/",
    "\x00",
    "/leading",
    "~",
    ".",
    "..",
    "",
    "a" * 300,
    "ordinary-name",
)

#: The template roster, lifted out of the strategy so ONE roster feeds both
#: the generator and the explicit examples (PDF-77 D6). Listing the shapes
#: twice is how a seed ends up guaranteed under four templates and missing
#: under the fifth, with nothing able to say so.
_TEMPLATES: Final[tuple[str, ...]] = (
    "{stem}.{ext}",
    "{stem}-{index:03}.{ext}",
    "{stem}-{page:03}.{ext}",
    "{index:03}-{stem}.{ext}",
    "{stem}",
)

_templates = st.sampled_from(_TEMPLATES)

_ordinary_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00/\\"),
    max_size=40,
)

#: Both spellings, so the strategy is correct on a platform where `os.sep` is
#: the backslash and `os.altsep` the forward slash as well as on this one.
_SEPARATORS = st.sampled_from(("/", "\\"))

#: Deliberately adversarial component text, kept OUT of `_ordinary_text` on
#: purpose: a strategy called *ordinary* that draws separators and 300-byte
#: components is a name that lies to its next reader, and the two need
#: different size caps — forty characters is the right cap for ordinary text
#: and cannot reach a byte limit at all.
#:
#: Note that raising a CHARACTER cap is not the same as reaching a BYTE limit:
#: `st.text(max_size=n)` counts characters, and hypothesis biases hard toward
#: short draws, so a long free-form text strategy reaches an over-length
#: component approximately never. The over-long shape below is therefore built
#: rather than hoped for, and AC11's probe counts what it actually reaches.
_hostile_text = st.one_of(
    st.builds(
        lambda left, sep, right: f"{left}{sep}{right}",
        _ordinary_text,
        _SEPARATORS,
        _ordinary_text,
    ),
    st.builds(lambda sep, rest: f"{sep}{rest}", _SEPARATORS, _ordinary_text),
    st.builds(
        lambda char, count: char * count,
        st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00/\\"),
        st.integers(min_value=300, max_value=400),
    ),
)

#: The seeds are NOT a branch here, and that is deliberate (a declared
#: deviation from the spec's §D7 sentence, which offers them as one). They are
#: guaranteed by `@example` instead, which is strictly stronger than sampling
#: them — and leaving them in the generator as well would make the NUL byte
#: generator-reachable, which is precisely what AC14 requires it not to be:
#: a control that reds whether or not the seeds are pinned proves nothing
#: about pinning.
_stem_strategy = st.one_of(_ordinary_text, _hostile_text)

#: The vacuity meter's two outcomes, named once so the strings cannot drift
#: between the emit sites and whatever reads `--hypothesis-show-statistics`.
_REFUSED: Final[str] = "render_name refused the rendered component"
_RETURNED: Final[str] = "render_name returned a contained component"


def _guaranteed_seed_examples(test: Callable[..., None]) -> Callable[..., None]:
    """Pin every seed under every template — the cross-product, DERIVED.

    A seed roster without the template it bites under is a roster of
    near-misses: only ``"{stem}"`` renders the component as the seed verbatim,
    so under ``"{stem}.{ext}"`` the seed ``".."`` renders ``"...pdf"``, which
    refuses nothing. Taking the cross-product means nobody has to reason about
    which pairing bites, and a twelfth seed value or a sixth template extends
    the guaranteed set with no second edit — which AC8 demonstrates by
    extension rather than asserting.
    """
    for stem in _SEED_VALUES:
        for template in _TEMPLATES:
            test = example(template=template, stem=stem)(test)
    return test


def _is_single_component(candidate: Path, *, out_dir: Path) -> bool:
    resolved_parent = candidate.resolve(strict=False).parent
    resolved_base = out_dir.resolve(strict=False)
    return resolved_parent == resolved_base


def _the_filesystem_accepts(candidate: Path, *, out_dir: Path) -> None:
    """A behavioural oracle for the byte-length refusal, not a copy of it.

    The over-length branch is the one refusal the containment assertions
    cannot observe: raise the product's byte limit so an over-long component
    is RETURNED and every one of them stays green, because none of them
    asserts anything about length. Transcribing the product's own limit here
    would pin the constant to itself. Creating the file asks the filesystem
    instead — which is the authority the limit exists to keep the product away
    from — inside this test's own `tmp_path`, and removes it again.
    """
    try:
        candidate.touch()
    except OSError as error:
        encoded = len(candidate.name.encode("utf-8", "surrogateescape"))
        raise AssertionError(
            f"render_name returned a component of {encoded} bytes that the filesystem "
            f"under {out_dir} refuses ({error}); the renderer handed a name to a caller "
            "that AtomicWriter could only fail on with a bare OSError"
        ) from error
    candidate.unlink()


@_guaranteed_seed_examples
@given(template=_templates, stem=_stem_strategy)
@settings(
    max_examples=1000,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_render_name_either_raises_or_returns_a_single_contained_component(
    tmp_path: Path, template: str, stem: str
) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    try:
        candidate = render_name(
            template, out_dir=out_dir, stem=stem, ext="pdf", index=1, page=1, range_text="1"
        )
    except OutputEscapesDirError:
        event(_REFUSED)
        return  # a raise satisfies the invariant -- nothing more to check
    event(_RETURNED)
    name = candidate.name
    assert name not in ("", ".", "..")
    assert "/" not in name
    if os.sep and os.sep != "/":
        assert os.sep not in name
    if os.altsep:
        assert os.altsep not in name
    assert "\x00" not in name
    assert not os.path.isabs(name)
    assert _is_single_component(candidate, out_dir=out_dir)
    _the_filesystem_accepts(candidate, out_dir=out_dir)


def test_every_seed_value_is_guaranteed_under_every_template() -> None:
    """AC7. The seeds are pinned, and the pinning is checked STRUCTURALLY.

    Reading the decorated function's own explicit-example list, rather than
    reading the source or counting decorators by eye, is what makes "adding a
    seed without a matching example" fail by name instead of silently
    shrinking the guaranteed set.
    """
    property_under_test = test_render_name_either_raises_or_returns_a_single_contained_component
    examples = getattr(property_under_test, "hypothesis_explicit_examples", [])
    assert examples, (
        "the property carries NO explicit examples, so every adversarial value in "
        "_SEED_VALUES is merely sampled -- AC7's whole point is that they are not"
    )
    stems = {entry.kwargs["stem"] for entry in examples}
    assert stems == set(_SEED_VALUES), (
        "the guaranteed stem set is not the seed roster; missing "
        f"{sorted(set(_SEED_VALUES) - stems)!r}, unexpected {sorted(stems - set(_SEED_VALUES))!r}"
    )
    templates = {entry.kwargs["template"] for entry in examples}
    assert templates == set(_TEMPLATES), (
        "the guaranteed template set is not the template roster; a seed pinned under "
        "some templates and not others is a near-miss wearing a guarantee"
    )
    assert len(examples) == len(_SEED_VALUES) * len(_TEMPLATES), (
        f"{len(examples)} explicit examples for {len(_SEED_VALUES)} seeds x "
        f"{len(_TEMPLATES)} templates -- the cross-product is the contract, so this is "
        "either a duplicate pairing or a missing one"
    )


def test_the_conftest_profile_reaches_this_modules_property() -> None:
    """AC4. The profile supplies only what the decorator does not set.

    This is the load-bearing assumption of the whole arrangement: a profile
    loaded in `tests/conftest.py` must be in force when THIS module's
    `@settings(...)` decorator is evaluated, so the decorator keeps its own
    `max_examples` and `deadline` while inheriting the database and the blob
    setting. Asserting both halves means a profile that started carrying
    `max_examples` would be caught here rather than silently halving the
    search.
    """
    property_under_test = test_render_name_either_raises_or_returns_a_single_contained_component
    configured = property_under_test._hypothesis_internal_use_settings
    assert configured.print_blob is True, (
        "print_blob is off, so a property failure prints no @reproduce_failure token "
        "and a counterexample found on one CI leg is observed once and lost"
    )
    assert isinstance(configured.database, DirectoryBasedExampleDatabase), (
        f"the example database is {type(configured.database).__name__}; an in-memory "
        "database is discarded at process exit, so Phase.reuse has nothing to replay"
    )
    assert Path(configured.database.path) == conftest.HYPOTHESIS_DATABASE_DIR
    assert Phase.explicit in configured.phases, "no @example above would be guaranteed"
    assert Phase.reuse in configured.phases, "a persisted counterexample would never replay"
    assert configured.max_examples == 1000, "the decorator's own value did not survive"
    assert configured.deadline is None, "the decorator's own value did not survive"


def test_the_resolved_example_database_sits_outside_the_repository_tree() -> None:
    """AC3. The database persists, so WHERE it persists is the whole question."""
    database_dir = conftest.HYPOTHESIS_DATABASE_DIR
    assert not database_dir.is_relative_to(conftest.REPO_ROOT), (
        f"the example database resolves to {database_dir}, inside the repository at "
        f"{conftest.REPO_ROOT} -- that is B-147 under a different name"
    )
    assert database_dir.is_dir(), (
        f"{database_dir} does not exist, so the path the run header names is not a "
        "place a reader can go and look, and a persisted counterexample has nowhere "
        "to land"
    )


def test_a_database_path_inside_the_repository_is_refused_not_relocated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC3's red half. A misconfiguration must fail loudly, never fall back.

    Silently relocating a hostile `PDF_TOOLING_HYPOTHESIS_DB` to somewhere
    safe would leave the operator believing the database is where they pointed
    it; refusing at resolution time is the only answer that cannot be
    mistaken for success.
    """
    monkeypatch.setenv(conftest.HYPOTHESIS_DB_ENV, str(conftest.REPO_ROOT / ".hypothesis"))
    with pytest.raises(RuntimeError, match="INSIDE"):
        conftest.hypothesis_database_dir()


def test_used_fields_finds_every_referenced_token() -> None:
    assert used_fields("{stem}-{page:03}.{ext}") == {"stem", "page", "ext"}
    assert used_fields("{stem}-{index:03}.{ext}") == {"stem", "index", "ext"}
    assert used_fields("{stem}.{ext}") == {"stem", "ext"}
    assert used_fields("no-fields-here") == set()


def test_ext_renders_without_a_leading_dot(tmp_path: Path) -> None:
    out_dir = tmp_path
    rendered = render_name("{stem}.{ext}", out_dir=out_dir, stem="a", ext=".pdf")
    assert rendered.name == "a.pdf"
    assert ".." not in rendered.name.split(".")


def test_range_renders_the_resolved_extent_not_raw_range_text(tmp_path: Path) -> None:
    """A comma, `!`, or `/` in the user's raw expression must never reach a
    filename -- `{range}` renders the resolved extent (e.g. "1-3"), which is
    computed by the caller and handed in as plain text, never the original
    page-range spec string."""
    rendered = render_name(
        "{stem}-{range}.{ext}",
        out_dir=tmp_path,
        stem="doc",
        ext="pdf",
        range_text="1-3",
    )
    assert rendered.name == "doc-1-3.pdf"


def test_page_outside_each_page_is_a_caller_concern_not_this_modules(tmp_path: Path) -> None:
    """render_name itself has no opinion on which mode a template is valid
    for -- that vocabulary rule is Design §D6's "verb's concern", enforced by
    `ops/split.py` using `used_fields()` before this function is ever called.
    Passing `page=None` while the template references `{page}` therefore
    surfaces as this module's own generic unavailable-field refusal."""
    try:
        render_name("{page}.{ext}", out_dir=tmp_path, stem="a", ext="pdf", page=None)
    except OutputEscapesDirError:
        pass
    else:  # pragma: no cover - documents the contract, never expected to run
        raise AssertionError("expected an OutputEscapesDirError for an unavailable field")


def test_collision_two_distinct_stems_still_only_refused_by_the_caller(tmp_path: Path) -> None:
    """`ensure_within` is the containment half; render_name never checks
    against sibling outputs -- that is `check_output_collisions`'s job at the
    `ops/split.py` planning stage (AC10), and is proven there, not here."""
    first = render_name("{stem}.{ext}", out_dir=tmp_path, stem="a", ext="pdf")
    second = render_name("{stem}.{ext}", out_dir=tmp_path, stem="a", ext="pdf")
    assert first == second
