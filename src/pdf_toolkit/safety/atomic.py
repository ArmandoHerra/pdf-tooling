"""``AtomicWriter`` — the one place in this product that writes.

Everything the tool promises about safety is a property of this file. Not of a
convention, not of a review checklist, and not of twenty verb authors each
remembering ``PLAN.md`` §5.2: an import-boundary test over ``src/`` fails the
build when any module outside this one performs a filesystem mutation, so the
chokepoint is structural. That is the whole reason this lands in wave 2, before
the verbs, rather than after them.

The shape a verb sees::

    with AtomicWriter(target, policy=policy, kind="pdf") as writer:
        engine.save(writer.path)      # the engine writes to writer.path, only

``__enter__`` plans and opens; ``__exit__`` commits or unwinds. A verb never
chooses whether to consult the dry-run gate, because a verb never gets to reach
past the writer.

The seven steps, exactly (``PLAN.md`` §5.3)
-------------------------------------------
1. **Dry-run gate** — literally the first statement of ``__enter__``, before any
   filesystem call at all. In a dry run the writer records the planned action
   and hands back an object whose ``.path`` raises: there is nothing to write
   to, so asking for somewhere to write is a bug the writer names immediately
   rather than a directory it silently invents. The read-only planning helpers
   in ``paths.py`` are separately callable, so a dry run can still *report* the
   refusals it would hit without this module touching anything.
2. **Plan** — resolve the destination, refuse an existing target without
   ``--force`` (exit 5), and fail early if the destination directory cannot
   accept a write (exit 1). Both happen before an engine runs.
3. **Temp** — a temp file **beside the resolved destination**, never in the
   system temp directory. That co-location is not a preference; it is what makes
   step 6 atomic, and a test asserts the temp's parent directly rather than
   assuming it.
4. **Commit** — ``flush`` → ``os.fsync`` → close. Any exception unlinks the temp
   and re-raises, so no *handled* error leaves residue.
5. **Backup** — with ``--in-place`` and backups enabled, the original is linked
   (or copied) to a ``.bak`` sidecar. ``os.link`` first: it is instant, and it is
   *correct* precisely because step 6 replaces the directory entry rather than
   truncating the file, so the sidecar keeps the original inode. ``shutil.copy2``
   is the fallback where linking is refused.
6. **Replace** — ``os.replace``, atomic within a filesystem.
7. **Crash residue** — a hard kill between 3 and 6 can leave a toolkit temp
   file. That is expected, it is reported by ``doctor --strict`` and never swept
   (``PLAN.md`` §12 R-07), and the destination is untouched either way.

``--in-place`` is never an in-place mutation
--------------------------------------------
It is this identical path with the destination equal to the input, plus step 5.
Nothing in this product ever opens a user's file for writing. That one sentence
is why a ``SIGKILL`` mid-write leaves the original byte-identical for
``--in-place`` exactly as it does for a fresh output, and it is why the product
ships without a transaction log (D-07): safety here is immutability, not
reversibility.

Recorded simplification (OR-1)
------------------------------
No-clobber is a check at plan time plus a re-check immediately before
``os.replace``. That narrows the window in which another process could create
the destination to microseconds, but it does not close it: an exclusive create
(``os.link`` of the temp onto the destination, which fails with ``EEXIST``)
would. This is a decision, not an oversight — the exclusive-create hardening is
an additive change at this same seam, and the re-check is deliberately written
as its own method so that seam stays obvious.

Cross-filesystem degradation
----------------------------
``os.replace`` is atomic *within* a filesystem. Two situations end the guarantee
and both warn on stderr in one class, ``atomicity degraded``:

* the destination resolves onto a different filesystem than the one the user
  named (an ``--out-dir`` that is a symlink to another mount) — atomicity is
  preserved because the temp sits beside the *real* destination, but the bytes
  do not land where the user pointed, and they should be told before the write
  rather than after it;
* a real ``EXDEV`` from ``os.replace``, which is completed by copying into a
  second temp on the destination filesystem, fsyncing, replacing, and then
  verifying size **and** SHA-256. A degraded path that did not verify would be a
  worse guarantee wearing the same name.
"""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import IO, Final

from pdf_toolkit.errors import BackupExistsError, FailureError, TargetExistsError
from pdf_toolkit.safety._faults import checkpoint
from pdf_toolkit.safety.paths import (
    canonical,
    declared_device,
    ensure_destination_writable,
    ensure_no_clobber,
    resolved_device,
)
from pdf_toolkit.safety.policy import SafetyPolicy
from pdf_toolkit.safety.tempnames import TEMP_PREFIX

__all__ = ["AtomicWriter", "DEGRADED_PREFIX"]

#: The one warning class both cross-filesystem conditions are reported under, so
#: a caller can match on a stable prefix instead of on prose.
DEGRADED_PREFIX: Final[str] = "atomicity degraded"

#: Copy chunk for the ``EXDEV`` fallback. Large enough not to syscall per line,
#: small enough that a multi-gigabyte document is never held in memory.
_CHUNK: Final[int] = 1 << 20

#: ``os.link`` refusals that mean "this filesystem will not hard-link", as
#: opposed to a real error worth propagating.
_LINK_FALLBACK_ERRNOS: Final[frozenset[int]] = frozenset(
    {
        errno.EPERM,
        errno.EOPNOTSUPP,
        errno.EMLINK,
        errno.EXDEV,
        errno.EACCES,
    }
)


def _default_warn(message: str) -> None:
    """Warnings go to stderr. stdout is the payload and nothing else."""
    print(f"warning: {message}", file=sys.stderr)


def _digest(path: Path) -> tuple[int, str]:
    """``(size, sha256)`` for *path*, streamed rather than read whole."""
    hasher = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            size += len(chunk)
            hasher.update(chunk)
    return size, hasher.hexdigest()


class AtomicWriter:
    """A context manager that owns one destination, one temp, and one replace.

    Args:
        target: The destination, spelled as the user spelled it. Echoed verbatim
            in every message; canonicalized only as a comparison key.
        policy: The resolved safety posture for this invocation.
        kind: A short label for the artefact, used in diagnostics.
        warn: Where warnings go. Injectable so a test can capture them without
            parsing stderr; defaults to stderr.
        _temp_dir: **Test-only.** Forces the temp onto a chosen directory so the
            cross-filesystem arm can produce a genuine kernel ``EXDEV`` instead
            of a monkeypatched ``st_dev``. Never set by product code.
    """

    def __init__(
        self,
        target: Path | str,
        *,
        policy: SafetyPolicy,
        kind: str = "pdf",
        warn: Callable[[str], None] | None = None,
        _temp_dir: Path | str | None = None,
    ) -> None:
        self.target = Path(target)
        self.policy = policy
        self.kind = kind
        self.warnings: list[str] = []
        self.backup_path: Path | None = None
        self.destination: Path = canonical(target)
        self._warn_sink = warn if warn is not None else _default_warn
        self._temp_dir = Path(_temp_dir) if _temp_dir is not None else None
        self._handle: IO[bytes] | None = None
        self._temp_path: Path | None = None
        self._dry_run = False

    # -- the surface a verb touches ---------------------------------------- #

    @property
    def path(self) -> Path:
        """The path the engine writes to. Never the destination."""
        if self._dry_run:
            raise RuntimeError(
                "--dry-run writes nothing: this writer has no path to hand out. "
                "Render the plan instead of asking for a destination."
            )
        if self._temp_path is None:
            raise RuntimeError("AtomicWriter.path is only valid inside the with-block")
        return self._temp_path

    @property
    def is_dry_run(self) -> bool:
        """Whether this writer short-circuited on the dry-run gate."""
        return self._dry_run

    def __enter__(self) -> AtomicWriter:
        # THE GATE. First statement, before any filesystem call, unconditionally.
        if self.policy.dry_run:
            self._dry_run = True
            return self
        self._plan()
        self._open_temp()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._dry_run:
            return
        if exc_type is not None:
            self._discard()
            return
        try:
            self._commit()
        except BaseException:
            self._discard()
            raise

    # -- steps 2 and 3 ------------------------------------------------------ #

    def _plan(self) -> None:
        ensure_no_clobber(
            self.target,
            force=self.policy.force,
            in_place=self.policy.in_place,
        )
        ensure_destination_writable(
            self.destination.parent,
            as_written=self.target.parent,
        )
        self._warn_if_destination_moved()

    def _warn_if_destination_moved(self) -> None:
        """Condition 1: the bytes land on a filesystem the user did not name."""
        named = declared_device(self.target)
        actual = resolved_device(self.destination.parent)
        if named is None or actual is None or named == actual:
            return
        self._warn(
            f"{DEGRADED_PREFIX}: {self.target} (device {named}) resolves to "
            f"{self.destination} (device {actual}) on a different filesystem; the write "
            f"stays atomic on the destination filesystem, but not on the one you named"
        )

    def _open_temp(self) -> None:
        directory = self._temp_dir if self._temp_dir is not None else self.destination.parent
        # Closed in _commit (after fsync) or _discard (on any failure).
        handle = tempfile.NamedTemporaryFile(
            dir=directory,
            prefix=TEMP_PREFIX,
            delete=False,
        )
        self._handle = handle
        self._temp_path = Path(handle.name)
        checkpoint("after_temp_create", str(self._temp_path))

    # -- steps 4 to 6 ------------------------------------------------------- #

    def _commit(self) -> None:
        handle = self._handle
        temp = self._temp_path
        if handle is None or temp is None:  # pragma: no cover - unreachable by construction
            raise RuntimeError("AtomicWriter was committed without having been entered")

        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        self._handle = None
        checkpoint("after_fsync", str(temp))

        self._make_backup()
        checkpoint("after_backup", str(temp))

        self._replace(temp)
        self._temp_path = None

    def _make_backup(self) -> None:
        if not (self.policy.in_place and self.policy.backup):
            return
        if not self.destination.exists():
            return

        sidecar = self.destination.with_name(self.destination.name + ".bak")
        if sidecar.exists():
            if not self.policy.force:
                raise BackupExistsError(
                    f"{sidecar.name} already exists beside {self.target}; "
                    f"pass --force to replace the sidecar",
                    path=str(sidecar),
                )
            os.unlink(sidecar)

        try:
            os.link(self.destination, sidecar)
        except OSError as error:
            if error.errno not in _LINK_FALLBACK_ERRNOS:
                raise
            shutil.copy2(self.destination, sidecar)
        self.backup_path = sidecar

    def _recheck_no_clobber(self) -> None:
        """OR-1: the second half of the narrowed TOCTOU window.

        The exclusive-create hardening, if it is ever wanted, replaces this
        method and nothing else.
        """
        if self.policy.force or self.policy.in_place:
            return
        if self.destination.exists():
            raise TargetExistsError(
                f"{self.target} appeared while the write was in flight; "
                f"pass --force to overwrite it",
                path=str(self.target),
            )

    def _replace(self, temp: Path) -> None:
        self._recheck_no_clobber()
        try:
            os.replace(temp, self.destination)
        except OSError as error:
            if error.errno != errno.EXDEV:
                raise
            self._replace_across_devices(temp)

    def _replace_across_devices(self, temp: Path) -> None:
        """Condition 2: a real ``EXDEV``, completed and then verified."""
        source_device = declared_device(temp)
        target_device = resolved_device(self.destination.parent)
        self._warn(
            f"{DEGRADED_PREFIX}: cross-device rename from {temp} (device {source_device}) "
            f"to {self.destination} (device {target_device}); completing with "
            f"copy, fsync, replace and a size plus SHA-256 verification"
        )

        expected_size, expected_digest = _digest(temp)
        staged = tempfile.NamedTemporaryFile(
            dir=self.destination.parent,
            prefix=TEMP_PREFIX,
            delete=False,
        )
        staged_path = Path(staged.name)
        try:
            with open(temp, "rb") as source:
                while True:
                    chunk = source.read(_CHUNK)
                    if not chunk:
                        break
                    staged.write(chunk)
            staged.flush()
            os.fsync(staged.fileno())
        finally:
            staged.close()

        self._recheck_no_clobber()
        os.replace(staged_path, self.destination)
        self._unlink_quietly(temp)

        actual_size, actual_digest = _digest(self.destination)
        if (actual_size, actual_digest) != (expected_size, expected_digest):
            raise FailureError(
                f"the degraded write to {self.target} did not verify: "
                f"expected {expected_size} bytes / {expected_digest}, "
                f"got {actual_size} bytes / {actual_digest}",
                path=str(self.target),
            )

    # -- unwinding ---------------------------------------------------------- #

    def _discard(self) -> None:
        """Close and remove the temp. Never touches the destination."""
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.close()
            except OSError:  # pragma: no cover - close after a partial failure
                pass
        temp, self._temp_path = self._temp_path, None
        if temp is not None:
            self._unlink_quietly(temp)

    @staticmethod
    def _unlink_quietly(path: Path) -> None:
        try:
            os.unlink(path)
        except OSError:  # pragma: no cover - already gone
            pass

    def _warn(self, message: str) -> None:
        self.warnings.append(message)
        self._warn_sink(message)
