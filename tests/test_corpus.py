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
        if spec.rotations:
            assert int(page.get("/Rotate", 0)) == spec.rotations[index], (
                f"{name}: page {index} rotation"
            )
        else:
            assert int(page.get("/Rotate", 0)) == 0, f"{name}: unexpected rotation"

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
