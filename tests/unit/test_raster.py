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
from typing import Final

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


def _make_coloured(directory: Path, *, name: str = "coloured.pdf") -> Path:
    """PDF-21/AC4(a): a US-Letter page of six SATURATED colour bands.

    Verb-private, and deliberately not text: ``_make_letter`` draws black on
    white, so every channel is already equal before any grayscale conversion --
    the property that made the shipped AC9 webp arm pass with the feature
    switched off. Bands, not text, so a colour pixel dominates the measurement
    instead of a hairline glyph edge.
    """
    from reportlab.lib.pagesizes import letter

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    made = _new_canvas(path, letter)
    bands = ((1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (0, 1, 1), (1, 0, 1))
    for index, (red, green, blue) in enumerate(bands):
        made.setFillColorRGB(red, green, blue)  # type: ignore[attr-defined]
        made.rect(0, index * 132, 612, 132, stroke=0, fill=1)  # type: ignore[attr-defined]
    made.showPage()  # type: ignore[attr-defined]
    made.save()  # type: ignore[attr-defined]
    return path


def _stamp_rotate(path: Path, angle: int) -> Path:
    """Set ``/Rotate`` on page 1 **without touching the MediaBox** (B-094).

    reportlab's ``Canvas.setPageRotation()`` cannot express this shape: it
    pre-swaps the page's own MediaBox so that the *displayed* page keeps the
    requested ``pagesize``. A ``letter`` canvas with ``setPageRotation(90)``
    therefore writes ``MediaBox [0 0 792 612]`` + ``/Rotate 90``, i.e. a
    LANDSCAPE raw box that displays PORTRAIT -- the exact opposite of what its
    call site reads like, and the reason AC8's own fixture did not test what
    AC8 says it tests (see that test's comment). This is the same class of
    generated-fixture limit B-084 recorded for the *absence* of ``/Rotate``.

    pypdf's ``page.rotation`` setter writes the ``/Rotate`` key and nothing
    else, so a portrait page stays portrait in raw space and genuinely
    displays landscape.
    """
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(path))
    writer = PdfWriter()
    page = reader.pages[0]
    page.rotation = angle
    writer.add_page(page)
    with open(path, "wb") as handle:
        writer.write(handle)
    return path


def _make_rotated(directory: Path, *, name: str = "rotated.pdf") -> Path:
    """AC8's fixture: one **portrait** Letter page carrying ``/Rotate 90``.

    B-094: the ``/Rotate`` is stamped with pypdf rather than written by
    ``Canvas.setPageRotation()`` precisely so the raw MediaBox stays portrait
    (612x792) -- AC8's own wording is *"rasterizes landscape ... where the
    unrotated page is portrait"*, and the reportlab spelling silently supplied
    a landscape one.
    """
    from reportlab.lib.pagesizes import letter

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    made = _new_canvas(path, letter)
    made.drawString(72, 700, "rotated fixture -- one page, /Rotate 90.")
    made.showPage()
    made.save()
    return _stamp_rotate(path, 90)


#: B-094's fixture geometry: a tall PORTRAIT page with a black band across its
#: top fifth. Portrait-and-banded is what makes every angle distinguishable --
#: the size alone separates 0/180 from 90/270, and the band's edge separates 0
#: from 180 and 90 from 270. An aspect-ratio assertion can do neither.
_BAND_WIDTH_PT: Final[float] = 200.0
_BAND_HEIGHT_PT: Final[float] = 600.0

#: Where the band lands once ``/Rotate`` is applied. Derived from the format,
#: not from the renderer: ISO 32000 defines ``/Rotate`` as the number of
#: degrees the page is turned **clockwise when displayed**, and turning a sheet
#: clockwise carries its top edge to the right, then the bottom, then the left.
_BAND_EDGE_AFTER_ROTATE: Final[dict[int, str]] = {
    0: "top",
    90: "right",
    180: "bottom",
    270: "left",
}

#: The displayed ``(width_pt, height_pt)`` of that page at each angle.
_DISPLAYED_PT_AFTER_ROTATE: Final[dict[int, tuple[float, float]]] = {
    0: (_BAND_WIDTH_PT, _BAND_HEIGHT_PT),
    90: (_BAND_HEIGHT_PT, _BAND_WIDTH_PT),
    180: (_BAND_WIDTH_PT, _BAND_HEIGHT_PT),
    270: (_BAND_HEIGHT_PT, _BAND_WIDTH_PT),
}


def _make_banded(directory: Path, *, rotation: int, name: str | None = None) -> Path:
    """A portrait page, black band on the TOP fifth, carrying ``/Rotate``."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (name or f"banded-{rotation}.pdf")
    made = _new_canvas(path, (_BAND_WIDTH_PT, _BAND_HEIGHT_PT))
    made.setFillColorRGB(0, 0, 0)
    made.rect(0, _BAND_HEIGHT_PT * 0.8, _BAND_WIDTH_PT, _BAND_HEIGHT_PT * 0.2, stroke=0, fill=1)
    made.showPage()
    made.save()
    return _stamp_rotate(path, rotation)


def _darkest_edge(image: Image.Image) -> str:
    """Which of the four edge strips carries the band.

    Mean luminance over the outer tenth of each edge; the band is pure black
    on white, so the minimum is unambiguous (measured separations are
    0 vs 204+, not a close call).
    """
    grey = image.convert("L")
    width, height = grey.size
    pixels = grey.load()
    assert pixels is not None

    def mean(x0: int, y0: int, x1: int, y1: int) -> float:
        values = [pixels[x, y] for y in range(y0, y1) for x in range(x0, x1)]
        return sum(values) / len(values)

    strips = {
        "top": mean(0, 0, width, max(1, height // 10)),
        "bottom": mean(0, height - max(1, height // 10), width, height),
        "left": mean(0, 0, max(1, width // 10), height),
        "right": mean(width - max(1, width // 10), 0, width, height),
    }
    return min(strips, key=lambda key: strips[key])


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
#
# Not tested by monkeypatching a production function and checking which PID
# ran it: that only works under the `fork` multiprocessing start method
# (Linux's default through Python 3.13), where a child inherits the parent's
# already-patched module state. `fork` is NOT universal -- macOS has used
# `spawn` by default since Python 3.8, and Python 3.14 makes `spawn` the
# default everywhere. Under `spawn` a child re-imports every module fresh,
# so a parent-side monkeypatch never reaches it at all (confirmed live: this
# exact PID-monkeypatch design passed on Linux/3.12 locally and failed on
# every macOS job and the 3.14 job in CI). The two checks below are each
# start-method-independent.
# --------------------------------------------------------------------------- #


def test_ac5_the_planning_handle_is_closed_before_the_executor_is_created(
    tmp_path: Path,
) -> None:
    """PDF-21/AC4(b). This REPLACES ``test_ac5_a_process_pool_dispatch_runs_in_
    a_different_pid``, which was **vacuous**: its body referenced no
    ``pdf_toolkit`` symbol at all -- it submitted a local function to a
    ``ProcessPoolExecutor`` and asserted the PID differed, i.e. it tested that
    CPython forks. It would have passed with the entire rasterize feature
    deleted. (Reported as a finding, not silently dropped.)

    AC5's ACTUAL claim is *"the planning handle is closed before the executor is
    created"* (``ops/raster.py``: ``_plan_pages``'s ``with
    engine.open_document(...)`` closes at ``:132-134``; the pool is created at
    ``:412``), and AC5 itself offers the mechanization used here -- **an
    instrumented adapter counter**. The counter is sampled at the exact moment
    ``guarded_process_pool`` is called, so a handle held open across the pool
    reds it.

    The sibling ``test_ac5_rasterize_document_never_calls_render_directly`` is
    a structural proof about a DIFFERENT property (nothing renders on the
    parent's own stack) and is kept, not replaced.
    """
    import contextlib

    source = _make_multipage(tmp_path / "src", pages=4)
    live: list[int] = [0]
    open_handles_at_pool_creation: list[int] = []

    real_require_structure = raster_module.require_structure
    real_pool = raster_module.guarded_process_pool

    class _CountingEngine:
        """Wraps the real StructureEngine; counts CURRENTLY-OPEN documents."""

        def __init__(self, inner: object) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

        @contextlib.contextmanager
        def open_document(self, path: object):  # type: ignore[no-untyped-def]
            live[0] += 1
            try:
                with self._inner.open_document(path) as document:  # type: ignore[attr-defined]
                    yield document
            finally:
                live[0] -= 1

    def _counting_require_structure(*args: object, **kwargs: object) -> object:
        return _CountingEngine(real_require_structure(*args, **kwargs))

    def _observing_pool(*args: object, **kwargs: object) -> object:
        open_handles_at_pool_creation.append(live[0])
        return real_pool(*args, **kwargs)

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(raster_module, "require_structure", _counting_require_structure)
        monkeypatch.setattr(raster_module, "guarded_process_pool", _observing_pool)
        result = _rasterize(
            source, out_dir=tmp_path / "out", dpi=72.0, policy=make_policy(threads=2)
        )
    finally:
        monkeypatch.undo()

    assert result.exit_code == 0
    # Non-vacuity: the pool WAS created, so the sample below is a real sample.
    assert open_handles_at_pool_creation, (
        "guarded_process_pool was never called -- this assertion would be vacuous"
    )
    assert open_handles_at_pool_creation == [0], (
        f"{open_handles_at_pool_creation[0]} planning handle(s) were still open when the "
        f"executor was created; AC5 requires the parent to hold none"
    )
    assert live[0] == 0, "a planning handle outlived the run"


def test_ac5_a_process_pool_dispatch_runs_in_a_different_process(tmp_path: Path) -> None:
    """The PID property AC5 also states, re-derived through the PRODUCT rather
    than through a local function: the pages are rendered somewhere other than
    this interpreter. ``_render_one`` records ``os.getpid()`` nowhere, so the
    observation is made from the worker side of the real dispatch -- the module
    level worker ``_render_chunk``, submitted by ``rasterize_document`` itself.
    """
    source = _make_multipage(tmp_path / "src", pages=2)
    seen: list[int] = []
    real_pool = raster_module.guarded_process_pool

    class _PidRecordingExecutor:
        def __init__(self, inner: object) -> None:
            self._inner = inner

        def submit(self, fn: object, *args: object, **kwargs: object) -> object:
            future = self._inner.submit(_worker_pid_probe)  # type: ignore[attr-defined]
            seen.append(future.result())
            return self._inner.submit(fn, *args, **kwargs)  # type: ignore[attr-defined]

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    import contextlib

    @contextlib.contextmanager
    def _probing_pool(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        with real_pool(*args, **kwargs) as executor:
            yield _PidRecordingExecutor(executor)

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(raster_module, "guarded_process_pool", _probing_pool)
        result = _rasterize(source, out_dir=tmp_path / "out", dpi=72.0)
    finally:
        monkeypatch.undo()

    assert result.exit_code == 0
    assert seen, "the pool the product itself creates dispatched nothing"
    assert all(pid != os.getpid() for pid in seen), seen


def _worker_pid_probe() -> int:
    """Module-level (picklable by reference): reports the OS process a worker of
    the PRODUCT's own pool actually runs in."""
    return os.getpid()


def test_ac5_rasterize_document_never_calls_render_directly() -> None:
    """Structural proof, independent of any process/thread semantics:
    `rasterize_document`'s own body calls `_render_chunk` only through
    `executor.submit(...)`, never `_render_one` or `.render_page(` bare --
    so nothing in the parent's own call stack ever renders a page, whatever
    the multiprocessing start method turns out to be."""
    import ast
    import inspect

    source = inspect.getsource(raster_module.rasterize_document)
    tree = ast.parse(source)
    bare_calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_render_one" not in bare_calls
    assert "_render_chunk" not in bare_calls

    submitted = {
        node.args[0].id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "submit"
        and node.args
        and isinstance(node.args[0], ast.Name)
    }
    assert submitted == {"_render_chunk"}


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
#
# B-094 CORRECTED THIS TEST'S FIXTURE, and the correction is the finding.
# Until B-094 this test built its page with `Canvas.setPageRotation(90)`,
# which pre-swaps the MediaBox to 792x612 -- so the "portrait page" in its
# own docstring was landscape in raw space and PORTRAIT when displayed. The
# assertion `width > height` therefore passed only because the adapter
# double-applied `/Rotate` and rendered the RAW box; it was pinning the
# defect, and it goes red the moment the adapter is right. The fixture now
# stamps `/Rotate 90` onto a genuinely portrait page (`_stamp_rotate`), which
# is what AC8's own wording -- "where the unrotated page is portrait" --
# always said. The assertion below is unchanged; only the fixture is, and now
# it means what it reads like.
# --------------------------------------------------------------------------- #


def test_ac8_rotated_page_rasterizes_landscape(tmp_path: Path) -> None:
    source = _make_rotated(tmp_path / "src")

    from pypdf import PdfReader

    raw_box = PdfReader(str(source)).pages[0].mediabox
    # The precondition AC8 states, asserted rather than assumed (this is the
    # half the reportlab spelling silently inverted).
    assert float(raw_box.width) < float(raw_box.height), raw_box
    assert PdfReader(str(source)).pages[0].rotation == 90  # present, non-zero (B-084)

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
# B-094 -- `/Rotate` is applied EXACTLY ONCE, at every one of the four angles.
#
# The defect these tests exist for was a wrong answer on the happy path with
# a success exit code: `adapters/pdfium_raster.py` re-applied the page's own
# `/Rotate` on top of pdfium's internal application, in BOTH places it read
# the page -- it re-swapped `get_size()`'s already-displayed dimensions and
# passed `rotation=page.get_rotation()` into `render()`. The two second
# applications agreed with each other on the DIMENSIONS, so every
# size-or-aspect assertion in the suite stayed green while the PIXELS came out
# an ADDITIONAL `/Rotate` degrees clockwise: 90 degrees out at `/Rotate 90`,
# 180 degrees out at `/Rotate 180` -- it did NOT cancel -- and 270 degrees out
# at `/Rotate 270`. Only `/Rotate 0` was ever correct. (The "cancels at 0/180"
# reading this comment carried until B-102 was the pre-B-094 one, taken from
# image SIZES, which the second swap had already put back; the commit that
# added this matrix disproved it, and `adapters/pdfium_raster.py`'s module
# docstring -- written in that same commit -- says so.)
#
# So the matrix below covers all four angles and asserts WHERE THE CONTENT
# LANDED, not only how big the image is. Either half alone is blind: the size
# cannot separate 0 from 180, and the band edge alone would not have caught a
# transposed bitmap. The expected values come from ISO 32000's definition of
# `/Rotate` (clockwise-when-displayed), written down in
# `_BAND_EDGE_AFTER_ROTATE`, not from what the renderer happens to produce.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_b094_rotate_is_applied_exactly_once_at_every_angle(tmp_path: Path, rotation: int) -> None:
    source = _make_banded(tmp_path / "src", rotation=rotation)

    from pypdf import PdfReader

    page = PdfReader(str(source)).pages[0]
    # The fixture really is portrait in raw space at every angle -- the shape
    # reportlab cannot write, and the reason this matrix can tell 90 from 270.
    assert (float(page.mediabox.width), float(page.mediabox.height)) == (
        _BAND_WIDTH_PT,
        _BAND_HEIGHT_PT,
    )
    assert page.rotation == rotation

    dpi = 150.0
    out_dir = tmp_path / "out"
    result = _rasterize(source, out_dir=out_dir, dpi=dpi)
    assert result.exit_code == 0
    files = list(out_dir.iterdir())
    assert len(files) == 1

    displayed_width_pt, displayed_height_pt = _DISPLAYED_PT_AFTER_ROTATE[rotation]
    expected = (
        round(displayed_width_pt * dpi / 72.0),
        round(displayed_height_pt * dpi / 72.0),
    )
    with Image.open(files[0]) as img:
        assert img.size == expected, (rotation, img.size, expected)
        assert _darkest_edge(img) == _BAND_EDGE_AFTER_ROTATE[rotation], rotation
    assert _parse_dimensions(result.items[0].message) == expected


def test_b094_displayed_size_agrees_with_pdfiums_own_unrotated_render(
    tmp_path: Path,
) -> None:
    """`_displayed_size` must equal the box pdfium itself renders into.

    Stated against the engine rather than against this module's arithmetic:
    pdfium sizes its bitmap `ceil(get_size() * scale)` and honours `/Rotate`
    with no argument, so a no-argument render at scale 1 IS the displayed box
    in points. The pre-B-094 `_displayed_size` disagreed with it by a swap on
    90/270 -- which is the half of the defect a pixel assertion alone would
    not localise.
    """
    import pypdfium2 as pdfium

    from pdf_toolkit.adapters.pdfium_raster import _displayed_size

    for rotation in (0, 90, 180, 270):
        source = _make_banded(tmp_path / "src", rotation=rotation)
        document = pdfium.PdfDocument(str(source))
        try:
            page = document.get_page(0)
            try:
                bitmap = page.render(scale=1.0)
                try:
                    engine_size = bitmap.to_pil().size
                finally:
                    bitmap.close()
                assert _displayed_size(page) == _DISPLAYED_PT_AFTER_ROTATE[rotation], rotation
                assert engine_size == _DISPLAYED_PT_AFTER_ROTATE[rotation], rotation
            finally:
                page.close()
        finally:
            document.close()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_b094_the_ceiling_correction_is_still_a_crop_and_never_a_pad(
    tmp_path: Path, rotation: int
) -> None:
    """The module docstring's crop proof, re-derived at every angle.

    `PIL.Image.crop` past the edge PADS WITH BLACK rather than failing, so
    "target never exceeds pdfium's bitmap" is the invariant standing between
    this adapter and a second silent-wrong-answer defect. Before B-094 the
    target and the bitmap were computed from different boxes and merely
    happened to agree on 90/270; now both derive from `get_size()`, and this
    asserts the consequence directly against the engine.
    """
    import math

    import pypdfium2 as pdfium

    source = _make_banded(tmp_path / "src", rotation=rotation)
    document = pdfium.PdfDocument(str(source))
    try:
        page = document.get_page(0)
        try:
            displayed_width, displayed_height = page.get_size()
            for dpi in (72.0, 96.0, 150.0, 200.0, 300.0, 600.0):
                scale = dpi / 72.0
                bitmap = (
                    math.ceil(displayed_width * scale),
                    math.ceil(displayed_height * scale),
                )
                target = (
                    round(displayed_width * dpi / 72.0),
                    round(displayed_height * dpi / 72.0),
                )
                slack = (bitmap[0] - target[0], bitmap[1] - target[1])
                assert slack[0] >= 0 and slack[1] >= 0, (rotation, dpi, bitmap, target)
                assert slack[0] <= 1 and slack[1] <= 1, (rotation, dpi, bitmap, target)
        finally:
            page.close()
    finally:
        document.close()

    # And the end-to-end consequence: --width mode lands on the requested
    # width exactly at every angle, which is the crop actually firing.
    for width_px in (100, 333):
        out_dir = tmp_path / f"out-{rotation}-{width_px}"
        result = _rasterize(source, out_dir=out_dir, dpi=None, width_px=width_px)
        assert result.exit_code == 0
        displayed_width_pt, displayed_height_pt = _DISPLAYED_PT_AFTER_ROTATE[rotation]
        expected = (
            width_px,
            max(1, round(width_px * displayed_height_pt / displayed_width_pt)),
        )
        with Image.open(next(iter(out_dir.iterdir()))) as img:
            assert img.size == expected, (rotation, width_px, img.size, expected)
            assert _darkest_edge(img) == _BAND_EDGE_AFTER_ROTATE[rotation], (rotation, width_px)


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


#: The webp arm's tolerance: WebP's lossy YUV round-trip drifts a few units of
#: chroma even for an R==G==B source, so "perceptually grayscale" is asserted
#: rather than bit-exact channel equality.
_WEBP_GRAY_TOLERANCE = 8


def _max_channel_delta(path: Path) -> int:
    """The largest per-pixel spread between any two RGB channels in *path*."""
    with Image.open(path) as img:
        assert img.mode == "RGB", img.mode
        r, g, b = (channel.tobytes() for channel in img.split())
        return max(
            max(abs(rv - gv), abs(gv - bv), abs(rv - bv))
            for rv, gv, bv in zip(r, g, b, strict=True)
        )


def test_ac9_grayscale_webp_is_perceptually_grayscale_but_reads_back_rgb(
    tmp_path: Path,
) -> None:
    """PDF-21/AC4(a) -- REBUILT ON A COLOURED FIXTURE.

    **The shipped version of this test was an inverted control**, in the same
    file as AC8's and found the same way: it rendered ``_make_letter`` (BLACK
    TEXT ON WHITE), so R == G == B held *before any grayscale conversion at
    all*. Measured at ``b20a651``: ``grayscale=True -> mode=RGB max_delta=1``
    and ``grayscale=False -> mode=RGB max_delta=1`` -- **both of the shipped
    assertions passed identically with the feature switched off**, and would
    have gone on passing if ``--grayscale`` were removed for webp entirely.

    The fixture below paints six saturated colour bands, so the two states are
    separable: ``grayscale=True -> max_delta=0``, ``grayscale=False ->
    max_delta=255``. The negative arm underneath is what makes this a control
    rather than an observation.
    """
    source = _make_coloured(tmp_path / "src")
    out_dir = tmp_path / "out-webp-gray"
    result = _rasterize(source, out_dir=out_dir, dpi=96.0, fmt="webp", grayscale=True)
    assert result.exit_code == 0
    files = list(out_dir.iterdir())
    with Image.open(files[0]) as img:
        # The documented exception: WebP has no single-channel bitstream mode.
        assert img.mode == "RGB"
    assert _max_channel_delta(files[0]) <= _WEBP_GRAY_TOLERANCE


def test_ac9_the_webp_grayscale_arm_can_fail_without_the_flag(tmp_path: Path) -> None:
    """The negative half, and the whole reason the fixture above changed: the
    SAME source, the SAME assertion, with ``grayscale=False`` must FAIL. Without
    this, "perceptually grayscale" is a property of the fixture, not of the
    feature -- which is exactly what the shipped arm was measuring."""
    source = _make_coloured(tmp_path / "src")
    out_dir = tmp_path / "out-webp-colour"
    result = _rasterize(source, out_dir=out_dir, dpi=96.0, fmt="webp", grayscale=False)
    assert result.exit_code == 0
    files = list(out_dir.iterdir())
    with Image.open(files[0]) as img:
        assert img.mode == "RGB"
    assert _max_channel_delta(files[0]) > _WEBP_GRAY_TOLERANCE, (
        "a colour source rendered WITHOUT --grayscale came back with equal "
        "channels -- the positive arm above cannot distinguish the flag's two "
        "states and is therefore not a control"
    )


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


def test_ac16_a_render_failure_is_a_failed_item_and_exit_1_never_a_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PDF-09 AC16's second clause -- *"a render failure is a failed
    ``ItemResult`` and exit 1, never a fallback"* -- had **no test in the
    repository**: nothing ever produced ``ok=False`` out of ``_render_one``.

    Driven against ``_render_chunk`` directly for the reason
    ``test_ac26_atomic_writer_refusing_produces_zero_files`` already documents
    at length: production always dispatches through a ``ProcessPoolExecutor``,
    and under ``spawn`` a parent-side monkeypatch never reaches a child.
    ``_render_chunk`` is the module-level, picklable-argument unit AC4/AC7
    already pin as what a worker executes.
    """
    from pdf_toolkit.errors import FailureError
    from pdf_toolkit.models import OperationResult

    source = _make_multipage(tmp_path / "src", pages=3)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    real_require_raster = raster_module.require_raster

    class _FailsOnPageTwo:
        def __init__(self, inner: object) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

        def render_page(self, path: str, page_number: int, **kwargs: object) -> object:
            if page_number == 2:
                raise FailureError("planted render failure on page 2")
            return self._inner.render_page(path, page_number, **kwargs)  # type: ignore[attr-defined]

    def _flaky(*, capability: str | None = None) -> object:
        return _FailsOnPageTwo(real_require_raster(capability=capability))

    monkeypatch.setattr(raster_module, "require_raster", _flaky)

    items = [
        (slot, str(source), page, str(out_dir / f"src-{page:04}.png"), 96.0, None)
        for slot, page in enumerate(range(1, 4))
    ]
    produced = [
        item
        for _slot, item in raster_module._render_chunk(
            items, fmt="png", quality=None, grayscale=False, policy=make_policy()
        )
    ]

    assert [item.ok for item in produced] == [True, False, True]
    failed = produced[1]
    assert failed.exit_code == 1
    assert failed.message is not None and "planted render failure" in failed.message
    # No fallback: the failed page produced no file, the others did.
    assert sorted(path.name for path in out_dir.iterdir()) == ["src-0001.png", "src-0003.png"]
    # The run-level code AC16 names, from the per-item codes the run collects.
    run = OperationResult(
        schema_version=raster_module._SCHEMA_VERSION,
        verb=raster_module.VERB,
        dry_run=False,
        items=tuple(produced),
        warnings=(),
        duration_ms=0,
    )
    assert run.exit_code == 1


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


#: The only first arguments a `.save(` call in `ops/raster.py` may take. An
#: allowlist, not a denylist: PDF-09 AC26's own regex was a denylist and had a
#: PROVEN hole (below), which is what a denylist over source text always
#: eventually has.
_ALLOWED_SAVE_TARGETS = frozenset({"stream"})


def test_ac26_pillow_is_handed_a_stream_never_a_path() -> None:
    """PDF-21/AC5 -- the shipped regex had a proven hole, closed here by parsing.

    The shipped assertion was ``re.match(r"\\s*(str|Path|[a-z_]*path)\\s*[,)]",
    call)`` over ``re.findall(r"\\.save\\(([^)]*)")``. Because ``[^)]*`` stops at
    the FIRST ``)``, ``image.save(str(target), ...)`` captures ``"str(target"``
    -- and ``str`` is then followed by ``(``, not by ``[,)]``, so the guard does
    not fire. ``image.save(Path(target), ...)`` fails the same way. **Both are
    the two most natural chokepoint bypasses and both passed the shipped
    control** (each demonstrated red against this version -- see PDF-21's audit
    record).

    Parsing removes the class of hole rather than one instance of it: every
    ``.save(`` call's first positional argument must be, verbatim, one of
    :data:`_ALLOWED_SAVE_TARGETS`.
    """
    import ast

    tree = ast.parse((SRC_ROOT / "ops" / "raster.py").read_text())
    save_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "save"
    ]
    assert save_calls, "no .save( call found -- the test is measuring nothing"
    for call in save_calls:
        assert call.args, f"a .save() call with no positional target at line {call.lineno}"
        target = ast.unparse(call.args[0])
        assert target in _ALLOWED_SAVE_TARGETS, (
            f"ops/raster.py:{call.lineno}: image bytes are handed {target!r}, not an "
            f"AtomicWriter stream -- the chokepoint is bypassed "
            f"(allowed: {sorted(_ALLOWED_SAVE_TARGETS)})"
        )


def test_ac26_no_mkdir_in_ops_raster() -> None:
    text = (SRC_ROOT / "ops" / "raster.py").read_text()
    assert "mkdir" not in text


def test_ac26_atomic_writer_refusing_produces_zero_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Called directly against `_render_chunk` (in-process), not through
    `rasterize_document`'s real run: production always dispatches rendering
    through a `ProcessPoolExecutor` (module docstring), and under the
    `spawn` start method (macOS always; every platform from Python 3.14) a
    parent-side monkeypatch of `AtomicWriter` never reaches a spawned
    child -- it re-imports `pdf_toolkit.safety.atomic` fresh instead of
    inheriting the parent's patched state. `_render_chunk` is exactly the
    module-level, picklable-argument unit AC4/AC7 already pin as what a
    worker executes; calling it directly here exercises the identical
    chokepoint-construction code path, in the one process where a
    monkeypatch is guaranteed to apply on every platform."""
    source = _make_multipage(tmp_path / "src", pages=2)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    def _boom(self: object) -> None:
        raise RuntimeError("planted chokepoint failure")

    monkeypatch.setattr(atomic_module.AtomicWriter, "__enter__", _boom)
    items = [(0, str(source), 1, str(out_dir / "src-0001.png"), 96.0, None)]
    with pytest.raises(RuntimeError):
        raster_module._render_chunk(
            items, fmt="png", quality=None, grayscale=False, policy=make_policy()
        )
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
    """PDF-09's pin, EXTENDED by PDF-10 rather than deleted.

    The property PDF-09 was protecting -- *no verb bolts its own field onto the
    shared item model* -- is unchanged and still asserted exactly. What changed
    is that the cycle-wide `detail` seam now exists: `decision.md` §8 X-26 ruled
    one optional, verb-agnostic field for exactly this need, X-92 established it
    did not yet exist in code, and PDF-10 is the consumer that landed it. So the
    set is still EXACT, and the second assertion below states the original
    intent directly: nothing in this model is named after a verb.

    This pin was NOT in PDF-10's own §13 fallout table -- it is a ninth
    tripwire, found by running rather than by reading, and reported as such.
    """
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
        "detail",
    }
    verb_shaped = {
        name
        for name in fields
        if any(token in name for token in ("raster", "dpi", "image", "compose", "create", "px"))
    }
    assert verb_shaped == set(), f"{sorted(verb_shaped)} names a verb on a shared model"


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
