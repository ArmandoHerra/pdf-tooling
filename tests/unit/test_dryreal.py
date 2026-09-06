"""`tests/dryreal.py`'s own controls — PDF-44 Half A, the diagnostic blindfold.

WHY THIS FILE EXISTS
--------------------
`75447d838b`: ``prediction()``'s docstring claimed *"the non-vacuity guard every
prediction-reading helper in this suite carries"* while ``json.loads`` ran
**first and unguarded**. On EMPTY stdout the assertion it advertised could never
be reached, so the caller received a stdlib ``JSONDecodeError`` traceback with
the argv, the exit code and the stderr all discarded.

That is the blindfold `a31cd2a739` was diagnosed through — a `[reorder]` **M
cell** whose dry run printed nothing under whole-suite contention — and it cost
a full re-investigation to learn only that stdout had been empty.

**The file already contained the fix, twenty-two lines below the defect.**
``real_envelope()`` guards its own ``json.loads`` and its docstring explains
why (`fa5736f2ae`). The two siblings disagreed with each other, in the same
file, about the same hazard.

WHAT IS PROVEN HERE, AND HOW
----------------------------
By **injection**, never by reproduction. `a31cd2a739` is a contention flake:
the ledger's own rule is that *a single non-reproduction under contention is
weaker evidence than what is already recorded, not stronger*, and re-running
until green is indistinguishable from masking. So every arm below fabricates
the empty-stdout condition deterministically and asserts on the result. **No
arm here is a count of green runs.**

The two vacuity conditions are asserted to stay **distinguishable**. Collapsing
them into one message would answer *"there is no prediction"* without answering
*"because the process printed nothing"* versus *"because it printed an empty
batch"* — and those have completely different causes. The ledger's precision is
that the ``assert items`` line is unreachable **on empty stdout**, not
universally; an arm here pins that qualifier so the fix cannot lose it.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import pytest

TESTS_DIR: Final[Path] = Path(__file__).resolve().parents[1]
REPO_ROOT: Final[Path] = TESTS_DIR.parent
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from dryreal import prediction  # noqa: E402

#: The module whose three N/M/F cells carry `a31cd2a739`'s own failure.
MATRIX_MODULE: Final[Path] = TESTS_DIR / "integration" / "test_out_dir_planning.py"

#: `dry_and_real` call ordinal of the M cell inside
#: `test_ac12_the_five_precondition_matrix`: U (:167), N, **M**, F. Derived by
#: reading the function, and re-derived mechanically by
#: `test_the_m_cell_is_still_the_third_dry_and_real_call` below — a hard-coded
#: ordinal that silently stopped pointing at the M cell would make the
#: injection arm prove something about a different cell while still passing.
M_CELL_CALL_ORDINAL: Final = 3

#: A prediction payload with one item, the shape every non-vacuous dry run has.
_ONE_ITEM: Final = '{"items": [{"detail": {"would_exit": 4}}]}'


def _fake_dry(
    *,
    stdout: str = "",
    stderr: str = "boom",
    returncode: int = 2,
    args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """A dry run that printed nothing, fabricated rather than provoked."""
    return subprocess.CompletedProcess(
        args=args if args is not None else ["pdftooling", "reorder", "--dry-run", "-o", "json"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# --------------------------------------------------------------------------- #
# AC1 -- the guard fires BEFORE json.loads, and the TYPE is what observes it.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("blank", ["", "   ", "\n", " \t\n "])
def test_empty_or_whitespace_stdout_raises_an_assertion_not_a_json_error(blank: str) -> None:
    """AC1: the pre-fix behaviour is `json.JSONDecodeError`; the post-fix
    behaviour is `AssertionError`. Asserting the TYPE is what pins the
    difference — a message-only assertion would pass against either.

    Observed against the tree as it stood before this commit:
    ``prediction("")`` -> ``json.decoder.JSONDecodeError: Expecting value:
    line 1 column 1 (char 0)``.
    """
    with pytest.raises(AssertionError) as caught:
        prediction(blank)

    assert not isinstance(caught.value, json.JSONDecodeError), (
        "the guard must fire BEFORE json.loads; a JSONDecodeError here means the blindfold is back"
    )


def test_the_guard_runs_before_json_loads_even_when_json_would_also_fail() -> None:
    """The ordering is the property, so it is asserted on an input that BOTH
    guards could claim: whitespace is neither valid JSON nor non-empty."""
    with pytest.raises(AssertionError, match="NO STDOUT"):
        prediction("   \n  ")


# --------------------------------------------------------------------------- #
# AC2 -- the message NAMES THE RUN: verb, exit code, stderr, cell, pointer.
# --------------------------------------------------------------------------- #


def test_the_message_names_the_verb_the_cell_and_the_stderr() -> None:
    """AC2: all three of `reorder`, `M cell` and `boom` appear.

    `boom` is the load-bearing one. An empty-stdout dry run's ACTUAL signal is
    almost always sitting in stderr, and the `JSONDecodeError` this replaces
    threw it away — which is precisely why `a31cd2a739` cost a full
    re-investigation to learn only that stdout was empty.
    """
    with pytest.raises(AssertionError) as caught:
        prediction(_fake_dry(), context="reorder M cell")

    message = str(caught.value)
    missing = [token for token in ("reorder", "M cell", "boom") if token not in message]
    assert not missing, f"the message dropped {missing}: {message!r}"


def test_the_message_carries_the_returncode_and_the_ledger_pointer() -> None:
    """AC2's other two elements. The pointer means the next reader lands on the
    ledger rows instead of re-deriving them."""
    with pytest.raises(AssertionError) as caught:
        prediction(_fake_dry(returncode=3), context="convert N cell")

    message = str(caught.value)
    assert "returncode=3" in message, message
    assert "75447d838b" in message, message
    assert "a31cd2a739" in message, message


def test_a_long_stderr_is_truncated_rather_than_dropped_or_dumped() -> None:
    """The stderr is capped, not discarded: a verb that printed a megabyte of
    warnings must not bury the assertion naming it, and must not vanish."""
    with pytest.raises(AssertionError) as caught:
        prediction(_fake_dry(stderr="E" * 5000), context="split F cell")

    message = str(caught.value)
    assert "EEEE" in message, "the stderr was dropped entirely"
    assert "truncated" in message, "an unbounded stderr was pasted whole"
    assert len(message) < 2000, f"the message is {len(message)} chars; the cap did not apply"


def test_a_bare_string_says_so_rather_than_inventing_an_argv() -> None:
    """A caller that passed bare stdout cannot be told the verb, so the message
    says that and names the spelling that would carry it — rather than printing
    `argv=None` and leaving the reader to guess whether the run had no argv."""
    with pytest.raises(AssertionError) as caught:
        prediction("")

    message = str(caught.value)
    assert "bare stdout" in message, message
    assert "argv=" not in message, f"a bare string cannot carry an argv: {message!r}"


# --------------------------------------------------------------------------- #
# AC3 -- the TWO vacuity paths stay DISTINGUISHABLE.
# --------------------------------------------------------------------------- #


def test_the_two_vacuity_conditions_produce_different_diagnoses() -> None:
    """AC3: `""` and `'{"items": []}'` are different failures with different
    causes, and the fix may not collapse them into one message.

    This is the arm that keeps the ledger's own correction from being lost:
    the `assert items` line is unreachable **on empty stdout**, not
    universally. It is perfectly reachable on an empty batch, and it still is.
    """
    with pytest.raises(AssertionError) as empty_stdout:
        prediction("")
    with pytest.raises(AssertionError) as empty_batch:
        prediction('{"items": []}')

    no_stdout = str(empty_stdout.value)
    no_items = str(empty_batch.value)

    assert no_stdout != no_items, "the two vacuity paths collapsed into one message"
    assert "NO STDOUT" in no_stdout, no_stdout
    assert no_items == "the dry run produced no items to carry a prediction", (
        "the pre-existing empty-batch wording changed; AC3 requires it kept verbatim"
    )


def test_the_empty_batch_path_is_still_reached_through_a_process_object() -> None:
    """The tolerant signature must not route an empty BATCH into the empty
    STDOUT message just because a process object was passed."""
    with pytest.raises(AssertionError) as caught:
        prediction(_fake_dry(stdout='{"items": []}'), context="reorder M cell")

    assert str(caught.value) == "the dry run produced no items to carry a prediction"


# --------------------------------------------------------------------------- #
# AC4 -- the signature is BACKWARD-COMPATIBLE.
# --------------------------------------------------------------------------- #


def test_both_spellings_return_the_same_payload() -> None:
    """AC4: `prediction(dry.stdout)` and `prediction(dry)` agree. The tolerant
    signature is why Half A is a three-line landing rather than a 21-site
    sweep wearing a guard's clothes."""
    dry = _fake_dry(stdout=_ONE_ITEM, returncode=0, stderr="")

    assert prediction(dry.stdout) == {"would_exit": 4}
    assert prediction(dry) == prediction(dry.stdout)


def test_the_index_keyword_is_unchanged() -> None:
    """AC4: `index=` keeps its meaning and its default under both spellings."""
    payload = json.dumps({"items": [{"detail": {"would_exit": 1}}, {"detail": {"would_exit": 6}}]})
    dry = _fake_dry(stdout=payload, returncode=0, stderr="")

    assert prediction(payload) == {"would_exit": 1}
    assert prediction(payload, index=1) == {"would_exit": 6}
    assert prediction(dry, index=1) == {"would_exit": 6}


def test_an_item_without_a_detail_still_yields_an_empty_mapping() -> None:
    """The pre-existing `return {} if not detail` behaviour is unchanged."""
    assert prediction('{"items": [{}]}') == {}


# --------------------------------------------------------------------------- #
# AC5 -- a31cd2a739's OWN cell, made legible BY INJECTION, not by reproduction.
# --------------------------------------------------------------------------- #


def _matrix_source() -> str:
    return MATRIX_MODULE.read_text(encoding="utf-8")


def _prediction_calls_in_the_matrix_test() -> list[ast.Call]:
    """Every `prediction(...)` call inside `test_ac12_the_five_precondition_matrix`."""
    tree = ast.parse(_matrix_source())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "test_ac12_the_five_precondition_matrix"
        ):
            return [
                call
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "prediction"
            ]
    raise AssertionError("test_ac12_the_five_precondition_matrix no longer exists")


@pytest.mark.parametrize("cell", ["N cell", "M cell", "F cell"])
def test_each_flaking_cell_labels_itself(cell: str) -> None:
    """AC5's discriminator: each of the three cells that actually flaked passes
    its OWN `context=` label.

    Parametrised per cell deliberately. Reverting `context=` at the M cell
    alone must fail an arm that NAMES `M cell` — so the report says which half
    of the diagnostic regressed, rather than "the three cells changed".
    """
    labelled = {
        keyword.value
        for call in _prediction_calls_in_the_matrix_test()
        for keyword in call.keywords
        if keyword.arg == "context"
    }
    rendered = {ast.unparse(value) for value in labelled}

    assert any(cell in text for text in rendered), (
        f"the {cell} no longer passes a `context=` naming itself; `a31cd2a739`'s "
        f"next occurrence will name the verb but not the cell. Found: {sorted(rendered)}"
    )


def test_the_three_cells_pass_the_process_object_not_bare_stdout() -> None:
    """The verb comes from the argv, which only the process object carries. A
    cell that reverted to `.stdout` would keep its cell label and silently lose
    the verb, which is the half of AC2 that is easiest to lose by accident."""
    bare = [
        ast.unparse(call)
        for call in _prediction_calls_in_the_matrix_test()
        if any(keyword.arg == "context" for keyword in call.keywords)
        and any(isinstance(arg, ast.Attribute) and arg.attr == "stdout" for arg in call.args)
    ]
    assert not bare, (
        f"a labelled cell passes bare stdout, so its message cannot name the verb: {bare}"
    )


def test_the_m_cell_is_still_the_third_dry_and_real_call() -> None:
    """`M_CELL_CALL_ORDINAL` is derived, not trusted.

    The injection arm below blanks the Nth `dry_and_real` result. If a cell is
    added ahead of the M cell, that ordinal would silently start addressing the
    F cell and the injection would still pass — proving legibility for a cell
    nobody asked about. This fails instead.
    """
    tree = ast.parse(_matrix_source())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "test_ac12_the_five_precondition_matrix"
        ):
            calls = [
                call
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "dry_and_real"
            ]
            break
    else:  # pragma: no cover - guarded by the previous test
        raise AssertionError("the matrix test no longer exists")

    # ast.walk is not source-ordered; sort by position to get call ordinals.
    ordered = sorted(calls, key=lambda call: (call.lineno, call.col_offset))
    assert len(ordered) == 4, f"expected U/N/M/F, found {len(ordered)} dry_and_real calls"

    m_call = ordered[M_CELL_CALL_ORDINAL - 1]
    following = _matrix_source().splitlines()[m_call.lineno : m_call.lineno + 6]
    assert any("M cell" in line for line in following), (
        f"the {M_CELL_CALL_ORDINAL}rd dry_and_real call at line {m_call.lineno} is no "
        f"longer the M cell; the injection arm would address the wrong cell"
    )


_INJECTION_PLUGIN = '''\
"""Blank the M cell's dry stdout, reproducing `a31cd2a739`'s observable exactly."""

import subprocess

ORDINAL = {ordinal}


def pytest_collection_modifyitems(session, config, items):
    for item in items:
        module = getattr(item, "module", None)
        if module is not None and module.__name__.endswith("test_out_dir_planning"):
            _blank_the_m_cell(module)
            return


def _blank_the_m_cell(module):
    real = module.dry_and_real
    seen = {{"n": 0}}

    def counting(*args, **kwargs):
        dry, live = real(*args, **kwargs)
        seen["n"] += 1
        if seen["n"] == ORDINAL:
            dry = subprocess.CompletedProcess(
                args=dry.args, returncode=dry.returncode, stdout="", stderr=dry.stderr
            )
        return dry, live

    module.dry_and_real = counting
'''


@pytest.mark.e2e
def test_the_m_cell_names_the_verb_and_the_cell_when_its_dry_run_prints_nothing(
    tmp_path: Path,
) -> None:
    """AC5, end to end and by INJECTION: `a31cd2a739`'s exact observable —
    the `[reorder]` M cell's dry run producing empty stdout — is fabricated,
    and the real test is driven against it.

    **This does not reproduce the flake and does not try to.** The race is not
    re-run; its OBSERVABLE is injected, which is deterministic and costs no
    contention. The assertion is that the failure now NAMES the run instead of
    being a `JSONDecodeError` with the argv and the stderr thrown away.
    """
    plugin = tmp_path / "inject_m_cell.py"
    plugin.write_text(_INJECTION_PLUGIN.format(ordinal=M_CELL_CALL_ORDINAL), encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            f"{MATRIX_MODULE.relative_to(REPO_ROOT).as_posix()}"
            "::test_ac12_the_five_precondition_matrix[reorder]",
            "-q",
            "-n",
            "0",
            "-p",
            "inject_m_cell",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    output = completed.stdout + completed.stderr
    if "no tests ran" in output or "ERROR" in output.split("\n")[0]:  # pragma: no cover
        pytest.fail(f"the injection run never reached the cell:\n{output[-3000:]}")

    assert completed.returncode != 0, (
        f"blanking the M cell's dry stdout did not fail the test:\n{output[-3000:]}"
    )
    assert "reorder" in output, f"the failure does not name the VERB:\n{output[-3000:]}"
    assert "M cell" in output, f"the failure does not name the CELL:\n{output[-3000:]}"
    assert "NO STDOUT" in output, f"the guard did not fire:\n{output[-3000:]}"
    # The token is matched WITH ITS COLON, and that is not fussiness. A bare
    # `"JSONDecodeError" not in output` fails against the FIXED tree: pytest
    # echoes `dryreal.py`'s source as traceback context, and `prediction()`'s
    # own docstring names the exception it replaced. The predicate would have
    # been reading its own explanation. A raised one renders as
    # `json.decoder.JSONDecodeError: Expecting value: ...`; the prose spells it
    # ``JSONDecodeError`` in double backticks and never with a colon.
    raised_json_error = [line for line in output.splitlines() if "JSONDecodeError:" in line]
    assert not raised_json_error, (
        f"the blindfold is back -- the cell still fails as a stdlib traceback: {raised_json_error}"
    )


def test_the_injection_control_would_notice_a_message_that_named_nothing() -> None:
    """The control above can only be trusted if its own predicate can fail.

    `_no_stdout_message` is exercised here with an argv and a context that
    contain NEITHER token, so the four assertions the injection arm makes are
    shown to be discriminating rather than satisfied by any failure text.
    """
    with pytest.raises(AssertionError) as caught:
        prediction(_fake_dry(args=["pdftooling", "split"], stderr=""), context="split N cell")

    message = str(caught.value)
    assert "reorder" not in message
    assert "M cell" not in message
    assert "NO STDOUT" in message


def _unwrapped_prediction_call_sites() -> dict[str, int]:
    """AC4's census, DERIVED rather than transcribed — per file, `dryreal`'s
    `prediction` only.

    A bare `git grep -c "prediction("` over `tests/` counts six lines that are
    not call sites of this helper at all: a comment, a test function whose name
    ends in `_the_prediction`, `test_text_tables_cli.py`'s own module-local
    `_prediction` def and its three calls. Those are a DIFFERENT helper, and
    conflating them is how a census becomes a number nobody can re-derive.
    """
    counts: dict[str, int] = {}
    for path in sorted((TESTS_DIR).rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports_it = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "dryreal"
            and any(alias.name == "prediction" for alias in node.names)
            for node in ast.walk(tree)
        )
        if not imports_it:
            continue
        calls = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "prediction"
        )
        if calls:
            counts[path.relative_to(TESTS_DIR).as_posix()] = calls
    return counts


def test_the_call_site_census_is_derivable_and_the_sweep_was_not_taken() -> None:
    """AC4: the tolerant signature means the other call sites keep working
    UNEDITED. This asserts they are still there, so a later "cleanup" that
    migrated all of them would have to say so rather than drift.

    `test_crypto_roundtrip.py`'s eight sites are explicitly NOT migrated: the
    guard protects them without a call-site change, which is the entire reason
    the signature stays tolerant.
    """
    counts = _unwrapped_prediction_call_sites()

    assert counts.get("integration/test_crypto_roundtrip.py") == 8, (
        f"the crypto sites were migrated after all; census: {counts}"
    )
    assert sum(counts.values()) >= 18, f"call sites disappeared wholesale; census: {counts}"


def test_no_call_site_passes_a_process_object_without_expecting_the_tolerant_signature() -> None:
    """The tolerant signature is load-bearing, so it is asserted rather than
    assumed: every `prediction(x.stdout)` site still resolves against a `str`,
    and every `prediction(x, context=...)` site against a process object."""
    dry = _fake_dry(stdout=_ONE_ITEM, returncode=0, stderr="")

    assert prediction(dry.stdout, index=0) == {"would_exit": 4}
    assert prediction(dry, index=0, context="reorder M cell") == {"would_exit": 4}


def test_a_process_object_whose_stdout_is_none_is_treated_as_empty() -> None:
    """`capture_output=False` yields `stdout=None`. Unwrapping must not raise
    an `AttributeError` on `None.strip()` — that would be a THIRD failure mode
    wearing a traceback, which is the class this whole item exists to end."""
    dry: Any = subprocess.CompletedProcess(
        args=["pdftooling", "reorder"], returncode=1, stdout=None, stderr="boom"
    )
    with pytest.raises(AssertionError, match="NO STDOUT"):
        prediction(dry, context="reorder M cell")
