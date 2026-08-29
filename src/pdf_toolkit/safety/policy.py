"""``SafetyPolicy`` — the only representation of the safety flags below L1.

Constructed once, at the CLI boundary, from the global flags; threaded down from
there. An op can therefore never read a flag it was not handed, and the set of
things that influence a write is enumerable by reading this one class.
"""

from __future__ import annotations

from dataclasses import dataclass

from pdf_toolkit.errors import BackupWithoutInPlaceError


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

    def validate(self) -> None:
        """Reject the flag combinations the policy itself owns. Exit 2.

        There is exactly one today, and it lives here rather than in the CLI so
        that the rule travels with the data: any construction of a policy — a
        test, a future embedding, the CLI — gets the same answer, and the CLI
        layer delegates instead of keeping a second copy that can drift.

        ``--no-backup`` without ``--in-place`` is deliberately a **usage** error
        (exit 2) and not a safety refusal (exit 5). ``PLAN.md`` §4.2 and §5.6
        disagree on paper; §5.6's exit-2 row names "mutually exclusive flags",
        which is precisely what this is, and nothing has been attempted yet.
        Suppressing a backup that was never going to be taken is a mistake about
        the invocation, not a gate declining over a resolved destination.

        ``backup`` is already the resolved inverse of ``--no-backup``, so the
        rule reads off the two fields directly and no eighth field is added.
        """
        if not self.backup and not self.in_place:
            raise BackupWithoutInPlaceError("--no-backup requires --in-place")

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
