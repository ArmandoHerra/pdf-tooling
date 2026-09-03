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

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

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

#: The ten jobs, re-derived from the mapping rather than asserted from memory.
EXPECTED_JOB_COUNT: Final = 10


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


def test_ci_yml_parses_to_exactly_ten_jobs() -> None:
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


def test_the_load_immune_companion_exists_and_cannot_abstain() -> None:
    """The other half of Design §6, and the reason the abstention above is
    honest rather than a quiet retreat.

    Under `-n auto` the wall-clock startup test SKIPS on every worker, so it
    does not run in CI at all. That is only acceptable because a control that
    CANNOT abstain replaced it. This test pins that: Section 6 of
    tests/test_import_boundaries.py must exist, and its three assertions must
    not be guarded by a quietness precondition. Nobody gets to `fix` a flake by
    teaching the replacement to skip too.
    """
    text = IMPORT_BOUNDARIES.read_text()
    assert "Section 6 -- what `pdftoolkit --help` IMPORTS" in text, (
        "the contention-immune companion is gone; the startup claim is now held by a test "
        "that skips under `-n auto`, i.e. by nothing"
    )
    for name in (
        "test_help_imports_no_third_party_package_outside_the_pin",
        "test_help_import_count_stays_under_the_ceiling",
        "test_the_help_import_census_is_not_vacuous",
    ):
        assert f"def {name}" in text, f"Section 6 lost {name}"
    body = text[text.index("class HelpImports") :]
    assert "getloadavg" not in body, (
        "Section 6 has grown a load precondition. Its whole point is being load-IMMUNE -- "
        "if it can abstain, the startup claim is held by two tests that both skip."
    )


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
