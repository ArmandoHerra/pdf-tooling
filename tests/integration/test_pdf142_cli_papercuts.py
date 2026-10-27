"""PDF-142 -- four CLI surfaces that said something untrue, now say what is true.

The four ledger fingerprints, each pinned by its own nodes:

* ``e6a143a5b7`` (B-439): ``merge --help`` documented a ``--fail-fast`` that no
  verb declares. The sentence is gone; the flag is still NOT implemented
  (AC1-AC3).
* ``7c931ce9b2`` (B-462): ``compress`` printed a shrink as ``+97.8%`` and a
  growth as ``-10.1%``. The message now carries the signed size change
  (AC4, AC10).
* ``ea69b6206e`` (B-463): ``merge`` said ``1 pages selected`` (AC6).
* ``bab46d5ef8`` (B-479): ``--quiet``'s help said "Report only errors on
  stderr." while result ``warning:`` lines still print. Per operator ruling
  OR-56 only the HELP TEXT changed; stderr under ``--quiet`` is byte-unchanged
  (AC8, AC9).

Help text is compared normalised (whitespace collapsed), so no assertion
depends on where the formatter wraps. Click is vendored as ``typer._click``:
introspection goes through ``typer.main.get_command``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pikepdf
import pytest
import typer.main

from pdf_tooling.cli.main import app
from registry import console_script, discover_verbs, run_cli

VERBS = discover_verbs()

QUIET_HELP = (
    "Hide log records below ERROR on stderr; errors and the result's 'warning:' lines still print."
)
OLD_QUIET_HELP_COLLAPSED = "Reportonlyerrorsonstderr."


def norm(text: str) -> str:
    return " ".join(text.split())


def squash(text: str) -> str:
    return "".join(text.split())


def _env(columns: int) -> dict[str, str]:
    return {**os.environ, "COLUMNS": str(columns)}


def _blank(path: Path, pages: int, title: str | None = None) -> None:
    pdf = pikepdf.new()
    for _ in range(pages):
        pdf.add_blank_page()
    if title:
        pdf.docinfo["/Title"] = title
    pdf.save(path)


def _big(path: Path) -> None:
    pdf = pikepdf.new()
    for _ in range(20):
        pdf.add_blank_page()
        pdf.pages[-1].obj.Contents = pdf.make_indirect(
            pikepdf.Stream(pdf, b"0 0 m 100 100 l S\n" * 400)
        )
    pdf.save(
        path,
        compress_streams=False,
        object_stream_mode=pikepdf.ObjectStreamMode.disable,
    )


def _merge_help(columns: int) -> str:
    result = run_cli("merge", "--help", env=_env(columns))
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("columns", [40, 80, 200])
def test_ac1_merge_help_documents_no_fail_fast(columns: int) -> None:
    text = _merge_help(columns)
    flat = squash(text)
    assert flat.count("--fail-fast") == 0, (
        f"merge --help at COLUMNS={columns}: "
        f"--fail-fast count {flat.count('--fail-fast')}, expected 0"
    )
    assert flat.count("isconsequentlyano-opformerge") == 0
    assert "a wrong document that looks right." in norm(text)


def test_ac2_every_option_merge_help_names_is_declared() -> None:
    text = _merge_help(200)
    named = set(re.findall(r"--[a-z][a-z0-9-]*", text)) - {"--help"}
    merge_cmd = typer.main.get_command(app).commands["merge"]  # type: ignore[attr-defined]
    declared: set[str] = set()
    for param in merge_cmd.params:
        declared.update(param.opts)
        declared.update(param.secondary_opts)
    undeclared = named - declared
    assert undeclared == set(), f"merge --help names undeclared options: {undeclared}"


def test_ac3_fail_fast_is_still_an_unknown_option(tmp_path: Path) -> None:
    _blank(tmp_path / "a.pdf", 1)
    _blank(tmp_path / "d.pdf", 3)
    result = run_cli(
        "merge", "a.pdf", "d.pdf", "-O", "m.pdf", "--fail-fast", "-o", "json", cwd=tmp_path
    )
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == 2
    assert payload["error"]["kind"] == "usage"
    assert not (tmp_path / "m.pdf").exists()


@pytest.mark.parametrize("case", ["shrink", "grow", "equal"])
def test_ac4_compress_message_sign_follows_the_size_change(tmp_path: Path, case: str) -> None:
    if case == "shrink":
        _big(tmp_path / "in.pdf")
        args = ("compress", "in.pdf", "-O", "out.pdf", "-o", "json")
    elif case == "grow":
        _blank(tmp_path / "in.pdf", 1)
        args = ("compress", "in.pdf", "-O", "out.pdf", "-o", "json")
    else:
        _big(tmp_path / "big.pdf")
        first = run_cli("compress", "big.pdf", "-O", "in.pdf", "-o", "json", cwd=tmp_path)
        assert first.returncode == 0, first.stderr
        args = ("compress", "in.pdf", "-O", "out.pdf", "-o", "json")
    result = run_cli(*args, cwd=tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    row = json.loads(result.stdout)["items"][0]
    before, after = row["bytes_before"], row["bytes_after"]
    if case == "shrink":
        assert after < before, f"shrink fixture did not shrink: {before} -> {after}"
    elif case == "grow":
        assert after > before, f"grow fixture (1 blank page) did not grow: {before} -> {after}"
    else:
        assert after == before, f"equal fixture changed size: {before} -> {after}"
    message = row["message"]
    assert message == f"{before} -> {after} bytes ({(after - before) / before * 100:+.1f}%)"
    if case == "shrink":
        assert "(-" in message and "(+" not in message
    elif case == "grow":
        assert "(+" in message and "(-" not in message
    else:
        assert message.endswith("(+0.0%)")


@pytest.mark.parametrize("mode", ["real-json", "real-table", "dry-json"])
def test_ac6_merge_says_page_for_one_page(tmp_path: Path, mode: str) -> None:
    _blank(tmp_path / "a.pdf", 1)
    _blank(tmp_path / "d.pdf", 3)
    args = ["merge", "a.pdf", "d.pdf", "-O", "m.pdf"]
    if mode == "dry-json":
        args.insert(0, "--dry-run")
    args += ["-o", "table" if mode == "real-table" else "json"]
    result = run_cli(*args, cwd=tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    if mode == "real-table":
        assert "1 page selected" in result.stdout
        assert "3 pages selected" in result.stdout
        assert "1 pages selected" not in result.stdout
        return
    messages = [row["message"] for row in json.loads(result.stdout)["items"]]
    assert messages == ["1 page selected", "3 pages selected"], messages


@pytest.mark.parametrize("columns", [40, 200])
def test_ac8_quiet_help_says_result_warnings_stay_visible(columns: int) -> None:
    helps = [("<root>", ["--help"])] + [(verb.name, [verb.name, "--help"]) for verb in VERBS]
    assert len(helps) == 1 + len(VERBS)
    for label, argv in helps:
        result = run_cli(*argv, env=_env(columns))
        assert result.returncode == 0, (label, result.stderr)
        assert f"-q, --quiet {QUIET_HELP}" in norm(result.stdout), (
            f"{label} --help at COLUMNS={columns} lacks the new --quiet sentence"
        )
        assert OLD_QUIET_HELP_COLLAPSED not in squash(result.stdout), (
            f"{label} --help at COLUMNS={columns} still contains {OLD_QUIET_HELP_COLLAPSED}"
        )


def test_ac9_quiet_leaves_result_warnings_on_stderr_byte_for_byte(tmp_path: Path) -> None:
    _blank(tmp_path / "chapter1.pdf", 1)
    _blank(tmp_path / "chapter2.pdf", 1, "Chapter 2")
    expected = (
        b"warning: chapter2.pdf: merge does not carry the input's document /Info to its output\n"
    )

    def stderr_of(*extra: str, out: str) -> bytes:
        proc = subprocess.run(
            [
                *console_script(),
                "merge",
                "chapter1.pdf",
                "chapter2.pdf",
                "-O",
                out,
                *extra,
                "-o",
                "json",
            ],
            cwd=tmp_path,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        return proc.stderr

    quiet = stderr_of("--quiet", out="m1.pdf")
    loud = stderr_of(out="m2.pdf")
    assert quiet == expected, quiet
    assert loud == quiet


def test_ac10_compress_help_states_the_signed_change() -> None:
    result = run_cli("compress", "--help", env=_env(200))
    assert result.returncode == 0, result.stderr
    text = norm(result.stdout)
    assert text.count("percentage rendered as negative or zero") == 0
    assert text.count("size change rendered as zero or positive") == 1
