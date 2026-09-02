"""`PDF-04`'s 21 acceptance criteria, re-derived — `AUDIT-CONVENTION(PDF-17)`.

`PDF-04` is the safety spine: `AtomicWriter`, no-clobber, planned-output
collision detection, `--in-place` + `.bak`, the cross-filesystem degradation
warning, the non-TTY `-y` gate, and the write-chokepoint AST walk. Its roster
row reads `Implemented (2026-08-29)` and **it has never been swept** — all 21
criteria rest on the implementing engineer's self-report. This module is the
evidence for that first grant or refusal, produced by `PDF-19`. The
`qa-sentinel` grants or refuses; this module does not.

**Verdict counts — 17 `holds` · 1 `inverted` · 2 `not-met` · 1 `unmeasured` = 21.**

`ACAudit` has no `verdict` field and `_model.py` is frozen, so `PDF-27`'s
vocabulary is mapped onto the landed fields (declared deviation, per Design
§9.2 / R2), extended by one value this audit needed and `PDF-02`'s did not:

* **`holds`** — MET at the audited HEAD (`7522e3e`) **and** grounded in a
  control this audit drove RED, with the mutation, the failure text and the
  revert recorded in `red`. AC1, AC2, AC3, AC4, AC5, AC6, AC7, AC8, AC9, AC10,
  AC12, AC13, AC14, AC16, AC17, AC18, AC21 — seventeen.
* **`inverted`** — a covering test exists and **cannot fail for the reason it
  claims**. AC11: deleting the entire size + SHA-256 verification from
  `_replace_across_devices` leaves all eight cross-filesystem arms GREEN. The
  arm asserts `"SHA-256" in result.stderr`, which is a string in the *warning
  message* emitted **before** the copy — so it proves the writer ANNOUNCED a
  verification, never that it performed one. §D2 named this outcome in advance.
* **`not-met`** — the criterion is not satisfied at the audited HEAD. AC15
  (the walk is structurally blind to §D7 row 2's positional spelling) and AC20
  (`85dd844`'s logical change is described by no `changelog.md` entry, which
  `PDF-04`'s own log calls *"owed and not written"*).
* **`unmeasured`** — `red_kind=NOT_OBSERVED` plus a finding. AC19: `TESTING.md`'s
  arms section is mechanised by three greps and nothing executes them.
  `tests/test_docs_antirot.py` guards `TESTING.md`'s **make-target** claims only
  (`DOCS_WITH_COMMANDS`, `:32`); every content claim in it is unguarded, and
  widening that list is `PDF-30`'s (X-154). Filing it beats writing an assertion
  that would pass — `0615feae63` is the precedent.

**Every `red` below was applied inside a `git worktree` under `$TMPDIR`, never
in `apps/pdf-toolkit` (§D12 / HC-4 — `git stash` is never used).** Each was
reverted with `git show HEAD:<path> > <path>` and `git -C <scratch> status
--porcelain` confirmed empty before the next mutation. **X-210's hazard was
confirmed live and pinned:** a scratch tree run without `PYTHONPATH` pointed at
its own `src/` imports the REAL repository source through the venv's
`_editable_impl_pdf_toolkit.pth`, so every planted mutation would have been a
silent no-op reading green. Every run below carries `PYTHONPATH=<scratch>/src`,
and each mutation was proven present in the scratch file before its arm ran.

**Findings are reported to the `project-manager`, not filed here.** The wave-3
brief makes `qa/FINDINGS-LEDGER.md` read-only to this spec, so each `finding`
below carries a `PENDING-LEDGER:` slug in the convention `audit_pdf_03.py` and
`audit_pdf_06.py` established; the evidence for each is in `PDF-19`'s engineer
report for the `qa-sentinel` to fingerprint. Rows citing an EXISTING fingerprint
(`74861772f5`, `b408baff4a`, `ba07fdfb56`) name it directly.

**Three §D2 pointers no longer resolve at HEAD, and that is a `PDF-18`
consequence recorded rather than a defect filed against `PDF-04`** (§D10):
`atomic.py`'s checkpoint call sites moved `:518/:532/:535` → `:715/:729/:732`,
`os.replace` moved `:582` → `:779`, and AC21's prescribed whole-file oracle
(`git show d777dd8:src/pdf_toolkit/safety/atomic.py`) **cannot be used at all** —
eight `ops/` modules now import `plan_filesystem` from that module, so the
pre-X-67 file dies at import with `ImportError: cannot import name
'plan_filesystem'` and every arm would red for the wrong reason. AC21's row
records the targeted re-derivation used instead.
"""

from __future__ import annotations

from typing import Final

from acceptance._model import ACAudit, RedKind

SPEC_ID: Final[str] = "PDF-04"
AC_COUNT: Final[int] = 21

AUDIT: Final[tuple[ACAudit, ...]] = (
    ACAudit(
        ac="AC1",
        claim=(
            "safety/ contains __init__.py, policy.py, atomic.py, paths.py, tempnames.py, "
            "confirm.py, _faults.py. python -c 'from pdf_toolkit.safety import AtomicWriter, "
            "SafetyPolicy, require_confirmation, check_output_collisions, canonical, "
            "TEMP_PREFIX, is_toolkit_temp, find_stray_temps' exits 0."
        ),
        covering=(
            "tests/unit/test_tempnames.py::test_the_prefix_is_hidden_and_product_specific",
            "tests/unit/test_tempnames.py::test_find_stray_temps_reports_and_never_sweeps",
            "tests/integration/test_atomic_crash.py::test_every_declared_fault_point_is_reachable",
        ),
        red=(
            "Deleted `find_stray_temps` from safety/__init__.py's import line and from its "
            "`__all__` in the scratch worktree. Both files failed at COLLECTION: "
            "`ImportError: cannot import name 'find_stray_temps' from 'pdf_toolkit.safety'`, "
            "raised through tests/atomic_harness.py:51. Reverted with git show HEAD:; scratch "
            "status --porcelain empty; re-ran green. MEASURED, not transcribed: the AC1 import "
            "command was re-run verbatim at 7522e3e and exits 0.\\n"
            "HALF-MEASURED, and recorded as such. The IMPORT-SMOKE half is covered -- every one "
            "of the eight names is imported from `pdf_toolkit.safety` by at least one test "
            "module, so deleting any export reds collection. The MODULE-INVENTORY half is "
            "covered by nothing and is now STALE: `safety/naming.py` exists (added by PDF-07, "
            "`743853f`, per X-70) and appears in NEITHER AC1's seven-module list NOR "
            "`safety/__init__.py`'s own module inventory docstring (`:12-26`) NOR its `__all__` "
            "(`:51-67`), while seven `ops/` modules import `render_name` from it. AC1's literal "
            "text says `contains`, not `contains only`, so the criterion is MET -- but nothing "
            "would notice if a module were added or removed tomorrow."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-04-ac1-safety-module-inventory-is-unmechanised-and-stale",
    ),
    ACAudit(
        ac="AC2",
        claim=(
            "Writing to an existing target without --force exits 5 and the target's SHA-256 is "
            "unchanged. With --force the same run exits 0 and the target holds the new bytes."
        ),
        covering=(
            "tests/unit/test_safety_paths.py::test_an_existing_target_is_refused_without_force",
            "tests/unit/test_safety_paths.py::test_force_and_in_place_both_suppress_the_clobber_check",
            "tests/unit/test_atomic_writer.py::test_an_existing_target_is_refused_and_left_byte_identical",
            "tests/unit/test_atomic_writer.py::test_force_overwrites_with_the_new_bytes",
            "tests/unit/test_atomic_writer.py::test_the_harness_returns_5_for_an_existing_target",
            "tests/test_cli_contract.py::test_c11_no_clobber_exits_5[delete]",
        ),
        red=(
            "TWO mutations, one per direction, both in safety/paths.py in the scratch worktree. "
            "(a) Neutered the refusal -- `if False and (canonical(target).exists() or "
            "os.path.lexists(written)):` -- and `test_an_existing_target_is_refused_without_force` "
            "failed with `Failed: DID NOT RAISE TargetExistsError` (test_safety_paths.py:161). "
            "(b) Made --force stop suppressing -- `if force or in_place:` -> `if in_place:` -- and "
            "`test_force_overwrites_with_the_new_bytes` failed with "
            "`pdf_toolkit.errors.TargetExistsError: .../doc.pdf exists; pass --force to overwrite "
            "it` raised from paths.py:160. Each reverted with git show HEAD:; scratch clean.\\n"
            "RECORDED because it says something real about the arms: under mutation (a) the two "
            "AtomicWriter-level arms PASSED. `_recheck_no_clobber` (atomic.py:761) is an "
            "INDEPENDENT implementation of the same refusal -- OR-1's narrowed-TOCTOU second half "
            "-- so the writer still exits 5, with a different message ('appeared while the write "
            "was in flight') and only after the temp has been written. The behaviour AC2 asserts "
            "holds through either tier; no arm distinguishes which one answered."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC3",
        claim=(
            "Two planned outputs resolving to one destination exit 5 before any write, including "
            "an alias-shaped case (two paths differing only through a symlinked parent) and a "
            "hardlink-shaped case (two distinct paths, one inode)."
        ),
        covering=(
            "tests/unit/test_safety_paths.py::test_an_alias_shaped_collision_is_detected",
            "tests/unit/test_safety_paths.py::test_a_hardlink_shaped_collision_is_detected",
            "tests/unit/test_safety_paths.py::test_canonical_resolves_a_symlinked_parent",
            "tests/unit/test_safety_paths.py::test_two_names_for_one_inode_are_one_destination",
            "tests/unit/test_atomic_writer.py::test_the_harness_returns_5_for_a_planned_output_collision",
        ),
        red=(
            "TWO mutations, and the point is that they are INDEPENDENT -- one mutation reddening "
            "both arms would mean the two aliasing mechanisms are not separately covered. "
            "(a) `canonical()` -> `Path(path).expanduser().absolute()`, the MHC-81 defect "
            "verbatim: the ALIAS arm failed (`Failed: DID NOT RAISE OutputCollisionError`, "
            "test_safety_paths.py:80) together with `test_canonical_resolves_a_symlinked_parent` "
            "and the harness collision arm -- 3 failed, 1 passed -- and the HARDLINK arm stayed "
            "GREEN. (b) `identity_key` reduced to `return ('path', str(resolved))`, dropping "
            "`(st_dev, st_ino)`: the HARDLINK arm failed (`Failed: DID NOT RAISE "
            "OutputCollisionError`, test_safety_paths.py:90) and the ALIAS arm stayed GREEN. "
            "Independence proven in both directions. Each reverted with git show HEAD:; scratch "
            "status --porcelain empty after each."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC4",
        claim=(
            "Refusal messages and result payloads echo the path exactly as it was passed in, "
            "never the canonicalized form."
        ),
        covering=(
            "tests/unit/test_safety_paths.py::test_a_collision_message_echoes_both_paths_as_written",
            "tests/unit/test_safety_paths.py::test_containment_refusal_echoes_the_path_as_written",
            "tests/unit/test_safety_paths.py::test_writability_messages_echo_the_path_as_written",
        ),
        red=(
            "Echoed `canonical(p)` at all three refusal sites in safety/paths.py "
            "(check_output_collisions, ensure_within, ensure_destination_writable). All three "
            "arms failed, each naming the spelling that vanished: "
            "`assert '.../alias/doc.pdf' in 'two planned outputs resolve to one destination: "
            ".../real/doc.pdf and .../real/doc.pdf'`; "
            "`assert '.../out/../escaped.pdf' in 'the resolved output .../escaped.pdf escapes "
            "the output directory .../out'`; and `assert './out' in 'destination directory does "
            "not exist: .../resolved'` -- the last one the relative-path case, which is the one a "
            "user actually types. Reverted with git show HEAD:; scratch clean; re-ran green."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC5",
        claim=(
            "tests/fs_snapshot.py diff() detects all six planted mutations, each proven by a "
            "negative control: added, removed, content-with-mtime-restored, mtime-with-identical-"
            "content, os.replace-with-identical-content (inode), st_mode. A snapshot compared "
            "against itself yields zero differences."
        ),
        covering=(
            "tests/integration/test_purity_primitive.py::test_control_one_an_added_file_is_detected",
            "tests/integration/test_purity_primitive.py::test_control_five_a_replacement_with_identical_content_is_detected",
            "tests/integration/test_purity_primitive.py::test_control_six_a_mode_change_is_detected",
            "tests/integration/test_purity_primitive.py::test_a_snapshot_compared_against_itself_reports_nothing",
            "tests/integration/test_purity_primitive.py::test_every_named_negative_control_exists",
            "tests/integration/test_purity_primitive.py::test_both_docstrings_quote_the_measured_control_count",
        ),
        red=(
            "Re-running nine passing controls only proves they still pass, so each COMPARATOR "
            "DIMENSION was ablated in the scratch worktree and the control that depends on it "
            "confirmed to go blind (§D3). Removing `('ino','inode')` from `_FIELDS`: exactly ONE "
            "of nineteen arms failed -- `test_control_five_...` with `AssertionError: assert "
            "'inode' in set()` -- 1 failed, 18 passed. Stopping `_walk` yielding directories: "
            "`test_a_create_then_delete_...` failed with `AssertionError: []`. Removing "
            "`('mtime_ns','mtime')`: `test_control_four_...` AND the create-then-delete arm "
            "failed. ADDING an `atime` field to `Entry`/`_FIELDS`: EIGHT arms failed -- the atime "
            "exclusion control plus five legitimate dry-run purity arms plus two fault-hook arms "
            "-- proving the exclusion is a decision rather than laziness. Removing "
            "`('mode','mode')`: `test_control_six_...` failed with `assert 'mode' in set()` under "
            "BOTH `umask 022` and `umask 002`, so `85dd844`'s umask-independence fix holds. Every "
            "ablation reverted with git show HEAD:; scratch status --porcelain empty.\\n"
            "COUNT CORRECTED AT SOURCE: the criterion says six and the file carries NINE negative "
            "controls (the six named `control_one`..`control_six`, plus create-then-delete caught "
            "only by directory mtime, symlink retarget, and `assert_unchanged` naming every "
            "difference). Both instrument docstrings said 'six' from PDF-04's landing until this "
            "audit; X-171 records the cost of a brief inheriting that undercount. Corrected in "
            "tests/fs_snapshot.py and tests/integration/test_purity_primitive.py, and the number "
            "is now MECHANISED rather than written down."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC6",
        claim=(
            "assert_pure() wraps a --dry-run invocation of tests/atomic_harness.py with TMPDIR "
            "and HOME redirected into tmp_path and reports zero differences across every root; "
            "the same invocation WITHOUT --dry-run produces a non-empty diff."
        ),
        covering=(
            "tests/integration/test_purity_primitive.py::test_a_dry_run_touches_nothing_anywhere",
            "tests/integration/test_purity_primitive.py::test_the_same_invocation_without_dry_run_changes_the_tree",
            "tests/integration/test_purity_primitive.py::test_a_dry_run_over_an_existing_target_is_still_pure",
            "tests/integration/test_purity_primitive.py::test_a_home_write_is_invisible_without_redirection_and_caught_with_it",
        ),
        red=(
            "(a) Made the harness's DRY-RUN path write one byte "
            "(`Path(str(target) + '.dryrun-leak').write_bytes(b'x')`): two purity arms failed with "
            "`AssertionError: 2 filesystem difference(s) across 3 root(s); a pure run makes none: "
            "- .../work/doc.pdf.dryrun-leak: added - .../work: mtime ... -> ...`.\\n"
            "(b) §D2's PRESCRIBED live-guard mutation DID NOT RED, and that is a correction to the "
            "catalogue rather than a defect. Disabling only the harness's own "
            "`open(writer.path,'wb')` leaves `AtomicWriter` still creating the temp and "
            "`os.replace`-ing an EMPTY file onto the destination, so `doc.pdf: added` still fires "
            "and both arms passed. Re-derived: making the whole non-dry-run invocation a no-op "
            "(return before entering the writer) reds the guard with its OWN message -- "
            "`AssertionError: the non-dry-run control produced no differences -- a dead guard`. "
            "The guard is alive and now provably so, for the reason it claims.\\n"
            "(c) `redirected_environment()` proven load-bearing, both halves, entirely inside "
            "tmp_path: a child writing one byte into its `$HOME` is INVISIBLE to a snapshot scoped "
            "to the working tree and CAUGHT once the redirected roots are included. Landed as "
            "`test_a_home_write_is_invisible_without_redirection_and_caught_with_it`. All "
            "mutations reverted with git show HEAD:; scratch clean."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC7",
        claim=(
            "During a live write the temp file's parent is canonical(target).parent -- not "
            "tempfile.gettempdir() -- and its name starts with .pdftoolkit-; asserted by reading "
            "the path from the fault-hook rendezvous while the writer is parked mid-write."
        ),
        covering=(
            "tests/integration/test_atomic_crash.py::test_the_live_temp_sits_beside_the_destination",
            "tests/unit/test_atomic_writer.py::test_the_temp_lives_beside_the_destination_and_carries_the_prefix",
            "tests/unit/test_atomic_writer.py::test_a_symlinked_parent_still_puts_the_temp_beside_the_real_file",
        ),
        red=(
            "Dropped the co-location from `_open_temp` (atomic.py:706, moved from §D2's recorded "
            ":511 by PDF-18): `directory = self._temp_dir if self._temp_dir is not None else "
            "None`, "
            "so NamedTemporaryFile falls back to gettempdir(). All THREE arms failed, including "
            "the one that reads the path out of the live rendezvous: `AssertionError: assert "
            "PosixPath('/tmp') == PosixPath('.../sub')` and `assert PosixPath('/tmp') == "
            "PosixPath('.../real')` where `PosixPath('/tmp/.pdftoolkit-_qyeouq0').parent`. "
            "Reverted with git show HEAD:; scratch clean; re-ran green."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC8",
        claim=(
            "A real SIGKILL delivered to a child provably parked at after_temp_create, "
            "after_fsync and after_backup leaves the original byte-identical (SHA-256 + size) in "
            "all three cases, for both a fresh target and --in-place. No mock, no sleep, no "
            "polling."
        ),
        covering=(
            "tests/integration/test_atomic_crash.py::test_a_kill_never_creates_a_fresh_target[after_fsync]",
            "tests/integration/test_atomic_crash.py::test_a_kill_leaves_an_in_place_target_byte_identical[after_fsync]",
            "tests/integration/test_atomic_crash.py::test_a_kill_leaves_an_in_place_target_byte_identical[after_backup]",
            "tests/integration/test_atomic_crash.py::test_every_declared_fault_point_is_reachable",
            "tests/integration/test_atomic_crash.py::test_every_checkpoint_call_site_is_a_declared_fault_point",
            "tests/integration/test_atomic_crash.py::test_every_fault_point_precedes_the_replace",
        ),
        red=(
            "The kill is real and uncatchable; the vacuity risk is WHERE the child was when it "
            "arrived. Two mutations settle it (§D4). (1) `os.replace` hoisted ABOVE the "
            "after_fsync checkpoint in `_commit`: FOUR arms failed, and the in-place arms failed "
            "with the ORIGINAL'S SHA-256 CHANGED -- `assert '26d85e401ff4...33690ca1' == "
            "'b5b6b8f37820...09a239'` -- proving the arms observe the DESTINATION and not merely "
            "the absence of a fresh file. (`b5b6b8f378207bb265d91bbaa7ebf2fa910b438d65f9a23240a7f"
            "80df009a239` is byte-identical to the digest PDF-04's own Implementation Log "
            "recorded, so the fixture constant is unchanged.) (2) `checkpoint()` made a no-op: "
            "THREE arms failed in ~1 s with `AssertionError: the child exited (code 0) before "
            "reaching the fault point` -- NOT the 30 s rendezvous timeout §D2/§D4 predicted, and "
            "better than predicted: `park_at` detects a child that ran to completion instead of "
            "waiting for one that never parks. The arms are not green on a race. (3) A fourth "
            "name added to `FAULT_POINTS` reds `test_every_declared_fault_point_is_reachable`. "
            "The CONVERSE had no control and now does: a `checkpoint('after_flush')` the "
            "declaration does not carry reds the two arms appended by PDF-19, and a checkpoint "
            "moved after the commit reds `test_every_fault_point_precedes_the_replace` with "
            "`assert 735 < 734`. All reverted with git show HEAD:; scratch clean."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC9",
        claim=(
            "With no PDF_TOOLKIT_FAULT_* variables set, safety/_faults.checkpoint() performs no "
            "filesystem or IPC operation and changes no behaviour (asserted under assert_pure), "
            "and uv run bandit -r src/ -c pyproject.toml is clean."
        ),
        covering=(
            "tests/integration/test_purity_primitive.py::test_the_fault_hook_is_inert_with_no_environment_set",
            "tests/integration/test_purity_primitive.py::test_a_non_matching_fault_point_changes_nothing",
        ),
        red=(
            "Made `checkpoint()` write to the path it is handed -- `if detail: "
            "Path(detail).write_text('x')` before the env check. "
            "`test_the_fault_hook_is_inert_with_no_environment_set` failed with `AssertionError: "
            "2 filesystem difference(s) across 1 root(s); a pure run makes none: "
            "- .../work/detail: added - .../work: mtime 0 -> ...`. Reverted with git show HEAD:; "
            "scratch clean. Bandit re-run on the real tree at 7522e3e: `Total issues (by "
            "severity): Undefined 0, Low 0, Medium 0, High 0`.\\n"
            "SCOPE LIMIT, measured rather than assumed. The second arm PASSED under the same "
            "mutation, and it cannot do otherwise: both arms run IN-PROCESS with the real "
            "environment (no `redirected_environment`), and their `assert_pure` root is "
            "`tmp_path/'work'` only -- a directory `checkpoint()` can reach ONLY through the "
            "`detail` argument the first arm happens to pass. A first attempt at this mutation "
            "wrote to `$HOME` instead and was invisible to BOTH arms; it put one byte in the "
            "operator's real home directory, which this audit's own purity discipline caught and "
            "removed. So the inertness control covers a write the hook is POINTED at and not a "
            "write it CHOOSES."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-04-ac9-inertness-control-cannot-see-an-unpointed-write",
    ),
    ACAudit(
        ac="AC10",
        claim=(
            "A --out-dir that is a symlink onto a real second filesystem emits the degradation "
            "warning on stderr, naming both paths and both device ids. The second filesystem "
            "comes from the §D5 ladder; on Linux, failure to obtain one FAILS the test."
        ),
        covering=(
            "tests/integration/test_cross_filesystem.py::test_an_out_dir_symlinked_onto_another_mount_warns_on_stderr",
            "tests/integration/test_cross_filesystem.py::test_a_dry_run_reaches_the_degradation_warning_too",
            "tests/integration/test_cross_filesystem.py::test_the_two_directories_really_are_separate_filesystems",
            "tests/integration/test_cross_filesystem.py::test_a_same_filesystem_destination_warns_about_nothing",
        ),
        red=(
            "Suppressed the C1 emission with an early `return` at the top of "
            "`_warn_if_destination_moved` (atomic.py:693). TWO arms failed -- "
            "`test_an_out_dir_symlinked_onto_another_mount_warns_on_stderr` and "
            "`test_a_dry_run_reaches_the_degradation_warning_too` -- while the two "
            "same-filesystem negative arms and the four EXDEV arms stayed green, so the mutation "
            "is scoped to the condition it targets. Reverted with git show HEAD:; scratch clean; "
            "8 passed.\\n"
            "LADDER RUNG RECORDED, not assumed: the fixture printed `[PDF-04] second filesystem "
            "from ladder rung 2 (/dev/shm): /dev/shm` on every one of the six arms that take it, "
            "device 27 against /tmp's 66308. ZERO SKIPS on this Linux host, which is the "
            "combination §D5 requires (a Linux run that skipped this arm is a failure, not a "
            "skip). The non-vacuity arm asserts a genuine kernel EXDEV directly, so the pair "
            "cannot pass on one filesystem."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC11",
        claim=(
            "Forcing the temp onto the second filesystem via _temp_dir produces a genuine "
            "OSError(errno.EXDEV) from os.replace; the writer emits the degradation warning and "
            "completes via copy -> fsync -> replace -> size + SHA-256 VERIFY, and the final bytes "
            "equal what was written."
        ),
        covering=(
            "tests/integration/test_cross_filesystem.py::test_a_real_exdev_degrades_and_verifies",
            "tests/integration/test_cross_filesystem.py::test_the_degraded_path_still_refuses_to_clobber",
            "tests/integration/test_cross_filesystem.py::test_the_degraded_path_still_writes_the_sidecar",
        ),
        red=(
            "INVERTED, exactly as §D2 predicted it might be, and the three-mutation sequence is "
            "what establishes it. (1) DELETED the entire size + SHA-256 verification from "
            "`_replace_across_devices` (`if False:` around the FailureError raise, atomic.py:818): "
            "ALL EIGHT cross-filesystem arms stayed GREEN -- `8 passed in 1.92s`. Nothing in the "
            "suite notices that the writer stopped checking. (2) Corrupted the staged copy "
            "(`staged.write(chunk.replace(b'x', b'y', 1))`) WITH the verification present: the arm "
            "failed with `assert 1 == 0` and the captured stderr carried the product's own "
            "`error: the degraded write to .../doc.pdf did not verify: expected 5000 bytes / "
            "c59d3c04...92054, got 5000 bytes / 6622231b...44d915` -- so the PRODUCT's "
            "verification works. (3) Corrupted the copy AND removed the verification: the arm "
            "failed on `assert 'yxxxx...' == 'xxxx...'`, i.e. on the CONTENT comparison.\\n"
            "Taken together: `test_a_real_exdev_degrades_and_verifies` can only fail when the "
            "BYTES differ. Its one assertion about the verification is `'SHA-256' in "
            "result.stderr` -- a string in the WARNING MESSAGE emitted BEFORE the copy runs. It "
            "asserts the writer ANNOUNCED a verification; nothing asserts it performed one. §D2: "
            "'if the arm stays green, AC11 is INVERTED -- it would be asserting that the bytes "
            "match, not that the writer checked.' The degrade-and-verify BEHAVIOUR is correct at "
            "HEAD; the VERIFY clause of the criterion is uncovered. All mutations reverted with "
            "git show HEAD:; scratch status --porcelain empty."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=(
            "PENDING-LEDGER: pdf-04-ac11-exdev-verification-can-be-deleted-with-every-arm-green"
        ),
    ),
    ACAudit(
        ac="AC12",
        claim=(
            "--no-backup without --in-place exits 2 via SafetyPolicy.validate(), wired at the "
            "single named cli call site, with a message naming both flags."
        ),
        covering=(
            "tests/unit/test_atomic_writer.py::test_the_harness_returns_2_for_no_backup_without_in_place",
            "tests/test_cli_contract.py::test_c7_no_backup_alone_exits_2[doctor]",
            "tests/test_cli_contract.py::test_c7_no_backup_alone_exits_2[version]",
        ),
        red=(
            "Made `SafetyPolicy.validate()` a no-op (`return` before the "
            "BackupWithoutInPlaceError raise, policy.py:59). THREE arms failed: the harness arm "
            "(`assert 0 == 2`) and `test_c7_no_backup_alone_exits_2` for `doctor` and `version` "
            "(`assert 0 == 2`, the run completing and emitting its normal envelope). 24 of the 27 "
            "c7 legs still passed, because for the verbs taking a PDF operand a different tier -- "
            "the missing-argument usage error -- answers 2 first and masks the rule under test. "
            "Reverted with git show HEAD:; scratch clean; re-ran green."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC13",
        claim=(
            "--in-place writes <name>.bak BEFORE the replace and the sidecar is byte-identical to "
            "the ORIGINAL; an existing <name>.bak without --force exits 5 leaving both untouched; "
            "--no-backup --in-place writes no sidecar."
        ),
        covering=(
            "tests/unit/test_atomic_writer.py::test_in_place_writes_a_byte_identical_sidecar",
            "tests/unit/test_atomic_writer.py::test_the_sidecar_keeps_the_original_inode_when_linking_is_possible",
            "tests/unit/test_atomic_writer.py::test_an_existing_sidecar_is_refused_and_nothing_moves",
            "tests/unit/test_atomic_writer.py::test_force_replaces_a_stale_sidecar",
            "tests/unit/test_atomic_writer.py::test_no_backup_writes_no_sidecar",
        ),
        red=(
            "Moved `_make_backup()` to AFTER `self._replace(temp)` in `_commit`, so the sidecar "
            "captures the NEW bytes rather than the original. FOUR arms failed, and the decisive "
            "one failed in exactly the way §D2 requires before AC13 can be called covered: "
            "`test_in_place_writes_a_byte_identical_sidecar` reported `AssertionError: assert "
            "b'rewritten' == b'original bytes'`. The arm compares the sidecar to the ORIGINAL, not "
            "to the new content, so AC13 is NOT inverted. The inode arm failed with "
            "`'04d96d8a91ea...682b0' == '52c3935626c1...48698'`. Reverted with git show HEAD:; "
            "scratch clean; re-ran green."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC14",
        claim=(
            "-y gate, six parts: bulk+destructive on a never-written pipe exits 5 within a 10 s "
            "subprocess timeout (a TimeoutExpired fails the test); stderr carries the exact "
            "re-run command ending in ' -y'; the same run with -y proceeds; a single-input "
            "destructive run never refuses on this ground; under a real pty 'n' exits 5 and 'y' "
            "proceeds; under -o json the refusal is the error object on stdout with code 5."
        ),
        covering=(
            "tests/unit/test_confirm.py::test_a_non_terminal_refusal_is_immediate_and_never_blocks",
            "tests/unit/test_confirm.py::test_the_refusal_prints_a_command_that_actually_works",
            "tests/unit/test_confirm.py::test_the_same_run_with_yes_proceeds",
            "tests/unit/test_confirm.py::test_a_single_input_destructive_run_never_refuses_on_this_ground",
            "tests/unit/test_confirm.py::test_declining_on_a_real_terminal_exits_5",
            "tests/unit/test_confirm.py::test_the_json_refusal_is_the_error_object_on_stdout",
            "tests/test_cli_contract.py::test_c13_bulk_destructive_requires_y_on_a_non_tty[compress]",
        ),
        red=(
            "Made the non-TTY branch fall through to the interactive prompt (`if False and not "
            "policy.is_tty:` at confirm.py:117). THREE arms failed and -- this is the part that "
            "has to be OBSERVED rather than assumed -- the red is a TIMEOUT, not an assertion: "
            "`subprocess.TimeoutExpired: Command '[... 'confirm', '--inputs', '3', '--in-place']' "
            "timed out after 10.0 seconds`, twice, plus `OSError: pytest: reading from stdin while "
            "output is captured!` with the prompt `About to run destructively on 3 inputs in "
            "place. Continue? [y/N]` in the captured stderr. 'Must not hang' is genuinely a test "
            "here. The run took 20.4 s, which is two 10 s deadlines expiring as designed. "
            "Reverted with git show HEAD:; scratch clean; re-ran green."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC15",
        claim=(
            "tests/test_import_boundaries.py fails when ANY of the fourteen §D7 call groups "
            "appears under src/ outside the two tiers. Proven three ways: both allowlists empty "
            "and asserted; planted violations in a scratch copy of src/ make the test fail; a "
            "stale allowlist entry makes the test fail. A non-literal mode is a violation."
        ),
        covering=(
            "tests/test_import_boundaries.py::test_a_planted_violation_fails_the_walk[plant-shutil-move-in-ops]",
            "tests/test_import_boundaries.py::test_a_planted_violation_fails_the_walk[plant-os-symlink-in-ops]",
            "tests/test_import_boundaries.py::test_every_d7_call_group_has_a_planted_violation",
            "tests/test_import_boundaries.py::test_a_stale_allowlist_entry_fails",
            "tests/test_import_boundaries.py::test_a_non_literal_mode_is_a_violation",
            "tests/test_import_boundaries.py::test_benign_calls_are_never_flagged",
            "tests/test_import_boundaries.py::test_a_positional_mode_on_path_open_is_a_violation",
        ),
        red=(
            "NOT MET AT HEAD, and the audit found it while building the plants the criterion "
            "asks for. §D7 row 2 -- `.open(...)` (Path.open), MANDATED rather than an extension -- "
            "is structurally invisible to the walk in its idiomatic spelling. "
            "`_WriteCallVisitor._classify_open` reads the mode from `node.args[1]`, which is the "
            "BUILTIN `open`'s positional slot; on a METHOD call the receiver is `node.func.value`, "
            "so `p.open('w')`'s mode sits at `args[0]` and is never inspected. Measured directly "
            "against `scan_write_calls`: `p.open('w')` NOT FLAGGED, `p.open('a')` NOT FLAGGED, "
            "`p.open(m)` (non-literal) NOT FLAGGED, while `p.open(mode='w')` IS flagged "
            "(reason: open() with mutating mode 'w') and `open(p,'w')` IS flagged. The GUARANTEE "
            "holds today -- a regex sweep of src/ for a .open( call taking a mutating mode literal "
            "returns nothing at 7522e3e -- so it is the GUARD that is blind, not the product that "
            "is broken. Landed as a `strict=True` xfail so the gap closes itself loudly: "
            "`test_a_positional_mode_on_path_open_is_a_violation` turns RED the day the visitor "
            "learns to read a method call's mode. Filed, not fixed -- PDF-19 makes no repair to "
            "the mechanism it audits.\\n"
            "THE OTHER THIRTEEN GROUPS NOW RED. PDF-04 shipped five planted violations covering "
            "five of fourteen groups; nine had never been observed to fail. Nine rows were "
            "APPENDED to `PLANTED` (X-15's append rule; no existing row rewritten) and all "
            "fourteen pass `test_a_planted_violation_fails_the_walk`. The coverage claim itself is "
            "now mechanised by `D7_GROUP_PLANTS` + "
            "`test_every_d7_call_group_has_a_planted_violation`, observed RED by renaming one "
            "PLANTED label: `AssertionError: D7_GROUP_PLANTS names labels PLANTED does not carry: "
            "['group 6: plant-shutil-move-in-ops']`. The three inherited controls were "
            "RE-OBSERVED rather than assumed: the stale-allowlist arm reds against a fabricated "
            "entry, the non-literal-mode arm reds, and the false-positive floor still passes "
            "(`str.replace`, `list.remove`, `dict.copy`, `open(p,'rb')`, `p.open()` unflagged). "
            "CENSUS RE-MEASURED at 7522e3e with the walk's own machinery, not a grep: ELEVEN "
            "mutating calls under src/, all eleven inside safety/atomic.py "
            "(:344, :708, :751, :754, :758, :779, :796, :815, :844, :911, :921); tier-1 = 0; "
            "tier-2 outside atomic.py = 0; both allowlists measured empty. Against PDF-04's "
            "recorded EIGHT: `_ensure_out_dir`'s mkdir arrived with PDF-07 (`743853f`) and was "
            "rewritten in place by PDF-18 (`bd015d4`), and the ScratchDir pair (:911, :921) with "
            "PDF-15 (`5bf6e65`). The COUNT is unchanged since PDF-19's spec measured 11 at "
            "`2d19bcb`; every LINE NUMBER moved."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-04-ac15-write-walk-blind-to-path-open-with-a-positional-mode",
    ),
    ACAudit(
        ac="AC16",
        claim=(
            "PLAN §12 R-07: the .pdftoolkit- namespace has exactly one owner, so ops/discovery.py "
            "cannot hardcode it and must import the predicate. find_stray_temps() returns the "
            "planted stray files and, after the call, all of them still exist (report, never "
            "sweep)."
        ),
        covering=(
            "tests/unit/test_tempnames.py::test_find_stray_temps_reports_and_never_sweeps",
            "tests/integration/test_atomic_crash.py::test_residue_is_reported_rather_than_swept[after_fsync]",
            "tests/test_import_boundaries.py::test_the_temp_prefix_literal_has_exactly_one_definition",
            "tests/test_import_boundaries.py::test_a_second_prefix_literal_is_caught",
        ),
        red=(
            "REPORT-NEVER-SWEEP half: made `find_stray_temps` unlink what it finds. FOUR arms "
            "failed -- `test_find_stray_temps_reports_and_never_sweeps` and all three "
            "`test_residue_is_reported_rather_than_swept` legs, each on `assert all(stray.exists() "
            "for stray in strays)`. Reverted with git show HEAD:; scratch clean.\\n"
            "ONE-OWNER half: the criterion's own recorded ladder REPORTS THE WRONG ANSWER and is "
            "corrected here. Run verbatim at 7522e3e, `grep -rn '[.]pdftoolkit-' src/ | grep -v "
            "'^src/pdf_toolkit/safety/tempnames.py'` returns THREE hits and exits 0 where the "
            "criterion expects empty: ops/procpool.py:47 (module docstring), ops/procpool.py:207 "
            "(comment) and safety/atomic.py:861 (a doc-comment whose whole point is that "
            "`_SCRATCH_PREFIX` deliberately does NOT carry the literal). §D2's third hit was "
            "recorded at :664; PDF-18 moved it. All three are PROSE and the SUBSTANCE holds -- "
            "`TEMP_PREFIX` is defined exactly once, at tempnames.py:30 -- but a qa-sentinel "
            "re-running the recorded ladder would file a defect against a correct tree. The "
            "command tests a PHRASE where the criterion is a PROPOSITION. Replaced with an AST "
            "check for exactly one string-literal DEFINITION of the prefix under src/, and PROVEN "
            "RED by planting a second literal in a `discovery`-shaped module -- the violation "
            "PLAN §12 R-07's exclusion rule exists to prevent -- which the check reports as two "
            "definitions naming `pdf_toolkit.ops.discovery`."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC17",
        claim=(
            "PLAN §12 R-06 mechanized: grep -rniE '\\\\b(journal|undo|rollback)\\\\b' src/ | "
            "grep -v 'D-07' returns nothing. No journal module, no transaction log, no .journal "
            "file, no undo verb."
        ),
        covering=(),
        red=(
            "The grep is CORRECT at HEAD -- run verbatim it produces no output and exits 1 -- but "
            "a grep that has never been seen to match has never been observed to work, so it was "
            "PROVEN RED. Planted `src/pdf_toolkit/ops/_pdf19_probe.py` containing `def rollback() "
            "-> None:` with the docstring `Undo the last write.` in the scratch worktree: "
            "the same command returned exit 0 with TWO hits, "
            "`src/pdf_toolkit/ops/_pdf19_probe.py:4:def rollback() -> None:` and "
            "`:5:` carrying that docstring, catching both the identifier and the "
            "word-in-prose case the `\\\\b` anchors exist for. Removing the plant returned it to "
            "exit 1 with empty output; scratch status --porcelain empty.\\n"
            "The criterion is MET and the control fires. It is nonetheless carried by NO TEST: "
            "nothing in tests/ runs this grep, so it is a Validation-block ladder rather than a "
            "mechanism, and it is one file rename away from silently ceasing to be checked."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-04-ac17-no-journal-grep-is-a-ladder-not-a-mechanism",
    ),
    ACAudit(
        ac="AC18",
        claim=(
            "A table-driven test asserts each §D8 error class carries its documented exit_code, "
            "and the subprocess harness's exit status equals it for every row."
        ),
        covering=(
            "tests/unit/test_atomic_writer.py::test_each_safety_error_carries_its_documented_exit_code[BackupExistsError]",
            "tests/unit/test_atomic_writer.py::test_the_table_covers_every_safety_error_the_package_exports",
            "tests/unit/test_atomic_writer.py::test_the_harness_returns_5_for_an_existing_sidecar",
            "tests/unit/test_atomic_writer.py::test_the_harness_returns_5_for_an_escaping_destination",
            "tests/unit/test_atomic_writer.py::test_a_refusal_under_json_goes_to_stdout_with_its_code",
        ),
        red=(
            "Flipped one class's code -- added `exit_code: ClassVar[int] = FAILURE` to "
            "`BackupExistsError` (errors.py), 5 -> 1. TWO INDEPENDENT CONSUMERS failed, which is "
            "what §D2 requires and is this product's second headline defect class: the table arm "
            "(`AssertionError: assert 1 == 5 where 1 = BackupExistsError('message').exit_code`) "
            "AND the subprocess row (`assert 1 == 5` with the real refusal text `error: "
            "doc.pdf.bak already exists beside .../doc.pdf; pass --force to replace the sidecar` "
            "on stderr). A single-consumer control would have let a table and a binary disagree. "
            "The eight-row table is additionally pinned against `errors.__all__` by "
            "`test_the_table_covers_every_safety_error_the_package_exports`, so a ninth safety "
            "error cannot land unasserted. Reverted with git show HEAD:; scratch clean."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC19",
        claim=(
            "TESTING.md gains a 'Safety-spine test arms' section, mechanized: grep -q "
            "PDF_TOOLKIT_TEST_XDEV_DIR && grep -q PDF_TOOLKIT_FAULT_POINT && grep -q "
            "PDF_TOOLKIT_FAULT_RENDEZVOUS exits 0, and the section states the expected "
            "visible-skip count."
        ),
        covering=(),
        red=(
            "NOT OBSERVED RED -- there is nothing to drive. No test executes AC19's three greps "
            "or reads any content claim in TESTING.md. `tests/test_docs_antirot.py` scopes its "
            "phase-line, spec-identifier and spec-count guards to `PRIME_DOCS = ('README.md', "
            "'CLAUDE.md')` (`:29`) and includes TESTING.md only in `DOCS_WITH_COMMANDS` (`:32`), "
            "which checks that every `make <target>` it names exists -- nothing else. Widening "
            "that list is PDF-30's (X-154), so writing the assertion here would be trespassing "
            "AND would be the move `0615feae63` is the precedent against: AC19 is UNMEASURED, not "
            "unmet, and filing that is the honest outcome.\\n"
            "MEASURED instead, at 7522e3e: the chained grep exits 0 (the three variables appear "
            "2/1/1 times). Both content claims were WRONG and are corrected by PDF-19 in "
            "TESTING.md itself: the acquisition ladder was documented as THREE rungs while "
            "`_ladder()` (test_cross_filesystem.py:53-60) enumerates FIVE and the fixture prints "
            "the rung it resolved at, so an operator reading the doc would not recognise the "
            "message; and the negative-control count read 'six' where the file carries nine. The "
            "expected visible-skip count is RE-MEASURED on this host and stated as a number: "
            "over the eight safety-spine files, 259 passed / 0 skipped / 1 xfailed with -rs, "
            "ladder rung 2 (/dev/shm)."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-04-ac19-testing-md-content-claims-are-mechanised-by-nothing",
    ),
    ACAudit(
        ac="AC20",
        claim=(
            "HC compliance: exactly one DCO-signed commit subject-tagged [PDF-04]; git show "
            "--stat HEAD lists only Scope > In paths; changelog.md carries the [PDF-04] entry IN "
            "THAT COMMIT; git diff HEAD~1 -- pyproject.toml uv.lock is empty; README.md and "
            "CLAUDE.md untouched."
        ),
        covering=(),
        red=(
            "NOT OBSERVED RED, and NOT MET. Git history is not mutable by a planted defect and "
            "no test reads it, so this row is re-derived from `git log`/`git show --stat` rather "
            "than driven. Measured at 7522e3e across the three [PDF-04] commits:\\n"
            "  ebc6f5b  DCO-signed, 22 files, +3844/-10, changelog.md PRESENT\\n"
            "  85dd844  DCO-signed,  3 files, +18/-4,    changelog.md ABSENT\\n"
            "  e887d4d  DCO-signed,  7 files, +503/-30,  changelog.md PRESENT\\n"
            "Under X-180 as re-stated by X-188 the literal 'exactly one commit' clause is the "
            "defect, not the miss -- it is unsatisfiable against OR-6 once a pushed run goes red, "
            "and `85dd844` is a sanctioned fix-forward. What IS a miss is durable: `85dd844`'s "
            "two platform-dependent test fixes (the umask-dependent chmod control; APFS directory "
            "st_size in `assert_only_temp_residue`) are described by NO changelog entry -- "
            "`grep -n 'PDF-04' changelog.md` returns entries for `ebc6f5b` (`:1059`) and "
            "`e887d4d` (`:861`) and nothing for the fix-forward, and a search for its subject "
            "matter (umask / APFS / assert_only_temp_residue) returns nothing. X-188's binding "
            "reading is 'no entry is ever lost'. PDF-04's own Implementation Log deviation 12 "
            "reaches the same conclusion in its own words -- the entry was 'owed and not "
            "written', and the rule cited to excuse it is the rule that required it. This audit "
            "records that verdict; it does not re-litigate it and does not back-fill the entry "
            "(changelog rule 3 forbids editing a landed entry; a correction is a NEW entry with a "
            "new date, and allocating one is the project-manager's)."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-04-ac20-fix-forward-85dd844-changelog-entry-was-never-written",
    ),
    ACAudit(
        ac="AC21",
        claim=(
            "Ruling X-67: _plan() runs under --dry-run, so a dry run PREDICTS the refusal a real "
            "run raises, for all three conditions this spec owns -- occupied target -> 5, "
            "unwritable destination -> 1, cross-filesystem warning. would_exit equals the real "
            "exit status and would_refuse is the same §5.6 error object. Capture stops at the "
            "first refusal. A real run raises and captures nothing."
        ),
        covering=(
            "tests/unit/test_atomic_writer.py::test_a_dry_run_over_an_occupied_target_predicts_the_refusal",
            "tests/unit/test_atomic_writer.py::test_a_dry_run_over_a_missing_destination_predicts_exit_one",
            "tests/unit/test_atomic_writer.py::test_the_prediction_stops_where_the_real_run_would_have_stopped",
            "tests/unit/test_atomic_writer.py::test_a_real_run_still_raises_and_captures_nothing",
            "tests/unit/test_atomic_writer.py::test_the_dry_run_json_predicts_the_refusal_the_real_run_produces",
            "tests/unit/test_atomic_writer.py::test_the_dry_run_json_predicts_the_unwritable_destination_too",
            "tests/integration/test_purity_primitive.py::test_a_dry_run_that_predicts_a_refusal_is_still_pure",
            "tests/test_cli_contract.py::test_c15_dry_run_predicts_an_occupied_target_refusal[merge]",
            "tests/test_cli_contract.py::test_c15_dry_run_predicts_an_unwritable_destination_refusal[compose]",
        ),
        red=(
            "§D2's prescribed whole-file oracle CANNOT BE USED at HEAD, and that is recorded "
            "rather than worked around: `git show d777dd8:src/pdf_toolkit/safety/atomic.py` "
            "predates PDF-18, and eight ops/ modules now import `plan_filesystem` from that "
            "module, so the pre-X-67 file dies at import -- `ImportError: cannot import name "
            "'plan_filesystem' from 'pdf_toolkit.safety.atomic'` -- and every arm would red for "
            "the wrong reason. Re-derived as the targeted equivalent: the gate restored to the "
            "PRE-X-67 SHAPE, first statement of `__enter__`, so `_plan()` never runs under "
            "--dry-run. FOURTEEN arms failed -- six X-67 prediction arms in test_atomic_writer.py, "
            "two purity arms that wrap a capturing dry run, and six test_c15 legs across "
            "compose/create/merge -- while 111 passed. Reverted with git show HEAD:; scratch "
            "clean.\\n"
            "MEASURED AS PAIRS ON THE ENVELOPE, never the integer alone (X-185). Dry run first "
            "(it is pure), then the real run, in the SAME tree so the payloads are comparable: "
            "occupied target -> real 5 / dry 0 / would_exit 5 / would_refuse == the real -o json "
            "error object EXACTLY; unwritable destination -> real 1 / dry 0 / would_exit 1 / "
            "would_refuse == the real error object EXACTLY. The PRECEDENCE-DISTINGUISHING pair "
            "required by §D6, driven on the real CLI: `delete ro/a.pdf ro/b.pdf --pages 1 "
            "--in-place` with `ro` at 0o500 and stdin not a terminal answers real 5 / dry 5 with "
            "the IDENTICAL top-level `refused` envelope; adding `-y` makes the gate step aside so "
            "a strictly LOWER tier answers -- real 1 `failure` (destination directory is not "
            "writable) / dry 1 with a PLAN envelope whose two items each carry exit_code 1. The "
            "pair moves together to a different code in both modes, which a preview that had "
            "simply gone silent could not do. The carve-outs are asserted, not assumed: "
            "`test_a_real_run_still_raises_and_captures_nothing` pins the raise path.\\n"
            "SCOPE LIMIT FOUND WHILE MEASURING THE MATRIX, and it is OUTSIDE the three conditions "
            "AC21 names, so it does not make this criterion unmet -- it is a separate product "
            "finding reported to the project-manager. The `.bak` tier is invisible to the "
            "preview: `_make_backup()` raises BackupExistsError from `_commit()`, i.e. AFTER the "
            "gate, so `<verb> <doc> --in-place --dry-run -o json` reports `ok: true, exit_code: 0` "
            "and EXITS 0 while the identical real run EXITS 5. Measured on the real CLI over the "
            "twelve --in-place-capable verbs: SIX reproduce (compress, delete, linearize, repair, "
            "rotate, watermark), four need engine/password fixtures this probe did not build, and "
            "two were mis-invoked by the probe. `cmd --dry-run && cmd` green-lights a run that "
            "then refuses -- an OR-7 violation in the same preview-lies family X-67 fixed for the "
            "no-clobber and writability tiers."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-04-ac21-bak-tier-is-invisible-to-the-dry-run-preview",
    ),
)
