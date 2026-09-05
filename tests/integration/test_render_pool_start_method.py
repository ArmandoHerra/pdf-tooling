"""The render pool's start method is a PRODUCT DECISION, and it is proved
against the kernel rather than against a string (PDF-35, ruling X-401).

**Why this file exists at all, and why it is not `test_rasterize_signals.py`.**
That file is *start-method agnostic by construction* -- its own module docstring
says so -- and that is the right shape for it: it observes files, exit status and
process-group membership, which every start method produces identically. This
file is the opposite by design. Here the start method IS the variable, it is set
explicitly, and the arm that must fail is exercised rather than described.

**The defect this file's red arm reproduces.** ``PR_SET_PDEATHSIG`` asks the
kernel to SIGKILL *this process when its parent dies*. Under ``fork`` and
``spawn`` a render worker's parent is the CLI, so a SIGKILLed CLI takes its
workers with it. Under ``forkserver`` the worker is forked from the forkserver
HELPER, which outlives the CLI -- so the guard is armed against the wrong
process and never fires. Measured here, pre-pin, at the mechanism level with the
start method as the only variable: `fork` 0 survivors / 0 growth, `spawn` 0 / 0,
**`forkserver` 8 survivors and output 21 -> 240 files after the parent was
reaped.** The job ran to completion with nothing left alive to have asked for it.

**Why the red arm cannot be observed by simply running the suite.** On this
project's own venv (CPython 3.12.13) the ambient default is ``fork``, so the
existing SIGKILL arm is green locally and proves nothing about this defect; the
default only becomes ``forkserver`` on CPython 3.14, which is a supported,
CI-exercised interpreter (``requires-python = ">=3.11"``). An engineer who runs
the suite on a 3.11-3.13 host and sees green has observed nothing. Every arm here
therefore forces the start method explicitly -- in-process for the matrix, and
through a real CLI subprocess for the end-to-end arms.

**No allowlist, ever.** Survivors are enumerated from ``/proc`` by pid and
NOTHING is excluded. An earlier version of the sibling helper excluded processes
whose command line named ``multiprocessing.forkserver``, on the theory that those
are infrastructure rather than render workers -- and that made the control unable
to fail, because a forkserver-forked worker inherits the helper's command line
verbatim. The exclusion excluded the very processes the arm exists to catch. It
was fully reverted and must not return; the survivor cmdlines printed by this
file's own failure messages are exactly the ones such a list would have hidden.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from pdf_toolkit.ops import procpool

# NOTE: `pyproject.toml`'s `markers` list is closed and `--strict-markers` is in
# `addopts`, so this file deliberately registers no marker of its own -- an
# invented one would be rejected at collection time rather than at review.

# --------------------------------------------------------------------------- #
# Workload shape.
#
# A render-shaped chunked job: N pages dealt round-robin across W workers, each
# page a real CPU burn followed by a real fsync'd file write. It is deliberately
# NOT a pdfium render -- the mechanism under test is the kernel's parent-death
# signal, not the renderer, and depending on pypdfium2 here would make a
# start-method arm fail for renderer reasons. The observable is the same one
# `rasterize` produces: files landing on disk, one per page.
#
# The numbers are the ones the pre-fix RED was actually measured with, not
# rounded afterwards. Changing them is legitimate ONLY if the non-vacuity
# assertion below still holds with room to spare; shrinking the workload until
# the job finishes before the signal lands is how "no growth after death"
# becomes vacuously true, which is why that assertion is an assertion and not a
# preamble.
# --------------------------------------------------------------------------- #
_WORKERS = 6
_PAGES = 240
_SIGNAL_AT = 12
_BURN_ITERATIONS = 240_000

#: Wait for the job to make substantial, demonstrable progress. Generous: a
#: `spawn`-started worker pays a full cold import before its first page, and this
#: waits for a dozen pages, not one.
_PROGRESS_TIMEOUT_S = 60.0
#: The driver has no signal handler at all -- SIGKILL is uncatchable -- so this
#: is a bound on `wait()` returning, not on a teardown routine.
_PARENT_EXIT_TIMEOUT_S = 25.0
#: Margin against filesystem/scheduler noise once the survivors are gone.
_SETTLE_S = 1.0
#: How long the enumerated-survivor check polls. The kernel delivers
#: PR_SET_PDEATHSIG's SIGKILL asynchronously and the subreaper reaps
#: asynchronously too, so a single sample is a race, not a control.
_SURVIVOR_TIMEOUT_S = 10.0

_LINUX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason=(
        "the SIGKILL-to-parent orphan guard is PR_SET_PDEATHSIG, and prctl is a "
        "Linux syscall (ops/procpool.py::_set_pdeathsig_sigkill). There is no macOS "
        "equivalent, so on macos-14 these arms are a VISIBLE SKIP rather than a "
        "silent absence -- a control that cannot be run must be visible as skipped, "
        "never quietly counted as agreement (X-153)."
    ),
)

#: The matrix driver, written to disk per test rather than passed as `-c`, so the
#: traceback of a failing arm names a real file and a real line.
_DRIVER = """\
import os, sys
from concurrent.futures import ProcessPoolExecutor
import multiprocessing

from pdf_toolkit.ops.procpool import _worker_initializer


def _chunk(args):
    out_dir, pages, burn = args
    for page in pages:
        acc = 0
        for i in range(burn):
            acc += i * i
        path = os.path.join(out_dir, "page-%04d.out" % page)
        with open(path, "wb") as fh:
            fh.write(b"x" * 512)
            fh.flush()
            os.fsync(fh.fileno())
    return len(pages)


def main():
    method, out_dir, workers, pages, burn = (
        sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
    )
    os.makedirs(out_dir, exist_ok=True)
    ctx = multiprocessing.get_context(method)
    all_pages = list(range(1, pages + 1))
    chunks = [all_pages[i::workers] for i in range(workers)]
    executor = ProcessPoolExecutor(
        max_workers=workers, mp_context=ctx, initializer=_worker_initializer
    )
    futures = [executor.submit(_chunk, (out_dir, c, burn)) for c in chunks]
    for future in futures:
        future.result()
    executor.shutdown(wait=True)


if __name__ == "__main__":
    main()
"""


def live_group_members(pgid: int) -> tuple[tuple[int, str], ...]:
    """Every NON-ZOMBIE live pid whose process group is *pgid*, read from /proc.

    Enumeration, not a boolean: a control that reports true/false cannot say WHAT
    survived, and the cmdlines it returns are what make a failure diagnosable.
    Zombies are excluded because a zombie holds no memory and writes no output --
    under SIGKILL-to-parent an unreaped zombie is the normal, harmless transient
    while the kernel's kills land. A live worker is a survivor; a zombie is not.
    """
    procfs = Path("/proc")
    if not procfs.is_dir():  # pragma: no cover - macOS, where these arms skip
        return ()
    members: list[tuple[int, str]] = []
    for entry in procfs.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:  # pragma: no cover - the pid exited mid-scan
            continue
        try:
            # `comm` is parenthesised and may contain spaces/parens, so the
            # fields after it are found from the LAST ')'.
            fields = stat[stat.rindex(")") + 2 :].split()
            state, pgrp = fields[0], int(fields[2])
        except (ValueError, IndexError):  # pragma: no cover - malformed/raced
            continue
        if pgrp != pgid or state == "Z":
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:  # pragma: no cover - the pid exited mid-scan
            cmdline = ""
        members.append((int(entry.name), cmdline.strip()))
    return tuple(members)


def _wait_for_no_survivors(pgid: int, *, timeout: float) -> tuple[tuple[int, str], ...]:
    deadline = time.monotonic() + timeout
    survivors = live_group_members(pgid)
    while survivors and time.monotonic() < deadline:
        time.sleep(0.05)
        survivors = live_group_members(pgid)
    return survivors


def _reap(survivors: tuple[tuple[int, str], ...]) -> None:
    """Kill anything the arm found still alive.

    A test that PROVES orphans exist must not then leak them: this product's own
    `/tmp` exhaustion incident is the standing reminder that a test's residue is
    the next run's outage. Best-effort and never raises -- the assertion that
    follows is what reports the finding.
    """
    for pid, _cmd in survivors:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:  # pragma: no cover - already gone
            pass


def _purge(directory: str) -> None:
    """Remove *directory* and everything under it, deepest-first, best-effort.

    Written out rather than reached for via `shutil.rmtree` because these arms
    deliberately create orphaned processes, and a worker that is still writing
    when the purge runs would make a recursive delete raise mid-walk and mask the
    assertion that follows. **Temp hygiene is not incidental here:** this product
    has already taken its own host down once by exhausting `/tmp` inodes, and an
    arm whose whole purpose is proving that processes leak must not itself leak
    the directory they were writing into.
    """
    root = Path(directory)
    if not root.exists():  # pragma: no cover - already gone
        return
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        try:
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - raced against a surviving worker
            pass
    try:
        root.rmdir()
    except OSError:  # pragma: no cover - non-empty because a worker outlived us
        pass


def _short_tmpdir() -> str:
    """A SHORT `$TMPDIR` for the matrix driver, and it is load-bearing.

    Under `forkserver` CPython binds `<TMPDIR>/pymp-XXXXXXXX/listener-XXXXXXXX`,
    32 bytes past `$TMPDIR`, against a 107-character `sun_path` ceiling. With
    `-n auto` pytest's own `popen-gwN` temp paths can exceed 75 characters, and a
    `forkserver` arm inheriting one would die of `OSError: AF_UNIX path too long`
    BEFORE it could demonstrate the survivor defect -- an arm that errors for an
    unrelated reason is not a red, it is a broken control. The path-length class
    is measured deliberately and separately, by the D4 arm at the bottom of this
    file.
    """
    return tempfile.mkdtemp(prefix="pdf35-")


def _run_matrix_arm(
    method: str, tmp_path: Path
) -> tuple[int, int, int, tuple[tuple[int, str], ...]]:
    """Launch the driver under *method*, SIGKILL the PARENT PID ONLY, and return
    ``(returncode, count_at_death, count_after_settle, survivors)``.
    """
    driver = tmp_path / "driver.py"
    driver.write_text(_DRIVER)
    out_dir = tmp_path / method / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    short = _short_tmpdir()
    env["TMPDIR"] = short

    proc = subprocess.Popen(
        [
            sys.executable,
            str(driver),
            method,
            str(out_dir),
            str(_WORKERS),
            str(_PAGES),
            str(_BURN_ITERATIONS),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        # New session AND process-group leader in one syscall, so every worker
        # the driver starts inherits this pgid and /proc enumeration by pgid
        # catches all of them without any of them calling setpgid.
        start_new_session=True,
        env=env,
    )
    try:
        deadline = time.monotonic() + _PROGRESS_TIMEOUT_S
        count = 0
        while time.monotonic() < deadline:
            count = len(list(out_dir.iterdir())) if out_dir.is_dir() else 0
            if count >= _SIGNAL_AT:
                break
            if proc.poll() is not None:
                stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
                pytest.fail(
                    f"the {method} driver exited (rc={proc.returncode}) before writing "
                    f"{_SIGNAL_AT} pages -- this arm never reached the state it measures.\n"
                    f"stderr:\n{stderr[-2000:]}"
                )
            time.sleep(0.05)
        else:
            pytest.fail(
                f"only {count}/{_SIGNAL_AT} files appeared under {out_dir} within "
                f"{_PROGRESS_TIMEOUT_S}s under start method {method!r} -- the job "
                f"started too slowly (or not at all) for this arm to be decisive"
            )

        # THE PARENT PID ONLY -- never the group. Signalling the group would kill
        # the workers directly and manufacture a pass on every arm, including the
        # one that is supposed to be red.
        os.kill(proc.pid, signal.SIGKILL)
        try:
            proc.wait(timeout=_PARENT_EXIT_TIMEOUT_S)
        except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL is uncatchable
            proc.kill()
            proc.wait(timeout=5)

        count_at_death = len(list(out_dir.iterdir()))
        survivors = _wait_for_no_survivors(proc.pid, timeout=_SURVIVOR_TIMEOUT_S)
        time.sleep(_SETTLE_S)
        count_after_settle = len(list(out_dir.iterdir()))
    finally:
        if proc.poll() is None:  # pragma: no cover - defensive
            proc.kill()
            proc.wait(timeout=5)
        _purge(short)

    return proc.returncode, count_at_death, count_after_settle, survivors


# --------------------------------------------------------------------------- #
# AC1 / AC12 -- the declaration itself.
#
# These assert the product's OWN statement rather than reaching for
# `executor._mp_context`, a stdlib private with no public equivalent.
# `procpool.py` already accepts one such reach (`executor._processes`) BECAUSE
# there is no alternative; here there is one, and taking it keeps the
# private-surface count from growing.
#
# On their own these are claims about a string. The arms below are the claims
# about the kernel, and both are needed: the constant without the kernel arms
# would be a pin nobody proved, and the kernel arms without the constant would
# leave the decision undeclared and un-greppable.
# --------------------------------------------------------------------------- #


def test_ac1_the_pool_declares_spawn_as_a_product_decision() -> None:
    assert procpool._START_METHOD == "spawn", (
        f"the render pool's start method is declared as {procpool._START_METHOD!r}, "
        f"not 'spawn'. PDF-35 / ruling X-401 pins `spawn`: `forkserver` is the "
        f"defect and is excluded on every branch, and `fork` was deliberately NOT "
        f"chosen because pinning it is a commitment against CPython's direction of "
        f"travel that must be re-examined every release."
    )


def test_ac1_the_declared_method_is_what_the_context_actually_resolves() -> None:
    """The constant and the context cannot drift apart silently.

    `_START_METHOD` is a string; `get_context()` is what the executor is actually
    handed. Asserting only the first would let a typo'd or shadowed accessor ship
    a pool that reads 'spawn' in the source and starts something else.
    """
    context = procpool._mp_context()
    assert context.get_start_method() == "spawn", (
        f"`_mp_context()` resolved a context whose start method is "
        f"{context.get_start_method()!r}, not 'spawn' -- the declared constant and "
        f"the context handed to `ProcessPoolExecutor` have drifted apart."
    )


def test_ac12_the_pin_does_not_grow_the_public_surface() -> None:
    """A defect fix, not a new public surface (AC12).

    Asserted by absence, with the red control named in the message: adding either
    private name to `__all__` fails this.
    """
    assert procpool.__all__ == ["guarded_process_pool"], (
        f"`ops/procpool.__all__` is {procpool.__all__!r}. PDF-35 adds a start-method "
        f"DECISION, not an exported knob: `_START_METHOD` and `_mp_context` are "
        f"private and stay private. A caller that needs to override the start "
        f"method is asking to re-open ruling X-401, which is a product decision "
        f"rather than an argument."
    )
    for name in ("_START_METHOD", "_mp_context"):
        assert name not in procpool.__all__, name
        assert hasattr(procpool, name), (
            f"{name} is gone from ops/procpool -- the pin has been reverted or renamed"
        )


# --------------------------------------------------------------------------- #
# AC3 / AC4 -- the survivor matrix.
#
# Parameterized so the RED arm is EXERCISED rather than described in a comment.
# `forkserver` is expected to leak; `fork` and `spawn` are expected clean. The
# expectation is data, so inverting it makes the arm fail -- which is the proof
# that this reads the world rather than restating a belief about it.
# --------------------------------------------------------------------------- #


@_LINUX_ONLY
@pytest.mark.parametrize(
    ("method", "expect_orphans"),
    [
        # `fork`: the worker's parent IS the driver, so PR_SET_PDEATHSIG fires.
        ("fork", False),
        # `spawn`: same -- and this is the method the product pins.
        ("spawn", False),
        # `forkserver`: the worker's parent is the forkserver HELPER, which
        # outlives the driver, so the guard is armed against the wrong process
        # and never fires. THE RED. This is the defect PDF-35 exists to close,
        # and it is asserted POSITIVELY: if this arm ever goes green, either
        # CPython changed or this control stopped controlling, and both are
        # findings rather than relief.
        ("forkserver", True),
    ],
)
def test_ac3_survivors_and_post_death_growth_by_start_method(
    method: str, expect_orphans: bool, tmp_path: Path
) -> None:
    returncode, count_at_death, count_after_settle, survivors = _run_matrix_arm(method, tmp_path)
    growth = count_after_settle - count_at_death
    try:
        assert returncode == -signal.SIGKILL, (
            f"expected the {method} driver to die BY SIGKILL (returncode "
            f"{-signal.SIGKILL}), got {returncode}"
        )

        # AC4 -- NON-VACUITY, and it gates everything after it. Without this,
        # "no growth after death" is trivially true of a job that had already
        # finished, and the whole matrix would report a false green.
        assert count_at_death < _PAGES, (
            f"{count_at_death}/{_PAGES} pages already existed when the {method} "
            f"driver was killed -- the job finished before the signal landed, so "
            f"nothing this arm asserts afterwards is decisive. Raise _PAGES or "
            f"_BURN_ITERATIONS; do NOT relax the assertions below."
        )

        if expect_orphans:
            assert survivors, (
                f"start method {method!r} left ZERO survivors after SIGKILL to the "
                f"parent alone. That is the OPPOSITE of this arm's expectation and it "
                f"is a FINDING, not a relief: under `forkserver` a worker's parent is "
                f"the forkserver helper, so PR_SET_PDEATHSIG cannot protect it. If this "
                f"arm has gone green, the most likely causes are that it acquired an "
                f"allowlist (see this module's docstring for why that made the control "
                f"unable to fail once already) or that it lost its non-vacuity guard."
            )
            assert growth > 0, (
                f"start method {method!r} left {len(survivors)} survivor(s) but wrote "
                f"NO further output ({count_at_death} -> {count_after_settle}). The "
                f"defect is defined by both observables together -- an orphan that "
                f"writes nothing is a different (smaller) problem than one still "
                f"producing pages the user never asked for."
            )
        else:
            assert survivors == (), (
                f"after SIGKILL to the parent PID alone under start method {method!r}, "
                f"these processes are still alive in the job's own process group "
                f"(pgid inherited via start_new_session): {survivors} -- each one is an "
                f"orphaned worker holding buffers and a file handle."
            )
            # Only NOW is "no new output" decisive: asserted AFTER the survivors
            # are gone, so it cannot pass merely because the settle window was
            # short.
            assert growth == 0, (
                f"output grew from {count_at_death} to {count_after_settle} files after "
                f"the {method} driver was SIGKILLed -- something outlived it and kept "
                f"writing."
            )
    finally:
        _reap(survivors)


# --------------------------------------------------------------------------- #
# AC2 -- the pin defeats the ambient default, END TO END through the real CLI.
#
# The matrix above proves the MECHANISM. It cannot prove that the product's own
# CLI ignores whatever start method the interpreter (or an embedder) chose --
# that needs a real `pdftoolkit rasterize` under a forced ambient `forkserver`.
#
# This is the spec's centrepiece, and the property under test is precise: an
# explicit `mp_context=` DEFEATS `set_start_method()`. Pre-pin, this exact
# command reproduced the defect through the real CLI on the reference host
# (measured: 10 survivors, output 16 -> 32). Post-pin it is clean.
# --------------------------------------------------------------------------- #

#: D2 seam 1, and the seam that was actually used. It sets the ambient default
#: and then invokes the installed CLI's own entry point in-process: one command,
#: one variable, no file on disk, and it works on the venv's 3.12.13 without an
#: interpreter switch. Under `-c` there is no `__main__.__file__`, so `spawn`'s
#: `_fixup_main_from_path()` re-execution path is not even reached.
_FORKSERVER_SEAM = (
    "import multiprocessing, sys; "
    "multiprocessing.set_start_method('forkserver'); "
    "sys.argv = ['pdftoolkit'] + sys.argv[1:]; "
    "from pdf_toolkit.cli.main import main; "
    "sys.exit(main())"
)


def _make_source(directory: Path, *, pages: int) -> Path:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "start-method-source.pdf"
    made = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    # The CURRENT display name. The sibling fixture in `test_rasterize_signals.py`
    # still says the superseded one, and that occurrence is deliberately FROZEN by
    # `test_brand_surfaces.py`'s class H -- copying it into a NEW file would have
    # grown a frozen census, which is what that guard exists to catch. It did.
    made.setProducer("pdf-tooling test corpus")
    made.setCreator("tests/integration/test_render_pool_start_method.py")
    for number in range(1, pages + 1):
        made.drawString(72, 700, f"src page {number}")
        made.showPage()
    made.save()
    return path


@_LINUX_ONLY
def test_ac2_an_explicit_context_defeats_a_forced_ambient_forkserver(tmp_path: Path) -> None:
    """The claim about the kernel, not the claim about a string.

    A test asserting `_START_METHOD == "spawn"` says the source contains a word.
    This says: with the interpreter's ambient default set to the one start method
    that breaks the guarantee, a real SIGKILLed `rasterize` still leaves nothing
    behind.
    """
    pages = 32
    source = _make_source(tmp_path / "src", pages=pages)
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    short = _short_tmpdir()
    env["TMPDIR"] = short

    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _FORKSERVER_SEAM,
            "rasterize",
            str(source),
            "--dpi",
            "400",
            "--out-dir",
            str(out_dir),
            "--threads",
            "8",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=env,
    )
    signal_at = pages // 2
    survivors: tuple[tuple[int, str], ...] = ()
    try:
        deadline = time.monotonic() + _PROGRESS_TIMEOUT_S
        count = 0
        while time.monotonic() < deadline:
            count = len(list(out_dir.iterdir()))
            if count >= signal_at:
                break
            if proc.poll() is not None:
                stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
                pytest.fail(
                    f"the CLI exited (rc={proc.returncode}) before rendering {signal_at} "
                    f"pages -- this arm never reached the state it measures.\n"
                    f"stderr:\n{stderr[-2000:]}"
                )
            time.sleep(0.05)
        else:
            pytest.fail(
                f"only {count}/{signal_at} pages appeared within {_PROGRESS_TIMEOUT_S}s "
                f"-- the render started too slowly for this arm to be decisive"
            )

        os.kill(proc.pid, signal.SIGKILL)  # THE PARENT PID ONLY
        try:
            proc.wait(timeout=_PARENT_EXIT_TIMEOUT_S)
        except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL is uncatchable
            proc.kill()
            proc.wait(timeout=5)

        count_at_death = len(list(out_dir.iterdir()))
        survivors = _wait_for_no_survivors(proc.pid, timeout=_SURVIVOR_TIMEOUT_S)
        time.sleep(_SETTLE_S)
        count_after_settle = len(list(out_dir.iterdir()))

        assert proc.returncode == -signal.SIGKILL, proc.returncode
        assert count_at_death < pages, (
            f"{count_at_death}/{pages} pages existed at parent death -- the job "
            f"finished before SIGKILL arrived and this arm is not decisive"
        )
        assert survivors == (), (
            f"the ambient start method was forced to `forkserver` and a SIGKILLed "
            f"`rasterize` left these processes alive: {survivors}. The pin did NOT "
            f"defeat the ambient default -- either `mp_context=` was dropped from the "
            f"pool construction in ops/procpool.py, or something re-introduced a "
            f"context the product did not choose."
        )
        assert count_after_settle == count_at_death, (
            f"output grew from {count_at_death} to {count_after_settle} pages after the "
            f"parent was SIGKILLed under a forced ambient `forkserver` -- a worker "
            f"outlived the command that started it and kept writing"
        )
    finally:
        if proc.poll() is None:  # pragma: no cover - defensive
            proc.kill()
            proc.wait(timeout=5)
        _reap(survivors)
        _purge(short)


# --------------------------------------------------------------------------- #
# AC10 / D4 -- the AF_UNIX finding closes as a MECHANICAL CONSEQUENCE.
#
# The listener exists ONLY under `forkserver`, so pinning `spawn` does not
# mitigate `deabf608c2` -- it removes the object that causes it. That claim is
# made falsifiable in the user's own terms (a real CLI run at a real `$TMPDIR`
# length) rather than by reasoning, and corroborated on the filesystem rather
# than only by the absence of an exception.
#
# The arithmetic, re-derived against the INSTALLED stdlib rather than
# transcribed: `connection.arbitrary_address('AF_UNIX')` is
# `tempfile.mktemp(prefix='listener-', dir=util.get_temp_dir())`, and
# `get_temp_dir()` is `tempfile.mkdtemp(prefix='pymp-')`, each with an
# 8-character `_RandomNameSequence` suffix -- 6 + 8 + 10 + 8 = 32 past `$TMPDIR`.
# `sun_path[108]` including the NUL means 107 is the last path that binds, so
# `$TMPDIR` fails from 76 characters up. Measured pre-pin at length 80: the real
# CLI died with `OSError: AF_UNIX path too long` out of `forkserver.py`'s
# `listener.bind(address)`.
# --------------------------------------------------------------------------- #

_SUN_PATH_MAX = 107
_FORKSERVER_SUFFIX = 32
_MIN_FAILING_TMPDIR_LEN = _SUN_PATH_MAX - _FORKSERVER_SUFFIX + 1  # 76


def test_ac10_the_af_unix_arithmetic_is_re_derived_not_transcribed(tmp_path: Path) -> None:
    """The recipe, checked against the stdlib and the kernel in one place.

    A number carried between documents is a number nobody re-measures. This
    asserts the three inputs separately so a CPython change to the suffix length,
    or a platform with a different `sun_path`, fails HERE with a clear reason
    rather than as a mystifying timeout in the arm below.
    """
    import multiprocessing.util as mp_util

    assert len(next(tempfile._RandomNameSequence())) == 8, (  # type: ignore[attr-defined]
        "CPython's temporary-name suffix is no longer 8 characters -- the 32-byte "
        "forkserver suffix, and therefore _AF_UNIX_SAFE_TMPDIR_LEN in tests/fs_snapshot.py, "
        "must both be re-derived"
    )
    assert len("/pymp-") + 8 + len("/listener-") + 8 == _FORKSERVER_SUFFIX
    assert hasattr(mp_util, "get_temp_dir"), "the forkserver temp-dir helper moved"

    if not sys.platform.startswith("linux"):  # pragma: no cover - macOS sun_path is 104
        pytest.skip(
            "sun_path is 108 on Linux and 104 on macOS/BSD; this arm pins the Linux "
            "figure that the CI red (run 33738793820, test (3.14, ubuntu-latest)) was "
            "measured against"
        )

    # The kernel's own answer, not a header transcription: bind at the boundary.
    base = tmp_path / "b"
    base.mkdir()
    for length, should_bind in ((_SUN_PATH_MAX, True), (_SUN_PATH_MAX + 1, False)):
        padding = length - len(str(base)) - 1
        if padding < 1:  # pragma: no cover - pytest tmp_path is far shorter than 107
            pytest.skip(f"pytest tmp_path {str(base)!r} is too long to probe length {length}")
        path = str(base / ("a" * padding))
        assert len(path) == length
        sock = socket.socket(socket.AF_UNIX)
        try:
            sock.bind(path)
            bound = True
            os.unlink(path)
        except OSError:
            bound = False
        finally:
            sock.close()
        assert bound is should_bind, (
            f"an AF_UNIX bind at path length {length} returned bound={bound}; the "
            f"107-character ceiling this product's _AF_UNIX_SAFE_TMPDIR_LEN is derived "
            f"from does not hold on this kernel"
        )


@_LINUX_ONLY
def test_ac10_a_real_run_completes_at_a_tmpdir_length_that_broke_forkserver(
    tmp_path: Path,
) -> None:
    """`deabf608c2` in the user's own terms: the same command, the same `$TMPDIR`.

    Pre-pin, under a forced ambient `forkserver`, this raised `OSError: AF_UNIX
    path too long` from `forkserver.py::ensure_running` -> `listener.bind(address)`
    and the run produced nothing. Post-pin it completes, because `spawn` binds no
    socket at all -- the object is gone, not merely avoided.

    The ambient default is forced to `forkserver` here DELIBERATELY. Running this
    under the host's own default would prove nothing on a 3.11-3.13 box, where
    `fork` binds no socket either and the arm would pass without the pin.
    """
    long_tmp = tmp_path / ("t" * 60)
    long_tmp.mkdir(parents=True, exist_ok=True)
    if len(str(long_tmp)) < _MIN_FAILING_TMPDIR_LEN:  # pragma: no cover - tmp_path is long
        pytest.skip(
            f"could not construct a $TMPDIR of at least {_MIN_FAILING_TMPDIR_LEN} "
            f"characters under {tmp_path} (got {len(str(long_tmp))}); without it this "
            f"arm would pass vacuously"
        )

    source = _make_source(tmp_path / "src", pages=4)
    out_dir = tmp_path / "out"
    env = dict(os.environ)
    env["TMPDIR"] = str(long_tmp)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            _FORKSERVER_SEAM,
            "rasterize",
            str(source),
            "--dpi",
            "72",
            "--out-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=_PROGRESS_TIMEOUT_S,
    )

    assert "AF_UNIX path too long" not in result.stderr, (
        f"the run still dies of the `deabf608c2` path-length failure at "
        f"$TMPDIR length {len(str(long_tmp))}. `spawn` binds no AF_UNIX socket, so "
        f"reaching this means the pool was NOT built with the pinned context.\n"
        f"stderr:\n{result.stderr[-2000:]}"
    )
    assert result.returncode == 0, (
        f"a real `rasterize` at $TMPDIR length {len(str(long_tmp))} exited "
        f"{result.returncode}.\nstderr:\n{result.stderr[-2000:]}"
    )
    rendered = sorted(p.name for p in out_dir.iterdir())
    assert len(rendered) == 4, f"expected 4 rendered pages, got {rendered}"

    # The corroboration, and it is about the FILESYSTEM rather than about the
    # absence of an exception: a passing run could in principle have bound and
    # unlinked a socket. Nothing pinned-`spawn` does creates one at all.
    sockets = [p for p in long_tmp.rglob("*") if p.is_socket()]
    assert sockets == [], (
        f"an AF_UNIX socket appeared under $TMPDIR during a pinned run: {sockets}. "
        f"The pin is supposed to REMOVE the listener, not shorten its life."
    )
    leftovers = [p.name for p in long_tmp.iterdir() if p.name.startswith("pymp-")]
    assert leftovers == [], (
        f"forkserver temp directories were created under $TMPDIR during a pinned "
        f"run: {leftovers} -- the pool is not using the pinned context"
    )


# --------------------------------------------------------------------------- #
# AC9 / OR-7 -- `--dry-run` mirrors the real run on BOTH X-185 observables.
#
# Measured, not predicted. In the PRE-PIN posture this pair genuinely DIVERGED:
# at $TMPDIR length 80 under a forced ambient `forkserver`, `--dry-run` exited 0
# with a well-formed 7-key envelope while the real run exited 1 with an EMPTY
# stdout and a raw traceback -- a divergence on both observables at once, which
# is the strongest form of the OR-7 violation. Post-pin they agree, and this arm
# is what keeps them agreeing.
# --------------------------------------------------------------------------- #


@_LINUX_ONLY
def test_ac9_dry_run_and_real_run_agree_on_exit_code_and_envelope_shape(
    tmp_path: Path,
) -> None:
    import json

    long_tmp = tmp_path / ("t" * 60)
    long_tmp.mkdir(parents=True, exist_ok=True)
    if len(str(long_tmp)) < _MIN_FAILING_TMPDIR_LEN:  # pragma: no cover
        pytest.skip(f"$TMPDIR shorter than {_MIN_FAILING_TMPDIR_LEN}; arm would be vacuous")

    source = _make_source(tmp_path / "src", pages=4)
    env = dict(os.environ)
    env["TMPDIR"] = str(long_tmp)

    results: dict[str, tuple[int, dict[str, object]]] = {}
    for mode in ("dry", "real"):
        args = [
            "rasterize",
            str(source),
            "--dpi",
            "72",
            "--out-dir",
            str(tmp_path / f"out-{mode}"),
            "-o",
            "json",
        ]
        if mode == "dry":
            args.append("--dry-run")
        completed = subprocess.run(
            [sys.executable, "-c", _FORKSERVER_SEAM, *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=_PROGRESS_TIMEOUT_S,
        )
        try:
            envelope = json.loads(completed.stdout)
        except json.JSONDecodeError:
            pytest.fail(
                f"the {mode} run emitted no JSON envelope at all (exit "
                f"{completed.returncode}). Pre-pin this was the REAL run's behaviour: "
                f"it died inside pool construction before any envelope was written, "
                f"while --dry-run returned a clean one. That is the OR-7 divergence "
                f"this arm exists to keep closed.\nstderr:\n{completed.stderr[-1500:]}"
            )
        results[mode] = (completed.returncode, envelope)

    dry_code, dry_env = results["dry"]
    real_code, real_env = results["real"]

    # Observable 1 -- the exit code.
    assert dry_code == real_code, (
        f"--dry-run exited {dry_code} and the real run exited {real_code}. X-185: a "
        f"preview whose exit code does not mirror reality is worse than no preview, "
        f"because the user acts on it."
    )
    # Observable 2 -- the envelope SHAPE (keys), not its values: `items`,
    # `duration_ms` and `dry_run` legitimately differ between the two postures.
    assert sorted(dry_env.keys()) == sorted(real_env.keys()), (
        f"--dry-run produced envelope keys {sorted(dry_env.keys())} and the real run "
        f"produced {sorted(real_env.keys())}. Both observables are asserted because "
        f"the pre-pin defect broke BOTH at once."
    )
    assert dry_env.get("dry_run") is True and real_env.get("dry_run") is False, (
        f"the two runs are not actually in different postures: dry_run flags were "
        f"{dry_env.get('dry_run')!r} and {real_env.get('dry_run')!r} -- without this "
        f"the agreement above could be two identical runs agreeing with themselves"
    )
