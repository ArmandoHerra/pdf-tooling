"""Documentation anti-rot.

The prime documents rot in one predictable way: someone records progress in
them. A status line, a count, a spec-by-spec chain — each is correct for about a
week and actively misleading afterwards, and nothing catches it because prose is
not executed.

So the rule is mechanised rather than remembered. ``README.md`` and ``CLAUDE.md``
carry exactly **one** phase line each, and that line is a pointer rather than a
status: written correctly it needs editing zero times as work lands, which is a
stronger guarantee than "at most one line to edit".

The fourth check is the interesting one. It reads every ``make <target>`` string
out of the documentation and asserts the target exists — a doc-truth check that
would have caught the bootstrap command this repository documented before any
`Makefile` existed, and that every later change inherits for free.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The two documents an agent or a newcomer reads first.
PRIME_DOCS = ("README.md", "CLAUDE.md")

#: Every document allowed to name a `make` target.
DOCS_WITH_COMMANDS = ("README.md", "CLAUDE.md", "CONTRIBUTING.md", "TESTING.md")

PHASE_LINE = re.compile(r"^\*\*Current phase:\*\*", re.MULTILINE)
SPEC_ID = re.compile(r"pdf-[0-9]{2}", re.IGNORECASE)
SPEC_COUNT = re.compile(r"[0-9]+ +specs?\b", re.IGNORECASE)
MAKE_TARGET = re.compile(r"\bmake +([a-zA-Z0-9_-]+)")


def read(name: str) -> str:
    return (REPO_ROOT / name).read_text()


def makefile_targets() -> set[str]:
    text = (REPO_ROOT / "Makefile").read_text()
    return set(re.findall(r"^([a-zA-Z0-9_.-]+):", text, re.MULTILINE))


@pytest.mark.parametrize("doc", PRIME_DOCS)
def test_exactly_one_phase_line(doc: str) -> None:
    matches = PHASE_LINE.findall(read(doc))
    assert len(matches) == 1, f"{doc} must carry exactly one '**Current phase:**' line"


@pytest.mark.parametrize("doc", PRIME_DOCS)
def test_no_spec_identifier_is_embedded(doc: str) -> None:
    found = SPEC_ID.findall(read(doc))
    assert found == [], f"{doc} names {found}; per-spec status belongs in the spec index"


@pytest.mark.parametrize("doc", PRIME_DOCS)
def test_no_spec_count_is_embedded(doc: str) -> None:
    found = SPEC_COUNT.findall(read(doc))
    assert found == [], (
        f"{doc} states a count ({found}); a count is wrong the day after it is written"
    )


@pytest.mark.parametrize("doc", DOCS_WITH_COMMANDS)
def test_every_documented_make_target_exists(doc: str) -> None:
    targets = makefile_targets()
    referenced = set(MAKE_TARGET.findall(read(doc)))
    missing = sorted(referenced - targets)
    assert missing == [], f"{doc} documents {missing}, which the Makefile does not define"


def test_the_phase_line_points_at_the_index_rather_than_restating_it() -> None:
    """A pointer needs editing zero times; a status needs editing every time."""
    for doc in PRIME_DOCS:
        line = next(
            line for line in read(doc).splitlines() if line.startswith("**Current phase:**")
        )
        assert "SPEC-INDEX.md" in line
        assert "changelog.md" in line
