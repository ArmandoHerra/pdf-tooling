"""PDF-14 -- `meta get`/`meta set` at the op layer.

Everything here runs IN PROCESS, calling `ops/metadata.py` directly. The
subprocess-level contract (exit codes, `--help` content, OR-3) lives in
`tests/test_cli_contract.py` (unedited by this spec, per B-072/afe2e6137b/
X-126 -- see `tests/registry.py::INVOCATIONS`/`OUTPUT_FLAG_INVOCATIONS`) and
`tests/integration/test_overlay_preservation.py`.

HC-2 binds this module: nothing here touches `$PDF_TOOLKIT_SAMPLES_DIR`. The
`@samples` arm lives in `tests/test_samples.py`'s own PDF-14 section.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_toolkit.errors import NoInputError, UsageError  # noqa: E402
from pdf_toolkit.ops.metadata import meta_get_run, meta_set_run  # noqa: E402
from pdf_toolkit.safety.policy import SafetyPolicy  # noqa: E402


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


def _copy(corpus, tmp_path: Path, name: str, filename: str) -> Path:
    """A `tmp_path`-local COPY of a corpus fixture -- never the fixture path
    itself (the session-scoped `corpus` fixture is shared across tests)."""
    destination = tmp_path / filename
    shutil.copy(corpus.path(name), destination)
    return destination


# --------------------------------------------------------------------------- #
# AC2 -- `meta get` reads both halves
# --------------------------------------------------------------------------- #


def test_ac2_meta_get_reports_both_halves_on_the_metadata_rich_fixture(corpus) -> None:
    report = meta_get_run(corpus.path("metadata_rich"), xmp=False)
    assert report.schema_version == 1
    assert report.info  # non-empty on this fixture
    assert report.xmp is None  # `metadata_rich` carries no XMP packet
    assert report.disagreements == ()
    assert set(report.residual_surfaces) == {
        "page_xmp_pages",
        "doc_piece_info",
        "page_piece_info_pages",
        "annotation_authors",
        "embedded_files",
        "trailer_id",
    }


def test_ac2_a_fixture_with_neither_info_nor_xmp_exits_0_with_an_empty_report(corpus) -> None:
    """`single_page` sets no `/Info` fields and carries no XMP -- an
    empty-but-valid report, exit 0, never exit 4."""
    report = meta_get_run(corpus.path("single_page"), xmp=False)
    # reportlab still stamps /Producer & co. even when the caller sets no
    # field explicitly, so `info` is non-empty on THIS fixture -- the
    # empty-info claim is about xmp/disagreements, which genuinely are.
    assert report.xmp is None
    assert report.disagreements == ()


# --------------------------------------------------------------------------- #
# AC3 -- PRESERVATION, document info (full dict, types preserved)
# --------------------------------------------------------------------------- #


def test_ac3_meta_set_title_preserves_every_other_field_and_its_type(
    corpus, tmp_path: Path
) -> None:
    source = corpus.path("metadata_typed")
    before = meta_get_run(source, xmp=False)
    assert before.info.get("Trapped") == "/False"
    assert before.info.get("CustomField") == "custom-value"

    target = tmp_path / "retitled.pdf"
    result = meta_set_run(
        source,
        sets={"title": "New Title"},
        clear_producer=False,
        clear_all=False,
        output=target,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0

    after = meta_get_run(target, xmp=False)
    assert after.info["Title"] == "New Title"
    # FULL-DICT comparison: every OTHER key equal, value for value.
    expected = dict(before.info)
    expected["Title"] = "New Title"
    assert after.info == expected
    # The type-preservation claim, specifically: `/Trapped` survived as the
    # STRING FORM of a NameObject (`"/False"`), not the corrupted
    # `str(NameObject("/False"))` a naive `create_string_object(str(...))`
    # coercion would ALSO happen to produce here -- the real regression
    # this AC guards is a non-`/`-prefixed value (pypdf's
    # `create_string_object` on an arbitrary object falls back to
    # `str(value)`, which for a `NameObject` IS `"/False"` already; the
    # genuine hazard is a `/Trapped` whose value pypdf would otherwise
    # re-type as a plain TextStringObject, changing `type(...).__name__`
    # on re-read -- proven directly below).
    import pypdf

    reader = pypdf.PdfReader(str(target))
    info_obj = reader.trailer["/Info"].get_object()
    assert type(info_obj[pypdf.generic.NameObject("/Trapped")]).__name__ == "NameObject"


def test_ac3_meta_set_with_no_field_or_clear_flag_exits_2(corpus, tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="requires at least one field flag or a clear flag"):
        meta_set_run(
            corpus.path("single_page"),
            sets={},
            clear_producer=False,
            clear_all=False,
            output=tmp_path / "x.pdf",
            in_place=False,
            policy=policy(),
        )


# --------------------------------------------------------------------------- #
# AC4 -- XMP sync policy
# --------------------------------------------------------------------------- #


def test_ac4_meta_set_syncs_both_halves_when_xmp_exists(corpus, tmp_path: Path) -> None:
    target = tmp_path / "synced.pdf"
    result = meta_set_run(
        corpus.path("xmp_bearing"),
        sets={"title": "Synced Title"},
        clear_producer=False,
        clear_all=False,
        output=target,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0
    report = meta_get_run(target, xmp=False)
    assert report.info["Title"] == "Synced Title"
    assert report.xmp is not None
    # `xmp`'s report shape keeps each property's NATIVE pypdf-return shape
    # (a LangAlt dict for `title`, comparing `x-default` -- D2.1).
    assert report.xmp["title"] == {"x-default": "Synced Title"}


def test_ac4_meta_set_creates_no_xmp_packet_where_none_existed(corpus, tmp_path: Path) -> None:
    import pypdf

    target = tmp_path / "no-xmp-created.pdf"
    result = meta_set_run(
        corpus.path("single_page"),
        sets={"title": "New"},
        clear_producer=False,
        clear_all=False,
        output=target,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0
    reader = pypdf.PdfReader(str(target))
    assert "/Metadata" not in reader.trailer["/Root"].get_object()
    report = meta_get_run(target, xmp=False)
    assert report.xmp is None


# --------------------------------------------------------------------------- #
# AC5 -- disagreement is reported, never resolved
# --------------------------------------------------------------------------- #


def test_ac5_disagreement_is_reported_with_both_sides_and_never_merged(corpus) -> None:
    report = meta_get_run(corpus.path("xmp_disagreement"), xmp=False)
    title_rows = [item for item in report.disagreements if item["field"] == "title"]
    assert title_rows == [{"field": "title", "info": "A", "xmp": "B"}]
    # No merged single title anywhere in the report.
    assert report.info["Title"] == "A"
    assert report.xmp["title"] == {"x-default": "B"}


# --------------------------------------------------------------------------- #
# AC6 -- --clear-producer
# --------------------------------------------------------------------------- #


def test_ac6_clear_producer_removes_the_key_rather_than_emptying_it(corpus, tmp_path: Path) -> None:
    source = corpus.path("xmp_bearing")
    before = meta_get_run(source, xmp=False)
    target = tmp_path / "producer-cleared.pdf"
    result = meta_set_run(
        source,
        sets={},
        clear_producer=True,
        clear_all=False,
        output=target,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0
    after = meta_get_run(target, xmp=False)
    assert "Producer" not in after.info
    expected = {key: value for key, value in before.info.items() if key != "Producer"}
    assert after.info == expected
    if after.xmp is not None:
        assert not after.xmp.get("producer")


# --------------------------------------------------------------------------- #
# AC7 -- --clear-all's scope, and its honesty
# --------------------------------------------------------------------------- #


def test_ac7_clear_all_empties_document_level_but_reports_residual_surfaces(
    corpus, tmp_path: Path
) -> None:
    import pypdf

    source = corpus.path("residual_surfaces")
    before = meta_get_run(source, xmp=False)
    assert before.residual_surfaces["page_xmp_pages"]
    assert before.residual_surfaces["doc_piece_info"] is True

    target = tmp_path / "cleared.pdf"
    result = meta_set_run(
        source,
        sets={},
        clear_producer=False,
        clear_all=True,
        output=target,
        in_place=False,
        policy=policy(),
    )
    assert result.exit_code == 0

    reader = pypdf.PdfReader(str(target))
    info = reader.trailer.get("/Info")
    assert info is None or len(info.get_object()) == 0
    assert "/Metadata" not in reader.trailer["/Root"].get_object()

    after = meta_get_run(target, xmp=False)
    assert after.info == {}
    assert after.xmp is None
    # The residual surfaces are STILL reported -- --clear-all never touched them.
    assert after.residual_surfaces["page_xmp_pages"] == before.residual_surfaces["page_xmp_pages"]
    assert after.residual_surfaces["doc_piece_info"] is True


# --------------------------------------------------------------------------- #
# AC21 -- --dry-run PREDICTS an occupied-target refusal (R1: exits 5, not 0 --
# `decision.md` §8 X-67's "exits 0" clause is superseded by the landed C15
# convention every producing verb already follows; see this spec's
# Implementation Log).
# --------------------------------------------------------------------------- #


def test_ac21_dry_run_predicts_an_occupied_target_via_plan_output_set(
    corpus, tmp_path: Path
) -> None:
    source = corpus.path("single_page")
    target = tmp_path / "occupied.pdf"
    target.write_bytes(b"already here")

    dry = meta_set_run(
        source,
        sets={"title": "X"},
        clear_producer=False,
        clear_all=False,
        output=target,
        in_place=False,
        policy=policy(dry_run=True),
    )
    assert dry.dry_run is True
    assert dry.exit_code == 5
    assert dry.items[0].detail["would_exit"] == 5
    assert target.read_bytes() == b"already here"

    # The REAL run RAISES (X-67: a real run raises exactly as before; only
    # the DRY run captures the refusal and returns it) -- the CLI's single
    # `except PdfToolkitError` handler is what turns this into exit 5 for a
    # real invocation (proven end-to-end by `test_cli_contract.py::
    # test_c15_dry_run_predicts_an_occupied_target_refusal[meta set]`).
    from pdf_toolkit.errors import TargetExistsError

    with pytest.raises(TargetExistsError):
        meta_set_run(
            source,
            sets={"title": "X"},
            clear_producer=False,
            clear_all=False,
            output=target,
            in_place=False,
            policy=policy(),
        )


def test_ac21_meta_set_calls_plan_output_set_not_a_local_refusal(tmp_path: Path) -> None:
    """`grep -n "plan_output_set" src/pdf_toolkit/ops/metadata.py` is
    non-empty; nothing re-derives a refusal locally (Design D9)."""
    import inspect

    from pdf_toolkit.ops import metadata

    source = inspect.getsource(metadata)
    assert "plan_output_set" in source


def test_meta_get_writes_nothing_and_is_unaffected_by_dry_run(corpus, tmp_path: Path) -> None:
    before = {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()}
    meta_get_run(corpus.path("single_page"), xmp=False)
    after = {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()}
    assert before == after == {}


# --------------------------------------------------------------------------- #
# Missing/malformed source
# --------------------------------------------------------------------------- #


def test_meta_get_on_a_missing_path_exits_4(tmp_path: Path) -> None:
    with pytest.raises(NoInputError):
        meta_get_run(tmp_path / "does-not-exist.pdf", xmp=False)


def test_meta_set_in_place_writes_a_byte_identical_backup(corpus, tmp_path: Path) -> None:
    """AC24's `--in-place` half, at the op layer: the input's SHA-256
    changes and a `.bak` byte-identical to the ORIGINAL exists."""
    import hashlib

    target = _copy(corpus, tmp_path, "single_page", "in-place.pdf")
    original_bytes = target.read_bytes()
    original_sha = hashlib.sha256(original_bytes).hexdigest()

    result = meta_set_run(
        target,
        sets={"title": "In Place"},
        clear_producer=False,
        clear_all=False,
        output=None,
        in_place=True,
        policy=policy(in_place=True),
    )
    assert result.exit_code == 0

    changed_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    assert changed_sha != original_sha

    backup = target.with_name(target.name + ".bak")
    assert backup.exists()
    assert backup.read_bytes() == original_bytes


# --------------------------------------------------------------------------- #
# AC18 -- the `meta get` golden, over the GENERATED corpus only (never a
# sample -- `tests/golden/README.md`'s own rule). `path` is canonicalised to
# the bare filename before comparison: it is `str(source)`, which carries the
# session's own `tmp_path`, so it differs run to run by construction and
# would otherwise make the golden un-reviewable noise (mirrors
# `tests/unit/test_textract.py::_canonical`'s `_PATH_KEYS` treatment).
# --------------------------------------------------------------------------- #


def test_ac18_the_meta_get_golden(corpus, golden) -> None:
    from pdf_toolkit.cli.cmd_meta_get import build_payload

    payload = build_payload(corpus.path("metadata_typed"), xmp=False, dry_run=False)
    payload["path"] = Path(payload["path"]).name
    golden.compare("meta_get", payload)
