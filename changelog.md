# Changelog

All notable changes to pdf-toolkit, newest first. **One entry per implemented spec,
written by that spec's own commit** — never batched, never back-filled, never edited
afterwards (a correction is a new entry).

Entry format: `## [PDF-NN] <Spec title> — <YYYY-MM-DD>`, then 1–5 bullets.
New entries are inserted **directly below the anchor line**, above the previous newest entry.

Three rules bind every entry:

1. **Append at the top, at the anchor.** Never at the bottom, and never inside another
   entry.
2. **Each spec's own commit writes its own entry**, so `git show <sha> -- changelog.md`
   proves the entry and the code landed together.
3. **Never edit a landed entry.** A correction is a new entry with a new date.

Audit this file per commit with `git show <sha> -- changelog.md`, never with a heading
grep at `HEAD` — a grep at `HEAD` is exactly what hides a lost prepend.

<!-- CHANGELOG-ANCHOR: insert new entries directly below this line, newest first -->

## [PDF-02] CI, license gate & release skeleton — 2026-08-29
- Added `.github/workflows/ci.yml`: ten parallel jobs (`lint`, `typecheck`, `test` on
  {3.11,3.12,3.13,3.14}x{ubuntu-latest,macos-14}, `engines-present`, `without-engines`,
  `sast`, `vulncheck`, `secret-scan`, `license-gate`, `build`), every action SHA-pinned,
  workflow-level `contents: read` and no job above it.
- Added `scripts/licenses.py`: generates `THIRD_PARTY_LICENSES` from a dedicated
  `--no-dev --all-extras` Python 3.11 environment (never the ambient venv) and gates the
  distributed closure on `AGPL|GPL|LGPL`. MPL-2.0 passes by design (`pikepdf` bundles
  libqpdf, PLAN §12 R-11); `UNKNOWN` fails; the allowlist is present, commented and empty.
- Added `tests/test_license_policy.py`: an AST walk (never a text grep) over every file
  under `src/` for forbidden imports, `subprocess` argv[0] and `shutil.which` arguments,
  with permanent positive and negative self-tests proving `gs` inside an identifier does
  not false-positive, plus the `subprocess_util.py` spawn-chokepoint assertion.
- Added `.github/workflows/release.yml` (tag-gated, PyPI Trusted Publishing, **configured
  and never fired**), `.github/dependabot.yml` (`uv` + `github-actions`), and
  `scripts/assert_skips.py` / `scripts/assert_artifacts.py`.
- Rewired the `licenses` and `secret-scan` Makefile targets; `secret-scan` now hard-fails
  with an install hint instead of exiting 0 when `gitleaks` is absent.

## [PDF-01] Project scaffold & CLI spine — 2026-08-29
- Added `pyproject.toml` with the full PLAN §7.1 runtime dependency set and committed `uv.lock`.
- Added the `src/pdf_toolkit/` six-layer skeleton, the Typer root with all §4.2 global flags,
  `errors.py`/`exit_codes.py`, the table/JSON/NDJSON renderers, the redacting stderr logger,
  and `SafetyPolicy`.
- Added the placeholder `version` verb, the 18-target `Makefile`, six documentation skeletons,
  `changelog.md`, and `.scratch/` to `.gitignore`.
