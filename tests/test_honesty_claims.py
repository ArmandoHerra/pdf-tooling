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


# --------------------------------------------------------------------------- #
# PDF-24 / B-116 / `0d10c01634` -- the write-flag refusal, DISCLOSED.
#
# Appended at this spec's own anchor. The `ac8`/`ac9` sections above belong to
# PDF-12 and are not touched (X-15: append, never rewrite).
#
# Before this section, `version`, `doctor` and `info` advertised seven
# write-related flags in their rendered help, refused four of them at runtime
# and disclosed NOTHING, while `permissions` and `meta get` disclosed plainly.
# The disclosure fix uses the idiom `test_ac9_*` above already establishes --
# pin a specific sentence into a specific verb's `--help` -- and UPGRADES it in
# one respect: **the expected flag list is COMPUTED, not typed.**
#
# A hand-typed disclosure sentence is a hand-maintained list of refused flags,
# which is the same defect shape as the two hand-typed forbidden-name lists
# `PDF-24` is de-duplicating in `tests/test_cli_spine.py`. The derivation is
# also what caught the thing this item most easily gets wrong: it reads as
# "make three verbs match two", and it is actually "make five verbs match a
# derived list that has ITSELF changed" -- the two verbs that already disclosed
# named FOUR flags, and the refused set is SIX after B-115.
# --------------------------------------------------------------------------- #

import sys as _sys  # noqa: E402

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in _sys.path:  # pragma: no cover - import plumbing
    _sys.path.insert(0, str(_TESTS_DIR))

from pdf_toolkit.cli.common import (  # noqa: E402
    OUTPUT_FLAGS,
    SAFETY_FLAGS,
    UNGOVERNED_FLAGS,
)
from registry import discover_verbs, run_cli  # noqa: E402

#: The marker that opens the disclosure sentence on every verb that carries one.
#: In the voice `meta get` already used; `permissions` was migrated onto it so
#: the five sentences are one sentence, not five paraphrases.
DISCLOSURE_MARKER = "REPORTS, NEVER WRITES:"

#: The short spellings, per long spelling, that the sentence must also name --
#: because a user pastes `-y`, not `--yes`. Derived from the block's own
#: declarations would be circular here (the test would then assert whatever the
#: block says); these three are the ones the two ORIGINAL disclosures named, and
#: they are what makes the sentence useful rather than merely correct.
_SHORT_SPELLINGS = {"--output": "-O", "--force": "-f", "--yes": "-y"}


def _dewrapped(text: str) -> str:
    """Undo Click's help wrapping, which breaks at hyphens.

    `--in-place` is rendered as `--in-` + newline + `place` whenever the
    paragraph happens to wrap there, and Click caps help bodies at ~78 columns
    regardless of `COLUMNS` -- verified at `8fd2146`, where `COLUMNS=200` and
    `COLUMNS=120` produce byte-identical bodies. A test that searched the raw
    text for `--in-place` would therefore pass or fail on sentence length.
    """
    return " ".join(re.sub(r"-\n\s*", "-", text).split())


def _disclosure_sentence(help_text: str) -> str | None:
    """The disclosure sentence alone, or `None` when the verb carries none.

    Scoped to the SENTENCE and never to the whole body: the Options section
    names every global flag on every verb, so a body-wide search would report
    every verb as disclosing everything.
    """
    body = _dewrapped(help_text)
    start = body.find(DISCLOSURE_MARKER)
    if start == -1:
        return None
    end = body.find(".", start)
    return body[start : end + 1] if end != -1 else body[start:]


def _refused_spellings(consumes: tuple[str, ...]) -> set[str]:
    """`(OUTPUT_FLAGS | SAFETY_FLAGS) - consumes`, plus the short spellings.

    COMPUTED. Six long names / nine spellings for a `consumes == ()` verb after
    B-115 -- which is why the two verbs that already disclosed, naming four,
    had to be updated too.
    """
    refused = [flag for flag in (*OUTPUT_FLAGS, *SAFETY_FLAGS) if flag not in consumes]
    spellings = set(refused)
    spellings.update(_SHORT_SPELLINGS[flag] for flag in refused if flag in _SHORT_SPELLINGS)
    return spellings


def _named_spellings(sentence: str) -> set[str]:
    """Every flag spelling the sentence names, long and short."""
    return set(re.findall(r"(?<![\w-])(--?[A-Za-z][\w-]*)", sentence))


def _non_consuming() -> tuple[str, ...]:
    return tuple(sorted(verb.name for verb in discover_verbs() if verb.consumes == ()))


@pytest.mark.e2e
def test_ac12_every_verb_that_writes_nothing_discloses_the_refusal() -> None:
    """AC12 / B-116. The population is derived from the live registry, so a
    sixth `consumes == ()` verb joins with zero author action."""
    population = _non_consuming()
    assert population == ("doctor", "info", "meta get", "permissions", "version")
    missing = []
    for verb in population:
        result = run_cli(verb, "--help")
        assert result.returncode == 0, result.stderr
        if _disclosure_sentence(result.stdout) is None:
            missing.append(verb)
    assert missing == [], f"verbs that write nothing and disclose nothing: {missing}"


@pytest.mark.e2e
def test_ac13_the_disclosure_names_exactly_the_derived_refused_set() -> None:
    """AC13 -- the pinned claim is DERIVED, not a literal sentence typed here.

    Equality, not containment. A disclosure that OVER-claims is as false as one
    that under-claims, and over-claiming is the shape a copy-paste between verbs
    produces.
    """
    verbs = {verb.name: verb for verb in discover_verbs()}
    for name in _non_consuming():
        result = run_cli(name, "--help")
        assert result.returncode == 0, result.stderr
        sentence = _disclosure_sentence(result.stdout)
        assert sentence is not None, name
        expected = _refused_spellings(verbs[name].consumes)
        assert len(expected) == 9, f"{name}: expected nine spellings, got {sorted(expected)}"
        assert _named_spellings(sentence) == expected, (
            f"{name} discloses {sorted(_named_spellings(sentence))}, "
            f"derived set is {sorted(expected)}\nsentence: {sentence}"
        )
        # The full long-spelling half restated against the rendered BODY, which
        # is AC13's own wording.
        body = _dewrapped(result.stdout)
        for flag in (*OUTPUT_FLAGS, *SAFETY_FLAGS):
            assert flag in body, f"{name} --help does not name {flag}"


@pytest.mark.e2e
def test_ac14_no_verb_names_a_flag_it_consumes_as_refused() -> None:
    """AC14 -- the NEGATIVE half, over EVERY leaf verb rather than only the five.

    *Observed red by:* copying `version`'s disclosure verbatim into `merge`'s
    docstring -- `merge` consumes `--output`, so the sentence would claim a
    refusal the verb does not perform.
    """
    offenders = []
    for verb in discover_verbs():
        result = run_cli(verb.name, "--help")
        assert result.returncode == 0, result.stderr
        sentence = _disclosure_sentence(result.stdout)
        if sentence is None:
            continue
        named = _named_spellings(sentence)
        over_claimed = {
            flag
            for flag in verb.consumes
            if flag in named or _SHORT_SPELLINGS.get(flag, "\0") in named
        }
        if over_claimed:
            offenders.append(f"{verb.name}: claims to refuse {sorted(over_claimed)}, consumes them")
        derived = _refused_spellings(verb.consumes)
        if named != derived:
            offenders.append(f"{verb.name}: discloses {sorted(named)}, derived {sorted(derived)}")
    assert offenders == [], "\n".join(offenders)


@pytest.mark.e2e
def test_ac15_no_backup_is_never_named_in_a_disclosure_sentence() -> None:
    """AC15. `--no-backup` IS refused on these five verbs -- but for the
    UNIVERSAL `--no-backup requires --in-place` reason that applies identically
    to all twenty-six. Naming it in a five-verb *this verb writes nothing*
    sentence would assert a verb-specific fact that is not one.

    It sits in `UNGOVERNED_FLAGS` with exactly that reason recorded as data,
    which is what makes this assertion a consequence of the partition rather
    than a separate rule someone has to remember.
    """
    assert "--no-backup" in UNGOVERNED_FLAGS
    assert "--in-place" in UNGOVERNED_FLAGS["--no-backup"]
    for verb in discover_verbs():
        result = run_cli(verb.name, "--help")
        sentence = _disclosure_sentence(result.stdout)
        if sentence is None:
            continue
        assert "--no-backup" not in sentence, f"{verb.name}: {sentence}"


def test_the_disclosure_helpers_can_fail() -> None:
    """The non-vacuity proof for the three helpers above, on synthetic input.

    Without it, a `_disclosure_sentence` that always returned `None` would make
    AC13, AC14 and AC15 pass by skipping every verb -- the exact vacuity this
    cycle exists to end.
    """
    assert _disclosure_sentence("no marker here") is None
    wrapped = (
        "  REPORTS, NEVER WRITES: this verb writes no files, so -O/--output, --in-\n"
        "  place each exit 2.\n\n  Next paragraph."
    )
    sentence = _disclosure_sentence(wrapped)
    assert sentence is not None
    assert "--in-place" in sentence, sentence
    assert "Next paragraph" not in sentence
    assert _named_spellings(sentence) == {"-O", "--output", "--in-place"}
    assert _refused_spellings(()) == {
        "-O",
        "--output",
        "--out-dir",
        "--name",
        "--in-place",
        "-f",
        "--force",
        "-y",
        "--yes",
    }
    assert _refused_spellings(("--output",)) == {
        "--out-dir",
        "--name",
        "--in-place",
        "-f",
        "--force",
        "-y",
        "--yes",
    }
