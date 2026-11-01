"""PDF-170 (OR-87) -- ``--dry-run`` predicts ``atomicity degraded`` on the writing verbs.

The defect: ``pdftooling --dry-run compress good.pdf -O L/x.pdf -f -o json``, where
``L`` is a symlink onto another filesystem, exited ``0`` with ``warnings: []`` and
an empty stderr, while the real run of the same argv prints (and, since PDF-156,
publishes) ``atomicity degraded: ...``. Only ``merge``/``create``/``compose``
predicted it, because only their dry branch constructs an ``AtomicWriter``.

Provenance: the base readings below (every non-predicting leaf gives dry
``(0, 0, 0)`` in a cross-device cell, the same-device cells give ``(0, 0, 0)`` in
both modes) were measured at ``e7384d2`` on 2026-10-30 (PDF-170 E2) and re-driven
on the landing base ``7c08a40`` on 2026-10-31 (PDF-170 step 0). The fixtures the
product builds are not byte-deterministic (timestamps, ids), so a pinned sha256 of
a whole envelope cannot live in a test: the base-versus-HEAD byte freeze is a
differential run on shared fixture bytes and is recorded in the validation log,
while this module asserts the same freeze structurally (equality on whole lists
and whole strings, never on a substring).

Conventions follow ``test_pdf156_writer_warnings_in_envelope.py`` and
``test_cross_filesystem.py``: a REAL second filesystem (a missing one is a failure
on Linux, a skip elsewhere), real symlinks on disk, a fresh cell and a fresh
destination name per run, subprocess cells through ``run_cli`` with stdin closed.
Expected text is built from the product's own template with the cell's real values.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pytest

from pdf_tooling.safety import DEGRADED_PREFIX, AtomicWriter
from pdf_tooling.safety import atomic as atomic_module
from pdf_tooling.safety.policy import SafetyPolicy

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from fs_snapshot import assert_unchanged, snapshot  # noqa: E402
from integration.test_pdf156_writer_warnings_in_envelope import (  # noqa: E402
    ENGINE_FOR_LEAF,
    ENVELOPE_KEYS,
    LEAF_CELLS,
    SRC,
    WRITING_LEAVES,
    Run,
    World,
    _functions_with_calls,
    close_writer_warnings,
    deg,
    dns,
    open_writer_warnings,
    publish_writer_warnings,
    stderr_text,
    world,  # noqa: F401  (the module-scoped fixture, imported so this module shares its cells)
    writer_entries,
    writer_warnings,
)
from registry import REPO_ROOT, discover_verbs, run_cli  # noqa: E402

__all__ = ["world"]

#: The leaves whose dry branch already constructed a writer at base (E2), so they
#: predicted the line before this spec and are not edited by it (AC8).
ALREADY_PREDICTING: Final[frozenset[str]] = frozenset({"merge", "create", "compose"})

#: The ``ops/`` modules that call the helper (AC1 (d)); ``merge``/``compose`` are not among them.
CALLER_MODULES: Final[frozenset[str]] = frozenset(
    {
        "optimize",
        "pages",
        "split",
        "crypto",
        "metadata",
        "overlay",
        "office",
        "ocr",
        "raster",
        "textract",
    }
)

HELPER: Final[str] = "predict_degraded_destinations"
NAME_TEMPLATE: Final[str] = "U-{stem}.{ext}"


def _helper() -> Any:
    found = getattr(atomic_module, HELPER, None)
    assert found is not None, (
        f"PDF-170 behaviour is absent: safety.atomic does not provide {HELPER}"
    )
    return found


# --------------------------------------------------------------------------- #
# Population, derived from the live CLI (never typed)
# --------------------------------------------------------------------------- #


def _consumes() -> dict[str, tuple[str, ...]]:
    return {
        verb.name: verb.consumes
        for verb in discover_verbs()
        if not verb.is_group and verb.consumes != ()
    }


CONSUMES: Final[dict[str, tuple[str, ...]]] = _consumes()
NEWLY_PREDICTING: Final[tuple[str, ...]] = tuple(
    leaf for leaf in WRITING_LEAVES if leaf not in ALREADY_PREDICTING
)


def _marks(leaf: str) -> Any:
    return pytest.mark.requires(ENGINE_FOR_LEAF[leaf]) if leaf in ENGINE_FOR_LEAF else ()


def _leaf_params(leaves: tuple[str, ...] = WRITING_LEAVES) -> list[Any]:
    return [pytest.param(leaf, marks=_marks(leaf), id=leaf) for leaf in leaves]


# --------------------------------------------------------------------------- #
# Shapes: each is derived from the leaf's PDF-156 cell and its ``consumes``.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Shape:
    argv: tuple[str, ...]
    typed: tuple[str, ...]  # the target spellings the run writes, in plan order
    in_place_source: str | None = None  # the symlink/plain file the cell must hold


def _operand(leaf: str, argv: tuple[str, ...]) -> str:
    return argv[len(leaf.split())]


def _swap_output(argv: tuple[str, ...], replacement: tuple[str, ...]) -> tuple[str, ...]:
    index = argv.index("-O")
    return (*argv[:index], *replacement, *argv[index + 2 :])


def _with_source(leaf: str, argv: tuple[str, ...], source: str) -> tuple[str, ...]:
    position = len(leaf.split())
    return (*argv[:position], source, *argv[position + 1 :])


def _retarget(argv: tuple[str, ...], destination: str) -> tuple[str, ...]:
    """Point every token that names ``L`` at *destination* (same device: ``local``)."""
    out: list[str] = []
    for token in argv:
        if token == "L":
            out.append(destination)
        elif token.startswith("L/"):
            out.append(destination + token[1:])
        else:
            out.append(token)
    return tuple(out)


def shape_for(leaf: str, name: str, *, device: str = "L") -> Shape | None:
    """Shape ``a`` (-O), ``c`` (--out-dir) or ``e`` (--in-place) for *leaf*, or None.

    ``device`` is ``L`` (cross-device) or ``local`` (same device, shapes b and f).
    """
    flags = CONSUMES[leaf]
    argv, typed = LEAF_CELLS[leaf]
    suffix = Path(typed[0]).suffix
    stem = Path(_operand(leaf, argv)).stem
    if name == "a":
        if "--output" not in flags:
            return None
        return Shape(_retarget(argv, device), tuple(_retarget_text(t, device) for t in typed))
    if name == "c":
        if "--out-dir" not in flags:
            return None
        if "--output" not in flags:
            return Shape(_retarget(argv, device), tuple(_retarget_text(t, device) for t in typed))
        swapped = _swap_output(argv, ("--out-dir", device, "--name", NAME_TEMPLATE))
        return Shape(swapped, (f"{device}/U-{stem}{suffix}",))
    if name == "e":
        if "--in-place" not in flags:
            return None
        swapped = _swap_output(argv, ("--in-place", "-y"))
        return Shape(_with_source(leaf, swapped, "ip.pdf"), ("ip.pdf",), in_place_source="ip.pdf")
    raise AssertionError(f"unknown shape {name!r}")


def _retarget_text(typed: str, destination: str) -> str:
    return destination + typed[1:] if typed.startswith("L/") else typed


def prepare(shape: Shape, leaf: str, cell: tuple[Path, Path], *, cross: bool) -> None:
    """Materialise the in-place source: a symlink onto the second filesystem, or a plain file."""
    if shape.in_place_source is None:
        return
    cwd, xdir = cell
    original = cwd / _operand(leaf, LEAF_CELLS[leaf][0])
    if cross:
        real = xdir / "ip-real.pdf"
        shutil.copy(original, real)
        (cwd / shape.in_place_source).symlink_to(real)
    else:
        shutil.copy(original, cwd / shape.in_place_source)


# --------------------------------------------------------------------------- #
# Driving the CLI: a fresh cell, an owned TMPDIR, and a before/after snapshot.
# --------------------------------------------------------------------------- #


class Driver:
    def __init__(self, world: World) -> None:
        self.world = world
        self.count = 0

    def cell(self) -> tuple[Path, Path]:
        cell = self.world.cell()
        (cell[0] / "bad.pdf").write_bytes(b"this is not a pdf\n")
        return cell

    def tmpdir(self, cell: tuple[Path, Path]) -> Path:
        path = cell[0].parent / f"tmp-{cell[0].name}"
        path.mkdir(exist_ok=True)
        return path

    def run(
        self, argv: tuple[str, ...], cell: tuple[Path, Path], *fmt: str, dry: bool = False
    ) -> Run:
        cwd, xdir = cell
        flags = fmt if fmt else ("-o", "json")
        env = {**os.environ, "TMPDIR": str(self.tmpdir(cell))}
        full = (("--dry-run",) if dry else ()) + argv
        done = run_cli(*full, *flags, stdin="", cwd=cwd, env=env)
        return Run(done.returncode, done.stdout, done.stderr, cwd, xdir)

    def dry(self, argv: tuple[str, ...], cell: tuple[Path, Path], *fmt: str) -> Run:
        """A dry run that must write nothing, anywhere (AC9 (a))."""
        cwd, xdir = cell
        roots = (cwd, xdir, self.tmpdir(cell))
        before = snapshot(*roots)
        result = self.run(argv, cell, *fmt, dry=True)
        assert_unchanged(before, snapshot(*roots))  # the dry run wrote nothing, anywhere
        return result


@pytest.fixture
def driver(world: World) -> Driver:  # noqa: F811  (the imported module-scoped fixture)
    return Driver(world)


def entries(run: Run) -> list[str]:
    """The writer entries of *run*'s envelope (an error envelope carries no ``warnings``)."""
    return writer_entries(run.envelope.get("warnings", []))


def deg_lines(run: Run) -> list[str]:
    return [line for line in run.stderr_lines if line.startswith(DEGRADED_PREFIX)]


def without_deg(run: Run) -> str:
    return "".join(
        line + "\n"
        for line in run.err.splitlines()
        if not line.startswith("warning: " + DEGRADED_PREFIX)
    )


CROSS_SHAPES: Final[tuple[str, ...]] = ("a", "c", "e")


def _matrix_params() -> list[Any]:
    params: list[Any] = []
    for leaf in WRITING_LEAVES:
        for name in CROSS_SHAPES:
            if shape_for(leaf, name) is not None:
                params.append(pytest.param(leaf, name, marks=_marks(leaf), id=f"{leaf}-{name}"))
    return params


# --------------------------------------------------------------------------- #
# AC1 -- population and producer census
# --------------------------------------------------------------------------- #


def test_ac1_population_and_producer_census() -> None:
    # (a) the writing-leaf set, derived from the live CLI
    assert set(CONSUMES) == set(WRITING_LEAVES)
    assert len(CONSUMES) == 21
    assert len(NEWLY_PREDICTING) == 18

    # (c) the producers are unchanged; the only new caller of the writer's own method is the helper
    producers: set[str] = set()
    askers: set[str] = set()
    for module in sorted((SRC / "safety").glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for name, func in _functions_with_calls(tree):
            for node in ast.walk(func):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr == "_warn" and ast.unparse(node.func.value) == "self":
                    producers.add(name)
                if node.func.attr == "_warn_if_destination_moved":
                    askers.add(name)
    assert producers == {
        "AtomicWriter._warn_if_destination_moved",
        "AtomicWriter._replace_across_devices",
    }
    assert askers == {"AtomicWriter._plan", HELPER}

    # (d) the only callers are in the 10 ops modules, never merge/compose
    callers: set[str] = set()
    for module in sorted(SRC.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and ast.unparse(node.func).split(".")[-1] == HELPER:
                callers.add(f"{module.parent.name}/{module.stem}")
    assert callers == {f"ops/{stem}" for stem in CALLER_MODULES}


@pytest.mark.parametrize("leaf", _leaf_params(NEWLY_PREDICTING))
def test_ac1_every_writing_leaf_predicts(driver: Driver, leaf: str) -> None:
    """(b) After this spec the non-predicting set is empty: the leaf's first applicable
    cross-device shape publishes at least one entry in a dry run."""
    for name in CROSS_SHAPES:
        shape = shape_for(leaf, name)
        if shape is None:
            continue
        cell = driver.cell()
        prepare(shape, leaf, cell, cross=True)
        dry = driver.dry(shape.argv, cell)
        assert dry.rc == 0, dry.err
        assert len(entries(dry)) >= 1
        return
    raise AssertionError(f"{leaf} has no cross-device shape")


# --------------------------------------------------------------------------- #
# AC2 -- the ledger repro, dry (and parity with the real run)
# --------------------------------------------------------------------------- #

LEDGER_ARGV: Final[tuple[str, ...]] = ("compress", "good.pdf", "-O", "L/x.pdf", "-f")


def test_ac2_ledger_repro_dry(driver: Driver) -> None:
    cell = driver.cell()
    cwd, _xdir = cell
    expected = deg(cwd, "L/x.pdf")
    dry = driver.dry(LEDGER_ARGV, cell)
    assert dry.rc == 0
    assert dry.warnings == [expected]
    assert dry.err == stderr_text(expected)
    assert dry.envelope["schema_version"] == 1
    assert list(dry.envelope) == ENVELOPE_KEYS

    real = driver.run(LEDGER_ARGV, cell)
    assert real.rc == 0
    assert real.warnings == [dns(cwd, "good.pdf"), expected]
    assert entries(real) == dry.warnings
    assert deg_lines(real) == deg_lines(dry)


# --------------------------------------------------------------------------- #
# AC3 -- the dry/real matrix: every writing leaf x every applicable cross-device shape
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("leaf", "name"), _matrix_params())
def test_ac3_dry_real_matrix(driver: Driver, leaf: str, name: str) -> None:
    shape = shape_for(leaf, name)
    assert shape is not None
    cell = driver.cell()
    cwd, _xdir = cell
    prepare(shape, leaf, cell, cross=True)
    expected = [deg(cwd, typed) for typed in shape.typed]

    dry = driver.dry(shape.argv, cell)
    real = driver.run(shape.argv, cell)
    assert dry.rc == real.rc == 0, (dry.err, real.err)
    # the pair agrees: entries, and stderr deg lines (the lines are the entries)
    assert entries(dry) == expected  # item order
    assert sorted(entries(real)) == sorted(expected)  # rasterize: a worker race
    assert deg_lines(dry) == entries(dry)
    assert sorted(deg_lines(real)) == sorted(entries(real))
    # the writer entries sit at the tail, never duplicated, and the rest is unchanged
    assert dry.warnings[len(dry.warnings) - len(expected) :] == expected
    assert len(set(dry.warnings)) == len(dry.warnings)


# --------------------------------------------------------------------------- #
# AC4 -- decisive control: the same device predicts nothing, in either mode
# --------------------------------------------------------------------------- #


def _same_device_params() -> list[Any]:
    params: list[Any] = []
    for leaf in WRITING_LEAVES:
        for name in CROSS_SHAPES:
            if shape_for(leaf, name, device="local") is not None:
                params.append(pytest.param(leaf, name, marks=_marks(leaf), id=f"{leaf}-{name}"))
    return params


@pytest.mark.parametrize(("leaf", "name"), _same_device_params())
def test_ac4_same_device_is_unchanged(driver: Driver, leaf: str, name: str) -> None:
    shape = shape_for(leaf, name, device="local")
    assert shape is not None
    cell = driver.cell()
    prepare(shape, leaf, cell, cross=False)
    dry = driver.dry(shape.argv, cell)
    real = driver.run(shape.argv, cell)
    assert dry.rc == real.rc == 0, (dry.err, real.err)
    for run in (dry, real):
        assert entries(run) == []
        assert deg_lines(run) == []
    # the dry stderr is exactly the verb's own pre-existing dry stderr: no degraded line
    assert dry.err == without_deg(dry)


# --------------------------------------------------------------------------- #
# AC5 -- an --out-dir the real run creates first is not predicted
# --------------------------------------------------------------------------- #

OUT_DIR_LEAVES: Final[tuple[str, ...]] = tuple(
    leaf for leaf in WRITING_LEAVES if "--out-dir" in CONSUMES[leaf]
)


@pytest.mark.parametrize("created", ["L/newsub", "L/a/b"])
@pytest.mark.parametrize("leaf", _leaf_params(OUT_DIR_LEAVES))
def test_ac5_created_out_dir_is_not_predicted(driver: Driver, leaf: str, created: str) -> None:
    shape = shape_for(leaf, "c")
    assert shape is not None
    argv = tuple(created if token == "L" else token for token in shape.argv)
    cell = driver.cell()
    cwd, xdir = cell
    dry = driver.dry(argv, cell)
    assert dry.rc == 0, dry.err
    assert entries(dry) == []
    assert deg_lines(dry) == []
    assert not (xdir / created.split("/", 1)[1].split("/")[0]).exists(), (
        "the dry run made the directory"
    )
    real = driver.run(argv, cell)
    assert real.rc == 0, real.err
    assert entries(real) == []
    assert deg_lines(real) == []
    assert cwd.is_dir()


# --------------------------------------------------------------------------- #
# AC6 -- refused rows predict nothing
# --------------------------------------------------------------------------- #


def _pair(driver: Driver, argv: tuple[str, ...], cell: tuple[Path, Path]) -> tuple[Run, Run]:
    dry = driver.dry(argv, cell)
    real = driver.run(argv, cell)
    return dry, real


def test_ac6_refused_rows_predict_nothing(driver: Driver) -> None:
    # (a) a malformed input is a refusal, not an OK row
    cell = driver.cell()
    dry, real = _pair(driver, ("compress", "bad.pdf", "-O", "L/x.pdf"), cell)
    assert (dry.rc, entries(dry), deg_lines(dry)) == (1, [], [])
    assert (real.rc, entries(real), deg_lines(real)) == (1, [], [])

    # (b) a batch: the failed row builds no writer, so only the good row is predicted
    cell = driver.cell()
    cwd, _xdir = cell
    only = [deg(cwd, "L/U-good.pdf")]
    argv = (
        "compress",
        "good.pdf",
        "truncated.pdf",
        "--out-dir",
        "L",
        "--name",
        NAME_TEMPLATE,
        "-f",
    )
    dry, real = _pair(driver, argv, cell)
    assert dry.rc == real.rc == 1
    assert entries(dry) == only
    assert entries(real) == only

    # (c) a pages-family batch and a text batch with a truncated input
    for argv in (
        (
            "rotate",
            "good.pdf",
            "truncated.pdf",
            "--out-dir",
            "L",
            "--name",
            NAME_TEMPLATE,
            "--angle",
            "90",
            "-f",
        ),  # fmt: skip
        ("text", "good.pdf", "truncated.pdf", "--out-dir", "L", "--name", NAME_TEMPLATE),
    ):
        cell = driver.cell()
        dry, real = _pair(driver, argv, cell)
        assert dry.rc == real.rc
        assert entries(dry) == entries(real)
        assert deg_lines(dry) == deg_lines(real)

    # (d) the occupied-target refusal
    cell = driver.cell()
    _cwd, xdir = cell
    (xdir / "existing.pdf").write_bytes(b"occupied")
    dry, real = _pair(driver, ("compress", "good.pdf", "-O", "L/existing.pdf"), cell)
    assert (dry.rc, entries(dry), deg_lines(dry)) == (5, [], [])
    assert (real.rc, entries(real), deg_lines(real)) == (5, [], [])

    # (e) `tables` with no table builds no writer, so it predicts nothing and says so in both modes
    cell = driver.cell()
    dry, real = _pair(driver, ("tables", "good.pdf", "-O", "L/f.csv"), cell)
    assert (dry.rc, real.rc) == (0, 0)
    assert entries(dry) == entries(real) == []
    assert deg_lines(dry) == deg_lines(real) == []
    assert dry.warnings == real.warnings
    assert dry.envelope["items"][0]["output"] is None
    assert list(_xdir_listing(cell)) == []


def _xdir_listing(cell: tuple[Path, Path]) -> Iterator[Path]:
    return iter(sorted(cell[1].iterdir()))


# --------------------------------------------------------------------------- #
# AC7 -- placement and parity
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("leaf", "name"), _matrix_params())
def test_ac7_placement_and_parity(driver: Driver, leaf: str, name: str) -> None:
    shape = shape_for(leaf, name)
    same = shape_for(leaf, name, device="local")
    assert shape is not None
    assert same is not None
    cell = driver.cell()
    cwd, _xdir = cell
    prepare(shape, leaf, cell, cross=True)
    cross = driver.dry(shape.argv, cell)
    cell_local = driver.cell()
    prepare(same, leaf, cell_local, cross=False)
    local = driver.dry(same.argv, cell_local)
    assert cross.rc == local.rc == 0
    assert len(deg_lines(cross)) == len(shape.typed)  # one printed line per planned target
    assert deg_lines(cross) == entries(cross)
    # (a) minus the degraded lines, the dry stderr is the same-device dry stderr
    assert without_deg(cross) == local.err
    # (b) with the writer entries removed, the dry warnings are the same-device dry warnings
    kept = [entry for entry in cross.warnings if not entry.startswith(DEGRADED_PREFIX)]
    assert kept == local.warnings
    # the degraded lines print before the verb's own warnings, as the real run orders them
    printed = [line for line in cross.err.splitlines() if line]
    first = [
        index
        for index, line in enumerate(printed)
        if line.startswith("warning: " + DEGRADED_PREFIX)
    ]
    own = [
        index
        for index, line in enumerate(printed)
        if line.startswith("warning: ") and index not in first
    ]
    assert all(index < min(own) for index in first) if own else True
    assert cwd.is_dir()


@pytest.mark.parametrize("leaf", _leaf_params(("compress", "split", "text")))
def test_ac7_formats_agree(driver: Driver, leaf: str) -> None:
    for name in ("a", "c"):
        shape = shape_for(leaf, name)
        if shape is None:
            continue
        cell = driver.cell()
        baseline = driver.dry(shape.argv, cell)
        for flag in ("ndjson", "table"):
            other = driver.dry(shape.argv, cell, "-o", flag)
            assert other.rc == 0
            assert other.err == baseline.err
            if flag == "ndjson":
                records = [json.loads(line) for line in other.out.splitlines() if line.strip()]
                assert records
                assert not any("warnings" in record for record in records)


# --------------------------------------------------------------------------- #
# AC8 -- merge / create / compose are unchanged (exactly one line, no double print)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("leaf", sorted(ALREADY_PREDICTING))
def test_ac8_merge_create_compose_unchanged(driver: Driver, leaf: str) -> None:
    shape = shape_for(leaf, "a")
    same = shape_for(leaf, "a", device="local")
    assert shape is not None
    assert same is not None
    cell = driver.cell()
    cwd, _xdir = cell
    expected = deg(cwd, "L/x.pdf")
    dry = driver.dry(shape.argv, cell)
    real = driver.run(shape.argv, cell)
    for run in (dry, real):
        assert run.rc == 0, run.err
        assert entries(run) == [expected]
        assert deg_lines(run) == [expected]
    cell = driver.cell()
    dry_local = driver.dry(same.argv, cell)
    real_local = driver.run(same.argv, cell)
    for run in (dry_local, real_local):
        assert run.rc == 0, run.err
        assert entries(run) == []
        assert deg_lines(run) == []


# --------------------------------------------------------------------------- #
# AC9 (b) -- in-process: the helper creates nothing and enters no writer
# --------------------------------------------------------------------------- #


def _dry_policy() -> SafetyPolicy:
    return SafetyPolicy(
        dry_run=True,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )


def _recorded(call: Any) -> tuple[str, ...]:
    token = open_writer_warnings()
    try:
        call()
        return writer_warnings()
    finally:
        close_writer_warnings(token)


def test_ac9_dry_writes_nothing(
    driver: Driver, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    cell = driver.cell()
    cwd, xdir = cell
    predict = _helper()
    target = cwd / "L" / "fresh.pdf"
    created = cwd / "L" / "newsub" / "x.pdf"
    expected = deg(cwd, str(target))

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the prediction wrote or entered a writer")

    before = snapshot(cwd, xdir)
    with monkeypatch.context() as patch:
        for owner, attribute in (
            (AtomicWriter, "__enter__"),
            (AtomicWriter, "_plan"),
            (AtomicWriter, "_open_temp"),
            (sys.modules["tempfile"], "NamedTemporaryFile"),
            (sys.modules["tempfile"], "mkstemp"),
            (os, "mkdir"),
            (Path, "mkdir"),
        ):
            patch.setattr(owner, attribute, refuse)
        recorded = _recorded(lambda: predict([target], policy=_dry_policy(), kind="pdf"))
        none = _recorded(lambda: predict([created], policy=_dry_policy(), kind="pdf"))
    capfd.readouterr()
    assert recorded == (expected,)
    assert none == ()
    assert_unchanged(before, snapshot(cwd, xdir))
    assert not (xdir / "newsub").exists()


# --------------------------------------------------------------------------- #
# AC10 -- one producer, one wording (in-process)
# --------------------------------------------------------------------------- #


def test_ac10_one_producer_one_wording(driver: Driver, capfd: pytest.CaptureFixture[str]) -> None:
    cell = driver.cell()
    cwd, _xdir = cell
    predict = _helper()
    target = cwd / "L" / "w.pdf"
    policy = _dry_policy()

    def via_writer() -> None:
        with AtomicWriter(target, policy=policy, kind="pdf"):
            pass

    token = open_writer_warnings()
    try:
        predict([target], policy=policy, kind="pdf")
        helper_recorded = writer_warnings()
        from_ledger = publish_writer_warnings(
            dataclasses.replace(_result(), warnings=("x",))
        ).warnings
    finally:
        close_writer_warnings(token)
    writer_recorded = _recorded(via_writer)
    capfd.readouterr()
    assert len(helper_recorded) == 1
    assert helper_recorded == writer_recorded  # (a) byte for byte
    assert from_ledger == ("x", helper_recorded[0])

    # (b) a same-device target records nothing
    assert _recorded(lambda: predict([cwd / "local" / "w.pdf"], policy=policy, kind="pdf")) == ()
    capfd.readouterr()

    # (c) with no ledger open: nothing raises, nothing is recorded
    predict([target], policy=policy, kind="pdf")
    capfd.readouterr()
    assert writer_warnings() == ()

    # (d) no f-string or concatenation names DEGRADED_PREFIX outside the two base producers
    users: set[str] = set()
    for module in sorted(SRC.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for name, func in _functions_with_calls_and_defs(tree):
            for node in ast.walk(func):
                if isinstance(node, ast.JoinedStr | ast.BinOp) and "DEGRADED_PREFIX" in ast.unparse(
                    node
                ):
                    users.add(f"{module.name}:{name}")
    assert users == {
        "atomic.py:AtomicWriter._warn_if_destination_moved",
        "atomic.py:AtomicWriter._replace_across_devices",
    }


def _functions_with_calls_and_defs(tree: ast.Module) -> Iterator[tuple[str, ast.AST]]:
    yield from _functions_with_calls(tree)


def _result() -> Any:
    from pdf_tooling.models import OperationResult

    return OperationResult(
        schema_version=1, verb="probe", dry_run=True, items=(), warnings=(), duration_ms=0
    )


# --------------------------------------------------------------------------- #
# AC11 -- alias-shaped: one directory, two spellings; --in-place through a symlink
# --------------------------------------------------------------------------- #


def test_ac11_alias_two_spellings(driver: Driver) -> None:
    cell = driver.cell()
    cwd, xdir = cell
    spelled = f"{xdir}/a.pdf"
    for dry in (True, False):
        run = (
            driver.dry(("compress", "good.pdf", "-O", spelled, "-f"), cell)
            if dry
            else driver.run(("compress", "good.pdf", "-O", spelled, "-f"), cell)
        )
        assert run.rc == 0
        assert entries(run) == []
        assert deg_lines(run) == []

    expected = deg(cwd, "L/b.pdf")
    dry = driver.dry(("compress", "good.pdf", "-O", "L/b.pdf", "-f"), cell)
    real = driver.run(("compress", "good.pdf", "-O", "L/b.pdf", "-f"), cell)
    assert entries(dry) == [expected]
    assert entries(real) == [expected]
    assert deg_lines(dry) == [expected]  # the spelling as typed, byte for byte

    real_copy = xdir / "ip-real.pdf"
    shutil.copy(cwd / "good.pdf", real_copy)
    (cwd / "ip-link.pdf").symlink_to(real_copy)
    in_place = deg(cwd, "ip-link.pdf")
    argv = ("compress", "ip-link.pdf", "--in-place", "-y")
    dry_ip = driver.dry(argv, cell)
    real_ip = driver.run(argv, cell)
    assert dry_ip.rc == real_ip.rc == 0
    assert entries(dry_ip) == [in_place]
    assert entries(real_ip) == [in_place]
    assert tempfile.gettempdir()
    assert REPO_ROOT.is_dir()
