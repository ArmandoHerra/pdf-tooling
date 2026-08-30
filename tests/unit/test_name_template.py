"""``safety/naming.py`` — the ``--name`` template renderer (Design §D6, AC8/AC9).

The binding invariant (§D6, verbatim): for every template and every set of
substituted values, rendering either **raises** a classified error, or
returns a path whose final component ``c`` is not one of ``""``, ``"."``,
``".."``; contains no ``/``, no ``os.sep``/``os.altsep``, and no NUL byte; is
not absolute; and whose parent, once both sides are resolved, is ``out_dir``
itself. AC8 asks for at least 1000 examples over templates and values drawn
from at least: ``../``, ``..\\``, ``/``, ``\\x00``, a leading ``/``, ``~``,
``.``, ``..``, the empty string, a >255-byte name, and ordinary names.
"""

from __future__ import annotations

import os
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pdf_toolkit.errors import OutputEscapesDirError
from pdf_toolkit.safety.naming import render_name, used_fields

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

_ordinary_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00/\\"),
    max_size=40,
)

_stem_strategy = st.one_of(st.sampled_from(_SEED_VALUES), _ordinary_text)

_templates = st.sampled_from(
    [
        "{stem}.{ext}",
        "{stem}-{index:03}.{ext}",
        "{stem}-{page:03}.{ext}",
        "{index:03}-{stem}.{ext}",
        "{stem}",
    ]
)


def _is_single_component(candidate: Path, *, out_dir: Path) -> bool:
    resolved_parent = candidate.resolve(strict=False).parent
    resolved_base = out_dir.resolve(strict=False)
    return resolved_parent == resolved_base


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
        return  # a raise satisfies the invariant -- nothing more to check
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
