"""PDF-159 -- ``--dry-run`` predicts malformed-input failures (B-501).

Ledger rows ``60ae484d91`` and ``48e79e19ac``. A script that previewed ``compress``,
``linearize``, ``watermark``, ``stamp`` or ``meta set`` on a damaged PDF was told
``planned: <verb>`` with rc 0, and the real run then exited 1; ``stamp --from`` with an
encrypted or damaged operand had the same defect. The fix is one seam
(``predict_password_refusal(..., engine_probe=...)``): the verb's own engine reads the
bytes in memory with no secret. Operator ruling ``OR-87`` confirms that predicting an
error the real run already prints is the README contract, not a new surface.

A supplied password is still never tested (``password_verified: false``): an encrypted
operand reached with a resolvable password is never probed.

Every expected cell is a LITERAL ``(dry, real)`` pair measured at the base. Every
assertion is on the product's own output (rc, envelopes), never an engine's wording.
Fixtures are built here; nothing depends on another test module.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

import pikepdf
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import run_cli  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ADO: Final[str] = "--allow-decrypted-output"

VERBS: Final[tuple[str, ...]] = ("compress", "linearize", "watermark", "stamp", "meta set")
EXTRA: Final[dict[str, list[str]]] = {
    "compress": [],
    "linearize": [],
    "repair": [],
    "watermark": ["--text", "W"],
    "stamp": ["--from", "stampsrc.pdf"],
    "meta set": ["--title", "T"],
}

# cell -> (operand, extra args, a password-file name or None). "G"/"B" = good/bad.
CELLS: Final[dict[str, tuple[str, list[str]]]] = {
    "plain": ("plain.pdf", []),
    "plain+pw": ("plain.pdf", ["@G"]),
    "mal": ("malformed.pdf", []),
    "mal+pw": ("malformed.pdf", ["@G"]),
    "mal+pw+ado": ("malformed.pdf", ["@G", ADO]),
    "trunc": ("trunc.pdf", []),
    "noeof": ("noeof_tail.pdf", []),
    "garbage": ("garbage.pdf", []),
    "badxref": ("badxref.pdf", []),
    "nopages": ("nopages.pdf", []),
    "enc+ado": ("enc.pdf", [ADO]),
    "enc+pw+ado": ("enc.pdf", ["@G", ADO]),
    "enc+bad+ado": ("enc.pdf", ["@B", ADO]),
    "enc-gate": ("enc.pdf", []),
    "enc+pw-gate": ("enc.pdf", ["@G"]),
    "encown+ado": ("enc_owner.pdf", [ADO]),
    "encown+bad+ado": ("enc_owner.pdf", ["@B", ADO]),
    "enctrunc+pw+ado": ("enc_trunc.pdf", ["@G", ADO]),
    "enctrunc+ado": ("enc_trunc.pdf", [ADO]),
}

_Z = (0, 0)
_E = (1, 1)
#: After-fix (dry, real) rc per cell; verbs in VERBS order. Rows 13/17 are the
#: documented password-correctness carve-out (dry 0, real 6).
AC1_AFTER: Final[dict[str, tuple[tuple[int, int], ...]]] = {
    "plain": (_Z,) * 5,
    "plain+pw": (_Z,) * 5,
    "mal": (_E,) * 5,
    "mal+pw": (_E,) * 5,
    "mal+pw+ado": (_E,) * 5,
    "trunc": (_E,) * 5,
    "noeof": (_Z, _Z, _E, _E, _E),
    "garbage": (_E,) * 5,
    "badxref": (_Z,) * 5,
    "nopages": (_E,) * 5,
    "enc+ado": ((6, 6),) * 5,
    "enc+pw+ado": (_Z,) * 5,
    "enc+bad+ado": ((0, 6),) * 5,
    "enc-gate": ((5, 5),) * 5,
    "enc+pw-gate": ((5, 5),) * 5,
    "encown+ado": (_Z,) * 5,
    "encown+bad+ado": ((0, 6),) * 5,
    "enctrunc+pw+ado": (_E,) * 5,
    "enctrunc+ado": (_E,) * 5,
}
#: The cells that were dry 0 / real 1 at base and become (1, 1): the AC4 population.
AC4_CELLS: Final[tuple[str, ...]] = (
    "mal",
    "mal+pw",
    "mal+pw+ado",
    "trunc",
    "enctrunc+pw+ado",
    "enctrunc+ado",
)
#: `repair` recovers or fails identically in both tiers (E5); frozen.
REPAIR_AFTER: Final[dict[str, tuple[int, int]]] = {
    **dict.fromkeys(CELLS, _Z),
    "garbage": _E,
    "nopages": _E,
    "enc+ado": (6, 6),
    "enc+bad+ado": (0, 6),
    "enc-gate": (5, 5),
    "enc+pw-gate": (5, 5),
    "encown+bad+ado": (0, 6),
}

# stamp --from cells: name -> (argv after `stamp`, after (dry, real)).
FROM_CELLS: Final[dict[str, tuple[list[str], tuple[int, int]]]] = {
    "from-enc+ado": (["plain.pdf", "--from", "enc.pdf", ADO], (6, 6)),
    "from-enc+pw+ado": (["plain.pdf", "--from", "enc.pdf", "@G", ADO], (0, 0)),
    "from-enc+bad+ado": (["plain.pdf", "--from", "enc.pdf", "@B", ADO], (0, 6)),
    "from-enc-gate": (["plain.pdf", "--from", "enc.pdf"], (5, 5)),
    "from-enc+pw-gate": (["plain.pdf", "--from", "enc.pdf", "@G"], (5, 5)),
    "from-mal": (["plain.pdf", "--from", "malformed.pdf"], (1, 1)),
    "from-trunc": (["plain.pdf", "--from", "trunc.pdf"], (1, 1)),
    "from-garbage": (["plain.pdf", "--from", "garbage.pdf"], (1, 1)),
    "from-badxref": (["plain.pdf", "--from", "badxref.pdf"], (0, 0)),
    "from-encown+ado": (["plain.pdf", "--from", "enc_owner.pdf", ADO], (0, 0)),
    "from-encown+bad+ado": (["plain.pdf", "--from", "enc_owner.pdf", "@B", ADO], (0, 6)),
    "from-enctrunc+pw+ado": (["plain.pdf", "--from", "enc_trunc.pdf", "@G", ADO], (1, 1)),
    "from-noeof": (["plain.pdf", "--from", "noeof_tail.pdf"], (1, 1)),
    "from-nopages": (["plain.pdf", "--from", "nopages.pdf"], (1, 1)),
    "mal+from-enc+ado": (["malformed.pdf", "--from", "enc.pdf", ADO], (6, 6)),
    "mal+from-enc+pw+ado": (["malformed.pdf", "--from", "enc.pdf", "@G", ADO], (1, 1)),
    "mal+from-mal": (["malformed.pdf", "--from", "malformed.pdf"], (1, 1)),
    "enc+from-mal+pw+ado": (["enc.pdf", "--from", "malformed.pdf", "@G", ADO], (1, 1)),
    "enc+from-mal+ado": (["enc.pdf", "--from", "malformed.pdf", ADO], (1, 1)),
}
#: `--from` cells whose failure names `--from` in both tiers.
FROM_NAMED: Final[tuple[str, ...]] = (
    "from-mal",
    "from-trunc",
    "from-garbage",
    "from-enctrunc+pw+ado",
    "from-noeof",
    "from-nopages",
    "mal+from-mal",
    "enc+from-mal+pw+ado",
    "enc+from-mal+ado",
)
#: The two rc-only rows: the seam's credential-free parse fails first, so the inner
#: wording differs (PDF-165 territory), while rc and the `--from` prefix agree.
FROM_RC_ONLY: Final[tuple[str, ...]] = ("from-garbage", "from-nopages")

PAGE_CELLS: Final[dict[str, tuple[str, list[str]]]] = {
    "wm-abc": ("watermark", ["plain.pdf", "--text", "W", "--pages", "abc"]),
    "wm-9": ("watermark", ["plain.pdf", "--text", "W", "--pages", "9"]),
    "wm-0": ("watermark", ["plain.pdf", "--text", "W", "--pages", "0"]),
    "st-abc": ("stamp", ["plain.pdf", "--from", "stampsrc.pdf", "--pages", "abc"]),
    "st-9": ("stamp", ["plain.pdf", "--from", "stampsrc.pdf", "--pages", "9"]),
    "st-fp9": ("stamp", ["plain.pdf", "--from", "stampsrc.pdf", "--from-page", "9"]),
}

BATCH_ARMS: Final[
    dict[str, tuple[list[str], list[str], tuple[int, int], list[int] | None, list[int] | None]]
] = {
    # name: (operands, extra, (dry rc, real rc), dry rows, real rows)
    "nopw-noado": (["plain.pdf", "malformed.pdf", "enc.pdf"], [], (5, 5), None, None),
    "nopw-ado": (["plain.pdf", "malformed.pdf", "enc.pdf"], [ADO], (1, 1), [0, 1, 6], [0, 1, 6]),
    "pw-noado": (["plain.pdf", "malformed.pdf", "enc.pdf"], ["@G"], (5, 5), None, None),
    "pw-ado": (
        ["plain.pdf", "malformed.pdf", "enc.pdf"],
        ["@G", ADO],
        (1, 1),
        [0, 1, 0],
        [0, 1, 0],
    ),
    "bad-ado": (
        ["plain.pdf", "malformed.pdf", "enc.pdf"],
        ["@B", ADO],
        (1, 1),
        [0, 1, 0],
        [0, 1, 6],
    ),
    "ctl-garbage": (["plain.pdf", "garbage.pdf"], [], (1, 1), None, None),
    "ctl-malformed": (["plain.pdf", "malformed.pdf"], [], (1, 1), None, None),
}

_ENV_DROP = {"PDF_TOOLING_PASSWORD", "PDF_TOOLING_OWNER_PASSWORD"}


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _ENV_DROP}


def _make_plain(path: Path) -> None:
    pdf = pikepdf.new()
    font = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica
        )
    )
    for index in range(3):
        pdf.add_blank_page(page_size=(612, 792))
        page = pdf.pages[-1]
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.Contents = pdf.make_stream(
            f"BT /F1 24 Tf 72 700 Td (Page {index + 1} hello world) Tj ET".encode()
        )
    pdf.save(path)
    pdf.close()


@pytest.fixture(scope="module")
def fx(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("pdf159") / "fx"
    root.mkdir()
    _make_plain(root / "plain.pdf")
    _make_plain(root / "stampsrc.pdf")
    shutil.copy(REPO_ROOT / "testdata" / "malformed.pdf", root / "malformed.pdf")
    for name, value in (
        ("pw-good.txt", "u\n"),
        ("pw-bad.txt", "nope\n"),
        ("U", "u\n"),
        ("O", "o\n"),
    ):
        (root / name).write_text(value)
        (root / name).chmod(0o600)
    data = (root / "plain.pdf").read_bytes()
    (root / "trunc.pdf").write_bytes(data[: int(len(data) * 0.6)])
    rng = random.Random(1234)
    (root / "garbage.pdf").write_bytes(
        b"%PDF-1.7\n" + bytes(rng.getrandbits(8) for _ in range(2048))
    )
    last = list(re.finditer(rb"startxref\s+(\d+)", data))[-1]
    (root / "badxref.pdf").write_bytes(data[: last.start(1)] + b"99999" + data[last.end(1) :])
    stripped = data.rstrip()
    (root / "noeof_tail.pdf").write_bytes(
        stripped[:-6] if stripped.endswith(b"%%EOF") else stripped
    )
    pdf = pikepdf.open(root / "plain.pdf")
    del pdf.Root["/Pages"]
    pdf.save(root / "nopages.pdf")
    pdf.close()
    run_cli(
        "encrypt",
        "plain.pdf",
        "-O",
        "enc.pdf",
        "--user-password-file",
        "U",
        "--owner-password-file",
        "O",
        cwd=root,
        env=_env(),
    )
    run_cli(
        "encrypt",
        "plain.pdf",
        "-O",
        "enc_owner.pdf",
        "--owner-password-file",
        "O",
        cwd=root,
        env=_env(),
    )
    enc = (root / "enc.pdf").read_bytes()
    (root / "enc_trunc.pdf").write_bytes(enc[: int(len(enc) * 0.6)])
    return root


_CACHE: dict[tuple[str, tuple[str, ...], bool], tuple[int, str, str, str]] = {}
_COUNTER = [0]


def _masked(stdout: str) -> str:
    def strip(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: strip(v) for k, v in obj.items() if k != "duration_ms"}
        if isinstance(obj, list):
            return [strip(v) for v in obj]
        return obj

    try:
        return json.dumps(strip(json.loads(stdout)), sort_keys=True)
    except ValueError:
        return stdout


def _drive(fx: Path, verb: str, tail: list[str], *, dry: bool) -> tuple[int, str, str, str]:
    """(rc, masked stdout, stderr, raw stdout) in a fresh copy of the fixture directory."""
    resolved = _expand_password_flags(tail, fx)
    key = (verb, tuple(resolved), dry)
    if key in _CACHE:
        return _CACHE[key]
    _COUNTER[0] += 1
    work = fx.parent / f"cell{_COUNTER[0]}"
    shutil.copytree(fx, work)
    try:
        result = run_cli(
            verb, *(["--dry-run"] if dry else []), "-o", "json", *resolved, cwd=work, env=_env()
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out = (result.returncode, _masked(result.stdout), result.stderr, result.stdout)
    _CACHE[key] = out
    return out


def _expand_password_flags(tail: list[str], fx: Path) -> list[str]:
    out: list[str] = []
    for arg in tail:
        if arg == "@G":
            out += ["--password-file", str(fx / "pw-good.txt")]
        elif arg == "@B":
            out += ["--password-file", str(fx / "pw-bad.txt")]
        else:
            out.append(arg)
    return out


def _single(fx: Path, verb: str, cell: str, *, dry: bool) -> tuple[int, str, str, str]:
    operand, flags = CELLS[cell]
    return _drive(fx, verb, [operand, *EXTRA[verb], *flags, "-O", "o.pdf"], dry=dry)


def _need(module: Any, name: str) -> Any:
    """A PDF-159 symbol, looked up lazily so its absence is an assertion, not a load failure."""
    found = getattr(module, name, None)
    assert found is not None, f"{name} is missing (PDF-159 D2)"
    return found


def _json(raw: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    return parsed


GRID = [(verb, cell) for verb in VERBS for cell in CELLS]


@pytest.mark.parametrize(("verb", "cell"), GRID, ids=[f"{v}-{c}" for v, c in GRID])
def test_ac1_single_input_dry_real_matrix(fx: Path, verb: str, cell: str) -> None:
    expected = AC1_AFTER[cell][VERBS.index(verb)]
    dry = _single(fx, verb, cell, dry=True)
    real = _single(fx, verb, cell, dry=False)
    assert (dry[0], real[0]) == expected
    if dry[0] == 0:
        item = _json(dry[3])["items"][0]
        assert item["ok"] is True
        message_prefix = item["message"]
        assert message_prefix == f"planned: {verb}"
        if real[0] == 6:
            assert item["detail"]["password_verified"] is False


@pytest.mark.parametrize("verb", VERBS)
def test_ac2_noeof_tail_follows_each_verbs_engine(fx: Path, verb: str) -> None:
    expected = {"compress": _Z, "linearize": _Z, "watermark": _E, "stamp": _E, "meta set": _E}[verb]
    dry = _single(fx, verb, "noeof", dry=True)
    real = _single(fx, verb, "noeof", dry=False)
    assert (dry[0], real[0]) == expected


@pytest.mark.parametrize("verb", VERBS)
@pytest.mark.parametrize("cell", ["enc+bad+ado", "encown+bad+ado"])
def test_ac3_wrong_password_is_still_not_tested(fx: Path, verb: str, cell: str) -> None:
    dry = _single(fx, verb, cell, dry=True)
    real = _single(fx, verb, cell, dry=False)
    assert (dry[0], real[0]) == (0, 6)
    item = _json(dry[3])["items"][0]
    assert item["ok"] is True
    message_prefix = item["message"]
    assert message_prefix == f"planned: {verb}"
    assert item["detail"]["password_verified"] is False


AC4_GRID = [(v, c) for v in VERBS for c in AC4_CELLS] + [
    (v, "noeof") for v in ("watermark", "stamp", "meta set")
]


@pytest.mark.parametrize(("verb", "cell"), AC4_GRID, ids=[f"{v}-{c}" for v, c in AC4_GRID])
def test_ac4_predicted_failure_is_the_real_error(fx: Path, verb: str, cell: str) -> None:
    dry = _single(fx, verb, cell, dry=True)
    real = _single(fx, verb, cell, dry=False)
    assert (dry[0], real[0]) == _E
    assert dry[1] == real[1]
    assert _json(dry[3])["error"]["kind"] == "failure"
    assert set(dry[2].splitlines()) <= set(real[2].splitlines())


@pytest.mark.parametrize("cell", sorted(FROM_CELLS))
def test_ac5_stamp_from_dry_real_matrix(fx: Path, cell: str) -> None:
    tail, expected = FROM_CELLS[cell]
    argv = [*tail, "-O", "o.pdf"]
    dry = _drive(fx, "stamp", argv, dry=True)
    real = _drive(fx, "stamp", argv, dry=False)
    assert (dry[0], real[0]) == expected
    if expected == (1, 1) and cell not in FROM_RC_ONLY:
        assert dry[1] == real[1]
    if cell in FROM_NAMED:
        for tier in (dry, real):
            message_prefix = _json(tier[3])["error"]["message"]
            assert message_prefix.startswith("--from is malformed (")
    if expected == (6, 6):
        item = _json(dry[3])["items"][0]
        assert item["exit_code"] == 6
        message_prefix = item["message"]
        assert message_prefix.startswith("a password is required to open --from (enc.pdf); ")
    if expected == (0, 6):
        assert _json(dry[3])["items"][0]["detail"]["password_verified"] is False


#: sha256 of the masked dry stdout (duration_ms stripped, the fixture directory replaced by
#: `<FX>`) for the arms that already agreed at base. Provenance: the FREEZE run on the base
#: tree 075d8ba (masked sha256 of these same bytes, fixed FZROOT); each hash below was
#: checked equal to that base value after substituting the FZROOT fixture path for `<FX>`.
AC6_AGREEING_DRY_SHA: Final[dict[str, str]] = {
    "nopw-noado": "6fe916e0920ec0e22d27210a5ab17f43eb4907adc56b80837b63e018f0f6374c",
    "pw-noado": "6fe916e0920ec0e22d27210a5ab17f43eb4907adc56b80837b63e018f0f6374c",
    "ctl-garbage": "314e59807f160d454068ebee34b0f2c18a4381eeffe2fd3c563786d57f6fb90d",
}


@pytest.mark.parametrize("arm", sorted(BATCH_ARMS))
def test_ac6_compress_batch_dry_real_rows(fx: Path, arm: str) -> None:
    operands, extra, pair, dry_rows, real_rows = BATCH_ARMS[arm]
    tail = [*operands, *extra, "--out-dir", "out"]
    dry = _drive(fx, "compress", tail, dry=True)
    real = _drive(fx, "compress", tail, dry=False)
    assert (dry[0], real[0]) == pair
    if arm in AC6_AGREEING_DRY_SHA:
        normalised = dry[1].replace(str(fx), "<FX>")
        assert hashlib.sha256(normalised.encode()).hexdigest() == AC6_AGREEING_DRY_SHA[arm]
    if dry_rows is not None:
        assert [i["exit_code"] for i in _json(dry[3])["items"]] == dry_rows
        assert [i["exit_code"] for i in _json(real[3])["items"]] == real_rows


@pytest.mark.parametrize("cell", sorted(REPAIR_AFTER))
def test_ac7_repair_is_unchanged(fx: Path, cell: str) -> None:
    dry = _single(fx, "repair", cell, dry=True)
    real = _single(fx, "repair", cell, dry=False)
    assert (dry[0], real[0]) == REPAIR_AFTER[cell]


# --------------------------------------------------------------------------- #
# AC8 -- the probe is pure, runs once and never touches a secret (in-process)
# --------------------------------------------------------------------------- #


def _snapshot(directory: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir())
        if p.is_file()
    }


def _policy() -> Any:
    from pdf_tooling.safety.policy import SafetyPolicy

    return SafetyPolicy(
        dry_run=True,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )


@pytest.mark.parametrize("verb", VERBS)
@pytest.mark.parametrize("operand", ["malformed.pdf", "plain.pdf"])
def test_ac8_probe_is_pure_once_and_secret_free(
    fx: Path, verb: str, operand: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    from pdf_tooling.errors import PdfToolingError
    from pdf_tooling.ops import document_password as seam
    from pdf_tooling.ops import metadata as metadata_ops
    from pdf_tooling.ops import optimize as optimize_ops
    from pdf_tooling.ops import overlay as overlay_ops
    from pdf_tooling.ops.document_password import PasswordSource
    from pdf_tooling.safety import atomic

    DryOpenProbe = _need(seam, "DryOpenProbe")
    compress_probe = _need(optimize_ops, "compress_dry_probe")
    linearize_probe = _need(optimize_ops, "linearize_dry_probe")
    meta_factory = _need(metadata_ops, "_meta_set_dry_probe")

    work = tmp_path / "cell"
    shutil.copytree(fx, work)
    before = _snapshot(work)
    # A dedicated, empty TMPDIR for this test: the preview must leave it empty.
    scratch_tmp = tmp_path / "tmpdir"
    scratch_tmp.mkdir()
    monkeypatch.setenv("TMPDIR", str(scratch_tmp))
    monkeypatch.setattr(tempfile, "tempdir", None)
    calls: list[str] = []

    def thunk() -> Any:
        raise AssertionError("the secret must never be read by a preview")

    password = PasswordSource(slot="password", source="file:/x/pw", read=thunk)

    def _no_writer(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a preview must not create or write through a writer")

    def _no_process(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a preview must not start a process")

    # PDF-170 / OR-97: a preview may construct a writer, never enter, plan or open one.
    for attribute in ("__enter__", "_plan", "_open_temp"):
        monkeypatch.setattr(atomic.AtomicWriter, attribute, _no_writer)
    monkeypatch.setattr(subprocess, "Popen", _no_process)

    source = work / operand
    target = work / "o.pdf"
    policy = _policy()

    def counting(real: Any) -> Any:
        def wrapper(data: bytes, path: Path) -> object:
            calls.append(path.name)
            return real(data, path)

        return wrapper

    class CountingOpen(DryOpenProbe):
        def __call__(self, data: bytes, source: Path) -> object:
            calls.append(source.name)
            return super().__call__(data, source)

    monkeypatch.setattr(optimize_ops, "compress_dry_probe", counting(compress_probe))
    monkeypatch.setattr(optimize_ops, "linearize_dry_probe", counting(linearize_probe))
    monkeypatch.setattr(overlay_ops, "DryOpenProbe", CountingOpen)
    real_factory = meta_factory
    monkeypatch.setattr(
        metadata_ops, "_meta_set_dry_probe", lambda *a, **k: counting(real_factory(*a, **k))
    )

    def invoke() -> Any:
        if verb == "compress":
            return optimize_ops.compress_run(
                [source],
                lossless=True,
                images="keep",
                image_dpi=150.0,
                image_quality=75,
                pages_spec=None,
                output=target,
                out_dir=None,
                name_template=None,
                in_place=False,
                policy=policy,
                password=password,
            )
        if verb == "linearize":
            return optimize_ops.linearize_run(
                source, output=target, in_place=False, policy=policy, password=password
            )
        if verb == "watermark":
            return overlay_ops.watermark_run(
                source,
                text="W",
                pages_spec=None,
                position="center",
                font_size=48.0,
                color=(0.5, 0.5, 0.5),
                opacity=0.3,
                rotate_deg=0.0,
                output=target,
                in_place=False,
                policy=policy,
                password=password,
            )
        if verb == "stamp":
            return overlay_ops.stamp_run(
                source,
                from_path=work / "stampsrc.pdf",
                from_page=1,
                pages_spec=None,
                position="center",
                output=target,
                in_place=False,
                policy=policy,
                password=password,
            )
        return metadata_ops.meta_set_run(
            source,
            sets={"title": "T"},
            clear_producer=False,
            clear_all=False,
            output=target,
            in_place=False,
            policy=policy,
            password=password,
        )

    try:
        invoke()
    except PdfToolingError:
        assert operand == "malformed.pdf"
    expected_calls = 2 if verb == "stamp" else 1
    assert len(calls) == expected_calls
    assert _snapshot(work) == before
    assert tempfile.gettempdir() == str(scratch_tmp)
    assert sorted(os.listdir(scratch_tmp)) == []


CARVE_ARMS: Final[list[tuple[str, list[str]]]] = [
    ("compress", ["enc.pdf"]),
    ("linearize", ["enc.pdf"]),
    ("watermark", ["enc.pdf", "--text", "W"]),
    ("stamp", ["enc.pdf", "--from", "stampsrc.pdf"]),
    ("meta set", ["enc.pdf", "--title", "T"]),
    ("stamp", ["plain.pdf", "--from", "enc.pdf"]),
]


@pytest.mark.parametrize("which", ["good", "bad"])
@pytest.mark.parametrize(
    ("verb", "operands"), CARVE_ARMS, ids=[f"{v}-{o[0]}-{o[-1]}" for v, o in CARVE_ARMS]
)
def test_ac8_carve_out_arms_never_read_the_secret(
    fx: Path,
    verb: str,
    operands: list[str],
    which: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import pdf_tooling.cli.main as main_module
    import pdf_tooling.cli.password as password_module
    from pdf_tooling.cli.common import reset_error_format

    work = tmp_path / "cell"
    shutil.copytree(fx, work)
    reads: list[int] = []
    original = password_module._read_file

    def counting(*args: Any, **kwargs: Any) -> Any:
        reads.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(password_module, "_read_file", counting)
    pw = work / ("pw-good.txt" if which == "good" else "pw-bad.txt")
    argv = [
        "pdftooling",
        *verb.split(),
        "--dry-run",
        *(str(work / o) if o.endswith(".pdf") else o for o in operands),
        "-O",
        str(work / "o.pdf"),
        "--password-file",
        str(pw),
        ADO,
        "-o",
        "json",
    ]
    monkeypatch.chdir(work)
    monkeypatch.setattr(sys, "argv", argv)
    reset_error_format()
    with pytest.raises(SystemExit) as excinfo:
        main_module.main()
    capsys.readouterr()
    assert int(excinfo.value.code or 0) == 0
    assert reads == []


@pytest.mark.parametrize("cell", sorted(PAGE_CELLS))
def test_ac10_page_selection_cells_now_agree(fx: Path, cell: str) -> None:
    # PDF-162 / OR-96: PDF-159 left these six at (0, 2); PDF-162 makes the dry run predict them.
    verb, tail = PAGE_CELLS[cell]
    argv = [*tail, "-O", "o.pdf"]
    dry = _drive(fx, verb, argv, dry=True)
    real = _drive(fx, verb, argv, dry=False)
    assert (dry[0], real[0]) == (2, 2)


def test_ac11_dry_open_probe_reports_the_page_count(fx: Path) -> None:
    import inspect

    import pdf_tooling.ops.document_password as seam
    from pdf_tooling.errors import FailureError

    for name in ("DryOpenProbe", "EngineProbe", "compress_dry_probe", "linearize_dry_probe"):
        _need(seam, name)
        assert name in seam.__all__
    DryOpenProbe = _need(seam, "DryOpenProbe")
    predict_password_refusal = seam.predict_password_refusal
    probe = DryOpenProbe(composite=True)
    assert probe.page_count is None
    plain = fx / "plain.pdf"
    probe(plain.read_bytes(), plain)
    assert probe.page_count == 3
    bad = fx / "malformed.pdf"
    with pytest.raises(FailureError):
        DryOpenProbe(composite=True)(bad.read_bytes(), bad)
    parameter = inspect.signature(predict_password_refusal).parameters["engine_probe"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None
