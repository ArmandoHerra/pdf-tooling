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
from registry import OUTPUT_FLAG_INVOCATIONS, discover_verbs, run_cli  # noqa: E402

# --------------------------------------------------------------------------- #
# The population (Design D8) -- derived, asserted non-empty AND non-shrinking.
# --------------------------------------------------------------------------- #

VERBS: Final[tuple[str, ...]] = tuple(
    sorted(verb.name for verb in discover_verbs() if "--out-dir" in verb.consumes)
)

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

    # -- C: parent writable, out-dir absent -> dry == real == 0 (AC9) ----- #
    # Dry and real run SEPARATELY here (not through `dry_and_real`, which
    # returns both only after running both) so Trap 1's absent-then-present
    # existence check can land BETWEEN the two runs, not after both.
    c_root = tmp_path / "cell-c"
    c_root.mkdir()
    c_argv, c_out_dir = _out_dir_argv(verb, corpus, c_root)
    c_dry = run_cli(verb, "--dry-run", *c_argv, "-o", "json", cwd=c_root, env=env)

    c_detail = prediction(c_dry.stdout)
    assert c_detail["would_exit"] == 0, f"{verb} C cell: dry predicted {c_detail}"
    assert not c_out_dir.exists(), "Trap 1: the dry run must leave a non-existent out-dir absent"

    c_real = run_cli(verb, *c_argv, "-o", "json", cwd=c_root, env=env)
    assert c_real.returncode == 0, f"{verb} C cell real run: {c_real.stdout}{c_real.stderr}"
    assert c_dry.returncode == c_real.returncode == 0
    assert c_out_dir.is_dir(), "Trap 1's other half: the real run must have created it"

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
    assert prediction(n_dry.stdout)["would_exit"] == expected_masked, (
        f"{verb} N cell: dry predicted {prediction(n_dry.stdout)}"
    )
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
    assert prediction(m_dry.stdout)["would_exit"] == expected_masked, (
        f"{verb} M cell: dry predicted {prediction(m_dry.stdout)}"
    )
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
    assert prediction(f_dry.stdout)["would_exit"] == 0, (
        f"{verb} F cell: dry predicted {prediction(f_dry.stdout)}"
    )
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
