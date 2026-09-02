"""``rasterize`` — the CLI-level surface (Design §D3, D7, D10, D14): flag
contract exit codes, AC2/AC3's real-subprocess halves, AC6 (--threads),
AC12's whole matrix, AC14 (help text), AC15 (dry-run purity), AC23 (OR-3
single-path + ordering proof).

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
    made = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    made.setProducer("pdf-toolkit test corpus")
    made.setCreator("tests/integration/test_rasterize_cli.py")
    for number in range(1, pages + 1):
        made.drawString(72, 700, f"src page {number}")
        made.showPage()
    made.save()
    return path


# --------------------------------------------------------------------------- #
# AC2 -- --pages 2 writes exactly one file, over the real console script
# --------------------------------------------------------------------------- #


def test_ac2_pages_2_writes_exactly_one_file(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=3, name="multi.pdf")
    out_dir = tmp_path / "out"
    result = run_cli("rasterize", str(source), "--pages", "2", "--out-dir", str(out_dir))
    assert result.returncode == 0, result.stderr
    entries = list(out_dir.iterdir())
    assert len(entries) == 1
    assert entries[0].name == "multi-0002.png"


# --------------------------------------------------------------------------- #
# AC3 -- byte identity across --threads 1 / --threads 8, over the real
# console script. See tests/unit/test_raster.py for the ops-layer half.
# --------------------------------------------------------------------------- #


def test_ac3_threads_1_and_threads_8_are_byte_identical_over_the_cli(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=8, name="eight.pdf")
    out1 = tmp_path / "t1"
    out8 = tmp_path / "t8"

    result1 = run_cli(
        "rasterize",
        str(source),
        "--dpi",
        "96",
        "--out-dir",
        str(out1),
        "--threads",
        "1",
        "-o",
        "json",
    )
    result8 = run_cli(
        "rasterize",
        str(source),
        "--dpi",
        "96",
        "--out-dir",
        str(out8),
        "--threads",
        "8",
        "-o",
        "json",
    )
    assert result1.returncode == 0, result1.stderr
    assert result8.returncode == 0, result8.stderr

    names1 = sorted(p.name for p in out1.iterdir())
    names8 = sorted(p.name for p in out8.iterdir())
    assert names1 == names8
    assert len(names1) == 8
    for name in names1:
        assert (out1 / name).read_bytes() == (out8 / name).read_bytes(), name

    payload1 = json.loads(result1.stdout)
    payload8 = json.loads(result8.stdout)
    order1 = [Path(item["output"]).name for item in payload1["items"]]
    order8 = [Path(item["output"]).name for item in payload8["items"]]
    assert order1 == order8 == names1


# --------------------------------------------------------------------------- #
# AC6 -- --threads 0 / -1 exit 2; --threads 1 and --threads 8 both exit 0.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad_threads", ["0", "-1"])
def test_ac6_threads_out_of_range_exits_2(tmp_path: Path, bad_threads: str) -> None:
    source = _make_source(tmp_path / "src", pages=1)
    result = run_cli(
        "rasterize", str(source), "--threads", bad_threads, "--out-dir", str(tmp_path / "out")
    )
    assert result.returncode == 2


@pytest.mark.parametrize("threads", ["1", "8"])
def test_ac6_threads_1_and_8_both_exit_0(tmp_path: Path, threads: str) -> None:
    source = _make_source(tmp_path / "src", pages=2)
    out_dir = tmp_path / f"out-{threads}"
    result = run_cli(
        "rasterize", str(source), "--dpi", "72", "--threads", threads, "--out-dir", str(out_dir)
    )
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------- #
# AC12 -- every D3 ruling, asserted on the exit code.
# --------------------------------------------------------------------------- #


def test_ac12_dpi_and_width_together_exits_2(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=1)
    result = run_cli(
        "rasterize",
        str(source),
        "--dpi",
        "300",
        "--width",
        "1200",
        "--out-dir",
        str(tmp_path / "o"),
    )
    assert result.returncode == 2


def test_ac12_quality_with_png_exits_2(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=1)
    result = run_cli(
        "rasterize",
        str(source),
        "--quality",
        "82",
        "--format",
        "png",
        "--out-dir",
        str(tmp_path / "o"),
    )
    assert result.returncode == 2


@pytest.mark.parametrize("bad_quality", ["0", "101"])
def test_ac12_quality_out_of_range_exits_2(tmp_path: Path, bad_quality: str) -> None:
    source = _make_source(tmp_path / "src", pages=1)
    result = run_cli(
        "rasterize",
        str(source),
        "--quality",
        bad_quality,
        "--format",
        "jpeg",
        "--out-dir",
        str(tmp_path / "o"),
    )
    assert result.returncode == 2


def test_ac12_output_with_out_dir_exits_2(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=1)
    result = run_cli(
        "rasterize", str(source), "-O", str(tmp_path / "o.png"), "--out-dir", str(tmp_path / "d")
    )
    assert result.returncode == 2


def test_ac12_output_alone_exits_2_with_a_three_page_selection(tmp_path: Path) -> None:
    """D10 struck the old "single-output -O" rule (correction C-1): -O always
    exits 2 for rasterize, whatever the selection resolves to."""
    source = _make_source(tmp_path / "src", pages=3)
    result = run_cli("rasterize", str(source), "-O", str(tmp_path / "o.png"))
    assert result.returncode == 2


def test_ac12_name_range_exits_5(tmp_path: Path) -> None:
    """Correction C-3: `{range}` is a substituted-value concern, exit 5, not 2."""
    source = _make_source(tmp_path / "src", pages=1)
    result = run_cli(
        "rasterize", str(source), "--name", "{range}.png", "--out-dir", str(tmp_path / "o")
    )
    assert result.returncode == 5


def test_ac12_pages_malformed_exits_2(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=1)
    result = run_cli("rasterize", str(source), "--pages", "1--3", "--out-dir", str(tmp_path / "o"))
    assert result.returncode == 2


def test_ac12_pages_even_on_a_one_page_document_exits_4(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=1)
    result = run_cli("rasterize", str(source), "--pages", "even", "--out-dir", str(tmp_path / "o"))
    assert result.returncode == 4


def test_ac12_existing_target_without_force_exits_5(tmp_path: Path) -> None:
    """PDF-21: the seeded bytes are now RE-READ. The shipped version wrote
    ``b"already here"`` and asserted only the exit code, so "no-clobber" -- the
    half of the rule a user actually cares about -- was unasserted: a run that
    exited 5 *after* overwriting the file would have passed."""
    source = _make_source(tmp_path / "src", pages=1)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    target = out_dir / "src-0001.png"
    target.write_bytes(b"already here")
    result = run_cli("rasterize", str(source), "--out-dir", str(out_dir))
    assert result.returncode == 5
    assert target.read_bytes() == b"already here", (
        "the pre-existing target was modified by a run that refused with exit 5"
    )
    assert sorted(path.name for path in out_dir.iterdir()) == ["src-0001.png"]


def test_ac12_two_inputs_same_stem_collide_exit_5_nothing_written(tmp_path: Path) -> None:
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first = _make_source(first_dir, pages=1, name="same.pdf")
    second = _make_source(second_dir, pages=1, name="same.pdf")
    out_dir = tmp_path / "out"
    result = run_cli("rasterize", str(first), str(second), "--out-dir", str(out_dir))
    assert result.returncode == 5
    assert not out_dir.exists() or list(out_dir.iterdir()) == []


# AC12's "RasterEngine monkeypatched unavailable -> 3 with the hint" needs a
# test seam over a real, installed engine that a subprocess cannot provide;
# it is exercised at the unit layer instead --
# tests/unit/test_raster.py::test_raster_engine_unavailable_exits_3_with_a_hint
# and ::test_webp_engine_missing_exits_3_when_pillow_lacks_webp_support.


# --------------------------------------------------------------------------- #
# AC14 -- the mechanized help-text criterion.
# --------------------------------------------------------------------------- #


#: PDF-09 AC14's actual claim, as one collapsed-whitespace phrase. Pinned on
#: the SENTENCE rather than on the `--threads 1` token, because `--threads 1`
#: occurs TWICE in the help (measured at `b20a651`): deleting the claim
#: sentence outright leaves the shipped token assertion green -- which is the
#: finding, and this constant is the fix.
_THREADS_1_CLAIM = (
    "--threads 1 forces deterministic sequential rendering and is the switch "
    "to reproduce a parallel failure"
)


def test_ac14_help_documents_threads_1_as_the_reproduction_switch() -> None:
    result = run_cli("rasterize", "--help")
    assert result.returncode == 0
    assert "--threads 1" in result.stdout
    collapsed = " ".join(result.stdout.split())
    assert _THREADS_1_CLAIM in collapsed, (
        "`--threads 1` is named but the claim AC14 requires the surrounding "
        "line to make is absent; the flag token alone is not the criterion"
    )


# --------------------------------------------------------------------------- #
# AC15 -- --dry-run writes nothing, and --out-dir is not created.
# --------------------------------------------------------------------------- #


def test_ac15_dry_run_writes_nothing_and_does_not_create_out_dir(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=2)
    out_dir = tmp_path / "does-not-exist-yet"
    env, roots = redirected_environment(tmp_path)
    before = snapshot(*roots)
    result = run_cli(
        "rasterize", str(source), "--out-dir", str(out_dir), "--dry-run", env=env, cwd=tmp_path
    )
    assert result.returncode == 0, result.stderr
    assert_unchanged(before, snapshot(*roots))
    assert not out_dir.exists()
    assert list(tmp_path.rglob(".pdftoolkit-*")) == []

    # PDF-21: AC15's *"it still prints the FULL LIST of planned output paths"*
    # clause was unasserted -- C15 reads only `items[0].output`, so a dry run
    # that predicted ONE page of a two-page selection passed.
    envelope = json.loads(result.stdout)
    outputs = [item["output"] for item in envelope["items"]]
    assert outputs == [str(out_dir / "src-0001.png"), str(out_dir / "src-0002.png")], outputs


# --------------------------------------------------------------------------- #
# AC23 -- OR-3: -O/--in-place refused from the shared option layer only, and
# the pinned check-order (mutual exclusion before OR-3) is proven by message.
# --------------------------------------------------------------------------- #


def test_ac23_output_flag_refused_and_nothing_written(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=1)
    target = tmp_path / "thumb.png"
    result = run_cli("rasterize", str(source), "-O", str(target))
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "rasterize" in combined
    assert "--output" in combined
    assert not target.exists()


def test_ac23_in_place_refused(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=1)
    result = run_cli("rasterize", str(source), "--in-place")
    assert result.returncode == 2


def test_ac13_name_escaping_the_out_dir_is_refused_at_the_cli_and_nothing_escapes(
    tmp_path: Path,
) -> None:
    """PDF-21: AC13's escape case was asserted only at the OPS layer (the
    exception type it raises) and never at CLI exit-code level -- the level the
    criterion is actually written at.

    **The criterion's parenthetical is wrong and this test records the measured
    behaviour instead.** AC13 says *"is refused (exit 5 per D4; assert whatever
    the shared safety path enforces)"*. Measured at `b20a651`, the CLI refuses
    at **exit 2** from `cli/common.py`'s filename-template guard -- *"--name is
    a filename template and must not contain a path separator"* -- which fires
    BEFORE `render_name`'s containment check ever runs. Exit 5 is what the OPS
    layer produces when called directly (the sibling unit test), so both are
    real; the CLI's is stricter and earlier. The criterion's binding half --
    *"nothing is written outside --out-dir"* -- is asserted either way.
    """
    source = _make_source(tmp_path / "src", pages=1)
    out_dir = tmp_path / "out"
    result = run_cli("rasterize", str(source), "--out-dir", str(out_dir), "--name", "../{stem}.png")
    combined = result.stdout + result.stderr
    assert result.returncode == 2, combined
    assert "path separator" in combined, combined
    escaped = tmp_path / "src.png"
    assert not escaped.exists(), f"a file was written outside --out-dir: {escaped}"
    assert not out_dir.exists() or list(out_dir.iterdir()) == []


def test_ac23b_the_refusal_exists_only_in_the_shared_option_layer() -> None:
    """PDF-21: AC23 clause (b) is a mechanized single-path grep that **had no
    test**. Its property is the whole point of AC23: a duplicate ``-O`` /
    ``--in-place`` check inside the verb would be a second path that could later
    disagree with ``cli/common.py``'s."""
    import re

    path = Path(__file__).resolve().parents[2] / "src" / "pdf_toolkit" / "cli" / "cmd_rasterize.py"
    hits = re.findall(r'"--output"|"-O"|"--in-place"', path.read_text())
    assert hits == [], (
        f"cmd_rasterize.py names {hits} itself -- the OR-3 refusal must come from "
        f"the declaration in cli/common.py and from nowhere else"
    )


def test_ac23_declaration_is_exactly_out_dir_and_name() -> None:
    from pdf_toolkit.cli.common import consumed_output_flags

    assert consumed_output_flags("pdf_toolkit.cli.cmd_rasterize") == ("--out-dir", "--name")


def test_ac23_ordering_mutual_exclusion_before_or3(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "src", pages=1)
    both = run_cli(
        "rasterize", str(source), "-O", str(tmp_path / "a.png"), "--out-dir", str(tmp_path / "d")
    )
    assert both.returncode == 2
    assert "mutually exclusive" in (both.stdout + both.stderr).lower()

    output_only = run_cli("rasterize", str(source), "-O", str(tmp_path / "a.png"))
    assert output_only.returncode == 2
    assert "--output" in (output_only.stdout + output_only.stderr)


# --------------------------------------------------------------------------- #
# HC-1 / AC16 -- the mechanized grep, run for real over the CLI module too.
# --------------------------------------------------------------------------- #


def test_hc1_no_forbidden_name_in_cmd_rasterize() -> None:
    import re

    path = Path(__file__).resolve().parents[2] / "src" / "pdf_toolkit" / "cli" / "cmd_rasterize.py"
    text = path.read_text()
    pattern = (
        r"subprocess|os\.system|os\.exec|shutil\.which|pdf2image|pdftoppm|pdftocairo|"
        r"pdfinfo|ghostscript|\bgs\b|fitz|pymupdf"
    )
    assert re.search(pattern, text) is None
