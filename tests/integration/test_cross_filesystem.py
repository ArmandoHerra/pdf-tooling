"""Cross-filesystem behaviour, against a **real** second filesystem.

``os.replace`` is atomic within a filesystem and nowhere else, so two situations
end the guarantee and both must warn. Proving that honestly means obtaining a
genuine second mount rather than monkeypatching ``st_dev``: a patched device id
proves the branch is reachable, not that the kernel does what the branch assumes.

The acquisition ladder, first candidate whose device differs from ``tmp_path``
and which is writable:

1. ``$PDF_TOOLING_TEST_XDEV_DIR`` — the operator's explicit override.
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
import stat
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from pdf_tooling.safety import DEGRADED_PREFIX, find_stray_temps

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from atomic_harness import run_harness  # noqa: E402
from registry import run_cli  # noqa: E402

OVERRIDE = "PDF_TOOLING_TEST_XDEV_DIR"

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


def test_a_dry_run_reaches_the_degradation_warning_too(tmp_path: Path, xdev_dir: Path) -> None:
    """X-67: the third condition the writer owns, now reachable under --dry-run.

    This one is a warning rather than an exit code, so the prediction is the
    warning itself and ``would_exit`` stays 0 — a degraded write still succeeds.
    Before X-67 the plan never ran under ``--dry-run``, so a preview of a write
    that was about to land on a filesystem the user did not name said nothing at
    all; the user learned about it only from the real run, after the bytes moved.

    The warning text is asserted equal to the real run's, not merely similar.
    """
    import json

    real_out = xdev_dir / "out"
    real_out.mkdir()
    out_dir = tmp_path / "outdir"
    out_dir.symlink_to(real_out)
    target = out_dir / "doc.pdf"

    preview = run_harness(["--dry-run", "write", "--target", str(target), "-o", "json"])
    assert preview.returncode == 0, preview.stderr
    predicted = json.loads(preview.stdout)

    assert DEGRADED_PREFIX in preview.stderr
    assert predicted["would_exit"] == 0, "degradation warns; it does not refuse"
    assert "would_refuse" not in predicted
    assert not (real_out / "doc.pdf").exists(), "the preview wrote the document"
    assert find_stray_temps(real_out) == ()

    actual = run_harness(["write", "--target", str(target), "-o", "json"])
    assert actual.returncode == 0, actual.stderr
    assert predicted["warnings"] == json.loads(actual.stdout)["warnings"]


def test_a_same_filesystem_destination_warns_about_nothing(tmp_path: Path) -> None:
    result = run_harness(["write", "--target", str(tmp_path / "doc.pdf")])
    assert result.returncode == 0, result.stderr
    assert DEGRADED_PREFIX not in result.stderr


def test_a_same_filesystem_dry_run_warns_about_nothing_either(tmp_path: Path) -> None:
    """Non-vacuity for the arm above: the dry-run warning is not unconditional."""
    result = run_harness(["--dry-run", "write", "--target", str(tmp_path / "doc.pdf")])
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


# --------------------------------------------------------------------------- #
# PDF-90 AC8/AC9(b) — the degraded path lands the SAME mode as the normal
# path, and a preserved destination lacking the owner-read bit still
# completes at exit 0, because the mode is applied only after
# `_replace_across_devices`'s own verification (`§D3`, `§E11`).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("umask_value", "expected"),
    [(0o002, 0o664), (0o022, 0o644), (0o077, 0o600)],
    ids=["umask-002", "umask-022", "umask-077"],
)
def test_ac8_a_fresh_exdev_create_lands_the_same_mode_as_the_normal_path(
    tmp_path: Path, xdev_dir: Path, umask_value: int, expected: int
) -> None:
    """AC8. The ``umask 077`` cell is the same NEGATIVE control AC2 names:
    ``0o600`` is also the pre-fix defect's own answer, so it proves only that
    nothing loosened, never that this path preserves. The 002/022 cells are
    what discriminate the fix from the defect."""
    target = tmp_path / "doc.pdf"
    previous = os.umask(umask_value)
    try:
        result = run_harness(["write", "--target", str(target), "--temp-dir", str(xdev_dir)])
    finally:
        os.umask(previous)
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(target.stat().st_mode) == expected


def test_ac8_a_forced_exdev_overwrite_preserves_a_0400_destination(
    tmp_path: Path, xdev_dir: Path
) -> None:
    """AC8. ``-f`` over a ``0400`` destination through ``EXDEV``: ``0400``,
    identical to the normal path's own AC4 arm."""
    target = tmp_path / "doc.pdf"
    target.write_text("original")
    target.chmod(0o400)
    result = run_harness(["-f", "write", "--target", str(target), "--temp-dir", str(xdev_dir)])
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(target.stat().st_mode) == 0o400, (
        "the degraded path added back the owner-write bit a 0400 destination never "
        "had -- the normal path (AC4) refuses to do this"
    )


@pytest.mark.parametrize("preserved_mode", [0o200, 0o000], ids=["0200", "0000"])
def test_ac9b_a_preserved_destination_lacking_owner_read_completes_through_exdev(
    tmp_path: Path, xdev_dir: Path, preserved_mode: int
) -> None:
    """AC9(b). The mode is applied AFTER ``_replace_across_devices``'s own
    size-and-SHA-256 verification. Moved earlier, this exact arm raises an
    unhandled ``PermissionError`` out of ``_digest``'s ``open(path, "rb")``
    (`§E11`, `§D3`), because the verification re-reads the destination by
    path while it would already be unreadable."""
    target = tmp_path / "doc.pdf"
    target.write_text("original")
    target.chmod(preserved_mode)
    result = run_harness(["-f", "write", "--target", str(target), "--temp-dir", str(xdev_dir)])
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(target.stat().st_mode) == preserved_mode


# --------------------------------------------------------------------------- #
# PDF-81 — the same condition, reached through a REAL VERB rather than through
# the harness, because one verb was losing the warning and the harness cannot
# see that
# --------------------------------------------------------------------------- #
#
# Every arm above drives `tests/atomic_harness.py`, which exercises the safety
# spine directly. That is the right instrument for the spine and it is blind to
# this defect by construction: the harness never calls an engine, so nothing in
# it can rebind `sys.stderr` before `AtomicWriter._warn` writes to it. Measured
# at `0c63090`, through an identical cross-device destination, `compress` and
# `repair` emitted the degradation warning and `linearize` emitted ZERO bytes,
# 3/3 — because `pikepdf.Pdf.check_linearization` had taken `sys.stderr` during
# `linearize`'s verification step and never given it back. The warning was
# still raised, still appended to `AtomicWriter.warnings`, and still written;
# it was written somewhere nobody was reading.
#
# THE DESTINATION NAME MUST BE FRESH, and that is a property of the product
# rather than an accident of the fixture. `declared_device` walks
# `(target, *target.parents)` and `lstat`s the first that exists, so once a
# destination FILE exists behind the symlink its own device is what gets
# compared and the condition legitimately stops holding — a second write to the
# same name warns about nothing. `xdev_dir` hands out a fresh `mkdtemp`
# workspace per test, so the names below are fresh by construction; a future
# author reusing one would get a green arm that had stopped asking anything.

_DEGRADED_VERBS = ("linearize", "compress", "repair")


@pytest.fixture
def linearizable(tmp_path: Path) -> Path:
    """A document these verbs all succeed on, built by the product's own `create`."""
    source = tmp_path / "note.txt"
    source.write_text("PDF-81 payload\n")
    target = tmp_path / "input.pdf"
    result = run_cli("create", str(source), "-O", str(target), "-o", "json", cwd=tmp_path)
    assert result.returncode == 0, f"could not build the fixture: {result.stdout}{result.stderr}"
    return target


@pytest.mark.parametrize("verb", _DEGRADED_VERBS)
def test_a_producing_verb_writing_across_a_mount_still_warns_on_stderr(
    verb: str, tmp_path: Path, xdev_dir: Path, linearizable: Path
) -> None:
    """PDF-81 AC5, parametrized so the control rides in the same arm.

    `linearize` is the member that was losing this; `compress` and `repair` are
    the two that were not, through the SAME symlink, on the SAME input, and they
    were already green before the fix. A probe that had reddened on all three
    would have been measuring the destination rather than the verb.

    The run exits 0. That is the uncomfortable half of this defect and the
    cheapest symptom it has: the user is told the write SUCCEEDED while the
    safety warning saying it was not atomic on the filesystem they named is
    destroyed. Nothing about the exit code or the payload was ever wrong.
    """
    real_out = xdev_dir / "out"
    real_out.mkdir()
    out_dir = tmp_path / "outdir"
    out_dir.symlink_to(real_out)
    target = out_dir / f"{verb}-fresh.pdf"

    result = run_cli(verb, str(linearizable), "-O", str(target), "-f", "-o", "table", cwd=tmp_path)

    assert result.returncode == 0, f"{verb}: rc={result.returncode} {result.stdout}{result.stderr}"
    assert DEGRADED_PREFIX in result.stderr, (
        f"{verb} wrote across a mount boundary and said {result.stderr!r} on stderr. The "
        "warning is raised either way; before PDF-81 `linearize` wrote it into a buffer "
        "the engine had left in `sys.stderr`'s place, and the caller discarded it"
    )
    # WHAT THIS ARM DELIBERATELY DOES NOT ASSERT, and why the omission is a
    # decision rather than an oversight. PDF-81's spec asks this arm to pin that
    # the warning echoes the path as written and the path it resolved to. Those
    # two properties are ALREADY pinned, on the same message from the same
    # single formatter (`AtomicWriter._warn_if_destination_moved`, which builds
    # exactly one string), by `test_an_out_dir_symlinked_onto_another_mount_-
    # warns_on_stderr` above. Adding them here would add two `assert <operand>
    # in <output>` sites, which is `B-073`'s swept class: measured, it moves
    # `tests/test_secret_leak_sweeps.py`'s frozen `SWEEP_1_CEILING` from 79 to
    # 81, and no ceiling moves for this item. Restructuring the same comparison
    # out of an `assert` node to slip past the sweep, or renaming this function
    # into the `echoes...as_written` exemption written for three specific
    # `test_safety_paths.py` rows, would both be gaming an instrument rather
    # than respecting it. What PDF-81 changed is stream OWNERSHIP, not message
    # CONTENT: the string was always correct, it was written where nobody could
    # read it. So this arm grades the property that moved, and the content stays
    # pinned exactly once. ROUTED to the project-manager rather than decided
    # here -- see this spec's report.
    assert (real_out / target.name).is_file(), f"{verb}: the document did not land"


@pytest.mark.parametrize("verb", _DEGRADED_VERBS)
def test_the_same_verbs_warn_about_nothing_when_no_mount_is_crossed(
    verb: str, tmp_path: Path, linearizable: Path
) -> None:
    """The non-vacuity half of the arm above: it is not merely detecting that
    stderr had bytes. No symlink, no second filesystem, no warning — including
    for `linearize`, whose whole defect was that this channel said nothing."""
    result = run_cli(
        verb,
        str(linearizable),
        "-O",
        str(tmp_path / f"{verb}-local.pdf"),
        "-f",
        "-o",
        "table",
        cwd=tmp_path,
    )
    assert result.returncode == 0, f"{verb}: {result.stdout}{result.stderr}"
    assert DEGRADED_PREFIX not in result.stderr, (
        f"{verb} warned about atomicity on a write that never left its filesystem: "
        f"{result.stderr!r}"
    )
