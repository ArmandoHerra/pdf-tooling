# testdata/

Everything else the test suite needs is generated at test time by
`tests/corpus.py` (`PLAN.md` §10). These two binary artifacts are the only
exceptions — each is committed because reproducing what it tests *at test
time* would make the thing under test a function of the current dependency
versions rather than a fixed, reviewable defect. See `tests/corpus.py`'s
module docstring for the general policy and `PDF-06` Design §2 for the
per-artifact argument.

## `malformed.pdf` (439 bytes)

**Provenance.** Hand-authored — an ASCII-editable PDF with four intact
objects (`Catalog` → `Pages` → `Page` → a `Type1/Helvetica` content stream)
and **no `xref` table, no `trailer`, and no `startxref`/`%%EOF` at all**. The
corruption is *deletion*, not byte-mutation, so the object graph above it is
byte-intact and human-readable in a text editor.

**Exact defect.** The cross-reference table and trailer are destroyed
outright (absent from the file). Every object body (`N 0 obj` … `endobj`) is
otherwise well-formed and locatable by a linear scan.

**The four properties `PDF-12`'s `repair` acceptance signal depends on**
(`PDF-06` Design §2, ruled by `decision.md` X-20 — this file's name is
authoritative if a future spec names it differently):

1. **Destroyed xref/trailer.** `grep -c '^xref\|^trailer\|^startxref' testdata/malformed.pdf` returns `0`.
2. **Body objects intact.** All five objects (`1 0 obj` … `5 0 obj`, the
   fifth being the content stream) parse individually; `pikepdf`'s recovery
   pass reconstructs a 1-page document from them.
3. **`pdftoolkit info testdata/malformed.pdf` exits `1`** (not 2, not 4) —
   verified against the landed `info` verb at `PDF-06` commit time.
4. **`pikepdf.open(path, attempt_recovery=True)` recovers the document and
   reports ≥ 1 warning** via `Pdf.get_warnings()` (libqpdf under the hood;
   never a `qpdf` CLI shell-out — `PLAN.md` §7.2 / HC-1 forbids that even for
   test tooling). At authoring time it reports 5: file damage, missing
   `startxref`, xref-table reconstruction, an early EOF on object 5, and a
   missing trailer dictionary while recovering.

`tests/test_testdata.py` pins all four mechanically. **Do not add a second
malformed fixture** — one corpus, one name, reviewed once (`decision.md`
X-20).

## `scanned-page.png` (3054 bytes, 600×200, 8-bit grayscale)

**Provenance.** Synthesized locally with Pillow: black text rendered on a
white background using the `DejaVu Sans Bold` system font (Bitstream Vera
license, bundled with most Linux distributions) at `/usr/share/fonts/truetype/dejavu/`.
**Not derived from, copied from, or in any way sourced from
`$PDF_TOOLKIT_SAMPLES_DIR`** — the operator's real-document corpus is never
an input to anything under `testdata/` (`PLAN.md` §10.1 rule 4). `AC17`
mechanizes this as a standing check: no file under `testdata/` may ever share
a SHA-256 with any file in the samples directory.

**Why committed rather than generated at test time.** OCR success on
Pillow-drawn text depends on the host's installed font set — the same script
run on a machine without `DejaVu Sans Bold` would draw different glyphs and
tesseract's recovery would become a function of font availability rather than
of the `ocr` verb. Committing the raster pins tesseract's input so the only
variable left, across machines and CI legs, is the installed tesseract
version.

**What it proves.** `tesseract testdata/scanned-page.png stdout` recovers the
literal text `PDF TOOLKIT OCR FIXTURE` — verified at authoring time against
tesseract 5.5.0 with the `eng` language pack. Consumed by `PDF-15`'s `ocr`
acceptance signal (a real scan from which text can be recovered, as opposed
to the generated corpus, which never contains an unrecoverable page).
