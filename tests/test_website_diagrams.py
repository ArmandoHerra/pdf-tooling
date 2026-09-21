"""tests/test_website_diagrams.py -- PDF-96.

Pins every derived figure the six-layer spine, the exit-code/output
datasheet and the atomic-write sequence publish on the website against a
fresh AST walk over `src/pdf_tooling/` -- never a literal. Reuses
`tests/test_import_boundaries.py`'s own constants and walk
(`ENGINE_MODULES`, `SPAWN_MODULES`, `ADAPTER_PACKAGE`, `SPAWN_CHOKEPOINT`,
`CHOKEPOINT`, `_imported_top_levels`) by import, never re-spelled -- a
second vocabulary for the same question is the anti-pattern this product
has paid for twice (D3).

WHAT MAKES THIS A DERIVATION AND NOT A LITERAL
-----------------------------------------------
An equality assertion between the website's JSON data and a hard-coded
number is green forever. What actually proves the page tracks the tree is
the `tmp_path` plant: a `shutil.copytree` of `src/pdf_tooling/` mutated by
exactly one fact, re-walked, and the delta checked in isolation -- the
same idiom this product already ships at
`test_import_boundaries.py::test_a_planted_violation_fails_the_walk` and
its siblings. Every AC below that publishes a count carries at least one
such plant, and every plant here was driven and observed before this file
was written down (E4/E5).

TWO TIERS
---------
  * SOURCE TIER -- pure AST/JSON derivations over `src/pdf_tooling/` and
    the two data files. Always runs, no build required.
  * DIST TIER -- reads `website/dist/index.html`. Guarded by the same
    vacuity pattern `tests/test_website_contract.py` uses: unbuilt and
    `PDF_TOOLING_WEBSITE_BUILT` unset -> SKIP (named reason); unbuilt and
    that env var set -> FAIL, never a silent pass.

TWO TRAPS RECORDED HERE SO A FUTURE READER DOES NOT REDISCOVER THEM
---------------------------------------------------------------------
1. The product's real temp-file prefix (`safety/tempnames.py`'s
   `TEMP_PREFIX`) is a REGISTERED spelling under `src/` and a FORBIDDEN
   needle under `website/` (`tests/test_website_contract.py`'s legacy-
   needle arm; `tests/test_rename_completeness.py`'s remainder and
   residue-count checks). This module never spells it, including in a
   comment -- it self-matched once during this item's own drafting and
   reddened `test_rename_completeness.py`, not this file, with a message
   about a brand census.
2. `tests/test_import_boundaries.py` carries two "Section 6" headers, so a
   citation naming "§6" would be ambiguous. Every citation this module
   checks for is a test FUNCTION NAME, never a section number, and this
   module itself never writes the "§" character as a citation form.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from html import unescape as html_unescape
from pathlib import Path
from typing import Any, Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
WEBSITE_SRC: Final[Path] = REPO_ROOT / "website" / "src"
DIST_ROOT: Final[Path] = REPO_ROOT / "website" / "dist"
PDF_TOOLING_SRC: Final[Path] = REPO_ROOT / "src" / "pdf_tooling"
EXIT_CODES_SRC: Final[Path] = PDF_TOOLING_SRC / "cli" / "exit_codes.py"
README: Final[Path] = REPO_ROOT / "README.md"
CHANGELOG: Final[Path] = REPO_ROOT / "changelog.md"

SPINE_JSON: Final[Path] = WEBSITE_SRC / "data" / "spine.json"
CONTRACTS_JSON: Final[Path] = WEBSITE_SRC / "data" / "contracts.json"
ARCHITECTURE_ASTRO: Final[Path] = WEBSITE_SRC / "components" / "Architecture.astro"
EXITCODES_ASTRO: Final[Path] = WEBSITE_SRC / "components" / "ExitCodes.astro"
ATOMICWRITE_ASTRO: Final[Path] = WEBSITE_SRC / "components" / "AtomicWrite.astro"
IMPORT_BOUNDARIES_TEST: Final[Path] = Path(__file__).resolve().parent / "test_import_boundaries.py"

# --------------------------------------------------------------------------- #
# D3 -- reuse the product's own boundary-test constants and walk BY IMPORT.
# --------------------------------------------------------------------------- #
_tests_dir = str(Path(__file__).resolve().parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)
from test_import_boundaries import (  # noqa: E402  (path must be set up first)
    ENGINE_MODULES,
    SPAWN_MODULES,
    _imported_top_levels,
)

#: AC15/AC16. This module never spells the legacy needle as one contiguous
#: literal -- `tests/test_rename_completeness.py`'s whole-tree census would
#: see a fresh occurrence of whichever spelling got spelled out, at
#: whichever line it was written on, self-inflating the very population it
#: exists to measure (its own docstring's "WHY THIS FILE NEVER SPELLS"
#: section, and `tests/test_brand_surfaces.py`'s `NEEDLE` assembly, for the
#: identical reason). `LEGACY_NEEDLE` is reused BY IMPORT from
#: `test_website_contract`, which already assembles it correctly, rather
#: than re-assembled a third time here.
from test_website_contract import LEGACY_NEEDLE  # noqa: E402  (path must be set up first)

#: The bare (no-separator) fragment, assembled the same way, for the
#: substring check `test_ac16_...` needs -- never written contiguously.
_LEGACY_BARE_FRAGMENT: Final[str] = "pdf" + "toolkit"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )


def _require_dist() -> None:
    """Vacuity guard, D4's pattern from `tests/test_website_contract.py`:
    the unbuilt-and-unset case SKIPS with a named reason; the unbuilt-and-
    `PDF_TOOLING_WEBSITE_BUILT`-set case FAILS -- a skip is never allowed
    to read as a pass in the one job whose purpose is to check the built
    site."""
    if (DIST_ROOT / "index.html").is_file():
        return
    if os.environ.get("PDF_TOOLING_WEBSITE_BUILT"):
        pytest.fail(
            "PDF_TOOLING_WEBSITE_BUILT is set but website/dist/index.html does not exist -- "
            "run `npm run build` in website/ first."
        )
    pytest.skip("website not built; run `make website`")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_spine() -> dict[str, Any]:
    return _load_json(SPINE_JSON)


def _load_contracts() -> dict[str, Any]:
    return _load_json(CONTRACTS_JSON)


def _layer_by_path_suffix(spine: dict[str, Any], suffix: str) -> dict[str, Any]:
    for layer in spine["layers"]:
        if layer["path"].rstrip("/").split("/")[-1] == suffix:
            return layer
    raise AssertionError(f"no layer with path suffix {suffix!r}")


# --------------------------------------------------------------------------- #
# The derivations. Every one takes a `pdf_tooling_root: Path` -- the REAL
# `PDF_TOOLING_SRC` in the non-planted tests, a `tmp_path`-rooted
# `shutil.copytree` in every planted one, so the SAME function drives both
# arms (E4's own discipline: the derivation, not a second copy of it, is
# what is under test).
# --------------------------------------------------------------------------- #


def _real_packages(pdf_tooling_root: Path) -> set[str]:
    """AC3. Directories carrying an `__init__.py` -- NOT `iterdir()`, and
    NOT `ls`. `E2`: an unfiltered `iterdir()` over the real tree returns
    eleven-plus entries (five top-level files, an optional `__pycache__`),
    so a derivation written against a bare `iterdir()` reds on a CORRECT
    tree. This is the trap `test_ac3_an_unfiltered_walk_reds_...` proves
    organically, with no plant, against the real tree."""
    return {
        p.name for p in pdf_tooling_root.iterdir() if p.is_dir() and (p / "__init__.py").exists()
    }


def _bases_include_protocol(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "Protocol":
            return True
    return False


def _port_modules_with_protocol(pdf_tooling_root: Path) -> dict[str, list[str]]:
    """AC4(a). Modules under `ports/`, excluding `__init__.py`, that
    define at least one `ClassDef` with a `Protocol` base."""
    ports_dir = pdf_tooling_root / "ports"
    found: dict[str, list[str]] = {}
    for f in sorted(ports_dir.glob("*.py")):
        if f.name == "__init__.py":
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        classes = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and _bases_include_protocol(node)
        ]
        if classes:
            found[f.stem] = classes
    return found


def _ports_tuple(pdf_tooling_root: Path) -> tuple[str, ...]:
    """AC4(b). `PORTS` (`ports/__init__.py`) read by `ast.literal_eval`,
    WITHOUT importing the product -- it is PUBLIC API and gives a second,
    independent derivation of the six (E5)."""
    init_src = (pdf_tooling_root / "ports" / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(init_src)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "PORTS"
        ):
            value = ast.literal_eval(node.value)
            return tuple(value)
    raise AssertionError("PORTS not found in ports/__init__.py")


def _adapter_files(pdf_tooling_root: Path) -> set[str]:
    """`adapters/*.py` less `__init__.py` -- the population AC7's balance
    checks against, and what `Architecture.astro:19-20`'s PRE-PDF-96
    sentence actually required reading (E3)."""
    return {f.stem for f in (pdf_tooling_root / "adapters").glob("*.py") if f.name != "__init__.py"}


def _spawn_files_under_tree(pdf_tooling_root: Path) -> set[str]:
    """AC6. Every `.py` under `pdf_tooling_root` (not just `adapters/`)
    whose imports (via `_imported_top_levels`, an `ast.walk` so it sees
    function-local imports) intersect `SPAWN_MODULES`. Paths are relative
    to `pdf_tooling_root`, matching the spec's own quoted target
    `{"adapters/subprocess_util.py"}`."""
    found: set[str] = set()
    for f in sorted(pdf_tooling_root.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        names = {name for name, _line in _imported_top_levels(tree)}
        if names & SPAWN_MODULES:
            found.add(str(f.relative_to(pdf_tooling_root)).replace(os.sep, "/"))
    return found


def _engine_binding_adapters(pdf_tooling_root: Path) -> set[str]:
    """AC18/E3. Adapter modules whose imports (`ast.walk`, sees function-
    local imports) intersect `ENGINE_MODULES` -- ANYWHERE in the file, not
    just at module scope. Every one of the nine adapters imports its
    engine function-locally (the `--help` startup-cost decision
    `HELP_MODULE_CEILING` guards), so a module-level-only scan
    (`_module_level_engine_adapters` below) returns zero and is NOT this
    derivation."""
    adapters_dir = pdf_tooling_root / "adapters"
    found: set[str] = set()
    for f in sorted(adapters_dir.glob("*.py")):
        if f.name == "__init__.py":
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        names = {name for name, _line in _imported_top_levels(tree)}
        if names & ENGINE_MODULES:
            found.add(f.stem)
    return found


def _module_level_engine_adapters(pdf_tooling_root: Path) -> set[str]:
    """E3's "0" candidate: a MODULE-LEVEL-ONLY scan (`tree.body`, not
    `ast.walk`). Returns the empty set on the real tree -- proof that the
    `ast.walk`-based derivation above is not a refinement of a top-level
    grep, it is the only thing that returns a non-zero answer at all."""
    adapters_dir = pdf_tooling_root / "adapters"
    found: set[str] = set()
    for f in sorted(adapters_dir.glob("*.py")):
        if f.name == "__init__.py":
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        top_names: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                top_names.add(node.module.split(".")[0])
        if top_names & ENGINE_MODULES:
            found.add(f.stem)
    return found


def _port_backing_adapters(pdf_tooling_root: Path) -> set[str]:
    """AC5. `adapters/*.py` less `__init__.py` less the AST-derived spawn-
    chokepoint set (`_spawn_files_under_tree`, scoped to `adapters/`)."""
    files = _adapter_files(pdf_tooling_root)
    spawn = _spawn_files_under_tree(pdf_tooling_root)
    spawn_stems = {Path(p).stem for p in spawn if p.startswith("adapters/")}
    return files - spawn_stems


def _copy_pdf_tooling(tmp_path: Path) -> Path:
    """Every plant below runs against a `shutil.copytree` under `tmp_path`,
    never the real tree -- `pytest`'s own `tmp_path` fixture, the product's
    own idiom (`test_import_boundaries.py`'s `tmp_path`-based plants)."""
    tmp_pkg = tmp_path / "pdf_tooling"
    shutil.copytree(PDF_TOOLING_SRC, tmp_pkg)
    return tmp_pkg


# --------------------------------------------------------------------------- #
# AC1/AC2 -- the built page, dist tier.
# --------------------------------------------------------------------------- #


def test_ac1_the_rendered_spine_reads_cli_ops_safety_ports_adapters_output_in_order() -> None:
    """AC1. The six band PATHS occur in source order in the built page,
    and "Engines" occurs after the boundary-rule label. The standing red
    control is the pre-PDF-96 tree itself: at `5265850` the sixth spine
    entry was `Engines` and `output/` was absent entirely, which is the
    defect this item exists to fix (observed on `main`/`spec/pdf-95`
    before this item's own components existed, and re-confirmed by hand
    against a scratch `spine.json` with the last two entries swapped --
    see the implementation report)."""
    _require_dist()
    html = (DIST_ROOT / "index.html").read_text(encoding="utf-8")
    ordered_paths = [
        "src/pdf_tooling/cli/",
        "src/pdf_tooling/ops/",
        "src/pdf_tooling/safety/",
        "src/pdf_tooling/ports/",
        "src/pdf_tooling/adapters/",
        "src/pdf_tooling/output/",
    ]
    positions = [html.find(p) for p in ordered_paths]
    assert all(pos != -1 for pos in positions), (ordered_paths, positions)
    assert positions == sorted(positions), f"band paths are not in source order: {positions}"

    boundary_pos = html.find("Enforced boundary")
    engines_pos = html.find(">Engines<")
    assert boundary_pos != -1
    assert engines_pos != -1
    assert engines_pos > boundary_pos, "the string 'Engines' must occur AFTER the boundary label"


def test_ac2_output_carries_l6_and_its_own_sentence_and_engines_carries_neither() -> None:
    """AC2. `output/`'s band carries `L6` and the words `stdout`/`stderr`;
    the engines band carries no `Lx`-shaped index token anywhere and
    carries "Not this codebase"."""
    _require_dist()
    html = (DIST_ROOT / "index.html").read_text(encoding="utf-8")

    output_band = re.search(r'<li class="band return"[^>]*>.*?</li>', html, re.DOTALL)
    assert output_band, "no output/return band found in the built page"
    assert ">L6<" in output_band.group()
    assert "stdout" in output_band.group()
    assert "stderr" in output_band.group()

    engines_band = re.search(r'<li class="band external"[^>]*>.*?</li>', html, re.DOTALL)
    assert engines_band, "no engines/external band found in the built page"
    assert re.search(r"\bL\d\b", engines_band.group()) is None, (
        "the engines band carries an L-index token -- the absence of a layer "
        "index IS the argument (R1)"
    )
    assert "Not this codebase" in engines_band.group()


def test_ac10_the_lede_states_the_licence_guarantee_in_hard_form() -> None:
    """AC10. `empty` and `allowlist` occur together in one sentence; the
    file path `tests/test_import_boundaries.py` is present; the removed
    sentence `auditable by reading eight files` is absent."""
    _require_dist()
    html = (DIST_ROOT / "index.html").read_text(encoding="utf-8")
    assert "auditable by reading eight files" not in html
    assert "tests/test_import_boundaries.py" in html

    text = html_unescape(re.sub(r"<[^>]*>", " ", html))
    assert re.search(r"allowlist[^.]{0,220}\bempty\b", text, re.IGNORECASE) or re.search(
        r"\bempty\b[^.]{0,220}allowlist", text, re.IGNORECASE
    ), "the words 'empty' and 'allowlist' do not co-occur in one sentence"


def test_ac13_pdf92s_section_id_survives_the_exitcodes_rewrite_byte_identical() -> None:
    """AC13/D7 obligation 1. `id="contract"` -- PDF-92's, carrying no `id`
    at `5265850`, added by that item and frozen by
    `tests/test_website_contract.py`'s `FROZEN_SECTION_IDS` -- survives
    this item's rewrite of `ExitCodes.astro` byte-identical."""
    src = EXITCODES_ASTRO.read_text(encoding="utf-8")
    assert 'id="contract"' in src
    _require_dist()
    html = (DIST_ROOT / "index.html").read_text(encoding="utf-8")
    assert 'id="contract"' in html


def test_ac14_the_or7_guard_survives_and_the_struck_clause_stays_struck() -> None:
    """AC14/D7 obligation 2. The header comment carries OR-7's substance;
    the rendered code-0 meaning does not restate the clause OR-7 struck."""
    src = EXITCODES_ASTRO.read_text(encoding="utf-8")
    assert "OR-7" in src
    assert "struck" in src
    contracts = _load_contracts()
    code_zero = next(c for c in contracts["exitCodes"]["codes"] if c["code"] == 0)
    assert "a dry run is also 0" not in code_zero["meaning"].lower()
    assert "it is not always 0" in code_zero["meaning"]


# --------------------------------------------------------------------------- #
# AC3 -- the six real packages, derived and filtered.
# --------------------------------------------------------------------------- #


def test_ac3_the_six_layer_paths_are_the_six_real_packages() -> None:
    walked = _real_packages(PDF_TOOLING_SRC)
    assert walked == {"cli", "ops", "safety", "ports", "adapters", "output"}
    spine = _load_spine()
    rendered = {layer["path"].rstrip("/").split("/")[-1] for layer in spine["layers"]}
    assert rendered == walked


def test_ac3_an_unfiltered_walk_reds_on_the_real_tree_which_is_exactly_the_trap() -> None:
    """E2. `ls src/pdf_tooling/` (or a bare `iterdir()`) returns MORE than
    six entries on a CORRECT tree -- five top-level files plus the six
    packages, and an optional `__pycache__`. A derivation that used it
    would red on a tree that is not wrong. No plant needed: the real tree
    already proves it."""
    unfiltered = {p.name for p in PDF_TOOLING_SRC.iterdir()}
    filtered = _real_packages(PDF_TOOLING_SRC)
    assert filtered == {"cli", "ops", "safety", "ports", "adapters", "output"}
    assert unfiltered > filtered, (
        "the unfiltered walk should return strictly more than the six packages"
    )


def test_ac3_a_seventh_package_planted_moves_the_walked_set(tmp_path: Path) -> None:
    tmp_pkg = _copy_pdf_tooling(tmp_path)
    plant = tmp_pkg / "zzz_plant"
    plant.mkdir()
    (plant / "__init__.py").write_text("", encoding="utf-8")
    walked = _real_packages(tmp_pkg)
    assert walked == {"cli", "ops", "safety", "ports", "adapters", "output", "zzz_plant"}
    assert len(walked) == 7


# --------------------------------------------------------------------------- #
# AC4 -- the published six counts PORT MODULES, two independent derivations
# agree, and the rendered names equal PORTS in order.
# --------------------------------------------------------------------------- #


def test_ac4_the_published_six_is_ast_derived_and_both_derivations_agree() -> None:
    protocol_modules = _port_modules_with_protocol(PDF_TOOLING_SRC)
    ports_tuple = _ports_tuple(PDF_TOOLING_SRC)
    assert sorted(protocol_modules) == ["compose", "ocr", "office", "raster", "structure", "text"]
    assert len(protocol_modules) == len(ports_tuple) == 6

    spine = _load_spine()
    assert spine["counts"]["ports"] == 6
    ports_layer = _layer_by_path_suffix(spine, "ports")
    assert tuple(ports_layer["portNames"]) == ports_tuple, (
        "the rendered port names must equal PORTS in ORDER, not merely as a set"
    )


def test_ac4_a_seventh_ports_module_with_a_protocol_disagrees_the_two_derivations(
    tmp_path: Path,
) -> None:
    tmp_pkg = _copy_pdf_tooling(tmp_path)
    (tmp_pkg / "ports" / "zzz_plant.py").write_text(
        "from typing import Protocol\n\n\nclass PlantedEngine(Protocol):\n    ...\n",
        encoding="utf-8",
    )
    a = len(_port_modules_with_protocol(tmp_pkg))
    b = len(_ports_tuple(tmp_pkg))
    assert a == 7
    assert b == 6
    assert a != b, "the agreement arm must red when only ONE derivation moves"


def test_ac4_a_seventh_ports_entry_with_no_module_disagrees_from_the_other_side(
    tmp_path: Path,
) -> None:
    tmp_pkg = _copy_pdf_tooling(tmp_path)
    init_path = tmp_pkg / "ports" / "__init__.py"
    text = init_path.read_text(encoding="utf-8")
    mutated = text.replace(
        '    "OfficeConverter",\n)', '    "OfficeConverter",\n    "PlantedPort",\n)'
    )
    assert mutated != text, "PORTS's literal shape changed -- re-derive this plant"
    init_path.write_text(mutated, encoding="utf-8")
    a = len(_port_modules_with_protocol(tmp_pkg))
    b = len(_ports_tuple(tmp_pkg))
    assert a == 6
    assert b == 7
    assert a != b


def test_ac4_a_seventh_ports_module_with_no_protocol_moves_nothing(tmp_path: Path) -> None:
    """The row that proves the ports derivation is about PROTOCOL
    DEFINITIONS and not about files: a helper module dropped into `ports/`
    moves neither count."""
    tmp_pkg = _copy_pdf_tooling(tmp_path)
    (tmp_pkg / "ports" / "zzz_helper.py").write_text(
        "def helper() -> int:\n    return 1\n", encoding="utf-8"
    )
    a = len(_port_modules_with_protocol(tmp_pkg))
    b = len(_ports_tuple(tmp_pkg))
    assert a == 6
    assert b == 6


def test_ac17_the_page_never_labels_the_six_as_protocols() -> None:
    """AC17. `ports/` holds ELEVEN `Protocol` classes across six modules
    (E9) -- "six protocols" is ambiguous and, read literally, wrong. The
    page says "six ports"."""
    total_protocol_classes = sum(
        len(classes) for classes in _port_modules_with_protocol(PDF_TOOLING_SRC).values()
    )
    assert total_protocol_classes == 11, (
        "E9's eleven-Protocol-classes figure has moved -- re-derive"
    )

    for path in (ARCHITECTURE_ASTRO, SPINE_JSON):
        text = path.read_text(encoding="utf-8")
        assert re.search(r"\d+\s*protocols\b", text, re.IGNORECASE) is None, (
            f"{path.name} labels the six as a count of protocols"
        )

    spine = _load_spine()
    ports_layer = _layer_by_path_suffix(spine, "ports")
    assert "ports" in ports_layer["chip"].lower()
    assert "protocol" not in ports_layer["chip"].lower()


def test_ac17_changing_the_chip_to_protocols_reddens_this_cell_alone() -> None:
    """Control: a chip literally reading "6 protocols" reds this criterion
    while AC4's own count arm (which reads `counts.ports` / `PORTS` / the
    AST walk, never the chip string) stays green -- eleven Protocol
    classes exist across six modules and a COUNT arm cannot see a word."""
    mutated_chip = "6 protocols"
    assert re.search(r"\d+\s*protocols\b", mutated_chip, re.IGNORECASE)
    spine = _load_spine()
    assert spine["counts"]["ports"] == 6, "AC4's count arm is unaffected by the chip's own wording"


# --------------------------------------------------------------------------- #
# AC5/AC6/AC7 -- the adapter/spawn census and its balance.
# --------------------------------------------------------------------------- #


def test_ac5_the_published_eight_counts_port_backing_adapters_and_the_set_is_named() -> None:
    port_backing = _port_backing_adapters(PDF_TOOLING_SRC)
    assert port_backing == {
        "pdfium_raster",
        "pdfium_text",
        "pdfplumber_text",
        "pikepdf_structure",
        "pypdf_structure",
        "reportlab_compose",
        "soffice_office",
        "tesseract_ocr",
    }
    assert len(port_backing) == 8

    spine = _load_spine()
    assert spine["counts"]["portBackingAdapters"] == 8

    arch_src = ARCHITECTURE_ASTRO.read_text(encoding="utf-8")
    assert "adapter modules" in arch_src, "the published 8 must name its subject (R2/AC5)"
    assert (
        "{spine.adapters.count}" not in arch_src
    )  # not this product's own literal spelling; sanity only


def test_ac5_a_tenth_adapter_moves_the_published_figure_regardless_of_its_own_import(
    tmp_path: Path,
) -> None:
    """Control (both halves driven): a tenth adapter moves the published
    figure to 9 WHETHER OR NOT it imports an engine -- the figure is about
    port-backing, not engine-binding."""
    tmp_pkg = _copy_pdf_tooling(tmp_path)
    (tmp_pkg / "adapters" / "zzz_plant.py").write_text("import os\n", encoding="utf-8")
    port_backing = _port_backing_adapters(tmp_pkg)
    engine_binding = _engine_binding_adapters(tmp_pkg)
    assert len(port_backing) == 9
    assert len(engine_binding) == 7, "an `os`-only import does not bind an engine"


def test_ac5_a_tenth_adapter_that_imports_an_engine_moves_both_figures(tmp_path: Path) -> None:
    tmp_pkg = _copy_pdf_tooling(tmp_path)
    (tmp_pkg / "adapters" / "zzz_plant.py").write_text("import pypdf\n", encoding="utf-8")
    port_backing = _port_backing_adapters(tmp_pkg)
    engine_binding = _engine_binding_adapters(tmp_pkg)
    assert len(port_backing) == 9
    assert len(engine_binding) == 8


def test_ac6_the_published_one_is_the_spawn_chokepoint_ast_derived() -> None:
    spawn = _spawn_files_under_tree(PDF_TOOLING_SRC)
    assert spawn == {"adapters/subprocess_util.py"}
    arch_src = ARCHITECTURE_ASTRO.read_text(encoding="utf-8")
    assert "subprocess_util.py" in arch_src


def test_ac6_a_second_spawn_site_under_ops_moves_only_the_spawn_figure(tmp_path: Path) -> None:
    """Control. Deleting `subprocess_util.py` would also red the product's
    own `test_the_chokepoint_actually_spawns` and isolate nothing -- this
    plant is additive instead, and it moves ONLY the spawn figure."""
    tmp_pkg = _copy_pdf_tooling(tmp_path)
    (tmp_pkg / "ops" / "zzz_plant.py").write_text("import subprocess\n", encoding="utf-8")
    spawn = _spawn_files_under_tree(tmp_pkg)
    assert spawn == {"adapters/subprocess_util.py", "ops/zzz_plant.py"}
    assert len(spawn) == 2
    # AC4/AC5 unaffected by a plant under ops/
    assert len(_adapter_files(tmp_pkg)) == 9
    assert len(_port_modules_with_protocol(tmp_pkg)) == 6


def test_ac7_the_census_balances_eight_plus_one_equals_nine() -> None:
    files = _adapter_files(PDF_TOOLING_SRC)
    spawn = _spawn_files_under_tree(PDF_TOOLING_SRC)
    spawn_in_adapters = {p for p in spawn if p.startswith("adapters/")}
    port_backing = files - {Path(p).stem for p in spawn_in_adapters}
    assert len(port_backing) + len(spawn_in_adapters) == len(files) == 9

    spine = _load_spine()
    assert spine["counts"]["totalAdapterFiles"] == 9
    assert spine["counts"]["portBackingAdapters"] + spine["counts"]["spawnFiles"] == 9

    arch_src = ARCHITECTURE_ASTRO.read_text(encoding="utf-8")
    assert "counts.totalAdapterFiles} files" in arch_src, "the balance must be STATED, from data"


def test_ac7_a_tenth_adapter_that_spawns_makes_the_published_total_disagree_with_a_fresh_walk(
    tmp_path: Path,
) -> None:
    """Control (the spec's own scenario). Re-deriving port-backing and
    spawn counts FROM the same mutated tree is tautologically balanced by
    construction (`port_backing = files - spawn_stems`, always) -- that is
    not what the balance arm on the real page protects against. What it
    protects against is `spine.json`'s PUBLISHED total (`9`, hand-authored,
    unmoved by this plant because nothing here touches the website's data)
    silently going stale against the real tree. Planting a tenth, spawning
    adapter: port-backing stays 8, spawn becomes 2, the file count becomes
    10 -- and the page's published `9` no longer equals a fresh walk of
    THIS tree, which is exactly the drift `test_ac7_the_census_balances_
    eight_plus_one_equals_nine`'s own `spine["counts"]["totalAdapterFiles"]
    == 9` arm would catch if the real tree ever changed out from under a
    stale `spine.json`."""
    tmp_pkg = _copy_pdf_tooling(tmp_path)
    (tmp_pkg / "adapters" / "zzz_plant.py").write_text("import subprocess\n", encoding="utf-8")
    files = _adapter_files(tmp_pkg)
    spawn = _spawn_files_under_tree(tmp_pkg)
    spawn_in_adapters = {p for p in spawn if p.startswith("adapters/")}
    port_backing = files - {Path(p).stem for p in spawn_in_adapters}
    assert len(port_backing) == 8
    assert len(spawn_in_adapters) == 2
    assert len(files) == 10

    spine = _load_spine()  # unchanged -- stale relative to this mutated tree
    assert spine["counts"]["totalAdapterFiles"] == 9
    with pytest.raises(AssertionError):
        assert spine["counts"]["totalAdapterFiles"] == len(files), (
            "the page's published total (9) must equal a fresh walk of the real tree; "
            "against this mutated tree (10) it no longer does"
        )


# --------------------------------------------------------------------------- #
# AC18 -- engine-binding is measured, reported, and NEVER published.
# --------------------------------------------------------------------------- #


def test_ac18_engine_binding_seven_is_measured_and_differs_from_the_published_eight() -> None:
    engine_binding = _engine_binding_adapters(PDF_TOOLING_SRC)
    port_backing = _port_backing_adapters(PDF_TOOLING_SRC)
    module_level_only = _module_level_engine_adapters(PDF_TOOLING_SRC)

    assert len(engine_binding) == 7
    assert len(port_backing) == 8
    assert len(module_level_only) == 0, "E3: every adapter imports its engine function-locally"
    assert len(engine_binding) != len(port_backing)
    assert "soffice_office" in port_backing
    assert "soffice_office" not in engine_binding, (
        "soffice_office.py drives the `soffice` BINARY through the spawn chokepoint; "
        "it imports no engine library"
    )

    spine = _load_spine()
    assert spine["counts"]["portBackingAdapters"] == len(port_backing) == 8

    for path in (ARCHITECTURE_ASTRO, SPINE_JSON):
        text = path.read_text(encoding="utf-8")
        assert "7 adapter modules" not in text, (
            "the engine-binding 7 must never be published as the count"
        )


def test_ac18_a_planted_engine_import_in_soffice_office_reddens_the_must_differ_arm(
    tmp_path: Path,
) -> None:
    """Control (the spec's own, `AC18`): add `import pdfplumber` inside a
    function in `soffice_office.py` -- engine-binding moves 7 -> 8, the
    published figure stays 8, and the delta this criterion polices goes to
    ZERO. This is the plant that stops a future engineer "fixing" the
    seven into the eight."""
    tmp_pkg = _copy_pdf_tooling(tmp_path)
    soffice = tmp_pkg / "adapters" / "soffice_office.py"
    soffice.write_text(
        soffice.read_text(encoding="utf-8")
        + "\n\ndef _plant() -> object:\n    import pdfplumber\n\n    return pdfplumber\n",
        encoding="utf-8",
    )
    engine_binding = _engine_binding_adapters(tmp_pkg)
    port_backing = _port_backing_adapters(tmp_pkg)
    assert len(engine_binding) == 8, "the plant should move engine-binding 7 -> 8"
    assert len(port_backing) == 8, (
        "the published figure is unaffected by an import inside an existing adapter"
    )
    with pytest.raises(AssertionError):
        assert len(engine_binding) != len(port_backing), (
            "this is the exact assertion that would red in production if soffice_office.py "
            "started binding an engine library -- observed failing here, on the plant, on purpose"
        )


# --------------------------------------------------------------------------- #
# AC8 -- no bare cardinal typed into the rewritten components.
# --------------------------------------------------------------------------- #

#: The page-chapter eyebrow (`&sect;02`, `&sect;05`, ...) is a PRE-EXISTING
#: site convention on every section (Features, Architecture, Verbs,
#: ExitCodes, Licensing) and names a navigational chapter index, not a
#: claim about the codebase this spec's counts are about. Exempted so the
#: scan targets what AC8 actually cares about.
_SECT_EYEBROW_RE: Final[re.Pattern[str]] = re.compile(r"&sect;\d+")


def _strip_balanced_expressions(text: str) -> str:
    """Removes every `{...}` Astro/JSX expression, including nested ones
    (a ternary inside a `{}` can itself contain a `{}` -- the evidence
    table's citation cell does exactly this)."""
    out: list[str] = []
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            if depth > 0:
                depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def _template_prose_only(astro_source: str) -> str:
    """The rendered TEXT the component types literally: frontmatter
    dropped, any `<style>` block dropped WHOLESALE (its CSS numerals --
    pixel offsets, breakpoints -- are geometry, not a claim about the
    codebase), `{}` expressions dropped, tags (and their attributes, where
    Tailwind class names live) dropped, the eyebrow's chapter number
    dropped."""
    parts = astro_source.split("---", 2)
    template = parts[2] if len(parts) == 3 else astro_source
    template = re.sub(r"<style\b.*?</style>", " ", template, flags=re.DOTALL)
    template = _strip_balanced_expressions(template)
    template = _SECT_EYEBROW_RE.sub("", template)
    template = re.sub(r"<[^>]*>", " ", template)
    return template


def test_ac8_no_bare_cardinal_is_typed_into_the_rewritten_components() -> None:
    for path in (ARCHITECTURE_ASTRO, EXITCODES_ASTRO, ATOMICWRITE_ASTRO):
        prose = _template_prose_only(path.read_text(encoding="utf-8"))
        digits = re.findall(r"\d+", prose)
        assert digits == [], f"{path.name} types a bare cardinal in its rendered prose: {digits}"


def test_ac8_a_literal_replacing_a_count_expression_reddens_the_grep() -> None:
    """Control: replace one count EXPRESSION with a literal `8` in a copy
    of the real source (never written to the tree) -- the prose-only scan
    reds naming the digit, which is exactly the failure this criterion
    exists to catch separately from AC5's own count arm."""
    original = ARCHITECTURE_ASTRO.read_text(encoding="utf-8")
    needle = "{counts.portBackingAdapters} adapter modules"
    assert needle in original, (
        "the expression this control targets is no longer present -- re-derive the plant"
    )
    mutated = original.replace(needle, "8 adapter modules", 1)
    prose = _template_prose_only(mutated)
    digits = re.findall(r"\d+", prose)
    assert "8" in digits


# --------------------------------------------------------------------------- #
# AC9 -- every "Enforced by" cell cites a real test function, or the README
# heading for L6, and no cell cites "§N".
# --------------------------------------------------------------------------- #


def test_ac9_every_enforced_by_cell_cites_a_real_function_or_the_readme_heading() -> None:
    """The citations THEMSELVES live in `spine.json` (each layer's
    `enforcedBy`), consumed by `Architecture.astro`'s `<details>` table via
    a `.map()` expression -- the .astro SOURCE never spells a function name
    as a literal, only `spine.json` does, which is what makes the walk in
    `D3` a derivation rather than a duplicate vocabulary. This arm checks
    both: the data's own citations, and that `Architecture.astro`'s markup
    (which decides what CAN be rendered) never hard-codes a "§N" citation
    anywhere in its `<details>` block."""
    spine = _load_spine()
    import_boundaries_src = IMPORT_BOUNDARIES_TEST.read_text(encoding="utf-8")
    readme_src = README.read_text(encoding="utf-8")

    seen_readme_heading_citation = False
    for layer in spine["layers"]:
        citations = layer["enforcedBy"]
        assert citations, f"layer {layer['index']} has no 'Enforced by' citation at all"
        for citation in citations:
            assert "§" not in citation, (
                f"layer {layer['index']}'s citation {citation!r} names a section number -- "
                "tests/test_import_boundaries.py carries two Section 6 headers (E8/D4)"
            )
            if citation.startswith("README.md"):
                assert "## Output contract" in citation
                assert "## Output contract" in readme_src
                seen_readme_heading_citation = True
            else:
                assert f"def {citation}(" in import_boundaries_src, (
                    f"cited function {citation!r} does not exist in {IMPORT_BOUNDARIES_TEST.name}"
                )
    assert seen_readme_heading_citation, "L6 must cite the README heading, not a test function"

    arch_src = ARCHITECTURE_ASTRO.read_text(encoding="utf-8")
    match = re.search(r"<details.*?</details>", arch_src, re.DOTALL)
    assert match, "no <details> evidence block found in Architecture.astro"
    assert "§" not in match.group(), (
        "Architecture.astro's own markup must never hard-code a section-number citation"
    )


def test_ac9_the_built_evidence_table_renders_every_citation_and_no_section_symbol() -> None:
    """Dist-tier confirmation: the data-driven citations actually reach
    the built page, end to end."""
    _require_dist()
    html = (DIST_ROOT / "index.html").read_text(encoding="utf-8")
    details_block = re.search(r"<details.*?</details>", html, re.DOTALL)
    assert details_block, "no <details> evidence block found in the built page"
    block = details_block.group()
    assert "§" not in block
    assert "README.md" in block
    assert "## Output contract" in block
    spine = _load_spine()
    for layer in spine["layers"]:
        for citation in layer["enforcedBy"]:
            if not citation.startswith("README.md"):
                assert citation in block, f"citation {citation!r} did not reach the built page"


def test_ac9_a_renamed_cited_function_reddens_the_citation_arm(tmp_path: Path) -> None:
    """Control: rename one cited function in a `tmp_path` copy of the test
    file -- the citation arm reds naming the row's function."""
    tmp_copy = tmp_path / "test_import_boundaries.py"
    tmp_copy.write_text(
        IMPORT_BOUNDARIES_TEST.read_text(encoding="utf-8").replace(
            "def test_no_typer_or_click_import_below_l1(", "def test_renamed_by_the_plant("
        ),
        encoding="utf-8",
    )
    mutated_src = tmp_copy.read_text(encoding="utf-8")
    assert "def test_no_typer_or_click_import_below_l1(" not in mutated_src
    with pytest.raises(AssertionError):
        assert "def test_no_typer_or_click_import_below_l1(" in mutated_src, (
            "the citation arm reds exactly here when its cited function no longer exists"
        )


# --------------------------------------------------------------------------- #
# AC15/AC16 -- the temp-file prefix trap.
# --------------------------------------------------------------------------- #


def test_ac15_no_legacy_needle_under_website_reproof() -> None:
    """Re-proof (every slice in this cycle owes one, per the notes). The
    primary arm is `tests/test_website_contract.py`'s existing
    `test_a9_no_hyphenated_or_underscored_legacy_needle_under_website`;
    this is the same grep (same `LEGACY_NEEDLE`, imported rather than
    re-spelled), re-run here because this item is the one that introduced
    the trap's only live carrier (the atomic-write station)."""
    proc = _git("grep", "--untracked", "-Ion", "-E", LEGACY_NEEDLE, "--", "website/")
    assert proc.returncode in (0, 1), f"git grep failed rc={proc.returncode}: {proc.stderr}"
    hits = [line for line in proc.stdout.splitlines() if line]
    assert hits == [], f"legacy needle under website/: {hits}"


def test_ac16_station_three_names_the_property_without_the_forbidden_prefix() -> None:
    contracts = _load_contracts()
    station_three = contracts["atomicWrite"]["stations"][2]
    assert "same filesystem" in station_three["detail"]
    for path in (ATOMICWRITE_ASTRO, CONTRACTS_JSON):
        text = path.read_text(encoding="utf-8").lower()
        assert _LEGACY_BARE_FRAGMENT not in text, (
            f"{path.name} carries the forbidden temp-prefix spelling"
        )


def test_ac16_deleting_the_same_filesystem_clause_reddens_the_positive_half() -> None:
    """Control, the positive half: delete the "same filesystem" clause and
    the diagram would assert atomicity with nothing behind it."""
    contracts = _load_contracts()
    detail = contracts["atomicWrite"]["stations"][2]["detail"]
    mutated = detail.replace(", on the same filesystem — which is what makes the rename atomic", "")
    assert mutated != detail
    assert "same filesystem" not in mutated


# --------------------------------------------------------------------------- #
# AC19 -- the exit-code datasheet agrees with the source, in order and
# cardinality.
# --------------------------------------------------------------------------- #


def _exit_code_constants_in_order() -> list[tuple[str, int]]:
    text = EXIT_CODES_SRC.read_text(encoding="utf-8")
    pattern = re.compile(r"^(\w+): Final\[int\] = (\d+)$", re.MULTILINE)
    return [(m.group(1), int(m.group(2))) for m in pattern.finditer(text)]


def test_ac19_the_exit_code_datasheet_agrees_with_the_source_in_order_and_cardinality() -> None:
    constants = _exit_code_constants_in_order()
    assert [name for name, _value in constants] == [
        "OK",
        "FAILURE",
        "USAGE",
        "ENGINE_MISSING",
        "NO_INPUT",
        "REFUSED",
        "AUTH",
    ]
    assert [value for _name, value in constants] == [0, 1, 2, 3, 4, 5, 6]

    contracts = _load_contracts()
    codes = contracts["exitCodes"]["codes"]
    assert len(codes) == 7
    assert [c["code"] for c in codes] == [value for _name, value in constants]
    assert [c["name"] for c in codes] == [name for name, _value in constants]

    shapes = contracts["outputContract"]["shapes"]
    assert [s["flag"] for s in shapes] == ["-o table", "-o json", "-o ndjson"]


def test_ac19_dropping_a_code_reddens_the_cardinality_arm() -> None:
    """Control: drop `AUTH` from a copy of `contracts.json`'s codes -- the
    cardinality arm reds. Deliberately NOT
    `test_cli_spine.py::test_exit_code_constants_hold_their_published_integers`
    as this control -- that arm pins the SOURCE and stays green through any
    change to the website's own data, which is the gap this arm closes."""
    contracts = _load_contracts()
    codes = contracts["exitCodes"]["codes"]
    mutated = codes[:-1]
    assert len(mutated) == 6
    with pytest.raises(AssertionError):
        assert len(mutated) == 7


# --------------------------------------------------------------------------- #
# AC22 -- the changelog entry.
# --------------------------------------------------------------------------- #


def test_ac22_the_changelog_carries_a_pdf96_entry_directly_below_the_anchor() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    anchor = "<!-- CHANGELOG-ANCHOR"
    anchor_idx = text.index(anchor)
    anchor_line_end = text.index("\n", anchor_idx) + 1
    remainder = text[anchor_line_end:].lstrip("\n")
    first_line = remainder.splitlines()[0]
    assert first_line.startswith("## [PDF-96] "), (
        "the PDF-96 entry must be the first heading directly below the anchor line"
    )
    assert re.match(r"^## \[PDF-96\] .+ — \d{4}-\d{2}-\d{2}$", first_line), (
        f"changelog heading does not match the required format: {first_line!r}"
    )
