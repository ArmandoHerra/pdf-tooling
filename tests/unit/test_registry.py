"""Unit tests for `tests/registry.py` — `discover_verbs()`, the structural
predicates, and the `reaches_atomic_writer` scan that stands in for the
literal (and, in this codebase, unsatisfiable) `is_mutating` predicate. See
`registry.py`'s module docstring for why.
"""

from __future__ import annotations

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import (  # noqa: E402
    INVOCATIONS,
    VerbSpec,
    discover_verbs,
    reaches_atomic_writer,
)


def test_discover_verbs_finds_exactly_the_thirteen_landed_verbs() -> None:
    """`compress`/`repair`/`linearize` (PDF-12) join `text`/`tables` (PDF-11),
    `compose`/`create` (PDF-10), `rasterize` (PDF-09), `merge`/`split`
    (PDF-07) and the three PDF-06-landing verbs -- thirteen total. Renamed
    and extended rather than deleted, for the fourth time and for the same
    reason: this pin fails BY DESIGN the moment a verb registers, which is
    the tripwire working, not a defect."""
    verbs = discover_verbs()
    names = {verb.name for verb in verbs}
    assert names == {
        "version",
        "doctor",
        "info",
        "merge",
        "split",
        "rasterize",
        "compose",
        "create",
        "text",
        "tables",
        "compress",
        "repair",
        "linearize",
    }


def test_discover_verbs_returns_no_duplicates() -> None:
    verbs = discover_verbs()
    names = [verb.name for verb in verbs]
    assert len(names) == len(set(names))


def test_info_is_the_only_verb_that_takes_input_paths() -> None:
    verbs = {verb.name: verb for verb in discover_verbs()}
    assert verbs["info"].takes_input_paths is True
    assert verbs["doctor"].takes_input_paths is False
    assert verbs["version"].takes_input_paths is False


def test_the_expected_verbs_are_classified_page_addressing_or_not() -> None:
    """AC24 (E13): `rasterize` (PDF-09) is the product's FIRST `--pages` verb
    -- the tripwire this pin exists to catch, firing as designed. Updated to
    an explicit named set, the same shape `test_the_expected_verbs_are_
    classified_mutating_or_not` already uses, so it keeps failing loudly on
    the next unclassified verb rather than silently passing forever. Was
    `test_no_current_verb_is_page_addressing`, asserting `is_page_addressing
    is False` for every verb -- that pin failed BY DESIGN the moment
    `rasterize` was registered, and is updated here rather than deleted."""
    # PDF-11: `text`/`tables` are `--pages` verbs (PLAN.md §4.1) and, with
    # `rasterize`, are the product's set-semantics verbs (§4.3) -- so the
    # page-addressing set grows and nothing in this pin is removed.
    # PDF-12: only `compress` is page-addressing -- `PLAN.md` §4.1 marks it
    # "(image pass)" (D-12.2's `--pages` scopes the image pass only);
    # `repair`/`linearize` are "no" (D-12.4/D-12.6), so both join
    # `expected_not` instead.
    expected_page_addressing = {"rasterize", "text", "tables", "compress"}
    expected_not = {
        "version",
        "doctor",
        "info",
        "merge",
        "split",
        "compose",
        "create",
        "repair",
        "linearize",
    }
    # PDF-10 extends `expected_not`: neither `compose` nor `create` is page
    # addressing (`PLAN.md` §4.1 -- both "no"), so the set grows and nothing in
    # this pin is removed.
    for verb in discover_verbs():
        if verb.name in expected_page_addressing:
            assert verb.is_page_addressing is True, f"{verb.name} should be page-addressing"
        elif verb.name in expected_not:
            assert verb.is_page_addressing is False, f"{verb.name} should not be page-addressing"
        else:  # pragma: no cover - a new verb landing without updating this pin
            raise AssertionError(f"{verb.name} is not in either expected set -- update this pin")


def test_the_expected_verbs_are_classified_mutating_or_not() -> None:
    """AC24/AC28 (B-031, E10/E12): `merge`/`split` (PDF-07) and `rasterize`
    (PDF-09) are the product's verbs that reach `AtomicWriter`, every one
    classified `is_mutating=True` through the EXISTING `_MAX_IMPORT_HOPS = 4`
    scan -- `cmd_merge -> ops.merge -> safety.atomic`, `cmd_split ->
    ops.split -> safety.atomic` and `cmd_rasterize -> ops.raster ->
    safety.atomic` are each two hops, well inside the bound, so the bound was
    never raised for any of the three (see this spec's Implementation Log).
    `compose`/`create` (PDF-10) join them at the SAME bound: `cmd_compose ->
    ops.compose -> safety.atomic` and `cmd_create -> ops.compose ->
    safety.atomic` are two hops each, so `_MAX_IMPORT_HOPS` was not raised for
    either (B-031 / AC26).
    `version`/`doctor`/`info` still write nothing.
    Was `test_no_current_verb_is_mutating`, asserting `is_mutating is False`
    for every verb -- that pin failed BY DESIGN the moment `merge`/`split`
    were registered (a tripwire, not a defect), and is updated here to the
    explicit expected set rather than deleted."""
    # PDF-11: `text`/`tables` are read verbs toward their INPUT but PRODUCING
    # verbs toward a destination, so both reach the chokepoint and both classify
    # mutating -- `cmd_text -> ops.textract -> safety.atomic` and `cmd_tables ->
    # ops.textract -> safety.atomic` are two hops each, so `_MAX_IMPORT_HOPS`
    # was not raised for either (B-031).
    # PDF-12: `compress`/`repair`/`linearize` each reach `AtomicWriter` via
    # `cmd_optimize -> ops.optimize -> safety.atomic` -- two hops each, so
    # `_MAX_IMPORT_HOPS` was not raised for any of the three.
    expected_mutating = {
        "merge",
        "split",
        "rasterize",
        "compose",
        "create",
        "text",
        "tables",
        "compress",
        "repair",
        "linearize",
    }
    expected_pure = {"version", "doctor", "info"}
    for verb in discover_verbs():
        if verb.name in expected_mutating:
            assert verb.is_mutating is True, f"{verb.name} should classify as mutating"
        elif verb.name in expected_pure:
            assert verb.is_mutating is False, f"{verb.name} should not classify as mutating"
        else:  # pragma: no cover - a new verb landing without updating this pin
            raise AssertionError(f"{verb.name} is not in either expected set -- update this pin")


def test_every_discovered_verb_is_registered_in_invocations() -> None:
    """The AC10 anti-lapse guard's own precondition, proven independently of
    `test_cli_contract.py::test_every_verb_is_registered` so a break in one
    location is caught by two."""
    names = {verb.name for verb in discover_verbs()}
    assert names - set(INVOCATIONS) == set()


def test_verb_spec_is_a_frozen_dataclass_with_the_documented_fields() -> None:
    verb = VerbSpec(
        name="x",
        path=("x",),
        is_group=False,
        takes_input_paths=False,
        is_page_addressing=False,
        is_mutating=False,
    )
    assert verb.name == "x"


# --------------------------------------------------------------------------- #
# `reaches_atomic_writer` -- proven with planted synthetic modules, the same
# negative-control discipline `tests/test_import_boundaries.py` uses.
# --------------------------------------------------------------------------- #


def test_reaches_atomic_writer_is_true_for_a_module_that_imports_it() -> None:
    assert reaches_atomic_writer("pdf_toolkit.safety.atomic") is True


def test_reaches_atomic_writer_is_false_for_the_three_non_mutating_cli_modules() -> None:
    for module in (
        "pdf_toolkit.cli.cmd_version",
        "pdf_toolkit.cli.cmd_doctor",
        "pdf_toolkit.cli.cmd_info",
    ):
        assert reaches_atomic_writer(module) is False, module


def test_reaches_atomic_writer_is_true_for_the_two_mutating_cli_modules() -> None:
    """AC28: `merge`/`split` (PDF-07) each reach the chokepoint through the
    EXISTING `_MAX_IMPORT_HOPS = 4` scan -- `cmd_merge -> ops.merge ->
    safety.atomic` and `cmd_split -> ops.split -> safety.atomic`, two hops
    each. The bound was never raised; see the Implementation Log."""
    for module in ("pdf_toolkit.cli.cmd_merge", "pdf_toolkit.cli.cmd_split"):
        assert reaches_atomic_writer(module) is True, module


def test_reaches_atomic_writer_is_false_for_an_unknown_module() -> None:
    assert reaches_atomic_writer("pdf_toolkit.this_module_does_not_exist") is False


def test_reaches_atomic_writer_follows_a_transitive_import_chain(
    tmp_path: Path, monkeypatch
) -> None:
    """A planted two-hop chain: cmd_fake -> ops_fake -> AtomicWriter, none of
    which import it directly -- proving the scan is transitive, not one-hop."""
    import registry

    fake_src = tmp_path / "src"
    (fake_src / "pdf_toolkit" / "cli").mkdir(parents=True)
    (fake_src / "pdf_toolkit" / "ops").mkdir(parents=True)
    (fake_src / "pdf_toolkit" / "cli" / "cmd_fake.py").write_text(
        "from pdf_toolkit.ops.ops_fake import do_it\n\n\ndef go():\n    return do_it()\n"
    )
    (fake_src / "pdf_toolkit" / "ops" / "ops_fake.py").write_text(
        "from pdf_toolkit.safety.atomic import AtomicWriter\n\n\n"
        "def do_it():\n    return AtomicWriter\n"
    )
    monkeypatch.setattr(registry, "SRC", fake_src)
    assert registry.reaches_atomic_writer("pdf_toolkit.cli.cmd_fake") is True


def test_reaches_atomic_writer_does_not_false_positive_on_an_unrelated_chain(
    tmp_path: Path, monkeypatch
) -> None:
    import registry

    fake_src = tmp_path / "src"
    (fake_src / "pdf_toolkit" / "cli").mkdir(parents=True)
    (fake_src / "pdf_toolkit" / "ops").mkdir(parents=True)
    (fake_src / "pdf_toolkit" / "cli" / "cmd_fake.py").write_text(
        "from pdf_toolkit.ops.ops_fake import do_it\n\n\ndef go():\n    return do_it()\n"
    )
    (fake_src / "pdf_toolkit" / "ops" / "ops_fake.py").write_text(
        "def do_it():\n    return 'no writer here'\n"
    )
    monkeypatch.setattr(registry, "SRC", fake_src)
    assert registry.reaches_atomic_writer("pdf_toolkit.cli.cmd_fake") is False
