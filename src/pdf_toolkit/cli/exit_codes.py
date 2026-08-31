"""The process exit-code contract.

These integers are PUBLIC API from v1.0.0. They are uniform across every verb.
Renumbering one, or reusing one for a different meaning, is a breaking change
that requires a major version bump and a deprecation window — a mistake here is
not a defect in one verb, it is a defect in all of them.

Adding a code is additive and permitted; changing an existing one is not.
"""

from __future__ import annotations

from typing import Final

#: Success — including an empty-but-valid report. A ``--dry-run`` mirrors the
#: exit code the real run would return, so it is not always 0.
OK: Final[int] = 0

#: The operation ran and failed — corrupt input, engine error, unwritable
#: destination, or one or more inputs failing inside a batch.
FAILURE: Final[int] = 1

#: Bad invocation — unknown flag, mutually exclusive flags, a malformed or
#: out-of-range page range, a missing required argument, or an unknown
#: subcommand *including on a grouping parent*.
USAGE: Final[int] = 2

#: A required engine or system binary is unavailable. The message always
#: carries an install hint.
ENGINE_MISSING: Final[int] = 3

#: Valid invocation, nothing to act on — no path matched, directory empty, or a
#: page selection that resolved to zero pages.
NO_INPUT: Final[int] = 4

#: A safety gate declined: target exists without ``--force``, planned outputs
#: collide, or a bulk destructive run on a non-TTY without ``-y``.
REFUSED: Final[int] = 5

#: Password required and not supplied, supplied and incorrect, or the operation
#: needs the owner password and only the user password was given.
AUTH: Final[int] = 6

#: Every code this contract defines, lowest first. Tests iterate this.
ALL_EXIT_CODES: Final[tuple[int, ...]] = (
    OK,
    FAILURE,
    USAGE,
    ENGINE_MISSING,
    NO_INPUT,
    REFUSED,
    AUTH,
)
