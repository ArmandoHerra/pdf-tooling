# pdf-toolkit — developer entry points.
#
# `make ci` is a SUBSET of CI, run with the same commands -- it does not
# predict CI. What runs locally, what does not, and why is declared in
# .github/gate-parity.toml, enforced by tests/test_gate_parity.py, and printed
# by `make ci`'s own epilogue on every run (PDF-28). No target here degrades
# to a weaker substitute, swallows a missing tool, or exits 0 when its check
# did not run — a gate that cannot fail is not a gate.

.DEFAULT_GOAL := help
SHELL := /bin/bash
# PDF-34 / B-231: `-o pipefail` ONLY, and the narrowness is deliberate and
# asserted by a test. Without this, a recipe line that pipes a failing
# command into a reader inherits the READER's status, so `docs-gate`'s arms 1
# and 3 discarded pytest's verdict and the target exited 0 on a red suite --
# a gate that cannot fail is not a gate, eight lines after this file says so.
# `-e` is excluded because make already checks each recipe line's status, so
# it buys nothing here and would change four `;`-chained recipes; `-u` is
# excluded because `ARGS`/`PYTEST_ARGS` and several `$$`-shell variables
# expand empty BY DESIGN. `-c` stays last: make appends the command to it.
.SHELLFLAGS := -o pipefail -c

ARGS ?=
PYTEST_ARGS ?=

# PDF-28 / B-029: when set, PYTHON pins the targets below to an isolated
# per-interpreter environment (`.venv-py<x.y>/`), without disturbing the
# ambient `.venv/`. `make test PYTHON=3.11` runs, on that interpreter, the
# same command CI's 3.11 matrix legs run -- `make test`, uninstrumented. CI
# does not run `cover` at 3.11, so `make ci PYTHON=3.11` would add coverage
# instrumentation those legs do not have (B-148, owned by PDF-29); it is not
# the closer reproduction. Unset (the default) costs nothing and changes no
# command below.
PYTHON ?=
ifdef PYTHON
UV_RUN := UV_PROJECT_ENVIRONMENT=.venv-py$(PYTHON) uv run --python $(PYTHON)
else
UV_RUN := uv run
endif

.PHONY: help build install run doctor test test-e2e cover fmt fmt-check lint \
        typecheck vulncheck sast secret-scan licenses samples-scratch samples-check \
        samples-gate engines-gate licenses-check artifacts-check gate-timing \
        docs-gate ci clean

help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

build: ## Build the sdist and wheel into dist/
	uv build

install: ## Install the CLI onto your PATH as `pdftoolkit`
	uv tool install --force .

run: ## Run the CLI: make run ARGS="version -o json"
	uv run pdftoolkit $(ARGS)

doctor: ## Report which engines resolved (arrives with the engine-ports work; exits 2 until then)
	uv run pdftoolkit doctor

test: ## Run the test suite
	$(UV_RUN) pytest $(PYTEST_ARGS)

test-e2e: ## Run only the subprocess-level CLI tests
	uv run pytest -m e2e

cover: ## Run the suite under coverage against the project's floor
	# COVERAGE_FILE is pinned to an absolute path so subprocess-measured CLI
	# children (run with cwd=tmp_path/workspace by several tests) always write
	# their parallel data file next to this one in the repo root, never inside
	# a purity-snapshot root -- see [tool.coverage.run] in pyproject.toml.
	#
	# B-090: two concurrent `make cover` (or `make ci`) invocations against
	# this one absolute COVERAGE_FILE race and corrupt it -- the observed
	# signature was `make: *** [Makefile:44: cover] Error 1` alongside pytest
	# itself reporting a full, clean pass. `flock(1)` is util-linux and is NOT
	# on macOS, and this target runs on macos-14 as well as ubuntu-latest, so
	# the guard below uses `mkdir`, which is atomic on every POSIX filesystem
	# this repo targets and needs no new dependency. Guarding `cover` alone
	# (the one target that actually writes COVERAGE_FILE) is deliberate:
	# `ci` depends on `cover`, so it inherits this guard through that
	# dependency -- guarding `ci` too would self-deadlock `make ci` against
	# its own prerequisite.
	@lock="$(CURDIR)/.make-cover.lock"; \
	if ! mkdir "$$lock" 2>/dev/null; then \
	  holder="$$(cat "$$lock/pid" 2>/dev/null)"; \
	  if [ -n "$$holder" ] && ! kill -0 "$$holder" 2>/dev/null; then \
	    echo "make cover: clearing a STALE lock at $$lock (pid $$holder is no longer running)" >&2; \
	    rm -rf "$$lock"; \
	  fi; \
	  if ! mkdir "$$lock" 2>/dev/null; then \
	    holder="$$(cat "$$lock/pid" 2>/dev/null || echo unknown)"; \
	    echo "" >&2; \
	    echo "make cover: REFUSED -- this is a CONCURRENCY GUARD, not a test failure." >&2; \
	    echo "  Another 'make cover' (or 'make ci') is already running here, held by pid $$holder." >&2; \
	    echo "  Two concurrent runs would race on the shared COVERAGE_FILE at $(CURDIR)/.coverage" >&2; \
	    echo "  and corrupt it. Wait for the other run to finish. If you are certain nothing is" >&2; \
	    echo "  actually running, clear the lock with 'make clean' (or: rm -rf $$lock)." >&2; \
	    echo "" >&2; \
	    exit 1; \
	  fi; \
	fi; \
	echo "$$$$" > "$$lock/pid"; \
	trap 'rm -rf "$$lock"' EXIT INT TERM; \
	COVERAGE_FILE=$(CURDIR)/.coverage \
	  $(UV_RUN) pytest --cov=pdf_toolkit --cov-report=term-missing --cov-fail-under=85 $(PYTEST_ARGS)

fmt: ## Format the tree
	uv run ruff format .

fmt-check: ## Check formatting without writing
	$(UV_RUN) ruff format --check .

lint: ## Lint the tree
	$(UV_RUN) ruff check .

typecheck: ## Type-check src/ in strict mode
	$(UV_RUN) mypy src/

vulncheck: ## Audit dependencies for known CVEs
	$(UV_RUN) pip-audit

sast: ## Static security analysis of src/
	$(UV_RUN) bandit -r src/ -c pyproject.toml

secret-scan: ## Scan history and worktree for secrets (needs the gitleaks binary)
	@command -v gitleaks >/dev/null 2>&1 || { \
		echo ""; \
		echo "make: gitleaks is not on PATH."; \
		echo "  This gate cannot run, and it will NOT exit 0 pretending that it did."; \
		echo "  Install: https://github.com/gitleaks/gitleaks/releases"; \
		echo "           (macOS: brew install gitleaks)"; \
		echo "  CI installs a version-pinned release binary and then runs this same"; \
		echo "  target, so the local command and the CI command stay identical."; \
		echo ""; \
		exit 1; \
	}
	gitleaks detect --no-banner

licenses: ## Regenerate THIRD_PARTY_LICENSES from the pinned closure, then gate it
	$(UV_RUN) python scripts/licenses.py generate
	$(UV_RUN) python scripts/licenses.py check

samples-scratch: ## Copy $$PDF_TOOLKIT_SAMPLES_DIR into .scratch/samples/ + write the originals manifest (PLAN.md §10.1)
	@if [ -z "$$PDF_TOOLKIT_SAMPLES_DIR" ]; then \
		echo "make samples-scratch: PDF_TOOLKIT_SAMPLES_DIR is not set." >&2; \
		echo "  export PDF_TOOLKIT_SAMPLES_DIR=/path/to/your/samples" >&2; \
		exit 1; \
	fi
	@if [ ! -d "$$PDF_TOOLKIT_SAMPLES_DIR" ]; then \
		echo "make samples-scratch: $$PDF_TOOLKIT_SAMPLES_DIR is not a directory." >&2; \
		exit 1; \
	fi
	@if [ -e .scratch/samples.MANIFEST.sha256 ]; then \
		echo "make samples-scratch: .scratch/samples.MANIFEST.sha256 already exists." >&2; \
		echo "  Overwriting it would silently replace the snapshot that 'make samples-check'" >&2; \
		echo "  compares the originals against -- which is exactly how a STALE manifest lets" >&2; \
		echo "  that check report 'originals unchanged' for a run that never snapshotted" >&2; \
		echo "  anything. Refusing rather than overwriting is what makes that impossible" >&2; \
		echo "  instead of merely discouraged." >&2; \
		echo "  Clear .scratch/ with 'make clean', then re-run this target." >&2; \
		exit 1; \
	fi
	@mkdir -p .scratch
	@rm -rf .scratch/samples
	@cp -R "$$PDF_TOOLKIT_SAMPLES_DIR" .scratch/samples
	@cd "$$PDF_TOOLKIT_SAMPLES_DIR" && find . -type f -print0 | sort -z \
		| xargs -0 sha256sum > "$(CURDIR)/.scratch/samples.MANIFEST.sha256"
	@echo "samples copied to .scratch/samples/; originals manifest written to .scratch/samples.MANIFEST.sha256"

samples-check: ## Re-hash $$PDF_TOOLKIT_SAMPLES_DIR against .scratch/samples.MANIFEST.sha256 (PLAN.md §10.1 rule 3)
	@if [ -z "$$PDF_TOOLKIT_SAMPLES_DIR" ]; then \
		echo "make samples-check: PDF_TOOLKIT_SAMPLES_DIR is not set." >&2; \
		echo "  export PDF_TOOLKIT_SAMPLES_DIR=/path/to/your/samples" >&2; \
		exit 1; \
	fi
	@if [ ! -f .scratch/samples.MANIFEST.sha256 ]; then \
		echo "make samples-check: no manifest at .scratch/samples.MANIFEST.sha256 -- run 'make samples-scratch' first." >&2; \
		exit 1; \
	fi
	@cd "$$PDF_TOOLKIT_SAMPLES_DIR" && sha256sum -c --quiet "$(CURDIR)/.scratch/samples.MANIFEST.sha256"
	@echo "originals unchanged"

# The @samples control chain, encoded ONCE (decision.md §8 X-115).
#
# B-046 did not propagate because one engineer mis-ordered four steps; it
# propagated because the ordering was RE-TYPED into every spec's Validation
# block, three specs deep, and a re-typed recipe is a recipe that can be got
# wrong. So the ordering lives here and a spec invokes one target -- the same
# protected-by-construction lever as OR-3's central flag declaration and
# B-054's `plan_output_set`. There is then no recipe left for a spec to get
# wrong, which is the only version of this fix that survives a later wave's
# spec being written by a different engineer.
#
# Deliberately NOT part of `ci`: it needs the real-document corpus and copies
# every original, so wiring it into the gate would both slow the gate (B-061)
# and break CI, which has no corpus and must not have one.
#
# Step 4 needs a real ASSERTION and not an exit code. With the variable unset,
# "all skipped" and "all passed" both exit 0, so an exit-code check would be
# one more control that cannot control (X-68, X-92, X-102, X-108 -- four times
# now). The junit counts below fail on any pass AND on zero collected tests: a
# typo in the -m selector would otherwise let this step succeed vacuously,
# which is the same defect family wearing a different hat.
define SAMPLES_UNSET_ASSERT
import sys, xml.etree.ElementTree as ET
root = ET.parse(".scratch/samples-unset.xml").getroot()
suite = root if root.tag == "testsuite" else root.find("testsuite")
total = int(suite.get("tests", 0))
skipped = int(suite.get("skipped", 0))
broken = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
passed = total - skipped - broken
if total == 0:
    sys.exit(
        "make samples-gate: the unset arm COLLECTED ZERO samples tests. An exit code "
        "alone cannot tell that apart from 'every test skipped', which is precisely how "
        "a green control stops controlling. Check the -m selector."
    )
if passed or broken:
    sys.exit(
        "make samples-gate: with PDF_TOOLKIT_SAMPLES_DIR unset every samples test must "
        "SKIP, with a reason. Got %d test(s): %d skipped, %d passed, %d failed. "
        "A pass here IS the defect (PLAN.md 10.1 rule 5)." % (total, skipped, passed, broken)
    )
print("samples-gate: unset arm skipped all %d samples test(s), zero passes" % total)
endef
export SAMPLES_UNSET_ASSERT

samples-gate: ## Run the whole @samples chain in the one correct order (PLAN.md §10.1, B-046/X-108)
	@if [ -e .scratch/samples.MANIFEST.sha256 ]; then \
		echo "make samples-gate: a manifest already exists at .scratch/samples.MANIFEST.sha256." >&2; \
		echo "  A LEFTOVER manifest makes step 5 compare the originals against an artefact" >&2; \
		echo "  from an EARLIER run -- it reports 'originals unchanged' before this run has" >&2; \
		echo "  snapshotted anything, so the control passes without controlling (X-108)." >&2; \
		echo "  Clear .scratch/ with 'make clean', then re-run this target." >&2; \
		exit 1; \
	fi
	@echo "samples-gate 1/5: no stale manifest"
	@echo "samples-gate 2/5: snapshotting the originals BEFORE anything runs"
	$(MAKE) samples-scratch
	@echo "samples-gate 3/5: with the corpus present the arm must RUN and pass"
	uv run pytest -m samples -rs --junitxml=.scratch/samples-set.xml
	@echo "samples-gate 4/5: with the corpus absent the arm must SKIP, with zero passes"
	env -u PDF_TOOLKIT_SAMPLES_DIR uv run pytest -m samples -rs --junitxml=.scratch/samples-unset.xml
	@uv run python -c "$$SAMPLES_UNSET_ASSERT"
	@echo "samples-gate 5/5: only NOW is the originals comparison meaningful"
	$(MAKE) samples-check

# PDF-28: the three targets below make a CI-only check RUNNABLE locally. NONE
# joins `make ci` -- see .github/gate-parity.toml `in_make_ci`. Declaring a
# local counterpart is strictly better than having none, without spending the
# wall-clock `PDF-29` is fighting.

engines-gate: ## Run both engine configurations (present + hidden) with skip-visibility assertions
	@mkdir -p .scratch
	@missing=""; \
	command -v tesseract >/dev/null 2>&1 || missing="$$missing tesseract"; \
	command -v soffice >/dev/null 2>&1 || missing="$$missing soffice"; \
	if [ -n "$$missing" ]; then \
		echo "" >&2; \
		echo "make engines-gate: REFUSING arm 1 (engines present) --$$missing not on PATH." >&2; \
		echo "  This arm exercises the engine-backed code paths; it does not skip them," >&2; \
		echo "  and it will NOT exit 0 pretending it ran them." >&2; \
		echo "  Install the missing engine(s), or use 'make test' directly if you only" >&2; \
		echo "  need the without-engines arm below." >&2; \
		echo "" >&2; \
		exit 1; \
	fi
	@echo "engines-gate 1/2: engines present -- cover + zero-skip assertion"
	$(MAKE) cover PYTEST_ARGS="--junitxml=.scratch/junit-engines-present.xml"
	$(UV_RUN) python scripts/assert_skips.py .scratch/junit-engines-present.xml --expect-zero
	@echo "engines-gate 2/2: engines hidden -- test + skip-visibility assertion"
	PDF_TOOLKIT_TEST_HIDE_ENGINES=tesseract,soffice $(MAKE) test PYTEST_ARGS="--junitxml=.scratch/junit-without-engines.xml"
	$(UV_RUN) python scripts/assert_skips.py .scratch/junit-without-engines.xml

# PDF-29. DELIBERATELY NOT a prerequisite of `ci`, and that is a decision
# rather than an omission: a gate that measures itself on every run pays the
# measurement's cost on every run, and the measurement is only meaningful on a
# host verified quiet anyway -- `--baseline` REFUSES on a host it cannot verify,
# which would make `make ci` refuse on any loaded developer box. The protocol,
# the record schema and the rule that a `quiet: false` record is an observation
# and never a baseline all live in perf/README.md.
GATE_TIMING_ARGS ?= --target ci --cache-state warm

gate-timing: ## Measure a gate target under the PDF-29 protocol; appends one record to perf/gate-timings.jsonl
	$(UV_RUN) python scripts/measure_gate.py $(GATE_TIMING_ARGS) --baseline

licenses-check: ## Reproduce the license-gate CI job's freshness diffs locally (needs-clean-tree)
	$(MAKE) licenses
	git diff --exit-code -- THIRD_PARTY_LICENSES website/src/data/licenses.json

artifacts-check: ## Reproduce the build job's license-file assertion locally (needs-built-artifact)
	uv build
	uv run --no-project python scripts/assert_artifacts.py

# PDF-30 / B-099. The instruction `Re-run it; do not copy it` was written into
# TESTING.md and had no carrier, so the figure drifted anyway -- B-099 measured
# `8 passed, 18 skipped` and it was `8 passed, 20 skipped` when PDF-30 re-ran
# the same command. This is that instruction given a carrier: the documented
# command runs VERBATIM and the figure the document quotes is compared against
# what the run reported, naming the document, the quoted value and the measured
# value on any disagreement.
define DOCS_GATE_ENGINES_ASSERT
import pathlib, re, sys
report = pathlib.Path(".scratch/docs-gate-engines-hidden.txt").read_text()
tail = re.search(r"(\d+) passed, (\d+) skipped", report)
if tail is None:
    sys.exit(
        "make docs-gate: the engines-hidden run reported no `N passed, M skipped` "
        "line at all. An exit code alone cannot tell that apart from a run that "
        "collected nothing, which is how a green control stops controlling."
    )
measured = "%s passed, %s skipped" % (tail.group(1), tail.group(2))
doc = pathlib.Path("TESTING.md").read_text()
quoted = re.findall(r"`(\d+ passed, \d+ skipped)`", doc)
if not quoted:
    sys.exit(
        "make docs-gate: TESTING.md quotes no `N passed, M skipped` figure for the "
        "engines-hidden configuration, so this arm would compare nothing."
    )
wrong = [figure for figure in quoted if figure != measured]
if wrong:
    sys.exit(
        "make docs-gate: TESTING.md quotes %s for the engines-hidden run; the "
        "documented command just reported %s. Re-run it; do not copy it."
        % (", ".join(repr(f) for f in wrong), measured)
    )
print("docs-gate: TESTING.md's engines-hidden figure agrees with the run (%s)" % measured)
endef
export DOCS_GATE_ENGINES_ASSERT

# PDF-30. The documentation gate. DELIBERATELY NOT a prerequisite of `ci`, and
# that is a decision rather than an omission: `PDF-29` is halving a gate that
# had doubled and `PDF-28` asserts `make ci`'s target list against `ci.yml`'s
# job list, so a wave-8 target quietly joining `ci` would fight both. If its
# measured wall clock ever argues for inclusion, that is a number for the PM,
# not a decision taken in this recipe (decision.md §5 R-1).
#
# THE ARMS THAT CANNOT ALWAYS RUN SAY SO. MEASURED at PDF-34 HEAD by running
# the thing in each condition, because the previous figures here ("two" and
# "four") were BOTH wrong and nothing checked them -- a stale count in the
# comment above a skip census is the same defect this target exists to end:
#   FIVE  arms read the maintainer's planning tree (`PDF_TOOLKIT_PLANNING_DIR`);
#         recipe: PDF_TOOLKIT_PLANNING_DIR=/nonexistent make docs-gate
#   ELEVEN arms read git history deeper than a shallow checkout, in TWO classes
#         -- 10 against MINIMUM_HISTORY_DEPTH, plus 1 that cannot check a depth
#         precondition against a checkout never given the depth to check it;
#         recipe: run the three arm-3 files inside `git clone --depth 1`.
# `ci.yml`'s `test` job has neither, so in CI all SIXTEEN skip -- and a skipped
# arm is NEVER agreement. `-rs` prints every skip reason and the epilogue below
# repeats the count, so "it ran" and "it could not run" can never be read as
# the same green (X-153).
#
# PDF-34 D3: `DOCS_GATE_STRICT=1` turns that sentence into an exit code. Unset
# (the default) is byte-for-byte today's behaviour -- skips are printed and
# counted and the target still exits 0 -- because the five planning arms
# LEGITIMATELY cannot run in CI, which checks out this repository alone. The
# cadence that CAN see both trees runs it strict, where zero arms may skip.
define DOCS_GATE_EPILOGUE
import os, re, sys
text = sys.stdin.read()
sys.stdout.write(text)
# pytest AGGREGATES identical skip reasons as `SKIPPED [N] <reason>`, so
# counting LINES here would report 1 where 5 arms skipped -- a control that
# reports the wrong answer, which is the failure this whole target exists to
# end. The bracketed count is the number of arms.
skipped = re.findall(r"^SKIPPED \[(\d+)\] (.*)$$", text, re.MULTILINE)
arms = sum(int(count) for count, _ in skipped)
print("")
print("docs-gate: %d arm(s) skipped, in %d class(es)." % (arms, len(skipped)))
for count, reason in skipped:
    print("  SKIPPED [%s] -- %s" % (count, reason))
if skipped:
    print("")
    print("  A SKIPPED ARM IS NOT AGREEMENT. Re-run with PDF_TOOLKIT_PLANNING_DIR")
    print("  pointed at the planning tree, and in a full (non-shallow) clone, to")
    print("  turn these into real comparisons. `make ci` does not run this target.")
# PDF-34 D3. For as long as this epilogue has existed it has PRINTED
# "A SKIPPED ARM IS NOT AGREEMENT" and then exited 0 anyway -- the rule stated
# in prose, by the gate, about itself, with nothing enforcing it. Strict mode
# is that sentence as an exit code, and it is opt-in for one measured reason:
# CI checks out this repository alone, so the five planning arms skip there for
# a reason that is not a defect, and a strict CI run would fail honestly-shaped
# but wrongly. The Tier-2 cadence runs where BOTH trees exist, so zero arms may
# skip and any skip is real news.
if skipped and os.environ.get("DOCS_GATE_STRICT", "").strip() not in ("", "0", "false", "no"):
    print("")
    print("  DOCS_GATE_STRICT=1: %d skipped arm(s) in %d class(es) is a FAILURE."
          % (arms, len(skipped)))
    print("  A SKIPPED ARM IS NOT AGREEMENT -- and under this posture that is an")
    print("  exit code, not a paragraph. Classes above name what could not run.")
    sys.exit(1)
endef
export DOCS_GATE_EPILOGUE

docs-gate: ## Re-run the documented commands and compare the figures the docs quote (PDF-30; NOT part of `ci`)
	@mkdir -p .scratch
	@echo "docs-gate 1/3: the documented engines-hidden command, run VERBATIM"
	@PDF_TOOLKIT_TEST_HIDE_ENGINES=tesseract,soffice $(UV_RUN) pytest \
	  tests/integration/test_ocr.py tests/integration/test_office.py -rs -q \
	  2>&1 | tee .scratch/docs-gate-engines-hidden.txt | tail -1
	@echo "docs-gate 2/3: TESTING.md's quoted figure must equal what that run reported"
	@$(UV_RUN) python -c "$$DOCS_GATE_ENGINES_ASSERT"
	@echo "docs-gate 3/3: the derived, history and planning-artifact arms"
	@$(UV_RUN) pytest tests/test_docs_antirot.py tests/test_changelog_history.py \
	  tests/test_docstring_pointers.py -rs -q -p no:randomly \
	  | $(UV_RUN) python -c "$$DOCS_GATE_EPILOGUE"

ci: fmt-check lint typecheck cover licenses sast vulncheck ## Run the full local gate; ends by printing what CI additionally gates
	@uv run python scripts/gate_parity.py epilogue

clean: ## Remove build, cache and coverage artefacts
	rm -rf dist build .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage coverage.xml .scratch .make-cover.lock
	rm -f .coverage.*
