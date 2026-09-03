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

Under ``--dry-run`` the gate PREDICTS, and never prompts (OR-7, B-093)
-----------------------------------------------------------------------
Operator ruling **OR-7** makes ``--dry-run`` mirror the exit code the real run
would produce, and PDF-15 §D12.2 lists *"bulk-destructive, non-TTY, no ``-y``"*
as **knowable at plan time**: nothing has to be attempted to know that this gate
refuses, so a dry run predicts **5** exactly as the real run exits **5**.

Until B-093 every one of the fifteen CLI call sites guarded this function with
``if not config.dry_run and …``, so a dry run skipped the gate entirely and
exited **0** where the real run exited **5** — ``cmd --dry-run && cmd`` green-lit
a run that then refused. The rule now lives **here**, in the one shared check
every call site already funnels through, rather than in fifteen guards a
sixteenth verb would have to rediscover; ``tests/test_import_boundaries.py``
Section 4 asserts, against the AST rather than a comment, that no
``cli/cmd_*.py`` module re-introduces such a guard.

*Corrected by PDF-30 (`b408baff4a`). This paragraph named the CLI-spine module*
``test_cli_spine.py`` *instead, which exists and holds* **zero**
``require_confirmation`` *references — so an existence-only check would have
passed it. A pointer that sends the next reader somewhere nothing is wrong is
worse than no pointer, and*
``tests/test_docstring_pointers.py::test_the_resolver_is_red_on_the_pre_fix_confirm_pointer``
*is where that pre-fix pair is kept as this guard's named red.*

**This is the only correct home for it.** The gate's own inputs — the resolved
input count, and which targets already exist — are verb-specific, so the check
cannot move up into ``cli/common.py::validate_config`` beside its OR-3 siblings;
and it must not, because *precedence* would then be wrong. ``validate_config``
runs before a verb has rejected a missing input (exit 4) or an impossible arity
(exit 2), whereas the real run reaches this gate after both. Leaving the check
where every verb already calls it keeps the dry run refusing at exactly the tier
the real run refuses at first, which is the whole of what OR-7 asks for.

**On a TTY, a dry run neither prompts nor refuses.** There the real run asks a
human, and how that human answers is not a fact about the invocation — it is
D12.2's carve-out shape ("a preview predicts *resolvability*, never
*correctness*"), the same one a wrong password takes. Reading stdin under
``--dry-run`` would also break the non-negotiable purity rule (``CLAUDE.md``
rule 2): a preview that blocks on an answer is exactly the outage the non-TTY
branch above exists to prevent.
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

    Under ``policy.dry_run`` this is a **prediction**: the non-TTY refusal is
    raised exactly as it would be for real (OR-7 — ``dry == real == 5``), and
    the interactive branch below is never reached, so no stdin is read, nothing
    is written and nothing can block. See this module's own docstring for why
    the rule lives here and not in ``cli/common.py``.
    """
    bulk = input_count > 1
    destructive = in_place or bool(clobbered)
    if not (bulk and destructive) or policy.assume_yes:
        return

    if not policy.is_tty:
        # Raised under `--dry-run` TOO, and deliberately with the identical
        # payload: OR-7 asks for the exit code the real run would produce, and
        # the closest landed sibling -- B-096's engine tier -- answers the same
        # way, with the top-level error envelope rather than a synthesized plan
        # item (`tests/integration/test_or7_engine_absent.py` asserts dry and
        # real carry the SAME error object). `would_exit` belongs to the
        # FILESYSTEM tier, which is planned inside `ops/`; this gate fires in
        # the CLI layer above any plan, so manufacturing an item here would be
        # a second refusal-reporting mechanism, not a reuse of the existing one.
        raise ConfirmationRequiredError(
            f"refusing a destructive run on {input_count} inputs without confirmation "
            f"(stdin is not a terminal)\n"
            f"hint: re-run with -y to confirm:\n"
            f"  {rerun_hint}"
        )

    # A TTY, no `-y`: the real run asks a human. That answer is not a fact this
    # invocation carries, so a dry run declines to guess it -- D12.2's carve-out
    # -- and above all does not read the stdin a preview must leave alone.
    if policy.dry_run:
        return

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
