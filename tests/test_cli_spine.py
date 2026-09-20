"""The CLI spine contract.

Everything asserted here is public API from v1.0.0 — the exit-code integers, the
structured output shapes, and which stream each of them goes to. A failure in
this file is not a defect in one verb; it is a defect in the contract every verb
inherits, so treat a red test here as a breaking change until proven otherwise.

Deliberately disjoint from the fixture-corpus and per-verb contract harness that
arrive later: this file owns the spine, and there is no ``conftest.py`` here yet.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

from pdf_tooling import errors
from pdf_tooling.cli import exit_codes
from pdf_tooling.cli.common import (
    GLOBAL_FLAG_SPELLINGS,
    GLOBAL_OPTIONS,
    GLOBAL_PARAMS,
    OUTPUT_FLAGS,
    REFUSED_PASSWORD_FLAGS,
    SAFETY_FLAGS,
    UNGOVERNED_FLAGS,
    build_config,
    validate_config,
)
from pdf_tooling.models import SCHEMA_VERSION, ItemResult, OperationResult
from pdf_tooling.output import OutputFormat, emit_error, emit_result, render_payload
from pdf_tooling.output.logging import RedactingFilter, clear_secrets, register_secret

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
    # PDF-82: `engines-gate` arm 2 alone, runnable on every host because the
    # without-engines configuration needs the engines HIDDEN rather than
    # installed. It is what the manifest's `without-engines` entries point at,
    # and it joins `ci`'s prerequisite list no more than the three above do.
    "engines-hidden",
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
    # PDF-91: the website contract gate. Deliberately NOT in `ci`'s
    # prerequisite list -- `make ci` is uv-only by design and a Node toolchain
    # must not become a prerequisite of the Python gate. It IS a CI job
    # (`.github/gate-parity.toml`'s `website` entry, `in_make_ci = false`).
    "website",
    # PDF-46: the standing-residue reaper. Lists by default, removes only under
    # CONFIRM=1, and is a prerequisite of NOTHING -- asserted by parsing the
    # Makefile in tests/test_engine_hiding_shim.py, not by reading it here.
    "shim-reap",
    "ci",
    "clean",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def console_script() -> list[str]:
    """The argv prefix that runs the installed CLI as a real process."""
    sibling = Path(sys.executable).parent / "pdftooling"
    if sibling.exists():
        return [str(sibling)]
    found = shutil.which("pdftooling")
    if found:
        return [found]
    return [sys.executable, "-m", "pdf_tooling"]


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
    subclasses = errors.PdfToolingError.__subclasses__()
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
    error = errors.PdfToolingError("boom")
    assert error.exit_code == exit_codes.FAILURE
    assert error.redacted is False
    assert errors.AuthError("nope", redacted=True).redacted is True


def _error_descendants() -> tuple[type[errors.PdfToolingError], ...]:
    def walk(cls: type[errors.PdfToolingError]) -> list[type[errors.PdfToolingError]]:
        found = [cls]
        for child in cls.__subclasses__():
            found.extend(walk(child))
        return found

    return tuple(walk(errors.PdfToolingError))


def test_every_error_class_carries_a_published_exit_code() -> None:
    """PDF-01 AC8's SURVIVING invariant, and the half nothing measured.

    AC8 as written requires *"exactly one exception class per non-zero code"*.
    That is **no longer true and is correctly no longer true**: the mapping is
    many-to-one (`REFUSED` alone carries seven concrete classes). The property
    the exit-code table actually depends on is the partition plus membership:
    **one BASE class per non-zero code** (the assertion above, which reads
    `PdfToolingError.__subclasses__()` -- direct subclasses only) **and every
    concrete descendant's `exit_code` a member of `ALL_EXIT_CODES`**.

    **No cardinality is pinned here, deliberately.** A criterion pinning an
    error-class COUNT would turn a later spec red for adding a correctly
    classified subclass, which is a control failing for a reason it does not
    claim.
    """
    descendants = _error_descendants()
    assert len(descendants) > len(errors.PdfToolingError.__subclasses__()), (
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
    base_codes = {base.exit_code for base in errors.PdfToolingError.__subclasses__()}
    for cls in descendants:
        if cls is errors.PdfToolingError:
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
    assert "pdftooling" in line
    assert "Python" in line
    assert re.search(r"pypdf \d+\.\d+", line), line

    # PDF-24: the three clauses above assert LABELS, not VALUES. `"Python" in
    # line` is satisfied by the literal word sitting in `version_line()`'s own
    # f-string -- MEASURED: replacing `python_version()`'s whole return value
    # with a constant left this test GREEN. AC7 requires the line to carry
    # *the running Python version* and *the tool version*, so both are asserted
    # against a value computed here rather than against a word.
    import platform

    from pdf_tooling import __version__ as tool_version

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
        [sys.executable, "-m", "pdf_tooling", "--help"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert module.returncode == 0
    assert module.stdout == canonical.stdout

    alias = Path(sys.executable).parent / "pdf-tooling"
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


# --------------------------------------------------------------------------- #
# PDF-65 / OR-18 / X-723 -- THE LIVENESS ARM the partition never had
# --------------------------------------------------------------------------- #
#
# WHAT WAS BROKEN, AND IT WAS NOT A MISSING FLAG. The partition control above
# asserts that every ungoverned flag carries a non-blank reason longer than 20
# characters. `--no-color`'s reason was *"a property of the stderr stream, which
# every verb has"* -- 48 characters, grammatical, and BYTE-IDENTICAL to
# `--quiet`'s and `--verbose`'s, both of which are TRUE because `resolve_level`
# genuinely alters the stderr stream. The flag itself did nothing: `color_enabled`
# had zero callers, `configure_logging` executed `del no_color`, and no module
# under `src/` ever emitted an ANSI escape. **Prose quality is not evidence of
# behaviour**, and that is the measured proof of it: the instrument this product
# built BECAUSE it had already shipped inert flags (`996f9eb6bc`) could not see
# the one it was shipping.
#
# THE THREE TERMINAL CLASSES (X-723). Every member of `UNGOVERNED_FLAGS`
# resolves to exactly one, and each is a claim that is TRUE at this commit and
# FALSIFIABLE:
#
#   (a) BEHAVIOURAL      driven and asserted at EVERY leaf it is declared on.
#                        Reds when a node stops resolving, stops naming the
#                        flag, or when the driven set falls short of declared.
#   (b) INERT_BY_DESIGN  declared, provably no behaviour, AND the help text
#                        SAYS SO. Reds if the flag ever gains behaviour.
#                        EMPTY at this commit -- and asserted empty, plus
#                        constructible, because an emptiness assertion over an
#                        unbuildable shape is vacuous.
#   (c) UNDER_DRIVEN     live, but asserted at fewer leaves than declared. A
#                        RATCHET, not an exemption: the recorded floor may be
#                        RAISED freely and LOWERED only by an edit somebody
#                        makes on the record.
#
# `INERT_BY_DESIGN` IS FORBIDDEN ON `--threads` AND ON `--version`, and the
# prohibition is evidenced rather than asserted. `--threads 0` turns exit 0 into
# exit 2 (`test_ac6_threads_out_of_range_exits_2`) and `--threads 1` vs `8` is
# asserted byte-identical at `text`; `--version` is eager and exits before any
# verb body, which IS behaviour. Marking either inert would ship a false marker
# at the version that turns help into a promise -- the exact defect this arm
# exists to remove.
#
# WHY THE REGISTRY LIVES HERE AND NOT IN `cli/common.py`. `I-1` proposed
# re-expressing `UNGOVERNED_FLAGS` itself as `(reason, evidence)`. Measured, that
# breaks BOTH of its consumers: this file's `reason.strip()` raises on a tuple,
# and `tests/test_honesty_claims.py`'s `"--in-place" in UNGOVERNED_FLAGS[...]`
# silently changes meaning from *"this phrase is in the reason"* to *"this
# element is in the tuple"* -- passing or failing for the wrong reason. Beyond
# that, `evidence` is a pytest node id, and a shipped package whose module API
# depends on the shape of the test tree is backwards. The guarantee is
# identical anyway: `test_every_ungoverned_flag_resolves_to_a_terminal_class`
# asserts `set(LIVENESS) == set(UNGOVERNED_FLAGS)`, so a flag cannot be declared
# ungoverned without resolving to a class. The binding is ASSERTED rather than
# structural, and it is asserted in the one place that can resolve a node id.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Behavioural:
    """Class (a): driven and asserted at every leaf the flag is declared on."""

    nodes: tuple[str, ...]


@dataclass(frozen=True)
class _InertByDesign:
    """Class (b): declared, provably inert, and the help text DISCLOSES it.

    The third condition is the one that gets dropped, so it is the one the arm
    checks hardest: *inert by design, **disclosed*** is the safe state, and
    *inert by omission* is what this product's headline defect class is made of.
    """

    disclosure: str


@dataclass(frozen=True)
class _UnderDriven:
    """Class (c): live, but asserted at fewer leaves than it is declared on.

    `leaves` is the driven-leaf set MEASURED at landing and `floor` is the
    ratchet bound; the arm holds `len(leaves) == floor` so the recorded set and
    the bound cannot drift apart. The DECLARED count is never a literal here --
    it is derived from the live command tree every run (X-723 (ii)).

    `carrier` is a `BACKLOG.md` row id, checked for SHAPE ONLY. That file lives
    in a different repository, and making this product's gate read it would
    re-create the cross-repository coupling `PDF-70` exists to remove and would
    make a consumer's clone unable to go green. Verifying the row exists is the
    `project-manager`'s write and the `qa-sentinel`'s check.
    """

    nodes: tuple[str, ...]
    leaves: tuple[str, ...]
    floor: int
    carrier: str
    #: Why the floor is the number it is. REQUIRED, and the ONLY admissible
    #: cover for a floor of 0 -- an honest zero records a 0-of-26 gap in the
    #: instrument instead of in a report nobody re-reads.
    justification: str
    #: Non-empty exactly when `carrier` is unallocated: what was escalated, to
    #: whom, and what is owed back. An unallocated carrier can never be silent.
    escalation: str = ""


_Liveness = _Behavioural | _InertByDesign | _UnderDriven

#: The shape `carrier` must take once the `project-manager` has allocated it.
_CARRIER = re.compile(r"^B-\d{3}$")

#: `--quiet` measures 24 of 26 and therefore resolves to class (c), which needs
#: a carrier row the PM has not allocated (D8/AC9). The engineer does NOT mint a
#: `B-NNN` and does NOT widen class (a) to absorb it, so the unallocated state is
#: represented EXPLICITLY and carries its own escalation text.
_UNALLOCATED: Final[str] = ""

#: PDF-65 D7 -- `--threads` and `--version` are class (c) against the carrier the
#: PM forward-allocated for the deferred `I-14` repair. Consumed as given: this
#: file neither creates the row nor resolves it.
_B310: Final[str] = "B-310"

LIVENESS: Final[Mapping[str, _Liveness]] = MappingProxyType(
    {
        "--dry-run": _Behavioural(
            nodes=(
                "tests/test_cli_contract.py::test_c9_unconditional_dry_run_purity",
                "tests/test_cli_contract.py::test_c10_registered_invocation_dry_run_purity",
            ),
        ),
        "--output-format": _Behavioural(
            nodes=(
                "tests/test_usage_envelope.py::"
                "test_ac1_ac3_an_unknown_flag_is_enveloped_at_every_verb_in_every_shape",
            ),
        ),
        "--no-backup": _Behavioural(
            nodes=("tests/test_cli_contract.py::test_c7_no_backup_alone_exits_2",),
        ),
        "--password-file": _Behavioural(
            nodes=(
                "tests/test_password_file_contract.py::"
                "test_ac12_a_planted_secret_never_appears_in_debug_output",
            ),
        ),
        # The same node covers `--verbose`: it types `--password-file <path> -vv`
        # at every registered leaf through `_debug_sweep`, and `-vv` is `-v`'s
        # count-flag repeat form, derived from the declaration rather than
        # spelled out here.
        "--verbose": _Behavioural(
            nodes=(
                "tests/test_password_file_contract.py::"
                "test_ac12_a_planted_secret_never_appears_in_debug_output",
            ),
        ),
        "--quiet": _UnderDriven(
            nodes=(
                "tests/test_cli_contract.py::test_c18_an_unreadable_operand_is_a_coded_failure",
                "tests/test_cli_contract.py::test_c19_a_malformed_operand_never_tracebacks",
                "tests/test_cli_contract.py::test_c20_no_rendered_message_carries_a_heap_address",
            ),
            leaves=(
                "compose",
                "compress",
                "convert",
                "create",
                "decrypt",
                "delete",
                "encrypt",
                "extract",
                "info",
                "linearize",
                "merge",
                "meta get",
                "meta set",
                "ocr",
                "permissions",
                "rasterize",
                "reorder",
                "repair",
                "rotate",
                "split",
                "stamp",
                "tables",
                "text",
                "watermark",
            ),
            floor=24,
            carrier=_UNALLOCATED,
            justification=(
                "C18/C19/C20 run over `OPERAND_VERBS`, and `doctor` and `version` take no "
                "operand -- so 24 of the 26 leaves `--quiet` is declared on, re-derived at "
                "this commit and agreeing with AUDIT.md 3.4's prior of 24/26. The flag is "
                "unambiguously LIVE (`resolve_level` alters the stderr stream and "
                "`test_ac18_quiet_suppresses_engine_chatter_on_the_recorded_operand` "
                "measures the suppression), so class (b) is false about it and class (a) "
                "would let a short flag claim full coverage"
            ),
            escalation=(
                "PDF-65 AC9/D8: scoping by defect CLASS rather than by enumerated location "
                "pulls `--quiet` into class (c), and the PM allocated `B-310` for "
                "`--threads` and `--version` only. The engineer does not mint a `B-NNN`, "
                "does not borrow `B-310`, and does not widen class (a) to absorb it. "
                "ESCALATED to the project-manager for either a carrier row id of its own or "
                "a class ruling; until one lands the carrier stays unallocated and the "
                "carrier-shape cell below is xfail-pinned so the debt is VISIBLE rather "
                "than absorbed"
            ),
        ),
        "--threads": _UnderDriven(
            nodes=(
                "tests/test_batch_continuation.py::"
                "test_ac5_items_are_in_command_line_order_under_threads",
                "tests/integration/test_rasterize_cli.py::test_ac6_threads_out_of_range_exits_2",
                "tests/integration/test_text_tables_cli.py::"
                "test_ac18_threads_1_and_threads_8_produce_byte_identical_stdout",
            ),
            leaves=(
                "compress",
                "convert",
                "delete",
                "extract",
                "ocr",
                "rasterize",
                "reorder",
                "rotate",
                "tables",
                "text",
            ),
            floor=10,
            carrier=_B310,
            justification=(
                "AUDIT.md 3.4's prior is 3/26 and it UNDERCOUNTS: "
                "`test_ac5_items_are_in_command_line_order_under_threads` is parameterized "
                "over the ten `--out-dir` batch verbs and types `--threads 4` at each "
                "through `_drive`, with a flag-attributable assertion, which the audit's "
                "per-flag table does not carry. Re-derived here: 10. The other two nodes "
                "are the LIVENESS proof rather than leaf coverage -- `--threads 0` exits 2 "
                "and `--threads 1` vs `8` is byte-identical at `text` -- and they contribute "
                "no leaves because their node ids carry no leaf parameter id, which is the "
                "honest reading of a count derived from parameter ids"
            ),
        ),
        "--version": _UnderDriven(
            nodes=(
                "tests/test_cli_spine.py::"
                "test_version_flag_reports_tool_python_and_engine_versions",
            ),
            leaves=(),
            floor=0,
            carrier=_B310,
            justification=(
                "`--version` is EAGER: it exits before the callback, which is behaviour, and "
                "`test_version_flag_reports_tool_python_and_engine_versions` observes it at "
                "the ROOT. No control makes it observable AT A LEAF, so the derived count is "
                "0 of the 26 leaves it is declared on -- and the honest zero is the point. "
                "The entry still asserts that its node resolves, that the node names the "
                "flag, that the declared count is derived live, and that a carrier is named; "
                "it records a 0-of-26 gap in the instrument instead of in a report nobody "
                "re-reads. `INERT_BY_DESIGN` on this flag would be a FALSE marker, not a "
                "judgement call"
            ),
        ),
    }
)


# --------------------------------------------------------------------------- #
# The derivations. Every one reads the LIVE tree or a REAL collection; not one
# count below is transcribed, which is why deleting a flag moves five separate
# figures and requires no edit to any of them.
# --------------------------------------------------------------------------- #


def liveness_files() -> tuple[str, ...]:
    """The test files the registry's node ids name, and no others.

    Scoped this way so the arm costs one short collection rather than a
    whole-suite one -- the `tests/test_acceptance_audit.py` precedent.
    """
    return tuple(
        sorted(
            {
                node.split("::", 1)[0]
                for entry in LIVENESS.values()
                for node in getattr(entry, "nodes", ())
            }
        )
    )


def collect_liveness_nodes(targets: Sequence[str]) -> frozenset[str]:
    """Every node id pytest collects from *targets*, as a REAL collection.

    An AST guess would accept a node id that no longer collects, which is
    precisely the staleness half (i) of the resolution arm exists to catch.
    """
    if not targets:
        return frozenset()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            *targets,
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        pytest.fail(
            "pytest --collect-only failed over the files the liveness registry names "
            f"({list(targets)}): {result.stdout}{result.stderr}"
        )
    return frozenset(
        line.strip()
        for line in result.stdout.splitlines()
        if "::" in line and not line.startswith(" ")
    )


def _resolving(node: str, collected: frozenset[str]) -> tuple[str, ...]:
    """The collected ids *node* names -- itself, or its parameterized cells."""
    return tuple(sorted(one for one in collected if one == node or one.startswith(f"{node}[")))


def _param_id(node_id: str) -> str:
    if node_id.endswith("]") and "[" in node_id:
        return node_id[node_id.index("[") + 1 : -1]
    return ""


def leaves_in_param_id(param_id: str, leaves: Sequence[str]) -> frozenset[str]:
    """The live verb names appearing as dash-delimited runs in a parameter id.

    `[merge]` and `[merge-json]` and `[c20-meta get-json-quiet]` all name a leaf;
    `[default]` names none. Verb names carry spaces (`meta get`) and never
    dashes, so a dash is an unambiguous delimiter here.
    """
    found = set()
    for leaf in leaves:
        if (
            param_id == leaf
            or param_id.startswith(f"{leaf}-")
            or param_id.endswith(f"-{leaf}")
            or f"-{leaf}-" in param_id
        ):
            found.add(leaf)
    return frozenset(found)


def driven_leaves(
    nodes: Sequence[str], collected: frozenset[str], leaves: Sequence[str]
) -> frozenset[str]:
    """The leaves *nodes* cover, read off parameter ids against the live roster.

    **WHICH QUESTION THIS ANSWERS, stated rather than left to the reader**: it
    answers *the flag is TYPED at this leaf* -- the node names a spelling of the
    flag (asserted separately by the resolution arm) and collects a cell whose
    parameter id names the leaf. It does NOT answer *the flag's EFFECT is
    asserted at this leaf*; `tests/test_usage_envelope.py`'s
    `run_cli(verb.name, "--threads", "0", "-o", "json")` arm is the standing
    counter-example, where `--threads 0` is a decoy to force an ARITY error and
    the flag is not the subject. The same question is answered for every class-
    (c) member, because mixing the two makes the counts incomparable.

    Two caveats disclosed rather than hidden: the count is over COLLECTED cells
    rather than executed ones -- a host without an engine skips some of them --
    and a node whose leaf is fixed by its module rather than by a parameter
    (`tests/integration/test_rasterize_cli.py` is always `rasterize`) contributes
    no leaves at all. Both make the derived count a FLOOR on coverage, which is
    the safe direction for a ratchet.
    """
    covered: set[str] = set()
    for node in nodes:
        for node_id in _resolving(node, collected):
            covered |= leaves_in_param_id(_param_id(node_id), leaves)
    return frozenset(covered)


def _count_option_spellings() -> frozenset[str]:
    """Spellings declared `count=True`, so `-vv` can be recognised as `-v` typed
    twice WITHOUT writing `-vv` down anywhere."""
    spellings: set[str] = set()
    for spec in GLOBAL_PARAMS:
        info = typing.get_args(spec.annotation)[1]
        if not getattr(info, "count", False):
            continue
        decls = [getattr(info, "default", None), *(getattr(info, "param_decls", ()) or ())]
        canonical = next(one for one in decls if isinstance(one, str) and one.startswith("--"))
        spellings |= {
            spelling for spelling, target in GLOBAL_FLAG_SPELLINGS.items() if target == canonical
        }
    return frozenset(spellings)


_ARGV_TOKEN = re.compile(r"-{1,2}[A-Za-z][A-Za-z0-9-]*")


def canonical_flag_of(token: str, count_spellings: frozenset[str]) -> str | None:
    """The canonical long spelling *token* types, or `None` if it types nothing.

    Derived entirely from `GLOBAL_FLAG_SPELLINGS` plus the `count=True`
    repeat form; there is no literal spelling table here to go stale.
    """
    if token in GLOBAL_FLAG_SPELLINGS:
        return GLOBAL_FLAG_SPELLINGS[token]
    if not token.startswith("--") and len(token) > 2:
        head = token[:2]
        if head in count_spellings and set(token[1:]) == {token[1]}:
            return GLOBAL_FLAG_SPELLINGS[head]
    return None


def node_source(node: str) -> str:
    """The test function's own source, plus the source of the module-level
    helpers it calls DIRECTLY. One hop, deliberately.

    The flag is often typed in a helper -- `_debug_sweep` appends
    `--password-file <path> -vv`, `_drive` appends `--threads 4` -- so a
    function-body-only read would call those nodes flag-less and push live flags
    into class (c) for a reason that is about this arm rather than about the
    product. One hop covers every node this registry names; recursion is
    deliberately NOT taken, because an unbounded walk ends up reading the whole
    module, and a whole-module read is satisfied by any mention anywhere, which
    is the weak check half (ii) exists to replace.
    """
    rel, _, func = node.partition("::")
    path = REPO_ROOT / rel
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    top = {
        node_.name: node_
        for node_ in tree.body
        if isinstance(node_, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    target = top.get(func)
    if target is None:
        return ""
    chunks = [ast.get_source_segment(text, target) or ""]
    called = {
        inner.func.id
        for inner in ast.walk(target)
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
    }
    for name in sorted(called):
        if name in top and name != func:
            chunks.append(ast.get_source_segment(text, top[name]) or "")
    return "\n".join(chunks)


def source_names_flag(source: str, flag: str, count_spellings: frozenset[str]) -> bool:
    """Whether *source* types *flag* under any spelling the block declares."""
    return any(
        canonical_flag_of(token, count_spellings) == flag for token in _ARGV_TOKEN.findall(source)
    )


# --------------------------------------------------------------------------- #
# The four checkers. PURE over their parameters, following
# `docs_ratification_complaints`'s rule: a synthetic registry drives each one
# exactly as the real one does, so the red controls never vandalise a real
# entry to prove the arm fires.
# --------------------------------------------------------------------------- #


def totality_complaints(
    registry: Mapping[str, _Liveness], partition: Mapping[str, str]
) -> list[str]:
    """Arm 1 -- the arm the partition has always been missing."""
    complaints = []
    for flag in sorted(set(partition) - set(registry)):
        complaints.append(
            f"{flag} is declared in UNGOVERNED_FLAGS and resolves to NO terminal class. "
            "A non-blank reason is not evidence of behaviour: `--no-color` carried a "
            "48-character reason byte-identical to `--quiet`'s and did nothing at all. "
            "Classify it (a) BEHAVIOURAL, (b) INERT_BY_DESIGN with the disclosure its "
            "help text carries, or (c) UNDER_DRIVEN with a floor and a carrier"
        )
    for flag in sorted(set(registry) - set(partition)):
        complaints.append(
            f"{flag} carries a liveness class but is not in UNGOVERNED_FLAGS -- the "
            "registry is asserting about a flag the partition does not declare"
        )
    return complaints


def resolution_complaints(
    registry: Mapping[str, _Liveness],
    *,
    resolve: Callable[[str], tuple[str, ...]],
    source_of: Callable[[str], str],
    names_flag: Callable[[str, str], bool],
) -> list[str]:
    """Arm 2 -- both halves, and neither alone is sufficient (D5).

    (i) alone would let a registry point every flag at one real test and stay
    green; (ii) alone would let a deleted or renamed test sail through on a
    text match. Every message names the flag, because an unlocalised red is the
    first step toward an exemption.
    """
    complaints = []
    for flag in sorted(registry):
        for node in getattr(registry[flag], "nodes", ()):
            resolved = resolve(node)
            if not resolved:
                complaints.append(
                    f"{flag}: evidence node {node!r} resolves to NOTHING in the live "
                    "collection -- it was deleted, renamed or moved, and the class "
                    "marker has been making a claim about a test that is not there"
                )
                continue
            if not names_flag(source_of(node), flag):
                complaints.append(
                    f"{flag}: evidence node {node!r} collects {len(resolved)} cell(s) but "
                    f"its source never types {flag} under any spelling the block declares "
                    "-- a resolving node id is not evidence about THIS flag"
                )
    return complaints


def class_integrity_complaints(
    registry: Mapping[str, _Liveness],
    *,
    declared_leaves: Callable[[str], frozenset[str]],
    derived_driven: Callable[[str], frozenset[str]],
    help_texts: Callable[[str], Mapping[str, str]],
) -> list[str]:
    """Arm 3 -- three separate properties, each with its own cover."""
    complaints = []
    for flag in sorted(registry):
        entry = registry[flag]
        declared = declared_leaves(flag)
        if isinstance(entry, _Behavioural):
            driven = derived_driven(flag)
            missing = sorted(declared - driven)
            if missing:
                complaints.append(
                    f"{flag} is marked BEHAVIOURAL -- driven and asserted at every leaf it "
                    f"is declared on -- but the derived driven set misses {missing}. Either "
                    "close the gap or re-mark it UNDER_DRIVEN with a floor and a carrier; "
                    "class (a) may not be widened to absorb a short flag"
                )
        elif isinstance(entry, _InertByDesign):
            gained = sorted(derived_driven(flag))
            if gained:
                complaints.append(
                    f"{flag} is marked INERT_BY_DESIGN but the derived driven set is "
                    f"{gained} -- the flag GAINED behaviour and the marker is now a FALSE "
                    "claim in the help text. Re-classify it (a) or (c); a flag that does "
                    "something may not advertise that it does nothing"
                )
            if not entry.disclosure.strip():
                complaints.append(
                    f"{flag} is marked INERT_BY_DESIGN with an EMPTY disclosure. *Inert by "
                    "design, DISCLOSED* is the safe state; an undisclosed inert flag is "
                    "*inert by omission*, which is the state this arm exists to remove"
                )
            else:
                texts = help_texts(flag)
                silent = sorted(
                    leaf for leaf in declared if entry.disclosure not in texts.get(leaf, "")
                )
                if silent:
                    complaints.append(
                        f"{flag} is marked INERT_BY_DESIGN but its help text does not carry "
                        f"the disclosure {entry.disclosure!r} at {silent}. A user reading "
                        "--help must learn the flag does nothing"
                    )
        else:
            if len(entry.leaves) != entry.floor:
                complaints.append(
                    f"{flag}: the recorded driven-leaf set has {len(entry.leaves)} members "
                    f"but floor is {entry.floor} -- the record and the bound have drifted"
                )
            if entry.floor >= len(declared):
                complaints.append(
                    f"{flag} is marked UNDER_DRIVEN with floor {entry.floor} against "
                    f"{len(declared)} declared leaves. A floor that equals or exceeds the "
                    "declared count is a BEHAVIOURAL member wearing the wrong marker"
                )
            if entry.floor < 0:
                complaints.append(f"{flag}: floor {entry.floor} is negative")
            if not entry.justification.strip():
                complaints.append(
                    f"{flag} is marked UNDER_DRIVEN with no justification. A floor of "
                    f"{entry.floor} against {len(declared)} declared leaves is a gap; an "
                    "unexplained gap is the exemption this arm exists to prevent"
                )
            if entry.carrier == _UNALLOCATED and not entry.escalation.strip():
                complaints.append(
                    f"{flag} is marked UNDER_DRIVEN with an UNALLOCATED carrier and no "
                    "escalation text. An unallocated carrier may be outstanding, but it "
                    "may never be SILENT: record what was escalated and what is owed back"
                )
    return complaints


def carrier_complaints(flag: str, entry: _Liveness) -> list[str]:
    """Arm 3 (iii), split out so it can be observed per member (X-723 (iii)).

    SHAPE ONLY -- see `_UnderDriven`'s docstring for why this deliberately does
    not resolve the row against `BACKLOG.md`.
    """
    if not isinstance(entry, _UnderDriven):
        return []
    if not _CARRIER.fullmatch(entry.carrier):
        return [
            f"{flag} is marked UNDER_DRIVEN and its carrier is {entry.carrier!r}, which is "
            "not a `B-NNN` BACKLOG.md row id. A carried gap needs a row somebody owns; an "
            "uncarried one is an exemption with better manners"
        ]
    return []


def ratchet_complaints(
    registry: Mapping[str, _Liveness], *, derived_driven: Callable[[str], frozenset[str]]
) -> list[str]:
    """Arm 4 -- coverage may not fall silently.

    RAISING a floor is free and is what closing the carrier row looks like.
    LOWERING one is permitted and is supposed to be VISIBLE: it is an edit
    somebody makes on the record, and an unexplained lowering is the finding a
    `qa-sentinel` files.
    """
    complaints = []
    for flag in sorted(registry):
        entry = registry[flag]
        if not isinstance(entry, _UnderDriven):
            continue
        driven = derived_driven(flag)
        if len(driven) < entry.floor:
            complaints.append(
                f"{flag}: the derived driven-leaf count FELL to {len(driven)} "
                f"({sorted(driven)}) against a recorded floor of {entry.floor}. Coverage "
                "does not fall silently -- restore the covering node, or lower the floor "
                "deliberately and say why in the entry"
            )
    return complaints


def declared_leaves(flag: str) -> frozenset[str]:
    """The leaves that DECLARE *flag*, walked off the LIVE command tree.

    Never a literal and never `len(VERBS)` assumed-universal: a flag that stopped
    being attached to a verb would otherwise leave every count below unchanged
    (X-723 (ii)).
    """
    found: set[str] = set()

    def walk(cmd: object, path: tuple[str, ...]) -> None:
        commands = getattr(cmd, "commands", None)
        if commands is not None:
            for name in sorted(commands):
                walk(commands[name], (*path, name))
            return
        spellings = {
            opt for param in getattr(cmd, "params", ()) for opt in getattr(param, "opts", ())
        }
        if flag in spellings:
            found.add(" ".join(path))

    walk(typer_root_command(), ())
    return frozenset(found)


@pytest.fixture(scope="module")
def liveness_nodes() -> frozenset[str]:
    """One real collection, shared by every arm below."""
    return collect_liveness_nodes(liveness_files())


@pytest.fixture(scope="module")
def count_spellings() -> frozenset[str]:
    return _count_option_spellings()


# --------------------------------------------------------------------------- #
# Arm 1 -- TOTALITY. The arm the partition has always been missing, and the one
# that was RED at `d3fca0c` naming `--no-color` while the flag was still
# declared. The backend leg's eleven-line deletion is what turned it green, BY
# SUBTRACTION -- which is what makes "we removed an inert flag" a checkable
# claim rather than a commit message.
# --------------------------------------------------------------------------- #


def test_every_ungoverned_flag_resolves_to_a_terminal_class() -> None:
    """AC1/AC2 (X-723). A flag cannot be declared ungoverned without resolving
    to one of the three terminal classes."""
    complaints = totality_complaints(LIVENESS, UNGOVERNED_FLAGS)
    assert complaints == [], "\n".join(complaints)


def test_the_totality_arm_fires_in_each_direction() -> None:
    """AC2's red control, both directions, on SYNTHETIC data.

    Each direction alone leaves the other hole open: an arm that only checks
    *partition -> registry* accepts a registry asserting about a flag nobody
    declares, and an arm that only checks *registry -> partition* is exactly the
    hole `--no-color` lived in.
    """
    entry = _Behavioural(nodes=("tests/x.py::test_y",))

    undeclared_class = totality_complaints({"--a": entry}, {"--a": "r", "--b": "r"})
    assert any("--b" in one for one in undeclared_class), undeclared_class

    unknown_flag = totality_complaints({"--a": entry, "--c": entry}, {"--a": "r"})
    assert any("--c" in one for one in unknown_flag), unknown_flag

    assert totality_complaints({"--a": entry}, {"--a": "r"}) == []


# --------------------------------------------------------------------------- #
# Arm 2 -- RESOLUTION, both halves (D5).
# --------------------------------------------------------------------------- #


def test_every_liveness_node_resolves_and_names_its_flag(
    liveness_nodes: frozenset[str], count_spellings: frozenset[str]
) -> None:
    """AC3. Each evidence node collects live, AND its source types the flag."""
    complaints = resolution_complaints(
        LIVENESS,
        resolve=lambda node: _resolving(node, liveness_nodes),
        source_of=node_source,
        names_flag=lambda source, flag: source_names_flag(source, flag, count_spellings),
    )
    assert complaints == [], "\n".join(complaints)


def test_the_resolution_arm_fires_on_each_half_separately() -> None:
    """AC3's red control. The two halves establish different things.

    (i) alone would let a registry point EVERY flag at one real, resolving test
    and stay green -- it never reads what the test is about. (ii) alone would let
    a deleted or renamed node id sail through on a text match against source that
    is no longer collected. Both, or neither is worth having.
    """
    real = "tests/real.py::test_real"
    registry = {"--a": _Behavioural(nodes=(real,))}

    missing = resolution_complaints(
        registry,
        resolve=lambda node: (),
        source_of=lambda node: 'run_cli("--a")',
        names_flag=lambda source, flag: flag in source,
    )
    assert any("--a" in one and "resolves to NOTHING" in one for one in missing), missing

    silent = resolution_complaints(
        registry,
        resolve=lambda node: (f"{node}[info]",),
        source_of=lambda node: 'run_cli("--something-else")',
        names_flag=lambda source, flag: flag in source,
    )
    assert any("--a" in one and "never types" in one for one in silent), silent

    assert (
        resolution_complaints(
            registry,
            resolve=lambda node: (f"{node}[info]",),
            source_of=lambda node: 'run_cli("--a")',
            names_flag=lambda source, flag: flag in source,
        )
        == []
    )


def test_the_node_source_read_reaches_one_hop_into_a_helper() -> None:
    """The non-vacuity proof for `node_source` itself, and for the count-flag
    repeat form.

    `test_ac12_a_planted_secret_never_appears_in_debug_output` types neither
    `--password-file` nor `-vv` in its own body -- `_debug_sweep` does -- and a
    body-only read would call the node flag-less and push two LIVE flags into
    class (c) for a reason about this arm rather than about the product. If
    typer ever stops reporting `count=True`, the `-vv` half below goes red here
    rather than silently downgrading `--verbose`.
    """
    node = (
        "tests/test_password_file_contract.py::"
        "test_ac12_a_planted_secret_never_appears_in_debug_output"
    )
    body_only = ast.get_source_segment
    assert body_only is not None  # the reader this helper is built on still exists
    source = node_source(node)
    assert source, "the one-hop source read returned nothing"
    spellings = _count_option_spellings()
    assert spellings, "no count=True spelling was derived -- the `-vv` branch is unreachable"
    assert source_names_flag(source, "--password-file", spellings)
    assert source_names_flag(source, "--verbose", spellings), (
        "`-vv` was not recognised as `-v` typed twice; --verbose would be mis-classified"
    )
    assert not source_names_flag(source, "--no-backup", spellings), (
        "the reader matches a flag the node never types -- it is not discriminating"
    )


# --------------------------------------------------------------------------- #
# Arm 3 -- CLASS INTEGRITY. Three properties, three separate observations.
# --------------------------------------------------------------------------- #


def test_every_liveness_class_holds_its_own_invariants(
    liveness_nodes: frozenset[str],
) -> None:
    """AC4 (i) and (ii)."""
    leaves = tuple(verb.name for verb in discover_verbs())
    complaints = class_integrity_complaints(
        LIVENESS,
        declared_leaves=declared_leaves,
        derived_driven=lambda flag: driven_leaves(
            getattr(LIVENESS[flag], "nodes", ()), liveness_nodes, leaves
        ),
        help_texts=lambda flag: {},
    )
    assert complaints == [], "\n".join(complaints)


def test_the_class_integrity_arm_fires_on_each_property_separately() -> None:
    """AC4's red control. A single combined observation would not establish that
    each property has its own cover."""
    declared = frozenset({"one", "two", "three"})

    def check(registry, driven, helps=None):
        return class_integrity_complaints(
            registry,
            declared_leaves=lambda flag: declared,
            derived_driven=lambda flag: driven,
            help_texts=lambda flag: helps or {},
        )

    # (i) an UNDER_DRIVEN floor that equals the declared count
    full = {
        "--a": _UnderDriven(
            nodes=("tests/x.py::t",),
            leaves=("one", "two", "three"),
            floor=3,
            carrier="B-310",
            justification="because",
        )
    }
    assert any("wrong marker" in one for one in check(full, declared)), check(full, declared)

    # (ii) a BEHAVIOURAL member short of its declared leaves
    short = {"--a": _Behavioural(nodes=("tests/x.py::t",))}
    complaints = check(short, frozenset({"one"}))
    assert any("misses" in one and "'three'" in one for one in complaints), complaints

    # (iii) an UNDER_DRIVEN member with no justification at all
    bare = {
        "--a": _UnderDriven(
            nodes=("tests/x.py::t",),
            leaves=("one",),
            floor=1,
            carrier="B-310",
            justification="  ",
        )
    }
    assert any("no justification" in one for one in check(bare, declared)), check(bare, declared)

    # (iv) an UNDER_DRIVEN member whose recorded set and bound disagree
    drifted = {
        "--a": _UnderDriven(
            nodes=("tests/x.py::t",),
            leaves=("one",),
            floor=2,
            carrier="B-310",
            justification="because",
        )
    }
    assert any("drifted" in one for one in check(drifted, declared)), check(drifted, declared)

    # (v) an unallocated carrier with no escalation text is SILENT, which is
    #     the one thing an outstanding escalation may never be
    silent = {
        "--a": _UnderDriven(
            nodes=("tests/x.py::t",),
            leaves=("one",),
            floor=1,
            carrier=_UNALLOCATED,
            justification="because",
        )
    }
    assert any("never be SILENT" in one for one in check(silent, declared)), check(silent, declared)

    good = {
        "--a": _UnderDriven(
            nodes=("tests/x.py::t",),
            leaves=("one",),
            floor=1,
            carrier="B-310",
            justification="because",
        )
    }
    assert check(good, frozenset({"one"})) == []


def _carrier_cases() -> list[object]:
    """One case per class-(c) member, xfail-pinned where the PM has not yet
    allocated the carrier row.

    The pin is derived from the ENTRY's own state (`carrier == _UNALLOCATED`),
    never from a flag name written down here -- so it is a debt marker rather
    than an enumerated exemption, and it disappears the moment the row lands.
    """
    cases: list[object] = []
    for flag in sorted(LIVENESS):
        entry = LIVENESS[flag]
        if not isinstance(entry, _UnderDriven):
            continue
        marks = (
            (pytest.mark.xfail(strict=True, reason=entry.escalation),)
            if entry.carrier == _UNALLOCATED
            else ()
        )
        cases.append(pytest.param(flag, marks=marks, id=flag))
    return cases


@pytest.mark.parametrize("flag", _carrier_cases())
def test_every_under_driven_member_names_a_carrier_row(flag: str) -> None:
    """AC4 (iii), X-723 (iii). Shape only -- `BACKLOG.md` is another repository's
    file and resolving it here would make a consumer's clone unable to go green.

    `--quiet` is the outstanding one: it measures 24 of 26, the PM allocated
    `B-310` for `--threads` and `--version` only, and this engineer mints no
    `B-NNN`. Its cell is xfail-pinned with the escalation text as its reason, so
    the debt is VISIBLE in `-rx` output rather than absorbed into class (a).
    """
    complaints = carrier_complaints(flag, LIVENESS[flag])
    assert complaints == [], "\n".join(complaints)


def test_the_carrier_population_is_not_empty() -> None:
    """The anti-lapse guard on the parametrization above: an empty case list
    would make the carrier arm silently unrun."""
    assert _carrier_cases(), "no class-(c) member -- the carrier arm collects nothing"


def test_the_carrier_arm_fires_on_a_malformed_row_id() -> None:
    """AC4 (iii)'s red control, on synthetic entries."""

    def entry(carrier: str) -> _UnderDriven:
        return _UnderDriven(
            nodes=("tests/x.py::t",),
            leaves=("one",),
            floor=1,
            carrier=carrier,
            justification="because",
        )

    assert carrier_complaints("--a", entry("")) != []
    assert carrier_complaints("--a", entry("B-31")) != []
    assert carrier_complaints("--a", entry("b-310")) != []
    assert carrier_complaints("--a", entry("B-310")) == []
    assert carrier_complaints("--a", _Behavioural(nodes=())) == []


# --------------------------------------------------------------------------- #
# Arm 4 -- THE RATCHET.
# --------------------------------------------------------------------------- #


def test_the_driven_leaf_count_has_not_fallen_below_its_floor(
    liveness_nodes: frozenset[str],
) -> None:
    """AC5. Coverage may RISE freely; it may not FALL silently."""
    leaves = tuple(verb.name for verb in discover_verbs())
    complaints = ratchet_complaints(
        LIVENESS,
        derived_driven=lambda flag: driven_leaves(
            getattr(LIVENESS[flag], "nodes", ()), liveness_nodes, leaves
        ),
    )
    assert complaints == [], "\n".join(complaints)


def test_the_ratchet_fires_when_the_count_falls_and_clears_when_the_floor_moves() -> None:
    """AC5's red control, both halves, on synthetic data.

    Half (i) alone proves only that the arm reads a count; half (ii) alone proves
    only that the floor is editable. Together they establish the intended
    property: coverage cannot fall silently, and LOWERING the bar is an edit
    somebody makes on the record. Raising it is free, and is what closing the
    carrier row looks like.
    """

    def registry(floor: int) -> Mapping[str, _Liveness]:
        return {
            "--a": _UnderDriven(
                nodes=("tests/x.py::t",),
                leaves=tuple(f"leaf{n}" for n in range(floor)),
                floor=floor,
                carrier="B-310",
                justification="because",
            )
        }

    fallen = frozenset({"leaf0", "leaf1"})
    complaints = ratchet_complaints(registry(3), derived_driven=lambda flag: fallen)
    assert any("--a" in one and "FELL to 2" in one and "floor of 3" in one for one in complaints), (
        complaints
    )

    assert ratchet_complaints(registry(2), derived_driven=lambda flag: fallen) == []
    assert ratchet_complaints(registry(3), derived_driven=lambda flag: fallen | {"leaf2"}) == []


# --------------------------------------------------------------------------- #
# Class (b) -- EMPTY after OR-18, and asserted empty AND constructible.
# --------------------------------------------------------------------------- #


def test_no_flag_is_marked_inert_by_design() -> None:
    """AC5a (i). After OR-18 the class is empty, and an empty class is ASSERTED
    rather than omitted -- otherwise the shape could be unrepresentable and
    nobody would find out (`tests/test_secret_leak_sweeps.py`'s exact defect)."""
    inert = sorted(flag for flag, entry in LIVENESS.items() if isinstance(entry, _InertByDesign))
    assert inert == [], (
        f"{inert} are marked INERT_BY_DESIGN. `--no-color` was the only candidate this "
        "product had and OR-18 REMOVED it rather than documenting it as a no-op; a new "
        "member needs its disclosure in the help text of every leaf that declares it"
    )


def test_inert_by_design_is_forbidden_on_threads_and_version() -> None:
    """The prohibition, asserted rather than trusted to a reviewer.

    Both flags are LIVE and the controls that prove it are named here so nobody
    re-derives them: `--threads 0` turns exit 0 into exit 2
    (`tests/integration/test_rasterize_cli.py::test_ac6_threads_out_of_range_exits_2`)
    and `--threads 1` vs `8` is asserted byte-identical at `text`; `--version`
    is eager and exits before any verb body, observed by
    `test_version_flag_reports_tool_python_and_engine_versions`. Marking either
    inert would ship a false marker at the version that turns help into a
    promise -- a P0 finding, not a judgement call.
    """
    for flag in ("--threads", "--version"):
        entry = LIVENESS.get(flag)
        assert entry is not None, f"{flag} left the liveness registry entirely"
        assert not isinstance(entry, _InertByDesign), (
            f"{flag} is marked INERT_BY_DESIGN and it is LIVE. This is a failed "
            "acceptance, not a judgement call"
        )


def test_a_synthetic_inert_by_design_member_classifies_and_reds_on_gaining_behaviour() -> None:
    """AC5a (ii). Half (i) alone is vacuous over an unbuildable shape; this half
    alone says nothing about the live population. Both are required.

    The disclosure discipline being generalised already ships at one verb:
    `tests/integration/test_text_tables_cli.py` asserts `text`'s help carries
    *"`--threads` is accepted but has NO effect"* and calls it *"a DECLARED
    no-op, not a silent one"*.
    """
    disclosure = "--pretend is accepted but has NO effect"
    registry = {"--pretend": _InertByDesign(disclosure=disclosure)}
    declared = frozenset({"one", "two"})
    disclosed = {"one": f"Usage: ... {disclosure}", "two": f"Usage: ... {disclosure}"}

    def check(driven: frozenset[str], helps: Mapping[str, str]) -> list[str]:
        return class_integrity_complaints(
            registry,
            declared_leaves=lambda flag: declared,
            derived_driven=lambda flag: driven,
            help_texts=lambda flag: helps,
        )

    # it CLASSIFIES: constructible, and passing its disclosure check
    assert check(frozenset(), disclosed) == []

    # it REDS when the flag gains behaviour
    gained = check(frozenset({"one"}), disclosed)
    assert any("--pretend" in one and "GAINED behaviour" in one for one in gained), gained

    # it REDS when a leaf's help text stops carrying the disclosure
    undisclosed = check(frozenset(), {"one": f"Usage: ... {disclosure}", "two": "Usage: ..."})
    assert any("--pretend" in one and "'two'" in one for one in undisclosed), undisclosed

    # and an empty disclosure is *inert by omission* wearing class (b)'s clothes
    blank = class_integrity_complaints(
        {"--pretend": _InertByDesign(disclosure="   ")},
        declared_leaves=lambda flag: declared,
        derived_driven=lambda flag: frozenset(),
        help_texts=lambda flag: disclosed,
    )
    assert any("EMPTY disclosure" in one for one in blank), blank


def test_the_declared_leaf_derivation_reads_the_live_tree() -> None:
    """The non-vacuity proof for `declared_leaves`: an empty return would make
    every BEHAVIOURAL comparison and every floor-versus-declared check above pass
    over nothing."""
    leaves = {verb.name for verb in discover_verbs()}
    for flag in GLOBAL_OPTIONS:
        assert declared_leaves(flag) == leaves, (
            f"{flag} is declared at {sorted(declared_leaves(flag))}, not at every leaf"
        )
    assert declared_leaves("--definitely-not-a-flag") == frozenset()


# --------------------------------------------------------------------------- #
# OR-18 -- the removal, pinned as a BEHAVIOUR rather than as an absence.
#
# A source grep proves the code is gone; only the CLI proves the CONTRACT is.
# The population is DERIVED -- the root rendering plus every live leaf, which is
# 27 and not the 26 the brief said -- so a twenty-seventh verb inherits both
# halves the day it is registered, and neither half is sufficient alone: (i) is
# satisfied by any misspelled flag, and (ii) would be satisfied by a flag that
# is hidden but still parses.
# --------------------------------------------------------------------------- #

#: Root, then every leaf, each already tokenized. `()` is the root position.
#: `VerbSpec.name` is the space-joined display string (`"meta get"`), and THIS
#: module's `run_cli` passes argv through unsplit -- so a position left joined
#: reaches the binary as one token, which is a usage error for the WRONG reason
#: ("No such command 'meta get'") and would have made the typed-flag half below
#: pass on two cells without ever reaching the flag. Measured, not reasoned.
REMOVED_COLOUR_POSITIONS: Final[tuple[tuple[str, ...], ...]] = (
    (),
    *(tuple(verb.name.split()) for verb in discover_verbs()),
)


def _position_id(position: tuple[str, ...]) -> str:
    return " ".join(position) if position else "root"


def test_the_removed_flag_population_covers_root_and_every_leaf() -> None:
    """The anti-lapse guard: a population that went vacuous would make both
    halves below pass over nothing."""
    assert len(REMOVED_COLOUR_POSITIONS) == len(discover_verbs()) + 1
    assert REMOVED_COLOUR_POSITIONS[0] == ()


@pytest.mark.e2e
@pytest.mark.parametrize("position", REMOVED_COLOUR_POSITIONS, ids=_position_id)
def test_the_removed_colour_flag_is_named_in_no_help_rendering(position: tuple[str, ...]) -> None:
    """AC6 (ii). `--no-color` was declared once and rendered 27 times, and every
    one of those renderings promised *"Disable ANSI styling; NO_COLOR is honoured
    too"* about a product that emits no ANSI at all. OR-18 removed the flag, and
    `v1.0.0` is the version at which a help text is a promise."""
    result = run_cli(*position, "--help")
    assert result.returncode == 0, result.stderr
    assert "--no-color" not in result.stdout, (
        f"{_position_id(position)} --help still names --no-color: a flag that suppresses "
        "colour this product has committed to never emitting has no implementable meaning"
    )
    assert "NO_COLOR" not in result.stdout, (
        f"{_position_id(position)} --help still names the NO_COLOR environment variable, "
        "which has had no consumer since OR-18"
    )


@pytest.mark.e2e
@pytest.mark.parametrize("position", REMOVED_COLOUR_POSITIONS, ids=_position_id)
def test_the_removed_colour_flag_is_an_unknown_flag_in_the_usage_envelope(
    position: tuple[str, ...],
) -> None:
    """AC6 (i). Not *accepted and ignored*, not *hidden but parseable*: UNKNOWN.

    Exit 2 carrying the envelope `README.md`'s output contract promises for an
    unknown flag -- an object on **stdout** in a structured shape -- so a machine
    consumer reading stdout learns the run failed without also reading stderr.

    **THE MESSAGE IS ASSERTED, AND THE REASON IS MEASURED.** With the flag
    restored in full, an exit-code-and-kind-only version of this arm stayed GREEN
    on 25 of the 27 positions: at every leaf that takes an operand the ARITY error
    (`Missing argument 'PDF...'`) is also a `usage` 2 on stdout, so the cell
    passed while the flag parsed perfectly. That is `tests/test_usage_envelope.py`
    line 635's decoy wearing a different hat, and the only thing that
    distinguishes the two is what the message says.
    """
    result = run_cli(*position, "--no-color", "-o", "json")
    assert result.returncode == exit_codes.USAGE, (
        f"{_position_id(position)}: --no-color exited {result.returncode}, not "
        f"{exit_codes.USAGE} -- it still parses somewhere"
    )
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == exit_codes.USAGE, payload
    assert payload["error"]["kind"] == "usage", payload
    assert "--no-color" in payload["error"]["message"], (
        f"{_position_id(position)}: the run failed, but not because of --no-color -- "
        f"{payload['error']['message']!r}. An exit code alone does not distinguish an "
        "UNKNOWN flag from a flag that parsed fine beside some other usage error"
    )
    assert "No such option" in payload["error"]["message"], payload
    assert result.stderr == "", f"a structured shape must leave stderr empty: {result.stderr!r}"


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
    from pdf_tooling.cli import common as cli_common

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

    from pdf_tooling.cli.main import app

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
    assert any("pdf-tooling" in line for line in lines)


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
#: STALE) `pdftooling` from PATH, or the `-m` bootstrap, and until PDF-29
#: nothing asserted which arm a startup measurement had actually used.
VENV_CONSOLE_SCRIPT = REPO_ROOT / ".venv" / "bin" / "pdftooling"

#: `quiet` == loadavg(1m) <= this fraction of the cpu count. The same definition
#: perf/README.md states and scripts/measure_gate.py enforces, so the test and
#: the protocol cannot drift into disagreeing about what "quiet" means.
QUIET_LOAD_FRACTION = 0.25


def test_no_engine_library_is_imported_at_module_scope() -> None:
    probe = (
        "import sys, pdf_tooling.cli.main;"
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

    **PDF-42 -- what carries the LATENCY half now, and why this test still
    abstains.** Section 6 as PDF-29 shipped it was blind to latency by
    construction: a module-scope `time.sleep(0.5)` in `cli/common.py` moved
    `pdftoolkit --help` from 227.0 ms to 728.7 ms while the import census stayed
    at 282 -- a delta of exactly 0 -- and every Section 6 node id reported
    passed. Section 6 now also spends the two timing columns `-X importtime`
    was already handing it and throwing away, and
    `test_no_single_module_costs_more_than_the_self_time_ceiling` is the
    assertion that plant fails.

    That control is in Section 6 precisely so it does NOT have to abstain, and
    `tests/test_gate_budget.py::test_the_section_six_roster_actually_ran_under_-
    the_default_parallelism` proves it RAN -- from a JUnit receipt of a real
    `-n auto` subprocess, not from an argument. **This test's abstention stays.**
    A wall-clock assertion inside a suite that saturates its own box is a
    contradiction rather than a tuning problem, and the answer to a control that
    abstains under the default condition is a control that does not have to --
    not un-skipping this one.
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
            f"possibly STALE PATH install ({shutil.which('pdftooling')}) and the `-m` "
            "bootstrap, whose startup path differs measurably. Run `uv sync`."
        )
    chosen = console_script()
    assert chosen == [str(VENV_CONSOLE_SCRIPT)], (
        f"console_script() resolved {chosen!r}, not the project venv's own "
        f"{str(VENV_CONSOLE_SCRIPT)!r}. A startup number from a different binary is a "
        "number about a different build -- `make install` leaves a global `pdftooling` "
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
    """PDF-48. The two CANONICAL spellings share one target. Before PDF-58
    the two deprecated spellings did NOT share it -- each pointed at its own
    shim in `cli/deprecated.py`. PDF-58 removes both deprecated keys and the
    module they pointed at, so now there are only the two canonical
    spellings left to compare, and pinning that is
    `test_the_console_script_declarations_are_exactly_the_two_key_shape`'s
    job."""
    project = load_pyproject()["project"]
    assert isinstance(project, dict)
    scripts = project["scripts"]
    assert isinstance(scripts, dict)
    assert scripts["pdftooling"] == scripts["pdf-tooling"] == "pdf_tooling.cli.main:main"


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
            name="pdf_tooling",
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


# --------------------------------------------------------------------------- #
# PDF-31 D6 — criteria-by-absence: assert what did NOT change
#
# The repository and the distribution moved; the import package, both console
# scripts, the corpus byte strings and the existing tags did not. Absence is
# asserted rather than assumed, because a blanket substitution over this tree
# would be wrong far more often than it is right, and the names above are what
# it would have corrupted.
# --------------------------------------------------------------------------- #


def test_the_console_script_declarations_are_exactly_the_two_key_shape() -> None:
    """PDF-58 AC1. `[project.scripts]` declares EXACTLY two keys, both pointed
    at the one canonical target. Renamed and inverted from PDF-48 AC5's
    `..._exactly_the_four_key_shape`, which pinned the two canonical spellings
    plus the two now-removed deprecated ones -- dropping the deprecated pair
    at `v1.0.0` is the breaking change PDF-48 promised and PDF-58 executes,
    not a tidy-up folded into a later rename.
    """
    project = load_pyproject()["project"]
    assert isinstance(project, dict)
    scripts = project["scripts"]
    assert set(scripts) == {"pdftooling", "pdf-tooling"}, (
        f"[project.scripts] declares {sorted(scripts)}; PDF-58 requires exactly the "
        "two canonical spellings, no fewer and no more -- the deprecated pair is gone"
    )
    assert scripts["pdftooling"] == scripts["pdf-tooling"] == "pdf_tooling.cli.main:main"
    assert set(scripts.values()) == {"pdf_tooling.cli.main:main"}, (
        f"more than one target is declared: {scripts}"
    )


def test_the_alias_arms_that_pin_it_still_exist_and_still_run() -> None:
    """PDF-48. The arm that would have to be DELETED to drop the canonical
    alias is asserted to still be present, by name.

    A criterion that only re-asserted the declaration would stay green while
    its own evidence was deleted underneath it; what makes the alias safe is
    that removing it costs a passing assertion, so that is what is pinned.
    """
    spine = Path(__file__).read_text()
    assert "def test_both_console_scripts_point_at_the_same_entry_point()" in spine
    assert 'alias = Path(sys.executable).parent / "pdf-tooling"' in spine, (
        "test_cli_spine.py's alias arm constructs the CONSOLE-SCRIPT path and must "
        "not be swept: it is character-identical in shape to the planning-dir "
        "fallback in test_docs_antirot.py and opposite in disposition"
    )


def test_the_import_package_is_now_pdf_tooling() -> None:
    """PDF-48 AC9. The distribution did not move; the import package did,
    behind its own deprecation window. Inverted from the pre-PDF-48 arm this
    replaces, which asserted `["pdf_toolkit"]`."""
    packages = sorted(
        p.name for p in (REPO_ROOT / "src").iterdir() if (p / "__init__.py").is_file()
    )
    assert packages == ["pdf_tooling"], f"src/ declares {packages}"
    import importlib

    assert importlib.import_module("pdf_tooling") is not None


# --------------------------------------------------------------------------- #
# PDF-58 D3/AC2/AC5/AC6/AC7 -- the two deprecated shims, REMOVED, driven.
#
# PDF-48 D2/AC6/AC7/AC8 shipped this section to prove the two deprecated
# shims behaved identically to the canonical scripts during the deprecation
# window. PDF-58 closes that window: `test_ac6_the_deprecated_alias_
# produces_byte_identical_stdout` and `test_ac7_the_deprecated_alias_
# matches_exit_codes_on_a_non_zero_case` tested BEHAVIOUR a shim no longer
# has, so there is nothing left for either to invert INTO -- both are
# replaced by the one absence arm below (D3's own "INVERTED (below)"
# disposition for both rows) plus a dedicated three-way module-absence arm
# for AC2. `pytest.skip` is forbidden in every arm here (AC6): the two
# skips this section used to carry (naming the deprecated alias by name and
# pointing at `uv sync`, twice) are REMOVED, not re-pointed -- an arm that
# cannot answer FAILS and names why, per D3.
# --------------------------------------------------------------------------- #


def _deprecated_alias_path(name: str) -> Path | None:
    """Resolve one of the two now-removed deprecated console scripts, mirroring
    `console_script()`'s own venv-sibling-first order. KEPT and REPURPOSED by
    PDF-58 as the absence prober below: deleting it would delete the only
    construct that can see a stale binary left over from before the removal."""
    sibling = Path(sys.executable).parent / name
    if sibling.exists():
        return sibling
    found = shutil.which(name)
    return Path(found) if found else None


def test_the_deprecated_console_scripts_are_absent_from_the_environment() -> None:
    """PDF-58 AC5. Absence, with a POSITIVE CONTROL FIRST. An arm that only
    asserts absence passes against a venv that was never built, a PATH that
    resolves nothing, and a helper that returns None for the wrong reason."""
    assert _deprecated_alias_path("pdftooling") is not None, (
        "the CANONICAL script does not resolve either -- this environment is "
        "stale or unbuilt, and an absence assertion over it proves nothing. "
        "Run `uv sync --reinstall`. This arm does NOT skip."
    )
    for name in ("pdftoolkit", "pdf-toolkit"):
        assert _deprecated_alias_path(name) is None, f"{name} still resolves"


def test_the_deprecated_shim_module_is_removed_three_ways() -> None:
    """PDF-58 AC2. `src/pdf_tooling/cli/deprecated.py` is removed with
    `git rm`, and its absence is asserted three ways: the file does not
    exist, `importlib.util.find_spec` cannot find it, and no module under
    `src/` imports it. Three, because the first alone passes over a stale
    `__pycache__` and the second alone passes over an uninstalled package."""
    module_path = REPO_ROOT / "src" / "pdf_tooling" / "cli" / "deprecated.py"
    assert not module_path.exists(), f"{module_path} still exists"

    import importlib.util

    assert importlib.util.find_spec("pdf_tooling.cli.deprecated") is None, (
        "pdf_tooling.cli.deprecated still resolves as an importable module"
    )

    importers = [
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "src").rglob("*.py")
        if "cli.deprecated" in path.read_text(encoding="utf-8")
        or "cli/deprecated" in path.read_text(encoding="utf-8")
    ]
    assert not importers, f"still referenced under src/: {importers}"


def test_ac6_no_inverted_deprecated_shim_arm_can_skip() -> None:
    """PDF-58 AC6. `pytest.skip` appears in neither replacement arm's source
    span. A skipped arm is never agreement (`scripts/assert_skips.py:58`-
    `:66`) -- if either arm cannot answer it must FAIL and name why, never
    skip. Scoped to the two arms' own spans, not the whole file: this
    module's section header comment quotes PDF-48's retired skip reason
    text for the historical record (prose, not a call), and a whole-file
    scan would also match this very assertion's own literal describing what
    it looks for -- the self-reference `test_brand_surfaces.py`'s module
    docstring warns about, in a different file's clothing."""
    spine = Path(__file__).read_text()
    for name in (
        "test_the_deprecated_console_scripts_are_absent_from_the_environment",
        "test_the_deprecated_shim_module_is_removed_three_ways",
    ):
        start = spine.index(f"def {name}(")
        end = spine.index("\n\n\ndef ", start)
        span = spine[start:end]
        assert "pytest.skip" not in span, f"{name} contains a forbidden pytest.skip"


def test_pdf58_the_deprecation_removal_sites_are_gone_from_the_three_code_places() -> None:
    """PDF-48 AC8, INVERTED by PDF-58. Three of the four sites PDF-48's
    `test_ac8_the_deprecation_window_is_stated_in_all_four_machine_read_
    places` pinned no longer exist as of this removal: the
    `[project.scripts]` block's own two-line deprecation comment, the
    `cli/deprecated.py` module (and its docstring and notice text with it).
    The fourth (README naming `v1.0.0` as the removal release) is Signal 2's
    own arm's job in `tests/test_docs_antirot.py`, not re-asserted here --
    two instruments pinning one proposition in two places is how they
    drift (AC13's own rule)."""
    pyproject_text = (REPO_ROOT / "pyproject.toml").read_text()
    scripts_block = pyproject_text.split("[project.scripts]", 1)[1].split("\n\n", 1)[0]
    assert "v1.0.0" not in scripts_block, (
        "[project.scripts]'s deprecation comment naming v1.0.0 is still present; "
        "PDF-58 removes it along with the two deprecated keys"
    )
    assert not (REPO_ROOT / "src" / "pdf_tooling" / "cli" / "deprecated.py").exists(), (
        "cli/deprecated.py still exists; its module docstring and notice text named "
        "v1.0.0 as the removal release and the whole module is removed by PDF-58"
    )


def test_the_corpus_and_golden_name_strings_are_byte_identical() -> None:
    """AC23. Class E — the corpus producer/title strings and the goldens that
    read them back. Changing either half without the other reddens the golden;
    changing both is churn with no user-facing meaning.

    This asserts the PRODUCER and the GOLDEN carry the same literal, so the
    pair cannot be swept in lockstep and pass silently.
    """
    info = json.loads((REPO_ROOT / "tests" / "golden" / "meta_get.json").read_text())["info"]
    assert info["Author"] == "pdf-toolkit test corpus"
    assert info["Producer"] == "pdf-toolkit test corpus"
    assert info["Title"] == "pdf-toolkit corpus: metadata_rich"
    assert info["Keywords"] == "pdf-toolkit,fixture,metadata"

    corpus = (REPO_ROOT / "tests" / "corpus.py").read_text()
    assert '"pdf-toolkit test corpus"' in corpus
    assert '"pdf-toolkit corpus: metadata_rich"' in corpus
    assert '"pdf-toolkit,fixture,metadata"' in corpus


def test_the_existing_release_tags_are_untouched() -> None:
    """AC25. History is not rewritten and the tags are neither moved nor
    re-pointed. The object ids are the ones recorded before the sweep.
    """
    frozen = {
        "v0.1.0": "7b17304809bda4625875f0491835e75c320aa0db",
        "v0.1.1": "816674b3eea4f991ced36701f6b4f2e28f826e03",
    }
    listed = subprocess.run(
        ["git", "tag", "--list"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if listed.returncode != 0:
        pytest.skip("git tag --list unavailable in this checkout")
    tags = set(listed.stdout.split())
    if not frozen.keys() <= tags:
        pytest.skip(
            f"tags absent from this checkout ({sorted(tags)}); a shallow or "
            "tagless clone cannot check that tags were not moved, and must not "
            "report that it did"
        )
    for tag, oid in frozen.items():
        got = subprocess.run(
            ["git", "rev-parse", f"{tag}^{{}}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert got == oid, f"{tag} points at {got}, not the recorded {oid}"
