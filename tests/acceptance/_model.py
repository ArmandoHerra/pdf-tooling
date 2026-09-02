"""The ONE shared file of `AUDIT-CONVENTION(PDF-17)`. Frozen at landing.

A dependent spec that appears to need a new :class:`RedKind` member reports a
**BLOCKER to the PM** rather than editing this file (Design §9.2): widening a
shared enum mid-cycle is how the shared-anchor race returns through the back
door.

`NOT_OBSERVED` is the load-bearing member. An acceptance criterion with no
covering test is a FINDING, not a gap to be quietly filled with a passing
assertion (`0615feae63` is the precedent — `PDF-09`'s AC18 was *unmeasured*,
not unmet). The model makes "unmeasured" representable and **mandatory to
declare**, so the cheapest way to record an unmeasured AC is the honest one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RedKind(StrEnum):
    """How the control covering one acceptance criterion was observed RED."""

    PLANTED_DEFECT = "planted_defect"
    """`src/` or a test was mutated, the control fired, the mutation was reverted."""

    DELETED_ROW = "deleted_row"
    """A registry/roster row was removed and the anti-lapse guard fired."""

    MUTATED_CONFIG = "mutated_config"
    """A config key was flipped and the gate fired."""

    EXTERNAL_ORACLE = "external_oracle"
    """An out-of-tree oracle disagreed (the HC-1 carve-out, `decision.md` §0.7)."""

    NOT_OBSERVED = "not_observed"
    """The control was NOT seen red. **Requires** a `finding`."""


#: Values that are not evidence. A `red` field reading any of these — or
#: containing the phrase this product's own brief rules out in terms — is a
#: claim, not a red (Design §9.5 rule 5).
PLACEHOLDER_REDS: frozenset[str] = frozenset({"", "-", "n/a", "na", "todo", "tbd", "none", "?"})

#: Substrings that mean the author reasoned about a red instead of observing
#: one. `PDF-17`'s brief: *"Would fail if broken" is not a red.*
PLACEHOLDER_RED_PHRASES: tuple[str, ...] = (
    "would fail if broken",
    "would fail if the",
    "should fail if",
    "will fail if broken",
)


@dataclass(frozen=True, slots=True)
class ACAudit:
    """One acceptance criterion's evidence row."""

    ac: str
    """``"AC14"`` — the criterion id, contiguous from ``AC1`` within a module."""

    claim: str
    """The AC's own text, quoted, so a reader need not open the audited spec."""

    covering: tuple[str, ...]
    """pytest node ids, copy-pasted from a real ``--collect-only`` run. May be
    ``()`` **only** together with a `finding`."""

    red: str
    """What was changed, what failed, and what the failure message said."""

    red_kind: RedKind

    finding: str | None = None
    """A ledger fingerprint or ``B-NNN``. **Required** when `covering` is empty
    or `red_kind` is :attr:`RedKind.NOT_OBSERVED`."""
