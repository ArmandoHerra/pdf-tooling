"""PDF-12 -- `compress`/`repair`/`linearize` as real processes.

Only the assertions a direct call cannot make live here: exit codes as a real
process reports them, `--help` content, and CLI-level usage validation
(arity, the `--lossless`/`--images` flag-semantics rules) that lives in
`cli/cmd_compress.py` rather than `ops/optimize.py`. The op-layer behaviour
is proven in `tests/unit/test_optimize.py`, in process, which is what keeps
this module's subprocess count (B-061) proportionate to what genuinely needs
one -- the generic `tests/test_cli_contract.py` matrix (C1-C15) already
covers unknown-flag/nonexistent-input/no-clobber/OR-3/dry-run-parity for all
three verbs with zero action from this file.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import run_cli  # noqa: E402

pytestmark = pytest.mark.e2e


# --------------------------------------------------------------------------- #
# AC1 -- verb surface
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", ["compress", "repair", "linearize"])
def test_ac1_help_exits_0_and_names_structure_engine(verb: str) -> None:
    result = run_cli(verb, "--help")
    assert result.returncode == 0, result.stderr
    assert "StructureEngine" in result.stdout


# --------------------------------------------------------------------------- #
# AC4 -- `--lossless` excludes a lossy image pass (CLI-level flag semantics)
# --------------------------------------------------------------------------- #


def test_ac4_lossless_with_downsample_exits_2(corpus, tmp_path: Path) -> None:
    source = corpus.path("single_page")
    target = tmp_path / "x.pdf"
    result = run_cli(
        "compress", str(source), "--lossless", "--images", "downsample", "-O", str(target)
    )
    assert result.returncode == 2
    assert "--lossless" in (result.stdout + result.stderr)


def test_ac4_lossless_with_recompress_exits_2(corpus, tmp_path: Path) -> None:
    source = corpus.path("single_page")
    target = tmp_path / "x.pdf"
    result = run_cli(
        "compress", str(source), "--lossless", "--images", "recompress", "-O", str(target)
    )
    assert result.returncode == 2


# --------------------------------------------------------------------------- #
# AC6 -- opt-in flag semantics (CLI-level)
# --------------------------------------------------------------------------- #


def test_ac6_pages_without_images_exits_2(corpus, tmp_path: Path) -> None:
    source = corpus.path("single_page")
    result = run_cli("compress", str(source), "--pages", "1", "-O", str(tmp_path / "x.pdf"))
    assert result.returncode == 2


def test_ac6_image_dpi_without_images_exits_2(corpus, tmp_path: Path) -> None:
    source = corpus.path("single_page")
    result = run_cli("compress", str(source), "--image-dpi", "150", "-O", str(tmp_path / "x.pdf"))
    assert result.returncode == 2


def test_ac6_image_quality_without_images_exits_2(corpus, tmp_path: Path) -> None:
    source = corpus.path("single_page")
    target = tmp_path / "x.pdf"
    result = run_cli("compress", str(source), "--image-quality", "80", "-O", str(target))
    assert result.returncode == 2


def test_ac6_bogus_images_value_exits_2(corpus, tmp_path: Path) -> None:
    source = corpus.path("single_page")
    result = run_cli("compress", str(source), "--images", "bogus", "-O", str(tmp_path / "x.pdf"))
    assert result.returncode == 2


def test_ac6_images_default_is_keep_in_help() -> None:
    result = run_cli("compress", "--help")
    assert result.returncode == 0
    assert "keep (default)" in result.stdout or "default: keep" in result.stdout.lower()


# --------------------------------------------------------------------------- #
# Arity (D-12.0a) -- `compress a.pdf b.pdf -O one.pdf` is exit 2, never a
# widened OR-3 declaration.
# --------------------------------------------------------------------------- #


def test_arity_two_inputs_sharing_one_output_exits_2(corpus, tmp_path: Path) -> None:
    source = corpus.path("single_page")
    result = run_cli("compress", str(source), str(source), "-O", str(tmp_path / "one.pdf"))
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "compress" in combined


# --------------------------------------------------------------------------- #
# No destination at all -- exit 2, for all three verbs.
# --------------------------------------------------------------------------- #


def test_compress_with_no_destination_exits_2(corpus) -> None:
    source = corpus.path("single_page")
    result = run_cli("compress", str(source))
    assert result.returncode == 2


def test_repair_with_no_destination_exits_2(corpus) -> None:
    source = corpus.path("single_page")
    result = run_cli("repair", str(source))
    assert result.returncode == 2


def test_linearize_with_no_destination_exits_2(corpus) -> None:
    source = corpus.path("single_page")
    result = run_cli("linearize", str(source))
    assert result.returncode == 2


# --------------------------------------------------------------------------- #
# AC13 -- the encrypted fixture exits 6, naming `decrypt`, as a real process.
# --------------------------------------------------------------------------- #


def test_encrypted_input_exits_6_naming_decrypt(corpus, tmp_path: Path) -> None:
    source = corpus.path("encrypted_aes256")
    result = run_cli("compress", str(source), "-O", str(tmp_path / "x.pdf"))
    assert result.returncode == 6
    assert "decrypt" in (result.stdout + result.stderr)


# --------------------------------------------------------------------------- #
# AC14 -- `--in-place` writes a byte-identical `.bak` sidecar, as a real
# process sees the filesystem (the op-layer half is in
# tests/unit/test_optimize.py).
# --------------------------------------------------------------------------- #


def test_repair_in_place_creates_a_backup_sidecar(corpus, tmp_path: Path) -> None:
    import shutil

    copy_path = tmp_path / "copy.pdf"
    shutil.copy(corpus.path("single_page"), copy_path)
    original = copy_path.read_bytes()

    result = run_cli("repair", str(copy_path), "--in-place")
    assert result.returncode == 0, result.stderr

    backup = copy_path.with_name(copy_path.name + ".bak")
    assert backup.exists()
    assert backup.read_bytes() == original
