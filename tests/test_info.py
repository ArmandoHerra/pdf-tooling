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


def test_the_auth_message_names_the_flag_that_will_accept_a_password(
    plain_pdf: Path, tmp_path: Path
) -> None:
    """§5.7's "and say so when they cannot", satisfied by naming the flag."""
    locked = build_encrypted_pdf(plain_pdf, tmp_path / "locked.pdf", user_password="hunter2")
    entry = info_json(str(locked))["documents"][0]
    assert entry["error"]["code"] == 6
    assert "--password-file" in entry["error"]["message"]


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
