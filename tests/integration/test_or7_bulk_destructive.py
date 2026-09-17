"""OR-7 / §D12.2 — the bulk-destructive confirmation gate PREDICTS, on BOTH verbs.

The contract, from ruling OR-7 (`decision.md` §0.5) and PDF-15 §D12.2's own
table:

> `--dry-run` MIRRORS the exit code the real run would produce (`dry == real`).
> | Bulk-destructive, non-TTY, no `-y` | **5** | **5** | yes — `require_confirmation` |

**The defect (B-093, ledger `9ca0c128c8`).** All fifteen call sites spelled the
gate as `if not config.dry_run and <destructive>: require_confirmation(...)`, so
a dry run skipped it outright: `ocr a.pdf b.pdf --in-place --dry-run </dev/null`
exited **0** while the real run exited **5**, and `cmd --dry-run && cmd` green-lit
a run that then refused. Measured at `971d0e5` on BOTH of this spec's verbs — the
brief named `ocr`; `convert`'s `--force`-over-occupied-targets shape was the same
split and is asserted here too.

**Why this module is cross-verb**, exactly like its sibling
`test_or7_engine_absent.py`: `ocr` and `convert` reach the gate through the two
DIFFERENT halves of "destructive" that `safety/confirm.py` defines — `in_place`
for `ocr`, a non-empty `clobbered` for `convert` (which declares no `--in-place`
at all). A fix that only threaded one of them through would leave the other
split, and one parametrized pair is what stops the two drifting apart again.

**Why `convert` cannot simply join C13's population** (`tests/registry.py`'s
`Invocation.destructive_build`, asserted by `test_c13_*` over `DESTRUCTIVE`):
C13's contract is that a *confirmed* run mutates every operand, which is true of
an `--in-place` verb and false of `convert`, whose operands are `.odt`/`.txt`
inputs it never touches. C13 covers the generic `--in-place` population — every
future destructive verb joins it automatically — and this module covers the
`clobbered=` shape C13 structurally cannot express.

**These arms need no engine and carry no `requires` marker.** The gate refuses
above `ops/`, so neither `tesseract` nor `soffice` is ever reached on the
refusal path; the fixtures are a corpus copy and a `.txt`. They run, and mean
the same thing, in both CI configurations. The two arms that hide an engine do
so to probe PRECEDENCE, and hiding an already-absent binary is a no-op that
leaves their assertions true either way.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from fs_snapshot import assert_unchanged, redirected_environment, snapshot  # noqa: E402
from helpers.engine_hiding import hidden_engine_env  # noqa: E402
from registry import console_script, run_cli  # noqa: E402

#: `PLAN.md` §5.6.
REFUSED: Final[int] = 5
ENGINE_MISSING: Final[int] = 3


def _ocr_bulk_in_place(corpus, tmp_path: Path) -> tuple[list[str], list[Path]]:
    """`ocr --in-place` over TWO copies -- bulk AND destructive.

    Copies, never `corpus.path(...)` itself: an `--in-place` row naming the
    shared session-scoped fixture would corrupt every later test that reuses it
    (`tests/registry.py::_copy_corpus_fixture`'s own hazard note).

    `--skip-text-pages` over the text-only `single_page` fixture keeps the arm
    engine-independent on the CONFIRMED path too, the same trick
    `_ocr_destructive_invocation` uses.
    """
    operands = []
    for name in ("or7-ocr-a.pdf", "or7-ocr-b.pdf"):
        destination = tmp_path / name
        shutil.copy(corpus.path("single_page"), destination)
        operands.append(destination)
    args = [str(operands[0]), str(operands[1]), "--skip-text-pages", "--in-place"]
    return args, operands


def _convert_bulk_clobbering(corpus, tmp_path: Path) -> tuple[list[str], list[Path]]:
    """`convert --out-dir <occupied> --force` over TWO inputs.

    `convert` declares no `--in-place` (converting a document "in place" into a
    PDF is meaningless, `cmd_office.py`), so its ONLY destructive shape is a
    bulk `--force` run over targets that already exist -- the `clobbered=` half
    of the gate. The guarded operands here are the TARGETS, not the inputs.
    """
    sources = []
    for name in ("or7-convert-a.txt", "or7-convert-b.txt"):
        source = tmp_path / name
        source.write_text("The quick brown fox jumps over the lazy pdftooling.\n")
        sources.append(source)
    out_dir = tmp_path / "or7-convert-out"
    out_dir.mkdir()
    targets = []
    for source in sources:
        target = out_dir / f"{source.stem}.pdf"
        target.write_bytes(b"%PDF-1.4\n%%EOF\n")
        targets.append(target)
    args = [str(sources[0]), str(sources[1]), "--out-dir", str(out_dir), "--force"]
    return args, targets


_ARMS: Final = (
    ("ocr", _ocr_bulk_in_place),
    ("convert", _convert_bulk_clobbering),
)
_IDS: Final = [f"{verb}-bulk-destructive" for verb, _ in _ARMS]


@pytest.mark.parametrize(("verb", "build"), _ARMS, ids=_IDS)
def test_or7_bulk_destructive_dry_run_mirrors_the_real_exit_code(
    verb: str, build, corpus, tmp_path: Path
) -> None:
    """D12.2's bulk-destructive row — `dry == real == 5`, measured AS A PAIR."""
    args, guarded = build(corpus, tmp_path)
    before = {path: path.read_bytes() for path in guarded}

    dry = run_cli(verb, "--dry-run", *args, cwd=tmp_path)
    real = run_cli(verb, *args, cwd=tmp_path)

    assert dry.returncode == real.returncode, (
        f"{verb}: OR-7 violated -- dry={dry.returncode} real={real.returncode}. "
        f"`{verb} --dry-run && {verb}` would green-light a run that then refuses. "
        f"dry: {dry.stdout}{dry.stderr} / real: {real.stdout}{real.stderr}"
    )
    assert dry.returncode == REFUSED, (
        f"{verb}: a bulk-destructive run on a non-TTY without -y is knowable at "
        f"plan time (D12.2) and must predict exit {REFUSED}, got "
        f"{dry.returncode}: {dry.stdout}{dry.stderr}"
    )
    for path in guarded:
        assert path.read_bytes() == before[path], f"{verb}: a refused run changed {path.name}"


@pytest.mark.parametrize(("verb", "build"), _ARMS, ids=_IDS)
def test_or7_bulk_destructive_preview_carries_the_real_diagnosis(
    verb: str, build, corpus, tmp_path: Path
) -> None:
    """The prediction is actionable, not a bare non-zero code.

    `kind` and `code` are asserted IDENTICAL to the real run's -- the same
    top-level error-envelope shape B-096 landed for the engine tier, and the
    same equality `test_or7_engine_absent.py` asserts there. Only the re-run
    hint legitimately differs: it echoes the command actually typed, so the dry
    run's hint carries `--dry-run` and the real run's does not. Pinning that
    difference is deliberate -- a hint that silently dropped the flag would be
    telling the operator to run something they did not ask for.
    """
    args, _ = build(corpus, tmp_path)
    dry = json.loads(run_cli(verb, "-o", "json", "--dry-run", *args, cwd=tmp_path).stdout)
    real = json.loads(run_cli(verb, "-o", "json", *args, cwd=tmp_path).stdout)

    assert dry["error"]["code"] == real["error"]["code"] == REFUSED
    assert dry["error"]["kind"] == real["error"]["kind"] == "refused"
    assert "without confirmation" in dry["error"]["message"]
    assert dry["error"]["message"].rstrip().endswith(" -y")
    assert "--dry-run" in dry["error"]["message"]
    assert "--dry-run" not in real["error"]["message"]


@pytest.mark.parametrize(("verb", "build"), _ARMS, ids=_IDS)
def test_or7_bulk_destructive_dry_run_is_pure(verb: str, build, corpus, tmp_path: Path) -> None:
    """Predicting a refusal is not a licence to touch anything (CLAUDE.md rule 2).

    Snapshotted against a redirected `HOME` and `TMPDIR` — C10's own instrument
    — because "wrote a temp file it forgot to remove" and "created
    `$HOME/.config`" are the two ways this breaks invisibly to a working-tree
    diff.
    """
    args, _ = build(corpus, tmp_path)
    env, roots = redirected_environment(tmp_path)
    before = snapshot(*roots)
    result = run_cli(verb, "--dry-run", *args, env=env, cwd=tmp_path)
    assert result.returncode == REFUSED, f"{result.stdout}{result.stderr}"
    assert_unchanged(before, snapshot(*roots))


@pytest.mark.parametrize(("verb", "build"), _ARMS, ids=_IDS)
def test_or7_bulk_destructive_dry_run_never_reads_stdin(
    verb: str, build, corpus, tmp_path: Path
) -> None:
    """It refuses IMMEDIATELY, and never reaches for an answer.

    stdin is a pipe the parent holds open and never writes, under a hard
    deadline — `tests/unit/test_confirm.py`'s own instrument for the real run,
    reused here for the preview. A dry run that fell through to the interactive
    branch would block forever rather than fail, and "stuck" is the shape this
    gate's non-TTY branch exists to prevent. A `</dev/null` would prove nothing:
    reading it returns EOF and the run would still finish.
    """
    args, _ = build(corpus, tmp_path)
    read_end, write_end = os.pipe()
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv from console_script()
            [*console_script(), verb, "--dry-run", *args],
            stdin=read_end,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=30,
            check=False,
        )
    finally:
        os.close(read_end)
        os.close(write_end)
    assert result.returncode == REFUSED, f"{result.stdout}{result.stderr}"


# --------------------------------------------------------------------------- #
# PRECEDENCE. "Whatever tier the real run refuses at first is the tier the dry
# run must predict" -- derived from the real path, never assumed. The gate sits
# in the CLI layer ABOVE `ops/`, so it outranks the engine tier B-096 fixed; and
# with `-y` it steps aside and that engine tier is what answers. Asserting both
# directions is what makes this a precedence test rather than two exit codes.
# --------------------------------------------------------------------------- #

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SCANNED_RASTER: Final[Path] = REPO_ROOT / "testdata" / "scanned-page.png"


def _ocr_bulk_in_place_needing_the_engine(corpus, tmp_path: Path) -> tuple[list[str], list[Path]]:
    """Two IMAGE-ONLY pages, and deliberately NOT `--skip-text-pages`.

    The builder above is engine-INDEPENDENT on purpose, which makes it useless
    for a precedence arm: `ops/ocr.py` demands its engine lazily, so a fully
    skip-eligible run reaches exit 0 with tesseract hidden and the `-y` control
    below would compare 0 against 0 and prove nothing about the engine tier.
    Composing `testdata/scanned-page.png` gives `has_text=False` pages, so the
    engine demand is genuinely reached — the same reasoning, and the same
    fixture, as `test_or7_engine_absent.py::_ocr_source`.
    """
    from pdf_tooling.ops.compose import compose_document, parse_page_size
    from pdf_tooling.safety.policy import SafetyPolicy

    seed = tmp_path / "or7-scan-seed.pdf"
    result = compose_document(
        [SCANNED_RASTER],
        output=seed,
        page=parse_page_size("from-image"),
        fit="contain",
        margin_pt=0.0,
        dpi=None,
        policy=SafetyPolicy(
            dry_run=False,
            force=False,
            in_place=False,
            backup=True,
            assume_yes=False,
            is_tty=False,
            threads=1,
        ),
    )
    assert result.exit_code == 0, result
    operands = []
    for name in ("or7-scan-a.pdf", "or7-scan-b.pdf"):
        destination = tmp_path / name
        shutil.copy(seed, destination)
        operands.append(destination)
    return [str(operands[0]), str(operands[1]), "--in-place"], operands


_ENGINES: Final = (
    ("ocr", "tesseract", _ocr_bulk_in_place_needing_the_engine),
    ("convert", "soffice", _convert_bulk_clobbering),
)
_ENGINE_IDS: Final = [f"{verb}-{binary}" for verb, binary, _ in _ENGINES]


@pytest.mark.parametrize(("verb", "binary", "build"), _ENGINES, ids=_ENGINE_IDS)
def test_or7_the_gate_outranks_the_engine_tier_in_the_preview_too(
    verb: str, binary: str, build, corpus, tmp_path: Path
) -> None:
    """Engine ABSENT *and* bulk-destructive: both runs refuse at 5, not 3."""
    args, _ = build(corpus, tmp_path)
    env = hidden_engine_env(binary, tmp_path=tmp_path)

    dry = run_cli(verb, "--dry-run", *args, env=env, cwd=tmp_path)
    real = run_cli(verb, *args, env=env, cwd=tmp_path)

    assert dry.returncode == real.returncode == REFUSED, (
        f"{verb}: with {binary} hidden, the confirmation gate still fires FIRST "
        f"in both runs -- dry={dry.returncode} real={real.returncode}: "
        f"{dry.stdout}{dry.stderr} / {real.stdout}{real.stderr}"
    )


@pytest.mark.parametrize(("verb", "binary", "build"), _ENGINES, ids=_ENGINE_IDS)
def test_or7_with_y_the_engine_tier_answers_in_both_runs(
    verb: str, binary: str, build, corpus, tmp_path: Path
) -> None:
    """The other direction, and the control that makes the arm above mean
    something: `-y` retires the gate, and then BOTH runs report the absent
    engine at 3. Without this, "5 == 5" above would be equally consistent with
    a preview that had simply stopped predicting anything."""
    args, _ = build(corpus, tmp_path)
    env = hidden_engine_env(binary, tmp_path=tmp_path)

    dry = run_cli(verb, "--dry-run", "-y", *args, env=env, cwd=tmp_path)
    real = run_cli(verb, "-y", *args, env=env, cwd=tmp_path)

    assert dry.returncode == real.returncode == ENGINE_MISSING, (
        f"{verb}: with -y and {binary} hidden the ENGINE tier owns the answer -- "
        f"dry={dry.returncode} real={real.returncode}: "
        f"{dry.stdout}{dry.stderr} / {real.stdout}{real.stderr}"
    )


# --------------------------------------------------------------------------- #
# PDF-84 (`X-772`'s required criterion, `X-781`'s ratified +1, `X-782`'s pinned
# instrument) -- `convert` AND `ocr` refuse on an OCCUPIED `--out-dir`.
#
# WHY THIS PAIR NEEDS AN ARM AT ALL. `engine_blind_verbs() & BATCH_VERBS` is
# exactly these two, and they are precisely the pair
# `tests/test_batch_continuation.py`'s INERT_GATE_VERBS deliberately excludes.
# An inertness arm over the full population would have asserted that a bulk
# `--force` run over an occupied `--out-dir` runs IDENTICALLY with and without
# `-y` -- which is true of `ocr` before PDF-84, and is the defect. A criterion
# that would have PINNED THE DEFECT AS CORRECT is why `X-772` made this one
# required, and it is discharged here rather than deferred to a backlog row.
#
# WHY ONE NON-PARAMETRIZED FUNCTION AND NOT TWO CELLS. `PDF-82`'s census counts
# ungated engine-blind drives per module against a frozen ceiling standing at
# ZERO headroom in all sixteen, and `population()` appends one member per ARM:
# a single arm naming both verbs costs `+1`, parametrizing over them costs `2`.
# `X-781` authorized `+1` and stated in terms that `2` is NOT authorized. So the
# four runs live in one function.
#
# WHY NO `@pytest.mark.requires(...)`. Refuted on measurement, not preference:
# with the engine hidden the refusal below is byte-identical to the
# engine-present one (PM-measured at 402 bytes, `cmp` clean), so the marker
# would be a FALSE declaration -- and under `engines-hidden` it does not weaken
# the arm, it DELETES it, in the `without-engines` job `release.yml:44` gates
# the tag on. A tag-blocking safety criterion that is vacuous in the tag-gating
# job is not a criterion. Both engines are hidden here for that reason: the arm
# must mean the same thing on a host that has them and on one that does not.
#
# WHY THE `-y` FLIP IS THE NON-VACUITY HALF (`X-782`). The drafted
# discriminator -- the same command over an EMPTY `--out-dir` returning 3 -- is
# a true fact for `convert` and NOT satisfiable for `ocr` via its documented
# engine-free path: `--skip-text-pages` IS that path, so such a run never enters
# the engine tier and returns 0. Holding the occupancy CONSTANT and varying only
# `-y` is the stronger control anyway, and it works for both verbs: without the
# flag the gate answers 5, with it the engine tier answers 3. Before PDF-84
# `convert` read 5 -> 3 and `ocr` read 3 -> 3, the engine tier owning both
# answers because the gate was not there.
# --------------------------------------------------------------------------- #

#: THE FINGERPRINT for the arm below. Exit 5 is shared by four refusals on this
#: product and two of them also report `path: null` (the TTY-declined branch,
#: driven on a real pty), so neither the code nor the path discriminates -- only
#: the message does.
_GATE_SIGNATURE: Final = (
    "refusing a destructive run on",
    "(stdin is not a terminal)",
)


def _ocr_bulk_clobbering(corpus, tmp_path: Path) -> tuple[list[str], list[Path]]:
    """`ocr --out-dir <occupied> --force` over TWO inputs.

    The half of "destructive" `ocr` was blind to. Its `--in-place` sibling above
    covers the other limb and is deliberately left where it is: swapping that
    member to this builder would reach `+0` on the census by DELETING the
    `--in-place` coverage, which is the trade the census exists to prevent.

    The `--out-dir` is occupied by writing the target paths DIRECTLY rather than
    by running the verb once: seeding through `ocr` would need tesseract, and
    this arm has to run -- and mean the same thing -- with tesseract hidden.

    Deliberately NOT `--skip-text-pages`. That flag is the documented
    engine-free path, so a run carrying it never reaches the engine demand and
    the `-y` control below would compare 0 against 0.
    """
    sources = []
    for name in ("or7-ocr-clobber-a.pdf", "or7-ocr-clobber-b.pdf"):
        destination = tmp_path / name
        shutil.copy(corpus.path("single_page"), destination)
        sources.append(destination)
    out_dir = tmp_path / "or7-ocr-clobber-out"
    out_dir.mkdir()
    targets = []
    for source in sources:
        target = out_dir / f"{source.stem}.pdf"
        target.write_bytes(b"%PDF-1.4\n%%EOF\n")
        targets.append(target)
    args = [str(sources[0]), str(sources[1]), "--out-dir", str(out_dir), "--force"]
    return args, targets


def test_pdf84_the_clobber_gate_outranks_the_engine_tier_for_both_engine_blind_verbs(
    corpus, tmp_path: Path
) -> None:
    """`convert` and `ocr`, occupied `--out-dir`, `--force`, engines hidden.

    Four runs, one arm. Per verb, holding the occupancy constant:

    * **without `-y`** -> exit 5 carrying BOTH fragments of the gate's own
      message, and every target byte- and mtime-identical afterwards. The
      message is the assertion because exit 5 is shared by four refusals on this
      product and two of them also report ``path: null``;
    * **with `-y`** -> exit 3, ``kind: "engine_missing"``. This is the half that
      makes the first mean something: it proves the engine's absence is
      genuinely REACHABLE on this exact command, so the refusal above is the
      gate outranking the engine tier and not the engine being irrelevant.

    RED before PDF-84: the `ocr` legs read 3 -> 3, both answers owned by the
    engine tier because the gate never fired. The `convert` legs read 5 -> 3
    then and must still read 5 -> 3 now -- `cli/cmd_office.py:147`'s L1 call
    site is byte-identical in PDF-84's diff, so a regression there is this arm's
    to catch.
    """
    for verb, binary, build in (
        ("ocr", "tesseract", _ocr_bulk_clobbering),
        ("convert", "soffice", _convert_bulk_clobbering),
    ):
        args, targets = build(corpus, tmp_path)
        env = hidden_engine_env(binary, tmp_path=tmp_path)
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in targets}

        refused = run_cli(verb, "-o", "json", *args, env=env, cwd=tmp_path)
        payload = json.loads(refused.stdout)
        message = payload.get("error", {}).get("message", "")
        missing = [fragment for fragment in _GATE_SIGNATURE if fragment not in message]
        assert (
            refused.returncode == REFUSED and payload["error"]["kind"] == "refused" and not missing
        ), (
            f"{verb}: a bulk --force run over an OCCUPIED --out-dir must refuse at "
            f"{REFUSED} with the gate's own message (missing {missing}); got "
            f"{refused.returncode}: {refused.stdout}{refused.stderr}"
        )
        for path, (content, mtime) in before.items():
            assert path.read_bytes() == content, f"{verb}: the refused run rewrote {path.name}"
            assert path.stat().st_mtime_ns == mtime, f"{verb}: the refused run touched {path.name}"

        confirmed = run_cli(verb, "-o", "json", "-y", *args, env=env, cwd=tmp_path)
        engine_payload = json.loads(confirmed.stdout)
        assert confirmed.returncode == ENGINE_MISSING, (
            f"{verb}: with -y the gate steps aside and the ENGINE tier must own the answer "
            f"-- {binary} is hidden, so this is {ENGINE_MISSING}, not "
            f"{confirmed.returncode}. Without this leg the refusal above would be equally "
            f"consistent with the engine never having been relevant: "
            f"{confirmed.stdout}{confirmed.stderr}"
        )
        assert engine_payload["error"]["kind"] == "engine_missing", engine_payload
