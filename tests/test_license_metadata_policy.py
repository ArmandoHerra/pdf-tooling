"""Licence-metadata deny/allow evaluation — PLAN.md §7.2 mechanism 1.

`PLAN.md:45` states goal `G2` verbatim: *"Apache-2.0 with a machine-checked
guarantee that no AGPL/GPL/LGPL code is reachable, including via
`subprocess`. The guarantee is a CI job and a unit test, not a promise in a
README."* `PLAN.md` §7.2 delivers that guarantee through TWO mechanisms, and
they are different propositions over different inputs:

  mechanism 1 (THIS FILE)          mechanism 2 (tests/test_license_policy.py)
  --------------------------       -------------------------------------------
  scripts/licenses.py               `ast`-parses the product's OWN SOURCE
  reads the dependency closure's     for forbidden imports / dynamic
  LICENCE METADATA (pip-licenses)    imports / subprocess argv[0] / a
                                      `shutil.which` lookup of a forbidden
                                      name
  catches: pyproject.toml gaining    catches: a three-line convenience
  a copyleft dependency               shell-out to `gs` under deadline

`tests/test_license_policy.py`'s own opening states the split identically:
*"`scripts/licenses.py` sees the dependency graph; it cannot see the call
graph."* That file never imports `scripts/licenses.py` and makes no claim
about the deny pattern or the allowlist — this file is that missing half.

WHAT THIS FILE ASSERTS, AND HOW IT REACHES scripts/licenses.py
----------------------------------------------------------------
`scripts/` is not a package (no `__init__.py`), so the DECISION layer of
`scripts/licenses.py` is loaded by path with `importlib.util
.spec_from_file_location` + `module_from_spec` + `exec_module`, anchored at
`REPO_ROOT` (the same anchor `tests/test_assert_skips.py:47` uses). The path
is overridable via the `PDF_TOOLKIT_LICENSES_MODULE` environment variable, so
a MUTATED SCRATCH COPY can be substituted without ever editing the tracked
file (PDF-41 D6's eight red controls; HC-4 — never `git stash`, never a
working-tree edit).

The seam is drawn at PURITY. Every arm below calls only:

    DENY, DENY_PROSE, ALLOWLIST, SELF, UNKNOWN
    normalize, split_disjuncts, is_denied, evaluate_expression

`cmd_check` straddles provisioning and deciding: it is driven with THREE
patch points, never two — `ensure_pinned_env`, `rows`, AND `universal_names`.
The third is not optional. `cmd_check` (:355) calls `universal_names()`
unconditionally whenever `args.informational` is False, and `universal_names`
(:271-280) spawns `uv tree --frozen --universal --no-dev` as a REAL
subprocess reading the REAL lockfile. Patching only the first two would (a)
spawn that subprocess and blow AC2's "no subprocess, under 1s" budget, and
(b) make `cmd_check` return 1 at :366 on the real closure's non-empty
unmeasured set BEFORE ever reaching the offender/disjunctive reporting this
file exists to test at :371-380 and :382-392 — a "pass" for entirely the
wrong reason. Every arm here patches `universal_names` to return `set()`,
which always makes `unmeasured` empty regardless of the fixture's own
contents (`universal - measured - MARKER_ONLY` is empty whenever `universal`
is empty). No arm in this file runs `uv sync`, spawns a subprocess, or
touches the network — see `_drive_cmd_check` below.

`ensure_pinned_env`, `pip_licenses`, `rows`, `universal_names`,
`cmd_generate` and `main` are NEVER invoked in their real form by any arm.

BOUNDARIES THIS FILE DOES NOT CROSS (PDF-41 §Out — read there, not here)
----------------------------------------------------------------------
`scripts/licenses.py` is not edited by this file's spec. The deny pattern is
not widened, narrowed, or touched. `ALLOWLIST` stays empty — its emptiness is
a property this file protects, never an obstacle it routes around. `B-151`
is NOT closed by this file: it discharges exactly one of its thirteen
criteria (fingerprint `9385d4991e`), and twelve remain uncovered.
`MARKER_ONLY` and the universal-closure subset check are a neighbouring,
genuinely different proposition and are out of scope here.
"""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
DEFAULT_LICENSES_MODULE_PATH: Final[Path] = REPO_ROOT / "scripts" / "licenses.py"
DEFAULT_INVENTORY_PATH: Final[Path] = REPO_ROOT / "THIRD_PARTY_LICENSES"

#: Every symbol this file's arms bind from `scripts/licenses.py`. Asserted
#: present at load time (D1's anti-lapse clause): a rename in the source
#: module must be a COLLECTION ERROR naming the missing symbol, never a
#: silently-skipped module — see `test_ac1_...` below for the permanent,
#: in-suite regression, and PDF-41 D6/R-none (AC1 is not one of the eight
#: numbered reds; it is proven directly, in-process, via `tmp_path`).
_REQUIRED_SYMBOLS: Final[tuple[str, ...]] = (
    "SELF",
    "DENY",
    "DENY_PROSE",
    "ALLOWLIST",
    "MARKER_ONLY",
    "UNKNOWN",
    "normalize",
    "split_disjuncts",
    "is_denied",
    "evaluate_expression",
    "universal_names",
    "ensure_pinned_env",
    "rows",
    "cmd_check",
)


def _resolve_licenses_module_path() -> Path:
    """`PDF_TOOLKIT_LICENSES_MODULE` overrides the default so D6's mutated
    scratch copies are a PARAMETER, never a tree edit."""
    override = os.environ.get("PDF_TOOLKIT_LICENSES_MODULE")
    if override:
        return Path(override).resolve()
    return DEFAULT_LICENSES_MODULE_PATH


def _load_licenses_module(path: Path) -> ModuleType:
    """Load `scripts/licenses.py` (or a scratch copy at `path`) by path.

    Importing it executes nothing beyond top-level constants, two
    `re.compile`s, two dict literals and function definitions — `main()` is
    guarded by `if __name__ == "__main__":` (E7) — so this is side-effect
    free: no `uv sync`, no subprocess, no network, no filesystem write.
    """
    spec = importlib.util.spec_from_file_location("pdf_tooling_licenses_under_test", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot construct a module spec for scripts/licenses.py from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    missing = [name for name in _REQUIRED_SYMBOLS if not hasattr(module, name)]
    if missing:
        raise ImportError(
            f"{path} is missing expected symbol(s) {missing} — the mechanism-1 test seam "
            "(PDF-41 D1) requires every one of _REQUIRED_SYMBOLS to be present at import "
            "time. A rename in scripts/licenses.py must be a COLLECTION ERROR here, never "
            "a silently-skipped module (AC1)."
        )
    return module


licenses: Final[ModuleType] = _load_licenses_module(_resolve_licenses_module_path())


# --------------------------------------------------------------------------- #
# AC1 — the seam's own anti-lapse clause, mechanized as a permanent in-suite
# regression rather than only a one-off manual D6-style run. This is NOT one
# of the eight numbered reds (R1-R8); it is a property of THIS file's loader,
# proven directly against `tmp_path`, with no PDF_TOOLKIT_LICENSES_MODULE
# dance required.
# --------------------------------------------------------------------------- #


def test_ac1_loader_raises_a_named_import_error_when_a_bound_symbol_is_renamed(
    tmp_path: Path,
) -> None:
    """RED (AC1): rename `DENY` in a scratch copy of `scripts/licenses.py`
    and point the loader at it — expect a collection-shaped `ImportError`
    naming the missing symbol, never a skip and never a pass."""
    real_source = (REPO_ROOT / "scripts" / "licenses.py").read_text(encoding="utf-8")
    mutated_source = real_source.replace("DENY = re.compile", "DENY_RENAMED = re.compile", 1)
    assert mutated_source != real_source, "the rename substitution did not match — re-derive it"

    scratch = tmp_path / "licenses_ac1_renamed.py"
    scratch.write_text(mutated_source, encoding="utf-8")

    with pytest.raises(ImportError, match="DENY"):
        _load_licenses_module(scratch)


# --------------------------------------------------------------------------- #
# Arm A (D2) — the deny pattern rejects, and permits. AC3, AC4, AC5.
# --------------------------------------------------------------------------- #

#: SPDX + classifier forms, and prose-only forms that only `DENY_PROSE`
#: catches. Verified against the loaded module's own regexes before being
#: fixed here (see this file's Implementation Log / engineer report): the
#: three prose rows are spelled WITHOUT any parenthetical SPDX abbreviation
#: (e.g. "GNU Lesser General Public License v3", not "... (LGPLv2+)"), so
#: that `DENY` genuinely cannot match them and only `DENY_PROSE` does — a
#: form carrying the bracketed abbreviation (as PDF-41's own drafted example
#: did) is ALSO caught by `DENY` directly and would not exercise the
#: DENY_PROSE-only claim AC3 makes.
DENIED_TERMS: Final[tuple[str, ...]] = (
    "AGPL-3.0",
    "AGPL-3.0-only",
    "GPL-2.0",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "LGPL-2.1",
    "LGPL-3.0-only",
    "GPLv2+",
    "LGPLv2+",
    "GNU General Public License v3",
    "GNU Lesser General Public License v3",
    "GNU Affero General Public License v3",
)

#: Permitted forms. The four load-bearing rows are the arm's most valuable
#: assertions (D2): `DENY_PROSE` is "General Public License", and "Mozilla
#: Public License" is one careless `|` away from matching it.
PERMITTED_TERMS: Final[tuple[str, ...]] = (
    "MIT",
    "Apache-2.0",
    "BSD-3-Clause",
    "ISC",
    "Python-2.0",
    "HPND",
    "MPL-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)",
    "Mozilla Public License 1.1 (MPL 1.1)",
    "BSD-3-Clause, Apache-2.0, dependency licenses",  # pypdfium2, verbatim (E5)
)


@pytest.mark.parametrize("term", DENIED_TERMS, ids=DENIED_TERMS)
def test_ac3_is_denied_true_for_every_denied_term(term: str) -> None:
    """AC3. RED (R1) is this arm's OWN table planting a real GPL term as
    permitted (D6) — see the engineer report for the recorded, run instance;
    this file always ships with the correct classification."""
    assert licenses.is_denied(term) is True, (
        f"expected is_denied({term!r}) is True per D2's denied table — if this is red "
        "because the term was reclassified as permitted, that is exactly the planted-GPL "
        "control (R1) this arm exists to catch."
    )


@pytest.mark.parametrize("term", PERMITTED_TERMS, ids=PERMITTED_TERMS)
def test_ac4_is_denied_false_for_every_permitted_term(term: str) -> None:
    """AC4. RED (R2): weaken `DENY_PROSE` to `Public License` in a scratch
    copy of scripts/licenses.py — the four MPL/pypdfium2 rows fail. This is
    the "a gate that reddens on pikepdf is broken" direction
    (scripts/licenses.py:57-60); nothing else in the repository asserts it."""
    assert licenses.is_denied(term) is False, (
        f"expected is_denied({term!r}) is False per D2's permitted table — MPL-2.0 is "
        "PERMITTED and RECORDED (PLAN §12 R-11; pikepdf bundles libqpdf); scripts/"
        "licenses.py:57-60: 'a gate that reddens on pikepdf is broken'."
    )


def test_ac5_deny_and_deny_prose_patterns_are_asserted_exactly() -> None:
    """AC5. RED (R3/R4): any narrowing or widening of DENY fails this
    together with AC3/AC4. Widening is forbidden by PLAN §12 R-11 — MPL-2.0
    is permitted; scripts/licenses.py:57-60 calls the pattern 'THE PRODUCT'S
    ENTIRE PITCH'."""
    assert licenses.DENY.pattern == "AGPL|GPL|LGPL", (
        "DENY has been narrowed or widened — PLAN §12 R-11 forbids both directions; "
        "MPL-2.0 must remain permitted (scripts/licenses.py:57-60)."
    )
    assert licenses.DENY.flags & re.IGNORECASE, "DENY must be case-insensitive"
    assert licenses.DENY_PROSE.pattern == "General Public License", (
        "DENY_PROSE has drifted from the alias it is documented to be (scripts/licenses.py:62-65)."
    )
    assert licenses.DENY_PROSE.flags & re.IGNORECASE, "DENY_PROSE must be case-insensitive"


# --------------------------------------------------------------------------- #
# Arm B (D3) — the disjunctive path gets its OWN arm, discriminated by a
# state only :267 can produce. AC6, AC7, AC8, AC9.
# --------------------------------------------------------------------------- #


def _read_pyphen_expression(inventory_path: Path) -> str | None:
    """Read pyphen's licence expression from `inventory_path` at TEST TIME —
    never transcribed into this file (AC6). Layout, confirmed at HEAD:
    `pyphen` / `0.18.1` / `<expression>`, three consecutive lines. Returns
    `None` when the artifact does not exist or carries no `pyphen` entry
    (AC9)."""
    if not inventory_path.exists():
        return None
    lines = inventory_path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "pyphen" and index + 2 < len(lines):
            return lines[index + 2]
    return None


def _pyphen_expression_or_skip(inventory_path: Path) -> str:
    """Shared by AC6 and AC9: resolve pyphen's expression from
    `inventory_path`, or skip VISIBLY, naming the artifact and the package —
    never a vacuous pass (X-153: a control that cannot run must be visible
    as skipped)."""
    expression = _read_pyphen_expression(inventory_path)
    if expression is None:
        pytest.skip(
            f"pyphen is absent from {inventory_path} — the disjunctive arm (AC6/X-427) has "
            "no live disjunctive row from the pyphen package to assert against. This is a "
            "documented, visible skip (AC9), never a vacuous pass. If pyphen has genuinely "
            "left the dependency closure this is expected; otherwise re-derive the artifact "
            "path."
        )
    return expression


def test_ac6_disjunctive_branch_267_permits_pyphen_via_its_mpl_alternative() -> None:
    """AC6/D3/X-427: the disjunctive path's OWN arm, discriminated by a state
    only `scripts/licenses.py:267` can produce — `permitted is True AND
    denied != []`. RED (R5): mutate :267 to `return True, clean[0], []` in a
    scratch copy — the conjunction fails, proving this arm is about :267 and
    not about `evaluate_expression` in general."""
    expression = _pyphen_expression_or_skip(DEFAULT_INVENTORY_PATH)

    permitted, relied_on, denied = licenses.evaluate_expression(expression)

    # THE discriminating assertion. A clean-package expression cannot satisfy
    # this (see the MIT companion assertion below).
    assert permitted is True and denied != [], (
        f"expected the disjunctive branch at scripts/licenses.py:267 for pyphen's own "
        f"expression {expression!r}; got permitted={permitted!r} denied={denied!r} — this "
        "arm is supposed to be unreachable except through :267"
    )

    # Independently re-derive the expected shape from the RAW string via
    # plain str.split on ';' — never via split_disjuncts, so this is not
    # circular against the function under test.
    raw_terms = [term.strip() for term in expression.split(";")]
    assert len(raw_terms) == 3, (
        f"expected pyphen's THIRD_PARTY_LICENSES expression to carry exactly 3 ';'-joined "
        f"terms, got {raw_terms!r} — the assumption behind this arm has drifted since it "
        "was written; re-derive it rather than editing this assertion"
    )
    expected_denied, expected_clean = raw_terms[:2], raw_terms[2]
    assert relied_on == expected_clean == "Mozilla Public License 1.1 (MPL 1.1)"
    assert denied == expected_denied

    # Companion: a trivially clean expression must NOT satisfy the
    # discriminating conjunction — proving this arm rides :267's DISJUNCTIVE
    # case specifically, not the main path.
    mit_permitted, _mit_relied_on, mit_denied = licenses.evaluate_expression("MIT")
    assert mit_denied == [], "MIT must return via :267 with an EMPTY denied list"
    assert not (mit_permitted is True and mit_denied != []), (
        "a clean-package expression satisfied the disjunctive arm's discriminating "
        "conjunction — the arm has drifted onto the main path (X-427 violation)"
    )


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        pytest.param("GPLv2+", (False, None, ["GPLv2+"]), id="GPLv2+_pure_copyleft_via_268"),
        pytest.param("MIT", (True, "MIT", []), id="MIT_trivially_clean_via_267_empty_denied"),
        pytest.param("UNKNOWN", (False, None, ["UNKNOWN"]), id="UNKNOWN_via_262"),
    ],
)
def test_ac7_evaluate_expression_pinned_rows(
    expression: str, expected: tuple[bool, str | None, list[str]]
) -> None:
    """AC7: the other three rows of D3's table, pinned directly. RED: swap
    the expected tuple for any row — that row fails, naming the
    expression."""
    assert licenses.evaluate_expression(expression) == expected


def test_ac8_split_disjuncts_separator_contract() -> None:
    """AC8: `;` and uppercase ` OR ` split; lowercase ` or ` and commas do
    NOT. RED: add ` or ` to the separator tuple in a scratch copy — this arm
    fails, and a bare `later` term would match neither DENY nor DENY_PROSE —
    a false PASS on a pure-GPL package (scripts/licenses.py:224-231)."""
    assert licenses.split_disjuncts("A; B") == ["A", "B"]
    assert licenses.split_disjuncts("A OR B") == ["A", "B"]

    lowercase_or = licenses.split_disjuncts("GNU General Public License v2 or later")
    assert lowercase_or == ["GNU General Public License v2 or later"], (
        "split_disjuncts must NOT split on lowercase ' or ' — doing so would yield the bare "
        "term 'later', which matches neither DENY nor DENY_PROSE: a false PASS on a "
        "pure-GPL package (scripts/licenses.py:224-231)."
    )
    # The concrete consequence, demonstrated rather than only asserted in
    # prose: the bare word a bad split would produce is not denied.
    assert licenses.is_denied("later") is False

    commas = licenses.split_disjuncts("BSD-3-Clause, Apache-2.0, dependency licenses")
    assert commas == ["BSD-3-Clause, Apache-2.0, dependency licenses"], (
        "commas are an informal enumeration, not a disjunction (pypdfium2's expression); "
        "splitting on them would be exactly the silent widening R-11 forbids "
        "(scripts/licenses.py:220-224)."
    )


def test_ac9_pyphen_expression_lookup_skips_visibly_when_absent_from_the_artifact(
    tmp_path: Path,
) -> None:
    """AC9: point `_pyphen_expression_or_skip` at a fixture artifact with no
    `pyphen` row. RED: it must raise pytest's Skipped outcome, naming the
    artifact and the package — never silently return a value and never
    pass."""
    fixture = tmp_path / "THIRD_PARTY_LICENSES_without_pyphen"
    fixture.write_text("some-other-package\n1.0.0\nMIT\n\n", encoding="utf-8")
    assert _read_pyphen_expression(fixture) is None

    with pytest.raises(pytest.skip.Exception) as exc_info:
        _pyphen_expression_or_skip(fixture)
    message = str(exc_info.value)
    assert "pyphen" in message, "AC9's skip reason must name the package"
    assert str(fixture) in message, "AC9's skip reason must name the artifact"


# --------------------------------------------------------------------------- #
# Arm C (D4) — the empty ALLOWLIST is a property, asserted two ways. AC10,
# AC11, AC12.
# --------------------------------------------------------------------------- #


def _drive_cmd_check(
    monkeypatch: pytest.MonkeyPatch,
    rows_fixture: list[dict[str, str]],
    *,
    informational: bool = False,
) -> int:
    """Drive `cmd_check` over a caller-supplied static row list with the
    impure measurement pipeline patched at THREE points — never two.

    `cmd_check` (:355) calls `universal_names()` unconditionally when
    `informational` is False, and `universal_names` spawns `uv tree --frozen
    --universal --no-dev` as a real subprocess reading the real lockfile
    (:277-280). Patching only `ensure_pinned_env` and `rows` would (a) spawn
    that subprocess — violating AC2's "no subprocess, under 1s" — and (b)
    make `cmd_check` return 1 at :366 on the real closure's non-empty
    unmeasured set BEFORE reaching the offender/disjunctive reporting this
    file tests — a pass or fail for entirely the wrong reason. Returning
    `set()` here is always safe: `unmeasured = universal - measured -
    MARKER_ONLY` is empty whenever `universal` is empty, independent of the
    fixture's own contents. DO NOT DELETE THIS PATCH — see the module
    docstring and PDF-41's dispatch brief for the falsified premise this
    corrects.
    """
    monkeypatch.setattr(licenses, "ensure_pinned_env", lambda include_dev=False: Path("unused"))
    monkeypatch.setattr(licenses, "rows", lambda _python, ignore_self=False: rows_fixture)
    monkeypatch.setattr(licenses, "universal_names", lambda: set())
    return int(licenses.cmd_check(SimpleNamespace(informational=informational)))


def test_ac10_allowlist_is_empty_exactly() -> None:
    """AC10. RED (R6): add one entry to ALLOWLIST in a scratch copy — fails.
    The entry is NEVER added to the real file; if the work appears to need
    one, that is a finding and an operator question (PDF-41 §Out), not
    something to fix by editing this test."""
    assert licenses.ALLOWLIST == {}, (
        "scripts/licenses.py:69 — 'CURRENTLY EMPTY AND EXPECTED TO STAY EMPTY'. "
        ":70-77 explain why pyphen specifically must NOT be listed: a disjunctively "
        "licensed package is not an exception to the policy, it is a package the policy "
        "permits under one of its own alternative terms — allowlisting it would hide it "
        "behind a static dict instead of re-deciding it on every run against live metadata."
    )


def test_ac11_escape_hatch_suppresses_a_named_gpl_offender(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC11 (escape-hatch direction). RED (R7): remove the FIXTURE's
    allowlist entry (i.e. patch ALLOWLIST back to `{}`) — the return flips
    0 -> 1. This is what makes AC10's emptiness assertion meaningful: one
    entry is sufficient to pass a GPL package. The fixture key is
    ALREADY NORMALIZED and literally equal to the row name, so this arm
    tests the POLICY proposition and does not trip E6's KeyError defect
    (B-245, filed separately — see test_ac12 below)."""
    offender = {"Name": "planted-gpl-pkg", "Version": "1.0.0", "License": "GPL-3.0-only"}
    clean = {"Name": "clean-pkg", "Version": "2.0.0", "License": "MIT"}

    monkeypatch.setattr(licenses, "ALLOWLIST", {})
    denied_result = _drive_cmd_check(monkeypatch, [offender, clean])
    denied_stdout = capsys.readouterr().out
    assert denied_result == 1
    assert "planted-gpl-pkg" in denied_stdout, "the offender must be NAMED, not just counted"

    monkeypatch.setattr(
        licenses, "ALLOWLIST", {"planted-gpl-pkg": "verified MIT upstream; metadata is wrong"}
    )
    allowed_result = _drive_cmd_check(monkeypatch, [offender, clean])
    allowed_stdout = capsys.readouterr().out
    assert allowed_result == 0
    assert "ALLOWLISTED: planted-gpl-pkg" in allowed_stdout


@pytest.mark.xfail(
    strict=True,
    reason=(
        "B-245 (E6, filed not fixed — PDF-41 D7/AC12): scripts/licenses.py:343 tests "
        "ALLOWLIST membership on the PEP-503-normalized name, but :344 subscripts "
        "ALLOWLIST with the RAW row name. A key that normalizes equal to a row name but "
        "differs literally from it (key 'pdfminer-six' vs row name 'pdfminer.six') passes "
        "the :343 guard and raises KeyError at :344 instead of allowlisting — unreachable "
        "today only because the real ALLOWLIST is empty, which is this spec's own subject. "
        "scripts/licenses.py is NOT edited by this spec (§Out); this xfail PINS the defect "
        "so it stays visible. The day :344 is corrected to subscript by the matched key, "
        "this XPASSes and the suite goes red — that is the signal to retire the pin."
    ),
)
def test_ac12_pin_allowlist_raw_key_subscript_defect(monkeypatch: pytest.MonkeyPatch) -> None:
    offender = {"Name": "pdfminer.six", "Version": "1.0.0", "License": "GPL-3.0-only"}
    monkeypatch.setattr(
        licenses,
        "ALLOWLIST",
        {"pdfminer-six": "normalizes equal to the row name, not literally equal (E6)"},
    )
    result = _drive_cmd_check(monkeypatch, [offender])
    # This arm asserts the CORRECT behaviour, never the defective one, and that is
    # precisely what lets the pin fire. Today :344 raises KeyError before this line
    # is reached, so the arm xfails and the pin holds. The day :344 subscripts by
    # the MATCHED key, the offender is allowlisted, `cmd_check` returns 0, this
    # assertion PASSES, and the strict xfail turns the suite red — the retirement
    # signal this pin's own reason string promises.
    #
    # Asserting the DEFECTIVE outcome (`result == 1`) instead would xfail in BOTH
    # states — KeyError today, AssertionError after the fix — so the promised
    # signal could never fire and this pin would be an unfailable criterion.
    # Verified both directions against a mutated scratch copy before landing.
    assert result == 0, (
        "expected the allowlisted offender to be suppressed (cmd_check returns 0) once "
        "scripts/licenses.py:344 subscripts ALLOWLIST by the MATCHED key rather than the raw "
        "row name; reaching this assertion at all means the KeyError at :344 is gone and the "
        "B-245 pin should be retired"
    )


# --------------------------------------------------------------------------- #
# Arm D (D5) — the loud disjunctive report, B-024's entire mitigation. AC13.
# --------------------------------------------------------------------------- #


def test_ac13_disjunctive_row_prints_the_loud_multi_license_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC13: this asserts the MITIGATION `B-024` is held open on
    (scripts/licenses.py:371-380) — it does NOT close `B-024`, which remains
    an accepted-open suspected bug in the evaluator's disjunction handling
    (`split_disjuncts` treating `pip-licenses`'s `;`-joined trove-classifier
    list as a disjunction; PDF-41 §Out). RED (R8): delete the banner in a
    scratch copy of scripts/licenses.py — this arm fails naming the missing
    line.

    Uses a SYNTHETIC static row rather than the live pyphen artifact, so
    this arm does not depend on pyphen remaining in the dependency closure
    (unlike Arm B / AC6, which is deliberately tied to the live artifact)."""
    disjunctive_row = {
        "Name": "synthetic-disjunctive-pkg",
        "Version": "9.9.9",
        "License": "GPL-2.0-only; MIT",
    }

    result = _drive_cmd_check(monkeypatch, [disjunctive_row])
    stdout = capsys.readouterr().out

    assert result == 0, "the row is PERMITTED under its MIT alternative; the gate must pass"
    assert "MULTI-LICENSE (disjunctive)" in stdout, (
        "the loud banner is missing (B-024's mitigation)"
    )
    assert "full expression" in stdout
    assert "denied terms" in stdout
    assert "RELIED UPON" in stdout
    assert "GPL-2.0-only" in stdout, "the denied term must be named"
    assert "MIT" in stdout, "the relied-upon clean term must be named"
