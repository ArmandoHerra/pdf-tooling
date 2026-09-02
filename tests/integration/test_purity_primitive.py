"""The ``--dry-run`` purity primitive, and the negative controls that make it real.

``PLAN.md`` §10 calls dry-run purity *the single most important test in the
suite, because it is the guarantee users act on*. Which means the most valuable
thing this file contains is not the purity assertion — it is the **nine** planted
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
# AC5 — the negative controls. NINE of them, not the six this comment claimed
# from PDF-04's landing until PDF-19 counted them (2026-09-02): the six named
# `control_one`…`control_six`, plus create-then-delete, symlink retarget, and
# `assert_unchanged` naming every difference. `test_control_six_...` keeps its
# name -- that ordinal is the control's index, not the population size.
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


# --------------------------------------------------------------------------- #
# PDF-19 — the instrument, taken apart (Design §D3).
#
# Re-running the nine negative controls only proves they still pass. `PDF-19`'s
# premise is that a strong-LOOKING instrument is not evidence until it has been
# seen to fail, so each comparator dimension is ABLATED and exactly the control
# that depends on it is confirmed to go blind. A dimension whose removal changes
# nothing is carried by the comparator without earning its place, and a reader
# will trust it anyway.
#
# `Entry` is a frozen slotted dataclass with SEVEN fields; SIX are compared.
# `dev` is recorded and never compared -- measured at 7522e3e against
# `fs_snapshot._FIELDS` (`:186-193`), not transcribed.
#
# Observed transitions, 2026-09-02, all three:
#   remove `ino`        -> control five goes blind ("assert 'inode' in set()")
#   stop yielding dirs  -> the create-then-delete control goes blind
#   remove `mtime_ns`   -> control four AND the create-then-delete control blind
#   ADD `atime`         -> the atime control reds AND five legitimate dry-run
#                          purity arms red, because a dry run legitimately reads
# --------------------------------------------------------------------------- #

import shutil  # noqa: E402
import subprocess  # noqa: E402

import pytest  # noqa: E402

import fs_snapshot  # noqa: E402
import registry  # noqa: E402
from fs_snapshot import Entry  # noqa: E402


def _ablate(monkeypatch: pytest.MonkeyPatch, dropped: str) -> None:
    """Run the comparator with one dimension removed from `_FIELDS`."""
    remaining = tuple(row for row in fs_snapshot._FIELDS if row[0] != dropped)
    assert len(remaining) == len(fs_snapshot._FIELDS) - 1, f"{dropped} is not a compared field"
    monkeypatch.setattr(fs_snapshot, "_FIELDS", remaining)


def test_the_comparator_compares_six_of_seven_recorded_fields() -> None:
    """`dev` is recorded and deliberately never compared: a device id changes
    when a test's own `tmp_path` moves, which is not a purity fact."""
    assert len(Entry.__dataclass_fields__) == 7
    assert [name for name, _ in fs_snapshot._FIELDS] == [
        "ino",
        "sha256",
        "mode",
        "size",
        "symlink_target",
        "mtime_ns",
    ]
    assert "dev" not in {name for name, _ in fs_snapshot._FIELDS}


def test_ablating_ino_blinds_the_identical_content_replacement_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ino` is the ONLY signal that catches a file replaced with byte-identical
    content -- exactly the shape `os.replace` produces."""
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"aaaa")
    stamp = os.stat(target).st_mtime_ns
    before = snapshot(target)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"aaaa")
    os.replace(replacement, target)
    os.utime(target, ns=(stamp, stamp))

    assert "inode" in {item.kind for item in diff(before, snapshot(target))}
    _ablate(monkeypatch, "ino")
    assert diff(before, snapshot(target)) == [], (
        "removing `ino` did not blind the control it exists for -- the dimension is "
        "either redundant or the control is measuring something else"
    )


def test_ablating_directory_traversal_blinds_the_create_then_delete_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Directory mtime is the only signal that catches a create-then-delete
    INSIDE the run -- a verb that writes a temp file, notices `--dry-run` late,
    and tidies up."""
    workspace = tmp_path / "work"
    workspace.mkdir()
    os.utime(workspace, ns=(0, 0))
    before = snapshot(workspace)
    scratch = workspace / "transient"
    scratch.write_bytes(b"x")
    scratch.unlink()
    assert any(item.kind == "mtime" for item in diff(before, snapshot(workspace)))

    real_walk = fs_snapshot._walk
    monkeypatch.setattr(
        fs_snapshot,
        "_walk",
        lambda root: (p for p in real_walk(root) if not p.is_dir() or p.is_symlink()),
    )
    blinded = diff(before, snapshot(workspace))
    assert not any(item.kind == "mtime" for item in blinded), (
        f"the comparator still saw a create-then-delete with directories excluded: {blinded}"
    )


def test_ablating_mtime_blinds_the_create_then_delete_control_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second half of the same transition: directory traversal is useless
    without the timestamp that traversal exists to read."""
    workspace = tmp_path / "work"
    workspace.mkdir()
    os.utime(workspace, ns=(0, 0))
    before = snapshot(workspace)
    scratch = workspace / "transient"
    scratch.write_bytes(b"x")
    scratch.unlink()

    _ablate(monkeypatch, "mtime_ns")
    assert diff(before, snapshot(workspace)) == []


def test_adding_atime_would_make_a_legitimate_dry_run_impure(tmp_path: Path) -> None:
    """The exclusion is a DECISION, not laziness, and this is what it costs.

    A dry run legitimately reads: it opens documents to count pages. Comparing
    access time would assert "nothing was read", which is the wrong guarantee
    and would flake on `relatime`. Measured here without touching the product:
    the same before/after pair that is pure under `_FIELDS` reports an `atime`
    difference the moment access time is compared.
    """
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"aaaa")
    before = snapshot(target)
    access_before = os.stat(target).st_atime_ns
    os.utime(target, ns=(2_000_000_000, os.stat(target).st_mtime_ns))
    access_after = os.stat(target).st_atime_ns

    assert access_after == 2_000_000_000 != access_before, (
        "the probe did not actually move access time -- the ablation would prove nothing"
    )
    assert diff(before, snapshot(target)) == [], (
        "the shipped comparator must ignore atime; a dry run legitimately reads"
    )
    assert before.entries[str(target)].mtime_ns == snapshot(target).entries[str(target)].mtime_ns


@pytest.mark.parametrize("umask_value", [0o022, 0o002], ids=["umask-022", "umask-002"])
def test_the_mode_control_is_umask_independent(tmp_path: Path, umask_value: int) -> None:
    """`85dd844`'s fix, re-derived under BOTH umasks rather than inherited.

    This control was already vacuous once on this exact file: it chmod'ed to
    `0o600` and back to `0o644`, which under a 002 umask is a real change and
    under CI's 022 umask is a no-op, so it detected nothing on all eight `test`
    legs. A single-umask re-run is not a re-derivation.
    """
    previous = os.umask(umask_value)
    try:
        target = tmp_path / "doc.pdf"
        target.write_bytes(b"aaaa")
        target.chmod(0o644)
        before = snapshot(target)
        target.chmod(0o600)
        assert "mode" in {item.kind for item in diff(before, snapshot(target))}
    finally:
        os.umask(previous)


# --------------------------------------------------------------------------- #
# PDF-19 — `redirected_environment()` is load-bearing, proven both ways.
#
# It lives in `fs_snapshot.py:234-260` and is called explicitly per test; there
# is no conftest fixture. Without the pair below, "the tree was unchanged" is a
# statement about `tmp_path` and NOT about the machine.
#
# Both halves run entirely inside `tmp_path`. The operator's real `$HOME` is
# never an operand -- which is not a stylistic point: while re-deriving `PDF-04`
# AC9, PDF-19's own planted mutation wrote one byte into the real `$HOME`
# because `checkpoint()`'s in-process arms do NOT redirect, and the purity
# discipline is what caught it.
# --------------------------------------------------------------------------- #


#: One byte into `$HOME`, and nothing else.
_HOME_PROBE = "import os, pathlib; pathlib.Path(os.environ['HOME'], 'probe').write_text('x')"


def _probe_writes_into_home(env: dict[str, str], work: Path) -> None:
    """A child process that writes exactly one byte into ITS `$HOME`."""
    subprocess.run(
        [sys.executable, "-c", _HOME_PROBE],
        env=env,
        cwd=str(work),
        check=True,
        capture_output=True,
    )


def test_a_home_write_is_invisible_without_redirection_and_caught_with_it(
    tmp_path: Path,
) -> None:
    env, redirected = redirected_environment(tmp_path)
    work = tmp_path / "work"
    work.mkdir()

    # The roots a test would snapshot if it had NOT called redirected_environment.
    unredirected_roots = (work,)
    before_narrow = snapshot(*unredirected_roots)
    before_wide = snapshot(work, *redirected)

    _probe_writes_into_home(env, work)

    assert diff(before_narrow, snapshot(*unredirected_roots)) == [], (
        "a working-tree-only snapshot must NOT see the $HOME write -- if it does, this "
        "pair proves nothing about redirection"
    )
    wide = diff(before_wide, snapshot(work, *redirected))
    assert any(item.kind == "added" and item.path.endswith("/probe") for item in wide), (
        f"redirected_environment did not make the $HOME write visible: {[str(d) for d in wide]}"
    )


# --------------------------------------------------------------------------- #
# PDF-19 — the `README.md:74` purity census.
#
#   "`--dry-run` plans and reports; it writes nothing, anywhere."
#
# That claim is UNCONDITIONAL. Its mechanization,
# `tests/test_cli_contract.py::test_c9_unconditional_dry_run_purity`, is
# parameterized over `MUTATING` -- verbs whose module transitively imports
# `AtomicWriter` (`tests/registry.py`'s `is_mutating`) -- so by construction the
# population EXCLUDES `doctor`, `info` and `version`.
#
# Measured at 7522e3e, on this host, under `redirected_environment(tmp_path)`:
#   info    --dry-run  ->  0 differences   (also with `-o json`)
#   version --dry-run  ->  0 differences   (also with `-o json`)
#   doctor  --dry-run  ->  2 differences   ($HOME/.config added, $HOME mtime moved)
#
# Causation, not co-location: with `soffice`/`libreoffice` removed from `PATH`
# the same invocation produces ZERO differences. `SofficeOfficeAdapter.probe()`
# spawns `soffice --version`, which creates `$HOME/.config` (B-100 /
# `ba07fdfb56`). So the claim is CONDITIONAL on the host, and the instrument
# that mechanizes it cannot see the one member known to violate it.
#
# **That is a README honesty finding, and `doctor`'s behaviour is PDF-20's**
# (B-075). This file does not soften `README.md:74`, does not widen
# `tests/registry.py`, and does not touch `cli/cmd_doctor.py`. What it adds is
# the measurement, kept honest by a probe that must be caught.
# --------------------------------------------------------------------------- #

#: `doctor`'s known, filed impurity. Anything OUTSIDE this signature is a new
#: defect rather than the one already on the record.
DOCTOR_KNOWN_IMPURITY: tuple[str, ...] = (".config",)


def _dry_run_differences(verb: tuple[str, ...], base: Path, extra: list[str]) -> list[str]:
    env, redirected = redirected_environment(base)
    work = base / "work"
    work.mkdir(exist_ok=True)
    before = snapshot(work, *redirected)
    result = subprocess.run(
        [*registry.console_script(), *verb, "--dry-run", *extra],
        env=env,
        cwd=str(work),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return [str(item) for item in diff(before, snapshot(work, *redirected))]


def test_the_population_the_unconditional_claim_is_not_measured_over() -> None:
    """`VERBS - MUTATING`, named rather than counted.

    Red: this fails the moment `is_mutating` reclassifies any of the three,
    which is precisely the change `cli/common.py:175-198` records as having been
    avoided once already -- and which would have started failing `test_c9`.
    """
    verbs = registry.discover_verbs()
    unmeasured = sorted(" ".join(v.path) for v in verbs if not v.is_mutating)
    assert unmeasured == ["doctor", "info", "version"], unmeasured
    assert len(verbs) == 26
    assert len([v for v in verbs if v.is_mutating]) == 23


@pytest.mark.parametrize("verb", [("info",), ("version",)], ids=["info", "version"])
def test_a_non_mutating_verb_outside_the_c9_population_is_still_pure(
    verb: tuple[str, ...], corpus: object, tmp_path: Path
) -> None:
    extra: list[str] = []
    if verb == ("info",):
        work = tmp_path / "work"
        work.mkdir()
        document = work / "in.pdf"
        shutil.copy2(corpus.path("single_page"), document)  # type: ignore[attr-defined]
        extra = [str(document)]
    differences = _dry_run_differences(verb, tmp_path, extra)
    assert differences == [], differences


def test_doctors_dry_run_impurity_stays_inside_its_filed_signature(tmp_path: Path) -> None:
    """`doctor` is the counterexample to `README.md:74`, and it is PDF-20's.

    This asserts neither "pure" nor "impure": on a host without LibreOffice the
    run IS pure, and pinning either outcome would be a claim about the host. It
    asserts the SHAPE -- every difference is inside the filed
    `$HOME/.config` signature (B-075 / B-100 / `ba07fdfb56`). A `doctor` that
    started writing anywhere else reds here, which is the property worth
    holding while the fix belongs to another spec.
    """
    differences = _dry_run_differences(("doctor",), tmp_path, [])
    unexplained = [
        item
        for item in differences
        if not any(marker in item for marker in DOCTOR_KNOWN_IMPURITY)
        and not item.endswith("/home: mtime")
        and "/home: mtime " not in item
    ]
    assert unexplained == [], (
        "doctor --dry-run wrote outside its filed $HOME/.config signature: "
        f"{unexplained} (full set: {differences})"
    )


def test_the_purity_census_probe_is_caught(tmp_path: Path) -> None:
    """The census instrument's own red.

    Without this, "info and version are pure" is a green that proves nothing:
    a `_dry_run_differences` that snapshotted the wrong roots, or a
    `redirected_environment` that pointed `$HOME` somewhere unsnapshotted,
    would report zero differences for a verb that wrote a megabyte.
    """
    env, redirected = redirected_environment(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    before = snapshot(work, *redirected)
    _probe_writes_into_home(env, work)
    differences = diff(before, snapshot(work, *redirected))
    assert differences, "the census probe was not caught -- the census measures nothing"
    assert any(item.kind == "added" for item in differences)


# --------------------------------------------------------------------------- #
# PDF-19 — the control COUNT, mechanised so it cannot rot again.
#
# Both docstrings said "six" from PDF-04's landing (2026-08-29) to PDF-19
# (2026-09-02), and X-171 records the cost: a brief inherited the docstring and
# undercounted the control set, which invites a later spec to rebuild what
# already exists. A number in prose that nothing checks is a claim.
# --------------------------------------------------------------------------- #

#: Every arm here plants a mutation and asserts `diff()` DETECTS it. The count
#: is the population the two docstrings quote.
NEGATIVE_CONTROLS: tuple[str, ...] = (
    "test_control_one_an_added_file_is_detected",
    "test_control_two_a_removed_file_is_detected",
    "test_control_three_content_changed_with_mtime_restored_is_detected",
    "test_control_four_mtime_changed_with_identical_content_is_detected",
    "test_control_five_a_replacement_with_identical_content_is_detected",
    "test_control_six_a_mode_change_is_detected",
    "test_a_create_then_delete_inside_the_run_is_caught_by_directory_mtime",
    "test_a_symlink_change_is_detected",
    "test_assert_unchanged_names_every_difference",
)


def test_every_named_negative_control_exists() -> None:
    """Red: rename or delete one and this names it, instead of the count
    quietly describing a population that changed."""
    module = sys.modules[__name__]
    missing = [name for name in NEGATIVE_CONTROLS if not hasattr(module, name)]
    assert missing == [], f"NEGATIVE_CONTROLS names arms this module does not define: {missing}"


def test_both_docstrings_quote_the_measured_control_count() -> None:
    """The anti-rot pin for the two carriers PDF-19 corrected.

    `tests/fs_snapshot.py` and this module's own docstring both quote the
    number. Red: change either back to "six" -- or add a tenth control without
    updating them -- and this fails naming the file.
    """
    spelled = {6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven"}
    word = spelled[len(NEGATIVE_CONTROLS)]
    carriers = {
        "tests/fs_snapshot.py": (TESTS_DIR / "fs_snapshot.py").read_text(),
        "tests/integration/test_purity_primitive.py": Path(__file__).read_text(),
    }
    for name, text in carriers.items():
        assert f"**{word}**" in text, (
            f"{name} does not quote the measured negative-control count "
            f"({len(NEGATIVE_CONTROLS)} -> '**{word}**')"
        )
