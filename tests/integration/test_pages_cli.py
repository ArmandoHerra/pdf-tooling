"""PDF-08 at the subprocess level — exit codes, `--in-place` and the `.bak`
sidecar, the non-TTY posture, `--dry-run` prediction, containment, and the one
error-rendering chokepoint.

This is the first spec in the cycle where a **user** can reach `--in-place`,
`--no-backup`, the `.bak` sidecar or the non-TTY `-y` gate against a real verb:
PDF-04 built all of them against no callers. Their contract is therefore
re-asserted here against live verbs — exercised, never re-implemented.

Everything below runs the real CLI in a real process. A `SafetyPolicy`
constructed in-process cannot observe the non-TTY branch, which is the branch
that matters: a tool that prompts inside a cron job hangs a pipeline until an
unrelated timeout fires, and the operator sees "stuck", not "declined".
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from fs_snapshot import assert_unchanged, redirected_environment, snapshot  # noqa: E402
from pdfium_text import page_texts  # noqa: E402
from registry import run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

FIXTURE = "ten_page_text"
VERBS = ("extract", "delete", "rotate", "reorder")
#: The three verbs that declare `--in-place`. `extract` is deliberately absent:
#: it derives a different page set from its input, so "mutate the input" has no
#: meaning there, and its refusal is produced by the OR-3 declaration alone.
IN_PLACE_VERBS = ("delete", "rotate", "reorder")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy(corpus, tmp_path: Path, name: str = FIXTURE, filename: str = "work.pdf") -> Path:
    """A `tmp_path`-local COPY -- never the session-scoped corpus fixture
    itself, which an `--in-place` run would silently corrupt for every
    downstream test that reuses it."""
    destination = tmp_path / filename
    shutil.copy(corpus.path(name), destination)
    return destination


def _selection_args(verb: str) -> list[str]:
    """A valid, non-refusing selection tail for each verb (plus `--angle` for
    `rotate`, which a generic harness cannot know it needs)."""
    if verb == "rotate":
        return ["--pages", "1", "--angle", "90"]
    if verb == "reorder":
        return ["--pages", "last,1"]
    return ["--pages", "1"]


def _page_numbers(path: Path) -> list[int]:
    numbers: list[int] = []
    for text in page_texts(path):
        match = re.search(r"page (\d+) of 10", text)
        assert match is not None, f"unexpected page text: {text!r}"
        numbers.append(int(match.group(1)))
    return numbers


def _rotations(path: Path) -> list[int | None]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return [(page.get("/Rotate") if "/Rotate" in page else None) for page in reader.pages]


# --------------------------------------------------------------------------- #
# AC10 -- help text, mechanized (also asserted in tests/unit/test_verb_help_
# content.py, the shared append-only home; kept here too because the Validation
# block runs these as one-liners)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("verb", "phrase"),
    [
        ("extract", "order and duplicates are preserved"),
        ("reorder", "order and duplicates are preserved"),
        ("reorder", "pages you do not name are appended"),
        ("delete", "sorted, deduplicated set"),
        ("rotate", "sorted, deduplicated set"),
    ],
)
def test_ac10_each_verb_states_its_own_semantics_in_help(verb: str, phrase: str) -> None:
    result = run_cli(verb, "--help")
    assert result.returncode == 0
    # `--help` hard-wraps; compare on collapsed whitespace so the assertion is
    # about the sentence, not about the terminal width it was rendered at.
    assert phrase in " ".join(result.stdout.split())


# --------------------------------------------------------------------------- #
# AC12/AC13/AC16 -- exit codes at the CLI boundary
# --------------------------------------------------------------------------- #


def test_ac12_delete_all_refuses_and_writes_nothing(corpus, tmp_path: Path) -> None:
    target = tmp_path / "out.pdf"
    result = run_cli(
        "delete", str(corpus.path(FIXTURE)), "--pages", "all", "-O", str(target), cwd=tmp_path
    )
    assert result.returncode == 5
    assert not target.exists()
    assert "zero-page" in result.stdout + result.stderr


def test_ac12_delete_all_in_place_leaves_the_input_byte_identical(corpus, tmp_path: Path) -> None:
    source = _copy(corpus, tmp_path)
    before = _sha256(source)
    result = run_cli("delete", str(source), "--pages", "all", "--in-place", cwd=tmp_path)
    assert result.returncode == 5
    assert _sha256(source) == before
    assert not (tmp_path / "work.pdf.bak").exists(), "a refused run created a .bak"


@pytest.mark.parametrize(
    ("argv_tail", "expected"),
    [
        (["--pages", "all,!all"], 4),
        (["--pages", "1-10"], 5),
        (["--pages", "all"], 5),
    ],
)
def test_ac13_the_two_empty_cases_stay_distinct(
    argv_tail: list[str], expected: int, corpus, tmp_path: Path
) -> None:
    result = run_cli(
        "delete",
        str(corpus.path(FIXTURE)),
        *argv_tail,
        "-O",
        str(tmp_path / "o.pdf"),
        cwd=tmp_path,
    )
    assert result.returncode == expected


def test_ac13_an_empty_extract_selection_is_exit_4(corpus, tmp_path: Path) -> None:
    result = run_cli(
        "extract",
        str(corpus.path("single_page")),
        "--pages",
        "even",
        "-O",
        str(tmp_path / "o.pdf"),
        cwd=tmp_path,
    )
    assert result.returncode == 4


def test_ac16_an_out_of_set_angle_is_refused_naming_the_accepted_set(
    corpus, tmp_path: Path
) -> None:
    result = run_cli(
        "rotate",
        str(corpus.path(FIXTURE)),
        "--pages",
        "1",
        "--angle",
        "45",
        "-O",
        str(tmp_path / "o.pdf"),
        cwd=tmp_path,
    )
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    for value in ("90", "180", "270", "-90"):
        assert value in combined, f"the refusal does not name {value}"


def test_ac16_a_missing_angle_is_refused(corpus, tmp_path: Path) -> None:
    result = run_cli(
        "rotate",
        str(corpus.path(FIXTURE)),
        "--pages",
        "1",
        "-O",
        str(tmp_path / "o.pdf"),
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert "--angle" in result.stdout + result.stderr


def test_ac16_neither_angle_refusal_opens_the_document(tmp_path: Path) -> None:
    """ "Neither opens the document" made observable: a file that is not a PDF
    at all still produces the angle refusal, which it could not do if the
    document had been parsed first."""
    not_a_pdf = tmp_path / "not-a-pdf.pdf"
    not_a_pdf.write_bytes(b"this is not a PDF at all")
    for tail in (["--angle", "45"], []):
        result = run_cli(
            "rotate",
            str(not_a_pdf),
            "--pages",
            "1",
            *tail,
            "-O",
            str(tmp_path / "o.pdf"),
            cwd=tmp_path,
        )
        assert result.returncode == 2, result.stdout + result.stderr


# --------------------------------------------------------------------------- #
# AC17/AC18/AC20/AC21 -- `--in-place` and the `.bak` sidecar, first exercised
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", IN_PLACE_VERBS)
def test_ac17_the_bak_sidecar_carries_the_pre_run_bytes(verb: str, corpus, tmp_path: Path) -> None:
    """The `.bak` is a BYTE-IDENTICAL copy of the pre-run original, and the
    input now holds the mutated document.

    This is also the stated compensation for C14's honoured side being vacuous
    for these three verbs (ledger `afe2e6137b` / backlog B-065: the row's own
    fixture is materialised into `tmp_path` after C14's `before` snapshot, so
    those cells pass with the verb never having written anything). PDF-08
    inherits that and does not repair a shared control every verb depends on;
    what proves these three verbs actually wrote something is right here.
    """
    source = _copy(corpus, tmp_path)
    before_hash = _sha256(source)
    before_rotations = _rotations(source)

    result = run_cli(verb, str(source), *_selection_args(verb), "--in-place", cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr

    backup = tmp_path / "work.pdf.bak"
    assert backup.is_file(), "no .bak sidecar was written"
    assert _sha256(backup) == before_hash, ".bak does not carry the pre-run bytes"
    assert _sha256(source) != before_hash, "the input was not mutated"

    if verb == "delete":
        assert _page_numbers(source) == [2, 3, 4, 5, 6, 7, 8, 9, 10]
    elif verb == "reorder":
        assert _page_numbers(source)[0] == 10
    else:
        after_rotations = _rotations(source)
        assert after_rotations[0] != before_rotations[0]
        assert after_rotations[1:] == before_rotations[1:]


@pytest.mark.parametrize("verb", VERBS)
def test_ac18_no_backup_without_in_place_is_a_usage_error(
    verb: str, corpus, tmp_path: Path
) -> None:
    result = run_cli(
        verb,
        str(corpus.path(FIXTURE)),
        *_selection_args(verb),
        "--no-backup",
        "-O",
        str(tmp_path / "o.pdf"),
        cwd=tmp_path,
    )
    assert result.returncode == 2


@pytest.mark.parametrize("verb", IN_PLACE_VERBS)
def test_ac18_in_place_with_no_backup_creates_no_sidecar(verb: str, corpus, tmp_path: Path) -> None:
    source = _copy(corpus, tmp_path)
    before = _sha256(source)
    result = run_cli(
        verb, str(source), *_selection_args(verb), "--in-place", "--no-backup", cwd=tmp_path
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "work.pdf.bak").exists()
    assert _sha256(source) != before, "the input was not mutated"


@pytest.mark.parametrize("verb", IN_PLACE_VERBS)
def test_ac20_an_existing_bak_without_force_refuses_and_changes_nothing(
    verb: str, corpus, tmp_path: Path
) -> None:
    source = _copy(corpus, tmp_path)
    backup = tmp_path / "work.pdf.bak"
    backup.write_bytes(b"an earlier backup nobody should lose")
    source_hash, backup_hash = _sha256(source), _sha256(backup)

    result = run_cli(verb, str(source), *_selection_args(verb), "--in-place", cwd=tmp_path)
    assert result.returncode == 5
    assert _sha256(source) == source_hash, "a refused run mutated the input"
    assert _sha256(backup) == backup_hash, "a refused run overwrote the existing .bak"
    residue = [p.name for p in tmp_path.iterdir() if p.name.startswith(".pdftoolkit-")]
    assert residue == [], f"temp residue survived a refusal: {residue}"


@pytest.mark.parametrize("verb", IN_PLACE_VERBS)
def test_ac21_a_bulk_in_place_run_fails_closed_on_a_non_tty(
    verb: str, corpus, tmp_path: Path
) -> None:
    """`PLAN.md` §5.3's non-TTY posture, reachable by a user for the first
    time. `run_cli` never attaches a terminal, so this is the real branch."""
    first = _copy(corpus, tmp_path, filename="a.pdf")
    second = _copy(corpus, tmp_path, filename="b.pdf")
    hashes = (_sha256(first), _sha256(second))

    refused = run_cli(
        verb, str(first), str(second), *_selection_args(verb), "--in-place", cwd=tmp_path
    )
    assert refused.returncode == 5
    assert (_sha256(first), _sha256(second)) == hashes, "a refused bulk run mutated an input"
    assert not (tmp_path / "a.pdf.bak").exists()
    assert not (tmp_path / "b.pdf.bak").exists()
    assert "-y" in refused.stdout + refused.stderr, "the refusal does not hand back a re-run hint"

    confirmed = run_cli(
        verb, "-y", str(first), str(second), *_selection_args(verb), "--in-place", cwd=tmp_path
    )
    assert confirmed.returncode == 0, confirmed.stdout + confirmed.stderr
    assert (_sha256(first), _sha256(second)) != hashes, "the confirmed run mutated nothing"


# --------------------------------------------------------------------------- #
# AC19/AC33 -- `extract --in-place` is refused BY THE OR-3 DECLARATION
# --------------------------------------------------------------------------- #


def test_ac19_extract_refuses_in_place_naming_the_verb_the_flag_and_the_fix(
    corpus, tmp_path: Path
) -> None:
    before = snapshot(tmp_path)
    result = run_cli(
        "extract", str(corpus.path(FIXTURE)), "--pages", "1", "--in-place", cwd=tmp_path
    )
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "extract" in combined
    assert "--in-place" in combined
    assert "--output" in combined and "--out-dir" in combined
    assert_unchanged(before, snapshot(tmp_path))


def test_ac33_extracts_refusal_needs_no_branch_in_its_own_cmd_module(
    corpus, tmp_path: Path
) -> None:
    """AC33/AC19: the refusal is the shared check's, not a local `if`.

    Proven behaviourally rather than by grepping for an absent string (X-113):
    `cmd_extract.py` never reads the in-place policy, so it cannot be the
    source of the message -- and the message the user gets is byte-for-byte
    the one `cli/common.py::_check_output_flag_consumption` composes for ANY
    verb that does not declare a flag.
    """
    import inspect

    from pdf_toolkit.cli import cmd_extract
    from pdf_toolkit.cli.common import _check_output_flag_consumption

    source = inspect.getsource(cmd_extract)
    assert "config.in_place" not in source
    assert "in_place" not in source

    from pdf_toolkit.errors import UsageError

    class _Config:
        output = None
        out_dir = None
        name = None
        in_place = True

    with pytest.raises(UsageError) as shared:
        _check_output_flag_consumption(
            _Config(),  # type: ignore[arg-type]
            verb="extract",
            consumes=("--output", "--out-dir", "--name"),
        )

    live = run_cli("extract", str(corpus.path(FIXTURE)), "--pages", "1", "--in-place", cwd=tmp_path)
    assert shared.value.message in live.stdout + live.stderr


# --------------------------------------------------------------------------- #
# AC22 -- structural sanity: the output is a readable document
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("verb", "expected_pages"),
    [("extract", 2), ("delete", 9), ("rotate", 10), ("reorder", 10)],
)
def test_ac22_every_output_is_a_readable_document_with_the_expected_page_count(
    verb: str, expected_pages: int, corpus, tmp_path: Path
) -> None:
    target = tmp_path / f"{verb}.pdf"
    tail = ["--pages", "1,3"] if verb == "extract" else _selection_args(verb)
    produced = run_cli(verb, str(corpus.path(FIXTURE)), *tail, "-O", str(target), cwd=tmp_path)
    assert produced.returncode == 0, produced.stdout + produced.stderr

    inspected = run_cli("info", str(target), "-o", "json", cwd=tmp_path)
    assert inspected.returncode == 0, inspected.stderr
    documents = json.loads(inspected.stdout)["documents"]
    assert documents[0]["page_count"] == expected_pages


# --------------------------------------------------------------------------- #
# AC23/AC40/AC41 -- password posture and the ONE error-rendering chokepoint
# --------------------------------------------------------------------------- #


@pytest.mark.xfail(
    strict=True,
    reason=(
        "PDF-08 BLOCKER, reported not repaired. `StructureEngine.open_document`'s own "
        "Protocol docstring (`ports/structure.py`) documents `AuthError: Exit 6` for an "
        "encrypted input, and `PypdfOpenDocument.__enter__` does not implement it: pypdf "
        "raises `FileNotDecryptedError` LAZILY, on `reader.pages` inside `page_count`, "
        "which is outside that method's `except (PdfReadError, OSError, ValueError)` "
        "block. The result is an unhandled traceback and exit 1. This is PRE-EXISTING "
        "and NOT introduced here -- `merge` and `split` (PDF-07, landed at 743853f) "
        "reproduce it identically at 33bf481. PDF-08 does not repair it: password "
        "handling is this spec's Scope Out (PDF-13 owns the §5.7 contract), and the fix "
        "belongs to `PypdfOpenDocument`, a class X-127 assigned to neither PDF-08 nor "
        "PDF-14, whose repair would change two other verbs' behaviour mid-wave. "
        "The assertion below is the CORRECT one and is left intact: strict xfail means "
        "the day the shared fix lands this turns red as an XPASS and forces its own "
        "marker to be removed, rather than pinning today's defect (B-073)."
    ),
)
def test_ac23_an_encrypted_input_surfaces_exit_6_without_a_traceback(
    corpus, tmp_path: Path
) -> None:
    """PDF-13's path surfaced, not re-implemented: PDF-08 owns no password
    handling of its own, and its whole obligation here is that an encrypted
    document produces a classified refusal rather than a stack trace."""
    result = run_cli(
        "extract",
        str(corpus.path("encrypted_aes256")),
        "--pages",
        "1",
        "-O",
        str(tmp_path / "o.pdf"),
        cwd=tmp_path,
    )
    assert result.returncode == 6
    assert "Traceback (most recent call last)" not in result.stderr


@pytest.mark.parametrize("verb", VERBS)
def test_ac40_one_error_renders_through_the_single_chokepoint_in_every_shape(
    verb: str, corpus, tmp_path: Path
) -> None:
    """X-126: every renderer consumes `PdfToolkitError.to_dict()`, so the same
    refusal carries the same code and the same message in all six output
    shapes -- and PDF-08 introduces no renderer of its own."""
    target = tmp_path / "occupied.pdf"
    target.write_bytes(b"%PDF-1.4\n%%EOF\n")
    argv = [str(corpus.path(FIXTURE)), *_selection_args(verb), "-O", str(target)]

    shapes: list[list[str]] = [
        [],
        ["-o", "json"],
        ["-o", "ndjson"],
        ["-o", "table"],
        ["--quiet"],
        ["-vv"],
    ]
    codes: set[int] = set()
    for shape in shapes:
        result = run_cli(verb, *argv, *shape, cwd=tmp_path)
        codes.add(result.returncode)
        combined = result.stdout + result.stderr
        assert "Traceback (most recent call last)" not in combined
        if shape != ["--quiet"]:
            assert "occupied.pdf" in combined, f"shape {shape} rendered no message"
    assert codes == {5}, f"the same refusal produced different exit codes: {codes}"


@pytest.mark.parametrize("verb", VERBS)
def test_ac41_no_verb_grows_a_literal_password_flag(verb: str) -> None:
    """OR-4 + X-114: no flag in this product takes a password-shaped VALUE.
    The registry, not a typed list, is what "allowed" means (X-126)."""
    from pdf_toolkit.cli.common import PASSWORD_FILE_FLAGS

    result = run_cli(verb, "--help")
    assert result.returncode == 0
    normalized = re.sub(r"-[ \t]*\n[ \t]*", "-", result.stdout)
    offenders = [
        flag
        for flag in re.findall(r"--[a-z-]*password[a-z-]*", normalized)
        if flag not in PASSWORD_FILE_FLAGS
    ]
    assert offenders == [], f"`{verb} --help` names {offenders}, outside PASSWORD_FILE_FLAGS"


# --------------------------------------------------------------------------- #
# AC34/AC35/AC36 -- X-67: `--dry-run` PREDICTS, and is pure while doing it
#
# MEASURED DIVERGENCE FROM THE SPEC'S AC34/AC35, recorded here beside the
# tests rather than silently. Both criteria state that a dry run over a
# predicted refusal "exits 0" with the prediction in `-o json`. The landed
# product does the opposite and is PINNED doing it:
# `tests/test_cli_contract.py::test_c15_dry_run_predicts_an_occupied_target_
# refusal` asserts `dry.returncode == real.returncode == 5` for every
# PRODUCING verb, and `compress --dry-run -O <occupied>` exits 5 today. These
# four verbs follow the landed convention, so no verb disagrees with another
# about an exit code, and what the criteria are actually FOR -- a prediction
# that is present, correct, and agrees with the real outcome -- is asserted
# below in full.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", VERBS)
def test_ac34_a_dry_run_over_an_occupied_target_predicts_the_real_refusal(
    verb: str, corpus, tmp_path: Path
) -> None:
    target = tmp_path / "occupied.pdf"
    seed = b"C15-SHAPED-SEED"
    target.write_bytes(seed)
    argv = [str(corpus.path(FIXTURE)), *_selection_args(verb), "-O", str(target)]

    dry = run_cli(verb, "--dry-run", *argv, "-o", "json", cwd=tmp_path)
    payload = json.loads(dry.stdout)
    detail = payload["items"][0]["detail"]
    assert detail["would_exit"] == 5
    assert detail["would_refuse"]["code"] == 5
    assert target.read_bytes() == seed, "--dry-run mutated the occupied target"

    real = run_cli(verb, *argv, cwd=tmp_path)
    assert real.returncode == 5
    assert dry.returncode == detail["would_exit"] == real.returncode


@pytest.mark.parametrize(
    ("pages", "predicted"),
    [("all", 5), ("all,!all", 4)],
)
def test_ac35_the_two_empty_cases_stay_distinct_in_the_prediction(
    pages: str, predicted: int, corpus, tmp_path: Path
) -> None:
    """§D5's pair, predicted rather than only discovered: `delete --pages all`
    predicts the zero-page refusal (5) and `all,!all` predicts the empty
    selection (4), exactly as AC13 keeps them distinct in the outcome."""
    argv = [str(corpus.path(FIXTURE)), "--pages", pages, "-O", str(tmp_path / "o.pdf")]

    dry = run_cli("delete", "--dry-run", *argv, "-o", "json", cwd=tmp_path)
    payload = json.loads(dry.stdout)
    assert payload["dry_run"] is True
    assert payload["items"][0]["detail"]["would_exit"] == predicted

    real = run_cli("delete", *argv, cwd=tmp_path)
    assert real.returncode == predicted, "the prediction and the outcome disagree"
    assert not (tmp_path / "o.pdf").exists()


@pytest.mark.parametrize("verb", VERBS)
def test_ac36_dry_run_purity_is_asserted_non_vacuously(verb: str, corpus, tmp_path: Path) -> None:
    """Purity is necessary and NOT sufficient (X-89: PDF-04's own purity
    criterion passed trivially, because a dry run that does nothing is
    trivially pure). So this asserts both halves: the tree is unchanged, AND
    the run produced a non-trivial plan."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = _copy(corpus, workspace)
    argv = [str(source), *_selection_args(verb), "-O", str(workspace / "out.pdf")]

    env, roots = redirected_environment(tmp_path)
    before = snapshot(workspace, *roots)
    result = run_cli(verb, "--dry-run", *argv, "-o", "json", env=env, cwd=workspace)
    assert_unchanged(before, snapshot(workspace, *roots))
    assert result.returncode == 0, result.stdout + result.stderr

    payload = json.loads(result.stdout)
    assert payload["items"], "a pure dry run that planned nothing proves nothing"
    assert "would_exit" in payload["items"][0]["detail"]
    assert payload["items"][0]["detail"]["pages_after"] > 0

    residue = sorted(p.name for p in workspace.rglob(".pdftoolkit-*"))
    assert residue == [], f"--dry-run left temp residue: {residue}"
    assert not (workspace / "out.pdf").exists()
    assert not (workspace / "work.pdf.bak").exists()


@pytest.mark.parametrize("verb", IN_PLACE_VERBS)
def test_ac36_an_in_place_dry_run_writes_nothing_and_still_plans(
    verb: str, corpus, tmp_path: Path
) -> None:
    """The `--in-place` arm specifically: no `.bak`, no temp, no mutation --
    and still a plan."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = _copy(corpus, workspace)

    env, roots = redirected_environment(tmp_path)
    before = snapshot(workspace, *roots)
    result = run_cli(
        verb,
        "--dry-run",
        str(source),
        *_selection_args(verb),
        "--in-place",
        "-o",
        "json",
        env=env,
        cwd=workspace,
    )
    assert_unchanged(before, snapshot(workspace, *roots))
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["items"][0]["detail"]["pages_after"] > 0
    assert not (workspace / "work.pdf.bak").exists()


# --------------------------------------------------------------------------- #
# AC37 -- X-70: containment, by construction
# --------------------------------------------------------------------------- #


def test_ac37_a_traversal_carrying_stem_is_refused_at_the_exit_5_tier(
    corpus, tmp_path: Path
) -> None:
    """The escape that appears only AFTER substitution, because the *data*
    carried it: a file literally named `...pdf` has the stem `..`, so
    `--name '{stem}.{ext}'` renders a component that would leave `--out-dir`.

    This is the case a statically-valid template cannot be checked for at the
    exit-2 tier, and it is exactly what `ensure_within` (reached through
    `render_name`) exists to catch.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "...pdf"
    shutil.copy(corpus.path(FIXTURE), source)
    assert Path(source.name).stem == "..", "this test's own premise no longer holds"

    out_dir = workspace / "out"
    before = snapshot(tmp_path)
    result = run_cli(
        "extract",
        str(source),
        "--pages",
        "1",
        "--out-dir",
        str(out_dir),
        "--name",
        "{stem}",
        cwd=workspace,
    )
    assert result.returncode == 5, result.stdout + result.stderr
    assert_unchanged(before, snapshot(tmp_path))


def test_ac37_a_statically_malformed_name_is_refused_at_the_exit_2_tier(
    corpus, tmp_path: Path
) -> None:
    """A path separator or `..` typed on the command line is a different kind
    of thing -- decidable without any data -- and is exit 2 from the shared
    option layer, before containment is ever reached."""
    for template in ("../{stem}.{ext}", "sub/{stem}.{ext}"):
        result = run_cli(
            "extract",
            str(corpus.path(FIXTURE)),
            "--pages",
            "1",
            "--out-dir",
            str(tmp_path / "out"),
            "--name",
            template,
            cwd=tmp_path,
        )
        assert result.returncode == 2, f"{template!r}: {result.stdout}{result.stderr}"


def test_ac37_a_symlinked_out_dir_is_compared_in_canonical_form(corpus, tmp_path: Path) -> None:
    """X-70's canonical-form comparison: a symlinked `--out-dir` neither
    defeats containment nor false-refuses an ordinary write. Both halves are
    asserted, because a containment check that refuses everything would pass a
    one-sided test."""
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real_dir, target_is_directory=True)

    ordinary = run_cli(
        "extract",
        str(corpus.path(FIXTURE)),
        "--pages",
        "1",
        "--out-dir",
        str(linked),
        "--name",
        "{stem}.{ext}",
        cwd=tmp_path,
    )
    assert ordinary.returncode == 0, ordinary.stdout + ordinary.stderr
    written = sorted(p.name for p in real_dir.iterdir())
    assert written == [f"{FIXTURE}.pdf"], written

    workspace = tmp_path / "ws"
    workspace.mkdir()
    escaping = workspace / "...pdf"
    shutil.copy(corpus.path(FIXTURE), escaping)
    outside = snapshot(real_dir)
    refused = run_cli(
        "extract",
        str(escaping),
        "--pages",
        "1",
        "--out-dir",
        str(linked),
        "--name",
        "{stem}",
        cwd=workspace,
    )
    assert refused.returncode == 5
    assert_unchanged(outside, snapshot(real_dir))


# --------------------------------------------------------------------------- #
# Multi-input ordering (§5.4) and the arity rule (§D12 rule 1)
# --------------------------------------------------------------------------- #


def test_results_are_rendered_in_input_order(corpus, tmp_path: Path) -> None:
    first = _copy(corpus, tmp_path, filename="first.pdf")
    second = _copy(corpus, tmp_path, filename="second.pdf")
    third = _copy(corpus, tmp_path, filename="third.pdf")
    result = run_cli(
        "delete",
        str(third),
        str(first),
        str(second),
        "--pages",
        "1",
        "--out-dir",
        str(tmp_path / "out"),
        "-o",
        "json",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    inputs = [Path(item["input"]).name for item in json.loads(result.stdout)["items"]]
    assert inputs == ["third.pdf", "first.pdf", "second.pdf"]


@pytest.mark.parametrize("verb", VERBS)
def test_two_inputs_sharing_one_output_target_is_an_arity_error(
    verb: str, corpus, tmp_path: Path
) -> None:
    """Arity is NOT an OR-3 consumption error: all four verbs legitimately
    consume `--output`, so the central check cannot express this, and the
    message names `--out-dir` as the alternative."""
    source = corpus.path(FIXTURE)
    result = run_cli(
        verb,
        str(source),
        str(source),
        *_selection_args(verb),
        "-O",
        str(tmp_path / "one.pdf"),
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert "--out-dir" in result.stdout + result.stderr


@pytest.mark.parametrize("verb", VERBS)
def test_a_run_with_no_destination_at_all_is_a_usage_error(
    verb: str, corpus, tmp_path: Path
) -> None:
    result = run_cli(verb, str(corpus.path(FIXTURE)), *_selection_args(verb), cwd=tmp_path)
    assert result.returncode == 2


@pytest.mark.parametrize("verb", VERBS)
def test_a_run_with_no_pages_at_all_is_a_usage_error(verb: str, corpus, tmp_path: Path) -> None:
    tail = ["--angle", "90"] if verb == "rotate" else []
    result = run_cli(
        verb, str(corpus.path(FIXTURE)), *tail, "-O", str(tmp_path / "o.pdf"), cwd=tmp_path
    )
    assert result.returncode == 2
    assert "--pages" in result.stdout + result.stderr
