"""PDF-17 — the coverage floor's semantics, ruled with instruments not comments.

`pyproject.toml:146` reads `branch = false`. The floor's NUMBER stayed **85**
while the property it enforces weakened from branch coverage to line coverage,
and the only record of that is a comment — the same kind of comment that, three
lines further down, names the wrong file for its own opt-out. This module turns
the three things a comment cannot do into tests:

1. **An expiry alarm (AC19).** `pyproject.toml:142-145` calls re-enabling
   `branch = true` *"a legitimate follow-up once coverage.py/CPython ship the
   version combination that supports branch measurement under `sys.monitoring`"*.
   That is a TODO nobody will read on the day it comes true.
   `test_the_branch_coverage_deviation_has_not_expired` fails, naming PDF-17,
   the moment the installed combination supports it.

2. **The third gaming lever, closed (AC20).** `PDF-06:236`'s anti-gaming rule
   forbids `omit` and forbids lowering `fail_under`. It says nothing about
   `# pragma: no cover`, of which there are 46 under `src/`. A pragma excludes
   lines from measurement exactly as `omit` excludes files. Every occurrence
   must carry a reason, and the total is pinned so it may be LOWERED freely and
   not RAISED silently.

3. **The `PLAN §12 R-13` opt-out, pinned and correctly documented (AC21).**
   Exactly one test scrubs `COVERAGE_PROCESS_*` from a child environment, and
   it is `tests/test_cli_spine.py`'s startup-budget test — not
   `tests/unit/test_subprocess_util.py`, which `pyproject.toml:155-157` named.

**This module lowers nothing.** `PDF-06:236`, verbatim: *"If 85% is unreachable,
the answer is more tests — never a lower `fail_under` and never an `omit`.
Lowering the floor is a BLOCKER reported to the PM, not an edit."*
`test_the_floor_has_not_been_weakened_by_any_route` is that rule as a control.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from registry import REPO_ROOT

SRC: Final[Path] = REPO_ROOT / "src"
TESTS: Final[Path] = REPO_ROOT / "tests"
PYPROJECT: Final[Path] = REPO_ROOT / "pyproject.toml"
MAKEFILE: Final[Path] = REPO_ROOT / "Makefile"
CI_WORKFLOW: Final[Path] = REPO_ROOT / ".github" / "workflows" / "ci.yml"

_PRAGMA: Final[re.Pattern[str]] = re.compile(r"#\s*pragma:\s*no cover(?P<reason>.*)$")

#: MEASURED at `2d19bcb` and again at this spec's own implementation HEAD, not
#: inherited: `grep -rc "pragma: no cover" src/ | awk -F: '{s+=$2} END {print s}'`
#: returns 46. This ceiling may be LOWERED freely by anyone who removes a
#: pragma. RAISING it is a decision, not a diff: state in the commit body why a
#: new line cannot be covered, per `PDF-06:236`'s anti-gaming rule extended to
#: the lever that rule left open. (A test cannot read a commit body -- the
#: mechanism is the ceiling; the process rule is this comment, and it is the
#: same shape as the `fail_under` rule it extends.)
PRAGMA_CEILING: Final[int] = 46

#: Pragmas that carry no reason. Empty is the goal; each entry is a FINDING
#: filed against `src/`, never a fix made here -- `PDF-17`'s `src/` budget is
#: zero lines (AC34, AC35). Keyed by (path, source line) rather than by line
#: number so an edit elsewhere in the file does not invalidate the entry, while
#: a change to the line ITSELF does.
UNREASONED_PRAGMA_ALLOWLIST: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        (
            "pdf_toolkit/cli/common.py",
            'if ctx is None or not hasattr(ctx, "get_parameter_source"):  # pragma: no cover',
        ),
    }
)

#: This module is the CHECKER for `COVERAGE_PROCESS_*` scrubbing, so its own
#: mentions of those names are not call sites. Excluded by name, with
#: `test_the_scrub_detector_sees_the_known_site` as the positive control that
#: the exclusion is not hiding anything.
_SCRUB_SCAN_EXEMPT: Final[frozenset[str]] = frozenset({"tests/test_coverage_policy.py"})

#: The ONE legitimate opt-out (`PLAN.md` §12 R-13, argued in place at
#: `tests/test_cli_spine.py:486-498`).
EXPECTED_SCRUB_SITE: Final[str] = "tests/test_cli_spine.py"


# --------------------------------------------------------------------------- #
# AC20 -- `# pragma: no cover`, the third gaming lever
# --------------------------------------------------------------------------- #


def pragma_sites(root: Path) -> list[tuple[str, int, str, str]]:
    """(relative path, line number, stripped source line, reason) per pragma."""
    found: list[tuple[str, int, str, str]] = []
    for path in sorted(root.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = _PRAGMA.search(line)
            if match is None:
                continue
            relative = path.relative_to(root).as_posix()
            found.append((relative, lineno, line.strip(), match.group("reason").strip(" -\t")))
    return found


def unreasoned_pragmas(sites: list[tuple[str, int, str, str]]) -> list[tuple[str, str]]:
    return sorted((relative, line) for relative, _, line, reason in sites if not reason)


def test_the_pragma_total_has_not_been_raised() -> None:
    sites = pragma_sites(SRC)
    assert len(sites) <= PRAGMA_CEILING, (
        f"{len(sites)} `# pragma: no cover` occurrences under src/, above the pinned ceiling "
        f"of {PRAGMA_CEILING}. A pragma excludes lines from measurement exactly as an `omit` "
        "excludes files, and PDF-06:236's anti-gaming rule forbids the latter. Lowering this "
        "ceiling is free; raising it is a decision that belongs in the commit body."
    )


def test_every_pragma_carries_a_reason() -> None:
    offenders = unreasoned_pragmas(pragma_sites(SRC))
    unexpected = [row for row in offenders if row not in UNREASONED_PRAGMA_ALLOWLIST]
    assert unexpected == [], (
        "`# pragma: no cover` without a reason on the same line -- a silent exclusion is "
        "indistinguishable from an oversight six months later:\n  "
        + "\n  ".join(f"{path}: {line}" for path, line in unexpected)
    )


def test_no_unreasoned_pragma_allowlist_entry_is_stale() -> None:
    """The allowlist records `src/` findings PDF-17 is forbidden to FIX (AC35).
    It must not outlive them: an entry that no longer resolves means the pragma
    was reasoned or removed, and the entry is now hiding nothing while looking
    like it hides something."""
    offenders = set(unreasoned_pragmas(pragma_sites(SRC)))
    stale = sorted(UNREASONED_PRAGMA_ALLOWLIST - offenders)
    assert stale == [], f"allowlisted unreasoned pragma(s) no longer exist: {stale}"


@pytest.mark.parametrize(
    ("label", "line"),
    (
        ("bare", "    x = 1  # pragma: no cover"),
        ("bare-with-colon-spacing", "    x = 1  #pragma:no cover"),
    ),
)
def test_the_reason_check_fires_on_an_unreasoned_pragma(
    label: str, line: str, tmp_path: Path
) -> None:
    """AC20's red, synthetic: a planted unreasoned pragma is reported."""
    planted = tmp_path / "planted.py"
    planted.write_text(line + "\n", encoding="utf-8")
    assert unreasoned_pragmas(pragma_sites(tmp_path)) == [("planted.py", line.strip())], label


def test_the_reason_check_accepts_a_reasoned_pragma(tmp_path: Path) -> None:
    """The positive half: a check that flagged everything would be deleted
    rather than fixed."""
    (tmp_path / "ok.py").write_text(
        "    x = 1  # pragma: no cover - typing only\n", encoding="utf-8"
    )
    assert unreasoned_pragmas(pragma_sites(tmp_path)) == []


def test_the_count_pin_fires_on_a_planted_pragma(tmp_path: Path) -> None:
    """AC20's other red: the total moves the moment a pragma is added."""
    for index in range(PRAGMA_CEILING + 1):
        (tmp_path / f"m{index}.py").write_text(
            "x = 1  # pragma: no cover - planted\n", encoding="utf-8"
        )
    assert len(pragma_sites(tmp_path)) > PRAGMA_CEILING


# --------------------------------------------------------------------------- #
# AC21 -- the PLAN §12 R-13 coverage opt-out, pinned at exactly one
# --------------------------------------------------------------------------- #


def coverage_scrub_sites(root: Path) -> list[str]:
    """Test modules that name `COVERAGE_PROCESS_START`/`COVERAGE_PROCESS_CONFIG`
    as string CONSTANTS — i.e. in code, not in prose.

    AST rather than grep, deliberately: `tests/test_cli_spine.py:494` mentions
    both names in a COMMENT explaining the opt-out, and a grep-based pin would
    have counted the explanation as a second call site. `PDF-06`'s own AC5
    mechanization is the cautionary case — a naive uppercase substring scan
    that returns 2 hits against a required nothing, both of them prose.
    """
    wanted = {"COVERAGE_PROCESS_START", "COVERAGE_PROCESS_CONFIG"}
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        try:
            relative = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:  # a synthetic tree under tmp_path, from the proofs below
            relative = path.name
        if relative in _SCRUB_SCAN_EXEMPT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.Constant) and node.value in wanted for node in ast.walk(tree)):
            found.append(relative)
    return found


def test_exactly_one_test_module_scrubs_the_coverage_environment() -> None:
    sites = coverage_scrub_sites(TESTS)
    assert sites == [EXPECTED_SCRUB_SITE], (
        f"expected exactly one COVERAGE_PROCESS_* opt-out ({EXPECTED_SCRUB_SITE}, the "
        f"PLAN §12 R-13 startup-budget test), found {sites}. Every other subprocess call "
        "site in this suite inherits the measured environment by default, which is what "
        'makes `patch = ["subprocess"]` measure the CLI at all.'
    )


def test_the_scrub_detector_sees_the_known_site(tmp_path: Path) -> None:
    """The positive control for the self-exemption above: the detector really
    does report a scrubbing module, so excluding this file is not what makes
    the pin pass."""
    planted = tmp_path / "tests"
    planted.mkdir()
    (planted / "test_planted.py").write_text(
        'env = {k: v for k, v in os.environ.items() if k != "COVERAGE_PROCESS_START"}\n',
        encoding="utf-8",
    )
    assert coverage_scrub_sites(planted) != []


def test_the_scrub_detector_ignores_prose(tmp_path: Path) -> None:
    """The half `PDF-06`'s AC5 got wrong: a comment naming the variable is not
    a call site."""
    planted = tmp_path / "tests"
    planted.mkdir()
    (planted / "test_prose.py").write_text(
        "# COVERAGE_PROCESS_START is what a1_coverage.pth checks.\nx = 1\n", encoding="utf-8"
    )
    assert coverage_scrub_sites(planted) == []


def test_the_config_comment_names_the_real_opt_out() -> None:
    """B-033's other half: `pyproject.toml` named `tests/unit/test_subprocess_util.py`
    as the one module that scrubs the environment. It does not; the CLI-path
    opt-out is `tests/test_cli_spine.py`'s startup-budget test. A comment that
    points at the wrong file is worse than no comment — it sends the next
    reader to a module where nothing is wrong."""
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "test_subprocess_util" not in text, (
        "pyproject.toml still names tests/unit/test_subprocess_util.py as the coverage "
        "opt-out; the real one is tests/test_cli_spine.py (B-033)"
    )
    assert EXPECTED_SCRUB_SITE in text, (
        "pyproject.toml no longer names the real opt-out; the comment has gone back to "
        "being unlocatable"
    )


# --------------------------------------------------------------------------- #
# AC19 -- the expiry alarm for the branch-coverage deviation
# --------------------------------------------------------------------------- #

_SYSMON_REFUSAL: Final[re.Pattern[str]] = re.compile(
    r"can't use core\s*=?\s*[\"']?sysmon", re.IGNORECASE
)


def sysmon_refused_branch_measurement(output: str) -> bool:
    """Whether coverage.py said it could not measure branches under sysmon."""
    return _SYSMON_REFUSAL.search(output) is not None


def probe_branch_under_sysmon(tmp_path: Path) -> tuple[bool, str]:
    """(supported, raw output) for the INSTALLED coverage + CPython.

    Runs coverage.py for real with `COVERAGE_CORE=sysmon` and `--branch`,
    against a throwaway script in *tmp_path*, and reads whether it refused.

    FAIL-LOUD BY DESIGN. If coverage.py stops emitting that refusal — because
    support arrived, OR because the message was reworded — this reports
    "supported" and the alarm below fires, naming PDF-17. A human then looks.
    The alternative failure direction (silently reporting "still unsupported"
    forever) is the rotting TODO this replaces.
    """
    script = tmp_path / "probe.py"
    script.write_text("x = 1\nif x:\n    y = 2\n", encoding="utf-8")
    environment = dict(os.environ)
    environment["COVERAGE_CORE"] = "sysmon"
    environment["COVERAGE_FILE"] = str(tmp_path / ".coverage-probe")
    environment.pop("COVERAGE_PROCESS_START", None)
    environment.pop("COVERAGE_PROCESS_CONFIG", None)
    result = subprocess.run(
        [sys.executable, "-m", "coverage", "run", "--branch", "--rcfile=", str(script)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
        env=environment,
    )
    output = result.stdout + result.stderr
    return (not sysmon_refused_branch_measurement(output)), output


def test_the_branch_coverage_deviation_has_not_expired(tmp_path: Path) -> None:
    """AC19. `pyproject.toml:113-147` records the deviation and its cause:
    `branch = true` and `core = "sysmon"` are MUTUALLY EXCLUSIVE in the
    supported version combination, so restoring branch coverage re-enters
    `406420c494` (the ~25x band factor) by construction.

    This is the alarm for the day that stops being true. It is deliberately a
    FAILING test rather than a comment: PDF-17 measured the deviation and ruled
    it on the record, and the ruling has an expiry condition that nothing else
    watches.
    """
    supported, output = probe_branch_under_sysmon(tmp_path)
    assert not supported, (
        "coverage.py no longer refuses branch measurement under `sys.monitoring` on this "
        f"interpreter (coverage output: {output.strip()!r}).\n"
        "PDF-17 §8.1 ruled `branch = false` on the record BECAUSE `branch = true` forced "
        "the ctrace backend (~25x on the info/doctor/cli_contract band). That reason has "
        "now expired: re-measure both arms and revisit `[tool.coverage.run] branch` and "
        "`core` together, per PDF-17 AC17/AC18. Do NOT simply delete this test."
    )


def test_the_expiry_probe_can_report_both_answers() -> None:
    """Without this, `test_the_branch_coverage_deviation_has_not_expired` could
    be green because the refusal detector matches everything — the 24th control
    that cannot fail, installed by the spec written to end them."""
    assert sysmon_refused_branch_measurement(
        "Can't use core=sysmon: sys.monitoring can't measure branches in this version"
    )
    assert sysmon_refused_branch_measurement("can't use core sysmon: nope")
    assert not sysmon_refused_branch_measurement("")
    assert not sysmon_refused_branch_measurement("Wrote coverage data to .coverage")


# --------------------------------------------------------------------------- #
# AC22 -- the anti-gaming rule, as a control rather than a paragraph
# --------------------------------------------------------------------------- #


def test_the_floor_has_not_been_weakened_by_any_route() -> None:
    """`PDF-06:236`: *"If 85% is unreachable, the answer is more tests -- never
    a lower `fail_under` and never an `omit`. Lowering the floor is a BLOCKER
    reported to the PM, not an edit."* The floor lives on the COMMAND LINE in
    exactly two places (there is no `fail_under` key in `pyproject.toml`), and
    both must agree — a local gate that enforces a different number from CI is
    `PDF-28`'s subject, and this is the tripwire for it arriving by accident.
    """
    for path in (MAKEFILE, CI_WORKFLOW):
        text = path.read_text(encoding="utf-8")
        floors = re.findall(r"--cov-fail-under=(\d+)", text)
        assert floors == ["85"], (
            f"{path.name} declares coverage floor(s) {floors}, expected exactly one at 85"
        )
    config = PYPROJECT.read_text(encoding="utf-8")
    assert not re.search(r"^\s*omit\s*=", config, re.MULTILINE), (
        "an `omit` key appeared under [tool.coverage.*] -- PDF-06's AC14 forbids omitting "
        "anything under src/pdf_toolkit/, and an omit is how a floor gets met without tests"
    )
    assert not re.search(r"^\s*fail_under\s*=", config, re.MULTILINE), (
        "a `fail_under` key appeared in pyproject.toml. The floor is passed on the command "
        "line in Makefile and ci.yml; a second declaration is a second thing to lower."
    )
