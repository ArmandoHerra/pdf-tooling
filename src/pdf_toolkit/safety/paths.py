"""Path identity, containment and planning helpers.

Three of this package's guarantees — no-clobber, planned-output collision, and
"is the destination the same file as the input" — are all the same question:
**are these two paths one file?** They are equality tests across aliases, and an
alias-blind comparison gets them wrong in the direction that matters. The
sibling product's MHC-81 guard compared with ``abs()`` alone and, under macOS's
symlinked ``$TMPDIR`` parent (``/var`` → ``/private/var``), *called one file
two*: the guard fired once where it should have fired twice.

So identity is decided by :func:`canonical` plus, when the path exists,
``(st_dev, st_ino)`` — two names for one inode are one destination.

**Canonical form is a comparison key and nothing else.** Every message, every
``ItemResult.output`` and every structured payload echoes the path *as the user
wrote it*. Canonicalizing what is printed would turn a relative path the user
typed into an absolute one they never saw, and would rewrite goldens for no
gain; that is why each helper here takes the as-written spelling for the message
and derives the key privately.

Nothing in this module mutates the filesystem. ``os.access`` and ``stat`` are
reads; the one module allowed to write is ``atomic.py``.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from pdf_toolkit.errors import (
    DestinationUnwritableError,
    OutputCollisionError,
    OutputEscapesDirError,
    TargetExistsError,
)

__all__ = [
    "canonical",
    "check_output_collisions",
    "declared_device",
    "ensure_destination_writable",
    "ensure_no_clobber",
    "ensure_within",
    "identity_key",
    "nearest_existing_ancestor",
    "resolved_device",
    "same_destination",
    "target_exists",
]


def canonical(path: Path | str) -> Path:
    """The comparison key for *path*: expanded, absolute, symlinks resolved.

    ``strict=False`` because a destination legitimately does not exist yet — the
    key must be computable for a path that is about to be created.
    """
    return Path(path).expanduser().absolute().resolve(strict=False)


def identity_key(path: Path | str) -> tuple[object, ...]:
    """A hashable key that is equal for any two names of one file.

    Uses ``(st_dev, st_ino)`` when the path exists, which catches hard links —
    two entirely distinct paths, neither a symlink to the other, that are one
    inode. Falls back to the canonical string when it does not, which catches
    aliases through symlinked parent directories.
    """
    resolved = canonical(path)
    try:
        status = resolved.stat()
    except OSError:
        return ("path", str(resolved))
    return ("inode", status.st_dev, status.st_ino)


def same_destination(left: Path | str, right: Path | str) -> bool:
    """Whether two paths name one destination."""
    return identity_key(left) == identity_key(right)


def check_output_collisions(outputs: Sequence[Path | str]) -> None:
    """Refuse (exit 5) when two planned outputs resolve to one destination.

    Runs over the whole planned output set **before the first write**, so a
    200-file batch refuses at item 0 rather than after 137 files have landed.
    Both colliding paths are named in the message exactly as they were passed.
    """
    seen: dict[tuple[object, ...], str] = {}
    for candidate in outputs:
        key = identity_key(candidate)
        first = seen.get(key)
        if first is not None:
            raise OutputCollisionError(
                f"two planned outputs resolve to one destination: {first} and {candidate}",
                path=str(candidate),
            )
        seen[key] = str(candidate)


def ensure_within(base: Path | str, candidate: Path | str) -> None:
    """Refuse (exit 5) when *candidate* resolves outside *base*.

    The containment half of output naming, and deliberately only that half. A
    *statically malformed* template — one containing a path separator or ``..``
    — is a bad invocation and is rejected by the CLI layer as exit 2 before this
    is ever reached. What this function catches is different in kind: a
    destination that escapes only after token substitution, because the data
    (a filename stem, say) carried the traversal. That is discovered at plan
    time from data rather than from the command line, so it is a safety refusal.

    The comparison is between canonical forms, so a symlinked ``--out-dir`` does
    not defeat the check by making a contained path look external.

    Vocabulary — which tokens a template may use — is a *verb's* concern and
    lives with the verb that defines them. Containment is a safety concern and
    lives here. A renderer must call this on the path it produced.
    """
    base_key = canonical(base)
    candidate_key = canonical(candidate)
    if candidate_key == base_key or base_key in candidate_key.parents:
        return
    raise OutputEscapesDirError(
        f"the resolved output {candidate} escapes the output directory {base}",
        path=str(candidate),
    )


def target_exists(target: Path | str) -> bool:
    """Whether *target* already occupies a directory entry — a plain read.

    The same existence test :func:`ensure_no_clobber` uses (a dangling symlink
    counts as occupied), exposed as a boolean predicate for a caller that
    needs to know *whether* a refusal is coming rather than trigger one. The
    non-TTY bulk-destructive confirmation gate (`PLAN.md` §5.3) is the first
    consumer: it must decide whether a run is "destructive" — `--force` over
    an *existing* target — before deciding whether to prompt at all, and
    prompting is a CLI-layer concern this module has no business making.
    """
    written = Path(target).expanduser().absolute()
    return canonical(target).exists() or os.path.lexists(written)


def ensure_no_clobber(target: Path | str, *, force: bool, in_place: bool = False) -> None:
    """Refuse (exit 5) when *target* exists and overwriting was not requested.

    ``in_place`` suppresses the check by definition: ``--in-place`` names an
    existing file as its own destination, so treating that existence as a clobber
    would make the flag unusable. The protection ``--in-place`` gets instead is
    the ``.bak`` sidecar and the confirmation gate, not this one.

    Both an existing file and a *dangling symlink* count as occupied: replacing
    a dangling link still destroys a directory entry the user created.
    """
    if force or in_place:
        return
    written = Path(target).expanduser().absolute()
    if canonical(target).exists() or os.path.lexists(written):
        raise TargetExistsError(
            f"{target} exists; pass --force to overwrite it",
            path=str(target),
        )


def ensure_destination_writable(
    directory: Path | str,
    *,
    as_written: Path | str | None = None,
) -> None:
    """Fail (exit 1) when the destination directory cannot accept a write.

    Checked at plan time, before an engine runs: producing bytes and only then
    discovering there is nowhere to put them wastes the expensive half of the
    operation and produces a worse diagnostic.

    Exit 1 rather than 5 on purpose — nothing declined on safety grounds, the
    filesystem simply cannot accept the write.
    """
    shown = str(as_written if as_written is not None else directory)
    resolved = canonical(directory)
    if not resolved.is_dir():
        raise DestinationUnwritableError(
            f"destination directory does not exist: {shown}",
            path=shown,
        )
    if not os.access(resolved, os.W_OK | os.X_OK):
        raise DestinationUnwritableError(
            f"destination directory is not writable: {shown}",
            path=shown,
        )


def declared_device(path: Path | str) -> int | None:
    """The device id of the filesystem the user's *spelling* of *path* lives on.

    Walks up to the deepest existing ancestor and ``lstat``s it — ``lstat`` does
    not follow a final symlink component, so a directory entry that is a symlink
    reports the device its *entry* lives on rather than the device it points at.
    That difference is exactly the cross-filesystem condition worth warning
    about: the user named one filesystem and the bytes land on another.

    Returns ``None`` only if nothing in the chain can be stat'ed at all.
    """
    current = Path(path).expanduser().absolute()
    for candidate in (current, *current.parents):
        try:
            return os.lstat(candidate).st_dev
        except OSError:
            continue
    return None


def resolved_device(path: Path | str) -> int | None:
    """The device id of the filesystem the bytes will actually land on."""
    resolved = canonical(path)
    for candidate in (resolved, *resolved.parents):
        try:
            return candidate.stat().st_dev
        except OSError:
            continue
    return None


def nearest_existing_ancestor(path: Path | str) -> Path:
    """Read-only walk to the deepest existing ancestor of *path*, inclusive.

    Mirrors :func:`declared_device`'s own walk over ``(current, *current.parents)``
    -- that function asks the deepest stat-able ancestor for a device id;
    this one asks the same walk a different question ("does this exist?").
    It is what lets a caller predict whether a not-yet-existing path's
    eventual ``mkdir(parents=True, exist_ok=True)`` would land inside a real
    directory, land on a non-directory (``ENOTDIR``/``EEXIST``), or be
    refused for want of permission (``EACCES``) -- **without performing the
    operation** (PDF-18 Design D4).

    ``Path.exists()`` follows a final symlink and swallows *most* stat-time
    ``OSError``s (an inaccessible intermediate component included) -- but
    not every one. ``ENAMETOOLONG`` is a documented exception (CPython's own
    ``_ignore_error`` allowlist does not cover it), and a too-long component
    is exactly the condition this function exists to let a caller predict
    without performing the operation. So every candidate's existence check
    is wrapped here too: this is the read a *prediction* is allowed, and it
    must never raise for a caller asking a filesystem question about a
    destination that legitimately does not exist yet, however it fails to
    exist.

    The walk always terminates: a filesystem's root always exists, so the
    last candidate in ``current.parents`` is always returned if nothing
    closer does.
    """
    current = Path(path).expanduser().absolute()
    for candidate in (current, *current.parents):
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return current.parents[-1]
