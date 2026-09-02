"""Path identity, containment and the planning refusals.

The theme is one question asked three ways: **are these two paths one file?**
The sibling product's MHC-81 guard answered it with ``abs()`` alone and, under a
symlinked ``$TMPDIR`` parent, called one file two — so every arm here is built
around an alias, not around two obviously different paths. A test that only ever
compared ``a.pdf`` with ``b.pdf`` would pass against a comparison that is wrong
in exactly the way that matters.

The second theme is the split between what is *compared* and what is *printed*.
Canonical form is a comparison key; every message echoes the path as the user
wrote it. That is asserted directly, because the failure is silent: nobody
notices a diagnostic naming ``/private/var/folders/...`` when they typed
``./out``, until they try to grep their own logs for the path they used.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pdf_toolkit import errors
from pdf_toolkit.cli.exit_codes import FAILURE, REFUSED
from pdf_toolkit.safety import (
    canonical,
    check_output_collisions,
    ensure_destination_writable,
    ensure_no_clobber,
    ensure_within,
    identity_key,
    same_destination,
)
from pdf_toolkit.safety.paths import declared_device, nearest_existing_ancestor, resolved_device

# --------------------------------------------------------------------------- #
# Identity across aliases
# --------------------------------------------------------------------------- #


def test_canonical_resolves_a_symlinked_parent(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(real)
    assert canonical(link / "doc.pdf") == canonical(real / "doc.pdf")


def test_canonical_is_computable_for_a_path_that_does_not_exist_yet(tmp_path: Path) -> None:
    """A destination is, by definition, not there yet. strict=False is required."""
    assert canonical(tmp_path / "nope" / "doc.pdf").is_absolute()


def test_two_names_for_one_inode_are_one_destination(tmp_path: Path) -> None:
    original = tmp_path / "a.pdf"
    original.write_bytes(b"x")
    hardlink = tmp_path / "b.pdf"
    os.link(original, hardlink)
    assert identity_key(original) == identity_key(hardlink)
    assert same_destination(original, hardlink)


def test_two_genuinely_distinct_paths_are_not_one_destination(tmp_path: Path) -> None:
    (tmp_path / "a.pdf").write_bytes(b"x")
    (tmp_path / "b.pdf").write_bytes(b"x")
    assert not same_destination(tmp_path / "a.pdf", tmp_path / "b.pdf")


# --------------------------------------------------------------------------- #
# Planned-output collisions (AC3)
# --------------------------------------------------------------------------- #


def test_an_alias_shaped_collision_is_detected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(real)
    with pytest.raises(errors.OutputCollisionError) as caught:
        check_output_collisions([real / "doc.pdf", link / "doc.pdf"])
    assert caught.value.exit_code == REFUSED


def test_a_hardlink_shaped_collision_is_detected(tmp_path: Path) -> None:
    first = tmp_path / "a.pdf"
    first.write_bytes(b"x")
    second = tmp_path / "b.pdf"
    os.link(first, second)
    with pytest.raises(errors.OutputCollisionError):
        check_output_collisions([first, second])


def test_distinct_outputs_do_not_collide(tmp_path: Path) -> None:
    check_output_collisions([tmp_path / "a.pdf", tmp_path / "b.pdf", tmp_path / "sub" / "a.pdf"])


def test_a_collision_message_echoes_both_paths_as_written(tmp_path: Path) -> None:
    """AC4. The canonical form is a key; it is never what the user reads back."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(real)
    as_written = f"{link}/doc.pdf"
    with pytest.raises(errors.OutputCollisionError) as caught:
        check_output_collisions([f"{real}/doc.pdf", as_written])
    assert as_written in caught.value.message
    assert caught.value.path == as_written


# --------------------------------------------------------------------------- #
# Containment (X-2: the resolved destination, not the invocation)
# --------------------------------------------------------------------------- #


def test_a_contained_destination_is_allowed(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    ensure_within(out_dir, out_dir / "doc.pdf")
    ensure_within(out_dir, out_dir / "nested" / "doc.pdf")
    ensure_within(out_dir, out_dir)


def test_a_destination_that_escapes_the_out_dir_is_refused(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    with pytest.raises(errors.OutputEscapesDirError) as caught:
        ensure_within(out_dir, out_dir / ".." / "escaped.pdf")
    assert caught.value.exit_code == REFUSED
    assert caught.value.kind == "refused"


def test_a_symlinked_out_dir_does_not_defeat_containment(tmp_path: Path) -> None:
    """Compared canonically, so a symlinked --out-dir cannot smuggle a path in."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(real)
    ensure_within(link, real / "doc.pdf")
    with pytest.raises(errors.OutputEscapesDirError):
        ensure_within(link, tmp_path / "elsewhere.pdf")


def test_containment_refusal_echoes_the_path_as_written(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    as_written = f"{out_dir}/../escaped.pdf"
    with pytest.raises(errors.OutputEscapesDirError) as caught:
        ensure_within(out_dir, as_written)
    assert as_written in caught.value.message


# --------------------------------------------------------------------------- #
# No-clobber and destination writability
# --------------------------------------------------------------------------- #


def test_an_existing_target_is_refused_without_force(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"x")
    with pytest.raises(errors.TargetExistsError) as caught:
        ensure_no_clobber(target, force=False)
    assert caught.value.exit_code == REFUSED


def test_force_and_in_place_both_suppress_the_clobber_check(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"x")
    ensure_no_clobber(target, force=True)
    ensure_no_clobber(target, force=False, in_place=True)


def test_a_dangling_symlink_still_counts_as_occupied(tmp_path: Path) -> None:
    """Replacing a dangling link still destroys an entry the user created."""
    link = tmp_path / "doc.pdf"
    link.symlink_to(tmp_path / "missing.pdf")
    with pytest.raises(errors.TargetExistsError):
        ensure_no_clobber(link, force=False)


def test_a_missing_destination_directory_is_a_failure_not_a_refusal(tmp_path: Path) -> None:
    with pytest.raises(errors.DestinationUnwritableError) as caught:
        ensure_destination_writable(tmp_path / "nope")
    assert caught.value.exit_code == FAILURE


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="running with uid 0: directory permissions cannot make a write fail",
)
def test_an_unwritable_destination_directory_is_reported(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with pytest.raises(errors.DestinationUnwritableError) as caught:
            ensure_destination_writable(locked)
        assert caught.value.exit_code == FAILURE
    finally:
        locked.chmod(0o700)


def test_writability_messages_echo_the_path_as_written(tmp_path: Path) -> None:
    with pytest.raises(errors.DestinationUnwritableError) as caught:
        ensure_destination_writable(tmp_path / "resolved", as_written="./out")
    assert "./out" in caught.value.message


# --------------------------------------------------------------------------- #
# Device identity, which the cross-filesystem warning is built on
# --------------------------------------------------------------------------- #


def test_a_plain_directory_reports_one_device(tmp_path: Path) -> None:
    ordinary = tmp_path / "sub"
    ordinary.mkdir()
    assert declared_device(ordinary / "doc.pdf") == resolved_device(ordinary)


def test_declared_device_does_not_follow_the_final_symlink(tmp_path: Path) -> None:
    """lstat on the deepest existing ancestor is what makes the check meaningful."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(real)
    assert declared_device(link / "doc.pdf") == os.lstat(link).st_dev


# --------------------------------------------------------------------------- #
# `nearest_existing_ancestor` (PDF-18 Design D4) -- the read-only walk the
# `--out-dir` unwritable-parent prediction is built on.
# --------------------------------------------------------------------------- #


def test_nearest_existing_ancestor_returns_the_path_itself_when_it_exists(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "already-here"
    existing.mkdir()
    assert nearest_existing_ancestor(existing) == existing.resolve()


def test_nearest_existing_ancestor_climbs_to_the_deepest_existing_directory(
    tmp_path: Path,
) -> None:
    """`--out-dir a/b/c` where none of `a/b/c` exists yet -- the walk must
    stop at `tmp_path` itself, the deepest thing that is actually there."""
    absent = tmp_path / "a" / "b" / "c"
    assert nearest_existing_ancestor(absent) == tmp_path.resolve()


def test_nearest_existing_ancestor_stops_at_a_file_blocking_the_walk(
    tmp_path: Path,
) -> None:
    """The `EEXIST`-as-file family (`fa5736f2ae`): a regular file sitting
    where a directory component was expected is itself the "nearest existing
    ancestor" -- the caller's job is to notice it is not a directory."""
    blocker = tmp_path / "blocker.file"
    blocker.write_bytes(b"x")
    absent = blocker / "sub" / "out"
    ancestor = nearest_existing_ancestor(absent)
    assert ancestor == blocker.resolve()
    assert not ancestor.is_dir()


def test_nearest_existing_ancestor_over_the_out_dir_itself_that_is_a_file(
    tmp_path: Path,
) -> None:
    """`--out-dir blocker.file`, no `sub` component at all -- the out-dir
    path itself is the nearest existing ancestor of itself."""
    blocker = tmp_path / "blocker.file"
    blocker.write_bytes(b"x")
    assert nearest_existing_ancestor(blocker) == blocker.resolve()


def test_nearest_existing_ancestor_is_computable_for_a_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mirrors `canonical`'s own contract: a destination that does not exist
    yet, spelled relatively, must still resolve to an absolute answer."""
    monkeypatch.chdir(tmp_path)
    ancestor = nearest_existing_ancestor(Path("new") / "deeper")
    assert ancestor == tmp_path.resolve()
    assert ancestor.is_absolute()


def test_nearest_existing_ancestor_never_touches_the_filesystem(tmp_path: Path) -> None:
    """Read-only by construction: nothing named in the walk may come to
    exist merely by having been asked about (the AC9/AC10 purity property
    this function's own caller relies on)."""
    before = sorted(tmp_path.iterdir())
    nearest_existing_ancestor(tmp_path / "never" / "created" / "here")
    after = sorted(tmp_path.iterdir())
    assert before == after == []


def test_nearest_existing_ancestor_falls_back_to_the_root_when_nothing_stats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The root always exists on every real filesystem, so the walk's
    post-loop fallback is unreachable in practice -- proven rather than
    pragma'd around (PDF-06:236's own anti-gaming rule: unreachable-in-
    practice is a test to write, not a line to exclude): `Path.exists()` is
    monkeypatched to say "no" about EVERYTHING, including the root, and the
    walk must still terminate with an answer instead of raising or looping
    forever."""
    import pathlib

    monkeypatch.setattr(pathlib.Path, "exists", lambda self: False)
    absent = tmp_path / "a" / "b"
    result = nearest_existing_ancestor(absent)
    assert result == Path(absent).expanduser().absolute().parents[-1]
