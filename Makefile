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

ARGS ?=
PYTEST_ARGS ?=

# PDF-28 / B-029: when set, `make ci PYTHON=3.11` reproduces the ONE named CI
# leg that went red under an isolated per-interpreter environment, without
# disturbing the ambient `.venv/`. Unset (the default) costs nothing and
# changes no command below.
PYTHON ?=
ifdef PYTHON
UV_RUN := UV_PROJECT_ENVIRONMENT=.venv-py$(PYTHON) uv run --python $(PYTHON)
else
UV_RUN := uv run
endif

.PHONY: help build install run doctor test test-e2e cover fmt fmt-check lint \
        typecheck vulncheck sast secret-scan licenses samples-scratch samples-check \
        samples-gate engines-gate licenses-check artifacts-check ci clean

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

licenses-check: ## Reproduce the license-gate CI job's freshness diffs locally (needs-clean-tree)
	$(MAKE) licenses
	git diff --exit-code -- THIRD_PARTY_LICENSES website/src/data/licenses.json

artifacts-check: ## Reproduce the build job's license-file assertion locally (needs-built-artifact)
	uv build
	uv run --no-project python scripts/assert_artifacts.py

ci: fmt-check lint typecheck cover licenses sast vulncheck ## Run the full local gate; ends by printing what CI additionally gates
	@uv run python scripts/gate_parity.py epilogue

clean: ## Remove build, cache and coverage artefacts
	rm -rf dist build .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage coverage.xml .scratch .make-cover.lock
	rm -f .coverage.*
