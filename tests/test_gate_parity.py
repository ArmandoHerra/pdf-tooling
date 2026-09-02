"""The gate-parity agreement test — PDF-28.

`expertise/product.yaml`'s second headline defect class, applied literally:
*pair every assertion with one made by a DIFFERENT consumer than the one that
computes it.* `scripts/gate_parity.py` parses `.github/workflows/ci.yml`
structurally, with PyYAML. This module parses it a SECOND time, independently,
with a from-scratch regex/text scan that imports NOTHING from
`scripts.gate_parity` except the pure `validate()` function (which takes
already-derived data as arguments and does no parsing of its own — it is not
"the derivation" this file exists to double-check) and the closed `REASON_VOCAB`
constant.
`test_this_module_imports_only_the_pure_validator_from_gate_parity` mechanizes
that boundary so it cannot rot silently.

If both sides shared one YAML parser, a parser bug would make them agree
WRONGLY — a green that is evidence FOR the defect this cycle exists to catch,
not against it (the `PDF-09` AC8 shape). Three consumers must agree in total;
the third is `gh run view <id> --json jobs` on a real pushed run, which cannot
run in a unit test — its output is recorded in `PDF-28`'s Implementation Log.

This module also permanently mechanizes four of `PDF-02`'s criteria that were
verified once by hand and never again (Design §6, AC22): AC1 (the exact
ten-job set), AC2 (SHA-pinning count equality), AC3 (least-privilege scoping)
and AC17 (the two `PDF-16` anchor greps). And it carries a fifth: a real
`make secret-scan` invocation with `gitleaks` hidden from `PATH`, which is
`PDF-02` AC19's control, CONSTRUCTED rather than transcribed, because
`gitleaks` is now present and unpinned on this host (V-5) and the criterion's
original premise ("gitleaks absent") no longer holds.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Final

from acceptance._model import RedKind

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

# scripts/ has no __init__.py and is not on sys.path by pytest's default
# rootdir insertion (that only adds tests/, since tests/__init__.py does not
# exist either). Added explicitly, once, so `import gate_parity` below
# resolves. This imports `validate` (pure, data-in/data-out) and the closed
# `REASON_VOCAB` constant -- never the structural CI-workflow parsing entry
# point this module exists to double-check independently. See
# test_this_module_imports_only_the_pure_validator_from_gate_parity, which
# checks the real import statement via `ast`, not a substring search (a
# substring search would also trip on this file's own
# `independent_derive_from_ci` function name below -- X-183/X-198's lesson:
# assert on a computed value, never on a literal the assertion itself spells
# out).
_SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from gate_parity import REASON_VOCAB, GatingStep, validate  # noqa: E402

CI_WORKFLOW: Final[Path] = REPO_ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW: Final[Path] = REPO_ROOT / ".github" / "workflows" / "release.yml"
DEPLOY_WORKFLOW: Final[Path] = REPO_ROOT / ".github" / "workflows" / "deploy-website.yml"
MANIFEST_PATH: Final[Path] = REPO_ROOT / ".github" / "gate-parity.toml"
MAKEFILE_PATH: Final[Path] = REPO_ROOT / "Makefile"
DEPENDABOT_PATH: Final[Path] = REPO_ROOT / ".github" / "dependabot.yml"

_CLAIM_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"the local gate is the ci gate|exactly the checks ci runs|the same checks ci runs"
    r"|green locally it is green in ci",
    re.IGNORECASE,
)

_SETUP_STEP_NAMES: Final[frozenset[str]] = frozenset({"Install engines", "Install pinned gitleaks"})
_SETUP_RUN_COMMANDS: Final[frozenset[str]] = frozenset({"uv sync --locked"})

# --------------------------------------------------------------------------- #
# An INDEPENDENT, from-scratch regex scan of ci.yml. No PyYAML, no import from
# scripts.gate_parity's derivation. See module docstring.
# --------------------------------------------------------------------------- #


def _job_blocks(text: str) -> tuple[tuple[str, ...], dict[str, list[str]]]:
    lines = text.splitlines()
    jobs_at = next(i for i, line in enumerate(lines) if line == "jobs:")
    body = lines[jobs_at + 1 :]
    starts: list[tuple[int, str]] = []
    for i, line in enumerate(body):
        m = re.match(r"^  ([a-zA-Z][a-zA-Z0-9_-]*):\s*$", line)
        if m:
            starts.append((i, m.group(1)))
    names = tuple(name for _, name in starts)
    blocks: dict[str, list[str]] = {}
    for idx, (start_i, name) in enumerate(starts):
        end_i = starts[idx + 1][0] if idx + 1 < len(starts) else len(body)
        blocks[name] = body[start_i + 1 : end_i]
    return names, blocks


def _matrix_leg_count(block: list[str]) -> int:
    legs = 1
    found_matrix_axis = False
    for line in block:
        m = re.match(r"^\s{8}([a-zA-Z0-9_-]+):\s*\[(.*)\]\s*$", line)
        if not m:
            continue
        axis, values = m.group(1), m.group(2)
        if axis in ("include", "exclude"):
            continue
        items = [v for v in values.split(",") if v.strip()]
        legs *= len(items)
        found_matrix_axis = True
    return legs if found_matrix_axis else 1


def _step_chunks(block: list[str]) -> list[list[str]]:
    starts = [i for i, line in enumerate(block) if re.match(r"^      - (uses|run|name):", line)]
    chunks: list[list[str]] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(block)
        chunks.append(block[start:end])
    return chunks


def _extract_run_and_name(chunk: list[str]) -> tuple[str | None, str, bool]:
    norm = list(chunk)
    norm[0] = re.sub(r"^(\s*)- ", r"\1", norm[0], count=1)
    text_lines = [line for line in norm if not line.strip().startswith("#")]

    continue_on_error = any(
        re.match(r"^\s*continue-on-error:\s*true\s*$", line) for line in text_lines
    )

    name = ""
    for line in text_lines:
        m = re.match(r"^\s*name:\s*(.+?)\s*$", line)
        if m:
            name = m.group(1).strip().strip("\"'")
            break

    run_idx = None
    run_indent = None
    inline_text = None
    for i, line in enumerate(text_lines):
        m = re.match(r"^(\s*)run:\s*(.*)$", line)
        if m:
            run_idx, run_indent, inline_text = i, len(m.group(1)), m.group(2).strip()
            break
    if run_idx is None:
        return None, name, continue_on_error

    if inline_text and inline_text not in ("|", ">"):
        return inline_text, name, continue_on_error

    body: list[str] = []
    for line in text_lines[run_idx + 1 :]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= (run_indent or 0):
            break
        body.append(line.strip())
    return (body[-1] if body else ""), name, continue_on_error


def _is_gating(chunk: list[str]) -> bool:
    run_text, name, continue_on_error = _extract_run_and_name(chunk)
    if run_text is None or continue_on_error:
        return False
    if run_text.endswith("|| true"):
        return False
    if name in _SETUP_STEP_NAMES:
        return False
    if run_text.strip() in _SETUP_RUN_COMMANDS:
        return False
    return True


def independent_derive_from_ci(
    path: Path = CI_WORKFLOW,
) -> tuple[tuple[str, ...], int, dict[str, int]]:
    """Returns (job names, total check-leg count, {job: gating-step count})."""
    names, blocks = _job_blocks(path.read_text())
    leg_count = sum(_matrix_leg_count(blocks[name]) for name in names)
    gating_counts = {
        name: sum(1 for c in _step_chunks(blocks[name]) if _is_gating(c)) for name in names
    }
    return names, leg_count, gating_counts


def load_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open("rb") as fh:
        return tomllib.load(fh)


# --------------------------------------------------------------------------- #
# AC3 — the independent re-derivation, both directions
# --------------------------------------------------------------------------- #


def test_the_independent_scan_finds_ten_jobs_seventeen_legs_nineteen_gating_steps() -> None:
    names, leg_count, gating_counts = independent_derive_from_ci()
    assert len(names) == 10, names
    assert leg_count == 17, leg_count
    assert sum(gating_counts.values()) == 19, gating_counts


def test_manifest_parses_with_tomllib_and_declares_schema_version_1() -> None:
    manifest = load_manifest()
    assert manifest["schema_version"] == 1
    assert len(manifest["check"]) == 19


def test_gate_parity_check_subcommand_agrees_with_the_independent_scan() -> None:
    """The THIRD-from-independence angle: run the real CLI as a subprocess
    (never imported) and confirm its printed figures match this file's own
    from-scratch derivation."""
    names, leg_count, gating_counts = independent_derive_from_ci()
    result = subprocess.run(
        [sys.executable, "scripts/gate_parity.py", "check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert f"jobs: {len(names)}" in result.stdout
    assert f"check legs: {leg_count}" in result.stdout
    assert f"gating steps: {sum(gating_counts.values())}" in result.stdout


def test_the_manifest_agrees_with_the_independently_derived_job_set_and_step_counts() -> None:
    """The load-bearing check, computed independently of scripts.gate_parity's
    own validate() call (which this test does not invoke) -- if the job set or
    per-job gating-step counts drift from the manifest, this reddens."""
    names, _leg_count, gating_counts = independent_derive_from_ci()
    manifest = load_manifest()
    manifest_job_names = {c["job"] for c in manifest["check"]}
    assert manifest_job_names == set(names), (
        f"manifest jobs {sorted(manifest_job_names)} != ci.yml jobs {sorted(names)}"
    )
    manifest_counts: dict[str, int] = {}
    for c in manifest["check"]:
        manifest_counts[c["job"]] = manifest_counts.get(c["job"], 0) + 1
    assert manifest_counts == gating_counts, (manifest_counts, gating_counts)


def test_every_reason_in_the_manifest_is_in_the_closed_vocabulary() -> None:
    manifest = load_manifest()
    for c in manifest["check"]:
        reason = c.get("reason")
        if reason is not None:
            assert reason in REASON_VOCAB, (
                f"{c['job']}/{c['step']}: {reason!r} not in {REASON_VOCAB}"
            )


def test_every_local_target_is_a_real_makefile_target() -> None:
    manifest = load_manifest()
    text = MAKEFILE_PATH.read_text()
    target_names = {m.group(1) for m in re.finditer(r"^([A-Za-z0-9_-]+):", text, re.MULTILINE)}
    for c in manifest["check"]:
        local = c.get("local")
        if local:
            assert local in target_names, (
                f"{c['job']}/{c['step']}: local target {local!r} undefined"
            )


def test_makefiles_ci_prerequisites_are_exactly_the_in_make_ci_true_locals() -> None:
    text = MAKEFILE_PATH.read_text()
    m = re.search(r"^ci: ([^\n#]+)", text, re.MULTILINE)
    assert m is not None
    prereqs = frozenset(m.group(1).split())
    manifest = load_manifest()
    declared_true = frozenset(
        c["local"] for c in manifest["check"] if c.get("in_make_ci") is True and c.get("local")
    )
    assert prereqs == declared_true, (prereqs, declared_true)


def test_the_rejected_block_carries_b_r01() -> None:
    manifest = load_manifest()
    rejected = manifest.get("rejected", [])
    ids = {r["id"] for r in rejected}
    assert "B-R01" in ids, "the samples-check-as-a-CI-job rejection must be on the record by id"


def test_no_samples_job_exists_in_ci_yml() -> None:
    """PLAN.md 10.1 rule 5, checked mechanically: CI must never set
    PDF_TOOLKIT_SAMPLES_DIR or run a samples-gated job."""
    text = CI_WORKFLOW.read_text()
    assert "PDF_TOOLKIT_SAMPLES_DIR" not in text
    assert "samples-check" not in text
    assert "samples-gate" not in text


def test_this_module_imports_only_the_pure_validator_from_gate_parity() -> None:
    """AC7's 'different consumer' boundary, mechanized PRECISELY: walks the
    real `ast.ImportFrom` node for `gate_parity` and checks the imported
    NAMES against an allowlist, rather than a substring search over the
    source text -- a substring search for the parser function's own name
    would also match this file's OWN `independent_derive_from_ci` helper
    below, which is unrelated and legitimate (X-183/X-198's lesson)."""
    tree = ast.parse(Path(__file__).read_text())
    allowed = {"REASON_VOCAB", "GatingStep", "validate"}
    saw_gate_parity_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "gate_parity":
            saw_gate_parity_import = True
            imported = {alias.name for alias in node.names}
            assert imported <= allowed, f"imports {imported - allowed}, outside {allowed}"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "yaml", "this module must not import PyYAML -- see docstring"
    assert saw_gate_parity_import, "expected an `from gate_parity import ...` statement"


# --------------------------------------------------------------------------- #
# Proof that validate() itself fires — synthetic data, mirroring
# tests/test_acceptance_audit.py's "proof the gate fires" pattern. These are a
# STANDING regression guard; the LIVE mutation-and-observe controls (AC4-AC6,
# AC8) were run once against the real files in a scratch worktree and are
# recorded in PDF-28's Implementation Log, per HC-4.
# --------------------------------------------------------------------------- #

_BASE_MANIFEST: Final[dict[str, Any]] = {
    "schema_version": 1,
    "check": [
        {"job": "lint", "step": "make lint", "local": "lint", "in_make_ci": True},
    ],
}
_BASE_JOBS: Final[tuple[str, ...]] = ("lint",)
_BASE_STEPS: Final[tuple[GatingStep, ...]] = (
    GatingStep(job="lint", name="make lint", run="make lint"),
)
_BASE_MAKEFILE: Final[str] = "ci: lint ## Run the full local gate\n\nlint: ## Lint\n\ttrue\n"


def test_ac4_proof_an_undeclared_ci_job_reddens() -> None:
    problems = validate(("lint", "noop"), _BASE_STEPS, _BASE_MANIFEST, _BASE_MAKEFILE)
    assert any("noop" in p for p in problems), problems


def test_ac5_proof_a_manifest_entry_for_a_deleted_job_reddens() -> None:
    manifest = {
        "schema_version": 1,
        "check": [
            {"job": "lint", "step": "make lint", "local": "lint", "in_make_ci": True},
            {
                "job": "secret-scan",
                "step": "make secret-scan",
                "local": "secret-scan",
                "in_make_ci": False,
                "reason": "needs-pinned-external-binary",
            },
        ],
    }
    problems = validate(_BASE_JOBS, _BASE_STEPS, manifest, _BASE_MAKEFILE)
    assert any("secret-scan" in p and "does not resolve" in p for p in problems), problems


def test_ac6_proof_an_invented_reason_reddens() -> None:
    manifest = {
        "schema_version": 1,
        "check": [
            {
                "job": "lint",
                "step": "make lint",
                "local": "lint",
                "in_make_ci": True,
                "reason": "because",
            }
        ],
    }
    problems = validate(_BASE_JOBS, _BASE_STEPS, manifest, _BASE_MAKEFILE)
    assert any("because" in p for p in problems), problems


def test_ac6_proof_neither_local_nor_reason_reddens() -> None:
    manifest = {"schema_version": 1, "check": [{"job": "lint", "step": "orphan row"}]}
    problems = validate(_BASE_JOBS, _BASE_STEPS, manifest, _BASE_MAKEFILE)
    assert any("neither" in p for p in problems), problems


def test_ac8_proof_a_narrowed_makefile_ci_line_reddens() -> None:
    narrowed_makefile = "ci: ## Run the full local gate\n\nlint: ## Lint\n\ttrue\n"
    problems = validate(_BASE_JOBS, _BASE_STEPS, _BASE_MANIFEST, narrowed_makefile)
    assert any("lint" in p and "in_make_ci" in p for p in problems), problems


def test_the_base_fixture_itself_agrees() -> None:
    """Non-vacuity for the five proofs above: the UNMUTATED base fixture must
    pass, or every "reddens" assertion above would be trivially true."""
    assert validate(_BASE_JOBS, _BASE_STEPS, _BASE_MANIFEST, _BASE_MAKEFILE) == []


# --------------------------------------------------------------------------- #
# PDF-28 AC1/AC2 — the claim, corrected, and never able to drift back
# --------------------------------------------------------------------------- #


def test_no_claim_site_asserts_local_equals_ci() -> None:
    result = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    tracked_md = [line for line in result.stdout.splitlines() if line.strip()]
    # PLAN.md carries the SAME sixth statement of this claim at §8.1:595 and is
    # operator-owned (OR-13, X-158) -- excluded by name, not by omission. It is
    # not tracked inside apps/pdf-toolkit at all (it lives in the layer repo's
    # ai_plans/pdf-toolkit/PLAN.md, a symlink into ai_docs/), so this glob would
    # never see it regardless; the exclusion below is a named decision anyway.
    #
    # changelog.md is ALSO excluded by name, not by omission, and for a
    # different reason: it is a historical record that must be free to QUOTE a
    # past claim verbatim while correcting it (this spec's own [PDF-28] entry
    # does exactly that, describing what the five sites used to say) -- a
    # doc guard that reddens on a phrase quoted AS the thing being corrected is
    # self-defeating by construction (X-183/X-198's generalization, first
    # produced on this same product: "assert on a computed value, never on a
    # literal the assertion itself spells out"). changelog.md carries no
    # forward-looking claim about `make ci`; only the five live doc sites plus
    # Makefile do, and only those are asserted going forward.
    targets = [
        p for p in (*tracked_md, "Makefile") if Path(p).name not in ("PLAN.md", "changelog.md")
    ]
    for rel in targets:
        text = (REPO_ROOT / rel).read_text()
        m = _CLAIM_PATTERN.search(text)
        assert m is None, f"{rel}: still asserts local==CI ({m.group(0)!r})"


def test_no_claim_site_states_a_count_of_checks_or_targets() -> None:
    """HC-5/AC2: the corrected prose states NO numeral or spelled-out number of
    checks/targets. The count lives in the manifest and in generated epilogue
    output only."""
    count_pattern = re.compile(
        r"\b(seven|10|17|19|ten|seventeen|nineteen)\b\s+(check|target|job|gat(e|ing))",
        re.IGNORECASE,
    )
    for rel in ("README.md", "CLAUDE.md", "CONTRIBUTING.md", "Makefile"):
        text = (REPO_ROOT / rel).read_text()
        m = count_pattern.search(text)
        assert m is None, f"{rel}: states a count ({m.group(0)!r})"


def test_ac1_claim_site_regression_proof() -> None:
    assert _CLAIM_PATTERN.search("the local gate is the ci gate") is not None
    assert _CLAIM_PATTERN.search('"make ci" runs exactly the checks ci runs') is not None
    assert _CLAIM_PATTERN.search("if it is green locally it is green in ci") is not None
    assert _CLAIM_PATTERN.search("make ci is a subset of ci, run with the same commands") is None


# --------------------------------------------------------------------------- #
# PDF-28 AC16 — the coverage floor has one definition, not two
# --------------------------------------------------------------------------- #


def test_the_coverage_floor_is_defined_only_in_the_makefile() -> None:
    text = CI_WORKFLOW.read_text()
    assert text.count("cov-fail-under") == 0, "ci.yml must not re-duplicate the Makefile's floor"
    assert "cov-fail-under=85" in MAKEFILE_PATH.read_text()


# --------------------------------------------------------------------------- #
# PDF-02 AC1/AC2/AC3/AC17 — mechanized (PDF-28 Design §6, AC22)
# --------------------------------------------------------------------------- #

_PDF02_EXPECTED_JOBS: Final[tuple[str, ...]] = (
    "lint",
    "typecheck",
    "test",
    "engines-present",
    "without-engines",
    "sast",
    "vulncheck",
    "secret-scan",
    "license-gate",
    "build",
)


def test_pdf02_ac1_ci_yml_defines_exactly_the_ten_named_jobs() -> None:
    names, _legs, _counts = independent_derive_from_ci()
    assert names == _PDF02_EXPECTED_JOBS, names
    text = CI_WORKFLOW.read_text()
    assert re.search(r"^\s*push:\s*\n\s*branches: \[main\]", text, re.MULTILINE)
    assert "pull_request:" in text
    assert "workflow_dispatch:" in text
    assert "workflow_call:" in text


def test_pdf02_ac2_every_external_action_reference_is_sha_pinned_with_a_version_comment() -> None:
    """The local `uses: ./...` reusable-workflow reference in release.yml is
    the ONE documented exemption (PDF-02's own Implementation Log, 'AC2 — one
    principled, documented exemption'): a local reference always runs at the
    caller's commit and carries no third-party supply-chain risk."""
    workflow_files = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    all_uses = 0
    local_refs = 0
    sha_pinned = 0
    for path in workflow_files:
        text = path.read_text()
        all_uses += len(re.findall(r"^\s*(?:- )?uses:\s", text, re.MULTILINE))
        local_refs += len(re.findall(r"^\s*(?:- )?uses:\s+\./", text, re.MULTILINE))
        for m in re.finditer(
            r"^\s*(?:- )?uses:\s+[^@\s]+@([0-9a-f]{40})\s*(#\s*v\S+)?", text, re.MULTILINE
        ):
            assert m.group(2), f"{path}: SHA {m.group(1)} has no trailing '# vX.Y.Z' comment"
            sha_pinned += 1
    external_uses = all_uses - local_refs
    assert external_uses == sha_pinned, (all_uses, local_refs, sha_pinned)
    assert local_refs == 1, "the local ./ci.yml reference in release.yml is the one exemption"


def test_pdf02_ac3_least_privilege_scoping() -> None:
    """Re-derived at PDF-28 HEAD, not transcribed: `deploy-website.yml` (added
    after PDF-02, by PDF-16) also legitimately carries `id-token: write` for
    its own OIDC-based GitHub Pages deployment -- a second, distinct, correctly
    scoped grant, not a violation of the original criterion's spirit."""
    github_dir = REPO_ROOT / ".github"
    for path in github_dir.rglob("*.yml"):
        assert "write-all" not in path.read_text(), path

    contents_write = []
    id_token_write = []
    for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        for m in re.finditer(r"^(\s*)(contents|id-token): write", path.read_text(), re.MULTILINE):
            (contents_write if m.group(2) == "contents" else id_token_write).append(path.name)

    assert contents_write == ["release.yml"], contents_write
    assert id_token_write == ["deploy-website.yml", "release.yml"], id_token_write


def test_pdf02_ac17_the_two_pdf16_anchors_are_present_exactly_once() -> None:
    dependabot_text = DEPENDABOT_PATH.read_text()
    ci_text = CI_WORKFLOW.read_text()
    assert dependabot_text.count("PDF-16 appends the npm") == 1
    assert ci_text.count("PDF-16 inserts the website licenses.json drift diff") == 1

    # And it sits inside license-gate, after the freshness diff step.
    idx = ci_text.index("PDF-16 inserts the website licenses.json drift diff")
    license_gate_idx = ci_text.index("  license-gate:")
    freshness_diff_idx = ci_text.index("Assert THIRD_PARTY_LICENSES is current")
    build_job_idx = ci_text.index("  build:")
    assert license_gate_idx < freshness_diff_idx < idx < build_job_idx


def test_pdf02_ac6_make_licenses_is_idempotent_on_the_current_interpreter() -> None:
    """The CONSTRUCTED control (PDF-28 AC21): the original criterion's
    'verified locally on 3.14.4' note is stale -- the project venv is 3.12.13
    now (V-8, V-11). Re-derived by running `make licenses` TWICE under
    whichever interpreter is actually active, asserting the generated
    artefacts diff clean, and recording the interpreter alongside."""
    first = subprocess.run(
        ["make", "licenses"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert first.returncode == 0, first.stdout + first.stderr
    second = subprocess.run(
        ["make", "licenses"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert second.returncode == 0, second.stdout + second.stderr
    diff = subprocess.run(
        [
            "git",
            "diff",
            "--exit-code",
            "--",
            "THIRD_PARTY_LICENSES",
            "website/src/data/licenses.json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert diff.returncode == 0, f"make licenses is not idempotent:\n{diff.stdout}"
    interpreter = subprocess.run(
        ["uv", "run", "python", "-V"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert interpreter, "expected a non-empty interpreter version string"


def test_pdf02_ac19_make_secret_scan_refuses_loudly_when_gitleaks_is_absent_from_path() -> None:
    """The CONSTRUCTED control (PDF-28 AC21): gitleaks is now present and
    unpinned on this host (V-5), so AC19's original premise no longer holds.
    A PATH shadow only -- R4: the real /usr/bin/gitleaks binary is never
    touched, moved, or removed.

    `env PATH=/nonexistent make secret-scan` does NOT work as a shell command
    -- `env` execs its target using the NEW environment, so it cannot find
    `make` either (`env: 'make': No such file or directory`), independently
    reproduced. The form that shadows PATH for the RECIPE's subprocesses
    without needing to re-resolve `make` itself is a make command-line
    variable override: `make secret-scan PATH=/nonexistent`. GNU Make passes a
    command-line override of an environment-origin variable through to the
    recipe's own environment, which is exactly the shadow this control needs."""
    result = subprocess.run(
        ["make", "secret-scan", "PATH=/nonexistent"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, result.stdout
    assert "gitleaks is not on PATH" in result.stdout
    assert "will NOT exit 0 pretending that it did" in result.stdout


def test_red_kind_is_a_str_enum_and_the_closed_vocabulary_is_disjoint_from_it() -> None:
    """A cheap cross-module sanity pin: gate-parity's REASON_VOCAB and the
    acceptance audit convention's RedKind are two different closed
    vocabularies for two different questions, and they must not collide on a
    spelling that would make a reader conflate them."""
    reasons = {r.lower() for r in REASON_VOCAB}
    red_kinds = {k.value.lower() for k in RedKind}
    assert reasons.isdisjoint(red_kinds), (reasons, red_kinds)
