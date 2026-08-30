"""The `samples` fixture's own self-tests, and the home for every later
spec's `@samples` arm — `PLAN.md` §10.1, Design §10.

**This file is append-only across nine specs** (`PDF-07`…`PDF-15`). Each adds
exactly ONE section below this module's own PDF-06 section, in a delimited
block naming its own spec ID, and never edits another spec's section.
`decision.md` §2's execution rule (one engineer at a time in
`apps/pdf-toolkit`) is what makes an append-only shared file safe; the cycle
close audits it with `git log -p -- tests/test_samples.py`, never a grep at
HEAD (append-only shared files are not contention-free —
`expertise/product.yaml`, 2026-08-22).

Rules for every `@samples` arm, restated from Design §10 so a later engineer
does not have to re-derive them:

- Uses `samples.copy()` / `samples.copy_tree()` and nothing else. Never a
  path constructed from `$PDF_TOOLKIT_SAMPLES_DIR` directly.
- Asserts **structural** facts only — page counts, sizes, hashes,
  dimensions. **Never a content string extracted from a sample** (rule 4).
- Produces no golden file. Goldens are built from the generated corpus only.
- Privacy (rule 4) binds this file exactly as it binds `changelog.md`,
  `TESTING.md` and every Implementation Log: filename, page count, size and
  hash only — nothing else about any document's content.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# PDF-06 -- the fixture's own contract (AC15, AC18-adjacent)
# --------------------------------------------------------------------------- #


def test_ac15_fixture_exposes_exactly_four_public_members(samples) -> None:
    public = {name for name in dir(samples) if not name.startswith("_")}
    assert public == {"available", "names", "copy", "copy_tree"}


def test_ac15_available_and_names_never_leak_a_path(samples) -> None:
    """The zero-argument surface can never resolve under the originals root:
    `available` is a bool, `names()` is bare filenames with no separator."""
    assert isinstance(samples.available, bool)
    for name in samples.names():
        assert os.sep not in name
        assert "/" not in name
        assert not name.startswith((str(Path.home()), "/"))


def test_ac15_copy_and_copy_tree_are_argument_taking_methods() -> None:
    """Neither is a zero-argument property that could hand back a path
    directly -- both require a `name` and route through `_resolve()`, which
    is the fixture's one and only originals-root read site."""
    import inspect

    import conftest

    signature_copy = inspect.signature(conftest.Samples.copy)
    signature_copy_tree = inspect.signature(conftest.Samples.copy_tree)
    assert "name" in signature_copy.parameters
    assert "name" in signature_copy_tree.parameters


@pytest.mark.samples
def test_an_unknown_name_fails_rather_than_skips(samples) -> None:
    """ "Sample present but misspelled" is a test bug, not corpus absence."""
    with pytest.raises(pytest.fail.Exception):
        samples.copy("this-name-does-not-exist-anywhere-in-the-corpus.pdf")


@pytest.mark.samples
def test_copy_or_copy_tree_returns_a_writable_path_inside_tmp_path(samples, tmp_path: Path) -> None:
    """Generic on purpose: picks whichever entry the operator's corpus
    happens to have first, rather than hardcoding one operator's filenames
    into PDF-06's own self-test (later specs' `@samples` arms are the place
    for a specific, named file -- Design §10's suggested-sample table)."""
    names = samples.names()
    assert names, "samples.available is True but names() is empty"

    result: Path | None = None
    for name in names:
        try:
            result = samples.copy(name)
        except pytest.fail.Exception:
            try:
                result = samples.copy_tree(name)
            except pytest.fail.Exception:
                continue
        break
    assert result is not None, f"neither copy() nor copy_tree() worked for any of {names}"
    assert result.exists()
    assert result.parent == tmp_path or tmp_path in result.parents
    assert os.access(result, os.W_OK), "the copy is not user-writable"


@pytest.mark.samples
def test_copy_never_hands_back_a_path_under_the_originals_root(samples, tmp_path: Path) -> None:
    root = os.environ.get("PDF_TOOLKIT_SAMPLES_DIR", "")
    name = samples.names()[0]
    try:
        result = samples.copy(name)
    except pytest.fail.Exception:
        result = samples.copy_tree(name)
    assert not str(result).startswith(root), "copy() returned a path under the originals root"
    assert tmp_path in result.parents or result.parent == tmp_path


# --------------------------------------------------------------------------- #
# Later specs append ONE section each below this line, in wave order. Do not
# edit another spec's section. Re-read this file at HEAD immediately before
# adding yours (Design §10; `decision.md` §2 execution rule).
# --------------------------------------------------------------------------- #
