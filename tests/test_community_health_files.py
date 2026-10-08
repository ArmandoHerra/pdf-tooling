"""Community health files -- PDF-123.

Pins what the repository's security policy, issue forms, PR template and code
of conduct must and must not say. Each arm reads the COMMITTED files; a missing
file FAILS and never skips (a guard that skips on a missing file is satisfied
by deleting the file). The module reads files that are not in the sdist, which
is the existing posture of ``tests/test_workflow_supply_chain.py``.

Deliberately NOT widened into ``GUARDED_DOCS``: these files are free prose (and
the code of conduct is third-party text), so the properties that matter -- a
URL, no promise, no version number, no overclaim -- are guarded by specific
arms instead.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SECURITY = REPO_ROOT / "SECURITY.md"
CONDUCT = REPO_ROOT / "CODE_OF_CONDUCT.md"
PR_TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"
TEMPLATE_DIR = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"
BUG_FORM = TEMPLATE_DIR / "bug_report.yml"
FEATURE_FORM = TEMPLATE_DIR / "feature_request.yml"
CHOOSER = TEMPLATE_DIR / "config.yml"
README = REPO_ROOT / "README.md"
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

PVR_URL = "https://github.com/ArmandoHerra/pdf-tooling/security/advisories/new"
BLOB_CONTRIBUTING = "https://github.com/ArmandoHerra/pdf-tooling/blob/main/CONTRIBUTING.md"
FORM_ELEMENT_TYPES = {"markdown", "input", "textarea", "dropdown", "checkboxes"}


def _text(path: Path) -> str:
    assert path.is_file(), f"{path.relative_to(REPO_ROOT)} is missing"
    return path.read_text(encoding="utf-8")


def _yaml(path: Path) -> Any:
    return yaml.safe_load(_text(path))


def _slug(heading: str) -> str:
    """GitHub's anchor rule: lowercase, keep alphanumerics/spaces/hyphens, spaces to hyphens."""
    lowered = heading.strip().lower()
    kept = re.sub(r"[^a-z0-9 \-]", "", lowered)
    return kept.replace(" ", "-")


def _heading_slugs(path: Path) -> set[str]:
    slugs: set[str] = set()
    for line in _text(path).splitlines():
        match = re.match(r"^#{2,3}\s+(.+?)\s*$", line)
        if match:
            slugs.add(_slug(match.group(1)))
    return slugs


def _elements(form: dict[str, Any]) -> list[dict[str, Any]]:
    body = form.get("body")
    assert isinstance(body, list) and body, "form has an empty or missing body"
    return body


def _by_id(form: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {el["id"]: el for el in _elements(form) if "id" in el}


# H1 -- AC1


def test_h1_the_file_set_is_exactly_the_six_paths() -> None:
    for path in (SECURITY, CONDUCT, PR_TEMPLATE, BUG_FORM, FEATURE_FORM, CHOOSER):
        assert path.is_file(), f"{path.relative_to(REPO_ROOT)} is missing"
    assert TEMPLATE_DIR.is_dir(), "ISSUE_TEMPLATE directory is missing"
    present = {p.name for p in TEMPLATE_DIR.iterdir()}
    expected = {"bug_report.yml", "feature_request.yml", "config.yml"}
    assert present == expected, (
        f"ISSUE_TEMPLATE set differs: extra={sorted(present - expected)} "
        f"missing={sorted(expected - present)}"
    )


# H2 -- AC2


def test_h2_issue_forms_are_structurally_valid() -> None:
    for path in (BUG_FORM, FEATURE_FORM):
        form = _yaml(path)
        assert isinstance(form, dict), f"{path.name} is not a mapping"
        assert form.get("name"), f"{path.name} has no name"
        assert form.get("description"), f"{path.name} has no description"
        ids: list[str] = []
        labels: list[str] = []
        for element in _elements(form):
            assert element.get("type") in FORM_ELEMENT_TYPES, (
                f"{path.name}: bad type {element.get('type')!r}"
            )
            if element["type"] == "markdown":
                continue
            assert element.get("id"), f"{path.name}: element without id: {element}"
            label = (element.get("attributes") or {}).get("label")
            assert label, f"{path.name}: element {element['id']!r} has no label"
            ids.append(element["id"])
            labels.append(label)
        assert len(ids) == len(set(ids)), f"{path.name}: duplicate ids in {ids}"
        assert len(labels) == len(set(labels)), f"{path.name}: duplicate labels in {labels}"


# H3 -- AC3, AC4


def test_h3_bug_form_asks_for_what_the_brief_names() -> None:
    form = _yaml(BUG_FORM)
    by_id = _by_id(form)
    for required_id in (
        "verb",
        "flags",
        "input-description",
        "what-happened",
        "expected",
        "version",
        "doctor",
    ):
        assert required_id in by_id, f"bug form has no element {required_id!r}"
        assert (by_id[required_id].get("validations") or {}).get("required") is True, (
            f"bug form element {required_id!r} is not required"
        )
    for json_id in ("version", "doctor"):
        assert by_id[json_id]["attributes"].get("render") == "json", f"{json_id!r} must render json"
    blob = yaml.safe_dump(form)
    assert "pdftooling version -o json" in blob
    assert "pdftooling doctor -o json" in blob


def test_h3_bug_form_never_asks_for_the_document() -> None:
    form = _yaml(BUG_FORM)
    first = _elements(form)[0]
    assert first["type"] == "markdown"
    assert "Do not attach the PDF" in first["attributes"]["value"]
    ack = _by_id(form).get("no-document")
    assert ack is not None and ack["type"] == "checkboxes", "no-document checkboxes element missing"
    options = ack["attributes"]["options"]
    assert len(options) == 1 and options[0].get("required") is True, (
        "acknowledgement must be one required option"
    )
    pattern = re.compile(r"(?i)\b(attach|upload|share)\b")
    for element in _elements(form):
        if element["type"] not in ("input", "textarea"):
            continue
        attrs = element.get("attributes") or {}
        for key in ("label", "description", "placeholder"):
            value = attrs.get(key)
            if value:
                assert not pattern.search(str(value)), (
                    f"element {element['id']!r} {key} asks to attach/upload/share: {value!r}"
                )


# H4 -- AC5


def test_h4_chooser_routes_security_privately() -> None:
    config = _yaml(CHOOSER)
    assert config.get("blank_issues_enabled") is False, "blank issues must be off"
    links = [c for c in config.get("contact_links") or [] if c.get("url") == PVR_URL]
    assert len(links) == 1, f"expected exactly one contact link to {PVR_URL}, found {len(links)}"


# H5 -- AC6


def test_h5_security_policy_says_what_is_true_and_promises_nothing() -> None:
    text = _text(SECURITY)
    assert PVR_URL in text, "SECURITY.md lacks the private reporting URL"
    assert "latest minor" in text, "SECURITY.md must say the latest minor is supported"
    version_hit = re.search(r"\b\d+\.\d+\b", text)
    assert not version_hit, f"SECURITY.md carries a version literal: {version_hit.group(0)!r}"
    promise = re.search(
        r"(?i)\bwithin\s+\d+|\b\d+\s+(business\s+)?(hours?|days?|weeks?)\b|\bSLA\b|\bguarantee",
        text,
    )
    assert not promise, f"SECURITY.md promises a response: {promise.group(0)!r}"
    assert "clear-all" not in text.lower(), (
        "SECURITY.md must not mention clear-all until the corrected behaviour is released"
    )
    overclaim = re.search(
        r"(?i)(remov|strip|scrub|sanitiz|eras|delet)\w*\s+(all\s+)?(the\s+)?metadata"
        r"|metadata[- ]free|no metadata (remains|is left)",
        text,
    )
    assert not overclaim, f"SECURITY.md overclaims metadata removal: {overclaim.group(0)!r}"
    slugs = _heading_slugs(README)
    for anchor in re.findall(r"README\.md#([A-Za-z0-9_\-]+)", text):
        assert anchor in slugs, f"README.md#{anchor} does not resolve to a README heading"


# H6 -- AC7


def test_h6_pr_template_echoes_the_dco_and_does_not_fork_the_check_list() -> None:
    text = _text(PR_TEMPLATE)
    assert "git commit -s" in text, "PR template must echo `git commit -s`"
    assert "git commit -s" in _text(CONTRIBUTING), (
        "CONTRIBUTING.md no longer carries `git commit -s`"
    )
    slugs = _heading_slugs(CONTRIBUTING)
    anchors = re.findall(re.escape(BLOB_CONTRIBUTING) + r"#([A-Za-z0-9_\-]+)", text)
    expected = {
        "developer-certificate-of-origin",
        "what-must-be-green-before-a-merge",
        "what-a-change-must-not-do",
    }
    assert expected <= set(anchors), (
        f"PR template lacks CONTRIBUTING anchors: {sorted(expected - set(anchors))}"
    )
    for anchor in anchors:
        assert anchor in slugs, f"CONTRIBUTING.md#{anchor} does not resolve to a heading"
    jobs = _yaml(CI_WORKFLOW)["jobs"]
    hyphenated = sorted(job for job in jobs if "-" in job)
    assert hyphenated, "no hyphenated job id derived from ci.yml"
    found = [job for job in hyphenated if job in text]
    assert not found, f"PR template transcribes CI job ids: {found}"


# H7 -- AC8


def test_h7_code_of_conduct_is_2_1_licensed_attributed_and_filled_in() -> None:
    text = _text(CONDUCT)
    for literal in (
        "Contributor Covenant",
        "version 2.1",
        "https://www.contributor-covenant.org/version/2/1/code_of_conduct.html",
        "https://creativecommons.org/licenses/by/4.0/",
        "https://github.com/ArmandoHerra",
    ):
        assert literal in text, f"CODE_OF_CONDUCT.md lacks {literal!r}"
    assert "[INSERT" not in text, "unfilled [INSERT placeholder"
    assert "[NOTE" not in text, "unfilled [NOTE placeholder"
