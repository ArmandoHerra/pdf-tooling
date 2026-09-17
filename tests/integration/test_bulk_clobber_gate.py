"""PDF-84 (`B-345`) — a bulk `--force` run over an OCCUPIED `--out-dir` refuses.

The defect this file measures, driven at `af1dc4f` on every one of the ten
`--out-dir` batch verbs before a line was changed:

    pdftooling delete a2.pdf b2.pdf --out-dir OUT --pages 1 --force -o json
    -> exit 0, `"ok": true` per item, and BOTH targets' mtimes advanced,

on a non-terminal, with no `-y`. `safety/confirm.py::require_confirmation`
computes ``destructive = in_place or bool(clobbered)`` and NINE of the ten never
put anything on the second limb, so the gate's clobber route was unwired and a
bulk destructive run overwrote its targets unconfirmed. `convert` was the one
verb that refused.

**`--force` is a TRIGGER for `-y`, not a substitute** — this file asserts a
contract the product already carried and does not create one. `PLAN.md` §5.3
names *"`--force` over an existing target"* as a destructive condition;
`README.md`'s safety section requires `-y` **additionally**;
`cli/exit_codes.py:43-45` enumerates *target exists without `--force`*,
*planned outputs collide* and *a bulk destructive run on a non-TTY without `-y`*
as three separate members of code 5; and `merge`, `compose` and `convert` have
always implemented the answer.

WHY `returncode == 5` IS NOT A FINGERPRINT, AND WHAT IS
-------------------------------------------------------
FOUR distinct refusals on this product exit **5** carrying ``kind: "refused"``,
and two of them also carry ``path: null``:

===========================  ============  =========================================
refusal                      ``path``      message (first line)
===========================  ============  =========================================
this gate, non-TTY           ``null``      ``refusing a destructive run on N inputs
                                           without confirmation (stdin is not a
                                           terminal)``
this gate, TTY, declined     ``null``      ``declined at the confirmation prompt;
                                           nothing was written``
no-clobber                   the target    ``<target> exists; pass --force to
                                           overwrite it``
zero-page (`delete`)         the source    ``... selects every page; delete refuses
                                           to produce a zero-page document``
===========================  ============  =========================================

So neither the code, nor ``kind``, nor ``path`` discriminates: **only the
message does**, and every refusal assertion in this file pins
:data:`SIGNATURE` rather than an exit code. This is not a hypothetical — it is
how `PDF-75`'s own C13 arm stayed green on both members after the non-TTY raise
was deleted: the run fell through to the TTY branch, read EOF, and still exited
5. A one-page `delete --pages 1` fixture would reproduce the same confusion from
the other direction, which is why the source below has **two** pages.

THE POPULATION IS DERIVED, AND NARROWER THAN `BATCH_VERBS` ON PURPOSE
---------------------------------------------------------------------
`registry.out_dir_batch_verbs()` minus `registry.engine_blind_verbs()`, both
walked live — the same two-factor narrowing, for the same reason, as
`tests/test_batch_continuation.py`'s ``INERT_GATE_VERBS``. The excluded pair is
asserted to BE the engine-blind intersection rather than listed, so the
exclusion cannot quietly become a skip list.

The two excluded verbs are not dropped: their occupied-`--out-dir` refusal is
`X-772`'s required criterion and is asserted in
`tests/integration/test_or7_bulk_destructive.py`, in one arm, with the engines
hidden and the `-y` flip as its discriminator (`X-781`/`X-782`). Naming either
of them here would put two more ungated engine-blind cells into `PDF-82`'s
census, whose ceilings stand at zero headroom in every module — and buying
coverage by raising a ceiling is the trade that instrument exists to prevent.

THE TWO NEGATIVES ARE AS LOAD-BEARING AS THE POSITIVE
------------------------------------------------------
``confirm.py``'s own docstring: *"a gate that fires when it should not is a gate
people route around with `-y` in a shell profile, and then it protects
nobody."* A single-input run producing many targets must still exit 0 (``bulk``
is more than one **INPUT**, `PLAN.md` §5.3 — `tables` makes two of those numbers
differ by four), and so must a create-only run however large. Substituting a
target count for the input count reddens the first while leaving the headline
arm green, which is what stops this file deciding `B-022`'s deferred 1->N
question by accident.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import (  # noqa: E402
    console_script,
    discover_verbs,
    engine_blind_verbs,
    out_dir_batch_verbs,
    run_cli,
)

#: `PLAN.md` §5.6.
OK: Final[int] = 0
REFUSED: Final[int] = 5

#: THE FINGERPRINT. Both fragments, together, and never the exit code alone —
#: see this module's own docstring for the four refusals that share code 5.
SIGNATURE: Final[tuple[str, str]] = (
    "refusing a destructive run on",
    "(stdin is not a terminal)",
)

#: Resolved ONCE at import: `engine_blind_verbs()` walks the import graph under
#: `src/` and is measured at ~2 s per call.
_ENGINE_BLIND: Final[frozenset[str]] = frozenset(engine_blind_verbs())

#: The population. Derived on both sides; see the module docstring for why the
#: engine-blind pair is excluded and where it IS covered.
CLOBBER_VERBS: Final[tuple[str, ...]] = tuple(
    verb for verb in out_dir_batch_verbs() if verb not in _ENGINE_BLIND
)

#: Per-verb argv between the operands and `--out-dir`: only what each verb
#: REQUIRES to reach its own write path, and nothing that tunes behaviour. The
#: same shape `tests/test_batch_continuation.py::_EXTRA_ARGV` carries, restricted
#: to this file's own population so no engine-blind verb is spelled here.
_EXTRA_ARGV: Final[dict[str, list[str]]] = {
    "compress": [],
    "delete": ["--pages", "1"],
    "extract": ["--pages", "1"],
    "rasterize": ["--pages", "1"],
    "reorder": ["--pages", "1"],
    "rotate": ["--pages", "1", "--angle", "90"],
    "tables": [],
    "text": [],
}

#: The verbs above that also consume `--in-place`, read off the LIVE command
#: tree rather than listed: AC11's limb is "every verb that consumed that route",
#: which is a fact about the product and not about this file.
IN_PLACE_VERBS: Final[tuple[str, ...]] = tuple(
    verb.name
    for verb in discover_verbs()
    if verb.name in CLOBBER_VERBS and "--in-place" in verb.consumes
)


# --------------------------------------------------------------------------- #
# Fixtures. TWO pages, built from the corpus's ruled-grid `tabular` fixture
# through the product's own `merge`, and the reasons are both measured:
#
#   * `tables` needs RULED LINES or it detects nothing, plans no targets, seeds
#     an empty `--out-dir` and every arm below goes vacuously green. The PM's
#     own sweep read 7 of 10 rather than 9 for exactly this reason.
#   * ONE page would make `delete --pages 1` a whole-document selection, which
#     is the ZERO-PAGE refusal -- exit 5, `kind: "refused"` -- masquerading as
#     this gate. That confusion is this module's subject; it is not welcome in
#     its fixtures.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def two_page_source(corpus: Any, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A two-page, ruled, text-bearing PDF, built once per session."""
    root = tmp_path_factory.mktemp("pdf84-source")
    made = root / "source.pdf"
    tabular = corpus.path("tabular")
    result = run_cli("merge", str(tabular), str(tabular), "-O", str(made), "-o", "json")
    assert result.returncode == OK, f"fixture build failed: {result.stdout}{result.stderr}"
    return made


def _operands(root: Path, source: Path, count: int = 2) -> list[str]:
    """*count* independent copies of *source*, so a bulk run is genuinely bulk."""
    made: list[str] = []
    for index in range(count):
        destination = root / f"pdf84-{index}.pdf"
        shutil.copy(source, destination)
        made.append(str(destination))
    return made


def _argv(verb: str, operands: list[str], out_dir: Path, *, tail: list[str]) -> list[str]:
    return [verb, *operands, "--out-dir", str(out_dir), *_EXTRA_ARGV[verb], *tail, "-o", "json"]


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """``{relative path: (st_mtime_ns, st_size)}`` — read with `os.walk` and
    `os.stat` alone, never from the tool's own stdout. A payload that agrees
    with itself is exactly what shipped."""
    found: dict[str, tuple[int, int]] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            stat = path.stat()
            found[str(path.relative_to(root))] = (stat.st_mtime_ns, stat.st_size)
    return found


def _seed(verb: str, operands: list[str], out_dir: Path) -> dict[str, tuple[int, int]]:
    """Run *verb* once to OCCUPY *out_dir*, and prove it actually did.

    The non-vacuity guard for every arm below: a verb whose fixture makes it
    plan zero targets would seed nothing, leave nothing to clobber, and then
    agree with every assertion in this file while asserting nothing at all.
    """
    result = run_cli(*_argv(verb, operands, out_dir, tail=[]))
    assert result.returncode == OK, f"{verb}: seeding failed: {result.stdout}{result.stderr}"
    occupied = _snapshot(out_dir)
    assert len(occupied) >= len(operands), (
        f"{verb}: seeding produced {len(occupied)} file(s) for {len(operands)} input(s), so "
        f"there is nothing for --force to clobber and every arm here would pass vacuously"
    )
    return occupied


def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        return dict(json.loads(result.stdout))
    except json.JSONDecodeError as error:  # a traceback, not a payload
        raise AssertionError(
            f"stdout was not JSON ({error}); "
            f"stdout={result.stdout[:400]!r} stderr={result.stderr[-800:]!r}"
        ) from None


def _assert_refused_by_signature(
    verb: str, result: subprocess.CompletedProcess[str], *, what: str
) -> None:
    """The ONLY sanctioned refusal assertion in this file.

    Asserting ``returncode == 5`` satisfies four different refusals and would be
    satisfied by the zero-page one this module's fixtures are shaped to avoid.
    """
    payload = _payload(result)
    error = payload.get("error")
    assert isinstance(error, dict), f"{verb} ({what}): no error envelope: {payload}"
    message = str(error.get("message", ""))
    missing = [fragment for fragment in SIGNATURE if fragment not in message]
    assert result.returncode == REFUSED and error.get("kind") == "refused" and not missing, (
        f"{verb} ({what}): expected the BULK-DESTRUCTIVE refusal -- exit {REFUSED}, "
        f"kind 'refused', and a message carrying {list(SIGNATURE)}. Got exit "
        f"{result.returncode}, kind {error.get('kind')!r}, missing {missing}. "
        f"Exit {REFUSED} alone is shared by four refusals on this product and two of "
        f"them also report path=null, so the code is not a fingerprint: {message!r}"
    )


# --------------------------------------------------------------------------- #
# AC1 (behavioural half) -- the population, derived and non-empty.
# --------------------------------------------------------------------------- #


def test_the_population_is_derived_and_non_empty() -> None:
    """A parametrize set that derived empty would collect nothing and report
    green having asserted nothing -- this suite's own named failure mode."""
    assert CLOBBER_VERBS, "the clobber-gate population derived empty"
    assert set(_EXTRA_ARGV) == set(CLOBBER_VERBS), (
        f"the argv map and the derived population have drifted: map={sorted(_EXTRA_ARGV)} "
        f"population={sorted(CLOBBER_VERBS)}. A verb added to `out_dir_batch_verbs()` gets "
        f"an argv tail here, or this file stops covering it"
    )
    excluded = sorted(set(out_dir_batch_verbs()) - set(CLOBBER_VERBS))
    assert excluded == sorted(_ENGINE_BLIND & set(out_dir_batch_verbs())), (
        f"this file excludes {excluded}, which is not the engine-blind intersection -- the "
        f"exclusion has stopped being derived and become a list"
    )
    assert IN_PLACE_VERBS, "no verb in the population consumes --in-place; AC11's arm is vacuous"


# --------------------------------------------------------------------------- #
# AC2 / AC3 -- the headline: it refuses, by signature, and writes nothing.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", CLOBBER_VERBS)
def test_a_bulk_force_run_over_an_occupied_out_dir_refuses(
    verb: str, two_page_source: Path, tmp_path: Path
) -> None:
    """Bulk, `--force`, occupied `--out-dir`, non-TTY, no `-y` -> the gate.

    RED at `af1dc4f` on every cell: exit 0, `"ok": true`, targets overwritten.
    """
    operands = _operands(tmp_path, two_page_source)
    out_dir = tmp_path / "out"
    _seed(verb, operands, out_dir)

    result = run_cli(*_argv(verb, operands, out_dir, tail=["--force"]))
    _assert_refused_by_signature(verb, result, what="real run")


@pytest.mark.parametrize("verb", CLOBBER_VERBS)
def test_a_refused_run_writes_nothing(verb: str, two_page_source: Path, tmp_path: Path) -> None:
    """Per-target ``st_mtime_ns`` AND size, identical across the refused run.

    Size alone would pass a rewrite that produced the same byte count, and
    mtime alone would pass a truncation on a filesystem with a coarse clock.
    RED at `af1dc4f`: every target's mtime advanced (`delete` measured
    1789636326.776 -> 1789636328.275).
    """
    operands = _operands(tmp_path, two_page_source)
    out_dir = tmp_path / "out"
    occupied = _seed(verb, operands, out_dir)

    result = run_cli(*_argv(verb, operands, out_dir, tail=["--force"]))
    _assert_refused_by_signature(verb, result, what="real run")
    assert _snapshot(out_dir) == occupied, (
        f"{verb}: a REFUSED run changed the occupied --out-dir. The gate refuses before "
        f"the planner returns and long before the write chokepoint; anything touched here "
        f"means the refusal happened after bytes moved"
    )


# --------------------------------------------------------------------------- #
# AC4 -- OR-7: the dry run mirrors, on 5.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", CLOBBER_VERBS)
def test_the_dry_run_mirrors_the_refusal(verb: str, two_page_source: Path, tmp_path: Path) -> None:
    """`dry == real == 5`, with the same signature, and the preview writes
    nothing either.

    RED at `af1dc4f`: the dry run predicted **0** with ``would_exit: [0, 0]``
    while the real run exited 0 too -- OR-7's mirror holding on the wrong
    answer, which is a second oracle per verb rather than a second symptom.
    """
    operands = _operands(tmp_path, two_page_source)
    out_dir = tmp_path / "out"
    occupied = _seed(verb, operands, out_dir)

    dry = run_cli(*_argv(verb, operands, out_dir, tail=["--force", "--dry-run"]))
    real = run_cli(*_argv(verb, operands, out_dir, tail=["--force"]))

    assert dry.returncode == real.returncode, (
        f"{verb}: OR-7 violated -- dry={dry.returncode} real={real.returncode}. "
        f"`{verb} --dry-run && {verb}` would green-light a run that then refuses"
    )
    _assert_refused_by_signature(verb, dry, what="dry run")
    assert _snapshot(out_dir) == occupied, f"{verb}: the PREVIEW touched the --out-dir"


# --------------------------------------------------------------------------- #
# AC5 -- and `-y` lifts it. The control that makes every arm above mean
# "this gate" rather than "some refusal".
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", CLOBBER_VERBS)
def test_y_lifts_the_refusal(verb: str, two_page_source: Path, tmp_path: Path) -> None:
    """Same argv plus `-y` -> exit 0, and the targets are overwritten.

    The refusal lifts on exactly the flag the contract says lifts it, so what
    the arms above measure is the confirmation gate and not an unrelated tier.
    A gate that ignored ``assume_yes`` would leave this cell red while every
    refusal arm stayed green.
    """
    operands = _operands(tmp_path, two_page_source)
    out_dir = tmp_path / "out"
    occupied = _seed(verb, operands, out_dir)

    result = run_cli(*_argv(verb, operands, out_dir, tail=["--force", "-y"]))
    assert result.returncode == OK, f"{verb}: -y did not lift the gate: {result.stdout}"
    after = _snapshot(out_dir)
    advanced = [name for name, facts in occupied.items() if after.get(name) != facts]
    assert advanced, (
        f"{verb}: with -y the run is confirmed and must actually overwrite its targets; "
        f"nothing in {sorted(occupied)} changed"
    )


# --------------------------------------------------------------------------- #
# AC9 / AC10 -- THE TWO NEGATIVES. `bulk` is more than one INPUT, and a
# create-only run never refuses however large.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", CLOBBER_VERBS)
def test_a_single_input_run_still_does_not_refuse(
    verb: str, two_page_source: Path, tmp_path: Path
) -> None:
    """ONE input, many targets, occupied `--out-dir`, `--force` -> exit 0.

    THE most important negative in this spec. ``bulk`` is ``input_count > 1``
    (`PLAN.md` §5.3), and a fix that reached for ``len(targets) > 1`` at the
    planner -- where inputs are not in scope -- fires here while every arm
    above stays green, silently deciding `B-022` == `B-045`'s deferred 1->N
    question, which is explicitly not this file's to answer.

    RED control: substitute the target count for the input count in the gate's
    caller and this cell reds on `tables` (one input, two targets) while
    `test_a_bulk_force_run_over_an_occupied_out_dir_refuses` stays green.
    """
    operands = _operands(tmp_path, two_page_source, count=1)
    out_dir = tmp_path / "out"
    occupied = _seed(verb, operands, out_dir)

    result = run_cli(*_argv(verb, operands, out_dir, tail=["--force"]))
    assert result.returncode == OK, (
        f"{verb}: a SINGLE-input run is not bulk and must not refuse, however many targets "
        f"it produces ({len(occupied)} here): {result.stdout}{result.stderr}"
    )
    after = _snapshot(out_dir)
    assert [name for name, facts in occupied.items() if after.get(name) != facts], (
        f"{verb}: the single-input run exited 0 but overwrote nothing, so this cell is not "
        f"observing the clobbering path it claims to"
    )


@pytest.mark.parametrize("verb", CLOBBER_VERBS)
def test_a_create_only_run_still_does_not_refuse(
    verb: str, two_page_source: Path, tmp_path: Path
) -> None:
    """Bulk `--force` over an EMPTY `--out-dir` -> exit 0.

    ``confirm.py``'s own stated negative: *"neither does a create-only run,
    however large"*. Feeding the gate the PLANNED set instead of the EXISTING
    set reds here while every refusal arm stays green.
    """
    operands = _operands(tmp_path, two_page_source, count=3)
    out_dir = tmp_path / "fresh"

    result = run_cli(*_argv(verb, operands, out_dir, tail=["--force"]))
    assert result.returncode == OK, (
        f"{verb}: a bulk run into a FRESH --out-dir clobbers nothing, so it is not "
        f"destructive and the gate must not fire: {result.stdout}{result.stderr}"
    )
    assert _snapshot(out_dir), f"{verb}: the create-only run wrote nothing, so it proves nothing"


# --------------------------------------------------------------------------- #
# AC11 -- the `--in-place` limb is UNTOUCHED. It is the route that already
# worked, and it stays L1's: the planner deliberately does not collect
# in-place targets into `clobbered` (`plan_output_set`'s own docstring), so a
# merge of the two limbs -- in either direction -- reds here or above.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", IN_PLACE_VERBS)
def test_the_in_place_limb_still_refuses(verb: str, two_page_source: Path, tmp_path: Path) -> None:
    """Bulk `--in-place`, non-TTY, no `-y` -> the same gate, same signature.

    Measured green BEFORE the fix (`af1dc4f`) on every verb that consumes the
    flag, which is what makes this a non-regression arm rather than a new claim.
    """
    operands = _operands(tmp_path, two_page_source)
    before = {path: Path(path).stat().st_mtime_ns for path in operands}

    result = run_cli(verb, *operands, "--in-place", *_EXTRA_ARGV[verb], "-o", "json")
    _assert_refused_by_signature(verb, result, what="--in-place")
    for path, mtime in before.items():
        assert Path(path).stat().st_mtime_ns == mtime, f"{verb}: a refused run mutated {path}"


@pytest.mark.parametrize("verb", IN_PLACE_VERBS)
def test_the_in_place_limb_does_not_fire_twice(
    verb: str, two_page_source: Path, tmp_path: Path
) -> None:
    """The gate asks ONCE, and it must not have reached for stdin at all.

    The hazard a planner-tier gate introduces that an L1 one did not: under
    `--in-place` every target exists, so a planner that collected them into
    ``clobbered`` would refuse a SECOND time after L1 had already refused --
    harmless on a non-terminal, and on a terminal a second prompt after the
    operator had already answered the first. stdin is a pipe the parent holds
    open and never writes, under a hard deadline, so a second gate that fell
    through to the interactive branch hangs and this arm fails on the timeout
    instead of passing on a coincidence.
    """
    operands = _operands(tmp_path, two_page_source)
    read_end, write_end = os.pipe()
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv from console_script()
            [*console_script(), verb, *operands, "--in-place", *_EXTRA_ARGV[verb], "-o", "json"],
            stdin=read_end,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    finally:
        os.close(read_end)
        os.close(write_end)
    assert result.returncode == REFUSED, f"{verb}: {result.stdout}{result.stderr}"
    assert result.stdout.count('"kind": "refused"') == 1, (
        f"{verb}: the gate reported more than once: {result.stdout}"
    )
