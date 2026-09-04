"""PDF-33 — the display name is a CLASSIFIED population, not a swept one.

`PDF-31` moved the distribution, the repository and the planning tree to
`pdf-tooling` and deliberately left the rendered display name alone. `PDF-33`
moved the display name. Between them sit occurrences that must NEVER move --
the published console-script alias, the corpus/golden byte strings, landed
changelog history, recorded perf measurements -- and the difference between
this item and a `sed -i` is that the difference is MEASURED.

Three instruments live here, and each one exists because nothing in this
repository could observe its failure before:

1. `test_every_occurrence_is_classified` / `test_the_post_state_counts_hold`
   -- an ordered, first-match-wins classifier over the whole tree. Every
   occurrence gets exactly one role; the residual is asserted zero and a
   failure NAMES `file:line`. A classifier that stopped covering the tree is
   indistinguishable from one that passes, so the anti-lapse assertion is the
   point, not the per-class counts.

2. `test_the_og_card_agrees_with_its_generator` -- the Open Graph card is
   PIXELS, and no redeploy fixes a PNG. `d03bee3` changed the generator's
   footer string and never regenerated, so a stale card shipped through the
   `v0.2.0` release tag with nothing able to see it: `git grep -Iln "og-image"`
   returned five files, all documentation or configuration, none a test or a
   workflow. This is that missing instrument.

3. `test_the_broken_install_hint_names_the_real_distribution` -- `PDF-33`'s
   AC16 required each of five frozen distribution-identifier sites to have a
   control that can actually go red. Four did. `BROKEN_INSTALL_HINT` did not:
   its three apparent covers are all blind by construction (two assert against
   literals the tests themselves hard-code into their own fakes, and the third
   compares the constant to itself). Filed as PDF-33 F5; this is the arm.

WHY THIS FILE NEVER SPELLS THE NEEDLE
-------------------------------------
The classified population includes a class-H count of exactly 47 occurrences
under `tests/`. A test file that spelled the needle as a literal would inflate
the very operand it exists to measure, and would break the criterion it was
written to prove. So `NEEDLE` is assembled at runtime from two fragments. This
is not cleverness for its own sake: it is what makes `git diff -- tests/` over
this item's commit reviewable as "one new file, no `pdf-tool` + `kit` literal
anywhere in it".

`git grep` with no commit-ish reads the WORKING TREE, not history, so these
arms need no `require_full_history()` and run correctly on CI's shallow
checkout. That was confirmed against a real `--depth 1` clone, not assumed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import tomllib
from pathlib import Path
from typing import Callable, Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

#: Assembled, never written whole -- see the module docstring. Spelling this as
#: one literal would add an occurrence to class H and falsify its own count.
NEEDLE: Final[str] = "pdf-" + "toolkit"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )


def _occurrences() -> list[tuple[str, int, str]]:
    """Every occurrence in the tree as (path, line, full line text).

    `-Ion` and NOT `-Ioc`: `git grep -Ioc` silently drops `-o` and counts
    matching LINES, returning 99 where the true occurrence count is 112 -- a
    wrong answer with a success exit code, from an instrument that looks like
    it counts occurrences. The line text is re-read per (path, line) so the
    classifier can key on CONTENT rather than on line numbers, which drift.
    """
    proc = _git("grep", "-Ion", NEEDLE)
    if proc.returncode not in (0, 1):
        pytest.fail(f"git grep failed rc={proc.returncode}: {proc.stderr.strip()}")
    out: list[tuple[str, int, str]] = []
    text_cache: dict[str, list[str]] = {}
    for row in proc.stdout.splitlines():
        if not row:
            continue
        path, _, rest = row.partition(":")
        lineno_s, _, _match = rest.partition(":")
        lineno = int(lineno_s)
        if path not in text_cache:
            blob = _git("show", f"HEAD:{path}")
            source = blob.stdout if blob.returncode == 0 else ""
            if not source:
                source = (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace")
            text_cache[path] = source.splitlines()
        lines = text_cache[path]
        out.append((path, lineno, lines[lineno - 1] if 0 < lineno <= len(lines) else ""))
    return out


# --------------------------------------------------------------------------- #
# The rule set. ORDERED, FIRST-MATCH-WINS -- order is the mechanism, not a
# style choice. `README.md:27` matches both "is a console-script row" and "is
# brand text in README.md"; the alias rule MUST be consulted first, or that
# occurrence gets two roles and the reconciliation stops meaning anything.
# --------------------------------------------------------------------------- #

Rule = Callable[[str, int, str], bool]

#: Class D -- licence-adjacent (PDF-33 X-405). `THIRD_PARTY_LICENSES` is
#: reachable ONLY through `scripts/licenses.py`'s HEADER + `make licenses`.
LICENCE_ADJACENT: Final[frozenset[str]] = frozenset(
    {"Makefile", "NOTICE", "THIRD_PARTY_LICENSES", "scripts/licenses.py"}
)

#: Class C -- non-website brand text.
NON_WEBSITE_BRAND: Final[frozenset[str]] = frozenset(
    {"README.md", "CLAUDE.md", "src/pdf_toolkit/__init__.py"}
)


def _is_console_script_alias(path: str, _line: int, text: str) -> bool:
    """Class E. The alias is PUBLISHED and pinned; dropping it is a breaking
    change, not a rename (`tests/test_cli_spine.py`). Six occurrences."""
    if path == "pyproject.toml":
        return "pdf_toolkit.cli.main:main" in text
    if path == "src/pdf_toolkit/cli/main.py":
        return True
    if path == "src/pdf_toolkit/__init__.py":
        return "console scripts are" in text
    if path == "README.md":
        return "Console scripts" in text or "Both console scripts" in text
    return False


def _is_readme_contract_prose(path: str, _line: int, text: str) -> bool:
    """Class F. `README.md:29` -- "Why the distribution is not `<needle>`."
    Swept, it becomes a heading that contradicts the line four rows above it."""
    return path == "README.md" and "Why the distribution is not" in text


def _is_website_asset_path(path: str, _line: int, text: str) -> bool:
    """Class B. Path references, not brand text: they move if and only if the
    logo asset is renamed (PDF-33 D2)."""
    return path.startswith("website/") and "logo.svg" in text


RULES: Final[tuple[tuple[str, Rule], ...]] = (
    ("E", _is_console_script_alias),
    ("F", _is_readme_contract_prose),
    ("G", lambda p, _l, _t: p == "changelog.md"),
    ("H", lambda p, _l, _t: p.startswith("tests/")),
    ("I", lambda p, _l, _t: p.startswith("perf/")),
    ("D", lambda p, _l, _t: p in LICENCE_ADJACENT),
    ("B", _is_website_asset_path),
    ("A", lambda p, _l, _t: p.startswith("website/")),
    ("C", lambda p, _l, _t: p in NON_WEBSITE_BRAND),
)

#: The post-`PDF-33` expectation, per class and NEVER as a repo-wide total.
#: `PDF-31`'s AC6 said "the class is 0" of a raw grep total and was ruled
#: UNMEETABLE at execution: landed history, required supersession quotes and
#: frozen names all contain the string, so no total can reach zero.
#: `G` is a FLOOR because every future entry naming the old name adds to it.
EXPECTED_EXACT: Final[dict[str, int]] = {
    "A": 0,  # website brand text ......... all 17 moved
    "B": 0,  # website asset paths ........ all 3 moved with the rename
    "C": 0,  # non-website brand text ..... all 4 moved
    "D": 0,  # licence-adjacent ........... all 7 moved
    "E": 6,  # console-script alias ....... FROZEN, published
    "F": 1,  # README contract prose ...... FROZEN, rewriting it is nonsense
    "H": 47,  # tests/ ..................... FROZEN, not one byte
    "I": 12,  # perf/ ...................... FROZEN, recorded measurements
}
EXPECTED_FLOOR: Final[dict[str, int]] = {"G": 15}


def _classify() -> tuple[dict[str, list[str]], list[str]]:
    buckets: dict[str, list[str]] = {role: [] for role, _ in RULES}
    unclassified: list[str] = []
    for path, lineno, text in _occurrences():
        for role, rule in RULES:
            if rule(path, lineno, text):
                buckets[role].append(f"{path}:{lineno}")
                break
        else:
            unclassified.append(f"{path}:{lineno}  |  {text.strip()[:100]}")
    return buckets, unclassified


def test_every_occurrence_is_classified() -> None:
    """The anti-lapse assertion. An occurrence at a path no rule anticipates is
    a FAILURE NAMING file:line, never a silent skip -- a classifier that
    stopped covering the tree is a guard that guards nothing."""
    _buckets, unclassified = _classify()
    assert not unclassified, (
        f"{len(unclassified)} occurrence(s) of the display name matched no rule. "
        "Each is either a brand surface that drifted back (fix the surface) or a "
        "genuinely new role (add an ordered rule and state its disposition). "
        "Do NOT widen an existing rule to swallow it:\n  " + "\n  ".join(unclassified)
    )


def test_the_classification_reconciles_with_no_residual() -> None:
    """Sum of the per-class counts equals the live total. Without this, a rule
    that double-counted or a bucket that silently emptied would go unseen."""
    buckets, unclassified = _classify()
    total = len(_occurrences())
    classified = sum(len(v) for v in buckets.values())
    assert classified + len(unclassified) == total, (
        f"reconciliation residual: {classified} classified + {len(unclassified)} "
        f"unclassified != {total} live occurrences"
    )


@pytest.mark.parametrize("role", sorted(EXPECTED_EXACT))
def test_the_post_state_counts_hold(role: str) -> None:
    """Per class, never as a total. Reverting any single in-scope occurrence
    puts its class at >= 1 and fails HERE, naming the occurrence."""
    buckets, _ = _classify()
    found = buckets[role]
    assert len(found) == EXPECTED_EXACT[role], (
        f"class {role} is {len(found)}, expected exactly {EXPECTED_EXACT[role]}.\n"
        f"  found: {found}\n"
        "A class that GREW means a frozen occurrence moved or a brand surface "
        "drifted back. A class that SHRANK on E/F/H/I means something swept a "
        "population this item froze -- which is a breaking change for E."
    )


@pytest.mark.parametrize("role", sorted(EXPECTED_FLOOR))
def test_the_changelog_class_is_a_floor_not_a_ceiling(role: str) -> None:
    """Landed entries are never edited; a correction is a new entry with a new
    date. So this class can only grow, and pinning it exactly would redden on
    the next honest entry that names the old display name."""
    buckets, _ = _classify()
    assert len(buckets[role]) >= EXPECTED_FLOOR[role], (
        f"class {role} is {len(buckets[role])}, below the floor of "
        f"{EXPECTED_FLOOR[role]}. Landed changelog history was edited or deleted."
    )


# --------------------------------------------------------------------------- #
# The Open Graph card: generator <-> artifact agreement.
# --------------------------------------------------------------------------- #

OG_GENERATOR: Final[Path] = REPO_ROOT / "website" / "scripts" / "generate-og-image.py"
OG_ARTIFACT: Final[Path] = REPO_ROOT / "website" / "public" / "og-image.png"


def _load_og_generator():
    spec = importlib.util.spec_from_file_location("_og_generator", OG_GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_og_card_agrees_with_its_generator(tmp_path: Path) -> None:
    """Regenerate into a SCRATCH path and byte-compare. Never into the tracked
    artifact: a check that overwrites the thing it is verifying proves nothing.

    Determinism is a precondition, not an assumption -- `_load_font` picks a
    face by filesystem probe, so the bytes are host-dependent. Where no
    candidate resolves this SKIPS with the missing fonts named. It never
    passes on an unrenderable host.
    """
    pytest.importorskip("PIL", reason="Pillow is a declared runtime dependency")
    module = _load_og_generator()

    for group in ("FONT_CANDIDATES_BOLD", "FONT_CANDIDATES_REGULAR"):
        candidates = getattr(module, group)
        if not any(Path(c).exists() for c in candidates):
            pytest.skip(
                f"no {group} candidate resolves on this host, so the rendered bytes "
                f"would come from Pillow's bitmap fallback and could not be compared "
                f"against an artifact rendered with real fonts. Missing: {candidates}"
            )

    assert OG_ARTIFACT.exists(), f"the tracked OG card is missing at {OG_ARTIFACT}"
    scratch = tmp_path / "og-image.png"
    module.render(scratch)

    fresh = hashlib.sha256(scratch.read_bytes()).hexdigest()
    committed = hashlib.sha256(OG_ARTIFACT.read_bytes()).hexdigest()
    assert fresh == committed, (
        "the committed Open Graph card does not match what its generator now "
        f"produces (generator {fresh}, committed {committed}).\n"
        "The card is PIXELS -- no redeploy fixes a stale PNG, and a green source "
        "check says nothing about the deployed artifact. Re-run:\n"
        "    uv run python website/scripts/generate-og-image.py\n"
        "and commit the result. This exact divergence shipped through the v0.2.0 "
        "tag once already, because nothing in this repository could see it."
    )


# --------------------------------------------------------------------------- #
# PDF-33 AC16 / F5 -- the fifth frozen site's missing control.
# --------------------------------------------------------------------------- #


def test_the_broken_install_hint_names_the_real_distribution() -> None:
    """The hint tells a user with a broken install what to reinstall. If it
    names a distribution that does not exist, the advice is unfollowable.

    This reads TWO INDEPENDENT SOURCES -- the constant, and `pyproject.toml`'s
    `[project] name` -- deliberately. The pre-existing arm at
    `tests/unit/test_ports_registry.py` asserts `report.hint ==
    BROKEN_INSTALL_HINT`, which compares the constant to itself and therefore
    cannot fail when the constant is wrong. Two more arms
    (`tests/unit/test_raster.py`, `tests/unit/test_textract.py`) look like
    covers but assert against hint strings their own fakes hard-code, so they
    never read the product's value at all. Driving the plant reddened none of
    the three.
    """
    from pdf_toolkit.ports import BROKEN_INSTALL_HINT

    declared = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]["name"]
    assert BROKEN_INSTALL_HINT.split()[-1] == declared, (
        f"BROKEN_INSTALL_HINT is {BROKEN_INSTALL_HINT!r}, whose install target is "
        f"{BROKEN_INSTALL_HINT.split()[-1]!r}, but the distribution this project "
        f"actually publishes is {declared!r} (pyproject.toml [project] name). "
        "A user following this hint would be told to install something that is "
        "not on PyPI."
    )
