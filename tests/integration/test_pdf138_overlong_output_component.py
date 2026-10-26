"""PDF-138 -- an over-long `-O` destination component refuses at exit 5, in both modes.

At `7b1286b` (2026-10-25, PDF-138 E2/E5) a 300-byte `-O` name made every
single-output writer exit 1 with a raw `OSError [Errno 36]` traceback and empty
stdout, and `--dry-run` either tracebacked (CPython 3.11-3.13, where
`Path.exists` raises `ENAMETOOLONG`) or predicted 0 (3.14, where it swallows it).
After this item a component whose `os.fsencode()` length exceeds 255 bytes is
refused by ONE pure gate (`safety/paths.py::ensure_component_lengths`) that runs
before any `stat`, with `OutputEscapesDirError` -- the class and limit the
`--name` tier already uses. Real and dry answer `5` with one message.

Every matrix cell is a (dry, real) PAIR, each a fresh empty cell directory and a
closed stdin. The "written" oracle is a directory listing, never a payload.
Expected values are literals with provenance, not recomputed from the code under
test. 3.14 is blind to the ordering defects (its `Path.exists` swallows the
error), so the unit arm U1 patches `stat` to raise on an over-long component.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final
from unittest import mock

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

import pdf_tooling  # noqa: E402
from pdf_tooling.errors import OutputEscapesDirError  # noqa: E402
from pdf_tooling.safety import atomic as atomic_module  # noqa: E402
from pdf_tooling.safety import paths as paths_module  # noqa: E402
from pdf_tooling.safety.atomic import AtomicWriter, plan_output_set  # noqa: E402
from pdf_tooling.safety.policy import SafetyPolicy  # noqa: E402
from registry import discover_verbs, run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

SRC_ROOT: Final[Path] = Path(pdf_tooling.__file__).resolve().parent
ATOMIC_SRC: Final[Path] = SRC_ROOT / "safety" / "atomic.py"
NAMING_SRC: Final[Path] = SRC_ROOT / "safety" / "naming.py"

OK: Final[int] = 0
FAILURE: Final[int] = 1
USAGE: Final[int] = 2
REFUSED: Final[int] = 5

#: The names, byte counts included (PDF-138 E2). `.pdf` is part of the count.
N255: Final[str] = "a" * 251 + ".pdf"
N256: Final[str] = "a" * 252 + ".pdf"
N300: Final[str] = "a" * 296 + ".pdf"
MB255: Final[str] = "é" * 125 + "a.pdf"  # 255 bytes
MB256: Final[str] = "é" * 126 + ".pdf"  # 256 bytes, 130 characters
PARENT: Final[str] = "a" * 256 + "/x.pdf"
NAME_BYTES: Final[dict[str, int]] = {N255: 255, N256: 256, N300: 300, MB255: 255, MB256: 256}
PARENT_COMPONENT_BYTES: Final[int] = 256

SIX: Final[tuple[str, ...]] = ("rotate", "compress", "repair", "meta set", "watermark", "merge")
REFUSED_NAMES: Final[tuple[str, ...]] = (N256, N300, MB256)
ACCEPTED_NAMES: Final[tuple[str, ...]] = (N255, MB255)

#: The population literal, measured at `7b1286b` on 3.14 (2026-10-25, AC7).
POPULATION: Final[tuple[str, ...]] = (
    "compose",
    "compress",
    "convert",
    "create",
    "decrypt",
    "delete",
    "encrypt",
    "extract",
    "linearize",
    "merge",
    "meta set",
    "ocr",
    "reorder",
    "repair",
    "rotate",
    "stamp",
    "tables",
    "text",
    "watermark",
)
#: The other seven, one reason each (AC7).
EXCLUSIONS: Final[dict[str, str]] = {
    "info": "writes no files; -O rejected by _check_safety_flag_consumption",
    "doctor": "writes no files; -O rejected by _check_safety_flag_consumption",
    "version": "writes no files; -O rejected by _check_safety_flag_consumption",
    "permissions": "writes no files; -O rejected by _check_safety_flag_consumption",
    "meta get": "writes no files; -O rejected by _check_safety_flag_consumption",
    "split": "multi-output; -O rejected by _check_output_flag_consumption",
    "rasterize": "multi-output; -O rejected by _check_output_flag_consumption",
}

#: PDF-138 E5 literals, measured at `7b1286b` (identical on 3.11 and 3.14).
NAME_TIER_MESSAGE: Final[str] = (
    "the rendered output name is 305 bytes, over the 255-byte filename limit: '"
    + "a" * 300
    + "1.pdf'"
)


# --------------------------------------------------------------------------- #
# Inputs and cells
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def inputs(corpus: Any, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Read-only inputs, built once. Outputs always go to a separate cell."""
    from PIL import Image

    from corpus import ENCRYPTED_PASSWORD
    from registry import _password_file

    root = tmp_path_factory.mktemp("pdf138-inputs")
    made: dict[str, Path] = {}
    for key, fixture in (
        ("single", "single_page"),
        ("single2", "single_page"),
        ("ten", "ten_page_text"),
        ("tab", "tabular"),
        ("enc", "encrypted_aes256"),
        ("stamp_source", "stamp_source"),
    ):
        made[key] = root / f"{key}.pdf"
        shutil.copy(corpus.path(fixture), made[key])
    made["jpg"] = root / "in.jpg"
    Image.new("RGB", (64, 48), (10, 120, 200)).save(made["jpg"], format="JPEG", quality=85)
    made["txt"] = root / "in.txt"
    made["txt"].write_text("PDF-138 probe text\n")
    made["owner_pw"] = _password_file(root, "owner.pw", "pdf138-owner-pw")
    made["user_pw"] = _password_file(root, "user.pw", ENCRYPTED_PASSWORD)
    return made


Builder = Callable[[dict[str, Path]], list[str]]


def _single(i: dict[str, Path]) -> list[str]:
    return [str(i["single"])]


def _pages_ten(i: dict[str, Path]) -> list[str]:
    return [str(i["ten"]), "--pages", "1"]


#: Minimal valid argv (operands and required flags, never `-O`) per verb.
BUILDERS: Final[dict[str, Builder]] = {
    "compose": lambda i: [str(i["jpg"])],
    "compress": _single,
    "convert": lambda i: [str(i["txt"])],
    "create": lambda i: [str(i["txt"])],
    "decrypt": lambda i: [str(i["enc"]), "--password-file", str(i["user_pw"])],
    "delete": _pages_ten,
    "encrypt": lambda i: [str(i["single"]), "--owner-password-file", str(i["owner_pw"])],
    "extract": _pages_ten,
    "linearize": _single,
    "merge": lambda i: [str(i["single"]), str(i["single2"])],
    "meta set": lambda i: [str(i["single"]), "--title", "PDF-138-probe"],
    "ocr": lambda i: [str(i["single"]), "--skip-text-pages"],
    "reorder": _pages_ten,
    "repair": _single,
    "rotate": lambda i: [str(i["ten"]), "--pages", "1", "--angle", "90"],
    "stamp": lambda i: [str(i["single"]), "--from", str(i["stamp_source"])],
    "tables": lambda i: [str(i["tab"])],
    "text": _single,
    "watermark": lambda i: [str(i["single"]), "--text", "PDF-138"],
    # exclusions
    "info": _single,
    "doctor": lambda i: [],
    "version": lambda i: [],
    "permissions": _single,
    "meta get": _single,
    "split": lambda i: [str(i["single"]), "--each-page"],
    "rasterize": _single,
}


def _office_present() -> bool:
    from pdf_tooling.ports.office import office_binary_present

    return bool(office_binary_present())


def _new_cell(tmp_path: Path, label: str) -> Path:
    """A fresh empty directory under *tmp_path*; repeated labels get a suffix."""
    cell = tmp_path / label
    suffix = 0
    while cell.exists():
        suffix += 1
        cell = tmp_path / f"{label}-{suffix}"
    cell.mkdir()
    return cell


def _run(
    verb: str,
    inputs: dict[str, Path],
    cell: Path,
    *extra: str,
    dry: bool,
    output: str | None = "x.pdf",
) -> subprocess.CompletedProcess[str]:
    """One run of *verb* in the empty *cell* (cwd). `-O` is relative to the cell."""
    env = dict(os.environ)
    env["HOME"] = str(cell.parent / "home")
    argv = [verb, *BUILDERS[verb](inputs), *extra]
    if output is not None:
        argv += ["-O", output]
    if dry:
        argv.append("--dry-run")
    argv += ["-o", "json"]
    return run_cli(*argv, cwd=cell, env=env)


def _listing(cell: Path) -> list[str]:
    return sorted(entry.name for entry in cell.iterdir())


def _doc(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"stdout was not exactly one JSON document ({error}); "
            f"rc={result.returncode} stdout={result.stdout[:300]!r} "
            f"stderr={result.stderr[-500:]!r}"
        ) from None
    assert isinstance(parsed, dict)
    assert parsed.get("schema_version") == 1, parsed.get("schema_version")
    return parsed


def _real_refusal(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    doc = _doc(result)
    error = doc.get("error")
    assert isinstance(error, dict), f"no error envelope: {str(doc)[:400]}"
    return error


def _dry_refusal(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """The first refusing item, as `{code, kind, message}` where published."""
    doc = _doc(result)
    assert doc.get("dry_run") is True, str(doc)[:300]
    assert doc.get("exit_code") == result.returncode, (doc.get("exit_code"), result.returncode)
    refusing = [
        item
        for item in doc.get("items", [])
        if item.get("exit_code") == REFUSED and not item.get("ok", True)
    ]
    assert refusing, f"no refusing item in dry envelope: {str(doc)[:500]}"
    item = refusing[0]
    detail = item.get("detail") or {}
    if "would_refuse" in detail:
        assert detail.get("would_exit") == REFUSED, detail
        return dict(detail["would_refuse"])
    return {"code": item["exit_code"], "kind": "refused", "message": item["message"]}


def _assert_no_traceback(*results: subprocess.CompletedProcess[str]) -> None:
    for result in results:
        assert "Traceback" not in result.stderr, result.stderr[-800:]
        assert "Traceback" not in result.stdout, result.stdout[-800:]


def _assert_refused_pair(
    verb: str,
    inputs: dict[str, Path],
    tmp_path: Path,
    name: str,
    *,
    size: int,
    extra: tuple[str, ...] = (),
) -> None:
    """The AC1 pair: dry 5 / real 5, same message, no traceback, nothing written."""
    dry_cell = _new_cell(tmp_path, "dry")
    real_cell = _new_cell(tmp_path, "real")
    dry = _run(verb, inputs, dry_cell, *extra, dry=True, output=name)
    real = _run(verb, inputs, real_cell, *extra, dry=False, output=name)
    where = f"{verb} -O <{len(name.encode())}B>"
    assert (dry.returncode, real.returncode) == (REFUSED, REFUSED), (
        f"{where}: expected (dry, real) == (5, 5), got ({dry.returncode}, {real.returncode}); "
        f"dry stderr={dry.stderr[-300:]!r} real stderr={real.stderr[-300:]!r}"
    )
    _assert_no_traceback(dry, real)
    error = _real_refusal(real)
    assert error["code"] == REFUSED and error["kind"] == "refused", error
    assert "-byte filename limit" in error["message"], error["message"]
    assert f"{size} bytes" in error["message"], error["message"]
    assert error["path"] == name, "path must echo the -O argument as typed"
    refusal = _dry_refusal(dry)
    assert (refusal["code"], refusal["kind"]) == (REFUSED, "refused"), refusal
    assert refusal["message"] == error["message"], (refusal["message"], error["message"])
    assert _listing(dry_cell) == [], f"{where}: dry run wrote {_listing(dry_cell)}"
    assert _listing(real_cell) == [], f"{where}: real run left {_listing(real_cell)}"


# --------------------------------------------------------------------------- #
# M1 / AC1 -- refused pairs
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", REFUSED_NAMES, ids=["N256", "N300", "MB256"])
@pytest.mark.parametrize("verb", SIX)
def test_ac1_refused_pairs(verb: str, name: str, inputs: dict[str, Path], tmp_path: Path) -> None:
    """RED at `7b1286b`: real rc 1 + Traceback (3.11-3.14); dry rc 1 (3.11-3.13)
    or rc 0 `ok: true` (3.14)."""
    _assert_refused_pair(verb, inputs, tmp_path, name, size=NAME_BYTES[name])


# --------------------------------------------------------------------------- #
# M2 / AC2 -- accepted pairs, the off-by-one arm
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ACCEPTED_NAMES, ids=["N255", "MB255"])
@pytest.mark.parametrize("verb", SIX)
def test_ac2_accepted_pairs(verb: str, name: str, inputs: dict[str, Path], tmp_path: Path) -> None:
    """255 bytes is the limit, not over it: a `>=` gate refuses these cells."""
    dry_cell = _new_cell(tmp_path, "dry")
    real_cell = _new_cell(tmp_path, "real")
    dry = _run(verb, inputs, dry_cell, dry=True, output=name)
    real = _run(verb, inputs, real_cell, dry=False, output=name)
    assert (dry.returncode, real.returncode) == (OK, OK), (
        f"{verb}: ({dry.returncode}, {real.returncode}); dry={dry.stdout[:300]!r} "
        f"real={real.stdout[:300]!r}"
    )
    _assert_no_traceback(dry, real)
    dry_doc = _doc(dry)
    for item in dry_doc.get("items", []):
        assert (item.get("detail") or {}).get("would_exit", 0) == 0, item
    assert _listing(dry_cell) == []
    assert _listing(real_cell) == [name], _listing(real_cell)


# --------------------------------------------------------------------------- #
# AC3 -- bytes, not characters
# --------------------------------------------------------------------------- #


def test_ac3_bytes_not_characters(inputs: dict[str, Path], tmp_path: Path) -> None:
    """MB255 and MB256 are both 130-ish characters; only the byte count differs."""
    assert len(MB256) < 255 and len(MB255) < 255, "both are under 255 CHARACTERS"
    assert len(MB255.encode()) == 255 and len(MB256.encode()) == 256

    def pair(name: str, label: str) -> tuple[int, int]:
        dry = _run("rotate", inputs, _new_cell(tmp_path, f"{label}-d"), dry=True, output=name)
        real = _run("rotate", inputs, _new_cell(tmp_path, f"{label}-r"), dry=False, output=name)
        return dry.returncode, real.returncode

    assert pair(MB255, "mb255") == (OK, OK)
    assert pair(MB256, "mb256") == (REFUSED, REFUSED)


# --------------------------------------------------------------------------- #
# AC4 -- every component, not only the last
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", SIX)
def test_ac4_parent_component_pairs(verb: str, inputs: dict[str, Path], tmp_path: Path) -> None:
    """A 256-byte PARENT component refuses (5, 5). A last-component-only gate
    gave rc 1 "does not exist" on 3.14 and a traceback on 3.11-3.13."""
    _assert_refused_pair(verb, inputs, tmp_path, PARENT, size=PARENT_COMPONENT_BYTES)


# --------------------------------------------------------------------------- #
# U1 / AC5 -- the gate precedes every stat, on every interpreter
# --------------------------------------------------------------------------- #

LONG: Final[Path] = Path("a" * 296 + ".pdf")


def _policy(**overrides: Any) -> SafetyPolicy:
    values: dict[str, Any] = {
        "dry_run": False,
        "force": False,
        "in_place": False,
        "backup": False,
        "assume_yes": False,
        "is_tty": False,
        "threads": 1,
    }
    values.update(overrides)
    return SafetyPolicy(**values)


def _too_long(path: Any) -> bool:
    try:
        text = os.fspath(path)
    except TypeError:
        return False
    return any(len(os.fsencode(part)) > 255 for part in Path(text).parts)


@contextmanager
def _stat_forbidden_on_overlong() -> Iterator[None]:
    """Any `stat`/`lstat` handed an over-long component is a defect: raise
    `AssertionError`, which no `except OSError` in the product can swallow."""
    real_stat, real_lstat = os.stat, os.lstat
    real_path_stat, real_path_lstat = Path.stat, Path.lstat

    def guard(real: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(path: Any, *args: Any, **kwargs: Any) -> Any:
            if _too_long(path):
                raise AssertionError(f"stat reached an over-long component: {str(path)[:40]}...")
            return real(path, *args, **kwargs)

        return wrapper

    def guard_method(real: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(self: Path, *args: Any, **kwargs: Any) -> Any:
            if _too_long(self):
                raise AssertionError(f"Path.stat reached an over-long component: {str(self)[:40]}")
            return real(self, *args, **kwargs)

        return wrapper

    with (
        mock.patch.object(os, "stat", guard(real_stat)),
        mock.patch.object(os, "lstat", guard(real_lstat)),
        mock.patch.object(Path, "stat", guard_method(real_path_stat)),
        mock.patch.object(Path, "lstat", guard_method(real_path_lstat)),
    ):
        yield


def test_ac5_gate_precedes_every_stat(tmp_path: Path) -> None:
    """The planner and the writer's `_plan` each refuse before any `stat`.

    The CLI-level merge cells cannot see an ordering break on 3.14 (its
    `Path.exists` returns False); this arm can."""
    # real: plan_output_set raises
    with _stat_forbidden_on_overlong(), pytest.raises(OutputEscapesDirError) as planned:
        plan_output_set([LONG], out_dir=None, policy=_policy(), sources=[])
    assert type(planned.value) is OutputEscapesDirError
    # dry: plan_output_set captures
    with _stat_forbidden_on_overlong():
        outcome = plan_output_set([LONG], out_dir=None, policy=_policy(dry_run=True), sources=[])
    assert type(outcome.refusal) is OutputEscapesDirError
    # real: AtomicWriter._plan raises (constructed OUTSIDE the guard: __init__ canonicalises)
    writer = AtomicWriter(LONG, policy=_policy())
    with _stat_forbidden_on_overlong(), pytest.raises(OutputEscapesDirError) as writer_error:
        writer._plan()
    assert type(writer_error.value) is OutputEscapesDirError
    # dry: AtomicWriter._plan captures
    dry_writer = AtomicWriter(LONG, policy=_policy(dry_run=True))
    dry_writer._dry_run = True
    with _stat_forbidden_on_overlong():
        dry_writer._plan()
    assert type(dry_writer.planned_refusal) is OutputEscapesDirError
    # the PARENT spelling, through both
    parent = Path(PARENT)
    with _stat_forbidden_on_overlong(), pytest.raises(OutputEscapesDirError):
        plan_output_set([parent], out_dir=None, policy=_policy(), sources=[])
    # a clean spelling still stats (non-vacuity): the guard does not blind the planner
    with _stat_forbidden_on_overlong():
        clean = plan_output_set(
            [tmp_path / "ok.pdf"], out_dir=None, policy=_policy(dry_run=True), sources=[]
        )
    assert clean.refusal is None


# --------------------------------------------------------------------------- #
# M3 / AC6 -- `--force` does not route around the gate
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("verb", ["merge", "rotate"])
def test_ac6_force_does_not_bypass(verb: str, inputs: dict[str, Path], tmp_path: Path) -> None:
    """`merge --force` reaches `target_exists` at `cmd_merge.py` (the L1 guard)
    BEFORE any planner: on 3.11-3.13 that is a traceback unless the predicate
    answers False for an over-long spelling. 3.14 cannot see this break."""
    assert paths_module.target_exists(N300) is False
    assert paths_module.target_exists(PARENT) is False
    _assert_refused_pair(verb, inputs, tmp_path, N300, size=300, extra=("--force",))


# --------------------------------------------------------------------------- #
# M4 / AC7 -- the whole single-output `-O` population, derived by behaviour
# --------------------------------------------------------------------------- #

_TRACEBACK = "Traceback"


def _probe_member(verb: str, inputs: dict[str, Path], tmp_path: Path) -> bool:
    """Probe P (AC7): `<verb> <argv> -O x.pdf --dry-run`, in a fresh empty cell."""
    cell = _new_cell(tmp_path, "probe-" + verb.replace(" ", "-"))
    result = _run(verb, inputs, cell, dry=True, output="x.pdf")
    if result.returncode != OK or _TRACEBACK in result.stderr or _listing(cell):
        return False
    try:
        doc = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    outputs = {
        item["output"]
        for item in doc.get("items", [])
        if isinstance(item, dict) and item.get("output") is not None
    }
    return outputs == {"x.pdf"}


def _expected_population() -> tuple[str, ...]:
    return tuple(v for v in POPULATION if v != "convert" or _office_present())


def test_ac7_population_matches_probe(inputs: dict[str, Path], tmp_path: Path) -> None:
    universe = {v.name for v in discover_verbs()}
    assert len(universe) == 26, sorted(universe)
    assert set(POPULATION) | set(EXCLUSIONS) == universe, (
        f"unclassified leaf: {sorted(universe - set(POPULATION) - set(EXCLUSIONS))}; "
        f"stale: {sorted((set(POPULATION) | set(EXCLUSIONS)) - universe)}"
    )
    assert not set(POPULATION) & set(EXCLUSIONS)
    assert (len(POPULATION), len(EXCLUSIONS)) == (19, 7)
    derived = tuple(sorted(v for v in sorted(universe) if _probe_member(v, inputs, tmp_path)))
    assert derived == tuple(sorted(_expected_population())), (
        f"derived population {derived} != literal {sorted(_expected_population())}"
    )


#: The two population members whose operand only an out-of-process engine can
#: finally judge (the census's `engine-blind` verbs). They are asserted together,
#: in ONE arm below, so the ratchet's ungated count for this module is the
#: smallest it can honestly be.
ENGINE_BLIND: Final[frozenset[str]] = frozenset({"convert", "ocr"})
PAIR_VERBS: Final[tuple[str, ...]] = tuple(v for v in POPULATION if v not in ENGINE_BLIND)


@pytest.mark.parametrize("verb", PAIR_VERBS)
def test_ac7_population_pairs(verb: str, inputs: dict[str, Path], tmp_path: Path) -> None:
    _assert_refused_pair(verb, inputs, tmp_path, N300, size=300)


def test_ac7_engine_blind_members(inputs: dict[str, Path], tmp_path: Path) -> None:
    """`ocr` runs with `--skip-text-pages` (no engine needed): (5, 5). `convert`
    is (5, 5) when `soffice` is present; when it is absent its P answer is
    rc 3 `engine_missing` and its pair is not assertable on this host."""
    _assert_refused_pair("ocr", inputs, tmp_path, N300, size=300)
    if _office_present():
        _assert_refused_pair("convert", inputs, tmp_path, N300, size=300)
        return
    result = _run(
        "convert", inputs, _new_cell(tmp_path, "convert-absent"), dry=True, output="x.pdf"
    )
    assert result.returncode == 3, result.stdout[:300]
    assert _real_or_dry_kind(result) == "engine_missing"


def _real_or_dry_kind(result: subprocess.CompletedProcess[str]) -> str | None:
    doc = _doc(result)
    if "error" in doc:
        return str(doc["error"].get("kind"))
    for item in doc.get("items", []):
        would = (item.get("detail") or {}).get("would_refuse")
        if would:
            return str(would.get("kind"))
    return None


@pytest.mark.parametrize("verb", sorted(EXCLUSIONS))
def test_ac7_exclusions_answer_usage(verb: str, inputs: dict[str, Path], tmp_path: Path) -> None:
    """The usage gate stays in front of the length gate: (2, 2), `kind: usage`."""
    dry_cell = _new_cell(tmp_path, "dry")
    real_cell = _new_cell(tmp_path, "real")
    dry = _run(verb, inputs, dry_cell, dry=True, output=N300)
    real = _run(verb, inputs, real_cell, dry=False, output=N300)
    assert (dry.returncode, real.returncode) == (USAGE, USAGE), (
        f"{verb}: ({dry.returncode}, {real.returncode}) {real.stdout[:200]!r}"
    )
    _assert_no_traceback(dry, real)
    for result in (dry, real):
        error = _real_refusal(result)
        assert error["kind"] == "usage", error
        assert "does not accept --output" in error["message"], error["message"]
    assert _listing(dry_cell) == [] and _listing(real_cell) == []


# --------------------------------------------------------------------------- #
# AC8 -- the dry run is pure
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", [N300, PARENT], ids=["N300", "PARENT"])
@pytest.mark.parametrize("verb", ["merge", "create", "compose", "rotate", "repair"])
def test_ac8_dry_is_pure(verb: str, name: str, inputs: dict[str, Path], tmp_path: Path) -> None:
    """No dry cell leaves anything behind or regains the base answer
    (`ok: true`, `would_exit` 0)."""
    cell = _new_cell(tmp_path, "dry")
    result = _run(verb, inputs, cell, dry=True, output=name)
    assert result.returncode == REFUSED, (result.returncode, result.stdout[:300])
    doc = _doc(result)
    assert doc["exit_code"] == REFUSED
    assert not all(item.get("ok") for item in doc["items"]), "the preview must not say ok: true"
    assert _listing(cell) == []


# --------------------------------------------------------------------------- #
# M5 / AC9 -- the precedents keep their answers and their precedence
# --------------------------------------------------------------------------- #


def test_ac9_precedents_unchanged(inputs: dict[str, Path], tmp_path: Path) -> None:
    single = str(inputs["single"])
    # --name tier: rc 5 both modes, message byte-identical (E5 literal)
    name_args = [
        "split",
        single,
        "--each-page",
        "--out-dir",
        "sd",
        "--name",
        "a" * 300 + "{page}.pdf",
        "-o",
        "json",
    ]
    for dry in (True, False):
        cell = _new_cell(tmp_path, f"name-{dry}")
        result = run_cli(*name_args, *(["--dry-run"] if dry else []), cwd=cell)
        assert result.returncode == REFUSED, (dry, result.returncode, result.stdout[:300])
        refusal = _dry_refusal_any(result)
        assert refusal["message"] == NAME_TIER_MESSAGE, refusal["message"][:120]
        assert refusal["kind"] == "refused"
    # --out-dir tier: rc 1 both modes, PDF-64's own messages, gate stays behind it
    long_dir = "a" * 300
    for argv in (
        ["split", single, "--each-page", "--out-dir", long_dir],
        ["rotate", single, "--pages", "1", "--angle", "90", "--out-dir", long_dir],
    ):
        for dry in (True, False):
            cell = _new_cell(tmp_path, f"outdir-{argv[0]}-{dry}")
            result = run_cli(*argv, "-o", "json", *(["--dry-run"] if dry else []), cwd=cell)
            assert result.returncode == FAILURE, (argv[0], dry, result.stdout[:300])
            _assert_no_traceback(result)
            message = str((_dry_refusal_any(result) if dry else _real_refusal(result))["message"])
            if dry:
                assert "cannot be created" in message and "255-byte name limit" in message
            else:
                assert "could not be created" in message and "File name too long" in message
            assert "-byte filename limit" not in message, "the PDF-138 gate stepped in front"


def _dry_refusal_any(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """A dry refusal whatever its exit code (the `--out-dir` tier answers 1)."""
    doc = _doc(result)
    if "error" in doc:
        return dict(doc["error"])
    for item in doc["items"]:
        would = (item.get("detail") or {}).get("would_refuse")
        if would:
            return dict(would)
        if not item.get("ok", True):
            return {"message": item["message"]}
    raise AssertionError(f"no refusal in dry envelope: {str(doc)[:400]}")


# --------------------------------------------------------------------------- #
# U2 / AC10, AC12, AC13 -- the pins
# --------------------------------------------------------------------------- #


def _module_level_literal_255_assignments() -> list[str]:
    found: list[str] = []
    for source in sorted(SRC_ROOT.rglob("*.py")):
        for node in ast.parse(source.read_text(encoding="utf-8")).body:
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                value = node.value
            if isinstance(value, ast.Constant) and value.value == 255 and value is not None:
                found.append(str(source.relative_to(SRC_ROOT)))
    return found


def test_ac10_one_limit() -> None:
    assert paths_module.MAX_COMPONENT_BYTES == 255
    tree = ast.parse(NAMING_SRC.read_text(encoding="utf-8"))
    assigned = [
        node
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "_MAX_COMPONENT_BYTES"
    ]
    assert len(assigned) == 1
    value = assigned[0].value
    assert isinstance(value, ast.Name) and value.id == "MAX_COMPONENT_BYTES", ast.dump(value)  # type: ignore[arg-type]
    assert _module_level_literal_255_assignments() == ["safety/paths.py"]


#: sha256 of `AtomicWriter._replace`'s exact source at `7b1286b` (PDF-138 AC12).
REPLACE_SOURCE_SHA256: Final[str] = (
    "eedcfcdbade0cad731b8f260a76be60168c3ab5923407b59911e3c77fd3d7b36"
)
#: `except OSError` handlers in `atomic.py` at `7b1286b`.
OSERROR_HANDLERS_AT_BASE: Final[int] = 6


def test_ac12_replace_is_byte_unchanged() -> None:
    source = ATOMIC_SRC.read_text(encoding="utf-8")
    tree = ast.parse(source)
    replaces = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_replace"
    ]
    assert len(replaces) == 1
    segment = ast.get_source_segment(source, replaces[0])
    assert segment is not None
    assert hashlib.sha256(segment.encode("utf-8")).hexdigest() == REPLACE_SOURCE_SHA256, (
        "AtomicWriter._replace changed: the ENCODING half (2b88707a36) is out of scope (X-1068)"
    )
    handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and isinstance(node.type, ast.Name)
        and node.type.id == "OSError"
    ]
    assert len(handlers) == OSERROR_HANDLERS_AT_BASE, "atomic.py gained an `except OSError`"
    identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "ENAMETOOLONG" not in identifiers, "atomic.py must not classify ENAMETOOLONG"


def test_ac13_reuses_the_refusal_class(tmp_path: Path) -> None:
    from pdf_tooling import errors

    with pytest.raises(OutputEscapesDirError) as caught:
        paths_module.ensure_component_lengths(N300)
    assert type(caught.value) is OutputEscapesDirError
    assert caught.value.exit_code == REFUSED
    refusal_subclasses = [
        name
        for name, cls in vars(errors).items()
        if isinstance(cls, type)
        and issubclass(cls, errors.RefusedError)
        and cls is not errors.RefusedError
    ]
    assert len(refusal_subclasses) == 9, refusal_subclasses
    assert atomic_module.ensure_component_lengths is paths_module.ensure_component_lengths


# --------------------------------------------------------------------------- #
# M6 / AC11 -- aliases and spelling (GR-009)
# --------------------------------------------------------------------------- #


def test_ac11_alias_and_spelling(inputs: dict[str, Path], tmp_path: Path) -> None:
    real_dir = tmp_path / "realdir"
    real_dir.mkdir()
    # alias/N255 through a symlinked directory lands in the real directory
    for dry in (True, False):
        cell = _new_cell(tmp_path, f"alias-{dry}")
        (cell / "alias").symlink_to(real_dir)
        result = _run("rotate", inputs, cell, dry=dry, output=f"alias/{N255}")
        assert result.returncode == OK, (dry, result.stdout[:300], result.stderr[-300:])
        assert _listing(real_dir) == ([] if dry else [N255])
    # alias/N256 refuses (5, 5)
    for dry in (True, False):
        cell = _new_cell(tmp_path, f"alias256-{dry}")
        (cell / "alias").symlink_to(real_dir)
        result = _run("rotate", inputs, cell, dry=dry, output=f"alias/{N256}")
        assert result.returncode == REFUSED, (dry, result.stdout[:300])
    assert _listing(real_dir) == [N255]
    # ~/N256: refused, path echoes the spelling as typed
    for dry in (True, False):
        cell = _new_cell(tmp_path, f"tilde-{dry}")
        (cell.parent / "home").mkdir(exist_ok=True)
        result = _run("rotate", inputs, cell, dry=dry, output=f"~/{N256}")
        assert result.returncode == REFUSED, (dry, result.stdout[:300])
        refusal = _dry_refusal(result) if dry else _real_refusal(result)
        assert "-byte filename limit" in refusal["message"]
        if not dry:
            assert refusal["path"].startswith("~/"), refusal["path"]
            assert refusal["path"] == f"~/{N256}"
    assert _listing(cell.parent / "home") == []
