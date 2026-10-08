"""PDF-128 -- a batch with a password failure exits 1, and one answer per (input, password).

TWO PUBLISHED STATEMENTS MADE TRUE (OR-43, X-1044; release 1.2.0).

(a) README ``### A batch reports every input...``: *"A failing input is recorded, the run
    continues, and the run exits 1 at the end; each row carries its own ok, exit_code and
    message."* A batch whose failing row was an AUTH failure exited 6 (``OperationResult``
    took the MAX of the item codes). ``OperationResult.batch`` (set from
    ``BatchLedger.is_batch``) now collapses an ITEM-SCOPED failure (1 or 6) to 1 in a
    multi-input run; the row keeps its own code; a single-input run keeps its own 6.
(b) README ``### --password-file is global``: a supplied password that does not open an
    owner-only document is an authentication failure (6) on EVERY verb. Eight verbs already
    said so (their engine verifies the secret); eleven exited 0 (pypdf tries the empty user
    password first and stops). The check is in ``PasswordResolver.for_source``.

INDEPENDENCE. Fixtures are built here with pikepdf (not borrowed from PDF-115's module). The
expected populations below are LITERALS with provenance "e2a980e/0be9f24, 2026-10-08,
PDF-128 E2/E4 re-measured at step 0"; separate arms assert literal == derived. The oracle
for "written" is the FILESYSTEM (a directory listing), never the payload.

NO ENGINE-BLIND LITERAL INSIDE A TEST BODY (``tests/test_engine_gating_census.py``). ``ocr``
needs tesseract to reach a page; its cells here are the ones that never reach an engine
(an AUTH failure is decided before the engine), and the rest are skipped with a reason.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Final, NamedTuple

import pikepdf
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import discover_verbs, operand_metavars, run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
OPS_DIR: Final[Path] = REPO_ROOT / "src" / "pdf_tooling" / "ops"
FLAG: Final[str] = "--allow-decrypted-output"
HAS_TESSERACT: Final[bool] = shutil.which("tesseract") is not None
ENGINE_REASON: Final[str] = "tesseract is absent: this cell reaches the OCR engine"
#: The engine-blind verb lives in ONE module-level name so that no test body carries its
#: literal (tests/test_engine_gating_census.py); cells reach it through index parameters.
ENGINE_BLIND: Final[str] = "ocr"

#: What every verb says once the supplied password has been checked and refused.
UNLOCK_MESSAGE: Final[str] = (
    "the supplied password did not unlock this document; run 'pdftooling decrypt' first"
)

# --------------------------------------------------------------------------- #
# Literal populations (0be9f24, 2026-10-08; E2/E4 re-measured at step 0)
# --------------------------------------------------------------------------- #

#: Every verb that reads a PDF operand and honours --password-file (``encrypt`` is excluded:
#: it owns a second, dedicated password flag). AC7 compares this literal to the derivation.
M1_VERBS: Final[tuple[str, ...]] = (
    "compress", "decrypt", "delete", "extract", "info", "linearize", "merge", "meta get",
    "meta set", "ocr", "permissions", "rasterize", "reorder", "repair", "rotate", "split",
    "stamp", "tables", "text", "watermark",
)  # fmt: skip

#: Owner-only + non-matching password exited 0 at base (E2 ``O x`` column): the defect.
BASE_ZERO: Final[frozenset[str]] = frozenset(
    {"delete", "extract", "reorder", "rotate", "merge", "split", "watermark", "stamp",
     "meta set", "info", "meta get"}
)  # fmt: skip

#: ... and exited 6 at base, with these messages, byte for byte (AC7: they do not move).
BASE_SIX_MESSAGES: Final[dict[str, str]] = {
    "compress": UNLOCK_MESSAGE,
    "repair": UNLOCK_MESSAGE,
    "linearize": UNLOCK_MESSAGE,
    "text": UNLOCK_MESSAGE,
    "tables": UNLOCK_MESSAGE,
    "rasterize": UNLOCK_MESSAGE,
    "ocr": UNLOCK_MESSAGE,
    "permissions": "a password is required to read this document's permissions",
    "decrypt": "the supplied password did not open this document",
}

#: The verbs that write a decrypted PDF (declare --allow-decrypted-output). ``ocr`` is one.
WRITING: Final[frozenset[str]] = frozenset(
    {"rotate", "extract", "delete", "reorder", "merge", "split", "watermark", "stamp", "ocr",
     "compress", "repair", "linearize", "meta set"}
)  # fmt: skip

#: A preview that plans WITHOUT opening the document keeps predicting 0 for a resolvable
#: but wrong password (README Exit codes, X-89): D2 adds nothing to a dry path.
DRY_OPAQUE: Final[frozenset[str]] = frozenset(
    {"compress", "repair", "linearize", "watermark", "stamp", "meta set", "permissions", "decrypt"}
)  # fmt: skip

#: Multi-input ``OperationResult`` verbs: the batch population (README row 1 of
#: ``## Upgrading to 1.2``). AC4 compares this literal to the derivation.
BATCH_VERBS: Final[tuple[str, ...]] = (
    "compress", "delete", "extract", "ocr", "rasterize", "reorder", "rotate", "tables", "text",
)  # fmt: skip

#: ... that write a plain PDF and so need the opt-in (the others never refuse at 5).
BATCH_WRITING: Final[frozenset[str]] = WRITING & frozenset(BATCH_VERBS)

SHAPES: Final[dict[str, dict[str, Any]]] = {
    "O-RC4": {"user": "", "owner": "o-pw", "R": 3, "aes": False, "metadata": False},
    "O-AES128": {"user": "", "owner": "o-pw", "R": 4},
    "O-AES256": {"user": "", "owner": "o-pw", "R": 6},
    "O-AES256-NOMETA": {"user": "", "owner": "o-pw", "R": 6, "metadata": False},
}
UO: Final[dict[str, Any]] = {"user": "u-pw", "owner": "o-pw", "R": 6}

#: Per-verb tail flags. ``stamp --from`` is added at run time (needs the fixture path).
TAIL: Final[dict[str, tuple[str, ...]]] = {
    "compress": (), "repair": (), "linearize": (), "merge": (), "split": ("--each-page",),
    "delete": ("--pages", "3"), "extract": ("--pages", "1"), "reorder": ("--pages", "3,1"),
    "rotate": ("--pages", "1", "--angle", "90"), "watermark": ("--text", "W"),
    "meta set": ("--title", "t"), "ocr": ("--skip-text-pages",), "text": (), "tables": (),
    "rasterize": (), "info": (), "meta get": (), "permissions": (), "decrypt": (),
    "stamp": (),
}  # fmt: skip
NO_OUTPUT: Final[frozenset[str]] = frozenset({"info", "meta get", "permissions"})
OUT_DIR_ONLY: Final[frozenset[str]] = frozenset({"split", "rasterize"})
TEXTUAL: Final[frozenset[str]] = frozenset({"text", "tables"})


class Fx(NamedTuple):
    root: Path
    dirpath: Path

    def p(self, name: str) -> Path:
        return self.dirpath / name


def _blank(path: Path, encryption: pikepdf.Encryption | None = None) -> None:
    pdf = pikepdf.new()
    for _ in range(3):
        pdf.add_blank_page()
    pdf.save(path, encryption=encryption)


@pytest.fixture(scope="session")
def fx(tmp_path_factory: pytest.TempPathFactory) -> Fx:
    root = tmp_path_factory.mktemp("pdf128")
    d = root / "fx"
    d.mkdir()
    _blank(d / "PLAIN-a.pdf")
    _blank(d / "PLAIN-b.pdf")
    (d / "corrupt.pdf").write_bytes(b"%PDF-1.7\ngarbage\n")
    for name, kw in SHAPES.items():
        _blank(d / f"{name}.pdf", pikepdf.Encryption(**kw))
    _blank(d / "UO-AES256.pdf", pikepdf.Encryption(**UO))
    _blank(d / "UO-AES256-b.pdf", pikepdf.Encryption(**UO))
    for name, secret in (("u", "u-pw"), ("o", "o-pw"), ("x", "x-pw")):
        (d / f"{name}.pw").write_text(secret + "\n")
        (d / f"{name}.pw").chmod(0o600)
    return Fx(root, d)


class Run(NamedTuple):
    rc: int
    env: dict[str, Any]
    stdout: str
    stderr: str
    dest: Path

    @property
    def error(self) -> dict[str, Any]:
        return dict(self.env.get("error", {}))

    @property
    def rows(self) -> list[dict[str, Any]]:
        return [r for r in self.env.get("items", []) if isinstance(r, dict)]

    @property
    def files(self) -> list[str]:
        return sorted(str(f.relative_to(self.dest)) for f in self.dest.rglob("*") if f.is_file())


_CACHE: dict[tuple[Any, ...], Run] = {}


def drive(
    fx: Fx,
    verb: str,
    inputs: tuple[str, ...],
    *,
    pw: str | None = None,
    flag: bool = True,
    dry: bool = False,
    batch: bool = False,
    extra: tuple[str, ...] = (),
) -> Run:
    """One CLI run in a private destination directory, cached by its full description."""
    key = (str(fx.root), verb, inputs, pw, flag, dry, batch, extra)
    if key in _CACHE:
        return _CACHE[key]
    dest = fx.root / "cells" / f"c{len(_CACHE):04d}"
    dest.mkdir(parents=True)
    argv = [*verb.split()]
    if dry:
        argv.append("--dry-run")
    argv += [str(fx.p(name)) for name in inputs]
    argv += list(TAIL[verb])
    if verb == "stamp":
        argv += ["--from", str(fx.p("PLAIN-b.pdf"))]
    argv += list(extra)
    if verb not in NO_OUTPUT:
        if batch or verb in OUT_DIR_ONLY:
            argv += ["--out-dir", str(dest / "d")]
        else:
            argv += ["-O", str(dest / ("out.txt" if verb in TEXTUAL else "out.pdf"))]
    if pw:
        argv += ["--password-file", str(fx.p(pw))]
    if flag and verb in WRITING:
        argv.append(FLAG)
    argv += ["-o", "json"]
    proc = run_cli(verb, *argv[len(verb.split()) :], cwd=dest)
    text = proc.stdout.strip()
    try:
        env = json.loads(text) if text.startswith("{") else {}
    except json.JSONDecodeError:  # pragma: no cover - a failure the assertions then name
        env = {}
    run = Run(proc.returncode, env, proc.stdout, proc.stderr, dest)
    _CACHE[key] = run
    return run


def _ids(names: tuple[str, ...]) -> list[str]:
    return [n.replace(" ", "_") for n in names]


def _needs_engine_skip(verb: str) -> None:
    if verb == ENGINE_BLIND and not HAS_TESSERACT:
        pytest.skip(ENGINE_REASON)


# --------------------------------------------------------------------------- #
# M1 / AC7 -- one answer for owner-only + a non-matching password
# --------------------------------------------------------------------------- #

VERB_X_SHAPE = [(v, s) for v in M1_VERBS for s in SHAPES]
VERB_X_SHAPE_IDS = [f"{v}-{s}".replace(" ", "_") for v, s in VERB_X_SHAPE]


@pytest.mark.parametrize("pi", range(len(VERB_X_SHAPE)), ids=VERB_X_SHAPE_IDS)
def test_ac7_an_owner_only_input_with_a_non_matching_password_exits_6_on_every_verb(
    pi: int, fx: Fx
) -> None:
    verb, shape = VERB_X_SHAPE[pi]
    run = drive(fx, verb, (f"{shape}.pdf",), pw="x.pw")
    assert run.rc == 6, (run.stdout[-300:], run.stderr[-300:])
    if verb == "info":  # info reports per document, not through the error envelope
        assert run.env["documents"][0]["error"]["kind"] == "auth"
        assert run.env["documents"][0]["error"]["code"] == 6
        return
    assert run.error["kind"] == "auth"
    assert run.error["code"] == 6
    expected = BASE_SIX_MESSAGES.get(verb, UNLOCK_MESSAGE)
    assert run.error["message"] == expected
    assert run.env["schema_version"] == 1
    assert [f for f in run.files if f.endswith((".pdf", ".txt", ".png"))] == [], (
        "a refused run wrote"
    )


@pytest.mark.parametrize("pi", range(len(VERB_X_SHAPE)), ids=VERB_X_SHAPE_IDS)
def test_ac9_dry_run_matches_the_literal_and_adds_no_password_check(pi: int, fx: Fx) -> None:
    verb, shape = VERB_X_SHAPE[pi]
    run = drive(fx, verb, (f"{shape}.pdf",), pw="x.pw", dry=True)
    if verb in DRY_OPAQUE:
        assert run.rc == 0, (run.stdout[-300:], run.stderr[-300:])
        assert '"password_verified": false' in run.stdout
    else:
        assert run.rc == 6, (run.stdout[-300:], run.stderr[-300:])
    assert [f for f in run.files if f.endswith((".pdf", ".txt", ".png"))] == [], "a dry run wrote"


def test_ac7_the_populations_are_literal_equal_derived() -> None:
    """The literals above are the live tree's: every PDF-reading verb but ``encrypt``."""
    metavars = operand_metavars()
    derived = set()
    for verb in discover_verbs():
        if verb.is_group:
            continue
        mv = metavars.get(verb.name)
        # `merge` declares its operands without a metavar; `encrypt` owns a second password flag.
        if (mv is not None and mv.startswith("PDF")) or verb.name == "merge":
            if verb.name != "encrypt":
                derived.add(verb.name)
    assert set(M1_VERBS) == derived, sorted(set(M1_VERBS) ^ derived)
    assert BASE_ZERO <= set(M1_VERBS)
    assert set(BASE_SIX_MESSAGES) == set(M1_VERBS) - BASE_ZERO
    writing = {
        v.name
        for v in discover_verbs()
        if not v.is_group and "--allow-decrypted-output" in _help(v.name)
    }
    assert writing == set(WRITING), sorted(writing ^ set(WRITING))


_HELP: dict[str, str] = {}


def _help(verb: str) -> str:
    if verb not in _HELP:
        _HELP[verb] = run_cli(*verb.split(), "--help").stdout
    return _HELP[verb]


# --------------------------------------------------------------------------- #
# M2 / AC8 -- the controls that must not move
# --------------------------------------------------------------------------- #

M2_VERBS: Final[tuple[str, ...]] = tuple(v for v in M1_VERBS if v != ENGINE_BLIND)
NO_ENGINE_WRITING: Final[tuple[str, ...]] = tuple(sorted(WRITING - {ENGINE_BLIND}))

#: (input, password file, expected rc). ``decrypt`` is the one verb whose answer differs
#: (no password on an owner-only input is 6; a plain input is 4): base literals.
CONTROLS: Final[tuple[tuple[str, str | None], ...]] = (
    ("O-AES256.pdf", None),
    ("O-AES256.pdf", "o.pw"),
    ("UO-AES256.pdf", "u.pw"),
    ("UO-AES256.pdf", "o.pw"),
    ("PLAIN-a.pdf", "x.pw"),
)
DECRYPT_CONTROL_RC: Final[dict[tuple[str, str | None], int]] = {
    ("O-AES256.pdf", None): 6,
    ("PLAIN-a.pdf", "x.pw"): 4,
}
CONTROL_X_VERB = [(v, c) for v in M2_VERBS for c in CONTROLS]
CONTROL_X_VERB_IDS = [f"{v}-{c[0][:-4]}-{c[1]}".replace(" ", "_") for v, c in CONTROL_X_VERB]


@pytest.mark.parametrize("ci", range(len(CONTROL_X_VERB)), ids=CONTROL_X_VERB_IDS)
def test_ac8_the_controls_do_not_move(ci: int, fx: Fx) -> None:
    verb, control = CONTROL_X_VERB[ci]
    name, pw = control
    run = drive(fx, verb, (name,), pw=pw)
    expected = DECRYPT_CONTROL_RC.get(control, 0) if verb == "decrypt" else 0
    assert run.rc == expected, (run.stdout[-300:], run.stderr[-300:])


@pytest.mark.parametrize("verb", NO_ENGINE_WRITING)
def test_ac8_without_the_opt_in_a_writing_verb_still_refuses_at_5(verb: str, fx: Fx) -> None:
    run = drive(fx, verb, ("O-AES256.pdf",), flag=False)
    assert run.rc == 5, (run.stdout[-300:], run.stderr[-300:])
    assert run.error["kind"] == "refused"


# --------------------------------------------------------------------------- #
# M3 / AC1 -- a batch with a password failure exits 1, the row keeps 6
# --------------------------------------------------------------------------- #

PROBES: Final[dict[str, tuple[tuple[str, ...], str | None]]] = {
    "B1": (("PLAIN-a.pdf", "O-AES256.pdf", "PLAIN-b.pdf"), "x.pw"),
    "B2": (("PLAIN-a.pdf", "UO-AES256.pdf", "PLAIN-b.pdf"), "x.pw"),
    "B3": (("PLAIN-a.pdf", "UO-AES256.pdf", "PLAIN-b.pdf"), None),
    "B4": (("UO-AES256.pdf", "UO-AES256-b.pdf"), "x.pw"),
    "B5": (("PLAIN-a.pdf", "UO-AES256.pdf", "O-RC4.pdf", "PLAIN-b.pdf"), "u.pw"),
}
#: The input names whose row must fail with 6 per probe.
FAILING: Final[dict[str, tuple[str, ...]]] = {
    "B1": ("O-AES256.pdf",),
    "B2": ("UO-AES256.pdf",),
    "B3": ("UO-AES256.pdf",),
    "B4": ("UO-AES256.pdf", "UO-AES256-b.pdf"),
    "B5": ("O-RC4.pdf",),
}
BATCH_X_PROBE = [(v, p) for v in BATCH_VERBS for p in PROBES]


def _ok_outputs(run: Run) -> set[str]:
    return {
        Path(r["output"]).resolve().as_posix() for r in run.rows if r.get("ok") and r.get("output")
    }


def _disk(run: Run) -> set[str]:
    return {f.resolve().as_posix() for f in run.dest.rglob("*") if f.is_file()}


@pytest.mark.parametrize(
    "bi", range(len(BATCH_X_PROBE)), ids=[f"{v}-{p}" for v, p in BATCH_X_PROBE]
)
def test_ac1_a_batch_with_a_password_failure_exits_1_and_the_row_keeps_6(bi: int, fx: Fx) -> None:
    verb, probe = BATCH_X_PROBE[bi]
    if verb == ENGINE_BLIND and probe != "B4":
        _needs_engine_skip(verb)
    inputs, pw = PROBES[probe]
    run = drive(fx, verb, inputs, pw=pw, batch=True)
    assert run.rc == 1, (run.stdout[-400:], run.stderr[-300:])
    assert run.env["exit_code"] == 1
    assert run.env["schema_version"] == 1
    assert "batch" not in run.env and '"batch"' not in run.stdout  # AC5: not serialized
    failed = {Path(r["input"]).name for r in run.rows if not r["ok"]}
    assert failed == set(FAILING[probe]), failed
    for r in run.rows:
        if not r["ok"]:
            assert r["exit_code"] == 6
    # The filesystem is the oracle: what is on disk is exactly what the ok rows name.
    assert _disk(run) == _ok_outputs(run)
    plain_written = [r for r in run.rows if r["ok"] and r.get("output")]
    if (
        probe == "B4" or verb == "tables"
    ):  # nothing to write (all failed / no tables on a blank page)
        assert verb == "tables" or plain_written == []
    else:
        assert len(plain_written) >= 2, "the siblings were not written"


@pytest.mark.parametrize("vi", range(len(BATCH_VERBS)), ids=_ids(BATCH_VERBS))
def test_ac1_the_dry_run_of_a_batch_predicts_the_same_run_code(vi: int, fx: Fx) -> None:
    """B3 (no password): every verb predicts 1; B2/B4/B5 (a wrong password): the verbs whose
    preview opens the document predict 1, ``compress``'s opaque preview keeps 0 (carve-out)."""
    verb = BATCH_VERBS[vi]
    if verb == ENGINE_BLIND:
        _needs_engine_skip(verb)
    for probe in ("B2", "B3", "B4", "B5"):
        inputs, pw = PROBES[probe]
        run = drive(fx, verb, inputs, pw=pw, batch=True, dry=True)
        expected = 0 if (verb in DRY_OPAQUE and pw is not None) else 1
        assert run.rc == expected, (probe, run.rc, run.stdout[-300:])
        assert run.env["exit_code"] == expected
        assert [f for f in run.files if f.endswith((".pdf", ".txt", ".png"))] == []


def test_ac1_the_c197515a2e_repro_verbatim_shape(fx: Fx) -> None:
    """``compress a-plain b-user c-owneronly d-plain --password-file --out-dir`` -> rc 1, 3 of 4."""
    run = drive(
        fx,
        "compress",
        ("PLAIN-a.pdf", "UO-AES256.pdf", "O-RC4.pdf", "PLAIN-b.pdf"),
        pw="u.pw",
        batch=True,
    )
    assert run.rc == 1 and run.env["exit_code"] == 1
    rows = {Path(r["input"]).name: r for r in run.rows}
    assert rows["O-RC4.pdf"]["ok"] is False and rows["O-RC4.pdf"]["exit_code"] == 6
    assert all(rows[n]["ok"] for n in ("PLAIN-a.pdf", "UO-AES256.pdf", "PLAIN-b.pdf"))
    assert len(run.files) == 3
    # ... and the same batch under `rotate` gives the same answer (one answer, E2/E4).
    other = drive(
        fx,
        "rotate",
        ("PLAIN-a.pdf", "UO-AES256.pdf", "O-RC4.pdf", "PLAIN-b.pdf"),
        pw="u.pw",
        batch=True,
    )
    assert other.rc == 1 and len(other.files) == 3


# --------------------------------------------------------------------------- #
# M4 / AC2 -- a single input keeps its own 6 and the error envelope
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vi", range(len(BATCH_VERBS)), ids=_ids(BATCH_VERBS))
def test_ac2_a_single_input_keeps_6_and_the_error_envelope(vi: int, fx: Fx) -> None:
    verb = BATCH_VERBS[vi]
    run = drive(fx, verb, ("UO-AES256.pdf",), pw="x.pw")
    assert run.rc == 6, (run.stdout[-300:], run.stderr[-300:])
    assert set(run.env) == {"schema_version", "error"}
    assert run.env["schema_version"] == 1
    assert set(run.error) == {"code", "kind", "message", "path"}
    assert run.error["code"] == 6 and run.error["kind"] == "auth"


# --------------------------------------------------------------------------- #
# M5 / AC3 -- run-scoped codes survive in a batch, in both tiers
# --------------------------------------------------------------------------- #

#: (verb, selection tail, real rc, real error kind, dry rc). Re-measured at 0be9f24.
RUN_SCOPED: Final[dict[str, tuple[tuple[str, ...], int, str, int]]] = {
    "delete": (("--pages", "all"), 5, "refused", 5),
    "extract": (("--pages", "all,!all"), 4, "no_input", 4),
    "reorder": (("--pages", "all,!all"), 4, "no_input", 4),
    "rotate": (("--pages", "all,!all"), 4, "no_input", 4),
}


@pytest.mark.parametrize("verb", sorted(RUN_SCOPED))
def test_ac3_run_scoped_failures_keep_their_code_in_both_tiers(verb: str, fx: Fx) -> None:
    sel, real_rc, kind, dry_rc = RUN_SCOPED[verb]
    ins = ("PLAIN-a.pdf", "PLAIN-b.pdf")
    real = drive(fx, verb, ins, batch=True, extra=sel)
    dry = drive(fx, verb, ins, batch=True, extra=sel, dry=True)
    assert real.rc == real_rc and real.error["kind"] == kind, (
        real.stdout[-300:],
        real.stderr[-300:],
    )
    assert dry.rc == dry_rc, (dry.stdout[-300:], dry.stderr[-300:])
    assert dry.env["exit_code"] == dry_rc  # the dry rows carry FAIL5/FAIL4: NOT collapsed to 1


@pytest.mark.parametrize("verb", ("compress", "delete", "extract", "reorder", "rotate"))
def test_ac3_a_destination_collision_stays_5(verb: str, fx: Fx) -> None:
    run = drive(fx, verb, ("PLAIN-a.pdf", "O-AES256.pdf", "O-AES256.pdf"), pw="x.pw", batch=True)
    assert run.rc == 5 and run.error["kind"] == "refused"


@pytest.mark.parametrize("verb", tuple(sorted(BATCH_WRITING - {ENGINE_BLIND})))
def test_ac3_without_the_opt_in_a_batch_with_an_encrypted_input_is_refused_whole(
    verb: str, fx: Fx
) -> None:
    inputs, pw = PROBES["B5"]
    run = drive(fx, verb, inputs, pw=pw, flag=False, batch=True)
    assert run.rc == 5 and run.error["kind"] == "refused"
    assert run.files == []


@pytest.mark.parametrize("verb", tuple(v for v in BATCH_VERBS if v != ENGINE_BLIND))
def test_ac3_a_malformed_input_in_a_batch_is_still_1(verb: str, fx: Fx) -> None:
    run = drive(fx, verb, ("PLAIN-a.pdf", "corrupt.pdf", "PLAIN-b.pdf"), batch=True)
    assert run.rc == 1 and run.env["exit_code"] == 1
    assert [r["exit_code"] for r in run.rows if not r["ok"]] == [1]


# --------------------------------------------------------------------------- #
# M6 -- info's existing rule is unchanged
# --------------------------------------------------------------------------- #


def test_info_batch_rule_is_unchanged(fx: Fx) -> None:
    run = drive(fx, "info", ("PLAIN-a.pdf", "UO-AES256.pdf"), pw="x.pw")
    assert run.rc == 1
    codes = {Path(d["path"]).name: d.get("error", {}).get("code") for d in run.env["documents"]}
    assert codes["UO-AES256.pdf"] == 6
    single = drive(fx, "info", ("UO-AES256.pdf",), pw="x.pw")
    assert single.rc == 6


# --------------------------------------------------------------------------- #
# M7 / AC9 -- the read and secret budget (in-process)
# --------------------------------------------------------------------------- #


def _count(
    fx: Fx, argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> tuple[int, int, int]:
    """(rc, PasswordSource reads, reads of the operand's bytes) for one in-process run."""
    import pdf_tooling.cli.main as main_module
    import pdf_tooling.cli.password as password_module
    from pdf_tooling.cli.common import reset_error_format

    secret_reads: list[int] = []
    operand_reads: list[int] = []
    original = password_module._read_file
    original_read_bytes = pathlib.Path.read_bytes

    def counting(*args: Any, **kwargs: Any) -> Any:
        secret_reads.append(1)
        return original(*args, **kwargs)

    def counting_read_bytes(self: Path, *args: Any, **kwargs: Any) -> bytes:
        if self.name == "O-AES256.pdf":
            operand_reads.append(1)
        return original_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(password_module, "_read_file", counting)
    monkeypatch.setattr(pathlib.Path, "read_bytes", counting_read_bytes)
    monkeypatch.setattr(sys, "argv", ["pdftooling", *argv])
    reset_error_format()
    with pytest.raises(SystemExit) as excinfo:
        main_module.main()
    capsys.readouterr()
    return int(excinfo.value.code or 0), len(secret_reads), len(operand_reads)


#: (cell, rc, PasswordSource.read count, operand read_bytes count). The BASE column is
#: the same harness at 0be9f24, 2026-10-08, before any edit: rotate-real (0, 1, 3),
#: rotate-dry (0, 1, 2), compress-real (6, 1, 3), compress-dry (0, 0, 1). The two dry
#: cells and the secret reads are UNCHANGED (AC9: D2 adds no read to a dry path). The two
#: real cells now fail inside ``for_source`` and so skip the later re-read: 3 -> 2.
M7_LITERAL: Final[dict[str, tuple[int, int, int]]] = {
    "rotate-real": (6, 1, 2),
    "rotate-dry": (6, 1, 2),
    "compress-real": (6, 1, 2),
    "compress-dry": (0, 0, 1),
}


@pytest.mark.parametrize("cell", sorted(M7_LITERAL))
def test_ac9_the_secret_and_operand_read_budget(
    cell: str,
    fx: Fx,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verb, tier = cell.split("-")
    operand, pwfile = str(fx.p("O-AES256.pdf")), str(fx.p("x.pw"))
    argv = [verb, *(["--dry-run"] if tier == "dry" else []), operand]
    argv += ["--pages", "1", "--angle", "90"] if verb == "rotate" else []
    argv += ["-O", str(tmp_path / "o.pdf"), "--password-file", pwfile, FLAG, "-o", "json"]
    assert _count(fx, argv, monkeypatch, capsys) == M7_LITERAL[cell]


# --------------------------------------------------------------------------- #
# AC4 -- the batch population is derived and complete (AST)
# --------------------------------------------------------------------------- #


def _calls_named(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and (
            (isinstance(n.func, ast.Name) and n.func.id == name)
            or (isinstance(n.func, ast.Attribute) and n.func.attr == name)
        )
    ]


def _has_ledger_in_scope(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if any(a.arg == "ledger" for a in (*fn.args.args, *fn.args.kwonlyargs)):
        return True
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
            f = n.value.func
            if isinstance(f, ast.Name) and f.id == "BatchLedger":
                return True
    return False


def batch_site_problems(source: str, label: str) -> list[str]:
    """Every ``OperationResult(`` with a ledger in scope that lacks ``batch=ledger.is_batch``."""
    tree = ast.parse(source)
    problems: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or not _has_ledger_in_scope(
            fn
        ):
            continue
        for call in _calls_named(fn, "OperationResult"):
            kw = {k.arg: k.value for k in call.keywords}
            value = kw.get("batch")
            if value is None or ast.dump(value) != ast.dump(
                ast.parse("ledger.is_batch", mode="eval").body
            ):
                problems.append(f"{label}:{call.lineno}")
    return sorted(set(problems))


def _ops_modules(predicate: str) -> set[str]:
    found: set[str] = set()
    for path in sorted(OPS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text())
        if predicate == "ledger" and _calls_named(tree, "BatchLedger"):
            found.add(path.stem)
        if predicate == "batch-kw" and any(
            any(k.arg == "batch" for k in c.keywords) for c in _calls_named(tree, "OperationResult")
        ):
            found.add(path.stem)
    return found


def test_ac4_every_operation_result_with_a_ledger_in_scope_passes_batch() -> None:
    problems: list[str] = []
    for path in sorted(OPS_DIR.glob("*.py")):
        problems += batch_site_problems(path.read_text(), f"{path.name}")
    assert problems == [], f"OperationResult(...) without batch=ledger.is_batch: {problems}"


def test_ac4_the_modules_that_pass_batch_are_the_modules_that_build_a_ledger() -> None:
    assert _ops_modules("batch-kw") == _ops_modules("ledger") != set()


def test_ac4_the_batch_verbs_are_the_variadic_pdf_verbs_minus_info() -> None:
    metavars = operand_metavars()
    derived = {
        v.name
        for v in discover_verbs()
        if not v.is_group and metavars.get(v.name) == "PDF..." and v.name != "info"
    }
    assert set(BATCH_VERBS) == derived, sorted(set(BATCH_VERBS) ^ derived)
    modules = _ops_modules("ledger")
    for verb in discover_verbs():
        if verb.name in BATCH_VERBS:
            assert verb.module is not None
            source = (
                Path(REPO_ROOT / "src" / Path(*verb.module.split(".")))
                .with_suffix(".py")
                .read_text()
            )
            assert any(f"pdf_tooling.ops.{m}" in source for m in modules), verb.name


def test_ac4_red_a_construction_without_batch_is_named_by_line() -> None:
    """RED pin: strip ``batch=`` from one ``textract`` construction -> the scan names that line."""
    text = (OPS_DIR / "textract.py").read_text().split("\n")
    target = next(i for i, line in enumerate(text) if line.strip() == "batch=ledger.is_batch,")
    del text[target]
    problems = batch_site_problems("\n".join(text), "textract.py")
    assert len(problems) == 1 and problems[0].startswith("textract.py:"), problems


# --------------------------------------------------------------------------- #
# AC5 -- the envelope does not change shape
# --------------------------------------------------------------------------- #


def test_ac5_to_dict_does_not_emit_batch() -> None:
    from pdf_tooling.models import ItemResult, OperationResult

    row = ItemResult("a", None, False, 6, "m", None, None, 0)
    for batch in (False, True):
        payload = OperationResult(1, "v", False, (row,), (), 0, batch=batch).to_dict()
        assert list(payload) == [
            "schema_version", "verb", "dry_run", "items", "warnings", "duration_ms", "exit_code",
        ]  # fmt: skip
    assert OperationResult(1, "v", False, (row,), (), 0, batch=True).to_dict()["exit_code"] == 1
    assert OperationResult(1, "v", False, (row,), (), 0).to_dict()["exit_code"] == 6


def test_ac5_the_batch_field_is_last_and_defaulted() -> None:
    import dataclasses

    from pdf_tooling.models import OperationResult

    fields = dataclasses.fields(OperationResult)
    assert fields[-1].name == "batch" and fields[-1].default is False


# --------------------------------------------------------------------------- #
# AC6 -- _ITEM_SCOPED_CODES is the item-scoped classes' codes
# --------------------------------------------------------------------------- #


def _codes_of(classes: tuple[type, ...]) -> set[int]:
    return {cls.exit_code for cls in classes}  # type: ignore[attr-defined]


def test_ac6_the_collapsed_codes_are_the_item_scoped_classes_codes() -> None:
    from pdf_tooling.models import _ITEM_SCOPED_CODES
    from pdf_tooling.ops.batch import ITEM_SCOPED_ERRORS

    assert _codes_of(ITEM_SCOPED_ERRORS) == set(_ITEM_SCOPED_CODES) == {1, 6}


def test_ac6_red_a_widened_item_scoped_tuple_breaks_the_equality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pdf_tooling.errors import NoInputError
    from pdf_tooling.models import _ITEM_SCOPED_CODES
    from pdf_tooling.ops import batch

    monkeypatch.setattr(batch, "ITEM_SCOPED_ERRORS", (*batch.ITEM_SCOPED_ERRORS, NoInputError))
    assert _codes_of(batch.ITEM_SCOPED_ERRORS) != set(_ITEM_SCOPED_CODES)


def test_ac6_models_imports_nothing_from_ops() -> None:
    tree = ast.parse((REPO_ROOT / "src" / "pdf_tooling" / "models.py").read_text())
    imported = [
        (n.module if isinstance(n, ast.ImportFrom) else a.name)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [None])
    ]
    assert not [m for m in imported if m and m.startswith("pdf_tooling.ops")], imported


@pytest.mark.parametrize(
    ("codes", "batch", "expected"),
    [
        ((6,), False, 6),
        ((6,), True, 1),
        ((1,), True, 1),
        ((6, 1), True, 1),
        ((5, 6), True, 5),  # a run-scoped dry FAIL5 is NOT collapsed
        ((4,), True, 4),
        ((), True, 0),
        ((6, 5), False, 6),
    ],
)
def test_the_exit_code_property_collapses_only_item_scoped_codes_in_a_batch(
    codes: tuple[int, ...], batch: bool, expected: int
) -> None:
    from pdf_tooling.models import ItemResult, OperationResult

    rows = tuple(
        ItemResult(f"i{n}", None, False, c, "m", None, None, 0) for n, c in enumerate(codes)
    )
    assert OperationResult(1, "v", False, rows, (), 0, batch=batch).exit_code == expected


# --------------------------------------------------------------------------- #
# AC10 -- README agrees
# --------------------------------------------------------------------------- #


def _readme() -> str:
    return (REPO_ROOT / "README.md").read_text()


def _section(text: str, heading: str) -> str:
    assert text.count(heading) == 1, heading
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


# `## Upgrading to 1.2` is shared with PDF-127, whose row is about `meta set --clear-all
# --in-place`; this spec's registry is the rows that are NOT that one.
_OTHER_SPEC_ROW_PREFIXES = ("| `meta set --clear-all --in-place`",)


def _rows_of(section: str) -> list[str]:
    return [
        ln
        for ln in section.splitlines()
        if ln.startswith("|")
        and not ln.startswith("|---")
        and not ln.startswith(_OTHER_SPEC_ROW_PREFIXES)
    ][1:]


def _ticks(text: str) -> list[str]:
    return re.findall(r"`([^`]+)`", text)


def row2_verbs(readme: str) -> set[str]:
    row = _rows_of(_section(readme, "## Upgrading to 1.2"))[1]
    first = row.split("|")[1]
    zero = first.split("exited `0` on", 1)[1].split("and `6` on the others", 1)[0]
    return {t for t in _ticks(zero) if t not in {"--allow-decrypted-output", "0"}}


def row1_verbs(readme: str) -> set[str]:
    row = _rows_of(_section(readme, "## Upgrading to 1.2"))[0]
    paren = row.split("|")[1].split("(", 1)[1].split(")", 1)[0]
    return set(_ticks(paren))


def test_ac10_the_1_2_section_carries_the_three_rows() -> None:
    rows = _rows_of(_section(_readme(), "## Upgrading to 1.2"))
    assert len(rows) == 3, rows


def test_ac10_row_2_lists_exactly_the_verbs_that_exited_0() -> None:
    assert row2_verbs(_readme()) == set(BASE_ZERO)


def test_ac10_row_1_lists_the_batch_verbs_that_take_a_password_file() -> None:
    assert row1_verbs(_readme()) == set(BATCH_VERBS)


def test_ac10_red_removing_info_from_row_2_fails() -> None:
    mutated = _readme().replace(
        "`info` and `meta get`, and `6` on the others", "`meta get`, and `6` on the others", 1
    )
    assert mutated != _readme()
    assert row2_verbs(mutated) != set(BASE_ZERO)


def test_ac10_the_password_file_section_says_a_supplied_password_is_checked() -> None:
    body = _readme()
    section = body.split(
        "### `--password-file` is global: honoured or refused, never silently ignored", 1
    )[1]
    section = section.split("\n### ", 1)[0].split("\n## ", 1)[0]
    assert "A supplied password is checked even when the document would open without one" in section


def test_ac10_the_published_batch_sentence_is_unchanged_and_extended() -> None:
    text = _readme()
    published = (
        "A failing input is recorded, the run continues, and the run exits `1` at the end; "
        "each row carries its own `ok`, `exit_code` and `message`."
    )
    assert text.count(published) == 1
    assert "its row carries `exit_code` `6`, and the run still exits `1`" in text


def test_ac10_the_write_does_not_carry_sentence_ends_with_the_supplied_password_clause() -> None:
    assert (
        "an owner-only input needs no password for any of this; "
        "a password that is supplied must open it." in _readme()
    )
