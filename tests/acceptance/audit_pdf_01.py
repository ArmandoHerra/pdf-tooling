"""`PDF-01`'s 25 acceptance criteria — `AUDIT-CONVENTION(PDF-17)`, produced by `PDF-24`.

`PDF-01` is the Typer root, all fifteen `PLAN.md` §4.2 global flags, `errors.py`
+ `exit_codes.py`, the three renderers (`table`/`json`/`ndjson`, each carrying
`schema_version`) and the redacting stderr logger. **Every one of the twenty-six
leaf verbs passes through it.** Its twenty-five criteria were granted in one pass
in `PDF-01`'s own Implementation Log — twenty-two re-run by the implementing
architect, three (`AC1`, `AC13`, `AC19`) accepted on the engineer's evidence —
and none had been independently re-derived since. A wrong verdict here is not one
wrong verdict; it is twenty-six. **All three of the never-re-run criteria were
re-run for this audit**, `AC1` and `AC19` from a `$TMPDIR` `git worktree`
(HC-4 — `git stash` is never used).

THE AUDITED HEAD IS `8fd2146`
-----------------------------
Every *MET at the audited HEAD* judgement below is against the tree as it stood
**before `PDF-24`'s own commit**. This matters because `PDF-24`'s own `AC8`
changes product behaviour (`--force`/`--yes` move from exit 0 to exit 2 on the
five verbs that write nothing): **a `PDF-01` criterion that is only true after
those edits would be disqualified, not met.** X-242's mechanical test was run
GLOBALLY to settle that question rather than argued — see below.

FOUR-BUCKET CLASSIFICATION (X-242) — 19 `ADVANCES` · 0 `MADE-TRUE-HERE` ·
3 `SUPERSEDED` · 3 `FINDING` = 25.

* **`ADVANCES`** — MET at `8fd2146` **and** newly grounded in a control this
  audit drove RED, with the mutation, the observed failure text and the revert
  recorded. `AC1`–`AC7`, `AC9`–`AC16`, `AC19`, `AC21`, `AC22`, `AC24` —
  nineteen.
* **`MADE-TRUE-HERE`** — X-215(ii), true only because of this spec's own `src/`
  edits. **NONE. Zero is a measured result here, not an absence** — see the
  global sweep below.
* **`SUPERSEDED`** — X-215(iv): the criterion's words are not re-derivable and a
  successor property is stated. `AC8`, `AC17`, `AC18` — three.
* **`FINDING`** — X-215(i)/(iii): unmeasured as of the END of this audit, or a
  control that cannot fail. `AC20`, `AC23`, `AC25` — three.

**THE RE-GRANT IS REFUSED, and this module is the evidence for the refusal.**
Three supersessions and three findings each disqualify on their own (X-215).
`X-202` refused `PDF-02` on two supersessions; this is three. The `qa-sentinel`
decides; this module does not, and `PDF-24`'s engineer does not.

**X-251, applied: THE BUCKET IS NOT THE FINDING.** **Ten of the nineteen
`ADVANCES` rows carry a filed finding** about a shipped control that could not
fail for the reason it claimed, or about a criterion with no standing control at
all -- 16 of the 25 rows carry one in total. Nothing was laundered by a bucket
assignment. RedKind tally: 18 `PLANTED_DEFECT` + 4 `MUTATED_CONFIG` +
3 `NOT_OBSERVED` = 25.

HOW THE D7 DISPOSITION IS CARRIED (`_model.py` is FROZEN)
---------------------------------------------------------
`ACAudit` has no disposition field and no verdict field, and widening the model
is a BLOCKER (X-273, `_model.py`'s own docstring). The vocabulary therefore
rides inside existing fields, the declared deviation `audit_pdf_04.py`
established and `audit_pdf_05.py`/`audit_pdf_09.py` reused: **every `claim`
opens with `[D7: R|H|S|F]`** and **every `red` opens with its X-242 bucket in
capitals.** No new field, no new `RedKind`.

X-242's MECHANICAL TEST, RUN GLOBALLY
--------------------------------------
Every new and changed test file was copied onto **`8fd2146`'s product source**
in a scratch `git worktree` (`$TMPDIR/pdf24-x242`) with **no `src/` edit
applied**, and the whole set was run.

* `tests/test_cli_spine.py` and `tests/test_honesty_claims.py` **cannot be
  COLLECTED** there — both import `SAFETY_FLAGS`, which `PDF-24` adds. That is
  itself the mechanical answer for those two modules' new symbols.
* A pass-2 run injected the two added names as empty placeholders **purely so
  the modules import** (no control's logic was touched, and no control that
  READS either name is reported from that run): **97 passed, 11 failed.**
* **All 11 failures ground a `PDF-24` criterion (its `AC5`, `AC7`, `AC8`, `AC9`,
  `AC11`, `AC12`, `AC13`, `AC14`, `AC15`). NOT ONE grounds a `PDF-01`
  criterion.** Every control cited in a `PDF-01` row below was green against
  `8fd2146`'s product source, so **clause (b) is discharged and clause (ii)
  fires for no `PDF-01` criterion.** `tests/unit/test_registry.py` collected and
  passed 13/13 unshimmed.

TWO INSTRUMENT FAILURES, INVESTIGATED RATHER THAN RECORDED AS PASSES (X-266)
----------------------------------------------------------------------------
1. **`AC7`.** The shipped control asserted ``"Python" in line`` — and the literal
   word `Python` lives in `version_line()`'s own f-string, not in the value.
   Replacing `python_version()`'s ENTIRE return with a constant left the test
   GREEN. The criterion's property was met at `8fd2146`; the control could not
   fail for the reason it claimed (X-215(iii)). Two value-level assertions were
   added, the mutation re-run, and both arms observed red. **Finding filed.**
2. **`AC10`.** `schema_version` is supplied TWICE for the single JSON object —
   by `OperationResult.to_dict()` and again by `output/json.py::render_json`'s
   ``{"schema_version": SCHEMA_VERSION, **payload}``. Removing EITHER alone left
   the control green; **both had to be removed to red it.** Defended in depth,
   and recorded as a property of the product rather than a harness failure — but
   the merge order means **the payload's value WINS**, so `render_json`'s
   injection cannot correct a payload that carries the wrong version. **Finding
   filed; not repaired — `output/json.py` is not `PDF-24`'s to edit.**

`PDF-01` AC15's NUMBER (X-277)
-------------------------------
Fastest of five `pdftoolkit --help` subprocess runs at `8fd2146`, before any
`PDF-24` edit: **227.1 ms** against the **250.0 ms** gate — MET, with 22.9 ms of
headroom. Five trials: 227.1 / 228.6 / 271.1 / 271.1 / 255.0 ms — **three of the
five were over the gate**, which is `53b321dd03` / **B-098**'s own shape.
`/proc/loadavg` was `1.09 1.14 1.49` immediately before and after and nothing
else was dispatched during the measurement. Cross-referenced to B-098, **not
re-filed, not widened, not deleted, not `xfail`ed**; `STARTUP_BUDGET_MS` in
`tests/test_cli_spine.py` reads an unchanged `250.0`. `PDF-29` owns the budget.

AC3 — THE BIDIRECTIONAL MAP OVER `PDF-01`'s SCOPE > IN TABLE (16 rows)
-----------------------------------------------------------------------
Every artefact mapped to the AC that claims it, or to an explicit *no criterion
claims this*. **The spec predicted ONE unclaimed row (item 9). There are THREE.**

  1  pyproject.toml (packaging + the §7.1 runtime set)     -> AC3, AC22
  2  uv.lock (committed lock)                              -> AC1
  3  src/pdf_toolkit/** six-layer skeleton, one            -> **NO CRITERION
     __init__.py per layer carrying its layer contract**      CLAIMS THIS.**
  4  cli/main.py + cli/common.py (Typer root, dual-level,  -> AC5, AC6, AC11
     single error handler)
  5  cli/exit_codes.py (the §5.6 constants)                -> AC8, AC9
  6  errors.py (hierarchy, redacted marker)                -> AC8
  7  models.py (SCHEMA_VERSION + the spine dataclasses)    -> AC10
  8  output/table.py, output/json.py (three renderers)     -> AC10, AC13
  9  output/logging.py (stderr logger + the redaction      -> **NO CRITERION
     FILTER MECHANISM)**                                      CLAIMS THIS.**
  10 safety/policy.py (SafetyPolicy + its construction)    -> **NO CRITERION
                                                              CLAIMS THIS.**
  11 cli/cmd_version.py (the one placeholder verb)         -> AC9, AC10
  12 Makefile (the 18 §8.1 targets)                        -> AC17
  13 six documentation skeletons                           -> AC19, AC20,
                                                              AC21, AC22
  14 changelog.md                                          -> AC23
  15 .gitignore gains .scratch/                            -> AC24
  16 tests/test_cli_spine.py + tests/test_docs_antirot.py  -> AC21

**Three findings in the `0615feae63` family, filed and NOT silently absorbed:**

* **Item 9** — the one `PDF-24` predicted. Claimed by no AC; covered by
  `tests/test_cli_spine.py::test_registered_secrets_are_scrubbed_from_every_log_record`.
  A scope item silently protected by a test nobody connected to it is one
  refactor away from being protected by nothing.
* **Item 10** — `SafetyPolicy`'s seven-field frozen shape and its construction
  are claimed by no AC. `AC9` claims one *rule* the policy owns
  (`--no-backup` without `--in-place` -> 2), never the dataclass. Covered by
  `tests/test_cli_spine.py::test_safety_policy_is_built_from_the_global_flags`
  and `::test_no_backup_is_the_inverse_of_the_backup_field`.
* **Item 3** — the per-layer `__init__.py` docstring contract is claimed by no
  AC and, unlike items 9 and 10, is covered by **nothing**: no test in this
  repository asserts that any layer's `__init__.py` states its contract, even
  though `PDF-01` Design §D.1 makes those docstrings the thing later engineers
  are told to read before editing. Grep-confirmed across `tests/`.

MUTATION DISCIPLINE
-------------------
**Every mutation ran in a scratch `git worktree` under `$TMPDIR`
(`/tmp/pdf24-mut`), never in `apps/pdf-toolkit` (HC-4 — `git stash` is never
used).** X-210's hazard was defended on every arm: (1) `pdf_toolkit.__file__`
was asserted to start with the scratch path before any red was trusted; (2) the
mutation was proven PRESENT in the scratch file before its arm ran, and an
absent mutation ABORTED the arm rather than reporting a green as a red — which
fired twice, on a triple-quote anchor matching 18 times and a `$(UV_RUN)` recipe
spelling; (3) `PYTHONDONTWRITEBYTECODE=1`; (4) restoration is from an immutable
GOLD tree and **sha256-verified against a 174-entry manifest after every arm**.
**48 pytest-driven arms, 48 restorations, 0 mismatches**, plus two arms driven
outside pytest (`AC1`'s `uv sync` and `PDF-24` `AC6`'s grep) -- **50 observations,
45 red first time, 3 instrument failures investigated and resolved, 2 shell reds.**
The three HC-1 plants of `PDF-24`
AC19 are included and `git diff` over `pyproject.toml`, `uv.lock`, `src/` and
`tests/test_license_policy.py` in the product tree is **empty**.

FINDINGS ARE REPORTED TO THE `project-manager`, NOT FILED HERE — the ledger is
read-only to `PDF-24`, so new findings carry a `PENDING-LEDGER:` slug in the
convention `audit_pdf_03/04/05/06/09.py` established. Rows citing an EXISTING
fingerprint or backlog id name it directly.

SPEC POINTERS RE-MEASURED RATHER THAN TRANSCRIBED
--------------------------------------------------
* `PDF-24` **AC16** names `merge` among the verbs whose `takes_input_paths` is
  `True`. **It is False, and correctly so**: the predicate answers *does this
  verb declare a Click `Path`-typed positional*, and `merge`'s operand is the
  §4.2 `path:range` grammar, declared `list[str]`. Measured 23 True / 3 False
  (`doctor`, `merge`, `version`). The pin records the measurement, not the
  sentence.
* `PDF-24` §D8 predicts the wide 23-name list returns offenders. Re-measured at
  `8fd2146` over this tier's own haystacks: narrow twelve-name list **0**
  offenders; wide list **59** `(file, name)` pairs, **every one of them `gs`**
  and **zero** for the other ten additions including `poppler`. `\bgs\b` returns
  **0**. `PDF-01` AC4's property is therefore MET as written.
"""

from __future__ import annotations

from typing import Final

from acceptance._model import ACAudit, RedKind

SPEC_ID: Final[str] = "PDF-01"
AC_COUNT: Final[int] = 25

AUDIT: Final[tuple[ACAudit, ...]] = (
    ACAudit(
        ac="AC1",
        claim=(
            "[D7: R] `uv sync` succeeds from a clean clone on Python >= 3.11, and `uv.lock` is "
            "committed. One of the three PDF-01 criteria accepted on the engineer's transcript "
            "rather than re-run; re-run here from a $TMPDIR git worktree."
        ),
        covering=(),
        red=(
            "ADVANCES. MET at 8fd2146 and grounded on an observed red.\n"
            "GREEN: `git worktree add --detach $TMPDIR/pdf24-x242 8fd2146` then `uv sync` "
            "resolved and installed 77 packages on Python 3.13.14; `git ls-files uv.lock` "
            "returns `uv.lock`; `uv run pdftoolkit --version` printed the one-line banner.\n"
            "MUTATION: an unresolvable requirement "
            "(`pdf-toolkit-no-such-distribution-planted-by-pdf24>=9999`) added to "
            "[project].dependencies in the scratch worktree.\n"
            "OBSERVED: `uv sync` -> `x No solution found when resolving dependencies` / "
            "`Because pdf-toolkit-no-such-distribution-planted-by-pdf24 was not found in the "
            "package registry ... your project's requirements are unsatisfiable`.\n"
            "REVERTED with `git show HEAD:pyproject.toml > pyproject.toml` and the same for "
            "uv.lock (HC-4's named substitute; the layer's git-safety hook refuses `git "
            "checkout --`); `git status --short` then named neither file, and `uv sync` was "
            "re-run green.\n"
            "FINDING: no standing pytest control covers this criterion at all -- it is a "
            "command, re-run by hand once per audit. The committed lockfile and a green gate "
            "IMPLY it; nothing ASSERTS it."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
        finding="PENDING-LEDGER: pdf-01-ac1-clean-clone-install-has-no-standing-control",
    ),
    ACAudit(
        ac="AC2",
        claim=(
            "[D7: R] `uv run pdftoolkit --help` exits 0 and prints the root help. "
            "`uv run pdf-toolkit --help` and `uv run python -m pdf_toolkit --help` produce "
            "byte-identical output (D-10, §11)."
        ),
        covering=("tests/test_cli_spine.py::test_every_entry_point_prints_byte_identical_help",),
        red=(
            "ADVANCES. MET at 8fd2146 and grounded on an observed red.\n"
            "MUTATION: `src/pdf_toolkit/__main__.py`'s `main()` given a distinct program name "
            '(`main(prog_name="pdf_toolkit_module")`), so the module entry point\'s help '
            "diverges from the console script's.\n"
            "OBSERVED: `assert 1 == 0` / the `-m pdf_toolkit` child exited 1 -- the module arm "
            "is a real subprocess, so the divergence is caught at the byte level rather than by "
            "reading the source.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC3",
        claim=(
            "[D7: R] The declared runtime dependencies are exactly the eight core requirements "
            "of Design §D.2 -- pypdf[crypto], pypdfium2, reportlab, pikepdf, pdfplumber, "
            "pytesseract, pillow, typer -- and `weasyprint` appears ONLY under "
            "[project.optional-dependencies] (Q5, D-05)."
        ),
        covering=(
            "tests/test_cli_spine.py::test_declared_runtime_dependencies_are_the_frozen_set",
            "tests/test_cli_spine.py::"
            "test_weasyprint_is_an_optional_extra_and_never_a_core_dependency",
        ),
        red=(
            "ADVANCES. MET at 8fd2146 and grounded on an observed red.\n"
            'MUTATION: `"pikepdf>=10.12.0,<11",` deleted from [project].dependencies.\n'
            "OBSERVED: `AssertionError: assert {'pdfplumber', ..., 'reportlab', ...} == "
            "{'pdfplumber', ..., 'pytesseract', ...}` -- the control is an EQUALITY against a "
            "frozen set, so a REMOVAL reds it just as an addition would. A containment check "
            "would have stayed green.\n"
            "REVERTED from the gold tree; sha256 match.\n"
            "NOTE, measured not assumed: the frozen-set control splits each entry on "
            "`[><=!~;]` and compares NAMES only, so PDF-23's `pypdf` ceiling comment could not "
            "have perturbed this criterion either way."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
    ),
    ACAudit(
        ac="AC4",
        claim=(
            "[D7: R] The HC-1 forbidden-name grep -- `grep -riE 'fitz|pymupdf|pdf2image|"
            "pdftoppm|pdftotext|pdftocairo|pdfinfo|ghostscript|ocrmypdf|img2pdf|pandoc|pdftk' "
            "pyproject.toml src/ Makefile` -- returns NOTHING (HC-1)."
        ),
        covering=(
            "tests/test_cli_spine.py::"
            "test_no_forbidden_engine_name_appears_in_packaging_source_or_build",
        ),
        red=(
            "ADVANCES. MET AT 8fd2146 AS WRITTEN, and grounded on an observed red.\n"
            "MEASURED, not transcribed: the criterion's own literal twelve names run over its "
            "own three haystacks (pyproject.toml, Makefile, src/**/*.py) return ZERO "
            "offenders. The wider 23-name list of tests/test_license_policy.py returns 59 "
            "(file, name) pairs, EVERY ONE of them `gs` matching inside `warnings` (105 "
            "occurrences), `flags` (34), `args` (31), `belongs`, `output_flags`, `settings`, "
            "`strings` and 27 more enclosing words -- and ZERO for the other ten additions, "
            "`poppler` included. `\\bgs\\b` returns zero.\n"
            "MUTATION: the literal `Ghostscript` planted in "
            "`src/pdf_toolkit/adapters/subprocess_util.py`'s module docstring.\n"
            "OBSERVED: `AssertionError: PLAN §7.2 forbidden names found by the textual tier:` / "
            "`src/pdf_toolkit/adapters/subprocess_util.py: ghostscript` -- file and name both "
            "named.\n"
            "REVERTED from the gold tree; sha256 match; product-tree `git diff` empty.\n"
            "FINDING, about the instrument rather than the criterion: the shipped textual tier "
            "carried TWELVE hand-typed names against the AST tier's twenty-three, with nothing "
            "asserting the two related -- so `poppler` and `gs` were outside it entirely and "
            "the criterion's green was narrower than a reader would assume. PDF-24 closes it "
            "by IMPORTING the list; the gap existed at the audited head and is filed as one."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=(
            "PENDING-LEDGER: pdf-01-ac4-textual-hc1-tier-carried-12-names-against-the-ast-tier-23"
        ),
    ),
    ACAudit(
        ac="AC5",
        claim=(
            "[D7: R] `uv run pdftoolkit --help` names ALL FIFTEEN long options of the Design "
            "§D.3 table, asserted by a test that iterates that list rather than by eye."
        ),
        covering=(
            "tests/test_cli_spine.py::test_root_help_names_every_global_option",
            "tests/test_cli_spine.py::test_global_options_equals_the_derived_roster",
            "tests/test_cli_spine.py::test_the_derivation_is_not_vacuous",
        ),
        red=(
            "ADVANCES. MET at 8fd2146 and grounded on an observed red.\n"
            "MUTATION: the `--threads` `_ParamSpec` deleted from `GLOBAL_PARAMS` while "
            "`GLOBAL_OPTIONS` still lists `--threads`.\n"
            "OBSERVED: `AssertionError: root --help does not name --threads`, and the newly "
            "added roster-equality control fired on the same mutation.\n"
            "REVERTED from the gold tree; sha256 match.\n"
            "FINDING: the shipped control is PRESENCE-only in one direction -- it asserts every "
            "member of `GLOBAL_OPTIONS` appears in the help, and nothing asserted the reverse, "
            "so a sixteenth `_ParamSpec` added to `GLOBAL_PARAMS` alone would have rendered in "
            "all 26 helps, bound at runtime, and been invisible to EVERY control in the "
            "repository -- the contract harness's C2 included. Green at 8fd2146 (the two "
            "tuples agreed there); the HOLE was real and is what PDF-24 AC4 closes."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=(
            "PENDING-LEDGER: pdf-01-ac5-global-options-vs-global-params-had-no-equality-control"
        ),
    ),
    ACAudit(
        ac="AC6",
        claim=(
            "[D7: R] `uv run pdftoolkit version --help` names the SAME fifteen, and "
            "`pdftoolkit --dry-run version` and `pdftoolkit version --dry-run` produce "
            "identical stdout and identical exit codes (the §4.2 inheritance contract)."
        ),
        covering=(
            "tests/test_cli_spine.py::test_verb_help_names_the_same_global_option_block",
            "tests/test_cli_spine.py::test_a_global_flag_means_the_same_before_and_after_the_verb",
        ),
        red=(
            "ADVANCES. MET at 8fd2146 and grounded on an observed red.\n"
            "MUTATION: `_verb_handler`'s explicit-wins precedence broken -- "
            "`if explicit or not isinstance(parent_state, CliState)` forced to "
            "`if True or explicit or ...`, so a verb-level default always overrides the root "
            "value.\n"
            'OBSERVED: `assert \'{"schema_ver...t_code": 0}\\n\' == \'{"schema_ver...t_code": '
            "0}\\n'` with a byte-level diff -- the two spellings stopped being identical, which "
            "is exactly the property §4.2 requires and D.3 implements.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC7",
        claim=(
            "[D7: R] `uv run pdftoolkit --version` exits 0 and prints ONE line containing the "
            "tool version, the running Python version, and at least one engine distribution "
            "version."
        ),
        covering=(
            "tests/test_cli_spine.py::test_version_flag_reports_tool_python_and_engine_versions",
        ),
        red=(
            "ADVANCES, after an INSTRUMENT FAILURE that was investigated rather than recorded "
            "as a pass (X-266).\n"
            "FIRST MUTATION: `python_version()`'s ENTIRE return value replaced with the "
            'constant `"REDACTED-BY-PDF24"`.\n'
            'FIRST OBSERVATION: **GREEN.** The shipped control asserted `"Python" in line`, '
            "and the literal word `Python` lives in `version_line()`'s own f-string, not in the "
            "value -- so the control asserted a LABEL and could not fail for the reason it "
            'claimed (X-215(iii)). `"pdftoolkit" in line` had the same shape for the TOOL '
            "version clause.\n"
            "REPAIR: two VALUE-level assertions added, both computed rather than typed -- "
            "`platform.python_version() in line` and `pdf_toolkit.__version__ in line`.\n"
            "SECOND MUTATION, same as the first: OBSERVED `AssertionError: --version does not "
            "carry the running interpreter's version (3.13.14): pdftoolkit 0.1.0.dev0 (Python "
            "REDACTED-BY-PDF24 on linux); ...`.\n"
            "THIRD MUTATION: the tool version dropped from the banner "
            '(`f"pdftoolkit {tool_version()} "` -> `f"pdftoolkit "`). OBSERVED '
            "`AssertionError: --version does not carry the tool version (0.1.0.dev0)`.\n"
            "The PRODUCT satisfied this criterion at 8fd2146 (the banner does carry both "
            "values), so X-215(ii) does not fire -- the control was vacuous, not the product. "
            "Confirmed by X-242's sweep: the strengthened control is green against 8fd2146's "
            "product source.\n"
            "REVERTED from the gold tree on every arm; sha256 match.\n"
            "FINDING: the shipped control asserted the presence of two LABELS, not of two "
            "VALUES, from PDF-01's landing until this audit."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-01-ac7-version-control-asserted-the-label-not-the-value",
    ),
    ACAudit(
        ac="AC8",
        claim=(
            "[D7: S] A test asserts the integer value of each constant in `cli/exit_codes.py` "
            "-- OK==0, FAILURE==1, USAGE==2, ENGINE_MISSING==3, NO_INPUT==4, REFUSED==5, "
            "AUTH==6 -- and that `errors.py` exposes EXACTLY ONE exception class per non-zero "
            "code carrying that code."
        ),
        covering=(
            "tests/test_cli_spine.py::test_exit_code_constants_hold_their_published_integers",
            "tests/test_cli_spine.py::test_errors_expose_exactly_one_class_per_non_zero_exit_code",
            "tests/test_cli_spine.py::test_every_error_class_carries_a_published_exit_code",
        ),
        red=(
            "SUPERSEDED -- X-215(iv), and this row alone refuses the re-grant.\n"
            "LITERAL DRIFT, measured by import at 8fd2146: the mapping is MANY-TO-ONE. Code 5 "
            "carries SEVEN concrete classes (RefusedError, TargetExistsError, "
            "OutputCollisionError, BackupExistsError, OutputEscapesDirError, "
            "ConfirmationRequiredError, ConfirmationDeclinedError); code 1 carries THREE; code "
            "2 carries THREE (UsageError, PageRangeError, BackupWithoutInPlaceError). "
            "`exactly one exception class per non-zero code` is NOT re-derivable as written.\n"
            "SUPERSEDING SPECS: PDF-03 (PageRangeError), PDF-04 (the refusal family), PDF-07, "
            "PDF-13, PDF-18. NOT one spec -- the criterion was overtaken incrementally, which "
            "is why nobody noticed.\n"
            "SURVIVING INVARIANT, re-derived: ONE **BASE** class per non-zero code (the shipped "
            "control reads `PdfToolkitError.__subclasses__()` -- DIRECT subclasses only, which "
            "is why it still passes and why its NAME is now wrong), AND every concrete "
            "descendant's `exit_code` is a member of `ALL_EXIT_CODES`. **No cardinality is "
            "pinned**: PDF-26 adds `SourceUnreadableError(FailureError)` in wave 7 and a "
            "class-count assertion would turn it red for no reason.\n"
            "MUTATION (i): `USAGE: Final[int] = 2` renumbered to 12. OBSERVED `assert 12 == 2` "
            "/ `where 12 = exit_codes.USAGE`.\n"
            "MUTATION (ii): a SECOND direct subclass added for code 2. OBSERVED "
            "`AssertionError: got ['FailureError', 'UsageError', ..., "
            "'PlantedSecondUsageError']` / `assert [1, 2, 2, 3, 4, 5, ...] == [1, 2, 3, 4, 5, "
            "6]`.\n"
            "MUTATION (iii): a `RefusedError` subclass given `exit_code = 42`. OBSERVED "
            "`AssertionError: every error class's exit_code must be a published integer` / "
            "`['PlantedOffTableError: exit_code=42']` -- the second half of the surviving "
            "invariant, which nothing measured before this audit.\n"
            "REVERTED from the gold tree on all three arms; sha256 match.\n"
            "PDF-01's spec file is NOT edited: a landed record is corrected by a new entry."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=(
            "PENDING-LEDGER: pdf-01-ac8-one-class-per-code-superseded-"
            "and-the-subclass-half-was-unmeasured"
        ),
    ),
    ACAudit(
        ac="AC9",
        claim=(
            "[D7: R] The Design §D.3 command-surface table passes as written: `pdftoolkit` -> "
            "0; `--help` -> 0; `--version` -> 0; `bogus` -> 2; `--bogus-flag` -> 2; `version` "
            "-> 0; `-q -v` -> 2; `--no-backup` without `--in-place` -> 2; `-O x.pdf --out-dir "
            "d/` -> 2; `--password-file /no/such/file` -> 2."
        ),
        covering=(
            "tests/test_cli_spine.py::test_command_surface_exit_codes[()-0]",
            "tests/test_cli_spine.py::test_command_surface_exit_codes[('--help',)-0]",
            "tests/test_cli_spine.py::test_command_surface_exit_codes[('--version',)-0]",
            "tests/test_cli_spine.py::test_command_surface_exit_codes[('bogus',)-2]",
            "tests/test_cli_spine.py::test_command_surface_exit_codes[('--bogus-flag',)-2]",
            "tests/test_cli_spine.py::test_command_surface_exit_codes[('version',)-0]",
            "tests/test_cli_spine.py::test_command_surface_exit_codes[('-q', '-v', 'version')-2]",
            "tests/test_cli_spine.py::"
            "test_command_surface_exit_codes[('--no-backup', 'version')-2]",
            "tests/test_cli_spine.py::"
            "test_command_surface_exit_codes[('version', '--no-backup')-2]",
            "tests/test_cli_spine.py::"
            "test_command_surface_exit_codes[('-O', 'x.pdf', '--out-dir', 'd', 'version')-2]",
            "tests/test_cli_spine.py::"
            "test_command_surface_exit_codes[('--password-file', '/no/such/file', 'version')-2]",
            "tests/test_cli_spine.py::"
            "test_command_surface_exit_codes[('--threads', '0', 'version')-2]",
            "tests/test_cli_spine.py::test_command_surface_exit_codes[('version', '-q', '-v')-2]",
            "tests/test_cli_spine.py::"
            "test_command_surface_exit_codes[('version', '-O', 'x.pdf', '--out-dir', 'd')-2]",
            "tests/test_cli_spine.py::"
            "test_command_surface_exit_codes[('version', '--password-file', '/no/such/file')-2]",
            "tests/test_cli_spine.py::"
            "test_command_surface_exit_codes[('version', '--threads', '0')-2]",
            "tests/test_cli_spine.py::"
            "test_command_surface_exit_codes[('split', 'x.pdf', '--name', 'a/b')-2]",
        ),
        red=(
            "ADVANCES. MET at 8fd2146, row by row, and grounded on an observed red.\n"
            "MUTATION: `USAGE: Final[int] = 2` renumbered to 12 in `cli/exit_codes.py` -- a "
            "PUBLIC-API change (D-09), which is the class of defect this table exists to "
            "catch.\n"
            "OBSERVED: the parametrized table went red naming its rows, alongside "
            "`test_exit_code_constants_hold_their_published_integers` (`assert 12 == 2`).\n"
            "REVERTED from the gold tree; sha256 match.\n"
            "WIDENED BY THIS AUDIT (PDF-24 AC27): five POST-VERB rows added. `--no-backup` "
            "already carried both spellings (PDF-01's own F-4 resolution); `-q -v`, "
            "`-O`+`--out-dir`, `--password-file`, `--name` and `--threads` were pinned "
            "PRE-VERB ONLY, so the §4.2 inheritance contract was asserted for one flag and "
            "ASSUMED for four. All five new rows are green against 8fd2146's product source "
            "(X-242 sweep), so clause (ii) does not fire.\n"
            "FINDING: four of this table's five invocation-error rows had no post-verb "
            "counterpart from PDF-01's landing until this audit."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-01-ac9-four-invocation-error-rows-were-pinned-pre-verb-only",
    ),
    ACAudit(
        ac="AC10",
        claim=(
            "[D7: R] `pdftoolkit version -o json` writes to STDOUT a single object whose "
            "`schema_version` equals `models.SCHEMA_VERSION` (1) and which parses with "
            "`json.loads`; `-o ndjson` writes one object per line, EACH LINE CARRYING "
            "`schema_version`; `-o table` writes a human table to stdout. All three exit 0."
        ),
        covering=(
            "tests/test_cli_spine.py::test_json_output_is_one_object_carrying_the_schema_version",
            "tests/test_cli_spine.py::test_ndjson_output_is_one_self_describing_object_per_line",
            "tests/test_cli_spine.py::test_table_output_is_a_human_table_on_stdout",
        ),
        red=(
            "ADVANCES, and DEFENDED IN DEPTH -- a single-point mutation could not red the "
            "single-object half, which is recorded here as a property of the product rather "
            "than a harness failure (X-266 investigated, not waved through).\n"
            'MUTATION (ndjson): `"schema_version": SCHEMA_VERSION,` deleted from '
            "`output/json.py::render_ndjson`'s per-line dict. OBSERVED `KeyError: "
            "'schema_version'` -- each line builds its own dict, so one edit reds it.\n"
            "MUTATION (json, first attempt): the same key deleted from `render_json`'s "
            '`{"schema_version": SCHEMA_VERSION, **payload}`. OBSERVED **GREEN** -- the '
            "payload already supplies it.\n"
            "MUTATION (json, second attempt): the key deleted from "
            "`OperationResult.to_dict()` instead. OBSERVED **GREEN** -- `render_json` supplies "
            "it.\n"
            "MUTATION (json, COMBINED): both sites removed together. OBSERVED `KeyError: "
            "'schema_version'`. The criterion is grounded; it needed both.\n"
            "REVERTED from the gold tree on every arm; sha256 match.\n"
            "FINDING: `render_json`'s injection is not merely redundant, it is OVERRIDDEN -- "
            '`{"schema_version": SCHEMA_VERSION, **payload}` lets the PAYLOAD\'s value win, so '
            "the renderer cannot correct a payload carrying the wrong version, which is the one "
            "thing a top-level injection reads as promising. Filed, NOT repaired: "
            "`output/json.py` is not PDF-24's to edit."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding=(
            "PENDING-LEDGER: pdf-01-ac10-render-json-schema-"
            "version-injection-is-overridden-by-the-payload"
        ),
    ),
    ACAudit(
        ac="AC11",
        claim=(
            "[D7: R] With `-o table`, a raised `PdfToolkitError` renders as a one-line "
            "`error: ...` on STDERR and stdout is empty; with `-o json` the same error renders "
            'on STDOUT as `{"schema_version": 1, "error": {...}}`. Both asserted on captured '
            "streams. PDF-01's own log calls this *the single most invertible thing in the "
            "spec*."
        ),
        covering=(
            "tests/test_cli_spine.py::test_table_errors_go_to_stderr_and_leave_stdout_empty",
            "tests/test_cli_spine.py::test_json_errors_go_to_stdout_in_the_published_shape",
            "tests/test_cli_spine.py::test_an_error_reaches_the_single_handler_end_to_end",
        ),
        red=(
            "ADVANCES. MET at 8fd2146 and grounded on a control that was ACTUALLY INVERTED "
            "(PDF-24 AC28's requirement: a test that passes under both arrangements is testing "
            "nothing).\n"
            "MUTATION: the two streams SWAPPED inside "
            "`src/pdf_toolkit/output/__init__.py::emit_error` -- table to stdout, json to "
            "stderr.\n"
            "OBSERVED: `assert 'error: target exists (out.pdf)\\n' == ''` -- the table arm's "
            "stdout stopped being empty, and the end-to-end arm fired alongside it, so the "
            "inversion is caught both in-process and through a real subprocess.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC12",
        claim=(
            "[D7: R] `pdftoolkit version | cat` (stdout not a TTY, no `-o`) emits JSON; "
            "`pdftoolkit version -o table | cat` emits the table (D-08 auto-detect and its "
            "explicit override)."
        ),
        covering=(
            "tests/test_cli_spine.py::"
            "test_output_format_auto_detects_a_non_tty_and_an_explicit_override_wins",
        ),
        red=(
            "ADVANCES. MET at 8fd2146 and grounded on an observed red.\n"
            "MUTATION: `output/__init__.py::auto_format()` pinned to return "
            "`OutputFormat.TABLE` unconditionally, removing the D-08 non-TTY detection.\n"
            "OBSERVED: `json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char "
            "0)` -- the non-TTY arm emitted a table where the contract requires JSON.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC13",
        claim=(
            "[D7: R] A test asserts each renderer consumes only `to_dict()`: monkeypatching "
            "`OperationResult.to_dict` to add a key makes that key appear in the `-o json` "
            "payload (§6). The second of the three PDF-01 criteria never re-run; re-run here."
        ),
        covering=("tests/test_cli_spine.py::test_renderers_consume_only_to_dict",),
        red=(
            "ADVANCES. MET at 8fd2146 and grounded on an observed red.\n"
            "MUTATION: `render_payload` made to WHITELIST keys -- one line filtering the "
            "smuggled key out of the payload it was handed, which is precisely the behaviour "
            "*consumes only to_dict()* forbids.\n"
            "OBSERVED: `KeyError: 'smuggled'`.\n"
            "REVERTED from the gold tree; sha256 match.\n"
            "FINDING about the control's reach: it drives `render_payload(sample_result()."
            "to_dict(), JSON)` -- the TEST calls `to_dict()` itself, so what is proven is that "
            "`render_payload` passes an unknown key THROUGH. It does not prove that "
            "`emit_result` reaches the renderer via `to_dict()` rather than by reading fields; "
            "a mutation of `emit_result` alone would not red it. Narrower than the criterion's "
            "words, and green at 8fd2146 either way."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-01-ac13-to-dict-control-covers-render-payload-not-emit-result",
    ),
    ACAudit(
        ac="AC14",
        claim=(
            "[D7: R] Structural: importing `pdf_toolkit.cli.main` leaves none of pypdf, "
            "pikepdf, pypdfium2, reportlab, pdfplumber, fitz in `sys.modules` -- no engine "
            "library is imported at module scope (PLAN §12 R-13)."
        ),
        covering=("tests/test_cli_spine.py::test_no_engine_library_is_imported_at_module_scope",),
        red=(
            "ADVANCES. MET at 8fd2146 and grounded on an observed red.\n"
            "MUTATION: `import pypdf` added at module scope in `src/pdf_toolkit/cli/main.py`.\n"
            "OBSERVED: `AssertionError: engines imported at module scope: ['pypdf']` / "
            "`assert 1 == 0` -- the control runs a FRESH subprocess, so it measures the real "
            "import graph rather than whatever the test session already loaded.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC15",
        claim=(
            "[D7: R, contested] Measured: an `@pytest.mark.e2e` test runs `pdftoolkit --help` "
            "as a subprocess FIVE times and asserts the FASTEST run is under 250 ms. "
            "Best-of-N, not mean, so scheduler noise cannot flake the gate."
        ),
        covering=("tests/test_cli_spine.py::test_help_stays_within_the_startup_budget",),
        red=(
            "ADVANCES. MET at 8fd2146 -- fastest of five = **227.1 ms** against the 250.0 ms "
            "gate, 22.9 ms of headroom. Five trials: 227.1 / 228.6 / 271.1 / 271.1 / 255.0 ms, "
            "so THREE OF FIVE were over the gate; `/proc/loadavg` read `1.09 1.14 1.49` "
            "immediately before and after and nothing else was dispatched during the "
            "measurement.\n"
            "MUTATION: 300 ms of module-scope work (`time.sleep(0.3)`) added to "
            "`src/pdf_toolkit/cli/main.py`.\n"
            "OBSERVED: `AssertionError: fastest --help was 688 ms of 250.0 ms` / `assert "
            "688.3719149627723 < 250.0`.\n"
            "REVERTED from the gold tree; sha256 match.\n"
            "CROSS-REFERENCE, NOT A NEW FILING: the trial spread is `53b321dd03` / B-098's own "
            "shape, an open row owned by PDF-29. This audit did not widen the budget, delete "
            "the test or mark it xfail; `grep -n 'STARTUP_BUDGET_MS' tests/test_cli_spine.py` "
            "shows an unchanged `250.0`."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="53b321dd03 (B-098) -- cross-referenced, owned by PDF-29, not re-filed",
    ),
    ACAudit(
        ac="AC16",
        claim=(
            '[D7: R] `grep -rn "import rich\\|from rich" src/` returns NOTHING (§5.2 -- the '
            "table renderer is hand-rolled)."
        ),
        covering=("tests/test_cli_spine.py::test_no_module_under_src_imports_rich",),
        red=(
            "ADVANCES. MET at 8fd2146 and grounded on an observed red.\n"
            "MUTATION: `import rich` added to `src/pdf_toolkit/output/__init__.py` -- the L6 "
            "module where the temptation actually lives, since `typer` already pulls rich into "
            "the environment.\n"
            "OBSERVED: `AssertionError: the table renderer is hand-rolled on purpose` / "
            "`assert [PosixPath('.../output/__init__.py')] == []`.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC17",
        claim=(
            "[D7: S] `make help` exits 0 and lists exactly the **18** targets of Design §D.8; "
            "`grep -nE '\\|\\|[[:space:]]*true|^\\t-' Makefile` returns NOTHING (no silently "
            "degrading recipe -- the MHC-51 lesson)."
        ),
        covering=(
            "tests/test_cli_spine.py::test_makefile_documents_exactly_the_expected_targets",
            "tests/test_cli_spine.py::test_no_makefile_recipe_degrades_silently",
        ),
        red=(
            "SUPERSEDED -- X-215(iv). The literal **18** is IN the criterion and the Makefile "
            "carries **21**.\n"
            "LITERAL DRIFT: PDF-06 added `samples-scratch` and `samples-check`; PDF-11 added "
            "`samples-gate` (X-115); PDF-28 added `engines-gate`, `licenses-check` and "
            "`artifacts-check`. Re-running the criterion verbatim would produce a FALSE RED; "
            "declaring it met without comment would produce a FALSE GREEN.\n"
            "SURVIVING INVARIANT, re-derived and intact: the DOCUMENTED set equals the PINNED "
            "set EXACTLY -- an equality assertion, which is the reason the drift is visible at "
            "all -- and no recipe degrades.\n"
            "MUTATION (a): the `## ` doc comment stripped from the `clean` target. OBSERVED "
            "`AssertionError: assert {...} == {...}` / `Extra items in the right set: "
            "'clean'`.\n"
            "MUTATION (b): `|| true` appended to `lint`'s recipe. OBSERVED `AssertionError: a "
            "gate that cannot fail is not a gate` / `assert ['\\t$(UV_RUN) ruff check . || "
            "true'] == []`.\n"
            "REVERTED from the gold tree on both arms; sha256 match.\n"
            "PDF-01's spec file is NOT edited."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-01-ac17-the-literal-18-target-count-is-superseded-by-21",
    ),
    ACAudit(
        ac="AC18",
        claim=(
            "[D7: S] `make ci` exits 0 on an empty verb set, running `fmt-check lint typecheck "
            "**test** licenses sast vulncheck` IN THAT ORDER. `make test-e2e` also exits 0 (the "
            "e2e marker selects at least one test, so pytest does not exit 5)."
        ),
        covering=(
            "tests/test_gate_parity.py::"
            "test_makefiles_ci_prerequisites_are_exactly_the_in_make_ci_true_locals",
        ),
        red=(
            "SUPERSEDED -- X-215(iv). `test` became `cover` when PDF-06 brought the coverage "
            "floor into force; `Makefile` reads `ci: fmt-check lint typecheck **cover** "
            "licenses sast vulncheck`, and decision.md X-160 independently confirms that "
            "seven-item list.\n"
            "SUPERSEDING SPEC: PDF-06 (the floor), with PDF-28 owning the composition "
            "question thereafter. **PDF-24 does not adjudicate what `make ci` should contain** "
            "-- that is PDF-28's, and re-deciding it here would be scope theft.\n"
            "SURVIVING INVARIANT, re-derived: `make ci` exits 0, and its prerequisite list is "
            "no longer prose at all -- it is checked against `.github/gate-parity.toml`'s "
            "`in_make_ci` manifest, which is strictly stronger than the ordered literal PDF-01 "
            "wrote.\n"
            "MUTATION: `cover` removed from `ci`'s prerequisite list. OBSERVED "
            "`AssertionError: (frozenset({'fmt-check', 'licenses', 'lint', 'sast', 'typecheck', "
            "'vulncheck'}), frozenset({'cover', 'fmt-check', ...}))` -- the manifest and the "
            "Makefile disagreed and the control named both sides.\n"
            "REVERTED from the gold tree; sha256 match.\n"
            "PDF-01's spec file is NOT edited."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-01-ac18-make-ci-composition-superseded-test-became-cover",
    ),
    ACAudit(
        ac="AC19",
        claim=(
            "[D7: R] Every command in the README's Getting Started and Development blocks is "
            "executed IN ORDER from a clean clone and each exits 0: `uv sync`, "
            "`uv run pdftoolkit --help`, `make test`, `make ci`. The third of the three PDF-01 "
            "criteria never re-run; re-run here."
        ),
        covering=(),
        red=(
            "ADVANCES. MET at 8fd2146 and grounded on an observed red.\n"
            "GREEN, re-run in order in a clean `$TMPDIR` git worktree at 8fd2146 (HC-4's "
            "substitute for a stash): `uv sync` -> 0; `uv run pdftoolkit --help` -> 0; "
            "`make test` -> 0 (**2290 passed, 32 skipped, 1 xfailed** in 574 s); `make ci` -> "
            "0. All 32 skips are the PDF_TOOLKIT_SAMPLES_DIR real-document arm, which HC-2 "
            "requires to skip visibly rather than pass.\n"
            "MUTATION: the same unresolvable-requirement plant used for AC1, which is the "
            "FIRST command of the block and therefore reds the whole ordered run. OBSERVED "
            "`uv sync` -> `x No solution found when resolving dependencies`. A second, "
            "independent arm: `|| true` in a `make ci` prerequisite's recipe reds the gate "
            "leg (see AC17(b)).\n"
            "REVERTED with `git show HEAD:<path>`; `git status --short` clean afterwards.\n"
            "FINDING: like AC1, this criterion has NO standing control -- it is four commands "
            "re-run by hand. `tests/test_docs_antirot.py::test_every_documented_make_target_"
            "exists` asserts each documented `make <target>` RESOLVES to a real target; "
            "nothing asserts any of them EXITS 0."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
        finding="PENDING-LEDGER: pdf-01-ac19-readme-command-block-has-no-standing-control",
    ),
    ACAudit(
        ac="AC20",
        claim=(
            "[D7: F] `README.md` carries the D-10 / PLAN §12 R-14 paragraph: not `pdftk`, no "
            "shared code, Apache-2.0, install `pdf-toolkit` (not `pdftoolkit`)."
        ),
        covering=(),
        red=(
            "FINDING -- X-215(i). **UNMEASURED, and deliberately NOT converted into a passing "
            "assertion.**\n"
            "The paragraph IS present at 8fd2146 -- `README.md:11-15` carries the `## This is "
            "not `pdftk`` heading, the no-shared-code and not-a-fork sentences, the Apache-2.0 "
            "statement, and the explicit *the PyPI distribution to install is `pdf-toolkit` -- "
            "with the hyphen* clause naming the unrelated GPL-3.0 `pdftoolkit` distribution. So "
            "the criterion's PROPERTY holds.\n"
            "But NOTHING ASSERTS IT. Grep-confirmed across the whole suite: "
            "`tests/test_docs_antirot.py` walks README.md for the phase line, spec ids, spec "
            "counts and make-target truth; `tests/test_honesty_claims.py` walks it for "
            "comparative claims and one `compress` limitation; `tests/test_gate_parity.py` and "
            "`tests/test_password_leaks.py` walk it for their own claim sites. **No test names "
            "`pdftk`, `Apache-2.0` or the distribution-name warning as a README requirement.** "
            "Deleting the entire paragraph turns nothing red.\n"
            "WHY NO CONTROL WAS WRITTEN: PDF-06's anti-gaming rule, carried verbatim into "
            "PDF-24's Non-goals -- *an acceptance criterion with no covering test is a FINDING, "
            "not a gap to be quietly filled with a passing assertion* (`0615feae63` is the "
            "precedent: PDF-09's AC18 was unmeasured, not unmet). Writing the assertion here "
            "would have converted an unmeasured criterion into a green one inside the very "
            "audit that exists to find it."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-01-ac20-the-d10-readme-paragraph-is-asserted-by-no-test",
    ),
    ACAudit(
        ac="AC21",
        claim=(
            "[D7: R] HC-5, mechanized. `tests/test_docs_antirot.py` passes: exactly one "
            "`^\\*\\*Current phase:\\*\\*` line in each of README.md and CLAUDE.md; "
            "`grep -riE 'pdf-[0-9]{2}|[0-9]+ +specs?\\b' README.md CLAUDE.md` returns nothing; "
            "every `make <target>` string in README.md, CLAUDE.md, CONTRIBUTING.md and "
            "TESTING.md resolves to a real Makefile target."
        ),
        covering=(
            "tests/test_docs_antirot.py::test_exactly_one_phase_line[README.md]",
            "tests/test_docs_antirot.py::test_exactly_one_phase_line[CLAUDE.md]",
            "tests/test_docs_antirot.py::test_no_spec_identifier_is_embedded[README.md]",
            "tests/test_docs_antirot.py::test_no_spec_identifier_is_embedded[CLAUDE.md]",
            "tests/test_docs_antirot.py::test_no_spec_count_is_embedded[README.md]",
            "tests/test_docs_antirot.py::test_no_spec_count_is_embedded[CLAUDE.md]",
            "tests/test_docs_antirot.py::test_every_documented_make_target_exists[README.md]",
            "tests/test_docs_antirot.py::test_every_documented_make_target_exists[CLAUDE.md]",
            "tests/test_docs_antirot.py::test_every_documented_make_target_exists[CONTRIBUTING.md]",
            "tests/test_docs_antirot.py::test_every_documented_make_target_exists[TESTING.md]",
            "tests/test_docs_antirot.py::"
            "test_the_phase_line_points_at_the_index_rather_than_restating_it",
        ),
        red=(
            "ADVANCES. MET at 8fd2146 and grounded on an observed red. Re-derived AS IT STANDS "
            "TODAY -- widening the guarded document list is PDF-30's and is not done here.\n"
            "MUTATION: a spec identifier planted in README.md (`Planted by PDF-24: see "
            "PDF-99.`).\n"
            "OBSERVED: `AssertionError: README.md names ['PDF-24', 'PDF-99']; per-spec status "
            "belongs in the spec index` -- and the failure message is itself informative, "
            "because it caught the mutation's OWN prose token as well as the planted one.\n"
            "REVERTED from the gold tree; sha256 match."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC22",
        claim=(
            "[D7: R] `LICENSE` contains the full Apache-2.0 text; `NOTICE` exists; "
            '`pyproject.toml` declares `license = "Apache-2.0"` and `license-files = '
            '["LICENSE", "NOTICE"]`; `make build` produces an sdist and a wheel in `dist/` '
            "containing both files."
        ),
        covering=(
            "tests/test_cli_spine.py::test_packaging_declares_the_license_and_its_license_files",
        ),
        red=(
            "ADVANCES. MET at 8fd2146 and grounded on an observed red.\n"
            "MUTATION: `NOTICE` removed from `[project].license-files`.\n"
            "OBSERVED: `AssertionError: assert ['LICENSE', 'THIRD_PARTY_LICENSES'] == "
            "['LICENSE', 'NOTICE', 'THIRD_PARTY_LICENSES']` / `At index 1 diff: "
            "'THIRD_PARTY_LICENSES' != 'NOTICE'`.\n"
            "REVERTED from the gold tree; sha256 match.\n"
            "DRIFT, recorded not adjudicated: the declaration is now a THREE-element list -- "
            "PDF-02 added `THIRD_PARTY_LICENSES` because PLAN §11 requires it inside both "
            "archives. The criterion's two-element literal is a subset of what ships, so the "
            "property holds and this is not a supersession.\n"
            "FINDING: the ARCHIVE-CONTENT clause (*`make build` produces ... containing both "
            "files*) has no standing pytest control. It is checked by "
            "`scripts/assert_artifacts.py`, which runs only as a script -- from `make "
            "artifacts-check` and from ci.yml's build job -- so the covering node id above "
            "proves the DECLARATION, not the archives. Same instrument gap "
            "`audit_pdf_02.py`'s AC16 already recorded; cited rather than re-minted."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
        finding=(
            "PENDING-LEDGER: pdf-02-ac16-archive-content-has-"
            "no-standing-control (cited, not re-minted)"
        ),
    ),
    ACAudit(
        ac="AC23",
        claim=(
            "[D7: H] `changelog.md` exists with the Design §D.10 header, the literal "
            "`<!-- CHANGELOG-ANCHOR: ...` line, the three binding rules, and EXACTLY ONE entry "
            "-- `## [PDF-01] Project scaffold & CLI spine -- <date>` -- immediately below the "
            "anchor, added by this spec's OWN commit."
        ),
        covering=(),
        red=(
            "FINDING -- X-215(i): re-derived HISTORICALLY and NOT OBSERVED RED, because a "
            "historical git fact cannot be driven red by mutating the working tree, and "
            "manufacturing a control that 'proves' the history would prove only that something "
            "wrote a file saying so (the X-280 reasoning, applied to a second surface).\n"
            "RE-DERIVED against 478ab54, never with a heading grep at HEAD -- a grep at HEAD is "
            "exactly what hides a lost prepend. `git show 478ab54 -- changelog.md` shows the "
            "file created by THAT commit (`new file mode 100644`), whose subject is `[PDF-01] "
            "feat: project scaffold and CLI spine`. `git show 478ab54:changelog.md` carries: "
            "the `# Changelog` header and the one-entry-per-spec rule; the three numbered "
            "binding rules (append at the anchor / each spec's own commit writes its own entry "
            "/ never edit a landed entry); the literal anchor at line 21; and EXACTLY ONE "
            "`## [PDF-` heading -- `## [PDF-01] Project scaffold & CLI spine -- 2026-08-29`, "
            "starting two lines below the anchor with the blank line between them. `grep -c "
            "'^## \\[PDF-'` at that commit returns **1**.\n"
            "A STANDING CONTROL WAS DELIBERATELY NOT ADDED: it would have to read git history, "
            "and CI checks out shallow for every job but one, so such a test would red in CI "
            "for a reason unrelated to the property. `tests/test_cli_spine.py::"
            "test_changelog_prepends_every_spec_entry_below_the_anchor` covers the PREPEND "
            "invariant at HEAD, which is a different claim from this one."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-01-ac23-historical-changelog-claim-has-no-observable-red",
    ),
    ACAudit(
        ac="AC24",
        claim=(
            "[D7: R] `git check-ignore -v .scratch/` reports a match from `.gitignore`, and "
            "`grep -c '^\\.scratch/$' .gitignore` returns 1. `git check-ignore "
            "THIRD_PARTY_LICENSES` reports NO match (PDF-02 must be able to commit it)."
        ),
        covering=(
            "tests/test_cli_spine.py::"
            "test_gitignore_covers_scratch_but_not_the_generated_license_manifest",
        ),
        red=(
            "ADVANCES. MET at 8fd2146 and grounded on an observed red.\n"
            "MUTATION: the `.scratch/` line deleted from `.gitignore`.\n"
            "OBSERVED: `AssertionError: assert 0 == 1` / `where 0 = <built-in method count of "
            "list object>('.scratch/')` -- the control counts the line rather than testing "
            "membership, so a DUPLICATE would red it too.\n"
            "REVERTED from the gold tree; sha256 match.\n"
            "The negative half is a real assertion in the same control: no line mentioning "
            "`THIRD_PARTY_LICENSES` may appear, which is what keeps PDF-02 able to commit it."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC25",
        claim=(
            "[D7: H] `git log -1` shows exactly one new commit, subject tagged `[PDF-01]`, body "
            "carrying a `Signed-off-by:` trailer (`git commit -s`), and the diff lists only "
            "files named in Scope > In. No `.github/` file, no `THIRD_PARTY_LICENSES`, no "
            "`website/` file appears."
        ),
        covering=(),
        red=(
            "FINDING -- X-215(i): re-derived HISTORICALLY and NOT OBSERVED RED, for the same "
            "categorical reason as AC23. X-280 is directly on point: a procedural obligation of "
            "an engineer is not a property of the product, and a pytest control cannot assert "
            "it without asserting a lie.\n"
            "RE-DERIVED against 478ab54 with `git diff-tree --no-commit-id --name-only -r` -- "
            "**never `git show --stat`** (X-124). `git rev-list --count dc58472..478ab54` = "
            "**1**, so it is exactly one commit on top of the two-file scaffold. Subject: "
            "`[PDF-01] feat: project scaffold and CLI spine`. Trailers: `Signed-off-by: Armando "
            "Herra <armandoherra369@gmail.com>` present (plus `Co-Authored-By:` and "
            "`Claude-Session:`, flagged at the time as ruling X-46 and not a violation). "
            "Footprint: **31 paths**, top-level names `pyproject.toml, uv.lock, Makefile, "
            "README.md, CLAUDE.md, CONTRIBUTING.md, TESTING.md, LICENSE, NOTICE, changelog.md, "
            ".gitignore, src, tests` -- every one a Scope > In row. The forbidden-prefix grep "
            "(`^\\.github/|^website/|^THIRD_PARTY_LICENSES$`) returns **nothing**.\n"
            "A STANDING CONTROL WAS DELIBERATELY NOT ADDED: same shallow-checkout reason as "
            "AC23."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-01-ac25-historical-commit-hygiene-claim-has-no-observable-red",
    ),
)
