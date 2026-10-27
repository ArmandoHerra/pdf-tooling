"""PDF-150 -- `meta set` refuses a non-Unicode value with the error envelope, and
`--dry-run` predicts it.

THE DEFECT (ledger `3044f42cda`, carrier B-519). ``meta set base.pdf --title
"$(printf 'A\\xffB')" -O out.pdf -o json --dry-run`` predicted rc 0
(``planned: meta set``); the same argv without ``--dry-run`` exited 1 with 0 B
on stdout and two chained tracebacks ending ``UnicodeEncodeError: 'utf-16-be'
codec can't encode character '\\udcff'``. Python's argv decoder
(``surrogateescape``) turns every argv byte the command-line encoding cannot
decode into a surrogate code point, and no PDF text string can carry one.

THE FIX under test: ``ops/metadata.py::meta_set_run`` refuses any value holding
a surrogate (U+D800-U+DFFF) with a plain ``UsageError`` (exit 2, kind
``usage``) before the dry/real fork and before any filesystem, document or
engine work, so dry and real emit the same envelope.

Provenance of every literal below: ``549f589`` (v1.2.2) as measured 2026-10-26
(PDF-150 Evidence E2-E8), re-driven at the worktree base on 2026-10-27.

This module deliberately imports NO name that the fix adds at module level (the
purity node resolves ``_reject_unencodable_values`` with ``getattr`` inside its
own body), so copying it onto a tree without the fix collects cleanly and the
nodes fail on the behaviour, not on an ``ImportError``.
"""

from __future__ import annotations

import builtins
import hashlib
import itertools
import json
import os
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

REPO_ROOT: Final[Path] = TESTS_DIR.parent
SRC_METADATA: Final[Path] = REPO_ROOT / "src" / "pdf_tooling" / "ops" / "metadata.py"

#: Value set (raw argv bytes). Evidence "Value set" table.
RAW: Final[Mapping[str, bytes]] = {
    "INV": b"A\xffB",  # invalid UTF-8 byte
    "SUR": b"A\xed\xa0\x80B",  # UTF-8-encoded lone surrogate U+D800 (invalid strict UTF-8)
    "C1RAW": b"A\x9bB",  # raw C1 byte, invalid UTF-8
    "C1OK": b"A\xc2\x9bB",  # U+009B as valid UTF-8
    "CTL": b"A\x01B",  # valid ASCII control
    "UNI": "Aé漢\U0001f600B".encode(),  # valid non-ASCII incl. an astral code point
    "ASCII": b"plain",
}
BAD: Final[tuple[str, ...]] = ("INV", "SUR", "C1RAW")
GOOD: Final[tuple[str, ...]] = ("ASCII", "CTL", "C1OK", "UNI")
#: The first undecodable byte per BAD value, as D3 names it.
BAD_BYTE: Final[Mapping[str, int]] = {"INV": 0xFF, "SUR": 0xED, "C1RAW": 0x9B}
FIXTURES: Final[tuple[str, ...]] = ("base.pdf", "xmp_bearing.pdf")

#: `meta get` /Info key per `meta set` field.
INFO_KEY: Final[Mapping[str, str]] = {
    "title": "Title",
    "author": "Author",
    "subject": "Subject",
    "keywords": "Keywords",
    "creator": "Creator",
}

_PATCHED: Final[tuple[str, ...]] = (
    "plan_filesystem",
    "read_source_bytes",
    "require_structure",
    "predict_password_refusal",
    "AtomicWriter",
)

#: Resolved with getattr inside the purity node only, so the module collects on a tree without D1.
_HELPER_NAME: Final[str] = "_reject_unencodable_values"

_cell_counter = itertools.count()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _arg(raw: bytes) -> str:
    """The argv string whose OS encoding is exactly *raw* (round-trips via fsencode)."""
    return os.fsdecode(raw)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _child_encoding(env: Mapping[str, str] | None = None) -> str:
    done = subprocess.run(
        [sys.executable, "-c", "import sys; print(sys.getfilesystemencoding())"],
        capture_output=True,
        text=True,
        check=True,
        env=dict(env) if env is not None else None,
        stdin=subprocess.DEVNULL,
    )
    return done.stdout.strip()


def _message(field: str, what: str, position: int, encoding: str) -> str:
    """The D3 template, written out independently of the product."""
    return (
        f"--{field} is not Unicode text: {what} at character {position}; "
        f"metadata values must be text in the command-line encoding ({encoding})"
    )


def _byte_what(byte: int) -> str:
    return f"byte 0x{byte:02X} could not be decoded"


def _derive_population() -> frozenset[str]:
    """`meta set`'s own non-flag STRING options, derived from the live Click tree."""
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
    return frozenset(
        opt
        for param in meta_set.params
        if param.param_type_name == "option"  # typer vendors its own click: duck-typed
        and param.name not in shared
        and not param.is_flag
        and param.type.name == "str"
        for opt in param.opts
        if opt.startswith("--")
    )


#: An empty derivation must RED the matrices, never silently skip them.
OPTS: Final[tuple[str, ...]] = tuple(sorted(o[2:] for o in _derive_population())) or (
    "DERIVATION-EMPTY",
)


def _split(fixture: str) -> str:
    return fixture.removesuffix(".pdf")


@pytest.fixture(scope="module")
def fixtures_dir(tmp_path_factory: pytest.TempPathFactory, corpus: Any) -> Path:
    root = tmp_path_factory.mktemp("pdf150-fixtures")
    (root / "a.txt").write_text("hello\n", encoding="utf-8")
    made = run_cli("create", "a.txt", "-O", "base.pdf", "-o", "json", cwd=root, stdin="")
    assert made.returncode == 0, made.stderr[-500:]
    shutil.copy(corpus.path("xmp_bearing"), root / "xmp_bearing.pdf")
    shutil.copy(corpus.path("encrypted_aes256"), root / "encrypted.pdf")
    # A truncated PDF (Validation step 0): the first 200 bytes of base.pdf.
    (root / "corrupt.pdf").write_bytes((root / "base.pdf").read_bytes()[:200])
    return root


def _cell(tmp_path: Path, fixtures_dir: Path, *names: str) -> Path:
    """A fresh cell directory holding copies of *names* (the input fixtures)."""
    cell = tmp_path / f"cell{next(_cell_counter)}"
    cell.mkdir()
    for name in names:
        shutil.copy(fixtures_dir / name, cell / name)
    return cell


def _listing(cell: Path) -> list[str]:
    return sorted(p.name for p in cell.iterdir())


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
        env=dict(env) if env is not None else None,
    )


def _both(
    cell: Path, *argv: str, env: Mapping[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[str]]:
    dry = _run(cell, *argv, dry=True, env=env)
    real = _run(cell, *argv, dry=False, env=env)
    return dry, real


def _no_crash_text(run: subprocess.CompletedProcess[str]) -> None:
    for needle in ("Traceback", "UnicodeEncodeError", "utf-16-be", "surrogates not allowed"):
        assert needle not in run.stderr, f"{needle!r} in stderr: {run.stderr[-600:]!r}"
        assert needle not in run.stdout, f"{needle!r} in stdout: {run.stdout[-600:]!r}"


def _assert_refused(
    dry: subprocess.CompletedProcess[str],
    real: subprocess.CompletedProcess[str],
    cell: Path,
    *,
    message: str,
    expect_listing: list[str],
    input_sha: Mapping[str, str],
    label: str,
) -> None:
    """The refusal outcome (Acceptance Criteria preamble)."""
    assert (dry.returncode, real.returncode) == (2, 2), (
        f"{label}: pair {(dry.returncode, real.returncode)}; dry stderr={dry.stderr[-300:]!r} "
        f"real stderr={real.stderr[-300:]!r}"
    )
    for run in (dry, real):
        _no_crash_text(run)
    assert dry.stdout == real.stdout, f"{label}: dry/real stdout differ"
    document = json.loads(real.stdout)
    assert set(document) == {"schema_version", "error"}, document
    assert document["schema_version"] == 1
    error = document["error"]
    assert error["code"] == 2 and error["kind"] == "usage" and error["path"] is None, error
    assert error["message"] == message, f"{label}: {error['message']!r} != {message!r}"
    assert _listing(cell) == expect_listing, f"{label}: cell holds {_listing(cell)}"
    for name, digest in input_sha.items():
        assert _sha256(cell / name) == digest, f"{label}: {name} changed"


def _meta_get(cell: Path, name: str) -> dict[str, Any]:
    done = run_cli("meta get", name, "-o", "json", cwd=cell, stdin="")
    assert done.returncode == 0, done.stderr[-400:]
    return dict(json.loads(done.stdout))


def _xmp_text(value: object) -> str | None:
    """Flatten the native XMP shapes `meta get` reports (dict / list / scalar) to text."""
    if isinstance(value, dict):
        return next(iter(value.values()), None) if value else None
    if isinstance(value, list):
        return value[0] if value else None
    return value if isinstance(value, str) else None


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


def _install_patch_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC10's patch set: every tier after the check raises `AssertionError`."""
    import pdf_tooling.ops.metadata as module

    def _boom(name: str) -> Callable[..., Any]:
        def _raise(*args: object, **kwargs: object) -> Any:
            raise AssertionError(f"PDF-150 AC4: reached {name}")

        return _raise

    for name in _PATCHED:
        monkeypatch.setattr(module, name, _boom(name))


# --------------------------------------------------------------------------- #
# AC1 -- the population is derived, not typed.
# --------------------------------------------------------------------------- #


def test_ac1_population_is_derived() -> None:
    import pdf_tooling.ops.metadata as metadata_module

    settable_fields = metadata_module.SETTABLE_FIELDS

    derived = _derive_population()
    assert derived == {"--title", "--author", "--subject", "--keywords", "--creator"}, derived
    assert derived == {"--" + f for f in settable_fields}, (derived, settable_fields)
    meta_set = typer.main.get_command(app).commands["meta"].commands["set"]  # type: ignore[attr-defined]
    by_opt = {opt: param.name for param in meta_set.params for opt in getattr(param, "opts", ())}
    for opt in derived:
        assert by_opt[opt] == opt[2:], (opt, by_opt[opt])
    assert "--name" not in derived and "--password-file" not in derived


# --------------------------------------------------------------------------- #
# AC2 -- the refused matrix (GR-002): OPTS x BAD x FIX, 30 cells.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fixture", FIXTURES)
@pytest.mark.parametrize("opt", OPTS)
def test_ac2_refused_pairs(tmp_path: Path, fixtures_dir: Path, opt: str, fixture: str) -> None:
    encoding = _child_encoding()
    if encoding != "utf-8":
        pytest.skip(f"the child's filesystem encoding is {encoding}, not utf-8")
    for name in BAD:
        cell = _cell(tmp_path, fixtures_dir, fixture)
        sha = {fixture: _sha256(cell / fixture)}
        dry, real = _both(cell, fixture, f"--{opt}", _arg(RAW[name]), "-O", "out.pdf")
        _assert_refused(
            dry,
            real,
            cell,
            message=_message(opt, _byte_what(BAD_BYTE[name]), 2, "utf-8"),
            expect_listing=[fixture],
            input_sha=sha,
            label=f"{opt}/{name}/{fixture}",
        )


# --------------------------------------------------------------------------- #
# AC3 -- the accepted matrix is lossless: OPTS x GOOD x FIX, 40 cells.
# --------------------------------------------------------------------------- #

_XMP_EXACT: Final[Mapping[str, tuple[str, ...]]] = {
    "UNI": ("title", "author", "subject", "keywords", "creator"),
    "C1OK": ("title", "author", "subject"),
}
_XMP_LEFT_UNCHANGED: Final[str] = (
    "ok (XMP packet left unchanged: rewriting the XMP packet did not verify; /Info only)"
)


@pytest.mark.parametrize("fixture", FIXTURES)
@pytest.mark.parametrize("opt", OPTS)
def test_ac3_accepted_pairs_are_lossless(
    tmp_path: Path, fixtures_dir: Path, opt: str, fixture: str
) -> None:
    encoding = _child_encoding()
    if encoding != "utf-8":
        pytest.skip(f"the child's filesystem encoding is {encoding}, not utf-8")
    for name in GOOD:
        label = f"{opt}/{name}/{fixture}"
        cell = _cell(tmp_path, fixtures_dir, fixture)
        argv = (fixture, f"--{opt}", _arg(RAW[name]), "-O", "out.pdf")
        dry = _run(cell, *argv, dry=True)
        assert dry.returncode == 0, f"{label}: dry {dry.stderr[-300:]!r}"
        dry_item = json.loads(dry.stdout)["items"][0]
        assert dry_item["ok"] is True and dry_item["message"] == "planned: meta set", dry_item
        assert dry_item["detail"]["would_exit"] == 0, dry_item
        assert _listing(cell) == [fixture], f"{label}: dry wrote something"

        real = _run(cell, *argv, dry=False)
        assert real.returncode == 0, f"{label}: real {real.stderr[-300:]!r}"
        assert "Traceback" not in real.stderr
        assert _listing(cell) == sorted([fixture, "out.pdf"]), f"{label}: {_listing(cell)}"

        expected = RAW[name].decode("utf-8")
        got = _meta_get(cell, "out.pdf")
        assert got["info"][INFO_KEY[opt]] == expected, (label, got["info"][INFO_KEY[opt]])
        real_item = json.loads(real.stdout)["items"][0]
        if fixture == "xmp_bearing.pdf":
            if name == "CTL":
                # The unchanged PDF-107 path: U+0001 is not an XML 1.0 Char.
                assert real_item["message"] == _XMP_LEFT_UNCHANGED, (label, real_item["message"])
                assert len(json.loads(real.stdout)["warnings"]) == 1, label
            if opt in _XMP_EXACT.get(name, ()):
                assert _xmp_text(got["xmp"][opt]) == expected, (label, got["xmp"])


# --------------------------------------------------------------------------- #
# AC4 -- the rule is exactly the surrogate range, through the public op.
# --------------------------------------------------------------------------- #

_REFUSE_CPS: Final[tuple[int, ...]] = (0xD800, 0xDBFF, 0xDC00, 0xDC7F, 0xDC80, 0xDCFF, 0xDFFF)
_ACCEPT_CPS: Final[tuple[int, ...]] = (0x01, 0x7F, 0x9B, 0xD7FF, 0xE000, 0xFFFD, 0x1F600, 0x10FFFF)


def _ac4_what(cp: int) -> str:
    if 0xDC80 <= cp <= 0xDCFF:
        return _byte_what(cp - 0xDC00)
    return f"lone surrogate U+{cp:04X}"


@pytest.mark.parametrize("dry_run", (True, False), ids=("dry", "real"))
@pytest.mark.parametrize("cp", _REFUSE_CPS + _ACCEPT_CPS, ids=lambda c: f"U+{c:04X}")
def test_ac4_rule_is_exactly_the_surrogate_range(
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    cp: int,
    dry_run: bool,
) -> None:
    from pdf_tooling.ops.metadata import meta_set_run

    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    source = cell / "base.pdf"
    before = _sha256(source)
    _install_patch_set(monkeypatch)

    outcome: BaseException | object | None = None
    try:
        outcome = meta_set_run(
            source,
            sets={"title": "A" + chr(cp) + "B"},
            clear_producer=False,
            clear_all=False,
            output=cell / "o.pdf",
            in_place=False,
            policy=_policy(dry_run=dry_run),
        )
    except BaseException as error:  # noqa: BLE001 - classified below
        outcome = error

    if cp in _REFUSE_CPS:
        assert type(outcome) is UsageError, f"U+{cp:04X} dry={dry_run}: got {outcome!r}"
        expected = _message("title", _ac4_what(cp), 2, sys.getfilesystemencoding())
        assert outcome.message == expected, (outcome.message, expected)
    else:
        assert not isinstance(outcome, UsageError), f"U+{cp:04X} refused: {outcome!r}"
        if isinstance(outcome, AssertionError):
            assert "PDF-150 AC4: reached" in str(outcome), outcome
        else:
            assert not isinstance(outcome, BaseException), outcome
            assert outcome.exit_code == 0  # type: ignore[union-attr]
    assert _listing(cell) == ["base.pdf"] and _sha256(source) == before


def test_ac4_helper_makes_no_os_call(monkeypatch: pytest.MonkeyPatch) -> None:
    import pdf_tooling.ops.metadata as module

    helper = getattr(module, _HELPER_NAME)  # resolved here, never at import: absent at base
    real_stat, real_os_open, real_open = os.stat, os.open, builtins.open

    def _drive(sets: Mapping[str, str]) -> tuple[BaseException | None, list[tuple[str, Any]]]:
        calls: list[tuple[str, Any]] = []

        def _spy(name: str, real: Callable[..., Any]) -> Callable[..., Any]:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                calls.append((name, args))
                return real(*args, **kwargs)

            return wrapper

        raised: BaseException | None = None
        with monkeypatch.context() as scoped:
            scoped.setattr(os, "stat", _spy("stat", real_stat))
            scoped.setattr(os, "open", _spy("os.open", real_os_open))
            scoped.setattr(builtins, "open", _spy("open", real_open))
            try:
                result = helper(sets)
            except BaseException as error:  # noqa: BLE001 - asserted after restore
                raised, result = error, "raised"
        assert result is None or raised is not None
        return raised, calls

    refused, refused_calls = _drive({"title": "A\udcffB"})
    accepted, accepted_calls = _drive({"title": "AéB"})
    assert type(refused) is UsageError, refused
    assert accepted is None, accepted
    assert refused_calls == [] and accepted_calls == [], (refused_calls, accepted_calls)


# --------------------------------------------------------------------------- #
# AC5 -- first offender and 1-based position are deterministic.
# --------------------------------------------------------------------------- #


def test_ac5_first_offender_and_position(tmp_path: Path, fixtures_dir: Path) -> None:
    encoding = _child_encoding()
    if encoding != "utf-8":
        pytest.skip(f"the child's filesystem encoding is {encoding}, not utf-8")
    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    sha = {"base.pdf": _sha256(cell / "base.pdf")}
    # --author is given first on the argv: declaration order, not argv or sorted() order, wins.
    dry, real = _both(
        cell,
        "base.pdf",
        "--author",
        _arg(RAW["SUR"]),
        "--title",
        _arg(RAW["INV"]),
        "-O",
        "o.pdf",
    )
    _assert_refused(
        dry,
        real,
        cell,
        message=_message("title", _byte_what(0xFF), 2, "utf-8"),
        expect_listing=["base.pdf"],
        input_sha=sha,
        label="declaration-order",
    )
    dry, real = _both(cell, "base.pdf", "--title", _arg(b"AB\xffC"), "-O", "o.pdf")
    _assert_refused(
        dry,
        real,
        cell,
        message=_message("title", _byte_what(0xFF), 3, "utf-8"),
        expect_listing=["base.pdf"],
        input_sha=sha,
        label="position",
    )


# --------------------------------------------------------------------------- #
# AC6 -- an ASCII command-line encoding gets a true message.
# --------------------------------------------------------------------------- #


def test_ac6_ascii_encoding_message_is_true(tmp_path: Path, fixtures_dir: Path) -> None:
    env = {**os.environ, "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "LC_ALL": "C"}
    env.pop("LANG", None)
    encoding = _child_encoding(env)
    if encoding != "ascii":
        pytest.skip(f"the child's filesystem encoding under LC_ALL=C is {encoding}, not ascii")
    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    sha = {"base.pdf": _sha256(cell / "base.pdf")}
    dry, real = _both(cell, "base.pdf", "--title", _arg(RAW["UNI"]), "-O", "o.pdf", env=env)
    message = _message("title", _byte_what(0xC3), 2, "ascii")
    _assert_refused(
        dry,
        real,
        cell,
        message=message,
        expect_listing=["base.pdf"],
        input_sha=sha,
        label="ascii-locale",
    )
    assert "utf-8" not in json.loads(real.stdout)["error"]["message"].lower()
    control = _both(cell, "base.pdf", "--title", "plain", "-O", "o.pdf", env=env)
    assert (control[0].returncode, control[1].returncode) == (0, 0), control[1].stderr[-300:]


# --------------------------------------------------------------------------- #
# AC7 -- the exit-table matrix with the precedence arms (GR-002).
# --------------------------------------------------------------------------- #

_NOTHING_TO_SET: Final[str] = (
    '{"schema_version": 1, "error": {"code": 2, "kind": "usage", "message": '
    '"meta set requires at least one field flag or a clear flag", "path": null}}'
)


class _Row:
    def __init__(
        self,
        name: str,
        files: tuple[str, ...],
        argv: Callable[[str], list[str]],
        plain: tuple[int, int],
        bad: tuple[int, int],
        *,
        setup: Callable[[Path], None] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.name, self.files, self.argv = name, files, argv
        self.plain, self.bad, self.setup, self.env = plain, bad, setup, env


def _touch_existing(cell: Path) -> None:
    (cell / "o.pdf").write_bytes(b"existing\n")


_NO_PW: Final[Mapping[str, str]] = {
    k: v for k, v in os.environ.items() if k != "PDF_TOOLING_PASSWORD"
}

ROWS: Final[tuple[_Row, ...]] = (
    _Row("ok", ("base.pdf",), lambda v: ["base.pdf", "--title", v, "-O", "o.pdf"], (0, 0), (2, 2)),
    _Row(
        "missing_source",
        (),
        lambda v: ["missing.pdf", "--title", v, "-O", "o.pdf"],
        (4, 4),
        (4, 4),
    ),
    _Row(
        "existing_output",
        ("base.pdf",),
        lambda v: ["base.pdf", "--title", v, "-O", "o.pdf"],
        (5, 5),
        (2, 2),
        setup=_touch_existing,
    ),
    _Row(
        "pdf127_clear_all_in_place",
        ("base.pdf",),
        lambda v: ["base.pdf", "--clear-all", "--title", v, "--in-place"],
        (5, 5),
        (2, 2),
    ),
    _Row(
        "encrypted_no_allow",
        ("encrypted.pdf",),
        lambda v: ["encrypted.pdf", "--title", v, "-O", "o.pdf"],
        (5, 5),
        (5, 5),
        env=_NO_PW,
    ),
    _Row(
        "encrypted_allow_no_password",
        ("encrypted.pdf",),
        lambda v: ["encrypted.pdf", "--title", v, "-O", "o.pdf", "--allow-decrypted-output"],
        (6, 6),
        (2, 2),
        env=_NO_PW,
    ),
    # Base pair recorded at Validation step 0 on the worktree base (9ed3f55), 2026-10-27:
    # dry 1 ("could not read this document's encryption"), real 1 ("could not read PDF").
    _Row(
        "corrupt_input",
        ("corrupt.pdf",),
        lambda v: ["corrupt.pdf", "--title", v, "-O", "o.pdf"],
        (1, 1),
        (2, 2),
    ),
    _Row(
        "clear_all",
        ("base.pdf",),
        lambda v: ["base.pdf", "--clear-all", "--title", v, "-O", "o.pdf"],
        (0, 0),
        (2, 2),
    ),
    _Row(
        "clear_producer",
        ("base.pdf",),
        lambda v: ["base.pdf", "--clear-producer", "--title", v, "-O", "o.pdf"],
        (0, 0),
        (2, 2),
    ),
    _Row(
        "in_place",
        ("base.pdf",),
        lambda v: ["base.pdf", "--title", v, "--in-place"],
        (0, 0),
        (2, 2),
    ),
)


@pytest.mark.parametrize("row", ROWS, ids=lambda r: r.name)
def test_ac7_exit_table_pairs(tmp_path: Path, fixtures_dir: Path, row: _Row) -> None:
    encoding = _child_encoding()
    if encoding != "utf-8":
        pytest.skip(f"the child's filesystem encoding is {encoding}, not utf-8")
    # `plain`
    cell = _cell(tmp_path, fixtures_dir, *row.files)
    if row.setup:
        row.setup(cell)
    dry, real = _both(cell, *row.argv("plain"), env=row.env)
    assert (dry.returncode, real.returncode) == row.plain, (
        f"{row.name}/plain: {(dry.returncode, real.returncode)} != {row.plain}; "
        f"dry={dry.stdout[:200]!r} real={real.stdout[:200]!r} err={real.stderr[-200:]!r}"
    )
    if row.name == "in_place":
        assert (cell / "base.pdf.bak").is_file(), "--in-place keeps its .bak"
    # `INV`
    cell = _cell(tmp_path, fixtures_dir, *row.files)
    if row.setup:
        row.setup(cell)
    listing = _listing(cell)
    sha = {name: _sha256(cell / name) for name in listing}
    dry, real = _both(cell, *row.argv(_arg(RAW["INV"])), env=row.env)
    assert (dry.returncode, real.returncode) == row.bad, (
        f"{row.name}/INV: {(dry.returncode, real.returncode)} != {row.bad}; "
        f"dry={dry.stdout[:200]!r} real={real.stdout[:200]!r} err={real.stderr[-200:]!r}"
    )
    if row.bad == (2, 2):
        _assert_refused(
            dry,
            real,
            cell,
            message=_message("title", _byte_what(0xFF), 2, "utf-8"),
            expect_listing=listing,
            input_sha=sha,
            label=f"{row.name}/INV",
        )
    else:  # a gate that answers before the check: still no traceback, nothing written
        for run in (dry, real):
            assert "Traceback" not in run.stderr
        assert _listing(cell) == listing


def test_ac7_nothing_to_set_is_the_unchanged_envelope(tmp_path: Path, fixtures_dir: Path) -> None:
    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    dry, real = _both(cell, "base.pdf", "-O", "o.pdf")
    assert (dry.returncode, real.returncode) == (2, 2)
    assert dry.stdout == real.stdout == _NOTHING_TO_SET + "\n"
    assert len(real.stdout) == 147


# --------------------------------------------------------------------------- #
# AC8 -- no traceback on any renderer.
# --------------------------------------------------------------------------- #


def test_ac8_no_traceback_on_any_renderer(tmp_path: Path, fixtures_dir: Path) -> None:
    encoding = _child_encoding()
    if encoding != "utf-8":
        pytest.skip(f"the child's filesystem encoding is {encoding}, not utf-8")
    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    refusal = _message("title", _byte_what(0xFF), 2, "utf-8")
    bad = ("base.pdf", "--title", _arg(RAW["INV"]), "-O", "o.pdf")
    nothing = ("base.pdf", "-O", "o.pdf")
    nothing_msg = "meta set requires at least one field flag or a clear flag"

    # ndjson: byte-equal to the product's own rendering of the existing usage error.
    reference = _run(cell, *nothing, dry=False, fmt="ndjson")
    assert reference.returncode == 2 and nothing_msg in reference.stdout
    shaped = json.loads(reference.stdout)
    shaped["error"]["message"] = refusal
    expected = json.dumps(shaped) + "\n"
    for dry in (True, False):
        run = _run(cell, *bad, dry=dry, fmt="ndjson")
        assert run.returncode == 2, run.stderr[-300:]
        _no_crash_text(run)
        assert run.stdout == expected, (run.stdout, expected)

    # default format on a non-TTY.
    for dry in (True, False):
        run = _run(cell, *bad, dry=dry, fmt="")
        assert run.returncode == 2, run.stderr[-300:]
        _no_crash_text(run)
        assert refusal in run.stdout + run.stderr
    assert _listing(cell) == ["base.pdf"]


# --------------------------------------------------------------------------- #
# AC9 -- the Python API refuses too.  AC10 -- decided before any work.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("dry_run", (True, False), ids=("dry", "real"))
def test_ac9_python_api_refuses(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch, dry_run: bool
) -> None:
    from pdf_tooling.ops.metadata import meta_set_run

    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    before = _sha256(cell / "base.pdf")
    _install_patch_set(monkeypatch)
    encoding = sys.getfilesystemencoding()
    for value, what in (
        ("A\ud800B", "lone surrogate U+D800"),
        ("A\udcffB", _byte_what(0xFF)),
    ):
        with pytest.raises(UsageError) as caught:
            meta_set_run(
                cell / "base.pdf",
                sets={"title": value},
                clear_producer=False,
                clear_all=False,
                output=cell / "o.pdf",
                in_place=False,
                policy=_policy(dry_run=dry_run),
            )
        assert type(caught.value) is UsageError
        assert caught.value.message == _message("title", what, 2, encoding)
    assert _listing(cell) == ["base.pdf"] and _sha256(cell / "base.pdf") == before


@pytest.mark.parametrize("dry_run", (True, False), ids=("dry", "real"))
def test_ac10_missing_source_is_answered_before_the_value_check(
    tmp_path: Path, dry_run: bool
) -> None:
    """D2 'held': a missing source stays exit 4; `reject_missing_sources` runs first (X-1168 a)."""
    from pdf_tooling.errors import PdfToolingError
    from pdf_tooling.ops.metadata import meta_set_run

    with pytest.raises(PdfToolingError) as caught:
        meta_set_run(
            tmp_path / "missing.pdf",
            sets={"title": "A\udcffB"},
            clear_producer=False,
            clear_all=False,
            output=tmp_path / "o.pdf",
            in_place=False,
            policy=_policy(dry_run=dry_run),
        )
    error = caught.value
    assert error.exit_code == 4, (type(error), error)
    assert type(error) is not UsageError
    for needle in ("utf-16", "surrogate", "Unicode text"):
        assert needle not in error.message, error.message


@pytest.mark.parametrize("dry_run", (True, False), ids=("dry", "real"))
def test_ac10_decided_before_any_work(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch, dry_run: bool
) -> None:
    from pdf_tooling.ops.metadata import meta_set_run

    cell = _cell(tmp_path, fixtures_dir, "base.pdf")
    _install_patch_set(monkeypatch)  # plan_filesystem/read_source_bytes/require_structure/... raise
    with pytest.raises(UsageError):
        meta_set_run(
            cell / "base.pdf",
            sets={"title": "A\udcffB"},
            clear_producer=False,
            clear_all=False,
            output=cell / "o.pdf",
            in_place=False,
            policy=_policy(dry_run=dry_run),
        )


# --------------------------------------------------------------------------- #
# AC11 -- successful runs unchanged (literals recorded at Validation step 0).
# --------------------------------------------------------------------------- #

# Recorded 2026-10-27 at the worktree base 9ed3f55 (before any edit): `meta set base.pdf
# --title plain -O o9.pdf`, base.pdf built by `create`. `bytes_*` are asserted against
# the files' real sizes and then masked; `duration_ms` (item level) is masked.
_ITEM_KEYS: Final[list[str]] = [
    "input",
    "output",
    "ok",
    "exit_code",
    "message",
    "bytes_before",
    "bytes_after",
    "duration_ms",
    "detail",
]
_DRY_DETAIL: Final[dict[str, Any]] = {
    "would_exit": 0,
    "password_source": None,
    "password_verified": False,
}
_REAL_DETAIL: Final[dict[str, Any]] = {"wrote_xmp": False}


def _item(*, dry: bool) -> dict[str, Any]:
    return {
        "input": "base.pdf",
        "output": "o9.pdf",
        "ok": True,
        "exit_code": 0,
        "message": "planned: meta set" if dry else "ok (no XMP packet; /Info only)",
        "bytes_before": "<size of base.pdf>",
        "bytes_after": None if dry else "<size of o9.pdf>",
        "duration_ms": "<masked>",
        "detail": _DRY_DETAIL if dry else _REAL_DETAIL,
    }


def _normalised(doc: dict[str, Any], cell: Path, *, dry: bool) -> dict[str, Any]:
    if "items" in doc:
        item = doc["items"][0]
    else:  # ndjson: the item's keys sit beside the envelope's own three
        item = {k: v for k, v in doc.items() if k not in ("schema_version", "verb", "dry_run")}
    assert item["bytes_before"] == (cell / "base.pdf").stat().st_size
    if not dry:
        assert item["bytes_after"] == (cell / "o9.pdf").stat().st_size
    item = {**item, "bytes_before": "<size of base.pdf>", "duration_ms": "<masked>"}
    if not dry:
        item["bytes_after"] = "<size of o9.pdf>"
    assert list(item) == _ITEM_KEYS
    return item


@pytest.mark.parametrize("fmt", ("json", "ndjson"))
def test_ac11_success_shapes_unchanged(tmp_path: Path, fixtures_dir: Path, fmt: str) -> None:
    for dry in (True, False):
        cell = _cell(tmp_path, fixtures_dir, "base.pdf")
        run = _run(cell, "base.pdf", "--title", "plain", "-O", "o9.pdf", dry=dry, fmt=fmt)
        assert run.returncode == 0, run.stderr[-300:]
        doc = json.loads(run.stdout)
        assert doc["schema_version"] == 1 and doc["verb"] == "meta set"
        assert doc["dry_run"] is dry
        assert _normalised(doc, cell, dry=dry) == _item(dry=dry)
        if fmt == "json":
            assert doc["warnings"] == [] and doc["exit_code"] == 0
            assert list(doc) == [
                "schema_version",
                "verb",
                "dry_run",
                "items",
                "warnings",
                "duration_ms",
                "exit_code",
            ]
        else:
            assert list(doc) == ["schema_version", "verb", "dry_run", *_ITEM_KEYS]


# --------------------------------------------------------------------------- #
# AC12 -- the frozen surface and the diff's own shape.
# --------------------------------------------------------------------------- #


#: X-1182. The arm measures PDF-150's OWN landed commit, commit to commit, never the branch it
#: happens to run on: a merge-base against origin/main measured every later branch (X-1181).
PDF150_COMMIT: Final[str] = "662fa6ae5726e7d7b42c987150758960599e3e7e"
PDF150_SUBJECT: Final[str] = (
    "[PDF-150] fix: refuse a non-UTF-8 meta set value at exit 2 and predict it in --dry-run"
)
_FROZEN_PATHS: Final[tuple[str, ...]] = (
    "src/pdf_tooling/errors.py",
    "src/pdf_tooling/cli/",
    "src/pdf_tooling/adapters/",
    "README.md",
    "tests/golden/",
)
_ALLOWED_SRC: Final[frozenset[str]] = frozenset({"src/pdf_tooling/ops/metadata.py"})


def _git(*args: str, repo: Path = REPO_ROOT, env: Mapping[str, str] | None = None) -> str | None:
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
            env=None if env is None else dict(env),
        )
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def _frozen_surface_violations(
    repo: Path, parent: str, commit: str, env: Mapping[str, str] | None = None
) -> list[str]:
    """Violations of the PDF-150 diff shape between two COMMITS (never the working tree)."""

    def run(*args: str) -> str:
        out = _git(*args, repo=repo, env=env)
        assert out is not None, f"git {' '.join(args)} failed in {repo}"
        return out

    found: list[str] = []
    frozen = run("diff", "--name-only", parent, commit, "--", *_FROZEN_PATHS)
    found += [f"frozen surface changed: {n}" for n in frozen.split()]
    for name in run("diff", "--name-only", parent, commit, "--", "src/").split():
        if name not in _ALLOWED_SRC:
            found.append(f"src/ name outside the allow-list: {name}")
    for line in run("diff", "--numstat", parent, commit, "--", "src/").splitlines():
        _added, deleted, path = line.split("\t", 2)
        if deleted != "0":
            found.append(f"the src/ diff deletes {deleted} line(s): {path}")
    return found


def test_ac12_frozen_surface() -> None:
    # The class and schema pins hold on any checkout.
    assert SRC_METADATA.is_file()
    assert UsageError.exit_code == 2 and UsageError.kind == "usage"
    # X-1182: history-dependent, so skip only where the pinned commit or its parent is absent
    # (a shallow clone; a depth-1 clone AT the pin has the commit but not its parent).
    if any(_git("cat-file", "-e", f"{PDF150_COMMIT}{rev}^{{commit}}") is None for rev in ("", "^")):
        pytest.skip(f"shallow history: PDF-150 commit {PDF150_COMMIT[:7]} or its parent is absent")
    subject = _git("log", "-1", "--format=%s", PDF150_COMMIT)
    assert subject is not None and subject.strip() == PDF150_SUBJECT, (
        f"PDF150_COMMIT no longer names PDF-150: {subject!r}"
    )
    assert _frozen_surface_violations(REPO_ROOT, f"{PDF150_COMMIT}^", PDF150_COMMIT) == []


# Synthetic arms: the real arm measures immutable history and can never go red again, so the
# helper is proven able to see each break on a hermetic temp repo (X-1182).


def _synthetic_env(tmp_path: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", HOME=str(tmp_path))
    return env


def _commit(repo: Path, env: Mapping[str, str], files: Mapping[str, str | None], msg: str) -> str:
    for rel, text in files.items():
        path = repo / rel
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    ident = [
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "-c",
        "commit.gpgsign=false",
    ]
    assert _git("add", "-A", repo=repo, env=env) is not None
    assert _git(*ident, "commit", "-q", "-m", msg, repo=repo, env=env) is not None
    head = _git("rev-parse", "HEAD", repo=repo, env=env)
    assert head is not None
    return head.strip()


def _base_repo(tmp_path: Path) -> tuple[Path, dict[str, str], str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    env = _synthetic_env(tmp_path)
    assert _git("init", "-q", repo=repo, env=env) is not None
    base = _commit(
        repo,
        env,
        {
            "README.md": "readme\n",
            "src/pdf_tooling/errors.py": "e1\ne2\n",
            "src/pdf_tooling/ops/metadata.py": "m1\n",
            "src/pdf_tooling/cli/x.py": "c1\n",
        },
        "base",
    )
    return repo, env, base


def test_ac12_synthetic_s1_a_metadata_only_commit_is_clean(tmp_path: Path) -> None:
    repo, env, base = _base_repo(tmp_path)
    s1 = _commit(repo, env, {"src/pdf_tooling/ops/metadata.py": "m1\nm2\nm3\n"}, "s1")
    assert _frozen_surface_violations(repo, base, s1, env) == []


def test_ac12_synthetic_s2_a_later_commit_never_moves_the_measurement(tmp_path: Path) -> None:
    repo, env, base = _base_repo(tmp_path)
    s1 = _commit(repo, env, {"src/pdf_tooling/ops/metadata.py": "m1\nm2\n"}, "s1")
    s2 = _commit(
        repo,
        env,
        {"README.md": "changed\n", "src/pdf_tooling/errors.py": "e1\n"},
        "s2",
    )
    assert _frozen_surface_violations(repo, base, s1, env) == []
    own = "\n".join(_frozen_surface_violations(repo, s1, s2, env))
    assert "README.md" in own and "errors.py" in own
    assert "deletes 1 line(s)" in own


def test_ac12_synthetic_s3_a_cli_touch_is_named(tmp_path: Path) -> None:
    repo, env, base = _base_repo(tmp_path)
    s3 = _commit(
        repo,
        env,
        {"src/pdf_tooling/ops/metadata.py": "m1\nm2\n", "src/pdf_tooling/cli/x.py": "c1\nc2\n"},
        "s3",
    )
    found = "\n".join(_frozen_surface_violations(repo, base, s3, env))
    assert "src/pdf_tooling/cli/x.py" in found
