"""PDF-14 -- the `meta` grouping parent, OR-3's four declarations (D8.2), and
the mechanized "names its port" clause (AC27, open ledger row `0615feae63`).

`meta` is the CLI's first (and, as of this spec, only) grouping parent, so
this module is the first place any of the three checks below has ever had
something to run against.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import discover_verbs, run_cli  # noqa: E402

# --------------------------------------------------------------------------- #
# AC1 -- `meta` with no subcommand exits 2 (the bogus-subcommand half is
# already covered generically by `test_cli_contract.py::
# test_c4_bogus_subcommand_on_a_group_exits_2`, parametrized over
# `discover_groups()` -- unedited by this spec).
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
def test_ac1_meta_with_no_subcommand_exits_2() -> None:
    result = run_cli("meta")
    assert result.returncode == 2


@pytest.mark.e2e
@pytest.mark.parametrize("verb", ["meta get", "meta set", "watermark", "stamp"])
def test_ac1_help_exits_0_and_is_non_empty(verb: str) -> None:
    result = run_cli(*verb.split(), "--help")
    assert result.returncode == 0
    assert result.stdout.strip()


# --------------------------------------------------------------------------- #
# AC22 -- OR-3, one declaration per module (`decision.md` §0.5 OR-3).
# Mechanized behaviourally, not by grepping source (Design D8.1/D8.2).
# --------------------------------------------------------------------------- #


def test_ac22_or3_declarations_match_d82_exactly() -> None:
    from pdf_toolkit.cli.common import consumed_output_flags

    expected = {
        "pdf_toolkit.cli.cmd_meta_get": (),
        "pdf_toolkit.cli.cmd_meta_set": ("--output", "--in-place"),
        "pdf_toolkit.cli.cmd_watermark": ("--output", "--in-place"),
        "pdf_toolkit.cli.cmd_stamp": ("--output", "--in-place"),
        "pdf_toolkit.cli.cmd_meta": (),
    }
    for module, want in expected.items():
        got = consumed_output_flags(module)
        assert got == want, (module, got, want)


def test_ac22_every_meta_leaf_has_its_own_distinct_callback_module() -> None:
    meta_leaves = [verb for verb in discover_verbs() if verb.path[:1] == ("meta",)]
    assert len(meta_leaves) == 2  # get, set
    modules = set()
    for verb in meta_leaves:
        # `VerbSpec` does not carry the module directly; re-derive it the
        # SAME way `discover_verbs()` itself does, off the live command.
        import typer

        from pdf_toolkit.cli.main import app

        command = typer.main.get_command(app)
        node = command
        for name in verb.path:
            node = node.commands[name]
        callback = node.callback
        original = getattr(callback, "__wrapped__", callback)
        modules.add(original.__module__)
    assert len(modules) == len(meta_leaves), f"meta leaves share a module: {modules}"


# --------------------------------------------------------------------------- #
# AC27 -- the "names its port" clause has a test (open ledger row
# `0615feae63`): `--help` names the engine port each verb depends on.
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("verb", "ports"),
    [
        ("meta get", ("StructureEngine",)),
        ("meta set", ("StructureEngine",)),
        ("watermark", ("ComposeEngine", "StructureEngine")),
        ("stamp", ("StructureEngine",)),
    ],
    ids=lambda value: value if isinstance(value, str) else "+".join(value),
)
def test_ac27_help_names_its_engine_port(verb: str, ports: tuple[str, ...]) -> None:
    result = run_cli(*verb.split(), "--help")
    assert result.returncode == 0
    for port in ports:
        assert port in result.stdout, f"{verb} --help does not name {port}"
