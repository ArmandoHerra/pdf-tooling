"""L5. Adapters — the ONLY modules that import an engine library or spawn a process.

This restriction is what makes the licensing guarantee auditable: the question
"is anything AGPL/GPL/LGPL reachable?" is answered by reading this package, not
the whole tree. The forbidden list is absolute — never an import, never an
extra, and never a ``subprocess`` fallback.

This package is intentionally empty at this point in the build order.
"""
