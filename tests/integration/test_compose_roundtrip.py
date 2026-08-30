"""PDF-10 at the process boundary: the `rasterize`->`compose` round-trip, and
the CLI surface of both verbs.

Two things live here that only exist as real subprocess runs: exit codes, and
non-TTY posture. The unit suites drive the ops layer directly; nothing there can
observe either.

The round-trip is deliberately **soft-ordered** on PDF-09 rather than dependent
on it: when `rasterize` is not in the verb registry this file's round-trip arm
SKIPS with a reason. It must never fail on that verb's absence, and must never
silently pass either.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from helpers.pdfstream import page_media_box  # noqa: E402
from registry import console_script, discover_verbs, run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

_ROUNDTRIP_SKIP = "rasterize (PDF-09) not in the verb registry"


def _verb_names() -> set[str]:
    return {verb.name for verb in discover_verbs()}


def _jpeg(path: Path, *, size: tuple[int, int] = (320, 240)) -> Path:
    Image.new("RGB", size, (200, 30, 30)).save(path, format="JPEG", quality=85)
    return path


def _pages(path: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(path)).pages)


# --------------------------------------------------------------------------- #
# AC17 -- rasterize -> compose, page count exact and geometry within 1 pt.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("image_format", ["png", "jpeg"])
def test_ac17_rasterize_then_compose_round_trips_page_count_and_geometry(
    image_format: str, corpus, tmp_path: Path
) -> None:
    if "rasterize" not in _verb_names():
        pytest.skip(_ROUNDTRIP_SKIP)

    from pdf_toolkit.ops.compose import compose_document, parse_page_size
    from pdf_toolkit.ops.raster import rasterize_document
    from pdf_toolkit.safety.policy import SafetyPolicy

    policy = SafetyPolicy(
        dry_run=False,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )
    source = corpus.path("multipage_text")
    expected = [page_media_box(source, index) for index in range(_pages(source))]

    dpi = 150.0
    out_dir = tmp_path / f"pages-{image_format}"
    rendered = rasterize_document(
        [source],
        pages_spec=None,
        dpi=dpi,
        width_px=None,
        fmt=image_format,
        quality=None,
        grayscale=False,
        name_template=None,
        out_dir=out_dir,
        policy=policy,
    )
    assert rendered.exit_code == 0

    images = sorted(out_dir.iterdir())
    assert len(images) == len(expected)

    out = tmp_path / f"roundtrip-{image_format}.pdf"
    composed = compose_document(
        images,
        output=out,
        page=parse_page_size("from-image"),
        fit="contain",
        margin_pt=0.0,
        dpi=dpi,
        policy=policy,
    )
    assert composed.exit_code == 0
    assert _pages(out) == len(expected)
    for index, (width, height) in enumerate(expected):
        assert page_media_box(out, index) == pytest.approx((width, height), abs=1.0)


# --------------------------------------------------------------------------- #
# AC14/AC15 -- standard input, and every refusal around it.
# --------------------------------------------------------------------------- #


def test_ac14_create_from_standard_input_writes_a_one_page_pdf(tmp_path: Path) -> None:
    out = tmp_path / "hello.pdf"
    result = run_cli("create", "-", "-O", str(out), stdin="x")
    assert result.returncode == 0, result.stderr
    assert _pages(out) == 1

    from pypdf import PdfReader

    assert "x" in PdfReader(str(out)).pages[0].extract_text()


def test_ac15_empty_standard_input_is_exit_4_and_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    result = run_cli("create", "-", "-O", str(out), stdin="")
    assert result.returncode == 4
    assert not out.exists()


def test_ac15_a_zero_byte_file_behaves_identically(tmp_path: Path) -> None:
    source = tmp_path / "empty.txt"
    source.write_bytes(b"")
    out = tmp_path / "out.pdf"
    result = run_cli("create", str(source), "-O", str(out))
    assert result.returncode == 4
    assert not out.exists()


def test_ac15_standard_input_with_no_destination_is_exit_2() -> None:
    result = run_cli("create", "-", stdin="hello")
    assert result.returncode == 2


def test_ac15_two_operands_is_exit_2(tmp_path: Path) -> None:
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("a\n")
    second.write_text("b\n")
    result = run_cli("create", str(first), str(second), "-O", str(tmp_path / "out.pdf"))
    assert result.returncode == 2


@pytest.mark.skipif(sys.platform.startswith("win"), reason="pty is POSIX-only")
def test_ac15_reading_from_a_terminal_is_refused_rather_than_hanging(tmp_path: Path) -> None:
    """A real pty, so the refusal is proven against an actual terminal rather
    than against a mocked `isatty`. The timeout is the assertion that matters:
    the tool must never sit waiting on a prompt nobody typed."""
    import pty

    controller, follower = pty.openpty()
    try:
        completed = subprocess.run(
            [*console_script(), "create", "-", "-O", str(tmp_path / "out.pdf")],
            stdin=follower,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    finally:
        os.close(follower)
        os.close(controller)
    assert completed.returncode == 2
    assert not (tmp_path / "out.pdf").exists()


def test_a_file_operand_with_no_destination_writes_beside_the_input(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("hello\n")
    result = run_cli("create", str(source))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "notes.pdf").exists()


# --------------------------------------------------------------------------- #
# AC11/AC12 -- ordering, refusals and the honest per-item report, live.
# --------------------------------------------------------------------------- #


def test_ac11_a_directory_operand_is_exit_2_and_names_the_shell_glob(tmp_path: Path) -> None:
    result = run_cli("compose", str(tmp_path), "-O", str(tmp_path / "out.pdf"))
    assert result.returncode == 2
    assert "shell" in result.stdout + result.stderr


def test_ac12_the_json_payload_carries_the_per_item_facts(tmp_path: Path) -> None:
    jpeg = _jpeg(tmp_path / "a.jpg")
    png = tmp_path / "b.png"
    Image.new("RGB", (100, 80), (5, 5, 250)).save(png, format="PNG")
    out = tmp_path / "out.pdf"
    result = run_cli("compose", str(jpeg), str(png), "-O", str(out), "-o", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    first, second = payload["items"]
    for item in (first, second):
        for key in ("embed", "stream_bytes_identical", "source_format", "dpi_source", "page"):
            assert key in item["detail"], key
    assert first["detail"]["embed"] == "dctdecode-passthrough"
    assert first["detail"]["stream_bytes_identical"] is True
    assert second["detail"]["embed"] == "flate-reencode"
    assert second["detail"]["stream_bytes_identical"] is False
    assert (first["detail"]["page"], second["detail"]["page"]) == (1, 2)


def test_a_progressive_jpeg_warns_on_stderr_as_well_as_in_the_payload(tmp_path: Path) -> None:
    source = tmp_path / "prog.jpg"
    Image.new("RGB", (200, 150), (10, 200, 40)).save(
        source, format="JPEG", quality=85, progressive=True
    )
    out = tmp_path / "out.pdf"
    result = run_cli("compose", str(source), "-O", str(out), "-o", "json")
    assert result.returncode == 0, result.stderr
    assert "progressive" in result.stderr
    assert any("progressive" in warning for warning in json.loads(result.stdout)["warnings"])


# --------------------------------------------------------------------------- #
# AC22 -- OR-3, live, on both verbs.
# --------------------------------------------------------------------------- #


def _refused_flag_args(flag: str, tmp_path: Path) -> list[str]:
    if flag == "--out-dir":
        return ["--out-dir", str(tmp_path / "declined-dir")]
    if flag == "--name":
        return ["--name", "declined-{index}.{ext}"]
    return ["--in-place"]


@pytest.mark.parametrize("verb", ["compose", "create"])
@pytest.mark.parametrize("flag", ["--out-dir", "--name", "--in-place"])
def test_ac22_a_flag_neither_verb_consumes_exits_2_and_writes_nothing(
    verb: str, flag: str, tmp_path: Path
) -> None:
    workspace = tmp_path / f"{verb}{flag.strip('-')}"
    workspace.mkdir()
    if verb == "compose":
        operand = _jpeg(workspace / "a.jpg")
    else:
        operand = workspace / "a.txt"
        operand.write_text("hello\n")
    before = set(workspace.rglob("*"))

    result = run_cli(verb, str(operand), *_refused_flag_args(flag, workspace), cwd=workspace)
    combined = result.stdout + result.stderr
    assert result.returncode == 2, combined
    assert verb in combined
    assert flag in combined
    assert set(workspace.rglob("*")) == before


@pytest.mark.parametrize("verb", ["compose", "create"])
def test_ac22_the_consumed_flag_is_honoured(verb: str, tmp_path: Path) -> None:
    workspace = tmp_path / verb
    workspace.mkdir()
    if verb == "compose":
        operand = _jpeg(workspace / "a.jpg")
    else:
        operand = workspace / "a.txt"
        operand.write_text("hello\n")
    out = workspace / "honoured.pdf"
    result = run_cli(verb, str(operand), "-O", str(out), cwd=workspace)
    assert result.returncode == 0, result.stderr
    assert out.exists()


@pytest.mark.parametrize("verb", ["compose", "create"])
def test_ac22_the_refusal_ordering_is_proven_not_assumed(verb: str, tmp_path: Path) -> None:
    """Mutual exclusion is diagnosed FIRST, before the OR-3 consumption check --
    so the two invocations below exit 2 with DIFFERENT messages. Asserting the
    message is what proves the ordering rather than assuming it."""
    workspace = tmp_path / f"order-{verb}"
    workspace.mkdir()
    if verb == "compose":
        operand = _jpeg(workspace / "a.jpg")
    else:
        operand = workspace / "a.txt"
        operand.write_text("hello\n")

    both = run_cli(
        verb,
        str(operand),
        "-O",
        str(workspace / "o.pdf"),
        "--out-dir",
        str(workspace / "d"),
        cwd=workspace,
    )
    assert both.returncode == 2
    assert "mutually exclusive" in both.stdout + both.stderr

    only_declined = run_cli(verb, str(operand), "--out-dir", str(workspace / "d"), cwd=workspace)
    assert only_declined.returncode == 2
    combined = only_declined.stdout + only_declined.stderr
    assert "does not accept --out-dir" in combined
    assert "mutually exclusive" not in combined


# --------------------------------------------------------------------------- #
# AC19 -- the dry run writes nothing, live.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", ["compose", "create"])
def test_ac19_a_dry_run_leaves_the_workspace_byte_identical(verb: str, tmp_path: Path) -> None:
    from fs_snapshot import assert_unchanged, redirected_environment, snapshot

    workspace = tmp_path / f"dry-{verb}"
    workspace.mkdir()
    if verb == "compose":
        operand = _jpeg(workspace / "a.jpg")
    else:
        operand = workspace / "a.txt"
        operand.write_text("hello\n")

    env, roots = redirected_environment(workspace)
    before = snapshot(workspace, *roots)
    result = run_cli(
        verb,
        "--dry-run",
        str(operand),
        "-O",
        str(workspace / "out.pdf"),
        env=env,
        cwd=workspace,
    )
    assert result.returncode == 0, result.stderr
    assert_unchanged(before, snapshot(workspace, *roots))
    assert list(workspace.glob(".pdftoolkit-*")) == []
