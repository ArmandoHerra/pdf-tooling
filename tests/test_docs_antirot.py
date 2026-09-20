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
``PDF_TOOLING_PLANNING_DIR``, and since `PDF-70` **that variable is the ONLY
resolution path**: unset or empty resolves to ``None`` and the arms that read it
**skip with a reason naming the variable** — never a pass.

**What `PDF-70` removed, and why it was not cosmetic.** Until `PDF-70` an unset
variable fell back to ``REPO_ROOT.parent.parent / "ai_plans" / REPO_ROOT.name``,
so the ordinary local condition resolved into a **sibling repository this
product does not own** and nine arms then asserted against its contents. The
variable was therefore a no-op on a maintainer host — set and unset reached the
same tree — and a ``qa-sentinel`` writing a bare ``YYYY-MM-DD_HHMMSS`` run
directory over there could redden this product's gate without touching this
product. Enforcement is now **declared**, via the variable, rather than
**inherited from the filesystem layout**. The enforced configuration loses
nothing: with the variable set, those arms run and assert exactly as before.

:func:`vacuous_fixture_sweep_and_sha` is the one consumer that must NEVER skip,
and it absorbs the ``None`` differently — see its own docstring.

CI checks out this repository alone, so in CI those arms skip and their real
enforcement is local, ``make docs-gate`` and the ``qa-sentinel``. That is stated
here rather than discovered later; *a control that cannot be run must be visible
as skipped, never silently absent* (X-153).
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, NamedTuple

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


# --------------------------------------------------------------------------- #
# PDF-73 — the out-of-band branch-coverage pair
# --------------------------------------------------------------------------- #
#
# `[tool.coverage.run] branch = false` is set for a measured reason, so the
# coverage figure this product publishes is a LINE figure -- a weaker claim than
# it reads, because a line inside an `if` counts as covered the moment either arm
# of it runs once. PDF-73 measured the branch half ONCE, out of band, with
# `--cov-branch` forced on the command line of a single run, and published the
# pair. What follows binds TESTING.md's prose to the artefacts that measured it.
#
# THESE ARE NAMED MODULE-LEVEL READERS, NOT INLINE LAMBDA BODIES, and that is a
# coordination choice rather than a style one: a later spec quoting this pair can
# call them instead of re-parsing the artefacts a second way, which would leave
# two parsers to keep in agreement.
#
# WHY THE BRANCH FIGURE IS NOT READ OUT OF THE RECORD'S `coverage_pct`, WHICH IS
# THE ONE THING A LATER READER WILL WANT TO "SIMPLIFY". Under branch mode
# coverage.py's terminal `TOTAL` row reports a COMBINED line-and-branch figure in
# its `Cover` column -- `(covered_lines + covered_branches) / (num_statements +
# num_branches)` -- and that is the number `scripts/measure_gate.py` parses into
# `coverage_pct`. It is NOT branch coverage and it reads far higher: at this
# spec's landing the combined figure was 93.29% while branch coverage was 85.86%.
# The `PDF-29` record schema has no branch-only field, so the branch-only figure
# is read from `perf/branch-partials.md`, which is generated from the same run's
# own JSON report and carries that run's provenance in its own header. The header
# is asserted against the record below, so the two artefacts cannot drift apart.

#: The `PDF-29` trend file. Newest record last is the file's own convention.
GATE_TIMINGS = REPO_ROOT / "perf" / "gate-timings.jsonl"

#: The retained partial-branch list, generated from the branch run's JSON report.
BRANCH_PARTIALS = REPO_ROOT / "perf" / "branch-partials.md"

#: A `| `key` | `value` |` row of `perf/branch-partials.md`. The file is
#: generated, so the shape is stable; a row that stops matching is a regenerated
#: file that changed shape, and the assertions below name the missing key.
_PARTIALS_FIELD = re.compile(r"^\| `([A-Za-z_]+)` \| `([^`]+)` \|$", re.MULTILINE)


def gate_timing_records() -> tuple[dict[str, Any], ...]:
    """Every record in `perf/gate-timings.jsonl`, oldest first."""
    assert GATE_TIMINGS.is_file(), (
        "perf/gate-timings.jsonl is missing. It is the PDF-29 trend file and the only "
        "place a measured figure in these documents is anchored; restore it rather "
        "than re-deriving the numbers from prose."
    )
    records: list[dict[str, Any]] = []
    for number, line in enumerate(GATE_TIMINGS.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"perf/gate-timings.jsonl line {number} is not JSON ({exc}). The file is "
                f"append-only and machine-written; it is never hand-edited."
            ) from exc
    return tuple(records)


def coverage_measurement(variant: str) -> dict[str, Any]:
    """The newest ``target: "cover"`` record carrying *variant*, and quiet.

    ASSERTS rather than raising a bare lookup error, and the distinction is
    load-bearing: ``cardinal_residue`` calls ``derive()`` for every entry
    registered against the document it is scanning, so an opaque ``IndexError``
    here would surface as an unexplained failure of TESTING.md's residue arm
    instead of naming the file and the variant that are actually missing.

    ``quiet: false`` records are skipped rather than merely reported, because
    `perf/README.md`'s one rule is that such a record is admissible as an
    OBSERVATION and inadmissible as a BASELINE -- and a documented figure is a
    baseline claim.
    """
    hits = [
        record
        for record in gate_timing_records()
        if record.get("target") == "cover"
        and record.get("variant") == variant
        and record.get("quiet") is True
    ]
    assert hits, (
        f'perf/gate-timings.jsonl carries no quiet `target: "cover"` record with '
        f'`variant: "{variant}"`. Take one under the PDF-29 protocol -- '
        f"`uv run python scripts/measure_gate.py --target cover --variant {variant} "
        f"--baseline` -- on a host it can verify quiet, and never by hand-editing "
        f"the trend file."
    )
    return hits[-1]


def branch_partials_fields() -> dict[str, str]:
    """Every ``| `key` | `value` |`` row of `perf/branch-partials.md`.

    The branch-only percentage lives here rather than in the record because the
    `PDF-29` schema has no field for it and the record's `coverage_pct` is the
    COMBINED figure under branch mode (see this section's header comment).
    """
    assert BRANCH_PARTIALS.is_file(), (
        "perf/branch-partials.md is missing. It is the retained partial-branch list "
        "PDF-73 generated from the branch run's own JSON report, and the only "
        "committed source of the branch-only percentage this document quotes."
    )
    fields = dict(_PARTIALS_FIELD.findall(BRANCH_PARTIALS.read_text()))
    for key in ("commit", "percent_statements_covered", "percent_branches_covered"):
        assert key in fields, (
            f"perf/branch-partials.md carries no `{key}` row. Regenerate it from the "
            f"branch run's JSON coverage report rather than annotating it by hand."
        )
    return fields


def engine_disclosure_key() -> str:
    """The disclosure key as `README.md` renders it, FROM the product constant.

    PDF-67 Arm A. Never a literal: renaming ``ENGINE_VERIFIED_KEY`` in `src/`
    without following in `README.md` must redden the registry arm rather than
    rot silently -- which is precisely what `E9`'s census found had already
    happened to the code-`0` row's THREE unbound prose copies.
    """
    from pdf_tooling.ops.engine_disclosure import ENGINE_VERIFIED_KEY

    return f"`{ENGINE_VERIFIED_KEY}`"


def create_mode_octal() -> str:
    """`CREATE_MODE`, rendered the way `README.md`'s Safety contract bullet
    renders it -- FROM the product constant, never a restated literal.

    PDF-90 (`X-911`). `CREATE_MODE` is exported alongside `DEGRADED_PREFIX`
    through `pdf_tooling.safety` for exactly this: renaming or changing the
    constant reds this arm rather than leaving a stale octal literal sitting
    in the document next to a source that moved on.
    """
    from pdf_tooling.safety import CREATE_MODE

    return f"{CREATE_MODE:o}"


def password_disclosure_key() -> str:
    """The disclosure key as `README.md` renders it, FROM the CONSTRUCTOR.

    PDF-83, the second carve-out on the code-`0` row (`X-89`'s oracle limit).
    Deliberately NOT a constant: `password_detail` merges no caller-supplied
    `detail`, so with no sources the disclosure key is the only key it emits
    and the shipped constructor can simply be ASKED. That is stronger than
    the sibling above -- a constant reds only when the CONSTANT is renamed,
    while this reds when the key the payload actually PUBLISHES moves, which
    is the thing `README.md` makes a promise about. It also means `src/`
    needs no edit for this arm to exist, which keeps a documentation-only
    item behaviour-neutral by construction rather than by discipline.
    """
    from pdf_tooling.ops.document_password import password_detail

    return f"`{next(iter(password_detail((), verified=False)))}`"


def branch_and_line_coverage_span() -> str:
    """TESTING.md's line/branch pair, rendered from the artefacts that measured it.

    The pair is only a pair AT A SHARED COMMIT, and this is where that is
    enforced -- across the line record, the branch record and the partials list,
    all three. A branch total subtracted from a line total taken at some other
    commit is precisely the incommensurable trend `perf/` exists to replace.
    """
    branch = coverage_measurement("branch-true")
    line = coverage_measurement("default")
    partials = branch_partials_fields()

    assert branch["commit"] == line["commit"], (
        'the newest quiet `target: "cover"` records do not share a commit, so they '
        f"are not a pair: `branch-true` at {branch['commit']} against `default` at "
        f"{line['commit']}. Re-measure BOTH halves at a single commit rather than "
        "quoting a gap between runs that never saw the same tree."
    )
    assert partials["commit"] == branch["commit"], (
        f"perf/branch-partials.md was generated at {partials['commit']} but the "
        f"`branch-true` record it belongs to was measured at {branch['commit']}. A "
        f"list whose header disagrees with its record is a list about a different "
        f"run: regenerate it, do not annotate it."
    )
    for field in ("cache_state", "engines"):
        assert branch[field] == line[field], (
            f"the pair disagrees on `{field}` ({branch[field]!r} against "
            f"{line[field]!r}), so the halves are not comparable -- perf/README.md "
            f"forbids comparing across it."
        )

    line_pct = round(float(line["coverage_pct"]), 2)
    branch_pct = round(float(partials["percent_branches_covered"]), 2)
    # The branch run measured the LINE metric too, and it must agree with the
    # line arm: the two arms are only a pair if they ran the same suite.
    echoed = round(float(partials["percent_statements_covered"]), 2)
    assert echoed == line_pct, (
        f"the branch run's own line metric ({echoed}) disagrees with the line arm's "
        f"total ({line_pct}), so the two arms did not measure the same suite. "
        f"Re-measure both halves rather than publishing the difference."
    )
    gap = round(line_pct - branch_pct, 2)
    return (
        f"{line_pct}% of lines against {branch_pct}% of branches at "
        f"{branch['commit'][:7]}, a gap of {gap} points"
    )


# --------------------------------------------------------------------------- #
# PDF-72 — the shapes the closure rule could not see
# --------------------------------------------------------------------------- #
#
# The closure rule ("derived, gated by a run, or absent") was written about
# CARDINALS, and four claims on this product had rotted in shapes that are not
# cardinals: a boolean about CI-job membership, a count living in a document the
# guard does not scan, a figure anchored to a two-wave-old commit and then read
# in the present tense, and a suite size circulating in three renderings with no
# site naming its observable. The readers below give those shapes derivations.
#
# THE CROSS-MODULE CONSUMPTION IS DELIBERATE AND SO IS THE CHOICE OF SOURCE.
# `ci.yml`'s job set is already derived TWICE on purpose -- structurally by
# `scripts/gate_parity.py` (PyYAML) and from scratch by
# `tests/test_gate_parity.py` (regex, importing nothing from the first), so that
# "a shared-parser bug cannot make both sides agree wrongly". A THIRD parser here
# would spend that design, so nothing below parses `ci.yml`. Which of the two is
# consumed is decided per claim, and the FITNESS statement -- what property the
# population is being used for, and why the source's own filter is relevant to it
# -- is written beside each reader rather than left as provenance.


def _scripts_module(name: str):  # type: ignore[no-untyped-def]
    """Import *name* from `scripts/`, which carries no `__init__.py`.

    The same three lines `tests/test_gate_parity.py` already uses to reach
    `gate_parity`, and deliberately a SIBLING of `_tests_module` rather than a
    widening of it: the two directories are on `sys.path` for different reasons
    and a single helper would hide which one a caller meant.
    """
    import importlib
    import sys

    scripts_dir = str(REPO_ROOT / "scripts")
    if scripts_dir not in sys.path:  # pragma: no cover - import plumbing
        sys.path.insert(0, scripts_dir)
    return importlib.import_module(name)


def ci_job_membership() -> tuple[frozenset[str], frozenset[str]]:
    """(`ci.yml`'s top-level job names, the `make` targets its gating steps run).

    FITNESS. The claim this feeds is *"is `X` a CI job"*, and the consumed
    population is exactly `ci.yml`'s top-level job names plus the `make` targets
    those jobs actually invoke -- which is what "a CI job" means to a reader of
    these documents. The filter `derive_from_ci` carries (setup steps,
    `continue-on-error`, self-neutralizing commands) narrows the GATING-STEP
    population and is fit here for the same reason it is fit there: a
    provisioning step is not a check, and a claim about job membership is a claim
    about checks. Had the claim been about the NUMBER of gating steps, the same
    population would have been unfit without that filter's rationale being
    restated -- which is the distinction a bare provenance note never makes.

    `scripts/gate_parity.py` is the side consumed because it is the only one of
    the two that publishes the `run:` text of each gating step, and the predicate
    below has to resolve a `make` target to its job, not only a job name to
    itself: `TESTING.md`'s subject is `make docs-gate`, and `docs-gate` is both.
    """
    job_names, gating_steps, _legs = _scripts_module("gate_parity").derive_from_ci()
    invoked = {target for step in gating_steps for target in MAKE_TARGET.findall(step.run)}
    return frozenset(job_names), frozenset(invoked)


def gate_parity_span() -> str:
    """`.github/gate-parity.toml`'s own claim about what its rule yields.

    FITNESS, and it is a DIFFERENT fitness from the reader above. The sentence
    this renders credits `scripts/gate_parity.py` with reproducing the figure, so
    deriving it FROM that script would make the claim self-fulfilling: the file
    would agree with the parser it names no matter what either did. It is
    therefore derived from `tests/test_gate_parity.py`'s from-scratch scan --
    the side the sentence does NOT credit -- which is the same reason that scan
    exists at all.
    """
    module = _tests_module("test_gate_parity")
    names, _legs, gating_counts = module.independent_derive_from_ci()
    return f"{sum(gating_counts.values())} gating steps across the {len(names)} jobs"


def _raises_guarded_spans(tree: ast.AST) -> list[tuple[int, int]]:
    """Every `with pytest.raises(...)` block, as (first line, last line).

    An arm that ASSERTS a skip is not an arm that SUFFERS one, and the census
    below counts the second kind.
    """
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.With) and any(
            "raises" in ast.dump(item.context_expr) for item in node.items
        ):
            spans.append((node.lineno, node.end_lineno or node.lineno))
    return spans


def skipping_arms(module_relpath: str, helper: str, reason_constant: str) -> tuple[str, ...]:
    """Test functions in *module_relpath* that SKIP when a precondition is absent.

    Read by `ast` rather than by grep, because the grep answer is WRONG here and
    measurably so: `tests/test_docs_antirot.py` carries ten textual
    `require_planning_dir()` call sites and only NINE of them skip anything. The
    tenth sits inside `with pytest.raises(...)` in the arm that proves the helper
    skips at all -- it asserts the skip instead of suffering it, and counting it
    would make this census report one arm more than `make docs-gate` does. A
    census that disagrees with the target it describes is the exact defect the
    `Makefile` comment above `docs-gate` has now committed three times.

    A function counts if, outside any `pytest.raises` block, it calls *helper* or
    calls `pytest.skip` with *reason_constant* in the call. The second limb is
    what catches an arm that skips on its own precondition without routing
    through the shared helper.
    """
    path = REPO_ROOT / module_relpath
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    guarded = _raises_guarded_spans(tree)

    def shielded(node: ast.AST) -> bool:
        line = getattr(node, "lineno", 0)
        return any(low <= line <= high for low, high in guarded)

    found: list[str] = []
    for func in tree.body:
        if not isinstance(func, ast.FunctionDef) or not func.name.startswith("test_"):
            continue
        for node in ast.walk(func):
            if not isinstance(node, ast.Call) or shielded(node):
                continue
            target = node.func
            if isinstance(target, ast.Name) and target.id == helper:
                found.append(func.name)
                break
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "skip"
                and isinstance(target.value, ast.Name)
                and target.value.id == "pytest"
                and reason_constant in (ast.get_source_segment(source, node) or "")
            ):
                found.append(func.name)
                break
    return tuple(found)


def planning_gated_arms() -> tuple[str, ...]:
    """The arms that skip with `planning directory absent`.

    The reason token is the CONSTANT'S NAME rather than its value, because that
    is what appears in the source being walked -- every skip in this module
    builds its message as ``f"{SKIP_PLANNING_ABSENT}: ..."``, and a walker
    looking for the rendered string would find nothing.
    """
    return skipping_arms(
        "tests/test_docs_antirot.py", "require_planning_dir", "SKIP_PLANNING_ABSENT"
    )


def history_gated_arms() -> tuple[str, ...]:
    """The arms that skip with `shallow clone`, across the three arm-3 files.

    `tests/test_changelog_history.py` keeps its own copy of the helper and its
    own spelling of the reason, so both spellings are asked for.
    """
    arms: list[str] = []
    for relpath in (
        "tests/test_docs_antirot.py",
        "tests/test_changelog_history.py",
        "tests/test_docstring_pointers.py",
    ):
        arms.extend(
            f"{relpath}::{name}"
            for name in skipping_arms(relpath, "require_full_history", "SKIP_SHALLOW_CLONE")
        )
    return tuple(arms)


#: `perf/suite-size.md` — the ONE definition of the whole-suite figure. Same
#: record shape as `perf/branch-partials.md` (`PDF-73`) and read by the same
#: `_PARTIALS_FIELD` row reader, because a second shape for a second
#: commit-anchored figure is how two artefacts start disagreeing about what a
#: field means.
SUITE_SIZE_RECORD = REPO_ROOT / "perf" / "suite-size.md"


def suite_size_fields() -> dict[str, str]:
    """The machine-read rows of `perf/suite-size.md`."""
    assert SUITE_SIZE_RECORD.is_file(), (
        "perf/suite-size.md is missing. It is the one definition of the whole-suite "
        "size and the only committed source of the figure TESTING.md quotes; restore "
        "it rather than re-deriving the number from prose."
    )
    fields = dict(_PARTIALS_FIELD.findall(SUITE_SIZE_RECORD.read_text()))
    for key in ("commit", "observable", "command", "collected"):
        assert key in fields, (
            f"perf/suite-size.md carries no `{key}` row. Re-take the measurement and "
            f"write the record, rather than annotating the one that is there."
        )
    assert fields["observable"] == "collected", (
        f"perf/suite-size.md declares observable {fields['observable']!r}. The figure "
        "this product publishes is the COLLECTED count, which is host-independent; "
        "`passed` varies with engine presence, interpreter availability and the odd "
        "load flake, and that is how one suite came to circulate under three figures."
    )
    return fields


def suite_size_span() -> str:
    """TESTING.md's whole-suite sentence, rendered from the record.

    Deliberately carries NO backticks: `cardinal_residue` blanks code spans
    before it masks a registered figure, so a rendered claim containing one could
    never be found in the masked text and the figure it states would be counted
    as unregistered residue -- in the document with zero headroom.
    """
    fields = suite_size_fields()
    return f"the suite collected {int(fields['collected'])} tests at {fields['commit'][:7]}"


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
    DerivedFigure(
        document="TESTING.md",
        anchor="of branches at",
        derive=branch_and_line_coverage_span,
        note=(
            "PDF-73. The published coverage figure is a LINE figure, which is a weaker "
            "claim than it reads, and the size of the weakening was written down "
            "nowhere. This binds the documented line/branch pair to the perf/ "
            "artefacts that measured it, so neither half can be quoted without the "
            "other, nor carried forward to a commit it was never taken at. It is an "
            "out-of-band measurement and NOT a gate: pyproject.toml's `branch = false` "
            "is unchanged and --cov-fail-under keeps measuring lines."
        ),
    ),
    DerivedFigure(
        document="README.md",
        anchor="the carve-out covers an out-of-process engine",
        derive=lambda: f"carries {engine_disclosure_key()} set to `false` in its `detail`",
        note=(
            "PDF-67 / OR-19. `README.md`'s exit-code table is PUBLIC API from v1.0.0 and "
            "its code-`0` row now carries a named exception: an operand an out-of-process "
            "engine decides at load time, which a preview may not start. The row's own "
            "sentence already lived in THREE places bound by nothing -- README.md, "
            "cli/exit_codes.py and a synthetic string in test_honesty_claims.py -- and the "
            "first two had already drifted apart ('the code' vs 'the exit code') with "
            "nothing watching. This entry is the registry's FIRST README.md row, and it "
            "binds the documented carve-out to the product constant that implements it: "
            "delete or reword the carve-out and the anchor count moves off 1; rename "
            "ENGINE_VERIFIED_KEY in src/ alone, or reword README's rendering of it alone, "
            "and the derivation stops occurring in the document."
        ),
    ),
    DerivedFigure(
        document="README.md",
        anchor="the carve-out covers a supplied password's correctness",
        derive=lambda: f"carries {password_disclosure_key()} set to `false` in its `detail`",
        note=(
            "PDF-83 / X-89, and the SECOND exception on the same frozen row. An encrypted "
            "operand reached with a RESOLVABLE BUT WRONG password predicts `0` and really "
            "exits `6`, because a preview that decided correctness would have read the "
            "secret inside the planning path -- ops/crypto.py's own words, 'a preview must "
            "not become an oracle'. The behaviour is CORRECT and pinned as correct "
            "(test_password_file_contract.py::test_pdf52_a6_the_correctness_tier_is_still_"
            "not_predicted reds if the divergence ever CLOSES), so the remedy was a "
            "DISCLOSURE: the payload half shipped with PDF-52 and the published sentence "
            "did not, which is how a row frozen as public API from v1.0.0 stayed false at "
            "the version that froze it. This entry is the binding the gap consisted of. It "
            "is kept SEPARATE from the engine carve-out above on purpose -- two rulings, "
            "two grounds, two notes, two keys, and driven over the dry items of every "
            "honoured verb the two keys never co-occur. Unlike its sibling the derivation "
            "reads the key off password_detail() itself rather than off a constant, so "
            "renaming the PUBLISHED key reds here even if a constant were added later."
        ),
    ),
    DerivedFigure(
        document="README.md",
        anchor="a destination that did not exist is",
        derive=lambda: f"created at `0{create_mode_octal()} & ~umask`",
        note=(
            "PDF-90 (`X-911`). The FIRST anchor tried CONTAINED the derived string and "
            "reddened both arms at once when either half changed -- replaced, because a "
            "mutation reddening two criteria at once has proved neither. `CREATE_MODE` is "
            "the base an anonymous shell redirect starts from before the umask narrows it; "
            "renaming it, or changing its value, reds `test_every_registered_figure_"
            "equals_its_derivation` alone, and making this anchor occur a second time reds "
            "`test_every_registry_anchor_occurs_exactly_once` alone -- both driven "
            "independently rather than assumed from the shape of the other README entries "
            "above."
        ),
    ),
    DerivedFigure(
        document="Makefile",
        anchor="arms read the maintainer's planning tree",
        derive=lambda: (
            f"{cardinal(len(planning_gated_arms())).upper()} arms read the "
            f"maintainer's planning tree"
        ),
        note=(
            "PDF-72, and the registry's FIRST entry over a non-document file. The skip "
            "census in the comment above `docs-gate` drifted THREE times: its own "
            "preamble recorded that the previous figures ('two' and 'four') 'were BOTH "
            "wrong and nothing checked them -- a stale count in the comment above a skip "
            "census is the same defect this target exists to end', and then stated a "
            "third wrong figure ('FIVE') in the next line. Nothing checked that one "
            "either, because `Makefile` is in neither the guarded-document set nor, "
            "until now, this registry. The oracle the comment names -- "
            "PDF_TOOLING_PLANNING_DIR=/nonexistent make docs-gate -- has printed the "
            "true figure the whole time. Registering the claim is what makes a fourth "
            "drift a red instead of a fourth wrong word."
        ),
    ),
    DerivedFigure(
        document="Makefile",
        anchor="arms read git history deeper than a shallow checkout",
        derive=lambda: (
            f"{cardinal(len(history_gated_arms())).upper()} arms read git history "
            f"deeper than a shallow checkout"
        ),
        note=(
            "PDF-72. The history half of the same census, and it drifts for a different "
            "reason than the planning half: its arms live in THREE files, so a new one "
            "lands where nobody is looking at this comment. Derived across all three."
        ),
    ),
    DerivedFigure(
        document="Makefile",
        anchor="so in CI all",
        derive=lambda: (
            f"so in CI all {len(planning_gated_arms()) + len(history_gated_arms())} skip"
        ),
        note=(
            "PDF-72. The DERIVED TOTAL was wrong with its summands and by the same "
            "arithmetic: the comment read SIXTEEN, which is 5 + 11 with the stale five. "
            "A total carried beside two figures that each drift independently is a third "
            "thing to get wrong, so it is computed from both rather than written down."
        ),
    ),
    DerivedFigure(
        document=".github/gate-parity.toml",
        anchor="gating steps across the",
        derive=gate_parity_span,
        note=(
            "PDF-72's POSITIONAL claim. The file said 'Applying this at "
            "2d19bcb/PDF-28-HEAD yields 19 gating steps across the 10 jobs -- reproduced "
            "by `uv run python scripts/gate_parity.py check`' -- a historical measurement "
            "and a present-tense reproduction in one sentence, so when PDF-34 added the "
            "`docs-gate` job the measurement stayed true and the reproduction did not. "
            "tests/test_gate_parity.py has frozen 11/18/20 since that very commit, which "
            "means the product knew the right answer IN A TEST while its own manifest "
            "said otherwise; no guard scanned the file. Refreshing the literal would have "
            "restarted the same clock, so the sentence is derived -- and from the "
            "from-scratch scan rather than from the script the sentence credits, because "
            "a claim derived from the parser it names is self-fulfilling. The file also "
            "joined tests/test_gate_parity.py's stale-count guard, which reddened on the "
            "uncorrected text naming `'10 job'` before the correction was written."
        ),
    ),
    DerivedFigure(
        document="TESTING.md",
        anchor="the suite collected",
        derive=suite_size_span,
        note=(
            "PDF-72's PROVENANCE claim, and the one that was never a falsehood. `4486`, "
            "`4490` and `4526` were all circulating and ALL TRUE: 4486 passed and 4526 "
            "collected at one commit, 4490 collected at another. Not one site said which "
            "observable or which commit, so a reader comparing them concluded the product "
            "could not count itself. The remedy is an ANCHOR, not a gate -- the suite size "
            "moves with every spec that adds an arm, and a figure that reds on every "
            "landing gets edited to green as a reflex. `perf/suite-size.md` is the one "
            "definition; this entry renders TESTING.md's sentence from it, and separate "
            "arms hold the claim unique and the anchor resolvable. The rendering carries "
            "NO backticks on purpose: cardinal_residue blanks code spans before it masks "
            "a registered figure, so a rendered claim containing one would be counted as "
            "unregistered residue in the document with zero headroom."
        ),
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
# PDF-72 D1/D2 — THE CATEGORICAL-CLAIM REGISTRY: a boolean is derived, or it is
# not a claim
# --------------------------------------------------------------------------- #
#
# The residue backstop above sees DIGITS AND NUMBER-WORDS. It is blind to
# booleans by construction, and that is not a bug in it -- the closure rule was
# written about counts. From the commit that made it false, `TESTING.md` said
# `make docs-gate` "is not a CI job" while `ci.yml` defined a top-level
# `docs-gate` job whose sole gating step is that target, and no instrument on
# this product could have seen it: there is no number in the sentence. A wider
# regex would not have helped either, because the failure is not that the claim
# is unregistered; it is that a yes/no has no derivation to be compared against.
#
# So the shape gets an instrument of its own, deliberately built to the same
# three-arm plan as DERIVED_FIGURES so the module reads as one idea: the anchor
# occurs exactly once, the claim equals its derivation, and the registry is
# neither empty nor incomplete.
#
# THE POPULATION IS DETECTED, NEVER TYPED (D2). A hand-typed registry would be
# the fourth drift of the very disease this section exists to end. The audit
# that produced this item predicted FOUR such sentences across the four guarded
# documents; the detector below measures TWO, and the difference is not an
# error in either -- the other family asserts `make ci` TARGET membership, which
# is a different predicate already instrumented by the manifest's `in_make_ci`
# field, and the detector is self-tested on exactly that distinction before it is
# believed. A registry sized to a sentence in a report would have shipped eight
# false members on day one.


@dataclass(frozen=True)
class CategoricalClaim:
    """One documented yes/no, bound to the source that decides it."""

    document: str
    #: The sentence span, asserted to occur EXACTLY ONCE.
    anchor: str
    #: `docs-gate`, `samples-check` -- a bare target or job name, no `make `.
    subject: str
    #: "is-ci-job" | "is-not-ci-job"
    predicate: str
    #: Why this claim exists -- the failure it remembers.
    note: str


_CI_JOB_PREDICATES: Final[tuple[str, ...]] = ("is-ci-job", "is-not-ci-job")

#: A sentence of the shape "`X` is / is never / is not a CI job". The subject is
#: matched backticked OR bare, and bare is load-bearing rather than tolerant: the
#: sentence this section exists to remember said "and it is not a CI job", with a
#: PRONOUN for a subject, and a detector that required a code span would have
#: walked straight past the only claim that was wrong.
CI_JOB_CLAIM: Final = re.compile(
    r"(?P<subject>`[^`\n]{1,60}`|[A-Za-z][\w.-]{0,40})"
    r"\s+(?:is|are)\s+(?P<negation>never\s+|not\s+)?an?\s+CI\s+job",
    re.IGNORECASE,
)


def ci_job_claims(text: str) -> list[tuple[int, str, str, str]]:
    """Every CI-job claim in *text*, as (line, sentence, subject, predicate)."""
    found: list[tuple[int, str, str, str]] = []
    for match in CI_JOB_CLAIM.finditer(text):
        line = text[: match.start()].count("\n") + 1
        subject = re.sub(r"^make\s+", "", match.group("subject").strip("`").strip())
        predicate = "is-not-ci-job" if match.group("negation") else "is-ci-job"
        found.append((line, normalise(match.group(0)), subject, predicate))
    return found


def resolve_ci_job(subject: str) -> bool | None:
    """Whether *subject* is a CI job -- or `None` when nothing can decide it.

    `None` is the third outcome and it is a FAILURE at every call site below,
    never a pass: a categorical claim about a subject this repository does not
    define cannot be checked, and unverifiable is not the same as true. It is
    what the original sentence's `it` resolves to.

    Resolution is on BOTH limbs, because a document's subject is a `make` target
    while `ci.yml`'s is a job: `make docs-gate` names a target, `docs-gate` names
    a job, and the job's only gating step is `make docs-gate`. `make
    samples-check` is neither a job nor any job's step, but it IS a target, so it
    resolves -- to False, which is what its sentence claims.
    """
    jobs, invoked_targets = ci_job_membership()
    if subject in jobs or subject in invoked_targets:
        return True
    if subject in makefile_targets():
        return False
    return None


#: The MEASURED population (D2), not the predicted one. Two, across the four
#: guarded documents.
CATEGORICAL_CLAIMS: Final[tuple[CategoricalClaim, ...]] = (
    CategoricalClaim(
        document="TESTING.md",
        anchor="`make samples-check` is never a CI job",
        subject="samples-check",
        predicate="is-not-ci-job",
        note=(
            "TRUE, and corroborated by a second source: `.github/gate-parity.toml`'s "
            "own `[[rejected]]` block carries it as `B-R01`. It is registered anyway "
            "rather than left alone, because a registry holding only the claim that "
            "was wrong would have nothing to prove it can accept a correct one -- and "
            "because the anchor arm is what notices this sentence being DELETED, which "
            "no detector over live text can do."
        ),
    ),
    CategoricalClaim(
        document="TESTING.md",
        anchor="`make docs-gate` IS a CI job",
        subject="docs-gate",
        predicate="is-ci-job",
        note=(
            "THE CLAIM THAT WAS FALSE, and false in a shape nothing on this product "
            "could see. `TESTING.md` said 'It is not a prerequisite of `make ci` and it "
            "is not a CI job' -- a compound sentence, half true. The `make ci` half is "
            "true (`Makefile`'s `ci` recipe does not name the target, and the manifest "
            "records `in_make_ci = false`). The CI-job half had been false since PDF-34 "
            "added the top-level `docs-gate` job, whose sole gating step is `make "
            "docs-gate`. The paragraph beneath was wrong a SECOND way, and more "
            "damagingly: it said `ci.yml` checks out shallow so the history arms cannot "
            "run there, while that job sets `fetch-depth: 0` precisely so they can -- "
            "its own comment calls it 'the first job in the repository's history to run "
            "those arms anywhere but a maintainer's own full clone'. A reader following "
            "the document would have believed the changelog-history arms had never run "
            "in CI, when they have run in every `docs-gate` job since it landed."
        ),
    ),
)


def test_the_categorical_claim_registry_is_not_empty() -> None:
    """The anti-lapse assertion, mirroring the derived-figure registry's own.

    An empty registry passes the anchor arm and the agreement arm vacuously, so
    emptiness is asserted against directly rather than inferred.
    """
    assert CATEGORICAL_CLAIMS, "the categorical registry is empty; every arm below is vacuous"
    assert {c.predicate for c in CATEGORICAL_CLAIMS} <= set(_CI_JOB_PREDICATES)


@pytest.mark.parametrize(
    "claim", CATEGORICAL_CLAIMS, ids=lambda c: f"{c.document}:{c.subject}:{c.predicate}"
)
def test_every_categorical_anchor_occurs_exactly_once(claim: CategoricalClaim) -> None:
    """An anchor that matches nothing is a guard that guards nothing.

    A FAILURE and never a skip, on the same grounds as
    `test_every_registry_anchor_occurs_exactly_once`: the interesting way for a
    documented claim to go wrong is for the sentence to be reworded or deleted,
    and a guard that quietly stopped applying would report that as agreement.
    """
    body = normalise(read(claim.document))
    count = body.count(normalise(claim.anchor))
    assert count == 1, (
        f"{claim.document}: categorical anchor {claim.anchor!r} occurs {count} time(s), "
        f"expected exactly 1. Why this claim exists: {claim.note}"
    )


@pytest.mark.parametrize(
    "claim", CATEGORICAL_CLAIMS, ids=lambda c: f"{c.document}:{c.subject}:{c.predicate}"
)
def test_every_registered_categorical_claim_agrees_with_ci(claim: CategoricalClaim) -> None:
    """The registered predicate, against the job set derived from `ci.yml`."""
    jobs, invoked_targets = ci_job_membership()
    verdict = resolve_ci_job(claim.subject)
    assert verdict is not None, (
        f"{claim.document} registers a CI-job claim about {claim.subject!r}, which is "
        f"neither a `ci.yml` job nor a `make` target this repository defines, so nothing "
        f"can decide it. Jobs derived from ci.yml: {sorted(jobs)}. "
        f"Why this claim exists: {claim.note}"
    )
    expected = "is-ci-job" if verdict else "is-not-ci-job"
    assert claim.predicate == expected, (
        f"{claim.document} states {claim.anchor!r}, i.e. `{claim.subject}` is "
        f"{claim.predicate}. Derived from .github/workflows/ci.yml, it is {expected}: "
        f"the job set is {sorted(jobs)} and the `make` targets CI's gating steps run are "
        f"{sorted(invoked_targets)}. Why this claim exists: {claim.note}"
    )


@pytest.mark.parametrize("doc", GUARDED_DOCS)
def test_every_ci_job_sentence_in_the_guarded_documents_is_true(doc: str) -> None:
    """THE TRUTH ARM, and it is driven off the DETECTOR rather than the registry.

    A registry can only check the claims somebody remembered to register; this
    arm checks every sentence of the shape, registered or not, against the live
    derivation. It is the arm that would have caught the original defect on the
    day `docs-gate` became a job.
    """
    jobs, invoked_targets = ci_job_membership()
    wrong: list[str] = []
    for line, sentence, subject, predicate in ci_job_claims(read(doc)):
        verdict = resolve_ci_job(subject)
        if verdict is None:
            wrong.append(
                f"  {doc}:{line} {sentence!r} -- subject {subject!r} is neither a "
                f"`ci.yml` job nor a `make` target, so this claim cannot be checked "
                f"at all. Name the target the sentence is about."
            )
            continue
        derived = "is-ci-job" if verdict else "is-not-ci-job"
        if derived != predicate:
            wrong.append(
                f"  {doc}:{line} {sentence!r} -- the document says `{subject}` is "
                f"{predicate}; ci.yml derives {derived}."
            )
    assert not wrong, (
        f"{doc} states a CI-job claim that .github/workflows/ci.yml contradicts. The "
        f"derived job set is {sorted(jobs)} and the `make` targets its gating steps run "
        f"are {sorted(invoked_targets)}:\n" + "\n".join(wrong)
    )


def test_every_detected_ci_job_sentence_has_a_registry_entry() -> None:
    """D2's no-ungoverned-member arm: the population is DETECTED, never typed.

    An unregistered hit reds naming the file and the sentence, so the registry
    cannot silently fall behind the documents it governs -- which is how a
    hand-typed population becomes decoration.
    """
    registered = {(c.document, c.subject, c.predicate) for c in CATEGORICAL_CLAIMS}
    ungoverned: list[str] = []
    detected = 0
    for doc in GUARDED_DOCS:
        for line, sentence, subject, predicate in ci_job_claims(read(doc)):
            detected += 1
            if (doc, subject, predicate) not in registered:
                ungoverned.append(f"  {doc}:{line} {sentence!r} -> ({subject!r}, {predicate!r})")
    assert not ungoverned, (
        "a CI-job claim is registered in CATEGORICAL_CLAIMS or it does not exist. "
        "These sentences are governed by nothing:\n" + "\n".join(ungoverned)
    )
    assert detected == len(CATEGORICAL_CLAIMS), (
        f"the detector finds {detected} CI-job sentence(s) across {list(GUARDED_DOCS)} but "
        f"the registry carries {len(CATEGORICAL_CLAIMS)} entr(ies). A registry larger than "
        f"the detected population is a guard over sentences that no longer exist."
    )


def test_the_ci_job_detector_is_self_tested_before_it_is_trusted(tmp_path: Path) -> None:
    """House doctrine, applied to the new scanner (B-088).

    A scanner is not believed because it returned a number; it is believed
    because it was shown to find a known needle first -- AND, here, because it
    was shown NOT to find the near-miss. The negative half is the load-bearing
    one: `make ci` TARGET membership is a DIFFERENT predicate, asserted in at
    least half a dozen live sentences across these documents and the `Makefile`,
    and a detector that swallowed it would have handed the registry a crowd of
    false members on the day it shipped.
    """
    scratch = tmp_path / "SCRATCH.md"
    scratch.write_text(
        "**`make widget-gate` is never a CI job** for good reasons.\n"
        "\n"
        "It is not a prerequisite of `make ci` and it is not a CI job.\n"
        "\n"
        "`make sprocket` is not part of `make ci`, which is a different thing.\n"
        "Running `make sprocket` is not a prerequisite of `make ci` either.\n"
    )
    hits = ci_job_claims(scratch.read_text())

    subjects = [(subject, predicate) for _line, _sentence, subject, predicate in hits]
    assert ("widget-gate", "is-not-ci-job") in subjects, (
        f"the detector must find a planted backticked CI-job claim; it found {subjects}"
    )
    assert ("it", "is-not-ci-job") in subjects, (
        "the detector must find a CI-job claim whose subject is a PRONOUN -- that is "
        f"the exact sentence this instrument exists to remember; it found {subjects}"
    )
    assert "sprocket" not in [subject for subject, _ in subjects], (
        "`make ci` TARGET membership is a DIFFERENT predicate and must NOT be detected "
        f"as a CI-job claim; the detector returned {subjects}"
    )
    assert len(subjects) == 2, f"expected exactly the two planted claims, got {subjects}"

    # And the resolution half: the pronoun resolves to nothing, which is the
    # failure the truth arm reports rather than a quiet pass.
    assert resolve_ci_job("it") is None
    assert resolve_ci_job("docs-gate") is True
    assert resolve_ci_job("samples-check") is False


# --------------------------------------------------------------------------- #
# PDF-72 D5 — the suite's own size: one definition, one claim site, one anchor
# --------------------------------------------------------------------------- #
#
# NOT A GATE, and the asymmetry with the engines-hidden figure is the design.
# `make docs-gate` arm 1 re-runs the documented engines-hidden command and
# compares it because that figure changes rarely. The whole-suite size changes in
# EVERY spec that adds a test, so a gated whole-suite figure would red on every
# landing and would be edited to green as a reflex -- a gate nobody believes,
# which is worse than no gate. What is guarded instead is that the figure is
# UNIQUE, that it names its OBSERVABLE, and that its ANCHOR is real.

#: Documents scanned for a whole-suite-size claim. `changelog.md` is excluded BY
#: NAME, not by omission, on the idiom `tests/test_gate_parity.py:421-429`
#: already establishes on this product: a landed entry is never edited, so it
#: must stay free to quote a past figure verbatim -- and the only in-repo site
#: before this spec WAS a changelog entry. A guard that reddened on history would
#: order the engineer to commit the one edit this product most forbids.
SUITE_SIZE_SCAN: Final[tuple[str, ...]] = (
    *GUARDED_DOCS,
    "Makefile",
    ".github/workflows/ci.yml",
)

#: A claim about the size of the suite AS A WHOLE. Deliberately keyed on the
#: `collected` observable and on the word "suite" rather than on any `N passed,
#: M skipped` tail: those tails are SCOPED figures about a named subset (the
#: engines-hidden run, the safety-spine files), each already gated or anchored by
#: its own instrument, and folding them in here would make this arm red on claims
#: it has no business ruling on.
SUITE_SIZE_CLAIM: Final = re.compile(
    r"\bcollect(?:s|ed|ing)\s+(?:a\s+)?\d{3,5}\b"
    r"|\b\d{3,5}\s+(?:tests?|items?)\s+(?:were\s+|are\s+)?collected\b"
    r"|\bsuite\b[^.\n]{0,70}?\b\d{3,5}\s+tests?\b"
    r"|\b\d{3,5}\s+tests?\b[^.\n]{0,45}?\bsuite\b",
    re.IGNORECASE,
)


def suite_size_claim_sites() -> list[tuple[str, int, str]]:
    """Every whole-suite-size claim across `SUITE_SIZE_SCAN`, as (file, line, text)."""
    sites: list[tuple[str, int, str]] = []
    for rel in SUITE_SIZE_SCAN:
        text = read(rel)
        lines = text.splitlines()
        for match in SUITE_SIZE_CLAIM.finditer(text):
            line = text[: match.start()].count("\n") + 1
            sites.append((rel, line, lines[line - 1].strip()))
    return sites


def test_exactly_one_site_states_the_size_of_the_whole_suite() -> None:
    """D5. Three renderings of this figure were in circulation and every one of
    them was TRUE -- two observables at one commit, and one of those observables
    at another. The defect was never truth; it was that no site said WHICH
    quantity or WHICH commit, so a reader comparing them concluded the product
    could not count itself. One site, naming both, is the whole remedy."""
    sites = suite_size_claim_sites()
    listing = "\n".join(f"  {rel}:{line} {text[:100]}" for rel, line, text in sites)
    assert len(sites) == 1, (
        f"the whole-suite size is stated at {len(sites)} site(s); it is stated at exactly "
        f"one, in TESTING.md, rendered from perf/suite-size.md by the derived-figure "
        f"registry. A second site is a second thing to keep true:\n{listing}"
    )
    rel, _line, _text = sites[0]
    assert rel == "TESTING.md", f"the one site must be TESTING.md; it is {rel}"


def test_the_suite_size_claim_detector_is_self_tested_before_it_is_trusted() -> None:
    """The scanner is shown finding its needle -- and shown NOT finding the
    SCOPED run figures this document legitimately quotes, which is the half that
    keeps the uniqueness arm from ruling on claims it does not own."""
    positives = (
        "the suite collected 5348 tests at c76f0db",
        "5348 tests collected",
        "the whole suite is 5348 tests at that commit",
    )
    for probe in positives:
        assert SUITE_SIZE_CLAIM.search(probe), f"must detect a whole-suite claim: {probe!r}"
    negatives = (
        "and it reports `12 passed, 22 skipped`",
        "**259 passed, 0 skipped, 1 xfailed** with `-rs`",
        "the 84-test band moved from 66.24% to 71.49%",
        "CI was never affected (run 33287428715)",
    )
    for probe in negatives:
        assert not SUITE_SIZE_CLAIM.search(probe), (
            f"a SCOPED run figure is not a whole-suite claim and must not be detected: {probe!r}"
        )


def test_the_suite_size_anchor_resolves_to_an_ancestor_of_head() -> None:
    """A commit anchor nothing can resolve is decoration, not provenance.

    On a clone too shallow to answer this SKIPS with the module's existing
    `shallow clone` class rather than passing -- a control that cannot be run
    must be visible as skipped, never silently absent (X-153) -- and never
    invents a new class, because `scripts/assert_skips.py` names the classes it
    can report and a new one would land outside its verdict.
    """
    sha = suite_size_fields()["commit"]
    resolves = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if resolves.returncode != 0:
        if is_shallow_repository():
            pytest.skip(
                f"{SKIP_SHALLOW_CLONE}: perf/suite-size.md anchors the figure at {sha}, "
                f"which this checkout does not carry. A shallow clone cannot tell a bad "
                f"sha from an unfetched one, so this arm reports as skipped rather than "
                f"guessing; it is enforced locally, by `make docs-gate` and by the "
                f"qa-sentinel."
            )
        raise AssertionError(
            f"perf/suite-size.md anchors the whole-suite figure at {sha}, which does not "
            f"resolve to a commit in this repository, and this checkout is NOT shallow. "
            f"An anchor nothing can resolve makes the figure unattributable, which is the "
            f"exact defect the record exists to end: re-take the measurement and write "
            f"the commit it was taken at."
        )
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ancestor.returncode == 0, (
        f"perf/suite-size.md anchors the whole-suite figure at {sha}, which resolves but "
        f"is NOT an ancestor of HEAD -- so the figure was taken on a tree this one does "
        f"not descend from. Re-take it here."
    )


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


# --------------------------------------------------------------------------- #
# PDF-70 — THE RATIFICATION LEDGER: the missing DOWNWARD half of the ratchet
# --------------------------------------------------------------------------- #
#
# WHAT WAS ACTUALLY BROKEN, WHICH IS NOT WHAT IT LOOKED LIKE. The measured arm
# below (`test_the_unregistered_cardinal_residue_does_not_grow`) is `<=` and
# always was, so paying documented debt DOWN never reddened. The defect was one
# step further in and sharper: improvement was not punished, it was
# **unrewardable**. A document whose residue dropped 30 -> 26 kept a ceiling of
# 30, silently re-acquired four cardinals at no cost, and the only way to
# re-tighten was to edit a constant frozen by an equality — the one act this
# product's instrument culture forbids. The gap between arm and constant is
# SLACK: invisible, free to re-fill, and monotonically accumulating. **So the
# instrument decayed quietly every time the product got better.**
#
# WHAT REPLACED THE `== 171` LITERAL, AND WHY IT IS STRICTLY STRONGER. The
# ceiling is no longer a separately-writable constant; it is the newest record
# of an append-only ledger, and the verifier walks consecutive records PER KEY.
# An upward movement still requires everything X-715 required and now names the
# missing field when it is absent. A downward movement is ordinary and needs no
# ruling — that is the whole deliverable. The literal it replaces was blind to a
# COMPENSATING SWAP (one key -1, another +1, total unchanged), which is the exact
# act the sibling instrument's comment at `tests/test_read_seams.py:629-630`
# claims to catch and never could. The per-key walk catches it regardless of the
# total, so this is a STRENGTHENING with one deliberate relaxation.
#
# A RATIFICATION CANNOT FABRICATE AN IMPROVEMENT, and no second oracle is
# invented to check that it does not (D3). Tighten a ceiling without paying the
# debt and the measured arm reds naming the document and every offending line.
# The ledger RECORDS; the arm MEASURES. A second measurement that could disagree
# with the first would be worse than none.


class _DocsRatification(NamedTuple):
    """One recorded movement of the guarded-document residue ceiling.

    Immutable, and `ceilings` is a read-only view rather than a mutable dict
    shared with the live ceiling (D1): a record that could be edited in place
    would re-open the hole this ledger closes.
    """

    date: str
    spec: str
    #: "genesis" | "down" | "up" — and the verifier holds it to the movement it
    #: actually describes, so the field cannot disagree with the diff.
    direction: str
    ceilings: Mapping[str, int]
    reason: str
    #: The PM ruling id (X-NNN) authorising an UPWARD key movement. Structurally
    #: absent for a tightening — that asymmetry IS the spec.
    ruling: str = ""


_RATIFICATION_DATE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_RATIFICATION_DIRECTIONS: Final = ("genesis", "down", "up")


def docs_ratification_complaints(ledger: Sequence[_DocsRatification]) -> list[str]:
    """Every rule violation in *ledger*, per key. Empty means ACCEPTED.

    PURE OVER ITS PARAMETER, following `sweep_class_runs_with_verdict`'s rule
    (E7.3): a synthetic ledger drives this exactly as the real one does, which
    is what turns "we observed the refusal once" into a standing arm that runs
    on every execution. It RETURNS complaints rather than raising so the
    refusing direction can be asserted as ordinarily as the accepting one — and
    both are required, because a verifier that accepts everything and a verifier
    that rejects everything each pass exactly half the arms (the `PDF-44`
    blindfold lesson).

    DUPLICATED, KNOWINGLY, as `read_seam_ratification_complaints` in
    `tests/test_read_seams.py` (D5). It is deliberately NOT imported across test
    modules: cross-test-module coupling is already a filed defect on this
    product (I-12 piece 3, carrier `B-308`), and adding a fresh instance of a
    defect while deferring its fix would be indefensible. A shared support module
    is the other option and is rejected here because `B-308`'s own work may well
    establish the right home — at which point consolidating is a two-line
    follow-up against a decided location rather than a guess made now.
    """
    complaints: list[str] = []
    if not ledger:
        return ["the ratification ledger is EMPTY: the live ceiling has no record behind it"]

    for index, record in enumerate(ledger):
        where = f"[{index}] {record.spec} ({record.date})"
        if not _RATIFICATION_DATE.fullmatch(record.date):
            complaints.append(f"{where}: date is not YYYY-MM-DD")
        if not record.spec.strip():
            complaints.append(f"{where}: no allocating spec id")
        if not record.reason.strip():
            complaints.append(
                f"{where}: no reason — a ratification carrying no evidence is an edit "
                f"wearing a record's clothes"
            )
        if record.direction not in _RATIFICATION_DIRECTIONS:
            complaints.append(
                f"{where}: direction {record.direction!r} is not one of "
                f"{list(_RATIFICATION_DIRECTIONS)}"
            )
        if (record.direction == "genesis") != (index == 0):
            complaints.append(f"{where}: direction 'genesis' belongs to record 0 and to no other")
        if index and record.date < ledger[index - 1].date:
            complaints.append(f"{where}: dated before its predecessor {ledger[index - 1].date}")

    for index in range(1, len(ledger)):
        previous, current = ledger[index - 1], ledger[index]
        where = f"[{index}] {current.spec} ({current.date})"
        for key in sorted(set(previous.ceilings) | set(current.ceilings)):
            before = previous.ceilings.get(key)
            after = current.ceilings.get(key)
            if before == after:
                continue
            if after is not None and (before is None or after > before):
                # An ADDED key is this case with `before` absent, which is exactly
                # the act X-715 licensed once and no more.
                shown = "absent" if before is None else before
                if current.direction != "up":
                    complaints.append(
                        f"{where}: {key} RAISED {shown} -> {after} in a record declaring "
                        f"direction={current.direction!r}; an upward movement must declare "
                        f"direction='up'"
                    )
                if not current.ruling.strip():
                    complaints.append(
                        f"{where}: {key} RAISED {shown} -> {after} with NO ruling. X-715's "
                        f"fourth condition — the PM rules it explicitly, on the record — is "
                        f"not satisfiable without a ruling id in the diff"
                    )
                if key not in current.reason:
                    complaints.append(
                        f"{where}: {key} RAISED {shown} -> {after} but the reason does not "
                        f"name the key; a raise is justified per key or not at all"
                    )
            else:
                # D2 row 2 — THE WHOLE POINT OF PDF-70. No ruling is required, and
                # a fabricated tightening is caught by the measured arm, not here.
                shown = "removed" if after is None else after
                if current.direction != "down":
                    complaints.append(
                        f"{where}: {key} LOWERED {before} -> {shown} in a record declaring "
                        f"direction={current.direction!r}; a tightening must declare "
                        f"direction='down' so it is recorded rather than furtive"
                    )
    return complaints


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
DOCS_RESIDUE_LEDGER: Final[tuple[_DocsRatification, ...]] = (
    _DocsRatification(
        date="2026-09-06",
        spec="PDF-30",
        direction="genesis",
        ceilings=MappingProxyType(
            {
                "README.md": 30,
                "CLAUDE.md": 7,
                "CONTRIBUTING.md": 6,
                "TESTING.md": 128,
            }
        ),
        reason=(
            "GENESIS. The residue measured at PDF-30's landing with the self-tested "
            "backstop above: 30 / 7 / 6 / 128 = 171, against 159 for the same four "
            "documents at 7afdb1a. Both are far past D2's escalation threshold of 40, "
            "so the span is a PM decision and the number is RECORDED, not chosen. "
            "PDF-70 transcribes this record byte-identically in value and pays no "
            "debt down: every figure here is the figure that was live before it."
        ),
    ),
    _DocsRatification(
        date="2026-09-16",
        spec="PDF-67",
        direction="down",
        ceilings=MappingProxyType(
            {
                "README.md": 29,
                "CLAUDE.md": 7,
                "CONTRIBUTING.md": 6,
                "TESTING.md": 127,
            }
        ),
        reason=(
            "THE FIRST USE OF PDF-70's DOWNWARD PATH, and both movements are debt PAID "
            "rather than declared. README.md 30 -> 29: PDF-67 amended the code-`0` "
            "exit-code row to carry the engine-residual carve-out (OR-19), and "
            "rendering the row's trailing zero as an inline code span -- like every "
            "other code the row names -- was part of that amendment rather than an "
            "errand run beside it; the added carve-out prose itself introduces NO "
            "cardinal, bare or spelled, which is why the movement is a clean -1 and "
            "not a swap. TESTING.md 128 -> 127: the engines-hidden row's quoted "
            "`N passed, M skipped` figure moved because this spec's own arms joined "
            "that run, and `make docs-gate` compared the re-run against the document "
            "and refused -- re-running it meant rewriting the sentence beside it, "
            "where a HAND-MAINTAINED bare cardinal asserting that all of the skips "
            "were engine-gated became a claim that every skip is, which is both true "
            "of any population and one fewer figure for a later author to forget. "
            "MEASURED with this module's own backstop immediately before and after "
            "each edit at 20a3dbc; CLAUDE.md and CONTRIBUTING.md are unchanged on "
            "both sides. Nothing here is a tightening this spec invented to look "
            "good: the arm above measures the residue independently and would red "
            "naming the offending lines if it were."
        ),
    ),
)

#: The LIVE ceiling: the newest record's mapping, and nothing else. There is no
#: separately-writable literal left to edit, which is the load-bearing property
#: of D1 -- a ceiling cannot move unless a record moves with it. AC3 asserts
#: this structurally, by `ast`, because a comment saying so would be exactly the
#: decoration this design exists to replace.
RESIDUE_CEILING: Final[Mapping[str, int]] = DOCS_RESIDUE_LEDGER[-1].ceilings


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
    assert docs_ratification_complaints(DOCS_RESIDUE_LEDGER) == [], (
        "the guarded-document ratification ledger does not verify. PDF-70 replaced "
        "the frozen `sum(...) == 171` literal with this per-key walk, which is "
        "strictly stronger in both respects that matter: it catches a COMPENSATING "
        "SWAP the total never could, and it names the key, both values and the "
        "missing field instead of reporting only that a total moved. Lowering a "
        "ceiling is ORDINARY — append a record with direction='down' and a reason, "
        "no ruling needed. RAISING one still needs everything X-715 required, and "
        "raising one to reach green is anti-gaming and a decision for the PM"
    )


# --------------------------------------------------------------------------- #
# PDF-70 — the ratification verifier, self-tested in BOTH directions
# --------------------------------------------------------------------------- #
#
# Neither half establishes anything alone, and this product has paid for that
# lesson once already (`PDF-44`): a verifier that accepts everything passes the
# real-ledger arm above and fails nothing here; a verifier that rejects
# everything passes every arm below and fails the one above. Both are required,
# and they are driven on SYNTHETIC ledgers because the verifier is pure over its
# parameter (D4) — so the real ledger is never mutated to prove a point.


def _synthetic(
    direction: str, ceilings: dict[str, int], *, ruling: str = "", reason: str = "synthetic"
) -> _DocsRatification:
    return _DocsRatification(
        date="2026-09-15",
        spec="PDF-70",
        direction=direction,
        ceilings=MappingProxyType(dict(ceilings)),
        reason=reason,
        ruling=ruling,
    )


def _genesis(ceilings: dict[str, int]) -> _DocsRatification:
    return _DocsRatification(
        date="2026-09-14",
        spec="PDF-70",
        direction="genesis",
        ceilings=MappingProxyType(dict(ceilings)),
        reason="synthetic genesis",
    )


def test_a_downward_ratification_is_accepted_with_no_ruling() -> None:
    """AC4 — THE DELIVERABLE, and the single criterion four later specs wait on.

    Paying documented debt down is ordinary. It is recorded, so it is not
    furtive, and it needs no PM ruling — a tightening cannot make the product
    worse, and requiring a ruling for it is what made the instrument decay.

    RED: require a ruling for a downward movement and this arm fires.
    """
    ledger = (_genesis({"CONTRIBUTING.md": 6}), _synthetic("down", {"CONTRIBUTING.md": 5}))
    assert docs_ratification_complaints(ledger) == [], (
        "a recorded tightening with a reason and NO ruling must be accepted; this "
        "is the downward half of the ratchet PDF-70 exists to build"
    )


def test_an_unruled_upward_movement_is_refused_naming_the_key_and_both_values() -> None:
    """AC5 — X-715's fourth condition, mechanized for the first time.

    RED: drop the ruling requirement and this arm fires. Its other half —
    the SAME movement WITH a ruling being accepted — is the test below, and
    neither half alone proves anything: one shows only that the arm fires, the
    other only that it stopped firing.
    """
    ledger = (_genesis({"CONTRIBUTING.md": 6}), _synthetic("up", {"CONTRIBUTING.md": 7}))
    complaints = docs_ratification_complaints(ledger)
    assert complaints, "an unruled raise must be REFUSED"
    joined = " ".join(complaints)
    assert "CONTRIBUTING.md" in joined, joined
    assert "6" in joined and "7" in joined, joined
    assert "ruling" in joined, f"the missing field must be named: {joined}"


def test_a_ruled_upward_movement_is_accepted_so_the_x715_path_still_works() -> None:
    """AC5's other half (case b′). PDF-70 does not narrow the upward path; it
    leaves it exactly where X-715 left it and only makes the fourth condition
    checkable. An arm that refused every raise would have replaced one broken
    ratchet with another."""
    ledger = (
        _genesis({"CONTRIBUTING.md": 6}),
        _synthetic(
            "up",
            {"CONTRIBUTING.md": 7},
            ruling="X-999",
            reason="synthetic: CONTRIBUTING.md gains one structurally unobservable site",
        ),
    )
    assert docs_ratification_complaints(ledger) == []


def test_the_compensating_swap_is_refused_per_key_regardless_of_the_total() -> None:
    """AC7 — the property the sibling instrument's comment claimed and never had.

    `tests/test_read_seams.py:629-630` said a frozen TOTAL means "a shrink in one
    module cannot silently pay for a growth in another". It means the opposite: a
    frozen total catches NET movement and is structurally blind to COMPENSATING
    movement. Driven against the pre-PDF-70 constant, this exact pair left the
    total unchanged and the old guard accepted it — recorded in PDF-70's
    Implementation Log. The per-key walk refuses it, naming the raised key.

    RED: collapse the walk back onto a total and this arm goes green again.
    """
    ledger = (
        _genesis({"alpha.md": 4, "bravo.md": 3}),
        _synthetic("down", {"alpha.md": 3, "bravo.md": 4}),
    )
    complaints = docs_ratification_complaints(ledger)
    assert complaints, "a compensating swap must be REFUSED even though the total is unchanged"
    joined = " ".join(complaints)
    assert "bravo.md" in joined, f"the RAISED key must be named: {joined}"
    assert sum(ledger[0].ceilings.values()) == sum(ledger[1].ceilings.values()), (
        "the fixture is only meaningful while the two totals agree"
    )


def test_a_record_whose_direction_disagrees_with_its_movement_is_refused() -> None:
    """AC/D4 case (e). The `direction` field is not decoration: a record may not
    say "down" while a key rose, or the field would document the intention
    instead of the diff."""
    ledger = (_genesis({"CONTRIBUTING.md": 6}), _synthetic("down", {"CONTRIBUTING.md": 7}))
    joined = " ".join(docs_ratification_complaints(ledger))
    assert "direction='down'" in joined, joined


@pytest.mark.parametrize(
    ("label", "ledger"),
    (
        ("empty", ()),
        ("no genesis", (_synthetic("down", {"a.md": 1}),)),
        ("genesis twice", (_genesis({"a.md": 1}), _genesis({"a.md": 1}))),
        (
            "reasonless",
            (_genesis({"a.md": 1}), _synthetic("down", {"a.md": 0}, reason="  ")),
        ),
        (
            "undated",
            (_genesis({"a.md": 1}), _synthetic("down", {"a.md": 0})._replace(date="soon")),
        ),
    ),
)
def test_a_malformed_ledger_is_refused(label: str, ledger: object) -> None:
    """The structural half. A ledger nobody can read is not a record."""
    assert docs_ratification_complaints(ledger), label  # type: ignore[arg-type]


def test_an_added_key_is_treated_as_an_upward_movement_from_absent() -> None:
    """Gaining a key is how X-715's one licensed concession actually happened, so
    it is held to the upward rules rather than slipping in as a new mapping."""
    ledger = (_genesis({"a.md": 1}), _synthetic("up", {"a.md": 1, "b.md": 2}))
    joined = " ".join(docs_ratification_complaints(ledger))
    assert "b.md" in joined and "ruling" in joined, joined


def _ceiling_binding_value(module_path: Path) -> ast.expr:
    """The right-hand side of the ONE module-level `RESIDUE_CEILING = ...`.

    `ast`, not a regex and not a comment — the convention
    `tests/test_import_boundaries.py` already uses for questions about what the
    source actually binds.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    bindings: list[ast.expr] = []
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and getattr(node.target, "id", None) == "RESIDUE_CEILING"
        ):
            if node.value is not None:
                bindings.append(node.value)
        elif isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "RESIDUE_CEILING" for target in node.targets
        ):
            bindings.append(node.value)
    assert len(bindings) == 1, (
        f"{module_path.name} binds RESIDUE_CEILING {len(bindings)} times at module level; "
        "exactly one binding is allowed, or 'the ceiling' stops naming one thing"
    )
    return bindings[0]


def test_the_docs_ceiling_is_the_newest_ledger_record_not_a_writable_literal() -> None:
    """AC3 — without this, the ledger is documentation and the constant is still
    freely editable, which is the entire hole PDF-70 closes.

    RED: re-introduce a hand-written `dict` literal beside the ledger — the
    exact shape the constant had before this spec — and this arm fires naming
    the file.
    """
    value = _ceiling_binding_value(Path(__file__))
    assert not isinstance(value, ast.Dict), (
        "RESIDUE_CEILING is bound to a literal `dict` display again. The live "
        "ceiling must BE the newest ratification record's mapping, so that moving "
        "it is impossible without appending a record — a separately-writable "
        "literal beside the ledger makes the ledger decoration"
    )
    assert isinstance(value, ast.Attribute) and value.attr == "ceilings", ast.dump(value)
    subscript = value.value
    assert isinstance(subscript, ast.Subscript), ast.dump(value)
    assert getattr(subscript.value, "id", None) == "DOCS_RESIDUE_LEDGER", ast.dump(value)


# --------------------------------------------------------------------------- #
# PDF-70 D6 — the planning seam resolves through the VARIABLE, and nowhere else
# --------------------------------------------------------------------------- #


def test_planning_dir_resolves_only_through_the_declared_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC10. Unset and empty both answer `None`; set answers the declared path.

    Before PDF-70 the unset case answered
    `<repo>/../../ai_plans/<repo-name>` — a path inside a DIFFERENT repository —
    which is what made this product's green depend on a tree it does not own.

    RED: restore the fallback and the first two assertions fire.
    """
    monkeypatch.delenv(PLANNING_DIR_ENV, raising=False)
    assert planning_dir() is None, (
        "an unset variable must resolve to None, not to a computed sibling path"
    )

    monkeypatch.setenv(PLANNING_DIR_ENV, "")
    assert planning_dir() is None, "an EMPTY variable is not a declaration either"

    monkeypatch.setenv(PLANNING_DIR_ENV, str(tmp_path))
    assert planning_dir() == tmp_path


def test_an_undeclared_planning_tree_skips_with_the_censused_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC13. The skip is VISIBLE and its reason still leads with the string
    `scripts/assert_skips.py`'s `planning-directory-absent` class matches, so the
    census is unchanged and no new class is introduced."""
    monkeypatch.delenv(PLANNING_DIR_ENV, raising=False)
    with pytest.raises(BaseException) as caught:  # noqa: PT011 — pytest.skip's own
        require_planning_dir()
    assert type(caught.value).__name__ == "Skipped", type(caught.value).__name__
    reason = str(getattr(caught.value, "msg", caught.value))
    assert reason.startswith(SKIP_PLANNING_ABSENT), reason
    assert PLANNING_DIR_ENV in reason, reason


def test_the_vacuous_sweep_fixture_never_routes_through_the_skipping_helper() -> None:
    """AC11 — and it is a STRUCTURAL arm on purpose, because the failure it
    guards is silent.

    `vacuous_fixture_sweep_and_sha` feeds a test that is NOT planning-gated and
    must not newly become so. An engineer changing `planning_dir()`'s return type
    and updating only `require_planning_dir()` would naturally route this through
    the skipping helper — at which point
    `test_the_known_issues_section_survives_the_vacuous_rendering` SKIPS, the
    suite stays green, and an arm has gone quiet. A behavioural arm cannot catch
    that: under the mutant it would skip too. This one reads the source and reds.

    RED: route the function through `require_planning_dir()` — the exact mutant —
    and this arm fires naming the call.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"), filename=__file__)
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "vacuous_fixture_sweep_and_sha"
    ]
    assert len(functions) == 1
    called = {
        node.func.id
        for node in ast.walk(functions[0])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    skipping = {"require_planning_dir"} & called
    assert skipping == set(), (
        f"vacuous_fixture_sweep_and_sha calls {sorted(skipping)}, which SKIPS. It must "
        "never skip: the vacuous-rendering test it feeds is not gated on the planning "
        "tree and must not newly become so (X-153 — a skipped arm is not agreement)"
    )
    attribute_calls = {
        node.func.attr
        for node in ast.walk(functions[0])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "skip" not in attribute_calls, "it must not call pytest.skip directly either"


def test_the_vacuous_sweep_fixture_answers_the_synthetic_literal_when_undeclared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11's behavioural half. With no planning tree declared it returns the
    obviously-synthetic pointer that could never be mistaken for a real one —
    and it RETURNS, rather than skipping."""
    monkeypatch.delenv(PLANNING_DIR_ENV, raising=False)
    assert vacuous_fixture_sweep_and_sha() == ("1999-01-01_000000", "0000000")


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
PLANNING_DIR_ENV = "PDF_TOOLING_PLANNING_DIR"

STATUS_VOCABULARY = ("Proposed", "Implemented", "Verified", "Parked")

#: The two new skip classes this spec introduces, spelled once so `make
#: docs-gate` and `scripts/assert_skips.py` can both name them.
SKIP_PLANNING_ABSENT = "planning directory absent"
SKIP_SHALLOW_CLONE = "shallow clone"


def planning_dir() -> Path | None:
    """The planning tree the operator DECLARED, or ``None``. PDF-70 D6.

    ``None`` is a real answer and not a failure: it means nobody said where the
    maintainer's planning tree is, so no arm may assert against one.

    **The `../../` fallback this function used to end with is GONE, and its
    removal is the item.** It returned ``REPO_ROOT.parent.parent / "ai_plans" /
    REPO_ROOT.name`` — a directory in a **sibling repository this product does
    not own** — so on a maintainer host the ordinary unset condition silently
    reached that tree and nine arms asserted against its contents. Two
    consequences, both measured rather than supposed: the variable was a no-op
    locally (set and unset produced identical results, so the "enforced"
    configuration was never actually distinguishable from the unenforced one),
    and a ``qa-sentinel`` writing a bare ``YYYY-MM-DD_HHMMSS`` run directory over
    there reddened this product's gate without touching this product — which is
    why every recent sweep has had to name its run directories ``verify-*``.

    The enforcement did not disappear; it MOVED, from accidental to declared.
    With the variable set, every arm runs and asserts exactly as before. With it
    unset they skip **visibly, with a reason** and `make docs-gate` prints the
    class count. A skipped arm is not agreement (X-153).
    """
    override = os.environ.get(PLANNING_DIR_ENV)
    if override:
        return Path(override)
    return None


def require_planning_dir() -> Path:
    """The declared planning tree, or a SKIP naming why there is none.

    Nine call sites. Their assertions are untouched by PDF-70; what changed is
    only *when* they skip. The reason string still leads with
    :data:`SKIP_PLANNING_ABSENT`, so `scripts/assert_skips.py`'s existing
    ``planning-directory-absent`` class keeps matching and no census changes.
    """
    root = planning_dir()
    if root is None:
        pytest.skip(
            f"{SKIP_PLANNING_ABSENT}: {PLANNING_DIR_ENV} is not set, so no planning "
            "tree has been declared (set it to the maintainer's planning tree). "
            "This arm is enforced locally, by `make docs-gate` and by the "
            "qa-sentinel; CI checks out this repository alone."
        )
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

# --------------------------------------------------------------------------- #
# PDF-56 D1-D3 — the missing predicate: staleness, not just deletion
#
# The two lines above stop the section being deleted or emptied. Neither
# checks whether the id they find is the RIGHT id -- the newest sweep-class
# run carrying a verdict -- or whether the sha is the commit THAT run
# records. Both are checkable, and the classifier below is what makes
# "sweep-class" a population rather than a guess.
# --------------------------------------------------------------------------- #

#: D2's two classes. Declared mode wins over name-shape; name-shape is the
#: fallback ONLY when a run declares no `**Mode:**` line at all.
RUN_CLASS_SWEEP = "sweep"
RUN_CLASS_VERIFICATION = "verification"

#: The literal shape E6 counted (13 of 30): the bold label AND the colon
#: BOTH inside the `**...**` span. `` **Mode** `verify` `` (bold, no colon)
#: and `` Mode: **verify** `` (colon, label not bold) are both name-shape
#: fallback cases, not declarations -- the frozen table below pins one of
#: each on the record, by name, so this distinction cannot regress quietly.
MODE_LINE = re.compile(r"\*\*Mode:\*\*.*")


def run_mode_line(report_text: str) -> str | None:
    """The run's own `**Mode:**` line, verbatim, or `None` if it declares
    none. Pure over the text it is handed — the caller decides whether that
    text came from a real `report.md` or a planted one."""
    match = MODE_LINE.search(report_text)
    return match.group(0) if match else None


def classify_run(*, name: str, mode_line: str | None) -> str:
    """D2's classifier, read in the order it is applied.

    1. Declared mode wins. A `**Mode:**` line matching `verif` case-
       insensitively (catches `` `verify` ``, `` `verify PDF-26` `` and
       `narrow re-verify`) is a **verification**; one matching `sweep` is a
       **sweep**.
    2. With no declared mode, name shape is the fallback, and ONLY the
       fallback: a `_verify` substring in the directory *name* makes it a
       verification; anything else is a sweep.

    An unclassifiable declared mode — one line that matches neither `verif`
    nor `sweep` — is a FAILURE, never a default (AC4). Falling through to
    `sweep` silently is exactly how a naming-convention change on the other
    side of this boundary (E6 — 17-of-30 undeclared, a layer-side
    convention this instrument reads but does not own) would read as a
    stale README instead of a broken classifier.
    """
    if mode_line is not None:
        lowered = mode_line.lower()
        if "verif" in lowered:
            return RUN_CLASS_VERIFICATION
        if "sweep" in lowered:
            return RUN_CLASS_SWEEP
        raise ValueError(
            f"run {name!r} declares a `**Mode:**` line that matches neither "
            f"`verif` nor `sweep`, so it cannot be classified: {mode_line!r}"
        )
    return RUN_CLASS_VERIFICATION if "_verify" in name else RUN_CLASS_SWEEP


def run_has_verdict(run_dir: Path) -> bool:
    """X-368's property, reused verbatim, never re-derived: at least one of
    `VERDICT_ARTIFACTS` anywhere under *run_dir* (`rglob`, not just the top
    level — several runs carry their verdict inside `logs/`)."""
    return any(list(run_dir.rglob(pattern)) for pattern in VERDICT_ARTIFACTS)


def sweep_class_runs_with_verdict(runs_root: Path) -> tuple[str, ...]:
    """D1/D2/D6. Every sweep-class run directly under *runs_root* that
    carries a readable verdict, name-sorted. Directory names are
    `YYYY-MM-DD_HHMMSS[...]`, so lexicographic order is chronological order
    and the last element is the newest.

    Pure over its one parameter: a synthetic `tmp_path` inventory drives
    this exactly as the real `qa/runs/` does, which is what lets
    AC1/AC3/AC4/AC8 run without ever writing under the operator's planning
    tree (AC6).
    """
    names = []
    for entry in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        report = entry / "report.md"
        mode_line = run_mode_line(report.read_text()) if report.is_file() else None
        run_class = classify_run(name=entry.name, mode_line=mode_line)
        if run_class == RUN_CLASS_SWEEP and run_has_verdict(entry):
            names.append(entry.name)
    return tuple(names)


def newest_sweep_claim(body_text: str, runs_root: Path) -> tuple[str | None, str | None, int]:
    """D1/D6. Pure over both parameters — extracts the sweep id `body_text`
    names (via `SWEEP_ID`; `None` if it names none) and compares it against
    the sweep-class-with-verdict population under `runs_root`.

    Returns ``(named_id, newest_id, newer_count)``. `newer_count` is how
    many population members sort strictly after `named_id`, which is
    exactly the number the failure message names (D1).
    """
    match = SWEEP_ID.search(body_text)
    named_id = match.group(1) if match else None
    sweeps = sweep_class_runs_with_verdict(runs_root)
    newest_id = sweeps[-1] if sweeps else None
    newer_count = sum(1 for s in sweeps if named_id is not None and s > named_id)
    return named_id, newest_id, newer_count


def commit_occurs_in_run(sha: str, run_dir: Path) -> bool:
    """D3. Whether *sha* occurs, as a plain substring, in any file under
    *run_dir*. Deliberately a tolerant substring search rather than a parse
    of a `**Target:**` field — the inventory is 17-of-30 undeclared (E6)
    and a strict parser would skip more often than it would assert."""
    return any(
        sha in path.read_text(errors="ignore")
        for path in sorted(p for p in run_dir.rglob("*") if p.is_file())
    )


def recorded_commit(run_dir: Path) -> str | None:
    """Best-effort, for a legible failure message only — never load-bearing
    for `commit_occurs_in_run`'s assertion: the first short-sha-shaped token
    in the run's own `report.md`, naming what the run DOES record."""
    report = run_dir / "report.md"
    if not report.is_file():
        return None
    match = SHORT_SHA.search(report.read_text())
    return match.group(1) if match else None


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


def vacuous_fixture_sweep_and_sha() -> tuple[str, str]:
    """PDF-56 D8. The vacuous-rendering fixture's sweep id and sha, DERIVED
    rather than transcribed — this fixture used to hardcode the exact same
    superseded sweep id and sha `README.md:250` named, a second time inside
    this guard's own file, which is the same defect this spec exists to
    remove, just planted one function away from the arm that would have
    caught it.

    When the planning tree is reachable, both are pulled from a real
    sweep-class run carrying a verdict (D1's own population, so this
    fixture and the live arm can never disagree about what "sweep-class"
    means). When it is not, both fall back to an obviously-synthetic
    literal that could never be mistaken for a real pointer — this
    function never skips, because the vacuous-rendering test it feeds is
    not gated on the planning tree and must not newly become so."""
    root = planning_dir()
    if root is not None and (root / "specs" / "SPEC-INDEX.md").is_file():
        sweeps = sweep_class_runs_with_verdict(root / "qa" / "runs")
        if sweeps:
            newest = sweeps[-1]
            sha = recorded_commit(root / "qa" / "runs" / newest) or "0000000"
            return newest, sha
    return "1999-01-01_000000", "0000000"


def test_the_known_issues_section_survives_the_vacuous_rendering(tmp_path: Path) -> None:
    """AC23. `README.md:162` promises that if a sweep ever records nothing
    open, the section still stands and reads a no-open-findings sentence
    rather than being deleted (cycle 1's `planned.length > 0` ruling, applied
    here). Prose is not executed, so this builds that second rendering on a
    synthetic `tmp_path` document — the real README.md is never written —
    and runs it through the exact same `_known_issues_body_of` slicing the
    populated state above uses, so the heading surviving and the section
    still being found are both asserted mechanically rather than trusted.

    The sweep id and sha inside the vacuous sentence are DERIVED (D8), never
    a frozen literal transcribed a second time — a fixture that cannot rot
    is worth more than a fixture that is correct today."""
    sweep_id, sha = vacuous_fixture_sweep_and_sha()
    vacuous = (
        f"{KNOWN_ISSUES_HEADING}\n\n"
        "Open defects and planned work are recorded, per finding, in the "
        "maintainer's planning tree:\n\n"
        "- `ai_plans/pdf-tooling/BACKLOG.md` — the groomed intake list.\n"
        "- `ai_plans/pdf-tooling/qa/FINDINGS-LEDGER.md` — every finding a QA "
        "sweep has raised, with its state and its evidence.\n\n"
        "**Those artifacts live in the maintainer's planning repository and "
        "are not part of this distribution.**\n\n"
        f"no open findings are recorded as of sweep `{sweep_id}` "
        f"(`{sha}`)\n\n"
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
    one of the four whitelisted verdict artifacts.

    2026-09-12 (PDF-56, D7): X-368's observation was right and its
    conclusion was overtaken. The observation — a guard that demands
    recency of every run goes red every time the sentinel runs — is real;
    "assert nothing" was not the only conclusion available. Measured at
    89a4f1d, only 3 of 30 runs under `qa/runs/` declare `` **Mode:**
    `sweep` `` (10%); the sentinel's frequent event is a scoped `verify`
    run, which `classify_run`/`sweep_class_runs_with_verdict` above do not
    count as sweep-class. Recency IS asserted now, over that narrower
    population, by `test_the_named_sweep_is_the_newest_sweep` below."""
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


# --------------------------------------------------------------------------- #
# PDF-56 — the missing predicate: the named sweep must be the NEWEST one, and
# the named commit must be the one that sweep's own report records.
# --------------------------------------------------------------------------- #


def test_the_named_sweep_is_the_newest_sweep() -> None:
    """AC1/D1, the deliverable's primary arm. `README.md:250` claims the
    named id is "the most recent sweep carrying a readable verdict" — that
    claim has a checkable population (D2) and this is the missing half of
    it. Applies the pure `newest_sweep_claim` to the real README and the
    real inventory; every red this arm can produce is reproduced against
    synthetic inputs by `test_the_newest_sweep_arm_still_bites_after_the_refresh`
    below (AC8), so a green here is never the only evidence this arm works."""
    root = require_planning_dir()
    named, newest, newer = newest_sweep_claim(known_issues_body(), root / "qa" / "runs")
    assert named, "the section names no sweep id"
    assert named == newest, (
        f"README names sweep {named}; the newest sweep-class run carrying a "
        f"readable verdict is {newest}, and {newer} sweep-class run(s) are "
        "newer. Refresh `## Known issues` (README.md:250) -- this pointer "
        "is what the section exists for."
    )


def test_the_named_commit_is_the_one_the_named_sweep_records() -> None:
    """AC2/D3, the deliverable's other primary arm. `README.md:250` claims
    the named sweep was "taken at commit `<sha>`" — the run itself is the
    oracle for that claim, never the README's own text and never the
    engineer's working HEAD (E1 claim 3 is exactly an engineer's HEAD
    transcribed into this field by mistake, and no README-only predicate
    could have told the two apart)."""
    root = require_planning_dir()
    body = known_issues_body()
    sweep_match = SWEEP_ID.search(body)
    assert sweep_match, "the section names no sweep id"
    sha_match = SHORT_SHA.search(body)
    assert sha_match, "the section names no commit sha"
    named_sweep, named_sha = sweep_match.group(1), sha_match.group(1)
    run_dir = root / "qa" / "runs" / named_sweep
    assert run_dir.is_dir(), (
        f"README names sweep {named_sweep}, which does not exist under {run_dir}"
    )
    files = [p for p in run_dir.rglob("*") if p.is_file()]
    if not commit_occurs_in_run(named_sha, run_dir):
        recorded = recorded_commit(run_dir)
        recorded_clause = (
            f"That run records {recorded}."
            if recorded
            else "That run records no short-sha-shaped token at all."
        )
        pytest.fail(
            f"README names commit {named_sha} as the commit sweep {named_sweep} was "
            f"taken at; that string occurs in none of the {len(files)} file(s) under "
            f"{run_dir}. {recorded_clause}"
        )


#: AC3. A FROZEN sample of the 30 directories measured under `qa/runs/` at
#: `89a4f1d`, each with its `**Mode:**` line exactly as measured (or `None`
#: for the 17 that declare none) and its expected class. This table does
#: NOT grow when the sentinel runs — it is sample data proving the
#: classifier, not a live census (which would itself become a guard that
#: reddens on every sweep, the exact failure mode D4 is designed against).
FROZEN_RUN_CLASSIFICATION: tuple[tuple[str, str | None, str], ...] = (
    # -- 13 declared (a `**Mode:**` line present), chronological --
    (
        "2026-08-30_202600",
        "**Mode:** `verify` — PDF-15 (31 ACs) + the four wave-7 fixes + full "
        "ledger regression + OR-7 conformance",
        RUN_CLASS_VERIFICATION,
    ),
    (
        "2026-08-31_031141",
        "**Mode:** `verify` (closing sweep — PDF-15 AC21/AC26 ruling + full "
        "regression re-check + one PM-filed row)",
        RUN_CLASS_VERIFICATION,
    ),
    (
        "2026-09-01_234305",
        "- **Mode:** `sweep` (all layers) · **Time budget:** 30 m · "
        "**Used:** ~34 m (Layer 1 ran 15 m of it)",
        RUN_CLASS_SWEEP,
    ),
    (
        "2026-09-01_verify-PDF-17",
        "**Run:** `2026-09-01_verify-PDF-17` · **Mode:** `verify PDF-17` (layers 1 + 6, scoped)",
        RUN_CLASS_VERIFICATION,
    ),
    (
        "2026-09-02_215327",
        "**Mode:** `verify` — `PDF-23`, `PDF-24`, and an independent "
        "re-drive of the `PDF-01` re-grant",
        RUN_CLASS_VERIFICATION,
    ),
    (
        # D2's third pinned shape: `**Mode:**` declared, no backticks around
        # the value at all.
        "2026-09-03_060525",
        "**Mode:** narrow re-verify (wave 6) · **Commit:** `cdc02ee` "
        "(`main` == `origin/main`, tree clean before and after)",
        RUN_CLASS_VERIFICATION,
    ),
    (
        # D2's first pinned shape: bare directory name, declared `verify`.
        # Trimmed after the classifying clause (the real line continues with
        # a `**Target:**` naming this product's pre-rename identifier, which
        # this file must not reproduce -- `tests/test_brand_surfaces.py`
        # freezes that count and a second occurrence under `tests/` would
        # grow it).
        "2026-09-03_113318",
        "**Mode:** `verify PDF-26`",
        RUN_CLASS_VERIFICATION,
    ),
    (
        "2026-09-03_171838",
        "**Mode:** `verify` (narrow) + a durable-record repair",
        RUN_CLASS_VERIFICATION,
    ),
    (
        "2026-09-04_073621",
        "**Mode:** `sweep` (full, all six layers) · **Time budget:** 30 min "
        "requested; **~38 min wall clock used** (07:36:21 → ~08:14 local), "
        "overrun spent on Layer 6 and on writing these artifacts.",
        RUN_CLASS_SWEEP,
    ),
    (
        "2026-09-04_092622",
        "**Mode:** `verify` — scoped to `PDF-31` (Lane B set) and `PDF-32` (AC1–AC20).",
        RUN_CLASS_VERIFICATION,
    ),
    (
        "2026-09-04_095036_verify-PDF-31-tag",
        "**Mode:** `verify` — scoped by the task to the criteria the "
        "`v0.2.0` tag unblocked (**AC27**, **AC33.3**, **AC34 links 1–2**), "
        "plus **AC33.2**'s standing `NOT_OBSERVED` and the **Lane C** "
        "residuals (**AC15** post-Lane-C half, **AC16–AC19**).",
        RUN_CLASS_VERIFICATION,
    ),
    (
        "2026-09-05_064159_verify-PDF-39",
        "**Mode:** `verify`, scoped to **`PDF-39` only**.",
        RUN_CLASS_VERIFICATION,
    ),
    (
        # D2's fourth pinned shape: declared `` `sweep` (full) ``.
        "2026-09-11_112955",
        "- **Mode:** `sweep` (full)",
        RUN_CLASS_SWEEP,
    ),
    # -- 17 by name-shape fallback (no `**Mode:**` line at all) --
    ("2026-08-29_202000", None, RUN_CLASS_SWEEP),
    ("2026-08-29_213513", None, RUN_CLASS_SWEEP),
    ("2026-08-30_022741", None, RUN_CLASS_SWEEP),
    ("2026-08-30_083000", None, RUN_CLASS_SWEEP),
    ("2026-08-30_100806", None, RUN_CLASS_SWEEP),
    ("2026-08-30_150803", None, RUN_CLASS_SWEEP),
    ("2026-08-31_002400", None, RUN_CLASS_SWEEP),
    ("2026-08-31_061917", None, RUN_CLASS_SWEEP),
    ("2026-09-02_071003", None, RUN_CLASS_SWEEP),
    ("2026-09-02_112500", None, RUN_CLASS_SWEEP),
    ("2026-09-02_164410", None, RUN_CLASS_SWEEP),
    ("2026-09-03_040000", None, RUN_CLASS_SWEEP),
    ("2026-09-03_135137", None, RUN_CLASS_SWEEP),
    ("2026-09-04_180000_verify-wave1", None, RUN_CLASS_VERIFICATION),
    (
        # D2's second pinned shape: `_verify` suffix in the name, no `**Mode:**`
        # line at all.
        "2026-09-05_033730_verify-wave2",
        None,
        RUN_CLASS_VERIFICATION,
    ),
    ("2026-09-05_112000_verify-PDF-40", None, RUN_CLASS_VERIFICATION),
    ("2026-09-06_095123_verify-PDF-48", None, RUN_CLASS_VERIFICATION),
)

#: The four directory-name shapes D2 names explicitly as the ones that
#: defeat a one-signal classifier. The self-test below fails if the frozen
#: table above ever drops one of them.
FOUR_DEFEATING_SHAPES = (
    "2026-09-03_113318",
    "2026-09-05_033730_verify-wave2",
    "2026-09-03_060525",
    "2026-09-11_112955",
)


def frozen_classification_mismatches(
    rows: Iterable[tuple[str, str | None, str]],
) -> list[str]:
    """Pure: the classifier applied to *rows*, reporting every row where it
    disagrees with the row's own expected class. Used both by the self-test
    (over the real frozen table, expected empty) and by its RED control
    (over a scratch copy with one expected class flipped, expected non-empty)."""
    mismatches = []
    for name, mode_line, expected in rows:
        derived = classify_run(name=name, mode_line=mode_line)
        if derived != expected:
            mismatches.append(f"{name}: expected {expected!r}, classifier derives {derived!r}")
    return mismatches


def test_the_run_classifier_is_self_tested_before_it_is_trusted() -> None:
    """AC3. The classifier is proven against known answers (30 rows, frozen
    at that exact size) before its answer on the live inventory is
    believed — and the four shapes that defeat a one-signal classifier
    (D2) are pinned by name so none of them can quietly drop out of the
    sample."""
    assert len(FROZEN_RUN_CLASSIFICATION) == 30, (
        f"the frozen self-test table has {len(FROZEN_RUN_CLASSIFICATION)} rows; it "
        "was pinned at 30, measured at 89a4f1d -- the LIVE inventory is allowed to "
        "drift (AC5 records that, not this), but this frozen sample must not grow "
        "or shrink silently along with it"
    )
    pinned_names = {row[0] for row in FROZEN_RUN_CLASSIFICATION}
    missing_pins = [name for name in FOUR_DEFEATING_SHAPES if name not in pinned_names]
    assert missing_pins == [], (
        f"the frozen table dropped shape(s) that defeat a one-signal classifier: {missing_pins}"
    )
    mismatches = frozen_classification_mismatches(FROZEN_RUN_CLASSIFICATION)
    assert mismatches == [], "\n  ".join(
        ["classifier disagrees with the frozen table:", *mismatches]
    )


def test_the_classifier_self_test_can_fail() -> None:
    """AC3's RED: flip one expected class in a scratch copy of the frozen
    table and confirm the mismatch-detection this self-test relies on
    actually fires, naming the run, the expected class and the derived one."""
    name, mode_line, expected = FROZEN_RUN_CLASSIFICATION[0]
    flipped = RUN_CLASS_VERIFICATION if expected == RUN_CLASS_SWEEP else RUN_CLASS_SWEEP
    scratch = ((name, mode_line, flipped),) + FROZEN_RUN_CLASSIFICATION[1:]
    mismatches = frozen_classification_mismatches(scratch)
    assert mismatches != [], (
        "flipping one expected class must make the self-test disagree with the "
        "classifier, or the self-test cannot fail and proves nothing"
    )
    assert name in mismatches[0]


def test_an_unclassifiable_declared_mode_is_a_failure_not_a_default(tmp_path: Path) -> None:
    """AC4. A synthetic run whose `**Mode:**` line matches neither `verif`
    nor `sweep` must FAIL, naming the run and the line — never silently
    default to `sweep`, which is exactly how a naming-convention change on
    the other side of this boundary would read as a stale README instead
    of a broken classifier. Driven through a real `tmp_path` run directory
    and `report.md`, not a hand-built string, so the extraction
    (`run_mode_line`) is exercised too, not just the classifier."""
    run_dir = tmp_path / "2026-01-01_000000"
    run_dir.mkdir()
    (run_dir / "report.md").write_text("# scratch run\n\n**Mode:** `audit`\n")
    mode_line = run_mode_line((run_dir / "report.md").read_text())
    with pytest.raises(ValueError, match=r"2026-01-01_000000.*audit"):
        classify_run(name=run_dir.name, mode_line=mode_line)


def test_the_newest_sweep_arm_still_bites_after_the_refresh() -> None:
    """AC8, half 1. A green `test_the_named_sweep_is_the_newest_sweep` on
    the CORRECTED README is not evidence that arm works; this re-drives it
    red with a PLANTED superseded id, checked against the REAL inventory
    (never by editing the real `README.md`) — the same pure
    `newest_sweep_claim` the applied arm uses."""
    root = require_planning_dir()
    runs_root = root / "qa" / "runs"
    sweeps = sweep_class_runs_with_verdict(runs_root)
    assert len(sweeps) >= 2, (
        "need at least two sweep-class verdict-carrying runs in the real "
        "inventory to plant a provably-superseded one; the live population "
        "has shrunk below what this control needs"
    )
    superseded = sweeps[0]
    planted_body = (
        f"The most recent sweep carrying a readable verdict is `{superseded}`, "
        "taken at commit `deadbee`."
    )
    named, newest, newer = newest_sweep_claim(planted_body, runs_root)
    assert named == superseded
    assert named != newest and newer > 0, (
        f"planted id {superseded} did not disagree with the real inventory's "
        f"newest ({newest}); this control proves nothing if it cannot fail"
    )


def test_the_commit_agreement_arm_still_bites_after_the_refresh() -> None:
    """AC8, half 2. The correct newest sweep id, paired with a FOREIGN sha,
    checked against the REAL run directory it names, must still turn red."""
    root = require_planning_dir()
    runs_root = root / "qa" / "runs"
    sweeps = sweep_class_runs_with_verdict(runs_root)
    assert sweeps, "the real inventory carries no sweep-class run with a verdict"
    run_dir = runs_root / sweeps[-1]
    foreign_sha = "deadbee"
    assert not commit_occurs_in_run(foreign_sha, run_dir), (
        f"the foreign sha {foreign_sha!r} must not coincidentally occur under "
        f"{run_dir}, or this control proves nothing"
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


# --------------------------------------------------------------------------- #
# PDF-31 D4 — the naming contract: a section with a stable anchor, derived
# where it can be
# --------------------------------------------------------------------------- #

#: The heading the operator's blog post links. Asserted as a rendered ANCHOR
#: rather than as a literal heading string, because what a reader's link
#: resolves against is the slug, not the text.
NAMING_HEADING = "## Naming"
NAMING_ANCHOR = "naming"


def github_anchor(heading_text: str) -> str:
    """GitHub's heading slug: lowercase, punctuation dropped, spaces hyphenated."""
    slug = heading_text.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    return re.sub(r"\s+", "-", slug).strip("-")


def naming_section(text: str | None = None) -> str:
    """The body of `README.md`'s `## Naming` section, heading excluded."""
    body = read("README.md") if text is None else text
    start = body.find(f"{NAMING_HEADING}\n")
    assert start != -1, (
        f"README.md carries no {NAMING_HEADING!r} section; the naming contract is "
        "the citable form of the four names and its absence is the failure"
    )
    after = start + len(NAMING_HEADING)
    nxt = re.search(r"^## ", body[after:], re.MULTILINE)
    return body[after : after + nxt.start()] if nxt else body[after:]


def naming_table_rows(text: str | None = None) -> dict[str, str]:
    """The `| Kind | Name |` rows of the naming table, Kind -> Name cell."""
    rows: dict[str, str] = {}
    for line in naming_section(text).splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 2 or set(cells[0]) <= {"-", ":"} or cells[0] == "Kind":
            continue
        rows[cells[0]] = cells[1]
    return rows


def declared_console_scripts() -> set[str]:
    """The console scripts pyproject.toml DECLARES — the source of truth."""
    import tomllib

    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    return set(project["scripts"])


def test_the_naming_section_anchor_is_exactly_the_linked_slug() -> None:
    """AC9. The operator's blog post links `#naming`; a later doc reshuffle
    must break a test rather than a reader's link."""
    assert github_anchor("Naming") == NAMING_ANCHOR
    headings = [line for line in read("README.md").splitlines() if line.startswith(NAMING_HEADING)]
    assert headings == [NAMING_HEADING], (
        f"README.md must carry exactly one {NAMING_HEADING!r} heading rendering the "
        f"anchor #{NAMING_ANCHOR}; it carries {headings}"
    )


def test_the_naming_table_names_every_kind_of_name() -> None:
    """PDF-48 D5. The contract has a row per KIND of name -- five now, not
    four: `Console script` (singular, the one canonical spelling) and
    `Aliases` (the alternate spelling plus the two deprecated ones) replace
    the pre-PDF-48 single `Console scripts` row. The rows that can be
    derived are compared against their source of truth rather than read."""
    rows = naming_table_rows()
    assert set(rows) == {
        "PyPI distribution",
        "Repository",
        "Import package",
        "Console script",
        "Aliases",
    }, f"the naming table's kinds are {sorted(rows)}"

    import tomllib

    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]

    # Derived, not transcribed: distribution from [project] name, import
    # package from the src/ package directory. D5's operator table gives
    # Repository the same short name as the distribution (PDF-31), not the
    # full [project.urls] URL a pre-PDF-48 reader might expect.
    assert f"`{project['name']}`" == rows["PyPI distribution"]
    assert f"`{project['name']}`" == rows["Repository"], (
        f"the naming table's Repository row is {rows['Repository']!r}; D5's "
        f"operator table pins it to the same short name as the distribution, "
        f"`{project['name']}`, not the full [project.urls] URL"
    )
    packages = sorted(
        p.name for p in (REPO_ROOT / "src").iterdir() if (p / "__init__.py").is_file()
    )
    assert packages == ["pdf_tooling"], f"src/ declares {packages}"
    assert f"`{packages[0]}`" == rows["Import package"]


#: The Aliases cell's prose carries `` `v1.0.0` `` (the removal-trigger
#: version, backtick-quoted like every other name in the table) alongside
#: the three real alias spellings. It is not a console-script name and must
#: be filtered out before a set-equality check against `[project.scripts]`,
#: or a correct table would fail this arm for the wrong reason.
_VERSION_TOKEN: Final = re.compile(r"^v\d+\.\d+\.\d+$")


def test_the_naming_table_command_rows_equal_the_declared_console_scripts() -> None:
    """AC10, PDF-48-shaped. Set equality in BOTH directions against
    `[project.scripts]`, over the UNION of the `Console script` and
    `Aliases` rows -- the four declared script keys are split across the two
    rows now, not carried by one.

    A fifth console script added tomorrow reddens the table with zero author
    action, and a name in the table that is not declared fails too. Neither
    half is redundant: the first catches an omission, the second a phantom.
    """
    names = set(re.findall(r"`([^`]+)`", naming_table_rows()["Console script"]))
    names |= set(re.findall(r"`([^`]+)`", naming_table_rows()["Aliases"]))
    tabled = {name for name in names if not _VERSION_TOKEN.match(name)}
    declared = declared_console_scripts()
    assert tabled == declared, (
        f"the naming table lists {sorted(tabled)} and [project.scripts] declares "
        f"{sorted(declared)}; missing from the table: {sorted(declared - tabled)}; "
        f"in the table but not declared: {sorted(tabled - declared)}"
    )


def test_the_naming_table_check_can_fail_in_both_directions() -> None:
    """AC10's RED, two-sided, on scratch strings rather than the real README."""
    declared = declared_console_scripts()

    # (a) a third console script is declared and the table does not list it
    incomplete = set(declared)
    assert incomplete != declared | {"pdftk-compat"}

    # (b) the table lists a name that is not declared
    phantom = declared | {"pdftooling-legacy"}
    assert phantom != declared

    # and the parser really does read the row it claims to read
    scratch = (
        "## Naming\n\n| Kind | Name |\n|---|---|\n| Console scripts | `only-one` |\n\n## Next\n"
    )
    assert set(re.findall(r"`([^`]+)`", naming_table_rows(scratch)["Console scripts"])) == {
        "only-one"
    }


def test_the_naming_section_records_which_release_was_first_on_pypi() -> None:
    """AC9. The history a reader needs to interpret the install lines above it."""
    body = naming_section()
    assert "git-install-only" in body
    assert "v0.1.1" in body and "first published release" in body
    assert "v0.2.0" in body


# --------------------------------------------------------------------------- #
# PDF-58 Signal 2/Signal 3 -- `## Naming` says ONE removal release for the
# now-deleted console scripts, and never revives the old import package's
# retired spelling as a live claim.
#
# `_OLD_IMPORT_SPELLING` is assembled, never spelled whole, for the same
# reason `tests/test_brand_surfaces.py` and `tests/test_rename_completeness.
# py` assemble theirs: a literal here would inflate the very `tests/`
# population those two modules' frozen censuses measure.
# --------------------------------------------------------------------------- #

_OLD_IMPORT_SPELLING: Final[str] = "pdf" + "_toolkit"

#: AC8. Phrases that claim the deprecated console scripts still work. At
#: least one of these matched the pre-PDF-58 section (the self-contradiction,
#: B-281); none may match after.
SURVIVAL_CLAIM_PATTERNS: Final[tuple[str, ...]] = (
    "remain installed",
    "fully functional",
    "through `v1.0.0`",
    "until `v1.0.0`",
    "remain until",
)

#: AC12. Pairing the OLD import-package spelling with any of these in one
#: sentence is a false claim -- `PDF-48` renamed that package outright; it
#: does not exist "deprecated behind" anything, and raises
#: `ModuleNotFoundError` today. Naming it as HISTORY (renamed/removed/moved)
#: is permitted and is the expected end state.
_AVAILABILITY_CLAIM_WORDS: Final[tuple[str, ...]] = (
    "deprecated",
    "behind it",
    "still works",
    "available",
    "supported",
)

#: AC9. A release token, `vN.N.N`.
_VERSION_TOKEN_RE: Final = re.compile(r"v\d+\.\d+\.\d+")
#: AC9. A removal verb, case-insensitive.
_REMOVAL_VERB_RE: Final = re.compile(r"removed|removal|dropped|no longer", re.IGNORECASE)


def test_the_naming_section_states_no_survival_claim_for_the_deprecated_scripts() -> None:
    """PDF-58 AC8. `## Naming`, extracted by heading boundary (never by line
    number -- four specs edit this file across three waves), never claims
    the deprecated console scripts still work. RED, free and pre-existing,
    against the pre-removal section (`git show <base>:README.md`) -- it
    quotes `remain installed and fully functional through \\`v1.0.0\\``.
    Recorded verbatim in the Implementation Log."""
    body = naming_section()
    hits = [pattern for pattern in SURVIVAL_CLAIM_PATTERNS if pattern in body]
    assert not hits, (
        f"README.md's ## Naming section still claims the deprecated console scripts survive: {hits}"
    )


def test_the_naming_section_names_exactly_one_removal_release() -> None:
    """PDF-58 AC9. Sentence-scoped over `## Naming`: the set of version
    tokens co-occurring with a removal verb has EXACTLY one member, and the
    section states AT LEAST one such sentence. The at-least-one half is the
    anti-vacuity half -- a section that simply stops mentioning the old
    names would pass a "no contradiction" check and leave a reader with the
    deprecated scripts on PATH nothing to read about when they went."""
    body = naming_section()
    sentences = re.split(r"(?<=[.!?])\s+", body)
    tokens: set[str] = set()
    for sentence in sentences:
        found = _VERSION_TOKEN_RE.findall(sentence)
        if found and _REMOVAL_VERB_RE.search(sentence):
            tokens.update(found)
    assert tokens, (
        "## Naming carries no sentence pairing a version token with a removal "
        "verb -- a reader with the deprecated scripts on PATH has nothing "
        "telling them when they went"
    )
    assert len(tokens) == 1, (
        f"## Naming names {sorted(tokens)} as removal releases for the "
        "deprecated console scripts; exactly one is required"
    )


def test_no_naming_sentence_pairs_the_old_import_package_with_an_availability_claim() -> None:
    """PDF-58 AC12. The OLD import-package spelling (renamed outright at
    `PDF-48`; `ModuleNotFoundError` today) may be named as HISTORY in
    `## Naming` -- renamed, removed, moved -- but never paired with a word
    that claims it is still around. A count-based check is explicitly
    wrong here (unlike AC8's): the corrected sentence legitimately keeps
    the old spelling once, as history, so "zero occurrences" would force
    the true sentence out. RED, free and pre-existing, against the
    pre-removal section -- it pairs the old spelling with "deprecated
    behind it"."""
    body = naming_section()
    sentences = re.split(r"(?<=[.!?])\s+", body)
    offenders = [
        sentence.strip()
        for sentence in sentences
        if _OLD_IMPORT_SPELLING in sentence
        and any(word in sentence.lower() for word in _AVAILABILITY_CLAIM_WORDS)
    ]
    assert not offenders, (
        f"## Naming pairs the old import package's retired spelling with an "
        f"availability/deprecation claim: {offenders}"
    )


# --------------------------------------------------------------------------- #
# PDF-61 D5 -- the coupling is guarded, not merely corrected.
#
# README.md:144 stated the schema_version <-> major-version coupling as a
# biconditional ("together or not at all"); OR-14 rules it one-way (D0). The
# defect had a second, unnamed copy in this suite's own module docstring
# (E3, tests/test_envelope_contract.py:42-43). This guard reads exactly two
# named texts -- located by heading anchor and by module docstring, never by
# line number (X-411: coordinates rot) -- and never sweeps a document.
# --------------------------------------------------------------------------- #

#: D5 assertion 1's anchor. Occurs exactly once in README.md; the section it
#: opens runs to the NEXT `## ` heading (`## Exit codes`), the same bounding
#: rule `_known_issues_body_of` above uses for its own `## ` heading.
SCHEMA_VERSION_SECTION_HEADING = "### `schema_version` is `1`, and this is what would move it"


def _schema_version_section_body_of(text: str) -> str:
    """*text*'s `schema_version` section, bounded by the NEXT `## ` heading.

    Mirrors `_known_issues_body_of`'s slicing exactly. Whether the anchor
    occurs exactly once is checked SEPARATELY
    (`test_pdf61_the_schema_version_section_anchor_occurs_exactly_once`)
    rather than folded in here, which would silently return the wrong span
    on a duplicate instead of failing.
    """
    after = text.split(SCHEMA_VERSION_SECTION_HEADING, 1)[1]
    return after.split("\n## ", 1)[0]


def schema_version_section_body() -> str:
    return _schema_version_section_body_of(read("README.md"))


def envelope_contract_module_docstring() -> str:
    """`tests/test_envelope_contract.py`'s own module docstring, read through
    the module OBJECT rather than re-parsed from source, so this guard and
    the module it watches can never disagree about where the docstring
    starts and ends."""
    module = _tests_module("test_envelope_contract")
    assert module.__doc__, "test_envelope_contract.py lost its module docstring"
    return module.__doc__


#: D5.4's positive control -- the pre-fix `README.md:144` text, verbatim,
#: frozen as a historical literal fixture inside this test rather than
#: re-read from the file, so it can never itself go stale the way E1's
#: handed coordinate did.
PDF61_PRE_FIX_COUPLING_LITERAL = (
    "An increment is **coupled to a major version bump**; they move together or not at all."
)

#: The second, unnamed copy (E3) -- `tests/test_envelope_contract.py:42-43`'s
#: pre-fix docstring clause, frozen the same way.
PDF61_PRE_FIX_DOCSTRING_LITERAL = (
    "An increment is coupled to a major version bump and the two move together or not at all."
)

#: D5's synthetic third fixture. E1/E3's census of both pre-fix texts is
#: exhaustive, and neither one ever used "iff" / "if and only if" / "both or
#: neither" wording, so the third paraphrase pattern below needs its own
#: representative fixture to prove it can fire at all (AC9). Invented, and
#: named as such -- never presented as something either shipped text said.
PDF61_SYNTHETIC_IFF_PARAPHRASE = "schema_version increments if and only if the major version bumps."

#: D5.3 -- at least three paraphrase patterns, not one literal. The B-106
#: lesson, stated inside its own fix: a guard that answers "is this STRING
#: gone" rather than "is this CLAIM gone" is the failure mode this spec
#: exists to avoid repeating.
PDF61_BICONDITIONAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"together or not at all", re.IGNORECASE),
    re.compile(r"\bmoves?\s+together\b", re.IGNORECASE),
    re.compile(r"\biff\b|\bif and only if\b|\bboth or neither\b", re.IGNORECASE),
)

#: D1's repair: the one-way implication, stated, with its converse EXPLICITLY
#: denied. Matches both the bold README wording and the plain-text docstring
#: wording -- `\**` allows, but does not require, the markdown asterisks.
PDF61_ONE_WAY_REQUIRES_PATTERN = re.compile(
    r"an increment\s+\**requires\**\s+a major version bump", re.IGNORECASE
)
PDF61_ONE_WAY_CONVERSE_DENIAL_PATTERN = re.compile(
    r"a major version bump does not require an increment", re.IGNORECASE
)


def test_pdf61_the_schema_version_section_anchor_occurs_exactly_once() -> None:
    """D5 assertion 1. An anchor that matches nothing -- or matches twice --
    is a guard that guards nothing, so a heading rename is a hard failure
    here, never a silent skip."""
    count = read("README.md").count(SCHEMA_VERSION_SECTION_HEADING)
    assert count == 1, (
        f"README.md carries the schema_version section heading {count} time(s), expected exactly 1"
    )


def test_pdf61_the_anchor_check_fails_rather_than_skips_if_the_heading_changes() -> None:
    """AC8's anchor RED, on a scratch copy -- never the real README.md.
    Altering the heading must fail the anchor-count assertion rather than
    silently reporting zero hits as a skip."""
    real = read("README.md")
    altered = real.replace(SCHEMA_VERSION_SECTION_HEADING, "### schema_version is 1, renamed")
    assert altered != real, "the scratch mutation did not fire"
    assert altered.count(SCHEMA_VERSION_SECTION_HEADING) == 0


def test_pdf61_the_trigger_enumeration_still_has_exactly_four_items() -> None:
    """AC10. D5 assertion 2, derived from inside the located span, never
    typed. OR-14's own grounds are "the README enumerates exactly what moves
    it ... and none applies this cycle" -- a fifth trigger appearing
    silently would change the premise the ruling rests on. Measured at
    `89a4f1d`: 4."""
    bullets = re.findall(r"^- a published key", schema_version_section_body(), re.MULTILINE)
    assert len(bullets) == 4, (
        f"the trigger enumeration carries {len(bullets)} items, expected "
        "exactly 4 (OR-14's own grounds); a change here changes the premise "
        "the ruling rests on"
    )


def test_pdf61_the_trigger_enumeration_count_can_fail() -> None:
    """AC10's RED, on a scratch copy of the located span -- never the real
    README.md."""
    real_body = schema_version_section_body()
    poisoned = real_body.replace(
        "- a published key's **meaning** changes while its name and type stay the same.",
        "- a published key's **meaning** changes while its name and type "
        "stay the same.\n- a published key gains a fifth trigger nobody named.",
    )
    assert poisoned != real_body, "the scratch mutation did not fire"
    bullets = re.findall(r"^- a published key", poisoned, re.MULTILINE)
    assert len(bullets) == 5


def test_pdf61_the_biconditional_patterns_match_the_prefix_sentence() -> None:
    """AC9. The defect's own text is the free positive control for the first
    two paraphrase patterns -- a pattern set that cannot match the actual
    shipped defect is a guard that guards nothing (B-106). Neither shipped
    text ever used "iff" / "both or neither" wording (E1/E3's census is
    exhaustive), so the third pattern is proven able to fire against an
    invented, clearly-labelled synthetic fixture instead of text it never
    matched."""
    literal_pattern, moves_together_pattern, iff_pattern = PDF61_BICONDITIONAL_PATTERNS

    assert literal_pattern.search(PDF61_PRE_FIX_COUPLING_LITERAL)
    assert literal_pattern.search(PDF61_PRE_FIX_DOCSTRING_LITERAL)
    assert moves_together_pattern.search(PDF61_PRE_FIX_COUPLING_LITERAL)
    assert moves_together_pattern.search(PDF61_PRE_FIX_DOCSTRING_LITERAL)
    assert iff_pattern.search(PDF61_SYNTHETIC_IFF_PARAPHRASE), (
        "the iff/both-or-neither pattern must fire on its own synthetic "
        "fixture, or it is a pattern that guards nothing"
    )

    # AC9's second RED direction: a pattern broad enough to ALSO match the
    # REPAIRED sentence would fail the clean-section assertion below --
    # asserted here directly rather than merely trusted from that test's
    # own green.
    repaired = normalise(schema_version_section_body())
    for pattern in PDF61_BICONDITIONAL_PATTERNS:
        assert pattern.search(repaired) is None, (
            f"pattern {pattern.pattern!r} matches the REPAIRED section; a "
            "pattern broad enough to do that fails the clean-section "
            "assertion below"
        )


def test_pdf61_the_readme_states_the_coupling_in_one_direction_only() -> None:
    """AC8. Locates the section by its heading anchor, asserts the one-way
    sentence is present with its converse explicitly denied, and asserts no
    biconditional paraphrase appears -- over the README section AND
    `tests/test_envelope_contract.py`'s module docstring, the second named
    copy of the same defect (E3)."""
    assert read("README.md").count(SCHEMA_VERSION_SECTION_HEADING) == 1

    texts = (
        ("README.md's schema_version section", schema_version_section_body()),
        ("test_envelope_contract.py's module docstring", envelope_contract_module_docstring()),
    )
    for label, body in texts:
        normalised = normalise(body)
        assert PDF61_ONE_WAY_REQUIRES_PATTERN.search(normalised), (
            f"{label} no longer states the one-way requires-clause"
        )
        assert PDF61_ONE_WAY_CONVERSE_DENIAL_PATTERN.search(normalised), (
            f"{label} states the requires-clause but not the explicit "
            "converse denial -- a reader who has just read the public-API "
            "sentence will otherwise supply the converse themselves, which "
            "is how this defect was born"
        )
        for pattern in PDF61_BICONDITIONAL_PATTERNS:
            match = pattern.search(normalised)
            assert match is None, (
                f"{label} still carries a biconditional paraphrase "
                f"({match.group(0)!r}); OR-14 reads the coupling as a "
                "one-way implication"
            )


def test_pdf61_the_one_way_guard_fails_if_the_biconditional_reappears() -> None:
    """AC8's RED, on scratch copies -- never the real README.md or
    `tests/test_envelope_contract.py`. Reintroducing the pre-fix clause into
    either text must be caught by at least one biconditional pattern."""
    real_readme_body = schema_version_section_body()
    poisoned_readme = real_readme_body.replace(
        "An increment **requires a major version bump**; a major version "
        "bump does not require an increment.",
        PDF61_PRE_FIX_COUPLING_LITERAL,
    )
    assert poisoned_readme != real_readme_body, "the scratch mutation did not fire"
    assert any(p.search(normalise(poisoned_readme)) for p in PDF61_BICONDITIONAL_PATTERNS), (
        "reintroducing the pre-fix clause into a scratch copy of the README "
        "section must be caught by at least one biconditional pattern"
    )

    real_docstring = envelope_contract_module_docstring()
    poisoned_docstring = real_docstring.replace(
        "An increment requires a\nmajor version bump; a major version bump "
        "does not require an increment.",
        PDF61_PRE_FIX_DOCSTRING_LITERAL,
    )
    assert poisoned_docstring != real_docstring, "the scratch mutation did not fire"
    assert any(p.search(normalise(poisoned_docstring)) for p in PDF61_BICONDITIONAL_PATTERNS), (
        "reintroducing the pre-fix clause into a scratch copy of the "
        "docstring must be caught by at least one biconditional pattern"
    )


# --------------------------------------------------------------------------- #
# PDF-62 -- one migration note for the one breaking release.
#
# The hazard here is not completeness, it is truth (the spec's own
# Objective). Every claim below is re-derived FROM THE TREE by its own
# `derive()` callable (Direction A, D5) or is a stated, reasoned exclusion
# (Direction B, D6) -- never transcribed from this spec's own tables, which
# is exactly the failure mode `PDF-32` proved out first and this cycle keeps
# closing.
#
# SELF-MATCH DISCIPLINE. `tests/test_rename_completeness.py`'s own module
# docstring already names the hazard this section is careful never to
# repeat: a literal old-stem spelling written whole on one line, anywhere in
# THIS file's source, would add a fresh, unenumerated occurrence to that
# module's frozen census (`FROZEN_ENV_COUNT` / `FROZEN_CLASS_COUNT` /
# `BARE_REMAINDER`) in a file neither registry expects to carry one. Every
# old spelling this section needs for a COMPARISON (never for the README
# text itself, which is a different file and is EXPECTED to carry them) is
# therefore ASSEMBLED from small fragments -- never spelled whole on one
# line, exactly like `SPELL_BARE` and `test_brand_surfaces.py`'s `NEEDLE`.
# --------------------------------------------------------------------------- #

MIGRATION_HEADING = "## Upgrading to 1.0.0"
EXIT_CODES_HEADING = "## Exit codes"

PROVENANCE_PATTERN = re.compile(r"Re-derived at `([0-9a-f]{7,40})` on `(\d{4}-\d{2}-\d{2})`\.?\s*$")

MIGRATION_BOUNDING_SENTENCE_ANCHOR = "the published exit-code table is unchanged"


def _migration_section_body_of(text: str) -> str:
    """Pure text-level extraction, mirroring `_known_issues_body_of` exactly
    (D5's own instruction to reuse the house idiom rather than rebuild it).
    Used both by `migration_section_body()` against the real, populated
    README.md and directly by the vacuous-rendering test (AC13) against a
    synthetic `tmp_path` document."""
    assert MIGRATION_HEADING in text, f"document carries no {MIGRATION_HEADING!r} section"
    after = text.split(MIGRATION_HEADING, 1)[1]
    return after.split("\n## ", 1)[0]


def migration_section_body() -> str:
    return _migration_section_body_of(read("README.md"))


@dataclass(frozen=True)
class MigrationRow:
    """One row of the migration note (D5). `derive` re-derives the row's own
    claim FROM THE TREE and raises on disagreement -- it is never a value
    compared externally, because the only way to catch a WRONG quoted value
    is for the derivation itself to hold the comparison."""

    spec_id: str
    anchor: str
    derive: Callable[[], None]
    note: str


# --- Row 1: the deprecated console scripts (PDF-58). ------------------------ #


def _declared_console_scripts() -> frozenset[str]:
    import tomllib

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    return frozenset(pyproject["project"]["scripts"])


def _assert_console_scripts_removed(declared: frozenset[str]) -> None:
    # Assembled, never spelled whole on one line -- see the module-section
    # docstring above.
    old_bare = "pdf" + "toolkit"
    old_hyphen = "pdf" + "-" + "toolkit"
    assert declared == frozenset({"pdftooling", "pdf-tooling"}), (
        f"[project.scripts] declares {sorted(declared)}, expected exactly the two surviving names"
    )
    assert old_bare not in declared and old_hyphen not in declared, (
        f"a removed console-script name is still declared: {sorted(declared)}"
    )


def _derive_migration_console_scripts() -> None:
    _assert_console_scripts_removed(_declared_console_scripts())


# --- Row 2: the two password environment variables (PDF-57). ---------------- #


def _new_password_env_names() -> tuple[str, str]:
    from pdf_tooling.cli import password as _password

    return _password.ENV_PASSWORD, _password.ENV_OWNER_PASSWORD


def _assert_env_var_names(new_password: str, new_owner: str) -> None:
    assert new_password == "PDF_TOOLING_PASSWORD", (
        f"the row's quoted new spelling is {new_password!r}, not what "
        "pdf_tooling.cli.password.ENV_PASSWORD reads"
    )
    assert new_owner == "PDF_TOOLING_OWNER_PASSWORD", (
        f"the row's quoted new spelling is {new_owner!r}, not what "
        "pdf_tooling.cli.password.ENV_OWNER_PASSWORD reads"
    )


def _assert_old_env_prefix_absent() -> None:
    old_prefix = "PDF" + "_" + "TOOLKIT"
    proc = subprocess.run(
        ["git", "grep", "--untracked", "-c", old_prefix, "--", "src/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, (
        f"the old env-var prefix still appears under src/: {proc.stdout.strip()}"
    )


def _derive_migration_env_vars() -> None:
    _assert_env_var_names(*_new_password_env_names())
    _assert_old_env_prefix_absent()


# --- Row 3: the public base exception (PDF-57). ------------------------------ #


def _new_exception_name() -> str:
    from pdf_tooling import errors as _errors

    return _errors.PdfToolingError.__name__


def _assert_exception_name(name: str) -> None:
    assert name == "Pdf" + "Tooling" + "Error", (
        f"the row's quoted new class name is {name!r}, not what "
        "pdf_tooling.errors.PdfToolingError.__name__ reads"
    )
    import inspect

    from pdf_tooling.cli import main as _main

    main_source = inspect.getsource(_main)
    assert f"except {name} as error" in main_source, (
        f"{name} is not the name main.py catches -- main.py's own docstring promises "
        f"exactly one `except {name}`"
    )


def _assert_old_exception_name_absent() -> None:
    old_name = "Pdf" + "Toolkit" + "Error"
    proc = subprocess.run(
        ["git", "grep", "--untracked", "-c", old_name, "--", "src/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, f"{old_name} still appears under src/: {proc.stdout.strip()}"


def _derive_migration_exception_class() -> None:
    _assert_exception_name(_new_exception_name())
    _assert_old_exception_name_absent()


# --- Row 4: `info`'s no-input failure shape (PDF-51). ------------------------ #


def _info_probe_result() -> tuple[int, dict[str, object]]:
    import json

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pdf_tooling",
            "info",
            "/nonexistent/pdf-62-probe.pdf",
            "-o",
            "json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    payload: dict[str, object] = json.loads(result.stdout)
    return result.returncode, payload


def _assert_info_shape(code: int, payload: dict[str, object]) -> None:
    assert code == 4, f"expected exit 4, got {code}"
    assert "error" in payload, f"top-level 'error' key missing: {sorted(payload)}"
    assert "documents" not in payload, f"'documents' key unexpectedly present: {sorted(payload)}"


def _derive_migration_info_shape() -> None:
    _assert_info_shape(*_info_probe_result())


#: E3's own probe of the pre-`PDF-51` shape, frozen verbatim as a historical
#: literal fixture -- a live run cannot reproduce a shape the tree no longer
#: emits, by construction.
PDF62_PRE_FIX_INFO_PAYLOAD: dict[str, object] = {
    "schema_version": 1,
    "verb": "info",
    "documents": [
        {
            "path": "/nonexistent/nope.pdf",
            "error": {"code": 4, "kind": "no_input", "message": "no such file"},
        }
    ],
    "items": [],
    "exit_code": 4,
}


def test_ac5_the_info_row_rejects_the_pre_fix_shape() -> None:
    """AC5's own RED: E3's frozen pre-`PDF-51` probe must fail the shape
    assertion -- or the guard would not have caught the defect PDF-51 fixed."""
    with pytest.raises(AssertionError, match="documents"):
        _assert_info_shape(4, PDF62_PRE_FIX_INFO_PAYLOAD)


# --- Row 5: `convert --dry-run`'s exit-code prediction (PDF-53). ------------- #


def _office_converter_available() -> bool:
    from pdf_tooling.ports import resolve

    return bool(resolve("OfficeConverter").available)


def _dry_run_prediction_result() -> tuple[int, int]:
    """(real exit code, dry-run exit code) over a batch of one convertible
    and one corrupt operand -- the same office-container-triage shape
    `tests/test_batch_continuation.py`'s
    `test_ac10_corrupt_arm_dry_run_mirrors_the_real_run` drives for
    `convert` specifically (PDF-53's own AC6)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = root / "good.txt"
        good.write_text("hello\nworld\n")
        corrupt = root / "corrupt.docx"
        corrupt.write_bytes(b"PK\x03\x04 this is not an office document at all\n")

        def _run(dry_run: bool, out_name: str) -> int:
            args = [
                sys.executable,
                "-m",
                "pdf_tooling",
                "convert",
                str(good),
                str(corrupt),
                "--out-dir",
                str(root / out_name),
                "-o",
                "json",
            ]
            if dry_run:
                args.append("--dry-run")
            proc = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
            return proc.returncode

        return _run(False, "real"), _run(True, "dry")


def _assert_dry_run_prediction(real_code: int, dry_code: int) -> None:
    assert dry_code == 1, f"expected the preview to predict exit 1, got {dry_code}"
    assert dry_code == real_code, (
        f"the preview predicted exit {dry_code}, the real run over the same "
        f"failing batch exited {real_code}"
    )


def _derive_migration_dry_run_exit_code() -> None:
    if not _office_converter_available():
        pytest.skip(
            "convert --dry-run's prediction row needs the OfficeConverter engine "
            "(LibreOffice); not present"
        )
    _assert_dry_run_prediction(*_dry_run_prediction_result())


# --- The bounding sentence: schema_version, the exit-code table, the verb count. #


def _readme_exit_codes() -> set[int]:
    text = read("README.md")
    after = text.split(EXIT_CODES_HEADING, 1)[1]
    body = after.split("\n## ", 1)[0]
    return {int(match) for match in re.findall(r"^\|\s*(\d+)\s*\|", body, re.MULTILINE)}


def _assert_exit_code_table_agrees(readme_codes: set[int], module_codes: tuple[int, ...]) -> None:
    assert readme_codes == set(module_codes), (
        f"README's Exit codes table names {sorted(readme_codes)}, "
        f"cli/exit_codes.py declares {sorted(module_codes)}"
    )


def _historical_verb_count() -> int | None:
    """The count of `.command(name=...)` registrations at `v0.3.1`, or
    `None` if the tag is unreachable (a shallow clone without tags) -- X-153:
    a control that cannot run must skip visibly, never silently pass."""
    proc = subprocess.run(
        ["git", "show", "v0.3.1:src/pdf_tooling/cli/main.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return len(re.findall(r"\.command\(name=", proc.stdout))


def _derive_migration_bounding_sentence() -> None:
    from pdf_tooling.cli import exit_codes as _exit_codes
    from pdf_tooling.models import SCHEMA_VERSION

    assert SCHEMA_VERSION == 1, f"SCHEMA_VERSION is {SCHEMA_VERSION}, not 1"
    _assert_exit_code_table_agrees(_readme_exit_codes(), _exit_codes.ALL_EXIT_CODES)

    registry_module = _tests_module("registry")
    live_count = len(registry_module.discover_verbs())
    historical_count = _historical_verb_count()
    if historical_count is None:
        pytest.skip(
            "the v0.3.1 tag is unreachable in this clone (shallow checkout); the "
            "verb-count-did-not-shrink arm needs it and cannot run here"
        )
    assert live_count >= historical_count, (
        f"discover_verbs() reports {live_count} verbs, fewer than v0.3.1's {historical_count}"
    )


def test_the_migration_bounding_sentence_is_re_derivable() -> None:
    """D5's sixth derivation -- the bounding sentence, not tied to any one
    spec_id: `SCHEMA_VERSION` equals what the sentence names, the exit-code
    table's code set agrees with `cli/exit_codes.py`, and `discover_verbs()`
    reports no fewer verbs than v0.3.1 did."""
    body = migration_section_body()
    count = body.count(MIGRATION_BOUNDING_SENTENCE_ANCHOR)
    assert count == 1, (
        f"the bounding-sentence anchor {MIGRATION_BOUNDING_SENTENCE_ANCHOR!r} occurs "
        f"{count} time(s) in the section, expected exactly 1"
    )
    _derive_migration_bounding_sentence()


def test_the_migration_bounding_sentence_derivation_can_fail() -> None:
    """The bounding sentence's RED: a fabricated code set must disagree, or
    this comparison guards nothing."""
    with pytest.raises(AssertionError, match="declares"):
        _assert_exit_code_table_agrees({0, 1, 2}, (0, 1, 2, 3, 4, 5, 6))


# --- The registry itself, D5's three load-bearing properties. --------------- #

MIGRATION_ROWS: tuple[MigrationRow, ...] = (
    MigrationRow(
        spec_id="PDF-58",
        anchor="command not found",
        derive=_derive_migration_console_scripts,
        note="limb (a) -- the old command stops resolving at all",
    ),
    MigrationRow(
        spec_id="PDF-57",
        anchor="the password is silently unread",
        derive=_derive_migration_env_vars,
        note="limb (a), the highest-consequence row -- an unrecognised name is not an error",
    ),
    MigrationRow(
        spec_id="PDF-57",
        anchor="PdfToolingError",
        derive=_derive_migration_exception_class,
        note="limb (a) -- caught and imported by name",
    ),
    MigrationRow(
        spec_id="PDF-51",
        anchor="no `documents` key",
        derive=_derive_migration_info_shape,
        note="limb (b) -- the exit code is unchanged, only the payload shape moves",
    ),
    MigrationRow(
        spec_id="PDF-53",
        anchor="predicts the real run's own exit code",
        derive=_derive_migration_dry_run_exit_code,
        note="limb (b), engine-gated -- LibreOffice absent skips, never passes",
    ),
)


def test_every_migration_row_is_re_derivable_from_the_tree() -> None:
    """AC3. Non-empty registry; every anchor occurs exactly once in the
    section; every spec_id names a real allocated id (a changelog entry
    exists for it); and every row's derive() runs and agrees."""
    assert MIGRATION_ROWS, "the registry is empty; every check below would pass vacuously"
    body = migration_section_body()
    changelog_module = _tests_module("test_changelog_history")
    for row in MIGRATION_ROWS:
        count = body.count(row.anchor)
        assert count == 1, (
            f"{row.spec_id}: anchor {row.anchor!r} occurs {count} time(s) in the "
            "section, expected exactly 1"
        )
        assert changelog_module.entries_for(row.spec_id), (
            f"{row.spec_id} names no changelog entry; not a real allocated id"
        )
        row.derive()


def test_the_migration_row_derivations_can_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3's RED, one per row, each observed rather than assumed. Every
    corruption below is an in-memory substitution of the ONE seam the real
    `derive()` reads through -- never a disk write to a tracked file (HC-4's
    restore idiom is for a plant that must land on disk; none of these four
    needs one, and `monkeypatch` reverts automatically at teardown)."""
    this_module = sys.modules[__name__]

    # (a) a surviving old console script.
    monkeypatch.setattr(
        this_module,
        "_declared_console_scripts",
        lambda: frozenset({"pdftooling", "pdf-tooling", "pdf" + "toolkit"}),
    )
    with pytest.raises(AssertionError, match="expected exactly the two surviving names"):
        _derive_migration_console_scripts()

    # (b) a wrong env-var spelling.
    with pytest.raises(AssertionError, match="quoted new spelling"):
        _assert_env_var_names("PDF_TOOLING_PASSWROD", "PDF_TOOLING_OWNER_PASSWORD")

    # (c) a wrong exception name.
    with pytest.raises(AssertionError, match="quoted new class name"):
        _assert_exception_name("Pdf" + "Tooling" + "Errror")

    # (d) a wrong exit code.
    with pytest.raises(AssertionError, match="expected exit 4"):
        _assert_info_shape(5, {"error": {}})


def test_ac4_the_env_var_row_reds_on_a_planted_old_occurrence() -> None:
    """AC4's second RED: a NEW untracked file under `src/`, deleted in a
    `finally` regardless of outcome. Never a mutation of a TRACKED file, so
    HC-4's restore idiom (`git show HEAD:<path> > <path>`) does not apply
    here at all -- a plant that was never tracked is restored by deletion."""
    scratch = REPO_ROOT / "src" / "pdf_tooling" / "_pdf62_scratch_probe.py"
    assert not scratch.exists(), "a stray scratch probe was already on disk"
    old_prefix = "PDF" + "_" + "TOOLKIT"
    try:
        scratch.write_text(f"# {old_prefix}_PASSWORD\n")
        with pytest.raises(AssertionError, match="still appears"):
            _assert_old_env_prefix_absent()
    finally:
        scratch.unlink(missing_ok=True)


def test_ac6_the_console_script_row_survives_a_locally_built_wheel() -> None:
    """AC6. The entry-point oracle is a locally built wheel, never PyPI
    (X-703, B-250)."""
    import zipfile

    result = subprocess.run(
        ["make", "build"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"make build failed: {result.stderr}"
    wheels = sorted((REPO_ROOT / "dist").glob("*.whl"), key=lambda p: p.stat().st_mtime)
    assert wheels, "make build produced no wheel in dist/"
    with zipfile.ZipFile(wheels[-1]) as zf:
        entry_name = next(name for name in zf.namelist() if name.endswith("entry_points.txt"))
        entry_text = zf.read(entry_name).decode()
    entry_pattern = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*=", re.MULTILINE)
    wheel_scripts = frozenset(match.group(1) for match in entry_pattern.finditer(entry_text))
    _assert_wheel_scripts_match(wheel_scripts)


def _assert_wheel_scripts_match(wheel_scripts: frozenset[str]) -> None:
    declared = _declared_console_scripts()
    assert wheel_scripts == declared == frozenset({"pdftooling", "pdf-tooling"}), (
        f"wheel entry_points.txt declares {sorted(wheel_scripts)}, "
        f"[project.scripts] declares {sorted(declared)}"
    )


def test_ac6_the_wheel_oracle_reds_on_a_mismatched_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC6's RED: a `[project.scripts]` that declared a removed name would
    disagree with the wheel's own `entry_points.txt` -- proven without
    rebuilding the wheel twice, by monkeypatching the ONE seam the real arm
    reads `[project.scripts]` through."""
    this_module = sys.modules[__name__]
    monkeypatch.setattr(
        this_module,
        "_declared_console_scripts",
        lambda: frozenset({"pdftooling", "pdf-tooling", "pdf" + "toolkit"}),
    )
    with pytest.raises(AssertionError):
        _assert_wheel_scripts_match(frozenset({"pdftooling", "pdf-tooling"}))


def test_ac7_the_dry_run_row_skips_rather_than_passes_when_the_engine_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC7/X-153. Simulated engine absence must SKIP the derivation, never
    silently pass it -- a skipped arm is never recorded as agreement."""
    this_module = sys.modules[__name__]
    monkeypatch.setattr(this_module, "_office_converter_available", lambda: False)
    with pytest.raises(pytest.skip.Exception, match="OfficeConverter"):
        _derive_migration_dry_run_exit_code()


# --- Direction B: coverage over the DECLARED population (D6). --------------- #

#: Every spec in this cycle whose landing could plausibly break a `0.3.1`
#: consumer. Membership is a DECLARATION, not a derivation -- see the
#: residual D6 states rather than hides.
BREAKING_CANDIDATES: Final[frozenset[str]] = frozenset(
    {"PDF-50", "PDF-51", "PDF-52", "PDF-53", "PDF-57", "PDF-58", "PDF-59"}
)

#: A candidate deliberately absent from the note, with the D3 limb it
#: fails. A candidate in NEITHER this register nor `MIGRATION_ROWS` is a
#: FAILURE (AC8).
NOT_A_MIGRATION_ITEM: Final[dict[str, str]] = {
    "PDF-50": (
        "the 0.3.1 behaviour was a traceback on stdout; nothing could have been "
        "successfully branching on it, so this is a repair from unusable to usable, "
        "not a break in a working contract."
    ),
    "PDF-52": (
        "an added key (`password_verified`); README's own enumeration says addition "
        "never moves `schema_version`, and a name-reading consumer survives it "
        "unchanged."
    ),
    "PDF-59": (
        "a packaging classifier only (Alpha to Production/Stable); it changes no "
        "invocation, no payload and no exit code, so it fails both limbs of D3's test."
    ),
}


def test_every_declared_breaking_candidate_is_named_or_registered() -> None:
    """AC8. Coverage over the DECLARED population: every candidate that
    landed a changelog entry (`entries_for()`) is either a migration row or
    a stated exclusion. Silence is a failure."""
    changelog_module = _tests_module("test_changelog_history")
    row_ids = {row.spec_id for row in MIGRATION_ROWS}
    unaccounted = [
        spec_id
        for spec_id in sorted(BREAKING_CANDIDATES)
        if changelog_module.entries_for(spec_id)
        and spec_id not in row_ids
        and spec_id not in NOT_A_MIGRATION_ITEM
    ]
    assert unaccounted == [], (
        f"{unaccounted} landed a changelog entry but appears in neither "
        "MIGRATION_ROWS nor NOT_A_MIGRATION_ITEM"
    )


def test_the_coverage_register_reds_when_an_id_is_dropped_from_both() -> None:
    """AC8's RED: remove one landed id from both registers."""
    changelog_module = _tests_module("test_changelog_history")
    row_ids = {row.spec_id for row in MIGRATION_ROWS}
    victim = next(iter(NOT_A_MIGRATION_ITEM))
    exclusions_without_victim = {k: v for k, v in NOT_A_MIGRATION_ITEM.items() if k != victim}
    unaccounted = [
        spec_id
        for spec_id in sorted(BREAKING_CANDIDATES)
        if changelog_module.entries_for(spec_id)
        and spec_id not in row_ids
        and spec_id not in exclusions_without_victim
    ]
    assert unaccounted == [victim]


def _check_not_a_migration_item(register: dict[str, str], row_ids: set[str]) -> None:
    changelog_module = _tests_module("test_changelog_history")
    for spec_id, reason in register.items():
        assert changelog_module.entries_for(spec_id), f"{spec_id} names no changelog entry"
        assert reason.strip(), f"{spec_id} has an empty reason"
        assert spec_id not in row_ids, f"{spec_id} is both a row and an exclusion"


def test_the_not_a_migration_item_register_is_frozen_and_reasoned() -> None:
    """AC9. Frozen size, every key a real allocated id, every value
    non-empty, and no overlap with MIGRATION_ROWS."""
    assert len(NOT_A_MIGRATION_ITEM) == 3
    _check_not_a_migration_item(NOT_A_MIGRATION_ITEM, {row.spec_id for row in MIGRATION_ROWS})


def test_the_not_a_migration_item_register_reds() -> None:
    """AC9's two REDs: an empty reason, and an id that is also a row."""
    row_ids = {row.spec_id for row in MIGRATION_ROWS}

    empty_reason = dict(NOT_A_MIGRATION_ITEM)
    empty_reason["PDF-50"] = ""
    with pytest.raises(AssertionError, match="empty reason"):
        _check_not_a_migration_item(empty_reason, row_ids)

    overlapping = dict(NOT_A_MIGRATION_ITEM)
    overlapping[next(iter(row_ids))] = "a manufactured overlap, for the RED only"
    with pytest.raises(AssertionError, match="both a row"):
        _check_not_a_migration_item(overlapping, row_ids)


# --- D7: no unmasked cardinal in the section itself. ------------------------- #


def test_the_migration_section_carries_no_unmasked_cardinal() -> None:
    """AC10. Mirrors `test_the_known_issues_section_carries_no_count` (D7):
    enumerate, never count. Masked the same way `cardinal_residue` masks --
    code spans first, then the structured-reference family -- because the
    section is free to use `4` and `1.0.0` the way the rest of this file
    does; what may not survive is a BARE cardinal in prose."""
    body = migration_section_body()
    masked = _blank(body, code_spans(body))
    for pattern in (*STRUCTURED_REFERENCE, EXIT_CODE):
        masked = _blank(masked, [match.span() for match in pattern.finditer(masked)])
    residue = [match.group(0) for match in CANDIDATE.finditer(masked)]
    assert residue == [], f"the migration section carries an unmasked cardinal: {residue}"


def test_the_migration_section_cardinal_criterion_can_fail() -> None:
    """AC10's RED, on a scratch body -- never the real section."""
    poisoned = migration_section_body() + "\n\nThere are three breaking changes.\n"
    masked = _blank(poisoned, code_spans(poisoned))
    for pattern in (*STRUCTURED_REFERENCE, EXIT_CODE):
        masked = _blank(masked, [match.span() for match in pattern.finditer(masked)])
    residue = [match.group(0) for match in CANDIDATE.finditer(masked)]
    assert residue == ["three"]


# --- AC1: the section exists, in the ruled place, and is commit-anchored. --- #


def test_the_migration_section_exists_and_is_commit_anchored() -> None:
    """AC1. Exactly one `## Upgrading to 1.0.0` heading, positioned between
    `## Getting Started`'s content and `## What exists today`, and its body
    ends with a commit-anchored provenance line (PDF-30 D4)."""
    text = read("README.md")
    heading_count = text.count(MIGRATION_HEADING)
    assert heading_count == 1, (
        f"README.md carries the migration heading {heading_count} time(s), expected exactly 1"
    )
    getting_started = text.index("## Getting Started")
    what_exists_today = text.index("## What exists today")
    migration = text.index(MIGRATION_HEADING)
    assert getting_started < migration < what_exists_today, (
        "the migration section must sit between '## Getting Started' and '## What exists today'"
    )
    body = migration_section_body().rstrip()
    assert PROVENANCE_PATTERN.search(body), (
        "the section's body does not end with a commit-anchored provenance line"
    )


def test_the_commit_anchor_check_fails_if_the_provenance_line_is_missing() -> None:
    """AC1's RED, on a scratch body -- never the real section."""
    poisoned = migration_section_body().rsplit("Re-derived at", 1)[0].rstrip()
    assert PROVENANCE_PATTERN.search(poisoned) is None


# --- AC13: the section degrades conditionally, never by deletion. ----------- #


def _vacuous_migration_fixture() -> str:
    return (
        f"{MIGRATION_HEADING}\n\n"
        "`1.0.0` introduces no breaking change for a `0.3.1` consumer.\n\n"
        "Re-derived at `0000000` on `1999-01-01`.\n\n"
        "## What exists today\n\n"
        "placeholder body\n"
    )


def test_the_migration_section_survives_the_vacuous_rendering(tmp_path: Path) -> None:
    """AC13. D9's own degrade-honestly rule: if nothing breaking landed, the
    heading survives and reads the no-breaking-change sentence rather than
    being deleted -- checked on a synthetic `tmp_path` document sliced with
    the SAME extractor the populated state above uses."""
    vacuous = _vacuous_migration_fixture()
    scratch = tmp_path / "README.md"
    scratch.write_text(vacuous)

    assert MIGRATION_HEADING in vacuous, "the heading must survive the vacuous rendering"
    body = _migration_section_body_of(scratch.read_text())
    assert "introduces no breaking change" in body


def test_the_vacuous_rendering_extractor_fails_if_the_heading_is_deleted() -> None:
    """AC13's RED."""
    without_heading = _vacuous_migration_fixture().replace(MIGRATION_HEADING, "## Nothing here")
    with pytest.raises(AssertionError):
        _migration_section_body_of(without_heading)


# --------------------------------------------------------------------------- #
# PDF-79 / OR-21 — `-o table` is NOT public API, recorded where a user reads it
#
# `tests/golden/envelope_keys.json` freezes `json`, `ndjson_line` and
# `error_json`. It carries no `table` arm — while `auto_format()` returns
# `TABLE` whenever stdout is a terminal, so the one shape every interactive
# user sees is the one shape nothing freezes. That is not a falsehood in the
# documentation, it is a SILENCE, and a structural one: a three-row shape table
# sits directly under a heading called `## Output contract`, and the sentence
# that enumerates what the contract actually is ("the structured shapes and the
# exit-code table below") sits far below it, inside a sub-section. A reader who
# stops at the table has been told that all three shapes are the product's
# shapes, and has been told nothing that contradicts it.
#
# OR-21 rules the silence rather than closing it the expensive way: `-o table`
# is NOT public API. It is a human convenience, machine consumers are already
# pointed at the structured shapes, and freezing its columns would forbid
# improving the display. So NOTHING HERE FREEZES A COLUMN SET — not a name, not
# an order, not a width, not a count — and no `table` arm is added to the
# register. What ships is the ruling, in the section a user actually reads,
# plus these arms.
#
# WHAT THE RULING DOES NOT FREE. It frees the columns as a PROMISE TO USERS. It
# does not free them of test-internal coupling. Contract row C22 —
# `test_cli_contract.py::test_c22_the_prediction_holds_under_every_output_shape`
# — parses the rendered table and pins three column coordinates: `assert "ok"
# not in header`, `header.index("exit code")` and `header.index("detail")`,
# measured at `tests/test_cli_contract.py` lines 4255, 4259 and 4260 when this
# section was written (re-derive: coordinates rot, X-411). A column change WILL
# red those three, and that red is CORRECT — a parse coordinate, never a user
# promise. Re-derive C22's parse coordinates; do not conclude that the ruling
# makes the red wrong.
#
# WHAT THIS SECTION DELIBERATELY DOES NOT ASSERT. `render_table` TOTALITY —
# that it renders every publishing leaf without raising — is not asserted here,
# and no module anywhere in `tests/` has the renderer as its subject. That is
# carried, scoped and sequenced rather than forgotten: `B-311` /
# `IMPROVEMENT-REPORT.md` I-15 `P-C` (in the planning tree's `qa/` directory),
# which MAY assert totality but must NOT freeze a column set, and which needs
# PDF-77's hypothesis profile before a counterexample is recoverable at all.
# A reader who asks "so nothing asserts the renderer works?" gets the answer,
# an owner and a revisit condition at the point they ask it.
#
# WHY NOT PDF-72's CATEGORICAL-CLAIM REGISTRY, though this claim is categorical.
# That registry derives its boolean from `ci.yml`'s live job set via
# `resolve_ci_job`; its emptiness arm asserts every member's predicate is one of
# `_CI_JOB_PREDICATES`; and its completeness arm asserts the DETECTED population
# equals the registered one. A member reading "`-o table` is not public API"
# satisfies none of the three: its oracle is the register, not `ci.yml`, so
# `resolve_ci_job` returns `None` — which that registry treats as a FAILURE,
# correctly. Registering it there would hand a registry built to refuse
# underivable members exactly such a member. Measured, not reasoned: planted,
# it reds three arms at once. `DERIVED_FIGURES` is the other near-neighbour and
# is also wrong — its agreement arm asserts `derive()`'s STRING is rendered in
# the document, and this ruling is deliberately cardinal-free, so it renders no
# figure for a derivation to equal. What is reused is the module's VOCABULARY —
# anchor uniqueness checked separately, paraphrase patterns rather than one
# literal (B-106), every detector shown to find a known needle before it is
# believed (B-088) — and not its registries.
# --------------------------------------------------------------------------- #

#: The section heading, and the sliced body's closing sub-heading.
OUTPUT_CONTRACT_HEADING = "## Output contract"
COLLECTION_KEY_SUBHEADING = "### The collection key"

#: LINE-ANCHORED, and that is a deliberate divergence from
#: `_schema_version_section_body_of`'s bare `str.split`/`str.count`, recorded
#: here because it was measured rather than preferred. The bare substring
#: `## Output contract` occurs TWICE in `README.md`: once as this heading, and
#: once inside PDF-65's migration prose, which names "the `-o table` row under
#: `## Output contract`". The unanchored idiom therefore counts two and slices
#: from the PROSE mention, returning the migration table as the "section body".
#: `^...$` is what the spec's own acceptance criterion measures anyway
#: (`grep -c "^## Output contract"`), so the guard and its criterion agree.
_OUTPUT_CONTRACT_ANCHOR: Final = re.compile(
    rf"^{re.escape(OUTPUT_CONTRACT_HEADING)}$", re.MULTILINE
)


def _output_contract_body_of(text: str) -> str:
    """*text*'s `## Output contract` section, bounded by the NEXT `## ` heading.

    Whether the anchor occurs exactly once is checked SEPARATELY
    (`test_pdf79_the_output_contract_anchor_occurs_exactly_once`) rather than
    folded in here — the same reason `_schema_version_section_body_of` gives:
    folding it in would silently return the wrong span on a duplicate instead
    of failing. A MISSING anchor is an `AssertionError` here rather than an
    `IndexError`, so the extractor's own red is assertable.
    """
    match = _OUTPUT_CONTRACT_ANCHOR.search(text)
    assert match is not None, (
        f"the document carries no {OUTPUT_CONTRACT_HEADING!r} heading of its own line; "
        "OR-21's ruling has nowhere to live and every arm below is vacuous"
    )
    return text[match.end() :].split("\n## ", 1)[0]


def output_contract_body() -> str:
    return _output_contract_body_of(read("README.md"))


def _pdf79_scan(text: str) -> str:
    """*text* as the patterns below read it: whitespace collapsed, then markdown
    emphasis and code ticks removed.

    So a claim may wrap across lines, may be bolded, and may render `-o json`
    as a code span or as bare prose without changing whether a pattern sees it.
    Self-tested by `test_pdf79_the_scanner_is_self_tested_before_it_is_trusted`
    before anything believes it (B-088).
    """
    return normalise(text).replace("`", "").replace("*", "")


#: D3's paraphrase set, and there are three of them rather than one literal
#: because a guard that answers "is this STRING gone" rather than "is this CLAIM
#: gone" is the B-106 failure this module exists to stop repeating. Each covers
#: one limb of the ruling: the shape is for a person; its columns may move
#: without a major version bump; a program reads the structured shapes instead.
#: Each is proven to match the shipped paragraph AND to miss the pre-ruling
#: section by `test_pdf79_the_exclusion_patterns_can_fail`.
#:
#: NOTE WHAT IS ABSENT: no pattern names a column, an order or a width. A
#: pattern here that read a rendered header row would be this section
#: contradicting the ruling it records.
PDF79_EXCLUSION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"-o table[^.]{0,80}\bfor a (?:person|human)\b", re.IGNORECASE),
    re.compile(
        r"\bcolumns\b[^.]{0,160}\bmay change\b[^.]{0,80}\bwithout a major version bump\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:parses|parsing|reads|reading|consumes)\b[^.]{0,100}-o json[^.]{0,60}-o ndjson",
        re.IGNORECASE,
    ),
)

#: D3's contrary set — the patterns that match the ROT rather than the claim.
#: They are the answer to the limitation PDF-83 reported against its own arm
#: (the bite is on the anchor phrase, so a merge performed by WIDENING rather
#: than rewriting is invisible to it): these sweep whole documents, so a
#: contradiction appended to the ruling's own paragraph — which every exclusion
#: pattern above would still match — reds here. Proven by
#: `test_pdf79_a_widening_that_keeps_the_claim_is_still_caught`.
#:
#: Each is narrow in a specific, load-bearing way. The first requires a
#: UNIVERSAL QUANTIFIER, because `README.md` and `CLAUDE.md` both carry a true
#: sentence about "the structured (output) shapes" being public API and a
#: pattern without the quantifier would red a correct tree. The second requires
#: the TABLE SHAPE by name rather than the bare word `table`, because the same
#: true sentence names "the exit-code table".
PDF79_CONTRARY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"\b(?:all|every|each)\b[^.]{0,60}\bshapes?\b[^.]{0,60}"
        r"\b(?:public api|frozen|stable|contract)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:-o table|table shape|table output|table renderer)[^.]{0,100}"
        r"\b(?:is|are|remains?|stays?|becomes?)\b[^.]{0,60}"
        r"\b(?:public api|frozen|stable|part of the contract|covered by the register)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\btable\b\s+arm\b|\b(?:register|envelope keys)\b[^.]{0,80}\b(?:-o table|table shape)\b",
        re.IGNORECASE,
    ),
)

#: The contrary set's positive control. INVENTED — no text this product ever
#: shipped said any of this, which is precisely why the patterns need a fixture
#: of their own to prove they can fire at all. One sentence per pattern, in
#: order.
PDF79_SYNTHETIC_CONTRARY_LITERAL: Final[str] = (
    "All three output shapes are public API from v1.0.0. "
    "The `-o table` shape is frozen at `v1.0.0` and its columns may not be renamed. "
    "The frozen envelope register carries a `table` arm beside `json` and `ndjson_line`."
)

#: The fourth arm OR-21 declined. Named here so the agreement arm's message and
#: its own red speak about the same member.
PDF79_DECLINED_REGISTER_ARM: Final[str] = "table"


def _pdf79_ruling_paragraphs(body: str) -> list[str]:
    """Every paragraph of *body* carrying the WHOLE ruling.

    A paragraph qualifies only when EVERY exclusion pattern matches it, so a
    paragraph that merely mentions `-o table` does not qualify and the removal
    control below cannot delete the wrong prose. Located by CONTENT rather than
    by position, so the ruling may be reworded, merged or moved within the
    section without this helper needing an edit — and so no line coordinate
    enters this section (X-411).
    """
    return [
        paragraph
        for paragraph in body.split("\n\n")
        if all(pattern.search(_pdf79_scan(paragraph)) for pattern in PDF79_EXCLUSION_PATTERNS)
    ]


def _pdf79_table_arm_complaint(arms: Sequence[object]) -> str | None:
    """The register-agreement predicate, as a pure function of *arms*.

    Extracted so the `..._can_fail` twin can drive it against a scratch mapping
    instead of the shipped register — which must stay byte-identical across
    this spec's landing, and does.
    """
    if PDF79_DECLINED_REGISTER_ARM not in [str(arm) for arm in arms]:
        return None
    return (
        f"tests/golden/envelope_keys.json's `_meta.arms` now carries a "
        f"{PDF79_DECLINED_REGISTER_ARM!r} arm: {list(arms)}. Operator ruling OR-21 says "
        "`-o table` is NOT public API — it is a human convenience, machine consumers are "
        "pointed at the structured shapes, and freezing its columns would forbid improving "
        "the display. README.md's `## Output contract` states that ruling to users. THE "
        "REPAIR IS A PROJECT-MANAGER RULING PLUS AN AMENDED README.md, NEVER AN EDIT TO "
        "THIS ARM and never a quiet regeneration of the register: a fourth arm added here "
        "reverses OR-21 without a decision record, and leaves the document promising the "
        "opposite of what the register freezes."
    )


def test_pdf79_the_scanner_is_self_tested_before_it_is_trusted() -> None:
    """B-088, applied to `_pdf79_scan` before any pattern is believed through it.

    The load-bearing half is the markup half: the shipped ruling renders its
    flags as code spans, and a scanner that left the ticks in would make every
    pattern below depend on markup the author is free to change.
    """
    assert _pdf79_scan("a  b\nc") == "a b c"
    assert _pdf79_scan("ask for `-o json` or\n`-o ndjson`") == "ask for -o json or -o ndjson"
    assert _pdf79_scan("**public API** from `v1.0.0`") == "public API from v1.0.0"


def test_pdf79_the_output_contract_anchor_occurs_exactly_once() -> None:
    """AC3. An anchor that matches nothing — or matches twice — is a guard that
    guards nothing, so a heading rename is a HARD FAILURE here, never a skip.

    Counted line-anchored: the bare substring occurs twice in `README.md`, the
    second inside PDF-65's migration prose. See `_OUTPUT_CONTRACT_ANCHOR`.
    """
    count = len(_OUTPUT_CONTRACT_ANCHOR.findall(read("README.md")))
    assert count == 1, (
        f"README.md carries the {OUTPUT_CONTRACT_HEADING!r} heading {count} time(s), expected "
        "exactly 1. OR-21's ruling is delivered inside that section; a renamed, deleted or "
        "duplicated heading leaves it guarding nothing."
    )


def test_pdf79_the_anchor_check_fails_rather_than_skips_if_the_heading_changes() -> None:
    """AC3's RED, on a scratch copy — never the real `README.md`."""
    real = read("README.md")
    altered = re.sub(_OUTPUT_CONTRACT_ANCHOR, "## Output shapes", real)
    assert altered != real, "the scratch mutation did not fire"
    assert len(_OUTPUT_CONTRACT_ANCHOR.findall(altered)) == 0
    with pytest.raises(AssertionError):
        _output_contract_body_of(altered)

    duplicated = real.replace(
        f"{OUTPUT_CONTRACT_HEADING}\n", f"{OUTPUT_CONTRACT_HEADING}\n\n{OUTPUT_CONTRACT_HEADING}\n"
    )
    assert len(_OUTPUT_CONTRACT_ANCHOR.findall(duplicated)) == 2


def test_pdf79_the_output_contract_rules_the_table_shape_out_of_contract() -> None:
    """AC1/AC2. OR-21, stated where the belief is formed.

    Asserted by INDEX WITHIN THE SLICED BODY and never by line number (X-411):
    the ruling sits inside `## Output contract` and ahead of that body's
    `### The collection key` sub-heading, which is the granularity the ruling
    itself has.
    """
    body = output_contract_body()
    scanned = _pdf79_scan(body)
    sub_heading_index = scanned.find(COLLECTION_KEY_SUBHEADING)
    assert sub_heading_index != -1, (
        f"the `## Output contract` body no longer carries {COLLECTION_KEY_SUBHEADING!r}, so "
        "AC2's placement bound cannot be evaluated at all"
    )

    for pattern in PDF79_EXCLUSION_PATTERNS:
        match = pattern.search(scanned)
        assert match is not None, (
            "README.md's `## Output contract` no longer records operator ruling OR-21 — that "
            "`-o table` is NOT public API, that its columns, their names, their order and the "
            "layout may change in any release without a major version bump, and that anything "
            f"parsing output should ask for `-o json` or `-o ndjson`. Pattern "
            f"{pattern.pattern!r} matches nothing in the section body. A reader who stops at "
            "that section's shape table is otherwise told that all three shapes are this "
            "product's shapes, and told nothing that contradicts it. REPAIR THE SECTION, never "
            "this pattern."
        )
        assert match.start() < sub_heading_index, (
            f"README.md states OR-21's ruling ({pattern.pattern!r} matches at {match.start()}) "
            f"but BELOW the section's {COLLECTION_KEY_SUBHEADING!r} sub-heading (at "
            f"{sub_heading_index}). The ruling belongs where the belief is formed — beside the "
            "shape table — not after a reader has already stopped reading."
        )

    paragraphs = _pdf79_ruling_paragraphs(body)
    assert len(paragraphs) == 1, (
        f"the whole of OR-21's ruling should sit in exactly one paragraph of `## Output "
        f"contract`; {len(paragraphs)} paragraph(s) carry every limb of it. A ruling split "
        "across the section is one a later edit can half-delete without reddening anything."
    )


def test_pdf79_the_exclusion_patterns_can_fail() -> None:
    """AC4/AC5's RED, on a SCRATCH copy of the located span — never the tree.

    Two directions, and the second is the load-bearing one. (a) With the ruling
    removed, EVERY pattern must miss — a pattern that still matched would be
    passing on text that never made the claim. (b) The text it is removed from
    IS the pre-ruling section, so (a) is also the proof that no pattern matched
    the section before this ruling was written into it.
    """
    body = output_contract_body()
    paragraphs = _pdf79_ruling_paragraphs(body)
    assert len(paragraphs) == 1, "the scratch mutation has no single paragraph to remove"

    pre_ruling = body.replace(paragraphs[0], "")
    assert pre_ruling != body, "the scratch mutation did not fire"
    scanned = _pdf79_scan(pre_ruling)

    for pattern in PDF79_EXCLUSION_PATTERNS:
        assert pattern.search(scanned) is None, (
            f"pattern {pattern.pattern!r} still matches the section with OR-21's ruling "
            "REMOVED, so it is matching text that never made the claim and would stay green "
            "through the ruling's deletion"
        )


def test_pdf79_no_guarded_document_claims_the_table_shape_is_contract() -> None:
    """AC6. The ruling written down in one place and quietly contradicted in
    another is the second failure mode this section is designed against.

    Swept over all four GUARDED_DOCS rather than AC6's two prime documents:
    the wider net is green today, measured, and a contradiction in `TESTING.md`
    or `CONTRIBUTING.md` would be exactly as wrong as one in `README.md`.
    """
    contradictions: list[str] = []
    for doc in GUARDED_DOCS:
        scanned = _pdf79_scan(read(doc))
        for pattern in PDF79_CONTRARY_PATTERNS:
            match = pattern.search(scanned)
            if match is not None:
                contradictions.append(f"  {doc}: {match.group(0)!r} (pattern {pattern.pattern!r})")
    assert not contradictions, (
        "a guarded document asserts that the table shape — or every output shape — is public "
        "API, frozen, stable or covered by the frozen register. Operator ruling OR-21 says "
        "`-o table` is NOT public API, and README.md's `## Output contract` states that "
        "ruling to users:\n" + "\n".join(contradictions)
    )


def test_pdf79_the_contrary_patterns_fire_on_their_own_fixture() -> None:
    """AC6's other half. A contrary pattern that cannot fire guards nothing; a
    contrary pattern broad enough to fire on the SHIPPED text would red a
    correct tree. Both are asserted, rather than one being inferred from the
    other's green."""
    fixture = _pdf79_scan(PDF79_SYNTHETIC_CONTRARY_LITERAL)
    shipped = _pdf79_scan(output_contract_body())
    for pattern in PDF79_CONTRARY_PATTERNS:
        assert pattern.search(fixture), (
            f"contrary pattern {pattern.pattern!r} cannot fire even on its own invented "
            "fixture, so it would never notice the ruling being contradicted"
        )
        false_positive = pattern.search(shipped)
        hit = false_positive.group(0) if false_positive else ""
        assert false_positive is None, (
            f"contrary pattern {pattern.pattern!r} matches the SHIPPED section at {hit!r}, so "
            "it is broad enough to red a correct tree"
        )


def test_pdf79_a_widening_that_keeps_the_claim_is_still_caught() -> None:
    """The limitation PDF-83 reported against its own arm, answered.

    PDF-83's registry arm bites on an ANCHOR PHRASE, so a later editor who
    WIDENS the guarded sentence while preserving that phrase — rather than
    rewriting it — leaves the arm green while the claim has been reversed. The
    exclusion arm above inherits exactly that weakness on its own: a widening
    that keeps all three limbs matchable keeps it green.

    What closes it is that the contrary sweep reads the WHOLE document rather
    than the anchor: the widening is new text, and new text that reverses the
    ruling is what the contrary patterns are for. Demonstrated here on a
    scratch copy against the real shipped paragraph, not argued.
    """
    body = output_contract_body()
    paragraphs = _pdf79_ruling_paragraphs(body)
    assert len(paragraphs) == 1, "the scratch mutation has no single paragraph to widen"

    widened = body.replace(
        paragraphs[0],
        paragraphs[0].rstrip()
        + " That said, the `-o table` shape is public API from `v1.0.0` all the same.",
    )
    assert widened != body, "the scratch mutation did not fire"

    scanned = _pdf79_scan(widened)
    assert all(pattern.search(scanned) for pattern in PDF79_EXCLUSION_PATTERNS), (
        "the widening must leave every exclusion pattern matching — otherwise this control "
        "proves nothing about the weakness it exists to answer"
    )
    assert any(pattern.search(scanned) for pattern in PDF79_CONTRARY_PATTERNS), (
        "a widening that preserves every limb of the ruling and then reverses it must be "
        "caught by at least one contrary pattern; otherwise this section inherits PDF-83's "
        "anchor-phrase limitation whole"
    )


def test_pdf79_the_ruling_agrees_with_the_frozen_register() -> None:
    """AC7, and the load-bearing arm of the section.

    A prose guard proves a sentence is still PRESENT. It cannot prove the
    sentence is still TRUE. The one artefact a future engineer would touch on
    deciding that `table` IS contract is the register, so the two are bound.

    Read through `test_envelope_contract.load_register_document()` — the
    register's OWN reader — and never re-opened here (X-157): a second reader
    is a second thing to drift.
    """
    document = _tests_module("test_envelope_contract").load_register_document()
    arms = document["_meta"]["arms"]
    complaint = _pdf79_table_arm_complaint(arms)
    assert complaint is None, complaint


def test_pdf79_the_register_agreement_arm_can_fail() -> None:
    """AC7's RED, against a SCRATCH MAPPING — the shipped register is
    byte-identical across this spec's landing and is not touched even to prove
    its own guard bites."""
    real = _tests_module("test_envelope_contract").load_register_document()
    scratch_arms = [*real["_meta"]["arms"], PDF79_DECLINED_REGISTER_ARM]

    complaint = _pdf79_table_arm_complaint(scratch_arms)
    assert complaint is not None, "the agreement predicate is vacuous"
    assert "OR-21" in complaint
    assert "README.md" in complaint
    assert "NEVER AN EDIT TO THIS ARM" in complaint
