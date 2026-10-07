"""PDF-119 D2 -- the ONE ratification register for every scalar ceiling.

A DATA MODULE, not a test module (the `tests/seams.py` pattern: importing it from
a test module is not the `B-308` cross-test-module coupling).

Before this module, each scalar ceiling in the suite was a free-standing literal
beside the arm that read it, and RAISING it was a one-character edit with the
suite green (`1a6408b873`, `B-398`). Now a census binding gets its value ONLY
from :func:`ceiling`, so it has no literal left to raise:

* an in-place edit of a landed record is a red of `tests/test_ratchet_integrity.py`
  (git is the oracle: a landed record is immutable);
* appending an unruled `up` record is a red of the register verifier;
* re-binding a literal in a census module is a red of the binding arm.

The only green path upward is a NEW record, `direction="up"`, with a PM ruling id
and the key named in its reason: the reviewed act. The only way a count that
fell is recorded is a `down` record, and the exact arms (D3) make slack a red.

Keys are ``"<tests-relative path>::<NAME>"``. A value is an int, or a sorted
tuple of names for the two ``SWEEP_2_*`` set ceilings.

RE-MEASURING. Every figure below is measured at LANDING, by one command:

    uv run python tests/ratchet.py remeasure
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, NamedTuple


class _CeilingRatification(NamedTuple):
    """One recorded movement of the scalar-ceiling register (the read-seam shape)."""

    date: str
    spec: str
    #: "genesis" | "down" | "up"
    direction: str
    ceilings: Mapping[str, int | tuple[str, ...]]
    reason: str
    #: The PM ruling id authorising an UPWARD movement of any key.
    ruling: str = ""


CEILING_LEDGER: Final[tuple[_CeilingRatification, ...]] = (
    _CeilingRatification(
        date="2026-10-07",
        spec="PDF-119",
        direction="genesis",
        ruling="X-1006",
        ceilings=MappingProxyType(
            {
                "test_coverage_policy.py::PRAGMA_CEILING": 46,
                "test_docstring_pointers.py::UNTARGETED_CEILING": 35,
                "test_gate_budget.py::TIMEOUT_CEILING": 30,
                "test_import_boundaries.py::HELP_MODULE_CEILING": 320,
                "test_import_boundaries.py::MODULE_SELF_RATIO_CEILING_PER_MILLE": 470,
                "test_import_boundaries.py::PRODUCT_IMPORT_RATIO_CEILING_PER_MILLE": 2600,
                "test_import_boundaries.py::STARTUP_COST_RATIO_CEILING_PER_MILLE": 26500,
                "test_read_seams.py::BOUNDARY_SITE_CEILING": 12,
                "test_read_seams.py::METADATA_POPULATION_CEILING": 54,
                "test_secret_leak_sweeps.py::SWEEP_1_CEILING": 79,
                "test_secret_leak_sweeps.py::SWEEP_2_DEAD_BUT_HONEST_CEILING": (),
                "test_secret_leak_sweeps.py::SWEEP_2_GENUINE_CEILING": (
                    "src/pdf_tooling/ops/merge.py::BOOKMARK_MODES",
                    "src/pdf_tooling/ops/metadata.py::CLEARABLE_FIELDS",
                    "src/pdf_tooling/ops/metadata.py::SETTABLE_FIELDS",
                ),
            }
        ),
        reason=(
            "GENESIS (X-1006). Every scalar ceiling in the suite, each at the value it "
            "held as a free-standing literal at PDF-119's landing; nothing moves. The "
            "census is DERIVED (tests/ratchet.py::census), never listed by hand. ONE "
            "historical movement had no record and no ruling and is recorded here rather "
            "than laundered by this genesis: "
            "test_read_seams.py::METADATA_POPULATION_CEILING rose 73 -> 75 at 5afea7f "
            "([PDF-38] fix), by the two zero-argument `.exists()` probes in "
            "safety/paths.py::ensure_backup_sidecar_free. No scalar ceiling has ever "
            "moved down. ONE SLACK is recorded rather than hidden: the same "
            "test_read_seams.py::METADATA_POPULATION_CEILING was a free-standing literal "
            "of 75 while the measured scoped population (seams.metadata_sites) is 54, i.e. "
            "21 of silent headroom that a later unrecorded rise could have spent; this "
            "genesis records the MEASURED 54 so the exact arm (D3) holds, and that fall "
            "from the old literal is the only value here that differs from the "
            "pre-register source. EXACT classes (D3: slack is a red): PRAGMA_CEILING, "
            "UNTARGETED_CEILING, METADATA_POPULATION_CEILING, BOUNDARY_SITE_CEILING, "
            "SWEEP_1_CEILING and both SWEEP_2_* sets. ONE-SIDED classes (budgets with "
            "designed headroom, host- and load-dependent): TIMEOUT_CEILING, "
            "HELP_MODULE_CEILING and the three *_RATIO_CEILING_PER_MILLE."
        ),
    ),
)


def ceiling(key: str) -> int | tuple[str, ...]:
    """The newest register value for *key* -- the ONLY way a census binding gets one."""
    try:
        return CEILING_LEDGER[-1].ceilings[key]
    except KeyError:
        raise KeyError(
            f"{key!r} is not a key of the newest ceiling-register record; a census ceiling "
            f"needs a register entry (tests/ceiling_register.py)"
        ) from None
