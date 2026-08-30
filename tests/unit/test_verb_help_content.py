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


# --------------------------------------------------------------------------- #
# PDF-10 -- `compose --help` / `create --help` are this spec's documentation
# surface (Scope > Out: README.md and CLAUDE.md are untouched, HC-5). Every
# documentation rule the spec states is a grep over captured `--help` output.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", ["compose", "create"])
def test_ac1_both_new_verbs_name_the_port_they_depend_on(verb: str) -> None:
    assert "ComposeEngine" in _help(verb)


def test_ac1_compose_help_documents_its_four_flags_and_the_lossless_contract() -> None:
    text = _help("compose")
    for flag in ("--page-size", "--fit", "--margin", "--dpi"):
        assert flag in text, flag
    for value in ("a4", "letter", "from-image", "contain", "cover", "stretch"):
        assert value in text, value
    # The guarantee is described as a capability, in the terms a user can check.
    assert re.search(r"byte-for-byte|byte for byte", text)
    assert "re-encode" in text
    assert "progressive" in text.lower()
    # Ordering and the no-globbing rule are documented, not folklore.
    assert "order the operands appear" in text
    assert "shell" in text


def test_ac1_create_help_documents_its_five_flags_and_the_stdin_contract() -> None:
    text = _help("create")
    for flag in ("--page-size", "--font", "--size", "--margin", "--title"):
        assert flag in text, flag
    assert "Helvetica" in text
    assert "standard input" in text
    assert "exit 4" in text
    assert "exit 2" in text
    assert "form feed" in text


def test_the_two_margin_defaults_are_documented_as_deliberately_different() -> None:
    assert "0" in _help("compose")
    assert "54pt" in _help("create")


@pytest.mark.parametrize("verb", ["compose", "create"])
def test_ac30_no_help_text_names_a_forbidden_tool(verb: str) -> None:
    """The prohibition and the advertisement look identical to a grep, and this
    spec's headline feature is reproducing a forbidden tool's differentiator.
    So the capability is described and the tool is never named -- not in help
    text, not in a docstring, not in an error message."""
    from test_cli_spine import FORBIDDEN_NAMES

    lowered = _help(verb).lower()
    assert [name for name in FORBIDDEN_NAMES if name in lowered] == []
