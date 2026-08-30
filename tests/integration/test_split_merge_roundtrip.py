"""AC1 — the ``split`` → ``merge`` round-trip, the strongest proof available.

``split doc.pdf --each-page --out-dir parts/`` then
``merge <parts in sorted order> -O rebuilt.pdf`` must reproduce the original
document's page count **and** its per-page text, and ``{page:03}``'s
zero-padding must make lexical order equal page order — the property that
lets ``sorted(parts_dir.iterdir())`` rebuild the document at all.

Run once in-process (fast, exercises the ops layer directly) and once as a
subprocess arm under ``-m e2e`` (the only way exit codes and the installed
console script are real).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pdf_toolkit.ops.merge import merge_documents, resolve_merge_inputs
from pdf_toolkit.ops.split import split_document
from pdf_toolkit.safety.policy import SafetyPolicy

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdfium_text import page_text  # noqa: E402
from registry import run_cli  # noqa: E402


def make_policy(**overrides: object) -> SafetyPolicy:
    values: dict[str, object] = {
        "dry_run": False,
        "force": False,
        "in_place": False,
        "backup": True,
        "assume_yes": False,
        "is_tty": False,
        "threads": 1,
    }
    values.update(overrides)
    return SafetyPolicy(**values)  # type: ignore[arg-type]


def test_split_each_page_then_merge_reproduces_page_count_and_text_in_process(
    corpus, tmp_path: Path
) -> None:
    source = corpus.path("multipage_text")
    spec = corpus.spec("multipage_text")

    parts_dir = tmp_path / "parts"
    split_result = split_document(
        source,
        mode="each-page",
        every=None,
        ranges=(),
        name_template=None,
        out_dir=parts_dir,
        policy=make_policy(),
    )
    assert split_result.exit_code == 0

    # (c) {page:03}'s zero-padding makes lexical order equal page order.
    sorted_parts = sorted(parts_dir.iterdir())
    assert len(sorted_parts) == spec.page_count

    rebuilt = tmp_path / "rebuilt.pdf"
    inputs = resolve_merge_inputs(tuple(str(p) for p in sorted_parts))
    merge_result = merge_documents(inputs, output=rebuilt, bookmarks="none", policy=make_policy())
    assert merge_result.exit_code == 0

    from pdf_toolkit.ports.structure import require_structure

    engine = require_structure()
    with engine.open_document(rebuilt) as document:
        # (a) page count == N
        assert document.page_count == spec.page_count

    # (b) for every page i, text(rebuilt, i) == text(doc, i)
    for number, expected_text in enumerate(spec.page_texts, start=1):
        assert page_text(rebuilt, number) == expected_text
        assert page_text(source, number) == expected_text


@pytest.mark.e2e
def test_split_each_page_then_merge_reproduces_page_count_and_text_subprocess(
    corpus, tmp_path: Path
) -> None:
    source = corpus.path("multipage_text")
    spec = corpus.spec("multipage_text")

    parts_dir = tmp_path / "parts"
    split_proc = run_cli("split", str(source), "--each-page", "--out-dir", str(parts_dir))
    assert split_proc.returncode == 0, split_proc.stderr

    sorted_parts = sorted(parts_dir.iterdir())
    assert len(sorted_parts) == spec.page_count

    rebuilt = tmp_path / "rebuilt.pdf"
    merge_proc = run_cli("merge", *[str(p) for p in sorted_parts], "-O", str(rebuilt))
    assert merge_proc.returncode == 0, merge_proc.stderr

    from pdf_toolkit.ports.structure import require_structure

    engine = require_structure()
    with engine.open_document(rebuilt) as document:
        assert document.page_count == spec.page_count

    for number, expected_text in enumerate(spec.page_texts, start=1):
        assert page_text(rebuilt, number) == expected_text
