"""AC1 / AC2 — the generated corpus matches its own spec and is deterministic.

Every fixture is re-read with pypdf/pikepdf and checked against its **own**
:class:`~tests.corpus.FixtureSpec` (AC1). Building the corpus twice into two
different temp directories is asserted byte-identical for the six unencrypted
fixtures and only semantically identical for `encrypted_aes256` (AC2) — see
`tests/corpus.py`'s module docstring for why that one fixture is exempt from
byte-identity by construction.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pikepdf
import pypdf
import pytest

from corpus import ENCRYPTED_PASSWORD, FIXTURE_NAMES, Corpus, build_corpus

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Corpus:
    return build_corpus(tmp_path_factory.mktemp("corpus-ac1"))


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_every_fixture_matches_its_own_spec(built: Corpus, name: str) -> None:
    spec = built.spec(name)
    path = built.path(name)
    assert path.is_file(), f"{name}: fixture file was not built"

    reader = pypdf.PdfReader(str(path))
    if spec.encrypted:
        assert reader.is_encrypted, f"{name}: spec says encrypted but reader disagrees"
        result = reader.decrypt(ENCRYPTED_PASSWORD)
        assert result != pypdf.PasswordType.NOT_DECRYPTED, (
            f"{name}: the fixture's own password failed"
        )
    else:
        assert not reader.is_encrypted, f"{name}: spec says plain but reader disagrees"

    assert len(reader.pages) == spec.page_count, f"{name}: page count"
    for index, page in enumerate(reader.pages):
        text = page.extract_text()
        assert spec.page_texts[index] in text, f"{name}: page {index} text mismatch"

        # PDF-17/B-084 -- ABSENT and ZERO are different states, and until now
        # this test could not tell them apart: BOTH branches read
        # `page.get("/Rotate", 0)`, which answers `0` for a page with no
        # `/Rotate` key AND for a page with an explicit `/Rotate 0`. A verb
        # that must distinguish the two had no fixture that could tell it it
        # was wrong. The key's PRESENCE is now asserted in both directions, per
        # `FixtureSpec.rotate_key_absent_on`, so every fixture states which it
        # is rather than being silently flattened.
        key_present = "/Rotate" in page
        if index in spec.rotate_key_absent_on:
            assert not key_present, (
                f"{name}: page {index} carries an explicit /Rotate, but its spec says the "
                "key is ABSENT -- the one state B-084 says the corpus could not express"
            )
        else:
            assert key_present, (
                f"{name}: page {index} carries NO /Rotate key, but its spec does not list "
                f"page {index} in rotate_key_absent_on. Declare it: an undeclared absence "
                "is exactly the ambiguity B-084 filed."
            )
            expected = spec.rotations[index] if spec.rotations else 0
            assert int(page.get("/Rotate", 0)) == expected, f"{name}: page {index} rotation"

    if spec.metadata:
        with pikepdf.open(str(path), password=ENCRYPTED_PASSWORD if spec.encrypted else "") as pdf:
            docinfo = pdf.docinfo
            for key, expected in (
                ("title", "/Title"),
                ("author", "/Author"),
                ("subject", "/Subject"),
                ("keywords", "/Keywords"),
            ):
                assert str(docinfo.get(expected, "")) == spec.metadata[key], f"{name}: {expected}"

    if spec.embedded_jpeg:
        with pikepdf.open(str(path)) as pdf:
            images = pdf.pages[0].get_images()
            assert images, f"{name}: spec says embedded_jpeg but no image XObject was found"

    if spec.table:
        text = reader.pages[0].extract_text()
        for row in spec.table:
            for cell in row:
                assert cell in text, f"{name}: cell {cell!r} missing from extracted text"


def test_the_encrypted_fixture_rejects_the_wrong_password(built: Corpus) -> None:
    reader = pypdf.PdfReader(str(built.path("encrypted_aes256")))
    assert reader.is_encrypted
    result = reader.decrypt("definitely-not-the-fixture-password")
    assert result == pypdf.PasswordType.NOT_DECRYPTED


UNENCRYPTED_FIXTURES = tuple(name for name in FIXTURE_NAMES if name != "encrypted_aes256")


def test_the_absent_rotate_state_is_expressible_at_all(built: Corpus) -> None:
    """B-084's own subject, pinned as a FACT about the corpus rather than a
    property some fixture happens to have.

    Without this, `rotate_absent` could lose its whole purpose to a refactor
    and only `test_every_fixture_matches_its_own_spec` would notice -- and only
    if the spec were updated in the same edit, which is precisely how a fixture
    stops expressing the state it was built for."""
    declared = [name for name in FIXTURE_NAMES if built.spec(name).rotate_key_absent_on]
    assert "rotate_absent" in declared, (
        "the rotate_absent fixture no longer declares an absent /Rotate -- the corpus is "
        "back to the B-084 state where no fixture can express a page with no /Rotate key"
    )
    reader = pypdf.PdfReader(str(built.path("rotate_absent")))
    assert "/Rotate" not in reader.pages[0], "rotate_absent carries a /Rotate key"
    # And the contrast: `rotated` page 1 carries an EXPLICIT /Rotate 0, which
    # is the other half of the distinction and the reason `setPageRotation(0)`
    # is not the same as leaving the key off.
    rotated = pypdf.PdfReader(str(built.path("rotated")))
    assert "/Rotate" in rotated.pages[0]
    assert int(rotated.pages[0]["/Rotate"]) == 0


def test_six_unencrypted_fixtures_are_byte_identical_across_two_builds(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    first = build_corpus(tmp_path_factory.mktemp("corpus-build-a"))
    second = build_corpus(tmp_path_factory.mktemp("corpus-build-b"))
    for name in UNENCRYPTED_FIXTURES:
        first_hash = _sha256(first.path(name))
        second_hash = _sha256(second.path(name))
        assert first_hash == second_hash, (
            f"{name} is not byte-identical across two independent builds"
        )


def test_the_encrypted_fixture_is_semantically_identical_across_two_builds(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Exempt from byte-identity by construction (a fresh AES-256 salt per build).

    Proven SEMANTICALLY instead: decrypting two independent builds yields the
    same page count and the same per-page text. The byte-difference assertion
    below is the honest half of this test — it proves the exemption is real
    rather than accidentally true.
    """
    first = build_corpus(tmp_path_factory.mktemp("corpus-enc-a"))
    second = build_corpus(tmp_path_factory.mktemp("corpus-enc-b"))
    assert _sha256(first.path("encrypted_aes256")) != _sha256(second.path("encrypted_aes256")), (
        "encrypted_aes256 was byte-identical across two builds -- the AES-256 salt "
        "exemption no longer holds, which the test suite should know about"
    )

    for corpus in (first, second):
        spec = corpus.spec("encrypted_aes256")
        reader = pypdf.PdfReader(str(corpus.path("encrypted_aes256")))
        reader.decrypt(ENCRYPTED_PASSWORD)
        assert len(reader.pages) == spec.page_count
        for index, page in enumerate(reader.pages):
            assert spec.page_texts[index] in page.extract_text()
