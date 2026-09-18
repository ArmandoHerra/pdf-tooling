"""PDF-89 — a destination that is one of the run's own inputs refuses.

`safety/paths.py:1-12` names *"is the destination the same file as the
input"* as one of the three identity guarantees that module exists to
provide, and `same_destination` answered it correctly from ZERO call sites
until this item. `ensure_no_clobber` correctly admits an identity collision
once `--force` is given (it only asks *does the target exist*), and the
bulk-destructive confirmation gate correctly admits one once `-y` is given
(it only asks *did the operator agree to overwrite existing files*) —
neither asks *is the target also one of the run's own inputs*, so before
this item a run whose resolved destination equalled one of its own inputs
destroyed that input at exit 0, `"ok": true`, with no `.bak` sidecar and no
way back. This is the FIRST defect on this product that destroys data
irrecoverably (`X-861`/`X-864`).

The defect is `19/19` `-O` verbs and `11/11` `--out-dir` verbs (E2); `convert`
and `ocr` are asserted separately, in ONE arm, in
`tests/integration/test_or7_bulk_destructive.py`, under the PM's D10/X-891
census authorization — folding them in here would join the frozen
engine-gating census a second time and cost `+2` rather than the authorized
`+1` (X-892 refuses that trade in advance).

Every arm below is driven in an ISOLATED per-cell fixture copy, never
against the session-scoped `corpus` fixture directly: the destination this
item's own defect writes onto is one of the run's inputs, and the first `-O`
sweep taken for the architect's own spec reproduction corrupted a shared
fixture path by doing exactly that (spec Notes). `corpus.path(...)` is read
once per cell to seed a fresh, tmp_path-local copy; nothing here ever names
`-O`/`--out-dir` at a path under the session corpus.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from dryreal import dry_and_real  # noqa: E402
from fs_snapshot import assert_unchanged, redirected_environment, snapshot  # noqa: E402
from pdf_tooling.safety.paths import identity_key  # noqa: E402
from registry import _password_file, destination_flag_cases, run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

#: `PLAN.md` §5.6.
OK: Final[int] = 0
USAGE: Final[int] = 2
REFUSED: Final[int] = 5

#: AC20 — THE FINGERPRINT, and the only sanctioned refusal assertion in this
#: file. Eight `RefusedError` producers share exit 5 and at least three of
#: them also carry `path: null` (`test_bulk_clobber_gate.py`'s own table), so
#: `returncode == 5` alone proves nothing about WHICH refusal fired — this is
#: `PDF-75`'s C13 failure, which stayed green on both members after the raise
#: it tested was deleted. Two fragments, both from the production message in
#: `safety/paths.py::ensure_destination_is_not_an_input`, one naming the
#: destination clause and one naming the collision clause.
SIGNATURE: Final[tuple[str, str]] = (
    "names one of this run's own inputs",
    "refusing to use an input as a destination",
)


def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        return dict(json.loads(result.stdout))
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"stdout was not JSON ({error}); stdout={result.stdout[:400]!r} "
            f"stderr={result.stderr[-800:]!r}"
        ) from None


def _assert_refused_by_signature(result: subprocess.CompletedProcess[str], *, what: str) -> None:
    payload = _payload(result)
    error = payload.get("error")
    assert isinstance(error, dict), f"{what}: no error envelope: {payload}"
    message = str(error.get("message", ""))
    missing = [fragment for fragment in SIGNATURE if fragment not in message]
    assert result.returncode == REFUSED and error.get("kind") == "refused" and not missing, (
        f"{what}: expected the destination-is-an-input refusal -- exit {REFUSED}, "
        f"kind 'refused', message carrying {list(SIGNATURE)}. Got exit "
        f"{result.returncode}, kind {error.get('kind')!r}, missing {missing}: {message!r}"
    )


# --------------------------------------------------------------------------- #
# AC2 -- every `-O` verb refuses when its single output names its own input.
# 19 less `convert`/`ocr` (AC3's second half, D10) = 17 cells.
# --------------------------------------------------------------------------- #


def _build_compress(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    return target, []


def _build_repair(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    return _build_compress(corpus, tmp_path)


def _build_linearize(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    return _build_compress(corpus, tmp_path)


def _build_text(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    return _build_compress(corpus, tmp_path)


def _build_tables(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("tabular"), target)
    return target, []


def _build_extract(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    return target, ["--pages", "1"]


def _build_reorder(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    return _build_extract(corpus, tmp_path)


def _build_rotate(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    return target, ["--pages", "1", "--angle", "90"]


def _build_delete(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    """`ten_page_text`, never `single_page`: deleting the ONLY page of a
    one-page document is the ZERO-PAGE refusal (exit 5, distinct message)
    masquerading as this one -- `test_bulk_clobber_gate.py`'s own fixture
    note names the identical trap."""
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("ten_page_text"), target)
    return target, ["--pages", "1"]


def _build_merge(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    return target, []


def _build_watermark(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    return target, ["--text", "PDF-89"]


def _build_stamp(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    stamp_source = tmp_path / "stamp-source.pdf"
    shutil.copy(corpus.path("stamp_source"), stamp_source)
    return target, ["--from", str(stamp_source)]


def _build_meta_set(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    return target, ["--title", "PDF-89-probe"]


def _build_encrypt(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    pwfile = _password_file(tmp_path, "owner.pw", "pdf89-owner-pw")
    return target, ["--owner-password-file", str(pwfile)]


def _build_decrypt(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    from corpus import ENCRYPTED_PASSWORD

    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("encrypted_aes256"), target)
    pwfile = _password_file(tmp_path, "user.pw", ENCRYPTED_PASSWORD)
    return target, ["--password-file", str(pwfile)]


def _build_compose(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    from PIL import Image

    target = tmp_path / "in.jpg"
    Image.new("RGB", (64, 48), (10, 120, 200)).save(target, format="JPEG", quality=85)
    return target, []


def _build_create(corpus: Any, tmp_path: Path) -> tuple[Path, list[str]]:
    target = tmp_path / "in.txt"
    target.write_text("PDF-89 probe text\n")
    return target, []


#: The 17-cell population: the 19 `-O` verbs `destination_flag_cases()`
#: publishes, less `convert`/`ocr` (AC3's second half, D10). A drift between
#: this map's keys and the derived population is a defect this file's own
#: non-vacuity test (below) catches by name, never a silent under-cover.
_AC2_BUILDERS: Final[dict[str, Callable[[Any, Path], tuple[Path, list[str]]]]] = {
    "compose": _build_compose,
    "compress": _build_compress,
    "create": _build_create,
    "decrypt": _build_decrypt,
    "delete": _build_delete,
    "encrypt": _build_encrypt,
    "extract": _build_extract,
    "linearize": _build_linearize,
    "merge": _build_merge,
    "meta set": _build_meta_set,
    "reorder": _build_reorder,
    "repair": _build_repair,
    "rotate": _build_rotate,
    "stamp": _build_stamp,
    "tables": _build_tables,
    "text": _build_text,
    "watermark": _build_watermark,
}

#: `destination_flag_cases()` is the product's own published `(verb, flag)`
#: vocabulary (AC1) -- reused, never re-derived through a second one.
_OUTPUT_CASES: Final[frozenset[str]] = frozenset(
    verb for verb, flag in destination_flag_cases() if flag == "--output"
)
AC2_VERBS: Final[tuple[str, ...]] = tuple(sorted(_OUTPUT_CASES - {"convert", "ocr"}))


def test_ac2_population_matches_the_builder_table() -> None:
    """Non-vacuity: the builder map and the derived 17-cell population agree.

    A verb added to the product's `-O` population with no entry here would
    otherwise drop silently out of AC2's coverage rather than failing loudly.
    """
    assert set(AC2_VERBS) == set(_AC2_BUILDERS), (
        f"AC2 population {sorted(AC2_VERBS)} and builder table {sorted(_AC2_BUILDERS)} have drifted"
    )
    assert len(AC2_VERBS) == 17, len(AC2_VERBS)


@pytest.mark.parametrize("verb", AC2_VERBS)
def test_ac2_every_output_verb_refuses_when_its_input_is_its_own_output(
    verb: str, corpus: Any, tmp_path: Path
) -> None:
    """RED at `0283279`: all 19 `-O` verbs exit 0, `ok: true`, destroying the
    input, at zero confirmation flags beyond `-f` (E2)."""
    target, extra = _AC2_BUILDERS[verb](corpus, tmp_path)
    result = run_cli(verb, str(target), "-f", "-O", str(target), *extra, "-o", "json", cwd=tmp_path)
    _assert_refused_by_signature(result, what=verb)


# --------------------------------------------------------------------------- #
# AC3 -- every `--out-dir` verb refuses when a planned target resolves onto
# one of the run's inputs. 11 less `convert`/`ocr` = 9 cells.
# --------------------------------------------------------------------------- #


def _build_outdir_compress(corpus: Any, tmp_path: Path) -> tuple[Path, list[str], list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    return target, [], []


def _build_outdir_extract(corpus: Any, tmp_path: Path) -> tuple[Path, list[str], list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    return target, ["--pages", "1"], []


def _build_outdir_reorder(corpus: Any, tmp_path: Path) -> tuple[Path, list[str], list[str]]:
    return _build_outdir_extract(corpus, tmp_path)


def _build_outdir_rotate(corpus: Any, tmp_path: Path) -> tuple[Path, list[str], list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    return target, ["--pages", "1", "--angle", "90"], []


def _build_outdir_delete(corpus: Any, tmp_path: Path) -> tuple[Path, list[str], list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("ten_page_text"), target)
    return target, ["--pages", "1"], []


def _build_outdir_rasterize(corpus: Any, tmp_path: Path) -> tuple[Path, list[str], list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    return target, [], ["--name", "in.pdf"]


def _build_outdir_split(corpus: Any, tmp_path: Path) -> tuple[Path, list[str], list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    return target, ["--each-page"], ["--name", "in.pdf"]


def _build_outdir_tables(corpus: Any, tmp_path: Path) -> tuple[Path, list[str], list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("tabular"), target)
    return target, [], ["--name", "in.pdf"]


def _build_outdir_text(corpus: Any, tmp_path: Path) -> tuple[Path, list[str], list[str]]:
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    return target, [], ["--name", "in.pdf"]


#: `(input builder, whether the DEFAULT name template already collides)`.
#: The five same-stem/same-extension verbs need no `--name` override (E2's
#: first row); the four whose default template derives a different leaf need
#: one forced to the input's own basename (E2's second row) -- this is a
#: property of DEFAULT NAMING, never of the defect's reach, which is why the
#: population is 9 and not 5 (E2, and `PDF-84`'s own recurrence of the
#: identical undercount one cycle earlier on the neighbouring axis).
_AC3_BUILDERS: Final[dict[str, Callable[[Any, Path], tuple[Path, list[str], list[str]]]]] = {
    "compress": _build_outdir_compress,
    "delete": _build_outdir_delete,
    "extract": _build_outdir_extract,
    "rasterize": _build_outdir_rasterize,
    "reorder": _build_outdir_reorder,
    "rotate": _build_outdir_rotate,
    "split": _build_outdir_split,
    "tables": _build_outdir_tables,
    "text": _build_outdir_text,
}

_OUT_DIR_CASES: Final[frozenset[str]] = frozenset(
    verb for verb, flag in destination_flag_cases() if flag == "--out-dir"
)
AC3_VERBS: Final[tuple[str, ...]] = tuple(sorted(_OUT_DIR_CASES - {"convert", "ocr"}))


def test_ac3_population_matches_the_builder_table() -> None:
    assert set(AC3_VERBS) == set(_AC3_BUILDERS), (
        f"AC3 population {sorted(AC3_VERBS)} and builder table {sorted(_AC3_BUILDERS)} have drifted"
    )
    assert len(AC3_VERBS) == 9, len(AC3_VERBS)


@pytest.mark.parametrize("verb", AC3_VERBS)
def test_ac3_every_out_dir_verb_refuses_when_a_target_resolves_onto_an_input(
    verb: str, corpus: Any, tmp_path: Path
) -> None:
    """RED at `0283279`: the six same-stem verbs destroy under the DEFAULT
    template; `text`/`rasterize` (and, measured here, `split`/`tables`)
    destroy the moment `--name` reproduces the input's own filename (E2)."""
    target, extra, name_override = _AC3_BUILDERS[verb](corpus, tmp_path)
    result = run_cli(
        verb,
        str(target),
        "--out-dir",
        str(tmp_path),
        "--force",
        *extra,
        *name_override,
        "-o",
        "json",
        cwd=tmp_path,
    )
    _assert_refused_by_signature(result, what=verb)


# --------------------------------------------------------------------------- #
# AC4 -- the refusal lifts on no flag that can reach it.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("flags", [(), ("-y",), ("-f", "-y")], ids=["none", "-y", "-f-y"])
def test_ac4_no_flag_lifts_the_refusal(flags: tuple[str, ...], corpus: Any, tmp_path: Path) -> None:
    """Control (per the spec's own pin): mutate the raiser to return early on
    `policy.assume_yes` -- the `-y` and `-f -y` cells here red, while every
    AC2 cell (which carries no `-y`) stays green. `policy.force` must NEVER
    be the mutation driven for this criterion: every AC2/AC3 cell carries
    `-f`, so that mutation would red all 26 cells and isolate nothing (the
    spec's own control note)."""
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    result = run_cli(
        "extract", str(target), "-f", *flags, "-O", str(target), "--pages", "1", "-o", "json"
    )
    _assert_refused_by_signature(result, what=f"extract flags={flags}")


# --------------------------------------------------------------------------- #
# AC5 -- nothing is written ANYWHERE, including the temp tier.
#
# Instrument REPLACED per the gate's binding pin (X-889): `fs_snapshot`'s
# `assert_unchanged`/`redirected_environment`, never
# `test_bulk_clobber_gate.py`'s own `_snapshot` (files only, via `os.walk`) --
# that idiom cannot see a create-then-delete, and `AtomicWriter._discard()`
# unlinks the temp on every exception path, so the criterion's OWN stated
# mutation (move the raiser into the commit step) leaves that instrument's
# snapshot byte-identical and the cell would stay green through the exact
# mutation it exists to catch.
#
# CONTROL OBSERVED RED (reported per the gate's instruction): with the raiser
# moved from `AtomicWriter._plan` into `AtomicWriter._commit` (so `_open_temp`
# has already created a temp file in the destination's own directory before
# the refusal fires), `fs_snapshot.assert_unchanged` reds on the destination
# directory's `mtime` -- create-then-delete is invisible to a files-only walk
# but not to a directory-mtime-aware one. Driven by hand against
# `create notes.txt -f -O notes.txt` (the pure no-planner `AtomicWriter._plan`
# path `merge`/`compose`/`create` are the only three routed through) and
# restored before this suite ran; not re-driven automatically here because
# planting it permanently would require a second, mutated copy of
# `AtomicWriter` in the tree.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", ["extract", "create", "merge"])
def test_ac5_a_refused_run_touches_nothing_anywhere(verb: str, corpus: Any, tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    env, redirected = redirected_environment(tmp_path)
    roots = (work, *redirected)

    if verb == "create":
        target = work / "in.txt"
        target.write_text("ac5 probe\n")
        argv = ["create", "in.txt", "-f", "-O", "in.txt", "-o", "json"]
    elif verb == "merge":
        target = work / "in.pdf"
        shutil.copy(corpus.path("single_page"), target)
        argv = ["merge", "in.pdf", "-f", "-O", "in.pdf", "-o", "json"]
    else:
        target = work / "in.pdf"
        shutil.copy(corpus.path("single_page"), target)
        argv = ["extract", "in.pdf", "-f", "-O", "in.pdf", "--pages", "1", "-o", "json"]

    before = snapshot(*roots)
    result = run_cli(*argv, env=env, cwd=work)
    _assert_refused_by_signature(result, what=verb)
    assert_unchanged(before, snapshot(*roots))

    # The optional second observable the pin offers: the writer must never
    # even have parked at its own first mutating checkpoint. Absent any
    # `PDF_TOOLING_FAULT_*` rendezvous env, `checkpoint()` is inert either
    # way, so this is really the purity assertion above stated twice; kept as
    # its own line because it is a DIRECT claim about the writer's reach
    # rather than an inference from what is left on disk.
    assert "after_temp_create" not in (result.stdout + result.stderr)


# --------------------------------------------------------------------------- #
# AC6 -- the no-`--force` path is byte-identical to `0283279`.
# --------------------------------------------------------------------------- #


def test_ac6_the_no_force_path_is_unchanged(corpus: Any, tmp_path: Path) -> None:
    """Control: move the new call above `ensure_no_clobber` -- this cell
    reds on the message while AC2 stays green (both still exit 5)."""
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    result = run_cli(
        "extract", str(target), "-O", str(target), "--pages", "1", "-o", "json", cwd=tmp_path
    )
    payload = _payload(result)
    error = payload["error"]
    assert result.returncode == REFUSED
    assert error["kind"] == "refused"
    assert error["path"] == str(target)
    assert error["message"] == f"{target} exists; pass --force to overwrite it"
    assert target.read_bytes(), "the target must be untouched, not merely non-empty by luck"


def test_ac6_the_batch_no_force_path_is_unchanged(corpus: Any, tmp_path: Path) -> None:
    c1 = tmp_path / "c1.pdf"
    shutil.copy(corpus.path("single_page"), c1)
    result = run_cli("compress", str(c1), "--out-dir", str(tmp_path), "-o", "json", cwd=tmp_path)
    payload = _payload(result)
    error = payload["error"]
    assert result.returncode == REFUSED
    assert error["kind"] == "refused"
    assert error["message"] == f"{c1} exists; pass --force to overwrite it"


# --------------------------------------------------------------------------- #
# AC7 -- `dry == real`, on the absolute value 5, at both seams.
# --------------------------------------------------------------------------- #


def test_ac7_dry_mirrors_real_at_the_planner_seam(corpus: Any, tmp_path: Path) -> None:
    """`extract` reaches the identity check through `plan_filesystem`/
    `plan_output_set` -- the seam `merge`/`compose`/`create` never touch."""
    target = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), target)
    args = [str(target), "-f", "-O", str(target), "--pages", "1"]
    dry, real = dry_and_real("extract", args, cwd=tmp_path)
    assert dry.returncode == real.returncode == REFUSED, (dry.stdout, real.stdout)
    dry_payload = _payload(dry)
    real_payload = _payload(real)
    item = dry_payload["items"][0]
    assert item["detail"]["would_exit"] == REFUSED
    missing = [f for f in SIGNATURE if f not in item["message"]]
    assert not missing, item
    assert dry_payload["exit_code"] == real_payload["error"]["code"] == REFUSED


def test_ac7_dry_mirrors_real_at_the_writer_seam(corpus: Any, tmp_path: Path) -> None:
    """`create` calls no planner at all -- `AtomicWriter._plan` is its whole
    planning step (D2). Control: place the raiser outside the `try` (or in
    `_commit`) and the dry arm predicts 0 while the real run exits 5."""
    target = tmp_path / "in.txt"
    target.write_text("ac7 writer-seam probe\n")
    args = [str(target), "-f", "-O", str(target)]
    dry, real = dry_and_real("create", args, cwd=tmp_path)
    assert dry.returncode == real.returncode == REFUSED, (dry.stdout, real.stdout)
    item = _payload(dry)["items"][0]
    assert item["detail"]["would_exit"] == REFUSED
    missing = [f for f in SIGNATURE if f not in item["message"]]
    assert not missing, item


# --------------------------------------------------------------------------- #
# AC8 -- a genuinely distinct existing target is still overwritten.
# --------------------------------------------------------------------------- #


def test_ac8_a_distinct_existing_target_is_still_overwritten(corpus: Any, tmp_path: Path) -> None:
    """E6's shape. Control: compare on `Path.name` instead of `identity_key`
    -- `../out/c1.pdf` then collides with `c1.pdf` by name and this cell
    reds, while AC2/AC3 (true identities) stay green."""
    inputs_dir = tmp_path / "inputs"
    out_dir = tmp_path / "out"
    inputs_dir.mkdir()
    out_dir.mkdir()
    c1 = inputs_dir / "c1.pdf"
    shutil.copy(corpus.path("single_page"), c1)
    existing = out_dir / "c1.pdf"
    existing.write_bytes(b"pre-existing, distinct target")

    result = run_cli(
        "compress", str(c1), "--out-dir", str(out_dir), "--force", "-o", "json", cwd=tmp_path
    )
    payload = _payload(result)
    assert result.returncode == OK, payload
    assert payload["items"][0]["ok"] is True
    assert existing.read_bytes() != b"pre-existing, distinct target", "the target was not written"
    assert c1.read_bytes() == corpus.path("single_page").read_bytes(), "the input was mutated"


def test_ac8_minus_o_at_a_distinct_existing_file_still_succeeds(
    corpus: Any, tmp_path: Path
) -> None:
    c1 = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), c1)
    distinct = tmp_path / "distinct-existing.pdf"
    distinct.write_bytes(b"pre-existing distinct file")
    result = run_cli(
        "extract", str(c1), "-f", "-O", str(distinct), "--pages", "1", "-o", "json", cwd=tmp_path
    )
    payload = _payload(result)
    assert result.returncode == OK, payload
    assert distinct.read_bytes() != b"pre-existing distinct file"


# --------------------------------------------------------------------------- #
# AC9 -- identity is INODE identity, never string identity.
# --------------------------------------------------------------------------- #


def test_ac9_a_hard_link_to_an_input_refuses(corpus: Any, tmp_path: Path) -> None:
    """Control: replace `same_destination` with
    `str(canonical(a)) == str(canonical(b))` -- this cell reds (two distinct
    path strings, one inode), and the pre-existing
    `tests/unit/test_safety_paths.py:73` reds identically, which is what a
    reported red node id must distinguish from this one."""
    original = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), original)
    hardlink = tmp_path / "hardlink.pdf"
    os.link(original, hardlink)

    assert identity_key(original)[0] == "inode"
    assert identity_key(hardlink)[0] == "inode"
    assert identity_key(original) == identity_key(hardlink)

    result = run_cli(
        "extract", str(original), "-f", "-O", str(hardlink), "--pages", "1", "-o", "json"
    )
    _assert_refused_by_signature(result, what="hardlink")


def test_ac9_a_symlink_to_an_input_refuses(corpus: Any, tmp_path: Path) -> None:
    original = tmp_path / "in.pdf"
    shutil.copy(corpus.path("single_page"), original)
    symlink = tmp_path / "symlink.pdf"
    symlink.symlink_to(original)

    assert identity_key(original)[0] == "inode"
    assert identity_key(symlink)[0] == "inode"
    assert identity_key(original) == identity_key(symlink)

    result = run_cli(
        "extract", str(original), "-f", "-O", str(symlink), "--pages", "1", "-o", "json"
    )
    _assert_refused_by_signature(result, what="symlink")


def test_ac9_two_distinct_files_with_identical_content_do_not_refuse(
    corpus: Any, tmp_path: Path
) -> None:
    """The negative. Two genuinely distinct paths, byte-identical content,
    must NOT be treated as one destination."""
    original = tmp_path / "in.pdf"
    twin = tmp_path / "twin.pdf"
    shutil.copy(corpus.path("single_page"), original)
    shutil.copy(corpus.path("single_page"), twin)
    assert identity_key(original) != identity_key(twin)

    result = run_cli("extract", str(original), "-f", "-O", str(twin), "--pages", "1", "-o", "json")
    payload = _payload(result)
    assert result.returncode == OK, payload


# --------------------------------------------------------------------------- #
# AC10 -- `--in-place` is untouched. Two of the four E7 arms this criterion
# covers are already regression-tested, unmodified, by
# `test_bulk_clobber_gate.py::test_the_in_place_limb_still_refuses`/
# `test_the_in_place_limb_does_not_fire_twice`; the two arms genuinely NOT
# covered elsewhere -- single-input mutate with a true-hash `.bak`, and
# `--no-backup` suppressing it -- are asserted fresh here.
# --------------------------------------------------------------------------- #


def test_ac10_single_input_in_place_mutates_with_a_true_hash_backup(
    corpus: Any, tmp_path: Path
) -> None:
    doc = tmp_path / "doc.pdf"
    shutil.copy(corpus.path("single_page"), doc)
    true_pre_run = doc.read_bytes()

    result = run_cli("compress", str(doc), "--in-place", "-o", "json", cwd=tmp_path)
    payload = _payload(result)
    assert result.returncode == OK, payload
    backup = tmp_path / "doc.pdf.bak"
    assert backup.exists()
    assert backup.read_bytes() == true_pre_run


def test_ac10_no_backup_suppresses_the_sidecar(corpus: Any, tmp_path: Path) -> None:
    doc = tmp_path / "doc2.pdf"
    shutil.copy(corpus.path("single_page"), doc)
    result = run_cli("compress", str(doc), "--in-place", "--no-backup", "-o", "json", cwd=tmp_path)
    payload = _payload(result)
    assert result.returncode == OK, payload
    assert not (tmp_path / "doc2.pdf.bak").exists()


# --------------------------------------------------------------------------- #
# AC11 -- `--in-place` with a destination flag is still exit 2.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("flag,value", [("--output", None), ("--out-dir", ".")])
def test_ac11_in_place_with_a_destination_flag_is_still_usage_error(
    flag: str, value: str | None, corpus: Any, tmp_path: Path
) -> None:
    """Control: neutralise `_check_in_place_output_conflict` -- the
    combination then reaches the chokepoint, `policy.in_place` suppresses the
    new refusal, and the destruction returns. This is the proof D5's scope is
    exact rather than lucky."""
    doc = tmp_path / "doc.pdf"
    shutil.copy(corpus.path("single_page"), doc)
    args = [str(doc), "--in-place", flag]
    args.append(str(doc) if value is None else value)
    result = run_cli("compress", *args, "-o", "json", cwd=tmp_path)
    payload = _payload(result)
    assert result.returncode == USAGE, payload
    assert payload["error"]["kind"] == "usage"
    assert "mutually exclusive" in payload["error"]["message"]
    assert doc.read_bytes() == corpus.path("single_page").read_bytes()


# --------------------------------------------------------------------------- #
# AC14 -- the eighth subclass is additive and takes nothing from `bf697fd3cd`.
# --------------------------------------------------------------------------- #


def test_ac14_the_new_subclass_is_additive() -> None:
    from pdf_tooling.errors import DestinationIsInputError, RefusedError

    assert "kind" not in DestinationIsInputError.__dict__, (
        "the new class must not override `kind` -- that is `bf697fd3cd`'s row to "
        "take, deliberately not taken here (D11)"
    )
    assert DestinationIsInputError.kind == "refused"
    assert DestinationIsInputError.exit_code == REFUSED
    assert issubclass(DestinationIsInputError, RefusedError)


# --------------------------------------------------------------------------- #
# AC21 -- `check_output_collisions` keeps its precedence.
#
# FALSE AS WRITTEN (reported rather than softened, per this product's own
# four-specs-in-a-row precedent): the spec's own repro, `merge a.pdf a.pdf -O
# out.pdf`, does not refuse today -- `merge_documents`/`cmd_merge.py` call
# `check_output_collisions` from NOWHERE (grep-verified: zero call sites in
# either module), and driven at `0283279` this exact command exits 0. The
# criterion's INTENT -- a duplicate-operand run whose planned TARGETS collide
# with each other must keep refusing through `OutputCollisionError` rather
# than acquiring the new identity refusal -- is real and IS reachable, on a
# verb that actually calls `check_output_collisions` before its planner:
# `compress a.pdf a.pdf --out-dir . --force`, driven here, refuses today at
# `0283279` with `OutputCollisionError`'s own message ("two planned outputs
# resolve to one destination: a.pdf and a.pdf"), because `check_output_collisions`
# runs in `ops/optimize.py` BEFORE `plan_filesystem` is ever called. The
# re-scoped arm below is what proves that ordering is untouched.
# --------------------------------------------------------------------------- #


def test_ac21_check_output_collisions_keeps_its_precedence(corpus: Any, tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    shutil.copy(corpus.path("single_page"), a)
    result = run_cli(
        "compress", str(a), str(a), "--out-dir", str(tmp_path), "--force", "-o", "json"
    )
    payload = _payload(result)
    error = payload["error"]
    assert result.returncode == REFUSED
    assert error["kind"] == "refused"
    assert error["message"] == f"two planned outputs resolve to one destination: {a} and {a}"
    for fragment in SIGNATURE:
        assert fragment not in error["message"], (
            "the new identity refusal must never pre-empt the collision refusal"
        )
