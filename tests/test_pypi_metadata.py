"""PDF-124 -- the PyPI metadata declaration guard.

``[project.urls]`` and ``keywords`` in ``pyproject.toml`` are what the PyPI page
and PyPI search read. Before PDF-124 nothing in the repository read either, so a
URL could rot and a keyword could promise a verb the CLI does not have.

This module pins the DECLARATION (``pyproject.toml``) against the two things it
must agree with: the live CLI verb tree and the website's own config. The BUILT
artifacts are checked by ``scripts/assert_artifacts.py``. Fast unit tests only:
no subprocess, no build.

Literals carry their provenance: the verb table is the D2 table of PDF-124,
measured against ``pdftooling --help`` at ``e2a980e`` on 2026-10-08.
"""

from __future__ import annotations

import re
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Final

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import discover_verbs  # noqa: E402

PYPROJECT: Final = REPO_ROOT / "pyproject.toml"
ASTRO_CONFIG: Final = REPO_ROOT / "website" / "astro.config.mjs"
FOOTER: Final = REPO_ROOT / "website" / "src" / "components" / "Footer.astro"
README: Final = REPO_ROOT / "README.md"

EXPECTED_URL_LABELS: Final = ("Homepage", "Documentation", "Repository", "Changelog", "Issues")
ALLOWED_URL_HOSTS: Final = frozenset({"armandoherra.github.io", "github.com"})

GENERIC_KEYWORDS: Final = frozenset({"pdf", "cli"})

#: keyword -> the live leaf verb(s) that back it (PDF-124 D2).
KEYWORD_JOBS: Final[Mapping[str, tuple[str, ...]]] = {
    "merge": ("merge",),
    "split": ("split",),
    "ocr": ("ocr",),
    "rasterize": ("rasterize",),
    "compress": ("compress",),
    "encrypt": ("encrypt",),
    "decrypt": ("decrypt",),
    "watermark": ("watermark",),
    "stamp": ("stamp",),
    "rotate": ("rotate",),
    "linearize": ("linearize",),
    "repair": ("repair",),
    "metadata": ("meta get", "meta set"),
    "extract-text": ("text",),
    "extract-tables": ("tables",),
    "pdf-to-image": ("rasterize",),
    "image-to-pdf": ("compose",),
    "text-to-pdf": ("create",),
    "office-to-pdf": ("convert",),
    "docx-to-pdf": ("convert",),
}

STRIPPING_VOCABULARY: Final = re.compile(
    r"strip|scrub|saniti[sz]|anonymi[sz]|redact|clean|remov|wipe|privacy|sign"
)


def _project() -> dict[str, object]:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)["project"]


def _urls() -> dict[str, str]:
    return dict(_project()["urls"])


def _keywords() -> list[str]:
    return list(_project()["keywords"])


def _single(pattern: str, text: str, source: Path) -> str:
    matches = re.findall(pattern, text, re.M)
    assert len(matches) == 1, f"{source}: expected exactly one match of {pattern!r}, got {matches}"
    return matches[0]


def _site_url(astro_text: str) -> str:
    """``site + base + '/'`` as the website builds it, from the config text."""
    site = _single(r"^\s*site:\s*'([^']+)'", astro_text, ASTRO_CONFIG)
    base = _single(r"^\s*base:\s*'([^']+)'", astro_text, ASTRO_CONFIG)
    return site + base + "/"


def check_homepage(urls: Mapping[str, str], astro_text: str, readme_text: str) -> None:
    """Arm 2's assertions, over text, so a red control can feed a scratch copy."""
    site = _site_url(astro_text)
    assert urls["Homepage"] == site, f"Homepage {urls['Homepage']!r} != the built site {site!r}"
    readme_site = _single(r"\*\*Website:\*\*\s+(\S+)", readme_text, README)
    assert readme_site == site, f"README Website line {readme_site!r} != the built site {site!r}"


def test_the_url_labels_are_exactly_the_five() -> None:
    urls = _urls()
    assert tuple(urls) == EXPECTED_URL_LABELS, tuple(urls)
    for label, value in urls.items():
        assert value.startswith("https://"), f"{label}: {value!r} is not https"
        host = value.removeprefix("https://").split("/", 1)[0]
        assert host in ALLOWED_URL_HOSTS, (
            f"{label}: host {host!r} not in {sorted(ALLOWED_URL_HOSTS)}"
        )


def test_homepage_is_the_site_the_website_builds() -> None:
    check_homepage(
        _urls(),
        ASTRO_CONFIG.read_text(encoding="utf-8"),
        README.read_text(encoding="utf-8"),
    )


def test_homepage_check_goes_red_when_the_site_base_moves() -> None:
    """Non-vacuity for arm 2 (RC5): a scratch config whose ``base`` moved fails."""
    text = ASTRO_CONFIG.read_text(encoding="utf-8")
    moved = text.replace("base: '/pdf-tooling'", "base: '/pdftooling'")
    assert moved != text
    try:
        check_homepage(_urls(), moved, README.read_text(encoding="utf-8"))
    except AssertionError:
        return
    raise AssertionError("check_homepage accepted a site whose base no longer matches Homepage")


def test_documentation_is_what_the_site_calls_documentation() -> None:
    docs_url = _single(
        r"^\s*const docsUrl\s*=\s*'([^']+)'", FOOTER.read_text(encoding="utf-8"), FOOTER
    )
    assert _urls()["Documentation"] == docs_url


def test_issues_and_changelog_hang_off_the_repository() -> None:
    urls = _urls()
    assert urls["Issues"] == urls["Repository"] + "/issues"
    assert urls["Changelog"] == urls["Repository"] + "/blob/main/changelog.md"
    assert (REPO_ROOT / "changelog.md").is_file()
    assert urls["Repository"] == "https://github.com/ArmandoHerra/" + str(_project()["name"])


def test_every_keyword_names_a_job_the_cli_does() -> None:
    keywords = _keywords()
    assert len(keywords) == len(set(keywords)), f"duplicate keywords in {keywords}"
    declared = GENERIC_KEYWORDS | set(KEYWORD_JOBS)
    assert set(keywords) == declared, (
        f"keywords without a job row: {sorted(set(keywords) - declared)}; "
        f"job rows without a keyword: {sorted(declared - set(keywords))}"
    )
    live = {v.name for v in discover_verbs() if not v.is_group}
    dead = [
        f"{kw} -> {verb}"
        for kw, verbs in KEYWORD_JOBS.items()
        for verb in verbs
        if verb not in live
    ]
    assert not dead, f"keyword -> verb is not a live leaf verb: {dead}"
    assert len(KEYWORD_JOBS) >= 16
    assert len(live) >= 20


def test_no_keyword_teaches_metadata_stripping() -> None:
    assert [k for k in _keywords() if STRIPPING_VOCABULARY.search(k)] == []


def test_the_stripping_pattern_is_not_vacuous() -> None:
    for bad in (
        "strip-metadata",
        "remove-metadata",
        "sanitize",
        "scrub",
        "anonymize",
        "redact",
        "privacy",
        "sign",
    ):
        assert STRIPPING_VOCABULARY.search(bad), bad
    for good in GENERIC_KEYWORDS | set(KEYWORD_JOBS):
        assert not STRIPPING_VOCABULARY.search(good), good
