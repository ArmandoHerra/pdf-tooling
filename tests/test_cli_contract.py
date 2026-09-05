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
from typing import Annotated, Final

import pytest
import typer
import typer.core
import typer.models

from fs_snapshot import assert_unchanged, redirected_environment, snapshot
from pdf_toolkit.cli.common import GLOBAL_OPTIONS, OUTPUT_FLAGS
from registry import (
    INVOCATIONS,
    OUTPUT_FLAG_INVOCATIONS,
    REPO_ROOT,
    discover_groups,
    discover_verbs,
    out_dir_batch_verbs,
    run_cli,
)

pytestmark = pytest.mark.e2e

VERBS = discover_verbs()
GROUPS = discover_groups()
#: PDF-40 -- the `--out-dir` batch class: every verb whose batch can carry a bad
#: input IN THE MIDDLE. Derived in `registry.out_dir_batch_verbs()` from the
#: `--out-dir` consumer set, each operand's arity, and the live VERB name (never
#: the module basename -- `cli/cmd_office.py` registers `convert`). `split` is
#: the one consumer excluded, BY ARITY rather than by a literal.
OUT_DIR_BATCH = out_dir_batch_verbs()
MUTATING = tuple(verb for verb in VERBS if verb.is_mutating)
#: AC21 (PDF-20) — the population C9 and C10 measure. **Every verb, not just the
#: mutating ones.** `CLAUDE.md` rule 2 and `README.md`'s own claim state
#: `--dry-run` purity WITHOUT a condition ("it writes nothing, anywhere"), so
#: the instrument that measures it has no business being narrower than the
#: claim. It was narrower, and `doctor` -- which is structurally outside
#: `MUTATING`, because `is_mutating` derives from reaching the `AtomicWriter`
#: chokepoint and `doctor` never does -- wrote `$HOME/.config` on every run for
#: a whole cycle with both rows green (`ba07fdfb56` / B-100, B-075). The
#: impurity was not missed; it was UNREACHABLE by the instrument.
#:
#: Widened HERE rather than by touching `is_mutating`: the classifier is right
#: about what it classifies (which verbs reach the write chokepoint) and C11 /
#: C13 depend on that meaning. Purity simply is not a mutating-verb property.
DRY_RUN_PURITY = VERBS

#: The three keys `schema_version: 1` promises on every verb's `-o json` object.
#: `dry_run` is here because it was absent from exactly one envelope and nothing
#: was watching (E3: the invariant was upheld by two independent mechanisms,
#: neither of them enforced, and `doctor` rode neither).
ENVELOPE_KEYS: Final[tuple[str, ...]] = ("schema_version", "verb", "dry_run")
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

#: PDF-25 / `a472acde7a` — C17's population. `C4` above covers a BOGUS
#: SUBCOMMAND at every grouping parent; nothing covered a VALID GLOBAL FLAG at
#: one, and all fifteen members of the block exited 2 with zero bytes on stdout
#: there. Both factors are themselves rostered below, so this product is
#: non-empty exactly when they are.
GROUP_GLOBAL_FLAG_CASES = tuple((group, flag) for group in GROUPS for flag in GLOBAL_OPTIONS)


def operand_verb_names(root: object | None = None) -> frozenset[str]:
    """Every command on *root* that declares at least one positional operand.

    Duck-typed on `param_type_name == "argument"` for the same reason
    `registry.py::discover_verbs` duck-types its own walk: the CLI framework
    vendors its own click, so there is no importable top-level `click.Argument`
    to `isinstance`-check against. Deliberately NOT filtered on the parameter's
    type name -- that filter is what excludes `merge` (E5).
    """
    from pdf_toolkit.cli.main import app

    group = root if root is not None else typer.main.get_command(app)
    names: set[str] = set()

    def _walk(cmd: object, path: tuple[str, ...]) -> None:
        commands = getattr(cmd, "commands", None)
        if commands is not None:
            for name in sorted(commands):
                _walk(commands[name], (*path, name))
            return
        params = getattr(cmd, "params", ())
        if any(getattr(param, "param_type_name", None) == "argument" for param in params):
            names.add(" ".join(path))

    _walk(group, ())
    return frozenset(names)


#: AC7 -- every verb that accepts an operand, derived from the LIVE tree at run
#: time. 24 at `cdc02ee` (every command except `doctor` and `version`, which
#: accept no operand); the size is asserted against the live walk rather than
#: pinned to a literal, so a 25th operand verb joins this row the day it is
#: registered and a retired one does not fail the suite for a correct reason.
OPERAND_VERBS = tuple(verb for verb in VERBS if verb.name in operand_verb_names())


def _unreadable_shapes() -> tuple[tuple[str, bool], ...]:
    """AC15's `{table, json, ndjson} x {default, --quiet}` cross-product.

    `output_formats()` is CONSUMED rather than re-listed (X-157), so a fourth
    renderer joins this matrix with no action from its author. The quiet
    dimension is a local literal rather than a module-level tuple because
    `tty_modes()` -- the only existing two-member boolean helper -- means
    `isatty()`, and reusing it here would make this matrix claim something it
    does not measure.
    """
    from registry import output_formats

    return tuple((fmt.value, quiet) for fmt in output_formats() for quiet in (False, True))


#: The shapes `C18` drives every member of `OPERAND_VERBS` through. A traceback
#: that only escapes under `-o ndjson --quiet` is still a traceback.
UNREADABLE_SHAPES = _unreadable_shapes()


def _engine_visible_shapes() -> tuple[tuple[str, bool], ...]:
    """PDF-36 -- the subset of `UNREADABLE_SHAPES` that renders `kind` and `code`.

    `E3`'s first census was WRONG in a way that generalizes: passing `--pages 1`
    to `compress` returned `{"kind": "usage", "code": 2}` -- exit 2, never
    reaching the engine -- so the drive reported `permissions` as the ONLY
    leaking verb when four verbs leak. **A drive whose cells are usage errors
    measures the parser, not the engine.**

    `C20` therefore asserts that a cell REACHED ITS ENGINE before it draws any
    conclusion from that cell's message, and `kind`/`code` are only legible in
    a structured shape -- `render_error_table` prints a bare `error: <message>`
    line and carries neither. This is that subset, filtered from the live
    `output_formats()` rather than listed, so a fourth structured renderer
    joins it with no action from its author.
    """
    from registry import output_formats

    return tuple(
        (fmt.value, quiet)
        for fmt in output_formats()
        for quiet in (False, True)
        if fmt.value != "table"
    )


#: The shapes whose envelope names its own `kind` and `code` (`C20`).
ENGINE_VISIBLE_SHAPES = _engine_visible_shapes()

#: The verbs measured to leak a heap address at `ae723bc`, driven against a
#: garbage fixture. **The ledger row `5bd9143f61` names TWO** (`compress` and
#: `repair`); the drive found FOUR. Both the inherited value and the measured
#: one are recorded (`X-411`), and the measured one is `C20`'s positive control.
LEAKING_VERBS_AT_AE723BC: Final[tuple[str, ...]] = (
    "compress",
    "linearize",
    "permissions",
    "repair",
)

#: AC9 / §D7 -- the SINGLE-COMBINED-ARTIFACT class, DERIVED from each verb's own
#: OR-3 declaration rather than hand-written: N inputs -> 1 file is exactly
#: "declares `--output` and does not declare `--out-dir`". These verbs must NOT
#: survive a bad input; they must abort and write nothing. `merge` says why, and
#: it is right -- *a partially merged document is a wrong document that looks
#: right* -- and a verb that skipped an unreadable input and merged the rest
#: would be a silent wrong answer carrying a success exit code.
SINGLE_ARTIFACT_VERBS = tuple(
    verb
    for verb in OPERAND_VERBS
    if "--output" in verb.consumes and "--out-dir" not in verb.consumes
)

#: AC10's fourth arm -- OR-3 must stay unconfused. §D4 changes the READABILITY
#: VETO on `-O/--output`, never its consumption semantics: a verb that does not
#: declare `--output` still exits 2 when given one, unreadable target or not.
OUTPUT_REFUSING_VERBS = tuple(verb for verb in OPERAND_VERBS if "--output" not in verb.consumes)


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


@pytest.mark.parametrize("verb", DRY_RUN_PURITY, ids=_ids(DRY_RUN_PURITY))
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


@pytest.mark.parametrize("verb", DRY_RUN_PURITY, ids=_ids(DRY_RUN_PURITY))
def test_c10_registered_invocation_dry_run_purity(verb, corpus, tmp_path: Path) -> None:
    invocation = INVOCATIONS[verb.name]
    # Resolved BEFORE the snapshot opens -- RETAINED by PDF-20 (AC21), with the
    # reason re-measured rather than inherited.
    #
    # The claim this hoist used to carry was that it kept a `$HOME`-writing
    # probe out of the purity window. `PDF-20` D3.3 went further and called the
    # ordering "a control that cannot fail, on the exact defect it would
    # otherwise catch". **Measured: that causal story is wrong, in the product's
    # favour and against the hoist's own defence.** `resolve()` runs IN THIS
    # PROCESS against the REAL environment; the snapshot roots are the
    # REDIRECTED `$HOME`/`$TMPDIR` handed to the child. Moving the call after
    # `before = snapshot(...)` would therefore make the spawn no more visible to
    # this row -- it would simply write into the OPERATOR'S OWN home inside a
    # window that cannot see it. What actually blinded C9/C10 to `ba07fdfb56`
    # was the POPULATION (`doctor` is not `is_mutating`), which is what
    # `DRY_RUN_PURITY` above fixes. Removing the hoist would have bought nothing
    # and cost a real-home write on every run of this suite.
    #
    # It costs nothing to keep, either: since PDF-20 routed the probe spawns
    # through `subprocess_util.probe_env()`, the probe writes nowhere at all.
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
        "OUT_DIR_BATCH",
        OUT_DIR_BATCH,
        "C21",
        1,
        "PDF-40's class. NECESSARY BUT NOT SUFFICIENT as an emptiness pin: C21's real "
        "guarantee is `out_dir_batch_verbs()`'s three-step derivation -- consumer set, "
        "operand arity, VERB name -- and in particular that a verb keyed on its module "
        "basename would enter as `office` rather than `convert`",
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
        "C11,C13,C15 (via PRODUCING)",
        1,
        "unpinned before PDF-17 despite B-032 claiming otherwise. NO LONGER FEEDS C9/C10: "
        "PDF-20 moved the two purity rows onto DRY_RUN_PURITY, because `doctor` -- which "
        "cannot be `is_mutating` and wrote `$HOME/.config` on every run -- was structurally "
        "outside the population that measured purity",
    ),
    Population(
        "DRY_RUN_PURITY",
        DRY_RUN_PURITY,
        "C9,C10",
        1,
        "zero makes both dry-run purity checks collect zero cases. NOT pinned at "
        "len(VERBS): a floor that fails when a verb is legitimately retired gets lowered "
        "rather than investigated (`DESTRUCTIVE`'s own argument). What keeps this honest is "
        "the identity assertion below, which fails if the population ever becomes a SUBSET "
        "of the verbs -- that narrowing is exactly how B-075 stayed invisible",
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
        "ENVELOPE_KEYS",
        ENVELOPE_KEYS,
        "test_every_verb_envelope_carries_dry_run",
        1,
        "PDF-20's own population, and it is in this roster for the same reason HONOURED_CELLS "
        "is: `test_every_population_is_rostered` FIRED ON IT during implementation, on the "
        "first full `make ci`. An empty tuple makes the envelope guard iterate no keys and "
        "report 26 green verbs having asserted nothing -- which is exactly how `doctor` came "
        "to be the one verb on neither of E3's two unenforced mechanisms",
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
    Population(
        "GROUP_GLOBAL_FLAG_CASES",
        GROUP_GLOBAL_FLAG_CASES,
        "C17",
        1,
        "PDF-25's own population, and the reason it is rostered rather than pinned inline: "
        "`discover_groups()` returned `()` for eight specs, so a row parametrized over "
        "GROUPS x GLOBAL_OPTIONS is one refactor from collecting zero cases and reporting "
        "green having asserted nothing -- which is what let all fifteen flags exit 2 with an "
        "empty stdout at `meta` without any harness noticing",
    ),
    Population(
        "OPERAND_VERBS",
        OPERAND_VERBS,
        "C18,C19,C20",
        1,
        "PDF-26's own population, and it is DERIVED here rather than read off "
        "`TAKES_INPUT_PATHS` because that predicate excludes `merge` -- the one verb the "
        "roadmap named. Zero would make C18 collect zero cases across all six output "
        "shapes at once; `test_ac13_the_operand_population_contains_merge_by_name` and "
        "`test_ac7_the_operand_population_matches_the_live_tree` are what keep it from "
        "silently NARROWING, which is the failure mode a floor of 1 cannot see",
    ),
    Population(
        "SINGLE_ARTIFACT_VERBS",
        SINGLE_ARTIFACT_VERBS,
        "AC9 (fails closed)",
        1,
        "PDF-26 §D7's partition, derived from the OR-3 declarations rather than named. "
        "Zero would make the fail-closed arm collect no cases -- and `merge`, the verb "
        "whose fail-closed semantics the spec explicitly preserves, is its first member",
    ),
    Population(
        "OUTPUT_REFUSING_VERBS",
        OUTPUT_REFUSING_VERBS,
        "AC10 arm (d)",
        1,
        "the OR-3 control that keeps §D4's readability change from being mistaken for a "
        "consumption change. Zero makes the arm vacuous, and the arm is the only thing "
        "asserting that dropping the veto did not also drop the refusal",
    ),
    Population(
        "UNREADABLE_SHAPES",
        UNREADABLE_SHAPES,
        "C18,C19,C20",
        1,
        "AC15's {table,json,ndjson} x {default,--quiet} matrix, built from the live "
        "`output_formats()` rather than a literal. Empty collapses C18 to zero cases "
        "even with a full OPERAND_VERBS -- a stacked parametrize is vacuous if EITHER "
        "dimension empties, and only one of the two was a population before this row. "
        "PDF-36 gave it two more consumers: emptying it now silently retires the "
        "traceback census AND the heap-address guard alongside C18",
    ),
    Population(
        "ENGINE_VISIBLE_SHAPES",
        ENGINE_VISIBLE_SHAPES,
        "C20",
        1,
        "PDF-36 AC4 -- the shapes whose envelope names its own `kind` and `code`, so a "
        "cell can PROVE it reached its engine before its message is used as evidence. "
        "Zero does not make C20 collect no cases; it makes C20 stop DISCRIMINATING, "
        "which is worse: the arm would still run, still pass, and no longer be able to "
        "tell an engine failure from a usage error. `E3`'s first census made exactly "
        "that mistake and reported one leaking verb where four leak",
    ),
    Population(
        "LEAKING_VERBS_AT_AE723BC",
        LEAKING_VERBS_AT_AE723BC,
        "C20 (positive control)",
        1,
        "PDF-36 AC4's positive control. Every assertion C20 makes is an ABSENCE, and an "
        "absence is exactly what a drive reports once it stops reaching the code under "
        "test -- three operand verbs already exit 0 on garbage bytes. Zero here retires "
        "the only arm that proves C20 can still SEE the defect it was built for, while "
        "leaving all 144 of its cells green",
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


# --------------------------------------------------------------------------- #
# PDF-20 — AC21 and AC23. Appended; nothing above is rewritten except C9's and
# C10's own parametrize lines and the `MUTATING` roster row's `checks` field,
# each of which is recorded where it happens.
#
# TWO INVARIANTS, ONE CAUSE. `doctor` was the only verb whose `-o json` envelope
# lacked `dry_run` (`d4ae996c52` / B-038) AND the only verb writing into `$HOME`
# on every run (`ba07fdfb56` / B-100). Neither was noticed, and in both cases the
# reason was the same: the thing that would have noticed enumerated a population
# that did not contain `doctor`. The two guards below both derive their
# population from `discover_verbs()`, so a verb added tomorrow joins each of them
# with zero author action.
# --------------------------------------------------------------------------- #


def test_the_purity_population_is_every_verb_not_a_subset_of_them() -> None:
    """AC21. `DRY_RUN_PURITY` may not silently narrow back to a subset.

    A `POPULATIONS` minimum of 1 keeps the rows from collecting zero cases; it
    does NOT stop the population from shrinking to one verb, which is the shape
    that actually happened -- C9/C10 ran 22 green cases for a whole cycle while
    the verb with the impurity sat outside them. Purity is claimed
    unconditionally (`CLAUDE.md` rule 2), so the population is asserted EQUAL to
    the verb roster rather than merely non-empty.
    """
    missing = sorted({verb.name for verb in VERBS} - {verb.name for verb in DRY_RUN_PURITY})
    assert missing == [], (
        f"verb(s) {missing} are outside the population C9/C10 measure. `--dry-run` purity is "
        "claimed for every verb without a condition; a narrower instrument makes the claim "
        "unmeasured for exactly the verbs it excludes (B-075's whole history)"
    )
    assert "doctor" in {verb.name for verb in DRY_RUN_PURITY}, (
        "`doctor` is the verb the two rows were blind to; if it leaves this population the "
        "instrument has gone blind again"
    )


def envelope_problems(verb_name: str, payload: object) -> list[str]:
    """Every way *payload* fails the `-o json` envelope contract.

    A pure function of the parsed payload, so the red proof below can drive it
    with a synthetic object rather than by mutating `src/`.
    """
    if not isinstance(payload, dict):
        return [f"{verb_name}: -o json did not produce a JSON object"]
    problems = [
        f"{verb_name}: -o json object has no {key!r} key"
        for key in ENVELOPE_KEYS
        if key not in payload
    ]
    if payload.get("schema_version") != 1:
        problems.append(f"{verb_name}: schema_version is {payload.get('schema_version')!r}, not 1")
    if "verb" in payload and payload["verb"] != verb_name:
        problems.append(f"{verb_name}: envelope names verb {payload['verb']!r}")
    if payload.get("dry_run") is not True:
        problems.append(
            f"{verb_name}: ran with --dry-run but the envelope reports "
            f"dry_run={payload.get('dry_run')!r} -- the key reports what the USER ASKED FOR"
        )
    return problems


def test_every_verb_envelope_carries_dry_run(corpus, tmp_path: Path) -> None:
    """AC23's derived guard. Population from `discover_verbs()`, never typed.

    Driven with `--dry-run` so the guard writes nothing and so the reported
    value can be asserted against a KNOWN request rather than against whatever
    the verb happened to do. Verbs whose dry run legitimately does not reach an
    envelope -- an engine-absent `convert` predicts exit 3 and renders the error
    shape (`PLAN.md` §5.6), which carries no `verb` -- are recorded by name and
    excluded, and the guard then refuses to be vacuous about it.
    """
    checked: list[str] = []
    non_envelope: list[str] = []
    problems: list[str] = []
    for verb in VERBS:
        args = INVOCATIONS[verb.name].build(corpus, tmp_path)
        result = run_cli(verb.name, "--dry-run", "-o", "json", *args, cwd=tmp_path)
        if result.returncode != 0:
            non_envelope.append(f"{verb.name}(exit {result.returncode})")
            continue
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            problems.append(f"{verb.name}: -o json emitted no parseable JSON")
            continue
        checked.append(verb.name)
        problems.extend(envelope_problems(verb.name, payload))
    assert problems == [], "\n".join(problems + [f"(excluded: {non_envelope})"])
    # Non-vacuity, and it is the half that matters: a guard that quietly
    # excluded its whole population would report green having asserted nothing.
    assert len(checked) >= len(VERBS) - len(non_envelope), "accounting lost a verb"
    for required in ("doctor", "info", "version"):
        assert required in checked, (
            f"{required} was not asserted (excluded: {non_envelope}) -- narrowing the "
            "population until it passes is the defect this guard exists to end"
        )


def test_the_envelope_guard_fires_on_a_missing_key() -> None:
    """AC23's red, driven against a SYNTHETIC payload rather than a mutated
    `src/` (`tests/test_acceptance_audit.py`'s idiom). The LIVE red -- deleting
    `dry_run` from `cmd_info.py`'s payload and watching the guard above name
    `info` -- was run by hand and is recorded in `tests/acceptance/
    audit_pdf_05.py`'s AC23 row."""
    good = {"schema_version": 1, "verb": "info", "dry_run": True}
    assert envelope_problems("info", good) == []
    assert envelope_problems("info", {k: v for k, v in good.items() if k != "dry_run"}) != []
    assert envelope_problems("info", {**good, "dry_run": None}) != []
    assert envelope_problems("info", {**good, "schema_version": 2}) != []
    assert envelope_problems("info", {**good, "verb": "doctor"}) != []
    assert envelope_problems("info", ["not", "an", "object"]) != []


# --------------------------------------------------------------------------- #
# C17 (PDF-25) -- a global flag at a grouping parent exits 2, at every group.
#
# APPENDED, never restructured: `PDF-17` rebuilt this harness in wave 1 and
# owns its shape; this spec adds ONE row and nothing else (`decision.md` §2's
# file-contention table).
#
# `C4` above already covers a bogus SUBCOMMAND at every grouping parent. What
# nothing covered is a VALID GLOBAL FLAG at one -- and `a472acde7a` is exactly
# that gap: all fifteen members of the block exited 2 at `meta` with **zero
# bytes on stdout**, in every shape. The exit code is the contract this row
# pins (`PLAN.md` §5.6's grouping-parent clause, unchanged by PDF-25); the
# ENVELOPE half lives in `tests/test_usage_envelope.py`, which owns the rest of
# that row's criteria.
#
# `PLAN.md:145` plans a second grouped subtree, which would have inherited the
# gap by design. This row picks it up the moment it exists.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("group_path", "flag"),
    GROUP_GLOBAL_FLAG_CASES,
    ids=[f"{' '.join(group)}-{flag}" for group, flag in GROUP_GLOBAL_FLAG_CASES],
)
def test_c17_a_global_flag_at_a_grouping_parent_exits_2(
    group_path: tuple[str, ...], flag: str
) -> None:
    result = run_cli(*group_path, flag)
    assert result.returncode == 2, (
        f"{' '.join(group_path)} {flag} -> {result.returncode}; a group does not take the "
        f"global block, and `PLAN.md` §5.6 rules that exit 2"
    )


# --------------------------------------------------------------------------- #
# C18 (PDF-26) -- an existing-but-unreadable OPERAND is a coded exit-1 failure,
# at every verb that takes one, under every output shape.
#
# APPENDED, never restructured: `PDF-17` owns this module's shape and `PDF-25`
# took `C17`; `C18` is the next free integer, taken by re-reading the file
# rather than from a spec (the spec was drafted against `2d19bcb`, before
# `C17` existed).
#
# WHAT THIS PINS, AND WHY THE POPULATION IS DERIVED HERE RATHER THAN REUSED.
# `TAKES_INPUT_PATHS` -- the population `C5` uses -- is derived from
# `registry.py::_takes_input_paths`, which asks "does this command declare an
# argument whose click type is named `path`". `merge`'s operand is a
# `StringParamType`, because the `path:range` grammar needs the raw string, so
# `merge` is ABSENT from `TAKES_INPUT_PATHS` (n=23). A `C18` modelled naively on
# `C5` would therefore have silently omitted the one verb the roadmap named, and
# would have reported green while the defect it exists to catch sat one verb
# outside its parametrization. So `C18` asks the question it actually means --
# "does this command declare a positional operand at all" -- and gets 24. The
# predicate itself is `PDF-17`'s to fix; this spec does not touch it.
#
# THE DEFECT, MEASURED AT `cdc02ee` BEFORE ANYTHING CHANGED. The mechanism was
# never in `ops/` at all: it was the FRAMEWORK's `Path` parameter type, whose
# `readable=True` default ran `os.access(R_OK)` during argv parsing, before any
# verb callback and before any of this product's code executed. 23 of the 24
# exited 2 with the framework's own "is not readable" refusal and the batch
# dead; `merge` exited 1 by printing a raw `PermissionError` traceback, which is
# `cli/main.py`'s UNHANDLED-CRASH 1 rather than the `FAILURE` classification.
# **No verb classified an unreadable operand correctly, `merge` included.**
#
# WHY THE ASSERTIONS ARE WHAT THEY ARE, AND NOT "STDOUT IS EMPTY". At `2d19bcb`
# the refusal printed zero bytes on stdout, and the spec's AC1 was written
# against that. `PDF-25` (wave 6) then routed every framework-level usage error
# through the structured envelope, so at `cdc02ee` the same refusal prints a
# well-formed 279-byte `{"kind": "usage", "code": 2, ...}` object naming "is not
# readable". An assertion about stdout EMPTINESS would therefore now be
# measuring PDF-25's fix rather than this one. What this row asserts instead is
# the CLASSIFICATION: exit 1, no framework refusal text, no traceback, and --
# under a structured shape -- an envelope carrying code 1 / kind "failure".
# --------------------------------------------------------------------------- #


_FRAMEWORK_REFUSAL = "is not readable"
_TRACEBACK = "Traceback (most recent call last)"


def _unreadable_copy(operand: Path, destination: Path) -> Path:
    """A mode-`000` copy of *operand* at *destination*.

    A COPY, never the fixture itself: the corpus is session-scoped and shared,
    and `chmod 000` on it would break every downstream test that reuses it
    (`registry.py::_copy_corpus_fixture`'s own hazard note). `copyfile` rather
    than `copy`, because `copy` would carry the source's mode over and then be
    overwritten anyway.
    """
    import shutil

    shutil.copyfile(operand, destination)
    destination.chmod(0o000)
    return destination


def _substitute_unreadable_operand(verb, args: list[str], tmp_path: Path) -> tuple[list[str], Path]:
    """*args* with its input operand replaced by an unreadable copy of itself.

    Every `INVOCATIONS` row places the input operand FIRST in its argv tail, so
    the substitution is generic. Anti-lapse (mirrors `C15`'s `_discover_target`
    `pytest.fail`, never a silent skip): a future row whose first element is not
    an existing file fails HERE, by name, rather than quietly dropping out of
    `C18`'s coverage -- and taking the fixture's "is a valid input for its verb"
    property with it.
    """
    if not args:
        pytest.fail(
            f"{verb.name}: its INVOCATIONS row builds an empty argv tail, so C18 has no "
            "operand to make unreadable -- an operand verb must name one"
        )
    operand = Path(args[0])
    if not operand.is_file():
        pytest.fail(
            f"{verb.name}: its INVOCATIONS row does not begin with an existing file "
            f"({args[0]!r}), so C18 cannot build a VALID-but-unreadable operand from it. "
            "Every row placed the operand first when this was written; a row that no "
            "longer does needs its own arm here, by name"
        )
    suffix = operand.suffix or ".bin"
    unreadable = _unreadable_copy(
        operand, tmp_path / f"c18-unreadable-{verb.name.replace(' ', '-')}{suffix}"
    )
    return [str(unreadable), *args[1:]], unreadable


def _skip_as_root() -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignores mode bits; a mode-000 operand is readable as root")


@pytest.mark.parametrize("verb", OPERAND_VERBS, ids=_ids(OPERAND_VERBS))
@pytest.mark.parametrize(
    ("fmt", "quiet"),
    UNREADABLE_SHAPES,
    ids=[f"{fmt}{'-quiet' if quiet else ''}" for fmt, quiet in UNREADABLE_SHAPES],
)
def test_c18_an_unreadable_operand_is_a_coded_failure(
    verb, fmt: str, quiet: bool, corpus, tmp_path: Path
) -> None:
    """AC6 + AC15: exit 1, no framework refusal, no traceback, under every shape.

    *Red at `cdc02ee`, before any code changed*: 23 verbs failed the exit
    assertion (2, carrying "is not readable"); `merge` failed the traceback
    assertion (1, carrying `PermissionError`).
    """
    _skip_as_root()
    _skip_unless_engine_available(INVOCATIONS.get(verb.name))

    args = INVOCATIONS[verb.name].build(corpus, tmp_path)
    args, unreadable = _substitute_unreadable_operand(verb, args, tmp_path)
    extra = ["--quiet"] if quiet else []
    try:
        result = run_cli(verb.name, *args, "-o", fmt, *extra, cwd=tmp_path)
    finally:
        unreadable.chmod(0o600)

    both = result.stdout + result.stderr
    detail = f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.returncode == 1, (
        f"{verb.name} -o {fmt}{' --quiet' if quiet else ''}: an operand that EXISTS and "
        f"cannot be READ is an operation that ran and failed (exit 1), never a bad "
        f"invocation (exit 2) and never a crash -- {detail}"
    )
    assert _TRACEBACK not in both, (
        f"{verb.name} -o {fmt}: a raw traceback reached the user. `cli/main.py` calls that "
        f"'a signal, not a UX' -- {detail}"
    )
    assert "PermissionError" not in both, (
        f"{verb.name} -o {fmt}: the engine's own exception name leaked -- {detail}"
    )
    assert _FRAMEWORK_REFUSAL not in both, (
        f"{verb.name} -o {fmt}: the FRAMEWORK's readability veto is still firing. The "
        f"click-level refusal had to GO, not be renumbered -- {detail}"
    )
    if fmt in {"json", "ndjson"}:
        assert '"code": 1' in result.stdout and '"kind": "failure"' in result.stdout, (
            f"{verb.name} -o {fmt}: exit 1 without a payload saying so. The per-item code "
            f"is the half of `PLAN.md` §5.6 a single integer cannot carry -- {detail}"
        )


@pytest.mark.parametrize("verb", OPERAND_VERBS, ids=_ids(OPERAND_VERBS))
def test_c18_dry_run_predicts_the_unreadable_operand_failure(verb, corpus, tmp_path: Path) -> None:
    """AC11 (OR-7): `dry.returncode == real.returncode == 1`, and the dry run
    leaves the tree byte-identical.

    **The VALUE is pinned, not the equality.** `dry == real` alone was GREEN
    before this spec -- 2 == 2 for the 23 framework refusals and 1 == 1 for
    `merge`'s crash -- so an assertion phrased that way could not have failed
    and must not be written (`C15` already pins its own values for exactly this
    reason).
    """
    _skip_as_root()
    _skip_unless_engine_available(INVOCATIONS.get(verb.name))

    args = INVOCATIONS[verb.name].build(corpus, tmp_path)
    args, unreadable = _substitute_unreadable_operand(verb, args, tmp_path)
    planned_out_dir = _named_out_dir(args)

    env, roots = redirected_environment(tmp_path)
    try:
        before = snapshot(*roots)
        dry = run_cli(verb.name, "--dry-run", *args, env=env, cwd=tmp_path)
        assert_unchanged(before, snapshot(*roots))
        real = run_cli(verb.name, *args, env=env, cwd=tmp_path)
    finally:
        unreadable.chmod(0o600)

    assert dry.returncode == real.returncode == 1, (
        f"{verb.name}: dry={dry.returncode} real={real.returncode} (expected both 1) -- "
        f"dry: {dry.stdout}{dry.stderr} / real: {real.stdout}{real.stderr}"
    )
    if planned_out_dir is not None:
        assert not planned_out_dir.exists(), (
            f"{verb.name}: --dry-run created {planned_out_dir} -- a preview that makes a "
            "directory has already written to the tree"
        )


def _named_out_dir(args: list[str]) -> Path | None:
    """The `--out-dir` value in *args*, or ``None`` when the row names none."""
    for index, token in enumerate(args):
        if token == "--out-dir" and index + 1 < len(args):
            return Path(args[index + 1])
    return None


def test_c18_the_dry_run_out_dir_clause_is_not_vacuous(corpus, tmp_path: Path) -> None:
    """AC11's `--out-dir` half is conditional, so something has to prove the
    condition is ever met. Without this, every member could name no `--out-dir`
    and the clause would report green having asserted nothing."""
    naming = [
        verb.name
        for verb in OPERAND_VERBS
        if _named_out_dir(INVOCATIONS[verb.name].build(corpus, tmp_path)) is not None
    ]
    assert naming, (
        "no member of OPERAND_VERBS names an --out-dir in its INVOCATIONS row, so AC11's "
        "'a non-existent --out-dir is not created' clause never executes"
    )


# --------------------------------------------------------------------------- #
# PDF-36 -- TWO LEDGER ROWS, AND THE LEDGER FORBIDS MERGING THEM.
#
# `6f5911ef9d`: `compress testdata/malformed.pdf` exited 1 with 0 B of stdout
# and 3644 B of raw traceback.  `5bd9143f61`: four verbs rendered a live heap
# address into the message a user reads.  `5bd9143f61`'s own row states why
# they cannot be one item -- *"fixing `6f5911ef9d` will likely create MORE of
# this by routing more engine exceptions into the envelope"* -- so fixing the
# first alone converts a traceback into a POLLUTED MESSAGE: a smaller defect,
# not a fixed one.
#
# The two arms are deliberately NON-SUBSTITUTABLE, and that is structural
# rather than a matter of prose:
#
#   ................  C19 (the traceback)      C20 (the heap address)
#   fixture           testdata/malformed.pdf   a garbage PDF built in-test
#   file fixed in     adapters/pikepdf_...py   errors.py, one chokepoint
#   observable        no traceback on stderr   no `0x[0-9a-f]{6,}` in the message
#
# Reverting either fix leaves the other arm GREEN. That is asserted by driving
# it in both directions, not by arguing it.
#
# NEITHER ARM IS WRITTEN ON THE EXIT CODE. It was 1 before both fixes and is 1
# after them, so an exit-code control is green BECAUSE OF the defect, on every
# cell -- `X-206` measured exactly that control passing on 10 of 11 verbs of a
# deliberately broken binary.
# --------------------------------------------------------------------------- #

#: `5bd9143f61`'s observable. SIX-plus LOWERCASE hex digits, which is narrow
#: enough to leave the repository's existing benign matches alone -- byte
#: literals (`0xC0`, `0x01`) are two digits or uppercase, and dimension strings
#: (`2550x3300`, `210x297mm`) are not `0x`-prefixed hex at all -- and wide
#: enough that no real CPython address escapes it.
_HEAP_ADDRESS = re.compile(r"0x[0-9a-f]{6,}")

#: Two lines of bytes that are not a PDF. Deliberately NOT the committed
#: `testdata/malformed.pdf`: that file is recoverable enough that `repair`
#: exits 0 on it, and `C20` needs every verb to fail *inside its engine*.
_GARBAGE_PDF = b"%PDF-1.7\nthis is not a pdf at all\n"


def _substitute_malformed_operand(
    verb, args: list[str], tmp_path: Path, payload: bytes, tag: str
) -> list[str]:
    """*args* with its input operand replaced by a READABLE but broken copy.

    The counterpart of `_substitute_unreadable_operand`, and deliberately its
    sibling rather than a parameter of it: `C18` measures a mode-`000` operand
    (the file system refuses) while these two measure a *readable* one whose
    CONTENT the engine refuses. Different seam, different failure, same argv
    surgery.

    The suffix is preserved for the same reason `C18` preserves it -- a verb
    that dispatches on extension should still take this path -- and the
    anti-lapse `pytest.fail` is copied rather than softened: a row that stops
    placing its operand first must fail HERE, by name, instead of quietly
    dropping out of coverage.
    """
    if not args:
        pytest.fail(
            f"{verb.name}: its INVOCATIONS row builds an empty argv tail, so there is no "
            "operand to make malformed -- an operand verb must name one"
        )
    operand = Path(args[0])
    if not operand.is_file():
        pytest.fail(
            f"{verb.name}: its INVOCATIONS row does not begin with an existing file "
            f"({args[0]!r}), so a VALID-but-malformed operand cannot be built from it"
        )
    suffix = operand.suffix or ".bin"
    broken = tmp_path / f"{tag}-{verb.name.replace(' ', '-')}{suffix}"
    broken.write_bytes(payload)
    return [str(broken), *args[1:]]


# C19 -- a READABLE but malformed operand never reaches the user as a
# traceback, over `OPERAND_VERBS x UNREADABLE_SHAPES`. `6f5911ef9d`.
@pytest.mark.parametrize("verb", OPERAND_VERBS, ids=_ids(OPERAND_VERBS))
@pytest.mark.parametrize(
    ("fmt", "quiet"),
    UNREADABLE_SHAPES,
    ids=[f"{fmt}{'-quiet' if quiet else ''}" for fmt, quiet in UNREADABLE_SHAPES],
)
def test_c19_a_malformed_operand_never_tracebacks(
    verb, fmt: str, quiet: bool, corpus, tmp_path: Path
) -> None:
    """AC3 -- PDF-36 half one, over the whole surface rather than one verb.

    *Red at `ae723bc`, before any code changed*: an equivalent 15-verb x
    3-shape drive against `testdata/malformed.pdf` was **3 of 45 cells red, all
    `compress`** -- `adapters/pikepdf_structure.py:178` re-opened its own saved
    output OUTSIDE the `try` its function closes three lines above, so
    libqpdf's `PdfError` escaped to `cli/main.py`'s bug path.

    **The fix is at the engine boundary and never at the terminal seam.**
    `cli/main.py:10-13` ships the policy that an unexpected exception prints a
    traceback and exits 1 -- *"a signal, not a UX"* -- and that policy is
    correct and stays. A `pikepdf.PdfError` from opening a malformed document
    is not a bug; it is the foreseeable failure of a documented capability.
    `tests/test_usage_envelope.py` pins the surviving bug signal.

    NO CELL SKIPS. A traceback is never an acceptable answer, whatever the
    verb's operand was going to be, so this arm needs no engine-reaching
    precondition -- unlike `C20`, which draws conclusions from a MESSAGE and
    therefore has to know the message came from an engine.
    """
    _skip_unless_engine_available(INVOCATIONS.get(verb.name))

    args = INVOCATIONS[verb.name].build(corpus, tmp_path)
    malformed = (Path(__file__).resolve().parents[1] / "testdata" / "malformed.pdf").read_bytes()
    args = _substitute_malformed_operand(verb, args, tmp_path, malformed, "c19")
    extra = ["--quiet"] if quiet else []

    result = run_cli(verb.name, *args, "-o", fmt, *extra, cwd=tmp_path)
    both = result.stdout + result.stderr

    assert _TRACEBACK not in both, (
        f"{verb.name} -o {fmt}{' --quiet' if quiet else ''}: a raw traceback reached the "
        f"user from a READABLE but malformed operand. That is `6f5911ef9d` -- an engine "
        f"exception escaping its adapter, not a bug in this tool. Belt it at the engine "
        f"boundary; a catch-all at `cli/main.py` would destroy the bug signal instead "
        f"(exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r})"
    )


def _error_envelopes(stdout: str) -> list[dict]:
    """Every error envelope in a structured payload, wherever it is carried.

    There are two carriers and a cell cannot know in advance which one it will
    get: the `_terminate()` envelope is top-level (`text`, `compress`), while a
    per-item verb nests one per document (`info -o json` puts it under
    `documents[]`, `info -o ndjson` puts it top-level beside `ok`). Reaching
    for `payload["error"]` measured only the first carrier and raised
    `KeyError` on the second -- a guard that crashes on a legitimate shape is
    not measuring that shape.

    Recursive rather than a two-case lookup so that a THIRD carrier, added by
    some later verb, is read rather than silently missed.
    """
    envelopes: list[dict] = []

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            candidate = node.get("error")
            if isinstance(candidate, dict) and "code" in candidate and "kind" in candidate:
                envelopes.append(candidate)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            _walk(json.loads(line))
        except json.JSONDecodeError:  # not a structured line; the caller asserts shape
            continue
    return envelopes


# C20 -- no rendered envelope message carries a live heap address, over
# `OPERAND_VERBS x UNREADABLE_SHAPES` against a garbage fixture. `5bd9143f61`.
@pytest.mark.parametrize("verb", OPERAND_VERBS, ids=_ids(OPERAND_VERBS))
@pytest.mark.parametrize(
    ("fmt", "quiet"),
    UNREADABLE_SHAPES,
    ids=[f"{fmt}{'-quiet' if quiet else ''}" for fmt, quiet in UNREADABLE_SHAPES],
)
def test_c20_no_rendered_message_carries_a_heap_address(
    verb, fmt: str, quiet: bool, corpus, tmp_path: Path
) -> None:
    """AC4 -- PDF-36 half two. A STANDING TEST, not a one-off observation.

    *Red at `ae723bc`*: an equivalent 16-verb x 3-shape drive against a garbage
    fixture was **12 of 48 cells red across FOUR verbs** -- `compress`,
    `repair`, `linearize` and `permissions`. **The ledger row names only two**
    (`compress` and `repair`), so the measured population is wider than the
    inherited one, which is why this is derived and driven rather than
    enumerated.

    Two sites in the same family (`encrypt`, `decrypt`) were never reached by
    any fixture and are UNPROVEN rather than clean. They are inside this
    guard's population by DERIVATION -- if either ever leaks, this reddens --
    which is the whole reason the fix went to one renderer-side chokepoint
    instead of to six adapter-local call sites that a seventh would undo.

    The four `pdfium` sites and `pypdf_structure.py`'s fourteen are likewise
    INSIDE this population and deliberately UNEDITED: covered by the guard,
    not by a point-fix pass.
    """
    _skip_unless_engine_available(INVOCATIONS.get(verb.name))

    args = INVOCATIONS[verb.name].build(corpus, tmp_path)
    args = _substitute_malformed_operand(verb, args, tmp_path, _GARBAGE_PDF, "c20")
    extra = ["--quiet"] if quiet else []

    result = run_cli(verb.name, *args, "-o", fmt, *extra, cwd=tmp_path)
    both = result.stdout + result.stderr
    detail = f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"

    # (1) THE CELL MUST HAVE REACHED ITS ENGINE, AND IT ASSERTS SO RATHER THAN
    #     SKIPPING. `E3`'s first census reported ONE leaking verb instead of
    #     four because its cells were USAGE errors: passing `--pages 1` to
    #     `compress` returns `{"kind": "usage", "code": 2}` and never opens the
    #     document at all. **A drive whose cells are usage errors measures the
    #     parser.** Exit 2 is therefore the one outcome this arm refuses.
    #
    #     Exit 0 is a DIFFERENT thing and is legitimate: `convert`, `compose`
    #     and `create` take a `.txt`/image operand, for which two lines of
    #     garbage are a perfectly VALID input. Those cells reached their engine
    #     and it accepted the bytes -- there is simply no error message to draw
    #     a conclusion from, and the address assertion below still applies to
    #     the success payload. They are classified here, never skipped: a skip
    #     would land in `scripts/assert_skips.py`'s unclassified remainder,
    #     and a skipped cell is not a pass.
    #
    #     Exit 2 is the outcome `E3` warns about and it is NOT assumed absent:
    #     `compose` returns `{"kind": "usage", "code": 2}` with *"this is a
    #     PDF, not an image; combining PDFs is what 'merge' does"*, because a
    #     `%PDF` magic number in an image slot is refused by the parser BY
    #     DESIGN. That is correct behaviour, not a defect, and it is CLASSIFIED
    #     here rather than exempted: a usage message must not carry a heap
    #     address either, so assertion (2) below still binds on it -- it simply
    #     cannot be used as evidence ABOUT AN ENGINE.
    #
    #     What is asserted is that the cell's classification is COHERENT: the
    #     exit code is one this tool documents, and the envelope's `kind`
    #     agrees with its `code`. A cell whose envelope disagreed with its exit
    #     status could not be reasoned about at all.
    assert result.returncode in (0, 1, 2), (
        f"{verb.name} -o {fmt}: exit {result.returncode} on a READABLE operand -- not a "
        f"documented outcome for one. Anything else is a crash wearing an exit code "
        f"-- {detail}"
    )
    if (fmt, quiet) in ENGINE_VISIBLE_SHAPES and result.returncode != 0:
        envelopes = _error_envelopes(result.stdout)
        assert envelopes, (
            f"{verb.name} -o {fmt}: exit {result.returncode} and NO error envelope "
            f"anywhere in the structured payload, so this cell reports a failure the "
            f"machine-readable output does not admit to -- {detail}"
        )
        assert result.returncode in {envelope["code"] for envelope in envelopes}, (
            f"{verb.name} -o {fmt}: the process exited {result.returncode} and no "
            f"envelope claims that code ({sorted({e['code'] for e in envelopes})}). "
            f"`PLAN.md` §5.6's per-item code is the half a single integer cannot carry, "
            f"and the two have to agree somewhere -- {detail}"
        )
        for envelope in envelopes:
            assert (envelope["kind"] == "failure") == (envelope["code"] == 1), (
                f"{verb.name} -o {fmt}: kind {envelope['kind']!r} does not agree with "
                f"code {envelope['code']}, so this cell cannot prove whether its message "
                f"came from an engine or from the argument parser -- {detail}"
            )

    # (2) ONLY THEN is the message it produced worth an assertion.
    leaked = _HEAP_ADDRESS.search(both)
    assert leaked is None, (
        f"{verb.name} -o {fmt}{' --quiet' if quiet else ''}: the message a user reads "
        f"carries a live heap address ({leaked.group(0) if leaked else ''}). It is "
        f"per-process noise -- it changes every run, so it cannot be quoted in the docs "
        f"under PDF-30's closure rule and cannot be diffed between two runs. "
        f"`adapters/pikepdf_structure.py:61-66` already wrote this argument for warnings "
        f"and never applied it to the error path -- {detail}"
    )


def test_c20_the_engine_visible_shapes_are_a_proper_subset(corpus, tmp_path: Path) -> None:
    """C20's engine-reaching clause is conditional, so something must prove
    the condition is both reachable AND not universal.

    Without this, `ENGINE_VISIBLE_SHAPES` could silently become empty (the
    `kind`/`code` assertion then never runs and `C20` degrades to the exit-code
    check alone) or become everything (the assertion then runs against
    `render_error_table`'s output, which carries neither field, and would fail
    for a reason that has nothing to do with either ledger row).
    """
    assert ENGINE_VISIBLE_SHAPES, (
        "ENGINE_VISIBLE_SHAPES is empty, so C20's `kind`/`code` clause never executes "
        "and the arm can no longer tell an engine failure from a usage error"
    )
    assert set(ENGINE_VISIBLE_SHAPES) < set(UNREADABLE_SHAPES), (
        "ENGINE_VISIBLE_SHAPES must be a PROPER subset of UNREADABLE_SHAPES -- the table "
        "renderer emits a bare `error: <message>` line and carries no `kind` or `code`"
    )
    assert all(fmt != "table" for fmt, _ in ENGINE_VISIBLE_SHAPES)


@pytest.mark.parametrize("name", LEAKING_VERBS_AT_AE723BC)
def test_c20_the_four_measured_verbs_still_reach_their_engine(
    name: str, corpus, tmp_path: Path
) -> None:
    """`C20`'s positive control: the arm must still be able to SEE the defect.

    Every assertion in `C20` is an absence -- no heap address -- and an absence
    is exactly what a drive reports when it stopped reaching the code under
    test. Three of `OPERAND_VERBS` legitimately exit 0 on garbage bytes
    (`convert`, `compose`, `create` take a `.txt`/image operand), and if the
    other twenty-one ever joined them, `C20` would pass on every cell while
    measuring nothing at all.

    So the four verbs the defect was MEASURED on are pinned by name: each must
    still fail *inside its engine* against a garbage PDF. If one legitimately
    stops doing so, this fails loudly and is re-derived deliberately -- which
    is the point, and is what `test_every_population_is_non_empty` does for the
    populations one level up.
    """
    verbs = {verb.name: verb for verb in OPERAND_VERBS}
    assert name in verbs, (
        f"{name} was an operand verb when PDF-36 measured this defect and is not one now. "
        f"Re-derive this control against the live tree rather than deleting the row"
    )
    _skip_unless_engine_available(INVOCATIONS.get(name))

    args = INVOCATIONS[name].build(corpus, tmp_path)
    args = _substitute_malformed_operand(verbs[name], args, tmp_path, _GARBAGE_PDF, "c20-control")
    result = run_cli(name, *args, "-o", "json", cwd=tmp_path)

    assert result.returncode == 1, (
        f"{name}: a garbage PDF no longer reaches a failing engine (exit "
        f"{result.returncode}), so C20's cells for this verb assert an absence over a "
        f"path that no longer runs -- {result.stdout!r} {result.stderr!r}"
    )
    payload = json.loads(result.stdout)["error"]
    assert payload["kind"] == "failure" and payload["code"] == 1
    assert payload["message"], f"{name}: an exit-1 envelope with an EMPTY message"


# --------------------------------------------------------------------------- #
# AC12 -- the declaration guard: the half of this fix that survives PDF-27..30.
#
# The regression signature is precise: the defect returns the moment a new verb
# declares a plain `Annotated[Path, typer.Argument(...)]` operand, because the
# framework's default for a `Path` annotation is `readable=True`. That is not a
# mistake a reviewer reliably catches -- it is the ABSENCE of a keyword. So the
# tree is walked and the census pinned at zero.
#
# THE PREDICATE IS TYPER'S, NOT CLICK'S, AND THAT IS LOAD-BEARING. `click` is
# not importable as a top-level module in this environment -- the framework
# vendors it as `typer._click` -- so a guard written against `click.Path` /
# `click.Argument` raises `AttributeError` or, worse, matches ZERO parameters
# and is VACUOUSLY GREEN. `test_the_readability_scan_sees_the_live_tree_at_all`
# below is what makes that failure mode impossible to reintroduce.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PathParam:
    """One path-typed parameter on the live tree."""

    verb: str
    spelling: str
    is_operand: bool
    vetoes_readability: bool

    def __str__(self) -> str:
        role = "operand" if self.is_operand else "option"
        return f"{self.verb}: {self.spelling} ({role})"


def path_parameters(root: object | None = None) -> tuple[PathParam, ...]:
    """Every path-typed parameter on *root*, with its readability veto recorded."""
    from pdf_toolkit.cli.main import app

    group = root if root is not None else typer.main.get_command(app)
    found: list[PathParam] = []

    def _walk(cmd: object, path: tuple[str, ...]) -> None:
        commands = getattr(cmd, "commands", None)
        if commands is not None:
            for name in sorted(commands):
                _walk(commands[name], (*path, name))
            return
        for param in getattr(cmd, "params", ()):
            if not isinstance(getattr(param, "type", None), typer.models.TyperPath):
                continue
            spellings = getattr(param, "opts", ()) or (getattr(param, "name", "?"),)
            found.append(
                PathParam(
                    verb=" ".join(path) or "<root>",
                    spelling="/".join(str(item) for item in spellings),
                    is_operand=isinstance(param, typer.core.TyperArgument),
                    vetoes_readability=bool(param.type.readable),
                )
            )

    _walk(group, ())
    return tuple(found)


def test_ac12_no_path_parameter_vetoes_readability_on_the_live_tree() -> None:
    """AC12. *Red at `cdc02ee` at 76/76* -- 23 operands, 26 `-O/--output`, 26
    `--out-dir` and `stamp --from`, every one of them `readable=True`."""
    offenders = [str(param) for param in path_parameters() if param.vetoes_readability]
    assert offenders == [], (
        "these path-typed parameters still let the CLI FRAMEWORK veto readability during "
        "argv parsing, which makes an existing-but-unreadable path exit 2 before any of "
        "this product's code runs:\n"
        + "\n".join(f"  - {item}" for item in offenders)
        + "\n\nDeclare an operand through `cli.common.operand_argument(...)`, and pass "
        "`readable=False` on a path-typed OPTION. Readability is a run-time property of a "
        "file, answered by `safety.paths.classify_operand` (exit 1), not a parse-time "
        "property of a command line (exit 2)."
    )


def test_ac12_the_operand_half_of_the_guard_is_not_vacuous() -> None:
    """The guard above is a superset of AC12's own wording ("no INPUT OPERAND
    parameter carries `readable=True`"), and a superset assertion over an empty
    scan is green for the worst possible reason. So the operand subset is
    pinned non-empty and named."""
    operands = [param for param in path_parameters() if param.is_operand]
    assert len(operands) >= 20, (
        f"the scan found only {len(operands)} path-typed OPERAND(s) on a tree that has 23 "
        "-- the predicate has stopped seeing operands, which would make AC12's guard pass "
        "having measured nothing"
    )
    assert [str(param) for param in operands if param.vetoes_readability] == []


def test_the_readability_scan_sees_the_live_tree_at_all() -> None:
    """The non-vacuity guard for the guard, and the one that catches THIS
    cycle's signature defect: a predicate written against `click.Path` matches
    zero parameters on a Typer tree and reports green."""
    found = path_parameters()
    assert len(found) >= 70, (
        f"the scan found {len(found)} path-typed parameter(s); the live tree carries 76 "
        "(23 operands + 26 -O/--output + 26 --out-dir + stamp --from), so the predicate "
        "itself has stopped matching"
    )
    verbs = {param.verb for param in found}
    assert "merge" in verbs and "info" in verbs, sorted(verbs)


def test_the_readability_guard_fires_on_a_planted_declaration() -> None:
    """AC12's red, automated: a synthetic app whose operand carries
    `readable=True` is reported BY NAME. Synthetic rather than an edit to a real
    verb for the same reason `test_the_roster_check_fires_on_an_unrostered_-
    population` is -- a red proof that vandalises the tree it proves is not a
    proof. The MANUAL plant/observe/revert against a real verb was also run
    once; see PDF-26's Implementation Log for the verbatim message."""
    # TWO commands, so the synthetic app is a GROUP and the walk has a verb name
    # to report -- AC12 requires the failure to NAME the offending verb, and a
    # single-command Typer app collapses to the root and would prove only that
    # something, somewhere, was found.
    planted = typer.Typer()

    @planted.command("guilty")
    def _guilty(
        operand: Annotated[Path, typer.Argument(metavar="PDF", readable=True)],
    ) -> None:  # pragma: no cover - never invoked; only its declaration is read
        del operand

    @planted.command("innocent")
    def _innocent(
        operand: Annotated[Path, typer.Argument(metavar="PDF", readable=False)],
    ) -> None:  # pragma: no cover - never invoked
        del operand

    scanned = path_parameters(typer.main.get_command(planted))
    assert {param.verb for param in scanned} == {"guilty", "innocent"}, scanned
    offenders = [str(param) for param in scanned if param.vetoes_readability]

    # Exactly the guilty verb, named -- and NOT the innocent one, which is what
    # makes this guard discriminating rather than always-red.
    assert offenders == ["guilty: operand (operand)"], offenders


# --------------------------------------------------------------------------- #
# AC7/AC13 -- the population is re-derived, cannot silently empty, and contains
# `merge` BY NAME. The membership assertion is explicit rather than trusted to
# the derivation, because the derivation is precisely what got this wrong once
# already (`TAKES_INPUT_PATHS` excludes `merge`, E5).
# --------------------------------------------------------------------------- #


def test_ac13_the_operand_population_contains_merge_by_name() -> None:
    names = {verb.name for verb in OPERAND_VERBS}
    assert names, "OPERAND_VERBS is empty -- C18 collects zero cases and reports green"
    assert "merge" in names, (
        "`merge` is absent from C18's population. It is the verb the roadmap named, and it "
        "is ABSENT from `TAKES_INPUT_PATHS` (its operand is a StringParamType, not a path) "
        "-- which is why this row derives its own population and asserts this by name"
    )
    assert "merge" not in {verb.name for verb in TAKES_INPUT_PATHS}, (
        "`merge` has joined TAKES_INPUT_PATHS, so the divergence this assertion documents "
        "is gone. That is `PDF-17`'s predicate fix landing; re-derive C18's population "
        "against it and consume the shared one rather than keeping two"
    )


def test_ac7_the_operand_population_matches_the_live_tree() -> None:
    """AC7: size and membership against the live walk at run time, never a
    literal. 24 at `cdc02ee`; the two verbs outside it are named because
    'accepts no operand' is the only admissible reason to be outside."""
    live = operand_verb_names()
    assert {verb.name for verb in OPERAND_VERBS} == live
    outside = {verb.name for verb in VERBS} - live
    assert outside == {"doctor", "version"}, (
        f"the verbs with no operand are {sorted(outside)}; at drafting they were "
        "{'doctor', 'version'}. A verb that has LOST its operand is a fact to record; a "
        "verb that has one and is not in C18's population is the defect this row exists for"
    )


# --------------------------------------------------------------------------- #
# AC9 (§D7) -- the single-combined-artifact class still FAILS CLOSED.
#
# Classification is uniform across all 24 operand verbs. CONTINUATION is not,
# and the difference is the SHAPE OF THE OUTPUT rather than the verb's name --
# which is why the population above is derived from the OR-3 declarations.
#
# The roadmap's deliverable sentence ("the other inputs are still processed ...
# uniformly across info/rasterize/compose/merge") conflates the two. It is
# followed here for classification and DELIBERATELY NOT followed for
# continuation.
#
# THE LOAD-BEARING HALF OF THIS ROW IS THE TRACEBACK CLAUSE, not the exit code.
# `merge` ALREADY exited 1 at `cdc02ee` -- by printing a raw `PermissionError`
# traceback, which is `cli/main.py`'s unhandled-crash 1 rather than the FAILURE
# classification. An arm asserting only the exit code would have been green on
# the shipped defect, which is precisely what made B-057 ("merge already does
# it") wrong.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", SINGLE_ARTIFACT_VERBS, ids=_ids(SINGLE_ARTIFACT_VERBS))
def test_ac9_the_single_artifact_class_fails_closed_without_a_traceback(
    verb, corpus, tmp_path: Path
) -> None:
    _skip_as_root()
    _skip_unless_engine_available(INVOCATIONS.get(verb.name))

    args = INVOCATIONS[verb.name].build(corpus, tmp_path)
    target = _discover_target(verb, args, tmp_path)
    args, unreadable = _substitute_unreadable_operand(verb, args, tmp_path)
    assert not target.exists(), f"{verb.name}: the planned target pre-exists; arm is invalid"

    try:
        result = run_cli(verb.name, *args, "-o", "json", cwd=tmp_path)
    finally:
        unreadable.chmod(0o600)

    both = result.stdout + result.stderr
    detail = f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.returncode == 1, detail
    assert not target.exists(), (
        f"{verb.name}: {target} was written despite an unreadable input. A partially "
        "assembled artifact is a wrong answer that looks right"
    )
    assert "Traceback (most recent call last)" not in both, (
        f"{verb.name}: exit 1 by CRASHING is not exit 1 by CLASSIFYING -- {detail}"
    )
    assert "PermissionError" not in both, detail
    assert '"code": 1' in result.stdout and '"kind": "failure"' in result.stdout, detail


def test_ac9_the_partition_names_both_verbs_the_spec_calls_out() -> None:
    """§D7 names `merge` and `compose` as the single-artifact class. The
    population is DERIVED, so this asserts the derivation agrees with the
    spec rather than replacing it with a list."""
    names = {verb.name for verb in SINGLE_ARTIFACT_VERBS}
    assert {"merge", "compose"} <= names, sorted(names)
    assert names.isdisjoint({verb.name for verb in OUTPUT_REFUSING_VERBS})


# --------------------------------------------------------------------------- #
# AC10 -- the `-O` masking pair, with its precedence proof (E4).
#
# THE DEFECT WAS MORE SEVERE THAN THE ITEM IT RODE IN ON. `-O/--output` also
# carried `readable=True`, and readability of a WRITE TARGET is semantically
# irrelevant -- but the veto fired BEFORE the safety spine, so an existing
# output target with mode 000 answered **2** where mode 644 answered **5**.
# A safety refusal reported as a typo, and unreachable by ANY flag combination:
# adding `-f` was still 2.
#
# ARM (c) IS THE PRECEDENCE PROOF, and the spec is explicit that a **5** there
# FAILS this criterion: on POSIX, replacing a file is a DIRECTORY permission, so
# a `-f` run over an unreadable target must SUCCEED. An implementation that
# answered 5 would be predicting a refusal the real run never reaches -- the
# check landed at the wrong tier -- and only a pair that distinguishes the right
# answer from a plausible wrong one can tell those apart.
# --------------------------------------------------------------------------- #

_SEED = b"AC10-SEEDED-BYTES"


@pytest.mark.parametrize("verb", OUTPUT_CONSUMING_MUTATING, ids=_ids(OUTPUT_CONSUMING_MUTATING))
def test_ac10_an_unreadable_output_target_reaches_the_safety_spine(
    verb, corpus, tmp_path: Path
) -> None:
    """Arms (a) and (b): the answer must not depend on the target's mode.

    *Red at `cdc02ee`*: (a) 5, (b) **2**.
    """
    _skip_as_root()
    invocation = INVOCATIONS[verb.name]
    args = invocation.build(corpus, tmp_path)
    target = _discover_target(verb, args, tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    codes: dict[int, int] = {}
    for mode in (0o644, 0o000):
        if target.exists():
            target.chmod(0o600)
        target.write_bytes(_SEED)
        target.chmod(mode)
        try:
            codes[mode] = run_cli(verb.name, *args, cwd=tmp_path).returncode
        finally:
            target.chmod(0o600)

    assert codes[0o644] == codes[0o000] == 5, (
        f"{verb.name}: an occupied target answered {codes[0o644]} at mode 644 and "
        f"{codes[0o000]} at mode 000. The two must be the same refusal -- a 2 at mode 000 "
        "is a SAFETY GATE degraded to a usage error by a readability veto that fired "
        "before the spine"
    )
    assert target.read_bytes() == _SEED, f"{verb.name}: a refused run still wrote the target"


@pytest.mark.parametrize("verb", OUTPUT_CONSUMING_MUTATING, ids=_ids(OUTPUT_CONSUMING_MUTATING))
def test_ac10_force_over_an_unreadable_target_succeeds(verb, corpus, tmp_path: Path) -> None:
    """Arm (c), the precedence proof. **A 5 here FAILS this criterion.**

    *Red at `cdc02ee`*: 2.
    """
    _skip_as_root()
    invocation = INVOCATIONS[verb.name]
    args = invocation.build(corpus, tmp_path)
    target = _discover_target(verb, args, tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_SEED)
    target.chmod(0o000)

    try:
        result = run_cli(verb.name, *args, "-f", cwd=tmp_path)
    finally:
        if target.exists():
            target.chmod(0o600)

    detail = f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.returncode == 0, (
        f"{verb.name}: `-f` over an existing mode-000 target must SUCCEED -- on POSIX, "
        f"replacing a file is a DIRECTORY permission. A 5 here means the check landed at "
        f"a tier the real run does not reach; a 2 means the framework's veto is still "
        f"firing -- {detail}"
    )
    written = target.read_bytes()
    assert written and written != _SEED, (
        f"{verb.name}: exit 0 but the target still holds the seeded bytes -- the run "
        "reported success without replacing anything"
    )


@pytest.mark.parametrize("verb", OUTPUT_REFUSING_VERBS, ids=_ids(OUTPUT_REFUSING_VERBS))
def test_ac10_or3_still_refuses_output_at_a_verb_that_does_not_consume_it(
    verb, corpus, tmp_path: Path
) -> None:
    """Arm (d): §D4 changed the READABILITY VETO on `-O`, not OR-3's consumption
    semantics. Unchanged at `cdc02ee` and unchanged after -- which is the point:
    without this arm the two mechanisms could be confused, and a fix that
    silently made `-O` universally accepted would look like a success."""
    args = INVOCATIONS[verb.name].build(corpus, tmp_path)
    result = run_cli(verb.name, *args, "-O", str(tmp_path / "or3-not-consumed.out"), cwd=tmp_path)
    assert result.returncode == 2, (
        f"{verb.name} does not consume --output, so -O is a usage error (OR-3) -- "
        f"exit={result.returncode} {result.stdout}{result.stderr}"
    )
    assert not (tmp_path / "or3-not-consumed.out").exists()


# C21 -- a `--out-dir` batch payload never denies an artifact that is on disk,
# over the DERIVED `OUT_DIR_BATCH` population. `345a73e0e2`.
@pytest.mark.parametrize("verb", OUT_DIR_BATCH)
def test_c21_out_dir_batch_payload_agrees_with_the_filesystem(verb: str, tmp_path: Path) -> None:
    """PDF-40 -- the payload and the filesystem stop disagreeing.

    *Red at `e72f7fe`, before any code changed*: driven over all ten verbs with a
    corrupt input in position 2, EVERY one emitted `{"schema_version": 1,
    "error": {..., "path": null}}` -- **no collection key at all** -- while
    `compress` and `convert` left an artifact on disk. So the input that
    SUCCEEDED was unreported, the input that FAILED was unnamed, and the batch
    aborted, contradicting `PLAN.md` §5.4's Failure policy on a surface
    `README.md` declares public API.

    **The bad input is in the MIDDLE.** A first-position failure cannot
    distinguish *abort* from *continue*, so a position-1 row would be unfailable
    for the property this row exists to pin.

    **The filesystem listing is taken independently**, by `os.walk` in the
    harness, never from the tool's own stdout: a payload can be internally
    perfect -- right count, right names, right order, right codes -- and still be
    a lie. This row therefore checks BOTH directions, because running only "every
    item names a real file" reproduces the blind spot that let the defect ship
    (the pre-fix payload had no items at all, and so satisfied it trivially).

    The per-verb detail, both failure kinds, ordering under `--threads`, the
    run/item boundary and the `--dry-run` mirror live in
    `tests/test_batch_continuation.py`; this row is the anti-regression sweep, so
    a verb that loses its continuation reddens HERE, naming itself, without
    anyone writing a per-verb assertion.
    """
    from test_batch_continuation import (
        _build_batch,
        _collection,
        _drive,
        _skip_unless_engine_available,
        _walk,
    )

    _skip_unless_engine_available(verb)
    restore: list[Path] = []
    operands = _build_batch(tmp_path, "corrupt", restore)
    out_dir = tmp_path / "out"
    exit_code, payload, _ = _drive(verb, operands, out_dir)

    key, rows = _collection(payload)
    assert [row["input"] for row in rows] == [str(p) for p in operands], (
        f"{verb}: payload['{key}'] must name every operand exactly once, in input order"
    )
    on_disk = _walk(out_dir)
    claimed = [row["output"] for row in rows if row["ok"] and row["output"]]
    for artifact in on_disk:
        assert sum(1 for c in claimed if Path(c) == artifact) == 1, (
            f"{verb}: {artifact} is on disk but no single ok item names it"
        )
    for candidate in claimed:
        assert Path(candidate).exists(), f"{verb}: item names {candidate!r}, not on disk"
    failed = [row for row in rows if not row["ok"]]
    assert len(failed) == 1 and failed[0]["input"] == str(operands[1])
    assert failed[0]["exit_code"] != 0 and failed[0]["message"]
    assert exit_code == 1, f"{verb}: expected exit 1, got {exit_code}"


def test_c21_population_is_non_empty() -> None:
    """C21 cannot pass by iterating over nothing.

    This product has already shipped a silently empty parametrize set, which is
    why every derived population carries this pin rather than trusting the
    derivation to stay non-empty on its own.
    """
    assert OUT_DIR_BATCH, "the --out-dir batch population derived empty; C21 collected zero cases"
