"""`PDF-03`'s 20 acceptance criteria, re-derived — `AUDIT-CONVENTION(PDF-17)`.

`PDF-03` (`SPEC-INDEX.md`) carried **`Implemented (2026-08-29)`** and nothing
else: its twenty criteria were granted in one pass by their own author and no
independent instrument had touched them since. One module parses every
`PLAN.md` §4.3 token for every page-addressing verb, so a divergence between
the documented grammar and the parsed grammar surfaces as **a wrong page set
with exit 0**, not as an error.

**Verdict counts — 15 `UPHELD` · 3 `REPAIRED` · 2 `FINDING` = 20.**

`ACAudit` has no `verdict` field and `_model.py` is frozen, so `PDF-27`'s
three-value vocabulary is mapped onto the landed fields (declared deviation
C-1):

* **`UPHELD`** — a `red_kind` other than `NOT_OBSERVED`, with the mutation,
  the failure and the revert recorded in `red`. AC1..AC7, AC9, AC11..AC13,
  AC15..AC18.
* **`REPAIRED`** — the same, and the `red` additionally records **the original
  control's demonstrated weakness: the mutation that left it GREEN.** AC8,
  AC10, AC14.
* **`FINDING`** — `red_kind=NOT_OBSERVED` plus a real `finding`. AC19, AC20.

Every mutation below was applied to the working tree, observed, and reverted
by copying back `git show HEAD:<path>`; `git diff --exit-code` proved each
revert exact before the next one was applied, and no mutation ever reached the
index (HC-4: never `git stash`). Reds were observed against
`tests/test_pagerange.py` as `PDF-27` found it — a 52-test non-property band
that runs in ~0.5 s, so every row's red is a real run rather than a reading.

Two figures the audited spec's Implementation Log asserts are **contradicted
by measurement at HEAD** and are recorded in AC19's row rather than smoothed:
the module is no longer at "100% / 103 statements" (it is 120 statements /
**88%** as `PDF-27` found it), because `743853f [PDF-07]` added seventy lines
to it and zero lines to its test file.
"""

from __future__ import annotations

from typing import Final

from acceptance._model import ACAudit, RedKind

SPEC_ID: Final[str] = "PDF-03"
AC_COUNT: Final[int] = 20

AUDIT: Final[tuple[ACAudit, ...]] = (
    ACAudit(
        ac="AC1",
        claim=(
            "src/pdf_toolkit/ops/pagerange.py exists and importing parse, render, "
            "GRAMMAR_HELP, PageRangeError, EMPTY_SELECTION_EXIT_CODE exits 0. The module's "
            "__all__ is exactly those five names."
        ),
        covering=("tests/test_pagerange.py::test_ac1_public_surface",),
        red=(
            'Appended "is_valid_spec" to pagerange.__all__ at '
            "src/pdf_toolkit/ops/pagerange.py:67; test_ac1_public_surface failed with "
            "`AssertionError: assert {...6 names...} == {...5 names...}`; reverted from "
            "git show HEAD:<path>, git diff --exit-code clean, 52 passed again. AUDITED AS "
            "INTENT, NOT LUCK: 743853f [PDF-07] added is_valid_spec and ALL_PAGES_TOKEN and "
            "deliberately kept both OUT of __all__, with the reason written at "
            "pagerange.py:56-61. The criterion is genuinely upheld against a file seventy "
            "lines longer than the one it was written for."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC2",
        claim=(
            "Every row of the PLAN.md §4.3 token table has a passing test: "
            "`pytest -k token_table` is green, and test_token_table_covers_every_plan_row "
            "asserts the covered row ids are exactly {1..10}."
        ),
        covering=(
            "tests/test_pagerange.py::test_token_table[row1_N: single page]",
            "tests/test_pagerange.py::test_token_table[row2_A-B: closed ascending range]",
            "tests/test_pagerange.py::test_token_table[row3_B-A: closed descending range, order "
            "preserved]",
            "tests/test_pagerange.py::test_token_table[row4_N-: open-ended]",
            "tests/test_pagerange.py::test_token_table[row5_-N: negative index]",
            "tests/test_pagerange.py::test_token_table[row6_first: first page]",
            "tests/test_pagerange.py::test_token_table[row6_last: last page]",
            "tests/test_pagerange.py::test_token_table[row7_even: every even page]",
            "tests/test_pagerange.py::test_token_table[row7_odd: every odd page]",
            "tests/test_pagerange.py::test_token_table[row8_all: every page]",
            "tests/test_pagerange.py::test_token_table[row9_!TOKEN: exclude]",
            "tests/test_pagerange.py::test_token_table[row10_,: union, left to right (with "
            "exclusion)]",
            "tests/test_pagerange.py::test_token_table_covers_every_plan_row",
        ),
        red=(
            "TWELVE distinct mutations, one per parametrized case (ten §4.3 rows; rows 6 and "
            "7 carry two cases each, and each case got its own). Each applied, observed, "
            "reverted, re-run green: row1 `return [n]`->`[n + 1]`; row2 exclusive range end "
            "`range(first, second + step, step)`->`range(first, second, step)`; row3 "
            "`step = 1 if second >= first else -1`->`step = 1` (5-1 resolved to ()); row4 "
            "`range(start, page_count + 1)`->`range(start, page_count)`; row5 "
            "`page_count - magnitude + 1`->`page_count - magnitude`; row6a first `[1]`->`[2]`; "
            "row6b last `[page_count]`->`[page_count - 1]`; row7a even `i % 2 == 0`->`== 1`; "
            "row7b odd `i % 2 == 1`->`== 0`; row8 all `range(1, ...)`->`range(2, ...)`; row9 "
            "`excluded = set(resolved)`->`set()`; row10 `running.extend(resolved)`->"
            "`running = resolved + running`. Each named case went red. Collateral recorded "
            "rather than hidden: row1's mutation also reds row9/row10/ac4/ac5, row2's also "
            "reds row3/row10, row8's also reds row9. The META-test carries its own "
            "DELETED_ROW red: deleting the row10 _TokenCase from TOKEN_TABLE_CASES failed "
            "test_token_table_covers_every_plan_row on `{1..9} == {1..10}`."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC3",
        claim=(
            "Every row of the PLAN.md §4.3 error table has a passing test: "
            "`pytest -k error_table` is green, and test_error_table_covers_every_plan_row "
            "asserts the covered row ids are exactly {1..7} AND that the literal inputs 0, "
            '1-0, abc, 1--3, 1-2-3, ",", "", 50, -50, all,!all, even, 9- all appear as cases.'
        ),
        covering=(
            "tests/test_pagerange.py::test_error_table[row1_literal 0 is not 1-based]",
            "tests/test_pagerange.py::test_error_table[row1_1-0: zero endpoint is not 1-based]",
            "tests/test_pagerange.py::test_error_table[row2_malformed: abc]",
            "tests/test_pagerange.py::test_error_table[row2_malformed: 1--3 (negative endpoint in "
            "a range)]",
            "tests/test_pagerange.py::test_error_table[row2_malformed: 1-2-3]",
            "tests/test_pagerange.py::test_error_table[row2_malformed: , (bare comma)]",
            "tests/test_pagerange.py::test_error_table[row2_malformed: empty spec]",
            "tests/test_pagerange.py::test_error_table[row3_50 out of range on a 10-page document]",
            "tests/test_pagerange.py::test_error_table[row4_-50 out of range on a 10-page "
            "document]",
            "tests/test_pagerange.py::test_error_table[row5_all,!all resolves to nothing]",
            "tests/test_pagerange.py::test_error_table[row6_even on a 1-page document]",
            "tests/test_pagerange.py::test_error_table[row7_9- open-ended start out of range on a "
            "5-page document]",
            "tests/test_pagerange.py::test_error_table_covers_every_plan_row",
        ),
        red=(
            "SEVEN distinct mutations, one per §4.3 error row, each applied/observed/"
            "reverted/re-run green: row1 `_validate_endpoint`'s `if n == 0:`->`if n == -1:` "
            "(both row1 cases red); row2 the sole malformed fallthrough "
            "`raise _malformed(...)`->`return []` (all five row2 cases red); row3 the "
            "single-page `_validate_endpoint(n, ...)` call deleted; row4 `_resolve_negative`'s "
            "`if resolved < 1:`->`if resolved < -100:`; row5 the exclusion predicate inverted "
            "(`i not in excluded`->`i in excluded`), so all,!all resolved to (1..10) instead "
            "of (); row6 a `if not running: raise` inserted before parse()'s normalization, "
            "so an empty-but-valid selection raised (rows 5 AND 6 red -- this is the "
            "mutation PDF-27 AC4 names for the two empty-selection rows); row7 the open-end "
            "`_validate_endpoint(start, ...)` call deleted, red on row7 ALONE. Row3's "
            "mutation also reds row1_literal_0, since the deleted call is the same guard. "
            "The META-test carries its own DELETED_ROW red: deleting the `9-` _ErrorCase "
            "failed test_error_table_covers_every_plan_row on `{1..6} == {1..7}`, and its "
            "required_literal_inputs subset assertion is a genuinely strong second control "
            "that was confirmed rather than weakened."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC4",
        claim=(
            'Order semantics: parse("1,1,3", 10, ordered=True).indices == (1, 1, 3); '
            'parse("5-1", 10, ordered=True).indices == (5, 4, 3, 2, 1); the same two specs '
            "with ordered=False yield (1, 3) and (1, 2, 3, 4, 5)."
        ),
        covering=(
            "tests/test_pagerange.py::test_ac4_order_semantics",
            "tests/test_pagerange.py::test_property_p3_order_vs_set",
        ),
        red=(
            "Inverted parse()'s single normalization switch at pagerange.py:332: "
            "`tuple(running) if ordered else tuple(sorted(set(running)))` -> "
            "`tuple(sorted(set(running))) if ordered else tuple(running)`. "
            "test_ac4_order_semantics failed on `assert (1, 3) == (1, 1, 3)`; row3 and "
            "test_ac5_exclusion_left_to_right_order red as collateral. Reverted, 52 passed. "
            "SECOND, INDEPENDENT RED on the ordered=False half: dropping `sorted` "
            "(`tuple(sorted(set(running)))`->`tuple(set(running))`) failed "
            "test_property_p3_order_vs_set on `assert (8, 1) == ...` over 1000 examples, and "
            "so did sorting descending. Both order semantics carry a red of their own."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC5",
        claim=(
            'Left-to-right exclusion order: parse("all,!3", 5, ordered=False).indices == '
            '(1, 2, 4, 5); parse("!3,all", 5, ordered=False).indices == (1, 2, 3, 4, 5); '
            'parse("1-3,!2,2", 10, ordered=True).indices == (1, 3, 2).'
        ),
        covering=(
            "tests/test_pagerange.py::test_ac5_exclusion_left_to_right_order",
            "tests/test_pagerange.py::test_property_p4_exclusion_exactness",
        ),
        red=(
            "Made exclusions GLOBAL instead of left-to-right: added a `deferred: set[int]` "
            "beside `running` in parse(), replaced the in-loop subtraction with "
            "`deferred.update(resolved)`, and subtracted once after the loop. "
            'test_ac5_exclusion_left_to_right_order failed -- "!3,all" then yields '
            "(1, 2, 4, 5) instead of (1, 2, 3, 4, 5) -- with "
            "test_ac15_leading_exclusion_warns_exactly_once red as collateral. Both edits "
            "reverted together, git diff --exit-code clean, 52 passed. SECOND RED on the "
            "exactness half: making the exclusion remove only the FIRST occurrence "
            "(`running.remove(value)` in a loop) failed test_property_p4_exclusion_exactness."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC6",
        claim=(
            'Empty selection never raises: parse("all,!all", 10) and parse("even", 1) each '
            "return a PageRange with indices == () and is_empty is True."
        ),
        covering=(
            "tests/test_pagerange.py::test_ac6_empty_selection_never_raises",
            "tests/test_pagerange.py::test_error_table[row5_all,!all resolves to nothing]",
            "tests/test_pagerange.py::test_error_table[row6_even on a 1-page document]",
        ),
        red=(
            "Inserted `if not running: raise _malformed(spec, spec, 1)` immediately before "
            "parse()'s normalization line. test_ac6_empty_selection_never_raises failed with "
            "`pdf_toolkit.errors.PageRangeError`, together with error-table rows 5 and 6 and "
            "test_ac11_render_is_canonical. Reverted, 52 passed. Declared: this is the same "
            "mutation as error row 6's -- distinctness is required PER §4.3 ROW within the "
            "two tables (PDF-27 AC3/AC4), and raising on an empty selection is the honest "
            "mutation for this criterion as well as for that row."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC7",
        claim=(
            "Exit codes are derived, not literal: pagerange.EMPTY_SELECTION_EXIT_CODE == "
            "errors.NoInputError.exit_code == 4, and PageRangeError.exit_code == 2; no "
            "exit-code integer literal appears in the module "
            '(grep -nE "=\\s*[24]\\s*(#|$)" finds none).'
        ),
        covering=(
            "tests/test_pagerange.py::test_ac7_exit_codes_are_derived_not_literal",
            "tests/test_pagerange.py::test_ac7_no_exit_code_integer_literal_in_module",
        ),
        red=(
            "Replaced `EMPTY_SELECTION_EXIT_CODE: Final[int] = NoInputError.exit_code` at "
            "pagerange.py:81 with `= 4`. test_ac7_no_exit_code_integer_literal_in_module "
            "failed on `assert <re.Match...> is None` -- the grep regex does catch a literal "
            "at line end, and it fails rather than merely warning. Reverted, 52 passed. "
            "FILED ALONGSIDE, not smoothed: test_error_table's empty-selection arm asserts "
            "`pagerange.EMPTY_SELECTION_EXIT_CODE == 4` -- a literal 4 in a TEST that pins "
            "the echoed value, which is the B-073 shape. It should read "
            "`errors.NoInputError.exit_code`. Not changed here: it is a live control this "
            "audit is measuring, and rewriting an assertion mid-audit is how an auditor "
            "becomes an author."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-03-ac7-error-table-pins-the-echoed-exit-code-4",
    ),
    ACAudit(
        ac="AC8",
        claim=(
            "PageRangeError carries spec, token, column (1-based) and reason; for "
            'parse("1-3,abc", 10) the raised error has token == "abc", column == 5, and its '
            'message contains "abc" and column 5.'
        ),
        covering=(
            "tests/test_pagerange.py::test_ac8_error_carries_token_and_column",
            "tests/test_pagerange.py::test_whitespace_table[the column is the token's first "
            "NON-SPACE character]",
            "tests/test_pagerange.py::test_whitespace_table[internal whitespace is malformed, with "
            "the offending token quoted]",
            "tests/test_pagerange.py::test_whitespace_table[outer whitespace is stripped and "
            "resolves identically]",
        ),
        red=(
            "REPAIRED. Original weakness, MEASURED: `_split_tokens` computes the column as "
            "`pos + leading + 1`, and dropping the `leading` term alone "
            "(`pos + leading + 1`->`pos + 1`) left the ENTIRE 52-test band GREEN -- no test "
            "anywhere passed a spec containing whitespace, so a third of the column "
            "arithmetic had no control at all while AC8 read as covered. The +1 half did "
            "fire: `pos + leading + 1`->`pos + leading` failed "
            "test_ac8_error_carries_token_and_column on `assert 4 == 5` plus five row2 "
            "error cases. REPAIR: a three-case WHITESPACE_CASES table (PDF-27 §D9), kept out "
            "of the two §4.3 tables so their row counts stay 10 and 7. New red: with "
            "`leading` dropped, test_whitespace_table[the column is the token's first "
            'NON-SPACE character] fails on parse("1-3,  abc") reporting column 5 instead of '
            "7. Second new red: dropping the `.strip()` "
            "(`part.strip()`->`part`) fails the outer-whitespace case too. Reverted, green."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC9",
        claim=(
            'PLAN §12 R-04 hint: parse("-50", 10) raises PageRangeError whose message '
            "contains the literal 1-50, the word negative, the resolved index, and "
            '"document has 10 pages". A resolvable negative index emits no hint: '
            'parse("-3", 10, ordered=True).indices == (8,) and nothing is logged.'
        ),
        covering=(
            "tests/test_pagerange.py::test_ac9_negative_index_hint_message",
            "tests/test_pagerange.py::test_ac9_resolvable_negative_index_is_silent",
            "tests/test_pagerange.py::test_r04_negative_index_hint[out-of-range negative gets the "
            "open-left hint]",
            "tests/test_pagerange.py::test_r04_negative_index_hint[resolvable negative index is "
            "silent]",
            "tests/test_pagerange.py::test_r04_negative_index_hint[-page_count resolves to the "
            "first page]",
        ),
        red=(
            "Deleted the open-left clause from _resolve_negative's message "
            '(`did you mean the open-left range "1-{magnitude}"?` -> `from the end.`). '
            "test_ac9_negative_index_hint_message failed on the missing `1-50`, together "
            "with the r04 hint case and error-table row4. Reverted, 52 passed. SECOND, "
            "INDEPENDENT RED on the silence half: `page_count - magnitude + 1`->"
            '`page_count - magnitude` makes parse("-3", 10) resolve to (7,) and fails '
            "test_ac9_resolvable_negative_index_is_silent. Three controls, one of them a "
            "silence assertion (`caplog.records == []`); confirmed strong rather than taken "
            "on trust."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC10",
        claim=(
            "The five named invariants P1-P5 (Design D8) each have a hypothesis test "
            "decorated @settings(max_examples=1000, deadline=None), and "
            "`pytest -k property` is green with no counterexample and no Flaky/"
            "FailedHealthCheck outcome."
        ),
        covering=(
            "tests/test_pagerange.py::test_ac10_named_invariants_are_selectable_and_number_five",
            "tests/test_pagerange.py::test_property_p1_totality",
            "tests/test_pagerange.py::test_property_p2_bounds_and_coverage",
            "tests/test_pagerange.py::test_property_p3_order_vs_set",
            "tests/test_pagerange.py::test_property_p4_exclusion_exactness",
            "tests/test_pagerange.py::test_property_p5_render_round_trip",
        ),
        red=(
            "REPAIRED, and repaired FIRST, before any property was added. Original "
            'weakness, MEASURED by driving the original body ("count test names containing '
            "'property', assert == 5\") against three inputs: it goes RED when one of the "
            "five is renamed (counted 4 -- correct), RED when a SIXTH property test is added "
            "(counted 6 -- ANTI-ADDITIVE: it blocks its own strengthening, and the cheap "
            "repair is `>= 5`, which throws away the deletion red), and GREEN when an "
            "invariant's body is emptied while its name is kept. REPAIR: a NAMED_INVARIANTS "
            "roster asserting the five by name, each present, callable, name selectable by "
            "`-k property`, and carrying max_examples=1000 with deadline=None. Red two ways "
            "as PDF-27 AC8 requires, both observed: renaming test_property_p3_order_vs_set "
            "to ..._versus_... FAILED the repaired control; adding a sixth "
            "@settings(max_examples=1000)-decorated property test left it PASSING. A third "
            "red the original could not produce: changing one invariant's max_examples from "
            "1000 to 50 fails it. Each of P1-P5 additionally carries its OWN red: P1 -- "
            "page_count guard raises ValueError; P2 -- last -> page_count + 1; P3 -- sorted "
            "dropped; P4 -- exclusion removes only the first occurrence; P5 -- render() "
            "compresses runs. All reverted; 63 passed."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC11",
        claim=(
            'render() is canonical: render(parse("1-3,last", 10, ordered=True)) == '
            '"1,2,3,10"; render() of an empty selection is ""; parse("") raises '
            "PageRangeError."
        ),
        covering=(
            "tests/test_pagerange.py::test_ac11_render_is_canonical",
            "tests/test_pagerange.py::test_property_p5_render_round_trip",
        ),
        red=(
            "Replaced render()'s comma-join with a run compressor, so "
            '"1,2,3,10" became "1-3,10". test_ac11_render_is_canonical failed on the '
            "AssertionError comparing the two strings; reverted, 52 passed. WHICH FIRES "
            "FIRST, measured rather than guessed: in a `-k 'not property'` band only "
            "test_ac11_render_is_canonical is collected and it is the only failure; running "
            "`-k p5_render` alone under the same mutation ALSO fails "
            "test_property_p5_render_round_trip. Two independent controls, and the criterion "
            "does not depend on either one alone."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC12",
        claim=(
            "Unwired, checkably. After this spec lands: `pdftoolkit --help` prints no "
            "--pages and no --ranges; for every subcommand V the same holds; and "
            '`grep -rn "pagerange" src/pdf_toolkit/cli/` returns nothing.'
        ),
        covering=("tests/test_pagerange.py::test_the_page_range_grammar_has_exactly_one_owner",),
        red=(
            "ONE row, not two: `check_the_ac_roster_is_contiguous` requires exactly "
            "AC1..AC20, so PDF-27 §D5's two-row shape is folded into this row's two halves "
            "(declared deviation C-2). "
            "HISTORICAL HALF, re-derived from git and re-derivable forever without this "
            'spec\'s context: `git grep -n "pagerange" 9d0703d -- src/pdf_toolkit/cli/` '
            "exits 1 with no output, and `git show --stat 9d0703d` lists no cli/ path at "
            "all. The criterion was scoped to the tree at PDF-03's own commit and it HELD "
            "there. "
            "AT HEAD THE CRITERION HAS DELIBERATELY FLIPPED AND THAT IS CORRECT: "
            '`grep -rn "pagerange" src/pdf_toolkit/cli/` returns FIVE hits '
            "(cmd_rasterize.py:24, cmd_tables.py:34, cmd_merge.py:17, cmd_split.py:16, "
            "cmd_text.py:33, every one of them importing GRAMMAR_HELP) and eight ops/*.py "
            "modules import parse. PDF-07/PDF-08 wired the grammar and PDF-03's own "
            "Validation section predicted exactly this. A later reader who files those five "
            "hits as a regression is wrong; a later reader who deletes the criterion loses "
            "it. "
            "LIVE SUCCESSOR, with its own red: the unwiring was never the point, SINGLE "
            "OWNERSHIP was (G6), and test_the_page_range_grammar_has_exactly_one_owner now "
            "carries it. Three plants, each applied to one consumer, observed, reverted: a "
            'duplicate {"first","last","even","odd","all"} literal in ops/merge.py; an '
            'independently written re.compile(r"^([0-9]+)-([0-9]+)$") in cli/cmd_delete.py '
            "(caught by an accepts-a-page-range-token / rejects-ordinary-words "
            "discriminator, not by a copied pattern string); and "
            "`from pdf_toolkit.ops.pagerange import _KEYWORDS` in ops/pages.py. All three "
            "failed the test by name and file; all three reverted, tree clean. It touches "
            "neither tests/test_cli_contract.py nor tests/registry.py (PDF-17 owns both)."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC13",
        claim=(
            "Import boundary. test_pagerange_imports_are_stdlib_only walks the module's AST "
            "and asserts every imported root module is either stdlib or one of "
            "pdf_toolkit.models / pdf_toolkit.errors."
        ),
        covering=("tests/test_pagerange.py::test_pagerange_imports_are_stdlib_only",),
        red=(
            "Added `import pypdf` under `import re` at the module top; "
            "test_pagerange_imports_are_stdlib_only failed with "
            "`AssertionError: non-stdlib import: pypdf`. Reverted, 52 passed. It is an AST "
            "walk rather than a text grep -- the strong instrument -- and it correctly "
            "survived 743853f [PDF-07]'s seventy-line edit without needing a change."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC14",
        claim=(
            "Mechanized doc criterion. test_grammar_help_documents_every_token asserts each "
            "of the ten token forms (N, A-B, B-A, N-, -N, first, last, even, odd, all, !, ,) "
            "appears in GRAMMAR_HELP AND in the module docstring, and that both contain the "
            "string 1-based."
        ),
        covering=("tests/test_pagerange.py::test_ac14_grammar_help_documents_every_token",),
        red=(
            "REPAIRED. Original weakness, MEASURED by driving the original bare-substring "
            "body against GRAMMAR_HELP with one documentation row removed at a time: "
            "deleting the row for `N` -> GREEN; for `,` -> GREEN; for `first` -> GREEN; for "
            "`!TOKEN` -> GREEN; only `odd` -> RED. Four of the five forms probed were "
            "VACUOUS, because `N` occurs inside `N-` and `!TOKEN`, `,` occurs in every "
            "`e.g. 1-3,last,!2`, and `first`/`!` occur in the surrounding prose. AC14 called "
            "itself mechanized while its mechanism could not tell 'the row documenting this "
            "token exists' from 'this character appears somewhere'. REPAIR: match the "
            "grammar-table ROW KEY (an indented `<key><2+ spaces><description>` line) rather "
            "than a substring, with `!` mapped to its documented `!TOKEN` key. Both key sets "
            "parse to exactly the twelve documented forms. New reds, all four observed: "
            "deleting the GRAMMAR_HELP row for `N`, for `,`, for `odd` and for `!TOKEN` each "
            "failed test_ac14_grammar_help_documents_every_token by name, each reverted, "
            "green. "
            "TWO DIVERGENCES INSIDE THE CRITERION ITSELF, recorded rather than smoothed: "
            "AC14's own text says 'the TEN token forms' and then lists TWELVE, which is what "
            "REQUIRED_TOKEN_FORMS actually contains (measured: 12 entries) -- the §4.3 TABLE "
            "has ten rows, the token FORMS number twelve, and the criterion conflates them. "
            "And AC14 names `test_grammar_help_documents_every_token` while the landed test "
            "is `test_ac14_grammar_help_documents_every_token`."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-03-ac14-says-ten-forms-and-lists-twelve",
    ),
    ACAudit(
        ac="AC15",
        claim=(
            'No I/O. grep -nE "\\bprint\\(|sys\\.stderr|\\bopen\\(|write_bytes|write_text|'
            'shutil|subprocess|tempfile|os\\.replace|Path\\(" over the module returns '
            "nothing; the leading-exclusion warning is asserted via caplog (exactly one "
            "WARNING record, naming the token and containing 'exclusion')."
        ),
        covering=(
            "tests/test_pagerange.py::test_ac15_no_io_calls_in_module",
            "tests/test_pagerange.py::test_pagerange_module_does_no_io",
            "tests/test_pagerange.py::test_ac15_leading_exclusion_warns_exactly_once",
            "tests/test_pagerange.py::test_ac15_non_leading_exclusion_does_not_warn",
        ),
        red=(
            'Inserted `print("x")` above `running: list[int] = []` in parse(). BOTH '
            "source-scanning controls failed -- test_ac15_no_io_calls_in_module on "
            "`assert <re.Match> is None` and test_pagerange_module_does_no_io on "
            "`assert 'print(' not in source`. Reverted, 52 passed. The caplog half carries "
            "its own red: making `all` start at page 2 fails "
            "test_ac15_leading_exclusion_warns_exactly_once, and making exclusions global "
            "fails it too. TWO WEAKNESSES RECORDED, neither fatal: both matchers read SOURCE "
            "TEXT, so an aliased import (`from pathlib import Path as P`) evades them -- the "
            "B-026 naive-scan shape -- and test_pagerange_module_does_no_io is a strictly "
            "weaker duplicate of the regex above it (four substrings against ten). Neither "
            "was changed here: widening a matcher mid-audit would make this row's evidence "
            "about a control that did not exist when the criterion was granted."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-03-ac15-source-text-matcher-evaded-by-an-aliased-import",
    ),
    ACAudit(
        ac="AC16",
        claim=(
            "PageRange matches PLAN.md §6: fields exactly spec, indices, ordered, "
            "page_count; as_set() returns a frozenset; to_dict() returns exactly those four "
            "keys and is json.dumps-able; is_empty is a property, not a field."
        ),
        covering=("tests/test_pagerange.py::test_ac16_pagerange_model_is_additive_only",),
        red=(
            'Added a fifth field `label: str = ""` to models.PageRange, in the working tree '
            "only. test_ac16_pagerange_model_is_additive_only failed on the field-name set "
            "comparison. Reverted from git show HEAD:src/pdf_toolkit/models.py, "
            "git diff --exit-code clean, 52 passed, nothing staged -- models.py is read at "
            "HEAD by other cycle-2 specs and this audit leaves it byte-identical."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC17",
        claim=(
            'Bounds precede materialization: parse("1-99999999999", 10) raises '
            'PageRangeError and that test completes in under one second; parse("1", 0) '
            "raises PageRangeError, not ValueError."
        ),
        covering=(
            "tests/test_pagerange.py::test_ac17_validation_precedes_materialization",
            "tests/test_pagerange.py::test_ac17_pathologically_long_numeral_is_a_pagerange_error_no"
            "t_valueerror",
        ),
        red=(
            "Moved both `_validate_endpoint` calls in the A-B branch AFTER "
            "`list(range(first, second + step, step))`. THE CONTROL FIRES BY RESOURCE "
            "EXHAUSTION, NOT BY ASSERTING, and that is the honest record: run under "
            "`ulimit -v 2000000` and `timeout 30`, "
            "test_ac17_validation_precedes_materialization failed with `MemoryError` at "
            "src/pdf_toolkit/ops/pagerange.py:264 in 0.36 s -- the `elapsed < 1.0` assertion "
            "is never reached, because the process dies building the list. Without the "
            "rlimit the same mutation attempts a ~100-billion-element allocation, which is "
            "why it was never run inside `make ci`: an unbounded hang there is "
            'indistinguishable from B-095(a). Reverted, 2 passed. The `parse("1", 0)` half '
            "has its own red under AC10's P1 mutation (the page_count guard raising "
            "ValueError)."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-03-ac17-control-fires-as-memoryerror-not-as-an-assertion",
    ),
    ACAudit(
        ac="AC18",
        claim=(
            'HC-1 clean: grep -nE "fitz|pymupdf|pdf2image|pdftoppm|pdftotext|pdftocairo|'
            'pdfinfo|ghostscript|ocrmypdf|img2pdf|pandoc|pdftk" '
            "src/pdf_toolkit/ops/pagerange.py tests/test_pagerange.py returns nothing."
        ),
        covering=(
            "tests/test_license_policy.py::test_no_forbidden_names_under_src",
            "tests/test_license_policy.py::test_walk_covers_every_file_under_src",
        ),
        red=(
            "UPHELD BY CONSUMPTION of the repo-wide HC-1 walk, with a FIRST-HAND red rather "
            "than an inherited one. Membership proven by RUNNING it, not by reading it: the "
            "population is `SRC.rglob('*')` filtered to .py/.pyi at "
            "tests/test_license_policy.py:318, it computes to 82 files, and "
            "src/pdf_toolkit/ops/pagerange.py is IN it; "
            "test_walk_covers_every_file_under_src is the non-empty-population guard. RED: "
            "planted ONE transient forbidden-engine reference in the single file under audit "
            "-- a dead `_scratch_never_called()` doing "
            "`importlib.import_module(<forbidden engine>)` -- and "
            "test_no_forbidden_names_under_src failed naming the file and the line: "
            "`src/pdf_toolkit/ops/pagerange.py:408: forbidden dynamic import`. Reverted "
            "immediately, git diff --exit-code clean, 10 passed, nothing staged. This is not "
            "PDF-02's 82-file planting exercise repeated and it is not a second local "
            "scanner: it is one mutation of the one file this audit is about, which is what "
            "makes the red first-hand instead of quoted. "
            "RESIDUE STATED PLAINLY: AC18's original grep covered pagerange.py AND "
            "tests/test_pagerange.py. The shared walk is over src/ ONLY, so the tests/ half "
            "of this criterion has NO standing control -- PDF-03 deviation 5 removed the "
            "embedded one for a correct reason (spelling the names out to assert their "
            "absence makes the file match its own grep) and nothing replaced it. "
            "tests/test_license_policy.py was not modified."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-03-ac18-tests-half-has-no-standing-control",
    ),
    ACAudit(
        ac="AC19",
        claim=(
            "Gates green: make fmt-check, make lint, make typecheck and make ci all pass; "
            "`pytest --cov=pdf_toolkit.ops.pagerange --cov-report=term-missing "
            "tests/test_pagerange.py` reports >= 95% for the module; git status --porcelain "
            "is clean after a test run."
        ),
        covering=(),
        red=(
            "NOT OBSERVED RED, because nothing re-runs this criterion -- and re-measuring it "
            "at HEAD contradicts it. MEASURED, not transcribed: at PDF-27's starting HEAD "
            "(0abd691) the criterion's own command reports "
            "`src/pdf_toolkit/ops/pagerange.py 120 stmts, 14 miss, 88%`, missing lines "
            "348-351 and 382-391 -- exactly `_is_valid_body_shape` and `is_valid_spec`, the "
            "two functions 743853f [PDF-07] added. AC19's >= 95% floor was NOT met at HEAD. "
            "The Implementation Log's '100% / 103 statements' predates that commit and is "
            "not evidence about the file that exists now. There is no standing control: the "
            "repo-wide floor is `--cov-fail-under=85` at Makefile:78 and ci.yml:136 (both "
            "verified intact and unchanged by PDF-27), and nothing anywhere enforces a "
            "PER-MODULE 95%. Gates re-run and observed at PDF-27's own head: make fmt-check "
            "`170 files already formatted`, make lint `All checks passed!`, make typecheck "
            "`Success: no issues found in 82 source files`. After PDF-27's controls the same "
            "coverage command reports 128 stmts / 1 miss / 99%; the single uncovered line is "
            "the defensive `return False` under `if not tokens:` in is_valid_spec, which no "
            'input can reach because `"".split(",")` returns `[""]` and the blank-spec '
            "guard above it already returned. It is NAMED, not pragma'd: the pragma total "
            "under src/ stays at exactly 46. "
            "AC19's `git status --porcelain` clause holds -- but the parenthetical it "
            "carries ('.hypothesis/ ignored') is doing more work than it looks: a "
            ".hypothesis/ directory DOES exist in the repository root, dated 2026-08-29, "
            "written by tests/unit/test_name_template.py, which uses hypothesis WITHOUT the "
            "home-dir redirect PDF-03 invented for its own file. .gitignore has no entry for "
            "it; the tree reads clean only because Hypothesis writes its own nested "
            ".hypothesis/.gitignore containing `*`. Pre-existing, outside PDF-27's scope "
            "(that file is not this spec's and .gitignore is forbidden to it), and filed."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-03-ac19-module-coverage-88-vs-a-95-floor",
    ),
    ACAudit(
        ac="AC20",
        claim=(
            "HC-3/HC-5/Q5 discipline: git log -1 shows one commit subject-tagged [PDF-03] "
            "with a Signed-off-by: trailer; git show --stat HEAD lists only the files in "
            "Scope > In and no pyproject.toml, uv.lock, README.md or CLAUDE.md; changelog.md "
            "carries the [PDF-03 ...] entry in that same commit."
        ),
        covering=(),
        red=(
            "NOT OBSERVED RED, and no mutation exists that could: this is a HISTORICAL "
            "criterion about a commit that has already landed, and git is its only oracle. "
            "RE-DERIVED rather than trusted, and it HOLDS on every clause. "
            "`git show --stat 9d0703d` lists exactly five files -- changelog.md, "
            "src/pdf_toolkit/errors.py, src/pdf_toolkit/models.py, "
            "src/pdf_toolkit/ops/pagerange.py, tests/test_pagerange.py, 1026 insertions -- "
            "and NO pyproject.toml, uv.lock, README.md, CLAUDE.md or .gitignore. "
            "`git log -1 --format=%B 9d0703d` shows the `[PDF-03] feat:` subject and a "
            "`Signed-off-by: Armando Herra` trailer. `git show 9d0703d -- changelog.md` "
            "shows the entry present IN THAT COMMIT (+20 lines at the anchor) -- checked "
            "per-commit, never as a heading grep at HEAD, which is what hides a lost "
            "prepend. The row is filed as unmeasured because it has no covering test, not "
            "because it failed: a historical criterion is verifiable, it is simply not "
            "verifiable BY A TEST, and saying which is which is the honest record. "
            "One measured aside worth keeping: pagerange.py was 333 lines in 9d0703d and is "
            "403 at HEAD, while tests/test_pagerange.py was 633 lines in that commit and was "
            "still 633 when PDF-27 opened it -- the module grew seventy lines and its test "
            "file grew none."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-03-ac20-historical-criterion-has-no-standing-control",
    ),
)
