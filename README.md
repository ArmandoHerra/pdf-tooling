# pdf-toolkit

An Apache-2.0 PDF toolkit CLI in Python. One safe command-line tool (`pdftoolkit`) for the common PDF chores — merge, split, extract, rotate, PDF→images, images→PDF, create, text/tables, compress, encrypt, metadata, watermark, OCR, and Office→PDF — built on a permissively licensed engine stack (pypdf, pypdfium2, reportlab, pikepdf, pdfplumber, Tesseract, LibreOffice) with nothing AGPL or GPL on the call graph.

Safety is first-class: a global `--dry-run`, no-clobber by default, atomic write-to-temp-then-rename, and inputs that are never mutated unless you ask for `--in-place`.

## Getting Started

```bash
# Prerequisites: Python >= 3.11 and uv (https://docs.astral.sh/uv/)
git clone https://github.com/ArmandoHerra/pdf-toolkit.git
cd pdf-toolkit
uv sync
uv run pdftoolkit --help
```

Optional engines for `ocr` and `convert`: `tesseract` and LibreOffice (`soffice`) on your `PATH`. `pdftoolkit doctor` reports what is available.

## Development

```bash
make init      # install dev dependencies
make test      # run the test suite
make ci        # lint, typecheck, tests, security and license gates
```

Contributions are accepted under the Developer Certificate of Origin (`git commit -s`).

## License

Apache-2.0. The `LICENSE`, `NOTICE`, and generated `THIRD_PARTY_LICENSES` files land with the first implementation spec.
