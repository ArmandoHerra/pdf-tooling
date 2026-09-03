"""PDF-25 — every usage error a user can reach, inside the product's own envelope.

`README.md`'s output contract promises that *"a machine consumer reading stdout
never has to also read stderr to learn that the run failed."* Five ledger rows
were live counter-examples — `4772bfd8fc`, `76ece64648`, `7fc5a169f6`,
`d220b7d79d`, `a472acde7a` — and they are **three mechanisms**, every one of
them a case where something other than `cli/main.py`'s single
`except PdfToolkitError` handler terminated the process:

* **M1** Click's own parser raised, and `standalone_mode=True` printed
  ``Usage:`` + ``Error:`` to stderr and exited 2 with **zero bytes on stdout**;
* **M2** the root callback printed help and raised ``typer.Exit(OK)`` on a
  command line that named flags and no command;
* **M3** a third-party logger reached root's ``lastResort`` handler, so engine
  chatter ignored ``--quiet`` and bypassed ``RedactingFilter`` entirely.

**Why this module and not `tests/test_cli_spine.py`.** The spec nominated the
spine module *or* the one `PDF-17` designates; the PM designated a new module
(X-307), because `PDF-29` owns the spine module's startup-budget section in
this same wave and lands immediately after this spec. A hunk here would have
been a rebase conflict for an engineer who owns none of this code.

EVERY POPULATION IN THIS MODULE IS DERIVED
------------------------------------------
`discover_verbs()`, `discover_groups()`, `GLOBAL_OPTIONS`, `GLOBAL_PARAMS`,
`REFUSED_PASSWORD_FLAGS` and `OutputFormat` are read at runtime; the numbers
26, 1, 15 and 3 appear nowhere below. `POPULATIONS` at the foot of this module
is the anti-lapse guard (`tests/test_cli_contract.py`'s own idiom, and for its
own reason: `discover_groups()` returned `()` for eight specs, and a row
parametrized over an empty tuple collects zero cases and cannot bite).
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pytest
import typer

from pdf_toolkit.cli.common import (
    GLOBAL_FLAG_SPELLINGS,
    GLOBAL_OPTIONS,
    REFUSED_PASSWORD_FLAGS,
)
from pdf_toolkit.cli.exit_codes import (
    AUTH,
    ENGINE_MISSING,
    FAILURE,
    NO_INPUT,
    OK,
    REFUSED,
    USAGE,
)
from pdf_toolkit.cli.main import PROG_NAME, app
from pdf_toolkit.output import OutputFormat
from registry import REPO_ROOT, discover_groups, discover_verbs, run_cli, run_cli_with_pty

SRC: Final[Path] = REPO_ROOT / "src"

#: The repo fixture `d220b7d79d` was RECORDED against. Not corpus, and not
#: substituted: X-110 records that substituting a fixture for this exact file
#: previously manufactured a false "stopped reproducing" on this very row.
MALFORMED: Final[Path] = REPO_ROOT / "testdata" / "malformed.pdf"

VERBS = discover_verbs()
GROUPS = discover_groups()
SHAPES: Final[tuple[OutputFormat, ...]] = tuple(OutputFormat)

#: The structured shapes — the ones that put the envelope on **stdout**.
STRUCTURED_SHAPES: Final[tuple[OutputFormat, ...]] = tuple(
    shape for shape in SHAPES if shape is not OutputFormat.TABLE
)

#: The live root command's parameters, keyed by every spelling each declares.
#: Everything below that needs to know whether a global flag takes a value, or
#: exits eagerly, asks THIS rather than a hand-written table.
_ROOT_PARAMS: Final[dict[str, Any]] = {
    spelling: param
    for param in typer.main.get_command(app).params
    for spelling in tuple(getattr(param, "opts", ()) or ())
}


def _needs_value(flag: str) -> bool:
    param = _ROOT_PARAMS[flag]
    return not (getattr(param, "is_flag", False) or getattr(param, "count", False))


def _is_eager(flag: str) -> bool:
    return bool(getattr(_ROOT_PARAMS[flag], "is_eager", False))


#: The one global flag that exits **0** before the root callback body runs at
#: all. Derived, so a second eager flag joins it without an author noticing.
EAGER_GLOBAL_FLAGS: Final[tuple[str, ...]] = tuple(
    flag for flag in GLOBAL_OPTIONS if _is_eager(flag)
)

#: Everything else in the block: the flags for which "given, with no command"
#: is an INCOMPLETE INVOCATION rather than an eager exit.
INCOMPLETE_INVOCATION_FLAGS: Final[tuple[str, ...]] = tuple(
    flag for flag in GLOBAL_OPTIONS if flag not in EAGER_GLOBAL_FLAGS
)


def _value_for(flag: str, workspace: Path) -> list[str]:
    """A valid argument for *flag*, derived from the live parameter's type."""
    if not _needs_value(flag):
        return []
    param_type = getattr(_ROOT_PARAMS[flag], "type", None)
    choices = tuple(getattr(param_type, "choices", ()) or ())
    if choices:
        return [OutputFormat.JSON.value if OutputFormat.JSON.value in choices else choices[0]]
    name = getattr(param_type, "name", "")
    if name == "path":
        return [str(workspace / "destination")]
    if name in ("int", "integer"):
        return ["2"]
    # The two `text` members want different things — `--name` is a filename
    # template that must carry no path separator, `--password-file` a readable
    # path or `-`. A single dash satisfies both, and reads no stdin here
    # because nothing downstream of an incomplete invocation asks for one.
    return ["-"]


def argv_for(flag: str, workspace: Path) -> list[str]:
    """`<flag> [value]` — the minimal command line that names exactly one flag."""
    return [flag, *_value_for(flag, workspace)]


def envelope(stdout: str) -> dict[str, Any]:
    """The parsed envelope, asserting stdout parses **whole** as one object (AC20)."""
    payload = json.loads(stdout)
    assert isinstance(payload, dict), f"stdout is not one JSON object: {stdout[:200]!r}"
    assert "error" in payload, f"stdout carries no error envelope: {stdout[:200]!r}"
    return payload


def error_of(stdout: str) -> dict[str, Any]:
    error = envelope(stdout)["error"]
    assert isinstance(error, dict)
    return error


# --------------------------------------------------------------------------- #
# AC5 — ⚠ every verb's exit code survives `standalone_mode=False`.
#
# THE REGRESSION THAT MATTERS MORE THAN ANY OTHER CRITERION IN THIS SPEC, and
# the one whose red was observed FIRST, before the real `main()` was written.
#
# 28 `cli/cmd_*.py` modules signal their exit code with `raise typer.Exit(code)`.
# Under `standalone_mode=False` the framework converts that into the RETURN
# VALUE of `app(...)`: it does not raise and it does not exit. A `main()` ending
# in `raise SystemExit(OK)` therefore turns every such verb exit into 0,
# silently — a wrong answer carrying a success exit code, which would make
# `cmd --dry-run && cmd`, OR-7, every contract row asserting an exit code, and
# every CI gate pass on failure.
#
# A CORRECTION TO THIS SPEC'S OWN AC5, MEASURED RATHER THAN ASSUMED. AC5 states
# that under the planted defect "every non-zero case must go red". It cannot:
# this product signals SOME non-zero exits by RAISING (`PdfToolkitError` for
# every usage error, every safety refusal and every OR-3/OR-4 message) and
# others by RETURNING (`typer.Exit(result.exit_code)`), and only the returned
# ones ride the hazard. Measured at implementation time, USAGE (2) and REFUSED
# (5) are raised on every path this matrix can reach, so a red on them would be
# evidence of a DIFFERENT defect. `RETURN_SIGNALLED_CODES` below records which
# codes ride the return value, and `test_ac5_the_planted_defect_zeroes_exactly_
# the_return_signalled_codes` asserts that set rather than assuming it — so a
# later refactor that moves an exit onto the return path is a red here.
#
# A SECOND CORRECTION (2026-09-03), AND IT IS THE ONE THIS BLOCK ITSELF GOT
# WRONG. `RETURN_SIGNALLED_CODES` shipped as `(FAILURE, NO_INPUT, AUTH)` under a
# docstring calling that "the non-zero codes THIS PRODUCT signals through
# `typer.Exit(...)`". It is not the product's set. `cli/cmd_doctor.py` ends
# `raise typer.Exit(ENGINE_MISSING)` whenever `--strict` finds a port
# unavailable, so **3 rides the return value too** and the §D3 hazard zeroes it
# exactly as it zeroes 1, 4 and 6. The exclusion was DISCLOSED rather than
# concealed — `REACHABLE_CODES` named it and pointed at `tests/test_doctor.py`
# — but a disclosed exclusion under a docstring that generalises to the whole
# product is still a docstring asserting something false. It was checkable with
# this module's OWN plant, and it was not checked, because the matrix reached no
# invocation that exits 3.
#
# Both tuples now name 3 and the matrix carries a `doctor --strict` row.
# Measured: `PATH=<an empty dir> pdftoolkit doctor --strict` is **3** through
# the real `main()` and **0** through the plant, on a host where both system
# binaries ARE installed — so it is the PATH scrub that produces the 3, not the
# host. That is the whole hermeticity argument, and it is why the scrub is not
# optional: without it this row reads 0 here and 3 on a bare container.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ExitCase:
    """One invocation, its expected exit code, and why it is in the matrix.

    `env_overlay` and `cwd` exist for ONE row. Every other exit code in this
    contract is a property of the command line; `ENGINE_MISSING` is a property
    of the MACHINE, and a row that inherits this host's environment would read 0
    where tesseract and soffice are installed and 3 where they are not. Both
    fields are applied to BOTH runs of a case — the real CLI and the planted
    defect — because a plant handed a different environment measures a different
    invocation.
    """

    label: str
    code: int
    why: str
    #: A hashable overlay onto `os.environ`, empty for every row but one.
    env_overlay: tuple[tuple[str, str], ...] = ()
    #: The working directory, or `None` for `run_cli`'s default of `REPO_ROOT`.
    cwd: Path | None = None


def _env_for(case: ExitCase) -> dict[str, str] | None:
    """The case's environment, or `None` to inherit this process's.

    `None` and not `dict(os.environ)`: the twenty rows that do not scrub
    anything must keep riding the default that every other `run_cli` caller in
    this suite rides, so this remediation cannot change what they measure.
    """
    if not case.env_overlay:
        return None
    return {**os.environ, **dict(case.env_overlay)}


#: Every exit code this matrix reaches — now every code `cli/exit_codes.py`
#: defines, `ENGINE_MISSING` (3) included. 3 was excluded until 2026-09-03 on
#: the argument that it "depends on a system binary being unavailable, which is
#: an environment property rather than an invocation". The premise was right and
#: the conclusion was wrong: an environment is something a test can CONSTRUCT,
#: and the `doctor --strict` row below constructs it (`ExitCase.env_overlay`).
#:
#: WHO OWNS CODE 3, stated once so two docstrings cannot drift apart:
#: `tests/test_doctor.py` owns 3 as a PRODUCT behaviour — the six-row report,
#: the hints, `--strict` 3 vs plain 0 (`:222`, `:236`). This module owns 3 on
#: exactly one axis, the TERMINAL SEAM: that `standalone_mode=False` does not
#: swallow it. Neither is a substitute for the other, and `tests/test_doctor.py`
#: is not weakened by this row — it is what proves 3 is reachable at all.
REACHABLE_CODES: Final[tuple[int, ...]] = (
    OK,
    FAILURE,
    USAGE,
    ENGINE_MISSING,
    NO_INPUT,
    REFUSED,
    AUTH,
)

#: The non-zero codes THIS MATRIX'S INVOCATIONS signal through `typer.Exit(...)`
#: — i.e. as the RETURN VALUE of `app(..., standalone_mode=False)` — and
#: therefore the codes the §D3 hazard silently zeroes on them. Measured, not
#: assumed: the control below re-derives this set from the planted defect's own
#: behaviour and fails if it has moved.
#:
#: SCOPED TO THE MATRIX ON PURPOSE, and this is the correction of 2026-09-03.
#: The earlier wording claimed these were the codes "this product" signals by
#: return, which no matrix can establish: `typer.Exit(result.exit_code)` appears
#: in 26 verb modules, and `OperationResult.exit_code` is a field, so USAGE or
#: REFUSED reaching the return path on some invocation NOT made here is possible
#: and unmeasured. What is measured, and what the control enforces, is narrower
#: and still the thing that matters: on these twenty-one invocations the split
#: between raised and returned is pinned, so a refactor moving an exit across it
#: is a red rather than a silent widening of a `SystemExit(OK)` blast radius.
RETURN_SIGNALLED_CODES: Final[tuple[int, ...]] = (FAILURE, ENGINE_MISSING, NO_INPUT, AUTH)


def exit_matrix(workspace: Path, good: Path, encrypted: Path) -> list[tuple[ExitCase, list[str]]]:
    """The matrix, built against real files so every row is actually reachable.

    A NOTE ON THE `why` STRINGS, corrected 2026-09-03 alongside this module's
    return-signalled docstring and by the same evidence. Three rows read "a
    SECOND/THIRD verb on the returned-code path"; the plant below reports them
    among the cases that KEPT their code, so `text` and `meta get` reach 1, 4
    and 6 by RAISING, not by returning. Only `info` returns them, because it is
    the batch verb and ends `typer.Exit(run_exit_code(outcomes))`. The rows are
    still worth having — a second verb reaching the same code is what stops the
    raised/returned split being read off one verb — but they were describing a
    mechanism they do not use, next to a docstring being fixed for exactly that.
    """
    text_source = workspace / "source.txt"
    text_source.write_text("hello from the exit-code matrix\n", encoding="utf-8")
    occupied = workspace / "occupied.pdf"
    occupied.write_bytes(b"not a pdf, but it exists")
    # A directory with nothing in it, used as the whole of `PATH` for the
    # `doctor --strict` row. `tests/test_doctor.py`'s own idiom, and correct
    # for the same reason: `run_cli` and the plant both spawn through an
    # ABSOLUTE interpreter/console-script path, so scrubbing `PATH` hides the
    # system binaries the port registry probes for without hiding the CLI.
    empty_path = workspace / "an-empty-PATH"
    empty_path.mkdir(exist_ok=True)
    return [
        (ExitCase("version", OK, "a verb that succeeds"), ["version"]),
        (ExitCase("--version", OK, "an eager flag that exits before any verb body"), ["--version"]),
        (ExitCase("--help", OK, "the help option, also eager"), ["--help"]),
        (ExitCase("bare root", OK, "AC13 — no arguments at all keeps help + 0"), []),
        (ExitCase("info <good>", OK, "a reading verb over a valid document"), ["info", str(good)]),
        (
            ExitCase("info <malformed>", FAILURE, "the operation ran and failed (returned)"),
            ["info", str(MALFORMED)],
        ),
        (
            ExitCase("text <malformed>", FAILURE, "a SECOND verb reaching 1 — by RAISING"),
            ["text", str(MALFORMED)],
        ),
        (
            ExitCase("info <good> <missing>", FAILURE, "a mixed batch, also returned"),
            ["info", str(good), str(workspace / "absent.pdf")],
        ),
        (
            ExitCase("version --no-backup", USAGE, "OUR OWN usage error — raised, not returned"),
            ["version", "--no-backup"],
        ),
        (
            ExitCase("version --out-dir", USAGE, "OR-3's central refusal — also ours"),
            ["version", "--out-dir", str(workspace)],
        ),
        (
            ExitCase("info --unknown-flag", USAGE, "CLICK's parser error, newly enveloped"),
            ["info", "--definitely-not-a-flag", str(good)],
        ),
        (
            ExitCase("info --threads 1 (no operand)", USAGE, "Click's ARITY error (E4)"),
            ["info", "--threads", "1"],
        ),
        (
            ExitCase("meta bogus", USAGE, "PLAN.md §5.6's grouping-parent clause"),
            ["meta", "bogus"],
        ),
        (ExitCase("bogus verb", USAGE, "an unknown subcommand at root"), ["definitely-not-a-verb"]),
        (
            ExitCase("info <missing>", NO_INPUT, "valid invocation, nothing to act on (returned)"),
            ["info", str(workspace / "does-not-exist.pdf")],
        ),
        (
            ExitCase("text <missing>", NO_INPUT, "a SECOND verb reaching 4 — by RAISING"),
            ["text", str(workspace / "does-not-exist.pdf")],
        ),
        (
            ExitCase("create -O <occupied>", REFUSED, "a safety gate declined — raised"),
            ["create", str(text_source), "-O", str(occupied)],
        ),
        (
            ExitCase("merge -O <occupied>", REFUSED, "the same gate, from a second verb"),
            ["merge", str(good), str(good), "-O", str(occupied)],
        ),
        (
            ExitCase(
                "doctor --strict (PATH scrubbed)",
                ENGINE_MISSING,
                "the code this matrix used to exclude, and the reason the exclusion was "
                "wrong: `cmd_doctor.py` raises `typer.Exit(ENGINE_MISSING)`, so 3 rides "
                "the RETURN VALUE and the §D3 hazard zeroes it",
                env_overlay=(("PATH", str(empty_path)),),
                # The workspace, not `REPO_ROOT`: `--strict` also `rglob`s the
                # working directory for stray toolkit temp files, which costs
                # ~0.85 s over this repo (`.venv`, `.git`, `node_modules`) on
                # each of this row's two runs, and walks a tree other xdist
                # workers are live in. Strays never change the exit code, so
                # nothing is lost by pointing it somewhere small and ours.
                cwd=workspace,
            ),
            ["doctor", "--strict"],
        ),
        (
            ExitCase("info <encrypted>", AUTH, "password required, not supplied (returned)"),
            ["info", str(encrypted)],
        ),
        (
            ExitCase("meta get <encrypted>", AUTH, "a THIRD verb reaching 6 — by RAISING"),
            ["meta get", str(encrypted)],
        ),
    ]


#: The planted defect AC5 names, run as a real process. `main()` is reproduced
#: here with EXACTLY ONE mutation — the success path discards the return value
#: — and every handler reached through the real module, so what this control
#: measures is the §D3 hazard and nothing else. A cruder plant (a bare `app()`
#: call with no handlers) would have turned every RAISED error into a traceback
#: at exit 1 and reported that as a red too, which measures the absence of the
#: handlers rather than the presence of the bug.
_PLANTED_WRONG_MAIN: Final[str] = """
import sys
from pdf_toolkit.cli import main as m
from pdf_toolkit.cli.exit_codes import OK
from pdf_toolkit.errors import PdfToolkitError

try:
    m.app(prog_name=m.PROG_NAME, standalone_mode=False)
except PdfToolkitError as error:
    m._terminate(error, None)
except Exception as error:
    if m._is_click_exception(error):
        envelope, pointer = m._envelope_for(error)
        m._terminate(envelope, pointer)
    if m._ABORT in m._mro_names(error):
        raise SystemExit(1) from None
    raise
raise SystemExit(OK)  # THE MUTATION: the return value is discarded.
"""


def _run_planted_wrong_main(
    argv: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None
) -> int:
    result = subprocess.run(  # noqa: S603 - fixed argv, never a shell
        [sys.executable, "-c", _PLANTED_WRONG_MAIN, *argv],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd is not None else REPO_ROOT,
        env=env,
    )
    return result.returncode


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("usage-envelope")


@pytest.fixture(scope="module")
def good_pdf(workspace: Path) -> Path:
    """A valid one-page document, built through the CLI itself."""
    source = workspace / "good-source.txt"
    source.write_text("a valid document\n", encoding="utf-8")
    target = workspace / "good.pdf"
    if not target.exists():
        result = run_cli("create", str(source), "-O", str(target))
        assert result.returncode == OK, result.stderr
    return target


@pytest.mark.e2e
def test_ac5_every_reachable_exit_code_survives_the_terminal_seam(
    workspace: Path, good_pdf: Path, corpus
) -> None:
    """AC5. One invocation per reachable code, asserted as a whole matrix."""
    encrypted = Path(corpus.path("encrypted_aes256"))
    failures: list[str] = []
    for case, argv in exit_matrix(workspace, good_pdf, encrypted):
        result = run_cli(*argv, env=_env_for(case), cwd=case.cwd)
        if result.returncode != case.code:
            failures.append(
                f"{case.label}: expected {case.code}, got {result.returncode} "
                f"({case.why})\n    stdout={result.stdout[:160]!r}"
                f"\n    stderr={result.stderr[:160]!r}"
            )
    assert not failures, "exit codes moved under `standalone_mode=False`:\n" + "\n".join(failures)


@pytest.mark.e2e
def test_ac5_the_matrix_reaches_every_code_it_claims(
    workspace: Path, good_pdf: Path, corpus
) -> None:
    """The anti-lapse half: a matrix that stopped covering a code is not a
    narrower control, it is a control that cannot see the hazard on that code."""
    encrypted = Path(corpus.path("encrypted_aes256"))
    covered = {case.code for case, _ in exit_matrix(workspace, good_pdf, encrypted)}
    assert covered == set(REACHABLE_CODES), (
        f"the matrix covers {sorted(covered)}, but claims {sorted(REACHABLE_CODES)}"
    )


@pytest.mark.e2e
def test_ac5_the_planted_defect_zeroes_exactly_the_return_signalled_codes(
    workspace: Path, good_pdf: Path, corpus
) -> None:
    """AC5's RED, automated — and its breadth measured rather than claimed.

    Every non-zero case is re-run against a `main()` whose success path
    discards the return value. A case that then reports **0** was riding the
    §D3 hazard; a case that keeps its code was raising all along.

    Two assertions, and the second is the one that stops this being decorative:

    * the planted defect zeroes **at least one case per
      `RETURN_SIGNALLED_CODES` member** — so the control fires, on every code
      it claims to watch;
    * it zeroes **nothing outside** that set — so the set is a measurement of
      how this product signals its exits, not a guess, and a later refactor
      that moves USAGE or REFUSED onto the return path turns this red instead
      of quietly widening the blast radius of a `SystemExit(OK)` regression.
    """
    encrypted = Path(corpus.path("encrypted_aes256"))
    zeroed: dict[int, list[str]] = {}
    survived: dict[int, list[str]] = {}
    for case, argv in exit_matrix(workspace, good_pdf, encrypted):
        if case.code == OK:
            continue
        planted = _run_planted_wrong_main(argv, env=_env_for(case), cwd=case.cwd)
        (zeroed if planted == OK else survived).setdefault(case.code, []).append(case.label)

    assert set(zeroed) == set(RETURN_SIGNALLED_CODES), (
        f"the planted defect zeroed codes {sorted(zeroed)}; this module declares "
        f"{sorted(RETURN_SIGNALLED_CODES)} as the return-signalled set. Zeroed cases: "
        f"{zeroed}. Cases that kept their code: {survived}"
    )
    assert all(zeroed[code] for code in RETURN_SIGNALLED_CODES)


# --------------------------------------------------------------------------- #
# AC1 / AC2 / AC3 / AC20 — Click's parser errors, enveloped, in every shape.
#
# `4772bfd8fc`. Measured pre-fix at `2d19bcb` and re-measured at `15eb4ea`:
# `info --unknown-flag -o json` exits 2 with **0 bytes on stdout** and 129 on
# stderr. The roadmap and the brief both recorded Click's `Usage:` block as
# going "to stdout" — it does not, and an acceptance criterion written against
# "stdout stops carrying the Usage block" would have passed on the UNFIXED
# binary. The defect is that stdout is EMPTY.
# --------------------------------------------------------------------------- #

UNKNOWN_FLAG: Final[str] = "--definitely-not-a-flag"

UNKNOWN_FLAG_CASES: Final[tuple[tuple[Any, OutputFormat], ...]] = tuple(
    (verb, shape) for verb in VERBS for shape in SHAPES
)


def _shape_ids(cases: tuple[tuple[Any, OutputFormat], ...]) -> list[str]:
    return [f"{verb.name}-{shape.value}" for verb, shape in cases]


@pytest.mark.e2e
@pytest.mark.parametrize(("verb", "shape"), UNKNOWN_FLAG_CASES, ids=_shape_ids(UNKNOWN_FLAG_CASES))
def test_ac1_ac3_an_unknown_flag_is_enveloped_at_every_verb_in_every_shape(
    verb, shape: OutputFormat
) -> None:
    """AC1 + AC3 + AC20.

    Red: revert `main()` to `standalone_mode=True` — stdout is 0 bytes on all
    26 verbs and the JSON parse raises. Red for the shape dimension: delete the
    `ndjson` member from the source of `SHAPES` and the case count guard fails.
    """
    result = run_cli(verb.name, UNKNOWN_FLAG, "-o", shape.value)
    assert result.returncode == USAGE, f"{verb.name}/{shape.value}: {result.stderr!r}"
    if shape is OutputFormat.TABLE:
        assert result.stdout == "", f"table errors belong on stderr: {result.stdout!r}"
        assert result.stderr.startswith("error: "), result.stderr
        return
    error = error_of(result.stdout)
    assert error["code"] == USAGE
    assert error["kind"] == "usage"
    assert result.stderr == "", f"a structured shape must leave stderr empty: {result.stderr!r}"
    assert "Usage:" not in result.stdout, "AC20 — no usage block may leak onto stdout"


def test_ac2_the_unknown_flag_population_is_derived_and_non_vacuous() -> None:
    """AC2. The parametrization comes from the live registry and the live enum.

    Red: replace `discover_verbs()` with a hand-typed three-verb tuple and this
    count assertion fails.
    """
    assert len(VERBS) >= 26, f"the registry reports {len(VERBS)} verbs"
    assert len(SHAPES) == 3, SHAPES
    assert len(UNKNOWN_FLAG_CASES) == len(VERBS) * len(SHAPES)


# --------------------------------------------------------------------------- #
# AC4 — the ARITY shape (Evidence §E4), and why the fix could not live in
# `validate_config`.
#
# `pdftoolkit info --threads 0 -o json` gives exit 2, stdout 0 and stderr
# `Error: Missing argument 'PDF...'.` — the `--threads must be 1 or greater`
# message `cli/common.py` exists to produce NEVER FIRES, because Click's own
# arity check runs during parameter processing, upstream of every callback
# body. Any hook placed in a callback is structurally incapable of seeing this.
# --------------------------------------------------------------------------- #

_ROOT_COMMAND: Final[Any] = typer.main.get_command(app)


def _verbs_with_a_required_argument() -> tuple[Any, ...]:
    def required(command: Any) -> bool:
        return any(
            getattr(param, "param_type_name", None) == "argument"
            and getattr(param, "required", False)
            for param in getattr(command, "params", ())
        )

    found: list[Any] = []
    for verb in VERBS:
        command: Any = _ROOT_COMMAND
        for part in verb.path:
            command = getattr(command, "commands", {})[part]
        if required(command):
            found.append(verb)
    return tuple(found)


REQUIRED_ARGUMENT_VERBS: Final[tuple[Any, ...]] = _verbs_with_a_required_argument()

_MISSING_ARGUMENT = re.compile(r"Missing argument '([^']+)'")


@pytest.mark.e2e
@pytest.mark.parametrize(
    "verb", REQUIRED_ARGUMENT_VERBS, ids=[verb.name for verb in REQUIRED_ARGUMENT_VERBS]
)
def test_ac4_the_arity_shape_is_enveloped_and_names_the_missing_argument(verb) -> None:
    """AC4. Red: on the unfixed binary this is 0 bytes on stdout — which is the
    point, and why this criterion fails at `15eb4ea` today."""
    result = run_cli(verb.name, "--threads", "0", "-o", "json")
    assert result.returncode == USAGE, result.stderr
    message = str(error_of(result.stdout)["message"])
    named = _MISSING_ARGUMENT.search(message)
    assert named is not None, f"{verb.name}: the envelope names no missing argument: {message!r}"
    assert named.group(1), message


# --------------------------------------------------------------------------- #
# AC6 — `PdfToolkitError` keeps its precedence, byte for byte.
# --------------------------------------------------------------------------- #

#: Measured at `15eb4ea` (pre-change) and again after, from `pdftoolkit version
#: --out-dir <dir> -o json`. Pinned as BYTES, because AC6 is a byte-identity
#: criterion: it is the guard that the new Click branch did not quietly take
#: over a message OR-3 owns.
_OR3_ENVELOPE: Final[str] = (
    '{"schema_version": 1, "error": {"code": 2, "kind": "usage", "message": '
    '"version does not accept --out-dir (this verb writes no files)", "path": null}}\n'
)


@pytest.mark.e2e
def test_ac6_our_own_error_keeps_precedence_over_the_click_branch(tmp_path: Path) -> None:
    """AC6. Red: match the Click duck-type first and OR-3's message is replaced
    — in fact worse, because our `UsageError` is not a Click exception at all,
    so it would fall through to the re-raise and print a traceback at exit 1."""
    result = run_cli("version", "--out-dir", str(tmp_path), "-o", "json")
    assert result.returncode == USAGE
    assert result.stdout == _OR3_ENVELOPE, result.stdout
    assert result.stderr == ""


# --------------------------------------------------------------------------- #
# AC7 — a genuine bug still prints a traceback and exits 1.
#
# `cli/main.py`'s own header calls that "a signal, not a UX", and converting one
# into a tidy usage error is the single thing this spec must not do.
# --------------------------------------------------------------------------- #

_PLANTED_BUG: Final[str] = (
    "import sys;"
    "from pdf_toolkit.cli import cmd_version;"
    "from pdf_toolkit.cli.main import main;"
    "cmd_version.emit_result = "
    "(lambda *a, **k: (_ for _ in ()).throw(ZeroDivisionError('planted bug')));"
    "sys.argv = ['pdftoolkit', 'version'];"
    "main()"
)


@pytest.mark.e2e
def test_ac7_an_unexpected_exception_keeps_its_traceback_and_exit_1() -> None:
    """AC7. Red: replace the final `raise` with a catch-all envelope — the
    traceback disappears and the exit code becomes 2."""
    result = subprocess.run(  # noqa: S603 - fixed argv, never a shell
        [sys.executable, "-c", _PLANTED_BUG],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 1, f"exit {result.returncode}; stderr={result.stderr[:400]!r}"
    assert "Traceback (most recent call last)" in result.stderr
    assert "ZeroDivisionError" in result.stderr
    assert result.stdout == "", f"a bug is not a payload: {result.stdout!r}"


# --------------------------------------------------------------------------- #
# AC8 / AC9 / AC10 / AC11 — the GROUP position (`a472acde7a`).
#
# All fifteen `GLOBAL_OPTIONS` members exit 2 at `meta` with **zero bytes on
# stdout**. The exit code is correct and stays: `PLAN.md` §5.6 rules that a
# grouping parent is exit 2 (`pdftoolkit meta bogus` is 2, not 0). Only the
# empty stdout changes.
#
# The fix is explicitly NOT `@global_options` on the group. AC11 below is what
# keeps that promise honest against a later engineer: attaching the decorator
# would pollute `_CONSUMES_BY_MODULE` (keyed by module), enrol a group in an
# OR-3 matrix that classifies leaf verbs, and flip `meta -o json` from 2 to 0 —
# overturning `cli/cmd_meta.py:3-6` and `PLAN.md:327` in a single edit.
# --------------------------------------------------------------------------- #

GROUP_FLAG_CASES: Final[tuple[tuple[tuple[str, ...], str], ...]] = tuple(
    (group, flag) for group in GROUPS for flag in GLOBAL_OPTIONS
)


def _group_ids(cases: tuple[tuple[tuple[str, ...], str], ...]) -> list[str]:
    return [f"{' '.join(group)}-{flag}" for group, flag in cases]


@pytest.mark.e2e
@pytest.mark.parametrize(("group", "flag"), GROUP_FLAG_CASES, ids=_group_ids(GROUP_FLAG_CASES))
def test_ac8_ac9_ac10_the_group_position_emits_the_envelope(
    group: tuple[str, ...], flag: str
) -> None:
    """AC8 (envelope), AC9 (exit code unchanged) and AC10 (the message names the
    two working positions), on one invocation each.

    Both dimensions are read at runtime: neither `15` nor `meta` appears as a
    literal anywhere in this module.

    Red for AC8: at `15eb4ea` all fifteen cases give 0 bytes on stdout.
    Red for AC9: make the group accept the block and these exit 0.
    Red for AC10: strip the pointer back to Click's bare `No such option: -o`
    and the position assertions below fail.
    """
    result = run_cli(*group, flag)
    assert result.returncode == USAGE, f"{group} {flag} -> {result.returncode}"
    message = str(error_of(result.stdout)["message"])
    assert "Usage:" not in result.stdout

    group_name = " ".join(group)
    # The two working positions, asserted STRUCTURALLY rather than by restating
    # the sentence: the flag is named before the group somewhere (the
    # before-the-group example) and after it somewhere else (the
    # after-the-subcommand example).
    assert flag in message, message
    assert group_name in message, message
    assert message.index(flag) < message.index(group_name), (
        f"no 'before the group' example in: {message!r}"
    )
    assert message.rindex(flag) > message.rindex(group_name), (
        f"no 'after the subcommand' example in: {message!r}"
    )


@pytest.mark.e2e
def test_ac10_the_ledger_repro_names_both_working_positions_verbatim() -> None:
    """AC10, on `a472acde7a`'s own recorded command line.

    Pre-fix: exit 2, stdout 0 bytes, stderr 117 (`Error: No such option: -o`).
    """
    result = run_cli("meta", "-o", "json")
    assert result.returncode == USAGE
    message = str(error_of(result.stdout)["message"])
    assert f"{PROG_NAME} -o json meta" in message, message
    assert re.search(rf"{PROG_NAME} meta \S+ \.\.\. -o json", message), message


def test_ac10_the_readme_states_the_group_position_rule() -> None:
    """AC10's docs half. `a472acde7a`'s other clause is *"stated in no
    user-facing doc"*; a grep returning zero here fails the arm."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for group in GROUPS:
        name = " ".join(group)
        assert f"pdftoolkit {name} -o json" in readme, (
            f"README states no group-position rule for {name!r}"
        )
    assert "does not take the global block" in readme


def test_ac11_the_group_is_untouched_by_construction() -> None:
    """AC11. The guard that keeps §D6's promise honest against a later engineer.

    Red: add `@global_options(consumes=())` to `meta_app` and BOTH assertions
    fail.
    """
    from pdf_toolkit.cli.common import consumed_output_flags

    assert consumed_output_flags("pdf_toolkit.cli.cmd_meta") == ()
    source = (SRC / "pdf_toolkit" / "cli" / "cmd_meta.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    decorators = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name | ast.Attribute) and _referenced_name(node) == "global_options"
    ]
    assert decorators == [], "cmd_meta.py references global_options"


def _referenced_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def test_the_spelling_index_covers_every_global_spelling() -> None:
    """`GLOBAL_FLAG_SPELLINGS` is what classifies a token Click has already
    refused — a token no bound parameter exists to read the answer off. It is
    DERIVED from `GLOBAL_PARAMS`, and this is the control that stops a
    framework upgrade turning that derivation into an empty mapping, which
    would make every group-position and OR-4 branch silently unreachable while
    the envelope still rendered Click's own wording."""
    assert GLOBAL_FLAG_SPELLINGS, "the spelling index is empty — nothing can be classified"
    for flag in (*GLOBAL_OPTIONS, *REFUSED_PASSWORD_FLAGS):
        assert GLOBAL_FLAG_SPELLINGS.get(flag) == flag, flag
    # The short spellings resolve to their long form, which is what the
    # group-position and OR-4 branches key on.
    assert GLOBAL_FLAG_SPELLINGS.get("-o") == "--output-format"
    assert GLOBAL_FLAG_SPELLINGS.get("--definitely-not-a-flag") is None


def test_ac8_the_group_population_cannot_go_vacuous() -> None:
    """The anti-lapse guard `discover_groups()` needs: it returned `()` for
    eight specs, and a row parametrized over an empty tuple collects zero cases
    and reports green having asserted nothing."""
    assert GROUPS, "discover_groups() is empty — every group-position case is vacuous"
    assert GLOBAL_OPTIONS, "the global block is empty — every case above is vacuous"
    assert len(GROUP_FLAG_CASES) == len(GROUPS) * len(GLOBAL_OPTIONS)


# --------------------------------------------------------------------------- #
# AC12 / AC13 — flags with no command, and no arguments at all.
#
# `76ece64648`. `pdftoolkit -o json` exited **0** with 3754 bytes of human help
# on stdout: a machine consumer reading stdout learned neither that it had
# asked for nothing nor that it had got nothing.
#
# The rule adopted is INVOCATION COMPLETENESS, never output shape (§D7): a
# shape-dependent exit code (0 for `-o table`, 2 for `-o json`) would satisfy
# the row's title too and is refused, because `-o` is documented as a rendering
# choice and an exit code that turns on it is a new surprise.
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
@pytest.mark.parametrize("flag", INCOMPLETE_INVOCATION_FLAGS)
def test_ac12_global_flags_with_no_command_exit_2_and_name_help(flag: str, workspace: Path) -> None:
    """AC12. Red: at `15eb4ea` this exits **0** with 3754 bytes of human help."""
    result = run_cli(*argv_for(flag, workspace))
    assert result.returncode == USAGE, f"{flag} -> {result.returncode}: {result.stdout[:120]!r}"
    message = str(error_of(result.stdout)["message"])
    assert "--help" in message, message
    assert flag in message, message
    assert "Usage:" not in result.stdout


@pytest.mark.e2e
@pytest.mark.parametrize("flag", EAGER_GLOBAL_FLAGS)
def test_ac12_an_eager_flag_with_no_command_still_exits_0(flag: str, workspace: Path) -> None:
    """The other half of the derivation, stated rather than carved out: an eager
    flag exits before the root callback body runs at all, so it is 0 by design.
    Derived from the live parameter's own `is_eager`, so a second eager flag
    joins this arm instead of failing the one above."""
    result = run_cli(*argv_for(flag, workspace))
    assert result.returncode == OK, result.stderr


def test_ac12_the_two_arms_partition_the_block() -> None:
    """Neither arm may quietly lose a flag: together they are exactly the block."""
    assert set(EAGER_GLOBAL_FLAGS) | set(INCOMPLETE_INVOCATION_FLAGS) == set(GLOBAL_OPTIONS)
    assert not set(EAGER_GLOBAL_FLAGS) & set(INCOMPLETE_INVOCATION_FLAGS)
    assert INCOMPLETE_INVOCATION_FLAGS, "every global flag looks eager — the derivation is wrong"


@pytest.mark.e2e
def test_ac13_zero_argument_invocation_keeps_help_and_exit_0_on_a_pipe() -> None:
    """AC13. PRESERVED behaviour, newly pinned: nothing asserted this before, so
    it was unprotected against a later 'fix' extending AC12's rule to it.

    Red: extend the incomplete-invocation rule to the zero-argument case and
    this fails."""
    result = run_cli()
    assert result.returncode == OK
    assert result.stdout.startswith("Usage: pdftoolkit")
    assert "Commands:" in result.stdout


@pytest.mark.e2e
def test_ac13_zero_argument_invocation_keeps_help_and_exit_0_on_a_tty() -> None:
    """AC13's other half — on a real terminal, where `auto_format()` picks
    `table` and a shape-dependent rule would have diverged."""
    result = run_cli_with_pty(pty_stream="stdout")
    assert result.returncode == OK
    assert "Usage: pdftoolkit" in result.stdout


# --------------------------------------------------------------------------- #
# AC14 / AC15 / AC16 / AC17 — the `--flag=VALUE` spelling (`7fc5a169f6`).
#
# Nothing flag-specific is needed for the envelope: `Option '--password' does
# not take a value.` is a Click parser error, so M1's handler closes the entire
# equals-form class in one move. `7fc5a169f6` asks for more than an envelope
# though — it asks for OR-4's pointer message, because `README.md` promises a
# usage error NAMING THE THREE SUPPORTED PATHS and the equals form named none.
#
# THE `7fc5a169f6` REPRO IS RUNNABLE AND ALWAYS WAS. The ledger records it as
# "unrunnable since `--password` was removed"; measured, that is wrong.
# `--password` was removed as an ALIAS of `--password-file`, not as a spelling:
# it is still declared, still parsed and still refuses, as a hidden eager
# boolean (`cli/common.py`'s `REFUSED_PASSWORD_FLAGS`). The repro below is the
# recorded one, not a substitute — X-110 records that substituting a different
# flag previously manufactured a false "stopped reproducing" on this product.
#
# THE CROSS-PRODUCT CAP, and its argument. The full space is 12 boolean-ish
# global spellings x 26 verbs x 3 shapes = 936 subprocesses, which at this
# host's measured ~0.33 s per run is roughly five minutes added to a `make ci`
# already near ten. The cap keeps BOTH dimensions the defect actually varies
# over — every flag, every shape — at one derived verb (36 cases, exactly the
# shape of Evidence §E6's measured 33/33 population), and adds a second derived
# verb at one shape (12 cases) purely to prove the class is not verb-specific.
# The verb dimension is the one the mechanism CANNOT vary over: the failure
# happens inside Click's option parser, before any verb callback is entered, so
# a per-verb sweep would re-measure the same code path 26 times.
# --------------------------------------------------------------------------- #

#: A value that must never appear in any output. Deliberately password-shaped.
NEVER_ECHOED: Final[str] = "hunter2"

#: The members of the global block that take NO value, plus the three OR-4
#: refusals — i.e. exactly the spellings for which `--flag=VALUE` is a parser
#: error. Derived from the live parameters, never typed: §E6 counted eleven by
#: hand and missed `--verbose`, whose `count=True` makes it value-less too.
EQUALS_FORM_FLAGS: Final[tuple[str, ...]] = (
    *(flag for flag in GLOBAL_OPTIONS if not _needs_value(flag)),
    *REFUSED_PASSWORD_FLAGS,
)


def _sampled_verbs(count: int) -> tuple[Any, ...]:
    """*count* verbs, evenly spaced through the live registry — deterministic,
    derived, and never a hand-picked name."""
    if not VERBS:  # pragma: no cover - the population guard below owns this
        return ()
    step = max(1, len(VERBS) // count)
    return tuple(VERBS[index * step] for index in range(count) if index * step < len(VERBS))


SAMPLED_VERBS: Final[tuple[Any, ...]] = _sampled_verbs(2)

EQUALS_FORM_CASES: Final[tuple[tuple[Any, str, OutputFormat], ...]] = (
    *((SAMPLED_VERBS[0], flag, shape) for flag in EQUALS_FORM_FLAGS for shape in SHAPES),
    *((SAMPLED_VERBS[1], flag, OutputFormat.JSON) for flag in EQUALS_FORM_FLAGS),
)


def _equals_ids(cases: tuple[tuple[Any, str, OutputFormat], ...]) -> list[str]:
    return [f"{verb.name}-{flag}-{shape.value}" for verb, flag, shape in cases]


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("verb", "flag", "shape"), EQUALS_FORM_CASES, ids=_equals_ids(EQUALS_FORM_CASES)
)
def test_ac14_ac17_the_equals_form_is_enveloped_and_echoes_nothing(
    verb, flag: str, shape: OutputFormat
) -> None:
    """AC14 + AC17.

    Red for AC14: at `15eb4ea` the equals form gives **0 bytes on stdout** on
    every case (§E6 measured 33/33 at `info`).
    Red for AC17: build the message with the parsed token interpolated and
    every case fails.
    """
    result = run_cli(verb.name, f"{flag}={NEVER_ECHOED}", "-o", shape.value)
    assert result.returncode == USAGE, f"{verb.name} {flag}= -> {result.returncode}"
    assert NEVER_ECHOED not in result.stdout, "the value was echoed on stdout"
    assert NEVER_ECHOED not in result.stderr, "the value was echoed on stderr"
    if shape is OutputFormat.TABLE:
        assert result.stdout == ""
        assert result.stderr.startswith("error: ")
        return
    error = error_of(result.stdout)
    assert error["code"] == USAGE
    assert error["kind"] == "usage"
    assert "Usage:" not in result.stdout


def test_ac14_the_equals_form_population_is_derived_and_capped_with_an_argument() -> None:
    """The cap is a decision, so it is asserted rather than left implicit."""
    assert EQUALS_FORM_FLAGS, "no value-less global flag was derived — the sweep is vacuous"
    assert set(REFUSED_PASSWORD_FLAGS) <= set(EQUALS_FORM_FLAGS)
    assert len(SAMPLED_VERBS) == 2, SAMPLED_VERBS
    assert SAMPLED_VERBS[0].name != SAMPLED_VERBS[1].name
    assert len(EQUALS_FORM_CASES) == len(EQUALS_FORM_FLAGS) * (len(SHAPES) + 1)


@pytest.mark.e2e
@pytest.mark.parametrize("flag", REFUSED_PASSWORD_FLAGS)
@pytest.mark.parametrize("verbosity", [[], ["-vv"]], ids=["default", "vv"])
def test_ac15_ac17_the_refused_password_flags_carry_or4s_pointer(
    flag: str, verbosity: list[str]
) -> None:
    """AC15 + AC17, on `7fc5a169f6`'s OWN recorded repro shape.

    The flag list is read from `REFUSED_PASSWORD_FLAGS`, so removing
    `--password` SHRINKS this population instead of making the test unrunnable
    — which is the whole point: the row was frozen for two sweeps because it
    was pinned to a flag name rather than to the mechanism.

    Red: revert to Click's bare `does not take a value` and the three-paths
    assertions fail on all three flags.
    """
    verb = SAMPLED_VERBS[0]
    result = run_cli(verb.name, f"{flag}={NEVER_ECHOED}", *verbosity, "-o", "json")
    assert result.returncode == USAGE
    assert NEVER_ECHOED not in result.stdout
    assert NEVER_ECHOED not in result.stderr
    message = str(error_of(result.stdout)["message"])
    assert flag in message, message
    for token in readme_password_tokens():
        assert token in message, f"{flag}: the envelope does not name {token!r}: {message!r}"


# --------------------------------------------------------------------------- #
# AC16 — `README.md`'s three-spellings claim, made true MECHANICALLY.
#
# The claim was live and false: "Passing any of those three spellings is a
# usage error (exit 2) naming the three supported paths" — the equals form
# exited 2 and named NONE of them.
# --------------------------------------------------------------------------- #

_TABLE_ROW = re.compile(r"^\|(?P<path>[^|]+)\|(?P<spelling>[^|]+)\|", re.MULTILINE)


def readme_password_section() -> str:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index("## Encryption, passwords and permissions")
    end = text.index("\n## ", start + 1)
    return text[start:end]


#: The claim `README.md` makes and this spec has to make true. The table below
#: it is parsed relative to THIS sentence, not from the top of the section, so
#: an unrelated table elsewhere in the section can never stand in for it.
_README_CLAIM: Final[str] = "naming the three supported paths"

#: A password FILE flag, an ENVIRONMENT variable, and the stdin dash. Matched by
#: KIND rather than by row position: the first version of this helper read
#: `rows[0]`, `rows[1]`, `rows[2]`, which meant a reordered table silently
#: pointed the assertions at the wrong cells — and a `PATH` metavar inside
#: `--password-file PATH` matched a naive all-caps pattern before the real
#: environment variable did. The env pattern requires an underscore for that
#: reason: every environment name this product publishes is SCREAMING_SNAKE.
_README_FILE_FLAG = re.compile(r"--[a-z-]+-file\b")
_README_ENV_NAME = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
_README_STDIN = "`-`"


def readme_password_rows() -> tuple[tuple[str, str], ...]:
    """The claim's OWN table: `(Path, Spelling)` per data row."""
    section = readme_password_section()
    assert _README_CLAIM in section, (
        f"README no longer carries the claim {_README_CLAIM!r} — AC16 has nothing to hold "
        "the message against, and would otherwise pass having read nothing"
    )
    block = section[section.index(_README_CLAIM) :]
    rows: list[tuple[str, str]] = []
    for match in _TABLE_ROW.finditer(block):
        path = match.group("path").strip()
        spelling = match.group("spelling").strip()
        if path == "Path" or set(path) <= set("- "):
            continue
        rows.append((path, spelling))
    return tuple(rows)


def readme_password_tokens() -> tuple[str, ...]:
    """The three supported paths, READ OUT OF THE README rather than restated.

    A deletion of the table — or of the claim sentence above it — fails on the
    parse below, loudly, rather than turning this criterion into a green that
    asserts nothing.
    """
    rows = readme_password_rows()
    assert len(rows) >= 3, (
        f"README's password-paths table has {len(rows)} data row(s) after the claim: {rows}"
    )
    spellings = [spelling for _, spelling in rows]
    file_flag = next(
        (m.group(0) for s in spellings for m in [_README_FILE_FLAG.search(s)] if m), ""
    )
    env_name = next((m.group(0) for s in spellings for m in [_README_ENV_NAME.search(s)] if m), "")
    assert file_flag, f"no password-file flag anywhere in the table: {rows}"
    assert env_name, f"no environment variable anywhere in the table: {rows}"
    assert any(_README_STDIN in s for s in spellings), f"no stdin dash in the table: {rows}"
    return (file_flag, env_name, "stdin")


def test_ac16_the_readme_claim_and_the_message_agree() -> None:
    """AC16. Red: soften the message and this fails; delete the README table and
    it fails on the read, not silently."""
    section = readme_password_section()
    assert "naming the three supported paths" in section
    tokens = readme_password_tokens()
    assert len(tokens) == 3
    assert tokens[0].startswith("--")


@pytest.mark.e2e
def test_ac16_the_readme_claim_holds_for_both_spellings_of_the_value_form() -> None:
    """The separated form was already correct; the joined one was the defect.
    Both are asserted here so the README sentence is true of what it claims."""
    tokens = readme_password_tokens()
    for spelling in (
        ["--password", NEVER_ECHOED],
        [f"--password={NEVER_ECHOED}"],
    ):
        result = run_cli(SAMPLED_VERBS[0].name, *spelling, "-o", "json")
        assert result.returncode == USAGE, spelling
        message = str(error_of(result.stdout)["message"])
        for token in tokens:
            assert token in message, f"{spelling}: {token!r} missing from {message!r}"
        assert NEVER_ECHOED not in result.stdout
        assert NEVER_ECHOED not in result.stderr


# --------------------------------------------------------------------------- #
# AC18 — `--quiet` and the ROOT logger (`d220b7d79d`).
#
# `pypdf/_reader.py` calls `logging.getLogger("pypdf._reader").warning("EOF
# marker not found")`. `configure_logging` configured ONLY the `pdf_toolkit`
# logger, so that record propagated to root, found zero handlers there, and was
# emitted by `logging.lastResort` — a handler this process never installed and
# therefore never levelled. Two consequences, and the second is not in the row:
# the chatter ignored `--quiet`, and it bypassed `RedactingFilter` entirely.
#
# THE OPERAND IS `testdata/malformed.pdf` AND IS NOT SUBSTITUTED (X-110).
# --------------------------------------------------------------------------- #

CHATTER: Final[str] = "EOF marker not found"


@pytest.fixture
def restored_logging():
    """Snapshot and restore both loggers — `configure_logging` now owns root,
    and a test that left our handler on it would leak into every later test."""
    import logging as _logging

    from pdf_toolkit.output.logging import LOGGER_NAME, clear_secrets

    root = _logging.getLogger()
    ours = _logging.getLogger(LOGGER_NAME)
    saved = (
        list(root.handlers),
        root.level,
        list(ours.handlers),
        list(ours.filters),
        ours.level,
        ours.propagate,
    )
    try:
        yield
    finally:
        root.handlers[:] = saved[0]
        root.setLevel(saved[1])
        ours.handlers[:] = saved[2]
        ours.filters[:] = saved[3]
        ours.setLevel(saved[4])
        ours.propagate = saved[5]
        clear_secrets()


@pytest.mark.e2e
@pytest.mark.parametrize("verb", ["rasterize", "info"])
def test_ac18_quiet_suppresses_engine_chatter_on_the_recorded_operand(verb: str) -> None:
    """AC18. Red: revert the root-logger takeover and the chatter reappears
    under `--quiet` (measured pre-fix: 21 bytes on `rasterize`, 162 on `info`,
    identical with and without the flag)."""
    loud = run_cli(verb, str(MALFORMED), "-o", "json")
    quiet = run_cli(verb, "--quiet", str(MALFORMED), "-o", "json")

    assert CHATTER in loud.stderr, "the chatter is not reproducible — the operand changed"
    assert f"WARNING: {CHATTER}" in loud.stderr, (
        f"a third-party record is not going through our formatter: {loud.stderr!r}"
    )
    assert CHATTER not in quiet.stderr, f"--quiet did not suppress it: {quiet.stderr!r}"
    assert quiet.stdout == loud.stdout, "the stdout envelope must be unchanged by --quiet"
    assert quiet.returncode == loud.returncode


def test_ac18_a_third_party_record_passes_through_the_redacting_filter(
    restored_logging, capsys: pytest.CaptureFixture[str]
) -> None:
    """The half that is NOT in `d220b7d79d`, closed as a by-product and named so
    it is not mistaken for a new finding: before this change no third-party
    record went through `RedactingFilter` at all, so `output/logging.py`'s
    redaction guarantee covered none of them."""
    import logging as _logging

    from pdf_toolkit.output.logging import (
        REDACTION_PLACEHOLDER,
        configure_logging,
        register_secret,
    )

    register_secret(NEVER_ECHOED)
    configure_logging(verbose=0, quiet=False, no_color=True)
    _logging.getLogger("pypdf._reader").warning("a third-party record with %s in it", NEVER_ECHOED)
    captured = capsys.readouterr()
    assert NEVER_ECHOED not in captured.err, captured.err
    assert REDACTION_PLACEHOLDER in captured.err, captured.err
    assert captured.err.startswith("WARNING: "), captured.err
    assert captured.out == "", "nothing but the payload may reach stdout"


def test_ac18_quiet_levels_the_root_logger_too(
    restored_logging, capsys: pytest.CaptureFixture[str]
) -> None:
    """The mechanism, in isolation from any document: under `--quiet` a
    third-party WARNING is below the level root now carries."""
    import logging as _logging

    from pdf_toolkit.output.logging import configure_logging

    configure_logging(verbose=0, quiet=True, no_color=True)
    _logging.getLogger("pypdf._reader").warning(CHATTER)
    assert capsys.readouterr().err == ""


# --------------------------------------------------------------------------- #
# AC19 — the HUMAN path keeps its pointer.
#
# Routing through `emit_error()` replaces Click's 120-byte two-line stderr with
# our 38-byte one-liner. That is a UX regression and it is not acceptable, so
# the `-o table` rendering keeps a `Try '<command> --help' for help.` pointer.
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
def test_ac19_the_table_shape_keeps_a_help_pointer() -> None:
    """AC19. Red: emit only `error: <message>` and this fails."""
    result = run_cli("info", UNKNOWN_FLAG, "-o", "table")
    assert result.returncode == USAGE
    assert result.stdout == ""
    assert "--help" in result.stderr, result.stderr
    assert result.stderr.startswith("error: "), result.stderr


@pytest.mark.e2e
def test_ac19_a_structured_shape_keeps_stderr_clean() -> None:
    """The pointer is a HUMAN affordance: under a structured shape stdout
    carries the envelope and stderr carries nothing at all."""
    result = run_cli("info", UNKNOWN_FLAG, "-o", "json")
    assert result.stderr == "", result.stderr
    assert "--help" not in result.stdout


# --------------------------------------------------------------------------- #
# AC21 — no `click`, no private framework import, no dependency change.
#
# `import click` FAILS in this environment (the CLI framework vendors Click
# privately and there is no top-level distribution), adding one is forbidden by
# the dependency freeze, and a private `typer._click` import is a hidden
# coupling to a vendoring decision `cli/common.py` already refused once on the
# record. The classification is DUCK-TYPED instead.
# --------------------------------------------------------------------------- #

_PRIVATE_VENDORED = re.compile(r"typer\._click")


def _source_files() -> tuple[Path, ...]:
    return tuple(sorted(SRC.rglob("*.py")))


def test_ac21_no_source_file_imports_click_or_the_private_vendored_copy() -> None:
    """AC21. Red: add `import typer._click` anywhere under `src/` and this
    fails. (`import click` cannot even be planted — it raises
    `ModuleNotFoundError` at runtime.)"""
    files = _source_files()
    assert files, "the source scan found no files — it is not measuring anything"
    offenders: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Import):
                offenders.extend(
                    f"{path.name}: import {alias.name}"
                    for alias in node.names
                    if alias.name == "click" or alias.name.startswith("click.")
                )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "click" or module.startswith("click."):
                    offenders.append(f"{path.name}: from {module} import ...")
                if "_click" in module:
                    offenders.append(f"{path.name}: from {module} import ...")
        for match in _PRIVATE_VENDORED.finditer(text):
            offenders.append(f"{path.name}: {match.group(0)}")
    assert offenders == [], offenders


def test_ac21_click_is_not_a_declared_dependency() -> None:
    """The dependency half. The lockfile and both licence artifacts are
    generated from this list and CI-diffs them, so a new runtime dependency
    surfaces as a website defect on an unrelated commit."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    start = text.index("dependencies = [")
    block = text[start : text.index("]", start)]
    assert "click" not in block, block


def test_ac21_importing_click_really_does_fail() -> None:
    """The positive control for the negative claim above."""
    with pytest.raises(ModuleNotFoundError):
        __import__("click")


# --------------------------------------------------------------------------- #
# Every derived population in this module, pinned — `tests/test_cli_contract.py`
# `POPULATIONS` idiom, for its own reason: `discover_groups()` returned `()` for
# eight specs, and a row parametrized over an empty tuple collects zero cases
# and reports GREEN having asserted nothing.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Population:
    name: str
    members: tuple
    checks: str
    minimum: int
    why: str


POPULATIONS: Final[tuple[Population, ...]] = (
    Population(
        "VERBS", VERBS, "AC1,AC3,AC4,AC14", 1, "the root population; zero empties the sweep"
    ),
    Population(
        "GROUPS",
        GROUPS,
        "AC8,AC9,AC10",
        1,
        "`discover_groups()` returned () for eight specs. NECESSARY BUT NOT SUFFICIENT: one "
        "element passes an emptiness pin while being one refactor from vacuity, so the real "
        "guarantee is the derivation, not this",
    ),
    Population("SHAPES", SHAPES, "AC3,AC14", 3, "all three shapes; AC3's red is losing one"),
    Population(
        "STRUCTURED_SHAPES",
        STRUCTURED_SHAPES,
        "AC1,AC20",
        1,
        "the shapes that put the envelope on stdout; empty makes every stdout assertion vacuous",
    ),
    Population(
        "GLOBAL_OPTIONS",
        GLOBAL_OPTIONS,
        "AC8,AC12",
        1,
        "IMPORTED from the product; empty "
        "makes both the group sweep and the incomplete-invocation sweep collect zero cases",
    ),
    Population(
        "REFUSED_PASSWORD_FLAGS",
        REFUSED_PASSWORD_FLAGS,
        "AC15,AC17",
        1,
        "IMPORTED. `7fc5a169f6` is re-pinned to this tuple ON PURPOSE: removing `--password` "
        "must SHRINK the population, never make the row unrunnable again",
    ),
    Population(
        "EAGER_GLOBAL_FLAGS",
        EAGER_GLOBAL_FLAGS,
        "AC12 (the exits-0 arm)",
        1,
        "derived from the live parameter's `is_eager`; empty would silently move `--version` "
        "into the exit-2 arm and fail there instead of here",
    ),
    Population(
        "INCOMPLETE_INVOCATION_FLAGS",
        INCOMPLETE_INVOCATION_FLAGS,
        "AC12 (the exits-2 arm)",
        1,
        "empty makes `76ece64648`'s whole criterion collect zero cases",
    ),
    Population(
        "EQUALS_FORM_FLAGS",
        EQUALS_FORM_FLAGS,
        "AC14,AC17",
        1,
        "derived from `_needs_value`; §E6 counted eleven BY HAND and missed `--verbose`",
    ),
    Population(
        "SAMPLED_VERBS",
        SAMPLED_VERBS,
        "AC14,AC15,AC16",
        2,
        "the AC14 cap's own sample; "
        "below two, the 'not verb-specific' half of the argument stops being measured",
    ),
    Population(
        "REQUIRED_ARGUMENT_VERBS",
        REQUIRED_ARGUMENT_VERBS,
        "AC4",
        1,
        "derived from the live commands' own required arguments; empty makes E4's arity shape "
        "— the evidence that decided the PLACEMENT — untested",
    ),
    Population(
        "REACHABLE_CODES",
        REACHABLE_CODES,
        "AC5",
        1,
        "empty makes the exit matrix's coverage assertion compare two empty sets",
    ),
    Population(
        "RETURN_SIGNALLED_CODES",
        RETURN_SIGNALLED_CODES,
        "AC5's red",
        1,
        "empty makes the planted-defect control assert that nothing was zeroed, which is "
        "exactly the green-that-asserts-nothing shape this spec exists to end",
    ),
    Population(
        "UNKNOWN_FLAG_CASES",
        UNKNOWN_FLAG_CASES,
        "AC1,AC3",
        1,
        "the VERBS x SHAPES cross-product; zero takes the headline criterion down whole",
    ),
    Population(
        "GROUP_FLAG_CASES",
        GROUP_FLAG_CASES,
        "AC8,AC9,AC10",
        1,
        "the GROUPS x GLOBAL_OPTIONS cross-product",
    ),
    Population("EQUALS_FORM_CASES", EQUALS_FORM_CASES, "AC14,AC17", 1, "the capped cross-product"),
)


@pytest.mark.parametrize("population", POPULATIONS, ids=[row.name for row in POPULATIONS])
def test_every_population_is_non_empty(population: Population) -> None:
    assert len(population.members) >= population.minimum, (
        f"{population.name} has {len(population.members)} member(s), below its floor of "
        f"{population.minimum} — the check(s) it feeds ({population.checks}) would then collect "
        f"zero parametrized cases and report GREEN having asserted nothing. "
        f"Why this floor: {population.why}"
    )


def test_a_population_pin_fires() -> None:
    """The pin is an instrument only if it can fail."""
    emptied = Population("EMPTIED", (), "nothing", 1, "a deliberate zero")
    with pytest.raises(AssertionError, match="below its floor"):
        test_every_population_is_non_empty(emptied)
