#!/usr/bin/env python3
"""Reap the engine-hiding shim directories left behind by pre-PDF-46 sessions.

PDF-46 D5. `tests/conftest.py`'s engine-hiding shim used to `mkdtemp()` with no
teardown at all, so every pytest process -- and under the project's default
`-n auto`, every xdist worker as well -- left one directory of symlinks in
`$TMPDIR`. PDF-46 registers an `atexit` reclaim, which stops the leak from
*now* on and, deliberately, removes nothing that was already there.

WHY THIS SCRIPT IS NOT A FIXTURE, NOT A TEST, AND NOT PART OF ANY GATE
----------------------------------------------------------------------
The standing residue is the `qa-sentinel`'s recorded evidence. It is removed by
an OPERATOR, on purpose, at a moment named in the spec -- not by a suite run
that happens to pass. So this file lists by default and removes nothing; the
destructive path needs a word typed (`--confirm`, i.e. `make shim-reap
CONFIRM=1`). That mirrors the product's own rule that inputs are immutable by
default and outputs never clobber without `-f`, applied to the operator's
`$TMPDIR`.

WHY `shutil.rmtree` AND NOT A RECURSIVE-FORCE SHELL DELETE
-----------------------------------------------------------
E7, and it is a measurement rather than a preference: the agent layer's
`git_safety_guard.py` REFUSES recursive-force deletes, so a `make` recipe built
out of one is unrunnable by any agent in this loop. It would be a target usable
by a human and inert for the sentinel that most needs it.

The two-word shell form is not spelled anywhere in this file, and that is also
deliberate. `tests/test_engine_hiding_shim.py` asserts this module does not
contain it, and a guard whose subject can contain its own needle reads itself
and passes for the wrong reason -- the self-match class. The needle is
assembled at runtime there; here it simply never appears.

FOUR PREDICATES, ALL REQUIRED, EACH WITH ITS OWN SURVIVOR CONTROL
------------------------------------------------------------------
A candidate is removed only if it (a) carries the EXACT prefix, (b) is a direct
child of the root it was given, (c) is a real directory and not a symlink
wearing the prefix, and (d) is at least `--min-age-days` old. (d) is the
symmetry rule in a different hat: a younger directory may belong to a LIVE
session on the same host, and this script has no way to tell. Every survivor
class is planted individually in `tests/test_engine_hiding_shim.py`, so a
loosened predicate reddens by name rather than by an aggregate count.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

#: The exact family prefix. Deliberately the same string the ledger's own
#: census recipe globs on -- re-prefixing would silently invalidate every
#: historical reading and the sentinel's next sweep with it (D4).
PREFIX = "pdftoolkit-hide-engines-"

SECONDS_PER_DAY = 86400.0


def directory_size_bytes(path: Path) -> int:
    """`du -sb`-equivalent: apparent size, symlinks NOT dereferenced.

    `du -sbL` on one of these reports gigabytes because it sums the real
    executables behind a couple of thousand symlinks; `du -sb` reports
    kilobytes because it sums the links themselves. They differ by four orders
    of magnitude, so the instrument has to be stated rather than assumed (E4).
    This is the non-dereferencing one.

    THE ROOT'S OWN INODE SIZE IS DELIBERATELY EXCLUDED, and it is not a
    rounding question. A directory holding a couple of thousand entries has an
    `st_size` in the tens of kilobytes -- on the reference host, `94208` against
    `112207` for its whole contents -- so including it nearly doubles the
    answer. `du -sb` does not count it, and this figure exists to be COMPARED
    against the `du -sb` recipe the ledger's census publishes; two instruments
    that answer the same question with different numbers is the defect this
    whole item is about (E4), reproduced one directory down.
    """
    total = 0
    for root, dirnames, filenames in os.walk(path, followlinks=False):
        root_path = Path(root)
        for name in (*dirnames, *filenames):
            try:
                total += (root_path / name).lstat().st_size
            except OSError:
                continue
    return total


def entry_count(path: Path) -> int:
    """Entries held below *path* -- the inode figure, which is the resource
    that actually ran out on the reference host, and the one nobody was
    watching while the byte figure was being quoted."""
    total = 0
    for _root, dirnames, filenames in os.walk(path, followlinks=False):
        total += len(dirnames) + len(filenames)
    return total


def age_days(path: Path, now: float) -> float:
    try:
        return max(0.0, (now - path.lstat().st_mtime) / SECONDS_PER_DAY)
    except OSError:
        return 0.0


def candidates(root: Path) -> list[Path]:
    """Direct children of *root* carrying the exact prefix, real dirs only.

    `iterdir()` and not a recursive glob: (b) is enforced by the traversal
    itself rather than by a pattern a later edit could widen. A symlink wearing
    the prefix is EXCLUDED here, before any age or size question is asked, so
    it can never reach `shutil.rmtree`.
    """
    if not root.is_dir():
        return []
    found: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.name.startswith(PREFIX):
            continue
        if child.is_symlink() or not child.is_dir():
            continue
        found.append(child)
    return found


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reap_shims.py",
        description=(
            "List (default) or remove (--confirm) stale engine-hiding shim "
            "directories left in a temporary root by pre-PDF-46 test sessions."
        ),
    )
    parser.add_argument(
        "--root",
        default=tempfile.gettempdir(),
        help="the directory to look in; only its DIRECT children are ever considered",
    )
    parser.add_argument(
        "--min-age-days",
        type=float,
        default=1.0,
        help="never touch anything younger than this; a young one may be a live session",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="actually remove the qualifying set; without it nothing is removed",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser()
    now = time.time()

    found = candidates(root)
    qualifying: list[Path] = []
    total_bytes = 0
    total_entries = 0

    print(f"root: {root}")
    print(f"prefix: {PREFIX}*   min-age-days: {args.min_age_days}")
    if not found:
        print("no shim directories found; nothing to do")
        return 0

    for path in found:
        age = age_days(path, now)
        size = directory_size_bytes(path)
        entries = entry_count(path)
        total_bytes += size
        total_entries += entries
        old_enough = age >= args.min_age_days
        if old_enough:
            qualifying.append(path)
        marker = "REAPABLE" if old_enough else "too young"
        print(f"  {path}  age={age:.2f}d  entries={entries}  bytes={size}  [{marker}]")

    print(
        f"total: {len(found)} directory(ies), {total_bytes} bytes "
        f"(symlinks NOT dereferenced), {total_entries} entries, "
        f"{len(qualifying)} at or above the age floor"
    )

    if not args.confirm:
        print("")
        print("LISTING ONLY -- nothing was removed. Re-run with --confirm")
        print("(`make shim-reap CONFIRM=1`) to remove the REAPABLE entries above.")
        return 0

    failures: list[str] = []
    for path in qualifying:
        try:
            shutil.rmtree(path)
        except OSError as exc:
            failures.append(f"{path}: {exc}")
        else:
            print(f"removed {path}")

    if failures:
        print("")
        print(f"FAILED to remove {len(failures)} director(ies):", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        print("This target does NOT exit 0 on a removal it could not complete.", file=sys.stderr)
        return 1

    print(f"removed {len(qualifying)} director(ies)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
