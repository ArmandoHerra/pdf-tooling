"""PDF-146 D3: an opcode-boundary sweep proves an async unwind never strands a temp.

**The defect.** A render worker's ``_WorkerUnwind`` is raised from a signal handler,
which CPython runs at an eval-breaker site: the instruction after a call or a
backward jump, or a Python frame's entry. Two of those sites sit OUTSIDE the
``with AtomicWriter(...)`` statement's protected region while the temp inode
exists: inside ``__enter__`` after ``NamedTemporaryFile`` created the file (window
A), and at ``__exit__``'s own frame entry on the normal path (window B). Nothing
discards the temp from either, and the worker still ends by its own
``os._exit(143)``, so the pool records no SIGKILL: an unescalated stray.

**The instrument.** A child interpreter (the same ``sys.executable``) installs the
real worker handler, then runs one ``with AtomicWriter(...)`` per trial. In trial
N it sends ONE real signal when the N-th opcode of the statement executes and
delivers it, by calling the real handler, at the next eval-breaker site. It runs
trials until the signal no longer fires, so every site of the statement is hit.

* The tracer is ``sys.monitoring`` on 3.12+ and ``sys.settrace`` on 3.11: under
  ``settrace`` the first traced execution of a code object emits no opcode events
  on 3.13/3.14, which blinds a sweep to its own first trial.
* ``strays`` (AC1) counts trials that leave a toolkit temp. ``lost_in_window`` and
  ``other`` and ``resends`` (AC2) count a signal that never raised, an exception
  other than ``_WorkerUnwind``, and a signal sent from the unwind path.
* ``uncovered`` and the anchors (AC3) are the instrument's teeth: a reference trial
  lists every delivery site, and each must have been delivered at least once.
  ``trials`` is recorded and never floored, because it moves with path depth.

The literal temp prefix is never spelled here (``TEMP_PREFIX`` only).
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import textwrap
import warnings
from pathlib import Path
from typing import Any, Final

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="the worker handler and SIGHUP are POSIX-only; this product ships no Windows job",
)

SRC: Final[Path] = Path(__file__).resolve().parents[2] / "src" / "pdf_tooling"

#: D3's wall budget: dev host, solo, L0 (X-1154). Measured 135 s on 3.14.
_WALL_BUDGET_S: Final[float] = 240.0
#: D3's bound on GitHub Actions, where the node runs co-tenant in an xdist worker
#: of the full suite (X-1154): ceil10(1.25 x 462.6), the largest CI wall_s of
#: run 40474932446 (7 legs, 245.0-462.6 s), capped at _CHILD_TIMEOUT_S - 20 so
#: this assertion, not the subprocess timeout, names a breach. Re-derive from a
#: fresh census only; never widen it to make a leg green.
_CI_WALL_BUDGET_S: Final[float] = 580.0
_ON_GITHUB_ACTIONS: Final[bool] = os.environ.get("GITHUB_ACTIONS") == "true"
_CHILD_TIMEOUT_S: Final[int] = 600

#: The child program. A module-level constant with no spelled-out temp prefix. It is
#: written to a file and run as a script so it can read its own marker lines.
_SWEEP_PROGRAM: Final[str] = textwrap.dedent(
    r"""
    import collections, dis, json, os, shutil, signal, sys, tempfile, time
    from pathlib import Path

    from pdf_tooling.ops import procpool
    import pdf_tooling.safety.atomic as atomic
    from pdf_tooling.safety.atomic import AtomicWriter
    from pdf_tooling.safety.policy import SafetyPolicy
    from pdf_tooling.safety.tempnames import TEMP_PREFIX

    SIGS = tuple(getattr(signal, n) for n in ("SIGTERM", "SIGINT", "SIGHUP"))
    CHECK_OPS = {"CALL", "CALL_KW", "CALL_FUNCTION_EX", "JUMP_BACKWARD"}
    SELF = os.path.abspath(__file__)
    POLICY = SafetyPolicy(dry_run=False, force=False, in_place=False, backup=False,
                          assume_yes=True, is_tty=False, threads=1)
    USE_MON = sys.version_info >= (3, 12)
    HARNESS = "hook" if hasattr(atomic, "install_unwind_hook") else "direct"

    # The unwind path must send no signal (I3). The shims count a call made while one
    # of these names is on the stack; the harness injects through the saved originals.
    ORIG_KILL = os.kill
    ORIG_KILLPG = os.killpg
    ORIG_RAISE = signal.raise_signal
    ORIG_PTK = signal.pthread_kill
    HANDLER_NAMES = {"_raise_worker_unwind", "defer_unwind", "_lower_shield_and_deliver",
                     "install_unwind_hook"}


    class St:
        pass


    st = St()
    st.resends = 0
    st.defer_t = None
    st.unraisable = []
    _opnames = {}
    _resume = {}


    def opname(code, off):
        m = _opnames.get(code)
        if m is None:
            ins = list(dis.get_instructions(code))
            m = _opnames[code] = {i.offset: i.opname for i in ins}
            _resume[code] = next((i.offset for i in ins if i.opname == "RESUME"), 0)
        return m.get(off, "?")


    def resume_off(code):
        if code not in _resume:
            opname(code, 0)
        return _resume[code]


    def _stack_has_handler(f):
        while f is not None:
            c = f.f_code
            if c.co_name in HANDLER_NAMES:
                return True
            if c.co_name == "<lambda>" and os.path.basename(c.co_filename) == "procpool.py":
                return True
            f = f.f_back
        return False


    def _mk_shim(orig):
        def shim(*a, **k):
            if _stack_has_handler(sys._getframe(1)):
                st.resends += 1
            return orig(*a, **k)
        return shim


    def install_shims():
        os.kill = _mk_shim(ORIG_KILL)
        os.killpg = _mk_shim(ORIG_KILLPG)
        signal.raise_signal = _mk_shim(ORIG_RAISE)
        signal.pthread_kill = _mk_shim(ORIG_PTK)


    def _unraisable(u):
        st.unraisable.append(getattr(u.exc_type, "__name__", str(u.exc_type)))
        sys.__unraisablehook__(u)


    def recorder(signum, frame):
        st.recorded = True


    _wrapped = {"defer": False}


    def install_real():
        # Install the worker handler the way _worker_initializer does (one helper).
        if hasattr(atomic, "_SHIELD_DEPTH"):
            atomic._SHIELD_DEPTH = 0
            atomic._PENDING_SIGNUM = 0
        if hasattr(procpool, "_install_unwind_handlers"):
            procpool._install_unwind_handlers()
        else:
            for s in SIGS:
                signal.signal(s, procpool._raise_worker_unwind)
        # Hold-time instrumentation: wraps, changes no behaviour.
        if hasattr(atomic, "defer_unwind") and not _wrapped["defer"]:
            _wrapped["defer"] = True
            real_defer = atomic.defer_unwind

            def timed_defer(signum, frame=None):
                r = real_defer(signum, frame)
                if r and st.defer_t is None:
                    st.defer_t = time.perf_counter()
                return r
            atomic.defer_unwind = timed_defer
        hook = getattr(atomic, "_UNWIND_HOOK", None)
        if hook is not None:
            def timed_hook(signum, _h=hook):
                if st.defer_t is not None:
                    st.hold_ms = (time.perf_counter() - st.defer_t) * 1000.0
                return _h(signum)
            atomic._UNWIND_HOOK = timed_hook


    def inject(frame):
        # One real signal: the C-level handler trips; the Python handler is delivered
        # by this harness at the next eval-breaker site (the site predicate below).
        real = signal.getsignal(signal.SIGTERM)
        st.recorded = False
        signal.signal(signal.SIGTERM, recorder)
        ORIG_KILL(os.getpid(), signal.SIGTERM)
        signal.signal(signal.SIGTERM, real)
        assert st.recorded, "recorder did not run"
        st.pending = True
        st.prev_check = False


    def _finalizer_on_stack(f):
        while f is not None:
            c = f.f_code
            if c.co_name == "__del__":
                return c.co_qualname
            f = f.f_back
        return None


    def site_key(code, off, kind):
        return (code.co_qualname, os.path.basename(code.co_filename), off, kind)


    def deliver(frame, key):
        st.pending = False
        st.deliveries += 1
        DELIV[key] += 1
        st.deliv_site = key
        fin = _finalizer_on_stack(frame)
        if fin:
            st.deliv_final = fin
        handler = signal.getsignal(signal.SIGTERM)
        try:
            handler(signal.SIGTERM, frame)
        except BaseException:
            stop_events()
            st.armed = False
            raise


    def on_start(code, frame):
        if not st.armed:
            return
        key = site_key(code, resume_off(code), "resume")
        if not st.post:
            if code.co_qualname == "AtomicWriter.__enter__" and not st.entered:
                st.entered = True
            elif code.co_qualname == "AtomicWriter.__exit__":
                st.in_exit = True
            if st.refmode:
                REFSITES.setdefault(key, len(REFSITES))
        if st.pending:
            deliver(frame, key)
        st.prev_check = False


    def on_instr(code, off, frame):
        if not st.armed:
            return
        name = opname(code, off)
        if name == "RESUME":
            return
        if st.prev_check:
            kind = "post-jump" if st.prev_op == "JUMP_BACKWARD" else "post-call"
            key = site_key(code, off, kind)
            if st.refmode and not st.post:
                REFSITES.setdefault(key, len(REFSITES))
            if st.pending:
                deliver(frame, key)
        if st.in_exit and code is RUN_CODE:
            st.window_closed = True
        counted = not st.post
        if counted:
            st.count += 1
        if counted and st.count == st.target and not st.fired:
            st.fired = True
            st.in_window = st.entered and not st.window_closed
            st.kill = [code.co_qualname, os.path.basename(code.co_filename),
                       frame.f_lineno, name]
            inject(frame)
        st.prev_check = name in CHECK_OPS
        st.prev_op = name


    def on_line(code, line):
        if code is RUN_CODE:
            if line == WITH_LINE:
                st.armed = True
            elif line == POST_LINE:
                st.post = True
            elif line == END_LINE:
                st.armed = False


    if USE_MON:
        mon = sys.monitoring
        TOOL = mon.PROFILER_ID
        EV = mon.events
        _enabled = set()

        def m_start(code, offset):
            if not st.armed:
                return
            if code not in _enabled:
                _enabled.add(code)
                mon.set_local_events(TOOL, code, EV.INSTRUCTION)
            on_start(code, sys._getframe(1))

        def m_instr(code, offset):
            if st.armed:
                on_instr(code, offset, sys._getframe(1))

        def m_line(code, line):
            on_line(code, line)

        def start_events():
            mon.set_events(TOOL, EV.PY_START)
            mon.set_local_events(TOOL, RUN_CODE, EV.LINE | EV.INSTRUCTION)

        def stop_events():
            mon.set_events(TOOL, 0)
            for c in list(_enabled):
                try:
                    mon.set_local_events(TOOL, c, 0)
                except Exception:
                    pass
            _enabled.clear()
            try:
                mon.set_local_events(TOOL, RUN_CODE, 0)
            except Exception:
                pass

        mon.use_tool_id(TOOL, "pdf146_sweep")
        mon.register_callback(TOOL, EV.PY_START, m_start)
        mon.register_callback(TOOL, EV.INSTRUCTION, m_instr)
        mon.register_callback(TOOL, EV.LINE, m_line)
    else:
        def local_tracer(frame, event, arg):
            if event == "opcode":
                if st.armed:
                    on_instr(frame.f_code, frame.f_lasti, frame)
            elif event == "line" and frame.f_code is RUN_CODE:
                on_line(RUN_CODE, frame.f_lineno)
            return local_tracer

        def global_tracer(frame, event, arg):
            if event == "call":
                frame.f_trace_opcodes = True
                on_start(frame.f_code, frame)
                return local_tracer
            return None

        def start_events():
            me = RUN_FRAME[0]
            me.f_trace = local_tracer
            me.f_trace_opcodes = True
            sys.settrace(global_tracer)

        def stop_events():
            sys.settrace(None)
            RUN_FRAME[0].f_trace = None

    RUN_FRAME = [None]


    def sentinel():
        return 1


    DELIV = collections.Counter()
    REFSITES = {}


    def run(n, root, refmode=False):
        dest = Path(root) / "page-001.png"
        st.count = 0; st.target = n; st.fired = False; st.pending = False
        st.prev_check = False; st.prev_op = None; st.armed = False; st.post = False
        st.deliveries = 0
        st.kill = None; st.in_window = False
        st.entered = False; st.in_exit = False; st.window_closed = False
        st.deliv_site = None; st.deliv_final = None; st.refmode = refmode
        st.hold_ms = None; st.defer_t = None; st.unraisable = []
        install_real()
        exc = None
        RUN_FRAME[0] = sys._getframe()
        start_events()
        try:
            with AtomicWriter(dest, policy=POLICY, kind="image") as w:  # WITH_MARK
                w.stream.write(b"x" * 65536)
            sentinel()  # POST_MARK
            x = 1  # END_MARK
        except BaseException as e:
            exc = e
        finally:
            # Disarm before tracing is torn down: a late pending injection must not
            # fire into the harness's own teardown.
            st.armed = False
            st.pending = False
            stop_events()
        return exc


    def _lines():
        src = Path(SELF).read_text().splitlines()
        w = next(i + 1 for i, l in enumerate(src) if l.rstrip().endswith("# WITH_MARK"))
        e = next(i + 1 for i, l in enumerate(src) if l.rstrip().endswith("# END_MARK"))
        p = next(i + 1 for i, l in enumerate(src) if l.rstrip().endswith("# POST_MARK"))
        return w, e, p


    WITH_LINE, END_LINE, POST_LINE = _lines()
    RUN_CODE = run.__code__


    def surfaced(exc):
        tb = exc.__traceback__
        last = None
        chain = []
        while tb is not None:
            c = tb.tb_frame.f_code
            if os.path.abspath(c.co_filename) != SELF and c.co_name not in (
                    "_raise_worker_unwind", "<lambda>"):
                last = [c.co_qualname, os.path.basename(c.co_filename), tb.tb_lineno]
                chain.append(os.path.basename(c.co_filename) + ":" + c.co_name)
            tb = tb.tb_next
        return last, chain


    def loadavg():
        if not os.path.exists("/proc/loadavg"):
            return []
        return open("/proc/loadavg").read().split()[:3]


    def main():
        t_start = time.perf_counter()
        base = Path(sys.argv[1])
        la_start = loadavg()
        sys.unraisablehook = _unraisable
        install_shims()

        # Two un-signalled reference trials (cold, then warm) must list identical sites.
        refs = []
        for _ in range(2):
            root = tempfile.mkdtemp(prefix="ref-", dir=base)
            REFSITES.clear()
            run(0, root, refmode=True)
            refs.append((list(REFSITES), st.count))
            shutil.rmtree(root, ignore_errors=True)
        ref_stable = refs[0][0] == refs[1][0] and refs[0][1] == refs[1][1]
        ref_sites = list(REFSITES)
        DELIV.clear()
        st.resends = 0

        results = []
        total = None
        n = 1
        holds = []
        while True:
            root = tempfile.mkdtemp(prefix="trial-", dir=base)
            exc = run(n, root)
            temps = sorted(p.name for p in Path(root).iterdir() if p.name.startswith(TEMP_PREFIX))
            unwind = isinstance(exc, procpool._WorkerUnwind)
            r = dict(n=n, fired=st.fired, kill=st.kill, unwind=unwind,
                     other=(None if exc is None or unwind else repr(exc)),
                     surfaced=None, chain=[], temps=temps, deliv_site=st.deliv_site,
                     deliv_final=st.deliv_final, in_window=st.in_window)
            if exc is not None:
                r["surfaced"], r["chain"] = surfaced(exc)
            results.append(r)
            if st.hold_ms is not None:
                holds.append(st.hold_ms)
            shutil.rmtree(root, ignore_errors=True)
            if not st.fired:
                total = st.count
                break
            n += 1
        trials = results[:-1] if total is not None else results
        strays = [r for r in trials if r["temps"]]
        others = [r for r in trials if r["other"]]
        lost = [r for r in trials if r["fired"] and not r["unwind"] and r["other"] is None]
        lost_in = [r for r in lost if r["in_window"]]
        lost_out = [r for r in lost if not r["in_window"]]
        wc = collections.Counter(
            ("__enter__" if "atomic.py:__enter__" in r["chain"] else
             "__exit__" if "atomic.py:__exit__" in r["chain"] else "other") for r in strays)

        def lsite(r):
            if r["deliv_site"]:
                return "deliv:" + ":".join(str(x) for x in r["deliv_site"]) + (
                    " in " + r["deliv_final"] if r["deliv_final"] else "")
            return "never-delivered:fire@" + ":".join(str(x) for x in (r["kill"] or []))
        lost_by_site = collections.Counter(lsite(r) for r in lost)

        uncovered = [k for k in ref_sites if DELIV.get(k, 0) == 0]

        def fn_sites(qual, fname):
            return [[k[2], k[3], DELIV.get(k, 0)] for k in ref_sites
                    if k[0] == qual and k[1] == fname]
        anchors = {
            "AtomicWriter.__enter__": fn_sites("AtomicWriter.__enter__", "atomic.py"),
            "AtomicWriter._open_temp": fn_sites("AtomicWriter._open_temp", "atomic.py"),
            "AtomicWriter.__exit__": fn_sites("AtomicWriter.__exit__", "atomic.py"),
            "NamedTemporaryFile": fn_sites("NamedTemporaryFile", "tempfile.py"),
        }
        offenders = []
        for kind, rows in (("stray", strays), ("lost", lost), ("other", others)):
            for r in rows[:10]:
                offenders.append(dict(kind=kind, n=r["n"], kill=r["kill"], deliv=r["deliv_site"],
                                      surfaced=r["surfaced"], temps=r["temps"], other=r["other"]))
        summary = dict(
            python=sys.version.split()[0], harness=HARNESS, mon=USE_MON,
            trials=len(trials), strays=len(strays), windows=dict(wc),
            lost_in_window=len(lost_in), lost_outside=len(lost_out),
            lost_by_site=dict(lost_by_site.most_common(8)),
            other=len(others), resends=st.resends, ref_stable=ref_stable,
            sites_total=len(ref_sites), uncovered=len(uncovered),
            uncovered_list=[list(k) for k in uncovered[:20]], anchors=anchors,
            max_hold_ms=(round(max(holds), 3) if holds else None),
            offenders=offenders[:10], loadavg_start=la_start,
            loadavg_end=loadavg(),
            wall_s=round(time.perf_counter() - t_start, 1))
        print(json.dumps(summary))


    if __name__ == "__main__":
        main()
    """
)

_ANCHOR_FUNCTIONS: Final[tuple[str, ...]] = (
    "AtomicWriter.__enter__",
    "AtomicWriter._open_temp",
    "AtomicWriter.__exit__",
)


def _check_wall_budget(wall_s: float, on_ci: bool) -> None:
    bound = _CI_WALL_BUDGET_S if on_ci else _WALL_BUDGET_S
    assert wall_s <= bound, (
        f"the sweep took {wall_s} s, over the {bound} s {'CI' if on_ci else 'dev-host solo'} "
        f"budget (report it; never stride, sample or rerun)"
    )


def _run_sweep(tmp_path: Path) -> dict[str, Any]:
    script = tmp_path / "sweep_child.py"
    script.write_text(_SWEEP_PROGRAM)
    work = tmp_path / "trials"
    work.mkdir()
    # Not measured: a coverage tracer in the child adds frames of its own, which
    # makes the cold and the warm reference trials differ, and measures nothing the
    # sweep is about. `coverage`'s subprocess patch is keyed by these variables.
    env = {key: value for key, value in os.environ.items() if not key.startswith("COVERAGE")}
    done = subprocess.run(
        [sys.executable, "-I", str(script), str(work)],
        capture_output=True,
        text=True,
        timeout=_CHILD_TIMEOUT_S,
        check=False,
        env=env,
    )
    lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
    assert done.returncode == 0 and lines, (
        f"the sweep child failed (exit {done.returncode}): {done.stderr[-2000:]!r}"
    )
    summary: dict[str, Any] = json.loads(lines[-1])
    return summary


def test_one_async_unwind_at_any_eval_breaker_site_leaves_no_temp_and_is_never_lost(
    tmp_path: Path,
) -> None:
    summary = _run_sweep(tmp_path)
    # Recorded on every drive, red or green: AC1-AC3's base and after.
    shown = {key: value for key, value in summary.items() if key != "offenders"}
    print(f"PDF-146 sweep summary: {json.dumps(shown, sort_keys=True)}")
    if _ON_GITHUB_ACTIONS:
        # Puts wall_s/trials on green legs too, through the warnings summary xdist relays.
        warnings.warn(f"PDF-146 sweep summary: {json.dumps(shown, sort_keys=True)}", stacklevel=1)

    # 1. The instrument is stable.
    assert summary["ref_stable"], (
        "the cold and the warm reference trials listed different delivery sites"
    )
    # 2. AC3: it reached every site of the statement, and the three anchors.
    assert summary["uncovered"] == 0, (
        f"{summary['uncovered']} delivery site(s) of {summary['sites_total']} were never "
        f"delivered: {summary['uncovered_list']}"
    )
    for function in _ANCHOR_FUNCTIONS:
        resume = [row for row in summary["anchors"][function] if row[1] == "resume"]
        assert resume and sum(row[2] for row in resume) >= 1, (
            f"{function}'s frame entry was never a delivery site: {summary['anchors'][function]}"
        )
    non_resume = [row for row in summary["anchors"]["NamedTemporaryFile"] if row[1] != "resume"]
    assert non_resume and all(row[2] >= 1 for row in non_resume), (
        f"tempfile.NamedTemporaryFile's post-call sites were not all delivered: {non_resume}"
    )
    _check_wall_budget(summary["wall_s"], _ON_GITHUB_ACTIONS)
    # 3. AC1: no temp survives one async unwind at any site.
    assert summary["strays"] == 0, (
        f"{summary['strays']} trial(s) left a temp (windows {summary['windows']}, harness "
        f"{summary['harness']}); first offenders: {summary['offenders']}"
    )
    # 4. AC2: nothing lost, nothing else raised, nothing re-sent.
    assert summary["lost_in_window"] == 0, (
        f"{summary['lost_in_window']} signal(s) were never raised inside the shield span: "
        f"{summary['lost_by_site']}"
    )
    assert summary["other"] == 0, f"{summary['other']} trial(s) raised something else"
    assert summary["resends"] == 0, f"the unwind path sent {summary['resends']} signal(s)"


def test_the_wall_budget_reds_over_its_bound_on_the_dev_host_and_on_ci() -> None:
    assert _WALL_BUDGET_S < _CI_WALL_BUDGET_S <= _CHILD_TIMEOUT_S - 20
    with pytest.raises(AssertionError, match=r"580\.0 s CI"):
        _check_wall_budget(580.1, True)
    _check_wall_budget(580.0, True)
    _check_wall_budget(240.1, True)
    with pytest.raises(AssertionError, match=r"240\.0 s dev-host"):
        _check_wall_budget(240.1, False)
    _check_wall_budget(240.0, False)


#: The four functions whose bodies must send no signal (I3), by name.
_UNWIND_PATH: Final[dict[str, tuple[str, ...]]] = {
    "ops/procpool.py": ("_raise_worker_unwind", "_install_unwind_handlers"),
    "safety/atomic.py": ("defer_unwind", "install_unwind_hook", "_lower_shield_and_deliver"),
}
_SENDERS: Final[frozenset[str]] = frozenset({"kill", "killpg", "raise_signal", "pthread_kill"})


def _signal_calls(function: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            callee = node.func
            name = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", "")
            if name in _SENDERS:
                found.append(ast.unparse(callee))
    return found


def test_the_worker_unwind_path_never_sends_a_signal() -> None:
    offenders: list[str] = []
    checked = 0
    for relative, names in _UNWIND_PATH.items():
        tree = ast.parse((SRC / relative).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in names:
                checked += 1
                offenders.extend(f"{node.name} calls {name}" for name in _signal_calls(node))
    assert checked >= 1, "none of the unwind-path functions was found"
    assert offenders == [], f"the worker unwind path sends a signal (I3): {offenders}"
