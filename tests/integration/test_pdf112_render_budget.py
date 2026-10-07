"""PDF-112 / X-1002 -- the render is bounded.

One pure function sizes a page's bitmap (``ports.raster.page_pixels``), one
comparison refuses an over-budget page (``enforce_render_budget``), and the
adapter, the ``rasterize`` planner and the ``ocr`` planner all call them before
anything is allocated or written. Fixtures are built module-locally with
pikepdf (each at most 2 KB, none ever materialises an over-budget bitmap); the
shared corpus is untouched.

The RLIMIT_AS arms skip off Linux -- they are never counted as a pass there.
"""

from __future__ import annotations

import json
import math
import re
import resource
import subprocess
import sys
from pathlib import Path

import pikepdf
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from fs_snapshot import redirected_environment  # noqa: E402
from pdf_tooling.errors import RefusedError, RenderBudgetError  # noqa: E402
from pdf_tooling.ports.raster import (  # noqa: E402
    DPI_CEILING,
    PIXEL_BUDGET,
    WIDTH_CEILING,
    enforce_render_budget,
    page_pixels,
)
from registry import REPO_ROOT, console_script  # noqa: E402

pytestmark = pytest.mark.e2e

_ONE_GIB = 1 << 30


# --------------------------------------------------------------------------- #
# Module-local fixtures
# --------------------------------------------------------------------------- #


def _build(
    path: Path,
    box: tuple[float, float, float, float],
    *,
    rotate: int | None = None,
    crop: tuple[float, float, float, float] | None = None,
    user_unit: float | None = None,
    text: bool = False,
    encryption: pikepdf.Encryption | None = None,
) -> Path:
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(100, 100))
    page.MediaBox = list(box)
    if rotate is not None:
        page.Rotate = rotate
    if crop is not None:
        page.CropBox = list(crop)
    if user_unit is not None:
        page.UserUnit = user_unit
    if text:
        font = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica
            )
        )
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.Contents = pdf.make_stream(b"BT /F1 24 Tf 72 72 Td (hello budget) Tj ET")
    pdf.save(path, encryption=encryption) if encryption else pdf.save(path)
    return path


@pytest.fixture(scope="module")
def fx(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("pdf112")
    return {
        "huge": _build(d / "huge.pdf", (0, 0, 14400, 14400)),
        "giant": _build(d / "giant.pdf", (0, 0, 1e7, 1e7)),
        "wide_short": _build(d / "wide_short.pdf", (0, 0, 14400, 10)),
        "rot90_huge": _build(d / "rot90_huge.pdf", (0, 0, 14400, 7200), rotate=90),
        "crop_small_media_huge": _build(
            d / "crop_small_media_huge.pdf", (0, 0, 14400, 14400), crop=(0, 0, 100, 100)
        ),
        "uu10": _build(d / "uu10.pdf", (0, 0, 612, 792), user_unit=10),
        "huge_text": _build(d / "huge_text.pdf", (0, 0, 14400, 14400), text=True),
        "a0": _build(d / "a0.pdf", (0, 0, 2383.937, 3370.394)),
        "a4": _build(d / "a4.pdf", (0, 0, 595.276, 841.89)),
        "letter": _build(d / "letter.pdf", (0, 0, 612, 792)),
        "huge_enc": _build(
            d / "huge_enc.pdf",
            (0, 0, 14400, 14400),
            encryption=pikepdf.Encryption(user="u", owner="o", R=6),
        ),
    }


def _run(
    args: list[str],
    tmp_path: Path,
    *,
    cap: int | None = None,
) -> subprocess.CompletedProcess[str]:
    env, _roots = redirected_environment(tmp_path / "env")
    for key in ("TMPDIR", "HOME"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)

    def _limit() -> None:  # pragma: no cover - runs in the child
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))  # type: ignore[arg-type]

    return subprocess.run(
        [*console_script(), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
        env=env,
        preexec_fn=_limit if cap is not None else None,  # noqa: PLW1509
    )


def _need_rlimit() -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip(f"RLIMIT_AS is not enforced on {sys.platform}")


def _tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")) if root.exists() else []


def _assert_refused_envelope(result: subprocess.CompletedProcess[str], path: Path) -> dict:
    assert result.returncode == 5, (result.returncode, result.stdout, result.stderr)
    assert "Traceback" not in result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert set(payload) == {"schema_version", "error"}
    assert payload["error"]["code"] == 5
    assert payload["error"]["kind"] == "refused"
    assert Path(payload["error"]["path"]).samefile(path)
    return payload


# --------------------------------------------------------------------------- #
# AC1 / AC3 -- rasterize refuses before allocation; dry predicts it
# --------------------------------------------------------------------------- #


def test_ac1_rasterize_refuses_an_oversized_page_before_allocation(
    fx: dict[str, Path], tmp_path: Path
) -> None:
    _need_rlimit()
    out = tmp_path / "D"
    result = _run(
        ["rasterize", str(fx["huge"]), "--threads", "1", "--out-dir", str(out), "-o", "json"],
        tmp_path,
        cap=_ONE_GIB,
    )
    _assert_refused_envelope(result, fx["huge"])
    assert not out.exists() or list(out.iterdir()) == []
    _env, roots = redirected_environment(tmp_path / "env")
    assert [list(root.iterdir()) for root in roots] == [[], []], "a temp file was left behind"
    redirected = {root.relative_to(tmp_path).parts[0] for root in roots}
    assert [p for p in _tree(tmp_path) if p.split("/")[0] not in redirected | {"env"}] == []


def test_ac3_rasterize_dry_run_predicts_the_same_refusal_byte_for_byte(
    fx: dict[str, Path], tmp_path: Path
) -> None:
    base = [
        "rasterize",
        str(fx["huge"]),
        "--threads",
        "1",
        "--out-dir",
        str(tmp_path / "D"),
        "-o",
        "json",
    ]
    real = _run(base, tmp_path)
    dry = _run([*base, "--dry-run"], tmp_path)
    _assert_refused_envelope(dry, fx["huge"])
    assert dry.stdout == real.stdout


# --------------------------------------------------------------------------- #
# AC2 / AC3 -- ocr refuses (5 before 3), dry parity
# --------------------------------------------------------------------------- #


def test_ac2_ocr_refuses_the_same_page_before_allocation_and_before_the_engine(
    fx: dict[str, Path], tmp_path: Path
) -> None:
    _need_rlimit()
    out = tmp_path / "out.pdf"
    result = _run(["ocr", str(fx["huge"]), "-O", str(out), "-o", "json"], tmp_path, cap=_ONE_GIB)
    _assert_refused_envelope(result, fx["huge"])
    assert not out.exists()


def test_ac3_ocr_dry_run_predicts_the_same_refusal_byte_for_byte(
    fx: dict[str, Path], tmp_path: Path
) -> None:
    base = ["ocr", str(fx["huge"]), "-O", str(tmp_path / "out.pdf"), "-o", "json"]
    real = _run(base, tmp_path)
    dry = _run([*base, "--dry-run"], tmp_path)
    _assert_refused_envelope(dry, fx["huge"])
    assert dry.stdout == real.stdout


# --------------------------------------------------------------------------- #
# AC4 -- run-scoped in a batch, nothing written
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("order", [("a4", "huge"), ("huge", "a4")])
def test_ac4_rasterize_batch_is_refused_whole_and_writes_nothing(
    fx: dict[str, Path], tmp_path: Path, order: tuple[str, str]
) -> None:
    out = tmp_path / "D"
    result = _run(
        ["rasterize", *(str(fx[name]) for name in order), "--out-dir", str(out), "-o", "json"],
        tmp_path,
    )
    payload = _assert_refused_envelope(result, fx["huge"])
    assert "items" not in payload
    assert not out.exists() or list(out.iterdir()) == []


def test_ac4_ocr_batch_is_refused_whole_and_writes_nothing(
    fx: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "D"
    result = _run(
        ["ocr", str(fx["a4"]), str(fx["huge"]), "--out-dir", str(out), "-o", "json"], tmp_path
    )
    _assert_refused_envelope(result, fx["huge"])
    assert not out.exists() or list(out.iterdir()) == []


# --------------------------------------------------------------------------- #
# AC5 -- the pure function's boundary is exact and ceil-based
# --------------------------------------------------------------------------- #


def _refused(w: float, h: float, **kw: object) -> bool:
    pixels = page_pixels(w, h, **kw)  # type: ignore[arg-type]
    try:
        enforce_render_budget(
            pixels,
            page_number=1,
            path="p.pdf",
            dpi=kw.get("dpi"),  # type: ignore[arg-type]
            width_px=kw.get("width_px"),  # type: ignore[arg-type]
        )
    except RenderBudgetError:
        return True
    return False


def test_ac5_budget_boundary_is_exact_and_ceil_based() -> None:
    at = page_pixels(10000, 17895, dpi=72, width_px=None)
    assert at.alloc_pixels == 178_950_000
    assert not _refused(10000, 17895, dpi=72, width_px=None)
    assert _refused(10000, 17896, dpi=72, width_px=None)
    # `round` target is under budget, `ceil` allocation is over it.
    slack = page_pixels(10000.4, 17895, dpi=72, width_px=None)
    assert slack.target_width * slack.target_height <= PIXEL_BUDGET
    assert slack.alloc_pixels == 10001 * 17895 == 178_967_895
    assert _refused(10000.4, 17895, dpi=72, width_px=None)


def test_ac5_a_page_whose_allocation_equals_the_budget_exactly_is_legal() -> None:
    # Find a factorisation of PIXEL_BUDGET exactly, at 72 dpi (scale 1.0).
    for w in range(2, 100_000):
        if PIXEL_BUDGET % w == 0:
            h = PIXEL_BUDGET // w
            if w * h == PIXEL_BUDGET and w <= h:
                break
    else:  # pragma: no cover
        pytest.fail("no factorisation found")
    assert page_pixels(w, h, dpi=72, width_px=None).alloc_pixels == PIXEL_BUDGET
    assert not _refused(w, h, dpi=72, width_px=None)
    assert _refused(w, h + 1, dpi=72, width_px=None)


# --------------------------------------------------------------------------- #
# AC6 -- the function computes exactly what pdfium allocates
# --------------------------------------------------------------------------- #

_GEOMETRY = (
    "a4",
    "letter",
    "rot90_huge",
    "crop_small_media_huge",
    "uu10",
    "wide_short",
)


@pytest.mark.parametrize("name", _GEOMETRY)
def test_ac6_function_equals_pdfiums_real_allocation(
    fx: dict[str, Path], monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    import pypdfium2 as pdfium

    from pdf_tooling.adapters.pdfium_raster import ADAPTER, _displayed_size

    document = pdfium.PdfDocument(str(fx[name]))
    try:
        displayed = _displayed_size(document, 0)
        page = document.get_page(0)
        try:
            assert tuple(map(float, page.get_size())) == displayed
        finally:
            page.close()
    finally:
        document.close()

    # A dpi chosen so the bitmap is at most 4 MP.
    dpi = 72.0
    while page_pixels(*displayed, dpi=dpi, width_px=None).alloc_pixels > 4_000_000 and dpi > 0.01:
        dpi /= 2
    seen: list[tuple[int, int]] = []
    # `PdfPage.render` binds `PdfBitmap.new_native` as a default argument at
    # import time, so patching `new_native` never intercepts it. Its result is
    # built by `cls(raw, buffer, width, height, ...)`, so the constructor is
    # the seam that sees every allocation's (width, height).
    original_init = pdfium.PdfBitmap.__init__

    def spy(
        self: object, raw: object, buffer: object, width: int, height: int, *a: object, **k: object
    ) -> None:
        seen.append((width, height))
        original_init(self, raw, buffer, width, height, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(pdfium.PdfBitmap, "__init__", spy)
    try:
        ADAPTER.render_page(str(fx[name]), 1, dpi=dpi, width_px=None, grayscale=False)
    except Exception:
        pass  # a degenerate sliver may fail after allocation; the spy already captured it
    expected = page_pixels(*displayed, dpi=dpi, width_px=None)
    assert seen, "pdfium never allocated"
    assert seen[0] == (expected.alloc_width, expected.alloc_height), name


def test_ac6_userunit_is_not_applied_by_the_renderer(fx: dict[str, Path]) -> None:
    import pypdfium2 as pdfium

    from pdf_tooling.adapters.pdfium_raster import _displayed_size

    document = pdfium.PdfDocument(str(fx["uu10"]))
    try:
        assert _displayed_size(document, 0) == (612.0, 792.0)
    finally:
        document.close()


# --------------------------------------------------------------------------- #
# AC7 -- the chokepoint refuses before allocation, on every platform
# --------------------------------------------------------------------------- #


def test_ac7_the_chokepoint_refuses_before_pdfium_allocates(
    fx: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    import pypdfium2 as pdfium

    from pdf_tooling.adapters.pdfium_raster import ADAPTER

    def _boom(*_a: object, **_k: object) -> object:
        raise AssertionError("allocated")

    monkeypatch.setattr(pdfium.PdfBitmap, "new_native", classmethod(_boom))
    monkeypatch.setattr(pdfium.PdfBitmap, "__init__", _boom)
    monkeypatch.setattr(pdfium.PdfPage, "render", _boom)
    with pytest.raises(RenderBudgetError):
        ADAPTER.render_page(str(fx["huge"]), 1, dpi=150.0, width_px=None, grayscale=False)


def test_ac7_the_planner_pre_empts_the_chokepoint(
    fx: dict[str, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pdf_tooling.adapters import pdfium_raster
    from pdf_tooling.ops.raster import rasterize_document
    from pdf_tooling.safety.policy import SafetyPolicy

    measured: list[int] = []
    chokepoint: list[int] = []
    real_measure = pdfium_raster.ADAPTER.measure_pages
    real_enforce = pdfium_raster.enforce_render_budget

    def measure(*args: object, **kwargs: object) -> object:
        measured.append(1)
        return real_measure(*args, **kwargs)  # type: ignore[arg-type]

    def enforce(*args: object, **kwargs: object) -> None:
        chokepoint.append(1)
        real_enforce(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pdfium_raster.ADAPTER, "measure_pages", measure, raising=False)
    monkeypatch.setattr(pdfium_raster, "enforce_render_budget", enforce)
    policy = SafetyPolicy(
        dry_run=False,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )
    with pytest.raises(RenderBudgetError):
        rasterize_document(
            [fx["huge"]],
            pages_spec=None,
            dpi=150.0,
            width_px=None,
            fmt="png",
            quality=None,
            grayscale=False,
            name_template=None,
            out_dir=tmp_path / "out",
            policy=policy,
        )
    assert measured == [1]
    assert chokepoint == [], "the chokepoint was reached; the planner did not pre-empt it"


# --------------------------------------------------------------------------- #
# AC8 -- the message is actionable and its advice is true
# --------------------------------------------------------------------------- #


def _message(w: float, h: float, **kw: object) -> str:
    pixels = page_pixels(w, h, **{k: v for k, v in kw.items() if k in ("dpi", "width_px")})  # type: ignore[arg-type]
    with pytest.raises(RenderBudgetError) as caught:
        enforce_render_budget(pixels, page_number=1, path="huge.pdf", **kw)  # type: ignore[arg-type]
    return str(caught.value)


def test_ac8_message_names_page_size_budget_and_the_true_largest_dpi() -> None:
    message = _message(14400, 14400, dpi=150.0, width_px=None)
    for needle in (
        "page 1",
        "30,001x30,001",  # ceil(14400 * (150/72)) -- 30000.000000000004 in IEEE-754
        "178,956,970",
        "the largest --dpi that fits this page is 66",
    ):
        assert needle in message, message
    best = int(re.search(r"is (\d+)$", message).group(1))  # type: ignore[union-attr]
    assert page_pixels(14400, 14400, dpi=float(best), width_px=None).alloc_pixels <= PIXEL_BUDGET
    assert page_pixels(14400, 14400, dpi=float(best + 1), width_px=None).alloc_pixels > PIXEL_BUDGET


def test_ac8_width_mode_names_a_true_largest_width() -> None:
    message = _message(14400, 14400, dpi=None, width_px=20000)
    assert "the largest --width that fits is" in message
    best = int(message.rsplit(" ", 1)[1].replace(",", ""))
    assert page_pixels(14400, 14400, dpi=None, width_px=best).alloc_pixels <= PIXEL_BUDGET
    assert page_pixels(14400, 14400, dpi=None, width_px=best + 1).alloc_pixels > PIXEL_BUDGET


def test_ac8_advice_survives_ceil_slack_where_the_closed_form_would_not() -> None:
    # Search a page where int(72*sqrt(B/(w*h))) allocates over budget.
    found = None
    for w in range(7000, 9000, 7):
        for h in (w + 1, w + 3, w + 11):
            closed = int(72 * math.sqrt(PIXEL_BUDGET / (w * h)))
            if (
                closed >= 1
                and page_pixels(w, h, dpi=float(closed), width_px=None).alloc_pixels > PIXEL_BUDGET
            ):
                found = (w, h, closed)
                break
        if found:
            break
    if found is None:
        pytest.skip("no ceil-slack case in range")
    w, h, closed = found
    message = _message(w, h, dpi=float(closed + 1000), width_px=None)
    best = int(re.search(r"is (\d+)$", message).group(1))  # type: ignore[union-attr]
    assert best != closed
    assert page_pixels(w, h, dpi=float(best), width_px=None).alloc_pixels <= PIXEL_BUDGET


def test_ac8_giant_page_has_no_acceptable_dpi() -> None:
    assert "no --dpi this command accepts fits this page" in _message(
        1e7, 1e7, dpi=150.0, width_px=None
    )


def test_ac8_ocr_never_advises_a_dpi_below_its_floor() -> None:
    message = _message(1e7, 1e7, dpi=300.0, width_px=None, dpi_floor=72.0)
    assert "no --dpi this command accepts fits this page" in message
    # a page whose largest fitting dpi (66) is below ocr's floor of 72
    message = _message(14400, 14400, dpi=300.0, width_px=None, dpi_floor=72.0)
    assert "no --dpi this command accepts" in message
    assert "is 66" not in message


# --------------------------------------------------------------------------- #
# AC9 -- ocr budgets only the pages it renders
# --------------------------------------------------------------------------- #


def test_ac9_skip_text_pages_does_not_budget_an_unrendered_page(
    fx: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "out.pdf"
    ok = _run(
        ["ocr", str(fx["huge_text"]), "--skip-text-pages", "-O", str(out), "-o", "json"], tmp_path
    )
    assert ok.returncode == 0, (ok.stdout, ok.stderr)
    assert out.exists()
    refused = _run(
        ["ocr", str(fx["huge_text"]), "-O", str(tmp_path / "o2.pdf"), "-o", "json"], tmp_path
    )
    assert refused.returncode == 5, (refused.stdout, refused.stderr)


# --------------------------------------------------------------------------- #
# AC10 -- the static ceilings
# --------------------------------------------------------------------------- #


def _dry(fx: dict[str, Path], name: str, tmp_path: Path, *flags: str) -> int:
    return _run(
        [
            "rasterize",
            str(fx[name]),
            "--dry-run",
            "-o",
            "json",
            "--out-dir",
            str(tmp_path / "o"),
            *flags,
        ],
        tmp_path,
    ).returncode


def test_ac10_static_ceilings(fx: dict[str, Path], tmp_path: Path) -> None:
    assert _dry(fx, "wide_short", tmp_path, "--dpi", f"{DPI_CEILING:g}") == 0
    assert _dry(fx, "a4", tmp_path, "--dpi", f"{DPI_CEILING:g}") == 5
    for bad in ("2400.0001", "nan", "inf"):
        assert _dry(fx, "a4", tmp_path, "--dpi", bad) == 2, bad
    assert _dry(fx, "wide_short", tmp_path, "--width", str(WIDTH_CEILING)) == 0
    assert _dry(fx, "a4", tmp_path, "--width", str(WIDTH_CEILING + 1)) == 2
    assert _dry(fx, "a4", tmp_path, "--dpi", "0") == 2
    assert _dry(fx, "a4", tmp_path, "--width", "0") == 2


# --------------------------------------------------------------------------- #
# AC11 -- legal controls
# --------------------------------------------------------------------------- #


def test_ac11_legal_controls_are_under_budget_and_dry_run_clean(
    fx: dict[str, Path], tmp_path: Path
) -> None:
    assert page_pixels(2383.937, 3370.394, dpi=300.0, width_px=None).alloc_pixels <= PIXEL_BUDGET
    assert page_pixels(595.276, 841.89, dpi=1200.0, width_px=None).alloc_pixels <= PIXEL_BUDGET
    assert page_pixels(612, 792, dpi=1200.0, width_px=None).alloc_pixels <= PIXEL_BUDGET
    assert _dry(fx, "a0", tmp_path, "--dpi", "300") == 0
    assert _dry(fx, "a4", tmp_path, "--dpi", "1200") == 0


def test_ac11_a4_at_300_dpi_renders_unchanged(fx: dict[str, Path], tmp_path: Path) -> None:
    out = tmp_path / "o"
    result = _run(
        ["rasterize", str(fx["a4"]), "--dpi", "300", "--out-dir", str(out), "-o", "json"], tmp_path
    )
    assert result.returncode == 0, result.stderr
    messages = [item["message"] for item in json.loads(result.stdout)["items"]]
    assert messages == ["page 1: 2480x3508 png @ 300 dpi"]


def test_a_crop_box_governs_so_a_huge_media_box_with_a_small_crop_passes(
    fx: dict[str, Path], tmp_path: Path
) -> None:
    assert _dry(fx, "crop_small_media_huge", tmp_path) == 0


# --------------------------------------------------------------------------- #
# AC12 -- documented where the user reads it, derived not transcribed
# --------------------------------------------------------------------------- #


def test_ac12_help_names_the_budget_and_ceilings(tmp_path: Path) -> None:
    result = _run(["rasterize", "--help"], tmp_path)
    text = " ".join(result.stdout.split())
    assert f"{PIXEL_BUDGET:,}" in text
    assert f"{DPI_CEILING:g}" in text
    assert str(WIDTH_CEILING) in text
    assert "exit 5" in text


# --------------------------------------------------------------------------- #
# AC13 -- frozen surface
# --------------------------------------------------------------------------- #


def test_ac13_the_error_class_is_additive() -> None:
    assert issubclass(RenderBudgetError, RefusedError)
    assert RenderBudgetError.exit_code == 5
    assert "kind" not in RenderBudgetError.__dict__
    assert "__init__" not in RenderBudgetError.__dict__
    from pdf_tooling.ops.batch import ITEM_SCOPED_ERRORS

    assert RenderBudgetError not in ITEM_SCOPED_ERRORS


def test_encrypted_oversized_source_is_authenticated_before_it_is_measured(
    fx: dict[str, Path], tmp_path: Path
) -> None:
    result = _run(
        [
            "rasterize",
            str(fx["huge_enc"]),
            "--dry-run",
            "-o",
            "json",
            "--out-dir",
            str(tmp_path / "o"),
        ],
        tmp_path,
    )
    assert result.returncode == 6, (result.stdout, result.stderr)


def test_module_is_not_importing_the_env_for_the_override() -> None:
    # X-1002: there is no override of any kind.
    source = (REPO_ROOT / "src" / "pdf_tooling" / "ports" / "raster.py").read_text()
    assert "environ" not in source and "getenv" not in source


def test_a3_at_1200_dpi_is_over_budget_so_ocr_dpi_1200_on_a3_is_refused() -> None:
    assert _refused(841.89, 1190.551, dpi=1200.0, width_px=None)
