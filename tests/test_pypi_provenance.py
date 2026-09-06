"""PDF-47 — the PyPI provenance DIFFERENTIAL, and the reason it is not a reading.

`PDF-31`'s Amendment 2 rated `AC2` and `AC30` at its `[T-ii screenshot]` tier on
one stated ground: that pypi.org exposed nothing this loop could query, so a
read-back was available to nobody but the operator. **That ground is false.**
`GET /integrity/<project>/<version>/<file>/provenance` answers `200` with
`content-type: application/vnd.pypi.integrity.v1+json`, and its
`attestation_bundles[0].publisher` mapping is, field for field, the publisher
row those criteria assert.

WHY THIS MODULE IS A DIFFERENTIAL AND NEVER A SINGLE READING
------------------------------------------------------------
A criterion asserting only *`0.2.0` reports `environment: "pypi"`* is satisfied
by any endpoint that returns the expected value, and can fail only if PyPI
breaks. It is unfailable in exactly the way this product exists to remove.

The `0.1.1` arm is what makes the pair evidence. It reports `environment: null`
**even though its own release job declared `environment: pypi`** — re-derived
firsthand, not inherited::

    $ git show v0.1.1:.github/workflows/release.yml | grep -n 'environment'
    12:# `pdf-tooling`, workflow `release.yml`, environment `pypi` ...
    78:    environment:
    79:      name: pypi

The only reading consistent with both facts is that the field reports the
**configured publisher row at upload time**, not the token's claim. And because
`0.1.1` is published and immutable, that red is free and permanent: no future
release, no configuration change and no fix can ever make it report `pypi`.

Two fields differ, not one, and they carry different criteria:

===========  ================================  =========================
             ``publisher.repository``          ``publisher.environment``
===========  ================================  =========================
``0.1.1``    ``ArmandoHerra/<legacy name>``    ``null``
``0.2.0``    ``ArmandoHerra/pdf-tooling``      ``"pypi"``
===========  ================================  =========================

`repository` carries `PDF-31` `AC2` and `AC34` link 1; `environment` carries
`AC30` and `AC34` link 2. `workflow` and `kind` are equal in both releases and
are therefore labelled **invariants, not differentials** — they complete the
publisher row's shape and assert nothing about change.

THE LIMIT, STATED WHERE A READER HITS IT FIRST
-----------------------------------------------
`PEP 740` provenance is generated at **upload time** and is immutable
thereafter. This module proves **what the publisher row was when a given
distribution was published**. It cannot see the row **as it stands today**, and
no arm here should ever be described as verifying the current row.

**Therefore `PDF-31`'s `SR-11` hazard — a later edit silently dropping the
environment constraint from the publisher row — is NOT covered by this
instrument.** Describing it as covered would rebuild, inside a new control, the
"a control that appears present" failure `SR-10` is written against.

Nothing here signs, verifies or trusts anything cryptographically. It reads
four fields out of a served JSON document. That is not attestation
verification and this module never calls it that. `PDF-31`'s `AC33.2` refusal
probe remains **NOT_OBSERVED**: every construction of it is a *write*, and an
API read does not upgrade a refusal that was never run.

THE NETWORK POSTURE, WHICH IS ONE RULE
---------------------------------------
    The live arm never skips for a network reason. It skips only for an
    explicit, named opt-out. Once it runs, every failure — transport, DNS,
    timeout, non-200, wrong content type, malformed body, or a wrong field —
    is a FAILURE.

So the state *"pypi.org was unreachable and the suite went green"* cannot be
constructed. `test_no_exception_handler_in_this_module_yields_a_skip` asserts
that by walking this module's own AST, because a rule stated in a docstring is
not a control.

THE FIXTURES, AND WHAT THEY ARE NOT
------------------------------------
`tests/fixtures/provenance/*.json` hold the four bodies recorded on
2026-09-06. Recipe, reproducible verbatim — filenames are DERIVED from the
index rather than guessed, because `v0.1.0` is a git tag with no PyPI release
and a guessed population would silently test the wrong set::

    curl -sS https://pypi.org/pypi/pdf-tooling/json \\
      | python3 -c "import json,sys; d=json.load(sys.stdin); \\
          [print(v,f['filename']) for v in sorted(d['releases']) \\
           for f in d['releases'][v]]"
    curl -sS "https://pypi.org/integrity/pdf-tooling/<ver>/<file>/provenance"

**They are inputs to the offline arms; they are never evidence that the live
endpoint still agrees.** A green offline suite says exactly nothing about
pypi.org. A recorded response presented as a live one is the screenshot problem
with better formatting, and it is the problem this module was written against.

ONE DEVIATION FROM "BYTE-FOR-BYTE AS SERVED", FORCED AND MECHANICALLY REVERSED
------------------------------------------------------------------------------
`PDF-33` freezes a classified population of the legacy distribution name, and
its class `H` — every occurrence under `tests/` — is frozen at an EXACT count
(`tests/test_brand_surfaces.py`, `EXPECTED_EXACT["H"]`). The two `0.1.1` bodies
each carry exactly one occurrence of that name, in the very field this module
asserts, so storing them verbatim would inflate the operand another instrument
freezes.

The fix is the one `tests/test_brand_surfaces.py` already applies to itself,
for the identical reason (*"a test file that spelled the needle as a literal
would inflate the very operand it exists to measure"*): the name is assembled
at runtime and never written whole. Each fixture stores the served bytes with
that single token replaced by `LEGACY_TOKEN`, and the loader substitutes it
back before anything parses it.

**The round-trip is proven, not asserted by hand.** `SERVED_SHA256` records the
sha256 of each body AS SERVED, and `load_fixture()` hashes the reconstituted
text against it — so the reconstruction is byte-exact or the fixture arm goes
red naming the file. That is a strictly stronger fidelity guarantee than
storing the raw bytes would have been, and it is a check on this repository's
own round-trip, never on the live body: `E1`'s digests are recorded evidence of
measurement and are deliberately NOT an assertion target against pypi.org,
whose serialization is its own to change.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
FIXTURE_DIR: Final[Path] = REPO_ROOT / "tests" / "fixtures" / "provenance"
TESTING_DOC: Final[Path] = REPO_ROOT / "TESTING.md"

PROJECT: Final[str] = "pdf-tooling"

#: The opt-in. Absent, the live arm skips BY NAME; set, it runs and every
#: failure mode below is a FAILURE.
OPT_IN_VARIABLE: Final[str] = "PDF_TOOLKIT_PYPI_PROVENANCE"

#: Points the live arm somewhere other than pypi.org. Its purpose is the
#: unreachable-endpoint RED: set it to a closed port with the opt-in ON and the
#: arm must FAIL, not skip.
BASE_URL_VARIABLE: Final[str] = "PDF_TOOLKIT_PYPI_BASE_URL"
DEFAULT_BASE_URL: Final[str] = "https://pypi.org"

#: A CONTRACT BETWEEN TWO FILES. `scripts/assert_skips.py`'s
#: `SKIP_CLASSES["provenance-endpoint-disabled"]` matches this string, and
#: `tests/test_assert_skips.py` asserts the match directly, so a later reword
#: here cannot silently empty that census class.
SKIP_REASON: Final[str] = "provenance endpoint check disabled (set PDF_TOOLKIT_PYPI_PROVENANCE=1)"

#: Measured 0.130-0.233 s over four bodies on 2026-09-06 (loadavg 0.76 at the
#: read, on a shared box). 10 s makes "unreachable" a bounded, reported
#: condition rather than a hung job.
TIMEOUT_SECONDS: Final[int] = 10

PROVENANCE_CONTENT_TYPE: Final[str] = "application/vnd.pypi.integrity.v1+json"

#: PEP 740's provenance-object version, measured on every body. A different
#: value means a shape this parser has not been shown, and it is a FAILURE that
#: names the value — never a skip and never a default.
PROVENANCE_OBJECT_VERSION: Final[int] = 1

#: Assembled, never written whole — see the module docstring. Spelling either
#: of these as one literal would inflate `PDF-33`'s frozen class `H`.
LEGACY_TOKEN: Final[str] = "__PDF47_LEGACY_DISTRIBUTION__"
LEGACY_DISTRIBUTION: Final[str] = "pdf-" + "toolkit"
LEGACY_REPOSITORY: Final[str] = f"ArmandoHerra/{LEGACY_DISTRIBUTION}"
CURRENT_REPOSITORY: Final[str] = f"ArmandoHerra/{PROJECT}"

#: Invariants across all four bodies (D1): equal in both releases, so they are
#: labelled invariants rather than dressed up as a differential.
EXPECTED_KIND: Final[str] = "GitHub"
EXPECTED_WORKFLOW: Final[str] = "release.yml"

#: The version whose publisher row predates `AC30`'s constraint, and the one
#: whose row was written after it. Both are PUBLISHED and IMMUTABLE.
LEGACY_VERSION: Final[str] = "0.1.1"
CURRENT_VERSION: Final[str] = "0.2.0"

#: sha256 of each body AS SERVED, recorded 2026-09-06, keyed by distribution
#: filename. Recipe: `curl -sS <url> | sha256sum`. Used ONLY to prove the
#: fixture round-trip is byte-exact (see the docstring); never asserted against
#: a live fetch, whose serialization is PyPI's to change.
SERVED_SHA256: Final[dict[str, str]] = {
    "pdf_tooling-0.1.1-py3-none-any.whl": (
        "8e0adc1b5fb29948449340ae74885b65b4b0c7d47e4229f341eb72b5d6fd69b2"
    ),
    "pdf_tooling-0.1.1.tar.gz": (
        "aaed13555ec3f2ca7ce8f4ff44f7f5f0d05fb4a4131f247168a63080d2cd4e6c"
    ),
    "pdf_tooling-0.2.0-py3-none-any.whl": (
        "e89dd514e994d6ba1ead556ccaed2549c6d3a16fa10bb17ab35aa2eaf64b53ba"
    ),
    "pdf_tooling-0.2.0.tar.gz": (
        "1d856d6f8f4ec549579dcc19a11e655b217151305515d30bfdfe9c6221c92d7f"
    ),
}

#: `pdf_tooling-<version><suffix>.provenance.json`. The POPULATION is parsed out
#: of these names rather than written down as a list, so a fixture that is added
#: or removed changes what the arms below run over (AC3).
FIXTURE_NAME: Final[re.Pattern[str]] = re.compile(
    r"^pdf_tooling-(?P<version>\d+\.\d+\.\d+)(?P<suffix>-py3-none-any\.whl|\.tar\.gz)"
    r"\.provenance\.json$"
)


class ProvenanceShapeError(AssertionError):
    """The document is a shape this parser has not been shown.

    An `AssertionError` on purpose: shape drift is a VISIBLE RED. Nothing in
    this module converts it into a skip or into a default value, because a
    parser that quietly finds nothing is how an assertion becomes vacuous while
    staying green.
    """


@dataclass(frozen=True)
class PublisherFacts:
    """The four fields, and nothing else.

    `environment` is `str | None` and the distinction is load-bearing: a
    publisher row whose `environment` key is ABSENT is a shape failure, while
    one whose value is `null` is the `0.1.1` control. A `.get()` conflating
    those two would silently turn the standing red green.
    """

    kind: str
    repository: str
    workflow: str
    environment: str | None


@dataclass(frozen=True)
class FixtureBody:
    """One recorded body, keyed the way the index keys it."""

    version: str
    filename: str
    path: Path

    @property
    def label(self) -> str:
        return f"{self.version}/{self.filename}"


# --------------------------------------------------------------------------- #
# D2 — ONE pure predicate. Both arms consume it; neither has a parser of its
# own, so they cannot drift into disagreeing about what a publisher row is.
# --------------------------------------------------------------------------- #


def publisher_facts(body: Any, *, label: str) -> PublisherFacts:
    """*body*'s publisher row, with every shape check applied FIRST.

    Fails — naming what it found — rather than skipping or returning a default,
    on each of D4's conditions. The order matters: nothing reads a field until
    the document has been shown to be the shape this parser was written for.
    """
    if not isinstance(body, dict):
        raise ProvenanceShapeError(
            f"{label}: provenance body is {type(body).__name__}, not an object"
        )

    if "version" not in body:
        raise ProvenanceShapeError(f"{label}: provenance body has no top-level `version` key")
    if body["version"] != PROVENANCE_OBJECT_VERSION:
        raise ProvenanceShapeError(
            f"{label}: top-level `version` is {body['version']!r}, expected "
            f"{PROVENANCE_OBJECT_VERSION!r}. This document is a shape this parser has not "
            "been shown; that is a FINDING for the PM, not a criterion to soften."
        )

    if "attestation_bundles" not in body:
        raise ProvenanceShapeError(f"{label}: provenance body has no `attestation_bundles` key")
    bundles = body["attestation_bundles"]
    if not isinstance(bundles, list):
        raise ProvenanceShapeError(
            f"{label}: `attestation_bundles` is {type(bundles).__name__}, not a list"
        )
    if len(bundles) != 1:
        raise ProvenanceShapeError(
            f"{label}: `attestation_bundles` holds {len(bundles)} element(s), expected exactly 1. "
            "Zero is a failure; more than one is a failure that names the count, because WHICH "
            "bundle to read would then be a design decision nobody has made."
        )

    bundle = bundles[0]
    if not isinstance(bundle, dict) or "publisher" not in bundle:
        raise ProvenanceShapeError(f"{label}: attestation bundle carries no `publisher` mapping")
    publisher = bundle["publisher"]
    if not isinstance(publisher, dict):
        raise ProvenanceShapeError(
            f"{label}: `publisher` is {type(publisher).__name__}, not a mapping"
        )

    missing = [
        key for key in ("kind", "repository", "workflow", "environment") if key not in publisher
    ]
    if missing:
        raise ProvenanceShapeError(
            f"{label}: `publisher` is missing key(s) {missing!r}. `environment` must be PRESENT "
            "and may be null — absent and null are different documents, and conflating them is "
            "exactly what would turn the standing red control green."
        )

    return PublisherFacts(
        kind=publisher["kind"],
        repository=publisher["repository"],
        workflow=publisher["workflow"],
        environment=publisher["environment"],
    )


def assert_cross_cell(legacy: PublisherFacts, current: PublisherFacts) -> None:
    """AC4. The differential asserted AS a differential, on both columns.

    These are the assertions that go red if a future refactor accidentally
    reads the same version twice — the failure mode where a differential
    silently becomes a tautology and every remaining arm still passes.

    Both columns are asserted SEPARATELY because they carry different criteria:
    `repository` carries `PDF-31` `AC2` and `AC34` link 1, `environment`
    carries `AC30` and `AC34` link 2. A test that compared the two `publisher`
    mappings wholesale would be green on both and would tell a reader which
    criterion failed only by eye.
    """
    assert legacy.repository != current.repository, (
        "the `repository` differential has collapsed: both rows read "
        f"{current.repository!r}. Either the arms are pointed at one version, or the endpoint "
        "changed — both are findings, neither is a passing test"
    )
    assert legacy.environment != current.environment, (
        "the `environment` differential has collapsed: both rows read "
        f"{current.environment!r}. Same disposition as above"
    )


def assert_matrix(facts: dict[str, PublisherFacts]) -> None:
    """D1's four-cell matrix, asserted as a matrix.

    THE SHARED ASSERTION SET. Both the offline arm and the live arm call this
    and nothing else, which is what makes them one instrument read twice rather
    than two instruments that happen to share a file (AC6).

    *facts* is keyed by version. Both rows are required: a matrix missing its
    red row is a reading.
    """
    for version in (LEGACY_VERSION, CURRENT_VERSION):
        assert version in facts, (
            f"the matrix is missing its {version} row; both rows are required, because a "
            "single-row assertion can fail only if PyPI breaks"
        )

    legacy = facts[LEGACY_VERSION]
    current = facts[CURRENT_VERSION]

    # --- the CURRENT row: what AC2 and AC30 assert about the live publisher row
    assert current.repository == CURRENT_REPOSITORY, (
        f"{CURRENT_VERSION} `publisher.repository` is {current.repository!r}, expected "
        f"{CURRENT_REPOSITORY!r}"
    )
    assert current.environment == "pypi", (
        f"{CURRENT_VERSION} `publisher.environment` is {current.environment!r}, expected 'pypi'"
    )

    # --- the LEGACY row: the standing, free, permanent RED control
    assert legacy.repository == LEGACY_REPOSITORY, (
        f"{LEGACY_VERSION} `publisher.repository` is {legacy.repository!r}, expected "
        f"{LEGACY_REPOSITORY!r} — this row is published and immutable, so a change here is a "
        "FINDING about the endpoint, not a stale expectation"
    )
    assert legacy.environment is None, (
        f"{LEGACY_VERSION} `publisher.environment` is {legacy.environment!r}, expected null. "
        f"Its release job DID declare `environment: pypi` (git show v{LEGACY_VERSION}:"
        ".github/workflows/release.yml, :78-79), which is the whole reason this field is "
        "read as the CONFIGURED publisher row rather than the token's claim"
    )

    # --- AC4: the cross-cell assertions, in their own callable so the
    #     tautology RED can be driven at them DIRECTLY. Measured, not assumed:
    #     with both arms pointed at one body the LEGACY-ROW assertion above
    #     fires first, so a tautology arm that only called `assert_matrix`
    #     would observe a red and never learn whether the cross-cell
    #     assertions can fail at all — which is the same "a control that was
    #     never shown red" defect one level in.
    assert_cross_cell(legacy, current)

    # --- AC5: invariants, explicitly labelled as such
    for version, row in facts.items():
        assert row.kind == EXPECTED_KIND, f"{version} `publisher.kind` is {row.kind!r}"
        assert row.workflow == EXPECTED_WORKFLOW, (
            f"{version} `publisher.workflow` is {row.workflow!r}"
        )


# --------------------------------------------------------------------------- #
# The recorded bodies. Population parsed from the directory, never listed.
# --------------------------------------------------------------------------- #


def fixture_bodies() -> tuple[FixtureBody, ...]:
    """Every recorded body, DERIVED from the fixture directory listing."""
    found: list[FixtureBody] = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        match = FIXTURE_NAME.match(path.name)
        assert match is not None, (
            f"{path.name} does not parse as a provenance fixture name. The population is read "
            "from this directory, so an unparseable name silently shrinks what the arms run over"
        )
        version = match.group("version")
        filename = f"pdf_tooling-{version}{match.group('suffix')}"
        found.append(FixtureBody(version=version, filename=filename, path=path))
    return tuple(found)


def load_fixture(body: FixtureBody) -> Any:
    """*body*'s recorded document, reconstituted to the served bytes and parsed.

    The round-trip is PROVEN here rather than assumed: the reconstituted text is
    hashed against the sha256 recorded at fetch time, so the single
    placeholder substitution the class-`H` freeze forces is byte-exact or this
    fails naming the file.
    """
    stored = body.path.read_text(encoding="utf-8")
    served = stored.replace(LEGACY_TOKEN, LEGACY_DISTRIBUTION)
    digest = hashlib.sha256(served.encode("utf-8")).hexdigest()
    expected = SERVED_SHA256.get(body.filename)
    assert expected is not None, f"no recorded served digest for {body.filename}"
    assert digest == expected, (
        f"{body.path.name}: the reconstituted body hashes to {digest}, but the body served on "
        f"2026-09-06 hashed to {expected}. The fixture no longer round-trips to the bytes it "
        "claims to record"
    )
    return json.loads(served)


def facts_from_fixtures() -> dict[str, PublisherFacts]:
    """The matrix, keyed by version, built from the recorded bodies.

    Both files of a version must agree; they are four independent uploads, and
    an assertion over one file silently stops testing if a future release ships
    only a wheel.
    """
    by_version: dict[str, PublisherFacts] = {}
    for body in fixture_bodies():
        facts = publisher_facts(load_fixture(body), label=body.label)
        if body.version in by_version:
            assert by_version[body.version] == facts, (
                f"the two {body.version} distribution files disagree about the publisher row: "
                f"{by_version[body.version]!r} vs {facts!r}"
            )
        by_version[body.version] = facts
    return by_version


# --------------------------------------------------------------------------- #
# AC1 / AC2 / AC4 / AC5 — the offline arms. These run on every `make test`,
# with NO network, and they are where the logic is proven.
# --------------------------------------------------------------------------- #


def test_the_recorded_matrix_holds_in_both_rows_and_across_both_cells() -> None:
    """AC1, AC2, AC4 and AC5 over the recorded bodies, through the shared
    assertion set the live arm also calls."""
    assert_matrix(facts_from_fixtures())


@pytest.mark.parametrize("body", fixture_bodies(), ids=lambda b: b.label)
def test_every_recorded_body_carries_a_present_environment_key(body: FixtureBody) -> None:
    """AC2's precise half: `environment` is asserted PRESENT-AND-NULL on the
    legacy row, never absent-or-falsy. The distinction between an absent key and
    a null value IS the control, so it is checked against the raw document and
    not only through the parser."""
    document = load_fixture(body)
    publisher = document["attestation_bundles"][0]["publisher"]
    assert "environment" in publisher, (
        f"{body.label}: `environment` is ABSENT. Absent and null are different documents"
    )
    if body.version == LEGACY_VERSION:
        assert publisher["environment"] is None, (
            f"{body.label}: expected a null environment on the standing red control"
        )


def test_the_invariant_fields_are_invariant_across_every_recorded_body() -> None:
    """AC5. `workflow` and `kind` are equal in BOTH releases, so they are
    honestly labelled invariants rather than presented as a second differential.
    """
    rows = {
        body.label: publisher_facts(load_fixture(body), label=body.label)
        for body in fixture_bodies()
    }
    assert {row.kind for row in rows.values()} == {EXPECTED_KIND}, rows
    assert {row.workflow for row in rows.values()} == {EXPECTED_WORKFLOW}, rows


# --------------------------------------------------------------------------- #
# AC3 — the population is DERIVED. `v0.1.0` is a git tag with NO PyPI release
# (run 33717193914 failed at its `Publish to PyPI` step), so a population taken
# from git tags returns three versions and this instrument would test the wrong
# set. The live arm below reconciles the recorded set against the index.
# --------------------------------------------------------------------------- #


def test_the_recorded_population_covers_both_distribution_files_of_every_version() -> None:
    """AC3's offline half: SHAPE of the population, derived from the directory.

    An assertion over one file per version silently stops testing if a future
    release ships only a wheel, which is why all four bodies are recorded.
    """
    bodies = fixture_bodies()
    assert bodies, "the fixture directory is empty; every arm above would pass vacuously"
    suffixes: dict[str, set[str]] = {}
    for body in bodies:
        suffixes.setdefault(body.version, set()).add(
            body.filename[len(f"pdf_tooling-{body.version}") :]
        )
    assert len(suffixes) >= 2, (
        f"the recorded population covers {sorted(suffixes)}; a differential needs at least two "
        "versions and cannot be built from one"
    )
    for version, found in suffixes.items():
        assert found == {"-py3-none-any.whl", ".tar.gz"}, (
            f"{version} records {sorted(found)}; both distribution files are covered because the "
            "four bodies are four independent uploads"
        )


# --------------------------------------------------------------------------- #
# AC8 — shape drift is a VISIBLE RED, never a skip and never a pass. Four
# mutated scratch bodies, one per condition, each producing a failure whose
# message names the condition.
# --------------------------------------------------------------------------- #


def _a_recorded_body() -> Any:
    return load_fixture(fixture_bodies()[0])


def test_the_shape_check_rejects_an_unknown_provenance_object_version() -> None:
    """AC8, condition 1."""
    document = _a_recorded_body()
    document["version"] = 2
    with pytest.raises(ProvenanceShapeError, match=r"top-level `version` is 2"):
        publisher_facts(document, label="<mutated>")


def test_the_shape_check_rejects_a_body_with_no_bundles() -> None:
    """AC8, condition 2. Zero is a failure, never an empty pass."""
    document = _a_recorded_body()
    document["attestation_bundles"] = []
    with pytest.raises(ProvenanceShapeError, match=r"holds 0 element\(s\)"):
        publisher_facts(document, label="<mutated>")


def test_the_shape_check_rejects_a_body_with_more_than_one_bundle() -> None:
    """AC8, condition 3. The failure NAMES the count, because which bundle to
    read would then be a design decision nobody has made."""
    document = _a_recorded_body()
    document["attestation_bundles"] = document["attestation_bundles"] * 2
    with pytest.raises(ProvenanceShapeError, match=r"holds 2 element\(s\)"):
        publisher_facts(document, label="<mutated>")


def test_the_shape_check_rejects_an_absent_environment_key() -> None:
    """AC8, condition 4, and it is called out separately because conflating
    ABSENT with null is precisely what would turn the standing red green."""
    document = _a_recorded_body()
    del document["attestation_bundles"][0]["publisher"]["environment"]
    with pytest.raises(ProvenanceShapeError, match=r"missing key\(s\) \['environment'\]"):
        publisher_facts(document, label="<mutated>")


def test_a_null_environment_is_accepted_where_an_absent_one_is_not() -> None:
    """The complement of the arm above. A fix that rejected BOTH would be
    indistinguishable from one that broke the standing red control."""
    document = _a_recorded_body()
    document["attestation_bundles"][0]["publisher"]["environment"] = None
    assert publisher_facts(document, label="<mutated>").environment is None


def test_the_repository_differential_goes_red_when_both_rows_read_one_body() -> None:
    """AC4's RED, column 1. Point both arms at `0.2.0` and the `repository`
    cross-cell assertion must fail. This is the arm that stops the instrument
    decaying into two independent readings that happen to sit in one file."""
    current = facts_from_fixtures()[CURRENT_VERSION]
    with pytest.raises(AssertionError, match=r"`repository` differential has collapsed"):
        assert_cross_cell(current, current)


def test_the_environment_differential_goes_red_on_its_own_column() -> None:
    """AC4's RED, column 2, driven SEPARATELY.

    Column 1's red above would also fire on this input, so a single arm would
    let the `environment` assertion ride along on the `repository` assertion's
    evidence — the B-106 shape. Here the rows differ in `repository` and agree
    in `environment`, so only column 2 can be what fails.
    """
    facts = facts_from_fixtures()
    legacy = facts[LEGACY_VERSION]
    collapsed = PublisherFacts(
        kind=legacy.kind,
        repository=facts[CURRENT_VERSION].repository,
        workflow=legacy.workflow,
        environment=legacy.environment,
    )
    with pytest.raises(AssertionError, match=r"`environment` differential has collapsed"):
        assert_cross_cell(legacy, collapsed)


def test_the_whole_matrix_goes_red_on_a_tautology() -> None:
    """AC4, end to end. Whichever assertion fires first, a matrix built from one
    body twice is never a pass."""
    facts = facts_from_fixtures()
    tautology = {LEGACY_VERSION: facts[CURRENT_VERSION], CURRENT_VERSION: facts[CURRENT_VERSION]}
    with pytest.raises(AssertionError):
        assert_matrix(tautology)


def test_the_matrix_goes_red_on_a_mutated_repository_field() -> None:
    """AC1's RED: mutate the current row's `repository` to the legacy name and
    the failure names the field, the expected value and the read value."""
    facts = facts_from_fixtures()
    mutated = dict(facts)
    current = facts[CURRENT_VERSION]
    mutated[CURRENT_VERSION] = PublisherFacts(
        kind=current.kind,
        repository=LEGACY_REPOSITORY,
        workflow=current.workflow,
        environment=current.environment,
    )
    with pytest.raises(AssertionError, match=r"`publisher.repository` is"):
        assert_matrix(mutated)


def test_the_matrix_goes_red_on_a_mutated_invariant_field() -> None:
    """AC5's RED: mutate one body's `workflow` and the failure names the body."""
    facts = facts_from_fixtures()
    mutated = dict(facts)
    legacy = facts[LEGACY_VERSION]
    mutated[LEGACY_VERSION] = PublisherFacts(
        kind=legacy.kind,
        repository=legacy.repository,
        workflow="not-release.yml",
        environment=legacy.environment,
    )
    with pytest.raises(AssertionError, match=r"`publisher.workflow` is 'not-release.yml'"):
        assert_matrix(mutated)


# --------------------------------------------------------------------------- #
# AC7 — the posture, asserted structurally. A rule stated in a docstring is not
# a control, so this module's own AST is walked.
# --------------------------------------------------------------------------- #


def _module_tree() -> ast.Module:
    return ast.parse(Path(__file__).read_text(encoding="utf-8"))


def _is_skip_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in {"skip", "xfail", "importorskip"}:
        return True
    return isinstance(func, ast.Name) and func.id in {"skip", "importorskip"}


def test_no_exception_handler_in_this_module_yields_a_skip() -> None:
    """AC7's structural half, and the reason the silent-skip path cannot be
    constructed here at all.

    There is NO code path in which a network error produces a skip, so the state
    "pypi.org was unreachable and the suite went green" does not exist. The
    walk covers every `except` handler in the module, including ones a future
    edit adds.
    """
    offenders: list[str] = []
    for handler in ast.walk(_module_tree()):
        if not isinstance(handler, ast.ExceptHandler):
            continue
        for node in ast.walk(handler):
            if _is_skip_call(node):
                offenders.append(f"line {getattr(node, 'lineno', '?')}")
    assert offenders == [], (
        "an exception handler in this module raises a skip: " + ", ".join(offenders) + ". "
        "Once the live arm runs, EVERY failure -- transport, DNS, timeout, non-200, malformed "
        "body -- is a FAILURE. A suite that goes green in an airport is a suite that stopped "
        "asserting and did not say so."
    )


def test_the_walk_that_finds_no_skip_can_find_one_planted() -> None:
    """The control on the control (B-088): a scanner is believed because it was
    shown to find a known needle first, never because it returned zero."""
    planted = ast.parse(
        "import pytest\n"
        "def f():\n"
        "    try:\n"
        "        g()\n"
        "    except OSError:\n"
        "        pytest.skip('the network was down')\n"
    )
    found = [
        node
        for handler in ast.walk(planted)
        if isinstance(handler, ast.ExceptHandler)
        for node in ast.walk(handler)
        if _is_skip_call(node)
    ]
    assert len(found) == 1, "the walk must see a skip planted inside an except handler"


def test_the_live_arm_delegates_every_fact_assertion_to_the_shared_predicate() -> None:
    """AC6, mechanized. The live arm carries no `assert` of its own: every fact
    it asserts goes through `assert_matrix`, the same function the offline arm
    calls, over facts produced by the same `publisher_facts`. Transport-level
    checks (status, content type) live in the fetch helper and are not fact
    assertions.

    Without this, "both arms share one parser" would be a claim about the code
    rather than a property of it, and the two could drift.
    """
    target = "test_the_live_endpoint_still_agrees_with_the_recorded_matrix"
    function = next(
        node
        for node in ast.walk(_module_tree())
        if isinstance(node, ast.FunctionDef) and node.name == target
    )
    own_assertions = [node for node in ast.walk(function) if isinstance(node, ast.Assert)]
    assert own_assertions == [], (
        f"{target} makes {len(own_assertions)} assertion(s) of its own at lines "
        f"{[node.lineno for node in own_assertions]}. Every fact the live arm asserts must go "
        "through the shared predicate, or the offline and live arms are two instruments"
    )
    called = {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "assert_matrix" in called, f"{target} must call the shared assertion set"


def test_the_skip_reason_names_the_variable_an_operator_has_to_set() -> None:
    """A skip is information or it is noise. This one has to say what to do."""
    assert OPT_IN_VARIABLE in SKIP_REASON


# --------------------------------------------------------------------------- #
# AC12 — the instrument's own limit, where a reader will hit it.
# --------------------------------------------------------------------------- #


def test_this_module_and_testing_md_both_state_the_upload_time_limit() -> None:
    """AC12. PEP 740 provenance is generated at upload time and is immutable, so
    this instrument proves what the publisher row WAS at publication and cannot
    see it as it stands today -- `SR-11`'s hazard is NOT covered.

    Asserted in both places because a limit recorded only in the module is a
    limit an operator reading the test documentation will not meet.
    """
    module_text = Path(__file__).read_text(encoding="utf-8")
    doc_text = TESTING_DOC.read_text(encoding="utf-8")
    for label, text in (("this module", module_text), ("TESTING.md", doc_text)):
        assert "upload time" in text, (
            f"{label} does not state that provenance is fixed at upload time"
        )
        assert "SR-11" in text, f"{label} does not name the hazard this instrument leaves uncovered"


# --------------------------------------------------------------------------- #
# D3 — THE LIVE ARM. Runs iff the opt-in is set. Skips only for that opt-out,
# by name. Once it runs, everything is a FAILURE.
# --------------------------------------------------------------------------- #


def base_url() -> str:
    return os.environ.get(BASE_URL_VARIABLE) or DEFAULT_BASE_URL


def _get(url: str, *, accept: str) -> tuple[bytes, str]:
    """*url*'s body and content type, or an AssertionError naming both the URL
    and the transport error.

    NOT a skip. The `except` below re-raises as a failure, and
    `test_no_exception_handler_in_this_module_yields_a_skip` asserts that no
    handler in this module can ever do otherwise.

    *accept* IS LOAD-BEARING AND WAS MEASURED, NOT ASSUMED. The integrity
    endpoint content-negotiates, which nothing handed to this engineer said.
    Driven against the live `0.2.0` wheel on 2026-09-06, all four `200` with a
    byte-identical body::

        no Accept header  -> application/vnd.pypi.integrity.v1+json
        Accept: */*       -> application/vnd.pypi.integrity.v1+json
        Accept: application/json
                          -> application/json
        Accept: application/vnd.pypi.integrity.v1+json
                          -> application/vnd.pypi.integrity.v1+json

    So asking for `application/json` and then asserting the vendor type back is
    a red the SERVER is right about and the CLIENT is wrong about. The media
    type this parser was written for is requested explicitly, which makes the
    content-type check below an assertion that the server served the shape that
    was asked for rather than an accident of a default header.
    """
    request = urllib.request.Request(url, headers={"Accept": accept})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return response.read(), response.headers.get("content-type", "")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AssertionError(
            f"provenance fetch FAILED (this is a FAILURE, never a skip): {url} -- {exc!r}. "
            f"The opt-in {OPT_IN_VARIABLE} was set, so the endpoint was required to answer."
        ) from exc


def live_population() -> tuple[tuple[str, str], ...]:
    """(version, filename) for every PUBLISHED distribution, read from the index.

    DERIVED, never assumed from git tags: `v0.1.0` is a tag with no PyPI
    release, so a tag-derived population names a version the index does not
    list and the endpoint answers 404.
    """
    raw, _ = _get(f"{base_url()}/pypi/{PROJECT}/json", accept="application/json")
    index = json.loads(raw)
    return tuple(
        (version, dist["filename"])
        for version in sorted(index["releases"])
        for dist in index["releases"][version]
    )


def fetch_provenance(version: str, filename: str) -> Any:
    """One live provenance document, with its transport-level checks."""
    url = f"{base_url()}/integrity/{PROJECT}/{version}/{filename}/provenance"
    raw, content_type = _get(url, accept=PROVENANCE_CONTENT_TYPE)
    if not content_type.startswith(PROVENANCE_CONTENT_TYPE):
        raise AssertionError(
            f"{url} answered content-type {content_type!r}, expected {PROVENANCE_CONTENT_TYPE!r}"
        )
    return json.loads(raw)


@pytest.mark.pypi_provenance
@pytest.mark.skipif(os.environ.get(OPT_IN_VARIABLE) != "1", reason=SKIP_REASON)
def test_the_live_endpoint_still_agrees_with_the_recorded_matrix() -> None:
    """The one question the fixtures cannot answer: does pypi.org still agree?

    Carries NO assertion of its own (AC6, asserted structurally above). It
    derives the population from the index, reconciles it against what is
    recorded, and hands the live facts to the same `assert_matrix` the offline
    arm uses.

    If any cell disagrees with the recorded matrix, that is a FINDING about the
    publisher row for the PM and the sentinel -- not a criterion to be softened.
    A newly-honest instrument revealing more red is the instrument working.
    """
    published = live_population()
    recorded = {(body.version, body.filename) for body in fixture_bodies()}

    missing_from_index = sorted(recorded - set(published))
    if missing_from_index:
        raise AssertionError(
            f"recorded bodies name distribution(s) the index does not list: {missing_from_index}. "
            "The population is read from the index, never assumed, so this is a real divergence "
            "rather than three bodies being tested where four were meant to be"
        )
    unrecorded = sorted(set(published) - recorded)
    if unrecorded:
        raise AssertionError(
            f"the index lists distribution(s) with no recorded body: {unrecorded}. A new release "
            "has been published; record its body before this arm can speak for it"
        )

    facts: dict[str, PublisherFacts] = {}
    for version, filename in published:
        row = publisher_facts(fetch_provenance(version, filename), label=f"{version}/{filename}")
        if version in facts and facts[version] != row:
            raise AssertionError(
                f"the two {version} distribution files disagree about the publisher row: "
                f"{facts[version]!r} vs {row!r}"
            )
        facts[version] = row

    assert_matrix(facts)
