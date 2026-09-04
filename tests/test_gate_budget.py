"""PDF-29's own guards: the timing record schema, the single source of
parallelism, the `ci.yml` job bounds, and the documented-wall-clock-claim rule.

**The cycle rule, applied to every assertion in this file: a control that has
never been observed RED is not a control.** Each guard below therefore ships
with the red beside it -- a scratch copy with one defect planted, asserted to
turn that exact guard red and to name the offender. Nothing here asserts only a
green.

Why these five things live in one file. They are one defect wearing five hats:
**a number taken under conditions that were not recorded cannot justify a
decision.** A `make ci` trend built from six self-measured figures on six
unknown hosts; a 250 ms startup budget whose dispersion exceeded its headroom; a
CI job with no bound at all, which produces no number when it hangs; and a
documented wall-clock claim wrong by roughly 6x because prose is not executed.
Each is the same disease at a different scale.

This file is `PDF-29`'s alone. `tests/test_docs_antirot.py` has a single owner
(`PDF-30`) and is deliberately not widened here; if `PDF-30` later consolidates
the documented-claim guard, it should CONSUME this one rather than build a
second.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final, NamedTuple

import pytest
import yaml

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SCRIPTS_DIR: Final[Path] = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(SCRIPTS_DIR))

from measure_gate import RECORD_FIELDS, validate_record  # noqa: E402

CI_WORKFLOW: Final[Path] = REPO_ROOT / ".github" / "workflows" / "ci.yml"
MAKEFILE: Final[Path] = REPO_ROOT / "Makefile"
PYPROJECT: Final[Path] = REPO_ROOT / "pyproject.toml"
TESTING_DOC: Final[Path] = REPO_ROOT / "TESTING.md"
CLI_SPINE: Final[Path] = REPO_ROOT / "tests" / "test_cli_spine.py"
IMPORT_BOUNDARIES: Final[Path] = REPO_ROOT / "tests" / "test_import_boundaries.py"
PERF_DIR: Final[Path] = REPO_ROOT / "perf"
TREND_FILE: Final[Path] = PERF_DIR / "gate-timings.jsonl"

#: `timeout-minutes` may never exceed this. Design §7.
TIMEOUT_CEILING: Final = 30

#: The eleven jobs, re-derived from the mapping rather than asserted from
#: memory. PDF-34 D4/X-472 coordinate 1: `docs-gate` moves this 10 -> 11,
#: consumed at `test_ci_yml_parses_to_exactly_eleven_jobs` (renamed
#: accordingly) and at `test_every_timeout_is_preceded_by_its_derivation`
#: (one bound per job) -- both pass here because `docs-gate` lands with its
#: own p95-derived `timeout-minutes` and derivation comment in the same
#: commit (X-473), not deferred to a follow-up.
EXPECTED_JOB_COUNT: Final = 11


# --------------------------------------------------------------------------- #
# Shared derivations
# --------------------------------------------------------------------------- #


def ci_jobs() -> dict[str, Any]:
    """`ci.yml`'s `jobs:` mapping, PARSED -- never a two-space key grep.

    C-6: the roadmap said eleven jobs four times and `X-160` corrected it to
    ten, but **the wrong instrument was never corrected**, so it is still
    reproducible. `test_the_naive_two_space_key_grep_is_the_wrong_instrument`
    below pins the discrepancy so the wrong instrument cannot be substituted
    for this one silently.
    """
    document = yaml.safe_load(CI_WORKFLOW.read_text())
    jobs = document["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def naive_two_space_keys(text: str) -> list[str]:
    """The WRONG instrument, kept executable on purpose (see above)."""
    return re.findall(r"^  ([a-zA-Z][a-zA-Z0-9_-]*):\s*$", text, re.MULTILINE)


#: A pytest parallelism setting, wherever it might be written. `[ -n "$$x" ]`
#: is a shell string test and appears legitimately in the Makefile, so the
#: pattern requires an actual worker count after the flag.
PARALLELISM_SETTING: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w-])(-n\s+(?:auto|logical|\d+)|--numprocesses(?:[= ]\S+)?)"
)

#: `timeout-minutes: N` preceded within three lines by a comment naming its p95
#: and its observation window. AC16 -- the value is not the deliverable, the
#: derivation is; a bound nobody can re-derive is a guess with a number on it.
DERIVATION_COMMENT: Final[re.Pattern[str]] = re.compile(
    r"p95\s+[\d.]+s\s+over\s+\d+\s+green\s+runs", re.IGNORECASE
)


def timeout_sites(text: str) -> list[tuple[int, int, list[str]]]:
    """(1-based line number, value, the three preceding lines) per bound."""
    lines = text.splitlines()
    sites: list[tuple[int, int, list[str]]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^\s*timeout-minutes:\s*(\d+)\s*$", line)
        if match:
            sites.append((index + 1, int(match.group(1)), lines[max(0, index - 3) : index]))
    return sites


# --------------------------------------------------------------------------- #
# AC1 -- the record schema, and its red: every required field, removed in turn
# --------------------------------------------------------------------------- #


def a_valid_record() -> dict[str, Any]:
    return {
        "timestamp": "2026-09-03T01:09:34-0600",
        "commit": "0" * 40,
        "dirty": False,
        "target": "ci",
        "variant": "default",
        "interpreter": {"version": "3.12.13", "executable": "/x/.venv/bin/python3"},
        "binary": "/x/.venv/bin/pdftoolkit",
        "binary_arm": "venv-sibling",
        "cache_state": "warm",
        "engines": {"tesseract": "/usr/bin/tesseract", "soffice": "/usr/bin/soffice"},
        "tests_collected": 2605,
        "coverage_pct": 94.2,
        "cpu_count": 8,
        "loadavg_start": 1.15,
        "loadavg_peak": 7.9,
        "loadavg_end": 6.2,
        "foreign_processes": [],
        "quiet": True,
        "wall_clock_s": 291.4,
        "distribution": None,
    }


def test_the_reference_record_validates() -> None:
    """Non-vacuity. If the valid record did not validate, every red below would
    fire for the wrong reason and the schema would be untested in both
    directions."""
    assert validate_record(a_valid_record()) == []


@pytest.mark.parametrize("field", RECORD_FIELDS, ids=list(RECORD_FIELDS))
def test_a_record_missing_any_required_field_is_rejected_by_name(field: str) -> None:
    """AC1's RED, one planted defect per required field.

    Each field earns its place by being a way two timings stop being comparable
    -- `cache_state` is why 331.25 s and 492.20 s were never the same
    measurement, `engines` is why 860 s and 529 s were not either. A schema that
    accepted a record without one of them would be recording exactly the
    unusable numbers this spec exists to replace.
    """
    record = a_valid_record()
    del record[field]
    problems = validate_record(record)
    assert problems, f"a record with {field!r} removed was accepted"
    assert any(field in problem for problem in problems), (
        f"the rejection did not name the missing field {field!r}: {problems}"
    )


def test_every_recorded_trend_line_is_a_valid_record() -> None:
    """The file the protocol writes must itself satisfy the protocol."""
    if not TREND_FILE.exists():
        pytest.skip(f"no trend file at {TREND_FILE} yet")
    for number, line in enumerate(TREND_FILE.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        assert validate_record(record) == [], f"{TREND_FILE.name}:{number} is invalid"


def test_the_protocol_documents_the_quiet_rule() -> None:
    """`perf/README.md` is where a later reader learns that a `quiet: false`
    record is an observation and never a baseline. Without that sentence the
    JSONL is another incommensurable trend."""
    text = (PERF_DIR / "README.md").read_text()
    assert "quiet" in text
    assert "baseline" in text.lower()
    assert re.search(r"0\.25\s*\*\s*cpu_count", text), (
        "perf/README.md must state the quietness DEFINITION, not merely the word"
    )


# --------------------------------------------------------------------------- #
# AC6 -- the parallelism setting has exactly one source
# --------------------------------------------------------------------------- #


def test_the_parallelism_lever_is_declared_in_the_shared_option_layer() -> None:
    """`-n auto` is in `[tool.pytest.ini_options] addopts` and is therefore read
    by every invocation -- `make test`, `make cover`, `make test-e2e`,
    `make samples-gate`, `make engines-gate`, and all three CI pytest steps."""
    text = PYPROJECT.read_text()
    addopts = re.search(r"^addopts\s*=\s*\"([^\"]*)\"", text, re.MULTILINE)
    assert addopts is not None, "pyproject.toml declares no addopts"
    assert "-n auto" in addopts.group(1), (
        f"addopts is {addopts.group(1)!r}; the parallelism lever must live here and only here"
    )


@pytest.mark.parametrize("path", [MAKEFILE, CI_WORKFLOW], ids=lambda p: p.name)
def test_no_second_source_of_parallelism_exists(path: Path) -> None:
    """AC6. A per-site convention cannot be asserted single-source; a config key
    can, and this is the assertion that makes the placement decision real rather
    than a preference stated in a comment."""
    offenders = [
        (number, line.strip())
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if PARALLELISM_SETTING.search(line)
    ]
    assert offenders == [], (
        f"{path.name} sets pytest parallelism at {offenders}. It belongs in exactly one "
        "place, [tool.pytest.ini_options] addopts -- a second site is a silent local/CI "
        "divergence the moment the two disagree."
    )


def test_a_planted_second_source_reddens_the_single_source_check(tmp_path: Path) -> None:
    """AC6's RED. Plant `-n 1` on a Makefile pytest invocation; the guard must
    name the file and the line."""
    scratch = tmp_path / "Makefile"
    original = MAKEFILE.read_text()
    planted = original.replace(
        "test: ## Run the test suite\n\t$(UV_RUN) pytest $(PYTEST_ARGS)",
        "test: ## Run the test suite\n\t$(UV_RUN) pytest -n 1 $(PYTEST_ARGS)",
        1,
    )
    assert planted != original, "the plant did not apply -- the anchor moved"
    scratch.write_text(planted)

    offenders = [
        (number, line.strip())
        for number, line in enumerate(scratch.read_text().splitlines(), start=1)
        if PARALLELISM_SETTING.search(line)
    ]
    assert offenders, "the single-source check did not notice a planted `-n 1`"
    assert any("pytest" in line for _, line in offenders)


def test_the_shell_string_test_is_not_mistaken_for_a_worker_count() -> None:
    """The negative control. `[ -n "$holder" ]` appears legitimately in the
    Makefile's concurrency guard; a pattern that flagged it would be deleted the
    first time it fired, which is how a guard dies."""
    assert PARALLELISM_SETTING.search('if [ -n "$$holder" ] && ! kill -0 "$$holder"') is None
    assert PARALLELISM_SETTING.search("uv run pytest -n auto") is not None
    assert PARALLELISM_SETTING.search("pytest --numprocesses=4") is not None


# --------------------------------------------------------------------------- #
# AC15 / AC16 -- every job bounded, every bound derived
# --------------------------------------------------------------------------- #


def test_ci_yml_parses_to_exactly_eleven_jobs() -> None:
    jobs = ci_jobs()
    assert len(jobs) == EXPECTED_JOB_COUNT, sorted(jobs)


def test_every_ci_job_carries_an_integer_timeout_minutes() -> None:
    """AC15. Without this, a `main`-push run -- which `cancel-in-progress:
    false` deliberately never cancels -- has NO bound but GitHub's 360-minute
    default, and a hung leg produces no number at all."""
    unbounded = sorted(
        name for name, body in ci_jobs().items() if not isinstance(body.get("timeout-minutes"), int)
    )
    assert unbounded == [], f"jobs with no integer timeout-minutes: {unbounded}"


def test_deleting_one_jobs_timeout_reddens_the_check_by_name(tmp_path: Path) -> None:
    """AC15's RED, on a scratch copy: strip `secret-scan`'s bound and the parse
    must name that job and no other."""
    scratch = tmp_path / "ci.yml"
    lines = CI_WORKFLOW.read_text().splitlines(keepends=True)
    inside_secret_scan = False
    kept: list[str] = []
    for line in lines:
        if re.match(r"^  [a-zA-Z][a-zA-Z0-9_-]*:\s*$", line):
            inside_secret_scan = line.strip() == "secret-scan:"
        if inside_secret_scan and re.match(r"^\s*timeout-minutes:\s*\d+\s*$", line):
            continue
        kept.append(line)
    scratch.write_text("".join(kept))

    jobs = yaml.safe_load(scratch.read_text())["jobs"]
    unbounded = sorted(
        name for name, body in jobs.items() if not isinstance(body.get("timeout-minutes"), int)
    )
    assert unbounded == ["secret-scan"], (
        f"the parse should have named exactly the stripped job; got {unbounded}"
    )


def test_the_naive_two_space_key_grep_is_the_wrong_instrument() -> None:
    """AC15's SECOND red -- against the instrument rather than the workflow.

    `X-160` corrected the job count from eleven to ten but not the instrument
    that produced eleven, so the wrong instrument is still reproducible. It is
    pinned here so it cannot be substituted for the parse silently.

    MEASURED AT THIS COMMIT the naive regex returns **14**, not the 11 the
    correction record quotes -- the four extras are the `on:` trigger keys
    (`push`, `pull_request`, `workflow_dispatch`, `workflow_call`), and the
    figure in the record predates `workflow_dispatch`/`workflow_call` being
    added. The exact number is not the point and is not asserted; the point is
    that the two instruments DISAGREE, and by exactly the trigger keys.
    """
    text = CI_WORKFLOW.read_text()
    naive = naive_two_space_keys(text)
    parsed = sorted(ci_jobs())
    assert len(naive) > len(parsed), (
        "the naive grep no longer over-counts, so this control has stopped controlling -- "
        "re-derive it before deleting it"
    )
    extras = sorted(set(naive) - set(parsed))
    triggers = sorted(yaml.safe_load(text)["on"])
    assert extras == triggers, (
        f"the naive grep's over-count is {extras}, which is not the `on:` trigger set "
        f"{triggers} -- the over-count now has a second cause worth understanding"
    )


def test_no_timeout_exceeds_the_ceiling() -> None:
    """`.get()` rather than `[...]` on purpose: observed RED once with a job's
    key deleted, this raised KeyError instead of reporting. A control that
    ERRORS where it should report is one a reader will disable rather than
    read, and the missing-key case is the neighbouring test's to name."""
    over = {
        name: body.get("timeout-minutes")
        for name, body in ci_jobs().items()
        if isinstance(body.get("timeout-minutes"), int)
        and body["timeout-minutes"] > TIMEOUT_CEILING
    }
    assert over == {}, f"bounds over the {TIMEOUT_CEILING}-minute ceiling: {over}"


def test_every_timeout_is_preceded_by_its_derivation() -> None:
    """AC16. The value is not the deliverable; the derivation is. A later reader
    must be able to tell a bound derived from p95 over a stated window from a
    number somebody liked."""
    sites = timeout_sites(CI_WORKFLOW.read_text())
    assert len(sites) == EXPECTED_JOB_COUNT, f"expected one bound per job, found {len(sites)}"
    undocumented = [
        (line_number, value)
        for line_number, value, preceding in sites
        if not any(DERIVATION_COMMENT.search(line) for line in preceding)
    ]
    assert undocumented == [], (
        f"timeout-minutes with no derivation comment within three lines: {undocumented}"
    )


def test_stripping_one_derivation_comment_reddens_the_check(tmp_path: Path) -> None:
    """AC16's RED."""
    scratch = tmp_path / "ci.yml"
    text = CI_WORKFLOW.read_text()
    stripped = re.sub(
        r"^    # PDF-29 bound: p95 14\.0s.*\n    # 3x p95.*\n",
        "",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    assert stripped != text, "the plant did not apply -- lint's comment moved"
    scratch.write_text(stripped)

    undocumented = [
        (line_number, value)
        for line_number, value, preceding in timeout_sites(scratch.read_text())
        if not any(DERIVATION_COMMENT.search(line) for line in preceding)
    ]
    assert len(undocumented) == 1, (
        f"stripping one derivation comment should leave exactly one bound undocumented; "
        f"got {undocumented}"
    )


# --------------------------------------------------------------------------- #
# AC11 -- STARTUP_BUDGET_MS may not move without its measurement beside it
# --------------------------------------------------------------------------- #

#: The five figures a distribution must carry, plus the STATISTIC that says what
#: they are figures OF. The last one is not pedantry: a *median under
#: contention* and a *fastest-of-5 at low load* are different statistics of the
#: same distribution and differ by tens of milliseconds, and quoting either as
#: "headroom" without naming which produced two irreconcilable headroom figures
#: on this very row (4.7 ms and ~29 ms).
EVIDENCE_TOKENS: Final = ("STATISTIC", "DATE", "COMMIT", "HOST", "INTERPRETER", "ENGINES")
DISTRIBUTION_TOKENS: Final = ("min", "median", "p95", "max", "spread")


def budget_block(text: str) -> tuple[float, str]:
    """(the constant, the comment block immediately above it)."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^STARTUP_BUDGET_MS\s*=\s*([\d.]+)\s*$", line)
        if not match:
            continue
        start = index
        while start > 0 and lines[start - 1].startswith("#"):
            start -= 1
        return float(match.group(1)), "\n".join(lines[start:index])
    raise AssertionError("STARTUP_BUDGET_MS is not defined in tests/test_cli_spine.py")


def test_a_moved_startup_budget_carries_its_measurement() -> None:
    """AC11. Raising the constant without the adjacent measurement is
    mechanically forbidden -- the three sentinel medians on record (224.7 ->
    242.7 -> 243.2) trend upward across the same instrument while verbs were
    added, so a widening that silences a genuine startup regression is a live
    risk and not a hypothetical one."""
    value, block = budget_block(CLI_SPINE.read_text())
    if value == 250.0:
        return
    missing = [token for token in EVIDENCE_TOKENS if token not in block]
    assert missing == [], f"STARTUP_BUDGET_MS = {value} but its block omits {missing}"
    absent = [token for token in DISTRIBUTION_TOKENS if token not in block]
    assert absent == [], f"STARTUP_BUDGET_MS = {value} but its block omits {absent}"


def test_a_raised_constant_with_no_evidence_block_reddens(tmp_path: Path) -> None:
    """AC11's RED: the same check against a planted bare constant."""
    scratch = tmp_path / "planted.py"
    scratch.write_text("# unrelated comment\nSTARTUP_BUDGET_MS = 400.0\n")
    value, block = budget_block(scratch.read_text())
    assert value == 400.0
    missing = [token for token in EVIDENCE_TOKENS if token not in block]
    assert missing, "a bare raised constant was accepted -- the guard is not checking the block"


# --------------------------------------------------------------------------- #
# The load-immune companion, and the ONE proposition it may abstain on
#
# WHY THIS IS AN AST WALK AND NOT A GREP, and it is the same lesson twice.
# The first version of this guard asserted `"getloadavg" not in body`. An
# independent verifier defeated it in one line, with the mechanism shipped ten
# lines away in this very cycle: it planted
# `if os.environ.get("PYTEST_XDIST_WORKER"): pytest.skip(...)` -- the abstention
# `tests/test_cli_spine.py::test_help_stays_within_the_startup_budget` itself
# uses -- into Section 6's bodies. The guard passed (1 passed, noticed nothing)
# while Section 6 reported `3 skipped` on every worker. **The startup claim was
# then held by two tests that both skip, i.e. by nothing, and this file said it
# was fine.**
#
# That is `B-106`'s lesson one step along, and `AC20` in this same file already
# applies it to prose: an exact-phrase guard *answers "is this STRING gone", not
# "is this CLAIM gone"*. A guard naming `getloadavg` AND `PYTEST_XDIST_WORKER`
# would be the same defect a third step along -- the next mechanism has a
# different name too. So the proposition is stated positively and the SHAPE is
# what is matched:
#
#   **Section 6 may abstain on exactly one thing: the build under test is not
#   there to measure. Every other abstention, by any mechanism, is a red.**
#
# Sanctioned is decided by the guarding CONDITION, not by the function's name.
# Keying on names is how a bypass gets written inside an already-allowlisted
# function; keying on the condition means an xdist skip planted into the
# sanctioned fixture itself still reddens.
#
# Scope is deliberately OVER-approximated: every function defined inside
# Section 6's span, plus every module-level function anywhere in that file that
# Section 6 transitively calls. A precise call graph is one missed edge (an
# autouse fixture, a `getattr` dispatch) away from a false negative, and the
# cost of the over-approximation is only that nobody may write abstention code
# in Section 6 at all -- which is the rule being enforced.
# --------------------------------------------------------------------------- #

SECTION_SIX_BANNER: Final = "Section 6 -- what `pdftoolkit --help` IMPORTS"

#: Section 6's three claim-bearing assertions. Losing one is losing the claim.
SECTION_SIX_TESTS: Final = (
    "test_help_imports_no_third_party_package_outside_the_pin",
    "test_help_import_count_stays_under_the_ceiling",
    "test_the_help_import_census_is_not_vacuous",
)

#: The ONLY admissible precondition: the venv's console script is not there, so
#: there is no build to census (`PLAN.md` §10.1 rule 5 -- absent precondition,
#: skip with a reason, never pass). Matched against the guarding condition's
#: source, so it survives `if not X.exists()`, `if not X.is_file()`, and a
#: `skipif` decorator carrying the same test.
SANCTIONED_CONDITION: Final[re.Pattern[str]] = re.compile(
    r"VENV_CONSOLE_SCRIPT\b[^\n]*\.(exists|is_file)\(\)"
)

#: Abstention by call. `fail` is deliberately absent -- failing is the opposite
#: of abstaining and is what this section is FOR.
ABSTAINING_CALLS: Final = frozenset({"skip", "xfail", "importorskip", "exit"})

#: Abstention by decorator, matched on the dotted tail so `pytest.mark.skipif`,
#: `mark.skipif` and a bare `skipif` all count.
ABSTAINING_DECORATORS: Final = frozenset({"skip", "skipif", "xfail"})

#: Abstention by exception.
ABSTAINING_EXCEPTIONS: Final = frozenset({"SkipTest", "Skipped"})

#: Sensing host load or worker identity AT ALL. Separate from the abstention
#: rule on purpose: `modules = [] if os.getloadavg()[0] > 4 else census()` is
#: not a skip, does not fail, and empties the census -- an abstention that
#: reports itself as a pass. Identifiers only; comments and docstrings are
#: exempt by construction because this reads the AST.
LOAD_SENSING_NAMES: Final = frozenset(
    {"getloadavg", "loadavg", "cpu_count", "sched_getaffinity", "getaffinity", "psutil"}
)
#: The same proposition where it hides in a string: an env-var key.
LOAD_SENSING_LITERALS: Final = ("PYTEST_XDIST_WORKER", "XDIST_WORKER", "loadavg")


class Abstention(NamedTuple):
    """One way out of running, found in Section 6."""

    function: str
    mechanism: str
    lineno: int
    condition: str

    @property
    def sanctioned(self) -> bool:
        return bool(SANCTIONED_CONDITION.search(self.condition))

    def __str__(self) -> str:  # pragma: no cover - failure-message plumbing
        where = self.condition or "<unconditional>"
        return f"{self.function}:{self.lineno} abstains via {self.mechanism} on `{where}`"


def _dotted(node: ast.AST) -> str:
    """`pytest.mark.skipif` from the Attribute/Name chain, or ''."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def section_span(text: str, banner: str) -> tuple[int, int]:
    """1-based [start, end) line range of the banner-named section.

    The end is the next section banner, so this keeps working when `PDF-30`
    appends Section 7 -- the file is append-only and its section numbers are
    taken by re-reading it, never from a spec.
    """
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if banner in line), None)
    assert start is not None, (
        f"{banner!r} is gone from {IMPORT_BOUNDARIES.name}; the contention-immune companion "
        "no longer exists and the startup claim is held by a test that skips under `-n auto`, "
        "i.e. by nothing"
    )
    for index in range(start + 1, len(lines)):
        if re.match(r"^#\s*Section \d+ --", lines[index]):
            return start + 1, index + 1
    return start + 1, len(lines) + 1


def _abstentions_in(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[Abstention]:
    found: list[Abstention] = []
    is_test = function.name.startswith("test_")

    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        dotted = _dotted(target)
        if dotted.split(".")[-1] in ABSTAINING_DECORATORS:
            condition = ""
            if isinstance(decorator, ast.Call) and decorator.args:
                condition = ast.unparse(decorator.args[0])
            found.append(Abstention(function.name, f"@{dotted}", decorator.lineno, condition))

    def visit(node: ast.AST, guards: tuple[str, ...]) -> None:
        """Check *node* itself, THEN descend -- an early `return` IS the
        statement in an `if` body, so a child-only walk never sees it. (It did
        not: this walk's own fourth red control caught the omission.)"""
        if isinstance(node, ast.If):
            condition = ast.unparse(node.test)
            visit(node.test, guards)
            for statement in node.body:
                visit(statement, (*guards, condition))
            for statement in node.orelse:
                visit(statement, (*guards, f"not ({condition})"))
            return
        if isinstance(node, ast.Call):
            dotted = _dotted(node.func)
            tail = dotted.split(".")[-1]
            # `pytest.skip` and a bare `skip` imported from pytest both count;
            # `sys.exit` and `os._exit` do not -- they are not abstentions,
            # they are the harness dying.
            if tail in ABSTAINING_CALLS and (dotted == tail or "pytest" in dotted):
                found.append(Abstention(function.name, dotted, node.lineno, " and ".join(guards)))
        if isinstance(node, ast.Raise) and node.exc is not None:
            raised = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if _dotted(raised).split(".")[-1] in ABSTAINING_EXCEPTIONS:
                found.append(
                    Abstention(
                        function.name,
                        f"raise {_dotted(raised)}",
                        node.lineno,
                        " and ".join(guards),
                    )
                )
        if isinstance(node, ast.Return) and is_test and guards:
            found.append(
                Abstention(function.name, "conditional return", node.lineno, " and ".join(guards))
            )
        for child in ast.iter_child_nodes(node):
            visit(child, guards)

    for statement in function.body:
        visit(statement, ())
    return found


def _called_names(node: ast.AST) -> set[str]:
    names = {
        _dotted(child.func).split(".")[0]
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and _dotted(child.func)
    }
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        names |= {argument.arg for argument in node.args.args}  # fixtures, by name
    return names


def section_six_functions(text: str) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every function defined in Section 6, plus every module-level function in
    the file it transitively reaches (a helper planted three sections up and
    called from here abstains just as effectively)."""
    tree = ast.parse(text)
    start, end = section_span(text, SECTION_SIX_BANNER)
    module_functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    selected = {name: node for name, node in module_functions.items() if start <= node.lineno < end}
    frontier = list(selected.values())
    while frontier:
        for name in _called_names(frontier.pop()):
            if name in module_functions and name not in selected:
                selected[name] = module_functions[name]
                frontier.append(module_functions[name])
    return list(selected.values())


def section_six_abstentions(text: str) -> list[Abstention]:
    """Every way out of running that Section 6 can reach, by any mechanism."""
    found: list[Abstention] = []
    for function in section_six_functions(text):
        found.extend(_abstentions_in(function))
    # Module scope too: `pytest.skip(..., allow_module_level=True)` inside the
    # section would silence every test in the FILE, not merely this section.
    tree = ast.parse(text)
    start, end = section_span(text, SECTION_SIX_BANNER)
    loose = [
        node
        for node in tree.body
        if start <= node.lineno < end
        and not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    ]
    if loose:
        holder = ast.parse("def _module_scope() -> None:\n    pass\n").body[0]
        assert isinstance(holder, ast.FunctionDef)  # narrowing, for mypy
        holder.name = "<module scope>"
        holder.body = loose
        found.extend(_abstentions_in(holder))
    return sorted(found, key=lambda item: item.lineno)


def section_six_load_sensing(text: str) -> list[str]:
    """Identifiers and env-var literals in Section 6's CODE (never its prose)
    that sense host load or worker identity."""
    offenders: list[str] = []
    docstrings: set[int] = set()
    for function in section_six_functions(text):
        for node in ast.walk(function):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                first = node.body[0] if node.body else None
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    docstrings.add(id(first.value))
        for node in ast.walk(function):
            if isinstance(node, ast.Attribute) and node.attr in LOAD_SENSING_NAMES:
                offenders.append(f"{function.name}:{node.lineno} {_dotted(node)}")
            elif isinstance(node, ast.Name) and node.id in LOAD_SENSING_NAMES:
                offenders.append(f"{function.name}:{node.lineno} {node.id}")
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and any(token in node.value for token in LOAD_SENSING_LITERALS)
            ):
                offenders.append(f"{function.name}:{node.lineno} {node.value!r}")
    return offenders


def test_the_load_immune_companion_exists_and_cannot_abstain() -> None:
    """The other half of Design §6, and the reason the wall-clock test's
    abstention is honest rather than a quiet retreat.

    Under `-n auto` the wall-clock startup test SKIPS on every worker, so it
    does not run in CI at all. That is only tolerable because a control that
    CANNOT abstain replaced it. Nobody gets to `fix` a flake by teaching the
    replacement to skip too -- by ANY mechanism, which is the correction this
    guard carries after an independent verifier walked through the first
    version of it using the xdist skip shipped ten lines away.
    """
    text = IMPORT_BOUNDARIES.read_text()
    section_span(text, SECTION_SIX_BANNER)  # asserts the section still exists

    for name in SECTION_SIX_TESTS:
        assert f"def {name}" in text, f"Section 6 lost {name}"

    unsanctioned = [item for item in section_six_abstentions(text) if not item.sanctioned]
    assert unsanctioned == [], (
        "Section 6 has grown an abstention that is not the build-absent precondition:\n  "
        + "\n  ".join(str(item) for item in unsanctioned)
        + "\nIts whole point is being load-IMMUNE. If it can abstain, the startup claim is "
        "held by two tests that both skip, i.e. by nothing. The only admissible "
        "precondition is `VENV_CONSOLE_SCRIPT.exists()`."
    )

    sensing = section_six_load_sensing(text)
    assert sensing == [], (
        f"Section 6's code senses host load or worker identity: {sensing}. Even without a "
        "skip, that is an abstention -- a census narrowed under load reports itself as a "
        "pass."
    )


def test_the_abstention_walk_is_not_vacuous() -> None:
    """A walk that finds nothing everywhere is indistinguishable from a walk
    that is broken, and would pass the guard above forever.

    `expertise/product.yaml`: *a uniform negative across a population expected
    to be split is the signature of a dead instrument.* Section 6 legitimately
    carries the build-absent precondition in two places, so the split is
    available on the live tree: the walk must FIND them, and must classify them
    as sanctioned.
    """
    found = section_six_abstentions(IMPORT_BOUNDARIES.read_text())
    assert found, (
        "the walk found no abstention at all in Section 6, which carries the "
        "`VENV_CONSOLE_SCRIPT.exists()` precondition in its module-scope fixture and in "
        "its planted-import control. The walk is dead, so the guard above proves nothing."
    )
    assert {item.function for item in found} >= {
        "help_imports",
        "test_a_planted_eager_import_reddens_section_6",
    }, f"the walk missed a known abstention: {[str(item) for item in found]}"
    assert all(item.sanctioned for item in found), (
        f"a live abstention is not the sanctioned one: {[str(item) for item in found]}"
    )


def plant_in_section_six(text: str, function: str, snippet: str) -> str:
    """Insert *snippet* into *function*'s body, after its docstring."""
    tree = ast.parse(text)
    node = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.FunctionDef) and item.name == function
    )
    indent = " " * node.body[0].col_offset
    lines = text.splitlines()
    planted = [indent + line if line else "" for line in snippet.strip("\n").splitlines()]
    at = node.body[0].end_lineno or node.body[0].lineno
    return "\n".join([*lines[:at], *planted, *lines[at:]]) + "\n"


def plant_decorator_on(text: str, function: str, decorator: str) -> str:
    tree = ast.parse(text)
    node = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.FunctionDef) and item.name == function
    )
    first = node.decorator_list[0].lineno if node.decorator_list else node.lineno
    lines = text.splitlines()
    return "\n".join([*lines[: first - 1], decorator, *lines[first - 1 :]]) + "\n"


#: The four bypasses, planted into the SAME function of the LIVE file, so each
#: red is the bypass a real agent would write and not a toy. `getloadavg` is the
#: original case the string guard caught; `PYTEST_XDIST_WORKER` is the one it
#: waved through; the decorator is the same proposition moved out of the body,
#: where an inline-call check would miss it; the bare conditional return is
#: abstention with no pytest API at all.
ABSTENTION_PLANTS: Final = (
    (
        "getloadavg",
        "inline",
        """
if os.getloadavg()[0] > 2.0:
    pytest.skip("host is loaded; cannot census reliably")
""",
    ),
    (
        "PYTEST_XDIST_WORKER",
        "inline",
        """
worker = os.environ.get("PYTEST_XDIST_WORKER")
if worker:
    pytest.skip(f"parallel session: this is xdist worker {worker}")
""",
    ),
    (
        "skipif decorator",
        "decorator",
        '@pytest.mark.skipif(os.environ.get("PYTEST_XDIST_WORKER") is not None, reason="xdist")',
    ),
    (
        "conditional return",
        "inline",
        """
if help_imports.total > 0:
    return
""",
    ),
)


@pytest.mark.parametrize(("label", "kind", "snippet"), ABSTENTION_PLANTS)
def test_every_abstention_mechanism_reddens_the_companion_guard(
    label: str, kind: str, snippet: str
) -> None:
    """The RED, four ways, and the second case is the one that matters.

    An independent verifier planted case 2 -- the xdist skip -- and the previous
    string-matching guard reported `1 passed` while Section 6 reported
    `3 skipped` on every worker. If any of these four stops reddening, this
    guard has decayed back into a phrase match and Section 6 can be taught to
    abstain again.
    """
    target = "test_help_imports_no_third_party_package_outside_the_pin"
    text = IMPORT_BOUNDARIES.read_text()
    planted = (
        plant_in_section_six(text, target, snippet)
        if kind == "inline"
        else plant_decorator_on(text, target, snippet)
    )
    assert planted != text, f"the {label} plant did not modify the source"

    unsanctioned = [item for item in section_six_abstentions(planted) if not item.sanctioned]
    assert [item for item in unsanctioned if item.function == target], (
        f"the {label} bypass was NOT caught: {[str(item) for item in unsanctioned]}. This is "
        "the exact defect this guard was rewritten to end -- a guard that catches one named "
        "mechanism answers 'is this STRING gone', not 'is this CLAIM gone' (`B-106`)."
    )
    # And the same plant leaves the LIVE tree clean, so the red is the plant's.
    assert [item for item in section_six_abstentions(text) if not item.sanctioned] == []


def test_the_sanctioned_precondition_cannot_be_used_as_a_trojan() -> None:
    """Keying on the CONDITION rather than on the function name, asserted.

    The obvious next bypass is to write the load abstention INSIDE the fixture
    that is already permitted to skip. A name-keyed allowlist would wave that
    through; this one does not, because what is sanctioned is the proposition
    `the build is absent`, not the identity of the function stating it.
    """
    text = IMPORT_BOUNDARIES.read_text()
    planted = plant_in_section_six(
        text,
        "help_imports",
        'if os.environ.get("PYTEST_XDIST_WORKER"):\n    pytest.skip("not under xdist")\n',
    )
    caught = [item for item in section_six_abstentions(planted) if not item.sanctioned]
    assert [item for item in caught if item.function == "help_imports"], (
        f"an xdist skip inside the sanctioned fixture was accepted: {[str(i) for i in caught]}"
    )


def test_load_sensing_reddens_even_without_a_skip() -> None:
    """An abstention that reports itself as a pass: narrow the census under
    load, assert nothing, stay green. No `pytest.skip` is involved, so the
    abstention walk above is blind to it by construction -- which is why the
    load-sensing rule is a second, separate proposition rather than a
    convenience."""
    text = IMPORT_BOUNDARIES.read_text()
    assert section_six_load_sensing(text) == []
    planted = plant_in_section_six(
        text,
        "test_help_import_count_stays_under_the_ceiling",
        "if os.getloadavg()[0] > 4.0:\n    help_imports = help_imports._replace(total=0)\n",
    )
    assert section_six_load_sensing(planted), "a planted `os.getloadavg()` was not seen"


# --------------------------------------------------------------------------- #
# AC20 -- no bare wall-clock claim about the gate survives in TESTING.md
# --------------------------------------------------------------------------- #

#: The SUBJECT of the forbidden proposition: the gate as a whole. Deliberately
#: NOT every duration in the document -- `TESTING.md`'s B-034 forensics quote a
#: single subprocess call at 0.245s vs 15.8s and an 84-test band at 14.49s vs
#: 544.59s, and those are microbenchmarks stated WITH their conditions. A guard
#: that reddened on those would be deleted the first time someone recorded a
#: measurement properly, and then it would guard nothing.
CLAIM_SUBJECT: Final[re.Pattern[str]] = re.compile(
    r"make\s+(ci|cover|test)\b|the\s+(?:\w+\s+)?(?:full\s+|local\s+|whole\s+)?(?:gate|suite)\b",
    re.IGNORECASE,
)

#: The PREDICATE: a duration, however spelled. `B-106` survived `B-101` because
#: an exact-phrase grep answers "is this STRING gone", not "is this CLAIM gone",
#: so this matches the shape rather than the sentence that was deleted.
CLAIM_DURATION: Final[re.Pattern[str]] = re.compile(
    r"(~|about\s+|roughly\s+|around\s+)\s*\d+(?:\.\d+)?\s*(?:s\b|sec\w*|m\b|min\w*)",
    re.IGNORECASE,
)

#: How close the subject and the duration must be to count as one claim.
CLAIM_WINDOW: Final = 160


def wall_clock_claims(text: str) -> list[str]:
    """Every "<the gate> ... <duration>" proposition in *text*, with context."""
    findings: list[str] = []
    for duration in CLAIM_DURATION.finditer(text):
        window = text[max(0, duration.start() - CLAIM_WINDOW) : duration.start()]
        subject = CLAIM_SUBJECT.search(window)
        if subject is None:
            continue
        line = text.count("\n", 0, duration.start()) + 1
        findings.append(f"line {line}: ...{window[subject.start() :]}{duration.group(0)}...")
    return findings


def test_testing_md_states_no_bare_wall_clock_claim_about_the_gate() -> None:
    """AC20. `TESTING.md` claimed `make cover` ~77s and `make ci` ~80s. `X-109`
    corrected that figure ON THE RECORD to ~152 s and the file never followed,
    leaving a documented number wrong by roughly 6x -- and it is the one class
    of documented figure a "re-run the command and compare" mechanism
    structurally cannot check, because re-running `make ci` inside a doc test is
    neither cheap nor deterministic."""
    findings = wall_clock_claims(TESTING_DOC.read_text())
    assert findings == [], (
        "TESTING.md states a wall-clock figure for the gate. A bare duration in prose "
        "cannot be kept true; point at the protocol and perf/gate-timings.jsonl instead. "
        f"Offenders: {findings}"
    )


@pytest.mark.parametrize(
    "planted",
    [
        pytest.param(
            "On a typical laptop the full gate takes about 90 seconds.", id="ac20-example"
        ),
        pytest.param(
            "`make cover` now finishes in roughly 4 min on this host.", id="different-unit"
        ),
        pytest.param(
            "Expect the whole suite to run in around 300 s end to end.", id="no-make-token"
        ),
    ],
)
def test_a_differently_worded_claim_reddens_the_guard(planted: str) -> None:
    """AC20's RED, and the criterion is explicit that an exact-phrase guard which
    only catches the sentence just deleted FAILS it. None of these three is the
    sentence that was removed; two name no `make` target at all."""
    findings = wall_clock_claims(f"# heading\n\nSome context.\n\n{planted}\n")
    assert findings, f"the guard did not notice: {planted!r}"


def test_the_guard_does_not_flag_a_microbenchmark_with_its_conditions() -> None:
    """The negative control. Without this the guard would be tuned by whoever it
    first annoyed, and the useful half would go with it."""
    benign = (
        "A single isolated `info` subprocess call measured 0.245s uninstrumented vs "
        "15.8s instrumented (~65x); the 84-test band measured 14.49s vs 544.59s."
    )
    assert wall_clock_claims(benign) == []


# --------------------------------------------------------------------------- #
# The harness is executable, not merely present
# --------------------------------------------------------------------------- #


def test_the_harness_refuses_an_unknown_target_rather_than_measuring_something_else() -> None:
    result = subprocess.run(  # noqa: S603 - this interpreter, a literal argv
        [sys.executable, str(SCRIPTS_DIR / "measure_gate.py"), "--target", "not-a-target"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode != 0
    assert "not-a-target" in result.stderr


def test_the_gate_timing_target_is_not_a_prerequisite_of_ci() -> None:
    """Design §3, asserted rather than trusted to a comment. `make gate-timing`
    passes `--baseline`, which REFUSES on a host it cannot verify quiet -- so
    wiring it into `ci` would make the gate refuse to run on any loaded box."""
    text = MAKEFILE.read_text()
    assert re.search(r"^gate-timing:", text, re.MULTILINE), "the gate-timing target is gone"
    ci_line = next(line for line in text.splitlines() if line.startswith("ci:"))
    assert "gate-timing" not in ci_line, f"gate-timing joined `ci`'s prerequisites: {ci_line}"


def test_perf_is_not_shipped_in_the_sdist() -> None:
    """`perf/` is dev data. Adding it would change the distributed artifact,
    which scripts/assert_artifacts.py gates in CI's `build` job."""
    include = re.search(
        r"\[tool\.hatch\.build\.targets\.sdist\]\s*\ninclude\s*=\s*\[(.*?)\]",
        PYPROJECT.read_text(),
        re.DOTALL,
    )
    assert include is not None
    assert "perf" not in include.group(1)


def test_the_startup_test_abstains_rather_than_failing_on_a_loaded_host() -> None:
    """The instrument repair, pinned. `B-098` names the cost exactly: a control
    that goes red without a defect costs more than one that stays green, because
    a phantom red gets chased into a spec."""
    text = CLI_SPINE.read_text()
    assert "def startup_gate_abstention_reason" in text
    assert "pytest.skip(reason)" in text, (
        "the startup budget no longer abstains; it will flake again the moment the host is "
        "busy, and its own measured spread (28.3 ms) exceeds any headroom it can have"
    )
    assert "PYTEST_XDIST_WORKER" in text, (
        "the abstention does not know about xdist, so under `-n auto` it will measure "
        "wall-clock while seven sibling workers saturate the box"
    )
