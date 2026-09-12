"""PDF-39 — the `schema_version: 1` envelope contract, in one place.

`README.md`'s `## Output contract` calls the structured shapes **public API
from v1.0.0**. This module is the instrument behind that sentence. It holds
four members that share a *surface* and a *deadline* — one public envelope,
one freeze window — and nothing else; each has its own cause, its own
mechanism, and its own independently failable criterion, and the criteria are
written so they cannot hide each other.

THE RULING, IN FOUR LINES (Design D0)
--------------------------------------
========================  =========================================  ===========
Member                    Ruling                                     Mechanism
========================  =========================================  ===========
1 · two permission        **DOCUMENT.** Both vocabularies frozen     addition +
    vocabularies          verbatim; one derived mapping constant;    docs
    (`B-066`)             one published table
2 · 3 keys missing on     **UNIFY BY ADDITION.** `exit_code`,        addition
    3 leaves (`B-143`)    `warnings`, `duration_ms` added to
                          `doctor`, `info`, `meta get`
3 · two injection paths   **KEEP BOTH, ASSERT AGREEMENT.** The       guard only
    for one key           injection is not removed; a guard proves
    (`B-201`)             one value and forbids shadowing
4 · three collection      **ALIAS BY ADDITION.** `items` supplied    addition
    names (`B-235`)       to `-o json`; `ports` and `documents`
                          retained as primary
========================  =========================================  ===========

Every cell is `schema_version`-1-legal under X-410: **no rename, no removal,
no type change, no meaning change.** A consumer written against `v0.2.0` keeps
working against everything PDF-39 produced, because every change is a key
appearing where none was before.

`schema_version` STAYS `1`, AND THE NEXT INCREMENT HAS A NAMED TRIGGER (D5)
---------------------------------------------------------------------------
It increments on the first change a name-keyed consumer cannot survive, which
is exactly four things: a published key is **renamed**; a published key is
**removed**; a published key's **type** changes (including ``[]`` -> ``null``,
or scalar -> object); or a published key's **meaning** changes while its name
and type stay the same. **Adding a key never triggers it.** Adding a verb, an
item field or an output format never triggers it. An increment is coupled to a
major version bump and the two move together or not at all.

The first three are mechanical, via :data:`REGISTER_PATH`: it freezes, per
invocable leaf, the sorted top-level ``-o json`` key set and the sorted key
set of an ``-o ndjson`` line, **as measured at `d03bee3` (= tag `v0.2.0`)
before any of PDF-39's edits**, and the live envelope must be a **SUPERSET** of
it. Superset and not equality, deliberately: an addition is a strict superset
while a rename or a removal is not, so additive change stays cheap and
destructive change stops. The fourth — a meaning change — is **not**
mechanically detectable, and this module says so rather than pretending; its
control is human, and it is the register's own docstring, `CLAUDE.md` rule 3,
and the review of any diff touching a ``to_dict()``.

WHY A NEW FILE, AND WHAT EXTENDS IT
------------------------------------
`tests/test_cli_contract.py` is PDF-17's and is consumed here, never
restructured. PDF-40 changes the batch envelope's shape and **extends this
module**; that is the intended seam, and a separate file makes the extension
an append rather than a merge. The eight clauses PDF-40 inherits are the
spec's §D6, and the two this module enforces directly are clause 2 (`items` is
the universal collection key) and clause 4 (no item may carry
``schema_version``, ``verb`` or ``dry_run``).

THE TWO HAZARDS THIS MODULE IS DESIGNED AGAINST
------------------------------------------------
1. **A register that covers nine leaves and claims to cover the envelope.**
   `discover_verbs()` supplies the denominator and
   :func:`test_ac19_the_register_covers_every_leaf_the_harness_can_invoke`
   fails when the register is narrower than it. An uncovered leaf is a stated
   gap, never a leaf silently asserted to be fine.
2. **A `schema_version` guard that reads the value from the same constant the
   renderer reads** — the `B-080` tautology family. Every assertion below
   reads the value out of the CLI's real stdout, through ``run_cli()``, and
   compares it to ``models.SCHEMA_VERSION``. It never compares the constant to
   itself.

PDF-54 — THE FAILURE ARM, AND WHY IT IS A NEW ARM RATHER THAN A FIFTH MEMBER
-----------------------------------------------------------------------------
Every member above is measured on a run that **succeeds**. The error
envelope — the shape a consumer actually branches into — was frozen nowhere:
``kind = "no_input"`` (``errors.py``) appeared in no test assertion at all
before this extension. PDF-54 adds :data:`FAILURE_ARM` to the register
(:const:`no_input_population` supplies the denominator, DERIVED from a
positional-``argument`` predicate and never from ``VerbSpec.takes_input_paths``,
which is ``click.Path``-typed and silently drops ``merge``), asserts
kind-independence once from ``errors.py``'s own class tree rather than as a
per-(leaf × kind) matrix, and repairs the regeneration node so the register's
own ``_meta`` is DERIVED FROM GIT at the moment of regeneration rather than
preserved from ``PDF-39``'s original run. It is not a fifth member of the
table above: it freezes a different envelope entirely (the one the base
exception class renders, never :class:`OperationResult`), so it gets its own
arm key rather than a manufactured pair with ``json``/``ndjson_line``.

A NOTE ON WHY THIS MODULE STILL ALIASES THE BASE ERROR IMPORT
------------------------------------------------------------------
D4's kind-independence walk needs the base exception class object, imported
once (``errors.py``) and aliased immediately to ``_BASE_ERROR`` — every
other reference below uses the alias. **PDF-57 (2026-09-12) retires the
frozen name this note used to protect** — the base class carries its
post-rename name now, a live, moving population with no byte-frozen count
to avoid inflating. The alias is kept anyway, unchanged, because it is
still the right shape for the same underlying reason: one import site, one
alias, everything else in this module reads the alias rather than
re-spelling the class name at each use site.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pytest

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_tooling.adapters.pypdf_structure import _PERMISSION_BITS  # noqa: E402
from pdf_tooling.errors import PdfToolingError as _BASE_ERROR  # noqa: E402
from pdf_tooling.models import SCHEMA_VERSION  # noqa: E402
from pdf_tooling.output.json import render_error_json  # noqa: E402
from pdf_tooling.ports.structure import (  # noqa: E402
    ALWAYS_GRANTED_TOKENS,
    PERMISSION_TOKEN_MAP,
    PERMISSION_TOKENS,
)
from registry import (  # noqa: E402
    INVOCATIONS,
    REPO_ROOT,
    Invocation,
    discover_verbs,
    no_input_population,
    rerun_hint,
    run_cli,
)

REGISTER_PATH: Final[Path] = REPO_ROOT / "tests" / "golden" / "envelope_keys.json"
README: Final[Path] = REPO_ROOT / "README.md"
TESTING_MD: Final[Path] = REPO_ROOT / "TESTING.md"

#: PDF-54 D1 -- the register's failure arm, recommended spelling: never
#: confusable with a success arm, listed in `_meta.arms`, asserted by its own
#: loop iteration below. `render_error_json` serves it byte-identically to
#: `-o json` and `-o ndjson` (E3), so there is no `error_ndjson` sibling.
FAILURE_ARM: Final[str] = "error_json"

#: PDF-54 E5/E10 -- the `_meta.spec` this cycle's regeneration is authorised
#: under (D6/TESTING.md case 3).
REGENERATING_SPEC: Final[str] = "PDF-54"

#: X-709 ruling 3 — the single sentence that makes the register worth
#: having, quoted verbatim from `tests/golden/envelope_keys.json` at
#: `89a4f1d` and asserted BYTE-IDENTICAL by `test_ac9_the_forbidden_clause_
#: survives_byte_identical` below. It never changes across a regeneration.
FORBIDDEN_CLAUSE: Final[str] = (
    "See TESTING.md. A rename or a removal is the ONLY thing a superset "
    "assertion can catch, and it is caught by this file being older than "
    "the change. The sanctioned ways to make it green are (a) an ADDITION, "
    "which is already a superset and needs no regeneration at all, or (b) "
    "a PM-approved schema_version increment (models.py SCHEMA_VERSION), "
    "which is not an engineer's call."
)

#: The env var that regenerates :data:`REGISTER_PATH`. **Deliberately NOT
#: `--update-golden`**: that flag is aimed at ordinary goldens and a regenerated
#: envelope register is not an ordinary golden — it is the only evidence that a
#: public key was not renamed or removed, and regenerating it is exactly how
#: that evidence would be destroyed by accident. See `TESTING.md`.
REGENERATE_ENV: Final[str] = "PDF_TOOLING_ENVELOPE_REGISTER_REGENERATE"

#: The three fields `render_ndjson` injects into every streamed line
#: (`output/json.py`). An item dict carrying one would silently shadow the
#: envelope-level value on that path. §D6 clause 4.
INJECTED_ENVELOPE_FIELDS: Final[tuple[str, ...]] = ("schema_version", "verb", "dry_run")

#: The three envelope-level keys member 2 unified. Measured at `d03bee3`:
#: 23 of 26 leaves carried them, 3 omitted them (`doctor`, `info`, `meta get`).
#: `meta set` was always a CARRIER — the population is per LEAF and `meta` is
#: not atomic, so a guard built to the ledger's "22 of 25" would have
#: mis-predicted it.
UNIFIED_ENVELOPE_KEYS: Final[tuple[str, ...]] = ("exit_code", "warnings", "duration_ms")

#: Member 2's three former omitters, kept by name only so the historical claim
#: is legible. Nothing below reads this to DECIDE anything — the omitter set is
#: enumerated from the live registry, so a future verb that omits a key reddens
#: with no author action.
FORMER_OMITTERS: Final[tuple[str, ...]] = ("doctor", "info", "meta get")


# --------------------------------------------------------------------------- #
# The shared observation. ONE definition, used by every member and by the
# register, so a leaf cannot be observed one way here and another way there.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Observation:
    """One leaf's two rendered envelopes, parsed, plus the real exit statuses."""

    verb: str
    json_payload: dict[str, Any] | None
    json_returncode: int
    json_stdout: str
    ndjson_lines: tuple[dict[str, Any], ...]
    ndjson_returncode: int
    argv: tuple[str, ...]

    def register_entry(self) -> dict[str, list[str] | None]:
        """Exactly what :data:`REGISTER_PATH` freezes for this leaf."""
        return {
            "json": sorted(self.json_payload) if self.json_payload is not None else None,
            "ndjson_line": sorted(self.ndjson_lines[0]) if self.ndjson_lines else None,
        }


def _parse_object(text: str) -> dict[str, Any] | None:
    """*text* as a JSON object, or ``None`` when it is empty or not one.

    Empty stdout under a structured format is itself a finding, so this
    returns ``None`` and lets the caller assert rather than raising a
    ``JSONDecodeError`` on the caller's behalf and burying the real signal.
    """
    text = text.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def observe_envelope_keys(verb: str, corpus: object, tmp_root: Path) -> Observation:
    """Run *verb*'s registered invocation once per structured format.

    Each format gets its own scratch directory and its own freshly built argv:
    several registered invocations name a destination, and a second run into
    the same directory would meet its own output and measure a no-clobber
    refusal instead of the envelope.
    """
    invocation: Invocation = INVOCATIONS[verb]
    slug = verb.replace(" ", "_")

    json_dir = tmp_root / f"{slug}-json"
    json_dir.mkdir(parents=True, exist_ok=True)
    argv = invocation.build(corpus, json_dir)
    as_json = run_cli(verb, "-o", "json", *argv, cwd=json_dir)

    nd_dir = tmp_root / f"{slug}-ndjson"
    nd_dir.mkdir(parents=True, exist_ok=True)
    as_ndjson = run_cli(verb, "-o", "ndjson", *invocation.build(corpus, nd_dir), cwd=nd_dir)
    lines = tuple(
        parsed
        for line in as_ndjson.stdout.splitlines()
        if line.strip() and (parsed := _parse_object(line)) is not None
    )

    return Observation(
        verb=verb,
        json_payload=_parse_object(as_json.stdout),
        json_returncode=as_json.returncode,
        json_stdout=as_json.stdout,
        ndjson_lines=lines,
        ndjson_returncode=as_ndjson.returncode,
        argv=tuple(argv),
    )


@dataclass(frozen=True)
class FailureObservation:
    """One leaf's no-input failure envelope — PDF-54 D1/D3.

    Measured on `-o json` only, deliberately: D1/E3 found `render_error_json`
    serves `-o json` and `-o ndjson` BYTE-IDENTICALLY on the failure path, so
    a second run would freeze the same shape twice under two names and prove
    nothing an `-o json` run does not already prove.
    """

    verb: str
    payload: dict[str, Any] | None
    kind: str | None
    returncode: int
    argv: tuple[str, ...]

    def register_entry(self) -> dict[str, list[str]] | None:
        """The TWO key sets D1 rules the arm freezes — the envelope's own
        top level, and the nested `error` object, independently. Freezing
        only the container would freeze nothing: `error`'s key set IS the
        published failure contract (the base exception class's `to_dict()`)."""
        if self.payload is None:
            return None
        error = self.payload.get("error")
        return {
            "top": sorted(self.payload),
            "error": sorted(error) if isinstance(error, dict) else [],
        }


def observe_failure_envelope(verb: str, corpus: object, tmp_root: Path) -> FailureObservation:
    """Run *verb*'s purpose-built `no_input_build` once, on `-o json`.

    Deliberately NOT gated on `_require_engine()` (AC5/E8): the no-input
    check fires before any engine is ever demanded, on every leaf, so
    skipping this observation on a lean host would cover fewer leaves than
    the register claims and be green about the gap.
    """
    invocation: Invocation = INVOCATIONS[verb]
    build = invocation.no_input_build
    if build is None:
        return FailureObservation(verb=verb, payload=None, kind=None, returncode=-1, argv=())
    slug = verb.replace(" ", "_")
    run_dir = tmp_root / f"{slug}-no-input"
    run_dir.mkdir(parents=True, exist_ok=True)
    argv = build(corpus, run_dir)
    result = run_cli(verb, "-o", "json", *argv, cwd=run_dir)
    payload = _parse_object(result.stdout)
    kind: str | None = None
    if payload is not None:
        error = payload.get("error")
        if isinstance(error, dict):
            raw_kind = error.get("kind")
            kind = raw_kind if isinstance(raw_kind, str) else None
    return FailureObservation(
        verb=verb, payload=payload, kind=kind, returncode=result.returncode, argv=tuple(argv)
    )


def failure_arm_population() -> tuple[str, ...]:
    """PDF-54 D2 — every leaf with a no-input failure arm to reach.

    `no_input_population()` supplies the denominator, DERIVED from a
    positional-`argument` predicate of ANY type and never from
    `VerbSpec.takes_input_paths` (`click.Path`-typed, silently drops `merge`
    — E12). Kept as its own function, mirroring `invocable_leaves()`'s own
    shape, so the population is computed once and re-used rather than
    re-derived per call site.
    """
    return no_input_population()


def invocable_leaves() -> tuple[str, ...]:
    """Every discovered leaf the harness can build an argv for, sorted.

    The denominator is `discover_verbs()`, never a typed list, so a verb
    registered tomorrow joins this population without an author touching it.
    """
    return tuple(
        sorted(
            spec.name for spec in discover_verbs() if not spec.is_group and spec.name in INVOCATIONS
        )
    )


def uninvocable_leaves() -> tuple[str, ...]:
    """Discovered leaves with no `INVOCATIONS` row — a stated gap, never a
    silent drop. `tests/registry.py`'s own anti-lapse guard
    (`test_every_verb_is_registered`) already fails the suite when this is
    non-empty, so it is expected to be `()`; it is computed rather than
    assumed so that AC19's published coverage is a measurement."""
    return tuple(
        sorted(
            spec.name
            for spec in discover_verbs()
            if not spec.is_group and spec.name not in INVOCATIONS
        )
    )


def _require_engine(verb: str) -> None:
    """Skip VISIBLY, naming the engine, when *verb*'s row declares one that
    does not resolve. Resolved through the same `ports.resolve()` the CLI uses
    — never an independent `shutil.which` — exactly as `tests/conftest.py`'s
    own `requires` marker does. An absent engine skips with a reason; it never
    passes."""
    port = INVOCATIONS[verb].requires_engine
    if port is None:
        return
    from pdf_tooling.ports import resolve

    if not resolve(port).available:
        pytest.skip(f"{verb}: the {port} engine does not resolve on this host")


@pytest.fixture(scope="session")
def envelope(corpus, tmp_path_factory) -> Callable[[str], Observation]:
    """A memoized `verb -> Observation` reader.

    Memoized rather than eagerly computed over all 26 leaves: `-n auto` in
    `addopts` distributes these tests, and an eager fixture would make every
    xdist worker pay for every leaf. A worker observes only the leaves its
    own tests ask for, once each.
    """
    root = tmp_path_factory.mktemp("envelope-contract")
    cache: dict[str, Observation] = {}

    def read(verb: str) -> Observation:
        if verb not in cache:
            cache[verb] = observe_envelope_keys(verb, corpus, root)
        return cache[verb]

    return read


@pytest.fixture(scope="session")
def failure_envelope(corpus, tmp_path_factory) -> Callable[[str], FailureObservation]:
    """A memoized `verb -> FailureObservation` reader — PDF-54's sibling to
    `envelope` above, on the identical memoization rationale (`-n auto`)."""
    root = tmp_path_factory.mktemp("no-input-contract")
    cache: dict[str, FailureObservation] = {}

    def read(verb: str) -> FailureObservation:
        if verb not in cache:
            cache[verb] = observe_failure_envelope(verb, corpus, root)
        return cache[verb]

    return read


LEAVES = invocable_leaves()
FAILURE_LEAVES = failure_arm_population()


def test_the_leaf_population_is_not_empty() -> None:
    """The anti-lapse assertion. Every leaf-parameterized test below collects
    zero cases — and passes — over an empty population."""
    assert len(LEAVES) >= 20, (
        f"the leaf walk found {len(LEAVES)}; every parameterized guard in this "
        "module would pass vacuously"
    )


# --------------------------------------------------------------------------- #
# Member 1 — the two permission vocabularies (`B-066`). AC1-AC4.
# --------------------------------------------------------------------------- #


def info_vocabulary() -> tuple[str, ...]:
    """`info`'s published permission spelling, read from the decoder that
    produces it rather than transcribed."""
    return tuple(name for name, _ in _PERMISSION_BITS)


def test_ac1_the_two_permission_vocabularies_are_a_bijection_through_the_map() -> None:
    """AC1 — the static arm. RED, both directions: append a ninth token to
    either `_PERMISSION_BITS` or `PERMISSION_TOKENS` in a scratch tree and this
    fails NAMING the unmapped token.

    Applying `PERMISSION_TOKEN_MAP` to `PERMISSION_TOKENS` must yield `info`'s
    vocabulary exactly, as a set. The five tokens absent from the map are
    spelled identically on both surfaces and pass through unchanged.
    """
    info_vocab = info_vocabulary()
    translated = {PERMISSION_TOKEN_MAP.get(token, token) for token in PERMISSION_TOKENS}

    unmapped = sorted(translated - set(info_vocab))
    assert not unmapped, (
        f"`--allow`/`permissions` token(s) {unmapped} have no counterpart in `info`'s "
        f"vocabulary {sorted(info_vocab)}. Either the token was respelled on one "
        f"surface only, or a new token needs a PERMISSION_TOKEN_MAP row."
    )
    orphans = sorted(set(info_vocab) - translated)
    assert not orphans, (
        f"`info` publishes token(s) {orphans} that nothing in PERMISSION_TOKENS maps "
        f"onto. A consumer crossing from `permissions` to `info` cannot name them."
    )

    assert len(PERMISSION_TOKENS) == len(info_vocab), (
        f"the two vocabularies have different lengths: `--allow` has "
        f"{len(PERMISSION_TOKENS)}, `info` has {len(info_vocab)}"
    )

    stray_keys = sorted(set(PERMISSION_TOKEN_MAP) - set(PERMISSION_TOKENS))
    assert not stray_keys, f"PERMISSION_TOKEN_MAP keys {stray_keys} are not `--allow` tokens"
    stray_values = sorted(set(PERMISSION_TOKEN_MAP.values()) - set(info_vocab))
    assert not stray_values, f"PERMISSION_TOKEN_MAP values {stray_values} are not `info` tokens"

    assert len(set(PERMISSION_TOKEN_MAP.values())) == len(PERMISSION_TOKEN_MAP), (
        "PERMISSION_TOKEN_MAP's image has a collision; two `--allow` tokens claim the "
        "same `info` spelling, so the crossing is not reversible"
    )
    identities = sorted(key for key, value in PERMISSION_TOKEN_MAP.items() if key == value)
    assert not identities, (
        f"PERMISSION_TOKEN_MAP carries identity row(s) {identities}. The map holds the "
        f"DIVERGING pairs only; an identical spelling belongs in neither the map nor "
        f"README's mapped rows."
    )


def test_ac1_the_always_granted_token_crosses_the_map_too() -> None:
    """`ALWAYS_GRANTED_TOKENS` is `--allow`-spelled and `README.md` singles it
    out for a reader; its `info`-side counterpart is `extract-accessibility`.
    A mapping is required to reason about even the always-granted case, which
    is why the pair is asserted rather than assumed."""
    for token in ALWAYS_GRANTED_TOKENS:
        assert token in PERMISSION_TOKENS, f"{token!r} is not an `--allow` token"
        assert PERMISSION_TOKEN_MAP.get(token, token) in info_vocabulary(), (
            f"the always-granted token {token!r} does not cross into `info`'s vocabulary"
        )


@pytest.mark.e2e
@pytest.mark.parametrize("allow", sorted(PERMISSION_TOKEN_MAP))
def test_ac2_info_and_permissions_report_the_same_bits_through_the_map(
    allow: str, corpus, tmp_path: Path
) -> None:
    """AC2 — the BEHAVIOURAL arm, and the one that would have caught the defect.

    It compares the two PUBLIC surfaces against each other rather than either
    against a source comment: `info -o json` and `permissions -o json` are run
    against the same encrypted artifact, and `permissions`' tokens are
    translated through the map. `B-066`'s ledger framing — *"`info` emits …
    while `--allow` takes …"* — understates this: the disagreement is between
    two OUTPUT surfaces, so a consumer diffing one against the other sees three
    phantom differences on every encrypted document.

    **PARAMETERIZED OVER EACH DIVERGING TOKEN ALONE, AND THAT IS NOT
    COSMETIC.** A single arm encrypting with every diverging permission at once
    compares two SETS, and a set comparison is blind to a PERMUTATION of the
    map's values: swap two entries and the translated set is unchanged.
    Measured, not reasoned — swapping `forms` and `accessibility` in a scratch
    tree left a single-fixture version of this arm GREEN while the map was
    plainly wrong. Granting one diverging token at a time breaks that symmetry,
    because the two tokens of a swapped pair are then no longer both present.

    RED: change one map value, or swap two, in a scratch tree; at least one of
    these arms fails naming the tokens that failed to translate.
    """
    owner_pw = tmp_path / "owner.pw"
    owner_pw.write_text("pdf39-owner-pw")
    owner_pw.chmod(0o600)
    encrypted = tmp_path / "encrypted.pdf"

    made = run_cli(
        "encrypt",
        str(corpus.path("single_page")),
        "--owner-password-file",
        str(owner_pw),
        "--allow",
        allow,
        "-O",
        str(encrypted),
        "-o",
        "json",
        cwd=tmp_path,
    )
    assert made.returncode == 0, (made.stdout, made.stderr)

    from_info = run_cli("info", str(encrypted), "-o", "json", cwd=tmp_path)
    from_permissions = run_cli("permissions", str(encrypted), "-o", "json", cwd=tmp_path)
    assert from_info.returncode == 0, from_info.stderr
    assert from_permissions.returncode == 0, from_permissions.stderr

    info_tokens = set(json.loads(from_info.stdout)["documents"][0]["permissions"])
    granted = json.loads(from_permissions.stdout)["items"][0]["detail"]["granted"]
    assert granted, "the `permissions` arm reported nothing to translate"

    crossed = {PERMISSION_TOKEN_MAP.get(token, token) for token in granted}
    assert crossed == info_tokens, (
        f"--allow {allow}: the two public surfaces disagree after translation. "
        f"`permissions` reported {sorted(granted)}, which crosses to {sorted(crossed)}; "
        f"`info` published {sorted(info_tokens)}. Failed to translate: "
        f"{sorted(crossed ^ info_tokens)}. Repro: "
        f"{rerun_hint(['permissions', str(encrypted)])}"
    )
    assert crossed != set(granted), (
        f"--allow {allow}: the translation was a no-op, so this arm did not exercise "
        f"the map at all -- the granted set must contain at least one DIVERGING token"
    )


_README_TABLE_ROW = re.compile(
    r"^\|\s*`(?P<allow>[a-z-]+)`\s*\|\s*`(?P<info>[a-z-]+)`\s*\|\s*`(?P<bit>\d+)`\s*\|\s*$"
)


def readme_permission_table() -> tuple[tuple[str, str, int], ...]:
    """The published mapping table, parsed out of `README.md`.

    The table is DERIVED, never transcribed: a hand-maintained table in a
    document guarded by nothing is this product's most-filed defect class.
    """
    rows: list[tuple[str, str, int]] = []
    for line in README.read_text().splitlines():
        match = _README_TABLE_ROW.match(line)
        if match:
            rows.append((match["allow"], match["info"], int(match["bit"])))
    return tuple(rows)


def test_ac3_the_readme_permission_table_derives_from_the_map() -> None:
    """AC3. RED: alter one cell of the README table and this fails naming the row.

    **This arm lives here rather than in `tests/test_docs_antirot.py`'s
    `DERIVED_FIGURES` registry, and the reason is the registry's own shape.**
    A `DerivedFigure` binds ONE anchored substring of a document to a callable
    returning ONE normalised string, and asserts string equality after
    whitespace collapse. The claim here is not a string: it is an eight-row,
    three-column table whose assertion is SET equality against a dict and a
    tuple, plus a partition into mapped and identical rows. Forcing it into
    `derive` would mean serialising the whole table to a single string and
    comparing byte-for-byte, which reddens on a column-width edit that changes
    nothing a reader relies on, and which names no row when it fails. The
    registry is consumed elsewhere and is not widened here.
    """
    rows = readme_permission_table()
    assert rows, (
        "README.md carries no parseable permission mapping table; the published "
        "mapping this whole member exists to ship is absent"
    )

    allow_column = [row[0] for row in rows]
    info_column = [row[1] for row in rows]
    assert len(set(allow_column)) == len(allow_column), (
        f"the README table repeats an `--allow` token: {sorted(allow_column)}"
    )
    assert set(allow_column) == set(PERMISSION_TOKENS), (
        f"the README table's `--allow` column is {sorted(set(allow_column))}, "
        f"but PERMISSION_TOKENS is {sorted(PERMISSION_TOKENS)}"
    )
    assert set(info_column) == set(info_vocabulary()), (
        f"the README table's `info` column is {sorted(set(info_column))}, "
        f"but `info` publishes {sorted(info_vocabulary())}"
    )

    documented_map = {allow: info for allow, info, _ in rows if allow != info}
    assert documented_map == PERMISSION_TOKEN_MAP, (
        f"the README table's MAPPED rows are {documented_map}, but "
        f"PERMISSION_TOKEN_MAP is {dict(PERMISSION_TOKEN_MAP)}. The rows that differ: "
        f"{sorted(set(documented_map.items()) ^ set(PERMISSION_TOKEN_MAP.items()))}"
    )
    documented_identical = {allow for allow, info, _ in rows if allow == info}
    shared = set(PERMISSION_TOKENS) - set(PERMISSION_TOKEN_MAP)
    assert documented_identical == shared, (
        f"the README table says {sorted(documented_identical)} are spelled identically "
        f"on both surfaces; the source says {sorted(shared)}"
    )

    documented_bits = {allow: bit for allow, _, bit in rows}
    real_bits = {
        allow: bit
        for allow in PERMISSION_TOKENS
        for name, bit in _PERMISSION_BITS
        if name == PERMISSION_TOKEN_MAP.get(allow, allow)
    }
    assert documented_bits == real_bits, (
        f"the README table's ISO 32000-1 bit column is {documented_bits}; "
        f"`_PERMISSION_BITS` says {real_bits}. Rows that differ: "
        f"{sorted(set(documented_bits.items()) ^ set(real_bits.items()))}"
    )


@pytest.mark.e2e
@pytest.mark.parametrize("token", sorted(PERMISSION_TOKEN_MAP.values()))
def test_ac4_the_allow_input_vocabulary_was_not_widened(token: str, tmp_path: Path) -> None:
    """AC4 — a CRITERION BY ABSENCE, so a later reader can prove the input
    vocabulary was not widened in cycle 3.

    Teaching `--allow` to also accept `info`'s spellings is X-410-legal and was
    considered and REFUSED (the ruling is recorded beside `PERMISSION_TOKEN_MAP`
    in `ports/structure.py`): an accepted input token is permanent from v1.0.0
    and could never be withdrawn without a major bump, so it would spend an
    irreversible budget to close a gap a documented table closes reversibly.

    RED: implement the alias and this fails.
    """
    owner_pw = tmp_path / "owner.pw"
    owner_pw.write_text("pdf39-owner-pw")
    owner_pw.chmod(0o600)
    result = run_cli(
        "encrypt",
        str(REPO_ROOT / "testdata" / "malformed.pdf"),
        "--owner-password-file",
        str(owner_pw),
        "--allow",
        token,
        "-O",
        str(tmp_path / "out.pdf"),
        cwd=tmp_path,
    )
    assert result.returncode == 2, (
        f"`--allow {token}` exited {result.returncode}, not 2. The `info` spelling is "
        f"NOT an accepted input token and PDF-39 ruled that it stays that way; adding "
        f"it is a permanent public-API widening and is the PM's call, not an "
        f"engineer's. stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# --------------------------------------------------------------------------- #
# Member 2 — the three missing envelope keys (`B-143`). AC5, AC6, AC8.
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
@pytest.mark.parametrize("verb", FORMER_OMITTERS)
def test_ac5_the_three_former_omitters_now_carry_all_three_keys(verb: str, envelope) -> None:
    """AC5. The RED was FREE and was observed at `f83b757` before any edit: all
    three keys were absent from all three of these envelopes, and the three
    pre-change envelopes are recorded verbatim in the spec's Implementation
    Log as this criterion's positive control."""
    _require_engine(verb)
    payload = envelope(verb).json_payload
    assert payload is not None, f"{verb} -o json produced no parseable envelope"
    missing = [key for key in UNIFIED_ENVELOPE_KEYS if key not in payload]
    assert not missing, f"{verb} -o json omits {missing}"
    assert isinstance(payload["warnings"], list), (
        f"{verb}'s `warnings` is {type(payload['warnings']).__name__}, not a list. "
        f"`[]` when empty -- never null, never omitted."
    )
    assert isinstance(payload["duration_ms"], int) and not isinstance(
        payload["duration_ms"], bool
    ), f"{verb}'s `duration_ms` is {payload['duration_ms']!r}, not an integer"
    assert isinstance(payload["exit_code"], int) and not isinstance(payload["exit_code"], bool), (
        f"{verb}'s `exit_code` is {payload['exit_code']!r}, not an integer"
    )


@pytest.mark.e2e
@pytest.mark.parametrize("verb", LEAVES)
def test_ac8_no_leaf_omits_an_envelope_level_key(verb: str, envelope) -> None:
    """AC8 — the omitter set, enumerated from the LIVE registry rather than
    from a typed list, so it goes to zero at the end of this spec and a future
    verb that omits a key turns this red with no author action.

    The population is stated **per leaf, not per top-level command**: `main.py`
    registers 25 top-level commands for 26 leaves, and `meta set` is a CARRIER
    while `meta get` was an omitter. A guard built to the ledger's *"22 of 25"*
    would either have written a red control that never fires on `meta set` or
    been surprised by a green it did not predict.

    RED: strip `warnings` from any one leaf's payload and this fails naming it.
    """
    _require_engine(verb)
    payload = envelope(verb).json_payload
    assert payload is not None, f"{verb} -o json produced no parseable envelope"
    missing = [key for key in UNIFIED_ENVELOPE_KEYS if key not in payload]
    assert not missing, (
        f"{verb} -o json omits {missing}. All 26 leaves publish the same three "
        f"envelope-level keys since PDF-39; a new verb inherits the obligation."
    )


@pytest.mark.e2e
@pytest.mark.parametrize("verb", LEAVES)
def test_ac6_the_envelope_exit_code_equals_the_real_exit_status(verb: str, envelope) -> None:
    """AC6 — the envelope's `exit_code` equals the process's ACTUAL exit
    status, asserted rather than assumed, over every invocable leaf.

    The two are derived independently in source on all three of member 2's
    verbs: `build_payload` computes the code from the same facts the command's
    own `typer.Exit` is computed from, never by copying the number the process
    was handed. A payload that echoed the process's code could not disagree
    with it and this assertion would be a `B-080` tautology.

    RED: hard-code `"exit_code": 0` in one of the three payloads and the arm
    that exercises a non-zero path fails naming the verb and both values.
    """
    _require_engine(verb)
    observed = envelope(verb)
    payload = observed.json_payload
    assert payload is not None, f"{verb} -o json produced no parseable envelope"
    assert payload["exit_code"] == observed.json_returncode, (
        f"{verb}: the envelope says exit_code={payload['exit_code']} while the process "
        f"exited {observed.json_returncode}. Repro: "
        f"{rerun_hint([verb, '-o', 'json', *observed.argv])}"
    )


@pytest.mark.e2e
def test_ac6_doctor_reports_three_under_strict_with_an_engine_hidden(tmp_path: Path) -> None:
    """AC6's non-zero arm for `doctor`. `--strict` with any port unavailable is
    exit 3 (`ENGINE_MISSING`), and the envelope must say so too.

    The two system binaries are hidden by pointing `PATH` at an empty
    directory — `tests/test_doctor.py`'s own mechanism, and it never renames,
    moves or chmods anything on the host. The CLI is still reachable because
    `run_cli` spawns it through an absolute path.
    """
    empty = tmp_path / "nothing"
    empty.mkdir()
    env = {**os.environ, "PATH": str(empty)}
    strict = run_cli("doctor", "--strict", "-o", "json", cwd=tmp_path, env=env)
    payload = json.loads(strict.stdout)
    assert strict.returncode == 3, (strict.returncode, strict.stderr)
    assert payload["exit_code"] == 3, (
        f"doctor --strict exited {strict.returncode} while its envelope said "
        f"exit_code={payload['exit_code']}"
    )
    assert all(isinstance(warning, str) for warning in payload["warnings"])

    plain = run_cli("doctor", "-o", "json", cwd=tmp_path, env=env)
    assert plain.returncode == 0, plain.stderr
    assert json.loads(plain.stdout)["exit_code"] == 0, (
        "plain `doctor` exits 0 even with engines missing, and the envelope must "
        "agree -- this is the arm that makes the strict/plain distinction a "
        "distinction rather than a constant"
    )


@pytest.mark.e2e
def test_ac6_info_reports_the_batch_code_on_several_inputs(corpus, tmp_path: Path) -> None:
    """AC6's non-zero arm for `info`, on `PLAN.md` §5.4's batch rule as quoted
    at `cli/cmd_info.py`: a failing input is recorded, the run continues, and
    the run exits 1 at the end with a per-input status."""
    good = corpus.path("single_page")
    result = run_cli(
        "info",
        str(good),
        str(REPO_ROOT / "testdata" / "malformed.pdf"),
        "-o",
        "json",
        cwd=tmp_path,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 1, (result.returncode, result.stderr)
    assert payload["exit_code"] == 1, (
        f"info exited {result.returncode} on a mixed batch while its envelope said "
        f"exit_code={payload['exit_code']}"
    )
    assert len(payload["documents"]) == 2


@pytest.mark.e2e
def test_ac6_info_reports_a_single_inputs_own_code(tmp_path: Path) -> None:
    """A single input reports its OWN code — `1` for a malformed document —
    which is what keeps 1/4/6 distinguishable at all."""
    result = run_cli(
        "info", str(REPO_ROOT / "testdata" / "malformed.pdf"), "-o", "json", cwd=tmp_path
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["exit_code"] == 1, payload


@pytest.mark.e2e
@pytest.mark.parametrize("verb", FORMER_OMITTERS)
def test_ac6_dry_run_mirrors_the_real_run_on_both_observables(
    verb: str, corpus, tmp_path: Path
) -> None:
    """AC6 — OR-7 / X-185, BOTH observables. `--dry-run` reports the same
    `exit_code` the real run returns **and** the same key set. The values may
    differ; the shape does not.

    A code-only comparison is exactly the trap X-185 names: it agrees on the
    integer while the real run's stdout is empty, so the key set is asserted
    beside it.
    """
    _require_engine(verb)
    argv = INVOCATIONS[verb].build(corpus, tmp_path)
    dry = run_cli(verb, "--dry-run", *argv, "-o", "json", cwd=tmp_path)
    real = run_cli(verb, *INVOCATIONS[verb].build(corpus, tmp_path), "-o", "json", cwd=tmp_path)

    assert dry.returncode == real.returncode, (
        f"{verb}: --dry-run exited {dry.returncode}, the real run exited {real.returncode}"
    )
    dry_payload = _parse_object(dry.stdout)
    real_payload = _parse_object(real.stdout)
    assert dry_payload is not None and real_payload is not None, (dry.stdout, real.stdout)
    assert sorted(dry_payload) == sorted(real_payload), (
        f"{verb}: --dry-run's envelope shape is {sorted(dry_payload)}, the real run's is "
        f"{sorted(real_payload)}. OR-7 binds the SHAPE as well as the code."
    )
    assert dry_payload["exit_code"] == dry.returncode
    assert real_payload["exit_code"] == real.returncode


# --------------------------------------------------------------------------- #
# Member 3 — the two injection paths for one key (`B-201`). AC9-AC12.
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
@pytest.mark.parametrize("verb", LEAVES)
def test_ac9_every_leaf_publishes_the_one_schema_version(verb: str, envelope) -> None:
    """AC9 — the value is read out of the CLI's REAL STDOUT and compared to
    `models.SCHEMA_VERSION`, on both structured formats, whichever injection
    path supplied it. It is never the constant compared to itself.

    RED: rebind `SCHEMA_VERSION` to `2` in a scratch tree without touching the
    register and this fails naming the leaf and both values.
    """
    _require_engine(verb)
    observed = envelope(verb)
    payload = observed.json_payload
    assert payload is not None, f"{verb} -o json produced no parseable envelope"
    assert payload.get("schema_version") == SCHEMA_VERSION, (
        f"{verb} -o json published schema_version={payload.get('schema_version')!r}; "
        f"models.SCHEMA_VERSION is {SCHEMA_VERSION}"
    )
    for index, line in enumerate(observed.ndjson_lines):
        assert line.get("schema_version") == SCHEMA_VERSION, (
            f"{verb} -o ndjson line {index} published "
            f"schema_version={line.get('schema_version')!r}; models.SCHEMA_VERSION is "
            f"{SCHEMA_VERSION}"
        )


@pytest.mark.e2e
@pytest.mark.parametrize("verb", ["doctor", "info"])
def test_ac10_doctor_and_info_carry_the_injected_schema_version(verb: str, envelope) -> None:
    """AC10 — and this is the point of the criterion.

    `doctor` and `info` render BESPOKE payloads that carry no `schema_version`
    of their own, so `render_json`'s literal (`output/json.py`) is the **only**
    source of the key on these two verbs. The other 24 leaves supply it from
    their own `to_dict()` and shadow the injection value-identically.

    **The ledger's *"DEAD CODE, overridden by the payload on every shipped
    call"* is FALSIFIED by this red.** Delete the
    `"schema_version": SCHEMA_VERSION` literal from `render_json` in a scratch
    tree: these two verbs lose a published key from a published envelope —
    which X-410 forbids outright — while the other 24 leaves stay green. The
    most dangerous remediation available for `B-201` is the one its own ledger
    row describes.
    """
    payload = envelope(verb).json_payload
    assert payload is not None
    assert "schema_version" in payload, (
        f"{verb} -o json has no `schema_version`. `render_json`'s injection is this "
        f"verb's ONLY source of the key -- removing it as dead code deletes a public "
        f"key from a public envelope (X-410)."
    )
    assert payload["schema_version"] == SCHEMA_VERSION


def test_ac10_neither_bespoke_payload_supplies_schema_version_itself() -> None:
    """The other half of AC10, asserted at the source: neither builder writes
    the key, which is what makes the injection LIVE rather than shadowed. If a
    later spec teaches one of them to supply its own, this test reddens and the
    docstring above stops being true — which is the point of pinning it."""
    from pdf_tooling.cli import cmd_doctor, cmd_info

    doctor_payload = cmd_doctor.build_payload(strict=False, dry_run=False, root=REPO_ROOT)
    assert "schema_version" not in doctor_payload, (
        "`doctor`'s own payload now carries `schema_version`; `output/json.py`'s "
        "module docstring says it does not, and one of the two is now wrong"
    )
    info_payload, _ = cmd_info.build_payload(
        (REPO_ROOT / "testdata" / "malformed.pdf",), fonts=False, pages_detail=False, dry_run=False
    )
    assert "schema_version" not in info_payload, (
        "`info`'s own payload now carries `schema_version`; `output/json.py`'s module "
        "docstring says it does not, and one of the two is now wrong"
    )


@pytest.mark.e2e
@pytest.mark.parametrize("verb", LEAVES)
def test_ac11_no_ndjson_item_shadows_an_envelope_field(verb: str, envelope) -> None:
    """AC11 — §D6 clause 4's enforcement, and the clause PDF-40 is most likely
    to trip.

    `render_ndjson` injects `schema_version`, `verb` and `dry_run` BEFORE
    `**item`, so an item dict carrying one of the three would silently
    overwrite the envelope-level value on that path. Measured at PDF-39: no
    shipped item shape carries one, so this is a live hazard with no live
    instance — exactly the condition under which the next spec to add an item
    key creates the first one without noticing.

    The assertion is made against the ITEM DICTS in the `-o json` envelope,
    not against the rendered ndjson line: the rendered line always carries all
    three, because the renderer put them there.

    RED: add `"verb": "x"` to `ItemResult.to_dict()` in a scratch tree and this
    fails naming the item key that would shadow an envelope field.
    """
    _require_engine(verb)
    payload = envelope(verb).json_payload
    assert payload is not None
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        pytest.skip(f"{verb} -o json published no non-empty `items` collection to inspect")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        shadowing = sorted(set(item) & set(INJECTED_ENVELOPE_FIELDS))
        assert not shadowing, (
            f"{verb} item {index} carries {shadowing}, which `render_ndjson` also "
            f"injects -- the item would silently overwrite the envelope's value on the "
            f"ndjson path. Those three keys are envelope-level (§D6 clause 4)."
        )


def test_ac12_the_render_json_shadowing_mechanism_is_pinned() -> None:
    """AC12 — the ledger's own demonstration, kept as a test that ASSERTS the
    shadowing behaviour rather than as a claim about it.

    `**payload` is splatted after the literal, so a payload carrying
    `schema_version` wins. That mechanism is **live for `doctor` and `info`**
    (their payloads carry no `schema_version`, so the injection is the only
    source) and **shadowed, value-identically, everywhere else**. Removing the
    injection is forbidden by X-410 — it would delete a published key from two
    published envelopes. A test that pins a hazard is how the hazard stops
    being a surprise.
    """
    from pdf_tooling.output.json import render_json

    shadowed = json.loads(render_json({"schema_version": 99, "verb": "x"}))
    assert shadowed["schema_version"] == 99, (
        "the payload no longer shadows the injected `schema_version`. That is a "
        "BEHAVIOUR CHANGE in a public renderer, not a cleanup."
    )
    injected = json.loads(render_json({"verb": "x"}))
    assert injected["schema_version"] == SCHEMA_VERSION, (
        "a payload with no `schema_version` no longer receives the injected one -- "
        "which is precisely how `doctor -o json` and `info -o json` would lose a "
        "published key"
    )


def test_ac12_the_render_ndjson_shadowing_mechanism_is_pinned() -> None:
    """AC12's second half. `render_ndjson` repeats the shape on THREE fields,
    each splatted over by `**item`. None is shadowed on any shipped path today
    (AC11 asserts that continuously); the mechanism is pinned here so the first
    attempt is a red rather than a silent overwrite."""
    from pdf_tooling.output.json import render_ndjson

    line = json.loads(
        render_ndjson(
            {
                "verb": "envelope",
                "dry_run": False,
                "items": [{"schema_version": 99, "verb": "item", "dry_run": True, "ok": True}],
            }
        )
    )
    assert (line["schema_version"], line["verb"], line["dry_run"]) == (99, "item", True), (
        "an ndjson item no longer shadows the three injected fields. That is a "
        "BEHAVIOUR CHANGE in a public renderer."
    )
    clean = json.loads(
        render_ndjson({"verb": "envelope", "dry_run": False, "items": [{"ok": True}]})
    )
    assert clean["schema_version"] == SCHEMA_VERSION
    assert clean["verb"] == "envelope"
    assert clean["dry_run"] is False


def test_ac12_the_error_envelope_is_not_exposed_to_the_shadowing_at_all() -> None:
    """A distinction worth preserving rather than tidying away:
    `render_error_json` builds `{schema_version, error}` with **no `**payload`
    splat**, so it cannot be shadowed. It is named here so a later reader does
    not "normalise" the three renderers into one and quietly hand the error
    envelope a hazard it never had."""
    import inspect

    from pdf_tooling.output.json import render_error_json

    source = inspect.getsource(render_error_json)
    assert "**" not in source, (
        "`render_error_json` has grown a splat; it was the one renderer a payload "
        "could not shadow, and that property was deliberate"
    )
    rendered = json.loads(render_error_json({"code": 2, "message": "x"}))
    assert rendered["schema_version"] == SCHEMA_VERSION
    assert set(rendered) == {"schema_version", "error"}


# --------------------------------------------------------------------------- #
# Member 4 — the three collection names (`B-235`). AC13-AC16.
# --------------------------------------------------------------------------- #

#: The two verbs whose `-o json` collection has a PRIMARY name of its own, and
#: what that name is. Both are load-bearing and neither may be renamed:
#: `ports` is pinned by `PLAN.md` §3's own `jq '.ports[]'` example, `documents`
#: by `cli/cmd_info.py`'s published shape. PDF-39 added `items` beside them.
PRIMARY_COLLECTION_KEYS: Final[dict[str, str]] = {"doctor": "ports", "info": "documents"}


@pytest.mark.e2e
@pytest.mark.parametrize("verb", sorted(PRIMARY_COLLECTION_KEYS))
def test_ac13_the_primary_key_and_the_items_alias_are_the_same_list(verb: str, envelope) -> None:
    """AC13. The RED was FREE and was observed at `f83b757` before any edit:
    `doctor -o json` carried `ports` and no `items`; `info -o json` carried
    `documents` and no `items`; the `OperationResult` verbs carried `items`.
    Three spellings of one concept under one `schema_version`.

    RED now: drop the alias from one of the two and this fails naming the verb;
    make the alias a different list and the equality assertion fails.
    """
    primary = PRIMARY_COLLECTION_KEYS[verb]
    payload = envelope(verb).json_payload
    assert payload is not None
    assert primary in payload, (
        f"{verb} -o json no longer carries `{primary}`. It is a PUBLISHED key and "
        f"X-410 forbids renaming or removing it; `items` is an ADDITION beside it, "
        f"never a replacement for it."
    )
    assert "items" in payload, (
        f"{verb} -o json carries `{primary}` but no `items`. PDF-39 D4 made `items` "
        f"the universal collection key by ADDITION."
    )
    assert payload["items"] == payload[primary], (
        f"{verb}: `items` and `{primary}` are not the same list. They must never drift "
        f"into meaning different things."
    )


@pytest.mark.e2e
@pytest.mark.parametrize("verb", LEAVES)
def test_ac14_a_verb_that_streams_rows_names_that_collection_items(verb: str, envelope) -> None:
    """AC14 — enumerated from the LIVE registry rather than from a typed list,
    so a future verb publishing only a bespoke collection key turns this red
    with zero author action.

    **The rule, stated mechanically:** a verb whose `-o ndjson` STREAMS PER-ROW
    lines has a row collection, and that collection must be reachable under
    `items` in its `-o json` envelope too. "Streams per-row lines" is measured
    from the shipped output, not declared: a streaming verb's ndjson line has a
    different key set from its `-o json` envelope, because the line is a row
    and the envelope is an envelope. `meta get` is correctly OUTSIDE this
    population — its `-o ndjson` emits the whole envelope on one line, so it
    publishes no row collection to name, and PDF-39 did not invent one for it.

    `-o ndjson` and `-o table` behaviour is UNCHANGED by this member, asserted
    by their existing tests passing untouched.
    """
    _require_engine(verb)
    observed = envelope(verb)
    payload = observed.json_payload
    assert payload is not None
    if not observed.ndjson_lines:
        pytest.skip(f"{verb} -o ndjson streamed no lines on its registered invocation")
    streams_rows = sorted(observed.ndjson_lines[0]) != sorted(payload)
    if not streams_rows:
        return
    assert "items" in payload, (
        f"{verb} streams per-row `-o ndjson` lines but its `-o json` envelope has no "
        f"`items`. Its collection is published under "
        f"{sorted(k for k, v in payload.items() if isinstance(v, list))} only, which is "
        f"a fourth spelling of a concept that already has a universal name."
    )
    assert isinstance(payload["items"], list)


@pytest.mark.parametrize("token", ["`documents`", "`ports`"])
def test_ac15_the_readme_output_contract_names_the_collection_keys(token: str) -> None:
    """AC15's mechanical criterion. The census recipe returns **0** for both of
    these in `README.md`, `TESTING.md` and `CLAUDE.md` at `d03bee3` and at
    `f83b757` — measured, not assumed, and it is the strongest single line of
    evidence in this member: neither divergent collection key was named
    ANYWHERE on the three surfaces a consumer reads. They were documented only
    in source comments, which a consumer of a published JSON envelope has no
    reason to open.

    RED: remove the collection-key table and the count returns to 0.
    """
    assert README.read_text().count(token) > 0, (
        f"README.md does not name {token}. `## Output contract` documents `-o json` as "
        f"'one object carrying schema_version' and, before PDF-39, named no collection "
        f"key at all."
    )


def test_ac16_no_docstring_still_claims_items_is_withheld_from_json() -> None:
    """AC16 — the docstrings that ARGUED FOR the old behaviour are corrected,
    not left standing. A docstring contradicting the code is the defect class
    this member's remediation must not create, and it is the one this product
    files most often."""
    sources = {
        path: (REPO_ROOT / "src" / "pdf_tooling" / "cli" / path).read_text()
        for path in ("cmd_doctor.py", "cmd_info.py")
    }
    for path, text in sources.items():
        assert "withheld" not in text, (
            f"{path} still uses the word that carried the old ruling. The reversed "
            f"claim is PARAPHRASED as history in both modules rather than quoted, so "
            f"this guard can be a flat literal check that a re-introduction cannot "
            f"slip past on a line break."
        )
    for path, text in sources.items():
        assert "PDF-39" in text, (
            f"{path} carries no record of the reversal. Leaving the old reasoning "
            f"unedited creates exactly the docstring/code contradiction D3 exists to "
            f"remove."
        )


# --------------------------------------------------------------------------- #
# The frame held — X-410 made mechanical. AC17-AC19.
# --------------------------------------------------------------------------- #


def test_ac17_the_schema_version_is_still_one() -> None:
    """AC17 — a criterion by absence, so a later reader can prove the frame
    held without trusting any document.

    `schema_version` stays `1` through cycle 3, through v1.0.0, and for as long
    after it as the envelope changes only by ADDITION. It increments on the
    first change a name-keyed consumer cannot survive — a rename, a removal, a
    type change, or a meaning change (see this module's docstring for D5's four
    trigger conditions in full) — and an increment is coupled to a major
    version bump. **Only a PM-approved increment may change this value; it is
    never an engineer's call.**
    """
    assert SCHEMA_VERSION == 1, (
        f"models.SCHEMA_VERSION is {SCHEMA_VERSION}. An increment is a MAJOR version "
        f"bump coupled to it, and is the PM's decision. If a change genuinely needs "
        f"one, that is a BLOCKER to the PM, not an edit."
    )


def load_register() -> dict[str, dict[str, list[str] | None]]:
    """The frozen per-leaf key register. A register generated AFTER the work
    asserts nothing, which is why its provenance is asserted separately by
    `test_the_register_exists_and_declares_where_it_came_from` rather than
    trusted from this function's own read."""
    return dict(json.loads(REGISTER_PATH.read_text())["leaves"])


def load_register_document() -> dict[str, Any]:
    """The WHOLE register file, `_meta` included — PDF-54's own reader,
    beside `load_register()`'s `leaves`-only one (kept for the callers that
    only ever wanted that)."""
    return json.loads(REGISTER_PATH.read_text())


def test_the_register_exists_and_declares_where_it_came_from() -> None:
    """The register's own provenance, asserted.

    PDF-54 AC6/D5 — no longer a hard-pinned commit literal. `d03bee3` was
    the ONE-TIME anchor `PDF-39` generated the register at; hard-pinning it
    forever would make every future HONEST regeneration (this spec's own,
    and `PDF-57`'s after it, D9) fail a test that exists to prove the
    register is trustworthy. What is asserted instead is the SHAPE every
    regeneration must produce: a commit that resolves in this repository, a
    tag that is either absent or real, and an `arms` list that names every
    arm the file actually carries — never a second sha literal, which would
    only move the rot to the next regeneration (E5).

    `qa-sentinel`'s re-run instruction is to check this file's git history
    first: it must have been written by the `[PDF-54]` commit (or, later,
    `PDF-57`'s — D9 clause 1), and `generated_at_commit` must be an ancestor
    of, or equal to, that commit.

    Skipped, not asserted, while a regeneration is IN PROGRESS in this same
    `-k register` invocation (`test_regenerating_the_register` is the one
    test that writes this file, and `-n auto` gives no ordering guarantee
    between xdist workers): this test's job is to grade the COMMITTED,
    STABLE file, and a register mid-rewrite is not yet either.
    """
    if os.environ.get(REGENERATE_ENV) == "1":
        pytest.skip(f"{REGENERATE_ENV}=1 -- grading the committed file, not one mid-regeneration")
    meta = load_register_document()["_meta"]

    commit = meta["generated_at_commit"]
    assert (
        isinstance(commit, str)
        and len(commit) == 40
        and all(c in "0123456789abcdef" for c in commit)
    ), f"_meta.generated_at_commit {commit!r} is not a 40-character hex string"
    resolved = subprocess.run(["git", "cat-file", "-e", commit], cwd=REPO_ROOT, capture_output=True)
    assert resolved.returncode == 0, (
        f"_meta.generated_at_commit {commit!r} does not resolve in this repository -- "
        f"a hard-coded sha that never rotted would still have to pass THIS check"
    )

    tag = meta.get("generated_at_tag")
    if tag is not None:
        known = subprocess.run(
            ["git", "tag", "--list", tag], cwd=REPO_ROOT, capture_output=True, text=True
        )
        assert known.stdout.strip() == tag, (
            f"_meta.generated_at_tag {tag!r} is not a tag `git tag --list` knows -- "
            f"no tag may be invented (X-703)"
        )
    assert "generated_at_describe" in meta, "_meta.generated_at_describe is missing"
    assert meta["assertion"].startswith("SUPERSET")
    arms = meta.get("arms")
    assert isinstance(arms, list) and FAILURE_ARM in arms, (
        f"_meta.arms is {arms!r}; it must list every arm the register carries, "
        f"including {FAILURE_ARM!r}"
    )


@pytest.mark.e2e
@pytest.mark.parametrize("verb", LEAVES)
def test_ac18_no_public_key_was_renamed_or_removed(verb: str, envelope) -> None:
    """AC18 — X-410 made mechanical, and the headline criterion of this spec.

    The post-change envelope must be a **SUPERSET** of the key set frozen at
    `d03bee3`, per leaf, on both arms. Superset and NOT equality, deliberately:
    an addition is a strict superset while a rename or a removal is not, so
    additive change stays cheap and destructive change stops.

    RED, two directions: rename `ports` to `engines` in a scratch tree and this
    fails naming `ports`; delete `warnings` from `OperationResult.to_dict()`
    and it fails naming `warnings`.

    **Regenerating this register to make a red go green is FORBIDDEN.** An
    addition is already a superset and needs no regeneration at all; the only
    other sanctioned route is a PM-approved `schema_version` increment. If the
    register reddens on a leaf nobody predicted, that is INFORMATION: record
    it, file it, and escalate.
    """
    _require_engine(verb)
    register = load_register()
    assert verb in register, (
        f"{verb} is invocable but absent from the frozen register. A register narrower "
        f"than the population it claims to cover asserts nothing about the gap."
    )
    frozen = register[verb]
    live = envelope(verb).register_entry()

    for arm in ("json", "ndjson_line"):
        expected, actual = frozen[arm], live[arm]
        if expected is None:
            continue
        assert actual is not None, (
            f"{verb} [{arm}]: the register froze {expected} at d03bee3 and the live run "
            f"produced no parseable object at all"
        )
        lost = sorted(set(expected) - set(actual))
        assert not lost, (
            f"{verb} [{arm}]: published key(s) {lost} are GONE. They were in the "
            f"envelope at d03bee3 (= tag v0.2.0). A rename or a removal of a published "
            f"key is a `schema_version` increment coupled to a major version bump "
            f"(D5), and that is the PM's call. Do NOT regenerate the register."
        )


def test_ac19_the_register_covers_every_leaf_the_harness_can_invoke() -> None:
    """AC19 — the register's coverage is PUBLISHED, not claimed.

    A register that covers nine leaves and claims to cover the envelope passes
    while asserting nothing; that is this spec's own headline hazard and this
    is its control. `discover_verbs()` gives the denominator, so the assertion
    is against the live command tree rather than against a list somebody typed.
    """
    register = load_register()
    covered = set(register)
    invocable = set(LEAVES)
    assert not (invocable - covered), (
        f"leaf/leaves {sorted(invocable - covered)} are invocable but not in the "
        f"register. Add them, or state why they are uninvocable -- never drop them "
        f"quietly."
    )
    assert not (covered - invocable), (
        f"the register freezes {sorted(covered - invocable)}, which the live command "
        f"tree no longer offers. A verb REMOVED from the CLI is a public-API removal "
        f"in its own right; escalate rather than trimming the register."
    )
    assert uninvocable_leaves() == (), (
        f"leaves {uninvocable_leaves()} are discovered but have no INVOCATIONS row, so "
        f"the register cannot cover them. This is a stated gap and a finding, not a "
        f"reason to narrow the population."
    )


# --------------------------------------------------------------------------- #
# PDF-54 — the failure arm. Extends the register to the error envelope, the
# arm a consumer actually branches on and the one nothing froze before this.
# --------------------------------------------------------------------------- #


def test_the_failure_arm_population_is_not_empty() -> None:
    """The anti-lapse assertion for :data:`FAILURE_LEAVES`, mirroring
    `test_the_leaf_population_is_not_empty` above."""
    assert len(FAILURE_LEAVES) >= 20, (
        f"the failure-arm population walk found {len(FAILURE_LEAVES)}; every "
        f"parameterized guard below would pass vacuously"
    )


def test_ac2_the_failure_arm_population_is_derived_and_includes_merge() -> None:
    """AC2. RED: build the population from `VerbSpec.takes_input_paths` —
    the arm fails naming `merge` as the leaf that would have been dropped
    (E12: `takes_input_paths` is `click.Path`-typed and `merge`'s own
    operand is declared `str`)."""
    from_takes_input_paths = {spec.name for spec in discover_verbs() if spec.takes_input_paths}
    from_positional_argument = set(FAILURE_LEAVES)

    only_in_positional = from_positional_argument - from_takes_input_paths
    only_in_typed_path = from_takes_input_paths - from_positional_argument
    assert only_in_positional == {"merge"} and not only_in_typed_path, (
        f"the two predicates disagree on {sorted(only_in_positional | only_in_typed_path)}, "
        f"not exactly on `merge` alone — `takes_input_paths` is `click.Path`-typed and "
        f"silently drops any verb whose operand is declared `str` (E12)"
    )

    every_leaf = {spec.name for spec in discover_verbs() if not spec.is_group}
    excluded = every_leaf - from_positional_argument
    assert excluded == {"doctor", "version"}, (
        f"the failure-arm population excludes {sorted(excluded)}; it must exclude "
        f"exactly `doctor` and `version`, the two leaves with no positional operand"
    )


@pytest.mark.parametrize("verb", FAILURE_LEAVES)
def test_ac3_every_failure_arm_population_member_supplies_a_no_input_build(verb: str) -> None:
    """AC3's anti-lapse half, modelled on the shipped
    `test_a_destructive_row_supplies_its_own_bulk_argv`
    (`tests/test_cli_contract.py`) on the identical `destructive_build`
    precedent. RED: delete one row's `no_input_build` and this fails naming
    it."""
    assert INVOCATIONS[verb].no_input_build is not None, (
        f"tests/registry.py::INVOCATIONS[{verb!r}] declares a positional operand "
        f"but has no `no_input_build`. `build`'s shared shape cannot be trusted to "
        f"reach `kind=no_input` on every leaf — several verbs need MORE than a "
        f"nonexistent path before the no-input check ever runs (E13). Add a "
        f"purpose-built row (PDF-54 D3)."
    )


@pytest.mark.e2e
@pytest.mark.parametrize("verb", FAILURE_LEAVES)
def test_ac3_the_no_input_build_reaches_kind_no_input(verb: str, failure_envelope) -> None:
    """AC3's kind assertion, per leaf. RED: replace `merge`'s `no_input_build`
    with a bare operand swap (drop `-O`) — this fails naming `merge`,
    `"usage"` and `"no_input"`, reproducing E13's own measured trap live."""
    observed = failure_envelope(verb)
    assert observed.payload is not None, (
        f"{verb}: the no-input invocation produced no parseable envelope. Repro: "
        f"{rerun_hint([verb, '-o', 'json', *observed.argv])}"
    )
    assert observed.kind == "no_input", (
        f"{verb}: the no-input invocation reached kind={observed.kind!r}, not "
        f"'no_input'. A purpose-built `no_input_build` must supply every flag the "
        f"verb requires BEFORE the no-input check runs, exactly as its ordinary "
        f"`build` does (E13). Repro: {rerun_hint([verb, '-o', 'json', *observed.argv])}"
    )


@pytest.mark.e2e
@pytest.mark.parametrize("verb", FAILURE_LEAVES)
def test_ac4_the_failure_arm_is_a_superset_of_the_frozen_cells(verb: str, failure_envelope) -> None:
    """AC4. RED, two directions: fold the failure keys into the `json` arm —
    every SUCCESSFUL leaf then fails AC18's superset assertion demanding
    `error`. RED, second direction: delete `path` from the base exception
    class's `to_dict()` in a scratch tree — this fails naming `path`.
    """
    register = load_register()
    frozen = register[verb].get(FAILURE_ARM)
    assert frozen is not None, (
        f"{verb} has no {FAILURE_ARM!r} cell in the register — extend it (PDF-54 D1)"
    )
    live = failure_envelope(verb).register_entry()
    assert live is not None, f"{verb}: the live no-input run produced no parseable envelope"
    for level in ("top", "error"):
        lost = sorted(set(frozen[level]) - set(live[level]))
        assert not lost, (
            f"{verb} [{FAILURE_ARM}.{level}]: published key(s) {lost} are GONE. A "
            f"rename or removal of a published failure-envelope key is a "
            f"`schema_version` increment coupled to a major version bump (D5), and "
            f"that is the PM's call. Do NOT regenerate the register."
        )


def test_ac4_the_failure_arm_never_shares_the_json_arm() -> None:
    """AC4's structural half. RED: fold `error_json` into `json` in a
    scratch tree — every successful leaf's `json` cell would then have to
    carry `error`, which no successful envelope does, and AC18 fails on all
    of them (D1's own reasoning: freeze the union and every success red;
    freeze the intersection and nothing but `schema_version` is asserted)."""
    document = load_register_document()
    arms = document["_meta"].get("arms")
    assert isinstance(arms, list) and FAILURE_ARM in arms, (
        f"_meta.arms {arms!r} does not list {FAILURE_ARM!r}"
    )
    for verb, cells in document["leaves"].items():
        if FAILURE_ARM not in cells:
            continue
        assert set(cells[FAILURE_ARM]) == {"top", "error"}, (
            f"{verb}'s {FAILURE_ARM} cell has keys {sorted(cells[FAILURE_ARM])}, not "
            f"exactly {{'top', 'error'}} — D1 freezes both levels independently"
        )
        assert "error" not in (cells.get("json") or []), (
            f"{verb}'s `json` arm carries a top-level `error` key — the failure arm "
            f"has been folded into the success arm, which D1/AC4 forbid"
        )


#: The two system binaries any registered invocation depends on
#: (`ports/__init__.py`'s `_BINARY_HINTS`: `OcrEngine` -> tesseract,
#: `OfficeConverter` -> soffice). `convert` is the only failure-arm member
#: declaring `requires_engine` at all; the other binary is included anyway
#: because AC5's claim is about the CHECK, not about any one verb's declared
#: dependency, and E8 measured both.
_KNOWN_ENGINE_BINARIES: Final[tuple[str, ...]] = ("tesseract", "soffice")


@pytest.mark.e2e
@pytest.mark.parametrize("binary", _KNOWN_ENGINE_BINARIES)
def test_ac5_the_failure_arm_population_is_identical_with_engines_hidden(
    binary: str, corpus, tmp_path: Path
) -> None:
    """AC5. RED: gate the failure-arm observation on `_require_engine()` —
    the population shrinks with *binary* genuinely absent from `PATH` and
    this fails naming the skipped leaves. `Invocation.requires_engine` is
    scoped to reaching exit 0 (its own docstring); the failure arm never
    does (E8).

    Hides *binary* with `helpers.engine_hiding.hidden_engine_env` — the
    shared, already-shipped instrument every other engine-absence test in
    this suite uses (`tests/integration/test_or7_engine_absent.py`,
    `test_or7_bulk_destructive.py`) — never the pytest-process-only
    `conftest.py` shim, which mutates the CURRENT interpreter's `PATH` for
    collection-time `requires()` skips and has no effect on a subprocess
    `run_cli()` spawns with its own `env=`.
    """
    from helpers.engine_hiding import hidden_engine_env

    env = hidden_engine_env(binary, tmp_path=tmp_path)
    root = tmp_path / "hidden-runs"
    root.mkdir()
    covered: list[str] = []
    for verb in FAILURE_LEAVES:
        build = INVOCATIONS[verb].no_input_build
        assert build is not None
        run_dir = root / verb.replace(" ", "_")
        run_dir.mkdir()
        argv = build(corpus, run_dir)
        result = run_cli(verb, "-o", "json", *argv, cwd=run_dir, env=env)
        payload = _parse_object(result.stdout)
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and error.get("kind") == "no_input":
            covered.append(verb)
    missing = sorted(set(FAILURE_LEAVES) - set(covered))
    assert not missing, (
        f"leaf/leaves {missing} lost their no-input failure arm with {binary!r} hidden "
        f"— gating the observation on engine resolution would cover fewer leaves on a "
        f"lean host and be green about it (E8)"
    )


@pytest.mark.e2e
@pytest.mark.parametrize("verb", FAILURE_LEAVES)
def test_ac10_dry_run_mirrors_the_real_run_on_the_failure_arm(
    verb: str, corpus, tmp_path: Path
) -> None:
    """AC10 — OR-7 / X-185, BOTH observables, on the failure arm this spec
    freezes. RED: hard-code a `0` exit on one verb's dry-run path in a
    scratch tree — the arm fails naming the verb and both codes. Measured
    green at `89a4f1d` with no work at all (E3); this criterion is by
    preservation."""
    build = INVOCATIONS[verb].no_input_build
    assert build is not None
    dry_dir = tmp_path / "dry"
    dry_dir.mkdir()
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    dry = run_cli(verb, "--dry-run", *build(corpus, dry_dir), "-o", "json", cwd=dry_dir)
    real = run_cli(verb, *build(corpus, real_dir), "-o", "json", cwd=real_dir)
    assert dry.returncode == real.returncode, (
        f"{verb}: --dry-run exited {dry.returncode}, the real run exited {real.returncode}"
    )
    dry_payload = _parse_object(dry.stdout)
    real_payload = _parse_object(real.stdout)
    assert dry_payload is not None and real_payload is not None, (dry.stdout, real.stdout)
    assert sorted(dry_payload) == sorted(real_payload), (
        f"{verb}: --dry-run's failure envelope shape is {sorted(dry_payload)}, the real "
        f"run's is {sorted(real_payload)}. OR-7 binds the SHAPE as well as the code."
    )
    dry_error = dry_payload.get("error")
    real_error = real_payload.get("error")
    assert isinstance(dry_error, dict) and isinstance(real_error, dict)
    assert sorted(dry_error) == sorted(real_error), (
        f"{verb}: the nested `error` key sets disagree between --dry-run "
        f"({sorted(dry_error)}) and the real run ({sorted(real_error)})"
    )


def _walk_error_subclasses(root: type = _BASE_ERROR) -> tuple[type, ...]:
    """The base exception class and every subclass, walked recursively.
    Never a typed list of seven strings (D4) — a class added tomorrow joins
    this walk with zero author action."""
    found: list[type] = [root]
    for sub in root.__subclasses__():
        found.extend(_walk_error_subclasses(sub))
    return tuple(found)


def _instantiate_for_kind_check(cls: type) -> _BASE_ERROR:  # type: ignore[valid-type]
    """A throwaway instance of *cls*, with a synthetic value for every
    constructor argument it declares beyond one carrying a default.

    Structural, never a per-class special case: :class:`PageRangeError` is
    the one subclass with a wider constructor than the base
    (`spec`/`token`/`column`/`reason`), and this reads its signature rather
    than naming it, so a future subclass with a novel constructor is
    covered with zero author action — the same "no skip list, ever" shape
    `discover_verbs()` already commits to.
    """
    signature = inspect.signature(cls.__init__)
    kwargs: dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        if name == "self" or parameter.default is not inspect.Parameter.empty:
            continue
        if parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        kwargs[name] = 1 if parameter.annotation in (int, "int") else "pdf54-kind-probe"
    return cls(**kwargs)


def test_d4_every_error_kind_renders_the_same_key_sets() -> None:
    """D4 — kind-independence, asserted ONCE from `errors.py`'s own class
    tree, never as a per-(leaf × kind) matrix. RED: rename `kind` to
    `category`, or remove `path`, from the base exception class's
    `to_dict()` in a scratch tree — every class in the tree fails together,
    naming the class and the lost key (AC17's two plants).
    """
    frozen: list[str] | None = None
    frozen_owner: str | None = None
    for cls in _walk_error_subclasses():
        instance = _instantiate_for_kind_check(cls)
        rendered = json.loads(render_error_json(instance.to_dict()))
        keys = sorted(rendered.get("error", {}))
        if frozen is None:
            frozen, frozen_owner = keys, cls.__name__
            continue
        assert keys == frozen, (
            f"{cls.__name__} (kind={instance.kind!r}) renders error keys {keys}, which "
            f"disagree with {frozen_owner}'s {frozen} — the shape must not vary by kind"
        )


def test_ac9_the_forbidden_clause_survives_byte_identical() -> None:
    """AC9. RED: change one character and this fails. X-709 ruling 3 — it is
    the single sentence that makes the instrument worth having, and it
    survives every regeneration this spec performs untouched."""
    meta = load_register_document()["_meta"]
    assert meta["regenerating_this_file_to_make_a_red_go_green_is_forbidden"] == FORBIDDEN_CLAUSE


def _derive_meta(existing: dict[str, Any], *, spec_id: str) -> dict[str, Any]:
    """PDF-54 D5/AC7 — `_meta` is DERIVED FROM GIT at the moment of
    regeneration, never preserved from a prior run. This is the repair: at
    `89a4f1d` the regenerate node rewrote `leaves` and never touched `_meta`
    at all (E5), so any regeneration, by anyone, at any commit, left the
    file claiming `d03bee3` over key sets measured elsewhere. Calling this on
    every regeneration is what keeps that from recurring at `PDF-57` (D9).
    """
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    describe = subprocess.run(
        ["git", "describe", "--tags", "--always"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    pointed_at_head = subprocess.run(
        ["git", "tag", "--points-at", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    tag = pointed_at_head.splitlines()[0] if pointed_at_head else None

    meta = dict(existing)
    meta["generated_at_commit"] = commit
    meta["generated_at_describe"] = describe
    meta["generated_at_tag"] = tag
    meta["spec"] = spec_id
    meta.pop("generated_before_any_edit", None)
    meta["generated_from_a_tree_with_no_src_change"] = True
    meta["arms"] = ["json", "ndjson_line", FAILURE_ARM]
    meta["regenerate"] = (
        f"{REGENERATE_ENV}=1 uv run pytest tests/test_envelope_contract.py "
        "-k register -p no:randomly"
    )
    return meta


def test_ac7_derive_meta_rewrites_provenance_rather_than_preserving_it() -> None:
    """AC7, always-run (never gated behind `REGENERATE_ENV`, unlike the real
    regeneration below): the derivation is exercised directly against a
    synthetic STALE `_meta`, proving the mechanism rewrites provenance on
    every call rather than carrying the old value forward. RED, and it is
    the point of the criterion: before this spec, `test_regenerating_the_
    register` rewrote `leaves` and never touched `_meta` at all — run it on
    any commit and the file would still claim `d03bee3` over key sets
    measured elsewhere (E5).
    """
    stale = {
        "generated_at_commit": "d03bee3ca226a18c42814ad15cfddb7cecdb97a5",
        "generated_at_tag": "v0.2.0",
        "generated_before_any_edit": True,
        "assertion": "SUPERSET, per leaf, per arm -- never equality",
        "spec": "PDF-39",
    }
    derived = _derive_meta(stale, spec_id=REGENERATING_SPEC)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert derived["generated_at_commit"] == head, (
        "the derivation did not overwrite the stale commit with the live HEAD"
    )
    assert derived["generated_at_commit"] != stale["generated_at_commit"]
    assert derived["spec"] == REGENERATING_SPEC
    assert "generated_before_any_edit" not in derived
    assert derived["generated_from_a_tree_with_no_src_change"] is True
    assert FAILURE_ARM in derived["arms"]


def test_ac14_the_registers_own_meta_publishes_failure_arm_coverage() -> None:
    """AC14. RED: a covered list narrower than the derived population — the
    published-coverage arm fails naming the gap. Coverage lives in the
    artifact itself (D2) rather than in the Implementation Log (B-270 /
    X-511), so a verifier can read it at any later commit without the
    engineer's context.

    Skipped while a regeneration is in progress in this same `-k register`
    invocation, on the identical rationale
    `test_the_register_exists_and_declares_where_it_came_from` states in
    full above."""
    if os.environ.get(REGENERATE_ENV) == "1":
        pytest.skip(f"{REGENERATE_ENV}=1 -- grading the committed file, not one mid-regeneration")
    meta = load_register_document()["_meta"]
    population = set(FAILURE_LEAVES)

    published_population = set(meta.get("failure_arm_population", ()))
    assert published_population == population, (
        f"_meta.failure_arm_population {sorted(published_population)} does not match "
        f"the live derived population {sorted(population)}"
    )
    covered = set(meta.get("failure_arm_leaves_covered", ()))
    assert covered == population, (
        f"_meta.failure_arm_leaves_covered {sorted(covered)} is narrower than the "
        f"derived population {sorted(population)} — a register that covers fewer "
        f"leaves than it claims passes while asserting less"
    )
    assert meta.get("failure_arm_leaves_uncovered") == [], meta.get("failure_arm_leaves_uncovered")

    assert meta.get("leaves_covered") == len(LEAVES)
    assert meta.get("leaves_discovered") == len(LEAVES) + len(uninvocable_leaves())
    assert meta.get("leaves_uncovered") == list(uninvocable_leaves())


def _envelope_register_section(text: str) -> str:
    """TESTING.md's `## The envelope key register` section, isolated to its
    own heading boundary, so AC15/AC16 grade the section rather than the
    whole document."""
    start = text.index("## The envelope key register")
    rest = text[start + len("## The envelope key register") :]
    end = rest.find("\n## ")
    return text[
        start : start + len("## The envelope key register") + (end if end != -1 else len(rest))
    ]


def test_ac15_testing_md_documents_exactly_three_sanctioned_register_cases() -> None:
    """AC15. RED: a mechanical check that the string `There is no third case`
    is gone AND that the section still contains the unqualified FORBIDDEN
    prohibition; removing the prohibition to make room for the third case
    fails it too."""
    section = _envelope_register_section(TESTING_MD.read_text())
    assert "There is no third case" not in section, (
        "the enumeration still claims only two sanctioned outcomes exist"
    )
    assert "FORBIDDEN" in section, "the unqualified prohibition headline is gone"
    for marker in ("\n1. ", "\n2. ", "\n3. "):
        assert marker in section, f"the section does not enumerate a case at {marker!r}"


def test_ac16_the_two_published_regenerate_spellings_agree() -> None:
    """AC16. RED: rename the env var here — `PDF-57`'s population
    reconciliation (D9) finds a name already moved and its census is wrong
    in both directions."""
    meta_recipe = load_register_document()["_meta"]["regenerate"]
    section = _envelope_register_section(TESTING_MD.read_text())
    block = re.search(rf"```bash\n({re.escape(REGENERATE_ENV)}=1.*?)\n```", section, re.DOTALL)
    assert block is not None, "TESTING.md's register section carries no fenced regenerate recipe"
    # `\` is a shell line-continuation marker, not part of the command itself
    # (TESTING.md wraps the recipe onto two lines for readability; `_meta`
    # does not) -- stripped before the two spellings are compared.
    testing_recipe = " ".join(block.group(1).replace("\\", " ").split())
    meta_recipe_normalised = " ".join(meta_recipe.replace("\\", " ").split())
    assert REGENERATE_ENV in meta_recipe_normalised
    assert REGENERATE_ENV in testing_recipe
    assert meta_recipe_normalised == testing_recipe, (
        f"_meta.regenerate is {meta_recipe_normalised!r}; TESTING.md's own recipe is "
        f"{testing_recipe!r} — two spellings of one command (E10)"
    )


@pytest.mark.e2e
def test_regenerating_the_register(corpus, tmp_path_factory) -> None:
    """The ONE sanctioned regeneration path, gated behind
    :data:`REGENERATE_ENV` and skipped on every ordinary run.

    Deliberately NOT wired to `--update-golden`: that flag exists for ordinary
    goldens, and someone regenerating `meta_get.json` must not silently destroy
    the only evidence that no public key was renamed. See `TESTING.md` for the
    ruling on when this may be run at all — the short version is that an
    ADDITION never needs it, and nothing else may use it without a PM-approved
    `schema_version` increment.

    PDF-54 D5/AC7 — `_meta` is now rewritten in the SAME operation as
    `leaves`, derived from git rather than preserved from whatever the file
    said before this call. PDF-54 D1/D2 — the failure arm is regenerated
    alongside the success arms, over the SAME derived population every
    ordinary test run reads from :data:`FAILURE_LEAVES`, and its own
    coverage is published into `_meta` rather than assumed.
    """
    if os.environ.get(REGENERATE_ENV) != "1":
        pytest.skip(f"set {REGENERATE_ENV}=1 to regenerate {REGISTER_PATH.name}; see TESTING.md")
    root = tmp_path_factory.mktemp("envelope-register")
    document = json.loads(REGISTER_PATH.read_text())
    document["leaves"] = {
        verb: observe_envelope_keys(verb, corpus, root).register_entry() for verb in LEAVES
    }

    covered: list[str] = []
    uncovered: list[dict[str, str]] = []
    for verb in FAILURE_LEAVES:
        invocation = INVOCATIONS.get(verb)
        if invocation is None or invocation.no_input_build is None:
            uncovered.append({"leaf": verb, "reason": "no no_input_build registered"})
            continue
        observed = observe_failure_envelope(verb, corpus, root)
        entry = observed.register_entry()
        if observed.kind != "no_input" or entry is None:
            uncovered.append(
                {"leaf": verb, "reason": f"reached kind={observed.kind!r}, not no_input"}
            )
            continue
        document["leaves"].setdefault(verb, {})[FAILURE_ARM] = entry
        covered.append(verb)

    document["_meta"] = _derive_meta(document["_meta"], spec_id=REGENERATING_SPEC)
    document["_meta"]["leaves_discovered"] = len(LEAVES) + len(uninvocable_leaves())
    document["_meta"]["leaves_covered"] = len(LEAVES)
    document["_meta"]["leaves_uncovered"] = list(uninvocable_leaves())
    document["_meta"]["failure_arm_population"] = list(FAILURE_LEAVES)
    document["_meta"]["failure_arm_leaves_covered"] = sorted(covered)
    document["_meta"]["failure_arm_leaves_uncovered"] = uncovered

    REGISTER_PATH.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


# --------------------------------------------------------------------------- #
# The whole surface — AC20's independence, and AC21's no-other-golden rule.
# --------------------------------------------------------------------------- #


def test_ac20_the_four_members_have_four_independent_criteria() -> None:
    """AC20's anti-lapse half, mechanized: the four members' headline criteria
    must be four DISTINCT test functions, so that no one of them can hide
    another. The independence itself is proven by driving each red alone with
    the other three green — recorded in the spec's Implementation Log, because
    a mutation cannot be a standing test."""
    headline = {
        "member 1 (B-066)": (
            "test_ac1_the_two_permission_vocabularies_are_a_bijection_through_the_map"
        ),
        "member 2 (B-143)": "test_ac5_the_three_former_omitters_now_carry_all_three_keys",
        "member 3 (B-201)": "test_ac10_doctor_and_info_carry_the_injected_schema_version",
        "member 4 (B-235)": "test_ac13_the_primary_key_and_the_items_alias_are_the_same_list",
    }
    assert len(set(headline.values())) == 4, "two members share a criterion"
    for member, name in headline.items():
        assert name in globals(), f"{member}'s headline criterion {name!r} does not exist"
