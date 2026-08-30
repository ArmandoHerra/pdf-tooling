"""PDF-14 at the subprocess level -- `meta set`/`watermark`/`stamp`'s exit
codes, the safety spine as a real process sees it, AC24's honoured side, and
AC29's chokepoint/no-echo guarantee.

Everything below runs the real CLI in a real process (mirrors
`tests/integration/test_pages_cli.py`'s own module docstring: a
`SafetyPolicy` constructed in-process cannot observe the non-TTY branch or a
real `--dry-run`/no-clobber refusal the way a subprocess can).
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path
from typing import Final

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from fs_snapshot import assert_unchanged, redirected_environment, snapshot  # noqa: E402
from registry import discover_verbs, run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

MY_VERBS: Final[tuple[str, ...]] = ("meta set", "watermark", "stamp")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy(corpus, tmp_path: Path, filename: str, name: str = "single_page") -> Path:
    """A `tmp_path`-local COPY -- never the session-scoped corpus fixture
    itself, which an `--in-place` run would silently corrupt for every
    downstream test that reuses it."""
    destination = tmp_path / filename
    shutil.copy(corpus.path(name), destination)
    return destination


def _extra_args(verb: str, corpus) -> list[str]:
    """The flags each verb needs beyond a destination, to reach exit 0."""
    if verb == "meta set":
        return ["--title", "AC24-Proof-Title"]
    if verb == "watermark":
        return ["--text", "AC24-PROOF"]
    if verb == "stamp":
        return ["--from", str(corpus.path("stamp_source"))]
    raise AssertionError(verb)  # pragma: no cover - MY_VERBS is closed


# --------------------------------------------------------------------------- #
# End-to-end preservation smoke, as a real process
# --------------------------------------------------------------------------- #


def test_watermark_end_to_end_preserves_text_and_adds_draft(corpus, tmp_path: Path) -> None:
    import pypdf

    source = corpus.path("ten_page_text")
    target = tmp_path / "watermarked.pdf"
    result = run_cli("watermark", str(source), "--text", "DRAFT", "-O", str(target), cwd=tmp_path)
    assert result.returncode == 0, result.stderr

    before = pypdf.PdfReader(str(source))
    after = pypdf.PdfReader(str(target))
    assert len(after.pages) == len(before.pages)
    for before_page, after_page in zip(before.pages, after.pages, strict=True):
        before_text = " ".join((before_page.extract_text() or "").split())
        after_text = " ".join((after_page.extract_text() or "").split())
        assert before_text in after_text
        assert "DRAFT" in after_text


def test_stamp_end_to_end_underlay_beneath_original(corpus, tmp_path: Path) -> None:
    import pypdf

    from corpus import STAMP_MARKER

    source = corpus.path("single_page")
    target = tmp_path / "stamped.pdf"
    result = run_cli(
        "stamp",
        str(source),
        "--from",
        str(corpus.path("stamp_source")),
        "--position",
        "underlay",
        "-O",
        str(target),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    stream = pypdf.PdfReader(str(target)).pages[0].get_contents().get_data()
    base_marker = corpus.spec("single_page").page_texts[0].encode()
    assert stream.index(STAMP_MARKER.encode()) < stream.index(base_marker)


def test_meta_set_then_meta_get_round_trips_a_single_field(corpus, tmp_path: Path) -> None:
    import json

    source = corpus.path("metadata_typed")
    target = tmp_path / "tagged.pdf"
    set_result = run_cli(
        "meta", "set", str(source), "--title", "Round Trip Title", "-O", str(target), cwd=tmp_path
    )
    assert set_result.returncode == 0, set_result.stderr

    get_result = run_cli("meta", "get", str(target), "-o", "json", cwd=tmp_path)
    assert get_result.returncode == 0, get_result.stderr
    payload = json.loads(get_result.stdout)
    assert payload["info"]["Title"] == "Round Trip Title"
    assert payload["info"]["Trapped"] == "/False"
    assert payload["info"]["CustomField"] == "custom-value"


# --------------------------------------------------------------------------- #
# AC15 -- the safety spine, as a real process observes it
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", MY_VERBS)
def test_ac15_dry_run_is_pure_and_leaves_no_scratch_residue(
    verb: str, corpus, tmp_path: Path
) -> None:
    args = [*verb.split(), str(corpus.path("single_page")), *_extra_args(verb, corpus)]
    target = tmp_path / "would-write.pdf"
    env, roots = redirected_environment(tmp_path)
    before = snapshot(*roots)
    result = run_cli(*args, "--dry-run", "-O", str(target), env=env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert_unchanged(before, snapshot(*roots))
    assert not any(tmp_path.glob(".pdftoolkit-*"))


@pytest.mark.parametrize("verb", MY_VERBS)
def test_ac15_no_clobber_without_force_exits_5(verb: str, corpus, tmp_path: Path) -> None:
    args = [*verb.split(), str(corpus.path("single_page")), *_extra_args(verb, corpus)]
    target = tmp_path / "occupied.pdf"
    target.write_bytes(b"seeded")
    result = run_cli(*args, "-O", str(target), cwd=tmp_path)
    assert result.returncode == 5
    assert target.read_bytes() == b"seeded"


@pytest.mark.parametrize("verb", MY_VERBS)
def test_ac15_in_place_leaves_a_byte_identical_backup(verb: str, corpus, tmp_path: Path) -> None:
    work = _copy(corpus, tmp_path, f"in-place-{verb.replace(' ', '-')}.pdf")
    original = work.read_bytes()
    args = [*verb.split(), str(work), *_extra_args(verb, corpus)]
    result = run_cli(*args, "--in-place", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    backup = work.with_name(work.name + ".bak")
    assert backup.exists()
    assert backup.read_bytes() == original


# --------------------------------------------------------------------------- #
# AC24 -- the honoured side proves the VERB wrote, not that a fixture
# appeared (open ledger row afe2e6137b). Enumerated by reading
# `VerbSpec.consumes` off the LIVE registry -- never a typed
# `("--output", "--in-place")` tuple.
# --------------------------------------------------------------------------- #


def _declared_pairs() -> list[tuple[str, str]]:
    verbs = {verb.name: verb for verb in discover_verbs() if verb.name in MY_VERBS}
    return [(name, flag) for name, verb in verbs.items() for flag in verb.consumes]


@pytest.mark.parametrize(("verb", "flag"), _declared_pairs(), ids=lambda value: str(value))
def test_ac24_the_honoured_side_proves_the_verb_wrote(
    verb: str, flag: str, corpus, tmp_path: Path
) -> None:
    extra = _extra_args(verb, corpus)
    if flag == "--output":
        target = tmp_path / "ac24-output.pdf"
        assert not target.exists()
        result = run_cli(
            *verb.split(), str(corpus.path("single_page")), *extra, "-O", str(target), cwd=tmp_path
        )
        assert result.returncode == 0, result.stderr
        assert target.exists()
    elif flag == "--in-place":
        work = _copy(corpus, tmp_path, f"ac24-{verb.replace(' ', '-')}.pdf")
        before_sha = _sha256(work)
        before_bytes = work.read_bytes()
        result = run_cli(*verb.split(), str(work), *extra, "--in-place", cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert _sha256(work) != before_sha
        backup = work.with_name(work.name + ".bak")
        assert backup.exists()
        assert backup.read_bytes() == before_bytes
    else:  # pragma: no cover - PDF-14 declares only --output/--in-place
        pytest.fail(f"unexpected declared flag {flag!r} for {verb!r}")


# --------------------------------------------------------------------------- #
# AC29 -- `stamp --from` refusals echo nothing and render through the one
# chokepoint, across every output shape (`OutputFormat`'s own values, not a
# typed list of format strings).
# --------------------------------------------------------------------------- #


def _shapes() -> tuple[tuple[str, ...], ...]:
    from pdf_toolkit.output import OutputFormat

    return (
        (),
        *tuple(("-o", fmt.value) for fmt in OutputFormat),
        ("--quiet",),
        ("-vv",),
    )


def _shape_id(shape: tuple[str, ...]) -> str:
    return " ".join(shape) or "default"


@pytest.mark.parametrize("shape", _shapes(), ids=_shape_id)
def test_ac29_from_missing_path_refusal_names_the_real_path_never_redacted(
    shape: tuple[str, ...], corpus, tmp_path: Path
) -> None:
    """B-074: `stamp`'s `--from` refusals name a DOCUMENT, never a secret --
    constructed without `redacted=True`, so the real path renders."""
    missing = tmp_path / "does-not-exist.pdf"
    result = run_cli(
        "stamp",
        str(corpus.path("single_page")),
        "--from",
        str(missing),
        "-O",
        str(tmp_path / "out.pdf"),
        *shape,
        cwd=tmp_path,
    )
    assert result.returncode == 4
    combined = result.stdout + result.stderr
    assert str(missing) in combined
    assert "<redacted>" not in combined


@pytest.mark.parametrize("shape", _shapes(), ids=_shape_id)
def test_ac29_from_auth_refusal_names_the_flag_and_echoes_no_password(
    shape: tuple[str, ...], corpus, tmp_path: Path
) -> None:
    """AC16's exit-6 refusal, across every output shape: names `--from`,
    never the positional input, and carries no password-shaped value."""
    import pypdf

    password = "pdf-toolkit-ac29-not-a-secret"
    locked = tmp_path / "locked.pdf"
    reader = pypdf.PdfReader(str(corpus.path("single_page")))
    writer = pypdf.PdfWriter(clone_from=reader)
    writer.encrypt(user_password=password, algorithm="AES-256")
    with open(locked, "wb") as handle:  # noqa: PTH123 - test-only scratch
        writer.write(handle)

    result = run_cli(
        "stamp",
        str(corpus.path("single_page")),
        "--from",
        str(locked),
        "-O",
        str(tmp_path / "out.pdf"),
        *shape,
        cwd=tmp_path,
    )
    assert result.returncode == 6
    combined = result.stdout + result.stderr
    assert "--from" in combined
    assert password not in combined
