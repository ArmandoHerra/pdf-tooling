"""PDF-156 (X-1209) -- every ``AtomicWriter`` safety warning is also published in
the result envelope's ``warnings``.

The defect: ``compress good.pdf -O L/out.pdf -f -o json``, where ``L`` is a
symlink onto another filesystem, printed ``warning: atomicity degraded: ...`` on
stderr and published only the cosmetic ``did not shrink`` warning. A populated
``warnings`` list that is incomplete reads as complete.

Provenance of every literal below: measured at ``e83c743`` (``v1.3.0-1``) on
2026-10-28 (PDF-156 E2/E4) and re-measured at ``7d3b593`` (``v1.3.1``) on
2026-10-29; the base ``warnings`` of the only two leaves that carry a non-writer
entry (``compress``: ``did not shrink``; ``merge``: the later inputs' ``/Info``
carriage) are the literals in :data:`BASE_ENTRIES`.

Conventions follow ``test_cross_filesystem.py``: a REAL second filesystem (on
Linux a missing one is a FAILURE naming the ladder, elsewhere a skip, never a
vacuous pass), every cell in a fresh directory so every destination name is
fresh (``declared_device`` lstats the first existing ancestor; an existing file
or a verb-made real ``--out-dir`` makes the named and actual devices agree and
the warning legitimately never fires), subprocess cells through ``run_cli`` with
stdin closed. Expected text is built from the product's own template with the
cell's real values and asserted by EQUALITY.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import os
import pickle
import re
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pytest

from pdf_tooling.models import ItemResult, OperationResult
from pdf_tooling.safety import DEGRADED_PREFIX, AtomicWriter
from pdf_tooling.safety.paths import canonical
from pdf_tooling.safety.policy import SafetyPolicy

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from integration.test_cross_filesystem import (  # noqa: E402
    LADDER_MESSAGE,
    find_second_filesystem,
)
from registry import REPO_ROOT, discover_verbs, run_cli  # noqa: E402

# --------------------------------------------------------------------------- #
# Lazy access to the symbols PDF-156 adds. They are resolved when a test USES
# them, never at import, so this module collects on a tree that lacks them and
# the affected tests fail on an assertion naming the missing behaviour.
# --------------------------------------------------------------------------- #


def _added(module: str, *names: str) -> tuple[Any, ...]:
    try:
        loaded = importlib.import_module(module)
    except ImportError as exc:
        raise AssertionError(f"PDF-156: importing {module} failed: {exc!r}") from exc
    missing = [name for name in names if not hasattr(loaded, name)]
    assert not missing, f"PDF-156 behaviour is absent: {module} does not provide {missing}"
    return tuple(getattr(loaded, name) for name in names)


def test_added_names_the_original_import_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PDF-163 / B-551 (2): a module whose own import fails is reported with
    the symbol that failed, chained, never as a bare 'does not provide'."""
    (tmp_path / "ghost_pdf163.py").write_text(
        "from pdf_tooling.safety.writer_warnings import _no_such_symbol_pdf163\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "ghost_pdf163", raising=False)
    with pytest.raises(AssertionError) as caught:
        _added("ghost_pdf163", "x")
    assert isinstance(caught.value.__cause__, ImportError)
    assert "_no_such_symbol_pdf163" in str(caught.value)
    with pytest.raises(AssertionError) as absent:
        _added("pdf_tooling.no_such_module_pdf163", "x")
    assert isinstance(absent.value.__cause__, ModuleNotFoundError)
    with pytest.raises(AssertionError, match=r"does not provide \['no_such_attr'\]"):
        _added("pdf_tooling.ops.carriage", "no_such_attr")


def merge_writer_warnings(existing: Any) -> list[str]:
    (func,) = _added("pdf_tooling.ops.carriage", "merge_writer_warnings")
    return func(existing)  # type: ignore[no-any-return]


def publish_writer_warnings(result: Any) -> Any:
    (func,) = _added("pdf_tooling.ops.carriage", "publish_writer_warnings")
    return func(result)


def open_writer_warnings() -> Any:
    (func,) = _added("pdf_tooling.safety.writer_warnings", "open_writer_warnings")
    return func()


def close_writer_warnings(token: Any) -> None:
    (func,) = _added("pdf_tooling.safety.writer_warnings", "close_writer_warnings")
    func(token)


def record_writer_warnings(messages: Any) -> None:
    (func,) = _added("pdf_tooling.safety.writer_warnings", "record_writer_warnings")
    func(messages)


def writer_warnings() -> tuple[str, ...]:
    (func,) = _added("pdf_tooling.safety.writer_warnings", "writer_warnings")
    return func()  # type: ignore[no-any-return]


def rendered_chunk_class() -> Any:
    (cls,) = _added("pdf_tooling.ops.raster", "_RenderedChunk")
    return cls


SRC: Final[Path] = REPO_ROOT / "src" / "pdf_tooling"
STDERR_PREFIX: Final[str] = "warning: "

#: PDF-156 E4, 21 writing leaves (the OR-3 output-flag declaration, not `is_mutating`).
WRITING_LEAVES: Final[tuple[str, ...]] = (
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
    "rasterize",
    "reorder",
    "repair",
    "rotate",
    "split",
    "stamp",
    "tables",
    "text",
    "watermark",
)

MERGE_INFO_ENTRY: Final[str] = (
    "good2.pdf: merge does not carry the input's document /Info to its output"
)

# leaf -> (argv through `L`, the target spellings the run writes, in plan order)
LEAF_CELLS: Final[dict[str, tuple[tuple[str, ...], tuple[str, ...]]]] = {
    "compress": (("compress", "good.pdf", "-O", "L/x.pdf", "-f"), ("L/x.pdf",)),
    "repair": (("repair", "good.pdf", "-O", "L/x.pdf"), ("L/x.pdf",)),
    "linearize": (("linearize", "good.pdf", "-O", "L/x.pdf"), ("L/x.pdf",)),
    "merge": (("merge", "good.pdf", "good2.pdf", "-O", "L/x.pdf"), ("L/x.pdf",)),
    "split": (
        ("split", "multi.pdf", "--each-page", "--out-dir", "L", "--name", "s-{page}.{ext}"),
        ("L/s-1.pdf", "L/s-2.pdf", "L/s-3.pdf"),
    ),
    "extract": (("extract", "multi.pdf", "--pages", "1", "-O", "L/x.pdf"), ("L/x.pdf",)),
    "delete": (("delete", "multi.pdf", "--pages", "1", "-O", "L/x.pdf"), ("L/x.pdf",)),
    "rotate": (
        ("rotate", "good.pdf", "--angle", "90", "--pages", "1", "-O", "L/x.pdf"),
        ("L/x.pdf",),
    ),
    "reorder": (("reorder", "multi.pdf", "--pages", "2,1", "-O", "L/x.pdf"), ("L/x.pdf",)),
    "encrypt": (
        (
            "encrypt",
            "good.pdf",
            "--user-password-file",
            "pw",
            "--owner-password-file",
            "pw",
            "-O",
            "L/x.pdf",
        ),
        ("L/x.pdf",),
    ),
    "decrypt": (
        ("decrypt", "enc.pdf", "--password-file", "pw", "-O", "L/x.pdf"),
        ("L/x.pdf",),
    ),
    "watermark": (
        ("watermark", "good.pdf", "--text", "DRAFT", "-O", "L/x.pdf"),
        ("L/x.pdf",),
    ),
    "stamp": (("stamp", "good.pdf", "--from", "good2.pdf", "-O", "L/x.pdf"), ("L/x.pdf",)),
    "meta set": (("meta", "set", "good.pdf", "--title", "t", "-O", "L/x.pdf"), ("L/x.pdf",)),
    "create": (("create", "a.txt", "-O", "L/x.pdf"), ("L/x.pdf",)),
    "compose": (("compose", "p.png", "p.png", "-O", "L/x.pdf"), ("L/x.pdf",)),
    "convert": (("convert", "a.txt", "-O", "L/x.pdf"), ("L/x.pdf",)),
    "ocr": (("ocr", "good.pdf", "-O", "L/x.pdf"), ("L/x.pdf",)),
    "rasterize": (
        ("rasterize", "multi.pdf", "--out-dir", "L", "--name", "r-{page}.{ext}"),
        ("L/r-1.png", "L/r-2.png", "L/r-3.png"),
    ),
    "text": (("text", "good.pdf", "-O", "L/x.txt"), ("L/x.txt",)),
    "tables": (("tables", "tabular.pdf", "-O", "L/x.csv"), ("L/x.csv",)),
}

#: The two engine-blind leaves only an out-of-process engine can finally judge
#: (PDF-82's census): their cells carry the engine marker and skip visibly, with
#: the product's own engine-gated reason, when it is absent. A module-level
#: constant, not a literal in a function, so the lexical walk of that census
#: does not reach every other leaf's cell.
ENGINE_FOR_LEAF: Final[dict[str, str]] = {"ocr": "tesseract", "convert": "soffice"}

ENVELOPE_KEYS: Final[list[str]] = [
    "schema_version",
    "verb",
    "dry_run",
    "items",
    "warnings",
    "duration_ms",
    "exit_code",
]


# --------------------------------------------------------------------------- #
# The world: fixtures built with the product, a real second filesystem, cells.
# --------------------------------------------------------------------------- #


@dataclass
class Run:
    rc: int
    out: str
    err: str
    cwd: Path
    xdir: Path

    @property
    def envelope(self) -> dict[str, Any]:
        loaded = json.loads(self.out)
        assert isinstance(loaded, dict), "stdout is not a JSON object"
        return loaded

    @property
    def warnings(self) -> list[str]:
        entries = self.envelope["warnings"]
        assert isinstance(entries, list)
        return entries

    @property
    def stderr_lines(self) -> list[str]:
        return [
            line[len(STDERR_PREFIX) :]
            for line in self.err.splitlines()
            if line.startswith(STDERR_PREFIX)
        ]


class World:
    def __init__(self, primary: Path, xdev: Path, fixtures: Path) -> None:
        self.primary = primary
        self.xdev = xdev
        self.fixtures = fixtures
        self.count = 0

    def cell(self) -> tuple[Path, Path]:
        """A fresh cell directory (primary fs, fixtures copied in) with `L` -> a
        fresh directory on the second filesystem."""
        self.count += 1
        cwd = self.primary / f"cell{self.count}"
        shutil.copytree(self.fixtures, cwd)
        xdir = self.xdev / f"cell{self.count}"
        xdir.mkdir()
        (cwd / "L").symlink_to(xdir)
        (cwd / "local").mkdir()
        return cwd, xdir

    def run(self, argv: tuple[str, ...], cell: tuple[Path, Path], *fmt: str) -> Run:
        cwd, xdir = cell
        flags = fmt if fmt else ("-o", "json")
        done = run_cli(*argv, *flags, stdin="", cwd=cwd)
        return Run(done.returncode, done.stdout, done.stderr, cwd, xdir)

    def fresh(self, argv: tuple[str, ...], *fmt: str) -> Run:
        return self.run(argv, self.cell(), *fmt)


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory, corpus: Any) -> Iterator[World]:
    primary = tmp_path_factory.mktemp("pdf156")
    found = find_second_filesystem(primary)
    if found is None:
        if sys.platform == "linux":
            pytest.fail(LADDER_MESSAGE)
        pytest.skip(LADDER_MESSAGE)
    directory, rung = found
    print(f"[PDF-156] second filesystem from ladder rung {rung}: {directory}")
    xdev = Path(tempfile.mkdtemp(dir=directory, prefix="pdf156-xdev-"))
    fixtures = primary / "fixtures"
    fixtures.mkdir()

    def product(*argv: str) -> None:
        done = run_cli(*argv, "-o", "json", stdin="", cwd=fixtures)
        assert done.returncode == 0, (argv, done.stderr)

    (fixtures / "a.txt").write_text("hello\n")
    (fixtures / "pw").write_text("secret\n")
    product("create", "a.txt", "-O", "x.pdf")
    product("compress", "x.pdf", "-O", "good.pdf")  # does not shrink (E2)
    product("compress", "x.pdf", "-O", "good2.pdf")
    product("merge", "good.pdf", "good.pdf", "good.pdf", "-O", "multi.pdf")
    product(
        "encrypt", "good.pdf", "--user-password-file", "pw", "--owner-password-file", "pw",
        "-O", "enc.pdf",
    )  # fmt: skip
    whole = (fixtures / "good.pdf").read_bytes()
    (fixtures / "truncated.pdf").write_bytes(whole[: len(whole) // 2])
    from PIL import Image

    Image.new("RGB", (40, 30), (200, 10, 10)).save(fixtures / "p.png")
    shutil.copy(corpus.path("tabular"), fixtures / "tabular.pdf")
    try:
        yield World(primary, xdev, fixtures)
    finally:
        shutil.rmtree(xdev, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Expected text, built from the product's own template with the cell's values.
# --------------------------------------------------------------------------- #


def deg(cwd: Path, typed: str) -> str:
    """The condition-1 message for the spelling *typed*, built BEFORE the run
    (an existing file would move the first existing ancestor's device)."""
    absolute = Path(cwd) / typed
    named = None
    for candidate in (absolute, *absolute.parents):
        try:
            named = os.lstat(candidate).st_dev
            break
        except OSError:
            continue
    assert named is not None
    resolved = canonical(absolute)
    actual = os.stat(resolved.parent).st_dev
    return (
        f"{DEGRADED_PREFIX}: {typed} (device {named}) resolves to "
        f"{resolved} (device {actual}) on a different filesystem; the write "
        f"stays atomic on the destination filesystem, but not on the one you named"
    )


def dns(cwd: Path, name: str) -> str:
    size = os.stat(cwd / name).st_size
    return f"{name}: did not shrink ({size} -> {size} bytes)"


def stderr_text(*messages: str) -> str:
    return "".join(f"{STDERR_PREFIX}{message}\n" for message in messages)


def writer_entries(entries: list[str]) -> list[str]:
    return [entry for entry in entries if entry.startswith(DEGRADED_PREFIX)]


# --------------------------------------------------------------------------- #
# AC1 -- the census is pinned
# --------------------------------------------------------------------------- #


def _functions_with_calls(tree: ast.Module) -> Iterator[tuple[str, ast.AST]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield f"{node.name}.{member.name}", member
    for top in tree.body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield top.name, top


def test_ac1_census_is_pinned() -> None:
    callers: set[str] = set()
    printers: set[str] = set()
    for module in sorted((SRC / "safety").glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for name, func in _functions_with_calls(tree):
            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                callee = node.func
                if (
                    isinstance(callee, ast.Attribute)
                    and callee.attr == "_warn"
                    and isinstance(callee.value, ast.Name)
                    and callee.value.id == "self"
                ):
                    callers.add(name)
                to_stderr = any(
                    keyword.arg == "file" and ast.unparse(keyword.value) == "sys.stderr"
                    for keyword in node.keywords
                )
                if to_stderr or ast.unparse(callee) == "sys.stderr.write":
                    printers.add(name)
    # (a) exactly the two producers; (b) exactly one stderr sink
    assert callers == {
        "AtomicWriter._warn_if_destination_moved",
        "AtomicWriter._replace_across_devices",
    }
    assert printers == {"_default_warn"}

    # (c) no product construction injects a sink
    injected: list[str] = []
    for module in sorted((SRC / "ops").glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and ast.unparse(node.func).split(".")[-1] == "AtomicWriter"
                and any(keyword.arg == "warn" for keyword in node.keywords)
            ):
                injected.append(f"{module.name}:{node.lineno}")
    assert injected == []

    # (d) the writing-leaf population, derived from the live CLI
    verbs = discover_verbs()
    writing = {verb.name for verb in verbs if not verb.is_group and verb.consumes != ()}
    assert writing == set(WRITING_LEAVES)
    assert len(writing) == 21
    mutating = {verb.name for verb in verbs if verb.is_mutating and not verb.is_group}
    assert mutating - writing == {"meta get", "permissions"}
    assert set(LEAF_CELLS) == writing


# --------------------------------------------------------------------------- #
# AC2 -- the ledger repro publishes both entries
# --------------------------------------------------------------------------- #

LEDGER_ARGV: Final[tuple[str, ...]] = ("compress", "good.pdf", "-O", "L/x.pdf", "-f")


def test_ac2_ledger_repro_publishes_both(world: World) -> None:
    cell = world.cell()
    cwd, xdir = cell
    degraded = deg(cwd, "L/x.pdf")
    shrink = dns(cwd, "good.pdf")
    first = world.run(LEDGER_ARGV, cell)
    assert first.rc == 0
    assert first.warnings == [shrink, degraded]
    assert first.err == stderr_text(degraded, shrink)
    assert first.envelope["schema_version"] == 1
    assert list(first.envelope) == ENVELOPE_KEYS

    # ndjson and table reuse the json cell's exact output name
    for flag in ("ndjson", "table"):
        (xdir / "x.pdf").unlink()
        other = world.run(LEDGER_ARGV, cell, "-o", flag)
        assert other.rc == 0
        assert other.err == first.err
        if flag == "ndjson":
            records = [json.loads(line) for line in other.out.splitlines() if line.strip()]
            assert records
            assert not any("warnings" in record for record in records)


# --------------------------------------------------------------------------- #
# AC4 -- the same-device control is unchanged
# --------------------------------------------------------------------------- #


def test_ac4_same_device_control(world: World) -> None:
    cell = world.cell()
    cwd, _xdir = cell
    shrink = dns(cwd, "good.pdf")
    argv = ("compress", "good.pdf", "-O", "local/x.pdf", "-f")
    real = world.run(argv, cell)
    assert real.rc == 0
    assert real.warnings == [shrink]
    assert writer_entries(real.warnings) == []
    assert real.err == stderr_text(shrink)

    dry = world.run(("--dry-run", *argv), cell)
    assert dry.rc == 0
    assert dry.warnings == []
    assert dry.err == ""


# --------------------------------------------------------------------------- #
# AC5 / AC6 -- completeness over every writing leaf, and the dry/real matrix
# --------------------------------------------------------------------------- #


def _leaf_params() -> list[Any]:
    return [
        pytest.param(
            leaf,
            marks=pytest.mark.requires(ENGINE_FOR_LEAF[leaf]) if leaf in ENGINE_FOR_LEAF else (),
            id=leaf,
        )
        for leaf in WRITING_LEAVES
    ]


def _base_entries(leaf: str, cwd: Path) -> list[str]:
    if leaf == "compress":
        return [dns(cwd, "good.pdf")]
    if leaf == "merge":
        return [MERGE_INFO_ENTRY]
    return []


@pytest.mark.parametrize("leaf", _leaf_params())
def test_ac5_every_writing_leaf_is_complete(world: World, leaf: str) -> None:
    argv, typed_targets = LEAF_CELLS[leaf]
    cell = world.cell()
    cwd, _xdir = cell
    expected = [deg(cwd, typed) for typed in typed_targets]
    base = _base_entries(leaf, cwd)
    real = world.run(argv, cell)
    assert real.rc == 0, real.err

    entries = real.warnings
    assert set(real.stderr_lines) == set(entries)
    assert len(set(entries)) == len(entries)
    assert writer_entries(entries) == expected
    stderr_degraded = [line for line in real.stderr_lines if line.startswith(DEGRADED_PREFIX)]
    assert sorted(stderr_degraded) == sorted(expected)
    # the base list is a prefix, element for element; the tail is the writer entries
    assert entries[: len(base)] == base
    assert entries[len(base) :] == expected


@pytest.mark.parametrize("leaf", _leaf_params())
def test_ac6_dry_real_pairs(world: World, leaf: str) -> None:
    argv, typed_targets = LEAF_CELLS[leaf]
    cell = world.cell()
    cwd, xdir = cell
    expected = [deg(cwd, typed) for typed in typed_targets]
    dry = world.run(("--dry-run", *argv), cell)
    assert dry.rc == 0, dry.err
    assert list(xdir.iterdir()) == [], "the dry run wrote"
    real = world.run(argv, cell)
    assert real.rc == 0, real.err
    assert writer_entries(real.warnings) == expected
    # PDF-170 (OR-87): every writing leaf's dry run predicts the line the real run prints
    # (the former `else` arm pinned the base defect, `(0, deg)`).
    assert writer_entries(dry.warnings) == expected
    assert sorted(line for line in dry.stderr_lines if line.startswith(DEGRADED_PREFIX)) == (
        sorted(expected)
    )


# PDF-163 / B-551 (1): PDF-156's refusal row as BYTES, provenance e7384d2 (E2).
REFUSAL_REAL_STDOUT: Final = (
    151,
    "2aca3d7a9b971862a67b38139e7c545264d5e9349cc869001b67b05cac9caa0f",
)
REFUSAL_DRY_STDOUT_NORMALISED: Final = (
    538,
    "8945d68079f047fa1fe5c9cf6da77cc694d20e2beb64021bed355dbf6a7634bf",
)


def test_ac6_refusal_row_warns_before_nothing(world: World) -> None:
    argv = ("compress", "good.pdf", "-O", "L/exists.pdf")
    real_cell = world.cell()
    shutil.copy(real_cell[0] / "good.pdf", real_cell[1] / "exists.pdf")
    real = world.run(argv, real_cell)
    assert real.rc == 5
    assert list(real.envelope) == ["schema_version", "error"]
    assert real.envelope["error"]["code"] == 5
    assert real.envelope["error"]["kind"] == "refused"
    assert real.stderr_lines == []

    dry_cell = world.cell()
    shutil.copy(dry_cell[0] / "good.pdf", dry_cell[1] / "exists.pdf")
    dry = world.run(("--dry-run", *argv), dry_cell)
    assert dry.rc == 5
    assert dry.envelope["dry_run"] is True
    assert dry.envelope["exit_code"] == 5
    assert dry.envelope["items"][0]["ok"] is False
    assert dry.envelope["items"][0]["detail"]["would_exit"] == 5
    assert writer_entries(dry.warnings) == []
    assert not any(line.startswith(DEGRADED_PREFIX) for line in dry.stderr_lines)

    real_raw = real.out.encode()
    assert (len(real_raw), hashlib.sha256(real_raw).hexdigest()) == REFUSAL_REAL_STDOUT, real.out
    assert real.err == "" and dry.err == ""
    size = (dry_cell[0] / "good.pdf").stat().st_size
    dry_raw = dry.out.encode()
    assert f'"bytes_before": {size},'.encode() in dry_raw, dry.out  # good.pdf is 974|975 bytes (E2)
    dry_norm = re.sub(rb'"duration_ms": [0-9.]+', b'"duration_ms": 0', dry_raw)
    dry_norm = re.sub(rb'"bytes_before": [0-9]+', b'"bytes_before": 0', dry_norm)
    assert (len(dry_norm), hashlib.sha256(dry_norm).hexdigest()) == REFUSAL_DRY_STDOUT_NORMALISED, (
        dry.out
    )


# --------------------------------------------------------------------------- #
# AC7 -- batch, --out-dir and per-item attribution
# --------------------------------------------------------------------------- #


def test_ac7_batch_and_out_dir(world: World) -> None:
    name = ("--out-dir", "L", "--name", "U-{stem}.{ext}", "-f")
    cell = world.cell()
    cwd, _xdir = cell
    expected = [
        dns(cwd, "good.pdf"),
        dns(cwd, "good2.pdf"),
        deg(cwd, "L/U-good.pdf"),
        deg(cwd, "L/U-good2.pdf"),
    ]
    batch = world.run(("compress", "good.pdf", "good2.pdf", *name), cell)
    assert batch.rc == 0
    assert batch.warnings == expected

    cell = world.cell()
    cwd, _xdir = cell
    parts = [deg(cwd, f"L/p-{page}.pdf") for page in (1, 2, 3)]
    split = world.run(
        ("split", "multi.pdf", "--each-page", "--out-dir", "L", "--name", "p-{page}.{ext}"), cell
    )
    assert split.rc == 0
    assert split.warnings == parts

    # partial failure: base shape is items[0] ok, items[1] not ok, rc 1
    cell = world.cell()
    cwd, _xdir = cell
    first_only = deg(cwd, "L/U-good.pdf")
    base_list = [dns(cwd, "good.pdf")]
    partial = world.run(("compress", "good.pdf", "truncated.pdf", *name), cell)
    assert partial.rc == 1
    assert [item["ok"] for item in partial.envelope["items"]] == [True, False]
    assert partial.warnings == [*base_list, first_only]


# --------------------------------------------------------------------------- #
# AC8 -- rasterize through spawn workers
# --------------------------------------------------------------------------- #


def test_ac8_rasterize_workers(world: World) -> None:
    argv = ("rasterize", "multi.pdf", "--out-dir", "L", "--name", "r-{page}.{ext}")
    cell = world.cell()
    cwd, xdir = cell
    expected = [deg(cwd, f"L/r-{page}.png") for page in (1, 2, 3)]
    published: list[list[str]] = []
    for _attempt in range(3):
        for produced in xdir.iterdir():
            produced.unlink()  # same names again, fresh each time
        run = world.run(argv, cell)
        assert run.rc == 0, run.err
        published.append(run.warnings)
        assert sorted(line for line in run.stderr_lines if line.startswith(DEGRADED_PREFIX)) == (
            sorted(expected)
        )
    assert published == [expected, expected, expected]

    cell = world.cell()
    cwd, _xdir = cell
    expected_two = [deg(cwd, "L/r-good.png"), deg(cwd, "L/r-good2.png")]
    two_argv = ("rasterize", "good.pdf", "good2.pdf", "--out-dir", "L", "--name", "r-{stem}.{ext}")
    two = world.run(two_argv, cell)
    assert two.rc == 0
    assert two.warnings == expected_two

    item = ItemResult(
        input="a", output="b", ok=True, exit_code=0, message=None,
        bytes_before=None, bytes_after=None, duration_ms=0,
    )  # fmt: skip
    chunk = rendered_chunk_class()([(0, item), (1, item)], ((1, ("m1", "m2")),))
    revived = pickle.loads(pickle.dumps(chunk))
    assert list(revived) == [(0, item), (1, item)]
    assert revived.writer_warnings == ("m1", "m2")
    assert _added("pdf_tooling.ops.raster", "_render_chunk")[0].__name__ == "_render_chunk"
    assert rendered_chunk_class()().writer_warnings == ()


# --------------------------------------------------------------------------- #
# AC9 -- text and tables render their own envelope and publish too
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("argv", "typed"),
    [
        (("text", "good.pdf", "-O", "L/x.txt"), "L/x.txt"),
        (("tables", "tabular.pdf", "-O", "L/x.csv"), "L/x.csv"),
    ],
    ids=["text", "tables"],
)
def test_ac9_text_and_tables(world: World, argv: tuple[str, ...], typed: str) -> None:
    cell = world.cell()
    cwd, _xdir = cell
    degraded = deg(cwd, typed)
    run = world.run(argv, cell)
    assert run.rc == 0
    assert run.warnings == [degraded]
    assert run.err == stderr_text(degraded)

    local_argv = tuple(part.replace("L/", "local/") for part in argv)
    local = world.run(local_argv, cell)
    assert local.warnings == []
    assert list(local.envelope) == list(run.envelope)


def test_ac9_no_table_guard_publishes_no_writer_entry(world: World) -> None:
    cell = world.cell()
    _cwd, xdir = cell
    run = world.run(("tables", "good.pdf", "-O", "L/nt.csv"), cell)
    assert run.rc == 0
    assert len(run.warnings) == 1
    assert run.warnings[0].startswith("no tables detected")
    assert writer_entries(run.warnings) == []
    assert not any(line.startswith(DEGRADED_PREFIX) for line in run.stderr_lines)
    assert list(xdir.iterdir()) == []


# --------------------------------------------------------------------------- #
# AC10 -- condition 2 and the recording rule (in-process)
# --------------------------------------------------------------------------- #


def _policy() -> SafetyPolicy:
    return SafetyPolicy(
        dry_run=False,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )


def _exdev_write(destination: Path, scratch: Path, **extra: Any) -> AtomicWriter:
    with AtomicWriter(destination, policy=_policy(), _temp_dir=scratch, **extra) as writer:
        writer.stream.write(b"x" * 64)
    return writer


def _result(*entries: str) -> OperationResult:
    return OperationResult(
        schema_version=1, verb="probe", dry_run=False, items=(), warnings=entries, duration_ms=0
    )


def test_ac10_exdev_and_recording_rule(world: World, tmp_path: Path) -> None:
    scratch = world.xdev / "exdev-scratch"
    scratch.mkdir()

    token = open_writer_warnings()
    try:
        writer = _exdev_write(tmp_path / "a.pdf", scratch)
        recorded = writer_warnings()
    finally:
        close_writer_warnings(token)
    assert len(recorded) == 1
    message = recorded[0]
    assert message.startswith(f"{DEGRADED_PREFIX}: cross-device rename from ")
    assert writer.warnings == [message]
    token = open_writer_warnings()
    try:
        record_writer_warnings((message,))
        assert publish_writer_warnings(_result("x")).warnings == ("x", message)
    finally:
        close_writer_warnings(token)

    # (b) an injected sink never reached stderr, so it is not recorded
    sink: list[str] = []
    token = open_writer_warnings()
    try:
        injected = _exdev_write(tmp_path / "b.pdf", scratch, warn=sink.append)
        recorded_b = writer_warnings()
    finally:
        close_writer_warnings(token)
    assert recorded_b == ()
    assert sink == injected.warnings
    assert len(sink) == 1

    # (c) with no ledger open nothing is recorded and nothing raises
    bare = _exdev_write(tmp_path / "c.pdf", scratch)
    assert len(bare.warnings) == 1
    assert writer_warnings() == ()


# --------------------------------------------------------------------------- #
# AC11 -- the duplicate and order rule
# --------------------------------------------------------------------------- #

M: Final[str] = f"{DEGRADED_PREFIX}: probe"


def _with_ledger(recorded: tuple[str, ...], body: Callable[[], Any]) -> Any:
    token = open_writer_warnings()
    try:
        record_writer_warnings(recorded)
        return body()
    finally:
        close_writer_warnings(token)


def test_ac11_dedupe_and_order(tmp_path: Path) -> None:
    assert _with_ledger((M,), lambda: merge_writer_warnings(("a", M))) == ["a", M]
    assert _with_ledger((M, M), lambda: merge_writer_warnings(("a",))) == ["a", M]
    # pre-existing duplicates are kept
    assert _with_ledger((M,), lambda: merge_writer_warnings(("a", "a"))) == ["a", "a", M]
    # nothing recorded: the same object comes back
    untouched = _result("a")
    assert _with_ledger((), lambda: publish_writer_warnings(untouched)) is untouched
    assert publish_writer_warnings(untouched) is untouched
    # two spellings of one ON-DISK file are two messages (never collapsed by a
    # canonicalizing key): `link` -> `real`, and `real/b.pdf` exists
    real = tmp_path / "real"
    real.mkdir()
    (real / "b.pdf").write_bytes(b"x")
    link = tmp_path / "link"
    link.symlink_to(real)
    assert (link / "b.pdf").samefile(real / "b.pdf")
    alias = f"{DEGRADED_PREFIX}: {link}/b.pdf (device 1) resolves to {real}/b.pdf (device 2)"
    canon = f"{DEGRADED_PREFIX}: {real}/b.pdf (device 1) resolves to {real}/b.pdf (device 2)"
    assert alias != canon
    assert _with_ledger((alias, canon), lambda: merge_writer_warnings(())) == [alias, canon]
    assert _with_ledger((alias,), lambda: merge_writer_warnings((canon,))) == [canon, alias]


# --------------------------------------------------------------------------- #
# AC12 -- alias-shaped: one directory, two spellings
# --------------------------------------------------------------------------- #


def test_ac12_alias_two_spellings(world: World) -> None:
    cell = world.cell()
    cwd, xdir = cell
    canonical_spelling = f"{xdir}/a.pdf"
    direct = world.run(("compress", "good.pdf", "-O", canonical_spelling, "-f"), cell)
    assert direct.rc == 0
    assert writer_entries(direct.warnings) == []
    assert not any(line.startswith(DEGRADED_PREFIX) for line in direct.stderr_lines)

    via_link_expected = deg(cwd, "L/b.pdf")
    via_link = world.run(("compress", "good.pdf", "-O", "L/b.pdf", "-f"), cell)
    assert via_link.rc == 0
    assert writer_entries(via_link.warnings) == [via_link_expected]
    assert via_link.stderr_lines[0] == via_link_expected  # byte for byte, as typed
    # one on-disk file, two spellings, one ledger: both messages survive
    link_spelling = via_link_expected.replace("L/b.pdf", f"{cwd}/L/b.pdf", 1)
    other_spelling = via_link_expected.replace("L/b.pdf", f"{xdir}/b.pdf", 1)
    assert (cwd / "L" / "b.pdf").samefile(xdir / "b.pdf")
    assert link_spelling != other_spelling
    merged = _with_ledger((link_spelling, other_spelling), lambda: merge_writer_warnings(()))
    assert merged == [link_spelling, other_spelling]

    real_copy = xdir / "ip-real.pdf"
    shutil.copy(cwd / "good.pdf", real_copy)
    (cwd / "ip-link.pdf").symlink_to(real_copy)
    in_place_expected = deg(cwd, "ip-link.pdf")
    in_place = world.run(("compress", "ip-link.pdf", "--in-place", "-y"), cell)
    assert in_place.rc == 0
    assert writer_entries(in_place.warnings) == [in_place_expected]
