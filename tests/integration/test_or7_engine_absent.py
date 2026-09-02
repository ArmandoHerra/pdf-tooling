"""OR-7 / §D12.1 — an ABSENT engine is knowable at plan time, on BOTH verbs.

The contract, stated by ruling OR-7 (`decision.md` §0.5) and by PDF-15 §D12.1
in terms:

> `--dry-run` MIRRORS the exit code the real run would produce (`dry == real`),
> so `cmd --dry-run && cmd` short-circuits.
> ... a dry run against an ABSENT binary predicts and exits **3**.

This module is deliberately CROSS-VERB rather than living in either
`test_ocr.py` or `test_office.py`. `ocr` and `convert` are the only two
system-binary verbs, D12.2's first row applies to both identically, and B-096
was exactly the failure of proving it on only one of them: `ops/ocr.py`
demanded its engine ABOVE the `if policy.dry_run:` return and was correct,
while `ops/office.py` demanded it BELOW and reported `would_exit: 0` where the
real run exited 3 — so `convert --dry-run && convert` green-lit a run that then
failed. A single parametrized pair is what keeps the two verbs from drifting
apart again: any future verb-local "fix" that regresses one arm reddens this
module by name.

**Why the engine is HIDDEN and never SHADOWED.** `helpers/engine_hiding.py`
removes the binary from PATH so `shutil.which` returns `None`. A shim that
exists but fails would make the engine *present but broken*, which is D12.2's
explicit **carve-out** (dry 0 / real non-zero — correct, not a defect): the
probe would silently assert a different row than the one under test. The helper
asserts the binary is genuinely unresolvable before returning, so this probe
cannot be blind.

**Why these arms run in BOTH CI configurations.** Neither fixture needs an
engine to BUILD (a `.txt` for `convert`; `testdata/scanned-page.png` composed
through the always-present pdfium/Pillow wheels for `ocr`), and hiding an
already-absent binary is a no-op that leaves the asserted `3 == 3` true. So
these rows are engine-INDEPENDENT and carry no `requires` marker — they run,
and mean the same thing, with or without the engines installed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from helpers.engine_hiding import hidden_engine_env  # noqa: E402
from pdf_toolkit.ops.compose import compose_document, parse_page_size  # noqa: E402
from pdf_toolkit.safety.policy import SafetyPolicy  # noqa: E402
from registry import run_cli  # noqa: E402

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SCANNED_RASTER: Final[Path] = REPO_ROOT / "testdata" / "scanned-page.png"

#: Exit 3 — `ENGINE_MISSING` (PLAN.md §5.6).
ENGINE_MISSING: Final[int] = 3


def _policy() -> SafetyPolicy:
    return SafetyPolicy(
        dry_run=False,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )


def _convert_source(tmp_path: Path) -> list[str]:
    """`convert`'s operand is never a PDF; a plain `.txt` is what
    `tests/registry.py::_convert_invocation` already uses for this verb."""
    source = tmp_path / "or7-convert.txt"
    source.write_text("The quick brown fox jumps over the lazy pdftoolkit.\n")
    return [str(source)]


def _ocr_source(tmp_path: Path) -> list[str]:
    """An IMAGE-ONLY page, and deliberately NOT `--skip-text-pages`.

    This is the arm's whole point: `ops/ocr.py` demands its engine lazily, so a
    fully skip-eligible selection reaches the dry-run return having needed no
    engine at all and would assert nothing. Composing `scanned-page.png` gives
    a page with `has_text=False`, so `_page_needs_engine` is true and the
    engine demand is genuinely exercised.
    """
    source = tmp_path / "or7-ocr.pdf"
    result = compose_document(
        [SCANNED_RASTER],
        output=source,
        page=parse_page_size("from-image"),
        fit="contain",
        margin_pt=0.0,
        dpi=None,
        policy=_policy(),
    )
    assert result.exit_code == 0, result
    return [str(source)]


_ARMS: Final[tuple[tuple[str, str, object], ...]] = (
    ("convert", "soffice", _convert_source),
    ("ocr", "tesseract", _ocr_source),
)


def _payload(completed) -> dict:
    """The structured refusal, from wherever the CLI put it."""
    for stream in (completed.stdout, completed.stderr):
        stream = stream.strip()
        if not stream:
            continue
        try:
            return json.loads(stream)
        except json.JSONDecodeError:
            continue
    raise AssertionError(
        f"no JSON payload: stdout={completed.stdout!r} stderr={completed.stderr!r}"
    )


@pytest.mark.parametrize(
    ("verb", "binary", "build_source"),
    _ARMS,
    ids=[f"{verb}-{binary}-absent" for verb, binary, _ in _ARMS],
)
def test_or7_absent_engine_dry_run_mirrors_the_real_exit_code(
    verb: str, binary: str, build_source, tmp_path: Path
) -> None:
    """D12.2 row 1 — `dry == real == 3`, measured AS A PAIR (AC26)."""
    args = build_source(tmp_path)
    env = hidden_engine_env(binary, tmp_path=tmp_path)
    target = tmp_path / f"or7-{verb}-out.pdf"

    dry = run_cli(verb, *args, "-O", str(target), "--dry-run", env=env)
    real = run_cli(verb, *args, "-O", str(target), env=env)

    assert dry.returncode == real.returncode, (
        f"{verb}: OR-7 violated -- dry={dry.returncode} real={real.returncode}. "
        f"`{verb} --dry-run && {verb}` would green-light a run that then fails. "
        f"dry: {dry.stdout}{dry.stderr} / real: {real.stdout}{real.stderr}"
    )
    assert dry.returncode == ENGINE_MISSING, (
        f"{verb}: an absent {binary} is knowable at plan time (D12.1) and must "
        f"predict exit {ENGINE_MISSING}, got {dry.returncode}: {dry.stdout}{dry.stderr}"
    )

    # The preview carries the SAME diagnosis the real run gives -- AC26's
    # "plus the same install hint" -- so the prediction is actionable, not a
    # bare non-zero code.
    dry_error = _payload(dry)["error"]
    real_error = _payload(real)["error"]
    assert dry_error == real_error, f"{verb}: dry {dry_error} != real {real_error}"
    assert dry_error["kind"] == "engine_missing"
    assert "doctor" in dry_error["message"]

    # --dry-run stays pure, and the refused real run writes nothing either.
    assert not target.exists(), f"{verb}: {target.name} was created by a refused run"


# --------------------------------------------------------------------------- #
# PDF-20 — AC20(b)'s OTHER half: the engine-PRESENT pair.
#
# WHY THIS ROW EXISTS BESIDE THE ABSENT ONE. The absent arm above proves
# `3 == 3`. On its own that is not enough to say a preview still WORKS: a matrix
# that agrees everywhere is equally consistent with a preview that has gone
# silent, and D7.1 names that reading in terms. The discriminating evidence is a
# pair where the engine gate STEPS ASIDE and a lower tier answers -- here, the
# same verb predicting and exiting **0** with soffice resolvable. Two pairs, two
# different answers, both agreeing: that is precedence, not agreement.
#
# WHY PDF-20 ADDS IT. PDF-20 changes the ENVIRONMENT the office probe spawns
# under (`adapters/subprocess_util.probe_env()`), and OR-7 forbids that from
# moving a predicted exit code. Asserting `0 == 0` here is how "no predicted
# exit code changed" is measured rather than assumed.
# --------------------------------------------------------------------------- #


@pytest.mark.requires("soffice")
def test_or7_present_engine_dry_run_still_predicts_success(tmp_path: Path) -> None:
    """`dry == real == 0` with the engine present, measured AS A PAIR."""
    args = _convert_source(tmp_path)
    dry_target = tmp_path / "or7-present-dry.pdf"
    real_target = tmp_path / "or7-present-real.pdf"

    dry = run_cli("convert", *args, "-O", str(dry_target), "--dry-run")
    real = run_cli("convert", *args, "-O", str(real_target))

    assert dry.returncode == real.returncode, (
        f"OR-7 violated with the engine PRESENT -- dry={dry.returncode} real={real.returncode}. "
        f"dry: {dry.stdout}{dry.stderr} / real: {real.stdout}{real.stderr}"
    )
    assert dry.returncode == 0, (
        f"a resolvable engine must predict success, got {dry.returncode}: {dry.stdout}{dry.stderr}"
    )
    # The pair is only discriminating if the two arms genuinely DIFFER in what
    # they do: the preview writes nothing and the real run produces the file.
    assert not dry_target.exists(), "the preview created its destination"
    assert real_target.is_file() and real_target.stat().st_size > 0, "the real run produced nothing"
