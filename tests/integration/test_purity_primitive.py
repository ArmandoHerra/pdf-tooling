"""The ``--dry-run`` purity primitive, and the negative controls that make it real.

``PLAN.md`` §10 calls dry-run purity *the single most important test in the
suite, because it is the guarantee users act on*. Which means the most valuable
thing this file contains is not the purity assertion — it is the six planted
mutations proving the comparator can *fail*. A snapshot differ that always
returned "equal" would make the most important test in the suite green and
meaningless, and nobody would notice until a verb quietly wrote something during
a plan.

So every arm here is symmetric: prove the mechanism detects the change, then
prove a real dry run makes none, then prove the *same* invocation without
``--dry-run`` makes plenty. The third one is the live-guard check. Without it,
"zero differences" is equally consistent with "the run did nothing" and "the
harness never ran at all".

PDF-06 parameterizes this over the verb registry. This file pins the contract it
will parameterize.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from atomic_harness import run_harness  # noqa: E402
from fs_snapshot import (  # noqa: E402
    assert_pure,
    assert_unchanged,
    diff,
    redirected_environment,
    snapshot,
)

# --------------------------------------------------------------------------- #
# AC5 — the six negative controls
# --------------------------------------------------------------------------- #


def test_a_snapshot_compared_against_itself_reports_nothing(tmp_path: Path) -> None:
    (tmp_path / "a.pdf").write_bytes(b"aaaa")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.pdf").write_bytes(b"bbbb")
    taken = snapshot(tmp_path)
    assert diff(taken, taken) == []
    assert len(taken) >= 4


def test_control_one_an_added_file_is_detected(tmp_path: Path) -> None:
    before = snapshot(tmp_path)
    (tmp_path / "new.pdf").write_bytes(b"x")
    kinds = {item.kind for item in diff(before, snapshot(tmp_path))}
    assert "added" in kinds


def test_control_two_a_removed_file_is_detected(tmp_path: Path) -> None:
    victim = tmp_path / "gone.pdf"
    victim.write_bytes(b"x")
    before = snapshot(tmp_path)
    victim.unlink()
    kinds = {item.kind for item in diff(before, snapshot(tmp_path))}
    assert "removed" in kinds


def test_control_three_content_changed_with_mtime_restored_is_detected(tmp_path: Path) -> None:
    """The one a naive mtime-only comparator misses entirely."""
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"aaaa")
    status = os.stat(target)
    before = snapshot(target)

    target.write_bytes(b"bbbb")  # same length, so size cannot give it away
    os.utime(target, ns=(status.st_atime_ns, status.st_mtime_ns))

    differences = diff(before, snapshot(target))
    assert "content" in {item.kind for item in differences}


def test_control_four_mtime_changed_with_identical_content_is_detected(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"aaaa")
    before = snapshot(target)
    os.utime(target, ns=(1_000_000_000, 1_000_000_000))
    assert "mtime" in {item.kind for item in diff(before, snapshot(target))}


def test_control_five_a_replacement_with_identical_content_is_detected(tmp_path: Path) -> None:
    """The inode field is the only thing that sees an atomic replace."""
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"aaaa")
    status = os.stat(target)
    before = snapshot(target)

    stand_in = tmp_path / "stand-in"
    stand_in.write_bytes(b"aaaa")
    os.replace(stand_in, target)
    os.utime(target, ns=(status.st_atime_ns, status.st_mtime_ns))

    kinds = {item.kind for item in diff(before, snapshot(target))}
    assert "inode" in kinds


def test_control_six_a_mode_change_is_detected(tmp_path: Path) -> None:
    """The starting mode is pinned, not inherited from the ambient umask.

    Creating the file and then changing the mode *back* would be a no-op under
    a 022 umask and a real change under 002 — the test would pass on the
    author's machine and fail on the runner, which is how a control test stops
    controlling anything.
    """
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"aaaa")
    target.chmod(0o644)
    before = snapshot(target)
    target.chmod(0o600)
    after = snapshot(target)
    assert "mode" in {item.kind for item in diff(before, after)}


def test_a_create_then_delete_inside_the_run_is_caught_by_directory_mtime(
    tmp_path: Path,
) -> None:
    """Why directory mtime is in the entry at all.

    A verb that writes a temp file, notices the dry-run flag late and tidies up
    leaves no file behind — and nothing but the directory's own mtime sees it.
    The directory's timestamp is pinned to the epoch first so the assertion does
    not depend on clock resolution.
    """
    workspace = tmp_path / "work"
    workspace.mkdir()
    os.utime(workspace, ns=(0, 0))
    before = snapshot(workspace)

    scratch = workspace / "transient"
    scratch.write_bytes(b"x")
    scratch.unlink()

    differences = diff(before, snapshot(workspace))
    assert any(item.kind == "mtime" for item in differences), differences


def test_a_symlink_change_is_detected(tmp_path: Path) -> None:
    link = tmp_path / "alias"
    link.symlink_to(tmp_path / "first")
    before = snapshot(tmp_path)
    link.unlink()
    link.symlink_to(tmp_path / "second")
    kinds = {item.kind for item in diff(before, snapshot(tmp_path))}
    assert "symlink" in kinds


def test_assert_unchanged_names_every_difference(tmp_path: Path) -> None:
    before = snapshot(tmp_path)
    (tmp_path / "one.pdf").write_bytes(b"x")
    (tmp_path / "two.pdf").write_bytes(b"x")
    try:
        assert_unchanged(before, snapshot(tmp_path))
    except AssertionError as error:
        assert "one.pdf" in str(error)
        assert "two.pdf" in str(error)
    else:  # pragma: no cover - the whole point is that it raises
        raise AssertionError("assert_unchanged passed over two added files")


def test_access_time_is_deliberately_not_compared(tmp_path: Path) -> None:
    """A dry run legitimately reads. Comparing atime would assert the wrong thing."""
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"aaaa")
    before = snapshot(target)
    os.utime(target, ns=(2_000_000_000, os.stat(target).st_mtime_ns))
    assert diff(before, snapshot(target)) == []


# --------------------------------------------------------------------------- #
# AC6 — a real dry run, and the control that proves the guard is live
# --------------------------------------------------------------------------- #


def test_a_dry_run_touches_nothing_anywhere(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    env, redirected = redirected_environment(tmp_path)
    roots = (work, *redirected)

    with assert_pure(*roots):
        result = run_harness(
            ["--dry-run", "write", "--target", str(work / "doc.pdf")],
            env=env,
        )
        assert result.returncode == 0, result.stderr


def test_the_same_invocation_without_dry_run_changes_the_tree(tmp_path: Path) -> None:
    """The live-guard control. Zero differences must mean something."""
    work = tmp_path / "work"
    work.mkdir()
    env, redirected = redirected_environment(tmp_path)
    roots = (work, *redirected)

    before = snapshot(*roots)
    result = run_harness(["write", "--target", str(work / "doc.pdf")], env=env)
    assert result.returncode == 0, result.stderr
    differences = diff(before, snapshot(*roots))

    assert differences, "the non-dry-run control produced no differences — a dead guard"
    assert any(item.kind == "added" for item in differences)


def test_a_dry_run_over_an_existing_target_is_still_pure(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "doc.pdf").write_bytes(b"original")
    env, redirected = redirected_environment(tmp_path)

    with assert_pure(work, *redirected):
        result = run_harness(
            ["--dry-run", "--in-place", "write", "--target", str(work / "doc.pdf")],
            env=env,
        )
        assert result.returncode == 0, result.stderr


def test_a_dry_run_that_predicts_a_refusal_is_still_pure(tmp_path: Path) -> None:
    """X-67 made this assertion mean something, so it is asserted separately.

    Before X-67 the purity arms above passed *vacuously* over a refusal: the gate
    was the first statement of ``__enter__``, so a dry run over an occupied
    target executed no filesystem code at all and "zero differences" was
    guaranteed by doing nothing. The plan now genuinely runs — ``exists()``,
    ``lexists()``, ``is_dir()``, ``os.access`` and two device stats — and this
    arm is what proves every one of those is a read.

    Deliberately without ``--in-place``, unlike the arm above: ``--in-place``
    suppresses the no-clobber check by definition, so that arm never exercised
    the capture path. If this test ever reports differences, the planning helpers
    are not read-only and that is a defect in them, never a reason to relax what
    is asserted here.
    """
    work = tmp_path / "work"
    work.mkdir()
    (work / "doc.pdf").write_bytes(b"original")
    env, redirected = redirected_environment(tmp_path)

    with assert_pure(work, *redirected):
        result = run_harness(
            ["--dry-run", "write", "--target", str(work / "doc.pdf"), "-o", "json"],
            env=env,
        )
        assert result.returncode == 0, result.stderr
        assert '"would_exit": 5' in result.stdout, result.stdout


def test_a_dry_run_over_a_missing_destination_is_still_pure(tmp_path: Path) -> None:
    """The exit-1 arm of the same guarantee: predicting is not creating."""
    work = tmp_path / "work"
    work.mkdir()
    env, redirected = redirected_environment(tmp_path)

    with assert_pure(work, *redirected):
        result = run_harness(
            ["--dry-run", "write", "--target", str(work / "nope" / "doc.pdf"), "-o", "json"],
            env=env,
        )
        assert result.returncode == 0, result.stderr
        assert '"would_exit": 1' in result.stdout, result.stdout
    assert not (work / "nope").exists()


def test_a_refused_run_leaves_the_tree_untouched(tmp_path: Path) -> None:
    """A refusal is not a partial write. Nothing at all should have moved."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "doc.pdf").write_bytes(b"original")
    env, redirected = redirected_environment(tmp_path)

    before = snapshot(work, *redirected)
    result = run_harness(["write", "--target", str(work / "doc.pdf")], env=env)
    assert result.returncode == 5
    assert_unchanged(before, snapshot(work, *redirected))


# --------------------------------------------------------------------------- #
# AC9 — the fault hook is inert unless a test asks for it
# --------------------------------------------------------------------------- #


def test_the_fault_hook_is_inert_with_no_environment_set(tmp_path: Path) -> None:
    from pdf_toolkit.safety._faults import ENV_POINT, ENV_RENDEZVOUS, FAULT_POINTS, checkpoint

    assert ENV_POINT not in os.environ
    assert ENV_RENDEZVOUS not in os.environ

    workspace = tmp_path / "work"
    workspace.mkdir()
    os.utime(workspace, ns=(0, 0))
    with assert_pure(workspace):
        for point in FAULT_POINTS:
            checkpoint(point, str(workspace / "detail"))
            checkpoint("a name no writer uses")


def test_a_non_matching_fault_point_changes_nothing(tmp_path: Path) -> None:
    from pdf_toolkit.safety._faults import ENV_POINT, checkpoint

    workspace = tmp_path / "work"
    workspace.mkdir()
    os.utime(workspace, ns=(0, 0))
    os.environ[ENV_POINT] = "after_temp_create"
    try:
        with assert_pure(workspace):
            checkpoint("after_fsync")
    finally:
        del os.environ[ENV_POINT]
