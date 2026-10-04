"""`PDF-88`'s 15 acceptance criteria, re-derived -- `AUDIT-CONVENTION(PDF-17)`.

`PDF-88` ("Derive the acceptance premise from the host the arm runs on", landed
`0283279`) reads `Implemented (2026-09-18)` in `SPEC-INDEX.md` and has never
held a `Verified`. This module is the evidence for that first grant or refusal,
written under `PDF-106` (roadmap `R-05`, PM ruling `X-962`, dispatch B). The
`PDF-106` auditing spec is the reason this file exists; `PDF-88` is the audited
spec.

**Independence (R-05, binding).** The author of this module did not implement
`PDF-88` or `PDF-85`: it is a fresh dispatch that never held either spec's
context. The audited spec's Implementation Log was not used as evidence; the
spec text was used for the AC wording only, and every red below was re-driven by
this author at the audit base.

The qa-sentinel grants or refuses; this module does not.

**Taken at the audit base `119f47e`.** Every `covering` id was copy-pasted from
`uv run pytest tests/unit/test_name_template.py --collect-only -q` at that
base; the file collects 21 ids.

**Verdict counts -- 8 locally driven, 0 covered red NOT observed, 5
command-evidenced, 1 CI-evidenced, 1 UNREDDENABLE = 15. Unmeasured: 0.**

* **locally driven** -- AC1, AC2, AC3, AC4, AC5, AC6, AC7, AC9. Each `red` names
  the file:line mutated in a private scratch worktree at `119f47e`, the failure
  line seen, the revert and the base sha. AC2 and AC7 each also carry a finding
  for the half of the criterion that did NOT red; AC3 records the split the
  spec itself predicts (its first half is true in both worlds).
* **COMMAND:** -- AC8, AC10, AC11, AC12, AC14. Properties of a landed commit,
  evidenced by a re-runnable `git show`/`git diff` command; no mutation can red
  them without rewriting history. None carries a command-level red, so each is
  `NOT_OBSERVED` plus a finding. Worth the sentinel's attention: AC10's own
  literal command (`grep` the diff for `skip|xfail|platform|darwin|unicodedata`)
  returns 6, not the 0 the spec requires, because six added prose lines
  (comments and docstrings) contain those words. An AST-level count of the same
  diff is 0. The AC says a non-zero count is a BLOCKER, so this is handed up
  rather than adjudicated here.
* **CI-EVIDENCED:** -- AC15. Live `gh run view` quoted in the row.
* **UNREDDENABLE:** -- AC13. The spec's own failing control is a person reading
  the diff ("a reader's test"). A mechanical attempt was driven and stayed green
  (see the row). Reason: the AC asserts that corrected prose in a comment and a
  docstring is accurate and legible, and no assertion in the suite reads that
  prose.

Mutation method for every locally driven row: edit the named line(s) in the
scratch worktree, run the named node ids with
`uv run pytest <ids> -n 0 -p no:randomly`, record the failure line, restore the
file and prove the restore with `git diff --exit-code`. Nothing in this module
was mutated in the shared worktree.

Findings the sentinel should weigh: AC2 (the spec's literal "no-op `event`"
mutation does not red the arm; the channel-silencing mutation does), AC7 (the
`_REFUSED`/`_RETURNED` statistics events have no standing control), AC10 (its
literal grep is non-zero on prose). Free text is never a finding: each is a
`PENDING-LEDGER:` slug for the sentinel to mint.
"""

from __future__ import annotations

from typing import Final

from acceptance._model import ACAudit, RedKind

SPEC_ID: Final[str] = "PDF-88"
AC_COUNT: Final[int] = 15

AUDIT: Final[tuple[ACAudit, ...]] = (
    ACAudit(
        ac="AC1",
        claim=(
            "AC1 -- the premise is MEASURED, and the probe is pure of hypothesis. "
            "`_host_refusal_for` exists at module level, performs `candidate.touch()`, "
            "returns `OSError | None`, removes its own file on success, and calls nothing"
            " from hypothesis. Failing control: stub it to return `None` unconditionally "
            "and drive the recording-host arm -- the arm reds on the agreement assertion."
        ),
        covering=(
            "tests/unit/test_name_template.py::test_a_refusing_host_is_recorded_and_published_rather_than_reddened",
        ),
        red=(
            "Mutated tests/unit/test_name_template.py:469 (inserted `return None` as the "
            "first statement of `_host_refusal_for`, so the probe claims acceptance "
            "unconditionally) in a private detached scratch worktree at base 119f47e. `uv"
            " run pytest tests/unit/test_name_template.py::test_a_refusing_host_is_record"
            "ed_and_published_rather_than_reddened -n 0` -> 1 failed: `AssertionError: "
            "the probe measured this host ACCEPTING the component, and the oracle then "
            "published 1 encoding refusal(s) on the same name. The two instruments "
            "disagree, so one of them is lying and this helper cannot say which branch "
            "the host took`. The arm injects a refusing `touch`, so the channel publishes"
            " while the stubbed probe says accepted. Reverted by restoring the file from "
            "its pre-mutation copy (byte-identical to `git show "
            "HEAD:tests/unit/test_name_template.py`; sha256 matched before and after) and"
            " `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC2",
        claim=(
            "AC2 -- THE ARM REDS UNDER THE MUTATION THAT MADE THE CHEAP FIX GREEN. Apply "
            "the rejected candidate exactly as E3 drove it -- substitute a no-op `event` "
            "before the body runs -- under a refusing filesystem. The repaired arm must "
            "FAIL, and its message must name the disagreement between the measured "
            "premise and what was published."
        ),
        covering=(
            "tests/unit/test_name_template.py::test_a_refusing_host_is_recorded_and_published_rather_than_reddened",
            "tests/unit/test_name_template.py::test_the_measured_counterexample_passes_here_and_is_recorded_where_it_is_refused",
        ),
        red=(
            "The criterion's discriminating property is driven; its LITERAL mutation does"
            " not red. (a) Mutated tests/unit/test_name_template.py:396-398 (the "
            "`warnings.warn(...)` publication replaced by `pass`, i.e. the channel "
            "silenced under a refusing filesystem) in a private detached scratch worktree"
            " at base 119f47e: `uv run pytest tests/unit/test_name_template.py::test_a_re"
            "fusing_host_is_recorded_and_published_rather_than_reddened tests/unit/test_n"
            "ame_template.py::test_the_measured_counterexample_passes_here_and_is_recorde"
            "d_where_it_is_refused -n 0` -> 1 failed, 1 passed; `AssertionError: the "
            "probe measured this host REFUSING the component with EILSEQ, and the oracle "
            "published 0 encoding refusal(s) rather than exactly one. The two instruments"
            " disagree: a silenced channel reads as an accepting host, which is the "
            "premise PDF-88 exists to stop this arm from assuming` and `assert 0 == 1 "
            "where 0 = len([])`. That message names the disagreement the criterion asks "
            "for. (b) The literal mutation: tests/unit/test_name_template.py:902 "
            "(inserted `monkeypatch.setattr(sys.modules[__name__], 'event', lambda *_a, "
            "**_k: None)` before the refusing `touch` is installed, in the refusing-host "
            "arm) -> `uv run pytest tests/unit/test_name_template.py::test_a_refusing_hos"
            "t_is_recorded_and_published_rather_than_reddened -n 0` -> 1 passed. A no-op "
            "`event` does NOT red the repaired arm: the oracle publishes through the "
            "warning channel and merely calls `event()` beside it, so replacing `event` "
            "changes nothing the arm reads. The spec's literal control is not "
            "reproducible at the base; the property it names (premise asserted, not "
            "assumed) is held by the channel-silencing red in (a). Reverted by restoring "
            "the file from its pre-mutation copy (byte-identical to `git show "
            "HEAD:tests/unit/test_name_template.py`; sha256 matched before and after) and"
            " `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-88-ac2-literal-noop-event-mutation-does-not-red",
    ),
    ACAudit(
        ac="AC3",
        claim=(
            "AC3 -- the accepting branch's assertion DISCRIMINATES. On this host the arm "
            'takes `"accepted"`, publishes nothing, and the probe\'s file is gone. `assert'
            " not candidate.exists()` passes in both worlds and is therefore no longer "
            "load-bearing; mutate the accepting branch to expect a published warning and "
            "watch it red (`assert [] == ['MUTATED']`)."
        ),
        covering=(
            "tests/unit/test_name_template.py::test_the_unmutated_host_decides_the_branch_and_both_instruments_agree",
        ),
        red=(
            "The spec predicts a split and it is recorded as it fell. SECOND half (the "
            "mutated branch) reds: mutated tests/unit/test_name_template.py:531 (`assert "
            "recorded == []` -> `assert recorded == ['MUTATED']` in the accepting branch "
            "of `_the_hosts_answer_for`) in a private detached scratch worktree at base "
            "119f47e; `uv run pytest tests/unit/test_name_template.py::test_the_unmutated"
            "_host_decides_the_branch_and_both_instruments_agree -n 0` -> 1 failed: "
            "`AssertionError: the probe measured this host ACCEPTING the component, and "
            "the oracle then published 0 encoding refusal(s) on the same name ...: []` "
            "and `assert [] == ['MUTATED']  Right contains one more item: 'MUTATED'`. "
            "FIRST half (`assert not candidate.exists()` is true in both worlds) is a "
            "statement about a REFUSING host, where a refused `touch()` never created the"
            " file; it cannot be reddened there and was not. On this ACCEPTING host the "
            "same assertion is NOT vacuous: a probe-leak control, mutated "
            "tests/unit/test_name_template.py:418 (removed `candidate.unlink()` from the "
            "oracle's accepting tail) -> `uv run pytest tests/unit/test_name_template.py:"
            ":test_the_unmutated_host_decides_the_branch_and_both_instruments_agree -n 0`"
            " -> 1 failed: `AssertionError: the host ACCEPTED the component and the "
            "oracle left its own probe file behind` and `assert not True where True = "
            "exists()`. So the assertion is load-bearing on the accepting leg and "
            "trivially true on the refusing one, exactly as the spec says. Reverted by "
            "restoring the file from its pre-mutation copy (byte-identical to `git show "
            "HEAD:tests/unit/test_name_template.py`; sha256 matched before and after) and"
            " `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC4",
        claim=(
            "AC4 -- an unclassified host answer reds and names the errno. "
            "`_refusing_touch(errno.EACCES)` drives the helper to a red naming errno 13 "
            "and `EACCES`. Failing control: widen `_ENCODING_REFUSAL_ERRNOS` to include "
            "`EACCES` and the arm goes green -- `DID NOT RAISE AssertionError`, the "
            "swallow this verdict exists to prevent."
        ),
        covering=(
            "tests/unit/test_name_template.py::test_an_unclassified_host_answer_reds_the_branch_helper_naming_its_errno",
        ),
        red=(
            "Mutated tests/unit/test_name_template.py:242 (`_ENCODING_REFUSAL_ERRNOS = "
            "frozenset({errno.EILSEQ})` -> `frozenset({errno.EILSEQ, errno.EACCES})`) in "
            "a private detached scratch worktree at base 119f47e. `uv run pytest tests/un"
            "it/test_name_template.py::test_an_unclassified_host_answer_reds_the_branch_h"
            "elper_naming_its_errno -n 0` -> 1 failed: `Failed: DID NOT RAISE "
            "AssertionError` -- with EACCES admitted, the helper returns `recorded` for "
            "an unwritable directory, the swallow the verdict exists to prevent. The "
            "width assertion that fires alongside it is recorded under AC9. Reverted by "
            "restoring the file from its pre-mutation copy (byte-identical to `git show "
            "HEAD:tests/unit/test_name_template.py`; sha256 matched before and after) and"
            " `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC5",
        claim=(
            "AC5 -- the channel exists, publishes on every recorded refusal, and its "
            "message is INVARIANT. `_EncodingRefusalRecorded(UserWarning)` is emitted "
            "from the oracle's recorded branch; the message carries ledger `2b88707a36`, "
            "carrier `B-352`, the codepoint and the errno by symbolic name, and contains "
            "no component text and no errno integer. Failing control: comment out the "
            "`warnings.warn`."
        ),
        covering=(
            "tests/unit/test_name_template.py::test_a_refusing_host_is_recorded_and_published_rather_than_reddened",
        ),
        red=(
            "Three mutations in a private detached scratch worktree at base 119f47e, each"
            " `uv run pytest tests/unit/test_name_template.py::test_a_refusing_host_is_re"
            "corded_and_published_rather_than_reddened -n 0` -> 1 failed. (a) "
            "tests/unit/test_name_template.py:224-225 (dropped `carrier B-352,` from "
            "`_ENCODING_REFUSAL_PUBLICATION`): `AssertionError: the publication dropped "
            "'B-352', so the operator who reads this line in a job log cannot get from it"
            " to the row it is filed under`. (b) tests/unit/test_name_template.py:397 "
            "(appended `+ candidate.name` to the published text, making it vary per "
            "component): `AssertionError: the publication carries component text "
            "('\\U0001239a'), so a host that refuses many generated components scatters "
            "the warnings summary into one distinct line per component`. (c) "
            "tests/unit/test_name_template.py:396-398 (the `warnings.warn(...)` removed "
            "-- the spec's own control): the arm reds on the agreement assertion, "
            "`published 0 encoding refusal(s) rather than exactly one`. The spec's quoted"
            " text `DID NOT WARN. No warnings of type ... were emitted` is NOT what the "
            "landed arm prints: it reads the channel with "
            "`warnings.catch_warnings(record=True)` and asserts a count, not "
            "`pytest.warns`. The control reds; the message differs from the spec's. Not "
            "mutated: the 'no errno integer' clause (`assert str(errno.EILSEQ) not in "
            "message`) and the `issubclass(..., UserWarning)` clause (the latter is "
            "driven under AC6). Reverted by restoring the file from its pre-mutation copy"
            " (byte-identical to `git show HEAD:tests/unit/test_name_template.py`; sha256"
            " matched before and after) and `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC6",
        claim=(
            "AC6 -- THE CLASS'S HOME IS PINNED, AND THE CROSSING IS PROVEN. "
            "`_EncodingRefusalRecorded` is defined in `tests/conftest.py`; the "
            'channel-home arm asserts `__module__ == "conftest"` and `!= __name__`. The '
            "warning is driven uncaught across the worker-to-controller boundary under "
            "the project's real `-n auto`. Failing control: move the class into "
            "`tests/unit/test_name_template.py` and the same command reds 3 of 3 with "
            "`INTERNALERROR ... ModuleNotFoundError: No module named "
            "'test_name_template'`."
        ),
        covering=(
            "tests/unit/test_name_template.py::test_the_publication_channel_is_defined_where_every_process_can_import_it",
            "tests/unit/test_name_template.py::test_the_measured_counterexample_passes_here_and_is_recorded_where_it_is_refused",
        ),
        red=(
            "Three mutations in a private detached scratch worktree at base 119f47e. (a) "
            "tests/conftest.py:209 (`class _EncodingRefusalRecorded(UserWarning)` -> "
            "`(Warning)`): `uv run pytest tests/unit/test_name_template.py::test_the_publ"
            "ication_channel_is_defined_where_every_process_can_import_it -n 0` -> 1 "
            "failed: `AssertionError: the channel's base is Warning, not UserWarning, so "
            "it has silently left the category set PDF-86's landed liveness guard matches"
            " on` and `assert False where False = issubclass(<class "
            "'conftest._EncodingRefusalRecorded'>, UserWarning)`. (b) THE MOVE: a `class "
            "_EncodingRefusalRecorded(UserWarning)` defined at "
            "tests/unit/test_name_template.py:252 and the three "
            "`conftest._EncodingRefusalRecorded` references (lines 396, 444, 987) "
            "re-pointed at it: `uv run pytest tests/unit/test_name_template.py::test_the_"
            "publication_channel_is_defined_where_every_process_can_import_it -n 0` -> "
            "`AssertionError: the publication channel is defined in 'test_name_template'."
            " Under `-n auto` the xdist CONTROLLER rebuilds a reported warning by "
            "importing that module ...` and `assert 'test_name_template' == 'conftest'`. "
            "(c) The crossing, same move, `uv run pytest tests/unit/test_name_template.py"
            " -n 2` three times: 3 of 3 exit 3, each `.......!!!!!!!!!!!!!!!!!!!! "
            "<ExceptionInfo ModuleNotFoundError(\"No module named 'test_name_template'\") "
            "tblen=6>` with `INTERNALERROR>` frames in `xdist/workermanage.py` "
            "`unserialize_warning_message` -> "
            '`importlib.import_module(data["message_module"])`. (The spec\'s trailing '
            "`node down` / `KeyError: <WorkerController gwN>` lines were not read: the "
            "output was filtered to its first lines.) Unmutated, the same module under "
            "`-n 2` is 21 passed with exit 0, with the channel warning rendered in the "
            "warnings summary. -n 2 was used instead of the project's `-n auto` because "
            "this host is shared; the crossing mechanism is the same. Reverted by "
            "restoring the file from its pre-mutation copy (byte-identical to `git show "
            "HEAD:tests/unit/test_name_template.py and tests/conftest.py`; sha256 matched"
            " before and after) and `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC7",
        claim=(
            "AC7 -- `event()` is not silenced, and the guard is the exception-shaped one."
            " The oracle still calls `event(verdict.event_name)`, wrapped in `try/except "
            "InvalidArgument`. The property's `_REFUSED` / `_RETURNED` events are "
            "unchanged and `--hypothesis-show-statistics` still names both at their "
            "pre-change shares. Failing control: substitute `currently_in_test_context()`"
            " and half 2 reds with `recorded == []`."
        ),
        covering=(
            "tests/unit/test_name_template.py::test_the_measured_counterexample_passes_here_and_is_recorded_where_it_is_refused",
        ),
        red=(
            "GUARD SHAPE driven: mutated tests/unit/test_name_template.py:412-415 (the "
            "`try: event(verdict.event_name) except InvalidArgument: pass` replaced by "
            "`if currently_in_test_context(): event(verdict.event_name)`) in a private "
            "detached scratch worktree at base 119f47e; `uv run pytest tests/unit/test_na"
            "me_template.py::test_the_measured_counterexample_passes_here_and_is_recorded"
            "_where_it_is_refused -n 0` -> 1 failed: `AssertionError: the encoding "
            "refusal recorded []; an observation nobody emits is an observation the "
            'operator never sees in --hypothesis-show-statistics` and `assert [] == ["the'
            " filesystem refused the component's ENCODING, not its length\"]`. STATISTICS "
            "HALF NOT DRIVEN TO RED: mutated tests/unit/test_name_template.py:572 "
            "(removed `event(_REFUSED)` from the property's `except "
            "OutputEscapesDirError` branch) -> `uv run pytest "
            "tests/unit/test_name_template.py -n 0` -> 21 passed, 1 warning. Nothing "
            "asserts that the property's `_REFUSED`/`_RETURNED` events exist or what "
            "shares they hold, so that clause of the AC has no standing control; it is a "
            "clause about an operator-facing meter, checked only by running "
            "`--hypothesis-show-statistics` by hand. Reverted by restoring the file from "
            "its pre-mutation copy (byte-identical to `git show "
            "HEAD:tests/unit/test_name_template.py`; sha256 matched before and after) and"
            " `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-88-ac7-statistics-event-shares-have-no-standing-control",
    ),
    ACAudit(
        ac="AC8",
        claim=(
            "AC8 -- halves 2 and 3 survive BYTE-IDENTICALLY. `git diff` shows no edit "
            "inside the halves-2-and-3 region. Both pass unchanged and unedited. Failing "
            "control: confirm from the diff, not from a test result."
        ),
        covering=(),
        red=(
            "COMMAND: a property of the landed commit `0283279`, and the spec itself says"
            " to confirm it 'from the diff, not from a test result'. The spec's line "
            "range (`:588-607`) is stale at the base, so the region was taken by content."
            " Re-run: for r in `0283279^` and `0283279`, `git show "
            "$r:tests/unit/test_name_template.py | awk '/^    recorded: list\\[str\\] = "
            "\\[\\]/{f=1} f&&(/^# ---/||/^def test_the_conftest_profile/){exit} f'` -> 22 "
            "lines each, sha256 prefix `9a860cea96ae7e8a` both, and `diff` of the two "
            "extractions prints nothing. The same extraction method over `def "
            "_classify_filesystem_refusal` up to `def _the_filesystem_accepts` is also "
            "identical across the two commits (this is AC13's 'byte-untouched classifier'"
            " clause). No command-level red was driven (no plant of an edited half-2 line"
            " was run against the command): NOT_OBSERVED."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-88-landed-diff-acs-have-no-standing-control",
    ),
    ACAudit(
        ac="AC9",
        claim=(
            "AC9 -- `_ENCODING_REFUSAL_ERRNOS` is still exactly one member wide, "
            "`errno.EILSEQ`, symbolic. The roster arm and its width assertion are "
            "unchanged, unedited and green. Failing control: empty the allowlist and "
            "watch the roster arm red naming the retirement."
        ),
        covering=(
            "tests/unit/test_name_template.py::test_the_classifier_answers_every_roster_errno_with_one_of_three_verdicts[ENAMETOOLONG]",
            "tests/unit/test_name_template.py::test_the_classifier_answers_every_roster_errno_with_one_of_three_verdicts[EILSEQ]",
            "tests/unit/test_name_template.py::test_the_classifier_answers_every_roster_errno_with_one_of_three_verdicts[EACCES]",
            "tests/unit/test_name_template.py::test_the_classifier_answers_every_roster_errno_with_one_of_three_verdicts[ENOENT]",
            "tests/unit/test_name_template.py::test_the_classifier_answers_every_roster_errno_with_one_of_three_verdicts[ENOSPC]",
        ),
        red=(
            "Mutated tests/unit/test_name_template.py:242 (`frozenset({errno.EILSEQ})` ->"
            " `frozenset()`) in a private detached scratch worktree at base 119f47e. `uv "
            "run pytest tests/unit/test_name_template.py::test_the_classifier_answers_eve"
            "ry_roster_errno_with_one_of_three_verdicts -n 0` -> 5 failed (all five "
            "roster ids): `AssertionError: the recorded-verdict allowlist is no longer "
            "exactly one member wide. The narrowing PDF-85 landed is exactly one verdict "
            "wide ... an empty allowlist retires the one observation this arm exists to "
            "carry` and `assert 0 == 1 where 0 = len(frozenset())`. The widening "
            "direction (a second member) reds the same assertion; see PDF-85 AC4 (`assert"
            " 2 == 1`), which also covers the roster. Reverted by restoring the file from"
            " its pre-mutation copy (byte-identical to `git show "
            "HEAD:tests/unit/test_name_template.py`; sha256 matched before and after) and"
            " `git diff --exit-code` returned 0."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC10",
        claim=(
            "AC10 -- no platform, no predicate, no skip. `git diff` contains no "
            "`sys.platform`, no `darwin`, no `unicodedata`, no codepoint allowlist, no "
            "`@pytest.mark.skip`, no `xfail`, no `pytest.skip()`. Failing control: grep "
            "the diff for `skip|xfail|platform|darwin|unicodedata` and record that the "
            "count is zero. A non-zero count is a BLOCKER, not a judgement call."
        ),
        covering=(),
        red=(
            "COMMAND: a property of the landed commit `0283279`. THE SPEC'S LITERAL "
            "COMMAND IS NON-ZERO. Re-run at base 119f47e: `git show 0283279 -- "
            "tests/unit/test_name_template.py tests/conftest.py | grep -E '^\\+' | grep "
            "-vE '^\\+\\+\\+' | grep -ciE 'skip|xfail|platform|darwin|unicodedata'` -> 6. "
            "All six are added prose, none is code: a comment ('and skips a channel the "
            "caller had already put in domain'), a comment ('handed UP as a measurement "
            "and never skipped'), a docstring line ('platform branch.** It does not ask "
            "which platform is running'), a docstring ('arm that runs on both "
            "platforms'), a docstring ('on the exact platform where its own claim was "
            "false') and a docstring ('handed up, never skipped'). `unicodedata` accounts"
            ' for 0 of the 6. The structural count, re-runnable: `python3 -c "import '
            "ast,subprocess as s;c=lambda r,p:sum(isinstance(n,ast.Attribute) and n.attr "
            "in{'skip','xfail','skipif','platform'} or isinstance(n,ast.Constant) and "
            "n.value=='darwin' for n in ast.walk(ast.parse(s.check_output(['git','show',r"
            "+':'+p],text=True))));print([c('0283279',p)-c('0283279^',p) for p in "
            "('tests/unit/test_name_template.py','tests/conftest.py')])\"` -> `[0, 0]`: no"
            " skip/xfail/skipif attribute, no `platform` attribute and no `'darwin'` "
            "literal was added by the commit. By the spec's own wording the literal "
            "non-zero count is a BLOCKER; this module hands it up as a finding and does "
            "not adjudicate it. No command-level red was driven: NOT_OBSERVED."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-88-ac10-literal-grep-is-nonzero-on-prose",
    ),
    ACAudit(
        ac="AC11",
        claim=(
            "AC11 -- `src/` is untouched and the diff is exactly three files. `git diff "
            "--stat -- src/` is empty; `safety/naming.py` and `safety/atomic.py` are "
            "byte-identical to `76437a8`; `git diff --stat` lists exactly "
            "`tests/conftest.py`, `tests/unit/test_name_template.py` and `changelog.md`. "
            "Any fourth file is a BLOCKER."
        ),
        covering=(),
        red=(
            "COMMAND: a property of the landed commit `0283279`. Re-run at base 119f47e: "
            "`git diff --stat 0283279^ 0283279 -- src/ | wc -l` -> 0; `git show --stat "
            "--format= 0283279` -> exactly `changelog.md | 8 +`, `tests/conftest.py | 55 "
            "+++`, `tests/unit/test_name_template.py | 427 ++++++--` (3 files changed, "
            "478 insertions, 12 deletions); `git merge-base --is-ancestor 76437a8 "
            "0283279` exit 0 and `git diff --exit-code 76437a8 0283279 -- "
            "src/pdf_tooling/safety/naming.py src/pdf_tooling/safety/atomic.py` exit 0. "
            "`tests/test_import_boundaries.py` is not among the three. No command-level "
            "red was driven: NOT_OBSERVED."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-88-landed-diff-acs-have-no-standing-control",
    ),
    ACAudit(
        ac="AC12",
        claim=(
            "AC12 -- no ceiling, count or bound moved. `tests/test_docs_antirot.py` "
            "passes; the four residues are unchanged at 29 / 7 / 6 / 127; "
            "`hypothesis_explicit_examples` is still 60 and "
            "`test_every_seed_value_is_guaranteed_under_every_template` passes unchanged "
            "and unedited; every `*_CEILING` in `tests/` is unedited; `.github/` and "
            "`perf/suite-size.md` are unedited."
        ),
        covering=(),
        red=(
            "COMMAND: a property of the landed commit `0283279`. Re-run at base 119f47e: "
            "`git show 0283279 | grep -E '^\\+' | grep -cE 'CEILING|RESIDUE'` -> 0 added "
            "lines mention a ceiling or residue, and `git show --stat --format= 0283279` "
            "names no file under `.github/`, no `perf/suite-size.md` and no test file "
            "other than `tests/conftest.py` and the audited module. The explicit-example "
            "count was measured at the BASE, not at landing: `len(test_render_name_either"
            "_raises_or_returns_a_single_contained_component.hypothesis_explicit_examples"
            ")` -> 60 (12 seeds x 5 templates), consistent with the AC but unpinned by "
            "any arm (see PDF-85 AC9). The residue figures 29 / 7 / 6 / 127 were NOT "
            "re-derived: they were measured at landing and the guarded documents have "
            "moved since. No command-level red was driven: NOT_OBSERVED."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-88-landed-diff-acs-have-no-standing-control",
    ),
    ACAudit(
        ac="AC13",
        claim=(
            "AC13 -- the two false sentences are corrected and the true one is kept. "
            "`_ENCODING_REFUSED`'s comment no longer claims the statistics meter shows "
            "the operator this observation, and says what does; the arm's docstring "
            "states the premise is measured at runtime. The classifier's deviation "
            "docstring is byte-untouched. Failing control: a reader's test."
        ),
        covering=(),
        red=(
            "UNREDDENABLE: the spec's own failing control is a person reading the diff, "
            "and no assertion in the suite reads the prose it concerns. A mechanical red "
            "was attempted and none exists: in the scratch worktree at 119f47e the "
            "`_ENCODING_REFUSED` comment's 'PDF-88 CORRECTS THE CLAIM THIS COMMENT USED "
            "TO MAKE' paragraph was replaced by `REDACTED`, and `uv run pytest "
            "tests/unit/test_name_template.py tests/test_docs_antirot.py "
            "tests/test_docstring_pointers.py -n 2` -> 279 passed, 9 skipped (the skips "
            "are `test_docs_antirot.py:2203`, no planning tree on this host), 0 failed. "
            "Reverted from the pre-mutation copy; sha256 matched; `git diff --exit-code` "
            "returned 0. The one mechanical clause of this AC, 'the classifier is "
            "byte-untouched', is a landed-diff fact and is recorded under AC8 (the "
            "classifier function text is identical across `0283279^` and `0283279`)."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-88-ac13-readers-test-has-no-mechanical-red",
    ),
    ACAudit(
        ac="AC14",
        claim=(
            "AC14 -- the suite is green in both gates, the cost is reported, and the "
            "changelog lands in this commit. `make test` and `make ci` are each run and "
            "reported separately; the module's wall clock is recorded against the 2.77s "
            "baseline; the collected count moves from 17 to 17 plus this spec's arms. One"
            " DCO-signed commit staging explicit paths, subject tagged `[PDF-88]`, with "
            "exactly one `## [PDF-88]` entry directly below the anchor."
        ),
        covering=(),
        red=(
            "COMMAND: a landed-commit and run-time property. Re-run at base 119f47e: `git"
            " show 0283279 -- changelog.md | grep -E '^\\+## \\[PDF-88\\]'` -> exactly one "
            "line (`+## [PDF-88] Derive the acceptance premise from the host the arm runs"
            " on -- 2026-09-18`), and `... | grep -cE '^-[^-]'` -> 0 removed lines. `git "
            "show $r:tests/unit/test_name_template.py | grep -c '^def test_'` -> 13 at "
            "`0283279^` and 17 at `0283279` (four new arms; with the five-way "
            "parametrized roster the collected count is 17 -> 21, and the module collects"
            " 21 at the base). `git show --stat --format= 0283279` -> 3 files, as AC11. "
            "`make test`, `make ci`, the 2.77s wall-clock baseline and the DCO trailer "
            "were NOT re-derived by this audit. No command-level red was driven: "
            "NOT_OBSERVED."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-88-landed-diff-acs-have-no-standing-control",
    ),
    ACAudit(
        ac="AC15",
        claim=(
            "AC15 -- the macOS legs are the last word, and the criterion is an "
            "OBSERVATION scoped to this file. After the change lands and is pushed, the "
            "four `test (3.1x, macos-14)` legs no longer fail on "
            "`tests/unit/test_name_template.py`, and the run id and the four job ids are "
            "recorded. This discharges `PDF-85`'s `AC14`, which `X-854` transferred here."
            " Nothing asserts this criterion and nothing skips waiting for it."
        ),
        covering=(),
        red=(
            "CI-EVIDENCED: observation queried LIVE at audit time, not transcribed. `gh "
            "run view 37230496908 --repo ArmandoHerra/pdf-tooling --json headSha,jobs` "
            "(workflow CI, event push to main) -> headSha "
            "119f47e8e2eaf311c6870e4255d77fff215b19e8; `test (3.11, macos-14)` id "
            "111518947001 conclusion success; `test (3.12, macos-14)` id 111518947102 "
            "conclusion success; `test (3.13, macos-14)` id 111518947015 conclusion "
            "success; `test (3.14, macos-14)` id 111518947144 conclusion success (the "
            "four ubuntu-latest legs, ids 111518946923, 111518946978, 111518947055, "
            "111518947185, also success). `git merge-base --is-ancestor 0283279 "
            "119f47e8e2eaf311c6870e4255d77fff215b19e8` exit 0, so the run includes "
            "PDF-88's landing commit `0283279`. No macos-14 leg failed on this file or on"
            " any file: the four jobs' pytest summaries read `5436 passed, 202 skipped, 3"
            " xfailed` (3.11, 3.12, 3.13) and `5435 passed, 203 skipped, 3 xfailed` "
            "(3.14). The published channel line is present once in each of the four "
            "macos-14 job logs (`gh api "
            "repos/ArmandoHerra/pdf-tooling/actions/jobs/<id>/logs`), at "
            "`tests/unit/test_name_template.py:396`, and its text equals "
            "`_ENCODING_REFUSAL_PUBLICATION` verbatim; BUT the ubuntu-latest 3.11 job (id"
            " 111518946923) carries the same single line, because half 2 of the "
            "measured-counterexample arm injects a refusing `touch` and publishes on "
            "every host. The line therefore does NOT evidence a real macOS refusal; the "
            "spec's hoped-for first record of the macOS refusal as an observation is NOT "
            "established by these logs. Whether this green run discharges `PDF-85`'s "
            "`AC14` under `X-854`'s named condition is the project-manager's ruling; this"
            " module records the observation only. Nothing asserts this criterion and no "
            "mutation can red it."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-88-ac15-macos-legs-are-a-ci-only-observation",
    ),
)
