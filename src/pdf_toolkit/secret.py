"""``Secret`` — a password-shaped value that cannot be printed.

Root level on purpose (`PLAN.md` §5.1): L1 (``cli``), L2 (``ops``), L5
(``adapters``) and L6 (``output``) all need to name this type, and a home
inside any one of them would invert the layering for the other three. Not
named ``secrets.py`` — shadowing a stdlib module name inside the package is a
needless confusion in exactly the file where confusion is most expensive.

Why a type rather than a discipline
-----------------------------------
Every leak path in `PLAN.md` §5.7's threat model is **repr-driven**: log
formatting (``%s`` interpolation and ``logging``'s own lazy formatting), the
JSON encoder, ``traceback``'s locals-capturing formatter, and f-strings. A
value that cannot be rendered cannot travel down any of them, which is why
:meth:`__repr__` / :meth:`__str__` / :meth:`__format__` are the whole
mechanism and the two-line ``repr()`` test is the cheapest test in this spec.

:meth:`reveal` is the single accessor and therefore the single greppable
name. ``tests/test_password_leaks.py`` walks ``src/`` and asserts it is
called in exactly one file — ``adapters/pikepdf_structure.py``, at the point
where the engine demands a ``str``.

**Rejected design, recorded so a later reviewer does not "improve" it back
in**: a process-global registry of live plaintext values that a log filter
substitutes out. It is a set of plaintext passwords living for the whole
process — a new leak surface built to defend against leaks — and it cannot
catch a value that was sliced, partially formatted or escape-encoded on its
way out. Prevention by construction beats scrubbing, and a scrubber's main
product is false confidence. (``output/logging.py`` ships such a registry
from PDF-01; this spec deliberately never registers a password in it. See
that module's own note.)

**No secure-erasure claim.** :meth:`clear` zeroes the buffer, but CPython may
already have copied the value while decoding the file, and swap and core
dumps are outside this process's control. Best-effort, never "wiped".
"""

from __future__ import annotations

import hmac
from typing import Any, Final, NoReturn

__all__ = ["REDACTED", "Secret", "SecretClearedError"]

#: What every rendering of a :class:`Secret` produces, at every verbosity.
REDACTED: Final[str] = "<redacted>"


class SecretClearedError(RuntimeError):
    """:meth:`Secret.reveal` was called after :meth:`Secret.clear`."""


class Secret:
    """One password, held as bytes and rendered as ``"<redacted>"``.

    Args:
        value: The password. ``str`` is encoded UTF-8; ``bytes`` is stored as
            given.
        source: A **safe-to-log** label describing where the value came from —
            ``"file:/home/u/pw.txt"``, ``"stdin"``, ``"env:PDF_TOOLKIT_PASSWORD"``
            or ``"prompt"``. This is the only thing about a secret that is ever
            rendered into a plan, a log record or structured output.
    """

    __slots__ = ("_buffer", "_cleared", "source")

    def __init__(self, value: str | bytes, *, source: str) -> None:
        raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        self._buffer = bytearray(raw)
        self._cleared = False
        self.source = source

    # -- rendering: the whole mechanism ------------------------------------ #

    def __repr__(self) -> str:
        return REDACTED

    def __str__(self) -> str:
        return REDACTED

    def __format__(self, format_spec: str) -> str:
        # Deliberately ignores the spec: `f"{secret:>40}"` must not be able to
        # pad, truncate or otherwise transform its way toward the value.
        del format_spec
        return REDACTED

    # -- boundaries -------------------------------------------------------- #

    def __reduce__(self) -> NoReturn:
        """Pickle is refused: a secret never crosses a process boundary."""
        raise TypeError("a Secret is not picklable: it must not cross a process boundary")

    def __eq__(self, other: object) -> Any:
        if not isinstance(other, Secret):
            return NotImplemented
        if self._cleared or other._cleared:
            return False
        return hmac.compare_digest(bytes(self._buffer), bytes(other._buffer))

    #: Defining ``__eq__`` already sets this to ``None``; stated explicitly so
    #: the property is a decision rather than a side effect. An unhashable
    #: secret cannot end up as a dict key or inside a ``set`` that some later
    #: diagnostic decides to print.
    __hash__ = None  # type: ignore[assignment]

    def __len__(self) -> int:
        """Deliberately absent as a *reported* fact: this exists only so that
        ``if secret:`` works. ``len()`` on a password is a real, if small,
        leak, and nothing in this product ever logs it — see
        ``tests/test_password_leaks.py``'s length assertion."""
        return len(self._buffer)

    # -- the one accessor -------------------------------------------------- #

    def reveal(self) -> str:
        """The plaintext, as ``str``.

        The **only** accessor and the only greppable name. Confined by an
        allowlist walk to ``adapters/pikepdf_structure.py``.
        """
        if self._cleared:
            raise SecretClearedError("this Secret was cleared; its value is no longer available")
        return self._buffer.decode("utf-8")

    def clear(self) -> None:
        """Zero the buffer. Best-effort, never a secure-erasure claim."""
        for index in range(len(self._buffer)):
            self._buffer[index] = 0
        self._buffer = bytearray()
        self._cleared = True

    @property
    def cleared(self) -> bool:
        return self._cleared
