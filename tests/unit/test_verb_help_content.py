"""AC23 — documentation, mechanized. ``merge --help``/``split --help`` are
this spec's documentation surface (Scope > Out: README.md/CLAUDE.md are
untouched, HC-5); every rule this spec defines is asserted here as a grep
over captured ``--help`` output, never left to a human to notice.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import run_cli  # noqa: E402

pytestmark = pytest.mark.e2e


def _help(verb: str) -> str:
    result = run_cli(verb, "--help")
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_merge_help_documents_path_range_and_the_colon_rule() -> None:
    text = _help("merge")
    assert "path:range" in text
    assert re.search(r"last colon", text)
    assert ":all" in text
    for mode in ("per-file", "preserve", "none"):
        assert mode in text


def test_split_help_documents_all_four_modes_and_the_comma_rule() -> None:
    text = _help("split")
    for flag in ("--every", "--ranges", "--each-page", "--at-bookmarks"):
        assert flag in text
    assert "comma" in text
    assert re.search(r"no top-level outline|exit 4", text)
    assert "each-page" in text and "{page}" in text
