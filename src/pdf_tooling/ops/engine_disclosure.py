"""PDF-67 -- the one place a preview states it did not run the engine.

`README.md`'s exit-code table carries ONE carve-out on the code-``0`` row:
an operand whose acceptability is decided by an out-of-process engine at
load time. This module is the PAYLOAD half of that carve-out, and
``README.md``'s sentence is the prose half; neither ships without the other.

WHY THE PAYLOAD AND NOT PROSE ALONE. A machine consumer -- the party
``README.md``'s public-API freeze exists *for* -- reads ``exit_code: 0`` and
``ok: true`` off a dry run and has nothing else to go on. The
``ops/document_password.py::password_detail`` precedent (``d01c9d52fb`` /
PDF-52) states the doctrine this module copies, in its own words: *"Stating
that in the payload is what keeps the preview from reading like success."*

WHAT IT DOES NOT COVER, AND THIS BOUNDARY IS A RULING RATHER THAN A TASTE.
The product carries a SECOND dry/real divergence -- a resolvable-but-wrong
password predicts ``0`` where the real run exits ``6`` -- carved out on
entirely different grounds (``X-89``'s oracle limit, stated in shipped
source at ``ops/crypto.py``: *"A preview must not become an oracle"*). That
one is about a secret this product deliberately declines to read; this one
is about an out-of-process engine's verdict on an operand. The two are kept
apart structurally as well as textually: the verbs emitting
:func:`password_detail` and the verbs emitting :func:`engine_detail` are
DISJOINT populations, and
``tests/test_cli_contract.py::test_c26_the_population_is_derived_from_the_import_graph``
derives this one from the import graph so it cannot quietly grow into the
other.

NO NEW IMPORT EDGE. This module imports nothing from ``ports/`` and nothing
from ``adapters/`` -- only the shared data model -- so adding it to
``ops/office.py`` and ``ops/ocr.py`` moves no edge
``tests/registry.py::is_mutating`` did not already have, which is the
identical constraint ``password_detail``'s own docstring records having
reasoned about. There is ONE constructor and ONE key constant here; no verb
repeats the literal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Final

from pdf_tooling.models import ItemResult

__all__ = ["ENGINE_VERIFIED_KEY", "disclose_engine_blindness", "engine_detail"]

#: The one spelling of the disclosure key. `README.md` renders this name, and
#: `tests/test_docs_antirot.py::engine_disclosure_key` derives the documented
#: claim FROM this constant rather than from a literal -- so renaming it here
#: without following in `README.md` reddens the doc arm instead of rotting
#: silently.
ENGINE_VERIFIED_KEY: Final[str] = "engine_verified"


def engine_detail(detail: Mapping[str, object] | None) -> dict[str, object]:
    """*detail* plus the honest statement of what the preview did not run.

    ``engine_verified`` is ``False`` for every dry item by construction, in
    exactly the sense ``password_verified`` is: a ``--dry-run`` writes
    nothing anywhere and starts no process, so it never handed the operand
    to ``soffice`` or ``tesseract`` and cannot report their verdict. A
    CONDITIONAL value would have to be conditional on something, and the
    only honest answer is *"the engine, which we did not run"*.

    Emitted from the dry branch only. A real-run ``engine_verified: true``
    would be a payload change on the success path that the carve-out does
    not need, and PDF-67 AC10 pins the real run byte-unchanged.

    Uniform across the item's states -- a clean prediction, a
    filesystem-refused one (``would_exit: 5``) and an item that the
    spawn-free triage or the operand classifier already failed all carry it.
    The claim is about the PREVIEW'S blindness, not about the operand's
    fate, and a key that appears only sometimes is a key a consumer has to
    branch on.

    Returns a COPY and never mutates *detail*: ``ops/office.py`` computes
    ``plan.detail()`` ONCE and hands the same object to every item in the
    batch, so an in-place update here would be a shared-object bug that
    looks like a payload change. ``None`` -- an item that carries no
    ``detail`` at all, which is what ``ops/batch.py::failure_item`` builds
    -- yields the disclosure on its own.
    """
    payload: dict[str, object] = dict(detail or {})
    payload[ENGINE_VERIFIED_KEY] = False
    return payload


def disclose_engine_blindness(items: Sequence[ItemResult]) -> tuple[ItemResult, ...]:
    """*items* with :func:`engine_detail` applied to EVERY row, unconditionally.

    The seam that makes the disclosure uniform rather than nearly uniform.
    Routing only the verb's own predicted rows through :func:`engine_detail`
    reaches the clean and filesystem-refused states and MISSES the rows
    ``ops/batch.py::BatchLedger`` recorded on the way -- a triage refusal, an
    unreadable operand, an auth refusal -- because those are built by
    ``failure_item`` with no ``detail`` at all. Measured at ``20a3dbc``: a
    two-operand ``convert --dry-run`` whose second operand the spawn-free
    triage refuses emits one row carrying ``detail`` and one carrying none.

    Applied AFTER ``BatchLedger.assemble``, so the population is every dry
    item the run will actually render, in input order, whatever produced it.
    Dry branches only -- a real run never calls this.

    Deliberately NOT pushed down into ``ops/batch.py``: ``failure_item`` is
    shared with the real path, and a disclosure emitted there would change
    the real run's payload (PDF-67 AC10) and break the ``dry == real``
    byte-identity PDF-53 established for exactly that row.
    """
    return tuple(replace(item, detail=engine_detail(item.detail)) for item in items)
