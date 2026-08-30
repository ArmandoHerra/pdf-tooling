"""D-12.7 -- the mechanized honesty gate.

`expertise/product.yaml` (2026-08-22): *mechanizing a documentation AC
collapses its variance.* `PLAN §12 R-02` binds the wording, not just the
code, so the wording gets a test.

Walks the source, docs and `--help` surfaces `compress`/`repair`/`linearize`
touch, and fails on any case-insensitive match of `FORBIDDEN_CLAIM_PATTERNS`
-- verbatim from the spec, never widened or narrowed here without a spec
amendment. `tests/` is excluded from the walk by construction: the patterns
are literals in THIS module, so a walk that included the tests directory
would fail on its own definition.

**One deliberate deviation from the spec's own file list, and it is
load-bearing.** D-12.7 names a single `cli/cmd_optimize.py`; the engineer
split that module into three (`cmd_compress.py`/`cmd_repair.py`/
`cmd_linearize.py`) to fix a real OR-3 registry collision (`cli/common.py`'s
`_CONSUMES_BY_MODULE` is keyed by module, and the codebase's own convention
-- and `tests/registry.py`'s own docstring -- is one command per
`cli/cmd_*.py` file). This module walks all three in the single file's place.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "pdf_toolkit"

#: D-12.7 -- verbatim from the spec.
FORBIDDEN_CLAIM_PATTERNS = [
    r"ghostscript[- ]?(level|grade|class|quality|equivalent|parity)",
    r"(as good as|on par with|comparable to|matches|rivals|beats|equal to)\s+ghostscript",
    r"ghostscript.{0,40}\b(parity|equivalent|same ratios?)\b",
    r"best[- ]in[- ]class",
    r"industry[- ]leading",
    r"state[- ]of[- ]the[- ]art",
    r"unbeatable",
    r"maximum compression",
    r"smallest possible",
    r"lossless image (compression|downsampling|recompression)",
]
_COMPILED = [re.compile(pattern, re.IGNORECASE) for pattern in FORBIDDEN_CLAIM_PATTERNS]

#: The source files this spec's mechanized gate walks, in place of D-12.7's
#: single `cli/cmd_optimize.py` -- see the module docstring.
_SOURCE_TARGETS = (
    SRC / "ops" / "optimize.py",
    SRC / "cli" / "cmd_compress.py",
    SRC / "cli" / "cmd_repair.py",
    SRC / "cli" / "cmd_linearize.py",
)

_DOC_TARGETS = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "changelog.md",
)


def _findings(text: str, *, label: str) -> list[str]:
    findings: list[str] = []
    for pattern in _COMPILED:
        match = pattern.search(text)
        if match:
            findings.append(f"{label}: {pattern.pattern!r} matched {match.group(0)!r}")
    return findings


def _help_texts() -> dict[str, str]:
    import sys

    tests_dir = Path(__file__).resolve().parent
    if str(tests_dir) not in sys.path:  # pragma: no cover - import plumbing
        sys.path.insert(0, str(tests_dir))
    from registry import run_cli

    texts: dict[str, str] = {}
    for verb in ("compress", "repair", "linearize"):
        result = run_cli(verb, "--help")
        assert result.returncode == 0, result.stderr
        texts[verb] = result.stdout
    return texts


# --------------------------------------------------------------------------- #
# AC8 -- the gate itself, over the real tree
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
def test_ac8_no_comparative_or_superlative_claim_anywhere() -> None:
    findings: list[str] = []
    for path in (*_SOURCE_TARGETS, *_DOC_TARGETS):
        findings.extend(_findings(path.read_text(encoding="utf-8"), label=str(path)))
    for verb, text in _help_texts().items():
        findings.extend(_findings(text, label=f"`{verb} --help` stdout"))
    assert findings == [], "PLAN §12 R-02 forbidden-claim matches:\n" + "\n".join(findings)


def test_ac8_negative_control_the_gate_can_fail() -> None:
    """AC8's own negative control (not a subprocess -- the pattern check
    itself, proven able to fail). The transcript against the REAL source
    tree (adding the literal claim to `cmd_compress.py`'s docstring,
    observing red, reverting, observing green) is recorded in this spec's
    Implementation Log."""
    poisoned = "This verb performs Ghostscript-level compression on every input."
    findings = _findings(poisoned, label="<synthetic>")
    assert findings, "the gate must be able to fail on its own target pattern"


def test_ac8_the_bare_word_ghostscript_is_not_forbidden() -> None:
    """D-12.7's own two deliberate design points, mechanized: a plain mention
    -- explaining the licence, never a comparison -- must NOT trip the gate."""
    honest = (
        "the conventional one-call compressor is AGPL-3.0+ and excluded by "
        "PLAN.md §7.2; pikepdf/libqpdf object streams replace it"
    )
    assert _findings(honest, label="<synthetic>") == []


# --------------------------------------------------------------------------- #
# AC9 -- positive help assertions
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
def test_ac9_compress_help_describes_the_image_pass_as_lossy() -> None:
    texts = _help_texts()
    assert "lossy" in texts["compress"].lower()


@pytest.mark.e2e
def test_ac9_lossless_help_states_the_text_identity_guarantee() -> None:
    texts = _help_texts()
    lowered = texts["compress"].lower()
    assert "byte-identical" in lowered
    assert "text" in lowered


@pytest.mark.e2e
def test_ac9_pages_help_states_the_set_semantics() -> None:
    texts = _help_texts()
    assert "set of pages" in texts["compress"].lower()


@pytest.mark.e2e
def test_ac9_the_page_box_dpi_limitation_is_in_help_and_readme() -> None:
    texts = _help_texts()
    compress_help = texts["compress"].lower()
    assert "page box" in compress_help
    assert "placement" in compress_help

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "page box" in readme or "page's own width" in readme
