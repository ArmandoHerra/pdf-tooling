"""AC9, AC18, AC19, AC21, AC30 — the remaining CLI-level surface for
``merge``/``split``: escape exit codes, dry-run purity for all five paths,
the usage/safety rejection matrix, structured output shape, and OR-3's own
evidence line inverted.

Every test here runs the installed console script as a subprocess (the only
way exit codes, "no traceback" and non-TTY posture are observable at all).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from fs_snapshot import assert_unchanged, redirected_environment, snapshot  # noqa: E402
from registry import run_cli  # noqa: E402

pytestmark = pytest.mark.e2e


def _make_source(directory: Path, pages: int, *, name: str = "src.pdf") -> Path:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    made = canvas.Canvas(str(path), pagesize=letter)
    for number in range(1, pages + 1):
        made.drawString(72, 700, f"src page {number}")
        made.showPage()
    made.save()
    return path


def _outlined_source(directory: Path, pages: int) -> Path:
    """A source with a top-level outline, so --at-bookmarks has one to use."""
    from pypdf import PdfReader, PdfWriter

    base = _make_source(directory, pages, name="base.pdf")
    reader = PdfReader(str(base))
    writer = PdfWriter()
    writer.append(reader)
    writer.add_outline_item("first", 0)
    writer.add_outline_item("second", pages // 2)
    outlined = directory / "outlined.pdf"
    with open(outlined, "wb") as handle:
        writer.write(handle)
    return outlined


# --------------------------------------------------------------------------- #
# AC9 -- escape attempts have specified exit codes
# --------------------------------------------------------------------------- #


def test_name_literal_traversal_is_exit_2_nothing_written(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=2)
    out_dir = tmp_path / "parts"
    result = run_cli(
        "split", str(source), "--each-page", "--name", "../{page}.pdf", "--out-dir", str(out_dir)
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert not out_dir.exists()


def test_name_literal_absolute_leading_slash_is_exit_2(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=2)
    out_dir = tmp_path / "parts"
    result = run_cli(
        "split", str(source), "--each-page", "--name", "/tmp/{page}.pdf", "--out-dir", str(out_dir)
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert not out_dir.exists()


def test_a_greater_than_255_byte_component_is_exit_5_not_an_oserror_traceback(
    tmp_path: Path,
) -> None:
    """A real 300-byte filename cannot exist on disk in the first place
    (ext4's own 255-byte-per-component limit), so the over-length component
    is produced by a long TEMPLATE LITERAL instead -- `_validate_name_
    template` (exit 2) checks only emptiness/separators/`..`, never length,
    so this reaches naming.py's exit-5 tier exactly as a long substituted
    `{stem}` would."""
    source = _make_source(tmp_path / "src", pages=1)
    out_dir = tmp_path / "parts"
    long_literal = "p" * 300
    result = run_cli(
        "split",
        str(source),
        "--each-page",
        "--name",
        f"{long_literal}-{{page}}.{{ext}}",
        "--out-dir",
        str(out_dir),
    )
    assert result.returncode == 5
    assert "Traceback" not in result.stderr
    assert not out_dir.exists() or list(out_dir.iterdir()) == []


# --------------------------------------------------------------------------- #
# AC18 -- --dry-run purity for all five paths
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--every", "2"],
        ["--ranges", "1-2,3-4"],
        ["--each-page"],
        ["--at-bookmarks"],
    ],
    ids=["every", "ranges", "each-page", "at-bookmarks"],
)
def test_split_dry_run_purity_across_all_four_modes(tmp_path: Path, extra_args: list[str]) -> None:
    source = _outlined_source(tmp_path / "src", pages=4)
    out_dir = tmp_path / "never-created"
    env, roots = redirected_environment(tmp_path)
    before = snapshot(*roots, source.parent)
    result = run_cli(
        "split",
        str(source),
        *extra_args,
        "--out-dir",
        str(out_dir),
        "--dry-run",
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert not out_dir.exists()
    assert_unchanged(before, snapshot(*roots, source.parent))
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert len(payload["items"]) >= 1
    for item in payload["items"]:
        assert item["output"]


def test_merge_dry_run_purity(tmp_path: Path) -> None:
    a = _make_source(tmp_path / "a", pages=2)
    b_dir = tmp_path / "b"
    b = _make_source(b_dir, pages=2, name="b.pdf")
    output = tmp_path / "out.pdf"
    env, roots = redirected_environment(tmp_path)
    before = snapshot(*roots, tmp_path)
    result = run_cli("merge", str(a), str(b), "-O", str(output), "--dry-run", env=env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert not output.exists()
    assert_unchanged(before, snapshot(*roots, tmp_path))


# --------------------------------------------------------------------------- #
# AC19 -- usage and safety rejections
# --------------------------------------------------------------------------- #


def test_split_zero_mode_flags_is_exit_2(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=1)
    result = run_cli("split", str(source), "--out-dir", str(tmp_path / "out"))
    assert result.returncode == 2


def test_split_two_mode_flags_is_exit_2(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=4)
    result = run_cli(
        "split", str(source), "--every", "2", "--each-page", "--out-dir", str(tmp_path / "out")
    )
    assert result.returncode == 2


def test_directory_argument_is_exit_2_for_merge_and_split(tmp_path: Path) -> None:
    directory = tmp_path / "adir"
    directory.mkdir()
    merge_result = run_cli("merge", str(directory), "-O", str(tmp_path / "out.pdf"))
    assert merge_result.returncode == 2
    split_result = run_cli("split", str(directory), "--each-page", "--out-dir", str(tmp_path / "o"))
    assert split_result.returncode == 2


def test_existing_target_without_force_is_exit_5_including_a_dangling_symlink(
    tmp_path: Path,
) -> None:
    import os

    source = _make_source(tmp_path / "src", pages=1)

    real_target = tmp_path / "already-real.pdf"
    real_target.write_bytes(b"%PDF-1.4\n%%EOF\n")
    result = run_cli("merge", str(source), "-O", str(real_target))
    assert result.returncode == 5

    dangling = tmp_path / "dangling.pdf"
    os.symlink(tmp_path / "does-not-exist-target", dangling)
    result = run_cli("merge", str(source), "-O", str(dangling))
    assert result.returncode == 5


def test_merge_bulk_force_over_existing_non_tty_no_y_is_exit_5_with_rerun_command(
    tmp_path: Path,
) -> None:
    a = _make_source(tmp_path / "a", pages=1)
    b = _make_source(tmp_path / "b", pages=1, name="b.pdf")
    target = tmp_path / "existing.pdf"
    target.write_bytes(b"%PDF-1.4\n%%EOF\n")

    refused = run_cli("merge", str(a), str(b), "-O", str(target), "--force")
    assert refused.returncode == 5
    combined = refused.stdout + refused.stderr
    assert "-y" in combined

    confirmed = run_cli("merge", str(a), str(b), "-O", str(target), "--force", "-y")
    assert confirmed.returncode == 0, confirmed.stderr


# --------------------------------------------------------------------------- #
# AC21 -- structured output
# --------------------------------------------------------------------------- #


def test_merge_json_output_has_one_item_per_input(tmp_path: Path) -> None:
    a = _make_source(tmp_path / "a", pages=2)
    b = _make_source(tmp_path / "b", pages=3, name="b.pdf")
    output = tmp_path / "out.pdf"
    result = run_cli("merge", str(a), str(b), "-O", str(output), "-o", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["items"]) == 2
    for item in payload["items"]:
        assert item["output"] == str(output)
    assert "schema_version" in payload


def test_split_every_json_output_has_one_item_per_part(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=25)
    out_dir = tmp_path / "parts"
    result = run_cli("split", str(source), "--every", "10", "--out-dir", str(out_dir), "-o", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["items"]) == 3
    assert "schema_version" in payload


# --------------------------------------------------------------------------- #
# AC30 -- B-035's own evidence line, inverted
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", ["info", "doctor", "version"])
@pytest.mark.parametrize("flag_args", [["-O"], ["--out-dir"], ["--name"], ["--in-place"]])
def test_or3_evidence_line_inverted_no_traceback(
    tmp_path: Path, verb: str, flag_args: list[str]
) -> None:
    source = _make_source(tmp_path / "src", pages=1)
    target = tmp_path / "report.json"
    base = [] if verb in ("doctor", "version") else [str(source)]
    if flag_args[0] == "--in-place":
        extra = ["--in-place"]
    else:
        extra = [*flag_args, str(target)]
    result = run_cli(verb, *base, *extra)
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert not target.exists()
