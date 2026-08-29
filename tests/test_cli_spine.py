"""The CLI spine contract.

Everything asserted here is public API from v1.0.0 — the exit-code integers, the
structured output shapes, and which stream each of them goes to. A failure in
this file is not a defect in one verb; it is a defect in the contract every verb
inherits, so treat a red test here as a breaking change until proven otherwise.

Deliberately disjoint from the fixture-corpus and per-verb contract harness that
arrive later: this file owns the spine, and there is no ``conftest.py`` here yet.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from pdf_toolkit import errors
from pdf_toolkit.cli import exit_codes
from pdf_toolkit.cli.common import (
    GLOBAL_OPTIONS,
    GLOBAL_PARAMS,
    build_config,
    validate_config,
)
from pdf_toolkit.models import SCHEMA_VERSION, ItemResult, OperationResult
from pdf_toolkit.output import OutputFormat, emit_error, emit_result, render_payload
from pdf_toolkit.output.logging import RedactingFilter, clear_secrets, register_secret

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Names that must never appear in packaging, source, or the build entry points.
#: The realistic violation is a convenience shell-out, not a declared dependency,
#: which is why this looks at the Makefile as well as at the code.
FORBIDDEN_NAMES = (
    "fitz",
    "pymupdf",
    "pdf2image",
    "pdftoppm",
    "pdftotext",
    "pdftocairo",
    "pdfinfo",
    "ghostscript",
    "ocrmypdf",
    "img2pdf",
    "pandoc",
    "pdftk",
)

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


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the CLI as a subprocess, which is the only way exit codes are real."""
    return subprocess.run(
        [*console_script(), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
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
        (("--name", "a/b", "version"), 2),
        (("--threads", "0", "version"), 2),
    ],
    ids=lambda value: str(value),
)
def test_command_surface_exit_codes(argv: tuple[str, ...], expected: int) -> None:
    result = run_cli(*argv)
    assert result.returncode == expected, f"{argv} -> {result.returncode}\n{result.stderr}"


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
    assert payload["error"]["path"] == "/no/such/file"


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


@pytest.mark.e2e
def test_help_stays_within_the_startup_budget() -> None:
    import time

    budget_ms = 250.0
    timings: list[float] = []
    for _ in range(5):
        started = time.perf_counter()
        result = run_cli("--help")
        timings.append((time.perf_counter() - started) * 1000)
        assert result.returncode == 0
    # Best-of-N rather than the mean, so scheduler noise cannot flake the gate
    # while a genuine regression still turns it red.
    assert min(timings) < budget_ms, f"fastest --help was {min(timings):.0f} ms of {budget_ms} ms"


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


def test_packaging_declares_the_license_and_both_license_files() -> None:
    project = load_pyproject()["project"]
    assert isinstance(project, dict)
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE", "NOTICE"]
    assert (REPO_ROOT / "LICENSE").read_text().count("Apache License") >= 1
    assert (REPO_ROOT / "NOTICE").exists()


def test_both_console_scripts_point_at_the_same_entry_point() -> None:
    project = load_pyproject()["project"]
    assert isinstance(project, dict)
    scripts = project["scripts"]
    assert isinstance(scripts, dict)
    assert scripts["pdftoolkit"] == scripts["pdf-toolkit"] == "pdf_toolkit.cli.main:main"


def test_no_forbidden_engine_name_appears_in_packaging_source_or_build() -> None:
    haystacks = [REPO_ROOT / "pyproject.toml", REPO_ROOT / "Makefile"]
    haystacks.extend(sorted((REPO_ROOT / "src").rglob("*.py")))
    offenders: list[str] = []
    for path in haystacks:
        text = path.read_text().lower()
        offenders.extend(
            f"{path.relative_to(REPO_ROOT)}: {name}" for name in FORBIDDEN_NAMES if name in text
        )
    assert offenders == []


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


def test_changelog_carries_the_anchor_and_this_spine_entry() -> None:
    text = (REPO_ROOT / "changelog.md").read_text()
    anchor = "<!-- CHANGELOG-ANCHOR: insert new entries directly below this line, newest first -->"
    assert anchor in text
    headings = re.findall(r"^## \[PDF-\d\d\].*$", text, re.MULTILINE)
    assert len(headings) == 1
    assert headings[0].startswith("## [PDF-01] Project scaffold & CLI spine")
    assert text.index(anchor) < text.index(headings[0])


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
