"""AC23 — documentation, mechanized. ``merge --help``/``split --help`` are
this spec's documentation surface (Scope > Out: README.md/CLAUDE.md are
untouched, HC-5); every rule this spec defines is asserted here as a grep
over captured ``--help`` output, never left to a human to notice.
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path
from typing import Final

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import (  # noqa: E402
    PDF_08_VERBS,
    discover_verbs,
    run_cli,
    undeclared_expectations,
)

pytestmark = pytest.mark.e2e


def _help(verb: str) -> str:
    result = run_cli(verb, "--help")
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_merge_help_documents_path_range_and_the_colon_rule() -> None:
    text = _help("merge")
    assert "path:range" in text
    assert re.search(r"last colon", text)
    assert ":all" in text
    for mode in ("per-file", "preserve", "none"):
        assert mode in text


def test_split_help_documents_all_four_modes_and_the_comma_rule() -> None:
    text = _help("split")
    for flag in ("--every", "--ranges", "--each-page", "--at-bookmarks"):
        assert flag in text
    assert "comma" in text
    assert re.search(r"no top-level outline|exit 4", text)
    assert "each-page" in text and "{page}" in text


# --------------------------------------------------------------------------- #
# PDF-10 -- `compose --help` / `create --help` are this spec's documentation
# surface (Scope > Out: README.md and CLAUDE.md are untouched, HC-5). Every
# documentation rule the spec states is a grep over captured `--help` output.
# --------------------------------------------------------------------------- #


#: PDF-21/AC8 -- verb -> the dotted module whose ``PORT`` constant that verb's
#: ``--help`` must name. **The port name is READ FROM THE CODE, never typed
#: here**: a hand-written port-name literal would be exactly the
#: hand-maintained claim `0615feae63` was filed about, and a port rename would
#: leave it stale and still passing. `rasterize` joins the pattern PDF-10
#: established for `compose`/`create` rather than starting a second one
#: (X-157: consume the existing dimension, do not build a parallel one).
_VERB_PORT_MODULES: Final[dict[str, str]] = {
    "compose": "pdf_toolkit.ports.compose",
    "create": "pdf_toolkit.ports.compose",
    "rasterize": "pdf_toolkit.ports.raster",
}


@pytest.mark.parametrize("verb", sorted(_VERB_PORT_MODULES))
def test_ac1_these_verbs_name_the_port_they_depend_on(verb: str) -> None:
    port = importlib.import_module(_VERB_PORT_MODULES[verb]).PORT
    assert port, f"{_VERB_PORT_MODULES[verb]}.PORT is empty -- this check would be vacuous"
    assert port in _help(verb), (
        f"{verb} --help does not name {port!r}, the port it resolves. A user who "
        f"cannot see which engine a verb depends on cannot act on `doctor` output."
    )


def test_ac1_compose_help_documents_its_four_flags_and_the_lossless_contract() -> None:
    text = _help("compose")
    for flag in ("--page-size", "--fit", "--margin", "--dpi"):
        assert flag in text, flag
    for value in ("a4", "letter", "from-image", "contain", "cover", "stretch"):
        assert value in text, value
    # The guarantee is described as a capability, in the terms a user can check.
    assert re.search(r"byte-for-byte|byte for byte", text)
    assert "re-encode" in text
    assert "progressive" in text.lower()
    # Ordering and the no-globbing rule are documented, not folklore.
    assert "order the operands appear" in text
    assert "shell" in text


def test_ac1_create_help_documents_its_five_flags_and_the_stdin_contract() -> None:
    text = _help("create")
    for flag in ("--page-size", "--font", "--size", "--margin", "--title"):
        assert flag in text, flag
    assert "Helvetica" in text
    assert "standard input" in text
    assert "exit 4" in text
    assert "exit 2" in text
    assert "form feed" in text


def test_the_two_margin_defaults_are_documented_as_deliberately_different() -> None:
    assert "0" in _help("compose")
    assert "54pt" in _help("create")


# --------------------------------------------------------------------------- #
# PDF-08 -- `extract`/`delete`/`rotate`/`reorder --help` are this spec's
# documentation surface (Scope > Out: README.md and CLAUDE.md are untouched,
# HC-5 -- the verb-surface refresh is PDF-16 Phase B). AC10's rule is that the
# set-vs-ordered distinction is stated in EACH verb's own `--help`, and it is
# mechanized here as an exact-string grep rather than left to review.
#
# Compared on collapsed whitespace throughout: `--help` hard-wraps to the
# terminal width, so a literal `in text` check would assert the wrap position
# rather than the sentence.
# --------------------------------------------------------------------------- #

#: PDF-17/AC10 -- DERIVED. See `registry.PDF_08_VERBS`.
_PAGES_VERBS = PDF_08_VERBS

#: §D3's selection semantics per governed verb. A MAPPING keyed by the derived
#: dimension, not a pair of hand-typed tuples: `("extract", "reorder")` and
#: `("delete", "rotate")` were PARTIAL subsets of the verb list, which is worse
#: than a full stale tuple -- a rename leaves a partial subset both stale and
#: passing, with nothing to notice it. The totality test below is the tie.
_SELECTION_SEMANTICS: dict[str, object] = {
    "extract": "ordered",
    "delete": "set",
    "rotate": "set",
    "reorder": "ordered",
}
_ORDERED_VERBS = tuple(verb for verb in _PAGES_VERBS if _SELECTION_SEMANTICS.get(verb) == "ordered")
_SET_VERBS = tuple(verb for verb in _PAGES_VERBS if _SELECTION_SEMANTICS.get(verb) == "set")


def test_every_governed_verb_declares_its_selection_semantics() -> None:
    missing, stale = undeclared_expectations(_SELECTION_SEMANTICS, _PAGES_VERBS)
    assert (missing, stale) == ([], []), (
        f"_SELECTION_SEMANTICS is out of step with the derived verb dimension -- "
        f"missing={missing} stale={stale}"
    )
    assert _ORDERED_VERBS and _SET_VERBS, (
        "one of the two semantic partitions is empty -- the parametrized rows below would "
        "collect zero cases and pass vacuously"
    )


def _collapsed(verb: str) -> str:
    return " ".join(_help(verb).split())


@pytest.mark.parametrize("verb", _ORDERED_VERBS)
def test_ac10_the_ordered_verbs_say_so(verb: str) -> None:
    assert "order and duplicates are preserved" in _collapsed(verb)


@pytest.mark.parametrize("verb", _SET_VERBS)
def test_ac10_the_set_verbs_say_so(verb: str) -> None:
    assert "sorted, deduplicated set" in _collapsed(verb)


def test_ac10_reorder_states_the_remainder_rule() -> None:
    assert "pages you do not name are appended" in _collapsed("reorder")


def test_ac10_the_ordered_and_set_phrasings_never_overlap() -> None:
    """The negative half: an ordered verb must not ALSO claim set semantics,
    and vice versa. Without this, one copy-pasted help block could satisfy
    every positive grep above while telling the user the opposite of what the
    verb does."""
    for verb in _ORDERED_VERBS:
        assert "sorted, deduplicated set" not in _collapsed(verb), verb
    for verb in _SET_VERBS:
        assert "order and duplicates are preserved" not in _collapsed(verb), verb


def test_ac10_reorder_points_at_the_verbs_that_actually_drop_pages() -> None:
    """§D3: an exclusion in `reorder` means "move to the back", never
    "delete" -- surprising enough that the help must name the alternatives."""
    text = _collapsed("reorder")
    assert "delete" in text and "extract" in text


def test_rotate_help_names_the_accepted_angles_and_the_relative_default() -> None:
    text = _collapsed("rotate")
    for value in ("90", "180", "270", "-90"):
        assert value in text, value
    assert "--absolute" in text


def test_delete_help_documents_the_zero_page_refusal() -> None:
    text = _collapsed("delete")
    assert "exit 5" in text
    assert "zero-page" in text


# --------------------------------------------------------------------------- #
# PDF-14 -- `meta set --help`'s AC7 mechanized honesty clause: the sentence
# naming what `--clear-all` does NOT clear is a grep over captured `--help`
# output, never left to a human to notice.
# --------------------------------------------------------------------------- #


def test_ac7_meta_set_help_names_clear_all_and_its_uncleared_surfaces() -> None:
    text = _help("meta set")
    assert "--clear-all" in text
    lowered = text.lower()
    assert "page" in lowered
    assert "pieceinfo" in lowered
    assert "annotation" in lowered


def test_watermark_and_stamp_help_state_the_overlay_default() -> None:
    for verb in ("watermark", "stamp"):
        text = _collapsed(verb)
        assert "overlay" in text
        assert "'overlay' (default)" in text or "overlay (default)" in text.replace("'", "")


# --------------------------------------------------------------------------- #
# PDF-21 -- `rasterize --help` is this spec's documentation surface, and the
# three hand-typed forbidden-tool copies collapse into ONE derived check.
#
# AC14/D8: this file carried THREE copies of the same assertion over three
# hand-typed verb lists (`compose`/`create`, the four PDF-08 page verbs,
# `watermark`/`stamp`) -- eight verbs of the twenty-six the CLI actually
# exposes, and `rasterize` was in none of them, even though `rasterize`'s own
# first `--help` draft is the ONE that ever tripped the repository-wide
# forbidden-name scan. A fourth hand-typed copy would reproduce the exact
# anti-pattern, so the roster is DERIVED from `discover_verbs()` and a new verb
# is covered with zero author action.
# --------------------------------------------------------------------------- #

#: Every leaf verb on the LIVE command tree -- no hand-typed list, no skip list.
_ALL_VERBS: Final[tuple[str, ...]] = tuple(sorted(spec.name for spec in discover_verbs()))


def test_the_derived_verb_roster_is_neither_empty_nor_a_subset() -> None:
    """Non-vacuity for the parametrized check below: an empty or partial roster
    would collect zero (or eight of twenty-six) cases and pass by doing nothing,
    which is the failure mode the three hand-typed copies actually had."""
    live = discover_verbs()
    assert _ALL_VERBS, "discover_verbs() returned nothing -- the check below is vacuous"
    assert len(_ALL_VERBS) == len(live)
    assert "rasterize" in _ALL_VERBS
    for hand_typed in ("compose", "create", "watermark", "stamp", *PDF_08_VERBS):
        assert hand_typed in _ALL_VERBS, hand_typed


@pytest.mark.parametrize("verb", _ALL_VERBS)
def test_no_verb_help_names_a_forbidden_tool(verb: str) -> None:
    """The prohibition and the advertisement look identical to a grep, and this
    product's headline features reproduce forbidden tools' differentiators. So
    the capability is described and the tool is never named -- not in help text,
    not in a docstring, not in an error message."""
    from test_cli_spine import FORBIDDEN_NAMES

    lowered = _help(verb).lower()
    assert [name for name in FORBIDDEN_NAMES if name in lowered] == []


def _rasterize_help() -> str:
    return _collapsed("rasterize")


def test_ac9_rasterize_help_qualifies_the_single_channel_claim_for_webp() -> None:
    """`66f43b3123`: the help claimed, unqualified, that `--grayscale` renders
    single-channel output. For `--format webp` that is false -- WebP's bitstream
    has no single-channel pixel mode at all, so the file reads back as Pillow
    mode `RGB`. The OUTPUT is deliberately unchanged (forcing an approximation
    would be a silent behaviour change to a shipped verb); the CLAIM is
    qualified, and `webp` is named in the same statement so a reader cannot miss
    which format the exception is about."""
    text = _rasterize_help()
    assert "single-channel" in text
    qualification = text[text.index("single-channel") :]
    head = qualification[:400]
    assert "webp" in head, (
        f"the single-channel claim is not qualified for webp within the same statement: {head!r}"
    )
    assert "png" in head and "tiff" in head and "jpeg" in head, (
        f"the qualification does not say which formats DO get one channel: {head!r}"
    )


def test_ac12_rasterize_help_states_the_teardown_guarantee_per_platform() -> None:
    """X-153: the `PR_SET_PDEATHSIG` worker guard that closed `cb948ad85b` is
    Linux-only (`prctl` is a Linux syscall), while `macos-14` is a supported CI
    platform -- and a user reading `rasterize --help` saw no platform scope at
    all. Both halves are asserted: the catchable signals are POSIX-wide, and the
    uncatchable SIGKILL-to-parent case is Linux-only, with its reason."""
    text = _rasterize_help()
    for token in ("SIGTERM", "SIGINT", "SIGHUP"):
        assert token in text, token
    assert "POSIX" in text, "the catchable-signal guarantee names no platform scope"
    assert "SIGKILL" in text
    assert "Linux" in text and "macOS" in text, (
        "the SIGKILL-to-parent case is stated without naming the platform it "
        "does and does not hold on"
    )
    assert "PR_SET_PDEATHSIG" in text, "the reason for the Linux-only scope is not stated"


def test_pdf35_rasterize_help_names_the_pinned_start_method_and_keeps_the_macos_gap() -> None:
    """PDF-35 AC7 -- the CONTRACT half of the pin, which had no control at all.

    E7, re-derived: `test_ac12_rasterize_help_states_the_teardown_guarantee_per_platform`
    (immediately above) pins `SIGTERM`/`SIGINT`/`SIGHUP`/`POSIX`/`SIGKILL`/`Linux`/
    `macOS`/`PR_SET_PDEATHSIG`. **Every one of those tokens survives a corrected
    help text**, so that test stays green whether or not the help promises the
    `forkserver` gap -- and, symmetrically, would stay green if a future edit put
    the promise back. *A test that passes in both states of the thing it is named
    after is not a control.* This is the control.

    Three assertions, matching D6's three requirements on the corrected paragraph:

    1. **The forkserver promise is GONE.** Before PDF-35 the help told the user, as
       a shipped property, that SIGKILL coverage *"does not cover the 'forkserver'
       start method Python 3.14 makes the Linux default"*. The pool is pinned to
       `spawn` now, so that sentence is false in the user's favour -- which is
       still false.
    2. **The pinned start method is NAMED as the reason the Linux guarantee
       holds.** A help text that merely dropped the caveat would be quieter, not
       more honest; the user is owed the mechanism.
    3. **The macOS gap is STILL STATED.** `prctl` is a Linux syscall and macOS
       genuinely remains uncovered. Softening that would be an anti-gaming
       violation, and it is asserted here rather than trusted.
    """
    text = _rasterize_help()

    assert "forkserver" not in text, (
        "`rasterize --help` still promises the `forkserver` gap to the user. "
        "PDF-35 pinned the pool to `spawn` (ops/procpool.py::_START_METHOD), so "
        "that clause is now false -- and a help text making a false promise in "
        f"the user's favour is still a false promise. Help text:\n{text}"
    )

    assert "spawn" in text, (
        "the help does not name the pinned start method. Dropping the forkserver "
        "caveat without saying WHY the Linux guarantee now holds makes the text "
        "quieter rather than more honest: the reason the SIGKILL guarantee "
        "survives Python 3.14 is that this command pins `spawn` instead of "
        f"inheriting the interpreter default. Help text:\n{text}"
    )

    assert "macOS" in text, (
        "the macOS gap has been dropped from the help. PR_SET_PDEATHSIG is "
        "`prctl`, a Linux syscall with no macOS equivalent, so a SIGKILLed parent "
        "on macOS can still leave workers running. The pin did not close that "
        "half, and softening the contract to look finished is exactly the "
        f"anti-gaming violation PDF-35 D6 forbids. Help text:\n{text}"
    )
