"""PDF-48/PDF-57 -- the thirteen-spelling reconciliation, and the census the
shipped brand classifier does not (and structurally cannot) own.

`tests/test_brand_surfaces.py` classifies exactly ONE spelling of the old
name -- the hyphenated one, assembled at runtime so the module never spells
it and inflates the very population (class H, `tests/`) it exists to
measure. That module's own docstring explains why a multi-needle version of
the same trick does not generalise: a classifier that must not spell any of
several needles, over a population in the thousands across a hundred files,
in one file, is not a widening -- it is a rewrite that keeps the old name.

So this module owns a DIFFERENT property: that the spellings this item's
Evidence section (E1/E10) counted are ALL of the spellings that exist, and
that summing their occurrence counts reproduces the live case-insensitive
total with NO residual. A spelling this module does not already expect,
appearing anywhere in the tree, is a FAILURE naming it, never a silent skip
-- which is the whole point of a reconciliation instrument: there is no seam
where an occurrence can hide.

PDF-57 (2026-09-12) widens the family this module polices from EIGHT
spellings to THIRTEEN: `PDF-48` froze the eight lower-tier spellings of the
OLD stem ("toolkit"); `PDF-57` retires the two upper-tier ones ("the
environment-variable-cased form", "the exception-class-cased form" plus its
logo-import sibling) to the corresponding NEW stem ("tooling"), joining
three NEW-stem spellings that already existed before this item landed (the
underscore-separated, no-separator and hyphenated forms of the NEW name --
`PDF-48`'s own package/console-script/distribution renames). **One census,
both eras, bucketed by exact matched spelling, zero residual** (D5) -- the
family regex widens from `pdf[-_ ]?toolkit` to `pdf[-_ ]?tool(kit|ing)` so
the two names this rename actually moves stay inside the one instrument that
watches for a stray occurrence, rather than exiting it unwatched.

This module also owns the two named remainder censuses PDF-48's AC10
predicts (one per moving spelling) and the four frozen-population byte
counts AC26 requires, because `test_the_corpus_and_golden_name_strings_are_
byte_identical` (in `test_cli_spine.py`) being green is explicitly NOT
accepted as evidence a frozen population survived a tree-wide sweep -- that
arm is blind to a sweep that moves the producer, the golden AND the oracle
together (`B-237`), and PDF-48 sweeps `tests/` at scale. A COUNT-based
reconciliation is a different instrument for exactly that reason.

WHY THIS FILE NEVER SPELLS ANY OF THE THIRTEEN SPELLINGS, OR THE RESIDUE PREFIX
--------------------------------------------------------------------------------
Every one of the thirteen spellings is assembled from small fragments,
exactly like `test_brand_surfaces.py`'s `NEEDLE`. Writing any of them whole
here would make this module's own live census see itself: a fresh
occurrence of whichever spelling got spelled out, at whichever line it was
written on, counted by the SAME `git grep` this module runs to police the
rest of the tree. The on-disk crash-residue dot-prefix (`safety/tempnames.py`'s
`TEMP_PREFIX`) is assembled for the identical reason -- it is a substring of
the no-separator spelling and would self-match just as readily.

Prose below refers to spellings by shape ("the underscore-separated form",
"the no-separator form", "the environment-variable-cased form", "the
exception-class-cased form", "the hyphenated form", "the three common-noun
spellings", and their NEW-stem counterparts) rather than by typing them, for
the same reason.
"""

from __future__ import annotations

import collections
import subprocess
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
# The thirteen spellings, assembled -- never spelled whole. See the module
# docstring's "WHY THIS FILE NEVER SPELLS" section.
# --------------------------------------------------------------------------- #

_LOW: Final[str] = "pdf"
_UP: Final[str] = "PDF"
_CAP: Final[str] = "Pdf"
_STEM_LOW: Final[str] = "toolkit"
_STEM_UP: Final[str] = "TOOLKIT"
_STEM_CAP: Final[str] = "Toolkit"
#: PDF-57 D5 -- the NEW stem, added alongside the old one rather than in its
#: place, so both eras stay inside one census with zero residual.
_STEM_LOW2: Final[str] = "tooling"
_STEM_UP2: Final[str] = "TOOLING"
_STEM_CAP2: Final[str] = "Tooling"

#: The underscore-separated form, e.g. what the import package used to be.
SPELL_UNDERSCORE: Final[str] = _LOW + "_" + _STEM_LOW
#: Its NEW-stem counterpart -- what the import package IS, PDF-48. Not this
#: item's own doing; it existed in the live tree before PDF-57 landed.
SPELL_UNDERSCORE_NEW: Final[str] = _LOW + "_" + _STEM_LOW2
#: The no-separator form, e.g. what the canonical console script used to be.
SPELL_BARE: Final[str] = _LOW + _STEM_LOW
#: Its NEW-stem counterpart -- the canonical console script, PDF-48.
SPELL_BARE_NEW: Final[str] = _LOW + _STEM_LOW2
#: The environment-variable-cased form (frozen AFTER PDF-57, D6a) -- the
#: prefix the documented secret-input env vars and a CI-absence guard both
#: key on. PDF-57 moves the LIVE population to its NEW-stem counterpart
#: below; this old form survives only in its enumerated frozen carriers.
SPELL_ENV: Final[str] = _UP + "_" + _STEM_UP
#: PDF-57 D2 -- the prefix swap this item performs. The contract-bearing
#: secret-input env vars and the CI-absence guard now key on THIS.
SPELL_ENV_NEW: Final[str] = _UP + "_" + _STEM_UP2
#: The exception-class-cased form (frozen AFTER PDF-57, D6b) -- the public
#: base exception's OLD name, and a leftover Astro logo-import identifier's
#: OLD name. PDF-57 moves the live population to its NEW-stem counterpart
#: below; this old form survives only in its enumerated frozen carriers.
SPELL_CLASS: Final[str] = _CAP + _STEM_CAP
#: PDF-57 D2 -- the base exception's new name and the Astro logo-import
#: identifier's new name after this item (never spelled whole here, for the
#: same self-match reason as everything else in this file -- see the module
#: docstring's "WHY THIS FILE NEVER SPELLS" section, which binds all
#: thirteen spellings, not only the eight PDF-48 froze).
SPELL_CLASS_NEW: Final[str] = _CAP + _STEM_CAP2
#: The hyphenated form -- the deprecated console-script alias.
SPELL_HYPHEN: Final[str] = _LOW + "-" + _STEM_LOW
#: Its NEW-stem counterpart -- the distribution name, PDF-48/X-405 frozen.
#: Everywhere, by construction: this is `pdf-tooling` itself.
SPELL_HYPHEN_NEW: Final[str] = _LOW + "-" + _STEM_LOW2
#: The three common-noun / fixture-marker spellings (D6c), out of scope.
#: UNCHANGED by PDF-57 -- ordinary English and a generated fixture's PDF name
#: object have no "tooling" counterpart to widen to.
SPELL_NOUN_LOW: Final[str] = _UP + " " + _STEM_LOW
SPELL_NOUN_UP: Final[str] = _UP + " " + _STEM_UP
SPELL_NOUN_MIXED: Final[str] = _UP + _STEM_CAP

#: PDF-57 D5.2 -- derived from the live tree, never guessed. Eight members
#: are PDF-48's frozen family (all still present -- `changelog.md` and
#: `tests/acceptance/` keep every one of them alive, D4's own prediction);
#: three are PDF-48's own NEW-stem population, already live before this item
#: touched anything; two (`SPELL_ENV_NEW`, `SPELL_CLASS_NEW`) are what THIS
#: item's rename adds. Thirteen total, re-derived at this item's own HEAD via
#: `git grep --untracked -Ioni -E "pdf[-_ ]?tool(kit|ing)"` bucketed by exact
#: matched text -- see the Implementation Log for the verbatim count per
#: member. A fourteenth member appearing anywhere is a NINTH-spelling-shaped
#: failure (the assertion's name predates PDF-57 and still applies); one of
#: these thirteen occurring nowhere is a "vanished" failure.
EXPECTED_SPELLINGS: Final[frozenset[str]] = frozenset(
    {
        SPELL_UNDERSCORE,
        SPELL_UNDERSCORE_NEW,
        SPELL_BARE,
        SPELL_BARE_NEW,
        SPELL_ENV,
        SPELL_ENV_NEW,
        SPELL_CLASS,
        SPELL_CLASS_NEW,
        SPELL_HYPHEN,
        SPELL_HYPHEN_NEW,
        SPELL_NOUN_LOW,
        SPELL_NOUN_UP,
        SPELL_NOUN_MIXED,
    }
)
assert len(EXPECTED_SPELLINGS) == 13, "the thirteen assembled fragments collided"

#: The residue dot-prefix, assembled for the same reason -- it is a
#: substring of SPELL_BARE and would self-match if spelled whole.
_RESIDUE_PREFIX: Final[str] = "." + SPELL_BARE + "-"
#: The scratch-directory prefix declared once, `safety/atomic.py`.
_SCRATCH_PREFIX: Final[str] = SPELL_BARE + "-scratch-"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )


def _census() -> tuple[dict[str, list[str]], int]:
    """Every occurrence of the case-insensitive family, bucketed by its EXACT
    matched spelling. Returns (buckets, live total). `-Ion`, never `-Ioc`
    (AC4, X-420) -- the aliased shell `grep` is never used, only `git grep`
    or an absolute-path binary."""
    proc = _git("grep", "--untracked", "-Ioni", "-E", "pdf[-_ ]?tool(kit|ing)")
    if proc.returncode not in (0, 1):
        pytest.fail(f"git grep failed rc={proc.returncode}: {proc.stderr.strip()}")
    buckets: dict[str, list[str]] = collections.defaultdict(list)
    total = 0
    for row in proc.stdout.splitlines():
        if not row:
            continue
        path, _, rest = row.partition(":")
        lineno, _, matched = rest.partition(":")
        buckets[matched].append(f"{path}:{lineno}")
        total += 1
    return dict(buckets), total


def _count(spelling: str, *, scope: str | None = None, exclude: str | None = None) -> int:
    """`git grep -Fion <exact spelling>`, optionally path-scoped or with one
    path excluded (pathspec `:!<exclude>`). `-F` (fixed-string) is
    load-bearing: the residue prefix contains a literal `.`, which a regex
    engine reads as "any character" without it -- exactly the kind of
    silent overcount this item's own instruments exist to refuse. A plain
    substring search, not the `pdf[-_ ]?toolkit` family regex -- this is how
    the per-spelling remainder censuses below are taken, matching AC10's own
    recipe shape."""
    args = ["grep", "--untracked", "-IFon", "--", spelling]  # no `-i`: exact case, buckets disjoint
    if scope is not None or exclude is not None:
        args += ["--", scope or "."]
        if exclude is not None:
            args += [f":!{exclude}"]
    proc = _git(*args)
    if proc.returncode not in (0, 1):
        pytest.fail(f"git grep failed rc={proc.returncode}: {proc.stderr.strip()}")
    return len([line for line in proc.stdout.splitlines() if line])


# --------------------------------------------------------------------------- #
# AC1 -- the reconciliation, and its two REDs.
#
# The assertion core is a PURE function of (buckets, total) so the REDs can
# drive it on synthetic data without ever planting a file inside the real
# repository -- HC-4 forbids leaving working-tree state behind between
# assertions, and a standing automated RED cannot depend on a plant a human
# remembered to clean up.
# --------------------------------------------------------------------------- #


def _assert_reconciliation(buckets: dict[str, list[str]], total: int) -> None:
    reconciled = sum(len(v) for v in buckets.values())
    assert reconciled == total, (
        f"reconciliation residual: {reconciled} bucketed occurrence(s) != "
        f"{total} live occurrence(s) -- a rule double-counted or a bucket "
        "silently emptied"
    )
    observed = set(buckets)
    unexpected = observed - EXPECTED_SPELLINGS
    detail = "; ".join(
        f"{spelling!r} at {loc}" for spelling in unexpected for loc in buckets[spelling]
    )
    assert not unexpected, (
        f"{sum(len(buckets[s]) for s in unexpected)} occurrence(s) of a NINTH "
        f"(or later) spelling found -- named, never silently skipped: {detail}"
    )
    missing = EXPECTED_SPELLINGS - observed
    assert not missing, (
        f"spelling(s) {sorted(missing)} are in the expected set but occur nowhere "
        "in the live tree -- a spelling this item counted on has vanished entirely"
    )


def test_the_thirteen_spelling_reconciliation_has_no_residual() -> None:
    """AC1/PDF-57 D5. A single census over the whole tree, bucketed by EXACT
    matched spelling, sums to the live total with zero residual, and the set
    of observed spellings is exactly the thirteen of E1/E10 (both eras) --
    never fewer, never more. Renamed from `..._eight_spelling_...` -- PDF-57
    widens the family this reconciliation polices; see the module docstring."""
    buckets, total = _census()
    _assert_reconciliation(buckets, total)


def test_an_unexpected_spelling_is_named_not_skipped() -> None:
    """AC1's first RED. A synthetic spelling outside the expected thirteen
    (assembled the same way the real ones are, matching the operator's own
    suggested plant) fails the reconciliation, naming the spelling and its
    file:line -- never a silent skip. Driven on a COPY of the real census,
    not a scratch file left in the repository (HC-4). Renamed from
    `test_a_ninth_spelling_...` -- the plant is no longer the ninth spelling
    against a widened family of thirteen, but the failure message's own
    "NINTH (or later)" wording already covers that (unchanged, below)."""
    buckets, total = _census()
    planted = dict(buckets)
    ninth = _CAP + "_" + _STEM_CAP  # assembled: the operator's own example plant
    planted[ninth] = ["scratch/plant.py:1"]
    with pytest.raises(AssertionError, match="NINTH"):
        _assert_reconciliation(planted, total + 1)


def test_dropping_an_expected_spelling_reddens_the_reconciliation() -> None:
    """AC1's second RED. Removing one bucket from the expected set (by
    deleting it from the observed buckets, so `EXPECTED_SPELLINGS` names a
    spelling the tree no longer shows) makes the residual non-zero and the
    failure names the count."""
    buckets, total = _census()
    reduced = dict(buckets)
    victim = next(spelling for spelling in EXPECTED_SPELLINGS if spelling in reduced)
    removed = reduced.pop(victim)
    with pytest.raises(AssertionError, match="vanished"):
        _assert_reconciliation(reduced, total - len(removed))


# --------------------------------------------------------------------------- #
# AC4 -- the line-vs-occurrence trap, re-recorded (F2). `git grep -Ioc`
# silently drops `-o` and counts matching LINES; a census that used it would
# undercount whenever one line carries a spelling twice, with a success exit
# code. The brief's own `README.md` instance (23 occurrences over 20 lines
# at authoring time, since re-measured at HEAD as 26 over 22 -- both figures
# recorded in the Implementation Log) closed once PDF-48's rename left no
# README line repeating the no-separator spelling twice. The trap is
# demonstrated here on the site PDF-48 itself introduces one: `pyproject.
# toml`'s deprecated-shim declaration line names the no-separator spelling
# once as the key and once inside its shim function's name.
# --------------------------------------------------------------------------- #


def test_the_line_vs_occurrence_trap_is_still_live() -> None:
    """AC4/F2. The occurrence census and a naive line census of the SAME
    spelling over the SAME file disagree whenever a line carries the
    spelling more than once -- which `pyproject.toml`'s deprecated-shim
    script declaration now does for the no-separator spelling (D2). If they
    ever agree, this note is stale and must be re-derived, not carried
    forward -- exactly as happened to the brief's own `README.md` instance."""
    occ = _git("grep", "-Ion", "--", SPELL_BARE, "--", "pyproject.toml")
    occ_count = len([line for line in occ.stdout.splitlines() if line])
    # `-Ioc` silently drops `-o` and prints one "<path>:<count>" line
    # counting matching LINES, not occurrences -- X-420's own trap,
    # reproduced here on purpose rather than avoided, to demonstrate the
    # SAME undercount a `-Ioc` reader would silently accept.
    line_count_proc = _git("grep", "-Ioc", "--", SPELL_BARE, "--", "pyproject.toml")
    line_count = int(line_count_proc.stdout.strip().rpartition(":")[2] or "0")
    assert occ_count > line_count, (
        f"pyproject.toml's occurrence count ({occ_count}) no longer exceeds its "
        f"line count ({line_count}) for the no-separator spelling -- the "
        "line-vs-occurrence trap this note records has closed and must be "
        "re-derived, not asserted from memory"
    )
    assert occ_count > 0 and line_count > 0, "both censuses must see occurrences to compare"


# --------------------------------------------------------------------------- #
# AC10 -- the predicted remainder, one registry per moving spelling.
#
# Every carrier below is named WITH a reason (never a bare number), and the
# registries are EXHAUSTIVE: a residual occurrence outside every listed path
# is a failure, not a silent widening of some "everything else" bucket.
# --------------------------------------------------------------------------- #

#: `changelog.md` is a FLOOR, not an exact count, in every remainder
#: registry below -- exactly like `test_brand_surfaces.py`'s class `G`.
#: Landed entries are never edited; a correction is a new entry with a new
#: date, and THIS SPEC's own entry (landing in the same commit as this
#: file) already names both spellings by describing the rename itself. A
#: registry that pinned changelog.md exactly would redden on its own
#: commit, and every honest entry after it.
CHANGELOG_FLOOR: Final[dict[str, int]] = {
    SPELL_UNDERSCORE: 55,
    SPELL_BARE: 27,
}

#: The underscore-separated spelling's remainder. `.gitleaksignore` carries a
#: historical gitleaks fingerprint keyed on a past commit+path pair (frozen,
#: like changelog history -- rewriting the path would desync the fingerprint
#: from the history it describes); `README.md`/`pyproject.toml` each carry
#: one deprecated-shim mention (D2/D5); `test_cli_spine.py` carries the two
#: deprecated-shim target strings in its four-key AC5 arm. `changelog.md`
#: is NOT here -- it is a floor (`CHANGELOG_FLOOR`, above).
UNDERSCORE_REMAINDER: Final[dict[str, int]] = {
    "tests/acceptance/audit_pdf_01.py": 14,
    "tests/acceptance/audit_pdf_02.py": 11,
    "tests/acceptance/audit_pdf_03.py": 19,
    "tests/acceptance/audit_pdf_04.py": 12,
    "tests/acceptance/audit_pdf_05.py": 6,
    "tests/acceptance/audit_pdf_06.py": 4,
    "tests/acceptance/audit_pdf_09.py": 12,
    "tests/acceptance/audit_pdf_23.py": 5,
    ".gitleaksignore": 1,
    "README.md": 1,
    "pyproject.toml": 1,
    "src/pdf_tooling/cli/deprecated.py": 2,
    "tests/test_cli_spine.py": 2,
}

#: The no-separator spelling's remainder. Five classes of carrier: (1)
#: landed/recorded text (changelog, acceptance, perf); (2) the deprecated
#: console-script alias and its shim target, spread across the sites D1/D2/D5
#: name -- `test_cli_spine.py`'s nine cover the four-key AC5 arm (2), two
#: historical measurement citations (D3, quoting a specific past run, never
#: edited), and the AC6/AC7/AC8 shim-behaviour arms this item creates (5,
#: each resolving the deprecated script by name to drive it); (3) the on-disk
#: residue prefix and its scratch sibling (D6d), plus the PDF-46-introduced
#: shim-hiding directory prefix this item's Evidence section predates (F5, a
#: NEW finding -- see the Implementation Log); (4) the frozen corpus/golden
#: literal that embeds it (`tests/corpus.py`'s AC26 fixture password); (5)
#: fixture content that is not a reference to the product at all.
#: `changelog.md` is NOT here -- it is a floor (`CHANGELOG_FLOOR`, above).
BARE_REMAINDER: Final[dict[str, int]] = {
    "tests/acceptance/audit_pdf_01.py": 21,
    "tests/acceptance/audit_pdf_03.py": 1,
    "tests/acceptance/audit_pdf_04.py": 4,
    "tests/acceptance/audit_pdf_05.py": 3,
    "tests/acceptance/audit_pdf_06.py": 1,
    "tests/acceptance/audit_pdf_09.py": 2,
    "perf/README.md": 1,
    "perf/gate-timings.jsonl": 4,
    "README.md": 6,
    "pyproject.toml": 2,
    "src/pdf_tooling/__init__.py": 1,
    "src/pdf_tooling/cli/deprecated.py": 5,
    "src/pdf_tooling/cli/main.py": 1,
    "src/pdf_tooling/ops/procpool.py": 2,
    "src/pdf_tooling/safety/atomic.py": 2,
    "src/pdf_tooling/safety/tempnames.py": 1,
    "scripts/reap_shims.py": 1,
    "tests/conftest.py": 1,
    "tests/test_engine_hiding_shim.py": 1,
    "tests/corpus.py": 1,
    "tests/integration/test_compose_roundtrip.py": 1,
    "tests/integration/test_crypto_roundtrip.py": 3,
    "tests/integration/test_overlay_preservation.py": 1,
    "tests/integration/test_pages_cli.py": 2,
    "tests/integration/test_rasterize_cli.py": 1,
    "tests/integration/test_rasterize_signals.py": 2,
    "tests/integration/test_split_merge_atomicity.py": 2,
    "tests/test_cli_spine.py": 9,
    "tests/test_import_boundaries.py": 5,
    "tests/unit/test_compose.py": 1,
    "tests/unit/test_tempnames.py": 3,
    "tests/unit/test_raster.py": 1,
}


def _remainder_check(spelling: str, registry: dict[str, int], label: str) -> None:
    buckets, _total = _census()
    found = collections.Counter(loc.rpartition(":")[0] for loc in buckets.get(spelling, []))
    registered_paths = set(registry) | {"changelog.md"}
    found_paths = set(found)
    unexpected_paths = found_paths - registered_paths
    assert not unexpected_paths, (
        f"the {label} spelling appears outside its registered carriers, unenumerated: "
        f"{sorted(unexpected_paths)}. Enumerate it with a stated reason, or it moves "
        "(AC10)."
    )
    mismatched = {
        path: (found.get(path, 0), expected)
        for path, expected in registry.items()
        if found.get(path, 0) != expected
    }
    assert not mismatched, (
        f"the {label} spelling's registered carriers drifted from their predicted "
        f"counts (found, expected): {mismatched}. A carrier that GREW without a "
        "changelog-style reason, or SHRANK, is a regression -- re-derive and update "
        "the registry with a stated reason, never silently."
    )
    floor = CHANGELOG_FLOOR[spelling]
    changelog_found = found.get("changelog.md", 0)
    assert changelog_found >= floor, (
        f"changelog.md's {label} spelling count ({changelog_found}) fell BELOW its "
        f"floor of {floor} -- landed history was edited or deleted, which "
        "changelog.md's own third rule forbids"
    )


def test_the_underscore_spelling_remainder_is_fully_enumerated() -> None:
    """AC10. Every remaining occurrence of the underscore-separated spelling
    is inside a named, counted carrier -- nothing outside the registry."""
    _remainder_check(SPELL_UNDERSCORE, UNDERSCORE_REMAINDER, "underscore-separated")


def test_the_bare_spelling_remainder_is_fully_enumerated() -> None:
    """AC10. Every remaining occurrence of the no-separator spelling is
    inside a named, counted carrier -- nothing outside the registry."""
    _remainder_check(SPELL_BARE, BARE_REMAINDER, "no-separator")


def test_reverting_one_import_grows_its_remainder_bucket_by_one() -> None:
    """AC10's RED. Reverting one import (synthetically: inflate a registered
    carrier's expected count by one less than reality) makes the mismatch
    check fail naming the file and the (found, expected) drift."""
    buckets, _total = _census()
    found = collections.Counter(loc.rpartition(":")[0] for loc in buckets.get(SPELL_UNDERSCORE, []))
    victim = next(path for path in UNDERSCORE_REMAINDER if found.get(path, 0) > 0)
    tampered = dict(UNDERSCORE_REMAINDER)
    tampered[victim] -= 1
    with pytest.raises(AssertionError, match="drifted"):
        _remainder_check(SPELL_UNDERSCORE, tampered, "underscore-separated")


# --------------------------------------------------------------------------- #
# AC26 -- the four frozen populations, byte-unchanged, each measured by a
# DIFFERENT instrument than `test_the_corpus_and_golden_name_strings_are_
# byte_identical` (B-237's blindness -- that arm cannot see a sweep that
# moves the producer, the golden and the oracle together).
# --------------------------------------------------------------------------- #

#: Measured at PDF-48 HEAD (re-derive; do not trust this comment), OUTSIDE
#: `changelog.md`. A population that CHANGES during this item's own
#: execution is a regression; a population that differs from the spec's
#: *authoring-time* figure is wave-5 information (X-621/X-622).
#:
#: `changelog.md` is EXCLUDED from all four exact counts below for the same
#: reason it is a floor rather than an exact count in `CHANGELOG_FLOOR`:
#: this spec's OWN new entry (landing in the same commit as this file)
#: already names the frozen env-var prefix and the frozen exception-class
#: names by describing what stayed frozen, so a repo-wide exact count would
#: redden on this spec's own commit. The four floors below record what
#: this spec's own entry legitimately added; a value BELOW its floor is a
#: rewritten landed entry, which changelog.md's own third rule forbids.
#:
#: PDF-57 D4 -- INVERTED, not merely renumbered. `PDF-48` froze this figure
#: at 146 (the live, moving population, outside `changelog.md`); `PDF-57`
#: retires the spelling entirely, so what survives outside `changelog.md`
#: is now ONLY the recorded-audit-text carrier this item never touches
#: (`tests/acceptance/`, D6/Scope>In row 4) -- re-derived at this item's own
#: HEAD via `_count(SPELL_ENV, scope=".", exclude="changelog.md")`, itemized
#: per path in the Implementation Log (never spelled literally in a comment
#: here -- doing so would self-match this module's own live census, exactly
#: the hazard the module docstring's "WHY THIS FILE NEVER SPELLS" warns
#: about). A value BELOW this means a frozen `tests/acceptance/` audit file
#: was swept; a value ABOVE it means the old prefix drifted back into the
#: live tree post-rename.
FROZEN_ENV_COUNT: Final[int] = 18
#: PDF-57 D4 -- INVERTED. `PDF-48`/X-717 froze this figure at 117 (bumped
#: from 116 for `PDF-54`'s own import, "SHORT-LIVED BY DESIGN: PDF-57
#: retires this spelling entirely and rewrites this census" -- that
#: retirement is THIS commit). What survives outside `changelog.md` is now
#: only the recorded-audit-text carrier (`tests/acceptance/`), re-derived at
#: this item's own HEAD via `_count(SPELL_CLASS, scope=".",
#: exclude="changelog.md")`, itemized per path in the Implementation Log
#: (never spelled literally in a comment -- same self-match hazard as above).
FROZEN_CLASS_COUNT: Final[int] = 4
FROZEN_RESIDUE_COUNT: Final[int] = 30  # the dot-prefix (29) + its scratch sibling (1)
FROZEN_NOUN_COUNT: Final[int] = 5  # 2 + 2 + 1, the three common-noun spellings summed
CHANGELOG_ENV_FLOOR: Final[int] = 14
CHANGELOG_CLASS_FLOOR: Final[int] = 8
CHANGELOG_RESIDUE_FLOOR: Final[int] = 3
CHANGELOG_NOUN_FLOOR: Final[int] = 1


def test_the_environment_variable_population_has_shrunk_to_its_frozen_remainder() -> None:
    """AC26/PDF-57 D4 -- INVERTED from `test_..._is_byte_unchanged`. Before
    this item the environment-variable-cased prefix was itself the frozen,
    live population (146, outside `changelog.md`); after it, the prefix is
    RETIRED and only survives inside its enumerated, recorded-audit-text
    carrier (`tests/acceptance/`). The claim this test now makes is the
    opposite of what its PDF-48 predecessor made, which is the point (D4):
    an arm whose NAME still said "byte unchanged" while asserting a
    population moved would be the exact classifier-annotation defect PDF-48
    E2 found in PDF-33's own shipped module.

    The NEW prefix (`SPELL_ENV_NEW`) is asserted PRESENT, never pinned to an
    exact count: it is now a live, moving population (the four env vars
    reachable from `src/` plus the twelve that are not), and pinning it here
    would make this module red on the next ordinary spec that touches one of
    those sixteen names -- exactly `PDF-31`'s AC6/AC14/AC20 zero-phrasing
    failure, adopted onto a fresh population instead of a stale one (D5.4)."""
    assert _count(SPELL_ENV, scope=".", exclude="changelog.md") == FROZEN_ENV_COUNT
    assert _count(SPELL_ENV, scope="changelog.md") >= CHANGELOG_ENV_FLOOR
    live_new = _count(SPELL_ENV_NEW, scope=".", exclude="changelog.md")
    assert live_new > 0, (
        "the new environment-variable-cased prefix has ZERO live occurrences -- "
        "the rename this item performs has vanished from the tree entirely"
    )


def test_the_exception_class_population_has_shrunk_to_its_frozen_remainder() -> None:
    """AC26/PDF-57 D4 -- INVERTED from `test_..._is_byte_unchanged`. The
    public base exception and its Astro-side logo identifier are RETIRED by
    this item; what survives outside `changelog.md` is only the
    recorded-audit-text carrier. See the docstring above for why the NEW
    class-cased spelling is asserted present rather than pinned."""
    assert _count(SPELL_CLASS, scope=".", exclude="changelog.md") == FROZEN_CLASS_COUNT
    assert _count(SPELL_CLASS, scope="changelog.md") >= CHANGELOG_CLASS_FLOOR
    live_new = _count(SPELL_CLASS_NEW, scope=".", exclude="changelog.md")
    assert live_new > 0, (
        "the new exception-class-cased spelling has ZERO live occurrences -- "
        "the rename this item performs has vanished from the tree entirely"
    )


def test_the_residue_prefix_population_is_byte_unchanged() -> None:
    """AC26. The on-disk crash-residue dot-prefix and its scratch-directory
    sibling (D6d) -- on-disk filenames with a recovery contract, not
    references. `PDF-46` owns this surface and landed first."""
    live = _count(_RESIDUE_PREFIX, scope=".", exclude="changelog.md") + _count(
        _SCRATCH_PREFIX, scope=".", exclude="changelog.md"
    )
    assert live == FROZEN_RESIDUE_COUNT
    logged = _count(_RESIDUE_PREFIX, scope="changelog.md") + _count(
        _SCRATCH_PREFIX, scope="changelog.md"
    )
    assert logged >= CHANGELOG_RESIDUE_FLOOR


def test_the_common_noun_population_is_byte_unchanged() -> None:
    """AC26. The three common-noun / fixture-marker spellings (D6c) --
    ordinary English, landed history, fixture text and a PDF name object
    inside a generated fixture. None of the three is a brand reference."""
    live = (
        _count(SPELL_NOUN_LOW, scope=".", exclude="changelog.md")
        + _count(SPELL_NOUN_UP, scope=".", exclude="changelog.md")
        + _count(SPELL_NOUN_MIXED, scope=".", exclude="changelog.md")
    )
    assert live == FROZEN_NOUN_COUNT
    logged = (
        _count(SPELL_NOUN_LOW, scope="changelog.md")
        + _count(SPELL_NOUN_UP, scope="changelog.md")
        + _count(SPELL_NOUN_MIXED, scope="changelog.md")
    )
    assert logged >= CHANGELOG_NOUN_FLOOR


def test_sweeping_a_frozen_population_shrinks_its_bucket_and_is_caught() -> None:
    """AC26's RED, driven through AC1's reconciliation rather than a
    file-content plant, independently of `test_brand_surfaces.py`'s
    classifier.

    PDF-57 D4 -- the DIRECTION REVERSES, and this docstring says so rather
    than silently keeping the old claim. Before this item a value BELOW
    `FROZEN_ENV_COUNT` meant a sweep had reached the (then-live) frozen
    population; after this item's own rename, the old spelling is RETIRED,
    so the only way a value can move at all is for the old name to drift
    BACK into the live tree above its enumerated `tests/acceptance/`
    remainder -- a value below it means one of those recorded-audit-text
    files was itself swept, which is equally a violation."""
    buckets, _total = _census()
    live_env = len(
        [loc for loc in buckets.get(SPELL_ENV, []) if not loc.startswith("changelog.md:")]
    )
    assert live_env == FROZEN_ENV_COUNT, (
        f"the environment-variable-cased population outside changelog.md is "
        f"{live_env}, expected exactly {FROZEN_ENV_COUNT} -- a value ABOVE this is "
        "the old, retired prefix drifting back into the live tree; a value BELOW it "
        "is a frozen tests/acceptance/ recorded-audit-text file that was itself swept"
    )
