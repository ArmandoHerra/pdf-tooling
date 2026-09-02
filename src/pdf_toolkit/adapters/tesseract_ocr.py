"""``OcrEngine`` adapter — the ``tesseract`` binary, bound by pytesseract.

Unlike the five wheel-backed ports, this one can legitimately be absent: the
binary is a system package the user installs. Absence is therefore a *report*
(``available:false`` with an OS-aware hint), and a verb that needs it exits
**3** — never a traceback, and never a degraded result that looks real
(``PLAN.md`` §12 R-09).

HONEST LANGUAGE ENUMERATION
---------------------------
``detail`` lists the tessdata languages that are **actually installed**, read
from the binary itself. A tool that advertised language support it does not have
would fail at the worst possible moment — mid-batch, on someone's documents —
and multi-language OCR is deferred (B-009) precisely so this stays a statement
of fact rather than a promise.

WHY THE SPAWN IS OURS AND NOT pytesseract's
-------------------------------------------
Every spawn here goes through ``subprocess_util.run``, which puts the child in
its own process group and kills the **group** on timeout. pytesseract 0.3.13's
own ``run_tesseract()`` does not pass ``start_new_session`` and calls
``terminate()`` on the direct child only, so a tesseract that has itself forked
leaves the grandchild running. That is the exact shape of the leak recorded in
``expertise/product.yaml`` — 163 orphaned daemons, roughly 6.5 GiB resident, on
this host — and it is why the OCR spec builds its argv and spawns it here rather
than calling the binding's runner.
"""

from __future__ import annotations

import re
import shutil
from typing import TYPE_CHECKING, Final

from pdf_toolkit.adapters import AdapterProbe, package_probe, subprocess_util
from pdf_toolkit.errors import FailureError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

    from PIL.Image import Image

__all__ = ["ADAPTER", "BINARY", "PROBE_TIMEOUT_S", "TesseractOcrAdapter"]

_NAME: Final[str] = "tesseract"

#: A module-level string literal on purpose: the licence walk in
#: ``tests/test_license_policy.py`` resolves a spawn's ``argv[0]`` through
#: exactly this shape, so a binary name that lives in a `Final[str]` stays
#: statically auditable while a computed one would be refused outright.
BINARY: Final[str] = "tesseract"

_BINDING_DISTRIBUTION: Final[str] = "pytesseract"
_BINDING_MODULE: Final[str] = "pytesseract"

#: Short by design. A version probe that hangs is an unavailable engine, not a
#: reason for ``doctor`` to hang with it.
PROBE_TIMEOUT_S: Final[float] = 5.0

_CAPABILITIES: Final[frozenset[str]] = frozenset({"ocr", "hocr", "languages"})

#: ``tesseract 5.5.0`` -> ``5.5.0``. Anchored, so a line that merely mentions the
#: binary cannot be mistaken for a version line.
_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"^tesseract\s+v?([0-9][0-9A-Za-z.\-]*)")

#: PDF-15 (`ocr`), Design D3 -- the ``-c`` config that makes tesseract's PDF
#: output TEXT-ONLY (invisible render mode, no re-rasterized image of its
#: own). This is what makes "pixels are never touched" achievable at all:
#: without it tesseract's PDF output embeds its OWN copy of the page image.
_TEXTONLY_CONFIG: Final[str] = "textonly_pdf=1"

#: The scratch filenames `text_layer` reuses across every page of a run
#: (Design §D2: pages are processed sequentially, one at a time, so reusing
#: one name keeps disk usage bounded rather than growing with page count).
_SCRATCH_INPUT_NAME: Final[str] = "ocr-input.png"
_SCRATCH_OUTPUT_BASENAME: Final[str] = "ocr-output"


def _parse_version(line: str) -> str | None:
    match = _VERSION_RE.match(line.strip())
    return match.group(1) if match else None


def _parse_languages(stdout: str) -> tuple[str, ...]:
    """Languages from ``--list-langs``, header line dropped, sorted and deduped.

    The first line is a human sentence naming the tessdata directory and a
    count; everything after it is one language code per line.
    """
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    body = [line for line in lines[1:] if " " not in line]
    return tuple(sorted(set(body)))


#: PDF-15 (`ocr`), Design D4 route (a) -- the four page rotations ISO 32000
#: permits. Anything else is a defect elsewhere (`PageInfo.rotation` is
#: normalised to this set at the source), not a value this function guesses
#: at.
_SUPPORTED_ROTATIONS: Final[frozenset[int]] = frozenset({0, 90, 180, 270})


def _quarter_turn(
    ctm: tuple[float, float, float, float, float, float], degrees: int
) -> tuple[float, float, float, float, float, float]:
    """*ctm* composed with an EXACT counter-clockwise turn of *degrees* (B-094).

    *degrees* is one of 90/180/270; anything else is returned unchanged, which
    is what makes ``rotation == 0`` a no-op at the call site.

    ``pypdf.Transformation.rotate()`` builds its matrix from
    ``math.cos``/``math.sin``, so a 90 degree turn carries
    ``cos(pi/2) == 6.123233995736766e-17`` rather than ``0`` into the layer's
    ``cm`` operator. That residue is far too small to move a glyph — it is
    ~1e-14 pt across a Letter page — but it is not too small to be *read*:
    ``pdfplumber`` derives each character's ``upright`` flag from those matrix
    entries by comparing them against zero, so the epsilon flips ``upright``
    and its word grouping then emits one character per line instead of whole
    words. Measured on the AC7 fixture: with ``rotate(90)`` the product's own
    ``TextEngine`` returned ``'P\\nD\\nF\\nT\\nO...'``; with the exact matrix
    below it returns ``'PDF\\nTOOLKIT\\nOCR\\nFIXTURE'``, and the layer's
    per-character matrices become exactly those of the same layer stamped onto
    an unrotated page (``(0, -0.99980004, 0.99920064, 0)``, translations within
    0.16 pt) rather than merely close to them.

    Composition order matches ``Transformation.rotate``'s own
    (``self.matrix @ rotation``), so this is a drop-in for it at the four
    right angles and nothing else changes. Kept pure and pypdf-free so it can
    be unit-tested without an engine (``adapters/__init__``'s import rule).
    """
    a, b, c, d, e, f = ctm
    if degrees == 90:
        return (-b, a, -d, c, -f, e)
    if degrees == 180:
        return (-a, -b, -c, -d, -e, -f)
    if degrees == 270:
        return (b, -a, d, -c, f, -e)
    return ctm


def _normalize_layer_geometry(
    raw_pdf_bytes: bytes,
    *,
    page_width_pt: float,
    page_height_pt: float,
    rotation: int,
) -> bytes:
    """Design §D4 route (a) -- the one genuine design gap this spec closes.

    ``StructureEngine.composite_layer`` (`ports/structure.py:606`) merges a
    one-page layer onto the original page via a raw ``page.merge_page`` --
    no transform, no matrix argument. So the layer handed to it must
    ALREADY be sized to the original page's own UNROTATED ``MediaBox``
    (*page_width_pt* x *page_height_pt*) and, when the page carries a
    non-zero ``/Rotate``, must already carry the geometric INVERSE of that
    rotation baked into its content -- otherwise the text lands rotated
    and/or off the page it was read from.

    tesseract's own page is sized to the DISPLAYED (post-rotation) view,
    because `RasterEngine.render_page` renders in that same orientation
    (Design §D2 step 2; `pdfium_raster.py`'s own ``_displayed_size``). This
    function measures that box back (never assumes it -- tesseract's own
    rounding is not trusted) and applies ONE composed transform:

    1. **Scale** the measured box to the EXACT expected display dimensions
       (``page_height_pt`` x ``page_width_pt`` swapped for a 90/270
       rotation, unchanged otherwise) -- this is what makes the final box
       exact rather than merely within the 0.5 pt tolerance D4 names.
    2. **Rotate + translate** by the geometric inverse of *rotation*, so
       that when the merged page is later displayed with the ORIGINAL
       page's own ``/Rotate`` re-applied, the text lands back on the exact
       picture tesseract read. Derived directly from the PDF ``/Rotate``
       convention (clockwise-for-display) rather than from
       ``PageObject.transfer_rotation_to_content`` (which solves the
       opposite direction and, critically, is not reachable from ``ops/``
       at all -- it is a pypdf method and this whole function exists
       precisely because ``ops/ocr.py`` cannot import pypdf).

    Verified against a live ``/Rotate 90`` fixture end to end (this spec's
    Implementation Log) rather than by derivation alone -- AC7 is exactly
    this function's own acceptance signal.
    """
    import io

    from pypdf import PdfReader, PdfWriter, Transformation
    from pypdf.errors import PdfReadError

    if rotation not in _SUPPORTED_ROTATIONS:
        raise FailureError(f"unsupported page rotation {rotation} (expected one of 0/90/180/270)")

    try:
        reader = PdfReader(io.BytesIO(raw_pdf_bytes))
        page = reader.pages[0]
    except (PdfReadError, IndexError, OSError, ValueError) as error:
        raise FailureError(
            f"tesseract's text-layer page could not be read back: {error}"
        ) from error

    raw_box = page.mediabox
    raw_width, raw_height = float(raw_box.width), float(raw_box.height)
    if raw_width <= 0 or raw_height <= 0:
        raise FailureError("tesseract produced a degenerate (zero-area) text-layer page")

    display_width, display_height = (
        (page_height_pt, page_width_pt)
        if rotation in (90, 270)
        else (page_width_pt, page_height_pt)
    )

    # Step 0: move the measured box's own origin to (0, 0) before scaling --
    # tesseract's own output is expected at (0, 0) already, but this makes
    # no assumption of it.
    trsf = Transformation().translate(-float(raw_box.left), -float(raw_box.bottom))
    # Step 1: scale the measured box to the EXACT expected display size.
    trsf = trsf.scale(display_width / raw_width, display_height / raw_height)
    # Step 2: rotate + translate by the inverse of `rotation` -- see the
    # docstring above for the derivation. `rotation == 0` needs neither.
    # The quarter turn goes through `_quarter_turn`, not
    # `Transformation.rotate()`: see that function's docstring for the
    # trigonometric residue this avoids and what it was measured to break.
    if rotation == 90:
        trsf = Transformation(_quarter_turn(trsf.ctm, 90)).translate(page_width_pt, 0)
    elif rotation == 180:
        trsf = Transformation(_quarter_turn(trsf.ctm, 180)).translate(page_width_pt, page_height_pt)
    elif rotation == 270:
        trsf = Transformation(_quarter_turn(trsf.ctm, 270)).translate(0, page_height_pt)

    page.add_transformation(trsf, expand=False)
    page.mediabox.lower_left = (0, 0)
    page.mediabox.upper_right = (page_width_pt, page_height_pt)
    page.cropbox.lower_left = (0, 0)
    page.cropbox.upper_right = (page_width_pt, page_height_pt)

    writer = PdfWriter()
    writer.add_page(page)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class TesseractOcrAdapter:
    """The ``tesseract``-binary-backed ``OcrEngine``."""

    kind: Final[str] = "system-binary"

    @property
    def adapter_name(self) -> str:
        return _NAME

    def capabilities(self) -> frozenset[str]:
        return _CAPABILITIES

    def probe(self) -> AdapterProbe:
        """Locate the binary, read its version, and enumerate its languages.

        ``PATH`` is consulted at probe time and never cached across
        ``ports.reset_cache()``: the acceptance signal for this whole spec
        manipulates ``PATH`` and expects exactly one row to flip.
        """
        if shutil.which(BINARY) is None:
            return AdapterProbe(available=False, version=None, detail=None)

        # argv[0] is the module-level `Final[str]`, NOT the absolute path
        # `shutil.which` just returned. Both consult PATH identically -- Popen
        # without a shell uses execvp semantics for a name containing no slash --
        # but only the constant is statically resolvable, and
        # tests/test_import_boundaries.py Section 2 refuses a spawn whose argv[0]
        # it cannot resolve and check against the forbidden set. A guarantee that
        # a reader can verify by grepping one constant beats one that requires
        # tracing a local variable.
        # `env=subprocess_util.probe_env()` -- the probe-path sandbox (PDF-20,
        # D2). The environment is INHERITED and only the five home-rooted
        # variables are overridden, so `TESSDATA_PREFIX` and `PATH` both survive
        # and this probe reports exactly what it reported before.
        run = subprocess_util.run(
            [BINARY, "--version"],
            timeout=PROBE_TIMEOUT_S,
            check=False,
            env=subprocess_util.probe_env(),
        )
        first = run.first_line() or run.first_line("stderr")
        version = _parse_version(first)

        details: list[str] = []
        if version is None:
            # Present but unparsed. Report the raw line and NOT a version --
            # `doctor` never prints a version it did not actually read.
            unparsed = f"version line not recognised: {first!r}" if first else "no version line"
            details.append(unparsed)
        languages = self.languages()
        if languages:
            details.append("languages: " + ", ".join(languages))
        else:
            details.append("languages: none reported")

        return AdapterProbe(available=True, version=version, detail="; ".join(details))

    def languages(self) -> tuple[str, ...]:
        """The tessdata languages installed on this host, sorted.

        What is reported is what ``--list-langs`` says is there. This product
        does not claim language support it cannot demonstrate.
        """
        if shutil.which(BINARY) is None:
            return ()
        # The probe-path sandbox again -- see `probe()`. `TESSDATA_PREFIX` is
        # inherited unchanged, which is what keeps the reported language set
        # identical to the one an OCR run would use.
        run = subprocess_util.run(
            [BINARY, "--list-langs"],
            timeout=PROBE_TIMEOUT_S,
            check=False,
            env=subprocess_util.probe_env(),
        )
        return _parse_languages(run.stdout or run.stderr)

    def binding_probe(self) -> AdapterProbe:
        """The Python binding's own presence, reported separately from the binary.

        The binding is a hard dependency (a wheel) and the binary is not, so
        conflating them would report a broken install and a missing system
        package identically.
        """
        return package_probe(_BINDING_MODULE, _BINDING_DISTRIBUTION)

    # -- PDF-15 (`ocr`), appended at the end of the class -------------------- #

    def text_layer(
        self,
        image: Image,
        *,
        lang: str,
        psm: int,
        dpi: float,
        page_width_pt: float,
        page_height_pt: float,
        rotation: int,
        timeout: float,
        scratch_dir: Path,
    ) -> bytes:
        """See the Protocol docstring in ``ports/ocr.py``."""
        input_path = scratch_dir / _SCRATCH_INPUT_NAME
        output_base = scratch_dir / _SCRATCH_OUTPUT_BASENAME
        output_path = output_base.with_suffix(".pdf")

        # `image.save` -- not one of Section 1's forbidden names (a stdlib
        # write chokepoint violation), and this is scratch space, never a
        # product destination: see `safety.atomic.ScratchDir`'s own
        # docstring for the boundary this stays inside of. `dpi=` is set
        # too, belt-and-braces alongside the CLI `--dpi` below.
        image.save(input_path, format="PNG", dpi=(dpi, dpi))

        # argv[0] is the module-level `Final[str]` constant -- see the note
        # on the same line in `probe()`. `--dpi` is D3's one deliberate
        # deviation from pytesseract's own emitted argv (Design §D4 route
        # (a)): forcing resolution explicitly, rather than leaving it to
        # the saved image's own metadata, is what makes the produced page's
        # own box a function of OUR chosen render DPI rather than of
        # whatever a given image format happens to embed.
        # The list literal is inlined directly into the call -- not built up
        # in a local `argv` variable first -- because
        # `tests/test_import_boundaries.py` Section 2's `_static_argv0` reads
        # `node.args[0]` at the CALL SITE itself; a variable reference is not
        # statically resolvable even though its value is (see the identical
        # note on the same shape in `probe()` above).
        run = subprocess_util.run(
            [
                BINARY,
                str(input_path),
                str(output_base),
                "-l",
                lang,
                "--psm",
                str(psm),
                "--dpi",
                str(round(dpi)),
                "-c",
                _TEXTONLY_CONFIG,
                "pdf",
            ],
            timeout=timeout,
            check=False,
        )
        if run.timed_out:
            raise FailureError(f"tesseract timed out after {timeout:g}s recognising one page")
        if run.returncode != 0:
            tail = "\n".join(run.stderr.strip().splitlines()[-5:])
            detail = f": {tail}" if tail else ""
            raise FailureError(f"tesseract exited {run.returncode}{detail}")
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise FailureError(
                f"tesseract exited 0 but produced no readable text layer at {output_path}"
            )

        raw_pdf_bytes = output_path.read_bytes()
        return _normalize_layer_geometry(
            raw_pdf_bytes,
            page_width_pt=page_width_pt,
            page_height_pt=page_height_pt,
            rotation=rotation,
        )


ADAPTER: Final[TesseractOcrAdapter] = TesseractOcrAdapter()
