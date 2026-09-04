"""PDF-11 -- `text` and `tables` at the op layer, plus this spec's mechanized
honesty rails.

Everything here runs IN PROCESS. The subprocess-level contract (exit codes,
banner placement, `--help` greps) lives in
`tests/integration/test_text_tables_cli.py`; keeping the two apart is what stops
this spec from adding another twenty subprocess launches to the local gate
(B-061) for assertions that a direct call proves just as well.

Two conventions this module holds deliberately:

* **No exact-coordinate assertion, anywhere** (AC3). A test asserting a literal
  `x`/`y`/`width` value is itself a defect for this spec: those numbers are the
  layout engine's, they are not part of any contract this product makes, and an
  engine upgrade moving one is not a defect. The ORDERING invariant is asserted,
  because the tool imposes it; the coordinates themselves are asserted only for
  type and presence, including inside the goldens.
* **Every control here is proven able to fail.** Four controls in this cycle
  were found incapable of failing, so each grep-shaped guard below is paired
  with a red demonstration against a synthetic input.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_toolkit.cli.common import consumed_output_flags  # noqa: E402
from pdf_toolkit.errors import (  # noqa: E402
    EngineMissingError,
    NoInputError,
    PdfToolkitError,
    UsageError,
)
from pdf_toolkit.models import EngineReport  # noqa: E402
from pdf_toolkit.ops.textract import (  # noqa: E402
    extract_tables_run,
    extract_text_run,
    normalize_page_text,
    rows_to_csv_bytes,
    table_artifact_bytes,
    text_artifact_bytes,
)
from pdf_toolkit.safety.policy import SafetyPolicy  # noqa: E402

REPO_ROOT = TESTS_DIR.parent
SRC = REPO_ROOT / "src" / "pdf_toolkit"
GOLDEN_DIR = TESTS_DIR / "golden"

#: The five source files this spec created or filled in. AC7 greps exactly
#: these, plus every golden payload.
SPEC_SOURCES = (
    SRC / "ops" / "textract.py",
    SRC / "adapters" / "pdfium_text.py",
    SRC / "adapters" / "pdfplumber_text.py",
    SRC / "cli" / "cmd_text.py",
    SRC / "cli" / "cmd_tables.py",
)

#: The two Typer modules AC22's single-path guard is about.
CLI_MODULES = (SRC / "cli" / "cmd_text.py", SRC / "cli" / "cmd_tables.py")

#: AC7. Identifiers that must not appear -- a number claiming how sure the
#: engine was is worse than no number, and the prohibition is greppable rather
#: than reviewable. Matched on WORD BOUNDARIES, deliberately: a bare substring
#: scan flags ordinary English ("equality" contains one of these) and would then
#: fail a correct implementation, which is the unsatisfiable shape B-052
#: warns about. These are identifier names, so identifier matching is the
#: assertion that means what it says.
FORBIDDEN_IDENTIFIERS = (
    "confidence",
    "score",
    "accuracy",
    "probability",
    "certainty",
    "quality",
)
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(FORBIDDEN_IDENTIFIERS) + r")\b", re.IGNORECASE)

OUTPUT_FLAGS_CONSUMED = ("--output", "--out-dir", "--name")


def policy(**overrides: Any) -> SafetyPolicy:
    values: dict[str, Any] = {
        "dry_run": False,
        "force": False,
        "in_place": False,
        "backup": True,
        "assume_yes": False,
        "is_tty": False,
        "threads": 1,
    }
    values.update(overrides)
    return SafetyPolicy(**values)


def run_text(source: Path, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "pages_spec": None,
        "layout": False,
        "output": None,
        "out_dir": None,
        "name_template": None,
        "policy": policy(),
    }
    kwargs.update(overrides)
    return extract_text_run([source], **kwargs)


def run_tables(source: Path, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "pages_spec": None,
        "strategy": "lines",
        "fmt": None,
        "output": None,
        "out_dir": None,
        "name_template": None,
        "policy": policy(),
    }
    kwargs.update(overrides)
    return extract_tables_run([source], **kwargs)


# --------------------------------------------------------------------------- #
# Normalization (Design §3) -- a product behaviour, unit-tested as one
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a\r\nb", "a\nb"),
        ("a\rb", "a\nb"),
        ("a  \t\nb\t", "a\nb"),
        ("a\n\n\n", "a\n"),
        ("a", "a"),
        ("", ""),
        ("\n", "\n"),
        ("a\nb", "a\nb"),
    ],
)
def test_normalization_is_exactly_the_documented_rule(raw: str, expected: str) -> None:
    assert normalize_page_text(raw) == expected


def test_normalization_is_idempotent() -> None:
    for raw in ("a\r\n b \t\n\n\n", "x", "", "\r\n"):
        once = normalize_page_text(raw)
        assert normalize_page_text(once) == once


# --------------------------------------------------------------------------- #
# AC10 -- the CSV dialect, pinned at byte level
# --------------------------------------------------------------------------- #

AC10_GRID: tuple[tuple[str | None, ...], ...] = (
    ("a,b", 'he said "hi"', "line1\nline2"),
    (None, "", "x"),
)
AC10_EXPECTED = b'"a,b","he said ""hi""","line1\nline2"\n,,x\n'


def test_ac10_the_csv_dialect_is_pinned_at_byte_level() -> None:
    """The test that stops two implementations silently disagreeing: LF
    terminators, QUOTE_MINIMAL, doubled quotes, None -> the empty string, and a
    newline inside a cell preserved inside the quoted field."""
    assert rows_to_csv_bytes(AC10_GRID) == AC10_EXPECTED


def test_ac10_the_produced_csv_round_trips_through_a_reader() -> None:
    """Corroborating, never the evidence: the bytes above are the contract, and
    a standard reader must also agree about what they mean."""
    parsed = list(csv.reader(io.StringIO(AC10_EXPECTED.decode("utf-8"), newline="")))
    assert parsed == [["a,b", 'he said "hi"', "line1\nline2"], ["", "", "x"]]


def test_ac10_no_bom_and_no_cr_anywhere() -> None:
    produced = rows_to_csv_bytes(AC10_GRID)
    assert not produced.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in produced


def test_ac10_the_byte_assertion_is_able_to_fail() -> None:
    """The dialect check proven able to go red: CRLF is the realistic wrong
    answer (it is RFC 4180's own terminator), and it must NOT compare equal."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    for row in AC10_GRID:
        writer.writerow(["" if cell is None else cell for cell in row])
    assert buffer.getvalue().encode("utf-8") != AC10_EXPECTED


# --------------------------------------------------------------------------- #
# Artifact serialization
# --------------------------------------------------------------------------- #


def test_text_artifact_is_newline_terminated_and_empty_when_every_page_is_empty() -> None:
    assert text_artifact_bytes(["a", "b"]) == b"a\nb\n"
    assert text_artifact_bytes([""]) == b""
    assert text_artifact_bytes(["", ""]) == b""


def test_the_json_table_artifact_omits_path_and_carries_the_schema_version(corpus) -> None:
    outcome = run_tables(corpus.path("tabular"))
    payload = json.loads(table_artifact_bytes(outcome.tables[0], "json"))
    assert payload["schema_version"] == 1
    assert "path" not in payload
    assert payload["rows"] == [list(row) for row in corpus.spec("tabular").table]


# --------------------------------------------------------------------------- #
# AC1 -- the extracted text equals exactly what the generator wrote
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fixture", ["multipage_text", "single_page", "metadata_rich"])
def test_ac1_the_fast_path_returns_the_exact_strings_reportlab_wrote(corpus, fixture: str) -> None:
    spec = corpus.spec(fixture)
    outcome = run_text(corpus.path(fixture))
    assert outcome.strategy == "fast"
    assert [page.text for page in outcome.pages] == list(spec.page_texts)


@pytest.mark.parametrize("fixture", ["multipage_text", "single_page", "metadata_rich"])
def test_ac1_the_layout_path_returns_the_same_exact_strings(corpus, fixture: str) -> None:
    """The layout half of AC1: '\\n'.join(block.text for block in blocks) equals
    the same expected string, per page. An EQUALITY, never a contains-check --
    the fixture's ground truth is known by construction."""
    spec = corpus.spec(fixture)
    outcome = run_text(corpus.path(fixture), layout=True)
    assert outcome.strategy == "layout"
    joined = ["\n".join(block.text for block in (page.blocks or ())) for page in outcome.pages]
    assert joined == list(spec.page_texts)


def test_ac1_the_two_paths_agree_page_for_page(corpus) -> None:
    fast = run_text(corpus.path("multipage_text"))
    layout = run_text(corpus.path("multipage_text"), layout=True)
    assert [page.text for page in fast.pages] == [page.text for page in layout.pages]


def test_ac1_the_equality_assertion_is_able_to_fail(corpus) -> None:
    """The AC1 comparison proven able to discriminate before its zero is
    trusted: the same extraction against a DIFFERENT fixture's declared strings
    must not compare equal."""
    outcome = run_text(corpus.path("multipage_text"))
    other = corpus.spec("single_page").page_texts
    assert [page.text for page in outcome.pages] != list(other)


def test_char_count_is_the_length_of_the_page_text(corpus) -> None:
    for layout in (False, True):
        outcome = run_text(corpus.path("multipage_text"), layout=layout)
        assert [page.char_count for page in outcome.pages] == [
            len(page.text) for page in outcome.pages
        ]


# --------------------------------------------------------------------------- #
# AC3 -- blocks have NON-DECREASING y, and the order is imposed
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fixture", ["multipage_text", "rotated", "tabular"])
def test_ac3_block_y_is_non_decreasing_on_every_page(corpus, fixture: str) -> None:
    """Non-decreasing, not strictly increasing (Design §4): two blocks may
    legitimately share a `top` in a multi-column layout, and asserting strict
    increase would be asserting something the data cannot support."""
    outcome = run_text(corpus.path(fixture), layout=True)
    for page in outcome.pages:
        ys = [block.y for block in (page.blocks or ())]
        assert ys == sorted(ys), f"{fixture} page {page.page}: blocks are not ordered by y"


def test_ac3_block_indices_are_dense_and_start_at_zero(corpus) -> None:
    outcome = run_text(corpus.path("tabular"), layout=True)
    for page in outcome.pages:
        blocks = page.blocks or ()
        assert [block.index for block in blocks] == list(range(len(blocks)))


def test_ac3_the_ordering_is_imposed_by_the_tool_not_inherited(corpus) -> None:
    """The invariant is a GUARANTEE, not a property the engine happens to have:
    feeding the sorter deliberately reversed lines still yields non-decreasing
    y. This is what stops an engine upgrade turning the invariant red for a
    reason that is not a defect."""
    from pdf_toolkit.ops.textract import _blocks_from
    from pdf_toolkit.ports.text import TextLine

    scrambled = [
        TextLine(text="third", x0=10.0, top=300.0, x1=50.0, bottom=312.0),
        TextLine(text="first", x0=10.0, top=100.0, x1=50.0, bottom=112.0),
        TextLine(text="second-b", x0=200.0, top=200.0, x1=250.0, bottom=212.0),
        TextLine(text="second-a", x0=10.0, top=200.0, x1=50.0, bottom=212.0),
    ]
    blocks = _blocks_from(scrambled)
    ys = [block.y for block in blocks]
    assert ys == sorted(ys)
    assert [block.text for block in blocks] == ["first", "second-a", "second-b", "third"]


# --------------------------------------------------------------------------- #
# AC13 -- set page semantics
# --------------------------------------------------------------------------- #


def test_ac13_pages_are_a_sorted_deduplicated_set(corpus) -> None:
    outcome = run_text(corpus.path("multipage_text"), pages_spec="3,1,1")
    assert [page.page for page in outcome.pages] == [1, 3]


def test_ac13_tables_uses_the_same_set_semantics(corpus) -> None:
    outcome = run_tables(corpus.path("rotated"), pages_spec="3,1,1")
    # No tables on that fixture; the WARNINGS are what report the pages visited.
    assert len(outcome.result.warnings) == 2


def test_a_selection_resolving_to_zero_pages_is_exit_4(corpus) -> None:
    """Exit 4 ('nothing to act on') stays distinct from exit 0 with an empty
    result ('we acted and the honest answer is empty'). Collapsing the two is
    the defect family this verb's exit-code map exists to avoid."""
    with pytest.raises(NoInputError) as excinfo:
        run_text(corpus.path("multipage_text"), pages_spec="1,!1")
    assert excinfo.value.exit_code == 4


def test_a_nonexistent_input_is_exit_4_at_the_op_layer(tmp_path: Path) -> None:
    with pytest.raises(NoInputError) as excinfo:
        run_text(tmp_path / "nope.pdf")
    assert excinfo.value.exit_code == 4


def test_a_directory_operand_is_exit_2_at_the_op_layer(tmp_path: Path) -> None:
    with pytest.raises(UsageError) as excinfo:
        run_text(tmp_path)
    assert excinfo.value.exit_code == 2


def test_a_filename_template_without_a_destination_is_exit_2(corpus) -> None:
    """A template for a file nobody asked to write is a usage error, not a
    silently ignored flag -- B-035's own shape is 'documented flag not
    honoured', and quietly dropping this one would reproduce it."""
    for runner in (run_text, run_tables):
        with pytest.raises(UsageError) as excinfo:
            runner(corpus.path("tabular"), name_template="x-{stem}.{ext}")
        assert excinfo.value.exit_code == 2


# --------------------------------------------------------------------------- #
# AC5 -- no silent fallback. Exit 3, through the product's own error handler.
# --------------------------------------------------------------------------- #


def _unavailable_text_engine() -> EngineReport:
    return EngineReport(
        port="TextEngine",
        adapter="pdfplumber",
        available=False,
        version=None,
        kind="python-package",
        detail="forced unavailable by this test",
        hint="uv tool install --force pdf-tooling",
    )


def _run_cli_in_process(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    """Invoke the real console entry point in this process and return its exit
    status.

    An unresolvable engine cannot be produced in a SUBPROCESS without lying
    about the environment: `package_probe` answers "is it installed?" through
    `importlib.util.find_spec`, which a PATH or PYTHONPATH shim cannot make say
    no for a package that is genuinely installed. So this drives
    `cli.main.main()` directly -- the same function the console script calls,
    including its one `except PdfToolkitError` handler and the `SystemExit` it
    raises -- with the port registry's memo replaced. The exit STATUS is
    therefore the product's own, not a re-derivation of it.
    """
    import pdf_toolkit.ports as ports
    from pdf_toolkit.cli.common import reset_error_format
    from pdf_toolkit.cli.main import main

    monkeypatch.setattr(ports, "_CACHE", {"TextEngine": _unavailable_text_engine()})
    monkeypatch.setattr(sys, "argv", ["pdftoolkit", *argv])
    reset_error_format()
    with pytest.raises(SystemExit) as excinfo:
        main()
    code = excinfo.value.code
    return int(code) if code is not None else 0


def test_ac5_layout_with_the_adapter_unresolved_exits_3_and_never_falls_back(
    corpus, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = str(corpus.path("multipage_text"))
    code = _run_cli_in_process(monkeypatch, ["text", source, "--layout", "-o", "table"])
    captured = capsys.readouterr()

    assert code == 3
    assert "uv tool install --force pdf-tooling" in captured.err
    assert "pdftoolkit doctor" in captured.err
    # No extracted text, and no payload claiming the layout strategy ran.
    assert captured.out == ""
    assert "strategy: layout" not in captured.err
    assert "multipage_text fixture" not in captured.out + captured.err


def test_ac5_the_fast_path_with_the_port_unresolved_exits_3_not_a_traceback(
    corpus, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = str(corpus.path("multipage_text"))
    code = _run_cli_in_process(monkeypatch, ["text", source, "-o", "table"])
    captured = capsys.readouterr()
    assert code == 3
    assert "Traceback" not in captured.err
    assert "ImportError" not in captured.err
    assert captured.out == ""


def test_ac5_tables_with_the_port_unresolved_exits_3(
    corpus, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = str(corpus.path("tabular"))
    code = _run_cli_in_process(monkeypatch, ["tables", source, "-o", "table"])
    captured = capsys.readouterr()
    assert code == 3
    assert captured.out == ""


def test_ac5_the_port_itself_raises_the_coded_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The refusal is the PORT's, not a per-verb check: with the memo replaced,
    the three `require_*` helpers all raise the same coded error."""
    import pdf_toolkit.ports as ports
    from pdf_toolkit.ports.text import require_fast_text, require_layout_text, require_tables

    monkeypatch.setattr(ports, "_CACHE", {"TextEngine": _unavailable_text_engine()})
    for require in (require_fast_text, require_layout_text, require_tables):
        with pytest.raises(EngineMissingError) as excinfo:
            require()
        assert excinfo.value.exit_code == 3


def test_ac5_the_unresolved_control_is_able_to_go_green(corpus) -> None:
    """The other half of the control: without the monkeypatch the same
    invocation must succeed, so a 3 above is the injection and not an ambient
    broken installation."""
    outcome = run_text(corpus.path("multipage_text"), layout=True)
    assert outcome.result.exit_code == 0


# --------------------------------------------------------------------------- #
# AC7 -- no invented number, mechanized
# --------------------------------------------------------------------------- #


def _forbidden_hits(text: str) -> list[str]:
    return [match.group(0) for match in _FORBIDDEN_RE.finditer(text)]


@pytest.mark.parametrize("path", SPEC_SOURCES, ids=lambda p: p.name)
def test_ac7_no_source_file_of_this_spec_invents_a_number(path: Path) -> None:
    hits = _forbidden_hits(path.read_text())
    assert hits == [], (
        f"{path.relative_to(REPO_ROOT)} names {sorted(set(hits))} -- this spec attaches no "
        "number claiming how sure the engine was, to a table, a cell or a block "
        "(PLAN.md §12 R-03). A fabricated number is worse than no number."
    )


def test_ac7_no_golden_payload_invents_a_number() -> None:
    goldens = sorted(GOLDEN_DIR.glob("*.json"))
    assert goldens, "no golden payloads to scan -- this check would be vacuous"
    for golden in goldens:
        assert _forbidden_hits(golden.read_text()) == [], golden.name


def test_ac7_the_grep_is_able_to_fail() -> None:
    """Proven able to go red, and proven NOT to fire on ordinary English -- a
    substring scan would flag 'equality' and then fail a correct
    implementation, which is the unsatisfiable shape B-052 warns about."""
    assert _forbidden_hits('payload["confidence"] = 0.9') == ["confidence"]
    assert _forbidden_hits("row_count") == []
    assert _forbidden_hits("a meaningful equality rather than a brittle one") == []


# --------------------------------------------------------------------------- #
# AC22 -- OR-3 declared once, consumed, and never re-implemented
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "module", ["pdf_toolkit.cli.cmd_text", "pdf_toolkit.cli.cmd_tables"], ids=["text", "tables"]
)
def test_ac22_both_verbs_declare_exactly_the_three_destination_flags(module: str) -> None:
    __import__(module)
    assert consumed_output_flags(module) == OUTPUT_FLAGS_CONSUMED


def _decorator_line(source: str) -> str:
    lines = [line for line in source.splitlines() if line.startswith("@global_options(consumes=")]
    assert len(lines) == 1, "expected exactly one OR-3 declaration in the module"
    return lines[0]


@pytest.mark.parametrize("path", CLI_MODULES, ids=lambda p: p.name)
def test_ac22_each_declared_flag_appears_exactly_once_on_the_decorator_line(path: Path) -> None:
    """The single-path guard in its SATISFIABLE form (B-052): 'appears exactly
    once, on the decorator line' -- never 'does not appear', which no correct
    implementation could satisfy, since the declaration itself names them.

    What this actually proves is that neither module re-implements the OR-3
    refusal. A duplicate check inside a command module is a defect *even when it
    agrees*, because it is the path that can later disagree with the shared one.
    """
    source = path.read_text()
    decorator = _decorator_line(source)
    for flag in OUTPUT_FLAGS_CONSUMED:
        assert source.count(flag) == 1, (
            f"{path.name} names {flag} {source.count(flag)} times; it belongs on the "
            "@global_options(consumes=...) line and nowhere else"
        )
        assert flag in decorator, f"{path.name}'s only mention of {flag} is not the declaration"


@pytest.mark.parametrize("path", CLI_MODULES, ids=lambda p: p.name)
def test_ac22_in_place_appears_nowhere_in_either_command_module(path: Path) -> None:
    """`--in-place` is refused BY THE DECLARATION -- by not being in it. A
    per-verb `if in_place: exit(2)` is exactly the enforcement-by-omission shape
    OR-3 exists to abolish."""
    assert "--in-place" not in path.read_text()


def test_ac22_the_single_path_guard_is_able_to_fail() -> None:
    """Both halves proven able to go red against synthetic module text."""
    planted_second_mention = (
        '@global_options(consumes=("--output", "--out-dir", "--name"))\n'
        "def verb():\n"
        '    if out_dir is None: raise UsageError("--out-dir is required")\n'
    )
    assert planted_second_mention.count("--out-dir") == 2
    planted_in_place = "if config.in_place:\n    raise UsageError('--in-place is not accepted')\n"
    assert "--in-place" in planted_in_place


def test_ac22_the_verbs_are_discovered_with_their_declaration_attached() -> None:
    """AC17/AC23's own precondition, read off the LIVE tree rather than a list."""
    from registry import INVOCATIONS, OUTPUT_FLAG_INVOCATIONS, discover_verbs

    verbs = {verb.name: verb for verb in discover_verbs()}
    for name in ("text", "tables"):
        assert name in verbs, f"{name} is not on the live CLI tree"
        assert verbs[name].consumes == OUTPUT_FLAGS_CONSUMED
        assert verbs[name].is_mutating, f"{name} must reach the write chokepoint"
        assert name in INVOCATIONS, f"{name} has no tests/registry.py::INVOCATIONS row"
        for flag in OUTPUT_FLAGS_CONSUMED:
            assert (name, flag) in OUTPUT_FLAG_INVOCATIONS, f"missing OR-3 row for {name} {flag}"


# --------------------------------------------------------------------------- #
# AC19 -- the licence gate, over this spec's own files
# --------------------------------------------------------------------------- #


def test_ac19_no_forbidden_engine_name_appears_in_this_spec_s_files() -> None:
    """HC-1 restated over exactly the files this spec wrote. The realistic
    violation on this verb is a convenience shell-out for text extraction, not
    a declared dependency -- pypdfium2 IS the fast path, and there is no second
    route to the same answer anywhere on this call graph."""
    from test_cli_spine import FORBIDDEN_NAMES

    offenders = []
    for path in SPEC_SOURCES:
        lowered = path.read_text().lower()
        offenders.extend(f"{path.name}: {name}" for name in FORBIDDEN_NAMES if name in lowered)
    assert offenders == []


def test_ac19_that_scan_is_able_to_fail() -> None:
    from test_cli_spine import FORBIDDEN_NAMES

    planted = "subprocess.run([" + '"pdf' + 'totext", path])'
    assert [name for name in FORBIDDEN_NAMES if name in planted.lower()] != []


# --------------------------------------------------------------------------- #
# AC9 -- the cell grid, at the op layer (the CLI/CSV half is the integration
# module's). Ground truth is `tests/corpus.py`'s own declared TABLE_GRID.
# --------------------------------------------------------------------------- #


def test_ac9_the_lines_strategy_reproduces_the_fixture_grid_exactly(corpus) -> None:
    outcome = run_tables(corpus.path("tabular"))
    assert outcome.strategy == "lines"
    assert len(outcome.tables) == 1
    assert outcome.tables[0].rows == corpus.spec("tabular").table


def test_the_text_strategy_is_reported_as_the_strategy_that_ran(corpus) -> None:
    """The strategy is a fact about the code path taken. The two heuristics may
    legitimately disagree about the grid -- what may never differ is the label."""
    outcome = run_tables(corpus.path("tabular"), strategy="text")
    assert outcome.strategy == "text"
    assert outcome.tables, "the text strategy found nothing on the ruled fixture"


def test_zero_tables_is_exit_0_with_a_warning_naming_the_strategy(corpus) -> None:
    outcome = run_tables(corpus.path("multipage_text"))
    assert outcome.result.exit_code == 0
    assert outcome.tables == ()
    assert len(outcome.result.warnings) == 3
    assert all("heuristic" in warning for warning in outcome.result.warnings)


def test_an_unknown_strategy_is_refused_at_the_op_layer_too(corpus) -> None:
    with pytest.raises(UsageError):
        run_tables(corpus.path("tabular"), strategy="auto")


# --------------------------------------------------------------------------- #
# The pdfplumber adapter's own plain-text method (the Protocol's shared half)
# --------------------------------------------------------------------------- #


def test_the_layout_adapter_also_implements_plain_text_extraction(corpus) -> None:
    from pdf_toolkit.ports.text import require_layout_text

    engine = require_layout_text()
    spec = corpus.spec("multipage_text")
    extracted = engine.extract_text(str(corpus.path("multipage_text")), (1, 2, 3))
    assert [normalize_page_text(text) for text in extracted] == list(spec.page_texts)


def test_an_unreadable_input_is_a_coded_failure_not_a_raw_engine_error(tmp_path: Path) -> None:
    from pdf_toolkit.ports.text import require_layout_text

    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf at all")
    with pytest.raises(PdfToolkitError) as excinfo:
        require_layout_text().extract_text(str(broken), (1,))
    assert excinfo.value.exit_code == 1


# --------------------------------------------------------------------------- #
# AC16 -- goldens, compared as parsed dicts
#
# Coordinates are canonicalized to a TYPE MARKER rather than pinned: AC3 forbids
# an exact-coordinate assertion anywhere in this suite, and a golden carrying
# literal x/y/width values would be one -- with the added property that an
# engine upgrade moving a bounding box by a hundredth of a point would turn it
# red for something that is not a defect. The engine VERSION is canonicalized
# for the same reason: it is a fact about the host, not about the document.
# What the goldens do pin is the whole published schema plus every value that is
# a property of the document: the text, the grid, the ordering, the counts.
# --------------------------------------------------------------------------- #

_GEOMETRY_KEYS = ("x", "y", "width", "height")
_PATH_KEYS = ("source", "input", "output", "path")


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in _GEOMETRY_KEYS and isinstance(item, int | float):
                out[key] = "<float>"
            elif key == "bbox" and isinstance(item, list):
                out[key] = ["<float>"] * len(item)
            elif key in _PATH_KEYS and isinstance(item, str):
                out[key] = Path(item).name
            elif key == "version":
                out[key] = "<version>"
            else:
                out[key] = _canonical(item)
        return out
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def test_ac16_the_text_layout_golden(corpus, golden) -> None:
    from pdf_toolkit.cli.cmd_text import build_payload

    outcome = run_text(corpus.path("multipage_text"), layout=True)
    golden.compare("text_layout", _canonical(build_payload(outcome)))


def test_ac16_the_tables_golden(corpus, golden, tmp_path: Path) -> None:
    from pdf_toolkit.cli.cmd_tables import build_payload

    outcome = run_tables(corpus.path("tabular"), out_dir=tmp_path / "grids")
    golden.compare("tables_lines", _canonical(build_payload(outcome)))


def test_ac16_the_canonicalizer_still_pins_everything_that_is_not_geometry() -> None:
    """The canonicalization proven not to have gutted the golden: it replaces
    geometry, paths and the engine version, and nothing else."""
    payload = {
        "x": 1.5,
        "bbox": [1.0, 2.0, 3.0, 4.0],
        "source": "/tmp/x/y.pdf",
        "engine": {"adapter": "pdfplumber", "version": "0.11.10"},
        "rows": [["R1C1", None]],
        "row_count": 3,
        "text": "exact",
    }
    assert _canonical(payload) == {
        "x": "<float>",
        "bbox": ["<float>"] * 4,
        "source": "y.pdf",
        "engine": {"adapter": "pdfplumber", "version": "<version>"},
        "rows": [["R1C1", None]],
        "row_count": 3,
        "text": "exact",
    }
