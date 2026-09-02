"""The per-verb CLI contract matrix — `PLAN.md` §10.

Every check (`C1`…`C15`) is parameterized over `tests/registry.py`'s
`discover_verbs()`: **no skip list, no filter, no hard-coded verb name**
(AC5). A verb registered on the live Typer tree is covered here the next time
the suite runs, with no action from its author beyond registering an
`Invocation` in `tests/registry.py::INVOCATIONS` (enforced by
`test_every_verb_is_registered`, AC10).

Every test in this module runs the installed console script as a real
subprocess — the only way exit codes, ANSI-on-a-pipe, and non-TTY posture are
observable at all — and therefore carries `@pytest.mark.e2e`
(`pytestmark`, module-wide) per Design §4.

Checks marked **(reg)** in the docstring of each test additionally require
the verb's `INVOCATIONS` row. `C4`, `C9`, `C10` and `C11` currently collect
**zero** parametrized cases at PDF-06 landing's own baseline: `version`/
`doctor`/`info` are the only verbs that exist then, none of them is
`is_mutating` (they write nothing) and no non-root grouping parent exists
yet. That is real, not a defect — later specs gain coverage for each of
these automatically the moment a verb reaches the write chokepoint or a
subcommand group is created. `AC6`'s own non-vacuity guard (`pytest -m e2e
--collect-only -q` is non-zero) is satisfied by `C1`/`C2`/`C3`/`C5`/`C7`/
`C8`/`C12` plus the three root-level tests below, which are never empty.

**C13 (B-079).** Its `DESTRUCTIVE` population was empty from PDF-06 through
PDF-14 — every landed `INVOCATIONS` row was `destructive=False` — which is
*why* the bulk-destructive confirmation gate went unwired on five verbs
(`compress`/`repair`/`linearize`/`encrypt`/`decrypt`) without the suite ever
noticing: `DESTRUCTIVE` empty means C13 collects zero cases and cannot bite
on anything. B-079 wires the gate on all five and seeds `compress` --
the one of the five whose arity makes a bulk `--in-place` run reachable
today -- as C13's first non-empty case (`tests/registry.py`'s
`Invocation.destructive_build`); the `POPULATIONS` roster at the foot of this
module is the anti-lapse guard so this cannot silently regress to zero again.

**PDF-17 -- every derived population is pinned, not two of them.** `DESTRUCTIVE`
and `IN_PLACE_OUTPUT_CONFLICT_VERBS` carried the module's only two
`assert len(...) > 0` statements; the other thirteen tuple-valued module-level
constants -- including `PAGE_ADDRESSING` and `MUTATING`, which `B-032` believed
were the pinned ones -- had no pin at all. They are now rostered in
`POPULATIONS` and pinned by ONE parameterized control, with a second control
(`test_every_population_is_rostered`) that fails when a population exists in
this module but not in the roster, so the roster cannot lag the module the way
seven hand-typed verb tuples lagged the live registry (`e138934a60`).
"""

from __future__ import annotations

import ast
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from fs_snapshot import assert_unchanged, redirected_environment, snapshot
from pdf_toolkit.cli.common import GLOBAL_OPTIONS, OUTPUT_FLAGS
from registry import (
    INVOCATIONS,
    OUTPUT_FLAG_INVOCATIONS,
    REPO_ROOT,
    discover_groups,
    discover_verbs,
    run_cli,
)

pytestmark = pytest.mark.e2e

VERBS = discover_verbs()
GROUPS = discover_groups()
MUTATING = tuple(verb for verb in VERBS if verb.is_mutating)
PAGE_ADDRESSING = tuple(verb for verb in VERBS if verb.is_page_addressing)
TAKES_INPUT_PATHS = tuple(verb for verb in VERBS if verb.takes_input_paths)
REGISTERED = tuple(verb for verb in VERBS if verb.name in INVOCATIONS)
DESTRUCTIVE = tuple(
    verb for verb in VERBS if verb.name in INVOCATIONS and INVOCATIONS[verb.name].destructive
)
#: B-054, C15 — "producing" widened from C11's `--output`-only lens to every
#: destination-naming flag a mutating, registered verb declares consuming
#: (OR-3's own `consumes`, `decision.md` §0.5). ONE shared derivation; C11's
#: own narrower set below is read off it rather than re-derived, so there is
#: one definition of "producing" in this module, not two.
_DESTINATION_FLAGS = ("--output", "--out-dir")
PRODUCING = tuple(
    verb
    for verb in MUTATING
    if verb.name in INVOCATIONS and any(flag in verb.consumes for flag in _DESTINATION_FLAGS)
)
#: AC29 — C11 re-parameterized off the §D12 declaration itself rather than a
#: hard-coded `-O`: a mutating verb only earns a no-clobber-over-`-O` case
#: when it actually *declares* `--output` (E13 — driving `-O` at `split`,
#: which does not consume it, is exit 2, not 5). Read off PRODUCING (a
#: superset by construction) rather than MUTATING directly.
OUTPUT_CONSUMING_MUTATING = tuple(verb for verb in PRODUCING if "--output" in verb.consumes)


def _ids(verbs: tuple) -> list[str]:
    return [verb.name for verb in verbs]


# --------------------------------------------------------------------------- #
# C1 -- every verb's --help exits 0, non-empty stdout, names itself
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", VERBS, ids=_ids(VERBS))
def test_c1_help_exits_0_and_names_itself(verb) -> None:
    result = run_cli(verb.name, "--help")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), f"{verb.name} --help printed nothing"
    assert verb.path[-1] in result.stdout


# --------------------------------------------------------------------------- #
# C2 -- the §4.2 global-flag block matches root's, at every verb
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", VERBS, ids=_ids(VERBS))
def test_c2_global_flag_block_matches_root(verb) -> None:
    root_help = run_cli("--help").stdout
    verb_help = run_cli(verb.name, "--help").stdout
    for option in GLOBAL_OPTIONS:
        assert option in root_help, f"root --help is missing {option}"
        assert option in verb_help, f"`{verb.name} --help` is missing {option}"


# --------------------------------------------------------------------------- #
# C3 -- an unknown flag exits 2, at every verb
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", VERBS, ids=_ids(VERBS))
def test_c3_unknown_flag_exits_2(verb) -> None:
    result = run_cli(verb.name, "--definitely-not-a-flag")
    assert result.returncode == 2


# --------------------------------------------------------------------------- #
# C4 -- a bogus subcommand exits 2, at every grouping parent
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("group_path", GROUPS, ids=[" ".join(p) for p in GROUPS])
def test_c4_bogus_subcommand_on_a_group_exits_2(group_path: tuple[str, ...]) -> None:
    result = run_cli(*group_path, "bogus-subcommand-xyz")
    assert result.returncode == 2


# --------------------------------------------------------------------------- #
# C5 -- a nonexistent input path exits 4, for every takes_input_paths verb
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", TAKES_INPUT_PATHS, ids=_ids(TAKES_INPUT_PATHS))
def test_c5_nonexistent_input_exits_4(verb, tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.pdf"
    result = run_cli(verb.name, str(missing))
    assert result.returncode == 4


# --------------------------------------------------------------------------- #
# C6 -- a malformed page range exits 2, for every is_page_addressing verb
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", PAGE_ADDRESSING, ids=_ids(PAGE_ADDRESSING))
def test_c6_malformed_page_range_exits_2(verb, corpus) -> None:
    source = corpus.path("single_page")
    result = run_cli(verb.name, "--pages", "1--3", str(source))
    assert result.returncode == 2


# --------------------------------------------------------------------------- #
# C7 -- --no-backup alone (no --in-place) exits 2
#
# The global block attaches --no-backup and --in-place to every verb
# uniformly (`pdf_toolkit.cli.common.global_options`), so "verbs with both
# flags" is every verb at PDF-06 landing time -- see `tests/registry.py`'s
# module docstring for why that same universality makes the literal
# `is_mutating` predicate unusable, while this one is unaffected: C7 asserts
# a REFUSAL that the shared `SafetyPolicy.validate()` raises before any verb
# body runs, so it is correctly universal by construction.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", VERBS, ids=_ids(VERBS))
def test_c7_no_backup_alone_exits_2(verb) -> None:
    result = run_cli("--no-backup", verb.name)
    assert result.returncode == 2


# --------------------------------------------------------------------------- #
# C8 -- no ANSI escape through a pipe, at every verb
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", VERBS, ids=_ids(VERBS))
def test_c8_no_ansi_on_a_pipe(verb) -> None:
    result = run_cli(verb.name, "--help")
    assert "\x1b[" not in result.stdout


# --------------------------------------------------------------------------- #
# C9 -- unconditional dry-run purity: a bare --dry-run leaves the tree
# unchanged WHATEVER the exit code, for every is_mutating verb.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", MUTATING, ids=_ids(MUTATING))
def test_c9_unconditional_dry_run_purity(verb, tmp_path: Path) -> None:
    env, roots = redirected_environment(tmp_path)
    before = snapshot(*roots)
    run_cli(verb.name, "--dry-run", env=env, cwd=tmp_path)
    assert_unchanged(before, snapshot(*roots))


# --------------------------------------------------------------------------- #
# C10 -- (reg) the registered invocation + --dry-run is PURE, and PREDICTS the
# exit code the real run would produce.
#
# B-096. The `== 0` this row asserted until now was never a fact about dry
# runs. It was `PLAN.md` §5.6's *"Also: `--dry-run` completed"* clause -- the
# clause operator ruling OR-7 STRUCK when it made `--dry-run` mirror the real
# exit code (`dry == real`) -- encoded here as a UNIVERSAL over a population
# every new mutating verb joins automatically. It survived the ruling only
# because, until `convert`, no registered invocation could legitimately predict
# non-zero on an engine-less host: every verb either needed no engine at all
# or, like `ocr --skip-text-pages`, had an engine-free path. So this row is not
# collateral damage from B-096's fix -- B-096 is the first thing to REVEAL that
# the universal was already wrong, on a second live instance of a struck
# clause.
#
# This row therefore BRANCHES, and never skips. Purity is its actual subject,
# it holds on every host whatever the exit code, and it is asserted
# UNCONDITIONALLY below -- so C10 keeps running on every host and every verb.
# Only the PREDICTED EXIT CODE is derived, and it is derived from the verb's
# own declared precondition (`Invocation.requires_engine`) resolved through the
# `pdf_toolkit.ports.resolve()` chokepoint that `doctor`, `conftest.py`'s
# `requires(engine)` marker and `_skip_unless_engine_available` below all
# already use -- never an independent `shutil.which`, never an env var, never a
# platform check. Today only `convert` can take the non-zero arm, and only on a
# host without soffice; `ocr` declares `requires_engine=None` and stays at 0
# everywhere, as does every other mutating verb.
# --------------------------------------------------------------------------- #

#: Exit 3 -- `ENGINE_MISSING` (`PLAN.md` §5.6).
ENGINE_MISSING = 3


def _expected_dry_run_exit(invocation) -> int:
    """The exit code *invocation*'s ``--dry-run`` must predict ON THIS HOST.

    OR-7 makes ``--dry-run`` mirror the real run, and the real run of a verb
    that declares an engine exits ``ENGINE_MISSING`` when that engine does not
    resolve. The expectation is therefore a function of the declared
    precondition rather than a constant: ``0`` when the verb needs no engine or
    its engine is present, ``3`` when a genuinely declared engine is absent.

    Resolved through the same ``ports.resolve()`` chokepoint as
    :func:`_skip_unless_engine_available` below, so a prediction here and
    ``doctor`` can never disagree about whether an engine is there.
    """
    engine = getattr(invocation, "requires_engine", None)
    if engine is None:
        return 0
    from pdf_toolkit.ports import resolve

    return 0 if resolve(engine).available else ENGINE_MISSING


@pytest.mark.parametrize("verb", MUTATING, ids=_ids(MUTATING))
def test_c10_registered_invocation_dry_run_purity(verb, corpus, tmp_path: Path) -> None:
    invocation = INVOCATIONS[verb.name]
    # Resolved BEFORE the snapshot opens. `resolve()` may spawn a version probe
    # on an engine-PRESENT host (`soffice --version` creates `$HOME/.config`),
    # and it runs in THIS process against the real environment rather than the
    # redirected one under test -- ordering it first keeps that spawn provably
    # outside the purity window this row measures, instead of relying on the
    # roots happening not to overlap.
    expected = _expected_dry_run_exit(invocation)
    args = invocation.build(corpus, tmp_path)
    env, roots = redirected_environment(tmp_path)
    before = snapshot(*roots)
    result = run_cli(verb.name, "--dry-run", *args, env=env, cwd=tmp_path)
    assert result.returncode == expected, (
        f"{verb.name}: --dry-run exited {result.returncode}, expected {expected} "
        f"(OR-7: a dry run mirrors the exit code the real run would produce): "
        f"{result.stdout}{result.stderr}"
    )
    # Purity is unconditional and is this row's real subject: under EITHER arm,
    # whatever the exit code, a --dry-run writes nothing anywhere.
    assert_unchanged(before, snapshot(*roots))


# --------------------------------------------------------------------------- #
# C11 -- (reg) no-clobber: writing over an existing target without --force
# exits 5. Re-parameterized (AC29, E13) over mutating verbs that *declare*
# `--output` in the OR-3 sense (Design §D12) -- reading the declaration
# rather than hard-coding `-O` for every mutating verb, which would drive it
# at `split` (exit 2, since split does not consume `--output`) instead of
# exercising the no-clobber refusal C11 exists to prove.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", OUTPUT_CONSUMING_MUTATING, ids=_ids(OUTPUT_CONSUMING_MUTATING))
def test_c11_no_clobber_exits_5(verb, corpus, tmp_path: Path) -> None:
    invocation = INVOCATIONS[verb.name]
    args = invocation.build(corpus, tmp_path)
    target = tmp_path / "already-exists.pdf"
    target.write_bytes(b"%PDF-1.4\n%%EOF\n")
    result = run_cli(verb.name, *args, "-O", str(target), cwd=tmp_path)
    assert result.returncode == 5


# --------------------------------------------------------------------------- #
# Engine-gated rows -- PDF-15 fix-forward, post-`5bf6e65`.
#
# `Invocation.requires_engine` (`tests/registry.py`) names a genuine
# precondition some verbs have and most do not: `convert`'s whole job IS the
# conversion (no engine-free path the way `ocr --skip-text-pages` has one),
# so its registered rows cannot reach exit 0 without `OfficeConverter`
# (soffice) resolvable. C12 and C14's honoured side are the only two checks
# that actually RUN a registered/`OUTPUT_FLAG_INVOCATIONS` build expecting
# exit 0, so they are the only two that need this gate; every other check in
# this module either never runs `convert`'s row at all or exercises an
# OR-3 refusal that returns BEFORE `require_office()` is ever reached
# (`tests/registry.py`'s own PDF-15 section note).
#
# This SKIPS VISIBLY, by name, exactly like `tests/conftest.py`'s own
# `@pytest.mark.requires(engine)` marker -- resolved through the identical
# `pdf_toolkit.ports.resolve()` chokepoint `doctor` uses, never an
# independent `shutil.which` and never an env var or platform check. When the
# engine IS present (the `engines-present` CI job), this returns immediately
# and the row runs for real -- `scripts/assert_skips.py --expect-zero` on
# that job is the existing guard that a skip here would trip.
# --------------------------------------------------------------------------- #


def _skip_unless_engine_available(invocation) -> None:
    engine = getattr(invocation, "requires_engine", None)
    if engine is None:
        return
    from pdf_toolkit.ports import resolve

    report = resolve(engine)
    if not report.available:
        pytest.skip(f"{engine} engine unavailable; install with: {report.hint}")


# --------------------------------------------------------------------------- #
# C12 -- (reg) stdout on a pipe with no -o parses as JSON carrying
# schema_version.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", REGISTERED, ids=_ids(REGISTERED))
def test_c12_json_on_a_pipe_by_default(verb, corpus, tmp_path: Path) -> None:
    invocation = INVOCATIONS[verb.name]
    _skip_unless_engine_available(invocation)
    args = invocation.build(corpus, tmp_path)
    result = run_cli(verb.name, *args)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "schema_version" in payload


# --------------------------------------------------------------------------- #
# C13 -- (reg) bulk destructive without -y refuses on a non-TTY; -y succeeds;
# a single-input run never refuses.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", DESTRUCTIVE, ids=_ids(DESTRUCTIVE))
def test_c13_bulk_destructive_requires_y_on_a_non_tty(verb, corpus, tmp_path: Path) -> None:
    """B-079's own red/green pair: a refused run mutates NOTHING, a
    confirmed one mutates EVERY operand -- not just the exit codes.

    Operand discovery is generic (`token.startswith("-")` marks a flag,
    everything else that resolves to a real file is an operand), matching
    every other check in this module's own "no hard-coded verb name"
    convention -- `Invocation.destructive_build`'s own contract is that
    leading positional operands come before the first flag, the same shape
    every other registered ``build`` in this file already has.
    """
    invocation = INVOCATIONS[verb.name]
    args = destructive_argv(invocation, verb.name, corpus, tmp_path)
    operands = [Path(tok) for tok in args if not tok.startswith("-")]
    operands = [op for op in operands if op.is_file()]
    assert operands, f"{verb.name}: destructive invocation names no discoverable operand file"
    before = {op: op.read_bytes() for op in operands}

    refused = run_cli(verb.name, *args)
    assert refused.returncode == 5
    for op in operands:
        assert op.read_bytes() == before[op], f"{verb.name}: a refused bulk run mutated {op}"

    confirmed = run_cli(verb.name, "-y", *args)
    assert confirmed.returncode != 5
    for op in operands:
        assert op.read_bytes() != before[op], (
            f"{verb.name}: --in-place was declared but the confirmed run left {op} unchanged"
        )


@pytest.mark.parametrize("verb", DESTRUCTIVE, ids=_ids(DESTRUCTIVE))
def test_c13_dry_run_predicts_the_bulk_destructive_refusal(verb, corpus, tmp_path: Path) -> None:
    """B-093 -- OR-7 over C13's own population: `dry == real == 5`, AS A PAIR.

    PDF-15 §D12.2 lists "bulk-destructive, non-TTY, no `-y`" among the rows
    KNOWABLE at plan time, and it was the last one still splitting: every CLI
    call site guarded `require_confirmation` with `if not config.dry_run and
    ...`, so the preview skipped the gate, exited 0, and green-lit
    `cmd --dry-run && cmd` into a run that then refused.

    Deliberately parameterized over `DESTRUCTIVE` rather than written against
    one verb: this is the same generic-population discipline every other row in
    this module follows, so the sixteenth destructive verb is covered the day it
    registers a `destructive_build`, not the day someone remembers it. The
    matching per-verb pairs for PDF-15's own two verbs (including `convert`,
    whose destructive shape is `--force` over occupied targets and so cannot
    join C13's `--in-place` population) live in
    `tests/integration/test_or7_bulk_destructive.py`.

    Purity is asserted alongside the code, under a redirected `HOME`/`TMPDIR`
    (C10's own instrument): predicting a refusal must not become a licence to
    touch the filesystem, and a gate that read stdin here would hang rather
    than fail.
    """
    invocation = INVOCATIONS[verb.name]
    args = destructive_argv(invocation, verb.name, corpus, tmp_path)
    operands = [Path(tok) for tok in args if not tok.startswith("-")]
    operands = [op for op in operands if op.is_file()]
    assert operands, f"{verb.name}: destructive invocation names no discoverable operand file"

    env, roots = redirected_environment(tmp_path)
    before = snapshot(*roots)
    dry = run_cli(verb.name, "--dry-run", *args, env=env, cwd=tmp_path)
    assert_unchanged(before, snapshot(*roots))

    real = run_cli(verb.name, *args, env=env, cwd=tmp_path)
    assert dry.returncode == real.returncode, (
        f"{verb.name}: OR-7 violated at the confirmation gate -- "
        f"dry={dry.returncode} real={real.returncode}; "
        f"`{verb.name} --dry-run && {verb.name}` would green-light a refused run. "
        f"dry: {dry.stdout}{dry.stderr} / real: {real.stdout}{real.stderr}"
    )
    assert dry.returncode == 5, (
        f"{verb.name}: a bulk-destructive non-TTY run without -y is knowable at "
        f"plan time (D12.2) and must predict exit 5, got {dry.returncode}: "
        f"{dry.stdout}{dry.stderr}"
    )

    dry_payload = json.loads(
        run_cli(verb.name, "-o", "json", "--dry-run", *args, cwd=tmp_path).stdout
    )
    assert dry_payload["error"]["kind"] == "refused", dry_payload
    assert "-y" in dry_payload["error"]["message"]


# --------------------------------------------------------------------------- #
# C14 -- the OR-3 matrix arm (AC25, Design §D12). Every verb in the LIVE
# registry x every OUTPUT_FLAGS entry -> honoured (a file appears) or exit 2.
# No skip list, no filter, no hard-coded verb name -- driven off
# `discover_verbs()` x `OUTPUT_FLAGS`, exactly like every other check in this
# module. A future verb is covered the day it registers, not the day someone
# remembers to extend a list.
#
# PDF-17 -- V2 (satisfiable assertion): THE HONOURED SIDE NOW PROVES THAT THE
# *VERB* WROTE SOMETHING.
#
# `afe6137b`/`afe2e6137b`'s mechanism, and it is not the exit code: the row's
# own builder materialises its input INTO `tmp_path` (`_copy_corpus_fixture`,
# `_fixture_jpeg`, `_fixture_text`, `_password_file`), and the pre-PDF-17
# assertion snapshotted `tmp_path` BEFORE calling the builder. `after - before`
# was therefore satisfied by the BUILDER's file, for any cell whose builder
# writes -- which is precisely the shape the old comment claimed to catch
# ("this is B-035's own shape (exit 0, nothing written)"). The verb ran and its
# exit code was checked; the WRITE assertion was what proved nothing.
#
# Moving the snapshot after the builder is the minimal edit and it is NOT
# enough: a whole-directory diff still passes if the verb writes ANY file
# anywhere under `tmp_path` -- a temp artefact, a partial write -- and still
# cannot tell "the verb honoured `--out-dir`" from "the verb wrote somewhere
# else". The snapshot moves as defence in depth; the real assertion is
# specific, and it is made against a destination THE PRODUCT NAMED:
#
#   1. `_discover_target` reads `items[0].output` from the verb's own
#      `--dry-run -o json` plan (the machinery C15 already has).
#   2. The target is asserted ABSENT before the real run -- if the builder
#      already created it, the cell proves nothing and says so BY FAILING.
#   3. The real run exits 0.
#   4. The target EXISTS. The verb wrote THAT path.
#
# That makes the honoured side a dry/real pair: the plan PREDICTS the
# destination and the real run is checked against the prediction, so a verb
# whose plan names one path and whose write lands on another now fails a check
# that previously could not see it. The path is computed by the verb's own
# `_plan()`; the existence check is made by the test. Neither vouches for
# itself.
#
# THE `--in-place` ARM IS DIFFERENT AND IS NOT FORCED INTO THE SAME SHAPE. For
# an in-place row the planned target IS the input, so "absent before" is false
# by construction. The witness is the `.bak` SIDECAR: `safety/atomic.py:546`
# creates `destination.with_name(destination.name + ".bak")` and ONLY the
# in-place path does so, which makes its appearance an unforgeable signal that
# the verb reached the write chokepoint. The input's BYTES are deliberately not
# asserted to change -- a legitimately idempotent operation (compressing an
# already-compressed file) would fail for a correct reason.
#
# ONE HONOURED CELL CANNOT USE THE SIDECAR AND IT IS ALLOWLISTED RATHER THAN
# WAVED THROUGH: `("encrypt", "--in-place")` passes `--no-backup`, because a
# bare `encrypt --in-place` exits 5 by design (PDF-13's plaintext-`.bak` gate)
# and the row deliberately leaves no plaintext copy behind. With backups off
# there is no sidecar to witness, so that cell falls back to "the operand's
# bytes changed" -- sound there because encryption is not byte-idempotent, and
# UNSOUND in general, which is why the fallback is an allowlist with its own
# staleness pin (`test_the_no_backup_in_place_allowlist_is_not_stale`) rather
# than a branch any future row can take silently.
# --------------------------------------------------------------------------- #

OUTPUT_FLAG_CASES = tuple((verb, flag) for verb in VERBS for flag in OUTPUT_FLAGS)

#: The DECLARED (honoured) half of the matrix — 53 of C14's 104 cells at this
#: commit. Defined here beside `OUTPUT_FLAG_CASES` rather than beside the red
#: proof that consumes it, so `POPULATIONS` below can roster it.
HONOURED_CELLS: Final[tuple[tuple, ...]] = tuple(
    (verb, flag) for verb, flag in OUTPUT_FLAG_CASES if flag in verb.consumes
)


def _output_flag_ids(cases: tuple) -> list[str]:
    return [f"{verb.name}:{flag}" for verb, flag in cases]


def _base_args_for(verb_name: str, corpus) -> list[str]:
    """The minimal positional argv a verb needs to reach the OR-3 check at
    all -- never a mode flag, never the offending flag itself, so a verb's
    OWN "which flag was given" logic is what the test is exercising."""
    if verb_name in ("doctor", "version"):
        return []
    return [str(corpus.path("single_page"))]


def _offending_flag_args(flag: str, tmp_path: Path) -> list[str]:
    if flag == "--output":
        return ["-O", str(tmp_path / "not-declared-output.pdf")]
    if flag == "--out-dir":
        return ["--out-dir", str(tmp_path / "not-declared-out-dir")]
    if flag == "--name":
        return ["--name", "not-declared-{index}.{ext}"]
    if flag == "--in-place":
        return ["--in-place"]
    raise AssertionError(f"unknown OUTPUT_FLAGS entry {flag!r}")  # pragma: no cover


#: The honoured `--in-place` cells whose row suppresses the `.bak` sidecar, and
#: which therefore cannot use it as the write witness. Kept as an ALLOWLIST
#: rather than a `"--no-backup" in args` branch so a second row taking the
#: weaker fallback is a decision someone has to write down.
#: `test_the_no_backup_in_place_allowlist_is_not_stale` fails when an entry
#: stops being a real declared cell or stops passing `--no-backup`.
NO_BACKUP_IN_PLACE_CELLS: Final[frozenset[tuple[str, str]]] = frozenset({("encrypt", "--in-place")})


def _bak_sidecar(operand: Path) -> Path:
    """`safety/atomic.py:546`'s in-place backup path. Only the in-place write
    path creates this, which is what makes it unforgeable as a witness."""
    return operand.with_name(operand.name + ".bak")


def _honoured_witness(
    verb, flag: str, args: list[str], tmp_path: Path
) -> tuple[Path, bytes | None]:
    """The path whose appearance proves *verb* itself wrote, plus the operand's
    pre-run bytes when the witness is a byte change rather than a new file.

    Never a per-verb table: the destination comes from the product's own
    ``--dry-run -o json`` plan for the non-in-place arm, and from
    ``safety/atomic.py``'s one backup-naming rule for the in-place arm.
    """
    if flag != "--in-place":
        return _discover_target(verb, args, tmp_path), None
    operand = Path(args[0])
    if (verb.name, flag) in NO_BACKUP_IN_PLACE_CELLS:
        return operand, operand.read_bytes()
    return _bak_sidecar(operand), None


def assert_the_verb_itself_wrote(
    verb_name: str,
    flag: str,
    witness: Path,
    witness_existed_before: bool,
    operand_bytes_before: bytes | None,
    returncode: int,
    stderr: str,
    new_paths: frozenset[Path],
) -> None:
    """C14's honoured-side assertion, as a PURE function of an already-obtained
    result.

    Factored out so `test_a_planted_exit_0_without_writing_fails_every_honoured_cell`
    can drive it with a synthetic exit-0 result over EVERY honoured cell without
    spawning 53 more subprocesses -- the red proof is what makes this assertion
    an instrument, and a red proof that doubles the gate's wall-clock is a
    different spec's problem (`decision.md` §5 R-1).
    """
    if operand_bytes_before is None:
        assert not witness_existed_before, (
            f"{verb_name} {flag}: the write witness {witness} ALREADY existed before the "
            "run -- the row's own builder created the destination, so this cell could not "
            "tell a verb that wrote from one that did not. Fix the row, do not relax this."
        )
    else:
        # The byte-change arm's precondition is the MIRROR IMAGE: an in-place
        # operand must be there before the run, or "its bytes changed" is a
        # statement about a file the verb created rather than one it rewrote.
        assert witness_existed_before, (
            f"{verb_name} {flag}: the in-place operand {witness} did not exist before the "
            "run, so a byte change afterwards would not prove an in-place rewrite"
        )
    assert returncode == 0, f"{verb_name} declares {flag!r} but the invocation refused: {stderr}"
    if operand_bytes_before is None:
        assert witness.exists(), (
            f"{verb_name} declares {flag!r} and exited 0, but did not write {witness} -- "
            f"the destination its OWN --dry-run plan named. This is B-035's shape (exit 0, "
            "nothing written), and until PDF-17 this cell was satisfied by whatever the "
            "row's builder happened to drop in tmp_path."
        )
        assert witness in new_paths, (
            f"{verb_name} {flag}: {witness} exists but is not NEW since the builder ran -- "
            "defence in depth for the precondition above"
        )
    else:
        assert witness.read_bytes() != operand_bytes_before, (
            f"{verb_name} declares {flag!r} and exited 0, but left {witness} byte-identical. "
            "This cell suppresses the .bak sidecar (NO_BACKUP_IN_PLACE_CELLS), so a byte "
            "change is the only witness available that the verb reached the write chokepoint."
        )


@pytest.mark.parametrize(
    ("verb", "flag"), OUTPUT_FLAG_CASES, ids=_output_flag_ids(OUTPUT_FLAG_CASES)
)
def test_c14_output_flag_matrix(verb, flag: str, corpus, tmp_path: Path) -> None:
    declared = flag in verb.consumes

    if declared:
        key = (verb.name, flag)
        if key not in OUTPUT_FLAG_INVOCATIONS:
            pytest.fail(
                f"{verb.name} declares {flag!r} consumed but has no "
                f"tests/registry.py::OUTPUT_FLAG_INVOCATIONS[{key!r}] row -- "
                "add one so this pair's honoured side is actually proven"
            )
        # The honoured side is the only C14 arm that runs a real invocation
        # expecting exit 0 -- `_skip_unless_engine_available`'s own module
        # note above. The UNDECLARED/refusal arm below never reaches this and
        # stays engine-independent for every verb, `convert` included.
        _skip_unless_engine_available(INVOCATIONS.get(verb.name))
        args = OUTPUT_FLAG_INVOCATIONS[key](corpus, tmp_path)
        witness, operand_bytes_before = _honoured_witness(verb, flag, args, tmp_path)
        # Snapshotted AFTER the builder call (AC5): everything the ROW created
        # is already on disk here, so nothing below can be satisfied by it.
        before = set(tmp_path.rglob("*"))
        result = run_cli(verb.name, *args, cwd=tmp_path)
        assert_the_verb_itself_wrote(
            verb.name,
            flag,
            witness,
            witness_existed_before=witness in before,
            operand_bytes_before=operand_bytes_before,
            returncode=result.returncode,
            stderr=result.stderr,
            new_paths=frozenset(set(tmp_path.rglob("*")) - before),
        )
    else:
        before = set(tmp_path.rglob("*"))
        args = [*_base_args_for(verb.name, corpus), *_offending_flag_args(flag, tmp_path)]
        result = run_cli(verb.name, *args, cwd=tmp_path)
        assert result.returncode == 2, (
            f"{verb.name} does not declare {flag!r}; expected exit 2, got "
            f"{result.returncode}: {result.stdout}{result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert verb.name in combined, f"OR-3 message does not name the verb: {combined}"
        assert flag in combined, f"OR-3 message does not name the flag: {combined}"
        after = set(tmp_path.rglob("*"))
        assert after == before, (
            f"{verb.name} refused {flag!r} (exit 2) but still wrote something: "
            f"{sorted(str(p) for p in after - before)}"
        )


# --------------------------------------------------------------------------- #
# C15 -- B-054: for every PRODUCING verb, `--dry-run` predicts the SAME exit
# code an occupied or unwritable destination produces for real, and leaves
# the tree byte-identical. Target discovery is GENERIC: the FIRST planned
# output path (`items[0].output`) is read from the verb's own `--dry-run`
# JSON plan rather than a per-verb table, so this works identically for `-O`
# verbs and `--out-dir` verbs, on both pre-fix and post-fix code -- which is
# what makes the negative control possible -- and a future producing verb is
# covered the moment it registers an INVOCATIONS row (already forced by
# `test_every_verb_is_registered`), with zero action from its author.
#
# B-096 -- WHY THE DISCOVERY PREAMBLE IS ENGINE-GATED AND THE ASSERTIONS ARE
# NOT. C15's own assertions remain true on an engine-less host, and were
# measured so: with soffice hidden, `convert`'s occupied-target arm still gives
# dry 5 / real 5 and its unwritable-destination arm still gives dry 1 / real 1,
# because both refusals are FILESYSTEM-tier and are reached before any engine
# is demanded. What an engine-less host breaks is strictly the INSTRUMENT:
# `_discover_target` learns the target by running the invocation under
# `--dry-run -o json` and requires exit 0, and now that an absent engine is
# knowable at plan time (OR-7/D12.1) `convert --dry-run` legitimately exits 3
# before any plan exists. The row cannot be SEEDED there. That is a true
# property of the verb, not a harness defect, so it skips VISIBLY -- via the
# already-landed `_skip_unless_engine_available`, the same mechanism and the
# same `ports.resolve()` chokepoint X-140 authorized for C12 and C14 on
# identical reasoning.
#
# The rule this follows, and the line it draws against C10 above: a row that
# can still assert something real on an engine-less host BRANCHES and never
# skips (C10 -- purity holds regardless of any engine); a row that cannot even
# be SEEDED there skips visibly, and must still RUN where the engine is
# present.
#
# ON THIS MODULE'S "no skip list, no filter, no hard-coded verb name" (AC5,
# module docstring). That property forbids a HAND-MAINTAINED list of excluded
# verbs -- an anti-vacuity guarantee. This gate is not that: it hard-codes no
# verb, reads a per-verb declaration (`Invocation.requires_engine`), and
# resolves it through the product's own port registry. The guarantee is kept by
# two properties, and BOTH are required -- the second is what stops this from
# manufacturing another vacuous control:
#   1. engine hidden  -> the `convert` rows SKIP with a reason naming the
#      engine, never a silent pass;
#   2. engine present -> the `convert` rows still RUN and pass, which CI's
#      `engines-present` leg keeps honest via
#      `scripts/assert_skips.py --expect-zero`.
#
# Deriving the target from the invocation's argv instead was considered and
# rejected: it discards `_discover_target`'s anti-lapse property, and cannot
# work at all for the `--out-dir` + `--name` verbs (`split`, `rasterize`) whose
# final target never appears in the argv.
# --------------------------------------------------------------------------- #


def _discover_target(verb, args: list[str], tmp_path: Path) -> Path:
    """The first planned output path for *verb*'s registered invocation,
    read from the product's own ``--dry-run -o json`` plan.

    Anti-lapse (mirrors C14's own `pytest.fail`, never a silent skip): a
    producing verb whose plan carries no discoverable target -- a future verb
    that writes to stdout, say -- fails here BY NAME rather than quietly
    dropping out of C15's coverage.
    """
    # The gate lives HERE, at the single call site both C15 arms share, so the
    # two can never drift into disagreeing about whether a target is
    # discoverable. See this section's own B-096 note for why the preamble --
    # and only the preamble -- is what an absent engine defeats.
    _skip_unless_engine_available(INVOCATIONS.get(verb.name))
    result = run_cli(verb.name, "--dry-run", *args, "-o", "json", cwd=tmp_path)
    if result.returncode != 0:
        pytest.fail(
            f"{verb.name}: registered invocation --dry-run exited "
            f"{result.returncode}, not 0 -- C15 cannot discover a target from "
            f"a plan that never completed: {result.stdout}{result.stderr}"
        )
    payload = json.loads(result.stdout)
    items = payload.get("items") or []
    output = items[0].get("output") if items else None
    if not output:
        pytest.fail(
            f"{verb.name}: --dry-run produced no discoverable output target "
            "(items[0].output) -- C15 needs one to seed an occupied/unwritable "
            "destination arm; a verb whose destination cannot be discovered "
            "this way needs its own arm added here, by name"
        )
    return Path(output)


@pytest.mark.parametrize("verb", PRODUCING, ids=_ids(PRODUCING))
def test_c15_dry_run_predicts_an_occupied_target_refusal(verb, corpus, tmp_path: Path) -> None:
    """B-054: dry exit code == real exit code over an occupied target, and
    the dry run leaves the seeded bytes untouched."""
    invocation = INVOCATIONS[verb.name]
    args = invocation.build(corpus, tmp_path)
    target = _discover_target(verb, args, tmp_path)

    target.parent.mkdir(parents=True, exist_ok=True)
    seed = b"C15-SEEDED-BYTES"
    target.write_bytes(seed)

    env, roots = redirected_environment(tmp_path)
    before = snapshot(*roots)
    dry = run_cli(verb.name, "--dry-run", *args, env=env, cwd=tmp_path)
    assert_unchanged(before, snapshot(*roots))
    assert target.read_bytes() == seed, f"{verb.name}: --dry-run mutated the occupied target"

    real = run_cli(verb.name, *args, env=env, cwd=tmp_path)

    assert dry.returncode == real.returncode == 5, (
        f"{verb.name}: dry={dry.returncode} real={real.returncode} (expected both 5) -- "
        f"dry: {dry.stdout}{dry.stderr} / real: {real.stdout}{real.stderr}"
    )


@pytest.mark.parametrize("verb", PRODUCING, ids=_ids(PRODUCING))
def test_c15_dry_run_predicts_an_unwritable_destination_refusal(
    verb, corpus, tmp_path: Path
) -> None:
    """B-054's other arm: dry exit code == real exit code == 1 when the
    destination directory exists but cannot accept a write."""
    if os.geteuid() == 0:
        pytest.skip("root ignores directory mode bits; this arm cannot fire as root")

    invocation = INVOCATIONS[verb.name]
    args = invocation.build(corpus, tmp_path)
    target = _discover_target(verb, args, tmp_path)
    destination_dir = target.parent
    destination_dir.mkdir(parents=True, exist_ok=True)

    # $TMPDIR/$HOME must exist BEFORE the lock -- redirected_environment's own
    # mkdir would otherwise fail against the very directory this arm locks.
    env, roots = redirected_environment(tmp_path)

    destination_dir.chmod(0o500)
    try:
        before = snapshot(*roots)
        dry = run_cli(verb.name, "--dry-run", *args, env=env, cwd=tmp_path)
        assert_unchanged(before, snapshot(*roots))

        real = run_cli(verb.name, *args, env=env, cwd=tmp_path)
    finally:
        destination_dir.chmod(0o700)

    assert dry.returncode == real.returncode == 1, (
        f"{verb.name}: dry={dry.returncode} real={real.returncode} (expected both 1) -- "
        f"dry: {dry.stdout}{dry.stderr} / real: {real.stdout}{real.stderr}"
    )


# --------------------------------------------------------------------------- #
# C16 -- B-076: `--in-place` together with a destination flag (`--output`/
# `--out-dir`/`--name`) the SAME verb ALSO declares is a CONFLICT the OR-3
# consumption check (C14 above) cannot see -- both flags sit inside one
# declared set, so C14's matrix reads the pair as honoured even though the
# `ops/` layer's shared `if in_place: ... elif output/out_dir: ...`
# precedence silently drops the destination and mutates the input instead.
# Exit 2, naming both flags, writing and mutating nothing -- B-035's own
# defect class, surviving *inside* the mechanism OR-3 built to end it.
#
# Derived generically off the live registry, exactly like C14: no
# hard-coded verb list, so a future verb (PDF-15's `ocr`, per the ledger)
# is covered the day it declares both flags, zero action from its author.
# --------------------------------------------------------------------------- #

_C16_DESTINATION_FLAGS = tuple(flag for flag in OUTPUT_FLAGS if flag != "--in-place")
IN_PLACE_OUTPUT_CONFLICT_VERBS = tuple(
    verb
    for verb in VERBS
    if "--in-place" in verb.consumes
    and any(flag in verb.consumes for flag in _C16_DESTINATION_FLAGS)
)


def test_c16_instrument_control_output_alone_still_writes(corpus, tmp_path: Path) -> None:
    """Positive control: `-O` alone (no `--in-place`) still honours the
    target -- proves the probe below is not blind, same idiom C14's own
    'declared' branch already relies on."""
    args = OUTPUT_FLAG_INVOCATIONS[("compress", "--output")](corpus, tmp_path)
    result = run_cli("compress", *args, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(args[-1]).is_file()


def test_c16_instrument_control_undeclared_flag_still_exits_2(corpus, tmp_path: Path) -> None:
    """Negative control: an UNDECLARED flag (`info` does not consume
    `--in-place`) still refuses through OR-3's own path -- proves this new
    conflict check has not swallowed or shadowed C14's own refusal."""
    result = run_cli("info", str(corpus.path("single_page")), "--in-place", cwd=tmp_path)
    assert result.returncode == 2


@pytest.mark.parametrize(
    "verb", IN_PLACE_OUTPUT_CONFLICT_VERBS, ids=_ids(IN_PLACE_OUTPUT_CONFLICT_VERBS)
)
def test_c16_in_place_output_conflict_refuses_exit_2(verb, corpus, tmp_path: Path) -> None:
    """B-076: for every verb declaring BOTH `--in-place` and a destination
    flag, giving both together refuses the PAIR -- exit 2, naming both
    flags, writing and mutating nothing. Per B-073, this does NOT pin
    today's exit-0-and-mutate behaviour anywhere -- only the refusal the
    fix introduces."""
    flag = next((f for f in _C16_DESTINATION_FLAGS if f in verb.consumes), None)
    assert flag is not None  # guaranteed by IN_PLACE_OUTPUT_CONFLICT_VERBS's own filter

    in_place_key = (verb.name, "--in-place")
    if in_place_key not in OUTPUT_FLAG_INVOCATIONS:
        pytest.fail(
            f"{verb.name} declares --in-place and {flag!r} but has no "
            f"tests/registry.py::OUTPUT_FLAG_INVOCATIONS[{in_place_key!r}] row -- "
            "add one (C14 needs it too) so C16 can build a copy-safe conflicting "
            "invocation"
        )
    # The `--in-place` row is already copy-safe (never the shared, session-scoped
    # corpus fixture itself, per `_copy_corpus_fixture`'s own docstring) --
    # reused here, with the destination flag appended, rather than building a
    # new row: the verb's `--output` row names the raw corpus path directly,
    # which is safe there ONLY because that row never mutates it.
    base_args = OUTPUT_FLAG_INVOCATIONS[in_place_key](corpus, tmp_path)
    conflicting_args = [*base_args, *_offending_flag_args(flag, tmp_path)]

    operand = Path(base_args[0])
    before_bytes = operand.read_bytes()
    before_files = set(tmp_path.rglob("*"))

    result = run_cli(verb.name, *conflicting_args, cwd=tmp_path)

    assert result.returncode == 2, (
        f"{verb.name}: --in-place + {flag} expected exit 2, got {result.returncode}: "
        f"{result.stdout}{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "--in-place" in combined, f"B-076 message does not name --in-place: {combined}"
    assert flag in combined, f"B-076 message does not name {flag}: {combined}"
    assert operand.read_bytes() == before_bytes, (
        f"{verb.name}: refused (exit 2) but mutated the input"
    )
    after_files = set(tmp_path.rglob("*"))
    assert after_files == before_files, (
        f"{verb.name}: refused (exit 2) but still wrote something: "
        f"{sorted(str(p) for p in after_files - before_files)}"
    )


# --------------------------------------------------------------------------- #
# Three non-parameterized root-level tests (Design §4)
# --------------------------------------------------------------------------- #


def test_root_bogus_subcommand_exits_2() -> None:
    result = run_cli("bogus-subcommand-xyz")
    assert result.returncode == 2


def test_root_help_exits_0_and_lists_every_global_flag() -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    for option in GLOBAL_OPTIONS:
        assert option in result.stdout, f"root --help is missing {option}"


# The §12 R-13 startup-budget assertion (`--help` under 250 ms, best of five)
# is Design §4's third root-level test. Omitted here per AC12's own
# conditional: PDF-01 already shipped it --
# `tests/test_cli_spine.py::test_help_stays_within_the_startup_budget`,
# consuming the same `STARTUP_BUDGET_MS` constant PDF-05 promoted for exactly
# this reuse. Recorded in this spec's Implementation Log (AC12).


# --------------------------------------------------------------------------- #
# AC10 -- the anti-lapse guard: a verb registered in the CLI but absent from
# INVOCATIONS fails the suite, naming the verb.
# --------------------------------------------------------------------------- #


def test_every_verb_is_registered() -> None:
    names = {verb.name for verb in VERBS}
    missing = names - set(INVOCATIONS)
    assert missing == set(), (
        f"verb(s) {sorted(missing)} are discovered on the live CLI tree but have no row in "
        "tests/registry.py::INVOCATIONS -- add one before this suite can pass"
    )


def test_the_anti_lapse_guard_fires_when_a_verb_is_unregistered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Automated proof of AC10: monkeypatch one real, live-discovered verb out
    of INVOCATIONS and confirm the same set-difference this module's own
    `test_every_verb_is_registered` runs would report it -- restored
    automatically by `monkeypatch` on teardown. A manual delete/observe/
    restore cycle against the real file was also run once by hand; see this
    spec's Implementation Log."""
    import registry

    trimmed = dict(registry.INVOCATIONS)
    removed_name, _ = trimmed.popitem()
    monkeypatch.setattr(registry, "INVOCATIONS", trimmed)

    names = {verb.name for verb in registry.discover_verbs()}
    missing = names - set(registry.INVOCATIONS)
    assert missing == {removed_name}


# --------------------------------------------------------------------------- #
# PDF-17 -- V1 (empty population): every derived population, pinned, with a red
#
# `B-032` filed this as "`GROUPS` and `DESTRUCTIVE` have no dedicated emptiness
# pin, unlike `PAGE_ADDRESSING` and `MUTATING`". Re-measured at `2d19bcb` the
# row is wrong in BOTH directions and the true state is materially worse:
# `DESTRUCTIVE` *was* pinned (B-079) and `PAGE_ADDRESSING`/`MUTATING` were
# **not**. The module carried exactly two `assert len(...) > 0` statements
# against FIFTEEN tuple-valued module-level constants -- thirteen unpinned.
#
# Two ad-hoc pins are replaced by ONE parameterized control over a declared
# roster, because a hand-written pin per population is the same shape as a
# hand-typed verb tuple beside a live registry: it covers what someone
# remembered. `test_every_population_is_rostered` is what makes the roster
# unable to lag the module, and `test_a_population_pin_fires` /
# `test_the_roster_check_fires_on_an_unrostered_population` are what make both
# of them instruments rather than claims.
#
# WHY THIS IS NOT `PDF-06` AC6 IN A NEW COSTUME. AC6 pins that `pytest -m e2e
# --collect-only -q` collects a non-zero number of items, and it was GREEN at
# the very commit where C4/C9/C10/C11/C13 each collected zero: an aggregate
# non-emptiness pin cannot see a per-population zero. Every pin below is
# PER-POPULATION, and the roster control is what stops a new population from
# escaping the per-population treatment.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Population:
    """One derived population, the checks it feeds, and its floor."""

    name: str
    members: tuple
    checks: str
    minimum: int
    why: str
    """Why *minimum* is what it is. Argued per row, never defaulted."""


#: Every tuple-valued module-level constant in this module -- the ones defined
#: here AND the two imported from the product -- with the check(s) it feeds and
#: the cardinality below which that check stops discriminating. Adding a
#: population without adding a row here fails `test_every_population_is_rostered`.
#:
#: EVERY `minimum` IS 1, AND THAT IS AN ARGUMENT RATHER THAN A DEFAULT. A pin
#: that fails for a CORRECT reason -- a verb legitimately retired, a flag
#: legitimately withdrawn -- gets weakened by the next author rather than
#: investigated, which converts an instrument back into a claim. `DESTRUCTIVE`
#: is the sharpest case: `compress` and `ocr` both carry a `destructive_build`
#: today, but pinning it at 2 would fail the day one of them is retired for a
#: good reason. One is the floor at which the check still RUNS; above that, the
#: population's own derivation is what keeps it honest.
POPULATIONS: Final[tuple[Population, ...]] = (
    Population(
        "VERBS",
        VERBS,
        "C1,C2,C3,C7,C8,C14",
        1,
        "the root population; zero makes six checks collect zero cases at once",
    ),
    Population(
        "GROUPS",
        GROUPS,
        "C4",
        1,
        "one grouping parent exists (`meta`, PDF-14). NECESSARY BUT NOT SUFFICIENT: a "
        "single-element population passes an emptiness pin while being one refactor away "
        "from vacuity, so C4's real guarantee is `discover_groups()`'s derivation, not this",
    ),
    Population(
        "MUTATING",
        MUTATING,
        "C9,C10",
        1,
        "unpinned before PDF-17 despite B-032 claiming otherwise; zero makes both "
        "dry-run purity checks collect zero cases",
    ),
    Population(
        "PAGE_ADDRESSING",
        PAGE_ADDRESSING,
        "C6",
        1,
        "unpinned before PDF-17 despite B-032 claiming otherwise",
    ),
    Population("TAKES_INPUT_PATHS", TAKES_INPUT_PATHS, "C5", 1, "zero makes C5 collect zero cases"),
    Population(
        "REGISTERED",
        REGISTERED,
        "C12",
        1,
        "`test_every_verb_is_registered` forces REGISTERED == VERBS, so a zero here means "
        "the CLI tree itself came back empty",
    ),
    Population(
        "DESTRUCTIVE",
        DESTRUCTIVE,
        "C13",
        1,
        "the population that sat EMPTY from PDF-06 through PDF-14, which is why the bulk "
        "confirmation gate went unwired on five verbs with the suite green throughout. "
        "NOT 2: `compress` and `ocr` both qualify today, but a pin that fails when a verb "
        "is legitimately retired gets lowered rather than investigated",
    ),
    Population(
        "_DESTINATION_FLAGS",
        _DESTINATION_FLAGS,
        "feeds PRODUCING -> C15",
        1,
        "a literal rather than a derivation, and pinned anyway: an empty one silently "
        "empties PRODUCING and takes both C15 arms down with it",
    ),
    Population(
        "PRODUCING",
        PRODUCING,
        "C15",
        1,
        "zero makes both C15 arms (occupied target, unwritable destination) collect zero",
    ),
    Population(
        "OUTPUT_CONSUMING_MUTATING", OUTPUT_CONSUMING_MUTATING, "C11", 1, "zero makes C11 vacuous"
    ),
    Population(
        "OUTPUT_FLAG_CASES",
        OUTPUT_FLAG_CASES,
        "C14",
        1,
        "the full VERBS x OUTPUT_FLAGS cross-product; zero takes down the entire OR-3 "
        "matrix arm, honoured and refused sides together",
    ),
    Population(
        "_C16_DESTINATION_FLAGS",
        _C16_DESTINATION_FLAGS,
        "feeds IN_PLACE_OUTPUT_CONFLICT_VERBS -> C16",
        1,
        "empty makes IN_PLACE_OUTPUT_CONFLICT_VERBS empty by construction",
    ),
    Population(
        "IN_PLACE_OUTPUT_CONFLICT_VERBS",
        IN_PLACE_OUTPUT_CONFLICT_VERBS,
        "C16",
        1,
        "B-076's own population, whose history is three separately-measured, all-too-narrow "
        "scopes (five, then three, then four verbs) before it was re-derived at eleven",
    ),
    Population(
        "GLOBAL_OPTIONS",
        GLOBAL_OPTIONS,
        "C2, test_root_help_exits_0_and_lists_every_global_flag",
        1,
        "IMPORTED from `pdf_toolkit.cli.common`, and pinned here because C2's assertions "
        "live inside a `for option in GLOBAL_OPTIONS` loop: an empty tuple makes C2 report "
        "26 green cases having asserted nothing at all",
    ),
    Population(
        "OUTPUT_FLAGS",
        OUTPUT_FLAGS,
        "feeds OUTPUT_FLAG_CASES -> C14; _C16_DESTINATION_FLAGS -> C16",
        1,
        "IMPORTED from `pdf_toolkit.cli.common`; empty empties C14's whole matrix",
    ),
    Population(
        "HONOURED_CELLS",
        HONOURED_CELLS,
        "test_a_planted_exit_0_without_writing_fails_every_honoured_cell",
        1,
        "PDF-17's own population, and it is in this roster because "
        "`test_every_population_is_rostered` FIRED ON IT during implementation -- the "
        "roster control catching its own author is the evidence that it is not decorative. "
        "Empty means AC7's red proof collects zero cases and reports green, which is the "
        "precise shape (`PDF-06` AC6) this spec exists to end",
    ),
)

_ROSTERED: Final[frozenset[str]] = frozenset(row.name for row in POPULATIONS)


@pytest.mark.parametrize("population", POPULATIONS, ids=[row.name for row in POPULATIONS])
def test_every_population_is_non_empty(population: Population) -> None:
    """The V1 pin, per population rather than in aggregate."""
    assert len(population.members) >= population.minimum, (
        f"{population.name} has {len(population.members)} member(s), below its floor of "
        f"{population.minimum} -- the check(s) it feeds ({population.checks}) would then "
        f"collect zero parametrized cases and report GREEN having asserted nothing. "
        f"Why this floor: {population.why}"
    )


def module_level_tuple_names(source: str, namespace: Mapping[str, object]) -> frozenset[str]:
    """Every module-level name in *source* whose live value in *namespace* is a tuple.

    Assignments AND imports, because two of this module's populations
    (`GLOBAL_OPTIONS`, `OUTPUT_FLAGS`) are the product's own constants imported
    from `pdf_toolkit.cli.common` -- and an empty `GLOBAL_OPTIONS` makes C2
    vacuous just as surely as an empty `VERBS` makes C1 vacuous.

    Static over the module's own source (`ast`, the convention
    `tests/registry.py` and `tests/test_import_boundaries.py` already share)
    rather than a bare `vars()` scan, so a tuple bound inside a function or a
    class body is not mistaken for a module-level population.
    """
    tree = ast.parse(source)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
    return frozenset(name for name in names if isinstance(namespace.get(name), tuple))


def unrostered_populations(
    source: str, namespace: Mapping[str, object], rostered: frozenset[str]
) -> list[str]:
    """The module-level tuple constants that have no `POPULATIONS` row."""
    return sorted(module_level_tuple_names(source, namespace) - rostered - {"POPULATIONS"})


def test_every_population_is_rostered() -> None:
    """Without this, `POPULATIONS` is a hand-maintained list beside a live
    module -- the exact `e138934a60` shape this spec exists to end,
    reintroduced by its own fix. A population added by a later spec is pinned
    the day it exists rather than the day someone remembers."""
    source = Path(__file__).read_text(encoding="utf-8")
    missing = unrostered_populations(source, dict(globals()), _ROSTERED)
    assert missing == [], (
        f"module-level tuple population(s) {missing} have no row in POPULATIONS -- add one "
        "naming the check(s) each feeds and a `minimum` with a stated argument, or the new "
        "population is exempt from the only emptiness pin this module has"
    )


# --------------------------------------------------------------------------- #
# Proof that the population guards fire. Without these, the two tests above are
# a claim (`tests/test_import_boundaries.py:481`'s own idiom).
# --------------------------------------------------------------------------- #


def test_a_population_pin_fires(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1's red, automated: empty ONE population and confirm the pin fails
    naming that population AND the checks it feeds. A manual monkeypatch of the
    real module was also run once by hand; see PDF-17's Implementation Log for
    the verbatim message."""
    for row in POPULATIONS:
        emptied = Population(row.name, (), row.checks, row.minimum, row.why)
        with pytest.raises(AssertionError) as caught:
            test_every_population_is_non_empty(emptied)
        message = str(caught.value)
        assert row.name in message, f"the pin's message does not name {row.name}"
        assert row.checks in message, f"the pin's message does not name {row.name}'s checks"


def test_the_roster_check_fires_on_an_unrostered_population() -> None:
    """AC2's red, automated: a synthetic module whose source declares a derived
    tuple absent from the roster is reported BY NAME. Synthetic rather than a
    real edit for the same reason `tests/test_acceptance_audit.py`'s proofs are
    synthetic -- a red proof that vandalises the registry it proves is not a
    proof."""
    source = "VERBS = discover_verbs()\nSMUGGLED = tuple(v for v in VERBS if v.is_mutating)\n"
    namespace = {"VERBS": VERBS, "SMUGGLED": MUTATING}
    assert unrostered_populations(source, namespace, frozenset({"VERBS"})) == ["SMUGGLED"]
    # ...and the same check is quiet once the row exists.
    assert unrostered_populations(source, namespace, frozenset({"VERBS", "SMUGGLED"})) == []


def test_the_roster_scan_sees_this_module_at_all() -> None:
    """The non-vacuity guard for the guard: a `module_level_tuple_names` that
    returned an empty set would make `test_every_population_is_rostered` pass
    for the worst possible reason. Pinned against the roster's own length, so
    the two cannot drift apart silently."""
    found = module_level_tuple_names(Path(__file__).read_text(encoding="utf-8"), dict(globals()))
    assert len(found) >= len(POPULATIONS), (
        f"the AST scan found {len(found)} module-level tuple(s) but POPULATIONS declares "
        f"{len(POPULATIONS)} -- the scan itself has stopped seeing this module"
    )
    assert "VERBS" in found and "GLOBAL_OPTIONS" in found, sorted(found)


# --------------------------------------------------------------------------- #
# PDF-17 -- V2: proof that C14's honoured side fires.
#
# The planted defect is the B-035 shape the old comment claimed to catch and
# did not: a run that EXITS 0 AND WRITES NOTHING. Driven against the pure
# assertion over EVERY honoured cell rather than against a mutated `src/`,
# because (a) PDF-17's `src/` budget is zero lines and (b) 53 extra CLI spawns
# is a `make ci` regression, which `decision.md` §5 R-1 makes a BLOCKER rather
# than a cost to absorb. The END-TO-END version of this probe -- the real
# `_discover_target`, the real builders, the verb genuinely never run -- was
# run once out of tree and its counts are recorded in PDF-17's Implementation
# Log, including how many cells the PRE-CHANGE assertion let the same planted
# defect pass.
# --------------------------------------------------------------------------- #


def test_the_honoured_population_matches_the_declared_registry() -> None:
    """Totality between the two registries, and the non-vacuity guard for the
    red proof below: an empty `HONOURED_CELLS` would make that proof collect
    zero cases and report green, which is `PDF-06` AC6's own defect."""
    assert len(HONOURED_CELLS) > 0, "HONOURED_CELLS is empty -- C14's honoured side is vacuous"
    assert {(verb.name, flag) for verb, flag in HONOURED_CELLS} == set(OUTPUT_FLAG_INVOCATIONS), (
        "the OR-3 declarations and OUTPUT_FLAG_INVOCATIONS disagree about which cells are "
        "honoured -- C14's own pytest.fail catches one direction, this catches both"
    )


@pytest.mark.parametrize(("verb", "flag"), HONOURED_CELLS, ids=_output_flag_ids(HONOURED_CELLS))
def test_a_planted_exit_0_without_writing_fails_every_honoured_cell(
    verb, flag: str, tmp_path: Path
) -> None:
    """AC7's red: exit 0, nothing written, for EVERY honoured cell -- naming
    the verb, the flag and the expected path."""
    if (verb.name, flag) in NO_BACKUP_IN_PLACE_CELLS:
        witness = tmp_path / "planted-no-backup-operand.pdf"
        witness.write_bytes(b"%PDF-1.4\n%%EOF\n")
        operand_bytes_before: bytes | None = witness.read_bytes()
    else:
        witness = tmp_path / f"planted-{verb.name.replace(' ', '-')}{flag}.out"
        operand_bytes_before = None

    with pytest.raises(AssertionError) as caught:
        assert_the_verb_itself_wrote(
            verb.name,
            flag,
            witness,
            witness_existed_before=operand_bytes_before is not None,
            operand_bytes_before=operand_bytes_before,
            returncode=0,
            stderr="",
            new_paths=frozenset(),
        )
    message = str(caught.value)
    assert verb.name in message, message
    assert flag in message, message
    assert str(witness) in message, message


def test_the_honoured_precondition_pin_fires_when_the_builder_made_the_target(
    tmp_path: Path,
) -> None:
    """The other half of AC5: a row whose own builder creates the destination
    proves nothing, and must say so BY FAILING rather than by passing."""
    witness = tmp_path / "the-builder-already-made-this.pdf"
    with pytest.raises(AssertionError) as caught:
        assert_the_verb_itself_wrote(
            "merge",
            "--output",
            witness,
            witness_existed_before=True,
            operand_bytes_before=None,
            returncode=0,
            stderr="",
            new_paths=frozenset({witness}),
        )
    assert "ALREADY existed before the run" in str(caught.value)


def test_the_honoured_assertion_passes_a_verb_that_really_wrote(tmp_path: Path) -> None:
    """The positive control. Without it, an `assert_the_verb_itself_wrote` that
    raised unconditionally would satisfy every red proof above and fail every
    real cell -- a guard that cannot pass is as useless as one that cannot
    fail."""
    witness = tmp_path / "really-written.pdf"
    witness.write_bytes(b"%PDF-1.4\n%%EOF\n")
    assert_the_verb_itself_wrote(
        "merge",
        "--output",
        witness,
        witness_existed_before=False,
        operand_bytes_before=None,
        returncode=0,
        stderr="",
        new_paths=frozenset({witness}),
    )


def test_the_no_backup_in_place_allowlist_is_not_stale(corpus, tmp_path: Path) -> None:
    """Every allowlisted cell must still be a real declared honoured cell whose
    row really does pass `--no-backup`. Without this the allowlist outlives its
    reason and silently downgrades a cell from the unforgeable `.bak` witness
    to the weaker byte-change one."""
    declared = {(verb.name, flag) for verb, flag in HONOURED_CELLS}
    for cell in sorted(NO_BACKUP_IN_PLACE_CELLS):
        assert cell in declared, f"{cell} is allowlisted but is no longer a declared C14 cell"
        args = OUTPUT_FLAG_INVOCATIONS[cell](corpus, tmp_path)
        assert "--no-backup" in args, (
            f"{cell} is allowlisted as suppressing the .bak sidecar but its row no longer "
            "passes --no-backup -- remove the allowlist entry so the cell goes back to the "
            "unforgeable sidecar witness"
        )


# --------------------------------------------------------------------------- #
# PDF-17 -- C13: B-047's reinstatement path, closed.
#
# The MECHANISM landed with B-079 (`Invocation.destructive_build`); the GUARD
# never did. `registry.py` documented `None` as "C13 falls back to `build`",
# and both C13 rows took that fallback -- so the next author to write
# `destructive=True` without a `destructive_build` would have silently
# re-shared C12's single-input `-O` tail, C13 would have stopped
# discriminating, and NO TEST WOULD HAVE FAILED. That is B-047 reinstating
# itself through a documented door.
#
# PDF-17 deletes the fallback rather than pragma-ing it (Design §4 control 2
# prefers deletion): a documented path that cannot execute is the next
# reader's trap, and `destructive_argv` below turns a missing row into a
# failure that names the verb and the field to add.
# --------------------------------------------------------------------------- #


def destructive_argv(invocation, verb_name: str, corpus, tmp_path: Path) -> list[str]:
    """C13's bulk, `--in-place` argv for *verb_name*. No fallback to `build`."""
    build = invocation.destructive_build
    assert build is not None, (
        f"{verb_name} is destructive=True but supplies no `destructive_build` -- C13 would "
        "fall back to `build`, which is the SINGLE-INPUT `-O` shape C12 uses, so the "
        "bulk-destructive confirmation gate would go untested while C13 reported green. "
        "Add a `destructive_build` to tests/registry.py::INVOCATIONS (B-047)."
    )
    return build(corpus, tmp_path)


@pytest.mark.parametrize("verb", DESTRUCTIVE, ids=_ids(DESTRUCTIVE))
def test_a_destructive_row_supplies_its_own_bulk_argv(verb) -> None:
    """AC8. The guard B-047 asked for -- not the field, which already existed."""
    assert INVOCATIONS[verb.name].destructive_build is not None, (
        f"tests/registry.py::INVOCATIONS[{verb.name!r}] is destructive=True with "
        "destructive_build=None. `registry.py`'s own reasoning: `build` is SHARED by "
        "C1/C9/C10/C11/C12/C15 and is a single-input, `-O`-terminated shape which "
        "'cannot exercise C13's bulk-destructive ground at all'."
    )


def test_the_destructive_argv_guard_fires_on_a_missing_row(corpus, tmp_path: Path) -> None:
    """AC8's red, automated against a synthetic Invocation -- the manual
    version (setting `compress`'s row to None in the real file, observing the
    named failure, restoring with `git show HEAD:`) is in PDF-17's
    Implementation Log with the verbatim message."""
    from registry import Invocation

    orphan = Invocation(build=lambda corpus, tmp_path: [], destructive=True)
    with pytest.raises(AssertionError) as caught:
        destructive_argv(orphan, "hypothetical", corpus, tmp_path)
    message = str(caught.value)
    assert "hypothetical" in message
    assert "destructive_build" in message


# --------------------------------------------------------------------------- #
# PDF-17 -- AC9: a routing COMMENT is tied to the test it credits.
#
# `tests/registry.py` routes `extract`/`delete`/`rotate`/`reorder` away from
# C13's population and justifies it by crediting a test elsewhere. That
# argument is sound -- a single input writing to `-O` is neither bulk nor
# destructive -- but until now it was a COMMENT, and nothing tied the claim to
# its evidence. A credited test that is renamed or deleted leaves the routing
# decision standing on nothing, which is the same "a claim must be tied to its
# evidence" shape as `AUDIT-CONVENTION(PDF-17)` itself.
# --------------------------------------------------------------------------- #

_CREDITED_NODE_ID = re.compile(r"`(tests/[\w/]+\.py)::(\w+)`")

#: The specific claim AC9 is about, located by its own words so the tie moves
#: with the sentence rather than with a line number.
_ROUTING_CLAIM = re.compile(
    r"posture these three DO honour is asserted directly by `(tests/[\w/]+\.py)::(\w+)`"
)


def comment_text(source: str) -> str:
    """*source*'s comment lines, de-hashed and joined — so a claim wrapped
    across several `#` lines is one sentence again."""
    stripped = [
        line.lstrip().lstrip("#").lstrip(":").strip()
        for line in source.splitlines()
        if line.lstrip().startswith("#")
    ]
    return " ".join(part for part in stripped if part)


def credited_node_ids(source: str) -> list[tuple[str, str]]:
    """Every `tests/...py::test_name` node id named inside a COMMENT in *source*."""
    return _CREDITED_NODE_ID.findall(comment_text(source))


def routing_claim_credit(source: str) -> tuple[str, str] | None:
    """The node id `registry.py`'s PDF-08 routing comment credits, or None."""
    match = _ROUTING_CLAIM.search(comment_text(source))
    return (match.group(1), match.group(2)) if match else None


def _test_functions(module: Path) -> dict[str, str]:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    return {
        node.name: ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }


def test_every_node_id_the_registry_credits_still_resolves() -> None:
    """The general rule: `tests/registry.py` may cite a test as evidence for a
    decision, and every such citation must resolve. A comment that credits a
    deleted test is a decision standing on nothing."""
    import registry

    source = Path(registry.__file__).read_text(encoding="utf-8")
    credited = credited_node_ids(source)
    assert credited, (
        "tests/registry.py's comments credit no node id at all -- PDF-17 added two, so "
        "either they were removed or this parser has stopped reading comments"
    )
    unresolved = [
        f"{relative}::{name}"
        for relative, name in credited
        if not (REPO_ROOT / relative).is_file() or name not in _test_functions(REPO_ROOT / relative)
    ]
    assert unresolved == [], (
        f"tests/registry.py credits node id(s) that no longer resolve: {unresolved}"
    )


def test_the_pdf_08_destructive_routing_claim_names_a_test_that_exists() -> None:
    """AC9's tie, on the specific claim.

    `registry.py` routes `extract`/`delete`/`rotate`/`reorder` away from C13's
    population and justifies it by crediting a test elsewhere. Until PDF-17 the
    credit named a whole MODULE and nothing checked it, so the routing decision
    could outlive the test that justified it.
    """
    import registry

    source = Path(registry.__file__).read_text(encoding="utf-8")
    credit = routing_claim_credit(source)
    assert credit is not None, (
        "tests/registry.py's PDF-08 routing comment no longer credits a node id -- the "
        "argument for keeping extract/delete/rotate/reorder out of C13's population is "
        "back to being an untied claim"
    )
    relative, test_name = credit
    module = REPO_ROOT / relative
    assert module.is_file(), f"credited module {relative} does not exist"
    functions = _test_functions(module)
    assert test_name in functions, (
        f"tests/registry.py credits {relative}::{test_name} with asserting PDF-08's "
        "bulk `--in-place` non-TTY posture, and that test no longer exists. Either "
        "the credit is stale or the coverage it stands for is gone -- the routing "
        "decision it justifies (destructive=False for four verbs) cannot outlive it."
    )
    # `ast.unparse` normalizes string quoting, so the tokens are compared
    # against a quote-normalized body rather than the source's own quote style.
    body = functions[test_name].replace('"', "'")
    for token in ("'--in-place'", "== 5", "'-y'"):
        assert token in body, (
            f"{relative}::{test_name} exists but no longer contains {token} -- it is "
            "credited with proving the bulk non-TTY refusal/confirmation pair, and a "
            "renamed-but-hollowed test satisfies the credit without the coverage"
        )


def test_the_credited_node_id_parser_can_find_and_miss() -> None:
    """The tie's own red proof: the parser really does read a node id out of a
    comment (including one wrapped across several `#` lines, which is how the
    real credit is written), and really does return nothing when the credit is
    dropped."""
    assert credited_node_ids("# see `tests/integration/test_x.py::test_y` for the proof") == [
        ("tests/integration/test_x.py", "test_y")
    ]
    assert credited_node_ids("# see tests/integration/test_x.py for the proof") == []
    # A node id in CODE (a string literal, say) is not a credit.
    assert credited_node_ids('NODE = "`tests/test_x.py::test_y`"') == []
    # The specific claim survives being wrapped across lines, and disappears
    # when the sentence does -- which is the failure mode AC9 is about.
    wrapped = (
        "    # posture these three DO honour is asserted directly by\n"
        "    # `tests/integration/test_pages_cli.py::test_ac21_x`\n"
        "    # instead of by giving C13 a row it would pass vacuously.\n"
    )
    assert routing_claim_credit(wrapped) == (
        "tests/integration/test_pages_cli.py",
        "test_ac21_x",
    )
    assert routing_claim_credit("# some other comment entirely\n") is None
