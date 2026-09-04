# Changelog

All notable changes to pdf-toolkit, newest first. **One entry per implemented spec,
written by that spec's own commit** — never batched, never back-filled, never edited
afterwards (a correction is a new entry).

Entry format: `## [PDF-NN] <Spec title> — <YYYY-MM-DD>`, then 1–5 bullets.
New entries are inserted **directly below the anchor line**, above the previous newest entry.

Three rules bind every entry:

1. **Append at the top, at the anchor.** Never at the bottom, and never inside another
   entry.
2. **Each spec's own commit writes its own entry**, so `git show <sha> -- changelog.md`
   proves the entry and the code landed together.
3. **Never edit a landed entry.** A correction is a new entry with a new date.

Audit this file per commit with `git show <sha> -- changelog.md`, never with a heading
grep at `HEAD` — a grep at `HEAD` is exactly what hides a lost prepend.

<!-- CHANGELOG-ANCHOR: insert new entries directly below this line, newest first -->

## [PDF-34] X-474 (2/2): the bounded observation window closed with zero scheduled runs — AC17 PARTIAL, cron reset to weekly — 2026-09-04

- **The attempt, and its result, stated plainly rather than optimistically.** The prior entry tightened `docs-gate`'s cron to `*/5 * * * *` at commit `28ea6b1` (pushed `2026-09-04T20:51:22Z`) for a capped 90-minute observation window. `gh run list --workflow=ci.yml --json databaseId,event,status,conclusion,createdAt`, polled repeatedly to the cap (`2026-09-04T22:21:22Z`, closed at `2026-09-04T22:21:37Z`), returned **zero** runs with `event == "schedule"` in that window — every run observed in the interval was `event: push` (this branch's own commits).
- **AC17 disposition: PARTIAL, not LANDED.** The `schedule:` trigger exists in `ci.yml` and its cron expression is syntactically valid (confirmed by `yaml.safe_load` parsing it as `{'cron': '...'}`), but *"a workflow whose `schedule:` has never fired is a cadence on paper"* — no observed run means the criterion's own text is not satisfied. What remains owed: a later, passive observation (the cron now reverts to weekly below, so the next opportunity is a real Sunday 06:00 UTC firing, not another bounded window) — or a repeat of this same bounded-tightening technique on a future maintenance pass, at the PM's discretion. This is not fabricated as a pass; GitHub's own documented behavior (schedule delivery from the default branch, delayed and best-effort, sometimes skipped under load) is exactly why the criterion demands an OBSERVED run rather than accepting the file's cron line as sufficient evidence — and that same behavior is why 90 minutes did not guarantee one.
- **The cron is reset to weekly (`0 6 * * 0`), unconditionally, exactly as committed to before the window opened.** This file is never left carrying a tightened cron regardless of outcome; the reset does not depend on whether a run was observed. `.github/workflows/ci.yml`'s trigger block records both the window's bounds and its zero-run result in a comment, so a later reader does not have to reconstruct this from git log archaeology.

## [PDF-34] X-474 (1/2): AC17's cron tightened to `*/5 * * * *` for a bounded observation window — 2026-09-04

- **Temporary, and stated as temporary in the diff itself.** The prior entry landed `docs-gate`'s weekly `schedule:` on paper; AC17 also requires an OBSERVED `event: schedule` run, not merely the cron expression sitting in the file — *"a workflow whose `schedule:` has never fired is a cadence on paper."* GitHub delivers `schedule:` only from the default branch and often late, so the cron is tightened to `*/5 * * * *` for a capped 90-minute observation window starting from this commit's push, watched via `gh run list --workflow=ci.yml --json databaseId,event,status,conclusion,createdAt` filtered to `event == "schedule"`.
- **A follow-up commit resets this to weekly unconditionally**, whether or not a scheduled run is observed inside the cap — this file is never left carrying a tightened cron. That reset entry records AC17's final disposition (LANDED or PARTIAL) with its evidence.

## [PDF-34] D4/D5/AC10/AC11/AC12/AC17: the deferred unit lands — `docs-gate` runs in CI, `test`'s history arms stop skipping, and a weekly cadence — 2026-09-04

- **D4, landed with its own measured bound, not deferred behind it.** The new single-leg `docs-gate` job (`ubuntu-latest`, `fetch-depth: 0`, `uv sync --locked`, `make docs-gate`) sits between `secret-scan` and `license-gate`. `timeout-minutes: 5` carries a real p95, re-derived independently rather than transcribed: five green **job** conclusions (`gh api .../jobs`, not the enclosing run — see the next bullet) on throwaway branch `pdf34-p95-measure`, ids `33913473653, 33913606349, 33913611800, 33913616874, 33913621276` (2026-09-04), durations `[20, 19, 19, 19, 16]` s from `started_at`/`completed_at`. `scripts/measure_gate.py::summarize()`'s own index formula — `index = round(0.95 * (n-1))`, `n=5` → `index=4` → the sorted array's last element — gives **p95 = 20.0s**; 3x = 1.0 min, raised to the 5 min floor, matching every other job's derivation shape in this file.
- **The job-vs-run greenness distinction is the reason those five ids are not contiguous, and it is recorded rather than smoothed over.** `gh run list` on `pdf34-p95-measure` shows every RUN in that window as `conclusion: cancelled` — the surrounding run is red by construction there, on the pre-derivation `test` job (X-473's own throwaway-branch shape, the same one this file's header records `PDF-29` using). The `docs-gate` JOB inside four of those runs nonetheless completed `success` with real timing data; one earlier dispatch (`33913480024..33913497795`) produced **zero** job data because it was cancelled before starting. That is the concurrency-queue finding below, not a measurement error, and the derivation comment on the job says so explicitly: *"'green runs' below counts the docs-gate JOB's own conclusion... the surrounding RUN is red there by construction."*
- **D5, decided on a measured number, not an aesthetic.** `fetch-depth: 0` is added to the `test` job's checkout (option 2). Measured from real step timestamps: D5 run `33913794214` (fetch-depth: 0) reports the `actions/checkout` step at 1s on `ubuntu-latest` (3.12) and 2s on `macos-14` (3.12); baseline run `33910574692` (shallow, the pre-existing default) reports the identical step at 1s and 2s respectively on the same two legs. **Delta ~=0-1s on both OSes** (GitHub's job-step timestamps are second-granularity, so the true delta sits inside that band either way) — seconds against a `make ci` budget of 331.25s (`PDF-29`). **This is not a budget question and it is not the same budget**: `PDF-29`'s 331.25s bounds the LOCAL `make ci` gate; `fetch-depth: 0` on a CI checkout step costs CI wall clock and touches `make ci` not at all. Even collapsed into one figure they would be 0-1s against 331.25s. No escalation. The whole skip class this closes: ten `833321e40b` history-depth arms plus both `036fd0a353` changelog-debt arms now run on the job that matters most (AC11), instead of skipping silently against a one-commit checkout.
- **AC17 Tier 1: a weekly `schedule:` trigger, landed at the correct final state.** `"on":` gains `schedule: - cron: "0 6 * * 0"` (Sunday 06:00 UTC). GitHub has no per-job schedule, so a scheduled run exercises the whole job set, not only `docs-gate` — a wider net than the criterion requires. The observed-run half of AC17 (a real `event: schedule` run, not merely the cron expression on paper) is a separate, later step (X-474) — GitHub delivers `schedule:` only from the default branch and often late, so it cannot be observed from a feature commit before `main` carries it.
- **The five X-472 coordinates, each with its anti-gaming discriminator**, all in this commit: (1) `tests/test_gate_budget.py::EXPECTED_JOB_COUNT` `10 -> 11`, consumed at `test_ci_yml_parses_to_exactly_eleven_jobs` (renamed from `..._ten_jobs`) and at `test_every_timeout_is_preceded_by_its_derivation` — both pass here because `docs-gate` lands WITH its bound in this same commit, never deferred behind a follow-up. (2) `DERIVATION_COMMENT`'s regex (`p95\s+[\d.]+s\s+over\s+\d+\s+green\s+runs`) is satisfied by the real bound above, sitting within the 3-line window `timeout_sites()` checks; the job's own greenness-distinction prose sits ABOVE the matching line rather than inside it, so the regex is not broken by the clarification the way a naive placement would break it. (3) `tests/test_gate_parity.py`'s frozen `10/17/19 -> 11/18/20`, and the test's own name moves with it: `test_the_independent_scan_finds_ten_jobs_seventeen_legs_nineteen_gating_steps` -> `..._eleven_jobs_eighteen_legs_twenty_gating_steps`; `test_manifest_parses_with_tomllib_and_declares_schema_version_1`'s `len(manifest["check"])` `19 -> 20`. (4) `.github/gate-parity.toml` gains one `[[check]] job = "docs-gate"` entry **in this same commit**, never after — the discriminator this whole coordinate set exists to enforce (D4's own text: *"a bare count bump with no manifest entry leaves the agreement test red, which is the guard doing its job"*), and `test_gate_parity_check_subcommand_agrees_with_the_independent_scan` passes on it. (5) `_PDF02_EXPECTED_JOBS` gains `"docs-gate"` at its scan-derived position (between `secret-scan` and `license-gate`) — a **CONTRACT CHANGE**: PDF-02 asserted a ten-job CI, PDF-34 D4 authorises the eleventh. All four figures re-derived by running the independent scan at implementation HEAD, never transcribed: `11 jobs / 18 legs / 20 gating steps / 20 manifest checks`.
- **The stale name stays stale, deliberately, and it is filed rather than fixed.** `test_pdf02_ac1_ci_yml_defines_exactly_the_ten_named_jobs` keeps its ten-jobs name while asserting eleven names, because `tests/acceptance/audit_pdf_02.py:63`'s `covering=(...)` cites this exact node id, and `tests/acceptance/audit_pdf_*.py` is outside PDF-34's Scope In table — the spec's own E6 already ruled this class out of scope, the same category `PDF-30` AC28 ruled out of a citation sweep. Renaming here would silently break an out-of-scope covering pointer instead of fixing it. `audit_pdf_02.py`'s own stale "ten jobs" claim prose is filed alongside it, for the same reason. Both are a PDF-02 re-verification's or the PM's to correct, not this spec's.
- **FINDING, filed and not fixed: `cancel-in-progress: false` does not protect a QUEUED run from being superseded by a newer dispatch in the SAME concurrency group.** Re-derived from the X-473 measurement dispatches on `pdf34-p95-measure`: five `workflow_dispatch` runs seconds apart into `ci-${{ github.ref }}` produced one real run with job data and four dead runs cancelled before a single job started (`33913480024, 33913485759, 33913491555, 33913497795`) — GitHub supersedes a queued-but-not-started run in that group the instant a newer one lands, regardless of `cancel-in-progress`. `ci.yml`'s real concurrency posture (`group: ci-${{ github.ref }}`, `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`) is **unchanged by this commit** — the measurement-branch-only override that appended `github.run_id` to the group (`092ffd9`, `pdf34-p95-measure` only) is explicitly NOT landed here. This finding is about a race between successive dispatches into the same group generally, not specific to that override.
- **CI flake watch, named rather than pre-empted.** Two already-filed, already-known flake classes (`PDF-46`/`B-216`, process/temp-cleanup) are the only ones any post-push rerun is authorised against: `tests/integration/test_office.py::test_ac13_timeout_kills_the_whole_process_group` and `tests/rasterize/test_rasterize_signals.py::test_sig{int,term}_to_parent_only_*`. Any other red surfaced by the newly-honest `test`-job history arms is a NEW finding under AC21 and is filed, not rerun past.
- **Nothing was weakened to reach green.** `--cov-fail-under=85` keeps its single site (`Makefile:107`, zero-line diff); `ENTRY_OWED_EXEMPT` is byte-unchanged at five members with its `== 5` intact; `RESIDUE_CEILING` is byte-unchanged (`TESTING.md`, `README.md`, `CLAUDE.md`, `CONTRIBUTING.md` all untouched by this commit); the `# pragma: no cover` total under `src/` stays **46**; `src/`, `pyproject.toml`, `tests/acceptance/` and `TESTING.md` carry a zero-line diff; no test was deleted, skipped or xfailed.

## [PDF-34] X-467: `be89f36` is registered, not paid — the register grows to five with its finding attached — 2026-09-04

- **The mechanism, measured: both entry-owed arms read an immutable property of a landed commit, and no later commit changes what they read.** `test_every_spec_or_remediation_commit_writes_its_own_entry` and `test_the_entry_owed_guard_can_fail` (`tests/test_changelog_history.py:428`, `:478`) both evaluate `CHANGELOG not in touched_files(sha)`, where `touched_files()` (`:171-172`) is `git diff-tree --no-commit-id --name-only -r <sha>` over a **landed** commit. Re-measured here: `git diff-tree --no-commit-id --name-only -r be89f36` returns `README.md` and `website/src/components/QuickStart.astro` — no `changelog.md` — and its subject, `[B-218] docs: install lines flip to PyPI now that pdf-tooling 0.1.1 is live`, matches `OWES_AN_ENTRY` (`:113`). No entry written in any later commit, including this one, changes either fact: `be89f36`'s touched-file set is landed and immutable. X-408's ground (iii), which its own text called decisive, is **false** — paying the debt with a correction entry cannot turn either arm green, because neither arm reads what a later commit wrote; it reads what `be89f36` wrote.
- **What changed, and why it is the register doing what it was designed to do.** `ENTRY_OWED_EXEMPT` (`:88-94`) grows from four members to five, `be89f36` appended as the fifth; `test_the_entry_owed_register_is_frozen_reachable_and_older_than_head`'s assertion (`:459`) moves `len(...) == 4` to `== 5`. That assertion's own failure message says growing the register "is a FINDING for the PM, never an edit made to reach green" — it is designed to move only with a finding attached, where the coverage floor beside it (`--cov-fail-under=85`, unchanged) is designed never to move at all. The PM is the finding's recipient and has ruled: **X-467, registered.** Precedent on this exact product, re-derived rather than trusted: `b3c92f7` (`[PDF-18] fix: AC12's convert cell must respect engine absence, not assume it`) matches `OWES_AN_ENTRY`, and `git diff-tree --no-commit-id --name-only -r b3c92f7` returns `src/pdf_toolkit/cli/cmd_compress.py`, `src/pdf_toolkit/ops/office.py`, `src/pdf_toolkit/ops/optimize.py`, `tests/integration/test_out_dir_planning.py` — no `changelog.md` — and it was registered, growing the register three to four at `7afdb1a`.
- **X-470, explicitly: two landed assertions are falsified by this registration, and both are left byte-unchanged.** `changelog.md:29` asserts `ENTRY_OWED_EXEMPT` "is byte-unchanged at four members with its `== 4` intact"; `changelog.md:34` asserts the debt "was NOT laundered into the register… byte-unchanged at its four members." X-467 falsifies both — the register is at five members with `== 5` as of this entry. Neither line is edited: this file's third rule makes a correction a new entry, and this entry is that correction — the same handling this file's `[PDF-34]` entry gave its own falsified `[B-090]` bullet ("left byte-unchanged; a row quietly reworded is indistinguishable from one that was never wrong," at `changelog.md:29`). `:34`'s own `tests/test_changelog_history.py:81-86` citation is now coordinate rot as well — the register moved to `:88-94` when the fifth member was appended — and that citation is also left alone.
- **What stays refused.** Option (C) — changing the guard so a later correction entry discharges an already-landed commit's debt — stays refused. `changelog.md:14-15`'s second rule is that each spec's own commit writes its own entry, so `git show <sha> -- changelog.md` proves the entry and the code landed together; honouring a later correction as a discharge path destroys that landed-together property for every future debt, not just this one. That is weakening the arm that found the problem, and AC21 forbids it.
- **The landed `[B-218]` correction entry ("correction: `be89f36` landed owing a changelog entry and wrote none", 2026-09-04) STAYS, unedited and unreverted.** It is a legitimate new entry at the anchor with its own date, and it is the human-readable record of what `be89f36` should have written. It was never the guard's discharge path and never claimed to be — its own closing sentence already said "the arms therefore remain red at this commit, correctly." Nothing about it is reverted here.
- **The proof was banked before the green, not after.** `test_the_entry_owed_register_is_frozen_reachable_and_older_than_head` and its sibling entry-owed arm were driven RED first: in a scratch `git worktree` (never a stash), `ENTRY_OWED_EXEMPT` reverted to its four pre-`be89f36` members and `== 5` reverted to `== 4`, both arms failed, each message naming `be89f36` as the sole offender against the four-member expectation — `"commit(s) owing a changelog entry that wrote none:\n  be89f36 (…)"` and `"it named [...'be89f36']"` where the expectation held only the other four shas. `== 4` passed on that reverted tree, confirming `== 5` is what carries the fix on the real tree. The worktree was then removed and pruned. This is not a gate observed green before it was ever shown red.
- **Nothing else was weakened to reach this green.** `--cov-fail-under=85` keeps its single site (`Makefile:107`); the `# pragma: no cover` total under `src/` stays **46**; `RESIDUE_CEILING` (`tests/test_docs_antirot.py`) is byte-unchanged, and its `GUARDED_DOCS` set (`README.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `TESTING.md`) does not cover this file, so the figures above carry no ceiling risk; `src/`, `pyproject.toml`, `.github/`, `Makefile` and `TESTING.md` carry a zero-line diff; no test was deleted, skipped or xfailed.

## [PDF-34] No gate exits 0 while its arms are red — `pipefail`, a strict posture, and the publish path gated — 2026-09-04

- **Three gates can now fail, and each was shown failing before it was shown passing.** `Makefile` declares `.SHELLFLAGS := -o pipefail -c` (D1), so `docs-gate`'s arms 1 and 3 stop inheriting `tail -1`'s and the epilogue reader's status. The control is an **identical tree read twice**: with the line, `make docs-gate` exits **2**; with the single line deleted and nothing else changed, it exits **0** — while arm 3 reports **`2 failed, 140 passed, 5 skipped`** in *both* runs. Same red, two verdicts; that is the whole defect in one measurement (`909f1bae72` / `B-231`). D3 adds `DOCS_GATE_STRICT`: the epilogue has printed *"A SKIPPED ARM IS NOT AGREEMENT"* and exited 0 for its whole existence, and that sentence is now an exit code — fed a five-skip, zero-failure run the epilogue returns **0** unset and **1** under `DOCS_GATE_STRICT=1`, and **0** under strict on a zero-skip run, so the default posture is byte-for-byte unchanged and strict fires only on a real skip. D2 pins the flag choice with a test, including the *negative* half (`-e` and `-u` excluded by measurement, not taste), so deleting or widening the line reddens instead of passing review. D7 closes **`B-164`**: `deploy-website.yml` gained a `gate (full CI)` job calling `./.github/workflows/ci.yml` with `build` on `needs: gate` — `workflow_call`, never `workflow_run`, because `workflow_call` gates *the exact commit being published*, keeps the `paths:` filter, and needs no `head_sha` plumbing whose omission ships a different commit than the one that went green. Until this commit a push to `main` published the site with nothing in front of it.
- **FINDING, filed and not fixed: the spec specified a discharge path that does not exist, and this is the measurement rather than an argument.** D9/AC7/AC2's second half assume a **correction entry** for `be89f36` turns `036fd0a353`'s two arms green. It does not, and no forward-fix can. Both arms evaluate `CHANGELOG not in touched_files(be89f36)`, and `touched_files()` is `git diff-tree --no-commit-id --name-only -r <sha>` — **an immutable property of a landed commit**. `git diff-tree` on `be89f36` returns `README.md website/src/components/QuickStart.astro`, and its `[B-218]` subject matches `OWES_AN_ENTRY`, so it is a permanent offender. Driven both ways at this tree: **with** the correction entry present and **with** it reverted, the two failure messages are byte-identical and name `be89f36` as the sole offender. Only three dispositions exist — **(A)** grow `ENTRY_OWED_EXEMPT` to five and bump `== 4` to `== 5` at `tests/test_changelog_history.py:447`; **(B)** land the unblocked subset and defer the CI arm-running work; **(C)** change the guard so a correction discharges the debt. **(B)** was taken. **(A)** is refused here on the guard's own instruction — *"growing it is the B-042 class recurring and is a **FINDING for the PM**, never an edit made to reach green"* — and **(C)** would soften the arm that found the problem. The two arms therefore stay red at this commit, **correctly**, for exactly one reason, naming exactly one commit. The disposition is the PM's.
- **What did NOT land, and why the omission is the point rather than an excuse.** **D4** (the new `docs-gate` CI job), **D5** (the `test` job's `fetch-depth` decision) and their criteria **AC10 / AC11 / AC17** are deferred **as one unit**: with `fetch-depth: 0` the entry-owed arms *run* and *fail*, so D4 would arrive red, redden `main` permanently, and — through the very `needs: gate` D7 adds one bullet above — block every subsequent publish. That inverts exactly what the wave ordering sequenced this spec first to achieve. `continue-on-error: true` is not an escape hatch and was not used: this file's own first paragraph forbids it by name, *a gate that cannot fail is not a gate*. **D6** (a workflow-level `defaults: run: shell: bash` replacing `ci.yml:290`'s lone `set -euo pipefail`) was **tried, measured, and reverted on the evidence**, which is the branch AC14 explicitly permits: dispatched run **`33894266632`** returned **`failure`** with **10 of 17 jobs red** on one arm — `tests/test_gate_budget.py::test_the_naive_two_space_key_grep_is_the_wrong_instrument`, whose message had pre-written its own diagnosis, *"the over-count now has a second cause worth understanding"*. The second cause is the `run:` key the `defaults:` block introduces at two-space indent. `ci.yml` is byte-identical to its parent at this commit; the arm was not softened and the finding is filed.
- **Two stale counts corrected with the recipe published, because a stale figure above a skip census is this target's own defect one level up.** `docs-gate`'s comment claimed *"two"* planning arms and *"four"* history arms. **Measured: FIVE planning arms in one class; ELEVEN history arms in TWO classes** (ten against `MINIMUM_HISTORY_DEPTH`, plus one that cannot check a depth precondition against a checkout never given the depth to check it); **SIXTEEN arms in THREE classes** in total. The spec's own *"ten"* was wrong in the same direction. Recipes: `PDF_TOOLKIT_PLANNING_DIR=/nonexistent make docs-gate` for the planning class (strict mode prints `5 skipped arm(s) in 1 class(es)`), and running arm 3's three files inside a `git clone --depth 1` for the history classes. The blast-radius census was re-derived the same way: `grep -cP '^\t.*\|' Makefile` returns **9** and is the **wrong instrument**; `awk` stripping `||` first returns **5**, across `help`, `samples-scratch` (twice) and `docs-gate` (twice). Related, and recorded here because a correction is a new entry: this file's own `[B-090]` bullet reasoning *"`Makefile:9` sets `SHELL := /bin/bash` with no `.SHELLFLAGS`"* now has **both** a stale coordinate and a **falsified premise** — yet its **conclusion survives intact**, because D1 adds `-o pipefail` and deliberately **not** `-e`. That bullet is **left byte-unchanged**; a row quietly reworded is indistinguishable from one that was never wrong.
- **Nothing was weakened to reach green, and the one count that did move is declared here rather than discovered later.** `--cov-fail-under=85` keeps its single enforcement site with a **zero-line diff**; `ENTRY_OWED_EXEMPT` is byte-unchanged at four members with its `== 4` intact; `RESIDUE_CEILING` is byte-unchanged (sum **171**, `TESTING.md` at **128 of 128** — the new prose registers every figure it states and adds no bare cardinal); the `# pragma: no cover` total under `src/` stays **46**; `src/`, `pyproject.toml` and `.github/gate-parity.toml` are untouched; **no test was deleted, skipped or xfailed**; and the gate-parity figures did not move at all (**10 jobs / 17 legs / 19 gating steps / 19 manifest checks**, re-derived by running the scan, not transcribed). The single exception is stated plainly: `test_pdf02_ac2_...`'s `local_refs` assertion moved **1 → 2**, because D7 gave `deploy-website.yml` the same local `uses: ./` reusable-workflow call `release.yml` already had. It passes D4's own discriminator — *the population demonstrably grew and the new member is declared in the same commit* — its safety half (`external_uses == sha_pinned`, **34 == 34**) is untouched, and a **third** local reference still reddens, which was driven and discarded. A bumped count is what gaming looks like from outside, so it is recorded rather than quietly done; reverting it is one line if the PM rules otherwise.

## [B-218] correction: `be89f36` landed owing a changelog entry and wrote none — 2026-09-04

- **This is the payment for `036fd0a353`, and it is a new entry rather than a back-fill.** `be89f36` (`[B-218] docs: install lines flip to PyPI now that pdf-tooling 0.1.1 is live`) matches `OWES_AN_ENTRY` and touched no `changelog.md`, so `tests/test_changelog_history.py`'s two entry-owed arms have named it as the sole offender since it landed. `be89f36`'s own entry is **not** retro-inserted at its position and no landed entry is edited — this file's third rule is that a correction is a new entry with a new date. What `be89f36` should have recorded is recorded here: the public install lines flipped from the `git+https` form to the PyPI form (`uv tool install pdf-tooling` primary, `pip install pdf-tooling` alternative) in `website/src/components/QuickStart.astro` and `README.md`, once PyPI served `pdf-tooling` 0.1.1 and the v0.1.1 release carried wheel, sdist and `THIRD_PARTY_LICENSES`.
- **The debt was NOT laundered into the register, and that refusal is the point rather than a side note.** `ENTRY_OWED_EXEMPT` (`tests/test_changelog_history.py:81-86`) is byte-unchanged at its four members. Registering `be89f36` would have been the cheap green and it costs an edit to a guard's frozen constant — `test_the_entry_owed_register_is_frozen_reachable_and_older_than_head` asserts `len(...) == 4` — which is the coverage-floor-gaming pattern wearing a different hat. The demonstration was run and discarded: adding `be89f36` fails that assertion at `:447` with *"the register was three at 2d19bcb and is four at 7afdb1a; growing it is the B-042 class recurring and is a FINDING for the PM, never an edit made to reach green."*
- **MEASURED, and it falsifies the premise this payment was specified under: paying the debt does NOT turn the two arms green, and nothing a forward-fix may do can.** Both arms test `CHANGELOG not in touched_files(be89f36)` — `git diff-tree` against an immutable landed commit. No new commit changes what `be89f36` touched, so the only greens available are amending history (forbidden: forward-fix only) or growing the register (forbidden: X-408). The arms therefore remain red at this commit, **correctly**, and they are red for exactly one reason, naming exactly one commit. That is the guard working, not the guard failing. Filed for the PM as the disposition question it actually is; recorded here rather than resolved by softening the arm that found it.

## [PDF-31] Name sync — repo, website and layer follow the `pdf-tooling` distribution — 2026-09-04

- **The repository followed the distribution, and this entry supersedes two clauses of `[B-218]` that the rename falsified.** `[B-218]` recorded *"Trusted Publishing (OIDC) is now configured on PyPI for project `pdf-tooling`, repo `ArmandoHerra/pdf-toolkit`, workflow `release.yml`"* and *"**The repo name, the import package, and both console scripts are unchanged.**"* Both were true when written and are false now: the repository is `ArmandoHerra/pdf-tooling`, and the trusted publisher was re-registered against it. **Neither clause is edited** — this file's third rule is that a correction is a new entry, so the correction is here. The other two names in that clause still hold: `import pdf_toolkit` and the `pdftoolkit`/`pdf-toolkit` console scripts did **not** move, and are now asserted not to have moved rather than merely left alone.
- **A blanket substitution would have been wrong most of the time, so the sweep was derived rather than typed.** An ordered, first-match-wins classifier over `git grep -Io "pdf-toolkit"` (**117** occurrences over **45** files) assigned every occurrence to exactly one role and reconciled `sum(classes) == total`; only the repo-URL and Pages-URL classes moved, plus the live layer-path pointers. The console-script alias, the corpus and golden byte strings, the rendered display name and the logo filename are asserted **unchanged**. The instrument matters as much as the rule: the same sweep as `/bin/grep -rIo` over this working tree returns **562** occurrences over **303** files, because it reads `.venv/`, `website/node_modules/` and `website/dist/` — a **4.8×** inflation of a population that is supposed to be the tracked tree.
- **`planning_dir()` is now derived instead of hardcoded, which removes a flag day and disarms a silent-skip hazard.** `tests/test_docs_antirot.py`'s fallback read `… / "ai_plans" / "pdf-toolkit"`; it now reads `… / "ai_plans" / REPO_ROOT.name`, correct on **both** sides of the directory rename. The hazard it removes is that `require_planning_dir()` **skips** rather than fails, so a renamed planning tree would have quietly silenced five arms — including the spec-header ↔ roster agreement guard — while the suite stayed green. A skipped arm is not agreement.
- **`README.md` gains a `## Naming` section, and three of its four rows are derived from source rather than transcribed.** The distribution comes from `[project] name`, the import package from the `src/` package directory, the repository from `[project.urls]`, and the console-script row is compared to `[project.scripts]` by **set equality in both directions** — so a third script added later reddens the table with zero author action, and a name in the table that is not declared fails too. The section carries no count of anything, so the unregistered-cardinal backstop stays green.
- **Version `0.2.0`, with `uv.lock` regenerated in this same commit.** Every CI job runs `uv sync --locked`; a bump without a lock sync has already failed every job on this product once. The lock diff is one line. **A known pre-existing red is NOT fixed here:** `be89f36` (`[B-218] docs: install lines flip to PyPI…`) owes a changelog entry and wrote none, so `tests/test_changelog_history.py`'s entry-owed arms are red locally at this commit and were red before it. Paying another item's debt by registering it as exempt would defeat the frozen-size register that makes such debt visible; it is filed, not laundered.

## [PDF-32] Website dependency currency — Dependabot PR #2 triaged NEEDS-REVIEW, in-range bumps swept — 2026-09-04

- **PR #2 (`typescript` 6.0.3 → 7.0.2) was NOT merged. Verdict: NEEDS-REVIEW, and a purpose-built gate is what said so.** This repository has no pre-merge instrument for the website toolchain (`git grep -Io "npm run check" | wc -l` → 0 callers; `grep -rno "npm " .github/workflows/ | wc -l` → 2, both in `deploy-website.yml`, which runs only *after* merge). One was built for this item and run twice on Node v22.23.2: the **`HEAD` baseline at 2026-09-04T07:21:36Z → `ci=0 build=0 check=0`** — the first time `astro check` has ever been observed green in this repository (16 files, 0 errors/warnings/hints) — and the **merge result at 2026-09-04T07:29:03Z → `ci=1`, ERESOLVE, with `build` and `check` therefore unreachable**. A green baseline against a red merge result is what attributes the failure to the bump rather than to the script.
- **The blocker is upstream and has no forward fix at this measurement.** `@astrojs/check@0.9.10` is `dist-tags.latest` and declares `peerDependencies.typescript: "^5.0.0 || ^6.0.0"`; 7.0.2 does not satisfy it and 6.0.3 does (both readings taken — an instrument that reports "not satisfied" for everything proves nothing). The ERESOLVE reproduces **identically on PR #2's own pristine, unmerged, Dependabot-generated lockfile**, so it is intrinsic to the update and not an artifact of a git-merged lockfile — which is why `@dependabot rebase` was not requested: it regenerates the same conflict. `--force` and `--legacy-peer-deps` were not used; accepting a knowingly-broken peer resolution to land a devDependency bump is not a currency improvement.
- **PR #2's 16 green checks carry zero signal about TypeScript 7.** `ci.yml` produced all 17 of the PR's checks and contains **0** `npm` tokens; every one of its jobs is Python. The single red check, `lint`, is `uv sync --locked` / `make fmt-check` / `make lint` and contains **0** node/npm/typescript tokens, so it cannot carry TypeScript signal either — and its log has expired, so no diagnosis is available from it. Neither the greens nor the red were evidence about this change.
- **The in-range half landed on its own, lockfile-only: `astro` 7.2.9 → 7.3.1 and `@astrojs/sitemap` 3.7.3 → 3.7.4.** Both satisfy their declared ranges (`^7.2.3`, `^3.7.3`), so `website/package.json` is byte-unchanged — a manifest diff here would have meant a widened range, which is a different and unspecified act. The triad re-ran green on the swept tree (`ci=0 build=0 check=0`, Node v22.23.2, 2026-09-04T07:36:35Z). `astro` 7.3.1 moves its `@astrojs/markdown-remark` peer from the exact pin `7.2.4` to the range `^7.3.0`, so the "safe minor" is not graph-neutral; two transitive packages moved with it and one was dropped.
- **Remaining majors, enumerated over all six declared packages rather than discharged by silence: 1 before this commit and 1 after** — `typescript 6.0.3 → 7.0.2`, still pending and still blocked upstream. The enumerator was shown able to print a row before it was trusted to print none. The set is **not** empty, because the merge did not happen; recording it as empty would have been exactly the false green the enumeration exists to prevent.

## [B-218] chore: rename distribution to pdf-tooling, version 0.1.1 — 2026-09-03

- **PyPI registered the project as `pdf-tooling`, not `pdf-toolkit`.** The operator found `pdf-toolkit` too close to existing PyPI packages; Trusted Publishing (OIDC) is now configured on PyPI for project `pdf-tooling`, repo `ArmandoHerra/pdf-toolkit`, workflow `release.yml`. `pyproject.toml`'s `[project] name`, `scripts/licenses.py`'s `SELF` (the `--ignore-packages` self-exclusion for the license inventory), `src/pdf_toolkit/__init__.py`'s `_DISTRIBUTION`, `src/pdf_toolkit/cli/cmd_version.py`'s `_TOOL_DISTRIBUTION`, and `src/pdf_toolkit/ports/__init__.py`'s `BROKEN_INSTALL_HINT` all move together — each is an independent `importlib.metadata` lookup or `--ignore-packages` match keyed on the literal distribution string, and each would have silently broken (unresolved own-version, or a leaked self-entry in `THIRD_PARTY_LICENSES`) had it been left naming the old distribution.
- **The repo name, the import package, and both console scripts are unchanged.** `apps/pdf-toolkit`/`ArmandoHerra/pdf-toolkit`, `import pdf_toolkit`, and the `pdftoolkit`/`pdf-toolkit` console scripts are three names independent of the PyPI distribution identifier, and none of the three changed — only the fourth name, the thing `pip`/`uv` resolve, did.
- **`v0.1.0` remains git-install-only.** It was never published to PyPI under either name (`release.yml`'s `publish` job has never fired — B-015). `v0.1.1` is the first tag this rename applies to and the first this repository will attempt to publish as `pdf-tooling`.

## [PDF-30] fix: two false claims inside the spec's own instruments — 2026-09-03

- **AC23 had no covering test, and the guard that should have caught that said otherwise.** `grep -rn 'no open findings' tests/` returned nothing — the README's conditional-degradation rendering (`README.md:162`, *"no open findings are recorded as of sweep `<id>` (`<sha>`)"*) was carried only in prose — an instruction a future maintainer must honour, which this spec's own closure rule forbids as a mechanism. Worse, `tests/test_docs_antirot.py:894`'s docstring claimed *"the heading is asserted in BOTH states"* while its body only ever read the real, populated README — a guard documenting coverage it did not have, this spec's own failure mode reproduced inside its own deliverable (precedent `0615feae63`: an AC with no covering test is a FINDING, not a gap to fill quietly).
- **Fixed by extracting the pure-text slicing and adding the second state.** `known_issues_body()`'s body-splitting logic moved into `_known_issues_body_of(text: str)`, a pure helper `known_issues_body()` now wraps around `read("README.md")`; the new `test_the_known_issues_section_survives_the_vacuous_rendering(tmp_path)` builds the vacuous rendering on a synthetic `tmp_path` document (the real `README.md` is never touched), runs it through the same slicing, asserts the heading and the no-open-findings sentence survive, and re-applies AC21's digit-grep discipline (`grep -o … | wc -l`, never `grep -c`, B-104) after stripping the sweep-id and short-sha tokens the sentence is allowed to carry. `:894`'s docstring now says what the body actually does and defers the both-states claim to the new test. No skip class added — the arm runs unconditionally on a synthetic document.
- **The RED was observed, not assumed.** A scratch variant of the new test's document deleted the `## Known issues` section entirely (the exact regression AC23 exists to catch, leaving only an unrelated License section) and reddened on the test's own first assertion: `AssertionError: the heading must survive the vacuous rendering`. Tree restored byte-for-byte afterward by direct text substitution back to the intended content (no stash, no working-tree checkout, per `7842b7b`'s pattern) — confirmed by `md5sum` matching the pre-RED copy.
- **A second, smaller false claim: the residue ceiling misattributed its own provenance.** `tests/test_docs_antirot.py:570` blamed the frozen `RESIDUE_CEILING` figures (30/7/6/128 = 171) on `7afdb1a`, but the register's own docstring at `:535-539` and the sibling assertion at `:576-585` both say 171 was measured at *this spec's landing* — `7afdb1a`'s figure was 159. `git log --oneline -S "RESIDUE_CEILING" -- tests/test_docs_antirot.py` and `git blame -L 554,559` both confirm the ceiling was introduced at `6deebb4`, so the attribution clause now names that commit. No ceiling value changed, no exemption list widened, and the correct `7afdb1a` references at `:536`, `:582`, and `tests/test_docstring_pointers.py:143` are untouched.


## [PDF-30] forward-fix: the history-depth meta-guard was shallow-blind and silently passed unmeasurable — 2026-09-03

- **Two defects in two lines, both in `test_the_history_depth_precondition_is_frozen_and_reachable`.** CI run `33808364031` on `6deebb4` reddened this single test across all 10 pytest legs. Defect A: `ci.yml`'s `test` job checks out at the default depth 1 (only `secret-scan` sets `fetch-depth: 0`), so `history_depth()` returns **1** there and `1 >= 72 or 1 == 0` is False — the arm reddened on CI's own deliberate posture, not a repository defect. Defect B, the sharper one: `history_depth()` returns `0` **only** when `git rev-list` itself exits non-zero, i.e. the precondition is *unmeasurable*, not *shallow* — so `or history_depth() == 0` made the assertion **PASS whenever the precondition could not be measured at all**, a second unfailable disjunct violating D3/AC13's own rule (X-153: a control that cannot be run must be visible as skipped, never silently passed).
- **Fixed with three honestly-labelled outcomes, no disjunction anywhere.** A new `is_shallow_repository()` helper probes `git rev-parse --is-shallow-repository`, and a failed probe falls through as "not shallow" rather than being reported as one. The arm now: shallow checkout -> `pytest.skip` naming `SKIP_SHALLOW_CLONE`; unmeasurable depth (`rev-list` exit non-zero) -> `pytest.skip` naming the measurement failure, never borrowing the word "shallow"; full, measurable clone -> `assert depth >= MINIMUM_HISTORY_DEPTH` with real teeth. `depth >= 72 or depth < 72` (true for every integer) appears nowhere, and `MINIMUM_HISTORY_DEPTH` stays **72**.
- **Both rejected fixes were excluded by the spec's own Scope > Out, not by preference.** `depth >= 72 or depth < 72` is forbidden — it is an unfailable tautology that would neuter the exact guard this test exists to be. Adding `fetch-depth: 0` to the `test` job is equally forbidden — PDF-30's own Scope > Out states `.github/workflows/ci.yml`, including its checkout depth, is owned by `PDF-28`/`PDF-29`; that file is byte-unchanged here.
- **Three reds observed, tree byte-restored after each (no stash, no working-tree checkout).** Red 1 (teeth): `MINIMUM_HISTORY_DEPTH` raised to `9999` in this full clone (real depth **73**) -> `AssertionError: ... is 73 ... below the frozen minimum of 9999`. Red 2 (shallow never passes): `git clone --depth 1 file://<repo>` -> the single arm `SKIP`s naming `shallow clone`, never a pass; the other history arms in `tests/test_docs_antirot.py` and `tests/test_changelog_history.py` were confirmed skipping in the same shallow posture rather than passing. Red 3 (unmeasurable, with the old-code contrast): `rev-list`'s invocation planted with an invalid flag (exit 129) while `rev-parse --is-shallow-repository` still answers `false` -> the NEW code `SKIP`s naming the measurement failure; the OLD two-line form, planted alongside the identical forced failure, **PASSED** — proving Defect B directly.
- **No new skip class added to `scripts/assert_skips.py`.** The unmeasurable branch is unreachable in CI (git is present and `rev-list` succeeds in every real checkout, shallow included), so a census class for it would be unfalsifiable; `assert_skips.py`'s `unclassified` remainder already preserves visibility for it.

## [PDF-30] Mechanized doc claims & README known-issues pointer — 2026-09-03

- **The closure rule, and the five free reds it was built against.** In a guarded document a cardinal claim about this repository is now **derived from source at test time**, **produced by a documented command `make docs-gate` re-runs and compares**, or **absent** — there is no fourth option. `tests/test_docs_antirot.py` was scoped at `PRIME_DOCS` to `README.md`/`CLAUDE.md`, so `TESTING.md` was unguarded *by construction*; three of its stale claims were spelled-out words (`seven`, `six of the seven`, `thirteen`) the guard's `SPEC_COUNT` regex could not have matched even had the file been in scope, so `cardinal(n)` renders 0–20 as words and the comparison is made in the rendering the document uses. All five registry entries were **observed red before anything was corrected**: `seven` against a derived **seventeen**, `six of the seven` against **sixteen of the seventeen**, `thirteen` against **eighteen**, `Empty at PDF-06 landing` against **three** goldens, and the four-empty-parametrize-sets parenthetical against **five non-empty populations**. `PRIME_DOCS` is untouched and the four pre-existing checks pass unchanged — the guarded-document list widened, the prime-document rule did not.
- **A sixth stale figure the run-and-compare arm found on its first run, which is the whole argument for having one.** `TESTING.md` carried B-099's instruction *"Re-run it; do not copy it"* beside the figure `8 passed, 18 skipped` and no carrier for it, so the figure drifted anyway: the documented command reports **`8 passed, 20 skipped`** at this commit, `tests/integration/test_ocr.py`'s half having moved 13 → 15 across the intervening waves with nothing able to observe it. `make docs-gate` now runs that command **verbatim** and fails naming the document, the quoted value and the measured value. The two competing coverage totals stop competing: `91.29%` and `93.79%` are re-written **commit-anchored** to `d777dd8` and `ebb1cd3`, because a total is true at one commit and at no other. `changelog.md`'s own `94.00%` is a landed entry and is untouched.
- **Four changelog guards that can fail, replacing one that could not.** `test_changelog_prepends_every_spec_entry_below_the_anchor`'s remediation clause was a **tautology** (B-080) — `original_date[n]` held the bottom-most date, which the non-increasing assertion three lines above already made the minimum, so `d < min(...)` was unsatisfiable. It is **deleted**, its entailment recorded in the docstring, and its intent moved to `tests/test_changelog_history.py` where it is measured against **git**. The population widens from a `PDF-NN`-only regex (**46 of 65** headings) to all 65, so the newest-first assertion now covers the 17 `[B-NNN]` and 2 `[Task: …]` entries it could not see. Heading sets are compared as exact byte strings **in Python, never through a shell pipeline** — three shell instruments got this comparison wrong on this very file and one got it wrong silently (B-088) — and the comparator is **self-tested against the known-lost needle** (present at `73f6722`, absent at `d458517`) before any green is trusted. Reds observed, all supplied by history: `33bf481` destroyed `PDF-13`'s entry; `81e31e9`, `85dd844`, `26f4c79` owe an entry and wrote none — **and so does a fourth, `b3c92f7`, which landed after this spec was drafted**, so the register is frozen at four rather than three and the growth is filed as B-042's class recurring. **No entry is back-filled** (`changelog.md:15-16`).
- **Three pointers that pointed at nothing, each mechanized rather than merely edited.** `safety/confirm.py`'s B-093 paragraph named `test_cli_spine.py`, which **exists** and holds **zero** `require_confirmation` references — the walk is `tests/test_import_boundaries.py` Section 4 — so an existence-only check would have passed it, and `tests/test_docstring_pointers.py` keeps that pre-fix pair as its named red with **both halves** recorded. `safety/atomic.py`'s *"the dry run's own exit status is 0 either way"* is **struck** (it contradicts OR-7, and the product's own `test_c15_*` pins `dry == real == 5`); it is guarded by **four paraphrase patterns**, each shown red on a distinct rewording, because B-106 survived B-101 for want of exactly that — an exact-phrase grep answers *is this STRING gone*, not *is this CLAIM gone*. `encrypt --allow print-highres` also granting `print` is disclosed in `README.md` and in the flag's own `--help`, and asserted **by running the tool**: `encrypt` writes it, `permissions -o json` reports it, so the claim is checked by a different consumer than the one that computes it.
- **A README that finally says where the defects are, and says it without a number.** A `Known issues` section points at `BACKLOG.md` and `qa/FINDINGS-LEDGER.md` **by path**, states plainly that both live in the maintainer's planning repository and are **not part of this distribution**, and anchors itself to a sweep id and a commit rather than a tally — its criterion is a digit-grep (`grep -o … | wc -l`, never `grep -c`, B-104) that must return nothing once the sweep id and short sha are removed. The named sweep must resolve to a directory **that carries a readable verdict artifact**, not merely to a directory: the newest sweep on disk has fourteen tracked files and none of the four whitelisted verdict names, so a reader following it would find probe scripts and no verdict. Recency is deliberately **not** asserted — a guard that demands the newest sweep goes red every time the sentinel runs. `README.md:3` stops omitting ten shipped verb families and a complete roster under *What exists today* is asserted by set-inclusion against `discover_verbs()`, so a verb shipped tomorrow reddens it with zero author action.


## [PDF-26] the §D3 belt's second and last carrier — `cli/cmd_create.py` — 2026-09-03

- **The entry below filed this seam rather than fixing it, and filing it was the right call only if it then got fixed.** That entry names `cli/cmd_create.py:163` as "one further unbelted seam", characterises it as *"one pattern rather than one file"*, and leaves it **deliberately unbelted** because it sits outside `ops/`. On that characterisation the ruling belts it: correcting one carrier of a proposition and knowingly leaving its twin moves the falsehood rather than removing it, and a correction that does not sweep every carrier gets re-discovered. Measured at `ef4cad2` before anything changed, at **AC16's own condition** — `os.access` patched to lie while the real `open()` still fails — `create` exited 1 with **zero bytes of stdout** and a **3452-byte** `PermissionError` traceback at `cmd_create.py:163, in _read_input`, on `return source.read_bytes()`.
- **`read_source_bytes` is the one-line belt for exactly this shape and still could not serve it — for the opposite reason the three `compose` seams could not.** Those three never reach `read_bytes` at all; this one *is* a bare `read_bytes`. What disqualifies it is the **noun**: `source_read_error`'s fallback says `could not read PDF`, which is accurate for all eight of its existing call sites because every one of them reads a PDF, and false at the two verbs that turn **non-PDF input into PDF**. `create`'s operand is a `.txt`. Answering a failing disk with `could not read PDF` at a text file would have swapped one wrong sentence for another rather than removed one, so `_input_read_error` mirrors `ops/compose.py::_image_read_error`: ask `safety/paths.py::unreadable_source_error` **first** — the same predicate `classify_operand`'s rung 4 uses, so belt and classifier cannot come to disagree at the one verb where both run — and fall back to the noun `cli/password.py::_read_file` already uses for its own read, the thing being **read**, never the thing being produced.
- **It deliberately has no `FileNotFoundError` rung, which is the one place it departs from `source_read_error`.** That rung answers **4**; this seam has only ever answered **1**. Refining an unhandled crash into a coded failure is the belt's whole job, and renumbering a race nobody asked about is not — so both arms here are exit 1. The class and the message are refined; the integer never is.
- **One arm, two drives, and the second is not padding.** AC16's condition patches `os.access` to lie, which is the only thing that reaches the seam — but it lies to the **belt's own predicate** too, so under it a `SourceUnreadableError` is unobservable *by construction* and the belt necessarily lands on its fallback; that drive proves the **crash is gone** (and asserts `could not read PDF` is absent, pinning the noun decision above). The **honest race** — the operand going unreadable between `classify_operand` and the read, the TOCTOU window `os.access` cannot close and the only reason §D3 exists — is the only condition under which the predicate answers truthfully, and it proves the **classification**: `exists but cannot be read`, the classifier's own sentence, exactly as the belted `merge` gives. Both drives assert `create` wrote nothing. *Red with this belt alone removed*: **1 failed, 50 passed** across the whole of `tests/test_info.py` — its own arm and only its own, `stdout=''` and the recorded `PermissionError` frame; the three `compose` arms and their control stayed green.
- **The sweep was re-run live rather than re-reasoned, and the count is now zero.** Every leaf verb was enumerated from `discover_verbs()` (no hard-coded name) and driven with an unreadable operand at the lying-`os.access` condition, reusing `C18`'s own `_substitute_unreadable_operand`: **26 leaf verbs enumerated, 24 driven** — `doctor` and `version` take no file operand — and `merge` was driven **explicitly** despite `takes_input_paths=False` (it types its operand `str` for the `path:range` form and so drops out of that predicate, yet it reads files and is the verb this spec started from). Before: **1** tracebacking seam, `create`. After: **0**. No third carrier appeared, so the pattern was two members and is now closed.

## [PDF-26] the §D3 belt reached `ops/compose.py` and stopped at one seam of three — 2026-09-03

- **The extension beyond `adapters/` was right and unfinished, and the arm that should have said so did not exist.** The entry below claims *"a `§D3` belt maps `OSError` at the engine read seams so a TOCTOU race still exits 1 with a payload rather than a traceback"*. Driven at **AC16's own condition** — `os.access` patched to lie while the real `open()` still fails — `compose` exited 1 with **zero bytes of stdout** and a `PermissionError` traceback at `ops/compose.py:442, in _read_head`, on `with path.open("rb") as handle:`. Eight other read seams driven the same way returned clean coded envelopes; `compose` was the ninth. **`:406` was belted via `read_source_bytes` and the other three reads in the same file were not** — which is worse than a file nobody looked at, because the file *was* identified and the belt was fitted to one seam in it.
- **Three seams, three different measured answers, and only two of them were crashes.** `:442` (`_read_head`) and `:518` (`_decode_for_reencode`'s `Image.open`) both produced tracebacks — the second only under the wider race, since a mode-000 operand never gets that far. `:391` (`inspect_image`'s `Image.open`) was **already traceback-covered**: its `except (UnidentifiedImageError, OSError, ValueError)` caught the `PermissionError` and returned a coded exit 1 — saying `could not read as an image: [Errno 13] Permission denied: <absolute path>`, a raw errno blaming the decoder for a file the process was never permitted to open. So the belt there buys **classification, not the absence of a crash**, and its arm asserts the message rather than the code or it would pass with the belt removed. Each of the three was measured before anything was added; none was assumed.
- **`read_source_bytes` could not serve any of them, which is why they were missed.** Two hand `Image.open` a *path* (Pillow does the opening) and one reads a header prefix rather than a whole file — none goes through `read_bytes`. `ops/compose.py::_image_read_error` is the belt they share: it asks `safety/paths.py::unreadable_source_error` **first** — the same predicate `classify_operand`'s rung 4 uses, so the belt and the classifier cannot come to disagree about what "unreadable" means — and falls back to this module's own noun for everything that is *genuinely* a decode failure. A truncated frame, an `UnidentifiedImageError` and a Pillow `ValueError` keep `could not read as an image` verbatim, because for those it is the accurate sentence. Like `source_read_error`, it refines the **class and the message and never the integer**: both arms are exit 1. `compose` now answers exactly as the already-belted `merge` does — the module's noun under a lying `os.access`, the classifier's `exists but cannot be read` under an honest one.
- **One arm per seam, and each was proved red by removing its own belt while the other two stayed green.** `:442` shadows the two below it, so three arms sharing one invocation would have measured one seam three times; the later two are reached by the honest race they are actually exposed to — the operand goes unreadable *between* two reads, which is the window `os.access` cannot close and the only reason §D3 exists. Observed, one mutation at a time: remove `:442`'s belt → **1 failed, 3 passed**, the header arm alone, `stdout=''` and the recorded `PermissionError` frame; remove `:391`'s → **1 failed, 3 passed**, the inspect arm alone, message reverting to `could not read as an image: [Errno 13] ...`; remove `:518`'s → **1 failed, 3 passed**, the decode arm alone. The decode arm uses a **PNG**, deliberately: a JPEG takes the passthrough path, `raster=None`, and that seam never runs at all — an arm built on the JPEG fixture the other two use would have been green with no belt anywhere in the function, so a fourth control pins the fixture's ineligibility against the product's own verdict. All three arms also assert `compose` wrote **nothing**, which for `:518` is a claim about a write already open inside the `AtomicWriter` context.
- **Filed, not fixed, and reported rather than decided: `cli/cmd_create.py:163`.** An AST sweep of every source-read seam under `src/` (not a re-walk of the nine the finding drove) found **exactly one** further unbelted seam, and it is the sibling verb: `_read_input`'s bare `source.read_bytes()` gives the same traceback under the same condition, at `cmd_create.py:163, in _read_input`. `compose` and `create` are the two verbs that turn non-PDF input into PDF and share one `ops/` module by design, so this is one pattern rather than one file — but it lives outside `ops/compose.py` and outside `ops/`, which this task's scope forbids reaching into without a ruling. **It is left unbelted deliberately.** Everything else the sweep enumerated came back covered and was left alone: `pikepdf`'s `is_linearized` degrades to `False` by documented design, `--password-file` maps `OSError` at `cli/password.py:147`, `pdfium` raises `PdfiumError` rather than `OSError` and is outside the belt by design, and `tesseract`/`soffice` output reads are product-generated temporaries, not operands.

## [PDF-26] Per-input failure classification for batch verbs — 2026-09-03

- **The finding this closes is not the one that was filed. `B-057` said `merge` already classified an unreadable operand correctly and that the target behaviour was "demonstrably reachable inside the product"; both halves are false, and `BACKLOG.md:113` and `FINDINGS-LEDGER.md:199` inherit the error.** Measured at `cdc02ee` before anything changed: `merge <unreadable.pdf> <good.pdf> -O out.pdf` exits 1 **by printing a raw `PermissionError` traceback** from `adapters/pypdf_structure.py:802`, which is `cli/main.py`'s unhandled-crash 1 — *"a signal, not a UX"* — and not the `FAILURE` classification. **No verb on this tree classified an existing-but-unreadable operand correctly, `merge` included.** The other 23 exited **2** with the framework's own `is not readable` refusal and the batch dead, and `info <unreadable.pdf> <good.pdf>` never parsed the readable second input, let alone inspected it.
- **The mechanism was never in `ops/` or `cli/cmd_info.py`: it was the framework's `Path` parameter type.** Typer defaults a `pathlib.Path` annotation to `readable=True`, so click's converter ran `os.access(R_OK)` during argv parsing — **before any verb callback and before any of this product's code executed**. The live census was **76** such declarations: 23 input operands, 26 × `-O/--output`, 26 × `--out-dir`, and `stamp --from`. It is now **0**, and the operand half is centralised behind one constructor (`cli/common.py::operand_argument`) so the decision is written once rather than twenty-four times.
- **A third mechanism was found on the OUTPUT side, and it is more severe than the item it rode in on: a safety refusal reported as a typo.** `-O/--output` carried the same veto, and readability of a *write target* is semantically irrelevant. Measured pair, identical invocation, only the target's mode differing: mode 644 → **5** (`TargetExistsError`, correct); mode 000 → **2**. Adding `-f` was still 2, so an existing unreadable output target was unreachable by any flag combination. Now: 5, 5, and **0 with `-f`** (on POSIX, replacing a file is a *directory* permission), with `--out-dir <dir, mode 000>` giving the spine's own answer, **1** (`DestinationUnwritableError`), instead of 2.
- **One classifier owns the precedence, and the order is the contract.** `safety/paths.py::classify_operand` — missing → 4, directory → 2, non-regular → 2, unreadable → **1** (`SourceUnreadableError`, a `FailureError` subclass; `cli/exit_codes.py` is byte-unchanged and `ALL_EXIT_CODES` still has 7 members) — replaces the same ladder hand-written in 31 places, every one of them missing the last rung. The readability rung must run *after* the existence rung or every verb's exit 4 becomes exit 1, silently: `os.access` answers `False` for a path that is not there. A `§D3` belt maps `OSError` at the engine read seams so a **TOCTOU** race (readable at classify time, unreadable at open time) still exits 1 with a payload rather than a traceback; both belted pypdf seams have their own arm, because removing the belt at one of them left the other's arm green.
- **Two live-tree guards make a verb nobody has written inherit the fix, and both were proved red by planting.** `readable=True` re-added to `compress` alone: the declaration guard fails naming `compress: sources (operand)`. `C18`'s population pointed at `TAKES_INPUT_PATHS`: the membership guard fails on **`merge`'s absence** — `merge`'s operand is a `StringParamType` (the `path:range` grammar needs the raw string), so the predicate `C5` uses excludes it, and a check modelled naively on `C5` would have been green while the one verb the roadmap named sat outside its parametrization. **Continuation is deliberately NOT uniform**: the 10 single-artifact verbs derived from their own OR-3 declarations (`merge` and `compose` among them) still abort and write nothing, because a partially merged document is a wrong document that looks right.

## [PDF-29] the anti-abstention guard named one mechanism and missed the one shipped beside it — 2026-09-03

- **A guard written to stop Section 6 abstaining could be bypassed by the abstention shipped ten lines away, and an independent QA sweep walked through it.** `tests/test_gate_budget.py::test_the_load_immune_companion_exists_and_cannot_abstain` asserted `"getloadavg" not in body`. The sweep planted the *other* mechanism — the same `PYTEST_XDIST_WORKER` skip `tests/test_cli_spine.py::test_help_stays_within_the_startup_budget` itself uses — into Section 6's three claim-bearing tests and got **`1 passed`** from the guard while Section 6 reported **`3 skipped` on every worker**. That is `B-106`'s lesson one step along, and `AC20` in the very same file already applies it to prose: an exact-phrase guard *answers "is this STRING gone", not "is this CLAIM gone"*. Naming `getloadavg` **and** `PYTEST_XDIST_WORKER` would have been the same defect a third step along.
- **Rewritten as an AST walk over a proposition, not a phrase: Section 6 may abstain on exactly one thing — the build under test is not there to measure.** `section_six_abstentions()` matches the SHAPE (`pytest.skip`/`xfail`/`importorskip`/`exit`, `@pytest.mark.skip|skipif|xfail`, `raise SkipTest`, and a conditional `return` inside a `test_*` body — abstention with no pytest API at all), over every function in Section 6's span plus every module-level function in that file it transitively calls. Sanctioned is decided by the guarding CONDITION (`VENV_CONSOLE_SCRIPT.exists()`), never by the function's name, so planting the xdist skip *inside* the fixture already permitted to skip still reddens. A second, separate proposition — `section_six_load_sensing()` — forbids sensing host load or worker identity in Section 6's code at all, because `modules = [] if os.getloadavg()[0] > 4 else census()` is not a skip, does not fail, and empties the census: an abstention that reports itself as a pass. `test_the_abstention_walk_is_not_vacuous` pins the dead-instrument case — the walk must FIND Section 6's two legitimate `VENV_CONSOLE_SCRIPT` skips, or a walk returning `[]` everywhere would pass the guard forever.
- **Four reds observed on the real file, planted and restored without `git stash`.** Clean tree: **54 passed**. `getloadavg` skip (the original case, must still redden): **7 failed / 47 passed**. `PYTEST_XDIST_WORKER` skip in all three tests (the bypass): **7 failed / 47 passed**, with Section 6 reproducing the sweep's exact `1 passed, 3 skipped`. The same as a `@pytest.mark.skipif` **decorator**, where an inline-call check would miss it: **7 failed / 47 passed**. The same planted **inside the sanctioned fixture**: **7 failed / 47 passed**. The guard names the offender and its condition. `tests/test_import_boundaries.py` was not modified — the guard reads that file, it does not own it.
- **`53b321dd03`'s disposition is corrected on the record: RE-SCOPED, not `fixed`.** The earlier entry reported the flake gone. It is gone **by abstention** — the wall-clock test skips on every xdist worker and `-n auto` is this project's default, so **it runs nowhere by default**, and *a gate that does not run is not a gate that passes*. Its replacement is measurably blind to the thing the row is about: a module-scope `time.sleep(0.5)` planted in `cli/common.py` (`time` is a builtin, so the import census does not move) took `--help` from **222.9 ms to 761–811 ms** — 3.5×, and 2.4× the new 325 ms budget — while all five Section 6 node IDs **and** this guard passed 6/6. The row's new scope is *no control that runs by default can see `--help` startup latency*; the latency blindness itself is filed **`57156e22c0` (high)** for the next cycle, because it falsifies a premise rather than an acceptance criterion and a latency gate that survives a self-saturating suite is a spec, not a fix-forward. **No product source changed and no measurement was re-run** — `git diff` on `src/` is empty.

## [PDF-25] `RETURN_SIGNALLED_CODES` claimed the product's set and held a subset — 2026-09-03

- **A docstring shipped in this spec's own commit asserted something false about the product, and an independent QA sweep caught it.** `tests/test_usage_envelope.py`'s `RETURN_SIGNALLED_CODES` was `(FAILURE, NO_INPUT, AUTH)` under the words *"the non-zero codes **this product** signals through `typer.Exit(...)`"*. It is not the product's set: `cli/cmd_doctor.py` ends `raise typer.Exit(ENGINE_MISSING)` whenever `--strict` finds a port unavailable, so **3 rides the return value too** and the §D3 hazard — a `main()` ending in `raise SystemExit(OK)` — silently zeroes it exactly as it zeroes 1, 4 and 6. The exclusion was disclosed rather than concealed (`REACHABLE_CODES` named it and pointed at `tests/test_doctor.py:222,236`, which does cover code 3 as a product behaviour), but a disclosed exclusion under a docstring that generalises to the whole product is still a false docstring — and it was checkable with this module's **own** plant, which never ran on an invocation that exits 3.
- **Fixed by widening the matrix, not by narrowing the claim alone.** `exit_matrix()` gains one row — `doctor --strict` with `PATH` scrubbed to an empty directory — so the matrix now reaches **every one of the seven codes `cli/exit_codes.py` defines** (21 cases, up from 20), and both tuples name 3. `ExitCase` gains a hashable `env_overlay` and a `cwd`, applied to **both** runs of a case (the real CLI and the plant), because `ENGINE_MISSING` is a property of the machine rather than of a command line and a row that inherited this host would read 0 where the binaries are installed and 3 where they are not. `cwd` points at the module workspace, not `REPO_ROOT`: `--strict` also `rglob`s the working directory for stray temp files, which costs ~0.85 s over this repo on each of the row's two runs and walks a tree other xdist workers are live in.
- **Three reds observed, not asserted.** (1) Re-plant the shipped tuple with the row present: `test_ac5_the_planted_defect_zeroes_exactly_the_return_signalled_codes` fails — *"the planted defect zeroed codes [1, 3, 4, 6]; this module declares [1, 4, 6]"*, naming `doctor --strict (PATH scrubbed)` as the case. (2) Delete the row with the tuples corrected: the coverage arm fails — *"the matrix covers [0, 1, 2, 4, 5, 6], but claims [0, 1, 2, 3, 4, 5, 6]"*. (3) Drop the `PATH` scrub: the row reads **0** on this host, where tesseract and soffice both resolve — so it is the scrub that produces the 3, not the host, which is the whole hermeticity argument. Measured directly: `PATH=<empty> pdftoolkit doctor --strict` is **3** through the real `main()` and **0** through the plant.
- **The docstrings now claim only what was measured, and they no longer disagree about who owns code 3.** `RETURN_SIGNALLED_CODES` is scoped to *this matrix's invocations* rather than to the product, because no matrix can establish the product's set: `typer.Exit(result.exit_code)` appears in 26 verb modules and `OperationResult.exit_code` is a field, so USAGE or REFUSED reaching the return path on an invocation not made here is possible and unmeasured. `REACHABLE_CODES` states the split once — `tests/test_doctor.py` owns 3 as a **product behaviour** (six rows, hints, `--strict` 3 vs plain 0), this module owns 3 on exactly one axis, the **terminal seam**.
- **Three `why` strings the same red control proved false, corrected in passing.** `text <malformed>`, `text <missing>` and `meta get <encrypted>` each read *"a SECOND/THIRD verb on the returned-code path"*; the plant reports all three among the cases that **kept** their code, so they reach 1, 4 and 6 by **raising**. Only `info` returns them, being the batch verb that ends `typer.Exit(run_exit_code(outcomes))`. The rows stay — a second verb reaching the same code is what stops the raised/returned split being read off one verb — but they now say which path they take. **No product source changed**; `git diff` on `src/` is empty and the earlier entry's `{1, 4, 6}` figure stands as written, corrected here rather than edited there.

## [PDF-29] `-n auto` broke a 3.14-only AF_UNIX path budget — 2026-09-03

- **The lever's first pushed CI run went red on exactly one leg of seventeen, and the cause is arithmetic.** `sockaddr_un.sun_path` is 108 bytes, so a Unix socket path may be 107 characters; CPython's `multiprocessing` forkserver binds `<TMPDIR>/pymp-XXXXXXXX/listener-XXXXXXXX`, exactly 32 past `$TMPDIR`. Under `-n auto` pytest inserts a `popen-gwN` component into every temporary path, and `tests/fs_snapshot.py`'s redirected `$TMPDIR` became `/tmp/pytest-of-runner/pytest-0/popen-gw1/test_ac12_the_five_preconditio2/tmp` — **76 characters, 108 with the suffix, one over the limit**. `test (3.14, ubuntu-latest)` failed with `OSError: AF_UNIX path too long` in run 33738793820; 3.11–3.13 default `multiprocessing` to `fork` (no socket at all) and macOS to `spawn`, which is why exactly one leg saw it.
- **Fixed where the artificially long path comes from, not by widening anything.** `redirected_environment()` keeps `base/"tmp"` when it fits under 75 characters and otherwise uses a short, per-test-unique sibling inside the same pytest numbered root — so the directory is still unique, still returned as a snapshot root, and still removed on exactly the same schedule. Measured: 85–87 characters with the socket suffix, against the 107 limit, for worker counts and run numbers into the double digits.
- **Filed, not fixed: the product has the same edge.** `pdftoolkit rasterize` builds a forkserver pool, so a user whose real `$TMPDIR` is long enough gets this same `OSError` from the CLI rather than from a test. That is a `src/` robustness question and is reported rather than changed here.

## [PDF-29] make ci budget & startup-gate baseline — 2026-09-03

- **The 250 ms `--help` budget was refuted by its own first honest measurement, not defended by it.** Twenty independent fastest-of-5 trials on a host verified quiet (loadavg 1.15 of an 8-cpu box, zero foreign processes) gave min 219.7 / median 235.8 / **p95 247.9** / max 248.0 ms — **2.1 ms of headroom against a 28.3 ms spread**. A best-of-5 estimator whose dispersion is thirteen times its headroom flakes by construction, on a quiet host as much as a loaded one, which is exactly what it did to three agents in one day and to `test (3.12, macos-14)` in run 33721445070. `STARTUP_BUDGET_MS` is re-baselined to **325.0** by the stated rule (p95 x 1.25, rounded up to the next 25 ms), with the full distribution and its **statistic** recorded in a comment block beside the constant — because a *median under contention* and a *fastest-of-5 at low load* are different statistics and quoting either as "headroom" is how this row's ledger came to hold two irreconcilable figures.
- **A measurement protocol now exists as a script, because a protocol that is not executable is not a protocol.** `scripts/measure_gate.py` records interpreter (resolved through `uv run`, never the system Python — 3.12.13 vs 3.14.4 on this host), the resolved binary AND which fallback arm produced it, cache state, engine presence, test count, coverage, cpu count, loadavg throughout, and a live census of foreign processes; `--baseline` **refuses on a host it cannot verify quiet** rather than recording a number nobody can use. Trend and rules in `perf/gate-timings.jsonl` + `perf/README.md`. Every one of the six historical `make ci` figures was self-measured under unrecorded conditions, which is why none of them could justify a decision.
- **`-n auto` in the shared option layer, and every job in `ci.yml` bounded.** One config key, read by every invocation, running the same tests locally and in CI — not the `@pytest.mark.slow` split-gate, which is refused on the record. All ten jobs now carry `timeout-minutes` derived from p95 over 15 green runs and commented with that derivation; a `main`-push run is never cancelled, so before this it had no bound at all but GitHub's 360-minute default.
- **Three defects the lever exposed, all the same defect: an unstated wall-clock assumption used as a correctness mechanism.** `tests/registry.py`'s pty helper slept a flat 0.5 s before writing a password, but `getpass` sets `TCSAFLUSH`, which DISCARDS pending input — under eight workers the write landed first, was flushed, and the child waited forever (reproduced at loadavg 14; widening 30 s to 240 s reproduced the identical hang at 240 s). Replaced by waiting for the pty's ECHO bit to clear, which is the exact happens-before the write needs at any load. The hang bound itself now scales with the worker count and says in terms that it is a hang bound and not a latency assertion.
- **A load-immune control now holds the startup claim in CI, and the old one says plainly that it does not.** Section 6 of `tests/test_import_boundaries.py` pins what `pdftoolkit --help` imports (a runtime `-X importtime` census, minus a bare-interpreter baseline so coverage's own instrumentation cancels instead of being scrubbed). It records what is there today rather than flattering it: **280 modules to print a help screen**, with `PIL` eagerly imported by `pdf_toolkit.cli.common` and `email` by `pdf_toolkit.ops.textract` — reported as findings, not fixed here. `TESTING.md`'s `~77s`/`~80s` claims, wrong by roughly 6x since `X-109` corrected them on the record, are replaced by a pointer to the protocol and guarded by a proposition-shaped check that reddens on differently worded claims.

## [PDF-25] AC16's README control could not fail — 2026-09-03

- **A control shipped in this spec's own first commit was found unable to fail, by observing its named red rather than asserting it, and is repaired here.** `tests/test_usage_envelope.py`'s AC16 arm parsed `README.md`'s password-paths table **positionally** (`rows[0]`, `rows[1]`, `rows[2]`) and anchored on the section rather than on the claim sentence it exists to hold the OR-4 message against. Deleting the table's header row left the data rows parsing fine and the control reported **8 passed** — a green that had asserted nothing.
- **The positional form hid a live bug of its own:** a naive all-caps pattern matched the `PATH` metavar inside `` `--password-file PATH` `` before it ever reached `PDF_TOOLKIT_PASSWORD`, so the token the rendered message was checked against was the wrong string and the check passed anyway.
- **Rewritten to match by KIND** inside the block following the claim sentence — a `--*-file` flag, a SCREAMING_SNAKE environment name (the underscore requirement is what excludes `PATH`), and the stdin dash. A reordered table can no longer point the assertions at the wrong cells, and the parse now fails loudly on all three mutations: the whole table deleted, the claim sentence deleted, and the file row's flag spelling removed — **8 failed on each**, against 8 passed before. No product source changed.

## [PDF-25] Structured envelope for every usage error — 2026-09-02

- **`cli/main.py::main()` becomes the terminal seam, and five ledger rows turn out to be three mechanisms.** `4772bfd8fc`, `76ece64648`, `7fc5a169f6`, `d220b7d79d` and `a472acde7a` were all cases where something *other than* the single `except PdfToolkitError` handler terminated the process — Click's own parser under `standalone_mode=True`, the root callback's help-and-exit-0, and a third-party logger reaching root's `lastResort`. `app()` now runs with `standalone_mode=False` and `main()` classifies what comes back: `PdfToolkitError` first (precedence unchanged, byte-identical), a Click parser error second (duck-typed on `ClickException` in the MRO — **no `click` import, no private framework import, no dependency change**), `Abort` third, everything else re-raised so a genuine bug keeps its traceback and exit 1. Unknown flag, missing argument, `does not take a value` and bad option usage now emit the structured envelope at every verb, every group and root, in every shape.
- **⚠ The hazard that came with the seam, and the control that pins it.** Twenty-eight `cli/cmd_*.py` modules signal their exit code with `raise typer.Exit(code)`, which `standalone_mode=False` converts into the **return value** of `app(...)` — so a `main()` ending in `raise SystemExit(OK)` would have zeroed every one of them silently. The return value **is** the exit code, and `tests/test_usage_envelope.py`'s exit-code matrix (20 invocations across all six reachable codes) plus an automated planted-defect control assert it. The planted defect zeroes exactly `{1, 4, 6}` — measured, not assumed: this product *raises* USAGE and REFUSED and *returns* the rest, so the matrix declares that partition and goes red if a later refactor moves an exit across it.
- **Output shape recovered from raw `argv`, behind five fences (`cli/common.py::format_from_argv`).** Consulted only when the flags were never resolved, it never influences an exit code, returns `None` for anything it does not recognise, never echoes the token it read, and honours `--`. Because it reads `argv` rather than the parse tree it behaves identically at root, group and leaf — which is what closes the group position **without** attaching `@global_options` to `meta`: `consumed_output_flags("pdf_toolkit.cli.cmd_meta")` is still `()`, `cmd_meta.py` still contains no `global_options`, and `pdftoolkit meta -o json` still exits **2**, now naming the two positions that work. Fixed alongside: `_apply` pins the error format only for an *explicitly given* `-o`, because pinning the auto-detected fallback at root made a verb-level `-o table` render in the auto shape whenever Click refused the line.
- **`--quiet` now suppresses engine chatter, and third-party records finally pass through `RedactingFilter`** (`output/logging.py`). `configure_logging` configured only the `pdf_toolkit` logger, leaving **root with zero handlers**, so `pypdf._reader`'s `"EOF marker not found"` was emitted by `logging.lastResort` — a handler this process never installed and therefore never levelled. It now owns root too (same formatter, same filter, same level), removing only handlers it marked itself so a host process's own handlers are untouched. Measured on the recorded operand `testdata/malformed.pdf`, unsubstituted: `rasterize --quiet` stderr 21 → 0 bytes, `info --quiet` 162 → 141, and at default verbosity the record renders as `WARNING: EOF marker not found` instead of bare.
- **`pdftoolkit -o json` with no command is exit 2 with an envelope naming `--help`; `pdftoolkit` alone still prints help and exits 0** — the rule is *invocation completeness*, never output shape, so no exit code turns on `-o`. `README.md` gains the group-position rule, the two new exit-2 classes in the exit-code table, and the correction that the three refused password spellings are refused in the joined form (`--password=hunter2`) as well as the separated one — a claim that was live and **false**, since the equals form named none of the three supported paths. New suite `tests/test_usage_envelope.py` (229 cases, every population derived from `discover_verbs()` / `discover_groups()` / `GLOBAL_OPTIONS` / `GLOBAL_PARAMS` / `OutputFormat`), plus one appended contract row `C17`.

## [PDF-24] PDF-01 CLI-spine re-verification — 2026-09-02

- **Turns the global-flag block from *governed by a hand-picked subset* into *governed by an exhaustive partition*.** `cli/common.py` now declares `OUTPUT_FLAGS` (4, unchanged) / `SAFETY_FLAGS` (2, new) / `UNGOVERNED_FLAGS` (9, a flag-to-reason **mapping**, so each reason is data rather than a comment), and `tests/test_cli_spine.py` asserts the three are pairwise disjoint, that their union is exactly `set(GLOBAL_OPTIONS)`, and that every ungoverned member carries a non-empty reason. A sixteenth flag added to the block without a class is now a red test. The prose classification at `cli/common.py:71-77` — which named eleven flags in English and could not fail — is gone; `grep -n 'ungoverned by design' src/pdf_toolkit/cli/common.py` returns nothing.
- **Closes the second, independent way a flag could exist unchecked: the roster axis.** Nothing asserted that `GLOBAL_OPTIONS` (15 strings, which every control iterates) and `GLOBAL_PARAMS` (18 `_ParamSpec`s, which Typer actually renders and binds) agreed, and every existing assertion was a presence check. A sixteenth `_ParamSpec` would have rendered in all 26 helps, bound at runtime, and been invisible to every test in the repository — the contract harness's C2 included. `test_global_options_equals_the_derived_roster` derives the block from `GLOBAL_PARAMS` minus the OR-4 hidden three and asserts order-sensitive equality.
- **Fixes B-115 / `996f9eb6bc`: `-f/--force` and `-y/--yes` were advertised, accepted and silently ignored at exit 0 on all five verbs that write nothing.** They now exit **2** with the structured envelope on stdout, on every verb the live registry reports with `consumes == ()` — one central rule, zero new per-verb declarations, derived from a fact the product already published in user-visible text. Measured behaviour change, pinned deliberately: `permissions <missing.pdf> --force` moves **4 → 2**, matching what `permissions <missing.pdf> -O x` already returned. `--dry-run` and the real run are asserted as **pairs** (exit code and envelope shape), with a discriminating `merge ... --force` → `0 == 0` row so a uniform `2 == 2` cannot be mistaken for a preview that has gone silent.
- **Fixes B-116 / `0d10c01634`: all five non-mutating verbs now disclose the refusal in `--help`,** and the pinned claim is **derived** — the test computes each verb's refused set as `(OUTPUT_FLAGS ∪ SAFETY_FLAGS) − consumes` and asserts the sentence names exactly it, six names / nine spellings. `permissions` and `meta get`, which already disclosed four, were updated too. `--no-backup` is deliberately not named: it is refused universally, for a reason that is not verb-specific. Fixes **B-050** (`test_info_is_the_only_verb_that_takes_input_paths` asserted a falsehood — renamed and widened to a pinned expected set over all 26 verbs) and **B-026** (the textual HC-1 tier carried 12 hand-typed names against the AST tier's 23, missing `poppler` and `gs`; it now **imports** the one list, gains a per-`(file, name)` exemption mechanism proven unable to silence a whole name, and matches `gs` with a word boundary for a reason recorded beside the list).
- **`tests/acceptance/audit_pdf_01.py`** — `PDF-01`'s 25 criteria independently re-derived, each with its D7 disposition, its covering test by node id and the mutation that made that test go red. **The re-grant is refused and the split is stated: 19 `ADVANCES` · 0 `MADE-TRUE-HERE` · 3 `SUPERSEDED` (AC8, AC17, AC18) · 3 `FINDING` (AC20, AC23, AC25) = 25.** Two shipped controls were found unable to fail for the reason they claimed (AC7 asserted the *label* `"Python"`, which lives in the format string — strengthened here; AC10's single-object `schema_version` is supplied twice and the renderer's copy is overridden by the payload — filed, not repaired). The bidirectional Scope > In map found **three** unclaimed artefacts where the spec predicted one.
## [PDF-23] Page-scoped overlays & merge_page migration — 2026-09-02

- **Fixes `4adc417234` / B-097: a `--pages`-scoped `watermark`/`stamp`/`ocr` on a document whose pages share one `/Contents` object mutated every page sharing it, while the completion message and `detail.pages_composited` reported only the selection.** `StructureEngine.composite_layer` (`ports/structure.py`) now operates on an already-appended **writer**'s pages (never the reader's) and, before merging, copy-on-writes a selected page's `/Contents` when it is shared with another page (`adapters/pypdf_structure.py`) — a fresh stream object registered on the writer, pointed at before the merge, so a sibling page's object is never touched. `CompositeOutcome` gains `pages_copied`, and `watermark`/`stamp`/`ocr`'s own JSON `detail` now carries it alongside `pages_composited`/`pages_ocrd`.
- **Migrates all three `merge_page` consumers off the reader-attached call pypdf 6.16.2 deprecates and 7.0.0 removes (`438bd13038` / B-092), in the same commit as the scoping fix** — landing the migration alone would have removed the only signal the over-reach emitted. `ops/overlay.py::watermark_run`/`stamp_run` and `ops/ocr.py::ocr_run` now create the writer and append the full page range **before** compositing, the reverse of their prior ordering. Full-suite `pypdf` `DeprecationWarning` census: pre-fix 27 (16 from `watermark`/`stamp`'s own tests, 11 from `ocr`'s); post-fix 12, **all** attributable to a residual, out-of-scope source (`adapters/tesseract_ocr.py::_normalize_layer_geometry`'s own `page.add_transformation` call, measured to be reader-attached — not the writer-attached shape this spec's own Design §D6 claimed; reported, not fixed, per `PDF-15`'s ownership).
- **The `pypdf<7` ceiling stays** (`pyproject.toml`): §D8's probe run at implementation time found no `7.x` release (latest published `6.16.2`, the pinned floor) — Arm A. A dated comment names this spec; `uv.lock` and both licence artifacts were regenerated and diffed clean (no change — the version constraint itself did not move).
- **New fixture `shared_contents_pages`** (`tests/corpus.py`) — three pages sharing one `/Contents` object, with its own fixture-integrity test (`tests/test_corpus.py`) proving the sharing property can itself fail loudly. New shared test helper `changed_pages()` derives the changed-page set from the produced file's decoded content (reusing `tests/pagetree.py`'s own coalescing helper), never from `OperationResult`.
- **`tests/acceptance/audit_pdf_23.py`** — the roster's first SELF-audit (evidence for criteria landed by this same commit, not a re-derivation): 23 rows, `AC1`..`AC23`, every red observed and recorded (18 `PLANTED_DEFECT`, 3 `NOT_OBSERVED` for the three procedural/gate-hygiene ACs, 2 `MUTATED_CONFIG` for the licence/ceiling duty). Two corrections to this spec's own text are recorded there and in the Implementation Log: AC17's literal "exits 0" contradicts the actual, correct `dry.returncode == real.returncode == 5` contract; Design §D6's claim that `_normalize_layer_geometry` "carries no deprecation" is measured wrong.

## [PDF-22] Code-derived secret-leak regression matrix — 2026-09-02

- **Replaces B-068's hand-typed `_B068_FLAG_VERBS`/`_B068_SHAPES` guard (30 cases over 4 of 26 verbs) with a matrix derived from the code that defines its own dimensions.** Verbs from `discover_verbs()`, the `(flag, verb)` population from a rendered-`--help` probe (`tests/registry.py::derive_password_file_pairs`, D2), and the shape dimension from `OutputFormat` **plus** the absent-`-o` state **plus** three real `isatty()` axes (stdout/stderr/stdin), each driven by a **real pty** — a capability that did not exist anywhere in this suite before this spec (both pre-existing pty tests attach the pty to `stdin` only).
- **Four tiers**: Tier A (subprocess, 28 cases, every derived pair × one shape), Tier B (subprocess, 8 cases incl. 3 real ptys, one pair × every derived shape state, including the historical **sixth shape** — no `-o`, stdout a real terminal, table rendered to stderr — pinned by name in `test_ac4_the_sixth_shape_is_pinned_by_name`), Tier C (in-process, 5,376 states, < 0.05s, cross-checked against a real subprocess per AC6), and a mechanized witness over ledger `5ff60a280e`. `PDF22_SUBPROCESS_CASE_CAP = 96` is asserted, not just stated; measured subprocess surface (Tier A + Tier B + the witness's 26-verb population) is 61 cases / ~19.4s, under the cap and under the `<= 30s` budget (measured interleaved with this run, loadavg 1.2-2.7, sole dispatched process).
- **Witnesses (does not fix) ledger `5ff60a280e`**: `--password-file` is declared by 26/26 verbs, honoured by **2** (`decrypt`, `permissions` — one fewer than the ledger's inherited figure; `encrypt` measured to refuse an already-encrypted operand via a REFUSED, non-AUTH mechanism regardless of the flag, so it is classified `OTHER`, not `HONOURED` — reported to the project-manager), silently ignored on 18 (verbatim match to the ledger's list), with 6 verbs (`compose`/`convert`/`create`/`doctor`/`encrypt`/`version`) in a named, counted residual the ledger's own arithmetic never accounted for. `HONOURED_FLOOR`/`IGNORED_DEFECT_BASELINE` are DEFECT baselines, not contracts — a verb leaving the honoured floor reds as a regression, a verb newly honoured while still on the ignored baseline fails with a directed message naming the baseline as stale. `5ff60a280e` stays `open`/`high` with its `Spec` cell empty (X-243).
- **Two mechanized sweeps** (`tests/test_secret_leak_sweeps.py`, D6): Sweep 1 (B-073) — assertions pinning a caller-supplied operand present in output, exempting `tests/unit/test_safety_paths.py`'s documented `..._echoes_the_path_as_written` contract by naming convention; measured baseline **65** (broader than the `2d19bcb`-era estimate of 17 — this sweep's heuristic is more permissive and its own baseline is self-measured, not inherited). Sweep 2 (B-074) — attributes documented as behaviour-changing that nothing reads, over both `src/` and `tests/`, token-level (not substring) matching, `Enum` classes / dunders / `__all__` / `to_dict()`-only loads exempted, an `intentionally unread` suppression marker honoured. Finds F1 (`ops/merge.py:53` `BOOKMARK_MODES`), F2 (`ops/metadata.py:79` `SETTABLE_FIELDS`), F3 (`ops/metadata.py:85` `CLEARABLE_FIELDS`) — all three **filed, not fixed** (AC13).
- **AC11 filed, not fixed**: `tests/unit/test_password_resolution.py:308` pins the `--password-file` argument present in a DEBUG log record — B-073's shape surviving in a different sink (the log, not the envelope); a live security-policy question for the project-manager, unchanged here.
- **Seven per-dimension red controls (R1-R7), each observed red in an isolated scratch worktree and reverted, never landed**: R1 (verb-local bypass in `cmd_encrypt.py`'s owner-password handling) caught only by that verb's Tier-A case; R3 (`emit_error()` reading the raw exception instead of the already-redacted payload for the TABLE branch) caught only by a dedicated `test_r3_...` red control — `render_error_table` alone cannot observe this class, since no live call site in this product currently pairs `path=` with `redacted=True`; R4 (the historical defect itself, `73f6722` vs `33bf481`) reproduced and cleared via the new pty capability; R6 (the interactive `getpass` prompt path echoing a wrong password) caught only by the Tier-B stdin-pty arm; R7 (a sentinel leaking only in its `\uXXXX`-escaped JSON form) exposed a genuine blind spot in Tier C's first draft (a raw-substring-only check missed the unicode-sentinel JSON/NDJSON states specifically, while the ASCII-sentinel and every TABLE-shaped state stayed detectable, since ASCII is byte-identical either way) — fixed by adding an explicit escaped-form check before landing, mirroring the pre-existing `test_ac5_the_password_is_absent_from_the_json_payload`'s own pattern.
- Nothing under `src/pdf_toolkit/` is modified (AC14).

## [PDF-21] fix: PR_SET_PDEATHSIG does not protect a forkserver worker — 2026-09-02

- **This entry corrects the previous one. The exclusion it added was WRONG and it made the SIGKILL arm unable to fail, and CI caught that one assertion later.** Under the `forkserver` start method a render worker is forked FROM the forkserver and **inherits its command line verbatim**, so excluding survivors whose argv names `multiprocessing.forkserver` excluded the very processes the arm exists to catch. The `test (3.14, ubuntu-latest)` leg then failed on the arm's OTHER assertion — `new output appeared after the parent was SIGKILLed`, `assert 24 == 16` — which is precisely why this arm asserts **both** zero survivors and zero new output. The exclusion is fully reverted; the survivor assertion has no allowlist again, and the reasoning is recorded in the helper's docstring rather than deleted.
- **The real finding, on a supported platform: `PR_SET_PDEATHSIG` does not cover `forkserver` workers, and Python 3.14 makes `forkserver` the Linux default.** The kernel delivers the death signal when the worker's OWN parent dies; under `forkserver` that parent is the forkserver helper, not the CLI process. **Measured on CI: a SIGKILLed `pdftoolkit rasterize` left its workers running and still writing pages, 16 → 24 files after the parent was reaped.** This is `cb948ad85b`'s defect returning through a start-method change, and it is **wider than the macOS gap X-153 ruled on**.
- **Filed, not fixed.** `PDF-21` is a verification spec and `src/pdf_toolkit/ops/procpool.py` is Scope > Out; pinning a start method or arming the guard inside the forkserver is a behaviour change to a shipped verb and belongs to its own spec. The arm is marked `xfail(strict=True)` when the resolved start method is `forkserver`, following `tests/test_import_boundaries.py`'s own *"Filed, not fixed"* precedent — **strict**, so the day the mechanism is repaired the marker fails and has to be removed.
- **`rasterize --help` is corrected to match what was measured**, since the previous wording claimed the workers *are* reaped on Linux: the guarantee is now stated for the `fork` and `spawn` start methods, explicitly **not** for the `forkserver` default of Python 3.14, and the help names `SIGTERM` as the signal that does work everywhere.

## [PDF-21] fix: the SIGKILL arm counted multiprocessing's own helpers as orphans — 2026-09-02

- **CI's `test (3.14, ubuntu-latest)` leg red on the new SIGKILL teardown arm, and the arm was over-broad rather than the product being wrong.** Python 3.14 changes the default `multiprocessing` start method on Linux to **`forkserver`**, and `ops/procpool.py` arms `PR_SET_PDEATHSIG` in the WORKER initializer — which a forkserver or resource-tracker helper never runs. Measured on that leg: a SIGKILLed parent left **1 `resource_tracker` + 9 `forkserver` helpers** alive in its process group and **zero render workers**. Those helpers import no pdfium and no Pillow, hold no page buffer and write no page; a SIGKILLed process runs no code, so it cannot shut its own helper down — the same class `PLAN §12 R-07` already accepts for temp-file residue. **Filed, not silently tolerated.**
- **The exclusion is BY NAME, and the narrowing was proven not to have disarmed the control.** `_is_multiprocessing_helper` matches only `multiprocessing.forkserver` / `multiprocessing.resource_tracker` in a survivor's command line — not the verb name, since a forkserver helper's argv *also* contains `rasterize`. Any survivor that is not one of those two still reds the arm and is named in the message. Re-run against the pre-`B-055` tree at `c870e73` **after** the narrowing: still **RED**, with **8 real render workers** enumerated by pid and **zero** helpers excluded. `test_the_multiprocessing_helper_classifier_can_tell_a_worker_from_a_helper` pins the classifier against the verbatim command lines CI produced, so it cannot drift into matching everything.
- The SIGHUP arm is unchanged and keeps the stricter assertion: `_assert_clean_signal_death` still requires the whole process group to be empty, helpers included, because a catchable signal reaches the parent's teardown routine and it shuts the pool down properly.

## [PDF-21] `PDF-09` rasterize re-grant — 2026-09-02

- **All 27 of `PDF-09`'s remaining acceptance criteria are re-derived, each against a control observed RED** (`tests/acceptance/audit_pdf_09.py`, `AUDIT-CONVENTION(PDF-17)`, 89 covering node ids all resolving in a live collection; the aggregator needed **zero** edits). Four-bucket classification (X-242): **19 `ADVANCES` · 1 `MADE-TRUE-HERE` · 6 `SUPERSEDED` · 1 `FINDING` = 27**, plus `AC8` as a 28th **regression-only** row — already re-verified at `971d0e5`, re-run green here (10 passed) and explicitly **not** re-derived. 34 mutation arms ran in a scratch `git worktree` under `$TMPDIR` with `PYTHONPATH` pinned to its own `src/`, each proven present before its arm and restored from an immutable gold tree — **34 restorations, 0 sha256 mismatches**. `git stash` was never used. **The re-grant is REFUSED**: `PDF-09` `AC18` was factually *unmet* at `b20a651` and is true only because of this spec's own `_HELP` edit, which is X-215(ii) in terms.
- **A second inverted control, in the same file as `AC8`'s, was measured before being repaired.** `test_ac9_grayscale_webp_is_perceptually_grayscale_but_reads_back_rgb` rendered a black-text-on-white fixture, so `R == G == B` held *before any grayscale conversion*: measured at `b20a651`, `grayscale=True → mode=RGB max_delta=1` and `grayscale=False → mode=RGB max_delta=1` — **both shipped assertions passed identically with the feature switched off**. Rebuilt on a six-band saturated-colour fixture (`True → 0`, `False → 255`) with a negative arm that reds without the flag. Two further controls that could not fail are repaired the same way: `AC5`'s PID test referenced **no `pdf_toolkit` symbol at all** (it tested that CPython forks) and is replaced by an instrumented-adapter-counter control asserting the planning handle is closed before the executor is created; `AC26`'s `.save(` denylist regex **passed both `image.save(str(target), …)` and `image.save(Path(target), …)`** and is replaced by an AST allowlist, with both bypasses and `writer.path` each demonstrated red.
- **Three `--help` honesty edits, each with its red observed against unmodified source before the text was written** — the only `src/` change in this spec, and text only. `rasterize --help` now names the `RasterEngine` port it resolves (`0615feae63`; the assertion imports `ports.raster.PORT` rather than typing the literal, so a rename reds it), qualifies the `--grayscale` single-channel claim for `--format webp` **without changing the output mode** (`66f43b3123` — WebP's bitstream has no single-channel mode), and states the orphan-teardown guarantee **per platform**: `SIGTERM`/`SIGINT`/`SIGHUP` on any POSIX host, the uncatchable `SIGKILL`-to-parent case on **Linux only**, because `PR_SET_PDEATHSIG` is a `prctl` facility (X-153 — the CI matrix is **not** widened; the macOS gap is filed).
- **The two teardown arms `PR_SET_PDEATHSIG` exists for never had a test on any platform, and now do.** `tests/integration/test_rasterize_signals.py` held exactly two functions (SIGTERM, SIGINT) while `changelog.md` claimed SIGHUP routed through the same teardown and the sentinel reports recorded all four at zero survivors — those were probes in a report, not committed controls. A SIGHUP arm and a Linux-gated SIGKILL arm are added; both signal the **parent PID alone** (X-119), both carry the non-vacuity guard (`count_at_death < _PAGE_COUNT`), and both **enumerate surviving PIDs from `/proc`** rather than reading a boolean, excluding zombies. Driven red against the pre-`B-055` tree at `c870e73`: SIGHUP `file count grew from 16 to 24 after the parent died`, SIGKILL **8 enumerated orphaned workers** listed by pid and argv. Off Linux the SIGKILL arm is a **visible skip** naming `PR_SET_PDEATHSIG` (demonstrated).
- **One derived forbidden-tool help check replaces three hand-typed copies**, and `PDF-09` `AC14`'s control now pins the claim instead of the token. `tests/unit/test_verb_help_content.py` carried three copies over hand-typed verb lists covering **8 of 26** verbs — with `rasterize`, the one verb whose first `--help` draft actually tripped the repository-wide forbidden-name scan, in none of them; the roster is now `discover_verbs()`-derived (26 cases, 0 offenders) with a non-vacuity pin. `AC14`'s shipped assertion stayed **green** when the claim sentence was deleted, because `--threads 1` occurs twice; the collapsed-sentence pin reds. Six further orphaned sub-clauses gained their first tests (`AC12`'s no-clobber read-back, `AC15`'s planned-path list, `AC16`'s render-failure path, `AC13`'s CLI-level refusal, `AC23(b)`'s single-path grep). 22 findings reported to the `project-manager`; `qa/FINDINGS-LEDGER.md` is not edited by this spec.

## [PDF-20] `PDF-05` engine-ports re-verification & purity tail — 2026-09-02

- **`doctor` is filesystem-pure on an engines-PRESENT host, and the fix is at the probe rather than at the verb** (`ba07fdfb56` / B-100, and B-075, which is the same defect seen through the `--dry-run` purity rule). `adapters/subprocess_util.probe_env()` copies the inherited environment and overrides only `HOME`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME` and `XDG_STATE_HOME`; the three probe-path spawns (`soffice --version`, `tesseract --version`, `tesseract --list-langs`) pass it, the two **operational** spawns deliberately do not, and `tests/test_import_boundaries.py` Section 2 asserts that split by construction so a fourth probe inherits it. **Measured, both ways:** before, all four of `doctor` / `doctor --strict` / `doctor --dry-run` / `doctor -o json` made exactly 2 differences under a pristine redirected `HOME` (`$HOME/.config` added, `$HOME` mtime moved); after, **0 differences on all four** and `$HOME/.config` absent, with every row still `available:true` and both binary versions still parsed. **D2.2 alone was measured to be sufficient; D2.5's `-env:UserInstallation` fallback was measured to be neither necessary nor sufficient on its own** and is not used.
- **The `doctor` envelope carries `dry_run`, additive at `schema_version` 1** — a key added, never renamed or renumbered (`d4ae996c52` / B-038). `build_payload()` takes a **required** `dry_run` keyword and emits it immediately after `verb`, so `-o json` reads `{schema_version, verb, dry_run, strict, ports}`; `-o ndjson` stops emitting `dry_run: null`. `doctor` follows `version`'s settled precedent: the key reports **what the user asked for**, not what the verb did. A guard whose verb population comes from `discover_verbs()` now asserts `schema_version`/`verb`/`dry_run` on **every** verb's `-o json` object, so the next hand-built payload cannot repeat the omission; its red is removing the key from `cmd_info.py`, which makes the guard fire for `info`.
- **One password hint, at the port, saying something true** (B-086). `ports/structure.PASSWORD_HINT` replaces two byte-identical private copies **and three further inline spellings the finding did not name** — five message sites, not two — following `PDF-13`'s `ENCRYPTION_ALGORITHMS` precedent exactly. The `--password-file` clause is **dropped**, and the measurement is worse than the row said: every one of the 26 verbs *accepts* that flag and exactly three (`decrypt`, `encrypt`, `permissions`) *honour* it, so on 18 of the 19 verbs that can print the hint a user who supplied the correct password received the identical exit-6 refusal. A landed test was **pinning** that misinstruction (`test_info.py` asserted `--password-file` was named) and is re-derived to assert the resolution `info` can actually offer.
- **All 18 of `PDF-05`'s acceptance criteria are re-derived, each against a control observed RED** (`tests/acceptance/audit_pdf_05.py`, `AUDIT-CONVENTION(PDF-17)`, 58 covering node ids all resolving in a live collection): **15 `holds` · 1 `inverted` · 1 `not-met` · 1 `no-live-control`**. Every mutation was applied in a scratch `git worktree` under `$TMPDIR` with `PYTHONPATH` pinned to its own `src/` (X-210), proven present before its arm ran, and reverted with a sha256 manifest — 13 files, 13 matches. **AC10 is inverted and it is the sharpest thing here:** `start_new_session=False` — the mutation `PDF-05` AC10 names as its own red — leaves the group-kill row green in 300.25 s, and green in 0.25 s on the row whose grandchild does not hold the pipes **while a `sleep 30` survives the run**, because `ProcRun.pgid` is `proc.pid` unconditionally and `killpg` on a group that never existed raises at once. **AC16 is not met** (the `PDF-06` corpus handoff was never executed and is mechanised by nothing). **AC17 carries no live control by construction** and is recorded as such rather than counted as one. Filed, not repaired.
- **The `--dry-run` purity instrument can now see the defect it was blind to** (AC21). C9/C10 move from `MUTATING` to a new `DRY_RUN_PURITY` population equal to **every** verb, because `CLAUDE.md` rule 2 states purity without a condition while `doctor` — which cannot be `is_mutating`, since it never reaches the write chokepoint — sat structurally outside the rows that measure it. `is_mutating` is **not** touched and the `[compress]` parameter ids are preserved. The `resolve()` hoist in C10 is **retained**, with its reason re-measured and corrected: `resolve()` runs in-process against the **real** environment, so removing the hoist would have made the spawn no more visible to that row and would have added a real-home write to every suite run. Proven by mutation: reverting the `env=` argument turns `test_c9_unconditional_dry_run_purity[doctor]` red **with the hoist still in place**.

## [PDF-19] `PDF-04` safety-spine re-verification — 2026-09-02

- **`PDF-04`'s 21 acceptance criteria are re-derived for the first time since its 2026-08-29 landing, and the split is 17 `holds` · 1 `inverted` · 2 `not-met` · 1 `unmeasured`** (`tests/acceptance/audit_pdf_04.py`, `AUDIT-CONVENTION(PDF-17)`, 85 covering node ids all resolving in a live collection). Every `holds` row names a control this audit drove **red** against a mutation planted in a `git worktree` under `$TMPDIR`, reverted with `git show HEAD:` and confirmed clean before the next one; **no mutation ever entered `apps/pdf-toolkit`, and `src/` is byte-untouched by this commit**. X-210's hazard was confirmed live first: a scratch tree run without `PYTHONPATH` pinned to its own `src/` imports the real repository through the venv's editable `.pth`, so every plant would have been a silent no-op reading green. **No `PDF-04` criterion is claimed `Verified` here** — the engineer produces evidence, the `qa-sentinel` grants or refuses.
- **Three things this audit found that a green suite could not have shown, all reported and none fixed here.** (1) **AC11 is inverted**: the entire size + SHA-256 verification can be deleted from `_replace_across_devices` and all eight cross-filesystem arms stay green, because `test_a_real_exdev_degrades_and_verifies` asserts `"SHA-256" in stderr` — a string in the *warning message emitted before the copy* — so it proves the writer **announced** a verification, never that it performed one. (2) **AC15 is not met**: §D7 row 2 (`Path.open`, *mandated*, not an extension) is invisible to the write-chokepoint walk in its idiomatic spelling, because `_classify_open` reads the mode from `node.args[1]` — the builtin `open`'s slot — while a method call puts it at `args[0]`; `p.open('w')` is unflagged, `p.open(mode='w')` is flagged. `src/` contains no such call, so the guarantee holds and the **guard** is blind. Landed as a `strict=True` xfail that turns red the day the visitor learns to read a method call's mode. (3) **AC20 is not met**: `85dd844`'s two platform-dependent test fixes are described by no `changelog.md` entry — X-188's binding reading is *no entry is ever lost*, and `PDF-04`'s own log already calls it *"owed and not written"*. Back-filling it is the `project-manager`'s (rule 3), not this commit's.
- **All fourteen §D7 call groups now carry a planted violation, and the coverage claim is executed rather than written down.** `PDF-04` shipped five plants for five groups; nine had never been observed to red. Nine rows were **appended** to `PLANTED` (X-15; no existing row rewritten), and `D7_GROUP_PLANTS` + `test_every_d7_call_group_has_a_planted_violation` fail naming the group if a plant is renamed or a group emptied. `PLAN §12 R-07`'s recorded ladder — `grep -rn "\.pdftoolkit-" src/ | grep -v tempnames.py` — **returns 3 prose hits and exits 0** at `7522e3e` where `PDF-04` AC16 expects empty, so a sentinel re-running it would file a defect against a correct tree; it is replaced by an AST check for exactly one string-literal *definition* of the prefix, proven red by planting a second literal in a `discovery`-shaped module. That also discharges `tempnames.py:8-11`'s claim that *"an import-boundary grep asserts it"*, which was backed by nothing. Census re-measured with the walk's own machinery: **11** mutating calls under `src/`, all inside `safety/atomic.py`, tier-1 **0**, tier-2 **0**, both allowlists empty — every line number moved under `PDF-18`.
- **The `--dry-run` purity instrument is taken apart rather than re-run, and its `README.md:74` census is measured.** Three dimension ablations, three observed transitions: removing `ino` blinds exactly the identical-content-replacement control; removing directory traversal, or `mtime_ns`, blinds the create-then-delete control; *adding* `atime` reds the exclusion control **and** five legitimate dry-run purity arms, which is what turns that exclusion from an omission into a decision. The mode control is re-derived under **both** `umask 022` and `umask 002` (it was vacuous once on this exact file, `85dd844`). `redirected_environment()` is proven load-bearing in both directions, entirely inside `tmp_path`. Both instrument docstrings said **six** negative controls since `PDF-04` landed; the file carries **nine**, corrected at all three carriers and now mechanized. `VERBS − MUTATING` = `{doctor, info, version}`: `info` and `version` are pure; **`doctor --dry-run` writes `$HOME/.config`** and is pure again with `soffice` off `PATH` — causation, not co-location. `README.md:74` is **not** softened, `tests/registry.py` is **not** widened, `cli/cmd_doctor.py` is **not** touched; the `doctor` behaviour is `PDF-20`'s (B-075 / B-100 / `ba07fdfb56`).
- **Confirmation-gate *reachability* is now visible instead of silent, and `TESTING.md` is corrected where it was measurably wrong.** Section 4's walk forbids a `dry_run`-guarded call and structurally cannot see an **absent** one; `GATE_EXEMPT` (12 entries, mandatory `# reason:` each, stale-entry detection, the `ALLOWED_WRITE_SITES` idiom) makes every `cli/cmd_*.py` module either gate or say why not — four entries are the deferred **B-022 ≡ B-045** producers (`extract`, `rasterize`, `tables`, `text`), which this spec measures and does not decide. `TESTING.md`'s acquisition ladder went from three documented rungs to the **five** `_ladder()` enumerates (the fixture prints the rung it resolved at, so a three-rung list does not match the message an operator is handed), the negative-control count from six to nine, the import-boundary section from three sections to **five**, and the expected visible-skip count is re-measured on this host and stated as a number: **259 passed, 0 skipped, 1 xfailed** over the eight safety-spine files, ladder rung `2 (/dev/shm)`.

## [PDF-28] docs: correct the epilogue's reproduce-one-CI-leg command — `make test PYTHON=3.11`, not `make ci PYTHON=3.11` — 2026-09-02

- **This entry corrects a command published by the previous `[PDF-28]` entry and by the epilogue that entry shipped; that entry is left standing and unedited** (rule 3: *never edit a landed entry; a correction is a new entry with a new date*). `scripts/gate_parity.py`'s success epilogue — the one line whose entire purpose is to tell the truth about what `make ci` does and does not predict — advertised `make ci PYTHON=3.11`, and so did the `PYTHON ?=` comment block in `Makefile`. Both now read **`make test PYTHON=3.11`**.
- **The advertised command was wrong on two independent counts, either of which alone would have been enough.** It **fails**: `[tool.coverage.run] core = "sysmon"` (`pyproject.toml:153`) needs CPython >= 3.12 (PEP 669), and `patch = ["subprocess"]` (`:176`) propagates coverage into every spawned CLI child — so on 3.11 coverage.py's fallback `CoverageWarning: Can't use core=sysmon` becomes the **first line of that child's stderr** and breaks the tests asserting the `strategy: ` diagnostic banner is that first line. Measured directly here rather than inherited: `tests/integration/test_text_tables_cli.py::test_ac2_the_banner_is_on_stderr_when_the_payload_goes_to_stdout` is red at both parametrizations under an instrumented 3.11 run. And it **would not have reproduced a 3.11 CI leg even if it had passed**: CI's 3.11 matrix legs run `make test` (`.github/workflows/ci.yml:100`), UNINSTRUMENTED — `make ci` runs `cover`, which CI never does at 3.11. The epilogue was pointing contributors at a command that both breaks and measures the wrong thing.
- **`make test PYTHON=3.11` is the command CI's 3.11 legs actually run, and it is green: 2118 passed, 31 skipped.** Measured on this host with exactly that invocation *before* the text was changed to claim it. That it is uninstrumented is not incidental to the correction — it is precisely why the `sysmon` failure cannot arise on the path now advertised.
- **The underlying 3.11-under-coverage failure is NOT fixed here; it is backlog `B-148`, owned by `PDF-29`.** Nothing was weakened to make this entry true: `--cov-fail-under=85` still has exactly one definition (`Makefile`), the pragma total under `src/` stays at **46**, no `omit` was added, no test was skipped or deleted, and the CI matrix is untouched. The whole product diff is two prose sites and one f-string; `src/` is byte-untouched.

## [PDF-28] Local-gate/CI-gate equivalence & PDF-02 re-verification — 2026-09-02

- **Five claim sites said `make ci` runs exactly the checks CI runs; it is 7 targets against 10 jobs / 17 check legs / 19 gating steps, and no host a contributor plausibly has can close that gap** (half the `test` matrix is `macos-14`; `secret-scan`'s local `gitleaks` binary is unpinned and a different scanner than CI's pinned `8.30.1`, V-5/B-121). `README.md`, `CLAUDE.md` (two sites), `CONTRIBUTING.md` and `Makefile` are corrected to state `make ci` is a **subset** of CI that does not predict it, with no numeral in the corrected prose (HC-5). The sixth statement of the same claim, `PLAN.md` §8.1:595, is operator-owned and out of scope (OR-13, X-158) — reported, not edited.
- **`.github/gate-parity.toml` + `scripts/gate_parity.py` + `tests/test_gate_parity.py` replace the claim with a derived, two-directionally-enforced manifest.** 19 `[[check]]` rows, one per CI gating step (derived by a documented classification rule — `run:` steps, excluding setup/informational/self-neutralizing ones — applied identically by two SEPARATELY WRITTEN parsers: `gate_parity.py`'s structural PyYAML derivation and the test's own from-scratch regex scan, so a shared-parser bug cannot make both sides agree wrongly). A CI job added without a declaration, or a manifest entry whose job no longer exists, both redden the suite — the anti-weakening direction is mechanically enforced, not merely written down. `make ci`'s new one-line epilogue (`scripts/gate_parity.py epilogue`) prints, from the manifest, exactly what CI additionally gates and how to reproduce it locally where a counterpart exists; it costs ~0.1s. Three new local targets make CI-only checks runnable without joining `make ci`: `make engines-gate` (both engine configurations; refuses loudly, never skips, if `tesseract`/`soffice` are absent), `make licenses-check`, `make artifacts-check`. `Makefile` gains `PYTHON ?=` (B-029): `make ci PYTHON=3.11` reproduces one CI leg under an isolated `.venv-py3.11/` without disturbing the ambient `.venv/`.
- **`scripts/assert_skips.py` no longer miscounts a deliberate `xfail` as an engine-gated skip (B-081).** `<skipped type="pytest.xfail">` is excluded before the `ENGINE_REASON` regex runs; the complement (`type="pytest.skip"`, the real shape a `@pytest.mark.requires(engine)` skip produces) is still counted, and the without-engines non-vacuity guarantee (zero engine-gated skips is itself a regression) is unweakened — both proved with the first tests this script has ever had (`tests/test_assert_skips.py`, 6 tests, synthetic JUnit fixtures only, none committed).
- **`PDF-02`'s 20 acceptance criteria are re-derived for the first time since its 2026-08-29 landing** (`tests/acceptance/audit_pdf_02.py`, `AUDIT-CONVENTION(PDF-17)`): 8 `holds`, 2 `superseded` (AC3 by `deploy-website.yml`'s later, legitimate `id-token: write`; AC5 by `PDF-06`'s non-vacuity fix, exactly as `PDF-02`'s own Validation block predicted), 10 `unmeasured` — four of those (AC8/AC9/AC10/AC15) are one-time historical `gh` observations against a deleted spike branch and a dispatched release run, re-confirmed live rather than transcribed, and expected to land this way per this spec's own AC23. Four of `PDF-02`'s criteria (AC1, AC2, AC3, AC17) are now permanently mechanized rather than re-checked by hand; two (AC6, AC19) have their controls CONSTRUCTED because their original premises are stale (the venv is 3.12.13, not 3.14.4; `gitleaks` is now present and unpinned, not absent). No `PDF-02` criterion is claimed `Verified` here — the engineer produces evidence, the `qa-sentinel` grants or refuses.
- **Nothing was weakened to make the two lists agree.** `ci.yml`'s `jobs:` key count is 10 before and after (only two `run:` steps converted to `make cover`/`make test` invocations, so `--cov-fail-under=85` now has exactly one definition, in `Makefile`); the redundant second `make licenses` in the `license-gate` job is declared in the manifest and NOT removed; the pragma total under `src/` stays at 46; `pyyaml` is declared in `[dependency-groups] dev` only (already resolved transitively, `make licenses && git diff --exit-code` proves the dev/runtime boundary holds).

## [PDF-27] docs: correct the pre-existing `/tmp` directory count — the figure was 333, not 244 — 2026-09-02

- **This entry corrects the figure published in the previous `[PDF-27]` entry, which is left standing and unedited** (rule 3: *never edit a landed entry; a correction is a new entry with a new date*). That entry states *"244 such directories predate this commit on the implementing host"*. **The correct figure is 333**, and the commit body of `9de34e7` — the very same commit — already said `333`. The two numbers were published side by side, in the same commit, disagreeing with each other.
- **Both numbers were real, which is the whole reason this is worth an entry.** `244` was the count measured at the start of the implementing session. The audit then ran the suite roughly 89 more times against the still-unfixed import-time `tempfile.mkdtemp()`, and **each of those runs leaked another directory** — the finding reproducing itself while it was being measured. By the time the `atexit` teardown landed, `333` directories predated the commit. A full `make ci` on the fixed tree afterwards added **zero**, which is the result the fix claims. All 333 remain on disk: **none was deleted, and no recursive delete under `/tmp` was attempted** — that residue is the operator's under OR-13.
- **The mechanism, named because it is the durable part: a published number that was superseded by its own author's later measurement, and was not re-derived before publication.** Nothing was inherited from another agent here and nothing was guessed — the author measured twice, correctly, and then published the first measurement. That is the same family as the counts corrected at X-160, X-166, X-169 and X-186, arriving inside the wave whose stated thesis is that hand-carried figures are this product's recurring defect. **The rule it argues for is narrow and mechanical: a figure is re-read from its source at the moment it is written down, not recalled from earlier in the same session.**

## [PDF-27] PDF-03 page-range grammar re-verification — 2026-09-02
- **All twenty of `PDF-03`'s acceptance criteria re-derived against the module as it stands today, with a zero-line product diff except one named finding: 15 `UPHELD` · 3 `REPAIRED` · 2 `FINDING`.** The audit record is `tests/acceptance/audit_pdf_03.py` — `AUDIT-CONVENTION(PDF-17)`'s second module, twenty contiguous rows, every covering node id copy-pasted from a real `--collect-only` and re-checked live by `test_every_covering_node_id_resolves`. Every non-`FINDING` row names a mutation that was applied to the working tree, observed red, and reverted (`git show HEAD:<path>` + `git diff --exit-code`; never `git stash`, never the index). **Forty-one mutations in total**, including one distinct mutation per `PLAN.md` §4.3 token-table case (twelve) and per error-table row (seven), plus a `DELETED_ROW` red for each completeness meta-test. `PDF-03`'s AC17 control is recorded honestly as firing by **`MemoryError` under `ulimit -v`**, not by its `elapsed < 1.0` assertion — the mutation attempts a ~100-billion-element allocation, so it was never run inside `make ci`.
- **The two dispatches over one grammar disagreed, and the divergence was real.** `743853f [PDF-07]` added `is_valid_spec()`/`_is_valid_body_shape()` beside `parse()`'s `_resolve_body()`: shared keyword set, shared regexes, independent `if` ladders, and nothing that could detect drift. The new `test_syntax_oracle_agrees_with_parse` property was **red at `0abd691`** with hypothesis shrinking to `'9' * 4301` — a numeral past CPython's 4300-digit `int()` ceiling is matched by `_SINGLE_RE`, so the oracle answered `True` while `parse()` raised `malformed` through `_safe_int`. `ops/merge.py:73` decides whether `a.pdf:1-3` is a path-plus-range or a filename by calling that oracle, so the disagreement is a wrong answer with a success exit code. **Fixed in `_is_valid_body_shape` (the whole product diff, ~13 lines):** it now converts the same numeral groups through the same `int()`, so both dispatches refuse together. Red both ways — removing the agreement reds the soundness clause; accepting the empty token shape in `_resolve_body` alone reds the completeness clause.
- **Three controls that could not fail for the reason they claimed, repaired with the original weakness measured.** `PDF-03` AC14's "mechanized doc criterion" was a bare substring scan: deleting the `GRAMMAR_HELP` rows for `N`, `,`, `first` or `!TOKEN` each left it **green** (only `odd` reds it), because `N` lives inside `N-`/`!TOKEN` and `,` lives inside every `e.g. 1-3,last,!2`; it now matches the documentation **row key**, and all four deletions red. AC10's invariant control counted names containing `property` and asserted `== 5` — **anti-additive**: a rename reds it (correct) and so does a sixth property test (wrong), inviting the `>= 5` "fix" that discards its only value; it now asserts the five `P1`–`P5` names, callable, `-k property`-selectable, `max_examples=1000`, `deadline=None`, and red two ways as required (rename reds, a sixth property does not). AC8's column arithmetic had no control on its `leading` term at all: dropping it left the whole 52-test band green, closed now by a three-case whitespace table (`" 1-3 , 5 "` ≡ `"1-3,5"`; `"1 - 3"` malformed with the token quoted; `"1-3,  abc"` reporting column 7).
- **`PDF-03` AC12's live successor is now checkable, and its historical half is re-derivable forever.** `grep -rn "pagerange" src/pdf_toolkit/cli/` returns **five** hits at HEAD and that is **correct** — `PDF-07`/`PDF-08` wired the grammar and `PDF-03`'s own Validation section predicted the flip; the historical criterion holds at `9d0703d` (`git grep` there returns nothing, and that commit touches no `cli/` path). What survives the flip is **single ownership**, and `test_the_page_range_grammar_has_exactly_one_owner` carries it: no §4.3 keyword-set literal, no page-range regex (matched by an accepts-a-page-token/rejects-ordinary-words discriminator, so a re-derived regex is caught as well as a copied one) and no private-internal import anywhere under `src/` outside `ops/pagerange.py`. Red-observed with three plants in three different consumers. `tests/test_cli_contract.py`, `tests/registry.py` and `tests/test_license_policy.py` are byte-untouched; AC18 is upheld by **consuming** the repo-wide HC-1 walk, with a first-hand red (one transient forbidden-engine reference in the audited file, caught by name and line, reverted).
- **`d8233d4cc9` stops growing, and the fix asserts about its own directory only.** `tests/test_pagerange.py`'s import-time `tempfile.mkdtemp()` now has an `atexit` teardown — no repository write, no new dependency, no `conftest.py` edit — and its control runs a child interpreter, records the path that child created, and asserts it is gone once the child exits. Deliberately **not** a glob over `pdf-toolkit-pagerange-hypothesis-*`: 244 such directories predate this commit on the implementing host, they belong to whoever ran the suite before (OR-13), and none was deleted. **Two figures measured rather than inherited:** module coverage from `tests/test_pagerange.py` was **88 %** at `0abd691`, not the Implementation Log's 100 % and below AC19's own ≥ 95 % floor (`PDF-07`'s seventy new lines were untested and nothing re-runs a per-module floor — filed as a `FINDING`); it is **99 %** after this commit, the one remaining line being an unreachable defensive `return False` that is **named, not pragma'd** (the `src/` pragma total stays at exactly 46, and `--cov-fail-under=85` is untouched at both enforcement sites).

## [PDF-18] fix: AC12's convert cell must respect engine absence, not assume it — 2026-09-02
- **The first `PDF-18` commit (`bd015d4`) pushed CI red on 10 of 17 checks** — every `test` matrix leg plus `without-engines`. `test_ac12_the_five_precondition_matrix[convert]` assumed every dry-run `-o json` payload carries an `items` list, but `convert`'s C cell on a host without `soffice` raises `EngineMissingError` from inside the dry-run branch itself (D12.1/B-096/OR-7 — an absent engine is knowable at plan time and predicts exit 3 in both modes, exactly as designed), producing a top-level `{"error": {...}}` envelope with no `items` key. `soffice` is installed on the implementing host, so `make ci` passed locally every time; only `engines-present` (the one CI job that also installs `libreoffice-writer`) came back green, exposing the gap.
- **Fix, scoped to the one parametrize case that needs it — an expected VALUE, never a skip.** `_C_CELL_EXPECTED` derives the C cell's expected exit code once, at collection time, from `pdf_toolkit.ports.office.office_binary_present()` (the same spawn-free presence check `ops/office.py` itself uses): `convert` reads `0` engine-present / `3` engine-absent, every other verb reads `0` unconditionally — `_NO_CLOBBER_EXPECTED`'s own sibling pattern. **The U cell is asserted UNCONDITIONALLY on every leg**, regardless of engine presence: the filesystem tier refuses before `ops/office.py`'s engine-presence check is ever reached, in both modes, so it is the cell that proves `PDF-18`'s D3 thesis, and a whole-parametrize-case `pytest.mark.requires("soffice")` skip (the first candidate fix, rejected) would have thrown it away on 9 of 10 legs. `convert`'s N/M/F cells need a real conversion to seed a colliding output; with `soffice` absent that seed itself exits 3 before writing anything, so a stated-reason `pytest.skip` (never a silently-passing assertion) replaces the assertion for that one leg only, after U and C have already run.
- Also folds in three stale cross-file references to the deleted `ops/_plan_filesystem` name (`cmd_compress.py`, `optimize.py` docstrings; an `office.py` comment block citing the deleted function's old line numbers), found via `grep -rn "\b_plan_filesystem\b" src/` after the first commit had already been pushed. No other `src/` behaviour changed; product code is otherwise identical to `bd015d4`.
- CI hand-tallied at `b3c92f7`: **17/17 checks green**, including `engines-present` and `without-engines`.
- **Process note:** this fix landed as `b3c92f7` without its own changelog entry, discovered and corrected here (this entry) rather than by amending that commit (`OR-6`/X-180: forward-fix only, no history rewrite).

## [PDF-18] One planning tier: unify `_plan_filesystem`, refuse the unwritable-parent tier — 2026-09-02
- **Eight `_plan_filesystem` definitions and seven `_FilesystemPlan` dataclasses collapse into one.** `crypto.py:265`, `metadata.py:200`, `ocr.py:178`, `office.py:148`, `optimize.py:159`, `overlay.py:148`, `pages.py:349`, `textract.py:326` are gone; `safety/atomic.py::plan_filesystem()` is the single planner, reached by all 12 former call sites with the identical `(targets, *, out_dir, policy, kind)` shape, including `ops/crypto.py`'s own divergent `PdfToolkitError | None` return (B-064's "fourth copy", now folded in with the other seven). `PlannedOutputs` absorbs the `would_exit`/`would_refuse`/`message`/`refused`/`detail()` vocabulary every copy defined identically. Wire-compatible byte-for-byte, verified against `git archive 2d19bcb src` for `compress`/`ocr`/`meta set`/`encrypt` across a clean plan, an occupied target, and an unwritable existing destination — 12/12 identical.
- **`d55b302668` (high, B-112) — the unwritable-`--out-dir`-parent crash — closed on all 11 `--out-dir` verbs.** `safety/atomic.py::_ensure_out_dir`'s unguarded `out_dir.mkdir(parents=True, exist_ok=True)` is now wrapped: any `OSError` (the whole errno family — `EACCES`, `ENOTDIR`, `EEXIST`-as-file, `ENAMETOOLONG`; `EROFS` skipped, not producible without root) becomes `DestinationUnwritableError`, exit 1, through the CLI's existing single error handler — no new plumbing. The `--dry-run` side, previously an unconditional no-op leaving this tier structurally invisible, now predicts the same question read-only via a new `nearest_existing_ancestor()` walk (`safety/paths.py`) plus an `os.pathconf(PC_NAME_MAX)` length check. `compress`, `convert`, `delete`, `extract`, `ocr`, `rasterize`, `reorder`, `rotate`, `split`, `tables`, `text` all predict `dry == real == 1` where the population previously crashed with a bare traceback and 0 bytes on `-o json` stdout. B-058's live half now has its correctly-scoped fingerprint.
- **`fa5736f2ae` (high) discharged as the same defect's second trigger.** An `--out-dir` that names an existing regular file raised the identical unguarded `FileExistsError` (`exist_ok=True` only suppresses `EEXIST` when the existing path is a directory); the same guard now converts it to the same coded refusal. Verified on the observable X-184(b) requires — the `-o json` stdout envelope and the absence of a stderr traceback — not the exit code alone, because the unfixed binary already exited 1 for this arm.
- **`d231fbcec4` (medium, B-113) — the `crypto` ladder's tier-order disagreement — closed as a byproduct of unification, not a second fix (Design D3).** Six of the eight collapsed copies consulted the single-destination writer tier only under `if policy.dry_run and out_dir is None:`, so a real run's always-false guard let a *different* tier answer first — for `encrypt`/`decrypt`, password resolvability (exit 6) or the document tier (exit 4) instead of the filesystem tier the dry run had already predicted (exit 1). `plan_filesystem` now checks destination writability in **both modes** unconditionally (the widening `ops/ocr.py`/`ops/office.py` already carried, generalised to every caller), so a real run raises at the filesystem tier before the password loop is ever reached. `ops/crypto.py:315`'s *"every tier is evaluated identically in both modes"* is true again and pinned mechanically, one stimulus per `_plan` tier. X-67's own carve-out (a wrong-but-resolvable password stays `dry 0 / real 6`) is unchanged and re-asserted with the decidability rule named at the pinning test.
- **`--out-dir a/b` under an unwritable parent stays exit `0` for the ordinary case (Trap 1, unchanged).** `--dry-run --out-dir new/` over a writable parent still predicts clean and leaves `new/` absent; the real run still creates it. New unit and integration coverage pins the composed precedence of the four-tier order and the 11 × 5 dry/real pair matrix (`tests/integration/test_out_dir_planning.py`, population and per-verb invocations derived from the live registry, `len(verbs) == 11` pinned as a non-shrinkage guard). `tables` is the one verb the exit-5 no-clobber gate cannot mask (nothing seeded to collide with) and its own cells are asserted explicitly rather than skipped — which also surfaced and fixed a latent gap in `extract_tables_run`'s (and, symmetrically, `extract_text_run`'s) empty-targets branch, which hardcoded `ok=True, exit_code=0` regardless of the plan.
- **The write chokepoint did not move** (`tests/test_import_boundaries.py` Section 1 unaffected) and a new Section 5 makes the invariant this spec's own refactor depends on structural: no module under `ops/` may name `DestinationUnwritableError` or `TargetExistsError` — the two refusal classes belong to `plan_filesystem` alone. `tests/unit/test_metadata.py`'s AC21 pin is re-pointed at the new symbol by design (Design D9); the invariant it protected is now also enforced tree-wide rather than for one module.
- Both new `# pragma: no cover` candidates introduced while writing `nearest_existing_ancestor`'s root fallback and the `os.pathconf` unavailability branch were made coverable with targeted monkeypatch tests instead — the `src/` pragma total stays pinned at **46**, unchanged from `PDF-17`.

## [PDF-17] fix: the branch-coverage expiry alarm fired, correctly, on CPython 3.14 — 2026-09-01
- **The alarm was right and the deviation HAS expired — on one interpreter.** `PDF-17` shipped `test_the_branch_coverage_deviation_has_not_expired` as *"fail the moment the installed coverage + CPython supports branch measurement under `sys.monitoring`"*, which is what `pyproject.toml:142-145` asks for in terms. Its first pushed CI run (33588614762) went **red on both `test (3.14, ...)` legs** while all six 3.11/3.12/3.13 legs passed: on 3.14 coverage.py emits no refusal at all. Measured across **eight interpreters** plus this engineer's local 3.12.13, the support boundary is exactly **CPython 3.14**.
- **Recorded as a boundary, not papered over, and now it fires in BOTH directions.** `BRANCH_UNDER_SYSMON_FROM = (3, 14)` is compared against a live probe on every matrix interpreter, so support arriving *earlier* than recorded and support being *withdrawn* both fail by name. Nothing was excluded, skipped or version-gated away.
- **§8.1's ruling still holds where it binds, and that is now an assertion rather than an assumption.** `--cov-fail-under=85` is enforced only in `ci.yml`'s `engines-present` job, which pins **Python 3.13** — an interpreter that still cannot measure branches under `sys.monitoring`, so `branch = false` stays for the reason it was measured. `test_the_floor_interpreter_still_needs_the_branch_deviation` fails, naming `PDF-17`, the day that job moves to 3.14+, and `test_the_floor_interpreter_matches_the_workflow` parses the version out of `ci.yml` so the claim cannot outlive the file it describes. **`ci.yml` itself is untouched** — `PDF-28`/`PDF-29` own it.

## [PDF-17] Contract-harness repair & PDF-06 re-verification — 2026-09-01
- **The primary instrument can now fail.** `tests/test_cli_contract.py` carried exactly **two** `assert len(...) > 0` statements against **fifteen** tuple-valued module-level populations — and `B-032` was wrong in both directions about which two (`DESTRUCTIVE` *was* pinned; `PAGE_ADDRESSING`/`MUTATING` were not). Both ad-hoc pins are replaced by a `POPULATIONS` roster with a `minimum` argued per row, one parameterized pin over it, and `test_every_population_is_rostered`, which fires when a population exists in the module but not in the roster — it fired on this spec's own new `HONOURED_CELLS` during implementation, which is why the roster is sixteen rows and not fifteen. Deliberately **per-population**: `PDF-06`'s AC6 pins that `pytest -m e2e --collect-only` collects non-zero and was **green at the very commit where C4/C9/C10/C11/C13 each collected zero**.
- **C14's honoured side proves the *verb* wrote, not the test builder.** `afe2e6137b`: the row's own builder materialises its input into `tmp_path` and the harness snapshotted `tmp_path` *before* calling it, so `assert after - before` was satisfied by the builder's file — the exact "exit 0, nothing written" shape the assertion's own comment claimed to catch. Re-derived at implementation HEAD by the sentinel's method (replicate the assertion with the verb never run): **19 of 53** declared cells passed vacuously — not the ledger's `9 of 25`, not the spec's `20 of 53`, neither inherited. The honoured side now reads the verb's own planted destination from its `--dry-run -o json` plan and asserts it absent before and present after (`--in-place` rows witness the `.bak` sidecar); **0 of 53** survive the same probe, and a planted stub that exits 0 without writing fails all 53.
- **B-047's reinstatement path is closed, and PDF-08's routing claim is tied to the test it credits.** `Invocation.destructive_build` already existed; the *guard* did not, and the documented `destructive_build or build` fallback meant the next `destructive=True` row written without one would silently re-share C12's single-input tail with C13 no longer discriminating and nothing failing. The fallback is deleted and pinned. Separately, `e138934a60` said "three hand-typed verb tuples"; the mechanized AC30 scan measured **twelve**, including partial subsets a rename leaves stale *and* passing, and one site no manual list had ever named. All twelve derive from one `registry.PDF_08_VERBS` declaration with a live membership tie.
- **The coverage floor's weakened semantics are ruled with instruments, not a comment.** Measured fresh at implementation HEAD, both arms, same band (`test_doctor` + `test_info`, 55 tests, quiet host): `branch = false, core = "sysmon"` **24.93 s / 46% line**; `branch = true` **486.56 s / 39% branch** — a **19.5×** factor, with `coverage` 7.16.0 emitting `Can't use core=sysmon: sys.monitoring can't measure branches in this version`. **`branch = false` stays and the key was not touched**, and the deviation now carries an expiry alarm that fails, naming `PDF-17`, the day that stops being true. The third gaming lever `PDF-06:236` left open is closed: every `# pragma: no cover` under `src/` must carry a reason and the total is pinned at **46**. **No test deleted, no `omit` added, `--cov-fail-under=85` unchanged.**
- **`AUDIT-CONVENTION(PDF-17)` exists and the suite executes it.** `tests/acceptance/` is one module per audited spec discovered by glob, with a frozen `_model.py` and a six-control aggregator whose own reds are proven against synthetic in-memory audits. `tests/acceptance/audit_pdf_06.py` re-derives all **25** of `PDF-06`'s criteria including the two its engineer filed as BLOCKERs at landing. `PDF-06`'s AC5 and AC11 both returned the wrong answer at `2d19bcb` and nobody noticed **because nothing ran them**; both are repaired as tests, and the aggregator caught a covering node id this spec's own author guessed wrong — which is the whole point.

## [B-101] fix: the last two surfaces still asserting the `--dry-run` clause OR-7 struck — 2026-08-31
- Operator ruling **OR-7** (2026-08-30) settled this cycle's longest-running contract question — `--dry-run` **MIRRORS** the exit code the real run would produce (`dry == real`), so `cmd --dry-run && cmd` short-circuits — and in doing so **struck** `PLAN.md` §5.6's *"Also: `--dry-run` completed"* clause, which now renders struck through as *"superseded by OR-7, 2026-08-30"*. Two surfaces went on asserting the struck clause as fact and were the **last two copies of it in the repo**: `README.md`'s exit-code table row 0 — the product's front door — and the `#:` comment on `OK` in `src/pdf_toolkit/cli/exit_codes.py`, a file whose own module docstring declares these integers **PUBLIC API from v1.0.0**. Both now describe the shipped contract, matching the phrasing already approved and live in the website's `ExitCodes.astro` cell 0 so the three surfaces agree word for word in meaning.
- Both were **false at HEAD, and the product's own pinned tests disprove them**: `convert --dry-run` against an absent `soffice` completes and exits **3** (`tests/integration/test_or7_engine_absent.py`), a bulk-destructive dry run on a non-TTY without `-y` completes and exits **5** (`test_c13_dry_run_predicts_the_bulk_destructive_refusal`), and a dry run over an occupied target exits **5** (`test_c15_dry_run_predicts_an_occupied_target_refusal`, `dry == real == 5`). Exit **0** is one outcome of a dry run, not its definition.
- **No behavioural change.** `exit_codes.py`'s diff is comment-only — no integer, name, ordering or `ALL_EXIT_CODES` membership moved — and `README.md`'s is a single table cell; the suite is unmoved at **1857 passed / 30 skipped**. A prose-only change earned its own commit **deliberately**: the PDF-16 Phase B pass *reported* `README.md:64` instead of fixing it, because AC26 enumerated that pass's README changes and widening a final-item commit is how scope findings get bounced. Correcting a PUBLIC-API surface is attributable to this commit rather than buried inside a website re-derivation.
- `website/src/components/ExitCodes.astro`'s header comment — the guard that stops the next honest re-derivation from walking the clause back in from an older copy — was **re-worded, not deleted**. It recorded cell 0 as knowingly diverging from a stale `exit_codes.py`; this commit made that note stale in the other direction, so it now records that the docstring has since been corrected and that the two **agree**. The rendered cell prose is untouched.
- **A third copy exists and was deliberately left alone, reported rather than fixed:** `src/pdf_toolkit/safety/atomic.py`'s `would_exit` docstring still claims *"The dry run's own exit status is 0 either way"* over an occupied target — the same struck clause in different words, which is why the exact-phrase grep that scoped this item missed it, and flatly contradicted by `test_c15`'s pinned `dry == real == 5`. It needs its own backlog item; widening this commit to reach it is exactly the failure mode this commit was carved out to avoid.

## [Task: PDF-16 — Project website (GitHub Pages), Phase B] - 2026-08-31
- Re-derived `Verbs.astro`'s roster entirely from `pdftoolkit --help` and each verb's own
  `--help`, entry by entry: all 16 pdf-toolkit specs have now landed, so all 26 rows
  (25 top-level commands, with the `meta` grouping parent kept expanded as its own
  `meta get`/`meta set` rows) are `available`; `planned.length` is 0, and the
  "Verbs marked planned..." sentence is now rendered conditionally on that count while
  the anti-drift sentence stays unconditional.
- Corrected `ExitCodes.astro`'s `OK` cell prose per operator ruling X-142: the code and
  name still come from `src/pdf_toolkit/cli/exit_codes.py`, but the meaning text no
  longer restates the `--dry-run` clause struck by OR-7 (a completed `--dry-run` mirrors
  the code the real run would return, so it is not always 0). The other six cells and
  the source docstring's remaining staleness are unchanged (`B-101`, out of `src/` scope).
- Regenerated `website/src/data/licenses.json` via `make licenses`; both it and
  `THIRD_PARTY_LICENSES` came back byte-identical to what CI already has at `327b4ad`
  (no drift to commit).
- Rewrote `QuickStart.astro`'s example block to three shipped invocations (`merge`,
  `rotate`, `compress`), every flag checked against that verb's own `--help`; per
  backlog `B-097`, neither `ocr` nor `watermark --pages N` appears in any example.
  Refreshed `README.md`'s "What exists today" section and both `README.md`/`CLAUDE.md`
  `Current phase:` lines (phase-name clause only, to "Phase 1 (v1) complete" — the
  trailing pointer clause is byte-identical in both files, per X-124/HC-5).

## [B-102] fix: a `test_raster.py` comment contradicted the commit that wrote it — 2026-08-31
- The comment heading B-094's four-angle matrix (`tests/unit/test_raster.py`) still said the double `/Rotate` application *"cancelled out at 0/180"*. **B-094 disproved that in the same commit**: the second application is an additional clockwise turn of `/Rotate` degrees, so the error was 90° at `/Rotate 90`, **180° at `/Rotate 180` — it did not cancel** — and 270° at `/Rotate 270`; only `/Rotate 0` was ever correct. `adapters/pdfium_raster.py`'s module docstring, written in that same commit, already says so, so the two read in opposite directions.
- The corrected comment also records **where the wrong reading came from** — comparing image *sizes*, which the second swap had already put back — because that is the part a future reader needs in order not to re-derive it. This is why the matrix asserts the band edge as well as the size: `_BAND_EDGE_AFTER_ROTATE`'s expectations only make sense against the corrected description, not against "cancels at 0/180".
- Comment text only. No assertion, no fixture, no product code; `tests/unit/test_raster.py` 45 passed, unchanged.

## [B-099] fix: `TESTING.md`'s quoted engines-hidden pass count was one low — 2026-08-31
- `TESTING.md`'s expected-skip table quoted the documented engines-hidden command as reporting `7 passed, 18 skipped`. Run verbatim it reports **`8 passed, 18 skipped`** — measured six times here (three at `971d0e5`, three at `2f8fc53`), stable every time. The `18` half is correct and the split it names is correct (13 in `tests/integration/test_ocr.py` — twelve `SKIPPED` lines, one of them a `[2]` — and 5 in `tests/integration/test_office.py`). Ledger fingerprint `03e638e590`; PDF-15 **AC21** requires the documented counts and the suite to agree (PLAN §10).
- **The provenance is the interesting half, and it is now written into the line.** B-094 corrected the *skip* half of this figure and carried the *pass* half across unchanged, because it was transcribed rather than re-run — which is exactly how a count stays one low through three consecutive QA sweeps. The line now says where its number came from and instructs the next reader to re-run rather than copy.
- Nothing else changed: no test, no product code, no other documented figure.

## [B-093] fix: the bulk-destructive confirmation gate did not mirror under `--dry-run` — 2026-08-31
- Every one of the **fifteen** `require_confirmation` call sites was guarded `if not config.dry_run and <destructive>:`, so `--dry-run` skipped the gate entirely: `pdftoolkit ocr a.pdf b.pdf --in-place --dry-run </dev/null` exited **0** while the real run exited **5**, and `cmd --dry-run && cmd` green-lit a run that then refused. That is a `dry != real` split on a row PDF-15 §D12.2 lists as **knowable at plan time**, so operator ruling **OR-7** binds it and AC26 asserts it. Ledger fingerprint `9ca0c128c8`. Pre-existing rather than a PDF-15 construction failure — 8 of the 15 guards predate B-079 — and it was the last blocker on AC26.
- **The rule is now in the ONE shared check, not in fifteen guards.** `safety/confirm.py::require_confirmation` is dry-run aware: on a non-TTY it raises the same `ConfirmationRequiredError` for a preview as for the real run (`dry == real == 5`), and the interactive branch is unreachable under `--dry-run`, so no stdin is read, nothing is written and nothing can block. The fifteen bypass guards are deleted; a call site's whole job is now to call the gate on the destructive path. **`cli/common.py::validate_config` was rejected as the home** despite being where its OR-3 siblings live (`_check_in_place_output_conflict`): the gate's inputs — the resolved input count, and which targets already exist — are verb-specific, and, decisively, `validate_config` runs BEFORE a verb has rejected a missing input (exit 4) or an impossible arity (exit 2) while the real run reaches the gate AFTER both, so checking there would predict the wrong tier. Leaving the check where every verb already calls it makes precedence correct by construction.
- **Precedence was derived from the real path, not assumed** — 12 dry/real pairs measured, all mirroring: the gate outranks the engine tier (`ocr a b --in-place` with `tesseract` hidden is **5 == 5**, not 3), the usage tier outranks the gate (`--in-place` with `-O` is **2 == 2**), the missing-input tier outranks it (**4 == 4**), and with `-y` the gate steps aside so the engine tier answers (**3 == 3**). That last pair is the control that stops "5 == 5" from being consistent with a preview that had simply stopped predicting anything.
- **The brief named one verb; the split was on two.** `ocr` reaches the gate through `in_place`, `convert` through a non-empty `clobbered` (it declares no `--in-place` at all, so `--force` over occupied targets is its only destructive shape) — both measured `dry 0 / real 5` at `971d0e5`, and `convert` structurally cannot join C13's `--in-place` population. The full §D12.2 table now mirrors on **14 of 14** knowable rows across both verbs (it was 12 of 14), each measured as a pair.
- Four instruments, every one shown able to fail. `tests/integration/test_or7_bulk_destructive.py` (new, cross-verb — mirror, diagnosis, purity under a redirected `HOME`, a never-written-stdin pipe under a hard deadline, and both precedence directions); C13 gains a **population-driven** dry arm in `tests/test_cli_contract.py`, so every future destructive verb is covered the day it registers a `destructive_build`; `tests/unit/test_confirm.py` pins the semantics in-process with a reader that fails if it is read; and `tests/test_import_boundaries.py` **Section 4** is an AST walk asserting no `cli/cmd_*.py` re-introduces a `dry_run` guard around the gate — comment-immune, with the original defect planted as one of its four controls. It reports exactly **15** violations against `971d0e5` and **0** here. 13 of the 27 new cases were RED at `971d0e5`; the other 14 were shown red under three planted mutations (hoisting the dry return above the non-TTY refusal, making the preview refuse everything, and un-hiding the engine).
- Full suite: engines-present **1857 passed / 30 skipped / 0 failed** (from 1830/30/0); engines-hidden **1826 passed / 61 skipped / 0 failed** (from 1799/61/0) — no new skips, the new arms run and mean the same thing in both configurations. `make ci` exit 0, coverage 94.00%.

## [B-094] fix: `/Rotate` was applied twice in `pdfium_raster`, so 90/180/270 pages rendered wrong — 2026-08-30
- `adapters/pdfium_raster.py` re-applied each page's own `/Rotate` on top of pdfium's internal application, **in both places it read the page**: `_displayed_size()` re-swapped `PdfPage.get_size()` (which is `FPDF_GetPage{Width,Height}F`, i.e. already the DISPLAYED box — measured: `get_mediabox() == (0,0,792,612)` while `get_size() == (612.0, 792.0)` on a `/Rotate 90` page, pypdfium2 5.13.0), and `_render()` passed `rotation=page.get_rotation()` into `PdfPage.render()`, whose own parameter pypdfium2 documents as *"**Additional** rotation in degrees"*. The two second applications **agreed with each other on the dimensions**, which is why the crop never fired and why every size-and-aspect assertion in the suite stayed green while the pixels were wrong. Fixed by removing both — pdfium's single internal application is left to stand; no compensating counter-rotation anywhere.
- **The received description of the blast radius was wrong in both halves, and the corrected one is why the new matrix covers all four angles.** The second application is an *additional clockwise turn of `/Rotate` degrees*, so the error is 90° at `/Rotate 90`, **180° at `/Rotate 180` — it does NOT cancel** — and 270° at `/Rotate 270`, with the dimensions additionally unswapped at 90/270. Only `/Rotate 0` was ever correct. Measured on a 200×600 portrait page with a black band on its top fifth: correct renders put the band top/right/bottom/left at 0/90/180/270 (ISO 32000: `/Rotate` turns the page **clockwise when displayed**); the pre-fix adapter put it top/bottom/top/bottom. `test_b094_rotate_is_applied_exactly_once_at_every_angle` asserts size **and** band edge at all four, and `[0]` is green on both sides of the fix — the control that makes the other three mean something.
- **`test_ac8_rotated_page_rasterizes_landscape` was pinning the defect (B-073's class), and its fixture is corrected here.** It built its page with `Canvas.setPageRotation(90)`, which **pre-swaps the MediaBox** to 792×612 — so the "portrait page" in its own docstring was landscape in raw space and displayed PORTRAIT, and `width > height` passed only because the adapter rendered the raw box. The fixture now stamps `/Rotate 90` onto a genuinely portrait page with pypdf (`_stamp_rotate`), which is what AC8's own wording — *"where the unrotated page is portrait"* — always said; the assertion is untouched and the precondition is now asserted rather than assumed. Same class of generated-fixture limit B-084 recorded for the *absence* of `/Rotate`.
- **The ceiling-vs-round crop needed no adjustment, and is now checked instead of trusted.** Target and bitmap both derive from the same `get_size()` floats, so `round(displayed*scale) <= ceil(displayed*scale)` holds at every angle — re-derived live across 0/90/180/270 × {72, 96, 150, 200, 300, 600} dpi: slack is 0 or 1 px, never negative (it does still fire — 200 pt @ 300 dpi gives bitmap 834 vs target 833). Before the fix the two were computed from *different* boxes and merely happened to agree. Because `PIL.Image.crop` past the edge silently **pads with black** rather than failing — the same silent-wrong-answer shape as the defect itself — `_render` now refuses a bitmap that disagrees with the target by more than that one pixel (`FailureError`, exit 1) instead of cropping it. AC1's exact 2550×3300 at 300 dpi is unchanged.
- **AC7 is unskipped and passing.** `tests/integration/test_ocr.py::test_ac7_rotated_page_returns_the_expected_text` shipped under an unconditional `@pytest.mark.skip`; it now carries only the ordinary `@pytest.mark.requires("tesseract")` gate, so it RUNS with engines present and skips VISIBLY without them — which also puts it back on the right side of `scripts/assert_skips.py` in **both** CI configurations (verified against real JUnit reports from both — see the suite figures below). The reason string's deliberate dodge of that script's `ENGINE_REASON` regex is no longer needed and is gone with the skip.
- **`_normalize_layer_geometry` composes correctly now that the adapter is right, and one 1e-16 residue in it was fixed.** Measured end to end: the OCR layer produced from a `/Rotate 90` page lands in the **same four word boxes** as the layer produced from the identical unrotated page (max deviation 0.16 pt), and its per-character matrices are `(0, -0.99980004, 0.99920064, 0)` — identical to the known-good layer stamped with `/Rotate 90`. Getting that exact required replacing `pypdf.Transformation.rotate()` with `_quarter_turn()`: `rotate()` builds its matrix from `math.cos`/`math.sin`, so a quarter turn carried `cos(π/2) == 6.123233995736766e-17` into the layer's `cm`. Far too small to move a glyph, **not** too small to be read — `pdfplumber` derives each character's `upright` flag by comparing those entries against zero, and the epsilon flipped it, making `pdftoolkit text` return `'P\nD\nF\nT\nO…'` instead of `'PDF\nTOOLKIT\nOCR\nFIXTURE'`. Product behaviour is otherwise byte-for-byte unchanged at rotation 0.
- Word-vs-newline separation on a rotated page is the **extractor's**, not the layer's, and is proven so with a control rather than assumed: stamping `/Rotate 90` onto an already-OCR'd unrotated file — changing one dictionary key and nothing else — makes the same engine regroup the words the same way. That is what licenses AC7's whitespace normalisation, the same one AC6 and AC10 already use.
- New coverage beyond AC7: an engine-free guard that `_quarter_turn`'s zeros are exactly `0.0` (and that `Transformation.rotate`'s are not), a **raster-level** four-angle matrix (size + band edge + `--width` mode), `_displayed_size` asserted against pdfium's own no-argument render rather than against this module's arithmetic, the crop invariant re-derived at every angle, and a **real-world rotated scan** — sideways pixels that `/Rotate` puts upright, at 90 **and** 270 — where a mis-rotated render is unambiguously fatal. All **13** new/corrected tests observed **RED at `30eb02a`** (via `git archive` into a scratch tree; the checkout was never touched) and green here.
- Full suite: engines-present **1830 passed / 30 skipped / 0 failed** (from 1816/31/0); engines-hidden **1799 passed / 61 skipped / 0 failed** (from 1789/58/0). `scripts/assert_skips.py` re-checked against real JUnit reports from BOTH configurations (1860 testcases each): engines-present `--expect-zero` reports `engine-gated skips: 0` and exits 0; without-engines reports `engine-gated skips: 33` (up from 29) and exits 0. `TESTING.md`'s expected-skip table is updated in the same commit — it named the AC7 skip as the one unconditional skip in the suite, and that is no longer true.

## [B-096] fix: `convert --dry-run` exited 0 with no `soffice`, while the real run exited 3 — 2026-08-30
- `pdftoolkit convert <src> -O <dst> --dry-run` on a host with no `soffice` on `PATH` reported `{"would_exit": 0}` and exited **0** while the real run exited **3** (`ENGINE_MISSING`), so `convert --dry-run && convert` green-lit a run that then failed — violating operator ruling OR-7 and PDF-15 §D12.1 (`--dry-run` MIRRORS the real exit code; `dry == real`). `ops/ocr.py` demanded its engine ABOVE its own dry-run return and was already correct; `ops/office.py` demanded it BELOW. Fixed in `ops/office.py`'s dry branch with `if not plan.refused and not office_binary_present(): require_office()`: the FILESYSTEM tier keeps its precedence, matching the real run (which raises there first), so an unwritable destination stays `dry 1 / real 1` instead of regressing to the `dry 1 / real 3` split, and the exit-3 message still comes from the ONE `require_office()` chokepoint rather than a second, drifting copy.
- **Why the obvious shape — simply calling `require_office()` (i.e. probing) under `--dry-run` — was REJECTED.** `require_office()` is spawn-free only when the binary is ABSENT: with `soffice` PRESENT, resolution runs `soffice --version`, and that command **creates `$HOME/.config`** (measured, LibreOffice 26.2.5.2). Probing under `--dry-run` would therefore break the non-negotiable purity rule (`CLAUDE.md` rule 2 — a dry run writes nothing, anywhere), which contract row C10 enforces against a redirected `HOME`. Presence is the only fact exit 3 turns on and `shutil.which` writes nothing, so `probe()`'s own `shutil.which` short-circuit was factored out into `adapters/soffice_office.py::binary_present()` and exposed as `ports/office.py::office_binary_present()` — ONE presence call site, shared by `probe()` and the preview, so a preview and `doctor` can never disagree. The branch is pure AND predictive rather than one or the other.
- Emitting a plan carrying `would_exit: 3` instead was also rejected: PDF-15 §D12.1/§D12.2 and AC26 specify exit-code EQUALITY (`dry == real == 3`, “each measured as a pair”); the `would_exit` plan-item language belongs to the FILESYSTEM tier and `"engine_verified": false` to the present-but-broken carve-out. The landed shape — a top-level error payload plus exit 3 — is identical to `ocr`'s existing engine-absent behaviour. Proven by the new cross-verb `tests/integration/test_or7_engine_absent.py` (one parametrized pair over both system-binary verbs), observed RED at `066db80` (`convert: dry=0 real=3`) and green here.
- **C10's `assert returncode == 0` was a SUPERSEDED-CLAUSE ARTIFACT, not a casualty of this fix.** It encoded `PLAN.md` §5.6's *“Also: `--dry-run` completed”* — the clause OR-7 STRUCK when it made `--dry-run` mirror the real exit code — as a universal over a population every new mutating verb joins automatically, and it survived the ruling only because, until `convert`, no registered invocation could legitimately predict non-zero on an engine-less host. `test_c10_registered_invocation_dry_run_purity` now BRANCHES and never skips: purity is the row's actual subject and is still asserted UNCONDITIONALLY on every host, while only the expected exit code is derived, from the verb's own declared `Invocation.requires_engine` resolved through the `ports.resolve()` chokepoint `doctor` uses — never an independent `shutil.which`, env var or platform check. The new arm was proved able to FAIL: against the pre-fix product with `soffice` hidden it reds with `convert: --dry-run exited 0, expected 3`.
- `tests/test_cli_contract.py::_discover_target` — C15's discovery preamble, which learns the target by running the invocation under `--dry-run -o json` and requires exit 0 — cannot be SEEDED on an engine-less host now that `convert --dry-run` legitimately exits 3 before any plan exists, so it is gated by the already-landed `_skip_unless_engine_available` (same mechanism and same chokepoint X-140 authorized for C12/C14). C15's own ASSERTIONS still hold there and were re-measured directly: occupied target `dry 5 / real 5` with the seeded bytes untouched, unwritable destination `dry 1 / real 1` — only the instrument fails. AC5's “no skip list” is preserved because BOTH properties hold: engine hidden → the two `convert` rows skip with a reason naming the engine (6 engine-gated skips in the module, up from 4); engine present → they still RUN and pass (`scripts/assert_skips.py --expect-zero` clean over 424 testcases). Full suite: engines-present 1816 passed / 31 skipped / 0 failed; engines-hidden 1789 passed / 58 skipped / **0 failed**, from an inherited 3 failed / 1788 passed / 56 skipped.

## [PDF-15] fix: declare `convert`'s genuine engine precondition so C12/C14 skip visibly instead of failing — 2026-08-30
- CI run `33345319975` failed 9/17: `test_c12_json_on_a_pipe_by_default[convert]` and three `test_c14_output_flag_matrix[convert:--output|--out-dir|--name]` cases asserted `returncode == 0` and got `3` (`ENGINE_MISSING`) in all eight `test (3.x, ubuntu|macos)` legs plus `without-engines`. Exit 3 was CORRECT there — those runners have no `soffice`, and unlike `ocr` (whose `--skip-text-pages` path never demands `tesseract`), `convert`'s whole job IS the conversion; it has no engine-free path (`tests/registry.py`'s own PDF-15 section note said so at landing, and reported the shared, un-markable harness as a known gap out of that spec's edit scope). `engines-present` passing on the identical rows was the proof the verb itself was never wrong.
- Reproduced locally first, as required: with `soffice` on `PATH`, all four rows pass (the trap — this host has LibreOffice installed); with `PDF_TOOLKIT_TEST_HIDE_ENGINES=soffice` (PDF-06's PATH-hiding shim, never a shadowing shim), the identical four rows fail with the identical `assert 3 == 0`.
- Fixed by adding `Invocation.requires_engine: str | None` (`tests/registry.py`, beside `destructive_build`) — a port name from `pdf_toolkit.ports.PORTS`, declared once on `INVOCATIONS["convert"]` as `"OfficeConverter"`. `tests/test_cli_contract.py::_skip_unless_engine_available` reads it (resolved through the same `pdf_toolkit.ports.resolve()` chokepoint `doctor` and `conftest.py`'s own `@pytest.mark.requires` marker use — never an independent `shutil.which`, never an env var, never a platform check) and calls `pytest.skip()` naming the missing engine when unavailable — never a silent pass. One declaration serves both consumers: C12 (`INVOCATIONS[verb.name]` directly) and C14's honoured side (which builds its argv from the separate, per-flag `OUTPUT_FLAG_INVOCATIONS` table but still reads the same per-verb `INVOCATIONS[verb.name].requires_engine`, since the precondition is a property of the verb, not of any one flag row).
- Verified both directions locally: engine hidden → the same four cases now report `SKIPPED ... OfficeConverter engine unavailable; install with: apt install libreoffice` (0 failures); engine present → all 16 `convert` contract cases (including the four) still `PASSED`, proving the rows RUN when the engine resolves rather than vanishing unconditionally — exactly what keeps `engines-present`'s own `scripts/assert_skips.py --expect-zero` meaningful. `make test` (full suite, engines present on this host): 1814 passed, 31 skipped (all pre-existing: `PDF_TOOLKIT_SAMPLES_DIR` unset arms and one already-reported, out-of-scope `pdfium_raster.py` rotation defect) — no regressions.
- `src/` is untouched by this commit; only `tests/registry.py` and `tests/test_cli_contract.py` changed.

## [PDF-15] feat: `ocr` + `convert` — the two system-binary verbs — 2026-08-30
- `ocr` rasterizes each selected page (`RasterEngine`), drives `tesseract` for a text-only invisible layer (`-c textonly_pdf=1`, spawned through the one sanctioned chokepoint, never `pytesseract`'s own runner), and overlays it on the ORIGINAL page object via `StructureEngine.composite_layer` — the page's image XObject is byte-identical before and after (AC3), proven with `tests/helpers/pdfstream.py`, never `tests/pagetree.py::page_tree_digest` (B-083: a pypdf rewrite is not byte-identical at the whole-document level even for a pure pass-through). `convert` drives headless LibreOffice into a private per-invocation scratch space (isolated `-env:UserInstallation` profile + outdir), reads the result back, and writes it through `AtomicWriter` — LibreOffice never touches the user's destination directly, and an exit 0 with no output file is treated as a failure (D6), not a success.
- Design §D4's one genuine gap — `StructureEngine.composite_layer` takes no transform, so the OCR layer must already be sized and rotated to the page's own unrotated space before crossing the port — is closed with route (a): the geometry correction lives inside `adapters/tesseract_ocr.py::_normalize_layer_geometry` (measures tesseract's own emitted box back rather than trusting it, then applies one composed scale+rotate+translate transform derived from the PDF `/Rotate` convention). `ports/structure.py` and `adapters/pypdf_structure.py` are untouched by this commit (`git diff --numstat` on both: zero lines).
- The OCR engine is demanded LAZILY: `ocr --skip-text-pages` over a selection that is entirely skip-eligible never calls `require_ocr()` at all, so it succeeds without tesseract installed — this is what the C1-C16 generic contract population's own registered `ocr` rows exploit to stay engine-independent in both CI configurations (`tests/registry.py`'s own PDF-15 section explains why). `convert` has no equivalent (its whole job is the conversion), and its own C12/C14 "declared flag honoured" rows genuinely need `soffice` — a structural gap in the shared, un-markable `test_cli_contract.py` harness this spec may not edit; reported rather than papered over (see this spec's Implementation Log).
- New `safety.atomic.ScratchDir`: a per-invocation scratch directory for an external engine's own working files (never a product destination), living inside the ONE file `tests/test_import_boundaries.py` Section 1 exempts from the write-chokepoint walk — additive, no allowlist entry, no second raw-mutation site. `_plan_filesystem` in both `ops/ocr.py` and `ops/office.py` is widened beyond `compress`'s own donor shape to check destination writability in BOTH modes (not only under `--dry-run`) for the single-target case, so a run that is going to be refused on filesystem grounds never demands an absent engine first — `ensure_destination_writable`'s own docstring states the rule directly ("checked at plan time, before an engine runs"). `require_ocr()`/`require_office()` are narrowed from the bare `Adapter` to `OcrEngine`/`OfficeConverter` via `cast`, mirroring `require_raster()`'s own precedent.
- **Known, reported gap (BLOCKED, out of scope):** AC7 (a genuinely rotated page) is `pytest.mark.skip`'d. Live-verified: `RasterEngine.render_page` (`adapters/pdfium_raster.py`, PDF-09, explicitly off-limits to this spec) double-applies `/Rotate` for 90°/270° pages — `pdfium.PdfPage.render()` already auto-applies the page's own `/Rotate` internally, and the adapter's `_render()` passes `rotation=page.get_rotation()` on top, a second application. Net effect for `/Rotate 90`: dims wrongly stay unswapped and content renders 180° from correct; for `/Rotate 180` the double-application cancels out, which is exactly why no earlier spec caught it — PDF-09's own rotation test only asserts an aspect-ratio class against a fixture that itself renders blank under inspection. This spec's own geometry-normalisation is implemented against the documented, intended contract and is not itself in question.

## [B-076] fix: `--in-place` silently dropped `-O`/`--out-dir`/`--name` and exited 0 — 2026-08-30
- All **eleven** structurally-eligible verbs (`compress`, `repair`, `linearize`, `encrypt`, `decrypt`, `delete`, `rotate`, `reorder`, `meta set`, `watermark`, `stamp` — every module declaring `--in-place` under OR-3 alongside at least one of `--output`/`--out-dir`/`--name`) silently let `--in-place` win: the input was mutated, the named destination was never written, and the run exited 0 — B-035's own defect class surviving *inside* the mechanism (`cli/common.py`'s OR-3 consumption check) built to end it. Re-measured directly against every one of the eleven with operands built via the product's own `create`/`encrypt` (not the pre-existing corpus fixtures — the same instrument gap invalidated three earlier, narrower scopes reported on this row): confirmed reproducing on **all eleven**, not four. `encrypt` needs `--no-backup` (or `-y`) alongside `--in-place -O` to get past its own PDF-13 plaintext-`.bak` refusal (exit 5) far enough to observe the same silent drop underneath it — the earlier scopes that read `encrypt` as immune had not added it.
- The OR-3 consumption check (`_check_output_flag_consumption`, `cli/common.py`) is one-dimensional (verb → flag SET) and cannot see this: both flags sit inside every one of the eleven verbs' own declared `consumes` sets, so the matrix reads the pair as *honoured*. This is a conflict BETWEEN two declared flags, a dimension that check has no vocabulary for. Fixed with ONE new central check, `_check_in_place_output_conflict`, called from `validate_config` immediately beside `_check_output_flag_consumption` — never a per-verb fix, which would need eleven correct edits (twelve, counting PDF-15's incoming `ocr`) and leave the next author to rediscover the gap. Exit 2, naming every conflicting flag, e.g. `compress: --in-place is mutually exclusive with --output (--in-place would mutate the input and the destination would never be written)`.
- Per B-073, no test pins today's exit-0-and-silently-drop behaviour anywhere — only the new refusal. `tests/test_cli_contract.py` gains C16, derived generically off the live registry (`consumes` intersection, no hard-coded verb list) exactly like C14, so a future verb declaring both sides (PDF-15's `ocr`) is covered the day it lands, zero action from its author. Two instrument controls prove the probe is not blind: `compress -O <path>` alone still writes its target, and an undeclared flag (`info --in-place`) still exits 2 through OR-3's own path, unshadowed by the new check.
- No product code outside `cli/common.py` changed; the eleven verbs' own `if in_place: ... elif output: ...` precedence in `ops/optimize.py`/`ops/crypto.py`/`ops/pages.py`/`ops/metadata.py`/`ops/overlay.py` is now provably unreachable with both flags given, but is left in place as the correct single-flag resolution.

## [B-079] fix: the bulk-destructive confirmation gate was unwired on five verbs — 2026-08-30
- `compress`/`repair`/`linearize`/`encrypt`/`decrypt` never called `safety/confirm.py::require_confirmation`, unlike the other 8 mutating verbs (`merge`/`compose`/`delete`/`reorder`/`rotate`/`stamp`/`watermark`/`meta set`). `compress` is multi-input and was live-reachable: `compress a.pdf b.pdf --in-place </dev/null` exited **0** and mutated both inputs, unconfirmed, against the control `delete a.pdf b.pdf --pages 1 --in-place </dev/null` at exit **5**, mutating neither. `repair`/`linearize`/`encrypt`/`decrypt` each take a single `{PDF}` argument, so the gap there was **latent** (a second operand is refused at exit 2 by arity before the gate could ever be consulted), not exposed — PDF-15's `ocr` is a stated future candidate for multi-input.
- Wired all five, mirroring `cmd_delete.py`/`cmd_rotate.py`'s own call site exactly: `require_confirmation(config.safety, input_count=<REAL resolved count>, in_place=True, rerun_hint=build_rerun_hint())`, guarded by `not config.dry_run and config.in_place`. `compress` passes `len(sources)`; the other four pass `1` (their arity's own real count, same as `cmd_meta_set.py`'s existing precedent — never a literal chosen independently of arity).
- `tests/registry.py::Invocation` gained an optional `destructive_build` field so C13 (`tests/test_cli_contract.py`) can seed a genuinely bulk, `--in-place` invocation for `compress` without perturbing the single-input `-O` shape every OTHER check (C1/C9/C10/C11/C12/C15) already depends on for that same verb. `compress` is now `destructive=True` — the FIRST non-empty case `DESTRUCTIVE`/C13 has ever had (PDF-06 through PDF-14 left it empty, which is exactly why this gate went unwired without the suite ever noticing: `test_cli_contract.py:248` emitted `got empty parameter set for (verb)`). `test_c13_population_is_non_empty` is the anti-lapse guard against a silent regression back to zero, and C13's own assertions now check mutation state (hash before/after), not just exit codes, directly proving the red/green pair: refused → neither input mutated; confirmed (`-y`) → both mutated.
- `repair`/`linearize`/`encrypt`/`decrypt` stay `destructive=False` (their arity keeps the gap latent), each documented in its own module docstring.

## [B-090] fix: drop the un-failable `|| true` the stale-lock check introduced — 2026-08-30
- `43e6061` landed the `make cover` concurrency guard but its stale-lock branch read `holder="$$(cat "$$lock/pid" 2>/dev/null || true)"`, which matches `tests/test_cli_spine.py::test_no_makefile_recipe_degrades_silently`'s own predicate (`\|\|\s*true`, or a leading tab-hyphen) — a guard-building commit rejected by the guard that forbids un-failable guards. CI run `33337802941` failed 8/17 (`without-engines` plus all eight `test (3.x, ubuntu|macos)` legs).
- Dropped `|| true`, kept `2>/dev/null`: `Makefile:9` sets `SHELL := /bin/bash` with no `.SHELLFLAGS`, so recipes run under make's default `-c`, not `-ec` — a failing `cat` inside this assignment, which is not the last command in its `if` chain, cannot abort the recipe, so the bare form is safe and the `|| true` was never load-bearing.
- Verified the guard still discriminates and still works, not just that the offending line is gone: the test's own regex returns 0 offenders against the current `Makefile` (1 at `43e6061`, 0 at its parent `cd33ced` — a control, not a guess), and `uv run pytest tests/test_cli_spine.py -k "degrades_silently or documents_exactly"` passes locally. Re-ran both arms of the guard itself against a stand-in Makefile carrying the identical, unmodified recipe body (only the trailing `uv run pytest --cov...` stubbed out, to stay cheap per the brief — never the real ~8-minute `make cover`): a lock held by a genuinely live pid still refuses a second invocation (non-zero exit, CONCURRENCY GUARD message, holder pid named); a lock whose recorded pid is dead — the exact branch this edit's `cat` sits in — still clears the stale lock, prints the STALE message, and proceeds past the guard.
- No product code changed; `src/pdf_toolkit/**` is untouched by this commit.

## [B-090] fix: `make ci` had no concurrency guard and manufactured PHANTOM REDS — 2026-08-30
- Two independently-controlled `make ci`/`pytest --cov` processes against one checkout raced on the single absolute `COVERAGE_FILE` `cover` pins on purpose (subprocess-measured CLI children need it next to the repo root's own data file, never inside a purity-snapshot root — see `[tool.coverage.run]` in `pyproject.toml`) and produced `make: *** [Makefile:44: cover] Error 1` while pytest itself reported a full, clean pass — a `.coverage` race, not a code defect, but indistinguishable from one without a guard.
- Added an `mkdir`-based concurrency guard to `cover` only (not `ci`): `mkdir` is atomic on every POSIX filesystem and needs no new dependency, unlike `flock(1)`, which is util-linux and absent on the `macos-14` runners this project's CI matrix uses. Guarding `cover` — the one target that actually writes `COVERAGE_FILE` — lets `ci` inherit the guard through its existing dependency on `cover` instead of self-deadlocking against its own prerequisite.
- A refused invocation fails within about a second with a message that says plainly it is a concurrency refusal and not a test failure, and names the holding PID. The lock is released on every exit path via `trap ... EXIT INT TERM`, including a failing guarded run and Ctrl-C. A lock left behind naming a PID that is no longer running is detected and cleared automatically on the next invocation; `make clean` also removes it, and `.make-cover.lock/` is now gitignored.
- CI itself never invokes `make cover` or `make ci`: `.github/workflows/ci.yml`'s `engines-present` job runs `uv run pytest --cov=... --cov-fail-under=85` directly, and every other job runs a single non-`cover` Make target, each in its own isolated GitHub Actions checkout. The guard therefore cannot make any of the 17 CI job runs go red on its own account — verified by reading the workflow rather than assumed.
- Proved with a stand-in Makefile reusing the identical guard logic against a cheap job (not the real 8-minute suite, per the brief): a genuine concurrent holder gets a second invocation refused (exit 2, concurrency-refusal message, holder PID named); an uncontended run completes and leaves no lock; a guarded job that itself fails still releases the lock and the very next invocation is admitted; a `SIGINT` sent to a guarded run's process group also releases the lock. No product code changed; `src/pdf_toolkit/**` is untouched by this commit.

## [B-088] fix: restore the changelog entry silently overwritten at `33bf481` — 2026-08-30
- `33bf481` (`[B-068] fix: --password-file's refusal echoed the given value...`) replaced the entry `73f6722` had written at the anchor instead of prepending above it, silently dropping the heading `## [PDF-13] fix: wait for /proc to show the child's argv before reading it — 2026-08-30` from the changelog (its body bullets survived verbatim, incidentally duplicated inside the `[B-068]` entry, but the heading itself — and the entry's existence as its own record — was gone). Recovered verbatim from `git show 73f6722:changelog.md` and re-inserted in chronological order, directly above the `[B-068]` entry that displaced it (73f6722 is 33bf481's own git parent).
- A forward-fix, not a history rewrite: the entry above and every trailer already on `origin/main` are untouched; this entry is prepended above them, per the file's own rule 1.

## [PDF-14] fix: add the missing `meta get` golden (AC18/Scope > Tests) — 2026-08-30
- The initial landing implemented and tested every acceptance criterion but
  never added the `tests/golden/meta_get.json` golden file the spec's own
  Scope > Tests row and AC18 both name explicitly. Added
  `tests/unit/test_metadata.py::test_ac18_the_meta_get_golden`, built from
  the **generated** `metadata_typed` corpus fixture only (never a sample,
  per `tests/golden/README.md`'s own rule) via `cli/cmd_meta_get.build_
  payload`, with `path` canonicalised to the bare filename before comparison
  (mirrors `tests/unit/test_textract.py::_canonical`'s `_PATH_KEYS`
  treatment — the raw value carries the session's own `tmp_path` and would
  otherwise make the golden un-reviewable noise). Regenerated with
  `--update-golden`, diff reviewed (11 keys, all generated-corpus content,
  nothing from a sample), then re-run without the flag to confirm the
  comparison itself passes.
- No product code changed; `src/pdf_toolkit/**` is untouched by this commit.

## [PDF-14] feat: `meta get`/`meta set` over /Info + XMP; `watermark`/`stamp` via the compositing port — 2026-08-30
- `meta` is the CLI's first grouping parent — `meta get`/`meta set` each live
  in their own `cli/cmd_meta_{get,set}.py` module (D8.1), with `cli/cmd_meta.py`
  holding only the sub-`Typer`. `watermark`/`stamp` are ordinary top-level
  verbs. Registered on the live tree via `app.add_typer(cmd_meta.meta_app)`.
  `cli/common.py::_verb_name` now walks the `ctx.parent` chain so an OR-3
  refusal on a grouped verb names `"meta set"`, not `"set"` — verified
  unchanged for every pre-existing top-level verb — and
  `tests/registry.py::run_cli`'s first argument is tokenized on whitespace,
  so `run_cli(verb.name, ...)` (`test_cli_contract.py`'s own convention,
  unedited) reaches a two-word verb correctly.
- `meta get` reports the document information dictionary and the XMP packet
  SIDE BY SIDE and states a disagreement rather than resolving it
  (`MetadataReport`, one new model per `models.py`'s Scope row). `meta set`
  writes/clears `--title`/`--author`/`--subject`/`--keywords`/`--creator`/
  `--clear-producer`/`--clear-all`, syncing XMP only when a packet already
  exists and creating none where one did not — `adapters/pypdf_structure.py`'s
  `write_metadata` uses `PdfWriter(clone_from=reader)` plus direct
  `/Info`-dictionary manipulation (documented deviation, D2.3) so every
  untouched key keeps its ORIGINAL PdfObject type (a `/Trapped` name object
  round-trips as a name object, never stringified).
- `watermark`/`stamp` composite an overlay/underlay layer onto the selected
  pages through a new `StructureEngine.composite_layer` port method
  (Design D4.1): it mutates an already-open document's reader pages IN PLACE,
  and the caller reuses the SAME `new_writer()`/`append_pages()`/`write()`
  path `rotate` already established — `set_rotation` stamps the WRITER's
  pages post-append, `composite_layer` stamps the READER's pages pre-append.
  `watermark`'s text layer is a new `ComposeEngine.render_text_layer` method
  on the existing `reportlab_compose` adapter (single-page, rotated,
  alpha-blended — distinct from `render_text`'s paginated-document shape).
  Both new port methods are selected BY CAPABILITY (`"text-layer"`,
  `"composite"`, X-76) — `require_composite()` mirrors `require_image_pass()`.
  Deviation from the spec's Scope row, recorded rather than silently
  exceeded: `meta get`/`meta set` needed their OWN two new `StructureEngine`
  methods (`read_metadata`/`write_metadata`) beyond the two the Scope table
  named — there is no existing method that reports XMP-property-level or
  residual-surface facts without widening the pinned `DocumentInfo` model or
  letting `ops/` hold a pypdf object.
- Page-range scoping is consumed, never reimplemented (`ops.pagerange.parse`,
  called exactly once per run for each verb). The dry-run gate follows the
  LANDED convention every other producing verb already uses
  (`safety.atomic.plan_output_set` + the item's own `exit_code =
  plan.would_exit`): a `--dry-run` over an occupied `-O` target exits **5**,
  matching `test_cli_contract.py::test_c15_dry_run_predicts_an_occupied_
  target_refusal` — NOT the 0 `decision.md` §8 X-67's prose predicted before
  that convention landed (B-025, deliberately unmet per the spec's own R1
  ruling). Every `--in-place` path calls `safety.confirm.require_confirmation`
  (mirroring `cmd_rotate.py` exactly), so none of the three new verbs joins
  the five-verb confirmation blind spot (B-079).
- Seven new deterministic corpus fixtures (`tests/corpus.py`): a `/Trapped`-
  and custom-key-bearing `metadata_typed`; an agreeing `xmp_bearing`; a
  disagreeing `xmp_disagreement`; a `residual_surfaces` fixture carrying
  page-level XMP + document-level `/PieceInfo`; `no_contents_page`/
  `empty_contents_page` for the two content-stream edge cases; and
  `stamp_source`, carrying the `STAMP_MARKER` ASCII marker in a base-14 font
  for the content-stream-order proof. All byte-identical across two builds.
- Tests: `tests/unit/test_metadata.py`, `tests/unit/test_overlay.py`,
  `tests/unit/test_meta_group.py`, `tests/integration/
  test_overlay_preservation.py`, plus a PDF-14 section appended to
  `tests/test_samples.py` (three `@samples` arms over
  `catalogo_arquitectura_2017_2023_0.pdf`, run through `make samples-gate`).
  Registry additions only — `tests/test_cli_contract.py` itself is unedited
  (`tests/registry.py::INVOCATIONS`/`OUTPUT_FLAG_INVOCATIONS` carry the four
  new rows; `tests/unit/test_registry.py`'s pinned verb/classification sets
  extended from twenty to twenty-four).
- Known, disclosed finding: `composite_layer` merges onto a document's reader
  pages before they are attached to a writer, which pypdf 6.16.2 accepts but
  flags with a `DeprecationWarning` slated for removal in pypdf 7.0.0 — the
  spec's own Design §D4.1 signature (`document: OpenStructureDocument`, not
  a writer) makes the alternative (attach-then-merge) a different method
  shape; not a defect against the pinned version, filed for the PM.

## [B-078] fix: `open_document` now raises `AuthError` on a user-password-protected input — 2026-08-30
- `StructureEngine.open_document`'s own Protocol docstring documented `AuthError:
  Exit 6` for an encrypted input; `PypdfOpenDocument.__enter__` never implemented
  it. pypdf raises `FileNotDecryptedError` LAZILY — not at `PdfReader()`
  construction, but on the first `.pages` access, which sat outside the
  construction-only `try`/`except (PdfReadError, OSError, ValueError)` block. A
  user-password-protected input therefore surfaced an unhandled traceback and
  exit 1 through every consumer of `open_document` — `merge`, `split`,
  `extract`, `delete`, `rotate`, `reorder`, `rasterize`, `text`, `tables`, and
  `compress --pages`. Pre-existing at `33bf481`, not a regression; left
  unrepaired by PDF-08 on purpose (X-127: `PypdfOpenDocument` belongs to
  neither PDF-08 nor PDF-14) and pinned by a strict xfail
  (`test_ac23_an_encrypted_input_surfaces_exit_6_without_a_traceback`) until now.
- Fixed in the ONE place every consumer shares: `__enter__` now forces the
  first `.pages` access inside its own guard, immediately after `PdfReader()`
  succeeds, and a new `except FileNotDecryptedError` (ahead of the existing,
  now-widened `except PdfReadError`) raises `AuthError` instead of letting the
  exception escape. `page_count`/`top_level_outline` are unchanged — every
  consumer above is fixed by one edit rather than six.
- The message follows the house `_PASSWORD_HINT`/"decrypt" precedent
  (`adapters/pikepdf_structure.py`'s `compress`/`repair`/`linearize` refusals),
  duplicated locally as this adapter's own `_PASSWORD_HINT` rather than
  imported across the sibling adapter boundary: `"a password is required to
  open this document; supply one with --password-file PATH ..., or run
  'pdftoolkit decrypt' first"`. `path=` names the document, never the
  password; `redacted` is not set (B-068's second-order hazard: a redacted
  path hides a useful, non-secret value).
- `StructureEngine` and `PypdfStructureAdapter` were not touched (PDF-14's
  X-127 reserved anchors). No new runtime dependency; no forbidden-license
  name reachable.
- The `test_ac23_...` strict xfail and its dead `NOTE ON THE WORDING` comment
  are removed from `tests/integration/test_pages_cli.py`; the assertion now
  stands as a normal passing test, verified as a real subprocess for `merge`,
  `split`, `extract`, `delete`, `rotate`, `reorder` against the
  `encrypted_aes256` corpus fixture (a genuine user password, per
  `tests/corpus.py`) before and after the fix.

## [PDF-08] fix: two CI-only defects the local gate could not see — 2026-08-30
- `Path.stem` is not stable across supported Pythons, and AC37's containment
  test depended on it. **CPython 3.14 changed `PurePath.suffix`/`stem` so a
  leading dot counts as part of the stem** (hidden-file handling), so a file
  named `...pdf` has the stem `..` on 3.11-3.13 and `...pdf` on 3.14. The
  traversal-carrying-stem fixture therefore stopped carrying a traversal, and
  the two AC37 arms built on it failed on both 3.14 legs. Caught by the arm's
  own premise assertion (`this test's own premise no longer holds`) rather than
  by a silent pass, which is the only reason it was diagnosable from the log.
- Fixed by making the property portable instead of the fixture cleverer. A new
  arm drives the same post-substitution tier on **every** supported version: a
  200-character stem with a `{stem}-{stem}.{ext}` template renders a 405-byte
  component, where the stem and the template are each individually legal and
  only the substituted result is not. The traversal-shaped arm is kept and now
  skips with a reason naming the CPython change on 3.14+, and the symlink arm's
  refusing half uses the portable vector, so containment stays asserted
  everywhere rather than on three versions out of four. Verified by running the
  suites under 3.11-3.14 rather than reasoning about them.
- The `engines-present` job failed for an unrelated reason: `scripts/
  assert_skips.py` classifies a skip as engine-gated by a regex over its
  **reason**, pytest records an xfail as `<skipped type="pytest.xfail">` in the
  JUnit report, and the AC23 xfail's reason named the structure port by its
  class name. A deliberate xfail was therefore counted as a test that should
  have exercised a real engine and silently did not. Worked around by wording
  that reason without the matched terms, with the constraint recorded inline;
  the real fix — teaching that script to exclude `type="pytest.xfail"` — is a
  shared CI gate outside this spec's scope and is reported rather than made.
- Forward-fix commits rather than an amend: `1c4684c` is already on
  `origin/main`, and this cycle does not rewrite history.

## [PDF-08] extract / delete / rotate / reorder — 2026-08-30
- Added the four page-addressed structure verbs over one shared selection path.
  The set-vs-ordered distinction is enforced in code rather than left to each
  verb's author: `extract`/`reorder` thread `ordered=True` into
  `ops/pagerange.py::parse` and consume `PageRange.indices`, so
  `extract --pages '1,1,3'` yields three pages in that order;
  `delete`/`rotate` thread `ordered=False` and consume `PageRange.as_set()`, so
  `delete --pages '1,1,3'` equals `delete --pages '1,3'` and a page named twice
  is rotated once. `reorder` is total — pages the selection does not name are
  appended in ascending original order, so an exclusion moves a page to the
  back rather than deleting it, and the verb can honour `--in-place` without
  being able to destroy a document. `delete` refuses (exit 5) to produce a
  zero-page PDF; an empty-but-valid selection stays exit 4, and the two are
  pinned apart in both the outcome and the `--dry-run` prediction.
- Extended the `StructureWriter` port with one method, `set_rotation(index,
  degrees)`, implemented on `PypdfStructureWriter` alone
  (`adapters/pikepdf_structure.py` is untouched — it implements neither
  `new_writer` nor `open_document`). There was no write-side rotation anywhere
  in the product before this. All arithmetic stays in the framework-free ops
  layer: relative-by-default, `--absolute`, and `% 360` normalization live in
  `ops/pages.normalize_rotation`, so the adapter only stamps a value it is
  handed and the rules are unit-testable with no engine present. Pages the
  selection does not name get no call at all, which is what keeps an absent
  `/Rotate` key absent rather than stamped with an explicit 0.
- This is the first spec where a user can reach `--in-place`, `--no-backup`,
  the `.bak` sidecar or the non-TTY `-y` gate against a real verb; PDF-04 built
  all of them against no callers. Each is now exercised end to end: the `.bak`
  is proven to carry the pre-run bytes by hash, a bulk `--in-place` run fails
  closed on a non-terminal and hands back the exact re-run command, and an
  existing `.bak` without `--force` refuses while leaving both the input and
  the sidecar byte-identical.
- Known limitation, reported rather than repaired: an encrypted input produces
  an unhandled traceback and exit 1 instead of the exit 6 that
  `StructureEngine.open_document`'s own contract documents. pypdf raises
  lazily, on the first page read, outside the `except` block in
  `PypdfOpenDocument.__enter__`. Pre-existing and not introduced here —
  `merge` and `split` reproduce it identically at `33bf481`. Password handling
  is this spec's declared scope-out, so the criterion is carried as a strict
  `xfail` holding the correct assertion, which turns red the day the shared
  fix lands rather than pinning today's behaviour.
- `--dry-run` predicts both tiers: the filesystem tier through the shared
  `plan_output_set`/`AtomicWriter` planners, and the selection tier so that
  `delete --pages all --dry-run` reports the zero-page refusal instead of
  discovering it on the real run. Purity is asserted with both halves — the
  tree is unchanged AND the run produced a non-trivial plan — because a dry run
  that does nothing is trivially pure.

## [PDF-13] fix: wait for /proc to show the child's argv before reading it — 2026-08-30
- The AC7 argv proof read `/proc/<pid>/cmdline` as soon as the read
  succeeded. The kernel exposes `/proc/<pid>` the moment the child is
  forked, **before** `execve` has installed the new argv, so the read could
  return an empty buffer — and an empty buffer trivially "does not contain
  the password", which is a green assertion proving nothing. Caught by CI on
  `test (3.11, ubuntu-latest)` (run `33315489842`, 17 jobs, that one job
  only); the local gate and every macos-14 leg had passed.
- The poll now waits for the argv this test itself passed to be visible, and
  re-asserts the process is still blocked at the moment the buffers were
  read, so the measurement is of a live process rather than of a corpse's
  leftovers. Verified 20 consecutive runs under CPU load, zero failures.
- A forward-fix commit rather than an amend: the operator's instruction is
  never to rewrite history (`decision.md` §8 X-118), and `ff512ce` is already
  on `origin/main`.

## [B-068] fix: `--password-file`'s refusal echoed the given value on stdout/stderr — 2026-08-30
- `--password-file`'s shape check (`cli/common.py`, the shared option layer
  every verb goes through) built its own `UsageError(path=value)` instead of
  routing through the never-echo constructor `--owner-password-file` /
  `--user-password-file` already used — the value it refused reached the
  structured error envelope's `path` field, in every output shape (default,
  `-o json`, `-o ndjson`, `-o table`, `--quiet`, `-vv`; `-o table` puts it on
  stderr, the other five on stdout). PDF-13's AC1 (`PLAN.md` §5.7) as
  extended 2026-08-30 names `--password-file` explicitly; pre-existing at
  `c870e73`, not a regression.
- `PdfToolkitError.to_dict()` now honours `redacted` (it was a fully dead
  flag: five write sites, zero reads) at the single chokepoint every
  renderer consumes — a refusal built `redacted=True` with a populated
  `path` renders `path` as `pdf_toolkit.secret.REDACTED` instead of the
  value, so a future password-bearing flag cannot leak this way again.
  `--password-file`'s own check now calls the shared `not_a_readable_file`
  constructor directly, and `PASSWORD_FILE_FLAGS` (companion to
  `REFUSED_PASSWORD_FLAGS`) is the completeness registry a new test ties to
  every verb's rendered `--help`.
- Found and fixed in the same pass: `permissions`' own "password required"
  `AuthError` (`ops/crypto.py`) carried `redacted=True` alongside a
  `path=str(source)` that names the *document*, not a password — harmless
  while `redacted` was dead code, but would have started hiding a useful,
  non-secret document path as `<redacted>` the moment the flag gained
  effect. Removed; the document path is shown again, as it always was.
- The AC7 argv proof read `/proc/<pid>/cmdline` as soon as the read
  succeeded. The kernel exposes `/proc/<pid>` the moment the child is
  forked, **before** `execve` has installed the new argv, so the read could
  return an empty buffer — and an empty buffer trivially "does not contain
  the password", which is a green assertion proving nothing. Caught by CI on
  `test (3.11, ubuntu-latest)` (run `33315489842`, 17 jobs, that one job
  only); the local gate and every macos-14 leg had passed.
- The poll now waits for the argv this test itself passed to be visible, and
  re-asserts the process is still blocked at the moment the buffers were
  read, so the measurement is of a live process rather than of a corpse's
  leftovers. Verified 20 consecutive runs under CPU load, zero failures.
- A forward-fix commit rather than an amend: the operator's instruction is
  never to rewrite history (`decision.md` §8 X-118), and `ff512ce` is already
  on `origin/main`.

## [PDF-13] encrypt / decrypt / permissions + password handling — 2026-08-30
- Added `encrypt` (AES-256 / revision 6 by default; RC4-128 only behind
  `--legacy`, which warns that it is broken and that metadata is left
  unencrypted), `decrypt` (an unencrypted document is exit 4 and writes
  nothing) and `permissions` (non-producing: it reports, so all four output
  flags exit 2). Every cryptographic operation is libqpdf's through
  `pikepdf`'s `robust-encryption` capability — no key derivation, no cipher
  and no password comparison is implemented in this repository, and no
  runtime dependency moved.
- A password is never accepted as a command-line value, and the inviting
  spelling no longer exists: `--password` (a shipped alias of
  `--password-file`), `--user-password` and `--owner-password` are hidden,
  refusing options that exit 2 with a message naming the file, environment
  and prompt paths. The harm — a value reaching shell history and
  world-readable `/proc` argv — happens before a tool could refuse, so the
  removal is preventive rather than post-hoc. Resolution is
  file/stdin → environment → TTY prompt → exit 6.
- Passwords travel as a `Secret` whose every rendering is `<redacted>`, which
  JSON and `pickle` refuse, and whose single accessor `reveal()` is confined
  by an AST walk to one adapter file. Four adversarial proofs, each with a
  positive control: absent from captured `-vv` stderr (which is asserted
  non-empty and carrying a real debug record), absent from `-o json` in raw
  bytes and in every string leaf and under `\uXXXX` escaping, absent from a
  forced traceback including the locals-capturing form, and absent from
  `/proc/<pid>/cmdline` read while the process is provably blocked on stdin.
  The environment channel is asserted to be readable and is documented as
  weaker than a file rather than implied safe.
- `--dry-run` predicts what it can and states what it cannot. Password
  *resolvability* is predicted (`would_exit: 6`) from existence alone, with
  no secret entering the process; password *correctness* deliberately is not,
  and the payload says so with `password_verified: false` — a preview must
  not become an oracle that distinguishes a right password from a wrong one
  inside a CI artifact.
- `encrypt --in-place` refuses (exit 5) unless given `--no-backup` or `-y`,
  because the `.bak` sidecar is a copy of the *original* and would leave
  plaintext beside the ciphertext. Permission bits are reported as the
  document grants them, not as they were requested: `accessibility` is always
  granted and `print-highres` also grants `print`, both measured against
  libqpdf and both documented as advisory — the bits are a request to a
  cooperating reader, never a lock.

## [PDF-12] compress + repair + linearize — 2026-08-30
- Added `compress` (`pikepdf`/libqpdf object streams + stream recompression,
  lossless by construction; opt-in `--images downsample|recompress` over
  Pillow, opt-in and never implied), `repair` (libqpdf's own recovery
  parser, warnings via `pikepdf.Pdf.get_warnings()` — never a `qpdf` CLI
  shell-out) and `linearize` (verified structurally before a byte reaches
  disk), over `StructureEngine` extended in place with three additive
  methods and one capability-selected sibling Protocol (`ImagePassEngine`)
  for the image pass — the registry stays the only adapter-selection seam.
  Ghostscript is the conventional one-call compressor and is AGPL-3.0+,
  excluded by `PLAN.md` §7.2; this is the replacement, not a workaround.
- `--lossless` is an enforced runtime guarantee (page count, every image
  XObject's structural facts, every `/DCTDecode` stream's raw bytes),
  checked before `AtomicWriter` ever opens — a violated guarantee writes
  nothing and exits 1, naming the failed check. `compress` reports a
  measurement, never a claim: `bytes_before`/`bytes_after` on every item, a
  non-shrinking run still exits 0 with a signed, non-positive percentage and
  a stderr warning. A mechanized honesty gate (`tests/test_honesty_claims.py`)
  fails the build on any comparative or superlative claim, anywhere.
- `compress`/`repair`/`linearize` are the product's first `--in-place`
  verbs; `cli/cmd_compress.py`, `cmd_repair.py` and `cmd_linearize.py`
  (one file per verb, not `cmd_optimize.py`, to keep OR-3's per-module
  output-flag declaration collision-free) each declare their own consumed
  output flags. `compress`/`repair`/`linearize` all satisfy contract row
  C15 (a `--dry-run` predicts the same exit code the real run produces)
  through the shared filesystem-tier planner, extending `[B-054]`'s pattern
  to the `-O`/`--in-place` destination shape for the first time alongside
  `--out-dir`.

## [PDF-11] text + tables — 2026-08-30
- Added `text` (pypdfium2 fast path; `--layout` via pdfplumber, one block per
  line with top-left-origin geometry) and `tables` (`--strategy lines|text`,
  `--format csv|json`), over one `TextEngine` port extended in place —
  `LayoutTextEngine` is a second Protocol in the same file, not a seventh port,
  so the licence claim still reads as six files. New frozen models `TextBlock`,
  `PageText`, `TableGrid`; new op layer `ops/textract.py`.
- Every result DECLARES the strategy and the engine that produced it, in
  `-o json`, on every `-o ndjson` line, and as a one-line banner in `-o table`
  (stdout when a destination was given, stderr when stdout is carrying the
  payload). `--layout` with the layout adapter unresolved exits **3** and never
  falls back. Table extraction is documented as a heuristic in `--help`, and no
  number claiming how sure the engine was is invented anywhere — enforced by a
  grep over the five source files and both goldens, not by review. A page that
  exists and yields nothing returns empty, exits **0** and warns; that is the
  before-state the later `ocr` verb's acceptance signal depends on.
- Block extraction uses pdfplumber's own `Page.extract_text_lines()` — present
  across the whole pinned `>=0.11.10,<0.12` range, so the spec's documented
  word-grouping fallback is deliberately NOT carried as unreachable code; its
  absence is reported as a coded exit-3 engine failure instead of an
  `AttributeError` traceback. Block ORDER is imposed by a stable sort on
  `(y, x)`, so `y` is non-decreasing on every page including rotated ones — a
  guarantee the tool makes rather than a property it hopes the engine has.
- Contract row `C15` found a real gap while this landed: `plan_output_set`
  deliberately skips the writability tier when there is no shared `--out-dir`,
  so a `-O` dry run predicted 0 where the real run exited 1. Closed by
  consulting BOTH shared primitives — the planner for the `--out-dir` tier and
  `AtomicWriter`'s own plan for the single-destination tier that `merge`,
  `compose` and `create` already predict through. No per-verb prediction logic
  and no per-verb exit-code logic was added; `--in-place` is refused by the OR-3
  declaration alone, and neither command module mentions it.
- Makefile: `make samples-gate` now encodes the `@samples` ordering ONCE
  (`decision.md` §8 X-115) — assert-no-stale-manifest, `samples-scratch`,
  the arm with the corpus present, the arm with it absent, `samples-check` —
  so no spec has to re-type the four steps that let B-046 propagate. Its
  unset arm asserts on junit COUNTS, failing on any pass and on zero collected
  tests, because an exit code cannot tell "all skipped" from "all passed".
  `make samples-scratch` now REFUSES over an existing manifest naming
  `make clean`, instead of silently overwriting the snapshot that
  `samples-check` compares against (X-108). `samples-gate` is deliberately not
  part of `make ci`: it needs the real-document corpus, which CI has not got.

## [B-055] widen the SIGTERM/SIGINT/SIGHUP teardown grace window and make its own test spawn-safe — 2026-08-30
- CI's `macos-14` leg (`test (3.13, macos-14)`) caught a real gap on the
  first push of the landed `[B-055]` entry below: stray `.pdftoolkit-*`
  temp files survived the run. `multiprocessing` defaults to `spawn` on
  macOS (and every platform from Python 3.14 on), so every worker
  cold-imports pypdfium2/Pillow/this package from scratch on start —
  `guarded_process_pool()`'s grace window widens from 2s to 6s in
  `ops/procpool.py` to give that cold start room to finish an in-flight
  `AtomicWriter` unwind before the SIGKILL deadline, instead of racing it.
- `tests/integration/test_rasterize_signals.py` sent its signal at the
  worst possible moment — the very first output file — which statistically
  catches other workers mid cold-import, uninterruptible C call included.
  Fixed by signalling once half the run's pages already exist instead, so
  the test's own timing no longer manufactures the race it was written to
  detect.
- The `guarded_process_pool()` docstring now states residue avoidance as
  best-effort under PLAN §12 R-07's own accepted class, not as a guarantee
  — the fix narrows the race, it does not eliminate the theoretical window
  inherent to signalling a cold-starting worker.

## [B-055] `rasterize`'s worker pool no longer survives SIGTERM/SIGINT/SIGHUP to the parent — 2026-08-30
- Fixed: `rasterize --threads N>1` left every render worker running (and
  writing) after a signal to the parent — `ProcessPoolExecutor.__exit__`'s
  `shutdown(wait=True)` blocks until already-running workers finish rather
  than signalling them, so a bare `shutdown()` in any combination was never
  a fix. Added `ops/procpool.py::guarded_process_pool()`, a drop-in
  `ProcessPoolExecutor` wrapper that actively SIGTERMs every known worker
  PID (via `executor._processes`, the only reachable handle), waits out a
  2s grace window for an in-flight `AtomicWriter` to unwind and discard its
  own temp file, then SIGKILLs stragglers and reaps them — before letting
  the parent die BY the signal (`SIG_DFL` + self-`kill`, `$?` = 128+signo,
  not `sys.exit`). `ProcessPoolExecutor` stays mandatory (X-104: real
  concurrent pdfium rendering corrupts the heap even with per-worker
  document isolation) — this is not a switch to threads.
- SIGTERM, SIGINT and SIGHUP all route through the one teardown routine.
  Measured directly: a bare `kill -INT <parent pid only>` on the unfixed
  code does NOT stop the job — "SIGINT is already clean" held only for an
  interactive Ctrl-C, which signals the whole foreground process group and
  kills workers by accident, not for a supervisor's single-process signal.
  SIGKILL to the parent remains uncatchable by definition; the one thing
  the child side can do about it, `PR_SET_PDEATHSIG(SIGKILL)` via `ctypes`
  in the worker initializer, is Linux-only and stated as such (no macOS
  coverage).
- The worker initializer also resets SIGINT/SIGHUP to `SIG_DFL` and
  installs a worker-local SIGTERM handler, closing the `fork`-inheritance
  hazard commit `26f4c79` already paid for once: a forked worker must never
  run the PARENT's own pool-shaped teardown handler.
- Added `tests/integration/test_rasterize_signals.py` — black-box, real
  `subprocess.Popen`/`os.kill` (parent PID only, never the group), proven
  start-method agnostic by construction (never touches multiprocessing
  internals) and seen RED on the unfixed code before being made GREEN.
  Added `tests/unit/test_procpool.py` for the underlying mechanics. R-08
  byte-identity (`--threads 1` vs `--threads 8`, sha256) re-verified after
  the change.

## [B-054] `--dry-run` predicts the filesystem-tier refusal for `--out-dir` verbs — 2026-08-30
- Fixed `split`/`rasterize`: `--dry-run` over an occupied `--out-dir` target,
  or over an unwritable `--out-dir`, now predicts the same exit code the real
  run produces (5 / 1) with a character-identical `would_refuse` payload,
  instead of entering cleanly and exiting 0 (QA `b43bb70cc3`).
- Added `safety/atomic.py::plan_output_set()` — the X-67 filesystem-tier
  planner, extended from one destination to a multi-target `--out-dir` run,
  run once, unconditionally, in both modes. `ensure_out_dir` is now private
  (`_ensure_out_dir`) and `plan_output_set` is its only caller, so a future
  `--out-dir` verb cannot reach the write chokepoint without also getting the
  prediction. `split`/`rasterize` each call it once, at the position their
  own real-run filesystem checks used to occupy.
- Added contract-harness arm `C15` (`tests/test_cli_contract.py`), driven off
  a widened structural "producing" derivation (`--output` OR `--out-dir`)
  that C11's own set is now read off, and generic target discovery via each
  verb's own `--dry-run -o json` plan rather than a per-verb table — so a
  future producing verb is covered the day it registers, with zero action
  from its author.
- Added focused unit coverage for `plan_output_set` (clean plan, occupied
  target, unwritable directory, and the non-existent-`--out-dir` case) in
  `tests/unit/test_atomic_writer.py`.

## [PDF-10] compose + create — 2026-08-30
- Added `src/pdf_toolkit/ops/compose.py` (framework-free ops for BOTH verbs) +
  `cli/cmd_compose.py` and `cli/cmd_create.py`. `compose` builds a PDF from
  images, one page per operand in argv order (duplicates allowed, no sorting,
  no globbing — a directory operand is exit 2 naming the shell as the fix);
  `create` renders one plain-text input, including `-` for standard input.
  Both declare `consumes=("--output",)` (OR-3), so `--out-dir`, `--name` and
  `--in-place` exit 2 **for free** from the shared option layer — neither
  command module contains a check for any of them, and neither names them.
  One operand with no explicit destination writes beside the input; two or
  more is exit 2 rather than a guess.
- **The lossless guarantee, asserted byte-for-byte rather than visually.** A
  baseline JPEG is stored as its own compressed bytes under a `/DCTDecode`
  filter with no decode and no re-encode; the chain is pinned to exactly
  `("/DCTDecode",)` by disabling reportlab's ASCII85 transport layer inside a
  save/restore context manager that spans every `drawImage` call (the toggle
  is read there, not at canvas construction) and restores on the exception
  path. Greyscale, RGB **and** CMYK pass through — reportlab emits the Adobe
  `/Decode [1 0 1 0 1 0 1 0]` inversion array, so the page renders correctly
  AND the bytes survive. A **progressive** JPEG is diverted to Flate with a
  per-file warning; the op sniffs the SOF marker itself, because the renderer
  sniffs nothing and would otherwise pass everything through silently.
- **Defect found on the 108-scan real-document corpus and fixed here:**
  `drawImage` de-duplicates image XObjects by a digest computed from the
  DECODED PIXELS when handed an `ImageReader`, so two inputs with identical
  pixels but different compressed bytes collapsed onto one XObject and the
  second page silently rendered the first file's bytes — with the filter chain
  still reading `/DCTDecode` and the item still claiming a passthrough.
  Handing the path itself to `drawImage` keys the cache on the filename;
  a repeated operand still, correctly, shares one XObject. Regression test
  reproduces it without the corpus and was proven to go red without the fix.
- `src/pdf_toolkit/ports/compose.py` gains `ComposeEngine.compose_images()` and
  `.render_text()` plus the `ImagePlacement`/`TextLayout`/`ComposeReport`
  carriers; both render into a **caller-supplied binary stream**, never a path,
  so every byte still reaches disk through `safety.AtomicWriter` and
  `tests/test_import_boundaries.py` stays green unedited. Geometry is placement
  — a CTM scale and a PDF clip path — never a pixel operation, so byte
  identity survives `--fit cover`.
- `src/pdf_toolkit/models.py` gains **one** optional field, `ItemResult.detail`
  (last, defaulted `None`, omitted from `to_dict()` when `None`) — the
  cycle-wide per-item-facts seam. `SCHEMA_VERSION` is unchanged and PDF-06's
  `info`/`doctor` goldens pass byte-identical, which is the proof the change is
  additive rather than a claim that it is. `compose` reports `embed`,
  `stream_bytes_identical`, `source_format`, `dpi_source` and `page` through it.

## [PDF-09] rasterize — PDF pages to images — 2026-08-30
- Added `src/pdf_toolkit/ops/raster.py` + `cli/cmd_rasterize.py`: `rasterize`
  renders every selected page of one or more PDFs to PNG/JPEG/TIFF/WEBP,
  `--dpi`/`--width` (mutually exclusive), `--quality` (lossy formats only),
  `--grayscale`, `--pages` (a **set** — PLAN §4.3, the product's first
  `--pages` verb). `consumes=("--out-dir", "--name")` (Design §D10) —
  `-O/--output` and `--in-place` exit 2 **for free** from the shared option
  layer; `cmd_rasterize.py` contains no check for either flag (AC23).
  Default `--name` template `{stem}-{page:04}.{ext}`.
- `src/pdf_toolkit/ports/raster.py` gains `RasterEngine.render_page()` and
  the `RenderedPage` carrier (in-memory pixels only — encoding/naming/write
  stay outside the port, D2), the interface PDF-15's `ocr` will reuse.
  `src/pdf_toolkit/adapters/pdfium_raster.py` fills in the render path PDF-05
  left probe-and-version-only: per-page open/render/close, rotation honoured
  via the page's own declared `/Rotate`, and a round()-vs-pdfium's-own-ceil()
  pixel-dimension correction (pypdfium2's `math.ceil(page_pt * scale)` can
  overshoot by one pixel on a scale like `300/72` that isn't exactly
  representable as an IEEE double — confirmed live, corrected by cropping
  down to the independently-computed exact target, never padding).
- **PLAN §12 R-08's per-worker-document-handle requirement, live-tested and
  the executor swapped as a result.** `_render_chunk` is a module-level,
  picklable-argument worker (proven by driving it through both a
  `ThreadPoolExecutor` and a `ProcessPoolExecutor` in the test suite).
  Live-testing found that real concurrent multi-threaded pdfium rendering —
  even with each thread opening and closing its own separate document,
  exactly as designed — reliably corrupts the process heap (`free(): invalid
  pointer`, `malloc(): unaligned tcache chunk detected`, `double free or
  corruption`, reproduced with 2 and with 8 concurrent threads on pypdfium2
  5.13.0). Production therefore dispatches `_render_chunk` through a
  `ProcessPoolExecutor`, not a `ThreadPoolExecutor` — a deviation from the
  spec's literal prose, in the direction the evidence pointed. `--threads 1`
  and `--threads 8` are proven byte-identical, same file order, over both a
  local 8-page fixture and a real 108-page scanned sample.
- Registered the sixth verb: the CLI-contract `C14` matrix moves 20→24
  automatically; `tests/unit/test_registry.py`'s three pins fire as designed
  (six-verb set, `rasterize` added to the mutating set — classified through
  the **existing** `_MAX_IMPORT_HOPS = 4`, never raised — and a new explicit
  page-addressing set) and are updated, never deleted.
- Added `tests/unit/test_raster.py` (ops/ports/adapter, in-process) and
  `tests/integration/test_rasterize_cli.py` (subprocess, flag contract,
  OR-3). Appended one `@pytest.mark.samples` section to `tests/test_samples.py`
  over a copy of `1888-10.pdf` (AC20): page 1 at `--dpi 72` renders the exact
  956×1435 px the sample's own point geometry predicts, and the thread-count
  identity proof re-run at `--pages 1-12` over the real scan.
- **Reported to the PM, not reconciled here (the spec is the carrier, not
  this commit):** AC9's "`--grayscale` reads back mode `L` for webp too" is
  physically unsatisfiable — WebP's own bitstream format has no
  single-channel pixel mode at all (Pillow 12.3.0's WebP encoder
  unconditionally converts any non-RGB(A/X) source to RGB before handing it
  to libwebp); the produced file is still perceptually grayscale (R≈G≈B
  throughout), which is what the test asserts instead. My own help text
  mentioning "Ghostscript" (prose, matching the spec's own D8 wording)
  tripped `tests/test_cli_spine.py`'s literal, case-insensitive,
  whole-source-tree forbidden-name scan — reworded to name no forbidden tool
  at all, even in prose.

## [PDF-07] merge + split — the OR-3 output-flag consumption mechanism — 2026-08-30
- **OR-3 (`decision.md` §0.5, Design §D12), built here before either verb
  existed.** `cli/common.py` gains `OUTPUT_FLAGS` (`--output`, `--out-dir`,
  `--name`, `--in-place`) and turns `global_options` into a decorator
  **factory** taking a required `consumes=` keyword; a bare `@global_options`
  now raises `TypeError` at import time, and an unknown flag name raises
  `ValueError` — both at import time, never at runtime. The central check
  (`_check_output_flag_consumption`) runs once, inside `validate_config()`, in
  a pinned order: `--output`/`--out-dir` mutual exclusion, then OR-3, then the
  existing shape checks. `version`/`doctor`/`info` are retrofitted to declare
  `consumes=()` — the proof the mechanism actually refuses. Closes **B-035**
  (QA fingerprint `54500b06e5`).
- Added `src/pdf_toolkit/ops/merge.py` and `cli/cmd_merge.py`: `merge`
  concatenates PDFs with per-input `path:range` selection (last-colon
  disambiguation, `:all` escape), `--bookmarks per-file|preserve|none`,
  fail-closed on any input (all inputs opened and resolved before the first
  byte is written), `consumes=("--output",)`.
- Added `src/pdf_toolkit/ops/split.py` and `cli/cmd_split.py`: `split` splits
  one PDF into many by `--every`, `--ranges` (comma is the part separator,
  not a union), `--each-page` or `--at-bookmarks` (including the documented
  no-outline-at-all case, exit 4), `--name` templating into `--out-dir`,
  plan-then-write (all parts resolved and no-clobber/collision-checked before
  the first write), `consumes=("--out-dir", "--name")`.
- Added `src/pdf_toolkit/safety/naming.py`: the `--name` template renderer
  (X-70 resolves Design §D6's branch — PDF-04 shipped only
  `ensure_within()`, no renderer, so this module is new, not consumed).
  Token substitution plus the binding containment invariant; calls
  `ensure_within()` on every rendered path before it ever reaches
  `AtomicWriter`. Owns only the substituted-value/255-byte exit-5 tier;
  `cli/common.py::_validate_name_template`'s exit-2 tier is untouched.
- `src/pdf_toolkit/safety/atomic.py`: added `AtomicWriter.stream` (the open
  file handle, never a path — D7's fix for `pypdf.PdfWriter.write(path)`
  opening its own handle and bypassing the tracked one) and `ensure_out_dir()`
  (the one confined `Path.mkdir` call site for `--out-dir`, gated on
  `--dry-run`, chokepoint-confined per the existing AST-walk boundary).
- `src/pdf_toolkit/safety/paths.py`: added `target_exists()`, a boolean
  existence predicate (dangling-symlink-aware) for the bulk-destructive
  confirmation gate to consult before deciding whether a run is destructive.
- `src/pdf_toolkit/ports/structure.py` + `adapters/pypdf_structure.py`: D10's
  minimal method set — `open_document()`/`OpenStructureDocument`
  (context-managed, page count, top-level outline as 1-based
  `(title, page)` pairs) and `new_writer()`/`StructureWriter`
  (`append_pages`, `add_outline_entry`, `import_outline`, `write`). No new
  adapter, no second engine.
- `src/pdf_toolkit/ops/pagerange.py`: added `is_valid_spec()` (syntax-only,
  no bounds check, no materialization — reuses the existing regex/keyword
  constants) and `ALL_PAGES_TOKEN`. **Neither is added to `__all__`** —
  `tests/test_pagerange.py::test_ac1_public_surface` pins that list exactly
  and that file is unedited (AC6/HC-3); both stay directly importable.
- `tests/registry.py` (PDF-06's, edited under the ruling's own
  authorization): `VerbSpec` gained `consumes`; `merge`/`split` rows added to
  `INVOCATIONS`; added `OUTPUT_FLAG_INVOCATIONS` for the three OR-3-honoured
  pairs.
- `tests/test_cli_contract.py` (PDF-06's): added `C14`, the OR-3 matrix arm —
  `discover_verbs()` × `OUTPUT_FLAGS`, no skip list — 5×4=20 cases at
  landing, 3 honoured / 17 exit-2. `C11` re-parameterized off the live
  `consumes` declaration instead of a hard-coded `-O` (`OUTPUT_CONSUMING_
  MUTATING`), so it no longer drives `-O` at `split`.
- `tests/unit/test_registry.py`: the two pins the tripwire hit (B-031, E12)
  updated to the explicit expected set, never deleted —
  `test_discover_verbs_finds_exactly_the_five_landed_verbs` and
  `test_the_expected_verbs_are_classified_mutating_or_not`
  (`merge`/`split` classify `is_mutating=True` through the **existing**
  `_MAX_IMPORT_HOPS = 4` scan; the bound was never raised).
- `tests/test_cli_spine.py`: the two E13-vacuous cases repaired, not
  deleted — the `-O`/`--out-dir` row now has a dedicated message assertion
  proving the mutual-exclusion ordering rule; the `--name` row is re-pointed
  at `split` (which declares `--name`) with a dedicated template-shape
  message assertion.
- Added `tests/unit/test_merge.py`, `tests/unit/test_split.py`,
  `tests/unit/test_name_template.py` (hypothesis, 1000 examples),
  `tests/unit/test_output_flags.py` (AC26), `tests/unit/test_verb_help_
  content.py` (AC23), `tests/integration/test_split_merge_roundtrip.py`
  (AC1, in-process and subprocess), `tests/integration/test_split_merge_
  atomicity.py` (AC17/AC20), `tests/integration/test_split_merge_cli.py`
  (AC9/AC18/AC19/AC21/AC30), `tests/pdfium_text.py` (the pypdfium2 per-page
  text helper AC1/AC4/AC5/AC15 share). Appended PDF-07's `@samples` section
  to `tests/test_samples.py` (AC22, over a copy of `PrendiniLoria2020.pdf`).

## [B-034] `make ci` was locally unrunnable under coverage instrumentation — 2026-08-30
- **Measurement (identical band both arms, `tests/test_info.py` +
  `tests/test_doctor.py` + `tests/test_cli_contract.py`, 84 tests):**
  14.49s uninstrumented vs **544.59s** instrumented under the pre-existing
  `[tool.coverage.run]` config (`branch = true`, default core) — a 37.6x
  penalty, consistent with the qa-sentinel's earlier 57x control on
  `tests/test_info.py` alone. A single isolated `info` subprocess call
  (real PDF parse) measured 0.245s uninstrumented vs **15.8s** instrumented
  (~65x) — `version`/`doctor` calls, which never reach the parser, stayed
  near baseline (~2.6x for 10 calls). CI is unaffected: the same suite ran
  in ~86s on Python 3.13 in the `engines-present` job (run `33287428715`).
- **Diagnosis, attributed by direct measurement, not assumed:** the cost is
  coverage.py's classic ctrace tracer applied to `adapters/pypdf_structure.py`
  — the primary `StructureEngine`, a pure-Python PDF parser reached by every
  `info` call. `branch = true` blocks `sys.monitoring` (`COVERAGE_CORE=sysmon`)
  from engaging at all (`Can't use core=sysmon: sys.monitoring can't measure
  branches in this version`), forcing ctrace, and ctrace on pure-Python
  parsing code is what is catastrophically slow — not a fixed per-subprocess
  startup tax (ruled out: `version`/`doctor` pay the same startup and stay
  fast) and not the `.coverage.*` combine step (ruled out: the single-call
  isolation reproduces the full multiplier with zero combine involved).
  Turning off branch tracking alone did **not** help (15.8s, unchanged) —
  the fix is specifically `core = "sysmon"` becoming reachable once branch
  tracking is off: same single call measured 0.34s (~46x faster), same
  84-test band measured 21.51s end-to-end (~25x faster).
- **Fix, config-only:** `[tool.coverage.run]` in `pyproject.toml` — `branch =
  true` → `branch = false` + `core = "sysmon"`. No Makefile or CI workflow
  changes needed: pytest-cov's parent-process measurement and the
  `patch = ["subprocess"]` child measurement both read the same
  `pyproject.toml` section, so local and CI apply the identical config with
  zero divergence. `--cov-fail-under=85` is unchanged; `patch`/`parallel`
  (subprocess measurement) are untouched — the floor for subprocess-executed
  code stays exactly as honest as `d777dd8` left it.
- **What the floor now means:** this is line coverage, not branch coverage —
  a weaker property (a line inside a branch counts as covered the moment
  either arm executes once) that reads higher for the same code. The
  84-test band alone moved from 66.24% (branch) to 71.49% (line) under
  identical tests. Re-enabling branch coverage is a legitimate follow-up
  once coverage.py/CPython ship a version combination where `sys.monitoring`
  supports branch measurement.
- **End-to-end result:** `make cover` (full 490-test suite, instrumented):
  93.79% line coverage (>= the unchanged 85% floor) in **76.67s**, down from
  a PM-observed baseline of ~571s. `make ci` (fmt-check, lint, typecheck,
  cover, licenses, sast, vulncheck): green, **80s** total wall clock, well
  under the ~5 minute target from OR-5. Only `pyproject.toml` changed —
  `make licenses`'s regenerate step is a no-op diff since no dependency
  moved.

## [PDF-04] Ruling X-67 fix-forward: `--dry-run` now runs the plan and predicts the refusal — 2026-08-29
- **The preview lied.** The dry-run gate was the first statement of
  `AtomicWriter.__enter__`, so `_plan()` never ran under `--dry-run` and a dry
  run could not predict any of the three conditions this module owns. Against an
  occupied target a `--dry-run` entered cleanly and reported
  `{"target": ..., "dry_run": true, "written": false}` — while the real run
  refused with `TargetExistsError`, exit **5**. Same for
  `DestinationUnwritableError` (exit **1**) and the cross-filesystem `atomicity
  degraded` warning, which was unreachable under `--dry-run` entirely. Ruling
  X-67 settled this during the cycle and was never carried into the PDF-04 spec,
  so the original implementation was a faithful build of an incomplete spec.
- **The gate moved to immediately above `_open_temp()`** — the first genuinely
  mutating call — so `_plan()` now runs in *both* modes. Under `--dry-run` its
  refusals are **computed and captured** rather than raised: `planned_refusal`
  holds the exception the real run would have thrown, `would_exit` is the status
  it would have exited with, and `plan_item()` renders both as one item whose
  `would_refuse` is the *identical* payload the real run prints under `-o json`.
  Capture stops at the first refusal, exactly where a real run would have
  stopped. The dry run itself still exits **0**; mirroring the predicted status
  into the dry run's own exit code is filed as **B-025**, not implemented here.
- **Real-run behaviour is unchanged** — same classes, codes, messages and
  ordering — and a test asserts a real run raises and captures nothing, so the
  capture path cannot quietly become the raise path. No runtime dependency, no
  `SCHEMA_VERSION` change, and no `ItemResult.detail`: X-26 approved that seam as
  a convention but PDF-10 has not landed and no verb consumes `AtomicWriter`, so
  the writer carries the fact and `tests/atomic_harness.py` is the machine-
  readable surface. (`EngineReport.detail` is PDF-05's unrelated `str` field.)
- **`--dry-run` purity is unchanged and now means something.** `_plan()` calls
  only `ensure_no_clobber`, `ensure_destination_writable` and
  `_warn_if_destination_moved`, which between them use `resolve()`, `.exists()`,
  `os.path.lexists()`, `.is_dir()`, `os.access` and two device stats — reads,
  every one. `assert_pure()` still reports zero differences, and two new arms
  assert it over a dry run that *does* capture a refusal (the pre-existing arm
  used `--in-place`, which suppresses no-clobber by definition and so never
  exercised the capture path at all).
- 16 tests added across `tests/unit/test_atomic_writer.py`,
  `tests/integration/test_purity_primitive.py` and
  `tests/integration/test_cross_filesystem.py`; the regression arms assert the
  prediction against a *second, real* process rather than against a hand-written
  expectation. `test_the_gate_fires_even_when_the_run_would_have_been_refused`
  was rewritten (not deleted): its "a dry run never reaches a filesystem check at
  all" docstring was the superseded contract, while its assertions still hold.


## [PDF-06] Coverage floor fix-forward: subprocess-executed CLI code was unmeasured — 2026-08-29
- `[tool.coverage.run]` gained `patch = ["subprocess"]` and `parallel = true`.
  The suite drives the CLI exclusively through `subprocess.run`
  (`tests/registry.py`, `tests/test_doctor.py`, `tests/test_info.py`,
  `tests/test_cli_spine.py`); without subprocess patching, coverage.py
  measured the parent pytest process only, and the landing commit's reported
  **71.29%** was a measurement artifact, not a real gap. Every subprocess
  call site already inherits the parent's full environment by default
  (`env=None`), so `COVERAGE_PROCESS_CONFIG` (set by the patch) reaches every
  child with no test-helper changes; `tests/unit/test_subprocess_util.py`'s
  deliberately scrubbed `env=` (testing `subprocess_util`'s own env
  handling, not the CLI) is the one exception, left untouched on purpose.
- `Makefile`'s `cover` target pins `COVERAGE_FILE` to an absolute path so a
  subprocess-measured child's parallel data file always lands next to the
  parent's in the repo root, never inside a purity-snapshot root (several
  tests spawn the CLI with `cwd` set to a temp directory). `clean` now also
  removes `.coverage.*`; `.gitignore` gained the same pattern.
- `tests/test_cli_spine.py::test_help_stays_within_the_startup_budget` now
  runs its five `--help` timings with `COVERAGE_PROCESS_START`/
  `COVERAGE_PROCESS_CONFIG` stripped from the child's environment — R-13's
  250 ms budget is a claim about the product's real startup latency, not
  about how the suite happens to be instrumented, and coverage.py's own
  tracer overhead (worse under `branch = true`) pushed the unpatched
  measurement past the budget. `run_cli()` gained an optional `env=`
  parameter (default `None`, so every other call site's inheritance is
  unchanged).
- Re-measured total: **91.29%, engines present — the floor is met**
  (`cli/cmd_doctor.py` 32%→94%, `cli/cmd_info.py` 26%→94%, `ops/inspect.py`
  30%→90%, `output/json.py` 43%→90%, `cli/main.py` 70%→100%, `__main__.py`
  0%→83%). `fail_under` stays 85; no `omit` of anything under
  `src/pdf_toolkit/` was added, then or now.
- `.github/workflows/ci.yml`'s `engines-present` job now also enforces
  `--cov-fail-under=85` (conditionally authorized only because the floor
  genuinely passes there — `decision.md` X-85); `without-engines` is
  deliberately not gated on it, matching Design §6's engines-present-only
  coverage allowance.
- `TESTING.md`'s coverage-floor section rewritten to report the true,
  current state. The original PDF-06 entry below is left untouched per this
  file's own rule 3 — this is a new entry, not a correction of that one.

## [PDF-06] Fixture corpus, CLI contract harness & real-sample guard — 2026-08-29
- Added `tests/corpus.py`: seven deterministic reportlab-generated fixtures
  (`multipage_text`, `rotated`, `jpeg_page`, `encrypted_aes256`,
  `metadata_rich`, `single_page`, `tabular`), built once per session into
  pytest's own scratch directory. Six are byte-identical across two
  independent builds; `encrypted_aes256` is exempt by construction (a fresh
  AES-256 salt every build) and is instead proven semantically —
  `tests/test_corpus.py`.
- Added `testdata/malformed.pdf` (439 B, xref/trailer destroyed, body
  objects intact, `info` exits 1, pikepdf recovers with 5 warnings) and
  `testdata/scanned-page.png` (synthesized, tesseract-recoverable) — the only
  two committed binaries, each earning its place per `testdata/README.md`.
- Added `tests/registry.py`: `discover_verbs()` walks the live Typer tree
  with no skip list, no filter, no hard-coded verb name; the
  `INVOCATIONS` registration contract; and a `reaches_atomic_writer()` scan
  that stands in for the Design-literal `is_mutating` predicate, which is
  unsatisfiable in this codebase because the global flag block attaches
  `-O`/`--out-dir`/`--in-place` to every verb uniformly (see the module's own
  docstring for the full account, and this spec's Implementation Log).
- Added `tests/test_cli_contract.py`: the thirteen-check per-verb matrix
  (`--help`, exit codes, dry-run purity, no-clobber, JSON-on-a-pipe, bulk
  non-TTY posture), parameterized over `discover_verbs()`, plus the AC10
  anti-lapse guard (`test_every_verb_is_registered`, with an automated
  monkeypatch proof that it fires).
- Added `tests/conftest.py`: the session-scoped `corpus` and `golden`
  fixtures, the `requires(engine)` marker resolving through
  `ports.resolve()`, the PATH-shadowing engines-hiding shim
  (`PDF_TOOLKIT_TEST_HIDE_ENGINES`, never touching a system binary), the
  working-tree guard (tracked files only, controller-only under `-n auto`),
  and the `samples` fixture.
- Added `tests/samples_guard.py`: the `PLAN.md` §10.1 rule 3
  originals-integrity guard as an independently-loadable pytest plugin —
  session-start manifest, session-end re-hash, fails the session naming the
  file, controller-only (`if hasattr(config, "workerinput")`). Proven against
  a **synthetic** samples directory, never the operator's real corpus
  (ruling X-25), including a proof that it runs exactly once under `-n 2`
  (`tests/integration/test_samples_guard_fires.py`).
- Added `tests/test_samples.py` (the append-only home for `PDF-07`…`PDF-15`'s
  `@samples` arms) and `tests/golden/` (empty at landing; the primitive is
  self-tested in `tests/unit/test_golden.py` entirely inside a scratch
  directory).
- Appended Section 3 to `tests/test_import_boundaries.py`: no `typer`/`click`
  import below `cli/` (`PLAN.md` §10, D-03), inheriting PDF-04's AST-walk
  machinery per `decision.md` X-6.
- `Makefile`: added `samples-scratch` / `samples-check`; `clean` now removes
  `.scratch/`; `ci` now runs `cover` instead of `test` (X-22) — the coverage
  floor is real on the local gate for the first time. **At this commit,
  coverage measures 71.29%, not the 85% floor** — a genuine, disclosed,
  out-of-scope gap (adapter internals for verbs that do not exist yet);
  `ci.yml`'s `engines-present` job is deliberately **not** wired to enforce
  the floor in this commit, to avoid shipping a red CI run over a gap PDF-06
  cannot close. See `TESTING.md`'s closing section and this spec's
  Implementation Log.
- `pyproject.toml`: `[tool.pytest.ini_options]` gained `addopts =
  "--strict-markers -ra"` and the `samples` / `requires(engine)` markers.
  `[tool.coverage.*]` untouched — already correct.
- `scripts/assert_skips.py`: the `without-engines` count is no longer
  vacuous (at least 7 engine-gated skips now exist) — its docstring and its
  own zero-count branch were updated to treat a future zero as a
  **regression**, not vacuity, per the fleet's own "make the unverifiable
  case FAIL, not SKIP" lesson.
- `tests/test_cli_spine.py`: `MAKEFILE_TARGETS` gained `samples-scratch` /
  `samples-check` (disclosed necessary edit, X-54 class — the Makefile-target
  consistency test would otherwise turn red on PDF-06's own Makefile change).

## [PDF-05] Engine ports, adapters, doctor & info — 2026-08-29
- Added `src/pdf_toolkit/ports/`: six `typing.Protocol` port modules
  (`StructureEngine`, `RasterEngine`, `ComposeEngine`, `TextEngine`, `OcrEngine`,
  `OfficeConverter`) behind a memoized `resolve()`/`resolve_all()`/`reset_cache()`
  registry, plus `require(port, capability=...)` as the **single** exit-3 chokepoint —
  every message carries the OS-aware install hint and names `pdftoolkit doctor`
  (`PLAN.md` §12 R-09). Adapter selection is **by capability, never by name**: `info`
  asks for `linearized` and gets the pikepdf-backed adapter without naming it, and
  `repair`/`linearize`/`object-streams` already resolve through the same seam.
- Added `src/pdf_toolkit/adapters/`: eight engine adapters over seven backends
  (`pypdf`/`pikepdf` structure, `pdfium` raster + text fast path, `pdfplumber` text,
  `reportlab` compose, `tesseract` OCR, `soffice` office) — probe and version
  reporting only, every engine import function-local, wheel presence read via
  `find_spec` + distribution metadata rather than by importing the library.
  `weasyprint_compose.py` is deliberately not created; `doctor` prints six rows, never
  seven, and a secondary is named in its port's `detail`.
- Added `adapters/subprocess_util.py`, **the product's only process-spawn point**:
  `timeout` is a required keyword with no default, `start_new_session=True`, and a
  process-**GROUP** kill (SIGTERM → 2 s grace → SIGKILL) on timeout *and* on every
  other exit path. `tests/unit/test_subprocess_util.py` proves it against a real
  forked grandchild via `os.killpg(pgid, 0)` → `ProcessLookupError`, corroborated by
  a pgid-scoped `pgrep -g`. This is the mediakit MHC-50 lesson (163 orphaned daemons,
  ~6.5 GiB RSS) applied before the first external binary ships.
- Added `doctor` / `doctor --strict` and `info`. `doctor` renders exactly six rows in
  a pinned order whatever the host looks like, exits 0 with engines missing and 3
  under `--strict`, and reports stray `.pdftoolkit-*` residue via PDF-04's
  `find_stray_temps()` — report, never sweep, and never a change to the exit code.
  `info` reports page count, sizes, encryption state and algorithm, permission
  tokens, PDF version, metadata, signature/form presence, linearization, `--fonts`
  and `--pages-detail`; it **writes nothing**, proven by a before/after whole-tree
  filesystem snapshot on both the plain and `--dry-run` paths. Exit codes pinned one
  test per row: 0 / 1 malformed / 2 unknown flag / 2 directory / 4 missing / 6 locked,
  with a batch collapsing to 1 per `PLAN.md` §5.4. `models.py` gained `PageInfo`,
  `DocumentInfo` and `EngineReport` at their reserved anchors; `errors.py` needed no
  change — `EngineMissingError`, `AuthError`, `NoInputError`, `UsageError` and
  `FailureError` already carried every code this spec needs.
- Added Section 2 to `tests/test_import_boundaries.py` (appended beside PDF-04's
  Section 1): no engine library imported outside `adapters/`, no spawn surface
  (`subprocess`, `pty`, `os.exec*`/`spawn*`/`system`) outside `subprocess_util.py`,
  and every `subprocess_util.run()` call site proven to pass a statically resolvable
  `argv[0]` that is not a forbidden binary — fourteen planted violations prove each
  guard fires, and a negative control proves engine names in docstrings and
  parameters are not flagged. **`tests/test_license_policy.py` was amended**: its
  non-literal-`argv[0]` refusal applied to the chokepoint file too, which a generic
  spawn wrapper cannot satisfy by construction, so the refusal moved inside the
  `is_chokepoint` branch and the compensating call-site check landed in Section 2.
  Pillow's exclusion from the engine list is recorded with its reason so a later
  spec cannot quietly weaken the walk to make room for it.

## [PDF-04] Safety spine (atomic writes, no-clobber, --in-place, -y gate) — 2026-08-29
- Added the write chokepoint under `src/pdf_toolkit/safety/`: `atomic.py`
  (`AtomicWriter` — dry-run gate as the first statement of `__enter__`, temp beside the
  resolved destination, `flush`/`fsync`, the `.bak` sidecar via `os.link` with a
  `shutil.copy2` fallback, `os.replace`, and an `EXDEV` path that copies, fsyncs,
  replaces and then verifies size **and** SHA-256), plus `paths.py` (alias-safe identity,
  no-clobber, planned-output collision, `ensure_within`, destination writability),
  `tempnames.py` (`TEMP_PREFIX`, `find_stray_temps` — reports, never sweeps, per
  `PLAN.md` §12 R-07), `confirm.py` (the bulk-destructive `-y` gate, which fails closed
  and immediately on a non-terminal) and `_faults.py` (an inherited-pipe crash
  rendezvous, inert unless a test asks for it). `SafetyPolicy.validate()` now owns
  `--no-backup` without `--in-place` (exit **2**) and `cli/common.py` delegates to it;
  `cli/main.py` gained `build_rerun_hint()`. Eight error classes added to `errors.py`,
  all subclasses of existing ones, so no new exit-code integer entered the public table.
- Added `tests/test_import_boundaries.py`: an AST walk over every file under `src/` that
  fails on any of fourteen filesystem-mutating call groups outside
  `safety/atomic.py`. Two tiers, two allowlists, **both empty and asserted empty**,
  stale-entry detection, five planted violations proving the walk bites, and a negative
  self-test proving `str.replace`, `list.remove`, `dict.copy` and `open(p, "rb")` are
  not flagged. Shared and append-only — PDF-05 and PDF-06 add their sections to it.
- Added `tests/fs_snapshot.py`, the `--dry-run` purity primitive (inode, mode, size,
  mtime, content hash, symlink target; `atime` excluded, directory mtime included;
  `$TMPDIR`/`$HOME` redirected into the test's own tree and both snapshot roots), with
  six planted mutations as negative controls and a non-dry-run control that produces a
  non-empty diff so "zero differences" cannot mean "nothing ran".
- Added `tests/atomic_harness.py` (a subprocess driver, deliberately not a verb, routing
  errors through the product's own `emit_error` and `exit_code`) and seven test arms:
  a **real** `SIGKILL` delivered to a child provably parked at `after_temp_create`,
  `after_fsync` and `after_backup` leaves the original byte-identical for both a fresh
  target and `--in-place`; a real second filesystem (`/dev/shm`) proves the degradation
  warning and a genuine kernel `EXDEV`; the `-y` gate is exercised over a never-written
  stdin pipe under a hard timeout and over a real `pty`.
- `TESTING.md` gained a "Safety-spine test arms" section documenting
  `PDF_TOOLKIT_FAULT_POINT`, `PDF_TOOLKIT_FAULT_RENDEZVOUS`,
  `PDF_TOOLKIT_TEST_XDEV_DIR`, the second-filesystem ladder (which **fails** rather than
  skips on Linux) and the expected visible-skip count per configuration. No runtime
  dependency was added and no engine is touched — every arm writes plain bytes.

## [PDF-03] Page-range grammar & selection engine — 2026-08-29
- Added `src/pdf_toolkit/ops/pagerange.py`: the one module that owns the full `PLAN.md`
  §4.3 grammar (`N`, `A-B`, `B-A`, `N-`, `-N`, `first`/`last`, `even`/`odd`, `all`,
  `!TOKEN`, `,`) via a single left-to-right evaluator over a running list, one
  normalization switch at the end (ordered vs. sorted-deduplicated). `parse()`/`render()`
  are public and framework-free (stdlib + `pdf_toolkit.models`/`errors` only, no engine,
  no I/O); `GRAMMAR_HELP` is the one string PDF-07/PDF-08 will build their `--pages` help
  text from (G6). PLAN §12 R-04 closed: `-N` is negative indexing, with a dedicated
  `1-N` open-left hint on an unresolvable negative index.
- Added `PageRangeError(UsageError)` to `src/pdf_toolkit/errors.py` (`spec`/`token`/
  `column`/`reason`) and the `is_empty` property (never a field) to `PageRange` in
  `src/pdf_toolkit/models.py` — both edits additive-only, no other line touched.
- Added `tests/test_pagerange.py`: the §4.3 token table (10/10 rows) and error table
  (7/7 rows) as data with completeness meta-tests, the five named property invariants
  P1–P5 at 1000 hypothesis examples each (`-k property` selects exactly those five), the
  PLAN §12 R-04 hint cases, and the module's own import-boundary/no-I/O tests. 100%
  statement+branch coverage on the module.
- The grammar is deliberately **unwired**: no verb, no flag, no `cli/` file created or
  edited — `pdftoolkit --help` still lists only `version`. Wiring is PDF-07/PDF-08.

## [Task: PDF-16 — Project website (GitHub Pages), Phase A] - 2026-08-29
- Added `website/` (27 files — 24 hand-authored, plus generated `package-lock.json`,
  `public/og-image.png`, `src/data/licenses.json`): a zero-client-JS Astro 7 +
  Tailwind v4 landing page at `https://armandoherra.github.io/pdf-toolkit/`, rose accent,
  ten sections (Navbar, Hero, Features, Architecture, Verbs, QuickStart, ExitCodes,
  Licensing, TechStack, Footer), data-driven Verbs/Licensing/TechStack sections rendered
  from `src/data/licenses.json` (generated by `make licenses`, PDF-02 — no second
  generator script was written).
- Added `.github/workflows/deploy-website.yml`, byte-identical to the `apps/mediakit`
  donor, SHA-pinned Pages build+deploy on push to `website/**`.
- Appended the `npm:/website` ecosystem block to `.github/dependabot.yml` (created by
  PDF-02; `uv` + `github-actions` blocks left byte-identical).
- Appended two steps to `ci.yml`'s `license-gate` job: regenerate and diff
  `website/src/data/licenses.json` for drift (PLAN §12 R-15).
- One added line each in `README.md` (website link) and `CLAUDE.md` (website layout
  note); `Current phase:` untouched in both (Phase B's job).
- Phase B (re-deriving Verbs/ExitCodes content once more verbs ship, wave 8) remains
  open by design — this item is `In progress (Phase A landed)`, not `Implemented`.

## [PDF-02] CI, license gate & release skeleton — 2026-08-29
- Added `.github/workflows/ci.yml`: ten parallel jobs (`lint`, `typecheck`, `test` on
  {3.11,3.12,3.13,3.14}x{ubuntu-latest,macos-14}, `engines-present`, `without-engines`,
  `sast`, `vulncheck`, `secret-scan`, `license-gate`, `build`), every action SHA-pinned,
  workflow-level `contents: read` and no job above it.
- Added `scripts/licenses.py`: generates `THIRD_PARTY_LICENSES` from a dedicated
  `--no-dev --all-extras` Python 3.11 environment (never the ambient venv) and gates the
  distributed closure on `AGPL|GPL|LGPL`. MPL-2.0 passes by design (`pikepdf` bundles
  libqpdf, PLAN §12 R-11); `UNKNOWN` fails; the allowlist is present, commented and empty.
- Added `tests/test_license_policy.py`: an AST walk (never a text grep) over every file
  under `src/` for forbidden imports, `subprocess` argv[0] and `shutil.which` arguments,
  with permanent positive and negative self-tests proving `gs` inside an identifier does
  not false-positive, plus the `subprocess_util.py` spawn-chokepoint assertion.
- Added `.github/workflows/release.yml` (tag-gated, PyPI Trusted Publishing, **configured
  and never fired**), `.github/dependabot.yml` (`uv` + `github-actions`), and
  `scripts/assert_skips.py` / `scripts/assert_artifacts.py`.
- Rewired the `licenses` and `secret-scan` Makefile targets; `secret-scan` now hard-fails
  with an install hint instead of exiting 0 when `gitleaks` is absent.

## [PDF-01] Project scaffold & CLI spine — 2026-08-29
- Added `pyproject.toml` with the full PLAN §7.1 runtime dependency set and committed `uv.lock`.
- Added the `src/pdf_toolkit/` six-layer skeleton, the Typer root with all §4.2 global flags,
  `errors.py`/`exit_codes.py`, the table/JSON/NDJSON renderers, the redacting stderr logger,
  and `SafetyPolicy`.
- Added the placeholder `version` verb, the 18-target `Makefile`, six documentation skeletons,
  `changelog.md`, and `.scratch/` to `.gitignore`.
