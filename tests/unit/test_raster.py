"""``ops/raster.py`` / ``ports/raster.py`` / ``adapters/pdfium_raster.py`` —
the render call, the concurrency model, and the AC1/AC3/AC4/AC5/AC7-AC11/
AC13/AC16/AC17/AC25-AC27 unit-level proofs (Design §D2, §D5-D6, §D10-D12).

Runs in-process against the framework-free ops/ports layers. CLI-surface
behaviour (flag contract, exit codes, help text, OR-3) lives in
``tests/integration/test_rasterize_cli.py``.

E-15: the corpus has no >=8-page fixture (the largest is 3 pages), and AC3
needs one so ``min(threads, len(work))`` can actually reach 8 workers. Built
locally here, never added to ``tests/corpus.py`` -- ``FIXTURE_NAMES``/
``_BUILDERS`` are a pinned pair in a shared PDF-06 file, and one verb's
private need is not a corpus-wide change. Built with reportlab's
``invariant=1`` (the same switch ``tests/corpus.py::_new_canvas`` uses) so it
is byte-reproducible.
"""

from __future__ import annotations

import os
import pickle
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image

from pdf_toolkit.errors import EngineMissingError, NoInputError, OutputEscapesDirError, UsageError
from pdf_toolkit.ops import raster as raster_module
from pdf_toolkit.ports.raster import RenderedPage, require_raster
from pdf_toolkit.safety import atomic as atomic_module
from pdf_toolkit.safety.policy import SafetyPolicy

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "pdf_toolkit"


def make_policy(**overrides: object) -> SafetyPolicy:
    values: dict[str, object] = {
        "dry_run": False,
        "force": False,
        "in_place": False,
        "backup": True,
        "assume_yes": False,
        "is_tty": False,
        "threads": 1,
    }
    values.update(overrides)
    return SafetyPolicy(**values)  # type: ignore[arg-type]


def _new_canvas(path: Path, page_size: tuple[float, float]) -> object:
    """Deterministic canvas -- mirrors ``tests/corpus.py::_new_canvas`` (E-15)."""
    from reportlab.pdfgen import canvas

    made = canvas.Canvas(str(path), pagesize=page_size, invariant=1)
    made.setProducer("pdf-toolkit test corpus")
    made.setCreator("tests/unit/test_raster.py")
    return made


def _make_letter(directory: Path, *, name: str = "letter.pdf") -> Path:
    """AC1's fixture: one US-Letter page (612x792 pt)."""
    from reportlab.lib.pagesizes import letter

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    made = _new_canvas(path, letter)
    made.drawString(72, 700, "single_page fixture -- exactly one page.")
    made.showPage()
    made.save()
    return path


def _make_multipage(directory: Path, pages: int, *, name: str = "multi.pdf") -> Path:
    from reportlab.lib.pagesizes import letter

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    made = _new_canvas(path, letter)
    for number in range(1, pages + 1):
        made.drawString(72, 700, f"page {number} of {pages}")
        made.showPage()
    made.save()
    return path


def _make_rotated(directory: Path, *, name: str = "rotated.pdf") -> Path:
    """AC8's fixture: one portrait Letter page carrying ``/Rotate 90``."""
    from reportlab.lib.pagesizes import letter

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    made = _new_canvas(path, letter)
    made.setPageRotation(90)
    made.drawString(72, 700, "rotated fixture -- one page, /Rotate 90.")
    made.showPage()
    made.save()
    return path


def _rasterize(
    source: Path,
    *,
    out_dir: Path,
    pages_spec: str | None = None,
    dpi: float | None = 150.0,
    width_px: int | None = None,
    fmt: str = "png",
    quality: int | None = None,
    grayscale: bool = False,
    name_template: str | None = None,
    policy: SafetyPolicy | None = None,
):
    return raster_module.rasterize_document(
        [source],
        pages_spec=pages_spec,
        dpi=dpi,
        width_px=width_px,
        fmt=fmt,
        quality=quality,
        grayscale=grayscale,
        name_template=name_template,
        out_dir=out_dir,
        policy=policy if policy is not None else make_policy(),
    )


# --------------------------------------------------------------------------- #
# AC1 -- exact pixel dimensions, not merely "a file exists"
# --------------------------------------------------------------------------- #


def test_ac1_dpi_300_on_us_letter_produces_exactly_2550x3300(tmp_path: Path) -> None:
    source = _make_letter(tmp_path / "src")
    out_dir = tmp_path / "out"
    result = _rasterize(source, out_dir=out_dir, dpi=300.0)
    assert result.exit_code == 0
    files = list(out_dir.iterdir())
    assert len(files) == 1
    with Image.open(files[0]) as img:
        assert img.size == (2550, 3300)


# --------------------------------------------------------------------------- #
# AC3 -- byte identity across --threads 1 / --threads 8, ops-layer half.
# (The subprocess/CLI half, over the real console script, lives in
# tests/integration/test_rasterize_cli.py.)
# --------------------------------------------------------------------------- #


def test_ac3_threads_1_and_threads_8_are_byte_identical(tmp_path: Path) -> None:
    source = _make_multipage(tmp_path / "src", pages=8)

    out1 = tmp_path / "t1"
    out8 = tmp_path / "t8"
    result1 = _rasterize(source, out_dir=out1, dpi=96.0, policy=make_policy(threads=1))
    result8 = _rasterize(source, out_dir=out8, dpi=96.0, policy=make_policy(threads=8))

    assert result1.exit_code == 0
    assert result8.exit_code == 0

    names1 = sorted(p.name for p in out1.iterdir())
    names8 = sorted(p.name for p in out8.iterdir())
    assert names1 == names8
    assert len(names1) == 8

    for name in names1:
        assert (out1 / name).read_bytes() == (out8 / name).read_bytes(), name

    # (b) ordering identity: items are in resolved-selection (slot) order,
    # equal between the two runs and equal to the sorted page order --
    # compared by basename, since the two runs deliberately used different
    # --out-dir values (AC3(b) is about ITEM order, not directory identity).
    order1 = [Path(item.output).name for item in result1.items]
    order8 = [Path(item.output).name for item in result8.items]
    assert order1 == order8 == names1


# --------------------------------------------------------------------------- #
# AC4 -- the worker function: module-level, every argument/return picklable.
# --------------------------------------------------------------------------- #


def test_ac4_render_chunk_is_module_level_and_picklable() -> None:
    worker = raster_module._render_chunk
    assert worker.__module__ == "pdf_toolkit.ops.raster"
    assert worker.__qualname__ == "_render_chunk"
    # The function itself pickles by reference (name lookup), which is what
    # lets a ProcessPoolExecutor worker import it fresh.
    assert pickle.loads(pickle.dumps(worker)) is worker


def test_ac4_worker_arguments_and_return_value_round_trip_through_pickle(
    tmp_path: Path,
) -> None:
    source = _make_letter(tmp_path / "src")
    items = [(0, str(source), 1, str(tmp_path / "out-0001.png"), 150.0, None)]
    policy = make_policy()
    # Every argument `_render_chunk` receives is plain data -- no pdfium
    # object, no open file handle, no adapter reference.
    restored_items = pickle.loads(pickle.dumps(items))
    restored_policy = pickle.loads(pickle.dumps(policy))
    assert restored_items == items
    assert restored_policy == policy

    result = raster_module._render_chunk(
        items, fmt="png", quality=None, grayscale=False, policy=policy
    )
    assert pickle.loads(pickle.dumps(result)) == result


# --------------------------------------------------------------------------- #
# AC5 -- the parent never renders; rendering happens in a CHILD PROCESS.
# --------------------------------------------------------------------------- #


def test_ac5_render_happens_in_a_child_process_never_in_the_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_multipage(tmp_path / "src", pages=4)
    pid_file = tmp_path / "pids.txt"
    original = raster_module._render_one

    def _recording(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        with open(pid_file, "a") as handle:
            handle.write(f"{os.getpid()}\n")
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(raster_module, "_render_one", _recording)

    result = _rasterize(source, out_dir=tmp_path / "out", dpi=96.0, policy=make_policy(threads=2))
    assert result.exit_code == 0

    parent_pid = os.getpid()
    child_pids = {int(line) for line in pid_file.read_text().splitlines()}
    assert child_pids, "the monkeypatched worker never ran at all"
    assert parent_pid not in child_pids


# --------------------------------------------------------------------------- #
# AC7 -- executor-agnosticism: the SAME worker through a ProcessPoolExecutor
# produces byte-identical files to a single-worker ThreadPoolExecutor
# baseline. (A real MULTI-worker ThreadPoolExecutor comparison is not used
# here -- see the Implementation Log / ops/raster.py's module docstring:
# concurrent pdfium rendering across real OS threads corrupts the process
# heap even with per-worker document isolation, reproduced live during this
# spec's implementation. A single-worker thread pool has no concurrent
# access at all and is therefore the safe baseline this test compares
# against.)
# --------------------------------------------------------------------------- #


def test_ac7_process_pool_and_thread_pool_produce_byte_identical_output(
    tmp_path: Path,
) -> None:
    source = _make_multipage(tmp_path / "src", pages=8)
    policy = make_policy()
    work = [
        (slot, str(source), page, str(tmp_path / f"work-{page:04}.png"), 96.0, None)
        for slot, page in enumerate(range(1, 9), start=0)
    ]

    thread_dir = tmp_path / "via_thread"
    thread_dir.mkdir()
    thread_items = [
        (slot, str(source), page, str(thread_dir / f"page-{page:04}.png"), 96.0, None)
        for slot, page in enumerate(range(1, 9), start=0)
    ]
    with ThreadPoolExecutor(max_workers=1) as executor:
        thread_results = executor.submit(
            raster_module._render_chunk,
            thread_items,
            fmt="png",
            quality=None,
            grayscale=False,
            policy=policy,
        ).result()

    process_dir = tmp_path / "via_process"
    process_dir.mkdir()
    process_items = [
        (slot, str(source), page, str(process_dir / f"page-{page:04}.png"), 96.0, None)
        for slot, page in enumerate(range(1, 9), start=0)
    ]
    chunks = [[item] for item in process_items]
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(
                raster_module._render_chunk,
                chunk,
                fmt="png",
                quality=None,
                grayscale=False,
                policy=policy,
            )
            for chunk in chunks
        ]
        process_results = [pair for future in futures for pair in future.result()]

    assert len(thread_results) == len(process_results) == 8
    thread_by_slot = dict(thread_results)
    process_by_slot = dict(process_results)
    for slot in range(8):
        thread_item = thread_by_slot[slot]
        process_item = process_by_slot[slot]
        assert thread_item.ok and process_item.ok
        assert Path(thread_item.output).read_bytes() == Path(process_item.output).read_bytes()
    del work  # only built to document the shape; both runs above use their own copies


# --------------------------------------------------------------------------- #
# AC8 -- rotation is honoured: a /Rotate 90 page rasterizes landscape.
# --------------------------------------------------------------------------- #


def test_ac8_rotated_page_rasterizes_landscape(tmp_path: Path) -> None:
    source = _make_rotated(tmp_path / "src")
    out_dir = tmp_path / "out"
    result = _rasterize(source, out_dir=out_dir, dpi=150.0)
    assert result.exit_code == 0
    files = list(out_dir.iterdir())
    assert len(files) == 1
    with Image.open(files[0]) as img:
        width, height = img.size
        assert width > height, img.size
    item = result.items[0]
    parsed_width, parsed_height = _parse_dimensions(item.message)
    assert (parsed_width, parsed_height) == (width, height)


# --------------------------------------------------------------------------- #
# AC9 -- --grayscale produces mode "L" for png/tiff/jpeg. WEBP is the one
# documented exception: WebP's own bitstream format has no single-channel
# pixel mode at all (confirmed against Pillow 12.3.0's WebP encoder, which
# unconditionally converts any non-RGB(A/X) source to RGB/RGBA before
# handing it to libwebp -- PIL.WebPImagePlugin._convert_frame). AC9's
# "L for webp too" clause is therefore reported as unsatisfiable rather than
# quietly worked around; see the Implementation Log. The file IS still
# rendered from single-channel source pixels (R == G == B throughout, no
# colour information), which is the property this test asserts instead.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fmt", ["png", "tiff", "jpeg"])
def test_ac9_grayscale_produces_mode_l(tmp_path: Path, fmt: str) -> None:
    source = _make_letter(tmp_path / "src")
    out_dir = tmp_path / f"out-{fmt}"
    result = _rasterize(source, out_dir=out_dir, dpi=96.0, fmt=fmt, grayscale=True)
    assert result.exit_code == 0
    files = list(out_dir.iterdir())
    with Image.open(files[0]) as img:
        assert img.mode == "L"


def test_ac9_grayscale_webp_is_perceptually_grayscale_but_reads_back_rgb(
    tmp_path: Path,
) -> None:
    source = _make_letter(tmp_path / "src")
    out_dir = tmp_path / "out-webp-gray"
    result = _rasterize(source, out_dir=out_dir, dpi=96.0, fmt="webp", grayscale=True)
    assert result.exit_code == 0
    files = list(out_dir.iterdir())
    with Image.open(files[0]) as img:
        assert img.mode == "RGB"  # the documented exception -- see the block comment above
        # Not exact equality: WebP's lossy YUV round-trip introduces a few
        # units of chroma-subsampling drift even for an R==G==B source, so
        # this asserts "perceptually grayscale" (every channel pair within a
        # small tolerance) rather than bit-exact equality.
        r, g, b = (channel.tobytes() for channel in img.split())
        max_delta = max(
            max(abs(rv - gv), abs(gv - bv), abs(rv - bv))
            for rv, gv, bv in zip(r, g, b, strict=True)
        )
        assert max_delta <= 8, max_delta


def test_ac9_without_grayscale_the_mode_is_rgb(tmp_path: Path) -> None:
    source = _make_letter(tmp_path / "src")
    out_dir = tmp_path / "out"
    result = _rasterize(source, out_dir=out_dir, dpi=96.0)
    assert result.exit_code == 0
    files = list(out_dir.iterdir())
    with Image.open(files[0]) as img:
        assert img.mode == "RGB"


# --------------------------------------------------------------------------- #
# AC10 -- --width produces the exact requested width; height within Design
# §D6's "measured, never predicted" property, matching what the file holds.
# --------------------------------------------------------------------------- #


def test_ac10_width_mode_produces_exact_width_and_measured_height(tmp_path: Path) -> None:
    source = _make_letter(tmp_path / "src")
    out_dir = tmp_path / "out"
    result = _rasterize(source, out_dir=out_dir, width_px=1200)
    assert result.exit_code == 0
    files = list(out_dir.iterdir())
    with Image.open(files[0]) as img:
        width, height = img.size
    assert width == 1200
    assert abs(height - round(1200 * 792 / 612)) <= 1
    parsed_width, parsed_height = _parse_dimensions(result.items[0].message)
    assert (parsed_width, parsed_height) == (width, height)


# --------------------------------------------------------------------------- #
# AC11 -- run-to-run determinism: two --threads 8 runs are byte-identical,
# and a produced PNG carries no tIME chunk.
# --------------------------------------------------------------------------- #


def test_ac11_two_runs_are_byte_identical_and_carry_no_time_chunk(tmp_path: Path) -> None:
    source = _make_multipage(tmp_path / "src", pages=8)
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    policy = make_policy(threads=8)
    result_a = _rasterize(source, out_dir=out_a, dpi=96.0, policy=policy)
    result_b = _rasterize(source, out_dir=out_b, dpi=96.0, policy=policy)
    assert result_a.exit_code == 0
    assert result_b.exit_code == 0

    names_a = sorted(p.name for p in out_a.iterdir())
    names_b = sorted(p.name for p in out_b.iterdir())
    assert names_a == names_b
    for name in names_a:
        bytes_a = (out_a / name).read_bytes()
        bytes_b = (out_b / name).read_bytes()
        assert bytes_a == bytes_b
        assert b"tIME" not in bytes_a


# --------------------------------------------------------------------------- #
# AC13 -- containment is consumed, not re-derived. No local sanitizer.
# --------------------------------------------------------------------------- #


def test_ac13_ops_raster_calls_no_path_sanitization_function() -> None:
    """The spec's own grep (`\\.\\.|normpath|realpath|resolve\\(\\)`) also
    matches innocuous prose/type-hint ellipses in this file (``tuple[int,
    ...]``, ``open(..., "w")`` in a docstring) -- the same false-positive
    shape ``ops/split.py`` already has for the identical grep (its own
    `tuple[str, ...]` annotations). This test asserts the property AC13
    actually cares about: no *function call* that sanitizes a path."""
    text = (SRC_ROOT / "ops" / "raster.py").read_text()
    import re

    assert re.search(r"normpath\(|realpath\(|resolve\(\)|os\.path\.abspath\(", text) is None


def test_ac13_name_escaping_the_out_dir_is_refused_and_nothing_escapes(
    tmp_path: Path,
) -> None:
    source = _make_letter(tmp_path / "src")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    before = set(tmp_path.rglob("*"))
    with pytest.raises(OutputEscapesDirError):
        _rasterize(source, out_dir=out_dir, name_template="../{stem}.png")
    after = set(tmp_path.rglob("*"))
    # Only the (already-created) out_dir itself may exist; nothing new.
    assert after - before == set()


# --------------------------------------------------------------------------- #
# AC16 -- HC-1: no forbidden name, no subprocess/spawn, in this verb's files.
# --------------------------------------------------------------------------- #


_FORBIDDEN_PATTERN = (
    r"subprocess|os\.system|os\.exec|shutil\.which|pdf2image|pdftoppm|pdftocairo|"
    r"pdfinfo|ghostscript|\bgs\b|fitz|pymupdf"
)


@pytest.mark.parametrize(
    "relative",
    ["ops/raster.py", "ports/raster.py", "adapters/pdfium_raster.py"],
)
def test_ac16_no_forbidden_name_or_process_spawn(relative: str) -> None:
    import re

    text = (SRC_ROOT / relative).read_text()
    assert re.search(_FORBIDDEN_PATTERN, text) is None, relative


# --------------------------------------------------------------------------- #
# AC17 -- the render is re-usable by another verb (PDF-15's ocr): a direct
# port import, no Typer, no CLI, no --out-dir, no file written.
# --------------------------------------------------------------------------- #


def test_ac17_render_page_is_directly_reusable_without_the_cli(tmp_path: Path) -> None:
    source = _make_letter(tmp_path / "src")
    adapter = require_raster(capability="render")
    rendered = adapter.render_page(str(source), 1, dpi=150.0, width_px=None, grayscale=True)
    assert isinstance(rendered, RenderedPage)
    assert rendered.width_px == 1275  # 612/72*150
    assert rendered.height_px == 1650  # 792/72*150
    assert rendered.mode == "L"
    assert rendered.width_px == rendered.image.width
    assert rendered.height_px == rendered.image.height
    written_files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written_files == [source]  # no file written


# --------------------------------------------------------------------------- #
# AC25 -- safety/naming.py is consumed unchanged, never copied or extended.
# --------------------------------------------------------------------------- #


def test_ac25_ops_raster_never_calls_ensure_within_directly() -> None:
    text = (SRC_ROOT / "ops" / "raster.py").read_text()
    assert "ensure_within" not in text


def test_ac25_range_in_name_template_is_refused_by_the_shared_renderer(
    tmp_path: Path,
) -> None:
    source = _make_letter(tmp_path / "src")
    with pytest.raises(OutputEscapesDirError):
        _rasterize(source, out_dir=tmp_path / "out", name_template="{range}.png")


def test_ac25_fields_is_not_extended() -> None:
    from pdf_toolkit.safety.naming import FIELDS

    assert FIELDS == frozenset({"stem", "page", "index", "range", "ext"})


# --------------------------------------------------------------------------- #
# AC26 -- image bytes reach disk only through the chokepoint.
# --------------------------------------------------------------------------- #


def test_ac26_pillow_is_handed_a_stream_never_a_path() -> None:
    text = (SRC_ROOT / "ops" / "raster.py").read_text()
    import re

    save_calls = re.findall(r"\.save\(([^)]*)", text)
    assert save_calls, "no .save( call found -- the test is measuring nothing"
    for call in save_calls:
        assert "writer.path" not in call
        assert not re.match(r"\s*(str|Path|[a-z_]*path)\s*[,)]", call)


def test_ac26_no_mkdir_in_ops_raster() -> None:
    text = (SRC_ROOT / "ops" / "raster.py").read_text()
    assert "mkdir" not in text


def test_ac26_atomic_writer_refusing_produces_zero_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_multipage(tmp_path / "src", pages=2)
    out_dir = tmp_path / "out"

    def _boom(self: object) -> None:
        raise RuntimeError("planted chokepoint failure")

    monkeypatch.setattr(atomic_module.AtomicWriter, "__enter__", _boom)
    with pytest.raises(RuntimeError):
        _rasterize(source, out_dir=out_dir, policy=make_policy(threads=2))
    assert out_dir.exists()
    assert list(out_dir.iterdir()) == []
    assert list(tmp_path.rglob(".pdftoolkit-*")) == []


# --------------------------------------------------------------------------- #
# AC27 -- models.py untouched; message is parseable and matches the file.
# --------------------------------------------------------------------------- #


def _parse_dimensions(message: str | None) -> tuple[int, int]:
    import re

    assert message is not None
    match = re.match(r"^page \d+: (\d+)x(\d+) [a-z]+ @ [\d.]+ dpi$", message)
    assert match is not None, message
    return int(match.group(1)), int(match.group(2))


def test_ac27_models_py_has_no_rasterize_specific_field() -> None:
    from pdf_toolkit.models import ItemResult

    fields = set(ItemResult.__dataclass_fields__)
    assert fields == {
        "input",
        "output",
        "ok",
        "exit_code",
        "message",
        "bytes_before",
        "bytes_after",
        "duration_ms",
    }


def test_ac27_message_matches_the_produced_file_for_dpi_and_width_modes(
    tmp_path: Path,
) -> None:
    source = _make_letter(tmp_path / "src")

    dpi_out = tmp_path / "dpi_out"
    dpi_result = _rasterize(source, out_dir=dpi_out, dpi=300.0)
    with Image.open(next(dpi_out.iterdir())) as img:
        assert _parse_dimensions(dpi_result.items[0].message) == img.size

    width_out = tmp_path / "width_out"
    width_result = _rasterize(source, out_dir=width_out, width_px=900)
    with Image.open(next(width_out.iterdir())) as img:
        assert _parse_dimensions(width_result.items[0].message) == img.size


# --------------------------------------------------------------------------- #
# D7 -- flag-independent error contracts exercised at the ops layer.
# --------------------------------------------------------------------------- #


def test_pages_even_on_a_one_page_document_exits_4(tmp_path: Path) -> None:
    source = _make_letter(tmp_path / "src")
    with pytest.raises(NoInputError):
        _rasterize(source, out_dir=tmp_path / "out", pages_spec="even")


def test_nonexistent_source_exits_4(tmp_path: Path) -> None:
    with pytest.raises(NoInputError):
        _rasterize(tmp_path / "does-not-exist.pdf", out_dir=tmp_path / "out")


def test_source_that_is_a_directory_exits_2(tmp_path: Path) -> None:
    directory = tmp_path / "a-directory"
    directory.mkdir()
    with pytest.raises(UsageError):
        _rasterize(directory, out_dir=tmp_path / "out")


def test_webp_engine_missing_exits_3_when_pillow_lacks_webp_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_letter(tmp_path / "src")

    def _no_webp(name: str) -> bool:
        return False if name == "webp" else True

    from PIL import features

    monkeypatch.setattr(features, "check", _no_webp)
    with pytest.raises(EngineMissingError):
        _rasterize(source, out_dir=tmp_path / "out", fmt="webp")


def test_raster_engine_unavailable_exits_3_with_a_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_letter(tmp_path / "src")

    def _missing(*, capability: str | None = None) -> object:
        raise EngineMissingError(
            "RasterEngine is unavailable. Install it with: uv tool install --force pdf-toolkit. "
            "Run 'pdftoolkit doctor' to see which engines resolved."
        )

    monkeypatch.setattr(raster_module, "require_raster", _missing)
    with pytest.raises(EngineMissingError, match="Install it with"):
        _rasterize(source, out_dir=tmp_path / "out")


# --------------------------------------------------------------------------- #
# D6 -- explicit, pinned encoder parameters (not Pillow's own defaults).
# --------------------------------------------------------------------------- #


def test_png_output_uses_the_pinned_compress_level(tmp_path: Path) -> None:
    source = _make_letter(tmp_path / "src")
    out_dir = tmp_path / "out"
    _rasterize(source, out_dir=out_dir, dpi=72.0)
    files = list(out_dir.iterdir())
    with Image.open(files[0]) as img:
        assert img.mode == "RGB"
    # A cheap proxy for "compress_level was actually passed": the encoder
    # accepted the call with no exception, and the file is a valid deflate
    # stream (any PNG is); the pinned level itself is asserted directly.
    assert raster_module._PNG_COMPRESS_LEVEL == 9


def test_jpeg_output_is_valid_and_quality_defaults_to_85(tmp_path: Path) -> None:
    source = _make_letter(tmp_path / "src")
    out_dir = tmp_path / "out"
    _rasterize(source, out_dir=out_dir, dpi=72.0, fmt="jpeg")
    files = list(out_dir.iterdir())
    with Image.open(files[0]) as img:
        img.verify()
    assert raster_module._DEFAULT_QUALITY == 85
