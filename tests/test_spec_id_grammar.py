"""PDF-100 (X-953, B-383): the spec-id grammar is defined once, and a second copy is refused."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from spec_id_grammar import SPEC_ID_GRAMMAR

REPO_ROOT = Path(__file__).resolve().parent.parent

LEGAL = (
    "PDF-01",
    "PDF-09",
    "PDF-10",
    "PDF-98",
    "PDF-99",
    "PDF-100",
    "PDF-101",
    "PDF-999",
    "PDF-1000",
)
ILLEGAL = ("PDF-1", "PDF-007", "PDF-099", "PDF-0100", "PDF-", "PDF-1a", "pdf-100", "PDF-100 ")

#: Needles are assembled at runtime so this file does not match its own census.
_STEM = "PDF" + "-"
_TWO_DIGIT_SPELLINGS = (
    _STEM + r"\d" + r"\d",
    _STEM + r"\d" + "{2}",
    _STEM + "[0-9]" + "{2}",
    _STEM + "[0-9]" + "[0-9]",
)
_NEEDLE = re.compile("|".join(re.escape(s) for s in _TWO_DIGIT_SPELLINGS), re.IGNORECASE)

#: The only three places the two-digit grammar may still be spelled, keyed by path and matched
#: text (never by line number): the frozen historical form, the prime-doc deny list, and a
#: landed audit's prose.
ALLOWED_SITES = frozenset(
    {
        ("tests/spec_id_grammar.py", _STEM + r"\d" + r"\d"),
        ("tests/test_docs_antirot.py", "pdf-[0-9]" + "{2}"),
        ("tests/acceptance/audit_pdf_01.py", "pdf-[0-9]" + "{2}"),
    }
)


def two_digit_grammar_sites(roots: list[Path], base: Path) -> list[tuple[str, str]]:
    """`(path relative to base, matched text)` for every two-digit spelling under *roots*."""
    found: set[tuple[str, str]] = set()
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            for match in _NEEDLE.finditer(path.read_text()):
                found.add((path.relative_to(base).as_posix(), match.group(0)))
    return sorted(found)


@pytest.mark.parametrize("candidate", LEGAL)
def test_the_grammar_admits_legal_ids(candidate: str) -> None:
    assert re.fullmatch(SPEC_ID_GRAMMAR, candidate)


@pytest.mark.parametrize("candidate", ILLEGAL)
def test_the_grammar_rejects_illegal_ids(candidate: str) -> None:
    assert re.fullmatch(SPEC_ID_GRAMMAR, candidate) is None


def test_the_grammar_admits_two_and_three_digit_ids_and_nothing_else() -> None:
    accepted = [s for s in (*LEGAL, *ILLEGAL) if re.fullmatch(SPEC_ID_GRAMMAR, s)]

    assert accepted == list(LEGAL)


def test_the_spec_id_grammar_is_spelled_once() -> None:
    sites = two_digit_grammar_sites([REPO_ROOT / "tests", REPO_ROOT / "scripts"], REPO_ROOT)

    assert set(sites) == ALLOWED_SITES, sites
    assert len(ALLOWED_SITES) == 3


def test_the_census_names_a_planted_copy(tmp_path: Path) -> None:
    planted = tmp_path / "tests" / "test_x.py"
    planted.parent.mkdir()
    planted.write_text('import re\nX = re.compile(r"' + _STEM + r"\d" + r"\d" + '")\n')

    assert two_digit_grammar_sites([tmp_path / "tests"], tmp_path) == [
        ("tests/test_x.py", _STEM + r"\d" + r"\d")
    ]
