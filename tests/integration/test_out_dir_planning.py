"""PDF-18 -- the unwritable-parent tier, proven over the live `--out-dir`
population (`d55b302668` / B-112, AC7-AC15).

**The one precondition that decides whether this file is real.** Every
``--out-dir`` in the U, C and F cells below must point at a directory that
does **not yet exist**. With a populated ``--out-dir``, the exit-5
no-clobber gate fires first and completely masks the tier on 10 of 11 verbs
-- a probe that reuses a populated ``--out-dir`` will report `d55b302668`
closed. That precondition is what distinguishes cells U/C from N/M, and cell
F exists specifically to prove the matrix is not silence wearing five
different names (§ AC12's own note).

**Population, derived, not typed** (Design D8). ``discover_verbs()`` and
``OUTPUT_FLAG_INVOCATIONS`` are `tests/registry.py`'s own live-registry
symbols; this module reads them and asserts non-shrinkage rather than
hand-listing eleven verb strings.

**Every ``--out-dir`` invocation here is built from the SAME
``OUTPUT_FLAG_INVOCATIONS[(verb, "--out-dir")]`` callable `PDF-17`'s own
`C14`/AC25 harness registers**, with one deliberate exception: `tables`'
own registered invocation uses the `tabular` fixture, which genuinely
detects table content and would seed 1+ real output files -- exactly the
population AC13 says `tables` must NOT have, so cells N/M/F can prove it is
the one verb the exit-5 gate cannot mask. `tables`' own cells are built
against `single_page` instead (no drawn table grid, zero detections),
stated here rather than silently substituted.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, str(TESTS_DIR))

from dryreal import dry_and_real, prediction, real_envelope  # noqa: E402
from fs_snapshot import assert_unchanged, redirected_environment, snapshot  # noqa: E402
from pdf_tooling.ports.office import office_binary_present  # noqa: E402
from registry import OUTPUT_FLAG_INVOCATIONS, discover_verbs, run_cli  # noqa: E402

# --------------------------------------------------------------------------- #
# The population (Design D8) -- derived, asserted non-empty AND non-shrinking.
# --------------------------------------------------------------------------- #

VERBS: Final[tuple[str, ...]] = tuple(
    sorted(verb.name for verb in discover_verbs() if "--out-dir" in verb.consumes)
)

#: `office_binary_present()` is a spawn-free `shutil.which` check (its own
#: docstring: it exists precisely so a `--dry-run` preview can ask "is the
#: engine there" without the side effect `require_office()` has when the
#: engine IS present). Detecting it once here at collection time is D8's own
#: "derived, not hand-typed" philosophy applied to a second population axis
#: -- not just WHICH verbs take `--out-dir`, but which of THIS matrix's cells
#: an engine-dependent verb can even measure on the current leg.
_OFFICE_PRESENT: Final[bool] = office_binary_present()

#: AC12's C cell (parent writable, out-dir absent) for `convert`: the
#: filesystem tier answers cleanly -- `0` -- in BOTH modes regardless of the
#: engine, but `ops/office.py:203`'s own `not plan.refused and not
#: office_binary_present()` guard means the very NEXT tier, engine presence,
#: refuses with exit `3` in both modes too (OR-7/D12.1) whenever `soffice`
#: is absent. Every other `--out-dir` verb has no engine-shaped tier between
#: the filesystem check and success, so its own C cell is unconditionally
#: `0`. This is `_NO_CLOBBER_EXPECTED`'s own sibling pattern below: an
#: expected VALUE, derived once at module scope -- never a skip, and never
#: hand-typed per cell.
_C_CELL_EXPECTED: Final[dict[str, int]] = {"convert": 0 if _OFFICE_PRESENT else 3}

#: AC13 -- the one verb the exit-5 no-clobber gate cannot mask, because its
#: own N/M/F cells are built to produce nothing. Every other verb's N/M/F
#: cell reads 5 (masked) / 5 (masked) / 0 (force steps aside); `tables`
#: reads 0 / 0 / 0 throughout, because there is nothing to collide with.
_NO_CLOBBER_EXPECTED: Final[dict[str, int]] = {"tables": 0}
_DEFAULT_NO_CLOBBER_EXPECTED: Final[int] = 5


def test_the_population_is_derived_and_pinned_at_eleven() -> None:
    """The non-emptiness AND non-shrinkage guard Design D8 asks for: a future
    `--out-dir` verb joins with zero author action and trips this count,
    which is the intended prompt to extend the matrix rather than a failure
    to route around."""
    assert len(VERBS) == 11, (
        f"the live --out-dir population is {len(VERBS)}, not 11: {VERBS} -- "
        "extend this matrix rather than silently accepting the new count"
    )
    for verb in VERBS:
        assert (verb, "--out-dir") in OUTPUT_FLAG_INVOCATIONS, (
            f"{verb!r} declares --out-dir but has no registered invocation "
            "(AC25's own anti-lapse guard should have caught this first)"
        )


# --------------------------------------------------------------------------- #
# Shared invocation building
# --------------------------------------------------------------------------- #


def _out_dir_argv(verb: str, corpus: Any, root: Path) -> tuple[list[str], Path]:
    """The registered ``--out-dir`` invocation for *verb*, built against
    *root* (which becomes ``--out-dir``'s own parent) -- plus the resolved
    ``out_dir`` path itself, read back out of the built argv rather than
    reconstructed by convention.

    AC13's documented exception: `tables` is rebuilt against `single_page`
    (see the module docstring) so its own N/M/F cells read 0, not 5.
    """
    if verb == "tables":
        argv = [str(corpus.path("single_page")), "--out-dir", str(root / "or3-tables-out-dir")]
    else:
        argv = OUTPUT_FLAG_INVOCATIONS[(verb, "--out-dir")](corpus, root)
    index = argv.index("--out-dir")
    out_dir = Path(argv[index + 1])
    assert out_dir.parent == root, (
        f"{verb}'s registered --out-dir invocation does not place its target "
        f"directly under the directory this matrix chmods: {out_dir} vs {root}"
    )
    return argv, out_dir


def _skip_if_root_ignores_mode_bits(directory: Path) -> None:
    """The post-chmod probe form (`tests/unit/test_atomic_writer.py:470` and
    friends): catches BOTH root (euid 0) and the container case where euid is
    non-zero but mode bits are ignored anyway -- the bare `os.geteuid() == 0`
    form catches neither of the second kind."""
    if os.access(directory, os.W_OK):
        pytest.skip("this user can write to a mode-0500 directory (root or CAP_DAC_OVERRIDE?)")


# --------------------------------------------------------------------------- #
# AC7 / AC9 / AC12 / AC13 -- the five-precondition matrix, one verb at a
# time. Every cell is a measured dry/real pair; U, C and N/M/F are built
# fresh so no cell's precondition leaks into another's.
#
# `convert` is the one verb here whose engine can be legitimately ABSENT
# (D12.1/B-096/OR-7). This does NOT gate the parametrize case (a whole-verb
# `pytest.mark.requires("soffice")` skip would throw the U cell away on
# every leg but `engines-present` -- U is engine-INDEPENDENT: the filesystem
# tier refuses before `ops/office.py:203`'s engine-presence check is ever
# reached, in both modes, so it is the cell that proves PDF-18's D3 thesis
# and it is asserted UNCONDITIONALLY below, on every leg). Only the C cell's
# EXPECTED VALUE (`_C_CELL_EXPECTED`, module scope, AC13's own
# "expected-value, not skip" pattern) and the N/M/F seeding step are
# engine-dependent -- see the inline notes at each.
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
@pytest.mark.parametrize("verb", VERBS)
def test_ac12_the_five_precondition_matrix(verb: str, corpus: Any, tmp_path: Path) -> None:
    env, _roots = redirected_environment(tmp_path)

    # -- U: parent 0o500, out-dir absent -> dry == real == 1 (AC7) -------- #
    u_root = tmp_path / "cell-u"
    u_root.mkdir()
    u_argv, u_out_dir = _out_dir_argv(verb, corpus, u_root)
    u_root.chmod(0o500)
    try:
        _skip_if_root_ignores_mode_bits(u_root)
        u_dry, u_real = dry_and_real(verb, u_argv, cwd=u_root, env=env)
    finally:
        u_root.chmod(0o700)

    u_detail = prediction(u_dry.stdout)
    assert u_detail["would_exit"] == 1, f"{verb} U cell: dry predicted {u_detail}"
    assert u_dry.returncode == u_real.returncode == 1, (
        f"{verb} U cell: dry {u_dry.returncode} != real {u_real.returncode}"
    )
    # X-184: never on the exit integer alone -- the stdout envelope and the
    # absence of a traceback are the observables `fa5736f2ae`'s own arm
    # (AC8, the next test) drives red; here they are the non-regression
    # guard for every OTHER verb's U cell too.
    u_real_envelope = real_envelope(u_real.stdout)
    assert u_real_envelope is not None, f"{verb} U cell: real stdout was empty under -o json"
    assert u_real_envelope["error"]["kind"] == "failure"
    assert "Traceback (most recent call last)" not in u_real.stderr, u_real.stderr
    assert not u_out_dir.exists(), "neither run may create the directory it refuses"

    # -- C: parent writable, out-dir absent -> dry == real == 0 (AC9),
    #    EXCEPT `convert` when `soffice` is ABSENT (`_C_CELL_EXPECTED`,
    #    module scope): the filesystem tier answers cleanly in both modes,
    #    but `ops/office.py:203`'s `not plan.refused and not
    #    office_binary_present()` guard means the engine-presence tier
    #    refuses right after it, with exit 3, ALSO in both modes (OR-7).
    #    Dry and real run SEPARATELY here (not through `dry_and_real`, which
    #    returns both only after running both) so Trap 1's absent-then-present
    #    existence check can land BETWEEN the two runs, not after both.
    c_root = tmp_path / "cell-c"
    c_root.mkdir()
    c_argv, c_out_dir = _out_dir_argv(verb, corpus, c_root)
    expected_c = _C_CELL_EXPECTED.get(verb, 0)

    c_dry = run_cli(verb, "--dry-run", *c_argv, "-o", "json", cwd=c_root, env=env)
    assert c_dry.returncode == expected_c, (
        f"{verb} C cell: dry {c_dry.returncode}, expected {expected_c}"
    )
    assert not c_out_dir.exists(), "Trap 1: the dry run must leave a non-existent out-dir absent"

    c_real = run_cli(verb, *c_argv, "-o", "json", cwd=c_root, env=env)
    assert c_real.returncode == expected_c, (
        f"{verb} C cell real run: {c_real.stdout}{c_real.stderr}, expected {expected_c}"
    )

    if expected_c == 0:
        c_detail = prediction(c_dry.stdout)
        assert c_detail["would_exit"] == 0, f"{verb} C cell: dry predicted {c_detail}"
        assert c_out_dir.is_dir(), "Trap 1's other half: the real run must have created it"
    else:
        # `convert`, `soffice` absent: an ENGINE-tier refusal, not a
        # filesystem-tier one. `dryreal.prediction()` is deliberately NOT
        # used here -- it asserts an `items` list exists, and NEITHER run
        # ever constructs one: `require_office()` raises before the dry
        # branch builds `items` and before the real branch's write loop
        # starts, so both envelopes are the top-level `{"error": {...}}`
        # shape `render_error_json` emits for an uncaught `PdfToolingError`.
        # Asserted directly instead, on the SHAPE (X-184(b)/X-185), never
        # the exit integer alone. `c_out_dir`'s own existence after the real
        # run is NOT asserted here: `plan_filesystem`'s real-mode branch
        # already ran `_ensure_out_dir`'s `mkdir` (unrefused) before
        # `require_office()` raised, so the directory is typically created
        # anyway as an incidental side effect -- not a property this cell
        # exists to pin, and not the same "planned, not silently absent"
        # shape Trap 1 is about (that guard is about a *clean* run, not one
        # already ending in a different tier's refusal).
        dry_error = json.loads(c_dry.stdout)["error"]
        real_error = json.loads(c_real.stdout)["error"]
        assert dry_error["kind"] == real_error["kind"] == "engine_missing", (
            f"{verb} C cell (soffice absent): dry {dry_error} real {real_error}"
        )
        assert "Traceback (most recent call last)" not in c_dry.stderr, c_dry.stderr
        assert "Traceback (most recent call last)" not in c_real.stderr, c_real.stderr

    if verb == "convert" and not _OFFICE_PRESENT:
        # N/M/F all depend on a SEEDING run (below) that succeeds and writes
        # a real colliding output -- for every other verb, that seed is a
        # plain real invocation of the verb itself. For `convert` without
        # `soffice`, the seed cannot succeed: `require_office()` raises
        # exit 3 before the per-target write loop ever runs, so there is no
        # colliding target to build N/M/F's own precondition from at all.
        # This is NOT the `tables` shape (AC13): `tables`' seed run DOES
        # succeed (exit 0), it simply detects nothing to write, so its N/M/F
        # cells get an expected VALUE (0) rather than being unreachable.
        # Here the seed run itself cannot complete, so a fixed expected
        # value would not exercise the no-clobber gate or `--force` at all --
        # every re-probe would read `engine_missing` regardless of state,
        # which is exactly the "one answer everywhere" shape AC12's own note
        # warns a silent preview would produce. U and C are asserted above,
        # UNCONDITIONALLY, on this same leg; the `engines-present` CI job
        # (which installs `libreoffice-writer`) is where this verb's full
        # five-cell matrix, N/M/F included, is proven.
        pytest.skip(
            "convert's N/M/F cells need a REAL conversion to seed a colliding "
            "output; soffice is absent on this leg, so seeding itself exits 3 "
            "(engine_missing) before writing anything -- there is no "
            "colliding target to build N/M/F's precondition from. U and C "
            "are asserted above, unconditionally, on this same leg."
        )

    # -- N / M / F: seed once under a writable parent, then re-probe ------ #
    nmf_root = tmp_path / "cell-nmf"
    nmf_root.mkdir()
    nmf_argv, nmf_out_dir = _out_dir_argv(verb, corpus, nmf_root)
    seed = run_cli(verb, *nmf_argv, "-o", "json", cwd=nmf_root, env=env)
    assert seed.returncode == 0, f"{verb} seeding run failed: {seed.stdout}{seed.stderr}"
    assert nmf_out_dir.is_dir()

    expected_masked = _NO_CLOBBER_EXPECTED.get(verb, _DEFAULT_NO_CLOBBER_EXPECTED)

    # N: out-dir exists, colliding (or, for `tables`, simply already there).
    n_dry, n_real = dry_and_real(verb, nmf_argv, cwd=nmf_root, env=env)
    n_detail = prediction(n_dry, context=f"{verb} N cell")
    assert n_detail["would_exit"] == expected_masked, f"{verb} N cell: dry predicted {n_detail}"
    assert n_dry.returncode == n_real.returncode == expected_masked

    # M: as N, plus out-dir's OWN PARENT locked -- the mask must still hold,
    # because `_ensure_out_dir`'s `mkdir(exist_ok=True)` only needs SEARCH
    # permission on the parent to discover EEXIST, never write.
    nmf_root.chmod(0o500)
    try:
        _skip_if_root_ignores_mode_bits(nmf_root)
        m_dry, m_real = dry_and_real(verb, nmf_argv, cwd=nmf_root, env=env)
    finally:
        nmf_root.chmod(0o700)
    m_detail = prediction(m_dry, context=f"{verb} M cell")
    assert m_detail["would_exit"] == expected_masked, f"{verb} M cell: dry predicted {m_detail}"
    assert m_dry.returncode == m_real.returncode == expected_masked

    # F: as M, plus --force -y -- the gate steps aside and a LOWER tier
    # answers (AC12's own note: this is the cell that proves the matrix is
    # not silence wearing five names).
    nmf_root.chmod(0o500)
    try:
        _skip_if_root_ignores_mode_bits(nmf_root)
        f_dry, f_real = dry_and_real(verb, [*nmf_argv, "--force", "-y"], cwd=nmf_root, env=env)
    finally:
        nmf_root.chmod(0o700)
    f_detail = prediction(f_dry, context=f"{verb} F cell")
    assert f_detail["would_exit"] == 0, f"{verb} F cell: dry predicted {f_detail}"
    assert f_dry.returncode == f_real.returncode == 0, (
        f"{verb} F cell: dry {f_dry.returncode} real {f_real.returncode} "
        f"({f_real.stdout}{f_real.stderr})"
    )


# --------------------------------------------------------------------------- #
# AC8 -- the errno family, on `compress` (a hard, always-present dependency,
# so no engine availability confounds the filesystem-tier signal). EACCES is
# already covered above (the U cell, all 11 verbs); this covers the rest.
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
def test_ac8_enotdir_a_path_component_is_a_file(corpus: Any, tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    blocker = root / "blocker.file"
    blocker.write_bytes(b"x")
    argv = [str(corpus.path("single_page")), "--out-dir", str(blocker / "sub")]
    env, _roots = redirected_environment(tmp_path)

    dry, real = dry_and_real("compress", argv, cwd=root, env=env)
    assert prediction(dry.stdout)["would_exit"] == 1
    assert real.returncode == 1, real.stdout + real.stderr
    envelope = real_envelope(real.stdout)
    assert envelope is not None
    assert envelope["error"]["kind"] == "failure"
    assert "Traceback (most recent call last)" not in real.stderr
    assert blocker.read_bytes() == b"x"


@pytest.mark.e2e
def test_ac8_eexist_as_file_discharges_fa5736f2ae(corpus: Any, tmp_path: Path) -> None:
    """`fa5736f2ae`'s own repro: `--out-dir` names an existing REGULAR FILE.

    **X-184(b): reddened on the stdout envelope and stderr traceback, never
    on the exit integer alone.** At HEAD `2d19bcb` the real run ALREADY
    exits 1 (an unhandled `FileExistsError` traceback still terminates the
    process with status 1), so an assertion written against
    ``real.returncode == 1`` passes on the broken binary too -- exactly the
    inverted-control shape this cycle exists to end. The two observables
    below are what actually distinguish "refused" from "crashed": a
    parseable, non-empty ``-o json`` envelope, and no traceback on stderr.
    """
    root = tmp_path / "work"
    root.mkdir()
    blocker = root / "blocker.file"
    blocker.write_bytes(b"i am a regular file")
    argv = [str(corpus.path("single_page")), "--out-dir", str(blocker)]
    env, _roots = redirected_environment(tmp_path)

    dry, real = dry_and_real("compress", argv, cwd=root, env=env)

    # The exit code, recorded but explicitly NOT the control.
    assert dry.returncode == real.returncode == 1

    # THE CONTROL: the stdout envelope.
    assert real.stdout.strip() != "", (
        "real stdout was EMPTY under -o json -- this is fa5736f2ae's exact shape "
        "(a machine consumer reading stdout alone would see nothing at all)"
    )
    envelope = real_envelope(real.stdout)
    assert envelope is not None, "real stdout did not parse as JSON"
    assert envelope["error"]["kind"] == "failure"
    assert envelope["error"]["code"] == 1

    # THE OTHER CONTROL: no traceback, no FileExistsError, on stderr.
    assert "Traceback (most recent call last)" not in real.stderr, real.stderr
    assert "FileExistsError" not in real.stderr, real.stderr

    dry_detail = prediction(dry.stdout)
    assert dry_detail["would_exit"] == 1
    assert dry_detail["would_refuse"]["kind"] == "failure"

    assert blocker.read_bytes() == b"i am a regular file"


@pytest.mark.e2e
def test_ac8_enametoolong_a_path_component_exceeds_the_filesystem_limit(
    corpus: Any, tmp_path: Path
) -> None:
    root = tmp_path / "work"
    root.mkdir()
    try:
        limit = os.pathconf(str(root), "PC_NAME_MAX")
    except (OSError, ValueError, AttributeError):  # pragma: no cover - platform-dependent
        pytest.skip("PC_NAME_MAX is not available on this platform")
    too_long = "x" * (limit + 1)
    argv = [str(corpus.path("single_page")), "--out-dir", str(root / too_long)]
    env, _roots = redirected_environment(tmp_path)

    dry, real = dry_and_real("compress", argv, cwd=root, env=env)
    assert prediction(dry.stdout)["would_exit"] == 1
    assert real.returncode == 1, real.stdout + real.stderr
    envelope = real_envelope(real.stdout)
    assert envelope is not None
    assert "Traceback (most recent call last)" not in real.stderr
    assert list(root.iterdir()) == [], "neither run may have created anything under root"


def test_ac8_erofs_is_skipped_with_a_stated_reason_never_silently_absent() -> None:
    """§D4's errno table names `EROFS` as **not producible without root**
    (X-153's own rule: a skip must be *observed* skipping, never quietly
    absent). This host does not mount an unprivileged read-only filesystem
    this suite can target, so the arm is recorded here as a stated skip
    rather than omitted from the file -- a reader grepping this module for
    every §D4 errno finds all five named, one of them explicitly not
    attempted rather than silently missing. `ci.yml:140`'s
    `assert_skips --expect-zero` on the main leg is why this is its own
    zero-assertion test rather than a `pytest.skip()` folded into another
    arm: it must never fire in CI, and a bare `pytest.skip()` inside a
    parametrized case would have been indistinguishable from one that does.
    """
    pytest.skip(
        "EROFS is not producible without root or a dedicated read-only mount on this "
        "host (PDF-18 Design D4 / X-153); the real mkdir's guard still wraps any "
        "OSError uniformly, EROFS included -- this arm is a documented gap in "
        "reproducibility, not in coverage."
    )


# --------------------------------------------------------------------------- #
# AC10 -- `--dry-run` purity over the U tier, cited rather than re-derived.
# `tests/integration/test_purity_primitive.py` already proves the snapshot
# comparator itself can fail (its own six negative controls); this is the
# positive arm, over the specific tier this spec adds.
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
def test_ac10_dry_run_purity_over_the_u_tier(corpus: Any, tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    argv, out_dir = _out_dir_argv("compress", corpus, root)
    env, roots = redirected_environment(tmp_path)
    root.chmod(0o500)
    try:
        _skip_if_root_ignores_mode_bits(root)
        before = snapshot(root, *roots)
        dry = run_cli("compress", "--dry-run", *argv, "-o", "json", cwd=root, env=env)
        after = snapshot(root, *roots)
    finally:
        root.chmod(0o700)
    assert prediction(dry.stdout)["would_exit"] == 1
    assert_unchanged(before, after)
    assert not out_dir.exists()


# --------------------------------------------------------------------------- #
# AC11 -- `--force` does not override the U tier. Force overrides SAFETY
# refusals (exit 5); it may never override a filesystem that structurally
# cannot accept the write.
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
@pytest.mark.parametrize("verb", VERBS)
def test_ac11_force_does_not_override_the_unwritable_parent_tier(
    verb: str, corpus: Any, tmp_path: Path
) -> None:
    root = tmp_path / "work"
    root.mkdir()
    argv, out_dir = _out_dir_argv(verb, corpus, root)
    env, _roots = redirected_environment(tmp_path)
    root.chmod(0o500)
    try:
        _skip_if_root_ignores_mode_bits(root)
        dry, real = dry_and_real(verb, [*argv, "--force", "-y"], cwd=root, env=env)
    finally:
        root.chmod(0o700)
    assert prediction(dry.stdout)["would_exit"] == 1, f"{verb}: --force masked the U tier in dry"
    assert real.returncode == 1, f"{verb}: --force masked the U tier for real: {real.stderr}"
    assert dry.returncode == real.returncode == 1
    assert not out_dir.exists()


# --------------------------------------------------------------------------- #
# AC15 -- batch integrity. A REAL multi-target run over an unwritable parent
# writes ZERO output files, on a verb whose fixture yields >= 3 targets.
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
@pytest.mark.parametrize("verb", ["split", "rasterize"])
def test_ac15_a_real_multi_target_run_writes_nothing_under_an_unwritable_parent(
    verb: str, corpus: Any, tmp_path: Path
) -> None:
    root = tmp_path / "work"
    root.mkdir()
    source = corpus.path("ten_page_text")
    out_dir = root / "parts"
    if verb == "split":
        args = [str(source), "--each-page", "--out-dir", str(out_dir)]
    else:
        args = [str(source), "--out-dir", str(out_dir)]
    env, roots = redirected_environment(tmp_path)
    root.chmod(0o500)
    try:
        _skip_if_root_ignores_mode_bits(root)
        before = snapshot(root, *roots)
        real = run_cli(verb, *args, "-o", "json", cwd=root, env=env)
        after = snapshot(root, *roots)
    finally:
        root.chmod(0o700)

    assert real.returncode == 1, real.stdout + real.stderr
    assert not out_dir.exists()
    assert_unchanged(before, after)
    envelope = real_envelope(real.stdout)
    assert envelope is not None
    assert "Traceback (most recent call last)" not in real.stderr


def test_ac15_the_fixture_actually_yields_at_least_three_targets(
    corpus: Any, tmp_path: Path
) -> None:
    """Non-vacuity for AC15: the assertion above is meaningless if the
    fixture happens to yield fewer than three parts."""
    data = json.loads(
        run_cli(
            "split",
            "--dry-run",
            str(corpus.path("ten_page_text")),
            "--each-page",
            "--out-dir",
            str(tmp_path / "count-only"),
            "-o",
            "json",
        ).stdout
    )
    assert len(data["items"]) >= 3, data


# --------------------------------------------------------------------------- #
# PDF-64 -- the dry run crashed on a relative, not-yet-existing `--out-dir`
# with a raw `ValueError` (0 bytes stdout, rc 1) on every one of the eleven
# verbs in `VERBS`, while the identical argv without `--dry-run` succeeded
# (rc 0) on all eleven (E1). AC3/AC5-AC8/AC9/AC12/AC14/AC18/AC20/AC21.
#
# Every cell here drives a BARE RELATIVE `--out-dir` name with `cwd` set to
# its parent -- no `tmp_path`-rooted absolute spelling anywhere in this
# block (AC20: an absolute spelling is exactly what let 4,450 tests stay
# green over a two-command reproduction, E4). Built from `_out_dir_argv`'s
# own registered invocation with only the `--out-dir` VALUE rewritten to
# its bare relative component (`out_dir.name`) -- `_out_dir_argv` itself is
# not modified (Design D4); its own `parent == root` guard has already run
# against the absolute form before the relative spelling is derived.
# --------------------------------------------------------------------------- #


def _relative_argv(argv: list[str], absolute_out_dir: Path) -> tuple[list[str], str]:
    """*argv* with its `--out-dir` value rewritten to the bare relative
    component of *absolute_out_dir* -- the value, not the flag, changes."""
    name = absolute_out_dir.name
    index = argv.index("--out-dir")
    return [*argv[: index + 1], name, *argv[index + 2 :]], name


def _assert_engine_gated_refusal(dry_stdout: str, real_stdout: str, verb: str, cell: str) -> None:
    """`convert`, `soffice` absent (Design D6): the engine-presence tier
    refuses BEFORE the filesystem tier's own success would be observable,
    in both modes, with the top-level `{"error": {...}}` shape rather than
    an `items` envelope -- asserted on shape, never the exit integer alone.
    """
    dry_error = json.loads(dry_stdout)["error"]
    real_error = json.loads(real_stdout)["error"]
    assert dry_error["kind"] == real_error["kind"] == "engine_missing", (
        f"{verb} {cell} cell (soffice absent): dry {dry_error} real {real_error}"
    )


@pytest.mark.e2e
@pytest.mark.parametrize("verb", VERBS)
def test_pdf64_a_relative_not_yet_existing_out_dir_is_predicted_not_raised(
    verb: str, corpus: Any, tmp_path: Path
) -> None:
    """AC5/AC6/AC8/AC12/AC20/AC21 -- the ordinary relative cell, dry and
    real driven together. **RED, free, pre-fix, on all eleven verbs:** rc
    1, zero bytes of stdout, a raw `ValueError` traceback on stderr.
    """
    env, _roots = redirected_environment(tmp_path)
    root = tmp_path / "ordinary"
    root.mkdir()
    argv, absolute_out_dir = _out_dir_argv(verb, corpus, root)
    relative_argv, name = _relative_argv(argv, absolute_out_dir)
    out_dir = root / name
    expected = _C_CELL_EXPECTED.get(verb, 0)

    dry, real = dry_and_real(verb, relative_argv, cwd=root, env=env)

    # AC8 -- no traceback, on stdout or stderr, and a non-empty envelope.
    combined = dry.stdout + dry.stderr
    assert "Traceback (most recent call last)" not in combined, (
        f"{verb}: a traceback reached the user -- {dry.stderr}"
    )
    assert "ValueError" not in combined, f"{verb}: a ValueError leaked -- {dry.stderr}"
    assert dry.stdout.strip() != "", (
        f"{verb}: the dry run produced NO STDOUT under -o json -- {dry.stderr}"
    )

    # AC5 -- the dry run agrees with the real run's own code.
    assert dry.returncode == expected, (
        f"{verb}: dry run exited {dry.returncode}, expected {expected} -- {dry.stdout}{dry.stderr}"
    )
    assert real.returncode == expected, (
        f"{verb}: real run exited {real.returncode}, expected {expected} -- "
        f"{real.stdout}{real.stderr}"
    )

    if expected != 0:
        # `convert`, soffice absent (D6): the engine tier, not the
        # filesystem tier, is what refuses -- asserted on shape.
        _assert_engine_gated_refusal(dry.stdout, real.stdout, verb, "ordinary")
        return

    # AC6 -- both X-185 observables agree: the exit code AND the structured
    # prediction, including the RELATIVE spelling of `output` (E7).
    dry_item = json.loads(dry.stdout)["items"][0]
    real_item = json.loads(real.stdout)["items"][0]
    assert dry_item["ok"] is True, f"{verb}: predicted ok={dry_item['ok']!r}"
    assert dry_item["exit_code"] == 0
    assert dry_item["detail"]["would_exit"] == 0, f"{verb}: {dry_item['detail']}"
    assert dry_item["output"] == real_item["output"], (
        f"{verb}: dry output {dry_item['output']!r} != real output {real_item['output']!r}"
    )
    # `tables` (AC13's own exception, `single_page`: zero detections) never
    # populates `output` at all -- guarded rather than asserted blindly, so
    # this arm still pins the RELATIVE spelling for every verb that does.
    if dry_item["output"] is not None:
        assert not Path(dry_item["output"]).is_absolute(), (
            f"{verb}: the predicted output was absolutized -- {dry_item['output']!r} -- "
            "the user's own relative spelling must survive (E7/D2)"
        )

    # AC12 -- the real run actually created the directory.
    assert out_dir.is_dir(), f"{verb}: the real run must have created {out_dir}"


@pytest.mark.e2e
@pytest.mark.parametrize("verb", VERBS)
def test_pdf64_the_two_cells_that_were_already_correct_do_not_move(
    verb: str, corpus: Any, tmp_path: Path
) -> None:
    """AC7 -- relative+existing and absolute+absent, spelled the SAME way
    this spec's own ordinary cell is spelled, must answer exactly as they
    did before this fix (E1's own third and fourth rows). **RED:** an
    over-eager absolutization that changed the real run's `output` spelling
    would leave these cells' own exit codes green while the spelling moved
    -- caught here by round-tripping through the SAME assertions the
    ordinary cell above uses.
    """
    env, _roots = redirected_environment(tmp_path)
    expected = _C_CELL_EXPECTED.get(verb, 0)

    # -- relative, ALREADY EXISTING -------------------------------------- #
    existing_root = tmp_path / "existing"
    existing_root.mkdir()
    e_argv, e_absolute_out_dir = _out_dir_argv(verb, corpus, existing_root)
    e_relative_argv, e_name = _relative_argv(e_argv, e_absolute_out_dir)
    (existing_root / e_name).mkdir()

    e_dry, e_real = dry_and_real(verb, e_relative_argv, cwd=existing_root, env=env)
    assert e_dry.returncode == expected, f"{verb}: relative-existing dry moved -- {e_dry.stdout}"
    assert e_real.returncode == expected, f"{verb}: relative-existing real moved -- {e_real.stdout}"
    if expected == 0:
        e_detail = prediction(e_dry.stdout, context=f"{verb} relative-existing")
        assert e_detail["would_exit"] == 0, f"{verb}: relative-existing {e_detail}"
    else:
        _assert_engine_gated_refusal(e_dry.stdout, e_real.stdout, verb, "relative-existing")

    # -- ABSOLUTE, absent -------------------------------------------------- #
    absolute_root = tmp_path / "absolute"
    absolute_root.mkdir()
    a_argv, _a_out_dir = _out_dir_argv(verb, corpus, absolute_root)
    a_dry, a_real = dry_and_real(verb, a_argv, cwd=absolute_root, env=env)
    assert a_dry.returncode == expected, f"{verb}: absolute-absent dry moved -- {a_dry.stdout}"
    assert a_real.returncode == expected, f"{verb}: absolute-absent real moved -- {a_real.stdout}"
    if expected == 0:
        a_detail = prediction(a_dry.stdout, context=f"{verb} absolute-absent")
        assert a_detail["would_exit"] == 0, f"{verb}: absolute-absent {a_detail}"
    else:
        _assert_engine_gated_refusal(a_dry.stdout, a_real.stdout, verb, "absolute-absent")


@pytest.mark.e2e
@pytest.mark.parametrize("verb", VERBS)
def test_pdf64_dry_run_purity_holds_for_a_relative_out_dir(
    verb: str, corpus: Any, tmp_path: Path
) -> None:
    """AC14 -- driven ALONE, never paired with the real run that would
    create the directory: after the dry run, the parent is byte-identical
    and the `--out-dir` itself still does not exist (`os.path.lexists`,
    never a bare `.exists()` -- AC14's own instrument choice, because
    `.exists()` on a too-long relative component would itself raise, see
    the sibling test below for that cell).
    """
    env, roots = redirected_environment(tmp_path)
    root = tmp_path / "purity"
    root.mkdir()
    argv, absolute_out_dir = _out_dir_argv(verb, corpus, root)
    relative_argv, name = _relative_argv(argv, absolute_out_dir)
    out_dir = root / name

    before = snapshot(root, *roots)
    dry = run_cli(verb, "--dry-run", *relative_argv, "-o", "json", cwd=root, env=env)
    after = snapshot(root, *roots)

    expected = _C_CELL_EXPECTED.get(verb, 0)
    assert dry.returncode == expected, (
        f"{verb}: purity-cell dry run moved -- {dry.stdout}{dry.stderr}"
    )
    assert_unchanged(before, after)
    assert not os.path.lexists(out_dir), (
        f"{verb}: --out-dir came to exist after a --dry-run alone -- {out_dir}"
    )


# --------------------------------------------------------------------------- #
# AC9/AC11/AC18 -- the discriminator: a relative, not-yet-existing
# `--out-dir` whose SOLE component exceeds `PC_NAME_MAX`. Verb-independent
# (the tier this spec touches has no verb-specific logic at all), driven on
# ONE verb only -- `compress`, beside the existing ABSOLUTE arm at :385,
# never a parametrized sweep (Design D4).
# --------------------------------------------------------------------------- #


@pytest.mark.e2e
def test_pdf64_enametoolong_relative_out_dir_is_predicted_not_raised(
    corpus: Any, tmp_path: Path
) -> None:
    """AC9 -- the discriminator that separates a CORRECTED prediction from
    a SILENCED one (E6). **RED, free, pre-fix:** the identical `ValueError`
    the ordinary cell raises, because the crash happens computing
    `remainder` on the FIRST statement of the length check, before the
    length loop itself ever runs -- so a naive `except ValueError: return`
    swallow (the AC10 mutant) would make this cell predict `would_exit: 0`
    on an argv whose real run refuses with `1`.
    """
    root = tmp_path / "work"
    root.mkdir()
    try:
        limit = os.pathconf(str(root), "PC_NAME_MAX")
    except (OSError, ValueError, AttributeError):  # pragma: no cover - platform-dependent
        pytest.skip("PC_NAME_MAX is not available on this platform")
    too_long = "x" * (limit + 1)
    env, _roots = redirected_environment(tmp_path)

    dry, real = dry_and_real(
        "compress", [str(corpus.path("single_page")), "--out-dir", too_long], cwd=root, env=env
    )

    combined = dry.stdout + dry.stderr
    assert "Traceback (most recent call last)" not in combined, dry.stderr
    assert "ValueError" not in combined, dry.stderr
    assert dry.stdout.strip() != "", f"dry run produced NO STDOUT -- {dry.stderr}"

    # The real run is the reference: it refuses with 1.
    assert real.returncode == 1, real.stdout + real.stderr

    # AC9 -- the dry run must PREDICT that refusal, not silence it.
    dry_detail = prediction(dry.stdout, context="enametoolong relative")
    assert dry_detail["would_exit"] == 1, f"discriminator not corrected -- {dry_detail}"
    refusal = dry_detail["would_refuse"]
    assert refusal["code"] == 1
    assert refusal["kind"] == "failure"
    assert str(limit) in refusal["message"], refusal["message"]
    assert dry.returncode == 1

    # AC18 -- the user's RELATIVE spelling survives in both message and path,
    # never the absolutized form. This is the mutant that ships green
    # everywhere else (D2): substituting the absolutized value wholesale
    # would still predict `would_exit: 1` correctly but would render the
    # message and `path` with the full absolute prefix instead of the bare
    # relative name the user actually typed.
    assert refusal["path"] == too_long, (
        f"the refusal echoed {refusal['path']!r} instead of the user's own "
        f"spelling {too_long!r} -- the absolutized value leaked into the payload"
    )
    assert str(root) not in refusal["message"], (
        f"the message was absolutized -- {refusal['message']!r} contains {str(root)!r}"
    )

    # AC14 -- nothing was created.
    assert list(root.iterdir()) == [], "neither run may have created anything under root"
