"""PDF-12 -- `compress`/`repair`/`linearize` at the op layer.

Everything here runs IN PROCESS, calling `ops/optimize.py` directly. The
subprocess-level contract (exit codes, `--help` content, the encrypted-fixture
AUTH path, the `--in-place` `.bak` sidecar as a real process sees it) lives in
`tests/integration/test_optimize_cli.py`; keeping the two apart is what keeps
this spec's subprocess count proportionate to what genuinely needs a process
(B-061).

HC-2 binds this module: nothing here touches `$PDF_TOOLKIT_SAMPLES_DIR`. The
`@samples` arm lives in `tests/test_samples.py`'s own PDF-12 section.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_toolkit.errors import AuthError, FailureError, NoInputError, UsageError  # noqa: E402
from pdf_toolkit.ops.optimize import compress_run, linearize_run, repair_run  # noqa: E402
from pdf_toolkit.ports.structure import CompressOutcome, ImageXObjectFacts  # noqa: E402
from pdf_toolkit.safety.policy import SafetyPolicy  # noqa: E402
from pdfium_text import page_texts  # noqa: E402

REPO_ROOT = TESTS_DIR.parent
TESTDATA = REPO_ROOT / "testdata"
MALFORMED_PDF = TESTDATA / "malformed.pdf"


def policy(**overrides: Any) -> SafetyPolicy:
    values: dict[str, Any] = {
        "dry_run": False,
        "force": False,
        "in_place": False,
        "backup": True,
        "assume_yes": False,
        "is_tty": False,
        "threads": 1,
    }
    values.update(overrides)
    return SafetyPolicy(**values)


def _large_image_pdf(tmp_path: Path, *, width: int = 2000, height: int = 1500) -> Path:
    """A local, self-contained fixture: a Letter page carrying one embedded
    JPEG wide enough to cross the default `--image-dpi 150` threshold
    (`150 x 8.5in == 1275px`) -- unlike `tests/corpus.py`'s shared
    `jpeg_page` fixture, whose 32x32 embedded image is deliberately tiny and
    would never cross that threshold on a Letter page (D-12.2's own stated
    page-box-not-placement-rect limitation). Built locally, never touching
    the shared corpus module (`tests/corpus.py`'s docstring names exactly
    seven fixtures; this spec adds none there)."""
    import io

    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    image = Image.new("RGB", (width, height), (30, 60, 90))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90, subsampling=0)

    path = tmp_path / "large-image.pdf"
    made = canvas.Canvas(str(path), pagesize=(612, 792))
    made.drawImage(ImageReader(io.BytesIO(buffer.getvalue())), 50, 50, width=500, height=375)
    made.showPage()
    made.save()
    return path


# --------------------------------------------------------------------------- #
# AC2 -- the measurement, not a claim
# --------------------------------------------------------------------------- #


def test_ac2_bytes_before_and_after_are_populated_for_every_item(corpus, tmp_path: Path) -> None:
    source = corpus.path("multipage_text")
    target = tmp_path / "out.pdf"
    result = compress_run(
        [source],
        lossless=False,
        images="keep",
        image_dpi=150.0,
        image_quality=80,
        pages_spec=None,
        output=target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0
    item = result.items[0]
    assert isinstance(item.bytes_before, int)
    assert isinstance(item.bytes_after, int)
    payload = result.to_dict()
    assert payload["items"][0]["bytes_before"] is not None
    assert payload["items"][0]["bytes_after"] is not None


# --------------------------------------------------------------------------- #
# AC3 -- `--lossless` reduces size AND preserves text
# --------------------------------------------------------------------------- #


def test_ac3_lossless_shrinks_and_preserves_text(corpus, tmp_path: Path) -> None:
    source = corpus.path("multipage_text")
    target = tmp_path / "lossless.pdf"
    result = compress_run(
        [source],
        lossless=True,
        images="keep",
        image_dpi=150.0,
        image_quality=80,
        pages_spec=None,
        output=target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0
    item = result.items[0]
    assert item.bytes_after is not None and item.bytes_before is not None
    assert item.bytes_after < item.bytes_before, (
        "the generated multipage_text fixture did not shrink under --lossless -- "
        "a finding to report, per the spec's own escalation note; not relaxed to <="
    )

    before_texts = page_texts(source)
    after_texts = page_texts(target)
    assert len(after_texts) == len(before_texts)
    assert after_texts == before_texts


# --------------------------------------------------------------------------- #
# AC4 -- the guarantee is enforced, not asserted
# --------------------------------------------------------------------------- #


def test_ac4_lossless_with_a_lossy_image_pass_is_a_cli_level_refusal() -> None:
    """The `--lossless --images downsample` refusal is OR-2-shaped usage
    validation, checked in `cli/cmd_compress.py` -- see
    `tests/integration/test_optimize_cli.py` for the exit-2 proof. `ops/`
    itself does not gate flag combinations; it trusts what the CLI already
    validated, matching every other verb's split (`ops/raster.py` does not
    re-check `--dpi`/`--width` mutual exclusion either)."""


def test_ac4_a_page_count_mismatch_refuses_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, corpus, tmp_path: Path
) -> None:
    from pdf_toolkit.adapters import pikepdf_structure

    source = corpus.path("multipage_text")
    target = tmp_path / "target.pdf"
    seed = b"pre-existing bytes, must survive untouched"
    target.write_bytes(seed)

    real_compress = pikepdf_structure.PikepdfStructureAdapter.compress

    def _tampered(self: Any, data: bytes) -> CompressOutcome:
        outcome = real_compress(self, data)
        tampered_after = outcome.after.__class__(
            page_count=outcome.after.page_count - 1, images=outcome.after.images
        )
        return CompressOutcome(output=outcome.output, before=outcome.before, after=tampered_after)

    monkeypatch.setattr(pikepdf_structure.PikepdfStructureAdapter, "compress", _tampered)

    with pytest.raises(FailureError, match="page count changed"):
        compress_run(
            [source],
            lossless=True,
            images="keep",
            image_dpi=150.0,
            image_quality=80,
            pages_spec=None,
            output=target,
            out_dir=None,
            name_template=None,
            in_place=False,
            policy=policy(force=True),
        )
    assert target.read_bytes() == seed, "nothing may be written when the guarantee fails"


def test_ac4_a_dct_stream_mismatch_refuses_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, corpus, tmp_path: Path
) -> None:
    from pdf_toolkit.adapters import pikepdf_structure

    source = corpus.path("jpeg_page")
    target = tmp_path / "target.pdf"
    seed = b"pre-existing bytes, must survive untouched"
    target.write_bytes(seed)

    real_compress = pikepdf_structure.PikepdfStructureAdapter.compress

    def _tampered(self: Any, data: bytes) -> CompressOutcome:
        outcome = real_compress(self, data)
        images = list(outcome.after.images)
        assert images, "jpeg_page must carry at least one image XObject"
        first = images[0]
        images[0] = ImageXObjectFacts(
            filters=first.filters,
            width=first.width,
            height=first.height,
            colorspace=first.colorspace,
            bits_per_component=first.bits_per_component,
            dct_sha256="0" * 64,
        )
        tampered_after = outcome.after.__class__(
            page_count=outcome.after.page_count, images=tuple(images)
        )
        return CompressOutcome(output=outcome.output, before=outcome.before, after=tampered_after)

    monkeypatch.setattr(pikepdf_structure.PikepdfStructureAdapter, "compress", _tampered)

    with pytest.raises(FailureError, match="changed structurally"):
        compress_run(
            [source],
            lossless=True,
            images="keep",
            image_dpi=150.0,
            image_quality=80,
            pages_spec=None,
            output=target,
            out_dir=None,
            name_template=None,
            in_place=False,
            policy=policy(force=True),
        )
    assert target.read_bytes() == seed


# --------------------------------------------------------------------------- #
# AC5 -- the image pass reduces further, with content intact
# --------------------------------------------------------------------------- #


def test_ac5_downsample_is_strictly_smaller_than_lossless_only(corpus, tmp_path: Path) -> None:
    source = _large_image_pdf(tmp_path)

    lossless_target = tmp_path / "lossless-only.pdf"
    lossless_result = compress_run(
        [source],
        lossless=True,
        images="keep",
        image_dpi=150.0,
        image_quality=80,
        pages_spec=None,
        output=lossless_target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=policy(),
    )
    assert lossless_result.exit_code == 0

    downsample_target = tmp_path / "downsampled.pdf"
    downsample_result = compress_run(
        [source],
        lossless=False,
        images="downsample",
        image_dpi=150.0,
        image_quality=80,
        pages_spec=None,
        output=downsample_target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=policy(),
    )
    assert downsample_result.exit_code == 0

    assert downsample_target.stat().st_size < lossless_target.stat().st_size

    before_texts = page_texts(source)
    after_texts = page_texts(downsample_target)
    assert len(after_texts) == len(before_texts) == 1


# --------------------------------------------------------------------------- #
# AC6 -- opt-in, never implied, never default
# --------------------------------------------------------------------------- #


def test_ac6_bare_compress_leaves_the_image_inventory_identical(corpus, tmp_path: Path) -> None:
    from pdf_toolkit.adapters.pikepdf_structure import ADAPTER as pikepdf_adapter

    source = corpus.path("jpeg_page")
    target = tmp_path / "out.pdf"
    result = compress_run(
        [source],
        lossless=False,
        images="keep",
        image_dpi=150.0,
        image_quality=80,
        pages_spec=None,
        output=target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0

    before_facts = pikepdf_adapter.compress(source.read_bytes()).before
    after_facts = pikepdf_adapter.compress(target.read_bytes()).before
    assert before_facts.images == after_facts.images
    assert len(before_facts.images) >= 1


def test_ac6_pages_without_images_is_a_cli_level_refusal() -> None:
    """`--pages`/`--image-dpi`/`--image-quality` without `--images`, and a
    bogus `--images` value, are all CLI-level usage errors (Typer's own enum
    validation for the bogus case) -- see `tests/integration/test_optimize_cli.py`."""


# --------------------------------------------------------------------------- #
# AC7 -- honest ratio when it does not shrink
# --------------------------------------------------------------------------- #


def test_ac7_a_second_compression_pass_reports_a_non_positive_ratio(corpus, tmp_path: Path) -> None:
    source = corpus.path("multipage_text")
    once = tmp_path / "once.pdf"
    result_once = compress_run(
        [source],
        lossless=False,
        images="keep",
        image_dpi=150.0,
        image_quality=80,
        pages_spec=None,
        output=once,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=policy(),
    )
    assert result_once.exit_code == 0

    twice = tmp_path / "twice.pdf"
    result_twice = compress_run(
        [once],
        lossless=False,
        images="keep",
        image_dpi=150.0,
        image_quality=80,
        pages_spec=None,
        output=twice,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=policy(),
    )
    assert result_twice.exit_code == 0
    item = result_twice.items[0]
    assert item.bytes_before is not None and item.bytes_after is not None
    if item.bytes_after >= item.bytes_before:
        assert result_twice.warnings, "a non-shrinking run must warn on stderr-bound warnings"
        assert any("did not shrink" in warning for warning in result_twice.warnings)
        ratio = (item.bytes_before - item.bytes_after) / item.bytes_before * 100
        assert ratio <= 0
        assert item.message is not None and "%" in item.message


# --------------------------------------------------------------------------- #
# AC10 (superseded) -- `repair`'s before/after proof on `testdata/malformed.pdf`
# --------------------------------------------------------------------------- #


def test_malformed_fixture_precondition() -> None:
    """D-12.5's escalation rule: `info` must exit 1 on the fixture. Tested
    here at the port level (never a `pdftoolkit info` subprocess -- that
    belongs to `tests/integration/test_optimize_cli.py` if ever needed) via
    the same adapter `info` itself uses."""
    from pdf_toolkit.ports.structure import require_structure

    engine = require_structure()
    with pytest.raises(Exception):  # noqa: B017 - FailureError, asserted structurally below
        with engine.open_document(MALFORMED_PDF):
            pass


def test_ac10_repair_recovers_the_malformed_fixture_to_one_page(tmp_path: Path) -> None:
    """AC10 (superseded) as written asks for the repaired output's extracted
    text to be byte-identical to the in-memory reconstruction's AND
    non-empty. **Verified finding, reported to the PM (not silently
    reconciled):** neither side is ever non-empty for THIS fixture. Object 5
    -- the content stream, the one object item 4 of `testdata/README.md`
    names in its own "early EOF on object 5" warning -- comes back as
    `None` from `pikepdf.Pdf.open(..., attempt_recovery=True)` itself
    (confirmed here BEFORE this spec's own `repair()` ever runs: `page.Contents
    is None` immediately after open). `pypdfium2` and `pypdf` both then
    extract the empty string from both sides, on every run. `repair()` is not
    losing anything additional; libqpdf's own recovery already lost the
    text, and `testdata/README.md`'s own item 2 claims only that the
    structural objects "parse individually" and reconstruct "a 1-page
    document" -- never that the content stream survives.

    The equality assertion below is kept (it is still the real, meaningful
    proof that `repair` loses nothing BEYOND what recovery already lost).
    The X-102 non-vacuity requirement is satisfied instead against something
    that DOES demonstrably survive recovery -- the font resource -- rather
    than against text that does not exist for this fixture.
    """
    import pikepdf

    target = tmp_path / "fixed.pdf"
    result = repair_run(MALFORMED_PDF, output=target, in_place=False, report=True, policy=policy())
    assert result.exit_code == 0
    from pdf_toolkit.ports.structure import require_structure

    engine = require_structure()
    with engine.open_document(target) as document:
        assert document.page_count == 1

    with pikepdf.Pdf.open(MALFORMED_PDF, attempt_recovery=True) as recovered:
        # The verified finding, pinned so a future pikepdf upgrade that
        # starts recovering this stream is a loud, welcome surprise rather
        # than a silent behaviour change.
        assert recovered.pages[0].get("/Contents") is None
        buffer = __import__("io").BytesIO()
        recovered.save(buffer)
        recovered_bytes = buffer.getvalue()
    reconstructed_path = tmp_path / "reconstructed.pdf"
    reconstructed_path.write_bytes(recovered_bytes)

    repaired_texts = page_texts(target)
    reconstructed_texts = page_texts(reconstructed_path)
    assert repaired_texts == reconstructed_texts == ("",)

    # Non-vacuous content-survival proof (X-102): the font resource DOES
    # survive recovery, unlike the content stream -- asserted directly
    # against the repaired output, never fabricated.
    with pikepdf.Pdf.open(target) as repaired_pdf:
        font = repaired_pdf.pages[0].Resources.Font.F1
        assert str(font.BaseFont) == "/Helvetica"


# --------------------------------------------------------------------------- #
# AC11 -- `repair` reports only what happened
# --------------------------------------------------------------------------- #


def test_ac11_repair_on_a_healthy_document_reports_no_damage(corpus, tmp_path: Path) -> None:
    source = corpus.path("multipage_text")
    target = tmp_path / "out.pdf"
    result = repair_run(source, output=target, in_place=False, report=True, policy=policy())
    assert result.exit_code == 0
    assert result.warnings == ()
    item = result.items[0]
    assert item.message is not None
    assert "no damage" in item.message.lower()
    assert "recovered" not in item.message.lower()


def test_ac11_repair_on_the_malformed_fixture_lists_findings(tmp_path: Path) -> None:
    target = tmp_path / "out.pdf"
    result = repair_run(MALFORMED_PDF, output=target, in_place=False, report=True, policy=policy())
    assert result.exit_code == 0
    assert len(result.warnings) >= 1
    item = result.items[0]
    assert item.detail is not None
    assert "object_count_before" in item.detail
    assert "page_count_before" in item.detail
    assert "xref_reconstructed" in item.detail


# --------------------------------------------------------------------------- #
# AC12 -- `linearize` is verified structurally
# --------------------------------------------------------------------------- #


def test_ac12_linearize_is_verified_structurally(corpus, tmp_path: Path) -> None:
    import pikepdf

    source = corpus.path("multipage_text")
    target = tmp_path / "linearized.pdf"
    result = linearize_run(source, output=target, in_place=False, policy=policy())
    assert result.exit_code == 0

    with pikepdf.Pdf.open(target) as reopened:
        assert reopened.is_linearized is True
        assert reopened.check_linearization(__import__("io").StringIO()) is True

    head = target.read_bytes()[:1024]
    assert b"/Linearized" in head


def test_ac12_a_failed_linearize_verification_refuses_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, corpus, tmp_path: Path
) -> None:
    import pikepdf

    source = corpus.path("multipage_text")
    target = tmp_path / "target.pdf"
    seed = b"pre-existing, must survive untouched"
    target.write_bytes(seed)

    real_save = pikepdf.Pdf.save

    def _save_without_linearizing(self: Any, *args: Any, **kwargs: Any) -> None:
        kwargs["linearize"] = False
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(pikepdf.Pdf, "save", _save_without_linearizing)

    with pytest.raises(FailureError, match="did not verify"):
        linearize_run(source, output=target, in_place=False, policy=policy(force=True))
    assert target.read_bytes() == seed


# --------------------------------------------------------------------------- #
# AC13 -- safety and exit contract (the op-layer half; subprocess half in
# tests/integration/test_optimize_cli.py)
# --------------------------------------------------------------------------- #


def test_ac13_nonexistent_input_is_exit_4(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.pdf"
    with pytest.raises(NoInputError):
        compress_run(
            [missing],
            lossless=False,
            images="keep",
            image_dpi=150.0,
            image_quality=80,
            pages_spec=None,
            output=tmp_path / "out.pdf",
            out_dir=None,
            name_template=None,
            in_place=False,
            policy=policy(),
        )


def test_ac13_encrypted_input_is_exit_6_naming_decrypt(corpus, tmp_path: Path) -> None:
    source = corpus.path("encrypted_aes256")
    with pytest.raises(AuthError, match="decrypt"):
        compress_run(
            [source],
            lossless=False,
            images="keep",
            image_dpi=150.0,
            image_quality=80,
            pages_spec=None,
            output=tmp_path / "out.pdf",
            out_dir=None,
            name_template=None,
            in_place=False,
            policy=policy(),
        )
    with pytest.raises(AuthError, match="decrypt"):
        repair_run(source, output=tmp_path / "r.pdf", in_place=False, report=False, policy=policy())
    with pytest.raises(AuthError, match="decrypt"):
        linearize_run(source, output=tmp_path / "l.pdf", in_place=False, policy=policy())


def test_ac13_dry_run_writes_nothing(corpus, tmp_path: Path) -> None:
    source = corpus.path("multipage_text")
    target = tmp_path / "out.pdf"
    result = compress_run(
        [source],
        lossless=False,
        images="keep",
        image_dpi=150.0,
        image_quality=80,
        pages_spec=None,
        output=target,
        out_dir=None,
        name_template=None,
        in_place=False,
        policy=policy(dry_run=True),
    )
    assert result.dry_run is True
    assert not target.exists()


def test_ac13_no_destination_at_all_is_a_usage_error(corpus, tmp_path: Path) -> None:
    source = corpus.path("multipage_text")
    with pytest.raises(UsageError):
        repair_run(source, output=None, in_place=False, report=False, policy=policy())


# --------------------------------------------------------------------------- #
# AC14 -- inherited `--in-place` path
# --------------------------------------------------------------------------- #


def test_ac14_compress_in_place_creates_a_byte_identical_backup(corpus, tmp_path: Path) -> None:
    import shutil

    copy_path = tmp_path / "copy.pdf"
    shutil.copy(corpus.path("multipage_text"), copy_path)
    original_bytes = copy_path.read_bytes()

    result = compress_run(
        [copy_path],
        lossless=False,
        images="keep",
        image_dpi=150.0,
        image_quality=80,
        pages_spec=None,
        output=None,
        out_dir=None,
        name_template=None,
        in_place=True,
        policy=policy(in_place=True),
    )
    assert result.exit_code == 0

    backup = copy_path.with_name(copy_path.name + ".bak")
    assert backup.exists()
    assert backup.read_bytes() == original_bytes
