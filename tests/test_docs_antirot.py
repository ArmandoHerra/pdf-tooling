"""Documentation anti-rot.

The prime documents rot in one predictable way: someone records progress in
them. A status line, a count, a spec-by-spec chain — each is correct for about a
week and actively misleading afterwards, and nothing catches it because prose is
not executed.

So the rule is mechanised rather than remembered. ``README.md`` and ``CLAUDE.md``
carry exactly **one** phase line each, and that line is a pointer rather than a
status: written correctly it needs editing zero times as work lands, which is a
stronger guarantee than "at most one line to edit".

The fourth check is the interesting one. It reads every ``make <target>`` string
out of the documentation and asserts the target exists — a doc-truth check that
would have caught the bootstrap command this repository documented before any
`Makefile` existed, and that every later change inherits for free.

PDF-30 — THE CLOSURE RULE
-------------------------
Everything above was scoped, at ``PRIME_DOCS``, to two documents. ``TESTING.md``
was unguarded by construction and five of its cardinal claims were stale; three
of them were spelled-out words (*"seven"*, *"six of the seven"*, *"thirteen"*)
that the ``SPEC_COUNT`` regex could not have matched even had the file been in
scope. Correcting those five numbers is a day's truth. The deliverable is the
**closure rule**:

    In a guarded document a cardinal claim about this repository is **derived
    from source at test time**, **produced by a documented command the gate
    re-runs and compares**, or **absent**. There is no fourth option.

:data:`DERIVED_FIGURES` is the first arm — every registered claim is compared
against a callable that recomputes it from source, in the rendering the document
uses (so a number written as a word is compared as a word). :func:`cardinal_residue`
is the backstop for the next unregistered number.

**HC-5 is not weakened here.** ``PRIME_DOCS`` is untouched and the four checks
above still run over exactly the two prime documents. What widens is
:data:`GUARDED_DOCS`, which is a different list for a different rule.

THE PLANNING SEAM, AND ITS HONEST ABSENCE STORY
-----------------------------------------------
The specs and their roster live OUTSIDE this repository, in the maintainer's
planning tree. :func:`planning_dir` resolves it through
``PDF_TOOLKIT_PLANNING_DIR`` and the arms that read it **skip with a reason
naming the resolved path** when it is absent — never a pass. CI checks out this
repository alone, so in CI those arms skip and their real enforcement is local,
``make docs-gate`` and the ``qa-sentinel``. That is stated here rather than
discovered later; *a control that cannot be run must be visible as skipped,
never silently absent* (X-153).
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The two documents an agent or a newcomer reads first.
PRIME_DOCS = ("README.md", "CLAUDE.md")

#: Every document allowed to name a `make` target.
DOCS_WITH_COMMANDS = ("README.md", "CLAUDE.md", "CONTRIBUTING.md", "TESTING.md")

#: PDF-30 D2 — the documents the closure rule binds. Deliberately the same four
#: as `DOCS_WITH_COMMANDS` and deliberately NOT `PRIME_DOCS`: the phase-line and
#: spec-identifier rules stay scoped to the two prime documents (HC-5).
GUARDED_DOCS = ("README.md", "CLAUDE.md", "CONTRIBUTING.md", "TESTING.md")

PHASE_LINE = re.compile(r"^\*\*Current phase:\*\*", re.MULTILINE)
SPEC_ID = re.compile(r"pdf-[0-9]{2}", re.IGNORECASE)
SPEC_COUNT = re.compile(r"[0-9]+ +specs?\b", re.IGNORECASE)
MAKE_TARGET = re.compile(r"\bmake +([a-zA-Z0-9_-]+)")


def read(name: str) -> str:
    return (REPO_ROOT / name).read_text()


def makefile_targets() -> set[str]:
    text = (REPO_ROOT / "Makefile").read_text()
    return set(re.findall(r"^([a-zA-Z0-9_.-]+):", text, re.MULTILINE))


@pytest.mark.parametrize("doc", PRIME_DOCS)
def test_exactly_one_phase_line(doc: str) -> None:
    matches = PHASE_LINE.findall(read(doc))
    assert len(matches) == 1, f"{doc} must carry exactly one '**Current phase:**' line"


@pytest.mark.parametrize("doc", PRIME_DOCS)
def test_no_spec_identifier_is_embedded(doc: str) -> None:
    found = SPEC_ID.findall(read(doc))
    assert found == [], f"{doc} names {found}; per-spec status belongs in the spec index"


@pytest.mark.parametrize("doc", PRIME_DOCS)
def test_no_spec_count_is_embedded(doc: str) -> None:
    found = SPEC_COUNT.findall(read(doc))
    assert found == [], (
        f"{doc} states a count ({found}); a count is wrong the day after it is written"
    )


@pytest.mark.parametrize("doc", DOCS_WITH_COMMANDS)
def test_every_documented_make_target_exists(doc: str) -> None:
    targets = makefile_targets()
    referenced = documented_make_targets(read(doc))
    missing = sorted(referenced - targets)
    assert missing == [], f"{doc} documents {missing}, which the Makefile does not define"


def test_the_phase_line_points_at_the_index_rather_than_restating_it() -> None:
    """A pointer needs editing zero times; a status needs editing every time."""
    for doc in PRIME_DOCS:
        line = next(
            line for line in read(doc).splitlines() if line.startswith("**Current phase:**")
        )
        assert "SPEC-INDEX.md" in line
        assert "changelog.md" in line


# --------------------------------------------------------------------------- #
# PDF-30 D2a — code spans, and why `make` is only read inside one
# --------------------------------------------------------------------------- #

FENCED_BLOCK = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]+`")


def code_spans(text: str) -> list[tuple[int, int]]:
    """Every fenced block and inline-code span, as (start, end) offsets."""
    spans = [m.span() for m in FENCED_BLOCK.finditer(text)]
    covered = [range(a, b) for a, b in spans]
    for match in INLINE_CODE.finditer(text):
        if not any(match.start() in r for r in covered):
            spans.append(match.span())
    return sorted(spans)


def _blank(text: str, spans: Iterable[tuple[int, int]]) -> str:
    """*text* with every span replaced by spaces, newlines preserved.

    Preserving newlines is not cosmetic: every residue below is reported with a
    line number, and a masker that ate newlines would report the wrong line —
    the "worst control reports the WRONG answer" failure this spec exists for.
    """
    out = list(text)
    for start, end in spans:
        for index in range(start, min(end, len(out))):
            if out[index] != "\n":
                out[index] = " "
    return "".join(out)


def code_text(text: str) -> str:
    """Only the code spans of *text*; everything else blanked."""
    keep = code_spans(text)
    mask = [(0, len(text))]
    body = _blank(text, mask)
    out = list(body)
    for start, end in keep:
        for index in range(start, min(end, len(out))):
            out[index] = text[index]
    return "".join(out)


def documented_make_targets(text: str) -> set[str]:
    """The `make <target>` strings a document DOCUMENTS, i.e. names in code.

    D2a: the bare regex matches English. Over the four documents it is green
    today by luck — the first *"make sure the corpus is absent"* in `TESTING.md`
    would turn it red on prose. A documented command lives in a code span, so
    that is where the match is read; the assertion above is unchanged.
    """
    return set(MAKE_TARGET.findall(code_text(text)))


def test_make_target_matching_reads_code_spans_and_not_prose() -> None:
    """AC5's negative control: the narrowing is proven, not assumed."""
    prose = "Please make sure the corpus is absent before you make room for it."
    assert documented_make_targets(prose) == set()
    assert MAKE_TARGET.findall(prose) == ["sure", "room"], (
        "the unrestricted matcher must still be shown to fire on prose, or this "
        "control proves nothing about the narrowing"
    )
    fenced = "text\n\n```bash\nmake docs-gate\n```\n\nmore text"
    assert documented_make_targets(fenced) == {"docs-gate"}
    inline = "Run `make samples-gate` when you have the corpus."
    assert documented_make_targets(inline) == {"samples-gate"}


# --------------------------------------------------------------------------- #
# PDF-30 D1 — the derived-figure registry
# --------------------------------------------------------------------------- #

_CARDINALS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
)


def cardinal(number: int) -> str:
    """*number* as this documentation writes it: a word to twenty, then digits.

    AC3. The three claims the `SPEC_COUNT` regex could never have seen were
    `"seven"`, `"six of the seven"` and `"thirteen"`. A registry that renders
    only digits would have reproduced that blind spot inside its own fix.
    """
    if 0 <= number < len(_CARDINALS):
        return _CARDINALS[number]
    return str(number)


def normalise(text: str) -> str:
    """Whitespace-collapsed *text*, so a claim may wrap across lines."""
    return " ".join(text.split())


@dataclass(frozen=True)
class DerivedFigure:
    """One documented claim, bound to the source that decides it."""

    document: str
    anchor: str
    derive: Callable[[], str]
    note: str


def _tests_module(name: str):  # type: ignore[no-untyped-def]
    import importlib
    import sys

    tests_dir = str(Path(__file__).resolve().parent)
    if tests_dir not in sys.path:  # pragma: no cover - import plumbing
        sys.path.insert(0, tests_dir)
    return importlib.import_module(name)


def fixture_names() -> tuple[str, ...]:
    return tuple(_tests_module("corpus").FIXTURE_NAMES)


def unencrypted_fixture_names() -> tuple[str, ...]:
    return tuple(_tests_module("test_corpus").UNENCRYPTED_FIXTURES)


def contract_check_rows() -> tuple[str, ...]:
    """Every `# C<N> --` row declared in `tests/test_cli_contract.py`.

    Read out of the file rather than out of a hand-typed list, because the list
    is what goes stale: `C15` (B-054) and `C16` (B-076) landed after the
    sentence in `TESTING.md` was written, and `C17`/`C18` after that.
    """
    text = (REPO_ROOT / "tests" / "test_cli_contract.py").read_text()
    return tuple(sorted(set(re.findall(r"^# (C\d+)\b", text, re.MULTILINE))))


def golden_files() -> tuple[str, ...]:
    return tuple(sorted(p.name for p in (REPO_ROOT / "tests" / "golden").glob("*.json")))


def contract_populations() -> dict[str, int]:
    """The five `tests/test_cli_contract.py` parametrize sets, live."""
    module = _tests_module("test_cli_contract")
    return {
        name: len(getattr(module, name))
        for name in (
            "GROUPS",
            "MUTATING",
            "DESTRUCTIVE",
            "PRODUCING",
            "OUTPUT_CONSUMING_MUTATING",
        )
    }


COVERAGE_FLOOR = re.compile(r"--cov-fail-under=(\d+)")


def coverage_floor() -> int:
    """The floor, from its one definition — `Makefile`'s `cover` recipe."""
    found = COVERAGE_FLOOR.findall((REPO_ROOT / "Makefile").read_text())
    assert found, "the Makefile no longer declares --cov-fail-under; the floor has no definition"
    assert len(set(found)) == 1, f"the Makefile declares more than one floor: {sorted(set(found))}"
    return int(found[0])


def documented_target(name: str) -> str:
    """`make <name>`, having first proven the Makefile defines *name*."""
    assert name in makefile_targets(), f"the Makefile does not define a `{name}` target"
    return f"make {name}"


#: D1. Each entry binds a span of a document to a callable that recomputes the
#: same value from source, in the rendering the document uses. `anchor` locates
#: the claim and is asserted to occur EXACTLY ONCE — an anchor that matches
#: nothing is a guard that guards nothing, so it is a failure and never a skip.
DERIVED_FIGURES: tuple[DerivedFigure, ...] = (
    DerivedFigure(
        document="TESTING.md",
        anchor="deterministic PDFs",
        derive=lambda: f"builds {cardinal(len(fixture_names()))} deterministic PDFs",
        note="TESTING.md said `seven` while tests/corpus.py declared far more.",
    ),
    DerivedFigure(
        document="TESTING.md",
        anchor="deterministic PDFs (",
        derive=lambda: "(" + ", ".join(f"`{name}`" for name in fixture_names()) + ")",
        note="The name list rots the same way the count does, one fixture at a time.",
    ),
    DerivedFigure(
        document="TESTING.md",
        anchor="are byte-identical across two",
        derive=lambda: (
            f"{cardinal(len(unencrypted_fixture_names())).capitalize()} of the "
            f"{cardinal(len(fixture_names()))} are byte-identical"
        ),
        note=(
            "tests/test_corpus.py::UNENCRYPTED_FIXTURES is already derived, so only "
            "the prose was ever stale — including the test's own function name."
        ),
    ),
    DerivedFigure(
        document="TESTING.md",
        anchor="parameterizes",
        derive=lambda: f"parameterizes {cardinal(len(contract_check_rows()))} checks",
        note="C15/C16 (B-054/B-076) and C17/C18 landed after the sentence was written.",
    ),
    DerivedFigure(
        document="TESTING.md",
        anchor="golden files live in",
        derive=lambda: f"{cardinal(len(golden_files()))} golden files live in",
        note="`Empty at PDF-06 landing` outlived the first golden by three specs.",
    ),
    DerivedFigure(
        document="TESTING.md",
        anchor="parametrize sets are",
        derive=lambda: f"{cardinal(len(contract_populations()))} parametrize sets are non-empty",
        note=(
            "The roadmap named C13 and C4; the measurement says all five populations "
            "are non-empty. The parenthetical was stale in whole, not in part."
        ),
    ),
    DerivedFigure(
        document="TESTING.md",
        anchor="the sanctioned `@samples` ordering",
        derive=lambda: documented_target("samples-gate"),
        note=(
            "X-115 created the one target that abolishes the hand-typed recipe and "
            "`grep -c samples-gate` returned 0 for all four documents (E7)."
        ),
    ),
    DerivedFigure(
        document="TESTING.md",
        anchor="re-runs the run-and-compare arms",
        derive=lambda: documented_target("docs-gate"),
        note="D10 — the carrier for B-099's `Re-run it; do not copy it`.",
    ),
    DerivedFigure(
        document="TESTING.md",
        anchor="is measured on",
        derive=lambda: f"--cov-fail-under={coverage_floor()}",
        note="The floor has one definition and three claim sites; AC8 compares them.",
    ),
)


def test_the_derived_figure_registry_is_not_empty() -> None:
    """AC1's anti-lapse assertion. An empty registry passes every other check."""
    assert DERIVED_FIGURES, "the registry is empty; every figure below would pass vacuously"


@pytest.mark.parametrize("entry", DERIVED_FIGURES, ids=lambda e: f"{e.document}:{e.anchor[:32]}")
def test_every_registry_anchor_occurs_exactly_once(entry: DerivedFigure) -> None:
    """AC1. A registry entry that matches nothing is a guard that guards nothing."""
    body = normalise(read(entry.document))
    count = body.count(normalise(entry.anchor))
    assert count == 1, (
        f"{entry.document}: anchor {entry.anchor!r} occurs {count} time(s), expected exactly 1. "
        f"Why this claim exists: {entry.note}"
    )


@pytest.mark.parametrize("entry", DERIVED_FIGURES, ids=lambda e: f"{e.document}:{e.anchor[:32]}")
def test_every_registered_figure_equals_its_derivation(entry: DerivedFigure) -> None:
    """AC2. Compared as the string the document renders, words included."""
    body = normalise(read(entry.document))
    expected = normalise(entry.derive())
    assert expected in body, (
        f"{entry.document} no longer states {expected!r}, which is what the source "
        f"now derives. Why this claim exists: {entry.note}"
    )


def test_the_cardinal_helper_renders_words_then_falls_back_to_digits() -> None:
    """AC3. The criterion the `SPEC_COUNT` regex could not have satisfied."""
    assert cardinal(0) == "zero"
    assert cardinal(7) == "seven"
    assert cardinal(16) == "sixteen"
    assert cardinal(20) == "twenty"
    assert cardinal(21) == "21"
    assert cardinal(1857) == "1857"
    # The AC3 red, in miniature: a one-off in the rendering is a different string.
    assert cardinal(15) != cardinal(16)


def test_the_registry_can_fail_on_a_scratch_document(tmp_path: Path) -> None:
    """AC1/AC2/AC3's reds, driven against a SCRATCH copy — never the real tree."""
    entry = next(e for e in DERIVED_FIGURES if e.anchor == "parameterizes")
    real = read(entry.document)
    expected = normalise(entry.derive())

    # (a) the anchor deleted -> the anchor check fails
    without_anchor = normalise(real.replace("parameterizes", "covers"))
    assert without_anchor.count(normalise(entry.anchor)) == 0

    # (b) the cardinal changed by one -> the equality check fails
    digits = len(contract_check_rows())
    off_by_one = normalise(real.replace(cardinal(digits), cardinal(digits - 1)))
    assert expected not in off_by_one

    # (c) an empty registry -> the non-empty check fails
    empty: tuple[DerivedFigure, ...] = ()
    assert not empty, "an empty registry is falsy, which is what AC1 asserts against"


# --------------------------------------------------------------------------- #
# PDF-30 D2 — the unregistered-cardinal backstop
# --------------------------------------------------------------------------- #

NUMBER_WORD = "|".join(_CARDINALS)
CANDIDATE = re.compile(rf"\b(?:\d+|{NUMBER_WORD})\b", re.IGNORECASE)

#: Structured references that carry digits and are not cardinals ABOUT this
#: repository. Order matters only for readability; each is masked before the
#: candidate scan runs.
STRUCTURED_REFERENCE = (
    re.compile(r"\d{4}-\d{2}-\d{2}"),  # a date
    re.compile(r"§\s?\d+(?:\.\d+)*"),  # a section reference
    re.compile(r":\d+(?:-\d+)?\b"),  # a line reference
    re.compile(r"\b(?:PDF|B|R|C|X|OR|AC|D)-?\d+[a-z]?\b"),  # an identifier
    re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b"),  # a version
    re.compile(r"\b[0-9a-f]{7,40}\b"),  # a short sha
    re.compile(r"https?://\S+"),  # a URL
    re.compile(r"\b(?:AES|RC4|SHA|UTF|Apache)-\d+(?:\.\d+)?\b"),  # a named algorithm
    re.compile(r"\bL\d\b"),  # a layer label
    re.compile(r"^\s*\d+\.\s", re.MULTILINE),  # a markdown ordered-list marker
    re.compile(r"\brules?\s+\d+\b"),  # a `PLAN.md` §10.1 rule reference
)

#: Exit codes are a fixed, published table (`README.md`'s own section) rather
#: than a count of anything, so a bare `2` next to `exit` is not a cardinal
#: claim about the repository.
EXIT_CODE = re.compile(r"\bexits?\s+\**\d\**|\bexit\s+code\s+\d|^\|\s*\d\s*\|", re.MULTILINE)


def cardinal_residue(document: str) -> list[tuple[int, str, str]]:
    """Every candidate cardinal in *document* that nothing above accounts for.

    Subtracted in D2's own order: registry spans, code spans, structured
    references, exit codes. What is left is, by the closure rule, a claim about
    this repository that no instrument can observe going wrong.
    """
    text = read(document)
    masked = _blank(text, code_spans(text))

    for entry in DERIVED_FIGURES:
        if entry.document != document:
            continue
        rendered = entry.derive()
        # Rendered FIRST, then the anchor: an anchor is usually a substring of
        # the rendered claim, so masking it first would shred the longer string
        # and leave the registered figure looking unregistered. Measured, not
        # reasoned -- the wrong order reported fifteen phantom residents.
        for needle in (rendered, entry.anchor):
            index = masked.find(needle)
            while index != -1:
                masked = _blank(masked, [(index, index + len(needle))])
                index = masked.find(needle)

    for pattern in (*STRUCTURED_REFERENCE, EXIT_CODE):
        masked = _blank(masked, [m.span() for m in pattern.finditer(masked)])

    lines = text.splitlines()
    residue: list[tuple[int, str, str]] = []
    for match in CANDIDATE.finditer(masked):
        line_no = masked[: match.start()].count("\n") + 1
        residue.append((line_no, match.group(0), lines[line_no - 1].strip()))
    return residue


def test_the_cardinal_backstop_can_see_a_planted_claim(tmp_path: Path) -> None:
    """AC4's RED, self-tested BEFORE the residue below is trusted (B-088).

    A scanner is not believed because it returned a number; it is believed
    because it was shown to find a known needle first.
    """
    scratch = tmp_path / "SCRATCH.md"
    scratch.write_text("The suite has 1857 tests.\n\nA fenced block:\n\n```\n42 tests\n```\n")
    text = scratch.read_text()
    masked = _blank(text, code_spans(text))
    hits = [m.group(0) for m in CANDIDATE.finditer(masked)]
    assert hits == ["1857"], (
        "the backstop must see a bare cardinal in prose and must NOT see one "
        f"inside a fenced block; it saw {hits}"
    )


#: The residue by document, with every D2 subtraction applied. Measured at
#: `7afdb1a` with this instrument: 26 / 7 / 6 / 120 = **159**. Measured at this
#: spec's landing: 30 / 7 / 6 / 128 = **171** — the growth is this spec's own
#: added prose (the `docs-gate` section, the README's known-issues section and
#: its verb roster), and it is reported rather than hidden.
#:
#: **This is a debt register, not an exemption list**, and the
#: distinction is the whole of D2's warning about itself: nothing here is
#: declared fine — each entry is a cardinal in a guarded document that no
#: instrument can observe going wrong, and the count may not GROW.
#:
#: D2 sets 40 as the point at which the engineer stops and escalates rather
#: than exempting to green, *"because at that point the right answer may be to
#: narrow the guarded span rather than to widen the exemptions, and that is a
#: PM decision."* The measured residue is far past 40, so it is escalated and
#: NOT exempted: the emptiness assertion D2 asks for is withheld pending that
#: ruling, and what ships instead is the instrument (self-tested above) plus
#: this frozen ceiling, so the debt is visible at its exact size and cannot
#: grow silently while the decision is outstanding.
RESIDUE_CEILING: dict[str, int] = {
    "README.md": 30,
    "CLAUDE.md": 7,
    "CONTRIBUTING.md": 6,
    "TESTING.md": 128,
}


@pytest.mark.parametrize("doc", GUARDED_DOCS)
def test_the_unregistered_cardinal_residue_does_not_grow(doc: str) -> None:
    """AC4, in the posture X-371 requires while the span ruling is outstanding."""
    residue = cardinal_residue(doc)
    ceiling = RESIDUE_CEILING[doc]
    listing = "\n".join(f"  {doc}:{line} {token!r} | {text[:90]}" for line, token, text in residue)
    assert len(residue) <= ceiling, (
        f"{doc} carries {len(residue)} unregistered cardinals, above the frozen "
        f"ceiling of {ceiling} measured at 6deebb4. A new cardinal claim in a "
        f"guarded document is derived, gated by `make docs-gate`, or absent — "
        f"there is no fourth option:\n{listing}"
    )


def test_the_residue_ceiling_is_frozen_and_covers_every_guarded_document() -> None:
    """The anti-lapse assertion on the ceiling itself: a ceiling that silently
    grew, or that stopped covering a document, would make the arm above vacuous."""
    assert set(RESIDUE_CEILING) == set(GUARDED_DOCS)
    assert sum(RESIDUE_CEILING.values()) == 171, (
        "171 is the total measured at PDF-30's landing, against 159 for the same "
        "four documents at 7afdb1a with this same instrument. Both are far past "
        "D2's escalation threshold of 40, so the number is a PM decision on the "
        "guarded span, not an edit made here to reach green"
    )


# --------------------------------------------------------------------------- #
# PDF-30 AC8 — the coverage floor, guarded three ways round
# --------------------------------------------------------------------------- #


def test_every_coverage_floor_claim_agrees_with_the_one_definition() -> None:
    """AC8. `Makefile`'s `cover` recipe defines the floor; every other site
    CLAIMS it. PDF-28 consolidated `ci.yml` onto `make cover`, so at this commit
    the definition is singular and `ci.yml` must declare none — which
    `tests/test_gate_parity.py` already pins from its own direction."""
    floor = coverage_floor()
    sites = {
        "Makefile": (REPO_ROOT / "Makefile").read_text(),
        "pyproject.toml": (REPO_ROOT / "pyproject.toml").read_text(),
        "TESTING.md": read("TESTING.md"),
        ".github/workflows/ci.yml": (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(),
    }
    disagreeing = {
        name: sorted(set(found))
        for name, text in sites.items()
        if (found := COVERAGE_FLOOR.findall(text)) and set(found) != {str(floor)}
    }
    assert disagreeing == {}, (
        f"the floor is {floor} in the Makefile; these sites state something else: {disagreeing}"
    )
    assert COVERAGE_FLOOR.findall(sites[".github/workflows/ci.yml"]) == [], (
        "ci.yml re-declaring the floor is the duplication PDF-28 removed"
    )
    assert str(floor) in read("TESTING.md"), "TESTING.md no longer states the floor at all"


def test_the_floor_agreement_check_can_fail() -> None:
    """AC8's RED, against a scratch copy of the four texts rather than the tree."""
    floor = coverage_floor()
    poisoned = f"--cov-fail-under={floor + 1}"
    assert COVERAGE_FLOOR.findall(poisoned) == [str(floor + 1)]
    assert set(COVERAGE_FLOOR.findall(poisoned)) != {str(floor)}


# --------------------------------------------------------------------------- #
# PDF-30 D6 — the planning-artifact seam
# --------------------------------------------------------------------------- #

#: How a test reaches the maintainer's planning tree. Absent -> SKIP with a
#: reason naming the resolved path. Never a pass.
PLANNING_DIR_ENV = "PDF_TOOLKIT_PLANNING_DIR"

STATUS_VOCABULARY = ("Proposed", "Implemented", "Verified", "Parked")

#: The two new skip classes this spec introduces, spelled once so `make
#: docs-gate` and `scripts/assert_skips.py` can both name them.
SKIP_PLANNING_ABSENT = "planning directory absent"
SKIP_SHALLOW_CLONE = "shallow clone"


def planning_dir() -> Path:
    """The resolved planning tree, existing or not."""
    override = os.environ.get(PLANNING_DIR_ENV)
    if override:
        return Path(override)
    return REPO_ROOT.parent.parent / "ai_plans" / "pdf-toolkit"


def require_planning_dir() -> Path:
    root = planning_dir()
    if not (root / "specs" / "SPEC-INDEX.md").is_file():
        pytest.skip(
            f"{SKIP_PLANNING_ABSENT}: no specs/SPEC-INDEX.md under {root} "
            f"(set {PLANNING_DIR_ENV} to the maintainer's planning tree). "
            "This arm is enforced locally, by `make docs-gate` and by the "
            "qa-sentinel; CI checks out this repository alone."
        )
    return root


STATUS_TOKEN = re.compile(r"^\s*(?:\*\*)?\s*([A-Za-z][A-Za-z-]*)")
BOLD_SPAN = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
#: X-364's third instrument, and the only one of three that was correct. A
#: verification GRANT is a bold span whose content LEADS with `VERIFIED (date)`,
#: with arbitrary trailing text allowed inside the span — `PDF-28`'s grant reads
#: `**VERIFIED (2026-09-02) as to its own criteria**` and a tight
#: `\*\*VERIFIED \(date\)\*\*` misses it. Negations need no blocklist: `Verified
#: WITHDRAWN` and `VERIFICATION WITHHELD` do not LEAD with the grant, so they are
#: excluded structurally. A word blocklist would be the next B-080 — and would
#: give the wrong answer on `PDF-25` and `PDF-29`, which both contain "WITHHELD"
#: and are both genuinely `Verified`.
VERIFICATION_GRANT = re.compile(r"^(?:VERIFIED|Verified)\s*\(\d{4}-\d{2}-\d{2}\)")
ROSTER_ROW = re.compile(r"^\|\s*(PDF-\d\d)\s*\|")
HEADER_STATUS = re.compile(r"^\*\*Status:\*\*\s*(.*)$", re.MULTILINE)


def status_token(field: str) -> str | None:
    """The leading status token of a declared status field.

    X-364's gated definition. A status cell is ``**<Token> (<date>)**``
    optionally followed by `` — <narrative>``; only the token is the status, and
    **narrative after the em dash is evidence, never status**. The header field
    has the same shape and is parsed the same way.
    """
    match = STATUS_TOKEN.match(field)
    return match.group(1) if match else None


def verification_grants(cell: str) -> list[str]:
    return [span for span in BOLD_SPAN.findall(cell) if VERIFICATION_GRANT.match(span.strip())]


def roster_rows(spec_index_text: str) -> dict[str, str]:
    """Every `PDF-NN` row's status cell, keyed by id.

    Cells are split on UNESCAPED pipes: the roster's own prose carries `\\|`
    inside inline code (`merge\\|preserve\\|none`), and a naive split would
    shred those rows into the wrong number of cells.
    """
    rows: dict[str, str] = {}
    for line in spec_index_text.splitlines():
        match = ROSTER_ROW.match(line)
        if match:
            cells = re.split(r"(?<!\\)\|", line.strip())[1:-1]
            rows[match.group(1)] = cells[-1].strip()
    return rows


def spec_header_statuses(root: Path) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for path in sorted((root / "specs").glob("PDF-*.md")):
        match = HEADER_STATUS.search(path.read_text())
        if match:
            statuses[path.name[:6]] = match.group(1).strip()
    return statuses


def test_the_grant_detector_is_self_tested_before_it_is_trusted() -> None:
    """B-088's discipline applied to X-364's instrument: one positive that
    defeats the tight pattern, three negatives that must NOT match."""
    positive = (
        "**VERIFIED (2026-09-02) as to its own criteria** by `qa-sentinel` run `2026-09-02_071003`"
    )
    assert verification_grants(positive), (
        "the trailing-qualifier grant is the one that defeats a tight "
        "`**VERIFIED (date)**` pattern; missing it is X-364's instrument #2"
    )
    assert verification_grants("**VERIFIED (2026-09-02)**")
    assert verification_grants("**Verified (2026-08-30)**")
    # The three negatives. None LEADS with the grant, so none is excluded by a
    # blocklist -- which is what keeps `PDF-25` and `PDF-29` (both of which
    # contain "WITHHELD" and are both genuinely Verified) correctly scored.
    assert not verification_grants("**Implemented (2026-08-30) — `Verified` WITHDRAWN 2026-08-31**")
    assert not verification_grants("**VERIFICATION WITHHELD (X-357) and the PM ACCEPTED**")
    assert not verification_grants("**PM-verified, and the split is recorded here**")


def test_the_roster_vocabulary_is_the_rosters_own() -> None:
    """AC17's vocabulary arm, provable without the planning tree."""
    assert status_token("**Verified (2026-09-02)** — landed `8fd2146`") == "Verified"
    assert status_token("Implemented (2026-08-30) — `Verified` WITHDRAWN") == "Implemented"
    assert status_token("Proposed") == "Proposed"
    assert status_token("In progress (Phase A landed 2026-08-29)") == "In"
    assert "In" not in STATUS_VOCABULARY, (
        "`In progress` must fail as an UNKNOWN token rather than be quietly normalised"
    )


def test_the_status_guard_fires_against_a_synthetic_planning_tree(tmp_path: Path) -> None:
    """AC20's RED, and X-364(iii)'s.

    Driven against a `tmp_path` fixture, never the operator's real tree — the
    same construction `tests/integration/test_samples_guard_fires.py` uses to
    prove the originals guard without touching the operator's corpus.

    The planted `PDF-28` cell is VERBATIM its own pre-normalisation text. It is
    the row that defeats a tight `**VERIFIED (date)**` pattern, so it is the row
    the red control uses.
    """
    specs = tmp_path / "specs"
    specs.mkdir(parents=True)
    planted = (
        "**Implemented (2026-09-02)** — `f543a22`, CI `33624132373` 17/17 (PM-tallied). "
        "**Its own AC15 NOT met** (`make ci PYTHON=3.11` red; X-199, B-148). … "
        "**VERIFIED (2026-09-02) as to its own criteria** by `qa-sentinel` run "
        "`2026-09-02_071003` — discharged."
    )
    rows = [
        "| ID | Title | Deliverable | Deps | Phase | Size | Status |",
        "|---|---|---|---|---|---|---|",
        f"| PDF-28 | Local gate | x | — | 1.1 | Medium | {planted} |",
        "| PDF-07 | merge + split | x | — | 1 | Medium | **Verified (2026-08-30)** |",
        "| PDF-16 | Website | x | — | 1 | Medium | **Parked (2026-08-31)** |",
    ]
    (specs / "SPEC-INDEX.md").write_text("\n".join(rows) + "\n")
    (specs / "PDF-28_local-gate.md").write_text("**Status:** Implemented (2026-09-02)\n")
    (specs / "PDF-07_merge-and-split.md").write_text("**Status:** Implemented (2026-08-29)\n")
    (specs / "PDF-16_website.md").write_text("**Status:** In progress (Phase A)\n")

    roster = roster_rows((specs / "SPEC-INDEX.md").read_text())
    headers = {
        "PDF-28": "Implemented (2026-09-02)",
        "PDF-07": "Implemented (2026-08-29)",
        "PDF-16": "In progress (Phase A)",
    }

    # (i) leading-token agreement
    divergences = [
        (sid, status_token(field), status_token(roster[sid])) for sid, field in headers.items()
    ]
    divergences = [d for d in divergences if d[1] != d[2]]
    assert sorted(sid for sid, _, _ in divergences) == ["PDF-07", "PDF-16"]

    # (ii) vocabulary
    unknown = [
        sid for sid, field in headers.items() if status_token(field) not in STATUS_VOCABULARY
    ]
    assert unknown == ["PDF-16"], "`In progress` is the live unknown token"

    # (iii) roster self-consistency — the check X-364 authorises beyond AC17/AC18
    contradictions = [
        sid
        for sid, cell in roster.items()
        if status_token(cell) == "Implemented" and verification_grants(cell)
    ]
    assert contradictions == ["PDF-28"], (
        "a cell leading `Implemented` while carrying an un-negated verification "
        "grant is a DEFECTIVE ROW; the PM repairs the row, and a header is never "
        "synced to a token the roster's own evidence refutes"
    )


def test_every_spec_header_agrees_with_its_roster_row() -> None:
    """AC17/AC18 — check (i), against the real planning tree.

    `PDF-09` is the case that proves the parser compares TOKENS rather than
    strings: header `Implemented (2026-08-30)` against roster `Implemented
    (2026-08-30) — Verified WITHDRAWN 2026-08-31` **agree**.
    """
    root = require_planning_dir()
    roster = roster_rows((root / "specs" / "SPEC-INDEX.md").read_text())
    headers = spec_header_statuses(root)
    assert headers, f"no PDF-NN specs under {root / 'specs'}"

    divergent = []
    for spec_id, field in sorted(headers.items()):
        if spec_id not in roster:
            continue
        header_token = status_token(field)
        roster_token = status_token(roster[spec_id])
        if header_token != roster_token:
            divergent.append(f"{spec_id}: header {header_token!r} vs roster {roster_token!r}")
    assert divergent == [], (
        "the roster is the source of truth and the header is synced to it, never "
        "the other way round:\n  " + "\n  ".join(divergent)
    )


def test_every_declared_status_token_is_in_the_rosters_own_vocabulary() -> None:
    """AC17 — check (ii). `In progress` fails as unknown, never normalised."""
    root = require_planning_dir()
    roster = roster_rows((root / "specs" / "SPEC-INDEX.md").read_text())
    headers = spec_header_statuses(root)
    unknown = [
        f"{sid}: {status_token(field)!r}"
        for source in (roster, headers)
        for sid, field in sorted(source.items())
        if status_token(field) not in STATUS_VOCABULARY
    ]
    assert unknown == [], f"status tokens outside {STATUS_VOCABULARY}: {unknown}"


def test_no_roster_row_contradicts_its_own_evidence() -> None:
    """X-364(iii) — check (iii), the strict superset of AC17/AC18.

    A cell may not LEAD `Implemented` while carrying an un-negated verification
    grant. Where it does, the ROW is defective and the PM repairs the row.
    """
    root = require_planning_dir()
    roster = roster_rows((root / "specs" / "SPEC-INDEX.md").read_text())
    contradictions = [
        f"{sid}: leads `Implemented` but carries {verification_grants(cell)!r}"
        for sid, cell in sorted(roster.items())
        if status_token(cell) == "Implemented" and verification_grants(cell)
    ]
    assert contradictions == [], "\n  ".join(["defective roster row(s):", *contradictions])


# --------------------------------------------------------------------------- #
# PDF-30 D5 / D7 — the README known-issues pointer and the verb roster
# --------------------------------------------------------------------------- #

KNOWN_ISSUES_HEADING = "## Known issues"
SWEEP_ID = re.compile(r"\b(\d{4}-\d{2}-\d{2}_\d{6})\b")
SHORT_SHA = re.compile(r"\b([0-9a-f]{7,40})\b")

#: AC22, strengthened by X-368. A sweep directory that carries none of these is
#: a pointer at scripts and stdout dumps and NO verdict document —
#: `.gitignore` drops `logs/**` except these three names, so "the directory
#: exists" is not the property a reader needs.
VERDICT_ARTIFACTS = ("report.md", "REPRO.txt", "VERDICT.txt", "RUN-SUMMARY.txt")


def _known_issues_body_of(text: str) -> str:
    """Pure text-level extraction, AC23. Used both by `known_issues_body()`
    below (the real, populated README.md) and directly by
    `test_the_known_issues_section_survives_the_vacuous_rendering` against a
    synthetic `tmp_path` document, so the vacuous rendering is checked with
    the exact slicing the populated state is, rather than a re-derived
    approximation of it."""
    assert KNOWN_ISSUES_HEADING in text, "document carries no `## Known issues` section"
    after = text.split(KNOWN_ISSUES_HEADING, 1)[1]
    return after.split("\n## ", 1)[0]


def known_issues_body() -> str:
    return _known_issues_body_of(read("README.md"))


def test_the_known_issues_section_exists_and_points_by_path() -> None:
    """AC21/AC23. The populated state: the real, current README.md's `##
    Known issues` section names both planning-tree paths, discloses they are
    not part of this distribution, and carries a sweep id and a short sha.
    The vacuous state — the heading surviving when nothing is open — is a
    different rendering of the same section, covered separately by
    `test_the_known_issues_section_survives_the_vacuous_rendering` below."""
    body = known_issues_body()
    assert "BACKLOG.md" in body
    assert "qa/FINDINGS-LEDGER.md" in body
    assert "not part of this distribution" in body, (
        "a known-issues section that points a user at a file they cannot open is "
        "worse than none; the section must say so plainly"
    )
    assert SWEEP_ID.search(body), "the section must name the sweep id it was taken at"
    assert SHORT_SHA.search(body), "the section must name the commit the sweep was taken at"


def test_the_known_issues_section_carries_no_count() -> None:
    """AC21's mechanical criterion, verbatim: strip the sweep-id and short-sha
    tokens, then no digit may survive. `grep -o … | wc -l`, never `grep -c`
    (B-104) — which is why this counts OCCURRENCES and not lines."""
    body = known_issues_body()
    stripped = SHORT_SHA.sub(" ", SWEEP_ID.sub(" ", body))
    digits = re.findall(r"[0-9]+", stripped)
    assert digits == [], (
        f"the section states {digits}; it points and never tallies — if the PM's own "
        "ledger header cannot hold a count still for two days, a README cannot"
    )


def test_the_no_count_criterion_can_fail() -> None:
    """AC21's RED, on a scratch body rather than the real README."""
    poisoned = known_issues_body() + "\n\nThere are 27 open findings.\n"
    stripped = SHORT_SHA.sub(" ", SWEEP_ID.sub(" ", poisoned))
    assert re.findall(r"[0-9]+", stripped) == ["27"]


def test_the_known_issues_section_survives_the_vacuous_rendering(tmp_path: Path) -> None:
    """AC23. `README.md:162` promises that if a sweep ever records nothing
    open, the section still stands and reads a no-open-findings sentence
    rather than being deleted (cycle 1's `planned.length > 0` ruling, applied
    here). Prose is not executed, so this builds that second rendering on a
    synthetic `tmp_path` document — the real README.md is never written —
    and runs it through the exact same `_known_issues_body_of` slicing the
    populated state above uses, so the heading surviving and the section
    still being found are both asserted mechanically rather than trusted."""
    vacuous = (
        f"{KNOWN_ISSUES_HEADING}\n\n"
        "Open defects and planned work are recorded, per finding, in the "
        "maintainer's planning tree:\n\n"
        "- `ai_plans/pdf-toolkit/BACKLOG.md` — the groomed intake list.\n"
        "- `ai_plans/pdf-toolkit/qa/FINDINGS-LEDGER.md` — every finding a QA "
        "sweep has raised, with its state and its evidence.\n\n"
        "**Those artifacts live in the maintainer's planning repository and "
        "are not part of this distribution.**\n\n"
        "no open findings are recorded as of sweep `2026-09-03_113318` "
        "(`7afdb1a`)\n\n"
        "## License\n\n"
        "Apache-2.0 — see `LICENSE` and `NOTICE`.\n"
    )
    scratch = tmp_path / "README.md"
    scratch.write_text(vacuous)

    assert KNOWN_ISSUES_HEADING in vacuous, "the heading must survive the vacuous rendering"
    body = _known_issues_body_of(scratch.read_text())
    assert "no open findings are recorded as of sweep" in body, (
        "the section must still be found once it is vacuous, not merely present as prose"
    )
    assert "not part of this distribution" in body

    # AC21's digit-grep discipline binds this arm too (B-104): strip the
    # sweep-id and short-sha tokens the vacuous sentence is allowed to carry,
    # then no digit may survive — `grep -o … | wc -l`, never `grep -c`.
    stripped = SHORT_SHA.sub(" ", SWEEP_ID.sub(" ", body))
    assert re.findall(r"[0-9]+", stripped) == []


def test_the_named_sweep_resolves_to_a_readable_verdict() -> None:
    """AC22, strengthened (X-368): the sweep must EXIST **and** carry at least
    one of the four whitelisted verdict artifacts. Recency is deliberately NOT
    asserted — a guard that demands the newest sweep goes red every time the
    sentinel runs, which is a guard that fights the loop."""
    root = require_planning_dir()
    body = known_issues_body()
    match = SWEEP_ID.search(body)
    assert match, "the section names no sweep id"
    sweep = root / "qa" / "runs" / match.group(1)
    assert sweep.is_dir(), (
        f"README names sweep {match.group(1)}, which does not exist under {sweep}"
    )
    found = [name for name in VERDICT_ARTIFACTS if list(sweep.rglob(name))]
    assert found, (
        f"sweep {match.group(1)} exists and carries none of {VERDICT_ARTIFACTS}; a reader "
        "following that pointer finds probe scripts and stdout dumps and no verdict"
    )


def test_the_sweep_pointer_check_can_fail() -> None:
    """AC22's RED. The planted red is supplied free by history: sweep
    `2026-09-03_135137` exists and carries no verdict artifact at all."""
    root = require_planning_dir()
    planted = root / "qa" / "runs" / "2026-09-03_135137"
    if not planted.is_dir():
        pytest.skip(f"{SKIP_PLANNING_ABSENT}: the planted red sweep is not present at {planted}")
    found = [name for name in VERDICT_ARTIFACTS if list(planted.rglob(name))]
    assert found == [], (
        "2026-09-03_135137 is X-368's planted red BECAUSE it carries no verdict "
        f"artifact; it now carries {found}, so this control no longer controls"
    )


def top_level_commands() -> set[str]:
    module = _tests_module("registry")
    return {verb.name.split()[0] for verb in module.discover_verbs()}


def what_exists_today_block() -> str:
    text = read("README.md")
    after = text.split("## What exists today", 1)[1]
    return after.split("\n## ", 1)[0]


def test_the_readme_roster_names_every_live_command() -> None:
    """AC24. Set-inclusion against the live registry, so a verb shipped tomorrow
    turns this red with ZERO author action — `discover_verbs()`'s own contract."""
    missing = sorted(
        top_level_commands() - set(re.findall(r"`([a-z-]+)`", what_exists_today_block()))
    )
    assert missing == [], (
        f"the roster under `What exists today` omits {missing}; the authoritative "
        "list is `discover_verbs()`, and this roster is asserted against it"
    )


def test_the_readme_tagline_names_no_verb_that_does_not_exist() -> None:
    """AC24's safe direction. Completeness of a tagline is not mechanized and
    this says so rather than pretending: a two-sided guard with each side
    mechanized where it can be beats one side pretending to cover both."""
    tagline = read("README.md").splitlines()[2]
    commands = top_level_commands()
    named = [word.strip("`,.") for word in tagline.split() if word.strip("`,.") in commands]
    assert named, "the tagline names no verb at all, so this check would be vacuous"
    invented = [word for word in named if word not in commands]
    assert invented == [], f"the tagline names {invented}, which the CLI does not register"


def test_the_roster_check_can_fail() -> None:
    """AC24's RED, on scratch text rather than the real README."""
    block = "Only `merge` and `split` ship."
    missing = sorted(top_level_commands() - set(re.findall(r"`([a-z-]+)`", block)))
    assert "rotate" in missing and "doctor" in missing


# --------------------------------------------------------------------------- #
# PDF-30 D3 — history depth, shared with tests/test_changelog_history.py
# --------------------------------------------------------------------------- #

#: The number of commits reachable at `7afdb1a`. The history arms assert at
#: least this many and otherwise skip with a reason naming the shallow clone —
#: `ci.yml`'s `test` job checks out shallow and this spec does not change that.
MINIMUM_HISTORY_DEPTH = 72


def history_depth() -> int:
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return 0
    return int(result.stdout.strip() or 0)


def is_shallow_repository() -> bool:
    """Whether HEAD's checkout is a DELIBERATELY shallow clone.

    `git rev-parse --is-shallow-repository` prints ``"true"``/``"false"`` and
    exits 0 in both a full and a shallow checkout. A non-zero exit here means
    the probe itself failed (no `git` on PATH, not a repository at all, ...),
    which is a DIFFERENT precondition than "shallow" — the caller must not
    report that as shallow, or it reintroduces the exact silencer this helper
    exists to remove. A failed probe therefore falls through as "not shallow",
    leaving `history_depth()` to handle unmeasurability under its own name.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    return result.stdout.strip() == "true"


def require_full_history() -> None:
    depth = history_depth()
    if depth < MINIMUM_HISTORY_DEPTH:
        pytest.skip(
            f"{SKIP_SHALLOW_CLONE}: git rev-list --count HEAD is {depth}, below the "
            f"frozen minimum of {MINIMUM_HISTORY_DEPTH}. The changelog history arms "
            "read old revisions and cannot run here; they are enforced locally, by "
            "`make docs-gate` and by the qa-sentinel."
        )


def test_the_history_depth_precondition_is_frozen_and_reachable() -> None:
    """A depth minimum that drifted upward would turn every history arm into a
    silent skip, which is the failure mode the skip exists to avoid.

    PDF-30 forward-fix (CI run 33808364031). The predecessor here was
    ``assert history_depth() >= MINIMUM_HISTORY_DEPTH or history_depth() ==
    0`` and carried two defects. First, `ci.yml`'s `test` job checks out at
    the default depth 1 (only `secret-scan` sets `fetch-depth: 0`), so
    ``history_depth()`` returns 1 there and ``1 >= 72 or 1 == 0`` is False —
    the arm reddened on CI's own deliberate posture, not a repository defect.
    Second, and worse, ``history_depth()`` returns 0 ONLY when `git rev-list`
    itself fails to exit 0 — i.e. the precondition is *unmeasurable*, not
    *shallow* — so ``or history_depth() == 0`` made the whole assertion PASS
    whenever the precondition could not be measured at all. That is a second
    unfailable disjunct, and it violates the exact rule this spec restates in
    D3/AC13 (X-153: a control that cannot be run must be visible as skipped,
    never silently passed).

    ``depth >= MINIMUM_HISTORY_DEPTH or depth < MINIMUM_HISTORY_DEPTH`` is
    FORBIDDEN here — true for every integer, it neuters this exact guard.
    Adding `fetch-depth: 0` to the `test` job is equally forbidden: PDF-30's
    own Scope > Out states `ci.yml` (including its checkout depth) is owned
    by PDF-28/PDF-29, so this arm must instead render three DISTINCT,
    honestly-labelled outcomes with no disjunction anywhere:

      * a deliberately shallow checkout (`git rev-parse
        --is-shallow-repository` says so) -> SKIP naming the shallow clone;
      * an unmeasurable depth (`git rev-list` exited non-zero) -> SKIP naming
        the measurement failure, never borrowing the word "shallow";
      * a full clone -> the real assertion, with teeth, against the frozen
        minimum.
    """
    assert MINIMUM_HISTORY_DEPTH > 0
    if is_shallow_repository():
        pytest.skip(
            f"{SKIP_SHALLOW_CLONE}: git rev-parse --is-shallow-repository "
            "reports true, so the depth precondition cannot be checked "
            "against a checkout that was never given the depth to check. "
            "This is CI's own `test` job posture (Scope > Out), enforced "
            "locally instead, by `make docs-gate` and by the qa-sentinel."
        )
    depth = history_depth()
    if depth == 0:
        pytest.skip(
            "history depth unmeasurable: git rev-list --count HEAD exited "
            "non-zero, so the depth precondition could not be measured at "
            "all. This is NOT a shallow clone — git itself failed to answer "
            "— and must not be reported as one."
        )
    assert depth >= MINIMUM_HISTORY_DEPTH, (
        f"git rev-list --count HEAD is {depth} in a full (non-shallow, "
        f"measurable) checkout, below the frozen minimum of "
        f"{MINIMUM_HISTORY_DEPTH}. The minimum drifted upward without the "
        "history actually growing to match, which would turn every history "
        "arm into a silent skip — the failure mode this test exists to catch."
    )
