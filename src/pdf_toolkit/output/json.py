"""The ``-o json`` and ``-o ndjson`` renderers.

Both shapes are PUBLIC API from v1.0.0, versioned by ``schema_version``.

Two rules this module exists to make structural rather than remembered:

1. Everything rendered comes from ``to_dict()`` — never from a dataclass field
   read directly — so the published schema cannot drift from the method a test
   pins.
2. Every NDJSON line carries its own ``schema_version``, so a consumer that
   reads a single streamed line, and never sees the first one, can still
   describe what it is holding.

BOTH INJECTIONS BELOW ARE SHADOWABLE BY THE PAYLOAD, AND THAT IS NOT DEAD CODE
------------------------------------------------------------------------------
``**payload`` is splatted **after** the literal keys in both renderers, so a
payload carrying one of those keys wins. PDF-39 member 3 (`B-201`) traced every
render path rather than inferring from the ones that are easy to see:

* the 23 leaves that render an ``OperationResult`` carry their own
  ``schema_version`` (``models.py``'s ``OperationResult.to_dict``), and so does
  ``meta get`` via ``MetadataReport.to_dict``. On those 24 leaves the injection
  below is **shadowed, value-identically**.
* ``doctor`` and ``info`` render bespoke dicts that carry **no**
  ``schema_version`` at all. On those two leaves :func:`render_json`'s literal
  is the **only** source of the key.

**So deleting the injection as "dead code" would strip ``schema_version`` from
``doctor -o json`` and ``info -o json`` entirely** — a removal of a published
key from a published envelope, forbidden by X-410, and it would land silently
if nothing asserted the key's presence on those two verbs.
``tests/test_envelope_contract.py::test_ac10_doctor_and_info_carry_the_injected_schema_version``
now does, reading the value out of the CLI's real stdout rather than comparing
the constant to itself.

The real hazard is narrower and survives the correction: **one published key,
two injection paths, agreeing today only because both resolve to the one
``models.SCHEMA_VERSION`` definition, with nothing asserting that they agree.**
That agreement is now guarded, and the shadowing mechanism is pinned as a test
rather than left as a surprise.

Note that ``import json`` inside this module resolves to the standard library:
absolute imports are the default, so the module's own name does not shadow it.
"""

from __future__ import annotations

import json
from typing import Any

from pdf_toolkit.models import SCHEMA_VERSION


def render_json(payload: dict[str, Any]) -> str:
    """One object: ``schema_version`` at the top level, then the payload.

    **The injected key does NOT always win, and the old one-line docstring
    read as though it did.** ``**payload`` is splatted after the literal, so a
    payload that carries ``schema_version`` shadows this value — which is what
    happens on 24 of the 26 leaves, value-identically. On the other two,
    ``doctor`` and ``info``, this literal is the ONLY source of the key, so it
    is live and removing it would delete a published key from two published
    envelopes (X-410 forbids it; see the module docstring).
    """
    # PDF-39 D3: NOT dead code. Live on `doctor` and `info`, shadowed
    # value-identically everywhere else. Do not "simplify" it away.
    return json.dumps({"schema_version": SCHEMA_VERSION, **payload}, ensure_ascii=False)


def render_ndjson(payload: dict[str, Any]) -> str:
    """One object per item, one per line, each line self-describing.

    **Three injected fields, all three shadowable by the item.**
    ``schema_version``, ``verb`` and ``dry_run`` are written before
    ``**item``, so an item dict carrying any of the three would silently
    overwrite the envelope-level value on this path. Measured at PDF-39: no
    shipped item shape carries one — ``ItemResult``, ``EngineReport``,
    ``InspectionOutcome`` and the text/tables rows are all clean — so this is
    **a live hazard with no live instance**, which is exactly the condition
    under which the next spec to add an item key would create the first one
    without noticing.
    ``tests/test_envelope_contract.py::test_ac11_no_ndjson_item_shadows_an_envelope_field``
    asserts the absence over every invocable leaf, so the first attempt turns
    a test red.
    """
    items_raw = payload.get("items") or []
    lines: list[str] = []
    for item in items_raw:
        if not isinstance(item, dict):
            continue
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "verb": payload.get("verb"),
            "dry_run": payload.get("dry_run"),
            **item,
        }
        lines.append(json.dumps(record, ensure_ascii=False))
    return "\n".join(lines)


def render_error_json(error: dict[str, Any]) -> str:
    """The structured error shape. Goes to stdout, not stderr — deliberately."""
    return json.dumps({"schema_version": SCHEMA_VERSION, "error": error}, ensure_ascii=False)
