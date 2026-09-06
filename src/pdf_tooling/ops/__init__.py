"""L2. Ops — the verbs, expressed as pure functions over ports.

Framework-free: no module in this package may import ``typer`` or ``click``
(asserted by an import-boundary test). An op takes a plan and a resolved port
set, returns a result, and never calls ``sys.exit`` and never prints.

This package is intentionally empty at this point in the build order. The
page-range grammar and the per-verb modules are added by later specs, which
extend this stated contract rather than making a fresh directory decision.
"""
