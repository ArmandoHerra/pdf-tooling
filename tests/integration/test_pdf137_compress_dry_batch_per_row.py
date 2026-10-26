"""PDF-137 -- a ``compress --dry-run`` batch predicts each row's OWN code.

README ``## Exit codes`` promises that a ``--dry-run`` mirrors the code the real run
would return, with one carve-out: a supplied password's correctness is never tested
(X-89, "a preview must not become an oracle"). A ``compress`` dry batch broke the
promise twice (ledger ``952937b15a``, ``72d60e9040``; carriers B-475, B-474):

* no password: one input's password failure was stamped on EVERY row (``[6,6,6]``
  against the real ``[0,6,0]``);
* a password supplied: the credential-free parse that detects a malformed input
  never ran (``[0,0,0]`` against the real ``[0,1,6]``).

This module is independent of every other test module: fixtures are built here with
pikepdf, every expected cell is a LITERAL, and every cell is a ``(dry, real)`` PAIR.
The "written" oracle is the directory listing, never the payload.

Provenance of every literal: ``7b1286b``, 2026-10-25, PDF-137 E3 (re-measured on the
PDF-135 base ``68447f3``, 2026-10-26, with the same results).

Reading of the PDF-135 erratum (X-1111(b)): a dry refusal rides an OPERATION envelope
and the real one an ERROR envelope, so a dry-vs-real comparison is on the exit code and
the row verdicts, with the envelope KIND recorded per tier rather than compared.

The decisive arms (a plausible wrong fix answers differently): B-a with the RIGHT
user password (a "predict 6 for any encrypted row" fix says ``6``), and B-e/none (a
batch-wide refusal says ``[6,1,6,6,6]``).
"""

from __future__ import annotations

import ast
import json
import pathlib
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pikepdf
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from fs_snapshot import redirected_environment  # noqa: E402
from registry import run_cli  # noqa: E402

SRC_DIR = Path(__file__).resolve().parents[2] / "src" / "pdf_tooling"
FLAG = "--allow-decrypted-output"

#: Which fixtures are encrypted (the module's own table; the carve-out test reads it).
ENCRYPTED = frozenset({"UO-AES256", "UO-AES256-b", "O-AES256", "O-RC4"})
PW_ARGS: Final[dict[str, list[str]]] = {
    "none": [],
    "u": ["--password-file", "u.pw"],
    "o": ["--password-file", "o.pw"],
    "x": ["--password-file", "x.pw"],
}


def _save(path: Path, **encryption: Any) -> None:
    pdf = pikepdf.new()
    pdf.add_blank_page()
    kwargs: dict[str, Any] = {}
    if encryption:
        kwargs["encryption"] = pikepdf.Encryption(**encryption)
    pdf.save(path, **kwargs)
    pdf.close()


def _build_fixtures(root: Path) -> None:
    root.mkdir(parents=True)
    _save(root / "PLAIN-a.pdf")
    _save(root / "PLAIN-b.pdf")
    _save(root / "O-AES256.pdf", user="", owner="o-pw", R=6)
    _save(root / "O-RC4.pdf", user="", owner="o-pw", R=3, aes=False, metadata=False)
    _save(root / "UO-AES256.pdf", user="u-pw", owner="o-pw", R=6)
    shutil.copy(root / "UO-AES256.pdf", root / "UO-AES256-b.pdf")
    (root / "corrupt.pdf").write_bytes(b"%PDF-1.7\ngarbage\n")
    for name, text in (("u.pw", "u-pw"), ("o.pw", "o-pw"), ("x.pw", "x-wrong")):
        (root / name).write_text(text, encoding="utf-8")
        (root / name).chmod(0o600)


@dataclass(frozen=True)
class Run:
    rc: int
    kind: str  # "operation" | "error"
    payload_code: int | None
    rows: tuple[tuple[bool, int], ...]
    items: tuple[dict[str, Any], ...]
    error_message: str | None
    files: tuple[str, ...]


class Lab:
    """Fixtures built once; every run gets a FRESH copy so a real run's output
    never leaks into the next cell."""

    def __init__(self, root: Path) -> None:
        self.root = root
        _build_fixtures(root / "master")
        self.env, _ = redirected_environment(root / "env")
        self.env.pop("PDF_TOOLING_PASSWORD", None)
        self.env.pop("PDF_TOOLING_OWNER_PASSWORD", None)
        self._n = 0
        self._cache: dict[tuple[Any, ...], Run] = {}

    def run(self, argv: tuple[str, ...]) -> Run:
        if (argv,) in self._cache:
            return self._cache[(argv,)]
        self._n += 1
        cwd = self.root / f"run{self._n}"
        shutil.copytree(self.root / "master", cwd)
        proc = run_cli(*argv, "-o", "json", stdin="", env=self.env, cwd=cwd)
        data = json.loads(proc.stdout)
        files = tuple(sorted(p.name for p in (cwd / "d").glob("*"))) if (cwd / "d").is_dir() else ()
        if "error" in data:
            result = Run(
                proc.returncode,
                "error",
                data["error"]["code"],
                (),
                (),
                data["error"]["message"],
                files,
            )
        else:
            rows = tuple((i["ok"], i["exit_code"]) for i in data["items"])
            result = Run(
                proc.returncode,
                "operation",
                data.get("exit_code"),
                rows,
                tuple(data["items"]),
                None,
                files,
            )
        self._cache[(argv,)] = result
        return result


@pytest.fixture(scope="module")
def lab(tmp_path_factory: pytest.TempPathFactory) -> Lab:
    return Lab(tmp_path_factory.mktemp("pdf137"))


def _codes(run: Run) -> list[int]:
    return [code for _ok, code in run.rows]


def _pair(lab: Lab, verb_args: list[str], pw: str, *, flag: bool = True) -> tuple[Run, Run]:
    args = [*verb_args, *PW_ARGS[pw], *([FLAG] if flag else [])]
    dry = lab.run(("compress", "--dry-run", *args))
    real = lab.run(("compress", *args))
    return dry, real


# --------------------------------------------------------------------------- #
# Single-input cells.  (dry rc, dry kind, dry rows) , (real rc, real kind, real rows)
# --------------------------------------------------------------------------- #

OP0 = (0, "operation", [0])
ERR1 = (1, "error", [])
ERR5 = (5, "error", [])
ERR6 = (6, "error", [])
DRY6 = (6, "operation", [6])

#: input -> {password arm -> (dry, real)};.
SINGLE: Final[dict[str, dict[str, tuple[Any, Any]]]] = {
    "PLAIN-a": dict.fromkeys(("none", "u", "o", "x"), (OP0, OP0)),
    "corrupt": dict.fromkeys(("none", "u", "o", "x"), (ERR1, ERR1)),
    "UO-AES256": {"none": (DRY6, ERR6), "u": (OP0, OP0), "o": (OP0, OP0), "x": (OP0, ERR6)},
    "O-AES256": {"none": (OP0, OP0), "u": (OP0, ERR6), "o": (OP0, OP0), "x": (OP0, ERR6)},
    "O-RC4": {"none": (OP0, OP0), "u": (OP0, ERR6), "o": (OP0, OP0), "x": (OP0, ERR6)},
}
SINGLE_CELLS = [(name, arm) for name, arms in SINGLE.items() for arm in arms]
#: no-flag control: an encrypted operand without --allow-decrypted-output is 5 in both tiers.
NOFLAG_CELLS = [(n, a) for n in ("UO-AES256", "O-AES256") for a in ("none", "x")]


def _shape(run: Run) -> tuple[int, str, list[int]]:
    return (run.rc, run.kind, _codes(run))


@pytest.mark.parametrize(("name", "arm"), SINGLE_CELLS)
def test_ac3_single_input_dry_real_pairs(lab: Lab, name: str, arm: str) -> None:
    dry, real = _pair(lab, [f"{name}.pdf", "-O", "o.pdf"], arm)
    want_dry, want_real = SINGLE[name][arm]
    assert (_shape(dry), _shape(real)) == (want_dry, want_real)


@pytest.mark.parametrize(("name", "arm"), NOFLAG_CELLS)
def test_ac3_single_input_dry_real_pairs_no_flag_control(lab: Lab, name: str, arm: str) -> None:
    dry, real = _pair(lab, [f"{name}.pdf", "-O", "o.pdf"], arm, flag=False)
    assert (_shape(dry), _shape(real)) == (ERR5, ERR5)


@pytest.mark.parametrize("arm", ["u", "o", "x"])
def test_ac3_a_corrupt_input_with_a_password_is_the_same_error_in_both_tiers(
    lab: Lab, arm: str
) -> None:
    dry, real = _pair(lab, ["corrupt.pdf", "-O", "o.pdf"], arm)
    assert (dry.rc, dry.kind, real.rc, real.kind) == (1, "error", 1, "error")
    assert dry.error_message == real.error_message


# --------------------------------------------------------------------------- #
# Batch cells.  shape -> inputs; (shape, arm) -> (dry rc, dry rows, real rc, real rows, files)
# --------------------------------------------------------------------------- #

SHAPES: Final[dict[str, tuple[str, ...]]] = {
    "B-a": ("PLAIN-a", "corrupt", "UO-AES256"),
    "B-b": ("PLAIN-a", "UO-AES256", "PLAIN-b"),
    "B-c": ("PLAIN-a", "O-AES256", "PLAIN-b"),
    "B-d": ("PLAIN-a", "corrupt", "PLAIN-b"),
    "B-e": ("PLAIN-a", "corrupt", "UO-AES256", "O-AES256", "PLAIN-b"),
    "B-f": ("UO-AES256", "UO-AES256-b"),
    "B-g": ("corrupt", "UO-AES256"),
}

PA, PB, UO, OA = "PLAIN-a.pdf", "PLAIN-b.pdf", "UO-AES256.pdf", "O-AES256.pdf"
UOB = "UO-AES256-b.pdf"

#: (shape, arm) -> (dry rc, dry rows, real rc, real rows, real files on disk)
BATCH: Final[dict[tuple[str, str], tuple[int, list[int], int, list[int], tuple[str, ...]]]] = {
    ("B-a", "none"): (1, [0, 1, 6], 1, [0, 1, 6], (PA,)),
    ("B-a", "u"): (1, [0, 1, 0], 1, [0, 1, 0], (PA, UO)),
    ("B-a", "o"): (1, [0, 1, 0], 1, [0, 1, 0], (PA, UO)),
    ("B-a", "x"): (1, [0, 1, 0], 1, [0, 1, 6], (PA,)),
    ("B-b", "none"): (1, [0, 6, 0], 1, [0, 6, 0], (PA, PB)),
    ("B-b", "u"): (0, [0, 0, 0], 0, [0, 0, 0], (PA, PB, UO)),
    ("B-b", "o"): (0, [0, 0, 0], 0, [0, 0, 0], (PA, PB, UO)),
    ("B-b", "x"): (0, [0, 0, 0], 1, [0, 6, 0], (PA, PB)),
    ("B-c", "none"): (0, [0, 0, 0], 0, [0, 0, 0], (OA, PA, PB)),
    ("B-c", "u"): (0, [0, 0, 0], 1, [0, 6, 0], (PA, PB)),
    ("B-c", "o"): (0, [0, 0, 0], 0, [0, 0, 0], (OA, PA, PB)),
    ("B-c", "x"): (0, [0, 0, 0], 1, [0, 6, 0], (PA, PB)),
    ("B-d", "none"): (1, [0, 1, 0], 1, [0, 1, 0], (PA, PB)),
    ("B-d", "u"): (1, [0, 1, 0], 1, [0, 1, 0], (PA, PB)),
    ("B-d", "o"): (1, [0, 1, 0], 1, [0, 1, 0], (PA, PB)),
    ("B-d", "x"): (1, [0, 1, 0], 1, [0, 1, 0], (PA, PB)),
    ("B-e", "none"): (1, [0, 1, 6, 0, 0], 1, [0, 1, 6, 0, 0], (OA, PA, PB)),
    ("B-e", "u"): (1, [0, 1, 0, 0, 0], 1, [0, 1, 0, 6, 0], (PA, PB, UO)),
    ("B-e", "o"): (1, [0, 1, 0, 0, 0], 1, [0, 1, 0, 0, 0], (OA, PA, PB, UO)),
    ("B-e", "x"): (1, [0, 1, 0, 0, 0], 1, [0, 1, 6, 6, 0], (PA, PB)),
    ("B-f", "none"): (1, [6, 6], 1, [6, 6], ()),
    ("B-f", "u"): (0, [0, 0], 0, [0, 0], (UO, UOB)),
    ("B-f", "o"): (0, [0, 0], 0, [0, 0], (UO, UOB)),
    ("B-f", "x"): (0, [0, 0], 1, [6, 6], ()),
    ("B-g", "none"): (1, [1, 6], 1, [1, 6], ()),
    ("B-g", "u"): (1, [1, 0], 1, [1, 0], (UO,)),
    ("B-g", "o"): (1, [1, 0], 1, [1, 0], (UO,)),
    ("B-g", "x"): (1, [1, 0], 1, [1, 6], ()),
}
BATCH_CELLS = sorted(BATCH)


def _batch_pair(lab: Lab, shape: str, arm: str) -> tuple[Run, Run]:
    inputs = [f"{n}.pdf" for n in SHAPES[shape]]
    return _pair(lab, [*inputs, "--out-dir", "d"], arm)


@pytest.mark.parametrize(("shape", "arm"), BATCH_CELLS)
def test_ac4_batch_dry_real_pairs(lab: Lab, shape: str, arm: str) -> None:
    dry, real = _batch_pair(lab, shape, arm)
    dry_rc, dry_rows, real_rc, real_rows, real_files = BATCH[(shape, arm)]
    assert (dry.rc, dry.kind, _codes(dry)) == (dry_rc, "operation", dry_rows)
    assert (real.rc, real.kind, _codes(real)) == (real_rc, "operation", real_rows)
    # the payload's own run code is the process exit code in both tiers
    assert (dry.payload_code, real.payload_code) == (dry_rc, real_rc)
    # row ok flag is exactly "code is 0"
    assert all(ok == (code == 0) for ok, code in dry.rows + real.rows)
    # the real files on disk are the oracle; a dry run writes nothing
    assert real.files == tuple(sorted(real_files))
    assert dry.files == ()


#: Every divergent row is a supplied password on an encrypted input: 15 rows in all
#: (5 single-input cells, 10 batch rows).
CARVE_OUT_ROW_COUNT: Final = 15


def _divergent_rows(lab: Lab) -> list[tuple[str, str, int, Run, Run]]:
    found: list[tuple[str, str, int, Run, Run]] = []
    for name, arm in SINGLE_CELLS:
        dry, real = _pair(lab, [f"{name}.pdf", "-O", "o.pdf"], arm)
        dry_codes = _codes(dry) if dry.kind == "operation" else [dry.rc]
        real_codes = _codes(real) if real.kind == "operation" else [real.rc]
        if dry_codes != real_codes:
            found.append((name, arm, 0, dry, real))
    for shape, arm in BATCH_CELLS:
        dry, real = _batch_pair(lab, shape, arm)
        for index, (dcode, rcode) in enumerate(zip(_codes(dry), _codes(real), strict=True)):
            if dcode != rcode:
                found.append((SHAPES[shape][index], arm, index, dry, real))
    return found


def test_ac4_every_divergent_row_is_the_password_carve_out(lab: Lab) -> None:
    divergent = _divergent_rows(lab)
    for name, arm, index, dry, real in divergent:
        assert arm != "none", "a password was supplied"
        assert name in ENCRYPTED, "the input is encrypted"
        if real.kind == "operation":
            assert real.rows[index] == (False, 6), "the real row code is 6"
            row = dry.items[index]
        else:
            assert real.rc == 6, "the real run is the auth error"
            row = dry.items[0]
        assert row["ok"] is True
        assert row["detail"]["password_verified"] is False
    assert len(divergent) == CARVE_OUT_ROW_COUNT


# --------------------------------------------------------------------------- #
# The two ledger repros, named.
# --------------------------------------------------------------------------- #


def test_ac1_the_952937b15a_batch_predicts_each_rows_own_code(lab: Lab) -> None:
    dry, real = _batch_pair(lab, "B-b", "none")
    assert (dry.rc, dry.payload_code, dry.rows) == (1, 1, ((True, 0), (False, 6), (True, 0)))
    assert (real.rc, real.payload_code, real.rows) == (1, 1, ((True, 0), (False, 6), (True, 0)))
    assert dry.files == ()
    assert real.files == (PA, PB)
    would = [item["detail"].get("would_exit") for item in dry.items]
    assert would == [0, 6, 0]


def test_ac2_the_72d60e9040_batch_predicts_the_malformed_row(lab: Lab) -> None:
    dry, real = _batch_pair(lab, "B-a", "x")
    assert (dry.rc, dry.rows) == (1, ((True, 0), (False, 1), (True, 0)))
    assert dry.items[2]["detail"]["password_verified"] is False
    assert (real.rc, real.rows) == (1, ((True, 0), (False, 1), (False, 6)))
    assert real.files == (PA,)
    assert dry.rc == real.rc
    # decisive arm: the RIGHT user password. A "predict 6 for any encrypted row" fix fails here.
    dry_u, real_u = _batch_pair(lab, "B-a", "u")
    assert (
        (dry_u.rc, dry_u.rows)
        == (real_u.rc, real_u.rows)
        == (1, ((True, 0), (False, 1), (True, 0)))
    )
    assert real_u.files == (PA, UO)


# --------------------------------------------------------------------------- #
# Run-scoped refusals keep precedence in both tiers.
# --------------------------------------------------------------------------- #

RUN_SCOPED: Final[dict[str, tuple[list[str], str, int]]] = {
    "name-without-out-dir": (["PLAIN-a.pdf", "--name", "{stem}-x.pdf"], "none", 2),
    "output-on-two-inputs": (["PLAIN-a.pdf", "PLAIN-b.pdf", "-O", "o.pdf"], "none", 2),
    "missing-single": (["nope.pdf", "-O", "o.pdf"], "none", 4),
    "missing-in-batch": (["PLAIN-a.pdf", "nope.pdf", "--out-dir", "d"], "none", 4),
    "encrypted-batch-no-flag": (["UO-AES256.pdf", "PLAIN-a.pdf", "--out-dir", "d"], "none", 5),
    "encrypted-batch-no-flag-wrong-pw": (
        ["UO-AES256.pdf", "PLAIN-a.pdf", "--out-dir", "d"],
        "x",
        5,
    ),
    "encrypted-batch-no-flag-corrupt": (
        ["UO-AES256.pdf", "corrupt.pdf", "--out-dir", "d"],
        "none",
        5,
    ),
    "encrypted-batch-no-flag-corrupt-wrong-pw": (
        ["UO-AES256.pdf", "corrupt.pdf", "--out-dir", "d"],
        "x",
        5,
    ),
}


@pytest.mark.parametrize("cell", sorted(RUN_SCOPED))
def test_ac5_run_scoped_refusals_win_in_both_tiers(lab: Lab, cell: str) -> None:
    verb_args, arm, code = RUN_SCOPED[cell]
    dry, real = _pair(lab, verb_args, arm, flag=False)
    assert (dry.rc, real.rc) == (code, code)


def test_ac5_an_out_dir_collision_is_5_in_both_tiers(lab: Lab) -> None:
    root = lab.root / "collide"
    (root / "one").mkdir(parents=True)
    (root / "two").mkdir()
    _save(root / "one" / "same.pdf")
    _save(root / "two" / "same.pdf")
    codes = []
    for dry in (True, False):
        argv = ["compress", *(["--dry-run"] if dry else []), "one/same.pdf", "two/same.pdf"]
        proc = run_cli(*argv, "--out-dir", "d", "-o", "json", stdin="", env=lab.env, cwd=root)
        codes.append(proc.returncode)
    assert codes == [5, 5]


def test_ac5_an_existing_output_target_keeps_its_envelope_shapes(lab: Lab) -> None:
    dry = lab.run(("compress", "--dry-run", "PLAIN-a.pdf", "-O", "PLAIN-b.pdf"))
    real = lab.run(("compress", "PLAIN-a.pdf", "-O", "PLAIN-b.pdf"))
    assert (dry.rc, dry.kind, _codes(dry)) == (5, "operation", [5])
    assert (real.rc, real.kind) == (5, "error")


# --------------------------------------------------------------------------- #
# The refusal detail belongs to its own row.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("shape", "auth_index"), [("B-e", 2), ("B-b", 1)])
def test_ac6_refusal_detail_rides_only_the_auth_row(lab: Lab, shape: str, auth_index: int) -> None:
    dry, _real = _batch_pair(lab, shape, "none")
    for index, item in enumerate(dry.items):
        detail = item.get("detail")
        if detail is None:  # the corrupt row: a guard-recorded failure carries none
            continue
        assert detail["password_verified"] is False
        if index == auth_index:
            assert detail["would_exit"] == 6
            assert detail["planned_refusal"] == "AuthError"
        else:
            assert detail["would_exit"] == 0
            assert "planned_refusal" not in detail


# --------------------------------------------------------------------------- #
# The preview reads the document, never the secret (in-process counters).
# --------------------------------------------------------------------------- #

#: (operand, password arm) -> (rc, PasswordSource reads, operand read_bytes count), dry only.
#: Provenance: PDF-137 E7, the "proto dry" column.
READ_BUDGET: Final[dict[tuple[str, str], tuple[int, int, int]]] = {
    ("O-AES256", "none"): (0, 0, 2),
    ("O-AES256", "x"): (0, 0, 2),
    ("PLAIN-a", "none"): (0, 0, 2),
    ("PLAIN-a", "x"): (0, 0, 2),
}


@pytest.mark.parametrize(("operand", "arm"), sorted(READ_BUDGET))
def test_ac7_compress_dry_reads_the_document_never_the_secret(
    operand: str,
    arm: str,
    lab: Lab,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import pdf_tooling.cli.main as main_module
    import pdf_tooling.cli.password as password_module
    from pdf_tooling.cli.common import reset_error_format

    cwd = tmp_path / "w"
    shutil.copytree(lab.root / "master", cwd)
    secret_reads: list[int] = []
    operand_reads: list[int] = []
    original = password_module._read_file
    original_read_bytes = pathlib.Path.read_bytes

    def counting(*args: Any, **kwargs: Any) -> Any:
        secret_reads.append(1)
        return original(*args, **kwargs)

    def counting_read_bytes(self: Path, *args: Any, **kwargs: Any) -> bytes:
        if self.name == f"{operand}.pdf":
            operand_reads.append(1)
        return original_read_bytes(self, *args, **kwargs)

    argv = ["compress", "--dry-run", str(cwd / f"{operand}.pdf"), "-O", str(cwd / "o.pdf")]
    argv += ["--password-file", str(cwd / "x.pw")] if arm == "x" else []
    argv += [FLAG, "-o", "json"]
    monkeypatch.setattr(password_module, "_read_file", counting)
    monkeypatch.setattr(pathlib.Path, "read_bytes", counting_read_bytes)
    monkeypatch.setattr(sys, "argv", ["pdftooling", *argv])
    reset_error_format()
    with pytest.raises(SystemExit) as excinfo:
        main_module.main()
    capsys.readouterr()
    got = (int(excinfo.value.code or 0), len(secret_reads), len(operand_reads))
    assert got == READ_BUDGET[(operand, arm)]


# --------------------------------------------------------------------------- #
# Only compress probes the document (AST over src/pdf_tooling).
# --------------------------------------------------------------------------- #


def _is_call_to(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Name) and node.func.id == name)
        or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
    )


def test_ac8_only_compress_probes_the_document() -> None:
    probing: list[tuple[str, str, object]] = []
    for path in sorted(SRC_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(fn):
                if not _is_call_to(call, "predict_password_refusal"):
                    continue
                for kw in call.keywords:  # type: ignore[attr-defined]
                    if kw.arg == "probe_document":
                        value = kw.value.value if isinstance(kw.value, ast.Constant) else "?"
                        probing.append((path.name, fn.name, value))
    # the nested `_predict_row` lives INSIDE `compress_run`; both walks see the call
    assert probing
    assert {(f, v) for f, _fn, v in probing} == {("optimize.py", True)}
    assert {fn for _f, fn, _v in probing} <= {"compress_run", "_predict_row"}

    tree = ast.parse((SRC_DIR / "ops" / "document_password.py").read_text(encoding="utf-8"))
    func = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "predict_password_refusal"
    )
    kwonly = [a.arg for a in func.args.kwonlyargs]
    defaults = dict(zip(kwonly, func.args.kw_defaults, strict=True))
    default = defaults["probe_document"]
    assert isinstance(default, ast.Constant)
    assert default.value is False
