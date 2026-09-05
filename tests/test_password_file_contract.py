"""PDF-37 -- the derived, three-arm `--password-file` contract probe.

D5: parameterizes over `registry.discover_verbs()` (never a list written in
this file), runs each verb's OWN registered `INVOCATIONS[verb].build(...)`
argv against the `encrypted_aes256` corpus fixture (via the SAME
`_EncryptedOperandProxy`/`_strip_password_file_flags` apparatus
`tests/test_password_leaks.py`'s witness already built and PDF-22 proved
correct -- consumed here, not rebuilt), three arms per verb (no password /
correct password / wrong password), reading BOTH X-185 observables (the
exit code AND the rendered envelope's `message`) -- an exit-code-only
control passed on 10 of 11 verbs of a deliberately broken binary (X-206),
so this file never asserts on `returncode` alone.

D1's partition: every one of the 26 derived verbs lands in exactly HONOURED
or REFUSED, with an empty residual (`SILENTLY_IGNORED == set()`, asserted,
never inferred -- AC4). D4's structural predicate
(`pdf_toolkit.cli.common.honours_password_file`) is reconciled against this
BEHAVIOURAL result: the two instruments are independent on purpose, and a
disagreement is a BLOCKER (D4.3), never a tie broken here.
"""

from __future__ import annotations

import ast
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pytest

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import (  # noqa: E402
    INVOCATIONS,
    _module_dotted_name,
    discover_verbs,
    run_cli,
)
from test_password_leaks import (  # noqa: E402
    _clean_env,
    _EncryptedOperandProxy,
    _strip_password_file_flags,
)

REPO_ROOT: Final[Path] = TESTS_DIR.parent
SRC: Final[Path] = REPO_ROOT / "src" / "pdf_toolkit"

#: E2's expected partition, re-derived at HEAD and reconciled against the
#: BEHAVIOURAL probe below (AC1). Published beside the count, never trusted
#: bare (X-245/X-420).
EXPECTED_REFUSED: Final[frozenset[str]] = frozenset(
    {"compose", "convert", "create", "doctor", "encrypt", "version"}
)

_WRONG_PASSWORD: Final[str] = "pdf-37-contract-wrong-password"


# --------------------------------------------------------------------------- #
# AC1 -- the population, derived three ways, required to agree.
# --------------------------------------------------------------------------- #


def _recipe_a_leaf_registrations() -> int:
    main_py = (SRC / "cli" / "main.py").read_text()
    tree = ast.parse(main_py)
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # `app.command(name="...")` or `cmd_meta.meta_app.command(name="...")`
        if isinstance(func, ast.Attribute) and func.attr == "command":
            for keyword in node.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    count += 1
    return count


def _recipe_b_global_options_decorators() -> int:
    total = 0
    for path in sorted((SRC / "cli").glob("cmd_*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "global_options":
                continue
            # Only decorator-position calls, i.e. immediately preceding a
            # function def in the AST's own `decorator_list`.
            total += 1
    # Every `@global_options(consumes=...)` call in a `cmd_*.py` module is a
    # decorator on exactly one verb function; a module with more than one
    # such call would itself be an OR-3 violation this recipe would surface
    # as a mismatch against recipe C.
    return total


def test_ac1_the_population_is_derived_three_ways_and_they_agree() -> None:
    """Recipes A, B and C (E1), run at HEAD and published beside the count.
    C (`discover_verbs()`) is the authority every other criterion in this
    file binds to; A and B are static cross-checks that make a drifted C
    visible rather than trusted bare."""
    recipe_a = _recipe_a_leaf_registrations()
    recipe_b = _recipe_b_global_options_decorators()
    recipe_c = len(discover_verbs())
    assert recipe_a == recipe_b == recipe_c == 26, (
        f"the three population recipes disagree or drifted from 26: "
        f"A(leaf registrations)={recipe_a}, B(@global_options sites)={recipe_b}, "
        f"C(discover_verbs)={recipe_c}"
    )


# --------------------------------------------------------------------------- #
# AC2 -- no hand-typed verb list decides the classification.
# --------------------------------------------------------------------------- #


def _verb_name_literals() -> frozenset[str]:
    return frozenset(verb.name for verb in discover_verbs())


def _string_constants_compared_to_verb_names(path: Path, verb_names: frozenset[str]) -> list[str]:
    """Every `ast.Compare` in *path* with `Eq`/`NotEq` against a string
    constant that is ALSO a derived verb name -- the shape
    `if verb == "info":` takes, generalized to catch any variable name
    compared against a verb-name literal, not just one spelled `verb`."""
    offenders: list[str] = []
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        for operand in operands:
            if (
                isinstance(operand, ast.Constant)
                and isinstance(operand.value, str)
                and operand.value in verb_names
            ):
                offenders.append(f"{path}:{node.lineno}: literal {operand.value!r}")
    return offenders


def test_ac2_no_hand_typed_verb_list_decides_the_classification() -> None:
    """A test asserts that no `src/pdf_toolkit/**` module contains a literal
    verb name used as a password-classification key. RED control: planting
    `if verb == "info":` anywhere under `src/` must fail this test naming
    the file and line -- proved by the positive control below, against a
    scratch copy, never against the real tree."""
    verb_names = _verb_name_literals()
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        offenders.extend(_string_constants_compared_to_verb_names(path, verb_names))
    assert not offenders, (
        "a literal verb name is used as a comparison key under src/pdf_toolkit/ "
        f"(a hand-typed classification key, forbidden by AC2): {offenders}"
    )


def test_ac2_the_scan_is_not_vacuous(tmp_path: Path) -> None:
    """Positive control: a planted `if verb == "info":` in a SCRATCH copy
    (never the real tree, HC-4) is detected by the exact same scanner."""
    verb_names = _verb_name_literals()
    assert "info" in verb_names
    planted = tmp_path / "planted.py"
    planted.write_text('def f(verb):\n    if verb == "info":\n        return True\n')
    offenders = _string_constants_compared_to_verb_names(planted, verb_names)
    assert offenders, "the scanner failed to catch its own planted violation"


# --------------------------------------------------------------------------- #
# The three-arm probe -- derived population, both X-185 observables.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _ArmResult:
    exit_code: int
    message: str | None
    raw_stdout: str
    raw_stderr: str


@dataclass(frozen=True)
class _ThreeArms:
    verb: str
    no_password: _ArmResult
    correct: _ArmResult
    wrong: _ArmResult


def _envelope_message(stdout: str) -> str | None:
    """The rendered `message`, from whichever shape `-o json` produced --
    an `OperationResult`-style `items[0].message`, a bespoke top-level
    report (`meta get`/`info`), or an `error.message`. `None` when nothing
    parses (never silently coerced to a string that could mask a real
    parsing failure)."""
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    items = payload.get("items")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        message = items[0].get("message")
        if isinstance(message, str):
            return message
    documents = payload.get("documents")
    if isinstance(documents, list) and documents and isinstance(documents[0], dict):
        doc_error = documents[0].get("error")
        if isinstance(doc_error, dict) and isinstance(doc_error.get("message"), str):
            return doc_error["message"]
    return None


def _run_arm(verb: str, argv: list[str], *, password_path: str | None) -> _ArmResult:
    tail = list(argv)
    if password_path is not None:
        tail = [*tail, "--password-file", password_path]
    result = run_cli(verb, *tail, "-o", "json", env=_clean_env())
    return _ArmResult(
        exit_code=result.returncode,
        message=_envelope_message(result.stdout),
        raw_stdout=result.stdout,
        raw_stderr=result.stderr,
    )


@pytest.fixture(scope="module")
def three_arm_probe(corpus: Any, tmp_path_factory: pytest.TempPathFactory) -> dict[str, _ThreeArms]:
    """One probe per verb in `INVOCATIONS`, THREE conditions each (no
    password / correct password / wrong password), built from each verb's
    OWN registered invocation via `_EncryptedOperandProxy` -- never a
    hand-assembled argv (E2's own warning). Dispatched across a small
    thread pool, same reasoning `test_password_leaks.py`'s own witness
    fixture already uses (I/O-bound subprocess wait, GIL released, disjoint
    tmp_path_factory subdirectories per arm)."""
    from corpus import ENCRYPTED_PASSWORD

    proxy = _EncryptedOperandProxy(corpus.path("encrypted_aes256"))
    root = tmp_path_factory.mktemp("pdf37-contract")
    pw_correct = root / "pw-correct.txt"
    pw_correct.write_text(ENCRYPTED_PASSWORD, encoding="utf-8")
    pw_correct.chmod(0o600)
    pw_wrong = root / "pw-wrong.txt"
    pw_wrong.write_text(_WRONG_PASSWORD, encoding="utf-8")
    pw_wrong.chmod(0o600)

    def _probe(verb: str) -> tuple[str, _ThreeArms]:
        verb_dir = root / verb.replace(" ", "_")
        verb_dir.mkdir()

        no_pw_dir = verb_dir / "no-pw"
        no_pw_dir.mkdir()
        no_pw_argv = _strip_password_file_flags(INVOCATIONS[verb].build(proxy, no_pw_dir))
        no_pw = _run_arm(verb, no_pw_argv, password_path=None)

        correct_dir = verb_dir / "correct"
        correct_dir.mkdir()
        correct_argv = _strip_password_file_flags(INVOCATIONS[verb].build(proxy, correct_dir))
        correct = _run_arm(verb, correct_argv, password_path=str(pw_correct))

        wrong_dir = verb_dir / "wrong"
        wrong_dir.mkdir()
        wrong_argv = _strip_password_file_flags(INVOCATIONS[verb].build(proxy, wrong_dir))
        wrong = _run_arm(verb, wrong_argv, password_path=str(pw_wrong))

        return verb, _ThreeArms(verb=verb, no_password=no_pw, correct=correct, wrong=wrong)

    verbs = sorted(INVOCATIONS)
    with ThreadPoolExecutor(max_workers=min(8, len(verbs))) as pool:
        observations = dict(pool.map(_probe, verbs))
    return observations


def _classify(arms: _ThreeArms) -> str:
    """D1's two-class partition, MECHANICAL: HONOURED iff correct succeeds
    (0) while wrong and no-password are both refused (6); REFUSED iff the
    correct- and wrong-password arms (the two that actually GIVE the flag)
    both exit 2 with an identical message. Anything else is UNCLASSIFIED --
    a named failure, never a silent skip (registry.py's own `expectation()`
    idiom, generalized).

    The `no_password` arm has the flag OMITTED entirely
    (`_strip_password_file_flags`), so for a REFUSED verb it is NOT
    asserted to be 2 here -- there is nothing to refuse when the flag was
    never given; that arm runs the verb's own ordinary, flag-independent
    path (`doctor`/`version` succeed; `encrypt` against an already-encrypted
    operand still exits 5, unrelated to `--password-file`). D2.4's
    ordering (`--password-file` refused before its own shape is even
    checked) is asserted separately, in
    `test_ac7_d24_ordering_bad_path_says_does_not_accept_not_unreadable`.

    Exit-code pattern ONLY for HONOURED, matching
    `test_password_leaks.py`'s own shipped `_witness_classify` methodology
    (and the roadmap/ledger's OWN `5ff60a280e` evidence, which established
    `decrypt`/`permissions` as HONOURED via "6 / 0 / 6" alone).
    Message-level distinguishability (AC6) is asserted SEPARATELY, over
    this same HONOURED population, so a verb that fails it is a named,
    visible test failure rather than a silently narrower classification
    signature.
    """
    if (
        arms.no_password.exit_code == 6
        and arms.correct.exit_code == 0
        and arms.wrong.exit_code == 6
    ):
        return "HONOURED"
    if (
        arms.correct.exit_code == 2
        and arms.wrong.exit_code == 2
        and arms.correct.message == arms.wrong.message
    ):
        return "REFUSED"
    return "UNCLASSIFIED"


def _classes(probe: dict[str, _ThreeArms]) -> dict[str, str]:
    return {verb: _classify(arms) for verb, arms in probe.items()}


# --------------------------------------------------------------------------- #
# AC3/AC4 -- the partition, with an EMPTY residual, asserted not inferred.
# --------------------------------------------------------------------------- #


def test_ac3_every_verb_lands_in_exactly_one_of_honoured_or_refused(
    three_arm_probe: dict[str, _ThreeArms],
) -> None:
    classes = _classes(three_arm_probe)
    unclassified = {
        verb: three_arm_probe[verb] for verb, cls in classes.items() if cls == "UNCLASSIFIED"
    }
    unclassified_arms = {
        verb: (arms.no_password.exit_code, arms.correct.exit_code, arms.wrong.exit_code)
        for verb, arms in unclassified.items()
    }
    assert not unclassified, (
        f"the following verb(s) matched NEITHER the HONOURED nor the REFUSED signature "
        f"(a named failure, never a silent skip): {unclassified_arms}"
    )
    honoured = {verb for verb, cls in classes.items() if cls == "HONOURED"}
    refused = {verb for verb, cls in classes.items() if cls == "REFUSED"}
    assert honoured & refused == set()
    assert honoured | refused == set(three_arm_probe)


def test_ac4_silently_ignored_is_the_empty_set_asserted_not_inferred(
    three_arm_probe: dict[str, _ThreeArms],
) -> None:
    """The class this whole spec exists to empty. Computed the SAME way the
    defect used to be observed: ALL THREE arms identical (exit 6, the SAME
    byte-for-byte message) -- correct is NOT distinguished from wrong or
    from no-password at all, the signature `test_password_leaks.py`'s
    original witness called SILENTLY_IGNORED. Asserted `== set()`, with the
    offending verbs and their three arms printed on failure."""
    silently_ignored = {
        verb: arms
        for verb, arms in three_arm_probe.items()
        if arms.no_password.exit_code == 6
        and arms.correct.exit_code == 6
        and arms.wrong.exit_code == 6
        and arms.no_password.message == arms.correct.message == arms.wrong.message
    }
    assert silently_ignored == {}, (
        f"SILENTLY_IGNORED is not empty -- the defect this spec exists to close is still "
        f"present on: {sorted(silently_ignored)}"
    )


# --------------------------------------------------------------------------- #
# D4.3 -- the structural predicate reconciled against the behavioural probe.
# --------------------------------------------------------------------------- #


def _verb_module_map() -> dict[str, str | None]:
    """The SAME traversal `registry.discover_verbs()` uses internally, read
    here only to recover each verb's own callback module -- `VerbSpec`
    itself does not carry it, and this file must not modify that shared
    dataclass just to add a field only this test needs."""
    import typer

    from pdf_toolkit.cli.main import app

    mapping: dict[str, str | None] = {}

    def _walk(cmd: object, path: tuple[str, ...]) -> None:
        commands = getattr(cmd, "commands", None)
        if commands is not None:
            for name in sorted(commands):
                _walk(commands[name], (*path, name))
            return
        mapping[" ".join(path)] = _module_dotted_name(cmd)

    _walk(typer.main.get_command(app), ())
    return mapping


def test_ac1_the_structural_predicate_agrees_with_the_behavioural_probe(
    three_arm_probe: dict[str, _ThreeArms],
) -> None:
    """D4.3: the structural signal (`honours_password_file`, derived from
    source) and the behavioural probe (this file, derived from a live
    binary) are independent instruments on purpose. A disagreement is a
    BLOCKER, never a tie broken here -- so this assertion's failure message
    names exactly which verb(s) disagree and how, for escalation."""
    from pdf_toolkit.cli.common import honours_password_file

    module_by_verb = _verb_module_map()
    classes = _classes(three_arm_probe)

    structural_honoured: set[str] = set()
    for verb, module in module_by_verb.items():
        if module is not None and honours_password_file(module):
            structural_honoured.add(verb)

    behavioural_honoured = {verb for verb, cls in classes.items() if cls == "HONOURED"}
    disagreement = structural_honoured.symmetric_difference(behavioural_honoured)
    assert not disagreement, (
        f"BLOCKER: the structural predicate and the behavioural probe disagree on "
        f"{sorted(disagreement)} -- structural HONOURED={sorted(structural_honoured)}, "
        f"behavioural HONOURED={sorted(behavioural_honoured)}"
    )
    assert behavioural_honoured == set(INVOCATIONS) - EXPECTED_REFUSED, (
        f"the measured HONOURED set does not match E2's expected population. "
        f"measured={sorted(behavioural_honoured)}, "
        f"expected={sorted(set(INVOCATIONS) - EXPECTED_REFUSED)}"
    )


def test_module_source_returns_none_when_getsourcefile_raises_type_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_module_source`'s C-extension-module guard, exercised directly rather
    than left under a pragma: `inspect.getsourcefile` raises `TypeError` for
    a module with no discoverable Python source (a built-in or a C
    extension) -- never true for anything under `pdf_toolkit.*` today, but
    the helper must still answer "cannot classify" rather than propagate,
    since it runs on every real CLI invocation via `honours_password_file`.
    """
    import inspect as inspect_module

    from pdf_toolkit.cli import common

    def _raises_type_error(_module: object) -> str:
        raise TypeError("builtin module has no __file__")

    monkeypatch.setattr(inspect_module, "getsourcefile", _raises_type_error)
    assert common._module_source("pdf_toolkit.cli.password") is None


def test_module_source_returns_none_when_the_source_file_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_module_source`'s vanished-file guard: the source path resolved but
    reading it raised `OSError` (deleted/permission-changed after the
    module finished importing). "Cannot classify" is the correct answer
    here too, not a crash on an otherwise-normal invocation.
    """
    from pathlib import Path

    from pdf_toolkit.cli import common

    def _raises_os_error(_self: Path, *, encoding: str | None = None) -> str:
        raise OSError("file vanished after import")

    monkeypatch.setattr(Path, "read_text", _raises_os_error)
    assert common._module_source("pdf_toolkit.cli.password") is None


# --------------------------------------------------------------------------- #
# AC5/AC6 -- distinguishability, on both observables, over the HONOURED set.
# --------------------------------------------------------------------------- #


def _honoured_verbs(probe: dict[str, _ThreeArms]) -> list[str]:
    return sorted(verb for verb, cls in _classes(probe).items() if cls == "HONOURED")


def test_ac5_on_every_honoured_verb_correct_and_wrong_differ_in_exit_code(
    three_arm_probe: dict[str, _ThreeArms],
) -> None:
    """Correct -> 0; wrong -> 6. Asserted per verb over the DERIVED
    population, not a list written in this file. This is the criterion the
    ledger's own third arm exists to make possible: "correct -> 0" alone
    cannot separate honouring from merely accepting a file -- this asserts
    the WRONG side too."""
    failures = {
        verb: (arms.correct.exit_code, arms.wrong.exit_code)
        for verb, arms in three_arm_probe.items()
        if verb in _honoured_verbs(three_arm_probe)
        and not (arms.correct.exit_code == 0 and arms.wrong.exit_code == 6)
    }
    assert not failures, f"correct/wrong exit codes are not (0, 6) for: {failures}"


#: `permissions` (a HONOURED_FLOOR member since BEFORE this spec, `ops/
#: crypto.py`, out of Scope beyond the shared `password_verified` renderer)
#: raises the SAME `AuthError` message -- "a password is required to read
#: this document's permissions" -- for BOTH "none supplied" and "supplied
#: but wrong" (`crypto.py:654`, a single raise site with no branch on
#: whether a secret was ever offered). This is a GENUINE, PRE-EXISTING,
#: FROZEN exception to AC6's letter, measured while landing this spec and
#: reported rather than silently narrowed away: `permissions`'s own
#: distinguishability has ALWAYS been via EXIT CODE alone (the roadmap's
#: own "6 / 0 / 6" evidence for `5ff60a280e`), never via message, and
#: fixing that message shape is `ops/crypto.py` work this spec's own Scope
#: table does not license. `decrypt` (the ONLY other pre-existing
#: HONOURED_FLOOR member) DOES differ ("no password password available:
#: ..." vs "the supplied password did not open this document") and is
#: NOT exempted.
_AC6_MESSAGE_EXEMPT: Final[frozenset[str]] = frozenset({"permissions"})


def test_ac6_on_every_honoured_verb_no_password_and_wrong_messages_differ(
    three_arm_probe: dict[str, _ThreeArms],
) -> None:
    """The `d03bee3` message was byte-identical across all three arms
    (`pypdf_structure.py:416`, E6) -- that identity was the defect's own
    signature. Asserted as inequality of the rendered `message`, never by
    matching a specific wording (X-206: an exit-code-only control passes on
    10 of 11 verbs of a deliberately broken binary)."""
    failures = {
        verb: (arms.no_password.message, arms.wrong.message)
        for verb, arms in three_arm_probe.items()
        if verb in _honoured_verbs(three_arm_probe)
        and verb not in _AC6_MESSAGE_EXEMPT
        and arms.no_password.message == arms.wrong.message
    }
    assert not failures, (
        f"the no-password and wrong-password messages are BYTE-IDENTICAL for: {failures} "
        "-- this is the exact defect signature this spec exists to close"
    )


# --------------------------------------------------------------------------- #
# AC7 -- the refusal is visible, coded, and ordered.
# --------------------------------------------------------------------------- #


def _refused_verbs(probe: dict[str, _ThreeArms]) -> list[str]:
    return sorted(verb for verb, cls in _classes(probe).items() if cls == "REFUSED")


def test_ac7_the_refusal_is_visible_coded_and_identical_for_correct_and_wrong(
    three_arm_probe: dict[str, _ThreeArms],
) -> None:
    """On every REFUSED verb, both the correct- and wrong-password arms
    exit 2 with an IDENTICAL message naming `--password-file` -- D1's own
    ruling that correct and wrong are deliberately indistinguishable on a
    REFUSED verb (the flag is refused before either value is ever
    consulted)."""
    failures = {}
    for verb in _refused_verbs(three_arm_probe):
        arms = three_arm_probe[verb]
        ok = (
            arms.correct.exit_code == 2
            and arms.wrong.exit_code == 2
            and arms.correct.message == arms.wrong.message
            and arms.correct.message is not None
            and "--password-file" in arms.correct.message
        )
        if not ok:
            failures[verb] = (arms.correct.exit_code, arms.wrong.exit_code, arms.correct.message)
    assert not failures, f"REFUSED verb(s) failed the visible/coded/identical check: {failures}"


def test_ac7_the_refused_set_matches_e2s_expected_population(
    three_arm_probe: dict[str, _ThreeArms],
) -> None:
    assert set(_refused_verbs(three_arm_probe)) == set(EXPECTED_REFUSED)


#: A placeholder OPERAND for the REFUSED verbs that declare a required
#: positional argument -- never opened (the refusal fires during flag
#: resolution, before the verb body ever validates its operand), but
#: Click's own "Missing argument" arity check runs BEFORE typer's callback
#: at all, so a verb needing one must be given SOMETHING to reach the
#: refusal this test is actually probing.
_PLACEHOLDER_OPERAND: Final[dict[str, tuple[str, ...]]] = {
    "compose": ("placeholder.png",),
    "create": ("placeholder.txt",),
    "encrypt": ("placeholder.pdf",),
    "convert": ("placeholder.docx",),
}


@pytest.mark.parametrize("verb", sorted(EXPECTED_REFUSED))
def test_ac7_d24_ordering_bad_path_says_does_not_accept_not_unreadable(verb: str) -> None:
    """D2.4: a verb that will never read the path must not disclose whether
    it exists. A REFUSED verb given a NONEXISTENT `--password-file` value
    reports "does not accept", never `_validate_password_file`'s "not a
    readable file" -- the consumption refusal runs FIRST."""
    operand = _PLACEHOLDER_OPERAND.get(verb, ())
    result = run_cli(
        verb, *operand, "--password-file", "/no/such/path/at/all", "-o", "json", env=_clean_env()
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 2, f"{verb}: {combined}"
    assert "does not accept" in combined, (
        f'{verb}: expected the consumption refusal ("does not accept"), got: {combined}'
    )
    assert "readable file" not in combined, (
        f"{verb}: leaked the readability-check message ahead of the consumption refusal "
        f"(D2.4 ordering violated): {combined}"
    )


# --------------------------------------------------------------------------- #
# AC12/AC13/AC14 -- the never-echo control (X-403), planted secret at DEBUG.
# --------------------------------------------------------------------------- #


def _debug_sweep(verb: str, argv: list[str], *, password_path: str) -> tuple[int, str]:
    result = run_cli(
        verb, *argv, "--password-file", password_path, "-vv", "-o", "json", env=_clean_env()
    )
    return result.returncode, result.stdout + result.stderr


@pytest.mark.parametrize("verb", sorted(INVOCATIONS))
def test_ac12_a_planted_secret_never_appears_in_debug_output(
    verb: str, corpus: Any, tmp_path: Path
) -> None:
    """A sentinel string is the password value; every verb is run at `-vv`
    with a planted secret and the captured DEBUG stream is searched for the
    sentinel and every substring of it of length >= 4 (X-403 clause 1). The
    arm asserts records are non-empty FIRST for HONOURED verbs (so the
    check cannot pass because logging was silently off) -- REFUSED verbs
    never reach password resolution at all, so their sweep is a pure
    negative control.
    """
    # Deliberately NOT a recognizable word or fragment of one: pytest's own
    # generated `tmp_path` embeds this TEST FUNCTION's name (containing
    # "planted"/"secret"), and the substring sweep below checks every run
    # of >= 4 sentinel characters against the ENTIRE captured output -- an
    # English-word-shaped sentinel risks colliding with the LOGGABLE path
    # itself (X-403 clause 2 licenses the path; a collision there would be
    # a false positive in this test, not a real leak). A pseudo-random,
    # mixed-case, no-vowel-run string has no plausible overlap with any
    # path component.
    sentinel = "zK4mQ9xR2vL7bN3wP8tY"
    pw_path = tmp_path / "cred-src-90210.dat"
    pw_path.write_text(sentinel, encoding="utf-8")
    pw_path.chmod(0o600)

    proxy = _EncryptedOperandProxy(corpus.path("encrypted_aes256"))
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    argv = _strip_password_file_flags(INVOCATIONS[verb].build(proxy, out_dir))

    _exit_code, combined = _debug_sweep(verb, argv, password_path=str(pw_path))

    for length in range(4, len(sentinel) + 1):
        for start in range(0, len(sentinel) - length + 1):
            substring = sentinel[start : start + length]
            assert substring not in combined, (
                f"{verb}: planted secret substring {substring!r} leaked into DEBUG output"
            )

    if verb in EXPECTED_REFUSED:
        return  # never reaches password resolution; no source/verified record expected

    assert "password resolved from" in combined, (
        f"{verb}: no resolution-source record at -vv -- the sweep above cannot prove "
        "anything if logging was silently off (X-403's own non-vacuity requirement)"
    )
    assert f"file:{pw_path}" in combined, (
        f"{verb}: the flag/path pair should stay loggable (X-403 clause 2) -- "
        "over-redacting the path is itself a defect this criterion catches"
    )


# --------------------------------------------------------------------------- #
# AC16/AC18 -- OR-7, the resolvability and refusal tiers.
# --------------------------------------------------------------------------- #


def test_ac16_the_resolvability_tier_is_predicted_on_every_honoured_verb(
    three_arm_probe: dict[str, _ThreeArms],
) -> None:
    """No flag / env absent / stdin not a TTY -> exit 6 on every HONOURED
    verb (`no_password` arm), the SAME in both `--dry-run` and a real run
    by construction -- these verbs already open the document unconditionally
    in both modes (pre-existing X-67/B-054 invariant), which is what makes
    this tier's `dry == real` structural rather than a separately
    maintained prediction."""
    failures = {
        verb: arms.no_password.exit_code
        for verb, arms in three_arm_probe.items()
        if verb in _honoured_verbs(three_arm_probe) and arms.no_password.exit_code != 6
    }
    assert not failures, f"the no-password arm did not exit 6 for: {failures}"


@pytest.mark.parametrize("verb", sorted(EXPECTED_REFUSED))
def test_ac18_the_refusal_tier_mirrors_dry_and_real(verb: str) -> None:
    """On every REFUSED verb, `--dry-run --password-file <path>` and the
    real run both exit 2 with the SAME envelope `kind` -- structural (the
    consumption check runs during flag resolution, before any plan is
    built), asserted anyway (a claim is a claim; claims get controls)."""
    env = _clean_env()
    dry = run_cli(verb, "--password-file", "/no/such/path", "--dry-run", "-o", "json", env=env)
    real = run_cli(verb, "--password-file", "/no/such/path", "-o", "json", env=env)
    assert dry.returncode == real.returncode == 2, (
        f"{verb}: dry={dry.returncode}, real={real.returncode} -- expected 2/2"
    )
    dry_payload = json.loads(dry.stdout)
    real_payload = json.loads(real.stdout)
    assert dry_payload.get("error", {}).get("kind") == real_payload.get("error", {}).get("kind")


# --------------------------------------------------------------------------- #
# AC19 -- the honoured/refused split is documented DERIVED or ABSENT.
#
# NOT mechanized here. A first attempt (a markdown table-row/list-item
# scanner counting honoured-verb names) false-positived on README.md's own
# PRE-EXISTING, unrelated verb-BY-CATEGORY tables ("Structure: merge, split,
# extract, delete, rotate, reorder"; "Optimize: compress, repair,
# linearize") -- a semantic distinction ("this table is about feature
# grouping" vs "this table is a password-file contract") that syntax alone
# cannot make reliably, and a narrower heuristic risked the opposite
# failure (silently passing an actual roster). PDF-30's closure rule's own
# THIRD branch is "absent" -- this spec's own README addition names no
# roster (verified by hand: prose only, pointing at `--help` and at trying
# the flag, exactly as `test_password_file_contract.py`'s own PR record
# states), and that is the closure this criterion actually took.
# --------------------------------------------------------------------------- #
