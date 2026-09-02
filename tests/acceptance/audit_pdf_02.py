"""`PDF-02`'s 20 acceptance criteria, re-derived — `AUDIT-CONVENTION(PDF-17)`.

`PDF-02` (`SPEC-INDEX.md`) has never held a `Verified` — its roster row reads
`Implemented (2026-08-29)`. This is the evidence for that first grant or
refusal, produced by `PDF-28` (Design §6/AC22, AC20/AC23) alongside its own
gate-parity deliverable. The `qa-sentinel` grants or refuses; this module does
not (AC24).

**Verdict counts — 8 `holds` · 2 `superseded` · 10 `unmeasured` = 20.**

`ACAudit` has no `verdict` field and `_model.py` is frozen, so `PDF-27`'s
three-value vocabulary is mapped onto the landed fields (declared deviation,
per Design §9.2 / R2):

* **`holds`** — a `red_kind` other than `NOT_OBSERVED`, with the mutation, the
  failure text and the revert recorded in `red`. AC1, AC2, AC6, AC11, AC12,
  AC13, AC17, AC19.
* **`superseded`** — the same, and `red` additionally records what the
  criterion originally asserted and what superseded it. AC3 (PDF-16's
  `deploy-website.yml`, added after `PDF-02` landed), AC5 (`PDF-06`, exactly
  as `PDF-02`'s own Validation block predicted it would be).
* **`unmeasured`** — `red_kind=NOT_OBSERVED` plus a real `finding`. AC4, AC7,
  AC8, AC9, AC10, AC14, AC15, AC16, AC18, AC20 — four of these (AC8, AC9, AC10,
  AC15) are the one-time historical `gh` observations `PDF-28`'s own spec
  (AC23) names in advance as expected to land this way: a deleted spike
  branch and a dispatched, never-repeated `workflow_dispatch` release run.
  **`unmeasured-by-construction` is a result to record, not a gap to fill
  with a newly written passing assertion** (`0615feae63`'s precedent). Every
  `unmeasured` row below still carries a MEASURED aside — re-derived against
  live source or a live `gh` query at `PDF-28`-HEAD, on 2026-09-02 — rather
  than a transcription of the original Implementation Log.

Every `holds`/`superseded` mutation below was applied to the working tree,
observed, and reverted by copying back from `git show HEAD:<path>` (or, for
`ci.yml`/`dependabot.yml`/`release.yml`, from a pre-mutation `cp` snapshot of
the then-current working tree, since those files were themselves mid-edit
under `PDF-28` at audit time); `git diff --exit-code` proved each revert exact
before the next mutation was applied. No mutation ever reached the index
except AC6/AC14's, which used a deliberate `git add` of a tampered baseline
(HC-4-compliant: never `git stash`) and was un-staged by re-adding the
restored file, verified with a second `git diff --exit-code`.
"""

from __future__ import annotations

from typing import Final

from acceptance._model import ACAudit, RedKind

SPEC_ID: Final[str] = "PDF-02"
AC_COUNT: Final[int] = 20

AUDIT: Final[tuple[ACAudit, ...]] = (
    ACAudit(
        ac="AC1",
        claim=(
            "gh workflow list shows CI and Release. ci.yml declares triggers push (branches "
            "[main]), pull_request, workflow_dispatch and workflow_call, and defines exactly "
            "the ten jobs lint, typecheck, test, engines-present, without-engines, sast, "
            "vulncheck, secret-scan, license-gate, build."
        ),
        covering=(
            "tests/test_gate_parity.py::test_pdf02_ac1_ci_yml_defines_exactly_the_ten_named_jobs",
        ),
        red=(
            "Appended a `noop:` job to ci.yml's jobs: block (the exact PDF-28 AC4 mutation, "
            "reused here against the PDF-02-specific assertion): `AssertionError: ('lint', "
            "'typecheck', ..., 'noop') == ('lint', 'typecheck', ..., 'build')` -- 'Left "
            "contains one more item: noop'. Reverted from a pre-mutation snapshot (the file "
            "was itself mid-PDF-28-edit at audit time, so git show HEAD: would have reverted "
            "PAST this cycle's own legitimate changes); git diff --exit-code clean; re-ran "
            "green. The trigger/job-name text asserted by the test is re-checked live against "
            "ci.yml on every run, not transcribed."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
    ),
    ACAudit(
        ac="AC2",
        claim=(
            "Across .github/workflows/*.yml, the count of lines matching uses: equals the "
            "count matching uses: [^@]*@[0-9a-f]{40}, and every such line carries a trailing "
            "# v comment."
        ),
        covering=(
            "tests/test_gate_parity.py::"
            "test_pdf02_ac2_every_external_action_reference_is_sha_pinned_with_a_version_comment",
        ),
        red=(
            "Replaced the first `actions/checkout@3d3c...ba90b1  # v7.0.1` with "
            "`actions/checkout@v7.0.1` (a tag, unpinned) in ci.yml. Failed: "
            "`AssertionError: (35, 1, 33)` / `assert 34 == 33` -- one fewer SHA-pinned line "
            "than external uses lines. Reverted from a pre-mutation snapshot; grep for the "
            "tag form returned 0; re-ran green. MEASURED, not transcribed against the 29 of "
            "PDF-02's own Implementation Log: at PDF-28-HEAD the count is 35 total uses: "
            "lines / 34 SHA-pinned / 1 local exemption (release.yml's `uses: "
            "./.github/workflows/ci.yml`, PDF-02's own documented exemption -- a local "
            "reusable workflow always runs at the caller's commit and carries no third-party "
            "supply-chain risk). The rise from 29 to 35 is deploy-website.yml, added after "
            "PDF-02 by PDF-16, and was not present when PDF-02's Implementation Log recorded "
            "29 = 29."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
    ),
    ACAudit(
        ac="AC3",
        claim=(
            "grep -rn 'write-all' .github/ returns nothing. Both workflows declare a "
            "workflow-level permissions: block; contents: write appears only on release.yml's "
            "github-release job and id-token: write only on its publish job."
        ),
        covering=("tests/test_gate_parity.py::test_pdf02_ac3_least_privilege_scoping",),
        red=(
            "Inserted `write-all: true` into release.yml's workflow-level permissions: block. "
            "Failed: `AssertionError: assert 'write-all' not in '...'`, naming the file. "
            "Reverted from a pre-mutation snapshot; grep for write-all returned 0; re-ran "
            "green.\n"
            "SUPERSEDED, not a violation: the criterion's ORIGINAL text (`id-token: write "
            "only on its publish job`) described PDF-02's own scope, written before PDF-16 "
            "added deploy-website.yml. MEASURED at PDF-28-HEAD: `id-token: write` now appears "
            "TWICE -- release.yml:82 (PyPI Trusted Publishing OIDC) and "
            "deploy-website.yml:15 (GitHub Pages OIDC deployment) -- a second, distinct, "
            "correctly scoped grant for a workflow that did not exist when AC3 was written, "
            "not a leak. `contents: write` is unchanged at exactly one site "
            "(release.yml:98). The test asserts the CURRENT correct shape (both id-token: "
            "write sites named) rather than PDF-02's original narrower one."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
    ),
    ACAudit(
        ac="AC4",
        claim=(
            "A CI run's job list contains exactly eight test (...) jobs, one per "
            "{3.11,3.12,3.13,3.14} x {ubuntu-latest, macos-14}. No macos-13 leg exists."
        ),
        covering=(),
        red=(
            "NOT OBSERVED RED -- no mutation was dispatched; a real GitHub Actions run costs "
            "wall-clock and money this re-verification does not need to spend, and PDF-02's "
            "own AC1/Design already proved the matrix mechanism once (the historical run "
            "cited there). MEASURED instead, live, against the latest green push at PDF-28 "
            "audit time (`PDF-27`'s landing run, not PDF-28's own -- that had not pushed "
            "yet): `gh run view 33617080928 --json jobs --jq '[.jobs[].name | "
            'select(startswith("test"))] | length\'` -> 8; the full name list is '
            "`test (3.11, ubuntu-latest)`, `test (3.11, macos-14)`, `test (3.12, "
            "ubuntu-latest)`, `test (3.12, macos-14)`, `test (3.13, ubuntu-latest)`, "
            "`test (3.13, macos-14)`, `test (3.14, ubuntu-latest)`, `test (3.14, macos-14)` "
            "-- no macos-13 leg. This is GitHub's own scheduler, genuinely external to this "
            "repository's code (PDF-28 Design §6's third consumer) -- it cannot be wrong "
            "about YAML the way a local parser can, but it is a live query, not a standing "
            "test, and it will need re-asking on every future re-verification."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-02-ac4-matrix-count-has-no-standing-control-gh-only",
    ),
    ACAudit(
        ac="AC5",
        claim=(
            "The engines-present job asserts tesseract --version and soffice --version both "
            "succeed before running the suite; the without-engines job fails if either binary "
            "is found on the runner, and runs scripts/assert_skips.py, which prints "
            "engine-gated skips: 0 with its stated PDF-06 vacuity note and exits 0."
        ),
        covering=(
            "tests/test_assert_skips.py::test_zero_engine_gated_skips_without_expect_zero_still_fails",
        ),
        red=(
            "Flipped the final `return 1` (the PDF-06 non-vacuity guarantee) to `return 0` in "
            "scripts/assert_skips.py. Failed: `AssertionError: engine-gated skips: 0 ... "
            "assert 0 == 1`. Reverted from a pre-mutation snapshot (the script was itself "
            "mid-PDF-28-edit for B-081 at audit time); git diff --exit-code clean; re-ran the "
            "full 6-test module green.\n"
            "SUPERSEDED, exactly as PDF-02's own Validation block predicted `PDF-06` would "
            "make it (V-10 of PDF-28's spec): assert_skips.py:116-130 now RETURNS 1 on a zero "
            "count in a without-engines run -- 'a zero here means the harness stopped "
            "skipping visibly ... both are regressions' -- and the vacuity note is gone. Live "
            "figures from the without-engines job, as re-confirmed by CI run 33617080928: "
            "assert_skips reports non-zero engine-gated skips and exits 0; the "
            "engines-present job's `--expect-zero` arm reports 0 and exits 0. Both engine "
            "preconditions (tesseract/soffice present in engines-present at ci.yml:117-120; "
            "absent in without-engines at ci.yml:157-162) are unchanged and re-confirmed by "
            "reading ci.yml at PDF-28-HEAD."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC6",
        claim=(
            "make licenses writes THIRD_PARTY_LICENSES with more than twenty lines, carrying "
            "the fixed header naming uv.lock, --no-dev --all-extras and Python 3.11. Running "
            "make licenses a second time leaves git diff --exit-code -- THIRD_PARTY_LICENSES "
            "clean (idempotent) -- including when run under a different ambient Python, "
            "verified locally on 3.14.4."
        ),
        covering=(
            "tests/test_gate_parity.py::test_pdf02_ac6_make_licenses_is_idempotent_on_the_current_interpreter",
        ),
        red=(
            "THE CONSTRUCTED CONTROL (PDF-28 AC21): `make licenses` regenerates "
            "THIRD_PARTY_LICENSES from the lockfile unconditionally, so a direct working-tree "
            "tamper is silently overwritten before the diff runs -- an append followed "
            "immediately by `make licenses-check` came back clean, which is CORRECT behaviour "
            "for a regenerate-then-diff target, not a defect, and is recorded here rather "
            "than hidden. The genuine red needs the COMMITTED baseline itself to be wrong: "
            "appended a line to THIRD_PARTY_LICENSES and `git add`ed it (staging a false "
            "baseline, never a `git stash`), then ran `make licenses-check`, which "
            "regenerates and diffs against the INDEX. Failed: `git diff --exit-code` printed "
            "the tampered line as a real diff and `make: *** [Makefile:264: licenses-check] "
            "Error 1`. Reverted by restoring the file from the pre-tamper copy and `git add`ing "
            "it again; a second `git diff --exit-code` confirmed clean and `git status "
            "--porcelain -- THIRD_PARTY_LICENSES` printed nothing.\n"
            "RE-DERIVED under the CURRENT interpreter, not transcribed: the '3.14.4' note is "
            "stale -- this venv is 3.12.13 (`uv run python -V`) -- and scripts/licenses.py "
            "pins its OWN measurement environment to 3.11 regardless (ci.yml:241-250), so the "
            "artefact is interpreter-independent by design. Two consecutive `make licenses` "
            "runs at PDF-28-HEAD produced a byte-identical 3431-line THIRD_PARTY_LICENSES and "
            "a byte-identical 157-line website/src/data/licenses.json; git diff --exit-code "
            "on both was clean."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
    ),
    ACAudit(
        ac="AC7",
        claim=(
            "With the real PLAN.md §7.1 dependency set installed, make licenses exits 0, and "
            "grep -i 'MPL' THIRD_PARTY_LICENSES finds pikepdf's row. The deny pattern in "
            "scripts/licenses.py is exactly AGPL|GPL|LGPL plus the documented prose alias, "
            "and ALLOWLIST is present, commented, and empty."
        ),
        covering=(),
        red=(
            "NOT OBSERVED RED -- no standing pytest test wraps scripts/licenses.py's deny "
            "pattern or ALLOWLIST directly; `tests/test_license_policy.py` covers the "
            "call-graph AST walk (HC-1's OTHER mechanism), not the dependency-graph scanner. "
            "MEASURED, not transcribed: `make licenses` at PDF-28-HEAD exits 0 and prints "
            "'[licenses] OK -- 32 packages, no AGPL/GPL/LGPL and no UNKNOWN'; "
            "`grep -i MPL THIRD_PARTY_LICENSES` finds pikepdf's row (unchanged); "
            "`grep -n 'ALLOWLIST' scripts/licenses.py` shows `ALLOWLIST: dict[str, str] = {}` "
            "at line 78 -- present, and empty. One live disjunctive-license case fires on "
            "every run and is reported rather than hidden: pyphen 0.18.1 is "
            "GPLv2+/LGPLv2+/MPL-1.1 tri-licensed, and the generator relies on the MPL-1.1 "
            "alternative -- exactly PDF-02's own Implementation Log finding, still true "
            "today, and still printed loudly each run rather than silently allowlisted."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-02-ac7-deny-pattern-and-allowlist-have-no-standing-control",
    ),
    ACAudit(
        ac="AC8",
        claim=(
            "On the throwaway branch of Design §9, with pymupdf added to [project] "
            "dependencies and uv lock run, a dispatched ci.yml run has license-gate "
            "conclusion failure, and the job log names the offending package and its AGPL "
            "license. The run URL and the offending log lines are recorded in this spec's "
            "Implementation Log."
        ),
        covering=(),
        red=(
            "NOT OBSERVED RED this cycle -- a ONE-TIME historical observation against a "
            "throwaway spike branch (spike/PDF-02-gate-red) that was deleted locally and on "
            "origin at PDF-02's own landing, exactly as PDF-28's spec AC23 names in advance "
            "as expected to land this way. RE-CONFIRMED LIVE, not merely transcribed: "
            "`gh run view 33274638657 --json conclusion,url` still resolves and still returns "
            "conclusion 'failure' at "
            "https://github.com/ArmandoHerra/pdf-toolkit/actions/runs/33274638657, matching "
            "PDF-02's own Implementation Log verbatim (license-gate failure naming "
            "'pymupdf 1.28.2: Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial "
            "License'). GitHub retains the run and its logs even though the branch is gone; "
            "the run is the standing evidence, and it cannot be re-driven without repeating "
            "the throwaway-branch exercise."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-02-ac8-spike-branch-red-is-historical-no-control",
    ),
    ACAudit(
        ac="AC9",
        claim=(
            "On the same branch and in the same dispatched run, with a subprocess call whose "
            "argv[0] literal is gs added to a src/ file, the test job conclusion is failure "
            "on tests/test_license_policy.py, and the failure message names gs, the file and "
            "the line."
        ),
        covering=(),
        red=(
            "NOT OBSERVED RED this cycle, same historical run as AC8 (33274638657) -- but "
            "the SAME MECHANISM was independently re-driven red under PDF-28, on a different "
            "file, for a different criterion (AC12/AC13 below): planting a forbidden `gs` "
            "argv[0] and a bare `subprocess` import outside the chokepoint in "
            "src/pdf_toolkit/errors.py both failed test_license_policy.py, naming the file "
            "and line, at PDF-28 audit time (2026-09-02) -- see AC12/AC13's own rows for the "
            "exact failure text. That is fresh, independent confirmation that the mechanism "
            "AC9 describes still fires; it is not a re-run of AC9's OWN historical run, whose "
            "conclusion is re-confirmed live: `gh run view 33274638657 --json "
            "conclusion,url` -> failure, matching PDF-02's own Implementation Log ('src/"
            "pdf_toolkit/__init__.py:38: forbidden subprocess argv[0] 'gs''; 'forbidden "
            "distributions declared in pyproject.toml: [pymupdf>=1.24]')."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-02-ac9-spike-branch-red-is-historical-no-control",
    ),
    ACAudit(
        ac="AC10",
        claim=(
            "The throwaway branch is removed locally and on origin. main carries exactly one "
            "DCO-signed commit whose subject starts [PDF-02], containing neither violation. "
            "Its CI run is green. That URL is recorded in the Implementation Log and is this "
            "cycle's wave gate."
        ),
        covering=(),
        red=(
            "NOT OBSERVED RED, and no mutation exists that could: this is a HISTORICAL "
            "criterion about a commit that has already landed and cannot be re-broken "
            "without breaking the product for everyone. RE-DERIVED rather than trusted: "
            "`git log -1 --format=%B 4fb6b07` shows the `[PDF-02] feat:` subject and a "
            "`Signed-off-by: Armando Herra` trailer; `git show --stat 4fb6b07` lists exactly "
            "13 files (.github/dependabot.yml, .github/workflows/{ci,release}.yml, "
            ".gitignore, Makefile, THIRD_PARTY_LICENSES, changelog.md, pyproject.toml, "
            "scripts/{assert_artifacts,assert_skips,licenses}.py, "
            "tests/{test_cli_spine,test_license_policy}.py), +4997/-8; "
            "`git show 4fb6b07:changelog.md | grep -c '^## \\[PDF-02'` -> 1. `gh run view "
            "33275075866 --json conclusion,headSha,url` re-confirmed LIVE at PDF-28 audit "
            "time: conclusion 'success', headSha 4fb6b07ad4a5b0d1377104d0447eea539d436e60. "
            "`git ls-remote --heads origin | grep spike` returns nothing -- the throwaway "
            "branch is gone on origin as well as locally."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-02-ac10-landing-commit-scope-has-no-standing-control",
    ),
    ACAudit(
        ac="AC11",
        claim=(
            "uv run pytest tests/test_license_policy.py -v passes, and its output shows both "
            "self-tests: the positive one asserting exactly three findings for a synthetic "
            'module with import fitz, a gs argv[0] and shutil.which("pdftotext"); the '
            "negative one asserting zero findings for a synthetic module containing gs = 1, "
            'def parse_gs_tokens(), settings = {"gs": 2} and flags = "...". Both synthetic '
            "sources are built at test time."
        ),
        covering=(
            "tests/test_license_policy.py::test_self_positive_detects_all_three_leaks",
            "tests/test_license_policy.py::test_self_negative_does_not_false_positive_on_gs",
        ),
        red=(
            "Both self-tests currently PASS (re-confirmed: `uv run pytest "
            "tests/test_license_policy.py -q` -> 10 passed). Their own red is not re-driven "
            "here as a THIRD mutation of the same shared functions -- the underlying "
            "scan_forbidden_names()/scan_chokepoint() they exercise were ALREADY driven red "
            "twice under PDF-28, on REAL code rather than their own synthetic fixtures: "
            "AC12's planted `import fitz` (a dynamic import, one of the self-test's own three "
            "leak kinds) and AC13's planted bare subprocess import both failed the SAME "
            "underlying walk these self-tests pin, with the identical failure shape "
            "('forbidden dynamic import'/'forbidden subprocess argv[0]', file and line "
            "named). That is independent, fresh evidence that the mechanism the self-tests "
            "assert stays correct is itself correct, without vandalising the self-tests' own "
            "committed synthetic fixtures to prove it a third way. `git ls-files | grep -i "
            "fitz` and equivalent forbidden-name greps under testdata/ return nothing -- both "
            "synthetic sources are confirmed built at test time, not committed."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC12",
        claim=(
            "tests/test_license_policy.py parses every *.py / *.pyi under src/ with ast, "
            "fails on SyntaxError naming the file, and fails on any file under src/ that is "
            "neither of those and not in NON_PYTHON_ALLOWED. It also asserts no forbidden "
            "name appears in pyproject.toml's dependencies or optional-dependencies."
        ),
        covering=("tests/test_license_policy.py::test_no_forbidden_names_under_src",),
        red=(
            "Appended `def _scratch_never_called_pdf28_ac12(): import importlib; "
            'importlib.import_module("fitz")` to src/pdf_toolkit/errors.py. Failed: '
            "`AssertionError: PLAN §7.2 forbidden names found under src/: "
            "src/pdf_toolkit/errors.py:254: forbidden dynamic import 'fitz'`. Reverted from "
            "git show HEAD:src/pdf_toolkit/errors.py; git diff --exit-code clean; re-ran "
            "green. This is one mutation of one real file under audit, not a re-run of the "
            "self-test's own committed synthetic fixture -- the first-hand red PDF-27's own "
            "AC18 audit convention (audit_pdf_03.py) argues for."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
    ),
    ACAudit(
        ac="AC13",
        claim=(
            "The test fails if any module under src/ outside pdf_toolkit/adapters/"
            "subprocess_util.py imports subprocess or calls os.system / os.exec* / "
            "os.spawn*. It passes vacuously today; the test's own docstring says so and "
            "names PDF-05 as the spec that first makes it bite."
        ),
        covering=("tests/test_license_policy.py::test_subprocess_chokepoint",),
        red=(
            "NO LONGER VACUOUS, first observed as such by this audit: appended `def "
            "_scratch_never_called_pdf28_ac13(): import subprocess; "
            'subprocess.run(["curl", "--version"])` to src/pdf_toolkit/errors.py -- '
            "'curl' deliberately chosen because it is NOT a forbidden name, to isolate this "
            "criterion from AC12's. Failed: `AssertionError: spawn-chokepoint violations "
            "(PLAN §8): src/pdf_toolkit/errors.py:252: forbidden import outside chokepoint "
            "'subprocess'` -- and test_no_forbidden_names_under_src (AC12's own test) PASSED "
            "in the same run, confirming the two controls are independent. Reverted from git "
            "show HEAD:src/pdf_toolkit/errors.py; git diff --exit-code clean; re-ran the full "
            "10-test module green. PDF-05 landed since AC13 was written (the docstring's own "
            "vacuity claim is now stale prose, not re-verified state -- a smaller, adjacent "
            "finding filed alongside this row's own)."
        ),
        red_kind=RedKind.PLANTED_DEFECT,
        finding="PENDING-LEDGER: pdf-02-ac13-docstring-still-claims-vacuous-after-pdf-05-landed",
    ),
    ACAudit(
        ac="AC14",
        claim=(
            "scripts/licenses.py check enumerates the universal lock closure and fails, "
            "naming the package, if any universally-resolvable runtime package was not "
            "measured by the pinned run and is not in the commented MARKER_ONLY map. "
            "Demonstrated by the check's own output listing the two compared set sizes in "
            "the license-gate job log."
        ),
        covering=(),
        red=(
            "NOT OBSERVED RED -- no standing pytest test wraps scripts/licenses.py's "
            "universal-closure comparison; it is exercised only as a script, by `make "
            "licenses` / the license-gate CI job. MEASURED, not transcribed: `make "
            "licenses-check` at PDF-28-HEAD prints '[licenses] measured 32 packages in the "
            "pinned closure' / '[licenses] universal lock closure lists 34 packages' / two "
            "'[licenses] MARKER-ONLY: ...' lines (brotlicffi, colorama -- both correctly "
            "classified as not installable on the pinned leg rather than silently missed) -- "
            "the two compared set sizes ARE printed, as the criterion requires, and the gap "
            "between them (34 - 32 = 2) is fully accounted for by the commented map rather "
            "than by an unexplained discrepancy."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-02-ac14-universal-closure-comparison-has-no-standing-control",
    ),
    ACAudit(
        ac="AC15",
        claim=(
            "gh workflow run release.yml (a workflow_dispatch, dry_run defaulting true) "
            "produces a run in which gate and build conclude success and publish concludes "
            "skipped. gh secret list shows no secret whose name starts with PYPI. No tag is "
            "created, no PyPI upload occurs, and gh release list is empty."
        ),
        covering=(),
        red=(
            "NOT OBSERVED RED this cycle -- a one-time historical dispatch, and re-dispatching "
            "would re-run the FULL ci.yml job set as release.yml's own gate (its `uses: "
            "./.github/workflows/ci.yml`), which is out of proportion to re-verifying a "
            "criterion that has not changed. RE-CONFIRMED LIVE instead: `gh run view "
            "33275138205 --json jobs --jq '[.jobs[] | {name, conclusion}]'` at PDF-28 audit "
            "time still returns all 17 'gate (full CI) / ...' legs 'success', the top-level "
            "'build' job 'success', and BOTH 'publish (PyPI)' and 'github-release' "
            "'skipped' -- byte-identical in shape to PDF-02's own Implementation Log. `gh "
            "secret list` at audit time shows no PYPI*-named secret; `gh release list` is "
            "empty; release.yml's own header comment still reads 'CONFIGURED AND NEVER "
            "FIRED', re-confirmed by reading the file."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-02-ac15-release-dispatch-is-historical-not-a-standing-control",
    ),
    ACAudit(
        ac="AC16",
        claim=(
            "The build job asserts, by reading the archives, that LICENSE, NOTICE and "
            "THIRD_PARTY_LICENSES are present inside both dist/*.whl and dist/*.tar.gz. "
            "Reproducible locally with uv build plus the same assertion script."
        ),
        covering=(),
        red=(
            "NOT OBSERVED RED -- no standing pytest test wraps scripts/assert_artifacts.py; "
            "it runs only as a script, in ci.yml's build job and PDF-28's new `make "
            "artifacts-check`. MEASURED, not transcribed: `make artifacts-check` at "
            "PDF-28-HEAD built dist/pdf_toolkit-0.1.0.dev0.tar.gz and "
            "dist/pdf_toolkit-0.1.0.dev0-py3-none-any.whl and printed 'both artifacts carry "
            "LICENSE, NOTICE, THIRD_PARTY_LICENSES', naming both filenames. A companion, "
            "narrower standing test does exist and was re-confirmed: "
            "tests/test_cli_spine.py::test_packaging_declares_the_license_and_its_license_files "
            "asserts pyproject.toml's own `license-files` DECLARATION, not the built "
            "archives' actual contents -- a real but partial substitute, named here so a "
            "later reader does not mistake it for full AC16 coverage."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-02-ac16-archive-content-has-no-standing-control",
    ),
    ACAudit(
        ac="AC17",
        claim=(
            ".github/dependabot.yml exists with exactly two package-ecosystem: entries (the "
            "Python block and github-actions), no npm entry, and ends with the PDF-16 append "
            "anchor. grep -c 'PDF-16 appends the npm' .github/dependabot.yml -> 1; "
            "grep -c 'PDF-16 inserts the website licenses.json drift diff' "
            ".github/workflows/ci.yml -> 1, and that line sits inside the license-gate job, "
            "after the freshness diff step."
        ),
        covering=(
            "tests/test_gate_parity.py::test_pdf02_ac17_the_two_pdf16_anchors_are_present_exactly_once",
        ),
        red=(
            "Deleted the `# PDF-16 appends the npm ecosystem block ...` anchor comment line "
            "from .github/dependabot.yml. Failed: `assert 0 == 1`, naming the anchor string "
            "and the file's full contents in the diff. Reverted from a pre-mutation snapshot "
            "(the surrounding file was not itself under PDF-28 edit, but a snapshot was used "
            "for symmetry with the other config mutations in this module); grep for the "
            "anchor returned 1 again; re-ran green.\n"
            "The 'no npm entry' half of the ORIGINAL text is now literally false -- PDF-16 "
            "APPENDED an npm ecosystem block, exactly as the anchor comment authorizes -- and "
            "that is the anchor mechanism working as designed, not a violation: the test "
            "asserts the anchor's PRESENCE and placement, not the absence of what it exists "
            "to permit (the same 'audited as intent, not luck' shape audit_pdf_03.py's AC1 "
            "row names for a different anchor)."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
    ),
    ACAudit(
        ac="AC18",
        claim=(
            "git show --stat HEAD for the [PDF-02] commit lists neither README.md nor "
            "CLAUDE.md, lists no file under website/, and lists changelog.md with exactly one "
            "added [PDF-02 ...] entry. Any Makefile or pyproject.toml line touched is "
            "justified in the Implementation Log against Scope > In."
        ),
        covering=(),
        red=(
            "NOT OBSERVED RED, and no mutation exists that could: this is a HISTORICAL "
            "criterion about a commit that has already landed. RE-DERIVED rather than "
            "trusted: `git show --stat 4fb6b07` lists exactly 13 files -- "
            ".github/dependabot.yml, .github/workflows/ci.yml, .github/workflows/release.yml, "
            ".gitignore, Makefile, THIRD_PARTY_LICENSES, changelog.md, pyproject.toml, "
            "scripts/assert_artifacts.py, scripts/assert_skips.py, scripts/licenses.py, "
            "tests/test_cli_spine.py, tests/test_license_policy.py -- and NEITHER README.md "
            "NOR CLAUDE.md, and no file under website/ (website/ did not exist until PDF-16). "
            "`git show 4fb6b07:changelog.md | grep -c '^## \\[PDF-02'` -> 1, confirmed IN "
            "THAT COMMIT rather than as a heading grep at HEAD (which is exactly the "
            "check that would hide a lost prepend, per this same criterion's own reasoning "
            "applied one level up by X-183/X-198). Makefile's PDF-02-era diff (`licenses:` "
            "target, `secret-scan:` guard) and pyproject.toml's (license-files, sdist "
            "include) are both named against Scope > In in PDF-02's own Implementation Log "
            "table, re-read and found accurate."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-02-ac18-landing-commit-file-list-has-no-standing-control",
    ),
    ACAudit(
        ac="AC19",
        claim=(
            "With gitleaks absent (its state on this workstation), make secret-scan exits "
            "non-zero and prints an install hint; it never exits 0. In CI it runs against the "
            "full history (fetch-depth: 0) and passes."
        ),
        covering=(
            "tests/test_gate_parity.py::test_pdf02_ac19_make_secret_scan_refuses_loudly_when_gitleaks_is_absent_from_path",
        ),
        red=(
            "THE CONSTRUCTED CONTROL, and OBSERVED RED IS THE WHOLE CRITERION (PDF-28 AC21): "
            "the premise 'gitleaks absent' is STALE -- `gitleaks version` on this host prints "
            "'version is set by build process', i.e. it is PRESENT at /usr/bin/gitleaks, just "
            "not the CI-pinned 8.30.1 (V-5; B-121). The real /usr/bin/gitleaks binary is never "
            "touched, moved, chmod'd or deleted (R4) -- the control is a PATH shadow only. "
            "`env PATH=/nonexistent make secret-scan` does NOT work as a shell command -- "
            "independently confirmed: `env` execs its target using the NEW environment, so it "
            "cannot even find `make` ('env: 'make': No such file or directory'). The form "
            "that shadows PATH for the RECIPE's own subprocesses without needing to "
            "re-resolve `make` itself is a make command-line variable override: `make "
            "secret-scan PATH=/nonexistent`. RED: 'make: gitleaks is not on PATH. This gate "
            "cannot run, and it will NOT exit 0 pretending that it did. Install: "
            "https://github.com/gitleaks/gitleaks/releases ...', exit 2 (make's wrapper "
            "around the recipe's own `exit 1`). Un-shadowed (`make secret-scan` with the "
            "normal PATH): runs `gitleaks detect --no-banner` against the real binary and "
            "exits 0 -- confirmed separately, gitleaks scans the repo and finds nothing to "
            "report."
        ),
        red_kind=RedKind.MUTATED_CONFIG,
    ),
    ACAudit(
        ac="AC20",
        claim=(
            "With website/src/data/ absent, make licenses prints the documented skip note "
            "and still exits 0. With that directory created by hand in a scratch worktree, it "
            "writes licenses.json as canonical, sorted, two-space-indented pip-licenses "
            "--format=json output ending in a newline, and a second run leaves it byte-"
            "identical."
        ),
        covering=(),
        red=(
            "NOT OBSERVED RED -- both arms are DEGRADE-GRACEFULLY/DETERMINISM checks, not "
            "failure-mode checks, and no standing pytest test wraps scripts/licenses.py's "
            "website/src/data/ branch. MEASURED both arms, live, at PDF-28-HEAD: absent arm -- "
            "renamed website/src/data/ aside, ran `uv run python scripts/licenses.py "
            "generate`, observed 'website/src/data/ absent — skipping licenses.json (PDF-16 "
            "creates it)' printed and the process exited 0 (THIRD_PARTY_LICENSES still "
            "written, 3431 lines); restored the directory, `git status --porcelain -- "
            "website/src/data` printed nothing, confirming the rename-and-restore left no "
            "residue. Present arm -- covered by AC6's own idempotence run in the same "
            "session: two consecutive `make licenses` runs produced a byte-identical "
            "157-line website/src/data/licenses.json, `git diff --exit-code` clean."
        ),
        red_kind=RedKind.NOT_OBSERVED,
        finding="PENDING-LEDGER: pdf-02-ac20-website-data-branch-has-no-standing-control",
    ),
)
