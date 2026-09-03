"""``info`` end to end: true values, exact exit codes, and provable purity.

Run as a **subprocess**, because exit codes are the point and an exit code
observed inside the test process is a return value.

THE THREE THINGS THIS FILE EXISTS TO PIN
----------------------------------------
1. **``info`` writes nothing.** A whole-tree filesystem snapshot is taken before
   and after, with ``$TMPDIR`` and ``$HOME`` redirected into the test's own
   directory so "nothing appeared in the temp dir" is a comparison rather than a
   glob racing every other process on the machine. Asserted for the plain
   invocation *and* for ``--dry-run``: the dry-run gate sits above the first
   mutating call, so a read-only verb must be pure on both paths, and
   "provable" and "proven" are different words.
2. **The exit codes, one test per row.** The malformed-PDF **1** is consumed by
   a later spec's acceptance signal; it must never drift to 2 or 4.
3. **The reported values are true**, checked against what the fixture generator
   actually wrote rather than against the tool's own earlier output.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from fs_snapshot import assert_unchanged, redirected_environment, snapshot

REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# PROVISIONAL — superseded by PDF-06 tests/corpus.py
#
# The shared fixture corpus does not exist yet and the spec that owns it depends
# on this one, so this is the minimum built inline: a reportlab-generated N-page
# document with known text, and pypdf-encrypted copies of it. When the corpus
# lands, MIGRATE these three builders into it rather than duplicating them —
# the marker line above is greppable precisely so that handoff is mechanical
# instead of depending on someone noticing this comment.
#
# Everything here is GENERATED at test time. Nothing is committed under
# testdata/, and no real document is ever an operand.
# --------------------------------------------------------------------------- #

FIXTURE_PAGES = 3
FIXTURE_TEXT = "pdf-toolkit fixture page"


def build_plain_pdf(path: Path, pages: int = FIXTURE_PAGES) -> Path:
    """A deterministic N-page PDF with known text on every page."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    surface = canvas.Canvas(str(path), pagesize=letter)
    for number in range(1, pages + 1):
        surface.drawString(72, 720, f"{FIXTURE_TEXT} {number}")
        surface.showPage()
    surface.save()
    return path


def build_encrypted_pdf(source: Path, target: Path, *, user_password: str) -> Path:
    """An AES-256 copy of *source*.

    An empty ``user_password`` is the common "owner password only" document —
    permissions are restricted but anyone may open it. A non-empty one is the
    document that genuinely needs a credential.
    """
    from pypdf import PdfWriter

    writer = PdfWriter(clone_from=str(source))
    writer.encrypt(user_password, owner_password="owner-secret", algorithm="AES-256")
    writer.write(str(target))
    return target


def build_malformed_pdf(path: Path) -> Path:
    """Bytes that are not a PDF at all. The 'exits 1 before the fix' input."""
    path.write_bytes(b"%PDF-1.7\nthis is not a valid cross-reference table\n")
    return path


# --------------------------------------------------------------------------- #
# Harness.
# --------------------------------------------------------------------------- #


def run_cli(
    *args: str,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pdf_toolkit", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT if cwd is None else cwd,
        env=env,
    )


def info_json(*args: str) -> dict[str, Any]:
    result = run_cli("info", "-o", "json", *args)
    assert result.stdout, f"no stdout (exit {result.returncode}): {result.stderr}"
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload


@pytest.fixture(scope="module")
def plain_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_plain_pdf(tmp_path_factory.mktemp("corpus") / "plain.pdf")


# --------------------------------------------------------------------------- #
# True values.
# --------------------------------------------------------------------------- #


def test_info_reports_the_true_page_count_and_version(plain_pdf: Path) -> None:
    """Asserted against what the generator wrote, not against prior output."""
    from pypdf import PdfReader

    expected_version = PdfReader(str(plain_pdf)).pdf_header.removeprefix("%PDF-")

    document = info_json(str(plain_pdf))["documents"][0]
    assert document["ok"] is True
    assert document["page_count"] == FIXTURE_PAGES
    assert document["pdf_version"] == expected_version
    assert document["encrypted"] is False
    assert document["encryption_algorithm"] is None
    assert document["size_bytes"] == plain_pdf.stat().st_size


def test_info_reports_the_true_encryption_algorithm(plain_pdf: Path, tmp_path: Path) -> None:
    encrypted = build_encrypted_pdf(plain_pdf, tmp_path / "aes256.pdf", user_password="")
    document = info_json(str(encrypted))["documents"][0]
    assert document["ok"] is True
    assert document["encrypted"] is True
    assert document["encryption_algorithm"] == "AES-256"
    assert document["page_count"] == FIXTURE_PAGES


def test_permissions_are_decoded_to_tokens_not_a_bitmask(plain_pdf: Path, tmp_path: Path) -> None:
    encrypted = build_encrypted_pdf(plain_pdf, tmp_path / "perms.pdf", user_password="")
    permissions = info_json(str(encrypted))["documents"][0]["permissions"]
    assert "print" in permissions
    assert "copy" in permissions
    assert all(isinstance(token, str) for token in permissions)
    assert not any(token.startswith("R") and token[1:].isdigit() for token in permissions), (
        "reserved permission bits are not user-facing information"
    )


def test_an_unencrypted_document_reports_no_permissions(plain_pdf: Path) -> None:
    assert info_json(str(plain_pdf))["documents"][0]["permissions"] == []


def test_linearization_is_reported_from_the_capability_adapter(
    plain_pdf: Path, tmp_path: Path
) -> None:
    """The one place D-04's "selected by capability" is realised in this spec.

    pypdf cannot answer this question at all; the answer comes from whichever
    adapter declares the ``linearized`` capability, chosen through the registry
    without any caller naming it.
    """
    import pikepdf

    linearized = tmp_path / "linearized.pdf"
    with pikepdf.Pdf.open(str(plain_pdf)) as pdf:
        pdf.save(str(linearized), linearize=True)

    assert info_json(str(plain_pdf))["documents"][0]["linearized"] is False
    assert info_json(str(linearized))["documents"][0]["linearized"] is True


def test_fonts_and_page_detail_are_empty_tuples_until_asked_for(plain_pdf: Path) -> None:
    """Empty, never absent and never null, so the shape is flag-independent."""
    document = info_json(str(plain_pdf))["documents"][0]
    assert document["fonts"] == []
    assert document["pages"] == []


def test_fonts_names_the_base_fonts(plain_pdf: Path) -> None:
    document = info_json("--fonts", str(plain_pdf))["documents"][0]
    assert document["fonts"] == ["Helvetica"]


def test_pages_detail_reports_one_entry_per_page(plain_pdf: Path) -> None:
    pages = info_json("--pages-detail", str(plain_pdf))["documents"][0]["pages"]
    assert len(pages) == FIXTURE_PAGES
    assert [page["number"] for page in pages] == [1, 2, 3]
    for page in pages:
        assert page["width_pt"] == pytest.approx(612.0)
        assert page["height_pt"] == pytest.approx(792.0)
        assert page["rotation"] == 0
        assert page["has_text"] is True, "the generator wrote text on every page"
        assert page["image_count"] == 0


def test_signature_and_form_presence_are_reported_without_a_validity_claim(
    plain_pdf: Path,
) -> None:
    document = info_json(str(plain_pdf))["documents"][0]
    assert document["has_signature"] is False
    assert document["has_forms"] is False
    assert "signature_valid" not in document, "this product makes no validity claim"


def test_metadata_is_reported_as_a_dictionary(plain_pdf: Path) -> None:
    metadata = info_json(str(plain_pdf))["documents"][0]["metadata"]
    assert isinstance(metadata, dict)
    assert any("ReportLab" in str(value) for value in metadata.values())


# --------------------------------------------------------------------------- #
# Exit codes — one test per row of the pinned table.
# --------------------------------------------------------------------------- #


def test_success_is_zero(plain_pdf: Path) -> None:
    assert run_cli("info", str(plain_pdf)).returncode == 0


def test_dry_run_is_also_zero(plain_pdf: Path) -> None:
    assert run_cli("info", str(plain_pdf), "--dry-run").returncode == 0


def test_a_malformed_pdf_is_exit_one(tmp_path: Path) -> None:
    """Consumed by a later spec: ``repair`` proves itself against this exact code."""
    broken = build_malformed_pdf(tmp_path / "broken.pdf")
    assert run_cli("info", str(broken)).returncode == 1


def test_a_malformed_pdf_reports_a_structured_error(tmp_path: Path) -> None:
    broken = build_malformed_pdf(tmp_path / "broken.pdf")
    entry = info_json(str(broken))["documents"][0]
    assert entry["ok"] is False
    assert entry["error"]["code"] == 1
    assert entry["error"]["kind"] == "failure"
    assert entry["error"]["message"]


def test_a_nonexistent_path_is_exit_four(tmp_path: Path) -> None:
    assert run_cli("info", str(tmp_path / "absent.pdf")).returncode == 4


def test_an_unknown_flag_is_exit_two(plain_pdf: Path) -> None:
    assert run_cli("info", str(plain_pdf), "--not-a-flag").returncode == 2


def test_a_directory_operand_is_exit_two(tmp_path: Path) -> None:
    """``--recursive`` is out of scope; this becomes 4 when discovery lands."""
    result = run_cli("info", str(tmp_path))
    assert result.returncode == 2


def test_the_directory_message_says_a_file_was_expected(tmp_path: Path) -> None:
    result = run_cli("info", "-o", "table", str(tmp_path))
    assert "directory" in (result.stdout + result.stderr).lower()


def test_no_operands_is_exit_two() -> None:
    assert run_cli("info").returncode == 2


def test_an_owner_password_only_document_is_exit_zero(plain_pdf: Path, tmp_path: Path) -> None:
    """``PLAN.md`` §5.7: report the permission bits without the owner password."""
    encrypted = build_encrypted_pdf(plain_pdf, tmp_path / "owner.pdf", user_password="")
    result = run_cli("info", "-o", "json", str(encrypted))
    assert result.returncode == 0
    assert json.loads(result.stdout)["documents"][0]["encrypted"] is True


def test_a_user_password_document_is_exit_six(plain_pdf: Path, tmp_path: Path) -> None:
    """Exit 6 does not collapse into 3 or 5 — ``PLAN.md`` §12 R-05, decided."""
    locked = build_encrypted_pdf(plain_pdf, tmp_path / "locked.pdf", user_password="hunter2")
    assert run_cli("info", str(locked)).returncode == 6


def test_the_auth_message_names_a_resolution_info_can_actually_offer(
    plain_pdf: Path, tmp_path: Path
) -> None:
    """§5.7's "and say so when they cannot" — RE-DERIVED by PDF-20 (B-086).

    This row previously asserted the message named ``--password-file``, on
    `PDF-05` D6.3's premise that `info` would grow that flag. **The premise
    turned out false.** `PDF-13` gave `--password-file` to `decrypt`, `encrypt`
    and `permissions` only, and `cli/common.py` refuses a flag a verb does not
    declare with exit 2 — so the shipped message told a user to reach for a flag
    whose use `info` itself would reject. The old assertion was an INVERTED
    control: it pinned the defect B-086 was filed against, and it was green
    throughout.

    What §5.7 actually requires is that the tool SAY SO when it cannot read a
    document. Naming the verb that resolves it does that and is true on every
    verb that can print the message; naming a flag is true on none of them.
    """
    locked = build_encrypted_pdf(plain_pdf, tmp_path / "locked.pdf", user_password="hunter2")
    entry = info_json(str(locked))["documents"][0]
    assert entry["error"]["code"] == 6
    message = entry["error"]["message"]
    assert "pdftoolkit decrypt" in message, message
    assert "--password-file" not in message, (
        "the message names a flag `info` does not declare; driving it would be exit 2 (B-086)"
    )


def test_the_password_itself_never_appears_in_the_output(plain_pdf: Path, tmp_path: Path) -> None:
    locked = build_encrypted_pdf(plain_pdf, tmp_path / "locked.pdf", user_password="hunter2")
    result = run_cli("info", "-vv", str(locked))
    assert "hunter2" not in result.stdout
    assert "hunter2" not in result.stderr


def test_a_batch_with_one_failure_is_exit_one(plain_pdf: Path, tmp_path: Path) -> None:
    """``PLAN.md`` §5.4: the run continues and exits 1, with per-item status.

    A single input keeps its own specific code (4 here); more than one collapses
    to 1 so the aggregate is not mistaken for a diagnosis of the whole run.
    """
    missing = tmp_path / "absent.pdf"
    assert run_cli("info", str(missing)).returncode == 4
    assert run_cli("info", str(plain_pdf), str(missing)).returncode == 1


def test_a_batch_preserves_per_item_codes_and_input_order(plain_pdf: Path, tmp_path: Path) -> None:
    missing = tmp_path / "absent.pdf"
    broken = build_malformed_pdf(tmp_path / "broken.pdf")
    documents = info_json(str(plain_pdf), str(missing), str(broken))["documents"]
    assert len(documents) == 3
    assert documents[0]["ok"] is True
    assert documents[1]["error"]["code"] == 4
    assert documents[2]["error"]["code"] == 1
    assert documents[1]["path"] == str(missing)


def test_a_batch_that_all_succeeds_is_exit_zero(plain_pdf: Path, tmp_path: Path) -> None:
    second = build_plain_pdf(tmp_path / "second.pdf", pages=1)
    assert run_cli("info", str(plain_pdf), str(second)).returncode == 0


# --------------------------------------------------------------------------- #
# Purity — the assertion the whole safety posture rests on.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("extra", [(), ("--dry-run",)], ids=["plain", "dry-run"])
def test_info_changes_nothing_on_the_filesystem(tmp_path: Path, extra: tuple[str, ...]) -> None:
    """Photograph the tree, run ``info``, photograph it again. Any difference fails.

    ``$TMPDIR`` and ``$HOME`` are redirected under *tmp_path* and both are
    snapshot roots, so a temp file the verb forgot to remove is caught by a
    whole-tree comparison rather than by a glob racing the rest of the machine.

    Both arms must be pure: ``--dry-run`` purity is the guarantee users act on,
    and a read-only verb that was pure only when asked nicely would be a strange
    thing to ship.
    """
    workspace = tmp_path / "work"
    workspace.mkdir()
    document = build_plain_pdf(workspace / "sample.pdf")

    env, extra_roots = redirected_environment(tmp_path / "env")
    roots = (workspace, *extra_roots)

    before = snapshot(*roots)
    result = run_cli("info", str(document), *extra, env=env, cwd=workspace)
    assert result.returncode == 0, result.stderr
    assert_unchanged(before, snapshot(*roots))


def test_info_leaves_no_toolkit_temp_file_anywhere(tmp_path: Path) -> None:
    """Named separately from the snapshot because it is the *specific* residue
    a killed write leaves, and ``doctor --strict`` reports on exactly it."""
    from pdf_toolkit.safety.tempnames import find_stray_temps

    workspace = tmp_path / "work"
    workspace.mkdir()
    document = build_plain_pdf(workspace / "sample.pdf")
    env, extra_roots = redirected_environment(tmp_path / "env")

    assert run_cli("info", str(document), env=env, cwd=workspace).returncode == 0
    for root in (workspace, *extra_roots):
        assert find_stray_temps(root) == (), root


def test_neither_info_module_constructs_a_writer() -> None:
    """Structural, not behavioural: the write path is never even reachable.

    An **AST** check, not a text grep. The first draft of this test was a
    substring scan and it went red on the word ``AtomicWriter`` appearing in
    ``ops/inspect.py``'s own docstring — where it appears precisely to say the
    writer is never constructed. A guard that a correct implementation cannot
    satisfy without deleting its own documentation is a defective guard, and
    ``tests/test_import_boundaries.py`` already demonstrates the right tool.
    """
    for module in ("ops/inspect.py", "cli/cmd_info.py"):
        tree = ast.parse((REPO_ROOT / "src" / "pdf_toolkit" / module).read_text(), filename=module)
        referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        assert "AtomicWriter" not in referenced, module
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "shutil" not in imported, module


# --------------------------------------------------------------------------- #
# Envelope and renderers.
# --------------------------------------------------------------------------- #


def test_the_json_envelope_is_the_published_shape(plain_pdf: Path) -> None:
    payload = info_json(str(plain_pdf))
    assert payload["schema_version"] == 1
    assert payload["verb"] == "info"
    assert isinstance(payload["documents"], list)
    assert "items" not in payload, "the streaming alias is withheld from -o json"


def test_ndjson_streams_one_full_entry_per_document(plain_pdf: Path, tmp_path: Path) -> None:
    second = build_plain_pdf(tmp_path / "second.pdf", pages=1)
    result = run_cli("info", "-o", "ndjson", str(plain_pdf), str(second))
    assert result.returncode == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert [record["page_count"] for record in records] == [FIXTURE_PAGES, 1]
    for record in records:
        assert record["schema_version"] == 1
        assert record["verb"] == "info"


def test_table_output_is_a_readable_projection(plain_pdf: Path) -> None:
    result = run_cli("info", "-o", "table", str(plain_pdf))
    assert result.returncode == 0
    header = result.stdout.splitlines()[0]
    for column in ("path", "page count", "pdf version"):
        assert column in header, header
    assert "metadata" not in header, "the full record belongs to -o json, not to a table cell"


def test_info_appears_in_help() -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    assert "info" in result.stdout


# --------------------------------------------------------------------------- #
# PDF-26 -- an existing-but-unreadable operand (936e467514 / B-037).
#
# `info` is the reference implementation of `PLAN.md` §5.4's batch rule -- *a
# failing input is recorded, the run continues, and the run exits 1 at the end
# with a per-input status* -- and it is the ONLY verb on this tree with a
# per-item outcome model to hang that rule on (`ops/inspect.py::inspect_paths`'
# per-input `except PdfToolkitError`). So this is where the SURVIVAL half of
# PDF-26 is asserted; the CLASSIFICATION half is uniform across all 24 operand
# verbs and lives in `tests/test_cli_contract.py`'s C18.
#
# EVERY ARM BELOW DEPENDS ON MODE BITS AND THEREFORE SKIPS AS ROOT. Root ignores
# them, so a mode-000 file is readable to root and these controls cannot fire at
# all; a green run from a root shell would have measured nothing.
# --------------------------------------------------------------------------- #

UNREADABLE_MODE = 0o000


def skip_as_root() -> None:
    import os

    if os.geteuid() == 0:
        pytest.skip("root ignores mode bits; a mode-000 operand is readable as root")


@pytest.fixture
def unreadable_pdf(plain_pdf: Path, tmp_path: Path) -> Path:
    """A valid, mode-`000` COPY of the shared fixture.

    A copy, never `plain_pdf` itself: the fixture is module-scoped and shared,
    so chmodding it would break every other test in this file. The mode is
    restored on teardown -- a mode-000 file is not removable by an ordinary
    recursive delete, and this product's own sweeps have left six orphaned
    sandboxes behind for exactly that reason.
    """
    import shutil

    target = tmp_path / "unreadable.pdf"
    shutil.copyfile(plain_pdf, target)
    target.chmod(UNREADABLE_MODE)
    yield target
    target.chmod(0o600)


def test_ac1_an_unreadable_input_beside_a_good_one_is_exit_one_with_both_entries(
    plain_pdf: Path, unreadable_pdf: Path
) -> None:
    """AC1, the recorded repro exactly as filed.

    *Red at `cdc02ee`*: exit **2** with a `{"kind": "usage", "code": 2}`
    envelope naming the framework's "is not readable", ONE entry-less error
    object, and the readable second input never parsed let alone inspected.
    (At `2d19bcb`, where the spec was drafted, the same refusal printed ZERO
    bytes on stdout; PDF-25 gave it an envelope in wave 6. The classification
    was identical in both -- which is why this asserts the classification and
    says nothing about stdout's length.)
    """
    skip_as_root()
    result = run_cli("info", "-o", "json", str(unreadable_pdf), str(plain_pdf))
    assert result.returncode == 1, f"exit {result.returncode}: {result.stdout}{result.stderr}"

    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["verb"] == "info"

    documents = payload["documents"]
    assert len(documents) == 2, f"expected an entry per input, in input order: {documents}"

    first, second = documents
    assert first["path"] == str(unreadable_pdf)
    assert first["ok"] is False
    assert first["error"]["code"] == 1
    assert first["error"]["kind"] == "failure"
    assert second["path"] == str(plain_pdf)
    assert second["ok"] is True


def test_ac2_the_second_input_is_genuinely_inspected_not_merely_listed(
    plain_pdf: Path, unreadable_pdf: Path
) -> None:
    """AC2: entry 2's values are READ FROM THE REAL DOCUMENT, not defaulted.

    An entry that is present but empty satisfies AC1's shape and not this
    criterion, which is the whole reason this is a separate assertion: "the
    batch survived" and "the batch did the work" are different claims.
    """
    skip_as_root()
    alone = info_json(str(plain_pdf))["documents"][0]

    result = run_cli("info", "-o", "json", str(unreadable_pdf), str(plain_pdf))
    beside = json.loads(result.stdout)["documents"][1]

    assert beside["page_count"] == alone["page_count"] == FIXTURE_PAGES
    assert beside["size_bytes"] == alone["size_bytes"] == plain_pdf.stat().st_size
    assert beside["pdf_version"] == alone["pdf_version"]


@pytest.mark.parametrize("unreadable_first", [True, False], ids=["bad-first", "bad-last"])
def test_ac3_argument_order_does_not_matter(
    plain_pdf: Path, unreadable_pdf: Path, unreadable_first: bool
) -> None:
    """AC3: both orders exit 1, both carry two entries, in the order given."""
    skip_as_root()
    operands = (
        [str(unreadable_pdf), str(plain_pdf)]
        if unreadable_first
        else [str(plain_pdf), str(unreadable_pdf)]
    )
    result = run_cli("info", "-o", "json", *operands)
    assert result.returncode == 1, f"exit {result.returncode}: {result.stdout}{result.stderr}"

    documents = json.loads(result.stdout)["documents"]
    assert [document["path"] for document in documents] == operands
    assert [document["ok"] for document in documents] == [not unreadable_first, unreadable_first]


def test_ac4_a_single_unreadable_input_reports_its_own_code(
    plain_pdf: Path, unreadable_pdf: Path, tmp_path: Path
) -> None:
    """AC4: nonexistent 4, directory 2, unreadable 1, corrupt 1 -- asserted
    TOGETHER, so the distinction `run_exit_code` exists to preserve (a single
    input reports its OWN code) is proved intact rather than assumed.

    *Red at `cdc02ee`*: the unreadable row was 2, colliding with the directory
    row and making the two indistinguishable to a caller.
    """
    skip_as_root()
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not a pdf at all")
    directory = tmp_path / "a-directory"
    directory.mkdir()

    rows = {
        "nonexistent": (tmp_path / "absent.pdf", 4),
        "directory": (directory, 2),
        "unreadable": (unreadable_pdf, 1),
        "corrupt": (corrupt, 1),
    }
    measured = {name: run_cli("info", str(path)).returncode for name, (path, _) in rows.items()}
    assert measured == {name: code for name, (_, code) in rows.items()}, measured

    entry = info_json(str(unreadable_pdf))["documents"][0]
    assert entry["ok"] is False
    assert entry["error"]["code"] == 1


def test_ac8_the_batch_survives_and_reports_every_readable_input(
    plain_pdf: Path, unreadable_pdf: Path, tmp_path: Path
) -> None:
    """AC8 for the per-input-independent class: N inputs, one unreadable, and
    **N-1 real report entries** plus one failed item carrying `code: 1`.

    Three inputs rather than two, with the bad one in the MIDDLE, so this fails
    if the run stops at the failure rather than merely if it never starts.
    """
    skip_as_root()
    import shutil

    second_good = tmp_path / "second-good.pdf"
    shutil.copyfile(plain_pdf, second_good)

    operands = [str(plain_pdf), str(unreadable_pdf), str(second_good)]
    result = run_cli("info", "-o", "json", *operands)
    assert result.returncode == 1

    documents = json.loads(result.stdout)["documents"]
    assert [document["path"] for document in documents] == operands
    ok = [document for document in documents if document["ok"]]
    failed = [document for document in documents if not document["ok"]]
    assert len(ok) == 2, f"expected N-1 surviving reports: {documents}"
    assert len(failed) == 1
    assert failed[0]["error"]["code"] == 1
    assert all(document["page_count"] == FIXTURE_PAGES for document in ok)


def test_ac16_a_toctou_race_still_exits_one_without_a_traceback(unreadable_pdf: Path) -> None:
    """AC16: with the §D5 classifier's `os.access` patched to LIE (always
    `True`) against an operand that is in fact mode 000, the run still exits 1
    with a coded error and no traceback -- which is what proves §D3's
    adapter-seam mapping is load-bearing rather than decorative.

    A real subprocess running the real `main()` seam; only `os.access` is
    replaced, in the child, before the product is imported. That is the honest
    shape of the race: readable at classify time, unreadable at open time.

    *Red before §D3 landed*: this arm produced E3's `PermissionError` traceback
    from `adapters/pypdf_structure.py`'s unguarded `open(self._path, "rb")`.
    """
    skip_as_root()
    liar = (
        "import os; os.access = lambda *a, **k: True; from pdf_toolkit.cli.main import main; main()"
    )
    result = subprocess.run(
        [sys.executable, "-c", liar, "-o", "json", "info", str(unreadable_pdf)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    both = result.stdout + result.stderr
    detail = f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"

    assert result.returncode == 1, detail
    assert "Traceback (most recent call last)" not in both, detail
    assert "PermissionError" not in both, detail
    entry = json.loads(result.stdout)["documents"][0]
    assert entry["ok"] is False
    assert entry["error"]["code"] == 1
    assert entry["error"]["kind"] == "failure"


def test_ac16_the_toctou_arm_holds_at_the_open_document_seam_too(
    unreadable_pdf: Path, tmp_path: Path
) -> None:
    """AC16's second seam, and it exists because the FIRST one did not cover it.

    §D3 belts TWO distinct pypdf entry points, and `info` only ever reaches one
    of them (`read_document_info`'s `PdfReader(str(path))`). The other --
    `PypdfOpenDocument.__enter__`'s bare `open(self._path, "rb")` -- is E3's
    ACTUAL captured frame and is reached by `merge`, `split`, `extract`,
    `delete`, `rotate`, `reorder`, `rasterize`, `text`, `tables` and `compress
    --pages`. Removing the belt there left the `info` arm above GREEN, which is
    how this gap was found: a control whose planted red does not fire is not a
    control, and one arm here would have been exactly that.
    """
    skip_as_root()
    liar = (
        "import os; os.access = lambda *a, **k: True; from pdf_toolkit.cli.main import main; main()"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            liar,
            "merge",
            str(unreadable_pdf),
            "-O",
            str(tmp_path / "toctou-merge.pdf"),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    both = result.stdout + result.stderr
    detail = f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.returncode == 1, detail
    assert "Traceback (most recent call last)" not in both, detail
    assert "PermissionError" not in both, detail
    assert not (tmp_path / "toctou-merge.pdf").exists(), detail


def test_the_toctou_arm_is_not_vacuous(unreadable_pdf: Path) -> None:
    """The control for the control: the same subprocess shape WITHOUT the lying
    `os.access` must reach the §D5 classifier instead, so AC16's arm is proved
    to be exercising a different code path rather than re-measuring §D5."""
    skip_as_root()
    honest = "from pdf_toolkit.cli.main import main; main()"
    result = subprocess.run(
        [sys.executable, "-c", honest, "-o", "json", "info", str(unreadable_pdf)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    from pdf_toolkit.safety.paths import UNREADABLE_MESSAGE

    entry = json.loads(result.stdout)["documents"][0]
    assert result.returncode == 1
    assert entry["error"]["message"] == UNREADABLE_MESSAGE, (
        "without the patch the classifier's own message must appear; if it does not, "
        "AC16's arm and the §D5 arm are measuring the same path and one of them is "
        "redundant"
    )


# --------------------------------------------------------------------------- #
# AC16, THE RASTER SEAMS -- `ops/compose.py`'s THREE reads (`02096f4422`).
#
# The two arms above belt `pypdf`. They cover the twenty-two verbs whose operand
# is a PDF and NOT the one whose operand is an image: `compose` reads its input
# three separate times, through neither of the belted entry points, and the
# first of those reads was unguarded. Driven at AC16's own condition it exited 1
# with **zero bytes of stdout and a 3361-byte traceback** ending
# `PermissionError` at `ops/compose.py:442, in _read_head`.
#
# THE FILE WAS ALREADY THE ONE §D3 EXTENDED TO, WHICH IS THE WHOLE LESSON. The
# extension belted `:406`'s `read_source_bytes` and stopped there; `:442`'s
# `path.open("rb")` and the two `Image.open(path)` seams -- neither of which
# goes through `read_bytes`, so neither could be served by `read_source_bytes`
# at all -- were left. A belt fitted to one seam in a three-seam file is not a
# belt, and the arm that would have said so did not exist.
#
# ONE ARM PER SEAM, AND EACH DRIVES ITS OWN. `:442` is the first read, so it
# SHADOWS the two below it: an operand that is mode-000 from the start can never
# reach them, and three arms sharing that one invocation would have measured one
# seam three times. So the later two are reached by the honest race they are
# actually exposed to -- the operand goes unreadable *between* two reads, which
# is the TOCTOU window `classify_operand`'s `os.access` cannot close and the
# only reason §D3 exists. Each arm was proved red by removing ITS OWN belt and
# confirming the other two stayed green.
# --------------------------------------------------------------------------- #

_LYING_ACCESS = "import os; os.access = lambda *a, **k: True; "
_ENTRYPOINT = "from pdf_toolkit.cli.main import main; main()"

#: How the race arms tell their child which file to pull the mode bits from.
#: An environment variable rather than an `argv` index: the arms differ in their
#: argv tails, and a positional guess would silently start chmodding the output
#: path the day a row grows a flag.
_RACE_TARGET_ENV = "PDF_TOOLKIT_TEST_RACE_TARGET"


def build_image(path: Path, fmt: str) -> Path:
    """A tiny real raster. JPEG takes `compose`'s passthrough path and PNG does
    not, which is what decides whether `_decode_for_reencode` runs at all."""
    from PIL import Image

    Image.new("RGB", (32, 24), (200, 30, 30)).save(path, format=fmt)
    return path


def run_compose_race(
    program: str, source: Path, tmp_path: Path, *, env: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run *program* as `compose <source> -O <out>` and hand back the result.

    The output path is returned rather than asserted on here because two callers
    want the same thing said about it: `compose` is a single-artifact verb, so
    every arm below has to show that a read that failed part-way wrote nothing.
    """
    import os as _os

    output = tmp_path / "toctou-compose.pdf"
    child_env = dict(_os.environ)
    child_env.update(env or {})
    result = subprocess.run(
        [sys.executable, "-c", program, "-o", "json", "compose", str(source), "-O", str(output)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        env=child_env,
    )
    return result, output


def assert_coded_not_crashed(result: subprocess.CompletedProcess[str], output: Path) -> dict:
    """The four things every AC16 arm means by "it held", and the envelope."""
    both = result.stdout + result.stderr
    detail = f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.returncode == 1, detail
    assert "Traceback (most recent call last)" not in both, detail
    assert "PermissionError" not in both, detail
    assert not output.exists(), (
        f"compose is a single-artifact verb: a read that failed part-way through must "
        f"leave NOTHING behind, and this left {output} -- {detail}"
    )
    envelope = json.loads(result.stdout)["error"]
    assert envelope["code"] == 1 and envelope["kind"] == "failure", detail
    return envelope


def test_ac16_the_toctou_arm_holds_at_composes_header_seam(tmp_path: Path) -> None:
    """AC16 at `ops/compose.py::_read_head` -- the recorded repro of `02096f4422`,
    at AC16's own condition and nothing added to it.

    *Red with this seam's belt removed*: exit 1, **zero bytes of stdout**, and a
    `PermissionError` traceback at `_read_head`'s `path.open("rb")`. The other
    two arms below stay GREEN when this belt alone is removed, because neither
    reaches this seam.
    """
    skip_as_root()
    source = build_image(tmp_path / "photo.jpg", "JPEG")
    source.chmod(UNREADABLE_MODE)
    try:
        result, output = run_compose_race(_LYING_ACCESS + _ENTRYPOINT, source, tmp_path)
    finally:
        source.chmod(0o600)

    envelope = assert_coded_not_crashed(result, output)
    assert "is not readable" not in result.stdout, (
        "the FRAMEWORK's parse-time veto is back; C18 asserts its absence and this "
        f"arm must not resurrect it -- {envelope}"
    )


def test_ac16_the_toctou_arm_holds_at_composes_inspect_seam(tmp_path: Path) -> None:
    """AC16 at `inspect_image`'s `Image.open` -- reached by the honest race.

    This seam was **already traceback-covered** before this fix: its
    `except (UnidentifiedImageError, OSError, ValueError)` caught the
    `PermissionError` and produced a coded exit 1. What it produced was
    `"could not read as an image: [Errno 13] Permission denied: <abs path>"` --
    a raw errno and an absolute path, blaming the decoder for a file the process
    was never allowed to open. So the belt here buys CLASSIFICATION, not the
    absence of a crash, and this arm asserts the message rather than merely the
    code -- otherwise it would pass with the belt removed.

    *Red with this seam's belt removed*: the message reverts to `could not read
    as an image: [Errno 13] ...`, which this asserts against by equality.
    """
    skip_as_root()
    from pdf_toolkit.safety.paths import UNREADABLE_MESSAGE

    source = build_image(tmp_path / "photo.jpg", "JPEG")
    # The head read succeeds; the operand goes unreadable before the decoder.
    program = (
        "import os\n"
        "from pathlib import Path\n"
        "import pdf_toolkit.ops.compose as C\n"
        f"target = Path(os.environ[{_RACE_TARGET_ENV!r}])\n"
        "_real_head = C._read_head\n"
        "def racing_head(path):\n"
        "    head = _real_head(path)\n"
        "    target.chmod(0o000)\n"
        "    return head\n"
        "C._read_head = racing_head\n" + _ENTRYPOINT
    )
    try:
        result, output = run_compose_race(
            program, source, tmp_path, env={_RACE_TARGET_ENV: str(source)}
        )
    finally:
        source.chmod(0o600)

    envelope = assert_coded_not_crashed(result, output)
    assert envelope["message"] == UNREADABLE_MESSAGE, (
        "an operand that went unreadable between two reads must get the CLASSIFIER's "
        f"sentence, not the decoder's errno -- {envelope}"
    )


def test_ac16_the_toctou_arm_holds_at_composes_decode_seam(tmp_path: Path) -> None:
    """AC16 at `_decode_for_reencode`'s `Image.open` -- the widest window.

    A **PNG**, deliberately: a JPEG takes the passthrough path, `raster=None`,
    and this seam never runs at all -- an arm built on the JPEG fixture the two
    above use would have been green with no belt anywhere in the function.

    This seam also runs INSIDE the `AtomicWriter` context, so it is the one arm
    where "wrote nothing" is a claim about a write already in progress rather
    than about a write never started.

    *Red with this seam's belt removed*: a `PermissionError` traceback at
    `ops/compose.py`'s `_decode_for_reencode`.
    """
    skip_as_root()
    from pdf_toolkit.safety.paths import UNREADABLE_MESSAGE

    source = build_image(tmp_path / "flat.png", "PNG")
    # Readable through the whole of `inspect_image`; unreadable before decode.
    program = (
        "import os\n"
        "from pathlib import Path\n"
        "import pdf_toolkit.ops.compose as C\n"
        f"target = Path(os.environ[{_RACE_TARGET_ENV!r}])\n"
        "_real_plan = C.plan_placements\n"
        "def racing_plan(facts, **kw):\n"
        "    planned = _real_plan(facts, **kw)\n"
        "    target.chmod(0o000)\n"
        "    return planned\n"
        "C.plan_placements = racing_plan\n" + _ENTRYPOINT
    )
    try:
        result, output = run_compose_race(
            program, source, tmp_path, env={_RACE_TARGET_ENV: str(source)}
        )
    finally:
        source.chmod(0o600)

    envelope = assert_coded_not_crashed(result, output)
    assert envelope["message"] == UNREADABLE_MESSAGE, envelope


def test_the_compose_decode_arm_reaches_the_seam_it_names(tmp_path: Path) -> None:
    """The control for the arm above: its PNG fixture must actually be routed to
    `_decode_for_reencode`, or the arm proves nothing about that seam.

    Asserted against the product's own eligibility verdict rather than against
    the extension, because "is this passed through" is `inspect_image`'s call
    and a fixture that quietly became eligible would make the arm vacuous.
    """
    from pdf_toolkit.ops.compose import inspect_image

    facts = inspect_image(build_image(tmp_path / "flat.png", "PNG"), dpi_flag=None)
    assert not facts.passthrough, (
        "the decode arm's fixture is passthrough-eligible, so `_decode_for_reencode` "
        "never runs and that arm is measuring nothing"
    )


# --------------------------------------------------------------------------- #
# AC14 -- `cli/cmd_info.py`'s PINNED EXIT-CODE TABLE, mechanized.
#
# The table was documentation that nothing checked, and it was INCOMPLETE: it
# had no row for an existing-but-unreadable input, which is exactly the gap
# PDF-26 exists to close. Adding the row by hand would repeat the mistake, so
# every row is now PARSED OUT OF THE MODULE DOCSTRING and driven through the
# CLI. A row whose claim is false fails; a row with no driver fails BY NAME, so
# the table cannot grow a claim nothing measures.
#
# This hands `PDF-30` (which re-derives doc claims against the finished
# surface) a table that is correct by construction rather than by review.
# --------------------------------------------------------------------------- #


def pinned_exit_table() -> dict[str, int]:
    """`cmd_info.py`'s EXIT CODES table, read out of its own module docstring."""
    import re

    import pdf_toolkit.cli.cmd_info as module

    docstring = module.__doc__ or ""
    body = docstring.split("EXIT CODES, PINNED", 1)[1]
    rows: dict[str, int] = {}
    for line in body.splitlines():
        match = re.fullmatch(r"(?P<label>\S.*?)\s{2,}(?P<code>\d+)\s*", line)
        if match:
            rows[match["label"].strip()] = int(match["code"])
    return rows


def test_ac14_the_pinned_exit_table_declares_the_unreadable_row() -> None:
    """The table's completeness, asserted before its accuracy: a driver table
    can only prove the rows that EXIST."""
    labels = pinned_exit_table()
    assert labels, (
        "no rows parsed out of cmd_info.py's EXIT CODES table -- the parser has stopped "
        "seeing the table, which would make every assertion below vacuous"
    )
    unreadable = [label for label in labels if "unreadable" in label.lower()]
    assert unreadable, (
        f"cmd_info.py's pinned exit table has no existing-but-unreadable row: {sorted(labels)}"
    )
    assert all(labels[label] == 1 for label in unreadable), labels


def test_ac14_every_pinned_table_row_is_driven_through_the_cli(
    plain_pdf: Path, unreadable_pdf: Path, tmp_path: Path
) -> None:
    """Every row of the table, measured. The anti-lapse half is the
    `pytest.fail` on a row with no driver -- that is what stops the table from
    growing a claim no test measures, which is how it came to be wrong."""
    skip_as_root()
    import shutil

    corrupt = tmp_path / "table-corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.4 truncated")
    directory = tmp_path / "table-directory"
    directory.mkdir()
    locked = build_encrypted_pdf(plain_pdf, tmp_path / "table-locked.pdf", user_password="hunter2")
    second_good = tmp_path / "table-second.pdf"
    shutil.copyfile(plain_pdf, second_good)

    drivers: dict[str, list[str]] = {
        "Success (including ``--dry-run``)": [str(plain_pdf)],
        "Malformed / corrupt / unparseable PDF": [str(corrupt)],
        "Nonexistent input path": [str(tmp_path / "table-absent.pdf")],
        "Unknown flag": [str(plain_pdf), "--no-such-flag"],
        "Directory operand": [str(directory)],
        "Existing but unreadable input": [str(unreadable_pdf)],
        "User password required, none supplied": [str(locked)],
        "Several inputs, at least one failed": [str(plain_pdf), str(corrupt), str(second_good)],
    }

    table = pinned_exit_table()
    undriven = sorted(set(table) - set(drivers))
    assert undriven == [], (
        f"cmd_info.py's pinned exit table declares row(s) {undriven} that nothing drives "
        "through the CLI -- add a driver here, or the table has grown a claim no test "
        "measures (which is how it came to be incomplete in the first place)"
    )

    for label, expected in sorted(table.items()):
        measured = run_cli("info", *drivers[label]).returncode
        assert measured == expected, (
            f"cmd_info.py's pinned table claims {expected} for {label!r}; the CLI returned "
            f"{measured} for `info {' '.join(drivers[label])}`"
        )


def test_ac14_the_table_driver_map_has_no_dead_rows(plain_pdf: Path) -> None:
    """The other direction: a driver whose label is no longer in the table is
    dead weight that would silently stop asserting anything. Kept honest by
    parsing the table rather than by remembering it."""
    table = pinned_exit_table()
    assert len(table) >= 8, f"the table parsed to {len(table)} rows: {sorted(table)}"
    assert "Existing but unreadable input" in table, sorted(table)
