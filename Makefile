# pdf-toolkit — developer entry points.
#
# The local gate IS the CI gate: `make ci` runs exactly the checks CI runs, in
# the same order, with the same commands. No target here degrades to a weaker
# substitute, swallows a missing tool, or exits 0 when its check did not run —
# a gate that cannot fail is not a gate.

.DEFAULT_GOAL := help
SHELL := /bin/bash

ARGS ?=

.PHONY: help build install run doctor test test-e2e cover fmt fmt-check lint \
        typecheck vulncheck sast secret-scan licenses ci clean

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
	uv run pytest

test-e2e: ## Run only the subprocess-level CLI tests
	uv run pytest -m e2e

cover: ## Run the suite under coverage against the project's floor
	uv run pytest --cov=pdf_toolkit --cov-report=term-missing --cov-fail-under=85

fmt: ## Format the tree
	uv run ruff format .

fmt-check: ## Check formatting without writing
	uv run ruff format --check .

lint: ## Lint the tree
	uv run ruff check .

typecheck: ## Type-check src/ in strict mode
	uv run mypy src/

vulncheck: ## Audit dependencies for known CVEs
	uv run pip-audit

sast: ## Static security analysis of src/
	uv run bandit -r src/ -c pyproject.toml

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
	uv run python scripts/licenses.py generate
	uv run python scripts/licenses.py check

ci: fmt-check lint typecheck test licenses sast vulncheck ## Run the full local gate

clean: ## Remove build, cache and coverage artefacts
	rm -rf dist build .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage coverage.xml
