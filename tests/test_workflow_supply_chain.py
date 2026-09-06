"""Workflow supply-chain criteria — PDF-45.

Two audit findings, each landed with a criterion a later edit cannot silently
undo, and each asserted over the PARSED workflow rather than over its text.

**Why a new module rather than an append to `tests/test_gate_parity.py`.**
That module declares its ci.yml job census *deliberately* regex-based, as an
independent from-scratch cross-check of a manifest; that independence is scoped
to the census and must not be disturbed. The criteria here need STRUCTURAL
parsing, because a permission grant's *level* is a tree property and not a text
property. Path constants below are re-derived locally from `REPO_ROOT` rather
than imported, so a restructuring of that module cannot break this one.

**The blindness this module exists to cover, recorded so the next reader knows
which instrument covers which half.** `test_gate_parity.py`'s
`test_pdf02_ac3_least_privilege_scoping` is the pre-existing least-privilege
guard. It captures the indentation of each `contents|id-token: write` match in
a group and then never uses it, asserting a list of *file names*. It is green
with the Pages grant at workflow level and green, unchanged, with the grant
scoped to the `deploy` job -- one `id-token: write` match in the file either
way. The repository's own least-privilege guard therefore could not distinguish
the defect from the fix. That test is **not** deleted, weakened or "upgraded"
here: it asserts a real and distinct proposition (*which files* carry a write
grant) and it stays green across this change. This module asserts the property
it cannot see (*at which LEVEL*, and *which job*).

**Anti-lapse.** Every assertion below is preceded by a check that the thing it
examines was actually found: the parse yields a mapping with a non-empty
`jobs`, `build` and `deploy` both exist, and the gitleaks step locator matches
exactly once. A locator that matches nothing is a FAILURE here, never a skip --
a criterion by absence is otherwise satisfied by an instrument that cannot see.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

import yaml

# Re-derived locally (PDF-45 D3), NOT imported from tests.test_gate_parity.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
CI_WORKFLOW: Final[Path] = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEPLOY_WORKFLOW: Final[Path] = REPO_ROOT / ".github" / "workflows" / "deploy-website.yml"

#: The two scopes this spec moves. `contents` is deliberately NOT here: the
#: criterion constrains where the WRITE scopes may live, and `deploy` gaining a
#: `contents: read` of its own is an explicitly permitted remedy (PDF-45 D1).
WRITE_SCOPES: Final[tuple[str, ...]] = ("pages", "id-token")

GITLEAKS_STEP_NAME: Final[str] = "Install pinned gitleaks"


def _load(path: Path) -> dict[str, Any]:
    """Parse a workflow, refusing to return anything an assertion could pass on
    vacuously."""
    assert path.is_file(), f"{path} does not exist -- the locator, not the criterion, failed"
    doc = yaml.safe_load(path.read_text())
    assert isinstance(doc, dict), f"{path}: parsed to {type(doc).__name__}, not a mapping"
    jobs = doc.get("jobs")
    assert isinstance(jobs, dict) and jobs, f"{path}: `jobs` is missing or empty -- {jobs!r}"
    return doc


def _jobs(doc: dict[str, Any]) -> dict[str, Any]:
    jobs: dict[str, Any] = doc["jobs"]
    return jobs


def _job_permissions(job: Any) -> dict[str, Any]:
    """A job's own `permissions` mapping, or `{}` when it declares none.

    A non-mapping form (`permissions: read-all`, `permissions: {}`) is returned
    as an empty mapping so the write-scope search below cannot be fooled by it;
    `read-all` grants no write scope, and `write-all` is separately banned by
    `test_gate_parity.py`.
    """
    if not isinstance(job, dict):
        return {}
    perms = job.get("permissions")
    return perms if isinstance(perms, dict) else {}


def _gitleaks_step() -> dict[str, Any]:
    """The `Install pinned gitleaks` step, with a locator that cannot lapse."""
    doc = _load(CI_WORKFLOW)
    raw = CI_WORKFLOW.read_text()
    occurrences = raw.count(f"name: {GITLEAKS_STEP_NAME}")
    assert occurrences == 1, (
        f"the step locator {GITLEAKS_STEP_NAME!r} matched {occurrences} times in ci.yml; "
        "exactly one is required, so a rename FAILS here instead of silently "
        "leaving this module covering nothing"
    )
    job = _jobs(doc).get("secret-scan")
    assert isinstance(job, dict), "ci.yml has no `secret-scan` job"
    steps = job.get("steps")
    assert isinstance(steps, list) and steps, "the secret-scan job declares no steps"
    hits = [s for s in steps if isinstance(s, dict) and s.get("name") == GITLEAKS_STEP_NAME]
    assert len(hits) == 1, f"parsed step locator matched {len(hits)} steps, expected exactly 1"
    return hits[0]


def _gitleaks_script_lines() -> list[str]:
    step = _gitleaks_step()
    run = step.get("run")
    assert isinstance(run, str) and run.strip(), f"{GITLEAKS_STEP_NAME}: empty or missing `run:`"
    return [ln for ln in run.splitlines() if ln.strip()]


def _index_of(lines: list[str], needle: str) -> int:
    matches = [i for i, ln in enumerate(lines) if needle in ln]
    assert len(matches) == 1, (
        f"expected exactly one line containing {needle!r} in the "
        f"{GITLEAKS_STEP_NAME} script, found {len(matches)}: {matches}"
    )
    return matches[0]


# --------------------------------------------------------------------------- #
# The Pages half — AC1..AC5
# --------------------------------------------------------------------------- #


def test_ac5_the_parse_is_not_vacuous_and_names_both_jobs() -> None:
    """Asserted as a SUBSET, never as equality: PDF-34 D7 added a third job
    (`gate`) above `build`, and a fourth nobody has proposed yet must not redden
    this module either. What the other criteria then pin is the grant
    POPULATION, which covers any such job by construction."""
    jobs = _jobs(_load(DEPLOY_WORKFLOW))
    assert {"build", "deploy"} <= set(jobs), sorted(jobs)


def test_ac1_neither_write_scope_survives_at_workflow_level() -> None:
    """The criterion that reddens when a later edit re-hoists the grant."""
    doc = _load(DEPLOY_WORKFLOW)
    top = doc.get("permissions")
    assert isinstance(top, dict), f"workflow-level `permissions` is {top!r}, expected a mapping"
    offenders = [scope for scope in WRITE_SCOPES if scope in top]
    assert not offenders, (
        f"{DEPLOY_WORKFLOW.name}: {offenders} declared at WORKFLOW level, where the grant "
        f"reaches every job (currently {sorted(_jobs(doc))}). Scope them to `deploy`."
    )


def test_ac2_deploy_declares_both_write_scopes() -> None:
    """Stated separately from AC1 on purpose. A criterion phrased purely by
    absence is satisfied by DELETING the grant, which breaks the publish and
    still reports success. This is the half that fails in that case while AC1
    still passes."""
    jobs = _jobs(_load(DEPLOY_WORKFLOW))
    perms = _job_permissions(jobs["deploy"])
    assert perms.get("pages") == "write", f"deploy.permissions.pages = {perms.get('pages')!r}"
    assert perms.get("id-token") == "write", (
        f"deploy.permissions.id-token = {perms.get('id-token')!r}"
    )


def test_ac3_the_grant_population_over_all_jobs_is_exactly_deploy() -> None:
    jobs = _jobs(_load(DEPLOY_WORKFLOW))
    for scope in WRITE_SCOPES:
        holders = {
            name for name, job in jobs.items() if _job_permissions(job).get(scope) == "write"
        }
        assert holders == {"deploy"}, (
            f"{scope}: write held by {sorted(holders)}, expected ['deploy']"
        )


def test_ac4_build_authority_is_explicit_and_exactly_contents_read() -> None:
    """Explicit, not inherited: inheritance is the failure mode being repaired,
    and a reader must see this job's authority without scrolling to the top of
    the file. `build` is the job running `npm ci` and `npm run build`."""
    jobs = _jobs(_load(DEPLOY_WORKFLOW))
    build = jobs["build"]
    assert isinstance(build, dict) and "permissions" in build, (
        "the `build` job declares no `permissions:` block of its own and would "
        "inherit the workflow default"
    )
    assert _job_permissions(build) == {"contents": "read"}, _job_permissions(build)


# --------------------------------------------------------------------------- #
# The gitleaks half — AC7, AC9, AC10
# --------------------------------------------------------------------------- #


def test_ac7_the_gitleaks_pin_is_a_committed_content_literal() -> None:
    """A version pin does not bind a MUTABLE release asset. The expected hash
    must be a committed literal -- not a command substitution, and not fetched
    at run time -- because that is what makes the control a claim by the
    repository rather than by the server it is checking."""
    doc = _load(CI_WORKFLOW)
    env = doc.get("env")
    assert isinstance(env, dict), f"ci.yml `env:` is {env!r}, expected a mapping"
    assert "GITLEAKS_VERSION" in env, "GITLEAKS_VERSION vanished from the env block"
    digest = env.get("GITLEAKS_SHA256")
    assert isinstance(digest, str), f"GITLEAKS_SHA256 is {digest!r}, expected a string literal"
    assert re.fullmatch(r"[0-9a-f]{64}", digest), (
        f"GITLEAKS_SHA256 = {digest!r} is not 64 lowercase hex characters; a command "
        "substitution or an expression here would be a control that cannot fail"
    )

    raw = CI_WORKFLOW.read_text()
    assert "${{" not in raw.split("GITLEAKS_SHA256")[1].split("\n")[0], (
        "GITLEAKS_SHA256 is interpolated rather than committed"
    )
    # The provenance comment is part of the criterion: a bare 64-hex literal
    # with no recorded source is unauditable by the next reader.
    preamble = raw.split("GITLEAKS_SHA256:")[0]
    tail = preamble[-1400:]
    assert "checksums" in tail, "no comment naming the checksum's published source"
    assert re.search(r"\b20\d{2}-\d{2}-\d{2}\b", tail), (
        "no comment recording the DATE the published checksum was read"
    )


def test_ac7_no_checksums_file_is_fetched_at_run_time() -> None:
    """A criterion by ABSENCE, and binding because this spec edits CI.

    Verifying a download against a checksums file fetched from the same release
    verifies nothing -- one compromise serves both. Named source lines only:
    the provenance comment above legitimately names the published URL, and a
    comment cannot fetch anything.
    """
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows, "no workflows found -- the probe cannot see what it rules out"
    offenders = []
    for path in workflows:
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            if re.search(r"\b(curl|wget)\b", line) and "checksum" in line.lower():
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, offenders


def test_ac9_verification_precedes_extraction() -> None:
    """Order is the whole property. A checksum verified after extraction has
    already let unverified bytes onto the filesystem; one verified after
    `sudo install` has already let them onto PATH as root."""
    lines = _gitleaks_script_lines()
    curl_at = _index_of(lines, "curl -fsSL")
    verify_at = _index_of(lines, "sha256sum -c")
    extract_at = _index_of(lines, "tar -xzf")
    install_at = _index_of(lines, "sudo install")
    assert curl_at < verify_at < extract_at < install_at, {
        "curl": curl_at,
        "sha256sum -c": verify_at,
        "tar -xzf": extract_at,
        "sudo install": install_at,
    }


def test_ac10_the_failure_status_can_still_reach_the_step() -> None:
    """`sha256sum` is the last command in its pipeline, so the pipeline status
    is its status even without `pipefail`; `set -euo pipefail` is then what
    aborts the step rather than letting it run on. Deleting that line would
    leave a verification that reports failure and proceeds anyway."""
    lines = _gitleaks_script_lines()
    assert lines[0].strip() == "set -euo pipefail", lines[0]

    # And the hash/path separator is two spaces: GNU coreutils rejects a single
    # space with "no properly formatted checksum lines found" -- which still
    # fails closed, but with a message that misdirects the next reader.
    verify = lines[_index_of(lines, "sha256sum -c")]
    assert re.search(r"\$\{GITLEAKS_SHA256\}\s{2}/", verify), verify


def test_ac11_the_version_pin_was_not_moved_by_the_content_pin() -> None:
    """A bump must move BOTH values together; this spec moved neither."""
    env = _load(CI_WORKFLOW)["env"]
    assert env["GITLEAKS_VERSION"] == "8.30.1", env["GITLEAKS_VERSION"]
    job = _jobs(_load(CI_WORKFLOW))["secret-scan"]
    checkout = [
        s for s in job["steps"] if isinstance(s, dict) and "actions/checkout" in str(s.get("uses"))
    ]
    assert len(checkout) == 1, checkout
    assert checkout[0].get("with", {}).get("fetch-depth") == 0, (
        "fetch-depth: 0 is load-bearing at this checkout -- a shallow clone "
        "downgrades the full-history gate to a one-commit gate that still "
        "reports success"
    )


# --------------------------------------------------------------------------- #
# Both halves — AC13
# --------------------------------------------------------------------------- #


def test_ac13_the_samples_dir_override_is_never_set_in_ci() -> None:
    """`B-R01`, re-asserted here because this spec edits CI. A criterion by
    absence, so the probe is proven able to SEE first: it reads the same files
    the assertion rules the name out of, and fails if it found none."""
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows, "no workflows found -- the probe cannot see what it rules out"
    texts = {path.name: path.read_text() for path in workflows}
    # Positive control: the probe demonstrably finds a string that IS present,
    # so an empty offender list below is evidence and not an artefact.
    assert any("runs-on" in text for text in texts.values()), (
        "the probe could not find `runs-on` in any workflow, so it is not "
        "reading what it claims to read"
    )
    offenders = [name for name, text in texts.items() if "PDF_TOOLKIT_SAMPLES_DIR" in text]
    assert not offenders, offenders
