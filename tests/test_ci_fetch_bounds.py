"""PDF-147 -- the two CI network fetches are bounded, retried and derived.

Two CI install steps used to fetch over the network with no bound and no retry:
`engines-present` / `Install engines` (a slow mirror spent the job's whole
30-minute budget before the suite started, ledger `ae19c17972`) and
`secret-scan` / `Install pinned gitleaks` (one release-asset 504 redded `main`
with no scan run, ledger `27960d012b`).

**What this module pins.**

* S1/S2 recompute every timeout/retry figure from the one `PDF-147 basis (...)`
  comment line each step carries and from the job's own `timeout-minutes`, and
  red when a step `env:` value drifts from the rule (X-476: the rule comes
  before the number; a figure retyped to go green is a finding, not a fix).
* S3 pins that no job budget moved and no extra bound was added.
* S4-S6 pin that the figures are wired by reference, that neither step can pass
  without fetching, and that one edit in `ci.yml` covers every gate.
* B1-B4 and G1-G4 EXECUTE the two steps' own `run:` text (stubbed `apt-get`,
  real GNU `timeout`; real `curl` against a local server) with the time figures
  overridden to small values. The mechanism is proved here; the real figures are
  proved by S1/S2. G5 pins that the G fixture tarball is byte-reproducible (PDF-160).

Paths are re-derived locally from `REPO_ROOT`; nothing is imported from
`test_gate_budget` or `test_gate_parity` (the PDF-45 independence convention).
Every locator asserts that it matched exactly once before any assertion runs.
"""

from __future__ import annotations

import gzip
import hashlib
import http.server
import io
import math
import os
import re
import signal
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
WORKFLOWS: Final[Path] = REPO_ROOT / ".github" / "workflows"
CI_WORKFLOW: Final[Path] = WORKFLOWS / "ci.yml"

ENGINES_JOB: Final[str] = "engines-present"
ENGINES_STEP: Final[str] = "Install engines"
GITLEAKS_JOB: Final[str] = "secret-scan"
GITLEAKS_STEP: Final[str] = "Install pinned gitleaks"

ENGINES_PACKAGES: Final[tuple[str, ...]] = (
    "tesseract-ocr",
    "tesseract-ocr-eng",
    "libreoffice-writer",
)
TIMEOUT_SITE_COUNT: Final[int] = (
    13  # the base value (GR-006): every `timeout-minutes:` line in ci.yml
)

_BASIS_RE: Final[re.Pattern[str]] = re.compile(r"PDF-147 basis \((?P<job>[a-z-]+)\): (?P<kv>.+)")
_TIMEOUT_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*timeout-minutes:\s*\d+\s*$", re.MULTILINE
)

LINUX_ONLY: Final[pytest.MarkDecorator] = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="the CI fetch steps run on ubuntu-latest only; GNU timeout(1) is Linux coreutils",
)


# --------------------------------------------------------------------------
# Locators -- every one asserts it matched, never returns vacuously.
# --------------------------------------------------------------------------


def _ci_text() -> str:
    assert CI_WORKFLOW.is_file(), (
        f"{CI_WORKFLOW} does not exist -- the locator, not the criterion, failed"
    )
    return CI_WORKFLOW.read_text(encoding="utf-8")


def _ci_doc() -> dict[str, Any]:
    doc = yaml.safe_load(_ci_text())
    assert isinstance(doc, dict), f"ci.yml parsed to {type(doc).__name__}, not a mapping"
    assert isinstance(doc.get("jobs"), dict) and doc["jobs"], "ci.yml parsed with no jobs"
    return doc


def _job(job: str) -> dict[str, Any]:
    jobs = _ci_doc()["jobs"]
    assert job in jobs, f"ci.yml has no job {job!r}"
    found = jobs[job]
    assert isinstance(found, dict)
    return found


def _step(job: str, name: str) -> dict[str, Any]:
    matches = [s for s in _job(job)["steps"] if isinstance(s, dict) and s.get("name") == name]
    assert len(matches) == 1, (
        f"step {name!r} in job {job!r} matched {len(matches)} times, expected exactly 1"
    )
    return matches[0]


def _script(job: str, name: str) -> str:
    run = _step(job, name).get("run")
    assert isinstance(run, str) and run.strip(), f"step {name!r} has no run: text"
    return run


def _step_env(job: str, name: str) -> dict[str, str]:
    env = _step(job, name).get("env")
    assert isinstance(env, dict) and env, f"step {name!r} has no env: block"
    return {str(k): str(v) for k, v in env.items()}


def _basis(job: str) -> dict[str, float]:
    """The single `PDF-147 basis (<job>): k=v ...` comment line, parsed."""
    found = [
        m
        for m in (_BASIS_RE.search(line) for line in _ci_text().splitlines())
        if m and m["job"] == job
    ]
    assert len(found) == 1, (
        f"expected exactly one 'PDF-147 basis ({job}):' line in ci.yml, found {len(found)}"
    )
    pairs: dict[str, float] = {}
    for token in found[0]["kv"].split():
        key, sep, value = token.partition("=")
        assert sep == "=", f"basis token {token!r} is not key=value"
        pairs[key] = float(value)
    return pairs


def _job_seconds(job: str) -> int:
    minutes = _job(job).get("timeout-minutes")
    assert isinstance(minutes, int) and not isinstance(minutes, bool), (
        f"{job}: timeout-minutes is not an integer"
    )
    return minutes * 60


def _require(basis: dict[str, float], *keys: str) -> None:
    missing = [k for k in keys if k not in basis]
    assert not missing, f"basis line is missing keys {missing}"


# --------------------------------------------------------------------------
# The rule (D0) -- R-A, R-B, R-C.
# --------------------------------------------------------------------------


def _ceil10(value: float) -> int:
    """R-A rounding: the next multiple of 10 s, the resolution."""
    return int(math.ceil(round(value, 9) / 10.0)) * 10


def _attempt_s(p95: float) -> int:
    """R-A: PDF-29's recorded multiplier (3x p95), rounded up to 10 s."""
    return _ceil10(3 * p95)


def _budget_s(job_s: int, *maxima: float) -> int:
    """R-B: the job's own budget less the largest observed time of everything else in it."""
    return int(math.floor(round(job_s - sum(maxima), 9)))


def _apt_attempts(budget: int, update_s: int, download_s: int) -> int:
    """R-C (apt): no sleep between attempts, so whole attempts that fit."""
    return budget // (update_s + download_s)


def _curl_retries(attempt_s: int, budget: int) -> int:
    """R-C (curl): max R: (R + 1) * attempt + (2**R - 1) <= budget (curl backoff 1, 2, 4 s)."""
    best = -1
    for retries in range(0, 64):
        if (retries + 1) * attempt_s + (2**retries - 1) <= budget:
            best = retries
        else:
            break
    return best


def _engines_rule() -> tuple[int, int, int, int]:
    basis = _basis(ENGINES_JOB)
    _require(basis, "update_p95_s", "download_p95_s", "install_max_s", "pre_max_s", "post_max_s")
    update_s = _attempt_s(basis["update_p95_s"])
    download_s = _attempt_s(basis["download_p95_s"])
    budget = _budget_s(
        _job_seconds(ENGINES_JOB), basis["pre_max_s"], basis["install_max_s"], basis["post_max_s"]
    )
    return update_s, download_s, _apt_attempts(budget, update_s, download_s), budget


def _gitleaks_rule() -> tuple[int, int, int]:
    basis = _basis(GITLEAKS_JOB)
    _require(basis, "fetch_p95_s", "after_fetch_max_s", "pre_max_s", "post_max_s")
    attempt = _attempt_s(basis["fetch_p95_s"])
    budget = _budget_s(
        _job_seconds(GITLEAKS_JOB),
        basis["pre_max_s"],
        basis["after_fetch_max_s"],
        basis["post_max_s"],
    )
    return attempt, _curl_retries(attempt, budget), budget


# --------------------------------------------------------------------------
# Structure arms S1-S6 (every platform).
# --------------------------------------------------------------------------


def test_engines_fetch_figures_are_the_rule_over_the_recorded_basis() -> None:
    """S1 (AC1): the three apt env figures are R-A/R-B/R-C over the basis line."""
    env = _step_env(ENGINES_JOB, ENGINES_STEP)
    update_s, download_s, attempts, budget = _engines_rule()
    got = (
        int(env["ENGINES_UPDATE_ATTEMPT_S"]),
        int(env["ENGINES_DOWNLOAD_ATTEMPT_S"]),
        int(env["ENGINES_FETCH_ATTEMPTS"]),
    )
    want = (update_s, download_s, attempts)
    assert got == want, (
        f"PDF-147 S1: step env has {got} but the rule over the basis line "
        f"gives {want} (budget {budget} s)"
    )
    assert attempts >= 2, (
        f"PDF-147 STOP S1: the rule yields {attempts} attempt(s) inside budget "
        f"{budget} s; no retry fits"
    )
    assert got[2] * (got[0] + got[1]) <= budget, (
        f"PDF-147 S1: worst case {got[2] * (got[0] + got[1])} s exceeds the budget "
        f"{budget} s (got {got}, rule {want})"
    )


def test_gitleaks_fetch_figures_are_the_rule_over_the_recorded_basis() -> None:
    """S2 (AC2): the three curl env figures are the rule over the basis line; retries is the MAX."""
    env = _step_env(GITLEAKS_JOB, GITLEAKS_STEP)
    attempt, retries, budget = _gitleaks_rule()
    got = (
        int(env["GITLEAKS_FETCH_ATTEMPT_S"]),
        int(env["GITLEAKS_FETCH_RETRIES"]),
        int(env["GITLEAKS_FETCH_BUDGET_S"]),
    )
    want = (attempt, retries, budget)
    assert got == want, (
        f"PDF-147 S2: step env has {got} but the rule over the basis line gives {want}"
    )
    assert retries >= 1, (
        f"PDF-147 STOP S1: the rule yields {retries} retries inside budget {budget} s"
    )
    over = (retries + 2) * attempt + (2 ** (retries + 1) - 1)
    assert over > budget, (
        f"PDF-147 S2: {retries + 1} retries would still fit ({over} <= {budget}); "
        "retries is not the maximum"
    )


def test_the_fetch_bounds_never_widen_a_job_budget() -> None:
    """S3 (AC3): job budgets stay 30/5, no step-level bound is added, the census stays 13."""
    assert _job(ENGINES_JOB)["timeout-minutes"] == 30
    assert _job(GITLEAKS_JOB)["timeout-minutes"] == 5
    for job, name in ((ENGINES_JOB, ENGINES_STEP), (GITLEAKS_JOB, GITLEAKS_STEP)):
        assert "timeout-minutes" not in _step(job, name), (
            f"{job}/{name}: a step-level timeout-minutes was added"
        )
    sites = _TIMEOUT_LINE_RE.findall(_ci_text())
    assert len(sites) == TIMEOUT_SITE_COUNT, (
        f"expected {TIMEOUT_SITE_COUNT} timeout-minutes sites in ci.yml, found {len(sites)}"
    )


def test_every_fetch_figure_is_read_by_reference_from_its_step_env() -> None:
    """S4 (AC6): each bound is a quoted ${...} reference to a declared env key, never a literal."""
    engines = _script(ENGINES_JOB, ENGINES_STEP)
    operands = re.findall(r"timeout\s+-s\s+KILL\s+(\S+)", engines)
    assert len(operands) == 2, (
        f"expected 2 'timeout -s KILL' operands in the engines script, found {operands}"
    )
    for operand in operands:
        assert re.fullmatch(r'"\$\{ENGINES_[A-Z_]+\}"', operand), (
            f"timeout operand {operand!r} is not a ${{ENGINES_...}} reference"
        )
    assert '"${ENGINES_FETCH_ATTEMPTS}"' in engines, (
        "the loop bound is not ${ENGINES_FETCH_ATTEMPTS}"
    )
    assert "ENGINES_UPDATE_ATTEMPT_S" in operands[0] and "ENGINES_DOWNLOAD_ATTEMPT_S" in operands[1]

    gitleaks = _script(GITLEAKS_JOB, GITLEAKS_STEP)
    curl_lines = [line for line in gitleaks.splitlines() if "curl -fsSL" in line]
    assert len(curl_lines) == 1, f"expected exactly one 'curl -fsSL' line, found {len(curl_lines)}"
    expected = {
        "--retry": "GITLEAKS_FETCH_RETRIES",
        "--max-time": "GITLEAKS_FETCH_ATTEMPT_S",
        "--retry-max-time": "GITLEAKS_FETCH_BUDGET_S",
    }
    for flag, key in expected.items():
        operand = re.findall(rf"(?<![\w-]){re.escape(flag)}\s+(\S+)", curl_lines[0])
        assert operand == [f'"${{{key}}}"'], (
            f"curl flag {flag} takes {operand}, expected one reference to ${{{key}}}"
        )

    for job, name, script, prefix in (
        (ENGINES_JOB, ENGINES_STEP, engines, "ENGINES_"),
        (GITLEAKS_JOB, GITLEAKS_STEP, gitleaks, "GITLEAKS_FETCH_"),
    ):
        env_keys = {k for k in _step_env(job, name) if k.startswith(prefix)}
        used = set(re.findall(rf"\$\{{({re.escape(prefix)}[A-Z_]+)\}}", script))
        assert used == env_keys, (
            f"{job}/{name}: script references {sorted(used)} but env declares {sorted(env_keys)}"
        )


def test_neither_fetch_step_can_pass_without_fetching() -> None:
    """S5 (AC5/AC8): no continue-on-error, no or-true, errexit first, the dpkg half offline."""
    for job, name in ((ENGINES_JOB, ENGINES_STEP), (GITLEAKS_JOB, GITLEAKS_STEP)):
        assert "continue-on-error" not in _step(job, name), (
            f"{job}/{name} carries continue-on-error"
        )
        assert "continue-on-error" not in _job(job), f"job {job} carries continue-on-error"
        script = _script(job, name)
        assert not re.search(r"\|\|\s*true", script), (
            f"{job}/{name}: an or-true idiom swallows a failure"
        )
        assert script.lstrip().startswith("set -euo pipefail"), (
            f"{job}/{name}: line 1 is not 'set -euo pipefail'"
        )
    last = [line for line in _script(ENGINES_JOB, ENGINES_STEP).splitlines() if line.strip()][-1]
    assert "apt-get install" in last and "--no-download" in last, (
        f"the final engines install is not offline: {last!r}"
    )


def test_every_gate_reaches_these_steps_through_ci_yml() -> None:
    """S6 (AC9): release and deploy-website reuse ci.yml; no other workflow fetches either."""
    for name in ("release.yml", "deploy-website.yml"):
        doc = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
        gate = doc["jobs"].get("gate")
        assert isinstance(gate, dict), f"{name} has no gate job"
        assert gate.get("uses") == "./.github/workflows/ci.yml", (
            f"{name}: gate does not reuse ci.yml"
        )

    def live_lines(path: Path) -> list[str]:
        return [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        ]

    ci_lines = live_lines(CI_WORKFLOW)
    assert any("apt-get" in line for line in ci_lines), "the probe cannot see apt-get in ci.yml"
    assert any("gitleaks/releases/download" in line for line in ci_lines), (
        "the probe cannot see the gitleaks asset URL in ci.yml"
    )
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path == CI_WORKFLOW:
            continue
        for line in live_lines(path):
            assert "apt-get" not in line, (
                f"{path.name} fetches apt packages outside ci.yml: {line.strip()!r}"
            )
            assert "gitleaks/releases/download" not in line, (
                f"{path.name} fetches the gitleaks asset outside ci.yml: {line.strip()!r}"
            )


# --------------------------------------------------------------------------
# Execution harness (behaviour arms).
# --------------------------------------------------------------------------


class _Result:
    def __init__(self, rc: int, output: str, elapsed: float) -> None:
        self.rc = rc
        self.output = output
        self.elapsed = elapsed


def _session_members(sid: int) -> list[int]:
    """Pids whose session id is `sid` (Linux /proc). Used to reap only our own harness session."""
    pids: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        fields = stat.rsplit(")", 1)[1].split()
        if len(fields) > 3 and int(fields[3]) == sid:
            pids.append(int(entry.name))
    return pids


def _run_step(
    script: str, tmp_path: Path, env: dict[str, str], stubs: Path, limit: float
) -> _Result:
    """Run `bash -e step.sh` in its own session, `stubs` first on PATH; reap only that session."""
    step_sh = tmp_path / "step.sh"
    step_sh.write_text(script, encoding="utf-8")
    full_env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
    full_env.update(env)
    full_env["PATH"] = f"{stubs}{os.pathsep}{full_env.get('PATH', '')}"
    full_env["no_proxy"] = full_env["NO_PROXY"] = "127.0.0.1,localhost"
    started = time.monotonic()
    proc = subprocess.Popen(
        ["bash", "-e", str(step_sh)],
        env=full_env,
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        for pid in _session_members(proc.pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        out, _ = proc.communicate()
        pytest.fail(
            f"the step did not finish within {limit} s (harness timeout); output so far:\n{out}"
        )
    return _Result(proc.returncode, out, time.monotonic() - started)


def _write_stub(stubs: Path, name: str, body: str) -> None:
    stubs.mkdir(parents=True, exist_ok=True)
    path = stubs / name
    path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


# ---- B arms: the engines step ------------------------------------------------

_APT_STUB: Final[str] = r"""
echo "$*" >> "$STUB_LOG"
case " $* " in
  *" update "*) kind=update; pattern='^update' ;;
  *" --download-only "*) kind=download; pattern='--download-only' ;;
  *" --no-download "*) kind=install; pattern='--no-download' ;;
  *) kind=other; pattern='^$' ;;
esac
n=$(grep -c -e "$pattern" "$STUB_LOG" || true)
case "$kind" in
  update) stall="${STUB_STALL_UPDATE:-}" ;;
  download) stall="${STUB_STALL_DOWNLOAD:-}" ;;
  *) stall="" ;;
esac
if [ "$stall" = "all" ] || { [ -n "$stall" ] && [[ ",$stall," == *",$n,"* ]]; }; then
  exec sleep 20
fi
exit 0
"""


def _engines_run(
    tmp_path: Path, *, stall_update: str = "", stall_download: str = ""
) -> tuple[_Result, list[str], dict[str, str]]:
    stubs = tmp_path / "stubs"
    _write_stub(stubs, "sudo", 'exec "$@"\n')
    _write_stub(stubs, "apt-get", _APT_STUB)
    log = tmp_path / "apt.log"
    log.write_text("", encoding="utf-8")
    env = _step_env(ENGINES_JOB, ENGINES_STEP)
    env.update(
        ENGINES_UPDATE_ATTEMPT_S="1",
        ENGINES_DOWNLOAD_ATTEMPT_S="1",
        STUB_LOG=str(log),
        STUB_STALL_UPDATE=stall_update,
        STUB_STALL_DOWNLOAD=stall_download,
    )
    result = _run_step(_script(ENGINES_JOB, ENGINES_STEP), tmp_path, env, stubs, limit=40)
    return result, log.read_text(encoding="utf-8").splitlines(), env


def _count(lines: list[str], needle: str) -> int:
    return sum(1 for line in lines if needle in line)


@LINUX_ONLY
def test_engines_step_healthy_path_fetches_once_and_installs_offline(tmp_path: Path) -> None:
    """B1 (AC5): one update, one download-only, one --no-download; exact argv; no annotation."""
    result, lines, _ = _engines_run(tmp_path)
    assert result.rc == 0, result.output
    updates = [line for line in lines if line.startswith("update")]
    assert (len(updates), _count(lines, "--download-only"), _count(lines, "--no-download")) == (
        1,
        1,
        1,
    ), lines
    final = [line for line in lines if "--no-download" in line][-1].split()
    assert tuple(final[-len(ENGINES_PACKAGES) :]) == ENGINES_PACKAGES, (
        f"final install argv: {final}"
    )
    assert "::warning" not in result.output and "::error" not in result.output, result.output


@LINUX_ONLY
def test_engines_step_recovers_from_one_stalled_download_with_a_warning(tmp_path: Path) -> None:
    """B2 (AC4): the first download stalls; the bound kills it; one warning; a second attempt."""
    result, lines, env = _engines_run(tmp_path, stall_download="1")
    attempts = env["ENGINES_FETCH_ATTEMPTS"]
    assert result.rc == 0, result.output
    assert _count(lines, "--download-only") == 2, lines
    assert _count(lines, "--no-download") == 1, lines
    warnings = [
        line
        for line in result.output.splitlines()
        if line.startswith("::warning title=Install engines::")
    ]
    assert len(warnings) == 1 and f"apt fetch attempt 1/{attempts}" in warnings[0], result.output


@LINUX_ONLY
def test_engines_step_reds_after_its_last_attempt_and_never_runs_dpkg(tmp_path: Path) -> None:
    """B3 (AC4/AC5/AC8): every download stalls; N attempts, a ::error, rc != 0, zero dpkg half."""
    result, lines, env = _engines_run(tmp_path, stall_download="all")
    n = int(env["ENGINES_FETCH_ATTEMPTS"])
    assert result.rc != 0, result.output
    assert result.elapsed <= n * (1 + 1) + 3, f"took {result.elapsed:.1f} s, bound {n * 2 + 3} s"
    assert any(
        line.startswith("::error title=Install engines::") for line in result.output.splitlines()
    ), result.output
    assert _count(lines, "--download-only") == n, lines
    assert _count(lines, "--no-download") == 0, lines


@LINUX_ONLY
def test_engines_step_reds_on_a_stalled_update_without_downloading(tmp_path: Path) -> None:
    """B4 (AC4): every update stalls; rc != 0 and no install of any kind is invoked."""
    result, lines, _ = _engines_run(tmp_path, stall_update="all")
    assert result.rc != 0, result.output
    assert _count(lines, "install") == 0, lines
    assert any(
        line.startswith("::error title=Install engines::") for line in result.output.splitlines()
    ), result.output


# ---- G arms: the gitleaks step -------------------------------------------------

_PINNED_BODY: Final[bytes] = b"#!/bin/sh\necho 8.30.1\n"
_IMPOSTOR_BODY: Final[bytes] = b"#!/bin/sh\necho 0.0.0-not-the-pin\n"
_RETRIES: Final[int] = 2


def _tarball(body: bytes) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        info = tarfile.TarInfo("gitleaks")
        info.size = len(body)
        info.mode = 0o755
        tar.addfile(info, io.BytesIO(body))
    return gzip.compress(raw.getvalue(), mtime=0)


class _Server:
    """A ThreadingHTTPServer on 127.0.0.1 that answers each request from a script of actions."""

    def __init__(self, actions: list[tuple[str, bytes]]) -> None:
        self.actions = actions
        self.count = 0
        self._lock = threading.Lock()
        self.stop = threading.Event()
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 -- http.server's required name
                with outer._lock:
                    index = outer.count
                    outer.count += 1
                kind, payload = outer.actions[min(index, len(outer.actions) - 1)]
                if kind == "stall":
                    outer.stop.wait(30)
                    return
                if kind == "504":
                    self.send_response(504)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self) -> _Server:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def _gitleaks_script(tmp_path: Path, base: str) -> str:
    """The step's run: text with the four exact needles pointed at tmp_path and the local server."""
    script = _script(GITLEAKS_JOB, GITLEAKS_STEP)
    url = "https://github.com/gitleaks/gitleaks/releases/download"
    tarball = "/tmp/gitleaks.tar.gz"
    assert script.count(url) == 1, f"the release URL occurs {script.count(url)} times, expected 1"
    lines = script.splitlines()
    for needle_line in (
        [x for x in lines if "curl -fsSL" in x],
        [x for x in lines if "tar -xzf" in x],
    ):
        assert len(needle_line) == 1 and needle_line[0].count(tarball) == 1, (
            f"tarball path not exactly once on {needle_line}"
        )
    assert all(line.count(tarball) <= 1 for line in lines), (
        "a line names the tarball path more than once"
    )
    tmp = str(tmp_path)
    script = script.replace(url, base)
    script = script.replace(tarball, f"{tmp}/gitleaks.tar.gz")
    script = script.replace("-C /tmp gitleaks", f"-C {tmp} gitleaks")
    script = script.replace("/tmp/gitleaks /usr/local/bin", f"{tmp}/gitleaks /usr/local/bin")
    assert "/tmp" not in script.replace(tmp, ""), (
        "a /tmp path survived substitution; the arm could write outside tmp_path"
    )
    return script


def _gitleaks_run(
    tmp_path: Path, actions: list[tuple[str, bytes]], limit: float = 40
) -> tuple[_Result, int, str]:
    pinned = _tarball(_PINNED_BODY)
    stubs = tmp_path / "stubs"
    sudo_log = tmp_path / "sudo.log"
    sudo_log.write_text("", encoding="utf-8")
    _write_stub(stubs, "sudo", 'echo "$*" >> "$STUB_SUDO_LOG"\n')
    _write_stub(stubs, "gitleaks", "echo 8.30.1\n")
    env = _step_env(GITLEAKS_JOB, GITLEAKS_STEP)
    env.update(
        GITLEAKS_FETCH_ATTEMPT_S="1",
        GITLEAKS_FETCH_RETRIES=str(_RETRIES),
        GITLEAKS_FETCH_BUDGET_S="20",
        GITLEAKS_VERSION="8.30.1",
        GITLEAKS_SHA256=hashlib.sha256(pinned).hexdigest(),
        STUB_SUDO_LOG=str(sudo_log),
    )
    with _Server(actions) as server:
        result = _run_step(_gitleaks_script(tmp_path, server.base), tmp_path, env, stubs, limit)
        count = server.count
    return result, count, sudo_log.read_text(encoding="utf-8")


@LINUX_ONLY
def test_gitleaks_step_recovers_from_504s_up_to_its_retry_count(tmp_path: Path) -> None:
    """G1 (AC6): R 504s then the pinned bytes: rc 0, R + 1 requests, the install reached."""
    pinned = _tarball(_PINNED_BODY)
    result, count, sudo_log = _gitleaks_run(
        tmp_path, [("504", b"")] * _RETRIES + [("body", pinned)]
    )
    assert result.rc == 0, result.output
    assert count == _RETRIES + 1, f"server saw {count} requests"
    assert "install -m 0755" in sudo_log, sudo_log


@LINUX_ONLY
def test_gitleaks_step_reds_after_its_retries_without_verifying_or_installing(
    tmp_path: Path,
) -> None:
    """G2 (AC6/AC8): R + 1 504s: rc 22 after exactly R + 1 requests and nothing installed."""
    result, count, sudo_log = _gitleaks_run(tmp_path, [("504", b"")])
    assert result.rc == 22, result.output
    assert count == _RETRIES + 1, f"server saw {count} requests"
    assert sudo_log == "", sudo_log


@LINUX_ONLY
def test_gitleaks_step_bounds_a_stalled_fetch_and_retries_it(tmp_path: Path) -> None:
    """G3 (AC6): every request held past --max-time: rc 28, R + 1 requests, inside the formula."""
    result, count, sudo_log = _gitleaks_run(tmp_path, [("stall", b"")])
    assert result.rc == 28, result.output
    assert count == _RETRIES + 1, f"server saw {count} requests"
    assert result.elapsed <= (_RETRIES + 1) * 1 + (2**_RETRIES - 1) + 2, (
        f"took {result.elapsed:.1f} s"
    )
    assert sudo_log == "", sudo_log


@LINUX_ONLY
def test_gitleaks_step_refuses_bytes_that_miss_the_pinned_sha(tmp_path: Path) -> None:
    """G4 (AC7): a valid tarball, a gitleaks member, wrong sha256: refused before any install."""
    pinned, impostor = _tarball(_PINNED_BODY), _tarball(_IMPOSTOR_BODY)
    assert hashlib.sha256(impostor).hexdigest() != hashlib.sha256(pinned).hexdigest(), (
        "the impostor fixture is the pinned one"
    )
    result, count, sudo_log = _gitleaks_run(tmp_path, [("body", impostor)])
    assert result.rc != 0, f"the step accepted bytes that miss the pin:\n{result.output}"
    assert "FAILED" in result.output, result.output
    assert count == 1, f"server saw {count} requests"
    assert "install -m 0755" not in sudo_log, sudo_log


def test_tarball_bytes_do_not_depend_on_the_wall_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """G5 (PDF-160, B-545): G1 serves one _tarball() and hashes another; a tick must not matter."""
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    first = _tarball(_PINNED_BODY)
    monkeypatch.setattr(time, "time", lambda: 2000.0)
    second = _tarball(_PINNED_BODY)
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest(), (
        "_tarball embeds the wall clock (gzip MTIME): the sha256 differs across a second boundary"
    )
