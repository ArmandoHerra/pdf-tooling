"""PDF-158 -- three CLI messages that named the wrong cause.

Carriers: ``B-505`` (the doubled-word password message), ``56cb6dc40f``
(``encrypt --in-place`` on ciphertext refusing about a plaintext ``.bak``) and
``dc54be861c`` (``meta get`` on a cyclic or broken ``/Prev`` chain exiting ``0``
with ``warnings: []``).

THE RULES. (1) ``decrypt`` with no password says ``no password available: pass
--password-file PATH ...`` and names a DECLARED flag; the ``owner``/``user``
slot messages are byte-unchanged. (2) On an already-encrypted input the
"already encrypted" refusal takes the plaintext-``.bak`` gate's place at the
same tier: rc ``5`` stays ``5`` in every cell, in a read-only directory too.
(3) ``meta get`` on an incomplete ``/Prev`` walk carries exactly one constant
product warning (envelope ``warnings`` plus one ``warning:`` stderr line); a
complete chain, including a normal incremental file, carries none.

Every cell is a subprocess (``registry.run_cli``) with relative operands and
``cwd`` = the fixture directory, stdin closed, and both password variables
removed from the environment. The module imports no symbol that PDF-158 adds,
so it collects at the base and its detector nodes fail there on behaviour.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pikepdf
import pypdf
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

MSG_A: Final[str] = (
    "`encrypt --in-place` would leave an UNENCRYPTED copy at <name>.bak; "
    "pass --no-backup to keep no plaintext copy, or -y to keep it knowingly"
)
MSG_B: Final[str] = "this document is already encrypted; run 'pdftooling decrypt' first"
MSG_U: Final[str] = "destination directory is not writable: ."
_TAIL: Final[str] = (
    "PATH (or '-' to read one line from stdin), set the matching environment "
    "variable, or run on a terminal to be prompted"
)
MSG_PASSWORD_NEW: Final[str] = f"no password available: pass --password-file {_TAIL}"
MSG_OWNER_BASE: Final[str] = f"no owner password available: pass --owner-password-file {_TAIL}"
MSG_USER_BASE: Final[str] = f"no user password available: pass --user-password-file {_TAIL}"
W: Final[str] = (
    "prior_revisions may be too high: the file's cross-reference chain (/Prev) is cyclic "
    "or broken, so earlier revisions were counted from its startxref keywords"
)
HELP_SENTENCE: Final[str] = (
    "If the file's cross-reference chain is cyclic or broken, prior_revisions is an "
    "upper estimate and the report carries a warning saying so."
)
#: sha256 of the real stdout of ``encrypt P.pdf --in-place`` with no flag at the
#: recorded base: the plaintext-``.bak`` gate's own refusal (E2), 230 bytes.
SHA_GATE_REFUSAL: Final[str] = "788b616dbf5bab83cee9da76ce38ce24bccef567eca3fdbe6dc81adbe01c7e6d"
#: The dry ``items[0].detail`` key set of ``encrypt E.pdf --in-place`` at base (E2).
DRY_DETAIL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "would_exit",
        "planned_refusal",
        "would_refuse",
        "owner_password_source",
        "password_verified",
        "algorithm",
        "allow",
    }
)

ENV: Final[dict[str, str]] = {
    k: v
    for k, v in os.environ.items()
    if k not in ("PDF_TOOLING_PASSWORD", "PDF_TOOLING_OWNER_PASSWORD")
}


@dataclass(frozen=True)
class Run:
    rc: int
    out: str
    err: str

    def json(self) -> dict[str, Any]:
        return json.loads(self.out.splitlines()[0])


def _cli(cwd: Path, *args: str) -> Run:
    done = run_cli(*args, stdin="", env=ENV, cwd=cwd)
    return Run(done.returncode, done.stdout, done.stderr)


def _message(run: Run) -> str:
    """The refusal text of a failed cell, whichever envelope carries it."""
    doc = run.json()
    if "error" in doc:
        return str(doc["error"]["message"])
    if "items" in doc:
        return str(doc["items"][0]["message"])
    return str(doc["documents"][0]["error"]["message"])


def _sha(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Fixtures (independent of the product: pikepdf and pypdf build them)
# --------------------------------------------------------------------------- #


def _write_secret(directory: Path, name: str, secret: str) -> None:
    (directory / name).write_text(secret)
    (directory / name).chmod(0o600)


def _build(directory: Path) -> None:
    plain = pikepdf.new()
    plain.add_blank_page()
    plain.save(directory / "P.pdf")
    plain.save(directory / "E.pdf", encryption=pikepdf.Encryption(owner="o", user=""))
    plain.save(directory / "U.pdf", encryption=pikepdf.Encryption(owner="o", user="u"))
    _write_secret(directory, "Ofile", "o")
    _write_secret(directory, "Ufile", "u")

    base = pikepdf.new()
    base.add_blank_page(page_size=(612, 792))
    base.docinfo["/Author"] = "SENTINEL-OLDREV-3M8P"
    base.save(
        directory / "B_rev1.pdf",
        compress_streams=False,
        object_stream_mode=pikepdf.ObjectStreamMode.disable,
    )
    writer = pypdf.PdfWriter(str(directory / "B_rev1.pdf"), incremental=True)
    writer.add_metadata({"/Author": "NEWREV-AUTHOR-5T1X"})
    with open(directory / "B.pdf", "wb") as handle:
        writer.write(handle)
    raw = (directory / "B.pdf").read_bytes()
    here = len(raw) + 1
    for name, prev in (("CY.pdf", here), ("BR.pdf", 99999999)):
        section = (
            b"\nxref\n0 1\n0000000000 65535 f \ntrailer\n"
            b"<< /Size 8 /Root 1 0 R /Prev %d >>\nstartxref\n%d\n%%%%EOF\n" % (prev, here)
        )
        (directory / name).write_bytes(raw + section)


@pytest.fixture(scope="module")
def fx(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("pdf158")
    _build(directory)
    return directory


def _cell_dir(fx: Path, tmp_path: Path, *names: str) -> Path:
    for name in names:
        shutil.copy2(fx / name, tmp_path / name)
    return tmp_path


# --------------------------------------------------------------------------- #
# D1 -- the single-slot password message
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tier", ["real", "dry"])
def test_ac1_decrypt_no_password_message(fx: Path, tier: str) -> None:
    opts = ["--dry-run"] if tier == "dry" else []
    run = _cli(fx, "decrypt", "U.pdf", "-O", "d.pdf", *opts, "-o", "json")
    assert run.rc == 6
    doc = run.json()
    if tier == "real":
        assert doc["error"]["kind"] == "auth"
        assert doc["error"]["message"] == MSG_PASSWORD_NEW
    else:
        item = doc["items"][0]
        assert item["message"] == MSG_PASSWORD_NEW
        assert item["detail"]["would_exit"] == 6
        assert item["detail"]["planned_refusal"] == "AuthError"


#: E1's rc table: (dry, real) rc is the same number per cell, keyed by verb and
#: by whether ``--allow-decrypted-output`` is passed. ``None`` = not declared.
_CENSUS_ARGS: Final[dict[str, list[str]]] = {
    "info": [],
    "text": [],
    "tables": [],
    "permissions": [],
    "meta get": [],
    "meta set": ["--title", "x", "-O", "out.pdf"],
    "decrypt": ["-O", "out.pdf"],
    "encrypt": ["-O", "out.pdf", "--owner-password-file", "Ofile"],
    "merge": ["-O", "out.pdf"],
    "split": ["--each-page", "--out-dir", "outd"],
    "compress": ["-O", "out.pdf"],
    "repair": ["-O", "out.pdf"],
    "linearize": ["-O", "out.pdf"],
    "extract": ["--pages", "1", "-O", "out.pdf"],
    "delete": ["--pages", "1", "-O", "out.pdf"],
    "rotate": ["--pages", "1", "--angle", "90", "-O", "out.pdf"],
    "reorder": ["--pages", "1", "-O", "out.pdf"],
    "watermark": ["--text", "x", "-O", "out.pdf"],
    "stamp": ["--from", "P.pdf", "-O", "out.pdf"],
    "ocr": ["-O", "out.pdf"],
    "rasterize": ["--out-dir", "outd"],
}
_RC_PLAIN: Final[dict[str, int]] = {
    "info": 6,
    "text": 6,
    "tables": 6,
    "permissions": 6,
    "meta get": 6,
    "decrypt": 6,
    "rasterize": 6,
    "encrypt": 5,
}
_WRITERS: Final[tuple[str, ...]] = (
    "meta set",
    "merge",
    "split",
    "compress",
    "repair",
    "linearize",
    "extract",
    "delete",
    "rotate",
    "reorder",
    "watermark",
    "stamp",
    "ocr",
)
_CENSUS_CELLS: Final[list[tuple[str, str, str]]] = [
    (verb, tier, mode)
    for verb in _CENSUS_ARGS
    for mode in (["plain", "allow"] if verb in _WRITERS else ["plain"])
    for tier in ("real", "dry")
]


#: Engine-blind verbs need their engine to judge the operand; those cells skip
#: where the engine is absent (PDF-82 gating census; same map as PDF-156).
ENGINE_FOR_VERB: Final[dict[str, str]] = {"ocr": "tesseract", "convert": "soffice"}


@pytest.mark.parametrize(
    ("verb", "tier", "mode"),
    [
        pytest.param(
            v,
            t,
            m,
            marks=pytest.mark.requires(ENGINE_FOR_VERB[v]) if v in ENGINE_FOR_VERB else (),
            id=f"{v}-{t}-{m}",
        )
        for v, t, m in _CENSUS_CELLS
    ],
)
def test_ac2_no_verb_says_password_password(fx: Path, verb: str, tier: str, mode: str) -> None:
    opts = list(_CENSUS_ARGS[verb])
    if verb != "merge":
        head = verb.split()
        opts = [*head, "U.pdf", *opts]
    else:
        opts = ["merge", "U.pdf", *opts]
    if mode == "allow":
        opts.append("--allow-decrypted-output")
    if tier == "dry":
        opts.append("--dry-run")
    run = _cli(fx, *opts, "-o", "json")
    if verb in _RC_PLAIN:
        want_rc = _RC_PLAIN[verb]
    else:
        want_rc = 5 if mode == "plain" else 6
    assert run.rc == want_rc
    rendered = run.out + run.err
    stuttering = [
        bad for bad in ("password password", "--password-password-file") if bad in rendered
    ]
    assert stuttering == []


def test_ac3_owner_and_user_messages_are_unchanged(fx: Path) -> None:
    from pdf_tooling.ops.document_password import unresolvable_password_error

    pair = []
    for opts in ([], ["--dry-run"]):
        run = _cli(fx, "encrypt", "P.pdf", "-O", "x.pdf", *opts, "-o", "json")
        pair.append(run.rc)
        assert _message(run) == MSG_OWNER_BASE
    assert pair == [6, 6]
    assert unresolvable_password_error("user").args[0] == MSG_USER_BASE
    assert unresolvable_password_error("owner").args[0] == MSG_OWNER_BASE


def test_ac4_every_flag_the_message_names_is_declared(fx: Path) -> None:
    import typer.main

    from pdf_tooling.cli.main import app

    group = typer.main.get_command(app)
    decrypt = group.commands["decrypt"]  # type: ignore[attr-defined]
    declared = {opt for param in decrypt.params for opt in (*param.opts, *param.secondary_opts)}
    run = _cli(fx, "decrypt", "U.pdf", "-O", "d.pdf", "-o", "json")
    named = set(re.findall(r"--[a-z][a-z0-9-]*", _message(run)))
    assert named - declared == set()
    work = fx / "ac4"
    work.mkdir(exist_ok=True)
    _cell_dir(fx, work, "U.pdf", "Ufile")
    good = _cli(work, "decrypt", "U.pdf", "-O", "d.pdf", "--password-file", "Ufile", "-o", "json")
    assert good.rc == 0


# --------------------------------------------------------------------------- #
# D2 -- already-encrypted outranks the plaintext-.bak gate
# --------------------------------------------------------------------------- #

_OPTS: Final[dict[str, list[str]]] = {
    "-": [],
    "y": ["-y"],
    "no-backup": ["--no-backup"],
    "y+no-backup": ["-y", "--no-backup"],
}
#: E2's AFTER column: (input, opts, dir) -> (rc, outcome) for BOTH tiers.
_MATRIX: Final[list[tuple[str, str, str, int, str]]] = [
    ("P", "-", "rw", 5, "A"),
    ("P", "y", "rw", 0, "ok"),
    ("P", "no-backup", "rw", 0, "ok"),
    ("P", "y+no-backup", "rw", 0, "ok"),
    ("E", "-", "rw", 5, "B"),
    ("E", "y", "rw", 5, "B"),
    ("E", "no-backup", "rw", 5, "B"),
    ("E", "y+no-backup", "rw", 5, "B"),
    ("P", "-", "ro", 5, "A"),
    ("P", "y", "ro", 1, "U"),
    ("E", "-", "ro", 5, "B"),
    ("E", "y", "ro", 1, "U"),
]
_MESSAGES: Final[dict[str, str]] = {"A": MSG_A, "B": MSG_B, "U": MSG_U}


def _encrypt_in_place(
    fx: Path, tmp_path: Path, name: str, opts: str, mode: str, tier: str
) -> tuple[Run, Path]:
    """One fresh cell: copy the fixtures, run, and always restore the mode."""
    work = tmp_path / f"{name}-{opts}-{mode}-{tier}"
    work.mkdir()
    _cell_dir(fx, work, f"{name}.pdf", "Ofile")
    extra = ["--dry-run"] if tier == "dry" else []
    if mode == "ro":
        work.chmod(0o555)
    try:
        run = _cli(
            work, "encrypt", f"{name}.pdf", "--in-place", "--owner-password-file", "Ofile",
            *_OPTS[opts], *extra, "-o", "json",
        )  # fmt: skip
    finally:
        work.chmod(0o755)
    return run, work


@pytest.mark.parametrize(
    ("name", "opts", "mode", "rc", "outcome"),
    _MATRIX,
    ids=[f"{n}-{o}-{m}" for n, o, m, _, _ in _MATRIX],
)
def test_ac5_encrypt_in_place_refusal_matrix(
    fx: Path, tmp_path: Path, name: str, opts: str, mode: str, rc: int, outcome: str
) -> None:
    results = {}
    for tier in ("dry", "real"):
        run, work = _encrypt_in_place(fx, tmp_path, name, opts, mode, tier)
        results[tier] = run
        assert run.rc == rc
        if outcome == "ok":
            continue
        assert _message(run) == _MESSAGES[outcome]
        # No refusal cell writes a backup or changes the operand.
        assert sorted(entry.name for entry in work.iterdir()) == sorted([f"{name}.pdf", "Ofile"])
        assert (work / f"{name}.pdf").read_bytes() == (fx / f"{name}.pdf").read_bytes()
    dry_doc = results["dry"].json()
    if outcome != "ok":
        detail = dry_doc["items"][0]["detail"]
        assert detail["would_exit"] == rc
        if outcome in ("A", "B"):
            assert detail["planned_refusal"] == "RefusedError"
    if name == "E" and opts == "-":
        assert set(dry_doc["items"][0]["detail"]) == DRY_DETAIL_KEYS
        ref, _ = _encrypt_in_place(fx, tmp_path, "E", "y", "rw", "real")
        assert results["real"].out == ref.out
        assert _sha(ref.out) != SHA_GATE_REFUSAL


@pytest.mark.parametrize("opts", ["-", "y", "no-backup", "y+no-backup"])
def test_ac6_plain_input_gate_is_unchanged(fx: Path, tmp_path: Path, opts: str) -> None:
    dry, _ = _encrypt_in_place(fx, tmp_path, "P", opts, "rw", "dry")
    real, work = _encrypt_in_place(fx, tmp_path, "P", opts, "rw", "real")
    backup = work / "P.pdf.bak"
    if opts == "-":
        assert (dry.rc, real.rc) == (5, 5)
        assert _message(dry) == _message(real) == MSG_A
        assert _sha(real.out) == SHA_GATE_REFUSAL
        assert len(real.out.encode()) == 230
        assert not backup.exists()
        return
    assert (dry.rc, real.rc) == (0, 0)
    if opts == "y":
        assert backup.exists()
        assert any("is an UNENCRYPTED copy of the original" in w for w in real.json()["warnings"])
        assert "is an UNENCRYPTED copy of the original" in real.err
    else:
        assert not backup.exists()


def test_ac7_encrypt_in_place_table_names_already_encrypted(fx: Path, tmp_path: Path) -> None:
    work = _cell_dir(fx, tmp_path, "E.pdf", "Ofile")
    run = _cli(
        work, "encrypt", "E.pdf", "--in-place", "--owner-password-file", "Ofile", "-o", "table"
    )
    assert run.rc == 5
    assert run.out == ""
    # B carries path "E.pdf" (A carries none), and the table renderer appends it.
    assert run.err.splitlines()[-1] == "error: " + MSG_B + " (E.pdf)"
    assert "UNENCRYPTED" not in run.err


# --------------------------------------------------------------------------- #
# D3 / D4 -- meta get on an incomplete /Prev walk
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", ["json", "dry", "ndjson"])
def test_ac8_meta_get_cyclic_prev_warns_once(fx: Path, mode: str) -> None:
    opts = {"json": ["-o", "json"], "dry": ["--dry-run", "-o", "json"], "ndjson": ["-o", "ndjson"]}
    run = _cli(fx, "meta", "get", "CY.pdf", *opts[mode])
    assert run.rc == 0
    doc = run.json()
    assert doc["warnings"] == [W]
    assert doc["exit_code"] == 0
    assert doc["residual_surfaces"]["prior_revisions"] == 2


def test_ac9_meta_get_broken_prev_warns_once(fx: Path) -> None:
    run = _cli(fx, "meta", "get", "BR.pdf", "-o", "json")
    assert run.rc == 0
    assert run.json()["warnings"] == [W]


@pytest.mark.parametrize("name", ["P", "B_rev1", "B"])
def test_ac10_meta_get_complete_chain_never_warns(fx: Path, name: str) -> None:
    run = _cli(fx, "meta", "get", f"{name}.pdf", "-o", "json")
    assert run.rc == 0
    doc = run.json()
    assert doc["warnings"] == []
    assert run.err == ""
    if name == "B":
        assert doc["residual_surfaces"]["prior_revisions"] == 1


@pytest.mark.parametrize("mode", ["json", "table", "ndjson", "quiet"])
def test_ac11_meta_get_stderr_carries_one_product_line(fx: Path, mode: str) -> None:
    opts = {
        "json": ["-o", "json"],
        "table": ["-o", "table"],
        "ndjson": ["-o", "ndjson"],
        "quiet": ["-q", "-o", "json"],
    }
    run = _cli(fx, "meta", "get", "CY.pdf", *opts[mode])
    assert run.rc == 0
    lines = run.err.splitlines()
    product = [line for line in lines if line.startswith("warning: ")]
    assert product == ["warning: " + W]
    if mode == "quiet":
        assert run.err == "warning: " + W + "\n"
    else:
        assert lines[-1] == "warning: " + W


def test_ac12_meta_get_table_stdout_has_no_warning(fx: Path) -> None:
    run = _cli(fx, "meta", "get", "CY.pdf", "-o", "table")
    assert run.rc == 0
    assert W not in run.out
    assert "warning:" not in run.out


def test_ac13_meta_get_help_states_the_estimate() -> None:
    env = {**ENV, "COLUMNS": "200"}
    done = run_cli("meta get", "--help", stdin="", env=env)
    assert done.returncode == 0
    flat = " ".join(done.stdout.split())
    assert flat.count(HELP_SENTENCE) == 1
