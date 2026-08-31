"""The confirmation gate — including the two negatives that keep it usable.

The gate is only a safety feature if it fires when it should *and does not fire
when it should not*. A gate that stops a single-file run, or a create-only batch
however large, is a gate people disable with a ``-y`` in their shell profile, and
after that it protects nobody. So the "never refuses" cases are asserted as
carefully as the refusal.

"Must not hang" is tested, not hoped for. The non-terminal arms run with stdin
bound to a pipe **the parent never writes to and never closes**, under a hard
timeout: if the gate ever reached for stdin on a non-terminal, the child would
block forever and the deadline would turn the test red. That is the difference
between a refusal and an outage in somebody's pipeline, and it is not something
prose can assert.

The terminal arms use a real ``pty``. ``policy.is_tty`` is data, so it would have
been easy to fake — and faking it would have proven that the branch exists, not
that the prompt works on a terminal.
"""

from __future__ import annotations

import os
import pty
import shlex
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from pdf_toolkit import errors
from pdf_toolkit.cli.exit_codes import OK, REFUSED
from pdf_toolkit.cli.main import build_rerun_hint
from pdf_toolkit.safety import SafetyPolicy, require_confirmation

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from atomic_harness import REPO_ROOT, run_harness  # noqa: E402

HINT = "pdftoolkit delete a.pdf b.pdf --in-place -y"


def make_policy(**overrides: object) -> SafetyPolicy:
    values: dict[str, object] = {
        "dry_run": False,
        "force": False,
        "in_place": False,
        "backup": True,
        "assume_yes": False,
        "is_tty": False,
        "threads": 1,
    }
    values.update(overrides)
    return SafetyPolicy(**values)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# The decision table, in process
# --------------------------------------------------------------------------- #


def test_a_bulk_destructive_run_on_a_non_terminal_is_refused() -> None:
    with pytest.raises(errors.ConfirmationRequiredError) as caught:
        require_confirmation(
            make_policy(is_tty=False),
            input_count=3,
            in_place=True,
            rerun_hint=HINT,
        )
    assert caught.value.exit_code == REFUSED
    assert "3 inputs" in caught.value.message
    assert caught.value.message.rstrip().endswith(HINT)


def test_clobbering_several_outputs_counts_as_destructive() -> None:
    with pytest.raises(errors.ConfirmationRequiredError):
        require_confirmation(
            make_policy(),
            input_count=2,
            clobbered=("a.pdf", "b.pdf"),
            rerun_hint=HINT,
        )


@pytest.mark.parametrize(
    ("label", "kwargs", "policy_kwargs"),
    [
        ("single input, in place", {"input_count": 1, "in_place": True}, {}),
        ("single input, clobbering", {"input_count": 1, "clobbered": ("a.pdf",)}, {}),
        ("bulk but create-only", {"input_count": 500}, {}),
        ("bulk destructive with -y", {"input_count": 9, "in_place": True}, {"assume_yes": True}),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_the_gate_stays_out_of_the_way(
    label: str,
    kwargs: dict[str, object],
    policy_kwargs: dict[str, object],
) -> None:
    """The negatives. A gate that fires too often is a gate people route around."""
    require_confirmation(make_policy(**policy_kwargs), rerun_hint=HINT, **kwargs)  # type: ignore[arg-type]


def test_a_terminal_prompt_defaults_to_no() -> None:
    stream = StringIO()
    with pytest.raises(errors.ConfirmationDeclinedError) as caught:
        require_confirmation(
            make_policy(is_tty=True),
            input_count=4,
            in_place=True,
            rerun_hint=HINT,
            stream=stream,
            reader=StringIO("\n"),
        )
    assert caught.value.exit_code == REFUSED
    assert "[y/N]" in stream.getvalue()


@pytest.mark.parametrize("answer", ["y\n", "Y\n", "yes\n", "YES\n"])
def test_an_affirmative_answer_proceeds(answer: str) -> None:
    require_confirmation(
        make_policy(is_tty=True),
        input_count=4,
        in_place=True,
        rerun_hint=HINT,
        stream=StringIO(),
        reader=StringIO(answer),
    )


@pytest.mark.parametrize("answer", ["n\n", "no\n", "\n", "maybe\n", ""])
def test_anything_else_declines(answer: str) -> None:
    with pytest.raises(errors.ConfirmationDeclinedError):
        require_confirmation(
            make_policy(is_tty=True),
            input_count=4,
            in_place=True,
            rerun_hint=HINT,
            stream=StringIO(),
            reader=StringIO(answer),
        )


# --------------------------------------------------------------------------- #
# The re-run hint
# --------------------------------------------------------------------------- #


def test_the_hint_quotes_paths_that_contain_spaces() -> None:
    hint = build_rerun_hint(["pdftoolkit", "delete", "my documents/a.pdf"])
    assert hint.endswith(" -y")
    assert shlex.split(hint) == ["pdftoolkit", "delete", "my documents/a.pdf", "-y"]


def test_the_hint_defaults_to_the_running_command() -> None:
    assert build_rerun_hint().endswith(" -y")


# --------------------------------------------------------------------------- #
# Through a real process: the non-terminal posture (AC14 i, ii, iii, vi)
# --------------------------------------------------------------------------- #


def _never_written_stdin() -> tuple[int, int]:
    """A pipe the parent holds open and never writes: reading it blocks forever."""
    return os.pipe()


def test_a_non_terminal_refusal_is_immediate_and_never_blocks() -> None:
    read_end, write_end = _never_written_stdin()
    try:
        result = run_harness(
            ["confirm", "--inputs", "3", "--in-place"],
            stdin=read_end,
            timeout=10.0,
        )
    finally:
        os.close(read_end)
        os.close(write_end)
    assert result.returncode == REFUSED, result.stderr
    assert "stdin is not a terminal" in result.stderr


def test_the_refusal_prints_a_command_that_actually_works() -> None:
    """AC14 (ii). Copy-pasteable is checked by pasting it, not by reading it."""
    read_end, write_end = _never_written_stdin()
    try:
        refusal = run_harness(
            ["confirm", "--inputs", "3", "--in-place"],
            stdin=read_end,
            timeout=10.0,
        )
    finally:
        os.close(read_end)
        os.close(write_end)
    assert refusal.returncode == REFUSED

    hint = refusal.stderr.strip().splitlines()[-1].strip()
    assert hint.endswith(" -y")

    replay = subprocess.run(  # noqa: S603 - the command under test, built by the tool
        shlex.split(hint),
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert replay.returncode == OK, replay.stderr


def test_the_same_run_with_yes_proceeds() -> None:
    result = run_harness(["confirm", "--inputs", "3", "--in-place", "-y"], timeout=10.0)
    assert result.returncode == OK, result.stderr


def test_a_single_input_destructive_run_never_refuses_on_this_ground() -> None:
    result = run_harness(["confirm", "--inputs", "1", "--in-place"], timeout=10.0)
    assert result.returncode == OK, result.stderr


def test_the_json_refusal_is_the_error_object_on_stdout() -> None:
    import json

    read_end, write_end = _never_written_stdin()
    try:
        result = run_harness(
            ["-o", "json", "confirm", "--inputs", "3", "--in-place"],
            stdin=read_end,
            timeout=10.0,
        )
    finally:
        os.close(read_end)
        os.close(write_end)
    assert result.returncode == REFUSED
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == REFUSED
    assert payload["error"]["kind"] == "refused"


# --------------------------------------------------------------------------- #
# Through a real terminal (AC14 v)
# --------------------------------------------------------------------------- #


def _answer_on_a_pty(answer: str) -> subprocess.CompletedProcess[str]:
    controller, follower = pty.openpty()
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", "tests.atomic_harness", "confirm", "--inputs", "3", "--in-place"],
        cwd=str(REPO_ROOT),
        stdin=follower,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    os.close(follower)
    try:
        os.write(controller, answer.encode())
        stdout, stderr = process.communicate(timeout=20)
    finally:
        os.close(controller)
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def test_declining_on_a_real_terminal_exits_5() -> None:
    result = _answer_on_a_pty("n\n")
    assert result.returncode == REFUSED, result.stderr
    assert "[y/N]" in result.stderr


def test_accepting_on_a_real_terminal_proceeds() -> None:
    result = _answer_on_a_pty("y\n")
    assert result.returncode == OK, result.stderr


# --------------------------------------------------------------------------- #
# B-093 -- under `--dry-run` the gate PREDICTS and never prompts (OR-7).
#
# PDF-15 §D12.2 lists "bulk-destructive, non-TTY, no -y" as KNOWABLE at plan
# time, so a dry run must exit the 5 the real run exits. Until B-093 the rule
# could not even be expressed here: all fifteen CLI call sites guarded this
# function with `if not config.dry_run and ...`, so `dry_run` never reached it
# and every arm below would have been vacuous. The rule now lives in this one
# shared check, which is why these are unit arms and not fifteen CLI probes.
#
# The TTY arm is the carve-out, and it is the one that needs a real instrument:
# "does not prompt" is only proven by a reader that would FAIL if it were read.
# --------------------------------------------------------------------------- #


class _ExplodingReader:
    """A stdin stand-in that fails the test if anything reads it.

    `--dry-run` purity (CLAUDE.md rule 2) is about more than not writing: a
    preview that blocks on an answer is the outage the non-TTY branch exists to
    prevent. A `StringIO` would let a regression pass silently.
    """

    def readline(self) -> str:  # pragma: no cover - reaching it IS the failure
        raise AssertionError("--dry-run read stdin at the confirmation gate")


def test_a_dry_run_predicts_the_non_terminal_refusal() -> None:
    """OR-7 / D12.2 -- dry == real == 5, with the identical payload."""
    with pytest.raises(errors.ConfirmationRequiredError) as dry:
        require_confirmation(
            make_policy(dry_run=True, is_tty=False),
            input_count=2,
            in_place=True,
            rerun_hint=HINT,
            reader=_ExplodingReader(),  # type: ignore[arg-type]
        )
    with pytest.raises(errors.ConfirmationRequiredError) as real:
        require_confirmation(
            make_policy(dry_run=False, is_tty=False),
            input_count=2,
            in_place=True,
            rerun_hint=HINT,
        )
    assert dry.value.exit_code == real.value.exit_code == REFUSED
    assert dry.value.message == real.value.message


def test_a_dry_run_predicts_a_clobbering_refusal_too() -> None:
    """The `clobbered=` half of "destructive" -- `merge`/`compose`/`convert`'s
    shape, not just `--in-place`'s."""
    with pytest.raises(errors.ConfirmationRequiredError):
        require_confirmation(
            make_policy(dry_run=True, is_tty=False),
            input_count=2,
            clobbered=("a.pdf", "b.pdf"),
            rerun_hint=HINT,
            reader=_ExplodingReader(),  # type: ignore[arg-type]
        )


def test_a_dry_run_on_a_terminal_neither_prompts_nor_refuses() -> None:
    """D12.2's carve-out: how a human answers is not a fact about the
    invocation, so the preview predicts nothing and -- above all -- reads
    nothing. The stream is checked as well as the reader: a prompt printed and
    then abandoned would leave the operator staring at an unanswerable question.
    """
    stream = StringIO()
    require_confirmation(
        make_policy(dry_run=True, is_tty=True),
        input_count=4,
        in_place=True,
        rerun_hint=HINT,
        stream=stream,
        reader=_ExplodingReader(),  # type: ignore[arg-type]
    )
    assert stream.getvalue() == "", f"a --dry-run prompted: {stream.getvalue()!r}"


@pytest.mark.parametrize(
    ("label", "kwargs", "policy_kwargs"),
    [
        ("dry, single input, in place", {"input_count": 1, "in_place": True}, {}),
        ("dry, bulk but create-only", {"input_count": 500}, {}),
        (
            "dry, bulk destructive with -y",
            {"input_count": 9, "in_place": True},
            {"assume_yes": True},
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_a_dry_run_keeps_every_negative_the_real_run_has(
    label: str,
    kwargs: dict[str, object],
    policy_kwargs: dict[str, object],
) -> None:
    """`dry == real` cuts both ways: a preview that refused where the real run
    proceeds would be exactly as wrong as the defect B-093 fixed."""
    require_confirmation(
        make_policy(dry_run=True, **policy_kwargs),  # type: ignore[arg-type]
        rerun_hint=HINT,
        reader=_ExplodingReader(),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )
