"""``doctor`` end to end — the countable acceptance signal.

Run as a **subprocess** throughout, because an exit code observed inside the
test process is a return value, not an exit code, and because the central
assertion here manipulates ``PATH`` for one invocation.

THE COUNT IS THE CONTRACT
-------------------------
*Exactly six* rows, and — with ``tesseract`` hidden — *exactly one* unavailable.
Both are asserted as **counts**, not by reading output, because the failure this
guards against is a seventh row quietly appearing (a Phase-2 adapter added
early, a secondary promoted to a row of its own) or a missing engine vanishing
from the report instead of appearing as ``available:false``.

THE ``PATH`` MECHANIC, WHICH IS EASY TO GET WRONG
-------------------------------------------------
Blanking ``PATH`` hides ``tesseract`` **and** ``soffice`` and flips **two** rows,
which fails the count. The construction that flips exactly one is a temp
directory containing only a ``soffice`` symlink, used as the whole ``PATH``.
The CLI is invoked through an absolute interpreter path so that gutting ``PATH``
does not also make the tool itself unfindable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_PORTS = (
    "StructureEngine",
    "RasterEngine",
    "ComposeEngine",
    "TextEngine",
    "OcrEngine",
    "OfficeConverter",
)


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the CLI as a subprocess through an absolute interpreter path.

    ``sys.executable`` is absolute, so this keeps working when ``PATH`` has been
    replaced by a one-entry shim directory — which is exactly what the
    acceptance-signal test does.
    """
    return subprocess.run(
        [sys.executable, "-m", "pdf_toolkit", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        env=env,
    )


def doctor_json(*args: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    result = run_cli("doctor", "-o", "json", *args, env=env)
    assert result.stdout, f"doctor produced no stdout (exit {result.returncode}): {result.stderr}"
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    return doctor_json()


def all_engines_present(report: dict[str, Any]) -> bool:
    return all(row["available"] for row in report["ports"])


# --------------------------------------------------------------------------- #
# Shape and count.
# --------------------------------------------------------------------------- #


def test_doctor_reports_exactly_six_ports(report: dict[str, Any]) -> None:
    assert len(report["ports"]) == 6


def test_the_six_are_the_right_six_in_the_right_order(report: dict[str, Any]) -> None:
    assert tuple(row["port"] for row in report["ports"]) == EXPECTED_PORTS


def test_no_seventh_row_exists_for_the_phase_two_html_engine(report: dict[str, Any]) -> None:
    """WeasyPrint is the ``[html]`` extra and Phase 2; it has no v1 row."""
    adapters = {row["adapter"] for row in report["ports"]}
    assert "weasyprint" not in adapters
    kinds = {row["kind"] for row in report["ports"]}
    assert "optional-extra" not in kinds
    assert kinds <= {"python-package", "system-binary"}


def test_every_row_carries_the_keys_a_consumer_reads(report: dict[str, Any]) -> None:
    for row in report["ports"]:
        assert row["port"]
        assert isinstance(row["available"], bool)
        assert row["kind"]
        assert "version" in row, "the key must exist even when the value is null"
        assert "adapter" in row
        assert "detail" in row
        assert "hint" in row


def test_the_envelope_is_the_published_shape(report: dict[str, Any]) -> None:
    """``.ports[]`` is fixed by ``PLAN.md`` §3's own ``jq`` example."""
    assert report["schema_version"] == 1
    assert report["verb"] == "doctor"
    assert isinstance(report["ports"], list)


def test_the_structure_row_names_its_secondary(report: dict[str, Any]) -> None:
    row = next(r for r in report["ports"] if r["port"] == "StructureEngine")
    assert row["adapter"] == "pypdf"
    assert row["detail"] is not None
    assert "pikepdf" in row["detail"]


def test_the_text_row_names_its_fast_path(report: dict[str, Any]) -> None:
    row = next(r for r in report["ports"] if r["port"] == "TextEngine")
    assert row["adapter"] == "pdfplumber"
    assert row["detail"] is not None
    assert "pypdfium2" in row["detail"]


def test_hints_appear_exactly_when_a_row_is_unavailable(report: dict[str, Any]) -> None:
    """Asserted over all six rows, in whichever configuration this host is in."""
    for row in report["ports"]:
        if row["available"]:
            assert row["hint"] is None, f"{row['port']} is available but carries a hint"
        else:
            assert row["hint"], f"{row['port']} is unavailable with no install hint"


# --------------------------------------------------------------------------- #
# Exit codes.
# --------------------------------------------------------------------------- #


def test_plain_doctor_exits_zero_whatever_is_installed() -> None:
    assert run_cli("doctor").returncode == 0


def test_strict_exits_zero_when_every_engine_is_present(report: dict[str, Any]) -> None:
    if not all_engines_present(report):
        missing = [row["port"] for row in report["ports"] if not row["available"]]
        pytest.skip(f"engine-gated: this host is missing {', '.join(missing)}")
    assert run_cli("doctor", "--strict").returncode == 0


def test_strict_lists_stray_temp_files_and_plain_does_not(report: dict[str, Any]) -> None:
    """Reported, never swept — and the key is absent unless ``--strict`` asked."""
    assert "stray_temp_files" not in report
    strict = doctor_json("--strict")
    assert isinstance(strict["stray_temp_files"], list)


# --------------------------------------------------------------------------- #
# THE acceptance signal: hide one engine, flip exactly one row.
# --------------------------------------------------------------------------- #


@pytest.fixture
def soffice_only_path(tmp_path: Path) -> str:
    """A ``PATH`` containing ``soffice`` and nothing else.

    Deliberately not an empty ``PATH``: that would hide both system binaries and
    flip two rows, which fails the "exactly one" count for the wrong reason.
    """
    located = shutil.which("soffice")
    if located is None:
        pytest.skip("engine-gated: soffice is not installed, so only one row could flip anyway")
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "soffice").symlink_to(located)
    return str(shim)


def test_hiding_tesseract_flips_exactly_one_row(soffice_only_path: str) -> None:
    env = {**os.environ, "PATH": soffice_only_path}
    report = doctor_json(env=env)

    assert len(report["ports"]) == 6, "the row count must not depend on what is installed"
    unavailable = [row for row in report["ports"] if not row["available"]]
    assert len(unavailable) == 1, [row["port"] for row in unavailable]
    assert unavailable[0]["port"] == "OcrEngine"
    assert unavailable[0]["hint"], "an unavailable row with no hint is the defect this guards"
    assert unavailable[0]["hint"].strip() != ""


def test_hints_are_still_exactly_right_with_an_engine_hidden(soffice_only_path: str) -> None:
    env = {**os.environ, "PATH": soffice_only_path}
    for row in doctor_json(env=env)["ports"]:
        assert bool(row["hint"]) is not bool(row["available"]), row["port"]


def test_strict_exits_three_when_an_engine_is_hidden_and_plain_still_exits_zero(
    soffice_only_path: str,
) -> None:
    env = {**os.environ, "PATH": soffice_only_path}
    assert run_cli("doctor", "--strict", env=env).returncode == 3
    assert run_cli("doctor", env=env).returncode == 0


# --------------------------------------------------------------------------- #
# Honest language enumeration.
# --------------------------------------------------------------------------- #


def _installed_languages() -> tuple[str, ...]:
    """Ask the binary directly, so the expectation is not a hardcoded host fact."""
    located = shutil.which("tesseract")
    if located is None:
        return ()
    result = subprocess.run([located, "--list-langs"], capture_output=True, text=True, check=False)
    lines = [line.strip() for line in (result.stdout or result.stderr).splitlines() if line.strip()]
    return tuple(sorted({line for line in lines[1:] if " " not in line}))


def test_the_ocr_row_enumerates_the_languages_that_are_actually_installed(
    report: dict[str, Any],
) -> None:
    """Derived from the binary, never hardcoded — the claim is "what is there".

    A test that asserted a fixed language set would be asserting a property of
    this laptop, and would go red on a CI image with a different tessdata
    package for a reason that is not a defect.
    """
    row = next(r for r in report["ports"] if r["port"] == "OcrEngine")
    if not row["available"]:
        pytest.skip("engine-gated: tesseract is not installed")

    installed = _installed_languages()
    assert installed, "tesseract is present but reported no languages at all"
    detail = row["detail"] or ""
    assert "languages:" in detail
    for language in installed:
        assert language in detail, f"{language} is installed but missing from detail: {detail!r}"


def test_the_ocr_row_claims_no_language_that_is_not_installed(report: dict[str, Any]) -> None:
    """Honest degradation, asserted negatively as well as positively."""
    row = next(r for r in report["ports"] if r["port"] == "OcrEngine")
    if not row["available"]:
        pytest.skip("engine-gated: tesseract is not installed")

    installed = set(_installed_languages())
    detail = row["detail"] or ""
    listed = detail.split("languages:", 1)[1].split(";", 1)[0]
    absent = [code for code in ("spa", "deu", "fra", "jpn") if code not in installed]
    assert absent, "every probe language happens to be installed; nothing to assert negatively"
    for code in absent:
        assert code not in listed, f"detail advertises {code}, which is not installed"


# --------------------------------------------------------------------------- #
# The other two renderers.
# --------------------------------------------------------------------------- #


def test_ndjson_streams_one_row_per_port_with_no_envelope() -> None:
    result = run_cli("doctor", "-o", "ndjson")
    assert result.returncode == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 6
    records = [json.loads(line) for line in lines]
    assert [record["port"] for record in records] == list(EXPECTED_PORTS)
    for record in records:
        assert record["schema_version"] == 1, "every streamed line is self-describing"
        assert record["verb"] == "doctor"


def test_json_carries_no_redundant_items_alias() -> None:
    """The alias exists for the streaming renderers and is withheld from ``-o json``.

    ``-o json``'s top level is a published contract; duplicating the six rows
    under a second key to satisfy a renderer would be a shape nobody asked for.
    """
    assert "items" not in doctor_json()


def test_table_output_names_the_columns_a_human_reads() -> None:
    result = run_cli("doctor", "-o", "table")
    assert result.returncode == 0
    header = result.stdout.splitlines()[0]
    for column in ("port", "adapter", "available", "version", "kind"):
        assert column in header, header
    assert len([line for line in result.stdout.splitlines() if line.strip()]) == 8


def test_doctor_writes_the_payload_to_stdout_and_nothing_else_there() -> None:
    result = run_cli("doctor", "-o", "json")
    json.loads(result.stdout)  # parses, therefore stdout is the payload alone


def test_doctor_appears_in_help() -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    assert "doctor" in result.stdout
