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
`Invocation.destructive_build`); `test_c13_population_is_non_empty` below is
the anti-lapse guard so this cannot silently regress to zero again.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from fs_snapshot import assert_unchanged, redirected_environment, snapshot
from pdf_toolkit.cli.common import GLOBAL_OPTIONS, OUTPUT_FLAGS
from registry import INVOCATIONS, OUTPUT_FLAG_INVOCATIONS, discover_groups, discover_verbs, run_cli

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
# C10 -- (reg) the registered invocation + --dry-run exits 0, tree unchanged
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", MUTATING, ids=_ids(MUTATING))
def test_c10_registered_invocation_dry_run_purity(verb, corpus, tmp_path: Path) -> None:
    invocation = INVOCATIONS[verb.name]
    args = invocation.build(corpus, tmp_path)
    env, roots = redirected_environment(tmp_path)
    before = snapshot(*roots)
    result = run_cli(verb.name, "--dry-run", *args, env=env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
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
# C12 -- (reg) stdout on a pipe with no -o parses as JSON carrying
# schema_version.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", REGISTERED, ids=_ids(REGISTERED))
def test_c12_json_on_a_pipe_by_default(verb, corpus, tmp_path: Path) -> None:
    invocation = INVOCATIONS[verb.name]
    args = invocation.build(corpus, tmp_path)
    result = run_cli(verb.name, *args)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "schema_version" in payload


# --------------------------------------------------------------------------- #
# C13 -- (reg) bulk destructive without -y refuses on a non-TTY; -y succeeds;
# a single-input run never refuses.
# --------------------------------------------------------------------------- #


def test_c13_population_is_non_empty() -> None:
    """B-079's own anti-lapse guard: a green C13 whose population is empty
    is exactly the failure this row exists to prevent (`DESTRUCTIVE` sat
    empty from PDF-06 through PDF-14, which is why the gate went unwired on
    five verbs without the suite ever noticing). Fails BY NAME, mirroring
    `test_every_verb_is_registered`'s own shape, rather than letting C13
    quietly collect zero cases again."""
    assert len(DESTRUCTIVE) > 0, (
        "DESTRUCTIVE is empty -- C13 would collect zero parametrized cases and pass "
        "vacuously; this is B-079's own defect shape (a control that cannot bite)"
    )


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
    args = (invocation.destructive_build or invocation.build)(corpus, tmp_path)
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


# --------------------------------------------------------------------------- #
# C14 -- the OR-3 matrix arm (AC25, Design §D12). Every verb in the LIVE
# registry x every OUTPUT_FLAGS entry -> honoured (a file appears) or exit 2.
# No skip list, no filter, no hard-coded verb name -- driven off
# `discover_verbs()` x `OUTPUT_FLAGS`, exactly like every other check in this
# module. A future verb is covered the day it registers, not the day someone
# remembers to extend a list.
# --------------------------------------------------------------------------- #

OUTPUT_FLAG_CASES = tuple((verb, flag) for verb in VERBS for flag in OUTPUT_FLAGS)


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


@pytest.mark.parametrize(
    ("verb", "flag"), OUTPUT_FLAG_CASES, ids=_output_flag_ids(OUTPUT_FLAG_CASES)
)
def test_c14_output_flag_matrix(verb, flag: str, corpus, tmp_path: Path) -> None:
    declared = flag in verb.consumes
    before = set(tmp_path.rglob("*"))

    if declared:
        key = (verb.name, flag)
        if key not in OUTPUT_FLAG_INVOCATIONS:
            pytest.fail(
                f"{verb.name} declares {flag!r} consumed but has no "
                f"tests/registry.py::OUTPUT_FLAG_INVOCATIONS[{key!r}] row -- "
                "add one so this pair's honoured side is actually proven"
            )
        args = OUTPUT_FLAG_INVOCATIONS[key](corpus, tmp_path)
        result = run_cli(verb.name, *args, cwd=tmp_path)
        assert result.returncode == 0, (
            f"{verb.name} declares {flag!r} but the invocation refused: {result.stderr}"
        )
        after = set(tmp_path.rglob("*"))
        assert after - before, (
            f"{verb.name} declares {flag!r} but no new file appeared under the target "
            "-- this is B-035's own shape (exit 0, nothing written)"
        )
    else:
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
# --------------------------------------------------------------------------- #


def _discover_target(verb, args: list[str], tmp_path: Path) -> Path:
    """The first planned output path for *verb*'s registered invocation,
    read from the product's own ``--dry-run -o json`` plan.

    Anti-lapse (mirrors C14's own `pytest.fail`, never a silent skip): a
    producing verb whose plan carries no discoverable target -- a future verb
    that writes to stdout, say -- fails here BY NAME rather than quietly
    dropping out of C15's coverage.
    """
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
