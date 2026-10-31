"""PDF-169 (B-549): pin ``uv.lock``'s ``revision`` to the uv that CI runs.

THE DEFECT. A ``uv lock`` run with a host's default uv can silently rewrite ``uv.lock`` from
``revision = 5`` to ``revision = 3``. CI's pinned uv accepts the downgraded lock: both
``uv lock --check`` and ``uv sync --locked`` answer rc 0 and leave the bytes alone, and a re-lock
keeps the revision it finds. So nothing in CI saw it. This module is the only instrument that does.

HOW IT PINS. CI's uv is *derived* from the ``astral-sh/setup-uv`` steps of every workflow, mapped
through ``LOCK_REVISION_WRITTEN_BY_UV`` (a measured register), and compared with the lock's header.

Everything here reads the working tree only. It reads no git history and spawns no process.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UV_LOCK = REPO_ROOT / "uv.lock"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"

#: Re-declared, not imported from tests/test_docs_antirot.py: importing one test module into
#: another gives it a second import identity under pytest's prepend mode (PDF-154 precedent).
FENCED_BLOCK = re.compile(r"```.*?```", re.DOTALL)

#: The header uv writes, anchored at byte 0. No TOML parse: a parse would accept the key anywhere.
LOCK_HEADER = re.compile(r"\Aversion = 1\nrevision = (\d+)\n")

#: PDF-169 (B-549). The `revision` each uv writes into a fresh uv.lock, measured with
#: `uvx uv@<v> lock` on a checkout with no uv.lock. A re-lock KEEPS the revision it finds,
#: so a lock written by another uv is not repaired by re-locking. Moving CI's uv pin needs
#: a new row here, measured, never copied.
LOCK_REVISION_WRITTEN_BY_UV: Final[Mapping[str, int]] = MappingProxyType({"0.13.5": 5})


def lock_revision(text: str) -> int:
    """The ``revision`` of a uv.lock text; AssertionError if the header is not what uv writes."""
    match = LOCK_HEADER.match(text)
    assert match, (
        "uv.lock does not start with `version = 1` then `revision = <n>`; first two lines: "
        f"{text.splitlines()[:2]!r}"
    )
    return int(match.group(1))


def ci_uv_versions() -> list[str]:
    """The `version:` of every `astral-sh/setup-uv` step in every workflow."""
    import yaml

    versions: list[str] = []
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for job in (document.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                if str(step.get("uses", "")).startswith("astral-sh/setup-uv@"):
                    versions.append(str((step.get("with") or {}).get("version")))
    return versions


def ci_uv() -> str:
    """The one uv CI runs; asserts there is at least one setup-uv step and exactly one value."""
    versions = ci_uv_versions()
    assert versions, "no astral-sh/setup-uv step found in any workflow"
    distinct = sorted(set(versions))
    assert len(distinct) == 1, f"the setup-uv steps pin more than one uv: {distinct}"
    return distinct[0]


def test_every_setup_uv_step_pins_one_uv_whose_lock_revision_is_measured() -> None:
    versions = ci_uv_versions()
    uv = ci_uv()
    print(f"setup-uv steps: {len(versions)}, uv {uv}")
    assert uv in LOCK_REVISION_WRITTEN_BY_UV, (
        f"CI pins uv {uv}, which has no row in LOCK_REVISION_WRITTEN_BY_UV: measure "
        f"`uvx uv@{uv} lock` on a fresh checkout and add the row"
    )


def test_uv_lock_carries_the_revision_ci_uv_writes() -> None:
    uv = ci_uv()
    expected = LOCK_REVISION_WRITTEN_BY_UV[uv]
    found = lock_revision(UV_LOCK.read_text(encoding="utf-8"))
    assert found == expected, (
        f"uv.lock carries revision = {found}, but CI's uv {uv} writes revision = {expected}. "
        "Re-locking keeps the revision it finds, so restore the lock first: "
        f"`git show origin/main:uv.lock > uv.lock`, then `uvx uv@{uv} lock`"
    )


def test_the_lock_revision_parser_reads_a_downgraded_header() -> None:
    downgraded = 'version = 1\nrevision = 3\nrequires-python = ">=3.11"\n'
    assert lock_revision(downgraded) == 3
    assert lock_revision(downgraded) != LOCK_REVISION_WRITTEN_BY_UV["0.13.5"]
    with pytest.raises(AssertionError):
        lock_revision('version = 1\nrequires-python = ">=3.11"\n')


def test_contributing_relocks_with_the_ci_uv_in_a_fenced_block() -> None:
    command = f"uvx uv@{ci_uv()} lock"
    text = CONTRIBUTING.read_text(encoding="utf-8")
    bash_blocks = [b for b in FENCED_BLOCK.findall(text) if b.startswith("```bash\n")]
    assert any(command in block.splitlines() for block in bash_blocks), (
        f"CONTRIBUTING.md has no ```bash block with the whole line {command!r}"
    )
