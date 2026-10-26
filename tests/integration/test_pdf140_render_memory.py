"""PDF-140 / X-1070 -- a ``rasterize`` run's render memory is bounded.

``RUN_PIXEL_BUDGET`` caps the pixels rendering at once across all workers by
using FEWER workers (never refusing). Every arm here observes the product from
the outside where it can: the dry/real pair over the exit table, the OS
processes actually spawned (``tests/rss_probe.py``, which never imports the
product), and bytes on disk. Fixtures are built module-locally with pikepdf.

The scaled seam (``_SCALED_SEAM``) is TEST-ONLY code: it patches the module
attribute in a child interpreter so the cap engages without gigabytes. The
product gains no override of any kind.

Linux-only arms (``/proc`` sampling) skip elsewhere and are never a pass.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import pikepdf
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

import rss_probe  # noqa: E402
from fs_snapshot import redirected_environment  # noqa: E402
from pdf_tooling.ports.raster import (  # noqa: E402
    PIXEL_BUDGET,
    RUN_PIXEL_BUDGET,
    render_cap_warning,
    render_workers,
)
from registry import REPO_ROOT, console_script  # noqa: E402

pytestmark = pytest.mark.e2e

A4 = (595.28, 841.89)
LETTER = (612.0, 792.0)
_CAP = re.compile(r"^render workers capped at (\d+) of (\d+):")
_SCALED_BUDGET = 2_000_000

#: Test-only. Patches the module attribute (what `render_workers` reads at call
#: time) in the child interpreter, then runs the real console entry point. The
#: env switch makes `PIL.features.check` report no webp (AC4 cell 3).
_SCALED_SEAM = (
    "import os, sys; "
    "import pdf_tooling.ports.raster as r; "
    "r.RUN_PIXEL_BUDGET = int(sys.argv[1]); "
    "sys.argv = ['pdftooling'] + sys.argv[2:]; "
    "import PIL.features as f; "
    "f.check = (lambda *a, **k: False) if os.environ.get('PDF140_NO_WEBP') else f.check; "
    "from pdf_tooling.cli.main import main; "
    "sys.exit(main())"
)


def _alloc_px(box: tuple[float, float], dpi: float | None = None, width: int | None = None) -> int:
    """The test's OWN restatement of the page-size arithmetic (D7): never the product's."""
    w_pt, h_pt = box
    scale = (width / w_pt * 72.0 if width is not None else float(dpi or 0)) / 72.0
    return math.ceil(w_pt * scale) * math.ceil(h_pt * scale)


def _expected_workers(px: int, *, threads: int, pages: int, budget: int = RUN_PIXEL_BUDGET) -> int:
    return max(1, min(threads, pages, budget // px))


def _make(path: Path, box: tuple[float, float], pages: int, **save: object) -> Path:
    pdf = pikepdf.new()
    for _ in range(pages):
        page = pdf.add_blank_page(page_size=(100, 100))
        page.MediaBox = [0, 0, box[0], box[1]]
    pdf.save(path, **save)  # type: ignore[arg-type]
    return path


@pytest.fixture(scope="module")
def fx(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("pdf140")
    corrupt = d / "corrupt.pdf"
    corrupt.write_bytes((_make(d / "tmp-src.pdf", A4, 1).read_bytes())[:120])
    return {
        "a4x8": _make(d / "a4x8.pdf", A4, 8),
        "a4x1": _make(d / "a4x1.pdf", A4, 1),
        "a4x4": _make(d / "a4x4.pdf", A4, 4),
        "a4x5": _make(d / "a4x5.pdf", A4, 5),
        "letter32": _make(d / "letter32.pdf", LETTER, 32),
        "letter4": _make(d / "letter4.pdf", LETTER, 4),
        "huge": _make(d / "huge.pdf", (14400, 14400), 1),
        "corrupt": corrupt,
        "a4x4_enc": _make(
            d / "a4x4_enc.pdf",
            A4,
            4,
            encryption=pikepdf.Encryption(user="u-pw", owner="o-pw", R=6),
        ),
        "missing": d / "missing.pdf",
    }


class Run:
    def __init__(self, completed: subprocess.CompletedProcess[str]) -> None:
        self.rc = completed.returncode
        self.stdout = completed.stdout
        self.stderr = completed.stderr
        try:
            self.envelope: dict | None = json.loads(completed.stdout)
        except json.JSONDecodeError:
            self.envelope = None

    @property
    def warnings(self) -> list[str]:
        assert self.envelope is not None, (self.rc, self.stdout, self.stderr)
        return list(self.envelope.get("warnings", []))

    @property
    def cap(self) -> tuple[int, int] | None:
        hits = [m for w in self.warnings if (m := _CAP.match(w))]
        assert len(hits) <= 1, self.warnings
        return (int(hits[0].group(1)), int(hits[0].group(2))) if hits else None


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env, _roots = redirected_environment(tmp_path / "env")
    for key in ("TMPDIR", "HOME"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    env.pop("PDF_TOOLING_PASSWORD", None)
    env.update(extra)
    return env


def _cli(args: list[str], tmp_path: Path) -> Run:
    return Run(
        subprocess.run(
            [*console_script(), *args],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(tmp_path),
            env=_env(tmp_path),
            timeout=180,
        )
    )


def _scaled(args: list[str], tmp_path: Path, *, budget: int = _SCALED_BUDGET, **env: str) -> Run:
    return Run(
        subprocess.run(
            [sys.executable, "-I", "-c", _SCALED_SEAM, str(budget), *args],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(tmp_path),
            env=_env(tmp_path, **env),
            timeout=180,
        )
    )


def _files(directory: Path) -> dict[str, str]:
    if not directory.exists():
        return {}
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir())
        if p.is_file()
    }


def _need_proc() -> None:
    if not rss_probe.have_proc():
        pytest.skip(rss_probe.PROC_SKIP_REASON)


# --------------------------------------------------------------------------- #
# AC1 / AC2 -- the pure function and the warning text
# --------------------------------------------------------------------------- #

_PEAKS = (1, 2_176_714, 34_806_376, 47_380_568, 89_478_485, 178_829_235, PIXEL_BUDGET)


def test_ac1_the_run_budget_is_at_least_the_page_budget() -> None:
    assert RUN_PIXEL_BUDGET >= PIXEL_BUDGET


def test_ac1_render_workers_holds_the_bound_caps_only_when_it_must_and_never_refuses() -> None:
    for peak in _PEAKS:
        for requested in range(1, 65):
            for items in range(1, 65):
                natural = min(requested, items)
                got = render_workers(peak, requested=requested, work_items=items)
                cell = f"(peak={peak:,}, requested={requested}, work_items={items})"
                assert 1 <= got <= natural, f"{cell} -> {got}"
                assert got * peak <= RUN_PIXEL_BUDGET, f"{cell} -> {got} overflows the budget"
                if natural * peak <= RUN_PIXEL_BUDGET:
                    assert got == natural, f"{cell} -> {got}: capped though it fit"


def test_ac1_equality_is_legal_and_a_nonpositive_peak_returns_the_natural_count() -> None:
    assert render_workers(PIXEL_BUDGET, requested=8, work_items=8) == 2
    assert render_workers(89_478_485, requested=4, work_items=4) == 4
    assert render_workers(0, requested=5, work_items=9) == 5
    assert render_workers(-1, requested=5, work_items=3) == 3


def test_ac2_the_warning_text_is_exact_and_derived() -> None:
    expected = (
        "render workers capped at 2 of 8: the largest planned page allocates "
        f"178,829,235 px, and at most {RUN_PIXEL_BUDGET:,} px may render at once "
        "(README: Render budget); output files are unchanged"
    )
    got = render_cap_warning(2, 8, 178_829_235)
    assert got == expected
    assert got.startswith("render workers capped at 2 of 8:")
    assert _CAP.match(got)


# --------------------------------------------------------------------------- #
# AC3 -- decisive dry arms at the REAL constant (no render, no memory)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("fixture", "flags", "expected"),
    [
        ("a4x8", ["--threads", "8", "--dpi", "600"], None),
        ("a4x8", ["--threads", "8", "--dpi", "700"], (7, 8)),
        ("a4x8", ["--threads", "8", "--dpi", "1360"], (2, 8)),
        ("a4x1", ["--threads", "8", "--dpi", "1360"], None),
        ("a4x8", ["--threads", "2", "--dpi", "1360"], None),
        ("a4x8", ["--threads", "8", "--width", "11245"], (2, 8)),
    ],
)
def test_ac3_dry_run_predicts_the_cap_at_the_real_constant(
    fx: dict[str, Path],
    tmp_path: Path,
    fixture: str,
    flags: list[str],
    expected: tuple[int, int] | None,
) -> None:
    run = _cli(
        [
            "rasterize",
            str(fx[fixture]),
            *flags,
            "--out-dir",
            str(tmp_path / "O"),
            "--dry-run",
            "-o",
            "json",
        ],
        tmp_path,
    )
    assert run.rc == 0, (run.stdout, run.stderr)
    assert run.cap == expected, run.warnings
    if expected is None:
        assert run.warnings == []
    assert not (tmp_path / "O").exists()


def test_ac3_the_expected_cells_agree_with_the_tests_own_arithmetic() -> None:
    assert _alloc_px(A4, dpi=700) == 47_380_568
    assert _expected_workers(_alloc_px(A4, dpi=700), threads=8, pages=8) == 7
    assert _expected_workers(_alloc_px(A4, dpi=1360), threads=8, pages=8) == 2
    assert _expected_workers(_alloc_px(A4, dpi=600), threads=8, pages=8) == 8
    assert _expected_workers(_alloc_px(A4, width=11245), threads=8, pages=8) == 2


# --------------------------------------------------------------------------- #
# AC4 -- the dry/real matrix over rasterize's exit table, as (dry, real) pairs
# --------------------------------------------------------------------------- #


def _pair(args: list[str], tmp_path: Path, **env: str) -> tuple[Run, Run, Path, Path]:
    d_out, r_out = tmp_path / "Od", tmp_path / "Or"
    dry = _scaled(
        [*args, "--out-dir", str(d_out), "--dry-run", "-o", "json"], tmp_path / "d", **env
    )
    real = _scaled([*args, "--out-dir", str(r_out), "-o", "json"], tmp_path / "r", **env)
    return dry, real, d_out, r_out


@pytest.fixture
def pairdirs(tmp_path: Path) -> Path:
    (tmp_path / "d").mkdir()
    (tmp_path / "r").mkdir()
    return tmp_path


def test_ac4_cell_0_uncapped(fx: dict[str, Path], pairdirs: Path) -> None:
    dry, real, _d, r_out = _pair(
        ["rasterize", str(fx["a4x4"]), "--dpi", "50", "--threads", "4"], pairdirs
    )
    assert (dry.rc, real.rc) == (0, 0)
    assert dry.cap is None and real.cap is None
    assert len(_files(r_out)) == 4


def test_ac4_cell_0_capped_the_decisive_arm(fx: dict[str, Path], pairdirs: Path) -> None:
    dry, real, d_out, r_out = _pair(
        ["rasterize", str(fx["a4x4"]), "--dpi", "100", "--threads", "4"], pairdirs
    )
    assert (dry.rc, real.rc) == (0, 0), (dry.stderr, real.stderr)
    assert dry.cap == (2, 4) and real.cap == (2, 4)
    assert dry.warnings == real.warnings
    assert f"warning: {real.warnings[0]}" in real.stderr
    assert not d_out.exists()
    assert len(_files(r_out)) == 4


def test_ac4_cell_1_a_corrupt_source_records_no_peak(fx: dict[str, Path], pairdirs: Path) -> None:
    dry, real, _d, r_out = _pair(
        [
            "rasterize",
            str(fx["a4x4"]),
            str(fx["corrupt"]),
            "--dpi",
            "100",
            "--threads",
            "4",
        ],
        pairdirs,
    )
    assert (dry.rc, real.rc) == (1, 1), (dry.stdout, real.stdout, real.stderr)
    assert dry.cap == (2, 4) and real.cap == (2, 4)
    assert sorted(_files(r_out)) == [f"a4x4-000{n}.png" for n in range(1, 5)]
    assert real.envelope is not None
    rows = {Path(i["input"]).name: i for i in real.envelope["items"] if "corrupt" in i["input"]}
    assert [r["exit_code"] for r in rows.values()] == [1]


@pytest.mark.parametrize("bad", [["--threads", "0"], ["--dpi", "nan"]])
def test_ac4_cell_2_usage(fx: dict[str, Path], pairdirs: Path, bad: list[str]) -> None:
    base = ["rasterize", str(fx["a4x4"]), "--dpi", "100", "--threads", "4"]
    if bad[0] == "--threads":
        base = ["rasterize", str(fx["a4x4"]), "--dpi", "100", *bad]
    else:
        base = ["rasterize", str(fx["a4x4"]), "--threads", "4", *bad]
    dry, real, d_out, r_out = _pair(base, pairdirs)
    assert (dry.rc, real.rc) == (2, 2), (dry.stderr, real.stderr)
    assert "render workers capped" not in dry.stderr + real.stderr
    assert _files(d_out) == {} and _files(r_out) == {}


def test_ac4_cell_3_engine_missing(fx: dict[str, Path], pairdirs: Path) -> None:
    dry, real, d_out, r_out = _pair(
        ["rasterize", str(fx["a4x4"]), "--dpi", "100", "--format", "webp", "--threads", "4"],
        pairdirs,
        PDF140_NO_WEBP="1",
    )
    assert (dry.rc, real.rc) == (3, 3), (dry.stdout, dry.stderr, real.stderr)
    assert "render workers capped" not in dry.stderr + real.stderr
    assert _files(d_out) == {} and _files(r_out) == {}


def test_ac4_cell_4_no_input(fx: dict[str, Path], pairdirs: Path) -> None:
    dry, real, d_out, r_out = _pair(
        ["rasterize", str(fx["missing"]), "--dpi", "100", "--threads", "4"], pairdirs
    )
    assert (dry.rc, real.rc) == (4, 4), (dry.stderr, real.stderr)
    assert "render workers capped" not in dry.stderr + real.stderr
    assert _files(d_out) == {} and _files(r_out) == {}


def test_ac4_cell_5_budget_refusal_is_never_turned_into_a_capped_render(
    fx: dict[str, Path], pairdirs: Path
) -> None:
    dry, real, d_out, r_out = _pair(
        ["rasterize", str(fx["a4x4"]), str(fx["huge"]), "--dpi", "100", "--threads", "4"],
        pairdirs,
    )
    assert (dry.rc, real.rc) == (5, 5), (dry.stdout, real.stdout)
    assert dry.stdout == real.stdout, "the refusal envelope must be byte-identical across tiers"
    assert "render workers capped" not in dry.stdout + dry.stderr + real.stdout + real.stderr
    assert _files(d_out) == {} and _files(r_out) == {}


def test_ac4_cell_5_clobber_predicts_exit_5_and_carries_no_cap_warning(
    fx: dict[str, Path], pairdirs: Path
) -> None:
    d_out, r_out = pairdirs / "Od", pairdirs / "Or"
    for out in (d_out, r_out):
        out.mkdir()
        (out / "a4x4-0001.png").write_bytes(b"precious")
    dry, real, _d, _r = _pair(
        ["rasterize", str(fx["a4x4"]), "--dpi", "100", "--threads", "4"], pairdirs
    )
    assert (dry.rc, real.rc) == (5, 5), (dry.stdout, dry.stderr, real.stdout, real.stderr)
    assert dry.envelope is not None
    assert {i["detail"]["would_exit"] for i in dry.envelope["items"]} == {5}
    assert dry.warnings == []
    assert (r_out / "a4x4-0001.png").read_bytes() == b"precious"
    assert sorted(p.name for p in r_out.iterdir()) == ["a4x4-0001.png"]


def test_ac4_cell_6_auth(fx: dict[str, Path], pairdirs: Path) -> None:
    dry, real, d_out, r_out = _pair(
        ["rasterize", str(fx["a4x4_enc"]), "--dpi", "100", "--threads", "4"], pairdirs
    )
    assert (dry.rc, real.rc) == (6, 6), (dry.stdout, dry.stderr, real.stdout, real.stderr)
    assert "render workers capped" not in dry.stderr + real.stderr
    assert _files(d_out) == {} and _files(r_out) == {}


# --------------------------------------------------------------------------- #
# AC5 -- independent harness: the OS sees the computed number of workers
# --------------------------------------------------------------------------- #

_AC5_BUDGET = 2 * 15_474_824


def test_ac5_the_capped_run_spawns_the_computed_workers_and_stays_under_the_bound(
    fx: dict[str, Path], tmp_path: Path
) -> None:
    _need_proc()
    px = _alloc_px(A4, dpi=400)
    assert px == 15_474_824
    expected = _expected_workers(px, threads=4, pages=4, budget=_AC5_BUDGET)
    assert expected == 2
    out = tmp_path / "O"
    result = rss_probe.probe(
        [
            sys.executable,
            "-I",
            "-c",
            _SCALED_SEAM,
            str(_AC5_BUDGET),
            "rasterize",
            str(fx["a4x4"]),
            "--dpi",
            "400",
            "--threads",
            "4",
            "--out-dir",
            str(out),
            "-o",
            "json",
        ],
        env=_env(tmp_path),
        cwd=tmp_path,
    )
    assert result.rc == 0, (result.stdout, result.stderr)
    bound = (_AC5_BUDGET * 13) / 2**20 + 80 + expected * 45
    assert result.max_workers == expected, (
        f"the OS saw {result.max_workers} render worker(s), expected {expected}"
    )
    assert result.peak_rss_mib <= bound, (
        f"summed group RSS peaked at {result.peak_rss_mib:.1f} MiB, over the {bound:.1f} MiB bound"
    )
    envelope = json.loads(result.stdout)
    assert any(w.startswith("render workers capped at 2 of 4:") for w in envelope["warnings"])


def test_ac5_the_harness_never_imports_the_product() -> None:
    tree = ast.parse((TESTS_DIR / "rss_probe.py").read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert [m for m in imported if m.split(".")[0] == "pdf_tooling"] == []


# --------------------------------------------------------------------------- #
# AC6 -- capped output is byte-identical to sequential output
# --------------------------------------------------------------------------- #


def test_ac6_capped_output_is_byte_identical_to_sequential_output(
    fx: dict[str, Path], tmp_path: Path
) -> None:
    (tmp_path / "c").mkdir()
    (tmp_path / "s").mkdir()
    cap_out, seq_out = tmp_path / "Ocap", tmp_path / "Oseq"
    common = ["rasterize", str(fx["a4x5"]), "--dpi", "100"]
    capped = _scaled(
        [*common, "--threads", "4", "--out-dir", str(cap_out), "-o", "json"], tmp_path / "c"
    )
    assert capped.rc == 0, (capped.stdout, capped.stderr)
    # The warning step FIRST: an uncapped run would produce the same map, so a
    # silent no-op seam must fail here, never skip.
    assert capped.envelope is not None
    assert any(
        w.startswith("render workers capped at 2 of 4:") for w in capped.envelope["warnings"]
    ), capped.envelope["warnings"]
    assert f"warning: {capped.warnings[0]}" in capped.stderr
    sequential = _scaled(
        [*common, "--threads", "1", "--out-dir", str(seq_out), "-o", "json"], tmp_path / "s"
    )
    assert sequential.rc == 0, (sequential.stdout, sequential.stderr)
    capped_map, seq_map = _files(cap_out), _files(seq_out)
    assert len(capped_map) == 5
    assert capped_map == seq_map


# --------------------------------------------------------------------------- #
# AC7 -- help documents the run bound, derived
# --------------------------------------------------------------------------- #


def test_ac7_help_documents_the_run_bound_derived_from_the_constant(tmp_path: Path) -> None:
    run = _cli(["rasterize", "--help"], tmp_path)
    assert run.rc == 0
    collapsed = " ".join(run.stdout.split())
    assert f"{RUN_PIXEL_BUDGET:,}" in collapsed
    assert "fewer workers render" in collapsed


# --------------------------------------------------------------------------- #
# AC9 -- the frozen surface holds, asserted as bytes
# --------------------------------------------------------------------------- #

_BASE = "7b1286b"


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        shallow = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--is-shallow-repository"],
            capture_output=True,
            text=True,
            check=False,
        )
        if shallow.returncode == 0 and shallow.stdout.strip() == "true":
            pytest.skip(f"shallow clone: {_BASE} is not reachable in this checkout")
        pytest.fail(f"git {' '.join(args)} failed (rc {done.returncode}): {done.stderr.strip()}")
    return done.stdout


def test_ac9_the_envelope_key_golden_is_byte_identical_to_the_base() -> None:
    at_base = _git("rev-parse", f"{_BASE}:tests/golden/envelope_keys.json").strip()
    at_head = _git("hash-object", "tests/golden/envelope_keys.json").strip()
    assert at_head == at_base


def test_ac9_the_pre_existing_render_budget_paragraphs_are_byte_identical() -> None:
    def first_three(text: str) -> str:
        body = text.split("\n## Render budget\n", 1)[1].split("\n## ", 1)[0]
        return "\n\n".join(body.strip("\n").split("\n\n")[:3])

    base = first_three(_git("show", f"{_BASE}:README.md"))
    head = first_three((REPO_ROOT / "README.md").read_text(encoding="utf-8"))
    assert base.startswith("No page of any PDF may make")
    assert head == base


def test_ac9_a_capped_real_run_keeps_the_envelope_shape(
    fx: dict[str, Path], tmp_path: Path
) -> None:
    golden = json.loads((REPO_ROOT / "tests/golden/envelope_keys.json").read_text("utf-8"))
    run = _scaled(
        [
            "rasterize",
            str(fx["a4x4"]),
            "--dpi",
            "100",
            "--threads",
            "4",
            "--out-dir",
            str(tmp_path / "O"),
            "-o",
            "json",
        ],
        tmp_path,
    )
    assert run.rc == 0 and run.cap == (2, 4), (run.stdout, run.stderr)
    assert run.envelope is not None
    assert set(run.envelope) == set(golden["leaves"]["rasterize"]["json"])
    assert all("detail" not in item for item in run.envelope["items"])


# --------------------------------------------------------------------------- #
# AC10 -- full-scale confirmation (opt-in; owed off the shared host)
# --------------------------------------------------------------------------- #


def test_ac10_full_scale_capped_run_stays_under_the_documented_bound(
    fx: dict[str, Path], tmp_path: Path
) -> None:
    if os.environ.get("PDF_TOOLING_FULL_SCALE_RSS") != "1":
        pytest.skip(rss_probe.FULL_SCALE_SKIP_REASON)
    _need_proc()
    px = _alloc_px(A4, dpi=1360)
    expected = _expected_workers(px, threads=8, pages=8)
    assert expected == 2
    result = rss_probe.probe(
        [
            *console_script(),
            "rasterize",
            str(fx["a4x8"]),
            "--dpi",
            "1360",
            "--threads",
            "8",
            "--out-dir",
            str(tmp_path / "O"),
            "-o",
            "json",
        ],
        env=_env(tmp_path),
        cwd=tmp_path,
    )
    assert result.rc == 0, (result.stdout, result.stderr)
    assert result.max_workers == expected
    assert any(
        w.startswith("render workers capped at 2 of 8:")
        for w in json.loads(result.stdout)["warnings"]
    )
    assert result.peak_rss_mib <= expected * px * 13 / 2**20 + 80 + expected * 45


# --------------------------------------------------------------------------- #
# AC11 -- the signal / start-method arms keep their worker counts
# --------------------------------------------------------------------------- #

#: (fixture, pages, box, dpi, threads-or-None) as LANDED at the base in
#: `test_rasterize_signals.py` (32 Letter pages, --dpi 400, --threads 8) and
#: `test_render_pool_start_method.py` (the same, plus 4 Letter pages, --dpi 72,
#: default --threads). Re-read at the rebased parent, not assumed.
_SIGNAL_CONFIGS = [
    ("letter32", 32, LETTER, 400, 8),
    ("letter4", 4, LETTER, 72, None),
]


@pytest.mark.parametrize(("fixture", "pages", "box", "dpi", "threads"), _SIGNAL_CONFIGS)
def test_ac11_the_signal_and_start_method_configs_stay_uncapped(
    fx: dict[str, Path],
    tmp_path: Path,
    fixture: str,
    pages: int,
    box: tuple[float, float],
    dpi: int,
    threads: int | None,
) -> None:
    requested = threads if threads is not None else 8  # DEFAULT_THREADS is at most 8
    px = _alloc_px(box, dpi=dpi)
    assert render_workers(px, requested=requested, work_items=pages) == min(requested, pages)
    args = ["rasterize", str(fx[fixture]), "--dpi", str(dpi)]
    if threads is not None:
        args += ["--threads", str(threads)]
    run = _cli([*args, "--out-dir", str(tmp_path / "O"), "--dry-run", "-o", "json"], tmp_path)
    assert run.rc == 0, (run.stdout, run.stderr)
    assert run.cap is None and run.warnings == []


def test_ac11_the_letter32_config_is_the_expected_value() -> None:
    assert _alloc_px(LETTER, dpi=400) == 14_960_000
    assert render_workers(14_960_000, requested=8, work_items=32) == 8


# --------------------------------------------------------------------------- #
# AC12 -- landing registers
# --------------------------------------------------------------------------- #


def test_ac12_the_changelog_carries_a_pdf140_entry_naming_the_minor_release_candidate() -> None:
    text = (REPO_ROOT / "changelog.md").read_text(encoding="utf-8")
    anchor_end = text.index("\n", text.index("<!-- CHANGELOG-ANCHOR")) + 1
    match = re.search(
        r"^## \[PDF-140\] .+ — \d{4}-\d{2}-\d{2}$", text[anchor_end:], flags=re.MULTILINE
    )
    assert match, "no ## [PDF-140] entry below the anchor"
    entry = text[anchor_end + match.end() :].split("\n## ", 1)[0]
    assert "minor-release candidate" in entry
    assert "Targets ledger" in entry
    assert "Closes ledger" not in entry
