"""PDF-127 -- ``meta set --clear-all --in-place`` is refused unless ``--no-backup`` or ``-y``.

Ledger ``3ce318e517`` (medium, surface-contract), backlog ``B-454``, ruling
``OR-44``. Before this spec the run exited ``0`` with ``ok`` and ``warnings: []``
and left ``<name>.bak`` beside the "cleaned" file holding the complete original
/Info and XMP. ``encrypt --in-place`` already refuses the same shape (exit 5);
this makes ``--clear-all --in-place`` the second such place.

ORACLE. The CLI runs as a subprocess, non-TTY (``stdin=DEVNULL``), with
``HOME``/``TMPDIR`` redirected into ``tmp_path``. "Nothing written" is
``tests/fs_snapshot.py``'s whole-tree comparison over the working directory,
``$HOME`` and ``$TMPDIR`` (dotfiles and the writer's temp files included) plus
the input's sha256. The refusal and warning texts are imported, never copied.

Every guard here was driven red before landing; the commit body records each
``mutation -> failing node -> assertion``.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import itertools
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import pikepdf
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

import fs_snapshot  # noqa: E402
from pdf_tooling.cli import cmd_meta_set  # noqa: E402
from pdf_tooling.cli.cmd_meta_set import (  # noqa: E402
    CLEARED_BACKUP_REFUSAL,
    cleared_metadata_backup_refusal,
)
from pdf_tooling.errors import RefusedError  # noqa: E402
from pdf_tooling.ops import metadata as ops_metadata  # noqa: E402
from pdf_tooling.ops.metadata import CLEARED_BACKUP_WARNING_SUFFIX, meta_set_run  # noqa: E402
from pdf_tooling.safety.policy import SafetyPolicy  # noqa: E402
from registry import console_script  # noqa: E402

pytestmark = pytest.mark.e2e

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
README: Final[Path] = REPO_ROOT / "README.md"
SENTINELS: Final[tuple[str, ...]] = (
    "E-REALISTIC-CREATOR-4N",
    "E-REALISTIC-TITLE-2B",
    "E-TOOL-SENTINEL-8J",
)
SIDECAR_EXISTS: Final[str] = "already exists beside E.pdf; pass --force to replace the sidecar"


# --------------------------------------------------------------------------- #
# Fixture + runner
# --------------------------------------------------------------------------- #


def build_e(path: Path) -> Path:
    """`3ce318e517`'s REPRO fixture: a blank page, three XMP sentinels, /Author."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Author"] = "E-AUTHOR"
    with pdf.open_metadata() as meta:
        meta["dc:creator"] = ["E-REALISTIC-CREATOR-4N"]
        meta["dc:title"] = "E-REALISTIC-TITLE-2B"
        meta["xmp:CreatorTool"] = "E-TOOL-SENTINEL-8J"
    pdf.save(path)
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Cell:
    """One fresh working directory with a fresh ``E.pdf`` and a redirected env."""

    def __init__(self, base: Path) -> None:
        self.dir = base / "w"
        self.dir.mkdir()
        self.pdf = build_e(self.dir / "E.pdf")
        self.env, self.extra_roots = fs_snapshot.redirected_environment(base)
        self.sha_before = sha(self.pdf)

    def snap(self) -> fs_snapshot.Snapshot:
        return fs_snapshot.snapshot(self.dir, *self.extra_roots)

    def run(self, *args: str, fmt: str = "json") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*console_script(), "-o", fmt, *args],
            cwd=self.dir,
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )

    def run_refused_untouched(
        self, *args: str, fmt: str = "json"
    ) -> subprocess.CompletedProcess[str]:
        before = self.snap()
        proc = self.run(*args, fmt=fmt)
        fs_snapshot.assert_unchanged(before, self.snap())
        assert sha(self.pdf) == self.sha_before
        return proc

    @property
    def bak(self) -> Path:
        return self.dir / "E.pdf.bak"

    def listing(self) -> list[str]:
        return sorted(p.name for p in self.dir.iterdir())


@pytest.fixture
def cell(tmp_path: Path) -> Cell:
    return Cell(tmp_path)


def meta_get_json(cell: Cell, name: str) -> dict[str, Any]:
    proc = cell.run("meta", "get", name)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


REFUSAL_ENVELOPE: Final[dict[str, Any]] = {
    "schema_version": 1,
    "error": {"code": 5, "kind": "refused", "message": CLEARED_BACKUP_REFUSAL, "path": None},
}

CLEAR_IN_PLACE: Final[tuple[str, ...]] = ("meta", "set", "E.pdf", "--clear-all", "--in-place")


# --------------------------------------------------------------------------- #
# AC1 -- default refuses before anything is written
# --------------------------------------------------------------------------- #


def test_ac1_default_refuses_with_exit_5_and_writes_nothing(cell: Cell) -> None:
    proc = cell.run_refused_untouched(*CLEAR_IN_PLACE)
    assert proc.returncode == 5
    assert json.loads(proc.stdout) == REFUSAL_ENVELOPE
    assert proc.stderr == ""
    assert not cell.bak.exists()
    assert cell.listing() == ["E.pdf"]


def test_ac1_table_mode_speaks_on_stderr_only(cell: Cell) -> None:
    proc = cell.run_refused_untouched(*CLEAR_IN_PLACE, fmt="table")
    assert proc.returncode == 5
    assert proc.stdout == ""
    assert proc.stderr.strip() == f"error: {CLEARED_BACKUP_REFUSAL}"


# --------------------------------------------------------------------------- #
# AC2 -- dry predicts the same 5, in encrypt's shape
# --------------------------------------------------------------------------- #


def test_ac2_dry_run_predicts_the_same_refusal_in_encrypts_shape(cell: Cell) -> None:
    proc = cell.run_refused_untouched("--dry-run", *CLEAR_IN_PLACE)
    assert proc.returncode == 5
    payload = json.loads(proc.stdout)
    assert payload["dry_run"] is True
    assert payload["exit_code"] == 5
    assert payload["warnings"] == []
    assert payload["schema_version"] == 1
    (item,) = payload["items"]
    assert item["ok"] is False
    assert item["exit_code"] == 5
    assert item["message"] == CLEARED_BACKUP_REFUSAL
    assert item["bytes_after"] is None
    assert item["detail"]["would_exit"] == 5
    assert item["detail"]["planned_refusal"] == "RefusedError"
    assert item["detail"]["would_refuse"] == REFUSAL_ENVELOPE["error"]

    # Key sets against `encrypt --in-place --dry-run` on the same fixture.
    pw = cell.dir / "owner.pw"
    pw.write_text("owner-secret\n")
    enc = cell.run_refused_untouched(
        "--dry-run", "encrypt", "E.pdf", "--in-place", "--owner-password-file", str(pw)
    )
    assert enc.returncode == 5
    (enc_item,) = json.loads(enc.stdout)["items"]
    assert set(item) == set(enc_item)
    encrypt_only = {"algorithm", "allow"}
    shared = set(enc_item["detail"]) - encrypt_only
    assert shared <= set(item["detail"]) | {"owner_password_source"}, (shared, set(item["detail"]))
    assert set(item["detail"]) - shared <= {"password_source"}


# --------------------------------------------------------------------------- #
# AC3 -- the truth table is exact
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("in_place", "clear_all", "backup", "assume_yes"),
    list(itertools.product([False, True], repeat=4)),
)
def test_ac3_truth_table_over_all_sixteen_combinations(
    in_place: bool, clear_all: bool, backup: bool, assume_yes: bool
) -> None:
    got = cleared_metadata_backup_refusal(
        in_place=in_place, clear_all=clear_all, backup=backup, assume_yes=assume_yes
    )
    if in_place and clear_all and backup and not assume_yes:
        assert isinstance(got, RefusedError)
        assert got.message == CLEARED_BACKUP_REFUSAL
        assert got.exit_code == 5
    else:
        assert got is None


# --------------------------------------------------------------------------- #
# AC4 -- --no-backup keeps no copy
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("extra", [(), ("-y",)], ids=["no-backup", "no-backup+yes"])
def test_ac4_no_backup_keeps_no_copy(cell: Cell, extra: tuple[str, ...]) -> None:
    proc = cell.run(*CLEAR_IN_PLACE, "--no-backup", *extra)
    assert proc.returncode == 0, proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["items"][0]["message"] == "ok"
    assert not cell.bak.exists()
    assert cell.listing() == ["E.pdf"]
    assert not any(".bak" in w for w in payload["warnings"])
    assert meta_get_json(cell, "E.pdf")["info"] == {}


def test_ac4_dry_run_with_no_backup_predicts_zero(cell: Cell) -> None:
    proc = cell.run_refused_untouched("--dry-run", *CLEAR_IN_PLACE, "--no-backup")
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["items"][0]["message"] == "planned: meta set"


# --------------------------------------------------------------------------- #
# AC5 -- -y keeps the .bak, knowingly
# --------------------------------------------------------------------------- #


def test_ac5_yes_keeps_the_bak_and_warns_once(cell: Cell) -> None:
    cell.pdf.chmod(0o640)
    original = cell.pdf.read_bytes()
    proc = cell.run(*CLEAR_IN_PLACE, "-y")
    assert proc.returncode == 0, proc.stdout
    assert cell.bak.read_bytes() == original
    assert cell.bak.stat().st_mode & 0o777 == 0o640
    got = meta_get_json(cell, "E.pdf.bak")
    blob = json.dumps(got)
    for sentinel in SENTINELS:
        assert sentinel in blob
    warnings = json.loads(proc.stdout)["warnings"]
    assert len(warnings) == 1
    (warning,) = warnings
    assert warning.startswith(f"{cell.bak} "), warning
    assert warning.endswith(
        "still holds the original /Info and XMP that --clear-all removed; "
        "delete it if you do not want it"
    )
    assert warning.endswith(CLEARED_BACKUP_WARNING_SUFFIX)
    assert meta_get_json(cell, "E.pdf")["info"] == {}


def test_ac5_dry_run_under_yes_predicts_zero_without_the_warning(cell: Cell) -> None:
    proc = cell.run_refused_untouched("--dry-run", *CLEAR_IN_PLACE, "-y")
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["items"][0]["message"] == "planned: meta set"
    assert payload["warnings"] == []


# --------------------------------------------------------------------------- #
# AC6 -- everything that is not --clear-all --in-place is unchanged
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("flags", [("--title", "X"), ("--clear-producer",)])
def test_ac6_in_place_without_clear_all_is_unchanged(cell: Cell, flags: tuple[str, ...]) -> None:
    proc = cell.run("meta", "set", "E.pdf", *flags, "--in-place")
    assert proc.returncode == 0, proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["warnings"] == []
    assert payload["items"][0]["message"] == "ok"
    assert payload["items"][0]["detail"] == {"wrote_xmp": True}
    assert cell.bak.exists()


def test_ac6_clear_all_to_a_new_output_is_unchanged(cell: Cell) -> None:
    proc = cell.run("meta", "set", "E.pdf", "--clear-all", "-O", "out.pdf")
    assert proc.returncode == 0, proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["warnings"] == []
    assert cell.listing() == ["E.pdf", "out.pdf"]


# --------------------------------------------------------------------------- #
# AC7 -- --clear-all with a field set still refuses
# --------------------------------------------------------------------------- #


def test_ac7_clear_all_with_a_field_set_still_refuses(cell: Cell) -> None:
    proc = cell.run_refused_untouched(*CLEAR_IN_PLACE, "--title", "X")
    assert proc.returncode == 5
    assert json.loads(proc.stdout) == REFUSAL_ENVELOPE
    assert cell.listing() == ["E.pdf"]


def test_ac7_clear_all_with_a_field_set_and_no_backup_proceeds(cell: Cell) -> None:
    proc = cell.run(*CLEAR_IN_PLACE, "--title", "X", "--no-backup")
    assert proc.returncode == 0, proc.stdout
    assert not cell.bak.exists()


# --------------------------------------------------------------------------- #
# AC8 -- precedence
# --------------------------------------------------------------------------- #


def test_ac8a_the_gate_speaks_before_the_sidecar_exists_refusal(cell: Cell) -> None:
    cell.bak.write_bytes(b"1234")
    for args in (CLEAR_IN_PLACE, ("--dry-run", *CLEAR_IN_PLACE)):
        proc = cell.run_refused_untouched(*args)
        assert proc.returncode == 5
        payload = json.loads(proc.stdout)
        message = (
            payload["error"]["message"] if "error" in payload else payload["items"][0]["message"]
        )
        assert message == CLEARED_BACKUP_REFUSAL
    assert cell.bak.read_bytes() == b"1234"


def test_ac8b_under_yes_the_sidecar_exists_refusal_speaks(cell: Cell) -> None:
    cell.bak.write_bytes(b"1234")
    proc = cell.run_refused_untouched(*CLEAR_IN_PLACE, "-y")
    assert proc.returncode == 5
    error = json.loads(proc.stdout)["error"]
    assert error["message"].endswith(SIDECAR_EXISTS)
    assert error["path"] is not None
    assert cell.bak.read_bytes() == b"1234"


def test_ac8c_a_missing_input_is_still_exit_4(cell: Cell) -> None:
    proc = cell.run_refused_untouched("meta", "set", "nope.pdf", "--clear-all", "--in-place")
    assert proc.returncode == 4


def test_ac8d_out_dir_is_still_a_usage_error(cell: Cell) -> None:
    (cell.dir / "d").mkdir()
    proc = cell.run_refused_untouched(*CLEAR_IN_PLACE, "--out-dir", "d")
    assert proc.returncode == 2
    assert "does not accept --out-dir" in json.loads(proc.stdout)["error"]["message"]


def _encrypted_copy(cell: Cell) -> None:
    with pikepdf.open(cell.pdf) as pdf:
        pdf.save(
            cell.dir / "X.pdf",
            encryption=pikepdf.Encryption(user="user-pw", owner="owner-pw", R=6),
        )
    cell.sha_before = sha(cell.pdf)


def test_ac8e_on_an_encrypted_input_the_gate_speaks_before_password_resolvability(
    cell: Cell,
) -> None:
    _encrypted_copy(cell)
    base = ("meta", "set", "X.pdf", "--clear-all", "--in-place")
    before = cell.snap()
    real = cell.run(*base, "--allow-decrypted-output")
    dry = cell.run("--dry-run", *base, "--allow-decrypted-output")
    fs_snapshot.assert_unchanged(before, cell.snap())
    assert real.returncode == 5
    assert json.loads(real.stdout)["error"]["message"] == CLEARED_BACKUP_REFUSAL
    assert dry.returncode == 5
    assert json.loads(dry.stdout)["items"][0]["message"] == CLEARED_BACKUP_REFUSAL


def test_ac8e_prime_without_allow_decrypted_output_the_pdf115_refusal_speaks(cell: Cell) -> None:
    _encrypted_copy(cell)
    proc = cell.run("meta", "set", "X.pdf", "--clear-all", "--in-place")
    assert proc.returncode == 5
    message = json.loads(proc.stdout)["error"]["message"]
    assert message != CLEARED_BACKUP_REFUSAL
    assert "--allow-decrypted-output" in message


# --------------------------------------------------------------------------- #
# AC9 -- run-scoped; the batch rule holds
# --------------------------------------------------------------------------- #


def test_ac9_two_inputs_are_a_usage_error_and_write_nothing(cell: Cell) -> None:
    build_e(cell.dir / "B.pdf")
    proc = cell.run_refused_untouched("meta", "set", "E.pdf", "B.pdf", "--clear-all", "--in-place")
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["error"]["message"] == "Got unexpected extra argument(s) (B.pdf)"


def test_ac9_the_gate_is_computed_once_before_confirmation_and_the_run() -> None:
    source = Path(inspect.getsourcefile(cmd_meta_set) or "").read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "meta_set_command"
    )
    calls: list[ast.Call] = [n for n in ast.walk(func) if isinstance(n, ast.Call)]

    def named(name: str) -> list[ast.Call]:
        return [
            c
            for c in calls
            if (isinstance(c.func, ast.Name) and c.func.id == name)
            or (isinstance(c.func, ast.Attribute) and c.func.attr == name)
        ]

    gate = named("cleared_metadata_backup_refusal")
    confirm = named("require_confirmation")
    run = named("meta_set_run")
    assert len(gate) == 1 and len(confirm) == 1 and len(run) == 1
    key = lambda c: (c.lineno, c.col_offset)  # noqa: E731
    assert key(gate[0]) < key(confirm[0]) < key(run[0])
    (assign,) = [
        n
        for n in ast.walk(func)
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and getattr(n, "value", None) is gate[0]
    ]
    target = assign.target if isinstance(assign, ast.AnnAssign) else assign.targets[0]
    assert isinstance(target, ast.Name)
    passed = {kw.arg: kw.value for kw in run[0].keywords}
    assert isinstance(passed.get("pre_refusal"), ast.Name)
    assert passed["pre_refusal"].id == target.id


# --------------------------------------------------------------------------- #
# AC10 -- never prompts
# --------------------------------------------------------------------------- #


class _TripwireReader:
    def read(self, *_a: object) -> str:
        raise AssertionError("the refusal consulted a reader")

    readline = read

    def isatty(self) -> bool:
        return True


def test_ac10_a_tty_run_is_refused_and_never_reads_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = build_e(tmp_path / "E.pdf")
    monkeypatch.setattr(sys, "stdin", _TripwireReader())
    monkeypatch.setattr("builtins.input", lambda *_a: pytest.fail("prompted"))
    policy = SafetyPolicy(
        dry_run=False,
        force=False,
        in_place=True,
        backup=True,
        assume_yes=False,
        is_tty=True,
        threads=1,
    )
    refusal = cleared_metadata_backup_refusal(
        in_place=True, clear_all=True, backup=True, assume_yes=False
    )
    assert "is_tty" not in inspect.signature(cleared_metadata_backup_refusal).parameters
    with pytest.raises(RefusedError) as caught:
        meta_set_run(
            source,
            sets={},
            clear_producer=False,
            clear_all=True,
            output=None,
            in_place=True,
            policy=policy,
            pre_refusal=refusal,
        )
    assert caught.value.message == CLEARED_BACKUP_REFUSAL
    assert not (tmp_path / "E.pdf.bak").exists()


# --------------------------------------------------------------------------- #
# AC11 -- no new read
# --------------------------------------------------------------------------- #


def test_ac11_a_refused_run_raises_before_the_source_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = build_e(tmp_path / "E.pdf")

    def boom(*_a: object, **_k: object) -> bytes:
        raise OSError("read_source_bytes was reached")

    monkeypatch.setattr(ops_metadata, "read_source_bytes", boom)
    policy = SafetyPolicy(
        dry_run=False,
        force=False,
        in_place=True,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )
    with pytest.raises(RefusedError):
        meta_set_run(
            source,
            sets={},
            clear_producer=False,
            clear_all=True,
            output=None,
            in_place=True,
            policy=policy,
            pre_refusal=cleared_metadata_backup_refusal(
                in_place=True, clear_all=True, backup=True, assume_yes=False
            ),
        )


# --------------------------------------------------------------------------- #
# AC12 -- help
# --------------------------------------------------------------------------- #


def test_ac12_help_names_the_rule(cell: Cell) -> None:
    env = {**cell.env, "COLUMNS": "200"}
    proc = subprocess.run(
        [*console_script(), "meta", "set", "--help"],
        cwd=cell.dir,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    # Whitespace-normalise, and undo click's wrap-after-a-hyphen (`--no-` / `backup`).
    flat = re.sub(r"(?<=-)\s+(?=[a-z])", "", re.sub(r"\s+", " ", proc.stdout))
    assert "--clear-all --in-place additionally requires either --no-backup" in flat
    assert "-y (keep it, knowingly" in flat


# --------------------------------------------------------------------------- #
# AC13 / AC14 -- README
# --------------------------------------------------------------------------- #


def _paragraph(text: str, needle: str) -> str:
    (para,) = [p for p in text.split("\n\n") if needle in p]
    return para


def test_ac13_the_encrypt_paragraph_is_true_for_two_places() -> None:
    text = README.read_text(encoding="utf-8")
    tail = "where the safety default and the security default point in opposite directions"
    old = "it is the one place " + tail
    assert old not in text
    new = "the two places " + tail
    assert new in text
    para = _paragraph(text, new)
    assert "`encrypt --in-place`" in para
    assert "`meta set --clear-all --in-place`" in para
    assert "`--no-backup`" in para
    assert "`-y` (keep it, knowingly" in para


def test_ac14_the_upgrading_to_1_2_section_exists_ordered_and_carries_the_row() -> None:
    text = README.read_text(encoding="utf-8")
    heading = "## Upgrading to 1.2"
    assert text.count(heading) == 1
    assert (
        text.index("## Getting Started")
        < text.index(heading)
        < text.index("## Upgrading to 1.1")
        < text.index("## Upgrading to 1.0.0")
    )
    body = text.split(heading, 1)[1].split("\n## ", 1)[0]
    rows = [line for line in body.splitlines() if "meta set --clear-all --in-place" in line]
    assert len(rows) == 1
    assert "`5`" in rows[0] and "exit" in rows[0]
    assert "the published exit-code table is unchanged" in body
    assert re.search(r"Re-derived at `[0-9a-f]{7,40}` on `\d{4}-\d{2}-\d{2}`\.?\s*$", body.rstrip())


# --------------------------------------------------------------------------- #
# AC15 -- frozen surface (the diff half is run by the engineer: `git diff`)
# --------------------------------------------------------------------------- #


def test_ac15_the_schema_version_stays_one_on_every_new_shape(cell: Cell) -> None:
    refused = json.loads(cell.run(*CLEAR_IN_PLACE).stdout)
    dry = json.loads(cell.run("--dry-run", *CLEAR_IN_PLACE).stdout)
    assert refused["schema_version"] == 1
    assert dry["schema_version"] == 1


# --------------------------------------------------------------------------- #
# AC16 -- the REPRO, transcribed
# --------------------------------------------------------------------------- #


def test_ac16_the_repro_is_refused_with_no_sidecar(tmp_path: Path) -> None:
    sandbox = tmp_path / "S"
    sandbox.mkdir()
    build_e(sandbox / "E.pdf")
    before = sha(sandbox / "E.pdf")
    env, _roots = fs_snapshot.redirected_environment(tmp_path)
    proc = subprocess.run(
        [
            *console_script(),
            "meta",
            "set",
            str(sandbox / "E.pdf"),
            "--clear-all",
            "--in-place",
            "-o",
            "json",
        ],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 5, proc.stdout
    assert not (sandbox / "E.pdf.bak").exists()
    assert sha(sandbox / "E.pdf") == before
