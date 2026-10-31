"""PDF-171 -- the website tagline and the Open Graph card state a true licence line.

The retired slogan said there was no copyleft underneath while the same site
discloses that `pikepdf` is MPL-2.0, copyleft file by file. The replacement is
derived from repo facts: the product licence and the one MPL-2.0 package in the
generated inventory. Source tier only: no Node, no `dist/`, no skip path.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import tomllib
from pathlib import Path
from typing import Any, Final

import pytest
from PIL import Image, ImageDraw

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SITE: Final[Path] = REPO_ROOT / "website"

# D1: one string per locale, reused verbatim on every surface.
TAGLINE_EN: Final[str] = (
    "Every common PDF chore. One safe CLI. Apache-2.0. MPL-2.0 dependency disclosed."
)
TAGLINE_ES: Final[str] = (
    "Todas las tareas comunes de PDF. Una sola CLI segura. Apache-2.0. "
    "Dependencia MPL-2.0 declarada."
)
TITLE_PREFIX: Final[str] = "pdf-tooling: "
PACKAGE_DESCRIPTION_TAIL: Final[str] = "one safe CLI, Apache-2.0, MPL-2.0 dependency disclosed"

# Re-pin only together with a re-review of the card-text arm.
OG_CARD_SHA256: Final[str] = "be089c199406d787d2d90b846fcbfcfe4a90214bd96aa420b01f964ac43e2d8f"

RETIRED: Final[re.Pattern[str]] = re.compile(r"(?i)\b(no|sin)\s+copyleft\b")
CLAIM: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(stars?|downloads?|users?|usuarios|estrellas|descargas|fastest|faster|best|mejor"
    r"|leading|l[ií]der|#1|\d+\s*(%|x\b|k\b|\+))"
)
NOTICE_PIKEPDF: Final[re.Pattern[str]] = re.compile(r"(?m)^\s*pikepdf\s+MPL-2\.0\b")

HERO: Final[Path] = SITE / "src" / "components" / "Hero.astro"
LAYOUT: Final[Path] = SITE / "src" / "layouts" / "Layout.astro"
LICENSE_SUMMARY: Final[Path] = SITE / "src" / "components" / "LicenseSummary.astro"
PACKAGE_JSON: Final[Path] = SITE / "package.json"
OG_PNG: Final[Path] = SITE / "public" / "og-image.png"
OG_GENERATOR: Final[Path] = SITE / "scripts" / "generate-og-image.py"
INVENTORY: Final[Path] = SITE / "src" / "data" / "licenses.json"

BASE_TAGLINE_EN: Final[str] = "Every common PDF chore. One safe CLI. No copyleft underneath."
BASE_TAGLINE_ES: Final[str] = (
    "Todas las tareas comunes de PDF. Una sola CLI segura. Sin copyleft debajo."
)
BASE_DESCRIPTION: Final[str] = (
    "Project website for pdf-tooling — every common PDF chore, one safe CLI, no copyleft underneath"
)


def _table_values(source: Path, key: str) -> list[str]:
    pattern = re.compile(rf"^\s*{re.escape(key)}:\s*'([^']*)',?\s*$")
    found: list[str] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            found.append(match.group(1))
    assert len(found) == 2, f"{source.name} `{key}` must have exactly two values, got {found}"
    return found


def _package_description() -> str:
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    return str(data["description"])


def _load_generator() -> Any:
    spec = importlib.util.spec_from_file_location("_pdf171_og_generator", OG_GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record_card(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    generator = _load_generator()
    recorded: list[str] = []
    original = ImageDraw.ImageDraw.text

    def wrapped(self: ImageDraw.ImageDraw, xy: Any, text: Any, *a: Any, **k: Any) -> Any:
        recorded.append(text)
        return original(self, xy, text, *a, **k)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", wrapped)
    generator.render(tmp_path / "og.png")
    return recorded


def _retired_hits(files: list[Path]) -> list[str]:
    hits: list[str] = []
    for item in files:
        if RETIRED.search(item.read_text(encoding="utf-8")):
            hits.append(str(item.relative_to(REPO_ROOT)))
    return hits


def _licence_violations(
    tagline: str, project_licence: str, inventory_rows: list[dict[str, str]]
) -> list[str]:
    problems: list[str] = []
    if "Apache-2.0" not in tagline or project_licence != "Apache-2.0":
        problems.append("the tagline does not state the project licence")
    if "MPL-2.0" not in tagline:
        problems.append("the tagline does not name MPL-2.0")
    mpl_names = [r["Name"] for r in inventory_rows if r["License"] == "MPL-2.0"]
    if mpl_names != ["pikepdf"]:
        problems.append(f"MPL-2.0 rows are {mpl_names}, not ['pikepdf']")
    return problems


def _claim_violations(strings: list[str]) -> list[str]:
    problems: list[str] = []
    for item in strings:
        stripped = item.replace("Apache-2.0", "").replace("MPL-2.0", "")
        if re.search(r"\d", stripped) or CLAIM.search(stripped):
            problems.append(item)
    return problems


def test_the_tagline_is_one_string_per_locale() -> None:
    hero = _table_values(HERO, "tagline")
    og_desc = _table_values(LAYOUT, "ogDescription")
    titles = _table_values(LAYOUT, "title")
    taglines = [TAGLINE_EN, TAGLINE_ES]
    assert hero == taglines
    assert og_desc == taglines
    assert titles == [TITLE_PREFIX + TAGLINE_EN, TITLE_PREFIX + TAGLINE_ES]
    assert _package_description().endswith(PACKAGE_DESCRIPTION_TAIL)


def test_no_website_surface_carries_the_retired_claim() -> None:
    files: list[Path] = []
    files += sorted((SITE / "src").rglob("*.astro"))
    files += sorted((SITE / "src").rglob("*.ts"))
    files += sorted((SITE / "scripts").glob("*.py"))
    files += [PACKAGE_JSON, SITE / "README.md", REPO_ROOT / "README.md"]
    files += [REPO_ROOT / "docs" / "social" / "generate-social-preview.py"]
    assert _retired_hits(files) == []


def test_the_retired_claim_arm_can_fail() -> None:
    assert RETIRED.search(BASE_TAGLINE_EN)
    assert RETIRED.search(BASE_TAGLINE_ES)
    assert RETIRED.search(BASE_DESCRIPTION)
    generator = _load_generator()
    card_tail = getattr(generator, "CARD_TAGLINE_LINES", ("",))[-1]
    for fresh in (TAGLINE_EN, TAGLINE_ES, card_tail):
        assert not RETIRED.search(fresh)


def test_the_licence_ids_in_the_tagline_are_the_repos_own() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_licence = pyproject["project"]["license"]
    rows = json.loads(INVENTORY.read_text(encoding="utf-8"))
    licence_file = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in licence_file
    assert "Version 2.0" in licence_file
    for tagline in (TAGLINE_EN, TAGLINE_ES):
        assert _licence_violations(tagline, project_licence, rows) == []
    notice = (REPO_ROOT / "NOTICE").read_text(encoding="utf-8")
    assert NOTICE_PIKEPDF.search(notice)
    assert "{pikepdf.License}" in LICENSE_SUMMARY.read_text(encoding="utf-8")


def test_the_licence_arm_can_fail() -> None:
    rows = [{"License": "MPL-2.0", "Name": "pikepdf"}]
    bad_tagline = "Every common PDF chore. One safe CLI. MIT. MPL-2.0 dependency disclosed."
    assert _licence_violations(bad_tagline, "Apache-2.0", rows)
    two = [*rows, {"License": "MPL-2.0", "Name": "zz-planted"}]
    assert _licence_violations(TAGLINE_EN, "Apache-2.0", two)
    real = (REPO_ROOT / "NOTICE").read_text(encoding="utf-8")
    assert NOTICE_PIKEPDF.search(real)
    assert not NOTICE_PIKEPDF.search("  pikepdf               MIT")


def test_the_og_card_draws_exactly_the_en_tagline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generator = _load_generator()
    name = getattr(generator, "CARD_NAME", None)
    lines = getattr(generator, "CARD_TAGLINE_LINES", None)
    footer = getattr(generator, "CARD_FOOTER", None)
    assert name is not None and lines is not None and footer is not None, (
        "the generator must expose CARD_NAME, CARD_TAGLINE_LINES and CARD_FOOTER"
    )
    drawn = _record_card(tmp_path, monkeypatch)
    assert drawn == [name, *lines, footer]
    joined = " ".join(lines)
    hero_en = _table_values(HERO, "tagline")[0]
    assert joined == TAGLINE_EN
    assert joined == hero_en


def test_no_tagline_surface_states_a_figure_or_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    surfaces = [
        *_table_values(HERO, "tagline"),
        *_table_values(LAYOUT, "title"),
        *_table_values(LAYOUT, "ogDescription"),
        _package_description(),
    ]
    generator = _load_generator()
    assert hasattr(generator, "CARD_TAGLINE_LINES"), "the generator must name its drawn lines"
    surfaces += _record_card(tmp_path, monkeypatch)
    assert _claim_violations(surfaces) == []


def test_the_claim_arm_can_fail() -> None:
    assert _claim_violations(["★ 42 stars"])
    assert _claim_violations(["10x faster"])
    assert _claim_violations(["Más de 100 usuarios."])
    assert _claim_violations([TAGLINE_EN, TAGLINE_ES]) == []


def test_the_og_card_artifact_is_pinned() -> None:
    with Image.open(OG_PNG) as image:
        shape = (image.format, image.size, image.mode)
    assert shape == ("PNG", (1200, 630), "RGB")
    digest = hashlib.sha256(OG_PNG.read_bytes()).hexdigest()
    assert digest == OG_CARD_SHA256, (
        "website/public/og-image.png changed: re-render with "
        "`uv run python website/scripts/generate-og-image.py` and re-pin OG_CARD_SHA256 "
        "only together with a re-review of the card-text arm"
    )
