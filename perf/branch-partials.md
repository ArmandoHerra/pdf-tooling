# Branch-coverage partials — the retained list, by module

**This is a one-off, out-of-band measurement and never a gate.**
`[tool.coverage.run] branch = false` in `pyproject.toml` is unchanged and
`--cov-fail-under` keeps measuring lines. Branch tracking was forced by
`--cov-branch` on the command line of a single run, under the `PDF-29` protocol,
and the run it belongs to is the `variant: "branch-true"` record in
`perf/gate-timings.jsonl`. See `perf/README.md` for how to read the pair.

**Sort key: descending `partial` (partially-taken branches), with `module` as
the tiebreaker.** The file exists to be read from the top as a work queue, so
the order is part of the artefact and is stated here rather than left to a
regeneration to change silently.

## Provenance — copied from the record this list belongs to

A list without this header is a list about nothing (`perf/README.md`'s `commit`
rule). Every field below is read out of the `branch-true` record, not retyped.

| Field | Value |
|---|---|
| `commit` | `7d0360edc44d40ddd68599bf7f956b959689d427` |
| `timestamp` | `2026-09-16T07:45:15-0600` |
| `target` / `variant` | `cover` / `branch-true` |
| `cache_state` | `warm` |
| `quiet` | `true` |
| `interpreter` | `3.12.13` via `uv run python`, prefix `/home/station-01/repos/ClaudeCode_Harness/apps/pdf-tooling/.venv` |
| `host` | `Linux-7.0.0-31-generic-x86_64-with-glibc2.43` (`x86_64`) |
| `engines` | `tesseract`: `/usr/bin/tesseract` · `soffice`: `/usr/bin/soffice` |
| `dirty` | `true` |
| `tests_collected` | `5125` |
| `coverage_pct` | `93.29` |
| `wall_clock_s` | `10819.212` |

`coverage_pct` is the record's own field and, under branch mode, it carries the
COMBINED line-and-branch figure rather than branch coverage -- see the totals
below.

## Totals, from the run's own JSON report

**Read `percent_covered` carefully: under branch mode it is the COMBINED
line-and-branch figure, not branch coverage.** coverage.py's terminal `TOTAL`
row reports that combined number in its `Cover` column, and it is the number
`scripts/measure_gate.py` parses into the record's `coverage_pct`. The
branch-only figure is `percent_branches_covered` and the line-only figure is
`percent_statements_covered`; quoting the combined number as a branch total
overstates branch coverage substantially. Every value below is read out of the
run's own JSON report, not retyped.

| Total | Value |
|---|---|
| `num_statements` | `6666` |
| `covered_lines` | `6343` |
| `missing_lines` | `323` |
| `num_branches` | `1676` |
| `covered_branches` | `1439` |
| `num_partial_branches` | `193` |
| `missing_branches` | `237` |
| `percent_statements_covered` | `95.15451545154515` |
| `percent_branches_covered` | `85.85918854415274` |
| `percent_covered` | `93.28698153919923` |

## The list

`partial` is coverage.py's `num_partial_branches` — a branch whose line ran but
only one of whose arms did. `missing_br` is `missing_branches`. `pct` is the
module's own combined line+branch percentage.

| # | module | stmts | miss | branches | partial | missing_br | pct |
|---|---|---|---|---|---|---|---|
| 1 | `src/pdf_tooling/adapters/pypdf_structure.py` | 489 | 91 | 160 | 39 | 55 | 77.50 |
| 2 | `src/pdf_tooling/cli/common.py` | 365 | 19 | 132 | 14 | 16 | 92.96 |
| 3 | `src/pdf_tooling/ops/compose.py` | 326 | 12 | 94 | 9 | 9 | 95.00 |
| 4 | `src/pdf_tooling/adapters/tesseract_ocr.py` | 114 | 13 | 30 | 8 | 8 | 85.42 |
| 5 | `src/pdf_tooling/safety/atomic.py` | 291 | 10 | 82 | 8 | 10 | 94.64 |
| 6 | `src/pdf_tooling/cli/cmd_meta_set.py` | 39 | 4 | 14 | 5 | 5 | 83.02 |
| 7 | `src/pdf_tooling/cli/cmd_watermark.py` | 52 | 7 | 18 | 5 | 5 | 82.86 |
| 8 | `src/pdf_tooling/cli/main.py` | 134 | 6 | 34 | 5 | 5 | 93.45 |
| 9 | `src/pdf_tooling/ops/procpool.py` | 93 | 10 | 30 | 5 | 5 | 87.80 |
| 10 | `src/pdf_tooling/output/logging.py` | 73 | 3 | 34 | 5 | 5 | 92.52 |
| 11 | `src/pdf_tooling/safety/paths.py` | 138 | 12 | 52 | 5 | 9 | 88.95 |
| 12 | `src/pdf_tooling/adapters/pikepdf_structure.py` | 212 | 24 | 28 | 4 | 8 | 86.67 |
| 13 | `src/pdf_tooling/cli/cmd_rasterize.py` | 48 | 3 | 16 | 4 | 4 | 89.06 |
| 14 | `src/pdf_tooling/ops/ocr.py` | 142 | 3 | 32 | 4 | 4 | 95.98 |
| 15 | `src/pdf_tooling/ops/optimize.py` | 198 | 10 | 62 | 4 | 6 | 93.85 |
| 16 | `src/pdf_tooling/ops/raster.py` | 134 | 2 | 36 | 4 | 4 | 96.47 |
| 17 | `src/pdf_tooling/cli/cmd_office.py` | 36 | 3 | 10 | 3 | 3 | 86.96 |
| 18 | `src/pdf_tooling/cli/cmd_stamp.py` | 38 | 3 | 12 | 3 | 3 | 88.00 |
| 19 | `src/pdf_tooling/cli/cmd_tables.py` | 68 | 1 | 16 | 3 | 3 | 95.24 |
| 20 | `src/pdf_tooling/cli/cmd_text.py` | 49 | 1 | 12 | 3 | 3 | 93.44 |
| 21 | `src/pdf_tooling/cli/password.py` | 92 | 7 | 32 | 3 | 3 | 91.94 |
| 22 | `src/pdf_tooling/ops/inspect.py` | 59 | 2 | 14 | 3 | 3 | 93.15 |
| 23 | `src/pdf_tooling/ops/overlay.py` | 148 | 2 | 28 | 3 | 3 | 97.16 |
| 24 | `src/pdf_tooling/cli/cmd_doctor.py` | 39 | 1 | 8 | 2 | 2 | 93.62 |
| 25 | `src/pdf_tooling/cli/cmd_encrypt.py` | 71 | 2 | 26 | 2 | 2 | 95.88 |
| 26 | `src/pdf_tooling/cli/cmd_meta_get.py` | 54 | 1 | 10 | 2 | 2 | 95.31 |
| 27 | `src/pdf_tooling/cli/cmd_ocr.py` | 51 | 2 | 14 | 2 | 2 | 93.85 |
| 28 | `src/pdf_tooling/ops/batch.py` | 66 | 2 | 20 | 2 | 2 | 95.35 |
| 29 | `src/pdf_tooling/ops/merge.py` | 95 | 2 | 28 | 2 | 2 | 96.75 |
| 30 | `src/pdf_tooling/ops/metadata.py` | 95 | 6 | 30 | 2 | 6 | 90.40 |
| 31 | `src/pdf_tooling/ops/pages.py` | 158 | 1 | 38 | 2 | 2 | 98.47 |
| 32 | `src/pdf_tooling/output/__init__.py` | 37 | 0 | 12 | 2 | 2 | 95.92 |
| 33 | `src/pdf_tooling/output/table.py` | 36 | 2 | 16 | 2 | 2 | 92.31 |
| 34 | `src/pdf_tooling/ports/ocr.py` | 24 | 1 | 4 | 2 | 2 | 89.29 |
| 35 | `src/pdf_tooling/safety/_faults.py` | 27 | 3 | 6 | 2 | 2 | 84.85 |
| 36 | `src/pdf_tooling/__main__.py` | 4 | 0 | 2 | 1 | 1 | 83.33 |
| 37 | `src/pdf_tooling/adapters/__init__.py` | 24 | 5 | 2 | 1 | 1 | 76.92 |
| 38 | `src/pdf_tooling/adapters/pdfium_raster.py` | 73 | 11 | 8 | 1 | 5 | 80.25 |
| 39 | `src/pdf_tooling/adapters/pdfplumber_text.py` | 75 | 4 | 14 | 1 | 3 | 92.13 |
| 40 | `src/pdf_tooling/adapters/soffice_office.py` | 69 | 2 | 14 | 1 | 1 | 96.39 |
| 41 | `src/pdf_tooling/adapters/subprocess_util.py` | 90 | 1 | 16 | 1 | 1 | 98.11 |
| 42 | `src/pdf_tooling/cli/cmd_compose.py` | 35 | 1 | 6 | 1 | 1 | 95.12 |
| 43 | `src/pdf_tooling/cli/cmd_info.py` | 50 | 0 | 16 | 1 | 1 | 98.48 |
| 44 | `src/pdf_tooling/cli/cmd_merge.py` | 33 | 1 | 4 | 1 | 1 | 94.59 |
| 45 | `src/pdf_tooling/cli/cmd_split.py` | 29 | 1 | 4 | 1 | 1 | 93.94 |
| 46 | `src/pdf_tooling/ops/crypto.py` | 151 | 2 | 42 | 1 | 1 | 98.45 |
| 47 | `src/pdf_tooling/ops/document_password.py` | 55 | 1 | 14 | 1 | 1 | 97.10 |
| 48 | `src/pdf_tooling/ops/office.py` | 72 | 1 | 14 | 1 | 1 | 97.67 |
| 49 | `src/pdf_tooling/ops/pagerange.py` | 128 | 1 | 50 | 1 | 1 | 98.88 |
| 50 | `src/pdf_tooling/ops/split.py` | 123 | 1 | 36 | 1 | 1 | 98.74 |
| 51 | `src/pdf_tooling/ops/textract.py` | 239 | 2 | 60 | 1 | 1 | 99.00 |
| 52 | `src/pdf_tooling/output/json.py` | 17 | 1 | 4 | 1 | 1 | 90.48 |
| 53 | `src/pdf_tooling/ports/structure.py` | 131 | 2 | 2 | 1 | 1 | 97.74 |
| 54 | `src/pdf_tooling/ports/text.py` | 48 | 1 | 2 | 1 | 1 | 96.00 |
| 55 | `src/pdf_tooling/safety/naming.py` | 46 | 1 | 20 | 1 | 1 | 96.97 |
| 56 | `src/pdf_tooling/__init__.py` | 10 | 0 | 2 | 0 | 0 | 100.00 |
| 57 | `src/pdf_tooling/adapters/pdfium_text.py` | 52 | 10 | 6 | 0 | 4 | 75.86 |
| 58 | `src/pdf_tooling/adapters/reportlab_compose.py` | 131 | 0 | 32 | 0 | 0 | 100.00 |
| 59 | `src/pdf_tooling/cli/__init__.py` | 0 | 0 | 0 | 0 | 0 | 100.00 |
| 60 | `src/pdf_tooling/cli/cmd_compress.py` | 48 | 0 | 14 | 0 | 0 | 100.00 |
| 61 | `src/pdf_tooling/cli/cmd_create.py` | 45 | 0 | 8 | 0 | 0 | 100.00 |
| 62 | `src/pdf_tooling/cli/cmd_decrypt.py` | 28 | 0 | 4 | 0 | 0 | 100.00 |
| 63 | `src/pdf_tooling/cli/cmd_delete.py` | 31 | 0 | 8 | 0 | 0 | 100.00 |
| 64 | `src/pdf_tooling/cli/cmd_extract.py` | 27 | 0 | 6 | 0 | 0 | 100.00 |
| 65 | `src/pdf_tooling/cli/cmd_linearize.py` | 28 | 0 | 4 | 0 | 0 | 100.00 |
| 66 | `src/pdf_tooling/cli/cmd_meta.py` | 4 | 0 | 0 | 0 | 0 | 100.00 |
| 67 | `src/pdf_tooling/cli/cmd_permissions.py` | 28 | 0 | 4 | 0 | 0 | 100.00 |
| 68 | `src/pdf_tooling/cli/cmd_reorder.py` | 31 | 0 | 8 | 0 | 0 | 100.00 |
| 69 | `src/pdf_tooling/cli/cmd_repair.py` | 28 | 0 | 4 | 0 | 0 | 100.00 |
| 70 | `src/pdf_tooling/cli/cmd_rotate.py` | 36 | 0 | 12 | 0 | 0 | 100.00 |
| 71 | `src/pdf_tooling/cli/cmd_version.py` | 39 | 2 | 0 | 0 | 0 | 94.87 |
| 72 | `src/pdf_tooling/cli/exit_codes.py` | 10 | 0 | 0 | 0 | 0 | 100.00 |
| 73 | `src/pdf_tooling/errors.py` | 56 | 0 | 2 | 0 | 0 | 100.00 |
| 74 | `src/pdf_tooling/models.py` | 183 | 1 | 4 | 0 | 0 | 99.47 |
| 75 | `src/pdf_tooling/ops/__init__.py` | 0 | 0 | 0 | 0 | 0 | 100.00 |
| 76 | `src/pdf_tooling/ports/__init__.py` | 72 | 0 | 18 | 0 | 0 | 100.00 |
| 77 | `src/pdf_tooling/ports/compose.py` | 44 | 0 | 0 | 0 | 0 | 100.00 |
| 78 | `src/pdf_tooling/ports/office.py` | 22 | 0 | 0 | 0 | 0 | 100.00 |
| 79 | `src/pdf_tooling/ports/raster.py` | 26 | 0 | 0 | 0 | 0 | 100.00 |
| 80 | `src/pdf_tooling/safety/__init__.py` | 6 | 0 | 0 | 0 | 0 | 100.00 |
| 81 | `src/pdf_tooling/safety/confirm.py` | 25 | 0 | 8 | 0 | 0 | 100.00 |
| 82 | `src/pdf_tooling/safety/policy.py` | 17 | 0 | 2 | 0 | 0 | 100.00 |
| 83 | `src/pdf_tooling/safety/tempnames.py` | 13 | 0 | 2 | 0 | 0 | 100.00 |
| 84 | `src/pdf_tooling/secret.py` | 43 | 0 | 8 | 0 | 0 | 100.00 |

