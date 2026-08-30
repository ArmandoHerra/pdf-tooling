"""L3. Safety — the single write chokepoint.

Inputs are immutable by default, and that is a structural property rather than a
promise. Every mutating path in the product funnels through
:class:`~pdf_toolkit.safety.atomic.AtomicWriter`: the dry-run gate, no-clobber
planning, the temp file beside the destination, ``fsync``, ``os.replace``, and
the ``--in-place`` sidecar all live inside it. An import-boundary test walks the
AST of every file under ``src/`` and fails when any module outside this package
performs a filesystem mutation — and inside this package, when the mutation is
anywhere but ``atomic.py``. The chokepoint is one *file*, not one package.

What lives here, and why each piece is separate:

* ``policy`` — :class:`SafetyPolicy`, the resolved posture for one invocation,
  and the flag-combination rules the policy itself owns.
* ``atomic`` — the writer. **The only module in the product that writes.**
* ``paths`` — identity across aliases, containment, and the read-only planning
  refusals (no-clobber, planned-output collision, destination writability).
  Comparison keys only: what gets *printed* is always the path as the user
  wrote it.
* ``tempnames`` — the temp namespace, and ``find_stray_temps()``, which reports
  crash residue and never removes it (``PLAN.md`` §12 R-07).
* ``confirm`` — the bulk-destructive confirmation gate, which fails closed and
  immediately when stdin is not a terminal.
* ``_faults`` — an env-gated rendezvous, inert in every real run, that lets a
  test park the process at a named point and deliver a real signal there.

**Destination ownership is the rule that covers what an AST walk cannot see.**
No module outside this package may *choose* a destination path. Adapters and
engines receive the path they are told to write to; ``AtomicWriter`` is the only
thing that decides what that path is. That is what makes "the engine wrote
somewhere unexpected" impossible to express, and the ``--dry-run`` purity
snapshot is the empirical backstop for the rest.
"""

from pdf_toolkit.safety.atomic import DEGRADED_PREFIX, AtomicWriter, ensure_out_dir
from pdf_toolkit.safety.confirm import require_confirmation
from pdf_toolkit.safety.paths import (
    canonical,
    check_output_collisions,
    ensure_destination_writable,
    ensure_no_clobber,
    ensure_within,
    identity_key,
    same_destination,
    target_exists,
)
from pdf_toolkit.safety.policy import SafetyPolicy
from pdf_toolkit.safety.tempnames import TEMP_PREFIX, find_stray_temps, is_toolkit_temp

__all__ = [
    "DEGRADED_PREFIX",
    "TEMP_PREFIX",
    "AtomicWriter",
    "SafetyPolicy",
    "canonical",
    "check_output_collisions",
    "ensure_destination_writable",
    "ensure_no_clobber",
    "ensure_out_dir",
    "ensure_within",
    "find_stray_temps",
    "identity_key",
    "is_toolkit_temp",
    "require_confirmation",
    "same_destination",
    "target_exists",
]
