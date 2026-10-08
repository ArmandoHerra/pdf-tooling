"""The README's first screen -- PDF-130.

A stranger on the repository or the PyPI page must be able to try the tool in a
single command, see it work, copy a recipe, and learn when to use something
else, without first reading migration tables or a pointer at a private tree.

Every arm is a pure function over README TEXT (or a path) plus a test that feeds
it the real file and a test that feeds it a scratch rendering that must turn it
red; a green arm that was never observed red is not yet evidence. The one
subprocess family is the recipe execution: the engine-free recipes are run
through the suite's existing CLI helper (`registry.run_cli`). The OCR recipe is
introspected but NEVER driven here (an `ocr` drive would join the PDF-82
engine-blind census); it is executed by hand in Validation.

Nothing here teaches `--clear-all` or claims metadata removal (OR-42).
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(_TESTS_DIR))

from registry import run_cli  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
TAPE = REPO_ROOT / "docs" / "demo" / "pdf-tooling.tape"
GIF = REPO_ROOT / "docs" / "demo" / "pdf-tooling.gif"

WHAT_EXISTS = "## What exists today"
COMPARISON_HEADING = "## When to use something else"
RECIPES_HEADING = "## Recipes"
LIMITATIONS_HEADING = "### Known limitations"
COMPARED_TOOLS = ("pdf-tooling", "qpdf", "pdfcpu", "pdfly", "OCRmyPDF")

GIF_URL = (
    "https://raw.githubusercontent.com/ArmandoHerra/pdf-tooling/main/docs/demo/pdf-tooling.gif"
)
GIF_URL_PATTERN = re.compile(
    r"^https://raw\.githubusercontent\.com/ArmandoHerra/pdf-tooling/main/docs/demo/pdf-tooling\.gif$"
)
GIF_MAX_BYTES = 1048576
GIF_MAX_WIDTH = 1400

#: D9(f). Case-insensitive; the stems cover "stripped", "scrubbing", "sanitize".
TEACHING_GATE = re.compile(
    r"clear-all|strip|scrub|sanitiz|remove metadata|removes metadata", re.IGNORECASE
)


def readme_text() -> str:
    return README.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Text helpers (pure: every arm takes text so a red control can feed scratch)
# --------------------------------------------------------------------------- #


def first_screen(text: str) -> str:
    """The README from the start up to, not including, `## What exists today`."""
    assert WHAT_EXISTS in text, "README carries no `## What exists today` heading"
    return text.split(WHAT_EXISTS, 1)[0]


def h2_headings(text: str) -> list[str]:
    """H2 headings in order, ignoring any `## ` inside a fenced block."""
    headings: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith("## "):
            headings.append(line)
    return headings


def section(text: str, heading: str) -> str:
    """The section opened by *heading*, bounded by the next heading of the same
    or a higher level (so a `###` section ends at the next `###` or `##`)."""
    assert text.count(heading + "\n") == 1, f"expected exactly one {heading!r} heading"
    level = len(heading) - len(heading.lstrip("#"))
    after = text.split(heading + "\n", 1)[1]
    stop = re.search(rf"^#{{1,{level}}} ", after, re.MULTILINE)
    return after[: stop.start()] if stop else after


def blank(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        for index in range(start, end):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


# --------------------------------------------------------------------------- #
# (a) the try-it line
# --------------------------------------------------------------------------- #

TRY_IT_BLOCK = "```bash\nuvx pdf-tooling --help\n```"


def try_it_complaints(text: str, project: dict[str, object]) -> list[str]:
    complaints: list[str] = []
    if TRY_IT_BLOCK not in first_screen(text):
        complaints.append(
            "the first screen does not carry the exact `uvx pdf-tooling --help` block"
        )
    name = str(project["name"])
    scripts = project.get("scripts", {})
    assert isinstance(scripts, dict)
    if name not in scripts:
        complaints.append(
            f"[project].name {name!r} is not a key of [project.scripts]; "
            f"`uvx {name}` would not resolve to a command"
        )
    if "uvx pdftooling" in text:
        complaints.append("`uvx pdftooling` appears; that name is not on PyPI")
    return complaints


def _project() -> dict[str, object]:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_try_it_line_is_the_alias_and_is_bound_to_pyproject() -> None:
    assert try_it_complaints(readme_text(), _project()) == []


def test_try_it_line_arm_can_fail() -> None:
    project = _project()
    scripts = {k: v for k, v in dict(project["scripts"]).items() if k != "pdf-tooling"}  # type: ignore[arg-type]
    complaints = try_it_complaints(readme_text(), {**project, "scripts": scripts})
    assert any("'pdf-tooling' is not a key of [project.scripts]" in c for c in complaints)
    wrong = readme_text().replace("uvx pdf-tooling --help", "uvx pdftooling --help", 1)
    assert try_it_complaints(wrong, project) != []


# --------------------------------------------------------------------------- #
# (b) order
# --------------------------------------------------------------------------- #


def order_complaints(text: str) -> list[str]:
    complaints: list[str] = []
    screen = first_screen(text)
    if not (
        "## Getting Started" in screen
        and RECIPES_HEADING in screen
        and screen.index("## Getting Started") < screen.index(RECIPES_HEADING)
    ):
        complaints.append("the first screen must carry `## Getting Started` then `## Recipes`")
    for token in ("## Upgrading", "## Naming", "**Current phase:**", "ai_plans/"):
        if token in screen:
            complaints.append(f"the first screen carries {token!r}")
    headings = h2_headings(text)
    upgrades = [h for h in headings if h.startswith("## Upgrading to ")]
    chain = ["## Exit codes", *upgrades, "## Naming", "## Development", "## Known issues"]
    try:
        positions = [headings.index(h) for h in chain]
    except ValueError as missing:
        return [*complaints, f"a heading in the order chain is absent: {missing}"]
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        complaints.append(
            "the order must be: Exit codes < Upgrading to ... < Naming < Development < Known issues"
        )
    if not upgrades:
        complaints.append("no `## Upgrading to ...` heading remains")
    index = headings.index("## Output contract")
    if headings[index + 1] != "## Exit codes":
        complaints.append("`## Output contract` must be directly followed by `## Exit codes`")
    return complaints


def test_order_of_the_first_screen_and_the_moved_sections() -> None:
    assert order_complaints(readme_text()) == []


def test_order_arm_can_fail_when_the_migration_block_moves_back_up() -> None:
    text = readme_text()
    start = text.index("## Upgrading to 1.0.0")
    end = text.index("\n## Naming", start) + 1
    block = text[start:end]
    moved = (text[:start] + text[end:]).replace(WHAT_EXISTS, block + WHAT_EXISTS, 1)
    complaints = order_complaints(moved)
    assert any("first screen carries '## Upgrading'" in c for c in complaints)
    assert any("the order must be" in c for c in complaints)


# --------------------------------------------------------------------------- #
# (c) recipes
# --------------------------------------------------------------------------- #

RECIPE_FILES = ("chapter1.pdf", "chapter2.pdf", "book.pdf", "scan.pdf", "owner.txt", "user.txt")


def recipes(text: str) -> list[tuple[str, str]]:
    """`(title, bash block body)` per `###` subsection under `## Recipes`."""
    body = section(text, RECIPES_HEADING)
    parts = re.split(r"^### ", body, flags=re.MULTILINE)[1:]
    found: list[tuple[str, str]] = []
    for part in parts:
        title = part.split("\n", 1)[0]
        blocks = re.findall(r"```bash\n(.*?)```", part, flags=re.DOTALL)
        assert len(blocks) == 1, f"recipe {title!r} must carry exactly one bash block"
        found.append((title, blocks[0]))
    return found


def pdftooling_argvs(block: str) -> list[list[str]]:
    """Each `pdftooling ...` line of *block* as argv (after the program name),
    cut at the first pipe so only the left side of a pipeline is run."""
    argvs: list[list[str]] = []
    for line in block.splitlines():
        words = shlex.split(line)
        if not words or words[0] != "pdftooling":
            continue
        if "|" in words:
            words = words[: words.index("|")]
        argvs.append(words[1:])
    return argvs


def _verb_command(argv: list[str]):  # type: ignore[no-untyped-def]
    import typer

    from pdf_tooling.cli.main import app

    root = typer.main.get_command(app)
    commands = getattr(root, "commands", {})
    for word in argv:
        if not word.startswith("-") and word in commands:
            return commands[word]
    raise AssertionError(f"no verb of the live command tree appears in {argv!r}")


def undeclared_options(text: str) -> list[str]:
    """Every long option in a recipe that its verb's Click command does not declare."""
    bad: list[str] = []
    for title, block in recipes(text):
        for argv in pdftooling_argvs(block):
            declared = {
                opt
                for param in _verb_command(argv).params
                for opt in (*param.opts, *param.secondary_opts)
            }
            bad.extend(
                f"{title}: {word}"
                for word in argv
                if word.startswith("--") and word.split("=", 1)[0] not in declared
            )
    return bad


def recipe_structure_complaints(text: str) -> list[str]:
    found = recipes(text)
    return [] if len(found) == 5 else [f"expected exactly 5 recipes, found {len(found)}"]


def test_recipe_structure_is_five_subsections_with_one_bash_block_each() -> None:
    assert recipe_structure_complaints(readme_text()) == []


def test_recipe_every_long_option_is_declared_by_its_verb() -> None:
    assert undeclared_options(readme_text()) == []


def test_recipe_introspection_arm_can_fail_on_an_undeclared_option() -> None:
    text = readme_text().replace(
        "pdftooling ocr scan.pdf -O scan-searchable.pdf",
        "pdftooling ocr scan.pdf -O scan-searchable.pdf --language eng",
        1,
    )
    assert any("--language" in bad for bad in undeclared_options(text))


def _materialize(workdir: Path, corpus) -> None:  # type: ignore[no-untyped-def]
    import shutil

    shutil.copy(corpus.path("multipage_text"), workdir / "chapter1.pdf")
    shutil.copy(corpus.path("single_page"), workdir / "chapter2.pdf")
    for name, password in (("owner.txt", "owner-secret"), ("user.txt", "user-secret")):
        target = workdir / name
        target.write_text(password + "\n", encoding="utf-8")
        target.chmod(0o600)


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def run_recipe(argvs: list[list[str]], workdir: Path) -> list[int]:
    codes: list[int] = []
    for argv in argvs:
        proc = run_cli(argv[0], *argv[1:], cwd=workdir)
        codes.append(proc.returncode)
    return codes


def test_recipe_the_engine_free_recipes_execute(tmp_path: Path, corpus) -> None:  # type: ignore[no-untyped-def]
    import json

    _materialize(tmp_path, corpus)
    by_title = dict(recipes(readme_text()))
    wanted = {
        "Merge": "book.pdf",
        "Compress": "book-small.pdf",
    }
    for title, output in wanted.items():
        for argv in pdftooling_argvs(by_title[title]):
            proc = run_cli(argv[0], *argv[1:], cwd=tmp_path)
            assert proc.returncode == 0, (title, argv, proc.stderr)
            assert json.loads(proc.stdout)["items"][0]["output"] == output
    encrypt_title = next(t for t in by_title if t.startswith("Encrypt"))
    for argv in pdftooling_argvs(by_title[encrypt_title]):
        proc = run_cli(argv[0], *argv[1:], cwd=tmp_path)
        assert proc.returncode == 0, (argv, proc.stderr)
        json.loads(proc.stdout)
    assert (tmp_path / "book-locked.pdf").is_file() and (tmp_path / "book-open.pdf").is_file()
    preview_title = next(t for t in by_title if t.startswith("Preview"))
    before = _tree(tmp_path)
    for argv in pdftooling_argvs(by_title[preview_title]):
        proc = run_cli(argv[0], *argv[1:], cwd=tmp_path)
        assert proc.returncode == 0, (argv, proc.stderr)
        assert [i["ok"] for i in json.loads(proc.stdout)["items"]] == [True, True]
    assert _tree(tmp_path) == before, "a --dry-run recipe wrote something"


def test_recipe_execution_arm_can_fail_on_encrypt_password_file(tmp_path: Path, corpus) -> None:  # type: ignore[no-untyped-def]
    """AC3(i): the roadmap's literal `encrypt --password-file` exits 2."""
    _materialize(tmp_path, corpus)
    (tmp_path / "book.pdf").write_bytes((tmp_path / "chapter1.pdf").read_bytes())
    scratch = readme_text().replace("--owner-password-file", "--password-file", 1)
    title = next(t for t, _ in recipes(scratch) if t.startswith("Encrypt"))
    encrypt_only = [a for a in pdftooling_argvs(dict(recipes(scratch))[title]) if a[0] == "encrypt"]
    assert run_recipe(encrypt_only, tmp_path) == [2]


# --------------------------------------------------------------------------- #
# (d) the demo
# --------------------------------------------------------------------------- #


def gif_complaints(data: bytes) -> list[str]:
    complaints: list[str] = []
    if not data.startswith(b"GIF89a"):
        complaints.append("the demo is not a GIF89a")
    if len(data) > GIF_MAX_BYTES:
        complaints.append(f"the demo is {len(data)} bytes, over the {GIF_MAX_BYTES} budget")
    width = int.from_bytes(data[6:8], "little") if len(data) >= 8 else 0
    if width > GIF_MAX_WIDTH:
        complaints.append(f"the demo is {width}px wide, over {GIF_MAX_WIDTH}")
    return complaints


def tape_complaints(tape: str, readme: str) -> list[str]:
    complaints: list[str] = []
    if "v0.12.1" not in tape:
        complaints.append("the tape does not name VHS v0.12.1")
    if "docker run" not in tape and "vhs docs/demo" not in tape:
        complaints.append("the tape header does not record the render command")
    if not re.search(r"pdf-tooling version: \d+\.\d+\.\d+", tape):
        complaints.append("the tape header does not record the pdf-tooling version")
    output = re.search(r"^Output (\S+)$", tape, re.MULTILINE)
    suffix = GIF_URL.split("/main/", 1)[1]
    if not output or output.group(1) != suffix:
        complaints.append(f"the tape Output must equal the README image path {suffix!r}")
    width = re.search(r"^Set Width (\d+)$", tape, re.MULTILINE)
    if not width or int(width.group(1)) > GIF_MAX_WIDTH:
        complaints.append("the tape must Set Width to at most 1400")
    images = re.findall(r"!\[[^\]]*\]\((\S+)\)", first_screen(readme))
    if not any(GIF_URL_PATTERN.match(url) for url in images):
        complaints.append("the first screen does not link the demo by its absolute URL")
    return complaints


def test_demo_tape_header_output_and_absolute_readme_link() -> None:
    assert tape_complaints(TAPE.read_text(encoding="utf-8"), readme_text()) == []


def test_demo_tape_arm_can_fail() -> None:
    tape = TAPE.read_text(encoding="utf-8")
    assert tape_complaints(tape.replace("v0.12.1", "v0.0.0"), readme_text()) != []
    relative = readme_text().replace(GIF_URL, "docs/demo/pdf-tooling.gif")
    assert tape_complaints(tape, relative) != []


def test_demo_gif_is_a_small_plain_blob() -> None:
    assert GIF.is_file(), "docs/demo/pdf-tooling.gif is missing"
    assert gif_complaints(GIF.read_bytes()) == []
    attr = subprocess.run(
        ["git", "check-attr", "filter", "--", "docs/demo/pdf-tooling.gif"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "lfs" not in attr, f"the demo must not be Git LFS: {attr!r}"


def test_demo_gif_size_arm_can_fail() -> None:
    oversized = b"GIF89a" + (1200).to_bytes(2, "little") + bytes(GIF_MAX_BYTES + 1 - 8)
    assert len(oversized) == GIF_MAX_BYTES + 1
    assert any("over the" in c for c in gif_complaints(oversized))
    wide = b"GIF89a" + (1401).to_bytes(2, "little") + bytes(10)
    assert any("px wide" in c for c in gif_complaints(wide))


# --------------------------------------------------------------------------- #
# (e) the comparison (README only: OR-39)
# --------------------------------------------------------------------------- #

DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
URL = re.compile(r"https?://\S+")


def comparison_complaints(text: str) -> list[str]:
    body = section(text, COMPARISON_HEADING)
    complaints: list[str] = []
    rows = [
        line for line in body.splitlines() if line.startswith("|") and not line.startswith("|---")
    ][1:]
    names = [row.split("|")[1].strip() for row in rows]
    if names != list(COMPARED_TOOLS):
        complaints.append(f"the table rows must be exactly {list(COMPARED_TOOLS)}, got {names}")
    sources = body.split("Sources:", 1)[1] if "Sources:" in body else ""
    for tool in COMPARED_TOOLS[1:]:
        if not any(tool in line and "https://" in line for line in sources.splitlines()):
            complaints.append(f"the Sources list carries no https:// URL for {tool}")
    if not re.search(r"Checked on `\d{4}-\d{2}-\d{2}`", body):
        complaints.append("the section carries no `Checked on` date")
    masked = body
    for pattern in (URL, DATE):
        masked = pattern.sub(" ", masked)
    masked = re.sub(r"`[^`]*`", " ", masked)
    digits = re.findall(r"\d+", masked)
    if digits:
        complaints.append(f"a digit survives masking (no counts, no versions): {digits}")
    return complaints


def website_files_naming_compared_projects() -> list[str]:
    needles = (b"pdfcpu", b"pdfly", b"ocrmypdf")
    hits: list[str] = []
    for root, dirs, files in os.walk(REPO_ROOT / "website"):
        dirs[:] = [d for d in dirs if d not in {"node_modules", "dist", ".astro", ".git"}]
        for name in files:
            path = Path(root) / name
            try:
                data = path.read_bytes().lower()
            except OSError:  # pragma: no cover - unreadable file
                continue
            if any(needle in data for needle in needles):
                hits.append(str(path.relative_to(REPO_ROOT)))
    return hits


def test_comparison_rows_sources_date_and_no_digit() -> None:
    assert comparison_complaints(readme_text()) == []


def test_comparison_arm_can_fail() -> None:
    text = readme_text()
    sixth = text.replace(
        "\nSources:\n",
        "\n| ripgrep | `MIT` | Rust | no | no | no | yes | grepping |\n\nSources:\n",
        1,
    )
    assert any("rows must be exactly" in c for c in comparison_complaints(sixth))
    stars = text.replace("| Go |", "| Go; 42 stars |", 1)
    assert any("digit survives" in c for c in comparison_complaints(stars))


def test_comparison_stays_off_the_website() -> None:
    """OR-39: no comparison on the project website."""
    assert website_files_naming_compared_projects() == []


# --------------------------------------------------------------------------- #
# (f) the teaching gate (OR-42)
# --------------------------------------------------------------------------- #


def teaching_gate_complaints(text: str, tape: str) -> list[str]:
    guarded = {
        "first screen": first_screen(text),
        "## Recipes": section(text, RECIPES_HEADING),
        COMPARISON_HEADING: section(text, COMPARISON_HEADING),
        LIMITATIONS_HEADING: section(text, LIMITATIONS_HEADING),
        "the .tape": tape,
    }
    return [
        f"{where} contains {match.group(0)!r}"
        for where, body in guarded.items()
        for match in TEACHING_GATE.finditer(body)
    ]


def test_teaching_gate_nothing_added_teaches_clear_all_or_metadata_removal() -> None:
    assert teaching_gate_complaints(readme_text(), TAPE.read_text(encoding="utf-8")) == []


def test_teaching_gate_arm_can_fail() -> None:
    tape = TAPE.read_text(encoding="utf-8")
    poisoned_tape = tape + "\nType `pdftooling meta set --clear-all book.pdf -O clean.pdf`\n"
    assert teaching_gate_complaints(readme_text(), poisoned_tape) != []
    text = readme_text().replace(
        "pdftooling merge chapter1.pdf chapter2.pdf -O book.pdf\n",
        "pdftooling merge chapter1.pdf chapter2.pdf -O book.pdf\n"
        "pdftooling meta set --clear-all book.pdf -O clean.pdf\n",
        1,
    )
    assert any("'clear-all'" in c for c in teaching_gate_complaints(text, tape))


def test_teaching_gate_known_limitations_states_no_removal_method() -> None:
    body = section(readme_text(), LIMITATIONS_HEADING)
    assert "What a write does not carry" in body
    assert "metadata" in body
