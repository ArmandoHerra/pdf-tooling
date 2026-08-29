"""L3. Safety — the single write chokepoint.

Inputs are immutable by default. Every mutating path funnels through this
package: no-clobber planning, the dry-run gate, write-to-temp-on-the-target-
filesystem, ``fsync``, ``os.replace``, and the ``--in-place`` backup sidecar.

At this point in the build order the package carries only ``SafetyPolicy`` —
the data those mechanisms are driven by, constructed once at the CLI boundary
and threaded down so that no op can read a flag it was not handed.
"""

from pdf_toolkit.safety.policy import SafetyPolicy

__all__ = ["SafetyPolicy"]
