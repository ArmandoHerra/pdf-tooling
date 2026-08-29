"""The confirmation gate — and the posture that makes it a safety feature.

A destructive run over many files is the one operation where an unattended
process should stop and ask. The rule (``PLAN.md`` §5.3):

* **bulk** means more than one input;
* **destructive** means ``--in-place``, or at least one output that would
  clobber an existing file;
* bulk **and** destructive, without ``-y``:

  * on a terminal — prompt, defaulting to **No**. Declining is exit 5.
  * not on a terminal — **exit 5 immediately.** Never prompt, never read stdin.

Everything else proceeds without a prompt. A single-input run never refuses on
this ground, and neither does a create-only run, however large; both negatives
are asserted, because a gate that fires when it should not is a gate people
route around with ``-y`` in a shell profile, and then it protects nobody.

The non-TTY branch is the load-bearing one. A tool that prompts inside a cron
job hangs a pipeline until a timeout somewhere unrelated fires, and the operator
sees "stuck", not "declined". Failing closed and immediately is the difference
between a refusal and an outage. "Must not hang" is therefore tested with a real
subprocess, a never-written stdin pipe and a hard timeout, not asserted in prose.

``rerun_hint`` is passed **in**. This module never reads ``sys.argv``: it stays a
pure function of its arguments, which is what lets the CLI decide how to spell a
command that a user can paste back. It also keeps ``SafetyPolicy`` at the seven
fields ``PLAN.md`` §6 pins — the hint is an argument, not a new field.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from pdf_toolkit.errors import ConfirmationDeclinedError, ConfirmationRequiredError
from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = ["require_confirmation"]

#: Answers that mean yes. Everything else, including empty input, means no —
#: the prompt defaults to No because the expensive mistake is the other way.
_AFFIRMATIVE = frozenset({"y", "yes"})


def require_confirmation(
    policy: SafetyPolicy,
    *,
    input_count: int,
    clobbered: Sequence[str] = (),
    in_place: bool = False,
    rerun_hint: str,
    stream: TextIO | None = None,
    reader: TextIO | None = None,
) -> None:
    """Refuse (exit 5) a bulk destructive run that nobody confirmed.

    Args:
        policy: The resolved safety posture. ``assume_yes`` and ``is_tty`` are
            the two fields consulted.
        input_count: How many inputs the plan resolved to.
        clobbered: The existing files this run would overwrite, as written.
        in_place: Whether the run mutates its inputs.
        rerun_hint: The exact command to re-run, already ending in ``-y``.
        stream: Where the prompt is written. Defaults to stderr — stdout is the
            payload, and a prompt on stdout would corrupt a piped run.
        reader: Where the answer is read from. Defaults to stdin.

    Returns without doing anything at all unless the run is both bulk and
    destructive and ``-y`` was not given.
    """
    bulk = input_count > 1
    destructive = in_place or bool(clobbered)
    if not (bulk and destructive) or policy.assume_yes:
        return

    if not policy.is_tty:
        raise ConfirmationRequiredError(
            f"refusing a destructive run on {input_count} inputs without confirmation "
            f"(stdin is not a terminal)\n"
            f"hint: re-run with -y to confirm:\n"
            f"  {rerun_hint}"
        )

    out = stream if stream is not None else sys.stderr
    what = "in place" if in_place else f"over {len(clobbered)} existing file(s)"
    print(f"About to run destructively on {input_count} inputs {what}.", file=out)
    print("Continue? [y/N] ", end="", file=out, flush=True)

    source = reader if reader is not None else sys.stdin
    answer = source.readline().strip().lower()
    if answer not in _AFFIRMATIVE:
        raise ConfirmationDeclinedError(
            f"declined at the confirmation prompt; nothing was written\n"
            f"hint: re-run with -y to skip the prompt:\n"
            f"  {rerun_hint}"
        )
