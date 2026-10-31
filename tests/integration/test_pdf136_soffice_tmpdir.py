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
import contextlib
import os
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar, Final

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


#: PDF-164: the hang ceiling of the lu gate. The worst natural second ``lu*.tmp`` was
#: 9.4 s (E3), so this is a hang guard with more than 3x headroom, never a tuning knob.
_LU_GATE_CEILING_S: Final[float] = 30.0


def _lu_names(directory: Path | None) -> list[str]:
    if directory is None:
        return []
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    return sorted(n for n in names if n.startswith("lu") and n.endswith(".tmp"))


def _group_gone(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


class _LuGate(subprocess.Popen[str]):
    """Holds the product's real ``communicate(timeout=...)`` back until a persistent
    ``lu*.tmp`` is observable, so the kill cannot land in soffice's own gap.

    LibreOffice creates a first ``lu*.tmp``, removes it itself 30-190 ms later, then
    creates a second that persists (E3). A fixed 1.0 s kill sometimes lands between the
    two. The gate waits until two distinct names were seen and one is present, bounded
    by the engine group's lifetime and ``ceiling_s``. The poll paces the wait; the
    directory state is the oracle. Only the timed ``--convert-to`` communicate is gated,
    once per instance; every other call is a pass-through.
    """

    root: ClassVar[Path | None] = None
    user_tmp: ClassVar[Path | None] = None
    ceiling_s: ClassVar[float] = _LU_GATE_CEILING_S
    poll_s: ClassVar[float] = 0.005
    observation: ClassVar[list[tuple[str, list[str], float]]] = []
    spawned: ClassVar[list[int]] = []
    _fired: bool = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        type(self).spawned.append(self.pid)

    def communicate(  # type: ignore[override]
        self, input: str | None = None, timeout: float | None = None
    ) -> tuple[str, str]:
        if timeout is not None and "--convert-to" in self.args and not self._fired:
            self._fired = True
            self._hold()
        return super().communicate(input, timeout)

    def _hold(self) -> None:
        cls = type(self)
        seen: set[str] = set()
        started = time.monotonic()
        while True:
            if _lu_names(cls.user_tmp):
                verdict = "outside"
                break
            present = _lu_names(cls.root)
            seen.update(present)
            if len(seen) >= 2 and present:
                verdict = "inside"
                break
            if self.poll() is not None and _group_gone(self.pid):
                verdict = "exited"
                break
            if time.monotonic() - started >= cls.ceiling_s:
                verdict = "ceiling"
                break
            time.sleep(cls.poll_s)
        cls.observation.append((verdict, sorted(seen), time.monotonic() - started))


#: A stand-in for the engine, driven as ``[python, -I, -c, SRC, --convert-to, mode, extra]``.
#: Its blocking is the subject under test, not synchronization.
_STANDIN_SRC: Final[str] = textwrap.dedent(
    """
    import os, subprocess, sys, threading, time
    mode, extra = sys.argv[2], sys.argv[3]
    tmp = os.environ.get("TMPDIR", "")

    def touch(path):
        open(path, "w").close()

    def block():
        threading.Event().wait()

    if mode == "inside":
        touch(tmp + "/lu1.tmp")
        time.sleep(0.05)
        os.remove(tmp + "/lu1.tmp")
        touch(tmp + "/lu2.tmp")
        block()
    elif mode == "outside":
        touch(extra + "/lu9.tmp")
        block()
    elif mode == "exit":
        sys.exit(0)
    elif mode == "orphan":
        child = subprocess.Popen(
            [sys.executable, "-I", "-c", "import threading; threading.Event().wait()"]
        )
        with open(extra + "/grandchild.pid", "w") as handle:
            handle.write(str(child.pid))
        sys.exit(0)
    elif mode == "gap":
        os.mkdir(tmp + "/profile")
        touch(tmp + "/lu1.tmp")
        time.sleep(0.05)
        os.remove(tmp + "/lu1.tmp")
        time.sleep(float(extra))
        touch(tmp + "/lu2.tmp")
        block()
    else:
        block()
    """
)


def _standin(mode: str, extra: str) -> list[str]:
    return [sys.executable, "-I", "-c", _STANDIN_SRC, "--convert-to", mode, extra]


def _configure_gate(
    monkeypatch: pytest.MonkeyPatch, *, root: Path, user_tmp: Path, ceiling_s: float
) -> list[tuple[str, list[str], float]]:
    observation: list[tuple[str, list[str], float]] = []
    monkeypatch.setattr(_LuGate, "root", root)
    monkeypatch.setattr(_LuGate, "user_tmp", user_tmp)
    monkeypatch.setattr(_LuGate, "ceiling_s", ceiling_s)
    monkeypatch.setattr(_LuGate, "observation", observation)
    monkeypatch.setattr(_LuGate, "spawned", [])
    return observation


@contextlib.contextmanager
def _watchdog(seconds: float = 10.0) -> Iterator[None]:
    """Outer guard: kills every stand-in group the gate spawned if a test hangs."""

    def _kill() -> None:
        for pgid in list(_LuGate.spawned):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(pgid, signal.SIGKILL)

    timer = threading.Timer(seconds, _kill)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()
        _kill()


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
    observation = _configure_gate(
        monkeypatch, root=tmp_path, user_tmp=real, ceiling_s=_LU_GATE_CEILING_S
    )
    monkeypatch.setattr(subprocess_util.subprocess, "Popen", _LuGate)

    def _recorder(argv: Any, **kwargs: Any) -> Any:
        if "--convert-to" not in argv:
            return real_run(argv, **kwargs)
        env = kwargs.get("env")
        assert env is not None, "the conversion spawn passed no env="
        profile = [a for a in argv if str(a).startswith("-env:UserInstallation=file://")]
        assert len(profile) == 1, argv
        root = Path(profile[0].split("file://", 1)[1]).parent
        assert env["TMPDIR"] == str(root), (
            f"the engine's TMPDIR {env['TMPDIR']!r} is not the product's scratch root"
        )
        monkeypatch.setattr(_LuGate, "root", root)
        result = real_run(argv, **kwargs)
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
    where = f"loadavg {os.getloadavg()}, gate {observation}"
    assert [row[0] for row in observation] == ["inside"], where
    assert len(observation[0][1]) >= 2, where
    assert record["timed_out"] is True, f"{record} ({where})"
    lu = [
        name
        for name in (record["entries"] or [])
        if name.startswith("lu") and name.endswith(".tmp")
    ]
    assert lu, f"no lu*.tmp inside the scratch root; it held {record['entries']} ({where})"
    assert not record["root"].exists(), f"the scratch root survived the kill path ({where})"
    assert _listing(link, real) == [], where


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


# --------------------------------------------------------------------------- #
# PDF-164: the lu gate, driven by a stand-in engine (no soffice needed).
# --------------------------------------------------------------------------- #


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "root"
    user = tmp_path / "user"
    root.mkdir()
    user.mkdir()
    return root, user


def test_pdf164_gate_releases_once_a_persistent_lu_is_inside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, user = _dirs(tmp_path)
    observation = _configure_gate(monkeypatch, root=root, user_tmp=user, ceiling_s=10.0)
    monkeypatch.setattr(subprocess_util.subprocess, "Popen", _LuGate)
    with _watchdog():
        result = subprocess_util.run(
            _standin("inside", ""),
            timeout=INPROC_TIMEOUT_S,
            env={**os.environ, "TMPDIR": str(root)},
        )
    assert len(observation) == 1, observation
    assert observation[0][0] == "inside", observation
    assert observation[0][1] == ["lu1.tmp", "lu2.tmp"], observation
    assert result.timed_out is True
    assert _lu_names(root) == ["lu2.tmp"]


def test_pdf164_gate_reds_when_lu_lands_in_the_user_tmpdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, user = _dirs(tmp_path)
    observation = _configure_gate(monkeypatch, root=root, user_tmp=user, ceiling_s=5.0)
    monkeypatch.setattr(subprocess_util.subprocess, "Popen", _LuGate)
    with _watchdog():
        subprocess_util.run(
            _standin("outside", str(user)),
            timeout=INPROC_TIMEOUT_S,
            env={**os.environ, "TMPDIR": str(root)},
        )
    assert [row[0] for row in observation] == ["outside"], observation
    assert observation[0][2] < 5.0, observation
    assert _lu_names(user) == ["lu9.tmp"]


class _LiveSampler(threading.Thread):
    """In-flight instrument: samples the grandchild's liveness while ``run`` is blocked."""

    def __init__(self, pid_file: Path) -> None:
        super().__init__(daemon=True)
        self.pid_file = pid_file
        self.halt = threading.Event()
        self.pid: int | None = None
        self.last_alive: float | None = None

    def run(self) -> None:
        while self.pid is None and not self.halt.is_set():
            try:
                self.pid = int(self.pid_file.read_text())
            except (OSError, ValueError):
                self.halt.wait(0.01)
        while self.pid is not None and not self.halt.is_set():
            try:
                os.kill(self.pid, 0)
            except ProcessLookupError:
                pass
            else:
                self.last_alive = time.monotonic()
            self.halt.wait(0.01)


@pytest.mark.parametrize(
    ("mode", "ceiling_s", "verdict"),
    [
        ("exit", _LU_GATE_CEILING_S, "exited"),
        ("orphan", 0.5, "ceiling"),
        ("hang", 0.5, "ceiling"),
    ],
)
def test_pdf164_gate_names_an_engine_that_exits_or_hangs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, ceiling_s: float, verdict: str
) -> None:
    root, user = _dirs(tmp_path)
    observation = _configure_gate(monkeypatch, root=root, user_tmp=user, ceiling_s=ceiling_s)
    monkeypatch.setattr(subprocess_util.subprocess, "Popen", _LuGate)
    sampler = _LiveSampler(root / "grandchild.pid")
    sampler.start()
    try:
        with _watchdog():
            subprocess_util.run(
                _standin(mode, str(root)),
                timeout=1.0,
                env={**os.environ, "TMPDIR": str(root)},
            )
        returned = time.monotonic()
    finally:
        sampler.halt.set()
        sampler.join(timeout=5)
        if sampler.pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(sampler.pid, signal.SIGKILL)
    assert [row[0] for row in observation] == [verdict], observation
    wait_s = observation[0][2]
    assert wait_s < 5.0, observation
    if verdict == "ceiling":
        assert wait_s >= 0.5, observation
    if mode == "orphan":
        # The leader was gone while the group lived: alive at the verdict, which is
        # at or before `returned - 1.0` (the real communicate then ran 1.0 s).
        assert sampler.last_alive is not None, "the grandchild was never seen alive"
        assert sampler.last_alive >= returned - 1.0, (sampler.last_alive, returned)


def test_pdf164_ac2_oracle_holds_across_an_lu_gap_longer_than_the_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, user = _dirs(tmp_path)
    observation = _configure_gate(
        monkeypatch, root=root, user_tmp=user, ceiling_s=_LU_GATE_CEILING_S
    )
    monkeypatch.setattr(subprocess_util.subprocess, "Popen", _LuGate)
    with _watchdog(60.0):
        result = subprocess_util.run(
            _standin("gap", "1.5"),
            timeout=INPROC_TIMEOUT_S,
            env={**os.environ, "TMPDIR": str(root)},
        )
    entries = sorted(os.listdir(root))
    assert _lu_names(root), f"no lu*.tmp inside the scratch root; it held {entries}"
    assert result.timed_out is True
    assert [row[0] for row in observation] == ["inside"], observation
    assert observation[0][1] == ["lu1.tmp", "lu2.tmp"], observation
    assert observation[0][2] < 5.0, observation
