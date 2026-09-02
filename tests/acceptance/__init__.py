"""`AUDIT-CONVENTION(PDF-17)` — per-acceptance-criterion control audits.

One module per **audited** spec (`audit_pdf_06.py` audits `PDF-06`), discovered
by glob from `tests/test_acceptance_audit.py`. A module has exactly one writer,
ever, so six specs landing in five waves cannot race on a shared anchor line —
the topology `decision.md` §2 predicted would produce a silent lost write.

The rules a dependent spec's engineer follows live in `PDF-17`'s Design §9.5.
The one shared file is :mod:`tests.acceptance._model`; it is frozen at landing
and widening it is a BLOCKER to the PM, not an edit.
"""
