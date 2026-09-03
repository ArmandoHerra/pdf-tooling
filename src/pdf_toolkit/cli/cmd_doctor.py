"""The ``doctor`` verb — the discovery path, and the only surface that spawns.

``doctor`` renders the port registry: **exactly six rows, in ``PORTS`` order,
every time**, whatever the host looks like. A missing engine is a row with
``available:false`` and an install hint, never an absent row — a consumer
counting rows must get the same number on every machine, which is what makes
"exactly six" assertable at all and "exactly one flipped" meaningful.

``doctor`` exits **0** even with engines missing; ``doctor --strict`` exits
**3** if any port is unavailable. That is the container/CI smoke check.

THE ENVELOPE KEY IS NOT A FREE CHOICE
-------------------------------------
``PLAN.md`` §3's own usage example is
``pdftoolkit doctor -o json | jq '.ports[] | select(.available == false)'``, so
the ``-o json`` top-level key is ``ports``. The shared NDJSON and table
renderers stream from ``payload["items"]``, which they own; rather than teach a
renderer about ``ports``, this module supplies ``items`` as an alias **only in
the payload handed to those two renderers**. ``-o json`` therefore carries
``ports`` and nothing redundant, and no shared file was modified to achieve it.

STRAY TEMP FILES: REPORT, NEVER SWEEP
-------------------------------------
``--strict`` also lists stray toolkit temp files under the working directory
(``PLAN.md`` §12 R-07). There is no janitor in v1: a stray file is evidence that
a process was killed between temp-create and replace, and evidence that deletes
itself is not evidence. The filename prefix is **not** re-declared here — it is
owned by ``safety/tempnames.py``, which exports ``find_stray_temps()`` for
exactly this caller and whose docstring states the literal may not appear
anywhere else under ``src/``.

**Strays never change the exit code.** Code 3 means ``ENGINE_MISSING``, and a
leftover temp file is not a missing engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from pdf_toolkit.cli.common import get_config, global_options
from pdf_toolkit.cli.exit_codes import ENGINE_MISSING, OK
from pdf_toolkit.output import OutputFormat, render_payload
from pdf_toolkit.output.logging import get_logger
from pdf_toolkit.ports import reset_cache, resolve_all
from pdf_toolkit.safety.tempnames import find_stray_temps

__all__ = ["build_payload", "doctor_command"]

VERB = "doctor"


def build_payload(*, strict: bool, dry_run: bool, root: Path | None = None) -> dict[str, Any]:
    """The canonical ``doctor`` payload.

    ``reset_cache()`` first: the registry memoizes per process, and this verb's
    whole job is to report the state of the machine *now*. A long-lived process
    — or a test that has just changed ``PATH`` — must not be answered from a
    memo taken before the change.

    ``dry_run`` is a REQUIRED keyword rather than a defaulted one (B-038). The
    key was missing from this envelope alone, and it was missing because nothing
    forced a hand-built payload to carry it: every other verb gets it either
    from ``OperationResult.to_dict()`` or by writing it into its own dict. A
    default here would let the next caller silently reproduce the omission.

    **What the key reports is what the USER ASKED FOR, not what the verb did.**
    ``doctor`` behaves identically with and without ``--dry-run``, so "always
    ``false``" is arguable -- and ``version``, which is non-mutating in exactly
    the same way, already settled it the other way (``cmd_version.py`` passes
    ``dry_run=config.dry_run``). That is the only reading under which the field
    means the same thing on every verb in the envelope.
    """
    reset_cache()
    reports = resolve_all()
    payload: dict[str, Any] = {
        "verb": VERB,
        # Immediately after `verb`: the envelope reads
        # {schema_version, verb, dry_run, strict, ports}. ADDITIVE at
        # schema_version 1 -- a key added, never renamed or renumbered.
        "dry_run": dry_run,
        "strict": strict,
        "ports": [report.to_dict() for report in reports],
    }
    if strict:
        base = Path.cwd() if root is None else root
        payload["stray_temp_files"] = [str(path) for path in find_stray_temps(base)]
    return payload


def _render(payload: dict[str, Any], fmt: OutputFormat) -> str:
    """Render through PDF-01's renderers, unmodified.

    The ``items`` alias is added for the two renderers that stream from it and
    withheld from ``-o json``, whose top-level shape is a published contract.
    """
    if fmt is OutputFormat.JSON:
        return render_payload(payload, fmt)
    streamed = {**payload, "items": payload["ports"]}
    return render_payload(streamed, fmt)


@global_options(consumes=())
def doctor_command(
    ctx: typer.Context,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Exit 3 if any port is unavailable, and list stray toolkit temp files.",
        ),
    ] = False,
) -> None:
    """Report which engines resolved, and how.

    REPORTS, NEVER WRITES: this verb writes no files, so -O/--output,
    --out-dir, --name, --in-place, -f/--force and -y/--yes each exit 2.
    """
    config = get_config(ctx)
    payload = build_payload(strict=strict, dry_run=config.dry_run)
    text = _render(payload, config.output_format)
    if text:
        typer.echo(text)

    logger = get_logger(VERB)
    for stray in payload.get("stray_temp_files", []):
        # Reported, never removed. See the module docstring.
        logger.warning("stray toolkit temp file: %s", stray)

    unavailable = [row["port"] for row in payload["ports"] if not row["available"]]
    if strict and unavailable:
        logger.error("unavailable ports: %s", ", ".join(unavailable))
        raise typer.Exit(ENGINE_MISSING)
    raise typer.Exit(OK)
