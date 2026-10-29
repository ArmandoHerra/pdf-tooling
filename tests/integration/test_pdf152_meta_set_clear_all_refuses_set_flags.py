"""PDF-152 -- `meta set --clear-all` combined with a set flag is REFUSED at exit 2
(operator ruling OR-70), and `--dry-run` predicts it.

THE DEFECT (carrier B-527). ``meta set x.pdf --clear-all --title plain -O y.pdf``
exited 0 in both modes, wrote ``y.pdf`` with no ``/Title`` and no XMP packet, and
reported ``warnings: []``: the ``--title`` the operator typed was silently dropped.

THE FIX under test: ``ops/metadata.py::meta_set_run`` raises a plain ``UsageError``
(exit 2, kind ``usage``) when ``--clear-all`` is combined with any field flag or
``--clear-producer``, directly after the no-destination ``UsageError`` and before
the PDF-127 / filesystem / password / document tiers, so both modes emit the same
envelope.

Provenance of every pinned literal: ``e83c743`` (``origin/main`` before the wave-1
siblings; ``meta set`` is byte-identical at ``8bb0bac``), 2026-10-28 (PDF-152 E4),
re-recorded at Validation step 0 on 2026-10-29 from a clean export of the worktree
base. Dry stdout hashes are exact; real stdout hashes are taken after normalising
only ``duration_ms``.

This module imports NO name the fix adds at module level, so copying it onto a tree
without the fix collects cleanly and its decisive nodes fail on the (dry, real)
pair, not on an ``ImportError``.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

import pytest
import typer

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_tooling.cli.main import app  # noqa: E402
from pdf_tooling.errors import UsageError  # noqa: E402
from pdf_tooling.safety.policy import SafetyPolicy  # noqa: E402
from registry import run_cli  # noqa: E402

pytestmark = pytest.mark.e2e

_PATCHED: Final[tuple[str, ...]] = (
    "plan_filesystem",
    "read_source_bytes",
    "require_structure",
    "predict_password_refusal",
    "AtomicWriter",
)
_INV: Final[bytes] = b"A\xffB"
_SDE: Final[str] = "1767225600"

#: Literals recorded at Validation step 0 (see module docstring). Full sha256.
_C8_DRY: Final[str] = "0c5312fdc1fe67b40b8f96729e254bdb77a687be01fd47bf8f5c8a360d0d3ba4"
_C8_REAL: Final[str] = "5e25aa2e59e38cc1b61179a45e3244f2d5090b501a4452b2e9d7638900161f37"
_C9_BOTH: Final[str] = "25d22ff9ae21832ecc28dc4393e5689e6e48eb1f50a266b9c11e90cfa4f4a880"
_C10_BOTH: Final[str] = "ed143d503c752db0db476343cac0046870a1d1738f24654660c56ef9c946027d"
_C12_BOTH: Final[str] = "c1ec7e59d4e8f8e64a4794af15b568c43ce10ae8e6af3d09824fe9de03a73995"
_C15_BOTH: Final[str] = "96aad524ce9af9eeb5d73d555db18d5b6450d82aeb1cd134159495fef7fa44fa"
_C16A_BOTH: Final[str] = "42d2032fdad41456c49434a2c97edb218a1515020784c13bdd64eceea3f65878"
_C16B_BOTH: Final[str] = "bde141f1e78ffb6e890a2dfe37028b35003cab45709c685f93c350d1bde6b661"
_C18D_BOTH: Final[str] = "7648a1c7758424cb14d77f92344e487206282056640f53788fc5bdedf6b8173a"
_C18_DRY: Final[str] = "f8800bc461c55b4cbeaa8b9ae1fc5329e3cd4a994ca771d5b09141f77ebe01e5"
_C18_REAL: Final[Mapping[str, str]] = {
    "C18a": "a119e8629c5a21b08e9ea890bbe36d161547815c84cda5f52133e2627f9f71a9",
    "C18b": "df1d4cdd7b4111a1406a6dadbebef84e3fa404f77024b8aa16864292816f0165",
    "C18c": "3a5be325056cfc52d1930660329371972edf170a0bb3b021598240c1f4bfb9c1",
}

_NO_PW: Final[Mapping[str, str]] = {
    k: v for k, v in os.environ.items() if k != "PDF_TOOLING_PASSWORD"
}
_PINNED_ENV: Final[Mapping[str, str]] = {**_NO_PW, "SOURCE_DATE_EPOCH": _SDE}

_cell_counter = itertools.count()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _normalised_sha(stdout: str) -> str:
    return _sha_bytes(re.sub(r'"duration_ms": \d+', '"duration_ms": 0', stdout).encode())


def _message(flags: list[str]) -> str:
    """The D1 template, written out independently of the product."""
    return (
        f"--clear-all cannot be combined with {', '.join(flags)}; --clear-all empties "
        "document-level /Info and removes the XMP packet, so run it on its own, then run "
        "meta set again to set a field"
    )


def _derive() -> dict[str, Any]:
    """The `meta set` leaf's own options, minus the global block and `--clear-all`."""
    root = typer.main.get_command(app)
    leaves: list[Any] = []

    def _walk(cmd: Any) -> None:
        children = getattr(cmd, "commands", None)
        if children is not None:
            for child in children.values():
                _walk(child)
            return
        leaves.append(cmd)

    _walk(root)
    meta_set = root.commands["meta"].commands["set"]  # type: ignore[attr-defined]
    shared = set.intersection(*({p.name for p in leaf.params} for leaf in leaves))
    strings: dict[str, str] = {}
    flags: set[str] = set()
    other: list[str] = []
    for param in meta_set.params:
        if param.param_type_name != "option" or param.name in shared:
            continue
        longs = [o for o in param.opts if o.startswith("--")]
        if longs == ["--clear-all"]:
            continue
        if param.is_flag:
            flags.update(longs)
        elif param.type.name == "str":
            for opt in longs:
                strings[opt] = param.name
        else:
            other.extend(longs)
    global_longs = {o for p in meta_set.params if p.name in shared for o in p.opts}
    return {"strings": strings, "flags": flags, "other": other, "global": global_longs}


_POP: Final[dict[str, Any]] = _derive()
#: An empty derivation must RED the matrices, never silently skip them.
REFUSED: Final[tuple[str, ...]] = tuple(
    sorted(set(_POP["strings"]) | {f for f in _POP["flags"] if f.startswith("--clear-")})
) or ("DERIVATION-EMPTY",)


@pytest.fixture(scope="module")
def fixtures_dir(tmp_path_factory: pytest.TempPathFactory, corpus: Any) -> Path:
    root = tmp_path_factory.mktemp("pdf152-fixtures")
    (root / "a.txt").write_text("hello\n", encoding="utf-8")
    made = run_cli(
        "create", "a.txt", "-O", "base.pdf", "-o", "json", cwd=root, stdin="", env=dict(_PINNED_ENV)
    )
    assert made.returncode == 0, made.stderr[-500:]
    shutil.copy(corpus.path("xmp_bearing"), root / "xmp.pdf")
    shutil.copy(corpus.path("encrypted_aes256"), root / "enc.pdf")
    (root / "corrupt.pdf").write_bytes((root / "base.pdf").read_bytes()[:200])
    return root


def _cell(tmp_path: Path, fixtures_dir: Path, *names: str) -> Path:
    cell = tmp_path / f"cell{next(_cell_counter)}"
    cell.mkdir()
    for name in names:
        shutil.copy(fixtures_dir / name, cell / name)
    return cell


def _listing(cell: Path) -> list[str]:
    return sorted(p.name for p in cell.iterdir())


def _snapshot(cell: Path) -> tuple[list[str], dict[str, str]]:
    names = _listing(cell)
    return names, {n: _sha(cell / n) for n in names if (cell / n).is_file()}


def _run(
    cell: Path,
    *argv: str,
    dry: bool,
    fmt: str = "json",
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    head = ["--dry-run"] if dry else []
    tail = ["-o", fmt] if fmt else []
    return run_cli(
        "meta set",
        *head,
        *argv,
        *tail,
        cwd=cell,
        stdin="",
        env=dict(env if env is not None else _NO_PW),
    )


def _both(
    cell: Path, *argv: str, env: Mapping[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[str]]:
    return _run(cell, *argv, dry=True, env=env), _run(cell, *argv, dry=False, env=env)


def _pair(dry: subprocess.CompletedProcess[str], real: subprocess.CompletedProcess[str]) -> Any:
    return (dry.returncode, real.returncode)


def _context(dry: subprocess.CompletedProcess[str], real: subprocess.CompletedProcess[str]) -> str:
    return (
        f"dry={dry.stdout[:240]!r} dry_err={dry.stderr[-200:]!r} "
        f"real={real.stdout[:240]!r} real_err={real.stderr[-200:]!r}"
    )


def _assert_refused(
    dry: subprocess.CompletedProcess[str],
    real: subprocess.CompletedProcess[str],
    cell: Path,
    before: tuple[list[str], dict[str, str]],
    flags: list[str],
    label: str,
) -> None:
    """The refusal outcome (Acceptance Criteria preamble)."""
    assert _pair(dry, real) == (2, 2), f"{label}: {_pair(dry, real)} {_context(dry, real)}"
    for run in (dry, real):
        assert "Traceback" not in run.stderr, run.stderr[-500:]
    assert dry.stdout == real.stdout, f"{label}: dry/real stdout differ"
    document = json.loads(real.stdout)
    assert set(document) == {"schema_version", "error"}, document
    assert document["schema_version"] == 1
    error = document["error"]
    assert error["code"] == 2 and error["kind"] == "usage" and error["path"] is None, error
    assert error["message"] == _message(flags), f"{label}: {error['message']!r}"
    assert _snapshot(cell) == before, f"{label}: the cell changed: {_listing(cell)}"


def _flag_argv(flag: str) -> list[str]:
    return [flag] if flag.startswith("--clear-") else [flag, "plain"]


def _policy(*, dry_run: bool) -> SafetyPolicy:
    return SafetyPolicy(
        dry_run=dry_run,
        force=False,
        in_place=False,
        backup=True,
        assume_yes=False,
        is_tty=False,
        threads=1,
    )


# --------------------------------------------------------------------------- #
# AC1 -- the population is derived, not typed.
# --------------------------------------------------------------------------- #


def test_ac1_population_is_derived() -> None:
    import pdf_tooling.ops.metadata as metadata_module

    strings: dict[str, str] = _POP["strings"]
    flags: set[str] = _POP["flags"]
    assert _POP["other"] == [], f"unexpected non-string non-flag options: {_POP['other']}"
    assert set(strings) == {"--" + f for f in metadata_module.SETTABLE_FIELDS}, strings
    for opt, name in strings.items():
        assert name == opt[2:], (opt, name)
    prefixed = {f for f in flags if f.startswith("--clear-")}
    rest = flags - prefixed
    assert prefixed == {"--clear-" + f for f in metadata_module.CLEARABLE_FIELDS}, prefixed
    assert prefixed == {"--clear-producer"}
    assert rest == {"--allow-decrypted-output"}, rest
    assert set(REFUSED) == set(strings) | prefixed
    assert "--allow-decrypted-output" not in REFUSED
    for opt in ("--name", "--password-file", "--dry-run"):
        assert opt in _POP["global"], opt
        assert opt not in REFUSED


# --------------------------------------------------------------------------- #
# AC2 -- the refused matrix (GR-002), plus the premise cell.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fixture", ("base.pdf", "xmp.pdf"))
@pytest.mark.parametrize("flag", REFUSED)
def test_ac2_refused_pairs(tmp_path: Path, fixtures_dir: Path, flag: str, fixture: str) -> None:
    cell = _cell(tmp_path, fixtures_dir, fixture)
    before = _snapshot(cell)
    dry, real = _both(cell, fixture, "--clear-all", *_flag_argv(flag), "-O", "y.pdf")
    _assert_refused(dry, real, cell, before, [flag], f"{fixture} {flag}")


def test_ac2_empty_title_is_still_a_supplied_flag(tmp_path: Path, fixtures_dir: Path) -> None:
    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    before = _snapshot(cell)
    dry, real = _both(cell, "base.pdf", "--clear-all", "--title", "", "-O", "y.pdf")
    _assert_refused(dry, real, cell, before, ["--title"], "empty title")


@pytest.mark.parametrize("keep", (("--no-backup",), ("-y",)), ids=("C7a", "C7b"))
def test_ac2_in_place_with_no_backup_or_yes_is_refused(
    tmp_path: Path, fixtures_dir: Path, keep: tuple[str, ...]
) -> None:
    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    before = _snapshot(cell)
    dry, real = _both(cell, "base.pdf", "--clear-all", "--title", "plain", "--in-place", *keep)
    _assert_refused(dry, real, cell, before, ["--title"], f"in-place {keep}")
    assert not (cell / "base.pdf.bak").exists()


# --------------------------------------------------------------------------- #
# AC3 -- declaration order, not argv order, not sorted().
# --------------------------------------------------------------------------- #


def test_ac3_message_names_flags_in_declaration_order(tmp_path: Path, fixtures_dir: Path) -> None:
    outs: list[str] = []
    for argv in (
        ["--clear-all", "--title", "plain", "--author", "a"],
        ["--author", "a", "--title", "plain", "--clear-all"],
    ):
        cell = _cell(tmp_path, fixtures_dir, "base.pdf")
        before = _snapshot(cell)
        dry, real = _both(cell, "base.pdf", *argv, "-O", "y.pdf")
        _assert_refused(dry, real, cell, before, ["--title", "--author"], f"order {argv}")
        assert real.stdout.startswith(
            '{"schema_version": 1, "error": {"code": 2, "kind": "usage", "message": '
            '"--clear-all cannot be combined with --title, --author;'
        )
        outs.append(real.stdout)
    assert outs[0] == outs[1]

    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    before = _snapshot(cell)
    dry, real = _both(
        cell, "base.pdf", "--clear-all", "--title", "t", "--clear-producer", "-O", "y.pdf"
    )
    _assert_refused(dry, real, cell, before, ["--title", "--clear-producer"], "producer last")


# --------------------------------------------------------------------------- #
# AC4 -- the exit-table and precedence matrix (GR-002).
# --------------------------------------------------------------------------- #


def _existing_output(cell: Path) -> None:
    (cell / "y.pdf").write_bytes(b"existing\n")


_AC4_ROWS: Final[
    tuple[tuple[str, tuple[str, ...], list[str], Callable[[Path], None] | None], ...]
] = (
    ("C6", ("base.pdf",), ["base.pdf", "--clear-all", "--title", "plain", "--in-place"], None),
    (
        "C11",
        ("base.pdf",),
        ["base.pdf", "--clear-all", "--title", "plain", "-O", "y.pdf"],
        _existing_output,
    ),
    (
        "C13",
        ("enc.pdf",),
        [
            "enc.pdf",
            "--clear-all",
            "--title",
            "plain",
            "-O",
            "y.pdf",
            "--allow-decrypted-output",
        ],
        None,
    ),
    (
        "C14",
        ("corrupt.pdf",),
        ["corrupt.pdf", "--clear-all", "--title", "plain", "-O", "y.pdf"],
        None,
    ),
    (
        "C17",
        ("xmp.pdf",),
        ["xmp.pdf", "--clear-all", "--title", "plain", "-O", "y.pdf"],
        None,
    ),
)


@pytest.mark.parametrize("row", _AC4_ROWS, ids=lambda r: r[0])
def test_ac4_exit_table_pairs(
    tmp_path: Path,
    fixtures_dir: Path,
    row: tuple[str, tuple[str, ...], list[str], Callable[[Path], None] | None],
) -> None:
    name, files, argv, setup = row
    cell = _cell(tmp_path, fixtures_dir, *files)
    if setup is not None:
        setup(cell)
    before = _snapshot(cell)
    dry, real = _both(cell, *argv)
    _assert_refused(dry, real, cell, before, ["--title"], name)


def test_ac4_c10_missing_source_stays_exit_4(tmp_path: Path, fixtures_dir: Path) -> None:
    cell = _cell(tmp_path, fixtures_dir)
    dry, real = _both(cell, "nope.pdf", "--clear-all", "--title", "plain", "-O", "y.pdf")
    assert _pair(dry, real) == (4, 4), _context(dry, real)
    for run in (dry, real):
        assert json.loads(run.stdout)["error"]["kind"] == "no_input"


def test_ac4_c12_encrypted_input_gate_still_answers_first(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    cell = _cell(tmp_path, fixtures_dir, "enc.pdf")
    before = _snapshot(cell)
    dry, real = _both(cell, "enc.pdf", "--clear-all", "--title", "plain", "-O", "y.pdf")
    assert _pair(dry, real) == (5, 5), _context(dry, real)
    for run in (dry, real):
        assert json.loads(run.stdout)["error"]["kind"] == "refused"
    assert _snapshot(cell) == before


# --------------------------------------------------------------------------- #
# AC5 -- every unmoved cell is byte-identical to the base.
# --------------------------------------------------------------------------- #


def test_ac5_unmoved_cells_are_byte_identical(tmp_path: Path, fixtures_dir: Path) -> None:
    inv = os.fsdecode(_INV)
    rows: list[tuple[str, tuple[str, ...], list[str], tuple[int, int], str, str]] = [
        (
            "C8",
            ("base.pdf",),
            ["base.pdf", "--clear-all", "--in-place"],
            (5, 5),
            _C8_DRY,
            _C8_REAL,
        ),
        (
            "C9",
            ("base.pdf",),
            ["base.pdf", "--clear-all", "--title", inv, "-O", "y.pdf"],
            (2, 2),
            _C9_BOTH,
            _C9_BOTH,
        ),
        (
            "C10",
            (),
            ["nope.pdf", "--clear-all", "--title", "plain", "-O", "y.pdf"],
            (4, 4),
            _C10_BOTH,
            _C10_BOTH,
        ),
        (
            "C12",
            ("enc.pdf",),
            ["enc.pdf", "--clear-all", "--title", "plain", "-O", "y.pdf"],
            (5, 5),
            _C12_BOTH,
            _C12_BOTH,
        ),
        (
            "C15",
            ("base.pdf",),
            ["base.pdf", "--clear-all", "--title", "plain"],
            (2, 2),
            _C15_BOTH,
            _C15_BOTH,
        ),
        (
            "C16a",
            ("base.pdf",),
            ["base.pdf", "--clear-all", "--title", "plain", "-O", "y.pdf", "--in-place"],
            (2, 2),
            _C16A_BOTH,
            _C16A_BOTH,
        ),
        (
            "C16b",
            ("base.pdf",),
            ["base.pdf", "--clear-all", "--title", "plain", "--out-dir", "d"],
            (2, 2),
            _C16B_BOTH,
            _C16B_BOTH,
        ),
        (
            "C18d",
            ("base.pdf",),
            ["base.pdf", "-O", "y.pdf"],
            (2, 2),
            _C18D_BOTH,
            _C18D_BOTH,
        ),
    ]
    for name, files, argv, pair, dry_sha, real_sha in rows:
        cell = _cell(tmp_path, fixtures_dir, *files)
        dry, real = _both(cell, *argv)
        assert _pair(dry, real) == pair, f"{name}: {_pair(dry, real)} {_context(dry, real)}"
        assert _sha_bytes(dry.stdout.encode()) == dry_sha, f"{name}: dry {dry.stdout!r}"
        assert _normalised_sha(real.stdout) == real_sha, f"{name}: real {real.stdout!r}"


_SUCCESS: Final[tuple[tuple[str, list[str]], ...]] = (
    ("C18a", ["--clear-all"]),
    ("C18b", ["--title", "plain"]),
    ("C18c", ["--clear-producer", "--title", "plain"]),
)


@pytest.mark.parametrize("case", _SUCCESS, ids=lambda c: c[0])
def test_ac5_success_controls(
    tmp_path: Path, fixtures_dir: Path, case: tuple[str, list[str]]
) -> None:
    name, flags = case
    outputs: list[str] = []
    for _ in range(2):  # two fresh cells from copies of one pinned base.pdf
        cell = _cell(tmp_path, fixtures_dir, "base.pdf")
        dry, real = _both(cell, "base.pdf", *flags, "-O", "y.pdf")
        assert _pair(dry, real) == (0, 0), _context(dry, real)
        assert _sha_bytes(dry.stdout.encode()) == _C18_DRY, dry.stdout
        assert _normalised_sha(real.stdout) == _C18_REAL[name], real.stdout
        outputs.append(_sha(cell / "y.pdf"))
    assert outputs[0] == outputs[1], f"{name}: the output file is not byte-stable"


# --------------------------------------------------------------------------- #
# AC6 -- every renderer refuses identically.
# --------------------------------------------------------------------------- #


def test_ac6_every_renderer_refuses_identically(tmp_path: Path, fixtures_dir: Path) -> None:
    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    before = _snapshot(cell)
    refusal = _message(["--title"])
    bad = ("base.pdf", "--clear-all", "--title", "plain", "-O", "y.pdf")

    # ndjson: byte-equal to the product's own rendering of the nothing-to-set error.
    reference = _run(cell, "base.pdf", "-O", "y.pdf", dry=False, fmt="ndjson")
    assert reference.returncode == 2 and "requires at least one field flag" in reference.stdout
    shaped = json.loads(reference.stdout)
    shaped["error"]["message"] = refusal
    expected = json.dumps(shaped) + "\n"
    runs = {dry: _run(cell, *bad, dry=dry, fmt="ndjson") for dry in (True, False)}
    for run in runs.values():
        assert run.returncode == 2, run.stderr[-300:]
        assert "Traceback" not in run.stderr
        assert run.stdout == expected, (run.stdout, expected)

    # default format on a non-TTY.
    default = {dry: _run(cell, *bad, dry=dry, fmt="") for dry in (True, False)}
    for run in default.values():
        assert run.returncode == 2, run.stderr[-300:]
        assert "Traceback" not in run.stderr
        assert refusal in run.stdout + run.stderr
    assert default[True].stdout == default[False].stdout
    assert _snapshot(cell) == before


# --------------------------------------------------------------------------- #
# AC7 -- the Python API refuses before any work.
# --------------------------------------------------------------------------- #


def _install_patch_set(monkeypatch: pytest.MonkeyPatch) -> None:
    import pdf_tooling.ops.metadata as module

    def _boom(name: str) -> Callable[..., Any]:
        def _raise(*args: object, **kwargs: object) -> Any:
            raise AssertionError(f"PDF-152 AC7: reached {name}")

        return _raise

    for name in _PATCHED:
        monkeypatch.setattr(module, name, _boom(name))


@pytest.mark.parametrize("dry_run", (True, False), ids=("dry", "real"))
def test_ac7_python_api_refuses_before_any_work(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch, dry_run: bool
) -> None:
    from pdf_tooling.ops.metadata import meta_set_run

    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    before = _snapshot(cell)
    src, out = cell / "base.pdf", cell / "o.pdf"
    _install_patch_set(monkeypatch)

    def call(sets: dict[str, str], *, clear_producer: bool, clear_all: bool) -> Any:
        return meta_set_run(
            src,
            sets=sets,
            clear_producer=clear_producer,
            clear_all=clear_all,
            output=out,
            in_place=False,
            policy=_policy(dry_run=dry_run),
        )

    for sets, producer, flags in (
        ({"title": "plain"}, False, ["--title"]),
        ({}, True, ["--clear-producer"]),
    ):
        with pytest.raises(UsageError) as caught:
            call(sets, clear_producer=producer, clear_all=True)
        assert type(caught.value) is UsageError
        assert caught.value.message == _message(flags)

    # Accepted calls do not raise UsageError: they reach a patched tier or return rc 0.
    for sets, clear_all in (({"title": "plain"}, False), ({}, True)):
        try:
            result = call(sets, clear_producer=False, clear_all=clear_all)
        except AssertionError as reached:
            assert "PDF-152 AC7: reached" in str(reached)
        else:
            assert getattr(result, "exit_code", 0) == 0
    assert _snapshot(cell) == before


# --------------------------------------------------------------------------- #
# AC8 -- `meta set --help` states the rule (hyphen-free fragments only).
# --------------------------------------------------------------------------- #


def _collapse(text: str) -> str:
    return " ".join(text.split())


def test_ac8_help_states_the_rule(tmp_path: Path) -> None:
    from pdf_tooling.cli import cmd_meta_set

    sentence = (
        "--clear-all cannot be combined with a field flag or --clear-producer: the run "
        "exits 2; run it on its own, then set fields in a second run."
    )
    assert sentence in _collapse(cmd_meta_set._HELP)
    for columns in ("80", "200"):
        env = {**_NO_PW, "COLUMNS": columns}
        done = run_cli("meta set", "--help", cwd=tmp_path, stdin="", env=env)
        assert done.returncode == 0, done.stderr[-300:]
        text = _collapse(done.stdout)
        assert "cannot be combined with a field flag" in text, (columns, text[-900:])
        assert "run it on its own, then set fields in a second run." in text, columns


# --------------------------------------------------------------------------- #
# AC10 -- the frozen surface, as far as the module can see it.
# --------------------------------------------------------------------------- #


def test_ac10_frozen_surface(tmp_path: Path, fixtures_dir: Path) -> None:
    from pdf_tooling import errors

    assert not [n for n in vars(errors) if "ClearAll" in n]
    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    dry, real = _both(cell, "base.pdf", "--clear-all", "--title", "plain", "-O", "y.pdf")
    for run in (dry, real):
        document = json.loads(run.stdout)
        assert document["schema_version"] == 1
        assert set(document["error"]) == {"code", "kind", "message", "path"}
