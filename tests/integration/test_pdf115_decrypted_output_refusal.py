"""PDF-115 -- refuse a decrypted output from an encrypted input unless opted in.

THE DEFECT. Thirteen PDF-in/PDF-out verbs wrote a PLAINTEXT output from an
encrypted input at exit 0 (an owner-only input needed no password at all; under
``--in-place --no-backup`` the only encrypted copy was destroyed). PDF-108 made
the run SAY so. This spec (OR-26, X-1001) makes the default the safe one: the run
is refused at exit 5 before anything is opened for a password or written, and
``--allow-decrypted-output`` restores the old run exactly.

INDEPENDENCE. The expected population below is a LITERAL (the 13 names, provenance
"PDF-108 census + 9809a7f, 2026-10-06"), never a call into the derivation under
test; AC9 separately asserts literal == derived. The oracle for "nothing written"
is the FILESYSTEM -- a recursive directory listing and the sha256 of every input
-- and "written decrypted" is ``pikepdf.open(out)`` with no password, never the
verb's own payload.

BASELINE (step 0, measured at ``9809a7f``, 2026-10-06, before any edit): the
opt-in codes frozen in ``PRECEDENCE`` and ``FIFO_BASELINE_RC`` below were observed
on the unmodified tree.

NO ENGINE-BLIND LITERAL INSIDE A TEST BODY. ``tests/test_engine_gating_census.py``
ratchets ungated drives of the two engine-blind verbs per module. The OCR cells
here are engine-free (``--skip-text-pages``) and reach the verb through the
module-level declarations and an index parameter, exactly as PDF-108's module does.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any, Final, NamedTuple

import pikepdf
import pytest
import typer

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_tooling.cli.common import global_options, operand_argument  # noqa: E402
from pdf_tooling.errors import DecryptedOutputRefusedError, RefusedError  # noqa: E402
from registry import (  # noqa: E402
    INVOCATIONS,
    console_script,
    discover_verbs,
    run_cli,
)

pytestmark = pytest.mark.e2e

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------- #
# The literal population and shapes
# --------------------------------------------------------------------------- #

#: PDF-108 census + ``9809a7f``. Typed here on purpose (AC9 compares it to the derivation).
POPULATION: Final[tuple[str, ...]] = (
    "rotate",
    "extract",
    "delete",
    "reorder",
    "merge",
    "split",
    "watermark",
    "stamp",
    "ocr",
    "compress",
    "repair",
    "linearize",
    "meta set",
)
IN_PLACE: Final[tuple[str, ...]] = (
    "rotate",
    "delete",
    "reorder",
    "watermark",
    "stamp",
    "ocr",
    "compress",
    "repair",
    "linearize",
    "meta set",
)
BATCH: Final[tuple[str, ...]] = ("rotate", "extract", "delete", "reorder", "compress", "ocr")
#: PDF-128 (OR-43, X-1044): under the opt-in, the mixed batch's owner-only `RC4-O`
#: input is NOT opened by the one `--password-file` supplied for `AES256-UO` (the
#: user password of a different file). That supplied password is checked against an
#: owner-only document on every verb, so the `RC4-O` row fails with `exit_code` 6, its
#: siblings are written, and the batch run exits `1` ("something in this run failed"),
#: for every batch verb. Before PDF-128 only `compress` did this (and exited `6`, the
#: deviation X-1021 accepted as pre-existing); the other verbs ignored the password
#: and exited `0` with four outputs. `compress`'s dry run still predicts `0` -- its
#: preview does not open the document (the X-89 carve-out); the verbs whose preview
#: opens it predict the same `1`.
OPTIN_BATCH_RC: Final[dict[str, int]] = dict.fromkeys(BATCH, 1)
OPTIN_BATCH_UNOPENED: Final[dict[str, tuple[str, ...]]] = dict.fromkeys(BATCH, ("RC4-O.pdf",))
OPTIN_BATCH_DRY_RC: Final[dict[str, int]] = dict.fromkeys(BATCH, 1) | {"compress": 0}

#: shape -> (user password or None, ``Encryption`` kwargs)
SHAPES: Final[dict[str, dict[str, Any]]] = {
    "RC4-UO": {"user": "u-pw", "owner": "o-pw", "R": 3, "metadata": False, "aes": False},
    "RC4-O": {"user": "", "owner": "o-pw", "R": 3, "metadata": False, "aes": False},
    "AES128-UO": {"user": "u-pw", "owner": "o-pw", "R": 4},
    "AES256-UO": {"user": "u-pw", "owner": "o-pw", "R": 6},
    "AES256-O": {"user": "", "owner": "o-pw", "R": 6},
    "AES256-NOMETA-UO": {"user": "u-pw", "owner": "o-pw", "R": 6, "metadata": False},
}
SHAPE_NAMES: Final[tuple[str, ...]] = tuple(SHAPES)
USER_PROTECTED: Final[frozenset[str]] = frozenset(name for name, kw in SHAPES.items() if kw["user"])

MODES: Final[tuple[str, ...]] = ("default-real", "default-dry", "optin-real", "optin-dry")
FLAG: Final[str] = "--allow-decrypted-output"


def w_enc(label: str, verb: str, *, in_place: bool = False) -> str:
    text = f"{label}: input is encrypted; {verb} writes its output unencrypted"
    return text + " (--in-place: the encrypted input is replaced)" if in_place else text


def refusal_message(verb: str, names: list[str]) -> str:
    noun = "input is" if len(names) == 1 else "inputs are"
    return (
        f"{verb} writes its output unencrypted, and {len(names)} {noun} encrypted: "
        f"{', '.join(names)}. Nothing was written. "
        "Pass --allow-decrypted-output to write a decrypted output anyway."
    )


class Shapes(NamedTuple):
    root: Path
    files: dict[str, Path]
    user_pw: Path
    corpus: Any


@pytest.fixture(scope="session")
def shapes(corpus: Any, tmp_path_factory: pytest.TempPathFactory) -> Shapes:
    root = tmp_path_factory.mktemp("pdf115")
    base = corpus.path("multipage_text")
    plain = root / "PLAIN.pdf"
    with pikepdf.Pdf.open(base) as pdf:
        pdf.docinfo["/Title"] = "A Title"
        pdf.docinfo["/Author"] = "An Author"
        with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as meta:
            meta["dc:title"] = "A Title"
        pdf.save(plain)
    files = {"PLAIN": plain}
    for name, kwargs in SHAPES.items():
        files[name] = root / f"{name}.pdf"
        with pikepdf.Pdf.open(plain) as pdf:
            pdf.save(files[name], encryption=pikepdf.Encryption(**kwargs))
    user_pw = root / "u.pw"
    user_pw.write_text("u-pw\n")
    user_pw.chmod(0o600)
    return Shapes(root, files, user_pw, corpus)


def _template(verb: str, sh: Shapes) -> list[str]:
    """The verb's own registered flags, minus operand and destination (PDF-108's idiom)."""
    scratch = sh.root / "tmpl" / verb.replace(" ", "_")
    scratch.mkdir(parents=True, exist_ok=True)
    argv = INVOCATIONS[verb].build(sh.corpus, scratch)
    kept: list[str] = []
    skip = False
    for token in argv[1:]:
        if skip:
            skip = False
            continue
        if token in ("-O", "--output", "--out-dir"):
            skip = True
            continue
        kept.append(token)
    return kept


def _consumes(verb: str) -> tuple[str, ...]:
    return {v.name: v for v in discover_verbs() if not v.is_group}[verb].consumes


class Run(NamedTuple):
    rc: int
    env: dict[str, Any]
    stdout: str
    stderr: str

    @property
    def warnings(self) -> list[str]:
        return list(self.env.get("warnings", []))

    @property
    def error(self) -> dict[str, Any]:
        return dict(self.env.get("error", {}))


def go(verb: str, args: list[str], *, dry: bool, cwd: Path | None = None) -> Run:
    proc = run_cli(verb, *(["--dry-run"] if dry else []), *args, "-o", "json", cwd=cwd)
    text = proc.stdout.strip()
    env = json.loads(text) if text.startswith("{") else {}
    return Run(proc.returncode, env, proc.stdout, proc.stderr)


def listing(directory: Path) -> list[str]:
    return sorted(str(p.relative_to(directory)) for p in directory.rglob("*"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pw_args(shape: str, sh: Shapes) -> list[str]:
    return ["--password-file", str(sh.user_pw)] if shape in USER_PROTECTED else []


class Cells:
    """Each (verb, shape, mode) run once and cached; every AC reads the same observation."""

    def __init__(self, sh: Shapes) -> None:
        self.sh = sh
        self._cache: dict[tuple[str, str, str], tuple[Run, Path]] = {}

    def cell(self, verb: str, shape: str, mode: str) -> tuple[Run, Path]:
        key = (verb, shape, mode)
        if key in self._cache:
            return self._cache[key]
        sh = self.sh
        tier = "default" if mode.startswith("default") else "optin"
        # real and dry of the same tier share a dest so a refusal's stdout is comparable.
        leaf = tier if tier == "default" else mode
        dest = sh.root / "cells" / verb.replace(" ", "_") / shape / leaf
        dest.mkdir(parents=True, exist_ok=True)
        args = [str(sh.files[shape]), *_template(verb, sh)]
        if "--output" in _consumes(verb):
            args += ["-O", str(dest / "out.pdf")]
        else:
            args += ["--out-dir", str(dest / "parts")]
        args += pw_args(shape, sh)
        if tier == "optin":
            args.append(FLAG)
        run = go(verb, args, dry=mode.endswith("dry"))
        self._cache[key] = (run, dest)
        return run, dest


@pytest.fixture(scope="session")
def cells(shapes: Shapes) -> Cells:
    return Cells(shapes)


def _ids(names: tuple[str, ...]) -> list[str]:
    return [n.replace(" ", "_") for n in names]


VERB_IDX = pytest.mark.parametrize("vi", range(len(POPULATION)), ids=_ids(POPULATION))
SHAPE_IDX = pytest.mark.parametrize("si", range(len(SHAPE_NAMES)), ids=list(SHAPE_NAMES))


def assert_opens_without_password(dest: Path) -> None:
    outputs = sorted(dest.rglob("*.pdf"))
    assert outputs, f"no output under {dest}"
    for path in outputs:
        with pikepdf.open(path) as pdf:  # no password: raises PasswordError if encrypted
            assert not pdf.is_encrypted


# --------------------------------------------------------------------------- #
# AC1 / AC2 / AC3 -- M1
# --------------------------------------------------------------------------- #


@VERB_IDX
@SHAPE_IDX
def test_ac1_default_refuses_every_verb_over_every_encrypted_shape(
    vi: int, si: int, cells: Cells, shapes: Shapes
) -> None:
    verb, shape = POPULATION[vi], SHAPE_NAMES[si]
    run, dest = cells.cell(verb, shape, "default-real")
    operand = str(shapes.files[shape])
    assert run.rc == 5, run.stderr[-300:]
    assert run.env == {
        "schema_version": 1,
        "error": {
            "code": 5,
            "kind": "refused",
            "message": refusal_message(verb, [operand]),
            "path": operand,
        },
    }
    assert run.stderr == ""
    assert listing(dest) == [], "a refused run wrote something"


@VERB_IDX
@SHAPE_IDX
def test_ac2_dry_predicts_the_identical_refusal(vi: int, si: int, cells: Cells) -> None:
    verb, shape = POPULATION[vi], SHAPE_NAMES[si]
    real, _ = cells.cell(verb, shape, "default-real")
    dry, dest = cells.cell(verb, shape, "default-dry")
    assert dry.rc == 5
    assert dry.stdout == real.stdout
    assert listing(dest) == []


@VERB_IDX
@SHAPE_IDX
def test_ac3_the_opt_in_restores_todays_run_with_the_warning(
    vi: int, si: int, cells: Cells, shapes: Shapes
) -> None:
    verb, shape = POPULATION[vi], SHAPE_NAMES[si]
    label = str(shapes.files[shape])
    real, real_dest = cells.cell(verb, shape, "optin-real")
    dry, dry_dest = cells.cell(verb, shape, "optin-dry")
    assert real.rc == 0, real.stderr[-300:]
    assert dry.rc == 0, dry.stderr[-300:]
    assert w_enc(label, verb) in real.warnings
    assert w_enc(label, verb) in dry.warnings
    assert dry.warnings == real.warnings
    assert_opens_without_password(real_dest)
    assert listing(dry_dest) == [], "a dry run wrote something"


# --------------------------------------------------------------------------- #
# AC4 -- M2, the false-refusal control
# --------------------------------------------------------------------------- #


@VERB_IDX
@pytest.mark.parametrize("dry", [False, True], ids=["real", "dry"])
def test_ac4_a_plain_input_is_never_refused(vi: int, dry: bool, shapes: Shapes) -> None:
    verb = POPULATION[vi]
    dest = shapes.root / "plain-cells" / verb.replace(" ", "_") / ("dry" if dry else "real")
    dest.mkdir(parents=True)
    args = [str(shapes.files["PLAIN"]), *_template(verb, shapes)]
    if "--output" in _consumes(verb):
        args += ["-O", str(dest / "out.pdf")]
    else:
        args += ["--out-dir", str(dest / "parts")]
    run = go(verb, args, dry=dry)
    assert run.rc == 0, run.stderr[-300:]
    assert "error" not in run.env


# --------------------------------------------------------------------------- #
# AC5 -- M3, --in-place
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vi", range(len(IN_PLACE)), ids=_ids(IN_PLACE))
@pytest.mark.parametrize("shape", ["AES256-UO", "AES256-O"])
@pytest.mark.parametrize("no_backup", [False, True], ids=["backup", "no-backup"])
def test_ac5_in_place_leaves_the_input_byte_identical_unless_opted_in(
    vi: int, shape: str, no_backup: bool, shapes: Shapes
) -> None:
    verb = IN_PLACE[vi]
    results: dict[str, tuple[Run, Path]] = {}
    for mode in MODES:
        # real and dry of the default tier share a folder: the refusal names the
        # operand, so byte-equal stdout needs the same spelling. A refused run
        # writes nothing, so the second run starts from the same bytes.
        leaf = "default" if mode.startswith("default") else mode
        folder = shapes.root / "inplace" / verb.replace(" ", "_") / shape / str(no_backup) / leaf
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "x.pdf"
        if not target.exists():
            shutil.copy(shapes.files[shape], target)
        before_sha, before_list = sha(target), listing(folder)
        args = [str(target), *_template(verb, shapes), "--in-place"]
        if no_backup:
            args.append("--no-backup")
        args += pw_args(shape, shapes)
        if mode.startswith("optin"):
            args.append(FLAG)
        run = go(verb, args, dry=mode.endswith("dry"))
        results[mode] = (run, folder)
        if mode.startswith("default"):
            assert run.rc == 5, run.stderr[-300:]
            assert sha(target) == before_sha
            assert listing(folder) == before_list == ["x.pdf"], "a .bak or temp appeared"
        elif mode == "optin-dry":
            assert run.rc == 0, run.stderr[-300:]
            assert sha(target) == before_sha
            assert listing(folder) == before_list
        else:
            assert run.rc == 0, run.stderr[-300:]
            with pikepdf.open(target) as pdf:  # plaintext in place
                assert not pdf.is_encrypted
            if no_backup:
                assert listing(folder) == ["x.pdf"]
            else:
                assert listing(folder) == ["x.pdf", "x.pdf.bak"]
                try:
                    with pikepdf.open(folder / "x.pdf.bak") as backup:
                        assert backup.is_encrypted, "the .bak must keep the ciphertext"
                except pikepdf.PasswordError:
                    pass  # a user-password input stays locked: it is still ciphertext
    assert results["default-dry"][0].stdout == results["default-real"][0].stdout


# --------------------------------------------------------------------------- #
# AC6 -- M4, a mixed batch is refused whole and named fully
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vi", range(len(BATCH)), ids=_ids(BATCH))
def test_ac6_a_mixed_batch_is_refused_whole_and_names_every_encrypted_input(
    vi: int, shapes: Shapes
) -> None:
    verb = BATCH[vi]
    work = shapes.root / "batch" / verb
    work.mkdir(parents=True)
    names = {
        "PLAIN-a.pdf": "PLAIN",
        "AES256-UO.pdf": "AES256-UO",
        "PLAIN-b.pdf": "PLAIN",
        "RC4-O.pdf": "RC4-O",
    }
    for name, shape in names.items():
        shutil.copy(shapes.files[shape], work / name)
    pre = {name: sha(work / name) for name in names}
    operands = list(names)
    base = [*operands, *_template(verb, shapes), "--out-dir", "d", *pw_args("AES256-UO", shapes)]
    default_real = go(verb, base, dry=False, cwd=work)
    default_dry = go(verb, base, dry=True, cwd=work)
    for run in (default_real, default_dry):
        assert run.rc == 5, run.stderr[-300:]
        assert run.error["message"] == refusal_message(verb, ["AES256-UO.pdf", "RC4-O.pdf"])
        assert "2 inputs are encrypted: AES256-UO.pdf, RC4-O.pdf." in run.error["message"]
        assert "PLAIN-a" not in run.error["message"] and "PLAIN-b" not in run.error["message"]
        assert run.error["path"] == "AES256-UO.pdf"
    assert default_dry.stdout == default_real.stdout
    assert not (work / "d").exists() or listing(work / "d") == []
    assert {name: sha(work / name) for name in names} == pre
    optin_dry = go(verb, [*base, FLAG], dry=True, cwd=work)
    assert optin_dry.rc == OPTIN_BATCH_DRY_RC[verb], optin_dry.stderr[-300:]
    assert not (work / "d").exists() or listing(work / "d") == []
    optin = go(verb, [*base, FLAG], dry=False, cwd=work)
    assert optin.rc == OPTIN_BATCH_RC[verb], optin.stderr[-300:]
    written = sorted(p.name for p in (work / "d").glob("*.pdf"))
    assert written == sorted(n for n in names if n not in OPTIN_BATCH_UNOPENED[verb]), written


# --------------------------------------------------------------------------- #
# AC7 -- M5, merge
# --------------------------------------------------------------------------- #

MERGE_ARMS: Final[tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]] = (
    ("enc-first", ("AES256-UO.pdf", "PLAIN.pdf"), ("AES256-UO.pdf",)),
    ("enc-second", ("PLAIN.pdf", "AES256-UO.pdf"), ("AES256-UO.pdf",)),
    ("enc-range", ("AES256-UO.pdf:1", "PLAIN.pdf"), ("AES256-UO.pdf:1",)),
)


@pytest.mark.parametrize(("arm", "operands", "named"), MERGE_ARMS, ids=[a[0] for a in MERGE_ARMS])
def test_ac7_merge_refuses_in_every_operand_order_and_names_a_ranged_operand(
    arm: str, operands: tuple[str, ...], named: tuple[str, ...], shapes: Shapes
) -> None:
    work = shapes.root / "merge" / arm
    work.mkdir(parents=True)
    for shape in ("PLAIN", "AES256-UO"):
        shutil.copy(shapes.files[shape], work / f"{shape}.pdf")
    base = [*operands, "-O", "m.pdf", *pw_args("AES256-UO", shapes)]
    real = go("merge", base, dry=False, cwd=work)
    dry = go("merge", base, dry=True, cwd=work)
    for run in (real, dry):
        assert run.rc == 5, run.stderr[-300:]
        assert run.error["message"] == refusal_message("merge", list(named))
        assert run.error["path"] == "AES256-UO.pdf"
    assert dry.stdout == real.stdout
    assert listing(work) == ["AES256-UO.pdf", "PLAIN.pdf"], "m.pdf must be absent"
    optin_dry = go("merge", [*base, FLAG], dry=True, cwd=work)
    optin = go("merge", [*base, FLAG], dry=False, cwd=work)
    assert (optin_dry.rc, optin.rc) == (0, 0), optin.stderr[-300:]
    assert optin_dry.warnings == optin.warnings
    with pikepdf.open(work / "m.pdf") as pdf:
        assert not pdf.is_encrypted


# --------------------------------------------------------------------------- #
# AC8 -- M6, the exemption arm
# --------------------------------------------------------------------------- #


def test_ac8_encrypt_and_decrypt_are_exempt_and_decrypt_keeps_its_stricter_gate(
    shapes: Shapes,
) -> None:
    work = shapes.root / "exempt"
    work.mkdir()
    owner = shapes.root / "o.pw"
    owner.write_text("o-pw\n")
    owner.chmod(0o600)
    enc = go(
        "encrypt",
        [
            str(shapes.files["PLAIN"]),
            "--owner-password-file",
            str(owner),
            "-O",
            str(work / "e.pdf"),
        ],
        dry=False,
    )
    assert enc.rc == 0 and "error" not in enc.env, enc.stderr[-300:]
    dec = go(
        "decrypt",
        [str(shapes.files["AES256-UO"]), "-O", str(work / "d.pdf"), *pw_args("AES256-UO", shapes)],
        dry=False,
    )
    assert dec.rc == 0 and "error" not in dec.env, dec.stderr[-300:]
    owner_only = go(
        "decrypt", [str(shapes.files["AES256-O"]), "-O", str(work / "d2.pdf")], dry=False
    )
    assert owner_only.rc == 6, owner_only.stderr[-300:]
    for verb, operand in (
        ("encrypt", str(shapes.files["PLAIN"])),
        ("decrypt", str(shapes.files["AES256-UO"])),
        ("info", str(shapes.files["PLAIN"])),
        ("text", str(shapes.files["PLAIN"])),
        ("permissions", str(shapes.files["PLAIN"])),
    ):
        run = go(verb, [operand, FLAG], dry=False)
        assert run.rc == 2, (verb, run.stdout, run.stderr)
        assert run.error["kind"] == "usage"
        assert FLAG in run.error["message"]


# --------------------------------------------------------------------------- #
# AC9 -- derived, complete, exact
# --------------------------------------------------------------------------- #


def test_ac9_the_flag_set_is_derived_complete_and_exact() -> None:
    from pdf_tooling.ops.carriage_decl import requires_decrypted_output_opt_in

    leaves = [v.name for v in discover_verbs() if not v.is_group]
    derived = {name for name in leaves if requires_decrypted_output_opt_in(name)}
    assert derived == set(POPULATION)
    assert len(POPULATION) == 13
    for name in leaves:
        proc = run_cli(*name.split(), "--help")
        assert proc.returncode == 0, (name, proc.stderr[-200:])
        assert (FLAG in proc.stdout) is (name in derived), name


# --------------------------------------------------------------------------- #
# AC10 -- README agrees with the derivation
# --------------------------------------------------------------------------- #

README: Final[Path] = REPO_ROOT / "README.md"
UPGRADING_1_1: Final[str] = "## Upgrading to 1.1"


def _backticked(text: str) -> set[str]:
    return set(re.findall(r"`([a-z][a-z ]*[a-z])`", text))


def test_ac10_the_readme_agrees_with_the_derivation() -> None:
    text = README.read_text()
    assert "Whether any of this should change is an open decision" not in text
    safety = text.split("## Safety contract", 1)[1].split("\n## ", 1)[0]
    assert FLAG in safety
    sentence = next(
        line for line in text.splitlines() if "Written unencrypted from an encrypted input:" in line
    )
    assert _backticked(sentence.split(":", 1)[1]) >= set(POPULATION)
    named = _backticked(sentence.split("encrypted input:", 1)[1].split(".", 1)[0])
    assert named == set(POPULATION)


def test_b437_the_safety_contract_bullet_names_exactly_the_verbs_that_refuse() -> None:
    """5956e51669: the bullet's claim is checked against the population DERIVED from code.

    Reds if the bullet names a verb that does not refuse (an extraction verb,
    `encrypt`, `decrypt`), omits one that does, or goes back to a blanket
    "every verb except ..." sentence.
    """
    from pdf_tooling.ops.carriage_decl import requires_decrypted_output_opt_in

    text = README.read_text()
    safety = text.split("## Safety contract", 1)[1].split("\n## ", 1)[0]
    bullet = next(line for line in safety.splitlines() if "never written out unencrypted" in line)
    assert "every verb" not in bullet
    leaves = [v.name for v in discover_verbs() if not v.is_group]
    derived = {name for name in leaves if requires_decrypted_output_opt_in(name)}
    refusing_clause = bullet.split("refuse it", 1)[0]
    assert _backticked(refusing_clause) & set(leaves) == derived
    not_gated = {name for name in leaves if name not in derived}
    assert not (_backticked(refusing_clause) & not_gated)


def test_ac10_the_upgrading_row_names_exactly_the_derived_verbs() -> None:
    text = README.read_text()
    assert UPGRADING_1_1 in text
    section = text.split(UPGRADING_1_1, 1)[1].split("\n## ", 1)[0]
    row = next(line for line in section.splitlines() if line.startswith("|") and "`rotate`" in line)
    assert _backticked(row.split("|")[1]) >= set(POPULATION)
    first_cell = row.split("|")[1]
    listed = first_cell.split("(", 1)[1].split(")", 1)[0]
    assert _backticked(listed) == set(POPULATION)
    assert FLAG in section


# --------------------------------------------------------------------------- #
# AC11 -- a new verb inherits both, or escapes visibly
# --------------------------------------------------------------------------- #


def _synthetic_root(marker: Path) -> Any:
    root = typer.Typer(add_completion=False)

    @root.command("synthetic-verb")
    @global_options(consumes=("--output",))
    def synthetic(
        ctx: typer.Context,
        source: Annotated[Path, operand_argument(metavar="PDF")],
    ) -> None:
        marker.write_text("wrote")

    @root.command("other-verb")
    def other() -> None:  # pragma: no cover - keeps the root a group
        return None

    return root


def _drive_synthetic(
    root: Any, argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    import pdf_tooling.cli.main as main_module
    from pdf_tooling.cli.common import reset_error_format

    monkeypatch.setattr(main_module, "app", root)
    monkeypatch.setattr(sys, "argv", ["pdftooling", *argv])
    reset_error_format()
    with pytest.raises(SystemExit) as excinfo:
        main_module.main()
    code = excinfo.value.code
    return (int(code) if code is not None else 0), capsys.readouterr().out


def test_ac11_a_new_verb_inherits_the_flag_and_the_refusal(
    shapes: Shapes,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from pdf_tooling.cli.common import declare_decrypted_output_opt_in

    marker = tmp_path / "marker"
    monkeypatch.setenv("COLUMNS", "200")  # rich wraps option names at the default width
    # The synthetic verb registers its module in the process-global declaration registry; a
    # private copy keeps `test_every_leaf_verb_declares_...` (27 vs 26) order-independent.
    import pdf_tooling.cli.common as cli_common

    monkeypatch.setattr(cli_common, "_CONSUMES_BY_MODULE", dict(cli_common._CONSUMES_BY_MODULE))
    root = _synthetic_root(marker)
    declare_decrypted_output_opt_in(root)
    declare_decrypted_output_opt_in(root)  # idempotent
    encrypted = str(shapes.files["AES256-O"])

    problems: list[str] = []
    code, out = _drive_synthetic(root, ["synthetic-verb", "--help"], monkeypatch, capsys)
    # CI sets GITHUB_ACTIONS, which makes rich emit colour codes that split the option name.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", out)
    if not (code == 0 and FLAG in plain):
        problems.append("(a) the derived flag is not on the synthetic verb")

    argv = ["synthetic-verb", encrypted, "-O", str(tmp_path / "o.pdf"), "-o", "json"]
    code, out = _drive_synthetic(root, argv, monkeypatch, capsys)
    if code != 5 or json.loads(out)["error"]["kind"] != "refused":
        problems.append(f"(b) not refused without the flag: rc {code}")
    if marker.exists():
        problems.append("(b) the verb body ran without the flag (marker written)")
        marker.unlink()

    code, out = _drive_synthetic(root, [*argv, FLAG], monkeypatch, capsys)
    if code != 0 or not marker.exists():
        problems.append(f"(c) the opt-in did not let the verb body run: rc {code}")
    assert not problems, "; ".join(problems)


# --------------------------------------------------------------------------- #
# AC12 -- the refusal never reads the secret
# --------------------------------------------------------------------------- #


def test_ac12_a_refusal_reads_the_secret_zero_times(
    shapes: Shapes,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import pdf_tooling.cli.main as main_module
    import pdf_tooling.cli.password as password_module
    from pdf_tooling.cli.common import reset_error_format

    reads: list[int] = []
    original = password_module._read_file

    def counting(*args: Any, **kwargs: Any) -> Any:
        reads.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(password_module, "_read_file", counting)

    def drive(extra: list[str]) -> int:
        argv = [
            "rotate", str(shapes.files["AES256-UO"]), "--pages", "1", "--angle", "90",
            "-O", str(tmp_path / "r.pdf"), "--password-file", str(shapes.user_pw), "-o", "json",
            *extra,
        ]  # fmt: skip
        monkeypatch.setattr(sys, "argv", ["pdftooling", *argv])
        reset_error_format()
        with pytest.raises(SystemExit) as excinfo:
            main_module.main()
        capsys.readouterr()
        return int(excinfo.value.code or 0)

    assert drive([]) == 5
    assert drive(["--dry-run"]) == 5
    assert reads == [], "the refusal must never resolve the password"
    # Control: the counter does see the opted-in real run's read, so the zero is not vacuous.
    assert drive([FLAG]) == 0
    assert len(reads) == 1


# --------------------------------------------------------------------------- #
# AC13 -- the gate cannot hang on, or read, a non-regular operand
# --------------------------------------------------------------------------- #

#: Observed on the unmodified tree at 9809a7f (2026-10-06): "expected a regular file".
FIFO_BASELINE_RC: Final[int] = 2


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="platform has no mkfifo")
def test_ac13_a_fifo_operand_is_classified_not_opened(shapes: Shapes, tmp_path: Path) -> None:
    fifo = tmp_path / "fifo.pdf"
    os.mkfifo(fifo)
    base = ["rotate", "--pages", "1", "--angle", "90", "--out-dir", str(tmp_path / "d")]

    def run(*operands: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*console_script(), base[0], *operands, *base[1:], "-o", "json",
             *pw_args("AES256-UO", shapes)],
            capture_output=True, text=True, timeout=20, check=False, cwd=REPO_ROOT,
        )  # fmt: skip

    alone = run(str(fifo))
    assert alone.returncode == FIFO_BASELINE_RC, alone.stderr[-300:]
    with_encrypted = run(str(shapes.files["AES256-UO"]), str(fifo))
    assert with_encrypted.returncode == 5, with_encrypted.stderr[-300:]
    assert json.loads(with_encrypted.stdout)["error"]["kind"] == "refused"


# --------------------------------------------------------------------------- #
# AC14 -- M7, precedence
# --------------------------------------------------------------------------- #

#: (cell, argv builder name, rc at 9809a7f under the opt-in). Frozen from the step-0 baseline.
PRECEDENCE: Final[tuple[tuple[str, int], ...]] = (
    ("merge-no-output", 2),
    ("rotate-no-password", 6),
    ("rotate-wrong-password", 6),
    ("rotate-missing-sibling", 4),
    ("rotate-bad-range", 2),
    ("rotate-existing-output", 5),
)


def _precedence_argv(cell: str, shapes: Shapes, work: Path) -> list[str]:
    enc = str(shapes.files["AES256-UO"])
    good = ["--password-file", str(shapes.user_pw)]
    wrong = work / "wrong.pw"
    wrong.write_text("nope\n")
    wrong.chmod(0o600)
    rot = ["--pages", "1", "--angle", "90"]
    existing = work / "existing.pdf"
    existing.write_bytes(b"x")
    return {
        "merge-no-output": ["merge", enc, *good],
        "rotate-no-password": ["rotate", enc, *rot, "-O", str(work / "r1.pdf")],
        "rotate-wrong-password": [
            "rotate", enc, *rot, "-O", str(work / "r2.pdf"), "--password-file", str(wrong)
        ],
        "rotate-missing-sibling": [
            "rotate", str(work / "missing.pdf"), enc, *rot, "--out-dir", str(work / "d"), *good
        ],
        "rotate-bad-range": [
            "rotate", enc, "--pages", "zzz", "--angle", "90", "-O", str(work / "r3.pdf"), *good
        ],
        "rotate-existing-output": ["rotate", enc, *rot, "-O", str(existing), *good],
    }[cell]  # fmt: skip


@pytest.mark.parametrize(("cell", "expected"), PRECEDENCE, ids=[c for c, _ in PRECEDENCE])
def test_ac14_precedence_is_as_declared(cell: str, expected: int, shapes: Shapes) -> None:
    work = shapes.root / "precedence" / cell
    work.mkdir(parents=True)
    argv = _precedence_argv(cell, shapes, work)
    verb, rest = argv[0], argv[1:]
    for dry in (False, True):
        default = go(verb, rest, dry=dry)
        assert default.rc == 5, (cell, dry, default.stdout)
        assert default.error["message"].startswith(f"{verb} writes its output unencrypted")
        optin = go(verb, [*rest, FLAG], dry=dry)
        assert optin.rc == expected, (cell, dry, optin.stdout[-300:], optin.stderr[-300:])


# --------------------------------------------------------------------------- #
# X-1014(a) -- stamp --from <encrypted> is gated like an encrypted operand
# --------------------------------------------------------------------------- #


def test_x1014a_an_encrypted_stamp_source_is_refused_and_the_opt_in_allows_it(
    shapes: Shapes,
) -> None:
    work = shapes.root / "stamp-from"
    work.mkdir()
    shutil.copy(shapes.files["PLAIN"], work / "PLAIN.pdf")
    shutil.copy(shapes.files["AES256-UO"], work / "SRC.pdf")
    pre = listing(work)
    common = [
        "PLAIN.pdf", "--from", "SRC.pdf", "-O", "out.pdf",
        "--password-file", str(shapes.user_pw),
    ]  # fmt: skip
    real = go("stamp", common, dry=False, cwd=work)
    dry = go("stamp", common, dry=True, cwd=work)
    for run in (real, dry):
        assert run.rc == 5, run.stdout
        assert run.error["message"] == refusal_message("stamp", ["SRC.pdf"])
        assert run.error["path"] == "SRC.pdf"
    assert dry.stdout == real.stdout
    assert listing(work) == pre, "a refused stamp wrote something"
    optin_dry = go("stamp", [*common, FLAG], dry=True, cwd=work)
    optin = go("stamp", [*common, FLAG], dry=False, cwd=work)
    assert (optin_dry.rc, optin.rc) == (0, 0), optin.stderr[-300:]
    assert (work / "out.pdf").exists()


def test_b437_optin_stamp_from_an_encrypted_source_warns_w_enc_naming_it(
    shapes: Shapes,
) -> None:
    """24ecc55c77: the opt-in output is unencrypted AND the warning says so, dry == real."""
    work = shapes.root / "stamp-from-wenc"
    work.mkdir()
    shutil.copy(shapes.files["PLAIN"], work / "PLAIN.pdf")
    shutil.copy(shapes.files["AES256-UO"], work / "SRC.pdf")
    common = [
        "PLAIN.pdf", "--from", "SRC.pdf", "-O", "out.pdf",
        "--password-file", str(shapes.user_pw),
    ]  # fmt: skip
    expected = "SRC.pdf: input is encrypted; stamp writes its output unencrypted"
    dry = go("stamp", [*common, FLAG], dry=True, cwd=work)
    real = go("stamp", [*common, FLAG], dry=False, cwd=work)
    assert (dry.rc, real.rc) == (0, 0), real.stderr[-300:]
    assert dry.warnings == real.warnings
    assert real.warnings.count(expected) == 1, real.warnings
    assert f"warning: {expected}" in real.stderr
    with pikepdf.open(work / "out.pdf") as written:  # no password
        assert not written.is_encrypted
    # A plaintext --from source stays quiet; refusal without the flag is unchanged.
    shutil.copy(shapes.files["PLAIN"], work / "SRC2.pdf")
    quiet = go(
        "stamp", ["PLAIN.pdf", "--from", "SRC2.pdf", "-O", "o2.pdf", FLAG], dry=False, cwd=work
    )
    assert quiet.rc == 0 and not any("is encrypted" in w for w in quiet.warnings)
    refused = go("stamp", [*common, "-f"], dry=False, cwd=work)
    assert refused.rc == 5
    assert refused.error["message"] == refusal_message("stamp", ["SRC.pdf"])


# --------------------------------------------------------------------------- #
# AC15 -- the error class is additive and B-361-compatible
# --------------------------------------------------------------------------- #


def test_ac15_the_error_class_is_additive_with_one_construction_site() -> None:
    assert issubclass(DecryptedOutputRefusedError, RefusedError)
    assert DecryptedOutputRefusedError.kind == "refused"
    assert DecryptedOutputRefusedError.exit_code == 5
    assert "kind" not in vars(DecryptedOutputRefusedError)
    assert "exit_code" not in vars(DecryptedOutputRefusedError)
    sites: list[str] = []
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "DecryptedOutputRefusedError"
            ):
                sites.append(str(path.relative_to(REPO_ROOT / "src" / "pdf_tooling")))
    assert sites == ["ops/carriage.py"]


# --------------------------------------------------------------------------- #
# AC19 -- rotate help
# --------------------------------------------------------------------------- #


def test_ac19_rotate_help_names_the_refusal_and_the_flag() -> None:
    proc = run_cli("rotate", "--help")
    assert proc.returncode == 0
    flat = " ".join(proc.stdout.split())
    assert "--allow-decrypted-output" in flat
    assert "refused unless --allow-decrypted-output" in flat
    assert "nothing else" not in flat.lower()
    assert "/Info" in flat and "XMP" in flat
