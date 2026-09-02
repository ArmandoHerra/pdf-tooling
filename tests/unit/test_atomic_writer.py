"""``AtomicWriter`` — the gate, the temp, the sidecar, the replace, and §D8.

Two things are proven here that are easy to *state* and easy to get wrong.

**The dry-run gate is unforgettable.** It sits immediately above the first
mutating call, so a verb cannot skip it by forgetting to check a flag — there is
no code path into the writer that does not pass it, and the object handed back
raises rather than offering a path that leads nowhere. Asserted directly,
because "we will remember to check ``policy.dry_run``" is exactly the kind of
guarantee that survives one spec and then quietly does not.

**And the plan runs above the gate, in both modes (X-67).** Which is the same
argument applied once more: real runs are protected by construction, dry runs
would be protected only by convention. A verb author cannot forget the gate, but
*can* forget to call the planning helpers — so a ``--dry-run`` that skipped the
plan predicted nothing against an occupied target while the real run refused with
exit 5. The section at the bottom of this file pins the prediction against the
outcome for all three conditions the writer owns, and pins it by comparing the
*same payload object* rather than two shapes that agree by luck.

**The temp lives beside the destination.** Not in ``/tmp``. That is not a
preference: ``os.replace`` is atomic within a filesystem and nowhere else, so a
temp in the system temp directory turns every write into a cross-device copy and
silently demotes the product's central promise. The test reads the temp's parent
while the writer holds it, rather than assuming it.

The §D8 exit-code table is at the bottom, asserted twice: once on the class, and
once through a real child process, so the arms prove the *actual* mapping rather
than a parallel one that happens to agree.
"""

from __future__ import annotations

import ast
import hashlib
import os
import sys
from pathlib import Path

import pytest

from pdf_toolkit import errors
from pdf_toolkit.cli.exit_codes import FAILURE, OK, REFUSED, USAGE
from pdf_toolkit.safety import TEMP_PREFIX, AtomicWriter, SafetyPolicy
from pdf_toolkit.safety.atomic import PlannedOutputs, plan_filesystem, plan_output_set

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from atomic_harness import run_harness  # noqa: E402


def make_policy(**overrides: object) -> SafetyPolicy:
    values: dict[str, object] = {
        "dry_run": False,
        "force": False,
        "in_place": False,
        "backup": True,
        "assume_yes": False,
        "is_tty": False,
        "threads": 1,
    }
    values.update(overrides)
    return SafetyPolicy(**values)  # type: ignore[arg-type]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def supports_hard_links(directory: Path) -> bool:
    probe = directory / ".link-probe"
    probe.write_bytes(b"x")
    linked = directory / ".link-probe-2"
    try:
        os.link(probe, linked)
    except OSError:
        return False
    finally:
        probe.unlink(missing_ok=True)
        linked.unlink(missing_ok=True)
    return True


# --------------------------------------------------------------------------- #
# The dry-run gate
# --------------------------------------------------------------------------- #


def test_a_dry_run_writer_refuses_to_hand_out_a_path(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    with AtomicWriter(target, policy=make_policy(dry_run=True)) as writer:
        assert writer.is_dry_run
        with pytest.raises(RuntimeError, match="dry-run"):
            _ = writer.path
    assert not target.exists()


def test_a_dry_run_creates_nothing_at_all(tmp_path: Path) -> None:
    before = sorted(p.name for p in tmp_path.iterdir())
    with AtomicWriter(tmp_path / "doc.pdf", policy=make_policy(dry_run=True)):
        pass
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_the_gate_fires_even_when_the_run_would_have_been_refused(tmp_path: Path) -> None:
    """The gate holds over a target the real run would refuse.

    Superseded in one respect by X-67 and rewritten rather than deleted: a dry
    run *does* now reach the read-only filesystem checks, so the old claim that
    it "never reaches a filesystem check at all" is no longer the contract. What
    this test still pins is the part that never changed — entering is not
    raising, and the occupied file is byte-identical afterwards. The prediction
    it now also computes is asserted below.
    """
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original")
    with AtomicWriter(target, policy=make_policy(dry_run=True)) as writer:
        assert writer.is_dry_run
    assert target.read_bytes() == b"original"


# --------------------------------------------------------------------------- #
# The temp file
# --------------------------------------------------------------------------- #


def test_the_temp_lives_beside_the_destination_and_carries_the_prefix(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "doc.pdf"
    target.parent.mkdir()
    with AtomicWriter(target, policy=make_policy()) as writer:
        temp = writer.path
        assert temp.parent == target.parent.resolve()
        assert temp.parent != Path(os.environ.get("TMPDIR", "/tmp")).resolve()
        assert temp.name.startswith(TEMP_PREFIX)
        temp.write_bytes(b"payload")
    assert target.read_bytes() == b"payload"


def test_a_handled_error_leaves_no_residue(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    with pytest.raises(ValueError, match="boom"):
        with AtomicWriter(target, policy=make_policy()) as writer:
            writer.path.write_bytes(b"half")
            raise ValueError("boom")
    assert not target.exists()
    assert [p.name for p in tmp_path.iterdir()] == []


def test_a_symlinked_parent_still_puts_the_temp_beside_the_real_file(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(real)
    with AtomicWriter(link / "doc.pdf", policy=make_policy()) as writer:
        assert writer.path.parent == real.resolve()
        writer.path.write_bytes(b"x")
    assert (real / "doc.pdf").read_bytes() == b"x"


# --------------------------------------------------------------------------- #
# No-clobber (plan acceptance signal a)
# --------------------------------------------------------------------------- #


def test_an_existing_target_is_refused_and_left_byte_identical(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original bytes")
    before = sha256(target)
    with pytest.raises(errors.TargetExistsError):
        with AtomicWriter(target, policy=make_policy()) as writer:
            writer.path.write_bytes(b"replacement")
    assert sha256(target) == before


def test_force_overwrites_with_the_new_bytes(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original bytes")
    with AtomicWriter(target, policy=make_policy(force=True)) as writer:
        writer.path.write_bytes(b"replacement")
    assert target.read_bytes() == b"replacement"


# --------------------------------------------------------------------------- #
# --in-place and the .bak sidecar
# --------------------------------------------------------------------------- #


def test_in_place_writes_a_byte_identical_sidecar(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original bytes")
    before = sha256(target)
    with AtomicWriter(target, policy=make_policy(in_place=True)) as writer:
        writer.path.write_bytes(b"rewritten")
    sidecar = tmp_path / "doc.pdf.bak"
    assert sidecar.exists()
    assert sha256(sidecar) == before
    assert target.read_bytes() == b"rewritten"


def test_the_sidecar_keeps_the_original_inode_when_linking_is_possible(tmp_path: Path) -> None:
    if not supports_hard_links(tmp_path):
        pytest.skip("hard links are unavailable on this temporary directory")
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original bytes")
    original_inode = target.stat().st_ino
    with AtomicWriter(target, policy=make_policy(in_place=True)) as writer:
        writer.path.write_bytes(b"rewritten")
    assert (tmp_path / "doc.pdf.bak").stat().st_ino == original_inode
    assert target.stat().st_ino != original_inode


def test_an_existing_sidecar_is_refused_and_nothing_moves(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original bytes")
    sidecar = tmp_path / "doc.pdf.bak"
    sidecar.write_bytes(b"an older backup")
    target_before, sidecar_before = sha256(target), sha256(sidecar)

    with pytest.raises(errors.BackupExistsError):
        with AtomicWriter(target, policy=make_policy(in_place=True)) as writer:
            writer.path.write_bytes(b"rewritten")

    assert sha256(target) == target_before
    assert sha256(sidecar) == sidecar_before


def test_force_replaces_a_stale_sidecar(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original bytes")
    (tmp_path / "doc.pdf.bak").write_bytes(b"an older backup")
    with AtomicWriter(target, policy=make_policy(in_place=True, force=True)) as writer:
        writer.path.write_bytes(b"rewritten")
    assert (tmp_path / "doc.pdf.bak").read_bytes() == b"original bytes"


def test_no_backup_writes_no_sidecar(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original bytes")
    with AtomicWriter(target, policy=make_policy(in_place=True, backup=False)) as writer:
        writer.path.write_bytes(b"rewritten")
    assert not (tmp_path / "doc.pdf.bak").exists()
    assert target.read_bytes() == b"rewritten"


def test_in_place_on_a_target_that_does_not_exist_yet_writes_no_sidecar(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    with AtomicWriter(target, policy=make_policy(in_place=True)) as writer:
        writer.path.write_bytes(b"fresh")
    assert target.read_bytes() == b"fresh"
    assert not (tmp_path / "doc.pdf.bak").exists()


# --------------------------------------------------------------------------- #
# The §D8 exit-code table (AC18)
# --------------------------------------------------------------------------- #

#: Every row of Design §D8. The class half of the assertion; the subprocess half
#: is below, except ``ConfirmationDeclinedError``, which needs a terminal and is
#: driven through a real pty in ``tests/unit/test_confirm.py``.
D8_TABLE = (
    (errors.TargetExistsError, REFUSED, "refused"),
    (errors.OutputCollisionError, REFUSED, "refused"),
    (errors.BackupExistsError, REFUSED, "refused"),
    (errors.OutputEscapesDirError, REFUSED, "refused"),
    (errors.ConfirmationRequiredError, REFUSED, "refused"),
    (errors.ConfirmationDeclinedError, REFUSED, "refused"),
    (errors.BackupWithoutInPlaceError, USAGE, "usage"),
    (errors.DestinationUnwritableError, FAILURE, "failure"),
)


@pytest.mark.parametrize(
    ("error_class", "code", "kind"),
    D8_TABLE,
    ids=[row[0].__name__ for row in D8_TABLE],
)
def test_each_safety_error_carries_its_documented_exit_code(
    error_class: type[errors.PdfToolkitError],
    code: int,
    kind: str,
) -> None:
    instance = error_class("message")
    assert instance.exit_code == code
    assert instance.kind == kind
    assert instance.to_dict()["code"] == code


def test_the_table_covers_every_safety_error_the_package_exports() -> None:
    """A row added to errors.py without a row here would go unasserted."""
    covered = {row[0].__name__ for row in D8_TABLE}
    exported = {
        name
        for name in errors.__all__
        if name.endswith("Error") and name not in {"PdfToolkitError"}
    }
    spine = exported - {
        "AuthError",
        "EngineMissingError",
        "FailureError",
        "NoInputError",
        "PageRangeError",
        "RefusedError",
        "UsageError",
    }
    assert spine == covered


def test_the_harness_returns_the_documented_status_for_a_missing_directory(
    tmp_path: Path,
) -> None:
    result = run_harness(["write", "--target", str(tmp_path / "nope" / "doc.pdf")])
    assert result.returncode == FAILURE, result.stderr


def test_the_harness_returns_5_for_an_existing_target(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original")
    before = sha256(target)
    result = run_harness(["write", "--target", str(target)])
    assert result.returncode == REFUSED, result.stderr
    assert sha256(target) == before


def test_the_harness_returns_5_for_a_planned_output_collision(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "alias").symlink_to(real)
    result = run_harness(
        [
            "collide",
            "--output",
            str(real / "doc.pdf"),
            "--output",
            str(tmp_path / "alias" / "doc.pdf"),
        ]
    )
    assert result.returncode == REFUSED, result.stderr


def test_the_harness_returns_5_for_an_existing_sidecar(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original")
    (tmp_path / "doc.pdf.bak").write_bytes(b"older")
    result = run_harness(["write", "--target", str(target), "--in-place"])
    assert result.returncode == REFUSED, result.stderr


def test_the_harness_returns_5_for_an_escaping_destination(tmp_path: Path) -> None:
    """X-2: the invocation is exit 2; the resolved destination is exit 5."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = run_harness(
        ["contain", "--out-dir", str(out_dir), "--candidate", f"{out_dir}/../escaped.pdf"]
    )
    assert result.returncode == REFUSED, result.stderr


def test_the_harness_returns_2_for_no_backup_without_in_place(tmp_path: Path) -> None:
    result = run_harness(["write", "--target", str(tmp_path / "doc.pdf"), "--no-backup"])
    assert result.returncode == USAGE, result.stderr
    assert "--no-backup" in result.stderr
    assert "--in-place" in result.stderr
    assert not (tmp_path / "doc.pdf").exists()


def test_the_harness_returns_0_for_a_completed_dry_run(tmp_path: Path) -> None:
    result = run_harness(["--dry-run", "write", "--target", str(tmp_path / "doc.pdf")])
    assert result.returncode == OK, result.stderr
    assert not (tmp_path / "doc.pdf").exists()


def test_a_refusal_under_json_goes_to_stdout_with_its_code(tmp_path: Path) -> None:
    import json

    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original")
    result = run_harness(["-o", "json", "write", "--target", str(target)])
    assert result.returncode == REFUSED
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == REFUSED
    assert payload["error"]["kind"] == "refused"


# --------------------------------------------------------------------------- #
# X-67 — the plan runs under --dry-run, and the preview stops lying
#
# The defect this section exists to prevent recurring: the gate used to be the
# first statement of __enter__, so _plan() never ran under --dry-run and a dry
# run could not predict the three conditions this module owns. Against an
# occupied target it entered cleanly and reported {"written": false}, while the
# real run refused with exit 5. Every arm below therefore asserts the PREDICTION
# against the OUTCOME rather than against a hand-written expectation, because a
# preview is only worth anything if it agrees with the run it previews.
# --------------------------------------------------------------------------- #


def test_a_dry_run_over_an_occupied_target_predicts_the_refusal(tmp_path: Path) -> None:
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original")
    before = sha256(target)

    with AtomicWriter(target, policy=make_policy(dry_run=True)) as writer:
        assert writer.is_dry_run
        assert writer.would_exit == REFUSED
        assert isinstance(writer.planned_refusal, errors.TargetExistsError)

    assert sha256(target) == before


def test_a_dry_run_over_a_missing_destination_predicts_exit_one(tmp_path: Path) -> None:
    """Exit 1, not 5. The filesystem cannot accept the write; nothing declined."""
    with AtomicWriter(tmp_path / "nope" / "doc.pdf", policy=make_policy(dry_run=True)) as writer:
        assert writer.would_exit == FAILURE
        assert isinstance(writer.planned_refusal, errors.DestinationUnwritableError)
    assert not (tmp_path / "nope").exists()


def test_a_clean_plan_predicts_nothing(tmp_path: Path) -> None:
    """The non-vacuity control: would_exit must not be a constant 5."""
    with AtomicWriter(tmp_path / "fresh.pdf", policy=make_policy(dry_run=True)) as writer:
        assert writer.would_exit == OK
        assert writer.planned_refusal is None
        assert writer.plan_item() == {
            "target": str(tmp_path / "fresh.pdf"),
            "would_exit": OK,
            "warnings": [],
        }


def test_force_makes_the_dry_run_predict_no_refusal(tmp_path: Path) -> None:
    """The prediction tracks the policy, not merely the state of the disk."""
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original")
    with AtomicWriter(target, policy=make_policy(dry_run=True, force=True)) as writer:
        assert writer.would_exit == OK
        assert writer.planned_refusal is None


def test_a_real_run_still_raises_and_captures_nothing(tmp_path: Path) -> None:
    """The hard requirement: real-run behaviour is UNCHANGED by X-67.

    Capture is a dry-run affordance only. A real run raises the same class with
    the same message it always did, and never leaves a swallowed refusal behind
    for a caller to have to remember to check.
    """
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original")
    writer = AtomicWriter(target, policy=make_policy())
    with pytest.raises(errors.TargetExistsError, match="pass --force to overwrite it"):
        with writer:
            pass
    assert writer.planned_refusal is None
    assert writer.would_exit == OK


def test_the_prediction_stops_where_the_real_run_would_have_stopped(tmp_path: Path) -> None:
    """Both conditions true at once must predict the FIRST one, as ordered.

    A real run checks no-clobber before writability, so an occupied target in an
    unwritable directory is exit 5 and never reaches exit 1. A dry run that
    reported the second refusal, or both, would be lying in the other direction.
    """
    directory = tmp_path / "locked"
    directory.mkdir()
    target = directory / "doc.pdf"
    target.write_bytes(b"original")
    directory.chmod(0o500)
    try:
        if os.access(directory, os.W_OK):
            pytest.skip("this user can write to a mode-0500 directory (root?)")
        with AtomicWriter(target, policy=make_policy(dry_run=True)) as writer:
            assert writer.would_exit == REFUSED
            assert isinstance(writer.planned_refusal, errors.TargetExistsError)
    finally:
        directory.chmod(0o700)


def test_the_plan_item_uses_the_key_name_the_ruling_fixed(tmp_path: Path) -> None:
    """``would_exit`` is the contract's spelling; a rename is a breaking change."""
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original")
    with AtomicWriter(target, policy=make_policy(dry_run=True)) as writer:
        item = writer.plan_item()
        refusal = writer.planned_refusal
    assert refusal is not None
    assert item["would_exit"] == REFUSED
    assert item["would_refuse"] == refusal.to_dict()


def test_a_dry_run_writer_still_refuses_to_hand_out_a_path_after_planning(
    tmp_path: Path,
) -> None:
    """Planning does not open a temp. There is still nowhere to write."""
    with AtomicWriter(tmp_path / "doc.pdf", policy=make_policy(dry_run=True)) as writer:
        with pytest.raises(RuntimeError, match="dry-run"):
            _ = writer.path


# --- the machine-readable surface, through a real process ------------------- #


def test_the_dry_run_json_predicts_the_refusal_the_real_run_produces(tmp_path: Path) -> None:
    """THE regression test for this defect, and it compares run against run.

    The dry run's ``would_refuse`` is asserted equal to the real run's ``error``
    — the same payload, not a restatement of it. Nothing can drift the preview
    away from the outcome without failing here.
    """
    import json

    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original")

    preview = run_harness(["--dry-run", "write", "--target", str(target), "-o", "json"])
    assert preview.returncode == OK, preview.stderr
    predicted = json.loads(preview.stdout)
    assert predicted["would_exit"] == REFUSED
    assert predicted["written"] is False

    actual = run_harness(["write", "--target", str(target), "-o", "json"])
    assert actual.returncode == REFUSED, actual.stderr

    assert predicted["would_exit"] == actual.returncode
    assert predicted["would_refuse"] == json.loads(actual.stdout)["error"]
    assert target.read_bytes() == b"original"


def test_the_dry_run_json_predicts_the_unwritable_destination_too(tmp_path: Path) -> None:
    import json

    target = tmp_path / "nope" / "doc.pdf"

    preview = run_harness(["--dry-run", "write", "--target", str(target), "-o", "json"])
    assert preview.returncode == OK, preview.stderr
    predicted = json.loads(preview.stdout)

    actual = run_harness(["write", "--target", str(target), "-o", "json"])
    assert actual.returncode == FAILURE, actual.stderr

    assert predicted["would_exit"] == FAILURE == actual.returncode
    assert predicted["would_refuse"] == json.loads(actual.stdout)["error"]


def test_a_dry_run_exits_zero_even_when_it_predicts_a_refusal(tmp_path: Path) -> None:
    """X-67 ruled exit 0 and this cycle does not mirror the predicted status.

    Whether ``cmd --dry-run && cmd`` should short-circuit is a real ergonomic
    question and it is filed rather than answered here. This test is what makes
    answering it later a deliberate, visible change instead of a silent one.
    """
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"original")
    result = run_harness(["--dry-run", "write", "--target", str(target)])
    assert result.returncode == OK, result.stderr


def test_the_predicted_status_is_absent_from_a_real_run_payload(tmp_path: Path) -> None:
    """A real run reports what happened; only a plan reports what would happen."""
    import json

    result = run_harness(["write", "--target", str(tmp_path / "doc.pdf"), "-o", "json"])
    assert result.returncode == OK, result.stderr
    payload = json.loads(result.stdout)
    assert payload["written"] is True
    assert "would_exit" not in payload


# --------------------------------------------------------------------------- #
# B-054 -- plan_output_set: the X-67 filesystem tier, extended to a
# multi-target --out-dir run. `split`/`rasterize` never called AtomicWriter
# during planning, so `--dry-run` over an occupied `--out-dir` target (or an
# unwritable one) entered cleanly while the real run refused with exit 5/1 --
# the same preview-lies defect class X-67 fixed once, recurring on a verb
# shape a single-destination `AtomicWriter` cannot see. Every arm below
# compares the PREDICTION against a real run's OUTCOME, mirroring the
# discipline of the X-67 section above rather than inventing a second one.
# --------------------------------------------------------------------------- #


def test_plan_output_set_a_clean_plan_predicts_nothing(tmp_path: Path) -> None:
    """The non-vacuity control: would_exit must not be a constant refusal."""
    out_dir = tmp_path / "out"
    targets = [out_dir / "a.pdf", out_dir / "b.pdf"]
    plan = plan_output_set(targets, out_dir=out_dir, policy=make_policy(dry_run=True))
    assert plan.refusal is None
    assert plan.would_exit == OK
    assert plan.would_refuse is None
    assert not out_dir.exists()  # dry run: _ensure_out_dir stays a no-op


def test_plan_output_set_predicts_an_occupied_target(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    occupied = out_dir / "b.pdf"
    occupied.write_bytes(b"already here")
    targets = [out_dir / "a.pdf", occupied]

    plan = plan_output_set(targets, out_dir=out_dir, policy=make_policy(dry_run=True))
    assert isinstance(plan.refusal, errors.TargetExistsError)
    assert plan.would_exit == REFUSED
    assert plan.would_refuse == plan.refusal.to_dict()

    # The OUTCOME: a real run over the identical plan raises the SAME class,
    # same message, and leaves the occupied file untouched.
    with pytest.raises(errors.TargetExistsError, match="pass --force to overwrite it"):
        plan_output_set(targets, out_dir=out_dir, policy=make_policy(dry_run=False))
    assert occupied.read_bytes() == b"already here"


def test_plan_output_set_predicts_an_unwritable_out_dir(tmp_path: Path) -> None:
    """Exit 1, not 5 -- the filesystem cannot accept the write; nothing declined."""
    out_dir = tmp_path / "locked"
    out_dir.mkdir()
    out_dir.chmod(0o500)
    try:
        if os.access(out_dir, os.W_OK):
            pytest.skip("this user can write to a mode-0500 directory (root?)")
        targets = [out_dir / "a.pdf"]
        plan = plan_output_set(targets, out_dir=out_dir, policy=make_policy(dry_run=True))
        assert isinstance(plan.refusal, errors.DestinationUnwritableError)
        assert plan.would_exit == FAILURE
        assert plan.would_refuse == plan.refusal.to_dict()

        with pytest.raises(errors.DestinationUnwritableError):
            plan_output_set(targets, out_dir=out_dir, policy=make_policy(dry_run=False))
    finally:
        out_dir.chmod(0o700)


def test_plan_output_set_a_nonexistent_out_dir_is_not_predicted_as_a_refusal(
    tmp_path: Path,
) -> None:
    """Trap 1 (B-054): the real run would CREATE this directory and succeed.

    Under --dry-run, `_ensure_out_dir` is a no-op, so a non-existent `out_dir`
    stays non-existent -- checking writability on it would raise
    DestinationUnwritableError for an ordinary, honourable run. The
    writability tier is skipped entirely when out_dir does not exist, so an
    otherwise-clean plan predicts nothing.
    """
    out_dir = tmp_path / "not-created-yet"
    targets = [out_dir / "a.pdf"]
    plan = plan_output_set(targets, out_dir=out_dir, policy=make_policy(dry_run=True))
    assert plan.refusal is None
    assert plan.would_exit == OK
    assert not out_dir.exists()


def test_plan_output_set_a_real_run_creates_the_out_dir_and_predicts_nothing(
    tmp_path: Path,
) -> None:
    """The OUTCOME side of the Trap 1 arm above: the real run's own
    create-then-succeed path is exactly what the dry run's silence predicted."""
    out_dir = tmp_path / "created-for-real"
    targets = [out_dir / "a.pdf"]
    plan = plan_output_set(targets, out_dir=out_dir, policy=make_policy())
    assert plan.refusal is None
    assert out_dir.is_dir()


def test_plan_output_set_stops_at_the_first_refusal(tmp_path: Path) -> None:
    """Two conditions true at once must predict the FIRST one, as ordered.

    The real run checks out_dir writability before any target's no-clobber,
    so an occupied target inside an unwritable out_dir predicts
    DestinationUnwritableError and never reaches TargetExistsError -- a dry
    run that reported the second refusal, or both, would be lying in the
    other direction (mirroring AtomicWriter._plan's own ordering guarantee).
    """
    out_dir = tmp_path / "locked"
    out_dir.mkdir()
    occupied = out_dir / "a.pdf"
    occupied.write_bytes(b"x")
    out_dir.chmod(0o500)
    try:
        if os.access(out_dir, os.W_OK):
            pytest.skip("this user can write to a mode-0500 directory (root?)")
        plan = plan_output_set([occupied], out_dir=out_dir, policy=make_policy(dry_run=True))
        assert isinstance(plan.refusal, errors.DestinationUnwritableError)
    finally:
        out_dir.chmod(0o700)


def test_plan_output_set_a_real_run_over_a_clean_plan_raises_nothing(tmp_path: Path) -> None:
    """Real-run behaviour is UNCHANGED by B-054: a clean plan just returns."""
    out_dir = tmp_path / "out"
    targets = [out_dir / "a.pdf", out_dir / "b.pdf"]
    plan = plan_output_set(targets, out_dir=out_dir, policy=make_policy())
    assert plan.refusal is None
    assert plan.would_exit == OK
    assert plan.would_refuse is None


# --------------------------------------------------------------------------- #
# PDF-18 AC5 -- `PlannedOutputs` gains `message`, `refused`, `detail()`: the
# three members every one of the eight collapsed `_FilesystemPlan` copies
# defined identically.
# --------------------------------------------------------------------------- #


def test_planned_outputs_a_clean_plan_reports_no_message_and_is_not_refused() -> None:
    clean = PlannedOutputs(refusal=None)
    assert clean.message is None
    assert clean.refused is False
    assert clean.detail() == {"would_exit": OK}


def test_planned_outputs_a_refused_plan_carries_the_refusal_message_and_detail(
    tmp_path: Path,
) -> None:
    refusal = errors.DestinationUnwritableError("nope", path=str(tmp_path))
    refused = PlannedOutputs(refusal=refusal)
    assert refused.message == "nope"
    assert refused.refused is True
    assert refused.detail() == {"would_exit": FAILURE, "would_refuse": refusal.to_dict()}


# --------------------------------------------------------------------------- #
# PDF-18 (`d55b302668`/`fa5736f2ae`) -- `_ensure_out_dir`'s own errno family,
# reached ONLY through the public `plan_output_set`/`plan_filesystem` API,
# never by calling the private helper directly.
#
# §D4's table, and which arm covers it here:
#   EACCES              -- parent 0o500, out-dir absent (the U tier)
#   ENOTDIR              -- a path component is a file
#   EEXIST-as-file        -- the out-dir path is itself a file
#   ENAMETOOLONG          -- a path component exceeds the filesystem's limit
#   EROFS                 -- skipped; not producible without root (§D4/X-153)
# --------------------------------------------------------------------------- #


def test_plan_output_set_predicts_a_nonexistent_out_dir_under_an_unwritable_parent(
    tmp_path: Path,
) -> None:
    """`d55b302668`'s own U-tier repro, at the unit level. Before PDF-18: the
    dry run predicted OK (`would_exit 0`) while a real run crashed with an
    unhandled `PermissionError` -- `_ensure_out_dir`'s dry branch was a total
    no-op. Both `plan.refusal` and the real run's own raise now agree."""
    parent = tmp_path / "locked"
    parent.mkdir()
    out_dir = parent / "newdir"
    targets = [out_dir / "a.pdf"]
    parent.chmod(0o500)
    try:
        if os.access(parent, os.W_OK):
            pytest.skip("this user can write to a mode-0500 directory (root?)")
        plan = plan_output_set(targets, out_dir=out_dir, policy=make_policy(dry_run=True))
        assert isinstance(plan.refusal, errors.DestinationUnwritableError)
        assert plan.would_exit == FAILURE
        assert not out_dir.exists(), "the dry run must not create the directory it refuses"

        with pytest.raises(errors.DestinationUnwritableError):
            plan_output_set(targets, out_dir=out_dir, policy=make_policy(dry_run=False))
        assert not out_dir.exists(), "a refused real run must not leave a partial directory"
    finally:
        parent.chmod(0o700)


def test_plan_output_set_real_run_wraps_enotdir_instead_of_crashing(tmp_path: Path) -> None:
    """`out-dir`'s PARENT component is a file (`ENOTDIR`): the unguarded
    `mkdir` used to raise `NotADirectoryError` uncaught; it is now a coded
    `DestinationUnwritableError` in both modes."""
    blocker = tmp_path / "blocker.file"
    blocker.write_bytes(b"x")
    out_dir = blocker / "sub"
    targets = [out_dir / "a.pdf"]

    plan = plan_output_set(targets, out_dir=out_dir, policy=make_policy(dry_run=True))
    assert isinstance(plan.refusal, errors.DestinationUnwritableError)

    with pytest.raises(errors.DestinationUnwritableError):
        plan_output_set(targets, out_dir=out_dir, policy=make_policy(dry_run=False))
    assert blocker.read_bytes() == b"x", "the blocking file must survive untouched"


def test_plan_output_set_real_run_wraps_eexist_as_file_instead_of_crashing(
    tmp_path: Path,
) -> None:
    """`fa5736f2ae` at the unit level: `--out-dir` names an existing regular
    file. `Path.mkdir(exist_ok=True)` only suppresses `FileExistsError` when
    the existing path IS a directory (``except OSError: if not exist_ok or
    not self.is_dir(): raise``); against a file it still raises -- now a
    coded refusal instead of an uncaught traceback, and `-o json` gets a
    structured envelope instead of empty stdout."""
    blocker = tmp_path / "blocker.file"
    blocker.write_bytes(b"i am a regular file")
    targets = [blocker / "a.pdf"]

    plan = plan_output_set(targets, out_dir=blocker, policy=make_policy(dry_run=True))
    assert isinstance(plan.refusal, errors.DestinationUnwritableError)
    assert plan.would_exit == FAILURE

    with pytest.raises(errors.DestinationUnwritableError):
        plan_output_set(targets, out_dir=blocker, policy=make_policy(dry_run=False))
    assert blocker.read_bytes() == b"i am a regular file"


def test_plan_output_set_predicts_a_path_component_that_is_too_long(tmp_path: Path) -> None:
    """`ENAMETOOLONG`, predicted rather than performed (PDF-18 Design D4
    implementation note 2, resolution (a))."""
    try:
        limit = os.pathconf(str(tmp_path), "PC_NAME_MAX")
    except (OSError, ValueError, AttributeError):  # pragma: no cover - platform-dependent
        pytest.skip("PC_NAME_MAX is not available on this platform")
    too_long = "x" * (limit + 1)
    out_dir = tmp_path / too_long
    targets = [out_dir / "a.pdf"]

    plan = plan_output_set(targets, out_dir=out_dir, policy=make_policy(dry_run=True))
    assert isinstance(plan.refusal, errors.DestinationUnwritableError)
    # `out_dir.exists()` itself raises OSError for a too-long component (the
    # same trap `nearest_existing_ancestor` and `_predict_out_dir_creation`
    # are built to avoid) -- listing the parent is the safe way to prove
    # nothing was created.
    assert list(tmp_path.iterdir()) == []

    with pytest.raises(errors.DestinationUnwritableError):
        plan_output_set(targets, out_dir=out_dir, policy=make_policy(dry_run=False))


def test_plan_output_set_skips_the_too_long_check_when_pathconf_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PDF-18 Design D4 implementation note 2, resolution (a)'s own fallback:
    ``os.pathconf`` does not exist on every platform (Windows has none at
    all). Proven rather than pragma'd around (PDF-06:236): ``os.pathconf``
    is monkeypatched to raise, and the prediction must skip that ONE tier
    silently -- an otherwise-clean plan over a writable, non-existent
    ``out_dir`` still predicts nothing, because directory writability
    (checked first) is unaffected."""
    import os as os_module

    def _unavailable(*_args: object, **_kwargs: object) -> int:
        raise OSError("pathconf not supported on this platform")

    monkeypatch.setattr(os_module, "pathconf", _unavailable)
    out_dir = tmp_path / "new-dir"
    targets = [out_dir / "a.pdf"]
    plan = plan_output_set(targets, out_dir=out_dir, policy=make_policy(dry_run=True))
    assert plan.refusal is None
    assert not out_dir.exists()


# --------------------------------------------------------------------------- #
# PDF-18 AC2 -- all 12 `plan_filesystem` call sites under `ops/` pass the
# IDENTICAL keyword set, over a `Sequence[Path]` first argument.
# --------------------------------------------------------------------------- #

_OPS_DIR = Path(__file__).resolve().parents[2] / "src" / "pdf_toolkit" / "ops"


def _plan_filesystem_call_sites() -> list[tuple[str, ast.Call]]:
    """Every ``plan_filesystem(...)`` call under ``src/pdf_toolkit/ops/``."""
    found: list[tuple[str, ast.Call]] = []
    for path in sorted(_OPS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "plan_filesystem"
            ):
                found.append((path.name, node))
    return found


def test_ac2_every_ops_call_site_passes_the_identical_keyword_set() -> None:
    """AC1's own census (`grep -rn "def _plan_filesystem" src/`) recorded 12
    call sites across the eight collapsed modules; this walks the AST
    instead of trusting the count, and pins the SHAPE those 12 calls share.

    Red: plant a call missing ``kind=``; the walk fails.
    """
    calls = _plan_filesystem_call_sites()
    assert len(calls) >= 12, f"found only {len(calls)} plan_filesystem call site(s) under ops/"

    modules = {module for module, _ in calls}
    assert len(modules) == 8, (
        f"expected all eight collapsed modules to call plan_filesystem, saw {sorted(modules)}"
    )

    for module, call in calls:
        assert len(call.args) == 1, (
            f"{module}:{call.lineno}: expected exactly one positional argument "
            f"(a Sequence[Path]), got {len(call.args)}"
        )
        keywords = {kw.arg for kw in call.keywords}
        assert keywords == {"out_dir", "policy", "kind"}, (
            f"{module}:{call.lineno}: keyword set was {sorted(keywords)}, expected "
            "{'kind', 'out_dir', 'policy'}"
        )


# --------------------------------------------------------------------------- #
# PDF-18 AC14 -- the composed precedence of §D6, pinned at the
# `plan_filesystem` level. Swapping any adjacent pair below reddens its test.
# --------------------------------------------------------------------------- #


def test_plan_filesystem_precedence_ancestor_unwritable_beats_occupied_out_dir_target(
    tmp_path: Path,
) -> None:
    """§D6 step 1/2 beat step 3, out_dir is not None: `plan_filesystem` calls
    `plan_output_set` first and returns its refusal unchanged, so the
    ordering `test_plan_output_set_stops_at_the_first_refusal` already pins
    (unwritable `out_dir` beats an occupied target inside it) holds at this
    level too."""
    parent = tmp_path / "locked"
    parent.mkdir()
    occupied = parent / "a.pdf"
    occupied.write_bytes(b"x")
    parent.chmod(0o500)
    try:
        if os.access(parent, os.W_OK):
            pytest.skip("this user can write to a mode-0500 directory (root?)")
        plan = plan_filesystem(
            [occupied], out_dir=parent, policy=make_policy(dry_run=True), kind="pdf"
        )
        assert isinstance(plan.refusal, errors.DestinationUnwritableError)
    finally:
        parent.chmod(0o700)


def test_plan_filesystem_out_dir_exists_defers_to_ensure_destination_writable(
    tmp_path: Path,
) -> None:
    """§D6 step 1's own no-op branch, out_dir is not None: when ``out_dir``
    already exists (as anything at all -- a file included), `_ensure_out_dir`'s
    prediction defers to step 2 (`ensure_destination_writable`) rather than
    also predicting, because step 2 ALREADY handles "exists but is a file"
    and "exists but unwritable" correctly and AC6 pins that message
    byte-for-byte across the refactor
    (`tests/integration/test_text_tables_cli.py::
    test_ac24_a_dry_run_predicts_an_unwritable_destination_refusal` is the
    live proof: it compares the dry prediction against the real run's own
    error payload for an out_dir that already exists, chmod 0o500, and both
    must come from the SAME tier or the comparison fails)."""
    blocker = tmp_path / "blocker.file"
    blocker.write_bytes(b"x")
    targets = [blocker / "a.pdf"]
    plan = plan_filesystem(targets, out_dir=blocker, policy=make_policy(dry_run=True), kind="pdf")
    assert isinstance(plan.refusal, errors.DestinationUnwritableError)
    assert plan.message == f"destination directory does not exist: {blocker}"


def test_plan_filesystem_real_run_still_wraps_the_mkdir_attempt_on_an_existing_file(
    tmp_path: Path,
) -> None:
    """The real-run OUTCOME side of the arm above: `_ensure_out_dir`'s real
    branch always attempts the ``mkdir`` regardless of whether ``out_dir``
    already exists, so `fa5736f2ae`'s own trigger IS caught on a real run
    even though the dry-run prediction reaches it through step 2 instead of
    step 1 -- both are `DestinationUnwritableError`, exit 1, which is what
    OR-7 (read per X-185 as exit code AND envelope KIND, not literal message
    text) requires."""
    blocker = tmp_path / "blocker.file"
    blocker.write_bytes(b"x")
    targets = [blocker / "a.pdf"]
    with pytest.raises(errors.DestinationUnwritableError) as caught:
        plan_filesystem(targets, out_dir=blocker, policy=make_policy(dry_run=False), kind="pdf")
    assert caught.value.exit_code == FAILURE
    assert caught.value.kind == "failure"


def test_plan_filesystem_ancestor_walk_catches_a_non_directory_component_at_0o755(
    tmp_path: Path,
) -> None:
    """PDF-18 design note 1's own literal concern: a blocking component with
    execute permission (0o755) would pass an ``os.access(W_OK | X_OK)``-only
    check, so the ancestor walk must ask "is this a directory?" FIRST. Here
    ``out_dir`` itself does NOT exist (only its blocking ancestor does), so
    this exercises `_ensure_out_dir`'s ancestor-walk branch directly, unlike
    the "out_dir exists" arm above."""
    blocker = tmp_path / "blocker.file"
    blocker.write_bytes(b"x")
    blocker.chmod(0o755)
    out_dir = blocker / "sub"
    targets = [out_dir / "a.pdf"]

    plan = plan_filesystem(targets, out_dir=out_dir, policy=make_policy(dry_run=True), kind="pdf")
    assert isinstance(plan.refusal, errors.DestinationUnwritableError)

    with pytest.raises(errors.DestinationUnwritableError):
        plan_filesystem(targets, out_dir=out_dir, policy=make_policy(dry_run=False), kind="pdf")


def test_plan_filesystem_precedence_no_clobber_beats_the_writer_tier(tmp_path: Path) -> None:
    """§D6 step 3 beats step 4, out_dir is None: per-target no-clobber
    (`plan_output_set`'s own loop) fires before the writer tier
    (`plan_filesystem`'s own widening). Both conditions armed at once --
    an occupied target AND an unwritable parent -- so a swapped order would
    read `TargetExistsError` as `DestinationUnwritableError`."""
    parent = tmp_path / "locked"
    parent.mkdir()
    target = parent / "a.pdf"
    target.write_bytes(b"already here")
    parent.chmod(0o500)
    try:
        if os.access(parent, os.W_OK):
            pytest.skip("this user can write to a mode-0500 directory (root?)")
        plan = plan_filesystem([target], out_dir=None, policy=make_policy(dry_run=True), kind="pdf")
        assert isinstance(plan.refusal, errors.TargetExistsError)
    finally:
        parent.chmod(0o700)


def test_plan_filesystem_widens_the_writer_tier_into_both_modes(tmp_path: Path) -> None:
    """PDF-18 Design D3 -- the firing moment. `out_dir is None`, target's
    parent unwritable: the real run must raise the SAME class the dry run
    predicts, which is the property `d231fbcec4` violated for `encrypt`/
    `decrypt` before every `_plan_filesystem` copy was unified into one
    firing moment."""
    parent = tmp_path / "locked"
    parent.mkdir()
    target = parent / "a.pdf"
    parent.chmod(0o500)
    try:
        if os.access(parent, os.W_OK):
            pytest.skip("this user can write to a mode-0500 directory (root?)")
        dry = plan_filesystem([target], out_dir=None, policy=make_policy(dry_run=True), kind="pdf")
        assert isinstance(dry.refusal, errors.DestinationUnwritableError)

        with pytest.raises(errors.DestinationUnwritableError):
            plan_filesystem([target], out_dir=None, policy=make_policy(dry_run=False), kind="pdf")
    finally:
        parent.chmod(0o700)
