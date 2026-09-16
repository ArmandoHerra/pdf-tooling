"""PDF-17 — every matrix dimension derives from the live registry or a live enum.

Three things live here, and they share one premise: **a dimension typed beside
the thing it describes is a stale-but-passing test waiting to happen.**

1. **AC30's mechanization (`e138934a60`).** `PDF-08`'s AC30 forbids a typed verb
   list *"anywhere in PDF-08's tests"*. Seven point fixes would have satisfied
   the letter of it and left the eighth site to arrive later; the ledger row
   itself undercounted (it said "three"). So the rule is MECHANIZED here
   instead: a scan that fails on any literal tuple/list/set of `PDF_08_VERBS`
   names anywhere under `tests/`.

2. **The dimension surface `PDF-22` consumes (X-157).** `output_formats()` and
   `tty_modes()` are pinned non-empty AND tied to a **different consumer** than
   the one that declares them, which is the only version of an "agreement"
   assertion that can fail — see `test_every_output_format_is_handled_by_the_renderer`.

3. **The scans' own red proofs**, in `tests/test_import_boundaries.py:481`'s
   idiom: *"Without these, the assertions above are a claim."*

WHY THE SCAN IS SCOPED BY VERB SET AND NOT BY MODULE ROSTER. A mechanized AC30
needs a declared set of things to scan, and a hand-maintained roster of "PDF-08's
test modules" is the same defect one level up. Two alternatives were measured
and rejected:

* **A structural predicate over the live registry.** There is none that isolates
  PDF-08's four: `is_page_addressing` returns ELEVEN verbs at this commit
  (`compress`, `delete`, `extract`, `ocr`, `rasterize`, `reorder`, `rotate`,
  `stamp`, `tables`, `text`, `watermark`).
* **A module roster derived from where violations are found.** It empties itself
  as the violations are fixed — a control that self-vacuates the moment it
  works, which is `PDF-06` AC6's defect with extra steps.

What is left is one declared verb set (`registry.PDF_08_VERBS`) with a LIVE tie
(`test_the_governed_verb_set_is_live`: every name must still be a discovered
verb), scanned over the whole `tests/` tree. Eleven hand-typed sites collapse to
one declaration that cannot go stale silently, and the scanned population gets
its own non-emptiness pin plus a proof that the detector detects.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Final

import pytest

from fs_snapshot import redirected_environment
from pdf_tooling.output import OutputFormat, auto_format
from registry import (
    ANCHORING_ABSOLUTE,
    ANCHORING_RELATIVE,
    DESTINATION_VALUE_FLAGS,
    OUTPUT_FLAG_INVOCATIONS,
    OUTPUT_FLAGS,
    PDF_08_VERBS,
    REPO_ROOT,
    destination_flag_cases,
    discover_verbs,
    output_formats,
    path_spellings,
    run_cli,
    tty_modes,
)

TESTS_DIR: Final[Path] = REPO_ROOT / "tests"

#: The ONE file allowed to declare `PDF_08_VERBS` as a literal: the declaration
#: site itself. AC30's purpose is that a verb rename cannot leave a passing
#: test; one declaration with a live membership tie achieves that, seven
#: scattered tuples with no tie do not.
DECLARATION_SITE: Final[Path] = TESTS_DIR / "registry.py"


# --------------------------------------------------------------------------- #
# The AC30 scan
# --------------------------------------------------------------------------- #


def typed_verb_collections(source: str, governed: frozenset[str]) -> list[tuple[int, str]]:
    """Every literal tuple/list/set in *source* that is a hand-typed collection
    of *governed* verb names.

    Two shapes are caught, because both appeared in the tree:

    * a collection of ≥2 string constants, all of them governed verb names
      (``("extract", "delete", "rotate", "reorder")``, and the PARTIAL subsets
      ``("extract", "reorder")`` / ``("delete", "rotate")`` -- a partial subset
      is WORSE than a full one, because a rename leaves it stale AND passing);
    * a collection of ≥2 tuple/list literals whose FIRST element is a governed
      verb name (``[("extract", 2), ("delete", 9), ...]`` -- a verb dimension
      carrying per-verb data).

    Dict literals are deliberately NOT caught. A mapping keyed by verb name is
    the shape AC10 blesses for per-verb *expectations*, and it is made
    un-stale by a TOTALITY assertion against the derived dimension
    (`registry.expectation`), which is a stronger tie than absence.
    """
    findings: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Tuple | ast.List | ast.Set):
            continue
        constants = [
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
        direct = [name for name in constants if name in governed]
        nested = [
            element.elts[0].value
            for element in node.elts
            if isinstance(element, ast.Tuple | ast.List)
            and element.elts
            and isinstance(element.elts[0], ast.Constant)
            and isinstance(element.elts[0].value, str)
            and element.elts[0].value in governed
        ]
        if len(direct) >= 2 and len(direct) == len(node.elts):
            findings.append((node.lineno, ast.unparse(node)))
        elif len(nested) >= 2:
            findings.append((node.lineno, ast.unparse(node)))
    return findings


def scanned_modules() -> tuple[Path, ...]:
    return tuple(sorted(TESTS_DIR.rglob("*.py")))


GOVERNED: Final[frozenset[str]] = frozenset(PDF_08_VERBS)


def test_the_governed_verb_set_is_live() -> None:
    """The tie that replaces eleven hand-typed sites. `PDF_08_VERBS` is a
    declaration, so it CAN go stale -- this is what stops it doing so
    silently. A renamed verb fails HERE, by name, instead of leaving seven
    tuples green and wrong."""
    live = {verb.name for verb in discover_verbs()}
    stale = sorted(GOVERNED - live)
    assert stale == [], (
        f"registry.PDF_08_VERBS names {stale}, which are no longer verbs on the live CLI "
        "tree -- the one declaration AC30 permits has gone stale, which is the exact "
        "failure the seven hand-typed tuples it replaced would have had"
    )
    assert len(GOVERNED) > 0, "PDF_08_VERBS is empty -- the AC30 scan would find nothing to scan"


def test_the_scan_sees_the_whole_test_tree() -> None:
    """Non-vacuity for the scan itself: a glob that matched nothing would make
    `test_no_typed_verb_list_survives_anywhere` pass by doing nothing -- the
    shape `PDF-06` AC6 has."""
    modules = scanned_modules()
    assert len(modules) >= 40, f"the AC30 scan visited only {len(modules)} module(s)"
    assert DECLARATION_SITE in modules


def test_no_typed_verb_list_survives_anywhere_under_tests() -> None:
    """AC30, mechanized rather than point-fixed seven times."""
    findings: list[str] = []
    for path in scanned_modules():
        if path == DECLARATION_SITE:
            continue
        for lineno, text in typed_verb_collections(path.read_text(encoding="utf-8"), GOVERNED):
            findings.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {text}")
    assert findings == [], (
        "hand-typed collection(s) of PDF-08 verb names sit beside the live registry, which "
        "PDF-08's AC30 forbids anywhere in its tests -- derive from "
        "`registry.PDF_08_VERBS` (and keep per-verb DATA as a mapping validated by "
        "`registry.expectation`):\n  " + "\n  ".join(findings)
    )


# --------------------------------------------------------------------------- #
# The dimension surface PDF-22 consumes (X-157)
# --------------------------------------------------------------------------- #


def test_output_formats_is_non_empty_and_derived() -> None:
    formats = output_formats()
    assert len(formats) > 0, "output_formats() is empty -- every consuming matrix collapses"
    assert set(formats) == set(OutputFormat), (
        "output_formats() no longer returns the live enum -- it must DERIVE from "
        "pdf_tooling.output.OutputFormat, never list its members"
    )


#: `render_payload`'s documented fall-through: the member reached by the final
#: bare `return`, rather than by an `if fmt is OutputFormat.X` arm. Exactly one
#: member may be the fall-through, and which one is pinned -- because the
#: fall-through is precisely where an unwired member goes to die quietly.
FALLTHROUGH_FORMAT: Final[OutputFormat] = OutputFormat.TABLE


def unhandled_output_formats(
    renderer_source: str,
    formats: Iterable[OutputFormat],
    fallthrough: OutputFormat = FALLTHROUGH_FORMAT,
) -> list[str]:
    """Enum members the renderer's own dispatch never names, excluding the one
    declared fall-through.

    THE AGREEMENT ASSERTION THAT CAN ACTUALLY FAIL. `set(output_formats()) ==
    set(OutputFormat)` -- which `PDF-17` AC12 asks for in terms -- is a
    TAUTOLOGY when `output_formats()` derives from the enum: both sides move
    together, so AC12's own prescribed red (add a member to the enum) cannot
    make it fire. That is `PDF-06` AC6's defect shape, in the spec written to
    end it, so the assertion is built against a DIFFERENT CONSUMER instead:
    `pdf_tooling.output.render_payload`, whose `if fmt is OutputFormat.X`
    dispatch silently falls through for any member it does not name. A renderer
    added to the enum and not wired there answers a `-o <new>` request with a
    TABLE and exit 0 -- a silent wrong answer with a success exit code -- and
    now fails by name.
    """
    named = {
        node.attr
        for node in ast.walk(ast.parse(renderer_source))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "OutputFormat"
    }
    return sorted(fmt.name for fmt in formats if fmt is not fallthrough and fmt.name not in named)


def fallthrough_renderer(renderer_source: str) -> str | None:
    """The function called by the renderer's FINAL `return` — the fall-through
    arm. Pinning it is what stops the declared `FALLTHROUGH_FORMAT` above from
    quietly disagreeing with the code."""
    for node in ast.walk(ast.parse(renderer_source)):
        if not isinstance(node, ast.FunctionDef):
            continue
        last = node.body[-1]
        if (
            isinstance(last, ast.Return)
            and isinstance(last.value, ast.Call)
            and isinstance(last.value.func, ast.Name)
        ):
            return last.value.func.id
    return None


def _render_payload_source() -> str:
    import inspect

    from pdf_tooling.output import render_payload

    return inspect.getsource(render_payload)


def test_every_output_format_is_handled_by_the_renderer() -> None:
    source = _render_payload_source()
    unhandled = unhandled_output_formats(source, output_formats())
    assert unhandled == [], (
        f"pdf_tooling.output.render_payload never names {unhandled} -- those OutputFormat "
        f"member(s) fall through to the {FALLTHROUGH_FORMAT.name} renderer silently. Wire "
        "the dispatch, or the product answers a `-o <new>` request with a table and exit 0."
    )
    assert fallthrough_renderer(source) == f"render_{FALLTHROUGH_FORMAT.value}", (
        f"render_payload's fall-through arm no longer calls "
        f"render_{FALLTHROUGH_FORMAT.value}(), so FALLTHROUGH_FORMAT "
        f"({FALLTHROUGH_FORMAT.name}) is now excused from the dispatch check for the wrong "
        "member -- and the member that IS excused is whichever one the code falls through "
        "to, not the one declared here"
    )


def test_tty_modes_is_the_two_valued_axis_it_claims_to_be() -> None:
    modes = tty_modes()
    assert len(modes) > 0, "tty_modes() is empty"
    assert set(modes) == {True, False}, f"tty_modes() is not the isatty axis: {modes}"


def collapsed_axis(outcome: Callable[[bool], object], modes: Sequence[bool]) -> bool:
    """Whether *outcome* returns the SAME value for every mode — i.e. whether
    the axis has collapsed and stopped being an axis at all."""
    return len({outcome(mode) for mode in modes}) < len(modes)


def test_the_tty_axis_still_changes_the_product_s_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`tty_modes()` is a declaration; this is its tie to the product. The two
    modes must produce two DIFFERENT default output formats, or the axis
    `PDF-22` is about to cross with `output_formats()` is decoration."""

    def outcome(interactive: bool) -> OutputFormat:
        monkeypatch.setattr(
            "pdf_tooling.output.sys.stdout", type("S", (), {"isatty": lambda self: interactive})()
        )
        return auto_format()

    assert not collapsed_axis(outcome, tty_modes()), (
        "auto_format() returns the same format on a TTY and off one -- the isatty axis has "
        "collapsed and tty_modes() no longer describes anything the product does"
    )


def test_the_registry_documents_the_surface_pdf_22_consumes() -> None:
    """X-157/AC13: `PDF-22` must CONSUME this surface rather than build a
    second one, and it can only do that if the surface is written down where
    its engineer will look — the registry's own module docstring."""
    import registry

    docstring = registry.__doc__ or ""
    for name in ("discover_verbs()", "OUTPUT_FLAGS", "output_formats()", "tty_modes()"):
        assert name in docstring, (
            f"tests/registry.py's module docstring does not name {name} as part of the "
            "dimension surface PDF-22 consumes (X-157)"
        )


# --------------------------------------------------------------------------- #
# Proof that the scans fire. Without these, the assertions above are a claim.
# --------------------------------------------------------------------------- #

PLANTED_VERB_COLLECTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("full-tuple", 'VERBS = ("extract", "delete", "rotate", "reorder")\n'),
    ("full-list", 'VERBS = ["extract", "delete", "rotate", "reorder"]\n'),
    ("partial-subset", 'ORDERED = ["extract", "reorder"]\n'),
    ("in-place-subset", 'IN_PLACE = ("delete", "rotate", "reorder")\n'),
    ("nested-with-data", 'CASES = [("extract", 2), ("delete", 9), ("rotate", 10)]\n'),
    ("set-literal", 'SEEN = {"delete", "rotate"}\n'),
)


@pytest.mark.parametrize(
    ("label", "source"), PLANTED_VERB_COLLECTIONS, ids=[row[0] for row in PLANTED_VERB_COLLECTIONS]
)
def test_a_planted_verb_collection_is_detected(label: str, source: str) -> None:
    assert typed_verb_collections(source, GOVERNED) != [], (
        f"the AC30 detector did not see the planted {label} -- reintroducing one of the "
        "eleven tuples this spec derived would go unnoticed"
    )


NOT_VIOLATIONS: Final[tuple[tuple[str, str], ...]] = (
    ("mixed-with-a-flag", 'ROW = ("extract", "--output")\n'),
    ("single-verb", 'ONE = ("extract",)\n'),
    ("mapping-keyed-by-verb", 'EXPECTED = {"extract": 2, "delete": 9}\n'),
    ("ungoverned-verbs", 'PAIR = ("text", "tables")\n'),
    ("derived", "VERBS = tuple(v.name for v in discover_verbs())\n"),
)


@pytest.mark.parametrize(
    ("label", "source"), NOT_VIOLATIONS, ids=[row[0] for row in NOT_VIOLATIONS]
)
def test_the_detector_does_not_cry_wolf(label: str, source: str) -> None:
    """The other half. A detector that flagged everything would be satisfied by
    every red proof above and would make the real scan unmaintainable, which is
    how a check gets deleted rather than fixed."""
    assert typed_verb_collections(source, GOVERNED) == [], label


def test_the_renderer_agreement_check_fires_on_an_unwired_member() -> None:
    """AC12's red, as a synthetic: a dispatch that drops an arm reports the
    member it dropped. Also run FOR REAL against a temporarily-added enum
    member -- PDF-17's Implementation Log carries the verbatim message."""
    partial = (
        "def render_payload(payload, fmt):\n"
        "    if fmt is OutputFormat.JSON:\n"
        "        return render_json(payload)\n"
        "    return render_table(payload)\n"
    )
    assert unhandled_output_formats(partial, output_formats()) == ["NDJSON"]
    # ...and the real renderer is clean, so the check is not simply always red.
    assert unhandled_output_formats(_render_payload_source(), output_formats()) == []


def test_the_fallthrough_pin_fires_when_the_final_arm_changes() -> None:
    """The other half: the fall-through member is EXCUSED from the dispatch
    check, so which member is excused must itself be pinned to the code."""
    moved = (
        "def render_payload(payload, fmt):\n"
        "    if fmt is OutputFormat.JSON:\n"
        "        return render_json(payload)\n"
        "    if fmt is OutputFormat.TABLE:\n"
        "        return render_table(payload)\n"
        "    return render_ndjson(payload)\n"
    )
    assert fallthrough_renderer(moved) == "render_ndjson"
    assert fallthrough_renderer(_render_payload_source()) == "render_table"


def test_the_collapsed_axis_check_fires() -> None:
    """The tty tie's own red: a function that ignores the mode collapses the
    axis and is reported as such."""
    assert collapsed_axis(lambda mode: "always-the-same", (True, False))
    assert not collapsed_axis(lambda mode: mode, (True, False))


# --------------------------------------------------------------------------- #
# PDF-17 -- AC32: `PDF-06`'s TWO BROKEN MECHANIZATIONS, repaired and EXECUTED.
#
# `PDF-06` AC5 and AC11 each carry a mechanized check written into a spec
# document. Both return the wrong answer at `2d19bcb`. Nobody noticed, because
# nothing ran them -- they are prose recipes, executed once by the implementing
# engineer and never again. That is the structural finding behind
# `AUDIT-CONVENTION(PDF-17)`, and the fix is not a better grep in a markdown
# file: it is a TEST.
#
#   AC5  -- `grep -nE 'SKIP|EXCLUDE|IGNORE' tests/registry.py` was required to
#           return NOTHING and returns TWO hits. Both are prose in docstrings
#           describing SKIP BEHAVIOUR; there is no skip list and the underlying
#           property HOLDS. The CHECK fails while the CLAIM is true -- a naive
#           uppercase substring scan, the same defect family as `B-026`'s naive
#           lowercase forbidden-name scan. Repaired below by scanning BINDINGS
#           rather than characters.
#
#   AC11 -- `grep -rn 'def snapshot_tree' tests/ src/ | wc -l` was required to
#           return `1` and returns `0`. The helper was renamed to `snapshot()`
#           (`tests/fs_snapshot.py:170`) and the AC's grep went on naming a
#           function that does not exist. Repaired below by asserting the
#           PROPERTY AC11 states -- exactly one tree-snapshot helper -- instead
#           of one spelling of its name.
# --------------------------------------------------------------------------- #

_SKIP_LIST_TOKENS: Final[tuple[str, ...]] = ("skip", "exclude", "ignore")


def skip_list_bindings(source: str) -> list[str]:
    """Names BOUND in *source* that look like a skip/exclude/ignore list.

    Bindings, not characters: a docstring that describes skip behaviour is not
    a skip list, and `PDF-06` AC5's own grep could not tell the two apart.
    Assignments, function parameters and comprehension targets are all bindings
    a real skip list would have to use.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        names: list[str] = []
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        elif isinstance(node, ast.arg):
            names = [node.arg]
        for name in names:
            lowered = name.lower()
            if any(token in lowered for token in _SKIP_LIST_TOKENS):
                found.append(name)
    return sorted(set(found))


def test_pdf_06_ac5_the_registry_carries_no_skip_list() -> None:
    """`PDF-06` AC5's property, mechanized so it is true AND checkable.

    AC5's own claim is that `discover_verbs()` walks the live tree with *"no
    skip list, no filter and no hard-coded verb name"*. The first two are what
    this asserts; the third is `test_no_typed_verb_list_survives_anywhere_under_tests`
    above, extended tree-wide.
    """
    source = DECLARATION_SITE.read_text(encoding="utf-8")
    bindings = skip_list_bindings(source)
    assert bindings == [], (
        f"tests/registry.py binds {bindings}, which read as a skip/exclude/ignore list. "
        "AC5's guarantee is that a verb registered on the live tree is covered the next "
        "time the suite runs, with no action from its author -- a skip list is the one "
        "thing that can take that away."
    )


def test_the_skip_list_scan_reads_bindings_and_not_prose() -> None:
    """The repair's own proof, in both directions -- and the second half is the
    half `PDF-06` AC5 got wrong."""
    assert skip_list_bindings("SKIP_VERBS = ('info',)\n") == ["SKIP_VERBS"]
    assert skip_list_bindings("def walk(exclude=None):\n    return exclude\n") == ["exclude"]
    # Prose describing skip BEHAVIOUR is not a skip list. AC5's grep returned
    # two hits on exactly this and called the property broken.
    assert skip_list_bindings('"""the consuming test SKIPS with a reason."""\n') == []
    assert skip_list_bindings("# reads it to SKIP those two checks visibly\nx = 1\n") == []


#: A tree-snapshot HELPER is a module-level function whose name IS a snapshot
#: name -- `snapshot`, `snapshot_tree`, `fs_snapshot` -- not one that merely
#: mentions snapshots. `PDF-06` AC11's grep was the opposite mistake, matching
#: exactly one spelling; matching every mention instead would flag this
#: module's own scanner and every test with "snapshot" in its name, and a check
#: that flags itself gets deleted rather than fixed.
_SNAPSHOT_HELPER = re.compile(r"^def (snapshot\w*|\w+_snapshot)\(", re.MULTILINE)


def tree_snapshot_helpers(roots: Sequence[Path]) -> list[str]:
    """Every module-level tree-snapshot helper under *roots*, as `path::name`."""
    found: list[str] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            try:
                label = path.relative_to(REPO_ROOT).as_posix()
            except ValueError:  # a synthetic tree under tmp_path, from the proof below
                label = path.name
            for name in _SNAPSHOT_HELPER.findall(path.read_text(encoding="utf-8")):
                found.append(f"{label}::{name}")
    return found


def test_pdf_06_ac11_exactly_one_tree_snapshot_helper_exists() -> None:
    """`PDF-06` AC11's PROPERTY, not one spelling of a function name.

    AC11's mechanization was `grep -rn 'def snapshot_tree' tests/ src/ | wc -l`
    returning `1`. The helper is `snapshot()`; the grep returns `0` and has
    done since the rename, with nothing to notice. Two purity helpers is the
    actual hazard AC11 names -- two definitions of "unchanged" that can
    disagree -- so that is what is asserted.
    """
    helpers = tree_snapshot_helpers([TESTS_DIR, REPO_ROOT / "src"])
    assert helpers == ["tests/fs_snapshot.py::snapshot"], (
        f"expected exactly one tree-snapshot helper, found {helpers}. Two definitions of "
        '"the tree is unchanged" can disagree, and every purity assertion in this suite '
        "is made through one of them."
    )


def test_the_snapshot_helper_scan_can_find_a_second_one(tmp_path: Path) -> None:
    """The repair's own proof: a planted second helper is reported, so the pin
    above is not green because the scan sees nothing."""
    (tmp_path / "planted.py").write_text(
        "def snapshot_tree(root):\n    return root\n", encoding="utf-8"
    )
    assert [entry.split("::")[-1] for entry in tree_snapshot_helpers([tmp_path])] == [
        "snapshot_tree"
    ]
    # And the narrowing is real rather than accidental: a function that merely
    # MENTIONS snapshots is not a second definition of "unchanged".
    (tmp_path / "mentions.py").write_text(
        "def tree_snapshot_helpers(roots):\n    return roots\n", encoding="utf-8"
    )
    assert [entry.split("::")[-1] for entry in tree_snapshot_helpers([tmp_path])] == [
        "snapshot_tree"
    ]


# --------------------------------------------------------------------------- #
# PDF-74 -- the VALUE-SHAPE axis, and the two guards a DECLARED dimension owes.
#
# `PATH_SPELLINGS` is a `tty_modes()`/`PDF_08_VERBS`-class member: declared,
# because the shapes a user can type are not enumerable from the command tree
# and inventing a spelling enum under `src/` to make a test derivable would be
# a product change made to serve a test. A declaration is admissible only with
# the two things those precedents carry, and both are below:
#
#   * THE TIE -- two distinct spellings of one destination must still produce
#     two distinct rendered payload values, at every `(verb, flag)` cell, or
#     something has absolutized at the boundary and the tuple describes
#     nothing. This is also the mechanization of the item's load-bearing
#     quantity: *the number of distinct spellings driven at a cell*, which was
#     ONE everywhere before `PDF-64` and TWO on eleven cells after it.
#   * THE SCAN -- `typed_verb_collections` is CONSUMED rather than copied: it
#     is already generic over the governed set, and the property is identical
#     (a literal collection of >=2 governed names, anywhere under `tests/`,
#     outside the one declaration site). A dimension each test re-enumerates is
#     not a dimension.
# --------------------------------------------------------------------------- #

SPELLING_IDS: Final[frozenset[str]] = frozenset(row.id for row in path_spellings())

DESTINATION_CELLS: Final[tuple[tuple[str, str], ...]] = destination_flag_cases()


def test_the_value_shape_axis_is_the_eight_member_axis_it_claims_to_be() -> None:
    rows = path_spellings()
    assert len(rows) > 0, "path_spellings() is empty -- every consuming matrix collapses"
    assert len(SPELLING_IDS) == len(rows), f"duplicate spelling id(s): {[r.id for r in rows]}"
    assert {row.anchoring for row in rows} == {ANCHORING_ABSOLUTE, ANCHORING_RELATIVE}, (
        "the anchoring field no longer takes both values -- the red control derives its "
        "predicted red set from it, so an axis that is all-absolute or all-relative makes "
        "that prediction unfalsifiable"
    )
    assert sum(1 for row in rows if row.anchoring == ANCHORING_ABSOLUTE) == 1, (
        "exactly one row is the absolute CONTROL column; more than one and the cross stops "
        "being a spelling axis crossed against a single reference"
    )


def test_the_declared_destination_flags_are_live_product_flags() -> None:
    """`DESTINATION_VALUE_FLAGS` is a scoping declaration, so it can go stale.
    This is what stops it doing so silently: a flag renamed under `src/` fails
    here by name instead of leaving a two-member axis quietly measuring one."""
    stale = sorted(set(DESTINATION_VALUE_FLAGS) - set(OUTPUT_FLAGS))
    assert stale == [], (
        f"registry.DESTINATION_VALUE_FLAGS names {stale}, which the product's own "
        f"OUTPUT_FLAGS {list(OUTPUT_FLAGS)} no longer declares"
    )


def test_the_spellings_driven_at_a_cell_is_the_whole_axis() -> None:
    """E4's load-bearing quantity, as a number the suite carries rather than a
    census someone re-greps.

    *The maximum, over all `(verb, flag)` cells, of the number of distinct
    spellings driven at that cell* was **one** everywhere before `PDF-64`,
    **two** on the eleven `--out-dir` cells after it, and is the whole axis now
    -- because `tests/integration/test_value_shape.py` parametrizes the full
    cross and a cell dropped from it fails that module's own cross-product
    assertion.
    """
    assert len(path_spellings()) == 8, (
        f"the value-shape axis has {len(path_spellings())} member(s); it was declared with "
        "eight, and a narrowing must be recorded IN CODE with the measurement that forced "
        "it, never absorbed here"
    )
    assert len(DESTINATION_CELLS) == 30, len(DESTINATION_CELLS)


def _destination_index(argv: list[str], flag: str) -> int:
    tokens = ("--output", "-O") if flag == "--output" else (flag,)
    return next(index for index, token in enumerate(argv) if token in tokens)


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("verb", "flag"),
    DESTINATION_CELLS,
    ids=[f"{verb.replace(' ', '-')}-{flag.lstrip('-')}" for verb, flag in DESTINATION_CELLS],
)
def test_the_value_shape_axis_still_changes_the_products_answer(
    verb: str, flag: str, corpus: object, tmp_path: Path
) -> None:
    """The TIE, and it is stronger than `tty_modes()`' because it runs against
    the live product at every cell rather than against one pure function.

    Two spellings of the SAME destination, driven under `--dry-run` so neither
    creates anything, must render two DIFFERENT destination values. If they
    ever render identically, the product has absolutized at the boundary --
    *"a payload change wearing a bug fix's clothes"* -- and this whole axis
    describes nothing, while every cell in the matrix keeps passing.
    """
    absolute = next(row for row in path_spellings() if row.anchoring == ANCHORING_ABSOLUTE)
    relative = next(row for row in path_spellings() if row.anchoring == ANCHORING_RELATIVE)

    anchor = tmp_path / "cell"
    anchor.mkdir()
    env, _roots = redirected_environment(anchor)
    registered = OUTPUT_FLAG_INVOCATIONS[(verb, flag)](corpus, anchor)
    index = _destination_index(registered, flag)
    leaf = Path(registered[index + 1]).name

    def outcome(row: object) -> str:
        value = row.render(anchor, leaf)  # type: ignore[attr-defined]
        argv = [*registered[: index + 1], value, *registered[index + 2 :]]
        dry = run_cli(
            verb,
            "--dry-run",
            *argv,
            "-o",
            "json",
            cwd=row.cwd(anchor),  # type: ignore[attr-defined]
            env=env,
        )
        assert dry.stdout.strip(), f"{verb} {flag}: the dry run printed nothing -- {dry.stderr}"
        payload = json.loads(dry.stdout)
        items = payload.get("items") or []
        rendered = items[0].get("output") if items else None
        if rendered is None:
            error = payload.get("error") or {}
            rendered = error.get("path")
        assert rendered is not None, f"{verb} {flag}: the payload named no destination"
        return str(rendered)

    assert not collapsed_axis(outcome, (absolute, relative)), (
        f"{verb} {flag}: an absolute and a relative spelling of the SAME destination render "
        "the IDENTICAL payload value, so the value-shape axis has collapsed and "
        "path_spellings() no longer describes anything the product does. The likely cause "
        "is an absolutization at the CLI boundary -- a payload change wearing a bug fix's "
        "clothes"
    )


def test_the_value_shape_collapse_check_fires() -> None:
    """The tie's own red, synthetic: a renderer that ignores the spelling
    collapses the axis and is reported as collapsed."""
    rows = path_spellings()[:2]
    assert collapsed_axis(lambda row: "always-the-same", rows)
    assert not collapsed_axis(lambda row: row.id, rows)


def test_no_typed_spelling_list_survives_anywhere_under_tests() -> None:
    """AC3. The same mechanism AC30 already has, pointed at the new dimension
    -- `typed_verb_collections` is generic over its governed set, so this
    CONSUMES the detector rather than growing a second one that can disagree
    with it."""
    findings: list[str] = []
    for path in scanned_modules():
        if path == DECLARATION_SITE:
            continue
        for lineno, text in typed_verb_collections(path.read_text(encoding="utf-8"), SPELLING_IDS):
            findings.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {text}")
    assert findings == [], (
        "hand-typed collection(s) of PATH_SPELLINGS ids sit beside the live declaration -- "
        "consume `registry.path_spellings()` instead. A dimension each test re-enumerates is "
        "not a dimension, it is eight tuples waiting to go stale:\n  " + "\n  ".join(findings)
    )


PLANTED_SPELLING_COLLECTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("full-tuple", "S = ('absolute', 'bare-relative', 'dot-relative', 'tilde')\n"),
    ("partial-subset", "RELATIVE = ['tilde', 'symlink']\n"),
    ("set-literal", "SEEN = {'tilde', 'trailing-slash'}\n"),
    ("nested-with-data", "CASES = [('tilde', 0), ('symlink', 1), ('absolute', 2)]\n"),
)


@pytest.mark.parametrize(
    ("label", "source"),
    PLANTED_SPELLING_COLLECTIONS,
    ids=[row[0] for row in PLANTED_SPELLING_COLLECTIONS],
)
def test_a_planted_spelling_collection_is_detected(label: str, source: str) -> None:
    assert typed_verb_collections(source, SPELLING_IDS) != [], (
        f"the AC3 detector did not see the planted {label} -- a re-listed value-shape axis "
        "would go unnoticed, which is the defect the declaration exists to avoid"
    )


NOT_SPELLING_VIOLATIONS: Final[tuple[tuple[str, str], ...]] = (
    ("mixed-with-a-flag", "ROW = ('tilde', '--out-dir')\n"),
    ("single-spelling", "ONE = ('tilde',)\n"),
    ("mapping-keyed-by-spelling", "EXPECTED = {'tilde': 1, 'symlink': 0}\n"),
    ("derived", "IDS = tuple(row.id for row in path_spellings())\n"),
)


@pytest.mark.parametrize(
    ("label", "source"),
    NOT_SPELLING_VIOLATIONS,
    ids=[row[0] for row in NOT_SPELLING_VIOLATIONS],
)
def test_the_spelling_detector_does_not_cry_wolf(label: str, source: str) -> None:
    """The other half. A detector that flagged everything would be satisfied by
    every red proof above and would make the real scan unmaintainable, which is
    how a check gets deleted rather than fixed."""
    assert typed_verb_collections(source, SPELLING_IDS) == [], label


def test_the_registry_documents_the_value_shape_surface_too() -> None:
    """X-157, applied to the new members: a surface can only be CONSUMED rather
    than rebuilt if it is written down where its next engineer will look."""
    import registry

    docstring = registry.__doc__ or ""
    for name in ("path_spellings()", "destination_flag_cases()"):
        assert name in docstring, (
            f"tests/registry.py's module docstring does not name {name} as part of the "
            "dimension surface a later matrix is meant to consume"
        )
