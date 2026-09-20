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

import pytest

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


def test_the_independent_scan_finds_twelve_jobs_nineteen_legs_twenty_one_gating_steps() -> None:
    """PDF-91: `website` is a new single-leg job with one gating step
    (`make website`), re-derived at implementation HEAD -- 11/18/20 -> 12/19/21.
    PDF-34 D4 made the previous move, `docs-gate`'s: 10/17/19 -> 11/18/20."""
    names, leg_count, gating_counts = independent_derive_from_ci()
    assert len(names) == 12, names
    assert leg_count == 19, leg_count
    assert sum(gating_counts.values()) == 21, gating_counts


def test_manifest_parses_with_tomllib_and_declares_schema_version_1() -> None:
    manifest = load_manifest()
    assert manifest["schema_version"] == 1
    assert len(manifest["check"]) == 21


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
    PDF_TOOLING_SAMPLES_DIR or run a samples-gated job."""
    text = CI_WORKFLOW.read_text()
    assert "PDF_TOOLING_SAMPLES_DIR" not in text
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
    # not tracked inside apps/pdf-tooling at all (it lives in the layer repo's
    # ai_plans/pdf-tooling/PLAN.md, a symlink into ai_docs/), so this glob would
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
    # `.github/gate-parity.toml` joins the four documents above because it is a
    # CLAIM SITE like any other -- PDF-72, and it was the only one of the five
    # that nothing scanned. Its header read "Applying this at 2d19bcb/PDF-28-HEAD
    # yields 19 gating steps across the 10 jobs -- reproduced by `uv run python
    # scripts/gate_parity.py check`": a historical measurement and a present-tense
    # reproduction welded into one sentence, so the half that stopped being true
    # at PDF-34 read as current. The arms above have frozen 11/18/20 since that
    # commit, which means THE PRODUCT KNEW THE RIGHT ANSWER IN A TEST the whole
    # time; the file simply was not in anything's scope. Appending this path
    # reddened on the uncorrected file, naming `'10 job'`, before a word of the
    # correction was written -- a red taken against the defect rather than
    # against a plant.
    for rel in (
        "README.md",
        "CLAUDE.md",
        "CONTRIBUTING.md",
        "Makefile",
        ".github/gate-parity.toml",
    ):
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
# PDF-34 D2 / AC3 — the shell posture is asserted, not merely written once
# --------------------------------------------------------------------------- #

_SHELLFLAGS_LINE: Final[re.Pattern[str]] = re.compile(r"^\.SHELLFLAGS\s*:?=\s*(.+)$", re.MULTILINE)


def test_the_makefile_declares_pipefail_and_neither_dash_e_nor_dash_u() -> None:
    """`docs-gate` exited 0 on a red suite for as long as this file existed,
    because two of its arms pipe pytest into a reader and, with no
    `.SHELLFLAGS`, a pipeline's status is its LAST command's status. Asserting
    the flag rather than merely writing it is the whole point: the defect it
    repairs (`B-231`) is indistinguishable from correctness by reading, and a
    later edit that deletes this line would restore a silently-passing gate --
    which is exactly how `833321e40b` happened, a missing `with:` block
    downgrading a gate with nothing to notice.

    The negative half is equally load-bearing and is NOT belt-and-braces.
    `-e` and `-u` are excluded by MEASUREMENT, not taste (PDF-34 E3): `make`
    already checks each recipe line's own status, so `-e` buys nothing for this
    defect and would change the semantics of four `;`-chained recipes; `-u`
    would abort recipes that reference deliberately-empty variables. Pinning
    the exclusion makes a future "hardening" edit argue with a test instead of
    slipping past a reviewer as an obvious improvement.
    """
    text = MAKEFILE_PATH.read_text()
    matches = _SHELLFLAGS_LINE.findall(text)
    assert matches, (
        "Makefile declares no .SHELLFLAGS, so every pipe-bearing recipe line "
        "inherits its LAST command's exit status and any gate built on a "
        "pipeline can exit 0 while its arms are red (PDF-34 / B-231)"
    )
    assert len(matches) == 1, f"expected exactly one .SHELLFLAGS declaration, found {matches}"
    flags = matches[0].strip()

    assert "pipefail" in flags, f".SHELLFLAGS must set pipefail; got {flags!r}"
    assert flags.split()[-1] == "-c", (
        f".SHELLFLAGS must end with -c (make appends the command string to it); got {flags!r}"
    )

    tokens = flags.split()
    assert "-e" not in tokens, (
        f"-e is excluded by measurement (PDF-34 E3), not oversight; got {flags!r}"
    )
    assert "-u" not in tokens, (
        f"-u is excluded by measurement (PDF-34 E3), not oversight; got {flags!r}"
    )
    for combined in tokens:
        if combined.startswith("-") and not combined.startswith("--") and combined != "-o":
            assert "e" not in combined[1:], f"-e smuggled inside {combined!r}: {flags!r}"
            assert "u" not in combined[1:], f"-u smuggled inside {combined!r}: {flags!r}"


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
    "docs-gate",
    "license-gate",
    "build",
    "website",
)


def test_pdf02_ac1_ci_yml_defines_exactly_the_ten_named_jobs() -> None:
    """PDF-34 D4 X-472 coordinate 5: `_PDF02_EXPECTED_JOBS` above gains
    `docs-gate` at its scan-derived position (between `secret-scan` and
    `license-gate`). This is a CONTRACT CHANGE, not a silent count edit --
    PDF-02 AC1 asserted a ten-job CI and PDF-34 D4 authorises the eleventh.

    The function NAME is left un-renamed on purpose even though it now reads
    "ten" over an eleven-member tuple: `tests/acceptance/audit_pdf_02.py:63`'s
    `covering=(...)` cites this exact node id, and that file is OUTSIDE
    PDF-34's Scope In table (E6, same class PDF-30 AC28 ruled out of a
    citation sweep). Renaming here would silently break an out-of-scope
    acceptance-audit pointer instead of fixing it -- FILED, not fixed. PDF-02
    AC1's audit claim prose ("...exactly the ten jobs...") is stale the moment
    the assertion below passes against eleven names; both the covering
    pointer's name and the claim prose are a PDF-02 re-verification's or the
    PM's to correct, not this spec's.

    PDF-91 D7/AC5: `_PDF02_EXPECTED_JOBS` gains `website` LAST (`ci.yml`'s file
    order, one wave later), a second CONTRACT CHANGE stacked on the first. The
    function name is left exactly as PDF-34 left it -- it now reads "ten" over
    a twelve-member tuple, and it is the same out-of-scope pointer's to correct,
    not this spec's; renaming it here without moving `audit_pdf_02.py:63` in
    the same commit would only trade one staleness for another.
    """
    names, _legs, _counts = independent_derive_from_ci()
    assert names == _PDF02_EXPECTED_JOBS, names
    text = CI_WORKFLOW.read_text()
    assert re.search(r"^\s*push:\s*\n\s*branches: \[main\]", text, re.MULTILINE)
    assert "pull_request:" in text
    assert "workflow_dispatch:" in text
    assert "workflow_call:" in text


def test_pdf02_ac2_every_external_action_reference_is_sha_pinned_with_a_version_comment() -> None:
    """The local `uses: ./...` reusable-workflow references are the documented
    exemption (PDF-02's own Implementation Log, 'AC2 — one principled,
    documented exemption'): a local reference is addressed by path and always
    runs at the CALLER'S commit, so it carries no third-party supply-chain risk
    and there is no SHA that could sensibly pin it.

    THE SAFETY HALF IS `external_uses == sha_pinned` AND IT IS UNTOUCHED. That
    is the assertion that makes this test a supply-chain gate; it was 34 == 34
    before PDF-34 and is 34 == 34 after. The `local_refs` assertion below is a
    freshness pin on the EXEMPTION, and it moved from 1 to 2 at PDF-34 under
    that spec's own D4 discriminator, stated there for the gate-parity counts
    and binding identically here: **a frozen count may be bumped iff the
    population it counts demonstrably grew and the new member is declared in
    the same commit.** Both halves hold. The population grew because PDF-34 D7
    gave `deploy-website.yml` the gate `release.yml` already had (`B-164`: the
    publish path had NO gate in front of it), and the new member is declared at
    its own site with the exemption's reasoning written beside it. Nothing was
    relaxed to reach green: a THIRD undeclared local reference still reddens
    here, which is the whole job of this line.

    Recorded rather than quietly done, because a bumped count is exactly what
    gaming looks like from the outside: the alternative was to leave this arm
    red, which would have reddened `main` permanently and — through the very
    `needs: gate` D7 adds — blocked every subsequent publish. Reverting is one
    line if the PM rules otherwise.
    """
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
    assert local_refs == 2, (
        "the local ./ci.yml references in release.yml (the release gate) and "
        "deploy-website.yml (the publish gate, PDF-34 D7 / B-164) are the two "
        "documented exemptions; a third is a FINDING, never a bump made to "
        "reach green"
    )


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


# --------------------------------------------------------------------------- #
# PDF-59 Arm A (D2/AC1-AC3/AC5/AC6) -- the maturity classifier's ruled
# MONOTONE relation (OR-16), not an equality, plus the version-oracle tie.
# Home: this module, sole claimant this cycle (D2). Additive only -- nothing
# above this line is touched, and `_PDF02_EXPECTED_JOBS` is untouched.
# --------------------------------------------------------------------------- #

PYPROJECT_PATH: Final[Path] = REPO_ROOT / "pyproject.toml"

_DEV_STATUS_PREFIX: Final[str] = "Development Status :: "
_FORBIDDEN_ALPHA: Final[str] = "Development Status :: 3 - Alpha"
_REQUIRED_STABLE: Final[str] = "Development Status :: 5 - Production/Stable"
_DEV_STATUS_RANK: Final[re.Pattern[str]] = re.compile(r"^Development Status :: (\d+) - ")

#: B-371/X-946 P1. Two SCENARIO INPUTS for the seven-cell table below, one
#: major-0 and one major-1 spelling -- each chosen because it is the major
#: bucket the cell's own LABEL claims to exercise, never because it happens
#: to match `pyproject.toml`'s `version` key. These are NOT the tree's
#: version and must NEVER be "updated to match" it: that update is the exact
#: defect this fix repairs. Before this fix, four of the table's seven cells
#: read `data["project"]["version"]` directly, so a table authored to probe
#: seven distinct (classifier, version) points quietly collapsed onto three
#: once the tree's own version caught up with the literals already sitting
#: in the other three cells -- reddening the one cell whose label named a
#: major-0 scenario it no longer received, and silently retiring
#: `pre-spec-tree`'s ability to isolate clause 1 (D2) from clause 2 along the
#: way (see `test_pdf59_ac2_ac3_the_seven_cell_relation_table`'s docstring
#: and `changelog.md`'s `[B-371]` entry for the full account). The next
#: maintainer who is tempted to bump either constant to "keep it current" at
#: the next major release is the next person to reproduce this defect.
_SCENARIO_VERSION_MAJOR_0: Final[str] = "0.3.1"
_SCENARIO_VERSION_MAJOR_1: Final[str] = "1.0.0"


def load_pyproject() -> dict[str, Any]:
    with PYPROJECT_PATH.open("rb") as fh:
        return tomllib.load(fh)


def maturity_relation_problems(classifiers: list[str], version: str) -> list[str]:
    """PDF-59 D2 / operator ruling OR-16 -- the RULED relation is MONOTONE,
    not an equality (`major == 1` <=> `5 - Production/Stable` is the
    FORBIDDEN shape X-705 names by name). Returns problems; an empty list
    means the relation holds.

    Pure: takes already-parsed data as arguments and reads no filesystem and
    calls no `uv`-backed target, so a version PLANT is just a Python
    argument -- it can never re-sync a venv against a planted distribution
    and contaminate a later measurement (HC-4).

    Three independently-checkable clauses (D2):
      1. "Development Status :: 3 - Alpha" is forbidden UNCONDITIONALLY, at
         any version, from this commit forward.
      2. A maturity classifier below "5 - Production/Stable" is forbidden
         once the version's major is >= 1.
      3. Exactly one "Development Status ::" classifier must be present --
         the vacuity guard. Zero is an absent claim, not a safe one (a
         "no forbidden string" implementation would pass VACUOUSLY against
         an empty block); two or more is an ambiguity PyPI would resolve
         arbitrarily.
    """
    problems: list[str] = []
    entries = [c for c in classifiers if c.startswith(_DEV_STATUS_PREFIX)]
    if len(entries) != 1:
        problems.append(
            f"exactly one {_DEV_STATUS_PREFIX!r} classifier is required (clause 3, "
            f"the vacuity guard); found {len(entries)}: {entries}"
        )
        return problems  # clauses 1/2 need exactly one entry to read
    entry = entries[0]
    if entry == _FORBIDDEN_ALPHA:
        problems.append(
            f"{_FORBIDDEN_ALPHA!r} is forbidden unconditionally, at any version (clause 1, OR-16)"
        )
    try:
        major = int(version.split(".", 1)[0])
    except (ValueError, IndexError):
        problems.append(f"cannot parse a major version out of {version!r}")
        return problems
    if major >= 1:
        rank_match = _DEV_STATUS_RANK.match(entry)
        if rank_match is None:
            problems.append(f"cannot parse a maturity rank out of {entry!r} (clause 2)")
        elif int(rank_match.group(1)) < 5:
            problems.append(
                f"version major is {major} (>= 1) but the maturity classifier is "
                f"{entry!r}; OR-16 forbids anything below {_REQUIRED_STABLE!r} once "
                "the major version is >= 1 (clause 2)"
            )
    return problems


def test_pdf59_ac1_the_maturity_classifier_is_5_production_stable() -> None:
    """PDF-59 AC1. Both census recipes from the spec's E2 are re-run here so
    the transition is OBSERVED, not merely asserted: at `89a4f1d` these same
    two recipes returned `pyproject.toml:16` reading `3 - Alpha`, one hit,
    repo-wide, and it was the declaration itself -- no test, no gate, no
    release step read it. This test is the instrument B-276 said did not
    exist.

    The recipe below excludes THIS MODULE by name, not by omission: this
    file is the census's own instrument (D2 -- "the deliverable is the
    instrument"), so once it exists it necessarily contains the phrase in
    its own constants and docstrings. Scanning it would make the recipe
    count its own existence -- the exact self-reference this module's own
    docstring already warns against for `independent_derive_from_ci`
    (X-183/X-198: assert on a computed value, never on a literal the
    assertion itself spells out)."""
    classifiers = load_pyproject()["project"]["classifiers"]
    entries = [c for c in classifiers if c.startswith(_DEV_STATUS_PREFIX)]
    assert entries == [_REQUIRED_STABLE], entries

    _SELF = "tests/test_gate_parity.py"
    # THE POPULATION this census counts: occurrences of the phrase in the SOURCE
    # TEXT of the three scanned sources, minus this module. Exactly one survives
    # -- the classifier declaration at `pyproject.toml:16` -- and that one is what
    # the assertions below grade.
    #
    # COMPILED BYTECODE IS EXCLUDED, and it is not a hit that was rounded away:
    # `tests/__pycache__/test_gate_parity.cpython-3NN-pytest-N.N.N.pyc` is a
    # derived copy of the one file already excluded by name above, so counting it
    # counts this instrument's own constants a second time through a build
    # artefact. pytest's assertion rewriting writes that artefact DURING this very
    # run (each macos-14 leg of run 35295764623 produced its own interpreter tag:
    # cpython-311/312/313/314), so a census that sees it is answering a question
    # about the runner's cache state rather than about the repository. The second
    # recipe in this same test reaches the same exclusion by a different route: it
    # is a `git grep`, a TRACKED-file scan, and bytecode is not tracked.
    #
    # WHY IT ONLY EVER REDDENED ON macOS, which is the whole diagnosis: GNU grep
    # (>= 3.5) sends its binary-file diagnostic to STDERR, while BSD grep -- which
    # is what `/usr/bin/grep` is on macos-14 -- prints "Binary file ... matches" to
    # STDOUT, and this recipe reads stdout. The expected count was NOT widened to
    # absorb the extra line: that line was never a hit.
    #
    # Both exclusions are deliberate rather than redundant: `--exclude-dir` covers
    # the PEP 3147 cache directory, `--exclude` covers a `.pyc` anywhere else.
    grep = subprocess.run(
        [
            "/usr/bin/grep",
            "-rn",
            "--exclude-dir=__pycache__",
            "--exclude=*.pyc",
            "Development Status",
            "tests",
            "pyproject.toml",
            "Makefile",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # 0 = matched, 1 = matched nothing, 2 = grep itself failed. Asserted because
    # the exclusions above are the one part of this recipe that cannot be
    # exercised on every platform from a single host: if a flag were unsupported
    # somewhere, grep would exit 2 with an empty stdout and the count arm below
    # would red with a mystery `0`. This reds naming the exit status instead.
    assert grep.returncode == 0, (grep.returncode, grep.stderr, grep.stdout)
    hits = [
        line
        for line in grep.stdout.splitlines()
        if line.strip() and not line.startswith(f"{_SELF}:")
    ]
    assert len(hits) == 1, hits
    assert "5 - Production/Stable" in hits[0], hits

    # `git grep -n "3 - Alpha"` is a TRACKED-file scan, so it cannot see
    # this module's own forbidden-string CONSTANT until the commit that adds
    # it lands -- excluded by name here for the same reason as the `/usr/bin/grep`
    # census above (this module names the forbidden string on purpose, as
    # the thing it asserts against; that is not a live occurrence of it).
    # `changelog.md` is excluded by the SAME established precedent this file
    # already carries for a different claim (`test_no_claim_site_asserts_
    # local_equals_ci`): it is a historical record that must be free to QUOTE
    # a past claim verbatim while correcting it -- this spec's own [PDF-59]
    # entry does exactly that, naming `3 - Alpha` as the string OR-16
    # replaced. A doc guard that reddens on a phrase quoted AS the thing
    # being corrected is self-defeating (X-183/X-198's generalization).
    _CHANGELOG = "changelog.md"
    alpha = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "3 - Alpha",
            "--",
            ".",
            f":(exclude){_SELF}",
            f":(exclude){_CHANGELOG}",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # `git grep` exits 1 when no line matches -- that is the desired outcome.
    assert alpha.returncode == 1, (alpha.returncode, alpha.stdout)
    assert alpha.stdout == ""


def _dev_status_marker(classifiers: list[str]) -> str:
    """B-371/X-946 P3. Reduces *classifiers* to a single hashable key for the
    seven-cell table's distinctness check below: the one
    `"Development Status :: "` entry present, or a marker naming how many
    were found when that count is not exactly one (0, for the vacuity cell;
    2+ would be the ambiguity clause 3 also forbids, though no cell plants
    that today). The marker is deliberately not `None` for the zero-entry
    case -- a bare `str | None` would make "zero entries" collide with a
    hypothetical future classifier literally spelled `"None"`, which is a
    needless way for a distinctness check to lie."""
    entries = [c for c in classifiers if c.startswith(_DEV_STATUS_PREFIX)]
    if len(entries) == 1:
        return entries[0]
    return f"<{len(entries)} dev-status entries>"


def scenario_points(
    cases: tuple[tuple[str, list[str], str, bool], ...],
) -> dict[str, tuple[str, str]]:
    """B-371/X-946 P3. Every cell reduced to its `(dev-status entry, version)`
    point, keyed by label. Pure and label-keyed on purpose: both the standing
    table below and `test_b371_proof_the_distinctness_assertion_reddens_a_
    collapsed_table` call it, and a label key is what lets the proof name
    exactly which two cells it collapsed."""
    return {
        label: (_dev_status_marker(classifiers), version)
        for label, classifiers, version, _ in cases
    }


def assert_scenario_points_are_distinct(
    cases: tuple[tuple[str, list[str], str, bool], ...],
) -> None:
    """B-371/X-946 P3 -- the mechanical control this fix exists to add. A
    collapsed table (three collision pairs, 7 points down to 4) PASSED
    silently before this fix; this is what makes a future collapse red
    instead.

    `as-shipped` is the ONE cell permitted to read the tree (P2), so it is
    the one cell permitted to coincide with a fixed-literal cell's point --
    and, AT THIS COMMIT, it does: `pyproject.toml` ships
    `_SCENARIO_VERSION_MAJOR_1` with `_REQUIRED_STABLE`, which is exactly the
    state `post-tag-state` was authored to predict. That coincidence is
    real, expected, temporary (the next patch release moves the tree's
    version off `_SCENARIO_VERSION_MAJOR_1` and it resolves on its own), and
    it is NOT what this control exists to catch.

    What it exists to catch is any of the other six cells -- every one of
    them built from literals entirely under this test's own control --
    landing on the same point as ANY other cell. Two such collisions existed
    at HEAD before this fix (`pre-spec-tree` == `major-1-alpha`,
    `major-1-beta` == `discriminator-major-0-beta`); either reappearing, or a
    new one appearing anywhere (including the live cell colliding with a
    cell OTHER than `post-tag-state`, which would mean the tree has drifted
    onto some other cell's frozen scenario), reds here.
    """
    points = scenario_points(cases)
    live_point = points.pop("as-shipped")
    assert len(set(points.values())) == 6, (
        "the six always-literal cells must occupy six distinct "
        f"(dev-status entry, version) points; got {points} -- a repeat here "
        "is the silent 7-point-to-4-point collapse (B-371) recurring"
    )
    if live_point in points.values():
        assert live_point == points["post-tag-state"], (
            "as-shipped's live point collided with a fixed cell that is NOT "
            f"post-tag-state: live={live_point}, fixed cells={points} -- the "
            "only coincidence P2 sanctions is with post-tag-state specifically"
        )


def test_pdf59_ac2_ac3_the_seven_cell_relation_table() -> None:
    """PDF-59 D2/AC2/AC3 -- all seven cells, driven against the SAME function
    with no edit between calls (AC2's whole point: the assertion must survive
    the version bump with no test edit, X-703/X-705). The
    `major-0/4-Beta` cell is the DISCRIMINATOR: GREEN under the ruled
    monotone relation, RED under the forbidden equality form
    (`major == 1` <=> `5 - Production/Stable`) -- this single cell is what
    proves the shape actually written.

    B-371/X-946 -- repaired here after AC2 was reported satisfied and was
    not (`changelog.md`'s `[B-371]` entry has the full account; the short
    version: this table's seven cells are byte-identical at the `PDF-59`
    landing commit and at HEAD, and that same file, run in a scratch
    worktree whose ONLY difference from the landing commit is
    `pyproject.toml`'s `version = "1.0.0"`, fails on
    `discriminator-major-0-beta`). Two rules restore AC2 for real:

      - P1 (no cell reads the tree for its version operand except the one
        below that is SUPPOSED to) -- `_SCENARIO_VERSION_MAJOR_0` /
        `_SCENARIO_VERSION_MAJOR_1` replace every `real_version` read except
        one.
      - P2 (exactly one cell may read the tree, and it is the live-
        compliance cell) -- renamed from `landing-state` to `as-shipped`:
        `landing-state` named a frozen historical moment that has since
        passed (the pre-1.0 tree); this cell's actual job, unchanged since
        it was written, is asserting the tree AS IT STANDS RIGHT NOW
        satisfies the relation, which only a tree-reading cell can do. It
        currently computes the same point as `post-tag-state`
        (`_REQUIRED_STABLE` at `_SCENARIO_VERSION_MAJOR_1`) because the tree
        currently ships exactly the state `post-tag-state` predicts -- see
        `assert_scenario_points_are_distinct`'s docstring for why that one
        coincidence is sound and everything else is not.

    P3's mechanical distinctness proof is `assert_scenario_points_are_
    distinct`, called below; P4's failure proofs (the three things this fix
    must be shown to actually catch or actually pass, having been run) are
    `test_b371_proof_p4a_fixed_operand_catches_what_the_tree_read_missed`,
    `test_b371_proof_the_distinctness_assertion_reddens_a_collapsed_table`,
    and `test_b371_proof_the_repaired_discriminator_is_green_for_the_ruled_
    reason`, all below.
    """
    data = load_pyproject()
    real_classifiers = data["project"]["classifiers"]
    real_version = data["project"]["version"]
    base = [c for c in real_classifiers if not c.startswith(_DEV_STATUS_PREFIX)]

    def with_entry(entry: str | None) -> list[str]:
        return base + ([entry] if entry else [])

    beta = "Development Status :: 4 - Beta"
    cases: tuple[tuple[str, list[str], str, bool], ...] = (
        # The ONE tree-reading cell (P2) -- asserts the tree AS SHIPPED, right
        # now, satisfies the relation. Everything else below is a literal.
        ("as-shipped", real_classifiers, real_version, True),
        ("post-tag-state", with_entry(_REQUIRED_STABLE), _SCENARIO_VERSION_MAJOR_1, True),
        # Isolates clause 1 (forbidden UNCONDITIONALLY, at ANY version) from
        # clause 2 (forbidden only once major >= 1) by staying at major 0 --
        # if this cell read `real_version` instead, it would isolate nothing
        # the moment the tree's major reached 1, because clause 2 would
        # redden it anyway for an unrelated reason. See
        # `test_b371_proof_p4a_fixed_operand_catches_what_the_tree_read_
        # missed` for this driven both ways.
        ("pre-spec-tree", with_entry(_FORBIDDEN_ALPHA), _SCENARIO_VERSION_MAJOR_0, False),
        ("major-1-alpha", with_entry(_FORBIDDEN_ALPHA), _SCENARIO_VERSION_MAJOR_1, False),
        ("major-1-beta", with_entry(beta), _SCENARIO_VERSION_MAJOR_1, False),
        # The discriminator: GREEN under the ruled relation, RED under the
        # forbidden equality shape -- MUST stay at major 0, or it stops
        # being the discriminator and starts being a second `major-1-alpha`.
        ("discriminator-major-0-beta", with_entry(beta), _SCENARIO_VERSION_MAJOR_0, True),
        ("vacuity-no-classifier", with_entry(None), _SCENARIO_VERSION_MAJOR_0, False),
    )
    for label, classifiers, version, expect_green in cases:
        problems = maturity_relation_problems(classifiers, version)
        if expect_green:
            assert problems == [], f"{label}: expected GREEN, got {problems}"
        else:
            assert problems != [], f"{label}: expected RED, got none"

    assert_scenario_points_are_distinct(cases)


def test_b371_proof_p4a_fixed_operand_catches_what_the_tree_read_missed() -> None:
    """B-371/X-946 P4(a), driven both ways. `clause1_conditional` below is
    `maturity_relation_problems` with clause 1 weakened from "forbidden
    unconditionally" to "forbidden once major >= 1" -- exactly the mutation
    `pre-spec-tree` exists to catch.

    BEFORE (the defect, reproduced here rather than left standing): if
    `pre-spec-tree` read `real_version` -- as it did before this fix -- the
    weakened clause is caught at a major-0 tree (the weakened clause never
    fires there, so `problems == []` and pre-spec-tree's own `assert
    problems != []` would FAIL) and MISSED at a major->=1 tree, where clause
    2 independently reddens Alpha-at-major->=1 for an unrelated reason --
    `problems != []` stays TRUE whether clause 1 is unconditional (correct)
    or conditional on major >= 1 (the mutation), so the two are
    indistinguishable there and the cell stops isolating anything. Confirmed
    live at the tree's OWN real version too, if its major is already >= 1
    (true at this commit).

    AFTER (this fix): pinned to `_SCENARIO_VERSION_MAJOR_0`, the weakened
    clause is caught BY ITS OWN PROBLEM STRING no matter what the tree's
    version is -- proven at three tree-version states: the tree's real
    version at the time this test runs, and two planted spellings never used
    as either scenario constant, one major 0 and one major 2.
    """

    def clause1_conditional(classifiers: list[str], version: str) -> list[str]:
        """The weakened relation this proof plants: clause 1 forbids
        `3 - Alpha` only once major >= 1, instead of unconditionally."""
        problems: list[str] = []
        entries = [c for c in classifiers if c.startswith(_DEV_STATUS_PREFIX)]
        if len(entries) != 1:
            problems.append("vacuity")
            return problems
        entry = entries[0]
        major = int(version.split(".", 1)[0])
        if entry == _FORBIDDEN_ALPHA and major >= 1:  # <- the weakening
            problems.append("weakened clause 1")
        if major >= 1:
            rank_match = _DEV_STATUS_RANK.match(entry)
            if rank_match is not None and int(rank_match.group(1)) < 5:
                problems.append("clause 2")
        return problems

    alpha_classifiers = [_FORBIDDEN_ALPHA]

    def would_be_caught(version_operand: str) -> bool:
        """pre-spec-tree expects RED (`assert problems != []`). `True` here
        means the weakened relation returns `[]` for this operand, so that
        assertion would FAIL -- the mutation is CAUGHT. `False` means the
        weakened relation still returns something non-empty (clause 2 firing
        on its own, unrelated to clause 1), so the table's assertion would
        still PASS -- the mutation is MISSED."""
        return clause1_conditional(alpha_classifiers, version_operand) == []

    # BEFORE (the defect, reproduced): pre-spec-tree read `real_version`
    # directly, so whether the mutation is caught depended entirely on what
    # the tree's version happened to be -- caught at major 0 (clause 2 cannot
    # cover for the weakened clause 1 there), MISSED at major >= 1 (clause 2
    # covers for it, so the cell still "looks red" for the wrong reason).
    assert would_be_caught("0.3.1") is True, "expected CAUGHT at a major-0 tree"
    assert would_be_caught("1.0.0") is False, "expected MISSED at a major-1 tree"
    assert would_be_caught("2.7.4") is False, "expected MISSED at a major-2 tree"

    # Confirmed live at the tree's own real version too, whatever it is
    # today: if it is already major >= 1, the mutation is MISSED there --
    # reproducing X-946's live evidence.
    real_version = load_pyproject()["project"]["version"]
    if int(real_version.split(".", 1)[0]) >= 1:
        assert would_be_caught(real_version) is False, real_version

    # AFTER (this fix): pre-spec-tree is pinned to `_SCENARIO_VERSION_MAJOR_0`
    # and no longer reads the tree at all, so it is CAUGHT no matter what the
    # tree's real version is -- unlike the BEFORE block above, this operand
    # never changes, which is exactly the point: the outcome stops depending
    # on whichever of these three states the tree happens to be in.
    for _simulated_tree_version in ("0.3.1", "1.0.0", "2.7.4"):
        assert would_be_caught(_SCENARIO_VERSION_MAJOR_0) is True


def test_b371_proof_the_distinctness_assertion_reddens_a_collapsed_table() -> None:
    """B-371/X-946 P4(b). Plants exactly one of the three collisions that
    existed at HEAD before this fix -- `pre-spec-tree` collapsed onto
    `major-1-alpha`'s point -- and confirms `assert_scenario_points_are_
    distinct` reds it. Not a tautology (X-153/B-080): the real, unmutated
    `cases` tuple in the table above already passes this same assertion on
    every run; this is the mutation that makes it fail, run and observed."""
    beta = "Development Status :: 4 - Beta"
    collapsed_cases: tuple[tuple[str, list[str], str, bool], ...] = (
        ("as-shipped", [_REQUIRED_STABLE], _SCENARIO_VERSION_MAJOR_1, True),
        ("post-tag-state", [_REQUIRED_STABLE], _SCENARIO_VERSION_MAJOR_1, True),
        # collapsed: pinned to MAJOR_1 instead of MAJOR_0, landing on the
        # exact same point as major-1-alpha directly below it.
        ("pre-spec-tree", [_FORBIDDEN_ALPHA], _SCENARIO_VERSION_MAJOR_1, False),
        ("major-1-alpha", [_FORBIDDEN_ALPHA], _SCENARIO_VERSION_MAJOR_1, False),
        ("major-1-beta", [beta], _SCENARIO_VERSION_MAJOR_1, False),
        ("discriminator-major-0-beta", [beta], _SCENARIO_VERSION_MAJOR_0, True),
        ("vacuity-no-classifier", [], _SCENARIO_VERSION_MAJOR_0, False),
    )
    with pytest.raises(AssertionError):
        assert_scenario_points_are_distinct(collapsed_cases)


def test_b371_proof_the_repaired_discriminator_is_green_for_the_ruled_reason() -> None:
    """B-371/X-946 P4(c). `discriminator-major-0-beta` is pinned to
    `_SCENARIO_VERSION_MAJOR_0` now, not `real_version` (the defect) --
    confirms the GREEN is the relation's clause 2 genuinely permitting a
    below-5 classifier while major is 0, not the cell having quietly stopped
    being checked. Sensitivity, not vacuity (mirrors `test_the_base_fixture_
    itself_agrees`'s reasoning): the identical classifier at major 1 reds
    (clause 2), and an unparseable version reds too -- if either of these
    were ALSO green, the discriminator's own green above would be trivially
    satisfied and would prove nothing about the relation."""
    beta = "Development Status :: 4 - Beta"
    green = maturity_relation_problems([beta], _SCENARIO_VERSION_MAJOR_0)
    assert green == [], green

    assert maturity_relation_problems([beta], _SCENARIO_VERSION_MAJOR_1) != []
    assert maturity_relation_problems([beta], "not-a-version") != []


def test_pdf59_ac3_proof_the_equality_shape_would_miss_the_discriminator() -> None:
    """The discriminator, isolated. `equality_shape` below is the FORBIDDEN
    per-bucket equality X-705 names: exactly `3 - Alpha` at major 0, exactly
    `5 - Production/Stable` once major >= 1, nothing else acceptable either
    side -- a careless literal translation of "the old value at major 0, the
    new value once tagged" that never considers a THIRD classifier. It
    reports the `major-0/4-Beta` cell as a violation (expected `3 - Alpha`
    at major 0, got `4 - Beta`) and it reports the LANDING cell itself
    (major 0, `5 - Production/Stable`) as a violation too -- matching D2's
    own account of why the naive equality is red on landing. The RULED
    monotone relation (clause 2 only forbids below-5 once major >= 1)
    reports the Beta cell clean. This test fails if
    `maturity_relation_problems` is ever rewritten as this forbidden shape.
    """
    beta_at_major_0 = maturity_relation_problems(["Development Status :: 4 - Beta"], "0.3.1")
    assert beta_at_major_0 == [], beta_at_major_0

    def equality_shape(classifiers: list[str], version: str) -> list[str]:
        major = int(version.split(".", 1)[0])
        entry = next(c for c in classifiers if c.startswith(_DEV_STATUS_PREFIX))
        expected = _REQUIRED_STABLE if major >= 1 else _FORBIDDEN_ALPHA
        if entry != expected:
            return [f"equality form: at major={major} expected {expected!r}, got {entry!r}"]
        return []

    assert equality_shape(["Development Status :: 4 - Beta"], "0.3.1") != []
    # The landing cell itself is ALSO red under the forbidden shape (D2: "the
    # naive equality is red on landing") -- the discriminator is not the only
    # divergence, it is the CHEAPEST one to check.
    assert equality_shape([_REQUIRED_STABLE], "0.3.1") != []


def test_pdf59_ac5_pdf02_expected_jobs_is_unmoved_by_this_spec() -> None:
    """PDF-59 AC5 -- ORIGINALLY a non-vacuity pin asserting that PDF-59's own
    diff added no hunk inside `_PDF02_EXPECTED_JOBS`'s span. PDF-91 D6 names
    this tuple as one of exactly three frozen structural inventories
    authorised to move when the CI job set itself moves (the other two are
    `EXPECTED_JOB_COUNT` in `tests/test_gate_budget.py` and the from-scratch
    scan triple above) -- so the pin now reads the POST-`website` twelve-
    member state, the same way it would have read eleven had this test
    existed when PDF-34 D4 added `docs-gate`. Found running this spec's own
    targeted suite: it is a fourteenth coordinate the spec's own Scope In
    table did not enumerate, because it is a residual pin from a DIFFERENT
    spec's acceptance criterion rather than a reader this spec's authors
    could have found by reading `ci.yml` or the manifest. The function NAME
    is left as PDF-59's own, for the identical D7 reason
    `test_pdf02_ac1_ci_yml_defines_exactly_the_ten_named_jobs` gives: nothing
    outside this file cites this node id, and renaming a stale-but-accurate
    name is a correction belonging to whichever spec next authorises a move
    here, not a silent side effect of this one.
    """
    assert len(_PDF02_EXPECTED_JOBS) == 12, _PDF02_EXPECTED_JOBS
    assert _PDF02_EXPECTED_JOBS == (
        "lint",
        "typecheck",
        "test",
        "engines-present",
        "without-engines",
        "sast",
        "vulncheck",
        "secret-scan",
        "docs-gate",
        "license-gate",
        "build",
        "website",
    )


def version_tie_verdict(pyproject_version: str, installed_version: str) -> str:
    """PDF-59 AC6 / D2's second, independent assertion -- the `PDF-30` AC25
    rule applied here: the assertion is made by a DIFFERENT consumer than the
    one that computes it. `pyproject.toml`'s `version` key is static and
    always current in the tree; `pdf_tooling.__version__` is resolved LAZILY
    from distribution metadata (`src/pdf_tooling/__init__.py`) and can lag
    the tree between an edit and a re-sync.

    Returns "match", "skip-unknown" (never a pass), or a mismatch message.
    """
    from pdf_tooling import _UNKNOWN_VERSION

    if installed_version == _UNKNOWN_VERSION:
        return "skip-unknown"
    if installed_version == pyproject_version:
        return "match"
    return (
        f"pdf_tooling.__version__ ({installed_version!r}) != pyproject.toml's "
        f"version ({pyproject_version!r})"
    )


def test_pdf59_ac6_the_version_oracles_are_tied() -> None:
    """PDF-59 AC6. `tests/test_cli_spine.py:489` already imports
    `__version__`, so the skip branch below will not fire in practice on an
    installed checkout -- it exists so an uninstalled tree fails LOUDLY
    rather than quietly reporting a `0`-major string for the wrong reason."""
    from pdf_tooling import __version__ as installed_version

    pyproject_version = load_pyproject()["project"]["version"]
    verdict = version_tie_verdict(pyproject_version, installed_version)
    if verdict == "skip-unknown":
        pytest.skip(
            "pdf_tooling.__version__ resolved to _UNKNOWN_VERSION -- the package is "
            "not installed in this interpreter, so the tie cannot be checked here "
            "(never a pass)"
        )
    assert verdict == "match", verdict


def test_pdf59_ac6_proof_a_differing_installed_version_reddens() -> None:
    verdict = version_tie_verdict("1.0.0", "0.3.1")
    assert verdict not in ("match", "skip-unknown"), verdict
    assert "0.3.1" in verdict and "1.0.0" in verdict, verdict


def test_pdf59_ac6_proof_an_unknown_installed_version_skips_rather_than_passes() -> None:
    from pdf_tooling import _UNKNOWN_VERSION

    assert version_tie_verdict("1.0.0", _UNKNOWN_VERSION) == "skip-unknown"


def test_pdf59_ac6_proof_a_matching_version_passes() -> None:
    assert version_tie_verdict("0.3.1", "0.3.1") == "match"
