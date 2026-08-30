"""PDF-11 -- `text` and `tables` as real processes.

Only the assertions that a direct call CANNOT make live here: exit codes, which
stream a line landed on, `--help` content, and the byte-identity of stdout. The
op-layer behaviour is proven in `tests/unit/test_textract.py`, in process, which
is what keeps this module's subprocess count (and therefore the local gate,
B-061) proportionate to what actually needs a process.

Note on cost, stated rather than hidden: registering two verbs also grows the
registry-parameterized contract harness by 8 C14 cases and 4 C15 cases, and
those are subprocess runs too. That growth is inherent to a matrix whose whole
value is that it covers a new verb with no action from its author.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from registry import run_cli  # noqa: E402

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def text_help() -> str:
    result = run_cli("text", "--help")
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture(scope="module")
def tables_help() -> str:
    result = run_cli("tables", "--help")
    assert result.returncode == 0, result.stderr
    return result.stdout


# --------------------------------------------------------------------------- #
# AC4 / AC8 / AC13 / AC18 -- documentation, mechanized as greps over --help
# --------------------------------------------------------------------------- #


def test_ac4_the_origin_convention_is_documented_and_greppable(text_help: str) -> None:
    lowered = text_help.lower()
    assert "top-left" in lowered
    assert "increas" in lowered
    assert "downward" in lowered


def test_ac8_the_heuristic_disclosure_is_mechanized(tables_help: str) -> None:
    assert "heuristic" in tables_help.lower()


def test_ac8_tables_help_distinguishes_the_text_strategy_from_the_text_verb(
    tables_help: str,
) -> None:
    """The two vocabularies read confusingly close together, so the distinction
    is a sentence in the help text rather than something a user has to infer."""
    lowered = tables_help.lower()
    assert "unrelated to the 'text' verb" in lowered
    assert "whitespace-alignment" in lowered


def test_ac8_tables_help_states_the_csv_provenance_limitation(tables_help: str) -> None:
    lowered = tables_help.lower()
    assert "cannot carry provenance" in lowered
    assert "no header row" in lowered
    assert "lf line terminators" in lowered


@pytest.mark.parametrize("which", ["text", "tables"])
def test_ac13_both_help_texts_state_the_set_semantics_difference(
    which: str, text_help: str, tables_help: str
) -> None:
    help_text = text_help if which == "text" else tables_help
    assert "SET" in help_text
    assert "sorted, deduplicated" in help_text


@pytest.mark.parametrize("which", ["text", "tables"])
def test_ac18_both_help_texts_declare_the_threads_no_op(
    which: str, text_help: str, tables_help: str
) -> None:
    help_text = text_help if which == "text" else tables_help
    assert "--threads is accepted but has NO effect" in help_text
    assert "sequentially" in help_text


@pytest.mark.parametrize("which", ["text", "tables"])
def test_both_help_texts_name_the_port_they_depend_on(
    which: str, text_help: str, tables_help: str
) -> None:
    help_text = text_help if which == "text" else tables_help
    assert "TextEngine" in help_text


@pytest.mark.parametrize("which", ["text", "tables"])
def test_no_help_text_names_a_forbidden_tool(which: str, text_help: str, tables_help: str) -> None:
    """The prohibition and the advertisement look identical to a grep, and this
    spec's default path reproduces a forbidden tool's whole reason for existing.
    So the capability is described and the tool is never named."""
    from test_cli_spine import FORBIDDEN_NAMES

    lowered = (text_help if which == "text" else tables_help).lower()
    assert [name for name in FORBIDDEN_NAMES if name in lowered] == []


# --------------------------------------------------------------------------- #
# AC2 -- the strategy is declared, always, on every shape
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (("text", "{multipage_text}"), "fast"),
        (("text", "{multipage_text}", "--layout"), "layout"),
        (("tables", "{tabular}"), "lines"),
        (("tables", "{tabular}", "--strategy", "text"), "text"),
    ],
    ids=["text-fast", "text-layout", "tables-lines", "tables-text"],
)
def test_ac2_json_always_declares_the_strategy_and_the_engine(
    corpus, argv: tuple[str, ...], expected: str
) -> None:
    resolved = [
        str(corpus.path(part.strip("{}"))) if part.startswith("{") else part for part in argv
    ]
    result = run_cli(*resolved, "-o", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["strategy"] == expected
    assert payload["engine"]["adapter"]
    assert payload["engine"]["version"], "a version this product prints is one it actually read"


@pytest.mark.parametrize("verb", ["text", "tables"])
def test_ac2_every_ndjson_line_carries_the_strategy(corpus, verb: str) -> None:
    """A consumer reading ONE streamed line must not have to have seen line 1."""
    fixture = "multipage_text" if verb == "text" else "tabular"
    result = run_cli(verb, str(corpus.path(fixture)), "-o", "ndjson")
    assert result.returncode == 0, result.stderr
    lines = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert lines, "ndjson produced no records"
    for record in lines:
        assert record["strategy"]
        assert record["engine"]["adapter"]
        assert record["schema_version"] == 1


@pytest.mark.parametrize("verb", ["text", "tables"])
def test_ac2_the_banner_is_on_stdout_when_a_destination_was_given(
    corpus, verb: str, tmp_path: Path
) -> None:
    fixture = "multipage_text" if verb == "text" else "tabular"
    result = run_cli(
        verb, str(corpus.path(fixture)), "--out-dir", str(tmp_path / "out"), "-o", "table"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0].startswith("strategy: ")
    assert "strategy: " not in result.stderr


@pytest.mark.parametrize("verb", ["text", "tables"])
def test_ac2_the_banner_is_on_stderr_when_the_payload_goes_to_stdout(corpus, verb: str) -> None:
    """The banner is a diagnostic about HOW the result was produced, so when
    stdout is carrying the result itself the banner belongs on stderr -- stdout
    stays pipe-clean."""
    fixture = "multipage_text" if verb == "text" else "tabular"
    result = run_cli(verb, str(corpus.path(fixture)), "-o", "table")
    assert result.returncode == 0, result.stderr
    assert result.stderr.splitlines()[0].startswith("strategy: ")
    assert not result.stdout.startswith("strategy: ")


def test_ac2_table_mode_without_a_destination_puts_the_text_itself_on_stdout(corpus) -> None:
    spec = corpus.spec("multipage_text")
    result = run_cli("text", str(corpus.path("multipage_text")), "-o", "table")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "\n".join(spec.page_texts) + "\n"


# --------------------------------------------------------------------------- #
# AC6 -- an unknown value is REJECTED, never ignored
# --------------------------------------------------------------------------- #


def test_ac6_strategy_auto_is_rejected_and_names_both_valid_values(corpus) -> None:
    """A silently-ignored unknown strategy is precisely the R-03 failure this
    verb exists to avoid; '--strategy auto' is Phase 2 and is not accepted now."""
    result = run_cli("tables", str(corpus.path("tabular")), "--strategy", "auto")
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "lines" in combined
    assert "text" in combined


def test_ac6_an_unknown_format_is_rejected(corpus) -> None:
    result = run_cli("tables", str(corpus.path("tabular")), "--format", "xlsx")
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "csv" in combined
    assert "json" in combined


# --------------------------------------------------------------------------- #
# AC9 -- `tables --format csv` reproduces the fixture's cell grid exactly
# --------------------------------------------------------------------------- #


def test_ac9_csv_artifacts_reproduce_the_declared_cell_grid(corpus, tmp_path: Path) -> None:
    """Compared as PARSED rows, so quoting style can never cause a false
    failure, against `tests/corpus.py`'s own declared grid rather than a literal
    repeated here."""
    out_dir = tmp_path / "grids"
    result = run_cli(
        "tables", str(corpus.path("tabular")), "--format", "csv", "--out-dir", str(out_dir)
    )
    assert result.returncode == 0, result.stderr

    written = sorted(out_dir.iterdir())
    assert len(written) == 1, [path.name for path in written]
    with written[0].open(newline="") as handle:
        parsed = [tuple(row) for row in csv.reader(handle)]
    assert tuple(parsed) == corpus.spec("tabular").table


# --------------------------------------------------------------------------- #
# AC11 -- `-O` and the collision path
# --------------------------------------------------------------------------- #


def test_ac11_output_accepts_exactly_one_table(corpus, tmp_path: Path) -> None:
    target = tmp_path / "one.csv"
    result = run_cli("tables", str(corpus.path("tabular")), "-O", str(target))
    assert result.returncode == 0, result.stderr
    assert target.is_file()


def test_ac11_two_or_more_tables_onto_one_path_is_a_collision(corpus, tmp_path: Path) -> None:
    """Exit 5 (collision), NOT exit 2 (OR-3): `tables` does declare `-O`. The
    two refusal paths must stay distinct, and this is what proves they are."""
    target = tmp_path / "one.csv"
    source = str(corpus.path("tabular"))
    result = run_cli("tables", source, source, "-O", str(target))
    assert result.returncode == 5, result.stdout + result.stderr
    assert "one destination" in result.stdout + result.stderr
    assert not target.exists()


def test_ac11_two_inputs_onto_one_text_file_is_a_collision(corpus, tmp_path: Path) -> None:
    target = tmp_path / "one.txt"
    result = run_cli(
        "text",
        str(corpus.path("multipage_text")),
        str(corpus.path("single_page")),
        "-O",
        str(target),
    )
    assert result.returncode == 5, result.stdout + result.stderr
    assert not target.exists()


# --------------------------------------------------------------------------- #
# AC12 -- `--format` with nowhere to write warns and continues
# --------------------------------------------------------------------------- #


def test_ac12_format_without_a_destination_warns_and_exits_0(corpus, tmp_path: Path) -> None:
    before = set(tmp_path.rglob("*"))
    result = run_cli(
        "tables", str(corpus.path("tabular")), "--format", "csv", "-o", "json", cwd=tmp_path
    )
    assert result.returncode == 0, result.stderr
    assert "--format only affects files written with --out-dir/-O" in result.stderr
    assert "stdout follows -o" in result.stderr
    assert set(tmp_path.rglob("*")) == before, "a warning must not have written anything"


# --------------------------------------------------------------------------- #
# AC18 -- `--threads` is a DECLARED no-op, not a silent one
# --------------------------------------------------------------------------- #


def test_ac18_threads_1_and_threads_8_produce_byte_identical_stdout(corpus) -> None:
    sources = [
        str(corpus.path("multipage_text")),
        str(corpus.path("single_page")),
        str(corpus.path("metadata_rich")),
    ]
    one = run_cli("text", *sources, "--threads", "1", "-o", "json")
    eight = run_cli("text", *sources, "--threads", "8", "-o", "json")
    assert one.returncode == eight.returncode == 0, one.stderr + eight.stderr
    assert one.stdout == eight.stdout

    payload = json.loads(one.stdout)
    assert [item["input"] for item in payload["items"]] == sources, (
        "inputs are processed sequentially, in the order they appear on the command line"
    )


# --------------------------------------------------------------------------- #
# AC22 -- the OR-3 refusal, live, and its ORDERING against mutual exclusion
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", ["text", "tables"])
def test_ac22_in_place_is_refused_by_the_declaration_naming_verb_and_flag(
    corpus, verb: str, tmp_path: Path
) -> None:
    fixture = "multipage_text" if verb == "text" else "tabular"
    before = set(tmp_path.rglob("*"))
    result = run_cli(verb, str(corpus.path(fixture)), "--in-place", cwd=tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert verb in combined
    assert "--in-place" in combined
    assert set(tmp_path.rglob("*")) == before


def test_ac22_ordering_mutual_exclusion_wins_over_the_or3_message(corpus, tmp_path: Path) -> None:
    """Proven rather than assumed (the PDF-10 AC22 precedent): `-O` together
    with `--out-dir` is a verb-independent contradiction and must report THAT,
    while a bare undeclared flag reports the OR-3 message. Both exit 2, so only
    the message tells them apart."""
    both = run_cli(
        "text",
        str(corpus.path("multipage_text")),
        "-O",
        str(tmp_path / "o.txt"),
        "--out-dir",
        str(tmp_path / "d"),
    )
    assert both.returncode == 2
    assert "mutually exclusive" in both.stdout + both.stderr

    or3 = run_cli("text", str(corpus.path("multipage_text")), "--in-place")
    assert or3.returncode == 2
    assert "does not accept" in or3.stdout + or3.stderr
    assert "mutually exclusive" not in or3.stdout + or3.stderr


# --------------------------------------------------------------------------- #
# AC24 -- X-67: the dry run PREDICTS the refusal, through the SHARED path
#
# This criterion asserts the PREDICTION and deliberately does NOT assert the dry
# run's own process exit code -- that question is B-025, it is unsettled, and it
# is the operator's. The observed codes are measured and recorded in the
# Implementation Log instead. Contract row C15 separately asserts the exit-code
# equality these verbs inherit from the shared path.
# --------------------------------------------------------------------------- #


def _dry_and_real(verb: str, args: list[str], cwd: Path):
    dry = run_cli(verb, "--dry-run", *args, "-o", "json", cwd=cwd)
    real = run_cli(verb, *args, "-o", "json", cwd=cwd)
    return dry, real


def _prediction(dry_stdout: str) -> dict:
    payload = json.loads(dry_stdout)
    details = [item.get("detail") or {} for item in payload["items"]]
    assert details, "the dry run produced no items to carry a prediction"
    return details[0]


@pytest.mark.parametrize("verb", ["text", "tables"])
def test_ac24_a_dry_run_predicts_an_occupied_target_refusal(
    corpus, verb: str, tmp_path: Path
) -> None:
    fixture = "multipage_text" if verb == "text" else "tabular"
    out_dir = tmp_path / "occupied"
    out_dir.mkdir()
    occupied = out_dir / ("multipage_text.txt" if verb == "text" else "tabular-p001-t0.csv")
    seed = b"AC24-SEEDED-BYTES"
    occupied.write_bytes(seed)

    args = [str(corpus.path(fixture)), "--out-dir", str(out_dir)]
    dry, real = _dry_and_real(verb, args, tmp_path)

    prediction = _prediction(dry.stdout)
    assert prediction["would_exit"] == real.returncode
    # The predicted payload IS the real run's own structured error, so a caller
    # comparing a prediction against an outcome compares like with like.
    assert prediction["would_refuse"] == json.loads(real.stdout)["error"]
    assert occupied.read_bytes() == seed, "the dry run mutated the occupied target"


@pytest.mark.parametrize("verb", ["text", "tables"])
def test_ac24_a_dry_run_predicts_an_unwritable_destination_refusal(
    corpus, verb: str, tmp_path: Path
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignores directory mode bits; this arm cannot fire as root")

    fixture = "multipage_text" if verb == "text" else "tabular"
    out_dir = tmp_path / "locked"
    out_dir.mkdir()
    args = [str(corpus.path(fixture)), "--out-dir", str(out_dir)]

    out_dir.chmod(0o500)
    try:
        dry, real = _dry_and_real(verb, args, tmp_path)
    finally:
        out_dir.chmod(0o700)

    prediction = _prediction(dry.stdout)
    assert prediction["would_exit"] == real.returncode
    assert prediction["would_refuse"] == json.loads(real.stdout)["error"]
    assert list(out_dir.iterdir()) == [], "neither run may have written into a locked directory"


def test_ac24_a_clean_dry_run_predicts_success_and_creates_nothing(corpus, tmp_path: Path) -> None:
    """The other half of the control: a prediction that is always a refusal
    would be a control that cannot discriminate."""
    out_dir = tmp_path / "brand-new"
    result = run_cli(
        "text",
        "--dry-run",
        str(corpus.path("multipage_text")),
        "--out-dir",
        str(out_dir),
        "-o",
        "json",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    prediction = _prediction(result.stdout)
    assert prediction == {"would_exit": 0}
    assert not out_dir.exists(), "--dry-run created the destination directory"
