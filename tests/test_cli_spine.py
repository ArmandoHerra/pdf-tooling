"""The CLI spine contract.

Everything asserted here is public API from v1.0.0 — the exit-code integers, the
structured output shapes, and which stream each of them goes to. A failure in
this file is not a defect in one verb; it is a defect in the contract every verb
inherits, so treat a red test here as a breaking change until proven otherwise.

Deliberately disjoint from the fixture-corpus and per-verb contract harness that
arrive later: this file owns the spine, and there is no ``conftest.py`` here yet.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import typing
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

from pdf_toolkit import errors
from pdf_toolkit.cli import exit_codes
from pdf_toolkit.cli.common import (
    GLOBAL_OPTIONS,
    GLOBAL_PARAMS,
    OUTPUT_FLAGS,
    REFUSED_PASSWORD_FLAGS,
    SAFETY_FLAGS,
    UNGOVERNED_FLAGS,
    build_config,
    validate_config,
)
from pdf_toolkit.models import SCHEMA_VERSION, ItemResult, OperationResult
from pdf_toolkit.output import OutputFormat, emit_error, emit_result, render_payload
from pdf_toolkit.output.logging import RedactingFilter, clear_secrets, register_secret

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import (  # noqa: E402
    _module_dotted_name,
    discover_verbs,
)
from registry import run_cli as registry_run_cli  # noqa: E402
from test_license_policy import EXTRA_FORBIDDEN, PLAN_FORBIDDEN  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
# HC-1, textual tier -- B-026 (PDF-24 Design §D8)
#
# There are TWO HC-1 name instruments in this repository and they used to
# DISAGREE. `tests/test_license_policy.py` is a four-shape AST walk over exact
# normalized names, list = PLAN_FORBIDDEN (13) + EXTRA_FORBIDDEN (10) = 23,
# with a freshness control (`assert len(PLAN_FORBIDDEN) == 13`). This file is
# the TEXTUAL tier -- a whole-file scan, which is the tier that catches a name
# inside a shell-out STRING the AST walk's four shapes cannot see. Its list was
# hand-typed at TWELVE and was missing `gs` and all ten tightening additions,
# `poppler` included, and NOTHING asserted the two lists related.
#
# ONE LIST NOW. The names are IMPORTED, never re-typed; a divergence is
# impossible rather than merely unlikely. `tests/test_license_policy.py` belongs
# to PDF-28 and is READ here, never edited -- two hand-maintained lists is the
# defect, one list with one owner is the fix, and one list with two owners would
# be a new defect.
# --------------------------------------------------------------------------- #

#: The one list, derived. 23 names at this writing; the number is never asserted
#: here -- `test_license_policy.py::test_forbidden_set_contains_the_plan_list`
#: owns the freshness control and deleting an entry reds it there.
SHARED_FORBIDDEN_NAMES: Final[tuple[str, ...]] = tuple(
    dict.fromkeys(PLAN_FORBIDDEN + EXTRA_FORBIDDEN)
)

#: **The AC21 `gs` decision, written down BESIDE the list with its reason** --
#: because the arrangement this replaces made the identical choice BY SILENCE
#: (`gs` was simply absent from the twelve).
#:
#: `gs` is matched by the textual tier with a WORD BOUNDARY, not by plain
#: substring. Measured at `8fd2146` over this tier's own haystacks
#: (`pyproject.toml`, `Makefile`, every `src/**/*.py`): plain substring `gs`
#: returns **282 occurrences across 59 (file, name) pairs**, and **every one of
#: them is inside a longer identifier or English word** -- `warnings` (105),
#: `flags` (34), `args` (31), `belongs` (10), `output_flags` (10), `alongside`,
#: `strings`, `langs`, `siblings`, `kwargs`, `settings`, `spellings`, `logs`,
#: `findings`, `docstrings` and nineteen more. `\bgs\b` returns **zero**. The
#: population excluded is therefore named, counted, and shown not to contain the
#: target (X-255).
#:
#: **This is a TIGHTENING, not a disarm, in both directions.** `gs` is not in
#: the twelve-name list this replaces, so nothing that was matched stops being
#: matched; and a word boundary still matches every realistic leak shape --
#: `subprocess.run(["gs", ...])`, a bare `gs -sDEVICE=...` recipe line, and
#: `/usr/bin/gs` (a `/` is not a word character). Ghostscript is additionally
#: covered by the AST tier, which matches `gs` on EXACT equality over imports,
#: `subprocess` argv[0] and `os.exec*`/`os.spawn*` basenames -- where the
#: realistic leak actually lives.
#:
#: **Scoped PER NAME, deliberately.** A blanket word-boundary rewrite of all 23
#: would be a WEAKENING, not a tightening: `\bpdftk\b` does NOT match
#: `use_pdftk_fallback`, because `_` is a word character. Every other name keeps
#: plain substring matching for exactly that reason.
WORD_BOUNDARY_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "gs": (
            "two characters; plain substring matches 'flags', 'args', 'warnings', 'settings' "
            "and 31 more enclosing words across 59 (file, name) pairs, none of them a "
            "Ghostscript reference. A word boundary still matches the realistic leak shapes "
            "(a shell-out argv[0], a bare recipe token, an absolute path) and the AST tier in "
            "tests/test_license_policy.py covers imports and argv[0] on exact equality."
        ),
    }
)

#: The plain-substring subset of the shared list. **This is the name five other
#: test modules import and use as `name in text.lower()`**
#: (`tests/unit/test_textract.py`, `tests/unit/test_verb_help_content.py`,
#: `tests/unit/test_compose.py`, `tests/integration/test_text_tables_cli.py`),
#: so it must stay substring-safe: every member here is long enough that a
#: substring hit is a real hit. Twelve names before PDF-24, twenty-two after --
#: those five consumers were widened by ten names with zero edits of their own.
FORBIDDEN_NAMES: Final[tuple[str, ...]] = tuple(
    name for name in SHARED_FORBIDDEN_NAMES if name not in WORD_BOUNDARY_NAMES
)

#: **The defined false-positive story** (AC20). Whole-file matching stays as the
#: textual tier -- it is the tier that sees a name in a shell-out string -- and
#: it gains an ENUMERATED, PER-`(file, name)`, INDIVIDUALLY-JUSTIFIED exemption
#: so a module under `src/` can cite `PLAN.md` §7.2 by name without any name
#: silently leaving the scan.
#:
#: **It is EMPTY, and that is the strongest form of it.** X-255: an exclusion
#: list added to a control while making it pass is presumptively a DISARM. This
#: tier passes at `8fd2146` with zero exemptions, so nothing here was added to
#: make anything green. The mechanism is proven on synthetic input below, and
#: `test_an_exemption_cannot_silence_a_whole_name` proves it cannot be widened
#: into one -- a bare skip list with no reasons is the same defect one level up.
#:
#: Keys are `(repo-relative POSIX path, forbidden name)`. A wildcard is not
#: REPRESENTABLE: there is no path-glob form and no name-only form.
TEXTUAL_EXEMPTIONS: Final[Mapping[tuple[str, str], str]] = MappingProxyType({})

CORE_DEPENDENCIES = {
    "pypdf",
    "pypdfium2",
    "reportlab",
    "pikepdf",
    "pdfplumber",
    "pytesseract",
    "pillow",
    "typer",
}

MAKEFILE_TARGETS = {
    "help",
    "build",
    "install",
    "run",
    "doctor",
    "test",
    "test-e2e",
    "cover",
    "fmt",
    "fmt-check",
    "lint",
    "typecheck",
    "vulncheck",
    "sast",
    "secret-scan",
    "licenses",
    # PDF-06 (decision.md file-contention table): the two §10.1 real-samples
    # targets, added to the same Makefile PDF-01 created. Sequential by
    # wave -- no overlap with PDF-01's 18 targets.
    "samples-scratch",
    "samples-check",
    # PDF-11 (decision.md §8 X-115): the @samples ordering, encoded ONCE as a
    # target instead of re-typed into every spec's Validation block.
    "samples-gate",
    # PDF-28: local counterparts for three CI-only checks. None joins `ci`'s
    # own prerequisite list -- see .github/gate-parity.toml `in_make_ci`.
    "engines-gate",
    "licenses-check",
    "artifacts-check",
    # PDF-29: the gate-timing protocol. Deliberately NOT in `ci`'s prerequisite
    # list -- a gate that measures itself on every run pays for the measurement
    # on every run, and `--baseline` refuses on a host it cannot verify quiet.
    "gate-timing",
    # PDF-30: the documentation gate. Deliberately NOT in `ci`'s prerequisite
    # list either -- `PDF-29` is halving a gate that had doubled, and two of
    # this target's arms cannot run in CI's shallow, planning-tree-less checkout
    # at all, so joining `ci` would trade a real local gate for a skipped one.
    "docs-gate",
    "ci",
    "clean",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def console_script() -> list[str]:
    """The argv prefix that runs the installed CLI as a real process."""
    sibling = Path(sys.executable).parent / "pdftoolkit"
    if sibling.exists():
        return [str(sibling)]
    found = shutil.which("pdftoolkit")
    if found:
        return [found]
    return [sys.executable, "-m", "pdf_toolkit"]


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the CLI as a subprocess, which is the only way exit codes are real."""
    return subprocess.run(
        [*console_script(), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        env=env,
    )


def sample_result(verb: str = "demo") -> OperationResult:
    return OperationResult(
        schema_version=SCHEMA_VERSION,
        verb=verb,
        dry_run=False,
        items=(
            ItemResult(
                input="a.pdf",
                output="b.pdf",
                ok=True,
                exit_code=0,
                message="done",
                bytes_before=10,
                bytes_after=8,
                duration_ms=1,
            ),
            ItemResult(
                input="c.pdf",
                output=None,
                ok=False,
                exit_code=1,
                message="broken",
                bytes_before=None,
                bytes_after=None,
                duration_ms=2,
            ),
        ),
        warnings=("careful",),
        duration_ms=3,
    )


def default_flag_values(**overrides: object) -> dict[str, object]:
    values = {spec.name: spec.default for spec in GLOBAL_PARAMS}
    values.update(overrides)
    return values


# --------------------------------------------------------------------------- #
# Exit codes — public API
# --------------------------------------------------------------------------- #


def test_exit_code_constants_hold_their_published_integers() -> None:
    assert exit_codes.OK == 0
    assert exit_codes.FAILURE == 1
    assert exit_codes.USAGE == 2
    assert exit_codes.ENGINE_MISSING == 3
    assert exit_codes.NO_INPUT == 4
    assert exit_codes.REFUSED == 5
    assert exit_codes.AUTH == 6
    assert exit_codes.ALL_EXIT_CODES == (0, 1, 2, 3, 4, 5, 6)


def test_errors_expose_exactly_one_class_per_non_zero_exit_code() -> None:
    subclasses = errors.PdfToolkitError.__subclasses__()
    codes = sorted(subclass.exit_code for subclass in subclasses)
    assert codes == [1, 2, 3, 4, 5, 6], f"got {[c.__name__ for c in subclasses]}"

    assert errors.FailureError.exit_code == exit_codes.FAILURE
    assert errors.UsageError.exit_code == exit_codes.USAGE
    assert errors.EngineMissingError.exit_code == exit_codes.ENGINE_MISSING
    assert errors.NoInputError.exit_code == exit_codes.NO_INPUT
    assert errors.RefusedError.exit_code == exit_codes.REFUSED
    assert errors.AuthError.exit_code == exit_codes.AUTH

    kinds = sorted(subclass.kind for subclass in subclasses)
    assert len(set(kinds)) == len(kinds), "each error class needs a distinct machine kind"


def test_base_error_defaults_to_failure_and_carries_the_redaction_marker() -> None:
    error = errors.PdfToolkitError("boom")
    assert error.exit_code == exit_codes.FAILURE
    assert error.redacted is False
    assert errors.AuthError("nope", redacted=True).redacted is True


def _error_descendants() -> tuple[type[errors.PdfToolkitError], ...]:
    def walk(cls: type[errors.PdfToolkitError]) -> list[type[errors.PdfToolkitError]]:
        found = [cls]
        for child in cls.__subclasses__():
            found.extend(walk(child))
        return found

    return tuple(walk(errors.PdfToolkitError))


def test_every_error_class_carries_a_published_exit_code() -> None:
    """PDF-01 AC8's SURVIVING invariant, and the half nothing measured.

    AC8 as written requires *"exactly one exception class per non-zero code"*.
    That is **no longer true and is correctly no longer true**: the mapping is
    many-to-one (`REFUSED` alone carries seven concrete classes). The property
    the exit-code table actually depends on is the partition plus membership:
    **one BASE class per non-zero code** (the assertion above, which reads
    `PdfToolkitError.__subclasses__()` -- direct subclasses only) **and every
    concrete descendant's `exit_code` a member of `ALL_EXIT_CODES`**.

    **No cardinality is pinned here, deliberately.** A criterion pinning an
    error-class COUNT would turn a later spec red for adding a correctly
    classified subclass, which is a control failing for a reason it does not
    claim.
    """
    descendants = _error_descendants()
    assert len(descendants) > len(errors.PdfToolkitError.__subclasses__()), (
        "the walk found no subclass beyond the direct ones -- it is not transitive"
    )
    offenders = [
        f"{cls.__name__}: exit_code={cls.exit_code!r}"
        for cls in descendants
        if cls.exit_code not in exit_codes.ALL_EXIT_CODES
    ]
    assert offenders == [], (
        "every error class's exit_code must be a published integer (D-09 -- the table is "
        f"public API and renumbering is a major bump): {offenders}"
    )
    # A descendant may only narrow the MESSAGE, never the code's meaning: each
    # concrete class carries the code of exactly one base.
    base_codes = {base.exit_code for base in errors.PdfToolkitError.__subclasses__()}
    for cls in descendants:
        if cls is errors.PdfToolkitError:
            continue
        assert cls.exit_code in base_codes, (
            f"{cls.__name__} carries exit_code {cls.exit_code}, which no base class owns"
        )


# --------------------------------------------------------------------------- #
# The command surface
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ((), 0),
        (("--help",), 0),
        (("--version",), 0),
        (("bogus",), 2),
        (("--bogus-flag",), 2),
        (("version",), 0),
        (("version", "--help"), 0),
        (("-q", "-v", "version"), 2),
        (("--no-backup", "version"), 2),
        (("version", "--no-backup"), 2),
        (("-O", "x.pdf", "--out-dir", "d", "version"), 2),
        (("--password-file", "/no/such/file", "version"), 2),
        # AC27/E13: re-pointed at `split`, which DOES declare `--name` in its
        # OR-3 consumption set (`version` does not) -- against `version` this
        # case would now be answered by OR-3's own refusal first, going
        # vacuous for `_validate_name_template`'s path-separator rule. Against
        # `split` it still reaches that rule, so the CLI-level shape check
        # stays exercised. See test_name_template_shape_message_is_still_
        # reachable_through_a_flag_consuming_verb below for the message half.
        (("--name", "a/b", "split", "x.pdf"), 2),
        (("--threads", "0", "version"), 2),
        # PDF-24 AC27: the same table at the POST-VERB spelling. `--no-backup`
        # already carried both (PDF-01's own F-4 resolution); the other four
        # invocation errors were pinned pre-verb only, so the §4.2 inheritance
        # contract was asserted for one flag and assumed for four. The global
        # block is declared at BOTH levels from one source of truth, and a
        # divergence at the verb level is a public-API regression (D-09), not a
        # cosmetic defect.
        (("version", "-q", "-v"), 2),
        (("version", "-O", "x.pdf", "--out-dir", "d"), 2),
        (("version", "--password-file", "/no/such/file"), 2),
        (("split", "x.pdf", "--name", "a/b"), 2),
        (("version", "--threads", "0"), 2),
    ],
    ids=lambda value: str(value),
)
def test_command_surface_exit_codes(argv: tuple[str, ...], expected: int) -> None:
    result = run_cli(*argv)
    assert result.returncode == expected, f"{argv} -> {result.returncode}\n{result.stderr}"


@pytest.mark.e2e
def test_output_and_out_dir_mutual_exclusion_message_wins_over_or3() -> None:
    """AC27/E13: `-O`/`--out-dir` together is a verb-independent contradiction
    (Design §D12's ordering rule, position 1) -- diagnosed BEFORE the OR-3
    output-flag-consumption check (position 2), even on `version`, which
    consumes neither flag and would otherwise report its own OR-3 refusal
    instead. Both are exit 2; this proves WHICH message fires, which is what
    proves the ordering rule rather than assuming it."""
    result = run_cli("-O", "x.pdf", "--out-dir", "d", "version")
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "mutually exclusive" in combined
    assert "--output" in combined
    assert "--out-dir" in combined


@pytest.mark.e2e
def test_name_template_shape_message_is_still_reachable_through_a_flag_consuming_verb() -> None:
    """AC27/E13: `split` declares `--name`, so `_validate_name_template`'s
    path-separator rule is still exercised through the CLI rather than being
    pre-empted by OR-3's own refusal (which is what `version` -- not
    declaring `--name` -- would answer with instead, per
    test_command_surface_exit_codes[('--name', 'a/b', 'split', 'x.pdf')])."""
    result = run_cli("--name", "a/b", "split", "x.pdf")
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "path separator" in combined


@pytest.mark.e2e
def test_root_help_names_every_global_option() -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    for option in GLOBAL_OPTIONS:
        assert option in result.stdout, f"root --help does not name {option}"


@pytest.mark.e2e
def test_verb_help_names_the_same_global_option_block() -> None:
    result = run_cli("version", "--help")
    assert result.returncode == 0
    for option in GLOBAL_OPTIONS:
        assert option in result.stdout, f"`version --help` does not name {option}"


@pytest.mark.e2e
def test_a_global_flag_means_the_same_before_and_after_the_verb() -> None:
    before = run_cli("--dry-run", "version", "-o", "json")
    after = run_cli("version", "--dry-run", "-o", "json")
    assert before.returncode == after.returncode == 0
    assert before.stdout == after.stdout
    assert json.loads(before.stdout)["dry_run"] is True


@pytest.mark.e2e
def test_version_flag_reports_tool_python_and_engine_versions() -> None:
    result = run_cli("--version")
    assert result.returncode == 0
    line = result.stdout.strip()
    assert "\n" not in line, "--version prints exactly one line"
    assert "pdftoolkit" in line
    assert "Python" in line
    assert re.search(r"pypdf \d+\.\d+", line), line

    # PDF-24: the three clauses above assert LABELS, not VALUES. `"Python" in
    # line` is satisfied by the literal word sitting in `version_line()`'s own
    # f-string -- MEASURED: replacing `python_version()`'s whole return value
    # with a constant left this test GREEN. AC7 requires the line to carry
    # *the running Python version* and *the tool version*, so both are asserted
    # against a value computed here rather than against a word.
    import platform

    from pdf_toolkit import __version__ as tool_version

    assert platform.python_version() in line, (
        f"--version does not carry the running interpreter's version "
        f"({platform.python_version()}): {line}"
    )
    assert tool_version in line, (
        f"--version does not carry the tool version ({tool_version}): {line}"
    )


@pytest.mark.e2e
def test_every_entry_point_prints_byte_identical_help() -> None:
    canonical = run_cli("--help")
    module = subprocess.run(
        [sys.executable, "-m", "pdf_toolkit", "--help"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert module.returncode == 0
    assert module.stdout == canonical.stdout

    alias = Path(sys.executable).parent / "pdf-toolkit"
    if alias.exists():
        aliased = subprocess.run(
            [str(alias), "--help"], capture_output=True, text=True, check=False, cwd=REPO_ROOT
        )
        assert aliased.stdout == canonical.stdout


# --------------------------------------------------------------------------- #
# PDF-24 -- the governance partition of the global-flag block, and the two
# by-construction controls over it.
#
# Before this section the governance surface was ONE hand-typed tuple
# (`OUTPUT_FLAGS`) plus a comment naming eleven flags in prose. A comment is not
# a control: it cannot fail. `996f9eb6bc` is what a prose-only classification
# produced -- `--force` and `-y` advertised, accepted and silently ignored at
# exit 0 on all five verbs that write nothing.
#
# Two INDEPENDENT ways a flag could exist without being checked are closed here:
#   * the ENFORCEMENT axis -- a flag in `GLOBAL_OPTIONS` that no class governs;
#   * the ROSTER axis -- a `_ParamSpec` in `GLOBAL_PARAMS` that renders and binds
#     on all 26 verbs but is absent from `GLOBAL_OPTIONS`, which every other
#     control in this repository iterates. Nothing asserted the two agreed, and
#     every existing assertion is a PRESENCE check, never an equality.
# --------------------------------------------------------------------------- #


def declared_spellings(spec: object) -> tuple[str, ...]:
    """Every command-line spelling one `_ParamSpec` declares, in its own order.

    Read off the `typer.Option` sitting in the `Annotated` metadata rather than
    re-typed. `typer.Option`'s FIRST positional parameter is `default`, so a
    single-spelling declaration lands its spelling there and leaves
    `param_decls` empty -- verified at `8fd2146`, where `--dry-run` reads
    `default='--dry-run', param_decls=()` and `-o/--output-format` reads
    `default='-o', param_decls=('--output-format',)`. Both shapes are handled,
    and `test_the_derivation_is_not_vacuous` below is what stops a typer upgrade
    turning this into a silently empty set.
    """
    annotation = getattr(spec, "annotation", None)
    args = typing.get_args(annotation)
    if len(args) < 2:
        return ()
    info = args[1]
    spellings: list[str] = []
    default = getattr(info, "default", None)
    if isinstance(default, str) and default.startswith("-"):
        spellings.append(default)
    spellings.extend(getattr(info, "param_decls", ()) or ())
    return tuple(spellings)


def derived_global_options() -> tuple[str, ...]:
    """`GLOBAL_OPTIONS`, computed from `GLOBAL_PARAMS` minus the OR-4 hidden three.

    Declaration order is preserved because C2 and the §4.2 root-vs-verb diff
    both read `GLOBAL_OPTIONS` in order.
    """
    refused = set(REFUSED_PASSWORD_FLAGS)
    derived: list[str] = []
    for spec in GLOBAL_PARAMS:
        for spelling in declared_spellings(spec):
            if spelling.startswith("--") and spelling not in refused:
                derived.append(spelling)
    return tuple(derived)


def test_the_derivation_is_not_vacuous() -> None:
    """The non-vacuity proof for `derived_global_options` itself.

    Without it, a typer upgrade that moved `param_decls` could make the
    derivation return `()` -- and `test_global_options_equals_the_derived_roster`
    would then compare an empty tuple against an empty tuple only if
    `GLOBAL_OPTIONS` were also emptied, but every OTHER control in this file
    iterates `GLOBAL_OPTIONS` and would go vacuously green on an empty roster.
    Both failure directions are pinned here.
    """
    derived = derived_global_options()
    assert derived, "the derivation returned nothing -- it is not measuring the block"
    assert len(derived) == len(set(derived)), f"the derivation duplicates a spelling: {derived}"
    for expected in ("--dry-run", "--output-format", "--output", "--threads", "--version"):
        assert expected in derived, expected
    assert declared_spellings(GLOBAL_PARAMS[0]) == ("--dry-run",)
    assert "--output-format" in declared_spellings(GLOBAL_PARAMS[1])
    assert "-o" in declared_spellings(GLOBAL_PARAMS[1])


def test_global_options_equals_the_derived_roster() -> None:
    """AC4 -- the ROSTER axis, closed.

    A sixteenth `_ParamSpec` added to `GLOBAL_PARAMS` and not to
    `GLOBAL_OPTIONS` renders in all 26 helps, binds at runtime, and was
    invisible to every control in this repository before this assertion --
    including the contract harness's C2, whose whole job is policing this block.

    Equality, not containment, and ORDER-SENSITIVE: `GLOBAL_OPTIONS`'s order is
    read by C2 and by the §4.2 root-vs-verb diff.
    """
    assert GLOBAL_OPTIONS == derived_global_options()


def test_the_hidden_password_refusals_stay_out_of_the_block() -> None:
    """OR-4, and the reason AC4's derivation must SUBTRACT rather than filter by
    `hidden=`: `tests/test_password_leaks.py`'s disjointness assertion is a free
    red control on this derivation, and a derivation that accidentally included
    the hidden three would turn it red rather than passing quietly."""
    assert set(REFUSED_PASSWORD_FLAGS) & set(GLOBAL_OPTIONS) == set()
    declared = {spelling for spec in GLOBAL_PARAMS for spelling in declared_spellings(spec)}
    assert set(REFUSED_PASSWORD_FLAGS) <= declared, (
        "the hidden three must still be DECLARED -- subtracting them from the block is "
        "the point; removing them from the parameter list would delete OR-4's refusal"
    )


def test_the_global_block_is_exhaustively_partitioned() -> None:
    """AC5 -- the ENFORCEMENT axis, closed *by construction*.

    Pairwise disjoint, union exactly `set(GLOBAL_OPTIONS)`, every ungoverned
    member carrying a non-empty reason. Adding a sixteenth flag to
    `GLOBAL_OPTIONS` without classifying it is a red test from here on, which is
    the literal reading of this item's deliverable -- *a flag cannot be declared
    without being checked*.
    """
    governed_output = set(OUTPUT_FLAGS)
    governed_safety = set(SAFETY_FLAGS)
    ungoverned = set(UNGOVERNED_FLAGS)

    assert governed_output & governed_safety == set()
    assert governed_output & ungoverned == set()
    assert governed_safety & ungoverned == set()

    assert governed_output | governed_safety | ungoverned == set(GLOBAL_OPTIONS)
    assert len(OUTPUT_FLAGS) + len(SAFETY_FLAGS) + len(UNGOVERNED_FLAGS) == len(GLOBAL_OPTIONS)

    for flag, reason in UNGOVERNED_FLAGS.items():
        assert reason.strip(), (
            f"{flag} is classified ungoverned and carries no reason -- that is *inert by "
            "omission*, which is the state this partition exists to make unrepresentable"
        )
        assert len(reason.strip()) > 20, (
            f"{flag}'s reason is a placeholder, not a reason: {reason!r}"
        )


def test_the_partition_control_can_fail_on_all_three_arms() -> None:
    """AC5's own red proof, driven on synthetic data so no real declaration is
    vandalised to prove the control fires (the `tests/test_acceptance_audit.py`
    discipline). The three arms are the three ways a partition breaks."""

    def problems(
        block: tuple[str, ...],
        output: tuple[str, ...],
        safety: tuple[str, ...],
        ungoverned: Mapping[str, str],
    ) -> list[str]:
        found = []
        classes = (set(output), set(safety), set(ungoverned))
        if set(output) & set(safety) or set(output) & set(ungoverned):
            found.append("not disjoint")
        if set(safety) & set(ungoverned):
            found.append("not disjoint")
        if set.union(*classes) != set(block):
            found.append("not total")
        if any(not reason.strip() for reason in ungoverned.values()):
            found.append("blank reason")
        return found

    good = problems(("--a", "--b", "--c"), ("--a",), ("--b",), {"--c": "because"})
    assert good == []
    # (a) a flag in the block and in no class
    assert problems(("--a", "--b", "--c", "--d"), ("--a",), ("--b",), {"--c": "because"}) != []
    # (b) one flag named in two classes
    assert problems(("--a", "--b", "--c"), ("--a", "--b"), ("--b",), {"--c": "because"}) != []
    # (c) a blank reason
    assert problems(("--a", "--b", "--c"), ("--a",), ("--b",), {"--c": "  "}) != []


def test_the_or3_output_flags_are_byte_unchanged() -> None:
    """AC7 / D10 -- the three properties this spec must NOT move. `OUTPUT_FLAGS`
    keeps the same four members in the same order: `test_c14_output_flag_matrix`
    and the `54500b06e5` regression cells read it, and reordering it perturbs
    the OR-3 message the `54500b06e5` cells assert verbatim."""
    assert OUTPUT_FLAGS == ("--output", "--out-dir", "--name", "--in-place")
    assert SAFETY_FLAGS == ("--force", "--yes")


def test_every_leaf_verb_declares_its_output_flag_consumption_exactly_once() -> None:
    """AC17 -- the VERB axis of the same by-construction property AC5 gives the
    FLAG axis: a verb cannot be registered without declaring.

    `consumed_output_flags()` returns `()` for an undecorated module too, so
    membership in the declaration registry is what distinguishes *declared
    nothing* from *never declared* -- the distinction a `consumes == ()` check
    structurally cannot make, and the one B-115's population depends on.
    """
    from pdf_toolkit.cli import common as cli_common

    verbs = discover_verbs()
    group = typer_root_command()
    modules = {}
    _collect_leaf_modules(group, (), modules)

    assert len(verbs) == len(modules), (
        f"{len(verbs)} leaf verbs but {len(modules)} resolvable callback modules"
    )
    undeclared = sorted(
        name for name, module in modules.items() if module not in cli_common._CONSUMES_BY_MODULE
    )
    assert undeclared == [], (
        f"leaf verb(s) {undeclared} have no @global_options(consumes=...) declaration -- "
        "OR-3 would never check them and every global output flag would be silently inert"
    )
    # One declaration per verb, and no orphan declarations left behind.
    assert len(set(modules.values())) == len(modules), "two leaf verbs share one callback module"
    assert len(cli_common._CONSUMES_BY_MODULE) == len(verbs), (
        f"{len(cli_common._CONSUMES_BY_MODULE)} declarations for {len(verbs)} leaf verbs"
    )


def typer_root_command() -> object:
    import typer

    from pdf_toolkit.cli.main import app

    return typer.main.get_command(app)


def _collect_leaf_modules(cmd: object, path: tuple[str, ...], out: dict[str, str]) -> None:
    commands = getattr(cmd, "commands", None)
    if commands is not None:
        for name in sorted(commands):
            _collect_leaf_modules(commands[name], (*path, name), out)
        return
    module = _module_dotted_name(cmd)
    assert module is not None, f"leaf verb {' '.join(path)} has no resolvable callback module"
    out[" ".join(path)] = module


# --------------------------------------------------------------------------- #
# B-115 / `996f9eb6bc` -- `--force` and `--yes` on a verb that writes nothing.
#
# The population is DERIVED FROM THE LIVE REGISTRY inside every test below,
# never hand-listed: a sixth `consumes == ()` verb joins the grid with zero
# author action. That is the whole point of the fix.
# --------------------------------------------------------------------------- #


def non_consuming_verbs() -> tuple[str, ...]:
    return tuple(sorted(verb.name for verb in discover_verbs() if verb.consumes == ()))


#: A valid argv tail per non-consuming verb, so the refusal is measured against
#: an otherwise-well-formed invocation rather than against a parse error. The
#: three path verbs get a REAL fixture -- `PDF-25` owns the empty-stdout answer
#: a non-existent path produces under `-o json`, and borrowing it here would
#: measure that defect instead of this one.
def _non_consuming_argv(verb: str, fixture: Path) -> list[str]:
    return [] if verb in {"version", "doctor"} else [str(fixture)]


@pytest.fixture(scope="module")
def spine_fixture(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One real single-page PDF, built by the corpus builders, copied per use."""
    from corpus import build_corpus

    return build_corpus(tmp_path_factory.mktemp("pdf24")).path("single_page")


def test_the_non_consuming_population_is_derived_and_non_empty() -> None:
    """The precondition for every grid below. A population that silently went
    empty would make the whole B-115 section pass by iterating nothing."""
    population = non_consuming_verbs()
    assert population == ("doctor", "info", "meta get", "permissions", "version")
    assert len(population) == 5
    for verb in population:
        assert verb in {v.name for v in discover_verbs()}


@pytest.mark.e2e
def test_ac8_safety_flags_are_refused_on_every_verb_that_writes_nothing(
    spine_fixture: Path, tmp_path: Path
) -> None:
    """AC8 / B-115. Exit 2, structured envelope on STDOUT under `-o json`, the
    message naming the verb and the flag's LONG spelling -- for both spellings
    of both flags, on every `consumes == ()` verb the live registry reports.

    Pinned explicitly because it is an intended change to an observable answer:
    `permissions <missing.pdf> --force` moves **4 -> 2**, matching what
    `permissions <missing.pdf> -O x` already returns.
    """
    source = tmp_path / "spine.pdf"
    source.write_bytes(spine_fixture.read_bytes())

    cells = 0
    for verb in non_consuming_verbs():
        argv = _non_consuming_argv(verb, source)
        for short, long in (("-f", "--force"), ("-y", "--yes")):
            for spelling in (short, long):
                result = registry_run_cli(verb, *argv, spelling, "-o", "json")
                cells += 1
                assert result.returncode == 2, (
                    f"{verb} {spelling} -> {result.returncode}\n{result.stdout}{result.stderr}"
                )
                payload = json.loads(result.stdout)
                assert payload["schema_version"] == SCHEMA_VERSION
                assert payload["error"]["code"] == 2
                assert payload["error"]["kind"] == "usage"
                message = payload["error"]["message"]
                assert message == f"{verb} does not accept {long} (this verb writes no files)", (
                    f"{verb} {spelling}: {message!r}"
                )
    assert cells == 20, f"the grid measured {cells} cells, not 5 verbs x 4 spellings"


@pytest.mark.e2e
def test_ac8_a_missing_input_no_longer_outranks_the_safety_refusal() -> None:
    """The one precedence consequence pinned deliberately rather than discovered
    in a diff. Measured at `8fd2146`: `permissions /no/such.pdf --force` was
    **4**; it is **2** now, which is the same answer
    `permissions /no/such.pdf -O x` already gave, so no NEW precedence class is
    introduced -- two flags joined a relation the product already ships."""
    refused = registry_run_cli("permissions", "/no/such.pdf", "--force", "-o", "json")
    assert refused.returncode == 2
    already = registry_run_cli("permissions", "/no/such.pdf", "-O", "x.pdf", "-o", "json")
    assert already.returncode == 2
    # ...and the missing-input tier is still reachable when no flag pre-empts it.
    plain = registry_run_cli("permissions", "/no/such.pdf", "-o", "json")
    assert plain.returncode == 4


@pytest.mark.e2e
def test_ac9_dry_and_real_agree_as_pairs_including_a_discriminating_row(
    spine_fixture: Path, tmp_path: Path
) -> None:
    """AC9 / OR-7, measured as PAIRS and not as two independent tables.

    A dry/real matrix showing the same number everywhere is equally consistent
    with a preview that has gone silent, so the matrix carries a DISCRIMINATING
    row where a different tier answers: `merge a.pdf b.pdf -O out.pdf --force`
    is `0 == 0` while `version --force` is `2 == 2`. Per X-185, `dry == real`
    means the exit code AND the `-o json` envelope shape, so both are compared.
    """
    source = tmp_path / "spine.pdf"
    source.write_bytes(spine_fixture.read_bytes())

    def envelope_shape(text: str) -> object:
        payload = json.loads(text)
        if "error" in payload:
            return ("error", sorted(payload["error"]), payload["error"]["code"])
        return ("result", sorted(payload))

    for verb in non_consuming_verbs():
        argv = _non_consuming_argv(verb, source)
        for spelling in ("-f", "--force", "-y", "--yes"):
            real = registry_run_cli(verb, *argv, spelling, "-o", "json")
            dry = registry_run_cli(verb, *argv, spelling, "--dry-run", "-o", "json")
            assert dry.returncode == real.returncode == 2, (
                f"{verb} {spelling}: dry={dry.returncode} real={real.returncode}"
            )
            assert envelope_shape(dry.stdout) == envelope_shape(real.stdout)

    # The discriminating row: a verb that DOES consume `--force` answers 0 == 0
    # through a different tier, so the grid above cannot be a silent preview.
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_bytes(spine_fixture.read_bytes())
    b.write_bytes(spine_fixture.read_bytes())
    target = tmp_path / "merged.pdf"
    real = registry_run_cli(
        "merge", str(a), str(b), "-O", str(target), "--force", "-o", "json", cwd=tmp_path
    )
    target.unlink(missing_ok=True)
    dry = registry_run_cli(
        "merge",
        str(a),
        str(b),
        "-O",
        str(target),
        "--force",
        "--dry-run",
        "-o",
        "json",
        cwd=tmp_path,
    )
    assert dry.returncode == real.returncode == 0, (
        f"discriminating row: dry={dry.returncode} real={real.returncode}\n{real.stderr}"
    )
    assert envelope_shape(dry.stdout) == envelope_shape(real.stdout)


@pytest.mark.e2e
def test_ac10_a_non_consuming_verb_creates_no_file_and_leaves_its_input_intact(
    spine_fixture: Path, tmp_path: Path
) -> None:
    """AC10 -- the premise the refusal message ASSERTS, pinned behaviourally and
    **by a different consumer than the one that computes it**.

    `consumes == () ⟹ writes no files` is load-bearing for both the refusal and
    the disclosure, and until now only the message asserted it.

    The obvious static oracle DOES NOT WORK and is deliberately not used:
    `registry.is_mutating` is transitive import-reachability to `AtomicWriter`,
    and `permissions` is pinned `is_mutating=True` while declaring `consumes=()`
    (`tests/unit/test_registry.py`) because it shares `ops/crypto.py` with the
    producing crypto verbs. A control asserting `consumes == () ⟹ not
    is_mutating` would go red on a correctly-classified verb.
    """
    for verb in non_consuming_verbs():
        scratch = tmp_path / verb.replace(" ", "_")
        scratch.mkdir()
        source = scratch / "input.pdf"
        source.write_bytes(spine_fixture.read_bytes())
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        argv = _non_consuming_argv(verb, source)

        result = registry_run_cli(verb, *argv, "-o", "json", cwd=scratch)
        assert result.returncode == 0, f"{verb} -> {result.returncode}\n{result.stderr}"

        after = sorted(p.name for p in scratch.iterdir())
        assert after == ["input.pdf"], f"{verb} wrote {set(after) - {'input.pdf'}} into {scratch}"
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before, (
            f"{verb} mutated its own input"
        )


@pytest.mark.e2e
def test_ac11_the_output_flag_refusal_and_no_backup_have_not_regressed(
    spine_fixture: Path, tmp_path: Path
) -> None:
    """AC11 -- `54500b06e5` has not regressed and `--no-backup` has NOT been
    silently reclassified into `SAFETY_FLAGS`.

    `--no-backup` is refused on these verbs too, but for the UNIVERSAL
    `--no-backup requires --in-place` reason that applies identically to all 26
    -- which is exactly why it sits in `UNGOVERNED_FLAGS` with that reason
    recorded, and why it is not named in the disclosure sentence.
    """
    source = tmp_path / "spine.pdf"
    source.write_bytes(spine_fixture.read_bytes())

    for verb in non_consuming_verbs():
        argv = _non_consuming_argv(verb, source)
        result = registry_run_cli(verb, *argv, "-O", "out.pdf", "-o", "json")
        assert result.returncode == 2
        message = json.loads(result.stdout)["error"]["message"]
        assert message == f"{verb} does not accept --output (this verb writes no files)", message

        backup = registry_run_cli(verb, *argv, "--no-backup", "-o", "json")
        assert backup.returncode == 2
        backup_message = json.loads(backup.stdout)["error"]["message"]
        assert "--no-backup requires --in-place" in backup_message, backup_message
        assert verb not in backup_message, (
            "--no-backup's message is UNIVERSAL, not verb-specific -- a verb name in it "
            "would mean it had been reclassified into SAFETY_FLAGS"
        )
    assert "--no-backup" in UNGOVERNED_FLAGS
    assert "--no-backup" not in set(SAFETY_FLAGS) | set(OUTPUT_FLAGS)


# --------------------------------------------------------------------------- #
# Renderers — public API
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
def test_json_output_is_one_object_carrying_the_schema_version() -> None:
    result = run_cli("version", "-o", "json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == SCHEMA_VERSION == 1
    assert payload["verb"] == "version"
    assert payload["items"]


@pytest.mark.e2e
def test_ndjson_output_is_one_self_describing_object_per_line() -> None:
    result = run_cli("version", "-o", "ndjson")
    assert result.returncode == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) > 1
    for line in lines:
        record = json.loads(line)
        assert record["schema_version"] == SCHEMA_VERSION
        assert record["verb"] == "version"


@pytest.mark.e2e
def test_table_output_is_a_human_table_on_stdout() -> None:
    result = run_cli("version", "-o", "table")
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert lines[0].startswith("input")
    assert set(lines[1].replace(" ", "")) == {"-"}
    assert any("pdf-toolkit" in line for line in lines)


@pytest.mark.e2e
def test_output_format_auto_detects_a_non_tty_and_an_explicit_override_wins() -> None:
    piped = run_cli("version")
    assert piped.returncode == 0
    assert json.loads(piped.stdout)["verb"] == "version"

    overridden = run_cli("version", "-o", "table")
    assert overridden.returncode == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(overridden.stdout)


def test_table_errors_go_to_stderr_and_leave_stdout_empty(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_error(errors.RefusedError("target exists", path="out.pdf"), OutputFormat.TABLE)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == ["error: target exists (out.pdf)"]


def test_json_errors_go_to_stdout_in_the_published_shape(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_error(errors.AuthError("password required", path="locked.pdf"), OutputFormat.JSON)
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload == {
        "schema_version": 1,
        "error": {
            "code": 6,
            "kind": "auth",
            "message": "password required",
            "path": "locked.pdf",
        },
    }


@pytest.mark.e2e
def test_an_error_reaches_the_single_handler_end_to_end() -> None:
    table = run_cli("-o", "table", "--password-file", "/no/such/file", "version")
    assert table.returncode == 2
    assert table.stdout == ""
    assert table.stderr.startswith("error: ")

    structured = run_cli("-o", "json", "--password-file", "/no/such/file", "version")
    assert structured.returncode == 2
    payload = json.loads(structured.stdout)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["error"]["code"] == 2
    assert payload["error"]["kind"] == "usage"
    # B-068: `--password-file` is a never-echo flag (like every flag in
    # `PASSWORD_FILE_FLAGS`) -- the given value must never appear in the
    # envelope, so `path` is `None` here rather than the literal argument.
    # `tests/test_password_leaks.py`'s B-068 section is the adversarial
    # proof; this assertion is this file's own pin of the same contract.
    assert payload["error"]["path"] is None
    assert "/no/such/file" not in structured.stdout


def test_renderers_consume_only_to_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    original = OperationResult.to_dict

    def patched(self: OperationResult) -> dict[str, object]:
        payload = original(self)
        payload["smuggled"] = "yes"
        return payload

    monkeypatch.setattr(OperationResult, "to_dict", patched)
    payload = json.loads(render_payload(sample_result().to_dict(), OutputFormat.JSON))
    assert payload["smuggled"] == "yes"


def test_warnings_go_to_stderr_and_never_pollute_the_payload(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_result(sample_result(), OutputFormat.JSON)
    captured = capsys.readouterr()
    assert json.loads(captured.out)["warnings"] == ["careful"]
    assert captured.err.strip() == "warning: careful"


def test_table_renderer_drops_columns_that_are_entirely_absent() -> None:
    rendered = render_payload(sample_result().to_dict(), OutputFormat.TABLE)
    header = rendered.splitlines()[0]
    assert "input" in header
    assert "ok" not in header.split(), "the ok column is folded into the exit code"


# --------------------------------------------------------------------------- #
# Startup budget and import hygiene
# --------------------------------------------------------------------------- #


ENGINE_MODULES = {"pypdf", "pikepdf", "pypdfium2", "reportlab", "pdfplumber", "fitz"}

#: The `--help` startup budget, `PLAN.md` §12 R-13, as a SINGLE NAMED CONSTANT.
#: Promoted from a local in `test_help_stays_within_the_startup_budget` by
#: PDF-05, which needed to assert against the budget rather than restate the
#: number: a second `250.0` written somewhere else is how two tests start
#: disagreeing about what the budget is. PDF-01 owns the measurement; this is
#: only its name.
#:
#: PDF-29 RE-BASELINED THIS FROM 250.0, AND THE EVIDENCE IS RIGHT HERE. The rule
#: applied is Design §6's, mechanically: measure first, then p95 < 225 ms leaves
#: the constant alone and p95 >= 225 ms re-baselines to p95 x 1.25 rounded up to
#: the next 25 ms. Nothing about the number was chosen; only the measurement was.
#:
#: ----------------------------- THE MEASUREMENT -----------------------------
#: STATISTIC:    fastest-of-5, 20 independent trials.  THE STATISTIC IS PART OF
#:               THE NUMBER. A *median under contention* and a *fastest-of-5 at
#:               low load* are different statistics of the same distribution and
#:               differ by tens of ms; quoting either as "headroom" without
#:               naming which one is how this row's own ledger came to hold two
#:               irreconcilable headroom figures (4.7 ms and ~29 ms).
#: DATE:         2026-09-03
#: COMMIT:       0665e64bc88d58b77993521ab3de528b99988959 (tree carrying only
#:               PDF-29's own scripts/measure_gate.py at measurement time)
#: HOST:         Linux-7.0.0-30-generic x86_64, 8 cpus; loadavg 1.15 at start /
#:               1.31 peak; ZERO foreign processes at or above 25% cpu for the
#:               whole run -- i.e. `quiet: true` by perf/README.md's definition
#: INTERPRETER:  CPython 3.12.13, resolved through `uv run python` into this
#:               repository's own `.venv` (never the system `python3`, which
#:               reports 3.14.4 on this host)
#: ENGINES:      tesseract AND soffice both present on PATH
#: BINARY:       .venv/bin/pdftoolkit, `venv-sibling` arm (asserted, not assumed)
#: DISTRIBUTION: min 219.712 / median 235.791 / p95 247.901 / max 247.990 ms,
#:               SPREAD 28.278 ms
#:
#: WHAT THAT DISTRIBUTION MEANS. Against the old 250.0 budget the p95 left
#: **2.1 ms of headroom against a 28.3 ms spread, on a host verified quiet**.
#: A best-of-5 estimator whose dispersion is thirteen times its headroom flakes
#: BY CONSTRUCTION -- on a quiet host as much as a loaded one -- which is
#: exactly what the ledger recorded happening to three different agents in one
#: day, and what reddened `test (3.12, macos-14)` in run 33721445070 at
#: "fastest --help was 308 ms of 250.0 ms". The old number was not defended by
#: this measurement; it was refuted by it.
#:
#: 247.901 x 1.25 = 309.876 -> rounded up to the next 25 ms = 325.0.
#:
#: AND THE RISK THIS CARRIES, STATED. Widening a budget can silence a genuine
#: startup regression, and the three medians on record (224.7 -> 242.7 -> 243.2)
#: DO trend upward across the same instrument while verbs were added. That risk
#: is the reason this block exists rather than a round number, and the reason
#: PDF-29 also landed a control that CANNOT be widened away: Section 6 of
#: tests/test_import_boundaries.py pins WHAT `--help` imports, which is
#: deterministic, load-immune and parallel-safe. A new eager import of a heavy
#: module reddens there whatever this number says.
STARTUP_BUDGET_MS = 325.0

#: The venv console script, as a path rather than a fallback chain. C-4: the
#: three-arm `console_script()` below can resolve a globally installed (possibly
#: STALE) `pdftoolkit` from PATH, or the `-m` bootstrap, and until PDF-29
#: nothing asserted which arm a startup measurement had actually used.
VENV_CONSOLE_SCRIPT = REPO_ROOT / ".venv" / "bin" / "pdftoolkit"

#: `quiet` == loadavg(1m) <= this fraction of the cpu count. The same definition
#: perf/README.md states and scripts/measure_gate.py enforces, so the test and
#: the protocol cannot drift into disagreeing about what "quiet" means.
QUIET_LOAD_FRACTION = 0.25


def test_no_engine_library_is_imported_at_module_scope() -> None:
    probe = (
        "import sys, pdf_toolkit.cli.main;"
        f"leaked = {ENGINE_MODULES!r} & set(sys.modules);"
        "print(sorted(leaked));"
        "sys.exit(1 if leaked else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False, cwd=REPO_ROOT
    )
    assert result.returncode == 0, f"engines imported at module scope: {result.stdout.strip()}"


def startup_gate_abstention_reason() -> str | None:
    """Why a wall-clock startup measurement is not admissible here, or None.

    THE PROBLEM THIS SOLVES, NAMED. A wall-clock assertion used as a
    CORRECTNESS gate on a shared box goes red for reasons unrelated to the code,
    and `B-098` states the cost exactly: *a control that goes red without a
    defect costs more than one that stays green, because a phantom red gets
    chased into a spec.* So this control abstains, with the observed load in the
    reason, rather than failing -- the product's own house idiom (`PLAN.md`
    §10.1 rule 5: absent precondition, skip with a reason, never pass) applied
    to timing for the first time.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker:
        count = os.environ.get("PYTEST_XDIST_WORKER_COUNT", "?")
        return (
            f"parallel session: this is xdist worker {worker} of {count}. A WALL-CLOCK "
            "assertion cannot live in a parallel suite -- under `-n auto` the box is "
            "saturated by our own workers by construction, so any number measured here "
            "is about the scheduler, not about the product. This is not a tuning "
            "problem, it is a contradiction. Re-measure with "
            "`uv run python scripts/measure_gate.py --target help-startup --baseline`, "
            "which refuses on a host it cannot verify quiet."
        )
    loadavg = os.getloadavg()[0]
    cpu_count = os.cpu_count() or 1
    ceiling = QUIET_LOAD_FRACTION * cpu_count
    if loadavg > ceiling:
        return (
            f"host not quiet: loadavg(1m) {loadavg:.2f} against the {ceiling:.2f} ceiling "
            f"({cpu_count} cpus). Measured at {loadavg:.2f}, this gate's spread exceeds "
            "its headroom and it would report contention as a product regression."
        )
    return None


@pytest.mark.e2e
def test_help_stays_within_the_startup_budget() -> None:
    """R-13's wall-clock claim -- an OBSERVATION that abstains, not a CI gate.

    READ THIS BEFORE TREATING A GREEN HERE AS EVIDENCE. Under `-n auto` (this
    project's default since PDF-29) this test SKIPS on every worker, so it does
    not run in CI at all, and saying so plainly is the point: a control that can
    silently stop running is the exact class this cycle exists to end. What
    replaced it in CI is **Section 6 of tests/test_import_boundaries.py**, which
    pins the import set behind `--help`. Import set is deterministic,
    load-immune and parallel-safe; wall-clock is none of those. The number is
    re-measured deliberately, on a verified-quiet host, by
    `scripts/measure_gate.py --target help-startup --baseline` (`make
    gate-timing`), and the distribution is recorded beside STARTUP_BUDGET_MS.
    """
    import time

    reason = startup_gate_abstention_reason()
    if reason is not None:
        pytest.skip(reason)

    # C-4, both directions. Measure the project venv's console script BY PATH,
    # and assert that is also the arm `console_script()` would have chosen -- so
    # a stale `make install` build on PATH can neither be measured here nor go
    # unnoticed.
    if not VENV_CONSOLE_SCRIPT.exists():
        pytest.skip(
            f"no console script at {VENV_CONSOLE_SCRIPT}; the remaining arms are a "
            f"possibly STALE PATH install ({shutil.which('pdftoolkit')}) and the `-m` "
            "bootstrap, whose startup path differs measurably. Run `uv sync`."
        )
    chosen = console_script()
    assert chosen == [str(VENV_CONSOLE_SCRIPT)], (
        f"console_script() resolved {chosen!r}, not the project venv's own "
        f"{str(VENV_CONSOLE_SCRIPT)!r}. A startup number from a different binary is a "
        "number about a different build -- `make install` leaves a global `pdftoolkit` "
        "on PATH that may be stale, and the `-m` arm bootstraps differently."
    )

    # R-13 is a claim about the product's real startup latency, not about how
    # this suite happens to be instrumented. Under `make cover`,
    # [tool.coverage.run]'s `patch = ["subprocess"]` (PDF-06 fix-forward) makes
    # every child process measured, and coverage.py's own tracer overhead
    # (worse still under `branch = true`) is real and unrelated to the
    # product's own startup path -- an uninstrumented child is what "fastest
    # --help" is actually supposed to measure, in every mode `make cover`
    # included. `COVERAGE_PROCESS_START`/`COVERAGE_PROCESS_CONFIG` are the two
    # env vars `a1_coverage.pth` checks (see coverage 7.16.0's own hook) to
    # decide whether to auto-start tracing in a fresh interpreter, so scrubbing
    # them from this one child's environment is enough to opt it out without
    # touching any other subprocess call site's default full-inheritance.
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("COVERAGE_PROCESS_START", "COVERAGE_PROCESS_CONFIG")
    }

    budget_ms = STARTUP_BUDGET_MS
    timings: list[float] = []
    for _ in range(5):
        started = time.perf_counter()
        result = run_cli("--help", env=env)
        timings.append((time.perf_counter() - started) * 1000)
        assert result.returncode == 0
    # Best-of-N rather than the mean, so scheduler noise cannot flake the gate
    # while a genuine regression still turns it red. PDF-29 measured what that
    # actually buys: over 20 such trials on a verified-quiet host the p95 was
    # 247.9 ms with a 28.3 ms spread, so at the old 250.0 budget it bought
    # 2.1 ms. See STARTUP_BUDGET_MS's block for the full distribution.
    assert min(timings) < budget_ms, (
        f"fastest --help was {min(timings):.0f} ms of {budget_ms} ms "
        f"(all five: {[round(value) for value in timings]}), measured on "
        f"{VENV_CONSOLE_SCRIPT} at loadavg {os.getloadavg()[0]:.2f}"
    )


def test_no_module_under_src_imports_rich() -> None:
    offenders = [
        path
        for path in (REPO_ROOT / "src").rglob("*.py")
        if re.search(r"^\s*(import rich|from rich)", path.read_text(), re.MULTILINE)
    ]
    assert offenders == [], "the table renderer is hand-rolled on purpose"


# --------------------------------------------------------------------------- #
# Packaging and the frozen dependency set
# --------------------------------------------------------------------------- #


def load_pyproject() -> dict[str, object]:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())


def test_declared_runtime_dependencies_are_the_frozen_set() -> None:
    project = load_pyproject()["project"]
    assert isinstance(project, dict)
    declared = {
        re.split(r"[\[><=!~;]", entry, maxsplit=1)[0].strip() for entry in project["dependencies"]
    }
    assert declared == CORE_DEPENDENCIES


def test_weasyprint_is_an_optional_extra_and_never_a_core_dependency() -> None:
    project = load_pyproject()["project"]
    assert isinstance(project, dict)
    assert not any("weasyprint" in entry for entry in project["dependencies"])
    extras = project["optional-dependencies"]
    assert isinstance(extras, dict)
    assert any("weasyprint" in entry for entry in extras["html"])


def test_packaging_declares_the_license_and_its_license_files() -> None:
    # THIRD_PARTY_LICENSES joined this list in PDF-02: PLAN §11 requires it inside
    # BOTH the sdist and the wheel, and PEP 639's license-files is the mechanism
    # that puts it there. PDF-01 could not list it — the file is generated by
    # `make licenses`, which PDF-02 wired up. scripts/assert_artifacts.py is the
    # assertion that it actually lands in both archives.
    project = load_pyproject()["project"]
    assert isinstance(project, dict)
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE", "NOTICE", "THIRD_PARTY_LICENSES"]
    assert (REPO_ROOT / "LICENSE").read_text().count("Apache License") >= 1
    assert (REPO_ROOT / "NOTICE").exists()
    assert (REPO_ROOT / "THIRD_PARTY_LICENSES").exists()


def test_both_console_scripts_point_at_the_same_entry_point() -> None:
    project = load_pyproject()["project"]
    assert isinstance(project, dict)
    scripts = project["scripts"]
    assert isinstance(scripts, dict)
    assert scripts["pdftoolkit"] == scripts["pdf-toolkit"] == "pdf_toolkit.cli.main:main"


def hc1_haystacks() -> list[Path]:
    """The textual tier's population: packaging, the build, and every source file.

    The Makefile is in here because the realistic HC-1 violation is a
    convenience shell-out, not a declared dependency.
    """
    haystacks = [REPO_ROOT / "pyproject.toml", REPO_ROOT / "Makefile"]
    haystacks.extend(sorted((REPO_ROOT / "src").rglob("*.py")))
    return haystacks


def forbidden_name_findings(
    text: str,
    *,
    relpath: str,
    names: tuple[str, ...] = SHARED_FORBIDDEN_NAMES,
    exemptions: Mapping[tuple[str, str], str] = TEXTUAL_EXEMPTIONS,
) -> list[str]:
    """One file's textual-tier findings, `name` by `name`.

    Parameterized on the data rather than reading module globals, so the red
    proofs below drive it with synthetic input instead of vandalising the real
    tree -- the discipline `tests/test_acceptance_audit.py` already uses.
    """
    lowered = text.lower()
    findings: list[str] = []
    for name in names:
        if (relpath, name) in exemptions:
            continue
        if name in WORD_BOUNDARY_NAMES:
            hit = re.search(rf"\b{re.escape(name)}\b", lowered) is not None
        else:
            hit = name in lowered
        if hit:
            findings.append(f"{relpath}: {name}")
    return findings


def names_silenced_everywhere(
    exemptions: Mapping[tuple[str, str], str],
    relpaths: tuple[str, ...],
    names: tuple[str, ...] = SHARED_FORBIDDEN_NAMES,
) -> list[str]:
    """Names whose every haystack is exempted -- i.e. silenced outright.

    AC20's teeth. A per-`(file, name)` exemption is a false-positive story; an
    exemption that reaches every file is a deleted name wearing one.
    """
    silenced = []
    for name in names:
        exempted = {path for (path, exempt_name) in exemptions if exempt_name == name}
        if relpaths and all(path in exempted for path in relpaths):
            silenced.append(name)
    return silenced


def test_no_forbidden_engine_name_appears_in_packaging_source_or_build() -> None:
    offenders: list[str] = []
    for path in hc1_haystacks():
        rel = path.relative_to(REPO_ROOT).as_posix()
        offenders.extend(forbidden_name_findings(path.read_text(), relpath=rel))
    assert offenders == [], "PLAN §7.2 forbidden names found by the textual tier:\n" + "\n".join(
        offenders
    )


def test_the_textual_tier_reads_the_shared_list_and_never_a_second_one() -> None:
    """AC18. `FORBIDDEN_NAMES` used to be twelve hand-typed names against the AST
    tier's twenty-three, with nothing asserting the two related. It is derived
    now, so adding a name to `PLAN_FORBIDDEN` reaches BOTH tiers with no edit
    here."""
    assert set(SHARED_FORBIDDEN_NAMES) == set(PLAN_FORBIDDEN) | set(EXTRA_FORBIDDEN)
    assert len(SHARED_FORBIDDEN_NAMES) == len(set(PLAN_FORBIDDEN) | set(EXTRA_FORBIDDEN))
    # Nothing is dropped on the way to the two matchers.
    assert set(FORBIDDEN_NAMES) | set(WORD_BOUNDARY_NAMES) == set(SHARED_FORBIDDEN_NAMES)
    assert set(FORBIDDEN_NAMES) & set(WORD_BOUNDARY_NAMES) == set()
    # Non-vacuity: the tier is not scanning an empty roster over an empty tree.
    assert len(SHARED_FORBIDDEN_NAMES) >= 20
    assert len(hc1_haystacks()) >= 40


def test_the_textual_tier_still_catches_a_plain_substring_name() -> None:
    """The positive control for the 22 substring names, on synthetic input."""
    planted = 'subprocess.run(["pdf' + 'totext", path])'
    assert forbidden_name_findings(planted, relpath="src/x.py") == ["src/x.py: pdftotext"]
    docstring = "This module is not " + "pdftk" + " and shares no code with it."
    assert forbidden_name_findings(docstring, relpath="src/y.py") == ["src/y.py: pdftk"]


def test_the_gs_decision_matches_a_leak_and_not_an_identifier() -> None:
    """AC21 -- the `gs` decision, mechanized in both directions.

    The reason lives beside the list in `WORD_BOUNDARY_NAMES`; this is the
    proof that the reason is true.
    """
    assert "gs" in PLAN_FORBIDDEN, "the AST tier's own list must still carry it"
    assert WORD_BOUNDARY_NAMES["gs"].strip(), "the decision must carry its reason as data"

    for leak in (
        'subprocess.run(["gs", "-q", "-sDEVICE=pdfwrite"])',
        "\tgs -sDEVICE=pdfwrite -o out.pdf in.pdf",
        'shutil.which("/usr/bin/gs")',
    ):
        assert forbidden_name_findings(leak, relpath="src/x.py") == ["src/x.py: gs"], leak

    identifiers = "flags args warnings settings strings kwargs output_flags belongs alongside"
    assert forbidden_name_findings(identifiers, relpath="src/x.py") == []


def test_a_blanket_word_boundary_rewrite_would_be_a_weakening_not_a_tightening() -> None:
    """Why `WORD_BOUNDARY_NAMES` is scoped PER NAME and holds exactly one entry.

    `_` is a word character, so `\\bpdftk\\b` does not match `use_pdftk_fallback`.
    A blanket rewrite would silently disarm every name against underscore-
    embedded identifiers -- the disarm shape X-255 forbids, arriving as a
    tidy-up.
    """
    embedded = "def use_pdftk_fallback(path):\n    return None\n"
    assert forbidden_name_findings(embedded, relpath="src/x.py") == ["src/x.py: pdftk"]
    assert re.search(r"\bpdftk\b", embedded) is None
    assert set(WORD_BOUNDARY_NAMES) == {"gs"}


def test_an_exemption_suppresses_exactly_one_file_and_one_name() -> None:
    """AC20 -- the mechanism, proven on synthetic input rather than by adding a
    live exemption to make something pass."""
    text = "This module is not " + "pdftk" + " and does not shell out to pdf" + "totext."
    assert sorted(forbidden_name_findings(text, relpath="src/a.py")) == [
        "src/a.py: pdftk",
        "src/a.py: pdftotext",
    ]
    scoped = MappingProxyType({("src/a.py", "pdftk"): "cites PLAN.md §7.2 in a docstring"})
    assert forbidden_name_findings(text, relpath="src/a.py", exemptions=scoped) == [
        "src/a.py: pdftotext"
    ]
    # The SAME exemption does not reach a different file.
    assert sorted(forbidden_name_findings(text, relpath="src/b.py", exemptions=scoped)) == [
        "src/b.py: pdftk",
        "src/b.py: pdftotext",
    ]


def test_an_exemption_cannot_silence_a_whole_name() -> None:
    """AC20's teeth: every name in the shared list is still matched somewhere the
    exemption does not reach. *Observed red by:* exempting `pdftk` for every
    haystack rather than for one file."""
    relpaths = tuple(p.relative_to(REPO_ROOT).as_posix() for p in hc1_haystacks())
    assert names_silenced_everywhere(TEXTUAL_EXEMPTIONS, relpaths) == []

    global_exemption = MappingProxyType({(path, "pdftk"): "because" for path in relpaths})
    assert names_silenced_everywhere(global_exemption, relpaths) == ["pdftk"]


def test_every_live_exemption_names_a_real_file_a_real_name_and_a_reason() -> None:
    """A stale exemption is a silencer waiting for its file to change. Empty at
    `8fd2146`; the loop is the forward constraint, and its own emptiness is
    stated rather than left to be inferred."""
    relpaths = {p.relative_to(REPO_ROOT).as_posix() for p in hc1_haystacks()}
    for (path, name), reason in TEXTUAL_EXEMPTIONS.items():
        assert path in relpaths, f"exemption names a file the tier does not scan: {path}"
        assert name in SHARED_FORBIDDEN_NAMES, f"exemption names an unknown forbidden name: {name}"
        assert reason.strip(), f"exemption ({path}, {name}) carries no reason"
    assert TEXTUAL_EXEMPTIONS == {}, (
        "the live exemption list is empty at this commit -- if that changes, this assertion "
        "is the place the change is argued, not the place it is hidden"
    )


# --------------------------------------------------------------------------- #
# Makefile, .gitignore and changelog hygiene
# --------------------------------------------------------------------------- #


def test_makefile_documents_exactly_the_expected_targets() -> None:
    text = (REPO_ROOT / "Makefile").read_text()
    documented = set(re.findall(r"^([a-zA-Z0-9_-]+):.*?## ", text, re.MULTILINE))
    assert documented == MAKEFILE_TARGETS


def test_no_makefile_recipe_degrades_silently() -> None:
    text = (REPO_ROOT / "Makefile").read_text()
    offenders = [
        line
        for line in text.splitlines()
        if re.search(r"\|\|\s*true", line) or line.startswith("\t-")
    ]
    assert offenders == [], "a gate that cannot fail is not a gate"


def test_gitignore_covers_scratch_but_not_the_generated_license_manifest() -> None:
    lines = (REPO_ROOT / ".gitignore").read_text().splitlines()
    assert lines.count(".scratch/") == 1
    assert not any("THIRD_PARTY_LICENSES" in line for line in lines)
    for cache in (".pytest_cache/", ".ruff_cache/", ".mypy_cache/", "htmlcov/", "*.egg-info/"):
        assert cache in lines


def test_changelog_prepends_every_spec_entry_below_the_anchor() -> None:
    """One entry per landed spec, newest first, directly below the anchor.

    PDF-01 asserted `len(headings) == 1`, which was true only while PDF-01 was
    the only landed spec: it would have failed on PDF-02 and on every spec after
    it. Generalized in PDF-02 to assert the INVARIANT the original was reaching
    for -- entries are PREPENDED, never appended -- which is strictly stronger,
    because it now also catches an out-of-order insert that the count never could.

    Generalized once more by PDF-04's X-67 fix-forward, for the same reason and
    in the same direction. "Spec numbers descend as you read down" was a PROXY
    for "prepended", sound only while no spec was ever remediated after a
    higher-numbered one landed. `changelog.md`'s own header rules that a
    correction is a NEW ENTRY WITH A NEW DATE, so a PDF-04 fix-forward landing
    after PDF-06 makes the sequence [4, 6, 6, 5, 4, 3, 2, 1] -- correctly
    newest-first, and correctly non-descending. Left as it was, the assertion
    would have forced a choice between an honest changelog and a green suite,
    which is how a guard starts getting worked around instead of trusted.

    The replacement is two checks that are together stronger, not weaker:

    * **dates are non-increasing** as you read down, which is what "newest
      first" literally claims and what the number check was only approximating;
    * **each spec's ORIGINAL landing entry still descends.** The original is the
      bottom-most entry carrying that number, remediations being prepended above
      it, so a genuinely misfiled entry -- PDF-07's first entry appended at the
      bottom, say -- still fails exactly as it did before.

    Generalized a THIRD time by PDF-08, for the third time in the same
    direction and for the same reason the docstring above already gives:
    "spec ORIGINALS descend" was itself a proxy, sound only while specs landed
    in ascending numeric order. This wave landed PDF-09 through PDF-13 BEFORE
    PDF-08, so PDF-08's original entry is correctly the newest and correctly
    sits at the top, and the old assertion would have forced exactly the choice
    the paragraph above refuses -- an honest changelog or a green suite.
    Landing order is a scheduling fact, not a changelog invariant, and this
    file's own header states the only ordering rule there is: newest first,
    inserted directly below the anchor.

    The catching power is preserved rather than dropped, by replacing the
    assumption with the invariant it was reaching for: **a spec's remediation
    entries are never dated before its own original landing entry.** PDF-07's
    first entry appended at the bottom still fails -- on the date check, which
    it violated all along.

    GENERALIZED A FOURTH TIME BY PDF-30, AND ONE ASSERTION DELETED OUTRIGHT
    ----------------------------------------------------------------------
    The remediation clause above was a **tautology** (B-080) and is deleted
    rather than repaired. Its entailment is recorded here so nobody re-derives
    it: `original_date[n]` was built top-down with overwrite, so it held the
    BOTTOM-most entry's date for `n`; the date list is asserted non-increasing
    top-to-bottom three lines earlier, so the bottom-most date for any `n` is
    the MINIMUM of that `n`'s dates; and `d < min(dates_for_n)` is
    unsatisfiable. It could never fire while the assertion above it held -- the
    PM's exhaustive result over 66,429 synthetic entry lists was **0** fires.
    It read as coverage and was not.

    Its *intent* -- remediations are prepended above the original -- now lives
    in `tests/test_changelog_history.py`, measured against **git** rather than
    against a date ordering that already implied it: every heading a commit adds
    must sit above every heading that existed at its parent.

    The population also widens. It was a `PDF-NN`-only heading regex, which
    matched 46 of the 65 `## ` headings at `7afdb1a` -- 17 `[B-NNN]` entries and
    the 2 `[Task: PDF-16 ...]` entries (B-107) sat outside every check here,
    the newest-first assertion included, and the `len(entries) == len(headings)`
    guard compared two PDF-only populations and was therefore self-consistent
    and blind. Parsing is now tolerant of both landed forms -- no entry is
    edited to fit a regex (`changelog.md:16`) -- and covers all 65.
    """
    text = (REPO_ROOT / "changelog.md").read_text()
    anchor = "<!-- CHANGELOG-ANCHOR: insert new entries directly below this line, newest first -->"
    assert anchor in text
    headings = re.findall(r"^## .*$", text, re.MULTILINE)
    assert headings, "changelog carries no entries at all"
    # Every entry lives below the anchor, and the newest one is immediately below it.
    assert text.index(anchor) < text.index(headings[0])
    # PDF-01's entry is never lost or edited — a lost prepend is exactly what
    # this file's own header warns a HEAD-level heading grep would hide.
    assert any(h.startswith("## [PDF-01] Project scaffold & CLI spine") for h in headings)

    # Tolerant on the way in: the canonical form AND the two frozen historical
    # `[Task: PDF-NN ...]` headings, so an id-keyed read finds PDF-16's two
    # entries without any landed entry being rewritten to suit this parser.
    canonical = re.compile(r"^## \[(PDF-\d\d|B-\d+)\] .+ \u2014 (\d{4}-\d{2}-\d{2})$")
    historical = re.compile(r"^## \[Task: (PDF-\d\d) \u2014 .+\] - (\d{4}-\d{2}-\d{2})$")
    entries: list[tuple[str, str]] = []
    unparsed: list[str] = []
    for heading in headings:
        match = canonical.match(heading) or historical.match(heading)
        if match is None:
            unparsed.append(heading)
        else:
            entries.append((match.group(1), match.group(2)))
    assert unparsed == [], (
        f"{len(unparsed)} heading(s) match neither the canonical form nor the two "
        f"frozen historical ones, so every check below would pass over them "
        f"silently: {unparsed}"
    )
    assert len(entries) == len(headings)

    # Newest first, literally: dates never increase as you read down. This now
    # covers the [B-NNN] and [Task: ...] entries it previously could not see.
    dates = [date for _, date in entries]
    assert dates == sorted(dates, reverse=True), f"entries are not newest-first: {dates}"


# --------------------------------------------------------------------------- #
# SafetyPolicy construction and the redaction mechanism
# --------------------------------------------------------------------------- #


def test_safety_policy_is_built_from_the_global_flags() -> None:
    config = build_config(default_flag_values(dry_run=True, force=True, in_place=True, threads=3))
    policy = config.safety
    assert policy.dry_run is True
    assert policy.force is True
    assert policy.in_place is True
    assert policy.backup is True
    assert policy.threads == 3
    assert set(policy.to_dict()) == {
        "dry_run",
        "force",
        "in_place",
        "backup",
        "assume_yes",
        "is_tty",
        "threads",
    }


def test_no_backup_is_the_inverse_of_the_backup_field() -> None:
    config = build_config(default_flag_values(in_place=True, no_backup=True))
    assert config.safety.backup is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"no_backup": True},
        {"quiet": True, "verbose": 1},
        {"output": Path("a.pdf"), "out_dir": Path("d")},
        {"threads": 0},
        {"name": "../escape.pdf"},
        {"name": ""},
        {"password_file": "/no/such/file"},
    ],
    ids=[
        "no-backup-alone",
        "quiet-and-verbose",
        "output-and-out-dir",
        "threads-zero",
        "name-escapes",
        "name-empty",
        "password-not-a-file",
    ],
)
def test_invalid_flag_combinations_are_usage_errors(overrides: dict[str, object]) -> None:
    with pytest.raises(errors.UsageError):
        validate_config(build_config(default_flag_values(**overrides)))


def test_a_password_file_may_be_stdin_or_an_existing_path(tmp_path: Path) -> None:
    validate_config(build_config(default_flag_values(password_file="-")))
    real = tmp_path / "secret.key"
    real.write_text("hunter2\n")
    validate_config(build_config(default_flag_values(password_file=str(real))))


def test_registered_secrets_are_scrubbed_from_every_log_record() -> None:
    import logging

    clear_secrets()
    try:
        register_secret("hunter2")
        record = logging.LogRecord(
            name="pdf_toolkit",
            level=logging.DEBUG,
            pathname=__file__,
            lineno=1,
            msg="opening with %s",
            args=("hunter2",),
            exc_info=None,
        )
        assert RedactingFilter().filter(record) is True
        assert "hunter2" not in record.getMessage()
        assert "<redacted>" in record.getMessage()
    finally:
        clear_secrets()
