"""``SafetyPolicy`` — the only representation of the safety flags below L1.

Constructed once, at the CLI boundary, from the global flags; threaded down from
there. An op can therefore never read a flag it was not handed, and the set of
things that influence a write is enumerable by reading this one class.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SafetyPolicy:
    """The resolved safety posture for one invocation.

    Attributes:
        dry_run: Plan and report; write nothing. The gate that enforces this
            lives in the write chokepoint, not in each verb.
        force: Permit overwriting an existing output.
        in_place: Mutate the input rather than producing a new file.
        backup: Write a ``.bak`` sidecar before an in-place mutation. This is
            the inverse of ``--no-backup``, resolved once here so no caller has
            to remember the negation.
        assume_yes: Skip confirmation. Required for bulk destructive runs on a
            non-TTY.
        is_tty: Whether the process is attached to an interactive terminal.
        threads: Worker cap for multi-file operations.
    """

    dry_run: bool
    force: bool
    in_place: bool
    backup: bool
    assume_yes: bool
    is_tty: bool
    threads: int

    def to_dict(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "force": self.force,
            "in_place": self.in_place,
            "backup": self.backup,
            "assume_yes": self.assume_yes,
            "is_tty": self.is_tty,
            "threads": self.threads,
        }
