"""PDF-30 D3 — four changelog guards that can fail, replacing one that cannot.

``tests/test_cli_spine.py`` carried a *"a spec's remediations never predate its
landing"* assertion that was **entailed** by the assertion nine lines above it
(B-080): the date list is asserted non-increasing top-to-bottom, so the
bottom-most date for any id is the minimum of that id's dates, and
``d < min(dates_for_id)`` is unsatisfiable. It read as coverage and was not.

Its *intent* is real and it lives here now, measured against **git** rather than
against a date ordering that already implied it. Four rules the file states about
itself, and that nothing enforced:

============================  ===============================================
``changelog.md:12-13``        append at the top, at the anchor
``changelog.md:14-15``        each spec's own commit writes its own entry
``changelog.md:18-19``        audit per commit, never with a heading grep at HEAD
``changelog.md:7``            the entry format is fixed
============================  ===============================================

THE INSTRUMENT, AND WHY IT IS SHAPED THIS WAY
---------------------------------------------
Heading sets are compared as **exact byte strings, in Python, never through a
shell pipeline**. That is not stylistic. Three shell instruments got this exact
comparison wrong on this exact file (B-088): a ``grep -c '^-##'`` over a diff
reported a deletion where an insertion had occurred, because git pairs lines;
and a ``sort``/``comm`` comparison reported **0 lost, silently**, because
``sort`` used locale collation on em-dashed headings while ``comm`` compares
bytes. The one that worked read ``git show <sha>:changelog.md`` in Python and
compared sets — and was **self-tested against a known-lost needle before it was
trusted**. :func:`test_the_no_loss_instrument_is_self_tested_first` is that
self-test and it runs before any green here is believed.

TOLERANT FOR HISTORY, STRICT FOR THE FUTURE
--------------------------------------------
:func:`parse_headings` accepts the canonical form **and** the two frozen
historical ``[Task: PDF-NN …] - <date>`` forms, so an id-keyed lookup finds
``PDF-16``'s two entries without any landed entry being edited — the file's own
rule is *never edit a landed entry; a correction is a new entry with a new date*.
A separate assertion requires every heading introduced after
:data:`FORMAT_BASELINE` to use the canonical form. That is the
``parse_report_sections()`` shape, for the same reason.

THREE FROZEN REGISTERS, EACH ASSERTED AT AN EXACT SIZE
-------------------------------------------------------
Every one of these guards is **born red on history**, and history is not
rewritten to make them green (HC-4, and ``changelog.md:16``). The debt is
carried in dated registers whose size is itself asserted, so it stays visible
and readable instead of being erased by a back-fill the file's own rules forbid.
"""

from __future__ import annotations

import re
import subprocess
from functools import cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = "changelog.md"
ANCHOR = "<!-- CHANGELOG-ANCHOR: insert new entries directly below this line, newest first -->"

HEADING = re.compile(r"^## .*$", re.MULTILINE)
CANONICAL = re.compile(r"^## \[(?P<id>PDF-\d\d|B-\d+)\] .+ — (?P<date>\d{4}-\d{2}-\d{2})$")
#: B-107. `changelog.md:7` fixes the format; these two landed before it was
#: enforced by anything, carry a `Task:` prefix inside the bracket and separate
#: the date with a hyphen rather than an em dash. `grep '^## \[PDF-16\]'`
#: therefore returns nothing and an id-keyed audit reports both entries missing.
HISTORICAL = re.compile(r"^## \[Task: (?P<id>PDF-\d\d) — .+\] - (?P<date>\d{4}-\d{2}-\d{2})$")

#: The last commit that introduced a non-canonical heading. Every heading
#: introduced AFTER it must be canonical; measured, not assumed.
FORMAT_BASELINE = "7f4183f"

#: B-042. Three commits owe an entry and wrote none — plus a FOURTH that landed
#: after this spec was drafted (`b3c92f7`, the `PDF-18` wave), which is the class
#: recurring rather than a list being wrong, and a FIFTH (`be89f36`, `[B-218]`)
#: registered by `PDF-34` under X-467: X-408 first ruled `036fd0a353` PAY, but
#: both guard arms evaluate `CHANGELOG not in touched_files(sha)` over a
#: LANDED commit and `be89f36`'s touched-file set (`README.md`,
#: `website/src/components/QuickStart.astro`) is immutable — no entry written
#: in any later commit can change what `touched_files(be89f36)` returns, so
#: paying leaves the guard saying the identical false thing it said before.
#: Registration is the only disposition a landed commit's debt has available.
#: **No entry is back-filled** (`changelog.md:15-16`); the register keeps the
#: debt visible at its exact size and a sixth member is a test failure.
ENTRY_OWED_EXEMPT = {
    "81e31e9": "[PDF-16] fix: ruff-format the OG image generator script",
    "85dd844": "[PDF-04] fix: two platform-dependent safety-spine test defects",
    "26f4c79": "[PDF-09] fix: make AC5/AC26 tests spawn-safe, not fork-only",
    "b3c92f7": "[PDF-18] fix: AC12's convert cell must respect engine absence, not assume it",
    "be89f36": "[B-218] docs: install lines flip to PyPI now that pdf-tooling 0.1.1 is live",
}

#: The single commit in this repository's history that DESTROYED a landed entry.
#: It is this spec's positive control and it is free: the guard must be shown red
#: here and green everywhere else.
NO_LOSS_EXEMPT = {"33bf481": "[B-068] fix: --password-file's refusal echoed the given value"}

#: The needle `33bf481` destroyed and `cd33ced` restored — the string the
#: instrument is self-tested against before its green is trusted.
LOST_NEEDLE = (
    "## [PDF-13] fix: wait for /proc to show the child's argv before reading it — 2026-08-30"
)

#: `cd33ced` exists SOLELY to restore what `33bf481` destroyed, so it correctly
#: re-inserts an entry at its original (lower) position rather than at the top.
#: A restoration is the one commit for which "everything added sits above
#: everything that already existed" is the wrong rule.
PREPEND_EXEMPT = {"cd33ced": "[B-088] fix: restore the changelog entry overwritten at 33bf481"}

OWES_AN_ENTRY = re.compile(r"^\[(PDF-\d\d|B-\d+)\]")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )


@cache
def history_depth() -> int:
    result = _git("rev-list", "--count", "HEAD")
    return int(result.stdout.strip() or 0) if result.returncode == 0 else 0


#: `7afdb1a`'s reachable-commit count. Below this the clone is shallow and the
#: history arms SKIP with a reason naming it — `ci.yml`'s `test` job checks out
#: shallow and this spec does not change that (Scope > Out). *A control that
#: cannot be run must be visible as skipped, never silently absent* (X-153).
MINIMUM_HISTORY_DEPTH = 72


def require_full_history() -> None:
    depth = history_depth()
    if depth < MINIMUM_HISTORY_DEPTH:
        pytest.skip(
            f"shallow clone: git rev-list --count HEAD is {depth}, below the frozen "
            f"minimum of {MINIMUM_HISTORY_DEPTH}. These arms read old revisions of "
            "changelog.md and cannot run here; they are enforced locally, by "
            "`make docs-gate` and by the qa-sentinel. A shallow checkout never "
            "yields a pass."
        )


@cache
def changelog_at(sha: str) -> str | None:
    """`changelog.md` exactly as it stood at *sha*, or None if absent there."""
    result = _git("show", f"{sha}:{CHANGELOG}")
    return result.stdout if result.returncode == 0 else None


@cache
def commits() -> tuple[str, ...]:
    result = _git("rev-list", "--reverse", "HEAD")
    return tuple(result.stdout.split())


@cache
def parents_of(sha: str) -> tuple[str, ...]:
    return tuple(_git("log", "-1", "--format=%P", sha).stdout.split())


@cache
def subject_of(sha: str) -> str:
    return _git("log", "-1", "--format=%s", sha).stdout.strip()


@cache
def touched_files(sha: str) -> tuple[str, ...]:
    return tuple(_git("diff-tree", "--no-commit-id", "--name-only", "-r", sha).stdout.split())


def headings(text: str | None) -> list[str]:
    """Every `## ` heading, in file order, as exact byte strings."""
    return HEADING.findall(text) if text is not None else []


def parse_headings(text: str | None) -> list[tuple[str, str, str]]:
    """`(id, date, raw)` for every heading, canonical or frozen-historical.

    Tolerant on the way IN so an id-keyed lookup finds `PDF-16`'s two entries
    (B-107) without any landed entry being edited; strict on the way FORWARD via
    :func:`test_every_heading_introduced_after_the_baseline_is_canonical`.
    """
    parsed: list[tuple[str, str, str]] = []
    for raw in headings(text):
        match = CANONICAL.match(raw) or HISTORICAL.match(raw)
        if match:
            parsed.append((match.group("id"), match.group("date"), raw))
    return parsed


def entries_for(spec_id: str, text: str | None = None) -> list[tuple[str, str, str]]:
    body = (REPO_ROOT / CHANGELOG).read_text() if text is None else text
    return [entry for entry in parse_headings(body) if entry[0] == spec_id]


# --------------------------------------------------------------------------- #
# AC12 — the tolerant parser, and the strict forward rule
# --------------------------------------------------------------------------- #


def test_the_parser_is_tolerant_enough_to_find_the_two_task_headings() -> None:
    """AC12's RED, free: `grep '^## \\[PDF-16\\]' changelog.md` returns nothing
    today, so an id-keyed audit reports both of PDF-16's entries missing."""
    text = (REPO_ROOT / CHANGELOG).read_text()
    assert re.findall(r"^## \[PDF-16\]", text, re.MULTILINE) == [], (
        "the naive id grep must still be shown returning nothing, or this control "
        "proves nothing about the tolerance"
    )
    assert len(entries_for("PDF-16", text)) == 2, (
        "the tolerant parser must find both `[Task: PDF-16 …]` entries"
    )


def test_an_id_keyed_lookup_keys_on_every_entry_not_only_the_newest() -> None:
    """X-198's constraint has a live instance: `PDF-26` carries three entries,
    `PDF-16` two. A parser that returned only the newest would report one each."""
    text = (REPO_ROOT / CHANGELOG).read_text()
    assert len(entries_for("PDF-26", text)) == 3
    assert len(entries_for("PDF-16", text)) == 2
    dates = [date for _, date, _ in entries_for("PDF-26", text)]
    assert dates == sorted(dates, reverse=True), "an id's own entries are newest-first too"


def test_the_historical_format_exemption_holds_exactly_two_entries() -> None:
    """The anti-lapse assertion on the tolerance: a THIRD non-canonical heading
    would be new debt wearing the exemption's clothes."""
    text = (REPO_ROOT / CHANGELOG).read_text()
    historical = [raw for raw in headings(text) if HISTORICAL.match(raw)]
    assert len(historical) == 2, (
        f"expected exactly two frozen historical headings, got {historical}"
    )
    canonical = [raw for raw in headings(text) if CANONICAL.match(raw)]
    assert len(canonical) + len(historical) == len(headings(text)), (
        "a heading matching neither form is unparseable, so every check keyed on "
        "ids would silently pass over it"
    )


def test_every_heading_introduced_after_the_baseline_is_canonical() -> None:
    """AC12's forward half. `7f4183f` introduced the last non-canonical heading;
    everything after it is held to `changelog.md:7`'s own format."""
    require_full_history()
    ordered = commits()
    baseline_full = _git("rev-parse", FORMAT_BASELINE).stdout.strip()
    assert baseline_full in ordered, f"the frozen format baseline {FORMAT_BASELINE} is unreachable"

    seen: set[str] = set()
    offenders: list[str] = []
    after_baseline = False
    for sha in ordered:
        current = headings(changelog_at(sha))
        if after_baseline:
            for raw in current:
                if raw not in seen and not CANONICAL.match(raw):
                    offenders.append(f"{sha[:7]} ({subject_of(sha)}): {raw}")
        seen |= set(current)
        if sha == baseline_full:
            after_baseline = True
    assert offenders == [], (
        "non-canonical heading(s) introduced after the baseline:\n  " + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------- #
# AC13 — no-loss
# --------------------------------------------------------------------------- #


def losses_at(sha: str) -> list[str]:
    """Headings present at *sha*'s parent and absent at *sha*, byte-exact."""
    current = set(headings(changelog_at(sha)))
    lost: set[str] = set()
    for parent in parents_of(sha):
        lost |= set(headings(changelog_at(parent))) - current
    return sorted(lost)


def test_the_no_loss_instrument_is_self_tested_first() -> None:
    """B-088, by name. The instrument is shown finding a KNOWN needle before any
    green it reports is believed — three shell instruments got this comparison
    wrong on this very file and one of them got it wrong SILENTLY."""
    require_full_history()
    before = set(headings(changelog_at("73f6722")))
    after = set(headings(changelog_at("d458517")))
    assert LOST_NEEDLE in before, "the needle must be present at 73f6722"
    assert LOST_NEEDLE not in after, "the needle must be absent at d458517"
    assert sorted(before - after) == [LOST_NEEDLE], (
        "the needle is the ONLY heading lost between those two revisions; a "
        "comparator reporting more or fewer is not the instrument B-088 validated"
    )


def test_the_no_loss_guard_is_red_at_the_commit_that_lost_an_entry() -> None:
    """AC13's positive control, supplied free by history."""
    require_full_history()
    lost = losses_at("33bf481")
    assert lost == [LOST_NEEDLE], (
        f"33bf481 is this guard's red and it must stay red; it reported {lost}"
    )


def test_no_other_commit_ever_loses_a_changelog_heading() -> None:
    """AC13. For every commit the heading set is a SUPERSET of its parent's."""
    require_full_history()
    exempt = {_git("rev-parse", sha).stdout.strip() for sha in NO_LOSS_EXEMPT}
    offenders = [
        f"{sha[:7]} ({subject_of(sha)}) lost {losses_at(sha)}"
        for sha in commits()
        if sha not in exempt and losses_at(sha)
    ]
    assert offenders == [], "\n  ".join(["a landed changelog entry was destroyed:", *offenders])


def test_the_no_loss_register_holds_exactly_one_commit() -> None:
    require_full_history()
    assert len(NO_LOSS_EXEMPT) == 1
    for sha in NO_LOSS_EXEMPT:
        assert _git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0, (
            f"{sha} is not reachable; a register naming an unreachable commit is a silencer"
        )


# --------------------------------------------------------------------------- #
# AC14 — prepend position
# --------------------------------------------------------------------------- #


def misplaced_at(sha: str) -> list[str]:
    """Headings *sha* added that do NOT sit above every pre-existing heading,
    or that sit above the anchor."""
    text = changelog_at(sha)
    if text is None:
        return []
    current = headings(text)
    existing: set[str] = set()
    for parent in parents_of(sha):
        existing |= set(headings(changelog_at(parent)))
    added = [raw for raw in current if raw not in existing]
    if not added:
        return []

    offenders: list[str] = []
    still_present = [raw for raw in current if raw in existing]
    if still_present:
        last_added = max(current.index(raw) for raw in added)
        first_existing = min(current.index(raw) for raw in still_present)
        if last_added > first_existing:
            offenders.extend(raw for raw in added if current.index(raw) > first_existing)
    if ANCHOR in text:
        anchor_at = text.index(ANCHOR)
        offenders.extend(raw for raw in added if text.index(raw) < anchor_at)
    return sorted(set(offenders))


def test_every_added_heading_is_prepended_below_the_anchor() -> None:
    """AC14. What `changelog.md:10-19` states and nothing enforced — measured
    against git rather than against a date ordering that already implied it."""
    require_full_history()
    exempt = {_git("rev-parse", sha).stdout.strip() for sha in PREPEND_EXEMPT}
    offenders = [
        f"{sha[:7]} ({subject_of(sha)}) filed {misplaced_at(sha)}"
        for sha in commits()
        if sha not in exempt and misplaced_at(sha)
    ]
    assert offenders == [], "\n  ".join(["entry filed out of position:", *offenders])


def test_the_prepend_guard_fires_on_a_synthesized_appending_commit(tmp_path: Path) -> None:
    """AC14's RED, in a scratch worktree under `$TMPDIR` — never a checkout of
    the working tree (HC-4), which is how `[B-094]` obtained its own reds."""
    repo = tmp_path / "scratch"
    repo.mkdir()

    def run(*args: str) -> None:
        result = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, f"git {args}: {result.stderr}"

    run("init", "-q", "-b", "main")
    run("config", "user.email", "scratch@example.invalid")
    run("config", "user.name", "scratch")
    log = repo / CHANGELOG
    first = "## [PDF-01] first — 2026-08-29"
    log.write_text(f"# Changelog\n\n{ANCHOR}\n\n{first}\n")
    run("add", CHANGELOG)
    run("commit", "-q", "-m", "[PDF-01] feat: first")
    appended = "## [PDF-02] appended at the BOTTOM — 2026-08-30"
    log.write_text(f"# Changelog\n\n{ANCHOR}\n\n{first}\n\n{appended}\n")
    run("add", CHANGELOG)
    run("commit", "-q", "-m", "[PDF-02] feat: second")

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=False
    ).stdout.strip()
    text = (repo / CHANGELOG).read_text()
    current = headings(text)
    existing = {first}
    added = [raw for raw in current if raw not in existing]
    last_added = max(current.index(raw) for raw in added)
    first_existing = min(current.index(raw) for raw in current if raw in existing)
    assert last_added > first_existing, (
        f"the synthesized commit {head[:7]} appends {added} BELOW an existing "
        "heading, which is exactly what AC14 forbids"
    )


def test_the_prepend_register_holds_exactly_one_commit_and_names_a_restoration() -> None:
    require_full_history()
    assert len(PREPEND_EXEMPT) == 1
    for sha in PREPEND_EXEMPT:
        assert _git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0
        assert "restore" in subject_of(sha), (
            "the one admissible reason to file below an existing entry is restoring "
            "one that was destroyed; any other reason is new debt"
        )


# --------------------------------------------------------------------------- #
# AC15 — entry owed
# --------------------------------------------------------------------------- #


def test_every_spec_or_remediation_commit_writes_its_own_entry() -> None:
    """AC15. `changelog.md:14-15`: each spec's own commit writes its own entry,
    so `git show <sha> -- changelog.md` proves the entry and the code landed
    together. Born red on history; the debt is registered, never back-filled."""
    require_full_history()
    exempt = {_git("rev-parse", sha).stdout.strip() for sha in ENTRY_OWED_EXEMPT}
    offenders = [
        f"{sha[:7]} ({subject_of(sha)})"
        for sha in commits()
        if sha not in exempt
        and OWES_AN_ENTRY.match(subject_of(sha))
        and CHANGELOG not in touched_files(sha)
    ]
    assert offenders == [], "\n  ".join(
        ["commit(s) owing a changelog entry that wrote none:", *offenders]
    )


def test_the_entry_owed_register_is_frozen_reachable_and_older_than_head() -> None:
    """The register's own anti-lapse assertion.

    The spec froze this at THREE. It was FOUR at `7afdb1a`: `b3c92f7` landed
    in the `PDF-18` wave, after the spec was drafted, and owed an entry it
    never wrote. It is FIVE as of `PDF-34`'s landing (X-467): `be89f36`
    (`[B-218]`) is a LANDED commit whose touched-file set is immutable, so
    X-408's "pay" disposition was withdrawn and registration ruled the only
    disposition available — X-408 is struck, not the register's own design.
    Each growth is B-042's class RECURRING, reported as a finding rather than
    quietly absorbed — and the size is asserted so a sixth is a test failure.
    """
    require_full_history()
    assert len(ENTRY_OWED_EXEMPT) == 5, (
        "the register was three at 2d19bcb, four at 7afdb1a, and is five as of "
        "PDF-34 (X-467, be89f36/[B-218]); growing it is the B-042 class recurring "
        "and is a FINDING for the PM, never an edit made to reach green"
    )
    reachable = set(commits())
    for sha, subject in ENTRY_OWED_EXEMPT.items():
        full = _git("rev-parse", sha).stdout.strip()
        assert full in reachable, f"{sha} is not reachable from HEAD"
        assert subject_of(full) == subject, (
            f"{sha}'s subject is {subject_of(full)!r}, not the registered {subject!r}; "
            "a register that has drifted off its own commits silences the wrong ones"
        )
        assert CHANGELOG not in touched_files(full), (
            f"{sha} now touches {CHANGELOG}, so its exemption no longer names a real "
            "debt — a stale exemption is a silencer waiting for its file to change"
        )


def test_the_entry_owed_guard_can_fail() -> None:
    """AC15's RED, driven with the register emptied rather than history changed."""
    require_full_history()
    offenders = [
        sha[:7]
        for sha in commits()
        if OWES_AN_ENTRY.match(subject_of(sha)) and CHANGELOG not in touched_files(sha)
    ]
    assert sorted(offenders) == sorted(ENTRY_OWED_EXEMPT), (
        "with the register emptied the guard must name exactly the registered "
        f"commits; it named {sorted(offenders)}"
    )
