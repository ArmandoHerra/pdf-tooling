"""Cross-filesystem behaviour, against a **real** second filesystem.

``os.replace`` is atomic within a filesystem and nowhere else, so two situations
end the guarantee and both must warn. Proving that honestly means obtaining a
genuine second mount rather than monkeypatching ``st_dev``: a patched device id
proves the branch is reachable, not that the kernel does what the branch assumes.

The acquisition ladder, first candidate whose device differs from ``tmp_path``
and which is writable:

1. ``$PDF_TOOLKIT_TEST_XDEV_DIR`` — the operator's explicit override.
2. ``/dev/shm`` — a tmpfs on effectively every Linux, including GitHub's
   ``ubuntu-*`` runners and most containers. No root, no mount, no ``sudo``.
3. ``$HOME``, then ``/var/tmp``, then ``/run/user/$UID``.

**If none is found, the behaviour is deliberately asymmetric.** On Linux the
test *fails*, naming the ladder and the override variable, because a Linux run
that quietly skipped this arm is exactly the "green run that proved nothing" this
product's testing strategy exists to prevent. On any other platform it skips with
that reason printed, never silently passes. A test that needed ``sudo`` would be
skipped forever and would read, on every dashboard, as coverage.
"""

from __future__ import annotations

import errno
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from pdf_toolkit.safety import DEGRADED_PREFIX, find_stray_temps

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from atomic_harness import run_harness  # noqa: E402

OVERRIDE = "PDF_TOOLKIT_TEST_XDEV_DIR"

LADDER_MESSAGE = (
    "no second filesystem could be obtained on this host. The ladder tried, in order: "
    f"${OVERRIDE}, /dev/shm, $HOME, /var/tmp, /run/user/$UID. "
    f"Set {OVERRIDE} to a writable directory on a different mount to run this arm."
)


def _ladder() -> list[tuple[str, str | None]]:
    return [
        (f"1 (${OVERRIDE})", os.environ.get(OVERRIDE)),
        ("2 (/dev/shm)", "/dev/shm"),
        ("3 ($HOME)", os.environ.get("HOME")),
        ("4 (/var/tmp)", "/var/tmp"),
        ("5 (/run/user/$UID)", f"/run/user/{os.getuid()}" if hasattr(os, "getuid") else None),
    ]


def find_second_filesystem(reference: Path) -> tuple[Path, str] | None:
    """The first ladder rung on a different device than *reference*, and writable."""
    try:
        base_device = os.stat(reference).st_dev
    except OSError:  # pragma: no cover - tmp_path always exists
        return None
    for rung, raw in _ladder():
        if not raw:
            continue
        candidate = Path(raw)
        try:
            if not candidate.is_dir():
                continue
            if os.stat(candidate).st_dev == base_device:
                continue
            if not os.access(candidate, os.W_OK | os.X_OK):
                continue
        except OSError:
            continue
        return candidate, rung
    return None


@pytest.fixture
def xdev_dir(tmp_path: Path) -> Iterator[Path]:
    found = find_second_filesystem(tmp_path)
    if found is None:
        if sys.platform == "linux":
            pytest.fail(LADDER_MESSAGE)
        pytest.skip(LADDER_MESSAGE)
    directory, rung = found
    print(f"[PDF-04] second filesystem from ladder rung {rung}: {directory}")
    workspace = Path(tempfile.mkdtemp(dir=directory, prefix="pdf04-xdev-"))
    try:
        yield workspace
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_the_two_directories_really_are_separate_filesystems(
    tmp_path: Path, xdev_dir: Path
) -> None:
    """Non-vacuity. If they shared a device, both arms below would prove nothing."""
    assert os.stat(xdev_dir).st_dev != os.stat(tmp_path).st_dev

    source = xdev_dir / "probe"
    source.write_bytes(b"x")
    with pytest.raises(OSError) as caught:
        os.replace(source, tmp_path / "probe")
    assert caught.value.errno == errno.EXDEV


# --------------------------------------------------------------------------- #
# Condition 1 — the destination is not on the filesystem the user named (AC10)
# --------------------------------------------------------------------------- #


def test_an_out_dir_symlinked_onto_another_mount_warns_on_stderr(
    tmp_path: Path, xdev_dir: Path
) -> None:
    real_out = xdev_dir / "out"
    real_out.mkdir()
    out_dir = tmp_path / "outdir"
    out_dir.symlink_to(real_out)
    target = out_dir / "doc.pdf"

    result = run_harness(["write", "--target", str(target)])
    assert result.returncode == 0, result.stderr

    assert DEGRADED_PREFIX in result.stderr
    assert str(target) in result.stderr, "the warning must echo the path as written"
    assert str(real_out / "doc.pdf") in result.stderr
    assert str(os.lstat(out_dir).st_dev) in result.stderr
    assert str(os.stat(real_out).st_dev) in result.stderr

    assert (real_out / "doc.pdf").read_text() == "PDF-04 payload\n"
    assert find_stray_temps(real_out) == ()


def test_a_same_filesystem_destination_warns_about_nothing(tmp_path: Path) -> None:
    result = run_harness(["write", "--target", str(tmp_path / "doc.pdf")])
    assert result.returncode == 0, result.stderr
    assert DEGRADED_PREFIX not in result.stderr


# --------------------------------------------------------------------------- #
# Condition 2 — a real EXDEV from os.replace (AC11)
# --------------------------------------------------------------------------- #


def test_a_real_exdev_degrades_and_verifies(tmp_path: Path, xdev_dir: Path) -> None:
    target = tmp_path / "doc.pdf"
    payload = "x" * 5000

    result = run_harness(
        ["write", "--target", str(target), "--temp-dir", str(xdev_dir), "--content", payload]
    )
    assert result.returncode == 0, result.stderr

    assert DEGRADED_PREFIX in result.stderr
    assert "cross-device" in result.stderr
    assert "SHA-256" in result.stderr
    assert target.read_text() == payload
    assert find_stray_temps(tmp_path) == ()
    assert find_stray_temps(xdev_dir) == ()


def test_the_degraded_path_still_refuses_to_clobber(tmp_path: Path, xdev_dir: Path) -> None:
    target = tmp_path / "doc.pdf"
    target.write_text("original")
    result = run_harness(["write", "--target", str(target), "--temp-dir", str(xdev_dir)])
    assert result.returncode == 5, result.stderr
    assert target.read_text() == "original"


def test_the_degraded_path_still_writes_the_sidecar(tmp_path: Path, xdev_dir: Path) -> None:
    target = tmp_path / "doc.pdf"
    target.write_text("original")
    result = run_harness(
        [
            "--in-place",
            "write",
            "--target",
            str(target),
            "--temp-dir",
            str(xdev_dir),
            "--content",
            "rewritten",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert target.read_text() == "rewritten"
    assert (tmp_path / "doc.pdf.bak").read_text() == "original"
