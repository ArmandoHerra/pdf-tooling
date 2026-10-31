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
    _CeilingRatification(
        date="2026-10-26",
        spec="PDF-134",
        direction="up",
        ruling="X-1116",
        ceilings=MappingProxyType(
            {
                "test_coverage_policy.py::PRAGMA_CEILING": 46,
                "test_docstring_pointers.py::UNTARGETED_CEILING": 35,
                "test_gate_budget.py::TIMEOUT_CEILING": 30,
                "test_import_boundaries.py::HELP_MODULE_CEILING": 320,
                "test_import_boundaries.py::MODULE_SELF_RATIO_CEILING_PER_MILLE": 470,
                "test_import_boundaries.py::PRODUCT_IMPORT_RATIO_CEILING_PER_MILLE": 2600,
                "test_import_boundaries.py::STARTUP_COST_RATIO_CEILING_PER_MILLE": 53900,
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
            "PDF-134 (B-461, xref 9a0daae8ee). "
            "test_import_boundaries.py::STARTUP_COST_RATIO_CEILING_PER_MILLE 26500 -> 53900: "
            "the OPERAND moved, not the product (X-946). uv 0.13 dropped the _virtualenv.pth "
            "shim; the CI bare floor fell 36 -> 24 names (3.11), 37 -> 25 (3.12), 39 -> 27 "
            "(3.13) and 39 -> 26 (3.14); re-derived by the recorded procedure, 1.25x the "
            "loaded p95 of the shipped estimator, governing cell linux/3.12 = 43.0476, "
            "measured under uv 0.13.5 on GitHub ubuntu-latest in runs "
            "40329456836/40331924934/40334289707, plant run 40338041719 (f=2.5 median "
            "98.5185 >= 2x loaded max 97.9098). Measured first, derived second, planted "
            "third (X-476). Ruled OR-63 / X-1116, conditional on the plant separation "
            "and the dev-host corroboration passing."
        ),
    ),
    _CeilingRatification(
        date="2026-10-27",
        spec="PDF-150",
        direction="down",
        ruling="X-1167",
        ceilings=MappingProxyType(
            {
                "test_coverage_policy.py::PRAGMA_CEILING": 46,
                "test_docstring_pointers.py::UNTARGETED_CEILING": 35,
                "test_gate_budget.py::TIMEOUT_CEILING": 30,
                "test_import_boundaries.py::HELP_MODULE_CEILING": 320,
                "test_import_boundaries.py::MODULE_SELF_RATIO_CEILING_PER_MILLE": 470,
                "test_import_boundaries.py::PRODUCT_IMPORT_RATIO_CEILING_PER_MILLE": 2600,
                "test_import_boundaries.py::STARTUP_COST_RATIO_CEILING_PER_MILLE": 53900,
                "test_read_seams.py::BOUNDARY_SITE_CEILING": 12,
                "test_read_seams.py::METADATA_POPULATION_CEILING": 54,
                "test_secret_leak_sweeps.py::SWEEP_1_CEILING": 79,
                "test_secret_leak_sweeps.py::SWEEP_2_DEAD_BUT_HONEST_CEILING": (),
                "test_secret_leak_sweeps.py::SWEEP_2_GENUINE_CEILING": (
                    "src/pdf_tooling/ops/merge.py::BOOKMARK_MODES",
                    "src/pdf_tooling/ops/metadata.py::CLEARABLE_FIELDS",
                ),
            }
        ),
        reason=(
            "PDF-150 (X-1167), B-074 F2 debt paid. "
            "test_secret_leak_sweeps.py::SWEEP_2_GENUINE_CEILING drops "
            "src/pdf_tooling/ops/metadata.py::SETTABLE_FIELDS: the symbol is now read by "
            "tests/integration/test_pdf150_meta_set_unencodable_value.py::"
            "test_ac1_population_is_derived, which derives the CLI population of `meta set` "
            "against it, so the sweep no longer finds it unread. Nothing else moves and "
            "nothing rises. Re-measured at landing with "
            "`uv run python tests/ratchet.py remeasure`: disagreements: 0."
        ),
    ),
    _CeilingRatification(
        date="2026-10-29",
        spec="PDF-152",
        direction="down",
        ruling="operator scope ruling 2026-10-29 (orchestrator relay)",
        ceilings=MappingProxyType(
            {
                "test_coverage_policy.py::PRAGMA_CEILING": 46,
                "test_docstring_pointers.py::UNTARGETED_CEILING": 35,
                "test_gate_budget.py::TIMEOUT_CEILING": 30,
                "test_import_boundaries.py::HELP_MODULE_CEILING": 320,
                "test_import_boundaries.py::MODULE_SELF_RATIO_CEILING_PER_MILLE": 470,
                "test_import_boundaries.py::PRODUCT_IMPORT_RATIO_CEILING_PER_MILLE": 2600,
                "test_import_boundaries.py::STARTUP_COST_RATIO_CEILING_PER_MILLE": 53900,
                "test_read_seams.py::BOUNDARY_SITE_CEILING": 12,
                "test_read_seams.py::METADATA_POPULATION_CEILING": 54,
                "test_secret_leak_sweeps.py::SWEEP_1_CEILING": 79,
                "test_secret_leak_sweeps.py::SWEEP_2_DEAD_BUT_HONEST_CEILING": (),
                "test_secret_leak_sweeps.py::SWEEP_2_GENUINE_CEILING": (
                    "src/pdf_tooling/ops/merge.py::BOOKMARK_MODES",
                ),
            }
        ),
        reason=(
            "PDF-152 (operator scope ruling 2026-10-29, orchestrator relay; X-1167 "
            "precedent), B-074 F3 debt paid. "
            "test_secret_leak_sweeps.py::SWEEP_2_GENUINE_CEILING drops "
            "src/pdf_tooling/ops/metadata.py::CLEARABLE_FIELDS: the symbol is now read by "
            "tests/integration/test_pdf152_meta_set_clear_all_refuses_set_flags.py::"
            "test_ac1_population_is_derived, which derives the CLI population of `meta set` "
            "against it, so the sweep no longer finds it unread. Nothing else moves and "
            "nothing rises. Re-measured at landing with "
            "`uv run --no-sync python tests/ratchet.py remeasure`: disagreements: 0."
        ),
    ),
    _CeilingRatification(
        date="2026-10-31",
        spec="PDF-159",
        direction="up",
        ruling="X-1329",
        ceilings=MappingProxyType(
            {
                "test_coverage_policy.py::PRAGMA_CEILING": 46,
                "test_docstring_pointers.py::UNTARGETED_CEILING": 35,
                "test_gate_budget.py::TIMEOUT_CEILING": 30,
                "test_import_boundaries.py::HELP_MODULE_CEILING": 320,
                "test_import_boundaries.py::MODULE_SELF_RATIO_CEILING_PER_MILLE": 470,
                "test_import_boundaries.py::PRODUCT_IMPORT_RATIO_CEILING_PER_MILLE": 2600,
                "test_import_boundaries.py::STARTUP_COST_RATIO_CEILING_PER_MILLE": 53900,
                "test_read_seams.py::BOUNDARY_SITE_CEILING": 13,
                "test_read_seams.py::METADATA_POPULATION_CEILING": 54,
                "test_secret_leak_sweeps.py::SWEEP_1_CEILING": 79,
                "test_secret_leak_sweeps.py::SWEEP_2_DEAD_BUT_HONEST_CEILING": (),
                "test_secret_leak_sweeps.py::SWEEP_2_GENUINE_CEILING": (
                    "src/pdf_tooling/ops/merge.py::BOOKMARK_MODES",
                ),
            }
        ),
        reason=(
            "PDF-159 (X-1329), the dry-run malformed-input prediction. "
            "test_read_seams.py::BOUNDARY_SITE_CEILING rises 12 -> 13: the one new ops->engine "
            "path handoff is ops/document_password.py DryOpenProbe.__call__ "
            "engine.open_document(source, password=None), the pypdf open plus page count the "
            "real watermark/stamp run performs (no bytes-only port method returns a pypdf page "
            "count). PDF-162 binds to DryOpenProbe.page_count. Nothing else moves. "
            "Re-measured at landing with `uv run --no-sync python tests/ratchet.py remeasure`: "
            "disagreements: 0."
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
