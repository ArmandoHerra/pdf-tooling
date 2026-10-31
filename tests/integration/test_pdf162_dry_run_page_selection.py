"""PDF-162 -- ``--dry-run`` predicts page-selection usage errors on ``watermark`` and ``stamp``.

Ledger row ``0350a9161e`` (carrier ``B-536``). ``watermark``/``stamp`` previewed ``0 planned:``
for a page selection the real run refuses (``--pages abc|9|0``, ``stamp --from-page 9``, an
empty selection ...). Both verbs now resolve the selection through one seam
(``_select_pages`` / ``_check_from_page``) and the dry run raises the real run's own
exception, using the page counts PDF-159's credential-free probe already read. Operator
ruling ``OR-87``: predicting an error the real run already prints is the README contract.

A dry run never reads a supplied secret, so an input locked behind a user password keeps the
documented ``password_verified: false`` exception (the four secret-gated cells, pinned here).

Every assertion is on the product's own output: exit code, envelope and the bytes of two runs
compared with each other. Fixtures are built here; nothing depends on another test module.
"""

from __future__ import annotations

import json
import os
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

from registry import run_cli  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ADO: Final[str] = "--allow-decrypted-output"
MALFORMED_KINDS: Final[tuple[str, ...]] = ("M.pdf", "malformed.pdf")


@dataclass(frozen=True)
class Cell:
    verb: str
    src: str = "P3.pdf"
    frm: str = "F3.pdf"
    out: str | None = "o.pdf"
    delta: tuple[str, ...] = ()

    def argv(self, *, dry: bool, fmt: str = "json", malformed: str = "M.pdf") -> list[str]:
        src = malformed if self.src == "M" else self.src
        frm = malformed if self.frm == "M" else self.frm
        tail = ["--text", "x"] if self.verb == "watermark" else ["--from", frm]
        dest = ["-O", self.out] if self.out is not None else ["--in-place", "-y"]
        return [
            self.verb,
            *(["--dry-run"] if dry else []),
            "-o",
            fmt,
            src,
            *tail,
            *dest,
            *self.delta,
        ]

    @property
    def names_malformed(self) -> bool:
        return "M" in (self.src, self.frm)


def _w(*delta: str, **kw: Any) -> Cell:
    return Cell("watermark", delta=delta, **kw)


def _s(*delta: str, **kw: Any) -> Cell:
    return Cell("stamp", delta=delta, **kw)


CELLS: Final[dict[str, Cell]] = {
    "W1": _w("--pages", "abc"),
    "W2": _w("--pages", "9"),
    "W3": _w("--pages", "0"),
    "W4": _w("--pages", "1-2"),
    "W5": _w("--pages=-5"),
    "W6": _w("--pages", ""),
    "W7": _w("--pages", "even", src="P1.pdf"),
    "W8": _w("--pages", "all,!all"),
    "W9": _w("--pages", "!2"),
    "W10": _w("--pages", "3-9"),
    "W11": _w("--pages", "1-99999999999"),
    "W12": _w("--pages", "2,9"),
    "W13": _w("--pages", "abc", src="M"),
    "W14": _w("--pages", "9", src="M"),
    "W15": _w(ADO, "--pages", "abc", src="EU.pdf"),
    "W16": _w(ADO, "--password-file", "Ufile", "--pages", "9", src="EU.pdf"),
    "W17": _w(ADO, "--password-file", "Wfile", "--pages", "9", src="EU.pdf"),
    "W18": _w(ADO, "--pages", "9", src="EO.pdf"),
    "W19": _w("--pages", "9", src="EU.pdf"),
    "W20": _w("--pages", "9", out="exists.pdf"),
    "W21": _w("--pages", "9", out=None),
    "W22": _w("--pages", "9", src="missing.pdf"),
    "W23": _w(),
    "W24": _w("--pages", "!2,all"),
    "W25": _w("--pages", "3"),
    "S1": _s("--pages", "abc"),
    "S2": _s("--pages", "9"),
    "S3": _s("--pages", "0"),
    "S4": _s("--pages", "1-2"),
    "S5": _s("--from-page", "9"),
    "S6": _s("--from-page", "3"),
    "S7": _s("--from-page", "0"),
    "S8": _s("--from-page", "9", "--pages", "abc"),
    "S9": _s("--from-page", "9", "--pages", "9"),
    "S10": _s("--from-page", "9", src="M"),
    "S11": _s("--pages", "9", src="M"),
    "S12": _s("--pages", "9", frm="M"),
    "S13": _s("--from-page", "9", frm="M"),
    "S14": _s("--from-page", "9", frm="EU.pdf"),
    "S15": _s("--password-file", "Ufile", "--from-page", "9", frm="EU.pdf"),
    "S16": _s(ADO, "--pages", "9", src="EU.pdf"),
    "S17": _s(ADO, "--password-file", "Ufile", "--pages", "9", src="EU.pdf"),
    "S18": _s(ADO, "--password-file", "Wfile", "--pages", "9", src="EU.pdf"),
    "S19": _s(ADO, "--pages", "9", src="EO.pdf"),
    "S20": _s("--from-page", "9", out="exists.pdf"),
    "S21": _s("--pages", "9", out="exists.pdf"),
    "S23": _s("--pages", "even", src="P1.pdf"),
    "S24": _s("--from-page", "2", frm="F1.pdf"),
    "S25": _s("--pages", "2,9"),
    "S26": _s(),
    "S27": _s("--pages", "4", frm="F5.pdf"),
}

AC1_CELLS: Final[tuple[str, ...]] = ("W1", "W2", "W3", "S1", "S2", "S5")
AC2_CELLS: Final[tuple[str, ...]] = (
    "W5", "W6", "W10", "W11", "W12", "W18", "W21",
    "S3", "S8", "S9", "S19", "S24", "S25", "S27",
)  # fmt: skip
AC3_ERR_CELLS: Final[tuple[str, ...]] = ("W7", "W8", "W9", "S23")
#: cell -> (dry rc, real rc); the dry answer for W20/S20/S21 is an OP envelope.
AC4_PINS: Final[dict[str, tuple[int, int]]] = {
    "W13": (1, 1), "W14": (1, 1), "W15": (6, 6), "W19": (5, 5), "W20": (5, 5),
    "W22": (4, 4), "S7": (2, 2), "S8": (2, 2), "S10": (2, 2), "S11": (1, 1),
    "S12": (1, 1), "S13": (1, 1), "S14": (5, 5), "S15": (5, 5), "S16": (6, 6),
    "S20": (5, 5), "S21": (5, 5),
}  # fmt: skip
AC4_DRY_OP: Final[tuple[str, ...]] = ("W20", "S20", "S21")
AC5_CELLS: Final[tuple[str, ...]] = ("W4", "W23", "W25", "S4", "S6", "S26")
AC6_PINS: Final[dict[str, tuple[int, int]]] = {
    "W16": (0, 2), "W17": (0, 6), "S17": (0, 2), "S18": (0, 6),
}  # fmt: skip

_ENV_DROP = {"PDF_TOOLING_PASSWORD", "PDF_TOOLING_OWNER_PASSWORD"}


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _ENV_DROP}


def _make_pages(path: Path, count: int, *, encryption: pikepdf.Encryption | None = None) -> None:
    pdf = pikepdf.new()
    for _ in range(count):
        pdf.add_blank_page(page_size=(612, 792))
    if encryption is None:
        pdf.save(path)
    else:
        pdf.save(path, encryption=encryption)
    pdf.close()


@pytest.fixture(scope="module")
def fx(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("pdf162") / "fx"
    root.mkdir()
    _make_pages(root / "P3.pdf", 3)
    _make_pages(root / "P1.pdf", 1)
    _make_pages(root / "F3.pdf", 3)
    _make_pages(root / "F1.pdf", 1)
    _make_pages(root / "F5.pdf", 5)
    _make_pages(root / "exists.pdf", 3)
    (root / "M.pdf").write_bytes((root / "P3.pdf").read_bytes()[:200])
    shutil.copy(REPO_ROOT / "testdata" / "malformed.pdf", root / "malformed.pdf")
    _make_pages(root / "EU.pdf", 3, encryption=pikepdf.Encryption(user="u", owner="o"))
    _make_pages(root / "EO.pdf", 3, encryption=pikepdf.Encryption(user="", owner="o"))
    for name, value in (("Ufile", "u\n"), ("Wfile", "wrong\n")):
        (root / name).write_text(value)
        (root / name).chmod(0o600)
    return root


@dataclass(frozen=True)
class Run:
    rc: int
    stdout: bytes
    stderr: bytes
    listing_before: tuple[tuple[str, int, int], ...]
    listing_after: tuple[tuple[str, int, int], ...]
    work: Path

    @property
    def doc(self) -> Any:
        return json.loads(self.stdout)

    @property
    def last_stderr_line(self) -> str:
        lines = self.stderr.decode().strip().splitlines()
        return lines[-1] if lines else ""


def _listing(root: Path) -> tuple[tuple[str, int, int], ...]:
    return tuple(
        sorted(
            (p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in root.iterdir() if p.is_file()
        )
    )


_CACHE: dict[tuple[str, ...], Run] = {}
_COUNTER = [0]


def _drive(fx: Path, argv: list[str]) -> Run:
    key = tuple(argv)
    if key in _CACHE:
        return _CACHE[key]
    _COUNTER[0] += 1
    work = fx.parent / f"cell{_COUNTER[0]}"
    shutil.copytree(fx, work)
    before = _listing(work)
    result = run_cli(*argv, cwd=work, env=_env())
    # run_cli decodes text; re-encode so two runs are compared as exact byte strings.
    run = Run(
        result.returncode,
        result.stdout.encode(),
        result.stderr.encode(),
        before,
        _listing(work),
        work,
    )
    _CACHE[key] = run
    return run


def _pair(
    fx: Path, cell_id: str, *, fmt: str = "json", malformed: str = "M.pdf"
) -> tuple[Run, Run]:
    cell = CELLS[cell_id]
    dry = _drive(fx, cell.argv(dry=True, fmt=fmt, malformed=malformed))
    real = _drive(fx, cell.argv(dry=False, fmt=fmt, malformed=malformed))
    return dry, real


def _kind(run: Run) -> str:
    return str(run.doc["error"]["kind"])


# --------------------------------------------------------------------------- #
# AC1 - AC3: the dry run raises what the real run raises, byte for byte
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("cell_id", AC1_CELLS)
def test_ac1_fingerprint_cells_dry_equals_real(fx: Path, cell_id: str) -> None:
    dry, real = _pair(fx, cell_id)
    assert (dry.rc, real.rc) == (2, 2)
    assert _kind(dry) == "usage"
    assert _kind(real) == "usage"
    assert dry.stdout == real.stdout
    assert dry.stderr == real.stderr


@pytest.mark.parametrize("cell_id", AC2_CELLS)
def test_ac2_census_usage_cells_dry_equals_real(fx: Path, cell_id: str) -> None:
    dry, real = _pair(fx, cell_id)
    assert (dry.rc, real.rc) == (2, 2)
    assert _kind(dry) == "usage"
    assert dry.stdout == real.stdout
    assert dry.stderr == real.stderr
    if cell_id in ("S8", "S9"):
        assert dry.doc["error"]["message"].startswith("--from-page 9 exceeds --from's page count")


@pytest.mark.parametrize("cell_id", [*AC3_ERR_CELLS, "W24"])
def test_ac3_empty_selection_cells_dry_equals_real(fx: Path, cell_id: str) -> None:
    dry, real = _pair(fx, cell_id)
    assert dry.stderr == real.stderr
    if cell_id == "W24":
        assert (dry.rc, real.rc) == (0, 0)
        assert b"begins with exclusion token" in dry.stderr
        return
    assert (dry.rc, real.rc) == (4, 4)
    assert _kind(dry) == "no_input"
    assert dry.stdout == real.stdout
    if cell_id == "W9":
        assert b"WARNING: page-range spec '!2' begins with exclusion token" in dry.stderr


# --------------------------------------------------------------------------- #
# AC4: precedence is the real run's
# --------------------------------------------------------------------------- #


def _ac4_params() -> list[Any]:
    out: list[Any] = []
    for cell_id in AC4_PINS:
        kinds = MALFORMED_KINDS if CELLS[cell_id].names_malformed else ("M.pdf",)
        for kind in kinds:
            out.append(pytest.param(cell_id, kind, id=f"{cell_id}-{kind}"))
    return out


@pytest.mark.parametrize(("cell_id", "malformed"), _ac4_params())
def test_ac4_precedence_pins(fx: Path, cell_id: str, malformed: str) -> None:
    dry, real = _pair(fx, cell_id, malformed=malformed)
    assert (dry.rc, real.rc) == AC4_PINS[cell_id]
    if cell_id in AC4_DRY_OP:
        assert "error" not in dry.doc
        item = dry.doc["items"][0]
        assert item["ok"] is False
        assert item["exit_code"] == 5
        assert "error" in real.doc
    if cell_id in ("S8", "S10"):
        assert dry.stdout == real.stdout
        assert dry.doc["error"]["message"].startswith("--from-page 9 exceeds --from's page count")


# --------------------------------------------------------------------------- #
# AC5: valid selections still plan
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("cell_id", AC5_CELLS)
def test_ac5_valid_selections_still_plan(fx: Path, cell_id: str) -> None:
    dry, real = _pair(fx, cell_id)
    assert (dry.rc, real.rc) == (0, 0)
    assert "error" not in dry.doc
    assert dry.doc["items"][0]["message"] == f"planned: {CELLS[cell_id].verb}"
    assert dry.listing_after == dry.listing_before
    assert any(name == "o.pdf" for name, _, _ in real.listing_after)


# --------------------------------------------------------------------------- #
# AC6: the secret-gated cells keep the documented exception
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("cell_id", list(AC6_PINS))
def test_ac6_secret_gated_cells_are_unchanged(fx: Path, cell_id: str) -> None:
    dry, real = _pair(fx, cell_id)
    assert (dry.rc, real.rc) == AC6_PINS[cell_id]
    item = dry.doc["items"][0]
    assert item["ok"] is True
    detail = item["detail"]
    assert detail["password_verified"] is False
    name = "Ufile" if "Ufile" in CELLS[cell_id].delta else "Wfile"
    assert detail["password_source"] == f"file:{name}"


# --------------------------------------------------------------------------- #
# AC7: the same envelope in every output format
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("cell_id", "fmt"),
    [
        pytest.param("W1", "table", id="W1-table"),
        pytest.param("W2", "table", id="W2-table"),
        pytest.param("S2", "table", id="S2-table"),
        pytest.param("S5", "table", id="S5-table"),
        pytest.param("W1", "ndjson", id="W1-ndjson"),
    ],
)
def test_ac7_other_formats_match(fx: Path, cell_id: str, fmt: str) -> None:
    dry, real = _pair(fx, cell_id, fmt=fmt)
    assert (dry.rc, real.rc) == (2, 2)
    if fmt == "ndjson":
        assert dry.stdout == real.stdout
        return
    assert dry.stdout == b""
    assert real.stdout == b""
    assert dry.stderr == real.stderr
    assert dry.last_stderr_line.startswith("error: ")


# --------------------------------------------------------------------------- #
# AC9: a dry run still writes nothing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("cell_id", sorted(CELLS))
def test_ac9_dry_cells_write_nothing(fx: Path, cell_id: str) -> None:
    cell = CELLS[cell_id]
    dry = _drive(fx, cell.argv(dry=True))
    assert dry.listing_after == dry.listing_before
    assert not (dry.work / "P3.pdf.bak").exists()
    if cell_id == "W21":
        assert (dry.work / "P3.pdf").read_bytes() == (fx / "P3.pdf").read_bytes()
