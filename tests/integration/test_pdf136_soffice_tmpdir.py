"""PDF-136 -- LibreOffice's temp directory lives inside the product's own
per-invocation ``ScratchDir``, so a ``convert --timeout`` kill leaves nothing in
the user's ``$TMPDIR``.

LibreOffice creates ``lu<pid><rand>.tmp`` in whatever ``TMPDIR`` it inherits and
removes it only on a clean exit; the process-group kill gives it none. The
conversion spawn now gets ``TMPDIR=<scratch root>``, a directory the product
created and already removes on every exit path. This is NOT a reaper: the product
never lists, globs or matches ``lu*`` and never touches an entry it did not
create (AC5).

Step-0 calibration (LibreOffice 24.2.7.2, base ``6d23e74``, 2026-10-26):
``big.txt`` is 40000 lines of 1080 chars; ``--timeout 0.5`` timed out 3/3 and left
3 ``lu*.tmp`` at base (the ``93a251f005`` repro). AC2's in-process recorder saw an
``lu*.tmp`` inside the scratch root 10/10 on COLD starts (fresh HOME every trial)
at both 0.5 s and 1.0 s; 1.0 s is used for margin.

Every CLI arm uses a private ``TMPDIR`` reached through a deliberately symlinked
parent (GR-009 alias shape) and a redirected ``HOME``.
"""

from __future__ import annotations

import ast
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from pdf_tooling.adapters import soffice_office, subprocess_util  # noqa: E402
from pdf_tooling.errors import FailureError  # noqa: E402
from pdf_tooling.ops.office import convert_run  # noqa: E402
from pdf_tooling.safety.atomic import ScratchDir  # noqa: E402
from pdf_tooling.safety.policy import SafetyPolicy  # noqa: E402
from pdf_tooling.safety.tempnames import TEMP_PREFIX  # noqa: E402
from registry import run_cli  # noqa: E402

SRC_ROOT: Final[Path] = Path(__file__).resolve().parents[2] / "src" / "pdf_tooling"

#: Timeout of the CLI timeout arms (AC1, AC5a); measured 3/3 at base.
CLI_TIMEOUT_S: Final[str] = "0.5"
#: Timeout of the in-process arm (AC2); lu*.tmp present 10/10 on cold starts.
INPROC_TIMEOUT_S: Final[float] = 1.0


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


def _private_tmpdir(tmp_path: Path, name: str = "") -> tuple[Path, Path]:
    """``(link_path, real_path)``: a private empty TMPDIR reached via a symlink."""
    real_parent = tmp_path / f"real{name}"
    real_parent.mkdir()
    link_parent = tmp_path / f"link{name}"
    link_parent.symlink_to(real_parent, target_is_directory=True)
    priv_real = real_parent / "tmp"
    priv_real.mkdir()
    return link_parent / "tmp", priv_real


def _cli_env(tmpdir: Path, home: Path) -> dict[str, str]:
    home.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["TMPDIR"] = str(tmpdir)
    env["HOME"] = str(home)
    return env


def _write_big(path: Path) -> None:
    path.write_text(("lorem ipsum dolor sit amet " * 40 + "\n") * 40000)


def _listing(link: Path, real: Path) -> list[str]:
    via_link = sorted(os.listdir(link))
    via_real = sorted(os.listdir(real))
    assert via_link == via_real
    return via_real


@pytest.mark.requires("soffice")
def test_ac1_timeout_kills_leave_tmpdir_empty(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    big = work / "big.txt"
    _write_big(big)
    link, real = _private_tmpdir(tmp_path)
    env = _cli_env(link, tmp_path / "home")
    for trial in range(1, 4):
        out = work / f"o{trial}"
        out.mkdir()
        proc = run_cli(
            "convert",
            str(big),
            "--out-dir",
            str(out),
            "--timeout",
            CLI_TIMEOUT_S,
            stdin="",
            env=env,
            cwd=work,
        )
        assert proc.returncode == 1, (trial, proc.returncode, proc.stderr, proc.stdout)
        assert "timed out" in proc.stdout + proc.stderr, (trial, proc.stdout, proc.stderr)
        assert os.listdir(out) == [], (trial, os.listdir(out))
        assert _listing(link, real) == [], f"trial {trial}: TMPDIR not empty"


@pytest.mark.requires("soffice")
def test_ac2_engine_tempdir_lands_inside_the_scratch_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    link, real = _private_tmpdir(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("TMPDIR", str(link))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(tempfile, "tempdir", None)

    big = tmp_path / "big.txt"
    _write_big(big)
    seen: list[dict[str, Any]] = []
    real_run = subprocess_util.run

    def _recorder(argv: Any, **kwargs: Any) -> Any:
        result = real_run(argv, **kwargs)
        if "--convert-to" in argv:
            env = kwargs.get("env")
            assert env is not None, "the conversion spawn passed no env="
            root = Path(env["TMPDIR"])
            seen.append(
                {
                    "timed_out": result.timed_out,
                    "root": root,
                    "entries": sorted(os.listdir(root)) if root.exists() else None,
                }
            )
        return result

    monkeypatch.setattr(soffice_office.subprocess_util, "run", _recorder)
    with pytest.raises(FailureError, match="timed out"):
        convert_run(
            [big],
            filter_name=None,
            timeout=INPROC_TIMEOUT_S,
            output=None,
            out_dir=tmp_path / "out",
            name_template=None,
            policy=_policy(),
        )
    assert len(seen) == 1, seen
    record = seen[0]
    assert record["timed_out"] is True, record
    lu = [
        name
        for name in (record["entries"] or [])
        if name.startswith("lu") and name.endswith(".tmp")
    ]
    assert lu, f"no lu*.tmp inside the scratch root; it held {record['entries']}"
    assert not record["root"].exists(), "the scratch root survived the kill path"
    assert _listing(link, real) == []


def test_ac3_conversion_env_is_inherited_plus_tmpdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    link, _real = _private_tmpdir(tmp_path)
    monkeypatch.setenv("TMPDIR", str(link))
    monkeypatch.setenv("TMP", "/sentinel/tmp")
    monkeypatch.setenv("TEMP", "/sentinel/temp")
    monkeypatch.setattr(tempfile, "tempdir", None)

    recorded: list[dict[str, Any]] = []

    def _fake_run(argv: Any, **kwargs: Any) -> subprocess_util.ProcRun:
        recorded.append(kwargs)
        return subprocess_util.ProcRun(
            argv=tuple(str(a) for a in argv),
            returncode=-9,
            stdout="",
            stderr="",
            duration_ms=0,
            timed_out=True,
            pgid=0,
        )

    monkeypatch.setattr(soffice_office.subprocess_util, "run", _fake_run)
    source = tmp_path / "note.txt"
    source.write_text("hello")
    with ScratchDir(seed=soffice_office.ADAPTER.scratch_seed()) as scratch_root:
        with pytest.raises(FailureError, match="timed out"):
            soffice_office.ADAPTER.convert_to_pdf(
                source, scratch_dir=scratch_root, filter_name=None, timeout=1.0
            )
        env = recorded[0]["env"]
        assert env["TMPDIR"] == str(scratch_root)  # verbatim, not canonicalized
        assert os.path.samefile(env["TMPDIR"], os.path.realpath(scratch_root))
        assert str(scratch_root).startswith(str(link)), (scratch_root, link)
        expected = {k: v for k, v in os.environ.items() if k != "TMPDIR"}
        assert {k: v for k, v in env.items() if k != "TMPDIR"} == expected
        assert env["TMP"] == "/sentinel/tmp"
        assert env["TEMP"] == "/sentinel/temp"

    base = {"A": "1"}
    produced = soffice_office._conversion_env(tmp_path, base=base)
    assert produced == {"A": "1", "TMPDIR": str(tmp_path)}
    assert base == {"A": "1"}


@pytest.mark.requires("soffice")
def test_ac4_successful_conversions_leave_tmpdir_empty(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "note.txt").write_text("hello\n")
    for trial in range(1, 4):
        link, real = _private_tmpdir(tmp_path, str(trial))
        assert _listing(link, real) == [], f"trial {trial}: TMPDIR not empty before"
        env = _cli_env(link, tmp_path / "home")
        proc = run_cli(
            "convert",
            "note.txt",
            "--out-dir",
            "cv",
            "-f",
            stdin="",
            env=env,
            cwd=work,
        )
        assert proc.returncode == 0, (trial, proc.stdout, proc.stderr)
        pdf = work / "cv" / "note.pdf"
        assert pdf.is_file() and pdf.stat().st_size > 0
        assert pdf.read_bytes().startswith(b"%PDF-")
        assert _listing(link, real) == [], f"trial {trial}: TMPDIR holds leftovers after"


@pytest.mark.requires("soffice")
def test_ac5_foreign_entries_in_tmpdir_survive_a_timeout(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    big = work / "big.txt"
    _write_big(big)
    link, real = _private_tmpdir(tmp_path)
    foreign_dir = real / "lu999999zzzzz.tmp"
    foreign_dir.mkdir(mode=0o700)
    foreign_dir.chmod(0o700)
    (foreign_dir / "child.bin").write_bytes(b"keep me")
    foreign_file = real / f"{TEMP_PREFIX}foreign"
    foreign_file.write_bytes(b"keep me too")

    def _snapshot(path: Path) -> tuple[Any, ...]:
        st = path.lstat()
        kids = sorted(os.listdir(path)) if path.is_dir() else None
        return (path.name, stat.S_IMODE(st.st_mode), st.st_mtime_ns, kids)

    before = {p.name: _snapshot(p) for p in (foreign_dir, foreign_file)}
    out = work / "o1"
    out.mkdir()
    proc = run_cli(
        "convert",
        str(big),
        "--out-dir",
        str(out),
        "--timeout",
        CLI_TIMEOUT_S,
        stdin="",
        env=_cli_env(link, tmp_path / "home"),
        cwd=work,
    )
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "timed out" in proc.stdout + proc.stderr
    assert sorted(os.listdir(real)) == sorted(before), os.listdir(real)
    after = {p.name: _snapshot(p) for p in (foreign_dir, foreign_file)}
    assert after == before
    assert (foreign_dir / "child.bin").read_bytes() == b"keep me"


_GLOB_CALLS: Final[frozenset[str]] = frozenset({"glob", "rglob", "iglob", "fnmatch", "fnmatchcase"})
_LIST_CALLS: Final[frozenset[str]] = frozenset({"listdir", "scandir", "iterdir", "glob", "rglob"})


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_gettempdir_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _call_name(node) == "gettempdir"


def _engine_temp_findings(tree: ast.AST, label: str) -> list[str]:
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name in _GLOB_CALLS:
            for arg in node.args:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and arg.value.startswith("lu")
                ):
                    findings.append(f"{label}:{node.lineno}: {name}({arg.value!r})")
        if name in _LIST_CALLS:
            operands: list[ast.AST] = list(node.args)
            if isinstance(node.func, ast.Attribute):
                operands.append(node.func.value)
            for operand in operands:
                if any(_is_gettempdir_call(sub) for sub in ast.walk(operand)):
                    findings.append(f"{label}:{node.lineno}: {name}(... gettempdir() ...)")
    return findings


def test_ac5_src_names_no_engine_temp_glob() -> None:
    findings: list[str] = []
    files = sorted(SRC_ROOT.rglob("*.py"))
    assert files, SRC_ROOT
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        findings.extend(_engine_temp_findings(tree, str(path.relative_to(SRC_ROOT))))
    assert findings == [], findings


def test_ac5_detector_sees_a_planted_janitor() -> None:
    """Non-vacuity: the AST walk flags the exact shapes the AC names."""
    planted = ast.parse(
        "import tempfile\n"
        "from pathlib import Path\n"
        "for p in Path(tempfile.gettempdir()).glob('lu*.tmp'):\n"
        "    pass\n"
    )
    found = _engine_temp_findings(planted, "planted.py")
    assert any("glob('lu*.tmp')" in f for f in found), found
    assert any("gettempdir()" in f for f in found), found
