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
from typing import Any, Final

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


def test_hiding_both_binaries_flips_exactly_two_rows(tmp_path: Path) -> None:
    """AC6's DISCRIMINATING arm (PDF-20). Appended, not a rewrite.

    `test_hiding_tesseract_flips_exactly_one_row` above only ever observes the
    value `1`, and a test that only ever sees one number cannot distinguish
    *"exactly one"* from *"at least one"* -- and "at least one" is the
    silent-wrong-answer reading of the product's own countable acceptance
    signal. This arm drives the same instrument to a DIFFERENT number, which is
    what makes the count assertion a count assertion.

    An empty `PATH` is correct here and wrong in the fixture above, for the same
    reason: it hides both system binaries. The CLI is still reachable because
    `run_cli` spawns through an absolute `sys.executable`.
    """
    empty = tmp_path / "nothing"
    empty.mkdir()
    env = {**os.environ, "PATH": str(empty)}
    report = doctor_json(env=env)

    assert len(report["ports"]) == 6, "the row count must not depend on what is installed"
    unavailable = [row["port"] for row in report["ports"] if not row["available"]]
    assert sorted(unavailable) == ["OcrEngine", "OfficeConverter"], unavailable
    assert run_cli("doctor", "--strict", env=env).returncode == 3
    assert run_cli("doctor", env=env).returncode == 0


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


def test_json_carries_the_items_alias_beside_ports() -> None:
    """PDF-39 D4 REVERSED this test's original claim, and the inversion is the
    record of it.

    It used to assert ``"items" not in doctor_json()`` on the ground that
    ``-o json``'s top level is a published contract and duplicating the six
    rows under a second key would be a shape nobody asked for. That judgement
    was reasonable and is overturned: the cost it avoided was one duplicated
    key; the cost it imposed was three spellings of one concept -- ``items``,
    ``documents`` on ``info``, ``ports`` here -- under one ``schema_version``,
    documented on no surface a consumer reads.

    ``ports`` is UNCHANGED and stays the published primary (``PLAN.md`` §3's
    own ``jq '.ports[]'`` example pins it, and X-410 forbids renaming it);
    ``items`` is an ADDITION beside it, and the two are the same list.
    ``tests/test_envelope_contract.py`` owns the equality across both verbs.
    """
    payload = doctor_json()
    assert payload["items"] == payload["ports"]


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


# --------------------------------------------------------------------------- #
# PDF-20 — B-100 / B-075: `doctor` is filesystem-pure on an engines-PRESENT
# host (AC19), and the sandbox that makes it so did not blind the probe (AC20a).
# Appended; nothing above is rewritten.
#
# THE CONDITION IS THE MEASUREMENT. `soffice --version` is what created
# `$HOME/.config`, so a host WITHOUT soffice reproduces B-100's own CONTROL
# ("`doctor` with soffice hidden is pure") rather than the defect. A pass there
# is the absence of the condition, not the presence of the fix, so the rows
# below SKIP WITH A REASON on such a host and are never marked passed.
# --------------------------------------------------------------------------- #

import sys as _sys  # noqa: E402

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in _sys.path:  # pragma: no cover - import plumbing
    _sys.path.insert(0, str(_TESTS_DIR))

from fs_snapshot import diff, redirected_environment, snapshot  # noqa: E402

#: The four invocations D3.4 requires for the B-075 exhaustivity claim. "We
#: fixed the one we knew about" is not an answer to a finding whose complaint
#: was that it had never been characterized.
PURITY_INVOCATIONS: Final = (
    ("doctor",),
    ("doctor", "--strict"),
    ("doctor", "--dry-run"),
    ("doctor", "-o", "json"),
)

#: The two ports whose probe SPAWNS. Without one of them resolvable there is no
#: probe-path spawn to be impure, so there is nothing here to prove.
SPAWNING_PORTS: Final = ("OcrEngine", "OfficeConverter")


def _purity_environment(base: Path) -> tuple[dict[str, str], tuple[Path, ...]]:
    """A redirected `$HOME`/`$TMPDIR` plus a scratch working tree as roots.

    `redirected_environment` is `tests/fs_snapshot.py`'s own helper -- the same
    one `test_c9`/`test_c10` use -- so this row and the contract rows cannot
    disagree about what "redirected" means. The working tree is added as a third
    root because a probe could equally have written beside the cwd, and the XDG
    variables are CLEARED so an operator's own `XDG_CONFIG_HOME` cannot route a
    write to a real directory outside the roots and out of sight.
    """
    env, roots = redirected_environment(base)
    for name in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        env.pop(name, None)
    tree = base / "tree"
    tree.mkdir(exist_ok=True)
    return env, (*roots, tree)


def _skip_unless_a_probe_spawns(report: dict[str, Any]) -> None:
    rows = {row["port"]: row["available"] for row in report["ports"]}
    if not any(rows.get(port) for port in SPAWNING_PORTS):
        pytest.skip(
            "engine-gated: neither system-binary port resolves, so no probe spawns and this "
            "host reproduces B-100's CONTROL rather than the defect -- a pass here would be "
            "the absence of the condition, not the presence of the fix"
        )


@pytest.mark.parametrize("argv", PURITY_INVOCATIONS, ids=[" ".join(a) for a in PURITY_INVOCATIONS])
def test_doctor_writes_nothing_on_an_engines_present_host(
    argv: tuple[str, ...], report: dict[str, Any], tmp_path: Path
) -> None:
    """AC19 / AC25. `ba07fdfb56` — every one of the four, not just `--dry-run`.

    The impurity was never dry-run-specific: `doctor` does nothing differently
    under `--dry-run` (it is ungoverned by OR-3 and is accepted and ignored), so
    the write happened on every invocation. Asserting all four is what makes the
    B-075 answer an exhaustivity claim rather than a spot check.
    """
    _skip_unless_a_probe_spawns(report)
    env, roots = _purity_environment(tmp_path)
    before = snapshot(*roots)
    result = run_cli(*argv, env=env)
    assert result.returncode == 0, f"{argv}: exit {result.returncode}: {result.stderr}"
    differences = diff(before, snapshot(*roots))
    assert differences == [], (
        f"`pdftoolkit {' '.join(argv)}` made {len(differences)} filesystem difference(s) "
        f"across {len(roots)} root(s): {[str(item) for item in differences]}"
    )
    assert not (Path(env["HOME"]) / ".config").exists(), (
        "$HOME/.config was created -- B-100 has regressed. The probe-path sandbox at "
        "adapters/subprocess_util.probe_env() is what stops the soffice version query "
        "writing into the operator's home."
    )


def test_the_sandbox_did_not_blind_the_probe(report: dict[str, Any], tmp_path: Path) -> None:
    """AC20(a). The D2.3 trap: a purity fix must not become a wrong answer.

    Run under a redirected `$HOME`, `doctor` must report exactly what it reports
    without one. Asserted as an EQUALITY against the unsandboxed report rather
    than as "all six available", so this row still discriminates on a host where
    an engine is genuinely missing.
    """
    _skip_unless_a_probe_spawns(report)
    env, _ = _purity_environment(tmp_path)
    sandboxed = doctor_json(env=env)
    plain = {
        row["port"]: (row["available"], row["version"], row["detail"]) for row in report["ports"]
    }
    under_home = {
        row["port"]: (row["available"], row["version"], row["detail"]) for row in sandboxed["ports"]
    }
    assert under_home == plain, (
        "the report changed when the probe environment changed -- a probe sandbox that "
        "strips PATH reports engines missing on a host that has them, with exit code 0"
    )
    for port in SPAWNING_PORTS:
        row = next(r for r in sandboxed["ports"] if r["port"] == port)
        if row["available"]:
            assert row["version"], f"{port} is available but its version no longer parses"


def test_the_probe_environment_inherits_everything_but_the_home_variables() -> None:
    """AC20(a)'s direct red control, and it is host-independent.

    The end-to-end arm above cannot fire for the trap D2.3 names on THIS host:
    `available` is decided by `shutil.which` against the PARENT's `PATH`, which
    the sandbox never touches, and `subprocess` falls back to `os.defpath`
    (`:/bin:/usr/bin`) when a child environment carries no `PATH` at all -- and
    both binaries live in `/usr/bin` here. So a helper that built a MINIMAL
    environment would leave every row unchanged on this machine and the
    prescribed red would not appear. This row asserts the property directly
    instead, where dropping the `os.environ` copy fails immediately, by name.
    """
    from pdf_toolkit.adapters.subprocess_util import (
        PROBE_HOME_VARIABLES,
        PROBE_SANDBOX_ROOT,
        probe_env,
    )

    base = {
        "PATH": "/usr/local/bin:/usr/bin",
        "TESSDATA_PREFIX": "/usr/share/tesseract-ocr/5/tessdata/",
        "LANG": "C.UTF-8",
        "HOME": "/home/someone",
        "XDG_CONFIG_HOME": "/home/someone/.config",
    }
    prepared = probe_env(base)
    for name in ("PATH", "TESSDATA_PREFIX", "LANG"):
        assert prepared[name] == base[name], (
            f"{name} did not survive the probe sandbox. `run()`'s `env` REPLACES the child "
            "environment wholesale, so a minimal env silently stops the binaries resolving "
            "and `doctor` reports engines missing on a host that has them"
        )
    for name in PROBE_HOME_VARIABLES:
        assert prepared[name] == PROBE_SANDBOX_ROOT, name
    assert set(prepared) == set(base) | set(PROBE_HOME_VARIABLES)


def test_the_probe_sandbox_root_cannot_be_created() -> None:
    """Zero net effect BY CONSTRUCTION, which is stronger than by cleanup.

    A scratch directory that is made and removed still moves its parent's mtime,
    and `tests/fs_snapshot.py` records directory mtime -- so a sweep-based
    sandbox trades `$HOME/.config` appearing for `$TMPDIR`'s mtime moving, and
    AC19 above would still be red. A path beneath the null device is not a
    directory anything can create, so there is nothing to clean up and nothing
    that can fail while cleaning up.
    """
    from pdf_toolkit.adapters.subprocess_util import PROBE_SANDBOX_ROOT

    if not os.path.isabs(os.devnull):  # pragma: no cover - POSIX hosts only
        pytest.skip(f"platform-gated: os.devnull is {os.devnull!r}, not an absolute path")
    assert PROBE_SANDBOX_ROOT.startswith(os.devnull + os.sep)
    assert not Path(PROBE_SANDBOX_ROOT).exists()
    with pytest.raises(OSError):
        Path(PROBE_SANDBOX_ROOT).mkdir(parents=True)
    assert not Path(PROBE_SANDBOX_ROOT).exists()
