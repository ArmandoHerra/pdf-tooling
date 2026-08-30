"""OR-3 (`decision.md` §0.5, Design §D12) — the declaration is mandatory and
typo-proof (AC26). Built as a unit test against throwaway commands, per the
spec, rather than by inspection.
"""

from __future__ import annotations

import typer

from pdf_toolkit.cli.common import OUTPUT_FLAGS, consumed_output_flags, global_options


def test_output_flags_is_exactly_the_governed_four() -> None:
    assert OUTPUT_FLAGS == ("--output", "--out-dir", "--name", "--in-place")


def test_a_bare_global_options_raises_type_error_at_decoration_time() -> None:
    def throwaway(ctx: typer.Context) -> None:  # pragma: no cover - never called
        pass

    try:
        global_options(throwaway)  # type: ignore[operator]
    except TypeError:
        pass
    else:  # pragma: no cover - documents the contract
        raise AssertionError("expected a bare @global_options to raise TypeError")


def test_an_unknown_consumes_flag_raises_value_error_at_decoration_time() -> None:
    try:
        global_options(consumes=("--bogus",))
    except ValueError as error:
        assert "--bogus" in str(error)
    else:  # pragma: no cover - documents the contract
        raise AssertionError("expected an unknown flag to raise ValueError")


def test_a_valid_declaration_decorates_a_throwaway_command_cleanly() -> None:
    @global_options(consumes=("--output",))
    def throwaway(ctx: typer.Context) -> None:  # pragma: no cover - never invoked
        pass

    assert consumed_output_flags(throwaway.__module__) == ("--output",)


def test_the_five_landed_verbs_declare_their_documented_consumes_sets() -> None:
    from pdf_toolkit.cli import cmd_doctor, cmd_info, cmd_merge, cmd_split, cmd_version

    assert consumed_output_flags(cmd_version.version_command.__module__) == ()
    assert consumed_output_flags(cmd_doctor.doctor_command.__module__) == ()
    assert consumed_output_flags(cmd_info.info_command.__module__) == ()
    assert consumed_output_flags(cmd_merge.merge_command.__module__) == ("--output",)
    assert consumed_output_flags(cmd_split.split_command.__module__) == (
        "--out-dir",
        "--name",
    )
