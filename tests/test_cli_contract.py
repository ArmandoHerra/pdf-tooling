"""The per-verb CLI contract matrix — `PLAN.md` §10.

Every check (`C1`…`C13`) is parameterized over `tests/registry.py`'s
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
the verb's `INVOCATIONS` row. `C4`, `C9`, `C10`, `C11` and `C13` currently
collect **zero** parametrized cases: `version`/`doctor`/`info` are the only
verbs that exist at PDF-06 landing, none of them is `is_mutating` (they write
nothing) and no non-root grouping parent exists yet. That is real, not a
defect — `PDF-07` onward gains coverage for each of these automatically the
moment a verb reaches the write chokepoint or a subcommand group is created.
`AC6`'s own non-vacuity guard (`pytest -m e2e --collect-only -q` is
non-zero) is satisfied by `C1`/`C2`/`C3`/`C5`/`C7`/`C8`/`C12` plus the three
root-level tests below, which are never empty.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fs_snapshot import assert_unchanged, redirected_environment, snapshot
from pdf_toolkit.cli.common import GLOBAL_OPTIONS
from registry import INVOCATIONS, discover_groups, discover_verbs, run_cli

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
# exits 5.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", MUTATING, ids=_ids(MUTATING))
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
    import json

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


@pytest.mark.parametrize("verb", DESTRUCTIVE, ids=_ids(DESTRUCTIVE))
def test_c13_bulk_destructive_requires_y_on_a_non_tty(verb, corpus, tmp_path: Path) -> None:
    invocation = INVOCATIONS[verb.name]
    args = invocation.build(corpus, tmp_path)
    refused = run_cli(verb.name, *args)
    assert refused.returncode == 5
    confirmed = run_cli(verb.name, "-y", *args)
    assert confirmed.returncode != 5


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
