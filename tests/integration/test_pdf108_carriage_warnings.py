"""PDF-108 -- a write says what it drops: encryption and document metadata.

THE DEFECT. Thirteen PDF-in/PDF-out verbs wrote a PLAINTEXT output from an
encrypted input at exit 0 with ``warnings: []``, and nine of them rebuilt the
document through the page-rebuild engine, which replaces ``/Info`` with the
engine's producer entry and drops the XMP packet. ``rotate --help`` claimed it
"changes a page's /Rotate entry and nothing else". This is the DESCRIPTIVE half
only: every such write says what it dropped, in the existing ``warnings`` array
and on stderr, and ``--dry-run`` says the same thing word for word.

HOW THE MATRIX IS BUILT. Inputs are made once per session with the product's own
``encrypt``. Each (verb, input) cell is run ONCE, dry and real, and cached, so
the AC arms below assert over the same observations instead of re-running them.
The expected texts are spelled out literally HERE, not imported from
``ops/carriage.py``: a pin that reads its expectation from the code it pins
cannot go red.

The verb classes are declared literally at module level and proved against the
live registry (``test_the_derived_population_...``), so a mutation of the
declaration table cannot also move the expectation.

NO LITERAL FOR THE TWO ENGINE-BLIND VERBS INSIDE A TEST BODY. The census in
``tests/test_engine_gating_census.py`` counts ungated drives of those verbs per
module against a ratified ceiling. The cells here are engine-free (the OCR verb
runs with ``--skip-text-pages``), so they are not engine-dependent; they reach
the verb through a module-level declaration and an index parameter so that this
module does not grow a ceiling it has no ruling to raise.
"""

from __future__ import annotations

import inspect
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, NamedTuple

import pikepdf
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from dryreal import dry_and_real  # noqa: E402
from pdf_tooling.ops import carriage  # noqa: E402
from pdf_tooling.ops.carriage import CARRIAGE, Drop  # noqa: E402
from pdf_tooling.ports.structure import CarriageFacts, StructureEngine  # noqa: E402
from registry import (  # noqa: E402
    INVOCATIONS,
    discover_verbs,
    engine_blind_verbs,
    run_cli,
)

pytestmark = pytest.mark.e2e

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------- #
# The declared population (D1), spelled literally and proved against the registry
# --------------------------------------------------------------------------- #

REBUILD: Final[tuple[str, ...]] = (
    "rotate",
    "extract",
    "delete",
    "reorder",
    "merge",
    "split",
    "watermark",
    "stamp",
    "ocr",
)
REWRITE: Final[tuple[str, ...]] = ("compress", "repair", "linearize", "meta set")
CRYPTO: Final[tuple[str, ...]] = ("encrypt", "decrypt")
DROPPERS: Final[tuple[str, ...]] = REBUILD + REWRITE

#: Every input shape of D9. ``U-*`` are opened with the user password.
INPUTS: Final[tuple[str, ...]] = (
    "P-both",
    "P-info",
    "P-xmp",
    "P-none",
    "P-default",
    "O-both",
    "U-both",
    "U-none",
)
ENCRYPTED: Final[frozenset[str]] = frozenset({"O-both", "U-both", "U-none"})
USER_PROTECTED: Final[frozenset[str]] = frozenset({"U-both", "U-none"})

#: What each readable input holds that a rebuild drops (D2's ``<parts>``).
BOTH: Final[str] = "document /Info and XMP metadata packet"
PARTS: Final[dict[str, str]] = {
    "P-both": BOTH,
    "P-info": "document /Info",
    "P-xmp": "XMP metadata packet",
    "O-both": BOTH,
}

IN_PLACE_SUFFIX: Final[str] = " (--in-place: the encrypted input is replaced)"

#: The 23 verbs ``registry`` classified as mutating at ``a219bcf`` (AC16).
MUTATING_AT_A219BCF: Final[frozenset[str]] = frozenset(
    {
        "compose",
        "compress",
        "convert",
        "create",
        "decrypt",
        "delete",
        "encrypt",
        "extract",
        "linearize",
        "merge",
        "meta get",
        "meta set",
        "ocr",
        "permissions",
        "rasterize",
        "reorder",
        "repair",
        "rotate",
        "split",
        "stamp",
        "tables",
        "text",
        "watermark",
    }
)


#: The engine-blind pair at ``a219bcf`` (AC16), kept at module level so no test
#: body spells either verb (see the module docstring).
ENGINE_BLIND_AT_A219BCF: Final[tuple[str, ...]] = ("convert", "ocr")


def w_enc(label: str, verb: str, *, in_place: bool = False) -> str:
    text = f"{label}: input is encrypted; {verb} writes its output unencrypted"
    return text + IN_PLACE_SUFFIX if in_place else text


def w_meta(label: str, verb: str, parts: str) -> str:
    return f"{label}: {verb} does not carry the input's {parts} to its output"


def w_unchecked(label: str, verb: str) -> str:
    return (
        f"{label}: {verb} carries no document /Info or XMP metadata packet to its output; "
        "the input needs a password to read, so whether it has either was not checked"
    )


def expected_for(verb: str, name: str, label: str, *, in_place: bool = False) -> list[str]:
    """The carriage warnings D2 prescribes for *verb* over input *name*."""
    out: list[str] = []
    if verb in DROPPERS and name in ENCRYPTED:
        out.append(w_enc(label, verb, in_place=in_place))
    # PDF-116: the page-rebuild verbs carry the source's /Info and XMP (an
    # authenticated write carries too), so a single source never earns a W-META
    # or W-META-UNCHECKED; only `merge`'s later inputs do (test_pdf116_*).
    return out


# --------------------------------------------------------------------------- #
# Fixtures: inputs built once per session with the product's own `encrypt`
# --------------------------------------------------------------------------- #


class Run(NamedTuple):
    rc: int
    env: dict[str, Any]
    stdout: str
    stderr: str

    @property
    def warnings(self) -> list[str]:
        return list(self.env.get("warnings", []))

    @property
    def seam_lines(self) -> list[str]:
        """Stderr's ``warning: `` lines, case-sensitive (the seam's own prefix)."""
        return [line for line in self.stderr.splitlines() if line.startswith("warning: ")]


def parse(proc: subprocess.CompletedProcess[str]) -> Run:
    text = proc.stdout.strip()
    env: dict[str, Any] = json.loads(text) if text.startswith("{") else {}
    return Run(proc.returncode, env, proc.stdout, proc.stderr)


def _write_pdf(base: Path, dest: Path, *, info: bool, xmp: bool) -> None:
    with pikepdf.Pdf.open(base) as pdf:
        if "/Info" in pdf.trailer:
            del pdf.trailer["/Info"]
        if info:
            pdf.docinfo["/Title"] = "A Title"
            pdf.docinfo["/Author"] = "An Author"
        if xmp:
            with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as meta:
                meta["dc:title"] = "A Title"
        pdf.save(dest)


class Inputs(NamedTuple):
    files: dict[str, Path]
    user_pw: Path
    owner_pw: Path
    stamp_source: Path
    corpus: Any
    root: Path

    def label(self, name: str) -> str:
        return str(self.files[name])

    def password_args(self, name: str) -> list[str]:
        return ["--password-file", str(self.user_pw)] if name in USER_PROTECTED else []


@pytest.fixture(scope="session")
def inputs(corpus: Any, tmp_path_factory: pytest.TempPathFactory) -> Inputs:
    root = tmp_path_factory.mktemp("pdf108")
    base = corpus.path("multipage_text")
    files: dict[str, Path] = {}
    for name, info, xmp in (
        ("P-both", True, True),
        ("P-info", True, False),
        ("P-xmp", False, True),
        ("P-none", False, False),
    ):
        files[name] = root / f"{name}.pdf"
        _write_pdf(base, files[name], info=info, xmp=xmp)
    user_pw = root / "user.pw"
    owner_pw = root / "owner.pw"
    user_pw.write_text("user-secret\n")
    owner_pw.write_text("owner-secret\n")
    user_pw.chmod(0o600)
    owner_pw.chmod(0o600)

    def encrypt(src: str, dest: str, *, user: bool) -> None:
        args = [
            "encrypt",
            str(files[src]),
            "--owner-password-file",
            str(owner_pw),
            "-O",
            str(root / dest),
        ]
        if user:
            args += ["--user-password-file", str(user_pw)]
        proc = run_cli(*args)
        assert proc.returncode == 0, proc.stderr

    encrypt("P-both", "O-both.pdf", user=False)
    encrypt("P-both", "U-both.pdf", user=True)
    encrypt("P-none", "U-none.pdf", user=True)
    files["O-both"] = root / "O-both.pdf"
    files["U-both"] = root / "U-both.pdf"
    files["U-none"] = root / "U-none.pdf"

    # P-default: a REBUILD output, so its /Info is exactly the engine default.
    default = root / "P-default.pdf"
    proc = run_cli(
        "rotate", str(files["P-both"]), "--pages", "1", "--angle", "90", "-O", str(default)
    )
    assert proc.returncode == 0, proc.stderr
    files["P-default"] = default
    return Inputs(files, user_pw, owner_pw, corpus.path("single_page"), corpus, root)


# --------------------------------------------------------------------------- #
# The cell runner: every (verb, input) observed once, dry and real
# --------------------------------------------------------------------------- #


def _verb_specs() -> dict[str, Any]:
    return {v.name: v for v in discover_verbs() if not v.is_group}


def _template(verb: str, inputs: Inputs) -> list[str]:
    """The verb's own registered flags, minus operand and destination.

    Taken from ``registry.INVOCATIONS`` so the per-verb flags (``--pages``,
    ``--angle``, ``--text``, ``--from``, ...) are the suite's single declaration
    of a valid invocation rather than a second copy of them here.
    """
    scratch = inputs.root / "tmpl" / verb.replace(" ", "_")
    scratch.mkdir(parents=True, exist_ok=True)
    argv = INVOCATIONS[verb].build(inputs.corpus, scratch)
    rest = argv[1:]
    kept: list[str] = []
    skip = False
    for token in rest:
        if skip:
            skip = False
            continue
        if token in ("-O", "--output", "--out-dir"):
            skip = True
            continue
        kept.append(token)
    return kept


def argv_for(
    verb: str, name: str, inputs: Inputs, dest: Path, *, in_place: bool = False
) -> list[str]:
    spec = _verb_specs()[verb]
    src = str(inputs.files[name]) if not in_place else str(dest)
    args = [src, *_template(verb, inputs)]
    if in_place:
        args.append("--in-place")
    elif "--output" in spec.consumes:
        args += ["-O", str(dest / "out.pdf")]
    else:
        args += ["--out-dir", str(dest / "parts")]
    # PDF-115 D10: a cell here asks what an ALLOWED run does, so an encrypted
    # operand of a dropping verb carries the opt-in. Nothing else moves.
    if name in ENCRYPTED and verb in DROPPERS:
        args.append("--allow-decrypted-output")
    return [*args, *inputs.password_args(name)]


class Cell(NamedTuple):
    dry: Run
    real: Run
    dest: Path


class Matrix:
    def __init__(self, inputs: Inputs) -> None:
        self.inputs = inputs
        self._cells: dict[tuple[str, str], Cell] = {}

    def cell(self, verb: str, name: str) -> Cell:
        key = (verb, name)
        if key not in self._cells:
            dest = self.inputs.root / "cells" / verb.replace(" ", "_") / name
            dest.mkdir(parents=True)
            args = argv_for(verb, name, self.inputs, dest)
            dry, real = dry_and_real(verb, args)
            self._cells[key] = Cell(parse(dry), parse(real), dest)
        return self._cells[key]


@pytest.fixture(scope="session")
def matrix(inputs: Inputs) -> Matrix:
    return Matrix(inputs)


def _ids(verbs: tuple[str, ...]) -> list[str]:
    return [v.replace(" ", "_") for v in verbs]


def check_cell(verb: str, name: str, matrix: Matrix) -> Cell:
    """Common assertions every cell must satisfy: rc, and stderr == envelope."""
    label = matrix.inputs.label(name)
    cell = matrix.cell(verb, name)
    for tier, run in (("dry", cell.dry), ("real", cell.real)):
        assert run.rc == 0, f"{verb} {name} {tier}: rc {run.rc}: {run.stderr[-400:]}"
        assert run.warnings == expected_for(verb, name, label), (
            f"{verb} {name} {tier}: {run.warnings!r}"
        )
        assert run.seam_lines == [f"warning: {w}" for w in run.warnings], (
            f"{verb} {name} {tier}: stderr {run.stderr!r}"
        )
    return cell


# --------------------------------------------------------------------------- #
# AC1 -- W-ENC, every encrypting cell
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vi", range(len(DROPPERS)), ids=_ids(DROPPERS))
def test_ac1_w_enc_fires_for_every_encrypting_cell_in_both_tiers(vi: int, matrix: Matrix) -> None:
    verb = DROPPERS[vi]
    for name in ("U-both", "O-both"):
        cell = check_cell(verb, name, matrix)
        label = matrix.inputs.label(name)
        for run in (cell.dry, cell.real):
            assert run.warnings.count(w_enc(label, verb)) == 1
            assert f"warning: {w_enc(label, verb)}" in run.stderr.splitlines()


# --------------------------------------------------------------------------- #
# AC2 -- W-META, known parts
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vi", range(len(REBUILD)), ids=_ids(REBUILD))
def test_ac2_w_meta_names_exactly_the_parts_the_input_holds(vi: int, matrix: Matrix) -> None:
    verb = REBUILD[vi]
    for name in ("P-both", "P-info", "P-xmp", "O-both"):
        cell = check_cell(verb, name, matrix)
        label = matrix.inputs.label(name)
        for run in (cell.dry, cell.real):
            # PDF-116: inverted -- carried, so nothing is named as dropped.
            assert w_meta(label, verb, PARTS[name]) not in run.warnings
            assert all("does not carry" not in w for w in run.warnings)


# --------------------------------------------------------------------------- #
# AC3 -- W-META-UNCHECKED
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vi", range(len(REBUILD)), ids=_ids(REBUILD))
def test_ac3_a_password_protected_input_is_reported_unchecked_not_absent(
    vi: int, matrix: Matrix
) -> None:
    verb = REBUILD[vi]
    for name in ("U-both", "U-none"):
        cell = check_cell(verb, name, matrix)
        label = matrix.inputs.label(name)
        for run in (cell.dry, cell.real):
            # PDF-116: inverted -- an authenticated rebuild carries, so it is not "unchecked".
            assert w_unchecked(label, verb) not in run.warnings
            assert all("not checked" not in w for w in run.warnings)


@pytest.mark.parametrize("vi", range(len(REWRITE)), ids=_ids(REWRITE))
def test_ac3_a_rewrite_verb_never_carries_a_metadata_warning(vi: int, matrix: Matrix) -> None:
    verb = REWRITE[vi]
    cell = check_cell(verb, "U-both", matrix)
    for run in (cell.dry, cell.real):
        assert all("does not carry" not in w and "not checked" not in w for w in run.warnings)


# --------------------------------------------------------------------------- #
# AC4 -- no false warnings
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vi", range(len(DROPPERS)), ids=_ids(DROPPERS))
def test_ac4a_a_document_with_nothing_to_drop_gets_no_warning(vi: int, matrix: Matrix) -> None:
    cell = check_cell(DROPPERS[vi], "P-none", matrix)
    for run in (cell.dry, cell.real):
        assert run.warnings == []
        assert run.seam_lines == []


@pytest.mark.parametrize("vi", range(len(DROPPERS)), ids=_ids(DROPPERS))
def test_ac4b_an_input_that_is_itself_a_rebuild_output_gets_no_warning(
    vi: int, matrix: Matrix
) -> None:
    cell = check_cell(DROPPERS[vi], "P-default", matrix)
    for run in (cell.dry, cell.real):
        assert run.warnings == []
        assert run.seam_lines == []


@pytest.mark.parametrize("vi", range(len(REWRITE)), ids=_ids(REWRITE))
def test_ac4c_a_rewrite_verb_carries_info_and_xmp_so_it_warns_of_nothing(
    vi: int, matrix: Matrix
) -> None:
    cell = check_cell(REWRITE[vi], "P-both", matrix)
    for run in (cell.dry, cell.real):
        assert run.warnings == []
        assert run.seam_lines == []


def test_ac4d_encrypt_over_a_plain_input_carries_no_seam_warning(inputs: Inputs) -> None:
    out = inputs.root / "ac4d.pdf"
    args = [
        str(inputs.files["P-both"]),
        "--owner-password-file",
        str(inputs.owner_pw),
        "-O",
        str(out),
    ]
    dry, real = (parse(p) for p in dry_and_real("encrypt", args))
    for run in (dry, real):
        assert run.rc == 0
        assert run.warnings == []
        assert run.seam_lines == []


def test_ac4e_decrypt_of_a_user_protected_input_carries_no_seam_warning(inputs: Inputs) -> None:
    out = inputs.root / "ac4e.pdf"
    args = [
        str(inputs.files["U-both"]),
        "--password-file",
        str(inputs.user_pw),
        "-O",
        str(out),
    ]
    dry, real = (parse(p) for p in dry_and_real("decrypt", args))
    for run in (dry, real):
        assert run.rc == 0
        assert run.warnings == []
        assert run.seam_lines == []


# --------------------------------------------------------------------------- #
# AC5 -- dry == real on warnings
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vi", range(len(DROPPERS)), ids=_ids(DROPPERS))
def test_ac5_dry_run_says_exactly_what_the_real_run_says(vi: int, matrix: Matrix) -> None:
    verb = DROPPERS[vi]
    for name in INPUTS:
        cell = matrix.cell(verb, name)
        assert cell.dry.warnings == cell.real.warnings, f"{verb} {name}"
        assert cell.dry.rc == cell.real.rc, f"{verb} {name}"


# --------------------------------------------------------------------------- #
# AC6 -- --in-place reports the pre-image
# --------------------------------------------------------------------------- #

_IN_PLACE_CAPABLE: Final[tuple[str, ...]] = (
    "compress",
    "delete",
    "linearize",
    "meta set",
    "ocr",
    "reorder",
    "repair",
    "rotate",
    "stamp",
    "watermark",
)


def test_ac6_the_in_place_population_is_the_registrys(inputs: Inputs) -> None:
    derived = {
        name
        for name, spec in _verb_specs().items()
        if "--in-place" in spec.consumes and name in DROPPERS
    }
    assert derived == set(_IN_PLACE_CAPABLE)


@pytest.mark.parametrize("vi", range(len(_IN_PLACE_CAPABLE)), ids=_ids(_IN_PLACE_CAPABLE))
def test_ac6_in_place_reports_the_encrypted_pre_image(vi: int, inputs: Inputs) -> None:
    verb = _IN_PLACE_CAPABLE[vi]
    work = inputs.root / "inplace" / verb.replace(" ", "_")
    work.mkdir(parents=True)
    target = work / "doc.pdf"
    shutil.copy(inputs.files["U-both"], target)
    args = argv_for(verb, "U-both", inputs, target, in_place=True)
    dry, real = (parse(p) for p in dry_and_real(verb, args))
    label = str(target)
    # PDF-116: the authenticated rebuild carries /Info and XMP, so only W-ENC remains.
    expected = [w_enc(label, verb, in_place=True)]
    assert dry.rc == 0 and real.rc == 0, (dry.stderr[-300:], real.stderr[-300:])
    assert dry.warnings == expected
    assert real.warnings == expected
    # Current behaviour, unchanged: the input is now plaintext; the backup keeps the ciphertext.
    with pikepdf.Pdf.open(target) as plain:
        assert not plain.is_encrypted
    backup = Path(f"{target}.bak")
    assert backup.exists()
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.Pdf.open(backup)


# --------------------------------------------------------------------------- #
# AC7 -- merge operands
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("arm", "first", "second"),
    [
        ("encrypted-first", "U-both", "P-none"),
        ("encrypted-second", "P-none", "U-both"),
        ("encrypted-with-a-range", "U-both:1", "P-none"),
    ],
)
def test_ac7_merge_names_the_encrypted_operand_exactly_as_published(
    arm: str, first: str, second: str, inputs: Inputs
) -> None:
    def spell(operand: str) -> str:
        name, _, rng = operand.partition(":")
        return str(inputs.files[name]) + (f":{rng}" if rng else "")

    out = inputs.root / f"merge-{arm}.pdf"
    args = [
        spell(first),
        spell(second),
        "-O",
        str(out),
        *inputs.password_args("U-both"),
        "--allow-decrypted-output",  # PDF-115 D10
    ]
    dry, real = (parse(p) for p in dry_and_real("merge", args))
    encrypted = spell(first if first.startswith("U-both") else second)
    plain = str(inputs.files["P-none"])
    for run in (dry, real):
        assert run.rc == 0, run.stderr[-400:]
        assert run.warnings.count(w_enc(encrypted, "merge")) == 1
        # PDF-116: the FIRST operand is the donor (authenticated, so carried);
        # a later encrypted operand is not carried and is reported unchecked.
        later = 0 if first.startswith("U-both") else 1
        assert run.warnings.count(w_unchecked(encrypted, "merge")) == later
        assert all(plain not in w for w in run.warnings)
        assert len(run.warnings) == 1 + later
    assert dry.warnings == real.warnings


def test_the_operand_splitter_agrees_with_merges_own() -> None:
    from pdf_tooling.ops.merge import split_input_spec

    for raw in (
        "notes:draft.pdf",
        "a.pdf:1-3",
        r"C:\docs\a.pdf:1-3",
        "a:1-3:all",
        "plain.pdf",
        "a.pdf:even",
        "a.pdf:",
        "a.pdf:1",
        "a.pdf:last,1",
    ):
        assert carriage.split_operand(raw) == split_input_spec(raw), raw


# --------------------------------------------------------------------------- #
# AC8 -- one warning per source, not per output
# --------------------------------------------------------------------------- #


def test_ac8_split_warns_once_per_source_however_many_parts(inputs: Inputs) -> None:
    out_dir = inputs.root / "ac8-parts"
    args = [
        str(inputs.files["U-both"]),
        "--each-page",
        "--out-dir",
        str(out_dir),
        *inputs.password_args("U-both"),
        "--allow-decrypted-output",  # PDF-115 D10
    ]
    dry, real = (parse(p) for p in dry_and_real("split", args))
    label = inputs.label("U-both")
    for run in (dry, real):
        assert run.rc == 0
        assert len(run.env["items"]) > 1
        assert run.warnings == [w_enc(label, "split")]  # PDF-116: carried into every part
    assert dry.warnings == real.warnings


# --------------------------------------------------------------------------- #
# AC9 -- a failed or refused item gets nothing
# --------------------------------------------------------------------------- #


def test_ac9a_a_failed_batch_item_is_not_named_in_any_warning(inputs: Inputs) -> None:
    garbage = inputs.root / "garbage.pdf"
    garbage.write_text("this is not a pdf\n")
    out_dir = inputs.root / "ac9a"
    proc = run_cli(
        "rotate",
        str(inputs.files["U-both"]),
        str(garbage),
        "--pages",
        "1",
        "--angle",
        "90",
        "--out-dir",
        str(out_dir),
        *inputs.password_args("U-both"),
        "--allow-decrypted-output",  # PDF-115 D10
        "-o",
        "json",
    )
    run = parse(proc)
    assert run.rc == 1, run.stderr[-400:]
    label = inputs.label("U-both")
    assert run.warnings.count(w_enc(label, "rotate")) == 1
    assert all("garbage.pdf" not in w for w in run.warnings)


def test_ac9b_a_refused_plan_carries_no_carriage_warning(inputs: Inputs) -> None:
    occupied = inputs.root / "occupied.pdf"
    occupied.write_bytes(inputs.files["P-none"].read_bytes())
    proc = run_cli(
        "rotate",
        str(inputs.files["P-both"]),
        "--pages",
        "1",
        "--angle",
        "90",
        "-O",
        str(occupied),
        "--dry-run",
        "-o",
        "json",
    )
    run = parse(proc)
    item = run.env["items"][0]
    assert item["ok"] is False
    assert item["detail"]["would_exit"] == 5
    assert run.warnings == []


# --------------------------------------------------------------------------- #
# AC10 -- order: the verb's own warnings come first
# --------------------------------------------------------------------------- #


def test_ac10_the_verbs_own_warnings_precede_the_carriage_warning(
    inputs: Inputs, corpus: Any
) -> None:
    plain = inputs.root / "blank-plain.pdf"
    bearing = inputs.root / "blank-bearing.pdf"
    _write_pdf(corpus.path("no_contents_page"), plain, info=False, xmp=False)
    _write_pdf(corpus.path("no_contents_page"), bearing, info=True, xmp=False)
    base = ["--text", "DRAFT"]
    own = parse(
        run_cli("watermark", str(plain), *base, "-O", str(inputs.root / "w1.pdf"), "-o", "json")
    )
    assert own.rc == 0 and own.warnings, "the fixture must raise the verb's own blank-page warning"
    got = parse(
        run_cli("watermark", str(bearing), *base, "-O", str(inputs.root / "w2.pdf"), "-o", "json")
    )
    assert got.rc == 0
    expected_own = [w.replace(str(plain), str(bearing)) for w in own.warnings]
    # PDF-116: the /Info is carried, so the verb's own warnings are all there is.
    assert got.warnings == expected_own


# --------------------------------------------------------------------------- #
# AC11 -- table shape
# --------------------------------------------------------------------------- #


def test_ac11_table_mode_puts_the_warning_on_stderr_only(inputs: Inputs) -> None:
    out = inputs.root / "ac11.pdf"
    proc = run_cli(
        "rotate",
        str(inputs.files["P-both"]),
        "--pages",
        "1",
        "--angle",
        "90",
        "-O",
        str(out),
        "-o",
        "table",
    )
    assert proc.returncode == 0
    assert "warning" not in proc.stdout.lower()
    # PDF-116: carried, so rotate over P-both says nothing; the stdout/stderr split
    # is still pinned by the encrypted arm (test_ac1_*) and by the empty stderr here.
    assert proc.stderr.splitlines() == []


# --------------------------------------------------------------------------- #
# AC12 -- the declaration is complete, and new verbs inherit or red
# --------------------------------------------------------------------------- #


def test_ac12a_keys_equal_the_tree() -> None:
    assert set(CARRIAGE) == set(_verb_specs())


def test_ac12b_a_synthetic_verb_is_reported_undeclared() -> None:
    import typer
    import typer.main

    from pdf_tooling.cli.main import app

    extra = typer.Typer()

    @extra.command("synthetic-verb")
    def _synthetic() -> None:  # pragma: no cover - never invoked
        return None

    @extra.command("sibling-verb")
    def _sibling() -> None:  # pragma: no cover - never invoked
        return None

    root = typer.main.get_command(app)
    root.add_command(typer.main.get_command(extra).commands["synthetic-verb"], "synthetic-verb")  # type: ignore[attr-defined]
    names = {v.name for v in discover_verbs(root) if not v.is_group}
    assert carriage.undeclared(names) == {"synthetic-verb"}


def test_ac12c_an_undeclared_verb_drops_on_every_dimension() -> None:
    facts = CarriageFacts(
        encrypted=True,
        readable=True,
        info_keys=frozenset({"/Title"}),
        producer=None,
        has_xmp=True,
    )
    got = carriage.carriage_warnings("synthetic-verb", "x.pdf", facts)
    assert got == (
        w_enc("x.pdf", "synthetic-verb"),
        w_meta("x.pdf", "synthetic-verb", BOTH),
    )


# --------------------------------------------------------------------------- #
# AC13 -- the derived population agrees with the table
# --------------------------------------------------------------------------- #


def _is_pdf(path: Path) -> bool:
    try:
        return path.is_file() and path.read_bytes()[:5] == b"%PDF-"
    except OSError:
        return False


def test_derived_writers_agree(inputs: Inputs, corpus: Any) -> None:
    """E5's derivation: mutating, consumes a PDF destination flag, takes a PDF
    operand, and a real run through the registered invocation leaves a PDF."""
    derived: set[str] = set()
    for name, spec in _verb_specs().items():
        if not spec.is_mutating or not set(spec.consumes) & {"--output", "--out-dir"}:
            continue
        scratch = inputs.root / "derive" / name.replace(" ", "_")
        scratch.mkdir(parents=True)
        argv = INVOCATIONS[name].build(corpus, scratch)
        if not argv or not _is_pdf(Path(argv[0])):
            continue
        proc = run_cli(name, *argv)
        if proc.returncode != 0:
            continue
        written: list[Path] = []
        for flag in ("-O", "--out-dir"):
            if flag in argv:
                target = Path(argv[argv.index(flag) + 1])
                written += sorted(target.glob("*")) if target.is_dir() else [target]
        if any(_is_pdf(p) for p in written):
            derived.add(name)
    declared = {name for name, row in CARRIAGE.items() if row.encryption is not Drop.NA}
    assert derived == declared
    assert declared == set(REBUILD) | set(REWRITE) | set(CRYPTO)


# --------------------------------------------------------------------------- #
# AC14 -- (inverted by PDF-116) a REBUILD output carries the source's /Info and XMP
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vi", range(len(REBUILD)), ids=_ids(REBUILD))
def test_ac14_every_rebuild_output_carries_exactly_the_engine_default_info(
    vi: int, matrix: Matrix
) -> None:
    """PDF-116 inverted this: it pinned ``/Info == {/Producer}`` (the engine
    default) at ``9809a7f``. The name is kept so no test function disappears
    (PDF-116 AC13); the pin now says the output carries the SOURCE's, unchanged."""
    cell = matrix.cell(REBUILD[vi], "P-both")
    assert cell.real.rc == 0
    outputs = sorted(cell.dest.rglob("*.pdf"))
    assert outputs
    with pikepdf.Pdf.open(matrix.inputs.files["P-both"]) as source:
        want_info = {str(k): v.unparse() for k, v in source.docinfo.items()}
        want_xmp = bytes(source.Root.Metadata.read_bytes())
    for path in outputs:
        with pikepdf.Pdf.open(path) as pdf:
            got_info = {str(k): v.unparse() for k, v in pdf.docinfo.items()}
            assert got_info == want_info, path
            assert bytes(pdf.Root.Metadata.read_bytes()) == want_xmp, path


# --------------------------------------------------------------------------- #
# AC15 -- the seam never reads the secret
# --------------------------------------------------------------------------- #


def test_ac15a_the_fact_read_takes_no_password() -> None:
    params = list(inspect.signature(StructureEngine.read_carriage_facts).parameters)
    assert params == ["self", "data"]


def _in_process(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    from pdf_tooling.cli.common import reset_error_format
    from pdf_tooling.cli.main import main

    monkeypatch.setattr(sys, "argv", ["pdftooling", *argv])
    reset_error_format()
    with pytest.raises(SystemExit) as excinfo:
        main()
    code = excinfo.value.code
    return int(code) if code is not None else 0


def test_ac15b_a_dry_run_that_does_not_authenticate_reads_the_secret_zero_times(
    inputs: Inputs, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pdf_tooling.cli.password as password_module

    reads: list[int] = []
    original = password_module._read_file

    def counting(*args: Any, **kwargs: Any) -> Any:
        reads.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(password_module, "_read_file", counting)
    common = [
        "compress",
        str(inputs.files["U-both"]),
        "-O",
        str(inputs.root / "ac15b.pdf"),
        "--password-file",
        str(inputs.user_pw),
        "--allow-decrypted-output",  # PDF-115 D10
        "-o",
        "json",
    ]
    assert _in_process([*common, "--dry-run"], monkeypatch) == 0
    assert reads == [], "the dry tier and the carriage seam must not read the secret"
    # Control: the counter does see the real run's single read, so the zero is not vacuous.
    assert _in_process(common, monkeypatch) == 0
    assert len(reads) == 1


def test_the_seam_never_raises_and_a_direct_call_records_nothing(tmp_path: Path) -> None:
    garbage = tmp_path / "garbage.pdf"
    garbage.write_text("not a pdf")
    carriage.record(garbage)  # no ledger open: a no-op
    token = carriage.open_ledger()
    try:
        carriage.record(garbage)
        carriage.record(tmp_path / "missing.pdf")
        ledger = carriage._LEDGER.get()
        assert ledger is not None and ledger.facts == {}
    finally:
        carriage.close_ledger(token)
    assert carriage._LEDGER.get() is None


def test_the_seam_never_raises_when_the_source_cannot_be_canonicalised(tmp_path: Path) -> None:
    """`record()`'s never-raises claim holds on EVERY path, including the key derivation.

    `canonical(source)` used to sit ABOVE the `try`, so a source it cannot key
    escaped the seam. Natural inputs exist, no monkeypatch needed: an unknown
    `~user` makes `expanduser()` raise ``RuntimeError``, and an embedded NUL makes
    `resolve()` raise ``ValueError``. Neither can reach `record()` through the CLI
    (the verb's own existence check refuses first), so the seam is driven directly.
    """
    token = carriage.open_ledger()
    try:
        for operand in (Path("~no_such_user_pdf108_zz/a.pdf"), Path("a\0b.pdf")):
            with pytest.raises(
                (RuntimeError, ValueError)
            ):  # control: the key derivation DOES raise
                carriage.canonical(operand)
            assert carriage.record(operand) is None
        ledger = carriage._LEDGER.get()
        assert ledger is not None and ledger.facts == {} and ledger.spelled == {}
    finally:
        carriage.close_ledger(token)


def test_a_raising_canonical_leaves_the_verbs_own_path_exactly_as_it_was(
    inputs: Inputs, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With the key derivation made to raise, the verb's normal AND error paths are unchanged.

    Approach: monkeypatch (`carriage.canonical`), because no operand that reaches
    `record()` through the CLI can make the real one raise. The baseline is the same
    in-process run BEFORE the patch, so "exactly as before" is compared, not assumed.
    """
    source = inputs.files["U-both"]
    ok_argv = ["compress", str(source), "-O", "{out}", "-o", "json"]
    missing = [
        "compress",
        str(inputs.root / "no-such.pdf"),
        "-O",
        str(inputs.root / "c.pdf"),
        "-o",
        "json",
    ]
    password = ["--password-file", str(inputs.user_pw), "--allow-decrypted-output"]  # PDF-115 D10

    counter = iter(range(100))

    def run(argv: list[str]) -> tuple[int, dict[str, Any]]:
        # A fresh output per run (a repeat would refuse as a clobber), normalised
        # out of the envelope; timings are dropped so only behaviour is compared.
        out = str(inputs.root / f"canon-{next(counter)}.pdf")
        capsys.readouterr()
        code = _in_process([out if a == "{out}" else a for a in argv], monkeypatch)
        text = capsys.readouterr().out.replace(out, "<out>")
        envelope = json.loads(text)
        envelope.pop("duration_ms", None)
        for item in envelope.get("items", []):
            item.pop("duration_ms", None)
        return code, envelope

    base_ok = run([*ok_argv, *password])
    base_err = run(missing)
    assert base_ok[0] == 0 and base_err[0] == 4
    assert base_ok[1]["warnings"], "control: the unpatched run does carry the W-ENC warning"

    def boom(path: Any) -> Any:
        raise RuntimeError("canonical exploded")

    monkeypatch.setattr(carriage, "canonical", boom)
    patched_ok = run([*ok_argv, *password])
    # The write succeeds exactly as before; the only difference is the honest
    # one: no fact was recorded, so the descriptive warning is absent.
    assert patched_ok[0] == 0
    assert patched_ok[1] == {**base_ok[1], "warnings": []}
    # The verb's own error path fires unchanged (code 4, its own envelope).
    assert run(missing) == base_err


# --------------------------------------------------------------------------- #
# AC16 -- registry classifications do not move
# --------------------------------------------------------------------------- #


def test_ac16_the_registry_classifications_have_not_moved() -> None:
    mutating = {v.name for v in discover_verbs() if v.is_mutating}
    assert mutating == set(MUTATING_AT_A219BCF)
    assert len(mutating) == 23
    assert engine_blind_verbs() == ENGINE_BLIND_AT_A219BCF


# --------------------------------------------------------------------------- #
# AC17 -- --help stays cheap
# --------------------------------------------------------------------------- #

_HELP_PROBE: Final[str] = (
    "import runpy, sys\n"
    "sys.argv = ['pdftooling'] + sys.argv[1:]\n"
    "try:\n"
    "    runpy.run_module('pdf_tooling', run_name='__main__')\n"
    "except SystemExit:\n"
    "    pass\n"
    "print('LOADED=' + str('pdf_tooling.ops.carriage' in sys.modules))\n"
)


def _carriage_loaded_after(*argv: str) -> bool:
    proc = subprocess.run(
        [sys.executable, "-c", _HELP_PROBE, *argv],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert "LOADED=" in proc.stdout, proc.stderr[-400:]
    return "LOADED=True" in proc.stdout


def test_ac17_help_does_not_load_the_carriage_module() -> None:
    assert _carriage_loaded_after("--help") is False
    assert _carriage_loaded_after("rotate", "--help") is False


def test_ac17_control_a_verb_run_does_load_it(inputs: Inputs) -> None:
    assert (
        _carriage_loaded_after(
            "rotate",
            str(inputs.files["P-none"]),
            "--pages",
            "1",
            "--angle",
            "90",
            "-O",
            str(inputs.root / "ac17.pdf"),
            "--dry-run",
        )
        is True
    )


# --------------------------------------------------------------------------- #
# AC18 -- the false help sentence is gone, and stays gone
# --------------------------------------------------------------------------- #


def test_ac18_rotate_help_no_longer_claims_nothing_else() -> None:
    text = run_cli("rotate", "--help").stdout
    assert "nothing else" not in text
    assert "/Info" in text and "XMP" in text


@pytest.mark.parametrize("vi", range(len(REBUILD)), ids=_ids(REBUILD))
def test_ac18_no_rebuild_verb_claims_nothing_else(vi: int) -> None:
    assert "nothing else" not in run_cli(REBUILD[vi], "--help").stdout


# --------------------------------------------------------------------------- #
# AC19 -- README states current behaviour, derived
# --------------------------------------------------------------------------- #


def _backticked(sentence: str) -> list[str]:
    return re.findall(r"`([^`]+)`", sentence)


def _sentence_led_by(text: str, lead: str) -> str:
    start = text.index(lead)
    end = text.index(".\n", start)
    return text[start + len(lead) : end]


def test_ac19_readme_states_what_a_write_does_not_carry() -> None:
    text = (REPO_ROOT / "README.md").read_text()
    assert "### What a write does not carry" in text
    unencrypted = _sentence_led_by(text, "Written unencrypted from an encrypted input:")
    carried = _sentence_led_by(text, "Carry the input's /Info and XMP packet unchanged:")
    assert set(_backticked(unencrypted)) == set(REBUILD) | set(REWRITE)
    # PDF-116 D8: `merge` carries only the FIRST input's, so it is not in the parsed sentence.
    assert set(_backticked(carried)) == (set(REBUILD) - {"merge"}) | set(REWRITE) | set(CRYPTO)
    # Compare with the declaration table, not only with this module's literals.
    assert set(_backticked(unencrypted)) == {
        n for n, row in CARRIAGE.items() if row.encryption is Drop.DROPS
    }
    assert set(_backticked(carried)) == {
        n for n, row in CARRIAGE.items() if row.info is Drop.CARRIES and row.xmp is Drop.CARRIES
    }
    assert "the output it writes is not encrypted" in text


# --------------------------------------------------------------------------- #
# PDF-116: REBUILD carries /Info and XMP (merge: the first input's), so the declared
# classes in this module are the table's.
# --------------------------------------------------------------------------- #


def test_the_declared_classes_in_this_module_are_the_tables() -> None:
    table: dict[str, Callable[[carriage.Carriage], bool]] = {
        "rebuild": lambda c: (
            (c.encryption, c.info, c.xmp) == (Drop.DROPS, Drop.CARRIES, Drop.CARRIES)
        ),
        "merge": lambda c: (c.encryption, c.info, c.xmp) == (Drop.DROPS, Drop.FIRST, Drop.FIRST),
        "rewrite": lambda c: (
            (c.encryption, c.info, c.xmp) == (Drop.DROPS, Drop.CARRIES, Drop.CARRIES)
        ),
        "crypto": lambda c: (
            (c.encryption, c.info, c.xmp) == (Drop.PURPOSE, Drop.CARRIES, Drop.CARRIES)
        ),
    }
    for verbs, kind in (
        (tuple(v for v in REBUILD if v != "merge"), "rebuild"),
        (("merge",), "merge"),
        (REWRITE, "rewrite"),
        (CRYPTO, "crypto"),
    ):
        for verb in verbs:
            assert table[kind](CARRIAGE[verb]), (verb, kind)


# --------------------------------------------------------------------------- #
# Matching an item to its source: by spelling, then by canonical path
# --------------------------------------------------------------------------- #


def test_a_relative_operand_is_named_exactly_as_the_item_publishes_it(inputs: Inputs) -> None:
    out = inputs.root / "relative-out.pdf"
    proc = run_cli(
        "rotate",
        "U-both.pdf",
        "--pages",
        "1",
        "--angle",
        "90",
        "-O",
        str(out),
        *inputs.password_args("U-both"),
        "--allow-decrypted-output",  # PDF-115 D10
        "-o",
        "json",
        cwd=inputs.root,
    )
    run = parse(proc)
    assert run.rc == 0, run.stderr[-400:]
    assert run.warnings == [w_enc("U-both.pdf", "rotate")]  # PDF-116: carried


def test_an_item_published_under_another_spelling_still_finds_its_source(inputs: Inputs) -> None:
    from pdf_tooling.models import SCHEMA_VERSION, ItemResult, OperationResult

    source = inputs.files["O-both"]
    alias = f"{source.parent}/../{source.parent.name}/{source.name}"
    token = carriage.open_ledger()
    try:
        carriage.record(source)
        item = ItemResult(
            input=alias,
            output="out.pdf",
            ok=True,
            exit_code=0,
            message=None,
            bytes_before=None,
            bytes_after=None,
            duration_ms=0,
        )
        result = OperationResult(SCHEMA_VERSION, "rotate", False, (item,), (), 0)
        amended = carriage.amend(result)
    finally:
        carriage.close_ledger(token)
    assert list(amended.warnings) == expected_for("rotate", "O-both", alias)
