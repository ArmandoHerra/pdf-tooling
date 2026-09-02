"""The ``--dry-run`` purity primitive: prove it, do not assert it.

``PLAN.md`` §10 calls the dry-run purity test *the single most important test in
the suite, because it is the guarantee users act on*, and D-06 records it as the
one safety behaviour that is not cheaply reversible. A test that merely asserted
"the writer did not call ``os.replace``" would prove something about the writer.
This proves something about the **filesystem**: it photographs every root before
the run and again afterwards, and any difference at all is a failure.

PDF-06 parameterizes this over the verb registry, so every verb written after it
is covered without its author doing anything. This module defines the primitive
and its contract; it deliberately does **not** create ``tests/conftest.py`` — the
fixture wiring is PDF-06's, and a contended file with two owners in one wave is
how a merge goes wrong.

What an entry records, and why each field is there
-------------------------------------------------
``(st_dev, st_ino, st_mode, st_size, st_mtime_ns, sha256, symlink_target)``

* **``atime`` is excluded.** A dry run legitimately *reads*: it opens documents
  to count pages. Including access time would assert "nothing was read", which
  is the wrong guarantee, and would make the most important test in the suite
  flake on ``relatime`` mounts.
* **Directory ``st_mtime_ns`` is included.** It is the only signal that catches a
  create-then-delete *inside* the run — the failure mode where a verb writes a
  temp file, notices the dry-run flag late, and tidies up. Nothing else in a
  before/after comparison sees that at all.
* **``st_ino`` is included.** It is the only signal that catches a file replaced
  with byte-identical content, which is exactly what an atomic writer that
  ignored the gate would produce.
* **``st_mode`` is included**, because metadata mutation is still mutation.

The environment rule that makes it deterministic
------------------------------------------------
``$TMPDIR`` and ``$HOME`` are redirected per test, into the test's own temporary
directory, and **both are snapshot roots**. Without that, "assert the temp
directory gained nothing" is a single glob racing every other process on the
machine; with it, it is a whole-tree comparison. :func:`redirected_environment`
is the one place that rule is implemented, so PDF-06 inherits it rather than
re-deriving it.

Negative controls are a deliverable
-----------------------------------
A comparator that always returned "equal" would make this test green and
meaningless — the precise failure mode this product's testing strategy exists to
prevent. ``tests/integration/test_purity_primitive.py`` plants **nine** mutation
classes and proves each one is detected, and proves the non-dry-run control
produces a non-empty diff.

Nine, not six: the count in this docstring said *six* from PDF-04's landing
until PDF-19 measured it (2026-09-02). The six ``control_one``…``control_six``
arms are joined by create-then-delete (caught only by directory ``mtime``),
symlink retarget, and ``assert_unchanged`` naming every difference. PDF-19 also
ablated each compared dimension and confirmed exactly the control that depends
on it goes blind, so the six fields in :data:`_FIELDS` are load-bearing rather
than decorative.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import stat
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "Difference",
    "Entry",
    "Snapshot",
    "assert_pure",
    "assert_unchanged",
    "diff",
    "redirected_environment",
    "snapshot",
]

_CHUNK: Final[int] = 1 << 16


@dataclass(frozen=True, slots=True)
class Entry:
    """One filesystem object, reduced to what a purity comparison needs."""

    dev: int
    ino: int
    mode: int
    size: int
    mtime_ns: int
    sha256: str | None
    symlink_target: str | None


@dataclass(frozen=True, slots=True)
class Difference:
    """One way in which two snapshots disagree about one path."""

    path: str
    kind: str
    before: object
    after: object

    def __str__(self) -> str:
        if self.kind == "added":
            return f"{self.path}: added"
        if self.kind == "removed":
            return f"{self.path}: removed"
        return f"{self.path}: {self.kind} {self.before!r} -> {self.after!r}"


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Every filesystem object under a set of roots, at one instant."""

    roots: tuple[str, ...]
    entries: Mapping[str, Entry]

    def __len__(self) -> int:
        return len(self.entries)


def _digest(path: Path) -> str | None:
    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(_CHUNK)
                if not chunk:
                    break
                hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


def _entry(path: Path) -> Entry | None:
    try:
        status = os.lstat(path)
    except OSError:
        return None
    mode = status.st_mode
    target: str | None = None
    digest: str | None = None
    if stat.S_ISLNK(mode):
        with contextlib.suppress(OSError):
            target = os.readlink(path)
    elif stat.S_ISREG(mode):
        digest = _digest(path)
    return Entry(
        dev=status.st_dev,
        ino=status.st_ino,
        mode=mode,
        size=status.st_size,
        mtime_ns=status.st_mtime_ns,
        sha256=digest,
        symlink_target=target,
    )


def _walk(root: Path) -> Iterator[Path]:
    """Yield *root* and everything beneath it, never following a symlink."""
    stack = [root]
    while stack:
        current = stack.pop()
        yield current
        if current.is_symlink():
            continue
        try:
            children = [Path(item.path) for item in os.scandir(current)]
        except OSError:
            continue
        stack.extend(children)


def snapshot(*roots: Path | str) -> Snapshot:
    """Photograph every filesystem object under *roots*."""
    entries: dict[str, Entry] = {}
    keys: list[str] = []
    for raw in roots:
        root = Path(raw)
        keys.append(str(root))
        for path in _walk(root):
            found = _entry(path)
            if found is not None:
                entries[str(path)] = found
    return Snapshot(roots=tuple(keys), entries=entries)


#: The comparison, field by field. Ordered so the most informative difference is
#: reported first when several fire at once.
_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("ino", "inode"),
    ("sha256", "content"),
    ("mode", "mode"),
    ("size", "size"),
    ("symlink_target", "symlink"),
    ("mtime_ns", "mtime"),
)


def diff(before: Snapshot, after: Snapshot) -> list[Difference]:
    """Every way in which *after* differs from *before*."""
    found: list[Difference] = []
    for path in sorted(set(before.entries) - set(after.entries)):
        found.append(Difference(path, "removed", before.entries[path], None))
    for path in sorted(set(after.entries) - set(before.entries)):
        found.append(Difference(path, "added", None, after.entries[path]))
    for path in sorted(set(before.entries) & set(after.entries)):
        old = before.entries[path]
        new = after.entries[path]
        for field, kind in _FIELDS:
            was = getattr(old, field)
            now = getattr(new, field)
            if was != now:
                found.append(Difference(path, kind, was, now))
    return found


def assert_unchanged(before: Snapshot, after: Snapshot) -> None:
    """Fail, naming every difference, if anything under the roots changed."""
    differences = diff(before, after)
    if not differences:
        return
    listed = "\n".join(f"  - {item}" for item in differences)
    raise AssertionError(
        f"{len(differences)} filesystem difference(s) across "
        f"{len(before.roots)} root(s); a pure run makes none:\n{listed}"
    )


@contextlib.contextmanager
def assert_pure(*roots: Path | str) -> Iterator[Snapshot]:
    """Snapshot *roots*, run the block, and fail if anything at all changed."""
    before = snapshot(*roots)
    yield before
    assert_unchanged(before, snapshot(*roots))


def redirected_environment(
    base: Path,
    env: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], tuple[Path, ...]]:
    """Build an environment whose ``$TMPDIR`` and ``$HOME`` live under *base*.

    Returns the environment to hand a subprocess, and the roots to snapshot.
    Both redirected directories are roots: a run that wrote into the real
    ``/tmp`` or the real home directory would otherwise be invisible to a
    comparison scoped to the working tree, and "wrote a temp file it forgot to
    remove" is the most likely way a verb breaks purity.

    ``PYTHONDONTWRITEBYTECODE`` is set for the same reason it is set in any
    reproducibility harness: a ``__pycache__`` entry is a real filesystem write,
    it is not the one under test, and letting it happen makes the signal noisy.
    """
    tmp = base / "tmp"
    home = base / "home"
    tmp.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    prepared = dict(os.environ if env is None else env)
    prepared["TMPDIR"] = str(tmp)
    prepared["TEMP"] = str(tmp)
    prepared["TMP"] = str(tmp)
    prepared["HOME"] = str(home)
    prepared["PYTHONDONTWRITEBYTECODE"] = "1"
    return prepared, (tmp, home)
