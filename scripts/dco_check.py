#!/usr/bin/env python3
"""The first-party DCO check engine — PDF-60.

`CONTRIBUTING.md` has stated, since before this repository had a test suite
this size, that "commits without the trailer are rejected." Nothing rejected
them. This module is the instrument that makes that sentence true, and
`.github/workflows/dco.yml` is the thin carrier that wires it to a real pull
request.

WHY FIRST-PARTY, STDLIB-ONLY (D3). The DCO GitHub App is a repository/org
SETTING — that puts the whole deliverable in Lane B and leaves nothing here
gradeable. A third-party action is a standing SHA pin to maintain on a public
repository, to run what is, in substance, `git log | grep`, and it does not
implement the exact policy below anyway. This module is the same shape as
`scripts/licenses.py`, `scripts/assert_skips.py` and `scripts/gate_parity.py`:
a first-party engine, invoked by a thin CI step, unit-tested offline.

THE POLICY (D4/D5), evaluated per commit, IN ORDER:

  1. `.author` is `null` — no GitHub account resolves the commit — FAILS,
     with a message distinct from the missing-trailer one. An unresolved
     identity is precisely the hole a bad actor would hide in.
  2. `.author.type == "Bot"` — EXEMPT, always printed with its reason. The
     exemption is keyed on GitHub's OWN resolution of the account, never on
     the commit's self-reported bytes (`commit.author.email`), which any
     contributor controls. Matching on the commit's own bytes is the bypass
     this design refuses (D4 policy P2's rejection).
  3. A merge commit (more than one parent) FAILS, naming the remedy
     (`rebase`) — `required_linear_history: true` already refuses to merge
     such a branch, so this agrees with the protection beside it rather than
     contradicting it.
  4. Otherwise the commit message must carry at least one
     `Signed-off-by: <name> <email>` trailer whose `<email>` equals
     `commit.author.email`, compared CASE-INSENSITIVELY and ONLY on the
     email — never the name (P0/P2 are both refused on this point).

An empty commit list is a FAILURE, not a vacuous pass — a check that examines
zero commits and exits 0 is the silently-skipped-verification defect this
product has a name for. And a declared count that disagrees with what was
actually examined is also a failure: it is how a paginated range that
silently truncated at the API's cap would otherwise report success on a
prefix (AC7).

Exit 0 only when at least one commit was examined and no finding was raised.
Exit 1 on any finding — an empty range, a count mismatch, or an offending
commit. Exit 2 on a usage error (unparsable input), which is not a finding
about the policy and must not be confused with one.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, TextIO

#: One `Signed-off-by:` trailer's email, per line. Matched case-insensitively
#: on the header itself (DCO tooling in the wild is not fussy about its
#: casing either); the case-insensitive comparison the policy actually cares
#: about is done separately, on the captured email, in `_evaluate`.
_TRAILER_LINE = re.compile(r"^Signed-off-by:\s*.*?<([^<>]+)>\s*$", re.MULTILINE | re.IGNORECASE)


def trailer_emails(message: str) -> list[str]:
    """Every `Signed-off-by:` email in *message*, exactly as the commit wrote it."""
    return _TRAILER_LINE.findall(message or "")


def evaluate_commit(record: dict[str, Any]) -> tuple[str, str]:
    """One commit record, evaluated per the ordered policy above.

    Returns ``(verdict, message)`` where *verdict* is one of ``"pass"``,
    ``"exempt"`` or ``"fail"``. *message* is empty for a pass (nothing about a
    clean commit needs printing); every exemption and every failure carries a
    message naming the sha, per D5's "every offending sha is printed" rule.
    """
    sha = record.get("sha") or "<sha unknown>"
    author = record.get("author")
    commit = record.get("commit") or {}
    commit_author = commit.get("author") or {}
    author_email = commit_author.get("email") or ""
    message = commit.get("message") or ""
    parents = record.get("parents") or []

    if author is None:
        return (
            "fail",
            f"{sha}: unresolved authorship — no GitHub account resolves this commit "
            "(distinct from a missing-trailer finding: nobody to check a trailer against)",
        )

    if author.get("type") == "Bot":
        login = author.get("login") or "<unknown login>"
        return "exempt", f"EXEMPT {sha} {login} — bot author (GitHub-asserted, .author.type)"

    if len(parents) > 1:
        return (
            "fail",
            f"{sha}: merge commit ({len(parents)} parents) — rebase onto a linear "
            "history; this check agrees with required_linear_history rather than "
            "contradicting it",
        )

    trailers = trailer_emails(message)
    if author_email and any(t.strip().lower() == author_email.strip().lower() for t in trailers):
        return "pass", ""

    found = ", ".join(trailers) if trailers else "none"
    return (
        "fail",
        f"{sha}: no Signed-off-by trailer matches the author email {author_email!r} "
        f"(trailers found: {found})",
    )


def run(records: list[dict[str, Any]], declared_count: int | None) -> tuple[int, list[str]]:
    """The pure core: *records* in, an exit code and the lines to print out.

    Kept separate from `main` so a test drives it with no file, no stdin and
    no argparse in the way (D1: "no network, no PR, no token, no settings").
    """
    lines: list[str] = []
    examined = len(records)
    lines.append(f"examined {examined} commit(s)")

    if examined == 0:
        lines.append("dco: an empty commit range is a FAILURE, never a silent pass.")
        return 1, lines

    if declared_count is not None and examined != declared_count:
        lines.append(
            f"dco: examined {examined} commit(s) but the pull request declares "
            f"{declared_count} commit(s) — a paginated range that silently truncated "
            "at the API's cap cannot report success on a prefix."
        )
        return 1, lines

    failures: list[str] = []
    for record in records:
        verdict, message = evaluate_commit(record)
        if verdict == "exempt":
            lines.append(message)
        elif verdict == "fail":
            failures.append(message)
            lines.append(message)

    if failures:
        lines.append(f"dco: {len(failures)} of {examined} commit(s) failed.")
        return 1, lines

    return 0, lines


def _load_records(stream: TextIO) -> list[dict[str, Any]] | None:
    try:
        data = json.load(stream)
    except json.JSONDecodeError as exc:
        print(f"dco: could not parse the input as JSON: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, list):
        print("dco: input must be a JSON array of commit records", file=sys.stderr)
        return None
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dco_check.py",
        description=(
            "First-party DCO check. Reads a JSON array shaped like "
            "GET /repos/{owner}/{repo}/pulls/{n}/commits and verifies every commit "
            "carries a Signed-off-by: trailer matching its GitHub-resolved author "
            "email, case-insensitively. GitHub-asserted bot authors are exempt; "
            "merge commits and unresolved authorship are refused outright."
        ),
    )
    parser.add_argument(
        "--input",
        type=argparse.FileType("r", encoding="utf-8"),
        default=sys.stdin,
        help="path to the JSON array (default: stdin)",
    )
    parser.add_argument(
        "--declared-count",
        type=int,
        default=None,
        metavar="N",
        help=(
            "the pull request's own declared commit count "
            "(github.event.pull_request.commits); a mismatch against what was "
            "actually examined fails loudly rather than trusting a silently "
            "truncated, paginated prefix (AC7)"
        ),
    )
    args = parser.parse_args(argv)

    records = _load_records(args.input)
    if records is None:
        return 2

    exit_code, lines = run(records, args.declared_count)
    for line in lines:
        print(line)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
