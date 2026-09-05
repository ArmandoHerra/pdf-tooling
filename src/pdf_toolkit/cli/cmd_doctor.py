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
the ``-o json`` top-level key is ``ports``. It stays ``ports``, verbatim and
first, and PDF-39's X-410 frame forbids renaming it.

``items`` IS NOW SUPPLIED TO ``-o json`` TOO — A DECISION REVERSED ON THE
RECORD (PDF-39 D4). This module used to argue that ``items`` belonged only in
the payload handed to the NDJSON and table renderers, and that ``-o json``
should carry *"``ports`` and nothing redundant"*. That judgement was
reasonable and is overturned: the cost it avoided was one duplicated key; the
cost it imposed was **three spellings of one concept across a single
`schema_version: 1` public envelope** — ``items`` on the ``OperationResult``
verbs, ``documents`` on ``info``, ``ports`` here — with no published mapping,
which a consumer pointing one ``jq`` expression at two verbs discovers the
hard way. One redundant key is cheaper than a translation table every
consumer writes for itself. ``ports`` and ``items`` are **the same list**, and
a test asserts the equality so the two can never drift into meaning different
things.

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
    rows = [report.to_dict() for report in reports]
    strays = (
        [str(path) for path in find_stray_temps(Path.cwd() if root is None else root)]
        if strict
        else []
    )
    unavailable = [row["port"] for row in rows if not row["available"]]
    payload: dict[str, Any] = {
        "verb": VERB,
        # Immediately after `verb`: the envelope reads
        # {schema_version, verb, dry_run, strict, ports, items, warnings,
        # duration_ms, exit_code}. ADDITIVE at schema_version 1 -- a key
        # added, never renamed or renumbered. PDF-39 added the last four
        # under that rule, which this comment already authorised.
        "dry_run": dry_run,
        "strict": strict,
        "ports": rows,
        # PDF-39 D4: the universal collection key, the SAME list as `ports`.
        # `ports` stays primary and first; `items` is the alias every other
        # verb's collection already answers to.
        "items": rows,
        # PDF-39 D2: mirrors what this verb actually warns about, so the
        # envelope cannot claim silence while the process printed a warning.
        # `doctor_command` logs exactly these lines to stderr. `[]` when there
        # are none -- never null, never omitted.
        "warnings": [f"stray toolkit temp file: {stray}" for stray in strays],
        # PDF-39 D2 -- `0`, chosen and reasoned rather than defaulted.
        # `cmd_version.py`'s own `duration_ms=0` comment is the precedent and
        # the reasoning is the same one: engine resolution is a property of
        # the HOST, not of this run, and a real wall-clock reading would make
        # two otherwise identical `doctor -o json` invocations differ
        # byte-for-byte for no informational gain -- on the one verb whose
        # published promise is that a consumer gets the same shape on every
        # machine.
        "duration_ms": 0,
        # PDF-39 D2/AC6: the code the process will exit with, for the run this
        # envelope describes -- 3 (ENGINE_MISSING) under `--strict` with any
        # port unavailable, else 0. DERIVED HERE INDEPENDENTLY of the `Exit`
        # `doctor_command` raises, deliberately: a payload that simply echoed
        # the number the process was handed would be a `B-080` tautology, and
        # the test that compares the envelope against the real process's exit
        # status could never fail.
        "exit_code": ENGINE_MISSING if (strict and unavailable) else OK,
    }
    if strict:
        payload["stray_temp_files"] = strays
    return payload


def _render(payload: dict[str, Any], fmt: OutputFormat) -> str:
    """Render through PDF-01's renderers, unmodified.

    **PDF-39 D4 removed this function's format branch, and the removal is the
    change.** ``items`` used to be spliced in here for the two renderers that
    stream from it, and kept out of the ``-o json`` branch; it now lives in
    the payload itself (see :func:`build_payload`), so all three renderers
    read the one payload and there is no longer a shape that depends on which
    one asked.
    The NDJSON and table paths receive exactly the list they received before —
    ``payload["items"] is payload["ports"]`` — which is why their existing
    tests pass untouched.
    """
    return render_payload(payload, fmt)


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
