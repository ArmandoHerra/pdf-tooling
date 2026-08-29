"""A crash rendezvous: env-gated, inert by default, and the reason the atomic
write guarantee is *demonstrated* rather than asserted.

Testing "a hard kill mid-write leaves the original intact" honestly requires two
things that are usually faked: a **real** ``SIGKILL``, and a process provably
parked at a named point when it arrives. A mock proves the mock. A ``sleep``
proves whatever the scheduler decided that run. So instead:

1. The test creates two pipes and passes their read/write ends down to a child
   process, handing the file-descriptor numbers over in
   ``PDF_TOOLKIT_FAULT_RENDEZVOUS`` as ``"<ready_fd>:<release_fd>"``, with the
   name of the wanted point in ``PDF_TOOLKIT_FAULT_POINT``.
2. :func:`checkpoint` fires at the matching point only. It writes one line to the
   *ready* descriptor — carrying an optional detail string, which is how a test
   learns the live temp path without guessing it — and then **blocks reading**
   the *release* descriptor.
3. The child is now parked at that exact point. No sleep, no poll, no race. The
   parent reads the ready line and delivers signal 9, which cannot be caught:
   there is no unwind, no ``finally``, no cleanup. That is the scenario.

**Inherited pipes rather than FIFOs, deliberately.** A FIFO would have to be
created on disk and opened for writing, and "open something for writing" is
precisely the call class the write-chokepoint import-boundary test forbids
outside ``atomic.py``. A rendezvous that needed an allowlist entry would be a
hole cut in the guard for the benefit of the test that proves the guard. Pipes
inherited across ``pass_fds`` need no filesystem object at all, which also keeps
the ``--dry-run`` purity snapshot clean, and ``os.read``/``os.write`` on an
already-open descriptor mutate nothing.

**Inertness is a criterion, not an aspiration.** With no environment variables
set, :func:`checkpoint` is one ``os.environ.get`` and a return: no import, no
descriptor, no filesystem access, and no branch a user can reach. A test asserts
that under the purity snapshot.
"""

from __future__ import annotations

import os
from typing import Final

__all__ = ["ENV_POINT", "ENV_RENDEZVOUS", "FAULT_POINTS", "checkpoint"]

#: Names the point at which the process should park. Unset in every real run.
ENV_POINT: Final[str] = "PDF_TOOLKIT_FAULT_POINT"

#: ``"<ready_fd>:<release_fd>"`` — two inherited pipe descriptors.
ENV_RENDEZVOUS: Final[str] = "PDF_TOOLKIT_FAULT_RENDEZVOUS"

#: Every point the writer offers. All three are necessarily *before* the
#: replace: there is no "during ``os.replace``" to inject into, and that absence
#: is the guarantee rather than a gap in the coverage.
FAULT_POINTS: Final[tuple[str, ...]] = (
    "after_temp_create",
    "after_fsync",
    "after_backup",
)

#: One byte from the parent means "carry on". Closing the pipe means the same,
#: so a parent that crashes cannot wedge a child forever.
_RELEASE_BYTE: Final[bytes] = b"\x01"


def checkpoint(name: str, detail: str = "") -> None:
    """Park at *name* if a test asked for it; otherwise do nothing at all."""
    if os.environ.get(ENV_POINT) != name:
        return
    _park(detail)


def _park(detail: str) -> None:
    """Announce arrival on the ready pipe, then block until released."""
    rendezvous = os.environ.get(ENV_RENDEZVOUS)
    if not rendezvous:
        return
    ready_text, _, release_text = rendezvous.partition(":")
    try:
        ready_fd = int(ready_text)
        release_fd = int(release_text)
    except ValueError:
        return

    os.write(ready_fd, detail.encode("utf-8", "replace") + b"\n")
    while True:
        chunk = os.read(release_fd, 1)
        if chunk in (b"", _RELEASE_BYTE):
            return
