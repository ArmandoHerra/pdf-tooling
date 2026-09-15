"""The merge gate — PDF-60.

Two independent things live here, in one file because they are cheap enough
to be almost free and important enough that each deserves its own name in a
stack trace.

FIRST: `scripts/dco_check.py`'s pure engine, driven BOTH directions, entirely
offline (D1). No network, no PR, no token, no repository setting — every
AC1-AC7 red is planted here, in memory, and watched fail before any green is
trusted. This is the whole of Lane A's AC1-AC7, and it is the reason Lane A
can reach `Verified` with `required_status_checks` still absent (E1) and
`allow_merge_commit` still `true` (E2).

SECOND: the `CONTRIBUTING.md` reconciliation (D8) and `dco.yml`'s own trigger
shape (D6). Both are independent, from-scratch scans over the workflow/doc
text — this module imports NOTHING from `scripts/gate_parity.py` or `tests/
test_gate_parity.py` (`decision.md` §4.1 forbids `PDF-60` writing that file at
all, and D8 is explicit that the reconciliation must not lean on the
instrument it is reconciling against).
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

# scripts/ has no __init__.py and is not on sys.path by pytest's default
# rootdir insertion — see tests/test_gate_parity.py's identical comment,
# which this one deliberately does not import from.
_SCRIPTS_DIR: Final[Path] = REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import dco_check  # noqa: E402

DCO_SCRIPT: Final[Path] = _SCRIPTS_DIR / "dco_check.py"
CONTRIBUTING_PATH: Final[Path] = REPO_ROOT / "CONTRIBUTING.md"
CI_WORKFLOW_PATH: Final[Path] = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DCO_WORKFLOW_PATH: Final[Path] = REPO_ROOT / ".github" / "workflows" / "dco.yml"

# --------------------------------------------------------------------------- #
# Synthetic commit records, in the exact shape
# GET /repos/{owner}/{repo}/pulls/{n}/commits returns.
# --------------------------------------------------------------------------- #


def _human_record(
    sha: str = "abc1234",
    email: str = "person@example.com",
    signoff_email: str | None = "SAME",
    parents: int = 1,
) -> dict[str, Any]:
    """A commit by a real, GitHub-resolved human author.

    `signoff_email="SAME"` (the default) writes a trailer matching *email*
    exactly. `None` writes no trailer at all. Any other string writes a
    trailer with that email, letting a test plant a mismatch deliberately.
    """
    if signoff_email is None:
        message = "feat: a thing, unsigned\n"
    else:
        trailer_email = email if signoff_email == "SAME" else signoff_email
        message = f"feat: a thing\n\nSigned-off-by: A Person <{trailer_email}>\n"
    return {
        "sha": sha,
        "author": {"login": "a-person", "type": "User"},
        "commit": {"author": {"email": email}, "message": message},
        "parents": [{"sha": f"parent-{i}"} for i in range(parents)],
    }


def _bot_record(
    sha: str = "bot1234",
    author_type: str = "Bot",
    commit_email: str = "49699333+dependabot[bot]@users.noreply.github.com",
    signoff_email: str | None = None,
) -> dict[str, Any]:
    """A commit shaped exactly like a live Dependabot commit (E6): the
    trailer's email and the commit author's email do NOT match by
    construction, which is the whole reason the bot exemption exists."""
    if signoff_email is None:
        message = "chore(deps): bump\n"
    else:
        message = f"chore(deps): bump\n\nSigned-off-by: dependabot[bot] <{signoff_email}>\n"
    return {
        "sha": sha,
        "author": {"login": "dependabot[bot]", "type": author_type},
        "commit": {"author": {"email": commit_email}, "message": message},
        "parents": [{"sha": "parent-0"}],
    }


# --------------------------------------------------------------------------- #
# AC1 — a pure function of its input, stdlib-only.
# --------------------------------------------------------------------------- #


def test_ac1_the_engine_imports_only_the_standard_library() -> None:
    tree = ast.parse(DCO_SCRIPT.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    non_stdlib = modules - set(sys.stdlib_module_names)
    assert non_stdlib == set(), f"scripts/dco_check.py imports non-stdlib module(s): {non_stdlib}"


def test_ac1_help_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(DCO_SCRIPT), "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_ac1_red_missing_trailer_fails_naming_sha_email_and_trailers_found() -> None:
    record = _human_record(sha="deadbeef", email="person@example.com", signoff_email=None)
    code, lines = dco_check.run([record], declared_count=None)
    text = "\n".join(lines)
    assert code == 1
    assert "deadbeef" in text
    assert "person@example.com" in text
    assert "trailers found" in text


# --------------------------------------------------------------------------- #
# AC2 — a good range passes and says how much it examined.
# --------------------------------------------------------------------------- #


def test_ac2_matching_signoff_passes_and_reports_the_examined_count() -> None:
    records = [
        _human_record(sha="aaa1111", email="a@example.com"),
        _human_record(sha="bbb2222", email="b@example.com"),
    ]
    code, lines = dco_check.run(records, declared_count=None)
    assert code == 0
    assert lines[0] == "examined 2 commit(s)"


def test_ac2_red_one_character_off_trailer_email_fails_naming_that_sha() -> None:
    records = [
        _human_record(sha="aaa1111", email="a@example.com"),
        # off by one character in the trailer email relative to the author's
        _human_record(sha="bbb2222", email="b@example.com", signoff_email="c@example.com"),
    ]
    code, lines = dco_check.run(records, declared_count=None)
    text = "\n".join(lines)
    assert code == 1
    assert "bbb2222" in text
    assert "aaa1111" not in text, "only the offending sha should be named"


# --------------------------------------------------------------------------- #
# AC3 — email equality, case-insensitive, and on nothing else.
# --------------------------------------------------------------------------- #


def test_ac3_email_match_is_case_insensitive() -> None:
    record = {
        "sha": "case0001",
        "author": {"login": "a-person", "type": "User"},
        "commit": {
            "author": {"email": "person@example.com"},
            "message": "feat: thing\n\nSigned-off-by: A Person <PERSON@Example.COM>\n",
        },
        "parents": [{"sha": "parent-0"}],
    }
    code, _lines = dco_check.run([record], declared_count=None)
    assert code == 0


def test_ac3_a_trailer_matching_only_the_authors_name_fails() -> None:
    record = {
        "sha": "name0001",
        "author": {"login": "a-person", "type": "User"},
        "commit": {
            "author": {"email": "person@example.com"},
            "message": "feat: thing\n\nSigned-off-by: A Person <someone-else@example.com>\n",
        },
        "parents": [{"sha": "parent-0"}],
    }
    code, _lines = dco_check.run([record], declared_count=None)
    assert code == 1


def test_ac3_red_dependabot_shaped_record_wearing_a_human_type_still_fails() -> None:
    """E6, encoded: matching on NAME (P2) is refused. This record has the
    trailer's NAME right (`dependabot[bot]`) and the EMAIL wrong, exactly as
    every live Dependabot commit does — with `.author.type` forced to
    `"User"` so the bot exemption (AC4) cannot be the reason it fails."""
    record = _bot_record(author_type="User", signoff_email="support@github.com")
    code, _lines = dco_check.run([record], declared_count=None)
    assert code == 1


# --------------------------------------------------------------------------- #
# AC4 — the bot exemption is GitHub-asserted and always printed.
# --------------------------------------------------------------------------- #


def test_ac4_bot_author_with_no_trailer_is_exempt_and_the_exemption_is_printed() -> None:
    record = _bot_record(author_type="Bot", signoff_email=None)
    code, lines = dco_check.run([record], declared_count=None)
    text = "\n".join(lines)
    assert code == 0
    assert "EXEMPT" in text
    assert record["sha"] in text
    assert "dependabot[bot]" in text


def test_ac4_red_flipping_author_type_to_user_fails() -> None:
    record = _bot_record(author_type="User", signoff_email=None)
    code, lines = dco_check.run([record], declared_count=None)
    assert code == 1
    assert "EXEMPT" not in "\n".join(lines)


def test_ac4_second_red_a_user_record_wearing_a_bots_email_is_not_exempt() -> None:
    """The bypass test. The decision reads `.author.type` — GitHub's own
    resolution of the account — never the commit's self-reported bytes. A
    `"User"`-typed record must not buy the exemption merely by setting its
    email to a bot's well-known no-reply address."""
    record = _bot_record(
        author_type="User",
        commit_email="49699333+dependabot[bot]@users.noreply.github.com",
        signoff_email=None,
    )
    code, lines = dco_check.run([record], declared_count=None)
    assert code == 1
    assert "EXEMPT" not in "\n".join(lines)


# --------------------------------------------------------------------------- #
# AC5 — unknown authorship fails, distinctly from a missing trailer.
# --------------------------------------------------------------------------- #


def test_ac5_null_author_fails_with_a_message_distinct_from_missing_trailer() -> None:
    record = {
        "sha": "nullauth",
        "author": None,
        "commit": {"author": {"email": "x@example.com"}, "message": "feat: thing\n"},
        "parents": [{"sha": "parent-0"}],
    }
    code, lines = dco_check.run([record], declared_count=None)
    text = "\n".join(lines)
    assert code == 1
    assert "unresolved authorship" in text
    assert "no Signed-off-by trailer matches" not in text


def test_ac5_red_a_valid_author_object_passes() -> None:
    record = _human_record(sha="nullauth")
    code, _lines = dco_check.run([record], declared_count=None)
    assert code == 0


# --------------------------------------------------------------------------- #
# AC6 — a merge commit fails naming `rebase`; an empty range fails, never a
# vacuous pass.
# --------------------------------------------------------------------------- #


def test_ac6_a_merge_commit_fails_naming_the_sha_and_rebase() -> None:
    record = _human_record(sha="merge001", parents=2)
    code, lines = dco_check.run([record], declared_count=None)
    text = "\n".join(lines)
    assert code == 1
    assert "merge001" in text
    assert "rebase" in text


def test_ac6_an_empty_range_fails_non_zero_and_examined_zero_is_never_a_pass() -> None:
    code, lines = dco_check.run([], declared_count=None)
    assert code != 0
    assert lines[0] == "examined 0 commit(s)"


# --------------------------------------------------------------------------- #
# AC7 — the count is reconciled, not trusted.
# --------------------------------------------------------------------------- #


def test_ac7_declared_count_one_higher_fails_naming_both_numbers() -> None:
    records = [_human_record(sha="only0001")]
    code, lines = dco_check.run(records, declared_count=2)
    text = "\n".join(lines)
    assert code == 1
    assert "1 commit(s)" in text
    assert "2 commit(s)" in text


def test_ac7_matching_declared_count_passes() -> None:
    records = [_human_record(sha="only0001"), _human_record(sha="only0002")]
    code, _lines = dco_check.run(records, declared_count=2)
    assert code == 0


# --------------------------------------------------------------------------- #
# D1 — the workflow is a thin carrier: the CLI wires the same pure function.
# --------------------------------------------------------------------------- #


def test_the_cli_wires_input_and_declared_count(tmp_path: Path) -> None:
    payload = json.dumps([_human_record(sha="cli00001")])
    input_path = tmp_path / "commits.json"
    input_path.write_text(payload)
    result = subprocess.run(
        [
            sys.executable,
            str(DCO_SCRIPT),
            "--input",
            str(input_path),
            "--declared-count",
            "1",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "examined 1 commit(s)" in result.stdout


# --------------------------------------------------------------------------- #
# D6 — the workflow's trigger shape: pull_request, never pull_request_target;
# no write permission anywhere; no concurrency group.
# --------------------------------------------------------------------------- #


def test_d6_dco_workflow_triggers_on_pull_request_only() -> None:
    text = DCO_WORKFLOW_PATH.read_text()
    on_match = re.search(r'^"on":\n((?:^ {2}\S.*\n?)*)', text, re.MULTILINE)
    assert on_match is not None, 'dco.yml has no "on": trigger block'
    triggers = re.findall(r"^ {2}(\w[\w_]*):", on_match.group(1), re.MULTILINE)
    assert triggers == ["pull_request"], triggers
    # `pull_request_target` is named in this file's own explanatory comment
    # (it says why the job must NOT use it) — the assertion binds the actual
    # trigger KEYS captured above, never a raw substring search over prose.
    assert "pull_request_target" not in on_match.group(1)


def test_d6_dco_workflow_declares_no_write_permission() -> None:
    text = DCO_WORKFLOW_PATH.read_text()
    perm_match = re.search(r"^permissions:\n((?:^ {2}\S.*\n?)*)", text, re.MULTILINE)
    assert perm_match is not None, "dco.yml has no permissions: block"
    assert "write" not in perm_match.group(1)


def test_d6_dco_workflow_declares_no_uses_local_reference() -> None:
    """E7: a `uses: ./` reference is a THIRD local ref the frozen `local_refs
    == 2` count (tests/test_gate_parity.py) does not expect."""
    text = DCO_WORKFLOW_PATH.read_text()
    assert not re.search(r"^\s*(?:- )?uses:\s+\./", text, re.MULTILINE)


def test_d6_dco_workflow_declares_no_concurrency_group() -> None:
    """D2: a re-push to a PR branch must produce its OWN complete, readable
    `dco` run — `ci.yml`'s `cancel-in-progress: true` on `pull_request` would
    otherwise defeat the D7 measurement this job's bound depends on."""
    text = DCO_WORKFLOW_PATH.read_text()
    assert not re.search(r"^concurrency:", text, re.MULTILINE)


# --------------------------------------------------------------------------- #
# D8 / AC11 — the CONTRIBUTING reconciliation: derived, never transcribed.
# --------------------------------------------------------------------------- #


def _independent_ci_job_names() -> list[str]:
    """An INDEPENDENT, from-scratch scan of `ci.yml`'s job names.

    Deliberately does not import `scripts/gate_parity.py` or reuse `tests/
    test_gate_parity.py`'s own scan — D8 requires the reconciliation to stand
    on its own, and `decision.md` §4.1 forbids this spec writing that file at
    all.
    """
    lines = CI_WORKFLOW_PATH.read_text().splitlines()
    jobs_at = next(i for i, line in enumerate(lines) if line == "jobs:")
    names: list[str] = []
    for line in lines[jobs_at + 1 :]:
        m = re.match(r"^ {2}([a-zA-Z][a-zA-Z0-9_-]*):\s*$", line)
        if m:
            names.append(m.group(1))
    return names


def _contributing_required_checks_section() -> str:
    """Everything between the new heading and the next `## ` heading."""
    text = CONTRIBUTING_PATH.read_text()
    m = re.search(r"## What must be green before a merge\n\n(.*?)\n\n## ", text, re.DOTALL)
    assert m is not None, "CONTRIBUTING.md has no 'What must be green' section"
    return m.group(1)


def _contributing_required_checks() -> list[str]:
    section = _contributing_required_checks_section()
    fenced = re.search(r"```\n(.*?)```", section, re.DOTALL)
    assert fenced is not None, "the required-checks section has no fenced block"
    return [line for line in fenced.group(1).splitlines() if line.strip()]


def test_ac11_contributing_lists_exactly_the_derived_check_set() -> None:
    expected = set(_independent_ci_job_names()) | {"dco"}
    actual = set(_contributing_required_checks())
    assert actual == expected, (actual, expected)


def test_ac11_red_a_deleted_job_name_breaks_the_reconciliation_on_scratch_text() -> None:
    """RED #1 of AC11's three, driven on SCRATCH text — never the tracked
    file (HC-4: no `git stash`, no working-tree mutation)."""
    expected = set(_independent_ci_job_names()) | {"dco"}
    scratch = set(_contributing_required_checks())
    scratch.discard("build")
    assert scratch != expected


_CARDINAL_WORD: Final[re.Pattern[str]] = re.compile(
    r"\b(?:\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\b",
    re.IGNORECASE,
)

_BANNED_LOCAL_EQUALS_CI_CLAIM: Final[re.Pattern[str]] = re.compile(
    r"the local gate is the ci gate|exactly the checks ci runs|the same checks ci runs"
    r"|green locally it is green in ci",
    re.IGNORECASE,
)


def _required_checks_prose() -> str:
    """The new section's prose ONLY — the fenced block stripped out, since
    E8's own escape is that the fenced list is free; only the prose around it
    may carry zero new cardinals."""
    section = _contributing_required_checks_section()
    return re.sub(r"```.*?```", "", section, flags=re.DOTALL)


def test_ac11_the_new_sections_prose_states_no_cardinal() -> None:
    """HC-5/AC11: zero new bare cardinals — RESIDUE_CEILING has no headroom."""
    hits = _CARDINAL_WORD.findall(_required_checks_prose())
    assert hits == [], hits


def test_ac11_red_a_planted_cardinal_is_caught_on_scratch_text() -> None:
    """RED #2 of AC11's three, driven on SCRATCH text."""
    planted = _required_checks_prose() + " There are eleven jobs."
    assert _CARDINAL_WORD.findall(planted)


def test_ac11_the_new_section_makes_no_local_equals_ci_claim() -> None:
    assert _BANNED_LOCAL_EQUALS_CI_CLAIM.search(_required_checks_prose()) is None


def test_ac11_red_a_planted_claim_is_caught_on_scratch_text() -> None:
    """RED #3 of AC11's three, driven on SCRATCH text."""
    planted = _required_checks_prose() + " This is exactly the checks CI runs."
    assert _BANNED_LOCAL_EQUALS_CI_CLAIM.search(planted) is not None
