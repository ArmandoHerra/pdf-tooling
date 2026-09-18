"""`PDF-82` D4 — the collection-time ratchet on UNGATED engine-blind drives.

WHAT THIS MODULE IS FOR
-----------------------
Only `make engines-gate` arm 2 can decide whether a test is engine-DEPENDENT:
that is a runtime property, and the one way to answer it is to run the suite
with the engines hidden. It costs a second full suite run, so it does not join
`make ci` (`X-756`) — and for eight engineers `make ci`'s epilogue named it
beside a reason that was false on the host each of them was standing on, so
nobody ran it and eighteen ungated engine-dependent arms accumulated unseen.

What CAN ride inside `make ci`, for free, is a census of the CLASS those
eighteen belong to: items that drive a verb whose operand only an out-of-process
engine can finally judge (`registry.engine_blind_verbs()`) while carrying no
engine marker. This module counts that class PER MODULE against a frozen,
append-only ceiling, reading the run's own collected item list — collection is
already paid for by the run this arm is inside, so the measurement costs
nothing. A NEW ungated engine-blind drive pushes its module over its ceiling and
reds BY NAME, with no engine configuration and no second suite run, and the
author who adds one has to write down why it is engine-independent — the one
thing none of the eight engineers was ever asked.

WHAT IT CANNOT DO, STATED RATHER THAN IMPLIED
---------------------------------------------
* It cannot decide ENGINE-DEPENDENCE. Most ungated members are genuinely
  engine-free; this arm makes the class VISIBLE and NON-GROWING, and
  `make engines-gate` arm 2 makes it CORRECT.
* It cannot catch OVER-marking — an engine-free arm gated into a permanent skip,
  whose coverage then vanishes with nothing to report it. Nothing in this
  repository can, which is why `PDF-82` D2's licence to mark is membership of a
  MEASURED red set and never judgement.
* On a `-k`- or path-filtered run the population is the selected subset, so the
  ratchet is weaker there. It is never WRONG there: the non-vacuity arm turns
  the degenerate case red rather than passing on an empty walk. The run that
  matters is `make cover`, which selects everything.

THE POPULATION IS DERIVED ON BOTH HALVES, AND BOTH ARE REQUIRED
---------------------------------------------------------------
Measured at `3aedef8` (`PDF-82` E6) BEFORE either detector was designed, which
is the only moment the reach of each could be checked against a known answer:

* **H1, the callspec walk** — an item one of whose `callspec.params` IS an
  engine-blind verb. It reaches the seventeen parametrized cells among the
  eighteen `PDF-82` gated, and 125 items in all, of which zero carried a marker.
* **H2, the lexical walk** — an item whose own function (`lexical`), or a
  module-level helper that function reaches (`helper`), spells an engine-blind
  verb as a string literal. It reaches `tests/test_read_seams.py`'s zip-claim
  arm, whose verb literal lives in the module-level `_convert_dry_argv` helper.

A callspec-only detector misses that arm; a lexical-only detector misses all
seventeen others, because `verb` is a PARAMETER and never a literal in the
modules where the defect actually was. `test_the_helper_limb_reaches_a_gated_arm_
the_callspec_walk_cannot_see` is what reds if the helper limb stops resolving,
instead of the walk quietly under-reaching — read off the TREE rather than off
the selection, because a claim about a walk's reach must not change its answer
with `-k`.

**H2's reach is deliberately a SUPERSET of "drives".** It sees an item that
NAMES an engine-blind verb, which includes arms that only assert about one
(`tests/unit/test_registry.py`'s classification arms are in the population for
that reason). The narrower reading would need a hand-typed roster of "suite CLI
drivers", and a new driver would then shrink the population silently — the one
direction a ratchet must not fail in. Over-inclusion costs a larger debt
register and cannot hide a new arm; under-inclusion hides exactly the class this
module exists to watch.

THE CEILING IS A RATIFICATION LEDGER, NOT A LITERAL
---------------------------------------------------
`PDF-70`'s shipped design, already carried by `tests/test_docs_antirot.py` and
`tests/test_read_seams.py`: the live ceiling is the NEWEST record's mapping and
nothing else, so a ceiling cannot move unless a record moves with it. Lowering
is ORDINARY (`direction="down"` plus a reason). Raising needs everything `X-715`
required, a ruling id in the diff, and a reason naming the key — and that
friction IS the instrument.
"""

from __future__ import annotations

import ast
import collections
import importlib.util
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Final, NamedTuple

import pytest

from registry import engine_blind_verbs

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

#: `registry.engine_blind_verbs()`, memoized PER PROCESS.
#:
#: The derivation is an `ast` walk of the import graph under `src/` and is NOT
#: memoized at its source: measured at ~2.0 s per call, and this module has four
#: callers. The walk is pure over a source tree pytest is not editing mid-run, so
#: caching it here changes no answer and keeps this instrument's cost to one walk
#: per worker instead of four. (`tests/test_cli_contract.py:97` already pays one
#: at module import on every worker; a cache at the source would make this free,
#: and is FILED rather than taken here — `registry.py` is not this item's file.)
_MEMOIZED_VERBS: list[tuple[str, ...]] = []


def engine_blind_verb_population() -> tuple[str, ...]:
    """The engine-blind verbs, walked once per process."""
    if not _MEMOIZED_VERBS:
        _MEMOIZED_VERBS.append(engine_blind_verbs())
    return _MEMOIZED_VERBS[0]


#: How many helper hops H2 follows from a test function. Three, because the
#: measured case needs one (`test_convert_zip_claim_branch_…` ->
#: `_convert_dry_argv`) and a ceiling that is exactly the measured case is a
#: detector fitted to its own evidence.
_HELPER_HOPS: Final[int] = 3

#: The three routes into the population, kept apart because the assertions below
#: are about REACH: a gated member reachable only by `helper` is what proves the
#: lexical walk resolves a module-level helper rather than stopping at the test
#: function's own body.
#: The marker `tests/conftest.py` resolves to a visible skip, spelled once.
_REQUIRES_MARKER: Final[str] = "requires"

_VIA_CALLSPEC: Final[str] = "callspec"
_VIA_LEXICAL: Final[str] = "lexical"
_VIA_HELPER: Final[str] = "helper"


# --------------------------------------------------------------------------- #
# The ratification ledger (PDF-70 D1), and its verifier.
# --------------------------------------------------------------------------- #


class _GatingRatification(NamedTuple):
    """One recorded movement of the ungated engine-blind-drive ceiling."""

    date: str
    spec: str
    #: "genesis" | "down" | "up"
    direction: str
    ceilings: Mapping[str, int]
    reason: str
    #: The PM ruling id (X-NNN) authorising an UPWARD key movement.
    ruling: str = ""


_RATIFICATION_DATE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_RATIFICATION_DIRECTIONS: Final = ("genesis", "down", "up")


def gating_ratification_complaints(ledger: Sequence[_GatingRatification]) -> list[str]:
    """Every rule violation in *ledger*, per key. Empty means ACCEPTED.

    PURE OVER ITS PARAMETER (`PDF-70` D4), so synthetic ledgers drive it
    in-process on every run and the real ledger is never mutated to prove a
    point, and it RETURNS complaints rather than raising so the refusing
    direction is as ordinary to assert as the accepting one.

    DUPLICATED, KNOWINGLY, from `tests/test_read_seams.py` and
    `tests/test_docs_antirot.py` — the THIRD instance, and the reason is the one
    those two already record: cross-test-module coupling is a filed defect on
    this product (I-12 piece 3, carrier `B-308`), so a new instance of it is not
    opened here to save a duplicate. Consolidating all three is a follow-up once
    `B-308` decides the shared home.
    """
    complaints: list[str] = []
    if not ledger:
        return ["the ratification ledger is EMPTY: the live ceiling has no record behind it"]

    for index, record in enumerate(ledger):
        where = f"[{index}] {record.spec} ({record.date})"
        if not _RATIFICATION_DATE.fullmatch(record.date):
            complaints.append(f"{where}: date is not YYYY-MM-DD")
        if not record.spec.strip():
            complaints.append(f"{where}: no allocating spec id")
        if not record.reason.strip():
            complaints.append(
                f"{where}: no reason — a ratification carrying no evidence is an edit "
                f"wearing a record's clothes"
            )
        if record.direction not in _RATIFICATION_DIRECTIONS:
            complaints.append(
                f"{where}: direction {record.direction!r} is not one of "
                f"{list(_RATIFICATION_DIRECTIONS)}"
            )
        if (record.direction == "genesis") != (index == 0):
            complaints.append(f"{where}: direction 'genesis' belongs to record 0 and to no other")
        if index and record.date < ledger[index - 1].date:
            complaints.append(f"{where}: dated before its predecessor {ledger[index - 1].date}")

    for index in range(1, len(ledger)):
        previous, current = ledger[index - 1], ledger[index]
        where = f"[{index}] {current.spec} ({current.date})"
        for key in sorted(set(previous.ceilings) | set(current.ceilings)):
            before = previous.ceilings.get(key)
            after = current.ceilings.get(key)
            if before == after:
                continue
            if after is not None and (before is None or after > before):
                shown = "absent" if before is None else before
                if current.direction != "up":
                    complaints.append(
                        f"{where}: {key} RAISED {shown} -> {after} in a record declaring "
                        f"direction={current.direction!r}; an upward movement must declare "
                        f"direction='up'"
                    )
                if not current.ruling.strip():
                    complaints.append(
                        f"{where}: {key} RAISED {shown} -> {after} with NO ruling. Raising "
                        f"this ceiling admits a new ungated engine-blind drive; it is the PM's "
                        f"call, on the record, or it is not made. Declare the arm's engine, or "
                        f"write down why the drive is engine-independent"
                    )
                if key not in current.reason:
                    complaints.append(
                        f"{where}: {key} RAISED {shown} -> {after} but the reason does not "
                        f"name the key; a raise is justified per key or not at all"
                    )
            else:
                shown = "removed" if after is None else after
                if current.direction != "down":
                    complaints.append(
                        f"{where}: {key} LOWERED {before} -> {shown} in a record declaring "
                        f"direction={current.direction!r}; a tightening must declare "
                        f"direction='down' so it is recorded rather than furtive"
                    )
    return complaints


#: `PDF-82` D4's genesis record, NAMED so the record that follows can derive its
#: own mapping from it (``{**previous, <one key>: <one value>}``) instead of
#: re-typing sixteen entries. A re-typed mapping is a mapping a later raise can
#: drift, and the verifier can only report a drift it is handed; deriving makes
#: "exactly one key moved" true BY CONSTRUCTION rather than by inspection.
_PDF_82_GENESIS: Final[_GatingRatification] = _GatingRatification(
    date="2026-09-16",
    spec="PDF-82",
    direction="genesis",
    ceilings=MappingProxyType(
        {
            "tests/integration/test_crypto_roundtrip.py": 1,
            "tests/integration/test_ocr.py": 7,
            "tests/integration/test_office.py": 1,
            "tests/integration/test_or7_bulk_destructive.py": 12,
            "tests/integration/test_or7_engine_absent.py": 2,
            "tests/integration/test_out_dir_planning.py": 19,
            "tests/integration/test_value_shape.py": 17,
            "tests/test_batch_continuation.py": 24,
            "tests/test_cli_contract.py": 16,
            "tests/test_derived_dimensions.py": 2,
            "tests/test_docs_antirot.py": 1,
            "tests/test_envelope_contract.py": 20,
            "tests/test_password_file_contract.py": 5,
            "tests/unit/test_overlay.py": 1,
            "tests/unit/test_registry.py": 4,
            "tests/unit/test_verb_help_content.py": 2,
        }
    ),
    reason=(
        "GENESIS. The ungated half of the population as MEASURED after PDF-82's "
        "eighteen marks landed -- 134 items across 16 modules, out of a population "
        "of 158 -- never predicted. It is a DEBT REGISTER and not an exemption list: "
        "nothing here is declared engine-free, each entry is a count of arms that "
        "name an engine-blind verb and declare no engine, and the count may not GROW. "
        "The population before the marks was the same 158 with 6 gated (PDF-82 E6's "
        "125 callspec-derived members are 125 of them, of which zero were gated), "
        "which is the measurement that licensed exactly eighteen marks and no "
        "nineteenth: the eighteen are the arms `make engines-gate` arm 2 reddened, "
        "minus tests/test_read_seams.py's residue-ceiling arm, which X-757 rules is "
        "reporting correctly rather than missing a marker."
    ),
)

#: PDF-82 D4 — THE RATIFICATION LEDGER, append-only. The live ceiling below is
#: the NEWEST record's mapping and never a separately-writable literal.
#: PDF-89's own record derives its mapping from THIS one (`{**previous, key:
#: value}`), never from `_PDF_82_GENESIS` directly -- the genesis mapping
#: still carries this same key's PRE-PDF-84 value, and spreading it again
#: would silently revert PDF-84's own movement.
_PDF_84_RATIFICATION: Final[_GatingRatification] = _GatingRatification(
    date="2026-09-17",
    spec="PDF-84",
    direction="up",
    ruling="X-781",
    ceilings=MappingProxyType(
        {**_PDF_82_GENESIS.ceilings, "tests/integration/test_or7_bulk_destructive.py": 13}
    ),
    reason=(
        "PDF-84 wires the clobber route into the bulk-destructive gate at every "
        "batch verb, and X-772 makes an occupied-`--out-dir` REFUSAL assertion for "
        "`convert` AND `ocr` a required criterion -- that pair being exactly "
        "`engine_blind_verbs() & out_dir_batch_verbs()`, and exactly the pair "
        "`tests/test_batch_continuation.py`'s INERT_GATE_VERBS excludes, so an "
        "inertness arm there would have pinned the defect as CORRECT. The new arm "
        "lands in tests/integration/test_or7_bulk_destructive.py, which already "
        "carries this idiom at :275 and :293; the key "
        "tests/integration/test_or7_bulk_destructive.py moves 12 -> 13 and no other "
        "key moves, total 134 -> 135 across the same 16 modules. "
        "THE DRIVE IS ENGINE-INDEPENDENT, MEASURED RATHER THAN ASSERTED: with PATH "
        "pointed at a directory the engine does not resolve from, the refusal is "
        "BYTE-IDENTICAL to the engine-present one -- PM-measured at 402 bytes, `cmp` "
        "clean, and re-driven here byte-identical at 700 (convert) and 692 (ocr) "
        "bytes, the absolute figure being a function of the fixture path length the "
        "re-run hint echoes rather than of the engine -- while "
        "the same command over an EMPTY `--out-dir` returns code 3 / kind "
        "engine_missing for BOTH verbs, so the engine's absence is genuinely reachable "
        "on that exact command and the gate is outranking the engine tier rather than "
        "the engine being irrelevant. A `@pytest.mark.requires(...)` would therefore be "
        "a FALSE declaration, and under `engines-hidden` it would not weaken the arm but "
        "DELETE it -- in the without-engines job release.yml:44 gates the tag on, "
        "where a vacuous safety criterion is no criterion. The per-verb discriminator "
        "holds the out-dir occupancy CONSTANT and varies only the flag under test: "
        "engine hidden, same occupied-`--out-dir` command, 5 with the gate's message "
        "signature without `-y` and 3 engine_missing WITH it -- the `-y` -> 3 flip. "
        "`convert` read 5 -> 3 before this item; `ocr` read 3 -> 3, the engine tier "
        "owning both answers because the gate was absent, and reads 5 -> 3 after it. "
        "+1 AND NO MORE: `population()` appends one Member per ARM, so the four runs "
        "live in ONE non-parametrized function. Parametrizing them over the two verbs "
        "would cost 2, is NOT authorized by X-781, and is a blocker back to the PM "
        "rather than an engineer's call; and swapping the `ocr` member of `_ENGINES` "
        "to the clobbering builder to reach +0 is refused in advance, because it buys "
        "the ceiling by deleting the `--in-place` coverage D4/AC11 require to survive."
    ),
)

ENGINE_GATING_LEDGER: Final[tuple[_GatingRatification, ...]] = (
    _PDF_82_GENESIS,
    _PDF_84_RATIFICATION,
    _GatingRatification(
        date="2026-09-18",
        spec="PDF-89",
        direction="up",
        ruling="X-891",
        ceilings=MappingProxyType(
            {**_PDF_84_RATIFICATION.ceilings, "tests/integration/test_or7_bulk_destructive.py": 14}
        ),
        reason=(
            "PDF-89 refuses a destination that resolves onto one of the run's own "
            "inputs, and `convert`/`ocr` are 2 of the 19 `-O` cells and 2 of the 11 "
            "`--out-dir` cells the defect reaches (E2) -- an acceptance bar that "
            "silently dropped the two verbs hardest to drive is `PDF-84`'s own lesson "
            "recurring one item later (X-772). The new arm lands in "
            "tests/integration/test_or7_bulk_destructive.py, which already carries "
            "this idiom; the key tests/integration/test_or7_bulk_destructive.py moves "
            "13 -> 14 and no other key moves, total 135 -> 136 across the same 16 "
            "modules. "
            "THE DRIVE IS ENGINE-INDEPENDENT, MEASURED HERE RATHER THAN INHERITED FROM "
            "X-781: PDF-89's refusal fires at PLAN TIME, strictly before X-781's own "
            "bulk-destructive gate is ever consulted, which makes engine-independence "
            "MORE plausible and therefore exactly the thing not to assume. With `PATH` "
            "pointed at a directory neither soffice nor tesseract resolves from, the "
            "refusal is BYTE-IDENTICAL to the engine-present one on both flag shapes: "
            "288 bytes, `cmp` clean, for `convert` on both `-O` and `--out-dir`; 279 "
            "bytes, `cmp` clean, for `ocr` on both `-O` and `--out-dir`. The same "
            "command over a DISTINCT target (not one of the run's inputs), with the "
            "engine hidden, reaches code 3 / kind engine_missing for both verbs, so the "
            "engine's absence is genuinely reachable on this exact command and the new "
            "refusal is the gate outranking the engine tier rather than the engine "
            "being irrelevant. A `@pytest.mark.requires(...)` would therefore be a "
            "FALSE declaration and would DELETE the arm under `engines-hidden`, in the "
            "without-engines job release.yml:44 gates the tag on. "
            "+1 AND NO MORE, carried forward verbatim from X-781: `population()` "
            "appends one Member per ARM, so both verbs and both flag shapes live in "
            "ONE non-parametrized function. Parametrizing over the two verbs would "
            "cost 2 and is not authorized by this ruling any more than by X-781."
        ),
    ),
)

#: The LIVE ceiling: the newest record's mapping, and nothing else.
UNGATED_CEILING: Final[Mapping[str, int]] = ENGINE_GATING_LEDGER[-1].ceilings


# --------------------------------------------------------------------------- #
# The two detectors.
# --------------------------------------------------------------------------- #

_SOURCES: dict[Path, str | None] = {}
_PARSED: dict[Path, ast.Module | None] = {}
#: Keyed on the PARSED TREE's identity, which `_PARSED` keeps alive for the
#: process, so the two readers below walk each module exactly once between them.
_FACTS: dict[int, dict[str, _Facts]] = {}


def _source(path: Path) -> str | None:
    if path not in _SOURCES:
        try:
            _SOURCES[path] = path.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover - a module pytest imported is readable
            _SOURCES[path] = None
    return _SOURCES[path]


_LEXICAL: dict[tuple[Path, tuple[str, ...]], tuple[frozenset[str], frozenset[str]]] = {}


def _parsed(path: Path) -> ast.Module | None:
    if path not in _PARSED:
        source = _source(path)
        try:
            _PARSED[path] = None if source is None else ast.parse(source)
        except SyntaxError:  # pragma: no cover - a module pytest imported parses
            _PARSED[path] = None
    return _PARSED[path]


class _Facts(NamedTuple):
    """One function's string constants and the names it calls, from ONE walk.

    Both halves are collected in a single pass and the calls are hoisted OUT of
    the hop loop below, which is the difference between this instrument costing
    a fraction of a second over the whole suite and costing several: a walk
    re-run per function per hop is four walks of the tree, not one.
    """

    constants: frozenset[str]
    calls: frozenset[str]
    #: Carries a `@pytest.mark.requires(...)` DECORATOR in the source. Read here
    #: as well as off the collected item because the fitness arm below is a claim
    #: about the WALK's reach, which must hold whatever a run happens to select.
    requires_decorated: bool


def _requires_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr == _REQUIRES_MARKER:
            return True
    return False


def _function_facts(tree: ast.Module) -> dict[str, _Facts]:
    cached = _FACTS.get(id(tree))
    if cached is not None:
        return cached
    definitions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            definitions.setdefault(node.name, node)

    facts: dict[str, _Facts] = {}
    for name, node in definitions.items():
        constants: set[str] = set()
        calls: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant):
                if isinstance(sub.value, str):
                    constants.add(sub.value)
            elif isinstance(sub, ast.Call):
                called = sub.func
                if isinstance(called, ast.Name):
                    calls.add(called.id)
                elif isinstance(called, ast.Attribute):
                    calls.add(called.attr)
        facts[name] = _Facts(frozenset(constants), frozenset(calls), _requires_decorator(node))
    _FACTS[id(tree)] = facts
    return facts


def helper_borne_gated_arms(verbs: Sequence[str]) -> tuple[str, ...]:
    """Every `requires`-decorated test function in the `tests/` tree ON DISK that
    the lexical walk reaches ONLY through a module-level helper.

    Read off the tree rather than off the run's collected items on purpose: this
    is a claim about the WALK's REACH, and a claim about the walk must not change
    its answer because a `-k` run selected a different set of modules. The
    decorator read is source-level and therefore blind to a mark applied at a
    `pytest.param` — which is exactly right here, because a helper-borne arm is a
    plain function and never a parametrized cell.
    """
    found: list[str] = []
    for path in sorted((REPO_ROOT / "tests").rglob("test_*.py")):
        tree = _parsed_if_it_names_a_verb(path, tuple(verbs))
        if tree is None:
            continue
        _direct, via_helper = _lexical_drivers_cached(path, tuple(verbs))
        facts = _function_facts(tree)
        found.extend(
            f"{path.relative_to(REPO_ROOT)}::{name}"
            for name in sorted(via_helper)
            if facts[name].requires_decorated
        )
    return tuple(found)


def lexical_drivers(
    tree: ast.Module, verbs: Sequence[str], *, hops: int = _HELPER_HOPS
) -> tuple[frozenset[str], frozenset[str]]:
    """``(direct, via_helper)`` — the function names in *tree* that spell an
    engine-blind verb in their OWN body, and those that reach one only through a
    module-level helper, within *hops* hops.

    The two are returned apart rather than unioned because the helper limb is
    the one a later refactor silently loses: `tests/test_read_seams.py`'s
    zip-claim arm passes `_convert_dry_argv(...)`'s return value to the driver
    and spells no verb of its own, so a body-only walk sees that ungated
    engine-blind arm as no arm at all (`PDF-82` E6). Keeping the routes distinct
    is what lets `test_the_helper_limb_reaches_a_gated_arm_the_callspec_walk_
    cannot_see` red when the limb disappears.
    """
    wanted = frozenset(verbs)
    facts = _function_facts(tree)
    direct = frozenset(name for name, fact in facts.items() if fact.constants & wanted)
    reaches = dict.fromkeys(facts, False) | dict.fromkeys(direct, True)
    for _ in range(hops):
        moved = False
        for name, fact in facts.items():
            if reaches[name]:
                continue
            if any(reaches.get(called, False) for called in fact.calls):
                reaches[name] = True
                moved = True
        if not moved:
            break
    return direct, frozenset(name for name, hit in reaches.items() if hit) - direct


def _lexical_drivers_cached(
    path: Path, verbs: tuple[str, ...]
) -> tuple[frozenset[str], frozenset[str]]:
    """Per module, memoized. A module whose SOURCE TEXT does not contain a verb
    as a substring is skipped without parsing: a string constant equal to one
    implies the text contains it, so the shortcut cannot hide a member."""
    key = (path, verbs)
    if key not in _LEXICAL:
        tree = _parsed_if_it_names_a_verb(path, verbs)
        _LEXICAL[key] = (frozenset(), frozenset()) if tree is None else lexical_drivers(tree, verbs)
    return _LEXICAL[key]


def _parsed_if_it_names_a_verb(path: Path, verbs: tuple[str, ...]) -> ast.Module | None:
    """The module's tree, or ``None`` when its SOURCE TEXT does not contain a
    verb as a substring — in which case it is skipped without parsing at all. A
    string constant equal to a verb implies the text contains it, so the
    shortcut cannot hide a member."""
    source = _source(path)
    if source is None or not any(verb in source for verb in verbs):
        return None
    return _parsed(path)


# --------------------------------------------------------------------------- #
# The census.
# --------------------------------------------------------------------------- #


class Arm(NamedTuple):
    """The facts about one collected item this instrument reads, and no others."""

    nodeid: str
    module: str
    params: tuple[object, ...]
    function: str | None
    path: Path | None
    engine: str | None

    @property
    def gated(self) -> bool:
        return self.engine is not None


class Member(NamedTuple):
    """One population member, and which detector(s) reached it."""

    arm: Arm
    via: tuple[str, ...]


def arms(items: Iterable[pytest.Item]) -> tuple[Arm, ...]:
    """The run's own collected items, reduced to what the detectors read.

    `request.session.items` is FULL on an xdist worker — including the items
    that worker did not run — which is what makes this instrument free under the
    project's default `-n auto` (`PDF-82` E7, measured on a worker).
    """
    found: list[Arm] = []
    for item in items:
        marker = item.get_closest_marker(_REQUIRES_MARKER)
        engine = str(marker.args[0]) if marker is not None and marker.args else None
        callspec = getattr(item, "callspec", None)
        params = tuple(getattr(callspec, "params", {}).values()) if callspec is not None else ()
        function = getattr(item, "function", None)
        raw_path = getattr(item, "path", None)
        found.append(
            Arm(
                nodeid=item.nodeid,
                module=item.nodeid.split("::")[0],
                params=params,
                function=None if function is None else function.__name__,
                path=None if raw_path is None else Path(str(raw_path)),
                engine=engine,
            )
        )
    return tuple(found)


def population(candidates: Sequence[Arm], verbs: Sequence[str]) -> tuple[Member, ...]:
    """Every arm either detector reaches, with the detector(s) that reached it."""
    wanted = frozenset(verbs)
    ordered = tuple(verbs)
    members: list[Member] = []
    for arm in candidates:
        via: list[str] = []
        if any(isinstance(value, str) and value in wanted for value in arm.params):
            via.append(_VIA_CALLSPEC)
        if arm.path is not None and arm.function is not None:
            direct, via_helper = _lexical_drivers_cached(arm.path, ordered)
            if arm.function in direct:
                via.append(_VIA_LEXICAL)
            elif arm.function in via_helper:
                via.append(_VIA_HELPER)
        if via:
            members.append(Member(arm, tuple(via)))
    return tuple(members)


class Census(NamedTuple):
    verbs: tuple[str, ...]
    collected_ids: frozenset[str]
    members: tuple[Member, ...]

    @property
    def collected(self) -> int:
        return len(self.collected_ids)

    @property
    def gated(self) -> tuple[Member, ...]:
        return tuple(member for member in self.members if member.arm.gated)

    @property
    def ungated(self) -> tuple[Member, ...]:
        return tuple(member for member in self.members if not member.arm.gated)

    @property
    def ungated_by_module(self) -> collections.Counter[str]:
        return collections.Counter(member.arm.module for member in self.ungated)


@pytest.fixture(scope="session")
def census(request: pytest.FixtureRequest) -> Census:
    """The run's own collected items, censused once per worker."""
    verbs = engine_blind_verb_population()
    collected = arms(request.session.items)
    return Census(
        verbs=verbs,
        collected_ids=frozenset(arm.nodeid for arm in collected),
        members=population(collected, verbs),
    )


# --------------------------------------------------------------------------- #
# The three assertions (PDF-82 D4).
# --------------------------------------------------------------------------- #


def test_the_ungated_engine_blind_drive_count_does_not_grow_per_module(census: Census) -> None:
    """THE RATCHET. A new ungated engine-blind drive reds its module by name.

    Not a failure on sight: most ungated members are genuinely engine-free, and
    a rule demanding a marker on all of them was REFUTED by its own population
    before it was designed against (125 members, 0 marked — `PDF-82` E6). What
    is forbidden is GROWTH, and the response to a red is to declare the arm's
    engine with `@pytest.mark.requires(...)` or to append a record saying why
    the drive is engine-independent — never to raise the ceiling to reach green.

    RED: add a test driving an engine-blind verb without an engine marker ->
    that module's count exceeds its ceiling -> red naming the module and the
    node. Its own `@pytest.mark.requires(...)` makes it green again, which is
    what proves this reads the MARKER and not the verb name.
    """
    counts = census.ungated_by_module
    grew = {
        module: (count, UNGATED_CEILING.get(module, 0))
        for module, count in counts.items()
        if count > UNGATED_CEILING.get(module, 0)
    }
    offenders = sorted(member.arm.nodeid for member in census.ungated if member.arm.module in grew)
    assert grew == {}, (
        f"ungated engine-blind drives grew past their frozen ceiling "
        f"{{module: (now, ceiling)}}: {grew}. The nodes in those modules: {offenders}. "
        f"An engine-blind verb is one whose operand only an out-of-process engine can "
        f"finally judge ({list(census.verbs)}); an arm whose OUTCOME depends on that engine "
        f"must carry @pytest.mark.requires(...) or it FAILS instead of skipping when the "
        f"engine is absent -- which is exactly what `make engines-gate` arm 2 found "
        f"eighteen times. Raising this ceiling is anti-gaming: gate the arm, or append a "
        f"ledger record saying why the drive is engine-independent"
    )
    assert set(counts) <= set(UNGATED_CEILING), (
        f"module(s) joined the ungated engine-blind population with no ceiling entry: "
        f"{sorted(set(counts) - set(UNGATED_CEILING))}. A new module drives an engine-blind "
        f"verb without an engine marker; record it or gate it"
    )
    assert gating_ratification_complaints(ENGINE_GATING_LEDGER) == [], (
        "the engine-gating ratification ledger does not verify: "
        f"{gating_ratification_complaints(ENGINE_GATING_LEDGER)}"
    )


def test_the_walk_is_not_vacuous(census: Census) -> None:
    """A walk that matched nothing is RED, not green (`PDF-81` AC7's shape).

    Three ways this instrument can go quietly blind and report a clean sheet:
    the derived verb population empties (an import-graph change, or a stubbed
    `engine_blind_verbs()`), both detectors stop reaching anything, or the
    GATED half empties — which is what a suite that had silently lost every
    engine marker would look like from here.
    """
    assert census.verbs, (
        "registry.engine_blind_verbs() is EMPTY, so this whole census is over nothing. "
        "It is derived from the import graph; an empty answer is a finding about that "
        "derivation, never a reason to trust the green below it"
    )
    assert census.members, (
        f"neither detector reached a single one of the {census.collected} collected item(s), "
        f"so the population is empty and the ratchet above is vacuous. Under a `-k`- or "
        f"path-filtered run that is the honest answer for the selection; under `make cover` "
        f"it means the walk has stopped seeing this suite"
    )
    assert census.gated, (
        "no member of the population carries an engine marker, so nothing in this suite is "
        "declared engine-dependent. Either every engine marker has been lost or the marker "
        "read below is broken; both make the ratchet's gated/ungated split meaningless"
    )


def test_the_helper_limb_reaches_a_gated_arm_the_callspec_walk_cannot_see() -> None:
    """FITNESS — the assertion that proves the walk resolves a HELPER-borne literal.

    `tests/test_read_seams.py`'s zip-claim arm carries `requires("soffice")`,
    spells its verb nowhere in its own body — the literal lives in the
    module-level `_convert_dry_argv` helper — and takes no parameters at all, so
    the callspec walk provably cannot see it (`PDF-82` E6 censused it OUT of the
    125). Under a body-only lexical walk it would fall outside the population and
    this instrument would under-reach SILENTLY, with every other assertion here
    still green. This is what reddens instead.

    Deliberately a claim about the HELPER route rather than about the lexical
    walk as a whole: seven gated members are lexical and six of them spell the
    verb in their own body, so a union claim stays green with the helper limb
    deleted. Measured, not assumed.

    Deliberately read off the TREE rather than off `census`, too, and that is the
    difference between a fitness claim and a selection artifact: exactly one
    module in this suite carries an arm of this shape, so a `-k` or path-filtered
    run that did not select it would red an arm about the WALK for a reason that
    is about the RUN. The population ratchet is allowed to be weaker under a
    filter; a claim about reach is not allowed to be wrong under one.

    It is also why `test_ac5_…ceiling_that_may_not_grow` in that same module
    carries NO marker (`PDF-82` D3): it reaches its drive through a FIXTURE and
    is in no population here, so a marker there would red this arm's own premise
    instead of gating anything.

    RED: set the helper hops to zero, or drop the lexical walk entirely.
    """
    verbs = engine_blind_verb_population()
    reached = helper_borne_gated_arms(verbs)
    assert reached, (
        "no `requires`-marked arm anywhere under tests/ is reached THROUGH A MODULE-LEVEL "
        "HELPER, so the lexical walk's helper limb is contributing nothing and a verb "
        "literal one hop away from a test body is now invisible to this census. Both "
        "detectors are required, and so are both of the lexical one's limbs: each alone "
        "misses a limb of the eighteen `PDF-82` gated (E6)"
    )


def test_the_helper_reached_gated_arms_are_in_the_population_when_they_are_collected(
    census: Census,
) -> None:
    """The item-level half of the arm above: an arm the walk reaches through a
    helper must also be IN the census, whenever this run collected it.

    Reach and membership are two different claims, and this is the one that would
    catch a population builder that resolved helpers correctly and then dropped
    the result on the floor. Scoped to what the run collected, so a filtered run
    narrows it rather than reddening it.
    """
    collected = {member.arm.nodeid for member in census.members}
    missing = sorted(
        arm
        for arm in helper_borne_gated_arms(census.verbs)
        if arm in census.collected_ids and arm not in collected
    )
    assert missing == [], (
        f"the lexical walk reaches {missing} through a module-level helper, and this run "
        f"COLLECTED them, yet the census left them out of the population -- the walk and "
        f"the population builder disagree"
    )


def test_every_gated_engine_spelling_is_one_the_skip_census_classifies(census: Census) -> None:
    """The gated arms' skips must land in `assert_skips.py`'s `engine-gated` class.

    `@pytest.mark.requires(...)` accepts a friendly name or a bare port name, and
    `tests/conftest.py` renders the skip reason as `"{engine} unavailable (port
    {port}); …"`. `scripts/assert_skips.py` classifies that reason by PROSE, so a
    marker spelled with the port name alone (`OfficeConverter`) would land its
    skips in the unclassified remainder unless the platform-dependent install
    HINT happened to rescue it — the same accident `PDF-82` E5 found underneath
    `ocr`'s cells. Asserted rather than left to the hint.
    """
    spec = importlib.util.spec_from_file_location(
        "pdf82_assert_skips", REPO_ROOT / "scripts" / "assert_skips.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine_reason = module.ENGINE_REASON

    offenders = sorted(
        {
            member.arm.engine
            for member in census.gated
            if member.arm.engine is not None and not engine_reason.search(member.arm.engine)
        }
    )
    assert offenders == [], (
        f"engine marker spelling(s) {offenders} are not matched by scripts/assert_skips.py's "
        f"own ENGINE_REASON, so the skips they produce would join the UNCLASSIFIED remainder "
        f"instead of the engine-gated class the `without-engines` job counts"
    )


# --------------------------------------------------------------------------- #
# The detectors' own reds, synthetic — a detector that matched nothing would
# satisfy every assertion above on a suite that had lost all its drives.
# --------------------------------------------------------------------------- #

#: A module-shaped source with the two shapes H2 must tell apart: a body-borne
#: verb literal, and one reachable only through a module-level helper.
_SYNTHETIC_MODULE: Final[str] = """
def _argv_helper(operand):
    return ["-o", "json", "{verb}", operand, "--dry-run"]


def test_helper_borne():
    drive(argv=_argv_helper("x"))


def test_body_borne():
    drive("{verb}", "x")


def test_names_no_verb():
    drive("version", "x")
"""


def test_the_lexical_detector_sees_both_shapes_and_cries_no_wolf() -> None:
    """H2's own red and its complement, on synthetic source rather than on a
    working-tree edit. A detector that flagged every function would make the
    ratchet unmaintainable, which is how a check gets deleted rather than fixed.
    """
    verbs = engine_blind_verb_population()
    assert verbs, "engine_blind_verbs() is empty; this proof would assert nothing"
    tree = ast.parse(_SYNTHETIC_MODULE.format(verb=verbs[0]))
    direct, via_helper = lexical_drivers(tree, verbs)
    assert "test_body_borne" in direct, direct
    assert "test_helper_borne" in via_helper, (
        f"the lexical walk did not follow `_argv_helper`, so a helper-borne verb literal is "
        f"invisible to it: direct={sorted(direct)} helper={sorted(via_helper)}"
    )
    assert "test_names_no_verb" not in (direct | via_helper), (direct, via_helper)
    assert lexical_drivers(tree, verbs, hops=0)[1] == frozenset(), (
        "with zero hops the helper limb must reach nothing; a walk that ignores its own "
        "hop budget cannot be shown to depend on it"
    )


def test_the_callspec_detector_sees_a_parameter_and_ignores_a_lookalike() -> None:
    """H1's own red and its complement, over synthetic arms."""
    verbs = engine_blind_verb_population()
    assert verbs, "engine_blind_verbs() is empty; this proof would assert nothing"
    driving = Arm("m::a", "m", (verbs[0], "--out-dir"), None, None, None)
    neighbouring = Arm("m::b", "m", (f"{verbs[0]}-ish", 3), None, None, None)
    reached = {
        member.arm.nodeid: member.via for member in population((driving, neighbouring), verbs)
    }
    assert reached == {"m::a": (_VIA_CALLSPEC,)}, reached


def test_the_marker_read_distinguishes_a_gated_arm_from_an_ungated_one() -> None:
    """The gated/ungated split is the whole ratchet; a marker read that always
    returned False would make every gated arm count as debt and a ceiling raised
    to absorb it would look like ordinary growth."""
    verbs = engine_blind_verb_population()
    assert verbs, "engine_blind_verbs() is empty; this proof would assert nothing"
    gated = Arm("m::a", "m", (verbs[0],), None, None, "soffice")
    ungated = Arm("m::b", "m", (verbs[0],), None, None, None)
    assert gated.gated and not ungated.gated
    counted = collections.Counter(
        member.arm.module for member in population((gated, ungated), verbs) if not member.arm.gated
    )
    assert counted == collections.Counter({"m": 1}), counted


# --------------------------------------------------------------------------- #
# The ledger verifier, self-tested in BOTH directions (PDF-70 D4).
# --------------------------------------------------------------------------- #


def test_the_landed_ledger_verifies() -> None:
    assert gating_ratification_complaints(ENGINE_GATING_LEDGER) == []
    assert UNGATED_CEILING is ENGINE_GATING_LEDGER[-1].ceilings, (
        "the live ceiling must BE the newest record's mapping; a separately-writable literal "
        "is a ceiling that can move without a record moving with it"
    )


def test_an_empty_ledger_is_refused() -> None:
    assert gating_ratification_complaints(()) != []


def test_a_downward_ratification_is_accepted_with_no_ruling() -> None:
    """PDF-89 correction: the synthetic step is derived from
    ``ENGINE_GATING_LEDGER[0]``'s OWN ceilings, never from the live
    ``UNGATED_CEILING`` -- a key touched by more than one prior upward
    ratification (`test_or7_bulk_destructive.py`, now moved twice: PDF-84
    then PDF-89) makes ``UNGATED_CEILING[key] - 1`` land ABOVE genesis for
    that key once two raises have happened, which this test's own two-record
    synthetic ledger (genesis at index 0, as ``_RATIFICATION_DIRECTIONS``
    requires) would then read as an undeclared RISE rather than the DOWN this
    arm exists to prove accepted. Deriving from genesis directly makes every
    key a uniform one-tick-down from record 0, independent of how many real
    ratifications the live ledger has since accumulated.
    """
    ledger = (
        ENGINE_GATING_LEDGER[0],
        _GatingRatification(
            date="2026-09-17",
            spec="PDF-XX",
            direction="down",
            ceilings=MappingProxyType(
                {key: max(value - 1, 0) for key, value in ENGINE_GATING_LEDGER[0].ceilings.items()}
            ),
            reason="a drive was gated, so the debt it represented is paid",
        ),
    )
    assert gating_ratification_complaints(ledger) == []


def test_an_unruled_raise_is_refused_naming_the_key_and_both_values() -> None:
    key = next(iter(UNGATED_CEILING))
    ledger = (
        ENGINE_GATING_LEDGER[0],
        _GatingRatification(
            date="2026-09-17",
            spec="PDF-XX",
            direction="up",
            ceilings=MappingProxyType({**UNGATED_CEILING, key: UNGATED_CEILING[key] + 1}),
            reason="a new ungated drive, declared nowhere",
        ),
    )
    complaints = gating_ratification_complaints(ledger)
    assert any("NO ruling" in complaint and key in complaint for complaint in complaints), (
        complaints
    )
