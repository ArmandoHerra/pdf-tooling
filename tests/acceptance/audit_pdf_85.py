"""`PDF-85`'s 14 acceptance criteria, re-derived -- `AUDIT-CONVENTION(PDF-17)`.

`PDF-85` ("Re-scope the filesystem-acceptance oracle to the branch it was built
for", landed `559183b`) reads `Implemented (2026-09-18)` in `SPEC-INDEX.md` and
has never held a `Verified`. This module is the evidence for that first grant or
refusal, written under `PDF-106` (roadmap `R-05`, PM ruling `X-962`, dispatch
B). The `PDF-106` auditing spec is the reason this file exists; `PDF-85` is the
audited spec.

**Independence (R-05, binding).** The author of this module did not implement
`PDF-85` or `PDF-88`: it is a fresh dispatch that never held either spec's
context. The audited spec's Implementation Log was not used as evidence; the
spec text was used for the AC wording only, and every red below was re-driven by
this author at the audit base.

The qa-sentinel grants or refuses; this module does not.

**Taken at the audit base `119f47e`, not at the landing commit.** The covering
arms live in `tests/unit/test_name_template.py`, which `PDF-88` (`0283279`)
rewrote after `PDF-85` landed, so several arms below are `PDF-88`'s successors
of the arm `PDF-85` wrote. Every `covering` id was copy-pasted from
`uv run pytest tests/unit/test_name_template.py --collect-only -q` at that base.

**Verdict counts -- 7 locally driven, 1 covered red NOT observed, 4
command-evidenced, 1 CI-evidenced, 1 UNREDDENABLE = 14. Unmeasured: 0.**

* **locally driven** -- AC1, AC2, AC3, AC4, AC6, AC7, AC8. Each `red` names the
  file:line mutated in a private scratch worktree at `119f47e`, the failure
  line seen, the revert and the base sha.
* **covered, red NOT observed** -- AC9 (`red_kind=NOT_OBSERVED`, with a
  finding): the covering arm stays green when the thing the AC pins is removed.
* **COMMAND:** -- AC5, AC11, AC12, AC13. Properties of a landed commit, evidenced
  by a re-runnable `git show` command; no mutation can red them without
  rewriting history. None carries a command-level red, so each is
  `NOT_OBSERVED` plus a finding.
* **CI-EVIDENCED:** -- AC14. NOT MET and NOT DISCHARGED per `X-854`; see the row.
* **UNREDDENABLE:** -- AC10. The spec's own failing control is a person reading
  the diff ("a reader's test"). A mechanical attempt was driven and stayed green
  (see the row), so there is no machine red to record. Reason: the AC asserts
  that prose in comments and a docstring is legible, and no assertion in the
  suite reads that prose.

Mutation method for every locally driven row: edit one line in the scratch
worktree, run the named node ids with `uv run pytest <ids> -n 0 -p no:randomly`,
record the failure line, restore the file and prove the restore with
`git diff --exit-code`. Nothing in this module was mutated in the shared
worktree.

Three rows carry a finding the sentinel should weigh: AC6 (the oracle's own
`except` path can swallow an unclassified errno and nothing reds), AC9 (the
counterexample's membership in `_SEED_VALUES` is pinned by no arm) and AC14
(`X-854`). Free-text is never a finding: each is a `PENDING-LEDGER:` slug for
the sentinel to mint.
"""

from __future__ import annotations

from typing import Final

from acceptance._model import ACAudit, RedKind

SPEC_ID: Final[str] = "PDF-85"
AC_COUNT: Final[int] = 14

AUDIT: Final[tuple[ACAudit, ...]] = (
    ACAudit(
        ac="AC1",
        claim=(
            "AC1 -- the oracle survives, and its docstring and its code now agree. "
            "`_the_filesystem_accepts` still exists, still calls `candidate.touch()`, and"
            " still asks the filesystem. Its `except OSError` block no longer decides "
            "anything itself; the decision is a module-level pure function over the "
            "exception."
        ),
        covering=(
            "tests/unit/test_name_template.py::test_the_measured_counterexample_passes_here_and_is_recorded_where_it_is_refused",
            "tests/unit/test_name_template.py::test_a_refusing_host_is_recorded_and_published_rather_than_reddened",
        ),
        red=(
            "Mutated tests/unit/test_name_template.py:380 (`if verdict.kind == "
            "_RECORDED:` -> `if False:`, so the oracle's `except` block stops consulting "
            "the classifier's verdict and always raises) in a private detached scratch "
            "worktree at base 119f47e. `uv run pytest tests/unit/test_name_template.py::t"
            "est_the_measured_counterexample_passes_here_and_is_recorded_where_it_is_refu"
            "sed tests/unit/test_name_template.py::test_a_refusing_host_is_recorded_and_p"
            "ublished_rather_than_reddened -n 0` -> 2 failed: `OSError: [Errno 84] "
            "Invalid or incomplete multibyte or wide character: '.../out/\\U0001239a.pdf'`"
            " followed by a bare `AssertionError` (empty message: the recorded verdict "
            "carries none). The decision therefore lives in the classifier and the oracle"
            " only obeys it. Reverted by restoring the file from its pre-mutation copy "
            "(byte-identical to `git show HEAD:tests/unit/test_name_template.py`; sha256 "
            "matched before and after) and `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC2",
        claim=(
            "AC2 -- the 255-byte branch is LIVE and is driven by a real syscall. The "
            "length arm reds with `_MAX_COMPONENT_BYTES` raised, against a real "
            "`tmp_path`, with no injected exception anywhere in its path, and its message"
            " names `ENAMETOOLONG`. Its own red-of-the-red: at the shipped value the arm "
            "cannot construct the case at all."
        ),
        covering=(
            "tests/unit/test_name_template.py::test_an_over_long_component_still_reds_the_oracle_on_a_real_syscall",
        ),
        red=(
            "Mutated tests/unit/test_name_template.py:311 (`if error.errno == "
            "errno.ENAMETOOLONG:` -> `errno.EFBIG`, so the classifier stops recognising "
            "the length refusal) in a private detached scratch worktree at base 119f47e. "
            "`uv run pytest tests/unit/test_name_template.py::test_an_over_long_component"
            "_still_reds_the_oracle_on_a_real_syscall -n 0` -> `AssertionError: the "
            "message lost the component's byte count ... UNCLASSIFIED errno 36 "
            "(ENAMETOOLONG): the filesystem under .../out refused the 304-byte component "
            "'aaaa...'` and `assert '304 bytes' in 'UNCLASSIFIED errno 36 "
            "(ENAMETOOLONG)...'`. That is the real kernel errno 36 on a 304-byte "
            "component through a real `tmp_path`. Second mutation for the red-of-the-red:"
            " tests/unit/test_name_template.py:665 (`_MAX_COMPONENT_BYTES` 10_000 -> 255,"
            " the shipped value) -> `pdf_tooling.errors.OutputEscapesDirError: the "
            "rendered output name is 304 bytes, over the 255-byte filename limit`, raised"
            " by `render_name` before the oracle is reached, and the arm fails loudly "
            "rather than skipping. Reverted by restoring the file from its pre-mutation "
            "copy (byte-identical to `git show HEAD:tests/unit/test_name_template.py`; "
            "sha256 matched before and after) and `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC3",
        claim=(
            "AC3 -- the encoding refusal is recorded, not asserted against. Injecting "
            "`errno.EILSEQ` at the oracle's `touch` against the pinned counterexample "
            "raises nothing and emits the named event. Removing `errno.EILSEQ` from the "
            'allowlist makes the same injection red, naming "UNCLASSIFIED errno 84 '
            '(EILSEQ)" on this host.'
        ),
        covering=(
            "tests/unit/test_name_template.py::test_the_measured_counterexample_passes_here_and_is_recorded_where_it_is_refused",
        ),
        red=(
            "Mutated tests/unit/test_name_template.py:242 (`_ENCODING_REFUSAL_ERRNOS = "
            "frozenset({errno.EILSEQ})` -> `frozenset()`) in a private detached scratch "
            "worktree at base 119f47e. `uv run pytest tests/unit/test_name_template.py::t"
            "est_the_measured_counterexample_passes_here_and_is_recorded_where_it_is_refu"
            "sed -n 0` -> `AssertionError: UNCLASSIFIED errno 84 (EILSEQ): the filesystem"
            " under .../out refused the 8-byte component '\\U0001239a.pdf' ... for a "
            "reason this oracle neither predicts nor has ever measured.` Other direction:"
            " the unmutated arm passes (the module is 21 passed at 119f47e), with the "
            "injected EILSEQ recorded rather than raised. Reverted by restoring the file "
            "from its pre-mutation copy (byte-identical to `git show "
            "HEAD:tests/unit/test_name_template.py`; sha256 matched before and after) and"
            " `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC4",
        claim=(
            "AC4 -- the third verdict exists and the narrowing is exactly one verdict "
            "wide. The parametrized verdict roster passes: `ENAMETOOLONG` -> defect, "
            "`EILSEQ` -> recorded, and `EACCES`, `ENOENT`, `ENOSPC` -> "
            "unclassified-and-red. Injected `EACCES` reds naming errno 13."
        ),
        covering=(
            "tests/unit/test_name_template.py::test_the_classifier_answers_every_roster_errno_with_one_of_three_verdicts[ENAMETOOLONG]",
            "tests/unit/test_name_template.py::test_the_classifier_answers_every_roster_errno_with_one_of_three_verdicts[EILSEQ]",
            "tests/unit/test_name_template.py::test_the_classifier_answers_every_roster_errno_with_one_of_three_verdicts[EACCES]",
            "tests/unit/test_name_template.py::test_the_classifier_answers_every_roster_errno_with_one_of_three_verdicts[ENOENT]",
            "tests/unit/test_name_template.py::test_the_classifier_answers_every_roster_errno_with_one_of_three_verdicts[ENOSPC]",
        ),
        red=(
            "Two mutations in a private detached scratch worktree at base 119f47e, each "
            "over the five roster ids. (a) tests/unit/test_name_template.py:347 "
            '(`f"UNCLASSIFIED errno {error.errno} "` -> `f"UNCLASSIFIED errno ? "`): 3 '
            "failed, 2 passed; `[EACCES]` -> `AssertionError: the unclassified verdict "
            "did not name the errno it could not classify ... UNCLASSIFIED errno ? "
            "(EACCES)` and `assert 'UNCLASSIFIED errno 13' in ...`; `[ENOENT]` and "
            "`[ENOSPC]` red likewise on errno 2 and 28. (b) "
            "tests/unit/test_name_template.py:242 (allowlist widened to `{errno.EILSEQ, "
            "errno.EACCES}`): 5 failed, `assert 2 == 1 where 2 = len(frozenset({13, "
            "84}))` -- the width assertion fires on every member, so a second allowlist "
            "entry cannot slip in without reddening the whole roster. Reverted by "
            "restoring the file from its pre-mutation copy (byte-identical to `git show "
            "HEAD:tests/unit/test_name_template.py`; sha256 matched before and after) and"
            " `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC5",
        claim=(
            "AC5 -- this is not a deletion. `git diff` shows `_the_filesystem_accepts` "
            "and its call site at the property's tail both present; the property's "
            "existing containment assertions are unchanged and unedited; no "
            "`@pytest.mark.skip`, no `xfail`, no `pytest.skip()`, and no `sys.platform` "
            "conditional appears anywhere in the diff."
        ),
        covering=(),
        red=(
            "COMMAND: a property of the landed commit `559183b`, re-derivable and not "
            "mutable without rewriting history. Re-run at base 119f47e: `git show 559183b"
            " -- tests/unit/test_name_template.py | grep -E '^\\+' | grep -vE '^\\+\\+\\+' | "
            "grep -ciE 'skip|xfail|platform|darwin'` -> 0 (the spec's own command, AC5's "
            "pattern). `git show 559183b -- tests/unit/test_name_template.py | grep -E "
            "'^-[^-]'` lists 7 removed lines: one comment line, and the old oracle's "
            "`encoded = ...` line plus the old unconditional `raise AssertionError(...) "
            "from error` -- none is a containment assertion. At base, "
            "`_the_filesystem_accepts` is present (line 358) and is called at the "
            "property's tail (line 585). No command-level red was driven: no plant was "
            "run against the command, so this row is NOT_OBSERVED."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-85-landed-diff-acs-have-no-standing-control",
    ),
    ACAudit(
        ac="AC6",
        claim=(
            "AC6 -- this is not a swallow. The classifier's `except` path has no branch "
            "that returns without either raising or emitting the recorded event. Failing "
            "control: add a bare `return` for an arbitrary errno and watch AC4's roster "
            "arm red on that errno."
        ),
        covering=(
            "tests/unit/test_name_template.py::test_the_classifier_answers_every_roster_errno_with_one_of_three_verdicts[ENOSPC]",
        ),
        red=(
            "Mutated tests/unit/test_name_template.py:311 (inserted `if error.errno == "
            "errno.ENOSPC: return _Verdict(kind=_UNCLASSIFIED)` ahead of the length "
            "branch -- a verdict carrying neither a message nor an event, the structural "
            "form of a swallow) in a private detached scratch worktree at base 119f47e. "
            "`uv run pytest tests/unit/test_name_template.py::test_the_classifier_answers"
            "_every_roster_errno_with_one_of_three_verdicts -n 0` -> 1 failed, 4 passed: "
            "`[ENOSPC]` -> `AssertionError: the verdict for ENOSPC carries neither -- a "
            "branch the oracle returns from having neither reddened nor recorded is a "
            "SWALLOW` and `assert False != False`. THAT IS THE CLASSIFIER HALF ONLY. "
            "Second mutation, the ORACLE half: tests/unit/test_name_template.py:417 "
            "(inserted `if verdict.kind == _UNCLASSIFIED: return` before `raise "
            "AssertionError(verdict.message) from error`, so the oracle itself swallows "
            "an unclassified errno) -> `uv run pytest tests/unit/test_name_template.py -n"
            " 0` -> 21 passed, 1 warning. NOTHING REDS: the roster arm calls only the "
            "classifier, and "
            "`test_an_unclassified_host_answer_reds_the_branch_helper_naming_its_errno` "
            "raises in the helper's pre-check before the oracle is reached. The "
            "criterion's wording is about the classifier's path and that is held; the "
            "oracle's own unclassified path is not pinned. Reverted by restoring the file"
            " from its pre-mutation copy (byte-identical to `git show "
            "HEAD:tests/unit/test_name_template.py`; sha256 matched before and after) and"
            " `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-85-ac6-oracle-level-swallow-has-no-red",
    ),
    ACAudit(
        ac="AC7",
        claim=(
            "AC7 -- no integer errno literal, anywhere. The diff contains `errno.EILSEQ` "
            "and `errno.ENAMETOOLONG` symbolically and contains neither `92` nor `36` nor"
            " `84` as an errno value. Failing control: substitute the literal `92` for "
            "`errno.EILSEQ` and AC3's arm reds on this host, because `92` here is "
            "`ENOPROTOOPT`."
        ),
        covering=(
            "tests/unit/test_name_template.py::test_the_measured_counterexample_passes_here_and_is_recorded_where_it_is_refused",
            "tests/unit/test_name_template.py::test_the_classifier_answers_every_roster_errno_with_one_of_three_verdicts[EILSEQ]",
        ),
        red=(
            "Mutated tests/unit/test_name_template.py:242 (`frozenset({errno.EILSEQ})` ->"
            " `frozenset({92})`; `errno.errorcode[92]` on this host is ENOPROTOOPT) in a "
            "private detached scratch worktree at base 119f47e. `uv run pytest tests/unit"
            "/test_name_template.py::test_the_measured_counterexample_passes_here_and_is_"
            "recorded_where_it_is_refused tests/unit/test_name_template.py::test_the_clas"
            "sifier_answers_every_roster_errno_with_one_of_three_verdicts[EILSEQ] -n 0` "
            "-> 2 failed: the measured arm -> `AssertionError: UNCLASSIFIED errno 84 "
            "(EILSEQ): ... refused the 8-byte component`, and `[EILSEQ]` -> "
            "`AssertionError: EILSEQ was classified 'unclassified, and therefore still "
            "red', not \"recorded, not the renderer's contract\"`. The diff-literal half, "
            "re-run at base: `git show 559183b -- tests/unit/test_name_template.py | grep"
            " -E '^\\+' | grep -vE '^\\+\\+\\+' | grep -cwE '92|36|84'` -> 0. Reverted by "
            "restoring the file from its pre-mutation copy (byte-identical to `git show "
            "HEAD:tests/unit/test_name_template.py`; sha256 matched before and after) and"
            " `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC8",
        claim=(
            "AC8 -- the length verdict follows the NAME, not the number. Injecting "
            "`errno.ENAMETOOLONG` against an 8-byte component reds with the "
            "renderer-defect message."
        ),
        covering=(
            "tests/unit/test_name_template.py::test_the_classifier_answers_every_roster_errno_with_one_of_three_verdicts[ENAMETOOLONG]",
        ),
        red=(
            "Mutated tests/unit/test_name_template.py:311 (`if error.errno == "
            "errno.ENAMETOOLONG:` -> `if error.errno == errno.ENAMETOOLONG and encoded > "
            "100:`, making the verdict follow component size as well as name) in a "
            "private detached scratch worktree at base 119f47e. `uv run pytest tests/unit"
            "/test_name_template.py::test_the_classifier_answers_every_roster_errno_with_"
            "one_of_three_verdicts -n 0` -> 1 failed, 4 passed: `[ENAMETOOLONG]` -> "
            "`AssertionError: ENAMETOOLONG was classified 'unclassified, and therefore "
            "still red', not \"the renderer's defect\"` -- the arm drives the 8-byte "
            "`\\U0001239a.pdf` component, so the length verdict must come from the errno "
            "alone. Reverted by restoring the file from its pre-mutation copy "
            "(byte-identical to `git show HEAD:tests/unit/test_name_template.py`; sha256 "
            "matched before and after) and `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC9",
        claim=(
            "AC9 -- the macOS counterexample is carried into the suite and replays on "
            "every run. `'\\U0001239a'` is in `_SEED_VALUES`; "
            "`hypothesis_explicit_examples` moves 55 -> 60; "
            "`test_every_seed_value_is_guaranteed_under_every_template` passes unchanged "
            "and unedited."
        ),
        covering=(
            "tests/unit/test_name_template.py::test_every_seed_value_is_guaranteed_under_every_template",
        ),
        red=(
            "NOT OBSERVED RED. Mutated tests/unit/test_name_template.py:117 (removed the "
            "`_MACOS_COUNTEREXAMPLE,` entry from `_SEED_VALUES`) in a private detached "
            "scratch worktree at base 119f47e. `uv run pytest "
            "tests/unit/test_name_template.py -n 0` -> 21 passed, 1 warning: THE COVERING"
            " ARM STAYS GREEN. It derives its expectation from `_SEED_VALUES` itself "
            "(`stems == set(_SEED_VALUES)`, `len(examples) == len(_SEED_VALUES) * "
            "len(_TEMPLATES)`), so it pins the cross-product and not the counterexample's"
            " membership or the count 60. No other arm reads `_SEED_VALUES` (`grep -rln "
            "'_SEED_VALUES' tests/` -> this file only). At base the roster holds 12 seeds"
            " x 5 templates = 60, which the arm confirms only relative to itself. The "
            "AC's claim holds at base and is unguarded: a later edit that drops the macOS"
            " seed is invisible to the suite. Reverted by restoring the file from its "
            "pre-mutation copy (byte-identical to `git show "
            "HEAD:tests/unit/test_name_template.py`; sha256 matched before and after) and"
            " `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-85-ac9-counterexample-seed-membership-unpinned",
    ),
    ACAudit(
        ac="AC10",
        claim=(
            "AC10 -- the observation is legible where it is read. The classifier's "
            "`EILSEQ` branch names ledger `2b88707a36`, carrier `B-352`, CI run "
            "`35295764623`, the codepoint and its category, and the errno by symbolic "
            "name; `_SEED_VALUES`' new entry names it as a measured counterexample; the "
            "module docstring carries `X-789`'s correction. Failing control: a reader's "
            "test."
        ),
        covering=(),
        red=(
            "UNREDDENABLE: the spec's own failing control is a person reading the diff, "
            "and no assertion in the suite reads the prose it concerns. A mechanical red "
            "was attempted and none exists: in the scratch worktree at 119f47e the "
            "classifier comment's ledger row, carrier and CI run id were replaced by "
            "`REDACTED`, the module docstring's `PDF-77 paid out through its oracle` "
            "sentence and the `U+1239A, category `Cn`` phrase were blanked, and `uv run "
            "pytest tests/unit/test_name_template.py tests/test_docs_antirot.py "
            "tests/test_docstring_pointers.py -n 2` -> 279 passed, 9 skipped (the skips "
            "are `test_docs_antirot.py:2203`, no planning tree on this host), 0 failed. "
            "Reverted from the pre-mutation copy; sha256 matched; `git diff --exit-code` "
            "returned 0. The ledger id and carrier ARE asserted, but only inside the "
            "published warning text (see PDF-88 AC5), not in the comment this AC names."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-85-ac10-readers-test-has-no-mechanical-red",
    ),
    ACAudit(
        ac="AC11",
        claim=(
            "AC11 -- `src/` is untouched. `git diff --stat -- src/` is empty. "
            "`safety/naming.py` and `safety/atomic.py` are byte-identical to `3d3221e`. "
            "`git diff --stat` for the whole change lists exactly two files, "
            "`tests/unit/test_name_template.py` and `changelog.md`."
        ),
        covering=(),
        red=(
            "COMMAND: a property of the landed commit `559183b`. Re-run at base 119f47e: "
            "`git diff --stat 559183b^ 559183b -- src/ | wc -l` -> 0, and `git show "
            "--stat --format= 559183b` -> exactly `changelog.md | 8 +` and "
            "`tests/unit/test_name_template.py | 369 +++++++-` (2 files changed, 370 "
            "insertions, 7 deletions). The `3d3221e` byte-identity half is implied by the"
            " empty `src/` diff of this single commit; it was not run as a separate `git "
            "diff 3d3221e 559183b` command. No command-level red was driven (no plant of "
            "a `src/` edit was run against the command): NOT_OBSERVED."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-85-landed-diff-acs-have-no-standing-control",
    ),
    ACAudit(
        ac="AC12",
        claim=(
            "AC12 -- no ceiling, count or bound moved. `tests/test_docs_antirot.py` "
            "passes; the four residues are recorded before and after and are unchanged at"
            " 29 / 7 / 6 / 127; `RESIDUE_CEILING`, `PRAGMA_CEILING`, `TIMEOUT_CEILING` "
            "and every `*_CEILING` constant in `tests/` are unedited; `.github/` is "
            "unedited; `perf/suite-size.md` is unedited."
        ),
        covering=(),
        red=(
            "COMMAND: a property of the landed commit `559183b`. Re-run at base 119f47e: "
            "`git show --stat --format= 559183b` names only `changelog.md` and "
            "`tests/unit/test_name_template.py`, so no file under `tests/` other than the"
            " audited module, nothing under `.github/` and no `perf/suite-size.md` was "
            "touched (`... | grep -cE '\\.github|perf/'` -> 0). `git show 559183b | grep "
            "-E 'CEILING|RESIDUE'` -> 4 lines, all comment or docstring prose inside the "
            "audited module (a sentence about `RESIDUE_CEILING` being a different "
            "constant), none an assignment. The residue figures 29 / 7 / 6 / 127 were NOT"
            " re-derived: they were measured at landing and the guarded documents have "
            "moved since, so reporting them now would be a transcription of the spec, not"
            " a measurement. No command-level red was driven: NOT_OBSERVED."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-85-landed-diff-acs-have-no-standing-control",
    ),
    ACAudit(
        ac="AC13",
        claim=(
            "AC13 -- the suite is green in both configurations, and the module's cost did"
            " not grow. `tests/unit/test_name_template.py` passes at its pre-change count"
            " plus this spec's three arms; the full `make test` passes; the module's wall"
            " clock is recorded against the 2.80s baseline; one `## [PDF-85]` entry sits "
            "directly below the `changelog.md` anchor, written by this spec's own commit."
        ),
        covering=(),
        red=(
            "COMMAND: a landed-commit and run-time property with no standing control for "
            "the numbers. Re-run at base 119f47e: `git show 559183b -- changelog.md | "
            "grep -E '^\\+## \\[PDF-85\\]'` -> exactly one line (`+## [PDF-85] Re-scope the "
            "filesystem-acceptance oracle to the branch it was built for -- 2026-09-18`),"
            " and `... | grep -cE '^-[^-]'` -> 0 removed lines (a pure insertion). `uv "
            "run pytest tests/unit/test_name_template.py -n 2` at base -> 21 passed, 1 "
            "warning in 3.83s; that figure includes `PDF-88`'s four later arms, so the "
            "2.80s landing-time baseline and the 'pre-change count plus three arms' "
            "arithmetic are NOT re-derivable here. `make test` was not run by this audit."
            " No command-level red was driven: NOT_OBSERVED."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-85-landed-diff-acs-have-no-standing-control",
    ),
    ACAudit(
        ac="AC14",
        claim=(
            "AC14 -- the macOS legs are the last word, and the claim is scoped honestly. "
            "After the change lands and is pushed, all four `test (3.1x, macos-14)` legs "
            "are green in one CI run, and the run id and the four job ids are recorded."
        ),
        covering=(),
        red=(
            "CI-EVIDENCED: NOT MET and NOT DISCHARGED, per `X-854` (/home/void/repos/Agen"
            "tic-Meta-Harness/ai_plans/pdf-tooling/roadmaps/2026-09-15_true-claims-then-t"
            "he-unnamed-dimension/decision.md:2192, ruling: 'AC14 stays DEFERRED and "
            "UNMET. PDF-85 stays 13/14'). The criterion's condition -- all four macos-14 "
            "legs green in one run -- was falsified in run 35341117470, where the legs "
            "went red on PDF-85's own arm; its 'capture the output and hand it up' branch"
            " is a routing duty, not a satisfaction condition. `X-854` TRANSFERRED the "
            "re-observation to `PDF-88` AC15 and left PDF-85's file unedited. A LATER "
            "GREEN RUN DOES NOT RETROACTIVELY DISCHARGE THIS ROW: it is evidence for "
            "PDF-88 AC15 (see that module) and nothing here converts it into a PDF-85 "
            "pass; whether `X-854`'s named discharge condition is now met is the "
            "project-manager's ruling, not this module's. For context only, queried live "
            "at audit time: `gh run view 37230496908 --repo ArmandoHerra/pdf-tooling "
            "--json headSha,jobs` -> headSha 119f47e8e2eaf311c6870e4255d77fff215b19e8, "
            "and `test (3.11, macos-14)` id 111518947001, `test (3.12, macos-14)` id "
            "111518947102, `test (3.13, macos-14)` id 111518947015, `test (3.14, "
            "macos-14)` id 111518947144 all conclusion success; `git merge-base "
            "--is-ancestor 559183b 119f47e8e2eaf311c6870e4255d77fff215b19e8` exit 0. "
            "Nothing asserts this criterion and no mutation can red it."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-85-ac14-x854-not-met-and-not-discharged-ci-only",
    ),
)
