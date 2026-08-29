"""``AtomicWriter`` — the gate, the temp, the sidecar, the replace, and §D8.

Two things are proven here that are easy to *state* and easy to get wrong.

**The dry-run gate is unforgettable.** It is the first statement of
``__enter__``, so a verb cannot skip it by forgetting to check a flag — there is
no code path into the writer that does not pass it, and the object handed back
raises rather than offering a path that leads nowhere. Asserted directly,
because "we will remember to check ``policy.dry_run``" is exactly the kind of
guarantee that survives one spec and then quietly does not.

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

import hashlib
import os
import sys
from pathlib import Path

import pytest

from pdf_toolkit import errors
from pdf_toolkit.cli.exit_codes import FAILURE, OK, REFUSED, USAGE
from pdf_toolkit.safety import TEMP_PREFIX, AtomicWriter, SafetyPolicy

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
    """The gate is FIRST. A dry run never reaches a filesystem check at all."""
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
